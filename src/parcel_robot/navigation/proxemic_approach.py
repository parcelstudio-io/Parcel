"""Pure proxemic scoring for approach-pose candidates.

Approach-pose selection that only minimizes robot travel (see
``approach.safe_approach_pose``) lands goals beside pedestrian streams; the
person-stop gate then correctly refuses the final metre. This module scores
candidate poses by predicted pedestrian occupancy and TTC urgency so a later
wiring step can prefer quieter spots inside the same goal region.

Fail-closed: malformed inputs raise; empty / all-over-threshold candidate
sets return ``None``. Not wired into the navigator — Opus owns that.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from parcel_robot.navigation.dynamic_costs import (
    AgentTrack,
    agent_cost_at,
    time_to_collision_s,
)
from parcel_robot.robot_profile import DEFAULT_ROBOT_PROFILE, RobotProfile


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
class ProxemicApproachConfig:
    """Weights and horizons for approach-pose proxemic cost.

    Cost per pose is::

        cost = occupancy_weight * occupancy
             + ttc_weight * max(0, 1 - ttc / horizon_s)
             + distance_weight * (distance_to_robot / distance_norm_m)

    ``occupancy`` is the predicted pedestrian occupancy from
    ``agent_cost_at`` (proximity to the CV rollout). The TTC term is the
    urgency of contact for a *stationary* robot parked at the candidate
    pose — short contact time raises cost. Distance is a soft tie-break so
    social cost dominates when streams diverge.
    """

    occupancy_weight: float = 1.0
    ttc_weight: float = 1.0
    distance_weight: float = 0.05
    distance_norm_m: float = 8.0
    horizon_s: float = 2.0
    step_s: float = 0.2
    decay_half_life_s: float = 0.8
    sigma_m: float = 0.45
    #: Resolved in ``__post_init__`` from ``profile`` (or the module-level
    #: default profile). It used to bind ``ROBOT_FOOTPRINT_RADIUS_M`` as a
    #: dataclass field default — evaluated once at import, unreachable by an
    #: injected profile. ``None`` means "ask the profile".
    robot_radius_m: float | None = None
    profile: RobotProfile | None = None
    # Poses at or above this cost are rejected (fail-closed selection).
    reject_cost: float = 0.85

    def __post_init__(self) -> None:
        if self.profile is not None and not isinstance(self.profile, RobotProfile):
            raise TypeError("profile must be a RobotProfile")
        if self.robot_radius_m is None:
            body = self.profile if self.profile is not None else DEFAULT_ROBOT_PROFILE
            object.__setattr__(self, "robot_radius_m", body.footprint_radius_m)
        _non_negative(self.occupancy_weight, "occupancy_weight")
        _non_negative(self.ttc_weight, "ttc_weight")
        _non_negative(self.distance_weight, "distance_weight")
        _positive(self.distance_norm_m, "distance_norm_m")
        _positive(self.horizon_s, "horizon_s")
        _positive(self.step_s, "step_s")
        _positive(self.decay_half_life_s, "decay_half_life_s")
        _positive(self.sigma_m, "sigma_m")
        _non_negative(self.robot_radius_m, "robot_radius_m")
        _positive(self.reject_cost, "reject_cost")
        if self.step_s > self.horizon_s:
            raise ValueError("step_s must not exceed horizon_s")


def _as_pose_array(poses_xy: Sequence[tuple[float, float]] | np.ndarray) -> np.ndarray:
    if isinstance(poses_xy, Sequence) and len(poses_xy) == 0:
        return np.zeros((0, 2), dtype=float)
    query = np.asarray(poses_xy, dtype=float)
    if query.size == 0:
        return np.zeros((0, 2), dtype=float)
    if query.ndim == 1 and query.shape == (2,):
        query = query.reshape(1, 2)
    if query.ndim != 2 or query.shape[1] != 2:
        raise ValueError("poses_xy must have shape (N, 2)")
    if not np.all(np.isfinite(query)):
        raise ValueError("poses_xy must be finite")
    return query


def proxemic_costs(
    poses_xy: Sequence[tuple[float, float]] | np.ndarray,
    tracks: Sequence[AgentTrack],
    *,
    robot_xy: tuple[float, float] | None = None,
    config: ProxemicApproachConfig | None = None,
) -> np.ndarray:
    """Return per-pose proxemic cost (lower is quieter / safer).

    Empty ``tracks`` yields zero social cost (distance term only, if
    ``robot_xy`` is provided). Does not clamp to ``[0, 1]`` so callers can
    compare raw magnitudes against ``reject_cost``.
    """

    cfg = config if config is not None else ProxemicApproachConfig()
    query = _as_pose_array(poses_xy)
    if query.shape[0] == 0:
        return np.zeros(0, dtype=float)

    occupancy = agent_cost_at(
        tracks,
        query,
        horizon_s=cfg.horizon_s,
        step_s=cfg.step_s,
        decay_half_life_s=cfg.decay_half_life_s,
        sigma_m=cfg.sigma_m,
    )
    costs = cfg.occupancy_weight * occupancy

    if cfg.ttc_weight > 0.0:
        ttc_urgency = np.zeros(query.shape[0], dtype=float)
        for index, (px, py) in enumerate(query):
            ttc = time_to_collision_s(
                tracks,
                robot_xy=(float(px), float(py)),
                robot_v=(0.0, 0.0),
                robot_radius_m=cfg.robot_radius_m,
                horizon_s=cfg.horizon_s,
            )
            if math.isfinite(ttc):
                ttc_urgency[index] = max(0.0, 1.0 - float(ttc) / cfg.horizon_s)
        costs = costs + cfg.ttc_weight * ttc_urgency

    if robot_xy is not None and cfg.distance_weight > 0.0:
        rx, ry = robot_xy
        if not (math.isfinite(rx) and math.isfinite(ry)):
            raise ValueError("robot_xy must be finite")
        distances = np.hypot(query[:, 0] - rx, query[:, 1] - ry)
        costs = costs + cfg.distance_weight * (distances / cfg.distance_norm_m)

    return costs


def select_proxemic_approach(
    poses_xy: Sequence[tuple[float, float]] | np.ndarray,
    tracks: Sequence[AgentTrack],
    *,
    robot_xy: tuple[float, float] | None = None,
    config: ProxemicApproachConfig | None = None,
) -> tuple[float, float] | None:
    """Pick the lowest-cost pose under ``reject_cost``; else ``None``.

    Fail-closed: no candidates, or every candidate at/above the reject
    threshold, returns ``None`` rather than the least-bad stream landing.
    """

    cfg = config if config is not None else ProxemicApproachConfig()
    query = _as_pose_array(poses_xy)
    if query.shape[0] == 0:
        return None

    costs = proxemic_costs(query, tracks, robot_xy=robot_xy, config=cfg)
    admissible = np.flatnonzero(costs < cfg.reject_cost)
    if admissible.size == 0:
        return None
    best = int(admissible[int(np.argmin(costs[admissible]))])
    return (float(query[best, 0]), float(query[best, 1]))
