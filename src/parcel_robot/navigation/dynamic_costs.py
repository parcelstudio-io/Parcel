"""Pure-numpy dynamic-agent cost and collision-time calculations."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

# One dynamic-agent body radius for observation producers and the cost
# primitive they feed. It describes a tracked pedestrian, not the robot
# footprint; keeping it here prevents simulator/runtime payloads from growing
# independent copies of the primitive's own default.
DEFAULT_DYNAMIC_AGENT_RADIUS_M = 0.35


@dataclass(frozen=True)
class AgentTrack:
    x: float
    y: float
    vx: float
    vy: float
    radius_m: float = DEFAULT_DYNAMIC_AGENT_RADIUS_M


def _validated_tracks(tracks: Sequence[AgentTrack]) -> tuple[AgentTrack, ...]:
    result = tuple(tracks)
    for track in result:
        values = (track.x, track.y, track.vx, track.vy, track.radius_m)
        if not all(math.isfinite(value) for value in values):
            raise ValueError("agent track values must be finite")
        if track.radius_m < 0.0:
            raise ValueError("agent radius_m must be non-negative")
    return result


def _positive(value: float, name: str) -> float:
    value = float(value)
    if not math.isfinite(value) or value <= 0.0:
        raise ValueError(f"{name} must be finite and positive")
    return value


def agent_cost_at(
    tracks: Sequence[AgentTrack],
    query_xy: np.ndarray,
    *,
    horizon_s: float = 2.0,
    step_s: float = 0.2,
    decay_half_life_s: float = 0.8,
    sigma_m: float = 0.45,
) -> np.ndarray:
    """Return summed, clipped Gaussian occupancy along CV agent rollouts."""
    tracks = _validated_tracks(tracks)
    horizon_s = _positive(horizon_s, "horizon_s")
    step_s = _positive(step_s, "step_s")
    decay_half_life_s = _positive(decay_half_life_s, "decay_half_life_s")
    sigma_m = _positive(sigma_m, "sigma_m")
    query = np.asarray(query_xy, dtype=float)
    if query.ndim != 2 or query.shape[1] != 2:
        raise ValueError("query_xy must have shape (N, 2)")
    if not np.all(np.isfinite(query)):
        raise ValueError("query_xy must be finite")
    if not tracks:
        return np.zeros(query.shape[0], dtype=float)

    times = np.arange(0.0, horizon_s + step_s * 0.5, step_s)
    times = times[times <= horizon_s + 1e-12]
    weights = np.exp2(-times / decay_half_life_s)
    # Vectorize across the entire query, but accumulate one rollout lobe at a
    # time. Materializing query-by-(track*time) ``dx``, ``dy`` and Gaussian
    # matrices used several large temporaries and was slower on the target's
    # powersave cores. These cache-sized vectors preserve the same Gaussian
    # sum while reducing peak working memory and cold-core latency.
    query_x = query[:, 0]
    query_y = query[:, 1]
    costs = np.zeros(query.shape[0], dtype=float)
    for track in tracks:
        # Radius broadens each Gaussian instead of introducing a costly square
        # root to compute distance from a hard circular envelope.
        exponent_scale = -1.0 / (2.0 * (sigma_m + track.radius_m) ** 2)
        for at_s, weight in zip(times, weights, strict=True):
            dx = query_x - (track.x + track.vx * at_s)
            dy = query_y - (track.y + track.vy * at_s)
            costs += weight * np.exp((dx * dx + dy * dy) * exponent_scale)
    # Normalize by the per-track weight sum before clipping. Raw summation of
    # the default 11-step decay series peaks near 5.35 and clips to a flat
    # cost=1 mesa (metres wide), which erases the gradient A* needs. Dividing
    # keeps the frozen [0, 1] range while restoring shape. Arbitration 2026-08-04.
    weight_total = float(weights.sum()) * max(len(tracks), 1)
    if weight_total > 0.0:
        costs = costs / weight_total
    return np.clip(costs, 0.0, 1.0)


def time_to_collision_s(
    tracks: Sequence[AgentTrack],
    *,
    robot_xy: tuple[float, float],
    robot_v: tuple[float, float],
    robot_radius_m: float,
    horizon_s: float = 2.0,
) -> float:
    """Return earliest exact circle-circle contact under relative CV motion."""
    tracks = _validated_tracks(tracks)
    values = (*robot_xy, *robot_v, robot_radius_m, horizon_s)
    if not all(math.isfinite(value) for value in values):
        raise ValueError("robot state and horizon must be finite")
    if robot_radius_m < 0.0:
        raise ValueError("robot_radius_m must be non-negative")
    if horizon_s < 0.0:
        raise ValueError("horizon_s must be non-negative")

    earliest = math.inf
    robot_position = np.asarray(robot_xy, dtype=float)
    robot_velocity = np.asarray(robot_v, dtype=float)
    for track in tracks:
        relative_position = np.array((track.x, track.y)) - robot_position
        relative_velocity = np.array((track.vx, track.vy)) - robot_velocity
        radius = robot_radius_m + track.radius_m
        c = float(relative_position @ relative_position - radius * radius)
        if c <= 0.0:
            return 0.0
        a = float(relative_velocity @ relative_velocity)
        if a <= 1e-18:
            continue
        b = 2.0 * float(relative_position @ relative_velocity)
        discriminant = b * b - 4.0 * a * c
        if discriminant < 0.0:
            continue
        contact = (-b - math.sqrt(max(0.0, discriminant))) / (2.0 * a)
        if 0.0 <= contact <= horizon_s:
            earliest = min(earliest, contact)
    return earliest
