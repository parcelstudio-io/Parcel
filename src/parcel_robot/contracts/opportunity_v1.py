"""Fail-closed candidate for owner-consented proactive conversation.

The candidate is sensing evidence, not permission to speak and never permission
to move.  A local gate must still enforce feature enablement, freshness,
identity, consent, privacy, quiet state, turn-taking, novelty, and cooldown.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from parcel_robot.contracts.companion_v1 import (
    PRIVACY_STATES,
    QUIET_STATES,
    SCHEMA_VERSION,
    ConsentDecisionV1,
    OwnerEvidenceV1,
    _boolean,
    _enum,
    _exact,
    _identifier,
    _integer,
    _mapping,
    _real,
    _text,
)


@dataclass(frozen=True, slots=True)
class OpportunityCandidateV1:
    candidate_id: str
    source_epoch: int
    subject_id: str
    event_class: str
    evidence_id: str
    observed_monotonic_ns: int
    received_monotonic_ns: int
    expires_monotonic_ns: int
    novelty: float
    confidence: float
    owner: OwnerEvidenceV1
    privacy_state: str
    quiet_state: str
    owner_speaking: bool
    tts_active: bool
    proactive_consent: ConsentDecisionV1
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION or isinstance(self.schema_version, bool):
            raise ValueError(f"schema_version must equal {SCHEMA_VERSION}")
        _identifier(self.candidate_id, "candidate_id")
        epoch = _integer(self.source_epoch, "source_epoch")
        _identifier(self.subject_id, "subject_id")
        _identifier(self.event_class, "event_class")
        _identifier(self.evidence_id, "evidence_id")
        observed = _integer(self.observed_monotonic_ns, "observed_monotonic_ns")
        received = _integer(self.received_monotonic_ns, "received_monotonic_ns")
        expires = _integer(self.expires_monotonic_ns, "expires_monotonic_ns")
        if received < observed:
            raise ValueError("opportunity cannot be received before it was observed")
        if expires <= received:
            raise ValueError("opportunity expiry must be after receipt")
        _real(self.novelty, "novelty", minimum=0.0, maximum=1.0)
        _real(self.confidence, "confidence", minimum=0.0, maximum=1.0)
        if not isinstance(self.owner, OwnerEvidenceV1):
            raise TypeError("owner must be OwnerEvidenceV1")
        if self.owner.source_epoch != epoch:
            raise ValueError("opportunity and owner evidence source epochs must match")
        _enum(self.privacy_state, PRIVACY_STATES, "privacy_state")
        _enum(self.quiet_state, QUIET_STATES, "quiet_state")
        _boolean(self.owner_speaking, "owner_speaking")
        _boolean(self.tts_active, "tts_active")
        if not isinstance(self.proactive_consent, ConsentDecisionV1):
            raise TypeError("proactive_consent must be ConsentDecisionV1")
        if self.proactive_consent.source_epoch != epoch:
            raise ValueError("opportunity and proactive consent source epochs must match")

    @property
    def authorizes_speech(self) -> bool:
        return False

    @property
    def authorizes_motion(self) -> bool:
        return False

    def evidence_age_ns(self, now_monotonic_ns: int) -> int:
        now = _integer(now_monotonic_ns, "now_monotonic_ns")
        if now < self.received_monotonic_ns:
            raise ValueError("opportunity receipt is in the future")
        return now - self.received_monotonic_ns

    def fresh(self, now_monotonic_ns: int) -> bool:
        now = _integer(now_monotonic_ns, "now_monotonic_ns")
        return self.received_monotonic_ns <= now < self.expires_monotonic_ns

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> OpportunityCandidateV1:
        data = _mapping(value, "OpportunityCandidateV1")
        fields = {
            "schema_version",
            "candidate_id",
            "source_epoch",
            "subject_id",
            "event_class",
            "evidence_id",
            "observed_monotonic_ns",
            "received_monotonic_ns",
            "expires_monotonic_ns",
            "novelty",
            "confidence",
            "owner",
            "privacy_state",
            "quiet_state",
            "owner_speaking",
            "tts_active",
            "proactive_consent",
        }
        _exact(data, fields, "OpportunityCandidateV1")
        return cls(
            schema_version=_integer(data["schema_version"], "schema_version"),
            candidate_id=_text(data["candidate_id"], "candidate_id", maximum=128),
            source_epoch=_integer(data["source_epoch"], "source_epoch"),
            subject_id=_text(data["subject_id"], "subject_id", maximum=128),
            event_class=_text(data["event_class"], "event_class", maximum=128),
            evidence_id=_text(data["evidence_id"], "evidence_id", maximum=128),
            observed_monotonic_ns=_integer(
                data["observed_monotonic_ns"], "observed_monotonic_ns"
            ),
            received_monotonic_ns=_integer(
                data["received_monotonic_ns"], "received_monotonic_ns"
            ),
            expires_monotonic_ns=_integer(
                data["expires_monotonic_ns"], "expires_monotonic_ns"
            ),
            novelty=_real(data["novelty"], "novelty"),
            confidence=_real(data["confidence"], "confidence"),
            owner=OwnerEvidenceV1.from_mapping(_mapping(data["owner"], "owner")),
            privacy_state=_text(data["privacy_state"], "privacy_state", maximum=64),
            quiet_state=_text(data["quiet_state"], "quiet_state", maximum=64),
            owner_speaking=_boolean(data["owner_speaking"], "owner_speaking"),
            tts_active=_boolean(data["tts_active"], "tts_active"),
            proactive_consent=ConsentDecisionV1.from_mapping(
                _mapping(data["proactive_consent"], "proactive_consent")
            ),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "candidate_id": self.candidate_id,
            "source_epoch": self.source_epoch,
            "subject_id": self.subject_id,
            "event_class": self.event_class,
            "evidence_id": self.evidence_id,
            "observed_monotonic_ns": self.observed_monotonic_ns,
            "received_monotonic_ns": self.received_monotonic_ns,
            "expires_monotonic_ns": self.expires_monotonic_ns,
            "novelty": self.novelty,
            "confidence": self.confidence,
            "owner": self.owner.as_dict(),
            "privacy_state": self.privacy_state,
            "quiet_state": self.quiet_state,
            "owner_speaking": self.owner_speaking,
            "tts_active": self.tts_active,
            "proactive_consent": self.proactive_consent.as_dict(),
        }


__all__ = ["OpportunityCandidateV1"]
