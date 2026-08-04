"""Phase 2 voice transport: VAD, microphone loop, speaker sink, chunked TTS."""

from __future__ import annotations

import io
import threading
import time
import wave

import numpy as np
import pytest

from parcel_robot.providers import (
    PiperSpeechProvider,
    SentenceChunkedSynthesizer,
    SpeechServiceError,
    build_speech_stack,
    split_speech_sentences,
)
from parcel_robot.voice_audio import (
    FRAME_SAMPLES,
    EnergyVad,
    MicrophoneVoiceLoop,
    SpeakerSink,
    pcm16_wav,
    resolve_audio_device,
)
from parcel_robot.voice_pipeline import DuplexVoiceSession


def _silence(frames: int = 1) -> np.ndarray:
    rng = np.random.default_rng(0)
    return rng.integers(-25, 25, size=FRAME_SAMPLES * frames, dtype=np.int16)


def _speech_frame(amplitude: int = 6000) -> np.ndarray:
    t = np.arange(FRAME_SAMPLES, dtype=np.float64)
    wave_ = amplitude * np.sin(2 * np.pi * 220.0 * t / 16000.0)
    return wave_.astype(np.int16)


class _FakeRecognizer:
    def __init__(self, transcript: str = "come here"):
        self.transcript = transcript
        self.calls: list[bytes] = []

    def transcribe(self, wav_audio: bytes) -> str:
        self.calls.append(wav_audio)
        return self.transcript


def test_vad_segments_one_utterance() -> None:
    vad = EnergyVad(min_speech_frames=2, hangover_frames=3)
    events = []
    for _ in range(5):
        events += vad.process(_silence())
    for _ in range(6):
        events += vad.process(_speech_frame())
    for _ in range(4):
        events += vad.process(_silence())
    kinds = [event.kind for event in events]
    assert kinds == ["speech_start", "speech_end"]
    utterance = events[-1].utterance
    assert len(utterance) >= 6 * FRAME_SAMPLES * 2  # speech plus hangover tail


def test_vad_noise_floor_quiet_adaptation_dominates_slow_upward_leak() -> None:
    # 2026-08-04 review fix: a strictly quiet-only floor locked the VAD into
    # endless 30 s max-length flushes under sustained ambient noise. The floor
    # now leaks upward ~50x slower on voiced frames than it settles downward
    # on quiet ones, so a short utterance barely moves the threshold while a
    # shifted ambient level eventually re-baselines.
    vad = EnergyVad()
    initial = vad.noise_rms
    for _ in range(50):
        vad.process(_silence())
    adapted = vad.noise_rms
    assert adapted < initial  # settled toward the true quiet floor
    for _ in range(30):
        vad.process(_speech_frame())
    after_speech = vad.noise_rms
    assert after_speech > adapted  # upward-only slow leak exists
    # A short utterance must not raise the detection threshold anywhere near
    # actual speech level: speech stays detectable.
    assert after_speech * vad.threshold_scale < EnergyVad.frame_rms(_speech_frame())


def test_vad_sustained_noise_cannot_flush_forever() -> None:
    # The review's failure loop: ambient noise above threshold made every
    # frame voiced, the floor froze, and 30 s noise "utterances" shipped to
    # STT back-to-back until the noise stopped. The max-length flush now
    # re-seeds the floor toward the segment RMS, breaking the loop.
    vad = EnergyVad(max_utterance_frames=50)
    for _ in range(50):
        vad.process(_silence())
    rng = np.random.default_rng(7)

    def _noise() -> np.ndarray:
        return rng.integers(-900, 900, size=FRAME_SAMPLES, dtype=np.int16)

    flushes = 0
    for _ in range(1000):
        for event in vad.process(_noise()):
            if event.kind == "speech_end":
                flushes += 1
    assert flushes <= 2  # first flush re-seeds the floor; the loop dies


def test_microphone_loop_submits_final_transcript() -> None:
    recognizer = _FakeRecognizer("sit down please")
    submitted: list[tuple[str, bool]] = []
    loop = MicrophoneVoiceLoop(
        recognizer=recognizer,
        submit_text=lambda text, is_final: submitted.append((text, is_final)),
        barge_in=lambda: None,
        playback_active=lambda: False,
        vad=EnergyVad(min_speech_frames=2, hangover_frames=3),
    )
    for _ in range(5):
        loop.run_once(_silence())
    for _ in range(20):
        loop.run_once(_speech_frame())
    for _ in range(4):
        loop.run_once(_silence())
    assert submitted == [("sit down please", True)]
    assert loop.utterances_submitted == 1
    # The recognizer received a valid WAV of the segmented utterance.
    with wave.open(io.BytesIO(recognizer.calls[0]), "rb") as reader:
        assert reader.getframerate() == 16000
        assert reader.getnframes() > FRAME_SAMPLES * 10


def test_microphone_loop_triggers_barge_in_over_echo_guard() -> None:
    barge_ins: list[bool] = []
    loop = MicrophoneVoiceLoop(
        recognizer=_FakeRecognizer(),
        submit_text=lambda text, is_final: None,
        barge_in=lambda: barge_ins.append(True),
        playback_active=lambda: True,
        vad=EnergyVad(min_speech_frames=2, hangover_frames=3),
        echo_guard_scale=2.0,
    )
    # Quiet frames during playback are suppressed by the echo guard.
    for _ in range(5):
        loop.run_once(_silence())
    assert loop.echo_guard_suppressions >= 5
    assert not barge_ins
    # Loud owner speech during playback crosses the guard and barges in.
    for _ in range(3):
        loop.run_once(_speech_frame(12000))
    assert barge_ins


def test_speaker_sink_plays_and_interrupts() -> None:
    played: list[tuple[int, int]] = []
    sink = SpeakerSink(player=lambda pcm, rate: played.append((len(pcm), rate)))
    sink.enqueue(pcm16_wav(b"\x00\x01" * 4000, 22050))
    deadline = time.monotonic() + 2.0
    while not played and time.monotonic() < deadline:
        time.sleep(0.01)
    assert played and played[0][1] == 22050
    sink.interrupt()
    assert sink.playback_active is False
    sink.close()


def test_split_speech_sentences() -> None:
    reply = "On my way. I will avoid the road; stay put! Understood?"
    parts = split_speech_sentences(reply)
    assert parts == ["On my way.", "I will avoid the road;", "stay put!", "Understood?"]
    long_run = "word " * 100
    chunks = split_speech_sentences(long_run, max_chars=60)
    assert all(len(chunk) <= 66 for chunk in chunks)
    assert " ".join(chunks) == long_run.strip()


class _RecordingSynthesizer:
    def __init__(self) -> None:
        self.requests: list[str] = []
        self.delay_s = 0.0

    def synthesize(self, text: str) -> bytes:
        self.requests.append(text)
        if self.delay_s:
            time.sleep(self.delay_s)
        return b"RIFFfake" + text.encode()


class _EchoAgent:
    def __init__(self, reply: str) -> None:
        self.reply = reply

    def handle_text(self, transcript: str) -> str:
        return self.reply


def test_session_streams_sentence_chunks_and_cancels_between_sentences() -> None:
    synthesizer = _RecordingSynthesizer()
    chunks: list[bytes] = []
    stages: list[str] = []
    session = DuplexVoiceSession(
        _EchoAgent("First sentence. Second sentence. Third sentence."),
        synthesizer=SentenceChunkedSynthesizer(synthesizer),
        audio_chunk_player=chunks.append,
        on_stage=lambda stage: stages.append(stage.name),
    )
    try:
        session.submit_text("hello", is_final=True)
        assert session.wait_until_idle(timeout=5.0)
        assert synthesizer.requests == [
            "First sentence.",
            "Second sentence.",
            "Third sentence.",
        ]
        assert len(chunks) == 3
        assert "tts_first_chunk" in stages
        assert "audio_first_playback" in stages
    finally:
        session.close()


def test_barge_in_stops_pending_sentences() -> None:
    synthesizer = _RecordingSynthesizer()
    synthesizer.delay_s = 0.15
    chunks: list[bytes] = []
    first_chunk = threading.Event()

    def player(chunk: bytes) -> None:
        chunks.append(chunk)
        first_chunk.set()

    session = DuplexVoiceSession(
        _EchoAgent("Alpha one. Beta two. Gamma three. Delta four. Epsilon five."),
        synthesizer=SentenceChunkedSynthesizer(synthesizer),
        audio_chunk_player=player,
    )
    try:
        session.submit_text("talk to me", is_final=True)
        assert first_chunk.wait(timeout=5.0)
        session.barge_in()
        assert session.wait_until_idle(timeout=5.0)
        # Synthesis stopped at a sentence boundary rather than finishing all 5.
        assert len(synthesizer.requests) < 5
    finally:
        session.close()


def test_piper_provider_fails_closed_when_missing() -> None:
    piper = PiperSpeechProvider(binary_path="/nonexistent/piper", voice_path="/nonexistent/v.onnx")
    assert piper.available() is False
    with pytest.raises(SpeechServiceError, match="not installed"):
        piper.synthesize("hello")


def test_build_speech_stack_degrades_to_text_mode() -> None:
    stack = build_speech_stack(
        {
            "mode": "auto",
            "stt_provider": "whisper_cpp",
            "whisper_url": "http://127.0.0.1:1",  # closed port
            "tts_provider": "piper",
            "piper_binary": "/nonexistent/piper",
            "piper_voice": "/nonexistent/voice.onnx",
        }
    )
    assert stack.recognizer is None
    assert stack.synthesizer is None
    assert "unreachable" in stack.stt_detail
    assert "not installed" in stack.tts_detail


def test_build_speech_stack_audio_mode_fails_closed() -> None:
    with pytest.raises(SpeechServiceError, match="requires healthy"):
        build_speech_stack(
            {
                "mode": "audio",
                "whisper_url": "http://127.0.0.1:1",
                "tts_provider": "piper",
                "piper_binary": "/nonexistent/piper",
                "piper_voice": "/nonexistent/voice.onnx",
            }
        )


def test_speaker_sink_stale_enqueue_after_interrupt_stays_suppressed() -> None:
    # 2026-08-04 review fix: enqueue() cleared the interrupt latch, so a
    # chunk enqueued by an output thread that lost the race against a
    # barge-in flush un-interrupted the sink and played cancelled speech.
    played: list[tuple[bytes, int]] = []
    sink = SpeakerSink(player=lambda pcm, rate: played.append((pcm, rate)))
    sink.interrupt()
    sink.enqueue(pcm16_wav(b"\x01\x00" * 1600))
    time.sleep(0.15)
    assert played == []

    sink.begin_utterance()  # only a NEW turn re-arms playback
    sink.enqueue(pcm16_wav(b"\x01\x00" * 1600))
    deadline = time.time() + 1.0
    while not played and time.time() < deadline:
        time.sleep(0.01)
    assert played
    sink.close()


def test_speaker_sink_playback_active_survives_interrupt_until_player_returns() -> None:
    # 2026-08-04 review fix: interrupt() cleared _playing while the in-flight
    # chunk was still audible, disabling the echo guard so the robot could
    # transcribe its own speech as an owner command.
    release = threading.Event()
    started = threading.Event()

    def blocking_player(pcm: bytes, rate: int) -> None:
        del pcm, rate
        started.set()
        assert release.wait(1.0)

    sink = SpeakerSink(player=blocking_player)
    sink.begin_utterance()
    sink.enqueue(pcm16_wav(b"\x01\x00" * 1600))
    assert started.wait(1.0)
    assert sink.playback_active
    sink.interrupt()
    assert sink.playback_active  # robot still audibly speaking
    release.set()
    deadline = time.time() + 1.0
    while sink.playback_active and time.time() < deadline:
        time.sleep(0.01)
    assert not sink.playback_active
    sink.close()


def test_microphone_loop_surfaces_capture_failure() -> None:
    # 2026-08-04 review fix: a capture failure inside the worker thread was
    # swallowed as a log line while status kept reporting an active mic.
    failures: list[Exception] = []

    def frames():
        yield _silence()
        raise RuntimeError("device unplugged")

    loop = MicrophoneVoiceLoop(
        recognizer=_FakeRecognizer(),
        submit_text=lambda text, is_final: None,
        barge_in=lambda: None,
        playback_active=lambda: False,
        frames=frames(),
        on_failure=failures.append,
    )
    loop.start()
    deadline = time.time() + 1.0
    while not failures and time.time() < deadline:
        time.sleep(0.01)
    assert failures and "unplugged" in str(failures[0])
    assert not loop.running
    loop.close()


# --- card B1: physical audio device selection -------------------------------

_DEVICES = [
    {"name": "HDA Intel PCH", "max_input_channels": 2, "max_output_channels": 2},
    {"name": "ReSpeaker XVF3800 4-Mic Array", "max_input_channels": 4,
     "max_output_channels": 2},
    {"name": "HDMI Output", "max_input_channels": 0, "max_output_channels": 2},
    {"name": "Loopback capture", "max_input_channels": 2, "max_output_channels": 0},
]


def _query() -> list[dict[str, object]]:
    return list(_DEVICES)


def test_unset_device_uses_the_system_default_without_querying() -> None:
    def explode() -> list[dict[str, object]]:
        raise AssertionError("must not enumerate devices when none is configured")

    assert resolve_audio_device(None, kind="input", query=explode) == (None, "system default")
    assert resolve_audio_device("  ", kind="output", query=explode) == (
        None,
        "system default",
    )


def test_device_resolves_by_name_substring_case_insensitively() -> None:
    index, detail = resolve_audio_device("respeaker", kind="input", query=_query)
    assert index == 1
    assert "ReSpeaker" in detail and "index 1" in detail


def test_device_resolves_by_index() -> None:
    index, detail = resolve_audio_device(1, kind="output", query=_query)
    assert index == 1
    assert "index 1" in detail


def test_device_kind_filters_by_channel_direction() -> None:
    # HDMI has no input channels; Loopback has no output channels.
    with pytest.raises(OSError, match="no input device matches"):
        resolve_audio_device("HDMI", kind="input", query=_query)
    with pytest.raises(OSError, match="no output device matches"):
        resolve_audio_device("Loopback", kind="output", query=_query)


def test_unknown_ambiguous_and_out_of_range_devices_fail_loudly() -> None:
    with pytest.raises(OSError, match="no input device matches"):
        resolve_audio_device("nonexistent", kind="input", query=_query)
    with pytest.raises(OSError, match="ambiguous"):
        resolve_audio_device("h", kind="output", query=_query)
    with pytest.raises(OSError, match="out of range"):
        resolve_audio_device(99, kind="input", query=_query)
    with pytest.raises(OSError, match="no input channels"):
        resolve_audio_device(2, kind="input", query=_query)


def test_missing_portaudio_only_fails_when_a_device_was_requested() -> None:
    def unavailable() -> list[dict[str, object]]:
        raise OSError("PortAudio library not found")

    assert resolve_audio_device(None, kind="input", query=unavailable) == (
        None,
        "system default",
    )
    with pytest.raises(OSError, match="cannot enumerate audio devices"):
        resolve_audio_device("ReSpeaker", kind="input", query=unavailable)


def test_bad_device_kind_and_boolean_spec_are_rejected() -> None:
    with pytest.raises(ValueError, match="device kind"):
        resolve_audio_device(None, kind="sideways")
    with pytest.raises(OSError, match="not a boolean"):
        resolve_audio_device(True, kind="input", query=_query)


def test_sinks_and_loops_carry_the_resolved_device() -> None:
    sink = SpeakerSink(player=lambda pcm, rate: None, device=3)
    try:
        assert sink.device == 3
    finally:
        sink.close()
    loop = MicrophoneVoiceLoop(
        recognizer=_FakeRecognizer(),
        submit_text=lambda text, is_final: None,
        barge_in=lambda: None,
        playback_active=lambda: False,
        frames=iter(()),
        device=1,
    )
    assert loop.device == 1
