from __future__ import annotations

import math
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass, fields
from typing import Any, ClassVar

from parcel_robot.backends.base import SimObservation
from parcel_robot.models import VelocityCommand
from parcel_robot.navigation.reactive_safety import (
    ReactiveSafetyPolicy,
    apply_reactive_safety,
)


def _wrap_angle(angle: float) -> float:
    return (angle + math.pi) % (2.0 * math.pi) - math.pi


@dataclass(frozen=True)
class FollowConfig:
    """Bounds for direct follow and the camera-derived behind formation.

    ``OwnerTrack`` positions and observation timestamps are the only source of
    owner motion used here. In production those tracks must be camera-derived
    and transformed into the robot odometry frame before entering this
    controller; no simulator pose or actor heading is consumed.
    """

    MODES: ClassVar[frozenset[str]] = frozenset({"direct", "behind"})

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
    person_stop_m: float = 1.0
    person_slow_m: float = 2.0
    owner_collision_envelope_m: float = 0.55

    behind_distance_m: float = 1.9
    max_behind_distance_m: float = 3.0
    formation_deadband_m: float = 0.20
    owner_keepout_m: float = 1.55
    staging_radius_m: float = 2.1
    staging_lookahead_rad: float = 0.35
    heading_min_dt_s: float = 0.05
    heading_history_gap_s: float = 0.9
    heading_stale_after_s: float = 0.8
    heading_min_displacement_m: float = 0.08
    heading_min_speed_mps: float = 0.10
    heading_max_speed_mps: float = 3.0
    heading_smoothing_alpha: float = 0.35
    heading_min_updates: int = 2
    prediction_horizon_s: float = 0.25
    prediction_max_m: float = 0.25

    def __post_init__(self) -> None:
        numeric = [
            getattr(self, item.name)
            for item in fields(self)
            if item.name != "heading_min_updates"
        ]
        if any(not math.isfinite(value) or value <= 0.0 for value in numeric):
            raise ValueError("follow configuration values must be positive and finite")
        if self.obstacle_stop_m >= self.obstacle_slow_m:
            raise ValueError("follow obstacle stop distance must be below slow distance")
        if self.person_stop_m >= self.person_slow_m:
            raise ValueError("follow person stop distance must be below slow distance")
        if self.heading_min_dt_s >= self.heading_history_gap_s:
            raise ValueError("heading minimum dt must be below the history gap")
        if self.heading_stale_after_s > self.heading_history_gap_s:
            raise ValueError("heading stale time must not exceed the history gap")
        if self.heading_min_speed_mps >= self.heading_max_speed_mps:
            raise ValueError("heading minimum speed must be below maximum speed")
        if not 0.0 < self.heading_smoothing_alpha <= 1.0:
            raise ValueError("heading smoothing alpha must be in (0, 1]")
        if self.heading_min_updates < 1:
            raise ValueError("heading_min_updates must be positive")
        minimum_keepout = self.person_stop_m + self.owner_collision_envelope_m
        if self.owner_keepout_m + 1e-9 < minimum_keepout:
            raise ValueError(
                "owner_keepout_m must include person stop distance and owner envelope"
            )
        if self.behind_distance_m <= self.owner_keepout_m:
            raise ValueError("behind distance must be outside the owner keepout")
        if self.max_behind_distance_m < self.behind_distance_m:
            raise ValueError("maximum behind distance must include the default distance")
        if self.staging_radius_m < self.behind_distance_m:
            raise ValueError("staging radius must be at least the behind distance")
        if self.staging_lookahead_rad >= math.pi / 2.0:
            raise ValueError("staging lookahead must be below pi/2")

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> FollowConfig:
        """Load a strict optional config section without silently accepting typos."""

        allowed = {item.name for item in fields(cls)}
        unknown = set(raw) - allowed
        if unknown:
            raise ValueError(f"unknown owner_follow settings: {sorted(unknown)}")
        values: dict[str, float | int] = {}
        for key, value in raw.items():
            if key == "heading_min_updates":
                if isinstance(value, bool):
                    raise TypeError("heading_min_updates must be an integer")
                converted = int(value)
                if converted != value:
                    raise ValueError("heading_min_updates must be an integer")
                values[key] = converted
            else:
                values[key] = float(value)
        return cls(**values)


@dataclass(frozen=True)
class FollowDecision:
    state: str
    command: VelocityCommand
    reason: str
    distance_m: float | None = None
    owner_id: str | None = None
    mode: str = "direct"
    owner_heading_rad: float | None = None
    target_x_m: float | None = None
    target_y_m: float | None = None
    stage_side: str | None = None


@dataclass(frozen=True)
class _MotionEstimate:
    heading_rad: float
    speed_mps: float


class FollowOwnerController:
    """Fail-closed owner-follow controller over camera/LiDAR observations.

    The legacy/default ``direct`` mode retains the original distance-following
    behavior. ``behind`` is an explicit formation mode: it derives owner heading
    from timestamped owner tracks, and it never falls back to chasing the owner
    point when that heading is unavailable.
    """

    def __init__(
        self,
        config: FollowConfig | None = None,
        *,
        safety_policy: ReactiveSafetyPolicy | None = None,
    ):
        self.config = config or FollowConfig()
        self._lock = threading.RLock()
        self._enabled = False
        self._mode = "direct"
        self._last_seen_at: float | None = None
        self._state = "idle"
        self._last_owner_id: str | None = None
        self._last_track: tuple[float, float, float] | None = None
        self._heading_anchor: tuple[float, float, float] | None = None
        self._filtered_velocity: tuple[float, float] | None = None
        self._heading_updated_at: float | None = None
        self._heading_updates = 0
        self._last_passive_seen_at: float | None = None
        self._latest_track_valid = False
        self._latest_track_status = "not_observed"
        self._stage_side: int | None = None
        self._active_behind_distance_m = self.config.behind_distance_m
        self._safety_policy = safety_policy or ReactiveSafetyPolicy(
            obstacle_stop_m=self.config.obstacle_stop_m,
            obstacle_slow_m=self.config.obstacle_slow_m,
            person_stop_m=self.config.person_stop_m,
            person_slow_m=self.config.person_slow_m,
            telemetry_stale_s=self.config.stale_after_s,
            owner_collision_envelope_m=self.config.owner_collision_envelope_m,
        )
        policy_owner_keepout = (
            self._safety_policy.person_stop_m
            + self._safety_policy.owner_collision_envelope_m
        )
        if self.config.owner_keepout_m + 1e-9 < policy_owner_keepout:
            raise ValueError(
                "owner keepout must include the supplied safety policy's person envelope"
            )

    @property
    def enabled(self) -> bool:
        with self._lock:
            return self._enabled

    @property
    def state(self) -> str:
        with self._lock:
            return self._state

    @property
    def mode(self) -> str:
        with self._lock:
            return self._mode

    def start(self, mode: str = "direct") -> None:
        if mode not in self.config.MODES:
            raise ValueError(f"unknown follow mode: {mode}")
        with self._lock:
            self._enabled = True
            self._mode = mode
            self._active_behind_distance_m = self.config.behind_distance_m
            self._last_seen_at = None
            self._state = "acquiring" if mode == "direct" else "acquiring_heading"
            # Passive camera history deliberately survives activation. A plan
            # admitted on a fresh heading must not throw that evidence away at
            # the exact moment it acquires the base resource.
            self._stage_side = None

    def start_formation(self, relation: str, *, distance_m: float | None = None) -> None:
        """Semantic entry point used by a future ``FollowFormation`` PlanIR skill."""

        if relation != "behind":
            raise ValueError(f"unsupported owner formation relation: {relation}")
        distance = self.config.behind_distance_m if distance_m is None else float(distance_m)
        if not math.isfinite(distance):
            raise ValueError("behind formation distance must be finite")
        minimum = self.config.owner_keepout_m + 0.05
        if not minimum <= distance <= self.config.max_behind_distance_m:
            raise ValueError(
                "behind formation distance must be between "
                f"{minimum:.2f} and {self.config.max_behind_distance_m:.2f} meters"
            )
        with self._lock:
            self.start("behind")
            self._active_behind_distance_m = distance

    def stop(self) -> None:
        with self._lock:
            self._enabled = False
            self._mode = "direct"
            self._last_seen_at = None
            self._state = "idle"
            # Cancellation removes every active path choice and guarantees the
            # next step emits no motion. Fresh passive heading history may be
            # reused by a later, separately admitted formation request.
            self._stage_side = None
            self._active_behind_distance_m = self.config.behind_distance_m

    def observe_owner(
        self,
        observation: SimObservation | None,
        now: float | None = None,
    ) -> str:
        """Passively update camera-track motion history without producing motion.

        This method is safe to call on every perception tick regardless of
        whether follow is enabled. Its return value is diagnostic only; callers
        should use :meth:`heading_available` as the formation admission gate.
        """

        current = time.monotonic() if now is None else now
        with self._lock:
            return self._observe_owner_locked(observation, current)

    def heading_available(self, now: float | None = None) -> bool:
        current = time.monotonic() if now is None else now
        with self._lock:
            return self._motion_estimate(current) is not None

    def heading_snapshot(self, now: float | None = None) -> dict[str, object]:
        """Return bounded passive heading evidence for planner admission/telemetry."""

        current = time.monotonic() if now is None else now
        with self._lock:
            estimate = self._motion_estimate(current)
            return {
                "available": estimate is not None,
                "owner_id": self._last_owner_id,
                "heading_rad": estimate.heading_rad if estimate is not None else None,
                "speed_mps": estimate.speed_mps if estimate is not None else None,
                "track_status": self._latest_track_status,
                "track_age_s": (
                    max(0.0, current - self._last_passive_seen_at)
                    if self._last_passive_seen_at is not None
                    else None
                ),
            }

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
        motion_status = self._observe_owner_locked(observation, current)
        if not self._enabled:
            self._state = "idle"
            return self._decision(zero, "follow_disabled")
        if observation is None:
            self._state = "acquiring"
            return self._decision(zero, "no_observation")
        if current - observation.timestamp > self.config.stale_after_s:
            self._state = "stale"
            return self._decision(zero, "stale_observation")

        owner = observation.owner
        if not _finite_track(observation):
            self._state = "invalid"
            return self._decision(zero, "invalid_owner_track", owner_id=owner.owner_id)
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
            return self._decision(zero, reason, owner_id=owner.owner_id)

        self._last_seen_at = current
        if self._mode == "behind":
            return self._step_behind(observation, current, motion_status)
        return self._step_direct(observation)

    def _step_direct(self, observation: SimObservation) -> FollowDecision:
        owner = observation.owner
        dx = owner.x - observation.robot.x
        dy = owner.y - observation.robot.y
        distance = math.hypot(dx, dy)
        obstacle = observation.nearest_obstacle_m
        obstacle_bearing = observation.nearest_obstacle_bearing_rad
        obstacle_in_path = obstacle_bearing is None or abs(obstacle_bearing) < 1.15
        if observation.collision and obstacle_in_path:
            self._state = "blocked"
            return self._decision(
                VelocityCommand(), "collision_contact", distance, owner.owner_id
            )
        if (
            obstacle_in_path
            and obstacle is not None
            and obstacle <= self.config.obstacle_stop_m
        ):
            self._state = "blocked"
            return self._decision(VelocityCommand(), "obstacle_stop", distance, owner.owner_id)

        target_heading = math.atan2(dy, dx)
        yaw_error = _wrap_angle(target_heading - observation.robot.yaw)
        vyaw = _clamp(yaw_error * self.config.yaw_gain, self.config.max_vyaw)
        distance_error = distance - self.config.desired_distance_m
        if distance_error <= self.config.distance_deadband_m:
            self._state = "holding"
            turn = vyaw if abs(yaw_error) > 0.35 else 0.0
            return self._decision(
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
        return self._decision(
            VelocityCommand(vx=vx, vyaw=vyaw),
            "tracking_owner",
            distance,
            owner.owner_id,
        )

    def _step_behind(
        self,
        observation: SimObservation,
        current: float,
        motion_status: str,
    ) -> FollowDecision:
        owner = observation.owner
        owner_distance = math.hypot(
            owner.x - observation.robot.x,
            owner.y - observation.robot.y,
        )
        if observation.collision:
            self._state = "blocked"
            return self._decision(
                VelocityCommand(),
                "collision_contact",
                owner_distance,
                owner.owner_id,
            )
        if motion_status == "outlier":
            self._state = "holding"
            return self._decision(
                VelocityCommand(),
                "owner_motion_outlier",
                owner_distance,
                owner.owner_id,
            )
        estimate = self._motion_estimate(current)
        if estimate is None:
            self._state = "acquiring_heading"
            reason = (
                "owner_heading_stale"
                if self._heading_updated_at is not None
                and self._heading_updates >= self.config.heading_min_updates
                and current - self._heading_updated_at > self.config.heading_stale_after_s
                else "owner_heading_unavailable"
            )
            return self._decision(
                VelocityCommand(), reason, owner_distance, owner.owner_id
            )

        heading_x = math.cos(estimate.heading_rad)
        heading_y = math.sin(estimate.heading_rad)
        prediction = min(
            self.config.prediction_max_m,
            estimate.speed_mps * self.config.prediction_horizon_s,
        )
        effective_rear_distance = max(
            self.config.owner_keepout_m + 0.05,
            self._active_behind_distance_m - prediction,
        )
        target_x = owner.x - heading_x * effective_rear_distance
        target_y = owner.y - heading_y * effective_rear_distance
        robot_rel = (
            observation.robot.x - owner.x,
            observation.robot.y - owner.y,
        )
        target_rel = (target_x - owner.x, target_y - owner.y)
        direct_clearance = _segment_origin_clearance(robot_rel, target_rel)

        if direct_clearance + 1e-9 < self.config.owner_keepout_m:
            target_x, target_y, reason = self._staging_target(
                observation,
                target_heading=math.atan2(target_rel[1], target_rel[0]),
            )
            state = "staging"
        else:
            self._stage_side = None
            reason = "tracking_behind_anchor"
            state = "tracking_behind"

        target_distance = math.hypot(
            target_x - observation.robot.x,
            target_y - observation.robot.y,
        )
        if state == "tracking_behind" and target_distance <= self.config.formation_deadband_m:
            yaw_error = _wrap_angle(estimate.heading_rad - observation.robot.yaw)
            turn = (
                _clamp(yaw_error * self.config.yaw_gain, self.config.max_vyaw)
                if abs(yaw_error) > 0.25
                else 0.0
            )
            self._state = "holding_behind"
            return self._decision(
                VelocityCommand(vyaw=turn),
                "behind_formation_reached",
                owner_distance,
                owner.owner_id,
                owner_heading=estimate.heading_rad,
                target=(target_x, target_y),
            )

        command = self._command_to_target(observation, target_x, target_y)
        safe_command, safety_state = apply_reactive_safety(
            command,
            observation,
            policy=self._safety_policy,
            now=current,
        )
        if safety_state == "stopped" and math.hypot(command.vx, command.vy) > 1e-6:
            self._state = "blocked"
            reason = "formation_proximity_stop"
        else:
            self._state = state
            if safety_state == "slowing":
                reason = f"{reason}_slowed"
        return self._decision(
            safe_command,
            reason,
            owner_distance,
            owner.owner_id,
            owner_heading=estimate.heading_rad,
            target=(target_x, target_y),
        )

    def _observe_owner_locked(
        self,
        observation: SimObservation | None,
        current: float,
    ) -> str:
        if observation is None:
            self._latest_track_valid = False
            self._latest_track_status = "no_observation"
            return self._latest_track_status

        owner = observation.owner
        if owner.owner_id != self._last_owner_id:
            self._reset_motion_history()
            self._last_owner_id = owner.owner_id
        if current - observation.timestamp > self.config.stale_after_s:
            self._latest_track_valid = False
            self._latest_track_status = "stale_observation"
            return self._latest_track_status
        if not _finite_track(observation):
            self._latest_track_valid = False
            self._latest_track_status = "invalid_owner_track"
            return self._latest_track_status
        if not owner.visible:
            self._latest_track_valid = False
            self._latest_track_status = "owner_not_visible"
            return self._latest_track_status
        if owner.confidence < self.config.min_confidence:
            self._latest_track_valid = False
            self._latest_track_status = "owner_low_confidence"
            return self._latest_track_status

        status = self._update_motion_estimate(observation, current)
        self._latest_track_valid = status != "outlier"
        self._latest_track_status = status
        if self._latest_track_valid:
            self._last_passive_seen_at = current
        return status

    def _update_motion_estimate(
        self,
        observation: SimObservation,
        current: float,
    ) -> str:
        owner = observation.owner
        sample = (observation.timestamp, owner.x, owner.y)
        if owner.owner_id != self._last_owner_id:
            self._reset_motion_history()
            self._last_owner_id = owner.owner_id
            self._last_track = sample
            self._heading_anchor = sample
            return "seeded"
        if self._last_track is None or self._heading_anchor is None:
            self._last_track = sample
            self._heading_anchor = sample
            return "seeded"

        last_t, last_x, last_y = self._last_track
        dt_last = sample[0] - last_t
        if dt_last <= 0.0:
            if dt_last < 0.0:
                self._reset_motion_history()
                self._last_owner_id = owner.owner_id
                self._last_track = sample
                self._heading_anchor = sample
                return "clock_reset"
            return "duplicate"
        if dt_last > self.config.heading_history_gap_s:
            self._reset_motion_history()
            self._last_owner_id = owner.owner_id
            self._last_track = sample
            self._heading_anchor = sample
            return "history_gap"

        raw_step_speed = math.hypot(sample[1] - last_x, sample[2] - last_y) / dt_last
        if raw_step_speed > self.config.heading_max_speed_mps:
            return "outlier"
        self._last_track = sample

        anchor_t, anchor_x, anchor_y = self._heading_anchor
        dt = sample[0] - anchor_t
        if dt < self.config.heading_min_dt_s:
            return "insufficient_dt"
        dx = sample[1] - anchor_x
        dy = sample[2] - anchor_y
        displacement = math.hypot(dx, dy)
        speed = displacement / dt
        if (
            displacement < self.config.heading_min_displacement_m
            or speed < self.config.heading_min_speed_mps
        ):
            return "insufficient_motion"
        if speed > self.config.heading_max_speed_mps:
            return "outlier"

        raw_vx = dx / dt
        raw_vy = dy / dt
        if self._filtered_velocity is None:
            filtered = (raw_vx, raw_vy)
        else:
            alpha = self.config.heading_smoothing_alpha
            filtered = (
                alpha * raw_vx + (1.0 - alpha) * self._filtered_velocity[0],
                alpha * raw_vy + (1.0 - alpha) * self._filtered_velocity[1],
            )
        filtered_speed = math.hypot(*filtered)
        if filtered_speed < self.config.heading_min_speed_mps:
            return "insufficient_filtered_motion"
        if filtered_speed > self.config.heading_max_speed_mps:
            scale = self.config.heading_max_speed_mps / filtered_speed
            filtered = (filtered[0] * scale, filtered[1] * scale)
        self._filtered_velocity = filtered
        self._heading_anchor = sample
        self._heading_updated_at = current
        self._heading_updates += 1
        return "updated"

    def _motion_estimate(self, current: float) -> _MotionEstimate | None:
        if (
            not self._latest_track_valid
            or self._last_passive_seen_at is None
            or current - self._last_passive_seen_at > self.config.stale_after_s
            or self._filtered_velocity is None
            or self._heading_updated_at is None
            or self._heading_updates < self.config.heading_min_updates
            or current - self._heading_updated_at > self.config.heading_stale_after_s
        ):
            return None
        vx, vy = self._filtered_velocity
        return _MotionEstimate(
            math.atan2(vy, vx),
            min(math.hypot(vx, vy), self.config.heading_max_speed_mps),
        )

    def _staging_target(
        self,
        observation: SimObservation,
        *,
        target_heading: float,
    ) -> tuple[float, float, str]:
        """Select a persistent, collision-clear polar lookahead around the owner."""

        owner = observation.owner
        rx = observation.robot.x - owner.x
        ry = observation.robot.y - owner.y
        radius = math.hypot(rx, ry)
        robot_angle = math.atan2(ry, rx)
        if self._stage_side is None:
            delta = _wrap_angle(target_heading - robot_angle)
            self._stage_side = 1 if delta > 0.0 else -1
        side = self._stage_side

        # If the owner entered the keepout, move radially away before attempting
        # a tangential transition. This path cannot move through the owner.
        if radius + 1e-9 < self.config.owner_keepout_m:
            stage_angle = robot_angle
            reason = "recovering_owner_clearance"
        else:
            directed_remaining = (
                (target_heading - robot_angle) % (2.0 * math.pi)
                if side > 0
                else (robot_angle - target_heading) % (2.0 * math.pi)
            )
            lookahead = min(self.config.staging_lookahead_rad, directed_remaining)
            stage_angle = robot_angle + side * lookahead
            reason = "staging_around_owner"

        stage_radius = max(self.config.staging_radius_m, self.config.owner_keepout_m)
        stage_rel = (
            math.cos(stage_angle) * stage_radius,
            math.sin(stage_angle) * stage_radius,
        )
        if (
            radius >= self.config.owner_keepout_m
            and _segment_origin_clearance((rx, ry), stage_rel)
            + 1e-9
            < self.config.owner_keepout_m
        ):
            # A deliberately conservative fallback for unusual custom radii or
            # lookahead settings: establish radial clearance first.
            stage_rel = (
                math.cos(robot_angle) * stage_radius,
                math.sin(robot_angle) * stage_radius,
            )
            reason = "establishing_staging_clearance"
        return owner.x + stage_rel[0], owner.y + stage_rel[1], reason

    def _command_to_target(
        self,
        observation: SimObservation,
        target_x: float,
        target_y: float,
    ) -> VelocityCommand:
        dx = target_x - observation.robot.x
        dy = target_y - observation.robot.y
        distance = math.hypot(dx, dy)
        target_heading = math.atan2(dy, dx)
        yaw_error = _wrap_angle(target_heading - observation.robot.yaw)
        vyaw = _clamp(yaw_error * self.config.yaw_gain, self.config.max_vyaw)
        if distance <= self.config.formation_deadband_m:
            return VelocityCommand(vyaw=vyaw if abs(yaw_error) > 0.25 else 0.0)
        vx = min(self.config.max_vx, distance * self.config.distance_gain)
        if abs(yaw_error) >= self.config.turn_in_place_rad:
            vx = 0.0
        return VelocityCommand(vx=vx, vyaw=vyaw)

    def _decision(
        self,
        command: VelocityCommand,
        reason: str,
        distance: float | None = None,
        owner_id: str | None = None,
        *,
        owner_heading: float | None = None,
        target: tuple[float, float] | None = None,
    ) -> FollowDecision:
        return FollowDecision(
            state=self._state,
            command=command,
            reason=reason,
            distance_m=distance,
            owner_id=owner_id,
            mode=self._mode,
            owner_heading_rad=owner_heading,
            target_x_m=target[0] if target is not None else None,
            target_y_m=target[1] if target is not None else None,
            stage_side=(
                "left" if self._stage_side == 1 else "right" if self._stage_side == -1 else None
            ),
        )

    def _reset_motion_history(self) -> None:
        self._last_owner_id = None
        self._last_track = None
        self._heading_anchor = None
        self._filtered_velocity = None
        self._heading_updated_at = None
        self._heading_updates = 0
        self._last_passive_seen_at = None
        self._latest_track_valid = False
        self._latest_track_status = "not_observed"
        self._stage_side = None

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            estimate = self._motion_estimate(time.monotonic())
            return {
                "enabled": self._enabled,
                "state": self._state,
                "mode": self._mode,
                "desired_distance_m": (
                    self._active_behind_distance_m
                    if self._mode == "behind"
                    else self.config.desired_distance_m
                ),
                "heading_available": estimate is not None,
                "owner_heading_rad": estimate.heading_rad if estimate is not None else None,
                "owner_speed_mps": estimate.speed_mps if estimate is not None else None,
                "heading_track_status": self._latest_track_status,
                "stage_side": (
                    "left"
                    if self._stage_side == 1
                    else "right"
                    if self._stage_side == -1
                    else None
                ),
                "perception_basis": "camera_owner_track+robot_odometry+lidar",
            }


def _finite_track(observation: SimObservation) -> bool:
    return all(
        math.isfinite(value)
        for value in (
            observation.timestamp,
            observation.owner.x,
            observation.owner.y,
            observation.owner.confidence,
            observation.robot.x,
            observation.robot.y,
            observation.robot.yaw,
        )
    )


def _clamp(value: float, limit: float) -> float:
    return max(-limit, min(limit, value))


def _segment_origin_clearance(
    start: tuple[float, float],
    end: tuple[float, float],
) -> float:
    """Minimum distance from the owner origin to one proposed path segment."""

    dx = end[0] - start[0]
    dy = end[1] - start[1]
    length_sq = dx * dx + dy * dy
    if length_sq <= 1e-12:
        return math.hypot(*start)
    projection = -(start[0] * dx + start[1] * dy) / length_sq
    fraction = max(0.0, min(1.0, projection))
    return math.hypot(start[0] + fraction * dx, start[1] + fraction * dy)
