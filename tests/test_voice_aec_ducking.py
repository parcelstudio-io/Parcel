"""AEC ladder rungs L1 (in-process cancellation) and L2 (ducking).

Both are OFF by default. The most important assertions here are the two that
prove that: a loop with no AEC stage and a sink that is never ducked must
behave exactly as they did before these features existed.
"""

from __future__ import annotations

import numpy as np
import pytest

from parcel_robot.voice_audio import (
    FRAME_SAMPLES,
    SAMPLE_RATE_HZ,
    AecStage,
    EnergyVad,
    MicrophoneVoiceLoop,
    SpeakerSink,
)


def _speech_like(
    samples: int,
    *,
    seed: int,
    amplitude: float = 6000.0,
    f0: float = 130.0,
    syllable_hz: float = 4.0,
) -> np.ndarray:
    """A deterministic voiced-ish signal: harmonics plus a syllable envelope.

    ``f0`` matters for double-talk tests: two talkers sharing a fundamental
    are correlated, and an adaptive filter will happily cancel BOTH of them.
    Real near-end speech is uncorrelated with the far end, so a double-talk
    fixture must use distinct spectra or it tests nothing.
    """

    rng = np.random.default_rng(seed)
    t = np.arange(samples) / SAMPLE_RATE_HZ
    signal = (
        np.sin(2 * np.pi * f0 * t)
        + 0.5 * np.sin(2 * np.pi * 2 * f0 * t)
        + 0.25 * np.sin(2 * np.pi * 4 * f0 * t)
    )
    envelope = 0.55 + 0.45 * np.sin(2 * np.pi * syllable_hz * t)
    noise = rng.normal(0.0, 0.02, samples)
    out = (signal * envelope + noise) * (amplitude / 1.75)
    return np.clip(out, -32768, 32767).astype(np.int16)


def _echo_of(far: np.ndarray, *, delay: int, attenuation: float) -> np.ndarray:
    """Synthetic linear echo path: delayed and attenuated far-end audio."""

    delayed = np.concatenate([np.zeros(delay, dtype=np.float64), far.astype(np.float64)])
    return (delayed[: far.size] * attenuation).astype(np.int16)


# --------------------------------------------------------------- AEC (L1)
class TestAecStage:
    def test_rejects_non_int16_frames(self):
        aec = AecStage()
        with pytest.raises(TypeError):
            aec.process(np.zeros(480, dtype=np.float32))
        with pytest.raises(TypeError):
            aec.submit_far(np.zeros(480, dtype=np.float32))

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"filter_taps": 4},
            {"filter_taps": 100_000},
            {"step_size": 0.0},
            {"step_size": 3.0},
            {"regularization": 0.0},
            {"stream_delay_ms": -1.0},
        ],
    )
    def test_rejects_invalid_configuration(self, kwargs):
        with pytest.raises(ValueError):
            AecStage(**kwargs)

    def test_cancels_synthetic_echo(self):
        """>= 15 dB ERLE on a delayed, attenuated far-end signal."""

        far = _speech_like(SAMPLE_RATE_HZ * 4, seed=11, amplitude=9000.0)
        echo = _echo_of(far, delay=96, attenuation=0.45)
        aec = AecStage(filter_taps=256, step_size=0.5)

        raw_tail: list[np.ndarray] = []
        clean_tail: list[np.ndarray] = []
        frames = far.size // FRAME_SAMPLES
        for index in range(frames):
            lo = index * FRAME_SAMPLES
            near_frame = echo[lo : lo + FRAME_SAMPLES]
            aec.submit_far(far[lo : lo + FRAME_SAMPLES])
            cleaned = aec.process(near_frame)
            # Judge on the converged portion only: an adaptive filter is not
            # expected to cancel before it has seen the echo path, and the
            # first moments after playback starts are documented as uncancelled.
            if index > frames * 0.5:
                raw_tail.append(near_frame)
                clean_tail.append(cleaned)

        erle = AecStage.erle_db(
            np.concatenate(raw_tail), np.concatenate(clean_tail)
        )
        assert erle >= 15.0, f"converged ERLE {erle:.1f} dB below the 15 dB bar"

    def test_near_end_speech_survives_cancellation(self):
        """The owner must still be audible through the canceller."""

        far = _speech_like(SAMPLE_RATE_HZ * 3, seed=5, amplitude=9000.0, f0=110.0)
        echo = _echo_of(far, delay=64, attenuation=0.4)
        # A different talker: distinct fundamental and syllable rate, so the
        # near end is genuinely uncorrelated with the far end.
        near_speech = _speech_like(
            SAMPLE_RATE_HZ * 3, seed=99, amplitude=5000.0, f0=205.0, syllable_hz=6.5
        )
        # Owner starts talking halfway through, over the robot.
        mixed = echo.astype(np.float64)
        half = mixed.size // 2
        mixed[half:] += near_speech[half:]
        mixed = np.clip(mixed, -32768, 32767).astype(np.int16)

        aec = AecStage(filter_taps=256, step_size=0.5)
        cleaned_frames = []
        for index in range(far.size // FRAME_SAMPLES):
            lo = index * FRAME_SAMPLES
            aec.submit_far(far[lo : lo + FRAME_SAMPLES])
            cleaned_frames.append(aec.process(mixed[lo : lo + FRAME_SAMPLES]))
        cleaned = np.concatenate(cleaned_frames)

        quiet = EnergyVad.frame_rms(cleaned[: cleaned.size // 2][-SAMPLE_RATE_HZ // 2 :])
        talking = EnergyVad.frame_rms(cleaned[half + SAMPLE_RATE_HZ // 2 :])
        assert talking > quiet * 3.0, (
            f"near-end speech not preserved: {talking:.0f} vs echo residual {quiet:.0f}"
        )

    def test_silence_in_silence_out(self):
        aec = AecStage()
        out = aec.process(np.zeros(FRAME_SAMPLES, dtype=np.int16))
        assert np.all(out == 0)

    def test_erle_of_identical_signals_is_zero(self):
        signal = _speech_like(4800, seed=3)
        assert AecStage.erle_db(signal, signal) == pytest.approx(0.0, abs=1e-9)

    def test_far_buffer_is_bounded(self):
        aec = AecStage()
        block = np.zeros(SAMPLE_RATE_HZ, dtype=np.int16)
        for _ in range(12):
            aec.submit_far(block)
        assert aec._far_buffer.size <= SAMPLE_RATE_HZ * 5


class TestAecInLoop:
    def test_loop_without_aec_is_unchanged(self):
        """Flag-off must leave the frame path byte-identical."""

        frames = [_speech_like(FRAME_SAMPLES, seed=i) for i in range(40)]
        seen: list[np.ndarray] = []

        loop = MicrophoneVoiceLoop(
            recognizer=type("R", (), {"transcribe": lambda self, w: ""})(),
            submit_text=lambda *a, **k: None,
            barge_in=lambda: None,
            playback_active=lambda: False,
        )
        original = loop.vad.process

        def spy(frame):
            seen.append(frame.copy())
            return original(frame)

        loop.vad.process = spy
        for frame in frames:
            loop.run_once(frame)
        assert loop.aec is None
        assert len(seen) == len(frames)
        for got, expected in zip(seen, frames, strict=True):
            assert np.array_equal(got, expected)

    def test_aec_stage_is_applied_before_the_vad(self):
        frames = [_speech_like(FRAME_SAMPLES, seed=i) for i in range(10)]
        seen: list[np.ndarray] = []

        loop = MicrophoneVoiceLoop(
            recognizer=type("R", (), {"transcribe": lambda self, w: ""})(),
            submit_text=lambda *a, **k: None,
            barge_in=lambda: None,
            playback_active=lambda: False,
            aec=AecStage(filter_taps=64),
        )
        original = loop.vad.process
        loop.vad.process = lambda f: (seen.append(f.copy()), original(f))[1]
        for frame in frames:
            loop.run_once(frame)
        assert loop.aec is not None
        assert loop.aec.frames_processed == len(frames)

    def test_failing_aec_is_dropped_and_capture_continues(self):
        class Exploding(AecStage):
            def process(self, near):
                raise RuntimeError("boom")

        loop = MicrophoneVoiceLoop(
            recognizer=type("R", (), {"transcribe": lambda self, w: ""})(),
            submit_text=lambda *a, **k: None,
            barge_in=lambda: None,
            playback_active=lambda: False,
            aec=Exploding(),
        )
        loop.run_once(_speech_like(FRAME_SAMPLES, seed=1))
        assert loop.aec is None, "a broken AEC must be dropped, not deafen the robot"
        loop.run_once(_speech_like(FRAME_SAMPLES, seed=2))  # still captures


# ----------------------------------------------------------- ducking (L2)
class TestSpeakerSinkDucking:
    def test_defaults_to_unity_gain(self):
        played: list[bytes] = []
        sink = SpeakerSink(player=lambda pcm, rate: played.append(pcm))
        try:
            assert sink.gain == 1.0
            assert not sink.ducked
            assert sink.ducks_applied == 0
        finally:
            sink.close()

    @pytest.mark.parametrize("value", [0.0, -3.0, 61.0, float("nan")])
    def test_rejects_invalid_attenuation(self, value):
        sink = SpeakerSink(player=lambda pcm, rate: None)
        try:
            with pytest.raises(ValueError):
                sink.duck(value)
        finally:
            sink.close()

    def test_duck_attenuates_by_the_requested_amount(self):
        sink = SpeakerSink(player=lambda pcm, rate: None)
        try:
            sink.duck(12.0)
            assert sink.ducked
            # 12 dB down is a factor of ~0.251.
            assert sink.gain == pytest.approx(10 ** (-12.0 / 20.0), rel=1e-6)
            assert sink.ducks_applied == 1
        finally:
            sink.close()

    def test_restore_returns_to_unity_and_counts(self):
        sink = SpeakerSink(player=lambda pcm, rate: None)
        try:
            sink.duck(10.0)
            sink.restore()
            assert sink.gain == 1.0
            assert not sink.ducked
            assert sink.ducks_restored == 1
        finally:
            sink.close()

    def test_restore_without_a_duck_does_not_count(self):
        sink = SpeakerSink(player=lambda pcm, rate: None)
        try:
            sink.restore()
            assert sink.ducks_restored == 0
        finally:
            sink.close()

    def test_ducked_for_s_tracks_the_confirm_window(self):
        sink = SpeakerSink(player=lambda pcm, rate: None)
        try:
            assert sink.ducked_for_s == 0.0
            sink.duck(10.0)
            assert sink.ducked_for_s >= 0.0
            sink.restore()
            assert sink.ducked_for_s == 0.0
        finally:
            sink.close()

    def test_duck_does_not_disturb_the_interrupt_latch(self):
        """Ducking is explicitly NOT a teardown: the turn must survive it."""

        sink = SpeakerSink(player=lambda pcm, rate: None)
        try:
            sink.begin_utterance()
            sink.duck(10.0)
            assert not sink._interrupted.is_set()
            sink.restore()
            assert not sink._interrupted.is_set()
        finally:
            sink.close()


# ------------------------------------------------------- acoustic clocks
class TestAcousticClocks:
    """The three ledger clocks this lane can own (see N19 for the fan-in)."""

    def test_speaker_records_its_first_sample_instant(self):
        import time

        started: list[float] = []
        sink = SpeakerSink(player=lambda pcm, rate: started.append(time.monotonic()))
        try:
            assert sink.first_chunk_started_monotonic is None
            sink.begin_utterance()
            sink.enqueue(np.zeros(1600, dtype=np.int16).tobytes())
            deadline = time.monotonic() + 3.0
            while time.monotonic() < deadline and not started:
                time.sleep(0.01)
            assert started, "player never ran"
            first = sink.first_chunk_started_monotonic
            assert first is not None
            # Recorded at the true start of the chunk, not at enqueue.
            assert abs(first - started[0]) < 0.5

            sink.enqueue(np.zeros(1600, dtype=np.int16).tobytes())
            deadline = time.monotonic() + 3.0
            while time.monotonic() < deadline and len(started) < 2:
                time.sleep(0.01)
            # A second chunk of the SAME reply must not move the first anchor.
            assert sink.first_chunk_started_monotonic == first
        finally:
            sink.close()

    def test_new_reply_resets_the_first_sample_anchor(self):
        sink = SpeakerSink(player=lambda pcm, rate: None)
        try:
            sink.first_chunk_started_monotonic = 123.0
            sink.begin_utterance()
            assert sink.first_chunk_started_monotonic is None, (
                "a stale anchor makes every later turn look instantaneous"
            )
        finally:
            sink.close()

    def test_commit_records_capture_clocks(self):
        """speech-end and semantic-commit must be real monotonic instants."""

        class AlwaysSpeech:
            available = True
            threshold = 0.5

            def process(self, window):
                return 1.0

        class CommitAfterSilence:
            """Speak, then commit on the first silent observation."""

            def __init__(self):
                self.seen_speech = False

            def observe(self, *, is_speech, audio_tail, now_s):
                if is_speech:
                    self.seen_speech = True
                    return "speaking"
                return "commit" if self.seen_speech else "hold"

        loop = MicrophoneVoiceLoop(
            recognizer=type("R", (), {"transcribe": lambda self, w: ""})(),
            submit_text=lambda *a, **k: None,
            barge_in=lambda: None,
            playback_active=lambda: False,
            neural_vad=AlwaysSpeech(),
            endpointer=CommitAfterSilence(),
        )
        assert loop.last_turn_clocks is None
        loud = (np.ones(FRAME_SAMPLES) * 6000).astype(np.int16)
        for _ in range(20):
            loop.run_once(loud)
        loop.neural_vad = None  # fall back to energy; silence now reads quiet
        for _ in range(6):
            loop.run_once(np.zeros(FRAME_SAMPLES, dtype=np.int16))

        clocks = loop.last_turn_clocks
        assert clocks is not None, "commit did not record capture clocks"
        assert clocks["semantic_commit_monotonic"] >= clocks["speech_end_monotonic"]
        assert clocks["endpoint_decision_s"] >= 0.0
        assert clocks["utterance_s"] > 0.0

    def test_whisper_provider_records_stt_clocks(self):
        from parcel_robot.providers import WhisperCppProvider

        provider = WhisperCppProvider(base_url="http://127.0.0.1:1")
        assert provider.last_metrics == {}
        with pytest.raises(RuntimeError):
            provider.transcribe(b"RIFF" + b"\x00" * 100)
        metrics = provider.last_metrics
        assert metrics["status"] == "failed"
        assert metrics["duration_s"] >= 0.0
        assert metrics["final_monotonic"] >= metrics["request_start_monotonic"]
        assert metrics["audio_s"] >= 0.0
