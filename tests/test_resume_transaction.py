"""K3: suspend→resume transaction — intent consumption, freshness, search→follow."""

from __future__ import annotations

import time
from dataclasses import replace
from pathlib import Path

import pytest
import yaml

from parcel_robot.audio.devices import AudioDeviceStatus
from parcel_robot.backends.base import OwnerTrack, RobotPose, SimObservation
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
from parcel_robot.core.resume import ResumeIntent, resume_rejection_reason
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
    base["navigation"] = {
        "enabled": True,
        "config": str(REPO / "configs/navigation/default.yaml"),
    }
    path = tmp_path / "robot.yaml"
    path.write_text(yaml.safe_dump(base), encoding="utf-8")
    return path


def _fresh_obs(rt: RobotRuntime, *, age_s: float = 0.0) -> SimObservation:
    obs = SimObservation(
        timestamp=time.monotonic() - age_s,
        robot=RobotPose(),
        owner=OwnerTrack("owner", 2.0, 0.0, True, 1.0),
        backend="fake",
    )
    rt._observation = obs
    return obs


def _brain_snap() -> ObservationSnapshot:
    return ObservationSnapshot(
        schema_version=1,
        snapshot_id="snap-k3",
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


def test_resume_rejection_reason_fail_closed() -> None:
    intent = ResumeIntent(
        channel="navigation",
        payload={"directive": "sidewalk"},
        suspend_reason="voice",
        suspended_at_s=0.0,
        valid_for_s=10.0,
        requires_fresh_observation=True,
    )
    assert resume_rejection_reason(None, now_s=1.0) == "missing_intent"
    assert resume_rejection_reason(intent, now_s=11.0) == "expired"
    assert (
        resume_rejection_reason(intent, now_s=1.0, observation_fresh=False)
        == "stale_observation"
    )
    assert (
        resume_rejection_reason(intent, now_s=1.0, observation_fresh=None)
        == "stale_observation"
    )
    assert (
        resume_rejection_reason(intent, now_s=1.0, observation_fresh=True) is None
    )


def _arm_navigation(rt: RobotRuntime, directive: str = "walk to the sidewalk"):
    """Start a mission and mark the runtime navigation channel active."""

    nav = rt.dog.navigator
    mission = nav.start(directive)
    assert mission is not None
    rt._navigation_directive = directive
    rt._navigation_detail = {
        "enabled": True,
        "state": "navigating",
        "directive": directive,
        "goal": directive,
        "reason": "en_route",
    }
    return nav, mission


def test_pause_resume_retains_nav_progress(
    runtime_config: Path, audio_status: AudioDeviceStatus
) -> None:
    rt = RobotRuntime(runtime_config, _Backend(), audio_status=audio_status)
    try:
        _fresh_obs(rt)
        nav, mission = _arm_navigation(rt)
        # Simulate progress already spent before suspend.
        nav._steps_without_progress = 7
        frozen_before = 7
        rt.pause_navigation(reason="owner_summons")
        assert nav.paused is True
        assert nav._steps_without_progress == frozen_before
        message = rt._start_brain_navigation("walk to the sidewalk")
        assert message.startswith("Resuming navigation")
        assert nav.paused is False
        assert nav.mission is mission
        assert nav._steps_without_progress == frozen_before
        assert rt._resume_store.peek("navigation") is None
    finally:
        rt.close()


def test_stale_observation_blocks_resume(
    runtime_config: Path, audio_status: AudioDeviceStatus
) -> None:
    rt = RobotRuntime(runtime_config, _Backend(), audio_status=audio_status)
    try:
        nav, _mission = _arm_navigation(rt)
        rt.pause_navigation(reason="owner_summons")
        # Intent still stored; observation older than telemetry_stale_s.
        stale_age = rt.telemetry_stale_s + 1.0
        _fresh_obs(rt, age_s=stale_age)
        with pytest.raises(RuntimeError, match="stale_observation"):
            rt.resume_navigation()
        # Intent retained for a later fresh retry.
        assert rt._resume_store.peek("navigation", now_s=time.monotonic()) is not None
        assert nav.paused is True
        _fresh_obs(rt)
        rt.resume_navigation()
        assert nav.paused is False
    finally:
        rt.close()


def test_expired_intent_does_not_silently_resume(
    runtime_config: Path, audio_status: AudioDeviceStatus
) -> None:
    rt = RobotRuntime(runtime_config, _Backend(), audio_status=audio_status)
    try:
        _fresh_obs(rt)
        nav, _mission = _arm_navigation(rt)
        rt.pause_navigation(reason="owner_summons")
        intent = rt._resume_store.peek("navigation", now_s=time.monotonic())
        assert intent is not None
        # Force expiry while keeping the paused mission.
        rt._resume_store.record(
            ResumeIntent(
                channel=intent.channel,
                payload=dict(intent.payload),
                suspend_reason=intent.suspend_reason,
                suspended_at_s=0.0,
                valid_for_s=0.0,
                requires_fresh_observation=intent.requires_fresh_observation,
            )
        )
        with pytest.raises(RuntimeError, match="missing or expired|expired|missing_intent"):
            rt._start_brain_navigation("walk to the sidewalk")
        assert nav.paused is True
    finally:
        rt.close()


def test_navigate_redispatch_consumes_resume_intent(
    runtime_config: Path, audio_status: AudioDeviceStatus
) -> None:
    plan = PlanIR(
        schema_version=1,
        task_id="nav-k3",
        plan_revision=1,
        source_turn_id="turn-k3",
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
    validated = PlanValidator(SkillContractRegistry.default()).validate(plan, _brain_snap())
    rt = RobotRuntime(runtime_config, _Backend(), audio_status=audio_status)
    try:
        _fresh_obs(rt)
        rt.task_executive.submit(validated)
        dispatch = rt.task_executive.tick(_brain_snap(), now=10.0)
        assert len(dispatch) == 1
        rt.semantic_tasks.dispatch(dispatch[0], now=10.0)
        nav = rt.dog.navigator
        # Adapter cold-started; pin progress then suspend via voice.
        assert nav.mission is not None
        nav._steps_without_progress = 4
        decision = rt.task_executive.request_interrupt(
            InterruptRequest(
                source="voice",
                reason="owner summons recall",
                requested="interrupt_now",
            )
        )
        assert decision.action == "suspend"
        rt._reconcile_semantic_tasks()
        assert nav.paused is True
        assert rt._resume_store.peek("navigation", now_s=time.monotonic()) is not None
        rt.task_executive.resume_task("nav-k3", reason="summons_done")
        again = rt.task_executive.tick(_brain_snap(), now=11.0)
        assert len(again) == 1
        assert again[0].skill == "NavigateTo"
        rt.semantic_tasks.dispatch(again[0], now=11.0)
        assert nav.paused is False
        assert nav._steps_without_progress == 4
        assert rt._resume_store.peek("navigation") is None
    finally:
        rt.close()


def test_search_to_follow_uses_stored_intent(
    runtime_config: Path, audio_status: AudioDeviceStatus
) -> None:
    rt = RobotRuntime(runtime_config, _Backend(), audio_status=audio_status)
    try:
        _fresh_obs(rt)
        # 1.8 -> 2.0 (2026-08-10, owner-authorized person-clearance retune):
        # the behind-formation floor is owner_keepout_m + the stand-off margin,
        # now 1.75 + 0.10 = 1.85 m, so 1.8 m is refused at the door. The value
        # is incidental to this test; what it pins is the resume transaction.
        rt._enable_owner_follow("behind", distance_m=2.0)
        assert rt.follow.enabled
        # Search preempts follow with PAUSE → ResumeIntent (no legacy tuple).
        taken = rt.preempt("search", reason="owner_search_queued", targets=("follow",))
        assert taken.get("follow") == "pause"
        assert not rt.follow.enabled
        intent = rt._resume_store.peek("follow", now_s=time.monotonic())
        assert intent is not None
        assert intent.payload.get("mode") == "behind"
        assert float(intent.payload["distance_m"]) == pytest.approx(2.0)
        assert not hasattr(rt, "_resume_follow_after_search")

        class _Decision:
            state = "reacquired"
            outcome = "owner_reacquired"

        rt._finish_owner_search(_Decision(), rt._observation)
        assert rt.follow.enabled
        assert rt.follow.mode == "behind"
        assert rt._resume_store.peek("follow") is None
    finally:
        rt.close()


def test_expired_follow_intent_does_not_resume_after_search(
    runtime_config: Path, audio_status: AudioDeviceStatus
) -> None:
    rt = RobotRuntime(runtime_config, _Backend(), audio_status=audio_status)
    try:
        _fresh_obs(rt)
        rt._enable_owner_follow("direct")
        rt.preempt("search", reason="owner_search_queued", targets=("follow",))
        intent = rt._resume_store.peek("follow", now_s=time.monotonic())
        assert intent is not None
        rt._resume_store.record(
            ResumeIntent(
                channel=intent.channel,
                payload=dict(intent.payload),
                suspend_reason=intent.suspend_reason,
                suspended_at_s=0.0,
                valid_for_s=0.0,
                requires_fresh_observation=True,
            )
        )

        class _Decision:
            state = "reacquired"
            outcome = "owner_reacquired"

        rt._finish_owner_search(_Decision(), rt._observation)
        assert not rt.follow.enabled
    finally:
        rt.close()
