"""Card R10 item 5: orbit feasibility, and the honesty obligation it carries.

Once ``circle_owner`` exists on the hosted surface, "I can't walk around you
here" has to be TRUE when said and must not be said when false. The bench caught
the hosted model failing that in both directions — fabricating capability
(``navigate_to("with owner")``) and denying it (*"I can't do a full circle
around you with the controls I have right now"*, which was simply untrue). So
this file pins BOTH directions:

* a blocked ring refuses, names the arc, and produces a sentence with a reason;
* a clear ring — and, critically, a ring the reactive gate would merely SLOW
  through — does not refuse. A false refusal is the same dishonesty as a false
  claim, and the first draft of this validator shipped one (see R10_STATUS §3).
"""

from __future__ import annotations

import math

import pytest

from parcel_robot.authority import DEFAULT_SAFETY_ENVELOPE
from parcel_robot.backends.base import (
    DynamicAgentTrack,
    LidarObstacle,
    OwnerTrack,
    RobotPose,
    SimObservation,
)
from parcel_robot.models import SpatialIntent
from parcel_robot.navigation.orbit_feasibility import (
    CAUSE_BLOCKED,
    CAUSE_NO_CENTRE,
    CAUSE_RADIUS,
    evaluate_orbit_annulus,
)
from parcel_robot.navigation.spatial import SpatialBehaviorConfig, SpatialBehaviorController

CLEARANCE = DEFAULT_SAFETY_ENVELOPE.footprint_radius_m + 0.10


# ================================================================== the ring
def test_an_empty_ring_is_feasible() -> None:
    verdict = evaluate_orbit_annulus(
        centre=(0.0, 0.0), radius_m=1.6, clearance_m=CLEARANCE
    )
    assert verdict.feasible is True
    assert verdict.blocked == ()
    assert verdict.refusal_sentence() == ""


def test_a_wall_on_one_side_blocks_that_arc_and_only_that_arc() -> None:
    # A short run of surfaces sitting exactly on the ring at bearing ~0 deg.
    wall = tuple(("desk", 1.6, offset) for offset in (-0.2, 0.0, 0.2))
    verdict = evaluate_orbit_annulus(
        centre=(0.0, 0.0), radius_m=1.6, clearance_m=CLEARANCE, blocked_points=wall
    )
    assert verdict.feasible is False
    assert verdict.cause == CAUSE_BLOCKED
    assert verdict.blocked, "an infeasible verdict must always name an arc"
    arc = verdict.worst
    assert arc is not None
    assert arc.label == "desk"
    assert arc.width_deg < 180.0, "one desk must not blank the whole ring"
    # The arc really is the side the desk is on.
    assert min(abs(arc.mid_deg), abs(arc.mid_deg - 360.0)) < 45.0


def test_a_person_disc_blocks_the_ring_at_any_clearance() -> None:
    verdict = evaluate_orbit_annulus(
        centre=(0.0, 0.0),
        radius_m=1.6,
        clearance_m=0.0,
        keepouts=(("someone", 0.0, 1.6, 0.5),),
    )
    assert verdict.feasible is False
    assert verdict.worst is not None
    assert verdict.worst.label == "someone"


def test_the_refusal_names_the_side_relative_to_the_owner() -> None:
    """"on your left" must mean the OWNER's left, not the map's."""

    # Blocker due north of the owner; robot due east, so north is the owner's
    # left when they are looking at the robot.
    verdict = evaluate_orbit_annulus(
        centre=(0.0, 0.0),
        radius_m=1.6,
        clearance_m=CLEARANCE,
        blocked_points=(("a planter", 0.0, 1.6),),
    )
    sentence = verdict.refusal_sentence(reference_deg=0.0)
    assert "a planter" in sentence
    assert "on your left" in sentence


def test_a_refusal_without_a_reference_drops_the_side_rather_than_inventing_one() -> None:
    verdict = evaluate_orbit_annulus(
        centre=(0.0, 0.0),
        radius_m=1.6,
        clearance_m=CLEARANCE,
        blocked_points=(("a planter", 0.0, 1.6),),
    )
    sentence = verdict.refusal_sentence(reference_deg=None)
    assert "a planter" in sentence
    for side in ("left", "right", "behind you", "in front of you"):
        assert side not in sentence


def test_bad_geometry_is_a_verdict_and_never_an_exception() -> None:
    """An admission check that raised would take down the call asking it."""

    assert evaluate_orbit_annulus(centre=None, radius_m=1.6, clearance_m=0.4).cause == (
        CAUSE_NO_CENTRE
    )
    assert evaluate_orbit_annulus(
        centre=(0.0, 0.0), radius_m=float("nan"), clearance_m=0.4
    ).cause == CAUSE_RADIUS
    assert evaluate_orbit_annulus(
        centre=(0.0, 0.0), radius_m=-1.0, clearance_m=0.4
    ).cause == CAUSE_RADIUS


def test_only_the_requested_arc_is_sampled() -> None:
    """A half-lap must not be refused for something behind the robot."""

    behind = (("bin", -1.6, 0.0),)
    whole = evaluate_orbit_annulus(
        centre=(0.0, 0.0), radius_m=1.6, clearance_m=CLEARANCE, blocked_points=behind
    )
    ahead_only = evaluate_orbit_annulus(
        centre=(0.0, 0.0),
        radius_m=1.6,
        clearance_m=CLEARANCE,
        blocked_points=behind,
        arc_start_deg=0.0,
        arc_sweep_deg=90.0,
    )
    assert whole.feasible is False
    assert ahead_only.feasible is True


# =============================================== admission + mid-orbit, wired
def _observation(
    *,
    robot: tuple[float, float] = (1.6, 0.0),
    lidar: tuple[LidarObstacle, ...] = (),
    agents: tuple[DynamicAgentTrack, ...] = (),
) -> SimObservation:
    return SimObservation(
        timestamp=0.0,
        robot=RobotPose(x=robot[0], y=robot[1], yaw=math.pi / 2.0),
        owner=OwnerTrack(x=0.0, y=0.0, visible=True, confidence=0.95),
        lidar_obstacles=lidar,
        dynamic_agents=agents,
    )


def _controller() -> SpatialBehaviorController:
    return SpatialBehaviorController(SpatialBehaviorConfig())


ORBIT = SpatialIntent("orbit_owner", "counterclockwise", size="normal", revolutions=1.0)


def test_admission_passes_when_there_is_room() -> None:
    verdict = _controller().assess_orbit(ORBIT, _observation(), obstacle_stop_m=0.65)
    assert verdict.feasible is True


def _lidar_at(point: tuple[float, float], *, label: str) -> LidarObstacle:
    """A LiDAR return for a surface at ``point``, seen from the robot at (1.6, 0).

    Mirrors the contract the lift in ``spatial._surface_points`` inverts: the
    reported ``distance_m`` is FOOTPRINT-to-surface, not centre range.
    """

    robot = (1.6, 0.0)
    yaw = math.pi / 2.0
    dx, dy = point[0] - robot[0], point[1] - robot[1]
    return LidarObstacle(
        distance_m=math.hypot(dx, dy) - DEFAULT_SAFETY_ENVELOPE.footprint_radius_m,
        bearing_rad=math.atan2(dy, dx) - yaw,
        obstacle_id=label,
    )


def test_admission_does_not_refuse_for_a_surface_the_gate_would_only_slow_for() -> None:
    """The false-refusal regression at the CONTROLLER, through its own clearance.

    Same claim as the annulus-level test above, but routed through
    ``_ring_clearance_m``, so swapping the body-fit distance back to the reactive
    gate's braking distance reddens HERE. The bollard sits 0.50 m from the ring
    point at bearing 90°: outside the 0.42 m fit clearance, well inside the
    ~1.12 m brake distance.
    """

    bollard = (_lidar_at((0.0, 2.1), label="bollard"),)
    verdict = _controller().assess_orbit(
        ORBIT, _observation(lidar=bollard), obstacle_stop_m=0.65
    )
    assert verdict.feasible is True, "a slowdown is not an impossibility"


def test_admission_refuses_a_surface_the_body_genuinely_cannot_clear() -> None:
    """…and the same path still says no when the body truly does not fit."""

    kerbstone = (_lidar_at((0.0, 1.9), label="kerbstone"),)
    verdict = _controller().assess_orbit(
        ORBIT, _observation(lidar=kerbstone), obstacle_stop_m=0.65
    )
    assert verdict.feasible is False
    assert verdict.cause == CAUSE_BLOCKED


def test_admission_refuses_with_a_sentence_when_the_owner_is_boxed_in() -> None:
    """The owner's scenario 3, answered by geometry rather than by the model."""

    controller = _controller()
    # A ring of people all around the owner at the orbit radius.
    agents = tuple(
        DynamicAgentTrack(
            agent_id=f"p{index}",
            kind="person",
            x=1.6 * math.cos(math.radians(index * 30.0)),
            y=1.6 * math.sin(math.radians(index * 30.0)),
            vx=0.0,
            vy=0.0,
            radius_m=0.5,
        )
        for index in range(12)
    )
    verdict = controller.assess_orbit(ORBIT, _observation(agents=agents), obstacle_stop_m=0.65)
    assert verdict.feasible is False
    assert verdict.cause == CAUSE_BLOCKED
    sentence = controller.last_refusal_sentence
    assert sentence, "a refusal that says nothing is the defect this card closes"
    assert "walk around you" in sentence


def test_admission_refuses_when_the_owner_is_not_tracked() -> None:
    observation = SimObservation(
        timestamp=0.0,
        robot=RobotPose(x=1.6, y=0.0),
        owner=OwnerTrack(x=0.0, y=0.0, visible=False, confidence=0.0),
    )
    verdict = _controller().assess_orbit(ORBIT, observation, obstacle_stop_m=0.65)
    assert verdict.feasible is False
    assert verdict.cause == CAUSE_NO_CENTRE
    assert "lost track of where you are" in _controller().assess_orbit(
        ORBIT, observation, obstacle_stop_m=0.65
    ).refusal_sentence()


def test_the_owners_own_body_is_never_counted_as_the_thing_blocking_the_ring() -> None:
    """Otherwise every orbit ever requested would be refused.

    The disc is deliberately BIGGER than the orbit radius. That is what makes
    this test able to fail: a normal 0.35 m owner never reaches a 1.6 m ring, so
    a version of this test using one would pass with the owner exclusion deleted
    and pin nothing. Merged or mis-sized detections are real — perception folding
    the owner and the thing they are holding into one fat track is exactly when
    a missing exclusion would refuse every circle the owner ever asks for.
    """

    fat_owner_blob = (
        DynamicAgentTrack(
            agent_id="owner", kind="person", x=0.0, y=0.0, vx=0.0, vy=0.0, radius_m=1.9
        ),
    )
    verdict = _controller().assess_orbit(
        ORBIT, _observation(agents=fat_owner_blob), obstacle_stop_m=0.65
    )
    assert verdict.feasible is True


def test_a_surface_the_gate_would_merely_slow_for_does_not_refuse_the_orbit() -> None:
    """The false-refusal regression, pinned. See R10_STATUS §3.

    A bollard 0.50 m from the ring is well outside the body-fit clearance
    (footprint 0.32 + margin 0.10 = 0.42 m) and well inside the reactive gate's
    braking distance (~1.12 m centre-to-surface). The robot can walk that ring —
    slowly. Refusing it would be a FALSE "I can't walk around you here", which is
    the same dishonesty as the model's fabricated claims and is what the first
    draft of this validator did to a live-sim orbit that has always completed.
    """

    bollard = (("bollard", 2.1, 0.0),)  # 0.50 m from the ring point at bearing 0
    verdict = evaluate_orbit_annulus(
        centre=(0.0, 0.0),
        radius_m=1.6,
        clearance_m=CLEARANCE,
        blocked_points=bollard,
    )
    assert verdict.feasible is True, "a slowdown is not an impossibility"

    # And the same bollard DOES refuse once it is inside the body-fit clearance.
    touching = (("bollard", 1.8, 0.0),)  # 0.20 m from the ring: the body cannot fit
    assert (
        evaluate_orbit_annulus(
            centre=(0.0, 0.0),
            radius_m=1.6,
            clearance_m=CLEARANCE,
            blocked_points=touching,
        ).feasible
        is False
    )


def test_a_clear_orbit_keeps_orbiting_tick_after_tick() -> None:
    controller = _controller()
    controller.start(ORBIT, _observation(), now=0.0)
    decision = controller.step(_observation(), now=0.5)
    assert decision.state != "failed"
    assert decision.reason != CAUSE_BLOCKED


def test_someone_stepping_into_the_path_aborts_the_orbit_with_a_cause() -> None:
    """Mid-orbit, not just at admission — and it SAYS something."""

    controller = _controller()
    controller.start(ORBIT, _observation(), now=0.0)
    intruder = (
        DynamicAgentTrack(
            agent_id="p1",
            kind="person",
            # ~30 deg counterclockwise of the robot: inside the lookahead arc.
            x=1.6 * math.cos(math.radians(30.0)),
            y=1.6 * math.sin(math.radians(30.0)),
            vx=0.0,
            vy=0.0,
            radius_m=0.5,
        ),
    )
    decision = controller.step(_observation(agents=intruder), now=0.5)
    assert decision.done is True
    assert decision.state == "failed"
    assert decision.reason == CAUSE_BLOCKED
    assert "walk around you" in controller.last_refusal_sentence


def test_a_sensor_quiet_tick_never_manufactures_a_refusal() -> None:
    """Absence of evidence is reported as absence, not as an obstacle."""

    controller = _controller()
    controller.start(ORBIT, _observation(), now=0.0)
    for tick in range(5):
        decision = controller.step(_observation(), now=0.5 + tick * 0.1)
        assert decision.reason != CAUSE_BLOCKED


@pytest.mark.parametrize("lookahead", [0.0, -5.0, 361.0, float("nan")])
def test_the_lookahead_window_is_validated_at_construction(lookahead: float) -> None:
    with pytest.raises(ValueError):
        SpatialBehaviorConfig(orbit_lookahead_deg=lookahead)
