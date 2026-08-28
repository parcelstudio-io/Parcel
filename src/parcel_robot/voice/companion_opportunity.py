"""Local, proposal-only admission for proactive conversation opportunities."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from parcel_robot.contracts.companion_v1 import (
    OPPORTUNITY_DECISIONS,
    SCHEMA_VERSION,
    _boolean,
    _enum,
    _identifier,
    _integer,
    _real,
)
from parcel_robot.contracts.opportunity_v1 import OpportunityCandidateV1

MAX_ENVELOPE_TTL_NS = 2_000_000_000
MAX_OWNER_EVIDENCE_TTL_NS = 10_000_000_000
MAX_CONSENT_TTL_NS = 60_000_000_000


@dataclass(frozen=True, slots=True)
class OpportunityAdmissionV1:
    candidate_id: str
    decision: str
    reason: str
    evaluated_at_monotonic_ns: int
    subject_id: str
    evidence_id: str
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION or isinstance(self.schema_version, bool):
            raise ValueError(f"schema_version must equal {SCHEMA_VERSION}")
        _identifier(self.candidate_id, "opportunity candidate_id", empty=True)
        _enum(self.decision, OPPORTUNITY_DECISIONS, "opportunity decision")
        _identifier(self.reason, "opportunity reason")
        _integer(self.evaluated_at_monotonic_ns, "opportunity evaluated time")
        _identifier(self.subject_id, "opportunity subject_id", empty=True)
        _identifier(self.evidence_id, "opportunity evidence_id", empty=True)
        if self.decision == "admit_for_phrasing" and (
            not self.candidate_id or not self.subject_id or not self.evidence_id
        ):
            raise ValueError("admitted opportunity requires candidate, subject, and evidence IDs")

    @property
    def admitted_for_phrasing(self) -> bool:
        return self.decision == "admit_for_phrasing"

    @property
    def authorizes_motion(self) -> bool:
        return False

    @property
    def authorizes_speech(self) -> bool:
        """Phrasing admission still has to acquire the local output lane."""

        return False

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "candidate_id": self.candidate_id,
            "decision": self.decision,
            "reason": self.reason,
            "evaluated_at_monotonic_ns": self.evaluated_at_monotonic_ns,
            "subject_id": self.subject_id,
            "evidence_id": self.evidence_id,
        }


def _lifetime_exceeds(start: int, end: int, maximum: int) -> bool:
    return end - start > maximum


def _opportunity_ttl_reason(candidate: OpportunityCandidateV1) -> str | None:
    if _lifetime_exceeds(
        candidate.received_monotonic_ns,
        candidate.expires_monotonic_ns,
        MAX_ENVELOPE_TTL_NS,
    ):
        return "opportunity_ttl_exceeds_limit"
    if _lifetime_exceeds(
        candidate.owner.received_monotonic_ns,
        candidate.owner.expires_monotonic_ns,
        MAX_OWNER_EVIDENCE_TTL_NS,
    ):
        return "owner_evidence_ttl_exceeds_limit"
    proactive = candidate.proactive_consent
    if proactive.decided_at_monotonic_ns is None or proactive.expires_at_monotonic_ns is None:
        return None
    if _lifetime_exceeds(
        proactive.decided_at_monotonic_ns,
        proactive.expires_at_monotonic_ns,
        MAX_CONSENT_TTL_NS,
    ):
        return "consent_ttl_exceeds_limit"
    return None


def admit_opportunity(
    candidate: OpportunityCandidateV1,
    *,
    now_monotonic_ns: int,
    current_source_epoch: int,
    feature_enabled: bool = False,
    lane_busy: bool = False,
    minimum_owner_confidence: float = 0.80,
    minimum_novelty: float = 0.60,
    minimum_event_confidence: float = 0.70,
    maximum_evidence_age_ns: int = 2_000_000_000,
    last_subject_at_monotonic_ns: int | None = None,
    subject_cooldown_ns: int = 600_000_000_000,
) -> OpportunityAdmissionV1:
    """Apply the local proactive gate. Default feature state is off."""

    if not isinstance(candidate, OpportunityCandidateV1):
        raise TypeError("candidate must be OpportunityCandidateV1")
    now = _integer(now_monotonic_ns, "now_monotonic_ns")
    epoch = _integer(current_source_epoch, "current_source_epoch")
    _boolean(feature_enabled, "feature_enabled")
    _boolean(lane_busy, "lane_busy")
    owner_threshold = _real(
        minimum_owner_confidence, "minimum_owner_confidence", minimum=0.0, maximum=1.0
    )
    novelty_threshold = _real(minimum_novelty, "minimum_novelty", minimum=0.0, maximum=1.0)
    confidence_threshold = _real(
        minimum_event_confidence,
        "minimum_event_confidence",
        minimum=0.0,
        maximum=1.0,
    )
    max_age = _integer(maximum_evidence_age_ns, "maximum_evidence_age_ns", minimum=1)
    cooldown = _integer(subject_cooldown_ns, "subject_cooldown_ns")

    def result(decision: str, reason: str) -> OpportunityAdmissionV1:
        return OpportunityAdmissionV1(
            candidate.candidate_id,
            decision,
            reason,
            now,
            candidate.subject_id,
            candidate.evidence_id,
        )

    if not feature_enabled:
        return result("drop", "proactive_feature_disabled")
    if candidate.source_epoch != epoch:
        return result("drop", "source_epoch_mismatch")
    try:
        age = candidate.evidence_age_ns(now)
    except ValueError:
        return result("drop", "evidence_from_future")
    if not candidate.fresh(now) or age > max_age:
        return result("drop", "evidence_stale")
    ttl_reason = _opportunity_ttl_reason(candidate)
    if ttl_reason is not None:
        return result("drop", ttl_reason)
    if not candidate.owner.fresh_and_verified(now, minimum_confidence=owner_threshold):
        return result("drop", "owner_unverified_or_stale")
    if not candidate.proactive_consent.granted_at(
        now, principal_id=candidate.owner.principal_id
    ):
        return result("drop", "proactive_consent_not_granted")
    if candidate.privacy_state != "public":
        return result("drop", "privacy_not_public")
    if candidate.quiet_state != "normal":
        return result("drop", "quiet_state_blocks")
    if candidate.owner_speaking:
        return result("drop", "owner_speaking")
    if candidate.tts_active or lane_busy:
        return result("drop", "output_lane_busy")
    if candidate.novelty < novelty_threshold:
        return result("drop", "low_novelty")
    if candidate.confidence < confidence_threshold:
        return result("drop", "low_event_confidence")
    if last_subject_at_monotonic_ns is not None:
        last = _integer(last_subject_at_monotonic_ns, "last_subject_at_monotonic_ns")
        if last > now:
            return result("drop", "subject_history_from_future")
        if now - last < cooldown:
            return result("drop", "subject_cooldown")
    return result("admit_for_phrasing", "local_opportunity_gate_passed")


def admit_opportunity_mapping(
    raw: Mapping[str, object],
    *,
    now_monotonic_ns: int,
    current_source_epoch: int,
    feature_enabled: bool = False,
    **kwargs: object,
) -> OpportunityAdmissionV1:
    """Strict raw boundary: malformed input becomes auditable ``drop_invalid``."""

    now = _integer(now_monotonic_ns, "now_monotonic_ns")
    try:
        candidate = OpportunityCandidateV1.from_mapping(raw)
    except (TypeError, ValueError):
        return OpportunityAdmissionV1(
            "", "drop_invalid", "invalid_opportunity_candidate", now, "", ""
        )
    return admit_opportunity(
        candidate,
        now_monotonic_ns=now,
        current_source_epoch=current_source_epoch,
        feature_enabled=feature_enabled,
        **kwargs,
    )


__all__ = ["OpportunityAdmissionV1", "admit_opportunity", "admit_opportunity_mapping"]
