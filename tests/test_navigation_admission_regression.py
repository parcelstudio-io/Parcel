"""Admission must not require a visible target — the 2026-08-05 regression.

"go to the sidewalk" was refused at plan admission with
``target_not_grounded`` whenever the sidewalk was outside the camera
frustum, dead-ending before the resolution ladder (frustum -> memory ->
scan -> frontier -> honest report) could run. Grounding-with-recovery is
NavigateTo's own job; admission only requires fresh sensors and an
available base. These tests pin the corrected contract and the honest
refusal replies at the exact layer that broke (VoiceAgent -> local sketch
-> validator admission), which the NAV_INSTRUCT harness bypasses.
"""

from __future__ import annotations

import time
from pathlib import Path

from parcel_robot.agent import VoiceAgent
from parcel_robot.audio_io import AudioDeviceStatus
from parcel_robot.backends.base import OwnerTrack, RobotPose, SimObservation
from parcel_robot.brain.navigate_admission import assert_searchable_admission_contract
from parcel_robot.brain.observations import build_observation_snapshot
from parcel_robot.brain.router import DeterministicIntentRouter
from parcel_robot.brain.validator import (
    PlanValidationError,
    PlanValidator,
    SkillContractRegistry,
)
from parcel_robot.models import VelocityCommand
from parcel_robot.runtime import RobotRuntime
from parcel_robot.voice.local_plans import sketch_navigate

REPO = Path(__file__).resolve().parents[1]


def _registry() -> SkillContractRegistry:
    return SkillContractRegistry.default().restricted(
        ("NavigateTo", "FollowFormation", "Hold", "MoveRelative", "OrbitOwner")
    )


def _fresh_observation(now: float) -> SimObservation:
    return SimObservation(
        timestamp=now,
        robot=RobotPose(),
        owner=OwnerTrack(),
        backend="admission-test",
    )


def test_navigate_contract_requires_searchable_not_visible_target() -> None:
    contract = _registry().get("NavigateTo")
    # Shared pin: searchable ≠ visible (see brain/navigate_admission.py).
    assert_searchable_admission_contract(contract.required_preconditions)
    # The ladder's recovery vocabulary is what makes admission-without-
    # visibility safe: the skill searches before it reports failure.
    assert "rescan" in contract.recovery_actions


def test_unseen_target_admits_with_fresh_sensors() -> None:
    """The exact regression: sidewalk absent from entities must still admit."""

    registry = _registry()
    frame = DeterministicIntentRouter().route(
        "go to the sidewalk", turn_id="turn-admission-1"
    )
    now = 50.0
    snapshot = build_observation_snapshot(
        _fresh_observation(now),
        snapshot_id="snapshot-admission-1",
        now=now,
    )
    assert snapshot.camera.fresh and snapshot.lidar.fresh
    assert not snapshot.matching_entities("sidewalk")

    from parcel_robot.brain.compiler import compile_plan_sketch

    plan = compile_plan_sketch(
        sketch_navigate("go to the sidewalk"), frame, snapshot, registry
    )
    assert "target_grounded" not in plan.steps[0].preconditions
    validated = PlanValidator(registry).validate(plan, snapshot)
    assert validated.plan == plan


def test_explicitly_declared_target_grounded_is_still_enforced() -> None:
    """The precondition token stays enforceable for plans that declare it."""

    registry = _registry()
    frame = DeterministicIntentRouter().route(
        "go to the sidewalk", turn_id="turn-admission-2"
    )
    now = 60.0
    snapshot = build_observation_snapshot(
        _fresh_observation(now), snapshot_id="snapshot-admission-2", now=now
    )
    from dataclasses import replace

    from parcel_robot.brain.compiler import compile_plan_sketch

    plan = compile_plan_sketch(
        sketch_navigate("go to the sidewalk"), frame, snapshot, registry
    )
    step = plan.steps[0]
    declared = replace(
        plan,
        steps=(
            replace(
                step,
                preconditions=tuple(sorted((*step.preconditions, "target_grounded"))),
            ),
        ),
    )
    try:
        PlanValidator(registry).validate(declared, snapshot)
    except PlanValidationError as error:
        assert error.code == "target_not_grounded"
    else:  # pragma: no cover - regression guard
        raise AssertionError("declared target_grounded must still be enforced")


def test_admission_failure_replies_name_the_reason() -> None:
    generic = VoiceAgent._admission_failure_reply(ValueError("boom"))
    assert "couldn't admit" in generic

    stale = VoiceAgent._admission_failure_reply(
        PlanValidationError("camera_stale", "first step requires a fresh camera")
    )
    assert "camera" in stale.lower()
    assert "couldn't admit" not in stale

    stopped = VoiceAgent._admission_failure_reply(
        PlanValidationError("emergency_stopped", "not admitted during emergency stop")
    )
    assert "emergency stop" in stopped.lower()


class _Backend:
    name = "admission-runtime"

    def observe(self) -> SimObservation:
        return _fresh_observation(time.monotonic())

    def move(self, command: VelocityCommand) -> None:
        del command

    def stop(self) -> None:
        pass

    def pose(self, pose: object) -> None:
        del pose

    def trajectory(self, skill: object) -> None:
        del skill

    def move_owner(self, dx: float, dy: float) -> None:
        del dx, dy


def _runtime_config(tmp_path: Path) -> Path:
    path = tmp_path / "admission-runtime.yaml"
    path.write_text(
        f"""
skills:
  root: {REPO / "configs" / "skills"}
navigation:
  enabled: true
motion:
  backend: rl
  max_vx: 0.6
  max_vy: 0.4
  max_vyaw: 1.0
  rl:
    enabled: true
    policy_path: ""
agent:
  prompts_root: {REPO / "prompts"}
  brain:
    enabled: true
    skills: [NavigateTo, FollowFormation, OrbitOwner, MoveRelative, Hold, Vocalize, AskClarification]
memory:
  path: ":memory:"
poses: {{}}
modules: []
"""
    )
    return path


def _audio() -> AudioDeviceStatus:
    return AudioDeviceStatus(
        status="text mode",
        driver="test",
        capture_hardware=False,
        connected_input=False,
        connected_output=False,
        detail="test",
    )


def test_runtime_text_path_admits_go_to_the_sidewalk(tmp_path: Path) -> None:
    """Full agent path: transcript -> local sketch -> admission -> task."""

    runtime = RobotRuntime(
        _runtime_config(tmp_path), _Backend(), language_model=None, audio_status=_audio()
    )
    observation = _fresh_observation(time.monotonic())
    runtime._observation = observation
    if runtime._control_state_source is not None:
        runtime._control_state_source.update_observation(observation)

    reply = runtime.handle_text("go to the sidewalk")

    assert "couldn't admit" not in reply
    assert runtime.agent.last_reasoning_source == "local_plan_sketch"
    assert runtime.agent.last_reasoning_error is None
    tasks = runtime.task_executive.snapshot().get("tasks", [])
    assert tasks, "an admitted NavigateTo task must exist"


def test_runtime_text_path_reports_stale_camera_honestly(tmp_path: Path) -> None:
    runtime = RobotRuntime(
        _runtime_config(tmp_path), _Backend(), language_model=None, audio_status=_audio()
    )
    # No observation ever streamed: sensors cannot be fresh.
    reply = runtime.handle_text("go to the sidewalk")

    assert "stale" in reply.lower() or "holding still" in reply.lower()
    assert "couldn't admit" not in reply
