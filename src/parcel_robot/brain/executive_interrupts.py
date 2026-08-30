"""Interrupt state-machine branches for the task executive.

The public executive resolves mutable voice policy and holds its lock before
entering this module.  Helpers therefore cannot make timing or policy choices
outside the original authority boundary.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any, TypeVar

DecisionT = TypeVar("DecisionT")
DecisionFactory = Callable[[str, tuple[str, ...], str], DecisionT]

_IMMEDIATE_SOURCES = frozenset({"emergency", "manual", "system_recovery", "explicit_stop"})
_DEFER_UNTIL_IDLE_SOURCES = frozenset({"social", "explicit_gesture"})


def handle_interrupt(
    owner: Any,
    request: Any,
    make_decision: DecisionFactory[DecisionT],
    *,
    terminal_states: frozenset[str],
    voice_policy_resolver: Callable[[str], str],
    goal_amend_predicate: Callable[[str], bool],
    goal_amend_forbidden_actions: frozenset[str],
    goal_amend_refused_action: str,
) -> DecisionT:
    """Apply one interrupt while the public wrapper holds ``owner._lock``."""

    records = [
        record
        for record in owner._ordered_records()
        if record.state not in terminal_states
        and (request.target_task_id is None or record.task_id == request.target_task_id)
    ]
    if not records:
        return make_decision("nothing_to_interrupt", (), request.reason)
    if request.source in _IMMEDIATE_SOURCES:
        return _cancel_records(owner, records, request.reason, make_decision)
    if request.source == "voice":
        policy = voice_policy_resolver(request.reason)
        refusal = (
            goal_amend_refused_action
            if policy in goal_amend_forbidden_actions and goal_amend_predicate(request.reason)
            else None
        )
        return _handle_voice(
            owner,
            records,
            request.reason,
            policy,
            refusal,
            make_decision,
        )
    if request.source in _DEFER_UNTIL_IDLE_SOURCES:
        affected = tuple(record.task_id for record in records)
        return make_decision("defer_when_idle", affected, request.reason)
    return _handle_deferred(owner, records, request, make_decision)


def _cancel_records(
    owner: Any,
    records: Iterable[Any],
    reason: str,
    make_decision: DecisionFactory[DecisionT],
) -> DecisionT:
    materialized = tuple(records)
    affected = tuple(record.task_id for record in materialized)
    for record in materialized:
        step = record.current_step
        if step is None:
            raise RuntimeError("interrupt target has no current step")
        prior_state = record.state
        prior_attempt = record.attempt
        owner._cancel(record, reason)
        owner._append_transition(
            record,
            step,
            attempt=prior_attempt,
            family="interruption",
            prior_state=prior_state,
            disposition="interrupt_cancelled",
            detail_code=f"interrupt_cancelled:{reason}"[:120],
        )
    return make_decision("cancel_now", affected, reason)


def _suspend_records(
    owner: Any,
    records: Iterable[Any],
    reason: str,
    make_decision: DecisionFactory[DecisionT],
) -> DecisionT:
    materialized = tuple(records)
    affected = tuple(record.task_id for record in materialized)
    for record in materialized:
        step = record.current_step
        if step is None:
            raise RuntimeError("suspend target has no current step")
        prior_state = record.state
        prior_attempt = record.attempt
        owner._suspend(record, reason)
        if record.state != prior_state:
            owner._append_transition(
                record,
                step,
                attempt=prior_attempt,
                family="interruption",
                prior_state=prior_state,
                disposition="interrupt_suspended",
                detail_code=f"interrupt_suspended:{reason}"[:120],
            )
    return make_decision("suspend", affected, reason)


def _handle_voice(
    owner: Any,
    records: list[Any],
    reason: str,
    policy: str | None,
    goal_amend_refusal: str | None,
    make_decision: DecisionFactory[DecisionT],
) -> DecisionT:
    if goal_amend_refusal is not None:
        return make_decision(goal_amend_refusal, (), reason)
    if policy == "overlap":
        return make_decision("overlap", (), reason)
    if policy == "suspend":
        return _suspend_records(owner, records, reason, make_decision)
    if policy == "cancel_now":
        return _cancel_records(owner, records, reason, make_decision)
    return make_decision("overlap", (), reason)


def _handle_deferred(
    owner: Any,
    records: list[Any],
    request: Any,
    make_decision: DecisionFactory[DecisionT],
) -> DecisionT:
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
            if step is None:
                raise RuntimeError("interrupt target has no current step")
            prior_state = record.state
            prior_attempt = record.attempt
            owner._cancel(record, request.reason)
            owner._append_transition(
                record,
                step,
                attempt=prior_attempt,
                family="interruption",
                prior_state=prior_state,
                disposition="interrupt_cancelled",
                detail_code=f"interrupt_cancelled:{request.reason}"[:120],
            )
        else:
            assert step is not None
            prior_state = record.state
            prior_pending = record.pending_interrupt
            record.pending_interrupt = request
            record.state = "waiting_checkpoint"
            record.last_detail = "interrupt_waiting_for_checkpoint"
            if prior_state != record.state or prior_pending != request:
                owner._append_transition(
                    record,
                    step,
                    attempt=record.attempt,
                    family="interruption",
                    prior_state=prior_state,
                    disposition="interrupt_waiting_checkpoint",
                    detail_code="interrupt_waiting_for_checkpoint",
                )
        affected.append(record.task_id)
    if deferred_until_idle and not affected:
        return make_decision(
            "defer_when_idle", tuple(record.task_id for record in records), request.reason
        )
    return make_decision("defer_to_checkpoint", tuple(affected), request.reason)
