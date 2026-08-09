"""Region and relation goal geometry solvers (pure)."""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence


def nearest_point_in_region(
    polygon: Sequence[tuple[float, float]],
    from_xy: tuple[float, float],
    *,
    inset_m: float = 0.3,
) -> tuple[float, float]:
    """Nearest reachable point *inside* the polygon, inset from the edge.

    Never returns the centroid alone when a nearer inset point exists — an
    L-shaped sidewalk's centroid can sit 20 m up the block.

    **Two callers, two different questions** (2026-08-07, the sampling-bias
    card):

    * ``inset_m > 0`` is the **POSE** use — "where may the body stand inside
      this region?" — and it stays a *sample* of the inset interior, because
      an inset point has to be tested for interior membership and edge
      clearance, which is what the sampler does.
    * ``inset_m == 0`` is the **DISTANCE** use — every interchangeable-goal
      ranking site asks only "how far is this region from here?" — and that is
      now answered **exactly**, by projecting onto the nearest edge segment,
      never by the nearest grid sample.

    Why it mattered: the sampler anchors its lattice at ``(min_x, min_y)`` with
    spacing ``max(0.15, min(0.5, span/40))`` — 0.4 m for a 16 m sidewalk — so a
    region approached from its ``max_x``/``max_y`` side reported up to one full
    spacing too far. Measured on the live city: ``sidewalk_south`` from the
    origin sampled 2.55 m against a true 2.25 m, while the north ``sidewalk``,
    whose near edge is its ``min_y`` side, sampled its true 2.20 m exactly. The
    decision between them was therefore taken with a 0.35 m artefact on a
    **0.05 m true margin**. The winner does not change; the margin it wins by
    is now the real one.
    """

    poly = _as_polygon(polygon)
    if len(poly) < 3:
        raise ValueError("polygon requires ≥3 vertices")
    fx, fy = float(from_xy[0]), float(from_xy[1])
    if not all(math.isfinite(v) for v in (fx, fy, inset_m)) or inset_m < 0.0:
        raise ValueError("from_xy and inset_m must be finite; inset_m ≥ 0")

    if _point_in_polygon((fx, fy), poly) and _has_clearance((fx, fy), poly, inset_m):
        return (fx, fy)

    if inset_m == 0.0:
        return nearest_boundary_point(poly, (fx, fy))

    samples = _inset_samples(poly, inset_m)
    if not samples:
        # Degenerate thin region: fall back to closest vertex inset toward interior.
        cx = sum(p[0] for p in poly) / len(poly)
        cy = sum(p[1] for p in poly) / len(poly)
        return min(poly, key=lambda p: math.hypot(p[0] - fx, p[1] - fy)) if inset_m == 0 else (
            cx,
            cy,
        )
    return min(samples, key=lambda p: math.hypot(p[0] - fx, p[1] - fy))


def nearest_boundary_point(
    polygon: Sequence[tuple[float, float]],
    from_xy: tuple[float, float],
) -> tuple[float, float]:
    """Exact nearest point of the polygon *boundary* — segment projection.

    Pure closed form: project the query onto every edge, clamp to the segment,
    keep the minimum. No sampling, no lattice, no anchor bias, and exact for
    convex and non-convex polygons alike. A query already inside the polygon
    still gets its nearest boundary point back; callers that want "0 m when
    inside" test membership themselves (:func:`distance_to_region_m` does).
    """

    poly = _as_polygon(polygon)
    if len(poly) < 3:
        raise ValueError("polygon requires ≥3 vertices")
    fx, fy = float(from_xy[0]), float(from_xy[1])
    if not (math.isfinite(fx) and math.isfinite(fy)):
        raise ValueError("from_xy must be finite")
    best: tuple[float, float] | None = None
    best_distance = math.inf
    previous = poly[-1]
    for current in poly:
        point = _closest_point_on_segment((fx, fy), previous, current)
        distance = math.hypot(point[0] - fx, point[1] - fy)
        if distance < best_distance:
            best_distance = distance
            best = point
        previous = current
    assert best is not None
    return best


def distance_to_region_m(
    polygon: Sequence[tuple[float, float]],
    from_xy: tuple[float, float],
) -> float:
    """Exact distance to a region: 0.0 inside, else to the nearest boundary."""

    poly = _as_polygon(polygon)
    if len(poly) < 3:
        raise ValueError("polygon requires ≥3 vertices")
    fx, fy = float(from_xy[0]), float(from_xy[1])
    if _point_in_polygon((fx, fy), poly):
        return 0.0
    point = nearest_boundary_point(poly, (fx, fy))
    return math.hypot(point[0] - fx, point[1] - fy)


#: Bearings and radii the annulus is sampled at. **Measured 2026-08-08 (card
#: B-1):** the lattice is uniform in bearing, so it is *not* biased the way the
#: ``nearest_point_in_region`` inset sampler was — that one anchored a
#: rectangular lattice at ``(min_x, min_y)``; this one starts at bearing 0 and
#: steps by a constant, which has no world-frame preference. It was, however,
#: **too coarse for the admissible sets a surface-anchored band opens**: on
#: ``bench_1`` under that band the admissible arc measures 332.5-336.2 degrees
#: (3.7 deg wide), and at 24 bearings (15 deg apart) the lattice missed it
#: entirely — 48 and 64 also miss, 72 (5 deg) finds it. The raise therefore
#: travels **with** the band change (card S-1, 2026-08-09) and not before it:
#: under the old centre-anchored band no anchor in any scene had a non-empty
#: admissible set for a denser lattice to find, so raising it earlier could
#: only have perturbed the one live ``next_to`` case that passed.
#: ``PLACEMENT_RADII`` stays at 5: the planning band is 0.86 m wide, so 5 radii
#: are 0.215 m apart, and the binding constraint measured on ``bench_1`` is
#: bearing resolution, not radial.
PLACEMENT_BEARINGS: int = 72
PLACEMENT_RADII: int = 5


def next_to_placement(
    anchor_xy: tuple[float, float],
    anchor_footprint_m: float,
    from_xy: tuple[float, float],
    *,
    band_m: tuple[float, float],
    facing_xy: tuple[float, float] | None = None,
    occupied: Callable[[float, float], bool] | None = None,
) -> tuple[float, float, float] | None:
    """Sample a free pose in the annular band around an anchor.

    Returns ``(x, y, heading_rad)`` or ``None`` when fully blocked.

    ``band_m`` is **required**. It used to default to ``(0.4, 0.9)`` — a second
    band literal that disagreed with the K0 authority
    (:data:`~parcel_robot.instructnav.scoring.NEXT_TO_BAND_M`, ``(0.4, 1.5)``)
    by 0.6 m on its outer edge. It was inert only because the single production
    caller always passed ``band_m=`` explicitly; any new caller taking the
    default would have planned against a band the arrival authority never
    verifies. Two bands is the D5 defect class, so there is now one and the
    caller must name it.

    ``band_m`` is in anchor-**centre** coordinates, because that is the frame a
    sampled ``(x, y)`` lives in. The caller materialises it there from the
    surface-relative K0 band through the one definition,
    :func:`~parcel_robot.instructnav.scoring.next_to_band_from_centre` (the
    production caller is ``navigation.approach._next_to_planning_band``, which
    then insets it by the controller's arrival tolerance). This sampler never
    applies an offset of its own — two places adding the anchor radius would be
    the same D5 defect as two bands.

    ``anchor_footprint_m`` still raises the inner edge, so a sample cannot land
    inside the anchor even if a caller hands over a band that would allow it.
    With a surface-anchored band that guard is redundant (``band_lo + R > R``
    for any positive ``band_lo``); it is kept because it costs nothing and is
    the last line of defence against a malformed band.
    """

    ax, ay = float(anchor_xy[0]), float(anchor_xy[1])
    fx, fy = float(from_xy[0]), float(from_xy[1])
    footprint = float(anchor_footprint_m)
    lo, hi = float(band_m[0]), float(band_m[1])
    if not all(math.isfinite(v) for v in (ax, ay, fx, fy, footprint, lo, hi)):
        raise ValueError("placement inputs must be finite")
    if footprint < 0.0 or not (0.0 <= lo < hi):
        raise ValueError("invalid footprint or band_m")

    inner = max(lo, footprint)
    if inner >= hi:
        return None

    radii = _linspace(inner, hi, PLACEMENT_RADII)
    bearings = [
        index * (2.0 * math.pi / PLACEMENT_BEARINGS) for index in range(PLACEMENT_BEARINGS)
    ]
    candidates: list[tuple[float, float, float, float]] = []
    for radius in radii:
        for bearing in bearings:
            x = ax + radius * math.cos(bearing)
            y = ay + radius * math.sin(bearing)
            if occupied is not None and occupied(x, y):
                continue
            approach = math.hypot(x - fx, y - fy)
            if facing_xy is not None:
                face = math.atan2(facing_xy[1] - y, facing_xy[0] - x)
                # Prefer poses whose approach aligns with facing preference.
                approach_heading = math.atan2(y - fy, x - fx)
                align = abs(_wrap(face - approach_heading))
            else:
                face = math.atan2(ay - y, ax - x)
                align = 0.0
            score = approach + 0.35 * align
            candidates.append((score, x, y, face))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1], item[2]))
    _, x, y, heading = candidates[0]
    return (x, y, heading)


def towards_waypoint(
    target_xy: tuple[float, float],
    from_xy: tuple[float, float],
    *,
    stop_short_m: float = 1.2,
) -> tuple[float, float]:
    """Advance toward the target but stop short — motion toward, not arrival."""

    tx, ty = float(target_xy[0]), float(target_xy[1])
    fx, fy = float(from_xy[0]), float(from_xy[1])
    stop = float(stop_short_m)
    if not all(math.isfinite(v) for v in (tx, ty, fx, fy, stop)) or stop < 0.0:
        raise ValueError("towards_waypoint inputs must be finite; stop_short_m ≥ 0")
    dx, dy = tx - fx, ty - fy
    dist = math.hypot(dx, dy)
    if dist <= stop:
        return (fx, fy)
    scale = (dist - stop) / dist
    return (fx + dx * scale, fy + dy * scale)


def _inset_samples(
    polygon: tuple[tuple[float, float], ...],
    inset_m: float,
) -> list[tuple[float, float]]:
    min_x = min(p[0] for p in polygon)
    max_x = max(p[0] for p in polygon)
    min_y = min(p[1] for p in polygon)
    max_y = max(p[1] for p in polygon)
    span = max(max_x - min_x, max_y - min_y, 1e-6)
    spacing = max(0.15, min(0.5, span / 40.0))
    samples: list[tuple[float, float]] = []
    # Prefer edge-proximal inset points over the centroid.
    x = min_x + inset_m
    while x <= max_x - inset_m + 1e-9:
        y = min_y + inset_m
        while y <= max_y - inset_m + 1e-9:
            point = (x, y)
            if _point_in_polygon(point, polygon) and _has_clearance(point, polygon, inset_m):
                samples.append(point)
            y += spacing
        x += spacing
    if not samples and inset_m > 0.0:
        return _inset_samples(polygon, 0.0)
    return samples


def _has_clearance(
    point: tuple[float, float],
    polygon: tuple[tuple[float, float], ...],
    clearance: float,
) -> bool:
    if clearance <= 0.0:
        return True
    # Approximate: point must remain inside after checking distance to edges.
    previous = polygon[-1]
    for current in polygon:
        if _distance_point_to_segment(point, previous, current) < clearance - 1e-9:
            return False
        previous = current
    return True


def _as_polygon(
    polygon: Sequence[tuple[float, float]],
) -> tuple[tuple[float, float], ...]:
    out = tuple((float(p[0]), float(p[1])) for p in polygon)
    if any(not math.isfinite(v) for p in out for v in p):
        raise ValueError("polygon vertices must be finite")
    return out


def _point_in_polygon(
    point: tuple[float, float],
    polygon: tuple[tuple[float, float], ...],
) -> bool:
    x, y = point
    inside = False
    previous = polygon[-1]
    for current in polygon:
        x1, y1 = previous
        x2, y2 = current
        if (y1 > y) != (y2 > y):
            intersection = (x2 - x1) * (y - y1) / (y2 - y1) + x1
            if x < intersection:
                inside = not inside
        previous = current
    return inside


def _closest_point_on_segment(
    point: tuple[float, float],
    a: tuple[float, float],
    b: tuple[float, float],
) -> tuple[float, float]:
    ax, ay = a
    bx, by = b
    px, py = point
    dx, dy = bx - ax, by - ay
    length_sq = dx * dx + dy * dy
    if length_sq <= 1e-18:
        return (ax, ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length_sq))
    return (ax + t * dx, ay + t * dy)


def _distance_point_to_segment(
    point: tuple[float, float],
    a: tuple[float, float],
    b: tuple[float, float],
) -> float:
    closest = _closest_point_on_segment(point, a, b)
    return math.hypot(point[0] - closest[0], point[1] - closest[1])


def _linspace(lo: float, hi: float, count: int) -> list[float]:
    if count <= 1:
        return [lo]
    step = (hi - lo) / (count - 1)
    return [lo + i * step for i in range(count)]


def _wrap(angle: float) -> float:
    return (angle + math.pi) % (2.0 * math.pi) - math.pi
