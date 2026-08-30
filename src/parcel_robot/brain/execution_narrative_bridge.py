"""One-to-one mapping from the executive-owned journal to Model-B facts.

The bridge never decides that a transition happened by comparing snapshots.
It delegates first, reads the exact owner-authored journal suffix, validates
continuity, then atomically enqueues authenticated read-only events. A journal
gap or either bounded queue overflowing latches a visible fault and no post-gap
event is narrated.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar

from parcel_robot.contracts.execution_narrative_v1 import (
    ExecutionNarrativeEventV1,
    build_execution_narrative_event,
)
from parcel_robot.revision import RevisionSink
from parcel_robot.voice.execution_narrative import (
    AuthenticatedExecutionNarrativeEventV1,
    TrustedExecutionNarrativeAuthenticatorV1,
)

from .contracts import ExecutionResult, ObservationSnapshot
from .executive import (
    DispatchRequest,
    ExecutiveJournalReadV1,
    ExecutiveJournalStatusV1,
    ExecutiveSubmission,
    ExecutiveTransitionV1,
    InterruptDecision,
    InterruptRequest,
    ReportDisposition,
    ResourceLocks,
    TaskExecutive,
)
from .validator import ValidatedPlan

_T = TypeVar("_T")


_NARRATIVE_STATUS_BY_DISPOSITION = {
    "task_queued": "accepted",
    "replacement_activated": "replanned",
    # A deferred replacement has not changed the active plan lineage yet. It
    # is owner-authored progress about a pending revision; mapping it as an
    # already-active replan makes a subsequent old-plan progress report look
    # corrupt to the consumer FSM.
    "replacement_deferred": "progress",
    "replacement_activated_at_checkpoint": "replanned",
    "replacement_activated_after_step": "replanned",
    "step_dispatched": "started",
    "step_timeout_retry": "blocked",
    "step_timeout_failed": "failed",
    "waiting_precondition": "blocked",
    "waiting_resource": "blocked",
    "progress_recorded": "progress",
    "step_succeeded": "progress",
    "task_succeeded": "succeeded",
    "retry_scheduled": "blocked",
    "task_failed": "failed",
    "task_cancelled": "cancelled",
    "cancelled_at_checkpoint": "cancelled",
    "cancelled_after_step": "cancelled",
    "interrupt_cancelled": "cancelled",
    "interrupt_waiting_checkpoint": "blocked",
    "interrupt_suspended": "suspended",
    "task_suspended": "suspended",
    "task_resumed": "resumed",
    "task_resumed_running": "resumed",
}


class ExecutiveJournalContinuityError(RuntimeError):
    """The bridge cannot prove a contiguous owner-authored suffix."""

    def __init__(self, fault_code: str) -> None:
        self.fault_code = fault_code
        super().__init__(f"execution narrative journal fault: {fault_code}")


@dataclass(frozen=True, slots=True)
class NarrativeQueueStatusV1:
    queued: int
    capacity: int
    overflow_count: int
    journal_cursor: int
    fault_code: str | None


class NarratingTaskExecutiveV1:
    """Explicit ``TaskExecutive`` facade over its authoritative journal."""

    def __init__(
        self,
        executive: TaskExecutive,
        *,
        authenticator: TrustedExecutionNarrativeAuthenticatorV1,
        source_epoch: int,
        speech_generation_provider: Callable[[], int] = lambda: 0,
        monotonic_ns: Callable[[], int] = time.monotonic_ns,
        event_ttl_ns: int = 5_000_000_000,
        event_capacity: int = 4096,
        journal_cursor: int = 0,
    ) -> None:
        if not isinstance(executive, TaskExecutive):
            raise TypeError("executive must be TaskExecutive")
        if not isinstance(authenticator, TrustedExecutionNarrativeAuthenticatorV1):
            raise TypeError("authenticator must be TrustedExecutionNarrativeAuthenticatorV1")
        if isinstance(source_epoch, bool) or not isinstance(source_epoch, int) or source_epoch < 1:
            raise ValueError("source_epoch must be a positive integer")
        if not callable(speech_generation_provider) or not callable(monotonic_ns):
            raise TypeError("time and speech generation providers must be callable")
        if isinstance(event_ttl_ns, bool) or not isinstance(event_ttl_ns, int):
            raise TypeError("event_ttl_ns must be an integer")
        if event_ttl_ns < 1 or event_ttl_ns > 60_000_000_000:
            raise ValueError("event_ttl_ns must be between 1ns and 60s")
        if isinstance(event_capacity, bool) or not isinstance(event_capacity, int):
            raise TypeError("event_capacity must be an integer")
        if not 1 <= event_capacity <= 65_536:
            raise ValueError("event_capacity must be between 1 and 65536")
        if isinstance(journal_cursor, bool) or not isinstance(journal_cursor, int):
            raise TypeError("journal_cursor must be an integer")
        if journal_cursor < 0:
            raise ValueError("journal_cursor cannot be negative")
        self._executive = executive
        self._authenticator = authenticator
        self._source_epoch = source_epoch
        self._speech_generation_provider = speech_generation_provider
        self._monotonic_ns = monotonic_ns
        self._event_ttl_ns = event_ttl_ns
        self._events: deque[AuthenticatedExecutionNarrativeEventV1] = deque()
        self._event_capacity = event_capacity
        self._overflow_count = 0
        self._journal_cursor = journal_cursor
        self._fault_code: str | None = None
        self._resume_parents: dict[str, str] = {}
        self._task_states: dict[str, str] = {}
        self._lock = threading.RLock()

    @property
    def resources(self) -> ResourceLocks:
        return self._executive.resources

    @property
    def max_records(self) -> int:
        return self._executive.max_records

    @property
    def authorizes_actuation(self) -> bool:
        return False

    def register_revision_sink(self, sink: RevisionSink) -> None:
        with self._lock:
            self._executive.register_revision_sink(sink)

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return self._executive.snapshot()

    def transition_journal_status(self) -> ExecutiveJournalStatusV1:
        with self._lock:
            return self._executive.transition_journal_status()

    def read_transition_journal(self, *, after_sequence: int) -> ExecutiveJournalReadV1:
        with self._lock:
            return self._executive.read_transition_journal(after_sequence=after_sequence)

    def narrative_queue_status(self) -> NarrativeQueueStatusV1:
        with self._lock:
            return NarrativeQueueStatusV1(
                queued=len(self._events),
                capacity=self._event_capacity,
                overflow_count=self._overflow_count,
                journal_cursor=self._journal_cursor,
                fault_code=self._fault_code,
            )

    def drain_narrative_events(
        self,
        *,
        maximum: int | None = None,
    ) -> tuple[AuthenticatedExecutionNarrativeEventV1, ...]:
        with self._lock:
            count = len(self._events) if maximum is None else maximum
            if isinstance(count, bool) or not isinstance(count, int) or count < 0:
                raise ValueError("maximum must be a non-negative integer or null")
            return tuple(
                self._events.popleft() for _ in range(min(count, len(self._events)))
            )

    def sync_narrative_transitions(self) -> int:
        """Map a contiguous journal suffix or latch an explicit fault."""

        with self._lock:
            return self._map_committed_transitions()

    def submit(
        self,
        validated: ValidatedPlan,
        *,
        task_class: str = "active_task",
        resume_parent_task_id: str | None = None,
    ) -> ExecutiveSubmission:
        with self._lock:
            if resume_parent_task_id is not None:
                if self._task_states.get(resume_parent_task_id) != "suspended":
                    raise ValueError("resume parent must name one exact suspended task")
                if validated.plan.task_id == resume_parent_task_id:
                    raise ValueError("a child task must have a distinct identity")
            disposition = self._executive.submit(validated, task_class=task_class)
            if disposition.accepted:
                if resume_parent_task_id is None:
                    self._resume_parents.pop(validated.plan.task_id, None)
                else:
                    self._resume_parents[validated.plan.task_id] = resume_parent_task_id
            self._map_committed_transitions()
            return disposition

    def replace(self, validated: ValidatedPlan) -> ExecutiveSubmission:
        return self._delegate(lambda: self._executive.replace(validated))

    def tick(
        self,
        snapshot: ObservationSnapshot | None = None,
        *,
        now: float | None = None,
    ) -> tuple[DispatchRequest, ...]:
        return self._delegate(lambda: self._executive.tick(snapshot, now=now))

    def report(self, result: ExecutionResult) -> ReportDisposition:
        return self._delegate(lambda: self._executive.report(result))

    def dispatch_failed(
        self,
        request: DispatchRequest,
        detail: str,
    ) -> ReportDisposition:
        return self._delegate(lambda: self._executive.dispatch_failed(request, detail))

    def request_interrupt(self, request: InterruptRequest) -> InterruptDecision:
        return self._delegate(lambda: self._executive.request_interrupt(request))

    def cancel_all(self, reason: str) -> InterruptDecision:
        # The owner's nested request_interrupt call appends once; this outer
        # wrapper drains once, so nested public calls cannot duplicate rows.
        return self._delegate(lambda: self._executive.cancel_all(reason))

    def suspend_task(self, task_id: str, *, reason: str) -> ReportDisposition:
        return self._delegate(lambda: self._executive.suspend_task(task_id, reason=reason))

    def resume_task(self, task_id: str, *, reason: str = "resume") -> ReportDisposition:
        return self._delegate(lambda: self._executive.resume_task(task_id, reason=reason))

    def resume_task_running(
        self,
        task_id: str,
        *,
        reason: str = "resume",
        now: float | None = None,
    ) -> tuple[ReportDisposition, DispatchRequest | None]:
        return self._delegate(
            lambda: self._executive.resume_task_running(task_id, reason=reason, now=now)
        )

    def _delegate(self, operation: Callable[[], _T]) -> _T:
        with self._lock:
            result = operation()
            self._map_committed_transitions()
            return result

    def _latch_fault(self, fault_code: str) -> None:
        if self._fault_code is None:
            self._fault_code = fault_code

    def _map_committed_transitions(self) -> int:
        if self._fault_code is not None:
            raise ExecutiveJournalContinuityError(self._fault_code)
        batch = self._executive.read_transition_journal(
            after_sequence=self._journal_cursor
        )
        if batch.status != "ok":
            fault = f"journal_{batch.status}"
            self._latch_fault(fault)
            raise ExecutiveJournalContinuityError(fault)
        expected = self._journal_cursor + 1
        for transition in batch.transitions:
            if transition.transition_sequence != expected:
                self._latch_fault("journal_sequence_gap")
                raise ExecutiveJournalContinuityError("journal_sequence_gap")
            expected += 1
        if len(self._events) + len(batch.transitions) > self._event_capacity:
            self._overflow_count += (
                len(self._events) + len(batch.transitions) - self._event_capacity
            )
            self._latch_fault("narrative_queue_overflow")
            raise ExecutiveJournalContinuityError("narrative_queue_overflow")

        prepared: list[AuthenticatedExecutionNarrativeEventV1] = []
        try:
            for transition in batch.transitions:
                prepared.append(
                    self._authenticator.authenticate(self._event_from_transition(transition))
                )
        except Exception as error:
            self._latch_fault("journal_mapping_failed")
            raise ExecutiveJournalContinuityError("journal_mapping_failed") from error

        self._events.extend(prepared)
        for transition in batch.transitions:
            self._task_states[transition.task_id] = transition.resulting_state
        if batch.transitions:
            self._journal_cursor = batch.transitions[-1].transition_sequence
        return len(batch.transitions)

    def _event_from_transition(
        self,
        transition: ExecutiveTransitionV1,
    ) -> ExecutionNarrativeEventV1:
        status = _NARRATIVE_STATUS_BY_DISPOSITION.get(transition.disposition)
        if status is None:
            raise ValueError(
                f"owner transition has no narrative mapping: {transition.disposition}"
            )
        issued = self._monotonic_ns()
        speech_generation = self._speech_generation_provider()
        if isinstance(issued, bool) or not isinstance(issued, int) or issued < 0:
            raise RuntimeError("monotonic clock returned an invalid value")
        if (
            isinstance(speech_generation, bool)
            or not isinstance(speech_generation, int)
            or speech_generation < 0
        ):
            raise RuntimeError("speech generation provider returned an invalid value")
        return build_execution_narrative_event(
            event_sequence=transition.transition_sequence,
            task_id=transition.task_id,
            plan_revision=transition.plan_revision,
            step_id=transition.step_id,
            attempt=transition.attempt,
            action_name=transition.skill,
            plan_sha256=transition.plan_sha256,
            status=status,
            source_epoch=self._source_epoch,
            speech_generation=speech_generation,
            issued_at_monotonic_ns=issued,
            claimable_until_monotonic_ns=issued + self._event_ttl_ns,
            verified_facts=transition.verified_facts,
            evidence_refs=transition.evidence_refs,
            detail_code=transition.detail_code,
            resume_parent_task_id=self._resume_parents.get(transition.task_id),
        )


__all__ = [
    "ExecutiveJournalContinuityError",
    "NarratingTaskExecutiveV1",
    "NarrativeQueueStatusV1",
]
