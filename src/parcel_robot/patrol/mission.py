"""The patrol policy, its sensing adapter, and the mission runner.

Split deliberately into a **pure policy** and a **thin driver** so the
behaviour that matters — "do not command a heading the safety gate will
refuse" — is decidable in a unit test with no simulator, no socket and no
clock, and the driver contains only I/O.

Nothing here re-implements or weakens a safety gate. The policy is a
*proposer* that keeps the body out of situations the reactive gate would have
to veto; the gate remains the unconditional last line of defence and is
untouched. A patrol that ignores this simply burns its budget on refused
commands, which is precisely what E2-D2 measured.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

# E2-D3, the T1 detector query vocabulary. No sidecar by design: this list is
# carried by the runner, never read from ``scenes/`` truth or a scene digest.
# Place-like, non-volatile nouns only — C-2's hygiene gate refuses people and
# other volatile classes, and a patrol that spends its detector budget
# proposing them learns nothing it is allowed to keep.
DEFAULT_MAP_SWEEP_VOCABULARY: tuple[str, ...] = (
    "building",
    "storefront",
    "door",
    "window",
    "lamppost",
    "bench",
    "tree",
    "planter",
    "bollard",
    "traffic sign",
    "bicycle rack",
    "trash can",
)

#: The detector query the camera channel REQUIRES, for safety rather than for
#: mapping. ``CameraStreamConfig.from_section`` refuses a batch without the
#: whole word "person": a camera that never asks about people must not claim
#: the person-relevant admission path (PG-1's safety lease). Measured by
#: running it, card MOVE-1.
SAFETY_LEASE_QUERY = "person"

#: Body-forward half-angle of the lane the patrol treats as "ahead". Matches
#: the reactive gate's own ``_toward`` half-angle so the clearance the policy
#: reads is the clearance the gate will judge.
FORWARD_HALF_ANGLE_RAD = 1.15


def ingress_queries(limit: int = 8) -> tuple[str, ...]:
    """The detector batch to hand the camera channel, safety query first.

    E2-D3's answer in one function: the **query** vocabulary and the **map**
    vocabulary are different sets, and conflating them is a safety bug in one
    direction and a hygiene bug in the other.

    * ``person`` must be asked, or the camera channel refuses to start.
    * ``person`` must never become a place — C-2's hygiene gate refuses
      volatile classes, and the patrol relies on that refusal rather than on
      not asking.
    """

    if limit < 1:
        raise ValueError("ingress_queries limit must be at least 1")
    sweep = DEFAULT_MAP_SWEEP_VOCABULARY[: max(0, limit - 1)]
    return (SAFETY_LEASE_QUERY, *sweep)


@dataclass(frozen=True)
class PatrolSense:
    """Everything the policy is allowed to see. One control tick's worth."""

    elapsed_s: float
    x: float
    y: float
    yaw: float
    forward_clearance_m: float | None = None
    person_clearance_m: float | None = None
    #: Bearing to the nearest person, in the BODY frame (0 = dead ahead).
    #: ``None`` means the bearing is unknown, which fails closed: an
    #: unlocated person blocks translation exactly like one dead ahead.
    person_bearing_rad: float | None = None
    collision: bool = False
    # ---- CARD ROAM-2: the coverage objective, and it is OPTIONAL ---------
    #: Bearing to the LEAST RECENTLY SEEN place the learned map knows about,
    #: in the BODY frame, exactly like :attr:`person_bearing_rad`. ``None``
    #: means "the map has nothing to send me at" — no map, no entries, every
    #: known place already in view — and it FAILS OPEN, which is the opposite
    #: of the person bearing and is deliberate: an absent coverage objective
    #: degrades to ROAM-1's wander, never to a stop. A stopped dog is the one
    #: failure mode a companion behaviour must not have.
    coverage_bearing_rad: float | None = None
    #: How long ago that place was last seen, seconds. ``None`` means the age
    #: is UNKNOWN (no clock, a reloaded map from another host, a stepped wall
    #: clock) and is treated as no objective at all — never as zero, which
    #: would read as "just seen" and would hide the place worth visiting.
    coverage_age_s: float | None = None

    def __post_init__(self) -> None:
        for name in ("elapsed_s", "x", "y", "yaw"):
            value = getattr(self, name)
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise TypeError(f"PatrolSense.{name} must be a number")
            if not math.isfinite(float(value)):
                raise ValueError(f"PatrolSense.{name} must be finite")
        if self.person_bearing_rad is not None and not math.isfinite(
            float(self.person_bearing_rad)
        ):
            raise ValueError("PatrolSense.person_bearing_rad must be finite")
        # Card ROAM-2. Validated exactly like the person bearing: a NaN
        # objective would compare False against every threshold and silently
        # mean "no coverage" instead of saying so.
        if self.coverage_bearing_rad is not None and not math.isfinite(
            float(self.coverage_bearing_rad)
        ):
            raise ValueError("PatrolSense.coverage_bearing_rad must be finite")
        if self.coverage_age_s is not None:
            age = float(self.coverage_age_s)
            if not math.isfinite(age) or age < 0.0:
                raise ValueError("PatrolSense.coverage_age_s must be finite and >= 0")
        for name in ("forward_clearance_m", "person_clearance_m"):
            value = getattr(self, name)
            if value is None:
                continue
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise TypeError(f"PatrolSense.{name} must be a number or None")
            if not math.isfinite(float(value)) or float(value) < 0.0:
                raise ValueError(f"PatrolSense.{name} must be finite and non-negative")


@dataclass(frozen=True)
class PatrolCommand:
    """A proposal, with the reason it was proposed. The reason is evidence."""

    vx: float = 0.0
    vy: float = 0.0
    vyaw: float = 0.0
    reason: str = "idle"

    @property
    def translating(self) -> bool:
        return math.hypot(self.vx, self.vy) > 1e-9


@dataclass(frozen=True)
class PatrolLimits:
    """Bounds. Every one of these is a refusal threshold, not a target."""

    budget_s: float = 120.0
    cruise_vx: float = 0.25
    turn_vyaw: float = 0.8
    #: Do not drive into a lane shorter than this. The reactive gate stops
    #: translation at ``obstacle_stop_m`` (0.65 m) and starts scaling it at
    #: ``obstacle_slow_m`` (1.2 m); commanding into anything under this
    #: threshold buys refused ticks, not distance.
    min_forward_clearance_m: float = 1.5
    #: Person standoff. The gate's ``person_stop_m`` is 1.2 m and the owner
    #: carries a further 0.55 m collision envelope; this is the *clearance*
    #: (already envelope-adjusted) below which the patrol turns away rather
    #: than be refused. E2-D2's exact failure.
    min_person_clearance_m: float = 1.35
    #: Hysteresis: once turning, keep turning until the lane is this much
    #: better than the threshold, so the patrol cannot chatter on the boundary.
    clearance_release_margin_m: float = 0.35
    #: A turn that has not found a lane in this long flips direction.
    turn_flip_after_s: float = 4.0
    #: Cap on one continuous turn, so a boxed-in patrol still ends.
    turn_giveup_after_s: float = 12.0
    #: Card ROAM-1, and it is the difference between wandering and circling.
    #:
    #: MEASURED, on the product path, three consecutive 120 s runs in
    #: ``--static-city``: 21.85 m of path and **0.14 m of net displacement**,
    #: with a total heading change of 1404 degrees — 3.90 full turns, every one
    #: of them the same way. ``_turn`` uses a sign that only ever flips
    #: mid-turn (``turn_flip_after_s``), so a patrol that clears each blocked
    #: lane by turning left traces a closed polygon and comes home. It was
    #: never exploring; it was doing donuts inside a 1.8 x 2.2 m box.
    #:
    #: With this on, the sign flips when a turn RELEASES, so consecutive
    #: avoidance turns alternate and the path opens out instead of closing.
    #:
    #: DEFAULT OFF. MOVE-1's policy is a measured artifact and its numbers are
    #: the baseline the Go2 decision is read against; changing what
    #: ``PatrolPolicy()`` does by default would silently move that baseline.
    #: :func:`limits_from_safety` — which only the roam behavior calls — turns
    #: it on.
    alternate_turns: bool = False
    #: Card ROAM-1, added under verification — HOW FAR FROM HOME IS STILL A
    #: WANDER. ``None`` means unbounded, which is what the shipped policy has
    #: always been.
    #:
    #: MEASURED, and it is why this exists. The third run of the corrected
    #: arm reported 20.674462 m of net displacement, and the verifier read the
    #: trace: the robot left the 24 x 24 m road plane at t = 85 s and spent
    #: 138 of 479 samples driving straight at -84.6 degrees across the
    #: unfenced infinite ground plane. 8.66 m of that "net displacement"
    #: accrued off the rendered map. The number was true and it was not the
    #: number anyone wanted — a dog told to go explore had left the block and
    #: was still going.
    #:
    #: A tether is not a safety device and must never be read as one; the
    #: reactive gate is untouched and is still the only thing that refuses.
    #: This is a PROPOSER bound: past it the patrol treats "away from home" the
    #: way it treats a wall, and turns.
    #:
    #: DEFAULT ``None`` so MOVE-1's baseline policy is byte-identical.
    #: :func:`limits_from_safety` sets it.
    tether_m: float | None = None

    # ---- CARD ROAM-2 — WANDERING IS NOT EXPLORING ------------------------
    #
    # ROAM-1's own closing sentence: "It does not prove the dog explores. It
    # proves the dog WANDERS under a budget without hitting anything. There is
    # no coverage objective, no frontier, no memory of where it has been."
    # This is the objective, and it is one bearing.
    #
    # DEFAULT OFF, for the same reason ``alternate_turns`` and ``tether_m``
    # are: MOVE-1's and ROAM-1's measured numbers are the baselines a Go2
    # purchase is read against, and a default that moved them would move the
    # baseline silently. And OFF ALL THE WAY DOWN — :func:`limits_from_safety`
    # defaults it off too, so the objective is on only where a profile says
    # ``roam: {coverage: true}`` in words. Flag-off, this class is byte-for-byte
    # the ROAM-1 policy: :meth:`PatrolPolicy._cruise_or_cover` returns
    # ``PatrolCommand(vx=cruise_vx, reason="advance")`` on its first branch.
    coverage_bias: bool = False
    #: How close to dead ahead the objective must be before the patrol simply
    #: cruises at it. Wider than a heading controller would want on purpose:
    #: this is a proposer nudging a wander, not a tracker closing an error, and
    #: a tight tolerance would turn every lane deviation into a correction
    #: turn. 0.35 rad = 20 degrees.
    coverage_align_tolerance_rad: float = 0.35
    #: A place seen more recently than this is not a coverage objective. The
    #: map refreshes ``last_seen_wall_s`` the instant the detector fires, so
    #: without a floor the objective would flicker between two places the robot
    #: is already looking at.
    coverage_min_age_s: float = 20.0
    #: A coverage alignment that has not converged in this long gives up and
    #: cruises. NOT a safety bound — the gate is untouched — it is the same
    #: promise ``turn_giveup_after_s`` makes for avoidance turns: the objective
    #: may never spend the whole budget turning on the spot.
    coverage_giveup_after_s: float = 6.0

    def __post_init__(self) -> None:
        positive = (
            "budget_s",
            "cruise_vx",
            "turn_vyaw",
            "min_forward_clearance_m",
            "min_person_clearance_m",
            "turn_flip_after_s",
            "turn_giveup_after_s",
            # Card ROAM-2. Both are refusal thresholds like every other field
            # here, and both are validated whether or not the objective is on:
            # a nonsense number must be refused at construction, not on the
            # first tick after somebody flips the flag.
            "coverage_align_tolerance_rad",
            "coverage_giveup_after_s",
        )
        for name in positive:
            value = getattr(self, name)
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise TypeError(f"PatrolLimits.{name} must be a number")
            if not math.isfinite(float(value)) or float(value) <= 0.0:
                raise ValueError(f"PatrolLimits.{name} must be positive and finite")
        if not math.isfinite(self.clearance_release_margin_m) or self.clearance_release_margin_m < 0.0:
            raise ValueError("PatrolLimits.clearance_release_margin_m must be >= 0")
        # Card ROAM-2. Zero is a legitimate floor ("any age counts"), so this
        # one is >= 0 rather than > 0.
        if not math.isfinite(self.coverage_min_age_s) or self.coverage_min_age_s < 0.0:
            raise ValueError("PatrolLimits.coverage_min_age_s must be >= 0")
        # Card ROAM-1. ``None`` is unbounded; a number must be a real radius.
        if self.tether_m is not None:
            if not isinstance(self.tether_m, (int, float)) or isinstance(self.tether_m, bool):
                raise TypeError("PatrolLimits.tether_m must be a number or None")
            if not math.isfinite(float(self.tether_m)) or float(self.tether_m) <= 0.0:
                raise ValueError("PatrolLimits.tether_m must be positive and finite")
        if self.turn_flip_after_s > self.turn_giveup_after_s:
            raise ValueError("turn_flip_after_s must not exceed turn_giveup_after_s")


# ===================== CARD ROAM-1 — patrol becomes a product behavior ======
#
# MOVE-1 ran this package from a harness with the SHIPPED defaults above, and
# those defaults were written against the SHIPPED reactive gate
# (``person_stop_m`` 1.2 m, ``obstacle_stop_m`` 0.65 m). P1-E then made the
# person zone a config: ``configs/robot.prototype.yaml`` commissions
# ``safety.person_stop_m: 0.7`` and the runtime boots on it. A patrol that
# keeps a 1.35 m standoff on a robot whose gate only refuses inside 0.7 m is
# not being safe — it is turning away from lanes the gate would have allowed,
# which is the same budget-burning failure E2-D2 measured from the other side.
#
# So the roam behavior DERIVES its two clearance thresholds from the gate's own
# numbers instead of carrying a second copy of them. Nothing here relaxes a
# gate: these are *proposer* thresholds that sit strictly OUTSIDE the gate's
# refusal radius, and the gate remains the unconditional last line.

#: How far outside the gate's person stop the proposer keeps itself. 0.15 m is
#: the margin the shipped defaults already encode (1.35 = 1.2 + 0.15) — carried
#: forward as a named constant rather than re-derived, so the prototype profile
#: reproduces the shipped ratio instead of inventing a new one.
PERSON_CLEARANCE_MARGIN_M = 0.15

#: The same relationship for the obstacle lane: the shipped default 1.5 m sits
#: 0.85 m outside the 0.65 m ``obstacle_stop_m``.
FORWARD_CLEARANCE_MARGIN_M = 0.85

#: How far from home a roam may wander when nobody configures it. One number,
#: read by :func:`limits_from_safety`, by ``RobotRuntime._roam_limits`` and
#: documented in ``configs/robot.prototype.yaml`` — three readers, one
#: definition. 10 m is comfortably inside the dev scene's 24 x 24 m road plane,
#: which is the boundary the untethered run walked off.
DEFAULT_ROAM_TETHER_M = 10.0


def limits_from_safety(
    *,
    person_stop_m: float,
    obstacle_stop_m: float,
    budget_s: float = 120.0,
    cruise_vx: float = 0.25,
    turn_vyaw: float = 0.8,
    alternate_turns: bool = True,
    tether_m: float | None = DEFAULT_ROAM_TETHER_M,
    coverage_bias: bool = False,
) -> PatrolLimits:
    """Build :class:`PatrolLimits` from the reactive gate's own thresholds.

    Pure and unit-testable with no runtime: given the two distances the gate
    will actually refuse at, it returns the proposer thresholds that sit one
    named margin outside them. Feeding it the SHIPPED numbers
    (``person_stop_m=1.2``, ``obstacle_stop_m=0.65``) reproduces the shipped
    defaults exactly, which is the property the card's test pins.
    """

    for name, value in (
        ("person_stop_m", person_stop_m),
        ("obstacle_stop_m", obstacle_stop_m),
    ):
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise TypeError(f"limits_from_safety {name} must be a number")
        if not math.isfinite(float(value)) or float(value) <= 0.0:
            raise ValueError(f"limits_from_safety {name} must be positive and finite")
    return PatrolLimits(
        budget_s=float(budget_s),
        cruise_vx=float(cruise_vx),
        turn_vyaw=float(turn_vyaw),
        min_forward_clearance_m=float(obstacle_stop_m) + FORWARD_CLEARANCE_MARGIN_M,
        min_person_clearance_m=float(person_stop_m) + PERSON_CLEARANCE_MARGIN_M,
        alternate_turns=bool(alternate_turns),
        # Card ROAM-1, under verification. 10 m is a bounded wander around
        # home, which is what "go explore" means for a companion — and it is
        # comfortably inside the 24 x 24 m road plane the dev scene renders, so
        # a roam cannot walk off the edge of the world and call it progress.
        tether_m=tether_m,
        # Card ROAM-2, CORRECTED at the third attempt. OFF here as well as on
        # ``PatrolLimits`` itself.
        #
        # The 17:38 draft defaulted this argument to ``True`` on the reasoning
        # that this function is the roam behaviour's only constructor, so
        # "prototype explores, package untouched" could be said in one place.
        # That reasoning is real and it is still WRONG against the wave's
        # standing rule (``../TASK_BOARD.md`` rule 1, the dispatch brief's
        # "defaults OFF for behaviour"): a default that turns a behaviour on is
        # a behaviour nobody wrote down. With this ``False``, the ONLY thing in
        # the tree that can turn the coverage objective on is an explicit
        # ``roam: {coverage: true}`` in a profile — which is also what makes
        # ROAM-2's two measurement arms differ by exactly one config line
        # (``../../scrum/20260822/task_33/PREREGISTRATION.md`` §2) instead of
        # by a code default nobody can see from the config.
        coverage_bias=bool(coverage_bias),
    )


# ===================== END CARD ROAM-1 region ==============================


class PatrolPolicy:
    """Pure decision function plus its own small, explicit state.

    Ordering is a priority ladder and is part of the contract: budget, then
    contact, then people, then geometry, then hysteresis, then cruise.
    """

    def __init__(self, limits: PatrolLimits | None = None, *, turn_sign: int = 1) -> None:
        self.limits = limits or PatrolLimits()
        if turn_sign not in (-1, 1):
            raise ValueError("turn_sign must be -1 or 1")
        self._turn_sign = turn_sign
        self._turning_since: float | None = None
        #: Card ROAM-1. Where the roam STARTED, latched on the first sense and
        #: never moved. The policy has no other notion of home and deliberately
        #: does not get one from a map: a tether that depended on localisation
        #: would fail in exactly the situation it exists for.
        self._home: tuple[float, float] | None = None
        #: Card ROAM-2. ``elapsed_s`` at which the current coverage ALIGNMENT
        #: began, or ``None`` when the patrol is not aligning. Deliberately a
        #: second clock rather than a reuse of ``_turning_since``: an avoidance
        #: turn that runs long is ``boxed_in`` and ends the mission, and a
        #: coverage turn that runs long is merely a bad objective — conflating
        #: them would let the map end a roam.
        self._coverage_since: float | None = None
        #: ``elapsed_s`` before which no coverage objective is adopted, after an
        #: alignment gave up. Without the cool-off, giving up and immediately
        #: re-adopting the same unreachable bearing is a patrol that turns for
        #: six seconds, walks for one tick, and turns again.
        self._coverage_hold_until: float | None = None
        #: Completed coverage legs — an alignment that converged and became a
        #: cruise. Published so "remarks per leg" is a countable thing. A tick
        #: that was ALREADY pointing at the objective needed no alignment and
        #: is not a leg: the count is deliberately the conservative one.
        self._coverage_legs = 0

    @property
    def turning_since(self) -> float | None:
        return self._turning_since

    @property
    def turn_sign(self) -> int:
        return self._turn_sign

    @property
    def coverage_legs(self) -> int:
        """Card ROAM-2. How many coverage legs this policy has completed."""

        return self._coverage_legs

    @property
    def coverage_aligning(self) -> bool:
        """Card ROAM-2. Is the patrol turning onto a coverage objective now?"""

        return self._coverage_since is not None

    @staticmethod
    def _person_blocks(sense: PatrolSense, threshold_m: float) -> bool:
        """Does the person stand between the patrol and where it wants to go?

        Distance alone is the wrong question, and asking it is what deadlocked
        the first live patrol (``patrol_city_block_20260822T034036Z``): a robot
        turning in place never changes its distance to a stationary owner, so a
        distance-only standoff can never release and the patrol spins out its
        whole budget. The product's own reactive gate asks about the travel
        DIRECTION (``reactive_safety._toward``); so does this.
        """

        clearance = sense.person_clearance_m
        if clearance is None or clearance >= threshold_m:
            return False
        bearing = sense.person_bearing_rad
        if bearing is None:
            return True  # unknown bearing fails closed
        wrapped = math.atan2(math.sin(bearing), math.cos(bearing))
        return abs(wrapped) < FORWARD_HALF_ANGLE_RAD

    def _tether_blocks(self, sense: PatrolSense, radius_m: float | None) -> bool:
        """Is the patrol outside its tether AND still heading away from home?

        Card ROAM-1. Distance alone is the wrong question here for the SAME
        reason it was the wrong question for people (see :meth:`_person_blocks`
        and the live patrol it deadlocked): a robot turning in place never
        changes its distance to home, so a distance-only tether can never
        release and the patrol spins out its whole budget on the boundary. So
        this asks about the travel DIRECTION — the tether blocks only while
        home is BEHIND the body, and clears the moment the nose comes round.
        """

        if radius_m is None or self._home is None:
            return False
        dx = self._home[0] - sense.x
        dy = self._home[1] - sense.y
        if math.hypot(dx, dy) < radius_m:
            return False
        # Bearing to home in the BODY frame; 0 means home is dead ahead.
        bearing = math.atan2(dy, dx) - sense.yaw
        wrapped = math.atan2(math.sin(bearing), math.cos(bearing))
        return abs(wrapped) >= FORWARD_HALF_ANGLE_RAD

    def _turn(self, sense: PatrolSense, reason: str) -> PatrolCommand:
        limits = self.limits
        if self._turning_since is None:
            self._turning_since = sense.elapsed_s
        turning_for = sense.elapsed_s - self._turning_since
        if turning_for >= limits.turn_giveup_after_s:
            # Boxed in. Stop proposing; the runner ends the mission and the
            # report says why, rather than spinning out the whole budget.
            return PatrolCommand(reason="boxed_in")
        if turning_for >= limits.turn_flip_after_s:
            self._turn_sign = -self._turn_sign
            self._turning_since = sense.elapsed_s
        sign = self._turn_sign
        if reason == "turn_tether" and self._home is not None:
            # Card ROAM-1. Turn the SHORT way back toward home rather than
            # whichever way the counter happens to point — the other way takes
            # the long way round and spends the budget outside the tether.
            bearing = math.atan2(
                self._home[1] - sense.y, self._home[0] - sense.x
            ) - sense.yaw
            wrapped = math.atan2(math.sin(bearing), math.cos(bearing))
            if wrapped != 0.0:
                sign = 1 if wrapped > 0.0 else -1
        if reason == "turn_person" and sense.person_bearing_rad is not None:
            # Turn AWAY from the person rather than whichever way the counter
            # happens to point: a person to port is cleared by turning to
            # starboard, and the other way round takes the long way past them.
            bearing = math.atan2(
                math.sin(sense.person_bearing_rad), math.cos(sense.person_bearing_rad)
            )
            if bearing != 0.0:
                sign = -1 if bearing > 0.0 else 1
        return PatrolCommand(vyaw=limits.turn_vyaw * sign, reason=reason)

    def step(self, sense: PatrolSense) -> PatrolCommand:
        limits = self.limits
        # Card ROAM-1. Home is wherever the patrol was standing when it was
        # told to go. Latched before the budget check so a zero-budget policy
        # still has one, and never re-latched.
        if self._home is None:
            self._home = (sense.x, sense.y)
        if sense.elapsed_s >= limits.budget_s:
            self._turning_since = None
            return PatrolCommand(reason="budget_exhausted")
        if sense.collision:
            return self._turn(sense, "turn_contact")
        if self._person_blocks(sense, limits.min_person_clearance_m):
            return self._turn(sense, "turn_person")
        # Card ROAM-1. Below people (a person is always the more urgent
        # yield) and above geometry (a wall inside the tether is still a wall).
        if self._tether_blocks(sense, limits.tether_m):
            return self._turn(sense, "turn_tether")
        forward = sense.forward_clearance_m
        if forward is not None and forward < limits.min_forward_clearance_m:
            return self._turn(sense, "turn_blocked")
        if self._turning_since is not None:
            release = limits.min_forward_clearance_m + limits.clearance_release_margin_m
            person_release = limits.min_person_clearance_m + limits.clearance_release_margin_m
            forward_ok = forward is None or forward >= release
            person_ok = not self._person_blocks(sense, person_release)
            # Card ROAM-1. The tether releases on DIRECTION, so it needs no
            # radius margin: it clears as soon as the nose is pointing home,
            # which cannot chatter the way a distance boundary can.
            tether_ok = not self._tether_blocks(sense, limits.tether_m)
            if not (forward_ok and person_ok and tether_ok):
                return self._turn(sense, "turn_hold")
            self._turning_since = None
            # Card ROAM-1. THE RELEASE, which is the only moment a sign flip is
            # free: the lane ahead is clear, so nothing about this tick's
            # decision depends on which way the last one turned. Flipping
            # mid-turn (what ``turn_flip_after_s`` does) is a recovery from
            # being boxed in; flipping HERE is what stops eighteen consecutive
            # left turns from closing into a circle.
            if limits.alternate_turns:
                self._turn_sign = -self._turn_sign
        # ---- CARD ROAM-2. THE LAST RUNG, and it has to be the last one ----
        #
        # Everything above this line is a YIELD: contact, a person, the tether,
        # a wall, the hysteresis that stops the patrol chattering on any of
        # them. The coverage objective is the only rung that expresses a
        # PREFERENCE rather than a refusal, so it is the only one that may be
        # overruled by all the others, and putting it anywhere else in this
        # ladder would let a map argue with a wall.
        return self._cruise_or_cover(sense)

    def _cruise_or_cover(self, sense: PatrolSense) -> PatrolCommand:
        """Cruise — but toward the least recently seen place, when there is one.

        Card ROAM-2. Reached ONLY with the lane ahead clear, no person in the
        way and the tether satisfied, which is why it may turn without asking
        anything else: the tick has already established that turning here is
        free.

        THE DEGRADE PATH IS THE POINT. Four different kinds of "the map has
        nothing for me" — the objective is off, there is no bearing, the age is
        unknown, the place was seen a moment ago — and every one of them
        returns ROAM-1's ``advance``. There is no branch in this function that
        can return a stop, and ``test_a_stale_map_wanders_it_never_stops``
        exists to keep it that way.
        """

        limits = self.limits
        cruise = PatrolCommand(vx=limits.cruise_vx, reason="advance")
        if not limits.coverage_bias:
            return cruise
        bearing = sense.coverage_bearing_rad
        age = sense.coverage_age_s
        if bearing is None or age is None or age < limits.coverage_min_age_s:
            # A stale, empty or silent map is a wander, exactly as before.
            self._coverage_since = None
            return cruise
        if (
            self._coverage_hold_until is not None
            and sense.elapsed_s < self._coverage_hold_until
        ):
            # Cooling off after an alignment that could not converge.
            return cruise
        self._coverage_hold_until = None
        wrapped = math.atan2(math.sin(bearing), math.cos(bearing))
        if abs(wrapped) <= limits.coverage_align_tolerance_rad:
            if self._coverage_since is not None:
                # The leg's alignment converged: this is where a leg BEGINS to
                # be walked, and it is the idle checkpoint the patrol prompt
                # promises between legs (``RobotRuntime._step_roam`` publishes
                # it; CURIO-1's remarks ride it).
                self._coverage_since = None
                self._coverage_legs += 1
            return PatrolCommand(vx=limits.cruise_vx, reason="advance_coverage")
        if self._coverage_since is None:
            self._coverage_since = sense.elapsed_s
        elif sense.elapsed_s - self._coverage_since >= limits.coverage_giveup_after_s:
            # An objective that cannot be reached by turning — the map's
            # nearest unseen place is behind a building, the bearing keeps
            # moving — must not spend the budget on the spot. Give up on THIS
            # objective and walk; the cool-off keeps the next tick from
            # re-adopting the same bearing straight away.
            self._coverage_since = None
            self._coverage_hold_until = sense.elapsed_s + limits.coverage_giveup_after_s
            return cruise
        sign = 1 if wrapped > 0.0 else -1
        return PatrolCommand(vyaw=limits.turn_vyaw * sign, reason="turn_coverage")


@dataclass(frozen=True)
class PathSample:
    t_s: float
    x: float
    y: float
    yaw: float
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "t_s": round(self.t_s, 4),
            "x": round(self.x, 6),
            "y": round(self.y, 6),
            "yaw": round(self.yaw, 6),
            "reason": self.reason,
        }


@dataclass(frozen=True)
class MapGrowthSample:
    t_s: float
    entries: int
    labels: tuple[str, ...]
    frames_seen: int
    detections_seen: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "t_s": round(self.t_s, 4),
            "entries": self.entries,
            "labels": list(self.labels),
            "frames_seen": self.frames_seen,
            "detections_seen": self.detections_seen,
        }


@dataclass
class PatrolReport:
    scene: str
    budget_s: float
    elapsed_s: float = 0.0
    stopped_reason: str = "unknown"
    path: list[PathSample] = field(default_factory=list)
    map_growth: list[MapGrowthSample] = field(default_factory=list)
    reasons: dict[str, int] = field(default_factory=dict)
    submitted: int = 0
    refused: int = 0
    collision_ticks: int = 0

    @property
    def path_length_m(self) -> float:
        total = 0.0
        for before, after in zip(self.path, self.path[1:], strict=False):
            total += math.hypot(after.x - before.x, after.y - before.y)
        return total

    @property
    def net_displacement_m(self) -> float:
        if len(self.path) < 2:
            return 0.0
        return math.hypot(self.path[-1].x - self.path[0].x, self.path[-1].y - self.path[0].y)

    def as_dict(self) -> dict[str, Any]:
        return {
            "scene": self.scene,
            "budget_s": self.budget_s,
            "elapsed_s": round(self.elapsed_s, 4),
            "stopped_reason": self.stopped_reason,
            "path_length_m": round(self.path_length_m, 6),
            "net_displacement_m": round(self.net_displacement_m, 6),
            "path_samples": len(self.path),
            "reasons": dict(sorted(self.reasons.items())),
            "submitted": self.submitted,
            "refused": self.refused,
            "collision_ticks": self.collision_ticks,
            "map_entries_final": (
                self.map_growth[-1].entries if self.map_growth else 0
            ),
            "map_labels_final": (
                list(self.map_growth[-1].labels) if self.map_growth else []
            ),
            "path": [sample.as_dict() for sample in self.path],
            "map_growth": [sample.as_dict() for sample in self.map_growth],
        }


def forward_clearance_from_scan(
    ranges: Sequence[float],
    *,
    angle_min_rad: float,
    angle_increment_rad: float,
    range_max_m: float | None = None,
    half_angle_rad: float = FORWARD_HALF_ANGLE_RAD,
) -> float | None:
    """Shortest ray inside the body-forward cone, or ``None`` if none is valid.

    NaN rays are ignored (dropout / self-return), matching the scan contract;
    a cone with no valid ray returns ``None``, which the policy treats as
    "unknown", never as "clear".
    """

    if not ranges or not math.isfinite(angle_increment_rad) or angle_increment_rad == 0.0:
        return None
    best: float | None = None
    for index, value in enumerate(ranges):
        try:
            distance = float(value)
        except (TypeError, ValueError):
            continue
        if math.isnan(distance) or not math.isfinite(distance):
            continue
        if range_max_m is not None and distance >= range_max_m:
            continue
        angle = angle_min_rad + index * angle_increment_rad
        angle = math.atan2(math.sin(angle), math.cos(angle))
        if abs(angle) >= half_angle_rad:
            continue
        if best is None or distance < best:
            best = distance
    return best


def sense_from_snapshot(
    snapshot: Mapping[str, Any],
    *,
    elapsed_s: float,
    owner_envelope_m: float = 0.55,
    coverage_bearing_rad: float | None = None,
    coverage_age_s: float | None = None,
) -> PatrolSense | None:
    """Build a :class:`PatrolSense` from the runtime's public state snapshot.

    Returns ``None`` when the snapshot carries no robot pose — an absent pose
    is not a pose at the origin, and the runner must not drive on one.

    Card ROAM-2: the coverage objective arrives as two arguments rather than
    as two more snapshot keys, because it does not come from the SNAPSHOT — it
    comes from the learned map, under the map's own lock, on the caller's side.
    Both default to ``None``, so every existing caller builds a byte-identical
    sense.
    """

    robot = snapshot.get("robot")
    if not isinstance(robot, Mapping):
        return None
    try:
        x = float(robot["x"])
        y = float(robot["y"])
        # ``RobotRuntime.snapshot`` publishes the heading in DEGREES
        # (``runtime.py``: ``"heading": math.degrees(observation.robot.yaw)``).
        # Reading it as radians silently corrupts every bearing computed from
        # it — measured on a live patrol, which produced a "bearing" of
        # -81.9 rad and a person predicate that decided nothing.
        yaw = math.radians(float(robot.get("heading", 0.0)))
    except (KeyError, TypeError, ValueError):
        return None
    if not all(math.isfinite(value) for value in (x, y, yaw)):
        return None

    forward: float | None = None
    scan = snapshot.get("lidar_scan")
    if isinstance(scan, Mapping) and isinstance(scan.get("ranges"), Sequence):
        forward = forward_clearance_from_scan(
            scan["ranges"],
            angle_min_rad=float(scan.get("angle_min_rad", -math.pi)),
            angle_increment_rad=float(scan.get("angle_increment_rad", 0.0)),
            range_max_m=(
                float(scan["range_max_m"]) if scan.get("range_max_m") is not None else None
            ),
        )
    if forward is None:
        obstacle = snapshot.get("obstacle_distance_m")
        if isinstance(obstacle, (int, float)) and not isinstance(obstacle, bool):
            forward = float(obstacle)

    # People, including the owner. The owner is a person for standoff purposes
    # and carries an extra collision envelope; forgetting that is exactly what
    # parked C-1's robot 0.31 m from the origin.
    clearances: list[tuple[float, float | None]] = []
    nearest = snapshot.get("nearest_person")
    if isinstance(nearest, Mapping):
        distance = nearest.get("distance_m")
        if isinstance(distance, (int, float)) and not isinstance(distance, bool):
            bearing = nearest.get("bearing_rad")
            clearances.append(
                (
                    float(distance),
                    float(bearing)
                    if isinstance(bearing, (int, float))
                    and not isinstance(bearing, bool)
                    else None,
                )
            )
    owner = snapshot.get("owner")
    if isinstance(owner, Mapping) and owner.get("visible"):
        try:
            owner_dx = float(owner["x"]) - x
            owner_dy = float(owner["y"]) - y
        except (KeyError, TypeError, ValueError):
            owner_dx = owner_dy = None
        if owner_dx is not None and owner_dy is not None:
            owner_distance = math.hypot(owner_dx, owner_dy)
            if math.isfinite(owner_distance):
                clearances.append(
                    (
                        max(0.0, owner_distance - owner_envelope_m),
                        math.atan2(owner_dy, owner_dx) - yaw,
                    )
                )

    # Keyed on distance: a tuple compare would reach the bearing on a tie
    # and raise when one of them is None.
    nearest_person = (
        min(clearances, key=lambda item: item[0]) if clearances else (None, None)
    )
    return PatrolSense(
        elapsed_s=elapsed_s,
        x=x,
        y=y,
        yaw=yaw,
        forward_clearance_m=forward,
        person_clearance_m=nearest_person[0] if clearances else None,
        person_bearing_rad=nearest_person[1] if clearances else None,
        collision=bool(snapshot.get("collision")),
        coverage_bearing_rad=coverage_bearing_rad,
        coverage_age_s=coverage_age_s,
    )


class PatrolRunner:
    """Drives one bounded patrol and returns its record.

    Deliberately I/O-only: it owns the clock, the submit call and the two
    recorders, and delegates every decision to :class:`PatrolPolicy`.
    """

    def __init__(
        self,
        *,
        scene: str,
        sense_provider: Callable[[float], PatrolSense | None],
        submit: Callable[[PatrolCommand], bool],
        map_probe: Callable[[], MapGrowthSample] | None = None,
        policy: PatrolPolicy | None = None,
        limits: PatrolLimits | None = None,
        tick_s: float = 0.25,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if tick_s <= 0.0 or not math.isfinite(tick_s):
            raise ValueError("tick_s must be positive and finite")
        self.scene = scene
        self.limits = limits or (policy.limits if policy else PatrolLimits())
        self.policy = policy or PatrolPolicy(self.limits)
        self._sense_provider = sense_provider
        self._submit = submit
        self._map_probe = map_probe
        self._tick_s = tick_s
        self._clock = clock
        self._sleep = sleep

    def run(self) -> PatrolReport:
        report = PatrolReport(scene=self.scene, budget_s=self.limits.budget_s)
        started = self._clock()
        stopped_reason = "budget_exhausted"
        while True:
            elapsed = self._clock() - started
            if elapsed >= self.limits.budget_s:
                stopped_reason = "budget_exhausted"
                break
            sense = self._sense_provider(elapsed)
            if sense is None:
                # No pose this tick. Do not drive blind, do not end the
                # mission on one gap; skip and let the budget run.
                report.reasons["no_sense"] = report.reasons.get("no_sense", 0) + 1
                self._sleep(self._tick_s)
                continue
            if sense.collision:
                report.collision_ticks += 1
            command = self.policy.step(sense)
            report.reasons[command.reason] = report.reasons.get(command.reason, 0) + 1
            report.path.append(
                PathSample(
                    t_s=sense.elapsed_s,
                    x=sense.x,
                    y=sense.y,
                    yaw=sense.yaw,
                    reason=command.reason,
                )
            )
            if self._map_probe is not None:
                report.map_growth.append(
                    replace(self._map_probe(), t_s=sense.elapsed_s)
                )
            if command.reason == "boxed_in":
                stopped_reason = "boxed_in"
                break
            if command.reason == "budget_exhausted":
                stopped_reason = "budget_exhausted"
                break
            report.submitted += 1
            if not self._submit(command):
                report.refused += 1
            self._sleep(self._tick_s)
        report.elapsed_s = self._clock() - started
        report.stopped_reason = stopped_reason
        return report
