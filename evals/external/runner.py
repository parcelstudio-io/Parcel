"""Offline kinematic episode runner for external benchmark proxies."""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .agents import AgentState, GoalSeekingAgent, OfflineAgent, VelocityCommand
from .compatibility import COMPATIBILITY, compatibility_table
from .episodes import DiscObstacle, Episode, build_suite
from .metrics import (
    EpisodeMetrics,
    aggregate,
    barn_score,
    coverage_ratio,
    euclidean,
    exploration_efficiency,
    optimal_time_s,
    path_length,
    personal_space_compliance,
    soft_spl,
    success_weighted_path_length,
)

DEFAULT_RESULTS_DIR = Path(__file__).resolve().parent / "results"


def _min_clearance(
    x: float,
    y: float,
    radius: float,
    discs: list[DiscObstacle],
) -> float | None:
    if not discs:
        return None
    return min(math.hypot(d.x - x, d.y - y) - d.radius - radius for d in discs)


def _integrate(state: AgentState, cmd: VelocityCommand, dt: float) -> AgentState:
    # Body-frame vx/vy with heading; vyaw integrates heading.
    heading = state.heading_rad + cmd.vyaw * dt
    c = math.cos(state.heading_rad)
    s = math.sin(state.heading_rad)
    dx = (cmd.vx * c - cmd.vy * s) * dt
    dy = (cmd.vx * s + cmd.vy * c) * dt
    return AgentState(x=state.x + dx, y=state.y + dy, heading_rad=heading)


def _oracle_visible(episode: Episode, state: AgentState) -> bool:
    """Habitat ObjectNav proxy: can an oracle see a target without translating?"""
    if episode.task != "objectnav" or not episode.target_category:
        return True
    for obj in episode.objects:
        if obj.category != episode.target_category:
            continue
        if euclidean((state.x, state.y), (obj.x, obj.y)) <= episode.success_radius_m + obj.radius:
            return True
    return False


def run_episode(episode: Episode, agent: OfflineAgent) -> tuple[EpisodeMetrics, dict[str, Any]]:
    agent.reset(episode)
    state = AgentState(
        x=episode.start_xy[0],
        y=episode.start_xy[1],
        heading_rad=episode.start_heading_rad,
    )
    path: list[tuple[float, float]] = [(state.x, state.y)]
    human_distances: list[float | None] = []
    collision_count = 0
    human_hit = False
    visited: set[tuple[int, int]] = set()

    def cell(x: float, y: float) -> tuple[int, int]:
        return (math.floor(x / episode.cell_m), math.floor(y / episode.cell_m))

    half = episode.grid_size_m / 2.0
    free_cells = 0
    if episode.task == "exploration":
        n = math.ceil(episode.grid_size_m / episode.cell_m)
        for ix in range(-n, n + 1):
            for iy in range(-n, n + 1):
                cx = (ix + 0.5) * episode.cell_m
                cy = (iy + 0.5) * episode.cell_m
                if abs(cx) > half or abs(cy) > half:
                    continue
                clearance = _min_clearance(cx, cy, 0.0, list(episode.obstacles))
                if clearance is None or clearance > episode.agent_radius_m:
                    free_cells += 1

    stopped = False
    for _ in range(episode.max_steps):
        cmd = agent.act(state, episode)
        if abs(cmd.vx) < 1e-6 and abs(cmd.vy) < 1e-6 and abs(cmd.vyaw) < 1e-6:
            stopped = True
            break
        # Clip to episode max speed.
        speed = math.hypot(cmd.vx, cmd.vy)
        if speed > episode.max_speed_mps:
            scale = episode.max_speed_mps / speed
            cmd = VelocityCommand(cmd.vx * scale, cmd.vy * scale, cmd.vyaw)
        state = _integrate(state, cmd, episode.dt_s)
        path.append((state.x, state.y))
        visited.add(cell(state.x, state.y))

        static = _min_clearance(state.x, state.y, episode.agent_radius_m, list(episode.obstacles))
        human = _min_clearance(state.x, state.y, episode.agent_radius_m, list(episode.humans))
        if episode.humans:
            human_distances.append(
                min(math.hypot(h.x - state.x, h.y - state.y) for h in episode.humans)
            )
        else:
            human_distances.append(None)

        if static is not None and static <= 0.0:
            collision_count += 1
        if human is not None and human <= 0.0:
            collision_count += 1
            human_hit = True

        if (
            episode.goal_xy is not None
            and euclidean((state.x, state.y), episode.goal_xy) <= episode.success_radius_m
        ):
            # Auto-stop when inside radius (Habitat requires explicit STOP; we model it).
            stopped = True
            break

    agent_path = path_length(path)
    traversal_time = max(0, len(path) - 1) * episode.dt_s
    shortest = episode.shortest_path_m

    if episode.task == "exploration":
        cov = coverage_ratio(len(visited), max(free_cells, 1))
        success = cov >= 0.25  # modest offline threshold, not an official 3WE cutoff
        dist_goal = 0.0
        progress = cov
    elif episode.task == "objectnav":
        dist_goal = (
            0.0
            if episode.goal_xy is None
            else euclidean((state.x, state.y), episode.goal_xy)
        )
        # Distance to nearest target instance.
        targets = [o for o in episode.objects if o.category == episode.target_category]
        if targets:
            dist_goal = min(euclidean((state.x, state.y), (o.x, o.y)) for o in targets)
        success = (
            stopped
            and dist_goal <= episode.success_radius_m
            and _oracle_visible(episode, state)
            and collision_count == 0
        )
        progress = 0.0 if shortest <= 1e-9 else max(0.0, min(1.0, 1.0 - dist_goal / shortest))
        cov = 0.0
    else:
        dist_goal = (
            float("inf")
            if episode.goal_xy is None
            else euclidean((state.x, state.y), episode.goal_xy)
        )
        success = (
            stopped
            and dist_goal <= episode.success_radius_m
            and collision_count == 0
        )
        progress = (
            0.0
            if not math.isfinite(dist_goal) or shortest <= 1e-9
            else max(0.0, min(1.0, 1.0 - dist_goal / shortest))
        )
        cov = 0.0

    # BARN-style success already requires zero collisions (encoded above).
    ot = optimal_time_s(shortest, episode.max_speed_mps)
    metrics = EpisodeMetrics(
        success=bool(success),
        spl=success_weighted_path_length(
            success=bool(success),
            shortest_path_m=shortest,
            agent_path_m=agent_path,
        ),
        soft_spl=soft_spl(
            progress=progress,
            shortest_path_m=shortest,
            agent_path_m=agent_path,
        ),
        distance_to_goal_m=float(dist_goal if math.isfinite(dist_goal) else 0.0),
        agent_path_m=agent_path,
        shortest_path_m=shortest,
        collision_count=collision_count,
        traversal_time_s=traversal_time,
        barn_score=barn_score(
            success=bool(success),
            actual_time_s=traversal_time,
            optimal_time_s=ot,
        ),
        psc=personal_space_compliance(
            human_distances,
            threshold_m=float(episode.metadata.get("psc_threshold_m", 1.0)),
        ),
        human_collision=human_hit,
        coverage=cov,
        exploration_efficiency=exploration_efficiency(coverage=cov, path_m=agent_path),
    )
    detail = {
        "episode_id": episode.episode_id,
        "task": episode.task,
        "benchmark_id": episode.benchmark_id,
        "stopped": stopped,
        "final_xy": [state.x, state.y],
        "metrics": metrics.to_dict(),
        "metadata": episode.metadata,
    }
    return metrics, detail


def run_suite(
    *,
    tasks: list[str] | None = None,
    episodes_per_task: int = 20,
    seed: int = 7,
    agent: OfflineAgent | None = None,
) -> dict[str, Any]:
    episodes = build_suite(tasks, episodes_per_task=episodes_per_task, seed=seed)
    policy = agent or GoalSeekingAgent()
    details: list[dict[str, Any]] = []
    metrics_list: list[EpisodeMetrics] = []
    by_task: dict[str, list[EpisodeMetrics]] = {}

    for episode in episodes:
        m, detail = run_episode(episode, policy)
        metrics_list.append(m)
        details.append(detail)
        by_task.setdefault(episode.task, []).append(m)

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "seed": seed,
        "episodes_per_task": episodes_per_task,
        "agent": type(policy).__name__,
        "compatibility": compatibility_table(),
        "aggregate": aggregate(metrics_list),
        "by_task": {name: aggregate(items) for name, items in by_task.items()},
        "episodes": details,
        "notes": [
            "Offline synthetic proxies only — not official Habitat/BARN/3WE leaderboard numbers.",
            "Euclidean shortest paths are lower bounds (no occupancy planner).",
            "GoalSeekingAgent is a coarse rotate-then-go baseline, not StubNavigator.",
        ],
        "benchmark_count": len(COMPATIBILITY),
    }
    return report


def write_report(report: dict[str, Any], path: Path | None = None) -> Path:
    out_dir = DEFAULT_RESULTS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    target = path or (out_dir / "latest_report.json")
    target.write_text(json.dumps(report, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    return target
