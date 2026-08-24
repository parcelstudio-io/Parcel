"""RM-3 taught-prior-route cells — the substrate route memory can actually flip.

Card ``scrum/20260811/task_2/SLAM_M_PLAN.md`` (r2), Wave 3, RM-3.

Why a new cell set exists at all
--------------------------------
The card's r2 correction says it in one sentence: *"RM-3's original McNemar
substrate (v4s LA/BB) is structurally unreachable under the memory-honesty
rule"*. v4s LA/BB are STRAIGHT corridors, so an episode's own traversal never
covers a route the planner cannot already see, and route memory can only ever
route over ground the robot **actually drove**. Pre-registering a gate on them
would be the Y-3 mistake — a gate the mechanism cannot flip — so the plan
re-registers on new **taught-prior-route** cells, which is this module.

The memory-honesty rule, and where each clause is enforced
---------------------------------------------------------
``AUDIT_WAVE2_FABLE.md`` ("Cross-lane intel binding on Wave 3") states it as
four clauses. Every one of them is a generation-time admission test here, so a
cell that cannot satisfy it never enters the set:

1. **recorded edges must cover start → goal** — the taught route is computed by
   :func:`_taught_route_points` from the start INTO the scored ``GoalRegion``
   and is DRIVEN, out and back, before the measured mission
   (:class:`TaughtRoutePreDrive`), so the graph's edges are exactly that
   traversal. Nothing is fabricated: RM-1's ``waypoints_toward`` refuses to
   invent an edge, and this module never touches the graph — it drives the robot
   and lets ``pipeline._route_memory_teach`` record what happened.
2. **both attach ends within 8.05 m of recorded keyframes** — the start end is
   the first recorded keyframe (0.00 m away, the robot is standing on it), and
   the goal end is admitted by :data:`ROUTE_MEMORY_REACH_M` against the LAST
   taught point, which lies inside the scored region. Asserted per cell at
   generation time (:func:`_attach_evidence`).
3. **goal beyond planner reach** — and measured in its STRICTEST honest form:
   the distance from the start to the NEAREST point of the scored region (its
   centre minus the region's own outer band) must exceed
   :data:`ROUTE_MEMORY_REACH_M` (8.05 m = half the rolling window). The
   pipeline's own predicate ``_route_memory_goal_is_at_range`` measures to the
   committed approach pose, which the grounder places somewhere inside that
   region, so the nearest-point form is a lower bound on the number the
   mechanism will actually read — the direction that cannot flatter the cell.
4. **sighted-or-known**, and these cells take the **KNOWN** half — measured, not
   assumed. The target sits OUTSIDE the frustum's range from the start
   (``range_m > VISIBILITY_MAX_RANGE_M``), so it cannot be sighted on tick 0;
   what commits it is the robot's own semantic memory of having DRIVEN past it
   during the taught leg. ``DirectiveNavigator.memory`` is built once per
   navigator and is not reset by ``start()``, so a mission boundary keeps it —
   the same session property that keeps the place graph. Every episode records
   the tick-0 ``resolution_state`` and the committed goal's distance, so
   "known" is a per-row measurement rather than a claim.

   **Why the first draft's SIGHTED form was abandoned, measured.** With the
   target inside the 12 m frustum, the committed approach pose sits at most
   ``12.0 − band_outer ≈ 9.5 m`` away, i.e. barely 1.5 m beyond the 8.05 m
   reach. The pilot measured the consequence: the robot closes that 1.5 m in
   well under the 60-tick non-progress hysteresis either trigger needs, the goal
   comes INTO range, ``_route_memory_goal_is_at_range`` correctly says "not
   memory's problem", and route memory is **never consulted in the measured
   mission at all** (0 queries on 3 of 4 pilot cells; the 4th's single query was
   the taught leg's). A gate pre-registered on that substrate would have been
   exactly the Y-3 mistake the card forbids. The pilot is recorded as such in
   RM3_STATUS.md; the substrate was changed before any pre-registration was
   frozen, and no gate has ever been registered on the sighted form.

And one more, which is this set's whole reason for existing and the deliberate
complement of DR-2's ``v4d`` rule 2: **the straight corridor from the start to
the target is BLOCKED**. ``RollingGridPlanner`` clips a beyond-window goal to
the window edge along that straight line, so a blocked corridor is precisely the
case where the clipped target is aimed at an obstacle and the robot's local
window has nothing useful to say — while a route it once drove does.

Geometry comes from the WORLD, not from the disc model
------------------------------------------------------
Every geometric admission test here is answered by
``HeadlessCityWorld.truth_minimum_clearance`` — the same function the simulator
itself integrates motion against — rather than by the landmark-disc
approximation the v1-v4s generators use. That is DR-2's handoff 2 acted on
rather than inherited:

> ``_v4s_point_is_free`` / ``_v4s_segment_blockers`` model buildings as **discs**
> while MuJoCo has boxes, so an admitted start can sit far tighter than the rule
> believes: measured true clearances of **0.06 m, 0.82 m, 0.98 m** at admitted
> starts. […] It is the single largest driver of the substrate's low SR.

It is not optional here, and the first draft measured why: the disc model
admitted a start at ``(3.5, 2.5)`` whose TRUE clearance is **0.157 m**, where
the reactive gate stops the body outright — the taught leg spent 1257 ticks
without moving 3.5 m and the "taught route" was a fiction. A cell whose taught
route cannot be driven is a cell that violates honesty clause 1, so occupancy
had to come from the authority. DR-2 could not make this change (a floor derived
from the current ``v4d`` set is pinned against it); ``v4r`` is new, pins
nothing, and therefore can.

Three thresholds follow, all derived from the reactive-safety authority and
none of them tuned:

* :data:`OBSTACLE_STOP_FLOOR_M` — the clearance at which the obstacle branch of
  ``apply_reactive_safety`` stops the body, read live off
  ``DEFAULT_SAFETY_ENVELOPE``. ``truth_minimum_clearance`` is already
  footprint-relative (it subtracts ``robot_radius_m``), so it is directly
  comparable — verified: ``SimObservation.nearest_obstacle_m`` and
  ``truth_minimum_clearance`` return the same number for the same pose.
* :data:`TEACH_WAYPOINT_TOLERANCE_M` — the follower's own tracking tolerance,
  hence the largest lateral deviation the taught leg can have from its polyline.
* :data:`TEACH_MIN_CLEARANCE_M` = their sum: the clearance a taught route must
  keep so that the gate's STOP branch provably cannot bind anywhere the follower
  can be. Stated precisely, because the weaker claim is the true one: the
  comfort band (``ReactiveSafetyPolicy.obstacle_slow_m``, 1.2 m) is WIDER than
  this, so a taught route may still be SLOWED by the gate — the taught leg's
  tick budget absorbs that (§ :data:`TEACH_TRAVEL_SLACK`), and the measured
  outcome is that every admitted cell's taught leg completes with zero
  collisions. What the threshold buys is that the leg can never be stopped
  outright, which is the failure that makes a taught route a fiction.

The owner keep-out ring stays a disc, and deliberately: the owner is a PERSON,
handled by a different branch of the same gate (card D-15's lane), and no
static-occupancy query knows about them.

What this module is NOT
-----------------------
It is not a scenario generator for capability claims, and it is candidate-only:
``v4r`` is deliberately **not** a member of ``generator.EPISODE_SETS``, so
``--freeze`` and the frozen-baseline ledger flag cannot reach it (DR-2's ``v4d``
set the precedent and the reason).

Determinism
-----------
Generation is a pure function of the scene (its artifact and its MuJoCo
occupancy) and ``(seed, per_target, limit)``: admission and ordering are total,
there is no sampling, and the seed only salts episode ids.
"""

from __future__ import annotations

import hashlib
import heapq
import math
from dataclasses import dataclass
from itertools import pairwise
from typing import Any

from evals.nav_instruct.drift_cells import _removed_entity_ids
from evals.nav_instruct.generator import (
    DEFAULT_OWNER_XY,
    EPISODE_SET_V4S,
    OWNER_CORRIDOR_KEEPOUT_M,
    V4S_CLEARANCE_MARGIN_M,
    V4S_TARGETS,
    VISIBILITY_MAX_RANGE_M,
    EpisodeSpec,
    GoalRegion,
    V4sTarget,
    _v4s_blocking_discs,
    _v4s_goal_for,
    _v4s_segment_blockers,
    _v4s_start_lattice,
    _v4s_synonym,
    episode_set_spec,
    landmarks_for,
)
from evals.nav_instruct.runner import route_memory_record
from parcel_robot.models import VelocityCommand
from parcel_robot.navigation.goals import navigation_directive_from_text
from parcel_robot.navigation.reactive_safety import (
    DEFAULT_SAFETY_ENVELOPE,
    apply_reactive_safety,
)
from parcel_robot.route_memory.place_graph import (
    DEFAULT_ATTACH_RADIUS_M,
    DEFAULT_KEYFRAME_SPACING_M,
)
from parcel_robot.simulation.headless_city import HeadlessCityWorld, _nav_observation

#: The set's name. NOT a member of ``generator.EPISODE_SETS`` — additive,
#: candidate-only namespace (DR-2's ``v4d`` precedent and its stated reason).
ROUTE_MEMORY_SET_NAME = "v4r"

#: This set's own seed. A new set gets a new seed; nothing about it can reach
#: v1-v4s or v4d.
ROUTE_MEMORY_SEED = 20260812

#: NOTE (RM3_STATUS.md revision 2, audit correction 5a): the wording below was
#: corrected AFTER the gated sweep ran. Artifacts written on 2026-08-12 at
#: ``20260812T083551Z`` and ``20260812T084541Z`` carry the previous string, which
#: said the target is "sighted from the start" — Pilot A's rule, not the one that
#: shipped. It was a header string only: no admission test, cell or measured
#: number was affected, every persisted row already carried
#: ``visible_from_start: False``, and those artifacts were deliberately NOT
#: regenerated.
ROUTE_MEMORY_PROVENANCE = (
    "2026-08-12 ADDITIVE taught-prior-route substrate (card RM-3): every scene "
    "cell whose target lies OUTSIDE the frustum's range from the start (so it "
    "can only be KNOWN, from the taught leg, never sighted on tick 0), sits "
    "beyond the planner's 8.05 m half-window, and whose straight corridor is "
    "blocked by a scene obstacle that a driveable detour goes around. Each cell "
    "declares the route the robot DRIVES, out and back, before the measured "
    "mission, so the place graph's edges cover start -> goal by traversal and "
    "by nothing else. Occupancy is the world's own "
    "(HeadlessCityWorld.truth_minimum_clearance), not the landmark-disc model. "
    "Built from v4s's geometry primitives and the live K0 goal builders; adds "
    "no arrival rule, no new natural-language surface, and re-freezes nothing. "
    "CANDIDATE-ONLY -- never a frozen baseline"
)

#: Half the rolling planner window, consumed BY REFERENCE from RM-1's own
#: constant — the same number ``pipeline.DirectiveNavigator.ROUTE_MEMORY_RANGE_M``
#: is defined as (``ROUTE_MEMORY_ATTACH_RADIUS_M``), so "beyond planner reach"
#: here means exactly what the mechanism means by it. Mirroring it as a literal
#: would let a planner retune silently invalidate every cell in the set.
ROUTE_MEMORY_REACH_M = DEFAULT_ATTACH_RADIUS_M

#: How much longer than the straight line a cell's driveable route must be
#: before the cell counts as a genuine DETOUR.
#:
#: Derived, not chosen: ``DEFAULT_KEYFRAME_SPACING_M`` (0.50 m) is the finest
#: distinction the place graph can record at all — two poses closer than one
#: spacing are the same recorded place — and the taught route is sampled on the
#: same 0.5 m grid the routability search runs on. So one keyframe spacing is
#: the smallest detour that is even REPRESENTABLE as "the recorded way round is
#: not the straight way", and anything smaller would be a rounding artefact of
#: the grid rather than a property of the scene. Deliberately a floor on the
#: ABSOLUTE excess, not a ratio: a ratio bar would admit or reject cells by how
#: long they are, which is not what is being claimed.
ROUTE_MEMORY_MIN_DETOUR_M = DEFAULT_KEYFRAME_SPACING_M

#: Grid resolution for the taught-route search. Same 0.5 m
#: :func:`generator._v4s_route_length_m` asserts routability on, and the same
#: bounds, so the two answers ("a route exists" / "here is the route") are
#: measured on one lattice.
TAUGHT_ROUTE_RESOLUTION_M = 0.5
TAUGHT_ROUTE_BOUNDS = (-10.0, -10.0, 10.0, 10.0)

#: Clearance at which the obstacle branch of ``apply_reactive_safety`` stops the
#: body, read live off the shipping envelope. ``truth_minimum_clearance`` already
#: subtracts the robot's footprint radius, so the two are directly comparable —
#: and verified so: for the same pose it returns exactly
#: ``SimObservation.nearest_obstacle_m``, which is the number the gate reads.
OBSTACLE_STOP_FLOOR_M = DEFAULT_SAFETY_ENVELOPE.obstacle_stop_floor_m

#: How close the taught-leg follower must come to a vertex before it advances to
#: the next one, i.e. the largest lateral deviation the driven path can have
#: from the polyline it was handed. Half a keyframe spacing — RM-2's own
#: ``DEFAULT_WAYPOINT_REACHED_M`` derivation, consumed here for the same reason
#: it holds there: RM-1 admits keyframes at least one spacing apart precisely so
#: their arrival discs do not overlap, so half a spacing is the largest radius
#: for which "the robot is AT this point" is unambiguous.
TEACH_WAYPOINT_TOLERANCE_M = DEFAULT_KEYFRAME_SPACING_M / 2.0

#: The clearance a taught route must keep everywhere. Stop floor plus tracking
#: tolerance: outside it the obstacle gate provably cannot bind anywhere the
#: follower can be, so a taught leg that fails to drive is a defect rather than
#: an expected outcome. Not tuned to any measured result — both terms are read
#: from their own authorities.
TEACH_MIN_CLEARANCE_M = OBSTACLE_STOP_FLOOR_M + TEACH_WAYPOINT_TOLERANCE_M

#: Sample spacing for the "is this straight corridor blocked" and "is this
#: taught route driveable" line queries. Half the lattice resolution, so no
#: obstacle narrower than one lattice cell can slip between two samples.
CLEARANCE_SAMPLE_M = TAUGHT_ROUTE_RESOLUTION_M / 2.0

#: Targets: reused verbatim from v4s, so this set adds ZERO new
#: natural-language surface and ZERO new arrival semantics.
ROUTE_MEMORY_TARGETS: tuple[V4sTarget, ...] = V4S_TARGETS

#: The pre-registered size of the GATED substrate: the first ``n`` cells of the
#: deterministic round-robin order. ``>= 60`` is the card's floor; 60 exactly is
#: what the paired sweep runs, and the order is fixed by the admission rule
#: (longest detour first within each target, round-robin across targets) rather
#: than by anything measured.
ROUTE_MEMORY_N_CELLS = 60


# ---------------------------------------------------------------------------
# Occupancy — the world's own, not the disc model's
# ---------------------------------------------------------------------------


class TruthOccupancy:
    """``HeadlessCityWorld``'s own clearance field, cached on a 0.5 m lattice.

    One world construction and ~1600 ``truth_minimum_clearance`` evaluations
    (measured: 0.4 s), after which every admission query is a table lookup. The
    world is reset to a far corner first so the ROBOT's own body cannot appear
    in its own clearance field.

    The owner is layered on top as a disc, because they are a person: no static
    occupancy query knows about them, and the branch of the gate that handles
    them is a different one.
    """

    def __init__(self, world: HeadlessCityWorld | None = None) -> None:
        self.world = world if world is not None else HeadlessCityWorld()
        min_x, min_y, max_x, max_y = TAUGHT_ROUTE_BOUNDS
        self.res = TAUGHT_ROUTE_RESOLUTION_M
        self.min_x, self.min_y = min_x, min_y
        self.width = math.ceil((max_x - min_x) / self.res)
        self.height = math.ceil((max_y - min_y) / self.res)
        self._grid = [
            [
                self.world.truth_minimum_clearance(*self.centre((i, j)))
                for j in range(self.height)
            ]
            for i in range(self.width)
        ]

    def centre(self, cell: tuple[int, int]) -> tuple[float, float]:
        return (
            self.min_x + (cell[0] + 0.5) * self.res,
            self.min_y + (cell[1] + 0.5) * self.res,
        )

    def cell_of(self, point: tuple[float, float]) -> tuple[int, int]:
        return (
            math.floor((point[0] - self.min_x) / self.res),
            math.floor((point[1] - self.min_y) / self.res),
        )

    def clearance(self, x: float, y: float) -> float:
        """Footprint-relative clearance at an arbitrary point (not cached)."""

        return float(self.world.truth_minimum_clearance(float(x), float(y)))

    def segment_min_clearance(
        self, a: tuple[float, float], b: tuple[float, float]
    ) -> float:
        distance = math.hypot(b[0] - a[0], b[1] - a[1])
        steps = max(1, math.ceil(distance / CLEARANCE_SAMPLE_M))
        return min(
            self.clearance(
                a[0] + (b[0] - a[0]) * index / steps,
                a[1] + (b[1] - a[1]) * index / steps,
            )
            for index in range(steps + 1)
        )

    def polyline_min_clearance(
        self, points: tuple[tuple[float, float], ...]
    ) -> float:
        return min(
            self.segment_min_clearance(a, b) for a, b in pairwise(points)
        )

    def free_cell(self, cell: tuple[int, int]) -> bool:
        if not (0 <= cell[0] < self.width and 0 <= cell[1] < self.height):
            return False
        if self._grid[cell[0]][cell[1]] <= TEACH_MIN_CLEARANCE_M:
            return False
        point = self.centre(cell)
        # The owner ring: a person, layered on as a disc at the same clearance
        # margin the v4s corridor rule uses for them.
        return (
            math.hypot(point[0] - DEFAULT_OWNER_XY[0], point[1] - DEFAULT_OWNER_XY[1])
            > OWNER_CORRIDOR_KEEPOUT_M + V4S_CLEARANCE_MARGIN_M
        )


_OCCUPANCY: TruthOccupancy | None = None


def truth_occupancy() -> TruthOccupancy:
    """The process-wide cached occupancy field (built on first use)."""

    global _OCCUPANCY
    if _OCCUPANCY is None:
        _OCCUPANCY = TruthOccupancy()
    return _OCCUPANCY


# ---------------------------------------------------------------------------
# Cell generation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RouteMemoryCell:
    """One admissible (target, start) pair, with the evidence for its claims."""

    target: V4sTarget
    start_xy: tuple[float, float]
    yaw_rad: float
    #: Start -> landmark position (the sighting distance).
    range_m: float
    #: Start -> the scored region's centre.
    goal_distance_m: float
    #: Start -> the NEAREST point of the scored region (the "beyond planner
    #: reach" distance, in its strictest honest form).
    goal_edge_distance_m: float
    #: Which discs the straight corridor crosses.
    corridor_blockers: tuple[str, ...]
    #: The driveable detour, start -> inside the scored region.
    taught_route: tuple[tuple[float, float], ...]
    taught_route_m: float
    #: ``taught_route_m`` minus the straight line to the last taught point.
    detour_excess_m: float
    #: Distance from the LAST taught point to the scored region's centre — the
    #: goal-side attach evidence.
    goal_attach_m: float
    #: World-truth clearances: at the start pose, the minimum along the BLOCKED
    #: straight corridor (which is why the cell exists), and the minimum along
    #: the taught route (which is why it can be driven).
    start_clearance_m: float
    corridor_min_clearance_m: float
    route_min_clearance_m: float


def _taught_route_points(
    start: tuple[float, float],
    goal: GoalRegion,
    occupancy: TruthOccupancy,
) -> tuple[tuple[float, float], ...] | None:
    """The polyline the robot will DRIVE, start -> inside the scored region.

    An 8-connected Dijkstra on the same 0.5 m lattice and bounds
    :func:`generator._v4s_route_length_m` proves routability on, with the one
    difference the module docstring argues for: a cell is free iff the WORLD's
    own clearance there exceeds :data:`TEACH_MIN_CLEARANCE_M`. The v4s
    routability search is an existence proof about a route under a disc
    approximation; this is a path a physical robot is asked to walk, so its
    freespace has to be the simulator's.

    Returns ``None`` when no such path exists (fail closed — the cell is then
    simply not admitted).
    """

    free = occupancy.free_cell
    start_cell = occupancy.cell_of(start)
    if not free(start_cell):
        return None
    parents: dict[tuple[int, int], tuple[int, int] | None] = {start_cell: None}
    best: dict[tuple[int, int], float] = {start_cell: 0.0}
    open_heap: list[tuple[float, tuple[int, int]]] = [(0.0, start_cell)]
    goal_cell: tuple[int, int] | None = None
    while open_heap:
        cost, current = heapq.heappop(open_heap)
        if cost > best.get(current, math.inf) + 1e-12:
            continue
        point = occupancy.centre(current)
        if current != start_cell and goal.contains(
            point[0], point[1], anchor_xy=goal.center
        ):
            goal_cell = current
            break
        for dx, dy in (
            (1, 0),
            (-1, 0),
            (0, 1),
            (0, -1),
            (1, 1),
            (1, -1),
            (-1, 1),
            (-1, -1),
        ):
            nxt = (current[0] + dx, current[1] + dy)
            if not free(nxt):
                continue
            # A diagonal may not cut a corner past a blocked orthogonal
            # neighbour: the robot would clip the obstacle the lattice says
            # it avoided.
            if dx and dy and (
                not free((current[0] + dx, current[1]))
                or not free((current[0], current[1] + dy))
            ):
                continue
            step = TAUGHT_ROUTE_RESOLUTION_M * math.hypot(dx, dy)
            tentative = cost + step
            if tentative + 1e-12 < best.get(nxt, math.inf):
                best[nxt] = tentative
                parents[nxt] = current
                heapq.heappush(open_heap, (tentative, nxt))
    if goal_cell is None:
        return None
    centre = occupancy.centre
    cells: list[tuple[int, int]] = []
    cursor: tuple[int, int] | None = goal_cell
    while cursor is not None:
        cells.append(cursor)
        cursor = parents[cursor]
    cells.reverse()
    points = [start] + [centre(cell) for cell in cells[1:]]
    return _compress_collinear(points)


def _compress_collinear(
    points: list[tuple[float, float]], *, tolerance_rad: float = 1e-6
) -> tuple[tuple[float, float], ...]:
    """Drop interior points that lie on the segment their neighbours span."""

    if len(points) <= 2:
        return tuple(points)
    out = [points[0]]
    for previous, current, following in zip(
        points, points[1:], points[2:], strict=False
    ):
        a = math.atan2(current[1] - previous[1], current[0] - previous[0])
        b = math.atan2(following[1] - current[1], following[0] - current[0])
        if abs(_wrap(b - a)) > tolerance_rad:
            out.append(current)
    out.append(points[-1])
    return tuple(out)


def _wrap(angle: float) -> float:
    return (angle + math.pi) % (2.0 * math.pi) - math.pi


def _polyline_length(points: tuple[tuple[float, float], ...]) -> float:
    return sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in pairwise(points))


def _attach_evidence(
    route: tuple[tuple[float, float], ...], goal: GoalRegion
) -> tuple[float, float]:
    """``(start-side attach m, goal-side attach m)`` for the honesty rule.

    The start side is 0.0 by construction — ``route[0]`` IS the start pose, and
    the first tick of the pre-drive records it — and is returned anyway so the
    claim is a measured number on the row rather than an argument in a docstring.
    """

    end = route[-1]
    return (
        math.hypot(route[0][0] - route[0][0], route[0][1] - route[0][1]),
        math.hypot(end[0] - goal.center[0], end[1] - goal.center[1]),
    )


def _region_outer_m(goal: GoalRegion) -> float:
    """The scored region's own outer extent from its centre, in metres.

    Read off the region the K0 builders produced, never hard-coded: a
    ``relative_band`` reaches ``band_m[1]``, a disc reaches ``radius_m``, and a
    region with neither contributes 0.0 (its centre IS its extent, which is the
    conservative reading).
    """

    band = getattr(goal, "band_m", None)
    if band:
        return float(band[1])
    radius = getattr(goal, "radius_m", None)
    return float(radius) if radius else 0.0


def _admissible_cells(
    target: V4sTarget,
    *,
    starts: tuple[tuple[float, float], ...],
    discs: tuple[tuple[str, float, float, float], ...],
    landmarks: dict[str, dict[str, Any]],
    occupancy: TruthOccupancy,
) -> list[RouteMemoryCell]:
    """Every start this target admits, LONGEST DETOUR FIRST.

    The ordering is a difficulty rule fixed at generation time and applied
    uniformly to every target: a longer detour is more route the local window
    cannot see, which is the quantity this set exists to stress. It was chosen
    before any arm was run and must never be re-ordered against a result.
    """

    goal, _radius_m, _label = _v4s_goal_for(target, landmarks)
    landmark = landmarks[target.entity_id]
    position = (float(landmark["position"][0]), float(landmark["position"][1]))
    admitted: list[RouteMemoryCell] = []
    for start in starts:
        range_m = math.hypot(position[0] - start[0], position[1] - start[1])
        # Clause 4 — KNOWN, not sighted: strictly OUTSIDE the frustum's range,
        # so tick 0 cannot see it and a committed goal can only have come from
        # the memory the taught leg built. No new constant: the bar is the
        # generator's own frustum range, used as its own complement.
        if range_m <= VISIBILITY_MAX_RANGE_M:
            continue
        # The start heading faces the target. It cannot make the target visible
        # (it is out of range), and it keeps the opening tick from being an
        # adversarial heading that measures the aligner instead of the route.
        yaw = math.atan2(position[1] - start[1], position[0] - start[0])
        # Clause 3 — BEYOND PLANNER REACH, to the NEAREST point of the scored
        # region (see the module docstring: a lower bound on what the mechanism
        # will read, never an upper one).
        goal_distance = math.hypot(goal.center[0] - start[0], goal.center[1] - start[1])
        goal_edge_distance = goal_distance - _region_outer_m(goal)
        if goal_edge_distance <= ROUTE_MEMORY_REACH_M:
            continue
        # The start must itself be driveable, on the WORLD's occupancy. DR-2's
        # handoff 2 in one line: the disc model admitted a start with 0.157 m of
        # true clearance, where the gate stops the body before it moves.
        start_clearance = occupancy.clearance(*start)
        if start_clearance <= TEACH_MIN_CLEARANCE_M:
            continue
        # This set's own rule — the straight corridor is BLOCKED, asserted
        # against the world's own occupancy: somewhere on the straight line to
        # the target the clearance drops to or below the gate's stop floor, so
        # the corridor cannot be driven. The disc lookup that follows only
        # ATTRIBUTES the blocker for the row; it is not the test.
        corridor_clearance = occupancy.segment_min_clearance(start, position)
        if corridor_clearance > OBSTACLE_STOP_FLOOR_M:
            continue
        blockers = _v4s_segment_blockers(start, position, discs)
        # Clause 1 — a driveable route that COVERS start -> goal, and a real
        # detour rather than a grid rounding artefact.
        route = _taught_route_points(start, goal, occupancy)
        if route is None or len(route) < 2:
            continue
        route_m = _polyline_length(route)
        straight_m = math.hypot(route[-1][0] - start[0], route[-1][1] - start[1])
        detour_excess = route_m - straight_m
        if detour_excess < ROUTE_MEMORY_MIN_DETOUR_M:
            continue
        # The lattice guarantees clearance at cell CENTRES; the driven polyline
        # is continuous, so it is re-checked as a line. A cell whose taught route
        # cannot be driven is not admitted, ever.
        route_clearance = occupancy.polyline_min_clearance(route)
        if route_clearance <= OBSTACLE_STOP_FLOOR_M:
            continue
        # Clause 2 — both attach ends inside RM-1's attach radius.
        start_attach, goal_attach = _attach_evidence(route, goal)
        if start_attach > ROUTE_MEMORY_REACH_M or goal_attach > ROUTE_MEMORY_REACH_M:
            continue
        admitted.append(
            RouteMemoryCell(
                target=target,
                start_xy=start,
                yaw_rad=yaw,
                range_m=range_m,
                goal_distance_m=goal_distance,
                goal_edge_distance_m=goal_edge_distance,
                corridor_blockers=tuple(blockers),
                taught_route=route,
                taught_route_m=route_m,
                detour_excess_m=detour_excess,
                goal_attach_m=goal_attach,
                start_clearance_m=start_clearance,
                corridor_min_clearance_m=corridor_clearance,
                route_min_clearance_m=route_clearance,
            )
        )
    admitted.sort(key=lambda cell: (-cell.detour_excess_m, cell.start_xy))
    return admitted


def _episode_id(cell: RouteMemoryCell, index: int, seed: int) -> str:
    digest = hashlib.sha256(
        f"{ROUTE_MEMORY_SET_NAME}|{seed}|{cell.target.entity_id}|"
        f"{cell.start_xy[0]:.6f}|{cell.start_xy[1]:.6f}".encode()
    ).hexdigest()[:8]
    return f"nav-rmem-{cell.target.family}-{index:02d}-{digest}"


def _build_episode(
    cell: RouteMemoryCell,
    *,
    index: int,
    seed: int,
    landmarks: dict[str, dict[str, Any]],
) -> EpisodeSpec:
    goal, _radius_m, _label = _v4s_goal_for(cell.target, landmarks)
    start_pose = (float(cell.start_xy[0]), float(cell.start_xy[1]), float(cell.yaw_rad))
    placement: dict[str, Any] = {
        # The measured evidence for every claim this cell makes about itself,
        # carried on the episode so a persisted row is self-describing.
        "route_memory_cell": {
            "set": ROUTE_MEMORY_SET_NAME,
            "target_entity_id": cell.target.entity_id,
            "range_m": round(cell.range_m, 6),
            "goal_distance_m": round(cell.goal_distance_m, 6),
            "goal_edge_distance_m": round(cell.goal_edge_distance_m, 6),
            "reach_m": ROUTE_MEMORY_REACH_M,
            "visibility_max_range_m": VISIBILITY_MAX_RANGE_M,
            "visible_from_start": False,
            "corridor_blockers": list(cell.corridor_blockers),
            "taught_route": [[round(x, 6), round(y, 6)] for x, y in cell.taught_route],
            "taught_route_m": round(cell.taught_route_m, 6),
            "detour_excess_m": round(cell.detour_excess_m, 6),
            "start_attach_m": 0.0,
            "goal_attach_m": round(cell.goal_attach_m, 6),
            "start_clearance_m": round(cell.start_clearance_m, 6),
            "corridor_min_clearance_m": round(cell.corridor_min_clearance_m, 6),
            "route_min_clearance_m": round(cell.route_min_clearance_m, 6),
            "obstacle_stop_floor_m": OBSTACLE_STOP_FLOOR_M,
            "teach_min_clearance_m": TEACH_MIN_CLEARANCE_M,
        },
    }
    # Referent uniqueness in perception, on DR-2's measured rule and reading
    # DR-2's function rather than re-transcribing it: under the default matcher
    # arm the grounder admits cross-class commits, which manufactures
    # ``false_arrival`` verdicts that have nothing to do with route memory.
    removed = _removed_entity_ids(cell.target.entity_id)
    if removed:
        placement["remove_entities"] = list(removed)
        placement["route_memory_cell"]["removed_entities"] = list(removed)
    return EpisodeSpec(
        episode_id=_episode_id(cell, index, seed),
        family=cell.target.family,
        # Not a v1-v4 difficulty tier: these cells are not a family x tier
        # matrix. "R" names the set, and no frozen tier statistic can absorb it.
        tier="R",
        instruction=cell.target.instruction,
        seed=seed,
        start_pose=start_pose,
        goal=goal,
        target_entity_id=cell.target.entity_id,
        shortest_path_m=float(cell.taught_route_m),
        distractors=(),
        placement_overrides=placement,
        synonym=_v4s_synonym(cell.target.instruction),
        absent_target=False,
        notes=(
            f"route_memory_taught|{cell.target.family}|"
            f"detour={cell.detour_excess_m:.2f}m|route={cell.taught_route_m:.2f}m"
        ),
    )


def generate_route_memory_cells(
    *,
    seed: int = ROUTE_MEMORY_SEED,
    per_target: int | None = None,
    limit: int | None = ROUTE_MEMORY_N_CELLS,
    landmarks: dict[str, dict[str, Any]] | None = None,
    occupancy: TruthOccupancy | None = None,
) -> tuple[EpisodeSpec, ...]:
    """The RM-3 taught-prior-route substrate.

    Round-robin across targets (never target-major), so a prefix spreads over
    every target instead of exhausting one. ``per_target`` caps each target's
    contribution and RAISES rather than silently shrinking when a target cannot
    fill it, so a small set can never be mistaken for the full one.

    ``limit`` is the **pre-registered n** (:data:`ROUTE_MEMORY_N_CELLS`): the
    first ``n`` of that round-robin order, which is fixed by the admission rule
    and by nothing measured. ``None`` returns every admitted cell — the honest
    denominator, reported alongside n in the status doc — and a ``limit`` larger
    than the rule admits RAISES rather than silently shrinking the sweep.
    """

    if per_target is not None and per_target < 1:
        raise ValueError("per_target must be >= 1 or None")
    if limit is not None and limit < 1:
        raise ValueError("limit must be >= 1 or None")
    spec = episode_set_spec(EPISODE_SET_V4S)
    if landmarks is None:
        landmarks = landmarks_for(spec)
    if occupancy is None:
        occupancy = truth_occupancy()
    discs = _v4s_blocking_discs(landmarks)
    starts = _v4s_start_lattice(discs)
    per_target_cells: list[list[RouteMemoryCell]] = []
    for target in ROUTE_MEMORY_TARGETS:
        admitted = _admissible_cells(
            target,
            starts=starts,
            discs=discs,
            landmarks=landmarks,
            occupancy=occupancy,
        )
        if not admitted:
            continue
        if per_target is not None:
            if len(admitted) < per_target:
                raise ValueError(
                    f"route-memory target {target.entity_id!r} yields only "
                    f"{len(admitted)} cells, below the requested {per_target} — "
                    "STOP and report, never silently shrink"
                )
            admitted = admitted[:per_target]
        per_target_cells.append(admitted)

    episodes: list[EpisodeSpec] = []
    depth = max((len(items) for items in per_target_cells), default=0)
    index = 0
    for position in range(depth):
        for items in per_target_cells:
            if position < len(items):
                episodes.append(
                    _build_episode(
                        items[position], index=index, seed=seed, landmarks=landmarks
                    )
                )
                index += 1
    if not episodes:
        raise ValueError("route-memory cell generation produced no episodes")
    if limit is not None:
        if len(episodes) < limit:
            raise ValueError(
                f"route-memory generation admits only {len(episodes)} cells, "
                f"below the pre-registered n={limit} — STOP and report, never "
                "silently shrink a pre-registered substrate"
            )
        episodes = episodes[:limit]
    return tuple(episodes)


def taught_route_of(episode: EpisodeSpec) -> tuple[tuple[float, float], ...]:
    """The polyline this episode declares, or ``()`` for a non-``v4r`` episode."""

    payload = (episode.placement_overrides or {}).get("route_memory_cell")
    if not isinstance(payload, dict):
        return ()
    return tuple(
        (float(point[0]), float(point[1])) for point in payload.get("taught_route", ())
    )


def cells_digest(episodes: tuple[EpisodeSpec, ...]) -> str:
    """A stable digest of the generated set, for the report header."""

    payload = "|".join(
        f"{ep.episode_id}:{ep.start_pose[0]:.6f},{ep.start_pose[1]:.6f},"
        f"{ep.start_pose[2]:.6f}:{ep.target_entity_id}:{ep.shortest_path_m:.6f}"
        for ep in episodes
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# The taught leg — teaching by DRIVING, which is the only honest way
# ---------------------------------------------------------------------------

#: Cruise speed of the taught leg, m/s. Half the platform's ``max_vx``
#: (``configs/robot.yaml`` 1.0 m/s), consumed by reference below. A taught leg
#: is a demonstration, not a race: at half speed the pre-drive samples the route
#: at ~0.05 m per control tick, an order of magnitude finer than RM-1's 0.50 m
#: keyframe admission spacing, so the recorded graph is a property of the ROUTE
#: and not of how fast it happened to be walked. It cannot be tuned against any
#: measured result: the graph RM-1 admits is spacing-quantised, so halving or
#: doubling this changes tick count and nothing in the graph.
TEACH_CRUISE_FRACTION = 0.5

#: Heading error above which the follower turns in place instead of driving.
#: ``pi/6`` — the shipping approach-alignment convention; below it the forward
#: component of an 0.5 m/s cruise still points within 30 deg of the segment.
TEACH_ALIGN_TOLERANCE_RAD = math.pi / 6.0

#: Yaw rate of the taught leg, rad/s: half ``configs/robot.yaml``'s ``max_vyaw``
#: (1.5), on the same reasoning as the cruise fraction.
TEACH_YAW_FRACTION = 0.5

#: The sim control period the world advances at (``HeadlessCityWorld``'s
#: default), used only to turn the two speed budgets below into tick counts.
TEACH_CONTROL_DT_S = 0.1

#: The taught leg's tick budget, derived rather than picked, as
#: ``2 x (travel ticks) + (one full reversal per vertex)``:
#:
#: * travel — ``route_m / (cruise x dt)`` ticks, DOUBLED, which is the same
#:   factor-of-two allowance ``scaled_step_budget``'s planning speed makes for
#:   slowdowns and alignment;
#: * turns — the worst case is a full ``pi`` reversal at every vertex, i.e.
#:   ``pi / (yaw_rate x dt)`` ticks each. Bounding the worst case rather than
#:   the typical one is what makes an exhausted budget a DEFECT report rather
#:   than an expected outcome.
#:
#: A leg that exceeds it is recorded ``completed: False`` and never silently
#: accepted: a partial taught route is a graph that does not cover start -> goal,
#: and a cell whose taught route did not get driven has to be excluded from the
#: gated set rather than counted as an honest failure.
TEACH_TRAVEL_SLACK = 2.0


def teach_tick_budget(
    route: tuple[tuple[float, float], ...], cruise_mps: float, yaw_rate_rad_s: float
) -> int:
    """Ticks the taught leg is allowed. See :data:`TEACH_TRAVEL_SLACK`."""

    travel = _polyline_length(route) / max(cruise_mps * TEACH_CONTROL_DT_S, 1e-9)
    turns = len(route) * math.pi / max(yaw_rate_rad_s * TEACH_CONTROL_DT_S, 1e-9)
    return math.ceil(TEACH_TRAVEL_SLACK * travel + turns)


@dataclass
class TaughtRoutePreDrive:
    """The ``NavInstructRunner.pre_drive`` callable that teaches by driving.

    **What it does, mechanically.** It starts a mission on the episode's own
    directive, then drives the robot OUT along the episode's declared polyline
    and BACK again with a scripted follower, stepping the NAVIGATOR on every
    tick. The navigator's returned command is deliberately DISCARDED — this leg
    is a demonstration, and the pipeline is stepped only so that
    ``_route_memory_teach`` ingests the pose the robot actually reached and the
    grounder's own memory sees the target the robot drove past. Every recorded
    keyframe is therefore a place the robot really stood, and every recorded
    edge a metre it really walked, which is the only reading under which RM-1's
    "no invented edges" contract means anything.

    **Why OUT AND BACK, rather than out-then-teleport.** The measured mission
    has to begin at the episode's start pose. Driving back there is the honest
    way to arrange that: the taught leg and the measured mission are then ONE
    continuous session — a monotone sim clock, a single unbroken pose history,
    and a semantic memory whose observations are all in the past. Teleporting
    instead (``world.reset``) would rewind ``data.time`` to zero and leave the
    grounder recalling entities it observed in the future, which is not a thing
    a robot can do. It is also what RM-2's own corridor gate did (drive A→B→A,
    then task a goal near B).

    **Why the navigator's own command is not used.** Because the measured task
    is exactly "can normal planning get there", and letting normal planning
    drive the taught leg would either (a) succeed, in which case the cell is not
    a beyond-reach cell at all, or (b) fail, in which case there is no taught
    route. The card names this: "scripted pre-drive **or** a first directive
    leg", and on this substrate only the scripted form can produce the route.

    **What it leaves behind, and what it must not.** ``navigator.stop()`` in the
    ``finally`` is contract clause 3: the mission boundary breaks RM-1's ingest
    track, so no edge can be laid across the seam between the taught leg and the
    measured mission. Clause 2 (restore the start pose) is discharged BY DRIVING
    — the follower's last vertex is the start pose, reached to within
    :data:`TEACH_WAYPOINT_TOLERANCE_M` — and the residual gap is measured onto
    the row (``final_gap_m``) rather than assumed to be zero. The world's
    collision counter is deliberately NOT zeroed: the taught leg's motion really
    happened, so its collisions belong to the episode. On an admitted cell there
    are none (the route keeps :data:`TEACH_MIN_CLEARANCE_M` everywhere) and the
    row records the count either way.

    **Cost accounting.** Not one tick of this leg is charged to the measured
    task: the whole thing happens before ``navigator.start(directive)`` and
    before the budget loop exists. The taught leg's own tick count is reported
    on the row (``teach_ticks``) so it is visible rather than free, and so are
    the route-memory counters as they stood when it ended (``counters``), so
    every measured-mission number can be read as a DELTA rather than a total —
    the pipeline is live during the taught leg and does query memory there.
    """

    #: Hard ceiling on taught-leg ticks, whatever the derived budget says. Only a
    #: backstop against a follower that cannot make progress at all; the derived
    #: budget binds first on every admitted cell.
    max_ticks_cap: int = 8000

    def __call__(
        self, runner: Any, navigator: Any, episode: EpisodeSpec
    ) -> dict[str, Any]:
        route = taught_route_of(episode)
        # OUT and BACK: the reversed polyline minus its duplicated first point.
        drive = route + tuple(reversed(route))[1:]
        record: dict[str, Any] = {
            "waypoints": len(route),
            "drive_waypoints": len(drive),
            "route_m": round(_polyline_length(route), 6) if route else 0.0,
            "drive_m": round(_polyline_length(drive), 6) if route else 0.0,
            "teach_ticks": 0,
            "completed": False,
            "collisions": 0,
            "final_xy": None,
            "reason": "no_taught_route",
        }
        if len(route) < 2:
            return record
        world = runner.world
        harness = runner.harness
        directive = navigation_directive_from_text(episode.instruction)
        max_vx, max_vyaw = _platform_limits(harness)
        cruise = TEACH_CRUISE_FRACTION * max_vx
        yaw_rate = TEACH_YAW_FRACTION * max_vyaw
        budget = min(self.max_ticks_cap, teach_tick_budget(drive, cruise, yaw_rate))
        record["teach_budget"] = budget
        provider, _seed = runner._new_pose_provider()
        turned = False
        try:
            navigator.start(directive)
            index = 1
            ticks = 0
            for _ in range(budget):
                observation = world.observe()
                nav_observation = _nav_observation(
                    observation,
                    measured_velocity=world.command,
                    stop_confirmed=world.stopped,
                    settled_linear_speed_mps=harness._settled_linear_speed_mps,
                    settled_yaw_speed_rad_s=harness._settled_yaw_speed_rad_s,
                    pose_provider=provider,
                )
                # Ingestion only. The command is discarded on purpose (docstring).
                navigator.step(nav_observation)
                ticks += 1
                robot = observation.robot
                while index < len(drive) and math.hypot(
                    drive[index][0] - robot.x, drive[index][1] - robot.y
                ) <= TEACH_WAYPOINT_TOLERANCE_M:
                    index += 1
                    if index == len(route) and not turned:
                        # The far end: the taught route now covers start -> goal
                        # in the graph, and the return leg starts here.
                        turned = True
                        record["reached_goal_end_tick"] = ticks
                if index >= len(drive):
                    record["completed"] = True
                    record["reason"] = "route_complete"
                    break
                target = drive[index]
                bearing = math.atan2(target[1] - robot.y, target[0] - robot.x)
                error = _wrap(bearing - robot.yaw)
                if abs(error) > TEACH_ALIGN_TOLERANCE_RAD:
                    requested = VelocityCommand(
                        0.0, 0.0, math.copysign(yaw_rate, error)
                    )
                else:
                    requested = VelocityCommand(
                        cruise, 0.0, max(-yaw_rate, min(yaw_rate, 2.0 * error))
                    )
                velocity, _ = apply_reactive_safety(
                    requested,
                    observation,
                    policy=harness.reactive_safety,
                    owner_orbit=False,
                    orbit_radius_m=0.0,
                    now=observation.timestamp,
                    require_fresh_telemetry=False,
                )
                world.apply(velocity)
                world.step()
            else:
                record["reason"] = "teach_budget_exhausted"
            final = world.observe().robot
            record["teach_ticks"] = ticks
            record["reached_goal_end"] = bool(turned)
            record["collisions"] = int(world.collision_count)
            record["final_xy"] = [round(float(final.x), 6), round(float(final.y), 6)]
            record["final_gap_m"] = round(
                math.hypot(final.x - drive[-1][0], final.y - drive[-1][1]), 6
            )
        finally:
            # Contract clause 3. Clause 2 was discharged by driving back.
            navigator.stop()
            record["counters"] = route_memory_record(navigator)
        return record


def _platform_limits(harness: Any) -> tuple[float, float]:
    """``(max_vx, max_vyaw)`` from the reactive-safety authority the harness holds.

    Read off the live policy rather than re-parsed from yaml: the pre-drive is
    subject to ``apply_reactive_safety`` with exactly this policy, so its own
    speed ceiling has to be the same object's, not a transcription of it.
    """

    policy = harness.reactive_safety
    max_vx = float(getattr(policy, "max_vx_mps", 1.0) or 1.0)
    max_vyaw = float(getattr(policy, "max_vyaw_rad_s", 1.5) or 1.5)
    return max_vx, max_vyaw
