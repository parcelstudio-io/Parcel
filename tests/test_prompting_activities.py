from __future__ import annotations

import json
from pathlib import Path

import pytest

from parcel_robot.core import ActivityContext, ActivityCoordinator, VelocitySmoother
from parcel_robot.models import ActionProposal, VelocityCommand
from parcel_robot.prompting import PromptLibrary
from parcel_robot.providers import parse_model_decision

REPO = Path(__file__).resolve().parents[1]


def _proposal(name: str = "play_bow") -> ActionProposal:
    return ActionProposal(
        kind="skill",
        name=name,
        trigger="inferred_affect",
        timing_preference="when_safe",
        interruption_request="none",
        reason="supportive response",
    )


def test_prompt_library_composes_personality_functions_and_runtime_state():
    library = PromptLibrary(REPO / "prompts")
    rendered = library.render_system(
        personality_id="playful_companion",
        function_ids=["companion", "navigator"],
        runtime_context={
            "active_activity": {"kind": "navigate", "interruptibility": "never"},
            "safety": {"emergency_stopped": False},
        },
    )

    assert "Active personality: Playful companion" in rendered
    assert "Navigation assistant" in rendered
    assert '"kind":"navigate"' in rendered
    assert "Never invent joint values" in rendered


def test_prompt_library_rejects_profile_path_traversal():
    library = PromptLibrary(REPO / "prompts")

    with pytest.raises(ValueError, match="invalid prompt profile"):
        library.personality("../system/core")


def test_prompt_library_loads_defensive_plan_schema_and_instruction():
    library = PromptLibrary(REPO / "prompts")

    schema = library.schema("plan_ir_v1.schema.json")
    schema["title"] = "mutated by caller"

    assert library.schema("plan_ir_v1.schema.json")["title"] == "Parcel PlanIR v1"
    assert "Return exactly one PlanIR JSON object" in library.planner_system()
    with pytest.raises(ValueError, match="invalid prompt schema filename"):
        library.schema("../plan_ir_v1.schema.json")


def test_model_decision_parses_bounded_semantic_action():
    decision = parse_model_decision(
        json.dumps(
            {
                "reply": "I'm here.",
                "tool_calls": [],
                "intent": "conversation",
                "affect": {"label": "sad", "confidence": 0.9},
                "next_action": {
                    "kind": "skill",
                    "name": "play_bow",
                    "trigger": "inferred_affect",
                    "timing_preference": "when_safe",
                    "interruption_request": "none",
                    "reason": "supportive response",
                },
            }
        )
    )

    assert decision.next_action == _proposal()
    assert decision.affect is not None
    assert decision.affect.confidence == pytest.approx(0.9)


def test_model_decision_accepts_explicit_excitement_action() -> None:
    decision = parse_model_decision(
        json.dumps(
            {
                "reply": "I'm excited with you!",
                "tool_calls": [],
                "intent": "conversation",
                "affect": {"label": "excited", "confidence": 0.98},
                "next_action": {
                    "kind": "skill",
                    "name": "excited_paw_taps",
                    "trigger": "inferred_affect",
                    "timing_preference": "when_safe",
                    "interruption_request": "none",
                    "reason": "clear positive anticipation",
                },
            }
        )
    )

    assert decision.affect is not None
    assert decision.affect.label == "excited"
    assert decision.next_action is not None
    assert decision.next_action.name == "excited_paw_taps"


def test_model_decision_accepts_short_lived_conversation_reaction() -> None:
    decision = parse_model_decision(
        json.dumps(
            {
                "reply": "Heh—that was a good one.",
                "tool_calls": [],
                "intent": "conversation",
                "affect": None,
                "next_action": {
                    "kind": "skill",
                    "name": "chuckle",
                    "trigger": "conversation_reaction",
                    "timing_preference": "when_safe",
                    "interruption_request": "none",
                    "reason": "clear humorous moment",
                },
            }
        )
    )

    assert decision.next_action is not None
    assert decision.next_action.trigger == "conversation_reaction"


def test_model_cannot_supply_force_or_priority():
    raw = {
        "reply": "Moving.",
        "tool_calls": [],
        "intent": "conversation",
        "affect": None,
        "next_action": {
            "kind": "skill",
            "name": "play_bow",
            "trigger": "explicit_command",
            "timing_preference": "now",
            "interruption_request": "force",
            "reason": "override",
            "priority": 999,
        },
    }

    with pytest.raises(ValueError, match="unsupported fields"):
        parse_model_decision(json.dumps(raw))


def test_activity_coordinator_defers_navigation_and_executes_when_idle():
    coordinator = ActivityCoordinator(proposal_ttl_s=10.0, cooldown_s=2.0)
    busy = ActivityContext(active_source="navigation", navigation_active=True)
    submission = coordinator.submit(_proposal(), busy, now=1.0)

    assert submission.accepted
    assert submission.disposition == "defer"
    assert coordinator.start_ready(busy, now=2.0) is None
    record = coordinator.start_ready(ActivityContext(), now=3.0)
    assert record is not None
    assert record.proposal.name == "play_bow"
    coordinator.finish(success=True, detail="done", now=4.0)
    assert coordinator.snapshot(now=4.0)["running"] is None


def test_activity_coordinator_rejects_estop_and_expires_deferred_action():
    coordinator = ActivityCoordinator(proposal_ttl_s=1.0, cooldown_s=0.0)
    rejected = coordinator.submit(_proposal(), ActivityContext(emergency_stopped=True), now=1.0)
    assert not rejected.accepted
    coordinator.submit(_proposal(), ActivityContext(navigation_active=True), now=2.0)

    snapshot = coordinator.snapshot(now=3.1)
    assert snapshot["pending"] == []
    assert snapshot["recent"][-1]["status"] == "expired"


def test_conversation_reaction_skips_busy_body_and_has_short_idle_ttl() -> None:
    coordinator = ActivityCoordinator(proposal_ttl_s=20.0, cooldown_s=0.0)
    reaction = ActionProposal(
        kind="skill",
        name="chuckle",
        trigger="conversation_reaction",
        timing_preference="when_safe",
        interruption_request="none",
        reason="clear joke",
    )

    skipped = coordinator.submit(
        reaction,
        ActivityContext(navigation_active=True),
        now=1.0,
    )
    assert skipped.accepted is False
    assert skipped.disposition == "skip"
    assert coordinator.snapshot(now=1.0)["pending"] == []

    accepted = coordinator.submit(reaction, ActivityContext(), now=2.0)
    assert accepted.accepted is True
    pending = coordinator.snapshot(now=2.0)["pending"]
    assert pending[0]["expires_at"] == pytest.approx(4.0)
    assert coordinator.snapshot(now=4.1)["pending"] == []


def test_prompt_defines_semantics_and_limits_for_conversation_reactions() -> None:
    library = PromptLibrary(REPO / "prompts")
    rendered = library.render_system(
        personality_id="gentle_companion",
        function_ids=["companion"],
        runtime_context={"available_social_skills": ["chuckle", "head_nod"]},
    )

    assert "conversation_reaction" in rendered
    assert "robot has no articulated neck" in rendered
    assert "tilt never proves" in rendered


def test_velocity_smoother_bounds_acceleration_and_can_force_safety_stop():
    smoother = VelocitySmoother(linear_accel=1.0, linear_decel=2.0, yaw_accel=2.0)
    first = smoother.step(VelocityCommand(vx=0.5, vyaw=0.5), now=10.0)
    second = smoother.step(VelocityCommand(vx=0.5, vyaw=0.5), now=10.1)

    assert first == VelocityCommand(vx=0.1, vyaw=0.2)
    assert second.vx == pytest.approx(0.2)
    assert second.vyaw == pytest.approx(0.4)
    smoother.force(VelocityCommand(), now=10.1)
    assert smoother.step(VelocityCommand(), now=10.2) == VelocityCommand()
