"""K6 voice lanes: closed intents, local PlanSketch, dialogue strip, reaction bridge."""

from __future__ import annotations

import time
from dataclasses import replace
from pathlib import Path

import pytest
import yaml

from parcel_robot.agent import MOTION_TOOLS, VoiceAgent
from parcel_robot.attention.stimuli import StimulusKind
from parcel_robot.audio_io import AudioDeviceStatus
from parcel_robot.backends.base import OwnerTrack, RobotPose, SimObservation
from parcel_robot.brain import DeterministicIntentRouter, PlanIR, PlanSketch
from parcel_robot.brain.compiler import compile_plan_sketch
from parcel_robot.brain.executive import VOICE_INTERRUPT_POLICY, _voice_interrupt_action
from parcel_robot.brain.observations import build_observation_snapshot
from parcel_robot.brain.validator import SkillContractRegistry
from parcel_robot.contracts.v1 import ReactionProposalV1, SocialCueV1
from parcel_robot.models import AgentDecision, SpatialIntent, ToolCall, VelocityCommand
from parcel_robot.runtime import RobotRuntime
from parcel_robot.voice.closed_intents import CLOSED_INTENT_NAMES, ClosedIntent, parse_closed_intent
from parcel_robot.voice.dialogue_lane import (
    PHYSICAL_TOOL_NAMES,
    conversation_tool_definitions,
    dialogue_act_from_text,
)
from parcel_robot.voice.executive_caps import PaceCap, resolve_cap
from parcel_robot.voice.local_plans import (
    sketch_come,
    sketch_follow,
    sketch_hold,
    sketch_navigate,
    sketch_spatial,
)
from parcel_robot.voice.reaction_bridge import SocialReactionBridge, proposal_preempts_base

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

    def observe(self) -> SimObservation:
        return replace(self._observation, timestamp=time.monotonic())

    def move(self, command: VelocityCommand) -> None:
        del command

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


def _fresh_obs(rt: RobotRuntime, *, age_s: float = 0.0) -> SimObservation:
    obs = SimObservation(
        timestamp=time.monotonic() - age_s,
        robot=RobotPose(),
        owner=OwnerTrack("owner", 2.0, 0.0, True, 1.0),
        backend="fake",
    )
    rt._observation = obs
    return obs


def _arm_navigation(rt: RobotRuntime, directive: str = "walk to the sidewalk"):
    nav = rt.dog.navigator
    mission = nav.start(directive)
    assert mission is not None
    rt._navigation_directive = directive
    rt._navigation_detail = {
        "enabled": True,
        "state": "navigating",
        "directive": directive,
        "goal": directive,
        "reason": "en_route",
    }
    return nav, mission


def test_closed_intent_enum_is_exact() -> None:
    assert CLOSED_INTENT_NAMES == {
        "pause",
        "resume",
        "faster",
        "slower",
        "stop",
        "come",
        "goal-amend",
    }
    assert parse_closed_intent("slow down") is ClosedIntent.SLOWER
    assert parse_closed_intent("come here") is ClosedIntent.COME
    assert parse_closed_intent("actually go to the other lamppost") is ClosedIntent.GOAL_AMEND
    assert parse_closed_intent("tell me a joke") is None


def test_pace_cap_bounds_and_scales() -> None:
    cap = PaceCap(1.0)
    assert cap.set_scale(2.0) == 1.25
    assert cap.set_scale(0.01) == 0.35
    vx, vy, vyaw = cap.scale_command(1.0, 0.5, 0.2)
    assert abs(vx - 0.35) < 1e-9
    assert abs(vy - 0.175) < 1e-9


def test_resolve_cap_come_yields_sketch() -> None:
    directive = resolve_cap(ClosedIntent.COME)
    assert directive.kind == "admit_plan"
    assert isinstance(directive.sketch, PlanSketch)
    assert directive.sketch.steps[0].skill == "FollowFormation"


def test_local_sketches_compile_to_plan_ir() -> None:
    registry = SkillContractRegistry.default().restricted(
        ("FollowFormation", "Hold", "MoveRelative", "OrbitOwner", "NavigateTo")
    )
    frame = DeterministicIntentRouter().route("follow me", turn_id="turn-k6-1")
    observation = build_observation_snapshot(
        None, snapshot_id="snapshot-k6", now=10.0
    )
    for sketch in (
        sketch_follow(),
        sketch_hold(),
        sketch_come(),
        sketch_spatial(
            SpatialIntent(behavior="move_steps", direction="forward", steps=3)
        ),
        sketch_navigate("go to the sidewalk"),
    ):
        plan = compile_plan_sketch(sketch, frame, observation, registry)
        assert isinstance(plan, PlanIR)
        assert plan.source_turn_id == frame.turn_id
        assert plan.steps


def test_conversation_tools_strip_physical() -> None:
    tools = [
        {"name": "set_behavior", "parameters": {}},
        {"name": "navigate", "parameters": {}},
        {"name": "get_status", "parameters": {}},
        {"name": "lookup_weather", "parameters": {}},
        {"name": "stop_motion", "parameters": {}},
    ]
    kept = conversation_tool_definitions(tools)
    names = {tool["name"] for tool in kept}
    assert names == {"get_status", "lookup_weather"}
    assert PHYSICAL_TOOL_NAMES <= MOTION_TOOLS


def test_dialogue_act_shape() -> None:
    act = dialogue_act_from_text(
        turn_id="turn-k6-dlg",
        text="Sure — happy to chat while I wait.",
        asks_clarification=False,
    )
    assert act.schema_version == 1
    assert act.text.startswith("Sure")
    assert act.as_dict()["asks_clarification"] is False


class _ConvModel:
    def __init__(self) -> None:
        self.last_tools: list[dict[str, object]] | None = None

    def decide(self, transcript, tools, context):
        del transcript, context
        self.last_tools = list(tools)
        return AgentDecision(
            "Hello!",
            tool_calls=(ToolCall("set_behavior", {"mode": "follow"}),),
        )


def test_agent_conversation_lane_strips_physical_tools_and_calls() -> None:
    model = _ConvModel()
    published: list[object] = []
    agent = VoiceAgent({}, [], published.append, language_model=model)
    reply = agent.handle_text("how are you today?")
    assert reply == "Hello!"
    assert model.last_tools is not None
    assert not any(tool["name"] in PHYSICAL_TOOL_NAMES for tool in model.last_tools)
    assert published == []
    assert agent.last_dialogue_act is not None
    assert agent.last_dialogue_act.text == "Hello!"


def test_agent_emergency_stop_remains_fast_path() -> None:
    stops: list[str] = []
    agent = VoiceAgent({}, [], lambda _pose: None, stop_publisher=lambda: stops.append("stop"))
    assert agent.handle_text("stop") == "Stopping."
    assert stops == ["stop"]
    assert agent.last_closed_intent is ClosedIntent.STOP


def test_agent_closed_intent_handler_receives_caps() -> None:
    seen: list[tuple[str, str]] = []

    def handler(intent: ClosedIntent, directive) -> str:
        seen.append((intent.value, directive.kind))
        return directive.reply

    agent = VoiceAgent(
        {},
        [],
        lambda _pose: None,
        closed_intent_handler=handler,
        pace_scale_provider=lambda: 1.0,
    )
    assert "slow" in agent.handle_text("slow down").lower()
    assert seen == [("slower", "pace")]


def test_reaction_bridge_never_preempts_base_when_busy() -> None:
    bridge = SocialReactionBridge(rng_seed=3)
    bridge.add_stimulus(StimulusKind.AFFECT, at_s=0.0, confidence=0.9)
    idle = bridge.tick(now_s=0.1, base_busy=False, critical_phase=False)
    # May or may not select; must not veto when idle.
    assert idle.vetoed is False
    bridge.add_stimulus(StimulusKind.AFFECT, at_s=0.2, confidence=0.95)
    busy = bridge.tick(now_s=0.3, base_busy=True, critical_phase=False)
    assert busy.vetoed is True
    assert busy.decision.reaction is None
    assert busy.reason == "base_busy"


def test_reaction_proposal_with_base_is_rejected() -> None:
    bridge = SocialReactionBridge(rng_seed=1)
    bad = ReactionProposalV1.from_mapping(
        {
            "proposal_id": "prop-bad",
            "source_cue_ids": ["cue-1"],
            "behavior_id": "full_body_bow",
            "required_tracks": ["base", "posture"],
            "confidence": 0.9,
            "urgency": 0.5,
            "earliest_start_monotonic_ns": 1,
            "expires_at_monotonic_ns": 2,
            "minimum_dwell_s": 0.1,
            "maximum_duration_s": 1.0,
            "interruption_policy": "overlay",
            "suppress_if": [],
            "personality_rule_id": "",
        }
    )
    assert proposal_preempts_base(bad) is True
    assert bridge.admit_proposal(bad) is False
    assert bridge.false_base_preempt_attempts == 1

    cue = SocialCueV1.from_mapping(
        {
            "cue_id": "cue-1",
            "source_turn_id": "turn-1",
            "kind": "joke",
            "modality": "transcript",
            "evidence_ref": "asr:1",
            "confidence": 0.8,
            "valence": 0.4,
            "arousal": 0.3,
            "observed_at_monotonic_ns": 10,
            "expires_at_monotonic_ns": 20,
        }
    )
    unit = bridge.ingest_social_cue(cue, at_s=1.0)
    assert unit >= 1


def test_closed_intent_pause_policy_is_suspend() -> None:
    assert VOICE_INTERRUPT_POLICY["closed_intent_pause"] == "suspend"
    assert _voice_interrupt_action("closed_intent_pause") == "suspend"


def test_closed_intent_pause_resume_transaction(
    runtime_config: Path, audio_status: AudioDeviceStatus
) -> None:
    """B1/S1: spoken pause true-PAUSEs; resume restores or fails closed."""

    rt = RobotRuntime(runtime_config, _Backend(), audio_status=audio_status)
    try:
        _fresh_obs(rt)
        nav, mission = _arm_navigation(rt)
        nav._steps_without_progress = 5
        pause_dir = resolve_cap(ClosedIntent.PAUSE)
        pause_reply = rt._apply_closed_intent(ClosedIntent.PAUSE, pause_dir)
        assert "pause" in pause_reply.lower()
        assert nav.paused is True
        assert nav.mission is mission
        assert nav._steps_without_progress == 5
        assert rt.snapshot()["navigation"]["state"] == "paused"
        intent = rt._resume_store.peek("navigation", now_s=time.monotonic())
        assert intent is not None
        assert intent.requires_fresh_observation is True
        assert intent.suspend_reason == "closed_intent_pause"

        # Stale observation rejects; intent retained; no success claim.
        stale_age = rt.telemetry_stale_s + 1.0
        _fresh_obs(rt, age_s=stale_age)
        resume_dir = resolve_cap(ClosedIntent.RESUME)
        stale_reply = rt._apply_closed_intent(ClosedIntent.RESUME, resume_dir)
        assert stale_reply != resume_dir.reply
        assert "couldn't resume" in stale_reply.lower() or "fresh" in stale_reply.lower()
        assert rt._resume_store.peek("navigation", now_s=time.monotonic()) is not None
        assert nav.paused is True

        # Fresh observation restores progress.
        _fresh_obs(rt)
        fresh_reply = rt._apply_closed_intent(ClosedIntent.RESUME, resume_dir)
        assert fresh_reply == resume_dir.reply
        assert nav.paused is False
        assert nav.mission is mission
        assert nav._steps_without_progress == 5
        assert rt._resume_store.peek("navigation", now_s=time.monotonic()) is None

        # Empty store: do not claim success.
        empty_reply = rt._apply_closed_intent(ClosedIntent.RESUME, resume_dir)
        assert empty_reply != resume_dir.reply
        assert "nothing paused" in empty_reply.lower()
    finally:
        rt.close()


def test_closed_intent_stop_still_emergency_path(
    runtime_config: Path, audio_status: AudioDeviceStatus
) -> None:
    """E-stop / spoken stop remains destructive cancel (not true PAUSE)."""

    rt = RobotRuntime(runtime_config, _Backend(), audio_status=audio_status)
    try:
        _fresh_obs(rt)
        nav, _mission = _arm_navigation(rt)
        stop_dir = resolve_cap(ClosedIntent.STOP)
        reply = rt._apply_closed_intent(ClosedIntent.STOP, stop_dir)
        assert reply == stop_dir.reply
        assert rt.arbiter.emergency_stopped is True
        # Stop must not leave a resume intent for the destroyed mission path.
        assert rt._resume_store.peek("navigation", now_s=time.monotonic()) is None
        assert nav.paused is False
    finally:
        rt.close()
