"""Deterministic task state, resource locking, and interruption policy."""

from __future__ import annotations

import math
import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass, field

from parcel_robot.revision import RevisionSink

from .contracts import (
    RESOURCES,
    ExecutionResult,
    FrozenDict,
    ObservationSnapshot,
    ResourceLease,
    SuccessCondition,
)
from .executive_interrupts import handle_interrupt as _handle_interrupt
from .executive_journal import (
    ExecutiveJournalReadV1 as _ExecutiveJournalReadV1,
)
from .executive_journal import (
    ExecutiveJournalStatusV1 as _ExecutiveJournalStatusV1,
)
from .executive_journal import (
    ExecutiveTransitionV1 as _ExecutiveTransitionV1,
)
from .executive_journal import (
    new_transition_journal as _new_transition_journal,
)
from .executive_journal import (
    read_transition_journal as _read_transition_journal_impl,
)
from .executive_journal import (
    transition_journal_status as _transition_journal_status_impl,
)
from .executive_reporting import (
    handle_dispatch_failed as _handle_dispatch_failed,
)
from .executive_reporting import (
    handle_report as _handle_report,
)
from .executive_reporting import (
    normalized as _normalized_impl,
)
from .executive_reporting import (
    result_satisfies_success as _result_satisfies_success_impl,
)
from .executive_revision_transaction import (
    ReplacementTransaction as _ReplacementTransaction,
)
from .executive_revision_transaction import (
    activate_replacement as _activate_replacement_impl,
)
from .executive_revision_transaction import (
    append_transition as _append_transition_transactional,
)
from .executive_revision_transaction import (
    report_with_rollback as _report_with_rollback,
)
from .executive_revision_transaction import (
    validate_revision_sink as _validate_revision_sink,
)
from .validator import ValidatedPlan, ValidatedStep

ExecutiveJournalReadV1 = _ExecutiveJournalReadV1
ExecutiveJournalStatusV1 = _ExecutiveJournalStatusV1
ExecutiveTransitionV1 = _ExecutiveTransitionV1
_normalized = _normalized_impl
_result_satisfies_success = _result_satisfies_success_impl

TERMINAL_TASK_STATES = frozenset({"succeeded", "failed", "cancelled"})
# Suspended is a status, never an outcome — must not replan/abandon.
NON_OUTCOME_TASK_STATES = frozenset({"suspended"})
TASK_CLASSES = frozenset({"system", "active_task", "explicit_action", "voice", "social"})
TASK_CLASS_PRIORITY = {
    "social": 10,
    "voice": 20,
    "explicit_action": 30,
    "active_task": 40,
    "system": 50,
}
INTERRUPT_SOURCES = frozenset(
    {
        "emergency",
        "manual",
        "system_recovery",
        "explicit_stop",
        "correction",
        "explicit_gesture",
        "social",
        "voice",
    }
)
#: The reason the closed-intent PAUSE cap suspends work under, and the one the
#: RESUME cap restores it under. Declared here because three parties must agree
#: on the pause string or the pair silently stops matching: the interrupt policy
#: below (which must map it to ``suspend``, not ``cancel``), the runtime branch
#: that issues it, and the runtime branch that looks for tasks parked by it.
CLOSED_INTENT_PAUSE_REASON = "closed_intent_pause"
CLOSED_INTENT_RESUME_REASON = "closed_intent_resume"
#: The reason a mid-task GOAL AMENDMENT suspends work under. It had no entry in
#: the policy below, so it resolved to the ``default`` (``overlap``) and the
#: executive answered an amendment with "carry on" — an executive-only task kept
#: running while its own goal was being revised. The word is duplicated from
#: ``voice.amendment.AMEND_SUSPEND_REASON`` (``brain`` must not import
#: ``voice``); ``tests/test_a5_goal_amend.py`` asserts the two are one string.
GOAL_AMEND_SUSPEND_REASON = "goal_amend"
#: Decisions a goal amendment may NEVER take. Amendment revises the *current*
#: goal, so ``cancel_now`` destroys the very thing being amended: it is excluded
#: from the acceptable decision set whatever the table below says, and the
#: exclusion is a refusal rather than a silent downgrade so the caller — which
#: must fail closed and roll back — can see that nothing was suspended.
GOAL_AMEND_FORBIDDEN_ACTIONS = frozenset({"cancel_now"})
GOAL_AMEND_REFUSED_ACTION = "refused_goal_amend_cancel"
# Declared voice interrupt policy (was a hardcoded no-op / overlap).
# Keys are reason prefixes or exact reasons; default is overlap.
VOICE_INTERRUPT_POLICY: dict[str, str] = {
    "default": "overlap",
    "ambient": "overlap",
    "summons": "suspend",
    "recall": "suspend",
    CLOSED_INTENT_PAUSE_REASON: "suspend",
    GOAL_AMEND_SUSPEND_REASON: "suspend",
    "explicit_directive": "cancel_now",
}


@dataclass(frozen=True, slots=True)
class _ResourceOwner:
    task_id: str
    step_id: str


class ResourceLocks:
    """Atomically acquire the four system-owned semantic resources."""

    def __init__(self):
        self._owners: dict[str, _ResourceOwner] = {}
        self._lock = threading.RLock()

    def acquire(
        self,
        task_id: str,
        step_id: str,
        resources: tuple[str, ...],
    ) -> tuple[bool, tuple[ResourceLease, ...]]:
        requested = tuple(dict.fromkeys(resources))
        if len(requested) != len(resources) or any(item not in RESOURCES for item in requested):
            raise ValueError("resources must be unique members of the Parcel resource set")
        owner = _ResourceOwner(task_id, step_id)
        with self._lock:
            conflicts = tuple(
                ResourceLease(resource, current.task_id, current.step_id)
                for resource in requested
                if (current := self._owners.get(resource)) is not None and current != owner
            )
            if conflicts:
                return False, conflicts
            for resource in requested:
                self._owners[resource] = owner
            return True, ()

    def release(self, task_id: str, step_id: str | None = None) -> None:
        with self._lock:
            for resource, owner in tuple(self._owners.items()):
                if owner.task_id == task_id and (step_id is None or owner.step_id == step_id):
                    del self._owners[resource]

    def leases(self) -> tuple[ResourceLease, ...]:
        with self._lock:
            return tuple(
                ResourceLease(resource, owner.task_id, owner.step_id)
                for resource, owner in sorted(self._owners.items())
            )

    def _checkpoint_owners(self) -> tuple[tuple[str, _ResourceOwner], ...]:
        """Snapshot executive-owned leases for an in-process transaction."""

        with self._lock:
            return tuple(self._owners.items())

    def _restore_owners(
        self,
        checkpoint: tuple[tuple[str, _ResourceOwner], ...],
    ) -> None:
        with self._lock:
            self._owners = dict(checkpoint)


@dataclass(frozen=True, slots=True)
class DispatchRequest:
    task_id: str
    plan_revision: int
    step_id: str
    attempt: int
    skill: str
    arguments: FrozenDict
    success: SuccessCondition
    resources: tuple[str, ...]
    timeout_s: float
    recovery_action: str | None = None


@dataclass(frozen=True, slots=True)
class ExecutiveSubmission:
    accepted: bool
    disposition: str
    task_id: str
    plan_revision: int
    reason: str


@dataclass(frozen=True, slots=True)
class InterruptRequest:
    source: str
    reason: str
    requested: str = "at_checkpoint"
    target_task_id: str | None = None

    def __post_init__(self) -> None:
        if self.source not in INTERRUPT_SOURCES:
            raise ValueError(f"unsupported interrupt source: {self.source}")
        if self.requested not in {"interrupt_now", "at_checkpoint", "when_idle"}:
            raise ValueError("interrupt request policy is not allowed")
        if not self.reason or len(self.reason) > 160:
            raise ValueError("interrupt reason must be short non-empty text")


@dataclass(frozen=True, slots=True)
class InterruptDecision:
    action: str
    affected_task_ids: tuple[str, ...]
    reason: str


@dataclass(frozen=True, slots=True)
class ReportDisposition:
    accepted: bool
    action: str
    task_id: str
    state: str


@dataclass(slots=True)
class _TaskRecord:
    validated: ValidatedPlan
    task_class: str
    sequence: int
    state: str = "queued"
    step_index: int = 0
    attempt: int = 1
    step_started_at: float | None = None
    at_checkpoint: bool = True
    pending_interrupt: InterruptRequest | None = None
    pending_replacement: ValidatedPlan | None = None
    pending_recovery: str | None = None
    last_detail: str = "accepted"
    conflicts: tuple[ResourceLease, ...] = field(default_factory=tuple)

    @property
    def task_id(self) -> str:
        return self.validated.plan.task_id

    @property
    def plan_revision(self) -> int:
        return self.validated.plan.plan_revision

    @property
    def current_step(self) -> ValidatedStep | None:
        if self.step_index >= len(self.validated.steps):
            return None
        return self.validated.steps[self.step_index]


class TaskExecutive:
    """A bounded state machine; it never calls a model or actuator.

    Runtime adapters consume :class:`DispatchRequest` values and return typed
    :class:`ExecutionResult` values.  The executive can therefore be tested
    without a simulator and cannot bypass the existing command arbiter.
    """

    def __init__(
        self,
        resources: ResourceLocks | None = None,
        *,
        max_records: int = 256,
        transition_capacity: int = 4096,
        revision_sinks: Sequence[RevisionSink] | None = None,
    ):
        if isinstance(max_records, bool) or not 1 <= max_records <= 10_000:
            raise ValueError("max_records must be an integer between 1 and 10000")
        if (
            isinstance(transition_capacity, bool)
            or not isinstance(transition_capacity, int)
            or not 1 <= transition_capacity <= 65_536
        ):
            raise ValueError("transition_capacity must be an integer between 1 and 65536")
        self.resources = resources or ResourceLocks()
        self.max_records = max_records
        self._tasks: dict[str, _TaskRecord] = {}
        self._sequence = 0
        self._lock = threading.RLock()
        self._executive_journal = _new_transition_journal(transition_capacity)
        self._replacement_transaction: _ReplacementTransaction | None = None
        # P0-C proposal-buffer flush: sinks (ProposerBus / GoalArbiter) are told
        # the committed plan_revision whenever a replacement activates, so a
        # correction atomically invalidates stale learned-goal proposals. Empty
        # by default -- an executive with no sinks behaves exactly as before.
        self._revision_sinks: list[RevisionSink] = []
        for sink in revision_sinks or ():
            self.register_revision_sink(sink)

    @property
    def authorizes_actuation(self) -> bool:
        return False

    transition_journal_status = _transition_journal_status_impl
    read_transition_journal = _read_transition_journal_impl
    _append_transition = _append_transition_transactional
    _activate_replacement = _activate_replacement_impl

    def register_revision_sink(self, sink: RevisionSink) -> None:
        """Bind a proposer buffer to this executive's committed revision.

        On every replacement activation the executive calls
        ``sink.commit_revision(task_id=..., plan_revision=...)`` so the buffer
        drops/rejects proposals authored under a superseded revision. Idempotent
        by object identity. Sinks must provide paired acquire/release and
        snapshot/restore hooks so navigation cannot observe a half-commit or
        lose a concurrent publish during compensation; opaque sinks are rejected.
        """

        if not callable(getattr(sink, "commit_revision", None)):
            raise TypeError("revision sink must expose a callable commit_revision")
        with self._lock:
            if any(existing is sink for existing in self._revision_sinks):
                return
            # A revision commit is a local transaction, not a best-effort event
            # fan-out. Refuse sinks whose state cannot be isolated and restored
            # if a later sink or the executive journal raises.
            _validate_revision_sink(sink)
            self._revision_sinks.append(sink)

    def submit(
        self,
        validated: ValidatedPlan,
        *,
        task_class: str = "active_task",
    ) -> ExecutiveSubmission:
        if task_class not in TASK_CLASSES:
            raise ValueError(f"unsupported task class: {task_class}")
        plan = validated.plan
        with self._lock:
            existing = self._tasks.get(plan.task_id)
            prior_state = existing.state if existing is not None else "absent"
            if existing is not None and existing.state not in TERMINAL_TASK_STATES:
                return ExecutiveSubmission(
                    False,
                    "reject",
                    plan.task_id,
                    plan.plan_revision,
                    "active task ID already exists; submit a higher revision via replace()",
                )
            if existing is None and len(self._tasks) >= self.max_records:
                self._prune_terminal_records(needed=1)
            if existing is None and len(self._tasks) >= self.max_records:
                return ExecutiveSubmission(
                    False,
                    "reject_capacity",
                    plan.task_id,
                    plan.plan_revision,
                    "executive capacity contains only non-terminal tasks",
                )
            self._sequence += 1
            record = _TaskRecord(
                validated=validated,
                task_class=task_class,
                sequence=self._sequence,
            )
            self._tasks[plan.task_id] = record
            step = record.current_step
            if step is None:  # PlanIR validation requires at least one step.
                raise RuntimeError("validated plan unexpectedly contains no executable step")
            self._append_transition(
                record,
                step,
                attempt=record.attempt,
                family="submission",
                prior_state=prior_state,
                disposition="task_queued",
                detail_code="validated_task_queued",
            )
            return ExecutiveSubmission(
                True,
                "queued",
                plan.task_id,
                plan.plan_revision,
                "validated task queued",
            )

    def replace(self, validated: ValidatedPlan) -> ExecutiveSubmission:
        """Replace one task with a strictly newer plan at a safe checkpoint."""

        plan = validated.plan
        with self._lock:
            record = self._tasks.get(plan.task_id)
            if record is None or record.state in TERMINAL_TASK_STATES:
                return self.submit(validated)
            if plan.plan_revision <= record.plan_revision:
                return ExecutiveSubmission(
                    False,
                    "reject",
                    plan.task_id,
                    plan.plan_revision,
                    "replacement revision must increase",
                )
            step = record.current_step
            if step is None:
                raise RuntimeError("active replacement target has no current step")
            prior_state = record.state
            interruptibility = step.effective_interruptibility if step is not None else "immediate"
            if record.state in {"running", "waiting_checkpoint"} and (
                not record.at_checkpoint or interruptibility == "never"
            ):
                record.pending_replacement = validated
                if interruptibility == "never":
                    record.last_detail = "replacement_waiting_until_step_finishes"
                    reason = "replacement deferred until non-interruptible step finishes"
                else:
                    record.pending_interrupt = InterruptRequest(
                        source="correction",
                        reason="accepted task correction",
                        requested="at_checkpoint",
                        target_task_id=plan.task_id,
                    )
                    record.state = "waiting_checkpoint"
                    record.last_detail = "replacement_waiting_for_checkpoint"
                    reason = "replacement deferred to the next task checkpoint"
                self._append_transition(
                    record,
                    step,
                    attempt=record.attempt,
                    family="replacement",
                    prior_state=prior_state,
                    disposition="replacement_deferred",
                    detail_code=record.last_detail[:120],
                )
                return ExecutiveSubmission(
                    True,
                    "defer",
                    plan.task_id,
                    plan.plan_revision,
                    reason,
                )
            self._activate_replacement(record, validated)
            replacement_step = record.current_step
            if replacement_step is None:
                raise RuntimeError("activated replacement has no executable step")
            self._append_transition(
                record,
                replacement_step,
                attempt=record.attempt,
                family="replacement",
                prior_state=prior_state,
                disposition="replacement_activated",
                detail_code="replacement_activated",
            )
            return ExecutiveSubmission(
                True,
                "queued",
                plan.task_id,
                plan.plan_revision,
                "replacement activated",
            )

    def _expire_timed_out_steps(self, timestamp: float) -> None:
        """Apply timeout transitions while the caller holds ``self._lock``."""

        for record in self._ordered_records():
            if record.state not in {"running", "waiting_checkpoint"}:
                continue
            step = record.current_step
            if (
                step is None
                or record.step_started_at is None
                or timestamp - record.step_started_at < step.step.timeout_s
            ):
                continue
            prior_state = record.state
            prior_attempt = record.attempt
            self.resources.release(record.task_id, step.step.step_id)
            self._fail_or_retry(record, "step_timeout")
            disposition = (
                "step_timeout_retry" if record.state == "recovering" else "step_timeout_failed"
            )
            self._append_transition(
                record,
                step,
                attempt=prior_attempt,
                family="tick",
                prior_state=prior_state,
                disposition=disposition,
                detail_code="step_timeout",
            )

    def tick(
        self,
        snapshot: ObservationSnapshot | None = None,
        *,
        now: float | None = None,
    ) -> tuple[DispatchRequest, ...]:
        """Advance bounded state and return at most one semantic dispatch."""

        timestamp = time.monotonic() if now is None else float(now)
        if not math.isfinite(timestamp):
            raise ValueError("executive time must be finite")
        with self._lock:
            self._expire_timed_out_steps(timestamp)
            for record in self._ordered_records():
                # suspended is a status (not an outcome): skip like running so
                # tick does not re-dispatch until resume_task re-queues it.
                if record.state in (
                    TERMINAL_TASK_STATES
                    | NON_OUTCOME_TASK_STATES
                    | {"running", "waiting_checkpoint"}
                ):
                    continue
                step = record.current_step
                if step is None:
                    # PlanIR requires at least one step and report() makes the
                    # final accepted success terminal in the same call.  This
                    # arm is a defensive invariant, not a constructible public
                    # transition in the validated state machine.
                    raise RuntimeError(
                        "non-terminal task has no executable step; empty tick completion "
                        "is not constructible"
                    )
                if not _preconditions_satisfied(step, record.validated, snapshot):
                    prior_state = record.state
                    record.state = "waiting_precondition"
                    record.last_detail = "preconditions_not_satisfied"
                    if prior_state != record.state:
                        self._append_transition(
                            record,
                            step,
                            attempt=record.attempt,
                            family="tick",
                            prior_state=prior_state,
                            disposition="waiting_precondition",
                            detail_code="preconditions_not_satisfied",
                        )
                    continue
                acquired, conflicts = self.resources.acquire(
                    record.task_id,
                    step.step.step_id,
                    step.effective_resources,
                )
                if not acquired:
                    prior_state = record.state
                    record.state = "waiting_resource"
                    record.conflicts = conflicts
                    record.last_detail = "resources_unavailable"
                    if prior_state != record.state:
                        self._append_transition(
                            record,
                            step,
                            attempt=record.attempt,
                            family="tick",
                            prior_state=prior_state,
                            disposition="waiting_resource",
                            detail_code="resources_unavailable",
                        )
                    continue
                recovery = record.pending_recovery
                prior_state = record.state
                record.pending_recovery = None
                record.conflicts = ()
                record.state = "running"
                record.at_checkpoint = False
                record.step_started_at = timestamp
                record.last_detail = "dispatched"
                self._append_transition(
                    record,
                    step,
                    attempt=record.attempt,
                    family="tick",
                    prior_state=prior_state,
                    disposition="step_dispatched",
                    detail_code="dispatch_returned",
                )
                return (self._dispatch_request(record, step, recovery),)
        return ()

    @staticmethod
    def _dispatch_request(
        record: _TaskRecord,
        step: ValidatedStep,
        recovery: str | None,
    ) -> DispatchRequest:
        """The one place a record + step becomes a dispatch (tick and resume)."""

        return DispatchRequest(
            task_id=record.task_id,
            plan_revision=record.plan_revision,
            step_id=step.step.step_id,
            attempt=record.attempt,
            skill=step.step.skill,
            arguments=step.step.arguments,
            success=step.step.success,
            resources=step.effective_resources,
            timeout_s=step.step.timeout_s,
            recovery_action=recovery,
        )

    def report(self, result: ExecutionResult) -> ReportDisposition:
        """Consume typed feedback; stale plan revisions are ignored."""

        with self._lock:
            return _report_with_rollback(
                self,
                result,
                _handle_report,
                ReportDisposition,
            )

    def dispatch_failed(
        self,
        request: DispatchRequest,
        detail: str,
    ) -> ReportDisposition:
        """Release every resource if an adapter raises before typed feedback."""

        with self._lock:
            return _handle_dispatch_failed(self, request, detail, ReportDisposition)

    def request_interrupt(self, request: InterruptRequest) -> InterruptDecision:
        """Apply system priority; model-requested timing is never authoritative."""

        with self._lock:
            return _handle_interrupt(
                self,
                request,
                InterruptDecision,
                terminal_states=TERMINAL_TASK_STATES,
                voice_policy_resolver=_voice_interrupt_action,
                goal_amend_predicate=_is_goal_amend_reason,
                goal_amend_forbidden_actions=GOAL_AMEND_FORBIDDEN_ACTIONS,
                goal_amend_refused_action=GOAL_AMEND_REFUSED_ACTION,
            )

    def cancel_all(self, reason: str) -> InterruptDecision:
        return self.request_interrupt(
            InterruptRequest(source="explicit_stop", reason=reason, requested="interrupt_now")
        )

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return {
                "tasks": [
                    {
                        "task_id": record.task_id,
                        "plan_revision": record.plan_revision,
                        "plan_sha256": record.validated.plan_sha256,
                        "task_class": record.task_class,
                        "state": record.state,
                        "step_id": (
                            record.current_step.step.step_id
                            if record.current_step is not None
                            else None
                        ),
                        # The current step's skill: the runtime needs it to know
                        # which channel a suspended task owns when it resumes.
                        "skill": (
                            record.current_step.step.skill
                            if record.current_step is not None
                            else None
                        ),
                        "step_index": record.step_index,
                        "attempt": record.attempt,
                        "at_checkpoint": record.at_checkpoint,
                        "pending_recovery": record.pending_recovery,
                        "pending_replacement_revision": (
                            record.pending_replacement.plan.plan_revision
                            if record.pending_replacement is not None
                            else None
                        ),
                        "last_detail": record.last_detail,
                        "resource_conflicts": [item.as_dict() for item in record.conflicts],
                    }
                    for record in self._ordered_records()
                ],
                "resource_leases": [item.as_dict() for item in self.resources.leases()],
            }

    def _ordered_records(self) -> list[_TaskRecord]:
        return sorted(
            self._tasks.values(),
            key=lambda item: (-TASK_CLASS_PRIORITY[item.task_class], item.sequence),
        )

    def _prune_terminal_records(self, *, needed: int) -> None:
        terminal = sorted(
            (record for record in self._tasks.values() if record.state in TERMINAL_TASK_STATES),
            key=lambda item: item.sequence,
        )
        target_size = self.max_records - needed
        for record in terminal:
            if len(self._tasks) <= target_size:
                break
            del self._tasks[record.task_id]

    def _fail_or_retry(self, record: _TaskRecord, detail: str) -> None:
        step = record.current_step
        if step is None:
            record.state = "failed"
            record.last_detail = detail
            return
        if record.attempt < step.step.max_attempts and step.step.recovery:
            recovery_index = min(record.attempt - 1, len(step.step.recovery) - 1)
            record.pending_recovery = step.step.recovery[recovery_index]
            record.attempt += 1
            record.state = "recovering"
            record.last_detail = detail
            return
        record.state = "failed"
        record.last_detail = detail
        record.at_checkpoint = True

    def _cancel(self, record: _TaskRecord, reason: str) -> None:
        self.resources.release(record.task_id)
        record.state = "cancelled"
        record.at_checkpoint = True
        record.step_started_at = None
        record.pending_interrupt = None
        record.pending_replacement = None
        record.pending_recovery = None
        record.last_detail = reason[:160]

    def _suspend(self, record: _TaskRecord, reason: str) -> None:
        """Park a task without succeeding or failing it."""

        if record.state in TERMINAL_TASK_STATES | NON_OUTCOME_TASK_STATES:
            return
        self.resources.release(record.task_id)
        record.state = "suspended"
        record.at_checkpoint = True
        record.step_started_at = None
        record.pending_interrupt = None
        record.pending_recovery = None
        record.last_detail = f"suspended:{reason[:140]}"

    def resume_task(self, task_id: str, *, reason: str = "resume") -> ReportDisposition:
        """Re-queue a suspended task for fresh dispatch (not an outcome transition)."""

        with self._lock:
            record = self._tasks.get(task_id)
            if record is None:
                return ReportDisposition(False, "ignored_unknown_task", task_id, "idle")
            if record.state != "suspended":
                return ReportDisposition(False, "ignored_not_suspended", task_id, record.state)
            step = record.current_step
            if step is None:
                return ReportDisposition(False, "ignored_no_current_step", task_id, record.state)
            prior_state = record.state
            prior_attempt = record.attempt
            record.state = "queued"
            record.at_checkpoint = True
            record.step_started_at = None
            record.last_detail = f"resumed:{reason[:140]}"
            self._append_transition(
                record,
                step,
                attempt=prior_attempt,
                family="explicit_lifecycle",
                prior_state=prior_state,
                disposition="task_resumed",
                detail_code=f"task_resumed:{reason}"[:120],
            )
            return ReportDisposition(True, "task_resumed", task_id, record.state)

    def resume_task_running(
        self,
        task_id: str,
        *,
        reason: str = "resume",
        now: float | None = None,
    ) -> tuple[ReportDisposition, DispatchRequest | None]:
        """Return a suspended task to ``running`` *without* re-dispatching it.

        :meth:`resume_task` re-queues, so the next :meth:`tick` dispatches the
        step again. That is right when the controller was torn down, and wrong
        when it was *paused* and has just been restored from its stored
        ``ResumeIntent``: a second dispatch cold-starts the mission and throws
        the restored state away. This is the other half of that pair — the step
        is already executing, so the record is re-bound to it (resources
        re-acquired, timeout clock restarted at ``now``) and the caller re-binds
        its own dispatch tracking with the returned request.

        Fail-closed: if the step's resources are held by someone else the task
        is left suspended and the disposition says why, because a ``running``
        record over an un-leased resource is a false claim of authority.
        """

        timestamp = time.monotonic() if now is None else float(now)
        if not math.isfinite(timestamp):
            raise ValueError("executive time must be finite")
        with self._lock:
            record = self._tasks.get(task_id)
            if record is None:
                return ReportDisposition(False, "ignored_unknown_task", task_id, "idle"), None
            if record.state != "suspended":
                return (
                    ReportDisposition(False, "ignored_not_suspended", task_id, record.state),
                    None,
                )
            step = record.current_step
            if step is None:
                return (
                    ReportDisposition(False, "ignored_no_current_step", task_id, record.state),
                    None,
                )
            prior_state = record.state
            prior_attempt = record.attempt
            acquired, conflicts = self.resources.acquire(
                record.task_id,
                step.step.step_id,
                step.effective_resources,
            )
            if not acquired:
                record.conflicts = conflicts
                return (
                    ReportDisposition(
                        False, "ignored_resources_unavailable", task_id, record.state
                    ),
                    None,
                )
            record.conflicts = ()
            record.state = "running"
            record.at_checkpoint = False
            record.step_started_at = timestamp
            record.last_detail = f"resumed_running:{reason[:120]}"
            self._append_transition(
                record,
                step,
                attempt=prior_attempt,
                family="explicit_lifecycle",
                prior_state=prior_state,
                disposition="task_resumed_running",
                detail_code=f"task_resumed_running:{reason}"[:120],
            )
            return (
                ReportDisposition(True, "task_resumed_running", task_id, record.state),
                self._dispatch_request(record, step, None),
            )

    def suspend_task(self, task_id: str, *, reason: str) -> ReportDisposition:
        with self._lock:
            record = self._tasks.get(task_id)
            if record is None:
                return ReportDisposition(False, "ignored_unknown_task", task_id, "idle")
            if record.state in TERMINAL_TASK_STATES:
                return ReportDisposition(False, "ignored_terminal_task", task_id, record.state)
            step = record.current_step
            if step is None:
                return ReportDisposition(False, "ignored_no_current_step", task_id, record.state)
            prior_state = record.state
            prior_attempt = record.attempt
            self._suspend(record, reason)
            if record.state != prior_state:
                self._append_transition(
                    record,
                    step,
                    attempt=prior_attempt,
                    family="explicit_lifecycle",
                    prior_state=prior_state,
                    disposition="task_suspended",
                    detail_code=f"task_suspended:{reason}"[:120],
                )
            return ReportDisposition(True, "task_suspended", task_id, record.state)

def _preconditions_satisfied(
    step: ValidatedStep,
    plan: ValidatedPlan,
    snapshot: ObservationSnapshot | None,
) -> bool:
    conditions = frozenset(step.step.preconditions)
    if snapshot is not None and snapshot.safety.emergency_stopped:
        return False
    external = conditions - {
        "base_available",
        "posture_available",
        "voice_available",
        "attention_available",
    }
    if not external:
        return True
    if snapshot is None:
        return False
    if "camera_fresh" in external and not snapshot.camera.fresh:
        return False
    if "lidar_fresh" in external and not snapshot.lidar.fresh:
        return False
    if "robot_stopped" in external and snapshot.robot.moving:
        return False
    if "battery_critical" in external and snapshot.battery.state != "critical":
        return False
    if "owner_visible" in external and not any(
        item.kind == "owner" and item.confidence >= 0.6 for item in snapshot.entities
    ):
        return False
    if "owner_heading_available" in external and not any(
        item.kind == "owner"
        and item.confidence >= 0.6
        and item.attributes.get("motion_heading_available") is True
        for item in snapshot.entities
    ):
        return False
    if "target_grounded" in external:
        target = step.step.success.target or plan.plan.goal.target.query
        if not target or not snapshot.matching_entities(target):
            return False
    return "safe_region_grounded" not in external or any(
        item.kind == "semantic_region"
        and item.label.lower() in {"sidewalk", "pavement", "safe region"}
        and item.confidence >= 0.6
        for item in snapshot.entities
    )


def _is_goal_amend_reason(reason: str) -> bool:
    """True when ``reason`` names a mid-task goal amendment."""

    return GOAL_AMEND_SUSPEND_REASON in reason.strip().lower()


def _voice_interrupt_action(reason: str) -> str:
    """Resolve the declared voice suspend-vs-overlap policy for a reason string."""

    clean = reason.strip().lower()
    if clean in VOICE_INTERRUPT_POLICY:
        return VOICE_INTERRUPT_POLICY[clean]
    for key, action in VOICE_INTERRUPT_POLICY.items():
        if key != "default" and key in clean:
            return action
    return VOICE_INTERRUPT_POLICY["default"]
