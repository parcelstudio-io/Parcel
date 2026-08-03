from __future__ import annotations

import math
from dataclasses import fields

import pytest

from evals.external.barn_native import BarnAction, BarnObservation
from evals.external.barn_ros2_adapter import (
    BARN_ROS2_COMMAND_MESSAGE,
    BARN_ROS2_FORBIDDEN_POLICY_INPUTS,
    BARN_ROS2_LIDAR_CALIBRATION,
    BARN_ROS2_LIDAR_FRAME_ID,
    BARN_ROS2_POLICY_INPUTS,
    BARN_ROS2_STATIC_GOAL_ODOM_XY,
    BarnRos2AdapterCore,
    BarnRos2SensorFrame,
    CircularSelfMask,
    PlanarLidarCalibration,
    normalize_planar_lidar_frame,
    quaternion_to_yaw,
)
from evals.external.parcel_barn_adapter import ParcelBarnAdapter


class RecordingPolicy:
    def __init__(self, actions: list[BarnAction] | None = None) -> None:
        self.actions = list(actions or [BarnAction(0.4, -0.2, note="track")])
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


def _frame(stamp_s: float = 1.0) -> BarnRos2SensorFrame:
    return BarnRos2SensorFrame(
        stamp_s=stamp_s,
        position_xy=(1.5, -0.25),
        heading_rad=0.3,
        lidar_ranges_m=(math.inf, 2.0, 1.25),
        lidar_angle_min_rad=-1.0,
        lidar_angle_increment_rad=0.5,
        lidar_range_min_m=0.1,
        lidar_range_max_m=30.0,
    )


def _calibrated_frame(
    ranges: tuple[float, ...],
    *,
    stamp_s: float = 1.0,
    angle_min_rad: float = -math.pi,
    angle_increment_rad: float | None = None,
    range_min_m: float = 0.05,
    range_max_m: float = 25.0,
) -> BarnRos2SensorFrame:
    increment = (
        2.0 * math.pi / (len(ranges) - 1) if angle_increment_rad is None else angle_increment_rad
    )
    return BarnRos2SensorFrame(
        stamp_s=stamp_s,
        position_xy=(0.0, 0.0),
        heading_rad=0.0,
        lidar_ranges_m=ranges,
        lidar_angle_min_rad=angle_min_rad,
        lidar_angle_increment_rad=increment,
        lidar_range_min_m=range_min_m,
        lidar_range_max_m=range_max_m,
        odometry_stamp_s=stamp_s - 0.01,
        lidar_frame_id=BARN_ROS2_LIDAR_FRAME_ID,
        odometry_child_frame_id="base_link",
    )


def _front_lidar_center_cylinder_scan(*, ray_count: int = 720) -> tuple[float, ...]:
    """Synthetic pinned BARN scan: +0.12 m LiDAR and radius-0.05 m body."""

    angle_min = -math.pi
    increment = 2.0 * math.pi / (ray_count - 1)
    sensor_x = 0.12
    radius = 0.05
    ranges: list[float] = []
    for index in range(ray_count):
        angle = angle_min + index * increment
        cosine = math.cos(angle)
        discriminant = (sensor_x * cosine) ** 2 - (sensor_x**2 - radius**2)
        if discriminant < 0.0:
            ranges.append(math.inf)
            continue
        roots = (
            -sensor_x * cosine - math.sqrt(discriminant),
            -sensor_x * cosine + math.sqrt(discriminant),
        )
        forward_roots = [root for root in roots if root >= 0.05]
        ranges.append(min(forward_roots) if forward_roots else math.inf)
    return tuple(ranges)


def test_ros2_transport_forwards_only_sensor_contract_and_resets_once() -> None:
    policy = RecordingPolicy()
    adapter = BarnRos2AdapterCore(policy)

    command = adapter.step(_frame())
    adapter.step(_frame(1.1))

    assert policy.resets == [((1.5, -0.25), 0.3, BARN_ROS2_STATIC_GOAL_ODOM_XY)]
    assert len(policy.observations) == 2
    observation = policy.observations[0]
    assert observation.position_xy == (1.5, -0.25)
    assert observation.heading_rad == pytest.approx(0.3)
    assert observation.lidar_ranges_m == (math.inf, 2.0, 1.25)
    assert observation.lidar_angle_min_rad == pytest.approx(-1.0)
    assert observation.lidar_angle_increment_rad == pytest.approx(0.5)
    assert observation.time_s == pytest.approx(1.0)
    assert command.forward_mps == pytest.approx(0.4)
    assert command.yaw_rate_rps == pytest.approx(-0.2)
    assert command.stop is False


def test_ros2_transport_converts_terminal_action_to_zero_twist() -> None:
    policy = RecordingPolicy([BarnAction(0.7, 0.5, stop=True, note="done")])
    adapter = BarnRos2AdapterCore(policy)

    command = adapter.step(_frame())

    assert command.stop is True
    assert command.forward_mps == 0.0
    assert command.yaw_rate_rps == 0.0
    assert command.note == "done"
    adapter.close()
    adapter.close()
    assert policy.closed is True


def test_ros2_transport_rejects_stale_frames_and_malformed_scan() -> None:
    adapter = BarnRos2AdapterCore(RecordingPolicy())
    adapter.step(_frame(2.0))

    with pytest.raises(ValueError, match="strictly increasing"):
        adapter.step(_frame(2.0))
    with pytest.raises(ValueError, match="LiDAR ranges"):
        BarnRos2SensorFrame(
            stamp_s=3.0,
            position_xy=(0.0, 0.0),
            heading_rad=0.0,
            lidar_ranges_m=(float("nan"),),
            lidar_angle_min_rad=0.0,
            lidar_angle_increment_rad=0.01,
            lidar_range_min_m=0.1,
            lidar_range_max_m=30.0,
        )


def test_ros2_contract_cannot_represent_evaluator_private_state() -> None:
    field_names = {field.name for field in fields(BarnRos2SensorFrame)}

    assert BARN_ROS2_POLICY_INPUTS == (
        "goal_in_odom_frame",
        "platform_odometry",
        "front_2d_lidar",
        "simulation_clock",
    )
    assert set(BARN_ROS2_FORBIDDEN_POLICY_INPUTS).isdisjoint(field_names)
    assert field_names == {
        "stamp_s",
        "position_xy",
        "heading_rad",
        "lidar_ranges_m",
        "lidar_angle_min_rad",
        "lidar_angle_increment_rad",
        "lidar_range_min_m",
        "lidar_range_max_m",
        "odometry_stamp_s",
        "lidar_frame_id",
        "odometry_child_frame_id",
    }
    assert BARN_ROS2_COMMAND_MESSAGE == "geometry_msgs/msg/TwistStamped"


def test_quaternion_to_yaw_normalizes_and_rejects_zero_quaternion() -> None:
    yaw = 1.2
    assert quaternion_to_yaw(
        0.0, 0.0, 3.0 * math.sin(yaw / 2.0), 3.0 * math.cos(yaw / 2.0)
    ) == pytest.approx(yaw)
    with pytest.raises(ValueError, match="norm"):
        quaternion_to_yaw(0.0, 0.0, 0.0, 0.0)


def test_calibrated_self_filter_invalidates_analytic_center_cylinder_arc() -> None:
    raw_ranges = _front_lidar_center_cylinder_scan()

    normalized = normalize_planar_lidar_frame(
        _calibrated_frame(raw_ranges),
        BARN_ROS2_LIDAR_CALIBRATION,
    )

    assert min(value for value in raw_ranges if math.isfinite(value)) == pytest.approx(0.07)
    assert normalized.diagnostics.self_return_count > 0
    assert normalized.diagnostics.reprojected_hit_count == 0
    # Invalid is intentionally distinct from infinity: the self-occluded
    # directions do not clear or occupy the map.
    assert any(math.isnan(value) for value in normalized.ranges_m)
    center_endpoint = BARN_ROS2_LIDAR_CALIBRATION.endpoint_in_base(raw_ranges[0], -math.pi)
    center_bearing = math.atan2(center_endpoint[1], center_endpoint[0])
    center_bin = round((center_bearing - normalized.angle_min_rad) / normalized.angle_increment_rad)
    assert math.isnan(normalized.ranges_m[center_bin])


def test_self_mask_resolution_margin_has_a_hard_external_boundary() -> None:
    mask = BARN_ROS2_LIDAR_CALIBRATION.self_masks[0]

    assert mask.radius_m == pytest.approx(0.05)
    assert mask.measurement_margin_m == pytest.approx(0.005)
    assert mask.contains((0.055, 0.0))
    assert not mask.contains((0.055_001, 0.0))

    # A close hit in front of the offset sensor is outside the declared robot
    # mask and must survive endpoint transformation and reprojection.
    ranges = list(_front_lidar_center_cylinder_scan(ray_count=721))
    ranges[360] = 0.08
    normalized = normalize_planar_lidar_frame(
        _calibrated_frame(tuple(ranges)),
        BARN_ROS2_LIDAR_CALIBRATION,
    )
    external_hits = [value for value in normalized.ranges_m if math.isfinite(value)]
    assert normalized.diagnostics.self_return_count > 0
    assert external_hits == pytest.approx([0.20])


def test_calibrated_reprojection_applies_extrinsic_rotation_and_translation() -> None:
    calibration = PlanarLidarCalibration(
        lidar_frame_id="test_lidar",
        base_frame_id="base_link",
        lidar_forward_m=1.0,
        lidar_left_m=2.0,
        lidar_yaw_rad=math.pi / 2.0,
        self_masks=(CircularSelfMask(100.0, 100.0, 0.1),),
    )
    ranges = [math.inf] * 721
    ranges[360] = 2.0
    frame = _calibrated_frame(tuple(ranges))
    frame = BarnRos2SensorFrame(
        **{
            **{field.name: getattr(frame, field.name) for field in fields(BarnRos2SensorFrame)},
            "lidar_frame_id": "test_lidar",
        }
    )

    normalized = normalize_planar_lidar_frame(frame, calibration)
    hit_index, hit_range = next(
        (index, value) for index, value in enumerate(normalized.ranges_m) if math.isfinite(value)
    )
    hit_bearing = normalized.angle_min_rad + hit_index * normalized.angle_increment_rad

    assert hit_range == pytest.approx(math.hypot(1.0, 4.0))
    assert hit_bearing == pytest.approx(math.atan2(4.0, 1.0), abs=math.pi / 720.0)


def test_calibrated_core_fails_closed_on_missing_bad_or_unsynchronised_calibration() -> None:
    with pytest.raises(ValueError, match="explicit calibration"):
        BarnRos2AdapterCore(RecordingPolicy(), require_lidar_calibration=True)
    with pytest.raises(ValueError, match="measurement margin"):
        CircularSelfMask(0.0, 0.0, 0.05, measurement_margin_m=0.051)

    core = BarnRos2AdapterCore(
        RecordingPolicy(),
        lidar_calibration=BARN_ROS2_LIDAR_CALIBRATION,
        require_lidar_calibration=True,
    )
    frame = _calibrated_frame((math.inf,) * 9)
    with pytest.raises(ValueError, match="frame mismatch"):
        core.step(
            BarnRos2SensorFrame(
                **{
                    **{
                        field.name: getattr(frame, field.name)
                        for field in fields(BarnRos2SensorFrame)
                    },
                    "lidar_frame_id": "wrong_lidar",
                }
            )
        )
    with pytest.raises(ValueError, match="child-frame mismatch"):
        core.step(
            BarnRos2SensorFrame(
                **{
                    **{
                        field.name: getattr(frame, field.name)
                        for field in fields(BarnRos2SensorFrame)
                    },
                    "odometry_child_frame_id": "wrong_base",
                }
            )
        )
    with pytest.raises(ValueError, match="max_sensor_skew"):
        core.step(
            BarnRos2SensorFrame(
                **{
                    **{
                        field.name: getattr(frame, field.name)
                        for field in fields(BarnRos2SensorFrame)
                    },
                    "odometry_stamp_s": frame.stamp_s - 0.2,
                }
            )
        )


def test_exact_synthetic_initial_scan_recovers_partial_forward_motion() -> None:
    raw_ranges = list(_front_lidar_center_cylinder_scan())
    # Preserve the causal replay's nearest external world hit while adding
    # only the analytic robot self arc.
    nearest_world_hit_bearing = -1.6035667647669738
    world_hit_index = min(
        range(len(raw_ranges)),
        key=lambda index: abs(
            -math.pi + index * 2.0 * math.pi / (len(raw_ranges) - 1) - nearest_world_hit_bearing
        ),
    )
    raw_ranges[world_hit_index] = 2.1013
    frame = _calibrated_frame(tuple(raw_ranges))
    raw_policy = ParcelBarnAdapter(
        navigation_config="configs/navigation/experiments/barn_grid_v1.yaml"
    )
    calibrated_policy = ParcelBarnAdapter(
        navigation_config="configs/navigation/experiments/barn_grid_v1.yaml"
    )
    raw_core = BarnRos2AdapterCore(raw_policy)
    calibrated_core = BarnRos2AdapterCore(
        calibrated_policy,
        lidar_calibration=BARN_ROS2_LIDAR_CALIBRATION,
        require_lidar_calibration=True,
    )
    try:
        raw_command = raw_core.step(frame)
        calibrated_command = calibrated_core.step(frame)
    finally:
        raw_core.close()
        calibrated_core.close()

    assert raw_command.forward_mps == 0.0
    assert "grid_recover_scan status=no_path" in raw_command.note
    assert calibrated_command.forward_mps > 0.0
    assert "grid_track" in calibrated_command.note
    assert "status=partial" in calibrated_command.note
