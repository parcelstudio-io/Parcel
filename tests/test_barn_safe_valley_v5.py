from __future__ import annotations

import math
from pathlib import Path

import pytest

from evals.external.barn_policy_specs import parcel_experimental_config_spec
from parcel_robot.navigation.base import GoalPose, Mission, NavObservation
from parcel_robot.navigation.grid_navigator import GridNavigator
from parcel_robot.navigation.grid_planner import RoutePlan
from parcel_robot.navigation.registry import ModelRegistry

REPO_ROOT = Path(__file__).resolve().parents[1]
MODEL_ID = "grid_safe_valley_v5"
EXPERIMENT_CONFIG = (
    REPO_ROOT / "configs" / "navigation" / "experiments" / "barn_grid_safe_valley_v5.yaml"
)


def _navigator(monkeypatch: pytest.MonkeyPatch) -> tuple[GridNavigator, Mission]:
    registry = ModelRegistry.load(REPO_ROOT / "configs" / "navigation" / "models")
    navigator = registry.create(MODEL_ID, arrive_radius_m=0.5)
    assert isinstance(navigator, GridNavigator)
    mission = Mission("metric goal", GoalPose(5.0, 0.0, arrival_radius_m=0.5))
    navigator.reset(mission)

    def no_path(*_args: object, **_kwargs: object) -> RoutePlan:
        return RoutePlan(
            status="no_path",
            waypoints_world=(),
            requested_goal_world=(5.0, 0.0),
            planning_target_world=None,
            reaches_goal_region=False,
            expanded_nodes=1,
            path_length_m=0.0,
            unknown_cells_on_grid_path=0,
            map_generation=navigator._planner.grid.generation,
            note="test_forced_no_path",
        )

    monkeypatch.setattr(navigator._planner, "plan", no_path)
    return navigator, mission


def _observation(
    *,
    timestamp_s: float,
    x: float = 0.0,
    heading_deg: float = 0.0,
    ranges: tuple[float, ...] | None = None,
    odometry_timestamp_s: float | None = None,
) -> NavObservation:
    scan = ranges if ranges is not None else (10.0,) * 361
    return NavObservation(
        position=(x, 0.0, 0.0),
        heading_deg=heading_deg,
        lidar=scan,
        nearest_obstacle_m=None,
        extras={
            "lidar_angle_min_rad": -3.0 * math.pi / 4.0,
            "lidar_angle_increment_rad": (3.0 * math.pi / 2.0) / (len(scan) - 1),
            "lidar_range_min_m": 0.05,
            "lidar_range_max_m": 10.0,
            "lidar_timestamp_s": timestamp_s,
            "odometry_timestamp_s": (
                timestamp_s if odometry_timestamp_s is None else odometry_timestamp_s
            ),
            "lidar_fresh": True,
            "odometry_fresh": True,
            "perception_fresh": True,
        },
    )


def test_safe_valley_is_opt_in_forward_only_and_deployment_disabled() -> None:
    registry = ModelRegistry.load(REPO_ROOT / "configs" / "navigation" / "models")
    incumbent = registry.create("grid_frontier_cached_v3", arrive_radius_m=0.5)
    challenger = registry.create(MODEL_ID, arrive_radius_m=0.5)

    assert incumbent.safe_valley_micro_advance is False
    assert challenger.safe_valley_micro_advance is True
    assert challenger.safe_valley_advance_m == pytest.approx(0.40)
    assert challenger.recovery_reverse_steps == 0

    spec = parcel_experimental_config_spec(
        EXPERIMENT_CONFIG,
        experiment_id="barn-grid-safe-valley-v5-test",
        description="deployment boundary test",
    )
    metadata = spec.report_metadata()
    assert metadata["experimental"] is True
    assert metadata["deployment_enabled"] is False
    assert metadata["production_default_behavior_modified"] is False

    incumbent.close()
    challenger.close()


def test_safe_valley_holds_selection_then_advances_on_new_synchronised_frame(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    navigator, mission = _navigator(monkeypatch)

    selected = navigator.act(_observation(timestamp_s=0.0), mission)
    advanced = navigator.act(_observation(timestamp_s=0.1), mission)

    assert selected.note.startswith("grid_safe_valley_align")
    assert (selected.vx, selected.vy, selected.vyaw) == (0.0, 0.0, 0.0)
    assert advanced.note.startswith("grid_safe_valley_advance")
    assert 0.0 < advanced.vx <= navigator.safe_valley_advance_vx
    assert advanced.vy == 0.0
    assert advanced.vyaw == 0.0
    navigator.close()


def test_safe_valley_rejects_replayed_or_unsynchronised_sensor_frames(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    navigator, mission = _navigator(monkeypatch)
    navigator.act(_observation(timestamp_s=1.0), mission)
    generation_before_replay = navigator._planner.grid.generation

    replayed = navigator.act(_observation(timestamp_s=1.0), mission)
    assert replayed.note == ("grid_safe_valley_hold reason=sensor_frame_stale_or_unsynchronised")
    assert (replayed.vx, replayed.vy, replayed.vyaw, replayed.stop) == (
        0.0,
        0.0,
        0.0,
        False,
    )
    assert navigator._planner.grid.generation == generation_before_replay

    generation_before_unsynchronised = navigator._planner.grid.generation
    unsynchronised = navigator.act(
        _observation(timestamp_s=1.1, odometry_timestamp_s=1.2),
        mission,
    )
    assert "sensor_frame_stale_or_unsynchronised" in unsynchronised.note
    assert unsynchronised.vx == unsynchronised.vy == unsynchronised.vyaw == 0.0
    assert navigator._planner.grid.generation == generation_before_unsynchronised
    navigator.close()


def test_safe_valley_rejects_unobserved_or_blocked_swept_corridor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    navigator, mission = _navigator(monkeypatch)
    invalid_scan = (math.nan,) * 361

    command = navigator.act(
        _observation(timestamp_s=0.0, ranges=invalid_scan),
        mission,
    )

    assert command.note == ("grid_safe_valley_hold reason=no_fully_observed_swept_corridor")
    assert command.vx == command.vy == command.vyaw == 0.0
    assert navigator._safe_valley_maneuver is None
    navigator.close()


def test_safe_valley_never_falls_back_to_open_loop_without_calibrated_lidar(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    navigator, mission = _navigator(monkeypatch)
    generation_before = navigator._planner.grid.generation
    observation = NavObservation(
        position=(0.0, 0.0, 0.0),
        heading_deg=0.0,
        lidar=None,
        extras={
            "lidar_timestamp_s": 0.0,
            "odometry_timestamp_s": 0.0,
            "lidar_fresh": True,
            "odometry_fresh": True,
        },
    )

    command = navigator.act(observation, mission)

    assert command.note == "grid_safe_valley_hold reason=calibrated_lidar_unavailable"
    assert (command.vx, command.vy, command.vyaw, command.stop) == (0.0, 0.0, 0.0, False)
    assert navigator._planner.grid.generation == generation_before
    navigator.close()


def test_safe_valley_advance_is_odometry_bounded_and_ends_with_a_hold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    navigator, mission = _navigator(monkeypatch)
    commands = [navigator.act(_observation(timestamp_s=0.0), mission)]
    for index, x in enumerate((0.0, 0.10, 0.20, 0.30, 0.40), start=1):
        commands.append(
            navigator.act(
                _observation(timestamp_s=index / 10.0, x=x),
                mission,
            )
        )

    assert any(item.note.startswith("grid_safe_valley_advance") for item in commands)
    assert commands[-1].note.startswith("grid_safe_valley_complete")
    assert all(0.0 <= item.vx <= navigator.safe_valley_advance_vx for item in commands)
    assert all(item.vy == 0.0 for item in commands)
    assert commands[-1].vx == commands[-1].vy == commands[-1].vyaw == 0.0
    assert navigator._safe_valley_maneuver is None
    navigator.close()
