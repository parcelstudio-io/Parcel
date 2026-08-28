"""Default-off, proposal-only promotion gate with an external signature seam."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .contracts import LearningContractError, boolean, canonical_digest, digest, finite, identifier
from .evaluation import CandidateEvaluationV1
from .registry import ScenarioRegistryV1

SignatureVerifier = Callable[[str, str, str], bool]


@dataclass(frozen=True, slots=True)
class MetricThresholdV1:
    family: str
    metric: str
    minimum: float

    def __post_init__(self) -> None:
        identifier(self.family, "threshold family")
        identifier(self.metric, "threshold metric")
        finite(self.minimum, "threshold minimum")


@dataclass(frozen=True, slots=True)
class PromotionPolicyV1:
    thresholds: tuple[MetricThresholdV1, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.thresholds, tuple):
            raise LearningContractError("promotion thresholds must be an immutable tuple")
        if not self.thresholds:
            raise LearningContractError("promotion policy must preregister thresholds")
        if len(self.thresholds) > 1_024:
            raise LearningContractError("promotion policy exceeds 1024 thresholds")
        if any(not isinstance(item, MetricThresholdV1) for item in self.thresholds):
            raise LearningContractError("thresholds must contain MetricThresholdV1 records")
        keys = tuple((item.family, item.metric) for item in self.thresholds)
        if len(set(keys)) != len(keys):
            raise LearningContractError("promotion thresholds must be unique")
        if keys != tuple(sorted(keys)):
            raise LearningContractError("promotion thresholds must be sorted")

    @property
    def policy_digest(self) -> str:
        return canonical_digest(
            {
                "schema": "promotion-policy-v1",
                "thresholds": [
                    {"family": item.family, "metric": item.metric, "minimum": item.minimum}
                    for item in self.thresholds
                ],
            }
        )


@dataclass(frozen=True, slots=True)
class HumanReviewV1:
    reviewer_id: str
    decision: str
    signed_payload_digest: str
    signer_key_id: str
    signature: str

    def __post_init__(self) -> None:
        identifier(self.reviewer_id, "reviewer_id")
        if self.decision not in {"approved", "rejected"}:
            raise LearningContractError("human decision must be approved or rejected")
        digest(self.signed_payload_digest, "signed_payload_digest")
        identifier(self.signer_key_id, "signer_key_id")
        if not isinstance(self.signature, str) or not self.signature or len(self.signature) > 4096:
            raise LearningContractError("signature must be a bounded non-empty string")


@dataclass(frozen=True, slots=True)
class RollbackArtifactV1:
    artifact_digest: str
    restores_model_digest: str
    test_evidence_digest: str
    tested: bool

    def __post_init__(self) -> None:
        digest(self.artifact_digest, "rollback artifact_digest")
        digest(self.restores_model_digest, "restores_model_digest")
        digest(self.test_evidence_digest, "rollback test_evidence_digest")
        boolean(self.tested, "rollback tested")

    @property
    def rollback_digest(self) -> str:
        return canonical_digest(
            {
                "schema": "rollback-artifact-v1",
                "artifact_digest": self.artifact_digest,
                "restores_model_digest": self.restores_model_digest,
                "test_evidence_digest": self.test_evidence_digest,
                "tested": self.tested,
            }
        )


RollbackVerifier = Callable[[RollbackArtifactV1], bool]


@dataclass(frozen=True, slots=True)
class PromotionRequestV1:
    expected_frozen_registry_digest: str
    expected_reproducibility_digest: str
    expected_evaluator_digest: str
    policy: PromotionPolicyV1
    review: HumanReviewV1 | None
    rollback: RollbackArtifactV1 | None

    def __post_init__(self) -> None:
        digest(self.expected_frozen_registry_digest, "expected_frozen_registry_digest")
        digest(self.expected_reproducibility_digest, "expected_reproducibility_digest")
        digest(self.expected_evaluator_digest, "expected_evaluator_digest")
        if not isinstance(self.policy, PromotionPolicyV1):
            raise LearningContractError("policy must be a PromotionPolicyV1 record")
        if self.review is not None and not isinstance(self.review, HumanReviewV1):
            raise LearningContractError("review must be a HumanReviewV1 record")
        if self.rollback is not None and not isinstance(self.rollback, RollbackArtifactV1):
            raise LearningContractError("rollback must be a RollbackArtifactV1 record")


@dataclass(frozen=True, slots=True)
class PromotionDecisionV1:
    decision: str
    reasons: tuple[str, ...]
    candidate_digest: str
    registry_digest: str
    authorizes_activation: bool = False

    def __post_init__(self) -> None:
        if self.decision not in {"reject", "propose_for_activation"}:
            raise LearningContractError("invalid promotion decision")
        if not isinstance(self.reasons, tuple):
            raise LearningContractError("promotion reasons must be an immutable tuple")
        for reason in self.reasons:
            if not isinstance(reason, str) or not reason or len(reason) > 256:
                raise LearningContractError("promotion reasons must be bounded strings")
        digest(self.candidate_digest, "candidate_digest")
        digest(self.registry_digest, "registry_digest")
        boolean(self.authorizes_activation, "authorizes_activation")
        if self.authorizes_activation:
            raise LearningContractError("promotion decisions cannot authorize activation")


@dataclass(frozen=True, slots=True)
class PromotionGateV1:
    enabled: bool = False
    expected_policy_digest: str | None = None

    def __post_init__(self) -> None:
        boolean(self.enabled, "promotion gate enabled")
        if self.expected_policy_digest is not None:
            digest(self.expected_policy_digest, "expected_policy_digest")

    def evaluate(
        self,
        *,
        registry: ScenarioRegistryV1,
        evaluation: CandidateEvaluationV1,
        request: PromotionRequestV1,
        trusted_prior_model_digest: str,
        signature_verifier: SignatureVerifier | None = None,
        rollback_verifier: RollbackVerifier | None = None,
    ) -> PromotionDecisionV1:
        if not isinstance(registry, ScenarioRegistryV1):
            raise LearningContractError("registry must be a ScenarioRegistryV1 record")
        if not isinstance(evaluation, CandidateEvaluationV1):
            raise LearningContractError("evaluation must be a CandidateEvaluationV1 record")
        if not isinstance(request, PromotionRequestV1):
            raise LearningContractError("request must be a PromotionRequestV1 record")
        if signature_verifier is not None and not callable(signature_verifier):
            raise LearningContractError("signature_verifier must be callable")
        prior_model = digest(trusted_prior_model_digest, "trusted_prior_model_digest")
        if rollback_verifier is not None and not callable(rollback_verifier):
            raise LearningContractError("rollback_verifier must be callable")
        reasons = self._rejection_reasons(
            registry,
            evaluation,
            request,
            signature_verifier,
            prior_model,
            rollback_verifier,
        )
        return PromotionDecisionV1(
            decision="reject" if reasons else "propose_for_activation",
            reasons=tuple(reasons),
            candidate_digest=evaluation.candidate_digest,
            registry_digest=registry.registry_digest,
        )

    def _rejection_reasons(
        self,
        registry: ScenarioRegistryV1,
        evaluation: CandidateEvaluationV1,
        request: PromotionRequestV1,
        verifier: SignatureVerifier | None,
        trusted_prior_model_digest: str,
        rollback_verifier: RollbackVerifier | None,
    ) -> list[str]:
        reasons: list[str] = []
        if not self.enabled:
            reasons.append("gate_disabled")
        if self.expected_policy_digest is None:
            reasons.append("expected_policy_digest_missing")
        elif request.policy.policy_digest != self.expected_policy_digest:
            reasons.append("promotion_policy_digest_mismatch")
        if evaluation.registry_digest != registry.registry_digest:
            reasons.append("registry_digest_mismatch")
        if request.expected_frozen_registry_digest != registry.frozen_test_digest:
            reasons.append("frozen_registry_digest_mismatch")
        if evaluation.evaluator_digest != request.expected_evaluator_digest:
            reasons.append("evaluator_digest_mismatch")
        if evaluation.reproducibility_digest != request.expected_reproducibility_digest:
            reasons.append("reproducibility_digest_mismatch")
        if not evaluation.safety.is_zero:
            reasons.append("nonzero_safety_counter")
        reasons.extend(self._threshold_reasons(evaluation, request.policy))
        reasons.extend(
            self._rollback_reasons(
                request.rollback,
                trusted_prior_model_digest,
                rollback_verifier,
            )
        )
        reasons.extend(self._review_reasons(evaluation, request, verifier))
        return reasons

    @staticmethod
    def _threshold_reasons(
        evaluation: CandidateEvaluationV1, policy: PromotionPolicyV1
    ) -> list[str]:
        reasons: list[str] = []
        for threshold in policy.thresholds:
            measured = evaluation.metric(threshold.family, threshold.metric)
            if measured is None:
                reasons.append(f"threshold_metric_missing:{threshold.family}:{threshold.metric}")
            elif measured < threshold.minimum:
                reasons.append(f"threshold_not_met:{threshold.family}:{threshold.metric}")
        return reasons

    @staticmethod
    def _rollback_reasons(
        rollback: RollbackArtifactV1 | None,
        trusted_prior_model_digest: str,
        verifier: RollbackVerifier | None,
    ) -> list[str]:
        if rollback is None:
            return ["rollback_missing"]
        reasons: list[str] = []
        if not rollback.tested:
            reasons.append("rollback_not_tested")
        if rollback.restores_model_digest != trusted_prior_model_digest:
            reasons.append("rollback_prior_model_mismatch")
        if verifier is None:
            reasons.append("rollback_verifier_missing")
        else:
            try:
                verified = verifier(rollback)
            except Exception:  # noqa: BLE001
                reasons.append("rollback_verifier_error")
            else:
                if verified is not True:
                    reasons.append("rollback_verification_failed")
        return reasons

    @staticmethod
    def _review_reasons(
        evaluation: CandidateEvaluationV1,
        request: PromotionRequestV1,
        verifier: SignatureVerifier | None,
    ) -> list[str]:
        review = request.review
        if review is None:
            return ["human_review_missing"]
        if review.decision != "approved":
            return ["human_review_rejected"]
        expected = review_payload_digest(
            evaluation,
            request.policy,
            request.rollback,
            reviewer_id=review.reviewer_id,
            signer_key_id=review.signer_key_id,
        )
        if review.signed_payload_digest != expected:
            return ["human_review_payload_mismatch"]
        if verifier is None:
            return ["signature_verifier_missing"]
        try:
            verified = verifier(review.signer_key_id, review.signed_payload_digest, review.signature)
        # The verifier is an external trust-provider seam.  Any provider
        # failure, including an implementation-specific exception, is denial.
        except Exception:  # noqa: BLE001
            return ["signature_verifier_error"]
        return [] if verified is True else ["signature_invalid"]


def review_payload_digest(
    evaluation: CandidateEvaluationV1,
    policy: PromotionPolicyV1,
    rollback: RollbackArtifactV1 | None,
    *,
    reviewer_id: str,
    signer_key_id: str,
) -> str:
    reviewer = identifier(reviewer_id, "reviewer_id")
    signer = identifier(signer_key_id, "signer_key_id")
    return canonical_digest(
        {
            "namespace": "human-promotion-review-v1",
            "reviewer_id": reviewer,
            "signer_key_id": signer,
            "candidate_digest": evaluation.candidate_digest,
            "evaluation_digest": evaluation.evaluation_digest,
            "model_digest": evaluation.model_digest,
            "config_digest": evaluation.config_digest,
            "registry_digest": evaluation.registry_digest,
            "evaluator_digest": evaluation.evaluator_digest,
            "reproducibility_digest": evaluation.reproducibility_digest,
            "policy_digest": policy.policy_digest,
            "rollback_digest": None if rollback is None else rollback.rollback_digest,
        }
    )
