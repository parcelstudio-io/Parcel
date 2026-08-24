"""Card A9 — the non-travel life half: body composer, drives, lease, terminal.

``scrum/20260824/task_2/IMPLEMENTATION_PLAN.md`` row A9; HLD Gate 8 plus §16's
ratified wave-2 amendments. What each row is bound to:

* **H4 continuous body intent** (CONFIRMED, harness-only): 50 Hz body composer,
  HOLD as a command rather than an absence, e-stop to HOLD in 17.66 ms = 0.88
  tick, locomotion byte-identical to the shipped path over 3,402 messages. Its
  verdict recorded the gap this card closes: *"nothing in ``runtime.py``
  constructs the composer"*.
* **H3 drives and initiative** (CONFIRMED-WITH-NOTES; D4 REFUTED): ~5.3
  initiations/h over three seeds (5, 5, 6), 90 % admitted, preemption in 0
  ticks, and 1,222 contact episodes when an initiated leg was allowed to
  translate — **travel radius 0**.
* **The ratified terminal amendment**: the initiated leg's terminal is a
  safe-hold invariant plus a receding horizon, NOT a scripted stop-and-return,
  which measured WORSE (contacts 319->323, contact time 89.1->244.6 s).
* **Composition**: A6's stop latch is the arbiter's and there is no second
  flag; A8's follow keeps motion authority because a drive can never claim it;
  A7's governor is asked before any hosted phrasing and refusal degrades to a
  local line.

No hosted call, no device, no owner store, and no robot: every clock is
supplied by the test.
"""

from __future__ import annotations

import ast
import dataclasses
import io
import pathlib
import tokenize
from pathlib import Path
from typing import Any

import pytest

from parcel_robot.attention.drives import (
    DriveState,
    InitiativeDigest,
    InitiativeKind,
    InitiativePolicy,
    InitiativeProposal,
    propose,
)
from parcel_robot.attention.initiative import (
    BEHAVIOR_LOOK,
    BEHAVIOR_ORIENT,
    BEHAVIOR_REMARK,
    BEHAVIOR_STRETCH,
    END_COMPLETED,
    END_EMERGENCY_STOP,
    END_OWNER_COMMAND,
    LOCAL_OPENERS,
    M1_REACHABLE_TERMINALS,
    NEUTRAL_OFFER,
    OPENER_HOSTED_ADMITTED,
    OPENER_LOCAL_NO_GOVERNOR,
    OPENER_LOCAL_REFUSED,
    OPENER_PURPOSE,
    REFUSE_DISABLED,
    REFUSE_QUIET,
    REFUSE_RATE,
    REFUSE_REFRACTORY,
    TERMINAL_HOLD,
    TERMINAL_KINDS,
    TERMINAL_RELEASE_AUTHORITY,
    TERMINAL_RETURN,
    BodyOffer,
    InitiativeLimits,
    Terminal,
    TranslationRefused,
    ZeroTranslationLease,
    open_line,
)
from parcel_robot.audio.devices import AudioDeviceStatus
from parcel_robot.backends.base import OwnerTrack, RobotPose, SimObservation
from parcel_robot.contracts.body_intent import HOLD, Velocity
from parcel_robot.core.arbiter import CommandArbiter
from parcel_robot.core.commands import SOURCE_PRIORITIES, MotionIntent
from parcel_robot.models import AgentDecision, VelocityCommand
from parcel_robot.motion.body_lane import (
    MAX_TICK_GAP_S,
    BodyIntentLane,
    install_body_lane,
)
from parcel_robot.motion.expression import ExpressiveOffsets
from parcel_robot.realtime.hosted_budget import (
    CLASS_CRITICAL,
    CLASS_ROUTINE,
    GovernorConfig,
    HostedCallGovernor,
)
from parcel_robot.runtime import RobotRuntime
from parcel_robot.safety import SafetyLimits

REPO = pathlib.Path(__file__).resolve().parents[1]
SRC = REPO / "src" / "parcel_robot"

TICK_S = 1.0 / 50.0

#: H4 row B6, the reference this card's bound is read against: e-stop to HOLD
#: in 17.66 ms, which is 0.88 of a 20 ms tick. The MECHANISM is same-tick, so
#: the bound asserted below is one tick — the residual is when in the tick the
#: flag arrived, not work the composer does.
H4_ESTOP_TICKS = 0.88
#: H3 row D1: 5, 5 and 6 initiations in an hour over three seeds.
H3_MEASURED_INITIATIONS = (5, 5, 6)


def _source(name: str) -> str:
    return (SRC / name).read_text(encoding="utf-8")


def _code(name: str) -> str:
    """The module's CODE: comments and every string literal removed.

    A structural claim ("this module cannot reach an actuator") must be made
    about what runs, not about what is written down. Grepping raw source makes
    a docstring that NAMES the forbidden thing — which a module explaining why
    it does not do it always will — indistinguishable from doing it.
    """

    kept: list[str] = []
    skip = {tokenize.COMMENT, tokenize.STRING, tokenize.NL, tokenize.NEWLINE}
    for token in tokenize.generate_tokens(io.StringIO(_source(name)).readline):
        if token.type in skip or token.type >= tokenize.FSTRING_START:
            continue
        kept.append(token.string)
    return " ".join(kept)


def _function_source(module: str, name: str) -> str:
    text = _source(module)
    tree = ast.parse(text)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.get_source_segment(text, node) or ""
    raise AssertionError(f"{module} has no function {name}")


def _lane(**limits: Any) -> BodyIntentLane:
    lane = install_body_lane(initiative=InitiativeLimits(**limits))
    assert lane is not None
    return lane


def _proposal(kind: str = InitiativeKind.LOOK.value, **overrides: Any) -> InitiativeProposal:
    fields: dict[str, Any] = {
        "kind": kind,
        "at_s": 0.0,
        "drive": "curiosity",
        "drive_value": 0.9,
        "reason": "curiosity_over_threshold:novelty",
        "seed": 1,
        "bearing_rad": 0.6,
        "budget_s": 6.0,
    }
    fields.update(overrides)
    return InitiativeProposal(**fields)


# ==========================================================================
# 1 — the composer, productized: cadence, HOLD-as-command, e-stop
# ==========================================================================


def test_the_lane_emits_one_intent_every_tick_and_hold_is_a_command() -> None:
    """H4 B1/B5, as a product property: no tick is silent, and HOLD is sent."""

    lane = _lane()
    for i in range(3_000):
        tick = lane.tick(
            offsets=ExpressiveOffsets(),
            finalized_velocity=None,
            now_s=i * TICK_S,
        )
        assert tick.intent.seq == i + 1
        assert tick.intent.locomotion is HOLD
        assert tick.intent.is_hold
        assert tick.intent.velocity is None
        assert tick.intent.ttl_ms > 0
    assert lane.ticks == lane.hold_ticks == 3_000
    assert lane.gaps_over_bound == 0


def test_the_cadence_holds_under_a_jittery_loaded_clock() -> None:
    """Replay: a 50 Hz channel on a loaded host still clears H4's 100 ms bar."""

    lane = _lane()
    now = 0.0
    jitter = (0.0, 0.004, 0.011, 0.002, 0.015, 0.001)
    for i in range(6_000):
        now += TICK_S + jitter[i % len(jitter)]
        lane.tick(offsets=ExpressiveOffsets(), finalized_velocity=None, now_s=now)
    assert lane.max_gap_s <= MAX_TICK_GAP_S
    assert lane.gaps_over_bound == 0
    measured_hz = lane.ticks / now
    assert measured_hz >= 20.0  # H4's B1 floor


def test_the_cadence_assertion_can_fail() -> None:
    """Anti-vacuity: a real stall is counted, so the bar above means something."""

    lane = _lane()
    for now in (0.0, TICK_S, 0.4, 0.42):
        lane.tick(offsets=ExpressiveOffsets(), finalized_velocity=None, now_s=now)
    assert lane.gaps_over_bound == 1
    assert lane.max_gap_s > MAX_TICK_GAP_S


def test_the_lane_copies_the_finalized_velocity_and_never_makes_one() -> None:
    """H4 B7 as a product row: the composer is downstream, not a second planner."""

    lane = _lane()
    for i, command in enumerate(
        (
            VelocityCommand(vx=0.31, vy=0.0, vyaw=-0.2),
            VelocityCommand(vx=0.0, vy=0.05, vyaw=0.0),
            VelocityCommand(vx=-0.12, vy=0.0, vyaw=0.4),
        )
    ):
        tick = lane.tick(
            offsets=ExpressiveOffsets(),
            finalized_velocity=command,
            now_s=i * TICK_S,
        )
        assert isinstance(tick.intent.locomotion, Velocity)
        assert tick.intent.locomotion.as_tuple() == (
            command.vx,
            command.vy,
            command.vyaw,
        )


def test_the_structural_reader_keeps_code_and_drops_prose() -> None:
    """Anti-vacuity for every source assertion below it."""

    code = _code("motion/body_lane.py").split()
    assert "BodyIntentLane" in code and "compose" in code and "tick" in code
    # The forbidden words the docstrings DO contain, which is the whole point.
    assert "set_target" in _source("motion/body_lane.py")
    assert "set_target" not in code


def test_the_lane_can_never_command_the_body_itself() -> None:
    """Structural: the lane has no route to an actuator, by source inspection."""

    code = _code("motion/body_lane.py")
    for forbidden in (
        "submit_motion",
        "set_target",
        "control_manager",
        "move",
        "VelocityCommand",
        "emergency_stop",
    ):
        assert forbidden not in code.split(), forbidden


def test_the_estop_reaches_hold_inside_one_tick_with_its_epoch() -> None:
    """H4 B6 mechanism + bound. Reference: 17.66 ms = 0.88 tick at 50 Hz."""

    lane = _lane()
    moving = VelocityCommand(vx=0.4)
    for i in range(50):
        lane.tick(offsets=ExpressiveOffsets(), finalized_velocity=moving, now_s=i * TICK_S)
    before = lane.composer.epoch
    assert lane.latest is not None and not lane.latest.is_hold

    flag_at = 50 * TICK_S
    tick = lane.tick(
        offsets=ExpressiveOffsets(head_yaw_rad=0.3),
        finalized_velocity=moving,
        emergency=True,
        now_s=flag_at,
    )

    assert tick.intent.locomotion is HOLD
    assert tick.intent.priority == 100
    assert tick.intent.gaze == (0.0, 0.0)  # the body is snapped, not ramped
    assert tick.intent.posture == (0.0, 0.0, 0.0)
    assert lane.composer.epoch == before + 1  # one bump, on the rising edge
    elapsed_ticks = (tick.intent.stamp_ns / 1e9 - flag_at) / TICK_S
    assert 0.0 <= elapsed_ticks <= 1.0
    assert H4_ESTOP_TICKS <= 1.0

    # Latched, not edge-triggered: the epoch does not walk while it is held.
    lane.tick(
        offsets=ExpressiveOffsets(),
        finalized_velocity=moving,
        emergency=True,
        now_s=flag_at + TICK_S,
    )
    assert lane.composer.epoch == before + 1
    assert lane.emergency_ticks == 2


# ==========================================================================
# 2 — composed BENEATH the dispatch chain, in the runtime
# ==========================================================================


def test_the_runtime_feeds_the_lane_only_what_the_chain_finalized() -> None:
    """The tap is ``_last_sent``, and ``_last_sent`` is the finalized command."""

    dispatch = _function_source("runtime.py", "_dispatch_active")
    finalize = dispatch.index("_finalize_for_actuator")
    publish = dispatch.index("self._last_sent = command")
    assert finalize < publish, "the lane's source must be POST-finalize"
    for stage in (
        "velocity_smoother.step",
        "_collision_safe",
        "_shape_for_actuator",
        "_finalize_for_actuator",
    ):
        assert stage in dispatch, stage

    step = _function_source("runtime.py", "_step_expression")
    assert "lane.tick(" in step
    assert "finalized_velocity=self._last_sent if self._was_moving else None" in step
    assert "emergency=self.arbiter.emergency_stopped" in step
    # One tap, and nothing else reaches the lane.
    assert _code("runtime.py").count("lane . tick") == 1


def test_the_lane_never_appears_in_a_safety_module() -> None:
    """The floors stay untouched: they do not import this card's modules."""

    for module in (
        "core/hard_stop.py",
        "navigation/reactive_safety.py",
        "core/arbiter.py",
        "audio/stop_hotword.py",
        "safety.py",
    ):
        text = _source(module)
        assert "body_lane" not in text
        assert "attention.initiative" not in text


# ==========================================================================
# 3 — the zero-translation lease, structurally
# ==========================================================================


def test_the_offer_a_drive_receives_cannot_express_translation() -> None:
    """The lease is a TYPE, not a rule: there is no field to put a velocity in."""

    names = {field.name for field in dataclasses.fields(BodyOffer)}
    assert names == {"behavior", "gaze", "posture", "style", "line"}
    code = _code("attention/initiative.py").split()
    for forbidden in ("VelocityCommand", "vx", "vyaw", "waypoint", "submit_motion"):
        assert forbidden not in code, forbidden


def test_a_positive_radius_cannot_even_hold_the_lease() -> None:
    with pytest.raises(TranslationRefused, match="zero-translation"):
        ZeroTranslationLease(policy=InitiativePolicy(travel_radius_m=6.0))


def test_a_travelling_proposal_is_refused_by_construction() -> None:
    """And the refusal is not vacuous: with a radius, drives DO propose travel."""

    travelling = [
        p
        for p in (
            propose(
                DriveState(at_s=0.0, curiosity=0.95, social=0.95, comfort=0.1, duty=0.1),
                InitiativeDigest(
                    at_s=t,
                    idle_s=600.0,
                    owner_present=True,
                    look_bearing_rad=0.4,
                    look_subject="movement",
                    person_id="p1",
                    person_range_m=3.0,
                    person_bearing_rad=0.3,
                    remark_subject="the window",
                    place_id="place-1",
                    place_bearing_rad=-0.5,
                    place_range_m=5.0,
                    place_age_s=600.0,
                    battery_fraction=0.9,
                ),
                InitiativePolicy(travel_radius_m=6.0, seed=t),
            )
            for t in range(40)
        )
        if p is not None and p.travels
    ]
    assert travelling, "H3's own proposer must still form travel at a radius"

    lease = ZeroTranslationLease(limits=InitiativeLimits(enabled=True))
    for proposal in travelling[:3]:
        with pytest.raises(TranslationRefused):
            lease.admit(proposal, now_s=0.0)
    assert lease.admitted == 0
    assert lease.refused == 3


def test_a_zero_budget_travel_kind_is_still_refused() -> None:
    """``travels`` is not the only door — a metre budget of any size is one too."""

    lease = ZeroTranslationLease(limits=InitiativeLimits(enabled=True))
    with pytest.raises(TranslationRefused):
        lease.admit(_proposal(InitiativeKind.GO_CHECK.value, budget_m=0.0), now_s=0.0)
    with pytest.raises(TranslationRefused):
        lease.admit(_proposal(InitiativeKind.LOOK.value, budget_m=0.4), now_s=0.0)


def test_no_drive_source_can_claim_motion_authority_at_all() -> None:
    """The third guard, in a module this card does not touch: the arbiter."""

    assert "drive" not in SOURCE_PRIORITIES
    assert "initiative" not in SOURCE_PRIORITIES
    for name in ("drive", "initiative", "curiosity"):
        with pytest.raises(ValueError, match="source"):
            MotionIntent(command=VelocityCommand(vx=0.2), source=name)


# ==========================================================================
# 4 — the initiation-rate envelope
# ==========================================================================


def test_initiative_ships_off_and_says_so() -> None:
    lane = install_body_lane()
    assert lane is not None
    assert lane.lease.limits.enabled is False
    verdict = lane.lease.may_admit(0.0)
    assert (verdict.admitted, verdict.code) == (False, REFUSE_DISABLED)


def test_the_envelope_default_is_the_measured_one() -> None:
    limits = InitiativeLimits()
    assert limits.max_per_hour == float(max(H3_MEASURED_INITIATIONS))
    assert 3.0 <= limits.max_per_hour <= 8.0  # H3's pre-registered D1 band
    assert limits.refractory_s == 120.0
    assert limits.window_s == 3600.0


def test_the_envelope_refuses_the_seventh_initiation_in_an_hour() -> None:
    """SEEDED RED past the bar: the seventh ask in the window is refused."""

    lease = ZeroTranslationLease(limits=InitiativeLimits(enabled=True))
    admitted = 0
    for i in range(10):
        now = i * 300.0  # 5 minutes apart: the refractory floor is clear
        verdict = lease.admit(_proposal(), now_s=now)
        if verdict.admitted:
            admitted += 1
            lease.withdraw(now + 1.0)
        else:
            assert verdict.code == REFUSE_RATE
    assert admitted == 6
    assert lease.initiations_in_window(9 * 300.0) == 6

    # The window slides: an hour after the first, there is room again.
    later = 3600.0 + 300.0
    assert lease.admit(_proposal(), now_s=later).admitted


def test_the_refractory_floor_refuses_a_second_ask_too_soon() -> None:
    lease = ZeroTranslationLease(limits=InitiativeLimits(enabled=True))
    assert lease.admit(_proposal(), now_s=0.0).admitted
    lease.withdraw(1.0)
    early = lease.admit(_proposal(), now_s=30.0)
    assert (early.admitted, early.code) == (False, REFUSE_REFRACTORY)
    assert lease.admit(_proposal(), now_s=130.0).admitted


def test_the_quiet_door_is_injected_and_not_reimplemented() -> None:
    """The product's own quiet-window/night-band authority stays the authority."""

    lease = ZeroTranslationLease(
        limits=InitiativeLimits(enabled=True), quiet=lambda _now: False
    )
    verdict = lease.admit(_proposal(), now_s=0.0)
    assert (verdict.admitted, verdict.code) == (False, REFUSE_QUIET)

    code = _code("attention/initiative.py").split()
    for forbidden in ("quiet_hours", "TIME_BAND", "ChatterScheduler"):
        assert forbidden not in code, forbidden


# ==========================================================================
# 5 — the 0-tick yield and the terminal
# ==========================================================================


def test_an_owner_command_preempts_the_behaviour_in_the_very_same_tick() -> None:
    """H3 D5 as a product row: the yield is 0 ticks, not 1."""

    lane = _lane(enabled=True)
    assert lane.begin(_proposal(), now_s=0.0).admitted
    running = lane.tick(
        offsets=ExpressiveOffsets(), finalized_velocity=None, now_s=TICK_S
    )
    assert running.offer.behavior == BEHAVIOR_LOOK
    assert running.intent.gaze != (0.0, 0.0)

    yielded = lane.tick(
        offsets=ExpressiveOffsets(),
        finalized_velocity=VelocityCommand(vx=0.3),
        owner_active=True,
        now_s=2 * TICK_S,
    )
    assert yielded.yielded
    assert yielded.offer is NEUTRAL_OFFER
    assert yielded.terminal is not None
    assert yielded.terminal.reason == END_OWNER_COMMAND
    assert yielded.terminal.kind == TERMINAL_RELEASE_AUTHORITY
    assert not lane.lease.running
    assert lane.yields == 1
    # The owner's command is what the body publishes on that same tick.
    assert yielded.intent.locomotion.as_tuple() == (0.3, 0.0, 0.0)


def test_every_terminal_is_a_safe_hold_and_none_is_a_return() -> None:
    """The ratified amendment: stop-and-return measured WORSE and is not built."""

    lane = _lane(enabled=True, max_behavior_s=0.2, refractory_s=0.0)
    now = 0.0
    for round_index in range(5):
        assert lane.begin(_proposal(), now_s=now).admitted
        for _ in range(20):
            now += TICK_S
            tick = lane.tick(
                offsets=ExpressiveOffsets(),
                finalized_velocity=None,
                owner_active=round_index == 4 and not lane.lease.running,
                now_s=now,
            )
            if tick.terminal is not None:
                break
        assert not lane.lease.running

    assert lane.lease.terminals
    for terminal in lane.lease.terminals:
        assert terminal.kind in M1_REACHABLE_TERMINALS
        assert terminal.returned is False
        assert terminal.reason in {END_COMPLETED, END_OWNER_COMMAND, END_EMERGENCY_STOP}
    assert {t.kind for t in lane.lease.terminals} <= TERMINAL_KINDS


def test_a_return_terminal_cannot_be_constructed_at_all() -> None:
    with pytest.raises(ValueError, match="cannot return"):
        Terminal(kind=TERMINAL_RETURN, reason=END_COMPLETED, at_s=0.0, returned=True)


def test_a_completed_leg_ends_holding_and_emits_no_trajectory() -> None:
    lane = _lane(enabled=True, max_behavior_s=0.1)
    assert lane.begin(_proposal(), now_s=0.0).admitted
    now = 0.0
    terminal = None
    while terminal is None and now < 1.0:
        now += TICK_S
        tick = lane.tick(offsets=ExpressiveOffsets(), finalized_velocity=None, now_s=now)
        terminal = tick.terminal
    assert terminal is not None
    assert terminal.kind == TERMINAL_HOLD
    assert terminal.reason == END_COMPLETED
    # Nothing the leg did produced a velocity: every tick of it was a HOLD.
    assert lane.hold_ticks == lane.ticks
    code = _code("attention/initiative.py").split()
    for forbidden in ("goal", "waypoint", "navigate", "return_to", "plan"):
        assert forbidden not in code, forbidden


def test_the_four_non_travelling_behaviours_reach_the_body() -> None:
    """Look, orient, stretch, remark — the whole M1 repertoire, and no more."""

    lane = _lane(enabled=True, refractory_s=0.0)
    now = 0.0

    def run(proposal: InitiativeProposal, **admit: Any) -> tuple[Any, Any]:
        nonlocal now
        assert lane.begin(proposal, now_s=now, **admit).admitted
        now += TICK_S
        tick = lane.tick(offsets=ExpressiveOffsets(), finalized_velocity=None, now_s=now)
        lane.lease.withdraw(now)
        return tick.offer, tick.intent

    looking, look_intent = run(_proposal(bearing_rad=0.6))
    assert looking.behavior == BEHAVIOR_LOOK
    assert look_intent.gaze[0] > 0.0

    # No measured bearing -> the dog lifts its head instead of inventing one.
    orienting, _ = run(_proposal(bearing_rad=None))
    assert orienting.behavior == BEHAVIOR_ORIENT
    assert orienting.gaze is None

    stretching, stretch_intent = run(_proposal(InitiativeKind.REST.value, bearing_rad=None))
    assert stretching.behavior == BEHAVIOR_STRETCH
    assert stretch_intent.posture[0] > 0.0

    spoken, _ = run(
        _proposal(InitiativeKind.REMARK.value), line=open_line(None, seed=1).line
    )
    assert spoken.behavior == BEHAVIOR_REMARK
    assert spoken.line in LOCAL_OPENERS

    assert {t.kind for t in lane.lease.terminals} <= M1_REACHABLE_TERMINALS


def test_the_offer_bounds_are_the_lease_asking_inside_the_envelope() -> None:
    """An out-of-band offer is a bug here, not a clamp in the composer."""

    with pytest.raises(ValueError, match="gaze exceeds"):
        BodyOffer(behavior=BEHAVIOR_LOOK, gaze=(3.0, 0.0))
    with pytest.raises(ValueError, match="posture exceeds"):
        BodyOffer(behavior=BEHAVIOR_STRETCH, posture=(1.0, 0.0))
    # And a bearing from the digest is clamped INTO the bound, never refused.
    lease = ZeroTranslationLease(limits=InitiativeLimits(enabled=True))
    assert lease.admit(_proposal(bearing_rad=3.0), now_s=0.0).admitted


# ==========================================================================
# 6 — composition with A6, A7, A8
# ==========================================================================


def test_the_stop_latch_terminates_any_running_behaviour(tmp_path: Path) -> None:
    """A6: one latch, the arbiter's, and the drive dies on it in the same tick."""

    lane = _lane(enabled=True)
    assert lane.begin(_proposal(), now_s=0.0).admitted
    stopped = lane.tick(
        offsets=ExpressiveOffsets(),
        finalized_velocity=VelocityCommand(vx=0.2),
        emergency=True,
        now_s=TICK_S,
    )
    assert stopped.terminal is not None
    assert stopped.terminal.reason == END_EMERGENCY_STOP
    assert stopped.terminal.kind == TERMINAL_RELEASE_AUTHORITY
    assert stopped.intent.locomotion is HOLD
    assert stopped.intent.priority == 100
    assert not lane.lease.running

    # And the flag the runtime reads is the panel's own latch, not a copy.
    arbiter = CommandArbiter(SafetyLimits())
    arbiter.engage_emergency_stop()
    assert arbiter.emergency_stopped is True
    assert "emergency=self.arbiter.emergency_stopped" in _function_source(
        "runtime.py", "_step_expression"
    )


def test_a_drive_never_takes_motion_authority_away_from_follow() -> None:
    """A8: follow keeps its lease; the drive is the one that yields."""

    arbiter = CommandArbiter(SafetyLimits())
    accepted = arbiter.submit(
        MotionIntent(command=VelocityCommand(vx=0.25), source="follow", ttl=10.0),
        now=0.0,
    )
    assert accepted.accepted

    lane = _lane(enabled=True)
    assert lane.begin(_proposal(), now_s=0.0).admitted
    tick = lane.tick(
        offsets=ExpressiveOffsets(),
        finalized_velocity=VelocityCommand(vx=0.25),
        owner_active=arbiter.current(1.0) is not None,
        now_s=TICK_S,
    )
    assert tick.terminal is not None  # the drive yielded, inside the tick
    active = arbiter.current(1.0)
    assert active is not None and active.source == "follow"
    assert SOURCE_PRIORITIES["follow"] == 40


class _Total:
    def __init__(self, usd: float, *, readable: bool = True, month: str = "2026-08") -> None:
        self.usd = usd
        self.readable = readable
        self.month = month


class _SpyGovernor:
    def __init__(self, inner: HostedCallGovernor) -> None:
        self.inner = inner
        self.calls: list[tuple[str, str]] = []

    def admit(self, purpose: str, *, call_class: str = CLASS_ROUTINE):
        self.calls.append((purpose, call_class))
        return self.inner.admit(purpose, call_class=call_class)


def test_a_drive_opener_asks_the_governor_and_degrades_to_a_local_line() -> None:
    """A7: over the envelope, the dog still speaks — with its own words. $0."""

    over = _SpyGovernor(
        HostedCallGovernor(
            config=GovernorConfig(envelope_usd=160.0, reserve_usd=40.0),
            month_to_date=lambda: _Total(160.01),
        )
    )
    refused = open_line(over, seed=2)
    assert refused.hosted is False
    assert refused.code == OPENER_LOCAL_REFUSED
    assert refused.line in LOCAL_OPENERS
    assert refused.reason
    assert over.calls == [(OPENER_PURPOSE, CLASS_ROUTINE)]
    assert CLASS_CRITICAL not in {call_class for _, call_class in over.calls}

    under = _SpyGovernor(
        HostedCallGovernor(
            config=GovernorConfig(envelope_usd=160.0, reserve_usd=40.0),
            month_to_date=lambda: _Total(1.25),
        )
    )
    admitted = open_line(under, seed=2)
    assert admitted.hosted is True
    assert admitted.code == OPENER_HOSTED_ADMITTED
    assert admitted.line == refused.line  # the local floor is always ready

    # A build with no governor is not a build with an unlimited budget.
    assert open_line(None).code == OPENER_LOCAL_NO_GOVERNOR
    assert open_line(None).hosted is False


def test_this_card_opens_no_socket_of_its_own() -> None:
    for module in ("attention/initiative.py", "motion/body_lane.py"):
        code = _code(module).split()
        for forbidden in ("urllib", "requests", "http", "socket", "openai"):
            assert forbidden not in code, f"{module}: {forbidden}"


def test_the_opener_bank_is_deterministic_and_local() -> None:
    assert len(set(LOCAL_OPENERS)) == len(LOCAL_OPENERS)
    assert all(line.strip() for line in LOCAL_OPENERS)
    assert open_line(None, seed=7).line == open_line(None, seed=7).line


# ==========================================================================
# 7 — the product path: a real runtime publishes body intent
# ==========================================================================


class _Backend:
    name = "a9-life"

    def __init__(self) -> None:
        self.emergencies = 0
        self.stops = 0
        self.expressions = 0

    def observe(self) -> SimObservation:
        return SimObservation(
            timestamp=0.0,
            robot=RobotPose(),
            owner=OwnerTrack(),
            nearest_obstacle_m=10.0,
            backend=self.name,
        )

    def move(self, command: VelocityCommand) -> None:
        del command

    def stop(self) -> None:
        self.stops += 1

    def emergency_stop(self) -> None:
        self.emergencies += 1

    def expression(self, offsets: dict) -> None:
        del offsets
        self.expressions += 1

    def pose(self, pose: object) -> None:
        del pose

    def trajectory(self, skill: object) -> None:
        del skill

    def move_owner(self, dx: float, dy: float) -> None:
        del dx, dy


class _SilentModel:
    def decide(self, transcript, tools, context) -> AgentDecision:
        del transcript, tools, context
        return AgentDecision("Understood.")


@pytest.fixture()
def runtime(tmp_path: Path):
    path = tmp_path / "a9.yaml"
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
agent:
  prompts_root: {REPO / "prompts"}
memory:
  path: ":memory:"
speech:
  mode: auto
  stt_provider: none
  tts_provider: none
poses: {{}}
modules: []
""",
        encoding="utf-8",
    )
    instance = RobotRuntime(
        path,
        _Backend(),
        language_model=_SilentModel(),
        audio_status=AudioDeviceStatus(
            status="text mode",
            driver="test",
            capture_hardware=False,
            connected_input=False,
            connected_output=False,
            detail="a9 life fixture",
        ),
    )
    try:
        yield instance
    finally:
        instance.close()


def test_the_runtime_publishes_a_body_intent_and_holds_by_default(runtime) -> None:
    """The wiring H4's verdict said did not exist. Inert: it drives nothing."""

    assert runtime._body_lane is not None
    assert runtime._body_lane.latest is None
    runtime._step_expression()
    intent = runtime._body_lane.latest
    assert intent is not None
    assert intent.is_hold  # a still dog COMMANDS stillness
    assert intent.source == "body_composer"
    assert runtime._body_lane.lease.limits.enabled is False


def test_the_runtimes_estop_reaches_the_published_intent(runtime) -> None:
    runtime._step_expression()
    assert runtime._body_lane.latest.priority == 0

    runtime.emergency_stop()
    runtime._step_expression()
    intent = runtime._body_lane.latest
    assert intent.is_hold
    assert intent.priority == 100
    assert runtime.arbiter.emergency_stopped is True


def test_a_broken_lane_cannot_take_the_expression_overlay_down(runtime) -> None:
    """The lane rides the decorative channel and must never break it."""

    class _Exploding:
        latest = None

        def tick(self, **kwargs: Any) -> None:
            raise RuntimeError("boom")

    runtime._body_lane = _Exploding()
    runtime._step_expression()  # must not raise
    assert runtime.backend.expressions >= 0
