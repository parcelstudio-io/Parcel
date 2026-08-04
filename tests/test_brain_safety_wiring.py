"""Phase 3 wiring: battery telemetry, ReturnToSafePose, and live invariants.

These paths existed as computed-but-unread contract surface; each test here
pins the newly enforced behavior.
"""

from __future__ import annotations

import pytest

from parcel_robot.brain.contracts import BatteryStateSnapshot
from parcel_robot.brain.executive import DispatchRequest
from parcel_robot.brain.runtime_adapter import (
    SemanticRuntimeState,
    SemanticTaskRuntimeAdapter,
)
from parcel_robot.brain.validator import PlanValidator, SkillContractRegistry


def _adapter(calls: dict, *, with_safe_pose: bool = True) -> SemanticTaskRuntimeAdapter:
    def record(name):
        def _inner(*args):
            calls.setdefault(name, []).append(args)
            return f"{name} ok"

        return _inner

    return SemanticTaskRuntimeAdapter(
        navigate=record("navigate"),
        follow_formation=record("follow_formation"),
        spatial_behavior=record("spatial_behavior"),
        hold=record("hold"),
        vocalize=record("vocalize"),
        return_to_safe_pose=record("return_to_safe_pose") if with_safe_pose else None,
    )


def _request(skill: str, arguments: dict) -> DispatchRequest:
    from parcel_robot.brain.contracts import FrozenDict

    return DispatchRequest(
        task_id="parcel-task-1",
        plan_revision=1,
        step_id="step-1",
        attempt=1,
        skill=skill,
        arguments=FrozenDict(arguments),
        success=_success_for(skill),
        resources=("base", "posture", "attention"),
        timeout_s=60.0,
        recovery_action=None,
    )


def _success_for(skill: str):
    from parcel_robot.brain.contracts import SuccessCondition

    if skill == "ReturnToSafePose":
        return SuccessCondition(fact="safe_pose", target="sit")
    return SuccessCondition(fact="motion_stop_verified", target=None)


def _state(**overrides) -> SemanticRuntimeState:
    defaults = {
        "snapshot_id": "snap-1",
        "stop_confirmed": True,
        "control_feedback_fresh": True,
        "robot_moving": False,
    }
    defaults.update(overrides)
    return SemanticRuntimeState(**defaults)


def test_return_to_safe_pose_is_supported_and_dispatches_callback() -> None:
    calls: dict = {}
    adapter = _adapter(calls)
    assert "ReturnToSafePose" in adapter.SUPPORTED_SKILLS

    result = adapter.dispatch(_request("ReturnToSafePose", {"pose": "sit"}), now=1.0)

    assert result is None  # active dispatch, verified via poll
    assert calls["return_to_safe_pose"] == [("sit",)]


def test_return_to_safe_pose_without_callback_fails_closed() -> None:
    adapter = _adapter({}, with_safe_pose=False)
    with pytest.raises(RuntimeError, match="no runtime callback"):
        adapter.dispatch(_request("ReturnToSafePose", {"pose": "sit"}), now=1.0)


def test_return_to_safe_pose_completes_only_after_posture_and_stop() -> None:
    calls: dict = {}
    adapter = _adapter(calls)
    adapter.dispatch(_request("ReturnToSafePose", {"pose": "sit"}), now=1.0)

    # Stopped but posture not yet applied: still in progress.
    (progress,) = adapter.poll(_state(posture="unknown"), now=2.0)
    assert progress.status == "in_progress"
    assert progress.detail_code == "waiting_for_posture_confirmation"

    # Posture applied but robot still moving: still in progress.
    (progress,) = adapter.poll(_state(posture="sit", robot_moving=True), now=3.0)
    assert progress.status == "in_progress"

    # Posture applied and stop verified: terminal success with the fact.
    (done,) = adapter.poll(_state(posture="sit"), now=4.0)
    assert done.status == "succeeded"
    assert done.detail_code == "safe_pose_stop_verified"
    assert any(fact.fact == "safe_pose" for fact in done.verified_facts)


def test_wrong_posture_never_completes_safe_pose() -> None:
    adapter = _adapter({})
    adapter.dispatch(_request("ReturnToSafePose", {"pose": "sit"}), now=1.0)
    (progress,) = adapter.poll(_state(posture="bow"), now=2.0)
    assert progress.status == "in_progress"


def test_battery_snapshot_states() -> None:
    assert BatteryStateSnapshot(state="normal", percent=90.0, source="simulated").state == "normal"
    with pytest.raises(ValueError):
        BatteryStateSnapshot(state="unavailable", percent=50.0)


def test_return_to_safe_pose_plan_requires_critical_battery() -> None:
    """The contract's battery_critical precondition is enforced by validation.

    2026-08-04 review fix: the original test validated with no snapshot, so
    _validate_snapshot_admission (the only place the battery gate lives) never
    ran — deleting the gate left the test green. Both directions are now
    exercised through the snapshot admission path.
    """

    from parcel_robot.brain.compiler import compile_plan_contracts
    from parcel_robot.brain.contracts import (
        FrozenDict,
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
    )
    from parcel_robot.brain.validator import PlanValidationError

    def _snapshot(battery_state: str, percent: float) -> ObservationSnapshot:
        return ObservationSnapshot(
            schema_version=1,
            snapshot_id=f"snapshot-battery-{battery_state}",
            captured_at_monotonic_s=10.0,
            camera=SensorSnapshot("camera", True, True, "camera", 9.9, 100.0),
            lidar=SensorSnapshot("lidar", True, True, "lidar", 9.95, 50.0),
            robot=RobotStateSnapshot(False, "stand"),
            safety=SafetyStateSnapshot(False, False, True),
            battery=BatteryStateSnapshot(battery_state, percent, "simulated"),
            task=TaskStateSnapshot(),
            entities=(),
        )

    registry = SkillContractRegistry.default(
        owner_heading_supported=True,
        pose_names=("sit", "lie_down"),
    )
    validator = PlanValidator(registry)
    plan = compile_plan_contracts(
        PlanIR(
            schema_version=1,
            task_id="parcel-task-9",
            plan_revision=1,
            source_turn_id="turn-9",
            goal=GoalSpec(
                relation="safe_pose",
                target=GoalTarget(kind="safe_region"),
            ),
            invariants=(),
            steps=(
                PlanStep(
                    step_id="s1",
                    skill="ReturnToSafePose",
                    arguments=FrozenDict({"pose": "sit"}),
                    success=SuccessCondition(fact="safe_pose", target="sit"),
                ),
            ),
        ),
        registry,
    )
    with pytest.raises(PlanValidationError) as excinfo:
        validator.validate(plan, _snapshot("normal", 80.0))
    assert excinfo.value.code == "battery_not_critical"

    validated = validator.validate(plan, _snapshot("critical", 5.0))
    assert "keep_collision_margin" in validated.effective_invariants
    assert "avoid_road_when_not_crossing" in validated.effective_invariants
