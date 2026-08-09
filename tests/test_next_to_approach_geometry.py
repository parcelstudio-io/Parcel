"""The ``next_to`` approach pose must be one the robot can actually hold.

Two arithmetic defects, both measured live on 2026-08-06/07 and both fixed in
``navigation/approach.py``'s ``next_to`` branch (card F-1):

1. **The pose was planned on the band's outer edge.** K0's ``NEXT_TO_BAND_M``
   is the band the arrival authority *verifies* against, but the controller
   stops anywhere within ``arrival_radius_m`` of the planned pose, in any
   direction — including radially away from the anchor. Measured: pose planned
   at 1.5000 m from ``lamp_post_1``, robot stopped at 1.572 m, mission failed
   ``semantic_arrival_verification_failed`` 0.072 m outside a band it had been
   driven to the edge of. 0.072 m is one arrival tolerance (0.08 m).

2. **The occupancy test compared a robot centre against a surface point using a
   footprint-to-surface threshold.** The body radius was simply missing from
   the comparison, so the branch would place the robot with its own footprint
   inside the stop envelope of the object it was asked to sit beside — and the
   runtime's reactive gate, which (correctly) exempts nothing, then refused to
   let it arrive. Measured on the bench: planned pose (-1.00, 3.045), robot
   stopped 0.663 m from ``bench_seat`` with 592 reactive-stop ticks, ending
   1.712 m from the bench centre, 0.212 m outside the band.

Neither fix widens a band, loosens a tolerance, or weakens a gate: both are
*narrowings* of the set of poses the planner may propose.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from parcel_robot.authority import DEFAULT_STAND_OFF_ENVELOPE
from parcel_robot.instructnav.scoring import (
    NEXT_TO_BAND_M,
    next_to_band_from_centre,
    object_next_to_goal_region,
)
from parcel_robot.navigation.approach import _next_to_planning_band, safe_approach_pose
from parcel_robot.navigation.base import NavObservation
from parcel_robot.navigation.goals import semantic_goal_from_directive
from parcel_robot.navigation.semantic_map import SemanticCandidate

#: What the pipeline passes in: the profile footprint and the navigator's
#: obstacle stop distance (``configs/navigation/default.yaml stop_distance_m``).
FOOTPRINT_M = 0.32
OBSTACLE_STOP_M = 0.8


def _candidate(x: float, y: float, radius_m: float, **metadata) -> SemanticCandidate:
    meta = {"radius_m": radius_m, "arrival_radius_m": 0.06}
    meta.update(metadata)
    return SemanticCandidate(
        candidate_id="target-1",
        label="lamppost",
        kind="object",
        x=x,
        y=y,
        z=0.0,
        confidence=0.98,
        source="test",
        reachable=True,
        metadata=meta,
    )


def _observation(*surfaces: tuple[str, float, float]) -> NavObservation:
    """Robot at the origin facing +x, with LiDAR returns at given (id, r, bearing).

    ``distance_m`` is footprint-to-surface by the range contract, which is what
    ``_observed_obstacle_points`` re-projects by adding the footprint back.
    """

    return NavObservation(
        position=(0.0, 0.0, 0.0),
        heading_deg=0.0,
        extras={
            "lidar_obstacles": [
                {"id": name, "distance_m": distance, "bearing_rad": bearing}
                for name, distance, bearing in surfaces
            ]
        },
    )


def _pose_for(candidate: SemanticCandidate, observation: NavObservation):
    goal = semantic_goal_from_directive("sit next to the lamppost")
    assert goal is not None and goal.terminal_relation == "next_to"
    return safe_approach_pose(
        goal,
        candidate,
        observation,
        footprint_clearance_m=FOOTPRINT_M,
        obstacle_stop_m=OBSTACLE_STOP_M,
    )


# --- 1. the band inset -----------------------------------------------------


@pytest.mark.parametrize("radius_m", [0.0, 0.06, 0.3, 0.45, 0.58, 0.733757, 2.408])
def test_the_planner_and_the_arrival_authority_read_ONE_band(radius_m: float):
    """The identity that makes planning and verification unable to disagree.

    The K0 band is measured to the anchor's **surface**. There is exactly one
    place that says what that is in the anchor-centre coordinates a pose lives
    in — ``next_to_band_from_centre`` — and both authorities go through it:

    * the arrival authority, via ``object_next_to_goal_region``;
    * the planner, via ``_next_to_planning_band``, which then insets by the
      tolerance the controller may spend.

    So the planning band is the *verified* band inset, for every anchor size,
    with no per-site offset anywhere. Before 2026-08-09 the two agreed only
    because both read the same centre-anchored literal, and both were wrong
    together for any anchor bigger than 0.38 m.
    """

    verified = object_next_to_goal_region((1.0, -2.0), radius_m).band_m
    assert verified == pytest.approx(next_to_band_from_centre(radius_m))
    assert verified == pytest.approx(
        (NEXT_TO_BAND_M[0] + radius_m, NEXT_TO_BAND_M[1] + radius_m)
    )

    lo, hi = _next_to_planning_band(0.08, radius_m)
    inset = 0.08 + DEFAULT_STAND_OFF_ENVELOPE.stand_off_margin_m
    assert (lo, hi) == pytest.approx((verified[0] + inset, verified[1] - inset))
    # A narrowing, never a widening — the property that makes this fix safe.
    assert lo > verified[0] and hi < verified[1]
    # ...and the band's WIDTH does not depend on the anchor's size, which is the
    # whole content of the change: a 2.4 m building gets the same 1.1 m of band
    # as a 0.06 m lamppost, measured from each one's own surface.
    assert verified[1] - verified[0] == pytest.approx(NEXT_TO_BAND_M[1] - NEXT_TO_BAND_M[0])


def test_the_planning_band_will_not_silently_assume_a_point_anchor():
    """``anchor_footprint_m`` is required, not defaulted.

    A caller that omitted it would plan inside a band the arrival authority
    never verifies — the exact class of defect the one-definition rule exists
    to prevent — so omitting it is a ``TypeError``, not a 0.0.
    """

    with pytest.raises(TypeError):
        _next_to_planning_band(0.08)  # type: ignore[call-arg]


def test_an_inset_that_would_empty_the_band_is_an_error_not_a_flipped_band():
    with pytest.raises(ValueError):
        _next_to_planning_band(1.0, 0.06)


@pytest.mark.parametrize(
    ("anchor", "radius_m"),
    [
        ((0.2, 3.15), 0.06),  # lamp_post_1, live city
        ((3.0, 0.0), 0.45),  # planter-scale
        ((-2.0, 2.0), 0.3),  # the metadata default
    ],
)
def test_every_pose_the_controller_may_stop_at_is_inside_the_verified_band(anchor, radius_m):
    """The invariant the 7 cm miss violated, stated as geometry.

    The controller declares arrival anywhere within ``arrival_radius_m`` of the
    pose. Every point of that disc must satisfy the K0 predicate, or the
    mission can be driven to a place it will then refuse to verify.
    """

    candidate = _candidate(anchor[0], anchor[1], radius_m)
    pose = _pose_for(candidate, _observation())
    assert pose is not None
    region = object_next_to_goal_region(anchor, radius_m, entity_id="target-1")
    tolerance = pose.arrival_radius_m
    assert tolerance is not None

    planned = math.hypot(pose.x - anchor[0], pose.y - anchor[1])
    assert region.contains(pose.x, pose.y)
    # The whole tolerance disc, sampled at its extremes along the anchor ray
    # (the worst case: the band is an annulus, so radial error is what escapes).
    assert region.contains(
        *_along_ray(anchor, pose, planned + tolerance)
    ), "a stop at the far edge of the arrival tolerance leaves the band"
    assert region.contains(*_along_ray(anchor, pose, planned - tolerance))


def _along_ray(anchor, pose, distance: float) -> tuple[float, float]:
    dx, dy = pose.x - anchor[0], pose.y - anchor[1]
    length = math.hypot(dx, dy)
    return (anchor[0] + dx / length * distance, anchor[1] + dy / length * distance)


def test_the_pre_fix_edge_pose_is_exactly_the_measured_7_cm_miss():
    """Regression witness: what the old band-edge pose admitted, in numbers.

    ``lamp_post_1`` at (0.2, 3.15), approached from the south. The old solver
    planned at the band maximum and the controller's 0.08 m tolerance then
    permitted a final pose one tolerance beyond it; the live run stopped at
    1.572 m against a band that ended at 1.500 m — 0.07 m outside.

    Surface-anchoring the band (2026-08-09) moved every edge of this scene out
    by the lamppost's own 0.06 m radius, so the *numbers* here are 0.06 larger
    than the 2026-08-06 measurement. **The defect and the invariant are
    unchanged**: a pose at the band's outer edge is still one tolerance from
    leaving it, which is why the planner plans in the inset band and not this
    one.
    """

    anchor = (0.2, 3.15)
    radius_m = 0.06
    region = object_next_to_goal_region(anchor, radius_m, entity_id="lamp_post_1")
    band_hi = next_to_band_from_centre(radius_m)[1]
    assert band_hi == pytest.approx(1.56)

    on_the_edge = (anchor[0], anchor[1] - band_hi)
    one_tolerance_out = (anchor[0], anchor[1] - (band_hi + 0.08))

    assert region.contains(*on_the_edge)
    assert not region.contains(*one_tolerance_out)
    assert round(region.distance_to(*one_tolerance_out), 2) == 0.08

    # The 2026-08-06 live pose. It was 0.070 m outside the centre-anchored band
    # (which ended at 1.500 m) and is still 0.010 m outside the surface-anchored
    # one (which ends at 1.560 m) — the band moved out by the lamppost's 0.06 m
    # radius and the miss shrank by exactly that. It is still a miss, which is
    # the point: the fix moved the band, not the body, and what keeps a
    # *planned* pose off the edge is the inset planning band.
    measured_live = (0.19, 1.58)
    assert math.hypot(
        measured_live[0] - anchor[0], measured_live[1] - anchor[1]
    ) == pytest.approx(1.5700, abs=5e-4)
    assert not region.contains(*measured_live)
    assert region.distance_to(*measured_live) == pytest.approx(0.010, abs=5e-4)
    assert object_next_to_goal_region(anchor, 0.0).distance_to(
        *measured_live
    ) == pytest.approx(0.070, abs=5e-4)


# --- 2. the footprint term in the occupancy test ---------------------------


def test_a_surface_the_body_would_sit_inside_is_not_an_admissible_placement():
    """The missing footprint radius, as a behaviour difference.

    A wall 1.0 m beyond the anchor: with the footprint in the comparison the
    solver must not place the robot's centre within 0.32 + 0.8 + 0.08 = 1.20 m
    of that surface. Placing it at, say, 1.05 m would leave 0.73 m of
    footprint-to-surface clearance — inside the 0.8 m the navigator's own gate
    stops at, and inside the runtime reactive gate's 0.65 m too.
    """

    anchor = (3.0, 0.0)
    candidate = _candidate(anchor[0], anchor[1], 0.06)
    # A surface at (4.0, 0.0): reported footprint-to-surface, so 4.0 - 0.32.
    observation = _observation(("wall", 4.0 - FOOTPRINT_M, 0.0))
    pose = _pose_for(candidate, observation)
    assert pose is not None
    clearance = math.hypot(pose.x - 4.0, pose.y - 0.0)
    assert clearance >= FOOTPRINT_M + OBSTACLE_STOP_M + 0.08 - 1e-9, (
        f"planned pose is {clearance:.3f} m from an observed surface — the body "
        f"radius is missing from the clearance test again"
    )


def test_an_anonymous_return_is_still_a_solid():
    """A camera and a LiDAR share no id space; an unlabelled return is a wall.

    The old test only considered returns carrying an id, so the whole check was
    inert for any real range sensor.
    """

    anchor = (3.0, 0.0)
    candidate = _candidate(anchor[0], anchor[1], 0.06)
    named = _pose_for(candidate, _observation(("wall", 4.0 - FOOTPRINT_M, 0.0)))
    anonymous = _observation()
    anonymous.extras["lidar_obstacles"] = [
        {"id": None, "distance_m": 4.0 - FOOTPRINT_M, "bearing_rad": 0.0}
    ]
    unnamed = _pose_for(candidate, anonymous)
    assert named is not None and unnamed is not None
    assert (round(named.x, 6), round(named.y, 6)) == (round(unnamed.x, 6), round(unnamed.y, 6))


def _ring_of_surfaces(anchor, ring_radius_m: float, count: int = 24):
    """LiDAR returns evenly spaced on a circle of ``ring_radius_m`` about ``anchor``."""

    out = []
    for index in range(count):
        theta = index * 2.0 * math.pi / count
        sx = anchor[0] + ring_radius_m * math.cos(theta)
        sy = anchor[1] + ring_radius_m * math.sin(theta)
        out.append(
            ("ring", math.hypot(sx, sy) - FOOTPRINT_M, math.atan2(sy, sx))
        )
    return out


def test_an_anchor_no_longer_empties_its_own_band_just_by_being_large():
    """The bench, in miniature — and the defect surface-anchoring removed.

    A 0.7 m anchor whose own surface is the only obstacle used to have an empty
    ``next_to`` band: the band's outer edge was a fixed 1.5 m from the *centre*,
    i.e. 0.8 m from that surface, against a 1.20 m solver clearance. With the
    band measured from the surface the outer edge is 1.5 m of clearance and a
    pose exists — and it is *outside* the clearance, not inside it, which is the
    part that matters.
    """

    anchor = (3.0, 0.0)
    candidate = _candidate(anchor[0], anchor[1], 0.7)
    pose = _pose_for(candidate, _observation(*_ring_of_surfaces(anchor, 0.7)))
    assert pose is not None
    from_centre = math.hypot(pose.x - anchor[0], pose.y - anchor[1])
    assert from_centre - 0.7 >= FOOTPRINT_M + OBSTACLE_STOP_M + 0.08 - 1e-9
    assert object_next_to_goal_region(anchor, 0.7).contains(pose.x, pose.y)


def test_a_band_with_no_admissible_pose_returns_none_rather_than_an_unholdable_one():
    """A genuinely blocked band is still refused, not answered with a bad pose.

    The anchor is ringed by *other* solids sitting inside the band itself, so
    every sample fails the footprint + stop + tolerance clearance. Honest
    ``None`` is what routes into the alternate-candidate release
    (``tests/test_unroutable_goal_release.py``); returning the least-bad pose
    would put the robot somewhere it can never verify arrival from.
    """

    anchor = (3.0, 0.0)
    radius_m = 0.7
    candidate = _candidate(anchor[0], anchor[1], radius_m)
    lo, hi = _next_to_planning_band(0.08, radius_m)
    # Two concentric rings of surfaces inside the planning band: with a 1.20 m
    # clearance requirement and a 0.86 m wide band, nothing in it can clear both.
    surfaces = [
        *_ring_of_surfaces(anchor, lo, count=48),
        *_ring_of_surfaces(anchor, 0.5 * (lo + hi), count=48),
        *_ring_of_surfaces(anchor, hi, count=48),
    ]
    assert _pose_for(candidate, _observation(*surfaces)) is None
