"""Runtime composition tests for the disarmed DMC-4 journal observer."""

from __future__ import annotations

from dataclasses import replace

import pytest

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
from parcel_robot.brain.executive import TaskExecutive
from parcel_robot.brain.validator import PlanValidator
from parcel_robot.contracts.execution_narrative_v1 import (
    build_execution_narrative_event,
)
from parcel_robot.voice.execution_narrative_runtime import (
    JournalOnlyNarrativeRuntimeV1,
)


def _plan(task_id: str, *, revision: int = 1):
    return PlanValidator().validate(
        PlanIR(
            schema_version=1,
            task_id=task_id,
            plan_revision=revision,
            source_turn_id=f"turn-{task_id}-{revision}",
            goal=GoalSpec("hold", GoalTarget("current_pose"), 0.0),
            invariants=(),
            steps=(
                PlanStep(
                    f"step-{task_id}",
                    "Hold",
                    {},
                    ("base_available",),
                    SuccessCondition("motion_stopped"),
                    5.0,
                    1,
                    (),
                    ("base",),
                    "immediate",
                ),
            ),
        )
    )


def _two_step_plan(task_id: str, *, wait_for: str):
    second_preconditions = (
        ("base_available", "camera_fresh")
        if wait_for == "precondition"
        else ("base_available",)
    )
    return PlanValidator().validate(
        PlanIR(
            schema_version=1,
            task_id=task_id,
            plan_revision=1,
            source_turn_id=f"turn-{task_id}",
            goal=GoalSpec("hold", GoalTarget("current_pose"), 0.0),
            invariants=(),
            steps=(
                PlanStep(
                    f"step-{task_id}-first",
                    "Hold",
                    {},
                    ("base_available",),
                    SuccessCondition("motion_stopped"),
                    5.0,
                    1,
                    (),
                    ("base",),
                    "immediate",
                ),
                PlanStep(
                    f"step-{task_id}-second",
                    "Hold",
                    {},
                    second_preconditions,
                    SuccessCondition("motion_stopped"),
                    5.0,
                    1,
                    (),
                    ("base",),
                    "immediate",
                ),
            ),
        )
    )


def _retry_plan(task_id: str):
    plan = _plan(task_id).plan
    step = plan.steps[0]
    return PlanValidator().validate(
        replace(
            plan,
            steps=(replace(step, max_attempts=2, recovery=("safe_stop",)),),
        )
    )


def _fresh_snapshot() -> ObservationSnapshot:
    return ObservationSnapshot(
        schema_version=1,
        snapshot_id="snapshot-narrative-lifecycle",
        captured_at_monotonic_s=11.0,
        camera=SensorSnapshot("camera", True, True, "camera", 10.9, 100.0),
        lidar=SensorSnapshot("lidar", True, True, "lidar", 10.95, 50.0),
        robot=RobotStateSnapshot(False, "stand"),
        safety=SafetyStateSnapshot(False, False, True),
        battery=BatteryStateSnapshot("normal", 80.0, "unitree"),
        task=TaskStateSnapshot(),
    )


def _success(request) -> ExecutionResult:
    return ExecutionResult(
        schema_version=1,
        task_id=request.task_id,
        plan_revision=request.plan_revision,
        step_id=request.step_id,
        attempt=request.attempt,
        status="succeeded",
        feedback_code="succeeded",
        snapshot_id=f"snapshot-{request.task_id}",
        verified_facts=(VerifiedFact("motion_stopped", None, "controller", 1.0),),
        checkpoint=True,
        detail_code="motion_stop_verified",
        started_at_monotonic_s=10.0,
        finished_at_monotonic_s=10.1,
    )


def _non_success(request, status: str) -> ExecutionResult:
    return ExecutionResult(
        schema_version=1,
        task_id=request.task_id,
        plan_revision=request.plan_revision,
        step_id=request.step_id,
        attempt=request.attempt,
        status=status,
        feedback_code=status,
        snapshot_id=f"snapshot-{request.task_id}-{status}",
        verified_facts=(),
        checkpoint=status != "in_progress",
        detail_code=f"controller_{status}",
        started_at_monotonic_s=10.0,
        finished_at_monotonic_s=None if status == "in_progress" else 10.1,
    )


def test_bare_executive_journal_becomes_non_actuating_model_b_frames() -> None:
    executive = TaskExecutive()
    observer = JournalOnlyNarrativeRuntimeV1(
        executive,
        source_epoch=17,
        authentication_key=b"runtime-journal-test-key-000000001",
        monotonic_ns=lambda: 1_000_000_000,
    )

    assert executive.submit(_plan("task-runtime-journal")).accepted
    request = executive.tick(now=10.0)[0]
    assert executive.report(_success(request)).accepted

    assert observer.poll() == 3
    frames = observer.drain_frames()
    assert [frame.status for frame in frames] == ["accepted", "started", "succeeded"]
    assert [frame.event_sequence for frame in frames] == [1, 2, 3]
    assert all(frame.source_epoch == 17 for frame in frames)
    assert all(frame.speech_generation == 0 for frame in frames)
    assert all(frame.plan_revision == 1 for frame in frames)
    assert all(frame.plan_sha256 == frames[0].plan_sha256 for frame in frames)
    assert all(frame.mission_id == frames[0].mission_id for frame in frames)
    assert all(frame.action_id == frames[0].action_id for frame in frames)
    assert all(frame.issued_at_monotonic_ns == 1_000_000_000 for frame in frames)
    assert all(frame.claimable_until_monotonic_ns == 6_000_000_000 for frame in frames)
    assert frames[-1].claimable_facts == (VerifiedFact("motion_stopped", None, "controller", 1.0),)
    assert all(frame.authorizes_actuation is False for frame in frames)
    with pytest.raises(ValueError, match="event_id does not match frame content"):
        replace(frames[0], event_sequence=99)
    assert observer.poll() == 0

    status = observer.status()
    assert status.consumed_event_sequence == 3
    assert status.fault_code is None
    mapping = status.as_dict()
    assert mapping["mode"] == "journal_only_disarmed"
    assert mapping["live_session_bound"] is False
    assert mapping["provider_bound"] is False
    assert mapping["audio_bound"] is False
    assert mapping["persistent_cursor_bound"] is False
    assert mapping["resume_parent_lineage_bound"] is False
    assert mapping["authentication_scope"] == "process_local"
    assert mapping["authorizes_actuation"] is False


def test_frame_overflow_latches_narration_closed_without_blocking_execution() -> None:
    executive = TaskExecutive()
    observer = JournalOnlyNarrativeRuntimeV1(
        executive,
        source_epoch=19,
        authentication_key=b"runtime-journal-test-key-000000002",
        monotonic_ns=lambda: 1_000_000_000,
        frame_capacity=1,
    )

    assert executive.submit(_plan("task-overflow-isolated")).accepted
    request = executive.tick(now=10.0)[0]
    assert observer.poll() == 0
    assert observer.status().fault_code == "narrative_frame_queue_overflow"
    assert observer.drain_frames() == ()

    # The optional wording lane is latched, but the authoritative task owner
    # can still accept the verified result and reach its terminal state.
    terminal = executive.report(_success(request))
    assert terminal.accepted and terminal.state == "succeeded"
    assert observer.poll() == 0
    assert observer.drain_frames() == ()
    task = executive.snapshot()["tasks"][0]
    assert task["state"] == "succeeded"


def test_queued_frame_expiry_latches_narration_without_blocking_execution() -> None:
    executive = TaskExecutive()
    clock = [1_000_000_000]
    observer = JournalOnlyNarrativeRuntimeV1(
        executive,
        source_epoch=23,
        authentication_key=b"runtime-journal-test-key-000000003",
        monotonic_ns=lambda: clock[0],
        event_ttl_ns=100,
    )

    assert executive.submit(_plan("task-expired-frame")).accepted
    request = executive.tick(now=10.0)[0]
    assert observer.poll() == 2
    clock[0] += 100

    assert observer.drain_frames() == ()
    assert observer.status().fault_code == "narrative_frame_expired_at_drain"

    terminal = executive.report(_success(request))
    assert terminal.accepted and terminal.state == "succeeded"
    assert observer.poll() == 0
    assert executive.snapshot()["tasks"][0]["state"] == "succeeded"


@pytest.mark.parametrize("wait_for", ["precondition", "resource"])
def test_next_step_wait_is_valid_owner_lineage(wait_for: str) -> None:
    executive = TaskExecutive()
    observer = JournalOnlyNarrativeRuntimeV1(
        executive,
        source_epoch=29,
        authentication_key=b"runtime-next-step-test-key-00000004",
        monotonic_ns=lambda: 1_000_000_000,
    )

    assert executive.submit(_two_step_plan(f"task-next-{wait_for}", wait_for=wait_for)).accepted
    first = executive.tick(now=10.0)[0]
    assert executive.report(_success(first)).action == "step_succeeded"
    if wait_for == "resource":
        acquired, _ = executive.resources.acquire("blocker", "step-blocker", ("base",))
        assert acquired
    assert executive.tick(now=11.0) == ()

    assert observer.poll() == 4
    frames = observer.drain_frames()
    assert [frame.status for frame in frames] == [
        "accepted",
        "started",
        "progress",
        "blocked",
    ]
    assert frames[-1].step_id.endswith("-second")
    assert frames[-1].claimable_facts == ()
    assert all(frame.authorizes_actuation is False for frame in frames)
    assert observer.status().fault_code is None


@pytest.mark.parametrize(
    "outcome",
    ("direct_success", "direct_failure", "progress_then_success"),
)
def test_resumed_running_accepts_valid_owner_result_lifecycle(outcome: str) -> None:
    executive = TaskExecutive()
    observer = JournalOnlyNarrativeRuntimeV1(
        executive,
        source_epoch=41,
        authentication_key=b"runtime-resume-lifecycle-test-key-0007",
        monotonic_ns=lambda: 1_000_000_000,
    )

    assert executive.submit(_plan(f"task-resume-{outcome}")).accepted
    executive.tick(now=10.0)[0]
    assert executive.suspend_task("task-resume-" + outcome, reason="owner_pause").accepted
    disposition, resumed = executive.resume_task_running(
        "task-resume-" + outcome,
        reason="owner_resume",
        now=10.5,
    )
    assert disposition.accepted and resumed is not None
    if outcome == "direct_failure":
        assert executive.report(_non_success(resumed, "failed")).action == "task_failed"
    else:
        if outcome == "progress_then_success":
            assert executive.report(_non_success(resumed, "in_progress")).accepted
        assert executive.report(_success(resumed)).action == "task_succeeded"

    assert observer.poll() in {5, 6}
    frames = observer.drain_frames()
    assert [frame.status for frame in frames[:4]] == [
        "accepted",
        "started",
        "suspended",
        "resumed",
    ]
    assert frames[-1].status == ("failed" if outcome == "direct_failure" else "succeeded")
    assert observer.status().fault_code is None


def test_retry_can_wait_on_attempt_two_without_false_latching_narration() -> None:
    executive = TaskExecutive()
    observer = JournalOnlyNarrativeRuntimeV1(
        executive,
        source_epoch=43,
        authentication_key=b"runtime-retry-wait-test-key-000000008",
        monotonic_ns=lambda: 1_000_000_000,
    )

    assert executive.submit(_retry_plan("task-retry-wait")).accepted
    first = executive.tick(now=10.0)[0]
    assert executive.report(_non_success(first, "failed")).action == "retry_scheduled"
    acquired, _ = executive.resources.acquire("blocker", "blocker-step", ("base",))
    assert acquired
    assert executive.tick(now=11.0) == ()

    assert observer.poll() == 4
    frames = observer.drain_frames()
    assert [frame.status for frame in frames] == ["accepted", "started", "blocked", "blocked"]
    assert [frame.attempt for frame in frames[-2:]] == [1, 2]
    assert observer.status().fault_code is None


def test_same_attempt_precondition_then_resource_wait_is_valid() -> None:
    executive = TaskExecutive()
    observer = JournalOnlyNarrativeRuntimeV1(
        executive,
        source_epoch=47,
        authentication_key=b"runtime-repeated-block-test-key-000009",
        monotonic_ns=lambda: 1_000_000_000,
    )

    assert executive.submit(_two_step_plan("task-double-wait", wait_for="precondition")).accepted
    first = executive.tick(now=10.0)[0]
    assert executive.report(_success(first)).action == "step_succeeded"
    assert executive.tick(now=10.5) == ()
    acquired, _ = executive.resources.acquire("blocker", "blocker-step", ("base",))
    assert acquired
    assert executive.tick(_fresh_snapshot(), now=11.0) == ()

    assert observer.poll() == 5
    frames = observer.drain_frames()
    assert [frame.status for frame in frames[-2:]] == ["blocked", "blocked"]
    assert [frame.attempt for frame in frames[-2:]] == [1, 1]
    assert observer.status().fault_code is None


@pytest.mark.parametrize("lifecycle", ("suspend", "cancel"))
def test_owner_can_suspend_or_cancel_between_steps(lifecycle: str) -> None:
    executive = TaskExecutive()
    observer = JournalOnlyNarrativeRuntimeV1(
        executive,
        source_epoch=53,
        authentication_key=b"runtime-between-step-test-key-0000010",
        monotonic_ns=lambda: 1_000_000_000,
    )
    task_id = f"task-between-{lifecycle}"

    assert executive.submit(_two_step_plan(task_id, wait_for="resource")).accepted
    first = executive.tick(now=10.0)[0]
    assert executive.report(_success(first)).action == "step_succeeded"
    if lifecycle == "suspend":
        assert executive.suspend_task(task_id, reason="owner_pause_between_steps").accepted
    else:
        assert executive.cancel_all("owner_cancel_between_steps").action == "cancel_now"

    assert observer.poll() == 4
    frames = observer.drain_frames()
    assert [frame.status for frame in frames] == [
        "accepted",
        "started",
        "progress",
        "suspended" if lifecycle == "suspend" else "cancelled",
    ]
    assert frames[-1].step_id.endswith("-second")
    assert observer.status().fault_code is None


def test_deferred_replacement_progress_does_not_claim_active_replan() -> None:
    executive = TaskExecutive()
    observer = JournalOnlyNarrativeRuntimeV1(
        executive,
        source_epoch=31,
        authentication_key=b"runtime-replacement-test-key-000005",
        monotonic_ns=lambda: 1_000_000_000,
    )

    assert executive.submit(_plan("task-deferred")).accepted
    request = executive.tick(now=10.0)[0]
    assert executive.replace(_plan("task-deferred", revision=2)).disposition == "defer"
    progress = ExecutionResult(
        schema_version=1,
        task_id=request.task_id,
        plan_revision=request.plan_revision,
        step_id=request.step_id,
        attempt=request.attempt,
        status="in_progress",
        feedback_code="in_progress",
        snapshot_id="snapshot-deferred",
        verified_facts=(),
        checkpoint=False,
        detail_code="controller_still_moving",
        started_at_monotonic_s=10.0,
        finished_at_monotonic_s=None,
    )
    assert executive.report(progress).action == "progress_recorded"

    assert observer.poll() == 4
    frames = observer.drain_frames()
    assert [frame.status for frame in frames] == [
        "accepted",
        "started",
        "progress",
        "progress",
    ]
    assert frames[2].detail_code == "replacement_waiting_for_checkpoint"
    assert all(frame.plan_revision == 1 for frame in frames)
    assert observer.status().fault_code is None


def test_invalid_next_step_block_latches_narration_permanently_closed() -> None:
    executive = TaskExecutive()
    observer = JournalOnlyNarrativeRuntimeV1(
        executive,
        source_epoch=37,
        authentication_key=b"runtime-corruption-test-key-000000006",
        monotonic_ns=lambda: 1_000_000_000,
    )
    plan = _two_step_plan("task-corrupt", wait_for="precondition")
    assert executive.submit(plan).accepted
    first = executive.tick(now=10.0)[0]
    assert executive.report(_success(first)).action == "step_succeeded"
    assert observer.poll() == 3
    prefix = observer.drain_frames()

    forged = build_execution_narrative_event(
        event_sequence=4,
        task_id="task-corrupt",
        plan_revision=1,
        step_id="step-task-corrupt-second",
        attempt=1,
        action_name="Hold",
        plan_sha256=prefix[0].plan_sha256,
        status="blocked",
        source_epoch=37,
        speech_generation=0,
        issued_at_monotonic_ns=1_000_000_000,
        claimable_until_monotonic_ns=6_000_000_000,
        verified_facts=(),
        evidence_refs=(),
        detail_code="forged_block_without_owner_disposition",
        resume_parent_task_id=None,
    )
    observer._bridge._events.append(observer._authenticator.authenticate(forged))

    assert observer.poll() == 0
    assert observer.status().fault_code == (
        "narrative_consumer_next_step_lineage_mismatch"
    )
    assert observer.drain_frames() == ()
    assert observer.poll() == 0
    assert executive.tick(now=11.0) == ()
    assert executive.snapshot()["tasks"][0]["state"] == "waiting_precondition"
