from __future__ import annotations

import math

from parcel_robot.geometry import ROBOT_FOOTPRINT_RADIUS_M
from parcel_robot.instructnav.relations import (
    nearest_point_in_region,
    next_to_placement,
    towards_waypoint,
)

from .base import GoalPose, NavObservation
from .goals import SemanticGoal
from .semantic_map import SemanticCandidate


def safe_approach_pose(
    goal: SemanticGoal,
    candidate: SemanticCandidate,
    observation: NavObservation,
    *,
    footprint_clearance_m: float = ROBOT_FOOTPRINT_RADIUS_M,
    obstacle_stop_m: float = 0.8,
) -> GoalPose | None:
    if (
        not candidate.reachable
        or not math.isfinite(obstacle_stop_m)
        or obstacle_stop_m <= 0.0
    ):
        return None
    blocked_points = _observed_obstacle_points(observation)
    arrival_radius = _bounded_metadata_float(
        candidate.metadata,
        "arrival_radius_m",
        default=0.12,
        minimum=0.05,
        maximum=0.35,
    )
    robot_xy = (observation.position[0], observation.position[1])
    if goal.terminal_relation == "inside" and candidate.polygon:
        terminal_clearance = _bounded_metadata_float(
            candidate.metadata,
            "terminal_clearance_m",
            default=0.32,
            minimum=0.10,
            maximum=1.0,
        )
        approach_clearance = max(footprint_clearance_m, terminal_clearance + arrival_radius)
        configured_obstacle_clearance = _bounded_metadata_float(
            candidate.metadata,
            "target_obstacle_clearance_m",
            default=footprint_clearance_m + obstacle_stop_m + arrival_radius + 0.05,
            minimum=footprint_clearance_m,
            maximum=3.0,
        )
        # This is center-to-obstacle-surface clearance at the planned pose.
        # Include the controller's arrival tolerance so every accepted terminal
        # pose still retains the hard-stop envelope around the robot footprint.
        obstacle_clearance = max(
            configured_obstacle_clearance,
            footprint_clearance_m + obstacle_stop_m + arrival_radius + 0.05,
        )
        point = _safe_polygon_point(
            candidate.polygon,
            robot_xy,
            approach_clearance,
            blocked_points=blocked_points,
            obstacle_clearance=obstacle_clearance,
        )
        if point is None:
            # N-S3 fallback: nearest inset point without LiDAR pruning.
            try:
                point = nearest_point_in_region(
                    candidate.polygon, robot_xy, inset_m=approach_clearance
                )
            except ValueError:
                return None
        x, y = point
    elif goal.terminal_relation == "towards":
        x, y = towards_waypoint((candidate.x, candidate.y), robot_xy, stop_short_m=1.2)
        arrival_radius = max(arrival_radius, 0.2)
    elif goal.terminal_relation == "next_to":
        footprint = _bounded_metadata_float(
            candidate.metadata, "radius_m", default=0.3, minimum=0.05, maximum=2.0
        )
        occupied_ids = {item[0] for item in blocked_points if item[0]}

        def _occupied(px: float, py: float) -> bool:
            for oid, ox, oy in blocked_points:
                if oid in occupied_ids and math.hypot(px - ox, py - oy) < obstacle_stop_m:
                    return True
            return False

        placement = next_to_placement(
            (candidate.x, candidate.y),
            footprint,
            robot_xy,
            band_m=(0.4, 1.5),
            occupied=_occupied,
        )
        if placement is None:
            return None
        x, y, _heading = placement
        arrival_radius = max(arrival_radius, 0.08)
    elif goal.terminal_relation == "near":
        stand_off = _bounded_metadata_float(
            candidate.metadata,
            "stand_off_m",
            default=1.2,
            minimum=0.5,
            maximum=3.0,
        )
        candidate_radius = _bounded_metadata_float(
            candidate.metadata,
            "radius_m",
            default=0.0,
            minimum=0.0,
            maximum=2.0,
        )
        target_surface_clearance = max(
            obstacle_stop_m,
            _bounded_metadata_float(
                candidate.metadata,
                "target_min_surface_clearance_m",
                default=obstacle_stop_m,
                minimum=0.1,
                maximum=2.0,
            ),
        )
        stand_off = max(
            stand_off,
            candidate_radius
            + footprint_clearance_m
            + target_surface_clearance
            + arrival_radius
            + 0.04,
        )
        maximum_vicinity = _bounded_metadata_float(
            candidate.metadata,
            "vicinity_radius_m",
            default=stand_off + arrival_radius + 0.05,
            minimum=0.5,
            maximum=4.0,
        )
        if stand_off + arrival_radius > maximum_vicinity + 1e-9:
            return None
        non_target_clearance = _bounded_metadata_float(
            candidate.metadata,
            "non_target_obstacle_clearance_m",
            default=footprint_clearance_m + obstacle_stop_m + arrival_radius + 0.05,
            minimum=footprint_clearance_m,
            maximum=3.0,
        )
        support_polygon = _metadata_polygon(candidate.metadata.get("support_polygon"))
        point = _safe_near_object_point(
            candidate,
            (observation.position[0], observation.position[1]),
            stand_off,
            support_polygon,
            blocked_points,
            footprint_clearance_m + arrival_radius,
            max(
                non_target_clearance,
                footprint_clearance_m + obstacle_stop_m + arrival_radius + 0.05,
            ),
        )
        if point is None:
            return None
        x, y = point
    else:
        x, y = candidate.x, candidate.y
    heading = math.degrees(
        math.atan2(candidate.y - y, candidate.x - x)
    )
    return GoalPose(
        x=x,
        y=y,
        z=candidate.z,
        heading_deg=heading,
        poi_id=candidate.candidate_id,
        label=candidate.label,
        arrival_radius_m=arrival_radius,
    )


def _safe_polygon_point(
    polygon: tuple[tuple[float, float], ...],
    robot: tuple[float, float],
    clearance: float,
    *,
    blocked_points: tuple[tuple[str | None, float, float], ...] = (),
    obstacle_clearance: float = 0.0,
) -> tuple[float, float] | None:
    if len(polygon) < 3:
        return None
    # Sample the interior rather than trusting its centroid: a sidewalk's
    # centroid can itself contain a lamp, bench, or tree. This is a bounded
    # local free-space approximation over camera semantics + LiDAR surfaces.
    cx = sum(point[0] for point in polygon) / len(polygon)
    cy = sum(point[1] for point in polygon) / len(polygon)
    samples = [(cx, cy)]
    min_x = min(point[0] for point in polygon)
    max_x = max(point[0] for point in polygon)
    min_y = min(point[1] for point in polygon)
    max_y = max(point[1] for point in polygon)
    spacing = max(0.25, max(max_x - min_x, max_y - min_y) / 40.0)
    x = min_x + clearance
    while x <= max_x - clearance + 1e-9:
        y = min_y + clearance
        while y <= max_y - clearance + 1e-9:
            samples.append((x, y))
            y += spacing
        x += spacing
    valid = [
        point
        for point in samples
        if _inside(point, polygon) and _has_clearance(point, polygon, clearance)
        and _clear_of_observed_obstacles(point, blocked_points, obstacle_clearance)
        and _segment_clear_of_observed_obstacles(
            robot,
            point,
            blocked_points,
            obstacle_clearance,
        )
    ]
    if not valid:
        return None
    return min(valid, key=lambda point: math.hypot(point[0] - robot[0], point[1] - robot[1]))


def point_in_polygon(point: tuple[float, float], polygon: tuple[tuple[float, float], ...]) -> bool:
    return _inside(point, polygon)


def point_in_polygon_with_clearance(
    point: tuple[float, float],
    polygon: tuple[tuple[float, float], ...],
    clearance_m: float,
) -> bool:
    return _inside(point, polygon) and _has_clearance(point, polygon, clearance_m)


def _safe_near_object_point(
    candidate: SemanticCandidate,
    robot: tuple[float, float],
    stand_off: float,
    support_polygon: tuple[tuple[float, float], ...],
    blocked_points: tuple[tuple[str | None, float, float], ...],
    footprint_clearance: float,
    obstacle_clearance: float,
) -> tuple[float, float] | None:
    base_angle = math.atan2(robot[1] - candidate.y, robot[0] - candidate.x)
    samples = [
        (
            candidate.x + stand_off * math.cos(base_angle + index * math.pi / 16.0),
            candidate.y + stand_off * math.sin(base_angle + index * math.pi / 16.0),
        )
        for index in range(32)
    ]
    target_ids = _associated_obstacle_ids(candidate)
    other_obstacles = tuple(item for item in blocked_points if item[0] not in target_ids)
    usable = []
    for point in samples:
        if support_polygon and not point_in_polygon_with_clearance(
            point, support_polygon, footprint_clearance
        ):
            continue
        if not _clear_of_observed_obstacles(point, other_obstacles, obstacle_clearance):
            continue
        if not _segment_clear_of_observed_obstacles(
            robot,
            point,
            other_obstacles,
            obstacle_clearance,
        ):
            continue
        usable.append(point)
    if not usable:
        return None
    return min(usable, key=lambda point: math.hypot(point[0] - robot[0], point[1] - robot[1]))


def _observed_obstacle_points(
    observation: NavObservation,
) -> tuple[tuple[str | None, float, float], ...]:
    raw = observation.extras.get("lidar_obstacles") or ()
    if not isinstance(raw, (list, tuple)):
        return ()
    heading = math.radians(observation.heading_deg)
    robot_x, robot_y = observation.position[:2]
    points: list[tuple[str | None, float, float]] = []
    for item in raw[:64]:
        if not isinstance(item, dict):
            continue
        try:
            distance = float(item["distance_m"])
            bearing = float(item["bearing_rad"])
        except (KeyError, TypeError, ValueError):
            continue
        if not math.isfinite(distance) or not math.isfinite(bearing) or distance < 0.0:
            continue
        # Simulator/robot range contracts report footprint-to-surface
        # clearance. Add the nominal body radius to estimate a world surface
        # point without exposing simulator coordinates to the planner.
        ray = distance + ROBOT_FOOTPRINT_RADIUS_M
        angle = heading + bearing
        points.append(
            (
                str(item["id"]) if item.get("id") else None,
                robot_x + ray * math.cos(angle),
                robot_y + ray * math.sin(angle),
            )
        )
    return tuple(points)


def _clear_of_observed_obstacles(
    point: tuple[float, float],
    blocked_points: tuple[tuple[str | None, float, float], ...],
    clearance: float,
) -> bool:
    return all(math.hypot(point[0] - x, point[1] - y) >= clearance for _, x, y in blocked_points)


def _segment_clear_of_observed_obstacles(
    start: tuple[float, float],
    end: tuple[float, float],
    blocked_points: tuple[tuple[str | None, float, float], ...],
    clearance: float,
) -> bool:
    """Conservatively validate the swept centerline against observed surfaces.

    A robot already inside a slowdown envelope may move away from that surface;
    otherwise the full segment must retain the requested center clearance.
    """

    groups: dict[str, list[tuple[float, float]]] = {}
    for index, (obstacle_id, x, y) in enumerate(blocked_points):
        key = obstacle_id or f"anonymous-{index}"
        groups.setdefault(key, []).append((x, y))
    for surfaces in groups.values():
        start_distance = min(math.dist(start, point) for point in surfaces)
        end_distance = min(math.dist(end, point) for point in surfaces)
        if (
            start_distance < clearance
            and end_distance > start_distance + 0.05
            and _group_clearance_is_nondecreasing(start, end, surfaces)
        ):
            # Moving out of an already-entered slowdown envelope is safer than
            # freezing in it. Group all returns from a long face so individual
            # perimeter samples do not falsely reject motion away from the
            # underlying solid obstacle.
            continue
        if any(
            _segment_distance(surface, start, end) < clearance
            for surface in surfaces
        ):
            return False
    return True


def _group_clearance_is_nondecreasing(
    start: tuple[float, float],
    end: tuple[float, float],
    surfaces: list[tuple[float, float]],
) -> bool:
    previous = min(math.dist(start, point) for point in surfaces)
    for index in range(1, 17):
        fraction = index / 16.0
        position = (
            start[0] + (end[0] - start[0]) * fraction,
            start[1] + (end[1] - start[1]) * fraction,
        )
        current = min(math.dist(position, point) for point in surfaces)
        if current + 1e-6 < previous:
            return False
        previous = current
    return True


def _associated_obstacle_ids(candidate: SemanticCandidate) -> frozenset[str]:
    values = candidate.metadata.get("associated_lidar_ids")
    ids = {candidate.candidate_id}
    if isinstance(values, (list, tuple)):
        ids.update(
            str(value)
            for value in values[:16]
            if isinstance(value, str) and 0 < len(value) <= 128
        )
    return frozenset(ids)


def _metadata_polygon(value: object) -> tuple[tuple[float, float], ...]:
    if not isinstance(value, (list, tuple)) or not 3 <= len(value) <= 256:
        return ()
    try:
        polygon = tuple((float(point[0]), float(point[1])) for point in value)
    except (IndexError, TypeError, ValueError):
        return ()
    if any(not math.isfinite(axis) for point in polygon for axis in point):
        return ()
    return polygon


def _bounded_metadata_float(
    metadata: dict[str, object],
    key: str,
    *,
    default: float,
    minimum: float,
    maximum: float,
) -> float:
    try:
        value = float(metadata.get(key, default))
    except (TypeError, ValueError):
        return default
    return value if math.isfinite(value) and minimum <= value <= maximum else default


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


def _has_clearance(
    point: tuple[float, float],
    polygon: tuple[tuple[float, float], ...],
    clearance: float,
) -> bool:
    return _edge_distance(point, polygon) + 1e-9 >= clearance


def _segment_distance(point, start, end) -> float:
    return _segment_distance_and_progress(point, start, end)[0]


def _segment_distance_and_progress(point, start, end) -> tuple[float, float]:
    dx, dy = end[0] - start[0], end[1] - start[1]
    length_sq = dx * dx + dy * dy
    if length_sq <= 1e-12:
        return math.hypot(point[0] - start[0], point[1] - start[1]), 0.0
    projection = ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / length_sq
    progress = max(0.0, min(1.0, projection))
    return (
        math.hypot(
            point[0] - (start[0] + progress * dx),
            point[1] - (start[1] + progress * dy),
        ),
        progress,
    )
