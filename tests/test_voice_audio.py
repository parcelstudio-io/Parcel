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


def test_vad_noise_floor_adapts_only_when_quiet() -> None:
    vad = EnergyVad()
    initial = vad.noise_rms
    for _ in range(50):
        vad.process(_silence())
    adapted = vad.noise_rms
    assert adapted < initial  # settled toward the true quiet floor
    for _ in range(30):
        vad.process(_speech_frame())
    assert vad.noise_rms == pytest.approx(adapted)  # speech never raises the floor


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
