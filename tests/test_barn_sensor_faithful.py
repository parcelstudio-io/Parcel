from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest

from evals.external.barn_native import (
    OFFICIAL_START_XY,
    BarnAction,
    BarnObservation,
    BarnWorld,
    CylinderObstacle,
    load_barn_world,
)
from evals.external.barn_policy_specs import BarnPolicySpec
from evals.external.barn_ros2_adapter import (
    BARN_ROS2_BASE_FRAME_ID,
    BARN_ROS2_LIDAR_CALIBRATION,
    BARN_ROS2_LIDAR_FRAME_ID,
    BarnRos2SensorFrame,
    normalize_planar_lidar_frame,
)
from evals.external.barn_sensor_faithful import (
    CALIBRATED_LIDAR_FORWARD_M,
    CALIBRATED_LIDAR_FOV_DEG,
    CALIBRATED_LIDAR_RANGE_MAX_M,
    CALIBRATED_LIDAR_RANGE_MIN_M,
    CALIBRATED_LIDAR_RAY_COUNT,
    CALIBRATED_POLICY_INPUTS,
    CALIBRATED_START_HEADING_RAD,
    CalibratedBarnConfig,
    SensorFaithfulBarnRunner,
    _laser_scan_float32,
    calibrated_policy_spec,
    calibrated_reference_config_spec,
    cast_sensor_faithful_lidar,
    run_sensor_faithful_comparison,
    run_sensor_faithful_suite,
    world_pose_to_odom,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
BARN_CACHE = (
    REPO_ROOT
    / ".cache"
    / "external-evals"
    / "repos"
    / "barn_challenge"
    / "jackal_helper"
    / "worlds"
    / "BARN"
)
BARN_GRID_REFERENCE_CONFIG = (
    REPO_ROOT / "configs" / "navigation" / "experiments" / "barn_grid_v1.yaml"
)


class _RecordingPolicy:
    def __init__(self, actions: list[BarnAction]) -> None:
        self.actions = list(actions)
        self.resets: list[tuple[tuple[float, float], float, tuple[float, float]]] = []
        self.observations: list[BarnObservation] = []
        self.closed = False

    def reset(
        self,
        start_xy: tuple[float, float],
        heading_rad: float,
        goal_xy: tuple[float, float],
    ) -> None:
        self.resets.append((start_xy, heading_rad, goal_xy))

    def act(self, observation: BarnObservation) -> BarnAction:
        self.observations.append(observation)
        return self.actions[min(len(self.observations) - 1, len(self.actions) - 1)]

    def close(self) -> None:
        self.closed = True


def _world(*cylinders: CylinderObstacle) -> BarnWorld:
    return BarnWorld(
        world_index=0,
        cylinders=tuple(cylinders),
        reference_path_grid=((15.0, 0.0), (15.0, 29.0)),
        reference_path_world=((-2.25, 5.075), (-2.25, 9.425)),
        optimal_path_length_m=10.0,
    )


def _assets(root: Path) -> None:
    (root / "path_files").mkdir(parents=True)
    (root / "world_0.world").write_text(
        '<sdf version="1.6"><world name="default"/></sdf>\n',
        encoding="utf-8",
    )
    np.save(root / "path_files" / "path_0.npy", np.asarray([[15, 0], [15, 29]]))


def _spec(
    policy_id: str,
    action: BarnAction,
    *,
    experimental: bool,
    seeds: list[int] | None = None,
) -> BarnPolicySpec:
    def factory(seed: int) -> _RecordingPolicy:
        if seeds is not None:
            seeds.append(seed)
        return _RecordingPolicy([action])

    return BarnPolicySpec(
        policy_id=policy_id,
        description=f"test policy {policy_id}",
        agent_id="test-policy",
        adapter_id="test-sensor-adapter",
        model_id="none",
        factory=factory,
        experimental=experimental,
    )


def _normalize_raw_scan(raw: tuple[float, ...]):
    frame = BarnRos2SensorFrame(
        stamp_s=1.0,
        position_xy=(0.0, 0.0),
        heading_rad=0.0,
        lidar_ranges_m=raw,
        lidar_angle_min_rad=-math.pi,
        lidar_angle_increment_rad=2.0 * math.pi / (CALIBRATED_LIDAR_RAY_COUNT - 1),
        lidar_range_min_m=CALIBRATED_LIDAR_RANGE_MIN_M,
        lidar_range_max_m=CALIBRATED_LIDAR_RANGE_MAX_M,
        odometry_stamp_s=0.995,
        lidar_frame_id=BARN_ROS2_LIDAR_FRAME_ID,
        odometry_child_frame_id=BARN_ROS2_BASE_FRAME_ID,
    )
    return normalize_planar_lidar_frame(frame, BARN_ROS2_LIDAR_CALIBRATION)


def test_calibrated_profile_and_world_to_odom_are_exact() -> None:
    config = CalibratedBarnConfig()

    assert CALIBRATED_LIDAR_FOV_DEG == 360.0
    assert CALIBRATED_LIDAR_RAY_COUNT == 720
    assert CALIBRATED_LIDAR_FORWARD_M == pytest.approx(0.12)
    assert CALIBRATED_LIDAR_RANGE_MIN_M == pytest.approx(0.05)
    assert CALIBRATED_LIDAR_RANGE_MAX_M == pytest.approx(25.0)
    assert config.lidar_angle_min_rad == pytest.approx(-math.pi)
    assert config.lidar_angle_max_rad == pytest.approx(math.pi)
    assert config.odometry_lag_s == pytest.approx(0.005)
    assert config.trial_start_translation_m == pytest.approx(0.1)

    start_odom, start_heading = world_pose_to_odom(
        OFFICIAL_START_XY,
        CALIBRATED_START_HEADING_RAD,
    )
    goal_odom, goal_heading = world_pose_to_odom(
        (-2.25, 13.0),
        CALIBRATED_START_HEADING_RAD,
    )
    left_world, _ = world_pose_to_odom(
        (-1.25, 3.0),
        CALIBRATED_START_HEADING_RAD,
    )

    assert start_odom == pytest.approx((0.0, 0.0), abs=1e-12)
    assert start_heading == pytest.approx(0.0)
    assert goal_odom == pytest.approx(
        (
            10.0 * math.sin(CALIBRATED_START_HEADING_RAD),
            10.0 * math.cos(CALIBRATED_START_HEADING_RAD),
        ),
        abs=1e-12,
    )
    assert goal_heading == pytest.approx(0.0)
    assert left_world == pytest.approx(
        (
            math.cos(CALIBRATED_START_HEADING_RAD),
            -math.sin(CALIBRATED_START_HEADING_RAD),
        ),
        abs=1e-12,
    )


def test_analytic_self_circle_is_sensor_only_and_exact_core_masks_it() -> None:
    raw = cast_sensor_faithful_lidar(
        OFFICIAL_START_XY,
        CALIBRATED_START_HEADING_RAD,
        (),
    )
    normalized = _normalize_raw_scan(raw)

    assert len(raw) == 720
    assert sum(math.isfinite(value) for value in raw) == 100
    assert min(value for value in raw if math.isfinite(value)) == pytest.approx(0.07)
    assert normalized.diagnostics.input_ray_count == 720
    assert normalized.diagnostics.output_ray_count == 720
    assert normalized.diagnostics.finite_hit_count == 100
    assert normalized.diagnostics.self_return_count == 100
    assert normalized.diagnostics.reprojected_hit_count == 0
    assert sum(math.isnan(value) for value in normalized.ranges_m) > 0

    # The self circle must not become collision geometry.
    policy = _RecordingPolicy([BarnAction(0.1, 0.0, note="straight")])
    result = SensorFaithfulBarnRunner(
        _world(),
        CalibratedBarnConfig(timeout_s=0.1),
    ).run(policy)
    assert result.collided is False
    assert result.trial_started is True
    assert result.traveled_distance_m == pytest.approx(0.11)


def test_official_timer_starts_after_point_one_meter_of_startup_motion() -> None:
    policy = _RecordingPolicy([BarnAction(1.0, 0.0, note="straight")])

    result = SensorFaithfulBarnRunner(
        _world(),
        CalibratedBarnConfig(dt_s=0.1, timeout_s=0.2),
    ).run(policy)

    assert result.trial_started is True
    assert result.startup_time_s == pytest.approx(0.1)
    assert result.elapsed_time_s == pytest.approx(0.2)
    assert result.simulation_elapsed_time_s == pytest.approx(0.3)
    assert result.steps == 3
    assert result.status == "timeout"
    assert result.traveled_distance_m == pytest.approx(0.3)


def test_replay_uses_lagged_pose_and_float32_laserscan_fields() -> None:
    policy = _RecordingPolicy([BarnAction(1.0, 0.0, note="straight")])

    SensorFaithfulBarnRunner(
        _world(CylinderObstacle((-2.25, 5.0), 0.10, "visible")),
        CalibratedBarnConfig(dt_s=0.1, timeout_s=0.1),
    ).run(policy)

    assert len(policy.observations) == 2
    second = policy.observations[1]
    assert second.position_xy == pytest.approx((0.095, 0.0), abs=1e-12)
    assert second.lidar_angle_min_rad == float(np.float32(-math.pi))
    assert second.lidar_angle_increment_rad == float(
        np.float32(2.0 * math.pi / (CALIBRATED_LIDAR_RAY_COUNT - 1))
    )
    finite_ranges = [value for value in second.lidar_ranges_m if math.isfinite(value)]
    assert finite_ranges
    assert _laser_scan_float32(1.234567890123) == float(np.float32(1.234567890123))


def test_external_forward_hit_survives_transform_and_self_mask() -> None:
    # Body-forward is world +y at the official start.  The sensor is at +0.12
    # and the obstacle's near surface is 0.28 m from the sensor / 0.40 m base.
    obstacle = CylinderObstacle((-2.25, 3.5), 0.10, "external")
    raw = cast_sensor_faithful_lidar(
        OFFICIAL_START_XY,
        CALIBRATED_START_HEADING_RAD,
        (obstacle,),
    )
    normalized = _normalize_raw_scan(raw)
    external_hits = [value for value in normalized.ranges_m if math.isfinite(value)]

    assert normalized.diagnostics.self_return_count == 100
    assert normalized.diagnostics.reprojected_hit_count > 0
    assert min(external_hits) == pytest.approx(0.40, abs=0.01)


def test_runner_uses_ideal_unicycle_arc_and_collision_terminal_dynamics() -> None:
    curved_policy = _RecordingPolicy([BarnAction(1.0, 1.0, note="arc")])
    curved = SensorFaithfulBarnRunner(
        _world(),
        CalibratedBarnConfig(dt_s=1.0, timeout_s=1.0),
    ).run(curved_policy)
    startup_crossing_s = 2.0 * math.asin(0.05)
    total_motion_s = startup_crossing_s + 1.0
    expected = (
        OFFICIAL_START_XY[0]
        + math.sin(CALIBRATED_START_HEADING_RAD + total_motion_s)
        - math.sin(CALIBRATED_START_HEADING_RAD),
        OFFICIAL_START_XY[1]
        + math.cos(CALIBRATED_START_HEADING_RAD)
        - math.cos(CALIBRATED_START_HEADING_RAD + total_motion_s),
    )

    assert curved.final_position_xy == pytest.approx(expected)
    assert curved.final_heading_rad == pytest.approx(
        (CALIBRATED_START_HEADING_RAD + total_motion_s + math.pi) % (2.0 * math.pi) - math.pi
    )
    assert curved_policy.resets == [((0.0, 0.0), 0.0, (10.0, 0.0))]
    assert curved_policy.closed is True
    assert not hasattr(curved_policy.observations[0], "cylinders")
    assert not hasattr(curved_policy.observations[0], "reference_path_world")

    collision_policy = _RecordingPolicy([BarnAction(1.0, 0.0, note="straight")])
    collision = SensorFaithfulBarnRunner(
        _world(CylinderObstacle((-2.25, 3.70), 0.10, "blocking")),
        CalibratedBarnConfig(dt_s=1.0, timeout_s=1.0),
    ).run(collision_policy)

    assert collision.collided is True
    assert collision.status == "collided"
    assert collision.final_position_xy == pytest.approx(OFFICIAL_START_XY)
    assert collision.evaluator_diagnostics.minimum_signed_obstacle_clearance_m <= 0.0


def test_minimum_clearance_includes_the_swept_path_between_tick_endpoints() -> None:
    # Both endpoints clear this obstacle by about 0.575 m, but the path passes
    # it at 0.44 m. The safety floor must use the swept value, not endpoints.
    obstacle = CylinderObstacle((-1.39, 3.5), 0.10, "mid_tick_pass_by")
    policy = _RecordingPolicy([BarnAction(1.0, 0.0, note="straight")])

    result = SensorFaithfulBarnRunner(
        _world(obstacle),
        CalibratedBarnConfig(dt_s=1.0, timeout_s=1.0),
    ).run(policy)

    endpoint_clearance = math.hypot(0.86, 0.5) - 0.32 - 0.10
    assert endpoint_clearance > 0.45
    assert result.collided is False
    assert result.evaluator_diagnostics.minimum_signed_obstacle_clearance_m == pytest.approx(
        0.44,
        abs=5e-4,
    )


def test_policy_stop_latches_zero_until_timeout_instead_of_ending_episode() -> None:
    policy = _RecordingPolicy([BarnAction(0.4, 0.2, stop=True, note="policy_done")])
    result = SensorFaithfulBarnRunner(
        _world(),
        CalibratedBarnConfig(dt_s=0.1, timeout_s=0.3, startup_timeout_s=0.3),
    ).run(policy)

    assert result.success is False
    assert result.stopped is True
    assert result.timed_out is True
    assert result.status == "startup_timeout"
    assert result.startup_timed_out is True
    assert result.trial_started is False
    assert result.elapsed_time_s == pytest.approx(0.0)
    assert result.simulation_elapsed_time_s == pytest.approx(0.3)
    assert result.steps == 3
    assert result.traveled_distance_m == 0.0
    assert len(policy.observations) == 1
    assert result.shield_stall_diagnostics.policy_stop_latch_step == 0
    assert result.sensor_diagnostics.policy_observation_steps == (0,)
    assert result.sensor_diagnostics.published_action_steps == (0, 1, 2)
    assert all(
        value[1:3] == (0.0, 0.0) for value in result.sensor_diagnostics.published_action_values
    )


def test_shield_stall_diagnostic_uses_nonterminal_obstacle_stop_contract() -> None:
    policy = _RecordingPolicy(
        [BarnAction(0.0, 0.4, stop=False, note="grid_track turn|obstacle_stop")]
    )
    result = SensorFaithfulBarnRunner(
        _world(),
        CalibratedBarnConfig(dt_s=0.1, timeout_s=0.6, startup_timeout_s=0.6),
    ).run(policy)
    shield = result.shield_stall_diagnostics

    assert shield.obstacle_stop_steps == 6
    assert shield.max_consecutive_obstacle_stop_steps == 6
    assert shield.turn_only_command_steps == 6
    assert shield.reverse_command_steps == 0
    assert shield.safety_phase_counts == {"obstacle_stop": 6}


def test_calibrated_metadata_relabels_legacy_lidar_and_preserves_provenance() -> None:
    spec = calibrated_reference_config_spec(
        BARN_GRID_REFERENCE_CONFIG,
        reference_id="calibrated-grid-reference-test",
        description="calibrated metadata test",
    )
    metadata = spec.report_metadata()

    assert metadata["policy_inputs"] == list(CALIBRATED_POLICY_INPUTS)
    assert "270_degree_lidar" not in metadata["policy_inputs"]
    assert metadata["underlying_policy_adapter_id"]
    assert metadata["sensor_transport"]["lidar_frame_id"] == BARN_ROS2_LIDAR_FRAME_ID
    assert len(metadata["provenance"]["config"]["sha256"]) == 64
    assert len(metadata["provenance"]["model_artifact"]["sha256"]) == 64
    assert len(metadata["provenance"]["policy_source_tree"]["sha256"]) == 64
    assert len(metadata["provenance"]["calibrated_sensor_transport"]["sha256"]) == 64


def test_suite_report_is_compare_compatible_and_has_requested_diagnostics(
    tmp_path: Path,
) -> None:
    _assets(tmp_path)
    seeds: list[int] = []
    report = run_sensor_faithful_suite(
        assets_root=tmp_path,
        world_indices=(0,),
        trials=2,
        suite_seed=41,
        policy_spec=calibrated_policy_spec(
            _spec(
                "calibrated-baseline",
                BarnAction(-0.1, 0.0, note="reverse"),
                experimental=False,
                seeds=seeds,
            )
        ),
        config=CalibratedBarnConfig(timeout_s=0.1),
    )
    sensor = report["aggregate"]["sensor_diagnostics"]

    assert seeds == [41, 42]
    assert report["official_gazebo_score"] is False
    assert report["native_config"]["lidar_ray_count"] == 720
    assert report["policy"]["policy_inputs"] == list(CALIBRATED_POLICY_INPUTS)
    assert sensor["long_shield_stall_threshold_steps"] == 50
    assert sensor["long_shield_stall_episode_count"] == 0
    assert sensor["sensor_normalization_failures"] == 0
    assert sensor["reverse_command_steps"] == 22
    assert sensor["max_consecutive_obstacle_stop_steps"] == 0
    assert len(report["provenance"]["config_sha256"]) == 64
    assert len(report["provenance"]["harness"]["sha256"]) == 64
    assert len(report["episodes"][0]["sensor_diagnostics"]["policy_observation_sha256"]) == 11
    assert len(report["episodes"][0]["sensor_diagnostics"]["published_action_sha256"]) == 11
    json.dumps(report, allow_nan=False)


def test_paired_comparison_attributes_first_action_change_to_mode_on_same_observation(
    tmp_path: Path,
) -> None:
    _assets(tmp_path)
    baseline_seeds: list[int] = []
    candidate_seeds: list[int] = []
    report = run_sensor_faithful_comparison(
        assets_root=tmp_path,
        world_indices=(0,),
        trials=2,
        suite_seed=83,
        baseline_spec=_spec(
            "causal-baseline",
            BarnAction(0.1, 0.0, note="track"),
            experimental=False,
            seeds=baseline_seeds,
        ),
        candidate_spec=_spec(
            "causal-candidate",
            BarnAction(0.2, 0.0, note="track"),
            experimental=True,
            seeds=candidate_seeds,
        ),
        allow_experimental=True,
        config=CalibratedBarnConfig(timeout_s=0.1),
    )
    comparison = report["comparison"]

    assert baseline_seeds == candidate_seeds == [83, 84]
    assert comparison["same_worlds_trials_config_and_seeds"] is True
    assert comparison["paired_episode_count"] == 2
    assert comparison["mode_affected_episode_count"] == 2
    assert all(
        pair["first_published_action_divergence_step"] == 0
        and pair["first_divergence_on_identical_policy_observation"] is True
        and pair["policy_observations_identical_through_first_action_divergence"] is True
        for pair in comparison["paired_episodes"]
    )


def test_suite_supports_spawned_builtin_policy_workers(tmp_path: Path) -> None:
    _assets(tmp_path)
    spec = calibrated_reference_config_spec(
        BARN_GRID_REFERENCE_CONFIG,
        reference_id="calibrated-spawn-reference-test",
        description="spawn transport test",
    )
    report = run_sensor_faithful_suite(
        assets_root=tmp_path,
        world_indices=(0,),
        trials=2,
        suite_seed=109,
        workers=2,
        policy_spec=spec,
        config=CalibratedBarnConfig(timeout_s=0.1),
    )

    assert report["execution"]["episode_workers_effective"] == 2
    assert report["execution"]["process_start_method"] == "spawn"
    assert len(report["episodes"]) == 2
    assert all(episode["sensor_diagnostics"]["frame_count"] >= 2 for episode in report["episodes"])


def test_cached_world0_matches_live_causal_stall_signature_when_available() -> None:
    if not (BARN_CACHE / "world_0.world").is_file():
        pytest.skip("pinned BARN world cache is not present")
    if not (BARN_CACHE / "path_files" / "path_0.npy").is_file():
        pytest.skip("pinned BARN path cache is not present")

    world = load_barn_world(BARN_CACHE, 0)
    spec = calibrated_reference_config_spec(
        BARN_GRID_REFERENCE_CONFIG,
        reference_id="calibrated-world0-causal-reference",
        description="cached world-0 causal replay",
    )
    policy = spec.create(episode_seed=20260803)
    result = SensorFaithfulBarnRunner(
        world,
        CalibratedBarnConfig(timeout_s=25.0),
    ).run(policy)

    first_action = result.sensor_diagnostics.published_action_values[0]
    first_normalization = result.sensor_diagnostics.first_normalization
    assert first_normalization is not None
    assert first_normalization["input_ray_count"] == 720
    assert first_normalization["self_return_count"] == 100
    assert first_action[1] == pytest.approx(0.09, abs=1e-9)
    assert result.final_position_xy == pytest.approx((-2.62, 5.24), abs=0.15)
    assert result.shield_stall_diagnostics.max_consecutive_obstacle_stop_steps >= 50
    assert len(result.sensor_diagnostics.policy_observation_sha256) == result.steps
    assert len(result.sensor_diagnostics.published_action_sha256) == result.steps
