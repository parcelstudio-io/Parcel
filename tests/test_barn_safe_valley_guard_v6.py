from __future__ import annotations

import math
from pathlib import Path

import pytest
import yaml

from evals.external.barn_policy_specs import (
    parcel_experimental_config_spec,
    parcel_reference_config_spec,
)
from evals.external.generate_safe_valley_guard_v6_corpus import REFERENCE_CONFIG
from parcel_robot.navigation.base import GoalPose, Mission, NavObservation
from parcel_robot.navigation.grid_navigator import GridNavigator
from parcel_robot.navigation.grid_planner import LidarScan, Pose2D, RoutePlan
from parcel_robot.navigation.registry import ModelRegistry

REPO_ROOT = Path(__file__).resolve().parents[1]
MODEL_ID = "grid_safe_valley_guard_v6"
REFERENCE_MODEL_ID = "grid_safe_valley_v5"
MODEL_PATH = REPO_ROOT / "configs" / "navigation" / "models" / f"{MODEL_ID}.yaml"
REFERENCE_MODEL_PATH = (
    REPO_ROOT / "configs" / "navigation" / "models" / f"{REFERENCE_MODEL_ID}.yaml"
)
EXPERIMENT_CONFIG = (
    REPO_ROOT / "configs" / "navigation" / "experiments" / "barn_grid_safe_valley_guard_v6.yaml"
)


def _registry() -> ModelRegistry:
    return ModelRegistry.load(REPO_ROOT / "configs" / "navigation" / "models")


def _force_no_path(navigator: GridNavigator, monkeypatch: pytest.MonkeyPatch) -> None:
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


def _observation(timestamp_s: float) -> NavObservation:
    scan = (10.0,) * 361
    return NavObservation(
        position=(0.0, 0.0, 0.0),
        heading_deg=0.0,
        lidar=scan,
        extras={
            "lidar_angle_min_rad": -3.0 * math.pi / 4.0,
            "lidar_angle_increment_rad": (3.0 * math.pi / 2.0) / (len(scan) - 1),
            "lidar_range_min_m": 0.05,
            "lidar_range_max_m": 10.0,
            "lidar_timestamp_s": timestamp_s,
            "odometry_timestamp_s": timestamp_s,
            "lidar_fresh": True,
            "odometry_fresh": True,
            "perception_fresh": True,
        },
    )


def test_v6_changes_only_the_half_cell_diagonal_guard_from_v5() -> None:
    v5 = yaml.safe_load(REFERENCE_MODEL_PATH.read_text(encoding="utf-8"))
    v6 = yaml.safe_load(MODEL_PATH.read_text(encoding="utf-8"))
    v5_controller = dict(v5["controller"])
    v6_controller = dict(v6["controller"])
    guard = float(v6_controller.pop("safe_valley_discretization_guard_m"))

    assert v6_controller == v5_controller
    assert guard == pytest.approx(0.10 / math.sqrt(2.0), abs=1e-15)


def test_v6_is_opt_in_cpu_only_and_deployment_disabled() -> None:
    navigator = _registry().create(MODEL_ID, arrive_radius_m=0.5)
    assert isinstance(navigator, GridNavigator)
    assert navigator.safe_valley_micro_advance is True
    assert navigator.safe_valley_discretization_guard_m == pytest.approx(
        navigator._planner.config.resolution_m / math.sqrt(2.0)
    )
    assert navigator.recovery_reverse_steps == 0

    spec = parcel_experimental_config_spec(
        EXPERIMENT_CONFIG,
        experiment_id="barn-grid-safe-valley-guard-v6-test",
        description="v6 deployment boundary test",
    )
    metadata = spec.report_metadata()
    assert metadata["experimental"] is True
    assert metadata["deployment_enabled"] is False
    assert metadata["execution_device"] == "cpu"
    assert metadata["policy_inputs"] == ["goal", "odometry", "270_degree_lidar", "clock"]
    navigator.close()


def test_v5_arm_is_byte_identical_deployment_disabled_reference_metadata() -> None:
    spec = parcel_reference_config_spec(
        REFERENCE_CONFIG,
        reference_id="v6-v5-reference-test",
        description="immutable v5 comparison reference",
    )
    metadata = spec.report_metadata()
    assert metadata["model_id"] == REFERENCE_MODEL_ID
    assert metadata["experimental"] is False
    assert metadata["deployment_enabled"] is False
    assert metadata["production_default_behavior_modified"] is False
    assert metadata["policy_inputs"] == ["goal", "odometry", "270_degree_lidar", "clock"]


def test_v6_guard_rejects_a_raw_valley_that_v5_admits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    v5 = _registry().create(REFERENCE_MODEL_ID, arrive_radius_m=0.5)
    v6 = _registry().create(MODEL_ID, arrive_radius_m=0.5)
    assert isinstance(v5, GridNavigator)
    assert isinstance(v6, GridNavigator)
    pose = Pose2D(0.0, 0.0, 0.0)
    scan = LidarScan(
        ranges_m=(0.56,) * 361,
        angle_min_rad=-3.0 * math.pi / 4.0,
        angle_increment_rad=(3.0 * math.pi / 2.0) / 360.0,
        range_min_m=0.05,
        range_max_m=10.0,
    )
    monkeypatch.setattr(v5, "_safe_valley_distance", lambda **kwargs: kwargs["requested_m"])
    monkeypatch.setattr(v6, "_safe_valley_distance", lambda **kwargs: kwargs["requested_m"])

    assert v5._select_safe_valley(pose=pose, scan=scan, goal=(5.0, 0.0)) is not None
    assert v6._select_safe_valley(pose=pose, scan=scan, goal=(5.0, 0.0)) is None
    v5.close()
    v6.close()


def test_v6_remains_rotate_first_forward_only_and_fresh_scan_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    navigator = _registry().create(MODEL_ID, arrive_radius_m=0.5)
    assert isinstance(navigator, GridNavigator)
    mission = Mission("metric goal", GoalPose(5.0, 0.0, arrival_radius_m=0.5))
    navigator.reset(mission)
    _force_no_path(navigator, monkeypatch)

    selected = navigator.act(_observation(0.0), mission)
    advanced = navigator.act(_observation(0.1), mission)

    assert selected.note.startswith("grid_safe_valley_align")
    assert (selected.vx, selected.vy, selected.vyaw) == (0.0, 0.0, 0.0)
    assert advanced.note.startswith("grid_safe_valley_advance")
    assert 0.0 < advanced.vx <= navigator.safe_valley_advance_vx
    assert advanced.vy == 0.0
    assert advanced.vyaw == 0.0
    navigator.close()


def test_v6_guard_configuration_fails_closed_outside_bound() -> None:
    with pytest.raises(ValueError, match="discretization_guard"):
        _registry().create(
            MODEL_ID,
            arrive_radius_m=0.5,
            safe_valley_discretization_guard_m=0.21,
        )
