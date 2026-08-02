from __future__ import annotations

from collections.abc import Callable

import numpy as np

RewardFn = Callable[[dict], float]


def pose_hold(info: dict) -> float:
    return float(info.get("pose_error", 0.0) * -1.0)


def jump_height(info: dict) -> float:
    return float(info.get("base_height", 0.0))


def kick_extension(info: dict) -> float:
    return float(info.get("kick_reach", 0.0))


def gesture_track(info: dict) -> float:
    return float(info.get("gesture_score", 0.0))


def standup_success(info: dict) -> float:
    return 1.0 if info.get("upright", False) else -0.1


def locomotion_velocity(info: dict) -> float:
    target = float(info.get("target_vx", 0.0))
    actual = float(info.get("actual_vx", 0.0))
    return -abs(target - actual)


def default_reward(info: dict) -> float:
    return float(info.get("reward", 0.0))


_REGISTRY: dict[str, RewardFn] = {
    "pose_hold": pose_hold,
    "jump_height": jump_height,
    "kick_extension": kick_extension,
    "gesture_track": gesture_track,
    "standup_success": standup_success,
    "locomotion_velocity": locomotion_velocity,
    "default": default_reward,
}


def reward_fn(name: str) -> RewardFn:
    return _REGISTRY.get(name, default_reward)


def compute_reward(name: str, info: dict) -> float:
    value = reward_fn(name)(info)
    if not np.isfinite(value):
        return 0.0
    return float(value)
