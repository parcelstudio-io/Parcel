"""Card A4: beat-synced nods, semantic endpointing, and their metrics."""

from __future__ import annotations

import io
import math
import time
import wave
from pathlib import Path

import numpy as np
import pytest

from parcel_robot.audio.devices import AudioDeviceStatus
from parcel_robot.audio.endpointing import TurnEndpointer
from parcel_robot.audio.prosody import analyze_pcm16, analyze_wav_chunk
from parcel_robot.audio.voice_loop import FRAME_SAMPLES, MicrophoneVoiceLoop, SpeakerSink
from parcel_robot.backends.base import OwnerTrack, RobotPose, SimObservation
from parcel_robot.motion.expression import (
    MAX_HEAD_PITCH_RAD,
    BeatLayer,
    ExpressionEngine,
    ExpressionGate,
)
from parcel_robot.robot_profile import RobotProfile
from parcel_robot.runtime import RobotRuntime

REPO = Path(__file__).resolve().parents[1]
SR = 22050


def _speech_pcm(duration_s: float = 2.0, syllable_hz: float = 3.0) -> bytes:
    """Syllabic AM with an intonation contour — enough prosody to have beats."""

    samples = int(SR * duration_s)
    t = np.arange(samples) / SR
    envelope = (0.5 + 0.5 * np.sin(2 * np.pi * syllable_hz * t - np.pi / 2)) ** 3
    f0 = 140 - 25 * (t / duration_s) + 18 * np.sin(2 * np.pi * syllable_hz * t)
    signal = 0.6 * np.sin(2 * np.pi * np.cumsum(f0) / SR) * envelope
    return (np.clip(signal, -1, 1) * 32767).astype(np.int16).tobytes()


def _speech_wav(duration_s: float = 2.0) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(SR)
        writer.writeframes(_speech_pcm(duration_s))
    return buffer.getvalue()


# --- BeatLayer scheduling ---------------------------------------------------


@pytest.mark.slow  # card P0-E: latency percentile pin is a nightly evidence ratchet
def test_nods_land_on_accents_within_the_perceptual_budget() -> None:
    """The whole point: apexes within +/-100 ms of the accent, P50 < 30 ms."""

    track = analyze_pcm16(_speech_pcm(), SR)
    assert track.accents, "test signal produced no accents"
    layer = BeatLayer()
    layer.arm(track, playback_start_s=0.0, epoch=0)

    dt = 1.0 / 50.0  # the shipped expression rate
    for tick in range(int(2.5 / dt)):
        layer.step(tick * dt, epoch=0)

    stats = layer.apex_error_stats()
    assert stats["count"] == len(track.accents)
    assert stats["p50_ms"] < 30.0, stats
    assert stats["p95_ms"] < 100.0, stats


@pytest.mark.slow  # card P0-E: latency percentile pin is a nightly evidence ratchet
def test_control_rate_cannot_meet_the_apex_budget() -> None:
    """Why expression got its own channel: 10 Hz is too coarse, by design."""

    track = analyze_pcm16(_speech_pcm(), SR)
    layer = BeatLayer()
    layer.arm(track, playback_start_s=0.0, epoch=0)
    for tick in range(int(2.5 / 0.1)):
        layer.step(tick * 0.1, epoch=0)
    coarse = layer.apex_error_stats()

    fine_layer = BeatLayer()
    fine_layer.arm(track, playback_start_s=0.0, epoch=0)
    for tick in range(int(2.5 / 0.02)):
        fine_layer.step(tick * 0.02, epoch=0)
    fine = fine_layer.apex_error_stats()
    # A 100 ms grid cannot resolve a 30 ms target; this pins the rationale so
    # nobody "simplifies" the expression channel back into the control loop.
    assert coarse["p50_ms"] > fine["p50_ms"]
    assert coarse["p95_ms"] >= 30.0
    assert fine["p50_ms"] < 30.0


def test_nod_amplitude_scales_with_arousal_and_stays_clamped() -> None:
    quiet = analyze_pcm16(_speech_pcm(syllable_hz=2.0), SR)
    layer = BeatLayer()
    layer.arm(quiet, playback_start_s=0.0, epoch=0)
    peak = 0.0
    dt = 1.0 / 50.0
    for tick in range(int(2.5 / dt)):
        peak = max(peak, layer.step(tick * dt, epoch=0).head_pitch_rad)
    assert 0.0 < peak <= MAX_HEAD_PITCH_RAD


def test_engine_clamps_even_a_pathological_beat_track() -> None:
    class _Fake:
        accents = tuple(
            type("A", (), {"time_s": 0.10 * i, "strength": 1.0})() for i in range(20)
        )
        arousal = 1.0

    engine = ExpressionEngine(RobotProfile.go2())
    engine.beats.arm(_Fake(), playback_start_s=0.0, epoch=engine.speech_epoch)
    dt = 1.0 / 50.0
    for tick in range(120):
        offsets = engine.step(tick * dt, ExpressionGate())
        assert abs(offsets.head_pitch_rad) <= MAX_HEAD_PITCH_RAD + 1e-12


def test_barge_in_drops_every_pending_nod() -> None:
    track = analyze_pcm16(_speech_pcm(), SR)
    engine = ExpressionEngine(RobotProfile.go2())
    engine.beats.arm(track, playback_start_s=0.0, epoch=engine.speech_epoch)
    assert engine.beats.active
    engine.supersede_speech()
    assert not engine.beats.active
    assert engine.step(0.5, ExpressionGate()).head_pitch_rad == pytest.approx(0.0)


def test_stale_epoch_arm_is_ignored() -> None:
    """A chunk that started playing after a barge-in must not schedule nods."""

    track = analyze_pcm16(_speech_pcm(), SR)
    engine = ExpressionEngine(RobotProfile.go2())
    stale_epoch = engine.speech_epoch
    engine.supersede_speech()
    engine.beats.arm(track, playback_start_s=0.0, epoch=stale_epoch)
    # Armed under the old epoch, the layer drops them at the next step.
    assert engine.step(0.1, ExpressionGate()).head_pitch_rad == pytest.approx(0.0)


def test_gated_off_expression_clears_scheduled_nods() -> None:
    track = analyze_pcm16(_speech_pcm(), SR)
    engine = ExpressionEngine(RobotProfile.go2())
    engine.beats.arm(track, playback_start_s=0.0, epoch=engine.speech_epoch)
    engine.step(0.05, ExpressionGate(emergency_stopped=True))
    assert not engine.beats.active


def test_beats_suppress_idle_head_movement() -> None:
    """Nods own the head while they play; idle look-arounds must yield."""

    engine = ExpressionEngine(RobotProfile.go2())
    engine.beats.arm(
        analyze_pcm16(_speech_pcm(), SR), playback_start_s=0.0, epoch=engine.speech_epoch
    )
    saw_beat = False
    for tick in range(120):
        offsets = engine.step(tick / 50.0, ExpressionGate())
        if abs(offsets.head_pitch_rad) > 1e-6:
            saw_beat = True
            assert engine.producer == "beat"
    assert saw_beat


# --- playback-clock anchoring ----------------------------------------------


def test_speaker_sink_reports_playback_start_with_its_token() -> None:
    started: list[object] = []
    sink = SpeakerSink(
        player=lambda pcm, rate: time.sleep(0.01),
        on_chunk_start=started.append,
    )
    try:
        sink.begin_utterance()
        sink.enqueue(_speech_wav(0.2), token="chunk-1")
        deadline = time.time() + 2.0
        while not started and time.time() < deadline:
            time.sleep(0.01)
        assert started == ["chunk-1"]
    finally:
        sink.close()


def test_interrupted_chunk_never_reports_playback_start() -> None:
    started: list[object] = []
    sink = SpeakerSink(player=lambda pcm, rate: None, on_chunk_start=started.append)
    try:
        sink.interrupt()
        sink.enqueue(_speech_wav(0.2), token="stale")
        time.sleep(0.15)
        assert started == []
    finally:
        sink.close()


# --- semantic endpointing ---------------------------------------------------


def _frames(count: int, *, speech: bool) -> list[np.ndarray]:
    if not speech:
        return [np.zeros(FRAME_SAMPLES, dtype=np.int16) for _ in range(count)]
    t = np.arange(FRAME_SAMPLES)
    tone = (6000 * np.sin(2 * np.pi * 220 * t / 16000)).astype(np.int16)
    return [tone for _ in range(count)]


class _Recognizer:
    def __init__(self, transcript: str = "hello there") -> None:
        self.transcript = transcript
        self.calls: list[bytes] = []

    def transcribe(self, wav_audio: bytes) -> str:
        self.calls.append(wav_audio)
        return self.transcript


def _semantic_loop(probability: float, **kwargs):
    submitted: list[tuple[str, bool]] = []
    commits: list[float] = []
    loop = MicrophoneVoiceLoop(
        recognizer=_Recognizer(),
        submit_text=lambda text, is_final: submitted.append((text, is_final)),
        barge_in=lambda: None,
        playback_active=lambda: False,
        endpointer=TurnEndpointer("fake.onnx", _infer=lambda audio: probability, **kwargs),
        on_turn_commit=commits.append,
    )
    return loop, submitted, commits


def test_complete_turn_commits_shortly_after_speech_ends() -> None:
    loop, submitted, commits = _semantic_loop(0.9)
    for frame in _frames(5, speech=False) + _frames(40, speech=True):
        loop.run_once(frame)
    assert not submitted, "committed while the owner was still speaking"
    for frame in _frames(15, speech=False):
        loop.run_once(frame)
    assert submitted == [("hello there", True)]
    assert loop.turn_commits == 1
    # 40 speech frames = 1.2 s, plus the ~0.2 s semantic commit tail.
    assert commits[0] == pytest.approx(1.2 + 0.2, abs=0.08)


def test_incomplete_turn_waits_out_the_long_timeout() -> None:
    loop, submitted, _ = _semantic_loop(0.05)
    for frame in _frames(40, speech=True):
        loop.run_once(frame)
    for frame in _frames(20, speech=False):  # 0.6 s of silence
        loop.run_once(frame)
    assert not submitted, "an unfinished sentence was cut off early"
    for frame in _frames(70, speech=False):  # past the 2.5 s hold
        loop.run_once(frame)
    assert submitted == [("hello there", True)]


def test_a_failing_endpointer_reverts_to_the_energy_path() -> None:
    """A model fault must not deafen the robot."""

    def explode(audio):
        raise RuntimeError("onnx died")

    loop, submitted, _ = _semantic_loop(0.9)
    loop.endpointer = TurnEndpointer("fake.onnx", _infer=explode)
    for frame in _frames(40, speech=True) + _frames(15, speech=False):
        loop.run_once(frame)
    # The endpointer absorbs the fault itself and says so, rather than
    # propagating; the loop keeps listening on the fixed-timeout path.
    assert "fallback" in loop.endpointer.detail.lower()
    assert loop.endpointer is not None
    for frame in _frames(80, speech=False):
        loop.run_once(frame)
    assert submitted, "a model fault left the robot permanently deaf"


# --- runtime integration ----------------------------------------------------


class _Backend:
    name = "beat-test"

    def observe(self) -> SimObservation:
        return SimObservation(
            timestamp=time.monotonic(),
            robot=RobotPose(),
            owner=OwnerTrack(),
            backend=self.name,
        )

    def move(self, command: object) -> None:
        del command

    def stop(self) -> None:
        pass

    def pose(self, pose: object) -> None:
        del pose

    def trajectory(self, skill: object) -> None:
        del skill

    def move_owner(self, dx: float, dy: float) -> None:
        del dx, dy


def _config(tmp_path: Path, extra: str = "") -> Path:
    path = tmp_path / "beat-runtime.yaml"
    path.write_text(
        f"""
skills:
  root: {REPO / "configs" / "skills"}
navigation:
  enabled: false
motion:
  backend: rl
  max_vx: 0.6
  max_vy: 0.4
  max_vyaw: 1.0
  rl:
    enabled: true
    policy_path: ""
agent:
  prompts_root: {REPO / "prompts"}
expression:
  rate_hz: 50
{extra}
memory:
  path: ":memory:"
poses: {{}}
modules: []
""",
        encoding="utf-8",
    )
    return path


def _audio() -> AudioDeviceStatus:
    return AudioDeviceStatus(
        status="text mode",
        driver="test",
        capture_hardware=False,
        connected_input=False,
        connected_output=False,
        detail="test",
    )


def test_runtime_exposes_the_expression_rate_and_beat_metrics(tmp_path: Path) -> None:
    runtime = RobotRuntime(_config(tmp_path), _Backend(), audio_status=_audio())
    try:
        assert runtime.expression_hz == 50.0
        expression = runtime.snapshot()["expression"]
        assert expression["nods_scheduled"] == 0
        assert expression["apex_error"]["count"] == 0
        assert runtime.snapshot()["speech"]["endpointing"] == "energy (VAD hangover)"
    finally:
        runtime.close()


def test_runtime_analyzes_a_chunk_and_arms_nods_on_playback(tmp_path: Path) -> None:
    """The full A4 path with no audio hardware: analyze -> token -> arm."""

    runtime = RobotRuntime(_config(tmp_path), _Backend(), audio_status=_audio())
    try:
        captured: list[tuple[bytes, object]] = []

        class _Sink:
            def enqueue(self, chunk: bytes, token: object = None) -> None:
                captured.append((chunk, token))

            def close(self, timeout: float = 3.0) -> None:
                pass

        runtime._speaker_sink = _Sink()
        runtime._enqueue_speech_chunk(_speech_wav())
        assert captured, "chunk was never queued"
        _chunk, token = captured[0]
        assert token is not None, "no prosody token attached"
        track, epoch, emotes = token
        assert track.accents and epoch == runtime.expression.speech_epoch
        assert emotes == ()

        runtime._audio_chunk_started(token)
        assert runtime.expression.beats.nods_scheduled == len(track.accents)

        # A superseded token must not schedule anything.
        runtime.expression.supersede_speech()
        before = runtime.expression.beats.nods_scheduled
        runtime._audio_chunk_started(token)
        assert runtime.expression.beats.nods_scheduled == before
    finally:
        runtime.close()


def test_unanalyzable_chunk_still_gets_spoken(tmp_path: Path) -> None:
    runtime = RobotRuntime(_config(tmp_path), _Backend(), audio_status=_audio())
    try:
        captured: list[tuple[bytes, object]] = []

        class _Sink:
            def enqueue(self, chunk: bytes, token: object = None) -> None:
                captured.append((chunk, token))

            def close(self, timeout: float = 3.0) -> None:
                pass

        runtime._speaker_sink = _Sink()
        runtime._enqueue_speech_chunk(b"not a wav file at all")
        assert len(captured) == 1
        assert captured[0][1] is None  # no beats, but the audio still queued
    finally:
        runtime.close()


def test_semantic_endpointing_config_degrades_loudly(tmp_path: Path) -> None:
    config = _config(
        tmp_path,
        extra="speech:\n  endpointing: semantic\n  vad_model: /nonexistent/silero.onnx\n",
    )
    runtime = RobotRuntime(config, _Backend(), audio_status=_audio())
    try:
        detail = runtime.snapshot()["speech"]["endpointing"]
        assert detail.startswith("semantic:")
        assert "fallback" in detail  # no turn model -> explicit fixed-timeout
        assert "unavailable" in detail  # silero weights missing -> named
        warnings = [
            event
            for event in runtime.snapshot()["events"]
            if "Silero" in str(event.get("text", ""))
        ]
        assert warnings, "missing weights were not reported"
    finally:
        runtime.close()


def test_invalid_endpointing_mode_fails_closed(tmp_path: Path) -> None:
    config = _config(tmp_path, extra="speech:\n  endpointing: telepathy\n")
    with pytest.raises(ValueError, match="endpointing"):
        RobotRuntime(config, _Backend(), audio_status=_audio())


def test_expression_thread_runs_at_the_configured_rate(tmp_path: Path) -> None:
    runtime = RobotRuntime(_config(tmp_path), _Backend(), audio_status=_audio())
    try:
        runtime.start()
        time.sleep(0.6)
        components = runtime.latency_snapshot()["components"]
        assert "ExpressionLayer" in components, "expression channel never ran"
        # ~50 Hz for 0.6 s is ~30 ticks; allow generous scheduling slack.
        assert components["ExpressionLayer"]["count"] >= 10, components["ExpressionLayer"]
    finally:
        runtime.close()


def test_lag_compensation_shifts_apexes_earlier() -> None:
    track = analyze_pcm16(_speech_pcm(), SR)
    plain = BeatLayer()
    lead = BeatLayer(lag_compensation_s=0.05)
    plain.arm(track, playback_start_s=10.0, epoch=0)
    lead.arm(track, playback_start_s=10.0, epoch=0)
    assert lead._nods[0].apex_s == pytest.approx(plain._nods[0].apex_s - 0.05)


def test_beat_layer_rejects_unsafe_configuration() -> None:
    with pytest.raises(ValueError, match="amplitude"):
        BeatLayer(base_amplitude_rad=math.radians(45.0))
    with pytest.raises(ValueError, match="lag compensation"):
        BeatLayer(lag_compensation_s=5.0)
    with pytest.raises(ValueError, match="rise and fall"):
        BeatLayer(rise_s=0.0)


def test_wav_and_pcm_analysis_agree_for_the_scheduler() -> None:
    from_wav = analyze_wav_chunk(_speech_wav())
    from_pcm = analyze_pcm16(_speech_pcm(), SR)
    assert len(from_wav.accents) == len(from_pcm.accents)
