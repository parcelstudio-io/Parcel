"""In-process atomicity helpers for task-executive plan replacement.

This leaf owns no task or motion authority.  Its functions run only while the
calling :class:`TaskExecutive` holds its lock and compensate local revision
sinks, journal state, task fields, and semantic resource leases together.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from dataclasses import dataclass, fields
from typing import Any, TypeVar

from parcel_robot.revision import RevisionSink

from .contracts import ExecutionResult, VerifiedFact
from .executive_journal import (
    ExecutiveTransitionV1,
)
from .executive_journal import (
    append_transition as _append_transition_impl,
)
from .validator import ValidatedPlan, ValidatedStep

DispositionT = TypeVar("DispositionT")


@dataclass(frozen=True, slots=True)
class _RevisionSinkCheckpoint:
    sink: RevisionSink
    state: object


@dataclass(frozen=True, slots=True)
class _JournalCheckpoint:
    sequence: int
    overflow_count: int
    rows: tuple[ExecutiveTransitionV1, ...]


@dataclass(slots=True)
class ReplacementTransaction:
    record: Any
    prior_record: Any
    sink_checkpoints: tuple[_RevisionSinkCheckpoint, ...]
    journal_checkpoint: _JournalCheckpoint


@dataclass(frozen=True, slots=True)
class _DeferredReportCheckpoint:
    record: Any
    prior_record: Any
    resource_owners: object
    journal_checkpoint: _JournalCheckpoint


def checkpoint_revision_sink(sink: RevisionSink) -> _RevisionSinkCheckpoint:
    """Lock one sink and capture rollback state before it is mutated."""

    acquire = getattr(sink, "revision_transaction_acquire", None)
    release = getattr(sink, "revision_transaction_release", None)
    snapshot = getattr(sink, "revision_transaction_snapshot", None)
    restore = getattr(sink, "revision_transaction_restore", None)
    hooks = (acquire, release, snapshot, restore)
    if not all(callable(hook) for hook in hooks):
        raise TypeError(
            "revision sink must expose acquire/release/snapshot/restore transaction hooks"
        )
    acquire()
    try:
        state = snapshot()
    except BaseException:
        release()
        raise
    return _RevisionSinkCheckpoint(sink, state)


def validate_revision_sink(sink: RevisionSink) -> None:
    """Prove a sink has the isolation hooks required at registration."""

    checkpoint = checkpoint_revision_sink(sink)
    checkpoint.sink.revision_transaction_release()


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
    """Append a transition and finish any staged revision transaction."""

    transaction = owner._replacement_transaction
    if transaction is not None and (transaction.record is not record or family != "replacement"):
        _rollback_replacement(owner, transaction)
        raise RuntimeError("replacement transaction was not journaled atomically")
    try:
        transition = _append_transition_impl(
            owner,
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
    except BaseException:
        if transaction is not None:
            _rollback_replacement(owner, transaction)
        raise
    if transaction is not None:
        try:
            owner.resources.release(record.task_id)
        except BaseException:
            _rollback_replacement(owner, transaction)
            raise
        owner._replacement_transaction = None
        _release_revision_sinks(transaction.sink_checkpoints)
    return transition


def report_with_rollback(
    owner: Any,
    result: ExecutionResult,
    handler: Callable[..., DispositionT],
    make_disposition: Callable[..., DispositionT],
) -> DispositionT:
    """Run reporting with a wider rollback boundary for deferred revisions."""

    checkpoint = _checkpoint_deferred_report(owner, result.task_id)
    try:
        return handler(owner, result, make_disposition)
    except BaseException:
        if checkpoint is not None:
            _restore_deferred_report(owner, checkpoint)
        raise


def activate_replacement(owner: Any, record: Any, replacement: ValidatedPlan) -> None:
    """Stage a revision; its immediately following journal append commits it."""

    if owner._replacement_transaction is not None:
        raise RuntimeError("a replacement transaction is already active")
    journal_checkpoint = _checkpoint_journal(owner._executive_journal)
    prior_record = copy.copy(record)
    sink_checkpoints = _checkpoint_revision_sinks(owner._revision_sinks)
    try:
        for sink in owner._revision_sinks:
            sink.commit_revision(
                task_id=replacement.plan.task_id,
                plan_revision=replacement.plan.plan_revision,
            )
        record.validated = replacement
        record.state = "queued"
        record.step_index = 0
        record.attempt = 1
        record.step_started_at = None
        record.at_checkpoint = True
        record.pending_interrupt = None
        record.pending_replacement = None
        record.pending_recovery = None
        record.conflicts = ()
        record.last_detail = "replacement_activated"
        owner._replacement_transaction = ReplacementTransaction(
            record=record,
            prior_record=prior_record,
            sink_checkpoints=sink_checkpoints,
            journal_checkpoint=journal_checkpoint,
        )
    except BaseException:
        _restore_record(record, prior_record)
        _restore_journal(owner._executive_journal, journal_checkpoint)
        _restore_and_release_revision_sinks(sink_checkpoints)
        raise


def _checkpoint_deferred_report(owner: Any, task_id: str) -> _DeferredReportCheckpoint | None:
    record = owner._tasks.get(task_id)
    if record is None or record.pending_replacement is None:
        return None
    return _DeferredReportCheckpoint(
        record=record,
        prior_record=copy.copy(record),
        resource_owners=owner.resources._checkpoint_owners(),
        journal_checkpoint=_checkpoint_journal(owner._executive_journal),
    )


def _restore_deferred_report(owner: Any, checkpoint: _DeferredReportCheckpoint) -> None:
    transaction = owner._replacement_transaction
    if transaction is not None:
        _rollback_replacement(owner, transaction)
    _restore_record(checkpoint.record, checkpoint.prior_record)
    owner.resources._restore_owners(checkpoint.resource_owners)
    _restore_journal(owner._executive_journal, checkpoint.journal_checkpoint)


def _rollback_replacement(owner: Any, transaction: ReplacementTransaction) -> None:
    try:
        for checkpoint in reversed(transaction.sink_checkpoints):
            _restore_revision_sink(checkpoint)
        _restore_record(transaction.record, transaction.prior_record)
        _restore_journal(owner._executive_journal, transaction.journal_checkpoint)
        owner._replacement_transaction = None
    finally:
        _release_revision_sinks(transaction.sink_checkpoints)


def _restore_record(record: Any, prior_record: Any) -> None:
    for item in fields(type(record)):
        setattr(record, item.name, getattr(prior_record, item.name))


def _checkpoint_journal(journal: Any) -> _JournalCheckpoint:
    return _JournalCheckpoint(
        sequence=journal.sequence,
        overflow_count=journal.overflow_count,
        rows=tuple(journal.rows),
    )


def _restore_journal(journal: Any, checkpoint: _JournalCheckpoint) -> None:
    journal.sequence = checkpoint.sequence
    journal.overflow_count = checkpoint.overflow_count
    journal.rows.clear()
    journal.rows.extend(checkpoint.rows)


def _restore_revision_sink(checkpoint: _RevisionSinkCheckpoint) -> None:
    checkpoint.sink.revision_transaction_restore(checkpoint.state)


def _checkpoint_revision_sinks(
    sinks: tuple[RevisionSink, ...] | list[RevisionSink],
) -> tuple[_RevisionSinkCheckpoint, ...]:
    checkpoints: list[_RevisionSinkCheckpoint] = []
    try:
        # Object identity is a process-wide total order while these live
        # references exist.  Using it rather than executive registration order
        # prevents two executives that share sinks in opposite registration
        # orders from taking A->B and B->A and deadlocking.
        for sink in sorted(sinks, key=id):
            checkpoints.append(checkpoint_revision_sink(sink))
    except BaseException:
        _release_revision_sinks(tuple(checkpoints))
        raise
    return tuple(checkpoints)


def _restore_and_release_revision_sinks(
    checkpoints: tuple[_RevisionSinkCheckpoint, ...],
) -> None:
    try:
        for checkpoint in reversed(checkpoints):
            _restore_revision_sink(checkpoint)
    finally:
        _release_revision_sinks(checkpoints)


def _release_revision_sinks(
    checkpoints: tuple[_RevisionSinkCheckpoint, ...],
) -> None:
    for checkpoint in reversed(checkpoints):
        checkpoint.sink.revision_transaction_release()


__all__ = [
    "ReplacementTransaction",
    "activate_replacement",
    "append_transition",
    "checkpoint_revision_sink",
    "report_with_rollback",
    "validate_revision_sink",
]
