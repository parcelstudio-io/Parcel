"""S-A2 live-pipeline properties for P0-A / P0-B wiring.

These tests exercise the product dispatch path (reactive gate → smoother force
→ actuator shaper → hard_stop finalize → set_target), not the core-only models
from S-A. Only S-A2 may claim P0-A/P0-B closed.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from parcel_robot import runtime as runtime_module
from parcel_robot.audio_io import AudioDeviceStatus
from parcel_robot.backends.base import OwnerTrack, RobotPose, SimObservation
from parcel_robot.core.commands import MotionIntent
from parcel_robot.core.hard_stop import ZERO_COMMAND, FinalStopDecision
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


def _runtime(tmp_path: Path, *, shaping: bool = True) -> RobotRuntime:
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
    enabled: {"true" if shaping else "false"}
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


def _zero_intent_reaches_set_target(
    tmp_path: Path, *, shaping: bool
) -> VelocityCommand:
    """Drive the PRODUCT dispatch path to a zero intent; return what set_target got.

    Warms the velocity smoother on a real forward intent so its ramp holds a
    non-zero residual, then submits the zero intent and dispatches once. Nothing
    here is a stand-in: ``_dispatch_active`` is the live path
    (smoother -> collision gate -> shaper -> ``finalize_command`` -> ``set_target``).
    """

    tmp_path.mkdir(parents=True, exist_ok=True)
    runtime = _runtime(tmp_path, shaping=shaping)
    sent: list[VelocityCommand] = []
    original = runtime.control_manager.set_target

    def capture(command, **kwargs):
        sent.append(command)
        return original(command, **kwargs)

    runtime.control_manager.set_target = capture  # type: ignore[method-assign]
    try:
        _seed_healthy(runtime)
        for _ in range(20):
            runtime.submit_motion("voice", VelocityCommand(vx=0.6), ttl=5.0)
            runtime._dispatch_active()
        assert sent and sent[-1].vx > 0.0, "the smoother must be warm before the stop"

        sent.clear()
        runtime.submit_motion("voice", VelocityCommand(), ttl=5.0)
        runtime._dispatch_active()
        assert sent, "the dispatch path must reach set_target on the zero intent"
        return sent[-1]
    finally:
        runtime.close()


def _finalize_passthrough(candidate, severity, *, downstream_stages=()):
    """The seeded mutant: ``finalize_command`` forwards its candidate unchanged.

    Same signature, same return type — it just never enforces HARD_STOP's exact
    zero and never runs the reset obligations. Injected by monkeypatch only; the
    mutation-panel rule forbids committing a source edit as a mutant.
    """

    del downstream_stages
    return FinalStopDecision(command=candidate, severity=severity, reset_required=False)


def test_mutation_oracle_residual_nonzero_after_hard_stop_is_killed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """P0-A's oracle must KILL a ``finalize_command`` pass-through. Proven here.

    This test used to compare ``VelocityCommand()`` against ``VelocityCommand(vx=0.12)``
    and assert they differed. That touches no product code and cannot fail for any
    reason a robot cares about — Fable's independent audit of task_15 named it a
    tautology, and ``S-A2_STATUS.md`` had cited it as the reason the real mutation
    panel went untouched. So it now drives the product path and proves its own kill.

    The configuration matters, and the honest statement of the layering is:

    * with ``motion.shaping.enabled: false`` the smoother's ramp residual is
      carried all the way to the finalize boundary, so ``finalize_command`` is the
      ONLY authority between that residual and ``set_target``. The mutant is
      killed here, and this is the case the oracle asserts;
    * with shaping enabled ``_shape_for_actuator`` is called with
      ``stopping=True`` on every HARD_STOP route and emergency-zeroes first, so a
      finalize pass-through is an EQUIVALENT mutant on that path. That is
      defence-in-depth working, not the oracle being weak, and it is recorded
      rather than hidden — see ``test_the_shaper_is_defence_in_depth_not_the_oracle``.
    """

    clean = _zero_intent_reaches_set_target(tmp_path / "clean", shaping=False)
    assert clean == ZERO_COMMAND, (
        f"P0-A: a zero intent must reach set_target as exact zero, got {clean}"
    )

    monkeypatch.setattr(runtime_module, "finalize_command", _finalize_passthrough)
    mutated = _zero_intent_reaches_set_target(tmp_path / "mutant", shaping=False)

    assert mutated != ZERO_COMMAND, (
        "the finalize_command pass-through mutant SURVIVED — this oracle is "
        "theatre and P0-A is unproven"
    )
    assert mutated.vx > 0.0, (
        f"the surviving residual should be the smoother's forward ramp, got {mutated}"
    )


def test_the_shaper_is_defence_in_depth_not_the_oracle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With shaping on, the shaper alone already zeroes — stated, not assumed.

    Recorded so the equivalence above is a measured property of the layering and
    not an unexamined gap: if a future change makes the shaper stop zeroing on
    ``stopping=True``, this reddens and the layering claim is re-opened.
    """

    monkeypatch.setattr(runtime_module, "finalize_command", _finalize_passthrough)
    with_shaper = _zero_intent_reaches_set_target(tmp_path / "shaped", shaping=True)

    assert with_shaper == ZERO_COMMAND, (
        "the actuator shaper is supposed to emergency-zero on every stop route "
        "independently of finalize_command; it no longer does"
    )


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
