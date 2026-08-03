"""Synthetic offline episodes that mirror external benchmark task shapes."""

from __future__ import annotations

import math
import random
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

TaskName = Literal[
    "pointnav",
    "objectnav",
    "barn_clutter",
    "socialnav",
    "exploration",
]


@dataclass(frozen=True)
class DiscObstacle:
    x: float
    y: float
    radius: float
    kind: str = "static"  # static | human


@dataclass(frozen=True)
class LabeledObject:
    category: str
    x: float
    y: float
    radius: float = 0.35


@dataclass
class Episode:
    """One offline evaluation episode.

    Coordinates are in a flat 2D metric frame. The agent is a disc of
    ``agent_radius_m`` commanded with body-frame velocities.
    """

    episode_id: str
    task: TaskName
    benchmark_id: str
    seed: int
    start_xy: tuple[float, float]
    start_heading_rad: float
    goal_xy: tuple[float, float] | None
    success_radius_m: float
    max_steps: int
    dt_s: float
    agent_radius_m: float
    max_speed_mps: float
    obstacles: tuple[DiscObstacle, ...] = ()
    humans: tuple[DiscObstacle, ...] = ()
    objects: tuple[LabeledObject, ...] = ()
    target_category: str | None = None
    grid_size_m: float = 12.0
    cell_m: float = 0.5
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def shortest_path_m(self) -> float:
        """Euclidean lower bound (no map planner required for offline smoke)."""
        if self.goal_xy is None:
            # Exploration has no single goal; use a nominal scale.
            return float(self.grid_size_m)
        return float(
            math.hypot(
                self.goal_xy[0] - self.start_xy[0],
                self.goal_xy[1] - self.start_xy[1],
            )
        )


def _rng(seed: int) -> random.Random:
    return random.Random(seed)


def make_pointnav_episode(index: int, *, seed: int = 0, habitat_radius: bool = False) -> Episode:
    rng = _rng(seed + 17 * index)
    start = (0.0, 0.0)
    # Relative goal like Habitat PointNav ("5m north, 3m west"), expressed as XY.
    goal = (rng.uniform(-5.0, 5.0), rng.uniform(2.0, 8.0))
    radius = 0.36 if habitat_radius else 0.80
    return Episode(
        episode_id=f"pointnav-{index:04d}",
        task="pointnav",
        benchmark_id="habitat2020_pointnav",
        seed=seed + index,
        start_xy=start,
        start_heading_rad=rng.uniform(-math.pi, math.pi),
        goal_xy=goal,
        success_radius_m=radius,
        max_steps=400,
        dt_s=0.1,
        agent_radius_m=0.30,
        max_speed_mps=0.6,
        metadata={"habitat_success_radius_m": 0.36, "parcel_default_radius_m": 0.80},
    )


def make_objectnav_episode(index: int, *, seed: int = 0) -> Episode:
    rng = _rng(seed + 31 * index)
    categories = ("chair", "table", "plant", "bench")
    target = categories[index % len(categories)]
    objects: list[LabeledObject] = []
    for cat in categories:
        objects.append(
            LabeledObject(
                category=cat,
                x=rng.uniform(-4.0, 4.0),
                y=rng.uniform(1.5, 9.0),
                radius=0.35,
            )
        )
    # Guarantee at least one target instance.
    if not any(o.category == target for o in objects):
        objects[0] = LabeledObject(category=target, x=2.0, y=4.0)
    instances = [o for o in objects if o.category == target]
    closest = min(instances, key=lambda o: math.hypot(o.x, o.y))
    return Episode(
        episode_id=f"objectnav-{index:04d}",
        task="objectnav",
        benchmark_id="habitat2020_objectnav",
        seed=seed + index,
        start_xy=(0.0, 0.0),
        start_heading_rad=0.0,
        goal_xy=(closest.x, closest.y),
        success_radius_m=1.0,
        max_steps=500,
        dt_s=0.1,
        agent_radius_m=0.30,
        max_speed_mps=0.6,
        objects=tuple(objects),
        target_category=target,
        metadata={"oracle_visibility": True},
    )


def make_barn_episode(index: int, *, seed: int = 0) -> Episode:
    """Narrow corridor with cylinder clutter (BARN-inspired, not official worlds)."""
    rng = _rng(seed + 53 * index)
    width = rng.uniform(1.6, 2.4)
    length = rng.uniform(8.0, 14.0)
    obstacles: list[DiscObstacle] = []
    # Corridor walls approximated as dense discs along edges.
    y = 0.5
    while y < length:
        obstacles.append(DiscObstacle(x=-width / 2, y=y, radius=0.25))
        obstacles.append(DiscObstacle(x=width / 2, y=y, radius=0.25))
        y += 0.55
    # Interior clutter.
    for _ in range(rng.randint(4, 10)):
        obstacles.append(
            DiscObstacle(
                x=rng.uniform(-width / 2 + 0.45, width / 2 - 0.45),
                y=rng.uniform(1.5, length - 1.5),
                radius=rng.uniform(0.15, 0.28),
            )
        )
    return Episode(
        episode_id=f"barn-{index:04d}",
        task="barn_clutter",
        benchmark_id="barn",
        seed=seed + index,
        start_xy=(0.0, 0.0),
        start_heading_rad=math.pi / 2,
        goal_xy=(0.0, length),
        success_radius_m=0.6,
        max_steps=600,
        dt_s=0.1,
        agent_radius_m=0.30,
        max_speed_mps=0.6,
        obstacles=tuple(obstacles),
        metadata={
            "corridor_width_m": width,
            "corridor_length_m": length,
            "note": "Synthetic BARN-like clutter; not an official BARN world id",
        },
    )


def make_socialnav_episode(index: int, *, seed: int = 0) -> Episode:
    rng = _rng(seed + 71 * index)
    goal = (rng.uniform(-1.0, 1.0), rng.uniform(6.0, 10.0))
    humans: list[DiscObstacle] = []
    for i in range(rng.randint(2, 5)):
        humans.append(
            DiscObstacle(
                x=rng.uniform(-3.0, 3.0),
                y=rng.uniform(2.0, 8.0),
                radius=0.30,
                kind="human",
            )
        )
    return Episode(
        episode_id=f"socialnav-{index:04d}",
        task="socialnav",
        benchmark_id="social_hm3d",
        seed=seed + index,
        start_xy=(0.0, 0.0),
        start_heading_rad=math.pi / 2,
        goal_xy=goal,
        success_radius_m=0.8,
        max_steps=500,
        dt_s=0.1,
        agent_radius_m=0.30,
        max_speed_mps=0.6,
        humans=tuple(humans),
        metadata={"psc_threshold_m": 1.0},
    )


def make_exploration_episode(index: int, *, seed: int = 0) -> Episode:
    rng = _rng(seed + 97 * index)
    obstacles = tuple(
        DiscObstacle(
            x=rng.uniform(-4.0, 4.0),
            y=rng.uniform(-4.0, 4.0),
            radius=rng.uniform(0.3, 0.7),
        )
        for _ in range(8)
    )
    return Episode(
        episode_id=f"exploration-{index:04d}",
        task="exploration",
        benchmark_id="threewe",
        seed=seed + index,
        start_xy=(0.0, 0.0),
        start_heading_rad=rng.uniform(-math.pi, math.pi),
        goal_xy=None,
        success_radius_m=0.0,
        max_steps=300,
        dt_s=0.1,
        agent_radius_m=0.30,
        max_speed_mps=0.6,
        obstacles=obstacles,
        grid_size_m=10.0,
        cell_m=0.5,
        metadata={"time_budget_s": 30.0},
    )


SUITE_BUILDERS = {
    "pointnav": make_pointnav_episode,
    "objectnav": make_objectnav_episode,
    "barn_clutter": make_barn_episode,
    "socialnav": make_socialnav_episode,
    "exploration": make_exploration_episode,
}


def build_suite(
    tasks: Sequence[str] | None = None,
    *,
    episodes_per_task: int = 20,
    seed: int = 7,
) -> list[Episode]:
    selected = tuple(tasks) if tasks else tuple(SUITE_BUILDERS.keys())
    out: list[Episode] = []
    for task in selected:
        if task not in SUITE_BUILDERS:
            raise KeyError(f"unknown task: {task}")
        builder = SUITE_BUILDERS[task]
        for i in range(episodes_per_task):
            out.append(builder(i, seed=seed))
    return out
