"""Card AIR-1 — the playback must still be playing when the recording starts.

THE BUG THIS FILE IS ABOUT
--------------------------
``sounddevice``'s ``play()``, ``rec()`` and ``playrec()`` are conveniences over
ONE shared module-level context, and ``_CallbackContext.start_stream`` opens
with ``stop()`` (sounddevice 0.5.5). So this, which reads like the obvious way
to play on one device and record on another:

    sounddevice.play(probe, device=speaker, blocking=False)
    sounddevice.rec(frames, device=array, blocking=True)

stops the playback as its first act and then records the room. The ERLE
``uncancelled`` leg is exactly that shape. The consequence was not a crash and
not an error message: it was an uncancelled leg sitting on the noise floor, an
attenuation figure of roughly zero, and a confident ``fail`` naming a clipped
amplifier that had never been involved.

The fix is explicit ``InputStream``/``OutputStream`` objects, which the shared
context cannot reach. These tests drive ``play_and_record`` with fake stream
classes so the overlap is asserted directly — no device, no PortAudio, no room.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = REPO_ROOT / "tools" / "measure_erle.py"


@pytest.fixture(scope="module")
def erle():
    for name, path in (
        ("xvf3800_probe", REPO_ROOT / "tools" / "xvf3800_probe.py"),
        ("measure_erle", TOOL_PATH),
    ):
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        assert spec.loader is not None
        spec.loader.exec_module(module)
    return sys.modules["measure_erle"]


class _FakeStream:
    """Records its own lifecycle so a test can ask what was open when."""

    def __init__(self, backend, kind, **kwargs) -> None:
        self.backend = backend
        self.kind = kind
        self.kwargs = kwargs
        self.active = False
        self.closed = False
        self.callback = kwargs.get("callback")

    def start(self) -> None:
        self.active = True
        self.backend.events.append(f"{self.kind}.start")
        self.backend.on_start(self)

    def stop(self) -> None:
        self.active = False
        self.backend.events.append(f"{self.kind}.stop")

    def close(self) -> None:
        self.closed = True
        self.backend.events.append(f"{self.kind}.close")


class FakeBackend:
    """A sounddevice stand-in with the real module's fatal habit, optionally."""

    def __init__(self, *, channels: int = 2, module_stop_kills_streams: bool = False) -> None:
        self.events: list[str] = []
        self.streams: list[_FakeStream] = []
        self.channels = channels
        #: The real module-level ``stop()`` reaches only the shared context. Set
        #: this to model a world where it reached explicit Stream objects too.
        self.module_stop_kills_streams = module_stop_kills_streams
        #: What the output stream was doing at the instant the input started.
        self.output_active_when_input_started: bool | None = None

    # -- the explicit Stream classes ---------------------------------------
    def InputStream(self, **kwargs) -> _FakeStream:
        stream = _FakeStream(self, "input", **kwargs)
        self.streams.append(stream)
        return stream

    def OutputStream(self, **kwargs) -> _FakeStream:
        stream = _FakeStream(self, "output", **kwargs)
        self.streams.append(stream)
        return stream

    def on_start(self, stream: _FakeStream) -> None:
        if stream.kind != "input":
            return
        self.output_active_when_input_started = any(
            other.kind == "output" and other.active for other in self.streams
        )
        # Feed the recorder everything it asked for, in one block.
        wanted = int(stream.kwargs.get("channels", self.channels))
        block = np.zeros((self._frames_wanted, wanted), dtype=np.int16)
        if stream.callback is not None:
            stream.callback(block, self._frames_wanted, None, None)

    _frames_wanted = 8_000

    # -- the module-level conveniences -------------------------------------
    def stop(self) -> None:
        self.events.append("module.stop")
        if self.module_stop_kills_streams:
            for stream in self.streams:
                stream.active = False

    def play(self, data, **kwargs) -> None:
        self.stop()  # the real _CallbackContext.start_stream does this first
        self.events.append("module.play")

    def rec(self, frames, **kwargs) -> np.ndarray:
        self.stop()  # ... and so does this one
        self.events.append("module.rec")
        return np.zeros((int(frames), int(kwargs.get("channels", self.channels))), dtype=np.int16)

    def playrec(self, data, **kwargs) -> np.ndarray:
        self.stop()
        self.events.append("module.playrec")
        return np.zeros(
            (data.shape[0], int(kwargs.get("channels", self.channels))), dtype=np.int16
        )


def _probe(erle, seconds: float = 0.5) -> np.ndarray:
    return erle.speech_shaped_probe(seconds)


# ========================================================== the guard itself
def test_the_probe_is_still_playing_when_the_capture_opens(erle) -> None:
    """THE regression. Two devices, and the output must survive the input."""

    backend = FakeBackend()
    probe = _probe(erle)
    backend._frames_wanted = probe.size

    erle.play_and_record(
        probe, capture_device=5, play_device=4, play_rate_hz=48_000, backend=backend,
    )

    assert backend.output_active_when_input_started is True
    assert "output.start" in backend.events
    assert backend.events.index("output.start") < backend.events.index("input.start")
    # And nothing went through the shared module context on this path.
    assert "module.play" not in backend.events
    assert "module.rec" not in backend.events


def test_both_streams_are_closed_afterwards(erle) -> None:
    backend = FakeBackend()
    probe = _probe(erle)
    backend._frames_wanted = probe.size

    erle.play_and_record(
        probe, capture_device=5, play_device=4, play_rate_hz=48_000, backend=backend,
    )

    assert [stream.closed for stream in backend.streams] == [True, True]
    assert backend.events.count("output.close") == 1
    assert backend.events.count("input.close") == 1


def test_a_context_that_stops_explicit_streams_is_caught_not_reported(erle) -> None:
    """If the playback ever did die at capture-open, the leg is refused.

    This is the runtime half of the guard: the tool does not merely avoid the
    bug, it notices the condition and declines to hand back a recording of the
    room labelled as an echo.
    """

    backend = FakeBackend(module_stop_kills_streams=True)
    probe = _probe(erle)
    backend._frames_wanted = probe.size
    # Model the failure directly: the output stream is dead by the time the
    # input starts.
    original = backend.on_start

    def _kill_then_start(stream):
        if stream.kind == "input":
            for other in backend.streams:
                if other.kind == "output":
                    other.active = False
        original(stream)

    backend.on_start = _kill_then_start

    with pytest.raises(erle.ProbeError) as caught:
        erle.play_and_record(
            probe, capture_device=5, play_device=4, play_rate_hz=48_000, backend=backend,
        )
    message = str(caught.value)
    assert "recorded the noise floor" in message
    assert "explicit Stream objects" in message


def test_the_one_device_path_still_uses_the_single_duplex_stream(erle) -> None:
    """``playrec`` is ONE context — a duplex stream, no overlap to lose."""

    backend = FakeBackend()
    probe = _probe(erle)

    erle.play_and_record(
        probe, capture_device=5, play_device=5, play_rate_hz=erle.ARRAY_RATE_HZ,
        backend=backend,
    )

    assert "module.playrec" in backend.events
    assert backend.streams == []


def test_the_floor_leg_never_opens_an_output_at_all(erle) -> None:
    backend = FakeBackend()
    probe = _probe(erle)

    erle.play_and_record(
        probe, capture_device=5, play_device=4, play_rate_hz=48_000,
        silent=True, backend=backend,
    )

    assert "module.rec" in backend.events
    assert not any(stream.kind == "output" for stream in backend.streams)


def test_a_short_capture_is_refused_rather_than_padded(erle) -> None:
    backend = FakeBackend()
    probe = _probe(erle)
    backend._frames_wanted = probe.size // 4  # the device gave up early

    with pytest.raises(erle.ProbeError) as caught:
        erle.play_and_record(
            probe, capture_device=5, play_device=4, play_rate_hz=48_000, backend=backend,
        )
    assert "of" in str(caught.value)
    assert "frames" in str(caught.value)


# =================================== the numerator has to actually be an echo
def _leg(erle, name: str, level: float, *, ref: float | None = None) -> dict:
    leg = {
        "leg": name,
        "asr_channel": 1,
        "default_sink_volume": 0.4,
        "alsa_gain": {"available": True, "controls": {"Headset,0": {"capture": {"L": 54}}}},
        "channels": {
            "ch0": {"rms_dbfs": level},
            "ch1": {"rms_dbfs": level, "frame_p90_dbfs": level},
        },
    }
    if ref is not None:
        leg["reference_mic"] = {"device": 4, "rate_hz": 48_000, "rms_dbfs": ref}
    return leg


def test_an_uncancelled_leg_on_the_noise_floor_is_refused(erle) -> None:
    """The exact shape the play()+rec() bug produced, refused at the report.

    Belt as well as braces: even if some future path manages to record a silent
    uncancelled leg, subtracting it would yield ~0 dB and a ``fail`` blaming a
    clipped amplifier. There is no echo in it to cancel, so there is nothing to
    measure, and the report says which knob to check.
    """

    report = erle.build_report([
        _leg(erle, "floor", -70.0),
        _leg(erle, "uncancelled", -68.5, ref=-30.0),
        _leg(erle, "cancelled", -69.0, ref=-30.1),
    ])

    assert report["verdict"] == "unmeasured"
    assert report["probe_reached_mic"] is False
    assert any("did not reach the microphone" in problem for problem in report["problems"])
    assert any("--play-device" in problem for problem in report["problems"])


def test_a_real_echo_is_measured_normally(erle) -> None:
    report = erle.build_report([
        _leg(erle, "floor", -70.0),
        _leg(erle, "uncancelled", -20.0, ref=-30.0),
        _leg(erle, "cancelled", -45.0, ref=-30.3),
    ])

    assert report["probe_reached_mic"] is True
    assert report["asr_beam_echo_attenuation_db"] == pytest.approx(25.0)
    assert report["erle_db"] == report["asr_beam_echo_attenuation_db"]  # the alias
    assert report["verdict"] == "pass"
    assert report["problems"] == []


def test_the_report_carries_its_own_definition(erle) -> None:
    """The number must not be able to travel without what it measured."""

    report = erle.build_report([
        _leg(erle, "uncancelled", -20.0, ref=-30.0),
        _leg(erle, "cancelled", -45.0, ref=-30.1),
    ])
    assert "NOT textbook ERLE" in report["measures"]
    assert "asr_beam_echo_attenuation_db" in report


def test_a_gain_change_between_legs_invalidates_the_subtraction(erle) -> None:
    moved = _leg(erle, "cancelled", -45.0, ref=-30.1)
    moved["alsa_gain"] = {
        "available": True, "controls": {"Headset,0": {"capture": {"L": 60}}},
    }
    report = erle.build_report([
        _leg(erle, "floor", -70.0), _leg(erle, "uncancelled", -20.0, ref=-30.0), moved,
    ])

    assert report["alsa_gain_stable"] is False
    assert report["verdict"] == "unmeasured"
    assert any("mixer setting" in problem for problem in report["problems"])
