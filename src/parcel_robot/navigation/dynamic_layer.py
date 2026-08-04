"""Card W4: dynamic-agent costs for `grid_v1` and the outgoing-command TTC gate.

This module is the *wiring* between Sol's pure `dynamic_costs` primitives and
Parcel's planner and safety path. It owns two things and nothing else:

* the fail-closed configuration for both halves, and
* the translation from observation tracks into the primitives' inputs.

It deliberately contains no geometric safety logic of its own. The
unconditional last line of defence remains `collision.py` / `reactive_safety.py`,
which this module never touches: the TTC gate only ever multiplies an already
admitted command by a factor in [0, 1].
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, fields
from typing import Any

import numpy as np

from parcel_robot.navigation.dynamic_costs import AgentTrack, agent_cost_at, time_to_collision_s

# A planner tick has a hard budget; a pathological track list must not blow it.
MAX_TRACKS = 16


def _positive(value: float, name: str) -> float:
    value = float(value)
    if not math.isfinite(value) or value <= 0.0:
        raise ValueError(f"{name} must be finite and positive")
    return value


def _non_negative(value: float, name: str) -> float:
    value = float(value)
    if not math.isfinite(value) or value < 0.0:
        raise ValueError(f"{name} must be finite and non-negative")
    return value


@dataclass(frozen=True)
class DynamicAgentCostConfig:
    """Planner-side settings for `navigation.models.grid_v1.dynamic_agents`.

    ``owner_weight`` is deliberately separate from ``weight``: a follower that
    reads its own owner as an obstacle wall cannot follow. The owner keeps a
    reduced lobe so the planner still routes around them politely, which is the
    same social-envelope distinction the runtime already makes elsewhere.
    """

    enabled: bool = False
    weight: float = 2.5
    owner_weight: float = 0.6
    horizon_s: float = 2.0
    step_s: float = 0.2
    decay_half_life_s: float = 0.8
    sigma_m: float = 0.45
    # Cells further than this from the robot are never scored: the rolling
    # window is 16 m across and a pedestrian eight metres away cannot change
    # this tick's route.
    window_radius_m: float = 6.0

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise TypeError("dynamic_agents.enabled must be a boolean")
        _positive(self.horizon_s, "dynamic_agents.horizon_s")
        _positive(self.step_s, "dynamic_agents.step_s")
        _positive(self.decay_half_life_s, "dynamic_agents.decay_half_life_s")
        _positive(self.sigma_m, "dynamic_agents.sigma_m")
        _positive(self.window_radius_m, "dynamic_agents.window_radius_m")
        _non_negative(self.weight, "dynamic_agents.weight")
        _non_negative(self.owner_weight, "dynamic_agents.owner_weight")
        if self.step_s > self.horizon_s:
            raise ValueError("dynamic_agents.step_s must not exceed horizon_s")
        if self.owner_weight > self.weight:
            raise ValueError(
                "dynamic_agents.owner_weight must not exceed weight: the owner is "
                "followed, not avoided harder than a stranger"
            )

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> DynamicAgentCostConfig:
        allowed = {item.name for item in fields(cls)}
        unknown = set(raw) - allowed
        if unknown:
            raise ValueError(f"unknown grid_v1 dynamic_agents settings: {sorted(unknown)}")
        values: dict[str, Any] = {}
        for key, value in raw.items():
            if key == "enabled":
                if not isinstance(value, bool):
                    raise TypeError("dynamic_agents.enabled must be a boolean")
                values[key] = value
            else:
                values[key] = float(value)
        return cls(**values)


@dataclass(frozen=True)
class TimeToCollisionConfig:
    """Runtime-side settings for `safety.time_to_collision`.

    This gate supplements the geometric proximity gate; it never replaces it.
    Between ``stop_s`` and ``brake_s`` the outgoing command is scaled linearly
    toward zero, and below ``stop_s`` it is zeroed.
    """

    enabled: bool = False
    brake_s: float = 2.0
    stop_s: float = 0.8
    robot_radius_m: float = 0.35
    # Floor on the scale factor while braking, so a distant predicted contact
    # cannot creep the robot to a crawl for a full corridor length.
    min_scale: float = 0.0

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise TypeError("safety.time_to_collision.enabled must be a boolean")
        _positive(self.brake_s, "safety.time_to_collision.brake_s")
        _positive(self.stop_s, "safety.time_to_collision.stop_s")
        _positive(self.robot_radius_m, "safety.time_to_collision.robot_radius_m")
        if self.stop_s >= self.brake_s:
            raise ValueError("safety.time_to_collision.stop_s must be below brake_s")
        if not math.isfinite(self.min_scale) or not 0.0 <= self.min_scale < 1.0:
            raise ValueError("safety.time_to_collision.min_scale must be within [0, 1)")

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> TimeToCollisionConfig:
        allowed = {item.name for item in fields(cls)}
        unknown = set(raw) - allowed
        if unknown:
            raise ValueError(f"unknown safety.time_to_collision settings: {sorted(unknown)}")
        values: dict[str, Any] = {}
        for key, value in raw.items():
            if key == "enabled":
                if not isinstance(value, bool):
                    raise TypeError("safety.time_to_collision.enabled must be a boolean")
                values[key] = value
            else:
                values[key] = float(value)
        return cls(**values)

    def scale_for(self, ttc_s: float) -> float:
        """Return the braking factor for one time-to-collision, never above 1."""

        if not math.isfinite(ttc_s):
            return 1.0
        if ttc_s >= self.brake_s:
            return 1.0
        if ttc_s <= self.stop_s:
            return 0.0
        span = self.brake_s - self.stop_s
        ramp = (ttc_s - self.stop_s) / span
        return max(self.min_scale, min(1.0, ramp))


def tracks_from_payload(payload: Iterable[Mapping[str, Any]]) -> tuple[AgentTrack, ...]:
    """Build validated tracks from the runtime's serialized agent payload.

    A malformed entry is a perception-contract failure, not something to guess
    around, so it raises rather than being dropped.
    """

    tracks: list[AgentTrack] = []
    for index, item in enumerate(payload):
        if len(tracks) >= MAX_TRACKS:
            break
        try:
            track = AgentTrack(
                x=float(item["x"]),
                y=float(item["y"]),
                vx=float(item["vx"]),
                vy=float(item["vy"]),
                radius_m=float(item.get("radius_m", 0.35)),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f"dynamic agent payload entry {index} is malformed") from error
        values = (track.x, track.y, track.vx, track.vy, track.radius_m)
        if not all(math.isfinite(value) for value in values):
            raise ValueError(f"dynamic agent payload entry {index} is not finite")
        tracks.append(track)
    return tuple(tracks)


def merged_cost_mask(
    *,
    config: DynamicAgentCostConfig,
    agent_tracks: Sequence[AgentTrack],
    owner_tracks: Sequence[AgentTrack],
    cell_centers_xy: np.ndarray,
    robot_xy: tuple[float, float],
) -> np.ndarray:
    """Return the additive per-cell A* penalty for this tick's tracks.

    Agents and the owner are scored separately so the owner's reduced weight is
    applied to the owner's lobe alone rather than to a blended field.
    """

    query = np.asarray(cell_centers_xy, dtype=float)
    if query.ndim != 2 or query.shape[1] != 2:
        raise ValueError("cell_centers_xy must have shape (N, 2)")
    costs = np.zeros(query.shape[0], dtype=np.float32)
    if not config.enabled or query.size == 0:
        return costs

    # Only score the neighbourhood the route can actually reach this tick.
    offsets = query - np.asarray(robot_xy, dtype=float)
    near = np.einsum("ij,ij->i", offsets, offsets) <= config.window_radius_m**2
    if not bool(near.any()):
        return costs
    window = query[near]

    for tracks, weight in ((agent_tracks, config.weight), (owner_tracks, config.owner_weight)):
        if not tracks or weight <= 0.0:
            continue
        lobes = agent_cost_at(
            tracks,
            window,
            horizon_s=config.horizon_s,
            step_s=config.step_s,
            decay_half_life_s=config.decay_half_life_s,
            sigma_m=config.sigma_m,
        )
        costs[near] += (weight * lobes).astype(np.float32)
    return costs


def minimum_time_to_collision_s(
    *,
    config: TimeToCollisionConfig,
    tracks: Sequence[AgentTrack],
    robot_xy: tuple[float, float],
    robot_v: tuple[float, float],
) -> float:
    """Earliest predicted contact for the candidate command, or infinity."""

    if not config.enabled or not tracks:
        return math.inf
    return time_to_collision_s(
        tracks,
        robot_xy=robot_xy,
        robot_v=robot_v,
        robot_radius_m=config.robot_radius_m,
        horizon_s=config.brake_s,
    )


def body_to_world(
    vx: float,
    vy: float,
    yaw_rad: float,
) -> tuple[float, float]:
    """Rotate a body-frame linear command into the track frame."""

    cos_yaw = math.cos(yaw_rad)
    sin_yaw = math.sin(yaw_rad)
    return (vx * cos_yaw - vy * sin_yaw, vx * sin_yaw + vy * cos_yaw)


@dataclass(frozen=True)
class TimeToCollisionVerdict:
    """One tick of the predictive brake: the scale it chose, and why."""

    scale: float
    time_to_collision_s: float
    proximity_state: str

    @property
    def intervened(self) -> bool:
        return self.scale < 1.0


def time_to_collision_verdict(
    *,
    config: TimeToCollisionConfig,
    tracks: Sequence[AgentTrack],
    robot_xy: tuple[float, float],
    robot_yaw_rad: float,
    command_vx: float,
    command_vy: float,
    proximity_state: str,
) -> TimeToCollisionVerdict:
    """Decide the predictive brake for one outgoing command.

    This is the whole gate, shared by the runtime dispatch and the eval bench
    so the two cannot drift. It returns a scale in [0, 1] and never a command:
    the caller multiplies, which makes it structurally impossible for this to
    release something an earlier authority stopped.
    """

    if not config.enabled:
        return TimeToCollisionVerdict(1.0, math.inf, proximity_state)
    ttc = minimum_time_to_collision_s(
        config=config,
        tracks=tracks,
        robot_xy=robot_xy,
        robot_v=body_to_world(command_vx, command_vy, robot_yaw_rad),
    )
    scale = config.scale_for(ttc)
    if scale >= 1.0:
        return TimeToCollisionVerdict(1.0, ttc, proximity_state)
    moving = math.hypot(command_vx, command_vy) > 1e-9
    if scale <= 0.0 and moving:
        state = "stopped"
    elif proximity_state == "clear":
        state = "slowing"
    else:
        state = proximity_state
    return TimeToCollisionVerdict(scale, ttc, state)


__all__ = [
    "MAX_TRACKS",
    "AgentTrack",
    "DynamicAgentCostConfig",
    "TimeToCollisionConfig",
    "TimeToCollisionVerdict",
    "body_to_world",
    "merged_cost_mask",
    "minimum_time_to_collision_s",
    "time_to_collision_verdict",
    "tracks_from_payload",
]
