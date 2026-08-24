import json
import threading
import time
from pathlib import Path
from urllib.error import URLError

import msgpack
import pytest

from parcel_robot import providers
from parcel_robot.brain.contracts import ObservationSnapshot
from parcel_robot.brain.router import DeterministicIntentRouter
from parcel_robot.providers import (
    FishSpeechProvider,
    LlamaCppProvider,
    ModelRequestCancelled,
    SpeechServiceError,
)
from parcel_robot.voice_pipeline import DuplexVoiceSession

REPO = Path(__file__).resolve().parents[1]


class FakeResponse:
    def __init__(self, chunks):
        self.chunks = list(chunks)
        self.closed = False

    def read(self, _size=-1):
        return self.chunks.pop(0) if self.chunks else b""

    def close(self):
        self.closed = True

    def __iter__(self):
        return iter(self.chunks)

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


def test_llama_provider_streams_for_true_first_output_timing(monkeypatch):
    requests = []
    response = FakeResponse(
        [
            b'data: {"choices":[{"delta":{"content":"{\\"reply\\":\\"Hi!\\","}}]}\n',
            b'data: {"choices":[{"delta":{"content":"\\"tool_calls\\":[],\\"intent\\":\\"conversation\\","}}]}\n',
            b'data: {"choices":[{"delta":{"content":"\\"affect\\":null,\\"next_action\\":null}"}}]}\n',
            b'data: {"choices":[],"usage":{"prompt_tokens":12,"completion_tokens":9,"total_tokens":21}}\n',
            b"data: [DONE]\n",
        ]
    )

    def fake_urlopen(request, timeout):
        requests.append((request, timeout))
        return response

    monkeypatch.setattr(providers, "urlopen", fake_urlopen)
    provider = LlamaCppProvider(base_url="http://reasoner.local", timeout=4)
    decision = provider.decide("hello", [], [])

    assert decision.reply == "Hi!"
    request, timeout = requests[0]
    payload = json.loads(request.data)
    assert payload["stream"] is True
    assert payload["stream_options"] == {"include_usage": True}
    assert payload["max_tokens"] == 256
    assert payload["reasoning_effort"] == "none"
    assert payload["chat_template_kwargs"] == {"enable_thinking": False}
    assert timeout == 4
    assert provider.last_metrics["model_streaming"] is True
    assert provider.last_metrics["reasoning_first_output_estimated"] is False
    assert provider.last_metrics["model_ttft_ms"] is not None
    assert provider.last_metrics["total_tokens"] == 21


def test_llama_provider_reuses_backbone_for_separate_plan_mode(monkeypatch):
    now = time.monotonic()
    frame = DeterministicIntentRouter().route(
        "Walk to the sidewalk and then wait.", turn_id="turn-plan-1"
    )
    snapshot = ObservationSnapshot.from_mapping(
        {
            "schema_version": 1,
            "snapshot_id": "snapshot-plan-1",
            "captured_at_monotonic_s": now,
            "camera": {
                "name": "camera",
                "available": True,
                "fresh": True,
                "source": "test_camera",
                "observed_at_monotonic_s": now,
                "age_ms": 0.0,
            },
            "lidar": {
                "name": "lidar",
                "available": True,
                "fresh": True,
                "source": "test_lidar",
                "observed_at_monotonic_s": now,
                "age_ms": 0.0,
            },
            "robot": {
                "moving": False,
                "controller_state": "ready",
                "x": 0.0,
                "y": 0.0,
                "z": 0.0,
                "yaw_rad": 0.0,
            },
            "safety": {
                "emergency_stopped": False,
                "collision_imminent": False,
                "telemetry_fresh": True,
                "nearest_obstacle_m": 3.0,
                "nearest_person_m": None,
            },
            "battery": {"state": "unavailable", "percent": None, "source": "unavailable"},
            "task": {
                "state": "idle",
                "task_id": None,
                "plan_revision": None,
                "step_id": None,
                "at_checkpoint": True,
            },
            "resource_leases": [],
            "entities": [],
        }
    )
    raw_plan = {
        "schema_version": 1,
        "task_id": "task-plan-1",
        "plan_revision": 1,
        "source_turn_id": "turn-plan-1",
        "goal": {
            "relation": "hold",
            "target": {"kind": "current_pose", "query": ""},
            "tolerance_m": 0.0,
        },
        "invariants": ["keep_collision_margin"],
        "steps": [
            {
                "id": "hold",
                "skill": "Hold",
                "arguments": {},
                "preconditions": ["base_available"],
                "success": {
                    "fact": "motion_stopped",
                    "target": None,
                    "tolerance_m": None,
                    "confidence_min": None,
                },
                "timeout_s": 5.0,
                "max_attempts": 1,
                "recovery": ["safe_stop"],
                "resources": ["base"],
                "interruptibility": "immediate",
            }
        ],
        "requested_interrupt": "at_checkpoint",
    }
    event = json.dumps({"choices": [{"delta": {"content": json.dumps(raw_plan)}}]})
    response = FakeResponse([f"data: {event}\n".encode(), b"data: [DONE]\n"])
    requests = []

    def fake_urlopen(request, timeout):
        requests.append((request, timeout))
        return response

    monkeypatch.setattr(providers, "urlopen", fake_urlopen)
    provider = LlamaCppProvider(
        model="shared-gemma",
        plan_timeout=12,
        plan_max_tokens=768,
    )
    schema = json.loads((REPO / "prompts/schemas/plan_ir_v1.schema.json").read_text())

    plan = provider.plan(
        "Walk to the sidewalk and then wait.",
        intent_frame=frame,
        observation=snapshot,
        skill_contracts={"schema_version": 1, "skills": [{"name": "Hold"}]},
        response_schema=schema,
        system_prompt="Return PlanIR only.",
    )

    assert plan.task_id == "task-plan-1"
    request, timeout = requests[0]
    payload = json.loads(request.data)
    planner_input = json.loads(payload["messages"][-1]["content"])
    assert payload["model"] == "shared-gemma"
    assert payload["max_tokens"] == 768
    assert payload["chat_template_kwargs"] == {"enable_thinking": False}
    assert payload["temperature"] == 0.0
    assert payload["response_format"]["schema"]["title"] == "Parcel PlanIR v1"
    assert planner_input["original_transcript"] == "Walk to the sidewalk and then wait."
    assert timeout == 12
    assert provider.last_metrics["model_mode"] == "plan"


def test_llama_provider_bounds_stream_and_validates_tuning(monkeypatch):
    response = FakeResponse([b'data: {"choices":[{"delta":{"content":"x"}}]}\n'] * 65)
    monkeypatch.setattr(providers, "urlopen", lambda request, timeout: response)
    provider = LlamaCppProvider(max_stream_events=64)

    with pytest.raises(ValueError, match="event limit"):
        provider.decide("hello", [], [])

    with pytest.raises(ValueError, match="max_tokens"):
        LlamaCppProvider(max_tokens=4)


def test_llama_context_budget_keeps_complete_newest_turns():
    context = [
        {"role": "user", "content": "old question"},
        {"role": "assistant", "content": "old answer"},
        {"role": "user", "content": "new question"},
        {"role": "assistant", "content": "new answer"},
    ]

    bounded = providers._bounded_chat_context(context, max_messages=4, max_chars=35)

    assert bounded == [
        {"role": "user", "content": "new question"},
        {"role": "assistant", "content": "new answer"},
    ]


def test_llama_stream_can_be_cancelled_by_barge_in(monkeypatch):
    first_event = threading.Event()
    release = threading.Event()

    class BlockingResponse(FakeResponse):
        def __iter__(self):
            yield b'data: {"choices":[{"delta":{"reasoning_content":"thinking"}}]}\n'
            first_event.set()
            assert release.wait(2)
            yield b'data: {"choices":[{"delta":{"content":"{}"}}]}\n'

    monkeypatch.setattr(
        providers,
        "urlopen",
        lambda request, timeout: BlockingResponse([]),
    )
    provider = LlamaCppProvider()
    errors = []

    def decide() -> None:
        try:
            provider.decide("hello", [], [])
        except Exception as error:  # noqa: BLE001 - asserted below
            errors.append(error)

    worker = threading.Thread(target=decide)
    worker.start()
    assert first_event.wait(1)
    provider.cancel_current()
    release.set()
    worker.join(2)

    assert not worker.is_alive()
    assert isinstance(errors[0], ModelRequestCancelled)


def test_duplex_session_runs_without_audio_and_executes_only_final_text():
    handled = []
    turns = []
    partials = []
    stages = []

    class Agent:
        def handle_text(self, text):
            handled.append(text)
            assert isinstance(text, str)
            return f"reply:{text}"

    with DuplexVoiceSession(
        Agent(),
        on_turn=turns.append,
        on_partial=partials.append,
        on_stage=stages.append,
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
    assert [stage.name for stage in stages] == [
        "query_end",
        "reasoning_start",
        "reasoning_response",
        "response_logged",
        "turn_complete",
    ]


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
    # 2026-08-04 review fix: the interrupt now also fires with no live output
    # state (the sink can still hold queued audio in the drain window), so a
    # supersede sequence may flush more than once. Flushing is idempotent —
    # what matters is that it fired.
    assert interrupted and all(interrupted)


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


def test_newest_final_compacts_pending_reasoning_queue():
    started = threading.Event()
    release = threading.Event()
    handled = []
    stages = []

    class Agent:
        def handle_text(self, text):
            handled.append(text)
            if text == "first":
                started.set()
                assert release.wait(2)
            return f"reply:{text}"

        def cancel_reasoning(self):
            return None

    with DuplexVoiceSession(Agent(), on_stage=stages.append) as session:
        session.submit_text("first")
        assert started.wait(1)
        session.submit_text("second")
        session.submit_text("third")
        release.set()
        assert session.wait_until_idle(2)

    assert handled == ["first", "third"]
    second_stages = [stage.name for stage in stages if stage.turn_id == 2]
    assert second_stages == ["query_end", "superseded", "turn_complete"]


def test_audio_handoff_is_not_reported_when_sink_rejects_chunk():
    stages = []
    errors = []

    class Agent:
        def handle_text(self, text):
            return "hello"

    class Synthesizer:
        def synthesize(self, text):
            return b"RIFF-audio"

    def reject(_chunk):
        raise OSError("sink unavailable")

    with DuplexVoiceSession(
        Agent(),
        synthesizer=Synthesizer(),
        audio_chunk_player=reject,
        on_stage=stages.append,
        on_error=errors.append,
    ) as session:
        session.submit_text("hello")
        assert session.wait_until_idle(2)

    names = [stage.name for stage in stages]
    assert "tts_first_chunk" in names
    assert "audio_first_playback" not in names
    assert "error" in names
    assert isinstance(errors[0], OSError)


def test_barge_in_flushes_queued_audio_after_output_worker_exits() -> None:
    """2026-08-04 sprint review, drain window: with faster-than-realtime TTS
    the output worker exits while the SpeakerSink still holds queued chunks.
    A barge-in in that window must still flush the sink — previously it was
    skipped entirely and the robot talked to the end of its queue."""

    import time as _time

    from parcel_robot.providers import SentenceChunkedSynthesizer
    from parcel_robot.voice_audio import SpeakerSink, pcm16_wav

    class _InstantSynth:
        def synthesize(self, text: str) -> bytes:
            return pcm16_wav(b"\x01\x00" * 1600)  # 0.1 s of audio per sentence

    class _SixSentenceAgent:
        def handle_text(self, text: str) -> str:
            return "One. Two. Three. Four. Five. Six."

    played: list[int] = []
    release = threading.Event()

    def slow_player(pcm: bytes, rate: int) -> None:
        played.append(len(pcm))
        release.wait(0.4)  # each chunk takes ~0.4 s to "play"

    sink = SpeakerSink(player=slow_player)
    session = DuplexVoiceSession(
        _SixSentenceAgent(),
        synthesizer=SentenceChunkedSynthesizer(_InstantSynth()),
        audio_chunk_player=sink.enqueue,
        audio_interrupt=sink.interrupt,
        audio_turn_start=sink.begin_utterance,
    )
    try:
        session.submit_text("hello", is_final=True)
        # All six chunks synthesize near-instantly; the output worker goes
        # idle while most are still queued behind the slow player.
        assert session.wait_until_idle(timeout=5.0)
        assert len(played) < 6, "player outran the test; slow it down"

        session.barge_in()
        _time.sleep(1.0)
        # The queue was flushed: at most one in-flight chunk finished after
        # the barge-in, the rest never played.
        assert len(played) <= 3, f"queued chunks kept playing: {len(played)}"
    finally:
        release.set()
        session.close()
        sink.close()
