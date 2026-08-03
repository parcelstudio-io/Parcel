from __future__ import annotations

import math
import time
from dataclasses import dataclass

from parcel_robot.backends.base import SimObservation
from parcel_robot.models import VelocityCommand


@dataclass(frozen=True)
class ReactiveSafetyPolicy:
    obstacle_stop_m: float = 0.65
    obstacle_slow_m: float = 1.2
    person_stop_m: float = 1.0
    person_slow_m: float = 2.0
    telemetry_stale_s: float = 0.6
    owner_collision_envelope_m: float = 0.55
    orbit_clearance_margin_m: float = 0.10
    orbit_waypoint_tolerance_m: float = 0.16
    reaction_time_s: float = 0.12

    def __post_init__(self) -> None:
        values = (
            self.obstacle_stop_m,
            self.obstacle_slow_m,
            self.person_stop_m,
            self.person_slow_m,
            self.telemetry_stale_s,
            self.owner_collision_envelope_m,
            self.orbit_clearance_margin_m,
            self.orbit_waypoint_tolerance_m,
            self.reaction_time_s,
        )
        if any(not math.isfinite(value) or value <= 0.0 for value in values):
            raise ValueError("reactive safety limits must be positive and finite")
        if self.obstacle_stop_m >= self.obstacle_slow_m:
            raise ValueError("obstacle stop distance must be below slow distance")
        if self.person_stop_m >= self.person_slow_m:
            raise ValueError("person stop distance must be below slow distance")


def apply_reactive_safety(
    command: VelocityCommand,
    observation: SimObservation | None,
    *,
    policy: ReactiveSafetyPolicy,
    owner_orbit: bool = False,
    orbit_radius_m: float = 0.0,
    now: float | None = None,
    require_fresh_telemetry: bool = True,
) -> tuple[VelocityCommand, str]:
    """Apply the final body-frame safety gate used in runtime and quality tests."""

    if observation is None:
        return _stop_translation(command) if _translating(command) else (command, "clear")
    timestamp = time.monotonic() if now is None else now
    if require_fresh_telemetry and timestamp - observation.timestamp > policy.telemetry_stale_s:
        return _stop_translation(command) if _translating(command) else (command, "clear")

    translating = _translating(command)
    predictive_state = "clear"
    owner_dx = observation.owner.x - observation.robot.x
    owner_dy = observation.owner.y - observation.robot.y
    owner_center_distance = math.hypot(owner_dx, owner_dy)
    people: list[tuple[float, float | None]] = []
    if observation.nearest_person_m is not None:
        people.append(
            (observation.nearest_person_m, observation.nearest_person_bearing_rad)
        )
    if observation.owner.visible and not owner_orbit:
        owner_clearance = max(
            0.0,
            owner_center_distance - policy.owner_collision_envelope_m,
        )
        people.append(
            (
                owner_clearance,
                _wrap(math.atan2(owner_dy, owner_dx) - observation.robot.yaw),
            )
        )
    for person_distance, person_bearing in people if translating else ():
        toward_person = _toward(command, person_bearing)
        predictive_person_stop = (
            policy.person_stop_m
            + math.hypot(command.vx, command.vy) * policy.reaction_time_s
        )
        if toward_person and person_distance <= predictive_person_stop:
            return _stop_translation(command)
        if toward_person and person_distance < policy.person_slow_m:
            scale = max(
                0.15,
                (person_distance - policy.person_stop_m)
                / (policy.person_slow_m - policy.person_stop_m),
            )
            command = _scale_translation(command, scale)
            predictive_state = "slowing"

    if owner_orbit and translating:
        minimum_center_distance = max(
            policy.obstacle_stop_m
            + policy.owner_collision_envelope_m
            + policy.orbit_clearance_margin_m,
            orbit_radius_m - policy.orbit_waypoint_tolerance_m,
        )
        owner_bearing = _wrap(
            math.atan2(owner_dy, owner_dx) - observation.robot.yaw
        )
        if owner_center_distance <= minimum_center_distance and _toward(
            command,
            owner_bearing,
            half_angle=math.pi / 2.0,
        ):
            return _stop_translation(command)

    person_ttc = observation.nearest_person_ttc_s
    if translating and person_ttc is not None:
        if person_ttc <= 0.8:
            return _stop_translation(command)
        if person_ttc < 1.8:
            command = _scale_translation(
                command,
                max(0.15, (person_ttc - 0.8) / 1.0),
            )
            predictive_state = "slowing"
    if not translating:
        return command, "clear"

    toward_obstacle = True
    distance: float | None
    if observation.lidar_obstacles:
        directional = [
            item
            for item in observation.lidar_obstacles
            if not (
                owner_orbit
                and item.obstacle_id is not None
                and item.obstacle_id.startswith("owner_")
            )
            if _toward(command, item.bearing_rad)
        ]
        if not directional:
            return command, predictive_state
        distance = min(directional, key=lambda item: item.distance_m).distance_m
    else:
        distance = observation.nearest_obstacle_m
        bearing = observation.nearest_obstacle_bearing_rad
        # A sparse range without a bearing fails closed for every translation.
        toward_obstacle = bearing is None or _toward(command, bearing)
    if observation.collision and toward_obstacle:
        return _stop_translation(command)
    if not toward_obstacle or distance is None:
        return command, predictive_state
    if distance <= policy.obstacle_stop_m:
        return _stop_translation(command)
    predictive_obstacle_stop = (
        policy.obstacle_stop_m
        + math.hypot(command.vx, command.vy) * policy.reaction_time_s
    )
    if distance <= predictive_obstacle_stop:
        return _stop_translation(command)
    if distance < policy.obstacle_slow_m:
        scale = max(
            0.15,
            (distance - policy.obstacle_stop_m)
            / (policy.obstacle_slow_m - policy.obstacle_stop_m),
        )
        return _scale_translation(command, scale), "slowing"
    return command, predictive_state


def _translating(command: VelocityCommand) -> bool:
    return math.hypot(command.vx, command.vy) > 1e-6


def _toward(
    command: VelocityCommand,
    bearing: float | None,
    *,
    half_angle: float = 1.15,
) -> bool:
    if bearing is None:
        return True
    travel_angle = math.atan2(command.vy, command.vx)
    return abs(_wrap(bearing - travel_angle)) < half_angle


def _scale_translation(command: VelocityCommand, scale: float) -> VelocityCommand:
    return VelocityCommand(
        vx=command.vx * scale,
        vy=command.vy * scale,
        vyaw=command.vyaw,
    )


def _stop_translation(command: VelocityCommand) -> tuple[VelocityCommand, str]:
    return VelocityCommand(vyaw=command.vyaw), "stopped"


def _wrap(angle: float) -> float:
    return (angle + math.pi) % (2.0 * math.pi) - math.pi
