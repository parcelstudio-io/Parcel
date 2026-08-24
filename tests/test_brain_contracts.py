import json
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

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

REPO = Path(__file__).resolve().parents[1]


def _plan(arguments: dict[str, object] | None = None) -> PlanIR:
    return PlanIR(
        schema_version=1,
        task_id="task-sidewalk",
        plan_revision=1,
        source_turn_id="turn-1",
        goal=GoalSpec("inside", GoalTarget("semantic_region", "sidewalk"), 0.4),
        invariants=(
            "keep_collision_margin",
            "avoid_road_when_not_crossing",
            "stop_on_stale_perception",
        ),
        steps=(
            PlanStep(
                step_id="navigate",
                skill="NavigateTo",
                arguments=arguments or {"directive": "walk to the sidewalk"},
                preconditions=(
                    "camera_fresh",
                    "lidar_fresh",
                    "base_available",
                    "target_grounded",
                ),
                success=SuccessCondition("inside", "sidewalk", 0.4, 0.7),
                timeout_s=90.0,
                max_attempts=2,
                recovery=("replan", "alternate_candidate"),
                resources=("base", "attention"),
            ),
        ),
    )


def _snapshot() -> ObservationSnapshot:
    return ObservationSnapshot(
        schema_version=1,
        snapshot_id="snapshot-1",
        captured_at_monotonic_s=12.0,
        camera=SensorSnapshot("camera", True, True, "camera", 11.9, 100.0),
        lidar=SensorSnapshot("lidar", True, True, "lidar", 11.95, 50.0),
        robot=RobotStateSnapshot(False, "stand", 0.0, 0.0, 0.3, 0.0),
        safety=SafetyStateSnapshot(False, False, True, 2.0, 4.0),
        battery=BatteryStateSnapshot("normal", 80.0, "unitree"),
        task=TaskStateSnapshot(),
        entities=(
            ObservedEntity(
                "region-sidewalk",
                "semantic_region",
                "sidewalk",
                0.91,
                "camera",
                11.9,
                {"candidate_id": "candidate-2"},
            ),
        ),
    )


def test_plan_snapshot_and_result_round_trip_without_loss() -> None:
    plan = _plan()
    snapshot = _snapshot()
    result = ExecutionResult(
        schema_version=1,
        task_id=plan.task_id,
        plan_revision=1,
        step_id="navigate",
        attempt=1,
        status="succeeded",
        feedback_code="succeeded",
        snapshot_id=snapshot.snapshot_id,
        verified_facts=(VerifiedFact("inside", "sidewalk", "camera", 0.92),),
        checkpoint=True,
        detail_code="goal_region_verified",
        started_at_monotonic_s=12.0,
        finished_at_monotonic_s=14.0,
    )

    assert PlanIR.from_mapping(plan.as_dict()) == plan
    assert ObservationSnapshot.from_mapping(snapshot.as_dict()) == snapshot
    assert ExecutionResult.from_mapping(result.as_dict()) == result


def test_contracts_are_frozen_and_copy_nested_model_arguments() -> None:
    original = {"directive": "sidewalk", "metadata": {"candidate": ["a", "b"]}}
    plan = _plan(original)
    original["directive"] = "road"
    original["metadata"]["candidate"].append("unsafe")

    assert plan.steps[0].arguments["directive"] == "sidewalk"
    assert plan.steps[0].arguments.to_dict()["metadata"] == {"candidate": ["a", "b"]}
    with pytest.raises(FrozenInstanceError):
        plan.plan_revision = 2  # type: ignore[misc]
    with pytest.raises(TypeError, match="steps must be a tuple"):
        PlanIR(
            schema_version=plan.schema_version,
            task_id=plan.task_id,
            plan_revision=plan.plan_revision,
            source_turn_id=plan.source_turn_id,
            goal=plan.goal,
            invariants=plan.invariants,
            steps=list(plan.steps),  # type: ignore[arg-type]
        )


def test_contract_parser_rejects_unknown_fields_versions_and_non_finite_values() -> None:
    payload = _plan().as_dict()
    payload["model_priority"] = 999
    with pytest.raises(ValueError, match="unknown"):
        PlanIR.from_mapping(payload)

    payload = _plan().as_dict()
    payload["schema_version"] = 2
    with pytest.raises(ValueError, match=r"schema[_ ]version"):
        PlanIR.from_mapping(payload)

    with pytest.raises(ValueError, match="finite"):
        _plan({"directive": "sidewalk", "confidence": float("nan")})


def test_nested_json_depth_is_bounded() -> None:
    nested: dict[str, object] = {"value": "end"}
    for _ in range(8):
        nested = {"nested": nested}
    with pytest.raises(ValueError, match="nesting depth"):
        _plan({"directive": "sidewalk", "metadata": nested})


def test_execution_result_enforces_terminal_timestamps() -> None:
    common = {
        "schema_version": 1,
        "task_id": "task-1",
        "plan_revision": 1,
        "step_id": "step-1",
        "attempt": 1,
        "feedback_code": "in_progress",
        "snapshot_id": None,
        "verified_facts": (),
        "checkpoint": False,
        "detail_code": "moving",
        "started_at_monotonic_s": 1.0,
    }
    with pytest.raises(ValueError, match="in-progress"):
        ExecutionResult(status="in_progress", finished_at_monotonic_s=2.0, **common)
    with pytest.raises(ValueError, match="requires a finish time"):
        ExecutionResult(status="failed", finished_at_monotonic_s=None, **common)


def test_machine_schemas_are_json_and_close_every_object_shape() -> None:
    schema_dir = REPO / "prompts" / "schemas"
    paths = tuple(sorted(schema_dir.glob("*_v1.schema.json")))
    assert {path.name for path in paths} >= {
        "execution_result_v1.schema.json",
        "intent_frame_v1.schema.json",
        "observation_snapshot_v1.schema.json",
        "plan_ir_v1.schema.json",
    }
    for path in paths:
        document = json.loads(path.read_text(encoding="utf-8"))
        assert document["$schema"].endswith("2020-12/schema")
        _assert_object_schemas_are_closed(document)


def _assert_object_schemas_are_closed(value: object) -> None:
    if isinstance(value, dict):
        if value.get("type") == "object" and "properties" in value:
            assert value.get("additionalProperties") is False
        for child in value.values():
            _assert_object_schemas_are_closed(child)
    elif isinstance(value, list):
        for child in value:
            _assert_object_schemas_are_closed(child)
