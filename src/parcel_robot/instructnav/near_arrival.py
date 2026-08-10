"""Fallback approach point inside a ``near`` K0 arrival band (search-reground).

Why this module exists
----------------------
``navigation.approach.safe_approach_pose`` plans a ``near`` stand pose on the
object's *support surface* (e.g. the sidewalk the bench sits on): every
candidate stand pose must lie inside the ``support_polygon`` with footprint
clearance. That is the right pose to *stand at* — but it is strictly stronger
than the directive's own success test. The K0 arrival authority for ``near``
(:func:`~parcel_robot.instructnav.scoring.object_near_goal_region`) accepts any
pose in a distance band around the object; it does **not** require the sidewalk.

When an object sits on a narrow strip flanked by other street furniture (a
0.73 m-radius bench centred on a 2 m sidewalk with a lamppost and a tree ~2.5 m
to either side), the support-gated ring of radius ``stand_off`` (~1.95 m for
that bench) has no admissible point: every strip-valid sample falls inside a
flanking obstacle's clearance, and every obstacle-clear sample falls off the
2 m strip. ``safe_approach_pose`` then returns ``None`` from *every* robot pose,
the recovery ladder reads that as "this instance is unreachable", banishes the
only real target from the excluding semantic map, and the dog spins out its
whole scan+frontier budget never seeing the bench again — the search-reground
defect (2026-08-09 root cause: pipeline ``_commit_semantic_candidate`` →
``_release_unreachable_candidate``).

This module supplies the honest fallback the ladder was missing: the nearest
collision-clear point **inside the same K0 band the mission verifies against**,
chosen off the support-surface constraint. A* routes to it; the K0 arrival
authority (``_inside_arrival_goal_region``) stops the robot; the scorer's band
(a superset of the runtime band) accepts it. It never invents a target — the
caller only reaches here for a candidate already grounded, confirmed, and
frustum-visible — and it returns ``None`` when the band is genuinely boxed in,
so a target with no clear approach still fails honestly.

Frozen contract
---------------
:func:`near_band_fallback_point` is pure and deterministic. Given the same
inputs it returns the same point (or ``None``). It reads no globals, imports no
navigation state, and never mutates its arguments. The selection rule is fixed:
the point sits at the band mid-radius, on the collision-clear bearing whose
direction is closest to "from the object toward the robot" (the shortest,
most natural approach), ties broken by scan index. Callers that already obtain
an admissible pose from ``safe_approach_pose`` must not call this — it is a
strictly-additional recovery path, invoked only where the prior behaviour was
an unconditional unreachable-release.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from parcel_robot.instructnav.scoring import GoalRegion

#: Number of bearings sampled around the band mid-radius. 72 → one every 5°,
#: dense enough that a clear gap wider than the robot footprint is never
#: stepped over, cheap enough to run inside one control tick.
DEFAULT_BEARING_SAMPLES = 72


def near_band_contains(
    xy: tuple[float, float],
    region: GoalRegion,
    *,
    anchor_covariance: (
        tuple[tuple[float, float], tuple[float, float]] | None
    ) = None,
    probability_threshold: float | None = None,
) -> bool:
    """K0 ``near`` membership — the single arrival authority, chance-aware.

    Delegates to :meth:`~parcel_robot.instructnav.scoring.GoalRegion.contains`
    so D4's ``P(inside)≥0.9`` upgrade stays in one place. Zero / omitted
    covariance is today's boolean (T0 byte-equal). Never invents a second
    arrival predicate.
    """

    from parcel_robot.instructnav.scoring import INSIDE_PROBABILITY_THRESHOLD

    threshold = (
        INSIDE_PROBABILITY_THRESHOLD
        if probability_threshold is None
        else float(probability_threshold)
    )
    return region.contains(
        float(xy[0]),
        float(xy[1]),
        anchor_covariance=anchor_covariance,
        probability_threshold=threshold,
    )


def near_band_fallback_point(
    *,
    center: tuple[float, float],
    band_m: tuple[float, float],
    robot_xy: tuple[float, float],
    blocked_points: Sequence[tuple[object, float, float]] = (),
    clearance_m: float = 0.0,
    bearings: int = DEFAULT_BEARING_SAMPLES,
) -> tuple[float, float] | None:
    """Return a collision-clear approach point inside a ``near`` arrival band.

    Parameters
    ----------
    center:
        The object's world-frame ``(x, y)`` — the anchor of the K0 band.
    band_m:
        ``(inner, outer)`` radii of the K0 vicinity band, in metres, exactly as
        the mission's arrival authority verifies against
        (``minimum_vicinity_radius_m`` / ``vicinity_radius_m``). Must satisfy
        ``0 < inner <= outer`` and both finite.
    robot_xy:
        The robot's world-frame ``(x, y)``. Only its *bearing* from ``center``
        is used, to prefer the shortest, most natural approach side.
    blocked_points:
        Observed obstacle **surface** points ``(id, x, y)``, with the approach
        *target's own* returns already removed by the caller (so the object
        never blocks its own band). Anything here is a solid to keep clear of.
    clearance_m:
        Minimum centre-to-surface distance the returned point keeps from every
        blocked surface. Pass ``footprint_radius + obstacle_stop`` so a pose
        this admits also clears the reactive collision gate. ``0`` disables the
        obstacle test (band geometry only).
    bearings:
        How many bearings to sample around the band mid-radius (8..720).

    Returns
    -------
    ``(x, y)`` of the chosen point, or ``None`` when every sampled bearing is
    within ``clearance_m`` of an obstacle surface (genuinely boxed in).
    """

    cx, cy = float(center[0]), float(center[1])
    inner, outer = float(band_m[0]), float(band_m[1])
    if not all(math.isfinite(v) for v in (cx, cy, inner, outer)):
        raise ValueError("center and band must be finite")
    if not (0.0 < inner <= outer):
        raise ValueError("band_m must satisfy 0 < inner <= outer")
    if not 8 <= int(bearings) <= 720:
        raise ValueError("bearings must be between 8 and 720")
    rx, ry = float(robot_xy[0]), float(robot_xy[1])
    if not (math.isfinite(rx) and math.isfinite(ry)):
        raise ValueError("robot_xy must be finite")
    clearance = float(clearance_m)
    if not math.isfinite(clearance) or clearance < 0.0:
        raise ValueError("clearance_m must be finite and >= 0")

    radius = 0.5 * (inner + outer)
    # Direction from the object toward the robot: index 0 lands the pose on the
    # robot's own side of the object, the shortest approach and the one least
    # likely to route the body around the object.
    approach_bearing = math.atan2(ry - cy, rx - cx)
    n = int(bearings)

    def _clear(px: float, py: float) -> bool:
        if clearance <= 0.0 or not blocked_points:
            return True
        for _oid, ox, oy in blocked_points:
            if math.hypot(px - float(ox), py - float(oy)) < clearance:
                return False
        return True

    # Sample bearings in order of increasing angular distance from the approach
    # bearing: 0, +1, -1, +2, -2, ... so the first clear one is the closest to
    # a straight walk-up. Deterministic and independent of dict ordering.
    for step in range(n // 2 + 1):
        for sign in ((0,) if step == 0 else (1, -1)):
            k = sign * step
            theta = approach_bearing + 2.0 * math.pi * k / n
            px = cx + radius * math.cos(theta)
            py = cy + radius * math.sin(theta)
            if _clear(px, py):
                return (px, py)
    return None
