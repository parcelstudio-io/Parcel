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

from .base import OwnerTrack, RobotPose, SimObservation


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
            nearest_obstacle_id=(
                str(obstacle_detail["id"]) if obstacle_detail.get("id") else None
            ),
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
