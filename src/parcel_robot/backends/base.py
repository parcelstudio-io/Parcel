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
class SimObservation:
    timestamp: float
    robot: RobotPose
    owner: OwnerTrack
    nearest_obstacle_m: float | None = None
    nearest_obstacle_bearing_rad: float | None = None
    nearest_obstacle_id: str | None = None
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
