"""Receipt-aware multi-turn dialogue read model.

``DialogueStateV1`` is a bounded, serializable read model around the language
model.  It is not the control state machine.  The local reducer in
``parcel_robot.voice.companion_state`` is the only supported way to attach an
authenticated execution receipt, which prevents a model-authored proposal or
a parsed receipt payload from becoming a completed action merely because it
appears in conversation history.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from parcel_robot.contracts.companion_v1 import (
    CONSENT_SCOPES,
    CORRECTION_KINDS,
    CORRECTION_STATES,
    MEMORY_SOURCES,
    PENDING_ACTION_STATES,
    SCHEMA_VERSION,
    ActionReceiptV1,
    ConsentDecisionV1,
    _boolean,
    _derived_identifier,
    _digest,
    _enum,
    _exact,
    _identifier,
    _integer,
    _mapping,
    _optional_identifier,
    _optional_integer,
    _strings,
    _text,
    derive_action_id,
    derive_mission_id,
)


@dataclass(frozen=True, slots=True)
class PendingActionV1:
    mission_id: str
    action_id: str
    proposal_id: str
    turn_id: str
    action_name: str
    manifest_digest: str
    consent_scope: str
    repeatable: bool
    state: str
    admitted_at_monotonic_ns: int
    start_receipt_id: str | None = None
    started_at_monotonic_ns: int | None = None
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION or isinstance(self.schema_version, bool):
            raise ValueError(f"schema_version must equal {SCHEMA_VERSION}")
        _derived_identifier(self.mission_id, "mission_id")
        _derived_identifier(self.action_id, "action_id")
        _identifier(self.proposal_id, "proposal_id")
        _identifier(self.turn_id, "turn_id")
        _identifier(self.action_name, "action_name")
        _digest(self.manifest_digest)
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
            raise ValueError("pending mission/action IDs do not match proposal content")
        _enum(self.consent_scope, CONSENT_SCOPES, "consent_scope")
        _boolean(self.repeatable, "repeatable")
        _enum(self.state, PENDING_ACTION_STATES, "pending action state")
        admitted = _integer(self.admitted_at_monotonic_ns, "admitted_at_monotonic_ns")
        if self.start_receipt_id is not None:
            _derived_identifier(self.start_receipt_id, "start_receipt_id")
        started = _optional_integer(self.started_at_monotonic_ns, "started_at_monotonic_ns")
        if self.state == "started":
            if self.start_receipt_id is None or started is None:
                raise ValueError("started pending action requires its start receipt and time")
            if started < admitted:
                raise ValueError("action cannot start before admission")
        elif self.state == "cancel_requested":
            if bool(self.start_receipt_id) != (started is not None):
                raise ValueError("cancel-requested start receipt and time must be paired")
            if started is not None and started < admitted:
                raise ValueError("action cannot start before admission")
        elif self.start_receipt_id is not None or started is not None:
            raise ValueError("an admitted-only action cannot carry start receipt/time")

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> PendingActionV1:
        data = _mapping(value, "PendingActionV1")
        fields = {
            "schema_version",
            "mission_id",
            "action_id",
            "proposal_id",
            "turn_id",
            "action_name",
            "manifest_digest",
            "consent_scope",
            "repeatable",
            "state",
            "admitted_at_monotonic_ns",
            "start_receipt_id",
            "started_at_monotonic_ns",
        }
        _exact(data, fields, "PendingActionV1")
        return cls(
            schema_version=_integer(data["schema_version"], "schema_version"),
            mission_id=_text(data["mission_id"], "mission_id", maximum=128),
            action_id=_text(data["action_id"], "action_id", maximum=128),
            proposal_id=_text(data["proposal_id"], "proposal_id", maximum=128),
            turn_id=_text(data["turn_id"], "turn_id", maximum=128),
            action_name=_text(data["action_name"], "action_name", maximum=128),
            manifest_digest=_text(data["manifest_digest"], "manifest_digest", maximum=64),
            consent_scope=_text(data["consent_scope"], "consent_scope", maximum=64),
            repeatable=_boolean(data["repeatable"], "repeatable"),
            state=_text(data["state"], "state", maximum=64),
            admitted_at_monotonic_ns=_integer(
                data["admitted_at_monotonic_ns"], "admitted_at_monotonic_ns"
            ),
            start_receipt_id=_optional_identifier(data["start_receipt_id"], "start_receipt_id"),
            started_at_monotonic_ns=_optional_integer(
                data["started_at_monotonic_ns"], "started_at_monotonic_ns"
            ),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "mission_id": self.mission_id,
            "action_id": self.action_id,
            "proposal_id": self.proposal_id,
            "turn_id": self.turn_id,
            "action_name": self.action_name,
            "manifest_digest": self.manifest_digest,
            "consent_scope": self.consent_scope,
            "repeatable": self.repeatable,
            "state": self.state,
            "admitted_at_monotonic_ns": self.admitted_at_monotonic_ns,
            "start_receipt_id": self.start_receipt_id,
            "started_at_monotonic_ns": self.started_at_monotonic_ns,
        }


@dataclass(frozen=True, slots=True)
class CompletedActionV1:
    mission_id: str
    action_id: str
    action_name: str
    manifest_digest: str
    terminal_receipt_id: str
    completed_at_monotonic_ns: int
    repeatable: bool
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION or isinstance(self.schema_version, bool):
            raise ValueError(f"schema_version must equal {SCHEMA_VERSION}")
        _derived_identifier(self.mission_id, "mission_id")
        _derived_identifier(self.action_id, "action_id")
        _identifier(self.action_name, "action_name")
        _digest(self.manifest_digest)
        _derived_identifier(self.terminal_receipt_id, "terminal_receipt_id")
        _integer(self.completed_at_monotonic_ns, "completed_at_monotonic_ns")
        _boolean(self.repeatable, "repeatable")

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> CompletedActionV1:
        data = _mapping(value, "CompletedActionV1")
        fields = {
            "schema_version",
            "mission_id",
            "action_id",
            "action_name",
            "manifest_digest",
            "terminal_receipt_id",
            "completed_at_monotonic_ns",
            "repeatable",
        }
        _exact(data, fields, "CompletedActionV1")
        return cls(
            schema_version=_integer(data["schema_version"], "schema_version"),
            mission_id=_text(data["mission_id"], "mission_id", maximum=128),
            action_id=_text(data["action_id"], "action_id", maximum=128),
            action_name=_text(data["action_name"], "action_name", maximum=128),
            manifest_digest=_text(data["manifest_digest"], "manifest_digest", maximum=64),
            terminal_receipt_id=_text(
                data["terminal_receipt_id"], "terminal_receipt_id", maximum=128
            ),
            completed_at_monotonic_ns=_integer(
                data["completed_at_monotonic_ns"], "completed_at_monotonic_ns"
            ),
            repeatable=_boolean(data["repeatable"], "repeatable"),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "mission_id": self.mission_id,
            "action_id": self.action_id,
            "action_name": self.action_name,
            "manifest_digest": self.manifest_digest,
            "terminal_receipt_id": self.terminal_receipt_id,
            "completed_at_monotonic_ns": self.completed_at_monotonic_ns,
            "repeatable": self.repeatable,
        }


@dataclass(frozen=True, slots=True)
class ClarificationV1:
    clarification_id: str
    source_turn_id: str
    unresolved_field: str
    candidate_referent_ids: tuple[str, ...]
    asked_at_monotonic_ns: int
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION or isinstance(self.schema_version, bool):
            raise ValueError(f"schema_version must equal {SCHEMA_VERSION}")
        _identifier(self.clarification_id, "clarification_id")
        _identifier(self.source_turn_id, "source_turn_id")
        _identifier(self.unresolved_field, "unresolved_field")
        _strings(self.candidate_referent_ids, "candidate_referent_ids", maximum=16)
        _integer(self.asked_at_monotonic_ns, "asked_at_monotonic_ns")

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> ClarificationV1:
        data = _mapping(value, "ClarificationV1")
        fields = {
            "schema_version",
            "clarification_id",
            "source_turn_id",
            "unresolved_field",
            "candidate_referent_ids",
            "asked_at_monotonic_ns",
        }
        _exact(data, fields, "ClarificationV1")
        return cls(
            schema_version=_integer(data["schema_version"], "schema_version"),
            clarification_id=_text(
                data["clarification_id"], "clarification_id", maximum=128
            ),
            source_turn_id=_text(data["source_turn_id"], "source_turn_id", maximum=128),
            unresolved_field=_text(
                data["unresolved_field"], "unresolved_field", maximum=128
            ),
            candidate_referent_ids=_strings(
                data["candidate_referent_ids"], "candidate_referent_ids", maximum=16
            ),
            asked_at_monotonic_ns=_integer(
                data["asked_at_monotonic_ns"], "asked_at_monotonic_ns"
            ),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "clarification_id": self.clarification_id,
            "source_turn_id": self.source_turn_id,
            "unresolved_field": self.unresolved_field,
            "candidate_referent_ids": list(self.candidate_referent_ids),
            "asked_at_monotonic_ns": self.asked_at_monotonic_ns,
        }


@dataclass(frozen=True, slots=True)
class CorrectionV1:
    correction_id: str
    source_turn_id: str
    kind: str
    state: str
    target_action_id: str | None
    replacement_referent_id: str | None
    recorded_at_monotonic_ns: int
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION or isinstance(self.schema_version, bool):
            raise ValueError(f"schema_version must equal {SCHEMA_VERSION}")
        _identifier(self.correction_id, "correction_id")
        _identifier(self.source_turn_id, "source_turn_id")
        _enum(self.kind, CORRECTION_KINDS, "correction kind")
        _enum(self.state, CORRECTION_STATES, "correction state")
        if self.target_action_id is not None:
            _derived_identifier(self.target_action_id, "target_action_id")
        _optional_identifier(self.replacement_referent_id, "replacement_referent_id")
        _integer(self.recorded_at_monotonic_ns, "recorded_at_monotonic_ns")

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> CorrectionV1:
        data = _mapping(value, "CorrectionV1")
        fields = {
            "schema_version",
            "correction_id",
            "source_turn_id",
            "kind",
            "state",
            "target_action_id",
            "replacement_referent_id",
            "recorded_at_monotonic_ns",
        }
        _exact(data, fields, "CorrectionV1")
        return cls(
            schema_version=_integer(data["schema_version"], "schema_version"),
            correction_id=_text(data["correction_id"], "correction_id", maximum=128),
            source_turn_id=_text(data["source_turn_id"], "source_turn_id", maximum=128),
            kind=_text(data["kind"], "kind", maximum=64),
            state=_text(data["state"], "state", maximum=64),
            target_action_id=_optional_identifier(data["target_action_id"], "target_action_id"),
            replacement_referent_id=_optional_identifier(
                data["replacement_referent_id"], "replacement_referent_id"
            ),
            recorded_at_monotonic_ns=_integer(
                data["recorded_at_monotonic_ns"], "recorded_at_monotonic_ns"
            ),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "correction_id": self.correction_id,
            "source_turn_id": self.source_turn_id,
            "kind": self.kind,
            "state": self.state,
            "target_action_id": self.target_action_id,
            "replacement_referent_id": self.replacement_referent_id,
            "recorded_at_monotonic_ns": self.recorded_at_monotonic_ns,
        }


@dataclass(frozen=True, slots=True)
class DialogueMemoryRecordV1:
    """A bounded provenance view; it does not replace the owner-memory store."""

    record_id: str
    key: str
    value: str
    source: str
    source_session_id: str
    source_turn_id: str
    observed_at_monotonic_ns: int
    valid_from_monotonic_ns: int
    valid_until_monotonic_ns: int | None
    consent: ConsentDecisionV1
    revoked_at_monotonic_ns: int | None
    supersedes_record_id: str | None
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION or isinstance(self.schema_version, bool):
            raise ValueError(f"schema_version must equal {SCHEMA_VERSION}")
        _identifier(self.record_id, "memory record_id")
        _identifier(self.key, "memory key")
        _text(self.value, "memory value", maximum=1000)
        _enum(self.source, MEMORY_SOURCES, "memory source")
        _identifier(self.source_session_id, "memory source_session_id")
        _identifier(self.source_turn_id, "memory source_turn_id")
        observed = _integer(self.observed_at_monotonic_ns, "memory observed time")
        valid_from = _integer(self.valid_from_monotonic_ns, "memory valid_from")
        valid_until = _optional_integer(self.valid_until_monotonic_ns, "memory valid_until")
        if valid_from < observed:
            raise ValueError("memory validity cannot begin before observation")
        if valid_until is not None and valid_until <= valid_from:
            raise ValueError("memory valid_until must be after valid_from")
        if not isinstance(self.consent, ConsentDecisionV1):
            raise TypeError("memory consent must be ConsentDecisionV1")
        revoked = _optional_integer(self.revoked_at_monotonic_ns, "memory revoked_at")
        if self.consent.status == "revoked" and revoked is None:
            raise ValueError("revoked memory consent requires revoked_at_monotonic_ns")
        if revoked is not None and revoked < observed:
            raise ValueError("memory cannot be revoked before observation")
        _optional_identifier(self.supersedes_record_id, "supersedes_record_id")
        if self.supersedes_record_id == self.record_id:
            raise ValueError("memory record cannot supersede itself")

    def answerable_at(self, now_monotonic_ns: int, *, principal_id: str) -> bool:
        now = _integer(now_monotonic_ns, "now_monotonic_ns")
        return (
            self.source == "owner"
            and self.valid_from_monotonic_ns <= now
            and (self.valid_until_monotonic_ns is None or now < self.valid_until_monotonic_ns)
            and (self.revoked_at_monotonic_ns is None or now < self.revoked_at_monotonic_ns)
            and self.consent.granted_at(now, principal_id=principal_id)
        )

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> DialogueMemoryRecordV1:
        data = _mapping(value, "DialogueMemoryRecordV1")
        fields = {
            "schema_version",
            "record_id",
            "key",
            "value",
            "source",
            "source_session_id",
            "source_turn_id",
            "observed_at_monotonic_ns",
            "valid_from_monotonic_ns",
            "valid_until_monotonic_ns",
            "consent",
            "revoked_at_monotonic_ns",
            "supersedes_record_id",
        }
        _exact(data, fields, "DialogueMemoryRecordV1")
        return cls(
            schema_version=_integer(data["schema_version"], "schema_version"),
            record_id=_text(data["record_id"], "record_id", maximum=128),
            key=_text(data["key"], "key", maximum=128),
            value=_text(data["value"], "value", maximum=1000),
            source=_text(data["source"], "source", maximum=64),
            source_session_id=_text(
                data["source_session_id"], "source_session_id", maximum=128
            ),
            source_turn_id=_text(data["source_turn_id"], "source_turn_id", maximum=128),
            observed_at_monotonic_ns=_integer(
                data["observed_at_monotonic_ns"], "observed_at_monotonic_ns"
            ),
            valid_from_monotonic_ns=_integer(
                data["valid_from_monotonic_ns"], "valid_from_monotonic_ns"
            ),
            valid_until_monotonic_ns=_optional_integer(
                data["valid_until_monotonic_ns"], "valid_until_monotonic_ns"
            ),
            consent=ConsentDecisionV1.from_mapping(_mapping(data["consent"], "consent")),
            revoked_at_monotonic_ns=_optional_integer(
                data["revoked_at_monotonic_ns"], "revoked_at_monotonic_ns"
            ),
            supersedes_record_id=_optional_identifier(
                data["supersedes_record_id"], "supersedes_record_id"
            ),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "record_id": self.record_id,
            "key": self.key,
            "value": self.value,
            "source": self.source,
            "source_session_id": self.source_session_id,
            "source_turn_id": self.source_turn_id,
            "observed_at_monotonic_ns": self.observed_at_monotonic_ns,
            "valid_from_monotonic_ns": self.valid_from_monotonic_ns,
            "valid_until_monotonic_ns": self.valid_until_monotonic_ns,
            "consent": self.consent.as_dict(),
            "revoked_at_monotonic_ns": self.revoked_at_monotonic_ns,
            "supersedes_record_id": self.supersedes_record_id,
        }


@dataclass(frozen=True, slots=True)
class RetrievalStateV1:
    query_id: str
    result_ids: tuple[str, ...]
    no_match: bool
    retrieved_at_monotonic_ns: int
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION or isinstance(self.schema_version, bool):
            raise ValueError(f"schema_version must equal {SCHEMA_VERSION}")
        _identifier(self.query_id, "query_id")
        results = _strings(self.result_ids, "result_ids", maximum=32)
        _boolean(self.no_match, "no_match")
        if self.no_match == bool(results):
            raise ValueError("no_match must be true exactly when result_ids is empty")
        _integer(self.retrieved_at_monotonic_ns, "retrieved_at_monotonic_ns")

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> RetrievalStateV1:
        data = _mapping(value, "RetrievalStateV1")
        fields = {
            "schema_version",
            "query_id",
            "result_ids",
            "no_match",
            "retrieved_at_monotonic_ns",
        }
        _exact(data, fields, "RetrievalStateV1")
        return cls(
            schema_version=_integer(data["schema_version"], "schema_version"),
            query_id=_text(data["query_id"], "query_id", maximum=128),
            result_ids=_strings(data["result_ids"], "result_ids", maximum=32),
            no_match=_boolean(data["no_match"], "no_match"),
            retrieved_at_monotonic_ns=_integer(
                data["retrieved_at_monotonic_ns"], "retrieved_at_monotonic_ns"
            ),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "query_id": self.query_id,
            "result_ids": list(self.result_ids),
            "no_match": self.no_match,
            "retrieved_at_monotonic_ns": self.retrieved_at_monotonic_ns,
        }


@dataclass(frozen=True, slots=True)
class ConsumedActionV1:
    """Replay token retained independently until its admission expires."""

    mission_id: str
    action_id: str
    expires_monotonic_ns: int
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION or isinstance(self.schema_version, bool):
            raise ValueError(f"schema_version must equal {SCHEMA_VERSION}")
        _derived_identifier(self.mission_id, "consumed mission_id")
        _derived_identifier(self.action_id, "consumed action_id")
        _integer(self.expires_monotonic_ns, "consumed expiry")

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> ConsumedActionV1:
        data = _mapping(value, "ConsumedActionV1")
        fields = {"schema_version", "mission_id", "action_id", "expires_monotonic_ns"}
        _exact(data, fields, "ConsumedActionV1")
        return cls(
            schema_version=_integer(data["schema_version"], "schema_version"),
            mission_id=_text(data["mission_id"], "mission_id", maximum=128),
            action_id=_text(data["action_id"], "action_id", maximum=128),
            expires_monotonic_ns=_integer(
                data["expires_monotonic_ns"], "expires_monotonic_ns"
            ),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "mission_id": self.mission_id,
            "action_id": self.action_id,
            "expires_monotonic_ns": self.expires_monotonic_ns,
        }


@dataclass(frozen=True, slots=True)
class DialogueStateV1:
    """Bounded multi-turn state with locally sourced execution evidence."""

    session_id: str
    revision: int
    active_turn_id: str
    updated_at_monotonic_ns: int
    current_topic: str
    current_referent_id: str | None
    pending_clarification: ClarificationV1 | None
    correction: CorrectionV1 | None
    pending_action: PendingActionV1 | None
    last_completed_action: CompletedActionV1 | None
    consumed_actions: tuple[ConsumedActionV1, ...]
    action_receipts: tuple[ActionReceiptV1, ...]
    memory_records: tuple[DialogueMemoryRecordV1, ...]
    retrieval: RetrievalStateV1 | None
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION or isinstance(self.schema_version, bool):
            raise ValueError(f"schema_version must equal {SCHEMA_VERSION}")
        _identifier(self.session_id, "session_id")
        _integer(self.revision, "dialogue revision")
        _identifier(self.active_turn_id, "active_turn_id", empty=True)
        _integer(self.updated_at_monotonic_ns, "updated_at_monotonic_ns")
        _text(self.current_topic, "current_topic", maximum=256, empty=True)
        _optional_identifier(self.current_referent_id, "current_referent_id")
        if self.pending_clarification is not None and not isinstance(
            self.pending_clarification, ClarificationV1
        ):
            raise TypeError("pending_clarification must be ClarificationV1 or None")
        if self.correction is not None and not isinstance(self.correction, CorrectionV1):
            raise TypeError("correction must be CorrectionV1 or None")
        if self.pending_action is not None and not isinstance(self.pending_action, PendingActionV1):
            raise TypeError("pending_action must be PendingActionV1 or None")
        if self.last_completed_action is not None and not isinstance(
            self.last_completed_action, CompletedActionV1
        ):
            raise TypeError("last_completed_action must be CompletedActionV1 or None")
        if not isinstance(self.consumed_actions, tuple) or any(
            not isinstance(item, ConsumedActionV1) for item in self.consumed_actions
        ):
            raise TypeError("consumed_actions must be a tuple of ConsumedActionV1")
        if len(self.consumed_actions) > 64:
            raise ValueError("consumed_actions exceeds 64 items")
        consumed_action_ids = [item.action_id for item in self.consumed_actions]
        consumed_mission_ids = [item.mission_id for item in self.consumed_actions]
        if len(set(consumed_action_ids)) != len(consumed_action_ids):
            raise ValueError("consumed action IDs must be unique")
        if len(set(consumed_mission_ids)) != len(consumed_mission_ids):
            raise ValueError("consumed mission IDs must be unique")
        consumed_pairs = {
            (item.mission_id, item.action_id) for item in self.consumed_actions
        }
        if self.pending_action is not None and (
            self.pending_action.mission_id,
            self.pending_action.action_id,
        ) not in consumed_pairs:
            raise ValueError("pending action must have a retained consumed-action token")
        if self.last_completed_action is not None and (
            self.last_completed_action.mission_id,
            self.last_completed_action.action_id,
        ) not in consumed_pairs:
            raise ValueError("completed action must have a retained consumed-action token")
        if not isinstance(self.action_receipts, tuple) or any(
            not isinstance(item, ActionReceiptV1) for item in self.action_receipts
        ):
            raise TypeError("action_receipts must be a tuple of ActionReceiptV1")
        if len(self.action_receipts) > 32:
            raise ValueError("action_receipts exceeds 32 items")
        receipt_ids = [item.receipt_id for item in self.action_receipts]
        if len(set(receipt_ids)) != len(receipt_ids):
            raise ValueError("action_receipt IDs must be unique")
        receipt_by_id = {item.receipt_id: item for item in self.action_receipts}
        if self.pending_action is not None and self.pending_action.start_receipt_id is not None:
            receipt = receipt_by_id.get(self.pending_action.start_receipt_id)
            if receipt is None or receipt.status != "started":
                raise ValueError("pending start receipt must reference a retained started receipt")
            if not _same_action(self.pending_action, receipt):
                raise ValueError("pending start receipt does not match the pending action")
        if self.last_completed_action is not None:
            receipt = receipt_by_id.get(self.last_completed_action.terminal_receipt_id)
            if receipt is None or receipt.status != "succeeded":
                raise ValueError("last completed action must reference a retained success receipt")
            if not _same_action(self.last_completed_action, receipt):
                raise ValueError("last completed receipt does not match the completed action")
        if not isinstance(self.memory_records, tuple) or any(
            not isinstance(item, DialogueMemoryRecordV1) for item in self.memory_records
        ):
            raise TypeError("memory_records must be a tuple of DialogueMemoryRecordV1")
        if len(self.memory_records) > 64:
            raise ValueError("memory_records exceeds 64 items")
        memory_ids = [item.record_id for item in self.memory_records]
        if len(set(memory_ids)) != len(memory_ids):
            raise ValueError("memory record IDs must be unique")
        if self.retrieval is not None:
            if not isinstance(self.retrieval, RetrievalStateV1):
                raise TypeError("retrieval must be RetrievalStateV1 or None")
            if not set(self.retrieval.result_ids).issubset(memory_ids):
                raise ValueError("retrieval result IDs must reference retained memory records")

    @classmethod
    def empty(cls, *, session_id: str, now_monotonic_ns: int) -> DialogueStateV1:
        return cls(
            session_id=session_id,
            revision=0,
            active_turn_id="",
            updated_at_monotonic_ns=now_monotonic_ns,
            current_topic="",
            current_referent_id=None,
            pending_clarification=None,
            correction=None,
            pending_action=None,
            last_completed_action=None,
            consumed_actions=(),
            action_receipts=(),
            memory_records=(),
            retrieval=None,
        )

    def receipt(self, receipt_id: str) -> ActionReceiptV1 | None:
        target = _derived_identifier(receipt_id, "receipt_id")
        return next((item for item in self.action_receipts if item.receipt_id == target), None)

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> DialogueStateV1:
        data = _mapping(value, "DialogueStateV1")
        fields = {
            "schema_version",
            "session_id",
            "revision",
            "active_turn_id",
            "updated_at_monotonic_ns",
            "current_topic",
            "current_referent_id",
            "pending_clarification",
            "correction",
            "pending_action",
            "last_completed_action",
            "consumed_actions",
            "action_receipts",
            "memory_records",
            "retrieval",
        }
        _exact(data, fields, "DialogueStateV1")
        receipts = data["action_receipts"]
        consumed = data["consumed_actions"]
        memories = data["memory_records"]
        if isinstance(receipts, (str, bytes)) or not isinstance(receipts, Sequence):
            raise TypeError("action_receipts must be a sequence")
        if isinstance(consumed, (str, bytes)) or not isinstance(consumed, Sequence):
            raise TypeError("consumed_actions must be a sequence")
        if isinstance(memories, (str, bytes)) or not isinstance(memories, Sequence):
            raise TypeError("memory_records must be a sequence")
        return cls(
            schema_version=_integer(data["schema_version"], "schema_version"),
            session_id=_text(data["session_id"], "session_id", maximum=128),
            revision=_integer(data["revision"], "revision"),
            active_turn_id=_text(data["active_turn_id"], "active_turn_id", maximum=128, empty=True),
            updated_at_monotonic_ns=_integer(
                data["updated_at_monotonic_ns"], "updated_at_monotonic_ns"
            ),
            current_topic=_text(data["current_topic"], "current_topic", maximum=256, empty=True),
            current_referent_id=_optional_identifier(
                data["current_referent_id"], "current_referent_id"
            ),
            pending_clarification=(
                None
                if data["pending_clarification"] is None
                else ClarificationV1.from_mapping(
                    _mapping(data["pending_clarification"], "pending_clarification")
                )
            ),
            correction=(
                None
                if data["correction"] is None
                else CorrectionV1.from_mapping(_mapping(data["correction"], "correction"))
            ),
            pending_action=(
                None
                if data["pending_action"] is None
                else PendingActionV1.from_mapping(
                    _mapping(data["pending_action"], "pending_action")
                )
            ),
            last_completed_action=(
                None
                if data["last_completed_action"] is None
                else CompletedActionV1.from_mapping(
                    _mapping(data["last_completed_action"], "last_completed_action")
                )
            ),
            consumed_actions=tuple(
                ConsumedActionV1.from_mapping(_mapping(item, "consumed action"))
                for item in consumed
            ),
            action_receipts=tuple(
                ActionReceiptV1.from_mapping(_mapping(item, "action receipt"))
                for item in receipts
            ),
            memory_records=tuple(
                DialogueMemoryRecordV1.from_mapping(_mapping(item, "memory record"))
                for item in memories
            ),
            retrieval=(
                None
                if data["retrieval"] is None
                else RetrievalStateV1.from_mapping(_mapping(data["retrieval"], "retrieval"))
            ),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "session_id": self.session_id,
            "revision": self.revision,
            "active_turn_id": self.active_turn_id,
            "updated_at_monotonic_ns": self.updated_at_monotonic_ns,
            "current_topic": self.current_topic,
            "current_referent_id": self.current_referent_id,
            "pending_clarification": (
                None if self.pending_clarification is None else self.pending_clarification.as_dict()
            ),
            "correction": None if self.correction is None else self.correction.as_dict(),
            "pending_action": (
                None if self.pending_action is None else self.pending_action.as_dict()
            ),
            "last_completed_action": (
                None if self.last_completed_action is None else self.last_completed_action.as_dict()
            ),
            "consumed_actions": [item.as_dict() for item in self.consumed_actions],
            "action_receipts": [item.as_dict() for item in self.action_receipts],
            "memory_records": [item.as_dict() for item in self.memory_records],
            "retrieval": None if self.retrieval is None else self.retrieval.as_dict(),
        }


def _same_action(action: PendingActionV1 | CompletedActionV1, receipt: ActionReceiptV1) -> bool:
    return (
        action.mission_id == receipt.mission_id
        and action.action_id == receipt.action_id
        and action.action_name == receipt.action_name
        and action.manifest_digest == receipt.manifest_digest
    )


__all__ = [
    "ClarificationV1",
    "CompletedActionV1",
    "ConsumedActionV1",
    "CorrectionV1",
    "DialogueMemoryRecordV1",
    "DialogueStateV1",
    "PendingActionV1",
    "RetrievalStateV1",
]
