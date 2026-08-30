from __future__ import annotations

from dataclasses import replace

import pytest

from parcel_robot.brain.affordance_planner import (
    AffordancePlanningError,
    ConfirmedWorldStateV1,
    GroundedSkillV1,
    PlannerOutcomeV1,
    SkillReliabilityV1,
)
from parcel_robot.brain.affordance_planner_v2 import (
    AffordancePlannerV2,
    PlanningProblemV2,
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
    reliability_key: str | None = None,
) -> GroundedSkillV1:
    return GroundedSkillV1(
        operator_id=operator_id,
        skill=skill,
        arguments=FrozenDict(),
        requires_true=frozenset(requires),
        requires_false=frozenset(requires_false),
        predicts_true=frozenset(adds),
        predicts_false=frozenset(removes),
        base_cost=cost,
        reliability_key=reliability_key or operator_id,
    )


def _problem(
    state: ConfirmedWorldStateV1,
    operators: tuple[GroundedSkillV1, ...],
    *,
    goal: tuple[str, ...] = ("owner.greeted",),
    observable: tuple[str, ...] = (),
    commissioned: tuple[str, ...] | None = None,
    **kwargs: object,
) -> PlanningProblemV2:
    return PlanningProblemV2(
        state=state,
        goal_true=frozenset(goal),
        goal_false=frozenset(),
        operators=operators,
        commissioned_skills=frozenset(
            commissioned if commissioned is not None else (item.skill for item in operators)
        ),
        capability_manifest_digest=_digest("9"),
        externally_observable_facts=frozenset(observable),
        **kwargs,
    )


def _greeting_chain() -> tuple[GroundedSkillV1, ...]:
    return (
        _skill("go-door", "NavigateTo", adds=("robot.at_door",)),
        _skill(
            "scan-door",
            "ScanBehavior",
            requires=("camera.ready", "robot.at_door"),
            adds=("owner.visible",),
        ),
        _skill(
            "approach-owner",
            "FollowFormation",
            requires=("owner.visible",),
            adds=("robot.near_owner",),
        ),
        _skill(
            "greet-owner",
            "Vocalize",
            requires=("robot.near_owner",),
            adds=("owner.greeted",),
        ),
    )


@pytest.mark.parametrize(
    ("case_id", "problem"),
    (
        (
            "greet-camera-false",
            _problem(
                _state(false=("camera.ready",)),
                _greeting_chain(),
                observable=("camera.ready",),
            ),
        ),
        (
            "greet-scan-uncommissioned",
            _problem(
                _state("camera.ready", false=("owner.visible",)),
                _greeting_chain(),
                observable=("camera.ready",),
                commissioned=("NavigateTo", "FollowFormation", "Vocalize"),
            ),
        ),
        (
            "follow-consent-false",
            _problem(
                _state("owner.visible", false=("consent.follow",)),
                (
                    _skill(
                        "approach-owner",
                        "FollowFormation",
                        requires=("owner.visible",),
                        adds=("robot.near_owner",),
                    ),
                    _skill(
                        "follow-owner",
                        "FollowFormation",
                        requires=("consent.follow", "robot.near_owner"),
                        adds=("owner.followed",),
                    ),
                ),
                goal=("owner.followed",),
                observable=("consent.follow",),
            ),
        ),
    ),
    ids=lambda value: value if isinstance(value, str) else None,
)
def test_sim_plan_1_false_positive_regressions_are_unreachable(
    case_id: str,
    problem: PlanningProblemV2,
) -> None:
    proposal = AffordancePlannerV2().plan(problem)

    assert case_id
    assert proposal.status == "unreachable"
    assert proposal.uncertain_facts == ()
    assert proposal.steps == ()


def test_observable_unknown_is_reported_only_after_a_complete_goal_chain_exists() -> None:
    problem = _problem(
        _state(),
        _greeting_chain(),
        observable=("camera.ready",),
    )

    proposal = AffordancePlannerV2().plan(problem)

    assert proposal.status == "needs_observation"
    assert proposal.uncertain_facts == ("camera.ready",)
    assert proposal.steps == ()
    assert proposal.authorizes_motion is False


def test_unknown_false_precondition_can_be_a_goal_relevant_observation() -> None:
    wait = _skill(
        "enter-clear-doorway",
        "NavigateTo",
        requires_false=("doorway.blocked",),
        adds=("owner.greeted",),
    )
    proposal = AffordancePlannerV2().plan(
        _problem(_state(), (wait,), observable=("doorway.blocked",))
    )

    assert proposal.status == "needs_observation"
    assert proposal.uncertain_facts == ("doorway.blocked",)


def test_unobservable_or_irrelevant_unknown_does_not_trigger_observation() -> None:
    useful = _skill(
        "useful-but-ungrounded",
        "Vocalize",
        requires=("voice.ready",),
        adds=("owner.greeted",),
    )
    irrelevant = _skill(
        "inspect-weather",
        "ScanBehavior",
        requires=("weather.visible",),
        adds=("weather.inspected",),
    )
    problem = _problem(
        _state(),
        (useful, irrelevant),
        observable=("weather.visible",),
    )

    proposal = AffordancePlannerV2().plan(problem)

    assert proposal.status == "unreachable"
    assert proposal.uncertain_facts == ()


def test_uncommissioned_observable_chain_is_not_goal_supporting() -> None:
    operator = _skill(
        "scan-and-greet",
        "ScanBehavior",
        requires=("camera.ready",),
        adds=("owner.greeted",),
    )
    proposal = AffordancePlannerV2().plan(
        _problem(
            _state(),
            (operator,),
            observable=("camera.ready",),
            commissioned=("Hold",),
        )
    )

    assert proposal.status == "unreachable"
    assert proposal.uncertain_facts == ()


def test_hard_safety_pruning_applies_to_observation_proof() -> None:
    forbidden = _skill(
        "unsafe-approach",
        "FollowFormation",
        requires=("consent.approach",),
        adds=("owner.greeted", "human.contact"),
    )
    problem = _problem(
        _state(),
        (forbidden,),
        observable=("consent.approach",),
        forbidden_true=frozenset({"human.contact"}),
    )

    proposal = AffordancePlannerV2().plan(problem)

    assert proposal.status == "unreachable"
    assert proposal.uncertain_facts == ()


def test_safety_history_suppression_applies_to_observation_proof() -> None:
    suppressed = _skill(
        "unsafe-history",
        "FollowFormation",
        requires=("consent.approach",),
        adds=("owner.greeted",),
        reliability_key="approach.unsafe",
    )
    problem = _problem(
        _state(),
        (suppressed,),
        observable=("consent.approach",),
        reliability=(SkillReliabilityV1("approach.unsafe", 99, 1, safety_failures=1),),
    )

    proposal = AffordancePlannerV2().plan(problem)

    assert proposal.status == "unreachable"
    assert proposal.uncertain_facts == ()


def test_operator_order_and_all_external_inputs_are_digest_bound() -> None:
    first = _skill(
        "a-scan",
        "ScanBehavior",
        requires=("camera.ready",),
        adds=("owner.visible",),
    )
    second = _skill(
        "b-greet",
        "Vocalize",
        requires=("owner.visible",),
        adds=("owner.greeted",),
    )
    left = _problem(_state(), (second, first), observable=("camera.ready",))
    right = _problem(_state(), (first, second), observable=("camera.ready",))

    left_proposal = AffordancePlannerV2().plan(left)
    right_proposal = AffordancePlannerV2().plan(right)

    assert left.problem_digest == right.problem_digest
    assert left_proposal.proposal_digest == right_proposal.proposal_digest
    assert left_proposal.source_problem_digest == left.problem_digest
    assert left_proposal.source_state_digest == left.state.state_digest
    assert left_proposal.capability_manifest_digest == left.capability_manifest_digest
    assert left_proposal.reliability_digest == left.reliability_digest
    assert left_proposal.observable_facts_digest == left.observable_facts_digest
    assert left_proposal.authorizes_motion is False

    changed_boundary = replace(
        left,
        externally_observable_facts=frozenset({"owner.visible"}),
    )
    changed_proposal = AffordancePlannerV2().plan(changed_boundary)
    assert changed_boundary.problem_digest != left.problem_digest
    assert changed_proposal.proposal_digest != left_proposal.proposal_digest


def test_shared_expansion_budget_remains_explicit() -> None:
    first = _skill("first", "Hold", adds=("mid.one",))
    second = _skill(
        "second",
        "Hold",
        requires=("mid.one",),
        adds=("owner.greeted",),
    )
    proposal = AffordancePlannerV2().plan(
        _problem(_state(), (first, second), max_expansions=1)
    )

    assert proposal.status == "budget_exhausted"
    assert proposal.expansions == 1


def test_v2_outcome_must_bind_the_exact_v2_problem_digest() -> None:
    operator = _skill("greet", "Vocalize", adds=("owner.greeted",))
    problem = _problem(_state(epoch=4), (operator,), observable=("owner.greeted",))
    v1_digest = problem.as_v1().problem_digest
    outcome = PlannerOutcomeV1(
        operator_id="greet",
        status="succeeded",
        source_problem_digest=v1_digest,
        observed_true=frozenset({"owner.greeted"}),
        observed_false=frozenset(),
        observation_epoch=5,
        receipt_digest=_digest("b"),
    )

    with pytest.raises(AffordancePlanningError, match="exact V2 problem"):
        AffordancePlannerV2().replan_after_outcome(problem, outcome)


def test_observable_fact_contract_is_immutable_and_problem_scoped() -> None:
    operator = _skill("greet", "Vocalize", adds=("owner.greeted",))
    with pytest.raises(AffordancePlanningError, match="immutable frozenset"):
        PlanningProblemV2(
            state=_state(),
            goal_true=frozenset({"owner.greeted"}),
            goal_false=frozenset(),
            operators=(operator,),
            commissioned_skills=frozenset({"Vocalize"}),
            capability_manifest_digest=_digest(),
            externally_observable_facts={"owner.greeted"},  # type: ignore[arg-type]
        )
    with pytest.raises(AffordancePlanningError, match="outside the problem vocabulary"):
        _problem(_state(), (operator,), observable=("unrelated.fact",))
