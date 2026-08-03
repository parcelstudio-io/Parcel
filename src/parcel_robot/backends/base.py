from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from parcel_robot.models import Pose, VelocityCommand


@dataclass(frozen=True)
class RobotPose:
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    yaw: float = 0.0


@dataclass(frozen=True)
class OwnerTrack:
    owner_id: str = "owner-1"
    x: float = 0.0
    y: float = 0.0
    visible: bool = False
    confidence: float = 0.0


@dataclass(frozen=True)
class DynamicAgentTrack:
    agent_id: str
    kind: str
    x: float
    y: float
    vx: float
    vy: float
    radius_m: float
    yaw: float = 0.0
    confidence: float = 1.0


@dataclass(frozen=True)
class LidarObstacle:
    """One bounded polar obstacle return from the local LiDAR adapter."""

    distance_m: float
    bearing_rad: float
    obstacle_id: str | None = None


@dataclass(frozen=True)
class SimObservation:
    timestamp: float
    robot: RobotPose
    owner: OwnerTrack
    nearest_obstacle_m: float | None = None
    nearest_obstacle_bearing_rad: float | None = None
    nearest_obstacle_id: str | None = None
    lidar_obstacles: tuple[LidarObstacle, ...] = ()
    nearest_person_m: float | None = None
    nearest_person_bearing_rad: float | None = None
    nearest_person_id: str | None = None
    nearest_person_ttc_s: float | None = None
    dynamic_agents: tuple[DynamicAgentTrack, ...] = ()
    collision: bool = False
    emergency_stopped: bool = False
    backend: str = "unknown"


class SimulatorBackend(Protocol):
    name: str

    def observe(self) -> SimObservation: ...

    def move(self, command: VelocityCommand) -> None: ...

    def stop(self) -> None: ...

    def pose(self, pose: Pose) -> None: ...

    def trajectory(self, skill: object) -> None: ...

    def move_owner(self, dx: float, dy: float) -> None: ...
