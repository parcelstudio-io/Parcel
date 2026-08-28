"""Strict conversation/embodiment read models for the companion executive.

These records deliberately contain no actuator handle.  A hosted or local
language model may construct :class:`ConversationActionProposalV1`, but only
the local policy in :mod:`parcel_robot.voice.companion_state` can turn it into
an *admission candidate* for the executive.  Even that admission is not a
motion command: the existing executive, safety supervisor, and sole writer
remain authoritative.

Every mapping decoder is exact and fail closed.  This matters at the model and
research-replay boundaries, where permissive defaults would silently turn
missing consent, identity, or freshness evidence into permission.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

SCHEMA_VERSION = 1

CONSENT_STATES = frozenset({"unknown", "granted", "denied", "revoked"})
CONSENT_SCOPES = frozenset(
    {
        "speech",
        "proactive_speech",
        "stationary_expression",
        "approach",
        "following",
        "owner_search",
        "navigation",
    }
)
ACTION_CONSENT_SCOPES = CONSENT_SCOPES | {"not_applicable"}
ACTION_RECEIPT_STATUSES = frozenset(
    {"admitted", "started", "succeeded", "failed", "cancelled", "rejected"}
)
TERMINAL_ACTION_STATUSES = frozenset({"succeeded", "failed", "cancelled", "rejected"})
ACTION_ADMISSION_DECISIONS = frozenset({"admit_to_executive", "reject", "defer"})
ACTION_INITIATORS = frozenset({"owner", "system", "operator"})
BODY_MODES = frozenset({"idle", "stationary", "locomoting", "transitioning", "fault", "unknown"})
ESTOP_STATES = frozenset({"clear", "active", "unknown"})
AFFORDANCE_STATES = frozenset({"ready", "blocked", "unknown"})
SPACE_STATES = frozenset({"clear", "occupied", "unknown"})
PENDING_ACTION_STATES = frozenset({"admitted", "started", "cancel_requested"})
CORRECTION_KINDS = frozenset({"replace", "cancel", "hold", "referent"})
CORRECTION_STATES = frozenset({"pending", "applied", "rejected"})
MEMORY_SOURCES = frozenset({"owner", "operator", "observation", "inferred"})
PRIVACY_STATES = frozenset({"public", "private", "unknown"})
QUIET_STATES = frozenset({"normal", "quiet", "unknown"})
OPPORTUNITY_DECISIONS = frozenset({"admit_for_phrasing", "drop", "drop_invalid"})

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_DERIVED_ID_RE = re.compile(r"^(?:mission|action|receipt)-[0-9a-f]{24}$")
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} must be a mapping")
    return value


def _exact(data: Mapping[str, object], fields: set[str], name: str) -> None:
    missing = fields - set(data)
    unknown = set(data) - fields
    if missing:
        raise ValueError(f"{name} missing fields: {sorted(missing)}")
    if unknown:
        raise ValueError(f"{name} has unknown fields: {sorted(unknown)}")


def _integer(value: object, name: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    if value < minimum or value > (1 << 64) - 1:
        raise ValueError(f"{name} must be between {minimum} and 2^64-1")
    return value


def _real(
    value: object,
    name: str,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    if minimum is not None and result < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    if maximum is not None and result > maximum:
        raise ValueError(f"{name} must be at most {maximum}")
    return result


def _boolean(value: object, name: str) -> bool:
    if type(value) is not bool:
        raise TypeError(f"{name} must be a boolean")
    return value


def _text(value: object, name: str, *, maximum: int = 256, empty: bool = False) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    if value != value.strip():
        raise ValueError(f"{name} cannot have leading or trailing whitespace")
    if not empty and not value:
        raise ValueError(f"{name} cannot be empty")
    if len(value) > maximum:
        raise ValueError(f"{name} exceeds {maximum} characters")
    return value


def _identifier(value: object, name: str, *, empty: bool = False) -> str:
    result = _text(value, name, maximum=128, empty=empty)
    if result and _ID_RE.fullmatch(result) is None:
        raise ValueError(f"{name} is not a valid identifier")
    return result


def _derived_identifier(value: object, name: str) -> str:
    result = _identifier(value, name)
    if _DERIVED_ID_RE.fullmatch(result) is None:
        raise ValueError(f"{name} is not a locally derived identifier")
    return result


def _digest(value: object, name: str = "manifest_digest") -> str:
    result = _text(value, name, maximum=64)
    if _DIGEST_RE.fullmatch(result) is None:
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return result


def _enum(value: object, allowed: frozenset[str], name: str) -> str:
    result = _text(value, name, maximum=64)
    if result not in allowed:
        raise ValueError(f"{name} must be one of {sorted(allowed)}")
    return result


def _optional_identifier(value: object, name: str) -> str | None:
    if value is None:
        return None
    return _identifier(value, name)


def _optional_integer(value: object, name: str) -> int | None:
    if value is None:
        return None
    return _integer(value, name)


def _strings(value: object, name: str, *, maximum: int = 32) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise TypeError(f"{name} must be a sequence")
    if len(value) > maximum:
        raise ValueError(f"{name} exceeds {maximum} items")
    result = tuple(_identifier(item, f"{name} item") for item in value)
    if len(set(result)) != len(result):
        raise ValueError(f"{name} cannot contain duplicates")
    return result


def _canonical_digest(namespace: str, payload: Mapping[str, object]) -> str:
    encoded = json.dumps(
        {"namespace": namespace, **dict(payload)},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def derive_mission_id(*, turn_id: str, proposal_id: str, manifest_digest: str) -> str:
    """Derive an idempotent local mission ID from one admitted proposal."""

    payload = {
        "turn_id": _identifier(turn_id, "turn_id"),
        "proposal_id": _identifier(proposal_id, "proposal_id"),
        "manifest_digest": _digest(manifest_digest),
    }
    return f"mission-{_canonical_digest('companion-mission-v1', payload)[:24]}"


def derive_action_id(*, mission_id: str, proposal_id: str, action_name: str) -> str:
    """Derive an idempotent action ID; the model never chooses it."""

    payload = {
        "mission_id": _derived_identifier(mission_id, "mission_id"),
        "proposal_id": _identifier(proposal_id, "proposal_id"),
        "action_name": _identifier(action_name, "action_name"),
    }
    return f"action-{_canonical_digest('companion-action-v1', payload)[:24]}"


@dataclass(frozen=True, slots=True)
class ConsentDecisionV1:
    """One explicit, expiring consent decision for exactly one scope."""

    status: str
    principal_id: str
    evidence_id: str
    source_epoch: int
    decided_at_monotonic_ns: int | None
    expires_at_monotonic_ns: int | None
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION or isinstance(self.schema_version, bool):
            raise ValueError(f"schema_version must equal {SCHEMA_VERSION}")
        _enum(self.status, CONSENT_STATES, "consent status")
        _identifier(self.principal_id, "consent principal_id", empty=True)
        _identifier(self.evidence_id, "consent evidence_id", empty=True)
        _integer(self.source_epoch, "consent source_epoch")
        decided = _optional_integer(self.decided_at_monotonic_ns, "consent decided time")
        expires = _optional_integer(self.expires_at_monotonic_ns, "consent expiry time")
        if self.status == "granted":
            if not self.principal_id or not self.evidence_id:
                raise ValueError("granted consent requires principal_id and evidence_id")
            if decided is None or expires is None or expires <= decided:
                raise ValueError("granted consent requires a positive bounded lifetime")
        elif expires is not None and decided is not None and expires <= decided:
            raise ValueError("consent expiry must be after its decision time")

    def granted_at(self, now_monotonic_ns: int, *, principal_id: str) -> bool:
        now = _integer(now_monotonic_ns, "now_monotonic_ns")
        if self.status != "granted" or self.principal_id != principal_id:
            return False
        assert self.decided_at_monotonic_ns is not None
        assert self.expires_at_monotonic_ns is not None
        return self.decided_at_monotonic_ns <= now < self.expires_at_monotonic_ns

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> ConsentDecisionV1:
        data = _mapping(value, "ConsentDecisionV1")
        fields = {
            "schema_version",
            "status",
            "principal_id",
            "evidence_id",
            "source_epoch",
            "decided_at_monotonic_ns",
            "expires_at_monotonic_ns",
        }
        _exact(data, fields, "ConsentDecisionV1")
        return cls(
            schema_version=_integer(data["schema_version"], "schema_version"),
            status=_text(data["status"], "status", maximum=64),
            principal_id=_text(data["principal_id"], "principal_id", maximum=128, empty=True),
            evidence_id=_text(data["evidence_id"], "evidence_id", maximum=128, empty=True),
            source_epoch=_integer(data["source_epoch"], "source_epoch"),
            decided_at_monotonic_ns=_optional_integer(
                data["decided_at_monotonic_ns"], "decided_at_monotonic_ns"
            ),
            expires_at_monotonic_ns=_optional_integer(
                data["expires_at_monotonic_ns"], "expires_at_monotonic_ns"
            ),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "principal_id": self.principal_id,
            "evidence_id": self.evidence_id,
            "source_epoch": self.source_epoch,
            "decided_at_monotonic_ns": self.decided_at_monotonic_ns,
            "expires_at_monotonic_ns": self.expires_at_monotonic_ns,
        }


@dataclass(frozen=True, slots=True)
class ConsentScopesV1:
    """Consent is never a single robot-wide boolean.

    All seven scopes are required on the wire, including unknown/denied ones,
    so adding a behavior cannot inherit an unrelated permission by omission.
    """

    speech: ConsentDecisionV1
    proactive_speech: ConsentDecisionV1
    stationary_expression: ConsentDecisionV1
    approach: ConsentDecisionV1
    following: ConsentDecisionV1
    owner_search: ConsentDecisionV1
    navigation: ConsentDecisionV1
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION or isinstance(self.schema_version, bool):
            raise ValueError(f"schema_version must equal {SCHEMA_VERSION}")
        for scope in CONSENT_SCOPES:
            if not isinstance(getattr(self, scope), ConsentDecisionV1):
                raise TypeError(f"{scope} must be ConsentDecisionV1")

    def for_scope(self, scope: str) -> ConsentDecisionV1:
        return getattr(self, _enum(scope, CONSENT_SCOPES, "consent scope"))

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> ConsentScopesV1:
        data = _mapping(value, "ConsentScopesV1")
        fields = {"schema_version", *CONSENT_SCOPES}
        _exact(data, fields, "ConsentScopesV1")
        return cls(
            schema_version=_integer(data["schema_version"], "schema_version"),
            **{
                scope: ConsentDecisionV1.from_mapping(
                    _mapping(data[scope], f"ConsentScopesV1.{scope}")
                )
                for scope in CONSENT_SCOPES
            },
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            **{scope: self.for_scope(scope).as_dict() for scope in sorted(CONSENT_SCOPES)},
        }


@dataclass(frozen=True, slots=True)
class OwnerEvidenceV1:
    principal_id: str
    verified: bool
    confidence: float
    evidence_id: str
    source_epoch: int
    received_monotonic_ns: int
    expires_monotonic_ns: int
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION or isinstance(self.schema_version, bool):
            raise ValueError(f"schema_version must equal {SCHEMA_VERSION}")
        _identifier(self.principal_id, "owner principal_id", empty=True)
        _boolean(self.verified, "owner verified")
        _real(self.confidence, "owner confidence", minimum=0.0, maximum=1.0)
        _identifier(self.evidence_id, "owner evidence_id", empty=not self.verified)
        _integer(self.source_epoch, "owner source_epoch")
        received = _integer(self.received_monotonic_ns, "owner received time")
        expires = _integer(self.expires_monotonic_ns, "owner expiry time")
        if expires <= received:
            raise ValueError("owner evidence expiry must be after receipt")
        if self.verified and (not self.principal_id or not self.evidence_id):
            raise ValueError("verified owner evidence requires principal_id and evidence_id")

    def fresh_and_verified(self, now_monotonic_ns: int, *, minimum_confidence: float) -> bool:
        now = _integer(now_monotonic_ns, "now_monotonic_ns")
        threshold = _real(
            minimum_confidence,
            "minimum owner confidence",
            minimum=0.0,
            maximum=1.0,
        )
        return (
            self.verified
            and self.received_monotonic_ns <= now < self.expires_monotonic_ns
            and self.confidence >= threshold
        )

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> OwnerEvidenceV1:
        data = _mapping(value, "OwnerEvidenceV1")
        fields = {
            "schema_version",
            "principal_id",
            "verified",
            "confidence",
            "evidence_id",
            "source_epoch",
            "received_monotonic_ns",
            "expires_monotonic_ns",
        }
        _exact(data, fields, "OwnerEvidenceV1")
        return cls(
            schema_version=_integer(data["schema_version"], "schema_version"),
            principal_id=_text(data["principal_id"], "principal_id", maximum=128, empty=True),
            verified=_boolean(data["verified"], "verified"),
            confidence=_real(data["confidence"], "confidence"),
            evidence_id=_text(data["evidence_id"], "evidence_id", maximum=128, empty=True),
            source_epoch=_integer(data["source_epoch"], "source_epoch"),
            received_monotonic_ns=_integer(
                data["received_monotonic_ns"], "received_monotonic_ns"
            ),
            expires_monotonic_ns=_integer(
                data["expires_monotonic_ns"], "expires_monotonic_ns"
            ),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "principal_id": self.principal_id,
            "verified": self.verified,
            "confidence": self.confidence,
            "evidence_id": self.evidence_id,
            "source_epoch": self.source_epoch,
            "received_monotonic_ns": self.received_monotonic_ns,
            "expires_monotonic_ns": self.expires_monotonic_ns,
        }


@dataclass(frozen=True, slots=True)
class OperatorEvidenceV1(OwnerEvidenceV1):
    """Authenticated operator evidence, kept distinct from owner evidence."""


@dataclass(frozen=True, slots=True)
class EmbodimentEnvelopeV1:
    """Fresh local body/capability/consent facts exposed to conversation."""

    envelope_id: str
    manifest_digest: str
    commissioned_actions: tuple[str, ...]
    action_bindings_digest: str
    snapshot_monotonic_ns: int
    expires_monotonic_ns: int
    initiator: str
    owner: OwnerEvidenceV1
    operator: OperatorEvidenceV1 | None
    body_mode: str
    estop_state: str
    locomotion_commissioned: bool
    locomotion_healthy: bool
    affordance_state: str
    space_state: str
    pending_action_id: str | None
    pending_action_status: str
    last_terminal_receipt_id: str | None
    busy_reason: str
    consent: ConsentScopesV1
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION or isinstance(self.schema_version, bool):
            raise ValueError(f"schema_version must equal {SCHEMA_VERSION}")
        _identifier(self.envelope_id, "envelope_id")
        _digest(self.manifest_digest)
        _digest(self.action_bindings_digest, "action_bindings_digest")
        if not isinstance(self.commissioned_actions, tuple):
            raise TypeError("commissioned_actions must be a tuple")
        actions = _strings(self.commissioned_actions, "commissioned_actions", maximum=256)
        if actions != tuple(sorted(actions)):
            raise ValueError("commissioned_actions must be sorted")
        snapshot = _integer(self.snapshot_monotonic_ns, "snapshot_monotonic_ns")
        expiry = _integer(self.expires_monotonic_ns, "expires_monotonic_ns")
        if expiry <= snapshot:
            raise ValueError("embodiment envelope expiry must be after snapshot")
        _enum(self.initiator, ACTION_INITIATORS, "initiator")
        if not isinstance(self.owner, OwnerEvidenceV1):
            raise TypeError("owner must be OwnerEvidenceV1")
        if self.operator is not None and not isinstance(
            self.operator, OperatorEvidenceV1
        ):
            raise TypeError("operator must be OperatorEvidenceV1 or None")
        if self.operator is not None and self.operator.source_epoch != self.owner.source_epoch:
            raise ValueError("operator and owner evidence source epochs must match")
        if not isinstance(self.consent, ConsentScopesV1):
            raise TypeError("consent must be ConsentScopesV1")
        if any(
            self.consent.for_scope(scope).source_epoch != self.owner.source_epoch
            for scope in CONSENT_SCOPES
        ):
            raise ValueError("consent and owner evidence source epochs must match")
        _enum(self.body_mode, BODY_MODES, "body_mode")
        _enum(self.estop_state, ESTOP_STATES, "estop_state")
        _boolean(self.locomotion_commissioned, "locomotion_commissioned")
        _boolean(self.locomotion_healthy, "locomotion_healthy")
        _enum(self.affordance_state, AFFORDANCE_STATES, "affordance_state")
        _enum(self.space_state, SPACE_STATES, "space_state")
        _optional_identifier(self.pending_action_id, "pending_action_id")
        _text(self.pending_action_status, "pending_action_status", maximum=64, empty=True)
        if bool(self.pending_action_id) != bool(self.pending_action_status):
            raise ValueError("pending action ID and status must be present together")
        if self.last_terminal_receipt_id is not None:
            _derived_identifier(self.last_terminal_receipt_id, "last_terminal_receipt_id")
        _text(self.busy_reason, "busy_reason", maximum=256, empty=True)

    def fresh(self, now_monotonic_ns: int) -> bool:
        now = _integer(now_monotonic_ns, "now_monotonic_ns")
        return self.snapshot_monotonic_ns <= now < self.expires_monotonic_ns

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> EmbodimentEnvelopeV1:
        data = _mapping(value, "EmbodimentEnvelopeV1")
        fields = {
            "schema_version",
            "envelope_id",
            "manifest_digest",
            "commissioned_actions",
            "action_bindings_digest",
            "snapshot_monotonic_ns",
            "expires_monotonic_ns",
            "initiator",
            "owner",
            "operator",
            "body_mode",
            "estop_state",
            "locomotion_commissioned",
            "locomotion_healthy",
            "affordance_state",
            "space_state",
            "pending_action_id",
            "pending_action_status",
            "last_terminal_receipt_id",
            "busy_reason",
            "consent",
        }
        _exact(data, fields, "EmbodimentEnvelopeV1")
        return cls(
            schema_version=_integer(data["schema_version"], "schema_version"),
            envelope_id=_text(data["envelope_id"], "envelope_id", maximum=128),
            manifest_digest=_text(data["manifest_digest"], "manifest_digest", maximum=64),
            commissioned_actions=_strings(
                data["commissioned_actions"], "commissioned_actions", maximum=256
            ),
            action_bindings_digest=_text(
                data["action_bindings_digest"],
                "action_bindings_digest",
                maximum=64,
            ),
            snapshot_monotonic_ns=_integer(
                data["snapshot_monotonic_ns"], "snapshot_monotonic_ns"
            ),
            expires_monotonic_ns=_integer(
                data["expires_monotonic_ns"], "expires_monotonic_ns"
            ),
            initiator=_text(data["initiator"], "initiator", maximum=64),
            owner=OwnerEvidenceV1.from_mapping(_mapping(data["owner"], "owner")),
            operator=(
                None
                if data["operator"] is None
                else OperatorEvidenceV1.from_mapping(
                    _mapping(data["operator"], "operator")
                )
            ),
            body_mode=_text(data["body_mode"], "body_mode", maximum=64),
            estop_state=_text(data["estop_state"], "estop_state", maximum=64),
            locomotion_commissioned=_boolean(
                data["locomotion_commissioned"], "locomotion_commissioned"
            ),
            locomotion_healthy=_boolean(data["locomotion_healthy"], "locomotion_healthy"),
            affordance_state=_text(data["affordance_state"], "affordance_state", maximum=64),
            space_state=_text(data["space_state"], "space_state", maximum=64),
            pending_action_id=_optional_identifier(data["pending_action_id"], "pending_action_id"),
            pending_action_status=_text(
                data["pending_action_status"], "pending_action_status", maximum=64, empty=True
            ),
            last_terminal_receipt_id=(
                None
                if data["last_terminal_receipt_id"] is None
                else _text(
                    data["last_terminal_receipt_id"],
                    "last_terminal_receipt_id",
                    maximum=128,
                )
            ),
            busy_reason=_text(data["busy_reason"], "busy_reason", maximum=256, empty=True),
            consent=ConsentScopesV1.from_mapping(_mapping(data["consent"], "consent")),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "envelope_id": self.envelope_id,
            "manifest_digest": self.manifest_digest,
            "commissioned_actions": list(self.commissioned_actions),
            "action_bindings_digest": self.action_bindings_digest,
            "snapshot_monotonic_ns": self.snapshot_monotonic_ns,
            "expires_monotonic_ns": self.expires_monotonic_ns,
            "initiator": self.initiator,
            "owner": self.owner.as_dict(),
            "operator": None if self.operator is None else self.operator.as_dict(),
            "body_mode": self.body_mode,
            "estop_state": self.estop_state,
            "locomotion_commissioned": self.locomotion_commissioned,
            "locomotion_healthy": self.locomotion_healthy,
            "affordance_state": self.affordance_state,
            "space_state": self.space_state,
            "pending_action_id": self.pending_action_id,
            "pending_action_status": self.pending_action_status,
            "last_terminal_receipt_id": self.last_terminal_receipt_id,
            "busy_reason": self.busy_reason,
            "consent": self.consent.as_dict(),
        }


@dataclass(frozen=True, slots=True)
class ConversationActionProposalV1:
    """One semantic action proposal.  This record never authorizes actuation."""

    proposal_id: str
    turn_id: str
    action_name: str
    manifest_digest: str
    initiator: str
    requested_by_principal_id: str
    created_at_monotonic_ns: int
    expires_monotonic_ns: int
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION or isinstance(self.schema_version, bool):
            raise ValueError(f"schema_version must equal {SCHEMA_VERSION}")
        _identifier(self.proposal_id, "proposal_id")
        _identifier(self.turn_id, "turn_id")
        _identifier(self.action_name, "action_name")
        _digest(self.manifest_digest)
        _enum(self.initiator, ACTION_INITIATORS, "initiator")
        _identifier(
            self.requested_by_principal_id,
            "requested_by_principal_id",
            empty=self.initiator == "system",
        )
        created = _integer(self.created_at_monotonic_ns, "created_at_monotonic_ns")
        expires = _integer(self.expires_monotonic_ns, "expires_monotonic_ns")
        if expires <= created:
            raise ValueError("action proposal expiry must be after creation")

    @property
    def authorizes_actuation(self) -> bool:
        return False

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> ConversationActionProposalV1:
        data = _mapping(value, "ConversationActionProposalV1")
        fields = {
            "schema_version",
            "proposal_id",
            "turn_id",
            "action_name",
            "manifest_digest",
            "initiator",
            "requested_by_principal_id",
            "created_at_monotonic_ns",
            "expires_monotonic_ns",
        }
        _exact(data, fields, "ConversationActionProposalV1")
        return cls(
            schema_version=_integer(data["schema_version"], "schema_version"),
            proposal_id=_text(data["proposal_id"], "proposal_id", maximum=128),
            turn_id=_text(data["turn_id"], "turn_id", maximum=128),
            action_name=_text(data["action_name"], "action_name", maximum=128),
            manifest_digest=_text(data["manifest_digest"], "manifest_digest", maximum=64),
            initiator=_text(data["initiator"], "initiator", maximum=64),
            requested_by_principal_id=_text(
                data["requested_by_principal_id"],
                "requested_by_principal_id",
                maximum=128,
                empty=True,
            ),
            created_at_monotonic_ns=_integer(
                data["created_at_monotonic_ns"], "created_at_monotonic_ns"
            ),
            expires_monotonic_ns=_integer(
                data["expires_monotonic_ns"], "expires_monotonic_ns"
            ),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "proposal_id": self.proposal_id,
            "turn_id": self.turn_id,
            "action_name": self.action_name,
            "manifest_digest": self.manifest_digest,
            "initiator": self.initiator,
            "requested_by_principal_id": self.requested_by_principal_id,
            "created_at_monotonic_ns": self.created_at_monotonic_ns,
            "expires_monotonic_ns": self.expires_monotonic_ns,
        }


@dataclass(frozen=True, slots=True)
class ConversationActionAdmissionV1:
    """Local eligibility verdict; admitted work still requires the executive."""

    proposal_id: str
    turn_id: str
    decision: str
    reason: str
    evaluated_at_monotonic_ns: int
    expires_monotonic_ns: int
    manifest_digest: str
    action_name: str
    consent_scope: str
    mission_id: str | None = None
    action_id: str | None = None
    repeatable: bool = False
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION or isinstance(self.schema_version, bool):
            raise ValueError(f"schema_version must equal {SCHEMA_VERSION}")
        _identifier(self.proposal_id, "proposal_id")
        _identifier(self.turn_id, "turn_id")
        _enum(self.decision, ACTION_ADMISSION_DECISIONS, "action admission decision")
        _text(self.reason, "action admission reason", maximum=256)
        admitted = self.decision == "admit_to_executive"
        evaluated = _integer(self.evaluated_at_monotonic_ns, "evaluated_at_monotonic_ns")
        expires = _integer(self.expires_monotonic_ns, "expires_monotonic_ns")
        if admitted and expires <= evaluated:
            raise ValueError("action admission expiry must be after evaluation")
        _digest(self.manifest_digest)
        _identifier(self.action_name, "action_name")
        _enum(self.consent_scope, ACTION_CONSENT_SCOPES, "consent_scope")
        _boolean(self.repeatable, "repeatable")
        if admitted:
            if self.consent_scope == "not_applicable":
                raise ValueError("admitted proposal requires an applicable consent scope")
            if self.mission_id is None or self.action_id is None:
                raise ValueError("admitted proposal requires locally derived mission/action IDs")
            _derived_identifier(self.mission_id, "mission_id")
            _derived_identifier(self.action_id, "action_id")
            expected_mission = derive_mission_id(
                turn_id=self.turn_id,
                proposal_id=self.proposal_id,
                manifest_digest=self.manifest_digest,
            )
            expected_action = derive_action_id(
                mission_id=expected_mission,
                proposal_id=self.proposal_id,
                action_name=self.action_name,
            )
            if self.mission_id != expected_mission or self.action_id != expected_action:
                raise ValueError("admission mission/action IDs do not match proposal content")
        elif self.mission_id is not None or self.action_id is not None:
            raise ValueError("non-admitted proposal cannot carry mission/action IDs")

    @property
    def authorizes_actuation(self) -> bool:
        """Always false: this verdict may only be submitted to the executive."""

        return False

    @property
    def admitted(self) -> bool:
        return self.decision == "admit_to_executive"

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> ConversationActionAdmissionV1:
        data = _mapping(value, "ConversationActionAdmissionV1")
        fields = {
            "schema_version",
            "proposal_id",
            "turn_id",
            "decision",
            "reason",
            "evaluated_at_monotonic_ns",
            "expires_monotonic_ns",
            "manifest_digest",
            "action_name",
            "consent_scope",
            "mission_id",
            "action_id",
            "repeatable",
        }
        _exact(data, fields, "ConversationActionAdmissionV1")
        return cls(
            schema_version=_integer(data["schema_version"], "schema_version"),
            proposal_id=_text(data["proposal_id"], "proposal_id", maximum=128),
            turn_id=_text(data["turn_id"], "turn_id", maximum=128),
            decision=_text(data["decision"], "decision", maximum=64),
            reason=_text(data["reason"], "reason", maximum=256),
            evaluated_at_monotonic_ns=_integer(
                data["evaluated_at_monotonic_ns"], "evaluated_at_monotonic_ns"
            ),
            expires_monotonic_ns=_integer(
                data["expires_monotonic_ns"], "expires_monotonic_ns"
            ),
            manifest_digest=_text(data["manifest_digest"], "manifest_digest", maximum=64),
            action_name=_text(data["action_name"], "action_name", maximum=128),
            consent_scope=_text(data["consent_scope"], "consent_scope", maximum=64),
            mission_id=_optional_identifier(data["mission_id"], "mission_id"),
            action_id=_optional_identifier(data["action_id"], "action_id"),
            repeatable=_boolean(data["repeatable"], "repeatable"),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "proposal_id": self.proposal_id,
            "turn_id": self.turn_id,
            "decision": self.decision,
            "reason": self.reason,
            "evaluated_at_monotonic_ns": self.evaluated_at_monotonic_ns,
            "expires_monotonic_ns": self.expires_monotonic_ns,
            "manifest_digest": self.manifest_digest,
            "action_name": self.action_name,
            "consent_scope": self.consent_scope,
            "mission_id": self.mission_id,
            "action_id": self.action_id,
            "repeatable": self.repeatable,
        }


@dataclass(frozen=True, slots=True)
class ActionReceiptV1:
    """Structural receipt payload with a content-derived correlation ID.

    The digest-derived ID is not authentication.  Only a trusted receipt
    channel can give this payload authority at the local reducer.
    """

    receipt_id: str
    mission_id: str
    action_id: str
    action_name: str
    manifest_digest: str
    status: str
    sequence: int
    issued_at_monotonic_ns: int
    claimable_until_monotonic_ns: int
    evidence_refs: tuple[str, ...]
    detail_code: str
    source: str = "local_executive"
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION or isinstance(self.schema_version, bool):
            raise ValueError(f"schema_version must equal {SCHEMA_VERSION}")
        _derived_identifier(self.receipt_id, "receipt_id")
        _derived_identifier(self.mission_id, "mission_id")
        _derived_identifier(self.action_id, "action_id")
        _identifier(self.action_name, "action_name")
        _digest(self.manifest_digest)
        _enum(self.status, ACTION_RECEIPT_STATUSES, "receipt status")
        _integer(self.sequence, "receipt sequence", minimum=1)
        issued = _integer(self.issued_at_monotonic_ns, "receipt issue time")
        claimable = _integer(self.claimable_until_monotonic_ns, "receipt claimable time")
        if claimable <= issued:
            raise ValueError("receipt claimable lifetime must be positive")
        if not isinstance(self.evidence_refs, tuple):
            raise TypeError("evidence_refs must be a tuple")
        _strings(self.evidence_refs, "evidence_refs", maximum=32)
        _identifier(self.detail_code, "detail_code")
        if self.source != "local_executive":
            raise ValueError("action receipt source must be local_executive")
        if self.receipt_id != self.derived_receipt_id():
            raise ValueError("receipt_id does not match the receipt content")

    @property
    def terminal(self) -> bool:
        return self.status in TERMINAL_ACTION_STATUSES

    def derived_receipt_id(self) -> str:
        payload = {
            "schema_version": self.schema_version,
            "mission_id": self.mission_id,
            "action_id": self.action_id,
            "action_name": self.action_name,
            "manifest_digest": self.manifest_digest,
            "status": self.status,
            "sequence": self.sequence,
            "issued_at_monotonic_ns": self.issued_at_monotonic_ns,
            "claimable_until_monotonic_ns": self.claimable_until_monotonic_ns,
            "evidence_refs": list(self.evidence_refs),
            "detail_code": self.detail_code,
            "source": self.source,
        }
        return f"receipt-{_canonical_digest('action-receipt-v1', payload)[:24]}"

    @classmethod
    def mint(
        cls,
        *,
        mission_id: str,
        action_id: str,
        action_name: str,
        manifest_digest: str,
        status: str,
        sequence: int,
        issued_at_monotonic_ns: int,
        claimable_until_monotonic_ns: int,
        evidence_refs: tuple[str, ...] = (),
        detail_code: str = "executive_receipt",
    ) -> ActionReceiptV1:
        provisional = object.__new__(cls)
        object.__setattr__(provisional, "receipt_id", "receipt-" + "0" * 24)
        object.__setattr__(provisional, "mission_id", mission_id)
        object.__setattr__(provisional, "action_id", action_id)
        object.__setattr__(provisional, "action_name", action_name)
        object.__setattr__(provisional, "manifest_digest", manifest_digest)
        object.__setattr__(provisional, "status", status)
        object.__setattr__(provisional, "sequence", sequence)
        object.__setattr__(provisional, "issued_at_monotonic_ns", issued_at_monotonic_ns)
        object.__setattr__(
            provisional, "claimable_until_monotonic_ns", claimable_until_monotonic_ns
        )
        object.__setattr__(provisional, "evidence_refs", evidence_refs)
        object.__setattr__(provisional, "detail_code", detail_code)
        object.__setattr__(provisional, "source", "local_executive")
        object.__setattr__(provisional, "schema_version", SCHEMA_VERSION)
        receipt_id = provisional.derived_receipt_id()
        return cls(
            receipt_id=receipt_id,
            mission_id=mission_id,
            action_id=action_id,
            action_name=action_name,
            manifest_digest=manifest_digest,
            status=status,
            sequence=sequence,
            issued_at_monotonic_ns=issued_at_monotonic_ns,
            claimable_until_monotonic_ns=claimable_until_monotonic_ns,
            evidence_refs=evidence_refs,
            detail_code=detail_code,
        )

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> ActionReceiptV1:
        data = _mapping(value, "ActionReceiptV1")
        fields = {
            "schema_version",
            "receipt_id",
            "mission_id",
            "action_id",
            "action_name",
            "manifest_digest",
            "status",
            "sequence",
            "issued_at_monotonic_ns",
            "claimable_until_monotonic_ns",
            "evidence_refs",
            "detail_code",
            "source",
        }
        _exact(data, fields, "ActionReceiptV1")
        return cls(
            schema_version=_integer(data["schema_version"], "schema_version"),
            receipt_id=_text(data["receipt_id"], "receipt_id", maximum=128),
            mission_id=_text(data["mission_id"], "mission_id", maximum=128),
            action_id=_text(data["action_id"], "action_id", maximum=128),
            action_name=_text(data["action_name"], "action_name", maximum=128),
            manifest_digest=_text(data["manifest_digest"], "manifest_digest", maximum=64),
            status=_text(data["status"], "status", maximum=64),
            sequence=_integer(data["sequence"], "sequence", minimum=1),
            issued_at_monotonic_ns=_integer(
                data["issued_at_monotonic_ns"], "issued_at_monotonic_ns"
            ),
            claimable_until_monotonic_ns=_integer(
                data["claimable_until_monotonic_ns"], "claimable_until_monotonic_ns"
            ),
            evidence_refs=_strings(data["evidence_refs"], "evidence_refs", maximum=32),
            detail_code=_text(data["detail_code"], "detail_code", maximum=128),
            source=_text(data["source"], "source", maximum=64),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "receipt_id": self.receipt_id,
            "mission_id": self.mission_id,
            "action_id": self.action_id,
            "action_name": self.action_name,
            "manifest_digest": self.manifest_digest,
            "status": self.status,
            "sequence": self.sequence,
            "issued_at_monotonic_ns": self.issued_at_monotonic_ns,
            "claimable_until_monotonic_ns": self.claimable_until_monotonic_ns,
            "evidence_refs": list(self.evidence_refs),
            "detail_code": self.detail_code,
            "source": self.source,
        }


__all__ = [
    "ACTION_RECEIPT_STATUSES",
    "CONSENT_SCOPES",
    "SCHEMA_VERSION",
    "TERMINAL_ACTION_STATUSES",
    "ActionReceiptV1",
    "ConsentDecisionV1",
    "ConsentScopesV1",
    "ConversationActionAdmissionV1",
    "ConversationActionProposalV1",
    "EmbodimentEnvelopeV1",
    "OperatorEvidenceV1",
    "OwnerEvidenceV1",
    "derive_action_id",
    "derive_mission_id",
]
