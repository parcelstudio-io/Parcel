"""Card AWARE-1 (`scrum/20260823/task_4`) — the periodic head turn.

Capability tests only, per the owner's binding testing directive: what the
behaviour DOES, measured through the product path, not a lattice of seeded
guards. Four groups:

* the proposer itself, pure and clock-injected (cadence, the arc bound, the
  heading it leaves behind);
* the R28 axis table, against the REAL input-health classes rather than
  strings this file invented — `scrum/20260823/task_4/R28_AXIS_TABLE.md` is
  the page these rows ratify;
* the runtime wiring — the sweep reaching the arbiter and degrading cleanly
  when motion is refused, which is the path the feature actually takes on the
  hardware that exists today;
* the two wave-A wire-ins this card carries: PROX-1's venue-mapped proximity
  profile at the `ReactiveSafetyPolicy` construction, and SENSE-1's pose seam
  read AT THE RUNTIME JOIN — not at the source, which SENSE-1 already proved.

No simulator is started and no socket is opened: the Go2 rows reuse HW-2's
recorded fixture and injected transports.
"""

from __future__ import annotations

import threading
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
import yaml

from parcel_robot.backends.base import RobotPose, SimObservation
from parcel_robot.core.input_health import (
    HealthAction,
    InputFault,
    InputHealthVerdict,
    RequiredInput,
)
from parcel_robot.models import VelocityCommand
from parcel_robot.navigation.awareness_sweep import (
    AwarenessLimits,
    AwarenessProposal,
    AwarenessSweep,
    awareness_limits_from_config,
    awareness_yaw_permitted,
)
from parcel_robot.navigation.proximity_profiles import ProximityContext

REPO = Path(__file__).resolve().parents[1]

#: The block this card would have added to `configs/robot.yaml` if that file
#: were not SHA-locked (`evals/companion/embodied_plan_v1/manifest.json`
#: `robot_config`, `tests/test_hw5_physical_profile.py:69`). Card PROX-1 hit
#: the same wall this wave and shipped its table as code constants for the same
#: reason. Proven loadable here, so landing it after an authorised re-pin needs
#: no code change: only the `enabled` default and the YAML.
PROPOSED_AWARENESS_BLOCK = """
awareness:
  enabled: true
  idle_period_s: 25.0
  sweep_arc_rad: 1.4
  sweep_vyaw: 0.35
"""


def _limits(**overrides: Any) -> AwarenessLimits:
    base = {
        "enabled": True,
        "idle_period_s": 1.0,
        "sweep_arc_rad": 1.4,
        "sweep_vyaw": 0.35,
    }
    base.update(overrides)
    return AwarenessLimits(**base)


def _drive(
    sweep: AwarenessSweep,
    *,
    ticks: int,
    dt: float = 0.25,
    idle: bool = True,
    permitted: bool = True,
) -> list[AwarenessProposal | None]:
    """Run the pure proposer on an injected clock. No wall time involved."""

    return [
        sweep.step(index * dt, idle=idle, yaw_permitted=permitted)
        for index in range(ticks)
    ]


# ===========================================================================
# 1 — the proposer: cadence, bound, and the heading it leaves behind
# ===========================================================================


def test_the_cadence_fires_only_after_the_configured_idle_period() -> None:
    """An idle robot looks around — but not the instant it goes idle.

    The period is measured from when the robot BECAME idle, so a dog that has
    just finished doing something does not immediately start turning.
    """

    sweep = AwarenessSweep(_limits(idle_period_s=2.0))
    emitted = _drive(sweep, ticks=12, dt=0.25)

    # Nothing for the first 2 s of idleness (ticks 0..7), then it starts.
    assert emitted[:8] == [None] * 8
    assert sweep.sweeps_started == 0 or emitted[8] is not None
    assert emitted[8] is not None
    assert sweep.sweeps_started == 1
    # And it is a yaw. There is nowhere on the proposal to put a translation.
    assert not hasattr(emitted[8], "vx")
    assert not hasattr(emitted[8], "vy")
    assert emitted[8].reason == "awareness_sweep"


def test_one_sweep_commands_no_more_than_the_configured_arc() -> None:
    """THE BOUND, measured as the angle actually commanded.

    Integrating |vyaw| over the ticks each proposal is held for is the honest
    measure: a proposal issued on the last tick of a sweep is still held until
    the next one, which is why the class stops when another tick WOULD cross
    the arc rather than when the arc is already crossed.
    """

    for arc, vyaw, dt in ((1.4, 0.35, 0.25), (0.6, 0.2, 0.1), (3.0, 0.8, 0.5)):
        sweep = AwarenessSweep(_limits(idle_period_s=0.5, sweep_arc_rad=arc, sweep_vyaw=vyaw))
        commanded = 0.0
        peak = 0.0
        heading = 0.0
        for index in range(400):
            proposal = sweep.step(index * dt, idle=True, yaw_permitted=True)
            if proposal is None:
                if sweep.sweeps_completed:
                    break
                continue
            assert abs(proposal.vyaw) == pytest.approx(vyaw), "the rate bound is per-command"
            commanded += abs(proposal.vyaw) * dt
            heading += proposal.vyaw * dt
            peak = max(peak, abs(heading))
        assert sweep.sweeps_completed == 1
        assert commanded <= arc + 1e-9, f"swept {commanded} past the {arc} rad bound"
        # Out and back: the furthest the body ever gets from where it started
        # is half the arc, not the whole of it.
        assert peak <= arc / 2.0 + vyaw * dt + 1e-9


def test_consecutive_sweeps_leave_the_heading_where_they_found_it() -> None:
    """A robot that looks around must not have turned round by morning.

    A discrete tick cannot reverse at exactly half the arc, so every sweep
    leaves a residual. Alternating the start direction makes consecutive
    residuals cancel instead of accumulate — ROAM-1's lesson, which measured a
    patrol doing 3.9 unintended full turns.
    """

    sweep = AwarenessSweep(_limits(idle_period_s=0.5))
    heading = 0.0
    at_completion: list[float] = []
    completed = 0
    peak = 0.0
    for index in range(400):
        proposal = sweep.step(index * 0.25, idle=True, yaw_permitted=True)
        if proposal is not None:
            heading += proposal.vyaw * 0.25
            peak = max(peak, abs(heading))
        if sweep.sweeps_completed != completed:
            completed = sweep.sweeps_completed
            at_completion.append(heading)

    assert len(at_completion) >= 6
    # Measured AT the sweep boundaries, which is the only place the claim
    # means anything: mid-sweep the robot is of course pointing elsewhere.
    for index, resting in enumerate(at_completion):
        assert resting == pytest.approx(0.0, abs=1e-9), (
            f"sweep {index + 1} left the heading at {resting} rad"
        )
    # And the excursion during a sweep never exceeded half the arc plus the
    # one tick the proposal is held for.
    assert peak <= 0.7 + 0.35 * 0.25 + 1e-9
    # Both directions actually get used, so this is alternation and not a
    # sweep that happens to be symmetric in one direction only.
    assert sweep.sweeps_completed >= 6


def test_a_suppression_abandons_a_sweep_in_progress_rather_than_pausing_it() -> None:
    """A sweep that resumed mid-arc would be finishing a gesture it began
    under evidence that no longer holds."""

    sweep = AwarenessSweep(_limits(idle_period_s=0.5))
    for index in range(6):
        sweep.step(index * 0.25, idle=True, yaw_permitted=True)
    assert sweep.sweeping

    assert sweep.step(1.6, idle=True, yaw_permitted=False) is None
    assert not sweep.sweeping
    assert sweep.swept_rad == 0.0
    # And the cadence restarts: the next tick does not resume mid-arc.
    assert sweep.step(1.7, idle=True, yaw_permitted=True) is None


def test_a_misspelled_awareness_key_refuses_instead_of_reading_as_no_bound() -> None:
    """`configs/config.py`'s own lesson: a key nothing reads is
    indistinguishable from a key nobody wrote."""

    loaded = awareness_limits_from_config(
        yaml.safe_load(PROPOSED_AWARENESS_BLOCK)["awareness"]
    )
    assert loaded.enabled is True
    assert loaded.idle_period_s == 25.0
    assert loaded.sweep_arc_rad == 1.4
    assert loaded.sweep_vyaw == 0.35

    with pytest.raises(ValueError, match="sweep_arc_radians"):
        awareness_limits_from_config({"sweep_arc_radians": 1.4})
    with pytest.raises(ValueError):
        awareness_limits_from_config({"sweep_vyaw": 0.0})
    with pytest.raises(ValueError, match="turn_vyaw"):
        awareness_limits_from_config({"sweep_vyaw": 1.5})
    with pytest.raises(TypeError):
        awareness_limits_from_config({"idle_period_s": "25"})
    # An absent section is the shipped default, and the shipped default is OFF.
    assert awareness_limits_from_config(None).enabled is False


# ===========================================================================
# 2 — the R28 axis table, against the real input-health classes
# ===========================================================================

#: Every LATCHED_STOP class `core/input_health.py` can emit, by name. Read off
#: `_fault_for` (`:236-268`) and `_global_latched_fault` (`:687`). The ordering
#: reasons (`sequence_duplicate` and friends) are not here on purpose: they
#: reach the join AS `payload_malformed`, which is.
LATCHING_CLASSES = (
    "malformed",
    "timestamp_malformed",
    "timestamp_in_future",
    "payload_malformed",
    "frame_inconsistent",
    "origin_malformed",
    "origin_unknown",
    "sim_fixture_forbidden",
    "sim_fixture_unlabeled",
    "physical_input_has_fixture_label",
    "decision_time_malformed",
    "evidence_table_malformed",
)


def _verdict(*faults: tuple[RequiredInput, str, HealthAction]) -> InputHealthVerdict:
    built = tuple(InputFault(item[0], item[1], item[2]) for item in faults)
    action = max((fault.action for fault in built), default=HealthAction.ALLOW)
    return InputHealthVerdict(action=action, faults=built)


@pytest.mark.parametrize("reason", LATCHING_CLASSES)
@pytest.mark.parametrize(
    "required", (RequiredInput.POSE, RequiredInput.SCAN, RequiredInput.CONTROLLER_FEEDBACK)
)
def test_every_latching_class_forbids_a_sensing_yaw(
    reason: str, required: RequiredInput
) -> None:
    """R28 rule A. A latch is all-axis, on every input, without exception."""

    verdict = _verdict((required, reason, HealthAction.LATCHED_STOP))
    assert awareness_yaw_permitted(verdict) is False


def test_the_hold_classes_split_exactly_where_the_r28_table_says_they_do() -> None:
    """R28 rules B, C and D, and the asymmetry between them is the point.

    The GATE preserves yaw through EVERY HOLD (`runtime.py:14050`). AWARE-1
    says yes to three named pairs and nothing else, because a discretionary
    look is not a recovery manoeuvre and giving up authority it is owed costs
    nothing.
    """

    for reason in ("missing", "stale"):
        # Rule B — the recoverable scan gap, where turning is what fixes it.
        assert awareness_yaw_permitted(
            _verdict((RequiredInput.SCAN, reason, HealthAction.HOLD))
        ) is True
        # Rule C — an arc you cannot measure cannot be bounded. Both classes.
        assert awareness_yaw_permitted(
            _verdict((RequiredInput.POSE, reason, HealthAction.HOLD))
        ) is False
        # A scan hold does not launder a pose hold beside it.
        assert awareness_yaw_permitted(
            _verdict(
                (RequiredInput.SCAN, reason, HealthAction.HOLD),
                (RequiredInput.POSE, reason, HealthAction.HOLD),
            )
        ) is False

    # Rule D, and it splits — this is the row measurement corrected. A robot at
    # rest has published no motion state at all, and demanding one before the
    # first command would deadlock the behaviour forever.
    assert awareness_yaw_permitted(
        _verdict((RequiredInput.CONTROLLER_FEEDBACK, "missing", HealthAction.HOLD))
    ) is True
    # ...but a controller that ANSWERED and then stopped is the open-loop turn
    # worth refusing, and it is the class a dying controller actually produces
    # once a sweep is running and feedback is being published.
    assert awareness_yaw_permitted(
        _verdict((RequiredInput.CONTROLLER_FEEDBACK, "stale", HealthAction.HOLD))
    ) is False
    # The real shape a stationary simulator runtime produces, together.
    assert awareness_yaw_permitted(
        _verdict(
            (RequiredInput.SCAN, "missing", HealthAction.HOLD),
            (RequiredInput.CONTROLLER_FEEDBACK, "missing", HealthAction.HOLD),
        )
    ) is True

    # ALLOW is the ordinary case, and it carries no faults.
    assert awareness_yaw_permitted(_verdict()) is True
    # Rule E — an unclassified class, an absent verdict, and an already-set
    # runtime latch all default to "no".
    assert awareness_yaw_permitted(
        _verdict((RequiredInput.SCAN, "a_class_from_the_future", HealthAction.HOLD))
    ) is False
    assert awareness_yaw_permitted(None) is False
    assert awareness_yaw_permitted(_verdict(), latched=True) is False


# ===========================================================================
# 3 — the runtime wiring
# ===========================================================================


class _AwarenessBackend:
    """Minimal backend: fresh observations, and it records what it was told."""

    name = "fake"

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self.moves: list[VelocityCommand] = []
        self.stop_count = 0
        self._observation = SimObservation(
            timestamp=time.monotonic(),
            robot=RobotPose(x=0.0, y=0.0, yaw=0.0),
            owner=None,
            lidar_ranges=(),
        )

    def observe(self) -> SimObservation:
        return replace(self._observation, timestamp=time.monotonic())

    def move(self, command: VelocityCommand) -> None:
        with self._condition:
            self.moves.append(command)

    def stop(self) -> None:
        with self._condition:
            self.stop_count += 1

    def pose(self, pose: object) -> None:
        return None

    def trajectory(self, skill: object) -> None:
        return None

    def move_owner(self, dx: float, dy: float) -> None:
        return None

    def close(self) -> None:
        return None


def _config(tmp_path: Path, **top_level: Any) -> Path:
    """A copy of the shipped base config, plus whatever a row needs on top."""

    document = yaml.safe_load((REPO / "configs" / "robot.yaml").read_text(encoding="utf-8"))
    for key, value in top_level.items():
        if isinstance(value, dict) and isinstance(document.get(key), dict):
            document[key].update(value)
        else:
            document[key] = value
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "robot.yaml"
    path.write_text(yaml.safe_dump(document), encoding="utf-8")
    return path


def _runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, **top_level: Any):
    from parcel_robot.runtime import RobotRuntime

    monkeypatch.setenv("PARCEL_MEMORY_PATH", str(tmp_path / "memory.sqlite3"))
    return RobotRuntime(_config(tmp_path, **top_level), _AwarenessBackend())


def _arm(runtime, monkeypatch: pytest.MonkeyPatch, **overrides: Any) -> None:
    """Turn the sweep on for one row, and let the loop ask every tick."""

    from parcel_robot import runtime as runtime_module

    monkeypatch.setattr(runtime_module, "AWARENESS_TICK_S", 0.0)
    runtime._awareness_limits = _limits(idle_period_s=0.005, **overrides)
    runtime._awareness_sweep = AwarenessSweep(runtime._awareness_limits)


def test_an_idle_runtime_proposes_a_yaw_only_sweep_through_the_arbiter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The wiring, end to end: cadence -> `submit_motion` -> the arbiter.

    No new authority anywhere. The proposal rides the channel roam already
    rides and wins the arbiter only because nothing else wants the body.
    """

    runtime = _runtime(tmp_path, monkeypatch)
    try:
        _arm(runtime, monkeypatch)
        observation = runtime.backend.observe()
        runtime._step_awareness(observation)  # starts the cadence clock
        assert runtime.arbiter.current() is None
        time.sleep(0.01)
        runtime._step_awareness(runtime.backend.observe())

        intent = runtime.arbiter.current()
        assert intent is not None, "the sweep never reached the arbiter"
        assert intent.source == "voice"
        assert intent.command.vx == 0.0 and intent.command.vy == 0.0
        assert abs(intent.command.vyaw) == pytest.approx(0.35)
        assert runtime._awareness_sweep.sweeping is True
        assert runtime.awareness_snapshot()["sweeps_started"] == 1
    finally:
        runtime.close()


def test_a_refused_proposal_abandons_the_sweep_and_is_counted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The path the feature actually takes today: the body refuses motion.

    An owner holding the body at a higher priority is the same shape as a
    backend that will not move — the proposal is refused, and a refusal is
    DATA, never an exception that reaches the control loop.
    """

    runtime = _runtime(tmp_path, monkeypatch)
    try:
        _arm(runtime, monkeypatch)
        # Manual teleop (priority 80) outbids the sweep's channel (60).
        runtime.submit_motion("manual", VelocityCommand(vx=0.1), ttl=30.0)

        runtime._step_awareness(runtime.backend.observe())
        time.sleep(0.01)
        runtime._step_awareness(runtime.backend.observe())  # must not raise

        # And it is the ARBITER refusing, not a malformed proposal: the reason
        # the submit door gave is the owner still holding the body.
        assert runtime._awareness_refused == 1
        assert runtime._awareness_sweep.sweeping is False
        with pytest.raises(RuntimeError, match="manual currently owns motion"):
            runtime.submit_motion("voice", VelocityCommand(vyaw=0.35), ttl=0.5)
        # The owner still owns the body; nothing the sweep did disturbed it.
        intent = runtime.arbiter.current()
        assert intent is not None and intent.source == "manual"
        assert intent.command.vx == pytest.approx(0.1)
    finally:
        runtime.close()


def test_an_r28_forbidding_verdict_suppresses_the_sweep_at_the_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The table is consulted on the product path, not only in a unit test.

    `require_physical_inputs: true` with a simulated pose is a real
    `sim_fixture_forbidden` LATCHED_STOP at the real join — rule A — so no
    proposal is made at all, however idle the robot is.
    """

    runtime = _runtime(tmp_path, monkeypatch, safety={"require_physical_inputs": True})
    try:
        _arm(runtime, monkeypatch)
        verdict = runtime._evaluate_dispatch_input_health(
            runtime.backend.observe(), now=time.monotonic()
        )
        assert verdict.action is HealthAction.LATCHED_STOP
        assert awareness_yaw_permitted(verdict) is False

        for _ in range(4):
            runtime._step_awareness(runtime.backend.observe())
            time.sleep(0.01)

        assert runtime.arbiter.current() is None
        assert runtime._awareness_sweep.sweeps_started == 0
        assert runtime.awareness_snapshot()["suppressed_reason"] == "r28_axis_table"
    finally:
        runtime.close()


# ===========================================================================
# 4 — the two wave-A wire-ins this card carries
# ===========================================================================


def test_the_commissioned_venue_gets_its_proximity_profile_and_others_are_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PROX-1's wire-in, and the reason it is conditional.

    `go2_edu_plus` maps to `indoor`, which tightens the social zone to the
    preregistered 0.95 / 2.00. A config that names no venue keeps the gate it
    commissioned, BYTE FOR BYTE — applying PROX-1's `default` rung
    unconditionally would have overwritten a deliberately retuned deployment
    (`configs/robot.prototype.yaml:197` commissions `person_stop_m: 0.7`) and
    left `runtime.person_stop_m` disagreeing with the gate it reports.
    """

    plain = _runtime(tmp_path / "plain", monkeypatch)
    try:
        assert plain._proximity_context_owner.context is ProximityContext.DEFAULT
        assert plain.reactive_safety_policy.person_stop_m == pytest.approx(1.2)
        assert plain.reactive_safety_policy.person_slow_m == pytest.approx(2.5)
        assert plain.reactive_safety_policy is plain._proximity_context_owner.base_policy
    finally:
        plain.close()

    indoor = _runtime(tmp_path / "venue", monkeypatch, venue="go2_edu_plus")
    try:
        assert indoor._proximity_context_owner.context is ProximityContext.INDOOR
        assert indoor.reactive_safety_policy.person_stop_m == pytest.approx(0.95)
        assert indoor.reactive_safety_policy.person_slow_m == pytest.approx(2.00)
        assert indoor.proximity_snapshot()["source"] == "venue"

        # The seam stays reachable for the later reasoning-model tool, and it
        # takes a preregistered NAME — never a distance.
        assert indoor.set_proximity_context("narrow") == "narrow"
        assert indoor.reactive_safety_policy.person_stop_m == pytest.approx(0.70)
        with pytest.raises(TypeError):
            indoor.set_proximity_context(0.4)
        assert indoor.reactive_safety_policy.person_stop_m == pytest.approx(0.70)
    finally:
        indoor.close()


def test_the_pose_seam_is_read_at_the_runtime_join_not_only_at_the_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SENSE-1's wire-in, measured where SENSE-1 could not: the JOIN.

    SENSE-1 proved `CommissionedPoseSource`'s rows at the seam but could not
    read it here — `runtime.py` was that card's MUST-NOT-TOUCH. This is the
    same three rows through `runtime._evaluate_dispatch_input_health`: a LIVE
    pose is PHYSICAL and no longer faults; a REPLAYED one still latches.
    """

    from test_hw2_go2_backend import _config_tree, _live_backend, _replay_backend

    from parcel_robot.runtime import RobotRuntime

    monkeypatch.setenv("PARCEL_MEMORY_PATH", str(tmp_path / "memory.sqlite3"))
    base = _config_tree(tmp_path, require_physical=True)

    live, clock = _live_backend()
    runtime = RobotRuntime(base, live)
    try:
        verdict = runtime._evaluate_dispatch_input_health(live.observe(), now=clock.t + 0.01)
        pose_faults = [f for f in verdict.faults if f.required_input is RequiredInput.POSE]
        assert pose_faults == [], "a live pose must pass the physical table"
        assert verdict.stop_latched is False
    finally:
        runtime.close()

    replay, replay_clock = _replay_backend()
    runtime = RobotRuntime(base, replay)
    try:
        verdict = runtime._evaluate_dispatch_input_health(
            replay.observe(), now=replay_clock.t + 0.01
        )
        pose_reasons = {
            f.reason for f in verdict.faults if f.required_input is RequiredInput.POSE
        }
        assert pose_reasons == {"sim_fixture_forbidden"}
        assert verdict.stop_latched is True
        # And R28 rule A: a latched verdict is no place for a discretionary look.
        assert awareness_yaw_permitted(verdict) is False
    finally:
        runtime.close()


def test_the_runtime_section_literal_matches_the_module_constant() -> None:
    """runtime.py reads ``store.section("awareness")`` as a literal so CAP-1's
    G2 cross-check can resolve it; this pin keeps that literal and the
    module's own AWARENESS_CONFIG_KEY from drifting apart."""

    from parcel_robot.navigation.awareness_sweep import AWARENESS_CONFIG_KEY

    assert AWARENESS_CONFIG_KEY == "awareness"
