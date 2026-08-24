"""Stratum-1 consumers: landmark-relative goals (B-4), LOST health (B-3), chance constraint (B-5).

These drive the real :class:`DirectiveNavigator` rather than a mock, because the
claims being made are about the navigator's behavior, not about a fixture.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from parcel_robot.navigation.base import NavObservation
from parcel_robot.navigation.grounder import PlaceGrounder
from parcel_robot.navigation.pipeline import DirectiveNavigator
from parcel_robot.navigation.registry import ModelRegistry
from parcel_robot.pose import (
    POSE_PROVIDER_KEY,
    DriftingOdomProvider,
    Frame,
    PoseEstimate,
    PoseHealth,
    TruthPoseProvider,
    load_pose_config,
)

REPO = Path(__file__).resolve().parents[1]
MODELS = REPO / "configs" / "navigation" / "models"

SETTLED = {
    "fresh": True,
    "stop_confirmed": True,
    "linear_speed_mps": 0.0,
    "yaw_speed_rad_s": 0.0,
    "settled_linear_speed_mps": 0.08,
    "settled_yaw_speed_rad_s": 0.12,
}


def _bench_candidate(x: float, y: float, candidate_id: str = "bench_1") -> dict:
    return {
        "id": candidate_id,
        "label": "bench",
        "kind": "object",
        "position": [x, y, 0.0],
        "confidence": 0.98,
        "reachable": True,
        "radius_m": 0.4,
    }


def _observation(
    candidates: list[dict],
    *,
    position: tuple[float, float, float] = (0.0, 0.0, 0.0),
    heading_deg: float = 0.0,
    provider=None,
    settled: bool = False,
) -> NavObservation:
    extras: dict = {
        "collision": False,
        "perception_fresh": True,
        "semantic_candidates": candidates,
    }
    if settled:
        extras["motion_feedback"] = dict(SETTLED)
    if provider is not None:
        extras[POSE_PROVIDER_KEY] = provider
    return NavObservation(position=position, heading_deg=heading_deg, extras=extras)


def _navigator(**kwargs) -> DirectiveNavigator:
    return DirectiveNavigator(
        registry=ModelRegistry.load(MODELS),
        grounder=PlaceGrounder([]),
        **kwargs,
    )


# --------------------------------------------------------------------------
# B-4 landmark-relative goals
# --------------------------------------------------------------------------


def _committed(navigator: DirectiveNavigator, candidates: list[dict]):
    mission = navigator.start("walk to the bench")
    observation = _observation(candidates)
    navigator.step(observation)
    navigator.step(observation)
    assert mission.goal is not None, "fixture failed to commit a goal"
    return mission


def test_commit_stores_landmark_id_and_offset_alongside_the_world_goal() -> None:
    navigator = _navigator()
    mission = _committed(navigator, [_bench_candidate(3.0, 1.0)])
    metadata = mission.metadata
    assert metadata["goal_landmark_id"] == "bench_1"
    assert metadata["goal_landmark_position"] == (3.0, 1.0)
    dx, dy, heading = metadata["goal_landmark_offset"]
    # The offset re-derives the stored world goal exactly.
    assert mission.goal.x == pytest.approx(3.0 + dx)
    assert mission.goal.y == pytest.approx(1.0 + dy)
    assert heading == pytest.approx(mission.goal.heading_deg)


def test_reobserving_the_same_landmark_moved_reanchors_the_goal() -> None:
    navigator = _navigator()
    mission = _committed(navigator, [_bench_candidate(3.0, 1.0)])
    before = (mission.goal.x, mission.goal.y)
    dx, dy, _ = mission.metadata["goal_landmark_offset"]

    # The landmark is seen again 0.4 m away — a drifted frame, not a new bench.
    navigator.step(_observation([_bench_candidate(3.4, 1.3)]))

    assert mission.metadata["goal_landmark_id"] == "bench_1"
    assert mission.metadata["landmark_reanchor_count"] == 1
    assert mission.goal.x == pytest.approx(3.4 + dx)
    assert mission.goal.y == pytest.approx(1.3 + dy)
    assert (mission.goal.x, mission.goal.y) != before
    # The goal followed the landmark by exactly the landmark's displacement.
    assert mission.goal.x - before[0] == pytest.approx(0.4)
    assert mission.goal.y - before[1] == pytest.approx(0.3)


def test_an_unmoved_landmark_is_a_strict_no_op() -> None:
    """The equality guard: nothing moved, so nothing may move — not by one ULP."""

    navigator = _navigator()
    mission = _committed(navigator, [_bench_candidate(3.0, 1.0)])
    goal = mission.goal
    for _ in range(5):
        navigator.step(_observation([_bench_candidate(3.0, 1.0)]))
        assert mission.goal.x == goal.x and mission.goal.y == goal.y
    assert "landmark_reanchor_count" not in mission.metadata


def test_a_different_instance_never_switches_the_goal() -> None:
    """Re-anchor only, never re-select. Seeing bench_2 does not move bench_1's goal."""

    navigator = _navigator()
    mission = _committed(navigator, [_bench_candidate(3.0, 1.0, "bench_1")])
    goal = (mission.goal.x, mission.goal.y)
    navigator.step(
        _observation(
            [
                _bench_candidate(-4.0, -4.0, "bench_2"),
                _bench_candidate(9.0, 9.0, "bench_7"),
            ]
        )
    )
    assert (mission.goal.x, mission.goal.y) == goal
    assert mission.metadata["goal_landmark_id"] == "bench_1"
    assert "landmark_reanchor_count" not in mission.metadata


def test_world_frame_remains_the_fallback_when_no_landmark_id_exists() -> None:
    """POI goals carry no landmark id and are untouched by re-anchoring."""

    navigator = _navigator()
    mission = navigator.start("walk to the bench")
    mission.metadata.pop("goal_landmark_id", None)
    observation = _observation([_bench_candidate(3.0, 1.0)])
    navigator.step(observation)
    navigator.step(observation)
    mission.metadata.pop("goal_landmark_id", None)
    goal = (mission.goal.x, mission.goal.y)
    navigator.step(_observation([_bench_candidate(5.0, 5.0)]))
    assert (mission.goal.x, mission.goal.y) == goal


def test_reanchoring_moves_the_arrival_authority_with_the_goal() -> None:
    navigator = _navigator()
    mission = _committed(navigator, [_bench_candidate(3.0, 1.0)])
    region = mission.metadata.get("arrival_goal_region")
    assert isinstance(region, dict) and region.get("center") is not None
    center = tuple(region["center"])
    navigator.step(_observation([_bench_candidate(3.4, 1.3)]))
    moved = tuple(mission.metadata["arrival_goal_region"]["center"])
    assert moved[0] - center[0] == pytest.approx(0.4)
    assert moved[1] - center[1] == pytest.approx(0.3)


def test_reanchoring_resets_the_progress_watchdog_baseline() -> None:
    """A goal that moved is not a robot that stalled."""

    navigator = _navigator(progress_timeout_steps=10, max_semantic_replans=0)
    mission = _committed(navigator, [_bench_candidate(3.0, 1.0)])
    for _ in range(8):
        navigator.step(_observation([_bench_candidate(3.0, 1.0)]))
    assert navigator._steps_without_progress > 0
    navigator.step(_observation([_bench_candidate(3.5, 1.0)]))
    assert navigator._steps_without_progress == 0
    assert mission.status == "running"


def test_a_malformed_reobservation_is_ignored_rather_than_trusted() -> None:
    navigator = _navigator()
    mission = _committed(navigator, [_bench_candidate(3.0, 1.0)])
    goal = (mission.goal.x, mission.goal.y)
    broken = _bench_candidate(3.0, 1.0)
    broken["position"] = ["nan-ish", None]
    navigator.step(_observation([broken]))
    assert (mission.goal.x, mission.goal.y) == goal


# --------------------------------------------------------------------------
# B-3 health / LOST
# --------------------------------------------------------------------------


class _FixedHealthProvider:
    """Truth pose with a pinned health value — the smallest possible test hook."""

    def __init__(self, health: PoseHealth, x: float = 0.0, y: float = 0.0) -> None:
        self.health = health
        self.x = x
        self.y = y

    def get_pose(self, frame: Frame) -> PoseEstimate:
        return PoseEstimate(self.x, self.y, 0.0, frame, health=self.health)


def test_lost_localization_stops_and_holds_without_failing_the_mission() -> None:
    navigator = _navigator()
    mission = _committed(navigator, [_bench_candidate(3.0, 1.0)])
    provider = _FixedHealthProvider(PoseHealth.LOST)
    command = navigator.step(_observation([_bench_candidate(3.0, 1.0)], provider=provider))
    assert command.stop and command.note == "pose_lost_hold"
    assert (command.vx, command.vy, command.vyaw) == (0.0, 0.0, 0.0)
    assert mission.metadata["pose_health"] == "lost"
    assert mission.metadata["resolution_state"] == "pose_lost"
    # Held, not failed: the goal is still valid and health can return.
    assert mission.status != "failed"


def test_the_hold_releases_when_localization_recovers() -> None:
    navigator = _navigator()
    mission = _committed(navigator, [_bench_candidate(3.0, 1.0)])
    lost = _FixedHealthProvider(PoseHealth.LOST)
    assert navigator.step(_observation([_bench_candidate(3.0, 1.0)], provider=lost)).note == (
        "pose_lost_hold"
    )
    healthy = TruthPoseProvider(0.0, 0.0, 0.0)
    command = navigator.step(_observation([_bench_candidate(3.0, 1.0)], provider=healthy))
    assert command.note != "pose_lost_hold"
    assert mission.metadata["pose_health"] == "healthy"


def test_degraded_does_not_stop_the_body_but_does_block_the_arrival_claim() -> None:
    navigator = _navigator(max_semantic_replans=0)
    mission = _committed(navigator, [_bench_candidate(3.0, 1.0)])
    at_goal = (mission.goal.x, mission.goal.y, 0.0)
    provider = _FixedHealthProvider(PoseHealth.DEGRADED, at_goal[0], at_goal[1])

    moving = navigator.step(
        _observation([_bench_candidate(3.0, 1.0)], position=at_goal, provider=provider)
    )
    assert moving.note != "pose_lost_hold"  # DEGRADED never stops the body

    settled = _observation(
        [_bench_candidate(3.0, 1.0)], position=at_goal, provider=provider, settled=True
    )
    navigator.step(settled)
    navigator.step(settled)
    assert mission.metadata.get("arrival_not_verified_reason") == "pose_unhealthy"
    assert mission.metadata.get("pose_health") == "degraded"
    assert mission.status != "arrived"


def test_truth_provider_can_never_trigger_the_health_paths() -> None:
    navigator = _navigator()
    mission = _committed(navigator, [_bench_candidate(3.0, 1.0)])
    provider = TruthPoseProvider(0.0, 0.0, 0.0)
    for _ in range(10):
        command = navigator.step(
            _observation([_bench_candidate(3.0, 1.0)], provider=provider)
        )
        assert command.note != "pose_lost_hold"
    assert mission.metadata.get("arrival_not_verified_reason") is None


def test_the_drift_provider_can_be_configured_lost_from_yaml() -> None:
    provider = load_pose_config(profile="lost").build()
    assert isinstance(provider, DriftingOdomProvider)
    assert provider.get_pose(Frame.MAP).health is PoseHealth.LOST


# --------------------------------------------------------------------------
# B-5 chance-constrained inside verification, wired
# --------------------------------------------------------------------------


SIDEWALK = [[2.0, -1.0], [6.0, -1.0], [6.0, 1.0], [2.0, 1.0]]


def _region_observation(provider=None, position=(4.0, 0.0, 0.0), settled=True) -> NavObservation:
    extras: dict = {
        "collision": False,
        "perception_fresh": True,
        "semantic_candidates": [
            {
                "id": "sidewalk-test",
                "label": "sidewalk",
                "kind": "region",
                "polygon": SIDEWALK,
                "confidence": 0.99,
                "reachable": True,
            }
        ],
    }
    if settled:
        extras["motion_feedback"] = dict(SETTLED)
    if provider is not None:
        extras[POSE_PROVIDER_KEY] = provider
    return NavObservation(position=position, heading_deg=0.0, extras=extras)


#: A region ("stuff class") goal is *interchangeable*, and the 2026-08-07
#: region-instance arbitration forbids committing to the first instance that
#: confirms: with one instance in view, "which sidewalk is nearest" is not
#: answerable until the robot has looked around. `ActiveSemanticSearch.observe`
#: withholds the commit until the sweep completes, bounded by
#: `scan_budget_steps` (80). These cases are about the *pose seam* — which frame
#: each consumer reads and what the chance constraint does with it — so they
#: drive the sweep to its commit and then assert exactly what they always did.
REGION_SWEEP_BUDGET_STEPS = 80


def _region_navigator(**kwargs) -> tuple[DirectiveNavigator, object]:
    navigator = _navigator(max_semantic_replans=0, **kwargs)
    mission = navigator.start("walk to the sidewalk")
    observation = _region_observation(settled=False)
    navigator.step(observation)
    navigator.step(observation)
    return navigator, mission


def _resolve_region_goal(navigator, observation, *, budget: int = REGION_SWEEP_BUDGET_STEPS):
    """Drive the interchangeable-goal sweep to its commit, on the given pose provider."""

    for _ in range(budget):
        navigator.step(observation)
        if navigator.mission is not None and navigator.mission.goal is not None:
            return
    raise AssertionError(
        f"region goal never committed inside the {budget}-step sweep budget"
    )


def test_inside_verification_is_unchanged_at_zero_covariance() -> None:
    navigator, mission = _region_navigator()
    provider = TruthPoseProvider(4.0, 0.0, 0.0)
    _resolve_region_goal(navigator, _region_observation(provider=provider))
    for _ in range(3):
        navigator.step(_region_observation(provider=provider))
    assert mission.status == "arrived"
    # The chance constraint never engaged, so it recorded nothing.
    assert "inside_probability" not in mission.metadata


def test_a_wide_covariance_at_the_polygon_edge_refuses_the_arrival_claim() -> None:
    """The whole point of the chance constraint, in one case."""

    class _Uncertain:
        def __init__(self, sigma: float, x: float, y: float) -> None:
            self.var = sigma * sigma
            self.x = x
            self.y = y

        def get_pose(self, frame: Frame) -> PoseEstimate:
            return PoseEstimate(
                self.x,
                self.y,
                0.0,
                frame,
                covariance=(self.var, 0, 0, 0, self.var, 0, 0, 0, 0.0),
            )

    # Deep inside with a small sigma: still verified.
    navigator, mission = _region_navigator()
    deep_inside = _region_observation(provider=_Uncertain(0.02, 4.0, 0.0))
    _resolve_region_goal(navigator, deep_inside)
    for _ in range(3):
        navigator.step(deep_inside)
    assert mission.status == "arrived"
    assert mission.metadata["inside_probability"] > 0.9

    # Near the edge with a metre of sigma: the point estimate says "inside",
    # the distribution says otherwise, and K0 refuses rather than guessing.
    navigator, mission = _region_navigator()
    at_edge = _region_observation(provider=_Uncertain(1.0, 4.0, 0.6))
    _resolve_region_goal(navigator, at_edge)
    for _ in range(3):
        navigator.step(at_edge)
    assert mission.status != "arrived"
    assert mission.metadata["inside_probability"] < 0.9
    assert mission.metadata["inside_probability_threshold"] == 0.9


def test_the_threshold_comes_from_the_config_not_a_literal() -> None:
    navigator = _navigator()
    assert navigator.inside_probability_threshold == (
        load_pose_config().inside_probability_threshold
    )
    override = _navigator(inside_probability_threshold=0.5)
    assert override.inside_probability_threshold == 0.5


# --------------------------------------------------------------------------
# Frame binding, end to end through the navigator
# --------------------------------------------------------------------------


class _SplitFrames:
    """MAP and ODOM deliberately disagree, so each read reveals its binding."""

    def __init__(self, map_xy, odom_xy) -> None:
        self.map_xy = map_xy
        self.odom_xy = odom_xy
        self.seen: list[str] = []

    def get_pose(self, frame: Frame) -> PoseEstimate:
        self.seen.append(frame.value)
        xy = self.map_xy if frame is Frame.MAP else self.odom_xy
        return PoseEstimate(xy[0], xy[1], 0.0, frame)


def test_grid_v1_the_shipping_controller_reads_odom_while_k0_reads_map() -> None:
    """The frame binding is live, not decorative: both frames get consulted."""

    navigator, mission = _region_navigator(model_id="grid_v1")
    provider = _SplitFrames((4.0, 0.0), (-5.0, 0.0))
    _resolve_region_goal(navigator, _region_observation(provider=provider))
    for _ in range(3):
        navigator.step(_region_observation(provider=provider))
    assert "odom" in provider.seen, "grid_v1 short-horizon control must read ODOM"
    assert "map" in provider.seen, "K0 arrival must read MAP"
    # K0 read MAP, which is inside the sidewalk, so the arrival verified even
    # though ODOM says the robot is 9 m away.
    assert mission.status == "arrived"


def test_the_stub_controller_is_not_yet_on_the_seam() -> None:
    """Honest scope: ``stub_v0`` (the degraded point-goal fallback) is allowlisted.

    It still reads ``observation.position`` directly, so under a drifting
    provider it would keep using truth. Named here so the gap is a recorded
    fact rather than a surprise; ``test_pose_authority_archon`` holds the entry.
    """

    navigator, mission = _region_navigator(model_id="stub_v0")
    provider = _SplitFrames((4.0, 0.0), (-5.0, 0.0))
    _resolve_region_goal(navigator, _region_observation(provider=provider))
    for _ in range(3):
        navigator.step(_region_observation(provider=provider))
    assert "map" in provider.seen
    assert "odom" not in provider.seen
    assert mission.status == "arrived"


def test_drift_reaches_the_controller_and_not_the_arrival_authority() -> None:
    """T1's mechanism, isolated: ODOM carries the drift, MAP does not."""

    provider = load_pose_config(profile="calibrated_go2").build()
    provider.reset()
    stamp = 0.0
    x = 0.0
    for _ in range(150):
        x += 0.1
        stamp += 0.1
        provider.update_truth(x, 0.0, 0.0, stamp_monotonic_s=stamp)
    map_pose = provider.get_pose(Frame.MAP)
    odom_pose = provider.get_pose(Frame.ODOM)
    assert math.hypot(map_pose.x - x, map_pose.y) < 1e-9
    assert math.hypot(odom_pose.x - x, odom_pose.y) > 1e-3
    assert map_pose.is_exact and not odom_pose.is_exact
