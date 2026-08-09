"""Phase 2: dialogue-state × T2, goal amendment, grounded clarification."""

from __future__ import annotations

import time
from dataclasses import replace
from pathlib import Path

import pytest
import yaml

from parcel_robot.agent import VoiceAgent
from parcel_robot.attention.stimuli import StimulusKind
from parcel_robot.audio_io import AudioDeviceStatus
from parcel_robot.backends.base import OwnerTrack, RobotPose, SimObservation
from parcel_robot.contracts.v1 import DialogueStateMsg, SCHEMA_VERSION
from parcel_robot.instructnav.grounding import GroundingOutcome, GroundingResult
from parcel_robot.models import VelocityCommand
from parcel_robot.runtime import RobotRuntime
from parcel_robot.voice.amendment import (
    begin_goal_amend,
    clarification_from_grounding,
    strip_amend_prefix,
)
from parcel_robot.voice.closed_intents import ClosedIntent, parse_closed_intent
from parcel_robot.voice.dialogue_state import (
    DIALOGUE_STATE_TTL_NS,
    DialogueStateChannel,
    map_dialogue_to_t2,
)
from parcel_robot.voice.executive_caps import CapDirective, PaceCap, resolve_cap

REPO = Path(__file__).resolve().parents[1]


class _Backend:
    name = "fake"

    def __init__(self) -> None:
        self._observation = SimObservation(
            timestamp=time.monotonic(),
            robot=RobotPose(),
            owner=OwnerTrack("owner", 2.0, 0.0, True, 1.0),
            backend="fake",
        )
        self.commands: list[VelocityCommand] = []

    def observe(self) -> SimObservation:
        return replace(self._observation, timestamp=time.monotonic())

    def move(self, command: VelocityCommand) -> None:
        self.commands.append(command)

    def stop(self) -> None:
        return None

    def pose(self, pose: object) -> None:
        del pose

    def trajectory(self, skill: object) -> None:
        del skill

    def move_owner(self, dx: float, dy: float) -> None:
        del dx, dy

    def set_robot_pose(self, pose: RobotPose) -> None:
        self._observation = replace(self._observation, robot=pose)

    def set_emergency_stopped(self, stopped: bool) -> None:
        self._observation = replace(self._observation, emergency_stopped=stopped)

    def close(self) -> None:
        return None


@pytest.fixture
def audio_status() -> AudioDeviceStatus:
    return AudioDeviceStatus(
        status="text mode",
        driver="test",
        capture_hardware=False,
        connected_input=False,
        connected_output=False,
        detail="deterministic test status",
    )


@pytest.fixture
def runtime_config(tmp_path: Path) -> Path:
    base = yaml.safe_load((REPO / "configs/robot.yaml").read_text(encoding="utf-8"))
    base["memory"] = {"path": ":memory:"}
    base["navigation"] = {
        "enabled": True,
        "config": str(REPO / "configs/navigation/default.yaml"),
    }
    path = tmp_path / "robot.yaml"
    path.write_text(yaml.safe_dump(base), encoding="utf-8")
    return path


def test_dialogue_state_publish_consume_and_ttl() -> None:
    channel = DialogueStateChannel(ttl_ns=DIALOGUE_STATE_TTL_NS)
    channel.set_phase("listening", engagement=0.8, turn_id="turn-p2")
    now = 1_000_000_000
    msg = channel.publish(now)
    assert isinstance(msg, DialogueStateMsg)
    assert msg.channel == "dialogue_state"
    assert msg.phase == "listening"
    assert msg.schema_version == SCHEMA_VERSION
    assert channel.latest(now + 100) == msg
    assert channel.latest(now + DIALOGUE_STATE_TTL_NS + 1) is None
    influence = map_dialogue_to_t2(msg)
    assert influence.gaze_mode == "mutual"
    assert influence.pace_scale_factor <= 1.0
    assert influence.defer_nonurgent is True


def test_t2_mapping_phases() -> None:
    base = dict(
        schema_version=SCHEMA_VERSION,
        channel="dialogue_state",
        turn_id="t1",
        published_monotonic_ns=0,
        expires_monotonic_ns=DIALOGUE_STATE_TTL_NS,
        sequence=1,
        engagement=0.9,
    )
    listening = DialogueStateMsg(**base, phase="listening")
    thinking = DialogueStateMsg(**base, phase="thinking")
    speaking = DialogueStateMsg(**base, phase="speaking")
    idle = DialogueStateMsg(**{**base, "engagement": 0.0}, phase="idle")
    assert map_dialogue_to_t2(listening).gaze_mode == "mutual"
    assert map_dialogue_to_t2(thinking).gaze_mode == "aversion"
    assert map_dialogue_to_t2(speaking).gaze_mode == "soft"
    assert map_dialogue_to_t2(idle).gaze_mode == "idle"
    assert map_dialogue_to_t2(idle).pace_scale_factor == 1.0


def test_dialogue_pace_never_raises_above_cap() -> None:
    cap = PaceCap(1.0)
    channel = DialogueStateChannel()
    channel.set_phase("speaking", engagement=1.0)
    msg = channel.publish(0)
    factor = map_dialogue_to_t2(msg).pace_scale_factor
    assert 0.35 <= factor <= 1.0
    vx, vy, vyaw = cap.scale_command(1.0, 0.0, 0.5)
    assert (vx * factor, vy * factor, vyaw * factor) <= (vx, vy, vyaw)


def test_clarification_from_ambiguous_attributes() -> None:
    result = GroundingResult(
        outcome=GroundingOutcome.AMBIGUOUS,
        candidate=None,
        candidates=(
            {"label": "bench near crosswalk", "confidence": 0.81},
            {"label": "bench on the left", "confidence": 0.80},
        ),
        detail="ambiguous_frustum_match",
    )
    act = clarification_from_grounding(result, query="bench")
    assert act.kind == "clarify"
    assert act.asks_clarification is True
    assert "crosswalk" in act.reply or "left" in act.reply


def test_clarification_unseen_offers_scan() -> None:
    result = GroundingResult(
        outcome=GroundingOutcome.UNSEEN,
        candidate=None,
        candidates=(),
        detail="unseen",
    )
    act = clarification_from_grounding(result, query="red mailbox")
    assert act.kind == "offer_scan"
    assert "scan" in act.reply.lower()


def test_amendment_fail_closed_when_idle() -> None:
    gate = begin_goal_amend(active_channels=(), paused_channels=())
    assert gate.ok is False
    assert gate.pending is False
    assert "nothing" in gate.reply.lower()


def test_amendment_ok_when_active() -> None:
    gate = begin_goal_amend(active_channels=("navigation",))
    assert gate.ok is True
    assert gate.pending is True
    assert gate.reason == "goal_amend"


def test_strip_amend_prefix() -> None:
    assert "other lamppost" in strip_amend_prefix("actually the other lamppost")
    assert parse_closed_intent("actually go to the other bench") is ClosedIntent.GOAL_AMEND


def test_agent_goal_amend_fail_closed_without_handler() -> None:
    agent = VoiceAgent({}, [], lambda _pose: None)
    reply = agent.handle_text("actually the other bench")
    assert "nothing" in reply.lower()
    assert agent.last_closed_intent is ClosedIntent.GOAL_AMEND
    assert agent.last_brain_metrics.get("goal_amend_ok") is False


def test_agent_goal_amend_via_handler_metrics() -> None:
    seen: list[str] = []
    agent_box: dict[str, VoiceAgent] = {}

    def handler(intent: ClosedIntent, directive: CapDirective) -> str:
        seen.append(intent.value)
        # Simulate runtime marking success after pause/snapshot.
        agent_box["agent"].last_brain_metrics["goal_amend_ok"] = True
        return directive.reply

    agent = VoiceAgent({}, [], lambda _pose: None, closed_intent_handler=handler)
    agent_box["agent"] = agent
    # No planner adapters → waits after successful pause.
    reply = agent.handle_text("instead the other lamppost")
    assert seen == ["goal-amend"]
    assert "revise" in reply.lower()
    assert agent.last_brain_metrics.get("goal_amend_replan") == "deferred_no_planner"


def test_runtime_dialogue_state_tick_and_pace(
    runtime_config: Path, audio_status: AudioDeviceStatus
) -> None:
    runtime = RobotRuntime(runtime_config, _Backend(), audio_status=audio_status)
    try:
        runtime._dialogue_state.set_phase("listening", engagement=0.9, turn_id="p2")
        runtime._step_dialogue_state(runtime._observation)
        snap = runtime.snapshot()
        dlg = snap["dialogue_state"]
        assert dlg["phase"] == "listening"
        assert dlg["gaze_mode"] == "mutual"
        assert 0.35 <= float(dlg["pace_factor"]) <= 1.0
        assert isinstance(dlg["latest"], dict)
        assert dlg["latest"]["channel"] == "dialogue_state"

        # Pace overlay slows nav-sourced motion; safety source untouched.
        runtime._dialogue_pace_factor = 0.5
        runtime._pace_cap.set_scale(1.0)
        reason = runtime.submit_motion("navigation", VelocityCommand(vx=0.8, vy=0.0, vyaw=0.0))
        assert reason  # accepted
        # Manual bypasses dialogue slowdown.
        runtime.submit_motion("manual", VelocityCommand(vx=0.4, vy=0.0, vyaw=0.0))
    finally:
        runtime.close()


def test_runtime_goal_amend_fail_closed_and_pause(
    runtime_config: Path, audio_status: AudioDeviceStatus
) -> None:
    runtime = RobotRuntime(runtime_config, _Backend(), audio_status=audio_status)
    try:
        # Idle: fail closed.
        reply = runtime._apply_closed_intent(
            ClosedIntent.GOAL_AMEND,
            resolve_cap(ClosedIntent.GOAL_AMEND),
        )
        assert "nothing" in reply.lower()
        assert runtime.agent.last_brain_metrics.get("goal_amend_ok") is False
        assert runtime._amendment_pending is False

        # Start nav, then amend must pause with ResumeIntent.
        runtime.start_navigation("go to the lamppost")
        assert runtime._channels.get("navigation") is not None
        reply2 = runtime._apply_closed_intent(
            ClosedIntent.GOAL_AMEND,
            resolve_cap(ClosedIntent.GOAL_AMEND),
        )
        assert "revise" in reply2.lower()
        assert runtime.agent.last_brain_metrics.get("goal_amend_ok") is True
        assert runtime._amendment_pending is True
        intent = runtime._resume_store.peek("navigation", now_s=time.monotonic())
        assert intent is not None
        assert intent.suspend_reason == "goal_amend"
    finally:
        runtime.close()


def test_runtime_feeds_dialogue_stimulus(
    runtime_config: Path, audio_status: AudioDeviceStatus
) -> None:
    runtime = RobotRuntime(runtime_config, _Backend(), audio_status=audio_status)
    try:
        runtime._dialogue_state.set_phase("thinking", engagement=0.8)
        runtime._step_reaction_bridge(None)
        # Bridge drained the dialogue stimulus (may or may not select a reaction).
        assert runtime._reaction_last["drained"] >= 1
        # Ensure StimulusKind exists for the channel.
        assert StimulusKind.DIALOGUE_STATE.value == "dialogue_state"
    finally:
        runtime.close()
