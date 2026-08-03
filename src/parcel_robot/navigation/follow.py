from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass

from parcel_robot.backends.base import SimObservation
from parcel_robot.models import VelocityCommand


def _wrap_angle(angle: float) -> float:
    return (angle + math.pi) % (2.0 * math.pi) - math.pi


@dataclass(frozen=True)
class FollowConfig:
    desired_distance_m: float = 1.6
    distance_deadband_m: float = 0.18
    max_vx: float = 0.35
    max_vyaw: float = 0.75
    distance_gain: float = 0.65
    yaw_gain: float = 1.2
    turn_in_place_rad: float = 0.8
    min_confidence: float = 0.65
    occlusion_grace_s: float = 0.7
    stale_after_s: float = 0.6
    obstacle_stop_m: float = 0.65
    obstacle_slow_m: float = 1.25


@dataclass(frozen=True)
class FollowDecision:
    state: str
    command: VelocityCommand
    reason: str
    distance_m: float | None = None
    owner_id: str | None = None


class FollowOwnerController:
    """Fail-closed owner-follow controller over an engine-neutral observation."""

    def __init__(self, config: FollowConfig | None = None):
        self.config = config or FollowConfig()
        self._lock = threading.RLock()
        self._enabled = False
        self._last_seen_at: float | None = None
        self._state = "idle"

    @property
    def enabled(self) -> bool:
        with self._lock:
            return self._enabled

    @property
    def state(self) -> str:
        with self._lock:
            return self._state

    def start(self) -> None:
        with self._lock:
            self._enabled = True
            self._last_seen_at = None
            self._state = "acquiring"

    def stop(self) -> None:
        with self._lock:
            self._enabled = False
            self._last_seen_at = None
            self._state = "idle"

    def step(
        self,
        observation: SimObservation | None,
        now: float | None = None,
    ) -> FollowDecision:
        with self._lock:
            return self._step_locked(observation, now)

    def _step_locked(
        self,
        observation: SimObservation | None,
        now: float | None,
    ) -> FollowDecision:
        current = time.monotonic() if now is None else now
        zero = VelocityCommand()
        if not self._enabled:
            self._state = "idle"
            return FollowDecision(self._state, zero, "follow_disabled")
        if observation is None:
            self._state = "acquiring"
            return FollowDecision(self._state, zero, "no_observation")
        if current - observation.timestamp > self.config.stale_after_s:
            self._state = "stale"
            return FollowDecision(self._state, zero, "stale_observation")

        owner = observation.owner
        if not owner.visible or owner.confidence < self.config.min_confidence:
            if (
                self._last_seen_at is not None
                and current - self._last_seen_at <= self.config.occlusion_grace_s
            ):
                self._state = "occluded"
                reason = "owner_temporarily_occluded"
            else:
                self._state = "lost" if self._last_seen_at is not None else "acquiring"
                reason = "owner_lost" if self._last_seen_at is not None else "owner_not_acquired"
            return FollowDecision(self._state, zero, reason, owner_id=owner.owner_id)

        self._last_seen_at = current
        dx = owner.x - observation.robot.x
        dy = owner.y - observation.robot.y
        distance = math.hypot(dx, dy)
        obstacle = observation.nearest_obstacle_m
        obstacle_bearing = observation.nearest_obstacle_bearing_rad
        obstacle_in_path = obstacle_bearing is None or abs(obstacle_bearing) < 1.15
        if observation.collision and obstacle_in_path:
            self._state = "blocked"
            return FollowDecision(
                self._state, zero, "collision_contact", distance, owner.owner_id
            )
        if (
            obstacle_in_path
            and obstacle is not None
            and obstacle <= self.config.obstacle_stop_m
        ):
            self._state = "blocked"
            return FollowDecision(
                self._state, zero, "obstacle_stop", distance, owner.owner_id
            )

        target_heading = math.atan2(dy, dx)
        yaw_error = _wrap_angle(target_heading - observation.robot.yaw)
        vyaw = max(
            -self.config.max_vyaw,
            min(self.config.max_vyaw, yaw_error * self.config.yaw_gain),
        )
        distance_error = distance - self.config.desired_distance_m
        if distance_error <= self.config.distance_deadband_m:
            self._state = "holding"
            turn = vyaw if abs(yaw_error) > 0.35 else 0.0
            return FollowDecision(
                self._state,
                VelocityCommand(vyaw=turn),
                "at_follow_distance",
                distance,
                owner.owner_id,
            )

        vx = min(self.config.max_vx, distance_error * self.config.distance_gain)
        if abs(yaw_error) >= self.config.turn_in_place_rad:
            vx = 0.0
        elif (
            obstacle_in_path
            and obstacle is not None
            and obstacle < self.config.obstacle_slow_m
        ):
            span = self.config.obstacle_slow_m - self.config.obstacle_stop_m
            scale = max(0.2, (obstacle - self.config.obstacle_stop_m) / span)
            vx *= scale
        self._state = "following"
        return FollowDecision(
            self._state,
            VelocityCommand(vx=vx, vyaw=vyaw),
            "tracking_owner",
            distance,
            owner.owner_id,
        )

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return {
                "enabled": self._enabled,
                "state": self._state,
                "desired_distance_m": self.config.desired_distance_m,
            }
