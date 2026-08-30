"""A committed semantic instance the planner cannot route to must be released.

Measured defect (2026-08-07, live sim, ``can you walk towards the lamppost``
from the origin): the only lamppost in the opening frustum is ``lamp_post_2``
at 7.30 m across the road; its ``towards`` approach pose lands at
(-5.60, -2.42), which sits inside the inflated LiDAR footprint of ``bldg_5``'s
north face. ``RollingGridPlanner.plan`` therefore returns ``goal_blocked``
(``no_traversable_cell_in_goal_region``) on essentially every tick, and
``GridNavigator``'s only answer to that is ``_recovery_command`` — which at the
shipping ``recovery_reverse_steps=0`` is pure in-place yaw. The robot span for
120 s and moved 0.00 m; the progress watchdog's replans re-grounded the *same*
instance and re-derived the *same* unroutable pose, three times, until the
mission failed ``navigation_no_progress``.

``goal_blocked`` is a *proof* of unroutability, not a slow-progress heuristic,
so the mission releases the commitment, remembers that instance as unreachable
for this mission only, and hands back to the resolution ladder — the
``alternate_candidate`` / ``rescan`` vocabulary the NavigateTo contract already
carries. These cases pin the release, the exclusion, and the two ways it must
NOT fire.

**2026-08-07, card F-1/F-3c — the same release now has three authorities**, and
they share one exit (``_release_unreachable_candidate``):

1. **A-star** — ``goal_blocked`` / ``no_path`` (the original, above);
2. **the obstacle gate** — ``_gate_blocked_route_recovery``. The global planner
   inflates obstacles by 0.42 m while the collision gate hard-stops at 0.8 m
   footprint-to-surface, so a corridor between those numbers is *routable and
   impassable*. Measured live ("sit next to the lamppost", static city): the
   route reported ``planned`` while the body sat at exactly 0.800 m from
   ``obstacle_bollard`` with ``vx=0`` for 190 ticks, until the watchdog failed
   the mission and its replan re-derived the identical route;
3. **the approach solver** — ``safe_approach_pose`` returning ``None``, which
   used to fail the whole mission on a fact about one instance.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from parcel_robot.navigation.base import MidLevelCommand, NavObservation
from parcel_robot.navigation.grounder import PlaceGrounder
from parcel_robot.navigation.pipeline import DirectiveNavigator
from parcel_robot.navigation.registry import ModelRegistry

MODELS = REPO / "configs" / "navigation" / "models"


class _RouteStatusNavigator:
    """Navigator stand-in whose global-plan status the test controls.

    Mirrors the surface ``DirectiveNavigator`` actually consults: ``act`` /
    ``reset`` / ``close`` plus the ``last_route_status`` property
    ``GridNavigator`` exposes. It never claims arrival, so every tick reaching
    it is a tick the mission is trying and failing to move.
    """

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


def _nav() -> DirectiveNavigator:
    return DirectiveNavigator(
        registry=ModelRegistry.load(MODELS),
        grounder=PlaceGrounder([]),
        model_id="stub_v0",
        arrive_radius_m=0.25,
    )


def _lamppost(
    candidate_id: str, x: float, y: float, *, distance_m: float
) -> dict[str, object]:
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


def _observation(*candidates: str, position=(0.0, 0.0, 0.0)) -> NavObservation:
    table = {
        # The blocked one: far, and the only thing visible at first.
        "far": _lamppost("lamp-far", -6.7, -2.9, distance_m=7.3),
        # The alternate the look-around finds.
        "near": _lamppost("lamp-near", 0.2, 3.15, distance_m=3.16),
    }
    rows = [table[name] for name in candidates]
    return NavObservation(
        position=position,
        heading_deg=0.0,
        extras={
            "collision": False,
            "perception_fresh": True,
            "semantic_candidates": [row[0] for row in rows],
            "lidar_obstacles": [row[1] for row in rows],
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


def _next_to_lamppost_observation() -> NavObservation:
    """The near lamppost with its scene-derived 0.06 m footprint."""

    observation = _observation("near")
    extras = dict(observation.extras)
    candidates = []
    for raw in extras["semantic_candidates"]:
        candidate = dict(raw)
        candidate["metadata"] = {
            **candidate["metadata"],
            "radius_m": 0.06,
            "arrival_radius_m": 0.06,
        }
        candidates.append(candidate)
    extras["semantic_candidates"] = candidates
    return NavObservation(
        position=observation.position,
        heading_deg=observation.heading_deg,
        extras=extras,
    )


def _commit(nav: DirectiveNavigator, observation: NavObservation, *, budget: int = 8):
    for _ in range(budget):
        nav.step(observation)
        if nav.mission is not None and nav.mission.goal is not None:
            return
    raise AssertionError("semantic goal never committed")


def test_unroutable_committed_goal_is_released_after_a_bounded_wait():
    nav = _nav()
    mission = nav.start("walk towards the lamppost")
    _commit(nav, _observation("far"))
    assert mission.metadata["candidate_id"] == "lamp-far"
    nav._navigator = _RouteStatusNavigator()

    # One tick short of the bound the commitment still stands: an unroutable
    # tick is evidence, and the release waits for enough of it.
    for _ in range(DirectiveNavigator.UNROUTABLE_GOAL_STEPS - 1):
        nav.step(_observation("far"))
    assert mission.goal is not None
    assert mission.metadata["resolution_state"] == "resolved"

    released = nav.step(_observation("far"))

    assert mission.goal is None
    assert mission.status == "searching"
    assert released.note == "semantic_replan_after_unroutable_goal"
    assert mission.metadata["resolution_state"] == "semantic_replan_after_unroutable_goal"
    assert mission.metadata["unreachable_candidates"] == ["lamp-far"]
    assert mission.metadata["unroutable_route_status"] == "goal_blocked"
    # Still far short of the progress watchdog, so the ladder keeps its budget.
    assert mission.metadata["replan_count"] == 1
    assert DirectiveNavigator.UNROUTABLE_GOAL_STEPS < nav.progress_timeout_steps
    nav.close()


def test_the_released_instance_is_excluded_and_the_alternate_is_committed():
    """The whole point: rescan, then commit the alternate.

    ``lamp-far`` stays in the frustum for the rest of the run. Without the
    exclusion the ladder re-grounds it immediately (or, with both visible,
    dead-ends on AMBIGUOUS); with it, only ``lamp-near`` is groundable and the
    mission commits that instead.
    """

    nav = _nav()
    mission = nav.start("walk towards the lamppost")
    _commit(nav, _observation("far"))
    nav._navigator = _RouteStatusNavigator()
    for _ in range(DirectiveNavigator.UNROUTABLE_GOAL_STEPS):
        nav.step(_observation("far"))
    assert mission.goal is None

    _commit(nav, _observation("far", "near"), budget=16)

    assert mission.metadata["candidate_id"] == "lamp-near"
    assert mission.goal is not None
    assert mission.goal.poi_id == "lamp-near"
    nav.close()


def test_an_unroutable_tick_while_closing_the_gap_is_a_detour_not_a_dead_goal():
    """Progress resets the evidence: a bounded detour must not release."""

    nav = _nav()
    mission = nav.start("walk towards the lamppost")
    _commit(nav, _observation("far"))
    goal = mission.goal
    assert goal is not None
    nav._navigator = _RouteStatusNavigator()

    # Walk the robot towards the goal one step at a time. Every tick reports
    # goal_blocked, and every tick also closes the gap.
    start = nav._best_goal_distance_m
    assert start is not None
    for index in range(DirectiveNavigator.UNROUTABLE_GOAL_STEPS * 2):
        fraction = 0.002 * (index + 1)
        nav.step(
            _observation(
                "far",
                position=(goal.x * fraction, goal.y * fraction, 0.0),
            )
        )
        assert mission.goal is not None, f"released on tick {index} despite progress"
    assert nav._best_goal_distance_m < start
    assert "unreachable_candidates" not in mission.metadata
    nav.close()


def test_a_navigator_without_a_route_status_never_triggers_the_release():
    """Fail-safe: models that publish no plan status keep the old behaviour."""

    nav = _nav()
    mission = nav.start("walk towards the lamppost")
    _commit(nav, _observation("far"))
    nav._navigator = _RouteStatusNavigator(status=None)

    for _ in range(DirectiveNavigator.UNROUTABLE_GOAL_STEPS * 2):
        nav.step(_observation("far"))

    assert mission.goal is not None
    assert "unreachable_candidates" not in mission.metadata
    nav.close()


class _DrivingNavigator:
    """Navigator stand-in that always asks to drive forward, route ``planned``.

    The gate-blocked case is precisely the one where the *planner* is content:
    ``last_route_status`` stays ``"planned"`` throughout, so the A* release can
    never fire and only the brake's verdict is left as evidence.
    """

    def __init__(self) -> None:
        self.last_route_status = "planned"
        self.resets = 0

    def reset(self, mission) -> None:
        self.resets += 1
        mission.status = "running"

    def act(self, observation, mission) -> MidLevelCommand:
        return MidLevelCommand(vx=0.6, vyaw=0.0, note="grid_track status=planned")

    def close(self) -> None:
        return None


def _blocked_observation(*candidates: str, obstacle_m: float | None = 0.4) -> NavObservation:
    """A frustum view plus a non-target surface inside the hard-stop boundary.

    The extra return goes into ``lidar_obstacles``, because that is the list
    ``_control_observation`` re-derives ``nearest_obstacle_m`` from — writing
    the scalar directly would be overwritten. ``bearing_rad=0.5`` points
    nowhere near ``lamp-far`` (which bears -2.73 rad from the origin), so the
    geometric target exemption does not swallow it: this is a *different* body,
    exactly as the bollard is.
    """

    observation = _observation(*candidates)
    extras = dict(observation.extras)
    rows = list(extras.get("lidar_obstacles") or ())
    if obstacle_m is not None:
        rows.append({"id": "bollard", "distance_m": obstacle_m, "bearing_rad": 0.5})
    extras["lidar_obstacles"] = rows
    return NavObservation(
        position=observation.position,
        heading_deg=observation.heading_deg,
        extras=extras,
    )


def _terminal_pose_blocked_observation(
    observation: NavObservation,
    goal,
    *,
    hard_stop_gate: bool,
) -> NavObservation:
    """Add a newly observed surface at the committed terminal pose.

    LiDAR ranges are footprint-to-surface while the approach solver projects a
    world point after adding the Go2 radius.  The first row therefore lands
    exactly on ``goal`` and forces the existing solver to choose another point
    in the same K0 region.  The optional closer row supplies the independent
    obstacle-gate proof that triggers the live lamppost recovery path.
    """

    extras = dict(observation.extras)
    rows = list(extras.get("lidar_obstacles") or ())
    rows.append(
        {
            "id": "late-terminal-blocker",
            "distance_m": math.hypot(goal.x, goal.y) - 0.32,
            "bearing_rad": math.atan2(goal.y, goal.x),
        }
    )
    if hard_stop_gate:
        rows.append(
            {
                "id": "gate-stop-witness",
                "distance_m": 0.4,
                "bearing_rad": -1.0,
            }
        )
    extras["lidar_obstacles"] = rows
    return NavObservation(
        position=observation.position,
        heading_deg=observation.heading_deg,
        nearest_person_m=observation.nearest_person_m,
        extras=extras,
    )


def test_a_route_the_obstacle_gate_will_not_execute_is_released():
    nav = _nav()
    mission = nav.start("walk towards the lamppost")
    _commit(nav, _observation("far"))
    assert mission.metadata["candidate_id"] == "lamp-far"
    nav._navigator = _DrivingNavigator()

    for _ in range(DirectiveNavigator.GATE_BLOCKED_ROUTE_STEPS):
        command = nav.step(_blocked_observation("far"))
        # The gate is believed, not bypassed: translation is zero every tick.
        assert command.vx == 0.0
    assert mission.goal is not None, "released before the bound"

    released = nav.step(_blocked_observation("far"))

    assert mission.goal is None
    assert mission.status == "searching"
    assert released.note == "semantic_replan_after_blocked_route"
    assert mission.metadata["unreachable_candidates"] == ["lamp-far"]
    assert mission.metadata["blocked_route_gate"] == "obstacle_stop"
    assert mission.metadata["replan_count"] == 1
    assert DirectiveNavigator.GATE_BLOCKED_ROUTE_STEPS < nav.progress_timeout_steps
    nav.close()


def test_first_blocked_candidate_advances_the_instance_ladder_before_pose_retry():
    """Candidate diversity precedes pose diversity in the bounded ladder."""

    nav = _nav()
    mission = nav.start("sit next to the lamppost")
    observation = _next_to_lamppost_observation()
    _commit(nav, observation)
    nav._navigator = _RouteStatusNavigator()

    for _ in range(DirectiveNavigator.UNROUTABLE_GOAL_STEPS):
        released = nav.step(observation)

    assert released.note == "semantic_replan_after_unroutable_goal"
    assert mission.goal is None
    assert mission.metadata["unreachable_candidates"] == ["lamp-near"]
    assert mission.metadata["terminal_pose_replan_refusal"] == (
        "candidate_alternative_not_yet_tried"
    )
    assert "terminal_pose_replan_attempts" not in mission.metadata
    nav.close()


def test_gate_blocked_terminal_pose_replans_the_same_candidate_inside_the_same_k0_region():
    """A blocked pose is not proof that the whole lamppost is unreachable."""

    nav = _nav()
    mission = nav.start("sit next to the lamppost")
    clear = _next_to_lamppost_observation()
    _commit(nav, clear)
    nav._unreachable_candidates.add("lamp-prior")
    mission.metadata["unreachable_candidates"] = ["lamp-prior"]
    old_goal = mission.goal
    assert old_goal is not None
    old_region = mission.metadata["arrival_goal_region"]
    blocked = _terminal_pose_blocked_observation(
        clear,
        old_goal,
        hard_stop_gate=True,
    )
    driver = _DrivingNavigator()
    nav._navigator = driver

    for _ in range(DirectiveNavigator.GATE_BLOCKED_ROUTE_STEPS):
        command = nav.step(blocked)
        assert command.vx == 0.0  # the gate remains authoritative throughout
    assert mission.goal == old_goal

    replanned = nav.step(blocked)

    new_goal = mission.goal
    assert new_goal is not None
    assert replanned.note == "semantic_terminal_pose_replanned_after_obstacle_stop"
    assert mission.metadata["candidate_id"] == "lamp-near"
    assert new_goal.poi_id == old_goal.poi_id == "lamp-near"
    assert mission.metadata["arrival_goal_region"] == old_region
    assert nav._arrival_goal_region().contains(new_goal.x, new_goal.y)
    assert math.hypot(new_goal.x - old_goal.x, new_goal.y - old_goal.y) >= (
        DirectiveNavigator.GATE_HOLD_DISPLACEMENT_M
    )
    assert mission.metadata["terminal_pose_replan_attempts"] == 1
    assert mission.metadata["terminal_pose_replan_count"] == 1
    assert mission.metadata["unreachable_candidates"] == ["lamp-prior"]
    assert driver.resets == 1
    nav.close()


def test_no_distinct_terminal_pose_preserves_the_fail_closed_release():
    """One unchanged re-solve cannot defer the existing blacklist path."""

    nav = _nav()
    mission = nav.start("sit next to the lamppost")
    observation = _next_to_lamppost_observation()
    _commit(nav, observation)
    nav._unreachable_candidates.add("lamp-prior")
    mission.metadata["unreachable_candidates"] = ["lamp-prior"]
    old_goal = mission.goal
    assert old_goal is not None
    nav._navigator = _RouteStatusNavigator()

    for _ in range(DirectiveNavigator.UNROUTABLE_GOAL_STEPS - 1):
        nav.step(observation)
    released = nav.step(observation)

    assert released.note == "semantic_replan_after_unroutable_goal"
    assert mission.goal is None
    assert mission.status == "searching"
    assert mission.metadata["unreachable_candidates"] == ["lamp-near", "lamp-prior"]
    assert mission.metadata["terminal_pose_replan_attempts"] == 1
    assert mission.metadata["terminal_pose_replan_refusal"] == "pose_unchanged"
    assert "terminal_pose_replan_count" not in mission.metadata
    nav.close()


def test_terminal_pose_retry_refuses_changed_candidate_geometry() -> None:
    """An exact object ID cannot splice refreshed geometry into an old K0 proof."""

    nav = _nav()
    mission = nav.start("sit next to the lamppost")
    clear = _next_to_lamppost_observation()
    _commit(nav, clear)
    nav._unreachable_candidates.add("lamp-prior")
    mission.metadata["unreachable_candidates"] = ["lamp-prior"]

    extras = dict(clear.extras)
    changed_candidates = []
    for raw in extras["semantic_candidates"]:
        changed = dict(raw)
        changed["metadata"] = {**changed["metadata"], "radius_m": 0.20}
        changed_candidates.append(changed)
    extras["semantic_candidates"] = changed_candidates
    changed_observation = NavObservation(
        position=clear.position,
        heading_deg=clear.heading_deg,
        extras=extras,
    )

    assert (
        nav._retry_committed_terminal_pose(changed_observation, trigger="test_geometry_drift")
        is None
    )
    assert mission.metadata["terminal_pose_replan_refusal"] == "candidate_geometry_changed"
    assert mission.metadata["terminal_pose_replan_attempts"] == 1
    assert "terminal_pose_replan_count" not in mission.metadata
    nav.close()


def test_a_clear_gate_never_releases_however_long_the_mission_runs():
    """Only a *stop* is evidence. A clear (or merely slowed) tick is not."""

    nav = _nav()
    mission = nav.start("walk towards the lamppost")
    _commit(nav, _observation("far"))
    nav._navigator = _DrivingNavigator()

    for _ in range(DirectiveNavigator.GATE_BLOCKED_ROUTE_STEPS * 2):
        nav.step(_blocked_observation("far", obstacle_m=None))

    assert mission.goal is not None
    assert "unreachable_candidates" not in mission.metadata
    nav.close()


def test_yielding_to_a_person_is_never_evidence_that_a_route_is_impassable():
    """``person_stop`` is the gate doing its job; releasing on it would make the
    robot abandon its goal every time somebody walked past it."""

    nav = _nav()
    mission = nav.start("walk towards the lamppost")
    _commit(nav, _observation("far"))
    nav._navigator = _DrivingNavigator()

    base = _observation("far")
    person_view = NavObservation(
        position=base.position,
        heading_deg=base.heading_deg,
        nearest_person_m=0.3,
        extras=dict(base.extras),
    )
    for _ in range(DirectiveNavigator.GATE_BLOCKED_ROUTE_STEPS * 2):
        command = nav.step(person_view)
        assert command.vx == 0.0  # the person gate really is stopping it

    assert mission.goal is not None
    assert "unreachable_candidates" not in mission.metadata
    nav.close()


def test_no_admissible_approach_pose_releases_the_instance_instead_of_the_mission():
    """F-3c: ``safe_approach_pose`` returning ``None`` is a fact about ONE
    instance. Failing the mission on it threw away a directive the robot could
    still satisfy at the alternate."""

    import parcel_robot.navigation.pipeline as pipeline_module

    nav = _nav()
    mission = nav.start("walk towards the lamppost")
    real = pipeline_module.safe_approach_pose
    refused: list[str] = []

    def _no_pose_for_the_far_one(goal, candidate, observation, **kwargs):
        if candidate.candidate_id == "lamp-far":
            refused.append(candidate.candidate_id)
            return None
        return real(goal, candidate, observation, **kwargs)

    pipeline_module.safe_approach_pose = _no_pose_for_the_far_one
    try:
        for _ in range(4):
            nav.step(_observation("far"))
        assert refused, "the far instance was never offered to the approach solver"
        assert mission.status != "failed", "the mission died on one instance's geometry"
        assert mission.metadata["unreachable_candidates"] == ["lamp-far"]
        assert mission.metadata["unreachable_pose_candidate"] == "lamp-far"

        _commit(nav, _observation("far", "near"), budget=16)
        assert mission.metadata["candidate_id"] == "lamp-near"
    finally:
        pipeline_module.safe_approach_pose = real
        nav.close()


def test_an_exhausted_ladder_that_released_something_says_unreachable_not_not_found():
    """The honest label: it was found, and it could not be reached."""

    nav = _nav()
    nav.start("walk towards the lamppost")
    assert nav._target_missing_command().note == "semantic_target_not_found"
    nav._unreachable_candidates.add("lamp-far")
    assert nav._target_missing_command().note == "semantic_target_unreachable"
    nav.close()


def test_grid_navigator_publishes_its_last_route_status():
    nav = ModelRegistry.load(MODELS).create("grid_v1", arrive_radius_m=0.25)
    try:
        assert nav.last_route_status is None  # nothing planned yet
    finally:
        nav.close()
