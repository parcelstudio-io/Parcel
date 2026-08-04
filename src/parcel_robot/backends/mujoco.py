from __future__ import annotations

import math
import time
from pathlib import Path

from parcel_robot.models import Pose, VelocityCommand
from parcel_robot.sim_ipc import (
    DEFAULT_SOCKET,
    publish_clear_emergency_stop,
    publish_emergency_stop,
    publish_pose,
    publish_stop,
    publish_trajectory,
    publish_velocity,
    request_status,
    send_message,
)

from .base import (
    DynamicAgentTrack,
    LidarObstacle,
    OwnerTrack,
    RobotPose,
    SemanticObjectTrack,
    SemanticRegionTrack,
    SimObservation,
)

MAX_DYNAMIC_AGENTS = 64
MAX_LIDAR_OBSTACLES = 64
MAX_SEMANTIC_REGIONS = 64
MAX_SEMANTIC_OBJECTS = 64


def _finite_float(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"simulator {field} must be a number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"simulator {field} must be finite")
    return result


class MujocoSocketBackend:
    """Engine-neutral backend adapter for the local MuJoCo process."""

    name = "mujoco"

    def __init__(self, socket_path: str | Path = DEFAULT_SOCKET, timeout: float = 1.0):
        self.socket_path = Path(socket_path)
        self.timeout = timeout

    def observe(self) -> SimObservation:
        data = request_status(self.socket_path, timeout=self.timeout)
        robot = data.get("robot")
        owner = data.get("owner")
        if not isinstance(robot, dict) or not isinstance(owner, dict):
            raise TypeError("simulator status requires robot and owner objects")
        obstacle = data.get("nearest_obstacle_m")
        if obstacle is not None:
            obstacle = _finite_float(obstacle, "nearest_obstacle_m")
            if obstacle < 0.0:
                raise ValueError("simulator nearest_obstacle_m cannot be negative")
        obstacle_detail = data.get("nearest_obstacle")
        if obstacle_detail is None:
            obstacle_detail = {}
        if not isinstance(obstacle_detail, dict):
            raise TypeError("simulator nearest_obstacle must be an object or null")
        bearing = obstacle_detail.get("bearing_rad")
        if bearing is not None:
            bearing = _finite_float(bearing, "nearest_obstacle.bearing_rad")
        raw_lidar = data.get("lidar_obstacles", [])
        if not isinstance(raw_lidar, list):
            raise TypeError("simulator lidar_obstacles must be a list")
        if len(raw_lidar) > MAX_LIDAR_OBSTACLES:
            raise ValueError("simulator reported too many LiDAR obstacles")
        lidar_obstacles = tuple(
            _parse_lidar_obstacle(item, index) for index, item in enumerate(raw_lidar)
        )
        scan = _parse_lidar_scan(data.get("lidar_scan"))
        person_distance = data.get("nearest_person_m")
        if person_distance is not None:
            person_distance = _finite_float(person_distance, "nearest_person_m")
            if person_distance < 0.0:
                raise ValueError("simulator nearest_person_m cannot be negative")
        person_detail = data.get("nearest_person") or {}
        if not isinstance(person_detail, dict):
            raise TypeError("simulator nearest_person must be an object or null")
        person_bearing = person_detail.get("bearing_rad")
        if person_bearing is not None:
            person_bearing = _finite_float(person_bearing, "nearest_person.bearing_rad")
        person_ttc = person_detail.get("time_to_collision_s")
        if person_ttc is not None:
            person_ttc = _finite_float(person_ttc, "nearest_person.time_to_collision_s")
            if person_ttc < 0.0:
                raise ValueError("simulator nearest-person TTC cannot be negative")
        raw_agents = data.get("dynamic_agents", [])
        if not isinstance(raw_agents, list):
            raise TypeError("simulator dynamic_agents must be a list")
        if len(raw_agents) > MAX_DYNAMIC_AGENTS:
            raise ValueError("simulator reported too many dynamic agents")
        dynamic_agents = tuple(
            _parse_dynamic_agent(item, index) for index, item in enumerate(raw_agents)
        )
        raw_regions = data.get("semantic_regions", [])
        if not isinstance(raw_regions, list):
            raise TypeError("simulator semantic_regions must be a list")
        if len(raw_regions) > MAX_SEMANTIC_REGIONS:
            raise ValueError("simulator reported too many semantic regions")
        semantic_regions = tuple(
            _parse_semantic_region(item, index) for index, item in enumerate(raw_regions)
        )
        raw_objects = data.get("semantic_objects", [])
        if not isinstance(raw_objects, list):
            raise TypeError("simulator semantic_objects must be a list")
        if len(raw_objects) > MAX_SEMANTIC_OBJECTS:
            raise ValueError("simulator reported too many semantic objects")
        semantic_objects = tuple(
            _parse_semantic_object(item, index) for index, item in enumerate(raw_objects)
        )
        timestamp = _finite_float(data.get("timestamp"), "timestamp")
        if timestamp <= 0.0 or timestamp > time.monotonic() + 5.0:
            raise ValueError("simulator timestamp is outside the valid monotonic range")
        visible = owner.get("visible")
        collision = data.get("collision")
        emergency_stopped = data.get("emergency_stopped", False)
        if not isinstance(visible, bool):
            raise TypeError("simulator owner.visible must be a boolean")
        if not isinstance(collision, bool):
            raise TypeError("simulator collision must be a boolean")
        if not isinstance(emergency_stopped, bool):
            raise TypeError("simulator emergency_stopped must be a boolean")
        confidence = _finite_float(owner.get("confidence"), "owner.confidence")
        if not 0.0 <= confidence <= 1.0:
            raise ValueError("simulator owner.confidence must be between zero and one")
        owner_id = owner.get("id")
        if not isinstance(owner_id, str) or not owner_id.strip():
            raise TypeError("simulator owner.id must be a non-empty string")
        backend = data.get("backend")
        if not isinstance(backend, str) or not backend:
            raise TypeError("simulator backend must be a non-empty string")
        return SimObservation(
            timestamp=timestamp,
            robot=RobotPose(
                x=_finite_float(robot.get("x"), "robot.x"),
                y=_finite_float(robot.get("y"), "robot.y"),
                z=_finite_float(robot.get("z"), "robot.z"),
                yaw=_finite_float(robot.get("yaw"), "robot.yaw"),
            ),
            owner=OwnerTrack(
                owner_id=owner_id,
                x=_finite_float(owner.get("x"), "owner.x"),
                y=_finite_float(owner.get("y"), "owner.y"),
                visible=visible,
                confidence=confidence,
            ),
            nearest_obstacle_m=obstacle,
            nearest_obstacle_bearing_rad=bearing,
            nearest_obstacle_id=(str(obstacle_detail["id"]) if obstacle_detail.get("id") else None),
            lidar_obstacles=lidar_obstacles,
            lidar_ranges=scan[0],
            lidar_angle_min_rad=scan[1],
            lidar_angle_increment_rad=scan[2],
            lidar_range_min_m=scan[3],
            lidar_range_max_m=scan[4],
            nearest_person_m=person_distance,
            nearest_person_bearing_rad=person_bearing,
            nearest_person_id=(str(person_detail["id"]) if person_detail.get("id") else None),
            nearest_person_ttc_s=person_ttc,
            dynamic_agents=dynamic_agents,
            semantic_regions=semantic_regions,
            semantic_objects=semantic_objects,
            collision=collision,
            emergency_stopped=emergency_stopped,
            backend=backend,
        )

    def move(self, command: VelocityCommand) -> None:
        publish_velocity(command, self.socket_path)

    def stop(self) -> None:
        publish_stop(self.socket_path)

    def emergency_stop(self) -> None:
        publish_emergency_stop(self.socket_path)

    def clear_emergency_stop(self) -> None:
        publish_clear_emergency_stop(self.socket_path)

    def pose(self, pose: Pose) -> None:
        publish_pose(pose, self.socket_path)

    def trajectory(self, skill: object) -> None:
        publish_trajectory(skill, self.socket_path)

    def move_owner(self, dx: float, dy: float) -> None:
        if not math.isfinite(dx) or not math.isfinite(dy):
            raise ValueError("owner movement must be finite")
        send_message({"version": 1, "type": "owner_move", "dx": dx, "dy": dy}, self.socket_path)

    def set_owner_visible(self, visible: bool) -> None:
        send_message(
            {"version": 1, "type": "owner_visibility", "visible": bool(visible)},
            self.socket_path,
        )


_EMPTY_SCAN: tuple[tuple[float, ...], None, None, None, None] = ((), None, None, None, None)


def _parse_lidar_scan(
    raw: object,
) -> tuple[tuple[float, ...], float | None, float | None, float | None, float | None]:
    """Parse the calibrated planar scan; ``None`` entries decode to NaN."""

    if raw is None:
        return _EMPTY_SCAN
    if not isinstance(raw, dict):
        raise TypeError("simulator lidar_scan must be an object or null")
    raw_ranges = raw.get("ranges")
    if not isinstance(raw_ranges, list) or not 2 <= len(raw_ranges) <= 16_384:
        raise TypeError("simulator lidar_scan.ranges must be a list of 2..16384 entries")
    angle_min = _finite_float(raw.get("angle_min_rad"), "lidar_scan.angle_min_rad")
    increment = _finite_float(raw.get("angle_increment_rad"), "lidar_scan.angle_increment_rad")
    range_min = _finite_float(raw.get("range_min_m"), "lidar_scan.range_min_m")
    range_max = _finite_float(raw.get("range_max_m"), "lidar_scan.range_max_m")
    if increment == 0.0:
        raise ValueError("simulator lidar_scan.angle_increment_rad cannot be zero")
    if range_max <= range_min or range_min < 0.0:
        raise ValueError("simulator lidar_scan range bounds are invalid")
    ranges: list[float] = []
    for index, value in enumerate(raw_ranges):
        if value is None:
            ranges.append(float("nan"))
            continue
        distance = _finite_float(value, f"lidar_scan.ranges[{index}]")
        if not 0.0 <= distance <= range_max * 1.001:
            raise ValueError(f"simulator lidar_scan.ranges[{index}] is outside the range")
        ranges.append(min(distance, range_max))
    return tuple(ranges), angle_min, increment, range_min, range_max


def _parse_dynamic_agent(item: object, index: int) -> DynamicAgentTrack:
    if not isinstance(item, dict):
        raise TypeError(f"simulator dynamic_agents[{index}] must be an object")
    agent_id = item.get("id")
    kind = item.get("kind")
    if not isinstance(agent_id, str) or not agent_id.strip() or len(agent_id) > 80:
        raise TypeError(f"simulator dynamic_agents[{index}].id is invalid")
    if kind not in {"pedestrian", "cyclist", "vehicle"}:
        raise ValueError(f"simulator dynamic_agents[{index}].kind is invalid")
    radius = _finite_float(item.get("radius_m"), f"dynamic_agents[{index}].radius_m")
    if not 0.05 <= radius <= 5.0:
        raise ValueError(f"simulator dynamic_agents[{index}].radius_m is invalid")
    return DynamicAgentTrack(
        agent_id=agent_id,
        kind=kind,
        x=_finite_float(item.get("x"), f"dynamic_agents[{index}].x"),
        y=_finite_float(item.get("y"), f"dynamic_agents[{index}].y"),
        vx=_finite_float(item.get("vx"), f"dynamic_agents[{index}].vx"),
        vy=_finite_float(item.get("vy"), f"dynamic_agents[{index}].vy"),
        radius_m=radius,
        yaw=_finite_float(item.get("yaw", 0.0), f"dynamic_agents[{index}].yaw"),
        confidence=1.0,
    )


def _parse_lidar_obstacle(item: object, index: int) -> LidarObstacle:
    if not isinstance(item, dict):
        raise TypeError(f"simulator lidar_obstacles[{index}] must be an object")
    if not set(item).issubset({"id", "distance_m", "bearing_rad"}):
        raise ValueError(f"simulator lidar_obstacles[{index}] contains unsupported fields")
    distance = _finite_float(item.get("distance_m"), f"lidar_obstacles[{index}].distance_m")
    bearing = _finite_float(item.get("bearing_rad"), f"lidar_obstacles[{index}].bearing_rad")
    if not 0.0 <= distance <= 1000.0:
        raise ValueError(f"simulator lidar_obstacles[{index}].distance_m is outside the range")
    if not -math.pi <= bearing <= math.pi:
        raise ValueError(f"simulator lidar_obstacles[{index}].bearing_rad is outside the range")
    obstacle_id = item.get("id")
    if obstacle_id is not None and (
        not isinstance(obstacle_id, str) or not obstacle_id.strip() or len(obstacle_id) > 128
    ):
        raise TypeError(f"simulator lidar_obstacles[{index}].id must be a short string or null")
    return LidarObstacle(distance, bearing, obstacle_id)


def _parse_semantic_region(item: object, index: int) -> SemanticRegionTrack:
    if not isinstance(item, dict):
        raise TypeError(f"simulator semantic_regions[{index}] must be an object")
    allowed = {"id", "label", "polygon", "confidence", "source", "reachable", "metadata"}
    if not set(item).issubset(allowed):
        raise ValueError(f"simulator semantic_regions[{index}] contains unsupported fields")
    region_id, label = item.get("id"), item.get("label")
    if not isinstance(region_id, str) or not region_id.strip() or len(region_id) > 128:
        raise TypeError(f"simulator semantic_regions[{index}].id is invalid")
    if not isinstance(label, str) or not label.strip() or len(label) > 160:
        raise TypeError(f"simulator semantic_regions[{index}].label is invalid")
    raw_polygon = item.get("polygon")
    if not isinstance(raw_polygon, list) or not 3 <= len(raw_polygon) <= 256:
        raise TypeError(f"simulator semantic_regions[{index}].polygon is invalid")
    polygon = tuple(
        (
            _finite_float(point[0], f"semantic_regions[{index}].polygon.x"),
            _finite_float(point[1], f"semantic_regions[{index}].polygon.y"),
        )
        for point in raw_polygon
        if isinstance(point, list) and len(point) == 2
    )
    if len(polygon) != len(raw_polygon):
        raise TypeError(f"simulator semantic_regions[{index}].polygon points are invalid")
    confidence = _finite_float(item.get("confidence"), f"semantic_regions[{index}].confidence")
    if not 0.0 <= confidence <= 1.0:
        raise ValueError(f"simulator semantic_regions[{index}].confidence is invalid")
    metadata = item.get("metadata") or {}
    if not isinstance(metadata, dict):
        raise TypeError(f"simulator semantic_regions[{index}].metadata must be an object")
    reachable = item.get("reachable", True)
    if not isinstance(reachable, bool):
        raise TypeError(f"simulator semantic_regions[{index}].reachable must be a boolean")
    return SemanticRegionTrack(
        region_id=region_id,
        label=label,
        polygon=polygon,
        confidence=confidence,
        source=str(item.get("source", "simulator_semantic_camera")),
        reachable=reachable,
        metadata=dict(metadata),
    )


def _parse_semantic_object(item: object, index: int) -> SemanticObjectTrack:
    if not isinstance(item, dict):
        raise TypeError(f"simulator semantic_objects[{index}] must be an object")
    allowed = {"id", "label", "position", "confidence", "source", "reachable", "metadata"}
    if not set(item).issubset(allowed):
        raise ValueError(f"simulator semantic_objects[{index}] contains unsupported fields")
    object_id, label = item.get("id"), item.get("label")
    if not isinstance(object_id, str) or not object_id.strip() or len(object_id) > 128:
        raise TypeError(f"simulator semantic_objects[{index}].id is invalid")
    if not isinstance(label, str) or not label.strip() or len(label) > 160:
        raise TypeError(f"simulator semantic_objects[{index}].label is invalid")
    raw_position = item.get("position")
    if not isinstance(raw_position, list) or len(raw_position) != 3:
        raise TypeError(f"simulator semantic_objects[{index}].position is invalid")
    confidence = _finite_float(item.get("confidence"), f"semantic_objects[{index}].confidence")
    if not 0.0 <= confidence <= 1.0:
        raise ValueError(f"simulator semantic_objects[{index}].confidence is invalid")
    metadata = item.get("metadata") or {}
    if not isinstance(metadata, dict):
        raise TypeError(f"simulator semantic_objects[{index}].metadata must be an object")
    reachable = item.get("reachable", True)
    if not isinstance(reachable, bool):
        raise TypeError(f"simulator semantic_objects[{index}].reachable must be a boolean")
    return SemanticObjectTrack(
        object_id=object_id,
        label=label,
        position=tuple(
            _finite_float(value, f"semantic_objects[{index}].position")
            for value in raw_position
        ),
        confidence=confidence,
        source=str(item.get("source", "simulator_semantic_camera")),
        reachable=reachable,
        metadata=dict(metadata),
    )
