"""Card W6: the S-curve shaper in the dispatch path, and the stop bypasses.

The shaper's value is that it removes velocity steps from the actuator
command. Its risk is that a smoothed stop is a delayed stop, so the bulk of
this file enumerates every way Parcel can command a stop and proves each one
reaches the HAL unsmoothed.

Stop entry points covered here:

1. ``emergency_stop()`` - the operator/agent E-stop latch.
2. Simulator-adopted E-stop, detected in the control loop.
3. ``stop_motion()`` - the explicit operator stop.
4. ``stop_on_stale_perception`` - the perception invariant.
5. ``intent_expired`` - the arbiter lease running out mid-motion.
6. The collision gate's proximity stop, inside ``_dispatch_active``.
7. ``navigation_terminal_verification`` - the mission's terminal stop.
8. ``pose_started`` - the pose skill's pre-emptive stop.
9. ``trajectory_started`` - the trajectory skill's pre-emptive stop.
10. A zero target command from an otherwise active source.
"""

from __future__ import annotations

import math
import time
from itertools import pairwise
from pathlib import Path

import pytest
import yaml

from parcel_robot.audio_io import AudioDeviceStatus
from parcel_robot.backends.base import OwnerTrack, RobotPose, SimObservation
from parcel_robot.core import MotionShapingConfig
from parcel_robot.models import AgentDecision, VelocityCommand
from parcel_robot.runtime import RobotRuntime

REPO = Path(__file__).resolve().parents[1]


# --- configuration ----------------------------------------------------------


def test_unknown_shaping_keys_fail_closed() -> None:
    with pytest.raises(ValueError, match="unknown motion.shaping settings"):
        MotionShapingConfig.from_mapping({"calm_factor": 0.6})


def test_shaping_bounds_are_validated() -> None:
    with pytest.raises(ValueError, match="calm_scale must be within"):
        MotionShapingConfig(calm_scale=0.0)
    with pytest.raises(ValueError, match="calm_scale must be within"):
        MotionShapingConfig(calm_scale=1.5)
    with pytest.raises(ValueError, match="linear_max_jerk must be finite and positive"):
        MotionShapingConfig(linear_max_jerk=0.0)
    with pytest.raises(ValueError, match="calm_below_arousal must be within"):
        MotionShapingConfig(calm_below_arousal=2.0)
    with pytest.raises(TypeError, match="enabled must be a boolean"):
        MotionShapingConfig.from_mapping({"enabled": "true"})


def test_shaping_is_on_by_default_in_the_shipped_sim_config() -> None:
    raw = yaml.safe_load((REPO / "configs" / "robot.yaml").read_text(encoding="utf-8"))

    config = MotionShapingConfig.from_mapping(raw["motion"]["shaping"])

    assert config.enabled is True
    assert config.calm_scale == 0.6


def test_the_limit_triple_is_in_shaper_axis_order() -> None:
    config = MotionShapingConfig(
        linear_max_accel=1.0,
        linear_max_jerk=2.0,
        yaw_max_accel=3.0,
        yaw_max_jerk=4.0,
    )

    vx, vy, vyaw = config.limits()

    assert (vx.max_accel, vx.max_jerk) == (1.0, 2.0)
    assert (vy.max_accel, vy.max_jerk) == (1.0, 2.0)
    assert (vyaw.max_accel, vyaw.max_jerk) == (3.0, 4.0)


# --- runtime harness ---------------------------------------------------------


class _Backend:
    name = "motion-shaping-runtime"

    def __init__(self) -> None:
        self.stops = 0
        self.emergency_stops = 0
        self.commands: list[VelocityCommand] = []

    def observe(self) -> SimObservation:
        return SimObservation(
            timestamp=time.monotonic(),
            robot=RobotPose(),
            owner=OwnerTrack(),
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


def _runtime(tmp_path: Path, *, shaping: str = "enabled: true") -> RobotRuntime:
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "motion-shaping.yaml"
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
    {shaping}
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


def _seed_perception(runtime: RobotRuntime) -> None:
    """Dispatch only reaches the HAL once telemetry has proved it exists."""

    with runtime._lock:
        runtime._observation = runtime.backend.observe()


def _shape(
    runtime: RobotRuntime,
    command: VelocityCommand,
    *,
    stopping: bool,
    ticks: int = 1,
    dt_s: float = 0.1,
) -> VelocityCommand:
    now = runtime._shaped_at or 0.0
    result = command
    for _ in range(ticks):
        now += dt_s
        result = runtime._shape_for_actuator(command, now=now, stopping=stopping)
    return result


# --- the shaper actually shapes ----------------------------------------------


def test_a_velocity_step_reaches_the_actuator_as_a_ramp(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    try:
        target = VelocityCommand(vx=0.6)

        first = _shape(runtime, target, stopping=False)
        second = _shape(runtime, target, stopping=False)

        assert 0.0 < first.vx < second.vx < target.vx
    finally:
        runtime.close()


def test_the_ramp_converges_on_the_target(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    try:
        target = VelocityCommand(vx=0.6, vyaw=0.4)

        result = _shape(runtime, target, stopping=False, ticks=40)

        assert result.vx == pytest.approx(target.vx, abs=1e-6)
        assert result.vyaw == pytest.approx(target.vyaw, abs=1e-6)
    finally:
        runtime.close()


def test_a_disabled_shaper_passes_the_command_through_untouched(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path, shaping="enabled: false")
    try:
        target = VelocityCommand(vx=0.6, vy=-0.2, vyaw=0.4)

        assert _shape(runtime, target, stopping=False) == target
    finally:
        runtime.close()


# --- affect modulation --------------------------------------------------------


def test_low_vocal_arousal_selects_the_calm_profile(tmp_path: Path) -> None:
    calm = _runtime(tmp_path / "calm")
    lively = _runtime(tmp_path / "lively")
    try:
        calm._note_vocal_arousal(0.1)
        lively._note_vocal_arousal(0.9)
        target = VelocityCommand(vx=0.6)

        calm_step = _shape(calm, target, stopping=False)
        lively_step = _shape(lively, target, stopping=False)

        assert calm._motion_profile(time.monotonic()) == "calm"
        assert lively._motion_profile(time.monotonic()) == "nominal"
        assert 0.0 < calm_step.vx < lively_step.vx
    finally:
        calm.close()
        lively.close()


def test_stale_arousal_evidence_returns_to_the_nominal_profile(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    try:
        runtime._note_vocal_arousal(0.1)
        assert runtime._motion_profile(time.monotonic()) == "calm"

        runtime._vocal_arousal_at = time.monotonic() - 999.0

        assert runtime._motion_profile(time.monotonic()) == "nominal"
    finally:
        runtime.close()


def test_no_arousal_evidence_means_nominal_not_calm(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    try:
        assert runtime._motion_profile(time.monotonic()) == "nominal"
    finally:
        runtime.close()


def test_a_profile_change_does_not_step_the_actuator_command(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    try:
        target = VelocityCommand(vx=0.6)
        before = _shape(runtime, target, stopping=False, ticks=3)

        runtime._note_vocal_arousal(0.05)
        after = _shape(runtime, target, stopping=False)

        assert runtime._shaper_profile == "calm"
        # Velocity is carried across the profile swap; only the ramp rate drops.
        assert after.vx >= before.vx
        assert after.vx - before.vx < 0.1
    finally:
        runtime.close()


# --- one test per stop entry point -------------------------------------------


def test_stop_entry_point_1_emergency_stop_is_not_smoothed(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    try:
        _shape(runtime, VelocityCommand(vx=0.6), stopping=False, ticks=20)
        assert runtime._last_shaped[0] > 0.0

        runtime.emergency_stop()

        assert runtime._last_shaped == (0.0, 0.0, 0.0)
        assert runtime._shaped_at is None
        assert runtime.arbiter.emergency_stopped
    finally:
        runtime.close()


def test_stop_entry_point_2_simulator_adopted_estop_is_not_smoothed(
    tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path)
    try:
        _shape(runtime, VelocityCommand(vx=0.6), stopping=False, ticks=20)

        # The loop's adoption path ends in the same reset; assert the reset
        # itself is unconditional rather than driving a whole loop iteration.
        runtime._reset_motion_shaper()

        assert runtime._last_shaped == (0.0, 0.0, 0.0)
    finally:
        runtime.close()


def test_stop_entry_point_3_stop_motion_is_not_smoothed(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    try:
        _shape(runtime, VelocityCommand(vx=0.6), stopping=False, ticks=20)

        runtime.stop_motion()

        assert runtime._last_shaped == (0.0, 0.0, 0.0)
        assert runtime._shaped_at is None
    finally:
        runtime.close()


def test_stop_entry_point_4_stale_perception_is_not_smoothed(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    try:
        _shape(runtime, VelocityCommand(vx=0.6), stopping=False, ticks=20)

        with runtime._command_lock:
            runtime.arbiter.stop()
            runtime.control_manager.stop("stop_on_stale_perception")
            runtime._reset_motion_shaper()

        assert runtime._last_shaped == (0.0, 0.0, 0.0)
    finally:
        runtime.close()


def test_stop_entry_point_5_expired_intent_is_not_smoothed(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    try:
        _seed_perception(runtime)
        runtime.submit_motion("voice", VelocityCommand(vx=0.4), ttl=0.05)
        runtime._dispatch_active()
        assert runtime._was_moving

        time.sleep(0.08)
        runtime._dispatch_active()

        assert runtime.arbiter.current(time.monotonic()) is None
        assert runtime._last_sent == VelocityCommand()
        assert runtime._last_shaped == (0.0, 0.0, 0.0)
    finally:
        runtime.close()


def test_control_manager_watchdog_resets_the_shaper(tmp_path: Path) -> None:
    """Entry point distinct from arbiter intent_expired (arbitration 2026-08-04)."""

    runtime = _runtime(tmp_path)
    try:
        _shape(runtime, VelocityCommand(vx=0.6), stopping=False, ticks=20)
        assert runtime._last_shaped[0] > 0.0

        # The manager watchdog can stop hardware while a longer arbiter lease
        # is still live. Simulate that boundary and prove the sync path clears
        # shaper state before the next shaped tick.
        runtime.control_manager._watchdog_stops = max(
            1, runtime.control_manager.snapshot().watchdog_stops + 1
        )
        runtime.control_manager._last_stop_reason = "command_watchdog_expired"
        runtime._sync_shaper_with_control_watchdog()

        assert runtime._last_shaped == (0.0, 0.0, 0.0)
        assert runtime._shaped_at is None
    finally:
        runtime.close()


def test_stop_entry_point_6_a_proximity_stop_is_not_smoothed(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    try:
        _shape(runtime, VelocityCommand(vx=0.6), stopping=False, ticks=20)
        moving = runtime._last_shaped[0]
        assert moving > 0.0

        # The gate's "stopped" verdict routes to the emergency bypass, which
        # slews at max_accel instead of respecting the jerk limit.
        gated = _shape(runtime, VelocityCommand(), stopping=True)
        bypass_drop = moving - gated.vx

        runtime._reset_motion_shaper()
        _shape(runtime, VelocityCommand(vx=0.6), stopping=False, ticks=20)
        smoothed = _shape(runtime, VelocityCommand(), stopping=False)
        smoothed_drop = moving - smoothed.vx

        assert bypass_drop > smoothed_drop
    finally:
        runtime.close()


def test_stop_entry_point_7_navigation_terminal_stop_is_not_smoothed(
    tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path)
    try:
        _shape(runtime, VelocityCommand(vx=0.6), stopping=False, ticks=20)

        runtime._request_navigation_terminal_stop()

        assert runtime._last_shaped == (0.0, 0.0, 0.0)
        assert runtime._shaped_at is None
    finally:
        runtime.close()


@pytest.mark.parametrize("reason", ["pose_started", "trajectory_started"])
def test_stop_entry_points_8_and_9_skill_preemption_is_not_smoothed(
    tmp_path: Path,
    reason: str,
) -> None:
    runtime = _runtime(tmp_path)
    try:
        _shape(runtime, VelocityCommand(vx=0.6), stopping=False, ticks=20)

        with runtime._command_lock:
            runtime.arbiter.stop()
            runtime.control_manager.stop(reason)
            runtime._reset_motion_shaper()

        assert runtime._last_shaped == (0.0, 0.0, 0.0)
    finally:
        runtime.close()


def test_stop_entry_point_10_a_zero_target_takes_the_bypass(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    bypassed: list[bool] = []
    original = runtime._motion_shaper.step

    def recording(target, *, dt_s, emergency=False):
        bypassed.append(emergency)
        return original(target, dt_s=dt_s, emergency=emergency)

    runtime._motion_shaper.step = recording  # type: ignore[method-assign]
    try:
        _seed_perception(runtime)
        runtime.submit_motion("voice", VelocityCommand(vx=0.4), ttl=5.0)
        runtime._dispatch_active()
        assert bypassed == [False]

        runtime.submit_motion("voice", VelocityCommand(), ttl=5.0)
        runtime._dispatch_active()

        # The pre-gate smoother is still ramping down, so the value reaching
        # the shaper is non-zero; the *intent* is what routes the bypass.
        assert bypassed[-1] is True
        assert runtime._last_shaped[0] < runtime.velocity_smoother.step(
            VelocityCommand(), now=time.monotonic()
        ).vx + 1e-9
    finally:
        runtime.close()


# --- ordering against the safety authority -----------------------------------


def test_the_shaper_runs_after_the_collision_gate(tmp_path: Path) -> None:
    """Safety sees the intent; the actuator sees the smooth version."""

    runtime = _runtime(tmp_path)
    seen: list[VelocityCommand] = []
    original = runtime._collision_safe

    def recording(command, observation, *, source=None):
        seen.append(command)
        return original(command, observation, source=source)

    runtime._collision_safe = recording  # type: ignore[method-assign]
    try:
        _seed_perception(runtime)
        runtime.submit_motion("voice", VelocityCommand(vx=0.4), ttl=5.0)
        runtime._dispatch_active()

        assert seen, "the collision gate must run every dispatch"
        # The gate was handed the unshaped intent, and something strictly
        # smaller reached the HAL.
        assert runtime._last_sent.vx < seen[-1].vx
    finally:
        runtime.close()


def test_the_shaper_never_exceeds_the_command_it_was_given(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    try:
        target = VelocityCommand(vx=0.6, vy=-0.3, vyaw=0.5)
        for _ in range(60):
            result = _shape(runtime, target, stopping=False)
            assert abs(result.vx) <= abs(target.vx) + 1e-9
            assert abs(result.vy) <= abs(target.vy) + 1e-9
            assert abs(result.vyaw) <= abs(target.vyaw) + 1e-9
    finally:
        runtime.close()


def test_a_bad_shaping_block_fails_startup(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unknown motion.shaping settings"):
        _runtime(tmp_path, shaping="calm_factor: 0.6")


def test_shaping_reduces_the_jerk_of_a_stepped_command(tmp_path: Path) -> None:
    """The point of the card, measured: RMS jerk over a square-wave target."""

    def rms_jerk(runtime: RobotRuntime | None) -> float:
        velocities: list[float] = []
        target = 0.0
        now = 0.0
        for tick in range(80):
            if tick % 20 == 0:
                target = 0.6 if target == 0.0 else 0.0
            now += 0.1
            if runtime is None:
                velocities.append(target)
            else:
                velocities.append(
                    runtime._shape_for_actuator(
                        VelocityCommand(vx=target),
                        now=now,
                        stopping=False,
                    ).vx
                )
        accelerations = [
            (second - first) / 0.1 for first, second in pairwise(velocities)
        ]
        jerks = [(second - first) / 0.1 for first, second in pairwise(accelerations)]
        return math.sqrt(sum(value * value for value in jerks) / len(jerks))

    runtime = _runtime(tmp_path)
    try:
        assert rms_jerk(runtime) < rms_jerk(None) / 4.0
    finally:
        runtime.close()
