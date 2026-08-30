from __future__ import annotations

from dataclasses import replace

import pytest

from parcel_robot.brain.affordance_planner import (
    AffordancePlannerV1,
    AffordancePlanningError,
    ConfirmedWorldStateV1,
    GroundedSkillV1,
    PlannerOutcomeV1,
    PlanningProblemV1,
    PlanProposalV1,
    SkillReliabilityV1,
)
from parcel_robot.brain.contracts import FrozenDict


def _digest(token: str = "a") -> str:
    return token * 64


def _state(*true_facts: str, false: tuple[str, ...] = (), epoch: int = 1):
    return ConfirmedWorldStateV1(frozenset(true_facts), frozenset(false), epoch)


def _skill(
    operator_id: str,
    skill: str,
    *,
    requires: tuple[str, ...] = (),
    requires_false: tuple[str, ...] = (),
    adds: tuple[str, ...] = (),
    removes: tuple[str, ...] = (),
    cost: float = 1.0,
    risk: float = 0.0,
    reliability_key: str | None = None,
    arguments: dict[str, object] | None = None,
) -> GroundedSkillV1:
    return GroundedSkillV1(
        operator_id=operator_id,
        skill=skill,
        arguments=FrozenDict(arguments or {}),
        requires_true=frozenset(requires),
        requires_false=frozenset(requires_false),
        predicts_true=frozenset(adds),
        predicts_false=frozenset(removes),
        base_cost=cost,
        risk=risk,
        reliability_key=reliability_key or operator_id,
    )


def _problem(
    state: ConfirmedWorldStateV1,
    operators: tuple[GroundedSkillV1, ...],
    *,
    goal: tuple[str, ...] = ("owner.greeted",),
    commissioned: tuple[str, ...] | None = None,
    **kwargs: object,
) -> PlanningProblemV1:
    return PlanningProblemV1(
        state=state,
        goal_true=frozenset(goal),
        goal_false=frozenset(),
        operators=operators,
        commissioned_skills=frozenset(
            commissioned if commissioned is not None else (item.skill for item in operators)
        ),
        capability_manifest_digest=_digest("9"),
        **kwargs,
    )


def test_composes_a_new_mission_from_reusable_grounded_skills() -> None:
    operators = (
        _skill(
            "navigate-door",
            "NavigateTo",
            requires=("lidar.fresh",),
            adds=("robot.at_door",),
            arguments={"directive": "go to the door"},
        ),
        _skill(
            "scan-owner-at-door",
            "ScanBehavior",
            requires=("robot.at_door", "camera.fresh"),
            adds=("owner.visible",),
        ),
        _skill(
            "approach-owner-at-door",
            "FollowFormation",
            requires=("owner.visible", "consent.approach"),
            adds=("robot.near_owner",),
            arguments={"relation": "follow", "distance_m": 1.9},
        ),
        _skill(
            "greet-owner",
            "Vocalize",
            requires=("robot.near_owner", "voice.available"),
            adds=("owner.greeted",),
            arguments={"text": "Welcome home!"},
        ),
    )
    problem = _problem(
        _state("lidar.fresh", "camera.fresh", "consent.approach", "voice.available"),
        tuple(reversed(operators)),
    )

    proposal = AffordancePlannerV1().plan(problem)

    assert proposal.status == "planned"
    assert [step.operator_id for step in proposal.steps] == [
        "navigate-door",
        "scan-owner-at-door",
        "approach-owner-at-door",
        "greet-owner",
    ]
    assert "owner.greeted" in proposal.expected_true
    assert proposal.authorizes_motion is False


def test_commissioning_is_an_exact_skill_allowlist() -> None:
    operator = _skill("navigate-door", "NavigateTo", adds=("owner.greeted",))
    proposal = AffordancePlannerV1().plan(
        _problem(_state("lidar.fresh"), (operator,), commissioned=("Hold",))
    )
    assert proposal.status == "unreachable"
    assert proposal.steps == ()


def test_unknown_precondition_does_not_become_true_by_optimism() -> None:
    operator = _skill(
        "approach-owner",
        "FollowFormation",
        requires=("consent.approach",),
        adds=("owner.greeted",),
    )
    proposal = AffordancePlannerV1().plan(_problem(_state(), (operator,)))
    assert proposal.status == "needs_observation"
    assert proposal.uncertain_facts == ("consent.approach",)


def test_confirmed_false_precondition_is_not_reported_as_merely_unknown() -> None:
    operator = _skill(
        "approach-owner",
        "FollowFormation",
        requires=("consent.approach",),
        adds=("owner.greeted",),
    )
    proposal = AffordancePlannerV1().plan(
        _problem(_state(false=("consent.approach",)), (operator,))
    )
    assert proposal.status == "unreachable"
    assert proposal.uncertain_facts == ()


def test_hard_forbidden_effect_prunes_an_unsafe_shortcut() -> None:
    shortcut = _skill(
        "rush-owner",
        "FollowFormation",
        adds=("owner.greeted", "human.contact"),
        cost=0.1,
    )
    safe = _skill("speak-from-distance", "Vocalize", adds=("owner.greeted",), cost=3.0)
    proposal = AffordancePlannerV1().plan(
        _problem(
            _state("voice.available"),
            (shortcut, safe),
            forbidden_true=frozenset({"human.contact"}),
        )
    )
    assert [step.operator_id for step in proposal.steps] == ["speak-from-distance"]


def test_a_confirmed_unsafe_state_refuses_planning() -> None:
    operator = _skill("hold", "Hold", adds=("owner.greeted",))
    proposal = AffordancePlannerV1().plan(
        _problem(
            _state("human.contact"),
            (operator,),
            forbidden_true=frozenset({"human.contact"}),
        )
    )
    assert proposal.status == "unsafe_state"
    assert proposal.steps == ()


def test_must_remain_true_preserves_consent_across_the_predicted_plan() -> None:
    revoke = _skill(
        "unsafe-shortcut",
        "FollowFormation",
        adds=("owner.greeted",),
        removes=("consent.approach",),
        cost=0.1,
    )
    safe = _skill("safe-greeting", "Vocalize", adds=("owner.greeted",), cost=2.0)
    proposal = AffordancePlannerV1().plan(
        _problem(
            _state("consent.approach"),
            (revoke, safe),
            must_remain_true=frozenset({"consent.approach"}),
        )
    )
    assert [step.operator_id for step in proposal.steps] == ["safe-greeting"]


def test_risk_and_frozen_reliability_change_ranking_not_authority() -> None:
    fast = _skill(
        "fast-route",
        "NavigateTo",
        adds=("owner.greeted",),
        cost=0.5,
        risk=0.2,
        reliability_key="route.fast",
    )
    careful = _skill(
        "careful-route",
        "NavigateTo",
        adds=("owner.greeted",),
        cost=1.5,
        risk=0.0,
        reliability_key="route.careful",
    )
    proposal = AffordancePlannerV1().plan(
        _problem(
            _state(),
            (fast, careful),
            reliability=(
                SkillReliabilityV1("route.fast", successes=2, failures=8),
                SkillReliabilityV1("route.careful", successes=90, failures=10),
            ),
            risk_weight=10.0,
            failure_weight=5.0,
        )
    )
    assert [step.operator_id for step in proposal.steps] == ["careful-route"]
    assert proposal.authorizes_motion is False


def test_any_recorded_safety_failure_suppresses_that_reliability_key() -> None:
    unsafe = _skill(
        "learned-shortcut",
        "NavigateTo",
        adds=("owner.greeted",),
        reliability_key="route.learned",
    )
    proposal = AffordancePlannerV1().plan(
        _problem(
            _state(),
            (unsafe,),
            reliability=(SkillReliabilityV1("route.learned", 999, 1, safety_failures=1),),
        )
    )
    assert proposal.status == "unreachable"


def test_reliability_evidence_cannot_enable_an_uncommissioned_skill() -> None:
    operator = _skill(
        "stairs",
        "TraverseStairs",
        adds=("owner.greeted",),
        reliability_key="terrain.stairs",
    )
    proposal = AffordancePlannerV1().plan(
        _problem(
            _state(),
            (operator,),
            commissioned=("Hold",),
            reliability=(SkillReliabilityV1("terrain.stairs", 1_000, 0),),
        )
    )
    assert proposal.status == "unreachable"


def test_replanning_uses_only_observed_effects_and_selects_an_alternate() -> None:
    primary = _skill(
        "primary-route",
        "NavigateTo",
        adds=("robot.at_door",),
        cost=1.0,
    )
    alternate = _skill(
        "alternate-route",
        "NavigateTo",
        adds=("robot.at_door",),
        cost=2.0,
    )
    greet = _skill(
        "greet-at-door",
        "Vocalize",
        requires=("robot.at_door",),
        adds=("owner.greeted",),
    )
    problem = _problem(_state("voice.available", epoch=10), (primary, alternate, greet))
    first = AffordancePlannerV1().plan(problem)
    assert [item.operator_id for item in first.steps[:1]] == ["primary-route"]

    outcome = PlannerOutcomeV1(
        operator_id="primary-route",
        status="blocked",
        source_problem_digest=problem.problem_digest,
        observed_true=frozenset({"route.primary_blocked"}),
        observed_false=frozenset(),
        observation_epoch=11,
        receipt_digest=_digest("b"),
    )
    replanned = AffordancePlannerV1().replan_after_outcome(problem, outcome)

    assert [item.operator_id for item in replanned.steps] == [
        "alternate-route",
        "greet-at-door",
    ]
    # The blocked primary predicted at_door, but no receipt observed at_door.
    assert replanned.source_state_digest != problem.state.state_digest


def test_a_success_receipt_still_does_not_auto_apply_predicted_effects() -> None:
    primary = _skill("primary-route", "NavigateTo", adds=("robot.at_door",))
    greet = _skill(
        "greet-at-door",
        "Vocalize",
        requires=("robot.at_door",),
        adds=("owner.greeted",),
    )
    problem = _problem(_state(epoch=4), (primary, greet))
    outcome = PlannerOutcomeV1(
        operator_id="primary-route",
        status="succeeded",
        source_problem_digest=problem.problem_digest,
        observed_true=frozenset(),
        observed_false=frozenset(),
        observation_epoch=5,
        receipt_digest=_digest("c"),
    )
    proposal = AffordancePlannerV1().replan_after_outcome(problem, outcome)
    assert proposal.status == "needs_observation"
    assert "robot.at_door" in proposal.uncertain_facts


def test_stale_outcome_receipt_is_rejected() -> None:
    operator = _skill("hold", "Hold", adds=("owner.greeted",))
    problem = _problem(_state(epoch=8), (operator,))
    outcome = PlannerOutcomeV1(
        operator_id="hold",
        status="succeeded",
        source_problem_digest=problem.problem_digest,
        observed_true=frozenset({"owner.greeted"}),
        observed_false=frozenset(),
        observation_epoch=8,
        receipt_digest=_digest("d"),
    )
    with pytest.raises(AffordancePlanningError, match="stale"):
        AffordancePlannerV1().replan_after_outcome(problem, outcome)


def test_planning_is_byte_deterministic_under_operator_order() -> None:
    left = _skill("route-a", "NavigateTo", adds=("owner.greeted",), cost=1.0)
    right = _skill("route-b", "NavigateTo", adds=("owner.greeted",), cost=1.0)
    planner = AffordancePlannerV1()
    first = planner.plan(_problem(_state(), (right, left)))
    second = planner.plan(_problem(_state(), (left, right)))
    assert first.proposal_digest == second.proposal_digest
    assert [item.operator_id for item in first.steps] == ["route-a"]


def test_search_budget_is_explicit_and_bounded() -> None:
    first = _skill("first", "Hold", adds=("mid.one",))
    second = _skill("second", "Hold", requires=("mid.one",), adds=("owner.greeted",))
    proposal = AffordancePlannerV1().plan(
        _problem(_state(), (first, second), max_expansions=1)
    )
    assert proposal.status == "budget_exhausted"
    assert proposal.expansions == 1


def test_contract_rejects_contradictory_or_mutable_world_facts() -> None:
    with pytest.raises(AffordancePlanningError, match="frozenset"):
        ConfirmedWorldStateV1({"owner.visible"}, frozenset(), 1)  # type: ignore[arg-type]
    with pytest.raises(AffordancePlanningError, match="true and false"):
        _state("owner.visible", false=("owner.visible",))


def test_a_plan_proposal_cannot_be_turned_into_motion_authority() -> None:
    with pytest.raises(AffordancePlanningError, match="never authorizes motion"):
        PlanProposalV1(
            status="planned",
            source_state_digest=_digest("e"),
            source_problem_digest=_digest("1"),
            capability_manifest_digest=_digest("2"),
            reliability_digest=_digest("3"),
            steps=(
                # Reuse a valid generated step to keep this assertion focused.
                AffordancePlannerV1()
                .plan(
                    _problem(
                        _state(),
                        (_skill("hold", "Hold", adds=("owner.greeted",)),),
                    )
                )
                .steps[0],
            ),
            expected_true=frozenset({"owner.greeted"}),
            expected_false=frozenset(),
            uncertain_facts=(),
            total_cost=1.0,
            expansions=1,
            reason="test",
            authorizes_motion=True,
        )


def test_goal_already_satisfied_does_not_emit_a_redundant_action() -> None:
    operator = _skill("greet", "Vocalize", adds=("owner.greeted",))
    proposal = AffordancePlannerV1().plan(_problem(_state("owner.greeted"), (operator,)))
    assert proposal.status == "goal_satisfied"
    assert proposal.steps == ()


def test_problem_rejects_an_invariant_that_is_not_confirmed() -> None:
    operator = _skill("hold", "Hold", adds=("owner.greeted",))
    with pytest.raises(AffordancePlanningError, match="confirmed initially"):
        _problem(
            _state(),
            (operator,),
            must_remain_true=frozenset({"consent.approach"}),
        )


def test_an_outcome_for_a_different_problem_is_rejected() -> None:
    operator = _skill("hold", "Hold", adds=("owner.greeted",))
    problem = _problem(_state(epoch=1), (operator,))
    outcome = PlannerOutcomeV1(
        operator_id="foreign",
        status="failed",
        source_problem_digest=problem.problem_digest,
        observed_true=frozenset(),
        observed_false=frozenset(),
        observation_epoch=2,
        receipt_digest=_digest("f"),
    )
    with pytest.raises(AffordancePlanningError, match="outside the problem"):
        AffordancePlannerV1().replan_after_outcome(problem, outcome)


def test_an_outcome_cannot_be_replayed_across_problem_digests() -> None:
    operator = _skill("hold", "Hold", adds=("owner.greeted",))
    problem = _problem(_state(epoch=1), (operator,))
    outcome = PlannerOutcomeV1(
        operator_id="hold",
        status="failed",
        source_problem_digest=_digest("0"),
        observed_true=frozenset(),
        observed_false=frozenset(),
        observation_epoch=2,
        receipt_digest=_digest("f"),
    )
    with pytest.raises(AffordancePlanningError, match="exact planning problem"):
        AffordancePlannerV1().replan_after_outcome(problem, outcome)


def test_failure_threshold_can_require_evidence_before_a_skill_is_proposed() -> None:
    operator = _skill(
        "route",
        "NavigateTo",
        adds=("owner.greeted",),
        reliability_key="route.flat",
    )
    no_evidence = _problem(_state(), (operator,), minimum_reliability=0.6)
    assert AffordancePlannerV1().plan(no_evidence).status == "unreachable"

    evidence = replace(
        no_evidence,
        reliability=(SkillReliabilityV1("route.flat", successes=9, failures=1),),
    )
    assert AffordancePlannerV1().plan(evidence).status == "planned"
