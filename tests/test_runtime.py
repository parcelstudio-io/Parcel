from __future__ import annotations

import math
import threading
import time
from dataclasses import replace
from pathlib import Path

import pytest

from parcel_robot.audio_io import AudioDeviceStatus
from parcel_robot.backends.base import LidarObstacle, OwnerTrack, RobotPose, SimObservation
from parcel_robot.control import build_backend_control_manager
from parcel_robot.core import CommandArbiter, MotionIntent
from parcel_robot.models import AgentDecision, Pose, SpatialIntent, ToolCall, VelocityCommand
from parcel_robot.navigation import GoalPose, MidLevelCommand, Mission, SemanticGoal
from parcel_robot.navigation.follow import FollowOwnerController
from parcel_robot.navigation.reactive_safety import (
    ReactiveSafetyPolicy,
    apply_reactive_safety,
)
from parcel_robot.navigation.spatial import SpatialDecision
from parcel_robot.runtime import RobotRuntime
from parcel_robot.safety import SafetyLimits
from parcel_robot.voice_pipeline import VoiceStage

REPO = Path(__file__).resolve().parents[1]


def _observation(
    timestamp: float,
    *,
    owner_x: float = 3.0,
    owner_y: float = 0.0,
    visible: bool = True,
    confidence: float = 1.0,
    obstacle_m: float | None = None,
    obstacle_bearing_rad: float | None = None,
    person_m: float | None = None,
    person_bearing_rad: float | None = None,
    person_ttc_s: float | None = None,
    lidar_obstacles: tuple[LidarObstacle, ...] = (),
    collision: bool = False,
) -> SimObservation:
    return SimObservation(
        timestamp=timestamp,
        robot=RobotPose(),
        owner=OwnerTrack(
            owner_id="owner-test",
            x=owner_x,
            y=owner_y,
            visible=visible,
            confidence=confidence,
        ),
        nearest_obstacle_m=obstacle_m,
        nearest_obstacle_bearing_rad=obstacle_bearing_rad,
        lidar_obstacles=lidar_obstacles,
        nearest_person_m=person_m,
        nearest_person_bearing_rad=person_bearing_rad,
        nearest_person_id="ped-test" if person_m is not None else None,
        nearest_person_ttc_s=person_ttc_s,
        collision=collision,
        backend="fake",
    )


class FakeSimulatorBackend:
    """Thread-safe backend whose condition variables make loop tests deterministic."""

    name = "fake"

    def __init__(self, observation: SimObservation):
        self._observation = observation
        self._condition = threading.Condition()
        self.moves: list[VelocityCommand] = []
        self.stop_count = 0
        self.poses: list[object] = []
        self.trajectories: list[object] = []

    def observe(self) -> SimObservation:
        with self._condition:
            return replace(self._observation, timestamp=time.monotonic())

    def move(self, command: VelocityCommand) -> None:
        with self._condition:
            self.moves.append(command)
            self._condition.notify_all()

    def stop(self) -> None:
        with self._condition:
            self.stop_count += 1
            self._condition.notify_all()

    def pose(self, pose: object) -> None:
        with self._condition:
            self.poses.append(pose)

    def trajectory(self, skill: object) -> None:
        with self._condition:
            self.trajectories.append(skill)

    def move_owner(self, dx: float, dy: float) -> None:
        with self._condition:
            owner = self._observation.owner
            self._observation = replace(
                self._observation,
                owner=replace(owner, x=owner.x + dx, y=owner.y + dy),
            )

    def wait_for_moves(self, count: int, timeout: float = 1.0) -> bool:
        with self._condition:
            return self._condition.wait_for(lambda: len(self.moves) >= count, timeout)

    def wait_for_stops(self, count: int, timeout: float = 1.0) -> bool:
        with self._condition:
            return self._condition.wait_for(lambda: self.stop_count >= count, timeout)

    def wait_for_trajectories(self, count: int, timeout: float = 1.0) -> bool:
        with self._condition:
            return self._condition.wait_for(lambda: len(self.trajectories) >= count, timeout)

    def set_robot_pose(self, pose: RobotPose) -> None:
        with self._condition:
            self._observation = replace(self._observation, robot=pose)
            self._condition.notify_all()

    def set_emergency_stopped(self, stopped: bool) -> None:
        with self._condition:
            self._observation = replace(self._observation, emergency_stopped=stopped)
            self._condition.notify_all()

    def move_count(self) -> int:
        with self._condition:
            return len(self.moves)

    def stopped_count(self) -> int:
        with self._condition:
            return self.stop_count

    def move_history(self) -> list[VelocityCommand]:
        with self._condition:
            return list(self.moves)


@pytest.fixture
def runtime_config(tmp_path: Path) -> Path:
    path = tmp_path / "robot.yaml"
    path.write_text(
        f"""
skills:
  root: {REPO / "configs" / "skills"}
navigation:
  enabled: false
motion:
  backend: rl
  max_vx: 0.6
  max_vy: 0.4
  max_vyaw: 1.0
  rl:
    enabled: true
    policy_path: ""
memory:
  path: ":memory:"
poses: {{}}
modules: []
""",
        encoding="utf-8",
    )
    return path


@pytest.fixture
def navigation_runtime_config(tmp_path: Path) -> Path:
    path = tmp_path / "robot-nav.yaml"
    path.write_text(
        f"""
skills:
  root: {REPO / "configs" / "skills"}
navigation:
  enabled: true
  config: {REPO / "configs" / "navigation" / "default.yaml"}
motion:
  backend: rl
  max_vx: 0.6
  max_vy: 0.4
  max_vyaw: 1.0
  rl:
    enabled: true
    policy_path: ""
safety:
  obstacle_stop_m: 0.65
  obstacle_slow_m: 1.2
memory:
  path: ":memory:"
poses: {{}}
modules: []
""",
        encoding="utf-8",
    )
    return path


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


def test_arbiter_honors_priority_and_expires_leases() -> None:
    arbiter = CommandArbiter()
    manual = MotionIntent(
        VelocityCommand(vx=0.2),
        source="manual",
        ttl=0.35,
        issued_at=10.0,
    )
    follow = MotionIntent(
        VelocityCommand(vx=0.1),
        source="follow",
        ttl=0.35,
        issued_at=10.1,
    )

    assert arbiter.submit(manual, now=10.0).accepted
    rejected = arbiter.submit(follow, now=10.1)
    assert not rejected.accepted
    assert "higher priority" in rejected.reason
    assert arbiter.current(now=10.349) == manual
    assert arbiter.current(now=10.35) is None
    assert arbiter.submit(follow, now=10.35).accepted


def test_physical_controller_config_cannot_implicitly_arm_runtime(
    tmp_path: Path,
    audio_status: AudioDeviceStatus,
) -> None:
    config = tmp_path / "physical.yaml"
    config.write_text(
        f"""
skills:
  root: {REPO / "configs" / "skills"}
navigation:
  enabled: false
control:
  controller: unitree_sport
motion:
  max_vx: 0.6
  max_vy: 0.4
  max_vyaw: 1.0
memory:
  path: ":memory:"
poses: {{}}
modules: []
""",
        encoding="utf-8",
    )
    backend = FakeSimulatorBackend(_observation(time.monotonic()))

    with pytest.raises(ValueError, match="explicit control_manager"):
        RobotRuntime(config, backend, audio_status=audio_status)


def test_external_controller_blocks_direct_pose_and_trajectory_actuation(
    runtime_config: Path,
    audio_status: AudioDeviceStatus,
) -> None:
    backend = FakeSimulatorBackend(_observation(time.monotonic()))
    manager, _ = build_backend_control_manager(backend, {}, SafetyLimits())
    runtime = RobotRuntime(
        runtime_config,
        backend,
        audio_status=audio_status,
        control_manager=manager,
    )
    try:
        with pytest.raises(RuntimeError, match="physical poses must be implemented"):
            runtime._run_pose(Pose("test", {}, 0.1))
        with pytest.raises(RuntimeError, match="physical trajectories must be implemented"):
            runtime._run_trajectory(object())
        assert backend.poses == []
        assert backend.trajectories == []
    finally:
        runtime.close()


def test_runtime_executes_bounded_owner_relative_steps_and_manual_preempts(
    runtime_config,
    audio_status,
):
    backend = FakeSimulatorBackend(_observation(time.monotonic(), owner_x=2.0))
    runtime = RobotRuntime(runtime_config, backend, audio_status=audio_status, loop_hz=30)
    runtime.start()
    try:
        reply = runtime.handle_text("Can you walk away from the owner 5 steps?")
        assert "5 small steps" in reply
        assert backend.wait_for_moves(1)
        assert any(command.vx < 0.0 for command in backend.move_history())
        spatial = runtime.snapshot()["spatial_behavior"]
        assert spatial["intent"] == {
            "behavior": "move_steps",
            "direction": "away_from_owner",
            "steps": 5,
            "size": "normal",
            "revolutions": 1.0,
        }

        runtime.manual_motion(0.0, 0.2, 0.0)
        assert runtime.snapshot()["spatial_behavior"]["state"] == "cancelled"
        assert runtime.snapshot()["motion"]["active_source"] == "manual"
    finally:
        runtime.close()


def test_explicit_voice_locomotion_preempts_active_spatial_behavior(
    runtime_config,
    audio_status,
):
    observation = _observation(time.monotonic(), owner_x=2.0)
    runtime = RobotRuntime(
        runtime_config,
        FakeSimulatorBackend(observation),
        audio_status=audio_status,
    )
    runtime._observation = observation
    try:
        runtime.start_spatial_behavior(SpatialIntent("move_steps", "forward", steps=3))
        assert runtime.snapshot()["spatial_behavior"]["enabled"] is True

        assert runtime.handle_text("run walk_forward") == "Running walk_forward"

        snapshot = runtime.snapshot()
        assert snapshot["spatial_behavior"]["state"] == "cancelled"
        assert snapshot["motion"]["active_source"] == "voice"
        assert runtime.agent.memory.recent(2) == [
            {"role": "user", "content": "run walk_forward"},
            {"role": "assistant", "content": "Running walk_forward"},
        ]
    finally:
        runtime.close()


def test_runtime_rejects_owner_orbit_when_camera_track_is_missing(
    runtime_config,
    audio_status,
):
    backend = FakeSimulatorBackend(_observation(time.monotonic(), visible=False, confidence=0.0))
    runtime = RobotRuntime(runtime_config, backend, audio_status=audio_status)
    runtime._observation = backend.observe()
    try:
        with pytest.raises(RuntimeError, match="owner_not_visible_to_camera"):
            runtime.start_spatial_behavior(SpatialIntent("orbit_owner", "counterclockwise"))
    finally:
        runtime.close()


def test_owner_orbit_refreshes_perception_at_action_commit(runtime_config, audio_status):
    backend = FakeSimulatorBackend(_observation(time.monotonic(), owner_x=3.0))
    runtime = RobotRuntime(runtime_config, backend, audio_status=audio_status)
    runtime._observation = backend.observe()
    backend.move_owner(-1.0, 0.0)
    backend.move_owner(-0.7, 0.0)
    try:
        reply = runtime.start_spatial_behavior(
            SpatialIntent(
                "orbit_owner",
                "counterclockwise",
                size="small",
                revolutions=0.5,
            )
        )
        assert "a half small counterclockwise circle" in reply
        assert runtime.snapshot()["spatial_behavior"]["state"] == "orbit"
        assert "SpatialCommandObserve" in runtime.latency_snapshot()["components"]
    finally:
        runtime.close()


def test_manual_input_invalidates_spatial_request_during_fresh_observe(
    runtime_config,
    audio_status,
):
    observation = _observation(time.monotonic(), owner_x=3.0)
    observe_started = threading.Event()
    release_observe = threading.Event()

    class BlockingObserveBackend(FakeSimulatorBackend):
        def observe(self) -> SimObservation:
            observe_started.set()
            assert release_observe.wait(2.0)
            return super().observe()

    runtime = RobotRuntime(
        runtime_config,
        BlockingObserveBackend(observation),
        audio_status=audio_status,
    )
    failures = []

    def start_spatial() -> None:
        try:
            runtime.start_spatial_behavior(
                SpatialIntent("orbit_owner", "counterclockwise", size="small")
            )
        except RuntimeError as error:
            failures.append(str(error))

    request = threading.Thread(target=start_spatial)
    try:
        request.start()
        assert observe_started.wait(1.0)
        runtime.manual_motion(0.2, 0.0, 0.0)
        release_observe.set()
        request.join(2.0)

        assert not request.is_alive()
        assert failures == ["spatial request was canceled by a newer operator action"]
        assert runtime.snapshot()["spatial_behavior"]["enabled"] is False
        assert runtime.snapshot()["motion"]["active_source"] == "manual"
    finally:
        release_observe.set()
        runtime.close()


def test_arbiter_estop_latches_until_explicitly_cleared() -> None:
    arbiter = CommandArbiter()
    intent = MotionIntent(
        VelocityCommand(vyaw=0.2),
        source="voice",
        issued_at=20.0,
    )
    assert arbiter.submit(intent, now=20.0).accepted

    arbiter.engage_emergency_stop()
    assert arbiter.emergency_stopped
    assert arbiter.current(now=20.1) is None
    rejected = arbiter.submit(intent, now=20.1)
    assert not rejected.accepted
    assert "emergency stop" in rejected.reason

    arbiter.clear_emergency_stop()
    assert not arbiter.emergency_stopped
    assert arbiter.submit(intent, now=20.1).accepted


@pytest.mark.parametrize(
    ("command", "reason"),
    [
        (VelocityCommand(vx=0.51), "vx exceeds"),
        (VelocityCommand(vy=-0.31), "vy exceeds"),
        (VelocityCommand(vyaw=0.81), "vyaw exceeds"),
    ],
)
def test_arbiter_rejects_commands_outside_limits(
    command: VelocityCommand,
    reason: str,
) -> None:
    arbiter = CommandArbiter(SafetyLimits(max_vx=0.5, max_vy=0.3, max_vyaw=0.8))
    result = arbiter.submit(MotionIntent(command, source="manual", issued_at=1.0), now=1.0)

    assert not result.accepted
    assert reason in result.reason
    assert arbiter.current(now=1.0) is None


def test_follow_controller_tracks_and_holds_at_target_distance() -> None:
    controller = FollowOwnerController()
    controller.start()

    tracking = controller.step(_observation(30.0), now=30.0)
    assert tracking.state == "following"
    assert tracking.reason == "tracking_owner"
    assert tracking.owner_id == "owner-test"
    assert tracking.command.vx == pytest.approx(controller.config.max_vx)
    assert tracking.command.vyaw == pytest.approx(0.0)

    holding = controller.step(
        _observation(30.1, owner_x=controller.config.desired_distance_m),
        now=30.1,
    )
    assert holding.state == "holding"
    assert holding.reason == "at_follow_distance"
    assert holding.command == VelocityCommand()


def test_follow_controller_fail_closes_for_occlusion_and_stale_data() -> None:
    controller = FollowOwnerController()
    controller.start()
    controller.step(_observation(40.0), now=40.0)

    occluded = controller.step(
        _observation(40.2, visible=False, confidence=0.0),
        now=40.2,
    )
    assert occluded.state == "occluded"
    assert occluded.command == VelocityCommand()

    lost = controller.step(
        _observation(40.8, visible=False, confidence=0.0),
        now=40.8,
    )
    assert lost.state == "lost"
    assert lost.reason == "owner_lost"
    assert lost.command == VelocityCommand()

    stale = controller.step(_observation(41.0), now=41.61)
    assert stale.state == "stale"
    assert stale.reason == "stale_observation"
    assert stale.command == VelocityCommand()


def test_follow_controller_stops_before_obstacle() -> None:
    controller = FollowOwnerController()
    controller.start()

    decision = controller.step(
        _observation(50.0, obstacle_m=controller.config.obstacle_stop_m),
        now=50.0,
    )

    assert decision.state == "blocked"
    assert decision.reason == "obstacle_stop"
    assert decision.command == VelocityCommand()


def test_runtime_exposes_bounded_semantic_follow_formation(
    runtime_config: Path,
    audio_status: AudioDeviceStatus,
) -> None:
    backend = FakeSimulatorBackend(_observation(0.0))
    runtime = RobotRuntime(runtime_config, backend, audio_status=audio_status)
    try:
        message = runtime.start_follow_formation("behind", distance_m=2.2)

        assert "Behind-owner formation enabled" in message
        assert runtime.follow.mode == "behind"
        detail = runtime.follow.snapshot()
        assert detail["desired_distance_m"] == pytest.approx(2.2)
        assert detail["perception_basis"] == "camera_owner_track+robot_odometry+lidar"

        runtime.set_behavior("follow")
        assert runtime.follow.mode == "direct"
        assert runtime.follow.snapshot()["desired_distance_m"] == pytest.approx(1.6)
    finally:
        runtime.close()


def test_runtime_dispatches_manual_stop_and_latched_estop(
    runtime_config: Path,
    audio_status: AudioDeviceStatus,
) -> None:
    backend = FakeSimulatorBackend(_observation(0.0))
    runtime = RobotRuntime(
        runtime_config,
        backend,
        audio_status=audio_status,
        loop_hz=50.0,
    )
    runtime.start()
    try:
        assert "accepted manual" in runtime.manual_motion(0.2, -0.1, 0.3)
        assert backend.wait_for_moves(1)
        first = backend.move_history()[-1]
        assert 0.0 < first.vx <= 0.2
        assert -0.1 <= first.vy < 0.0
        assert 0.0 < first.vyaw <= 0.3

        stops = backend.stopped_count()
        assert runtime.action("stop") == "Stopped"
        assert backend.wait_for_stops(stops + 1)

        moves = backend.move_count()
        runtime.manual_motion(0.1, 0.0, 0.0)
        assert backend.wait_for_moves(moves + 1)
        stops = backend.stopped_count()
        assert runtime.action("emergency_stop") == "Emergency stop latched"
        assert backend.wait_for_stops(stops + 1)
        assert runtime.snapshot()["emergency_stopped"] is True
        with pytest.raises(RuntimeError, match="emergency stop"):
            runtime.manual_motion(0.1, 0.0, 0.0)

        assert runtime.action("clear_emergency_stop") == "Emergency stop cleared"
        assert runtime.snapshot()["emergency_stopped"] is False
    finally:
        runtime.close()


def test_runtime_follow_refreshes_commands_and_stay_stops_loop(
    runtime_config: Path,
    audio_status: AudioDeviceStatus,
) -> None:
    backend = FakeSimulatorBackend(_observation(0.0, owner_x=3.0))
    runtime = RobotRuntime(
        runtime_config,
        backend,
        audio_status=audio_status,
        loop_hz=50.0,
    )
    runtime.start()
    try:
        assert runtime.action("follow") == "Owner-follow enabled"
        assert backend.wait_for_moves(2)
        first, second = backend.move_history()[:2]
        assert first.vx > 0.0
        assert 0.0 < first.vx < second.vx

        stops = backend.stopped_count()
        assert runtime.action("stay") == "Holding position"
        assert backend.wait_for_stops(stops + 1)
        assert not runtime.follow.enabled
        move_count = backend.move_count()
        assert not backend.wait_for_moves(move_count + 1, timeout=0.15)
    finally:
        runtime.close()


def test_runtime_text_commands_switch_follow_and_stay(
    runtime_config: Path,
    audio_status: AudioDeviceStatus,
) -> None:
    backend = FakeSimulatorBackend(_observation(0.0))
    runtime = RobotRuntime(runtime_config, backend, audio_status=audio_status)
    runtime._observation = backend.observe()
    try:
        assert runtime.handle_text("follow me") == "I will follow you."
        assert runtime.follow.enabled
        assert runtime.follow.state == "acquiring"

        stops = backend.stopped_count()
        assert runtime.handle_text("stay") == "I will stay here."
        assert not runtime.follow.enabled
        assert runtime.follow.state == "idle"
        assert backend.stopped_count() == stops + 1
    finally:
        runtime.close()


def test_runtime_streaming_text_executes_only_final_transcript(
    runtime_config: Path,
    audio_status: AudioDeviceStatus,
) -> None:
    backend = FakeSimulatorBackend(_observation(0.0))
    runtime = RobotRuntime(runtime_config, backend, audio_status=audio_status)
    try:
        assert runtime.submit_voice_text("follow", is_final=False) is None
        assert runtime.snapshot()["voice"]["partial"] == "follow"
        assert runtime.snapshot()["chat"] == []

        assert runtime.submit_voice_text("follow me", is_final=True) == 1
        assert runtime.voice_session.wait_until_idle(2.0)
        snapshot = runtime.snapshot()
        assert snapshot["voice"]["status"] == "completed"
        assert snapshot["voice"]["last_transcript"] == "follow me"
        assert [item["role"] for item in snapshot["chat"]] == ["user", "assistant"]
        assert runtime.follow.enabled
        trace = runtime.latency_snapshot()["turns"][0]
        assert trace["user_query"] == "follow me"
        assert trace["model_response"] == "I will follow you."
        assert trace["reasoning_source"] == "deterministic"
        assert trace["latency_ms"]["UserQueryEndToFirstResponse"] is not None
        assert trace["latency_ms"]["UserQueryEndToFirstReasoningResponse"] is not None
    finally:
        runtime.close()


def test_plan_latency_uses_the_independent_planner_provider(
    runtime_config: Path,
    audio_status: AudioDeviceStatus,
) -> None:
    class MetricsProvider:
        def __init__(self, lane: str, *, model_mode: str):
            self.last_metrics = {
                "provider_lane": lane,
                "model_mode": model_mode,
                "model_http_ms": 12.5,
            }

    conversation = MetricsProvider("conversation", model_mode="conversation")
    planner = MetricsProvider("planner", model_mode="plan")
    runtime = RobotRuntime(
        runtime_config,
        FakeSimulatorBackend(_observation(0.0)),
        language_model=conversation,
        planner_model=planner,
        audio_status=audio_status,
    )
    try:
        runtime.agent.last_reasoning_source = "plan_model"
        runtime._voice_stage(
            VoiceStage(
                turn_id=1,
                name="query_end",
                timestamp=10.0,
                transcript="Walk to the sidewalk.",
            )
        )
        runtime._voice_stage(
            VoiceStage(
                turn_id=1,
                name="reasoning_response",
                timestamp=10.1,
                reply="Safe plan accepted.",
            )
        )
        runtime._voice_stage(VoiceStage(turn_id=1, name="turn_complete", timestamp=10.2))

        trace = runtime.latency_snapshot()["turns"][0]
        assert trace["reasoning_source"] == "plan_model"
        assert trace["details"]["provider_lane"] == "planner"
        assert trace["details"]["model_mode"] == "plan"
        assert runtime.latency_snapshot()["components"]["PlanModel"]["latest_ms"] == 12.5
    finally:
        runtime.close()


def test_runtime_reports_conversation_and_planner_health_independently(
    runtime_config: Path,
    audio_status: AudioDeviceStatus,
    monkeypatch,
) -> None:
    class Provider:
        def __init__(self, base_url: str):
            self.base_url = base_url

    runtime = RobotRuntime(
        runtime_config,
        FakeSimulatorBackend(_observation(0.0)),
        language_model=Provider("http://127.0.0.1:8080"),
        planner_model=Provider("http://127.0.0.1:8082"),
        audio_status=audio_status,
    )
    try:
        monkeypatch.setattr(
            "parcel_robot.runtime.http_service_health",
            lambda url: url == "http://127.0.0.1:8080/health",
        )
        runtime._refresh_model_health()

        model = runtime.snapshot()["model"]
        assert model["status"] == "offline"
        assert model["roles"] == {"conversation": "ready", "planner": "offline"}

        monkeypatch.setattr("parcel_robot.runtime.http_service_health", lambda url: True)
        runtime._refresh_model_health()
        model = runtime.snapshot()["model"]
        assert model["status"] == "ready"
        assert model["roles"] == {"conversation": "ready", "planner": "ready"}
    finally:
        runtime.close()


def test_streamed_emergency_stop_preempts_slow_reasoning(
    runtime_config: Path,
    audio_status: AudioDeviceStatus,
) -> None:
    reasoning_started = threading.Event()
    release_reasoning = threading.Event()

    class BlockingModel:
        def decide(self, transcript, tools, history):
            reasoning_started.set()
            assert release_reasoning.wait(2.0)
            return AgentDecision(
                "Moving now.",
                (ToolCall("set_velocity", {"vx": 0.2, "vy": 0.0, "vyaw": 0.0}),),
            )

    backend = FakeSimulatorBackend(_observation(0.0))
    runtime = RobotRuntime(
        runtime_config,
        backend,
        language_model=BlockingModel(),
        audio_status=audio_status,
    )
    try:
        assert runtime.submit_voice_text("do something slowly") == 1
        assert reasoning_started.wait(1.0)

        started = time.monotonic()
        assert runtime.submit_voice_text("stop") is None
        assert time.monotonic() - started < 0.5
        assert runtime.snapshot()["emergency_stopped"] is True
        assert runtime.snapshot()["voice"]["status"] == "emergency_stop"

        release_reasoning.set()
        assert runtime.voice_session.wait_until_idle(2.0)
        assert runtime.snapshot()["voice"]["status"] == "emergency_stop"
        assert not backend.move_history()
    finally:
        release_reasoning.set()
        runtime.close()


def test_new_streamed_turn_suppresses_older_reasoned_action(
    runtime_config: Path,
    audio_status: AudioDeviceStatus,
) -> None:
    reasoning_started = threading.Event()
    release_reasoning = threading.Event()

    class BlockingModel:
        def decide(self, transcript, tools, history):
            reasoning_started.set()
            assert release_reasoning.wait(2.0)
            return AgentDecision(
                "Moving now.",
                (ToolCall("set_velocity", {"vx": 0.2, "vy": 0.0, "vyaw": 0.0}),),
            )

    backend = FakeSimulatorBackend(_observation(0.0))
    runtime = RobotRuntime(
        runtime_config,
        backend,
        language_model=BlockingModel(),
        audio_status=audio_status,
    )
    try:
        assert runtime.submit_voice_text("old ambiguous request") == 1
        assert reasoning_started.wait(1.0)
        assert runtime.submit_voice_text("stay") == 2
        release_reasoning.set()
        assert runtime.voice_session.wait_until_idle(2.0)

        assert runtime.dog.motion is not None
        assert runtime.dog.motion.backends["rl"].history == []
        assert runtime.snapshot()["voice"]["last_transcript"] == "stay"
        assert runtime.snapshot()["motion"]["active_source"] is None
    finally:
        release_reasoning.set()
        runtime.close()


def test_runtime_navigation_persists_and_manual_control_preempts_it(
    navigation_runtime_config: Path,
    audio_status: AudioDeviceStatus,
) -> None:
    backend = FakeSimulatorBackend(_observation(0.0))
    runtime = RobotRuntime(
        navigation_runtime_config,
        backend,
        audio_status=audio_status,
        loop_hz=50.0,
    )
    runtime.start()
    try:
        assert runtime.handle_text("navigate to the crosswalk") == "Navigating to crosswalk."
        assert backend.wait_for_moves(2)
        assert runtime.snapshot()["navigation"]["enabled"] is True
        assert runtime.snapshot()["motion"]["active_source"] == "navigation"

        move_count = backend.move_count()
        runtime.manual_motion(0.2, 0.0, 0.0)
        assert backend.wait_for_moves(move_count + 1)
        assert runtime.snapshot()["motion"]["active_source"] == "manual"

        runtime.action("stay")
        assert runtime.snapshot()["navigation"]["enabled"] is False
    finally:
        runtime.close()


def test_runtime_keeps_semantic_mission_active_until_stop_is_verified(
    navigation_runtime_config: Path,
    audio_status: AudioDeviceStatus,
    monkeypatch,
) -> None:
    observation = _observation(time.monotonic())
    runtime = RobotRuntime(
        navigation_runtime_config,
        FakeSimulatorBackend(observation),
        audio_status=audio_status,
    )
    mission = Mission(
        directive="walk to the sidewalk",
        goal=GoalPose(1.0, 0.0, label="sidewalk"),
        status="verifying",
        semantic_goal=SemanticGoal("sidewalk", kind="region", terminal_relation="inside"),
    )
    runtime._navigation_directive = mission.directive
    responses = iter(
        (
            (mission, MidLevelCommand(stop=True, note="semantic_stop_requested")),
            (mission, MidLevelCommand(stop=True, note="arrived_verified")),
        )
    )
    monkeypatch.setattr(runtime.dog, "navigate", lambda *args, **kwargs: next(responses))
    try:
        runtime._step_navigation(observation)

        assert runtime._navigation_directive == mission.directive
        assert runtime.snapshot()["navigation"]["state"] == "verifying"

        mission.status = "arrived"
        runtime._step_navigation(observation)

        assert runtime._navigation_directive is None
        assert runtime.snapshot()["navigation"]["state"] == "arrived"
    finally:
        runtime.close()


def test_runtime_does_not_advance_navigation_with_stale_perception(
    navigation_runtime_config: Path,
    audio_status: AudioDeviceStatus,
    monkeypatch,
) -> None:
    runtime = RobotRuntime(
        navigation_runtime_config,
        FakeSimulatorBackend(_observation(time.monotonic())),
        audio_status=audio_status,
    )
    runtime._navigation_directive = "walk to the sidewalk"
    navigate_called = False

    def navigate(*args, **kwargs):
        nonlocal navigate_called
        navigate_called = True
        raise AssertionError("stale perception must not reach the navigator")

    monkeypatch.setattr(runtime.dog, "navigate", navigate)
    stale = _observation(time.monotonic() - runtime.telemetry_stale_s - 0.1)
    try:
        runtime._step_navigation(stale)

        assert not navigate_called
        assert runtime._navigation_directive == "walk to the sidewalk"
        navigation = runtime.snapshot()["navigation"]
        assert navigation["state"] == "waiting"
        assert navigation["reason"] == "stale_perception"
    finally:
        runtime.close()


def test_runtime_final_proximity_gate_preserves_escape_turn(
    runtime_config: Path,
    audio_status: AudioDeviceStatus,
) -> None:
    backend = FakeSimulatorBackend(_observation(0.0, obstacle_m=0.3, obstacle_bearing_rad=0.0))
    runtime = RobotRuntime(
        runtime_config,
        backend,
        audio_status=audio_status,
        loop_hz=50.0,
    )
    runtime.start()
    try:
        runtime.manual_motion(0.2, 0.0, 0.4)
        assert backend.wait_for_moves(1)
        command = backend.move_history()[-1]
        assert command.vx == 0.0
        assert command.vy == 0.0
        assert 0.0 < command.vyaw <= 0.4
    finally:
        runtime.close()


def test_runtime_proximity_gate_fails_closed_for_reverse_without_bearing(
    runtime_config: Path,
    audio_status: AudioDeviceStatus,
) -> None:
    observation = _observation(
        time.monotonic(),
        obstacle_m=0.1,
        obstacle_bearing_rad=None,
        collision=True,
    )
    runtime = RobotRuntime(
        runtime_config,
        FakeSimulatorBackend(observation),
        audio_status=audio_status,
    )
    try:
        command, state = runtime._collision_safe(VelocityCommand(vx=-0.2), observation)
        assert command == VelocityCommand()
        assert state == "stopped"
    finally:
        runtime.close()


def test_owner_orbit_inward_gate_includes_obstacle_stop_clearance() -> None:
    policy = ReactiveSafetyPolicy(
        obstacle_stop_m=0.65,
        obstacle_slow_m=1.2,
        owner_collision_envelope_m=0.55,
        orbit_clearance_margin_m=0.10,
    )
    minimum_center_distance = (
        policy.obstacle_stop_m + policy.owner_collision_envelope_m + policy.orbit_clearance_margin_m
    )
    observation = _observation(
        10.0,
        owner_x=minimum_center_distance - 0.01,
    )

    inward, inward_state = apply_reactive_safety(
        VelocityCommand(vx=0.2),
        observation,
        policy=policy,
        owner_orbit=True,
        orbit_radius_m=minimum_center_distance,
        now=10.0,
    )
    outward, outward_state = apply_reactive_safety(
        VelocityCommand(vx=-0.2),
        observation,
        policy=policy,
        owner_orbit=True,
        orbit_radius_m=minimum_center_distance,
        now=10.0,
    )

    assert inward == VelocityCommand()
    assert inward_state == "stopped"
    assert outward == VelocityCommand(vx=-0.2)
    assert outward_state == "clear"


def test_runtime_first_command_uses_directional_person_distance_without_ttc(
    runtime_config: Path,
    audio_status: AudioDeviceStatus,
) -> None:
    observation = _observation(
        time.monotonic(),
        person_m=0.7,
        person_bearing_rad=0.0,
        person_ttc_s=None,
    )
    runtime = RobotRuntime(
        runtime_config,
        FakeSimulatorBackend(observation),
        audio_status=audio_status,
    )
    try:
        forward, forward_state = runtime._collision_safe(VelocityCommand(vx=0.2), observation)
        retreat, retreat_state = runtime._collision_safe(VelocityCommand(vx=-0.2), observation)
        tangent, tangent_state = runtime._collision_safe(VelocityCommand(vy=0.2), observation)

        assert forward == VelocityCommand()
        assert forward_state == "stopped"
        assert retreat == VelocityCommand(vx=-0.2)
        assert retreat_state == "clear"
        assert tangent == VelocityCommand(vy=0.2)
        assert tangent_state == "clear"
    finally:
        runtime.close()


def test_runtime_uses_current_motion_against_all_bounded_lidar_candidates(
    runtime_config: Path,
    audio_status: AudioDeviceStatus,
) -> None:
    observation = _observation(
        time.monotonic(),
        # Legacy nearest is behind and would be ignored for forward motion.
        obstacle_m=0.1,
        obstacle_bearing_rad=math.pi,
        lidar_obstacles=(
            LidarObstacle(0.1, math.pi, "rear"),
            LidarObstacle(0.3, 0.0, "front"),
        ),
    )
    runtime = RobotRuntime(
        runtime_config,
        FakeSimulatorBackend(observation),
        audio_status=audio_status,
    )
    try:
        command, state = runtime._collision_safe(VelocityCommand(vx=0.2), observation)

        assert command == VelocityCommand()
        assert state == "stopped"
    finally:
        runtime.close()


def test_spatial_step_cannot_reacquire_motion_after_operator_stop(
    runtime_config: Path,
    audio_status: AudioDeviceStatus,
    monkeypatch,
) -> None:
    observation = _observation(time.monotonic(), owner_x=2.0)
    runtime = RobotRuntime(
        runtime_config,
        FakeSimulatorBackend(observation),
        audio_status=audio_status,
    )
    runtime._observation = observation
    runtime.start_spatial_behavior(SpatialIntent("move_steps", "forward", steps=2))
    entered_step = threading.Event()
    release_step = threading.Event()

    def blocked_step(_observation):
        entered_step.set()
        assert release_step.wait(2.0)
        return SpatialDecision(
            VelocityCommand(vx=0.2),
            False,
            "moving",
            "bounded_step_motion",
            0.1,
        )

    monkeypatch.setattr(runtime.spatial, "step", blocked_step)
    stepping = threading.Thread(target=lambda: runtime._step_spatial(observation))
    stopping = threading.Thread(target=lambda: runtime.action("stop"))
    try:
        stepping.start()
        assert entered_step.wait(1.0)
        stopping.start()
        release_step.set()
        stepping.join(2.0)
        stopping.join(2.0)
        assert not stepping.is_alive()
        assert not stopping.is_alive()
        assert runtime.snapshot()["motion"]["active_source"] is None
        assert runtime.snapshot()["spatial_behavior"]["state"] == "cancelled"
    finally:
        release_step.set()
        runtime.close()


def test_runtime_serializes_dispatch_with_operator_stop(
    runtime_config: Path,
    audio_status: AudioDeviceStatus,
) -> None:
    entered_move = threading.Event()
    release_move = threading.Event()
    stop_returned = threading.Event()
    order: list[str] = []

    class BlockingBackend(FakeSimulatorBackend):
        def move(self, command: VelocityCommand) -> None:
            entered_move.set()
            assert release_move.wait(2.0)
            order.append("move")
            super().move(command)

        def stop(self) -> None:
            order.append("stop")
            super().stop()

    backend = BlockingBackend(_observation(time.monotonic()))
    runtime = RobotRuntime(runtime_config, backend, audio_status=audio_status)
    runtime._observation = _observation(time.monotonic())
    try:
        runtime.manual_motion(0.2, 0.0, 0.0)
        dispatcher = threading.Thread(target=runtime._dispatch_active)
        dispatcher.start()
        assert entered_move.wait(1.0)

        stopper = threading.Thread(target=lambda: (runtime.stop_motion(), stop_returned.set()))
        stopper.start()
        assert not stop_returned.wait(0.05)
        release_move.set()
        dispatcher.join(1.0)
        stopper.join(1.0)

        assert stop_returned.is_set()
        assert order[-2:] == ["move", "stop"]
        move_count = backend.move_count()
        runtime._dispatch_active()
        assert backend.move_count() == move_count
    finally:
        release_move.set()
        runtime.close()


def test_rotate_in_place_target_brakes_residual_translation_immediately(
    runtime_config: Path,
    audio_status: AudioDeviceStatus,
) -> None:
    backend = FakeSimulatorBackend(_observation(time.monotonic()))
    runtime = RobotRuntime(runtime_config, backend, audio_status=audio_status)
    runtime._observation = _observation(time.monotonic())
    try:
        runtime.manual_motion(0.4, 0.0, 0.0)
        runtime._dispatch_active()
        assert backend.move_history()[-1].vx > 0.0

        runtime.arbiter.cancel("manual")
        runtime.submit_motion("navigation", VelocityCommand(vyaw=0.6), ttl=1.0)
        runtime._dispatch_active()

        aligned = backend.move_history()[-1]
        assert aligned.vx == 0.0
        assert aligned.vy == 0.0
        assert aligned.vyaw > 0.0
    finally:
        runtime.close()


def test_operator_stop_cancels_activity_between_ready_and_dispatch(
    runtime_config: Path,
    audio_status: AudioDeviceStatus,
) -> None:
    backend = FakeSimulatorBackend(_observation(time.monotonic()))
    runtime = RobotRuntime(runtime_config, backend, audio_status=audio_status)
    try:
        runtime.handle_text("I am feeling sad")
        with runtime._command_lock:
            dispatcher = threading.Thread(target=runtime._step_activities)
            dispatcher.start()
            deadline = time.monotonic() + 1.0
            while runtime.activities.running() is None and time.monotonic() < deadline:
                time.sleep(0.005)
            assert runtime.activities.running() is not None
            assert runtime.action("stop") == "Stopped"
        dispatcher.join(1.0)

        assert not dispatcher.is_alive()
        assert backend.trajectories == []
        assert runtime.snapshot()["activities"]["running"] is None
    finally:
        runtime.close()


def test_runtime_telemetry_loss_blocks_translation(
    runtime_config: Path,
    audio_status: AudioDeviceStatus,
) -> None:
    class OfflineBackend(FakeSimulatorBackend):
        def observe(self) -> SimObservation:
            raise OSError("telemetry offline")

    backend = OfflineBackend(_observation(time.monotonic()))
    runtime = RobotRuntime(
        runtime_config,
        backend,
        audio_status=audio_status,
        loop_hz=50.0,
    )
    runtime.start()
    try:
        runtime.manual_motion(0.2, 0.0, 0.2)
        deadline = time.monotonic() + 0.5
        while runtime.snapshot()["simulator"]["status"] != "disconnected":
            assert time.monotonic() < deadline
            time.sleep(0.005)
        time.sleep(0.05)
        assert not backend.move_history()
        control = runtime.snapshot()["control"]
        assert control["lifecycle"] == "idle"
        assert control["fault"] is None
        assert runtime.snapshot()["simulator"]["status"] == "disconnected"
    finally:
        runtime.close()


def test_runtime_recovers_after_simulator_connects_and_stops_before_first_move(
    runtime_config: Path,
    audio_status: AudioDeviceStatus,
) -> None:
    class RecoveringBackend(FakeSimulatorBackend):
        def __init__(self, observation: SimObservation) -> None:
            super().__init__(observation)
            self.online = False
            self.actions: list[object] = []

        def observe(self) -> SimObservation:
            if not self.online:
                raise OSError("telemetry offline")
            return super().observe()

        def move(self, command: VelocityCommand) -> None:
            if not self.online:
                raise OSError("actuator transport offline")
            self.actions.append(command)
            super().move(command)

        def stop(self) -> None:
            if not self.online:
                raise OSError("actuator transport offline")
            self.actions.append("stop")
            super().stop()

    backend = RecoveringBackend(_observation(time.monotonic()))
    runtime = RobotRuntime(
        runtime_config,
        backend,
        audio_status=audio_status,
        loop_hz=50.0,
    )
    runtime.start()
    try:
        deadline = time.monotonic() + 0.5
        while runtime.snapshot()["simulator"]["status"] != "disconnected":
            assert time.monotonic() < deadline
            time.sleep(0.005)
        runtime.manual_motion(0.2, 0.0, 0.0)
        time.sleep(0.05)
        assert backend.actions == []
        assert runtime.snapshot()["control"]["lifecycle"] == "idle"

        # The UI's ordinary Stop is also local while this optional transport
        # has never produced telemetry; it must not poison later reconnect.
        runtime.stop_motion()
        assert backend.actions == []
        assert runtime.snapshot()["control"]["fault"] is None
        runtime.manual_motion(0.2, 0.0, 0.0)
        time.sleep(0.05)
        assert backend.actions == []
        backend.online = True

        assert backend.wait_for_moves(1)
        assert backend.actions[0] == "stop"
        assert isinstance(backend.actions[1], VelocityCommand)
        assert runtime.snapshot()["control"]["lifecycle"] != "faulted"
    finally:
        runtime.close()


def test_runtime_close_can_retry_controller_teardown(
    runtime_config: Path,
    audio_status: AudioDeviceStatus,
) -> None:
    backend = FakeSimulatorBackend(_observation(time.monotonic()))
    runtime = RobotRuntime(runtime_config, backend, audio_status=audio_status)
    original_close = runtime.control_manager.close
    attempts = 0

    def close_with_one_retryable_failure() -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("controller I/O is still quiescing")
        original_close()

    runtime.control_manager.close = close_with_one_retryable_failure  # type: ignore[method-assign]
    try:
        with pytest.raises(RuntimeError, match="still quiescing"):
            runtime.close()

        assert runtime._closed is True
        assert runtime._close_complete is False
        runtime.close()
        assert attempts == 2
        assert runtime._close_complete is True
    finally:
        if not runtime._close_complete:
            runtime.control_manager.close = original_close  # type: ignore[method-assign]
            runtime.close()


@pytest.mark.parametrize(
    "failing_thread_name",
    ["parcel-control-loop", "parcel-service-health"],
)
def test_runtime_thread_start_failure_closes_controller_owner(
    runtime_config: Path,
    audio_status: AudioDeviceStatus,
    monkeypatch,
    failing_thread_name: str,
) -> None:
    backend = FakeSimulatorBackend(_observation(time.monotonic()))
    runtime = RobotRuntime(runtime_config, backend, audio_status=audio_status)
    original_start = threading.Thread.start

    def start_or_fail(thread: threading.Thread) -> None:
        if thread.name == failing_thread_name:
            raise RuntimeError(f"cannot start {failing_thread_name}")
        original_start(thread)

    monkeypatch.setattr(threading.Thread, "start", start_or_fail)

    with pytest.raises(RuntimeError, match=failing_thread_name):
        runtime.start()

    assert runtime._closed is True
    assert runtime._close_complete is True
    assert runtime.control_manager.snapshot().lifecycle.value == "closed"
    assert runtime._thread is None or not runtime._thread.is_alive()
    assert runtime._health_thread is None or not runtime._health_thread.is_alive()
    runtime.close()


def test_social_affect_action_runs_from_idle_without_model(
    runtime_config: Path,
    audio_status: AudioDeviceStatus,
) -> None:
    backend = FakeSimulatorBackend(_observation(0.0))
    runtime = RobotRuntime(runtime_config, backend, audio_status=audio_status, loop_hz=50.0)
    try:
        assert runtime.handle_text("I am feeling sad") == "I'm here with you."
        pending = runtime.snapshot()["activities"]["pending"]
        assert pending[0]["name"] == "play_bow"

        runtime.start()
        assert backend.wait_for_trajectories(1)
        assert backend.trajectories[0].id == "play_bow"
    finally:
        runtime.close()


def test_social_affect_action_defers_until_navigation_finishes(
    navigation_runtime_config: Path,
    audio_status: AudioDeviceStatus,
) -> None:
    backend = FakeSimulatorBackend(_observation(0.0))
    runtime = RobotRuntime(
        navigation_runtime_config,
        backend,
        audio_status=audio_status,
        loop_hz=50.0,
    )
    runtime.start()
    try:
        assert runtime.handle_text("navigate to the crosswalk") == "Navigating to crosswalk."
        assert backend.wait_for_moves(1)
        reply = runtime.handle_text("I am very happy")
        assert reply.startswith("I'm happy with you!")
        assert "wait until the current task" in reply
        pending = runtime.snapshot()["activities"]["pending"]
        assert pending[0]["name"] == "paw_wave"
        assert pending[0]["disposition"] == "defer"
        assert backend.trajectories == []

        backend.set_robot_pose(RobotPose(x=3.5, y=-0.6, z=0.32, yaw=0.0))
        assert backend.wait_for_trajectories(1)
        assert backend.trajectories[0].id == "paw_wave"
        assert runtime.snapshot()["navigation"]["state"] == "arrived"
    finally:
        runtime.close()


def test_simulator_estop_clears_deferred_social_actions(
    runtime_config: Path,
    audio_status: AudioDeviceStatus,
) -> None:
    backend = FakeSimulatorBackend(_observation(0.0, owner_x=3.0))
    runtime = RobotRuntime(runtime_config, backend, audio_status=audio_status, loop_hz=50.0)
    runtime.set_behavior("follow")
    runtime.handle_text("I am feeling sad")
    assert runtime.snapshot()["activities"]["pending"]

    runtime.start()
    try:
        backend.set_emergency_stopped(True)
        deadline = time.monotonic() + 1.0
        while not runtime.snapshot()["emergency_stopped"] and time.monotonic() < deadline:
            time.sleep(0.01)
        snapshot = runtime.snapshot()
        assert snapshot["emergency_stopped"] is True
        assert snapshot["activities"]["pending"] == []

        backend.set_emergency_stopped(False)
        runtime.clear_emergency_stop()
        time.sleep(0.1)
        assert backend.trajectories == []
    finally:
        runtime.close()
