"""ProposerBus + GoalArbiter (pure seam for hot-swappable SE2 goals)."""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SE2Goal:
    source: str
    pose: tuple[float, float, float] | None  # x, y, yaw_rad
    waypoints: tuple[tuple[float, float], ...] = ()
    frame: str = "map"
    confidence: float = 1.0
    ttl_s: float = 2.0
    plan_step_id: str = ""
    issued_s: float = 0.0
    priority: int = 0

    def __post_init__(self) -> None:
        if not self.source:
            raise ValueError("SE2Goal.source must be non-empty")
        if self.pose is None and not self.waypoints:
            raise ValueError("SE2Goal requires pose or waypoints")
        if self.pose is not None and not all(math.isfinite(v) for v in self.pose):
            raise ValueError("pose must be finite")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be in [0, 1]")
        if not math.isfinite(self.ttl_s) or self.ttl_s <= 0.0:
            raise ValueError("ttl_s must be finite and positive")

    def expired(self, now_s: float) -> bool:
        return float(now_s) - float(self.issued_s) > self.ttl_s

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "pose": list(self.pose) if self.pose is not None else None,
            "waypoints": [list(p) for p in self.waypoints],
            "frame": self.frame,
            "confidence": self.confidence,
            "ttl_s": self.ttl_s,
            "plan_step_id": self.plan_step_id,
            "issued_s": self.issued_s,
            "priority": self.priority,
        }


@dataclass
class ProposerBus:
    """Register async proposers; each emit is timestamped onto the bus."""

    _proposers: dict[str, Callable[..., SE2Goal | None]] = field(default_factory=dict)
    _latest: dict[str, SE2Goal] = field(default_factory=dict)

    def register(self, source: str, proposer: Callable[..., SE2Goal | None]) -> None:
        if not source:
            raise ValueError("source must be non-empty")
        self._proposers[source] = proposer

    def publish(self, goal: SE2Goal) -> None:
        self._latest[goal.source] = goal

    def poll(self, *, now_s: float, context: Mapping[str, Any] | None = None) -> tuple[SE2Goal, ...]:
        ctx = dict(context or {})
        for source, proposer in self._proposers.items():
            try:
                goal = proposer(now_s=now_s, **ctx)
            except TypeError:
                goal = proposer()
            if goal is None:
                continue
            if goal.source != source:
                goal = SE2Goal(
                    source=source,
                    pose=goal.pose,
                    waypoints=goal.waypoints,
                    frame=goal.frame,
                    confidence=goal.confidence,
                    ttl_s=goal.ttl_s,
                    plan_step_id=goal.plan_step_id,
                    issued_s=now_s,
                    priority=goal.priority,
                )
            elif goal.issued_s == 0.0:
                goal = SE2Goal(
                    source=goal.source,
                    pose=goal.pose,
                    waypoints=goal.waypoints,
                    frame=goal.frame,
                    confidence=goal.confidence,
                    ttl_s=goal.ttl_s,
                    plan_step_id=goal.plan_step_id,
                    issued_s=now_s,
                    priority=goal.priority,
                )
            self._latest[source] = goal
        return tuple(self._latest.values())

    def snapshot(self) -> dict[str, Any]:
        return {
            "sources": sorted(self._proposers),
            "latest": {key: goal.as_dict() for key, goal in sorted(self._latest.items())},
        }


class GoalArbiter:
    """Resolve competing SE2 goals by plan-step ownership, priority, freshness.

    TTL-expired or lethal-cost goals are vetoed (AsyncShield staleness lesson).
    grid_v1 A* remains the sole consumer of the winner.
    """

    def __init__(
        self,
        *,
        lethal_cost: Callable[[float, float], bool] | None = None,
    ) -> None:
        self._lethal = lethal_cost or (lambda _x, _y: False)
        self._active_plan_step: str | None = None

    def set_plan_step(self, plan_step_id: str | None) -> None:
        self._active_plan_step = plan_step_id

    def resolve(
        self,
        goals: Sequence[SE2Goal],
        *,
        now_s: float,
    ) -> SE2Goal | None:
        viable: list[SE2Goal] = []
        for goal in goals:
            if goal.expired(now_s):
                continue
            pose = goal.pose
            if pose is not None and self._lethal(pose[0], pose[1]):
                continue
            if goal.waypoints and all(self._lethal(x, y) for x, y in goal.waypoints):
                continue
            viable.append(goal)
        if not viable:
            return None
        if self._active_plan_step:
            owned = [g for g in viable if g.plan_step_id == self._active_plan_step]
            if owned:
                viable = owned
        viable.sort(
            key=lambda g: (
                -int(g.priority),
                -float(g.confidence),
                -float(g.issued_s),
                g.source,
            )
        )
        return viable[0]
