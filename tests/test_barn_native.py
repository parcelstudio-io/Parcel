from __future__ import annotations

import math
from itertools import pairwise
from pathlib import Path

import numpy as np
import pytest

from evals.external.barn_native import (
    BARN_NATIVE_EVALUATION_KIND,
    BARN_PUBLIC_WORLD_INDICES,
    DEFAULT_LIDAR_MAX_RANGE_M,
    DEFAULT_LIDAR_RAY_COUNT,
    OFFICIAL_GOAL_XY,
    OFFICIAL_START_HEADING_RAD,
    OFFICIAL_START_XY,
    BarnAction,
    BarnNativeConfig,
    BarnNativeRunner,
    BarnObservation,
    BarnWorld,
    CylinderObstacle,
    barn_navigation_metric,
    cast_lidar,
    load_barn_world,
    parse_sdf_cylinders,
    path_coord_to_world,
    reference_path_length_m,
)


def _write_world(path: Path, *, cylinder_pose: str = "5 5 0 0 0 0") -> None:
    path.write_text(
        f"""\
<sdf version="1.6">
  <world name="default">
    <model name="obstacle">
      <pose>{cylinder_pose}</pose>
      <link name="link">
        <collision name="body">
          <geometry><cylinder><radius>0.25</radius><length>1</length></cylinder></geometry>
        </collision>
        <visual name="ignored_visual">
          <geometry><cylinder><radius>9</radius><length>1</length></cylinder></geometry>
        </visual>
      </link>
    </model>
    <state world_name="default">
      <model name="obstacle"><pose>99 99 0 0 0 0</pose></model>
    </state>
  </world>
</sdf>
""",
        encoding="utf-8",
    )


def _world(
    cylinders: tuple[CylinderObstacle, ...] = (),
    *,
    path_length_m: float = 10.0,
) -> BarnWorld:
    return BarnWorld(
        world_index=0,
        cylinders=cylinders,
        reference_path_grid=((0.0, 0.0),),
        reference_path_world=(path_coord_to_world(0.0, 0.0),),
        optimal_path_length_m=path_length_m,
    )


class _StraightPolicy:
    def __init__(self, speed: float = 1.0) -> None:
        self.speed = speed
        self.reset_args: tuple[tuple[float, float], float, tuple[float, float]] | None = None
        self.observations: list[BarnObservation] = []

    def reset(
        self,
        start_xy: tuple[float, float],
        heading_rad: float,
        goal_xy: tuple[float, float],
    ) -> None:
        self.reset_args = (start_xy, heading_rad, goal_xy)
        self.observations = []

    def act(self, observation: BarnObservation) -> BarnAction:
        self.observations.append(observation)
        return BarnAction(vx_mps=self.speed, yaw_rate_rps=0.0, note="sensor-only")


def test_public_world_split_is_the_pinned_evenly_spaced_set() -> None:
    assert BARN_PUBLIC_WORLD_INDICES == tuple(range(0, 300, 6))
    assert len(BARN_PUBLIC_WORLD_INDICES) == 50
    assert BARN_PUBLIC_WORLD_INDICES[0] == 0
    assert BARN_PUBLIC_WORLD_INDICES[-1] == 294


def test_native_lidar_defaults_match_pinned_jackal_melodic_ray_model() -> None:
    assert DEFAULT_LIDAR_RAY_COUNT == 720
    assert DEFAULT_LIDAR_MAX_RANGE_M == pytest.approx(30.0)


def test_path_coordinate_conversion_matches_pinned_evaluator() -> None:
    assert path_coord_to_world(0, 0) == pytest.approx((-4.575, 5.075))
    assert path_coord_to_world(29, 29) == pytest.approx((-0.225, 9.425))

    grid_path = ((0.0, 0.0), (1.0, 0.0))
    expected_points = [
        OFFICIAL_START_XY,
        (-4.575, 5.075),
        (-4.425, 5.075),
        OFFICIAL_GOAL_XY,
    ]
    expected_length = sum(math.dist(first, second) for first, second in pairwise(expected_points))
    assert reference_path_length_m(grid_path) == pytest.approx(expected_length)


def test_navigation_metric_matches_official_clip_formula() -> None:
    # path=20m -> OT=10s.  The official lower clip makes the maximum score 0.5.
    assert barn_navigation_metric(True, 1.0, 20.0) == pytest.approx(0.5)
    assert barn_navigation_metric(True, 40.0, 20.0) == pytest.approx(0.25)
    assert barn_navigation_metric(True, 1_000.0, 20.0) == pytest.approx(0.125)
    assert barn_navigation_metric(False, 40.0, 20.0) == 0.0


def test_parse_cylinders_composes_sdf_poses_and_ignores_visual_and_state(tmp_path: Path) -> None:
    world_path = tmp_path / "world.world"
    world_path.write_text(
        """\
<sdf version="1.6"><world name="default">
  <model name="m"><pose>1 2 0 0 0 1.5707963267948966</pose>
    <link name="l"><pose>1 0 0 0 0 0</pose>
      <collision name="c"><pose>0.5 0 0 0 0 0</pose><geometry>
        <cylinder><radius>0.2</radius><length>1</length></cylinder>
      </geometry></collision>
      <visual name="v"><geometry><cylinder><radius>8</radius><length>1</length></cylinder></geometry></visual>
    </link>
  </model>
  <state world_name="default"><model name="m"><pose>99 99 0 0 0 0</pose></model></state>
</world></sdf>
""",
        encoding="utf-8",
    )

    cylinders = parse_sdf_cylinders(world_path)
    assert len(cylinders) == 1
    assert cylinders[0].center_xy == pytest.approx((1.0, 3.5))
    assert cylinders[0].radius_m == pytest.approx(0.2)
    assert cylinders[0].source_name == "m/l/c"


def test_load_world_reads_official_folder_shape_and_path(tmp_path: Path) -> None:
    world_dir = tmp_path / "world_files"
    path_dir = tmp_path / "path_files"
    world_dir.mkdir()
    path_dir.mkdir()
    _write_world(world_dir / "world_6.world")
    np.save(path_dir / "path_6.npy", np.asarray([[0, 0], [1, 2]], dtype=np.int64))

    world = load_barn_world(tmp_path, 6)

    assert world.world_index == 6
    assert len(world.cylinders) == 1
    assert world.reference_path_grid == ((0.0, 0.0), (1.0, 2.0))
    assert np.asarray(world.reference_path_world) == pytest.approx(
        np.asarray((path_coord_to_world(0, 0), path_coord_to_world(1, 2)))
    )
    assert world.optimal_path_length_m == pytest.approx(
        reference_path_length_m(world.reference_path_grid)
    )


def test_lidar_casts_to_collision_surface_without_world_leakage() -> None:
    obstacle = CylinderObstacle(center_xy=(2.0, 0.0), radius_m=0.5)
    ranges = cast_lidar(
        (0.0, 0.0),
        0.0,
        (obstacle,),
        angle_min_rad=-math.pi / 2,
        angle_max_rad=math.pi / 2,
        ray_count=3,
        max_range_m=10.0,
    )
    assert ranges == pytest.approx((10.0, 1.5, 10.0))


def test_native_runner_is_sensor_only_deterministic_and_non_official() -> None:
    config = BarnNativeConfig(lidar_ray_count=9)
    policy = _StraightPolicy(speed=1.0)

    first = BarnNativeRunner(_world(path_length_m=10.0), config).run(policy)
    first_observations = tuple(policy.observations)
    second = BarnNativeRunner(_world(path_length_m=10.0), config).run(policy)

    assert first == second
    assert first.success is True
    assert first.status == "succeeded"
    assert first.elapsed_time_s == pytest.approx(9.0)
    assert first.final_position_xy[1] >= 12.0
    assert first.evaluation_kind == BARN_NATIVE_EVALUATION_KIND
    assert first.official_gazebo_score is False
    assert policy.reset_args == (
        OFFICIAL_START_XY,
        OFFICIAL_START_HEADING_RAD,
        OFFICIAL_GOAL_XY,
    )
    assert first_observations
    assert all(isinstance(observation, BarnObservation) for observation in first_observations)
    assert all(len(observation.lidar_ranges_m) == 9 for observation in first_observations)


def test_collision_is_terminal_and_does_not_slide() -> None:
    obstacle = CylinderObstacle(center_xy=(-2.25, 4.0), radius_m=0.2)
    config = BarnNativeConfig(robot_radius_m=0.2, lidar_ray_count=9)
    result = BarnNativeRunner(_world((obstacle,)), config).run(_StraightPolicy(speed=2.0))

    assert result.success is False
    assert result.collided is True
    assert result.status == "collided"
    assert result.navigation_metric == 0.0
    assert result.final_position_xy[0] == pytest.approx(OFFICIAL_START_XY[0])
    assert result.final_position_xy[1] < 3.6


def test_stop_outside_goal_fails_without_being_reported_as_timeout() -> None:
    class StopPolicy(_StraightPolicy):
        def act(self, observation: BarnObservation) -> BarnAction:
            return BarnAction(0.0, 0.0, stop=True, note="done")

    result = BarnNativeRunner(_world(), BarnNativeConfig(lidar_ray_count=3)).run(StopPolicy())

    assert result.status == "stopped_outside_goal"
    assert result.stopped is True
    assert result.timed_out is False
    assert result.success is False
    assert result.last_action_note == "done"


def test_timeout_executes_exactly_one_thousand_official_ticks() -> None:
    class IdlePolicy(_StraightPolicy):
        def act(self, observation: BarnObservation) -> BarnAction:
            return BarnAction(0.0, 0.0)

    result = BarnNativeRunner(_world(), BarnNativeConfig(lidar_ray_count=3)).run(IdlePolicy())

    assert result.status == "timeout"
    assert result.timed_out is True
    assert result.elapsed_time_s == 100.0
    assert result.steps == 1_000
