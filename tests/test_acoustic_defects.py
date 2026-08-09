"""Unit coverage for the three acoustic-close defects N16 / N17 / N19.

These are deterministic, hardware-free tests that pin the *code paths* the
fixes changed. The wall-clock acoustic improvements the fixes target
(post-interrupt output-buffer drain for N16; a genuine attenuated echo for
N17) require a real output device with real latency and a real acoustic echo
path; the virtual `acoustic_loop_v1` null-sink rig cannot exhibit either (its
OutputStream reports ~0 s latency, and it has no acoustic coupling). See
scrum/20260809/task_8/ACOUSTIC_CLOSE_STATUS.md for the rig evidence.
"""

from __future__ import annotations

import sys
import threading
import time
from typing import Self

import numpy as np
import pytest

from parcel_robot.observability import STAGES, LatencyTracker
from parcel_robot.voice_audio import (
    FRAME_SAMPLES,
    EnergyVad,
    MicrophoneVoiceLoop,
    SpeakerSink,
    pcm16_wav,
)


# --------------------------------------------------------------------- N16
class _FakeOutputStream:
    """Records the abort/stop/write/close order for a SpeakerSink._play call."""

    def __init__(self, *, calls: list[str], first_write_block: threading.Event):
        self._calls = calls
        self._first_write_block = first_write_block
        self._wrote_once = False

    def __enter__(self) -> Self:
        self._calls.append("enter")
        return self

    def __exit__(self, *_exc: object) -> None:
        # The real sounddevice OutputStream.__exit__ calls stop() (which DRAINS
        # the buffered frames) then close(). If the interrupt path relied on
        # this, the robot would keep talking for one output latency.
        self._calls.append("exit_stop")
        self._calls.append("exit_close")

    def write(self, chunk: np.ndarray) -> None:
        self._calls.append("write")
        if not self._wrote_once:
            self._wrote_once = True
            # Park the worker inside the first block so the test can request an
            # interrupt while a chunk is genuinely in flight.
            self._first_write_block.wait(2.0)

    def abort(self) -> None:
        self._calls.append("abort")

    def stop(self) -> None:  # pragma: no cover - only via __exit__ in this fake
        self._calls.append("stop")


def test_n16_interrupt_aborts_the_output_stream(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    first_write = threading.Event()

    class _FakeSounddevice:
        @staticmethod
        def OutputStream(**_kwargs: object) -> _FakeOutputStream:
            return _FakeOutputStream(calls=calls, first_write_block=first_write)

    monkeypatch.setitem(sys.modules, "sounddevice", _FakeSounddevice())

    sink = SpeakerSink()  # real playback path (no injected player)
    try:
        sink.begin_utterance()
        # Two ~50 ms blocks so there is a block boundary at which to notice the
        # interrupt latch.
        sink.enqueue(pcm16_wav(b"\x01\x00" * 3200))
        deadline = time.monotonic() + 2.0
        while "write" not in calls and time.monotonic() < deadline:
            time.sleep(0.005)
        assert "write" in calls, "worker never reached the output stream"

        sink.interrupt()  # barge-in while the first block is in flight
        first_write.set()  # let the parked write() return; loop re-checks latch

        deadline = time.monotonic() + 2.0
        while "abort" not in calls and time.monotonic() < deadline:
            time.sleep(0.005)
    finally:
        first_write.set()
        sink.close()

    # The buffered frames were dropped via abort() ...
    assert "abort" in calls, calls
    # ... and abort happened before the context manager's draining stop().
    assert calls.index("abort") < calls.index("exit_stop"), calls


def test_n16_normal_completion_drains_without_abort(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A reply that is NOT interrupted must play to its end: the draining stop()
    # on __exit__ is correct there, and abort() must not fire.
    calls: list[str] = []
    released = threading.Event()
    released.set()  # never block writes

    class _FakeSounddevice:
        @staticmethod
        def OutputStream(**_kwargs: object) -> _FakeOutputStream:
            return _FakeOutputStream(calls=calls, first_write_block=released)

    monkeypatch.setitem(sys.modules, "sounddevice", _FakeSounddevice())

    sink = SpeakerSink()
    try:
        sink.begin_utterance()
        sink.enqueue(pcm16_wav(b"\x01\x00" * 3200))
        deadline = time.monotonic() + 2.0
        while "exit_close" not in calls and time.monotonic() < deadline:
            time.sleep(0.005)
    finally:
        sink.close()
    assert "abort" not in calls, calls
    assert "exit_stop" in calls and "exit_close" in calls


# --------------------------------------------------------------------- N17
class _ScriptedNeuralVad:
    """Silero stand-in that records every window it is asked to score.

    ``available`` and ``threshold`` mirror the SileroVad interface the loop
    probes. The recorded ``windows`` count is what proves the loop feeds the
    model a CONTINUOUS stream rather than only the frames that survived the
    echo guard.
    """

    def __init__(self, probability: float) -> None:
        self.available = True
        self.threshold = 0.5
        self._p = probability
        self.windows = 0

    def process(self, window: np.ndarray) -> float:
        self.windows += 1
        return self._p


class _NeverCommit:
    def observe(self, *, is_speech: bool, audio_tail: object, now_s: float) -> str:
        del is_speech, audio_tail, now_s
        return "hold"


def _quiet_frame() -> np.ndarray:
    return np.full(FRAME_SAMPLES, 5, dtype=np.int16)  # RMS 5, far below any guard


def _loud_frame() -> np.ndarray:
    return np.full(FRAME_SAMPLES, 6000, dtype=np.int16)  # RMS 6000, above the guard


def _make_loop(vad: _ScriptedNeuralVad, barge: list[int], *, playback: bool):
    return MicrophoneVoiceLoop(
        recognizer=type("R", (), {"transcribe": lambda self, w: ""})(),
        submit_text=lambda *a, **k: None,
        barge_in=lambda: barge.append(1),
        playback_active=lambda: playback,
        neural_vad=vad,
        endpointer=_NeverCommit(),
        echo_guard_scale=2.5,
    )


def test_n17_neural_vad_sees_quiet_frames_during_playback() -> None:
    # The defect: the echo guard RETURNed on suppressed frames, so Silero saw a
    # fragmented stream. The fix lets every frame reach the model.
    vad = _ScriptedNeuralVad(probability=0.9)
    barge: list[int] = []
    loop = _make_loop(vad, barge, playback=True)
    for _ in range(12):
        loop.run_once(_quiet_frame())  # all below the echo guard
    # Continuity: the model was scored on the quiet frames (would be 0 if the
    # guard still swallowed them before the VAD).
    assert vad.windows > 0
    # ...but a quiet frame cannot COUNT as owner speech: no barge-in, and the
    # guard bookkeeping still records the suppression.
    assert barge == []
    assert loop.echo_guard_suppressions == 12


def test_n17_loud_owner_speech_over_tts_still_barges_in() -> None:
    vad = _ScriptedNeuralVad(probability=0.9)
    barge: list[int] = []
    loop = _make_loop(vad, barge, playback=True)
    for _ in range(6):
        loop.run_once(_loud_frame())  # above the guard: a real owner over TTS
    assert vad.windows > 0
    assert barge, "loud owner speech over TTS must still barge in"
    assert loop.echo_guard_suppressions == 0


def test_n17_no_playback_leaves_the_guard_inert() -> None:
    # With no playback the echo guard must not gate anything: this is the plain
    # capture path and quiet frames simply are not speech-level.
    vad = _ScriptedNeuralVad(probability=0.9)
    barge: list[int] = []
    loop = _make_loop(vad, barge, playback=False)
    for _ in range(6):
        loop.run_once(_quiet_frame())
    assert loop.echo_guard_suppressions == 0
    assert barge == []  # barge-in only fires while the robot is speaking


def test_n17_energy_path_still_swallows_suppressed_frames() -> None:
    # The legacy energy path (no neural VAD, no endpointer) keeps its historical
    # behaviour: a guard-suppressed frame is not fed to the segmenter at all.
    barge: list[int] = []
    loop = MicrophoneVoiceLoop(
        recognizer=type("R", (), {"transcribe": lambda self, w: ""})(),
        submit_text=lambda *a, **k: None,
        barge_in=lambda: barge.append(1),
        playback_active=lambda: True,
        vad=EnergyVad(min_speech_frames=2, hangover_frames=3),
        echo_guard_scale=2.0,
    )
    for _ in range(5):
        loop.run_once(np.full(FRAME_SAMPLES, 5, dtype=np.int16))
    assert loop.echo_guard_suppressions >= 5
    assert barge == []
    for _ in range(3):
        loop.run_once(np.full(FRAME_SAMPLES, 12000, dtype=np.int16))
    assert barge


# --------------------------------------------------------------------- N19
N19_STAGES = (
    "capture_speech_end",
    "semantic_commit",
    "stt_request_start",
    "stt_final",
    "audio_first_sample",
)


def test_n19_new_stages_are_registered() -> None:
    for name in N19_STAGES:
        assert name in STAGES, name


def test_n19_tracker_marks_and_reports_the_acoustic_clocks() -> None:
    tracker = LatencyTracker()
    tracker.start(1, "come here", source="microphone", now=100.0)
    tracker.mark(1, "capture_speech_end", now=100.20)
    tracker.mark(1, "semantic_commit", now=100.40)
    tracker.mark(1, "stt_request_start", now=100.41)
    tracker.mark(1, "stt_final", now=100.70)
    tracker.mark(1, "audio_first_playback", now=100.85)  # enqueue stamp
    tracker.mark(1, "audio_first_sample", now=101.45)  # true first sample
    tracker.finish(1, "on my way", now=101.50)

    snap = tracker.snapshot()
    row = next(r for r in snap["turns"] if r["turn_id"] == 1)
    assert row["source"] == "microphone"
    offsets = row["stage_offsets_ms"]
    for name in N19_STAGES:
        assert name in offsets, name
    # The honest gap the ledger was blind to: enqueue stamp vs first audible
    # sample. audio_first_playback is at +850 ms, audio_first_sample at +1450 ms.
    assert offsets["audio_first_sample"] > offsets["audio_first_playback"]


def test_n19_unknown_stage_still_raises() -> None:
    tracker = LatencyTracker()
    tracker.start(1, "hello", now=0.0)
    with pytest.raises(ValueError, match="unsupported latency stage"):
        tracker.mark(1, "not_a_real_stage")
