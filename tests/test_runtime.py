from __future__ import annotations

import threading
import time
from dataclasses import replace
from pathlib import Path

import pytest

from parcel_robot.audio_io import AudioDeviceStatus
from parcel_robot.backends.base import OwnerTrack, RobotPose, SimObservation
from parcel_robot.core import CommandArbiter, MotionIntent
from parcel_robot.models import AgentDecision, ToolCall, VelocityCommand
from parcel_robot.navigation.follow import FollowOwnerController
from parcel_robot.runtime import RobotRuntime
from parcel_robot.safety import SafetyLimits

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
        assert backend.move_history()[-1] == VelocityCommand(vx=0.2, vy=-0.1, vyaw=0.3)

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
        assert second == first

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


def test_runtime_final_proximity_gate_preserves_escape_turn(
    runtime_config: Path,
    audio_status: AudioDeviceStatus,
) -> None:
    backend = FakeSimulatorBackend(
        _observation(0.0, obstacle_m=0.3, obstacle_bearing_rad=0.0)
    )
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
        assert backend.move_history()[-1] == VelocityCommand(vyaw=0.4)
    finally:
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

        stopper = threading.Thread(
            target=lambda: (runtime.stop_motion(), stop_returned.set())
        )
        stopper.start()
        assert not stop_returned.wait(0.05)
        release_move.set()
        dispatcher.join(1.0)
        stopper.join(1.0)

        assert stop_returned.is_set()
        assert order[:2] == ["move", "stop"]
        move_count = backend.move_count()
        runtime._dispatch_active()
        assert backend.move_count() == move_count
    finally:
        release_move.set()
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
        assert backend.wait_for_moves(1)
        assert backend.move_history()[-1] == VelocityCommand(vyaw=0.2)
        assert runtime.snapshot()["simulator"]["status"] == "disconnected"
    finally:
        runtime.close()
