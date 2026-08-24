"""Card AIR-1 — the array is 16 kHz-only, and nothing may route around that.

THE FAILURE THIS PINS
---------------------
The reSpeaker XVF3800 opens exactly one sample rate, in both directions. The
hosted realtime lane produces 24 kHz and Piper produces 22.05 kHz. Whenever
somebody points either of those at the array's ``hw:`` device, PortAudio answers
``PaErrorCode -9997`` — and the symptom on the desk is a robot that has gone
mute, which is not a symptom anyone traces to a sample rate. Worse is the
opposite outcome: the call reaches the *PipeWire node* instead, PipeWire
resamples silently, and every latency number measured through that path belongs
to a resampler nobody chose.

So the pin has two halves:

* the **fact** — this host's own ``stream0``, and (where PortAudio is loadable)
  the array's live answer to a rate sweep;
* the **coupling** — the producers' real constants, imported from the product
  modules, cross-checked against the table the tools resample from. Moving
  ``PCM16_SAMPLE_RATE_HZ`` without teaching the array path about it reddens
  here rather than on the desk.

The live rows need ``scripts/env-audio.sh`` on the library path and the array
attached; they skip, loudly and by name, when either is absent. The parse rows
never do — they run against this host's captured ``stream0`` on any machine.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = REPO_ROOT / "tools" / "xvf3800_probe.py"

#: ``/proc/asound/card2/stream0`` on this host, 2026-08-22, copied verbatim.
#: The fixture is the evidence: "16 kHz-only" is a quotation, not a memory.
STREAM0_TEXT = """\
Seeed Studio reSpeaker XVF3800 4-Mic Array at usb-0000:03:00.4-1, high speed : USB Audio

Playback:
  Status: Stop
  Interface 1
    Altset 1
    Format: S16_LE
    Channels: 2
    Endpoint: 0x01 (1 OUT) (SYNC)
    Rates: 16000
    Data packet interval: 500 us
    Bits: 16
    Channel map: FL FR

Capture:
  Status: Stop
  Interface 2
    Altset 1
    Format: S16_LE
    Channels: 2
    Endpoint: 0x81 (1 IN) (SYNC)
    Rates: 16000
    Data packet interval: 500 us
    Bits: 16
    Channel map: FL FR
"""

#: ``wpctl status`` on this host, trimmed to the two sections the probe parses.
WPCTL_TEXT = """\
Audio
 ├─ Devices:
 │      71. reSpeaker XVF3800 4-Mic Array       [alsa]
 │
 ├─ Sinks:
 │  *   64. reSpeaker XVF3800 4-Mic Array Analog Stereo [vol: 0.40]
 │      72. HD-Audio Generic Analog Stereo      [vol: 1.00]
 │
 ├─ Sources:
 │      62. HD-Audio Generic Analog Stereo      [vol: 0.62]
 │  *   66. reSpeaker XVF3800 4-Mic Array Analog Stereo [vol: 0.82]
 │
 └─ Streams:
"""


@pytest.fixture(scope="module")
def probe():
    spec = importlib.util.spec_from_file_location("xvf3800_probe", TOOL_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["xvf3800_probe"] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


# ============================================================== the plain fact
def test_stream0_says_one_rate_in_both_directions(probe) -> None:
    parsed = probe.parse_stream0(STREAM0_TEXT)

    assert set(parsed) == {"playback", "capture"}
    for direction, section in parsed.items():
        assert section["rates_hz"] == [16_000], direction
        assert section["channels"] == 2, direction
        assert section["format"] == "S16_LE", direction


def test_the_pin_matches_the_device(probe) -> None:
    """The constant and the device agree — otherwise the constant is folklore."""

    capture = probe.parse_stream0(STREAM0_TEXT)["capture"]
    assert probe.ARRAY_SUPPORTED_RATES_HZ == (probe.ARRAY_RATE_HZ,)
    assert list(probe.ARRAY_SUPPORTED_RATES_HZ) == capture["rates_hz"]


def test_a_rate_the_array_cannot_open_is_refused_with_the_error_you_will_see(probe) -> None:
    probe.assert_array_rate(16_000, where="test")  # the one that works

    with pytest.raises(probe.ProbeError) as caught:
        probe.assert_array_rate(24_000, where="hosted lane playback")
    message = str(caught.value)
    assert "hosted lane playback" in message
    assert "16000" in message
    assert str(probe.PA_INVALID_SAMPLE_RATE) in message  # -9997, the traceback's number


# ========================================================== the coupling
def test_every_producer_in_this_stack_is_accounted_for(probe) -> None:
    """The rates the tools resample from ARE the product's own constants."""

    from parcel_robot.audio.voice_loop import SAMPLE_RATE_HZ as LEGACY_LOOP_RATE_HZ
    from parcel_robot.realtime.protocol import PCM16_SAMPLE_RATE_HZ

    assert probe.PRODUCER_RATES_HZ["hosted_realtime"] == PCM16_SAMPLE_RATE_HZ
    assert probe.PRODUCER_RATES_HZ["legacy_loop"] == LEGACY_LOOP_RATE_HZ

    plans = probe.check_producer_rates()
    assert plans["hosted_realtime"]["action"] == "resample"
    assert plans["piper_tts"]["action"] == "resample"
    assert plans["legacy_loop"]["action"] == "direct"
    assert plans["legacy_loop"]["direct"] is True


def test_resample_plan_states_the_ratio_rather_than_hiding_it(probe) -> None:
    plan = probe.resample_plan(24_000)
    assert plan["array_rate_hz"] == 16_000
    assert plan["ratio"] == pytest.approx(2 / 3)


# ============================================== the sweep, and its two failures
def _matrix(**accepted: bool) -> dict:
    return {
        rate: {
            direction: {"ok": accepted.get(rate, False), "error": ""}
            for direction in ("input", "output")
        }
        for rate in ("8000", "16000", "22050", "24000", "44100", "48000")
    }


def test_a_clean_sweep_has_no_problems(probe) -> None:
    assert probe.evaluate_rate_matrix(_matrix(**{"16000": True})) == []


def test_an_accepted_24k_means_something_is_resampling_underneath_you(probe) -> None:
    problems = probe.evaluate_rate_matrix(_matrix(**{"16000": True, "24000": True}))
    assert problems, "24 kHz accepted on a 16 kHz-only device must be a problem"
    assert any("resampling underneath you" in problem for problem in problems)


def test_a_refused_16k_is_a_problem_too(probe) -> None:
    problems = probe.evaluate_rate_matrix(_matrix())
    assert any("16000 Hz input was REFUSED" in problem for problem in problems)


# ==================================================== the rest of the wiring
def test_wpctl_parse_finds_the_defaults_and_their_volumes(probe) -> None:
    status = probe.parse_wpctl_status(WPCTL_TEXT)
    report = probe.default_device_report(status)

    assert report["sinks"]["default_id"] == 64
    assert report["sinks"]["default_volume"] == pytest.approx(0.40)
    assert report["sinks"]["is_array"] is True
    assert report["sources"]["default_id"] == 66
    assert report["sources"]["is_array"] is True


def test_a_one_channel_ear_gets_neither_beam(probe) -> None:
    """The downmix hazard, with a number on it.

    Two beams of the same room that disagree partly cancel when averaged. The
    tool reports the ASR beam's level, the average's level and their difference,
    so "the ear takes ch1" is a measurement and not a slogan.
    """

    import numpy as np

    rng = np.random.default_rng(7)
    common = rng.standard_normal(16_000) * 3000.0
    conference = (common + rng.standard_normal(16_000) * 500.0).astype(np.int16)
    asr = (-common + rng.standard_normal(16_000) * 500.0).astype(np.int16)
    block = np.stack([conference, asr], axis=1)

    hazard = probe.downmix_hazard(block)
    assert hazard["applicable"] is True
    assert hazard["ch0_ch1_correlation"] < -0.9  # the two beams disagree
    # ... and the average is far quieter than the beam the ear should have taken.
    assert hazard["downmix_minus_asr_db"] < -10.0
    assert str(probe.ASR_CHANNEL_INDEX) in hazard["note"]


def test_downmix_is_not_applicable_to_a_mono_capture(probe) -> None:
    import numpy as np

    hazard = probe.downmix_hazard(np.zeros((100, 1), dtype=np.int16))
    assert hazard["applicable"] is False


# ================================================================ the live row
def _live_device(probe):
    try:
        return probe.find_portaudio_device()
    except probe.ProbeError as error:
        pytest.skip(f"PortAudio is not loadable here: {error}")
    return None


@pytest.mark.load_sensitive
def test_the_array_itself_refuses_24k(probe) -> None:
    """The claim, measured on the hardware. Skips by name when it is not here.

    ``load_sensitive`` because it asks PortAudio a question about a device that
    a live session may be holding; the answer is a device capability and does
    not depend on load, but the query does open the host API.
    """

    device = _live_device(probe)
    if device is None:
        pytest.skip("no XVF3800 hw: device in PortAudio's list")
    matrix = probe.rate_matrix(device)

    assert matrix["16000"]["input"]["ok"] is True
    assert matrix["16000"]["output"]["ok"] is True
    for rate in ("22050", "24000", "44100", "48000"):
        assert matrix[rate]["input"]["ok"] is False, rate
        assert str(probe.PA_INVALID_SAMPLE_RATE) in matrix[rate]["input"]["error"]
    assert probe.evaluate_rate_matrix(matrix) == []
