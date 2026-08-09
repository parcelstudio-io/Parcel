"""Route-memory SE2Goal proposer for GoalArbiter (gated; no cmd_vel).

Promotion rule: learned / taught proposers remain behind ``gate_enabled``.
grid_v1 A* remains the sole motion consumer of the winner.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from parcel_robot.instructnav.arbiter import SE2Goal
from parcel_robot.route_memory.memory import PROPOSER_SOURCE, RoutePath

DOES_NOT_PROVE = (
    (
        "RouteMemoryProposer emits TTL'd SE2Goal waypoints from taught sim "
        "paths; it does not author velocity, bypass GoalArbiter/collision "
        "gates, or prove field teach-and-repeat success (HR-12)."
    ),
)


def _nearest_index(path: RoutePath, robot_x: float, robot_y: float) -> int:
    best_i = 0
    best_d = float("inf")
    for i, kf in enumerate(path.keyframes):
        d = math.hypot(kf.x - robot_x, kf.y - robot_y)
        if d < best_d:
            best_d = d
            best_i = i
    return best_i


@dataclass(frozen=True, slots=True)
class RouteMemoryProposer:
    """Replay a taught ``RoutePath`` as SE2Goal proposals.

    When ``gate_enabled`` is False (default), ``propose`` always returns None —
    learned proposers stay behind the promotion gate.
    """

    path: RoutePath
    gate_enabled: bool = False
    priority: int = 3
    ttl_s: float = 2.0
    confidence: float = 0.8
    plan_step_id: str = ""
    lookahead_keyframes: int = 3
    arrive_tol_m: float = 0.35
    source: str = PROPOSER_SOURCE

    def __post_init__(self) -> None:
        if not isinstance(self.path, RoutePath):
            raise TypeError("path must be RoutePath")
        if not isinstance(self.gate_enabled, bool):
            raise TypeError("gate_enabled must be a boolean")
        if isinstance(self.priority, bool) or not isinstance(self.priority, int):
            raise TypeError("priority must be an integer")
        if not math.isfinite(self.ttl_s) or self.ttl_s <= 0.0:
            raise ValueError("ttl_s must be finite and positive")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be in [0, 1]")
        if (
            isinstance(self.lookahead_keyframes, bool)
            or not isinstance(self.lookahead_keyframes, int)
            or self.lookahead_keyframes < 1
        ):
            raise ValueError("lookahead_keyframes must be an int ≥ 1")
        if not math.isfinite(self.arrive_tol_m) or self.arrive_tol_m <= 0.0:
            raise ValueError("arrive_tol_m must be finite and positive")
        if not isinstance(self.source, str) or not self.source.strip():
            raise ValueError("source must be non-empty")

    def propose(
        self,
        *,
        now_s: float,
        robot_x: float,
        robot_y: float,
        robot_yaw: float = 0.0,
        **_ctx: Any,
    ) -> SE2Goal | None:
        """Return the next SE2Goal along the taught path, or None if gated/done."""

        if not self.gate_enabled:
            return None
        for name, value in (
            ("now_s", now_s),
            ("robot_x", robot_x),
            ("robot_y", robot_y),
            ("robot_yaw", robot_yaw),
        ):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"{name} must be numeric")
            if not math.isfinite(float(value)):
                raise ValueError(f"{name} must be finite")

        idx = _nearest_index(self.path, float(robot_x), float(robot_y))
        # Advance past the nearest keyframe once we are inside arrive_tol.
        nearest = self.path.keyframes[idx]
        if math.hypot(nearest.x - robot_x, nearest.y - robot_y) <= self.arrive_tol_m:
            idx = min(idx + 1, len(self.path.keyframes) - 1)

        target_idx = min(idx + self.lookahead_keyframes - 1, len(self.path.keyframes) - 1)
        # If we are already at the terminal keyframe within tolerance, done.
        terminal = self.path.keyframes[-1]
        if idx >= len(self.path.keyframes) - 1 and math.hypot(
            terminal.x - robot_x, terminal.y - robot_y
        ) <= self.arrive_tol_m:
            return None

        slice_kfs = self.path.keyframes[idx : target_idx + 1]
        if not slice_kfs:
            return None
        waypoints = tuple((kf.x, kf.y) for kf in slice_kfs)
        tip = slice_kfs[-1]
        if len(slice_kfs) >= 2:
            prev = slice_kfs[-2]
            yaw = math.atan2(tip.y - prev.y, tip.x - prev.x)
        else:
            yaw = tip.yaw_rad
        return SE2Goal(
            source=self.source,
            pose=(tip.x, tip.y, yaw),
            waypoints=waypoints if len(waypoints) > 1 else (),
            frame=self.path.frame,
            confidence=self.confidence,
            ttl_s=self.ttl_s,
            plan_step_id=self.plan_step_id,
            issued_s=float(now_s),
            priority=self.priority,
        )

    def as_bus_proposer(self):
        """Adapter matching ProposerBus ``proposer(now_s=..., **ctx)`` shape."""

        def _propose(*, now_s: float, robot_x: float = 0.0, robot_y: float = 0.0, **ctx):
            robot_yaw = float(ctx.get("robot_yaw", 0.0))
            return self.propose(
                now_s=now_s,
                robot_x=robot_x,
                robot_y=robot_y,
                robot_yaw=robot_yaw,
            )

        return _propose

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "path_id": self.path.path_id,
            "gate_enabled": self.gate_enabled,
            "priority": self.priority,
            "ttl_s": self.ttl_s,
            "confidence": self.confidence,
            "plan_step_id": self.plan_step_id,
            "lookahead_keyframes": self.lookahead_keyframes,
            "arrive_tol_m": self.arrive_tol_m,
            "does_not_prove": list(DOES_NOT_PROVE),
        }


def goal_from_path_snapshot(
    path: RoutePath,
    *,
    now_s: float,
    gate_enabled: bool = False,
    priority: int = 3,
    ttl_s: float = 2.0,
    confidence: float = 0.8,
    plan_step_id: str = "",
) -> SE2Goal | None:
    """Emit a full-path SE2Goal snapshot (still gated; GoalArbiter-compatible)."""

    if not gate_enabled:
        return None
    if not isinstance(path, RoutePath):
        raise TypeError("path must be RoutePath")
    waypoints = path.waypoints_xy()
    pose = path.terminal_pose()
    return SE2Goal(
        source=PROPOSER_SOURCE,
        pose=pose,
        waypoints=waypoints if len(waypoints) > 1 else (),
        frame=path.frame,
        confidence=confidence,
        ttl_s=ttl_s,
        plan_step_id=plan_step_id,
        issued_s=float(now_s),
        priority=priority,
    )


def propose_with_context(
    proposer: RouteMemoryProposer,
    *,
    now_s: float,
    context: Mapping[str, Any] | None = None,
) -> SE2Goal | None:
    ctx = dict(context or {})
    return proposer.propose(
        now_s=now_s,
        robot_x=float(ctx.get("robot_x", 0.0)),
        robot_y=float(ctx.get("robot_y", 0.0)),
        robot_yaw=float(ctx.get("robot_yaw", 0.0)),
    )
