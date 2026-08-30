from __future__ import annotations

import hashlib
from dataclasses import FrozenInstanceError, replace

import pytest

from parcel_robot.brain.affordance_planner import SkillReliabilityV1
from parcel_robot.learning_loop.contracts import LearningContractError
from parcel_robot.learning_loop.registry import ScenarioRegistryV1, ScenarioV1
from parcel_robot.learning_loop.skill_outcomes import (
    SkillReliabilityTableProposalV1,
    SkillTransitionV1,
    propose_skill_reliability_table,
)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _scenario(scenario_id: str, split: str, group: str) -> ScenarioV1:
    return ScenarioV1(
        scenario_id=scenario_id,
        split=split,
        leakage_group_id=group,
        family="skill_outcome",
        artifact_digest=_sha(f"artifact:{scenario_id}"),
        config_digest=_sha(f"config:{scenario_id}"),
        code_digest=_sha("code"),
        calibration_digest=_sha("calibration"),
        evaluator_digest=_sha("evaluator"),
    )


def _registry() -> ScenarioRegistryV1:
    return ScenarioRegistryV1(
        (
            _scenario("dev-1", "dev", "home-dev"),
            _scenario("frozen-1", "frozen_test", "home-frozen"),
            _scenario("train-1", "train", "home-train"),
        )
    )


def _transition(
    number: int,
    *,
    scenario_id: str = "train-1",
    split: str = "train",
    reliability_key: str = "route.stairs",
    context: tuple[str, ...] = ("indoor", "stairs"),
    outcome: str = "succeeded",
    evidence_token: str | None = None,
) -> SkillTransitionV1:
    return SkillTransitionV1(
        transition_id=f"transition-{number}",
        scenario_id=scenario_id,
        source_split=split,
        reliability_key=reliability_key,
        context_path=context,
        outcome=outcome,
        evidence_digest=_sha(evidence_token or f"receipt:{number}"),
    )


def _mixed_transitions() -> tuple[SkillTransitionV1, ...]:
    return (
        _transition(1),
        _transition(2, outcome="failed"),
        _transition(3, scenario_id="dev-1", split="dev"),
        _transition(4, context=("indoor", "ramp")),
        _transition(5, scenario_id="dev-1", split="dev", context=("indoor", "ramp")),
        _transition(6, context=("indoor", "ramp")),
    )


def test_transition_is_immutable_content_bound_and_strictly_parsed() -> None:
    transition = _transition(1)
    assert SkillTransitionV1.from_mapping(transition.as_dict()) == transition
    with pytest.raises(FrozenInstanceError):
        transition.outcome = "failed"  # type: ignore[misc]
    with pytest.raises(LearningContractError, match="immutable tuple"):
        replace(transition, context_path=["indoor"])  # type: ignore[arg-type]

    tampered = transition.as_dict()
    tampered["outcome"] = "failed"
    with pytest.raises(LearningContractError, match="transition_digest does not match"):
        SkillTransitionV1.from_mapping(tampered)

    forged = transition.as_dict()
    forged["authorizes_motion"] = True
    with pytest.raises(LearningContractError, match="unknown fields"):
        SkillTransitionV1.from_mapping(forged)


def test_proposal_is_deterministic_across_transition_order() -> None:
    transitions = _mixed_transitions()
    first = propose_skill_reliability_table(_registry(), transitions, minimum_support=3)
    second = propose_skill_reliability_table(
        _registry(), tuple(reversed(transitions)), minimum_support=3
    )

    assert first == second
    assert first.proposal_digest == second.proposal_digest
    assert first.transition_set_digest == second.transition_set_digest
    assert first.train_transition_count == 4
    assert first.dev_transition_count == 2


def test_context_lookup_prefers_specific_then_backs_off_to_parent_and_global() -> None:
    proposal = propose_skill_reliability_table(_registry(), _mixed_transitions(), minimum_support=3)

    specific = proposal.resolve_entry("route.stairs", ("indoor", "stairs", "wet"))
    assert specific is not None
    assert specific.context_path == ("indoor", "stairs")
    assert (specific.successes, specific.failures) == (2, 1)

    parent = proposal.resolve_entry("route.stairs", ("indoor", "unseen"))
    assert parent is not None
    assert parent.context_path == ("indoor",)
    assert (parent.successes, parent.failures) == (5, 1)

    global_entry = proposal.resolve_entry("route.stairs", ("outdoor", "snow"))
    assert global_entry is not None
    assert global_entry.context_path == ()
    assert (global_entry.successes, global_entry.failures) == (5, 1)


def test_under_supported_specific_context_backs_off_without_becoming_known() -> None:
    proposal = propose_skill_reliability_table(_registry(), _mixed_transitions(), minimum_support=4)

    assert not any(entry.context_path == ("indoor", "stairs") for entry in proposal.entries)
    resolved = proposal.resolve_entry("route.stairs", ("indoor", "stairs"))
    assert resolved is not None
    assert resolved.context_path == ("indoor",)
    assert resolved.support == 6


def test_no_supported_context_is_explicitly_unknown_and_omitted_for_planner() -> None:
    transitions = (
        _transition(1, reliability_key="route.sparse"),
        _transition(2, reliability_key="route.sparse"),
    )
    proposal = propose_skill_reliability_table(_registry(), transitions, minimum_support=3)

    assert proposal.entries == ()
    assert proposal.resolve("route.sparse", ("indoor", "stairs")) is None
    assert proposal.planner_reliability(("route.sparse",), ("indoor", "stairs")) == ()


def test_sparse_safety_evidence_is_never_hidden_by_minimum_support() -> None:
    proposal = propose_skill_reliability_table(
        _registry(),
        (_transition(1, outcome="safety_failure"),),
        minimum_support=10,
    )

    estimate = proposal.resolve("route.stairs", ("indoor", "stairs"))
    assert isinstance(estimate, SkillReliabilityV1)
    assert estimate.successes == 0
    assert estimate.failures == 1
    assert estimate.safety_failures == 1


def test_known_estimate_is_exactly_affordance_planner_compatible() -> None:
    proposal = propose_skill_reliability_table(_registry(), _mixed_transitions(), minimum_support=3)

    estimate = proposal.resolve("route.stairs", ("indoor", "stairs"))
    assert isinstance(estimate, SkillReliabilityV1)
    assert estimate == SkillReliabilityV1("route.stairs", 2, 1)
    assert proposal.planner_reliability(("unknown.key", "route.stairs"), ("indoor", "stairs")) == (
        estimate,
    )


def test_frozen_test_and_split_spoofing_are_rejected_not_ignored() -> None:
    with pytest.raises(LearningContractError, match="frozen-test"):
        propose_skill_reliability_table(
            _registry(),
            (
                _transition(
                    1,
                    scenario_id="frozen-1",
                    split="frozen_test",
                ),
            ),
            minimum_support=1,
        )

    with pytest.raises(LearningContractError, match="does not match"):
        propose_skill_reliability_table(
            _registry(),
            (_transition(1, scenario_id="dev-1", split="train"),),
            minimum_support=1,
        )


def test_duplicate_transition_or_evidence_cannot_be_double_counted() -> None:
    original = _transition(1)
    with pytest.raises(LearningContractError, match="transition_id values must be unique"):
        propose_skill_reliability_table(
            _registry(), (original, replace(original, outcome="failed")), minimum_support=1
        )

    duplicated_evidence = _transition(2, evidence_token="receipt:1")
    with pytest.raises(LearningContractError, match="evidence_digest values must be unique"):
        propose_skill_reliability_table(
            _registry(), (original, duplicated_evidence), minimum_support=1
        )


def test_proposal_round_trip_binds_sources_entries_and_authority_bits() -> None:
    proposal = propose_skill_reliability_table(_registry(), _mixed_transitions(), minimum_support=3)
    parsed = SkillReliabilityTableProposalV1.from_mapping(proposal.as_dict())
    assert parsed == proposal
    assert parsed.proposal_digest == proposal.proposal_digest
    assert parsed.authorizes_registry_write is False
    assert parsed.authorizes_runtime_write is False
    assert parsed.authorizes_activation is False
    assert parsed.authorizes_motion is False

    with pytest.raises(LearningContractError, match="cannot grant"):
        replace(proposal, authorizes_activation=True)

    forged = proposal.as_dict()
    forged["authorizes_runtime_write"] = True
    with pytest.raises(LearningContractError, match="cannot grant"):
        SkillReliabilityTableProposalV1.from_mapping(forged)

    tampered = proposal.as_dict()
    tampered["entries"][0]["successes"] += 1  # type: ignore[index,operator]
    with pytest.raises(LearningContractError, match="entry_digest does not match"):
        SkillReliabilityTableProposalV1.from_mapping(tampered)


def test_support_floor_and_collection_inputs_are_strict() -> None:
    with pytest.raises(LearningContractError, match="immutable tuple"):
        propose_skill_reliability_table(  # type: ignore[arg-type]
            _registry(), list(_mixed_transitions()), minimum_support=3
        )
    with pytest.raises(LearningContractError, match="at least 1"):
        propose_skill_reliability_table(_registry(), _mixed_transitions(), minimum_support=0)
    with pytest.raises(LearningContractError, match="immutable tuple"):
        propose_skill_reliability_table(
            _registry(),
            (replace(_transition(1), context_path=["indoor"]),),  # type: ignore[arg-type]
            minimum_support=1,
        )
