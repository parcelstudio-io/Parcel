from __future__ import annotations

import math

from .base import GoalPose, NavObservation
from .goals import SemanticGoal
from .semantic_map import SemanticCandidate


def safe_approach_pose(
    goal: SemanticGoal,
    candidate: SemanticCandidate,
    observation: NavObservation,
    *,
    footprint_clearance_m: float = 0.35,
) -> GoalPose | None:
    if not candidate.reachable:
        return None
    if goal.terminal_relation == "inside" and candidate.polygon:
        point = _safe_polygon_point(
            candidate.polygon,
            (observation.position[0], observation.position[1]),
            footprint_clearance_m,
        )
        if point is None:
            return None
        x, y = point
    elif goal.terminal_relation == "near":
        dx = candidate.x - observation.position[0]
        dy = candidate.y - observation.position[1]
        distance = math.hypot(dx, dy)
        stand_off = float(candidate.metadata.get("stand_off_m", 0.8))
        scale = max(0.0, distance - stand_off) / distance if distance > 1e-6 else 0.0
        x = observation.position[0] + dx * scale
        y = observation.position[1] + dy * scale
    else:
        x, y = candidate.x, candidate.y
    heading = math.degrees(
        math.atan2(candidate.y - observation.position[1], candidate.x - observation.position[0])
    )
    return GoalPose(
        x=x,
        y=y,
        z=candidate.z,
        heading_deg=heading,
        poi_id=candidate.candidate_id,
        label=candidate.label,
    )


def _safe_polygon_point(
    polygon: tuple[tuple[float, float], ...],
    robot: tuple[float, float],
    clearance: float,
) -> tuple[float, float] | None:
    if len(polygon) < 3:
        return None
    # Candidate samples include centroid and points pulled from vertices toward
    # the centroid. Select the closest point with conservative edge clearance.
    cx = sum(point[0] for point in polygon) / len(polygon)
    cy = sum(point[1] for point in polygon) / len(polygon)
    samples = [(cx, cy)]
    samples.extend(((x + cx) * 0.5, (y + cy) * 0.5) for x, y in polygon)
    valid = [
        point
        for point in samples
        if _inside(point, polygon) and _edge_distance(point, polygon) >= clearance
    ]
    if not valid:
        return None
    return min(valid, key=lambda point: math.hypot(point[0] - robot[0], point[1] - robot[1]))


def point_in_polygon(point: tuple[float, float], polygon: tuple[tuple[float, float], ...]) -> bool:
    return _inside(point, polygon)


def _inside(point: tuple[float, float], polygon: tuple[tuple[float, float], ...]) -> bool:
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


def _edge_distance(point: tuple[float, float], polygon: tuple[tuple[float, float], ...]) -> float:
    return min(
        _segment_distance(point, polygon[index - 1], polygon[index])
        for index in range(len(polygon))
    )


def _segment_distance(point, start, end) -> float:
    dx, dy = end[0] - start[0], end[1] - start[1]
    length_sq = dx * dx + dy * dy
    if length_sq <= 1e-12:
        return math.hypot(point[0] - start[0], point[1] - start[1])
    t = max(0.0, min(1.0, ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / length_sq))
    return math.hypot(point[0] - (start[0] + t * dx), point[1] - (start[1] + t * dy))
