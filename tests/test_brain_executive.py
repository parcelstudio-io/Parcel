from parcel_robot.brain.contracts import (
    BatteryStateSnapshot,
    ExecutionResult,
    GoalSpec,
    GoalTarget,
    ObservationSnapshot,
    ObservedEntity,
    PlanIR,
    PlanStep,
    RobotStateSnapshot,
    SafetyStateSnapshot,
    SensorSnapshot,
    SuccessCondition,
    TaskStateSnapshot,
    VerifiedFact,
)
from parcel_robot.brain.executive import InterruptRequest, ResourceLocks, TaskExecutive
from parcel_robot.brain.validator import PlanValidator, SkillContractRegistry


def _snapshot(
    *,
    critical: bool = False,
    emergency: bool = False,
    entity_labels: tuple[str, ...] = (),
) -> ObservationSnapshot:
    return ObservationSnapshot(
        schema_version=1,
        snapshot_id="snapshot-exec",
        captured_at_monotonic_s=10.0,
        camera=SensorSnapshot("camera", True, True, "camera", 9.9, 100.0),
        lidar=SensorSnapshot("lidar", True, True, "lidar", 9.95, 50.0),
        robot=RobotStateSnapshot(False, "stand"),
        safety=SafetyStateSnapshot(emergency, False, True),
        battery=BatteryStateSnapshot(
            "critical" if critical else "normal",
            5.0 if critical else 80.0,
            "unitree",
        ),
        task=TaskStateSnapshot(),
        entities=tuple(
            ObservedEntity(
                f"{label}-1",
                "semantic_region" if label == "sidewalk" else "semantic_object",
                label,
                0.95,
                "camera",
                9.9,
                {},
            )
            for label in entity_labels
        ),
    )


def _hold_plan(task_id: str, *, revision: int = 1, attempts: int = 1) -> PlanIR:
    return PlanIR(
        schema_version=1,
        task_id=task_id,
        plan_revision=revision,
        source_turn_id=f"turn-{task_id}",
        goal=GoalSpec("hold", GoalTarget("current_pose"), 0.0),
        invariants=("keep_collision_margin",),
        steps=(
            PlanStep(
                "hold",
                "Hold",
                {},
                ("base_available",),
                SuccessCondition("motion_stopped"),
                5.0,
                attempts,
                ("safe_stop",) if attempts > 1 else (),
                ("base",),
                "checkpoint",
            ),
        ),
    )


def _voice_plan(task_id: str) -> PlanIR:
    return PlanIR(
        schema_version=1,
        task_id=task_id,
        plan_revision=1,
        source_turn_id=f"turn-{task_id}",
        goal=GoalSpec("hold", GoalTarget("current_pose"), 0.0),
        invariants=(),
        steps=(
            PlanStep(
                "speak",
                "Vocalize",
                {"text": "I'm right here."},
                ("voice_available",),
                SuccessCondition("utterance_sent"),
                5.0,
                1,
                (),
                ("voice",),
                "immediate",
            ),
        ),
    )


def _critical_plan(task_id: str, *, revision: int = 1) -> PlanIR:
    return PlanIR(
        schema_version=1,
        task_id=task_id,
        plan_revision=revision,
        source_turn_id="turn-battery",
        goal=GoalSpec("safe_pose", GoalTarget("safe_region", "safe region"), 0.5),
        invariants=(
            "keep_collision_margin",
            "stop_on_stale_perception",
            "do_not_interrupt_critical_task",
        ),
        steps=(
            PlanStep(
                "return-safe",
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


def _two_target_plan() -> PlanIR:
    preconditions = (
        "camera_fresh",
        "lidar_fresh",
        "base_available",
        "target_grounded",
    )
    return PlanIR(
        schema_version=1,
        task_id="two-targets",
        plan_revision=1,
        source_turn_id="turn-two-targets",
        goal=GoalSpec("near", GoalTarget("semantic_object", "lamppost"), 1.0),
        invariants=(),
        steps=(
            PlanStep(
                "sidewalk",
                "NavigateTo",
                {"directive": "sidewalk"},
                preconditions,
                SuccessCondition("inside", "sidewalk", None, 0.7),
                90.0,
                1,
                (),
                ("base", "attention"),
                "checkpoint",
            ),
            PlanStep(
                "lamppost",
                "NavigateTo",
                {"directive": "lamppost"},
                preconditions,
                SuccessCondition("near", "lamppost", None, 0.7),
                90.0,
                1,
                (),
                ("base", "attention"),
                "checkpoint",
            ),
        ),
    )


def _validated(plan: PlanIR, *, critical: bool = False):
    registry = SkillContractRegistry.default(pose_names=("sit",))
    return PlanValidator(registry).validate(plan, _snapshot(critical=critical))


def _result(request, status: str, *, checkpoint: bool = True) -> ExecutionResult:
    terminal = status != "in_progress"
    success_facts = {
        "Hold": VerifiedFact("motion_stopped", None, "controller", 1.0),
        "Vocalize": VerifiedFact("utterance_sent", None, "voice_adapter", 1.0),
        "ReturnToSafePose": VerifiedFact("safe_pose", None, "controller", 1.0),
    }
    return ExecutionResult(
        schema_version=1,
        task_id=request.task_id,
        plan_revision=request.plan_revision,
        step_id=request.step_id,
        attempt=request.attempt,
        status=status,
        feedback_code=status,
        snapshot_id="snapshot-exec",
        verified_facts=(success_facts[request.skill],) if status == "succeeded" else (),
        checkpoint=checkpoint,
        detail_code=status,
        started_at_monotonic_s=10.0,
        finished_at_monotonic_s=11.0 if terminal else None,
    )


def test_voice_can_overlap_base_but_two_base_tasks_cannot() -> None:
    executive = TaskExecutive()
    executive.submit(_validated(_hold_plan("move")), task_class="active_task")
    move = executive.tick(_snapshot(), now=10.0)[0]

    executive.submit(_validated(_voice_plan("voice")), task_class="voice")
    voice = executive.tick(_snapshot(), now=10.1)[0]
    executive.submit(_validated(_hold_plan("other")), task_class="explicit_action")

    assert move.resources == ("base",)
    assert move.success.fact == "motion_stopped"
    assert voice.resources == ("voice",)
    assert voice.success.fact == "utterance_sent"
    assert executive.tick(_snapshot(), now=10.2) == ()
    assert {lease.resource for lease in executive.resources.leases()} == {"base", "voice"}


def test_correction_replaces_only_at_checkpoint_and_stale_feedback_is_ignored() -> None:
    executive = TaskExecutive()
    executive.submit(_validated(_hold_plan("task")))
    old = executive.tick(_snapshot(), now=10.0)[0]
    submission = executive.replace(_validated(_hold_plan("task", revision=2)))

    assert submission.disposition == "defer"
    disposition = executive.report(_result(old, "in_progress", checkpoint=True))
    assert disposition.action == "replacement_activated_at_checkpoint"
    assert executive.report(_result(old, "succeeded")).action == "ignored_stale_result"

    new = executive.tick(_snapshot(), now=12.0)[0]
    assert new.plan_revision == 2
    assert new.attempt == 1


def test_system_stop_overrides_but_social_behavior_does_not() -> None:
    executive = TaskExecutive()
    executive.submit(_validated(_hold_plan("task")))
    executive.tick(_snapshot(), now=10.0)

    social = executive.request_interrupt(
        InterruptRequest("social", "react to laughter", "when_idle")
    )
    assert social.action == "defer_when_idle"
    assert executive.resources.leases()

    stopped = executive.request_interrupt(
        InterruptRequest("explicit_stop", "owner said stop", "interrupt_now")
    )
    assert stopped.action == "cancel_now"
    assert executive.resources.leases() == ()


def test_retry_is_bounded_and_recovery_is_system_visible() -> None:
    executive = TaskExecutive()
    executive.submit(_validated(_hold_plan("retry", attempts=2)))
    first = executive.tick(_snapshot(), now=10.0)[0]

    disposition = executive.report(_result(first, "blocked"))
    assert disposition.action == "retry_scheduled"
    retry = executive.tick(_snapshot(), now=12.0)[0]
    assert retry.attempt == 2
    assert retry.recovery_action == "safe_stop"

    final = executive.report(_result(retry, "blocked"))
    assert final.action == "task_failed"
    assert executive.resources.leases() == ()


def test_non_interruptible_system_step_finishes_before_replacement() -> None:
    executive = TaskExecutive()
    executive.submit(
        _validated(_critical_plan("battery"), critical=True), task_class="system"
    )
    active = executive.tick(_snapshot(critical=True), now=10.0)[0]
    replacement = executive.replace(_validated(_hold_plan("battery", revision=2)))

    assert replacement.disposition == "defer"
    progress = executive.report(_result(active, "in_progress", checkpoint=True))
    assert progress.action == "progress_recorded"
    assert executive.snapshot()["tasks"][0]["plan_revision"] == 1
    correction = executive.request_interrupt(
        InterruptRequest("correction", "owner changed request", target_task_id="battery")
    )
    assert correction.action == "defer_when_idle"

    disposition = executive.report(_result(active, "succeeded"))
    assert disposition.action == "replacement_activated_after_step"
    assert executive.tick(_snapshot(), now=12.0)[0].plan_revision == 2


def test_unverified_success_claim_fails_closed() -> None:
    executive = TaskExecutive()
    executive.submit(_validated(_hold_plan("task")))
    request = executive.tick(_snapshot(), now=10.0)[0]
    claimed = _result(request, "succeeded")
    claimed = ExecutionResult.from_mapping(
        {**claimed.as_dict(), "verified_facts": []}
    )

    disposition = executive.report(claimed)
    assert disposition.action == "task_failed"
    assert executive.snapshot()["tasks"][0]["last_detail"] == (
        "success_condition_not_verified"
    )


def test_emergency_stop_blocks_even_resource_only_dispatch() -> None:
    executive = TaskExecutive()
    executive.submit(_validated(_hold_plan("task")))
    assert executive.tick(_snapshot(emergency=True), now=10.0) == ()


def test_each_compound_navigation_step_waits_for_its_own_grounded_target() -> None:
    executive = TaskExecutive()
    validated = PlanValidator().validate(_two_target_plan())
    executive.submit(validated)

    assert executive.tick(_snapshot(entity_labels=("lamppost",)), now=10.0) == ()
    sidewalk_request = executive.tick(
        _snapshot(entity_labels=("sidewalk",)),
        now=10.1,
    )[0]
    assert sidewalk_request.step_id == "sidewalk"
    executive.report(
        ExecutionResult(
            schema_version=1,
            task_id=sidewalk_request.task_id,
            plan_revision=sidewalk_request.plan_revision,
            step_id=sidewalk_request.step_id,
            attempt=sidewalk_request.attempt,
            status="succeeded",
            feedback_code="succeeded",
            snapshot_id="snapshot-exec",
            verified_facts=(VerifiedFact("inside", "sidewalk", "camera", 0.95),),
            checkpoint=True,
            detail_code="inside_sidewalk",
            started_at_monotonic_s=10.1,
            finished_at_monotonic_s=10.2,
        )
    )

    assert executive.tick(_snapshot(entity_labels=("sidewalk",)), now=10.3) == ()
    lamppost_request = executive.tick(
        _snapshot(entity_labels=("lamppost",)),
        now=10.4,
    )[0]
    assert lamppost_request.step_id == "lamppost"
    assert lamppost_request.success.target == "lamppost"


def test_task_records_are_bounded_and_old_terminal_records_are_pruned() -> None:
    executive = TaskExecutive(max_records=1)
    executive.submit(_validated(_hold_plan("one")))
    rejected = executive.submit(_validated(_voice_plan("two")), task_class="voice")
    assert rejected.accepted is False
    assert rejected.disposition == "reject_capacity"

    request = executive.tick(_snapshot(), now=10.0)[0]
    executive.report(_result(request, "succeeded"))
    admitted = executive.submit(_validated(_voice_plan("two")), task_class="voice")
    assert admitted.accepted is True
    assert [item["task_id"] for item in executive.snapshot()["tasks"]] == ["two"]


def test_resource_locks_release_only_the_exact_owner() -> None:
    locks = ResourceLocks()
    assert locks.acquire("one", "step", ("base",))[0]
    acquired, conflicts = locks.acquire("two", "step", ("base",))
    assert not acquired
    assert conflicts[0].owner_task_id == "one"

    locks.release("two")
    assert locks.leases()[0].owner_task_id == "one"
    locks.release("one", "step")
    assert locks.leases() == ()


def test_suspend_tick_does_not_redispatch() -> None:
    """suspend → tick → still suspended, no new DispatchRequest."""

    executive = TaskExecutive()
    executive.submit(_validated(_hold_plan("nav-hold")))
    request = executive.tick(_snapshot(), now=10.0)[0]
    assert request.skill == "Hold"
    disposition = executive.suspend_task(request.task_id, reason="owner summons")
    assert disposition.accepted is True
    assert disposition.state == "suspended"
    assert executive.tick(_snapshot(), now=10.5) == ()
    assert executive.snapshot()["tasks"][0]["state"] == "suspended"
    resumed = executive.resume_task(request.task_id, reason="summons_done")
    assert resumed.accepted is True
    assert resumed.state == "queued"
    again = executive.tick(_snapshot(), now=11.0)
    assert len(again) == 1
    assert again[0].task_id == request.task_id
    assert again[0].skill == "Hold"
