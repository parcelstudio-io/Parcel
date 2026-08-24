"""D-O1–D-O3: filler policy, fail-closed config, coordinator, logging."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

from parcel_robot.duplex.act_codec import ActTokenCodec, default_twist_bins
from parcel_robot.duplex.config import DuplexConfig
from parcel_robot.duplex.consumer import DuplexFrameConsumer
from parcel_robot.duplex.coordinator import DuplexCoordinator
from parcel_robot.duplex.filler_policy import FillerPolicy
from parcel_robot.duplex.fillers import FillerPool
from parcel_robot.duplex.session_log import DuplexSessionLog
from parcel_robot.providers import SentenceChunkedSynthesizer
from parcel_robot.voice.pipeline import DuplexVoiceSession, VoiceStage


def test_duplex_config_fail_closed_unknown_key() -> None:
    with pytest.raises(ValueError, match="unknown duplex"):
        DuplexConfig.from_mapping({"enabled": True, "not_a_key": 1})


def test_filler_policy_predictive_and_watchdog() -> None:
    policy = FillerPolicy(FillerPool.default(rng_seed=1), watchdog_s=0.7, ceiling_s=2.0)
    policy.on_turn_start(now_s=0.0)
    fire = policy.predictive_fire(now_s=0.05, reason="predictive")
    assert fire is not None
    assert fire.reason == "predictive"
    policy.on_filler_audible(now_s=0.1)
    assert policy.filler_latency_s == pytest.approx(0.1)
    assert policy.poll_watchdog(now_s=1.0) is None  # already fired


def test_filler_watchdog_fires_without_predictive() -> None:
    policy = FillerPolicy(FillerPool.default(rng_seed=2), watchdog_s=0.7, ceiling_s=2.0)
    policy.on_turn_start(now_s=0.0)
    assert policy.poll_watchdog(now_s=0.69) is None
    fire = policy.poll_watchdog(now_s=0.70)
    assert fire is not None
    assert fire.reason == "watchdog"


def test_ceiling_breach_when_mute_past_two_seconds() -> None:
    policy = FillerPolicy(FillerPool.default(rng_seed=3), watchdog_s=0.7, ceiling_s=2.0)
    policy.on_turn_start(now_s=0.0)
    assert policy.poll_ceiling_breach(now_s=1.9) is False
    assert policy.poll_ceiling_breach(now_s=2.0) is True
    assert policy.response_ceiling_breaches == 1
    assert policy.poll_ceiling_breach(now_s=2.5) is False  # once per turn


def test_clause_boundary_handoff_queues_reply() -> None:
    policy = FillerPolicy(FillerPool.default(rng_seed=4))
    policy.note_clause_boundary_pending("real answer")
    assert policy.awaiting_clause_boundary
    assert policy.take_pending_reply() == "real answer"
    assert not policy.awaiting_clause_boundary


def test_coordinator_continuity_and_shadow(tmp_path: Path) -> None:
    config = DuplexConfig(logging=True, log_dir=str(tmp_path), rng_seed=9)
    duplex = DuplexCoordinator(config, session_id="testsess", log_root=tmp_path)
    duplex.set_epoch(1)
    duplex.push_twist(0.4, 0.0, epoch=1)
    duplex.push_text_tokens("hello there", epoch=1)
    for i in range(20):
        frame = duplex.tick(now_s=i * 0.1)
        assert frame is not None
        assert frame.t == i
    assert duplex.snapshot()["missing_frames"] == 0
    token = duplex.codec.encode_twist(0.4, 0.0)
    assert duplex.consumer.shadow_matches(token, vx=0.4, vyaw=0.0)
    log_path = tmp_path / "testsess.jsonl"
    assert log_path.exists()
    rows = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    assert any(row.get("type") == "frame" for row in rows)


def test_session_log_kill_switch(tmp_path: Path) -> None:
    path = tmp_path / "off.jsonl"
    log = DuplexSessionLog(path, enabled=False)
    log.write_frame(t=0, epoch=0, text="<silence>", act="<idle>")
    assert not path.exists()
    log.set_enabled(True)
    log.write_frame(t=1, epoch=0, text="hi", act="<idle>")
    assert path.exists()


def test_shadow_consumer_drops_stale_epoch() -> None:
    codec = ActTokenCodec(twist=default_twist_bins())
    consumer = DuplexFrameConsumer(codec, shadow=True)
    consumer.set_epoch(2)
    from parcel_robot.duplex.frames import DuplexFrame

    assert consumer.consume(DuplexFrame(t=0, epoch=1, text="<silence>", act="<idle>")) is None
    assert consumer.snapshot()["dropped_stale"] == 1


def test_voice_session_text_mode_filler_audible() -> None:
    audible = []

    class Agent:
        def handle_text(self, text: str) -> str:
            return f"reply:{text}"

    with DuplexVoiceSession(Agent(), on_filler_audible=lambda: audible.append(1)) as session:
        assert session.play_filler("Hmm, let me think…", turn_id=1)
        assert audible == [1]
        turn_id = session.submit_text("hello")
        assert turn_id == 1
        assert session.wait_until_idle(2)


def test_filler_double_fire_race_only_one_wins() -> None:
    policy = FillerPolicy(FillerPool.default(rng_seed=5), watchdog_s=0.01, ceiling_s=2.0)
    policy.on_turn_start(now_s=0.0)
    results: list[object] = []

    def _predictive() -> None:
        results.append(policy.predictive_fire(now_s=0.02, reason="predictive"))

    def _watchdog() -> None:
        results.append(policy.poll_watchdog(now_s=0.02))

    threads = [threading.Thread(target=_predictive), threading.Thread(target=_watchdog)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    fires = [item for item in results if item is not None]
    assert len(fires) == 1
    assert policy.fillers_fired == 1


def test_watchdog_not_cancelled_by_reasoning_text_alone() -> None:
    """Fast LLM text without TTS-queue token must still allow watchdog fire."""

    policy = FillerPolicy(FillerPool.default(rng_seed=6), watchdog_s=0.7, ceiling_s=2.0)
    policy.on_turn_start(now_s=0.0)
    # Deliberately skip on_first_token — reasoning_response is not audible.
    assert policy.poll_watchdog(now_s=0.69) is None
    fire = policy.poll_watchdog(now_s=0.70)
    assert fire is not None
    assert fire.reason == "watchdog"


def test_ceiling_breach_when_text_ready_but_tts_stalled() -> None:
    policy = FillerPolicy(FillerPool.default(rng_seed=8), watchdog_s=0.7, ceiling_s=2.0)
    policy.on_turn_start(now_s=0.0)
    # No on_first_token / no filler audible → breach at ceiling.
    assert policy.poll_ceiling_breach(now_s=2.0) is True
    assert policy.response_ceiling_breaches == 1


def test_coordinator_turn_outcome_logging(tmp_path: Path) -> None:
    config = DuplexConfig(logging=True, log_dir=str(tmp_path), rng_seed=3)
    duplex = DuplexCoordinator(config, session_id="outcomes", log_root=tmp_path)
    duplex.record_turn_outcome(
        {"turn_id": 1, "ttft_s": 0.12, "filler_used": None, "barge_in": False}
    )
    rows = [
        json.loads(line)
        for line in (tmp_path / "outcomes.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert any(row.get("type") == "turn_outcome" and row.get("turn_id") == 1 for row in rows)


def test_mid_filler_clause_boundary_with_synthesizer() -> None:
    """Real reply arriving mid-filler waits for filler completion (synthesizer path).

    Voice-session owns the handoff via ``_pending_reply_after_filler``; the
    duplex policy mirrors it on ``filler_clause_boundary_wait``.
    """

    filler_hold = threading.Event()
    release_filler = threading.Event()
    reasoning_gate = threading.Event()
    stages: list[VoiceStage] = []
    order: list[str] = []
    session_holder: dict[str, DuplexVoiceSession] = {}

    class SlowSynth:
        def synthesize(self, text: str) -> bytes:
            order.append(f"synth:{text}")
            if text.startswith("Hmm"):
                filler_hold.set()
                assert release_filler.wait(2.0)
            return b"RIFF" + text.encode("utf-8")[:32]

        def synthesize_stream(self, text: str, *, cancel_event=None, on_sentence=None):
            if on_sentence is not None:
                on_sentence(text)
            chunk = self.synthesize(text)
            if chunk:
                yield chunk

    class Agent:
        def handle_text(self, text: str) -> str:
            # Fire filler while this turn's reasoning is still open, then block
            # until the filler is mid-utterance before returning the reply.
            session = session_holder["session"]
            assert session.play_filler("Hmm, let me think…", turn_id=1)
            assert filler_hold.wait(2.0)
            reasoning_gate.set()
            return "Here is the real answer."

    played: list[bytes] = []
    with DuplexVoiceSession(
        Agent(),
        synthesizer=SlowSynth(),
        audio_chunk_player=played.append,
        on_stage=stages.append,
    ) as session:
        session_holder["session"] = session
        turn_id = session.submit_text("plan please")
        assert turn_id == 1
        assert reasoning_gate.wait(2.0)
        # Filler still holding; reply must not have started synthesizing yet.
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            if any(stage.name == "filler_clause_boundary_wait" for stage in stages):
                break
            time.sleep(0.01)
        assert any(stage.name == "filler_clause_boundary_wait" for stage in stages)
        assert not any(item.startswith("synth:Here") for item in order)
        release_filler.set()
        assert session.wait_until_idle(3.0)

    names = [stage.name for stage in stages]
    assert "filler_complete" in names
    assert "tts_first_chunk" in names
    assert any(item.startswith("synth:Here") for item in order)
    assert any(stage.name == "tts_text_chunk" and "Here" in stage.reply for stage in stages)


def test_sentence_chunked_emits_on_sentence_for_text_observe() -> None:
    seen: list[str] = []

    class Inner:
        def synthesize(self, text: str) -> bytes:
            return b"x" + text.encode("utf-8")[:8]

    streamer = SentenceChunkedSynthesizer(Inner(), max_chars=40)
    chunks = list(
        streamer.synthesize_stream(
            "First sentence. Second sentence.",
            on_sentence=seen.append,
        )
    )
    assert seen == ["First sentence.", "Second sentence."]
    assert len(chunks) == 2
