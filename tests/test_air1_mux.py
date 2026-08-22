"""Card AIR-1 — the output selector, and the discipline around writing to it.

WHAT THIS FILE IS THE CORRECTION FOR
------------------------------------
AIR-1's first draft asserted that the XVF3800's 2-channel firmware "exposes only
processed beams, so there is no raw microphone to read", and designed a
three-leg differential measurement — with a second loudspeaker and a hand level
match — around that assertion. **It is false.** Each of the two USB capture
channels is a runtime-selectable mux (``AUDIO_MGR_OP_L`` / ``AUDIO_MGR_OP_R``,
resource 35, commands 15 and 19), and its categories include the raw
microphone, the amplified microphone as the canceller receives it, the far-end
reference, and the per-microphone AEC residual. So the same-instant measurement
is available on the firmware already installed.

WHY THE TESTS ARE ABOUT RESTORING, NOT MEASURING
------------------------------------------------
Writing that mux changes what the LIVE capture stream carries. A voice stack
listening on :8765 would start receiving a raw microphone instead of a
beam-formed, echo-cancelled one, and nothing in the audio path would say so.
So the interesting failure here is not a wrong number — it is a routing left
changed. Every test below is about the write being refused, allow-listed, or
put back.

NOTHING HERE TOUCHES HARDWARE. Every control transfer on this host fails with
``Errno 13`` until the owner's udev rule lands, so the wire behaviour is
owner-gated and untested; the encoding, the allow-list and the restore
discipline are tested against a fake device, which is where the risk lives.
"""

from __future__ import annotations

import importlib.util
import struct
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = REPO_ROOT / "tools" / "xvf3800_probe.py"


@pytest.fixture(scope="module")
def probe():
    spec = importlib.util.spec_from_file_location("xvf3800_probe", TOOL_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["xvf3800_probe"] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class FakeDevice:
    """An XVF3800 that remembers its routing and logs every transfer."""

    def __init__(self) -> None:
        self.state: dict[tuple[int, int], list[int]] = {
            (35, 15): [6, 3],   # L: processed beam, auto-select — the shipped default
            (35, 19): [6, 3],   # R: the same
            (17, 10): [1],      # AGC on
        }
        self.floats: dict[tuple[int, int], float] = {(17, 13): 4.0}
        self.transfers: list[tuple[str, int, int]] = []
        self.fail_restore = False

    def ctrl_transfer(self, request_type, _request, value, index, data_or_length, timeout=0):
        command = value & 0x7F
        key = (index, command)
        if request_type == 0xC0:  # IN
            self.transfers.append(("read", index, command))
            if key in self.floats:
                return b"\x00" + struct.pack("<f", self.floats[key])
            values = self.state.get(key, [0, 0])
            if key == (17, 10):
                return b"\x00" + int(values[0]).to_bytes(4, "little", signed=True)
            return b"\x00" + bytes(values)
        self.transfers.append(("write", index, command))
        if self.fail_restore:
            raise OSError("device write refused")
        if key == (17, 10):
            self.state[key] = [int.from_bytes(bytes(data_or_length), "little", signed=True)]
        else:
            self.state[key] = list(bytes(data_or_length))
        return len(data_or_length)


@pytest.fixture
def wired(probe, monkeypatch):
    """An ``XvfControl`` bound to a fake device, writes unlocked."""

    device = FakeDevice()

    def _make(**kwargs):
        control = probe.XvfControl(**kwargs)
        monkeypatch.setattr(control, "_ensure_device", lambda: device)
        return control

    return device, _make


# ================================================================ the reads
def test_the_mux_reads_back_its_routing(probe, wired) -> None:
    _device, make = wired
    control = make()

    assert control.read("AUDIO_MGR_OP_L") == [6, 3]
    assert control.read("AUDIO_MGR_OP_R") == [6, 3]
    assert control.reads_ok == 2


def test_the_agc_state_is_readable(probe, wired) -> None:
    """An AGC that moved between two recordings invalidates a dB difference,
    so its state is evidence and not trivia."""

    _device, make = wired
    control = make()

    assert control.read("PP_AGCONOFF") == [1]
    assert control.read("PP_AGCGAIN") == pytest.approx([4.0])


def test_an_unknown_control_is_refused_rather_than_guessed(probe, wired) -> None:
    _device, make = wired
    with pytest.raises(probe.ProbeError) as caught:
        make().read("SAVE_CONFIGURATION")
    assert "unknown control" in str(caught.value)


# =============================================================== the writes
def test_a_read_only_control_object_refuses_every_write(probe, wired) -> None:
    """The default. Writing the mux changes what a live session hears."""

    device, make = wired
    control = make()  # allow_writes defaults to False

    with pytest.raises(probe.ProbeError) as caught:
        control.write("AUDIO_MGR_OP_L", (3, 0))
    assert "opened read-only" in str(caught.value)
    assert device.state[(35, 15)] == [6, 3]
    assert not any(kind == "write" for kind, _, _ in device.transfers)


def test_only_allow_listed_controls_can_be_written(probe, wired) -> None:
    _device, make = wired
    control = make(allow_writes=True)

    with pytest.raises(probe.ProbeError) as caught:
        control.write("PP_AGCGAIN", (2.0,))
    assert "not on the allow-list" in str(caught.value)


def test_save_configuration_has_no_spelling_at_all(probe) -> None:
    """Nothing this tool does may outlive a power cycle, so the command that
    would persist it is simply not in the table."""

    assert "SAVE_CONFIGURATION" not in probe.XVF_CONTROLS
    assert "SAVE_CONFIGURATION" not in probe.XVF_WRITABLE
    assert probe.XVF_WRITABLE <= set(probe.XVF_CONTROLS)


def test_a_wrong_value_count_is_refused(probe, wired) -> None:
    _device, make = wired
    control = make(allow_writes=True)
    with pytest.raises(probe.ProbeError) as caught:
        control.write("AUDIO_MGR_OP_L", (3,))
    assert "takes 2 value(s)" in str(caught.value)


# ============================================================== the session
def test_the_session_applies_the_pairing_and_puts_it_back(probe, wired) -> None:
    device, make = wired
    control = make(allow_writes=True)

    with control.mux_session(probe.MUX_PAIR_PIPELINE) as session:
        assert session["previous"] == {"AUDIO_MGR_OP_L": [6, 3], "AUDIO_MGR_OP_R": [6, 3]}
        # Inside the session the left channel is the canceller's INPUT.
        assert device.state[(35, 15)] == [probe.MUX_AMPLIFIED_MIC, 0]
        assert device.state[(35, 19)] == [probe.MUX_PROCESSED, 3]

    assert device.state[(35, 15)] == [6, 3]
    assert device.state[(35, 19)] == [6, 3]


def test_the_routing_is_restored_even_when_the_body_raises(probe, wired) -> None:
    """A measurement that crashes must not leave the owner's stack listening to
    a raw microphone."""

    device, make = wired
    control = make(allow_writes=True)

    with pytest.raises(RuntimeError), control.mux_session(probe.MUX_PAIR_PIPELINE):
        raise RuntimeError("the capture failed")

    assert device.state[(35, 15)] == [6, 3]
    assert device.state[(35, 19)] == [6, 3]


def test_a_restore_that_did_not_take_is_loud(probe, wired) -> None:
    """Silence here would be the worst outcome in the whole card: the array
    left mis-routed, and every later recording quietly wrong."""

    device, make = wired
    control = make(allow_writes=True)

    with pytest.raises(probe.ProbeError) as caught, control.mux_session(
        probe.MUX_PAIR_PIPELINE
    ):
        device.fail_restore = True
    message = str(caught.value)
    assert "THE CAPTURE MUX WAS NOT RESTORED" in message
    assert "Power-cycle the array" in message


# =============================================================== the snapshot
def test_the_snapshot_says_the_same_instant_path_is_available(probe, wired) -> None:
    _device, make = wired
    snapshot = probe.mux_snapshot(make())

    assert snapshot["readable"] is True
    assert snapshot["same_instant_available"] is True
    assert snapshot["controls"]["AUDIO_MGR_OP_L"] == [6, 3]


def test_the_snapshot_names_the_permission_error_instead_of_going_quiet(probe) -> None:
    """On this host, today: no pyusb, no udev rule, Errno 13. The probe has to
    say which, because 'unavailable' and 'not granted yet' are different jobs."""

    snapshot = probe.mux_snapshot()

    assert snapshot["readable"] is False
    assert snapshot["same_instant_available"] is False
    assert snapshot["errors"]
    assert "udev" in snapshot["note"]


def test_the_pairing_is_input_versus_output_of_the_canceller(probe) -> None:
    """If this pairing ever becomes two outputs, the number becomes zero and
    would read as a perfect canceller."""

    assert probe.MUX_PAIR_PIPELINE["AUDIO_MGR_OP_L"] == (probe.MUX_AMPLIFIED_MIC, 0)
    assert probe.MUX_PAIR_PIPELINE["AUDIO_MGR_OP_R"] == (probe.MUX_PROCESSED, 3)
    assert probe.MUX_AMPLIFIED_MIC != probe.MUX_PROCESSED
