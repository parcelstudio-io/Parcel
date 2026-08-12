"""Queryable MAP-frame place graph over the route-memory keyframe store.

This is the RM-1 half of the route-memory wiring
(``scrum/20260811/task_2/SLAM_M_PLAN.md``): ingestion, a recorded-edges-only
route query, and versioned persistence.  It is deliberately **pure** — stdlib
plus :mod:`parcel_robot.pose` (itself stdlib-only) plus the store's own
:class:`~parcel_robot.route_memory.memory.RouteKeyframe`.  No onnx, no torch,
no navigation import, no runtime import.

What this is not
----------------
This is **not** SLAM and not a localizer.  It records where the robot has
already been, in the frame the pose authority hands it, and answers exactly one
question: *given that history, is there a chain of places I have actually
traversed that leads from here toward there?*  It never proposes a shortcut
through space it has not visited, and it never converts a chain into an
``SE2Goal`` — that conversion lives in ``proposer.py`` (card RM-2).

REP-105 frame discipline, day one
---------------------------------
Poses arrive as :class:`~parcel_robot.pose.PoseEstimate` values obtained through
the sanctioned seam :func:`parcel_robot.pose.observation_pose`, and
:meth:`RoutePlaceGraph.record_visit` **refuses** anything that is not
:attr:`~parcel_robot.pose.Frame.MAP`.  ``ODOM`` is continuous but drifts without
bound, so an ``ODOM`` place graph would slowly describe a world that does not
exist; ``MAP`` is globally consistent, which is precisely the property a place
graph needs, and its documented cost is that it *may jump*.  The frame is
recorded in the persisted schema at both the graph level and on every keyframe,
and :meth:`load` refuses a file that claims any other frame.

Behaviour under a MAP re-anchor jump (the contract)
---------------------------------------------------
Keyframes are **MAP snapshots**: each one is the robot's best global estimate at
the tick it was admitted, and a later re-anchor does not retroactively move it.
There is no bundle adjustment here and none is planned.

An edge, by contrast, is a claim about *traversal*: "I walked from place A to
place B."  A MAP re-anchor teleports the estimate without the robot moving, so
an edge recorded across a jump is not a traversal claim — it is an artefact of
the correction.  Such edges are therefore:

1. **recorded** (the history stays honest — the graph does not pretend the jump
   did not happen), and
2. **flagged** ``crossed_reanchor=True``, and
3. **excluded from routing** by :meth:`waypoints_toward`, because routing over
   one would be exactly the "invented shortcut" the card forbids: a straight
   line the robot never walked.

A jump is detected two ways.  A caller that knows a correction occurred passes
``reanchored=True`` (authoritative).  Absent that, a single sample displacing
more than ``max_contiguous_step_m`` is treated as a discontinuity.  The
distance heuristic is cadence-dependent and its errors are one-directional by
construction: a caller sampling too coarsely gets *spurious* flags, which costs
routability (empty tuple, fail-closed) and never safety.  A ``POSE_LOST`` sample
also breaks the track, since MAP will jump when localization recovers.

Embedding seam
--------------
``embed_fn`` is a ``Callable[[Any], Sequence[float]]`` — the exact shape of
``parcel_robot.instructnav.siglip2_onnx``'s ``embed_image``::

    from parcel_robot.instructnav.siglip2_onnx import load_onnx_embedder

    embedder = load_onnx_embedder(weights_dir)          # None when onnx is off
    graph = RoutePlaceGraph(embed_fn=embedder.embed_image)

The default is :func:`stub_embed_image`, a deterministic hash stand-in.  This
module must never import onnx, onnxruntime, or the siglip modules — the import
belongs at the injection site, and ``tests/test_p4_place_graph.py`` pins that.
"""

from __future__ import annotations

import heapq
import json
import math
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from parcel_robot.pose import Frame, PoseEstimate, PoseHealth
from parcel_robot.route_memory.memory import RouteKeyframe
from parcel_robot.route_memory.vpr import StubVPREmbedder

PLACE_GRAPH_SCHEMA = "parcel.route_memory.place_graph.v1"

DOES_NOT_PROVE = (
    (
        "RoutePlaceGraph is a MAP-frame visit log with recorded-edges-only "
        "routing over sim poses; it does not prove SLAM, loop-closure "
        "correctness under real localization, visual place recognition recall, "
        "or that a recorded edge is still traversable now (HR-12)."
    ),
)

# ---------------------------------------------------------------------------
# Derived constants.  Each is stated once, here, with the value it derives
# from.  ``tests/test_p4_place_graph.py`` pins every one of these BY REFERENCE
# against the live source config, so a change to the planner reddens the gate
# instead of silently invalidating the derivation.
# ---------------------------------------------------------------------------

#: Mirror of ``GridPlannerConfig.resolution_m`` (navigation/grid_planner.py:138).
#: Mirrored rather than imported so this module stays free of navigation
#: imports; the test asserts the two are equal.
GRID_RESOLUTION_M = 0.10

#: Mirror of ``GridPlannerConfig.goal_tolerance_m`` (navigation/grid_planner.py).
GRID_GOAL_TOLERANCE_M = 0.25

#: Mirror of ``GridPlannerConfig.grid_size_cells`` (navigation/grid_planner.py).
GRID_SIZE_CELLS = 161

#: Mirror of ``configs/robot.yaml`` ``motion.max_vx`` (line 147).
PLATFORM_MAX_VX_MPS = 1.0

#: Mirror of ``GridNavigator.control_dt_s`` default (navigation/grid_navigator.py:94).
NAV_CONTROL_DT_S = 0.1

# Derivation of the keyframe spacing, once.
#
# The planner's spatial quantum is ``resolution_m`` = 0.10 m, so a spacing that
# is not an integer multiple of it cannot be represented as a distinct planner
# goal anyway.  The binding constraint on the multiple is that two consecutive
# keyframes must be individually reachable as SE2 goals: each carries an arrival
# disc of radius ``goal_tolerance_m`` = 0.25 m, and if those discs overlap then
# standing at one keyframe already satisfies its neighbour and the two are not
# distinct places.  Non-overlap requires spacing >= 2 * 0.25 = 0.50 m, and
# 0.50 / 0.10 = 5 cells exactly.  Five is therefore the SMALLEST integer number
# of grid cells satisfying the constraint — the coarsest thing the derivation
# forces and the finest that is meaningful.  Nothing here is tuned to a gate:
# drop to 4 cells and neighbouring arrival discs overlap.
KEYFRAME_SPACING_CELLS = 5
DEFAULT_KEYFRAME_SPACING_M = KEYFRAME_SPACING_CELLS * GRID_RESOLUTION_M  # 0.50 m

# Derivation of the contiguity threshold, once.
#
# Admission guarantees consecutive keyframes are at least one spacing apart but
# imposes no upper bound, so "how far can one sample legitimately move?" has to
# come from the platform.  At ``max_vx`` = 1.0 m/s the robot covers
# ``max_vx * control_dt_s`` = 0.10 m per navigation tick.  A sample that
# displaces four spacings (2.00 m) therefore implies at least 2.0 s — twenty
# navigation ticks — of unobserved motion.  For any caller sampling at or near
# the navigation tick that is not motion; it is a MAP discontinuity.  Four
# spacings is also the point at which at least three admission opportunities
# were skipped, so the resulting edge could not describe a contiguous walk.
MAX_CONTIGUOUS_STEP_SPACINGS = 4
DEFAULT_MAX_CONTIGUOUS_STEP_M = MAX_CONTIGUOUS_STEP_SPACINGS * DEFAULT_KEYFRAME_SPACING_M  # 2.00 m

# Derivation of the attach radius, once.
#
# ``waypoints_toward`` returns only recorded keyframes; the leg from the robot's
# actual position to the first returned keyframe, and the leg from the last one
# to the true goal, are the *planner's* job, not memory's.  That hand-off is
# only honest while those legs lie inside one rolling planner window, where the
# planner has live occupancy and can refuse or route around what it sees.  The
# window spans ``grid_size_cells * resolution_m`` = 161 * 0.10 = 16.10 m centred
# on the robot, so its half-span is 8.05 m.  Beyond that, attaching would be
# memory asserting reachability over ground no live map covers, so the query
# fails closed instead.
DEFAULT_ATTACH_RADIUS_M = GRID_SIZE_CELLS * GRID_RESOLUTION_M / 2.0  # 8.05 m

#: Dimensionality of the default stub embedding (``StubVPREmbedder`` default).
STUB_EMBED_DIM = 64

#: Fail-closed cap on labels carried per keyframe.
MAX_LABELS_PER_KEYFRAME = 64

#: Float slack for the ">= spacing" admission comparison.
_EPS_M = 1e-9


def stub_embed_image(image: Any) -> tuple[float, ...]:
    """Deterministic stand-in for ``siglip2_onnx``'s ``embed_image``.

    Same call shape as the real seam — one positional image, one L2-normalized
    float tuple out — so swapping in the onnx embedder is a constructor
    argument and nothing else.  UNVERIFIED for real SigLIP2 recall.
    """

    payload = image if isinstance(image, (bytes, bytearray)) else repr(image).encode("utf-8")
    return StubVPREmbedder(dim=STUB_EMBED_DIM).embed(frame_bytes=bytes(payload))


@dataclass(frozen=True, slots=True)
class PlaceEdge:
    """One recorded traversal between two keyframes.

    Undirected: ``a`` and ``b`` are stored with ``a < b`` and the query treats
    the edge as walkable both ways.  That is the single stated assumption in
    this module — a ground robot that walked A->B can walk B->A — and it is the
    only place where the graph asserts anything the robot did not literally do.
    Everything else is a replay of recorded motion.
    """

    a: int
    b: int
    length_m: float
    crossed_reanchor: bool = False
    traversals: int = 1

    def __post_init__(self) -> None:
        for name, value in (("a", self.a), ("b", self.b), ("traversals", self.traversals)):
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{name} must be an int")
        if self.a < 0 or self.b < 0:
            raise ValueError("edge endpoints must be non-negative")
        if self.a >= self.b:
            raise ValueError("edge endpoints must be stored as a < b")
        if self.traversals < 1:
            raise ValueError("traversals must be >= 1")
        if isinstance(self.length_m, bool) or not isinstance(self.length_m, (int, float)):
            raise TypeError("length_m must be numeric")
        if not math.isfinite(float(self.length_m)) or float(self.length_m) < 0.0:
            raise ValueError("length_m must be finite and non-negative")
        if not isinstance(self.crossed_reanchor, bool):
            raise TypeError("crossed_reanchor must be a boolean")

    @property
    def key(self) -> tuple[int, int]:
        return (self.a, self.b)

    @property
    def routable(self) -> bool:
        """False for edges recorded across a MAP re-anchor jump."""

        return not self.crossed_reanchor

    def as_dict(self) -> dict[str, Any]:
        return {
            "a": int(self.a),
            "b": int(self.b),
            "length_m": float(self.length_m),
            "crossed_reanchor": bool(self.crossed_reanchor),
            "traversals": int(self.traversals),
        }

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> PlaceEdge:
        if not isinstance(data, Mapping):
            raise TypeError("PlaceEdge data must be a mapping")
        for required in ("a", "b", "length_m"):
            if required not in data:
                raise ValueError(f"edge missing required key: {required!r}")
        raw_flag = data.get("crossed_reanchor", False)
        if not isinstance(raw_flag, bool):
            raise TypeError("crossed_reanchor must be a boolean")
        for name in ("a", "b"):
            if isinstance(data[name], bool) or not isinstance(data[name], int):
                raise TypeError(f"edge {name} must be an int")
        raw_traversals = data.get("traversals", 1)
        if isinstance(raw_traversals, bool) or not isinstance(raw_traversals, int):
            raise TypeError("traversals must be an int")
        return cls(
            a=int(data["a"]),
            b=int(data["b"]),
            length_m=float(data["length_m"]),
            crossed_reanchor=raw_flag,
            traversals=int(raw_traversals),
        )


def _positive(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be numeric")
    out = float(value)
    if not math.isfinite(out) or out <= 0.0:
        raise ValueError(f"{name} must be finite and positive")
    return out


def _xy(value: object, name: str) -> tuple[float, float]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or len(value) < 2:
        raise TypeError(f"{name} must be an (x, y) sequence")
    out = (float(value[0]), float(value[1]))
    if not all(math.isfinite(v) for v in out):
        raise ValueError(f"{name} components must be finite")
    return out


class RoutePlaceGraph:
    """MAP-frame place graph: visit ingestion + recorded-edges-only routing.

    Construction knobs, all derived-by-default (see the module constants)::

        RoutePlaceGraph(
            keyframe_spacing_m=DEFAULT_KEYFRAME_SPACING_M,      # 0.50 m
            max_contiguous_step_m=DEFAULT_MAX_CONTIGUOUS_STEP_M, # 2.00 m
            attach_radius_m=DEFAULT_ATTACH_RADIUS_M,             # 8.05 m
            embed_fn=stub_embed_image,
        )

    Persistence is **session-scoped by default**: nothing is written unless
    :meth:`save` is called with a path.  Whether a saved graph is reloaded
    across sessions is an owner-gated policy question (SLAM_M_PLAN OPEN
    items); this class only supplies the mechanism.
    """

    def __init__(
        self,
        *,
        keyframe_spacing_m: float = DEFAULT_KEYFRAME_SPACING_M,
        max_contiguous_step_m: float = DEFAULT_MAX_CONTIGUOUS_STEP_M,
        attach_radius_m: float = DEFAULT_ATTACH_RADIUS_M,
        embed_fn: Callable[[Any], Sequence[float]] | None = None,
    ) -> None:
        self._spacing_m = _positive(keyframe_spacing_m, "keyframe_spacing_m")
        self._max_step_m = _positive(max_contiguous_step_m, "max_contiguous_step_m")
        self._attach_m = _positive(attach_radius_m, "attach_radius_m")
        if self._max_step_m < self._spacing_m:
            raise ValueError("max_contiguous_step_m must be >= keyframe_spacing_m")
        if embed_fn is not None and not callable(embed_fn):
            raise TypeError("embed_fn must be callable")
        self._embed_fn: Callable[[Any], Sequence[float]] = (
            stub_embed_image if embed_fn is None else embed_fn
        )
        self._keyframes: list[RouteKeyframe] = []
        self._edges: list[PlaceEdge] = []
        self._edge_at: dict[tuple[int, int], int] = {}
        self._last_node: int | None = None
        self._last_sample_xy: tuple[float, float] | None = None
        self._pending_reanchor = False
        self._reanchor_events = 0

    # -- introspection -----------------------------------------------------

    @property
    def frame(self) -> Frame:
        """The one frame this graph accepts and persists."""

        return Frame.MAP

    @property
    def keyframe_spacing_m(self) -> float:
        return self._spacing_m

    @property
    def max_contiguous_step_m(self) -> float:
        return self._max_step_m

    @property
    def attach_radius_m(self) -> float:
        return self._attach_m

    @property
    def keyframes(self) -> tuple[RouteKeyframe, ...]:
        return tuple(self._keyframes)

    @property
    def edges(self) -> tuple[PlaceEdge, ...]:
        return tuple(self._edges)

    @property
    def reanchor_events(self) -> int:
        """Count of detected MAP discontinuities since construction/load."""

        return self._reanchor_events

    def __len__(self) -> int:
        return len(self._keyframes)

    def stats(self) -> dict[str, Any]:
        routable = sum(1 for e in self._edges if e.routable)
        return {
            "schema_version": PLACE_GRAPH_SCHEMA,
            "frame": self.frame.value,
            "keyframes": len(self._keyframes),
            "edges": len(self._edges),
            "routable_edges": routable,
            "reanchor_edges": len(self._edges) - routable,
            "reanchor_events": self._reanchor_events,
            "keyframe_spacing_m": self._spacing_m,
            "does_not_prove": list(DOES_NOT_PROVE),
        }

    # -- ingestion ---------------------------------------------------------

    def record_visit(
        self,
        pose: PoseEstimate,
        *,
        view_embedding: Sequence[float] | None = None,
        semantic_labels: Iterable[str] = (),
        timestamp_tick: int = 0,
        view_image: Any = None,
        reanchored: bool = False,
    ) -> RouteKeyframe | None:
        """Ingest one MAP-frame observation of where the robot is.

        Returns the newly admitted :class:`RouteKeyframe`, or ``None`` when the
        visit fell inside a place already recorded (or was refused).  A visit
        that lands within one ``keyframe_spacing_m`` of an existing keyframe is
        that place — it is not a new node — and the traversal that got the robot
        there is still recorded as an edge, which is how a re-driven route
        closes its loops instead of growing a parallel chain of duplicates.

        Refusals (all return ``None``, none raise except on programmer error):

        * ``PoseHealth.LOST`` — a lost pose is not a place.  The track breaks,
          so the next admitted edge is flagged: MAP jumps on recovery.

        Raises for contract violations the caller must fix:

        * ``pose`` is not a :class:`~parcel_robot.pose.PoseEstimate`,
        * ``pose.frame`` is not :attr:`~parcel_robot.pose.Frame.MAP`.
        """

        if not isinstance(pose, PoseEstimate):
            raise TypeError(
                "record_visit requires a PoseEstimate from the sanctioned seam "
                "(parcel_robot.pose.observation_pose(observation, Frame.MAP))"
            )
        if pose.frame is not Frame.MAP:
            raise ValueError(
                f"place graph ingests MAP-frame poses only; got {pose.frame.value!r}. "
                "ODOM drifts without bound — an ODOM place graph describes a world "
                "that does not exist."
            )
        if isinstance(timestamp_tick, bool) or not isinstance(timestamp_tick, int):
            raise TypeError("timestamp_tick must be an int")
        if timestamp_tick < 0:
            raise ValueError("timestamp_tick must be non-negative")

        if bool(reanchored):
            self._mark_discontinuity()

        if pose.health is PoseHealth.LOST:
            # Break the track without recording: the estimate is not a place.
            self._mark_discontinuity()
            self._last_sample_xy = None
            return None

        here = (float(pose.x), float(pose.y))
        if self._last_sample_xy is not None:
            step = math.hypot(here[0] - self._last_sample_xy[0], here[1] - self._last_sample_xy[1])
            if step > self._max_step_m:
                self._mark_discontinuity()
        self._last_sample_xy = here

        # A visit STRICTLY inside one spacing of a known keyframe is that place.
        # The comparison must be strict: a pose exactly one spacing from the
        # previous keyframe is the first admissible new place, and treating it
        # as a revisit would freeze the graph at one node on a straight walk.
        found = self._nearest(here)
        if found is not None and found[1] < self._spacing_m - _EPS_M:
            # Revisit of a known place: no new node, but the walk that arrived
            # here is a real traversal and is recorded as one.  This is how a
            # re-driven route closes its loop instead of growing a duplicate
            # parallel chain.
            existing = found[0]
            self._link(self._last_node, existing, here)
            self._last_node = existing
            return None

        labels = self._clean_labels(semantic_labels)
        embedding = self._resolve_embedding(view_embedding, view_image)
        keyframe = RouteKeyframe(
            x=here[0],
            y=here[1],
            yaw_rad=float(pose.yaw),
            t_s=float(pose.stamp_monotonic_s),
            embedding=embedding,
            frame_id="",
            meta={
                "pose_health": pose.health.value,
                "position_sigma_m": float(pose.position_sigma_m),
            },
            frame=self.frame.value,
            labels=labels,
            tick=int(timestamp_tick),
        )
        index = len(self._keyframes)
        self._keyframes.append(keyframe)
        self._link(self._last_node, index, here)
        self._last_node = index
        return keyframe

    def reset_track(self) -> None:
        """End the current ingestion track without discarding the graph.

        The next :meth:`record_visit` starts fresh: it has no "previous
        keyframe", so no edge is fabricated between wherever the robot is now
        and wherever it last was.  Call this at an episode boundary — the
        teleport from one episode's end pose to the next episode's start pose is
        not a traversal, and recording it as one would hand the router an edge
        across ground nothing ever walked.
        """

        self._last_node = None
        self._last_sample_xy = None
        self._pending_reanchor = False

    def _mark_discontinuity(self) -> None:
        if not self._pending_reanchor:
            self._reanchor_events += 1
        self._pending_reanchor = True

    def _clean_labels(self, semantic_labels: Iterable[str]) -> tuple[str, ...]:
        if isinstance(semantic_labels, (str, bytes)):
            raise TypeError("semantic_labels must be an iterable of strings, not a string")
        seen: list[str] = []
        for label in semantic_labels:
            if not isinstance(label, str):
                raise TypeError("semantic_labels must contain strings")
            text = label.strip()
            if text and text not in seen:
                seen.append(text)
            if len(seen) >= MAX_LABELS_PER_KEYFRAME:
                break
        return tuple(seen)

    def _resolve_embedding(
        self, view_embedding: Sequence[float] | None, view_image: Any
    ) -> tuple[float, ...]:
        if view_embedding is not None:
            if isinstance(view_embedding, (str, bytes)) or not isinstance(
                view_embedding, Sequence
            ):
                raise TypeError("view_embedding must be a sequence of floats")
            return tuple(float(v) for v in view_embedding)
        if view_image is not None:
            return tuple(float(v) for v in self._embed_fn(view_image))
        return ()

    def _link(self, src: int | None, dst: int, dst_xy: tuple[float, float]) -> None:
        """Record the traversal ``src -> dst``; consumes the pending jump flag."""

        if src is None or src == dst:
            # Nothing to connect (first node, or a revisit of the same place).
            # The pending flag survives: it belongs to the NEXT real edge.
            return
        src_kf = self._keyframes[src]
        length = math.hypot(dst_xy[0] - src_kf.x, dst_xy[1] - src_kf.y)
        crossed = self._pending_reanchor
        self._pending_reanchor = False
        key = (src, dst) if src < dst else (dst, src)
        at = self._edge_at.get(key)
        if at is None:
            self._edge_at[key] = len(self._edges)
            self._edges.append(
                PlaceEdge(a=key[0], b=key[1], length_m=length, crossed_reanchor=crossed)
            )
            return
        prior = self._edges[at]
        # One clean traversal is enough to make an edge a real traversal claim;
        # a later jump-crossing re-observation does not un-walk it.  Length keeps
        # the first recorded value so re-driving a route cannot drift the graph.
        self._edges[at] = PlaceEdge(
            a=prior.a,
            b=prior.b,
            length_m=prior.length_m,
            crossed_reanchor=prior.crossed_reanchor and crossed,
            traversals=prior.traversals + 1,
        )

    # -- query -------------------------------------------------------------

    def _nearest(self, point: tuple[float, float]) -> tuple[int, float] | None:
        """``(index, distance)`` of the nearest keyframe; ties to the lowest index."""

        best_i: int | None = None
        best_d = float("inf")
        for i, kf in enumerate(self._keyframes):
            d = math.hypot(kf.x - point[0], kf.y - point[1])
            if d < best_d:
                best_d = d
                best_i = i
        if best_i is None:
            return None
        return (best_i, best_d)

    def nearest_index(
        self, xy: Sequence[float], *, max_radius_m: float | None = None
    ) -> int | None:
        """Index of the nearest keyframe, or ``None`` if none within the radius.

        The radius is **inclusive**.  Ties break to the lowest index, which is
        what makes the query deterministic for a fixed visit history.
        """

        point = _xy(xy, "xy")
        limit = float("inf") if max_radius_m is None else _positive(max_radius_m, "max_radius_m")
        found = self._nearest(point)
        if found is None or found[1] > limit:
            return None
        return found[0]

    def waypoints_toward(
        self, goal_xy: Sequence[float], from_xy: Sequence[float]
    ) -> tuple[RouteKeyframe, ...]:
        """Shortest chain of **recorded** keyframes from ``from_xy`` toward ``goal_xy``.

        The returned tuple starts at the keyframe the robot attaches to (which
        may be slightly behind it) and ends at the recorded keyframe closest to
        the goal.  Every consecutive pair in the result is joined by an edge
        this graph actually recorded and that was not laid across a MAP
        re-anchor jump.  **No shortcut is ever synthesised**: if the only way
        from here to there is a 30 m walk around a U-shaped corridor, that is
        what comes back, not the 10 m straight line across it.

        Returns an **empty tuple** — fail closed, never a guess — when:

        * the graph is empty,
        * no keyframe lies within ``attach_radius_m`` of ``from_xy``,
        * no keyframe lies within ``attach_radius_m`` of ``goal_xy``,
        * or the two attachment points are in different connected components of
          the routable (non-jump) edge set.

        A single-element tuple means the robot is already attached to the
        keyframe nearest the goal.  Converting any of this into an ``SE2Goal``
        is *not* this method's job — see ``proposer.py`` (card RM-2).
        """

        goal = _xy(goal_xy, "goal_xy")
        start = _xy(from_xy, "from_xy")
        if not self._keyframes:
            return ()
        src = self.nearest_index(start, max_radius_m=self._attach_m)
        dst = self.nearest_index(goal, max_radius_m=self._attach_m)
        if src is None or dst is None:
            return ()
        if src == dst:
            return (self._keyframes[src],)
        chain = self._shortest_chain(src, dst)
        if chain is None:
            return ()
        return tuple(self._keyframes[i] for i in chain)

    def _adjacency(self) -> dict[int, list[tuple[int, float]]]:
        """Routable adjacency, built in edge-insertion order (deterministic)."""

        adj: dict[int, list[tuple[int, float]]] = {}
        for edge in self._edges:
            if not edge.routable:
                continue
            adj.setdefault(edge.a, []).append((edge.b, float(edge.length_m)))
            adj.setdefault(edge.b, []).append((edge.a, float(edge.length_m)))
        return adj

    def _shortest_chain(self, src: int, dst: int) -> list[int] | None:
        """Dijkstra over routable edges only.  ``None`` when disconnected."""

        adj = self._adjacency()
        dist: dict[int, float] = {src: 0.0}
        prev: dict[int, int] = {}
        done: set[int] = set()
        # (distance, node) — the node index is the tie-break, so equal-cost
        # frontiers always expand in the same order for the same history.
        heap: list[tuple[float, int]] = [(0.0, src)]
        while heap:
            d, node = heapq.heappop(heap)
            if node in done:
                continue
            done.add(node)
            if node == dst:
                break
            for nbr, cost in adj.get(node, ()):
                if nbr in done:
                    continue
                nd = d + cost
                if nd < dist.get(nbr, float("inf")):
                    dist[nbr] = nd
                    prev[nbr] = node
                    heapq.heappush(heap, (nd, nbr))
        if dst not in done:
            return None
        chain = [dst]
        while chain[-1] != src:
            chain.append(prev[chain[-1]])
        chain.reverse()
        return chain

    # -- persistence -------------------------------------------------------

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": PLACE_GRAPH_SCHEMA,
            "frame": self.frame.value,
            "keyframe_spacing_m": float(self._spacing_m),
            "max_contiguous_step_m": float(self._max_step_m),
            "attach_radius_m": float(self._attach_m),
            "reanchor_events": int(self._reanchor_events),
            "keyframes": [kf.as_dict() for kf in self._keyframes],
            "edges": [e.as_dict() for e in self._edges],
            "does_not_prove": list(DOES_NOT_PROVE),
        }

    def save(self, path: Path | str) -> Path:
        """Write the whole graph to ``path`` (versioned header, sorted keys).

        Serialization is a pure function of the visit history, so the same
        history always produces the same bytes.
        """

        target = Path(path).expanduser()
        if target.parent and not target.parent.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self.as_dict(), indent=2, sort_keys=True) + "\n"
        target.write_text(payload, encoding="utf-8")
        return target

    def load(self, path: Path | str) -> RoutePlaceGraph:
        """Replace this graph's contents from ``path``; returns ``self``.

        **Refuse, do not partially load.**  The file is parsed and validated in
        full into locals before a single attribute of ``self`` is touched, so a
        corrupt or truncated file raises and leaves the live graph exactly as it
        was.  A half-ingested place graph is worse than none: it would route
        confidently over edges whose endpoints were never read.

        Loading also **resets the ingestion track** — a loaded graph has no
        "previous keyframe", so the next :meth:`record_visit` starts a fresh
        track and cannot fabricate an edge between wherever the robot is now and
        wherever the file's last keyframe happened to be.
        """

        source = Path(path).expanduser()
        if not source.is_file():
            raise FileNotFoundError(f"place graph file missing: {source}")
        raw = source.read_text(encoding="utf-8")
        data = json.loads(raw)  # JSONDecodeError on a truncated/garbled file
        parsed = self._parse(data)
        # --- single commit point; everything above can raise freely ---
        (
            self._spacing_m,
            self._max_step_m,
            self._attach_m,
            self._keyframes,
            self._edges,
            self._edge_at,
            self._reanchor_events,
        ) = parsed
        self.reset_track()
        return self

    @classmethod
    def from_file(
        cls, path: Path | str, *, embed_fn: Callable[[Any], Sequence[float]] | None = None
    ) -> RoutePlaceGraph:
        """Construct a new graph from ``path`` (same validation as :meth:`load`)."""

        return cls(embed_fn=embed_fn).load(path)

    @staticmethod
    def _parse(
        data: Any,
    ) -> tuple[
        float,
        float,
        float,
        list[RouteKeyframe],
        list[PlaceEdge],
        dict[tuple[int, int], int],
        int,
    ]:
        if not isinstance(data, Mapping):
            raise TypeError("place graph JSON must be an object")
        schema = data.get("schema_version")
        if schema != PLACE_GRAPH_SCHEMA:
            raise ValueError(
                f"unsupported place graph schema: {schema!r} (expected {PLACE_GRAPH_SCHEMA!r})"
            )
        frame = data.get("frame")
        if frame != Frame.MAP.value:
            raise ValueError(
                f"place graph frame must be {Frame.MAP.value!r}, got {frame!r}; "
                "a non-MAP graph is refused rather than reinterpreted"
            )
        spacing = _positive(data.get("keyframe_spacing_m"), "keyframe_spacing_m")
        max_step = _positive(data.get("max_contiguous_step_m"), "max_contiguous_step_m")
        attach = _positive(data.get("attach_radius_m"), "attach_radius_m")
        if max_step < spacing:
            raise ValueError("max_contiguous_step_m must be >= keyframe_spacing_m")
        raw_events = data.get("reanchor_events", 0)
        if isinstance(raw_events, bool) or not isinstance(raw_events, int) or raw_events < 0:
            raise ValueError("reanchor_events must be a non-negative int")

        raw_kfs = data.get("keyframes")
        if not isinstance(raw_kfs, Sequence) or isinstance(raw_kfs, (str, bytes)):
            raise TypeError("keyframes must be a sequence")
        keyframes: list[RouteKeyframe] = []
        for i, item in enumerate(raw_kfs):
            kf = RouteKeyframe.from_mapping(item)
            if kf.frame != Frame.MAP.value:
                raise ValueError(
                    f"keyframe {i} claims frame {kf.frame!r}; place graph keyframes are "
                    f"{Frame.MAP.value!r} snapshots"
                )
            keyframes.append(kf)

        raw_edges = data.get("edges")
        if not isinstance(raw_edges, Sequence) or isinstance(raw_edges, (str, bytes)):
            raise TypeError("edges must be a sequence")
        edges: list[PlaceEdge] = []
        edge_at: dict[tuple[int, int], int] = {}
        for i, item in enumerate(raw_edges):
            edge = PlaceEdge.from_mapping(item)
            if edge.b >= len(keyframes):
                raise ValueError(
                    f"edge {i} references keyframe {edge.b} but only "
                    f"{len(keyframes)} keyframe(s) were read"
                )
            if edge.key in edge_at:
                raise ValueError(f"duplicate edge {edge.key} at index {i}")
            edge_at[edge.key] = len(edges)
            edges.append(edge)
        return (spacing, max_step, attach, keyframes, edges, edge_at, int(raw_events))


__all__ = [
    "DEFAULT_ATTACH_RADIUS_M",
    "DEFAULT_KEYFRAME_SPACING_M",
    "DEFAULT_MAX_CONTIGUOUS_STEP_M",
    "DOES_NOT_PROVE",
    "GRID_GOAL_TOLERANCE_M",
    "GRID_RESOLUTION_M",
    "GRID_SIZE_CELLS",
    "KEYFRAME_SPACING_CELLS",
    "MAX_CONTIGUOUS_STEP_SPACINGS",
    "MAX_LABELS_PER_KEYFRAME",
    "NAV_CONTROL_DT_S",
    "PLACE_GRAPH_SCHEMA",
    "PLATFORM_MAX_VX_MPS",
    "STUB_EMBED_DIM",
    "PlaceEdge",
    "RoutePlaceGraph",
    "stub_embed_image",
]
