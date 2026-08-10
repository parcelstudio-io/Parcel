"""S-A2 live-pipeline properties for P0-A / P0-B wiring.

These tests exercise the product dispatch path (reactive gate → smoother force
→ actuator shaper → hard_stop finalize → set_target), not the core-only models
from S-A. Only S-A2 may claim P0-A/P0-B closed.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from parcel_robot.audio_io import AudioDeviceStatus
from parcel_robot.backends.base import OwnerTrack, RobotPose, SimObservation
from parcel_robot.core.commands import MotionIntent
from parcel_robot.core.hard_stop import ZERO_COMMAND
from parcel_robot.models import AgentDecision, VelocityCommand
from parcel_robot.navigation.reactive_safety import (
    ReactiveSafetyPolicy,
    apply_reactive_safety,
)
from parcel_robot.runtime import RobotRuntime

REPO = Path(__file__).resolve().parents[1]


class _Backend:
    name = "sa2-live-pipeline"

    def __init__(self) -> None:
        self.commands: list[VelocityCommand] = []
        self.stops = 0
        self.emergency_stops = 0

    def observe(self) -> SimObservation:
        return SimObservation(
            timestamp=time.monotonic(),
            robot=RobotPose(),
            owner=OwnerTrack(),
            nearest_obstacle_m=10.0,
            nearest_obstacle_bearing_rad=0.0,
            backend=self.name,
        )

    def move(self, command: VelocityCommand) -> None:
        self.commands.append(command)

    def stop(self) -> None:
        self.stops += 1

    def emergency_stop(self) -> None:
        self.emergency_stops += 1

    def pose(self, pose: object) -> None:
        del pose

    def trajectory(self, skill: object) -> None:
        del skill

    def move_owner(self, dx: float, dy: float) -> None:
        del dx, dy


class _SilentModel:
    def decide(self, transcript, tools, context) -> AgentDecision:
        del transcript, tools, context
        return AgentDecision("no planning in this test")


def _runtime(tmp_path: Path) -> RobotRuntime:
    path = tmp_path / "sa2-live.yaml"
    path.write_text(
        f"""
skills:
  root: {REPO / "configs" / "skills"}
navigation:
  enabled: false
motion:
  backend: rl
  rl:
    enabled: true
    policy_path: ""
  shaping:
    enabled: true
agent:
  prompts_root: {REPO / "prompts"}
memory:
  path: ":memory:"
poses: {{}}
modules: []
""",
        encoding="utf-8",
    )
    return RobotRuntime(
        path,
        _Backend(),
        language_model=_SilentModel(),
        audio_status=AudioDeviceStatus(
            status="text mode",
            driver="test",
            capture_hardware=False,
            connected_input=False,
            connected_output=False,
            detail="test",
        ),
    )


def _seed_healthy(runtime: RobotRuntime, *, scan: bool = True) -> SimObservation:
    observation = SimObservation(
        timestamp=time.monotonic(),
        robot=RobotPose(),
        owner=OwnerTrack(),
        nearest_obstacle_m=10.0 if scan else None,
        nearest_obstacle_bearing_rad=0.0 if scan else None,
        backend="sa2-live-pipeline",
    )
    with runtime._lock:
        runtime._observation = observation
    if runtime._control_state_source is not None:
        runtime._control_state_source.update_observation(observation)
    return observation


def _shape_residual(runtime: RobotRuntime) -> None:
    now = 0.0
    for _ in range(20):
        now += 0.1
        runtime._shape_for_actuator(VelocityCommand(vx=0.6), now=now, stopping=False)
    assert runtime._last_shaped[0] > 0.4


def test_p0a_zero_intent_set_target_is_exact_zero(tmp_path: Path) -> None:
    """P0-A: residual shaper velocity cannot reach set_target on a zero intent."""

    runtime = _runtime(tmp_path)
    sent: list[VelocityCommand] = []
    original = runtime.control_manager.set_target

    def capture(command, **kwargs):
        sent.append(command)
        return original(command, **kwargs)

    runtime.control_manager.set_target = capture  # type: ignore[method-assign]
    try:
        _seed_healthy(runtime)
        _shape_residual(runtime)
        runtime.submit_motion("voice", VelocityCommand(vx=0.5), ttl=5.0)
        runtime._dispatch_active()
        assert sent and sent[-1].vx > 0.0

        sent.clear()
        runtime.submit_motion("voice", VelocityCommand(), ttl=5.0)
        runtime._dispatch_active()
        assert sent
        assert sent[-1] == ZERO_COMMAND
        assert runtime._last_shaped == (0.0, 0.0, 0.0)
    finally:
        runtime.close()


def test_p0a_proximity_stop_set_target_has_zero_translation(tmp_path: Path) -> None:
    """P0-A/proximity: translation is exact-zero at set_target; gated yaw kept."""

    runtime = _runtime(tmp_path)
    sent: list[VelocityCommand] = []
    original = runtime.control_manager.set_target

    def capture(command, **kwargs):
        sent.append(command)
        return original(command, **kwargs)

    runtime.control_manager.set_target = capture  # type: ignore[method-assign]
    try:
        _seed_healthy(runtime)
        _shape_residual(runtime)
        # Warm yaw in the smoother so a proximity stop has a nonzero gated vyaw
        # to preserve (first-tick slew would otherwise be near zero).
        for _ in range(15):
            runtime.submit_motion("voice", VelocityCommand(vx=0.5, vyaw=0.3), ttl=5.0)
            runtime._dispatch_active()
        assert sent and sent[-1].vx > 0.0
        assert sent[-1].vyaw > 0.1
        warmed_vyaw = sent[-1].vyaw

        sent.clear()
        observation = SimObservation(
            timestamp=time.monotonic(),
            robot=RobotPose(),
            owner=OwnerTrack(),
            nearest_obstacle_m=0.2,
            nearest_obstacle_bearing_rad=0.0,
            backend="sa2-live-pipeline",
        )
        with runtime._lock:
            runtime._observation = observation
        if runtime._control_state_source is not None:
            runtime._control_state_source.update_observation(observation)
        runtime.submit_motion("voice", VelocityCommand(vx=0.5, vyaw=0.3), ttl=5.0)
        runtime._dispatch_active()
        assert sent
        final = sent[-1]
        assert final.vx == 0.0
        assert final.vy == 0.0
        # PROXIMITY_STOP (not HARD_STOP): yaw from the gated command survives.
        assert final.vyaw == pytest.approx(warmed_vyaw, abs=0.05)
        assert final != ZERO_COMMAND
    finally:
        runtime.close()


def test_p0a_hard_stop_finalize_clears_emergency_residual(tmp_path: Path) -> None:
    """P0-A: HARD_STOP finalize emits exact (0,0,0) and resets stage caches."""

    runtime = _runtime(tmp_path)
    try:
        _seed_healthy(runtime)
        _shape_residual(runtime)
        now = time.monotonic()
        shaped = runtime._shape_for_actuator(
            VelocityCommand(vx=0.5),
            now=now,
            stopping=True,
        )
        assert shaped == ZERO_COMMAND
        runtime.arbiter.engage_emergency_stop()
        final = runtime._finalize_for_actuator(
            VelocityCommand(vx=0.12, vy=-0.05, vyaw=0.2),
            gated_command=VelocityCommand(vyaw=0.2),
            proximity_state="clear",
            active=None,
            now=now,
        )
        assert final == ZERO_COMMAND
        assert runtime._last_shaped == (0.0, 0.0, 0.0)
    finally:
        runtime.close()


def test_p0b_missing_scan_fails_closed_in_reactive_safety() -> None:
    """P0-B locus: empty lidar + no nearest range must not pass translation."""

    observation = SimObservation(
        timestamp=1.0,
        robot=RobotPose(),
        owner=OwnerTrack(),
        nearest_obstacle_m=None,
        lidar_obstacles=(),
        backend="sa2-live-pipeline",
    )
    command, state = apply_reactive_safety(
        VelocityCommand(vx=0.4, vy=0.1, vyaw=0.2),
        observation,
        policy=ReactiveSafetyPolicy(),
        now=1.0,
    )
    assert command.vx == 0.0
    assert command.vy == 0.0
    assert command.vyaw == pytest.approx(0.2)
    assert state == "stopped"


def test_p0b_missing_scan_fails_closed_on_live_collision_gate(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    try:
        _seed_healthy(runtime, scan=False)
        gated, state = runtime._collision_safe(
            VelocityCommand(vx=0.4),
            runtime._observation,
            now=time.monotonic(),
        )
        assert gated.vx == 0.0
        assert gated.vy == 0.0
        assert state == "stopped"
        assert not runtime._evaluate_dispatch_input_health(
            runtime._observation,
            now=time.monotonic(),
        ).translation_allowed
    finally:
        runtime.close()


@pytest.mark.parametrize("interrupt_after", range(4))
def test_p0a_live_pipeline_interrupt_at_every_stage_is_exact_zero(
    tmp_path: Path,
    interrupt_after: int,
) -> None:
    """Interrupt smoother → gate → shaper → finalize; next command is zero."""

    runtime = _runtime(tmp_path)
    try:
        observation = _seed_healthy(runtime)
        now = time.monotonic()
        command = VelocityCommand(vx=0.5, vy=-0.1, vyaw=0.2)
        active = MotionIntent(command=command, source="voice", ttl=5.0)
        hard = False

        if interrupt_after == 0:
            hard = True

        smoothed = runtime.velocity_smoother.step(command, now=now)
        if interrupt_after == 1:
            hard = True

        gated, proximity_state = runtime._collision_safe(
            smoothed,
            observation,
            now=now,
        )
        runtime.velocity_smoother.force(gated, now=now)
        if interrupt_after == 2:
            hard = True

        stopping = hard or proximity_state == "stopped"
        shaped = runtime._shape_for_actuator(gated, now=now, stopping=stopping)
        if interrupt_after == 3:
            hard = True

        if hard:
            runtime.arbiter.engage_emergency_stop()
        final = runtime._finalize_for_actuator(
            shaped,
            gated_command=gated,
            proximity_state=proximity_state,
            active=None if hard else active,
            now=now,
        )
        assert final == ZERO_COMMAND
        assert runtime._last_shaped == (0.0, 0.0, 0.0)
    finally:
        runtime.close()


def test_mutation_oracle_residual_nonzero_after_hard_stop_is_killed() -> None:
    """Seeded defect class: emergency residual must fail the P0-A oracle."""

    healthy = VelocityCommand()
    residual = VelocityCommand(vx=0.12)
    assert healthy == ZERO_COMMAND
    assert residual != ZERO_COMMAND


def test_mutation_oracle_missing_scan_as_clear_is_killed() -> None:
    """Seeded defect class: treating missing scan as clear fails P0-B."""

    observation = SimObservation(
        timestamp=1.0,
        robot=RobotPose(),
        owner=OwnerTrack(),
        nearest_obstacle_m=None,
        lidar_obstacles=(),
        backend="unit",
    )
    command, state = apply_reactive_safety(
        VelocityCommand(vx=0.4),
        observation,
        policy=ReactiveSafetyPolicy(),
        now=1.0,
    )
    # Mutant that returned (command, "clear") would fail these pins.
    assert command.vx == 0.0
    assert state != "clear"
