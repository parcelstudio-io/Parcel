"""Process-local authentication and deterministic Model-B constraint frames."""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass, replace

from parcel_robot.brain.contracts import VerifiedFact
from parcel_robot.contracts.execution_narrative_v1 import (
    EXECUTION_NARRATIVE_STATUSES,
    SCHEMA_VERSION,
    ExecutionNarrativeEventV1,
    derive_execution_action_id,
    derive_execution_event_id,
    derive_execution_mission_id,
)


def _canonical_payload(value: dict[str, object]) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")


def _identifier(value: object, name: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 128
        or value != value.strip()
        or not value[0].isalnum()
        or any(not (character.isalnum() or character in "._:-") for character in value)
    ):
        raise ValueError(f"{name} must be a bounded identifier")
    return value


def _integer(value: object, name: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    if not minimum <= value <= (1 << 64) - 1:
        raise ValueError(f"{name} must be between {minimum} and 2^64-1")
    return value


def _digest(value: object, name: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return value


def _valid_tag(value: object) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError("auth_tag must be a lowercase SHA-256 HMAC")
    return value


@dataclass(frozen=True, slots=True)
class AuthenticatedExecutionNarrativeEventV1:
    """An event plus integrity proof, explicitly without actuation authority."""

    event: ExecutionNarrativeEventV1
    authenticator_id: str
    auth_tag: str

    def __post_init__(self) -> None:
        if not isinstance(self.event, ExecutionNarrativeEventV1):
            raise TypeError("event must be ExecutionNarrativeEventV1")
        _identifier(self.authenticator_id, "authenticator_id")
        _valid_tag(self.auth_tag)

    @property
    def authorizes_actuation(self) -> bool:
        return False

    def as_dict(self) -> dict[str, object]:
        """Expose event evidence, never the local authentication secret/tag."""

        return self.event.as_dict()


class TrustedExecutionNarrativeAuthenticatorV1:
    """A process-local integrity channel with no publisher or actuator handle."""

    __slots__ = ("_key", "authenticator_id")

    def __init__(self, *, authenticator_id: str, key: bytes) -> None:
        self.authenticator_id = _identifier(authenticator_id, "authenticator_id")
        if not isinstance(key, bytes) or len(key) < 32:
            raise ValueError("event authentication key must contain at least 32 bytes")
        self._key = bytes(key)

    @property
    def authorizes_actuation(self) -> bool:
        return False

    def authenticate(
        self,
        event: ExecutionNarrativeEventV1,
    ) -> AuthenticatedExecutionNarrativeEventV1:
        if not isinstance(event, ExecutionNarrativeEventV1):
            raise TypeError("event must be ExecutionNarrativeEventV1")
        tag = hmac.new(
            self._key,
            _canonical_payload(event.as_dict()),
            hashlib.sha256,
        ).hexdigest()
        return AuthenticatedExecutionNarrativeEventV1(
            event=event,
            authenticator_id=self.authenticator_id,
            auth_tag=tag,
        )

    def verify(self, authenticated: object) -> bool:
        if not isinstance(authenticated, AuthenticatedExecutionNarrativeEventV1):
            return False
        if authenticated.authenticator_id != self.authenticator_id:
            return False
        expected = hmac.new(
            self._key,
            _canonical_payload(authenticated.event.as_dict()),
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(authenticated.auth_tag, expected)


@dataclass(frozen=True, slots=True)
class NarrativeTaskCursorV1:
    """The consumer's exact accepted lineage for one bounded task."""

    task_id: str
    plan_revision: int
    step_id: str
    attempt: int
    plan_sha256: str
    action_name: str
    phase: str
    resume_parent_task_id: str | None


@dataclass(frozen=True, slots=True)
class NarrativeConsumerStateV1:
    source_epoch: int
    speech_generation: int
    last_event_sequence: int = 0
    seen_event_ids: tuple[str, ...] = ()
    tasks: tuple[NarrativeTaskCursorV1, ...] = ()

    def __post_init__(self) -> None:
        _integer(self.source_epoch, "source_epoch", minimum=1)
        _integer(self.speech_generation, "speech_generation")
        _integer(self.last_event_sequence, "last_event_sequence")
        if len(self.seen_event_ids) > 4096:
            raise ValueError("seen event history exceeds 4096 entries")
        if len(set(self.seen_event_ids)) != len(self.seen_event_ids):
            raise ValueError("seen event history cannot contain duplicates")
        if len(self.tasks) > 256:
            raise ValueError("narrative task state exceeds 256 entries")
        if len({item.task_id for item in self.tasks}) != len(self.tasks):
            raise ValueError("narrative task state cannot contain duplicate task IDs")

    def as_dict(self) -> dict[str, object]:
        return {
            "source_epoch": self.source_epoch,
            "speech_generation": self.speech_generation,
            "last_event_sequence": self.last_event_sequence,
            "seen_event_ids": list(self.seen_event_ids),
            "tasks": [
                {
                    "task_id": item.task_id,
                    "plan_revision": item.plan_revision,
                    "step_id": item.step_id,
                    "attempt": item.attempt,
                    "plan_sha256": item.plan_sha256,
                    "action_name": item.action_name,
                    "phase": item.phase,
                    "resume_parent_task_id": item.resume_parent_task_id,
                }
                for item in self.tasks
            ],
        }


@dataclass(frozen=True, slots=True)
class ModelBNarrationFrameV1:
    """A deterministic fact/tense frame; a model may choose wording only."""

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
    tense: str
    source_epoch: int
    speech_generation: int
    issued_at_monotonic_ns: int
    claimable_until_monotonic_ns: int
    claimable_facts: tuple[VerifiedFact, ...]
    evidence_refs: tuple[str, ...]
    detail_code: str
    constraints: tuple[str, ...]
    resume_parent_task_id: str | None

    def __post_init__(self) -> None:
        _identifier(self.event_id, "event_id")
        _integer(self.event_sequence, "event_sequence", minimum=1)
        _identifier(self.task_id, "task_id")
        _integer(self.plan_revision, "plan_revision", minimum=1)
        _identifier(self.step_id, "step_id")
        _integer(self.attempt, "attempt", minimum=1)
        _identifier(self.mission_id, "mission_id")
        _identifier(self.action_id, "action_id")
        _identifier(self.action_name, "action_name")
        _digest(self.plan_sha256, "plan_sha256")
        if self.status not in EXECUTION_NARRATIVE_STATUSES:
            raise ValueError("status is not an execution narrative status")
        if self.tense not in {"future", "present", "past"}:
            raise ValueError("tense must be future, present, or past")
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
        if not isinstance(self.claimable_facts, tuple) or len(self.claimable_facts) > 16:
            raise TypeError("claimable_facts must be a bounded tuple")
        if any(not isinstance(item, VerifiedFact) for item in self.claimable_facts):
            raise TypeError("claimable_facts must contain VerifiedFact values")
        if not isinstance(self.evidence_refs, tuple) or len(self.evidence_refs) > 16:
            raise TypeError("evidence_refs must be a bounded tuple")
        for reference in self.evidence_refs:
            _identifier(reference, "evidence reference")
        if len(set(self.evidence_refs)) != len(self.evidence_refs):
            raise ValueError("evidence_refs cannot contain duplicates")
        if (
            not isinstance(self.detail_code, str)
            or not self.detail_code
            or self.detail_code != self.detail_code.strip()
            or len(self.detail_code) > 120
        ):
            raise ValueError("detail_code must be non-empty bounded text")
        if not isinstance(self.constraints, tuple) or not self.constraints:
            raise TypeError("constraints must be a non-empty tuple")
        for constraint in self.constraints:
            _identifier(constraint, "constraint")
        if len(set(self.constraints)) != len(self.constraints):
            raise ValueError("constraints cannot contain duplicates")
        if self.resume_parent_task_id is not None:
            _identifier(self.resume_parent_task_id, "resume_parent_task_id")
            if self.resume_parent_task_id == self.task_id:
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
            raise ValueError("action_id does not match frame lineage")
        identity_payload: dict[str, object] = {
            "schema_version": SCHEMA_VERSION,
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
            "verified_facts": [item.as_dict() for item in self.claimable_facts],
            "evidence_refs": list(self.evidence_refs),
            "detail_code": self.detail_code,
            "resume_parent_task_id": self.resume_parent_task_id,
        }
        if self.event_id != derive_execution_event_id(identity_payload):
            raise ValueError("event_id does not match frame content")

    @property
    def authorizes_actuation(self) -> bool:
        return False

    def as_dict(self) -> dict[str, object]:
        return {
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
            "tense": self.tense,
            "source_epoch": self.source_epoch,
            "speech_generation": self.speech_generation,
            "issued_at_monotonic_ns": self.issued_at_monotonic_ns,
            "claimable_until_monotonic_ns": self.claimable_until_monotonic_ns,
            "claimable_facts": [item.as_dict() for item in self.claimable_facts],
            "evidence_refs": list(self.evidence_refs),
            "detail_code": self.detail_code,
            "constraints": list(self.constraints),
            "resume_parent_task_id": self.resume_parent_task_id,
        }


@dataclass(frozen=True, slots=True)
class NarrativeConsumptionV1:
    accepted: bool
    reason: str
    state: NarrativeConsumerStateV1
    frame: ModelBNarrationFrameV1 | None


def advance_speech_generation(
    state: NarrativeConsumerStateV1,
    *,
    speech_generation: int,
) -> NarrativeConsumerStateV1:
    """Explicitly advance a voice session; old and speculative future fail closed."""

    generation = _integer(speech_generation, "speech_generation")
    if generation <= state.speech_generation:
        raise ValueError("speech_generation must advance")
    return replace(state, speech_generation=generation)


def _reject(state: NarrativeConsumerStateV1, reason: str) -> NarrativeConsumptionV1:
    return NarrativeConsumptionV1(False, reason, state, None)


def _cursor_map(state: NarrativeConsumerStateV1) -> dict[str, NarrativeTaskCursorV1]:
    return {item.task_id: item for item in state.tasks}


def _exact_lineage(cursor: NarrativeTaskCursorV1, event: ExecutionNarrativeEventV1) -> bool:
    return (
        event.plan_revision == cursor.plan_revision
        and event.step_id == cursor.step_id
        and event.attempt == cursor.attempt
        and event.plan_sha256 == cursor.plan_sha256
        and event.action_name == cursor.action_name
        and event.resume_parent_task_id == cursor.resume_parent_task_id
    )


_TERMINAL_TASK_PHASES = {"succeeded", "failed", "cancelled"}
_NEXT_STEP_BLOCK_DETAIL_CODES = frozenset(
    {"preconditions_not_satisfied", "resources_unavailable"}
)
_RETRY_ADVANCE_STATUSES = frozenset({"started", "blocked", "suspended", "cancelled"})
_NEXT_STEP_ADVANCE_STATUSES = frozenset(
    {"started", "blocked", "suspended", "cancelled"}
)
_ALLOWED_EVENT_PHASES = {
    "started": {"accepted", "replanned", "resumed", "blocked", "progress", "step_succeeded"},
    "progress": {"started", "progress", "blocked", "resumed"},
    "blocked": {"accepted", "started", "progress", "blocked", "replanned", "resumed"},
    "suspended": {"accepted", "started", "progress", "blocked", "replanned", "resumed"},
    "resumed": {"suspended"},
    "succeeded": {"started", "progress", "resumed"},
    "failed": {"started", "progress", "blocked", "resumed"},
    "cancelled": {
        "accepted",
        "started",
        "progress",
        "blocked",
        "replanned",
        "resumed",
        "suspended",
    },
}


def _accept_task(
    tasks: dict[str, NarrativeTaskCursorV1],
    event: ExecutionNarrativeEventV1,
) -> tuple[dict[str, NarrativeTaskCursorV1] | None, str]:
    if event.task_id in tasks:
        return None, "task_already_known"
    if len(tasks) >= 256:
        return None, "task_capacity_exhausted"
    if event.resume_parent_task_id is not None:
        parent = tasks.get(event.resume_parent_task_id)
        if parent is None or parent.phase != "suspended":
            return None, "resume_parent_not_suspended"
    tasks[event.task_id] = NarrativeTaskCursorV1(
        task_id=event.task_id,
        plan_revision=event.plan_revision,
        step_id=event.step_id,
        attempt=event.attempt,
        plan_sha256=event.plan_sha256,
        action_name=event.action_name,
        phase="accepted",
        resume_parent_task_id=event.resume_parent_task_id,
    )
    return tasks, "accepted"


def _replan_task(
    tasks: dict[str, NarrativeTaskCursorV1],
    cursor: NarrativeTaskCursorV1,
    event: ExecutionNarrativeEventV1,
) -> tuple[dict[str, NarrativeTaskCursorV1] | None, str]:
    if event.plan_revision < cursor.plan_revision:
        return None, "plan_revision_regression"
    if event.plan_revision == cursor.plan_revision and not _exact_lineage(cursor, event):
        return None, "replan_lineage_mismatch"
    tasks[event.task_id] = NarrativeTaskCursorV1(
        event.task_id,
        event.plan_revision,
        event.step_id,
        event.attempt,
        event.plan_sha256,
        event.action_name,
        "replanned",
        event.resume_parent_task_id,
    )
    return tasks, "accepted"


def _advance_started_cursor(
    tasks: dict[str, NarrativeTaskCursorV1],
    cursor: NarrativeTaskCursorV1,
    event: ExecutionNarrativeEventV1,
) -> tuple[NarrativeTaskCursorV1 | None, str | None]:
    if event.status in _RETRY_ADVANCE_STATUSES and event.attempt == cursor.attempt + 1:
        if (
            cursor.phase != "blocked"
            or event.plan_revision != cursor.plan_revision
            or event.step_id != cursor.step_id
            or event.plan_sha256 != cursor.plan_sha256
            or event.action_name != cursor.action_name
            or (
                event.status == "blocked"
                and event.detail_code not in _NEXT_STEP_BLOCK_DETAIL_CODES
            )
        ):
            return None, "retry_lineage_mismatch"
        cursor = replace(cursor, attempt=event.attempt)
        tasks[event.task_id] = cursor

    advances_to_next_step = event.status in _NEXT_STEP_ADVANCE_STATUSES and (
        event.status != "blocked" or event.detail_code in _NEXT_STEP_BLOCK_DETAIL_CODES
    )
    if advances_to_next_step and cursor.phase == "step_succeeded":
        if (
            event.plan_revision != cursor.plan_revision
            or event.plan_sha256 != cursor.plan_sha256
            or event.attempt != 1
            or event.step_id == cursor.step_id
        ):
            return None, "next_step_lineage_mismatch"
        cursor = replace(
            cursor,
            step_id=event.step_id,
            attempt=event.attempt,
            action_name=event.action_name,
            # Treat the owner-selected next step as admitted but not yet
            # running.  This permits only the normal started/blocked edges
            # below and does not invent completion or actuation authority.
            phase="accepted",
        )
        tasks[event.task_id] = cursor
    elif event.status == "blocked" and cursor.phase == "step_succeeded":
        return None, "next_step_lineage_mismatch"
    return cursor, None


def _finish_task_transition(
    tasks: dict[str, NarrativeTaskCursorV1],
    cursor: NarrativeTaskCursorV1,
    event: ExecutionNarrativeEventV1,
) -> tuple[dict[str, NarrativeTaskCursorV1] | None, str]:
    if not _exact_lineage(cursor, event):
        return None, "task_lineage_mismatch"
    if cursor.phase not in _ALLOWED_EVENT_PHASES.get(event.status, set()):
        return None, "invalid_lifecycle_transition"
    if event.status == "succeeded" and not event.verified_facts:
        return None, "success_fact_missing"
    if event.status == "succeeded" and cursor.resume_parent_task_id is not None:
        parent = tasks.get(cursor.resume_parent_task_id)
        if parent is None or parent.phase != "suspended":
            return None, "resume_parent_not_suspended"
    phase = (
        "step_succeeded"
        if event.status == "progress" and event.detail_code.startswith("step_succeeded:")
        else event.status
    )
    tasks[event.task_id] = replace(cursor, phase=phase)
    return tasks, "accepted"


def _transition(
    state: NarrativeConsumerStateV1,
    event: ExecutionNarrativeEventV1,
) -> tuple[dict[str, NarrativeTaskCursorV1] | None, str]:
    tasks = _cursor_map(state)
    cursor = tasks.get(event.task_id)

    if event.status == "accepted":
        return _accept_task(tasks, event)

    if cursor is None:
        return None, "unknown_task"
    if cursor.phase in _TERMINAL_TASK_PHASES:
        return None, "post_terminal_event"
    if event.resume_parent_task_id != cursor.resume_parent_task_id:
        return None, "resume_parent_mismatch"

    if event.status == "replanned":
        return _replan_task(tasks, cursor, event)

    cursor, reason = _advance_started_cursor(tasks, cursor, event)
    if cursor is None:
        assert reason is not None
        return None, reason
    return _finish_task_transition(tasks, cursor, event)


def _frame(event: ExecutionNarrativeEventV1) -> ModelBNarrationFrameV1:
    if event.status in {"accepted", "replanned"}:
        tense = "future"
    elif event.status in {"started", "progress", "blocked", "resumed"}:
        tense = "present"
    else:
        tense = "past"
    constraints = (
        "wording_only",
        "no_actuation",
        "do_not_infer_unlisted_observations",
        "do_not_claim_completion_without_listed_facts",
    )
    return ModelBNarrationFrameV1(
        event_id=event.event_id,
        event_sequence=event.event_sequence,
        task_id=event.task_id,
        plan_revision=event.plan_revision,
        step_id=event.step_id,
        attempt=event.attempt,
        mission_id=event.mission_id,
        action_id=event.action_id,
        action_name=event.action_name,
        plan_sha256=event.plan_sha256,
        status=event.status,
        tense=tense,
        source_epoch=event.source_epoch,
        speech_generation=event.speech_generation,
        issued_at_monotonic_ns=event.issued_at_monotonic_ns,
        claimable_until_monotonic_ns=event.claimable_until_monotonic_ns,
        claimable_facts=event.verified_facts,
        evidence_refs=event.evidence_refs,
        detail_code=event.detail_code,
        constraints=constraints,
        resume_parent_task_id=event.resume_parent_task_id,
    )


def consume_execution_narrative_event(
    state: NarrativeConsumerStateV1,
    authenticated: object,
    *,
    authenticator: TrustedExecutionNarrativeAuthenticatorV1,
    now_monotonic_ns: int,
) -> NarrativeConsumptionV1:
    """Authenticate, freshness-check, and reduce one event atomically."""

    now = _integer(now_monotonic_ns, "now_monotonic_ns")
    if not authenticator.verify(authenticated):
        return _reject(state, "event_authentication_failed")
    assert isinstance(authenticated, AuthenticatedExecutionNarrativeEventV1)
    event = authenticated.event
    if event.source_epoch != state.source_epoch:
        return _reject(state, "source_epoch_mismatch")
    if event.speech_generation != state.speech_generation:
        return _reject(state, "speech_generation_mismatch")
    if event.event_id in state.seen_event_ids:
        return _reject(state, "event_already_consumed")
    if event.event_sequence <= state.last_event_sequence:
        return _reject(state, "event_sequence_regression")
    if event.event_sequence != state.last_event_sequence + 1:
        return _reject(state, "event_sequence_gap")
    if event.issued_at_monotonic_ns > now:
        return _reject(state, "event_from_future")
    if now >= event.claimable_until_monotonic_ns:
        return _reject(state, "event_expired")
    tasks, reason = _transition(state, event)
    if tasks is None:
        return _reject(state, reason)
    if len(state.seen_event_ids) >= 4096:
        return _reject(state, "event_history_capacity_exhausted")
    next_state = NarrativeConsumerStateV1(
        source_epoch=state.source_epoch,
        speech_generation=state.speech_generation,
        last_event_sequence=event.event_sequence,
        seen_event_ids=state.seen_event_ids + (event.event_id,),
        tasks=tuple(tasks[key] for key in sorted(tasks)),
    )
    if event.detail_code == "unverified_success_claim":
        # This event is authenticated, contiguous, and lineage-valid, and the
        # executive has already converted the bad completion claim into an
        # honest terminal failure.  Consume it to preserve stream continuity,
        # but license no prose from the unverified success input.
        return NarrativeConsumptionV1(
            True,
            "unverified_success_claim_consumed_silently",
            next_state,
            None,
        )
    return NarrativeConsumptionV1(True, reason, next_state, _frame(event))


__all__ = [
    "AuthenticatedExecutionNarrativeEventV1",
    "ModelBNarrationFrameV1",
    "NarrativeConsumerStateV1",
    "NarrativeConsumptionV1",
    "NarrativeTaskCursorV1",
    "TrustedExecutionNarrativeAuthenticatorV1",
    "advance_speech_generation",
    "consume_execution_narrative_event",
]
