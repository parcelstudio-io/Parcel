"""Yield-aside proposer: corridor min-clearance scoring over rotated follow aims.

Wave-3 card Y-1 (``scrum/20260811/task_1/FOLLOWUP_DESIGNS.md`` §4.2). The
follow controller's direct mode aims at the owner and holds
``desired_distance_m`` from that aim. When a stranger stream occupies the
corridor between the robot and the owner, the only lever this module offers is
WHICH aim the controller chases: a candidate point on the circle of radius
``desired_distance_m`` about the owner, its bearing rotated off the current
robot bearing. Rotating the aim rather than translating it is what preserves
the distance law — ``|aim - owner| == desired_distance_m`` for every emitted
proposal, exactly (see :func:`circle_offset`).

**This module PROPOSES; it disposes of nothing.** The aim it returns is
consumed upstream of the untouched dispatch chain (velocity smoother ->
``apply_reactive_safety`` -> TTC -> shaper), so every comfort band, person stop
ring, collision veto and K0 semantic still applies to whatever command the
controller derives from the aim. An inactive proposal reproduces today's
behavior exactly, which is what makes the three fail-closed exits
(``no_strangers`` / ``no_scan`` / ``no_meaningful_aside``) a strict superset of
the current in-place brake rather than a new authority.

Two contract clauses are load-bearing and both come from the skeptic pass
(adjudication #10); neither is "safe by construction":

*Closed-loop equilibrium.* ``_step_direct`` holds ``desired_distance_m`` from
the AIM, so ``|robot - owner|`` is not constrained by ``|aim - owner|``. Under
the verified law (translate while ``distance - desired > deadband``, hold
otherwise) a stationary-owner chase of a rotated aim has the fixed point

    ``r_eq(theta) = D*cos(theta) + sqrt(h**2 - D**2 * sin(theta)**2)``

with ``D = desired_distance_m``, ``h = D + deadband`` and ``sin(theta) =
offset / D``. That expression is decreasing in ``theta``, so the whole
admissible family is bounded below by its value at the largest usable offset,
and :class:`YieldAsideLimits` REFUSES TO CONSTRUCT unless that bound clears
``owner_keepout_m`` (:meth:`YieldAsideLimits.equilibrium_floor_m`). The bound
is a precondition here and a seeded property test in
``tests/test_yield_aside.py``; the runtime disposer remains the untouched
reactive gate.

*Lagging-regime admissibility (stall guard).* The deadband is ONE-SIDED
(``distance_error <= deadband`` holds, including every negative error), so an
aim rotated toward a lagging robot can drop ``|robot - aim|`` inside the hold
ring and freeze a chase that was closing. While the robot lags
(``|robot - owner| > desired + deadband``) a candidate is admissible only if
``|robot - aim|`` stays strictly above the hold ring. The skeptic's worked
example (lag 2.77 m, offset 0.6 m -> ``|robot - aim| ~ 1.18 m``) is a canned
must-reject case in the tests.

Margins are DERIVED, never chosen here:

* max offset = ``person_comfort_band_m - person_stop(0.0)`` (:data:`MAX_ASIDE_OFFSET_M`)
  — the width of the stranger comfort band outside the stop ring, i.e. exactly
  the lateral room the gate's own bands price.
* candidate step = the caller's ``FollowConfig.distance_deadband_m`` — a step
  smaller than the controller's own distance resolution would propose
  differences the law cannot act on.
* rollout horizon = ``person_comfort_band_m / max_vx`` — how long the robot
  needs to cross the band it is trying to keep.
* rollout base step = :data:`MEANINGFUL_IMPROVEMENT_M` / ``max_vx`` and the
  sampling resolution = :data:`MEANINGFUL_IMPROVEMENT_M` — one improvement
  quantum of relative travel per sample, halved by the SB-1 rule below.
* minimum meaningful improvement = ``OWNER_STAND_OFF_MARGIN_M`` — the
  authority's standing margin, imported from ``reactive_safety`` so it cannot
  fork from the owner band that the same constant defines.

Pure by contract: stdlib plus the authority constants, no I/O, no clocks, no
imports from ``follow`` / ``pipeline`` / ``runtime`` (``follow`` imports THIS
module, never the reverse). Deterministic: identical inputs give bit-identical
proposals. Malformed values raise ``ValueError`` and malformed types raise
``TypeError`` loudly at every public entry point, repo style
(``FollowConfig`` splits the two the same way).

``does_not_prove``: the reactive gate's people list carries ONE stranger scalar
plus the owner, so this module's rejection over the full ``dynamic_agents``
track set is load-bearing rather than belt-and-suspenders (adjudication #11);
the free-range check is a walkability PROXY over a planar scan, not a traversal
guarantee; the constant-velocity rollout is an extrapolation, not a prediction
of what a pedestrian will actually do.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from parcel_robot.authority import DEFAULT_SAFETY_ENVELOPE
from parcel_robot.navigation.reactive_safety import OWNER_STAND_OFF_MARGIN_M
from parcel_robot.navigation.traffic_aware import (
    MAX_SAMPLES_PER_TRACK,
    coerce_tracks,
)

#: Largest lateral aim offset the proposer may consider: the stranger comfort
#: band minus the stranger stop ring (2.5 - 1.2 = 1.3 m today). DERIVED from
#: the one safety authority — the band whose violation the aside exists to
#: avoid is the same band that bounds how far aside it may reach.
MAX_ASIDE_OFFSET_M = (
    DEFAULT_SAFETY_ENVELOPE.person_comfort_band_m - DEFAULT_SAFETY_ENVELOPE.person_stop(0.0)
)

#: The smallest predicted-clearance gain worth changing the aim for, and the
#: rollout's spatial resolution. Imported, not restated: this is the authority's
#: ``arrival_radius_m + stand_off_margin_m`` pair that already separates a
#: minimum-clearance ring from the stand-off that wraps it.
MEANINGFUL_IMPROVEMENT_M = OWNER_STAND_OFF_MARGIN_M

#: How many one-ULP corrections :func:`circle_offset` may spend making the
#: emitted radius EXACTLY ``desired_distance_m``. Measured over 50k random
#: bearings at the shipped radius: at most 2 were ever needed, so 8 is a
#: budget, not a tuning knob. A candidate that exhausts it is REJECTED rather
#: than emitted with an off-circle aim.
RADIUS_ULP_BUDGET = 8

#: Inactive reasons, frozen contract. The first three are the fail-closed
#: triple; ``clearance_recovered`` is the asymmetric exit.
INACTIVE_REASONS = frozenset(
    {
        "no_strangers",
        "no_scan",
        "no_meaningful_aside",
        "clearance_recovered",
    }
)

#: The one active reason.
ACTIVE_REASON = "yield_aside"


@dataclass(frozen=True)
class YieldAsideLimits:
    """Geometry the proposer may use; every value supplied by the caller.

    The follow controller owns all of these (``FollowConfig``); restating them
    here would be exactly the literal drift the H-1/E5/E6 derivations removed,
    so this dataclass only VALIDATES the relationships it depends on.

    ``__post_init__`` enforces the closed-loop equilibrium precondition: the
    fixed point of the verified distance law at the largest usable offset must
    still clear ``owner_keepout_m``. A caller whose geometry cannot honour that
    gets a ``ValueError`` at construction instead of a proposal that would park
    the robot inside the ring the reactive gate defends.
    """

    desired_distance_m: float
    deadband_m: float
    max_vx_mps: float
    owner_keepout_m: float
    obstacle_stop_m: float
    person_stop_m: float = DEFAULT_SAFETY_ENVELOPE.person_stop(0.0)
    person_slow_m: float = DEFAULT_SAFETY_ENVELOPE.person_comfort_band_m

    def __post_init__(self) -> None:
        values = (
            self.desired_distance_m,
            self.deadband_m,
            self.max_vx_mps,
            self.owner_keepout_m,
            self.obstacle_stop_m,
            self.person_stop_m,
            self.person_slow_m,
        )
        if any(not math.isfinite(value) or value <= 0.0 for value in values):
            raise ValueError("yield-aside limits must be positive and finite")
        if self.person_stop_m >= self.person_slow_m:
            raise ValueError("person stop distance must be below the person slow band")
        if self.desired_distance_m <= self.owner_keepout_m:
            raise ValueError("desired follow distance must clear the owner keepout")
        if not self.offsets_m:
            raise ValueError(
                "yield-aside offsets are empty: the candidate step must admit at "
                "least one offset below the follow distance"
            )
        floor = self.equilibrium_floor_m
        if floor + 1e-12 < self.owner_keepout_m:
            raise ValueError(
                "yield-aside closed-loop equilibrium would park the robot inside "
                f"the owner keepout (floor {floor:.3f} m < {self.owner_keepout_m:.3f} m)"
            )

    @property
    def hold_ring_m(self) -> float:
        """``desired + deadband`` — where the one-sided deadband stops the chase."""

        return self.desired_distance_m + self.deadband_m

    @property
    def offsets_m(self) -> tuple[float, ...]:
        """Candidate lateral offsets: multiples of the caller's distance deadband.

        Capped by :data:`MAX_ASIDE_OFFSET_M` and, geometrically, by the follow
        radius itself — an offset at or beyond ``desired_distance_m`` has no
        bearing rotation that realizes it on the circle.
        """

        ceiling = min(MAX_ASIDE_OFFSET_M, self.desired_distance_m)
        offsets: list[float] = []
        index = 1
        while True:
            offset = index * self.deadband_m
            if offset > ceiling or offset >= self.desired_distance_m:
                break
            offsets.append(offset)
            index += 1
            if index > 1000:  # pragma: no cover - deadband validated positive
                break
        return tuple(offsets)

    @property
    def equilibrium_floor_m(self) -> float:
        """Lower bound on ``|robot_eq - owner|`` over every admissible proposal.

        ``r_eq(theta) = D*cos(theta) + sqrt(h**2 - D**2*sin(theta)**2)`` is
        decreasing on ``[0, theta_max]`` (both terms decrease), so evaluating it
        at the largest usable offset bounds the whole family. With no offsets
        the family is empty and the un-rotated law's own fixed point ``h``
        applies.
        """

        offsets = self.offsets_m
        if not offsets:  # pragma: no cover - construction rejects this
            return self.hold_ring_m
        lateral = offsets[-1]
        along = math.sqrt(max(0.0, self.desired_distance_m**2 - lateral**2))
        radial = math.sqrt(max(0.0, self.hold_ring_m**2 - lateral**2))
        return along + radial

    @property
    def horizon_s(self) -> float:
        """Rollout horizon: crossing the stranger comfort band at full speed."""

        return self.person_slow_m / self.max_vx_mps

    @property
    def rollout_step_s(self) -> float:
        """Base rollout step: one improvement quantum of travel at full speed."""

        return MEANINGFUL_IMPROVEMENT_M / self.max_vx_mps


@dataclass(frozen=True)
class YieldAsideProposal:
    """One proposer verdict. ``active`` false reproduces today's aim exactly.

    ``side`` is the sign of the AIM's rotation about the owner. The controller
    parks on the FAR side of its aim, so the robot's stance displaces the other
    way: ``side = +1`` (aim rotated counter-clockwise) walks the stance
    clockwise, away from a stranger on the counter-clockwise side. Callers that
    latch a side are latching the aim's sense, which is all the latch needs to
    be; anything reasoning about where the ROBOT ends up must go through
    :func:`predicted_stance`.

    ``aim_dx_m`` / ``aim_dy_m`` are the OFFSET FROM THE OWNER and carry the
    exact distance law: ``math.hypot(aim_dx_m, aim_dy_m) == desired_distance_m``
    for every active proposal, exactly, not approximately. ``aim_x_m`` /
    ``aim_y_m`` are the convenience sum ``owner + offset``; that addition is a
    second rounding, so the absolute point is the offset's float-lattice
    neighbour rather than a third source of truth.
    """

    active: bool
    reason: str
    side: int = 0
    offset_m: float = 0.0
    aim_dx_m: float = 0.0
    aim_dy_m: float = 0.0
    aim_x_m: float | None = None
    aim_y_m: float | None = None
    baseline_clearance_m: float | None = None
    aside_clearance_m: float | None = None
    improvement_m: float = 0.0
    candidates_considered: int = 0
    candidates_rejected: int = 0

    def __post_init__(self) -> None:
        if self.active:
            if self.reason != ACTIVE_REASON:
                raise ValueError(f"active proposals must carry reason {ACTIVE_REASON!r}")
            if self.side not in (-1, 1):
                raise ValueError("an active proposal must carry a side of -1 or +1")
        elif self.reason not in INACTIVE_REASONS:
            raise ValueError(f"unknown inactive yield-aside reason: {self.reason!r}")


@dataclass(frozen=True)
class _Candidate:
    """One surviving candidate, carried until the ranking picks a winner."""

    side: int
    offset_m: float
    aim_dx_m: float
    aim_dy_m: float
    aim_x_m: float
    aim_y_m: float
    clearance_m: float
    improvement_m: float


def corridor_min_clearance(
    start: tuple[float, float],
    end: tuple[float, float],
    tracks: Sequence[object],
    *,
    speed_mps: float,
    horizon_s: float,
    step_s: float,
    resolution_m: float,
) -> float:
    """Worst predicted SURFACE clearance to any track along ``start -> end``.

    The robot is rolled forward along the segment at ``speed_mps`` and parks at
    ``end`` for the remainder of ``horizon_s`` (parking matters: the strangers
    keep coming after the robot arrives). Every track is rolled out at constant
    velocity over the same clock, so the returned minimum is a SPACE-TIME
    minimum, not the minimum over a static snapshot.

    Sampling (SB-1 rule, borrowed from ``traffic_aware.traffic_occupancy_cost``):
    the per-track substep is ``min(step_s, resolution_m / (2 * relative_speed))``
    so no pair can close and reopen between samples — the sampled minimum can
    exceed the true minimum by at most ``resolution_m / 2``. The substep is
    floored at ``horizon_s / MAX_SAMPLES_PER_TRACK`` (SB-2) so a pathological
    resolution degrades accuracy instead of stalling the control loop.

    Returns ``math.inf`` when there are no tracks — nothing to be near. The
    result may be negative (overlap); it is never clamped, because a clamp
    would hide exactly the case the person-stop reject exists for.
    """

    start_x, start_y = _finite_pair(start, "start")
    end_x, end_y = _finite_pair(end, "end")
    speed = _positive(speed_mps, "speed_mps")
    horizon = _positive(horizon_s, "horizon_s")
    step = _positive(step_s, "step_s")
    resolution = _positive(resolution_m, "resolution_m")
    validated = coerce_tracks(tracks)
    if not validated:
        return math.inf

    length = math.hypot(end_x - start_x, end_y - start_y)
    travel_s = length / speed
    floor_s = horizon / MAX_SAMPLES_PER_TRACK
    worst = math.inf
    for track in validated:
        relative = speed + math.hypot(track.vx, track.vy)
        substep = step
        if relative > 0.0:
            substep = min(substep, resolution / (2.0 * relative))
        substep = max(substep, floor_s)
        samples = math.floor(horizon / substep + 1e-9)
        for index in range(samples + 1):
            elapsed = index * substep
            fraction = 1.0 if travel_s <= 0.0 else min(1.0, elapsed / travel_s)
            robot_x = start_x + (end_x - start_x) * fraction
            robot_y = start_y + (end_y - start_y) * fraction
            agent_x = track.x + track.vx * elapsed
            agent_y = track.y + track.vy * elapsed
            surface = math.hypot(robot_x - agent_x, robot_y - agent_y) - track.radius_m
            worst = min(worst, surface)
    return worst


def predicted_stance(
    robot_xy: tuple[float, float],
    aim_xy: tuple[float, float],
    *,
    desired_distance_m: float,
    deadband_m: float,
) -> tuple[float, float]:
    """Where the verified ``_step_direct`` distance law parks the robot.

    Faithful to the law's ONE-SIDED deadband: the controller translates only
    while ``distance - desired > deadband``, so an aim already inside the hold
    ring produces no motion at all and the predicted stance is the robot's
    current position. Otherwise the robot closes along the straight
    robot->aim bearing and the stance is taken at ``desired_distance_m`` from
    the aim — deliberately the INNER edge of the hold band, so the predicted
    path is never shorter than the path actually travelled.
    """

    robot_x, robot_y = _finite_pair(robot_xy, "robot_xy")
    aim_x, aim_y = _finite_pair(aim_xy, "aim_xy")
    desired = _positive(desired_distance_m, "desired_distance_m")
    deadband = _positive(deadband_m, "deadband_m")
    distance = math.hypot(aim_x - robot_x, aim_y - robot_y)
    if distance <= desired + deadband:
        return (robot_x, robot_y)
    scale = desired / distance
    return (aim_x + (robot_x - aim_x) * scale, aim_y + (robot_y - aim_y) * scale)


def circle_offset(bearing_rad: float, radius_m: float) -> tuple[float, float] | None:
    """Offset vector of length EXACTLY ``radius_m`` at (essentially) ``bearing_rad``.

    ``radius * (cos b, sin b)`` lands on the requested circle only about 79% of
    the time in binary floating point, and rescaling by ``radius / hypot``
    converges to ~92% — not good enough for a contract that says ``==``. So the
    remaining cases walk the larger component by single ULPs (at most 2 were
    ever needed over 50k measured bearings) until ``math.hypot`` returns the
    radius bit-for-bit. The bearing moves by at most one ULP of the radius
    (measured worst case 2.2e-16 rad) — far below any geometry this consumes.

    Returns ``None`` when :data:`RADIUS_ULP_BUDGET` is exhausted, which the
    caller must treat as a REJECTED candidate: an aim that is not on the circle
    is not a distance-law-preserving aim, and shipping it anyway is the exact
    "approximately" this contract refuses.
    """

    bearing = _finite(bearing_rad, "bearing_rad")
    radius = _positive(radius_m, "radius_m")
    offset_x = radius * math.cos(bearing)
    offset_y = radius * math.sin(bearing)
    for _ in range(4):
        length = math.hypot(offset_x, offset_y)
        if length == radius:
            return (offset_x, offset_y)
        scale = radius / length
        offset_x *= scale
        offset_y *= scale
    if abs(offset_x) >= abs(offset_y):
        major, minor, swapped = offset_x, offset_y, False
    else:
        major, minor, swapped = offset_y, offset_x, True
    length = math.hypot(major, minor)
    toward = math.inf if length < radius else -math.inf
    if major < 0.0:
        toward = -toward
    for _ in range(RADIUS_ULP_BUDGET):
        major = math.nextafter(major, toward)
        if math.hypot(major, minor) == radius:
            return (minor, major) if swapped else (major, minor)
    return None


def planar_free_range(
    ranges_m: Sequence[float],
    *,
    angle_min_rad: float,
    angle_increment_rad: float,
    range_max_m: float,
    robot_yaw_rad: float,
    bearing_rad: float,
    span_m: float,
) -> float:
    """Free range along a WORLD bearing, read as a corridor and not a needle.

    The angular window is DERIVED, not chosen: the robot has to fit through
    whatever it drives into, so the rays consulted are those within
    ``asin(footprint_radius_m / span_m)`` of the query — the half-angle the
    robot's own footprint subtends at the far end of the candidate path. A
    single-ray query would call the gap beside a lamp post a clear lane; a
    fixed window would be a new constant nobody derived.

    Ray conventions follow ``LidarScan``: non-finite entries are ignored rays
    except ``+inf``, which is a no-return that clears through ``range_max_m``,
    and finite values at or beyond the maximum are no-returns too. Returns
    ``0.0`` when the window holds no usable ray — fail-closed, because an
    unobserved corridor is not a free one.

    Takes the scan unpacked rather than a ``SimObservation``, which keeps this
    module free of backend types and directly unit-testable.
    """

    increment = _finite(angle_increment_rad, "angle_increment_rad")
    if increment == 0.0:
        raise ValueError("angle_increment_rad must be non-zero")
    minimum_angle = _finite(angle_min_rad, "angle_min_rad")
    maximum_range = _positive(range_max_m, "range_max_m")
    yaw = _finite(robot_yaw_rad, "robot_yaw_rad")
    span = _positive(span_m, "span_m")
    relative = _wrapped(_finite(bearing_rad, "bearing_rad") - yaw)
    footprint = DEFAULT_SAFETY_ENVELOPE.footprint_radius_m
    half_window = math.asin(min(1.0, footprint / max(span, footprint)))

    free = math.inf
    seen = False
    for index, raw in enumerate(ranges_m):
        angle = _wrapped(minimum_angle + index * increment)
        if abs(_wrapped(angle - relative)) > half_window:
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(value):
            if value == math.inf:
                seen = True
                free = min(free, maximum_range)
            continue
        seen = True
        free = min(free, maximum_range, value)
    return free if seen and math.isfinite(free) else 0.0


def propose_yield_aside(
    *,
    robot_xy: tuple[float, float],
    owner_xy: tuple[float, float],
    tracks: Sequence[object],
    limits: YieldAsideLimits,
    free_range_m: Callable[[float, float], float] | None,
    latched_side: int = 0,
    engaged: bool = False,
) -> YieldAsideProposal:
    """Propose a rotated follow aim that routes the chase around a stranger stream.

    ``tracks`` is the FULL ``dynamic_agents`` set (any ``coerce_tracks`` input).
    Rejecting over all of them is load-bearing: the reactive gate downstream
    carries only the nearest stranger scalar plus the owner, so a candidate that
    is clear of the nearest pedestrian and swept by a second one would otherwise
    reach the gate unopposed (adjudication #11).

    ``free_range_m(bearing_rad, span_m)`` returns the static free range from
    the robot along a WORLD bearing, read over a corridor as wide as the robot
    (:func:`planar_free_range` is the shipped implementation); ``None`` means no
    calibrated scan and fails closed. A candidate is rejected unless the scan
    clears the whole predicted path plus ``obstacle_stop_m`` — a walkability
    proxy, stated as such.

    ``latched_side`` (-1 / +1, 0 = unlatched) is the caller's committed side;
    it only breaks ties, never overrides clearance. ``engaged`` is the caller's
    statement that an aside is already in force and selects the hold arm of the
    asymmetric exit. Both arms share the domain condition — the un-offset
    predicted path must be INSIDE the ``person_slow_m`` comfort band, or there
    is nothing to yield from — and differ in what they charge inside it:
    entering costs a full :data:`MEANINGFUL_IMPROVEMENT_M` over the un-offset
    path, holding only requires not being worse than it.
    """

    robot_x, robot_y = _finite_pair(robot_xy, "robot_xy")
    owner_x, owner_y = _finite_pair(owner_xy, "owner_xy")
    if not isinstance(limits, YieldAsideLimits):
        raise TypeError("limits must be a YieldAsideLimits")
    if latched_side not in (-1, 0, 1):
        raise ValueError("latched_side must be -1, 0, or +1")
    if engaged is not True and engaged is not False:
        raise TypeError("engaged must be a boolean")
    validated = coerce_tracks(tracks)
    if not validated:
        return YieldAsideProposal(active=False, reason="no_strangers")
    if free_range_m is None:
        return YieldAsideProposal(active=False, reason="no_scan")

    bearing = math.atan2(robot_y - owner_y, robot_x - owner_x)
    lagging = math.hypot(robot_x - owner_x, robot_y - owner_y) > limits.hold_ring_m

    baseline_stance = predicted_stance(
        (robot_x, robot_y),
        (owner_x, owner_y),
        desired_distance_m=limits.desired_distance_m,
        deadband_m=limits.deadband_m,
    )
    baseline = corridor_min_clearance(
        (robot_x, robot_y),
        baseline_stance,
        validated,
        speed_mps=limits.max_vx_mps,
        horizon_s=limits.horizon_s,
        step_s=limits.rollout_step_s,
        resolution_m=MEANINGFUL_IMPROVEMENT_M,
    )
    if baseline >= limits.person_slow_m:
        # The aside's whole domain is "the un-offset path is inside the stranger
        # comfort band". Outside it there is nothing to yield from: an engaged
        # caller RELEASES (the asymmetric exit), and an unengaged one must not
        # enter, or a stranger 9 m away would buy a lateral detour worth one
        # improvement quantum of nothing.
        return YieldAsideProposal(
            active=False,
            reason="clearance_recovered" if engaged else "no_meaningful_aside",
            baseline_clearance_m=baseline,
        )

    required_improvement = 0.0 if engaged else MEANINGFUL_IMPROVEMENT_M
    considered = 0
    rejected = 0
    best_key: tuple[float, float, int, int] | None = None
    best: _Candidate | None = None
    for offset in limits.offsets_m:
        rotation = math.asin(offset / limits.desired_distance_m)
        for side in (1, -1):
            considered += 1
            vector = circle_offset(bearing + side * rotation, limits.desired_distance_m)
            if vector is None:
                rejected += 1
                continue
            aim_dx, aim_dy = vector
            aim_x = owner_x + aim_dx
            aim_y = owner_y + aim_dy
            reach = math.hypot(aim_x - robot_x, aim_y - robot_y)
            if lagging and reach <= limits.hold_ring_m:
                # Stall guard: the one-sided deadband would turn this lagging
                # chase into an 'at_follow_distance' hold.
                rejected += 1
                continue
            stance = predicted_stance(
                (robot_x, robot_y),
                (aim_x, aim_y),
                desired_distance_m=limits.desired_distance_m,
                deadband_m=limits.deadband_m,
            )
            clearance = corridor_min_clearance(
                (robot_x, robot_y),
                stance,
                validated,
                speed_mps=limits.max_vx_mps,
                horizon_s=limits.horizon_s,
                step_s=limits.rollout_step_s,
                resolution_m=MEANINGFUL_IMPROVEMENT_M,
            )
            if clearance < limits.person_stop_m:
                rejected += 1
                continue
            span = math.hypot(stance[0] - robot_x, stance[1] - robot_y)
            if span > 0.0:
                heading = math.atan2(stance[1] - robot_y, stance[0] - robot_x)
                free = _free_range(free_range_m, heading, span)
                if free < span + limits.obstacle_stop_m:
                    rejected += 1
                    continue
            improvement = clearance - baseline
            if improvement < required_improvement:
                rejected += 1
                continue
            # Ranking, fully deterministic: best clearance first; then the
            # smallest offset that achieves it (stay nearest the owner's own
            # stance — the owner-side preference); then the latched side; then
            # the fixed +1-before-(-1) order.
            key = (
                -clearance,
                offset,
                0 if (latched_side != 0 and side == latched_side) else 1,
                0 if side == 1 else 1,
            )
            if best_key is None or key < best_key:
                best_key = key
                best = _Candidate(
                    side=side,
                    offset_m=offset,
                    aim_dx_m=aim_dx,
                    aim_dy_m=aim_dy,
                    aim_x_m=aim_x,
                    aim_y_m=aim_y,
                    clearance_m=clearance,
                    improvement_m=improvement,
                )
    if best is None:
        return YieldAsideProposal(
            active=False,
            reason="no_meaningful_aside",
            baseline_clearance_m=baseline,
            candidates_considered=considered,
            candidates_rejected=rejected,
        )
    return YieldAsideProposal(
        active=True,
        reason=ACTIVE_REASON,
        side=best.side,
        offset_m=best.offset_m,
        aim_dx_m=best.aim_dx_m,
        aim_dy_m=best.aim_dy_m,
        aim_x_m=best.aim_x_m,
        aim_y_m=best.aim_y_m,
        baseline_clearance_m=baseline,
        aside_clearance_m=best.clearance_m,
        improvement_m=best.improvement_m,
        candidates_considered=considered,
        candidates_rejected=rejected,
    )


def _free_range(
    free_range_m: Callable[[float, float], float],
    bearing_rad: float,
    span_m: float,
) -> float:
    """Query the caller's scan, treating anything unusable as zero free range."""

    value = free_range_m(bearing_rad, span_m)
    try:
        free = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(free) or free < 0.0:
        return 0.0
    return free


def _wrapped(angle_rad: float) -> float:
    """Wrap to (-pi, pi]; the same convention the controller's yaw errors use."""

    return (angle_rad + math.pi) % (2.0 * math.pi) - math.pi


def _finite(value: object, name: str) -> float:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as error:
        raise ValueError(f"{name} must be a finite number") from error
    if not math.isfinite(number):
        raise ValueError(f"{name} must be a finite number")
    return number


def _positive(value: object, name: str) -> float:
    number = _finite(value, name)
    if number <= 0.0:
        raise ValueError(f"{name} must be positive")
    return number


def _finite_pair(point: object, name: str) -> tuple[float, float]:
    try:
        first, second = point  # type: ignore[misc]
    except (TypeError, ValueError) as error:
        raise ValueError(f"{name} must be an (x, y) pair") from error
    return _finite(first, f"{name}[0]"), _finite(second, f"{name}[1]")
