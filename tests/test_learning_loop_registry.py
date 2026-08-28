from __future__ import annotations

import hashlib
from dataclasses import FrozenInstanceError, replace

import pytest

from parcel_robot.learning_loop.contracts import LearningContractError
from parcel_robot.learning_loop.evaluation import (
    CandidateEvaluationV1,
    FamilyMetricsV1,
    SafetyCountersV1,
)
from parcel_robot.learning_loop.mining import FailureEpisodeV1, propose_failure_cases
from parcel_robot.learning_loop.promotion import (
    HumanReviewV1,
    MetricThresholdV1,
    PromotionDecisionV1,
    PromotionGateV1,
    PromotionPolicyV1,
    PromotionRequestV1,
    RollbackArtifactV1,
    review_payload_digest,
)
from parcel_robot.learning_loop.registry import ScenarioRegistryV1, ScenarioV1

D = "a" * 64
D2 = "b" * 64
D3 = "c" * 64
D4 = "d" * 64
D5 = "e" * 64
D6 = "f" * 64


def scenario(
    scenario_id: str,
    split: str,
    group: str,
    *,
    family: str = "owner_follow",
    artifact_digest: str | None = None,
) -> ScenarioV1:
    return ScenarioV1(
        scenario_id=scenario_id,
        split=split,
        leakage_group_id=group,
        family=family,
        artifact_digest=(
            artifact_digest
            if artifact_digest is not None
            else hashlib.sha256(f"{split}:{scenario_id}".encode()).hexdigest()
        ),
        config_digest=D2,
        code_digest=D3,
        calibration_digest=D4,
        evaluator_digest=D5,
    )


def registry() -> ScenarioRegistryV1:
    return ScenarioRegistryV1(
        (
            scenario("dev-1", "dev", "home-b"),
            scenario("frozen-1", "frozen_test", "home-c"),
            scenario("train-1", "train", "home-a"),
        )
    )


def evaluation(reg: ScenarioRegistryV1, **safety: object) -> CandidateEvaluationV1:
    counters = {
        "critical_failure_names": (),
        "false_arrivals": 0,
        "contacts": 0,
        "authority_bypasses": 0,
        **safety,
    }
    return CandidateEvaluationV1(
        candidate_id="candidate-1",
        candidate_digest=D,
        model_digest=D2,
        config_digest=D3,
        registry_digest=reg.registry_digest,
        evaluator_digest=D4,
        reproducibility_digest=D5,
        family_metrics=(FamilyMetricsV1("owner_follow", {"success_rate": 0.92}),),
        safety=SafetyCountersV1(**counters),
    )


def approved_request(
    reg: ScenarioRegistryV1,
    result: CandidateEvaluationV1,
) -> PromotionRequestV1:
    policy = PromotionPolicyV1((MetricThresholdV1("owner_follow", "success_rate", 0.9),))
    rollback = RollbackArtifactV1(D6, D3, D4, True)
    unsigned = PromotionRequestV1(reg.frozen_test_digest, D5, D4, policy, None, rollback)
    reviewer_id = "reviewer-1"
    signer_key_id = "key-1"
    review = HumanReviewV1(
        reviewer_id=reviewer_id,
        decision="approved",
        signed_payload_digest=review_payload_digest(
            result,
            policy,
            rollback,
            reviewer_id=reviewer_id,
            signer_key_id=signer_key_id,
        ),
        signer_key_id=signer_key_id,
        signature="external-signature",
    )
    return replace(unsigned, review=review)


def verify_rollback(rollback: RollbackArtifactV1) -> bool:
    return rollback.tested and rollback.restores_model_digest == D3


def test_registry_round_trip_is_canonical_and_immutable() -> None:
    original = registry()
    parsed = ScenarioRegistryV1.from_mapping(original.as_dict())
    assert parsed == original
    assert parsed.registry_digest == original.registry_digest
    with pytest.raises(FrozenInstanceError):
        parsed.schema_version = 2  # type: ignore[misc]
    with pytest.raises(LearningContractError, match="immutable tuple"):
        ScenarioRegistryV1(list(original.scenarios))  # type: ignore[arg-type]


def test_registry_rejects_split_leakage_and_duplicate_scenario_ids() -> None:
    with pytest.raises(LearningContractError, match="crosses splits"):
        ScenarioRegistryV1(
            (scenario("a", "train", "same-home"), scenario("b", "dev", "same-home"))
        )
    with pytest.raises(LearningContractError, match="unique"):
        ScenarioRegistryV1((scenario("same", "train", "g1"), scenario("same", "train", "g2")))


def test_registry_rejects_identical_artifact_relabelled_across_splits() -> None:
    with pytest.raises(LearningContractError, match="artifact .* crosses splits"):
        ScenarioRegistryV1(
            (
                scenario("dev-copy", "dev", "dev-group", artifact_digest=D),
                scenario("frozen-unique", "frozen_test", "frozen-group"),
                scenario("train-copy", "train", "train-group", artifact_digest=D),
            )
        )


def test_registry_rejects_mutation_digest_mismatch_and_extra_fields() -> None:
    payload = registry().as_dict()
    payload["scenarios"][0]["family"] = "tampered"  # type: ignore[index]
    with pytest.raises(LearningContractError, match="does not match"):
        ScenarioRegistryV1.from_mapping(payload)
    payload = registry().as_dict()
    payload["forged_authority"] = True
    with pytest.raises(LearningContractError, match="unknown fields"):
        ScenarioRegistryV1.from_mapping(payload)


def test_source_episode_lineage_cannot_cross_split_or_leakage_group() -> None:
    def with_episode(item: ScenarioV1, episode_id: str) -> ScenarioV1:
        return replace(item, source_episode_ids=(episode_id,))

    with pytest.raises(LearningContractError, match="crosses split or leakage group"):
        ScenarioRegistryV1(
            (
                with_episode(scenario("dev-1", "dev", "home-b"), "episode-shared"),
                with_episode(
                    scenario("frozen-1", "frozen_test", "home-c"), "episode-shared"
                ),
                scenario("train-1", "train", "home-a"),
            )
        )

    with pytest.raises(LearningContractError, match="crosses split or leakage group"):
        ScenarioRegistryV1(
            (
                scenario("dev-1", "dev", "home-b"),
                scenario("frozen-1", "frozen_test", "home-c"),
                with_episode(scenario("train-1", "train", "home-a"), "episode-shared"),
                with_episode(scenario("train-2", "train", "home-d"), "episode-shared"),
            )
        )

    same_assignment = ScenarioRegistryV1(
        (
            scenario("dev-1", "dev", "home-b"),
            scenario("frozen-1", "frozen_test", "home-c"),
            with_episode(scenario("train-1", "train", "home-a"), "episode-shared"),
            with_episode(scenario("train-2", "train", "home-a"), "episode-shared"),
        )
    )
    assert same_assignment.scenario("train-2").source_episode_ids == ("episode-shared",)


def test_failure_mining_is_deterministic_lineaged_and_proposal_only() -> None:
    reg = registry()
    failure = FailureEpisodeV1("episode-7", "train-1", "lost_owner", D6)
    first = propose_failure_cases(reg, (failure,))
    second = propose_failure_cases(reg, (failure,))
    assert first.proposed_registry.registry_digest == second.proposed_registry.registry_digest
    assert first.authorizes_registry_write is False
    added = first.proposed_registry.scenario(first.added_scenario_ids[0])
    assert added.split == "train"
    assert added.leakage_group_id == "home-a"
    assert added.source_episode_ids == ("episode-7",)
    assert reg.registry_digest == first.base_registry_digest


def test_failure_mining_cannot_observe_or_change_frozen_test() -> None:
    reg = registry()
    before = reg.frozen_test_digest
    with pytest.raises(LearningContractError, match="frozen-test"):
        propose_failure_cases(
            reg,
            (FailureEpisodeV1("episode-frozen", "frozen-1", "failure", D6),),
        )
    mined = propose_failure_cases(
        reg,
        (FailureEpisodeV1("episode-dev", "dev-1", "failure", D6),),
    )
    assert mined.proposed_registry.frozen_test_digest == before


def test_candidate_evaluation_strict_parser_rejects_forged_extra_fields() -> None:
    result = evaluation(registry())
    assert CandidateEvaluationV1.from_mapping(result.as_dict()) == result
    payload = result.as_dict()
    payload["authorizes_activation"] = True
    with pytest.raises(LearningContractError, match="unknown fields"):
        CandidateEvaluationV1.from_mapping(payload)
    safety = result.as_dict()
    safety["safety"]["collision_waiver"] = True  # type: ignore[index]
    with pytest.raises(LearningContractError, match="unknown fields"):
        CandidateEvaluationV1.from_mapping(safety)
    tampered = result.as_dict()
    tampered["family_metrics"][0]["metrics"]["success_rate"] = 1.0  # type: ignore[index]
    with pytest.raises(LearningContractError, match="evaluation_digest does not match"):
        CandidateEvaluationV1.from_mapping(tampered)


def test_gate_is_default_off_and_output_has_zero_authority() -> None:
    reg = registry()
    result = evaluation(reg)
    request = approved_request(reg, result)
    decision = PromotionGateV1(expected_policy_digest=request.policy.policy_digest).evaluate(
        registry=reg,
        evaluation=result,
        request=request,
        trusted_prior_model_digest=D3,
        signature_verifier=lambda *_: True,
        rollback_verifier=verify_rollback,
    )
    assert decision.decision == "reject"
    assert decision.reasons == ("gate_disabled",)
    assert decision.authorizes_activation is False
    with pytest.raises(LearningContractError, match="cannot authorize"):
        PromotionDecisionV1("propose_for_activation", (), D, reg.registry_digest, True)


def test_enabled_gate_without_trusted_policy_digest_rejects() -> None:
    reg = registry()
    result = evaluation(reg)
    request = approved_request(reg, result)
    decision = PromotionGateV1(enabled=True).evaluate(
        registry=reg,
        evaluation=result,
        request=request,
        trusted_prior_model_digest=D3,
        signature_verifier=lambda *_: True,
        rollback_verifier=verify_rollback,
    )
    assert "expected_policy_digest_missing" in decision.reasons


def test_enabled_gate_only_proposes_and_never_activates() -> None:
    reg = registry()
    result = evaluation(reg)
    request = approved_request(reg, result)
    decision = PromotionGateV1(
        enabled=True, expected_policy_digest=request.policy.policy_digest
    ).evaluate(
        registry=reg,
        evaluation=result,
        request=request,
        trusted_prior_model_digest=D3,
        signature_verifier=lambda key, payload, signature: bool(key and payload and signature),
        rollback_verifier=verify_rollback,
    )
    assert decision.decision == "propose_for_activation"
    assert decision.reasons == ()
    assert decision.authorizes_activation is False


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"false_arrivals": 1}, "nonzero_safety_counter"),
        ({"contacts": 1}, "nonzero_safety_counter"),
        ({"authority_bypasses": 1}, "nonzero_safety_counter"),
        ({"critical_failure_names": ("owner_contact",)}, "nonzero_safety_counter"),
    ],
)
def test_every_named_safety_failure_rejects(change: dict[str, object], reason: str) -> None:
    reg = registry()
    result = evaluation(reg, **change)
    request = approved_request(reg, result)
    decision = PromotionGateV1(True, request.policy.policy_digest).evaluate(
        registry=reg,
        evaluation=result,
        request=request,
        trusted_prior_model_digest=D3,
        signature_verifier=lambda *_: True,
        rollback_verifier=verify_rollback,
    )
    assert reason in decision.reasons


def test_threshold_omission_and_failure_reject() -> None:
    reg = registry()
    result = evaluation(reg)
    base = approved_request(reg, result)
    omitted = replace(
        base,
        policy=PromotionPolicyV1((MetricThresholdV1("stairs", "success_rate", 0.8),)),
    )
    decision = PromotionGateV1(True, base.policy.policy_digest).evaluate(
        registry=reg,
        evaluation=result,
        request=omitted,
        trusted_prior_model_digest=D3,
        signature_verifier=lambda *_: True,
        rollback_verifier=verify_rollback,
    )
    assert "threshold_metric_missing:stairs:success_rate" in decision.reasons
    too_high = replace(
        base,
        policy=PromotionPolicyV1((MetricThresholdV1("owner_follow", "success_rate", 0.99),)),
    )
    decision = PromotionGateV1(True, base.policy.policy_digest).evaluate(
        registry=reg,
        evaluation=result,
        request=too_high,
        trusted_prior_model_digest=D3,
        signature_verifier=lambda *_: True,
        rollback_verifier=verify_rollback,
    )
    assert "threshold_not_met:owner_follow:success_rate" in decision.reasons


def test_missing_human_signature_or_rollback_rejects() -> None:
    reg = registry()
    result = evaluation(reg)
    approved = approved_request(reg, result)
    cases = (
        (replace(approved, review=None), lambda *_: True, "human_review_missing"),
        (approved, None, "signature_verifier_missing"),
        (approved, lambda *_: False, "signature_invalid"),
        (replace(approved, rollback=None), lambda *_: True, "rollback_missing"),
    )
    for request, verifier, expected in cases:
        decision = PromotionGateV1(True, approved.policy.policy_digest).evaluate(
            registry=reg,
            evaluation=result,
            request=request,
            trusted_prior_model_digest=D3,
            signature_verifier=verifier,
            rollback_verifier=verify_rollback,
        )
        assert expected in decision.reasons


def test_rollback_requires_trusted_prior_identity_and_verified_artifact() -> None:
    reg = registry()
    result = evaluation(reg)
    approved = approved_request(reg, result)

    wrong_prior = PromotionGateV1(True, approved.policy.policy_digest).evaluate(
        registry=reg,
        evaluation=result,
        request=approved,
        trusted_prior_model_digest=D4,
        signature_verifier=lambda *_: True,
        rollback_verifier=lambda _: True,
    )
    assert "rollback_prior_model_mismatch" in wrong_prior.reasons

    unverified = PromotionGateV1(True, approved.policy.policy_digest).evaluate(
        registry=reg,
        evaluation=result,
        request=approved,
        trusted_prior_model_digest=D3,
        signature_verifier=lambda *_: True,
        rollback_verifier=lambda _: False,
    )
    assert "rollback_verification_failed" in unverified.reasons

    missing = PromotionGateV1(True, approved.policy.policy_digest).evaluate(
        registry=reg,
        evaluation=result,
        request=approved,
        trusted_prior_model_digest=D3,
        signature_verifier=lambda *_: True,
    )
    assert "rollback_verifier_missing" in missing.reasons


def test_digest_binding_and_reproducibility_are_fail_closed() -> None:
    reg = registry()
    result = evaluation(reg)
    request = approved_request(reg, result)
    tampered = replace(result, registry_digest=D6)
    decision = PromotionGateV1(True, request.policy.policy_digest).evaluate(
        registry=reg,
        evaluation=tampered,
        request=request,
        trusted_prior_model_digest=D3,
        signature_verifier=lambda *_: True,
        rollback_verifier=verify_rollback,
    )
    assert "registry_digest_mismatch" in decision.reasons
    request = replace(request, expected_reproducibility_digest=D6)
    decision = PromotionGateV1(True, request.policy.policy_digest).evaluate(
        registry=reg,
        evaluation=result,
        request=request,
        trusted_prior_model_digest=D3,
        signature_verifier=lambda *_: True,
        rollback_verifier=verify_rollback,
    )
    assert "reproducibility_digest_mismatch" in decision.reasons


def test_threshold_policy_omission_cannot_change_preregistered_policy() -> None:
    reg = registry()
    result = evaluation(reg)
    registered = approved_request(reg, result)
    weakened_policy = PromotionPolicyV1((MetricThresholdV1("owner_follow", "success_rate", 0.1),))
    weakened = replace(registered, policy=weakened_policy)
    decision = PromotionGateV1(True, registered.policy.policy_digest).evaluate(
        registry=reg,
        evaluation=result,
        request=weakened,
        trusted_prior_model_digest=D3,
        signature_verifier=lambda *_: True,
        rollback_verifier=verify_rollback,
    )
    assert "promotion_policy_digest_mismatch" in decision.reasons


def test_review_signature_binds_metrics_safety_and_full_rollback_record() -> None:
    reg = registry()
    original = evaluation(reg)
    signed = approved_request(reg, original)
    changed_metrics = replace(
        original,
        family_metrics=(FamilyMetricsV1("owner_follow", {"success_rate": 0.95}),),
    )
    decision = PromotionGateV1(True, signed.policy.policy_digest).evaluate(
        registry=reg,
        evaluation=changed_metrics,
        request=signed,
        trusted_prior_model_digest=D3,
        signature_verifier=lambda *_: True,
        rollback_verifier=verify_rollback,
    )
    assert "human_review_payload_mismatch" in decision.reasons

    changed_safety = replace(
        original,
        safety=SafetyCountersV1((), false_arrivals=1, contacts=0, authority_bypasses=0),
    )
    decision = PromotionGateV1(True, signed.policy.policy_digest).evaluate(
        registry=reg,
        evaluation=changed_safety,
        request=signed,
        trusted_prior_model_digest=D3,
        signature_verifier=lambda *_: True,
        rollback_verifier=verify_rollback,
    )
    assert "human_review_payload_mismatch" in decision.reasons
    assert "nonzero_safety_counter" in decision.reasons

    assert signed.rollback is not None
    changed_rollback = replace(
        signed,
        rollback=replace(signed.rollback, test_evidence_digest=D5),
    )
    decision = PromotionGateV1(True, signed.policy.policy_digest).evaluate(
        registry=reg,
        evaluation=original,
        request=changed_rollback,
        trusted_prior_model_digest=D3,
        signature_verifier=lambda *_: True,
        rollback_verifier=verify_rollback,
    )
    assert "human_review_payload_mismatch" in decision.reasons
