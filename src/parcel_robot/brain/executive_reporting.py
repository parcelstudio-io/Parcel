"""Typed execution-feedback transitions for :mod:`parcel_robot.brain.executive`.

The public executive keeps the lock for an entire call.  These helpers only
factor the deterministic branches so feedback handling remains auditable and
no helper can be mistaken for an independent authority owner.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

from .contracts import ExecutionResult
from .validator import ValidatedStep

DispositionT = TypeVar("DispositionT")
DispositionFactory = Callable[[bool, str, str, str], DispositionT]


def handle_report(
    owner: Any,
    result: ExecutionResult,
    make_disposition: DispositionFactory[DispositionT],
) -> DispositionT:
    """Consume one result while ``owner._lock`` is held by the public wrapper."""

    record = owner._tasks.get(result.task_id)
    if record is None:
        return make_disposition(False, "ignored_unknown_task", result.task_id, "idle")
    step = record.current_step
    if (
        step is None
        or result.plan_revision != record.plan_revision
        or result.step_id != step.step.step_id
        or result.attempt != record.attempt
        or record.state not in {"running", "waiting_checkpoint"}
    ):
        return make_disposition(False, "ignored_stale_result", result.task_id, record.state)

    prior_state = record.state
    prior_attempt = record.attempt
    evidence_refs = (result.snapshot_id,) if result.snapshot_id is not None else ()
    if result.status == "in_progress":
        return _handle_progress(
            owner,
            record,
            step,
            result,
            prior_state,
            prior_attempt,
            evidence_refs,
            make_disposition,
        )
    pending = _settle_step_and_apply_pending(
        owner,
        record,
        step,
        result,
        prior_state,
        prior_attempt,
        evidence_refs,
        make_disposition,
    )
    if pending is not None:
        return pending
    return _handle_terminal(
        owner,
        record,
        step,
        result,
        prior_state,
        prior_attempt,
        evidence_refs,
        make_disposition,
    )


def _handle_progress(
    owner: Any,
    record: Any,
    step: ValidatedStep,
    result: ExecutionResult,
    prior_state: str,
    prior_attempt: int,
    evidence_refs: tuple[str, ...],
    make_disposition: DispositionFactory[DispositionT],
) -> DispositionT:
    record.at_checkpoint = result.checkpoint
    record.last_detail = result.detail_code
    if (
        result.checkpoint
        and record.pending_replacement is not None
        and step.effective_interruptibility != "never"
    ):
        replacement = record.pending_replacement
        owner._activate_replacement(record, replacement)
        replacement_step = record.current_step
        if replacement_step is None:
            raise RuntimeError("checkpoint replacement has no executable step")
        owner._append_transition(
            record,
            replacement_step,
            attempt=record.attempt,
            family="replacement",
            prior_state=prior_state,
            disposition="replacement_activated_at_checkpoint",
            detail_code="replacement_activated_at_checkpoint",
        )
        return make_disposition(
            True, "replacement_activated_at_checkpoint", result.task_id, record.state
        )
    if result.checkpoint and record.pending_interrupt is not None:
        owner._cancel(record, record.pending_interrupt.reason)
        owner._append_transition(
            record,
            step,
            attempt=prior_attempt,
            family="report",
            prior_state=prior_state,
            disposition="cancelled_at_checkpoint",
            detail_code="cancelled_at_checkpoint",
            evidence_refs=evidence_refs,
        )
        return make_disposition(True, "cancelled_at_checkpoint", result.task_id, record.state)
    owner._append_transition(
        record,
        step,
        attempt=prior_attempt,
        family="report",
        prior_state=prior_state,
        disposition="progress_recorded",
        detail_code=f"progress_recorded:{result.detail_code}"[:120],
        verified_facts=result.verified_facts,
        evidence_refs=evidence_refs,
    )
    return make_disposition(True, "progress_recorded", result.task_id, record.state)


def _settle_step_and_apply_pending(
    owner: Any,
    record: Any,
    step: ValidatedStep,
    result: ExecutionResult,
    prior_state: str,
    prior_attempt: int,
    evidence_refs: tuple[str, ...],
    make_disposition: DispositionFactory[DispositionT],
) -> DispositionT | None:
    owner.resources.release(record.task_id, step.step.step_id)
    record.step_started_at = None
    record.at_checkpoint = True
    record.last_detail = result.detail_code
    if record.pending_replacement is not None:
        replacement = record.pending_replacement
        owner._activate_replacement(record, replacement)
        replacement_step = record.current_step
        if replacement_step is None:
            raise RuntimeError("after-step replacement has no executable step")
        owner._append_transition(
            record,
            replacement_step,
            attempt=record.attempt,
            family="replacement",
            prior_state=prior_state,
            disposition="replacement_activated_after_step",
            detail_code="replacement_activated_after_step",
        )
        return make_disposition(
            True, "replacement_activated_after_step", result.task_id, record.state
        )
    if record.pending_interrupt is None:
        return None
    owner._cancel(record, record.pending_interrupt.reason)
    owner._append_transition(
        record,
        step,
        attempt=prior_attempt,
        family="report",
        prior_state=prior_state,
        disposition="cancelled_after_step",
        detail_code="cancelled_after_step",
        evidence_refs=evidence_refs,
    )
    return make_disposition(True, "cancelled_after_step", result.task_id, record.state)


def _handle_terminal(
    owner: Any,
    record: Any,
    step: ValidatedStep,
    result: ExecutionResult,
    prior_state: str,
    prior_attempt: int,
    evidence_refs: tuple[str, ...],
    make_disposition: DispositionFactory[DispositionT],
) -> DispositionT:
    if result.status == "succeeded" and not result_satisfies_success(result, step):
        owner._fail_or_retry(record, "success_condition_not_verified")
        action = "retry_scheduled" if record.state == "recovering" else "task_failed"
        owner._append_transition(
            record,
            step,
            attempt=prior_attempt,
            family="report",
            prior_state=prior_state,
            disposition=action,
            detail_code="unverified_success_claim",
            evidence_refs=evidence_refs,
        )
        return make_disposition(True, action, result.task_id, record.state)
    if result.status == "succeeded":
        return _handle_verified_success(
            owner,
            record,
            step,
            result,
            prior_state,
            prior_attempt,
            evidence_refs,
            make_disposition,
        )
    if result.status == "cancelled":
        owner._cancel(record, result.detail_code)
        owner._append_transition(
            record,
            step,
            attempt=prior_attempt,
            family="report",
            prior_state=prior_state,
            disposition="task_cancelled",
            detail_code=f"task_cancelled:{result.detail_code}"[:120],
            evidence_refs=evidence_refs,
        )
        return make_disposition(True, "task_cancelled", result.task_id, record.state)
    detail = result.detail_code or result.feedback_code
    owner._fail_or_retry(record, detail)
    action = "retry_scheduled" if record.state == "recovering" else "task_failed"
    owner._append_transition(
        record,
        step,
        attempt=prior_attempt,
        family="report",
        prior_state=prior_state,
        disposition=action,
        detail_code=f"{action}:{detail}"[:120],
        evidence_refs=evidence_refs,
    )
    return make_disposition(True, action, result.task_id, record.state)


def _handle_verified_success(
    owner: Any,
    record: Any,
    step: ValidatedStep,
    result: ExecutionResult,
    prior_state: str,
    prior_attempt: int,
    evidence_refs: tuple[str, ...],
    make_disposition: DispositionFactory[DispositionT],
) -> DispositionT:
    record.step_index += 1
    record.attempt = 1
    terminal = record.step_index >= len(record.validated.steps)
    record.state = "succeeded" if terminal else "queued"
    action = "task_succeeded" if terminal else "step_succeeded"
    owner._append_transition(
        record,
        step,
        attempt=prior_attempt,
        family="report",
        prior_state=prior_state,
        disposition=action,
        detail_code=f"{action}:{result.detail_code}"[:120],
        verified_facts=result.verified_facts,
        evidence_refs=evidence_refs,
    )
    return make_disposition(True, action, result.task_id, record.state)


def handle_dispatch_failed(
    owner: Any,
    request: Any,
    detail: str,
    make_disposition: DispositionFactory[DispositionT],
) -> DispositionT:
    """Release resources when an adapter fails before typed feedback."""

    record = owner._tasks.get(request.task_id)
    if (
        record is None
        or record.plan_revision != request.plan_revision
        or record.attempt != request.attempt
        or record.current_step is None
        or record.current_step.step.step_id != request.step_id
        or record.state not in {"running", "waiting_checkpoint"}
    ):
        return make_disposition(False, "ignored_stale_dispatch", request.task_id, "idle")
    step = record.current_step
    assert step is not None
    prior_state = record.state
    prior_attempt = record.attempt
    owner.resources.release(request.task_id, request.step_id)
    record.step_started_at = None
    record.at_checkpoint = True
    owner._fail_or_retry(record, f"dispatch_failed:{detail[:80]}")
    action = "retry_scheduled" if record.state == "recovering" else "task_failed"
    owner._append_transition(
        record,
        step,
        attempt=prior_attempt,
        family="dispatch_failure",
        prior_state=prior_state,
        disposition=action,
        detail_code=f"{action}:dispatch_failed:{detail[:72]}"[:120],
    )
    return make_disposition(True, action, request.task_id, record.state)


def result_satisfies_success(result: ExecutionResult, step: ValidatedStep) -> bool:
    expected = step.step.success
    for fact in result.verified_facts:
        if fact.fact != expected.fact:
            continue
        if expected.target is not None and (
            fact.target is None or normalized(fact.target) != normalized(expected.target)
        ):
            continue
        if expected.confidence_min is not None and fact.confidence < expected.confidence_min:
            continue
        return True
    return False


def normalized(value: str) -> str:
    return "".join(character for character in value.lower() if character.isalnum())
