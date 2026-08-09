"""OSM footway graph → SE2Goal waypoint proposer for GoalArbiter."""

from __future__ import annotations

import math
from dataclasses import dataclass

from parcel_robot.instructnav.arbiter import SE2Goal
from parcel_robot.maps.graph import FootwayCrossingGraph

PROPOSER_SOURCE = "osm_footway_v1"

DOES_NOT_PROVE = (
    (
        "OSM waypoint proposer is a topological prior only; grid_v1 A* remains the "
        "motion authority (no Nav2 migration)."
    ),
)


@dataclass(frozen=True, slots=True)
class OsmWaypointProposer:
    """Emit SE2Goal waypoints along the cached footway graph.

    Crossing edges are excluded unless ``allow_crossing`` is True. Crossing
    mode (voice-authorized) is the only legitimate source of that flag —
    proposers must never flip it on their own.
    """

    graph: FootwayCrossingGraph
    priority: int = 2
    ttl_s: float = 2.0
    confidence: float = 0.85
    plan_step_id: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.graph, FootwayCrossingGraph):
            raise TypeError("graph must be FootwayCrossingGraph")
        if isinstance(self.priority, bool) or not isinstance(self.priority, int):
            raise TypeError("priority must be an integer")
        if not math.isfinite(self.ttl_s) or self.ttl_s <= 0.0:
            raise ValueError("ttl_s must be finite and positive")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be in [0, 1]")

    def propose(
        self,
        *,
        now_s: float,
        robot_x: float,
        robot_y: float,
        goal_x: float,
        goal_y: float,
        allow_crossing: bool = False,
    ) -> SE2Goal | None:
        """Return an SE2Goal along footways, or None if no non-crossing path."""

        for name, value in (
            ("now_s", now_s),
            ("robot_x", robot_x),
            ("robot_y", robot_y),
            ("goal_x", goal_x),
            ("goal_y", goal_y),
        ):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"{name} must be numeric")
            if not math.isfinite(float(value)):
                raise ValueError(f"{name} must be finite")
        if not isinstance(allow_crossing, bool):
            raise TypeError("allow_crossing must be a boolean")

        # Fail-closed: never propose a goal inside the road keepout unless
        # crossing mode explicitly authorized (still waypoints only).
        if self.graph.is_road_keepout(goal_x, goal_y) and not allow_crossing:
            return None

        waypoints = self.graph.path_waypoints(
            (robot_x, robot_y),
            (goal_x, goal_y),
            allow_crossing=allow_crossing,
        )
        if waypoints is None:
            return None
        if len(waypoints) == 1:
            pose = (waypoints[0][0], waypoints[0][1], 0.0)
            return SE2Goal(
                source=PROPOSER_SOURCE,
                pose=pose,
                waypoints=(),
                confidence=self.confidence,
                ttl_s=self.ttl_s,
                plan_step_id=self.plan_step_id,
                issued_s=float(now_s),
                priority=self.priority,
            )
        terminal = waypoints[-1]
        yaw = math.atan2(
            terminal[1] - waypoints[-2][1],
            terminal[0] - waypoints[-2][0],
        )
        return SE2Goal(
            source=PROPOSER_SOURCE,
            pose=(terminal[0], terminal[1], yaw),
            waypoints=waypoints,
            confidence=self.confidence,
            ttl_s=self.ttl_s,
            plan_step_id=self.plan_step_id,
            issued_s=float(now_s),
            priority=self.priority,
        )

    def as_bus_proposer(self, *, goal_x: float, goal_y: float, allow_crossing: bool = False):
        """Adapter matching ProposerBus ``proposer(now_s=..., **ctx)`` shape."""

        def _propose(*, now_s: float, robot_x: float = 0.0, robot_y: float = 0.0, **_ctx):
            return self.propose(
                now_s=now_s,
                robot_x=robot_x,
                robot_y=robot_y,
                goal_x=goal_x,
                goal_y=goal_y,
                allow_crossing=allow_crossing,
            )

        return _propose
