from __future__ import annotations

import math

from parcel_robot.navigation.base import GoalPose, Mission, ModelSpec, NavObservation
from parcel_robot.navigation.grid_navigator import GridNavigator
from parcel_robot.navigation.registry import ModelRegistry


def _spec() -> ModelSpec:
    return ModelSpec(id="grid_test", type="grid", version="test")


def _clear_scan_observation(*, heading_deg: float = 90.0) -> NavObservation:
    return NavObservation(
        position=(0.0, 0.0, 0.0),
        heading_deg=heading_deg,
        lidar=(30.0,) * 181,
        extras={
            "lidar_angle_min_rad": -math.pi / 2.0,
            "lidar_angle_increment_rad": math.pi / 180.0,
            "lidar_range_min_m": 0.05,
            "lidar_range_max_m": 30.0,
        },
    )


def test_grid_navigator_tracks_calibrated_scan_without_lateral_sliding() -> None:
    navigator = GridNavigator(_spec(), arrive_radius_m=0.5)
    mission = Mission("metric goal", GoalPose(0.0, 5.0, arrival_radius_m=0.5))
    navigator.reset(mission)

    command = navigator.act(_clear_scan_observation(), mission)

    assert command.vx > 0.0
    assert command.vy == 0.0
    assert command.stop is False
    assert command.note.startswith("grid_track")
    navigator.close()


def test_grid_navigator_turns_before_forward_egress_and_never_reverses() -> None:
    navigator = GridNavigator(_spec(), arrive_radius_m=0.5)
    mission = Mission("metric goal", GoalPose(3.0, 0.0, arrival_radius_m=0.5))
    navigator.reset(mission)

    # Facing west, the goal and observed-free egress are behind the body.  A
    # close return to the west inflates only the current raster cell.  The
    # controller must rotate toward the safe A* egress instead of reversing.
    command = navigator.act(
        NavObservation(
            position=(0.0, 0.0, 0.0),
            heading_deg=180.0,
            lidar=(30.0, 30.0, 0.45, 30.0, 30.0),
            extras={
                "lidar_angle_min_rad": -math.pi,
                "lidar_angle_increment_rad": math.pi / 2.0,
                "lidar_range_min_m": 0.05,
                "lidar_range_max_m": 30.0,
            },
        ),
        mission,
    )

    assert command.note.startswith("grid_align")
    assert command.vx == 0.0
    assert command.vy == 0.0
    assert command.vyaw != 0.0
    navigator.close()


def test_grid_navigator_falls_back_when_scan_calibration_is_missing() -> None:
    navigator = GridNavigator(_spec(), arrive_radius_m=0.5)
    mission = Mission("metric goal", GoalPose(0.0, 5.0, arrival_radius_m=0.5))
    navigator.reset(mission)

    command = navigator.act(
        NavObservation(position=(0.0, 0.0, 0.0), heading_deg=90.0, lidar=(30.0,) * 10),
        mission,
    )

    assert command.vy == 0.0
    assert command.note.startswith("track_goal")
    navigator.close()


def test_grid_model_is_feature_gated_in_registry() -> None:
    registry = ModelRegistry.load("configs/navigation/models")

    navigator = registry.create("grid_v1", arrive_radius_m=0.5)

    assert isinstance(navigator, GridNavigator)
    navigator.close()


def test_clearance_grid_model_is_separate_and_eval_only() -> None:
    registry = ModelRegistry.load("configs/navigation/models")

    navigator = registry.create("grid_clearance_v2", arrive_radius_m=0.5)

    assert isinstance(navigator, GridNavigator)
    assert navigator._planner.config.effective_hard_margin_m == 0.03
    assert navigator._planner.config.effective_comfort_margin_m == 0.10
    assert navigator._planner.config.comfort_cost_weight == 8.0
    navigator.close()


def test_frontier_grid_model_is_separate_and_eval_only() -> None:
    registry = ModelRegistry.load("configs/navigation/models")

    navigator = registry.create("grid_frontier_v2", arrive_radius_m=0.5)

    assert isinstance(navigator, GridNavigator)
    assert navigator._planner.config.reachable_frontier_fallback is True
    assert navigator._planner.config.frontier_band_m == 0.60
    assert navigator._planner.config.frontier_min_progress_m == 0.10
    navigator.close()


def test_cached_frontier_grid_model_is_separate_forward_only_experiment() -> None:
    registry = ModelRegistry.load("configs/navigation/models")

    navigator = registry.create("grid_frontier_cached_v3", arrive_radius_m=0.5)

    assert isinstance(navigator, GridNavigator)
    assert navigator._planner.config.reachable_frontier_fallback is True
    assert navigator._planner.config.frontier_search_mode == "observed_first"
    assert navigator.recovery_reverse_steps == 0
    mission = Mission("metric goal", GoalPose(0.0, 5.0, arrival_radius_m=0.5))
    navigator.reset(mission)
    command = navigator.act(_clear_scan_observation(), mission)
    assert command.vx >= 0.0
    assert command.vy == 0.0
    navigator.close()
