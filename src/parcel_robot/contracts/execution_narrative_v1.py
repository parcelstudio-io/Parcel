"""Authenticated, read-only facts from the task executive to Model B.

The contract deliberately contains no actuator, publisher, plan-admission, or
hosted-model handle.  An event describes one transition which already happened
inside :class:`parcel_robot.brain.executive.TaskExecutive`; it cannot cause a
transition.  Identifiers are derived locally so a narrator cannot choose a
different task lineage.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from parcel_robot.brain.contracts import VerifiedFact

SCHEMA_VERSION = 1
EXECUTION_NARRATIVE_STATUSES = frozenset(
    {
        "accepted",
        "started",
        "progress",
        "blocked",
        "replanned",
        "suspended",
        "resumed",
        "succeeded",
        "failed",
        "cancelled",
    }
)

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_DERIVED_RE = re.compile(r"^(?:event|mission|action)-[0-9a-f]{24}$")


def _identifier(value: object, name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    if value != value.strip() or _IDENTIFIER_RE.fullmatch(value) is None:
        raise ValueError(f"{name} must be a bounded identifier")
    return value


def _optional_identifier(value: object, name: str) -> str | None:
    if value is None:
        return None
    return _identifier(value, name)


def _derived(value: object, prefix: str) -> str:
    result = _identifier(value, prefix)
    if _DERIVED_RE.fullmatch(result) is None or not result.startswith(f"{prefix}-"):
        raise ValueError(f"{prefix} must be a content-derived identifier")
    return result


def _integer(value: object, name: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    if not minimum <= value <= (1 << 64) - 1:
        raise ValueError(f"{name} must be between {minimum} and 2^64-1")
    return value


def _text(value: object, name: str, *, maximum: int) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    if not value or value != value.strip() or len(value) > maximum:
        raise ValueError(f"{name} must be non-empty bounded text")
    return value


def _digest(value: object, name: str) -> str:
    if not isinstance(value, str) or _DIGEST_RE.fullmatch(value) is None:
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return value


def _canonical_bytes(value: Mapping[str, object]) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")


def _content_id(namespace: str, prefix: str, value: Mapping[str, object]) -> str:
    payload = {"namespace": namespace, **dict(value)}
    return f"{prefix}-{hashlib.sha256(_canonical_bytes(payload)).hexdigest()[:24]}"


def derive_execution_mission_id(*, task_id: str, plan_sha256: str) -> str:
    """Derive one stable mission identity for one task-plan pair."""

    return _content_id(
        "execution-narrative-mission-v1",
        "mission",
        {
            "task_id": _identifier(task_id, "task_id"),
            "plan_sha256": _digest(plan_sha256, "plan_sha256"),
        },
    )


def derive_execution_action_id(
    *,
    mission_id: str,
    plan_revision: int,
    step_id: str,
    attempt: int,
    action_name: str,
) -> str:
    """Derive the exact semantic action/attempt identity."""

    return _content_id(
        "execution-narrative-action-v1",
        "action",
        {
            "mission_id": _derived(mission_id, "mission"),
            "plan_revision": _integer(plan_revision, "plan_revision", minimum=1),
            "step_id": _identifier(step_id, "step_id"),
            "attempt": _integer(attempt, "attempt", minimum=1),
            "action_name": _identifier(action_name, "action_name"),
        },
    )


def derive_execution_event_id(payload: Mapping[str, object]) -> str:
    """Derive an event ID from every serialized field except ``event_id``."""

    if "event_id" in payload:
        raise ValueError("event identity payload cannot contain event_id")
    return _content_id("execution-narrative-event-v1", "event", payload)


@dataclass(frozen=True, slots=True)
class ExecutionNarrativeEventV1:
    """One immutable, non-actuating executive transition fact."""

    event_id: str
    event_sequence: int
    task_id: str
    plan_revision: int
    step_id: str
    attempt: int
    mission_id: str
    action_id: str
    action_name: str
    plan_sha256: str
    status: str
    source_epoch: int
    speech_generation: int
    issued_at_monotonic_ns: int
    claimable_until_monotonic_ns: int
    verified_facts: tuple[VerifiedFact, ...]
    evidence_refs: tuple[str, ...]
    detail_code: str
    resume_parent_task_id: str | None
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION or isinstance(self.schema_version, bool):
            raise ValueError(f"schema_version must equal {SCHEMA_VERSION}")
        _derived(self.event_id, "event")
        _integer(self.event_sequence, "event_sequence", minimum=1)
        _identifier(self.task_id, "task_id")
        _integer(self.plan_revision, "plan_revision", minimum=1)
        _identifier(self.step_id, "step_id")
        _integer(self.attempt, "attempt", minimum=1)
        _derived(self.mission_id, "mission")
        _derived(self.action_id, "action")
        _identifier(self.action_name, "action_name")
        _digest(self.plan_sha256, "plan_sha256")
        if self.status not in EXECUTION_NARRATIVE_STATUSES:
            raise ValueError("status is not an execution narrative status")
        _integer(self.source_epoch, "source_epoch", minimum=1)
        _integer(self.speech_generation, "speech_generation")
        issued = _integer(self.issued_at_monotonic_ns, "issued_at_monotonic_ns")
        claimable = _integer(
            self.claimable_until_monotonic_ns,
            "claimable_until_monotonic_ns",
            minimum=1,
        )
        if claimable <= issued:
            raise ValueError("claimable lifetime must be positive")
        if not isinstance(self.verified_facts, tuple) or len(self.verified_facts) > 16:
            raise TypeError("verified_facts must be a bounded tuple")
        if any(not isinstance(item, VerifiedFact) for item in self.verified_facts):
            raise TypeError("verified_facts must contain VerifiedFact values")
        if self.status == "succeeded" and not self.verified_facts:
            raise ValueError("succeeded event requires an executive-verified fact")
        if not isinstance(self.evidence_refs, tuple) or len(self.evidence_refs) > 16:
            raise TypeError("evidence_refs must be a bounded tuple")
        for reference in self.evidence_refs:
            _identifier(reference, "evidence reference")
        if len(set(self.evidence_refs)) != len(self.evidence_refs):
            raise ValueError("evidence_refs cannot contain duplicates")
        _text(self.detail_code, "detail_code", maximum=120)
        parent = _optional_identifier(self.resume_parent_task_id, "resume_parent_task_id")
        if parent == self.task_id:
            raise ValueError("a task cannot be its own resume parent")

        expected_mission = derive_execution_mission_id(
            task_id=self.task_id,
            plan_sha256=self.plan_sha256,
        )
        if self.mission_id != expected_mission:
            raise ValueError("mission_id does not match task and plan")
        expected_action = derive_execution_action_id(
            mission_id=self.mission_id,
            plan_revision=self.plan_revision,
            step_id=self.step_id,
            attempt=self.attempt,
            action_name=self.action_name,
        )
        if self.action_id != expected_action:
            raise ValueError("action_id does not match event lineage")
        if self.event_id != derive_execution_event_id(self.identity_payload()):
            raise ValueError("event_id does not match event content")

    def identity_payload(self) -> dict[str, object]:
        """Return every serialized field covered by ``event_id``."""

        value = self.as_dict()
        del value["event_id"]
        return value

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "event_id": self.event_id,
            "event_sequence": self.event_sequence,
            "task_id": self.task_id,
            "plan_revision": self.plan_revision,
            "step_id": self.step_id,
            "attempt": self.attempt,
            "mission_id": self.mission_id,
            "action_id": self.action_id,
            "action_name": self.action_name,
            "plan_sha256": self.plan_sha256,
            "status": self.status,
            "source_epoch": self.source_epoch,
            "speech_generation": self.speech_generation,
            "issued_at_monotonic_ns": self.issued_at_monotonic_ns,
            "claimable_until_monotonic_ns": self.claimable_until_monotonic_ns,
            "verified_facts": [item.as_dict() for item in self.verified_facts],
            "evidence_refs": list(self.evidence_refs),
            "detail_code": self.detail_code,
            "resume_parent_task_id": self.resume_parent_task_id,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> ExecutionNarrativeEventV1:
        if not isinstance(value, Mapping):
            raise TypeError("execution narrative event must be a mapping")
        fields = {
            "schema_version",
            "event_id",
            "event_sequence",
            "task_id",
            "plan_revision",
            "step_id",
            "attempt",
            "mission_id",
            "action_id",
            "action_name",
            "plan_sha256",
            "status",
            "source_epoch",
            "speech_generation",
            "issued_at_monotonic_ns",
            "claimable_until_monotonic_ns",
            "verified_facts",
            "evidence_refs",
            "detail_code",
            "resume_parent_task_id",
        }
        if set(value) != fields:
            raise ValueError("execution narrative event fields must be exact")
        facts_value = value["verified_facts"]
        refs_value = value["evidence_refs"]
        if isinstance(facts_value, (str, bytes)) or not isinstance(facts_value, Sequence):
            raise TypeError("verified_facts must be a sequence")
        if isinstance(refs_value, (str, bytes)) or not isinstance(refs_value, Sequence):
            raise TypeError("evidence_refs must be a sequence")
        if any(not isinstance(item, str) for item in refs_value):
            raise TypeError("evidence_refs must contain strings")
        parent = value["resume_parent_task_id"]
        if parent is not None and not isinstance(parent, str):
            raise TypeError("resume_parent_task_id must be a string or null")
        return cls(
            schema_version=_integer(value["schema_version"], "schema_version"),
            event_id=value["event_id"],  # type: ignore[arg-type]
            event_sequence=_integer(value["event_sequence"], "event_sequence", minimum=1),
            task_id=value["task_id"],  # type: ignore[arg-type]
            plan_revision=_integer(value["plan_revision"], "plan_revision", minimum=1),
            step_id=value["step_id"],  # type: ignore[arg-type]
            attempt=_integer(value["attempt"], "attempt", minimum=1),
            mission_id=value["mission_id"],  # type: ignore[arg-type]
            action_id=value["action_id"],  # type: ignore[arg-type]
            action_name=value["action_name"],  # type: ignore[arg-type]
            plan_sha256=value["plan_sha256"],  # type: ignore[arg-type]
            status=value["status"],  # type: ignore[arg-type]
            source_epoch=_integer(value["source_epoch"], "source_epoch", minimum=1),
            speech_generation=_integer(value["speech_generation"], "speech_generation"),
            issued_at_monotonic_ns=_integer(
                value["issued_at_monotonic_ns"], "issued_at_monotonic_ns"
            ),
            claimable_until_monotonic_ns=_integer(
                value["claimable_until_monotonic_ns"],
                "claimable_until_monotonic_ns",
                minimum=1,
            ),
            verified_facts=tuple(
                VerifiedFact.from_mapping(item)  # type: ignore[arg-type]
                for item in facts_value
            ),
            evidence_refs=tuple(refs_value),  # type: ignore[arg-type]
            detail_code=value["detail_code"],  # type: ignore[arg-type]
            resume_parent_task_id=parent,
        )


def build_execution_narrative_event(
    *,
    event_sequence: int,
    task_id: str,
    plan_revision: int,
    step_id: str,
    attempt: int,
    action_name: str,
    plan_sha256: str,
    status: str,
    source_epoch: int,
    speech_generation: int,
    issued_at_monotonic_ns: int,
    claimable_until_monotonic_ns: int,
    verified_facts: tuple[VerifiedFact, ...] = (),
    evidence_refs: tuple[str, ...] = (),
    detail_code: str,
    resume_parent_task_id: str | None = None,
) -> ExecutionNarrativeEventV1:
    """Build an event while deriving all three local identities."""

    mission_id = derive_execution_mission_id(
        task_id=task_id,
        plan_sha256=plan_sha256,
    )
    action_id = derive_execution_action_id(
        mission_id=mission_id,
        plan_revision=plan_revision,
        step_id=step_id,
        attempt=attempt,
        action_name=action_name,
    )
    values: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "event_sequence": event_sequence,
        "task_id": task_id,
        "plan_revision": plan_revision,
        "step_id": step_id,
        "attempt": attempt,
        "mission_id": mission_id,
        "action_id": action_id,
        "action_name": action_name,
        "plan_sha256": plan_sha256,
        "status": status,
        "source_epoch": source_epoch,
        "speech_generation": speech_generation,
        "issued_at_monotonic_ns": issued_at_monotonic_ns,
        "claimable_until_monotonic_ns": claimable_until_monotonic_ns,
        "verified_facts": [item.as_dict() for item in verified_facts],
        "evidence_refs": list(evidence_refs),
        "detail_code": detail_code,
        "resume_parent_task_id": resume_parent_task_id,
    }
    return ExecutionNarrativeEventV1(
        event_id=derive_execution_event_id(values),
        event_sequence=event_sequence,
        task_id=task_id,
        plan_revision=plan_revision,
        step_id=step_id,
        attempt=attempt,
        mission_id=mission_id,
        action_id=action_id,
        action_name=action_name,
        plan_sha256=plan_sha256,
        status=status,
        source_epoch=source_epoch,
        speech_generation=speech_generation,
        issued_at_monotonic_ns=issued_at_monotonic_ns,
        claimable_until_monotonic_ns=claimable_until_monotonic_ns,
        verified_facts=verified_facts,
        evidence_refs=evidence_refs,
        detail_code=detail_code,
        resume_parent_task_id=resume_parent_task_id,
    )


__all__ = [
    "EXECUTION_NARRATIVE_STATUSES",
    "ExecutionNarrativeEventV1",
    "build_execution_narrative_event",
    "derive_execution_action_id",
    "derive_execution_event_id",
    "derive_execution_mission_id",
]
