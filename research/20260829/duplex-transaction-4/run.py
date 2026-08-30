#!/usr/bin/env python
"""Fresh-process DMC-4 journal, bridge, corruption, and concurrency harness."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import resource
import threading
from dataclasses import replace
from pathlib import Path
from typing import Any

from parcel_robot.brain.contracts import (
    BatteryStateSnapshot,
    ExecutionResult,
    GoalSpec,
    GoalTarget,
    ObservationSnapshot,
    PlanIR,
    PlanStep,
    RobotStateSnapshot,
    SafetyStateSnapshot,
    SensorSnapshot,
    SuccessCondition,
    TaskStateSnapshot,
    VerifiedFact,
)
from parcel_robot.brain.execution_narrative_bridge import (
    ExecutiveJournalContinuityError,
    NarratingTaskExecutiveV1,
)
from parcel_robot.brain.executive import InterruptRequest, ResourceLocks, TaskExecutive
from parcel_robot.brain.validator import PlanValidator, SkillContractRegistry
from parcel_robot.contracts.execution_narrative_v1 import build_execution_narrative_event
from parcel_robot.voice.execution_narrative import (
    AuthenticatedExecutionNarrativeEventV1,
    NarrativeConsumerStateV1,
    TrustedExecutionNarrativeAuthenticatorV1,
    consume_execution_narrative_event,
)


HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]
MANIFEST_PATH = HERE / "manifest.json"
SOURCE_MANIFEST_PATH = HERE / "source_manifest.json"
AUTH = TrustedExecutionNarrativeAuthenticatorV1(
    authenticator_id="dmc4_frozen_journal",
    key=b"dmc4-frozen-process-local-key-20260829",
)


def canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")


def digest(value: object) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def file_sha256(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            value.update(block)
    return value.hexdigest()


def token(namespace: str, trial: int, field: str, length: int = 24) -> str:
    return hashlib.sha256(
        f"20260829:dmc4:{namespace}:{trial}:{field}".encode("ascii")
    ).hexdigest()[:length]


def _now_ns(namespace: str, trial: int) -> int:
    offset = int(token(namespace, trial, "clock", 8), 16) % 10_000_000
    return 4_000_000_000_000 + trial * 100_000_000 + offset


def _snapshot(*, critical: bool = False) -> ObservationSnapshot:
    return ObservationSnapshot(
        schema_version=1,
        snapshot_id="snapshot-dmc4",
        captured_at_monotonic_s=10.0,
        camera=SensorSnapshot("camera", True, True, "camera", 9.9, 100.0),
        lidar=SensorSnapshot("lidar", True, True, "lidar", 9.9, 50.0),
        robot=RobotStateSnapshot(False, "stand"),
        safety=SafetyStateSnapshot(False, False, True),
        battery=BatteryStateSnapshot(
            "critical" if critical else "normal",
            5.0 if critical else 80.0,
            "unitree",
        ),
        task=TaskStateSnapshot(),
    )


def _hold_plan(
    namespace: str,
    trial: int,
    *,
    revision: int = 1,
    attempts: int = 1,
    interruptibility: str = "checkpoint",
    steps: int = 1,
    suffix: str = "task",
) -> PlanIR:
    task_id = f"task-{token(namespace, trial, suffix)}"
    return PlanIR(
        schema_version=1,
        task_id=task_id,
        plan_revision=revision,
        source_turn_id=f"turn-{token(namespace, trial, f'{suffix}-{revision}')}",
        goal=GoalSpec("hold", GoalTarget("current_pose"), 0.0),
        invariants=(),
        steps=tuple(
            PlanStep(
                f"step-{token(namespace, trial, f'{suffix}-step-{index}')}",
                "Hold",
                {},
                ("base_available",),
                SuccessCondition("motion_stopped"),
                5.0,
                attempts,
                ("safe_stop",) if attempts > 1 else (),
                ("base",),
                interruptibility,
            )
            for index in range(steps)
        ),
    )


def _critical_plan(
    namespace: str,
    trial: int,
    *,
    revision: int = 1,
    suffix: str = "critical",
) -> PlanIR:
    task_id = f"task-{token(namespace, trial, suffix)}"
    return PlanIR(
        schema_version=1,
        task_id=task_id,
        plan_revision=revision,
        source_turn_id=f"turn-{token(namespace, trial, f'{suffix}-{revision}')}",
        goal=GoalSpec("safe_pose", GoalTarget("safe_region", "safe region"), 0.5),
        invariants=("do_not_interrupt_critical_task",),
        steps=(
            PlanStep(
                f"step-{token(namespace, trial, f'{suffix}-safe')}",
                "ReturnToSafePose",
                {"pose": "sit"},
                (
                    "camera_fresh",
                    "lidar_fresh",
                    "base_available",
                    "posture_available",
                    "battery_critical",
                ),
                SuccessCondition("safe_pose"),
                30.0,
                1,
                (),
                ("base", "posture", "attention"),
                "never",
            ),
        ),
    )


def _validated(plan: PlanIR, *, critical: bool = False):
    registry = SkillContractRegistry.default(pose_names=("sit",))
    return PlanValidator(registry).validate(plan, _snapshot(critical=critical))


def _result(
    request: Any,
    namespace: str,
    trial: int,
    status: str,
    *,
    checkpoint: bool = True,
    verified: bool = True,
) -> ExecutionResult:
    terminal = status != "in_progress"
    fact = (
        VerifiedFact("safe_pose", None, "controller", 1.0)
        if request.skill == "ReturnToSafePose"
        else VerifiedFact("motion_stopped", None, "controller", 1.0)
    )
    return ExecutionResult(
        schema_version=1,
        task_id=request.task_id,
        plan_revision=request.plan_revision,
        step_id=request.step_id,
        attempt=request.attempt,
        status=status,
        feedback_code=status,
        snapshot_id=f"snapshot-{token(namespace, trial, f'{request.step_id}-{status}')}",
        verified_facts=((fact,) if status == "succeeded" and verified else ()),
        checkpoint=checkpoint,
        detail_code=f"result_{status}",
        started_at_monotonic_s=1000.0 + trial,
        finished_at_monotonic_s=1000.1 + trial if terminal else None,
    )


def _bridge(
    manifest: dict[str, object],
    namespace: str,
    trial: int,
    *,
    executive: TaskExecutive | None = None,
    event_capacity: int = 256,
) -> tuple[TaskExecutive, NarratingTaskExecutiveV1]:
    owner = executive or TaskExecutive(transition_capacity=256)
    bridge = NarratingTaskExecutiveV1(
        owner,
        authenticator=AUTH,
        source_epoch=int(manifest["source_epoch"]),
        speech_generation_provider=lambda: int(manifest["speech_generation"]),
        monotonic_ns=lambda: _now_ns(namespace, trial),
        event_ttl_ns=int(manifest["event_ttl_ns"]),
        event_capacity=event_capacity,
    )
    return owner, bridge


def _expect(
    ledger: list[dict[str, object]],
    validated: Any,
    *,
    step_index: int,
    attempt: int,
    family: str,
    prior_state: str,
    resulting_state: str,
    disposition: str,
    detail_code: str,
    facts: tuple[VerifiedFact, ...] = (),
    evidence_refs: tuple[str, ...] = (),
) -> None:
    step = validated.steps[step_index].step
    ledger.append(
        {
            "schema_version": 1,
            "transition_sequence": len(ledger) + 1,
            "family": family,
            "task_id": validated.plan.task_id,
            "plan_revision": validated.plan.plan_revision,
            "plan_sha256": validated.plan_sha256,
            "step_id": step.step_id,
            "attempt": attempt,
            "skill": step.skill,
            "prior_state": prior_state,
            "resulting_state": resulting_state,
            "disposition": disposition,
            "detail_code": detail_code,
            "verified_facts": [item.as_dict() for item in facts],
            "evidence_refs": list(evidence_refs),
        }
    )


def _expect_submit(ledger: list[dict[str, object]], validated: Any) -> None:
    _expect(
        ledger,
        validated,
        step_index=0,
        attempt=1,
        family="submission",
        prior_state="absent",
        resulting_state="queued",
        disposition="task_queued",
        detail_code="validated_task_queued",
    )


def _expect_dispatch(
    ledger: list[dict[str, object]],
    validated: Any,
    *,
    prior_state: str = "queued",
    attempt: int = 1,
    step_index: int = 0,
) -> None:
    _expect(
        ledger,
        validated,
        step_index=step_index,
        attempt=attempt,
        family="tick",
        prior_state=prior_state,
        resulting_state="running",
        disposition="step_dispatched",
        detail_code="dispatch_returned",
    )


def _submission_case(manifest: dict[str, object], trial: int):
    namespace = "submission"
    owner, bridge = _bridge(manifest, namespace, trial)
    expected: list[dict[str, object]] = []
    plan = _validated(_hold_plan(namespace, trial))
    admitted = bridge.submit(plan)
    _expect_submit(expected, plan)
    rejected_active = bridge.submit(plan)
    capacity_owner = TaskExecutive(max_records=1)
    capacity_bridge = _bridge(
        manifest,
        f"{namespace}-capacity",
        trial,
        executive=capacity_owner,
    )[1]
    cap_one = _validated(_hold_plan(f"{namespace}-capacity", trial, suffix="one"))
    cap_two = _validated(_hold_plan(f"{namespace}-capacity", trial, suffix="two"))
    capacity_bridge.submit(cap_one)
    capacity_bridge.drain_narrative_events()
    capacity_before = capacity_owner.transition_journal_status().latest_sequence
    rejected_capacity = capacity_bridge.submit(cap_two)
    capacity_after = capacity_owner.transition_journal_status().latest_sequence
    return owner, bridge, expected, {
        "variant": "accepted_with_rejections",
        "tested_dispositions": {
            "admitted": admitted.__dict__ if hasattr(admitted, "__dict__") else {
                "accepted": admitted.accepted,
                "disposition": admitted.disposition,
            },
            "prior_active": {
                "accepted": rejected_active.accepted,
                "disposition": rejected_active.disposition,
            },
            "capacity": {
                "accepted": rejected_capacity.accepted,
                "disposition": rejected_capacity.disposition,
                "journal_delta": capacity_after - capacity_before,
            },
        },
    }


def _replacement_case(manifest: dict[str, object], trial: int):
    namespace = "replacement"
    variant = trial % 3
    owner, bridge = _bridge(manifest, namespace, trial)
    expected: list[dict[str, object]] = []
    if variant == 0:
        old = _validated(_hold_plan(namespace, trial))
        new = _validated(_hold_plan(namespace, trial, revision=2))
        bridge.submit(old)
        _expect_submit(expected, old)
        bridge.replace(new)
        _expect(
            expected,
            new,
            step_index=0,
            attempt=1,
            family="replacement",
            prior_state="queued",
            resulting_state="queued",
            disposition="replacement_activated",
            detail_code="replacement_activated",
        )
        name = "immediate_activation"
    elif variant == 1:
        old = _validated(_hold_plan(namespace, trial))
        new = _validated(_hold_plan(namespace, trial, revision=2))
        bridge.submit(old)
        _expect_submit(expected, old)
        request = bridge.tick(_snapshot(), now=1000.0 + trial)[0]
        _expect_dispatch(expected, old)
        bridge.replace(new)
        _expect(
            expected,
            old,
            step_index=0,
            attempt=1,
            family="replacement",
            prior_state="running",
            resulting_state="waiting_checkpoint",
            disposition="replacement_deferred",
            detail_code="replacement_waiting_for_checkpoint",
        )
        bridge.report(_result(request, namespace, trial, "in_progress"))
        _expect(
            expected,
            new,
            step_index=0,
            attempt=1,
            family="replacement",
            prior_state="waiting_checkpoint",
            resulting_state="queued",
            disposition="replacement_activated_at_checkpoint",
            detail_code="replacement_activated_at_checkpoint",
        )
        name = "deferred_checkpoint_activation"
    else:
        old = _validated(_critical_plan(namespace, trial), critical=True)
        new = _validated(_hold_plan(namespace, trial, revision=2, suffix="critical"))
        bridge.submit(old, task_class="system")
        _expect_submit(expected, old)
        request = bridge.tick(_snapshot(critical=True), now=1000.0 + trial)[0]
        _expect_dispatch(expected, old)
        bridge.replace(new)
        _expect(
            expected,
            old,
            step_index=0,
            attempt=1,
            family="replacement",
            prior_state="running",
            resulting_state="running",
            disposition="replacement_deferred",
            detail_code="replacement_waiting_until_step_finishes",
        )
        bridge.report(_result(request, namespace, trial, "succeeded"))
        _expect(
            expected,
            new,
            step_index=0,
            attempt=1,
            family="replacement",
            prior_state="running",
            resulting_state="queued",
            disposition="replacement_activated_after_step",
            detail_code="replacement_activated_after_step",
        )
        name = "deferred_after_step_activation"
    return owner, bridge, expected, {"variant": name}


def _tick_case(manifest: dict[str, object], trial: int):
    namespace = "tick"
    variant = trial % 5
    owner, bridge = _bridge(manifest, namespace, trial)
    expected: list[dict[str, object]] = []
    if variant == 0:
        plan = _validated(_hold_plan(namespace, trial))
        bridge.submit(plan)
        _expect_submit(expected, plan)
        bridge.tick(_snapshot(), now=1000.0 + trial)
        _expect_dispatch(expected, plan)
        name = "dispatch"
    elif variant in {1, 2}:
        attempts = 2 if variant == 1 else 1
        plan = _validated(_hold_plan(namespace, trial, attempts=attempts))
        bridge.submit(plan)
        _expect_submit(expected, plan)
        bridge.tick(_snapshot(), now=1000.0 + trial)
        _expect_dispatch(expected, plan)
        bridge.tick(_snapshot(), now=1005.0 + trial)
        if variant == 1:
            _expect(
                expected,
                plan,
                step_index=0,
                attempt=1,
                family="tick",
                prior_state="running",
                resulting_state="recovering",
                disposition="step_timeout_retry",
                detail_code="step_timeout",
            )
            _expect_dispatch(expected, plan, prior_state="recovering", attempt=2)
            name = "timeout_retry_and_dispatch"
        else:
            _expect(
                expected,
                plan,
                step_index=0,
                attempt=1,
                family="tick",
                prior_state="running",
                resulting_state="failed",
                disposition="step_timeout_failed",
                detail_code="step_timeout",
            )
            name = "timeout_failed"
    elif variant == 3:
        plan = _validated(_critical_plan(namespace, trial), critical=True)
        bridge.submit(plan, task_class="system")
        _expect_submit(expected, plan)
        bridge.tick(None, now=1000.0 + trial)
        _expect(
            expected,
            plan,
            step_index=0,
            attempt=1,
            family="tick",
            prior_state="queued",
            resulting_state="waiting_precondition",
            disposition="waiting_precondition",
            detail_code="preconditions_not_satisfied",
        )
        bridge.tick(None, now=1000.1 + trial)
        name = "first_precondition_wait_no_spam"
    else:
        locks = ResourceLocks()
        owner = TaskExecutive(resources=locks, transition_capacity=256)
        bridge = _bridge(manifest, namespace, trial, executive=owner)[1]
        holder = _validated(_hold_plan(namespace, trial, suffix="holder"))
        waiter = _validated(_hold_plan(namespace, trial, suffix="waiter"))
        bridge.submit(holder)
        _expect_submit(expected, holder)
        bridge.tick(_snapshot(), now=1000.0 + trial)
        _expect_dispatch(expected, holder)
        bridge.submit(waiter)
        _expect_submit(expected, waiter)
        bridge.tick(_snapshot(), now=1000.1 + trial)
        _expect(
            expected,
            waiter,
            step_index=0,
            attempt=1,
            family="tick",
            prior_state="queued",
            resulting_state="waiting_resource",
            disposition="waiting_resource",
            detail_code="resources_unavailable",
        )
        bridge.tick(_snapshot(), now=1000.2 + trial)
        name = "first_resource_wait_no_spam"
    return owner, bridge, expected, {"variant": name}


def _report_case(manifest: dict[str, object], trial: int):
    namespace = "report"
    variant = trial % 9
    owner, bridge = _bridge(manifest, namespace, trial)
    expected: list[dict[str, object]] = []
    attempts = 2 if variant == 3 else 1
    steps = 2 if variant == 1 else 1
    plan = _validated(_hold_plan(namespace, trial, attempts=attempts, steps=steps))
    bridge.submit(plan)
    _expect_submit(expected, plan)
    request = bridge.tick(_snapshot(), now=1000.0 + trial)[0]
    _expect_dispatch(expected, plan)
    if variant == 0:
        result = _result(request, namespace, trial, "in_progress")
        bridge.report(result)
        _expect(
            expected,
            plan,
            step_index=0,
            attempt=1,
            family="report",
            prior_state="running",
            resulting_state="running",
            disposition="progress_recorded",
            detail_code="progress_recorded:result_in_progress",
            evidence_refs=(result.snapshot_id,),
        )
        name = "progress"
    elif variant in {1, 2}:
        result = _result(request, namespace, trial, "succeeded")
        bridge.report(result)
        disposition = "step_succeeded" if variant == 1 else "task_succeeded"
        resulting = "queued" if variant == 1 else "succeeded"
        _expect(
            expected,
            plan,
            step_index=0,
            attempt=1,
            family="report",
            prior_state="running",
            resulting_state=resulting,
            disposition=disposition,
            detail_code=f"{disposition}:result_succeeded",
            facts=result.verified_facts,
            evidence_refs=(result.snapshot_id,),
        )
        name = disposition
    elif variant in {3, 4}:
        status = "blocked" if variant == 3 else "failed"
        result = _result(request, namespace, trial, status)
        bridge.report(result)
        disposition = "retry_scheduled" if variant == 3 else "task_failed"
        resulting = "recovering" if variant == 3 else "failed"
        _expect(
            expected,
            plan,
            step_index=0,
            attempt=1,
            family="report",
            prior_state="running",
            resulting_state=resulting,
            disposition=disposition,
            detail_code=f"{disposition}:result_{status}",
            evidence_refs=(result.snapshot_id,),
        )
        name = disposition
    elif variant == 5:
        result = _result(request, namespace, trial, "cancelled")
        bridge.report(result)
        _expect(
            expected,
            plan,
            step_index=0,
            attempt=1,
            family="report",
            prior_state="running",
            resulting_state="cancelled",
            disposition="task_cancelled",
            detail_code="task_cancelled:result_cancelled",
            evidence_refs=(result.snapshot_id,),
        )
        name = "cancellation"
    elif variant in {6, 7}:
        bridge.request_interrupt(
            InterruptRequest("correction", "switch task", target_task_id=plan.plan.task_id)
        )
        _expect(
            expected,
            plan,
            step_index=0,
            attempt=1,
            family="interruption",
            prior_state="running",
            resulting_state="waiting_checkpoint",
            disposition="interrupt_waiting_checkpoint",
            detail_code="interrupt_waiting_for_checkpoint",
        )
        result = _result(
            request,
            namespace,
            trial,
            "in_progress" if variant == 6 else "succeeded",
            checkpoint=variant == 6,
        )
        bridge.report(result)
        disposition = "cancelled_at_checkpoint" if variant == 6 else "cancelled_after_step"
        _expect(
            expected,
            plan,
            step_index=0,
            attempt=1,
            family="report",
            prior_state="waiting_checkpoint",
            resulting_state="cancelled",
            disposition=disposition,
            detail_code=disposition,
            evidence_refs=(result.snapshot_id,),
        )
        name = disposition
    else:
        result = _result(request, namespace, trial, "succeeded", verified=False)
        bridge.report(result)
        _expect(
            expected,
            plan,
            step_index=0,
            attempt=1,
            family="report",
            prior_state="running",
            resulting_state="failed",
            disposition="task_failed",
            detail_code="unverified_success_claim",
            evidence_refs=(result.snapshot_id,),
        )
        name = "invalid_success_to_failure"
    return owner, bridge, expected, {"variant": name}


def _dispatch_failure_case(manifest: dict[str, object], trial: int):
    namespace = "dispatch-failure"
    retry = trial % 2 == 0
    owner, bridge = _bridge(manifest, namespace, trial)
    expected: list[dict[str, object]] = []
    plan = _validated(_hold_plan(namespace, trial, attempts=2 if retry else 1))
    bridge.submit(plan)
    _expect_submit(expected, plan)
    request = bridge.tick(_snapshot(), now=1000.0 + trial)[0]
    _expect_dispatch(expected, plan)
    bridge.dispatch_failed(request, "adapter_exception")
    disposition = "retry_scheduled" if retry else "task_failed"
    _expect(
        expected,
        plan,
        step_index=0,
        attempt=1,
        family="dispatch_failure",
        prior_state="running",
        resulting_state="recovering" if retry else "failed",
        disposition=disposition,
        detail_code=f"{disposition}:dispatch_failed:adapter_exception",
    )
    before = owner.transition_journal_status().latest_sequence
    replay = bridge.dispatch_failed(request, "duplicate")
    after = owner.transition_journal_status().latest_sequence
    return owner, bridge, expected, {
        "variant": f"{disposition}_with_stale_replay",
        "stale_replay": {
            "accepted": replay.accepted,
            "journal_delta": after - before,
        },
    }


def _interruption_case(manifest: dict[str, object], trial: int):
    namespace = "interruption"
    variant = trial % 3
    owner, bridge = _bridge(manifest, namespace, trial)
    expected: list[dict[str, object]] = []
    plan = _validated(_hold_plan(namespace, trial))
    bridge.submit(plan)
    _expect_submit(expected, plan)
    request = bridge.tick(_snapshot(), now=1000.0 + trial)[0]
    _expect_dispatch(expected, plan)
    before = owner.transition_journal_status().latest_sequence
    overlap = bridge.request_interrupt(
        InterruptRequest("voice", "ambient", target_task_id=plan.plan.task_id)
    )
    overlap_delta = owner.transition_journal_status().latest_sequence - before
    if variant == 0:
        decision = bridge.request_interrupt(
            InterruptRequest("explicit_stop", "owner stop", target_task_id=plan.plan.task_id)
        )
        _expect(
            expected,
            plan,
            step_index=0,
            attempt=1,
            family="interruption",
            prior_state="running",
            resulting_state="cancelled",
            disposition="interrupt_cancelled",
            detail_code="interrupt_cancelled:owner stop",
        )
        name = "immediate_cancel"
    elif variant == 1:
        decision = bridge.request_interrupt(
            InterruptRequest("correction", "switch task", target_task_id=plan.plan.task_id)
        )
        _expect(
            expected,
            plan,
            step_index=0,
            attempt=1,
            family="interruption",
            prior_state="running",
            resulting_state="waiting_checkpoint",
            disposition="interrupt_waiting_checkpoint",
            detail_code="interrupt_waiting_for_checkpoint",
        )
        name = "checkpoint_wait"
    else:
        decision = bridge.request_interrupt(
            InterruptRequest("voice", "summons", target_task_id=plan.plan.task_id)
        )
        _expect(
            expected,
            plan,
            step_index=0,
            attempt=1,
            family="interruption",
            prior_state="running",
            resulting_state="suspended",
            disposition="interrupt_suspended",
            detail_code="interrupt_suspended:summons",
        )
        name = "suspend"
    return owner, bridge, expected, {
        "variant": name,
        "overlap": {"action": overlap.action, "journal_delta": overlap_delta},
        "decision": decision.action,
    }


def _lifecycle_case(manifest: dict[str, object], trial: int):
    namespace = "explicit-lifecycle"
    variant = trial % 3
    owner, bridge = _bridge(manifest, namespace, trial)
    expected: list[dict[str, object]] = []
    plan = _validated(_hold_plan(namespace, trial))
    bridge.submit(plan)
    _expect_submit(expected, plan)
    if variant == 0:
        bridge.suspend_task(plan.plan.task_id, reason="park")
        _expect(
            expected,
            plan,
            step_index=0,
            attempt=1,
            family="explicit_lifecycle",
            prior_state="queued",
            resulting_state="suspended",
            disposition="task_suspended",
            detail_code="task_suspended:park",
        )
        before = owner.transition_journal_status().latest_sequence
        bridge.suspend_task(plan.plan.task_id, reason="park again")
        rejected_delta = owner.transition_journal_status().latest_sequence - before
        name = "suspend"
    elif variant == 1:
        bridge.suspend_task(plan.plan.task_id, reason="park")
        _expect(
            expected,
            plan,
            step_index=0,
            attempt=1,
            family="explicit_lifecycle",
            prior_state="queued",
            resulting_state="suspended",
            disposition="task_suspended",
            detail_code="task_suspended:park",
        )
        bridge.resume_task(plan.plan.task_id, reason="continue")
        _expect(
            expected,
            plan,
            step_index=0,
            attempt=1,
            family="explicit_lifecycle",
            prior_state="suspended",
            resulting_state="queued",
            disposition="task_resumed",
            detail_code="task_resumed:continue",
        )
        before = owner.transition_journal_status().latest_sequence
        rejected = bridge.resume_task(plan.plan.task_id)
        rejected_delta = owner.transition_journal_status().latest_sequence - before
        assert not rejected.accepted
        name = "queued_resume"
    else:
        bridge.tick(_snapshot(), now=1000.0 + trial)
        _expect_dispatch(expected, plan)
        bridge.suspend_task(plan.plan.task_id, reason="pause controller")
        _expect(
            expected,
            plan,
            step_index=0,
            attempt=1,
            family="explicit_lifecycle",
            prior_state="running",
            resulting_state="suspended",
            disposition="task_suspended",
            detail_code="task_suspended:pause controller",
        )
        disposition, request = bridge.resume_task_running(
            plan.plan.task_id,
            reason="controller restored",
            now=1001.0 + trial,
        )
        assert disposition.accepted and request is not None
        _expect(
            expected,
            plan,
            step_index=0,
            attempt=1,
            family="explicit_lifecycle",
            prior_state="suspended",
            resulting_state="running",
            disposition="task_resumed_running",
            detail_code="task_resumed_running:controller restored",
        )
        before = owner.transition_journal_status().latest_sequence
        rejected = bridge.resume_task_running(plan.plan.task_id)[0]
        rejected_delta = owner.transition_journal_status().latest_sequence - before
        assert not rejected.accepted
        name = "running_resume"
    return owner, bridge, expected, {
        "variant": name,
        "rejected_or_noop_journal_delta": rejected_delta,
    }


def _parent_child_case(manifest: dict[str, object], trial: int):
    namespace = "parent-child"
    owner, bridge = _bridge(manifest, namespace, trial)
    expected: list[dict[str, object]] = []
    parent = _validated(_hold_plan(namespace, trial, suffix="parent"))
    child = _validated(_hold_plan(namespace, trial, suffix="child"))
    bridge.submit(parent)
    _expect_submit(expected, parent)
    bridge.tick(_snapshot(), now=1000.0 + trial)
    _expect_dispatch(expected, parent)
    bridge.suspend_task(parent.plan.task_id, reason="check sofa")
    _expect(
        expected,
        parent,
        step_index=0,
        attempt=1,
        family="explicit_lifecycle",
        prior_state="running",
        resulting_state="suspended",
        disposition="task_suspended",
        detail_code="task_suspended:check sofa",
    )
    bridge.submit(child, task_class="voice", resume_parent_task_id=parent.plan.task_id)
    _expect_submit(expected, child)
    child_request = bridge.tick(_snapshot(), now=1001.0 + trial)[0]
    _expect_dispatch(expected, child)
    progress = _result(child_request, namespace, trial, "in_progress")
    progress = replace(
        progress,
        verified_facts=(VerifiedFact("near", "sofa", "localization", 0.96),),
    )
    bridge.report(progress)
    _expect(
        expected,
        child,
        step_index=0,
        attempt=1,
        family="report",
        prior_state="running",
        resulting_state="running",
        disposition="progress_recorded",
        detail_code="progress_recorded:result_in_progress",
        facts=progress.verified_facts,
        evidence_refs=(progress.snapshot_id,),
    )
    success = _result(child_request, namespace, trial, "succeeded")
    bridge.report(success)
    _expect(
        expected,
        child,
        step_index=0,
        attempt=1,
        family="report",
        prior_state="running",
        resulting_state="succeeded",
        disposition="task_succeeded",
        detail_code="task_succeeded:result_succeeded",
        facts=success.verified_facts,
        evidence_refs=(success.snapshot_id,),
    )
    bridge.resume_task(parent.plan.task_id, reason="child complete")
    _expect(
        expected,
        parent,
        step_index=0,
        attempt=1,
        family="explicit_lifecycle",
        prior_state="suspended",
        resulting_state="queued",
        disposition="task_resumed",
        detail_code="task_resumed:child complete",
    )
    bridge.tick(_snapshot(), now=1002.0 + trial)
    _expect_dispatch(expected, parent)
    return owner, bridge, expected, {
        "variant": "parent_child_resume",
        "parent_task_id": parent.plan.task_id,
        "child_task_id": child.plan.task_id,
    }


_FAMILY_RUNNERS = {
    "submission": _submission_case,
    "replacement": _replacement_case,
    "tick": _tick_case,
    "report": _report_case,
    "dispatch_failure": _dispatch_failure_case,
    "interruption": _interruption_case,
    "explicit_lifecycle": _lifecycle_case,
}


def _event_record(
    authenticated: AuthenticatedExecutionNarrativeEventV1,
    state: NarrativeConsumerStateV1,
    manifest: dict[str, object],
    now: int,
) -> tuple[NarrativeConsumerStateV1, dict[str, object]]:
    reduction = consume_execution_narrative_event(
        state,
        authenticated,
        authenticator=AUTH,
        now_monotonic_ns=now,
    )
    replay = consume_execution_narrative_event(
        reduction.state,
        authenticated,
        authenticator=AUTH,
        now_monotonic_ns=now,
    )
    return reduction.state, {
        "event": authenticated.event.as_dict(),
        "authenticator_id": authenticated.authenticator_id,
        "auth_verified": AUTH.verify(authenticated),
        "authorizes_actuation": authenticated.authorizes_actuation,
        "consumer": {
            "accepted": reduction.accepted,
            "reason": reduction.reason,
            "frame": reduction.frame.as_dict() if reduction.frame is not None else None,
            "state_after": reduction.state.as_dict(),
        },
        "replay": {
            "accepted": replay.accepted,
            "reason": replay.reason,
            "frame": replay.frame.as_dict() if replay.frame is not None else None,
            "state_unchanged": replay.state is reduction.state,
        },
    }


def run_transition_case(
    manifest: dict[str, object],
    family: str,
    trial: int,
) -> dict[str, object]:
    owner, bridge, expected, metadata = _FAMILY_RUNNERS[family](manifest, trial)
    journal = owner.read_transition_journal(after_sequence=0)
    events = bridge.drain_narrative_events()
    state = NarrativeConsumerStateV1(
        source_epoch=int(manifest["source_epoch"]),
        speech_generation=int(manifest["speech_generation"]),
    )
    event_rows: list[dict[str, object]] = []
    for authenticated in events:
        state, record = _event_record(
            authenticated,
            state,
            manifest,
            authenticated.event.issued_at_monotonic_ns + 1,
        )
        event_rows.append(record)
    return {
        "case_id": f"h1h2-{family}-{trial:04d}",
        "family": family,
        "trial": trial,
        **metadata,
        "expected_ledger": expected,
        "journal_read": journal.as_dict(),
        "journal_status": owner.transition_journal_status().as_dict(),
        "events": event_rows,
        "final_consumer_state": state.as_dict(),
    }


def run_parent_child_case(
    manifest: dict[str, object],
    trial: int,
) -> dict[str, object]:
    owner, bridge, expected, metadata = _parent_child_case(manifest, trial)
    journal = owner.read_transition_journal(after_sequence=0)
    events = bridge.drain_narrative_events()
    state = NarrativeConsumerStateV1(
        source_epoch=int(manifest["source_epoch"]),
        speech_generation=int(manifest["speech_generation"]),
    )
    event_rows: list[dict[str, object]] = []
    for authenticated in events:
        state, record = _event_record(
            authenticated,
            state,
            manifest,
            authenticated.event.issued_at_monotonic_ns + 1,
        )
        event_rows.append(record)
    return {
        "case_id": f"h2-parent-child-{trial:04d}",
        "family": "interruption_stack",
        "trial": trial,
        **metadata,
        "expected_ledger": expected,
        "journal_read": journal.as_dict(),
        "journal_status": owner.transition_journal_status().as_dict(),
        "events": event_rows,
        "final_consumer_state": state.as_dict(),
    }


def _rebuild_event(event: Any, **changes: object):
    values = event.as_dict()
    values.update(changes)
    for field in ("schema_version", "event_id", "mission_id", "action_id"):
        values.pop(field, None)
    facts = tuple(VerifiedFact.from_mapping(item) for item in values.pop("verified_facts"))
    evidence_refs = tuple(values.pop("evidence_refs"))
    return build_execution_narrative_event(
        **values,
        verified_facts=facts,
        evidence_refs=evidence_refs,
    )


def _consume_prefix(
    manifest: dict[str, object],
    events: tuple[AuthenticatedExecutionNarrativeEventV1, ...],
) -> NarrativeConsumerStateV1:
    state = NarrativeConsumerStateV1(
        source_epoch=int(manifest["source_epoch"]),
        speech_generation=int(manifest["speech_generation"]),
    )
    for authenticated in events:
        reduction = consume_execution_narrative_event(
            state,
            authenticated,
            authenticator=AUTH,
            now_monotonic_ns=authenticated.event.issued_at_monotonic_ns + 1,
        )
        if not reduction.accepted:
            raise RuntimeError(f"corruption setup failed: {reduction.reason}")
        state = reduction.state
    return state


def run_corruption_case(
    manifest: dict[str, object],
    trial: int,
    corruption: str,
) -> dict[str, object]:
    namespace = "corruption"
    if corruption == "skipped_cursor":
        owner = TaskExecutive(transition_capacity=8)
        bridge = NarratingTaskExecutiveV1(
            owner,
            authenticator=AUTH,
            source_epoch=int(manifest["source_epoch"]),
            speech_generation_provider=lambda: int(manifest["speech_generation"]),
            monotonic_ns=lambda: _now_ns(namespace, trial),
            journal_cursor=1,
        )
        try:
            bridge.sync_narrative_transitions()
            fault = None
        except ExecutiveJournalContinuityError as error:
            fault = error.fault_code
        return {
            "case_id": f"h3-{trial:04d}-{corruption}",
            "trial": trial,
            "corruption": corruption,
            "surface": "journal",
            "journal_read": owner.read_transition_journal(after_sequence=1).as_dict(),
            "fault_code": fault,
            "queue_status": bridge.narrative_queue_status().__dict__
            if hasattr(bridge.narrative_queue_status(), "__dict__")
            else {
                "queued": bridge.narrative_queue_status().queued,
                "journal_cursor": bridge.narrative_queue_status().journal_cursor,
                "fault_code": bridge.narrative_queue_status().fault_code,
            },
            "post_fault_event_count": len(bridge.drain_narrative_events()),
        }
    if corruption == "overwritten_cursor":
        owner = TaskExecutive(transition_capacity=2)
        for suffix in ("one", "two", "three"):
            owner.submit(_validated(_hold_plan(namespace, trial, suffix=suffix)))
        bridge = _bridge(manifest, namespace, trial, executive=owner)[1]
        journal = owner.read_transition_journal(after_sequence=0)
        try:
            bridge.sync_narrative_transitions()
            fault = None
        except ExecutiveJournalContinuityError as error:
            fault = error.fault_code
        return {
            "case_id": f"h3-{trial:04d}-{corruption}",
            "trial": trial,
            "corruption": corruption,
            "surface": "journal",
            "journal_read": journal.as_dict(),
            "journal_status": owner.transition_journal_status().as_dict(),
            "fault_code": fault,
            "post_fault_event_count": len(bridge.drain_narrative_events()),
        }
    if corruption == "narrative_queue_overflow":
        owner, bridge = _bridge(
            manifest,
            namespace,
            trial,
            event_capacity=1,
        )
        first = _validated(_hold_plan(namespace, trial, suffix="first"))
        second = _validated(_hold_plan(namespace, trial, suffix="second"))
        bridge.submit(first)
        try:
            bridge.submit(second)
            fault = None
        except ExecutiveJournalContinuityError as error:
            fault = error.fault_code
        prefix = bridge.drain_narrative_events()
        prefix_state = _consume_prefix(manifest, prefix)
        return {
            "case_id": f"h3-{trial:04d}-{corruption}",
            "trial": trial,
            "corruption": corruption,
            "surface": "journal",
            "journal_status": owner.transition_journal_status().as_dict(),
            "fault_code": fault,
            "retained_prefix_sequences": [item.event.event_sequence for item in prefix],
            "prefix_consumer_sequence": prefix_state.last_event_sequence,
            "post_fault_event_count": len(bridge.drain_narrative_events()),
        }

    owner, bridge = _bridge(manifest, namespace, trial)
    plan = _validated(_hold_plan(namespace, trial))
    bridge.submit(plan)
    request = bridge.tick(_snapshot(), now=1000.0 + trial)[0]
    prefix = bridge.drain_narrative_events()
    state = _consume_prefix(manifest, prefix)
    base = prefix[-1]
    sequence = state.last_event_sequence + 1
    values: dict[str, object] = {
        "event_sequence": sequence,
        "status": "progress",
        "detail_code": f"corrupt_{corruption}",
        "issued_at_monotonic_ns": _now_ns(namespace, trial),
        "claimable_until_monotonic_ns": (
            _now_ns(namespace, trial) + int(manifest["event_ttl_ns"])
        ),
        "verified_facts": [
            VerifiedFact("near", "sofa", "localization", 0.9).as_dict()
        ],
        "evidence_refs": [f"evidence-{token(namespace, trial, 'base-evidence')}"] ,
    }
    if corruption == "post_terminal_transition":
        success = _result(request, namespace, trial, "succeeded")
        bridge.report(success)
        terminal = bridge.drain_narrative_events()
        state = _consume_prefix(manifest, prefix + terminal)
        base = terminal[-1]
        values["event_sequence"] = state.last_event_sequence + 1
    if corruption == "duplicate_event":
        tested: object = base
    else:
        if corruption == "reordered_event":
            values["event_sequence"] = max(1, state.last_event_sequence - 1)
        elif corruption == "stale_epoch":
            values["source_epoch"] = int(manifest["source_epoch"]) + 1
        elif corruption == "stale_speech_generation":
            values["speech_generation"] = int(manifest["speech_generation"]) + 1
        elif corruption == "expired_event":
            values["issued_at_monotonic_ns"] = _now_ns(namespace, trial) - 100
            values["claimable_until_monotonic_ns"] = _now_ns(namespace, trial)
        elif corruption == "future_event":
            values["issued_at_monotonic_ns"] = _now_ns(namespace, trial) + 100
        elif corruption == "task_mutation":
            values["task_id"] = f"task-{token(namespace, trial, 'mutated-task')}"
        elif corruption == "revision_mutation":
            values["plan_revision"] = base.event.plan_revision + 1
        elif corruption == "step_mutation":
            values["step_id"] = f"step-{token(namespace, trial, 'mutated-step')}"
        elif corruption == "attempt_mutation":
            values["attempt"] = base.event.attempt + 1
        elif corruption == "plan_mutation":
            values["plan_sha256"] = token(namespace, trial, "mutated-plan", 64)
        elif corruption == "action_mutation":
            values["action_name"] = "Vocalize"
        elif corruption == "event_sequence_gap":
            values["event_sequence"] = state.last_event_sequence + 2
        candidate = _rebuild_event(base.event, **values)
        if corruption == "tag_corruption":
            tested = AuthenticatedExecutionNarrativeEventV1(
                candidate,
                base.authenticator_id,
                "0" * 64,
            )
        elif corruption in {"fact_mutation", "evidence_mutation"}:
            original = AUTH.authenticate(candidate)
            tamper_values: dict[str, object] = {}
            if corruption == "fact_mutation":
                tamper_values["verified_facts"] = [
                    VerifiedFact("object_observed", "keys", "camera", 1.0).as_dict()
                ]
            else:
                tamper_values["evidence_refs"] = [
                    f"evidence-{token(namespace, trial, 'mutated-evidence')}"
                ]
            tampered_event = _rebuild_event(candidate, **tamper_values)
            tested = AuthenticatedExecutionNarrativeEventV1(
                tampered_event,
                original.authenticator_id,
                original.auth_tag,
            )
        else:
            tested = AUTH.authenticate(candidate)
    before = state
    reduction = consume_execution_narrative_event(
        state,
        tested,
        authenticator=AUTH,
        now_monotonic_ns=_now_ns(namespace, trial) + 1,
    )
    assert isinstance(tested, AuthenticatedExecutionNarrativeEventV1)
    return {
        "case_id": f"h3-{trial:04d}-{corruption}",
        "trial": trial,
        "corruption": corruption,
        "surface": "event",
        "setup_last_sequence": state.last_event_sequence,
        "tested_event": tested.event.as_dict(),
        "tested_auth_verified": AUTH.verify(tested),
        "consumer": {
            "accepted": reduction.accepted,
            "reason": reduction.reason,
            "frame": reduction.frame.as_dict() if reduction.frame is not None else None,
            "state_unchanged": reduction.state is before,
            "state_after": reduction.state.as_dict(),
        },
        "journal_status": owner.transition_journal_status().as_dict(),
    }


def run_concurrency_case(
    manifest: dict[str, object],
    *,
    force_overflow: bool,
) -> dict[str, object]:
    count = int(manifest["producer_threads"])
    capacity = (
        int(manifest["overflow_journal_capacity"])
        if force_overflow
        else int(manifest["normal_journal_capacity"])
    )
    owner = TaskExecutive(
        max_records=count + 1,
        transition_capacity=capacity,
    )
    plans = [
        _validated(_hold_plan("concurrency", index, suffix=f"producer-{index}"))
        for index in range(count)
    ]
    expected: list[dict[str, object]] = []
    for plan in plans:
        _expect_submit(expected, plan)

    condition = threading.Condition()
    barrier = threading.Barrier(count + 1)
    turn = [0]
    done = [False]
    errors: list[str] = []
    observed: list[dict[str, object]] = []

    def producer(index: int) -> None:
        try:
            barrier.wait(timeout=10.0)
            with condition:
                condition.wait_for(lambda: turn[0] == index, timeout=10.0)
                disposition = owner.submit(plans[index])
                if not disposition.accepted:
                    raise RuntimeError("concurrency submission rejected")
                turn[0] += 1
                if turn[0] == count:
                    done[0] = True
                condition.notify_all()
        except BaseException as error:
            with condition:
                errors.append(f"{type(error).__name__}:{error}")
                done[0] = True
                condition.notify_all()

    def consume() -> None:
        try:
            barrier.wait(timeout=10.0)
            if force_overflow:
                with condition:
                    condition.wait_for(lambda: done[0], timeout=10.0)
                read = owner.read_transition_journal(after_sequence=0)
                observed.append(
                    {
                        "status": read.status,
                        "oldest_available_sequence": read.oldest_available_sequence,
                        "latest_sequence": read.latest_sequence,
                        "transitions": [item.as_dict() for item in read.transitions],
                    }
                )
                return
            cursor = 0
            while cursor < count:
                with condition:
                    condition.wait_for(
                        lambda: owner.transition_journal_status().latest_sequence > cursor
                        or done[0],
                        timeout=10.0,
                    )
                read = owner.read_transition_journal(after_sequence=cursor)
                observed.extend(item.as_dict() for item in read.transitions)
                if read.transitions:
                    cursor = read.transitions[-1].transition_sequence
                elif done[0]:
                    break
        except BaseException as error:
            with condition:
                errors.append(f"consumer:{type(error).__name__}:{error}")
                done[0] = True
                condition.notify_all()

    consumer = threading.Thread(target=consume, name="dmc4-journal-consumer")
    producers = [
        threading.Thread(target=producer, args=(index,), name=f"dmc4-producer-{index}")
        for index in range(count)
    ]
    consumer.start()
    for thread in producers:
        thread.start()
    for thread in producers:
        thread.join(timeout=15.0)
    consumer.join(timeout=15.0)
    alive = sorted(
        thread.name
        for thread in [consumer, *producers]
        if thread.is_alive()
    )

    bridge_fault: str | None = None
    post_fault_events: list[object] = []
    if force_overflow:
        bridge = _bridge(
            manifest,
            "concurrency-overflow",
            0,
            executive=owner,
        )[1]
        try:
            bridge.sync_narrative_transitions()
        except ExecutiveJournalContinuityError as error:
            bridge_fault = error.fault_code
        post_fault_events = list(bridge.drain_narrative_events())
    return {
        "case_id": "h4-forced-overflow" if force_overflow else "h4-normal",
        "force_overflow": force_overflow,
        "producer_threads": count,
        "expected_ledger": expected,
        "observed": observed,
        "journal_status": owner.transition_journal_status().as_dict(),
        "errors": errors,
        "alive_threads": alive,
        "bridge_fault": bridge_fault,
        "post_fault_event_count": len(post_fault_events),
    }


def run_non_actuation_checks() -> dict[str, object]:
    import ast

    relative_files = (
        "src/parcel_robot/brain/executive.py",
        "src/parcel_robot/brain/execution_narrative_bridge.py",
        "src/parcel_robot/contracts/execution_narrative_v1.py",
        "src/parcel_robot/voice/execution_narrative.py",
    )
    forbidden_roots = {
        "socket",
        "requests",
        "httpx",
        "websockets",
        "openai",
        "unitree_sdk2py",
        "gateway",
    }
    imports: dict[str, list[str]] = {}
    violations: list[dict[str, str]] = []
    for relative in relative_files:
        source = (REPO_ROOT / relative).read_text(encoding="utf-8")
        tree = ast.parse(source)
        names: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                names.append(node.module or "")
        imports[relative] = sorted(names)
        for name in names:
            root = name.split(".")[0]
            if root in forbidden_roots or any(part in forbidden_roots for part in name.split(".")):
                violations.append({"file": relative, "import": name})
    owner = TaskExecutive()
    transition_auth = owner.authorizes_actuation
    journal_auth = owner.transition_journal_status().authorizes_actuation
    bridge = _bridge(
        json.loads(MANIFEST_PATH.read_text(encoding="utf-8")),
        "non-actuation",
        0,
        executive=owner,
    )[1]
    return {
        "files": list(relative_files),
        "imports": imports,
        "forbidden_imports": violations,
        "authorizes_actuation": {
            "executive": transition_auth,
            "journal_status": journal_auth,
            "authenticator": AUTH.authorizes_actuation,
            "bridge": bridge.authorizes_actuation,
        },
    }


def _chain(rows: list[dict[str, object]]) -> str:
    value = "0" * 64
    for row in rows:
        value = digest({"previous": value, "row": row})
    return value


def run_suite(
    manifest: dict[str, object],
    *,
    family_limit: int | None = None,
    parent_limit: int | None = None,
    corruption_limit: int | None = None,
) -> dict[str, object]:
    per_family = (
        int(manifest["cases_per_family"])
        if family_limit is None
        else family_limit
    )
    parent_count = (
        int(manifest["parent_child_cases"])
        if parent_limit is None
        else parent_limit
    )
    corruption_count = (
        int(manifest["corruption_cases"])
        if corruption_limit is None
        else corruption_limit
    )
    transition_rows = [
        run_transition_case(manifest, str(family), trial)
        for family in manifest["transition_families"]
        for trial in range(per_family)
    ]
    parent_rows = [
        run_parent_child_case(manifest, trial) for trial in range(parent_count)
    ]
    corruptions = tuple(str(item) for item in manifest["corruptions"])
    corruption_rows = [
        run_corruption_case(
            manifest,
            trial,
            corruptions[trial % len(corruptions)],
        )
        for trial in range(corruption_count)
    ]
    concurrency_rows = [
        run_concurrency_case(manifest, force_overflow=False),
        run_concurrency_case(manifest, force_overflow=True),
    ]
    rows = [*transition_rows, *parent_rows, *corruption_rows, *concurrency_rows]
    normalized = {
        "schema_version": 1,
        "experiment_id": manifest["experiment_id"],
        "seed": manifest["seed"],
        "population": {
            "cases_per_family": per_family,
            "parent_child_cases": parent_count,
            "corruption_cases": corruption_count,
            "producer_threads": manifest["producer_threads"],
        },
        "not_constructible": manifest["not_constructible"],
        "transition_rows": transition_rows,
        "parent_child_rows": parent_rows,
        "corruption_rows": corruption_rows,
        "concurrency_rows": concurrency_rows,
        "non_actuation": run_non_actuation_checks(),
    }
    return {
        **normalized,
        "manifest_sha256": file_sha256(MANIFEST_PATH),
        "source_manifest_sha256": file_sha256(SOURCE_MANIFEST_PATH),
        "normalized_trace_sha256": digest(normalized),
        "trace_chain_root_sha256": _chain(rows),
        "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    result = run_suite(manifest)
    result["result_sha256"] = digest(result)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output": str(args.output),
                "normalized_trace_sha256": result["normalized_trace_sha256"],
                "trace_chain_root_sha256": result["trace_chain_root_sha256"],
                "peak_rss_kib": result["peak_rss_kib"],
                "populations": result["population"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
