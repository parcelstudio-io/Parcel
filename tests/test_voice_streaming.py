import json
import threading
from urllib.error import URLError

import msgpack
import pytest

from parcel_robot import providers
from parcel_robot.providers import FishSpeechProvider, SpeechServiceError
from parcel_robot.voice_pipeline import DuplexVoiceSession


class FakeResponse:
    def __init__(self, chunks):
        self.chunks = list(chunks)
        self.closed = False

    def read(self, _size=-1):
        return self.chunks.pop(0) if self.chunks else b""

    def close(self):
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def test_fish_provider_sends_msgpack_and_returns_wav(monkeypatch):
    requests = []
    response = FakeResponse([b"RIFF-complete-wav"])

    def fake_urlopen(request, timeout):
        requests.append((request, timeout))
        return response

    monkeypatch.setattr(providers, "urlopen", fake_urlopen)
    provider = FishSpeechProvider(
        base_url="http://fish.local/",
        reference_id="parcel-voice",
        api_key="secret",
        timeout=9,
    )

    assert provider.synthesize(" Hello owner ") == b"RIFF-complete-wav"
    request, timeout = requests[0]
    payload = msgpack.unpackb(request.data, raw=False)
    assert request.full_url == "http://fish.local/v1/tts?format=msgpack"
    assert request.get_header("Content-type") == "application/msgpack"
    assert request.get_header("Authorization") == "Bearer secret"
    assert timeout == 9
    assert payload["text"] == "Hello owner"
    assert payload["format"] == "wav"
    assert payload["streaming"] is False
    assert payload["reference_id"] == "parcel-voice"
    assert payload["use_memory_cache"] == "on"
    assert response.closed


def test_fish_provider_stream_is_cancellable_wav_pcm(monkeypatch):
    requests = []
    response = FakeResponse([b"RIFF-header", b"pcm-frames", b""])

    def fake_urlopen(request, timeout):
        requests.append(request)
        return response

    monkeypatch.setattr(providers, "urlopen", fake_urlopen)
    provider = FishSpeechProvider(chunk_size=128)
    stream = provider.synthesize_stream("Following you")

    assert next(stream) == b"RIFF-header"
    payload = msgpack.unpackb(requests[0].data, raw=False)
    assert payload["streaming"] is True
    assert payload["format"] == "wav"
    stream.cancel()
    with pytest.raises(StopIteration):
        next(stream)
    assert response.closed


def test_fish_provider_health_and_offline_errors_are_graceful(monkeypatch):
    monkeypatch.setattr(
        providers,
        "urlopen",
        lambda request, timeout: FakeResponse([json.dumps({"status": "ok"}).encode()]),
    )
    provider = FishSpeechProvider()
    assert provider.health().available

    def offline(request, timeout):
        raise URLError("not running")

    monkeypatch.setattr(providers, "urlopen", offline)
    health = provider.health()
    assert not health.available
    assert "unavailable" in health.detail
    with pytest.raises(SpeechServiceError, match="Fish Speech request failed"):
        provider.synthesize("hello")


def test_duplex_session_runs_without_audio_and_executes_only_final_text():
    handled = []
    turns = []
    partials = []

    class Agent:
        def handle_text(self, text):
            handled.append(text)
            assert isinstance(text, str)
            return f"reply:{text}"

    with DuplexVoiceSession(
        Agent(),
        on_turn=turns.append,
        on_partial=partials.append,
    ) as session:
        assert session.submit_text("follow", is_final=False) is None
        turn_id = session.submit_text("follow me")
        assert turn_id == 1
        assert session.wait_until_idle(2)

    assert partials == ["follow"]
    assert handled == ["follow me"]
    assert turns[0].transcript == "follow me"
    assert turns[0].reply == "reply:follow me"
    assert not turns[0].superseded


def test_duplex_session_barge_in_cancels_active_stream():
    first_chunk = threading.Event()
    released = threading.Event()
    cancelled = threading.Event()
    played = []
    interrupted = []

    class Agent:
        def handle_text(self, text):
            return "I am following you"

    class BlockingStream:
        def __init__(self, cancel_event):
            self.cancel_event = cancel_event
            self.first = True

        def __iter__(self):
            return self

        def __next__(self):
            if self.first:
                self.first = False
                return b"RIFF-header"
            released.wait(2)
            if self.cancel_event.is_set() or cancelled.is_set():
                raise StopIteration
            return b"pcm"

        def cancel(self):
            cancelled.set()
            released.set()

        close = cancel

    class Synthesizer:
        def synthesize(self, text):
            raise AssertionError("streaming synthesis should be used")

        def synthesize_stream(self, text, *, cancel_event=None):
            return BlockingStream(cancel_event)

    def play(chunk):
        played.append(chunk)
        first_chunk.set()

    with DuplexVoiceSession(
        Agent(),
        synthesizer=Synthesizer(),
        audio_chunk_player=play,
        audio_interrupt=lambda: interrupted.append(True),
    ) as session:
        session.submit_text("follow me")
        assert first_chunk.wait(2)
        session.submit_text("st", is_final=False)
        assert session.wait_until_idle(2)

    assert played == [b"RIFF-header"]
    assert cancelled.is_set()
    assert interrupted == [True]


def test_new_turn_suppresses_stale_reply_audio():
    reasoning_started = threading.Event()
    release_reasoning = threading.Event()
    handled = []
    spoken = []
    turns = []

    class Agent:
        def handle_text(self, text):
            handled.append(text)
            if text == "first command":
                reasoning_started.set()
                release_reasoning.wait(2)
            return f"reply:{text}"

    class Synthesizer:
        def synthesize(self, text):
            return text.encode()

        def synthesize_stream(self, text, *, cancel_event=None):
            return iter([text.encode()])

    with DuplexVoiceSession(
        Agent(),
        synthesizer=Synthesizer(),
        audio_chunk_player=spoken.append,
        on_turn=turns.append,
    ) as session:
        session.submit_text("first command")
        assert reasoning_started.wait(2)
        session.submit_text("second command")
        release_reasoning.set()
        assert session.wait_until_idle(2)

    assert handled == ["first command", "second command"]
    assert turns[0].superseded
    assert not turns[1].superseded
    assert spoken == [b"reply:second command"]
