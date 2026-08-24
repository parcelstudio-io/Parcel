from __future__ import annotations

import math
import threading
from dataclasses import replace

from parcel_robot.contracts.navigation_snapshot_v2 import NavigationSnapshotV2
from parcel_robot.contracts.observation_carrier import ObservationCarrierV1
from parcel_robot.models import VelocityCommand
from parcel_robot.observation.carrier_view import carrier_view

from .models import RobotMotionState


class BufferedRobotStateSource:
    """Thread-safe feedback buffer used by simulator and test adapters."""

    name = "buffered"

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._latest: RobotMotionState | None = None
        self._sequence = 0
        self._started = False
        self._closed = False

    def start(self) -> None:
        with self._lock:
            if self._closed:
                raise RuntimeError("robot state source is closed")
            self._started = True

    def update(self, state: RobotMotionState) -> None:
        with self._lock:
            if self._closed:
                return
            if self._latest is not None:
                if state.sequence <= self._latest.sequence:
                    raise ValueError("robot state sequence must increase")
                if state.received_at < self._latest.received_at:
                    raise ValueError("robot state timestamps must not move backward")
            self._latest = state

    def update_observation(self, observation: ObservationCarrierV1) -> RobotMotionState:
        with self._lock:
            previous = self._latest
            self._sequence += 1
            sequence = self._sequence

        velocity = VelocityCommand()
        if previous is not None:
            dt = observation.timestamp - previous.received_at
            if 1e-6 < dt <= 1.0:
                odom_vx = (observation.robot.x - previous.position[0]) / dt
                odom_vy = (observation.robot.y - previous.position[1]) / dt
                cosine = math.cos(observation.robot.yaw)
                sine = math.sin(observation.robot.yaw)
                yaw_delta = math.atan2(
                    math.sin(observation.robot.yaw - previous.yaw),
                    math.cos(observation.robot.yaw - previous.yaw),
                )
                velocity = VelocityCommand(
                    vx=cosine * odom_vx + sine * odom_vy,
                    vy=-sine * odom_vx + cosine * odom_vy,
                    vyaw=yaw_delta / dt,
                )
        state = RobotMotionState(
            received_at=observation.timestamp,
            sequence=sequence,
            position=(observation.robot.x, observation.robot.y, observation.robot.z),
            yaw=observation.robot.yaw,
            velocity=velocity,
            # Environment collisions are handled by Parcel's external safety
            # gate. This field is reserved for the physical controller's own
            # hardware error code.
            error_code=0,
            source=observation.backend,
        )
        self.update(state)
        return state

    def latest(self) -> RobotMotionState | None:
        with self._lock:
            return replace(self._latest) if self._latest is not None else None

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._started = False
            self._latest = None


def update_state_source_from_snapshot(
    source: BufferedRobotStateSource, snapshot: NavigationSnapshotV2
) -> RobotMotionState:
    """Card A4's V2 entry point: synthesize feedback from a stamped snapshot."""

    return source.update_observation(carrier_view(snapshot))
