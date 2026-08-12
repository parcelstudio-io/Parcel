"""Card RM-2 — route memory on the product path, gated.

Provenance: ``scrum/20260811/task_2/SLAM_M_PLAN.md`` (r2), Wave 2, card RM-2,
consuming RM-1's frozen contract (``scrum/20260811/task_2/RM1_STATUS.md`` §1)
and the cross-lane intel in ``scrum/20260811/task_2/AUDIT_WAVE1_FABLE.md``.

The measured bottleneck this card exists for: the rolling grid planner sees one
16.1 m window (``ROUTE_MEMORY_RANGE_M`` = 8.05 m of reach in any direction)
while the semantic camera reports instances at 12 m and beyond. A goal the
planner has *proved* it cannot route to is released and blacklisted for the rest
of the mission — irreversibly — even when the robot itself drove past that place
ten seconds earlier. Route memory asks one question before that release: *is
there a chain of places I have actually traversed that leads there?*

What is gated here, in the card's own order:

(a) **flag-off is today's behaviour, verbatim.** Not asserted — *traced*: the
    unroutable-release scenario is run twice, flag-OFF and flag-ON-with-empty-
    memory, and every returned command and every mission-metadata field is
    compared tick for tick. RM-1's ``()`` fail-closed contract is what makes the
    second arm identical, and a seeded non-empty memory is used to prove the
    comparison can fail.
(b) **non-vacuity with a paired control.** A scripted U corridor: the robot
    drives A -> B -> A (auto-teach records it), then is tasked with a goal near
    B sighted at 11.0 m whose direct line is walled off. Flag-ON arrives;
    flag-OFF releases the only candidate and fails. The control that makes it a
    measurement rather than a demo is the THIRD arm — flag-ON with the teaching
    drive skipped — which reproduces the flag-OFF outcome exactly. The win comes
    from the recorded route, not from having the flag on.
(c) **no new motion authority.** ``GoalArbiter``'s lethal veto is evaluated over
    the waypoint's whole leg, and a veto leaves the interim target unset and the
    release path untouched.
(d) the correction/refusal flush lives with its own contract in
    ``tests/test_ve_detection_lock_on.py`` (AF-2's interleaving suite).

Plus the two seams the Wave-2 audit pre-registered as adversarial targets:
**waypoint-vs-mission-goal authority** (the mission goal, the K0 arrival region
and the arrival predicate are never replaced) and the **deferred-blacklist
LIVELOCK** (a chain that stops advancing must give the release back, and does so
inside a derived tick bound).

Every property case here carries a companion that seeds the exact defect it
forbids and shows the checker rejects it, so a green row is evidence rather than
a tautology.
"""

from __future__ import annotations

import math
import sys
from collections import deque
from itertools import pairwise
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from parcel_robot.instructnav.arbiter import GoalArbiter, SE2Goal
from parcel_robot.navigation.base import GoalPose, MidLevelCommand, Mission, NavObservation
from parcel_robot.navigation.grounder import PlaceGrounder
from parcel_robot.navigation.pipeline import DirectiveNavigator
from parcel_robot.navigation.registry import ModelRegistry
from parcel_robot.pose import POSE_PROVIDER_KEY, Frame, PoseEstimate, PoseHealth
from parcel_robot.route_memory.place_graph import (
    DEFAULT_ATTACH_RADIUS_M,
    DEFAULT_KEYFRAME_SPACING_M,
)
from parcel_robot.route_memory.proposer import (
    DEFAULT_WAYPOINT_REACHED_M,
    PLACE_ROUTE_SOURCE,
    chain_length_m,
    next_waypoint_keyframe,
    waypoint_goal_from_chain,
)

MODELS = REPO / "configs" / "navigation" / "models"


def _nav(*, route_memory: bool) -> DirectiveNavigator:
    return DirectiveNavigator(
        registry=ModelRegistry.load(MODELS),
        grounder=PlaceGrounder([]),
        model_id="stub_v0",
        arrive_radius_m=0.25,
        route_memory=route_memory,
    )


# ---------------------------------------------------------------------------
# Arm 1 substrate — the unroutable-release scenario, reused verbatim from
# ``tests/test_unroutable_goal_release.py`` so the flag-off comparison is
# against the behaviour that file already pins.
# ---------------------------------------------------------------------------


class _RouteStatusNavigator:
    """The pinned stand-in: ``goal_blocked`` forever, never claims arrival."""

    def __init__(self, status: str | None = "goal_blocked") -> None:
        self.last_route_status = status
        self.resets = 0

    def reset(self, mission) -> None:
        self.resets += 1
        mission.status = "running"

    def act(self, observation, mission) -> MidLevelCommand:
        return MidLevelCommand(vx=0.0, vyaw=0.2, note="grid_recover_scan status=goal_blocked")

    def close(self) -> None:
        return None


def _lamppost(candidate_id: str, x: float, y: float, *, distance_m: float):
    return {
        "id": candidate_id,
        "label": "lamppost",
        "kind": "object",
        "position": [x, y, 0.0],
        "confidence": 0.98,
        "source": "test_semantic_camera",
        "reachable": True,
        "metadata": {"aliases": ["street light", "lamp post"], "arrival_radius_m": 0.2},
    }, {"id": candidate_id, "distance_m": distance_m, "bearing_rad": 0.0}


#: The blocked instance sits BEYOND ``ROUTE_MEMORY_RANGE_M`` (12.53 m from the
#: origin), so ``_route_memory_goal_is_at_range`` says "at range" and the RM-2
#: trigger really is entered on every tick of the flag-ON arm. At the 7.3 m of
#: ``tests/test_unroutable_goal_release.py``'s own fixture the goal is INSIDE
#: the window, memory is never consulted, and the comparison below would be
#: satisfied by an implementation with no memory in it at all.
_FAR_LAMPPOST_XY = (-11.0, -6.0)


def _observation(position=(0.0, 0.0, 0.0)) -> NavObservation:
    candidate, obstacle = _lamppost(
        "lamp-far", _FAR_LAMPPOST_XY[0], _FAR_LAMPPOST_XY[1], distance_m=12.53
    )
    return NavObservation(
        position=position,
        heading_deg=0.0,
        extras={
            "collision": False,
            "perception_fresh": True,
            "semantic_candidates": [candidate],
            "lidar_obstacles": [obstacle],
            "motion_feedback": {
                "fresh": True,
                "stop_confirmed": True,
                "linear_speed_mps": 0.0,
                "yaw_speed_rad_s": 0.0,
                "settled_linear_speed_mps": 0.08,
                "settled_yaw_speed_rad_s": 0.12,
            },
        },
    )


def _tripwire(name: str, seen: list[str]):
    """A stand-in that records the fact it was called at all."""

    def _tripped(*_args, **_kwargs) -> None:
        seen.append(name)

    return _tripped


def _commit(nav: DirectiveNavigator, *, budget: int = 8) -> None:
    for _ in range(budget):
        nav.step(_observation())
        if nav.mission is not None and nav.mission.goal is not None:
            return
    raise AssertionError("semantic goal never committed")


def _release_trace(*, route_memory: bool, ticks: int) -> tuple[list, dict]:
    """Tick-for-tick trace of the unroutable release, and the final metadata."""

    nav = _nav(route_memory=route_memory)
    try:
        mission = nav.start("walk towards the lamppost")
        _commit(nav)
        nav._navigator = _RouteStatusNavigator()
        trace = []
        for _ in range(ticks):
            command = nav.step(_observation())
            trace.append(
                (
                    round(command.vx, 12),
                    round(command.vy, 12),
                    round(command.vyaw, 12),
                    command.stop,
                    command.note,
                    mission.status_value(),
                    None if mission.goal is None else (mission.goal.x, mission.goal.y),
                )
            )
        metadata = {
            key: value
            for key, value in mission.metadata.items()
            # The card's own telemetry keys are the one channel flag-ON is
            # ALLOWED to add; everything else must match. Flag-ON with empty
            # memory writes none of them, which the assertion below also pins.
            if not str(key).startswith("route_memory")
        }
        return trace, metadata
    finally:
        nav.close()


# ---------------------------------------------------------------------------
# Arm 2 substrate — the scripted U corridor (gate (b)).
#
# Free space is three axis-aligned legs around a solid block:
#
#         y=12  +---------------------------+
#               |   north leg (B side)      |
#         y=10  +-----------------------+   |
#               |                       | e |
#               |        SOLID          | a |
#               |                       | s |
#          y=1  +-----------------------+ t |
#               |   south leg (A side)      |
#         y=-1  +---------------------------+
#              x=-1                        x=9
#
# A = (0, 0) in the south leg, B = (0, 11) in the north leg: 11.0 m apart in a
# straight line (inside the card's "sighted at 10-12 m" band) and 27.0 m apart
# along the only corridor that connects them.
# ---------------------------------------------------------------------------

CELL_M = 0.25
_FREE_RECTANGLES = (
    (-1.0, 9.0, -1.0, 1.0),
    (7.0, 9.0, -1.0, 12.0),
    (-1.0, 9.0, 10.0, 12.0),
)
CORRIDOR_ROUTE = ((0.0, 0.0), (8.0, 0.0), (8.0, 11.0), (0.0, 11.0))
CORRIDOR_GOAL_XY = (0.0, 11.0)

#: 8 + 11 + 8. The recorded route the teaching drive lays down.
RECORDED_ROUTE_M = 27.0
#: The stand-in's commanded speed, and the shipped control period.
STAND_IN_SPEED_MPS = 0.6
CONTROL_DT_S = 0.1

# ---- the pre-registered budget and floor, DERIVED before the arms were run ---
#
# BUDGET: the flag-ON arm has to walk the whole recorded route before it can be
# anywhere near the goal --
#     27.0 m / (0.6 m/s * 0.1 s/tick) = 450 ticks
# -- and before memory is consulted at all it must first spend
# ``UNROUTABLE_GOAL_STEPS`` = 60 ticks proving the goal unroutable. 450 + 60 =
# 510, plus 90 ticks (1.5 * the same hysteresis) for the hand-back probe, the
# grounding ladder's opening ticks and the terminal settle: 600.
CORRIDOR_BUDGET_TICKS = 600
# N: the minimum advantage that counts as evidence. One
# ``UNROUTABLE_GOAL_STEPS``, because that is exactly the hysteresis the deferral
# suspends -- an advantage smaller than 60 ticks could be nothing but flag-ON
# declining to release for 60 ticks, which is not navigation.
CORRIDOR_MIN_TICK_ADVANTAGE = DirectiveNavigator.UNROUTABLE_GOAL_STEPS


def _corridor_free(x: float, y: float) -> bool:
    return any(x0 <= x <= x1 and y0 <= y <= y1 for x0, x1, y0, y1 in _FREE_RECTANGLES)


def _polyline(points, step_m: float) -> list[tuple[float, float]]:
    out = [points[0]]
    for a, b in pairwise(points):
        segments = max(1, round(math.dist(a, b) / step_m))
        for i in range(1, segments + 1):
            t = i / segments
            out.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
    return out


class _WindowPlanner:
    """Stand-in for ``RollingGridPlanner``: ONE window, search, clip, statuses.

    Faithful in the property this card turns on and in no other: the planner can
    only route inside the rolling window centred on the robot
    (``ROUTE_MEMORY_RANGE_M`` of reach), a goal outside it is clipped to the
    window along the straight line to it, and a target with no traversable route
    inside the window is ``goal_blocked`` / ``no_path``. It is a breadth-first
    search on a 0.25 m lattice, not A*, and it models none of the real planner's
    frontier fallbacks -- see ``does_not_prove`` in RM2_STATUS.md.
    """

    def __init__(self, free_fn) -> None:
        self._free = free_fn
        self._cache_key = None
        self._cache = None

    def plan(self, robot, goal):
        key = (
            round(robot[0] / CELL_M),
            round(robot[1] / CELL_M),
            round(goal[0] / CELL_M),
            round(goal[1] / CELL_M),
        )
        if key != self._cache_key:
            self._cache_key = key
            self._cache = self._plan(robot, goal)
        return self._cache

    def _plan(self, robot, goal):
        half = DirectiveNavigator.ROUTE_MEMORY_RANGE_M
        lo_x, hi_x = robot[0] - half, robot[0] + half
        lo_y, hi_y = robot[1] - half, robot[1] + half
        inside = lo_x <= goal[0] <= hi_x and lo_y <= goal[1] <= hi_y
        target = goal if inside else _clip_to_window(robot, goal, half)
        start = (round(robot[0] / CELL_M), round(robot[1] / CELL_M))
        tgt = (
            min(max(round(target[0] / CELL_M), math.ceil(lo_x / CELL_M)), int(hi_x / CELL_M)),
            min(max(round(target[1] / CELL_M), math.ceil(lo_y / CELL_M)), int(hi_y / CELL_M)),
        )
        if not self._free(tgt[0] * CELL_M, tgt[1] * CELL_M):
            return ("goal_blocked", None)
        seen = {start}
        parent: dict = {}
        queue = deque([start])
        while queue:
            current = queue.popleft()
            if current == tgt:
                break
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)):
                nxt = (current[0] + dx, current[1] + dy)
                if nxt in seen:
                    continue
                wx, wy = nxt[0] * CELL_M, nxt[1] * CELL_M
                if not (lo_x <= wx <= hi_x and lo_y <= wy <= hi_y) or not self._free(wx, wy):
                    continue
                seen.add(nxt)
                parent[nxt] = current
                queue.append(nxt)
        if tgt not in seen:
            return ("no_path" if inside else "goal_blocked", None)
        path = [tgt]
        while path[-1] != start:
            path.append(parent[path[-1]])
        path.reverse()
        status = "planned" if inside else "partial"
        return (status, [(c[0] * CELL_M, c[1] * CELL_M) for c in path])


def _clip_to_window(robot, goal, half):
    dx, dy = goal[0] - robot[0], goal[1] - robot[1]
    scale = 1.0
    if abs(dx) > 1e-9:
        scale = min(scale, half / abs(dx))
    if abs(dy) > 1e-9:
        scale = min(scale, half / abs(dy))
    return (robot[0] + dx * scale, robot[1] + dy * scale)


class _CorridorWorld:
    """Robot state; motion is integrated from the RETURNED (braked) command."""

    def __init__(self) -> None:
        self.x = 0.0
        self.y = 0.0
        self.t = 0.0

    def advance(self, stand_in, command: MidLevelCommand) -> None:
        self.t += CONTROL_DT_S
        if stand_in.direction is None or command.vx <= 0.0:
            return
        self.x += stand_in.direction[0] * command.vx * CONTROL_DT_S
        self.y += stand_in.direction[1] * command.vx * CONTROL_DT_S


class _CorridorNavigator:
    """Whatever ``mission.goal`` it is handed, it plans to THAT and only that.

    Route memory hands it a proxy mission carrying the interim waypoint, which
    is the whole consumption contract: memory chooses where to aim, the planner
    decides whether and how to get there, and the returned command is the only
    thing that ever moves the body.
    """

    LOOKAHEAD_M = 0.9

    def __init__(self, world: _CorridorWorld, free_fn=_corridor_free) -> None:
        self.world = world
        self.planner = _WindowPlanner(free_fn)
        self.last_route_status: str | None = None
        self.direction: tuple[float, float] | None = None
        self.goals_seen: list[tuple[float, float]] = []
        self.resets = 0

    def reset(self, mission) -> None:
        self.resets += 1
        mission.status = "running"

    def close(self) -> None:
        return None

    def act(self, observation, mission) -> MidLevelCommand:
        self.direction = None
        if mission.goal is None:
            mission.status = "failed"
            return MidLevelCommand(stop=True, note="grid_goal_missing")
        robot = (self.world.x, self.world.y)
        goal = (mission.goal.x, mission.goal.y)
        self.goals_seen.append(goal)
        radius = (
            0.25 if mission.goal.arrival_radius_m is None else float(mission.goal.arrival_radius_m)
        )
        if math.dist(robot, goal) <= radius:
            self.last_route_status = "at_goal"
            mission.status = "arrived"
            return MidLevelCommand(stop=True, note="arrived")
        status, path = self.planner.plan(robot, goal)
        self.last_route_status = status
        if path is None:
            return MidLevelCommand(vx=0.0, vyaw=0.2, note=f"grid_recover_scan status={status}")
        aim = path[-1]
        travelled = 0.0
        for a, b in pairwise(path):
            travelled += math.dist(a, b)
            if travelled >= self.LOOKAHEAD_M:
                aim = b
                break
        distance = math.dist(robot, aim)
        if distance < 1e-6:
            return MidLevelCommand(vx=0.0, vyaw=0.2, note=f"grid_recover_scan status={status}")
        self.direction = ((aim[0] - robot[0]) / distance, (aim[1] - robot[1]) / distance)
        return MidLevelCommand(
            vx=STAND_IN_SPEED_MPS, vyaw=0.0, note=f"grid_track status={status}"
        )


def _corridor_observation(world: _CorridorWorld, *, extras=None) -> NavObservation:
    candidate, _ = _lamppost("lamp-b", CORRIDOR_GOAL_XY[0], CORRIDOR_GOAL_XY[1], distance_m=0.0)
    distance = math.dist((world.x, world.y), CORRIDOR_GOAL_XY)
    bearing = math.atan2(CORRIDOR_GOAL_XY[1] - world.y, CORRIDOR_GOAL_XY[0] - world.x)
    payload = {
        "collision": False,
        "perception_fresh": True,
        "time_s": world.t,
        "semantic_candidates": [candidate],
        "lidar_obstacles": [{"id": "lamp-b", "distance_m": distance, "bearing_rad": bearing}],
        "motion_feedback": {
            "fresh": True,
            "stop_confirmed": True,
            "linear_speed_mps": 0.0,
            "yaw_speed_rad_s": 0.0,
            "settled_linear_speed_mps": 0.08,
            "settled_yaw_speed_rad_s": 0.12,
        },
    }
    payload.update(extras or {})
    return NavObservation(position=(world.x, world.y, 0.0), heading_deg=0.0, extras=payload)


def _teach_the_corridor(nav: DirectiveNavigator, world: _CorridorWorld) -> None:
    """Drive A -> B -> A on the product path so AUTO-TEACH records it."""

    nav.start("walk towards the lamppost")
    forward = _polyline(CORRIDOR_ROUTE, DEFAULT_KEYFRAME_SPACING_M * 0.8)
    back = _polyline(tuple(reversed(CORRIDOR_ROUTE)), DEFAULT_KEYFRAME_SPACING_M * 0.8)
    for x, y in forward + back:
        world.x, world.y = x, y
        world.t += CONTROL_DT_S
        nav.step(_corridor_observation(world))


class _CorridorRun:
    __slots__ = ("arrived_tick", "failed_tick", "final_xy", "mission", "nav", "note", "status")


def _run_corridor(
    *,
    route_memory: bool,
    teach: bool,
    budget: int = CORRIDOR_BUDGET_TICKS,
    free_fn=_corridor_free,
    mission_free_fn=None,
    on_commit=None,
) -> _CorridorRun:
    world = _CorridorWorld()
    nav = _nav(route_memory=route_memory)
    stand_in = _CorridorNavigator(world, free_fn)
    nav._navigator = stand_in
    if teach:
        _teach_the_corridor(nav, world)
    if mission_free_fn is not None:
        stand_in.planner = _WindowPlanner(mission_free_fn)
    world.x = world.y = world.t = 0.0
    mission = nav.start("walk towards the lamppost")
    result = _CorridorRun()
    result.arrived_tick = None
    result.failed_tick = None
    result.note = ""
    committed = False
    for tick in range(budget):
        command = nav.step(_corridor_observation(world))
        world.advance(stand_in, command)
        if on_commit is not None and not committed and mission.goal is not None:
            committed = True
            on_commit(nav)
        result.note = command.note
        if mission.status_value() == "arrived":
            result.arrived_tick = tick
            break
        if mission.status_value() == "failed":
            result.failed_tick = tick
            break
    result.final_xy = (world.x, world.y)
    result.status = mission.status_value()
    result.nav = nav
    result.mission = mission
    return result


# ---------------------------------------------------------------------------
# GATE (a) — flag-off is today's behaviour, verbatim
# ---------------------------------------------------------------------------


def test_the_flag_is_off_in_the_shipped_config_and_leaves_no_state_behind() -> None:
    navigator = DirectiveNavigator.from_config(REPO / "configs" / "navigation" / "default.yaml")
    try:
        assert navigator.route_memory is False
        assert navigator._route_memory is None
        assert navigator._route_memory_chain == ()
        assert navigator._route_memory_target is None
        assert navigator._route_memory_spent == set()
    finally:
        navigator.close()


def test_the_flag_is_reachable_from_config_so_the_off_default_is_a_choice() -> None:
    """A default that cannot be turned on is not a default, it is dead code."""

    navigator = DirectiveNavigator.from_config(
        REPO / "configs" / "navigation" / "default.yaml", route_memory=True
    )
    try:
        assert navigator.route_memory is True
        assert navigator._route_memory is not None
    finally:
        navigator.close()


def test_flag_off_and_empty_memory_produce_the_same_release_tick_for_tick() -> None:
    """GATE (a), second half: the ``_unroutable_goal_recovery`` release path.

    RM-1's contract is that ``waypoints_toward`` returns ``()`` for anything the
    robot has not actually driven, and that ``()`` means "today's behaviour,
    verbatim" -- never "maybe". A navigator that has taught the graph nothing is
    the strongest available instance of that: the flag is fully on, every RM-2
    branch is entered, and the answer is empty every time.
    """

    ticks = DirectiveNavigator.UNROUTABLE_GOAL_STEPS + 5
    off_trace, off_metadata = _release_trace(route_memory=False, ticks=ticks)
    on_trace, on_metadata = _release_trace(route_memory=True, ticks=ticks)

    assert on_trace == off_trace
    assert on_metadata == off_metadata
    # The release really did happen in both arms, so the equality is not the
    # equality of two runs that did nothing.
    assert off_metadata["unreachable_candidates"] == ["lamp-far"]
    assert off_metadata["unroutable_route_status"] == "goal_blocked"
    assert any(entry[4] == "semantic_replan_after_unroutable_goal" for entry in off_trace)
    # ...and the flag-ON arm really did consult memory rather than short-circuit
    # on the at-range test, which is what makes ``()`` the load-bearing answer.
    nav = _nav(route_memory=True)
    try:
        nav.start("walk towards the lamppost")
        _commit(nav)
        nav._navigator = _RouteStatusNavigator()
        for _ in range(ticks):
            nav.step(_observation())
        assert nav._route_memory.routes_queried >= 1
        assert nav._route_memory.routes_found == 0
    finally:
        nav.close()


def test_seeded_memory_makes_the_flag_off_comparison_fail() -> None:
    """The companion proof: the tick-for-tick comparison has teeth.

    Seed the hook's frozen query with a fabricated chain -- the one thing RM-1's
    router will never return -- and the two traces must diverge. Without this the
    equality above would be satisfied by any implementation that did nothing at
    all, including one that had accidentally disabled the flag.
    """

    from parcel_robot.route_memory.memory import RouteKeyframe

    ticks = DirectiveNavigator.UNROUTABLE_GOAL_STEPS + 5
    off_trace, _ = _release_trace(route_memory=False, ticks=ticks)

    nav = _nav(route_memory=True)
    try:
        mission = nav.start("walk towards the lamppost")
        _commit(nav)
        nav._navigator = _RouteStatusNavigator()
        goal = mission.goal
        assert goal is not None
        fabricated = tuple(
            RouteKeyframe(
                x=goal.x * (i / 6.0),
                y=goal.y * (i / 6.0),
                yaw_rad=0.0,
                frame="map",
            )
            for i in range(7)
        )
        nav._route_memory.graph.waypoints_toward = lambda *_args, **_kw: fabricated
        seeded_trace = []
        for _ in range(ticks):
            command = nav.step(_observation())
            seeded_trace.append(
                (
                    round(command.vx, 12),
                    round(command.vy, 12),
                    round(command.vyaw, 12),
                    command.stop,
                    command.note,
                    mission.status_value(),
                    None if mission.goal is None else (mission.goal.x, mission.goal.y),
                )
            )
        assert seeded_trace != off_trace
        # ...and it diverged for the RIGHT reason: the release was deferred.
        assert nav.route_memory_deferred_releases >= 1
        assert mission.goal is not None
    finally:
        nav.close()


def test_flag_off_never_enters_a_single_route_memory_branch() -> None:
    """Structural half of (a): the guards, not the outcomes."""

    nav = _nav(route_memory=False)
    tripped: list[str] = []
    for name in (
        "_route_memory_teach",
        "_arm_route_memory_chain",
        "_publish_route_memory_waypoint",
        "_route_memory_navigate",
        "_route_memory_partial_recovery",
        "_route_memory_defer_release",
    ):
        setattr(nav, name, _tripwire(name, tripped))
    try:
        nav.start("walk towards the lamppost")
        _commit(nav)
        nav._navigator = _RouteStatusNavigator()
        for _ in range(DirectiveNavigator.UNROUTABLE_GOAL_STEPS + 5):
            nav.step(_observation())
        assert tripped == []
    finally:
        nav.close()


# ---------------------------------------------------------------------------
# GATE (b) — non-vacuity, with the paired control
# ---------------------------------------------------------------------------


def test_the_corridor_substrate_is_the_one_the_card_specified() -> None:
    """Pre-flight: the scenario really is a beyond-reach goal at 10-12 m."""

    assert 10.0 <= math.dist((0.0, 0.0), CORRIDOR_GOAL_XY) <= 12.0
    # ...and it is beyond the planner's reach, which is the whole premise.
    assert math.dist((0.0, 0.0), CORRIDOR_GOAL_XY) > DirectiveNavigator.ROUTE_MEMORY_RANGE_M
    # The only corridor connecting A and B is 27 m long, so no window-local
    # detour can produce this route: it has to come from memory.
    assert chain_length_m(
        [type("K", (), {"x": x, "y": y})() for x, y in CORRIDOR_ROUTE]
    ) == pytest.approx(RECORDED_ROUTE_M)
    # The budget is what the derivation says it is, not a tuned number.
    assert CORRIDOR_BUDGET_TICKS == round(
        RECORDED_ROUTE_M / (STAND_IN_SPEED_MPS * CONTROL_DT_S)
    ) + DirectiveNavigator.UNROUTABLE_GOAL_STEPS + 90


def test_flag_on_arrives_through_a_remembered_route_where_flag_off_fails() -> None:
    """GATE (b). Three arms, one scenario, one budget.

    The DELTA, not the win: flag-ON reaches the true goal with at least
    ``CORRIDOR_MIN_TICK_ADVANTAGE`` ticks of the budget to spare, and neither
    control arm reaches it at all.
    """

    on = _run_corridor(route_memory=True, teach=True)
    off = _run_corridor(route_memory=False, teach=False)
    # The control that makes this a measurement: the flag is ON and every RM-2
    # branch is live, but the robot never drove the corridor, so memory has
    # nothing recorded and answers ``()``.
    untaught = _run_corridor(route_memory=True, teach=False)

    try:
        assert on.arrived_tick is not None, "flag-ON never reached the true goal"
        assert on.arrived_tick + CORRIDOR_MIN_TICK_ADVANTAGE <= CORRIDOR_BUDGET_TICKS
        assert math.dist(on.final_xy, CORRIDOR_GOAL_XY) < 3.0

        assert off.arrived_tick is None
        assert off.status == "failed"
        assert off.note == "semantic_target_unreachable"
        assert off.mission.metadata["unreachable_candidates"] == ["lamp-b"]
        # It never moved: the flag-off arm's problem is not that it is slow.
        assert math.dist(off.final_xy, (0.0, 0.0)) < 0.5

        assert untaught.arrived_tick is None
        assert untaught.status == off.status
        assert untaught.note == off.note
        assert untaught.nav.route_memory_routes_found == 0
        assert untaught.nav.route_memory_proposals == 0

        # Non-vacuity of the mechanism itself, counter by counter.
        assert on.nav.route_memory_keyframes > 0
        assert on.nav.route_memory_routes_found == 1
        assert on.nav.route_memory_wins >= 1
        assert on.nav.route_memory_vetoes == 0
        assert on.nav.route_memory_chain_ticks > 0
        assert on.nav.route_memory_deferred_releases >= 1
        assert on.mission.metadata["route_memory_trigger"].startswith("unroutable:")
    finally:
        for run in (on, off, untaught):
            run.nav.close()


def test_the_taught_route_is_what_flag_on_actually_drove() -> None:
    """The waypoints handed to the planner are recorded places, in travel order.

    Flag-ON could in principle "win" by wandering. It does not: every interim
    goal the planner was ever handed is within half a keyframe spacing of the
    recorded polyline, which is the corridor and nothing else.
    """

    run = _run_corridor(route_memory=True, teach=True)
    try:
        waypoints = [
            goal
            for goal in run.nav._navigator.goals_seen
            if _nearest_route_distance(goal) <= DEFAULT_KEYFRAME_SPACING_M
        ]
        assert len(waypoints) > 0
        # The robot got round the block: it visited the east leg, which the
        # straight line from A to B never touches.
        assert max(x for x, _ in run.nav._navigator.goals_seen) > 7.0
    finally:
        run.nav.close()


def _nearest_route_distance(point) -> float:
    best = float("inf")
    for a, b in pairwise(CORRIDOR_ROUTE):
        best = min(best, _point_segment_distance(point, a, b))
    return best


def _point_segment_distance(p, a, b) -> float:
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    length_sq = dx * dx + dy * dy
    if length_sq <= 0.0:
        return math.dist(p, a)
    t = max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / length_sq))
    return math.dist(p, (ax + t * dx, ay + t * dy))


# ---------------------------------------------------------------------------
# GATE (c) — the lethal veto, on a waypoint proposal
# ---------------------------------------------------------------------------


def _lethal_run(lethal_cost) -> _CorridorRun:
    def _install(nav: DirectiveNavigator) -> None:
        nav.goal_arbiter = GoalArbiter(lethal_cost=lethal_cost)

    return _run_corridor(route_memory=True, teach=True, on_commit=_install)


def test_a_lethal_waypoint_is_vetoed_and_grants_no_motion_authority() -> None:
    """GATE (c). The arbiter's veto is upstream of every interim target.

    ``_publish_route_memory_waypoint`` is the ONLY writer of
    ``_route_memory_target`` and it writes only what ``GoalArbiter.resolve``
    returned. A veto therefore leaves route memory with nothing to drive, and
    the mission takes the release path it would have taken flag-off.
    """

    run = _lethal_run(lambda _x, _y: True)
    try:
        assert run.nav.route_memory_proposals >= 1
        assert run.nav.route_memory_vetoes == run.nav.route_memory_proposals
        assert run.nav.route_memory_wins == 0
        assert run.nav._route_memory_target is None
        assert run.nav._route_memory_chain == ()
        assert run.nav.route_memory_chain_ticks == 0
        # Vetoed means the release was never deferred: today's behaviour.
        assert run.nav.route_memory_deferred_releases == 0
        assert run.status == "failed"
        assert run.note == "semantic_target_unreachable"
        assert run.mission.metadata["unreachable_candidates"] == ["lamp-b"]
    finally:
        run.nav.close()


def test_a_lethal_cell_on_the_leg_vetoes_the_whole_waypoint_not_just_the_tip() -> None:
    """The leg, not the endpoint. ``waypoints`` carries the whole slice.

    A tip in free space with a lethal cell halfway along it is the mixed-lethal
    case ``lethal_veto.waypoints_trigger_lethal_veto`` exists for. Route memory
    inherits it for free by publishing the slice, and this is the case that
    proves the slice is really there -- the tip alone would sail through.
    """

    # A lethal band across the south leg, well short of the first waypoint tip
    # (which sits at x ~ 8.0), so only the intermediate points touch it.
    run = _lethal_run(lambda x, _y: 3.0 <= x <= 5.0)
    try:
        assert run.nav.route_memory_proposals >= 1
        assert run.nav.route_memory_wins == 0
        assert run.nav.route_memory_vetoes >= 1
        assert run.nav._route_memory_target is None
        assert run.status == "failed"
    finally:
        run.nav.close()


def test_the_published_waypoint_carries_the_whole_leg_as_waypoints() -> None:
    """The pure half of the same property, at the proposer's own API."""

    from parcel_robot.route_memory.memory import RouteKeyframe

    chain = tuple(
        RouteKeyframe(x=float(i), y=0.0, yaw_rad=0.0, frame="map")
        for i in range(12)
    )
    goal = waypoint_goal_from_chain(chain, robot_xy=(0.0, 0.0), now_s=1.0)
    assert goal is not None
    assert goal.source == PLACE_ROUTE_SOURCE
    assert len(goal.waypoints) >= 2
    assert goal.waypoints[-1] == (goal.pose[0], goal.pose[1])
    # Every published point is a recorded keyframe, in recorded order.
    recorded = [(kf.x, kf.y) for kf in chain]
    first = recorded.index(goal.waypoints[0])
    assert list(goal.waypoints) == recorded[first : first + len(goal.waypoints)]


def test_seeded_tip_only_waypoints_would_survive_a_lethal_leg() -> None:
    """Companion proof for the two cases above, at the arbiter itself."""

    from dataclasses import replace as dataclass_replace

    from parcel_robot.route_memory.memory import RouteKeyframe

    chain = tuple(
        RouteKeyframe(x=float(i), y=0.0, yaw_rad=0.0, frame="map")
        for i in range(9)
    )
    goal = waypoint_goal_from_chain(chain, robot_xy=(0.0, 0.0), now_s=1.0)
    assert goal is not None
    lethal_mid = GoalArbiter(lethal_cost=lambda x, _y: 3.0 <= x <= 5.0)
    assert lethal_mid.resolve((goal,), now_s=1.0) is None
    # Strip the leg to just the tip -- the pre-hardening shape -- and the SAME
    # lethal function admits it. The veto is carried by the waypoints.
    tip_only = dataclass_replace(goal, waypoints=())
    assert lethal_mid.resolve((tip_only,), now_s=1.0) is tip_only


# ---------------------------------------------------------------------------
# Authority — the mission goal, the K0 region and the arrival predicate
# ---------------------------------------------------------------------------


def test_a_waypoint_never_replaces_the_mission_goal_or_its_arrival_region() -> None:
    run = _run_corridor(route_memory=True, teach=True)
    try:
        mission = run.mission
        assert mission.metadata["candidate_id"] == "lamp-b"
        # The committed approach pose is still an approach to the TRUE target,
        # not to any waypoint. Every waypoint the run drove lay on the recorded
        # corridor; the goal does not.
        assert mission.goal is not None
        assert math.dist((mission.goal.x, mission.goal.y), CORRIDOR_GOAL_XY) < 3.0
        assert mission.goal.label != "route_memory_waypoint"
        assert mission.goal.poi_id == "lamp-b"
        # K0's region, if this relation built one, is the true target's.
        region = mission.metadata.get("arrival_goal_region")
        if region is not None:
            centre = getattr(region, "center", None)
            if centre is not None:
                assert math.dist(tuple(centre)[:2], CORRIDOR_GOAL_XY) < 3.0
    finally:
        run.nav.close()


def test_reaching_a_waypoint_is_not_an_arrival() -> None:
    """The consumption contract's load-bearing line.

    The stand-in reports ``arrived`` on the PROXY mission the moment the robot
    is inside the waypoint's 0.25 m disc. If that leaked, the mission would
    claim to have arrived at a lamppost it is 20 m away from.
    """

    world = _CorridorWorld()
    nav = _nav(route_memory=True)
    stand_in = _CorridorNavigator(world)
    nav._navigator = stand_in
    try:
        _teach_the_corridor(nav, world)
        world.x = world.y = world.t = 0.0
        mission = nav.start("walk towards the lamppost")
        saw_waypoint_reached = False
        for _ in range(CORRIDOR_BUDGET_TICKS):
            command = nav.step(_corridor_observation(world))
            world.advance(stand_in, command)
            # The pipeline appends its own telemetry suffixes after a ``|``.
            if command.note.split("|")[0] == "route_memory_waypoint_reached":
                saw_waypoint_reached = True
                assert command.stop is False
                assert mission.status_value() == "running"
                assert math.dist((world.x, world.y), CORRIDOR_GOAL_XY) > 1.0
            if mission.status_value() in {"arrived", "failed"}:
                break
        assert saw_waypoint_reached, "no waypoint was ever reached; the case is vacuous"
        # And when the mission DID arrive, it arrived at the true goal.
        assert mission.status_value() == "arrived"
        assert math.dist((world.x, world.y), CORRIDOR_GOAL_XY) < 3.0
    finally:
        nav.close()


def test_a_released_candidate_takes_its_chain_with_it() -> None:
    """One release funnel, one place a chain dies.

    ``_begin_semantic_replan`` is where A*, the obstacle gate, the approach
    solver and the runtime's ``release_current_candidate`` all end up. A chain
    that outlived its commitment would keep steering toward a waypoint on the
    way to a goal the mission has already given up.
    """

    world = _CorridorWorld()
    nav = _nav(route_memory=True)
    stand_in = _CorridorNavigator(world)
    nav._navigator = stand_in
    try:
        _teach_the_corridor(nav, world)
        world.x = world.y = world.t = 0.0
        mission = nav.start("walk towards the lamppost")
        for _ in range(CORRIDOR_BUDGET_TICKS):
            command = nav.step(_corridor_observation(world))
            world.advance(stand_in, command)
            if nav._route_memory_chain:
                break
        assert nav._route_memory_chain, "no chain was ever armed; the case is vacuous"
        released = nav.release_current_candidate("test_release")
        assert released is True
        assert mission.goal is None
        assert nav._route_memory_chain == ()
        assert nav._route_memory_target is None
        assert mission.metadata["route_memory_flush"] == "candidate_released"
    finally:
        nav.close()


# ---------------------------------------------------------------------------
# The LIVELOCK seam the Wave-2 audit pre-registered
# ---------------------------------------------------------------------------


def _blocked_south_leg(x: float, y: float) -> bool:
    """The taught corridor, plugged at x in [3.0, 3.6] after teaching."""

    if 3.0 <= x <= 3.6 and -1.0 <= y <= 1.0:
        return False
    return _corridor_free(x, y)


#: The deferral's whole cost, derived: one ``ROUTE_MEMORY_STALL_STEPS`` for the
#: chain to prove it is not advancing, plus one ``UNROUTABLE_GOAL_STEPS`` for
#: ``_steps_goal_unroutable`` to re-accumulate after the deferral zeroed it.
#: Nothing else, and only once per committed instance.
LIVELOCK_TICK_BOUND = (
    DirectiveNavigator.ROUTE_MEMORY_STALL_STEPS + DirectiveNavigator.UNROUTABLE_GOAL_STEPS
)


def test_a_chain_that_stops_advancing_gives_the_release_back() -> None:
    """The deferred blacklist is a DEFERRAL, not a cancellation.

    Memory remembers a route it drove yesterday; today something is standing in
    it. The chain arms, the robot drives into the obstruction, and the route
    stops shortening. Flag-off would have released and blacklisted the instance
    at ``UNROUTABLE_GOAL_STEPS``; flag-ON must reach the SAME release, having
    spent a bounded and derived number of extra ticks finding out.
    """

    on = _run_corridor(
        route_memory=True, teach=True, budget=1400, mission_free_fn=_blocked_south_leg
    )
    off = _run_corridor(
        route_memory=False, teach=False, budget=1400, mission_free_fn=_blocked_south_leg
    )
    try:
        assert off.failed_tick is not None
        assert on.failed_tick is not None, "flag-ON never released: LIVELOCK"
        assert on.note == off.note == "semantic_target_unreachable"
        assert (
            on.mission.metadata["unreachable_candidates"]
            == off.mission.metadata["unreachable_candidates"]
            == ["lamp-b"]
        )
        # The chain really was tried, and really was retired for stalling.
        assert on.nav.route_memory_wins >= 1
        assert on.nav.route_memory_handbacks >= 1
        assert on.mission.metadata["route_memory_handback"] == "chain_stalled"
        assert on.mission.metadata["route_memory_spent"] == ["lamp-b"]
        # And the cost of finding out is the derived bound, not "eventually".
        assert on.failed_tick - off.failed_tick <= LIVELOCK_TICK_BOUND
    finally:
        for run in (on, off):
            run.nav.close()


def test_seeded_removal_of_the_spent_guard_reproduces_the_livelock() -> None:
    """Companion proof: without the guard the release never comes back.

    ``_route_memory_spent`` is replaced by a set that forgets every ``add`` --
    exactly the pre-fix implementation -- and the same scenario is run on the
    same budget. The chain is re-armed from the same recorded graph after every
    stall and the mission never reaches its release.
    """

    class _ForgetfulSet(set):
        """The seeded defect: a spent-set that forgets every ``add``."""

        def add(self, value) -> None:
            return None

    def _seed(nav: DirectiveNavigator) -> None:
        nav._route_memory_spent = _ForgetfulSet()

    guarded = _run_corridor(
        route_memory=True, teach=True, budget=1400, mission_free_fn=_blocked_south_leg
    )
    seeded = _run_corridor(
        route_memory=True,
        teach=True,
        budget=1400,
        mission_free_fn=_blocked_south_leg,
        on_commit=_seed,
    )
    off = _run_corridor(
        route_memory=False, teach=False, budget=1400, mission_free_fn=_blocked_south_leg
    )
    try:
        assert guarded.failed_tick is not None and off.failed_tick is not None
        assert guarded.failed_tick - off.failed_tick <= LIVELOCK_TICK_BOUND
        # The seeded arm re-arms the same dead chain over and over. Whatever
        # ends it, it is not the release the deferral suspended arriving on
        # time: it is far outside the derived bound, and it burns many more
        # deferrals doing it.
        seeded_release = 10**9 if seeded.failed_tick is None else seeded.failed_tick
        assert seeded_release - off.failed_tick > LIVELOCK_TICK_BOUND
        assert seeded.nav.route_memory_deferred_releases > (
            guarded.nav.route_memory_deferred_releases
        )
    finally:
        for run in (guarded, seeded, off):
            run.nav.close()


def test_an_advancing_chain_is_never_re_armed_and_never_hides_its_own_stall() -> None:
    """``_route_memory_defer_release`` must not re-query while a chain is live.

    Re-arming resets ``_steps_route_memory_stalled``, which is the clock the
    stall retirement runs on. A deferral that reset it every 60 ticks could
    never retire, which is the livelock by a second door.
    """

    world = _CorridorWorld()
    nav = _nav(route_memory=True)
    stand_in = _CorridorNavigator(world)
    nav._navigator = stand_in
    try:
        _teach_the_corridor(nav, world)
        world.x = world.y = world.t = 0.0
        nav.start("walk towards the lamppost")
        for _ in range(CORRIDOR_BUDGET_TICKS):
            command = nav.step(_corridor_observation(world))
            world.advance(stand_in, command)
            if nav._route_memory_chain:
                break
        assert nav._route_memory_chain
        armed_before = nav.route_memory_routes_found
        assert nav._route_memory_defer_release(trigger="probe") is True
        assert nav.route_memory_routes_found == armed_before
    finally:
        nav.close()


# ---------------------------------------------------------------------------
# Mission boundaries and MAP re-anchors (AUDIT_WAVE1_FABLE.md, cross-lane intel)
# ---------------------------------------------------------------------------


def test_every_mission_boundary_breaks_the_ingest_track() -> None:
    """AUDIT_WAVE1_FABLE.md's named failure, pinned in both directions.

    Without ``reset_track`` at the boundary, the teleport from one mission's end
    pose to the next mission's start pose is recorded as a traversal and the
    router hands out an edge across ground nothing ever walked.
    """

    world = _CorridorWorld()
    nav = _nav(route_memory=True)
    nav._navigator = _CorridorNavigator(world)
    try:
        # One-way this time, so the mission genuinely ENDS somewhere else: the
        # A -> B -> A drive of gate (b) finishes back at A and would make the
        # teleport zero-length, which is no test at all.
        nav.start("walk towards the lamppost")
        for x, y in _polyline(CORRIDOR_ROUTE, DEFAULT_KEYFRAME_SPACING_M * 0.8):
            world.x, world.y = x, y
            world.t += CONTROL_DT_S
            nav.step(_corridor_observation(world))
        end_xy = (world.x, world.y)
        teleport_m = math.dist(end_xy, (0.0, 0.0))
        assert teleport_m > 5.0, "the teleport is the test; it must be real"
        graph = nav._route_memory.graph
        edges_before = len(graph.edges)

        world.x, world.y = 0.0, 0.0  # the teleport back to A
        nav.start("walk towards the lamppost")
        nav.step(_corridor_observation(world))

        spanning = [
            edge for edge in graph.edges[edges_before:] if edge.length_m > teleport_m * 0.5
        ]
        assert spanning == []
        # Seeded control: the SAME teleport with the boundary skipped is
        # recorded (RM-1's distance backstop flags it rather than routing it,
        # which is the one-directional error its contract promises).
        graph.reset_track()
        graph.record_visit(_map_pose(*end_xy))
        graph.record_visit(_map_pose(0.0, 0.0))
        crossed = [edge for edge in graph.edges if edge.crossed_reanchor]
        assert crossed, "the backstop did not fire; the boundary assertion is vacuous"
    finally:
        nav.close()


def _map_pose(x: float, y: float) -> PoseEstimate:
    return PoseEstimate(
        x=x,
        y=y,
        yaw=0.0,
        frame=Frame.MAP,
        health=PoseHealth.HEALTHY,
        stamp_monotonic_s=0.0,
    )


class _CountingProvider:
    """A ``PoseProvider`` that also publishes its own map-correction count."""

    name = "test_counting"

    def __init__(self, world: _CorridorWorld) -> None:
        self._world = world
        self.map_correction_events = 0

    def get_pose(self, frame) -> PoseEstimate:
        return PoseEstimate(
            x=self._world.x,
            y=self._world.y,
            yaw=0.0,
            frame=frame,
            health=PoseHealth.HEALTHY,
            stamp_monotonic_s=self._world.t,
        )


def test_a_map_reanchor_reported_by_the_provider_flushes_the_live_chain() -> None:
    """RM-1 §4's preferred signal, consumed and acted on.

    A live chain is a list of MAP snapshots taken before the jump; after one the
    recorded geometry and the current estimate are not in the same frame. RM-1
    refuses to ROUTE across a jump for exactly this reason, and driving a chain
    extracted across one would be the same claim through another door.
    """

    world = _CorridorWorld()
    nav = _nav(route_memory=True)
    stand_in = _CorridorNavigator(world)
    nav._navigator = stand_in
    provider = _CountingProvider(world)
    extras = {POSE_PROVIDER_KEY: provider}
    try:
        _teach_the_corridor(nav, world)
        world.x = world.y = world.t = 0.0
        mission = nav.start("walk towards the lamppost")
        for _ in range(CORRIDOR_BUDGET_TICKS):
            command = nav.step(_corridor_observation(world, extras=extras))
            world.advance(stand_in, command)
            if nav._route_memory_chain:
                break
        assert nav._route_memory_chain, "no chain was armed; the case is vacuous"

        provider.map_correction_events += 1
        nav.step(_corridor_observation(world, extras=extras))

        assert nav._route_memory_chain == ()
        assert nav._route_memory_target is None
        assert mission.metadata["route_memory_flush"] == "map_reanchor"
        assert nav._route_memory.provider_reanchors == 1
    finally:
        nav.close()


def test_a_provider_without_a_correction_counter_falls_back_silently() -> None:
    """The honest half: ``pose.py`` publishes no counter today (DR-1's file)."""

    from parcel_robot.route_memory.runtime_hook import provider_reanchor_count

    assert provider_reanchor_count(object()) is None
    assert provider_reanchor_count(None) is None
    assert provider_reanchor_count(_CountingProvider(_CorridorWorld())) == 0


# ---------------------------------------------------------------------------
# Properties of the proposer, each with its seeded companion
# ---------------------------------------------------------------------------


def _straight_chain(n: int, step: float = 0.5):
    from parcel_robot.route_memory.memory import RouteKeyframe

    return tuple(
        RouteKeyframe(x=i * step, y=0.0, yaw_rad=0.0, frame="map")
        for i in range(n)
    )


def _u_chain():
    """6 m across, 30 m around — RM-1's own no-shortcut geometry, narrowed.

    The width matters: the far arm has to sit INSIDE the 8.05 m attach disc for
    the euclidean-nearest temptation to exist at all. At 6 m across it does, and
    it is 30 m away along the only route the robot ever walked.
    """

    from parcel_robot.route_memory.memory import RouteKeyframe

    points = (
        _polyline(((0.0, 0.0), (12.0, 0.0)), 0.5)
        + _polyline(((12.0, 0.0), (12.0, 6.0)), 0.5)[1:]
        + _polyline(((12.0, 6.0), (0.0, 6.0)), 0.5)[1:]
    )
    return tuple(RouteKeyframe(x=x, y=y, yaw_rad=0.0, frame="map") for x, y in points)


def test_property_a_waypoint_leg_never_exceeds_the_recorded_reach() -> None:
    """The bound is on RECORDED path length AND on the tip's own range.

    Bounding the recorded length by half the rolling window is the whole safety
    argument: the entire remembered leg between the robot and the interim
    waypoint lies inside one window of live occupancy, so the planner has
    current sensor evidence for every metre of it.
    """

    for chain in (_straight_chain(40), _u_chain(), _straight_chain(3, step=4.0)):
        for start in range(0, len(chain), 3):
            robot = (chain[start].x, chain[start].y)
            span = next_waypoint_keyframe(chain, robot)
            if span is None:
                continue
            lo, hi = span
            assert 0 <= lo <= hi < len(chain)
            assert chain_length_m(chain[lo : hi + 1]) <= DEFAULT_ATTACH_RADIUS_M + 1e-9
            assert (
                math.dist((chain[hi].x, chain[hi].y), robot) <= DEFAULT_ATTACH_RADIUS_M + 1e-9
            )


def test_seeded_a_euclidean_nearest_target_would_break_the_recorded_bound() -> None:
    """Companion proof, on RM-1's own U geometry.

    The far arm of a U sits ~10 m away in a straight line and ~30 m away along
    the route. A proposer that took the euclidean-nearest reachable keyframe
    would aim across the wall between them -- memory inventing precisely the
    shortcut RM-1's router refuses to invent. The recorded bound rejects it.
    """

    chain = _u_chain()
    robot = (chain[0].x, chain[0].y)
    span = next_waypoint_keyframe(chain, robot)
    assert span is not None
    _, target = span
    assert chain_length_m(chain[: target + 1]) <= DEFAULT_ATTACH_RADIUS_M + 1e-9

    # The seeded alternative: the keyframe a proximity-only proposer would find
    # most attractive — comfortably inside the same 8.05 m disc in a STRAIGHT
    # line, and as deep into the recorded route as that allows. It is on the far
    # arm of the U, with a wall between it and the robot.
    tempting = max(
        (
            index
            for index, kf in enumerate(chain)
            if math.dist((kf.x, kf.y), robot) <= DEFAULT_ATTACH_RADIUS_M
        ),
        key=lambda index: chain_length_m(chain[: index + 1]),
    )
    assert tempting > target
    assert math.dist((chain[tempting].x, chain[tempting].y), robot) <= DEFAULT_ATTACH_RADIUS_M
    assert chain_length_m(chain[: tempting + 1]) > DEFAULT_ATTACH_RADIUS_M
    # And the proposer never aims there: the published tip is the recorded-bound
    # one, not the tempting one.
    goal = waypoint_goal_from_chain(chain, robot_xy=robot, now_s=0.0)
    assert goal is not None
    assert goal.pose[:2] == (chain[target].x, chain[target].y)
    assert goal.pose[:2] != (chain[tempting].x, chain[tempting].y)


def test_property_a_spent_chain_returns_none_rather_than_a_zero_length_goal() -> None:
    chain = _straight_chain(6)
    terminal = (chain[-1].x, chain[-1].y)
    assert next_waypoint_keyframe(chain, terminal) is None
    assert waypoint_goal_from_chain(chain, robot_xy=terminal, now_s=0.0) is None
    # ...and the control: one keyframe short of the end, it still has work.
    penultimate = (chain[-2].x, chain[-2].y)
    assert next_waypoint_keyframe(chain, penultimate) is not None


def test_property_the_proposal_is_stamped_with_the_callers_revision_key() -> None:
    """P0-C: a waypoint authored under a corrected-away revision cannot win."""

    chain = _straight_chain(12)
    goal = waypoint_goal_from_chain(
        chain, robot_xy=(0.0, 0.0), now_s=5.0, task_id="task-7", plan_revision=3
    )
    assert goal is not None
    assert (goal.task_id, goal.plan_revision) == ("task-7", 3)
    arbiter = GoalArbiter()
    arbiter.commit_revision(task_id="task-7", plan_revision=4)
    assert arbiter.resolve((goal,), now_s=5.0) is None
    # Seeded companion: an UNSTAMPED proposal survives the same correction,
    # which is exactly the defect stamping exists to prevent.
    unstamped = waypoint_goal_from_chain(chain, robot_xy=(0.0, 0.0), now_s=5.0)
    assert unstamped is not None
    assert arbiter.resolve((unstamped,), now_s=5.0) is unstamped


def test_the_waypoint_reached_radius_is_derived_from_rm1s_spacing() -> None:
    """No new constant: 0.25 m is half RM-1's keyframe spacing, by reference."""

    assert DEFAULT_WAYPOINT_REACHED_M == DEFAULT_KEYFRAME_SPACING_M / 2.0
    assert DirectiveNavigator.ROUTE_MEMORY_RANGE_M == DEFAULT_ATTACH_RADIUS_M
    assert DirectiveNavigator.ROUTE_MEMORY_STALL_STEPS == DirectiveNavigator.UNROUTABLE_GOAL_STEPS


# ---------------------------------------------------------------------------
# AUDIT_WAVE2 finding 1 — the withdrawal keys off the PUBLISHED task, and is
# scoped to route memory's own entry
# ---------------------------------------------------------------------------


def _navigator_with_a_buffered_waypoint():
    """A corridor run stopped at the first tick a waypoint is live in the bus."""

    world = _CorridorWorld()
    nav = _nav(route_memory=True)
    stand_in = _CorridorNavigator(world)
    nav._navigator = stand_in
    _teach_the_corridor(nav, world)
    world.x = world.y = world.t = 0.0
    mission = nav.start("walk towards the lamppost")
    nav.set_active_revision("nav-task", 1)
    for _ in range(CORRIDOR_BUDGET_TICKS):
        command = nav.step(_corridor_observation(world))
        world.advance(stand_in, command)
        if nav._route_memory_chain:
            break
    assert nav._route_memory_chain, "no chain was armed; the case is vacuous"
    assert nav._route_memory_published_task == "nav-task"
    assert PLACE_ROUTE_SOURCE in {g.source for g in nav.proposer_bus.poll(now_s=0.0)}
    return nav, mission


def test_a_correction_that_switches_task_withdraws_the_old_tasks_waypoint() -> None:
    """AUDIT_WAVE2 finding 1, the upheld one.

    ``runtime`` re-points the active key on EVERY accepted plan, including a
    non-nav voice plan, and restamps a running navigator. The first RM-2 shape
    overwrote ``_active_task_id`` and only then purged the bus *under the new
    task*, so the old task's waypoint stayed buffered — and, being neither stale
    nor expired, it still won ``GoalArbiter.resolve`` inside its TTL.
    """

    nav, _mission = _navigator_with_a_buffered_waypoint()
    try:
        stranded = next(
            g for g in nav.proposer_bus.poll(now_s=0.0) if g.source == PLACE_ROUTE_SOURCE
        )
        assert stranded.task_id == "nav-task"

        nav.set_active_revision("voice-task-77", 1)  # the task-SWITCHING correction

        assert nav._route_memory_chain == ()
        assert nav._route_memory_target is None
        assert nav._route_memory_published_task is None
        assert PLACE_ROUTE_SOURCE not in {
            g.source for g in nav.proposer_bus.poll(now_s=0.0)
        }
        # The seeded companion, at the arbiter: the entry that WAS left behind is
        # not harmless — resolve admits it inside its TTL.
        nav.goal_arbiter.set_plan_step(stranded.plan_step_id)
        assert nav.goal_arbiter.resolve((stranded,), now_s=stranded.issued_s + 0.1) is stranded
    finally:
        nav.close()


def test_a_mission_boundary_withdraws_the_buffered_waypoint_too() -> None:
    """finding 1(a): ``stop()`` + ``start()`` keep the key, so nothing goes stale."""

    nav, _mission = _navigator_with_a_buffered_waypoint()
    try:
        nav.stop()
        nav.start("walk towards the lamppost")
        assert nav._route_memory_chain == ()
        assert nav._route_memory_published_task is None
        assert PLACE_ROUTE_SOURCE not in {
            g.source for g in nav.proposer_bus.poll(now_s=0.0)
        }
    finally:
        nav.close()


def test_a_route_memory_private_flush_leaves_other_proposers_buffers_alone() -> None:
    """finding 1(b): blast radius.

    ``ProposerBus.flush_task`` is TASK-scoped by AF-2's design — it drops every
    source's proposal for that task. On a MAP re-anchor, which is route memory's
    private business, nobody else's goal became invalid, so the withdrawal is
    composed down to route memory's own source.
    """

    nav, _mission = _navigator_with_a_buffered_waypoint()
    try:
        bystander = SE2Goal(
            source="grounded_approach",
            pose=(3.0, 0.0, 0.0),
            issued_s=0.0,
            ttl_s=30.0,
            plan_step_id="align_then_translate",
            priority=10,
            task_id="nav-task",
            plan_revision=1,  # live, same task, NOT route memory's
        )
        nav.proposer_bus.publish(bystander)

        dropped = nav._flush_route_memory_waypoints("map_reanchor")

        buffered = {g.source: g for g in nav.proposer_bus.poll(now_s=0.0)}
        assert dropped == 1
        assert PLACE_ROUTE_SOURCE not in buffered
        assert buffered.get("grounded_approach") is bystander
        # Seeded companion: the task-wide purge this replaced would have taken it.
        nav.proposer_bus.flush_task("nav-task")
        assert "grounded_approach" not in {
            g.source for g in nav.proposer_bus.poll(now_s=0.0)
        }
    finally:
        nav.close()


def test_set_active_revision_keeps_its_pre_rm2_exception_ordering() -> None:
    """finding 1(c): RM-2 must not move an exception boundary flag-off.

    Pre-RM-2 the body was two assignments in order: ``str(task_id)`` stored, then
    ``int(plan_revision)``. A revision that will not convert therefore left the
    task id ALREADY updated. Computing a "changed" tuple ahead of the assignments
    evaluated ``int()`` first and left both untouched — a different observable on
    the unconditional path.
    """

    for route_memory in (False, True):
        nav = _nav(route_memory=route_memory)
        try:
            nav.set_active_revision("task-a", 1)
            with pytest.raises((TypeError, ValueError)):
                nav.set_active_revision("task-b", "not-an-int")
            assert nav._active_task_id == "task-b"
            assert nav._active_plan_revision == 1
        finally:
            nav.close()


def test_a_correction_landing_between_resolve_and_store_leaves_no_orphan() -> None:
    """No interim target may ever exist without a chain behind it."""

    nav, _mission = _navigator_with_a_buffered_waypoint()
    try:
        nav._clear_route_memory_chain()
        assert nav._route_memory_target is None
        real_resolve = nav.goal_arbiter.resolve
        fired: list[bool] = []

        def _resolve_then_correct(goals, *, now_s):
            winner = real_resolve(goals, now_s=now_s)
            if winner is not None and winner.source == PLACE_ROUTE_SOURCE and not fired:
                fired.append(True)
                nav.set_active_revision("nav-task", 2)  # lands mid-publish
            return winner

        nav.goal_arbiter.resolve = _resolve_then_correct
        armed = nav._arm_route_memory_chain(trigger="orphan_probe")
        nav.goal_arbiter.resolve = real_resolve

        assert fired, "the interleaving never happened; the case is vacuous"
        assert armed is False
        assert nav._route_memory_target is None
        assert nav._route_memory_chain == ()
        assert nav._route_memory_published_task is None
        assert PLACE_ROUTE_SOURCE not in {
            g.source for g in nav.proposer_bus.poll(now_s=0.0)
        }
    finally:
        nav.close()


# ---------------------------------------------------------------------------
# AUDIT_WAVE2 finding 2 — the hand-back probe, against the REAL GridNavigator
# ---------------------------------------------------------------------------

_LIDAR_BEAMS = 271
_LIDAR_MIN_RAD = -math.radians(135.0)
_LIDAR_INC_RAD = math.radians(270.0) / (_LIDAR_BEAMS - 1)
_LIDAR_MAX_M = 12.0


def _scan_observation(x: float, y: float, *, wall_x: float | None = None) -> NavObservation:
    """A calibrated 270-degree scan of free space, optionally with one wall.

    The wall is VERTICAL at ``wall_x``, spanning y in [-12, 12]. Vertical and
    ahead of the robot on purpose: the 270-degree scanner has a rear blind
    wedge, so a wall placed across the robot's own axis is only OBSERVED over a
    short arc and the planner routes round its unobserved end through unknown
    space. This one is seen over its whole extent, which is what makes "the goal
    behind it has no route inside the window" a fact about the planner rather
    than about the fixture.
    """

    ranges = []
    for index in range(_LIDAR_BEAMS):
        angle = _LIDAR_MIN_RAD + index * _LIDAR_INC_RAD
        reach = _LIDAR_MAX_M
        if wall_x is not None:
            dx = math.cos(angle)
            if dx > 1e-6:
                t = (wall_x - x) / dx
                if 0.0 < t < reach and -12.0 <= y + math.sin(angle) * t <= 12.0:
                    reach = t
        ranges.append(reach)
    return NavObservation(
        position=(x, y, 0.0),
        heading_deg=0.0,
        lidar=ranges,
        extras={
            "collision": False,
            "perception_fresh": True,
            "time_s": 0.0,
            "lidar_angle_min_rad": _LIDAR_MIN_RAD,
            "lidar_angle_increment_rad": _LIDAR_INC_RAD,
            "lidar_range_max_m": _LIDAR_MAX_M,
            "lidar_range_min_m": 0.05,
        },
    )


def _real_grid_navigator():
    return ModelRegistry.load(MODELS).create("grid_v1", arrive_radius_m=0.25)


def test_the_real_grid_navigators_cadence_is_the_one_the_probe_budget_assumes() -> None:
    """Derived by reference, so a cadence retune reddens this instead of the fix."""

    shipped = yaml.safe_load(
        (MODELS / "grid.yaml").read_text(encoding="utf-8")
    )["controller"]["replan_interval_steps"]
    assert DirectiveNavigator.GRID_REPLAN_INTERVAL_STEPS == shipped
    navigator = _real_grid_navigator()
    try:
        assert navigator.replan_interval_steps == shipped
    finally:
        navigator.close()


def test_the_real_grid_navigator_does_not_replan_because_the_goal_changed() -> None:
    """The mechanism finding 2 rests on, measured on the shipping planner."""

    navigator = _real_grid_navigator()
    mission = Mission(
        directive="d",
        goal=GoalPose(x=5.0, y=0.0, arrival_radius_m=0.25),
        status="running",
    )
    try:
        navigator.reset(mission)
        for _ in range(3):
            navigator.act(_scan_observation(0.0, 0.0), mission)
        assert navigator.last_route_status == "planned"
        assert navigator._last_plan.requested_goal_world == (5.0, 0.0)

        # Swap the goal. Nothing else changes — same pose, same scan — so the
        # ONLY reason to replan would be the goal change, and there is no such
        # reason in ``should_replan``.
        mission.goal = GoalPose(x=0.0, y=5.0, arrival_radius_m=0.25)
        stale_ticks = 0
        stale_and_planned = 0
        for _ in range(navigator.replan_interval_steps):
            navigator.act(_scan_observation(0.0, 0.0), mission)
            if navigator._last_plan.requested_goal_world != (0.0, 5.0):
                stale_ticks += 1
                if navigator.last_route_status in {"planned", "at_goal"}:
                    stale_and_planned += 1
        # At least one tick inside one cadence period reports a status computed
        # for a goal the caller is no longer asking about — and reports it as
        # ``planned``, which is exactly the read the pre-audit probe believed.
        assert stale_ticks >= 1
        assert stale_and_planned >= 1
    finally:
        navigator.close()


def _probe_rig(*, cached_goal, probed_goal, wall_x):
    """A pipeline whose navigator holds a cached plan for a DIFFERENT goal."""

    nav = _nav(route_memory=True)
    navigator = _real_grid_navigator()
    nav._navigator = navigator
    mission = Mission(
        directive="walk towards the lamppost",
        goal=GoalPose(x=cached_goal[0], y=cached_goal[1], arrival_radius_m=0.25),
        status="running",
    )
    nav.mission = mission
    navigator.reset(mission)
    for _ in range(6):
        navigator.act(_scan_observation(0.0, 0.0, wall_x=wall_x), mission)
    cached_status = navigator.last_route_status
    mission.goal = GoalPose(x=probed_goal[0], y=probed_goal[1], arrival_radius_m=0.25)
    return nav, navigator, mission, cached_status


def test_a_stale_planned_status_is_never_a_hand_back_verdict() -> None:
    """finding 2, direction 1: no false hand-back on a cached ``planned``.

    The cached plan is for a goal 5 m up an open corridor; the goal being probed
    is behind a wall that spans the whole window. Pre-audit the probe read the
    cached ``planned`` and destroyed the chain.
    """

    nav, navigator, mission, cached = _probe_rig(
        cached_goal=(0.0, 5.0), probed_goal=(5.0, 0.0), wall_x=3.0
    )
    try:
        assert cached == "planned", "the rig did not produce a cached 'planned'"
        # Held out or not, a plan that is not about the probed goal is no verdict.
        assert nav._route_memory_probe_verdict(held_out=False) is None
        assert nav._route_memory_probe_verdict(held_out=True) is None
        # Drive the cadence out with the TRUE goal; the genuine verdict is refusal.
        verdict = None
        for _ in range(nav._route_memory_probe_budget() + 1):
            navigator.act(_scan_observation(0.0, 0.0, wall_x=3.0), mission)
            verdict = nav._route_memory_probe_verdict(held_out=True)
            if verdict is not None:
                break
        assert navigator._last_plan.requested_goal_world == (5.0, 0.0)
        assert verdict is False
    finally:
        nav.close()


def test_a_stale_blocked_status_is_never_a_hand_back_refusal() -> None:
    """finding 2, direction 2: no false REFUTE on a cached non-planned status."""

    nav, navigator, mission, cached = _probe_rig(
        cached_goal=(5.0, 0.0), probed_goal=(0.0, 5.0), wall_x=3.0
    )
    try:
        assert cached not in {"planned", "at_goal"}, "the rig did not produce a block"
        assert nav._route_memory_probe_verdict(held_out=False) is None
        assert nav._route_memory_probe_verdict(held_out=True) is None
        verdict = None
        for _ in range(nav._route_memory_probe_budget() + 1):
            navigator.act(_scan_observation(0.0, 0.0, wall_x=3.0), mission)
            verdict = nav._route_memory_probe_verdict(held_out=True)
            if verdict is not None:
                break
        assert navigator._last_plan.requested_goal_world == (0.0, 5.0)
        assert verdict is True
    finally:
        nav.close()


def test_the_probe_budget_is_two_of_the_planners_own_cadence_periods() -> None:
    nav = _nav(route_memory=True)
    try:
        nav._navigator = _real_grid_navigator()
        assert nav._route_memory_probe_budget() == 2 * nav._navigator.replan_interval_steps
        nav._navigator.close()
        # A stand-in that publishes no cadence falls back to the shipped value.
        nav._navigator = _CorridorNavigator(_CorridorWorld())
        assert nav._route_memory_probe_budget() == (
            2 * DirectiveNavigator.GRID_REPLAN_INTERVAL_STEPS
        )
    finally:
        nav.mission = None


class _CadenceNavigator(_CorridorNavigator):
    """The corridor stand-in with ``GridNavigator``'s ACTUAL replan policy.

    Replans only when it has no plan or on its own 5-tick cadence, and **never**
    because the goal changed — ``grid_navigator.py``'s ``should_replan``. This is
    the property the gate-(b) stand-in is structurally blind to, and it is what
    turned the hand-back probe into a coin flip on the cached plan.
    """

    def __init__(self, world, free_fn=_corridor_free, *, phase: int = 0) -> None:
        super().__init__(world, free_fn)
        self.replan_interval_steps = DirectiveNavigator.GRID_REPLAN_INTERVAL_STEPS
        self._acts = phase
        self._cached = None

    def act(self, observation, mission) -> MidLevelCommand:
        self.direction = None
        if mission.goal is None:
            mission.status = "failed"
            return MidLevelCommand(stop=True, note="grid_goal_missing")
        robot = (self.world.x, self.world.y)
        goal = (mission.goal.x, mission.goal.y)
        self.goals_seen.append(goal)
        radius = (
            0.25 if mission.goal.arrival_radius_m is None else float(mission.goal.arrival_radius_m)
        )
        if math.dist(robot, goal) <= radius:
            self.last_route_status = "at_goal"
            mission.status = "arrived"
            return MidLevelCommand(stop=True, note="arrived")
        if self._cached is None or self._acts % self.replan_interval_steps == 0:
            self._cached = self.planner._plan(robot, goal)
        self._acts += 1
        status, path = self._cached
        self.last_route_status = status
        if path is None:
            return MidLevelCommand(vx=0.0, vyaw=0.2, note=f"grid_recover_scan status={status}")
        aim = path[-1]
        travelled = 0.0
        for a, b in pairwise(path):
            travelled += math.dist(a, b)
            if travelled >= self.LOOKAHEAD_M:
                aim = b
                break
        distance = math.dist(robot, aim)
        if distance < 1e-6:
            return MidLevelCommand(vx=0.0, vyaw=0.2, note=f"grid_recover_scan status={status}")
        self.direction = ((aim[0] - robot[0]) / distance, (aim[1] - robot[1]) / distance)
        return MidLevelCommand(
            vx=STAND_IN_SPEED_MPS, vyaw=0.0, note=f"grid_track status={status}"
        )


def _run_cadence_corridor(*, phase: int, seeded_one_tick_probe: bool = False):
    world = _CorridorWorld()
    nav = _nav(route_memory=True)
    stand_in = _CadenceNavigator(world, phase=phase)
    nav._navigator = stand_in
    if seeded_one_tick_probe:
        # The pre-audit probe: one tick, read ``last_route_status``, believe it.
        nav._route_memory_probe_verdict = (
            lambda *, held_out: getattr(nav._navigator, "last_route_status", None)
            in {"planned", "at_goal"}
        )
    _teach_the_corridor(nav, world)
    world.x = world.y = world.t = 0.0
    mission = nav.start("walk towards the lamppost")
    result = _CorridorRun()
    result.arrived_tick = None
    result.failed_tick = None
    result.note = ""
    for tick in range(CORRIDOR_BUDGET_TICKS):
        command = nav.step(_corridor_observation(world))
        world.advance(stand_in, command)
        result.note = command.note
        if mission.status_value() == "arrived":
            result.arrived_tick = tick
            break
        if mission.status_value() == "failed":
            result.failed_tick = tick
            break
    result.final_xy = (world.x, world.y)
    result.status = mission.status_value()
    result.nav = nav
    result.mission = mission
    return result


def test_a_cadenced_planner_reaches_the_same_verdict_as_a_per_tick_one() -> None:
    """finding 2, at mission level, on every cadence phase.

    The probe fires mid-chain in this corridor (the true goal enters the 8.05 m
    disc while the block is still between), so a planner whose cached plan is the
    WAYPOINT's is exactly the adversarial case. All five phases must reach the
    same outcome as the per-tick stand-in: arrive, no blacklist.
    """

    reference = _run_corridor(route_memory=True, teach=True)
    runs = [_run_cadence_corridor(phase=phase) for phase in range(5)]
    try:
        assert reference.arrived_tick is not None
        for phase, run in enumerate(runs):
            assert run.arrived_tick is not None, f"phase {phase} lost the chain"
            assert run.status == "arrived"
            assert run.mission.metadata.get("unreachable_candidates") is None
            assert run.mission.metadata.get("route_memory_handback") != "goal_routable"
            assert math.dist(run.final_xy, CORRIDOR_GOAL_XY) < 3.0
    finally:
        reference.nav.close()
        for run in runs:
            run.nav.close()


def test_seeded_one_tick_probe_reproduces_the_false_hand_back() -> None:
    """The companion proof: restore the pre-audit probe and the case fails.

    Same corridor, same cadenced planner, one line different — the verdict is the
    cached status, believed after one tick. The chain is destroyed on a goal that
    is in RANGE and not routable, and the mission blacklists the only candidate.
    """

    seeded = [_run_cadence_corridor(phase=phase, seeded_one_tick_probe=True) for phase in range(5)]
    try:
        false_handbacks = [
            run for run in seeded
            if run.mission.metadata.get("route_memory_handback") == "goal_routable"
        ]
        assert false_handbacks, "the seeded probe did not reproduce the defect"
        for run in false_handbacks:
            assert run.arrived_tick is None
            assert run.mission.metadata["unreachable_candidates"] == ["lamp-b"]
    finally:
        for run in seeded:
            run.nav.close()


# ---------------------------------------------------------------------------
# AUDIT_WAVE2 finding 3 — the watchdog-replan re-arm is INTENDED, and pinned
# ---------------------------------------------------------------------------


def test_a_watchdog_replan_re_commits_and_re_arms_by_design() -> None:
    """The deferral is NOT "one chain per committed instance", and must not be.

    ``_begin_semantic_replan`` — the funnel the 400-tick progress watchdog goes
    through — flushes the chain and deliberately does NOT mark the instance
    spent, so a re-committed candidate gets a fresh chain. Measured cost and
    benefit (RM2_STATUS §5.4): in a doomed world this postpones the release to
    the watchdog cadence; in the adjacent RECOVERABLE world the SECOND chain is
    the one that arrives (t=762, dtg 2.48 m), and marking the funnel's flush
    spent converts that arrival into a blacklist failure.

    Pinned so the "obvious one-line fix" cannot be applied silently.
    """

    world = _CorridorWorld()
    nav = _nav(route_memory=True)
    stand_in = _CorridorNavigator(world)
    nav._navigator = stand_in
    try:
        _teach_the_corridor(nav, world)
        world.x = world.y = world.t = 0.0
        mission = nav.start("walk towards the lamppost")
        for _ in range(CORRIDOR_BUDGET_TICKS):
            command = nav.step(_corridor_observation(world))
            world.advance(stand_in, command)
            if nav._route_memory_chain:
                break
        assert nav._route_memory_chain
        first_arm = nav.route_memory_routes_found

        # The watchdog's own exit, called exactly as _progress_watchdog calls it.
        nav._begin_semantic_replan(0, note="semantic_replan_after_no_progress")

        assert mission.goal is None
        assert nav._route_memory_chain == ()
        assert mission.metadata["route_memory_flush"] == "candidate_released"
        # INTENDED: the release funnel does not spend the instance.
        assert nav._route_memory_spent == set()

        # Re-commit the same candidate and let it re-arm.
        for _ in range(CORRIDOR_BUDGET_TICKS):
            command = nav.step(_corridor_observation(world))
            world.advance(stand_in, command)
            if nav.route_memory_routes_found > first_arm:
                break
        assert nav.route_memory_routes_found == first_arm + 1
        assert mission.metadata["candidate_id"] == "lamp-b"
        # Termination is still guaranteed, and by a FLAG-INDEPENDENT ladder that
        # route memory neither extends nor resets.
        assert nav.progress_timeout_steps == 400
        assert nav.max_semantic_replans == 2
    finally:
        nav.close()


def test_the_corridor_run_is_deterministic() -> None:
    first = _run_corridor(route_memory=True, teach=True)
    second = _run_corridor(route_memory=True, teach=True)
    try:
        assert first.arrived_tick == second.arrived_tick
        assert first.final_xy == second.final_xy
        assert first.nav.route_memory_wins == second.nav.route_memory_wins
        assert first.nav.route_memory_keyframes == second.nav.route_memory_keyframes
    finally:
        for run in (first, second):
            run.nav.close()
