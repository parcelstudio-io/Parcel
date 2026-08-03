from dataclasses import replace
from pathlib import Path

import pytest

from parcel_robot.brain import (
    DeterministicIntentRouter,
    PlanIR,
    PlanSketch,
    PlanValidationError,
    PlanValidator,
    SkillContractRegistry,
    TaskStateSnapshot,
    admitted_plan_sketch_schema,
    compile_plan_sketch,
    contextual_planner_schema,
    materialize_planner_output,
)
from parcel_robot.brain.observations import build_observation_snapshot
from parcel_robot.prompting import PromptLibrary

REPO = Path(__file__).resolve().parents[1]


def _frame(*, correction: bool = False):
    transcript = (
        "Actually, wait by the lamppost instead."
        if correction
        else "Walk to the sidewalk and then wait by the lamppost."
    )
    return DeterministicIntentRouter().route(
        transcript,
        turn_id="turn-plan-sketch",
    )


def _snapshot(*, active: bool = False):
    task = (
        TaskStateSnapshot(
            state="running",
            task_id="active-navigation",
            plan_revision=7,
            step_id="step_1",
            at_checkpoint=False,
        )
        if active
        else None
    )
    return build_observation_snapshot(
        None,
        snapshot_id="snapshot-plan-sketch",
        now=10.0,
        task=task,
    )


def _multi_target_sketch() -> PlanSketch:
    return PlanSketch.from_mapping(
        {
            "schema_version": 1,
            "goal": {
                "relation": "near",
                "kind": "semantic_object",
                "query": "lamppost",
            },
            "steps": [
                {
                    "skill": "NavigateTo",
                    "arguments": {"directive": "sidewalk"},
                    "navigation": {"relation": "inside", "target": "sidewalk"},
                },
                {
                    "skill": "NavigateTo",
                    "arguments": {"directive": "lamppost"},
                    "navigation": {"relation": "near", "target": "lamppost"},
                },
                {"skill": "Hold", "arguments": {}, "navigation": None},
            ],
        }
    )


def test_plansketch_round_trips_only_model_owned_semantics() -> None:
    sketch = _multi_target_sketch()

    assert PlanSketch.from_mapping(sketch.as_dict()) == sketch
    assert set(sketch.as_dict()) == {"schema_version", "goal", "steps"}
    assert "task_id" not in sketch.as_dict()
    assert "resources" not in sketch.as_dict()["steps"][0]
    with pytest.raises(ValueError, match="fields are invalid"):
        PlanSketch.from_mapping({**sketch.as_dict(), "task_id": "model-task"})


def test_plansketch_compiles_trusted_envelope_and_system_boilerplate() -> None:
    registry = SkillContractRegistry.default().restricted(("NavigateTo", "Hold"))
    frame = _frame()

    plan = compile_plan_sketch(_multi_target_sketch(), frame, _snapshot(), registry)

    assert plan.source_turn_id == frame.turn_id
    assert plan.task_id.startswith("parcel-task-")
    assert plan.plan_revision == 1
    assert plan.requested_interrupt == "at_checkpoint"
    assert plan.goal.as_dict() == {
        "relation": "near",
        "target": {"kind": "semantic_object", "query": "lamppost"},
        "tolerance_m": 0.0,
    }
    assert [step.step_id for step in plan.steps] == ["step_1", "step_2", "step_3"]
    assert [step.success.fact for step in plan.steps] == [
        "inside",
        "near",
        "motion_stopped",
    ]
    assert [step.success.target for step in plan.steps] == [
        "sidewalk",
        "lamppost",
        None,
    ]
    assert plan.steps[0].preconditions == (
        "base_available",
        "camera_fresh",
        "lidar_fresh",
        "target_grounded",
    )
    assert plan.steps[0].resources == ("base", "attention")
    assert plan.steps[0].timeout_s == 120.0
    assert plan.steps[0].max_attempts == 1
    assert plan.steps[0].recovery == ("safe_stop",)
    assert PlanValidator(registry).validate(plan).plan == plan


def test_plansketch_correction_uses_active_task_revision_not_model_metadata() -> None:
    registry = SkillContractRegistry.default().restricted(("NavigateTo", "Hold"))
    frame = _frame(correction=True)

    plan = compile_plan_sketch(_multi_target_sketch(), frame, _snapshot(active=True), registry)

    assert frame.speech_act == "correction"
    assert plan.task_id == "active-navigation"
    assert plan.plan_revision == 8
    assert plan.source_turn_id == "turn-plan-sketch"


def test_plansketch_requires_explicit_navigation_grounding_and_never_repairs_it() -> None:
    payload = _multi_target_sketch().as_dict()
    payload["steps"][0]["navigation"] = None
    with pytest.raises(ValueError, match="requires explicit navigation grounding"):
        PlanSketch.from_mapping(payload)

    mismatch = _multi_target_sketch().as_dict()
    mismatch["steps"][0]["arguments"] = {"directive": "lamppost"}
    sketch = PlanSketch.from_mapping(mismatch)
    registry = SkillContractRegistry.default().restricted(("NavigateTo", "Hold"))
    plan = compile_plan_sketch(sketch, _frame(), _snapshot(), registry)

    assert plan.steps[0].arguments["directive"] == "lamppost"
    assert plan.steps[0].success.target == "sidewalk"
    with pytest.raises(PlanValidationError, match="navigation_directive_mismatch"):
        PlanValidator(registry).validate(plan)


def test_plansketch_does_not_repair_invalid_skill_arguments() -> None:
    sketch = PlanSketch.from_mapping(
        {
            "schema_version": 1,
            "goal": {"relation": "relative", "kind": "owner", "query": "owner"},
            "steps": [
                {
                    "skill": "MoveRelative",
                    "arguments": {"direction": "lateral", "steps": 5},
                    "navigation": None,
                }
            ],
        }
    )
    registry = SkillContractRegistry.default().restricted(("MoveRelative",))
    plan = compile_plan_sketch(sketch, _frame(), _snapshot(), registry)

    assert plan.steps[0].arguments["direction"] == "lateral"
    with pytest.raises(PlanValidationError, match="invalid_argument_value"):
        PlanValidator(registry).validate(plan)


def test_non_navigation_skill_cannot_smuggle_navigation_grounding() -> None:
    payload = {
        "schema_version": 1,
        "goal": {"relation": "hold", "kind": "current_pose", "query": ""},
        "steps": [
            {
                "skill": "Hold",
                "arguments": {},
                "navigation": {"relation": "near", "target": "owner"},
            }
        ],
    }

    with pytest.raises(ValueError, match="only NavigateTo"):
        PlanSketch.from_mapping(payload)


def test_plansketch_schema_is_restricted_and_never_exposes_provenance() -> None:
    library = PromptLibrary(REPO / "prompts")
    source = library.schema("plan_sketch_v1.schema.json")

    restricted = admitted_plan_sketch_schema(source, ("NavigateTo", "Hold"))
    contextual = contextual_planner_schema(restricted, _frame(), _snapshot())

    assert restricted["$defs"]["step"]["properties"]["skill"]["enum"] == [
        "Hold",
        "NavigateTo",
    ]
    assert source["$defs"]["step"]["properties"]["skill"]["enum"][0] == ("NavigateTo")
    assert contextual == restricted
    assert contextual is not restricted
    assert set(contextual["properties"]) == {"schema_version", "goal", "steps"}
    assert "PlanSketch v1 JSON object" in library.planner_system("plan_sketch_v1")
    with pytest.raises(ValueError, match="unsupported planner output contract"):
        library.planner_system("untrusted_contract")
    with pytest.raises(ValueError, match="unsupported planner output contract"):
        contextual_planner_schema(
            {"type": "object", "x-parcel-output-contract": "untrusted_contract"},
            _frame(),
            _snapshot(),
        )


def test_materializer_preserves_legacy_planir_mode() -> None:
    registry = SkillContractRegistry.default().restricted(("Hold",))
    sketch_plan = compile_plan_sketch(
        PlanSketch.from_mapping(
            {
                "schema_version": 1,
                "goal": {"relation": "hold", "kind": "current_pose", "query": ""},
                "steps": [{"skill": "Hold", "arguments": {}, "navigation": None}],
            }
        ),
        _frame(),
        _snapshot(),
        registry,
    )
    untrusted_legacy = replace(
        sketch_plan,
        task_id="model-task",
        source_turn_id="model-turn",
    )

    materialized = materialize_planner_output(
        untrusted_legacy,
        _frame(),
        _snapshot(),
        registry,
    )

    assert isinstance(materialized, PlanIR)
    assert materialized.task_id.startswith("parcel-task-")
    assert materialized.source_turn_id == "turn-plan-sketch"
    assert materialized.steps == untrusted_legacy.steps
