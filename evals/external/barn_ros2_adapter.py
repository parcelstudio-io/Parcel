"""Evaluator-only ROS 2 transport contract for Parcel's unchanged navigator.

This module deliberately lives outside :mod:`parcel_robot`.  The pure core
accepts only the observations exposed by the 2026 BARN ROS 2 evaluator and
delegates to :class:`ParcelBarnAdapter`, which in turn delegates to the normal
``DirectiveNavigator``.  It never imports the Gazebo world, collision topic,
reference path, optimal path length, or hidden-world identity.

The ROS-facing executable is kept in ``barn_ros2_node.py`` so this contract can
be unit-tested on machines without ROS.  The organizer's documented submission
hook remains the only evaluator integration point.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from .barn_native import BarnAction, BarnObservation
from .parcel_barn_adapter import ParcelBarnAdapter

BARN_ROS2_ADAPTER_ID = "parcel-barn-ros2-calibrated-sensor-transport-v2"
BARN_ROS2_SOURCE_ID = "barn_challenge_ros2_2026"
BARN_ROS2_SOURCE_COMMIT = "d6c575b51e477bd524d634e12cffeb34036fcd1e"

BARN_ROS2_LIDAR_TOPIC = "/front/scan"
BARN_ROS2_ODOMETRY_TOPIC = "/platform/odom/filtered"
BARN_ROS2_COMMAND_TOPIC = "/cmd_vel"
BARN_ROS2_COMMAND_MESSAGE = "geometry_msgs/msg/TwistStamped"
BARN_ROS2_CONTROL_PERIOD_S = 0.1
BARN_ROS2_STATIC_GOAL_ODOM_XY = (10.0, 0.0)

BARN_ROS2_POLICY_INPUTS = (
    "goal_in_odom_frame",
    "platform_odometry",
    "front_2d_lidar",
    "simulation_clock",
)
BARN_ROS2_FORBIDDEN_POLICY_INPUTS = (
    "world_sdf",
    "collision_truth",
    "reference_path",
    "optimal_path_length",
    "hidden_world_identity",
)


@dataclass(frozen=True, slots=True)
class CircularSelfMask:
    """One calibrated circular part of the robot in the base frame.

    Coordinates use Parcel's planar body convention: positive ``forward_m``
    is base +x and positive ``left_m`` is base +y.  The mask is applied only
    to finite hit endpoints.  A masked ray becomes invalid rather than a
    no-return ray, so it cannot clear unknown space behind the robot.
    """

    forward_m: float
    left_m: float
    radius_m: float
    measurement_margin_m: float = 0.0

    def __post_init__(self) -> None:
        values = (self.forward_m, self.left_m, self.radius_m, self.measurement_margin_m)
        if any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in values):
            raise ValueError("LiDAR self-mask values must be numeric")
        if not all(math.isfinite(value) for value in values):
            raise ValueError("LiDAR self-mask values must be finite")
        if self.radius_m <= 0.0:
            raise ValueError("LiDAR self-mask radius must be positive")
        if not 0.0 <= self.measurement_margin_m <= 0.05:
            raise ValueError("LiDAR self-mask measurement margin must be in [0, 0.05] meters")

    def contains(self, point: tuple[float, float]) -> bool:
        return (
            math.hypot(point[0] - self.forward_m, point[1] - self.left_m)
            <= self.radius_m + self.measurement_margin_m + 1e-9
        )


@dataclass(frozen=True, slots=True)
class PlanarLidarCalibration:
    """Declared rigid transform and robot-only mask for one planar LiDAR.

    ``lidar_*`` is the transform from the named LiDAR frame into the named
    base frame (``T_base_lidar``).  A non-empty self mask is required so a ROS
    deployment cannot silently claim to be calibrated while retaining the
    self-return failure this boundary exists to prevent.
    """

    lidar_frame_id: str
    base_frame_id: str
    lidar_forward_m: float
    lidar_left_m: float
    lidar_yaw_rad: float
    self_masks: tuple[CircularSelfMask, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.lidar_frame_id, str) or not isinstance(self.base_frame_id, str):
            raise TypeError("LiDAR and base frame IDs must be strings")
        if not self.lidar_frame_id.strip() or not self.base_frame_id.strip():
            raise ValueError("LiDAR and base frame IDs must not be empty")
        if any(character.isspace() for character in self.lidar_frame_id + self.base_frame_id):
            raise ValueError("LiDAR and base frame IDs must not contain whitespace")
        transform = (self.lidar_forward_m, self.lidar_left_m, self.lidar_yaw_rad)
        if any(
            isinstance(value, bool) or not isinstance(value, (int, float)) for value in transform
        ):
            raise ValueError("LiDAR-to-base transform must be numeric")
        if not all(math.isfinite(value) for value in transform):
            raise ValueError("LiDAR-to-base transform must be finite")
        try:
            masks = tuple(self.self_masks)
        except TypeError as exc:
            raise ValueError("LiDAR self_masks must be a non-empty sequence") from exc
        object.__setattr__(self, "self_masks", masks)
        if not masks or not all(isinstance(mask, CircularSelfMask) for mask in masks):
            raise ValueError("LiDAR self_masks must contain CircularSelfMask values")

    def endpoint_in_base(self, distance_m: float, beam_angle_rad: float) -> tuple[float, float]:
        """Transform one sensor-frame beam endpoint into the base frame."""

        angle = self.lidar_yaw_rad + beam_angle_rad
        return (
            self.lidar_forward_m + distance_m * math.cos(angle),
            self.lidar_left_m + distance_m * math.sin(angle),
        )


@dataclass(frozen=True, slots=True)
class LidarNormalizationDiagnostics:
    """Transport-visible scan-normalization evidence, never evaluator state."""

    lidar_frame_id: str
    base_frame_id: str
    lidar_stamp_s: float
    odometry_stamp_s: float
    input_ray_count: int
    output_ray_count: int
    finite_hit_count: int
    self_return_count: int
    reprojected_hit_count: int
    reprojected_clear_count: int


@dataclass(frozen=True, slots=True)
class NormalizedPlanarScan:
    """A base-origin regular scan accepted by Parcel's existing boundary."""

    ranges_m: tuple[float, ...]
    angle_min_rad: float
    angle_increment_rad: float
    diagnostics: LidarNormalizationDiagnostics


# Pinned BARN 2026 robot geometry.  The front Hokuyo focal point is 0.12 m
# ahead of base_link.  Its scan plane intersects the radius-0.05 m cylinder on
# default_mount.  Half of the declared 0.01 m range resolution is included in
# the mask so a quantized surface return cannot leak, while the effective
# 0.055 m circle remains far inside the platform's planar footprint.
BARN_ROS2_LIDAR_FRAME_ID = "lidar2d_0_laser"
BARN_ROS2_BASE_FRAME_ID = "base_link"
BARN_ROS2_LIDAR_RANGE_RESOLUTION_M = 0.01
BARN_ROS2_LIDAR_CALIBRATION = PlanarLidarCalibration(
    lidar_frame_id=BARN_ROS2_LIDAR_FRAME_ID,
    base_frame_id=BARN_ROS2_BASE_FRAME_ID,
    lidar_forward_m=0.12,
    lidar_left_m=0.0,
    lidar_yaw_rad=0.0,
    self_masks=(
        CircularSelfMask(
            forward_m=0.0,
            left_m=0.0,
            radius_m=0.05,
            measurement_margin_m=BARN_ROS2_LIDAR_RANGE_RESOLUTION_M / 2.0,
        ),
    ),
)


@runtime_checkable
class BarnRos2Policy(Protocol):
    """Narrow policy surface accepted by the ROS 2 transport."""

    def reset(
        self,
        start_xy: tuple[float, float],
        heading_rad: float,
        goal_xy: tuple[float, float],
    ) -> None: ...

    def act(self, observation: BarnObservation) -> BarnAction: ...

    def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class BarnRos2SensorFrame:
    """One synchronized, policy-visible ROS 2 observation.

    The transport node creates this from ``LaserScan`` and ``Odometry``.  No
    evaluator-private field is representable by this type.
    """

    stamp_s: float
    position_xy: tuple[float, float]
    heading_rad: float
    lidar_ranges_m: tuple[float, ...]
    lidar_angle_min_rad: float
    lidar_angle_increment_rad: float
    lidar_range_min_m: float
    lidar_range_max_m: float
    # ``stamp_s`` is the LaserScan acquisition time.  Keep the source frame
    # and odometry acquisition time separate when the ROS bridge provides
    # them; legacy/native policy tests remain source-compatible via ``None``.
    odometry_stamp_s: float | None = None
    lidar_frame_id: str | None = None
    odometry_child_frame_id: str | None = None

    def __post_init__(self) -> None:
        if not math.isfinite(self.stamp_s) or self.stamp_s < 0.0:
            raise ValueError("stamp_s must be finite and non-negative")
        if len(self.position_xy) != 2 or not all(
            math.isfinite(float(value)) for value in self.position_xy
        ):
            raise ValueError("position_xy must contain two finite values")
        if not math.isfinite(self.heading_rad):
            raise ValueError("heading_rad must be finite")
        if not self.lidar_ranges_m:
            raise ValueError("lidar_ranges_m must not be empty")
        if not math.isfinite(self.lidar_angle_min_rad):
            raise ValueError("lidar_angle_min_rad must be finite")
        if (
            not math.isfinite(self.lidar_angle_increment_rad)
            or self.lidar_angle_increment_rad <= 0.0
        ):
            raise ValueError("lidar_angle_increment_rad must be finite and positive")
        if not math.isfinite(self.lidar_range_min_m) or self.lidar_range_min_m < 0.0:
            raise ValueError("lidar_range_min_m must be finite and non-negative")
        if (
            not math.isfinite(self.lidar_range_max_m)
            or self.lidar_range_max_m <= self.lidar_range_min_m
        ):
            raise ValueError("lidar_range_max_m must exceed lidar_range_min_m")
        if self.odometry_stamp_s is not None:
            if isinstance(self.odometry_stamp_s, bool) or not isinstance(
                self.odometry_stamp_s, (int, float)
            ):
                raise ValueError("odometry_stamp_s must be numeric")
            if not math.isfinite(self.odometry_stamp_s) or self.odometry_stamp_s < 0.0:
                raise ValueError("odometry_stamp_s must be finite and non-negative")
        for name, value in (
            ("lidar_frame_id", self.lidar_frame_id),
            ("odometry_child_frame_id", self.odometry_child_frame_id),
        ):
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ValueError(f"{name} must be a non-empty string when provided")
        for distance in self.lidar_ranges_m:
            # LaserScan uses positive infinity for a clear ray.  NaN and
            # negative ranges are malformed transport data and fail closed.
            value = float(distance)
            if math.isnan(value) or value < 0.0:
                raise ValueError("LiDAR ranges must be non-negative or positive infinity")

    @property
    def lidar_stamp_s(self) -> float:
        """Explicit alias documenting that ``stamp_s`` belongs to the scan."""

        return self.stamp_s


def normalize_planar_lidar_frame(
    frame: BarnRos2SensorFrame,
    calibration: PlanarLidarCalibration,
) -> NormalizedPlanarScan:
    """Transform and self-filter a regular sensor scan for the base mapper.

    Parcel's frozen BARN policy boundary accepts a regular base-origin scan,
    not arbitrary per-ray origins.  Each raw endpoint is therefore transformed
    by ``T_base_lidar`` and conservatively reprojected to the nearest bin on a
    base-frame angular lattice.  A finite endpoint inside the declared robot
    mask contributes no evidence and is represented by NaN.  Positive
    infinity remains a no-return observation.  A self return suppresses clear
    evidence that quantizes into the same bin, while a valid finite external
    hit wins; this prevents accidental free-space carving without hiding a
    close obstacle at the reprojection resolution.
    """

    if not isinstance(calibration, PlanarLidarCalibration):
        raise TypeError("a valid PlanarLidarCalibration is required")
    if frame.lidar_frame_id is None:
        raise ValueError("calibrated LiDAR frame is missing lidar_frame_id")
    observed_frame = frame.lidar_frame_id.lstrip("/")
    expected_frame = calibration.lidar_frame_id.lstrip("/")
    if observed_frame != expected_frame:
        raise ValueError(
            f"LiDAR frame mismatch: expected {calibration.lidar_frame_id!r}, "
            f"received {frame.lidar_frame_id!r}"
        )
    if frame.odometry_stamp_s is None:
        raise ValueError("calibrated LiDAR frame is missing odometry_stamp_s")
    if frame.odometry_child_frame_id is None:
        raise ValueError("calibrated LiDAR frame is missing odometry_child_frame_id")
    observed_base = frame.odometry_child_frame_id.lstrip("/")
    expected_base = calibration.base_frame_id.lstrip("/")
    if observed_base != expected_base:
        raise ValueError(
            f"odometry child-frame mismatch: expected {calibration.base_frame_id!r}, "
            f"received {frame.odometry_child_frame_id!r}"
        )

    ray_count = len(frame.lidar_ranges_m)
    output_angle_min = frame.lidar_angle_min_rad + calibration.lidar_yaw_rad
    output_ranges = [math.nan] * ray_count
    output_has_hit = [False] * ray_count
    output_has_self_return = [False] * ray_count
    finite_hits = 0
    self_returns = 0
    reprojected_hits = 0
    reprojected_clear = 0

    for index, raw_value in enumerate(frame.lidar_ranges_m):
        raw_range = float(raw_value)
        sensor_angle = frame.lidar_angle_min_rad + index * frame.lidar_angle_increment_rad
        is_clear = raw_range == math.inf
        if not is_clear:
            if not math.isfinite(raw_range):
                raise ValueError("calibrated LiDAR input contains a non-finite non-clear range")
            if raw_range < frame.lidar_range_min_m:
                # ROS permits below-minimum values to signal an unusable ray.
                # Keep it invalid rather than manufacturing free or occupied
                # evidence.
                continue
            if raw_range > frame.lidar_range_max_m + 1e-9:
                raise ValueError("calibrated LiDAR range exceeds lidar_range_max_m")
            is_clear = raw_range >= frame.lidar_range_max_m - 1e-6

        projection_range = frame.lidar_range_max_m if is_clear else raw_range
        endpoint = calibration.endpoint_in_base(projection_range, sensor_angle)
        base_bearing = math.atan2(endpoint[1], endpoint[0])
        output_index = _nearest_scan_index(
            base_bearing,
            angle_min_rad=output_angle_min,
            angle_increment_rad=frame.lidar_angle_increment_rad,
            ray_count=ray_count,
        )
        if output_index is None:
            # This is possible only for a translated, partial-FOV sensor.  It
            # is safer to lose that edge ray than to place it in a false bin.
            continue

        if not is_clear:
            finite_hits += 1
            if any(mask.contains(endpoint) for mask in calibration.self_masks):
                self_returns += 1
                output_has_self_return[output_index] = True
                if not output_has_hit[output_index]:
                    output_ranges[output_index] = math.nan
                continue
            base_distance = math.hypot(*endpoint)
            previous = output_ranges[output_index]
            if not output_has_hit[output_index] or base_distance < previous:
                output_ranges[output_index] = base_distance
                output_has_hit[output_index] = True
            reprojected_hits += 1
            continue

        if (
            not output_has_hit[output_index]
            and not output_has_self_return[output_index]
            and math.isnan(output_ranges[output_index])
        ):
            output_ranges[output_index] = math.inf
        reprojected_clear += 1

    return NormalizedPlanarScan(
        ranges_m=tuple(output_ranges),
        angle_min_rad=output_angle_min,
        angle_increment_rad=frame.lidar_angle_increment_rad,
        diagnostics=LidarNormalizationDiagnostics(
            lidar_frame_id=frame.lidar_frame_id,
            base_frame_id=calibration.base_frame_id,
            lidar_stamp_s=frame.stamp_s,
            odometry_stamp_s=frame.odometry_stamp_s,
            input_ray_count=ray_count,
            output_ray_count=ray_count,
            finite_hit_count=finite_hits,
            self_return_count=self_returns,
            reprojected_hit_count=reprojected_hits,
            reprojected_clear_count=reprojected_clear,
        ),
    )


def _nearest_scan_index(
    bearing_rad: float,
    *,
    angle_min_rad: float,
    angle_increment_rad: float,
    ray_count: int,
) -> int | None:
    """Return the nearest regular-scan bin without widening the source FOV."""

    angle_max = angle_min_rad + (ray_count - 1) * angle_increment_rad
    full_circle = angle_max - angle_min_rad >= 2.0 * math.pi - 2.0 * angle_increment_rad
    candidate = bearing_rad
    while candidate < angle_min_rad - angle_increment_rad / 2.0:
        candidate += 2.0 * math.pi
    while candidate > angle_max + angle_increment_rad / 2.0:
        candidate -= 2.0 * math.pi
    index = round((candidate - angle_min_rad) / angle_increment_rad)
    if full_circle:
        # Full-circle scans commonly repeat the seam at both endpoints.  Map a
        # one-bin numerical spill to the equivalent seam instead of cropping.
        if index < 0:
            index = ray_count - 1
        elif index >= ray_count:
            index = 0
    return index if 0 <= index < ray_count else None


@dataclass(frozen=True, slots=True)
class BarnRos2VelocityCommand:
    """Differential-drive command emitted to ``TwistStamped``."""

    forward_mps: float
    yaw_rate_rps: float
    stop: bool
    note: str = ""

    def __post_init__(self) -> None:
        if not math.isfinite(self.forward_mps) or not math.isfinite(self.yaw_rate_rps):
            raise ValueError("velocity command must be finite")
        if self.stop and (abs(self.forward_mps) > 1e-12 or abs(self.yaw_rate_rps) > 1e-12):
            raise ValueError("a stopped transport command must have zero velocity")


class BarnRos2AdapterCore:
    """Translate public ROS 2 sensor fields to the existing BARN policy API."""

    def __init__(
        self,
        policy: BarnRos2Policy,
        *,
        goal_xy: tuple[float, float] = BARN_ROS2_STATIC_GOAL_ODOM_XY,
        lidar_calibration: PlanarLidarCalibration | None = None,
        require_lidar_calibration: bool = False,
        max_sensor_skew_s: float = 0.05,
    ) -> None:
        if not isinstance(policy, BarnRos2Policy):
            raise TypeError("policy must implement the BARN sensor-only policy contract")
        if len(goal_xy) != 2 or not all(math.isfinite(float(value)) for value in goal_xy):
            raise ValueError("goal_xy must contain two finite values")
        if not isinstance(require_lidar_calibration, bool):
            raise TypeError("require_lidar_calibration must be boolean")
        if lidar_calibration is not None and not isinstance(
            lidar_calibration, PlanarLidarCalibration
        ):
            raise TypeError("lidar_calibration must be PlanarLidarCalibration")
        if require_lidar_calibration and lidar_calibration is None:
            raise ValueError("calibrated ROS LiDAR input requires explicit calibration")
        if not math.isfinite(max_sensor_skew_s) or not 0.0 <= max_sensor_skew_s <= 0.5:
            raise ValueError("max_sensor_skew_s must be in [0, 0.5]")
        self._policy = policy
        self._goal_xy = (float(goal_xy[0]), float(goal_xy[1]))
        self._lidar_calibration = lidar_calibration
        self._max_sensor_skew_s = float(max_sensor_skew_s)
        self._started = False
        self._closed = False
        self._last_stamp_s: float | None = None
        self._last_odometry_stamp_s: float | None = None
        self._last_normalization: LidarNormalizationDiagnostics | None = None

    @classmethod
    def from_navigation_config(
        cls,
        navigation_config: str | Path,
        *,
        goal_xy: tuple[float, float] = BARN_ROS2_STATIC_GOAL_ODOM_XY,
        arrival_radius_m: float = 0.75,
        lidar_max_range_m: float = 10.0,
        lidar_calibration: PlanarLidarCalibration | None = None,
        max_sensor_skew_s: float = 0.05,
    ) -> BarnRos2AdapterCore:
        """Construct the calibrated ROS adapter without changing native defaults."""

        config_path = Path(navigation_config).expanduser().resolve()
        if not config_path.is_file():
            raise FileNotFoundError(f"navigation config does not exist: {config_path}")
        if lidar_calibration is None:
            raise ValueError("ROS Parcel adapter requires explicit LiDAR calibration")
        return cls(
            ParcelBarnAdapter(
                navigation_config=config_path,
                arrival_radius_m=arrival_radius_m,
                lidar_max_range_m=lidar_max_range_m,
            ),
            goal_xy=goal_xy,
            lidar_calibration=lidar_calibration,
            require_lidar_calibration=True,
            max_sensor_skew_s=max_sensor_skew_s,
        )

    @property
    def started(self) -> bool:
        return self._started

    @property
    def goal_xy(self) -> tuple[float, float]:
        return self._goal_xy

    @property
    def last_normalization_diagnostics(self) -> LidarNormalizationDiagnostics | None:
        return self._last_normalization

    def step(self, frame: BarnRos2SensorFrame) -> BarnRos2VelocityCommand:
        if self._closed:
            raise RuntimeError("adapter is closed")
        if self._last_stamp_s is not None and frame.stamp_s <= self._last_stamp_s:
            raise ValueError("LiDAR timestamps must be strictly increasing")

        ranges = frame.lidar_ranges_m
        angle_min = frame.lidar_angle_min_rad
        angle_increment = frame.lidar_angle_increment_rad
        if self._lidar_calibration is not None:
            if frame.odometry_stamp_s is None:
                raise ValueError("calibrated ROS LiDAR input requires odometry_stamp_s")
            if abs(frame.stamp_s - frame.odometry_stamp_s) > self._max_sensor_skew_s + 1e-12:
                raise ValueError("LiDAR and odometry timestamps exceed max_sensor_skew_s")
            if (
                self._last_odometry_stamp_s is not None
                and frame.odometry_stamp_s < self._last_odometry_stamp_s
            ):
                raise ValueError("odometry timestamps must be monotonic")
            normalized = normalize_planar_lidar_frame(frame, self._lidar_calibration)
            ranges = normalized.ranges_m
            angle_min = normalized.angle_min_rad
            angle_increment = normalized.angle_increment_rad
            self._last_normalization = normalized.diagnostics

        if not self._started:
            self._policy.reset(frame.position_xy, frame.heading_rad, self._goal_xy)
            self._started = True

        action = self._policy.act(
            BarnObservation(
                position_xy=frame.position_xy,
                heading_rad=frame.heading_rad,
                lidar_ranges_m=ranges,
                lidar_angle_min_rad=angle_min,
                lidar_angle_increment_rad=angle_increment,
                time_s=frame.stamp_s,
            )
        )
        self._last_stamp_s = frame.stamp_s
        self._last_odometry_stamp_s = frame.odometry_stamp_s
        if not math.isfinite(action.vx_mps) or not math.isfinite(action.yaw_rate_rps):
            raise ValueError("policy returned a non-finite command")
        if action.stop:
            return BarnRos2VelocityCommand(0.0, 0.0, stop=True, note=action.note)
        return BarnRos2VelocityCommand(
            forward_mps=float(action.vx_mps),
            yaw_rate_rps=float(action.yaw_rate_rps),
            stop=False,
            note=action.note,
        )

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._policy.close()


def quaternion_to_yaw(x: float, y: float, z: float, w: float) -> float:
    """Return planar yaw from a ROS quaternion without a TF dependency."""

    values = (float(x), float(y), float(z), float(w))
    if not all(math.isfinite(value) for value in values):
        raise ValueError("quaternion must be finite")
    norm = math.sqrt(sum(value * value for value in values))
    if norm <= 1e-12:
        raise ValueError("quaternion norm must be positive")
    qx, qy, qz, qw = (value / norm for value in values)
    siny_cosp = 2.0 * (qw * qz + qx * qy)
    cosy_cosp = 1.0 - 2.0 * (qy * qy + qz * qz)
    return math.atan2(siny_cosp, cosy_cosp)


__all__ = [
    "BARN_ROS2_ADAPTER_ID",
    "BARN_ROS2_BASE_FRAME_ID",
    "BARN_ROS2_COMMAND_MESSAGE",
    "BARN_ROS2_COMMAND_TOPIC",
    "BARN_ROS2_CONTROL_PERIOD_S",
    "BARN_ROS2_FORBIDDEN_POLICY_INPUTS",
    "BARN_ROS2_LIDAR_CALIBRATION",
    "BARN_ROS2_LIDAR_FRAME_ID",
    "BARN_ROS2_LIDAR_RANGE_RESOLUTION_M",
    "BARN_ROS2_LIDAR_TOPIC",
    "BARN_ROS2_ODOMETRY_TOPIC",
    "BARN_ROS2_POLICY_INPUTS",
    "BARN_ROS2_SOURCE_COMMIT",
    "BARN_ROS2_SOURCE_ID",
    "BARN_ROS2_STATIC_GOAL_ODOM_XY",
    "BarnRos2AdapterCore",
    "BarnRos2Policy",
    "BarnRos2SensorFrame",
    "BarnRos2VelocityCommand",
    "CircularSelfMask",
    "LidarNormalizationDiagnostics",
    "NormalizedPlanarScan",
    "PlanarLidarCalibration",
    "normalize_planar_lidar_frame",
    "quaternion_to_yaw",
]
