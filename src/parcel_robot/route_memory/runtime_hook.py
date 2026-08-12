"""Thin runtime / test hook for Phase-4 route memory (extras-shaped).

Does not wire into RobotRuntime by default — learned proposers stay behind
gates. Tests and optional sim injectors use this seam.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, MutableMapping
from dataclasses import dataclass, field
from typing import Any

from parcel_robot.route_memory.citywalker import CityWalkerInferenceAdapter, CityWalkerResult
from parcel_robot.route_memory.memory import RouteKeyframe
from parcel_robot.route_memory.place_graph import RoutePlaceGraph
from parcel_robot.route_memory.proposer import RouteMemoryProposer
from parcel_robot.route_memory.teach_repeat import TeachRepeatSession

EXTRAS_KEY = "route_memory"

#: Extras key for the RM-2 place-graph hook. Deliberately NOT ``EXTRAS_KEY``:
#: the two hooks are independent and a shared key would let whichever ran last
#: silently erase the other's payload.
PLACE_EXTRAS_KEY = "route_memory_place"

DOES_NOT_PROVE = (
    (
        "RouteMemoryRuntimeHook only publishes extras / proposer snapshots; "
        "it does not enable learned velocity, bypass GoalArbiter, or claim "
        "field route-memory validation (HR-12)."
    ),
    (
        "RouteMemoryPlaceHook counts what was ingested and what was proposed. "
        "A high keyframe count is a record of where the robot has BEEN, not "
        "evidence that any of it is still traversable, and a won proposal is "
        "an interim navigation target, never an arrival (card RM-2)."
    ),
)


@dataclass
class RouteMemoryRuntimeHook:
    """Hold a TeachRepeatSession + optional CityWalker adapter for tests/sim."""

    session: TeachRepeatSession = field(default_factory=TeachRepeatSession)
    citywalker: CityWalkerInferenceAdapter | None = None
    active_path_id: str | None = None
    _follower: RouteMemoryProposer | None = field(default=None, init=False, repr=False)

    def teach_poses(self, poses, **kwargs) -> str:
        path = self.session.teach(poses, **kwargs)
        return path.path_id

    def arm_follow(self, path_id: str, *, gate_enabled: bool = False, **kwargs) -> RouteMemoryProposer:
        proposer = self.session.follow(path_id, gate_enabled=gate_enabled, **kwargs)
        self.active_path_id = path_id
        self._follower = proposer
        return proposer

    def propose_route(
        self,
        *,
        now_s: float,
        robot_x: float,
        robot_y: float,
        robot_yaw: float = 0.0,
    ):
        if self._follower is None:
            return None
        return self._follower.propose(
            now_s=now_s,
            robot_x=robot_x,
            robot_y=robot_y,
            robot_yaw=robot_yaw,
        )

    def propose_citywalker(self, observation, *, now_s: float) -> CityWalkerResult | None:
        if self.citywalker is None:
            return None
        return self.citywalker.propose(observation, now_s=now_s)

    def inject_extras(
        self,
        extras: MutableMapping[str, Any],
        *,
        now_s: float,
        snapshot: Mapping[str, Any] | None = None,
    ) -> MutableMapping[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": 1,
            "active_path_id": self.active_path_id,
            "gate_enabled": bool(self._follower.gate_enabled) if self._follower else False,
            "paths": list(self.session.list_paths()),
            "does_not_prove": list(DOES_NOT_PROVE),
            "now_s": float(now_s),
        }
        if self._follower is not None:
            payload["follower"] = self._follower.as_dict()
        if self.citywalker is not None:
            payload["citywalker"] = self.citywalker.availability()
        if snapshot is not None:
            payload["snapshot"] = dict(snapshot)
        extras[EXTRAS_KEY] = payload
        return extras


# ---------------------------------------------------------------------------
# RM-2: the product-path hook. Owns ONE session-scoped
# :class:`~parcel_robot.route_memory.place_graph.RoutePlaceGraph`, feeds it from
# whatever the caller is already observing, and counts every ingestion and every
# proposal so a flag-ON run can be checked for non-vacuity instead of assumed.
# ---------------------------------------------------------------------------


def provider_reanchor_count(provider: Any) -> int | None:
    """The pose provider's OWN re-anchor event count, or ``None`` if it has none.

    RM-1's stated limitation (RM1_STATUS.md §4): the distance backstop cannot
    tell a genuine 2 m MAP jump from 2 s of unsampled walking, and RM-2 "should
    pass ``reanchored=True`` from the pose provider's own correction event where
    it can".

    Measured answer, honestly: **it cannot today.**
    ``parcel_robot.pose.DriftingOdomProvider`` performs the re-anchor inside
    ``_maybe_correct_map`` and publishes no counter for it; ``pose.py`` is DR-1's
    file and out of this card's OWNS, so nothing is added there. This function is
    the seam that consumes such a counter the moment one exists -- it duck-types
    two plausible names, returns ``None`` otherwise, and the caller then falls
    back to RM-1's documented backstop, whose error is one-directional (a
    spurious flag costs routability, never safety).

    Recorded as a handoff in ``scrum/20260811/task_2/RM2_STATUS.md``.
    """

    for name in ("map_correction_events", "reanchor_events"):
        value = getattr(provider, name, None)
        if isinstance(value, bool) or not isinstance(value, int):
            continue
        if value < 0:
            continue
        return value
    return None


@dataclass
class RouteMemoryPlaceHook:
    """Session-scoped place graph + the counters that make a run falsifiable.

    Every counter here is append-only evidence and is read by NO decision, which
    is the same discipline D15-B's engagement counters and VS-4's verify counters
    follow. ``proposals_won`` in particular is a record of arbitration outcomes,
    not an input to one.
    """

    graph: RoutePlaceGraph = field(default_factory=RoutePlaceGraph)
    #: Visits handed to the graph (every ingest attempt, admitted or not).
    visits: int = 0
    #: Visits that became a NEW recorded place.
    keyframes_admitted: int = 0
    #: ``waypoints_toward`` calls, and how many returned a non-empty chain.
    routes_queried: int = 0
    routes_found: int = 0
    #: SE2Goal waypoint proposals published, and how many the arbiter admitted.
    proposals_made: int = 0
    proposals_won: int = 0
    proposals_vetoed: int = 0
    #: Re-anchor signals taken from the provider's own event counter (never the
    #: distance backstop -- that one is counted by the graph itself).
    provider_reanchors: int = 0
    _last_provider_reanchors: int | None = field(default=None, init=False, repr=False)

    def reset_track(self) -> None:
        """Episode / mission boundary. Keeps the graph, breaks the ingest track.

        MANDATORY at every boundary (AUDIT_WAVE1_FABLE.md, cross-lane intel):
        without it the teleport from one episode's end pose to the next
        episode's start pose is recorded as a traversal, and the router would
        then hand out an edge across ground nothing ever walked.
        """

        self.graph.reset_track()

    def reanchored_from_provider(self, provider: Any) -> bool:
        """Whether the provider reported a NEW map correction since last asked."""

        count = provider_reanchor_count(provider)
        if count is None:
            return False
        previous = self._last_provider_reanchors
        self._last_provider_reanchors = count
        if previous is None or count <= previous:
            return False
        self.provider_reanchors += count - previous
        return True

    def record(
        self,
        pose: Any,
        *,
        semantic_labels: Iterable[str] = (),
        timestamp_tick: int = 0,
        view_embedding: Any = None,
        reanchored: bool = False,
    ) -> RouteKeyframe | None:
        """Ingest one MAP-frame pose; returns the admitted keyframe or ``None``."""

        self.visits += 1
        keyframe = self.graph.record_visit(
            pose,
            semantic_labels=semantic_labels,
            timestamp_tick=int(timestamp_tick),
            view_embedding=view_embedding,
            reanchored=bool(reanchored),
        )
        if keyframe is not None:
            self.keyframes_admitted += 1
        return keyframe

    def route(
        self, goal_xy: Any, from_xy: Any
    ) -> tuple[RouteKeyframe, ...]:
        """RM-1's frozen query. ``()`` means "memory has no route" -- fail closed."""

        self.routes_queried += 1
        chain = self.graph.waypoints_toward(goal_xy, from_xy)
        if chain:
            self.routes_found += 1
        return chain

    def note_proposal(self, *, won: bool) -> None:
        self.proposals_made += 1
        if won:
            self.proposals_won += 1
        else:
            self.proposals_vetoed += 1

    def snapshot(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "keyframes": len(self.graph),
            "edges": len(self.graph.edges),
            "visits": self.visits,
            "keyframes_admitted": self.keyframes_admitted,
            "routes_queried": self.routes_queried,
            "routes_found": self.routes_found,
            "proposals_made": self.proposals_made,
            "proposals_won": self.proposals_won,
            "proposals_vetoed": self.proposals_vetoed,
            "graph_reanchor_events": self.graph.reanchor_events,
            "provider_reanchors": self.provider_reanchors,
        }

    def inject_extras(
        self,
        extras: MutableMapping[str, Any],
        *,
        now_s: float,
    ) -> MutableMapping[str, Any]:
        payload = self.snapshot()
        payload["now_s"] = float(now_s)
        payload["does_not_prove"] = list(DOES_NOT_PROVE)
        extras[PLACE_EXTRAS_KEY] = payload
        return extras
