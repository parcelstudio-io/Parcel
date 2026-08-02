from __future__ import annotations

from typing import Any


def social_nav_reward(
    *,
    progress: float,
    dist_to_goal: float,
    nearest_person_m: float | None,
    nearest_obstacle_m: float | None,
    collided: bool,
    arrived: bool,
    people_weight: float = 1.0,
    obstacle_weight: float = 1.0,
) -> tuple[float, dict[str, Any]]:
    """Dense social-navigation reward used by MetaUrbanNavEnv / offline stub."""
    info: dict[str, Any] = {}
    reward = 0.0

    reward += 0.5 * progress
    reward += max(0.0, 2.0 - dist_to_goal) * 0.05
    info["progress_term"] = progress

    if nearest_person_m is not None:
        if nearest_person_m < 0.6:
            penalty = -2.0 * people_weight
        elif nearest_person_m < 1.5:
            penalty = -0.4 * people_weight * (1.5 - nearest_person_m)
        else:
            penalty = 0.0
        reward += penalty
        info["person_penalty"] = penalty

    if nearest_obstacle_m is not None:
        if nearest_obstacle_m < 0.4:
            penalty = -2.0 * obstacle_weight
        elif nearest_obstacle_m < 1.0:
            penalty = -0.3 * obstacle_weight * (1.0 - nearest_obstacle_m)
        else:
            penalty = 0.0
        reward += penalty
        info["obstacle_penalty"] = penalty

    if collided:
        reward -= 5.0
        info["collision"] = True
    if arrived:
        reward += 10.0
        info["arrived"] = True

    return float(reward), info
