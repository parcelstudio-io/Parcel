"""Route-memory SE2Goal proposer for GoalArbiter (gated; no cmd_vel).

Promotion rule: learned / taught proposers remain behind ``gate_enabled``.
grid_v1 A* remains the sole motion consumer of the winner.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from parcel_robot.instructnav.arbiter import SE2Goal
from parcel_robot.route_memory.memory import PROPOSER_SOURCE, RouteKeyframe, RoutePath
from parcel_robot.route_memory.place_graph import (
    DEFAULT_ATTACH_RADIUS_M,
    DEFAULT_KEYFRAME_SPACING_M,
)

DOES_NOT_PROVE = (
    (
        "RouteMemoryProposer emits TTL'd SE2Goal waypoints from taught sim "
        "paths; it does not author velocity, bypass GoalArbiter/collision "
        "gates, or prove field teach-and-repeat success (HR-12)."
    ),
    (
        "waypoint_goal_from_chain converts a RECORDED place-graph chain into "
        "one interim SE2Goal proposal. It is not a plan: the grid_v1 planner "
        "and the reactive gate remain the sole motion authority over the leg "
        "to that waypoint, and the mission goal / K0 arrival predicate are "
        "never replaced by it (card RM-2)."
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


# ---------------------------------------------------------------------------
# RM-2 (card ``scrum/20260811/task_2/SLAM_M_PLAN.md``): place-graph chain ->
# ONE interim SE2Goal, stamped with the pipeline's active (task_id,
# plan_revision).
#
# RM-1 froze the query side and put the SE2Goal conversion HERE by name:
# "``SE2Goal`` conversion is not in this module -- it stays in ``proposer.py``,
# RM-2's" (RM1_STATUS.md §1).  Everything below is additive; nothing above it
# changed shape.
# ---------------------------------------------------------------------------

#: Bus/arbiter source name for a place-graph waypoint proposal.  Distinct from
#: :data:`PROPOSER_SOURCE` (the taught-``RoutePath`` replay) so arbitration logs
#: and telemetry can tell a remembered-route waypoint from a taught-route one.
PLACE_ROUTE_SOURCE = "route_memory_place"

#: "The robot is AT this keyframe."  Derived, not chosen: RM-1 admits keyframes
#: at least ``DEFAULT_KEYFRAME_SPACING_M`` (0.50 m) apart, so a robot inside half
#: a spacing of a keyframe is strictly closer to it than to either neighbour --
#: that is what being at that place means, and it is the largest radius for
#: which the claim is unambiguous.  It coincides exactly with
#: ``GridPlannerConfig.goal_tolerance_m`` (0.25 m), which is the same statement
#: made from the planner's side; RM-1's spacing derivation is precisely
#: ``2 * goal_tolerance_m``.
DEFAULT_WAYPOINT_REACHED_M = DEFAULT_KEYFRAME_SPACING_M / 2.0  # 0.25 m


def chain_length_m(chain: Sequence[RouteKeyframe]) -> float:
    """Polyline length of a keyframe chain in metres (0.0 for < 2 keyframes)."""

    total = 0.0
    for previous, current in itertools.pairwise(chain):
        total += math.hypot(current.x - previous.x, current.y - previous.y)
    return total


def _attach_index(chain: Sequence[RouteKeyframe], robot_xy: tuple[float, float]) -> int:
    best_i = 0
    best_d = float("inf")
    for i, kf in enumerate(chain):
        d = math.hypot(kf.x - robot_xy[0], kf.y - robot_xy[1])
        if d < best_d:
            best_d = d
            best_i = i
    return best_i


def next_waypoint_keyframe(
    chain: Sequence[RouteKeyframe],
    robot_xy: Sequence[float],
    *,
    reached_m: float = DEFAULT_WAYPOINT_REACHED_M,
    reach_radius_m: float = DEFAULT_ATTACH_RADIUS_M,
) -> tuple[int, int] | None:
    """``(start, target)`` indices into ``chain``, or ``None`` when it is spent.

    ``start`` is the first keyframe ahead of the robot; ``target`` is the
    FURTHEST keyframe from ``start`` whose **recorded** path length from
    ``start`` still fits inside ``reach_radius_m``.

    The bound is on RECORDED path length, not straight-line distance, and that
    is the whole safety argument for this function.  A U-shaped corridor puts a
    keyframe 3 m away in a straight line and 25 m away along the route; taking
    the euclidean-nearest reachable keyframe as the interim SE2 goal would ask
    the planner to cross the wall between them -- memory inventing the shortcut
    RM-1's router refuses to invent.  Bounding the RECORDED length by half the
    rolling planner window (``DEFAULT_ATTACH_RADIUS_M`` = 8.05 m, RM-1's own
    derivation) guarantees the entire remembered leg between the robot and the
    interim waypoint lies inside one window of live occupancy, so the planner
    has current sensor evidence for every metre of it and remains free to route
    around, or refuse, whatever it actually sees there.  Memory chooses WHERE to
    aim; it never asserts that the ground is clear.

    Returns ``None`` when the robot is already at the chain's terminal keyframe
    -- the chain is spent and the caller must hand back to normal planning.
    """

    if not chain:
        return None
    robot = (float(robot_xy[0]), float(robot_xy[1]))
    if not all(math.isfinite(v) for v in robot):
        raise ValueError("robot_xy must be finite")
    reached = float(reached_m)
    reach = float(reach_radius_m)
    if not math.isfinite(reached) or reached <= 0.0:
        raise ValueError("reached_m must be finite and positive")
    if not math.isfinite(reach) or reach <= 0.0:
        raise ValueError("reach_radius_m must be finite and positive")

    start = _attach_index(chain, robot)
    if math.hypot(chain[start].x - robot[0], chain[start].y - robot[1]) <= reached:
        start += 1
    if start >= len(chain):
        # The robot stands on the last recorded keyframe: memory has nothing
        # further to offer and the remaining leg is the planner's.
        return None

    target = start
    travelled = 0.0
    for i in range(start + 1, len(chain)):
        step = math.hypot(chain[i].x - chain[i - 1].x, chain[i].y - chain[i - 1].y)
        if travelled + step > reach:
            break
        if math.hypot(chain[i].x - robot[0], chain[i].y - robot[1]) > reach:
            # Belt and braces: the recorded leg fits the window but this point
            # does not. Never aim outside the live map.
            break
        travelled += step
        target = i
    return (start, target)


def waypoint_goal_from_chain(
    chain: Sequence[RouteKeyframe],
    *,
    robot_xy: Sequence[float],
    now_s: float,
    task_id: str = "",
    plan_revision: int = 0,
    plan_step_id: str = "",
    reached_m: float = DEFAULT_WAYPOINT_REACHED_M,
    reach_radius_m: float = DEFAULT_ATTACH_RADIUS_M,
    ttl_s: float = 2.0,
    confidence: float = 0.8,
    priority: int = 3,
    source: str = PLACE_ROUTE_SOURCE,
    final_heading_xy: Sequence[float] | None = None,
) -> SE2Goal | None:
    """One interim SE2Goal along a RECORDED chain, or ``None`` when spent.

    ``ttl_s`` / ``confidence`` / ``priority`` are this module's already-published
    :class:`RouteMemoryProposer` defaults, carried over rather than re-picked:
    2.0 s matches every other ``SE2Goal`` the navigation pipeline publishes, and
    priority 3 keeps a remembered waypoint strictly below the grounder's
    committed approach pose (priority 10) in any pool that ever contains both.

    The goal's ``waypoints`` carry the whole ``start..target`` slice, so
    :meth:`GoalArbiter.resolve`'s lethal veto is evaluated over every
    intermediate point of the leg, not just its tip.

    ``task_id`` / ``plan_revision`` are the caller's ACTIVE revision key. They
    are what makes a waypoint droppable by the P0-C flush: a proposal authored
    under a corrected-away revision can never buffer and can never win.
    """

    span = next_waypoint_keyframe(
        chain,
        robot_xy,
        reached_m=reached_m,
        reach_radius_m=reach_radius_m,
    )
    if span is None:
        return None
    start, target = span
    slice_kfs = tuple(chain[start : target + 1])
    tip = slice_kfs[-1]
    if target + 1 < len(chain):
        ahead = chain[target + 1]
        yaw = math.atan2(ahead.y - tip.y, ahead.x - tip.x)
    elif final_heading_xy is not None:
        yaw = math.atan2(
            float(final_heading_xy[1]) - tip.y, float(final_heading_xy[0]) - tip.x
        )
    elif len(slice_kfs) >= 2:
        previous = slice_kfs[-2]
        yaw = math.atan2(tip.y - previous.y, tip.x - previous.x)
    else:
        yaw = float(tip.yaw_rad)
    waypoints = tuple((kf.x, kf.y) for kf in slice_kfs)
    return SE2Goal(
        source=source,
        pose=(float(tip.x), float(tip.y), float(yaw)),
        waypoints=waypoints if len(waypoints) > 1 else (),
        frame=str(getattr(tip, "frame", "map") or "map"),
        confidence=confidence,
        ttl_s=ttl_s,
        plan_step_id=plan_step_id,
        issued_s=float(now_s),
        priority=priority,
        task_id=str(task_id),
        plan_revision=int(plan_revision),
    )
