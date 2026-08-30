"""Bounded, non-actuating transition journal for the task executive.

This module owns storage and cursor semantics only.  The calling executive
continues to own its re-entrant lock and every task mutation, so extracting the
journal cannot widen an actuation or concurrency boundary.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any

from .contracts import VerifiedFact
from .validator import ValidatedStep

TRANSITION_FAMILIES = frozenset(
    {
        "submission",
        "replacement",
        "tick",
        "report",
        "dispatch_failure",
        "interruption",
        "explicit_lifecycle",
    }
)


@dataclass(frozen=True, slots=True)
class ExecutiveTransitionV1:
    """One owner-authored task mutation, committed under the executive lock."""

    transition_sequence: int
    family: str
    task_id: str
    plan_revision: int
    plan_sha256: str
    step_id: str
    attempt: int
    skill: str
    prior_state: str
    resulting_state: str
    disposition: str
    detail_code: str
    verified_facts: tuple[VerifiedFact, ...]
    evidence_refs: tuple[str, ...]
    schema_version: int = 1

    @property
    def authorizes_actuation(self) -> bool:
        return False

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "transition_sequence": self.transition_sequence,
            "family": self.family,
            "task_id": self.task_id,
            "plan_revision": self.plan_revision,
            "plan_sha256": self.plan_sha256,
            "step_id": self.step_id,
            "attempt": self.attempt,
            "skill": self.skill,
            "prior_state": self.prior_state,
            "resulting_state": self.resulting_state,
            "disposition": self.disposition,
            "detail_code": self.detail_code,
            "verified_facts": [item.as_dict() for item in self.verified_facts],
            "evidence_refs": list(self.evidence_refs),
        }


@dataclass(frozen=True, slots=True)
class ExecutiveJournalReadV1:
    """An exact cursor read; overflow never returns a guessed suffix."""

    requested_after_sequence: int
    oldest_available_sequence: int
    latest_sequence: int
    status: str
    transitions: tuple[ExecutiveTransitionV1, ...]

    @property
    def authorizes_actuation(self) -> bool:
        return False

    def as_dict(self) -> dict[str, object]:
        return {
            "requested_after_sequence": self.requested_after_sequence,
            "oldest_available_sequence": self.oldest_available_sequence,
            "latest_sequence": self.latest_sequence,
            "status": self.status,
            "transitions": [item.as_dict() for item in self.transitions],
        }


@dataclass(frozen=True, slots=True)
class ExecutiveJournalStatusV1:
    capacity: int
    retained: int
    oldest_available_sequence: int
    latest_sequence: int
    overflow_count: int

    @property
    def authorizes_actuation(self) -> bool:
        return False

    def as_dict(self) -> dict[str, object]:
        return {
            "capacity": self.capacity,
            "retained": self.retained,
            "oldest_available_sequence": self.oldest_available_sequence,
            "latest_sequence": self.latest_sequence,
            "overflow_count": self.overflow_count,
        }


class _ExecutiveJournal:
    """Storage primitive; callers serialize access with the executive lock."""

    def __init__(self, capacity: int) -> None:
        self.capacity = capacity
        self.sequence = 0
        self.overflow_count = 0
        self.rows: deque[ExecutiveTransitionV1] = deque(maxlen=capacity)

    def status(self) -> ExecutiveJournalStatusV1:
        oldest = self.rows[0].transition_sequence if self.rows else self.sequence + 1
        return ExecutiveJournalStatusV1(
            capacity=self.capacity,
            retained=len(self.rows),
            oldest_available_sequence=oldest,
            latest_sequence=self.sequence,
            overflow_count=self.overflow_count,
        )

    def read(self, after_sequence: int) -> ExecutiveJournalReadV1:
        latest = self.sequence
        oldest = self.rows[0].transition_sequence if self.rows else latest + 1
        if after_sequence > latest:
            return ExecutiveJournalReadV1(after_sequence, oldest, latest, "cursor_ahead", ())
        if self.rows and after_sequence < oldest - 1:
            return ExecutiveJournalReadV1(after_sequence, oldest, latest, "overflow", ())
        transitions = tuple(item for item in self.rows if item.transition_sequence > after_sequence)
        if transitions and transitions[0].transition_sequence != after_sequence + 1:
            return ExecutiveJournalReadV1(after_sequence, oldest, latest, "gap", ())
        return ExecutiveJournalReadV1(after_sequence, oldest, latest, "ok", transitions)

    def append(
        self,
        record: Any,
        step: ValidatedStep,
        *,
        attempt: int,
        family: str,
        prior_state: str,
        disposition: str,
        detail_code: str,
        verified_facts: tuple[VerifiedFact, ...] = (),
        evidence_refs: tuple[str, ...] = (),
    ) -> ExecutiveTransitionV1:
        if family not in TRANSITION_FAMILIES:
            raise ValueError(f"unsupported transition family: {family}")
        if not disposition or len(disposition) > 80:
            raise ValueError("transition disposition must be bounded non-empty text")
        if not detail_code or len(detail_code) > 120:
            raise ValueError("transition detail_code must be bounded non-empty text")
        self.sequence += 1
        transition = ExecutiveTransitionV1(
            transition_sequence=self.sequence,
            family=family,
            task_id=record.task_id,
            plan_revision=record.plan_revision,
            plan_sha256=record.validated.plan_sha256,
            step_id=step.step.step_id,
            attempt=attempt,
            skill=step.step.skill,
            prior_state=prior_state,
            resulting_state=record.state,
            disposition=disposition,
            detail_code=detail_code,
            verified_facts=verified_facts,
            evidence_refs=evidence_refs,
        )
        if len(self.rows) == self.capacity:
            self.overflow_count += 1
        self.rows.append(transition)
        return transition


def new_transition_journal(capacity: int) -> _ExecutiveJournal:
    return _ExecutiveJournal(capacity)


def transition_journal_status(owner: Any) -> ExecutiveJournalStatusV1:
    with owner._lock:
        return owner._executive_journal.status()


def read_transition_journal(owner: Any, *, after_sequence: int) -> ExecutiveJournalReadV1:
    if (
        isinstance(after_sequence, bool)
        or not isinstance(after_sequence, int)
        or after_sequence < 0
    ):
        raise ValueError("after_sequence must be a non-negative integer")
    with owner._lock:
        return owner._executive_journal.read(after_sequence)


def append_transition(
    owner: Any,
    record: Any,
    step: ValidatedStep,
    *,
    attempt: int,
    family: str,
    prior_state: str,
    disposition: str,
    detail_code: str,
    verified_facts: tuple[VerifiedFact, ...] = (),
    evidence_refs: tuple[str, ...] = (),
) -> ExecutiveTransitionV1:
    """Append while the caller holds the executive's lock."""

    return owner._executive_journal.append(
        record,
        step,
        attempt=attempt,
        family=family,
        prior_state=prior_state,
        disposition=disposition,
        detail_code=detail_code,
        verified_facts=verified_facts,
        evidence_refs=evidence_refs,
    )


__all__ = [
    "ExecutiveJournalReadV1",
    "ExecutiveJournalStatusV1",
    "ExecutiveTransitionV1",
]
