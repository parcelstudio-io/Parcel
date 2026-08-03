from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

PredictiveBrakeMode = Literal[
    "stop",
    "speed_cap",
    "projected_speed_cap",
    "all_ray_yaw_swept_projected_speed_cap",
]

_ALL_RAY_MODE = "all_ray_yaw_swept_projected_speed_cap"
_PROJECTED_CAP_MODES = {"projected_speed_cap"}
_TRANSLATIONAL_CAP_MODES = {"speed_cap", *_PROJECTED_CAP_MODES}


@dataclass(frozen=True)
class CollisionPolicy:
    """Soft social / obstacle braking thresholds (meters)."""

    person_stop_m: float = 1.2
    person_slow_m: float = 2.5
    obstacle_stop_m: float = 0.6
    obstacle_slow_m: float = 1.2
    slow_scale: float = 0.35
    reaction_time_s: float = 0.12
    predictive_mode: PredictiveBrakeMode = "stop"

    def __post_init__(self) -> None:
        values = (
            self.person_stop_m,
            self.person_slow_m,
            self.obstacle_stop_m,
            self.obstacle_slow_m,
            self.reaction_time_s,
        )
        if any(not math.isfinite(value) or value <= 0.0 for value in values):
            raise ValueError("collision distances and reaction time must be positive and finite")
        if self.person_stop_m >= self.person_slow_m:
            raise ValueError("person stop distance must be below slow distance")
        if self.obstacle_stop_m >= self.obstacle_slow_m:
            raise ValueError("obstacle stop distance must be below slow distance")
        if not math.isfinite(self.slow_scale) or not 0.0 < self.slow_scale <= 1.0:
            raise ValueError("collision slow scale must be in (0, 1]")
        if self.predictive_mode not in {
            "stop",
            *_TRANSLATIONAL_CAP_MODES,
            _ALL_RAY_MODE,
        }:
            raise ValueError(
                "predictive_mode must be 'stop', 'speed_cap', or "
                "'projected_speed_cap', or "
                "'all_ray_yaw_swept_projected_speed_cap'"
            )


def apply_collision_brake(
    vx: float,
    vy: float,
    *,
    nearest_person_m: float | None,
    nearest_obstacle_m: float | None,
    nearest_obstacle_bearing_rad: float | None = None,
    policy: CollisionPolicy | None = None,
) -> tuple[float, float, str]:
    """Scale mid-level velocity; never invents perception — caller supplies ranges."""
    policy = policy or CollisionPolicy()
    note = "clear"
    scale = 1.0

    if nearest_person_m is not None:
        if nearest_person_m < policy.person_stop_m:
            return 0.0, 0.0, "person_stop"
        if nearest_person_m < policy.person_slow_m:
            scale = min(scale, policy.slow_scale)
            note = "person_slow"

    obstacle_relevant = True
    obstacle_comfort_relevant = True
    speed = math.hypot(vx, vy)
    closing_fraction = 1.0
    if nearest_obstacle_bearing_rad is not None and speed > 1e-6:
        travel_bearing = math.atan2(vy, vx)
        angle_error = (
            nearest_obstacle_bearing_rad - travel_bearing + math.pi
        ) % (2.0 * math.pi) - math.pi
        closing_fraction = max(0.0, math.cos(angle_error))
        if policy.predictive_mode in _TRANSLATIONAL_CAP_MODES:
            # A hard-boundary cap must cover every obstacle with a positive
            # closing component, including bearings just outside the legacy
            # comfort-brake cone. Purely tangential/away motion remains free.
            obstacle_relevant = closing_fraction > 1e-9
            if policy.predictive_mode in _PROJECTED_CAP_MODES:
                # The hard cap covers every positive-closing return. Keep the
                # softer comfort slowdown directional so a nearby tangential
                # obstacle cannot needlessly stall a safe path around it.
                obstacle_comfort_relevant = abs(angle_error) < 1.15
        else:
            obstacle_relevant = abs(angle_error) < 1.15
            obstacle_comfort_relevant = obstacle_relevant

    if nearest_obstacle_m is not None and obstacle_relevant:
        if policy.predictive_mode == "stop":
            # Legacy/default semantics: stop whenever the requested velocity
            # could cross the hard boundary within one reaction horizon.
            predictive_stop_m = policy.obstacle_stop_m + speed * policy.reaction_time_s
            if nearest_obstacle_m <= predictive_stop_m:
                return 0.0, 0.0, "obstacle_stop"
        elif (
            policy.predictive_mode != _ALL_RAY_MODE
            and nearest_obstacle_m <= policy.obstacle_stop_m
        ):
            return 0.0, 0.0, "obstacle_stop"

        # The experimental all-ray mode deliberately keeps only this legacy
        # comfort/social layer. Its hard predictive boundary is enforced once,
        # after velocity bounds, against every observed finite scan return by
        # the pipeline's final all-ray shield.

        if nearest_obstacle_m < policy.obstacle_slow_m and obstacle_comfort_relevant:
            scale = min(scale, policy.slow_scale)
            note = "obstacle_slow" if note == "clear" else note

        if policy.predictive_mode in _TRANSLATIONAL_CAP_MODES and speed > 1e-6:
            # Keep one reaction horizon of stopping room without deadlocking
            # merely because the upstream controller requested cruise speed.
            # Direction is preserved; only translational magnitude is capped.
            allowed_closing_speed = max(
                0.0,
                (nearest_obstacle_m - policy.obstacle_stop_m)
                / policy.reaction_time_s,
            )
            speed_limit = (
                allowed_closing_speed
                if policy.predictive_mode == "speed_cap"
                else allowed_closing_speed / closing_fraction
            )
            cap_scale = min(1.0, speed_limit / speed)
            if cap_scale < scale:
                scale = cap_scale
                if note != "person_slow":
                    note = (
                        "obstacle_projected_speed_cap"
                        if policy.predictive_mode in _PROJECTED_CAP_MODES
                        else "obstacle_speed_cap"
                    )

    return vx * scale, vy * scale, note
