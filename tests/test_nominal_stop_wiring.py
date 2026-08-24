"""Card J-B: the severity-split stop shaping, wired.

The claim under test is narrow and safety-shaped: a NOMINAL zero intent may
decay along ``core.stop_ramp``'s monotone ramp, and NOTHING else changes. Every
emergency arm keeps P0-A's instant exact zero, every ramp candidate is disposed
by the UNTOUCHED reactive gate on the tick it is actuated, a stop verdict
preempts to hard zero on that same tick, and the flag is default-OFF with
flag-off dispatch byte-identical.

Design record: ``scrum/20260811/task_1/FOLLOWUP_DESIGNS.md`` §3.2 part 2 (the
re-spec is normative) and adjudications #2/#3/#4.
"""

from __future__ import annotations

import ast
import hashlib
import math
import time
from collections.abc import Callable
from itertools import pairwise
from pathlib import Path

import pytest

from parcel_robot import runtime as runtime_module
from parcel_robot.audio.devices import AudioDeviceStatus
from parcel_robot.backends.base import (
    DynamicAgentTrack,
    OwnerTrack,
    RobotPose,
    SimObservation,
)
from parcel_robot.core.hard_stop import (
    ZERO_COMMAND,
    InterventionSeverity,
    ResetObligation,
    finalize_command,
)
from parcel_robot.core.motion_shaping import MotionShapingConfig
from parcel_robot.models import AgentDecision, VelocityCommand
from parcel_robot.runtime import RobotRuntime

REPO = Path(__file__).resolve().parents[1]


# --- runtime harness ---------------------------------------------------------


class _Backend:
    name = "nominal-stop-wiring"

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


def _runtime(
    tmp_path: Path,
    *,
    ramp: bool,
    time_to_collision: bool = False,
) -> RobotRuntime:
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "nominal-stop.yaml"
    # The TTC block is emitted ONLY when asked for, so every pre-existing test
    # in this file keeps the config it was written against, key for key.
    safety_block = (
        """
safety:
  time_to_collision:
    enabled: true
"""
        if time_to_collision
        else ""
    )
    path.write_text(
        f"""
skills:
  root: {REPO / "configs" / "skills"}
navigation:
  enabled: false
{safety_block}
motion:
  backend: rl
  rl:
    enabled: true
    policy_path: ""
  shaping:
    enabled: true
    nominal_stop_ramp: {"true" if ramp else "false"}
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


def _seed(
    runtime: RobotRuntime,
    *,
    obstacle_m: float = 10.0,
    agents: tuple[DynamicAgentTrack, ...] = (),
) -> SimObservation:
    observation = SimObservation(
        timestamp=time.monotonic(),
        robot=RobotPose(),
        owner=OwnerTrack(),
        nearest_obstacle_m=obstacle_m,
        nearest_obstacle_bearing_rad=0.0,
        dynamic_agents=agents,
        backend=_Backend.name,
    )
    with runtime._lock:
        runtime._observation = observation
    if runtime._control_state_source is not None:
        runtime._control_state_source.update_observation(observation)
    return observation


def _capture(runtime: RobotRuntime) -> list[VelocityCommand]:
    sent: list[VelocityCommand] = []
    original = runtime.control_manager.set_target

    def capture(command, **kwargs):
        sent.append(command)
        return original(command, **kwargs)

    runtime.control_manager.set_target = capture  # type: ignore[method-assign]
    return sent


def _warm(runtime: RobotRuntime, sent: list[VelocityCommand], *, ticks: int = 20) -> None:
    """Drive a real forward intent until the shaper carries a velocity."""

    for _ in range(ticks):
        _seed(runtime)
        runtime.submit_motion("voice", VelocityCommand(vx=0.6), ttl=5.0)
        runtime._dispatch_active()
    assert sent and sent[-1].vx > 0.0, "the shaper must be warm before the stop"
    sent.clear()


def _stop_tick(
    runtime: RobotRuntime,
    *,
    obstacle_m: float = 10.0,
    agents: tuple[DynamicAgentTrack, ...] = (),
) -> None:
    _seed(runtime, obstacle_m=obstacle_m, agents=agents)
    runtime.submit_motion("voice", VelocityCommand(), ttl=5.0)
    runtime._dispatch_active()


# --- (a) the severity enum ---------------------------------------------------


def test_the_three_original_severity_values_never_move_and_nominal_is_appended() -> None:
    """Adjudication #3: append, never renumber. These ints are an ABI."""

    assert int(InterventionSeverity.CLEAR) == 0
    assert int(InterventionSeverity.PROXIMITY_STOP) == 1
    assert int(InterventionSeverity.HARD_STOP) == 2
    assert int(InterventionSeverity.NOMINAL_STOP) == 3
    assert [member.name for member in InterventionSeverity] == [
        "CLEAR",
        "PROXIMITY_STOP",
        "HARD_STOP",
        "NOMINAL_STOP",
    ]


def test_the_finalize_tail_is_explicitly_fail_closed_for_an_unknown_member(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The hole adjudication #3 found, closed and PROVEN closed.

    Before this card the tail returned the candidate for any severity that was
    not HARD/PROXIMITY, so appending a member (this card appends one) would have
    opened a pass-through. There is no fifth member to test with, so the resolver
    is monkeypatched to hand the tail a value it has never seen — exactly what
    tomorrow's appended member would be.
    """

    from parcel_robot.core import hard_stop as hard_stop_module

    class _FutureSeverity:
        name = "SOME_FUTURE_STOP"

    monkeypatch.setattr(
        hard_stop_module, "_severity_or_hard_stop", lambda value: _FutureSeverity()
    )
    reset: list[str] = []
    decision = finalize_command(
        VelocityCommand(vx=0.4, vy=0.1, vyaw=0.2),
        InterventionSeverity.CLEAR,
        downstream_stages=(ResetObligation("stage", lambda: reset.append("stage")),),
    )

    assert decision.command == ZERO_COMMAND
    assert decision.severity is InterventionSeverity.HARD_STOP
    assert decision.reset_required is True
    assert reset == ["stage"], "the fail-closed tail must run the reset obligations"


def test_nominal_stop_passes_only_a_monotone_candidate_and_otherwise_hard_stops() -> None:
    previous = VelocityCommand(vx=0.4, vy=-0.2, vyaw=1.0)
    ok = finalize_command(
        VelocityCommand(vx=0.28, vy=-0.08, vyaw=0.4),
        InterventionSeverity.NOMINAL_STOP,
        previous_command=previous,
    )
    assert ok.command == VelocityCommand(vx=0.28, vy=-0.08, vyaw=0.4)
    assert ok.severity is InterventionSeverity.NOMINAL_STOP
    assert ok.reset_required is False

    reset: list[str] = []
    stages = (ResetObligation("stage", lambda: reset.append("stage")),)
    for candidate in (
        VelocityCommand(vx=0.41, vy=-0.2, vyaw=1.0),  # magnitude increase
        VelocityCommand(vx=-0.1, vy=-0.2, vyaw=1.0),  # sign flip
        VelocityCommand(vx=math.nan, vy=0.0, vyaw=0.0),  # non-finite
    ):
        reset.clear()
        decision = finalize_command(
            candidate,
            InterventionSeverity.NOMINAL_STOP,
            downstream_stages=stages,
            previous_command=previous,
        )
        assert decision.command == ZERO_COMMAND
        assert decision.severity is InterventionSeverity.HARD_STOP
        assert reset == ["stage"]

    # No previous command at all: nothing to be monotone against, so HARD.
    blind = finalize_command(
        VelocityCommand(vx=0.1),
        InterventionSeverity.NOMINAL_STOP,
    )
    assert blind.command == ZERO_COMMAND
    assert blind.severity is InterventionSeverity.HARD_STOP


def test_the_flag_is_off_by_default_everywhere() -> None:
    assert MotionShapingConfig().nominal_stop_ramp is False
    import yaml

    raw = yaml.safe_load((REPO / "configs" / "robot.yaml").read_text(encoding="utf-8"))
    shipped = MotionShapingConfig.from_mapping(raw["motion"]["shaping"])
    assert shipped.nominal_stop_ramp is False
    with pytest.raises(TypeError, match="nominal_stop_ramp must be a boolean"):
        MotionShapingConfig.from_mapping({"nominal_stop_ramp": "true"})


# --- (b) flag-off identity ---------------------------------------------------


def test_flag_off_a_zero_intent_still_reaches_set_target_as_exact_zero(
    tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path, ramp=False)
    sent = _capture(runtime)
    try:
        _warm(runtime, sent)
        _stop_tick(runtime)
        assert sent[-1] == ZERO_COMMAND
        assert runtime._last_shaped == (0.0, 0.0, 0.0)
        # None of the card's machinery may run with the flag off.
        assert runtime._nominal_stop_ramp_ticks == 0
        assert runtime._nominal_stop_regate_ticks == 0
        assert runtime._nominal_stop_preempt_ticks == 0
        assert runtime._nominal_stop_ramping is False
    finally:
        runtime.close()


# --- (c) the ramp itself, and its gate ---------------------------------------


def _ramp_series(runtime: RobotRuntime, sent: list[VelocityCommand], ticks: int) -> list[float]:
    series: list[float] = []
    for _ in range(ticks):
        _stop_tick(runtime)
        series.append(sent[-1].vx)
    return series


def test_flag_on_a_nominal_zero_intent_decays_instead_of_snapping(
    tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path, ramp=True)
    sent = _capture(runtime)
    try:
        _warm(runtime, sent)
        # The tick spacing in this loop is sub-millisecond, so ``dt_s`` clamps
        # to its 1e-3 floor and the ramp is ~1.2 mm/s per tick: the ramp is a
        # RATE, and a test that only ran a handful of ticks would be asserting
        # the loop's wall clock rather than the contract.
        series = _ramp_series(runtime, sent, 60)

        assert series[0] > 0.0, "a nominal stop must ramp, not snap, with the flag on"
        assert series[-1] == 0.0, "the ramp must still reach exact zero"
        for previous, current in pairwise(series):
            assert abs(current) <= abs(previous), series
            assert previous * current >= 0.0, series
        # Every ramp tick was disposed by the untouched gate — counted, not claimed.
        assert runtime._nominal_stop_ramp_ticks >= 1
        assert runtime._nominal_stop_regate_ticks == runtime._nominal_stop_ramp_ticks
    finally:
        runtime.close()


def test_flag_on_ramp_never_exceeds_what_the_gate_approved(tmp_path: Path) -> None:
    """The actuated value IS the gate's disposition of the candidate."""

    runtime = _runtime(tmp_path, ramp=True)
    sent = _capture(runtime)
    seen: list[tuple[VelocityCommand, VelocityCommand]] = []
    original = runtime_module.apply_reactive_safety

    def watched(command, observation, **kwargs):
        result = original(command, observation, **kwargs)
        seen.append((command, result[0]))
        return result

    runtime_module.apply_reactive_safety = watched  # type: ignore[assignment]
    try:
        _warm(runtime, sent)
        seen.clear()
        _stop_tick(runtime)
        assert len(seen) == 2, "a nominal ramp tick re-gates exactly once"
        candidate, disposed = seen[-1]
        assert sent[-1].vx <= abs(disposed.vx) + 0.0
        assert abs(disposed.vx) <= abs(candidate.vx)
    finally:
        runtime_module.apply_reactive_safety = original  # type: ignore[assignment]
        runtime.close()


# --- (d) same-tick preemption -------------------------------------------------


def test_an_arbiter_emergency_stop_mid_ramp_dispatches_exact_zero_that_tick(
    tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path, ramp=True)
    sent = _capture(runtime)
    try:
        _warm(runtime, sent)
        _stop_tick(runtime)
        assert sent[-1].vx > 0.0, "the ramp must be in flight before the interrupt"

        # ``submit_motion`` refuses while latched, so the e-stop is engaged on a
        # tick whose intent is already live: the interrupt lands MID-ramp.
        _seed(runtime)
        dispatched = len(sent)
        runtime.arbiter.engage_emergency_stop()
        runtime._dispatch_active()

        # The e-stop drops the intent, so this tick takes the stop() path rather
        # than a zero set_target — a stronger outcome than the zero command, and
        # the ramp is over either way.
        assert len(sent) == dispatched, "no motion command may be dispatched"
        assert runtime._last_sent == ZERO_COMMAND
        assert runtime.backend.stops >= 1
        assert runtime._last_shaped == (0.0, 0.0, 0.0)
        assert runtime._nominal_stop_ramping is False
    finally:
        runtime.close()


def test_an_input_health_latch_mid_ramp_dispatches_exact_zero_that_tick(
    tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path, ramp=True)
    sent = _capture(runtime)
    try:
        _warm(runtime, sent)
        _stop_tick(runtime)
        assert sent[-1].vx > 0.0

        runtime._input_health_latched = True
        _stop_tick(runtime)

        assert sent[-1] == ZERO_COMMAND
        assert runtime._last_shaped == (0.0, 0.0, 0.0)
        assert runtime._nominal_stop_ramping is False
    finally:
        runtime.close()


def test_a_close_obstacle_mid_ramp_dispatches_exact_zero_that_tick(
    tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path, ramp=True)
    sent = _capture(runtime)
    try:
        _warm(runtime, sent)
        _stop_tick(runtime)
        assert sent[-1].vx > 0.0

        _stop_tick(runtime, obstacle_m=0.05)

        assert sent[-1] == ZERO_COMMAND
        assert runtime._last_shaped == (0.0, 0.0, 0.0)
    finally:
        runtime.close()


def _regate_preemption_case(
    tmp_path: Path,
    verdict: Callable[[VelocityCommand], tuple[VelocityCommand, str]],
) -> None:
    """Drive one nominal-ramp tick whose SECOND gate call returns ``verdict``.

    The first pass (on the pre-gate smoother's command) stays clear, so nothing
    but the re-gate can produce the hard zero asserted below. The injection is a
    monkeypatch of the module symbol — ``reactive_safety.py`` itself is
    MUST-NOT-TOUCH for this card and is not modified.
    """

    runtime = _runtime(tmp_path, ramp=True)
    sent = _capture(runtime)
    original = runtime_module.apply_reactive_safety
    calls = {"n": 0, "arm": False}

    def injected(command, observation, **kwargs):
        calls["n"] += 1
        if calls["arm"] and calls["n"] == 2:
            return verdict(command)
        return original(command, observation, **kwargs)

    runtime_module.apply_reactive_safety = injected  # type: ignore[assignment]
    try:
        _warm(runtime, sent)
        calls["n"] = 0
        _stop_tick(runtime)
        assert sent[-1].vx > 0.0, "the ramp must be in flight"

        calls["n"] = 0
        calls["arm"] = True
        preempts = runtime._nominal_stop_preempt_ticks
        _stop_tick(runtime)

        assert sent[-1] == ZERO_COMMAND
        assert runtime._nominal_stop_preempt_ticks == preempts + 1
        assert runtime._last_shaped == (0.0, 0.0, 0.0)
        assert runtime._nominal_stop_ramping is False
    finally:
        runtime_module.apply_reactive_safety = original  # type: ignore[assignment]
        runtime.close()


def test_a_stopped_verdict_from_the_re_gate_alone_preempts_the_same_tick(
    tmp_path: Path,
) -> None:
    """Arm 1 in isolation: the verdict SAYS stopped, the command is untouched.

    Deliberately split from the zeroed-translation case below. When one injection
    tripped both arms at once, a seeded mutant that deleted the verdict check
    survived — killed by the other arm. Two arms, two tests, two kills.
    """

    _regate_preemption_case(tmp_path, lambda command: (command, "stopped"))


def test_a_zeroed_translation_from_the_re_gate_alone_preempts_the_same_tick(
    tmp_path: Path,
) -> None:
    """Arm 2 in isolation: translation is zeroed while the state stays 'clear'.

    This is the input-health / stale-telemetry / missing-scan shape of the gate's
    refusal, which does not always carry the 'stopped' label. A zeroed
    translation IS a stop verdict and must preempt on the same tick.
    """

    _regate_preemption_case(
        tmp_path, lambda command: (VelocityCommand(vyaw=command.vyaw), "clear")
    )


#: Approaches whose predicted circle-circle contact is inside
#: ``TimeToCollisionConfig.stop_s`` (0.8 s) for EVERY robot speed the ramp can
#: still be carrying — the robot's own +x motion only ever brings each of these
#: contacts forward, so the property below does not depend on where in the ramp
#: the tick lands. ``(x, y, vx, vy)`` in the world frame, robot at the origin
#: facing +x, both radii 0.35 m.
_TTC_APPROACHES = (
    pytest.param((2.0, 0.0, -2.0, 0.0), id="head-on"),
    pytest.param((1.4, 0.6, -1.8, -0.8), id="oblique"),
    pytest.param((1.05, 0.0, -0.6, 0.0), id="slow-but-close"),
    pytest.param((0.4, 1.2, 0.0, -2.0), id="lateral-crosser"),
)


@pytest.mark.parametrize("approach", _TTC_APPROACHES)
def test_the_ttc_verdict_alone_preempts_a_nominal_ramp_on_the_same_tick(
    tmp_path: Path,
    approach: tuple[float, float, float, float],
) -> None:
    """AF-1, closing the audit's J-B finding: the TTC half of the re-gate.

    ``_regate_nominal_stop`` re-disposes the ramp candidate through TWO
    authorities — ``apply_reactive_safety`` and then the TTC verdict. Every
    pre-existing preemption test drives the first one, so silently deleting the
    TTC call from that method left the whole safety-adjacent selection green.
    This test drives the SECOND one alone.

    The isolation is structural, not a tuned coincidence:

    * ``apply_reactive_safety`` never reads ``observation.dynamic_agents``. The
      only consumer of a declared track is the TTC gate, so the geometric gate
      cannot be the thing that stops this tick — and the assertion below holds
      it to that, on its real return values, with no injection anywhere.
    * The pre-gate smoother is put at exact zero before the tick, which is the
      ordinary mid-ramp state (intent zero, smoother collapsed, the ACTUATOR
      still coasting down the ramp). The tick's first gate pass therefore sees
      a non-translating command, and ``time_to_collision_verdict`` can only
      return ``'stopped'`` for a command that is moving — so the first pass is
      structurally incapable of producing the emergency, whatever the geometry.
      The ramp candidate, which IS moving, is not.

    Non-vacuity is proven inside the test: an identical tick with the track
    parked far away ramps on and dispatches a non-zero command.
    """

    x, y, vx, vy = approach
    closing = DynamicAgentTrack(
        agent_id="crosser", kind="person", x=x, y=y, vx=vx, vy=vy, radius_m=0.35
    )
    parked = DynamicAgentTrack(
        agent_id="crosser", kind="person", x=12.0, y=0.0, vx=0.0, vy=0.0, radius_m=0.35
    )

    runtime = _runtime(tmp_path, ramp=True, time_to_collision=True)
    sent = _capture(runtime)
    # Both authorities are OBSERVED, not injected: the wrappers return exactly
    # what the real callables returned, so nothing below is a staged verdict.
    gate_calls: list[tuple[VelocityCommand, VelocityCommand, str]] = []
    verdicts: list[tuple[float, str]] = []
    original_gate = runtime_module.apply_reactive_safety
    original_ttc = runtime_module.time_to_collision_verdict

    def watched_gate(command, observation, **kwargs):
        result = original_gate(command, observation, **kwargs)
        gate_calls.append((command, result[0], result[1]))
        return result

    def watched_ttc(**kwargs):
        verdict = original_ttc(**kwargs)
        verdicts.append((verdict.scale, verdict.proximity_state))
        return verdict

    runtime_module.apply_reactive_safety = watched_gate  # type: ignore[assignment]
    runtime_module.time_to_collision_verdict = watched_ttc  # type: ignore[assignment]
    try:
        assert runtime.time_to_collision.enabled is True
        _warm(runtime, sent)

        # Mid-ramp state: intent zero, pre-gate smoother already collapsed.
        runtime.velocity_smoother.reset()

        # --- non-vacuity control: same tick, nothing on a collision course ---
        gate_calls.clear()
        verdicts.clear()
        _stop_tick(runtime, agents=(parked,))
        assert sent[-1].vx > 0.0, "the ramp must be in flight before the approach"
        assert runtime._nominal_stop_ramping is True
        assert math.isinf(runtime._min_time_to_collision_s)
        assert len(verdicts) == 2, (
            "both the tick's first gate pass AND the ramp's re-gate must consult "
            f"the TTC verdict; saw {verdicts}"
        )
        assert [state for _, state in verdicts] == ["clear", "clear"], verdicts

        # --- the approach ----------------------------------------------------
        gate_calls.clear()
        verdicts.clear()
        ramps = runtime._nominal_stop_ramp_ticks
        regates = runtime._nominal_stop_regate_ticks
        preempts = runtime._nominal_stop_preempt_ticks
        _stop_tick(runtime, agents=(closing,))

        # The tick really was a nominal ramp tick that reached the re-gate.
        assert runtime._nominal_stop_ramp_ticks == ramps + 1
        assert runtime._nominal_stop_regate_ticks == regates + 1
        # The RE-GATE's own TTC verdict is the stop, and the tick's first pass
        # was not one: the first pass sees a non-translating command, which
        # ``time_to_collision_verdict`` can only ever call 'slowing'.
        assert len(verdicts) == 2, "the ramp candidate must reach the TTC verdict"
        assert verdicts[0][1] != "stopped", verdicts
        assert verdicts[1] == (0.0, "stopped"), verdicts
        assert runtime._min_time_to_collision_s <= runtime.time_to_collision.stop_s
        assert runtime._nominal_stop_preempt_ticks == preempts + 1

        # The geometric gate stayed out of it: no 'stopped' state, and it never
        # zeroed a translating command. Whatever stopped this tick, it was not
        # ``apply_reactive_safety``.
        assert len(gate_calls) == 2, "one first pass + one re-gate"
        for command, disposed, state in gate_calls:
            assert state != "stopped", gate_calls
            if math.hypot(command.vx, command.vy) > 1e-6:
                assert math.hypot(disposed.vx, disposed.vy) > 1e-6, gate_calls
        candidate = gate_calls[-1][0]
        assert math.hypot(candidate.vx, candidate.vy) > 1e-6, "the re-gate saw a moving ramp"

        # Same tick, HARD: exact zero at the actuator, shaper zeroed, ramp over.
        assert sent[-1] == ZERO_COMMAND
        assert runtime._last_sent == ZERO_COMMAND
        assert runtime._last_shaped == (0.0, 0.0, 0.0)
        assert runtime._nominal_stop_ramping is False
    finally:
        runtime_module.apply_reactive_safety = original_gate  # type: ignore[assignment]
        runtime_module.time_to_collision_verdict = original_ttc  # type: ignore[assignment]
        runtime.close()


# --- (e) resume-reset ---------------------------------------------------------


def _resume_shaper_series(tmp_path: Path, *, ramp: bool) -> list[tuple[float, float, float]]:
    """Shaper outputs on the ticks after a stop, on an identical clock.

    The resume-reset claim is about the SHAPER's cached state, so it is measured
    on the shaper with the wall clock removed from the comparison (both arms are
    driven with the same explicit ``now`` sequence).
    """

    runtime = _runtime(tmp_path, ramp=ramp)
    sent = _capture(runtime)
    try:
        _warm(runtime, sent)
        for _ in range(3):
            _stop_tick(runtime)
        # Exactly what ``_dispatch_active`` does before shaping a resume tick.
        runtime._resume_reset_after_nominal_ramp()
        series: list[tuple[float, float, float]] = []
        now = 1000.0
        for _ in range(10):
            now += 0.1
            shaped = runtime._shape_for_actuator(
                VelocityCommand(vx=0.6), now=now, stopping=False
            )
            series.append((shaped.vx, shaped.vy, shaped.vyaw))
        return series
    finally:
        runtime.close()


def test_resume_after_a_nominal_ramp_is_byte_equal_to_a_flag_off_resume(
    tmp_path: Path,
) -> None:
    """Resume-reset: the ramp may not leak velocity into the resume ramp."""

    flag_off = _resume_shaper_series(tmp_path / "off", ramp=False)
    flag_on = _resume_shaper_series(tmp_path / "on", ramp=True)

    assert flag_on == flag_off
    for on_tick, off_tick in zip(flag_on, flag_off):
        for on_value, off_value in zip(on_tick, off_tick):
            assert on_value.hex() == off_value.hex()
    assert flag_off[0][0] > 0.0, "the arms must actually resume, not sit at zero"


def test_a_nominal_stop_does_not_run_the_hard_stop_reset_obligations(
    tmp_path: Path,
) -> None:
    """The one end-to-end difference the flag introduces, stated exactly.

    A nominal stop is NOT a hard stop, so it does not reset the PRE-gate
    velocity smoother; the shaper is instead re-synced to the gate's own
    disposition. Byte-equality of the resume is therefore claimed for the shaper
    (the stage the record's resume-reset names) and not for the smoother, whose
    residual is itself re-gated on every subsequent tick. Recorded here rather
    than left for a reader to discover in a diff.
    """

    def smoother_resets(path: Path, *, ramp: bool) -> int:
        runtime = _runtime(path, ramp=ramp)
        sent = _capture(runtime)
        resets = {"n": 0}
        original = runtime.velocity_smoother.reset

        def counted(**kwargs):
            resets["n"] += 1
            return original(**kwargs)

        try:
            _warm(runtime, sent)
            runtime.velocity_smoother.reset = counted  # type: ignore[method-assign]
            _stop_tick(runtime)
            return resets["n"]
        finally:
            runtime.close()

    assert smoother_resets(tmp_path / "off", ramp=False) == 1
    assert smoother_resets(tmp_path / "on", ramp=True) == 0


def test_the_shaper_is_zeroed_before_the_resume_tick(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path, ramp=True)
    sent = _capture(runtime)
    try:
        _warm(runtime, sent)
        _stop_tick(runtime)
        assert runtime._nominal_stop_ramping is True
        assert runtime._last_shaped[0] > 0.0

        states: list[tuple[float, float, float]] = []
        original = runtime._shape_for_actuator

        def watched(command, *, now, stopping, nominal_stop=False):
            states.append(runtime._motion_shaper._velocity[:3])  # type: ignore[arg-type]
            return original(command, now=now, stopping=stopping, nominal_stop=nominal_stop)

        runtime._shape_for_actuator = watched  # type: ignore[method-assign]
        _seed(runtime)
        runtime.submit_motion("voice", VelocityCommand(vx=0.6), ttl=5.0)
        runtime._dispatch_active()

        assert states, "the resume tick must reach the shaper"
        assert tuple(states[0]) == (0.0, 0.0, 0.0)
        assert runtime._nominal_stop_ramping is False
    finally:
        runtime.close()


# --- (f) the stopping-predicate symbol pin ------------------------------------


def _named_source(source: str, name: str) -> str:
    for node in ast.parse(source).body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name == name:
            return ast.unparse(node)
    raise AssertionError(f"{name!r} not found")


def _method_source(source: str, class_name: str, method: str) -> str:
    for node in ast.parse(source).body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for stmt in node.body:
                if isinstance(stmt, ast.FunctionDef) and stmt.name == method:
                    return ast.unparse(stmt)
    raise AssertionError(f"{class_name}.{method} not found")


def _symbol_source(source: str, symbol: str) -> str:
    if "." in symbol:
        class_name, method = symbol.split(".", 1)
        return _method_source(source, class_name, method)
    return _named_source(source, symbol)


def _symbol_digest(source: str, symbol: str) -> str:
    return hashlib.sha256(_symbol_source(source, symbol).encode("utf-8")).hexdigest()


#: Card J-B's stopping-predicate ratchet, in the REACTIVE_SAFETY_PIN pattern
#: (``tests/test_dynamic_layer.py``). It exists because the bench and the
#: product now have to agree about WHICH stops may ramp: the FOLLOW_BENCH jerk
#: number is only a claim about shipped behaviour while the replica classifies
#: stops the way the runtime does. AST-normalised, so comments and reformatting
#: are green and only a semantic move is red.
#:
#: Regenerate (and record WHY in the batch status doc — do not delete this test):
#:
#:   PYTHONPATH=src:. .parcel/bin/python -c "
#:   import pathlib, sys; sys.path.insert(0,'tests')
#:   from test_nominal_stop_wiring import _symbol_digest, STOPPING_PREDICATE_PIN
#:   for path, symbols in STOPPING_PREDICATE_PIN.items():
#:       src = pathlib.Path(path).read_text()
#:       for symbol in symbols:
#:           print(path, repr(symbol), repr(_symbol_digest(src, symbol)))"
#:
#: Regeneration log — one line per movement:
#: * 2026-08-11 (card J-B) — captured at creation, on the landed severity split.
#: * 2026-08-11 (mini-lane AF-1) — ADDED six symbols, no pinned digest moved.
#:   The Fable Wave-1 audit proved by mutation that the pin stopped at
#:   ``_nominal_stop_ramp_tick`` and did not cover the ``_regate*`` bodies it
#:   calls: deleting the TTC verdict from ``_regate_nominal_stop`` left the pin
#:   and the whole safety-adjacent selection green. The re-gate is half the
#:   stopping predicate, so both machines' ``_regate*`` methods and the three
#:   threshold helpers that read their output are now pinned too.
#: * 2026-08-18 (card R4-lite, task_1) — MOVED ``_dispatch_active`` only. The
#:   proximity TRANSITION EVENT — three ``_emit`` calls plus the
#:   ``_proximity_state`` assignment — was lifted verbatim into
#:   ``_emit_proximity_change`` so the slow/clear pair can be rate-limited and
#:   coalesced: a threshold flapping at the 10 Hz control rate was flushing the
#:   100-slot event deque and taking mission terminals out with it. Nothing
#:   about WHICH stops may ramp changed. ``proximity_state`` still comes from
#:   the same ``_collision_safe`` call, is still assigned on every transition,
#:   and every predicate below that line — ``emergency_stopping``,
#:   ``zero_intent``, ``stopping``, ``nominal_ramp`` — is untouched. Only the
#:   event TEXT moved. Reason recorded in scrum/20260818/task_1/R4L_STATUS.md.
#: * 2026-08-22 (card P0-D, scrum/20260822/task_4) — MOVED ``_dispatch_active``
#:   only, one call: ``velocity_smoother.force(command)`` ->
#:   ``velocity_smoother.sync_after_gate(command)``. Defect MOVE1-D1: forcing
#:   the ramp to the POST-gate command re-applied the reactive slow-scale to its
#:   own output every tick, so the slow band delivered 0.0279 m/s where one
#:   application of the same gate to the same policy gives 0.0591 m/s (100 % of
#:   255 slowing ticks, scrum/20260821/task_20/MOVE1_STATUS.md §5).
#:   ``sync_after_gate`` collapses the ramp on an axis the gate ZEROED — which
#:   is byte-identical to ``force`` for every stop, and stops are the only thing
#:   this pin classifies — and keeps the pre-gate value on an axis the gate
#:   merely SCALED. No predicate below that line moved: ``emergency_stopping``,
#:   ``zero_intent``, ``stopping`` and ``nominal_ramp`` are character-identical,
#:   and ``proximity_state`` still comes from the same ``_collision_safe`` call.
#:   KNOWN DIVERGENCE, declared rather than fixed: the bench replica
#:   (``evals/companion_nav/runner.py::_DispatchReplica.step``, which is NOT a
#:   pinned symbol) still calls ``force`` on the post-gate command, so its
#:   slow-band speeds now measure the compounding the product no longer has.
#:   ``evals/**`` is outside P0-D's OWNS; handed off in
#:   scrum/20260822/task_4/P0D_STATUS.md.
STOPPING_PREDICATE_PIN: dict[str, dict[str, str]] = {
    "src/parcel_robot/runtime.py": {
        "RobotRuntime._dispatch_active": (
            "51a508473b78c51a8b0dc916d1eead84f57455bc130f93f73aed52322905dc51"
        ),
        "RobotRuntime._finalize_for_actuator": (
            "e8d737068343a2945a2484a542d241d2ec0a737dcd6be1d69e1cb8c936769e7a"
        ),
        # A4 SPINE (scrum/20260824/task_2) re-froze the next two digests. The
        # ONLY change to either body is the observation annotation, which moved
        # off the simulator backend type onto the transitional carrier Protocol
        # (``SimObservation | None`` -> ``ObservationCarrierV1 | None``) so that
        # runtime.py stops importing ``backends.base.SimObservation`` (audit row
        # K3). Proved by diffing ``ast.unparse`` of each symbol against HEAD
        # f1a6a92: exactly one changed line each, the ``def`` line. No predicate,
        # threshold or ordering moved, so the runtime/replica parity claim this
        # pin protects is unchanged and the replica needed no edit.
        "RobotRuntime._nominal_stop_ramp_tick": (
            "92a5ccdc69d8c442b63e97f0091c02e2c07dc9646aa5f3b9a105a0e7956a0d6f"
        ),
        # AF-1: the re-gate itself — both authorities it consults, in order.
        "RobotRuntime._regate_nominal_stop": (
            "4ddc8c1ae2b3a2a89b2994575ea3244c7a5d08c966d46f021ee8ba9299731457"
        ),
        # AF-1: the thresholds the ramp's disposition is read against. A moved
        # tolerance here reclassifies stops without touching any method above.
        "_is_zero_command": (
            "5e97a33de0fb9cc8d9c395234517ff2725ece4bcc3731abfdc5ecbcce11006d8"
        ),
        "_finite_command_values": (
            "505f33dd2b8873800ee275ad1f3b4addd0bea2b666286e9c72c0e377e7e10ee5"
        ),
        "_command_translates": (
            "1490a9fe503edba6ddcaa5ff962f9f3a3b25fc5ac787ca682880a78e0f6e8bd4"
        ),
    },
    "evals/companion_nav/runner.py": {
        "_DispatchReplica._shape": (
            "43f95b5a1f572696e69ab939b42119edf1023372c2c47347f42365a66a8d38bd"
        ),
        "_DispatchReplica._shape_severity_split": (
            "2c93f4782f8893f294f8f531a6704b5119c9dcf513a47cc1ba9e762da6e4fac1"
        ),
        "_DispatchReplica._nominal_stop_ramp_tick": (
            "4c414668c92f56973e7a73b6a1e32f76a99726853696065219276a7ab4c7175d"
        ),
        # AF-1: the replica's half of the same re-gate, and its zero threshold.
        "_DispatchReplica._regate": (
            "42470992a3c60335b5fa57b9bab137f885d5a08bdf494e0092e1c88d5e6f0be4"
        ),
        "_is_zero": (
            "c75bc1802f310e9d2d57ae19c297202a1e068a5fa255f29d93fd817f2cdc9d25"
        ),
    },
}


def test_both_machines_stopping_predicates_are_pinned() -> None:
    drifted: list[str] = []
    for path, symbols in sorted(STOPPING_PREDICATE_PIN.items()):
        source = (REPO / path).read_text(encoding="utf-8")
        for symbol, pinned in sorted(symbols.items()):
            actual = _symbol_digest(source, symbol)
            if actual != pinned:
                drifted.append(f"  {path}::{symbol}: {actual} != pinned {pinned}")

    assert not drifted, (
        "a stopping predicate changed semantically:\n"
        + "\n".join(drifted)
        + "\n\nThis is a ratchet, not a blocker. The runtime and the bench replica "
        "must classify stops the same way or the FOLLOW_BENCH jerk number stops "
        "being a claim about shipped behaviour. If the change is intended, "
        "regenerate the pin with the command in its docstring and record the "
        "reason in the batch status doc."
    )


def test_the_flag_on_split_classifies_on_the_intent_in_both_machines() -> None:
    """Operand parity (adjudication #4), asserted on the live sources.

    The runtime has always classified on the intent. The bench replica's
    FLAG-OFF path classifies on the post-chain command and stays byte-untouched
    — that pre-existing divergence is recorded in the status doc's
    does_not_prove, not fixed here. What this pins is that the flag-ON split
    reads the INTENT on both sides.
    """

    runtime_src = (REPO / "src/parcel_robot/runtime.py").read_text(encoding="utf-8")
    replica_src = (REPO / "evals/companion_nav/runner.py").read_text(encoding="utf-8")

    dispatch = _symbol_source(runtime_src, "RobotRuntime._dispatch_active")
    assert "zero_intent = active is not None and _is_zero_command(active.command)" in dispatch
    assert "nominal_ramp = " in dispatch

    split = _symbol_source(replica_src, "_DispatchReplica._shape_severity_split")
    assert "_is_zero(intent)" in split
    assert "_is_zero(command)" not in split, "the flag-ON split must not read the command"

    flag_off = _symbol_source(replica_src, "_DispatchReplica._shape")
    assert "emergency=proximity_state == 'stopped' or _is_zero(command)" in flag_off
