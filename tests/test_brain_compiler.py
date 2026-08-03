import pytest

from parcel_robot.brain import (
    PlanIR,
    PlanValidationError,
    PlanValidator,
    SkillContractRegistry,
    compile_plan_contracts,
)


def _relative_plan(direction: str = "away_from_owner") -> PlanIR:
    return PlanIR.from_mapping(
        {
            "schema_version": 1,
            "task_id": "trusted-task",
            "plan_revision": 1,
            "source_turn_id": "trusted-turn",
            "goal": {
                "relation": "relative",
                "target": {"kind": "owner", "query": "owner"},
                "tolerance_m": 4.5,
            },
            "invariants": ["keep_collision_margin"],
            "steps": [
                {
                    "id": "model-chosen-step",
                    "skill": "MoveRelative",
                    "arguments": {"direction": direction, "steps": 5},
                    "preconditions": [],
                    "success": {
                        "fact": "model_claim",
                        "target": "owner",
                        "tolerance_m": None,
                        "confidence_min": 0.25,
                    },
                    "timeout_s": 1.0,
                    "max_attempts": 3,
                    "recovery": ["safe_stop"],
                    "resources": [],
                    "interruptibility": "immediate",
                }
            ],
            "requested_interrupt": "interrupt_now",
        }
    )


def test_compiler_owns_contract_boilerplate_but_preserves_semantic_arguments() -> None:
    registry = SkillContractRegistry.default().restricted(("MoveRelative",))

    compiled = compile_plan_contracts(_relative_plan(), registry)
    step = compiled.steps[0]

    assert compiled.task_id == "trusted-task"
    assert compiled.source_turn_id == "trusted-turn"
    assert compiled.goal.relation == "relative"
    assert compiled.goal.tolerance_m == 0.0
    assert compiled.invariants == ()
    assert compiled.requested_interrupt == "at_checkpoint"
    assert step.step_id == "step_1"
    assert step.arguments.to_dict() == {
        "direction": "away_from_owner",
        "steps": 5,
    }
    assert step.preconditions == (
        "base_available",
        "lidar_fresh",
        "owner_visible",
    )
    assert step.success.as_dict() == {
        "fact": "distance_travelled",
        "target": None,
        "tolerance_m": None,
        "confidence_min": None,
    }
    assert step.timeout_s == 60.0
    assert step.max_attempts == 1
    assert step.recovery == ("safe_stop",)
    assert step.resources == ("base",)
    assert step.interruptibility == "checkpoint"
    assert PlanValidator(registry).validate(compiled).plan == compiled


def test_compiler_does_not_repair_invalid_model_owned_arguments() -> None:
    registry = SkillContractRegistry.default().restricted(("MoveRelative",))
    compiled = compile_plan_contracts(_relative_plan("away"), registry)

    with pytest.raises(PlanValidationError, match="invalid_argument_value"):
        PlanValidator(registry).validate(compiled)


def test_compiler_does_not_fabricate_navigation_grounding() -> None:
    registry = SkillContractRegistry.default().restricted(("NavigateTo",))
    proposed = PlanIR.from_mapping(
        {
            "schema_version": 1,
            "task_id": "trusted-navigation",
            "plan_revision": 1,
            "source_turn_id": "trusted-turn",
            "goal": {
                "relation": "inside",
                "target": {"kind": "semantic_region", "query": "sidewalk"},
                "tolerance_m": 0.0,
            },
            "invariants": [],
            "steps": [
                {
                    "id": "navigate",
                    "skill": "NavigateTo",
                    "arguments": {"directive": "sidewalk"},
                    "preconditions": [],
                    "success": {
                        "fact": "inside",
                        "target": None,
                        "tolerance_m": None,
                        "confidence_min": None,
                    },
                    "timeout_s": 1.0,
                    "max_attempts": 1,
                    "recovery": [],
                    "resources": [],
                    "interruptibility": "immediate",
                }
            ],
            "requested_interrupt": "at_checkpoint",
        }
    )

    compiled = compile_plan_contracts(proposed, registry)

    assert compiled.steps[0].success.target is None
    with pytest.raises(PlanValidationError, match="invalid_success_target"):
        PlanValidator(registry).validate(compiled)
