"""Card A2 (NAV-GLUE) — the three glue defects NAV-CORE measured, pinned.

Grounding: ``research/20260824/nav-core/{RESULTS.md, VERDICT.md}``, fix list
items 1-3, and the executor register ``scrum/20260824/task_2/A2_STATUS.md``.
Each case below states the measured number it exists to keep fixed.

The three:

* **fix 3 — one clearance authority.** The planner inflated 0.42 m while the
  brakes above it stopped at 0.752 m (reactive gate at cruise) and 0.80 m
  (pipeline collision brake); 8/8 sampled stalls ended inside a brake ring with
  the route still ``status=planned``. Both PRODUCTION planner sites now build
  from the ring the brake that will actually stop them enforces, converted once
  into the frame an occupancy grid inflates in.
* **fix 3.4 — brake to replan.** Both release paths counted "no progress toward
  the goal", which a detector-jittered goal resets; the witness is now the
  body's own displacement.
* **fix 1 — region/object kind tolerance.** All 12 ``bed`` episodes answered
  ``not_found`` about a place the map was holding.
* **fix 2 — off-oracle arrival.** 15/60 episodes drove to the place and wrote
  ``target_surface_unobserved``, and R3 produced a false arrival at p = 0.9922.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from parcel_robot.authority import ClearanceProfile, gate_lateral_clearance_m
from parcel_robot.navigation.base import MidLevelCommand, NavObservation
from parcel_robot.navigation.goals import semantic_goal_from_directive
from parcel_robot.navigation.grounder import PlaceGrounder
from parcel_robot.navigation.pipeline import DirectiveNavigator
from parcel_robot.navigation.reactive_safety import ReactiveSafetyPolicy
from parcel_robot.navigation.registry import ModelRegistry
from parcel_robot.navigation.semantic_map import ObservationSemanticMap

MODELS = REPO / "configs" / "navigation" / "models"

#: ``configs/robot.yaml`` ``safety.obstacle_stop_m``.
SHIPPED_RING_M = 0.65
#: ``configs/navigation/default.yaml`` ``safety.stop_distance_m`` — the brake
#: the pipeline itself applies, and the stricter of the two.
PIPELINE_BRAKE_M = 0.8


# ---------------------------------------------------------------------------
# fix 3 — ONE clearance authority, in ONE frame
# ---------------------------------------------------------------------------


def test_the_gate_ring_is_restated_in_the_frame_the_planner_inflates_in() -> None:
    """The unit correction, and why DOOR-1's number was short by a footprint.

    ``apply_reactive_safety`` compares ``obstacle_stop_m`` against
    ``SimObservation.nearest_obstacle_m`` / ``LidarObstacle.distance_m``, and
    ``simulation/mujoco_lidar.py`` builds those as
    ``signed_center_distance - robot_radius_m`` — body-SURFACE to
    obstacle-surface. A grid planner inflates occupied cells around the body
    CENTRE. So the centre-to-surface distance the gate stops at is the ring PLUS
    the footprint, and the lateral demand follows from that, not from the raw
    ring.

    The measured consequence of getting this wrong: NAV-CORE's verifier raised
    ``map_safety_margin_m`` to 0.45 (a 0.77 m inflation, still short of the
    0.885 m below) and recovered 1 of 8 sampled stalls.
    """

    profile = ClearanceProfile(obstacle_ring_m=SHIPPED_RING_M)
    assert profile.gate_range_ring_m == pytest.approx(
        SHIPPED_RING_M + profile.envelope.footprint_radius_m
    )
    assert profile.commissioned_planner_inflation_m == pytest.approx(
        gate_lateral_clearance_m(profile.gate_range_ring_m), abs=5e-7
    )
    assert profile.commissioned_planner_inflation_m == pytest.approx(0.885381, abs=5e-7)
    # ...and it is strictly the safe direction: never below the legacy term,
    # never below the pre-A2 (understated) reading it replaces.
    assert profile.commissioned_planner_inflation_m >= profile.legacy_footprint_term_m
    assert profile.commissioned_planner_inflation_m >= profile.uncapped_planner_inflation_m


def test_the_pipeline_builds_its_planner_from_its_own_brake() -> None:
    """Production site 1: the caller commissions, and it commissions with the
    brake it will itself apply.

    NAV-CORE's arm A parked at ~0.79 m of body-surface clearance with
    ``status=planned|obstacle_stop`` — the pipeline's own 0.80 m collision
    brake, a stricter authority than the runtime reactive gate's 0.65 m ring.
    A planner blind to it proposes routes this very object then refuses to
    drive.
    """

    nav = DirectiveNavigator(
        registry=ModelRegistry.load(MODELS),
        grounder=PlaceGrounder([]),
        model_id="grid_v1",
        arrive_radius_m=1.5,
    )
    try:
        expected = ClearanceProfile(obstacle_ring_m=nav.collision.obstacle_stop_m)
        config = nav._navigator._planner.config
        assert config.gate_clearance_m == pytest.approx(expected.gate_range_ring_m)
        assert config.inflation_radius_m == pytest.approx(
            expected.commissioned_planner_inflation_m
        )
        # The one-directional property: outside the gate's lateral demand is
        # merely conservative; inside it is what DOOR-1 called RED.
        assert config.inflation_radius_m + 1e-12 >= config.gate_lateral_clearance_m
    finally:
        nav.close()


def test_the_shipped_pipeline_brake_is_the_one_that_reaches_the_planner() -> None:
    """...and on the SHIPPED config that brake is 0.80 m, not the envelope floor.

    ``DirectiveNavigator()`` built by hand carries ``CollisionPolicy()``'s
    envelope floor; the product path is ``from_config``, which commissions
    ``configs/navigation/default.yaml`` ``safety.stop_distance_m``. This is the
    number NAV-CORE's arm A actually parked against.
    """

    nav = DirectiveNavigator.from_config()
    try:
        assert nav.collision.obstacle_stop_m == pytest.approx(PIPELINE_BRAKE_M)
        assert nav._planner_gate_ring_m() == pytest.approx(PIPELINE_BRAKE_M)
        config = nav._navigator._planner.config
        expected = ClearanceProfile(obstacle_ring_m=PIPELINE_BRAKE_M)
        assert config.gate_clearance_m == pytest.approx(expected.gate_range_ring_m)
        assert config.inflation_radius_m == pytest.approx(
            expected.commissioned_planner_inflation_m
        )
        # Recorded old -> new: 0.42 -> 1.0223 m of hard inflation on the
        # shipped navigation config.
        assert config.inflation_radius_m == pytest.approx(1.022296, abs=5e-7)
    finally:
        nav.close()


def test_a_stub_controller_is_never_handed_a_ring_it_would_drop() -> None:
    """The commissioning reaches models that HAVE a map, and only those.

    ``StubNavigator`` is a point-goal controller with a strict keyword
    signature and no occupancy grid. Handing it a safety-relevant number it
    would have to ignore is how such a number gets silently dropped, so the
    pipeline does not.
    """

    nav = DirectiveNavigator(
        registry=ModelRegistry.load(MODELS),
        grounder=PlaceGrounder([]),
        model_id="stub_v0",
        arrive_radius_m=1.5,
    )
    try:
        assert not hasattr(nav._navigator, "_planner")
    finally:
        nav.close()


def test_an_uncommissioned_planner_keeps_its_legacy_inflation_exactly() -> None:
    """What the re-freeze did NOT touch, which is what keeps it scoped.

    A caller that never named a gate still gets the legacy footprint term, to
    the digit, on every grid profile in the tree — including
    ``grid_clearance.yaml``'s 0.03 m hard margin, whose legacy term is 0.35 m
    and which a flat cap would have moved to 0.42 m.
    """

    registry = ModelRegistry.load(MODELS)
    checked = 0
    for model_id in sorted(registry.ids()):
        if registry.get(model_id).type != "grid":
            continue
        navigator = registry.create(model_id, arrive_radius_m=1.5)
        try:
            config = navigator._planner.config
            assert config.gate_clearance_m is not None
            assert config.inflation_radius_m == (
                config.robot_radius_m + config.effective_hard_margin_m
            )
            checked += 1
        finally:
            navigator.close()
    assert checked >= 9, f"only {checked} grid profiles walked"


def test_the_owner_search_planner_takes_the_ring_its_own_policy_enforces() -> None:
    """Production site 2, which holds the commissioned gate directly."""

    from parcel_robot.navigation.search_owner import SearchOwnerController

    policy = ReactiveSafetyPolicy()
    assert policy.planner_gate_ring_m == pytest.approx(
        SHIPPED_RING_M + policy.envelope.footprint_radius_m
    )
    controller = SearchOwnerController(safety_policy=policy)
    controller._update_map(_corridor_observation(1.20))
    assert controller._planner is not None
    assert controller._planner.config.gate_clearance_m == pytest.approx(
        policy.planner_gate_ring_m
    )


def _corridor_observation(half_width_m: float):
    """A SimObservation carrying one wall return; enough to build the map."""

    from parcel_robot.backends.base import LidarObstacle, OwnerTrack, RobotPose, SimObservation

    return SimObservation(
        timestamp=0.0,
        robot=RobotPose(x=0.0, y=0.0, z=0.0, yaw=0.0),
        owner=OwnerTrack(x=40.0, y=40.0),
        nearest_obstacle_m=half_width_m,
        nearest_obstacle_bearing_rad=math.pi / 2.0,
        lidar_obstacles=(
            LidarObstacle(
                distance_m=half_width_m, bearing_rad=math.pi / 2.0, obstacle_id="wall"
            ),
        ),
        lidar_ranges=tuple(
            [half_width_m + 0.32] * 8 + [4.0] * 8 + [half_width_m + 0.32] * 8 + [4.0] * 8
        ),
        lidar_angle_min_rad=-math.pi,
        lidar_angle_increment_rad=2.0 * math.pi / 32.0,
        lidar_range_min_m=0.05,
        lidar_range_max_m=12.0,
    )


# ---------------------------------------------------------------------------
# fix 3.4 — the release paths' witness is the BODY, not the goal
# ---------------------------------------------------------------------------


class _BlockedNavigator:
    """A navigator that reports an unroutable goal and never moves the body."""

    def __init__(self) -> None:
        self.last_route_status = "goal_blocked"

    def reset(self, mission) -> None:
        mission.status = "running"

    def act(self, observation, mission) -> MidLevelCommand:
        return MidLevelCommand(vx=0.0, vyaw=0.2, note="grid_recover_scan status=goal_blocked")

    def close(self) -> None:
        return None


def _jittering_observation(index: int) -> NavObservation:
    """The body never moves; the DETECTED target walks toward it every tick.

    This is the measured mechanism, reproduced: NAV-CORE's detector scatters the
    learned-map estimate by 0.15 m per axis, so ``_progress_watchdog``'s running
    minimum distance-to-goal keeps improving while the body stands still, and
    the counter it gates never reaches its bound. Here the goal creeps in by
    0.005 m a tick — the same effect without the randomness, and slow enough
    that it stays five metres away for the whole run, so nothing but the
    watchdog reset is being exercised.
    """

    return NavObservation(
        position=(0.0, 0.0, 0.0),
        heading_deg=0.0,
        extras={
            "collision": False,
            "perception_fresh": True,
            "semantic_candidates": [
                {
                    "id": "lamp-1",
                    "label": "lamppost",
                    "kind": "object",
                    "position": [6.0 - 0.005 * index, 0.0, 0.0],
                    "confidence": 0.98,
                    "source": "test_semantic_camera",
                    "reachable": True,
                    "metadata": {"arrival_radius_m": 0.2},
                }
            ],
            "lidar_obstacles": [
                {"id": "lamp-1", "distance_m": 6.0 - 0.005 * index, "bearing_rad": 0.0}
            ],
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


def test_a_jittering_goal_can_no_longer_starve_the_unroutable_release() -> None:
    """The silent-stall class, as a unit case.

    Before A2 this episode ran to its step limit with no typed reason:
    ``_steps_goal_unroutable`` was zeroed on every tick the goal appeared to
    come closer, which was every tick. NAV-CORE measured 778 consecutive
    ``grid_recover_scan status=goal_blocked`` ticks in one arm-A episode and
    ``_steps_gate_blocked`` peaking at FOUR against a 60-tick bound.
    """

    nav = DirectiveNavigator(
        registry=ModelRegistry.load(MODELS),
        grounder=PlaceGrounder([]),
        model_id="stub_v0",
        arrive_radius_m=0.25,
    )
    try:
        mission = nav.start("walk towards the lamppost")
        for index in range(8):
            nav.step(_jittering_observation(index))
            if mission.goal is not None:
                break
        assert mission.goal is not None
        nav._navigator = _BlockedNavigator()
        released = None
        for index in range(8, 8 + 2 * DirectiveNavigator.UNROUTABLE_GOAL_STEPS):
            released = nav.step(_jittering_observation(index))
            if mission.goal is None:
                break
        # The goal kept "closing" the whole time, so the OLD witness never fired.
        assert nav._steps_without_progress == 0
        assert nav._body_is_still is True
        assert mission.goal is None
        assert mission.metadata["unroutable_route_status"] == "goal_blocked"
        assert released.note == "semantic_replan_after_unroutable_goal"
    finally:
        nav.close()


def test_a_body_that_travels_resets_the_release_counter() -> None:
    """The other direction: unroutable WHILE moving is a detour, not a dead goal."""

    nav = DirectiveNavigator(
        registry=ModelRegistry.load(MODELS),
        grounder=PlaceGrounder([]),
        model_id="stub_v0",
        arrive_radius_m=0.25,
    )
    try:
        nav._gate_blocked_anchor_xy = (0.0, 0.0)
        moved = NavObservation(position=(0.5, 0.0, 0.0), heading_deg=0.0, extras={})
        nav._update_body_stillness(moved)
        assert nav._body_is_still is False
        # ...and a second tick at the same place is still again.
        nav._update_body_stillness(moved)
        assert nav._body_is_still is True
    finally:
        nav.close()


# ---------------------------------------------------------------------------
# fix 1 — region/object kind tolerance, strict-first
# ---------------------------------------------------------------------------


def _learned_row(label: str, x: float, y: float, kind: str = "object") -> dict:
    return {
        "id": f"place-{label}",
        "label": label,
        "kind": kind,
        "position": [x, y, 0.0],
        "confidence": 0.9,
        "source": "online_map",
        "reachable": True,
        "metadata": {"semantic_source": "learned_map", "aliases": [label]},
    }


def _candidates_observation(rows: list[dict]) -> NavObservation:
    return NavObservation(
        position=(0.0, 0.0, 0.0),
        heading_deg=0.0,
        extras={"semantic_candidates": rows, "perception_fresh": True},
    )


def test_a_region_goal_now_resolves_against_the_learned_maps_object_rows() -> None:
    """PORTS ``test_navcore_probe.test_the_learned_map_cannot_answer_a_region_class_goal``.

    The two facts that disagreed are BOTH still true — the grammar classes
    "bed" as a region, the learned-map ingress stamps ``object`` — and the join
    between them no longer requires them to be the same word. All 12 ``bed``
    episodes answered ``not_found`` before this.
    """

    goal = semantic_goal_from_directive("bed")
    assert goal.kind == "region"
    resolved = ObservationSemanticMap().query(
        goal, _candidates_observation([_learned_row("bed", 2.0, 0.0)])
    )
    assert [item.candidate_id for item in resolved] == ["place-bed"]


def test_the_kind_relaxation_never_fires_while_a_same_kind_row_exists() -> None:
    """Strict-first is what makes fix 1 additive: no oracle row can move.

    Where the goal's own kind is present the answer is exactly the pre-A2 answer
    — same membership, same order — so the relaxation can only turn a
    ``not_found`` into a candidate, never re-rank a resolution that had one.
    """

    goal = semantic_goal_from_directive("bed")
    rows = [
        _learned_row("bed", 2.0, 0.0),
        _learned_row("bed", 3.0, 0.0, kind="region"),
    ]
    resolved = ObservationSemanticMap().query(goal, _candidates_observation(rows))
    assert [item.kind for item in resolved] == ["region"]


# ---------------------------------------------------------------------------
# fix 2 — off-oracle arrival: band + fresh detection, never covariance alone
# ---------------------------------------------------------------------------


def test_the_off_oracle_path_is_reserved_for_oracle_free_targets() -> None:
    """Provenance, not merely absent fields.

    The sim's own camera fixtures ship an object with no polygon and no
    ``associated_lidar_ids`` too; answering their ``near`` band from a metric
    distance would relax a live oracle check. So the candidate has to SAY it
    came from the map the dog built.
    """

    nav = DirectiveNavigator(
        registry=ModelRegistry.load(MODELS),
        grounder=PlaceGrounder([]),
        model_id="stub_v0",
    )
    try:
        assert nav._arrival_target_is_off_oracle(_learned_row("bed", 1.0, 0.0)) is True
        oracle = {
            "id": "lamp-1",
            "label": "lamppost",
            "kind": "object",
            "position": [2.0, 0.0, 0.0],
            "confidence": 0.98,
            "source": "test_semantic_camera",
            "metadata": {"aliases": ["street light"]},
        }
        assert nav._arrival_target_is_off_oracle(oracle) is False
    finally:
        nav.close()


def test_an_off_oracle_arrival_is_refused_on_confidence_alone() -> None:
    """NAV-CORE refuter R3, as a product pin.

    R3 declared arrival at ``p = 0.9922`` with the body 0.534 m from the goal
    against a 0.5 m band, because the chance constraint was reading a covariance
    nothing has calibrated (H7's missed L5/NEES row). Nothing on this path may
    VERIFY from a probability — only refuse — so a body OUTSIDE the committed
    band is refused however confident the localiser is, and the refusal is
    typed.
    """

    nav = DirectiveNavigator(
        registry=ModelRegistry.load(MODELS),
        grounder=PlaceGrounder([]),
        model_id="stub_v0",
    )
    try:
        mission = nav.start("go to the bed")
        mission.metadata.update(
            {
                "candidate_position": (0.0, 0.0, 0.0),
                "vicinity_radius_m": 0.5,
                "minimum_vicinity_radius_m": 0.0,
            }
        )

        class _Pose:
            x = 0.534
            y = 0.0

        assert (
            nav._off_oracle_arrival_verified(_Pose(), _learned_row("bed", 0.0, 0.0), "inside")
            is False
        )
        assert (
            mission.metadata["arrival_not_verified_reason"]
            == "outside_off_oracle_arrival_band"
        )
        # ...and inside the band, with this tick's detection in hand, it is a
        # verified arrival — the band is the mission's own, not a new number.
        class _Inside:
            x = 0.2
            y = 0.0

        assert (
            nav._off_oracle_arrival_verified(_Inside(), _learned_row("bed", 0.0, 0.0), "inside")
            is True
        )
        assert mission.metadata["arrival_verified_by"] == "off_oracle_band_and_resight"
        assert "arrival_not_verified_reason" not in mission.metadata
    finally:
        nav.close()
