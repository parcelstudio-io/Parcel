"""N-S3: nearest-in-region, next-to, towards solvers."""

from __future__ import annotations

import math

import pytest

from parcel_robot.instructnav.relations import (
    nearest_point_in_region,
    next_to_placement,
    towards_waypoint,
)


def test_nearest_point_prefers_local_inset_over_l_centroid():
    # L-shaped region: vertical stem + horizontal foot. Centroid sits near the
    # crook; robot at the foot should get a nearby inset point, not the crook.
    polygon = (
        (0.0, 0.0),
        (6.0, 0.0),
        (6.0, 1.0),
        (1.0, 1.0),
        (1.0, 8.0),
        (0.0, 8.0),
    )
    point = nearest_point_in_region(polygon, (5.5, -0.5), inset_m=0.2)
    cx = sum(p[0] for p in polygon) / len(polygon)
    cy = sum(p[1] for p in polygon) / len(polygon)
    dist_point = math.hypot(point[0] - 5.5, point[1] + 0.5)
    dist_centroid = math.hypot(cx - 5.5, cy + 0.5)
    assert dist_point < dist_centroid - 1.0
    assert point[1] < 2.0  # on the foot, not up the stem


def test_next_to_placement_respects_band_and_occupancy():
    placement = next_to_placement(
        (0.0, 0.0),
        0.3,
        (3.0, 0.0),
        band_m=(0.4, 0.9),
    )
    assert placement is not None
    x, y, heading = placement
    dist = math.hypot(x, y)
    assert 0.4 <= dist <= 0.9
    assert math.isfinite(heading)

    blocked = next_to_placement(
        (0.0, 0.0),
        0.3,
        (3.0, 0.0),
        band_m=(0.4, 0.9),
        occupied=lambda _x, _y: True,
    )
    assert blocked is None


def test_towards_stops_short():
    waypoint = towards_waypoint((10.0, 0.0), (0.0, 0.0), stop_short_m=1.2)
    assert waypoint[0] == pytest.approx(8.8)
    assert waypoint[1] == pytest.approx(0.0)

    already_close = towards_waypoint((0.5, 0.0), (0.0, 0.0), stop_short_m=1.2)
    assert already_close == pytest.approx((0.0, 0.0))


# --- exact boundary distance (card F-3b, 2026-08-07) -----------------------
#
# ``nearest_point_in_region`` serves two callers with two different questions,
# and the sampled answer was wrong for one of them. Every interchangeable-goal
# RANKING site calls it with ``inset_m=0`` and only wants a distance; the
# approach solver calls it with a positive inset and wants a *pose*. The
# sampler anchors its lattice at ``(min_x, min_y)``, so a region approached
# from its ``max_x``/``max_y`` side reported up to one full grid spacing too
# far — 0.4 m for a 16 m sidewalk, on a decision whose true margin is 0.05 m.


def test_the_distance_use_is_exact_and_the_pose_use_still_samples():
    from parcel_robot.instructnav.relations import _inset_samples, distance_to_region_m

    # The live city's two sidewalks, from the origin (the U34/D-4 decision).
    north = ((-8.0, 2.2), (8.0, 2.2), (8.0, 4.2), (-8.0, 4.2))
    south = ((-8.0, -3.75), (8.0, -3.75), (8.0, -2.25), (-8.0, -2.25))

    assert distance_to_region_m(north, (0.0, 0.0)) == pytest.approx(2.20)
    assert distance_to_region_m(south, (0.0, 0.0)) == pytest.approx(2.25)
    # North wins under BOTH measures — the arbitrated outcome does not move —
    # but the margin it wins by is 0.05 m, not the 0.35 m the sampler reported.
    assert distance_to_region_m(south, (0.0, 0.0)) - distance_to_region_m(
        north, (0.0, 0.0)
    ) == pytest.approx(0.05)

    # The bias this removes, measured: the south polygon's near edge is its
    # max_y side, so its nearest lattice sample sat 0.30 m short of the truth.
    sampled_south = min(
        math.hypot(p[0], p[1]) for p in _inset_samples(south, 0.0)
    )
    assert sampled_south == pytest.approx(2.55)
    assert sampled_south - distance_to_region_m(south, (0.0, 0.0)) == pytest.approx(0.30)

    # And the POSE use is untouched: a positive inset still returns an interior
    # sample with the requested edge clearance.
    pose = nearest_point_in_region(north, (0.0, 0.0), inset_m=0.5)
    assert pose[1] >= 2.2 + 0.5 - 1e-9


def test_the_exact_boundary_point_is_on_the_boundary_and_nearest():
    from parcel_robot.instructnav.relations import (
        distance_to_region_m,
        nearest_boundary_point,
    )

    # A non-convex polygon: the projection must clamp to the segment, so the
    # answer is a point on an edge, never an unbounded line projection.
    polygon = ((0.0, 0.0), (4.0, 0.0), (4.0, 4.0), (2.0, 1.0), (0.0, 4.0))
    for query in ((2.0, 3.0), (-3.0, -3.0), (10.0, 2.0), (2.0, 0.5)):
        point = nearest_boundary_point(polygon, query)
        edge = min(
            _segment_distance(point, polygon[i - 1], polygon[i])
            for i in range(len(polygon))
        )
        assert edge < 1e-9, f"{point} is not on the boundary"
        # No sampled interior point can beat it.
        assert math.hypot(point[0] - query[0], point[1] - query[1]) <= min(
            math.hypot(vertex[0] - query[0], vertex[1] - query[1]) for vertex in polygon
        ) + 1e-9
    assert distance_to_region_m(polygon, (2.0, 0.5)) == 0.0  # inside


def _segment_distance(point, a, b) -> float:
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    length_sq = dx * dx + dy * dy
    if length_sq <= 1e-18:
        return math.hypot(point[0] - ax, point[1] - ay)
    t = max(0.0, min(1.0, ((point[0] - ax) * dx + (point[1] - ay) * dy) / length_sq))
    return math.hypot(point[0] - (ax + t * dx), point[1] - (ay + t * dy))
