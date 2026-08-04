"""Deterministic task state, resource locking, and interruption policy."""

from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass, field

from .contracts import (
    RESOURCES,
    ExecutionResult,
    FrozenDict,
    ObservationSnapshot,
    ResourceLease,
    SuccessCondition,
)
from .validator import ValidatedPlan, ValidatedStep

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
# Declared voice interrupt policy (was a hardcoded no-op / overlap).
# Keys are reason prefixes or exact reasons; default is overlap.
VOICE_INTERRUPT_POLICY: dict[str, str] = {
    "default": "overlap",
    "ambient": "overlap",
    "summons": "suspend",
    "recall": "suspend",
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
    ):
        if isinstance(max_records, bool) or not 1 <= max_records <= 10_000:
            raise ValueError("max_records must be an integer between 1 and 10000")
        self.resources = resources or ResourceLocks()
        self.max_records = max_records
        self._tasks: dict[str, _TaskRecord] = {}
        self._sequence = 0
        self._lock = threading.RLock()

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
            self._tasks[plan.task_id] = _TaskRecord(
                validated=validated,
                task_class=task_class,
                sequence=self._sequence,
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
                return ExecutiveSubmission(
                    True,
                    "defer",
                    plan.task_id,
                    plan.plan_revision,
                    reason,
                )
            self._activate_replacement(record, validated)
            return ExecutiveSubmission(
                True,
                "queued",
                plan.task_id,
                plan.plan_revision,
                "replacement activated",
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
            for record in self._ordered_records():
                if record.state in {"running", "waiting_checkpoint"}:
                    step = record.current_step
                    if (
                        step is not None
                        and record.step_started_at is not None
                        and timestamp - record.step_started_at >= step.step.timeout_s
                    ):
                        self.resources.release(record.task_id, step.step.step_id)
                        self._fail_or_retry(record, "step_timeout")

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
                    record.state = "succeeded"
                    record.at_checkpoint = True
                    record.last_detail = "all_steps_completed"
                    continue
                if not _preconditions_satisfied(step, record.validated, snapshot):
                    record.state = "waiting_precondition"
                    record.last_detail = "preconditions_not_satisfied"
                    continue
                acquired, conflicts = self.resources.acquire(
                    record.task_id,
                    step.step.step_id,
                    step.effective_resources,
                )
                if not acquired:
                    record.state = "waiting_resource"
                    record.conflicts = conflicts
                    record.last_detail = "resources_unavailable"
                    continue
                recovery = record.pending_recovery
                record.pending_recovery = None
                record.conflicts = ()
                record.state = "running"
                record.at_checkpoint = False
                record.step_started_at = timestamp
                record.last_detail = "dispatched"
                return (
                    DispatchRequest(
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
                    ),
                )
        return ()

    def report(self, result: ExecutionResult) -> ReportDisposition:
        """Consume typed feedback; stale plan revisions are ignored."""

        with self._lock:
            record = self._tasks.get(result.task_id)
            if record is None:
                return ReportDisposition(False, "ignored_unknown_task", result.task_id, "idle")
            step = record.current_step
            if (
                step is None
                or result.plan_revision != record.plan_revision
                or result.step_id != step.step.step_id
                or result.attempt != record.attempt
                or record.state not in {"running", "waiting_checkpoint"}
            ):
                return ReportDisposition(
                    False, "ignored_stale_result", result.task_id, record.state
                )

            if result.status == "in_progress":
                record.at_checkpoint = result.checkpoint
                record.last_detail = result.detail_code
                if (
                    result.checkpoint
                    and record.pending_replacement is not None
                    and step.effective_interruptibility != "never"
                ):
                    replacement = record.pending_replacement
                    self._activate_replacement(record, replacement)
                    return ReportDisposition(
                        True, "replacement_activated_at_checkpoint", result.task_id, record.state
                    )
                if result.checkpoint and record.pending_interrupt is not None:
                    self._cancel(record, record.pending_interrupt.reason)
                    return ReportDisposition(
                        True, "cancelled_at_checkpoint", result.task_id, record.state
                    )
                return ReportDisposition(True, "progress_recorded", result.task_id, record.state)

            self.resources.release(record.task_id, step.step.step_id)
            record.step_started_at = None
            record.at_checkpoint = True
            record.last_detail = result.detail_code
            if record.pending_replacement is not None:
                replacement = record.pending_replacement
                self._activate_replacement(record, replacement)
                return ReportDisposition(
                    True,
                    "replacement_activated_after_step",
                    result.task_id,
                    record.state,
                )
            if record.pending_interrupt is not None:
                self._cancel(record, record.pending_interrupt.reason)
                return ReportDisposition(
                    True,
                    "cancelled_after_step",
                    result.task_id,
                    record.state,
                )
            if result.status == "succeeded" and not _result_satisfies_success(result, step):
                self._fail_or_retry(record, "success_condition_not_verified")
                action = "retry_scheduled" if record.state == "recovering" else "task_failed"
                return ReportDisposition(True, action, result.task_id, record.state)
            if result.status == "succeeded":
                record.step_index += 1
                record.attempt = 1
                if record.step_index >= len(record.validated.steps):
                    record.state = "succeeded"
                    return ReportDisposition(True, "task_succeeded", result.task_id, record.state)
                record.state = "queued"
                return ReportDisposition(True, "step_succeeded", result.task_id, record.state)
            if result.status == "cancelled":
                self._cancel(record, result.detail_code)
                return ReportDisposition(True, "task_cancelled", result.task_id, record.state)
            self._fail_or_retry(record, result.feedback_code)
            action = "retry_scheduled" if record.state == "recovering" else "task_failed"
            return ReportDisposition(True, action, result.task_id, record.state)

    def dispatch_failed(
        self,
        request: DispatchRequest,
        detail: str,
    ) -> ReportDisposition:
        """Release every resource if an adapter raises before typed feedback."""

        with self._lock:
            record = self._tasks.get(request.task_id)
            if (
                record is None
                or record.plan_revision != request.plan_revision
                or record.attempt != request.attempt
                or record.current_step is None
                or record.current_step.step.step_id != request.step_id
            ):
                return ReportDisposition(False, "ignored_stale_dispatch", request.task_id, "idle")
            self.resources.release(request.task_id, request.step_id)
            record.step_started_at = None
            record.at_checkpoint = True
            self._fail_or_retry(record, f"dispatch_failed:{detail[:80]}")
            action = "retry_scheduled" if record.state == "recovering" else "task_failed"
            return ReportDisposition(True, action, request.task_id, record.state)

    def request_interrupt(self, request: InterruptRequest) -> InterruptDecision:
        """Apply system priority; model-requested timing is never authoritative."""

        with self._lock:
            records = [
                record
                for record in self._ordered_records()
                if record.state not in TERMINAL_TASK_STATES
                and (request.target_task_id is None or record.task_id == request.target_task_id)
            ]
            if not records:
                return InterruptDecision("nothing_to_interrupt", (), request.reason)
            if request.source in {
                "emergency",
                "manual",
                "system_recovery",
                "explicit_stop",
            }:
                affected = tuple(record.task_id for record in records)
                for record in records:
                    self._cancel(record, request.reason)
                return InterruptDecision("cancel_now", affected, request.reason)
            if request.source == "voice":
                policy = _voice_interrupt_action(request.reason)
                if policy == "overlap":
                    return InterruptDecision("overlap", (), request.reason)
                if policy == "suspend":
                    affected = tuple(record.task_id for record in records)
                    for record in records:
                        self._suspend(record, request.reason)
                    return InterruptDecision("suspend", affected, request.reason)
                if policy == "cancel_now":
                    affected = tuple(record.task_id for record in records)
                    for record in records:
                        self._cancel(record, request.reason)
                    return InterruptDecision("cancel_now", affected, request.reason)
                return InterruptDecision("overlap", (), request.reason)
            if request.source in {"social", "explicit_gesture"}:
                return InterruptDecision(
                    "defer_when_idle", tuple(record.task_id for record in records), request.reason
                )

            affected: list[str] = []
            deferred_until_idle = False
            for record in records:
                step = record.current_step
                if (
                    step is not None
                    and step.effective_interruptibility == "never"
                    and record.state in {"running", "waiting_checkpoint"}
                ):
                    deferred_until_idle = True
                    continue
                if record.state not in {"running", "waiting_checkpoint"} or record.at_checkpoint:
                    self._cancel(record, request.reason)
                else:
                    record.pending_interrupt = request
                    record.state = "waiting_checkpoint"
                    record.last_detail = "interrupt_waiting_for_checkpoint"
                affected.append(record.task_id)
            if deferred_until_idle and not affected:
                return InterruptDecision(
                    "defer_when_idle",
                    tuple(record.task_id for record in records),
                    request.reason,
                )
            return InterruptDecision("defer_to_checkpoint", tuple(affected), request.reason)

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
                return ReportDisposition(
                    False, "ignored_not_suspended", task_id, record.state
                )
            record.state = "queued"
            record.at_checkpoint = True
            record.step_started_at = None
            record.last_detail = f"resumed:{reason[:140]}"
            return ReportDisposition(True, "task_resumed", task_id, record.state)

    def suspend_task(self, task_id: str, *, reason: str) -> ReportDisposition:
        with self._lock:
            record = self._tasks.get(task_id)
            if record is None:
                return ReportDisposition(False, "ignored_unknown_task", task_id, "idle")
            if record.state in TERMINAL_TASK_STATES:
                return ReportDisposition(
                    False, "ignored_terminal_task", task_id, record.state
                )
            self._suspend(record, reason)
            return ReportDisposition(True, "task_suspended", task_id, record.state)

    def _activate_replacement(
        self,
        record: _TaskRecord,
        replacement: ValidatedPlan,
    ) -> None:
        self.resources.release(record.task_id)
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


def _result_satisfies_success(result: ExecutionResult, step: ValidatedStep) -> bool:
    expected = step.step.success
    for fact in result.verified_facts:
        if fact.fact != expected.fact:
            continue
        if expected.target is not None and (
            fact.target is None or _normalized(fact.target) != _normalized(expected.target)
        ):
            continue
        if expected.confidence_min is not None and fact.confidence < expected.confidence_min:
            continue
        return True
    return False


def _normalized(value: str) -> str:
    return "".join(character for character in value.lower() if character.isalnum())


def _voice_interrupt_action(reason: str) -> str:
    """Resolve the declared voice suspend-vs-overlap policy for a reason string."""

    clean = reason.strip().lower()
    if clean in VOICE_INTERRUPT_POLICY:
        return VOICE_INTERRUPT_POLICY[clean]
    for key, action in VOICE_INTERRUPT_POLICY.items():
        if key != "default" and key in clean:
            return action
    return VOICE_INTERRUPT_POLICY["default"]
