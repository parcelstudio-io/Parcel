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

from .base import DynamicAgentTrack, OwnerTrack, RobotPose, SimObservation

MAX_DYNAMIC_AGENTS = 64


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
            nearest_person_m=person_distance,
            nearest_person_bearing_rad=person_bearing,
            nearest_person_id=(str(person_detail["id"]) if person_detail.get("id") else None),
            nearest_person_ttc_s=person_ttc,
            dynamic_agents=dynamic_agents,
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
