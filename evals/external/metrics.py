"""Standard navigation success metrics used by Habitat / BARN / SocialNav / 3WE."""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from itertools import pairwise


def path_length(path: Sequence[tuple[float, float]]) -> float:
    """Polyline length in meters."""
    if len(path) < 2:
        return 0.0
    total = 0.0
    for (x0, y0), (x1, y1) in pairwise(path):
        total += math.hypot(x1 - x0, y1 - y0)
    return float(total)


def euclidean(a: tuple[float, float], b: tuple[float, float]) -> float:
    return float(math.hypot(b[0] - a[0], b[1] - a[1]))


def success_weighted_path_length(
    *,
    success: bool,
    shortest_path_m: float,
    agent_path_m: float,
) -> float:
    """Anderson et al. SPL for a single episode (0 if failure)."""
    if not success:
        return 0.0
    shortest = max(0.0, float(shortest_path_m))
    agent = max(0.0, float(agent_path_m))
    if shortest == 0.0 and agent == 0.0:
        return 1.0
    denom = max(agent, shortest, 1e-9)
    return float(shortest / denom)


def soft_spl(
    *,
    progress: float,
    shortest_path_m: float,
    agent_path_m: float,
) -> float:
    """Habitat soft-SPL: progress in [0, 1] replaces hard success."""
    p = min(1.0, max(0.0, float(progress)))
    return success_weighted_path_length(
        success=True,
        shortest_path_m=shortest_path_m,
        agent_path_m=agent_path_m,
    ) * p


def barn_score(
    *,
    success: bool,
    actual_time_s: float,
    optimal_time_s: float,
    clip_low_factor: float = 2.0,
    clip_high_factor: float = 8.0,
) -> float:
    """BARN Challenge traversal score for one environment/trial.

    s = 1_success * OT / clip(AT, low*OT, high*OT)
    """
    if not success:
        return 0.0
    ot = max(float(optimal_time_s), 1e-9)
    at = max(float(actual_time_s), 0.0)
    low = clip_low_factor * ot
    high = clip_high_factor * ot
    clipped = min(max(at, low), high)
    return float(ot / clipped)


def optimal_time_s(path_length_m: float, max_speed_mps: float) -> float:
    speed = max(float(max_speed_mps), 1e-9)
    return float(max(path_length_m, 0.0) / speed)


def personal_space_compliance(
    distances_m: Iterable[float | None],
    *,
    threshold_m: float = 1.0,
) -> float:
    """Fraction of timesteps with min human distance >= threshold (or no human)."""
    values = list(distances_m)
    if not values:
        return 1.0
    ok = 0
    for dist in values:
        if dist is None or dist >= threshold_m:
            ok += 1
    return float(ok / len(values))


def coverage_ratio(visited_cells: int, free_cells: int) -> float:
    if free_cells <= 0:
        return 0.0
    return float(min(1.0, max(0.0, visited_cells / free_cells)))


def exploration_efficiency(*, coverage: float, path_m: float) -> float:
    """Coverage per meter traveled (higher is better; 0 if no motion)."""
    if path_m <= 1e-9:
        return 0.0
    return float(max(0.0, coverage) / path_m)


@dataclass(frozen=True)
class EpisodeMetrics:
    success: bool
    spl: float
    soft_spl: float
    distance_to_goal_m: float
    agent_path_m: float
    shortest_path_m: float
    collision_count: int
    traversal_time_s: float
    barn_score: float
    psc: float
    human_collision: bool
    coverage: float
    exploration_efficiency: float

    def to_dict(self) -> dict[str, float | bool | int]:
        return {
            "success": self.success,
            "spl": self.spl,
            "soft_spl": self.soft_spl,
            "distance_to_goal_m": self.distance_to_goal_m,
            "agent_path_m": self.agent_path_m,
            "shortest_path_m": self.shortest_path_m,
            "collision_count": self.collision_count,
            "traversal_time_s": self.traversal_time_s,
            "barn_score": self.barn_score,
            "psc": self.psc,
            "human_collision": self.human_collision,
            "coverage": self.coverage,
            "exploration_efficiency": self.exploration_efficiency,
        }


def aggregate(episodes: Sequence[EpisodeMetrics]) -> dict[str, float]:
    n = len(episodes)
    if n == 0:
        return {
            "episodes": 0.0,
            "success_rate": 0.0,
            "spl": 0.0,
            "soft_spl": 0.0,
            "barn_score": 0.0,
            "collision_rate": 0.0,
            "human_collision_rate": 0.0,
            "psc": 0.0,
            "mean_distance_to_goal_m": 0.0,
            "mean_coverage": 0.0,
        }
    return {
        "episodes": float(n),
        "success_rate": sum(1.0 for e in episodes if e.success) / n,
        "spl": sum(e.spl for e in episodes) / n,
        "soft_spl": sum(e.soft_spl for e in episodes) / n,
        "barn_score": sum(e.barn_score for e in episodes) / n,
        "collision_rate": sum(1.0 for e in episodes if e.collision_count > 0) / n,
        "human_collision_rate": sum(1.0 for e in episodes if e.human_collision) / n,
        "psc": sum(e.psc for e in episodes) / n,
        "mean_distance_to_goal_m": sum(e.distance_to_goal_m for e in episodes) / n,
        "mean_coverage": sum(e.coverage for e in episodes) / n,
    }
