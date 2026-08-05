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
    """

    poly = _as_polygon(polygon)
    if len(poly) < 3:
        raise ValueError("polygon requires ≥3 vertices")
    fx, fy = float(from_xy[0]), float(from_xy[1])
    if not all(math.isfinite(v) for v in (fx, fy, inset_m)) or inset_m < 0.0:
        raise ValueError("from_xy and inset_m must be finite; inset_m ≥ 0")

    if _point_in_polygon((fx, fy), poly) and _has_clearance((fx, fy), poly, inset_m):
        return (fx, fy)

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


def next_to_placement(
    anchor_xy: tuple[float, float],
    anchor_footprint_m: float,
    from_xy: tuple[float, float],
    *,
    band_m: tuple[float, float] = (0.4, 0.9),
    facing_xy: tuple[float, float] | None = None,
    occupied: Callable[[float, float], bool] | None = None,
) -> tuple[float, float, float] | None:
    """Sample a free pose in the annular band around an anchor.

    Returns ``(x, y, heading_rad)`` or ``None`` when fully blocked.
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

    radii = _linspace(inner, hi, 5)
    bearings = [index * (2.0 * math.pi / 24.0) for index in range(24)]
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


def _distance_point_to_segment(
    point: tuple[float, float],
    a: tuple[float, float],
    b: tuple[float, float],
) -> float:
    ax, ay = a
    bx, by = b
    px, py = point
    dx, dy = bx - ax, by - ay
    length_sq = dx * dx + dy * dy
    if length_sq <= 1e-18:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length_sq))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def _linspace(lo: float, hi: float, count: int) -> list[float]:
    if count <= 1:
        return [lo]
    step = (hi - lo) / (count - 1)
    return [lo + i * step for i in range(count)]


def _wrap(angle: float) -> float:
    return (angle + math.pi) % (2.0 * math.pi) - math.pi
