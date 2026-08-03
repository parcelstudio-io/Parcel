import json
from dataclasses import replace

import pytest

from parcel_robot.brain import (
    BatteryStateSnapshot,
    GoalSpec,
    GoalTarget,
    ObservationSnapshot,
    ObservedEntity,
    PlanIR,
    PlanStep,
    PlanValidationError,
    PlanValidator,
    RobotStateSnapshot,
    SafetyStateSnapshot,
    SensorSnapshot,
    SkillContractRegistry,
    SuccessCondition,
    TaskStateSnapshot,
)


def _snapshot(
    *,
    camera_fresh: bool = True,
    lidar_fresh: bool = True,
    emergency_stopped: bool = False,
    battery_state: str = "normal",
    owner_heading: bool = True,
) -> ObservationSnapshot:
    battery_percent = 5.0 if battery_state == "critical" else 80.0
    return ObservationSnapshot(
        schema_version=1,
        snapshot_id="snapshot-1",
        captured_at_monotonic_s=10.0,
        camera=SensorSnapshot(
            "camera", True, camera_fresh, "camera", 9.9, 100.0
        ),
        lidar=SensorSnapshot("lidar", True, lidar_fresh, "lidar", 9.95, 50.0),
        robot=RobotStateSnapshot(False, "stand", 0.0, 0.0, 0.3, 0.0),
        safety=SafetyStateSnapshot(emergency_stopped, False, True, 3.0, 4.0),
        battery=BatteryStateSnapshot(battery_state, battery_percent, "unitree"),
        task=TaskStateSnapshot(),
        entities=(
            ObservedEntity(
                "owner-1",
                "owner",
                "owner",
                0.95,
                "camera",
                9.9,
                {"motion_heading_available": owner_heading},
            ),
            ObservedEntity(
                "sidewalk-1",
                "semantic_region",
                "sidewalk",
                0.9,
                "camera",
                9.9,
                {},
            ),
        ),
    )


def _navigate_plan(
    *,
    arguments: dict[str, object] | None = None,
    resources: tuple[str, ...] = ("base", "attention"),
    invariants: tuple[str, ...] = (
        "keep_collision_margin",
        "avoid_road_when_not_crossing",
        "stop_on_stale_perception",
    ),
) -> PlanIR:
    return PlanIR(
        schema_version=1,
        task_id="task-sidewalk",
        plan_revision=1,
        source_turn_id="turn-1",
        goal=GoalSpec("inside", GoalTarget("semantic_region", "sidewalk"), 0.4),
        invariants=invariants,
        steps=(
            PlanStep(
                "navigate",
                "NavigateTo",
                arguments or {"directive": "walk to sidewalk"},
                (
                    "camera_fresh",
                    "lidar_fresh",
                    "base_available",
                    "target_grounded",
                ),
                SuccessCondition("inside", "sidewalk", None, 0.7),
                90.0,
                2,
                ("replan", "alternate_candidate"),
                resources,
                "checkpoint",
            ),
        ),
    )


def _follow_plan() -> PlanIR:
    return PlanIR(
        schema_version=1,
        task_id="task-follow",
        plan_revision=1,
        source_turn_id="turn-follow",
        goal=GoalSpec("behind", GoalTarget("owner", "owner"), 0.5),
        invariants=("keep_collision_margin", "stop_on_stale_perception"),
        steps=(
            PlanStep(
                "follow",
                "FollowFormation",
                {"relation": "behind", "distance_m": 1.5},
                (
                    "camera_fresh",
                    "lidar_fresh",
                    "base_available",
                    "owner_visible",
                    "owner_heading_available",
                ),
                SuccessCondition("behind", "owner", None, 0.7),
                120.0,
                2,
                ("reacquire_owner", "replan"),
                ("base", "attention"),
                "checkpoint",
            ),
        ),
    )


def _sidewalk_then_lamppost_plan() -> PlanIR:
    preconditions = (
        "camera_fresh",
        "lidar_fresh",
        "base_available",
        "target_grounded",
    )
    return PlanIR(
        schema_version=1,
        task_id="task-sidewalk-then-lamppost",
        plan_revision=1,
        source_turn_id="turn-compound",
        goal=GoalSpec("near", GoalTarget("semantic_object", "lamppost"), 1.0),
        invariants=(),
        steps=(
            PlanStep(
                "enter-sidewalk",
                "NavigateTo",
                {"directive": "sidewalk"},
                preconditions,
                SuccessCondition("inside", "sidewalk", None, 0.7),
                90.0,
                1,
                ("replan",),
                ("base", "attention"),
                "checkpoint",
            ),
            PlanStep(
                "approach-lamppost",
                "NavigateTo",
                {"directive": "lamppost"},
                preconditions,
                SuccessCondition("near", "lamppost", None, 0.7),
                90.0,
                1,
                ("replan",),
                ("base", "attention"),
                "checkpoint",
            ),
        ),
    )


def test_valid_semantic_plan_is_deterministic_and_snapshot_bound() -> None:
    validator = PlanValidator()
    first = validator.validate(_navigate_plan(), _snapshot())
    second = validator.validate(_navigate_plan(), _snapshot())

    assert first.plan_sha256 == second.plan_sha256
    assert first.validated_against_snapshot_id == "snapshot-1"
    assert first.steps[0].effective_resources == ("base", "attention")


def test_terminal_hold_can_settle_without_erasing_the_spatial_goal() -> None:
    navigate = _navigate_plan()
    hold = PlanStep(
        "settle",
        "Hold",
        {},
        ("base_available",),
        SuccessCondition("motion_stopped"),
        5.0,
        1,
        ("safe_stop",),
        ("base",),
        "immediate",
    )

    validated = PlanValidator().validate(
        replace(navigate, steps=(*navigate.steps, hold)),
        _snapshot(),
    )

    assert [step.step.skill for step in validated.steps] == ["NavigateTo", "Hold"]


@pytest.mark.parametrize(
    ("plan", "code"),
    [
        (
            _navigate_plan(arguments={"directive": "sidewalk", "vx": 50.0}),
            "raw_control_argument",
        ),
        (_navigate_plan(resources=("base",)), "resource_mismatch"),
    ],
)
def test_adversarial_plans_fail_closed(plan: PlanIR, code: str) -> None:
    with pytest.raises(PlanValidationError) as error:
        PlanValidator().validate(plan, _snapshot())
    assert error.value.code == code


def test_safety_invariants_are_compiled_by_the_system_not_the_model() -> None:
    validator = PlanValidator()

    omitted = validator.validate(_navigate_plan(invariants=()), _snapshot())
    overdeclared = validator.validate(
        _navigate_plan(invariants=("stay_within_local_orbit",)),
        _snapshot(),
    )

    expected = (
        "keep_collision_margin",
        "avoid_road_when_not_crossing",
        "stop_on_stale_perception",
        "yield_to_people",
        "do_not_interrupt_critical_task",
    )
    assert omitted.effective_invariants == expected
    assert overdeclared.effective_invariants == expected
    assert omitted.plan_sha256 != overdeclared.plan_sha256


def test_unknown_skill_is_never_dispatched_by_name() -> None:
    payload = _navigate_plan().as_dict()
    payload["steps"][0]["skill"] = "SetVelocity"
    plan = PlanIR.from_mapping(payload)
    with pytest.raises(PlanValidationError) as error:
        PlanValidator().validate(plan)
    assert error.value.code == "unknown_skill"


def test_speech_only_plan_cannot_claim_that_a_physical_goal_was_achieved() -> None:
    payload = _voice_plan_payload()
    payload["goal"] = {
        "relation": "inside",
        "target": {"kind": "semantic_region", "query": "sidewalk"},
        "tolerance_m": 0.4,
    }
    payload["invariants"] = ["avoid_road_when_not_crossing"]
    with pytest.raises(PlanValidationError) as error:
        PlanValidator().validate(PlanIR.from_mapping(payload))
    assert error.value.code == "goal_not_achievable"


def test_snapshot_grounding_and_freshness_are_enforced_at_admission() -> None:
    with pytest.raises(PlanValidationError) as stale:
        PlanValidator().validate(_navigate_plan(), _snapshot(camera_fresh=False))
    assert stale.value.code == "camera_stale"

    snapshot = _snapshot().as_dict()
    snapshot["entities"] = [
        entity for entity in snapshot["entities"] if entity["label"] != "sidewalk"
    ]
    with pytest.raises(PlanValidationError) as missing:
        PlanValidator().validate(
            _navigate_plan(), ObservationSnapshot.from_mapping(snapshot)
        )
    assert missing.value.code == "target_not_grounded"

    with pytest.raises(PlanValidationError) as stopped:
        PlanValidator().validate(_navigate_plan(), _snapshot(emergency_stopped=True))
    assert stopped.value.code == "emergency_stopped"


def test_compound_plan_admission_grounds_the_first_step_not_only_final_goal() -> None:
    plan = _sidewalk_then_lamppost_plan()
    snapshot = _snapshot().as_dict()
    snapshot["entities"] = [
        {
            "entity_id": "lamppost-1",
            "kind": "semantic_object",
            "label": "lamppost",
            "confidence": 0.95,
            "source": "camera",
            "observed_at_monotonic_s": 9.9,
            "attributes": {},
        }
    ]

    with pytest.raises(PlanValidationError) as missing_first_target:
        PlanValidator().validate(plan, ObservationSnapshot.from_mapping(snapshot))
    assert missing_first_target.value.code == "target_not_grounded"
    assert "sidewalk" in str(missing_first_target.value)

    snapshot["entities"] = [_snapshot().entities[1].as_dict()]
    validated = PlanValidator().validate(
        plan,
        ObservationSnapshot.from_mapping(snapshot),
    )
    assert [step.step.success.target for step in validated.steps] == [
        "sidewalk",
        "lamppost",
    ]


def test_behind_follow_is_disabled_until_owner_heading_is_observable() -> None:
    with pytest.raises(PlanValidationError) as unsupported:
        PlanValidator().validate(_follow_plan(), _snapshot())
    assert unsupported.value.code == "invalid_argument_value"
    assert "owner heading support is unavailable" in str(unsupported.value)

    registry = SkillContractRegistry.default(owner_heading_supported=True)
    validated = PlanValidator(registry).validate(_follow_plan(), _snapshot())
    assert validated.steps[0].step.skill == "FollowFormation"

    with pytest.raises(PlanValidationError) as missing_heading:
        PlanValidator(registry).validate(_follow_plan(), _snapshot(owner_heading=False))
    assert missing_heading.value.code == "owner_heading_unavailable"


def test_registry_prompt_description_is_compact_machine_readable_policy() -> None:
    registry = SkillContractRegistry.default(pose_names=("sit",), gesture_names=("bow",))
    description = registry.prompt_description()
    encoded = json.dumps(description, sort_keys=True, separators=(",", ":"))

    assert len(encoded) < 8_000
    assert description["capabilities"] == {"owner_heading_supported": False}
    follow = next(
        skill for skill in description["skills"] if skill["name"] == "FollowFormation"
    )
    assert follow["arguments"]["required"] == ["distance_m", "relation"]
    assert follow["admitted"] is False
    assert "priority" not in encoded

    prompt_contract = PlanValidator(registry).prompt_contract()
    assert prompt_contract["contract"] == "parcel_plan_ir_v1"
    assert prompt_contract["policy"]["raw_controls_allowed"] is False
    assert prompt_contract["policy"]["safety_invariants_system_compiled"] is True


def test_registry_restriction_preserves_hardware_capability_flags() -> None:
    registry = SkillContractRegistry.default(owner_heading_supported=True)
    restricted = registry.restricted(("FollowFormation",))
    assert restricted.owner_heading_supported is True
    assert restricted.names() == ("FollowFormation",)


def _voice_plan_payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "task_id": "task-voice",
        "plan_revision": 1,
        "source_turn_id": "turn-voice",
        "goal": {
            "relation": "hold",
            "target": {"kind": "current_pose", "query": ""},
            "tolerance_m": 0.0,
        },
        "invariants": [],
        "steps": [
            {
                "id": "speak",
                "skill": "Vocalize",
                "arguments": {"text": "I am here."},
                "preconditions": ["voice_available"],
                "success": {
                    "fact": "utterance_sent",
                    "target": None,
                    "tolerance_m": None,
                    "confidence_min": None,
                },
                "timeout_s": 5.0,
                "max_attempts": 1,
                "recovery": [],
                "resources": ["voice"],
                "interruptibility": "immediate",
            }
        ],
        "requested_interrupt": "at_checkpoint",
    }
