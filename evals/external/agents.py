"""Simple offline agents for external-eval smoke scoring.

These are *not* Parcel's production navigator. They exist so the metric and
episode machinery can run without MuJoCo, Habitat, Gazebo, or checkpoints.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .episodes import DiscObstacle, Episode


@dataclass
class AgentState:
    x: float
    y: float
    heading_rad: float


@dataclass(frozen=True)
class VelocityCommand:
    vx: float
    vy: float
    vyaw: float


class OfflineAgent:
    """Baseline policy interface."""

    def reset(self, episode: Episode) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def act(self, state: AgentState, episode: Episode) -> VelocityCommand:
        raise NotImplementedError


class GoalSeekingAgent(OfflineAgent):
    """Rotate-then-translate toward goal / nearest object; stop near success radius.

    Mimics Parcel's forward-preferred stub navigator at a very coarse level.
    """

    def __init__(self, *, align_gain: float = 2.0, speed: float = 0.45) -> None:
        self.align_gain = align_gain
        self.speed = speed
        self._episode: Episode | None = None

    def reset(self, episode: Episode) -> None:
        self._episode = episode

    def act(self, state: AgentState, episode: Episode) -> VelocityCommand:
        target = self._target(episode, state)
        if target is None:
            # Exploration: slow spiral / wander.
            return VelocityCommand(vx=0.35, vy=0.0, vyaw=0.35)

        dx = target[0] - state.x
        dy = target[1] - state.y
        dist = math.hypot(dx, dy)
        if dist <= episode.success_radius_m:
            return VelocityCommand(0.0, 0.0, 0.0)

        desired = math.atan2(dy, dx)
        err = _wrap(desired - state.heading_rad)
        if abs(err) > math.radians(25):
            return VelocityCommand(0.0, 0.0, max(-1.0, min(1.0, self.align_gain * err)))

        # Simple reactive sidestep if a disc is dead ahead.
        if _blocked_ahead(state, episode, look_ahead_m=0.9):
            return VelocityCommand(vx=0.12, vy=0.0, vyaw=0.8 if err >= 0 else -0.8)

        taper = max(0.15, min(1.0, dist / 2.0)) * max(0.0, math.cos(err)) ** 2
        return VelocityCommand(vx=self.speed * taper, vy=0.0, vyaw=1.2 * err)

    def _target(self, episode: Episode, state: AgentState) -> tuple[float, float] | None:
        if episode.task == "objectnav" and episode.target_category:
            inst = [
                o for o in episode.objects if o.category == episode.target_category
            ]
            if not inst:
                return episode.goal_xy
            best = min(inst, key=lambda o: math.hypot(o.x - state.x, o.y - state.y))
            return (best.x, best.y)
        return episode.goal_xy


def _wrap(angle: float) -> float:
    while angle > math.pi:
        angle -= 2.0 * math.pi
    while angle < -math.pi:
        angle += 2.0 * math.pi
    return angle


def _blocked_ahead(state: AgentState, episode: Episode, *, look_ahead_m: float) -> bool:
    px = state.x + look_ahead_m * math.cos(state.heading_rad)
    py = state.y + look_ahead_m * math.sin(state.heading_rad)
    discs: list[DiscObstacle] = list(episode.obstacles) + list(episode.humans)
    for disc in discs:
        if math.hypot(disc.x - px, disc.y - py) <= disc.radius + episode.agent_radius_m:
            return True
    return False
