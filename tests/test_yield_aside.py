"""Card Y-1 gate: the yield-aside proposer's frozen contract.

Every property test in this file is paired with a SEEDED-VIOLATION test that
runs the same checker over a deliberately broken proposer and asserts the
checker FAILS. A property nobody has watched fail is a property nobody has
tested; the two skeptic-mandated clauses (closed-loop equilibrium, lagging
stall guard) carry that proof explicitly.

The closed-loop rollouts drive the REAL ``FollowOwnerController._step_direct``
through ``step()`` with an observation whose owner point is the proposed aim —
which is exactly the substitution card Y-2 performs inside ``_step_direct``
(the law reads the aim only through ``owner.x``/``owner.y``). The rollout
integrates the controller's raw command and deliberately omits the dispatch
chain: the smoother, ``apply_reactive_safety`` and the shaper only ever REDUCE
motion, so a keepout property proven on the unshaped command is conservative
for the shipped one.
"""

from __future__ import annotations

import math
import random

import pytest

from parcel_robot.authority import DEFAULT_SAFETY_ENVELOPE
from parcel_robot.backends.base import OwnerTrack, RobotPose, SimObservation
from parcel_robot.navigation import yield_aside as ya
from parcel_robot.navigation.follow import FollowConfig, FollowOwnerController
from parcel_robot.navigation.reactive_safety import OWNER_STAND_OFF_MARGIN_M
from parcel_robot.navigation.traffic_aware import TrackState

CONTROL_DT_S = 0.1


def _limits(**overrides: float) -> ya.YieldAsideLimits:
    """The shipped follow geometry, so the tests price the real constants."""

    config = FollowConfig()
    values: dict[str, float] = {
        "desired_distance_m": config.desired_distance_m,
        "deadband_m": config.distance_deadband_m,
        "max_vx_mps": config.max_vx,
        "owner_keepout_m": config.owner_keepout_m,
        "obstacle_stop_m": config.obstacle_stop_m,
        "person_stop_m": config.person_stop_m,
        "person_slow_m": config.person_slow_m,
    }
    values.update(overrides)
    return ya.YieldAsideLimits(**values)


def _open_scan(_bearing_rad: float, _span_m: float) -> float:
    """A scan that reports 30 m of free space in every direction."""

    return 30.0


def _observation(
    robot: tuple[float, float, float],
    aim: tuple[float, float],
    now: float,
) -> SimObservation:
    return SimObservation(
        timestamp=now,
        robot=RobotPose(x=robot[0], y=robot[1], yaw=robot[2]),
        owner=OwnerTrack(owner_id="owner-1", x=aim[0], y=aim[1], visible=True, confidence=1.0),
    )


# ---------------------------------------------------------------------------
# (d) derived margins, asserted by reference
# ---------------------------------------------------------------------------


def test_margins_are_derived_by_reference() -> None:
    assert ya.MEANINGFUL_IMPROVEMENT_M is OWNER_STAND_OFF_MARGIN_M
    assert ya.MAX_ASIDE_OFFSET_M == (
        DEFAULT_SAFETY_ENVELOPE.person_comfort_band_m - DEFAULT_SAFETY_ENVELOPE.person_stop(0.0)
    )
    limits = _limits()
    # Candidate step is the caller's distance deadband, not a local literal.
    assert limits.offsets_m[0] == FollowConfig().distance_deadband_m
    for index, offset in enumerate(limits.offsets_m, start=1):
        assert offset == index * FollowConfig().distance_deadband_m
    assert limits.offsets_m[-1] <= ya.MAX_ASIDE_OFFSET_M
    # Rollout horizon is the comfort band crossed at full speed.
    assert limits.horizon_s == limits.person_slow_m / limits.max_vx_mps
    assert limits.rollout_step_s == ya.MEANINGFUL_IMPROVEMENT_M / limits.max_vx_mps


def test_limits_reject_geometry_that_cannot_hold_the_keepout(monkeypatch) -> None:
    """SEEDED VIOLATION for the equilibrium precondition (arm 1 of 2).

    Widening the offset cap past what the distance law can pay for drops the
    closed-loop fixed point inside ``owner_keepout_m``; the constructor must
    refuse rather than emit proposals whose equilibrium is inside the ring.
    """

    monkeypatch.setattr(ya, "MAX_ASIDE_OFFSET_M", 1.84)
    with pytest.raises(ValueError, match="closed-loop equilibrium"):
        _limits()


def test_equilibrium_floor_matches_the_documented_expression() -> None:
    limits = _limits()
    offset = limits.offsets_m[-1]
    theta = math.asin(offset / limits.desired_distance_m)
    expected = limits.desired_distance_m * math.cos(theta) + math.sqrt(
        limits.hold_ring_m**2 - limits.desired_distance_m**2 * math.sin(theta) ** 2
    )
    assert limits.equilibrium_floor_m == pytest.approx(expected, abs=1e-12)
    assert limits.equilibrium_floor_m >= limits.owner_keepout_m


# ---------------------------------------------------------------------------
# (b) the fail-closed triple
# ---------------------------------------------------------------------------


def test_no_strangers_is_inactive() -> None:
    proposal = ya.propose_yield_aside(
        robot_xy=(0.0, 0.0),
        owner_xy=(3.4, 0.0),
        tracks=(),
        limits=_limits(),
        free_range_m=_open_scan,
    )
    assert (proposal.active, proposal.reason) == (False, "no_strangers")
    assert proposal.aim_x_m is None and proposal.aim_y_m is None


def test_missing_scan_is_inactive() -> None:
    proposal = ya.propose_yield_aside(
        robot_xy=(0.0, 0.0),
        owner_xy=(3.4, 0.0),
        tracks=(TrackState(x=2.0, y=-1.6, vx=0.0, vy=0.5, radius_m=0.2),),
        limits=_limits(),
        free_range_m=None,
    )
    assert (proposal.active, proposal.reason) == (False, "no_scan")


def test_no_meaningful_aside_is_inactive() -> None:
    """A stranger dead ahead in a corridor with no clear route: today's brake."""

    proposal = ya.propose_yield_aside(
        robot_xy=(0.0, 0.0),
        owner_xy=(3.4, 0.0),
        tracks=(TrackState(x=1.5, y=0.0, vx=0.0, vy=0.0, radius_m=0.2),),
        limits=_limits(),
        free_range_m=_open_scan,
    )
    assert (proposal.active, proposal.reason) == (False, "no_meaningful_aside")
    assert proposal.candidates_rejected == proposal.candidates_considered


def test_blocked_scan_rejects_every_candidate() -> None:
    """The walkability proxy fails closed when the scan reports no free range."""

    tracks = (TrackState(x=2.0, y=-1.6, vx=0.0, vy=0.5, radius_m=0.2),)
    open_proposal = ya.propose_yield_aside(
        robot_xy=(0.0, 0.0),
        owner_xy=(3.4, 0.0),
        tracks=tracks,
        limits=_limits(),
        free_range_m=_open_scan,
    )
    assert open_proposal.active
    blocked = ya.propose_yield_aside(
        robot_xy=(0.0, 0.0),
        owner_xy=(3.4, 0.0),
        tracks=tracks,
        limits=_limits(),
        free_range_m=lambda _bearing, _span: 0.2,
    )
    assert (blocked.active, blocked.reason) == (False, "no_meaningful_aside")
    # A scan callable that returns garbage is treated as zero free range.
    garbage = ya.propose_yield_aside(
        robot_xy=(0.0, 0.0),
        owner_xy=(3.4, 0.0),
        tracks=tracks,
        limits=_limits(),
        free_range_m=lambda _bearing, _span: float("nan"),
    )
    assert garbage.active is False


def test_malformed_inputs_raise_loudly() -> None:
    limits = _limits()
    with pytest.raises(ValueError):
        ya.propose_yield_aside(
            robot_xy=(0.0, float("nan")),
            owner_xy=(3.4, 0.0),
            tracks=(),
            limits=limits,
            free_range_m=_open_scan,
        )
    with pytest.raises(ValueError):
        ya.propose_yield_aside(
            robot_xy=(0.0, 0.0),
            owner_xy=(3.4, 0.0),
            tracks=(),
            limits=limits,
            free_range_m=_open_scan,
            latched_side=2,
        )
    with pytest.raises(TypeError):
        ya.propose_yield_aside(
            robot_xy=(0.0, 0.0),
            owner_xy=(3.4, 0.0),
            tracks=(),
            limits={"desired_distance_m": 1.85},
            free_range_m=_open_scan,
        )
    with pytest.raises(ValueError):
        ya.corridor_min_clearance(
            (0.0, 0.0),
            (1.0, 0.0),
            (),
            speed_mps=0.0,
            horizon_s=1.0,
            step_s=0.1,
            resolution_m=0.1,
        )


# ---------------------------------------------------------------------------
# (a) the distance law: |aim - owner| == desired, exactly
# ---------------------------------------------------------------------------


def _random_case(rng: random.Random) -> tuple[tuple[float, float], tuple[float, float], list]:
    owner = (rng.uniform(-20.0, 20.0), rng.uniform(-20.0, 20.0))
    bearing = rng.uniform(-math.pi, math.pi)
    lag = rng.uniform(1.75, 6.0)
    robot = (owner[0] + lag * math.cos(bearing), owner[1] + lag * math.sin(bearing))
    tracks = []
    for _ in range(rng.randint(1, 6)):
        along = rng.uniform(0.2, 1.0)
        lateral = rng.uniform(-2.5, 2.5)
        base_x = robot[0] + (owner[0] - robot[0]) * along
        base_y = robot[1] + (owner[1] - robot[1]) * along
        normal = bearing + math.pi / 2.0
        tracks.append(
            TrackState(
                x=base_x + lateral * math.cos(normal),
                y=base_y + lateral * math.sin(normal),
                vx=rng.uniform(-1.2, 1.2),
                vy=rng.uniform(-1.2, 1.2),
                radius_m=rng.choice((0.2, 0.35)),
            )
        )
    return robot, owner, tracks


def _active_proposals(seed: int, cases: int) -> list[tuple[ya.YieldAsideProposal, tuple, tuple, list]]:
    rng = random.Random(seed)
    found = []
    for _ in range(cases):
        robot, owner, tracks = _random_case(rng)
        proposal = ya.propose_yield_aside(
            robot_xy=robot,
            owner_xy=owner,
            tracks=tracks,
            limits=_limits(),
            free_range_m=_open_scan,
        )
        if proposal.active:
            found.append((proposal, robot, owner, tracks))
    return found


def test_active_aims_sit_exactly_on_the_follow_circle() -> None:
    active = _active_proposals(seed=20260811, cases=400)
    assert len(active) >= 20, "randomized sweep produced too few active proposals to test"
    desired = _limits().desired_distance_m
    for proposal, _robot, _owner, _tracks in active:
        assert math.hypot(proposal.aim_dx_m, proposal.aim_dy_m) == desired
        assert proposal.side in (-1, 1)
        assert proposal.offset_m in _limits().offsets_m


def test_circle_offset_is_exact_over_many_bearings() -> None:
    radius = _limits().desired_distance_m
    rng = random.Random(4242)
    for _ in range(2000):
        bearing = rng.uniform(-math.pi, math.pi)
        offset = ya.circle_offset(bearing, radius)
        assert offset is not None
        assert math.hypot(*offset) == radius
        # The bearing correction is at most one ULP of the radius.
        assert abs(math.atan2(offset[1], offset[0]) - bearing) < 1e-12


# ---------------------------------------------------------------------------
# (c) no candidate ever samples inside the person stop ring
# ---------------------------------------------------------------------------


def _person_stop_violations(proposals: list, limits: ya.YieldAsideLimits) -> list[float]:
    violations = []
    for proposal, robot, owner, tracks in proposals:
        aim = (owner[0] + proposal.aim_dx_m, owner[1] + proposal.aim_dy_m)
        stance = ya.predicted_stance(
            robot,
            aim,
            desired_distance_m=limits.desired_distance_m,
            deadband_m=limits.deadband_m,
        )
        clearance = ya.corridor_min_clearance(
            robot,
            stance,
            tracks,
            speed_mps=limits.max_vx_mps,
            horizon_s=limits.horizon_s,
            step_s=limits.rollout_step_s,
            resolution_m=ya.MEANINGFUL_IMPROVEMENT_M,
        )
        if clearance < limits.person_stop_m:
            violations.append(clearance)
    return violations


def test_no_proposal_samples_inside_the_person_stop_ring() -> None:
    limits = _limits()
    active = _active_proposals(seed=99001, cases=400)
    assert len(active) >= 20
    assert _person_stop_violations(active, limits) == []


def test_person_stop_checker_catches_a_seeded_violation() -> None:
    """SEEDED VIOLATION: the same checker over a proposer with the reject removed."""

    limits = _limits()
    rng = random.Random(99001)
    unguarded = []
    for _ in range(400):
        robot, owner, tracks = _random_case(rng)
        bearing = math.atan2(robot[1] - owner[1], robot[0] - owner[0])
        offset = limits.offsets_m[-1]
        rotation = math.asin(offset / limits.desired_distance_m)
        vector = ya.circle_offset(bearing + rotation, limits.desired_distance_m)
        if vector is None:  # pragma: no cover - budget never exhausted in practice
            continue
        unguarded.append(
            (
                ya.YieldAsideProposal(
                    active=True,
                    reason=ya.ACTIVE_REASON,
                    side=1,
                    offset_m=offset,
                    aim_dx_m=vector[0],
                    aim_dy_m=vector[1],
                ),
                robot,
                owner,
                tracks,
            )
        )
    assert _person_stop_violations(unguarded, limits), (
        "the person-stop checker passed a proposer that never applied the reject"
    )


# ---------------------------------------------------------------------------
# (h) the lagging-regime stall guard
# ---------------------------------------------------------------------------


def _stall_violations(proposals: list, limits: ya.YieldAsideLimits) -> list[tuple[float, float]]:
    violations = []
    for proposal, robot, owner, _tracks in proposals:
        lag = math.hypot(robot[0] - owner[0], robot[1] - owner[1])
        if lag <= limits.hold_ring_m:
            continue
        aim = (owner[0] + proposal.aim_dx_m, owner[1] + proposal.aim_dy_m)
        reach = math.hypot(aim[0] - robot[0], aim[1] - robot[1])
        if reach <= limits.hold_ring_m:
            violations.append((lag, reach))
    return violations


def test_stall_guard_holds_over_randomized_geometries() -> None:
    limits = _limits()
    active = _active_proposals(seed=777001, cases=400)
    assert len(active) >= 20
    assert _stall_violations(active, limits) == []


def test_stall_guard_checker_catches_a_seeded_violation() -> None:
    """SEEDED VIOLATION: the same checker over a proposer with the guard removed."""

    limits = _limits()
    rng = random.Random(777001)
    unguarded = []
    for _ in range(400):
        robot, owner, tracks = _random_case(rng)
        bearing = math.atan2(robot[1] - owner[1], robot[0] - owner[0])
        offset = limits.offsets_m[2]
        rotation = math.asin(offset / limits.desired_distance_m)
        vector = ya.circle_offset(bearing + rotation, limits.desired_distance_m)
        if vector is None:  # pragma: no cover
            continue
        unguarded.append(
            (
                ya.YieldAsideProposal(
                    active=True,
                    reason=ya.ACTIVE_REASON,
                    side=1,
                    offset_m=offset,
                    aim_dx_m=vector[0],
                    aim_dy_m=vector[1],
                ),
                robot,
                owner,
                tracks,
            )
        )
    assert _stall_violations(unguarded, limits), (
        "the stall checker passed a proposer that never applied the guard"
    )


def test_canned_skeptic_case_is_rejected() -> None:
    """The skeptic's worked example: lag 2.77 m, offset 0.6 m -> |robot-aim| 1.18 m.

    The proposer must never emit that aim; the law would report
    'at_follow_distance' and freeze a chase that was 0.92 m behind its band.
    """

    limits = _limits()
    robot = (0.0, 0.0)
    owner = (2.77, 0.0)
    # The geometry the skeptic priced, re-derived here rather than asserted.
    rotation = math.asin(0.6 / limits.desired_distance_m)
    aim_x = owner[0] - limits.desired_distance_m * math.cos(rotation)
    aim_y = limits.desired_distance_m * math.sin(rotation)
    assert math.hypot(aim_x - robot[0], aim_y - robot[1]) == pytest.approx(1.183, abs=0.005)
    assert math.hypot(aim_x - robot[0], aim_y - robot[1]) < limits.hold_ring_m

    tracks = (
        TrackState(x=1.6, y=0.0, vx=0.0, vy=0.0, radius_m=0.2),
        TrackState(x=2.2, y=1.1, vx=0.0, vy=0.0, radius_m=0.2),
    )
    proposal = ya.propose_yield_aside(
        robot_xy=robot,
        owner_xy=owner,
        tracks=tracks,
        limits=limits,
        free_range_m=_open_scan,
    )
    if proposal.active:
        reach = math.hypot(
            owner[0] + proposal.aim_dx_m - robot[0],
            owner[1] + proposal.aim_dy_m - robot[1],
        )
        assert reach > limits.hold_ring_m
        assert proposal.offset_m != pytest.approx(0.6, abs=0.09)


def test_the_aside_never_translates_a_robot_inside_the_follow_distance() -> None:
    """Non-lagging regime: no candidate may start a chase from inside the band."""

    limits = _limits()
    rng = random.Random(5150)
    for _ in range(200):
        owner = (rng.uniform(-5.0, 5.0), rng.uniform(-5.0, 5.0))
        bearing = rng.uniform(-math.pi, math.pi)
        close = rng.uniform(0.2, limits.hold_ring_m)
        robot = (owner[0] + close * math.cos(bearing), owner[1] + close * math.sin(bearing))
        tracks = [
            TrackState(
                x=owner[0] + rng.uniform(-3.0, 3.0),
                y=owner[1] + rng.uniform(-3.0, 3.0),
                vx=rng.uniform(-1.0, 1.0),
                vy=rng.uniform(-1.0, 1.0),
                radius_m=0.2,
            )
            for _ in range(rng.randint(1, 4))
        ]
        proposal = ya.propose_yield_aside(
            robot_xy=robot,
            owner_xy=owner,
            tracks=tracks,
            limits=limits,
            free_range_m=_open_scan,
        )
        if not proposal.active:
            continue
        aim = (owner[0] + proposal.aim_dx_m, owner[1] + proposal.aim_dy_m)
        stance = ya.predicted_stance(
            robot,
            aim,
            desired_distance_m=limits.desired_distance_m,
            deadband_m=limits.deadband_m,
        )
        assert stance == (robot[0], robot[1])


# ---------------------------------------------------------------------------
# (g) the closed-loop equilibrium property, under the verified law
# ---------------------------------------------------------------------------


def _closed_loop(
    robot: tuple[float, float, float],
    owner: tuple[float, float],
    tracks: list,
    limits: ya.YieldAsideLimits,
    *,
    aim_fn,
    ticks: int = 400,
) -> tuple[float, float]:
    """Run the real ``_step_direct`` law to its fixed point.

    Returns ``(minimum owner distance over the rollout, terminal owner distance)``.
    """

    controller = FollowOwnerController(FollowConfig())
    controller.start("direct")
    x, y, yaw = robot
    minimum = math.hypot(x - owner[0], y - owner[1])
    settled = 0
    for tick in range(ticks):
        now = tick * CONTROL_DT_S
        aim = aim_fn((x, y), owner, tracks)
        decision = controller.step(_observation((x, y, yaw), aim, now), now=now)
        command = decision.command
        x += command.vx * math.cos(yaw) * CONTROL_DT_S
        y += command.vx * math.sin(yaw) * CONTROL_DT_S
        yaw += command.vyaw * CONTROL_DT_S
        minimum = min(minimum, math.hypot(x - owner[0], y - owner[1]))
        # The fixed point IS a standstill: once the law emits nothing for two
        # seconds the state cannot move again (the owner is stationary), so the
        # remaining ticks would re-derive the same pose.
        settled = settled + 1 if command == type(command)() else 0
        if settled >= 20:
            break
    return minimum, math.hypot(x - owner[0], y - owner[1])


def _proposed_aim(robot, owner, tracks):
    proposal = ya.propose_yield_aside(
        robot_xy=robot,
        owner_xy=owner,
        tracks=tracks,
        limits=_limits(),
        free_range_m=_open_scan,
    )
    if not proposal.active:
        return owner
    return (proposal.aim_x_m, proposal.aim_y_m)


def _rogue_aim(robot, owner, tracks):
    """A proposer that ignores the offset cap — the seeded equilibrium violation."""

    limits = _limits()
    bearing = math.atan2(robot[1] - owner[1], robot[0] - owner[0])
    vector = ya.circle_offset(bearing + 1.5, limits.desired_distance_m)
    assert vector is not None
    return (owner[0] + vector[0], owner[1] + vector[1])


def test_closed_loop_equilibrium_clears_the_owner_keepout() -> None:
    limits = _limits()
    rng = random.Random(31337)
    active_cases = 0
    for _ in range(60):
        robot_xy, owner, tracks = _random_case(rng)
        start = (robot_xy[0], robot_xy[1], rng.uniform(-math.pi, math.pi))
        proposal = ya.propose_yield_aside(
            robot_xy=robot_xy,
            owner_xy=owner,
            tracks=tracks,
            limits=limits,
            free_range_m=_open_scan,
        )
        active_cases += int(proposal.active)
        minimum, terminal = _closed_loop(start, owner, tracks, limits, aim_fn=_proposed_aim)
        assert minimum >= limits.owner_keepout_m, (
            f"rollout entered the owner keepout: {minimum:.3f} m"
        )
        assert terminal >= limits.owner_keepout_m
    assert active_cases >= 5, "the equilibrium sweep never exercised an active proposal"


def test_closed_loop_checker_catches_a_seeded_equilibrium_violation() -> None:
    """SEEDED VIOLATION (arm 2 of 2): the same rollout over an uncapped proposer."""

    limits = _limits()
    rng = random.Random(31337)
    breaches = 0
    for _ in range(30):
        robot_xy, owner, tracks = _random_case(rng)
        start = (robot_xy[0], robot_xy[1], rng.uniform(-math.pi, math.pi))
        minimum, _terminal = _closed_loop(start, owner, tracks, limits, aim_fn=_rogue_aim)
        breaches += int(minimum < limits.owner_keepout_m)
    assert breaches > 0, "the closed-loop checker never flagged the uncapped proposer"


def test_unyielded_law_equilibrates_on_the_hold_ring() -> None:
    """Control arm: with no aside the same rollout parks on ``desired + deadband``."""

    limits = _limits()
    minimum, terminal = _closed_loop(
        (0.0, 0.0, 0.0),
        (5.0, 0.0),
        [],
        limits,
        aim_fn=lambda _robot, owner, _tracks: owner,
    )
    assert terminal == pytest.approx(limits.hold_ring_m, abs=0.05)
    assert minimum >= limits.owner_keepout_m


# ---------------------------------------------------------------------------
# (e) determinism and (f) the asymmetric exit
# ---------------------------------------------------------------------------


def test_identical_inputs_give_bit_identical_proposals() -> None:
    rng = random.Random(60613)
    for _ in range(50):
        robot, owner, tracks = _random_case(rng)
        first = ya.propose_yield_aside(
            robot_xy=robot,
            owner_xy=owner,
            tracks=tracks,
            limits=_limits(),
            free_range_m=_open_scan,
        )
        second = ya.propose_yield_aside(
            robot_xy=robot,
            owner_xy=owner,
            tracks=list(tracks),
            limits=_limits(),
            free_range_m=_open_scan,
        )
        assert first == second
        assert repr(first) == repr(second)


def test_asymmetric_exit_holds_below_the_band_and_releases_at_it() -> None:
    limits = _limits()
    robot = (0.0, 0.0)
    owner = (3.4, 0.0)
    # A crossing stranger close enough that the un-offset path is inside the
    # comfort band: entering costs the improvement quantum, holding does not.
    tracks = (TrackState(x=2.0, y=-1.6, vx=0.0, vy=0.5, radius_m=0.2),)
    entered = ya.propose_yield_aside(
        robot_xy=robot,
        owner_xy=owner,
        tracks=tracks,
        limits=limits,
        free_range_m=_open_scan,
    )
    assert entered.active
    assert entered.improvement_m >= ya.MEANINGFUL_IMPROVEMENT_M
    assert entered.baseline_clearance_m < limits.person_slow_m

    # Same geometry, engaged: still held (the un-offset path is still banded).
    held = ya.propose_yield_aside(
        robot_xy=robot,
        owner_xy=owner,
        tracks=tracks,
        limits=limits,
        free_range_m=_open_scan,
        latched_side=entered.side,
        engaged=True,
    )
    assert held.active and held.side == entered.side

    # The stranger is now far outside the comfort band: engaged RELEASES, and
    # an unengaged caller would not have entered either.
    far = (TrackState(x=2.0, y=-9.0, vx=0.0, vy=0.0, radius_m=0.2),)
    released = ya.propose_yield_aside(
        robot_xy=robot,
        owner_xy=owner,
        tracks=far,
        limits=limits,
        free_range_m=_open_scan,
        latched_side=entered.side,
        engaged=True,
    )
    assert (released.active, released.reason) == (False, "clearance_recovered")
    assert released.baseline_clearance_m >= limits.person_slow_m
    fresh = ya.propose_yield_aside(
        robot_xy=robot,
        owner_xy=owner,
        tracks=far,
        limits=limits,
        free_range_m=_open_scan,
    )
    assert fresh.active is False


def test_engaged_holds_an_aside_that_no_longer_clears_the_entry_quantum() -> None:
    """The asymmetry itself: entry needs the quantum, holding needs only parity."""

    limits = _limits()
    robot = (0.0, 0.0)
    owner = (3.4, 0.0)
    rng = random.Random(8191)
    found = False
    for _ in range(400):
        tracks = [
            TrackState(
                x=rng.uniform(0.5, 3.0),
                y=rng.uniform(-2.5, 2.5),
                vx=rng.uniform(-0.8, 0.8),
                vy=rng.uniform(-0.8, 0.8),
                radius_m=0.2,
            )
            for _ in range(rng.randint(1, 3))
        ]
        fresh = ya.propose_yield_aside(
            robot_xy=robot,
            owner_xy=owner,
            tracks=tracks,
            limits=limits,
            free_range_m=_open_scan,
        )
        engaged = ya.propose_yield_aside(
            robot_xy=robot,
            owner_xy=owner,
            tracks=tracks,
            limits=limits,
            free_range_m=_open_scan,
            engaged=True,
        )
        if (not fresh.active) and engaged.active:
            assert engaged.baseline_clearance_m < limits.person_slow_m
            assert 0.0 <= engaged.improvement_m < ya.MEANINGFUL_IMPROVEMENT_M
            found = True
            break
    assert found, "no geometry exercised the hold-but-would-not-enter arm"


def test_latched_side_breaks_an_exact_tie(monkeypatch) -> None:
    """Mirror geometries tie only to ~1 ULP, so the tie is CONSTRUCTED here.

    With every candidate scoring identically the ranking must fall through to
    the documented order: smallest offset, then the caller's latched side.
    """

    limits = _limits()
    robot = (0.0, 0.0)
    owner = (3.4, 0.0)
    baseline_stance = ya.predicted_stance(
        robot,
        owner,
        desired_distance_m=limits.desired_distance_m,
        deadband_m=limits.deadband_m,
    )
    real_clearance = ya.corridor_min_clearance

    def tied(start, end, tracks, **kwargs):
        if end == baseline_stance:
            return 0.4
        return 1.4

    monkeypatch.setattr(ya, "corridor_min_clearance", tied)
    tracks = (TrackState(x=1.9, y=0.0, vx=0.0, vy=0.0, radius_m=0.2),)
    left = ya.propose_yield_aside(
        robot_xy=robot,
        owner_xy=owner,
        tracks=tracks,
        limits=limits,
        free_range_m=_open_scan,
        latched_side=1,
    )
    right = ya.propose_yield_aside(
        robot_xy=robot,
        owner_xy=owner,
        tracks=tracks,
        limits=limits,
        free_range_m=_open_scan,
        latched_side=-1,
    )
    unlatched = ya.propose_yield_aside(
        robot_xy=robot,
        owner_xy=owner,
        tracks=tracks,
        limits=limits,
        free_range_m=_open_scan,
    )
    assert left.active and right.active and unlatched.active
    assert (left.side, right.side, unlatched.side) == (1, -1, 1)
    assert left.offset_m == right.offset_m == unlatched.offset_m
    # The winner is the smallest offset the stall guard admits, not the largest.
    admissible = [
        offset
        for offset in limits.offsets_m
        if math.hypot(
            owner[0]
            - limits.desired_distance_m * math.cos(math.asin(offset / limits.desired_distance_m)),
            limits.desired_distance_m * math.sin(math.asin(offset / limits.desired_distance_m)),
        )
        > limits.hold_ring_m
    ]
    assert left.offset_m == min(admissible)
    assert ya.corridor_min_clearance is not real_clearance  # patch actually applied


def test_clearance_outranks_the_latch() -> None:
    """An asymmetric stream picks the side; the latch cannot override clearance.

    Note the sign convention (also stated on :class:`YieldAsideProposal`): the
    controller parks on the FAR side of the aim, so an aim rotated ``+1``
    displaces the robot's stance the other way. The assertion below is written
    on the STANCE, which is the thing that has to end up away from the stream.
    """

    limits = _limits()
    robot = (0.0, 0.0)
    owner = (3.4, 0.0)
    one_sided = (TrackState(x=1.9, y=1.2, vx=0.0, vy=0.0, radius_m=0.2),)
    for latch in (0, 1, -1):
        proposal = ya.propose_yield_aside(
            robot_xy=robot,
            owner_xy=owner,
            tracks=one_sided,
            limits=limits,
            free_range_m=_open_scan,
            latched_side=latch,
        )
        assert proposal.active
        stance = ya.predicted_stance(
            robot,
            (owner[0] + proposal.aim_dx_m, owner[1] + proposal.aim_dy_m),
            desired_distance_m=limits.desired_distance_m,
            deadband_m=limits.deadband_m,
        )
        assert stance[1] < 0.0, "the stance stayed on the stranger's side of the lane"
        assert proposal.aside_clearance_m > proposal.baseline_clearance_m


# ---------------------------------------------------------------------------
# corridor_min_clearance: the space-time minimum and its SB-1 resolution
# ---------------------------------------------------------------------------


def test_corridor_min_clearance_is_a_space_time_minimum() -> None:
    # The robot parks at (0.5, 0) after ~1.4 s; the stranger arrives there at
    # t = 3 s. A snapshot at t = 0 calls this 2.8 m clear; the rollout does not.
    tracks = (TrackState(x=0.5, y=3.0, vx=0.0, vy=-1.0, radius_m=0.2),)
    clearance = ya.corridor_min_clearance(
        (0.0, 0.0),
        (0.5, 0.0),
        tracks,
        speed_mps=0.35,
        horizon_s=7.0,
        step_s=0.28,
        resolution_m=0.1,
    )
    assert clearance < 0.0
    assert math.hypot(0.5 - 0.0, 3.0 - 0.0) - 0.2 > 2.8


def test_planar_free_range_reads_a_corridor_not_a_needle() -> None:
    """One blocked ray inside the footprint window must block the bearing."""

    rays = [30.0] * 360
    increment = 2.0 * math.pi / 360.0
    scan = {
        "angle_min_rad": -math.pi,
        "angle_increment_rad": increment,
        "range_max_m": 30.0,
        "robot_yaw_rad": 0.0,
        "span_m": 2.0,
    }
    assert ya.planar_free_range(rays, bearing_rad=0.0, **scan) == 30.0
    # A pole one degree off the bearing is inside the footprint corridor at 2 m.
    blocked = list(rays)
    blocked[181] = 1.1
    assert ya.planar_free_range(blocked, bearing_rad=0.0, **scan) == 1.1
    # The window is the half-angle the footprint (0.32 m) subtends at the far
    # end of the path: 9.2 deg at a 2 m span, 0.61 deg at 30 m. So the same
    # 1-degree-off pole falls OUTSIDE the window of a 30 m query.
    assert ya.planar_free_range(blocked, bearing_rad=0.0, **{**scan, "span_m": 30.0}) == 30.0
    assert math.degrees(
        math.asin(DEFAULT_SAFETY_ENVELOPE.footprint_radius_m / 2.0)
    ) == pytest.approx(9.21, abs=0.01)


def test_planar_free_range_fails_closed_on_an_unobserved_bearing() -> None:
    increment = 2.0 * math.pi / 36.0
    empty = ya.planar_free_range(
        [],
        angle_min_rad=-math.pi,
        angle_increment_rad=increment,
        range_max_m=30.0,
        robot_yaw_rad=0.0,
        bearing_rad=0.0,
        span_m=2.0,
    )
    assert empty == 0.0
    dropouts = ya.planar_free_range(
        [float("nan")] * 36,
        angle_min_rad=-math.pi,
        angle_increment_rad=increment,
        range_max_m=30.0,
        robot_yaw_rad=0.0,
        bearing_rad=0.0,
        span_m=2.0,
    )
    assert dropouts == 0.0
    no_returns = ya.planar_free_range(
        [math.inf] * 36,
        angle_min_rad=-math.pi,
        angle_increment_rad=increment,
        range_max_m=30.0,
        robot_yaw_rad=0.0,
        bearing_rad=0.0,
        span_m=2.0,
    )
    assert no_returns == 30.0


def test_planar_free_range_is_body_relative() -> None:
    rays = [30.0] * 36
    rays[27] = 0.8  # +pi/2 in body frame (index 27 -> angle_min + 27*increment)
    increment = 2.0 * math.pi / 36.0
    common = {
        "angle_min_rad": -math.pi,
        "angle_increment_rad": increment,
        "range_max_m": 30.0,
        "span_m": 1.0,
    }
    # Robot facing world +x: the blocked ray is world bearing +pi/2.
    assert ya.planar_free_range(rays, robot_yaw_rad=0.0, bearing_rad=math.pi / 2.0, **common) == 0.8
    # Rotate the robot by +pi/2: the same ray now covers world bearing pi.
    assert ya.planar_free_range(
        rays, robot_yaw_rad=math.pi / 2.0, bearing_rad=math.pi, **common
    ) == 0.8


def test_corridor_min_clearance_no_tracks_is_infinite() -> None:
    assert (
        ya.corridor_min_clearance(
            (0.0, 0.0),
            (1.0, 1.0),
            (),
            speed_mps=0.35,
            horizon_s=7.0,
            step_s=0.28,
            resolution_m=0.1,
        )
        == math.inf
    )


def test_corridor_min_clearance_resolution_bounds_the_sampling_error() -> None:
    """SB-1: a 9 m/s crosser cannot fall between samples, whatever ``step_s`` says."""

    tracks = (TrackState(x=0.3, y=6.0, vx=0.0, vy=-9.0, radius_m=0.2),)
    arguments = {
        "speed_mps": 0.35,
        "horizon_s": 7.0,
        "resolution_m": ya.MEANINGFUL_IMPROVEMENT_M,
    }
    fine = ya.corridor_min_clearance(
        (0.0, 0.0), (2.0, 0.0), tracks, step_s=0.001, **arguments
    )
    coarse = ya.corridor_min_clearance(
        (0.0, 0.0), (2.0, 0.0), tracks, step_s=5.0, **arguments
    )
    # The documented bound: the sampled minimum may overestimate the true one
    # by at most half the resolution, so two admissible grids agree to that.
    assert abs(coarse - fine) <= ya.MEANINGFUL_IMPROVEMENT_M / 2.0
    assert fine < ya.MEANINGFUL_IMPROVEMENT_M  # the crosser really does sweep the path

    # Without the cap, sampling on the requested 5 s grid misses the crossing
    # entirely — this is the defect the SB-1 rule exists for.
    naive = min(
        math.hypot(0.35 * t - 0.3, 6.0 - 9.0 * t) - 0.2
        for t in (0.0, 5.0)
    )
    assert naive > 1.0
