from __future__ import annotations

import math

import pytest

from evals.external.barn_native import (
    BarnNativeConfig,
    BarnNativeRunner,
    BarnObservation,
    BarnWorld,
)
from evals.external.parcel_barn_adapter import ParcelBarnAdapter
from parcel_robot.navigation.base import MidLevelCommand, Mission, NavObservation


class _FakeController:
    def __init__(self) -> None:
        self.mission: Mission | None = None
        self.observations: list[NavObservation] = []
        self.command = MidLevelCommand(vx=0.4, vy=0.0, vyaw=0.2, note="fake")

    def start(self, directive: str | Mission) -> Mission:
        assert isinstance(directive, Mission)
        self.mission = directive
        directive.status = "running"
        return directive

    def step(self, observation: NavObservation) -> MidLevelCommand:
        self.observations.append(observation)
        return self.command

    def done(self) -> bool:
        return self.mission is None or self.mission.status == "arrived"

    def close(self) -> None:
        self.mission = None


def _observation(ranges: tuple[float, ...], *, x: float = 0.0) -> BarnObservation:
    return BarnObservation(
        position_xy=(x, 0.0),
        heading_rad=0.0,
        lidar_ranges_m=ranges,
        lidar_angle_min_rad=-0.4,
        lidar_angle_increment_rad=0.2,
        time_s=1.0,
    )


def test_adapter_injects_metric_goal_without_language_or_world_oracle() -> None:
    controller = _FakeController()
    adapter = ParcelBarnAdapter(controller)

    adapter.reset((1.0, 2.0), math.pi / 2, (3.0, 4.0))

    assert controller.mission is not None and controller.mission.goal is not None
    assert controller.mission.directive == "BARN metric goal"
    assert (controller.mission.goal.x, controller.mission.goal.y) == (3.0, 4.0)
    assert controller.mission.goal.arrival_radius_m == pytest.approx(0.75)
    assert "world" not in controller.mission.metadata
    assert "path" not in controller.mission.metadata


def test_adapter_derives_stable_obstacle_tracks_from_scan_only() -> None:
    controller = _FakeController()
    adapter = ParcelBarnAdapter(controller)
    adapter.reset((0.0, 0.0), 0.0, (5.0, 0.0))

    first = adapter.act(_observation((10.0, 2.0, 1.9, 10.0, 3.0)))
    second = adapter.act(_observation((10.0, 2.1, 2.0, 10.0, 2.9), x=0.05))

    assert (first.vx_mps, first.yaw_rate_rps, first.stop) == pytest.approx((0.4, 0.2, False))
    assert second.note == "fake"
    first_tracks = controller.observations[0].extras["lidar_obstacles"]
    second_tracks = controller.observations[1].extras["lidar_obstacles"]
    assert len(first_tracks) == 2
    assert [item["id"] for item in first_tracks] == [item["id"] for item in second_tracks]
    assert controller.observations[0].nearest_obstacle_m == pytest.approx(1.9)
    assert controller.observations[0].extras["lidar_angle_min_rad"] == pytest.approx(-0.4)
    assert controller.observations[0].extras["lidar_angle_increment_rad"] == pytest.approx(0.2)
    assert controller.observations[0].extras["lidar_range_max_m"] == pytest.approx(10.0)
    assert controller.observations[0].extras["lidar_timestamp_s"] == pytest.approx(1.0)
    assert controller.observations[0].extras["odometry_timestamp_s"] == pytest.approx(1.0)
    assert controller.observations[0].extras["lidar_fresh"] is True
    assert controller.observations[0].extras["odometry_fresh"] is True
    latency = adapter.latency_metrics()
    assert latency["adapter_act_count"] == 2.0
    assert latency["controller_step_count"] == 2.0
    assert latency["adapter_act_p99_ms"] >= latency["controller_step_p50_ms"]
    diagnostics = adapter.policy_diagnostics()
    assert diagnostics["controller_phase_counts"] == {"fake": 2}
    assert diagnostics["safety_phase_counts"] == {"<none>": 2}
    assert diagnostics["policy_owned_only"] is True


def test_unchanged_parcel_controller_achieves_open_world_native_baseline() -> None:
    world = BarnWorld(
        world_index=0,
        cylinders=(),
        reference_path_grid=((0.0, 0.0),),
        reference_path_world=((-4.575, 5.075),),
        optimal_path_length_m=10.0,
    )
    adapter = ParcelBarnAdapter()
    try:
        result = BarnNativeRunner(world, BarnNativeConfig(lidar_ray_count=31)).run(adapter)
    finally:
        adapter.close()

    assert result.success is True
    assert result.collided is False
    assert result.navigation_metric > 0.0
