"""O2/O4: runtime preempt registry + per-channel generation isolation."""

from __future__ import annotations

import time
from dataclasses import replace
from pathlib import Path

import pytest
import yaml

from parcel_robot.audio_io import AudioDeviceStatus
from parcel_robot.backends.base import OwnerTrack, RobotPose, SimObservation
from parcel_robot.brain.executive import (
    NON_OUTCOME_TASK_STATES,
    TERMINAL_TASK_STATES,
    VOICE_INTERRUPT_POLICY,
    InterruptRequest,
    TaskExecutive,
)
from parcel_robot.models import VelocityCommand
from parcel_robot.runtime import RobotRuntime

REPO = Path(__file__).resolve().parents[1]


class _Backend:
    name = "fake"

    def __init__(self) -> None:
        self._observation = SimObservation(
            timestamp=time.monotonic(),
            robot=RobotPose(),
            owner=OwnerTrack("owner", 2.0, 0.0, True, 1.0),
            backend="fake",
        )

    def observe(self) -> SimObservation:
        return replace(self._observation, timestamp=time.monotonic())

    def move(self, command: VelocityCommand) -> None:
        del command

    def stop(self) -> None:
        return None

    def pose(self, pose: object) -> None:
        del pose

    def trajectory(self, skill: object) -> None:
        del skill

    def move_owner(self, dx: float, dy: float) -> None:
        del dx, dy

    def set_robot_pose(self, pose: RobotPose) -> None:
        self._observation = replace(self._observation, robot=pose)

    def set_emergency_stopped(self, stopped: bool) -> None:
        self._observation = replace(self._observation, emergency_stopped=stopped)

    def close(self) -> None:
        return None


@pytest.fixture
def audio_status() -> AudioDeviceStatus:
    return AudioDeviceStatus(
        status="text mode",
        driver="test",
        capture_hardware=False,
        connected_input=False,
        connected_output=False,
        detail="deterministic test status",
    )


@pytest.fixture
def runtime_config(tmp_path: Path) -> Path:
    base = yaml.safe_load((REPO / "configs/robot.yaml").read_text(encoding="utf-8"))
    base["memory"] = {"path": ":memory:"}
    base["navigation"] = {"enabled": True, "config": str(REPO / "configs/navigation/default.yaml")}
    path = tmp_path / "robot.yaml"
    path.write_text(yaml.safe_dump(base), encoding="utf-8")
    return path


def test_generation_tokens_isolation_runtime_level(
    runtime_config: Path, audio_status: AudioDeviceStatus
) -> None:
    rt = RobotRuntime(runtime_config, _Backend(), audio_status=audio_status)
    try:
        nav = rt._generation.bump("navigation")
        follow = rt._generation.bump("follow")
        assert rt._generation.is_current("follow", follow)
        rt._generation.bump("navigation")
        assert not rt._generation.is_current("navigation", nav)
        assert rt._generation.is_current("follow", follow)
    finally:
        rt.close()


def test_preempt_voice_stops_follow_via_table(
    runtime_config: Path, audio_status: AudioDeviceStatus
) -> None:
    rt = RobotRuntime(runtime_config, _Backend(), audio_status=audio_status)
    try:
        rt._enable_owner_follow("direct")
        assert rt.follow.enabled
        taken = rt.preempt(
            "voice",
            reason="voice_motion_started",
            targets=("follow", "navigation", "spatial"),
        )
        assert taken.get("follow") == "stop"
        assert not rt.follow.enabled
    finally:
        rt.close()


def test_voice_interrupt_policy_table_is_declared() -> None:
    from parcel_robot.brain.executive import _voice_interrupt_action

    assert VOICE_INTERRUPT_POLICY["default"] == "overlap"
    assert VOICE_INTERRUPT_POLICY["summons"] == "suspend"
    assert VOICE_INTERRUPT_POLICY["closed_intent_pause"] == "suspend"
    assert _voice_interrupt_action("ambient chatter") == "overlap"
    assert _voice_interrupt_action("owner summons recall") == "suspend"
    assert _voice_interrupt_action("closed_intent_pause") == "suspend"
    decision = TaskExecutive().request_interrupt(
        InterruptRequest(source="voice", reason="ambient chatter", requested="interrupt_now")
    )
    # No active tasks → nothing to interrupt; policy still consulted only when tasks exist.
    assert decision.action == "nothing_to_interrupt"


def test_suspend_is_not_an_outcome() -> None:
    assert "suspended" in NON_OUTCOME_TASK_STATES
    assert "suspended" not in TERMINAL_TASK_STATES


def test_pause_navigation_is_not_voice_stop(
    runtime_config: Path, audio_status: AudioDeviceStatus, monkeypatch
) -> None:
    """Dedicated pause path retains mission + ResumeIntent (≠ voice STOP)."""

    from parcel_robot.navigation.base import MidLevelCommand

    observation = SimObservation(
        timestamp=time.monotonic(),
        robot=RobotPose(),
        owner=OwnerTrack("owner", 2.0, 0.0, True, 1.0),
        backend="fake",
    )
    rt = RobotRuntime(runtime_config, _Backend(), audio_status=audio_status)
    try:
        rt._navigation_directive = "walk to the sidewalk"
        rt._navigation_detail = {
            "enabled": True,
            "state": "navigating",
            "directive": "walk to the sidewalk",
            "goal": "sidewalk",
            "reason": "en_route",
        }
        nav = rt.dog.navigator
        mission = nav.start("walk to the sidewalk")
        assert mission is not None
        rt.pause_navigation(reason="owner_summons")
        assert nav.paused is True
        assert rt._navigation_directive == "walk to the sidewalk"
        assert rt.snapshot()["navigation"]["state"] == "paused"
        intent = rt._resume_store.peek("navigation", now_s=time.monotonic())
        assert intent is not None
        assert intent.suspend_reason == "owner_summons"
        # Stepping while paused must not clear the directive.
        monkeypatch.setattr(
            rt.dog,
            "navigate",
            lambda *args, **kwargs: (
                nav.mission,
                MidLevelCommand(stop=True, note="mission_paused"),
            ),
        )
        rt._step_navigation(observation)
        assert rt._navigation_directive == "walk to the sidewalk"
        assert rt.snapshot()["navigation"]["state"] == "paused"
    finally:
        rt.close()


def test_voice_suspend_navigate_records_resume_intent(
    runtime_config: Path, audio_status: AudioDeviceStatus
) -> None:
    """Suspend releases leases + pauses nav with ResumeIntent; resume redispatches."""

    from parcel_robot.brain.contracts import (
        BatteryStateSnapshot,
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
    )
    from parcel_robot.brain.executive import InterruptRequest
    from parcel_robot.brain.validator import PlanValidator, SkillContractRegistry

    def snap() -> ObservationSnapshot:
        return ObservationSnapshot(
            schema_version=1,
            snapshot_id="snap-suspend",
            captured_at_monotonic_s=10.0,
            camera=SensorSnapshot("camera", True, True, "camera", 9.9, 100.0),
            lidar=SensorSnapshot("lidar", True, True, "lidar", 9.95, 50.0),
            robot=RobotStateSnapshot(False, "stand"),
            safety=SafetyStateSnapshot(False, False, True),
            battery=BatteryStateSnapshot("normal", 80.0, "unitree"),
            task=TaskStateSnapshot(),
            entities=(
                ObservedEntity(
                    "sidewalk-1",
                    "semantic_region",
                    "sidewalk",
                    0.95,
                    "camera",
                    9.9,
                    {},
                ),
            ),
        )

    plan = PlanIR(
        schema_version=1,
        task_id="nav-suspend",
        plan_revision=1,
        source_turn_id="turn-nav",
        goal=GoalSpec("inside", GoalTarget("semantic_region", "sidewalk"), 0.0),
        invariants=(),
        steps=(
            PlanStep(
                "go",
                "NavigateTo",
                {"directive": "sidewalk"},
                ("camera_fresh", "lidar_fresh", "base_available", "target_grounded"),
                SuccessCondition("inside", "sidewalk", None, 0.7),
                90.0,
                1,
                (),
                ("base", "attention"),
                "checkpoint",
            ),
        ),
    )
    validated = PlanValidator(SkillContractRegistry.default()).validate(plan, snap())
    rt = RobotRuntime(runtime_config, _Backend(), audio_status=audio_status)
    try:
        rt.task_executive.submit(validated)
        dispatch = rt.task_executive.tick(snap(), now=10.0)
        assert len(dispatch) == 1
        rt.semantic_tasks.dispatch(dispatch[0], now=10.0)
        rt._navigation_directive = "sidewalk"
        rt._navigation_detail = {
            "enabled": True,
            "state": "navigating",
            "directive": "sidewalk",
            "goal": "sidewalk",
            "reason": "en_route",
        }
        nav = rt.dog.navigator
        nav.start("sidewalk")
        decision = rt.task_executive.request_interrupt(
            InterruptRequest(
                source="voice",
                reason="owner summons recall",
                requested="interrupt_now",
            )
        )
        assert decision.action == "suspend"
        rt._reconcile_semantic_tasks()
        assert rt.task_executive.snapshot()["tasks"][0]["state"] == "suspended"
        assert rt._navigation_directive == "sidewalk"
        assert nav.paused is True
        intent = rt._resume_store.peek("navigation", now_s=time.monotonic())
        assert intent is not None
        # Still suspended: no redispatch.
        assert rt.task_executive.tick(snap(), now=10.5) == ()
        rt.task_executive.resume_task("nav-suspend", reason="summons_done")
        again = rt.task_executive.tick(snap(), now=11.0)
        assert len(again) == 1
        assert again[0].skill == "NavigateTo"
        assert again[0].task_id == "nav-suspend"
    finally:
        rt.close()
