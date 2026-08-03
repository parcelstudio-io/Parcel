from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class CollisionPolicy:
    """Soft social / obstacle braking thresholds (meters)."""

    person_stop_m: float = 1.2
    person_slow_m: float = 2.5
    obstacle_stop_m: float = 0.6
    obstacle_slow_m: float = 1.2
    slow_scale: float = 0.35


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
    speed = math.hypot(vx, vy)
    if nearest_obstacle_bearing_rad is not None and speed > 1e-6:
        travel_bearing = math.atan2(vy, vx)
        angle_error = (
            nearest_obstacle_bearing_rad - travel_bearing + math.pi
        ) % (2.0 * math.pi) - math.pi
        obstacle_relevant = abs(angle_error) < 1.15

    if nearest_obstacle_m is not None and obstacle_relevant:
        if nearest_obstacle_m < policy.obstacle_stop_m:
            return 0.0, 0.0, "obstacle_stop"
        if nearest_obstacle_m < policy.obstacle_slow_m:
            scale = min(scale, policy.slow_scale)
            note = "obstacle_slow" if note == "clear" else note

    return vx * scale, vy * scale, note
