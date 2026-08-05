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
