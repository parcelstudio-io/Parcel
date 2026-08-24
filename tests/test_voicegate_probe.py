"""VOICE-GATE v2 capability probe — the four claims the harness must not fake.

The study's own numbers live in ``research/20260824/voice-gate/results/``; this
file pins the four STRUCTURAL properties those numbers depend on, so a later
refactor cannot quietly turn a measured guarantee into a coincidence:

1. a refused span sends **zero bytes** to the transport (that is what "zero
   hosted bytes for television" means: it is a property of the code path, not a
   statistic);
2. an admitted span carries the **pre-roll**, so the first word is uploaded;
3. push-to-talk admits **nothing** outside its gesture window;
4. the STOP matcher's whole-word rule does **not** latch on "the driver stopped
   at the intersection" — the adversarial line that is in the television tape on
   purpose — while it does latch on "stop".

No hardware, no network, no whisper server: the ASR is a stub for (4) and the
gate rows use a deterministic tone/silence tape. The Silero model is a real file
in the tree, so (1)–(3) exercise the real VAD.
"""

from __future__ import annotations

import sys
import wave
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[1]
FOLDER = REPO / "research" / "20260824" / "voice-gate"

if str(FOLDER) not in sys.path:  # the folder name starts with a digit; import by path
    sys.path.insert(0, str(FOLDER))

pytest.importorskip("onnxruntime", reason="Silero needs onnxruntime")

from harness.asr import Transcript
from harness.gate import (
    FRAME_S,
    SILERO_MODEL,
    Decision,
    GateConfig,
    Placement,
    Tape,
    push_to_talk_arm,
    run_gate,
    vad_only_arm,
)
from harness.stop_matcher import StopConfig, run_stop_matcher

RATE_HZ = 16_000

#: Real speech, from a fixture already in the tree. Silero v6 is a speech
#: detector, not an energy detector: band-limited noise does not open it, and a
#: probe that used noise would be testing nothing.
FIXTURE = REPO / "evals" / "companion" / "acoustic_loop_v1" / "fixtures" / "complete_01.wav"


pytestmark = pytest.mark.skipif(
    not SILERO_MODEL.is_file() or not FIXTURE.is_file(),
    reason="VOICE-GATE probe needs the Silero model and the acoustic_loop_v1 fixture",
)


def _speech() -> np.ndarray:
    with wave.open(str(FIXTURE)) as handle:
        rate = handle.getframerate()
        frames = handle.readframes(handle.getnframes())
    samples = np.frombuffer(frames, dtype="<i2").astype(np.float64) / 32768.0
    if rate != RATE_HZ:
        index = np.linspace(0.0, samples.size - 1.0, round(samples.size * RATE_HZ / rate))
        samples = np.interp(index, np.arange(samples.size), samples)
    return samples / (np.abs(samples).max() + 1e-9)


def _tape(speech_at_s: float = 2.0, total_s: float = 10.0) -> Tape:
    rng = np.random.default_rng(1)
    samples = rng.standard_normal(int(total_s * RATE_HZ)) * 0.0008
    start = int(speech_at_s * RATE_HZ)
    voice = _speech() * 0.4
    speech_s = voice.size / RATE_HZ
    samples[start : start + voice.size] += voice
    pcm = np.clip(np.rint(samples * 32768.0), -32768, 32767).astype(np.int16)
    return Tape(
        samples=pcm,
        placements=[
            Placement(
                name="probe",
                role="owner",
                voice="probe",
                text="",
                start_s=speech_at_s,
                speech_start_s=speech_at_s,
                speech_end_s=speech_at_s + speech_s,
                geometry="1m/0deg",
                replay=False,
            )
        ],
    )


def test_a_refused_span_sends_no_bytes() -> None:
    """The pre-cloud rail's whole point: rejection means the transport saw nothing."""

    tape = _tape()

    def refuse(_window, _open_s, _placement) -> Decision:
        return Decision(admit=False, reason="test_refusal")

    admissions, transport = run_gate(tape, refuse, config=GateConfig())
    assert admissions, "the gate never opened, so the refusal proves nothing"
    assert all(not admission.admitted for admission in admissions)
    assert transport.uploaded_bytes == 0
    assert transport.uploaded_seconds == 0.0
    assert transport.opens == 0
    assert transport.by_role == {}


def test_an_admitted_span_carries_the_preroll() -> None:
    """First-word survival is a property of the buffer, not of luck."""

    tape = _tape()
    config = GateConfig(preroll_ms=500.0)
    admissions, transport = run_gate(tape, vad_only_arm, config=config)
    admitted = [admission for admission in admissions if admission.admitted]
    assert admitted, "nothing was admitted, so the pre-roll claim is untested"
    first = admitted[0]
    placement = tape.placements[0]
    # The pre-roll is measured from the FIRST speech frame, not from the frame
    # that satisfied the debounce, so the gap is preroll + open_frames frames.
    expected = 0.5 + config.open_frames * FRAME_S
    assert first.open_s - first.upload_from_s == pytest.approx(expected, abs=0.01)
    # The property that matters: the owner's first word is inside what was sent.
    assert first.upload_from_s <= placement.speech_start_s
    assert transport.uploaded_bytes > 0


def test_push_to_talk_admits_nothing_outside_its_window() -> None:
    """The reference floor has to actually be a floor."""

    tape = _tape()
    arm = push_to_talk_arm([(100.0, 200.0)])
    admissions, transport = run_gate(tape, arm, config=GateConfig())
    assert admissions
    assert transport.uploaded_bytes == 0
    assert all(admission.reason == "ptt_not_pressed" for admission in admissions)


class _StubAsr:
    """A transcriber with an opinion, so the matcher's rule is what is under test."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.calls = 0

    def transcribe(self, samples, rate_hz: int = RATE_HZ) -> Transcript:
        del samples, rate_hz
        self.calls += 1
        return Transcript(text=self.text, latency_s=0.25)


def test_the_stop_matcher_ignores_stopped_and_latches_on_stop() -> None:
    """The television line 'the driver stopped at the intersection' must not stop the dog."""

    tape = _tape(speech_at_s=1.0, total_s=8.0)
    config = StopConfig()

    innocent = _StubAsr("Police say the driver stopped at the intersection.")
    innocent_run = run_stop_matcher(tape.samples, innocent, config=config)
    assert innocent.calls > 0, "the matcher never asked the transcriber anything"
    assert innocent_run.events == []

    commanded = _StubAsr("Stop.")
    commanded_run = run_stop_matcher(tape.samples, commanded, config=config, latch_once=True)
    assert len(commanded_run.events) == 1
    event = commanded_run.events[0]
    assert event.latch_tape_s > event.window_end_tape_s
    assert event.substring_only is False
