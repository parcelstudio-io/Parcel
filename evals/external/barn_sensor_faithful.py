"""Calibrated, sensor-faithful native replay of the BARN ROS 2 boundary.

This is a dedicated non-official evaluator.  It preserves Parcel's policy and
routes a deterministic 360-degree, 720-ray scan through the exact calibrated
``BarnRos2AdapterCore`` used by the ROS 2 submission.  The evaluator owns the
world geometry, raw sensor construction, collision checks, and score; none of
those private values cross the policy boundary.

The runner intentionally differs from :mod:`barn_native`: a policy ``stop``
latches a zero command while evaluator time continues to the official timeout,
matching the official evaluator's external process semantics.  It is still an
ideal unicycle/circular-obstacle approximation, not Gazebo and not a leaderboard
score.
"""

from __future__ import annotations

import hashlib
import json
import math
import multiprocessing
import time
from collections import Counter
from collections.abc import Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import fmean
from typing import Any, Literal, cast

import numpy as np

from . import barn_native as barn_native_module
from . import barn_ros2_adapter as barn_ros2_adapter_module
from .barn_native import (
    BARN_EVALUATOR_COMMIT,
    DEFAULT_ROBOT_RADIUS_M,
    JACKAL_MELODIC_REFERENCE_COMMIT,
    JACKAL_SIMULATOR_MELODIC_REFERENCE_COMMIT,
    OFFICIAL_GOAL_XY,
    OFFICIAL_REFERENCE_SPEED_MPS,
    OFFICIAL_START_XY,
    OFFICIAL_STEP_DT_S,
    OFFICIAL_SUCCESS_RADIUS_M,
    OFFICIAL_TIMEOUT_S,
    BarnAction,
    BarnEvaluatorDiagnostics,
    BarnObservation,
    BarnWorld,
    CylinderObstacle,
    barn_navigation_metric,
    cast_lidar,
    load_barn_world,
    load_generated_barn_world,
)
from .barn_policy_sidecar import IsolatedPolicyDescriptor
from .barn_policy_specs import (
    BarnPolicySpec,
    IsolatedPlannerProfileAuthorization,
    ProcessPolicyDescriptor,
    parcel_baseline_policy_spec,
    parcel_experimental_config_spec,
    parcel_reference_config_spec,
    validate_isolated_policy_pair,
)
from .barn_ros2_adapter import (
    BARN_ROS2_ADAPTER_ID,
    BARN_ROS2_BASE_FRAME_ID,
    BARN_ROS2_LIDAR_CALIBRATION,
    BARN_ROS2_LIDAR_FRAME_ID,
    BARN_ROS2_SOURCE_COMMIT,
    BARN_ROS2_SOURCE_ID,
    BARN_ROS2_STATIC_GOAL_ODOM_XY,
    BarnRos2AdapterCore,
    BarnRos2Policy,
    BarnRos2SensorFrame,
    BarnRos2VelocityCommand,
    LidarNormalizationDiagnostics,
)
from .barn_v8_action_certifier import FROZEN_V8_BARN_EVALUATOR_PROFILE
from .barn_v8_action_evidence import (
    V8ActionEvidenceBuilder,
    read_v8_action_evidence,
)

BARN_SENSOR_FAITHFUL_EVALUATION_KIND = (
    "barn-calibrated-sensor-faithful-native-headless-non-official"
)
BARN_SENSOR_FAITHFUL_RUNNER_ID = "parcel-barn-calibrated-native-v1"
BARN_SOURCE = "https://github.com/Daffan/the-barn-challenge"

# The pinned 2026 ROS 2 robot publishes a full-circle Hokuyo scan from a focal
# point 0.12 m ahead of base_link.  Both seam endpoints are represented, just
# like sensor_msgs/LaserScan angle_min=-pi, angle_max=+pi with 720 samples.
CALIBRATED_LIDAR_ANGLE_MIN_RAD = -math.pi
CALIBRATED_LIDAR_ANGLE_MAX_RAD = math.pi
CALIBRATED_LIDAR_RAY_COUNT = 720
CALIBRATED_LIDAR_RANGE_MIN_M = 0.05
CALIBRATED_LIDAR_RANGE_MAX_M = 25.0
CALIBRATED_LIDAR_FOV_DEG = 360.0
CALIBRATED_LIDAR_FORWARD_M = 0.12
CALIBRATED_ODOMETRY_LAG_S = 0.005
CALIBRATED_TRIAL_START_TRANSLATION_M = 0.1
CALIBRATED_START_HEADING_RAD = 1.57

REFERENCE_THEN_CANDIDATE = "reference_then_candidate"
CANDIDATE_THEN_REFERENCE = "candidate_then_reference"
PairedArmOrder = Literal[
    "reference_then_candidate",
    "candidate_then_reference",
]

# This label describes the calibrated boundary and deliberately does not reuse
# BarnPolicySpec's historical ``270_degree_lidar`` label.
CALIBRATED_POLICY_INPUTS = (
    "goal_in_odom_frame",
    "platform_odometry",
    "360_degree_720_ray_front_lidar",
    "simulation_clock",
)


@dataclass(frozen=True, slots=True)
class CalibratedBarnConfig:
    """Reproducible dynamics and fixed calibrated sensor profile."""

    dt_s: float = OFFICIAL_STEP_DT_S
    timeout_s: float = OFFICIAL_TIMEOUT_S
    success_radius_m: float = OFFICIAL_SUCCESS_RADIUS_M
    robot_radius_m: float = DEFAULT_ROBOT_RADIUS_M
    max_forward_speed_mps: float = OFFICIAL_REFERENCE_SPEED_MPS
    max_reverse_speed_mps: float = OFFICIAL_REFERENCE_SPEED_MPS
    max_yaw_rate_rps: float = 4.0
    start_heading_rad: float = CALIBRATED_START_HEADING_RAD
    lidar_angle_min_rad: float = CALIBRATED_LIDAR_ANGLE_MIN_RAD
    lidar_angle_max_rad: float = CALIBRATED_LIDAR_ANGLE_MAX_RAD
    lidar_ray_count: int = CALIBRATED_LIDAR_RAY_COUNT
    lidar_range_min_m: float = CALIBRATED_LIDAR_RANGE_MIN_M
    lidar_range_max_m: float = CALIBRATED_LIDAR_RANGE_MAX_M
    lidar_forward_m: float = CALIBRATED_LIDAR_FORWARD_M
    odometry_lag_s: float = CALIBRATED_ODOMETRY_LAG_S
    trial_start_translation_m: float = CALIBRATED_TRIAL_START_TRANSLATION_M
    startup_timeout_s: float = 10.0
    sensor_stamp_origin_s: float = 1.0
    max_sensor_skew_s: float = 0.05
    trace_stride_steps: int = 10
    trace_max_samples: int = 256

    def __post_init__(self) -> None:
        positive = {
            "dt_s": self.dt_s,
            "timeout_s": self.timeout_s,
            "success_radius_m": self.success_radius_m,
            "robot_radius_m": self.robot_radius_m,
            "max_forward_speed_mps": self.max_forward_speed_mps,
            "max_reverse_speed_mps": self.max_reverse_speed_mps,
            "max_yaw_rate_rps": self.max_yaw_rate_rps,
            "startup_timeout_s": self.startup_timeout_s,
            "lidar_range_min_m": self.lidar_range_min_m,
            "lidar_range_max_m": self.lidar_range_max_m,
        }
        for name, value in positive.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"{name} must be numeric")
            if not math.isfinite(float(value)) or float(value) <= 0.0:
                raise ValueError(f"{name} must be finite and positive")
        exact = {
            "lidar_angle_min_rad": (
                self.lidar_angle_min_rad,
                CALIBRATED_LIDAR_ANGLE_MIN_RAD,
            ),
            "lidar_angle_max_rad": (
                self.lidar_angle_max_rad,
                CALIBRATED_LIDAR_ANGLE_MAX_RAD,
            ),
            "lidar_forward_m": (self.lidar_forward_m, CALIBRATED_LIDAR_FORWARD_M),
            "trial_start_translation_m": (
                self.trial_start_translation_m,
                CALIBRATED_TRIAL_START_TRANSLATION_M,
            ),
            "start_heading_rad": (
                self.start_heading_rad,
                CALIBRATED_START_HEADING_RAD,
            ),
        }
        for name, (actual, expected) in exact.items():
            if not math.isclose(float(actual), expected, rel_tol=0.0, abs_tol=1e-12):
                raise ValueError(f"{name} is fixed by the calibrated BARN sensor profile")
        if self.lidar_ray_count != CALIBRATED_LIDAR_RAY_COUNT:
            raise ValueError("lidar_ray_count is fixed at 720 by the calibrated profile")
        if not math.isclose(
            self.lidar_range_min_m,
            CALIBRATED_LIDAR_RANGE_MIN_M,
            rel_tol=0.0,
            abs_tol=1e-12,
        ):
            raise ValueError("lidar_range_min_m is fixed by the calibrated profile")
        if not math.isclose(
            self.lidar_range_max_m,
            CALIBRATED_LIDAR_RANGE_MAX_M,
            rel_tol=0.0,
            abs_tol=1e-12,
        ):
            raise ValueError("lidar_range_max_m is fixed by the calibrated profile")
        if not math.isclose(
            self.odometry_lag_s,
            CALIBRATED_ODOMETRY_LAG_S,
            rel_tol=0.0,
            abs_tol=1e-12,
        ):
            raise ValueError("odometry_lag_s is fixed by the calibrated replay profile")
        if not math.isfinite(self.sensor_stamp_origin_s) or self.sensor_stamp_origin_s < 0.01:
            raise ValueError("sensor_stamp_origin_s must be finite and at least 0.01")
        if not math.isfinite(self.max_sensor_skew_s) or not 0.0 <= self.max_sensor_skew_s <= 0.5:
            raise ValueError("max_sensor_skew_s must be in [0, 0.5]")
        if self.odometry_lag_s > self.max_sensor_skew_s:
            raise ValueError("odometry_lag_s must not exceed max_sensor_skew_s")
        for name, value in (
            ("trace_stride_steps", self.trace_stride_steps),
            ("trace_max_samples", self.trace_max_samples),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer")


# Kept as a descriptive alias for callers that discovered the implementation
# under its module name before the calibrated API was finalized.
SensorFaithfulConfig = CalibratedBarnConfig


@dataclass(frozen=True, slots=True)
class CalibratedPolicySpec:
    """A BarnPolicySpec relabeled for the exact calibrated ROS observation API."""

    underlying: BarnPolicySpec

    def __post_init__(self) -> None:
        if not isinstance(self.underlying, BarnPolicySpec):
            raise TypeError("underlying must be a BarnPolicySpec")

    @property
    def policy_id(self) -> str:
        return self.underlying.policy_id

    @property
    def execution_device(self) -> str:
        return self.underlying.execution_device

    @property
    def experimental(self) -> bool:
        return self.underlying.experimental

    @property
    def agent_id(self) -> str:
        return self.underlying.agent_id

    @property
    def adapter_id(self) -> str:
        return BARN_ROS2_ADAPTER_ID

    @property
    def implementation_sha256(self) -> str:
        return _sha256(Path(barn_ros2_adapter_module.__file__))

    @property
    def config_id(self) -> str | None:
        return self.underlying.config_id

    @property
    def config_sha256(self) -> str | None:
        return self.underlying.config_sha256

    @property
    def model_id(self) -> str:
        return self.underlying.model_id

    @property
    def model_artifact_sha256(self) -> str | None:
        return self.underlying.model_artifact_sha256

    def ensure_enabled(self, *, allow_experimental: bool = False) -> None:
        self.underlying.ensure_enabled(allow_experimental=allow_experimental)

    def create(
        self,
        *,
        episode_seed: int,
        allow_experimental: bool = False,
    ) -> BarnRos2Policy:
        policy = self.underlying.create(
            episode_seed=episode_seed,
            allow_experimental=allow_experimental,
        )
        if not isinstance(policy, BarnRos2Policy):
            raise TypeError("calibrated policies must also implement close()")
        return policy

    def require_process_descriptor(
        self,
    ) -> ProcessPolicyDescriptor | IsolatedPolicyDescriptor:
        return self.underlying.require_process_descriptor()

    def report_metadata(self) -> dict[str, Any]:
        metadata = self.underlying.report_metadata()
        underlying_adapter_id = str(metadata["adapter_id"])
        metadata["underlying_policy_adapter_id"] = underlying_adapter_id
        metadata["adapter_id"] = BARN_ROS2_ADAPTER_ID
        metadata["policy_inputs"] = list(CALIBRATED_POLICY_INPUTS)
        metadata["sensor_transport"] = {
            "id": BARN_ROS2_ADAPTER_ID,
            "source_id": BARN_ROS2_SOURCE_ID,
            "source_commit": BARN_ROS2_SOURCE_COMMIT,
            "lidar_frame_id": BARN_ROS2_LIDAR_FRAME_ID,
            "base_frame_id": BARN_ROS2_BASE_FRAME_ID,
            "goal_odom_xy": list(BARN_ROS2_STATIC_GOAL_ODOM_XY),
        }
        provenance = metadata.setdefault("provenance", {})
        provenance["calibrated_sensor_transport"] = {
            "id": _relative_source_id(Path(barn_ros2_adapter_module.__file__)),
            "sha256": _sha256(Path(barn_ros2_adapter_module.__file__)),
        }
        return metadata


def calibrated_policy_spec(spec: BarnPolicySpec | CalibratedPolicySpec) -> CalibratedPolicySpec:
    """Wrap one existing factory without changing the policy it constructs."""

    if isinstance(spec, CalibratedPolicySpec):
        return spec
    return CalibratedPolicySpec(spec)


def calibrated_reference_config_spec(
    config_path: str | Path,
    *,
    reference_id: str,
    description: str,
) -> CalibratedPolicySpec:
    return calibrated_policy_spec(
        parcel_reference_config_spec(
            config_path,
            reference_id=reference_id,
            description=description,
        )
    )


def calibrated_experimental_config_spec(
    config_path: str | Path,
    *,
    experiment_id: str,
    description: str,
) -> CalibratedPolicySpec:
    return calibrated_policy_spec(
        parcel_experimental_config_spec(
            config_path,
            experiment_id=experiment_id,
            description=description,
        )
    )


@dataclass(frozen=True, slots=True)
class SensorTransportDiagnostics:
    """Per-episode evidence from public sensor transport fields only."""

    profile_id: str
    raw_fov_deg: float
    raw_ray_count: int
    lidar_forward_m: float
    frame_count: int
    normalization_failures: int
    finite_hit_count: int
    self_return_count: int
    reprojected_hit_count: int
    reprojected_clear_count: int
    first_normalization: dict[str, Any] | None
    last_normalization: dict[str, Any] | None
    maximum_sensor_skew_s: float
    raw_scan_sha256: tuple[str, ...]
    policy_observation_steps: tuple[int, ...]
    policy_observation_sha256: tuple[str, ...]
    published_action_steps: tuple[int, ...]
    published_action_sha256: tuple[str, ...]
    published_action_note_sha256: tuple[str, ...]
    published_action_values: tuple[tuple[int, float, float, bool], ...]
    latency: dict[str, float]


@dataclass(frozen=True, slots=True)
class ShieldStallDiagnostics:
    """Policy-output evidence used to diagnose safety-shield deadlocks."""

    policy_stop_latched: bool
    policy_stop_latch_step: int | None
    issued_policy_command_steps: int
    positive_command_steps: int
    reverse_command_steps: int
    turn_only_command_steps: int
    obstacle_stop_steps: int
    obstacle_stop_command_steps: tuple[int, ...]
    max_consecutive_obstacle_stop_steps: int
    controller_phase_counts: dict[str, int]
    safety_phase_counts: dict[str, int]
    trace: tuple[dict[str, Any], ...]


@dataclass(frozen=True, slots=True)
class SensorFaithfulEpisodeResult:
    """One calibrated native result; never an official Gazebo score."""

    evaluation_kind: str
    official_gazebo_score: bool
    world_index: int
    success: bool
    collided: bool
    timed_out: bool
    startup_timed_out: bool
    stopped: bool
    status: str
    trial_started: bool
    startup_time_s: float | None
    simulation_elapsed_time_s: float
    elapsed_time_s: float
    navigation_metric: float
    optimal_path_length_m: float
    optimal_time_s: float
    traveled_distance_m: float
    final_position_xy: tuple[float, float]
    final_heading_rad: float
    steps: int
    last_action_note: str
    evaluator_diagnostics: BarnEvaluatorDiagnostics
    sensor_diagnostics: SensorTransportDiagnostics
    shield_stall_diagnostics: ShieldStallDiagnostics


@dataclass(frozen=True, slots=True)
class V8EpisodeEvidenceCaptureSpec:
    """Pickle-safe identity for one optional per-action evidence stream."""

    arm: Literal["reference", "candidate"]
    execution_order: int
    world_id: int
    trial_id: int
    seed: int

    def __post_init__(self) -> None:
        if self.arm not in {"reference", "candidate"}:
            raise ValueError("evidence arm must be 'reference' or 'candidate'")
        if (
            isinstance(self.execution_order, bool)
            or not isinstance(self.execution_order, int)
            or self.execution_order not in (0, 1)
        ):
            raise ValueError("evidence execution_order must be 0 or 1")
        for name in ("world_id", "trial_id", "seed"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value < 2**64:
                raise ValueError(f"evidence {name} must be an unsigned 64-bit integer")


@dataclass(frozen=True, slots=True)
class SensorFaithfulEpisodeWithEvidence:
    """A legacy episode result plus its unwritten evaluator-owned builder."""

    result: SensorFaithfulEpisodeResult
    action_evidence: V8ActionEvidenceBuilder


def _wrap_angle(angle: float) -> float:
    return (angle + math.pi) % (2.0 * math.pi) - math.pi


def world_pose_to_odom(
    position_xy: tuple[float, float],
    heading_rad: float,
) -> tuple[tuple[float, float], float]:
    """Express a BARN world pose in the evaluator's start-relative odom frame."""

    if len(position_xy) != 2 or not all(math.isfinite(float(value)) for value in position_xy):
        raise ValueError("position_xy must contain two finite values")
    if not math.isfinite(heading_rad):
        raise ValueError("heading_rad must be finite")
    delta_x = float(position_xy[0]) - OFFICIAL_START_XY[0]
    delta_y = float(position_xy[1]) - OFFICIAL_START_XY[1]
    cosine = math.cos(CALIBRATED_START_HEADING_RAD)
    sine = math.sin(CALIBRATED_START_HEADING_RAD)
    return (
        (cosine * delta_x + sine * delta_y, -sine * delta_x + cosine * delta_y),
        _wrap_angle(heading_rad - CALIBRATED_START_HEADING_RAD),
    )


def cast_sensor_faithful_lidar(
    position_xy: tuple[float, float],
    heading_rad: float,
    cylinders: Sequence[CylinderObstacle],
    *,
    config: CalibratedBarnConfig | None = None,
) -> tuple[float, ...]:
    """Cast the raw offset scan, including the analytic robot self circle.

    The self circle exists only in this sensor ray cast.  It is never appended
    to collision geometry.  Clear rays use positive infinity, matching ROS
    ``LaserScan`` and the exact normalizer's no-return convention.
    """

    profile = config or CalibratedBarnConfig()
    calibration = BARN_ROS2_LIDAR_CALIBRATION
    cosine = math.cos(heading_rad)
    sine = math.sin(heading_rad)
    sensor_position = (
        position_xy[0] + cosine * calibration.lidar_forward_m - sine * calibration.lidar_left_m,
        position_xy[1] + sine * calibration.lidar_forward_m + cosine * calibration.lidar_left_m,
    )
    sensor_heading = heading_rad + calibration.lidar_yaw_rad
    self_circles = tuple(
        CylinderObstacle(
            center_xy=(
                position_xy[0] + cosine * mask.forward_m - sine * mask.left_m,
                position_xy[1] + sine * mask.forward_m + cosine * mask.left_m,
            ),
            # The physical surface is radius 0.05 m.  The 0.005 m mask margin
            # belongs to measurement filtering, not sensor/collision geometry.
            radius_m=mask.radius_m,
            source_name="analytic_robot_self_mask",
        )
        for mask in calibration.self_masks
    )
    raw = cast_lidar(
        sensor_position,
        sensor_heading,
        tuple(cylinders) + self_circles,
        angle_min_rad=profile.lidar_angle_min_rad,
        angle_max_rad=profile.lidar_angle_max_rad,
        ray_count=profile.lidar_ray_count,
        max_range_m=profile.lidar_range_max_m,
    )
    return tuple(
        math.inf if value >= profile.lidar_range_max_m - 1e-9 else float(value) for value in raw
    )


def _policy_observation_sha256(observation: BarnObservation) -> str:
    digest = hashlib.sha256()
    header = np.asarray(
        (
            observation.position_xy[0],
            observation.position_xy[1],
            observation.heading_rad,
            observation.lidar_angle_min_rad,
            observation.lidar_angle_increment_rad,
            observation.time_s,
        ),
        dtype="<f8",
    )
    scan = np.asarray(observation.lidar_ranges_m, dtype="<f8")
    digest.update(len(scan).to_bytes(8, byteorder="little", signed=False))
    digest.update(header.tobytes(order="C"))
    digest.update(scan.tobytes(order="C"))
    return digest.hexdigest()


def _scan_sha256(ranges: Sequence[float]) -> str:
    scan = np.asarray(tuple(ranges), dtype="<f8")
    digest = hashlib.sha256()
    digest.update(len(scan).to_bytes(8, byteorder="little", signed=False))
    digest.update(scan.tobytes(order="C"))
    return digest.hexdigest()


def _laser_scan_float32(value: float) -> float:
    """Round one value through sensor_msgs/LaserScan's float32 wire type."""

    return float(np.float32(value))


def _published_action_sha256(command: BarnRos2VelocityCommand) -> str:
    digest = hashlib.sha256()
    values = np.asarray((command.forward_mps, command.yaw_rate_rps), dtype="<f8")
    digest.update(values.tobytes(order="C"))
    digest.update(b"\x01" if command.stop else b"\x00")
    return digest.hexdigest()


def _action_note_sha256(command: BarnRos2VelocityCommand) -> str:
    digest = hashlib.sha256()
    note = command.note.encode("utf-8")
    digest.update(len(note).to_bytes(8, byteorder="little", signed=False))
    digest.update(note)
    return digest.hexdigest()


class _InstrumentedPolicy:
    """Hash the exact post-normalization observation before delegation."""

    def __init__(self, policy: BarnRos2Policy) -> None:
        self.policy = policy
        self.observation_hashes: list[str] = []
        self.last_observation: BarnObservation | None = None
        self.closed = False

    def reset(
        self,
        start_xy: tuple[float, float],
        heading_rad: float,
        goal_xy: tuple[float, float],
    ) -> None:
        self.policy.reset(start_xy, heading_rad, goal_xy)

    def act(self, observation: BarnObservation) -> BarnAction:
        self.last_observation = observation
        self.observation_hashes.append(_policy_observation_sha256(observation))
        return self.policy.act(observation)

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        self.policy.close()


def _unicycle_step(
    position: tuple[float, float],
    heading: float,
    velocity: float,
    yaw_rate: float,
    dt_s: float,
) -> tuple[tuple[float, float], float]:
    if abs(yaw_rate) < 1e-12:
        return (
            (
                position[0] + velocity * math.cos(heading) * dt_s,
                position[1] + velocity * math.sin(heading) * dt_s,
            ),
            _wrap_angle(heading),
        )
    next_heading = heading + yaw_rate * dt_s
    radius = velocity / yaw_rate
    return (
        (
            position[0] + radius * (math.sin(next_heading) - math.sin(heading)),
            position[1] + radius * (math.cos(heading) - math.cos(next_heading)),
        ),
        _wrap_angle(next_heading),
    )


def _first_translation_threshold_crossing_s(
    *,
    initial_position: tuple[float, float],
    step_position: tuple[float, float],
    step_heading: float,
    velocity: float,
    yaw_rate: float,
    dt_s: float,
    threshold_m: float,
) -> float | None:
    """Find the first within-tick crossing of the scorer's startup radius."""

    threshold_with_tolerance = threshold_m - 1e-12
    if math.dist(step_position, initial_position) >= threshold_with_tolerance:
        return 0.0
    sample_count = 64
    lower_t = 0.0
    for sample in range(1, sample_count + 1):
        upper_t = dt_s * sample / sample_count
        upper_position, _ = _unicycle_step(
            step_position,
            step_heading,
            velocity,
            yaw_rate,
            upper_t,
        )
        if math.dist(upper_position, initial_position) >= threshold_with_tolerance:
            for _ in range(52):
                middle_t = (lower_t + upper_t) / 2.0
                middle_position, _ = _unicycle_step(
                    step_position,
                    step_heading,
                    velocity,
                    yaw_rate,
                    middle_t,
                )
                if math.dist(middle_position, initial_position) >= threshold_with_tolerance:
                    upper_t = middle_t
                else:
                    lower_t = middle_t
            return upper_t
        lower_t = upper_t
    return None


def _segment_minimum_signed_clearance(
    start: tuple[float, float],
    end: tuple[float, float],
    cylinders: Sequence[CylinderObstacle],
    robot_radius_m: float,
) -> float | None:
    delta_x = end[0] - start[0]
    delta_y = end[1] - start[1]
    length_squared = delta_x * delta_x + delta_y * delta_y
    minimum: float | None = None
    for cylinder in cylinders:
        if length_squared <= 1e-18:
            distance = math.dist(start, cylinder.center_xy)
        else:
            projection = (
                (cylinder.center_xy[0] - start[0]) * delta_x
                + (cylinder.center_xy[1] - start[1]) * delta_y
            ) / length_squared
            projection = min(max(projection, 0.0), 1.0)
            closest = (start[0] + projection * delta_x, start[1] + projection * delta_y)
            distance = math.dist(closest, cylinder.center_xy)
        clearance = distance - robot_radius_m - cylinder.radius_m
        minimum = clearance if minimum is None else min(minimum, clearance)
    return minimum


def _integrate_collision_terminal(
    position: tuple[float, float],
    heading: float,
    velocity: float,
    yaw_rate: float,
    dt_s: float,
    cylinders: Sequence[CylinderObstacle],
    robot_radius_m: float,
) -> tuple[tuple[float, float], float, bool, float | None]:
    """Integrate exact unicycle arcs with conservative swept collision checks."""

    substeps = max(
        1,
        math.ceil(abs(velocity) * dt_s / 0.025),
        math.ceil(abs(yaw_rate) * dt_s / 0.05),
    )
    sub_dt = dt_s / substeps
    cursor = position
    cursor_heading = heading
    minimum_clearance = _minimum_signed_clearance(position, cylinders, robot_radius_m)
    for _ in range(substeps):
        next_position, next_heading = _unicycle_step(
            cursor,
            cursor_heading,
            velocity,
            yaw_rate,
            sub_dt,
        )
        segment_clearance = _segment_minimum_signed_clearance(
            cursor,
            next_position,
            cylinders,
            robot_radius_m,
        )
        if segment_clearance is not None:
            minimum_clearance = (
                segment_clearance
                if minimum_clearance is None
                else min(minimum_clearance, segment_clearance)
            )
        if segment_clearance is not None and segment_clearance <= 0.0:
            return position, heading, True, minimum_clearance
        cursor = next_position
        cursor_heading = next_heading
    return cursor, cursor_heading, False, minimum_clearance


def _point_collides(
    position: tuple[float, float],
    cylinders: Sequence[CylinderObstacle],
    robot_radius_m: float,
) -> bool:
    return any(
        math.dist(position, cylinder.center_xy) <= robot_radius_m + cylinder.radius_m
        for cylinder in cylinders
    )


def _minimum_signed_clearance(
    position: tuple[float, float],
    cylinders: Sequence[CylinderObstacle],
    robot_radius_m: float,
) -> float | None:
    if not cylinders:
        return None
    return min(
        math.dist(position, cylinder.center_xy) - robot_radius_m - cylinder.radius_m
        for cylinder in cylinders
    )


def _latency_summary(samples: Mapping[str, Sequence[float]]) -> dict[str, float]:
    result: dict[str, float] = {}
    for prefix, raw_values in samples.items():
        values = sorted(float(value) for value in raw_values)
        if not values:
            continue
        result[f"{prefix}_count"] = float(len(values))
        result[f"{prefix}_mean_ms"] = fmean(values)
        for label, quantile in (("p50", 0.50), ("p95", 0.95), ("p99", 0.99)):
            index = max(0, min(len(values) - 1, math.ceil(quantile * len(values)) - 1))
            result[f"{prefix}_{label}_ms"] = values[index]
        result[f"{prefix}_max_ms"] = values[-1]
    return result


def _note_phases(note: str) -> tuple[str, str]:
    parts = [part.strip() for part in note.split("|") if part.strip()]
    if not parts:
        return "<none>", "<none>"
    controller = parts[0].split(maxsplit=1)[0]
    safety = (
        "obstacle_stop" if "obstacle_stop" in parts else (parts[-1] if len(parts) > 1 else "<none>")
    )
    return controller, safety


def _append_bounded_trace(
    trace: list[dict[str, Any]],
    item: dict[str, Any],
    *,
    maximum: int,
    force: bool = False,
) -> None:
    if trace and trace[-1]["step"] == item["step"]:
        trace[-1] = item
        return
    if len(trace) < maximum:
        trace.append(item)
    elif force:
        trace[-1] = item


class SensorFaithfulBarnRunner:
    """Execute one calibrated native episode around the exact ROS adapter core."""

    def __init__(
        self,
        world: BarnWorld,
        config: CalibratedBarnConfig | None = None,
    ) -> None:
        if not isinstance(world, BarnWorld):
            raise TypeError("world must be a BarnWorld")
        self._world = world
        self._config = config or CalibratedBarnConfig()

    def run(self, policy: BarnRos2Policy) -> SensorFaithfulEpisodeResult:
        """Run without action evidence, preserving the established API."""

        result, evidence = self._run(policy, evidence_capture=None)
        assert evidence is None
        return result

    def run_with_action_evidence(
        self,
        policy: BarnRos2Policy,
        evidence_capture: V8EpisodeEvidenceCaptureSpec,
    ) -> SensorFaithfulEpisodeWithEvidence:
        """Run with exact post-normalization/final-command evidence capture."""

        if not isinstance(evidence_capture, V8EpisodeEvidenceCaptureSpec):
            raise TypeError("evidence_capture must be a V8EpisodeEvidenceCaptureSpec")
        if evidence_capture.world_id != self._world.world_index:
            raise ValueError("evidence world_id does not match the calibrated world")
        if not math.isclose(
            self._config.dt_s,
            FROZEN_V8_BARN_EVALUATOR_PROFILE.control_period_s,
            rel_tol=0.0,
            abs_tol=1e-12,
        ):
            raise ValueError("v8 action evidence requires the frozen 0.1 s control period")
        result, evidence = self._run(policy, evidence_capture=evidence_capture)
        assert evidence is not None
        return SensorFaithfulEpisodeWithEvidence(result=result, action_evidence=evidence)

    def _run(
        self,
        policy: BarnRos2Policy,
        *,
        evidence_capture: V8EpisodeEvidenceCaptureSpec | None,
    ) -> tuple[SensorFaithfulEpisodeResult, V8ActionEvidenceBuilder | None]:
        if not isinstance(policy, BarnRos2Policy):
            raise TypeError("policy must implement reset(), act(), and close()")
        instrumented = _InstrumentedPolicy(policy)
        action_evidence = V8ActionEvidenceBuilder() if evidence_capture is not None else None
        core: BarnRos2AdapterCore | None = None
        try:
            core = BarnRos2AdapterCore(
                instrumented,
                goal_xy=BARN_ROS2_STATIC_GOAL_ODOM_XY,
                lidar_calibration=BARN_ROS2_LIDAR_CALIBRATION,
                require_lidar_calibration=True,
                max_sensor_skew_s=self._config.max_sensor_skew_s,
            )
            result = self._run_with_core(
                core,
                instrumented,
                action_evidence=action_evidence,
                evidence_capture=evidence_capture,
            )
            return result, action_evidence
        finally:
            if core is not None:
                core.close()
            else:
                instrumented.close()

    def _run_with_core(
        self,
        core: BarnRos2AdapterCore,
        instrumented: _InstrumentedPolicy,
        *,
        action_evidence: V8ActionEvidenceBuilder | None = None,
        evidence_capture: V8EpisodeEvidenceCaptureSpec | None = None,
    ) -> SensorFaithfulEpisodeResult:
        if (action_evidence is None) != (evidence_capture is None):
            raise ValueError(
                "action evidence builder and capture identity must be supplied together"
            )
        config = self._config
        position = OFFICIAL_START_XY
        heading = config.start_heading_rad
        simulation_elapsed = 0.0
        elapsed = 0.0
        trial_started = False
        startup_time: float | None = None
        traveled = 0.0
        steps = 0
        collided = _point_collides(position, self._world.cylinders, config.robot_radius_m)
        stopped = False
        stop_latch_step: int | None = None
        last_note = ""
        max_steps = math.ceil((config.startup_timeout_s + config.timeout_s) / config.dt_s)

        initial_goal_distance = math.dist(position, OFFICIAL_GOAL_XY)
        closest_goal_distance = initial_goal_distance
        closest_goal_time = 0.0
        initial_clearance = _minimum_signed_clearance(
            position,
            self._world.cylinders,
            config.robot_radius_m,
        )
        minimum_clearance = initial_clearance
        clearance_sum = 0.0 if initial_clearance is None else initial_clearance
        clearance_count = 0 if initial_clearance is None else 1

        normalizations: list[LidarNormalizationDiagnostics] = []
        raw_scan_hashes: list[str] = []
        observation_steps: list[int] = []
        action_steps: list[int] = []
        action_hashes: list[str] = []
        action_note_hashes: list[str] = []
        action_values: list[tuple[int, float, float, bool]] = []
        latency_samples: dict[str, list[float]] = {
            "raw_lidar_cast": [],
            "calibrated_adapter_core_step": [],
        }
        controller_phases: Counter[str] = Counter()
        safety_phases: Counter[str] = Counter()
        positive_steps = 0
        reverse_steps = 0
        turn_only_steps = 0
        obstacle_stop_steps = 0
        obstacle_stop_command_steps: list[int] = []
        consecutive_obstacle_stop = 0
        maximum_consecutive_obstacle_stop = 0
        previous_phase: tuple[str, str] | None = None
        last_evidence_observation: BarnObservation | None = None
        last_evidence_observation_sha256: str | None = None
        previous_interval: (
            tuple[
                tuple[float, float],
                float,
                float,
                float,
                float,
            ]
            | None
        ) = None
        trace: list[dict[str, Any]] = []

        while not collided and steps < max_steps:
            if math.dist(position, OFFICIAL_GOAL_XY) <= config.success_radius_m:
                break
            if trial_started and elapsed >= config.timeout_s - 1e-12:
                elapsed = config.timeout_s
                break
            if not trial_started and simulation_elapsed >= config.startup_timeout_s - 1e-12:
                simulation_elapsed = config.startup_timeout_s
                break

            odom_world_position = position
            odom_world_heading = heading
            if previous_interval is not None:
                prior_position, prior_heading, prior_velocity, prior_yaw_rate, prior_dt = (
                    previous_interval
                )
                odom_dt = max(0.0, prior_dt - config.odometry_lag_s)
                odom_world_position, odom_world_heading = _unicycle_step(
                    prior_position,
                    prior_heading,
                    prior_velocity,
                    prior_yaw_rate,
                    odom_dt,
                )
            odom_position, odom_heading = world_pose_to_odom(
                odom_world_position,
                odom_world_heading,
            )

            if stop_latch_step is None:
                scan_started = time.perf_counter_ns()
                raw_ranges = cast_sensor_faithful_lidar(
                    position,
                    heading,
                    self._world.cylinders,
                    config=config,
                )
                latency_samples["raw_lidar_cast"].append(
                    (time.perf_counter_ns() - scan_started) / 1e6
                )
                raw_ranges = tuple(_laser_scan_float32(value) for value in raw_ranges)
                raw_scan_hashes.append(_scan_sha256(raw_ranges))
                stamp = config.sensor_stamp_origin_s + simulation_elapsed
                frame = BarnRos2SensorFrame(
                    stamp_s=stamp,
                    position_xy=odom_position,
                    heading_rad=odom_heading,
                    lidar_ranges_m=raw_ranges,
                    lidar_angle_min_rad=_laser_scan_float32(config.lidar_angle_min_rad),
                    lidar_angle_increment_rad=_laser_scan_float32(
                        (config.lidar_angle_max_rad - config.lidar_angle_min_rad)
                        / (config.lidar_ray_count - 1)
                    ),
                    lidar_range_min_m=_laser_scan_float32(config.lidar_range_min_m),
                    lidar_range_max_m=_laser_scan_float32(config.lidar_range_max_m),
                    odometry_stamp_s=stamp - config.odometry_lag_s,
                    lidar_frame_id=BARN_ROS2_LIDAR_FRAME_ID,
                    odometry_child_frame_id=BARN_ROS2_BASE_FRAME_ID,
                )
                adapter_started = time.perf_counter_ns()
                command = core.step(frame)
                latency_samples["calibrated_adapter_core_step"].append(
                    (time.perf_counter_ns() - adapter_started) / 1e6
                )
                last_evidence_observation = instrumented.last_observation
                if last_evidence_observation is None:
                    raise RuntimeError("calibrated adapter omitted the policy observation")
                last_evidence_observation_sha256 = instrumented.observation_hashes[-1]
                observation_steps.append(steps)
                normalization = core.last_normalization_diagnostics
                if normalization is None:
                    raise RuntimeError("calibrated adapter omitted normalization diagnostics")
                normalizations.append(normalization)
                last_note = command.note
                if command.stop:
                    stopped = True
                    stop_latch_step = steps
            else:
                # Official evaluator semantics: a policy stop does not end the
                # external episode.  Zero remains latched until success/timeout.
                command = BarnRos2VelocityCommand(
                    0.0,
                    0.0,
                    stop=True,
                    note="policy_stop_latched",
                )

            action_steps.append(steps)
            action_hashes.append(_published_action_sha256(command))
            action_note_hashes.append(_action_note_sha256(command))
            action_values.append(
                (steps, float(command.forward_mps), float(command.yaw_rate_rps), command.stop)
            )
            controller_phase, safety_phase = _note_phases(command.note)
            controller_phases[controller_phase] += 1
            safety_phases[safety_phase] += 1
            issued_by_policy = stop_latch_step is None or steps == stop_latch_step
            if action_evidence is not None:
                assert evidence_capture is not None
                if last_evidence_observation is None:
                    raise RuntimeError("action evidence has no normalized observation to bind")
                if last_evidence_observation_sha256 is None:
                    raise RuntimeError("action evidence has no complete observation hash to bind")
                action_evidence.append(
                    step_index=steps,
                    execution_order=evidence_capture.execution_order,
                    arm=evidence_capture.arm,
                    world_id=evidence_capture.world_id,
                    trial_id=evidence_capture.trial_id,
                    seed=evidence_capture.seed,
                    issued_by_policy=issued_by_policy,
                    observation_reused=not issued_by_policy,
                    normalized_scan_m=last_evidence_observation.lidar_ranges_m,
                    angle_min_rad=last_evidence_observation.lidar_angle_min_rad,
                    angle_increment_rad=last_evidence_observation.lidar_angle_increment_rad,
                    published_vx_mps=command.forward_mps,
                    published_vy_mps=0.0,
                    published_yaw_rate_rps=command.yaw_rate_rps,
                    published_stop=command.stop,
                    note=command.note,
                    policy_observation_sha256=last_evidence_observation_sha256,
                )
            if issued_by_policy:
                if command.forward_mps >= 0.005:
                    positive_steps += 1
                elif command.forward_mps <= -0.005:
                    reverse_steps += 1
                elif abs(command.yaw_rate_rps) >= 0.005 and not command.stop:
                    turn_only_steps += 1
            is_obstacle_stop = (
                issued_by_policy
                and not command.stop
                and abs(command.forward_mps) < 0.005
                and safety_phase == "obstacle_stop"
            )
            if is_obstacle_stop:
                obstacle_stop_steps += 1
                obstacle_stop_command_steps.append(steps)
                consecutive_obstacle_stop += 1
                maximum_consecutive_obstacle_stop = max(
                    maximum_consecutive_obstacle_stop,
                    consecutive_obstacle_stop,
                )
            else:
                consecutive_obstacle_stop = 0

            velocity = min(
                max(command.forward_mps, -config.max_reverse_speed_mps),
                config.max_forward_speed_mps,
            )
            yaw_rate = min(
                max(command.yaw_rate_rps, -config.max_yaw_rate_rps),
                config.max_yaw_rate_rps,
            )
            phase = (controller_phase, safety_phase)
            should_trace = steps % config.trace_stride_steps == 0 or phase != previous_phase
            trace_item = {
                "step": steps,
                "time_s": simulation_elapsed,
                "trial_elapsed_time_s": elapsed,
                "trial_started": trial_started,
                "world_position_xy": position,
                "world_heading_rad": heading,
                "odom_position_xy": odom_position,
                "odom_heading_rad": odom_heading,
                "published_forward_mps": command.forward_mps,
                "published_yaw_rate_rps": command.yaw_rate_rps,
                "published_stop": command.stop,
                "controller_phase": controller_phase,
                "safety_phase": safety_phase,
                "note": command.note[:240],
                "policy_observation_sha256": (
                    instrumented.observation_hashes[-1] if issued_by_policy else None
                ),
                "published_action_sha256": action_hashes[-1],
            }
            if should_trace:
                _append_bounded_trace(
                    trace,
                    trace_item,
                    maximum=config.trace_max_samples,
                )
            previous_phase = phase

            remaining = (
                config.timeout_s - elapsed
                if trial_started
                else config.startup_timeout_s - simulation_elapsed
            )
            step_dt = min(config.dt_s, remaining)
            step_start_position = position
            step_start_heading = heading
            startup_crossing_dt = (
                None
                if trial_started
                else _first_translation_threshold_crossing_s(
                    initial_position=OFFICIAL_START_XY,
                    step_position=step_start_position,
                    step_heading=step_start_heading,
                    velocity=velocity,
                    yaw_rate=yaw_rate,
                    dt_s=step_dt,
                    threshold_m=config.trial_start_translation_m,
                )
            )
            next_position, next_heading, collided, swept_clearance = _integrate_collision_terminal(
                position,
                heading,
                velocity,
                yaw_rate,
                step_dt,
                self._world.cylinders,
                config.robot_radius_m,
            )
            previous_interval = (
                step_start_position,
                step_start_heading,
                velocity,
                yaw_rate,
                step_dt,
            )
            if swept_clearance is not None:
                minimum_clearance = (
                    swept_clearance
                    if minimum_clearance is None
                    else min(minimum_clearance, swept_clearance)
                )
            if not collided:
                traveled += math.dist(position, next_position)
                position = next_position
                heading = next_heading
            steps += 1
            simulation_elapsed = min(
                config.startup_timeout_s + config.timeout_s,
                simulation_elapsed + step_dt,
            )
            if trial_started:
                elapsed = min(config.timeout_s, elapsed + step_dt)
            elif not collided and startup_crossing_dt is not None:
                # The official scorer polls Gazebo continuously enough to begin
                # within a 100 ms policy tick. Interpolate that first crossing
                # so only the pre-crossing portion is unscored.
                trial_started = True
                startup_time = simulation_elapsed - step_dt + startup_crossing_dt
                elapsed = min(config.timeout_s, step_dt - startup_crossing_dt)
            if elapsed >= config.timeout_s - 1e-12:
                elapsed = config.timeout_s
            if collided:
                minimum_clearance = (
                    0.0 if minimum_clearance is None else min(minimum_clearance, 0.0)
                )
                clearance_sum += 0.0
                clearance_count += 1
            else:
                goal_distance = math.dist(position, OFFICIAL_GOAL_XY)
                if goal_distance < closest_goal_distance:
                    closest_goal_distance = goal_distance
                    closest_goal_time = elapsed
                clearance = _minimum_signed_clearance(
                    position,
                    self._world.cylinders,
                    config.robot_radius_m,
                )
                if clearance is not None:
                    minimum_clearance = (
                        clearance
                        if minimum_clearance is None
                        else min(minimum_clearance, clearance)
                    )
                    clearance_sum += clearance
                    clearance_count += 1

        success = not collided and math.dist(position, OFFICIAL_GOAL_XY) <= config.success_radius_m
        startup_timed_out = (
            not collided
            and not success
            and not trial_started
            and simulation_elapsed >= config.startup_timeout_s
        )
        timed_out = startup_timed_out or (
            not collided and not success and trial_started and elapsed >= config.timeout_s
        )
        status = (
            "collided"
            if collided
            else (
                "succeeded" if success else ("startup_timeout" if startup_timed_out else "timeout")
            )
        )
        if action_steps:
            final_odom_position, final_odom_heading = world_pose_to_odom(position, heading)
            final_trace = {
                "step": steps,
                "time_s": simulation_elapsed,
                "trial_elapsed_time_s": elapsed,
                "trial_started": trial_started,
                "world_position_xy": position,
                "world_heading_rad": heading,
                "odom_position_xy": final_odom_position,
                "odom_heading_rad": final_odom_heading,
                "published_forward_mps": 0.0 if stopped else action_values[-1][1],
                "published_yaw_rate_rps": 0.0 if stopped else action_values[-1][2],
                "published_stop": stopped,
                "controller_phase": "terminal",
                "safety_phase": "<none>",
                "note": status,
                "policy_observation_sha256": None,
                "published_action_sha256": action_hashes[-1],
            }
            _append_bounded_trace(
                trace,
                final_trace,
                maximum=config.trace_max_samples,
                force=True,
            )

        sensor = SensorTransportDiagnostics(
            profile_id=BARN_ROS2_ADAPTER_ID,
            raw_fov_deg=CALIBRATED_LIDAR_FOV_DEG,
            raw_ray_count=config.lidar_ray_count,
            lidar_forward_m=config.lidar_forward_m,
            frame_count=len(normalizations),
            normalization_failures=0,
            finite_hit_count=sum(item.finite_hit_count for item in normalizations),
            self_return_count=sum(item.self_return_count for item in normalizations),
            reprojected_hit_count=sum(item.reprojected_hit_count for item in normalizations),
            reprojected_clear_count=sum(item.reprojected_clear_count for item in normalizations),
            first_normalization=(asdict(normalizations[0]) if normalizations else None),
            last_normalization=(asdict(normalizations[-1]) if normalizations else None),
            maximum_sensor_skew_s=max(
                (abs(item.lidar_stamp_s - item.odometry_stamp_s) for item in normalizations),
                default=0.0,
            ),
            raw_scan_sha256=tuple(raw_scan_hashes),
            policy_observation_steps=tuple(observation_steps),
            policy_observation_sha256=tuple(instrumented.observation_hashes),
            published_action_steps=tuple(action_steps),
            published_action_sha256=tuple(action_hashes),
            published_action_note_sha256=tuple(action_note_hashes),
            published_action_values=tuple(action_values),
            latency=_latency_summary(latency_samples),
        )
        shield = ShieldStallDiagnostics(
            policy_stop_latched=stopped,
            policy_stop_latch_step=stop_latch_step,
            issued_policy_command_steps=len(observation_steps),
            positive_command_steps=positive_steps,
            reverse_command_steps=reverse_steps,
            turn_only_command_steps=turn_only_steps,
            obstacle_stop_steps=obstacle_stop_steps,
            obstacle_stop_command_steps=tuple(obstacle_stop_command_steps),
            max_consecutive_obstacle_stop_steps=maximum_consecutive_obstacle_stop,
            controller_phase_counts=dict(sorted(controller_phases.items())),
            safety_phase_counts=dict(sorted(safety_phases.items())),
            trace=tuple(trace),
        )
        return self._result(
            success=success,
            collided=collided,
            timed_out=timed_out,
            startup_timed_out=startup_timed_out,
            stopped=stopped,
            status=status,
            trial_started=trial_started,
            startup_time=startup_time,
            simulation_elapsed=simulation_elapsed,
            elapsed=elapsed,
            traveled=traveled,
            position=position,
            heading=heading,
            steps=steps,
            last_note=last_note,
            initial_goal_distance=initial_goal_distance,
            closest_goal_distance=closest_goal_distance,
            closest_goal_time=closest_goal_time,
            minimum_clearance=minimum_clearance,
            clearance_sum=clearance_sum,
            clearance_count=clearance_count,
            sensor=sensor,
            shield=shield,
        )

    def _result(
        self,
        *,
        success: bool,
        collided: bool,
        timed_out: bool,
        startup_timed_out: bool,
        stopped: bool,
        status: str,
        trial_started: bool,
        startup_time: float | None,
        simulation_elapsed: float,
        elapsed: float,
        traveled: float,
        position: tuple[float, float],
        heading: float,
        steps: int,
        last_note: str,
        initial_goal_distance: float,
        closest_goal_distance: float,
        closest_goal_time: float,
        minimum_clearance: float | None,
        clearance_sum: float,
        clearance_count: int,
        sensor: SensorTransportDiagnostics,
        shield: ShieldStallDiagnostics,
    ) -> SensorFaithfulEpisodeResult:
        length = self._world.optimal_path_length_m
        final_goal_distance = math.dist(position, OFFICIAL_GOAL_XY)
        net_progress = initial_goal_distance - final_goal_distance
        maximum_progress = initial_goal_distance - closest_goal_distance
        evaluator = BarnEvaluatorDiagnostics(
            evaluator_private_state=True,
            initial_goal_distance_m=initial_goal_distance,
            closest_goal_distance_m=closest_goal_distance,
            closest_goal_time_s=closest_goal_time,
            final_goal_distance_m=final_goal_distance,
            net_goal_progress_m=net_progress,
            maximum_goal_progress_m=maximum_progress,
            maximum_goal_progress_fraction=maximum_progress / initial_goal_distance,
            goal_progress_efficiency=(maximum_progress / traveled if traveled > 0.0 else 0.0),
            minimum_signed_obstacle_clearance_m=minimum_clearance,
            mean_signed_obstacle_clearance_m=(
                clearance_sum / clearance_count if clearance_count else None
            ),
            clearance_sample_count=clearance_count,
            traveled_to_reference_path_ratio=traveled / length,
            successful_reference_route_efficiency=(
                length / traveled if success and traveled > 0.0 else None
            ),
            mean_translational_speed_mps=(
                traveled / simulation_elapsed if simulation_elapsed > 0.0 else 0.0
            ),
        )
        return SensorFaithfulEpisodeResult(
            evaluation_kind=BARN_SENSOR_FAITHFUL_EVALUATION_KIND,
            official_gazebo_score=False,
            world_index=self._world.world_index,
            success=success,
            collided=collided,
            timed_out=timed_out,
            startup_timed_out=startup_timed_out,
            stopped=stopped,
            status=status,
            trial_started=trial_started,
            startup_time_s=startup_time,
            simulation_elapsed_time_s=simulation_elapsed,
            elapsed_time_s=elapsed,
            navigation_metric=barn_navigation_metric(success, elapsed, length),
            optimal_path_length_m=length,
            optimal_time_s=length / OFFICIAL_REFERENCE_SPEED_MPS,
            traveled_distance_m=traveled,
            final_position_xy=position,
            final_heading_rad=heading,
            steps=steps,
            last_action_note=last_note,
            evaluator_diagnostics=evaluator,
            sensor_diagnostics=sensor,
            shield_stall_diagnostics=shield,
        )


@dataclass(frozen=True, slots=True)
class _EpisodeRequest:
    world: BarnWorld
    config: CalibratedBarnConfig
    trial: int
    episode_seed: int
    process_policy: ProcessPolicyDescriptor | IsolatedPolicyDescriptor
    action_evidence: V8EpisodeEvidenceCaptureSpec | None = None


@dataclass(frozen=True, slots=True)
class _EpisodeExecution:
    detail: dict[str, Any]
    latency_samples_ms: dict[str, tuple[float, ...]]
    policy_diagnostics: dict[str, Any]
    action_evidence: V8ActionEvidenceBuilder | None = None


@dataclass(frozen=True, slots=True)
class _PairedEpisodeRequest:
    """Pickle-safe recipe for one sequential, counterbalanced A/B pair."""

    world: BarnWorld
    config: CalibratedBarnConfig
    trial: int
    episode_seed: int
    reference_policy: ProcessPolicyDescriptor | IsolatedPolicyDescriptor
    candidate_policy: ProcessPolicyDescriptor | IsolatedPolicyDescriptor
    arm_order: PairedArmOrder
    reference_action_evidence: V8EpisodeEvidenceCaptureSpec | None = None
    candidate_action_evidence: V8EpisodeEvidenceCaptureSpec | None = None


@dataclass(frozen=True, slots=True)
class _PairedEpisodeExecution:
    """Role-stable results from two arms that were never run concurrently."""

    world_index: int
    trial: int
    episode_seed: int
    arm_order: PairedArmOrder
    reference: _EpisodeExecution
    candidate: _EpisodeExecution


def alternating_paired_arm_order_schedule(
    pair_count: int,
) -> tuple[PairedArmOrder, ...]:
    """Return the deterministic reference-first/candidate-first alternation."""

    if isinstance(pair_count, bool) or not isinstance(pair_count, int) or pair_count < 1:
        raise ValueError("pair_count must be a positive integer")
    return tuple(
        REFERENCE_THEN_CANDIDATE if index % 2 == 0 else CANDIDATE_THEN_REFERENCE
        for index in range(pair_count)
    )


def validate_paired_arm_order_schedule(
    schedule: Sequence[str],
    *,
    pair_count: int,
) -> tuple[PairedArmOrder, ...]:
    """Validate exact membership, length, and first-position counterbalancing."""

    if isinstance(pair_count, bool) or not isinstance(pair_count, int) or pair_count < 1:
        raise ValueError("pair_count must be a positive integer")
    if isinstance(schedule, (str, bytes)):
        raise TypeError("arm_order_schedule must be a sequence of order labels")
    raw_orders = tuple(schedule)
    if len(raw_orders) != pair_count:
        raise ValueError(
            "arm_order_schedule must contain exactly one order for every world/trial pair"
        )
    allowed = {REFERENCE_THEN_CANDIDATE, CANDIDATE_THEN_REFERENCE}
    if any(not isinstance(order, str) or order not in allowed for order in raw_orders):
        raise ValueError("arm_order_schedule contains an unsupported order label")
    reference_first = raw_orders.count(REFERENCE_THEN_CANDIDATE)
    candidate_first = raw_orders.count(CANDIDATE_THEN_REFERENCE)
    if abs(reference_first - candidate_first) > 1:
        raise ValueError("arm_order_schedule must counterbalance first position")
    return tuple(cast(PairedArmOrder, order) for order in raw_orders)


def _execute_episode(
    *,
    world: BarnWorld,
    config: CalibratedBarnConfig,
    policy: BarnRos2Policy,
    trial: int,
    episode_seed: int,
    action_evidence: V8EpisodeEvidenceCaptureSpec | None = None,
) -> _EpisodeExecution:
    runner = SensorFaithfulBarnRunner(world, config)
    if action_evidence is None:
        result = runner.run(policy)
        evidence_builder = None
    else:
        evidence_run = runner.run_with_action_evidence(policy, action_evidence)
        result = evidence_run.result
        evidence_builder = evidence_run.action_evidence
    latency_samples_fn = getattr(policy, "latency_samples_ms", None)
    policy_diagnostics_fn = getattr(policy, "policy_diagnostics", None)
    raw_latency = latency_samples_fn() if callable(latency_samples_fn) else {}
    policy_diagnostics = policy_diagnostics_fn() if callable(policy_diagnostics_fn) else {}
    if not isinstance(policy_diagnostics, dict):
        policy_diagnostics = {}
    normalized_latency: dict[str, tuple[float, ...]] = {}
    if not isinstance(raw_latency, Mapping):
        raise TypeError("policy latency samples must be a mapping")
    for name, values in raw_latency.items():
        if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
            raise TypeError("policy latency sample groups must be numeric sequences")
        if any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in values):
            raise TypeError("policy latency samples must be numeric and not boolean")
        samples = tuple(float(value) for value in values)
        if any(not math.isfinite(value) or value < 0.0 for value in samples):
            raise ValueError("policy latency samples must be finite and non-negative")
        normalized_latency[str(name)] = samples
    detail = asdict(result)
    detail["trial"] = int(trial)
    detail["episode_seed"] = int(episode_seed)
    detail["final_distance_to_goal_m"] = math.dist(result.final_position_xy, OFFICIAL_GOAL_XY)
    latency_metrics_fn = getattr(policy, "latency_metrics", None)
    detail["latency"] = {
        **result.sensor_diagnostics.latency,
        **(latency_metrics_fn() if callable(latency_metrics_fn) else {}),
    }
    detail["policy_diagnostics"] = policy_diagnostics
    detail["evaluator_controller_step_latency_samples_ms"] = normalized_latency.get(
        "controller_step", ()
    )
    return _EpisodeExecution(
        detail=detail,
        latency_samples_ms=normalized_latency,
        policy_diagnostics=policy_diagnostics,
        action_evidence=evidence_builder,
    )


def _execute_descriptor_episode(
    descriptor: ProcessPolicyDescriptor | IsolatedPolicyDescriptor,
    *,
    world: BarnWorld,
    config: CalibratedBarnConfig,
    trial: int,
    episode_seed: int,
    action_evidence: V8EpisodeEvidenceCaptureSpec | None = None,
) -> _EpisodeExecution:
    policy = descriptor.create(episode_seed=episode_seed)
    if not isinstance(policy, BarnRos2Policy):
        raise TypeError("process descriptor policy must implement the calibrated policy API")
    return _execute_episode(
        world=world,
        config=config,
        policy=policy,
        trial=trial,
        episode_seed=episode_seed,
        action_evidence=action_evidence,
    )


def _run_process_episode(request: _EpisodeRequest) -> _EpisodeExecution:
    return _execute_descriptor_episode(
        request.process_policy,
        world=request.world,
        config=request.config,
        trial=request.trial,
        episode_seed=request.episode_seed,
        action_evidence=request.action_evidence,
    )


def _run_paired_process_episode(request: _PairedEpisodeRequest) -> _PairedEpisodeExecution:
    """Run one arm to completion and close it before constructing the other."""

    common = {
        "world": request.world,
        "config": request.config,
        "trial": request.trial,
        "episode_seed": request.episode_seed,
    }
    if request.arm_order == REFERENCE_THEN_CANDIDATE:
        reference = _execute_descriptor_episode(
            request.reference_policy,
            action_evidence=request.reference_action_evidence,
            **common,
        )
        candidate = _execute_descriptor_episode(
            request.candidate_policy,
            action_evidence=request.candidate_action_evidence,
            **common,
        )
    elif request.arm_order == CANDIDATE_THEN_REFERENCE:
        candidate = _execute_descriptor_episode(
            request.candidate_policy,
            action_evidence=request.candidate_action_evidence,
            **common,
        )
        reference = _execute_descriptor_episode(
            request.reference_policy,
            action_evidence=request.reference_action_evidence,
            **common,
        )
    else:  # pragma: no cover - requests are validated before process submission.
        raise ValueError(f"unsupported paired arm order: {request.arm_order!r}")
    return _PairedEpisodeExecution(
        world_index=request.world.world_index,
        trial=request.trial,
        episode_seed=request.episode_seed,
        arm_order=request.arm_order,
        reference=reference,
        candidate=candidate,
    )


def _execute_spec_episode(
    spec: CalibratedPolicySpec,
    *,
    world: BarnWorld,
    config: CalibratedBarnConfig,
    trial: int,
    episode_seed: int,
    allow_experimental: bool,
    action_evidence: V8EpisodeEvidenceCaptureSpec | None = None,
) -> _EpisodeExecution:
    policy = spec.create(
        episode_seed=episode_seed,
        allow_experimental=allow_experimental,
    )
    return _execute_episode(
        world=world,
        config=config,
        policy=policy,
        trial=trial,
        episode_seed=episode_seed,
        action_evidence=action_evidence,
    )


def _run_paired_local_episode(
    *,
    world: BarnWorld,
    config: CalibratedBarnConfig,
    trial: int,
    episode_seed: int,
    reference: CalibratedPolicySpec,
    candidate: CalibratedPolicySpec,
    arm_order: PairedArmOrder,
    reference_action_evidence: V8EpisodeEvidenceCaptureSpec | None = None,
    candidate_action_evidence: V8EpisodeEvidenceCaptureSpec | None = None,
) -> _PairedEpisodeExecution:
    """Local equivalent of the spawned pair with the same serial lifecycle."""

    common = {
        "world": world,
        "config": config,
        "trial": trial,
        "episode_seed": episode_seed,
    }
    if arm_order == REFERENCE_THEN_CANDIDATE:
        reference_execution = _execute_spec_episode(
            reference,
            allow_experimental=False,
            action_evidence=reference_action_evidence,
            **common,
        )
        candidate_execution = _execute_spec_episode(
            candidate,
            allow_experimental=True,
            action_evidence=candidate_action_evidence,
            **common,
        )
    elif arm_order == CANDIDATE_THEN_REFERENCE:
        candidate_execution = _execute_spec_episode(
            candidate,
            allow_experimental=True,
            action_evidence=candidate_action_evidence,
            **common,
        )
        reference_execution = _execute_spec_episode(
            reference,
            allow_experimental=False,
            action_evidence=reference_action_evidence,
            **common,
        )
    else:  # pragma: no cover - schedules are validated before execution.
        raise ValueError(f"unsupported paired arm order: {arm_order!r}")
    return _PairedEpisodeExecution(
        world_index=world.world_index,
        trial=trial,
        episode_seed=episode_seed,
        arm_order=arm_order,
        reference=reference_execution,
        candidate=candidate_execution,
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _relative_source_id(path: Path) -> str:
    resolved = path.resolve()
    repo_root = Path(__file__).resolve().parents[2]
    try:
        return resolved.relative_to(repo_root).as_posix()
    except ValueError:
        return str(resolved)


def _world_provenance(world: BarnWorld) -> dict[str, Any]:
    return {
        "world_index": world.world_index,
        "world": (
            None
            if world.world_path is None
            else {
                "id": _relative_source_id(world.world_path),
                "sha256": _sha256(world.world_path),
            }
        ),
        "reference_path": (
            None
            if world.path_path is None
            else {
                "id": _relative_source_id(world.path_path),
                "sha256": _sha256(world.path_path),
            }
        ),
    }


def _config_sha256(config: CalibratedBarnConfig) -> str:
    payload = json.dumps(asdict(config), sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _validate_manifest_hash(value: str | None) -> str:
    if (
        value is None
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError("generated corpus requires its lowercase SHA-256 manifest hash")
    return value


def _aggregate_executions(
    executions: Sequence[_EpisodeExecution],
    *,
    world_count: int,
    trials: int,
    long_shield_stall_steps: int,
) -> dict[str, Any]:
    episodes = [execution.detail for execution in executions]
    count = len(episodes)
    succeeded = [episode for episode in episodes if bool(episode["success"])]
    outcomes = Counter(str(episode["status"]) for episode in episodes)
    latency_samples: dict[str, list[float]] = {}
    policy_controller_phases: Counter[str] = Counter()
    policy_safety_phases: Counter[str] = Counter()
    for execution in executions:
        for name, values in execution.latency_samples_ms.items():
            latency_samples.setdefault(name, []).extend(values)
        policy_controller_phases.update(
            {
                str(name): int(value)
                for name, value in execution.policy_diagnostics.get(
                    "controller_phase_counts", {}
                ).items()
            }
        )
        policy_safety_phases.update(
            {
                str(name): int(value)
                for name, value in execution.policy_diagnostics.get(
                    "safety_phase_counts", {}
                ).items()
            }
        )
    evaluator_items = [episode["evaluator_diagnostics"] for episode in episodes]
    clearances = [
        float(item["minimum_signed_obstacle_clearance_m"])
        for item in evaluator_items
        if item["minimum_signed_obstacle_clearance_m"] is not None
    ]
    route_efficiencies = [
        float(item["successful_reference_route_efficiency"])
        for item in evaluator_items
        if item["successful_reference_route_efficiency"] is not None
    ]
    shields = [episode["shield_stall_diagnostics"] for episode in episodes]
    sensors = [episode["sensor_diagnostics"] for episode in episodes]
    long_stall_count = sum(
        int(item["max_consecutive_obstacle_stop_steps"]) >= long_shield_stall_steps
        for item in shields
    )
    return {
        "episodes": float(count),
        "worlds": float(world_count),
        "trials_per_world": float(trials),
        "success_rate": sum(bool(episode["success"]) for episode in episodes) / count,
        "navigation_metric": fmean(float(episode["navigation_metric"]) for episode in episodes),
        "collision_rate": sum(bool(episode["collided"]) for episode in episodes) / count,
        "timeout_rate": sum(str(episode["status"]) == "timeout" for episode in episodes) / count,
        "startup_failure_rate": sum(bool(episode["startup_timed_out"]) for episode in episodes)
        / count,
        # A policy stop is a timeout-latched zero command in this evaluator.
        "stopped_outside_goal_rate": 0.0,
        "policy_stop_latch_rate": sum(bool(episode["stopped"]) for episode in episodes) / count,
        "mean_elapsed_time_s": fmean(float(episode["elapsed_time_s"]) for episode in episodes),
        "mean_success_time_s": (
            fmean(float(episode["elapsed_time_s"]) for episode in succeeded) if succeeded else 0.0
        ),
        "mean_final_distance_to_goal_m": fmean(
            float(episode["final_distance_to_goal_m"]) for episode in episodes
        ),
        "mean_traveled_distance_m": fmean(
            float(episode["traveled_distance_m"]) for episode in episodes
        ),
        **_latency_summary(latency_samples),
        "sensor_diagnostics": {
            "long_shield_stall_threshold_steps": long_shield_stall_steps,
            "long_shield_stall_episode_count": long_stall_count,
            "sensor_normalization_failures": sum(
                int(item["normalization_failures"]) for item in sensors
            ),
            "reverse_command_steps": sum(int(item["reverse_command_steps"]) for item in shields),
            "obstacle_stop_steps": sum(int(item["obstacle_stop_steps"]) for item in shields),
            "max_consecutive_obstacle_stop_steps": max(
                (int(item["max_consecutive_obstacle_stop_steps"]) for item in shields),
                default=0,
            ),
            "normalized_frame_count": sum(int(item["frame_count"]) for item in sensors),
            "self_return_count": sum(int(item["self_return_count"]) for item in sensors),
        },
        "evaluator_diagnostics": {
            "private_state_not_exposed_to_policy": True,
            "outcome_counts": dict(sorted(outcomes.items())),
            "failure_counts": {
                key: value for key, value in sorted(outcomes.items()) if key != "succeeded"
            },
            "mean_net_goal_progress_m": fmean(
                float(item["net_goal_progress_m"]) for item in evaluator_items
            ),
            "mean_maximum_goal_progress_m": fmean(
                float(item["maximum_goal_progress_m"]) for item in evaluator_items
            ),
            "mean_maximum_goal_progress_fraction": fmean(
                float(item["maximum_goal_progress_fraction"]) for item in evaluator_items
            ),
            "mean_goal_progress_efficiency": fmean(
                float(item["goal_progress_efficiency"]) for item in evaluator_items
            ),
            "mean_closest_goal_distance_m": fmean(
                float(item["closest_goal_distance_m"]) for item in evaluator_items
            ),
            "minimum_signed_obstacle_clearance_m": min(clearances) if clearances else None,
            "mean_episode_minimum_signed_obstacle_clearance_m": (
                fmean(clearances) if clearances else None
            ),
            "mean_traveled_to_reference_path_ratio": fmean(
                float(item["traveled_to_reference_path_ratio"]) for item in evaluator_items
            ),
            "mean_successful_reference_route_efficiency": (
                fmean(route_efficiencies) if route_efficiencies else None
            ),
            "mean_translational_speed_mps": fmean(
                float(item["mean_translational_speed_mps"]) for item in evaluator_items
            ),
        },
        "policy_diagnostics": {
            "controller_phase_counts": dict(sorted(policy_controller_phases.items())),
            "safety_phase_counts": dict(sorted(policy_safety_phases.items())),
            "note": "Policy-provided notes are diagnostics, not evaluator failure labels.",
        },
    }


def _build_sensor_faithful_report(
    *,
    world_indices: Sequence[int],
    worlds: Sequence[BarnWorld],
    spec: CalibratedPolicySpec,
    executions: Sequence[_EpisodeExecution],
    trials: int,
    suite_seed: int,
    workers: int,
    effective_workers: int,
    process_start_method: str | None,
    config: CalibratedBarnConfig,
    generated_corpus: bool,
    manifest_hash: str | None,
    long_shield_stall_steps: int,
) -> dict[str, Any]:
    """Build the established suite schema from already completed episodes."""

    aggregate = _aggregate_executions(
        executions,
        world_count=len(worlds),
        trials=trials,
        long_shield_stall_steps=long_shield_stall_steps,
    )
    harness_path = Path(__file__).resolve()
    native_path = Path(barn_native_module.__file__).resolve()
    adapter_path = Path(barn_ros2_adapter_module.__file__).resolve()
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "evaluation_kind": BARN_SENSOR_FAITHFUL_EVALUATION_KIND,
        "official_gazebo_score": False,
        "benchmark": {
            "id": BARN_SENSOR_FAITHFUL_EVALUATION_KIND,
            "source": BARN_SOURCE,
            "source_commit": BARN_EVALUATOR_COMMIT,
            "public_world_indices": [int(index) for index in world_indices],
            "official_gazebo_score": False,
            "asset_scope": (
                "generated-public-style-development" if generated_corpus else "public-barn-static"
            ),
            "asset_manifest_sha256": manifest_hash,
            "native_reference_source_commits": {
                "jackal_melodic": JACKAL_MELODIC_REFERENCE_COMMIT,
                "jackal_simulator_melodic": JACKAL_SIMULATOR_MELODIC_REFERENCE_COMMIT,
            },
            "ros2_sensor_source": {
                "id": BARN_ROS2_SOURCE_ID,
                "commit": BARN_ROS2_SOURCE_COMMIT,
            },
        },
        "policy": spec.report_metadata(),
        "execution": {
            "evaluator_device": "cpu",
            "lidar_raycast_device": "cpu",
            "kinematics_device": "cpu",
            "policy_declared_device": spec.execution_device,
            "episode_workers_requested": workers,
            "episode_workers_effective": effective_workers,
            "process_start_method": process_start_method,
            "durable_report_writer": "caller_or_parent_process_only",
        },
        "suite_seed": suite_seed,
        # Keep this key compatible with compare_barn_reports.
        "native_config": asdict(config),
        "provenance": {
            "config_sha256": _config_sha256(config),
            "harness": {"id": _relative_source_id(harness_path), "sha256": _sha256(harness_path)},
            "native_geometry": {
                "id": _relative_source_id(native_path),
                "sha256": _sha256(native_path),
            },
            "calibrated_adapter": {
                "id": _relative_source_id(adapter_path),
                "sha256": _sha256(adapter_path),
            },
            "assets": [_world_provenance(world) for world in worlds],
        },
        "aggregate": aggregate,
        "top_decile_target": {
            "official_protocol": False,
            "pass": False,
            "note": "This calibrated native proxy cannot establish an official percentile.",
        },
        "episodes": [execution.detail for execution in executions],
        "notes": [
            "Non-official calibrated native approximation; not a Gazebo or leaderboard score.",
            "The policy receives only start-relative odometry, a normalized 360-degree LiDAR scan, clock, and odom-frame goal.",
            "Raw SDF geometry, collision truth, reference path, and optimal path length remain evaluator-private.",
            "A policy stop latches zero velocity until success or the 100 s evaluator timeout.",
            "LiDAR normalization is the exact BarnRos2AdapterCore path used by the ROS 2 submission.",
            "Observation/action hashes are post-run causal diagnostics and never enter policy observations.",
        ],
    }


def run_sensor_faithful_suite(
    *,
    assets_root: str | Path,
    world_indices: Sequence[int],
    policy_spec: BarnPolicySpec | CalibratedPolicySpec | None = None,
    trials: int = 1,
    suite_seed: int = 20260803,
    workers: int = 1,
    allow_experimental: bool = False,
    config: CalibratedBarnConfig | None = None,
    generated_corpus: bool = False,
    asset_manifest_sha256: str | None = None,
    long_shield_stall_steps: int = 50,
) -> dict[str, Any]:
    """Run calibrated episodes, optionally in isolated spawned CPU workers."""

    if not world_indices or len({int(value) for value in world_indices}) != len(world_indices):
        raise ValueError("world_indices must be non-empty and contain no duplicates")
    if not 1 <= trials <= 100:
        raise ValueError("trials must be in [1, 100]")
    if not 0 <= suite_seed < 2**63:
        raise ValueError("suite_seed must be in [0, 2**63)")
    if isinstance(workers, bool) or not isinstance(workers, int) or not 1 <= workers <= 128:
        raise ValueError("workers must be an integer in [1, 128]")
    if (
        isinstance(long_shield_stall_steps, bool)
        or not isinstance(long_shield_stall_steps, int)
        or long_shield_stall_steps < 1
    ):
        raise ValueError("long_shield_stall_steps must be a positive integer")
    calibrated_config = config or CalibratedBarnConfig()
    spec = calibrated_policy_spec(policy_spec or parcel_baseline_policy_spec())
    spec.ensure_enabled(allow_experimental=allow_experimental)
    if workers > 1 and spec.execution_device.strip().lower() != "cpu":
        raise ValueError("workers > 1 is supported only for CPU policies")
    process_policy = spec.require_process_descriptor() if workers > 1 else None

    if generated_corpus:
        manifest_hash = _validate_manifest_hash(asset_manifest_sha256)
        loader = load_generated_barn_world
    else:
        if asset_manifest_sha256 is not None:
            raise ValueError("asset_manifest_sha256 is valid only for a generated corpus")
        manifest_hash = None
        loader = load_barn_world
    worlds = [loader(assets_root, int(index)) for index in world_indices]
    episode_inputs = [
        (world, trial, suite_seed + int(world.world_index) * 1_009 + trial)
        for world in worlds
        for trial in range(trials)
    ]
    effective_workers = min(workers, len(episode_inputs))
    if effective_workers > 1:
        assert process_policy is not None
        requests = [
            _EpisodeRequest(
                world=world,
                config=calibrated_config,
                trial=trial,
                episode_seed=episode_seed,
                process_policy=process_policy,
            )
            for world, trial, episode_seed in episode_inputs
        ]
        context = multiprocessing.get_context("spawn")
        with ProcessPoolExecutor(
            max_workers=effective_workers,
            mp_context=context,
        ) as executor:
            executions = list(executor.map(_run_process_episode, requests, chunksize=1))
    else:
        executions = []
        for world, trial, episode_seed in episode_inputs:
            policy = spec.create(
                episode_seed=episode_seed,
                allow_experimental=allow_experimental,
            )
            executions.append(
                _execute_episode(
                    world=world,
                    config=calibrated_config,
                    policy=policy,
                    trial=trial,
                    episode_seed=episode_seed,
                )
            )

    return _build_sensor_faithful_report(
        world_indices=world_indices,
        worlds=worlds,
        spec=spec,
        executions=executions,
        trials=trials,
        suite_seed=suite_seed,
        workers=workers,
        effective_workers=effective_workers,
        process_start_method="spawn" if effective_workers > 1 else None,
        config=calibrated_config,
        generated_corpus=generated_corpus,
        manifest_hash=manifest_hash,
        long_shield_stall_steps=long_shield_stall_steps,
    )


def _causal_pair_fields(
    baseline_episode: Mapping[str, Any],
    candidate_episode: Mapping[str, Any],
) -> dict[str, Any]:
    baseline_sensor = baseline_episode["sensor_diagnostics"]
    candidate_sensor = candidate_episode["sensor_diagnostics"]
    baseline_observations = dict(
        zip(
            baseline_sensor["policy_observation_steps"],
            baseline_sensor["policy_observation_sha256"],
            strict=True,
        )
    )
    candidate_observations = dict(
        zip(
            candidate_sensor["policy_observation_steps"],
            candidate_sensor["policy_observation_sha256"],
            strict=True,
        )
    )
    baseline_actions = dict(
        zip(
            baseline_sensor["published_action_steps"],
            baseline_sensor["published_action_sha256"],
            strict=True,
        )
    )
    candidate_actions = dict(
        zip(
            candidate_sensor["published_action_steps"],
            candidate_sensor["published_action_sha256"],
            strict=True,
        )
    )
    common_action_steps = sorted(baseline_actions.keys() & candidate_actions.keys())
    first_divergence = next(
        (step for step in common_action_steps if baseline_actions[step] != candidate_actions[step]),
        None,
    )
    identical_observation = (
        first_divergence is not None
        and baseline_observations.get(first_divergence) is not None
        and baseline_observations.get(first_divergence)
        == candidate_observations.get(first_divergence)
    )
    prior_observation_steps = [
        step
        for step in baseline_observations.keys() & candidate_observations.keys()
        if first_divergence is None or step <= first_divergence
    ]
    return {
        "first_published_action_divergence_step": first_divergence,
        "first_divergence_on_identical_policy_observation": identical_observation,
        "policy_observations_identical_through_first_action_divergence": all(
            baseline_observations[step] == candidate_observations[step]
            for step in prior_observation_steps
        ),
        "mode_affected": identical_observation,
    }


def _annotate_paired_arm_execution(
    execution: _EpisodeExecution,
    *,
    role: str,
    arm_order: PairedArmOrder,
    position: str,
) -> _EpisodeExecution:
    detail = dict(execution.detail)
    detail["paired_execution"] = {
        "role": role,
        "arm_order": arm_order,
        "position": position,
        "concurrent_with_other_arm": False,
    }
    return _EpisodeExecution(
        detail=detail,
        latency_samples_ms=execution.latency_samples_ms,
        policy_diagnostics=execution.policy_diagnostics,
        action_evidence=execution.action_evidence,
    )


def _paired_arm_stratum(executions: Sequence[_EpisodeExecution]) -> dict[str, Any]:
    outcomes = Counter(str(execution.detail["status"]) for execution in executions)
    latency_samples: dict[str, list[float]] = {}
    for execution in executions:
        for name, values in execution.latency_samples_ms.items():
            latency_samples.setdefault(name, []).extend(values)
    count = len(executions)
    successes = sum(bool(execution.detail["success"]) for execution in executions)
    return {
        "episode_count": count,
        "success_count": successes,
        "success_rate": successes / count if count else None,
        "outcome_counts": dict(sorted(outcomes.items())),
        "latency": _latency_summary(latency_samples),
    }


def _paired_execution_metadata(
    executions: Sequence[_PairedEpisodeExecution],
) -> dict[str, Any]:
    reference_first = [
        execution.reference
        for execution in executions
        if execution.arm_order == REFERENCE_THEN_CANDIDATE
    ]
    reference_second = [
        execution.reference
        for execution in executions
        if execution.arm_order == CANDIDATE_THEN_REFERENCE
    ]
    candidate_first = [
        execution.candidate
        for execution in executions
        if execution.arm_order == CANDIDATE_THEN_REFERENCE
    ]
    candidate_second = [
        execution.candidate
        for execution in executions
        if execution.arm_order == REFERENCE_THEN_CANDIDATE
    ]
    order_counts = Counter(execution.arm_order for execution in executions)
    paired_outcomes = Counter(
        f"{execution.reference.detail['status']}->{execution.candidate.detail['status']}"
        for execution in executions
    )
    return {
        "pair_count": len(executions),
        "arms_never_concurrent_within_pair": True,
        "same_world_config_trial_and_seed_within_pair": True,
        "lifecycle": ("construct_run_and_close_first_arm_before_constructing_second_arm"),
        "order_counts": {
            REFERENCE_THEN_CANDIDATE: order_counts[REFERENCE_THEN_CANDIDATE],
            CANDIDATE_THEN_REFERENCE: order_counts[CANDIDATE_THEN_REFERENCE],
        },
        "schedule": [
            {
                "world_index": execution.world_index,
                "trial": execution.trial,
                "episode_seed": execution.episode_seed,
                "arm_order": execution.arm_order,
            }
            for execution in executions
        ],
        "order_stratified": {
            "reference": {
                "first": _paired_arm_stratum(reference_first),
                "second": _paired_arm_stratum(reference_second),
            },
            "candidate": {
                "first": _paired_arm_stratum(candidate_first),
                "second": _paired_arm_stratum(candidate_second),
            },
        },
        "paired_outcome_counts": dict(sorted(paired_outcomes.items())),
    }


def _paired_action_evidence_specs(
    *,
    world_id: int,
    trial: int,
    episode_seed: int,
    arm_order: PairedArmOrder,
    enabled: bool,
) -> tuple[V8EpisodeEvidenceCaptureSpec | None, V8EpisodeEvidenceCaptureSpec | None]:
    if not enabled:
        return None, None
    reference_order = 0 if arm_order == REFERENCE_THEN_CANDIDATE else 1
    candidate_order = 1 - reference_order
    return (
        V8EpisodeEvidenceCaptureSpec(
            arm="reference",
            execution_order=reference_order,
            world_id=world_id,
            trial_id=trial,
            seed=episode_seed,
        ),
        V8EpisodeEvidenceCaptureSpec(
            arm="candidate",
            execution_order=candidate_order,
            world_id=world_id,
            trial_id=trial,
            seed=episode_seed,
        ),
    )


def _validate_action_evidence_paths(
    paths: Mapping[tuple[int, int, str], str | Path] | None,
    *,
    episode_inputs: Sequence[tuple[BarnWorld, int, int]],
) -> dict[tuple[int, int, str], Path] | None:
    if paths is None:
        return None
    if not isinstance(paths, Mapping):
        raise TypeError("action_evidence_paths must be a mapping when provided")
    expected = {
        (int(world.world_index), int(trial), arm)
        for world, trial, _episode_seed in episode_inputs
        for arm in ("reference", "candidate")
    }
    actual = set(paths)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected, key=repr)
        raise ValueError(
            "action_evidence_paths must predeclare exactly every arm/world/trial artifact; "
            f"missing={missing!r}, extra={extra!r}"
        )
    resolved: dict[tuple[int, int, str], Path] = {}
    for key in sorted(expected):
        value = paths[key]
        if not isinstance(value, (str, Path)):
            raise TypeError("action evidence output paths must be strings or Paths")
        requested = Path(value).expanduser()
        target = requested.parent.resolve() / requested.name
        if target.is_symlink() or target.exists():
            raise FileExistsError(f"action evidence output already exists or is unsafe: {target}")
        resolved[key] = target
    if len(set(resolved.values())) != len(resolved):
        raise ValueError("action_evidence_paths must resolve to unique output files")
    return resolved


def _write_execution_action_evidence(
    execution: _EpisodeExecution,
    *,
    output_path: Path,
) -> tuple[_EpisodeExecution, dict[str, Any]]:
    builder = execution.action_evidence
    if builder is None:
        raise RuntimeError("paired episode omitted its requested action evidence")
    sensor = execution.detail.get("sensor_diagnostics")
    if not isinstance(sensor, Mapping):
        raise TypeError("paired episode sensor diagnostics are malformed")
    raw_steps = sensor.get("published_action_steps")
    if not isinstance(raw_steps, (tuple, list)):
        raise TypeError("paired episode published-action steps are malformed")
    published_steps = tuple(int(value) for value in raw_steps)
    captured_steps = tuple(record.step_index for record in builder.records)
    if captured_steps != published_steps:
        raise RuntimeError("action evidence steps do not match the published-action trace")
    raw_observation_steps = sensor.get("policy_observation_steps")
    raw_observation_hashes = sensor.get("policy_observation_sha256")
    if not isinstance(raw_observation_steps, (tuple, list)) or not isinstance(
        raw_observation_hashes, (tuple, list)
    ):
        raise TypeError("paired episode policy-observation hashes are malformed")
    observation_bindings = tuple(
        (int(step), str(digest))
        for step, digest in zip(
            raw_observation_steps,
            raw_observation_hashes,
            strict=True,
        )
    )
    captured_bindings = tuple(
        (record.step_index, record.policy_observation_sha256)
        for record in builder.records
        if record.issued_by_policy
    )
    if captured_bindings != observation_bindings:
        raise RuntimeError(
            "action evidence full-observation hashes do not match the published trace"
        )

    write_result = builder.write_exclusive(output_path)
    verified = read_v8_action_evidence(
        output_path,
        expected_artifact_sha256=write_result.identity.artifact_sha256,
    )
    if verified.identity != write_result.identity:
        raise RuntimeError("written and independently read action-evidence identities differ")
    if tuple(record.step_index for record in verified.records) != published_steps:
        raise RuntimeError("verified action evidence lost published-action step parity")
    verified_bindings = tuple(
        (record.step_index, record.policy_observation_sha256)
        for record in verified.records
        if record.issued_by_policy
    )
    if verified_bindings != observation_bindings:
        raise RuntimeError(
            "verified action-evidence full-observation hashes differ from the published trace"
        )

    violating_actions = sum(
        not record.certificate.observed_return_boundary_satisfied for record in verified.records
    )
    incomplete_actions = sum(
        not record.certificate.perception_complete for record in verified.records
    )
    metadata = {
        "identity": write_result.identity.as_dict(),
        "write_overhead": write_result.overhead.as_dict(),
        "read_verification_overhead": verified.overhead.as_dict(),
        "action_count_matches_published_trace": True,
        "policy_observation_hashes_match_published_trace": True,
        "all_records_format_read_and_recertified": True,
        "observed_return_boundary_satisfied_action_count": (
            len(verified.records) - violating_actions
        ),
        "observed_return_boundary_violating_action_count": violating_actions,
        "perception_incomplete_action_count": incomplete_actions,
        "evaluator_evidence_overhead_included_in_controller_latency": False,
    }
    detail = dict(execution.detail)
    detail["action_evidence"] = metadata
    return (
        _EpisodeExecution(
            detail=detail,
            latency_samples_ms=execution.latency_samples_ms,
            policy_diagnostics=execution.policy_diagnostics,
            action_evidence=None,
        ),
        metadata,
    )


def run_sensor_faithful_paired_comparison(
    *,
    assets_root: str | Path,
    world_indices: Sequence[int],
    candidate_spec: BarnPolicySpec | CalibratedPolicySpec,
    reference_spec: BarnPolicySpec | CalibratedPolicySpec | None = None,
    trials: int = 1,
    suite_seed: int = 20260803,
    workers: int = 1,
    allow_experimental: bool = False,
    config: CalibratedBarnConfig | None = None,
    generated_corpus: bool = False,
    asset_manifest_sha256: str | None = None,
    long_shield_stall_steps: int = 50,
    arm_order_schedule: Sequence[str] | None = None,
    action_evidence_paths: Mapping[tuple[int, int, str], str | Path] | None = None,
    isolated_planner_profile_authorization: (
        IsolatedPlannerProfileAuthorization | None
    ) = None,
) -> dict[str, Any]:
    """Run a counterbalanced A/B where each pair's arms are strictly serial.

    The returned reference report uses the legacy ``baseline`` key so the
    established scalar comparison contract remains reusable.
    """

    if not world_indices or len({int(value) for value in world_indices}) != len(world_indices):
        raise ValueError("world_indices must be non-empty and contain no duplicates")
    if not 1 <= trials <= 100:
        raise ValueError("trials must be in [1, 100]")
    if not 0 <= suite_seed < 2**63:
        raise ValueError("suite_seed must be in [0, 2**63)")
    if isinstance(workers, bool) or not isinstance(workers, int) or not 1 <= workers <= 128:
        raise ValueError("workers must be an integer in [1, 128]")
    if (
        isinstance(long_shield_stall_steps, bool)
        or not isinstance(long_shield_stall_steps, int)
        or long_shield_stall_steps < 1
    ):
        raise ValueError("long_shield_stall_steps must be a positive integer")

    candidate = calibrated_policy_spec(candidate_spec)
    reference = calibrated_policy_spec(reference_spec or parcel_baseline_policy_spec())
    if not candidate.experimental:
        raise ValueError("candidate_spec must be explicitly marked experimental")
    if reference.experimental:
        raise ValueError("reference_spec must not be experimental")
    reference.ensure_enabled()
    candidate.ensure_enabled(allow_experimental=allow_experimental)
    isolated_reference = isinstance(
        reference.underlying.process_descriptor,
        IsolatedPolicyDescriptor,
    )
    isolated_candidate = isinstance(
        candidate.underlying.process_descriptor,
        IsolatedPolicyDescriptor,
    )
    if isolated_planner_profile_authorization is not None:
        if not isinstance(
            isolated_planner_profile_authorization,
            IsolatedPlannerProfileAuthorization,
        ):
            raise TypeError(
                "isolated_planner_profile_authorization must be an "
                "IsolatedPlannerProfileAuthorization"
            )
        if not isolated_reference or not isolated_candidate:
            raise ValueError(
                "planner-profile authorization requires two isolated policy arms"
            )
        isolated_planner_profile_authorization.validate_pair(
            reference.underlying,
            candidate.underlying,
        )
    elif isolated_reference and isolated_candidate:
        validate_isolated_policy_pair(reference.underlying, candidate.underlying)
    if workers > 1 and {
        reference.execution_device.strip().lower(),
        candidate.execution_device.strip().lower(),
    } != {"cpu"}:
        raise ValueError("workers > 1 is supported only when both policies declare CPU")

    pair_count = len(world_indices) * trials
    raw_schedule = (
        alternating_paired_arm_order_schedule(pair_count)
        if arm_order_schedule is None
        else arm_order_schedule
    )
    schedule = validate_paired_arm_order_schedule(raw_schedule, pair_count=pair_count)
    calibrated_config = config or CalibratedBarnConfig()
    reference_descriptor = reference.require_process_descriptor() if workers > 1 else None
    candidate_descriptor = candidate.require_process_descriptor() if workers > 1 else None

    if generated_corpus:
        manifest_hash = _validate_manifest_hash(asset_manifest_sha256)
        loader = load_generated_barn_world
    else:
        if asset_manifest_sha256 is not None:
            raise ValueError("asset_manifest_sha256 is valid only for a generated corpus")
        manifest_hash = None
        loader = load_barn_world
    worlds = [loader(assets_root, int(index)) for index in world_indices]
    episode_inputs = [
        (world, trial, suite_seed + int(world.world_index) * 1_009 + trial)
        for world in worlds
        for trial in range(trials)
    ]
    if any(not 0 <= episode_seed < 2**63 for _, _, episode_seed in episode_inputs):
        raise ValueError("derived episode seed must be in [0, 2**63)")
    resolved_evidence_paths = _validate_action_evidence_paths(
        action_evidence_paths,
        episode_inputs=episode_inputs,
    )
    capture_action_evidence = resolved_evidence_paths is not None
    scheduled_inputs = [
        (
            world,
            trial,
            episode_seed,
            arm_order,
            *_paired_action_evidence_specs(
                world_id=world.world_index,
                trial=trial,
                episode_seed=episode_seed,
                arm_order=arm_order,
                enabled=capture_action_evidence,
            ),
        )
        for (world, trial, episode_seed), arm_order in zip(
            episode_inputs,
            schedule,
            strict=True,
        )
    ]
    effective_workers = min(workers, len(episode_inputs))

    if workers > 1:
        assert reference_descriptor is not None
        assert candidate_descriptor is not None
        requests = [
            _PairedEpisodeRequest(
                world=world,
                config=calibrated_config,
                trial=trial,
                episode_seed=episode_seed,
                reference_policy=reference_descriptor,
                candidate_policy=candidate_descriptor,
                arm_order=arm_order,
                reference_action_evidence=reference_action_evidence,
                candidate_action_evidence=candidate_action_evidence,
            )
            for (
                world,
                trial,
                episode_seed,
                arm_order,
                reference_action_evidence,
                candidate_action_evidence,
            ) in scheduled_inputs
        ]
        context = multiprocessing.get_context("spawn")
        with ProcessPoolExecutor(
            max_workers=effective_workers,
            mp_context=context,
        ) as executor:
            paired_executions = list(
                executor.map(_run_paired_process_episode, requests, chunksize=1)
            )
        process_start_method = "spawn"
    else:
        paired_executions = [
            _run_paired_local_episode(
                world=world,
                config=calibrated_config,
                trial=trial,
                episode_seed=episode_seed,
                reference=reference,
                candidate=candidate,
                arm_order=arm_order,
                reference_action_evidence=reference_action_evidence,
                candidate_action_evidence=candidate_action_evidence,
            )
            for (
                world,
                trial,
                episode_seed,
                arm_order,
                reference_action_evidence,
                candidate_action_evidence,
            ) in scheduled_inputs
        ]
        process_start_method = None

    action_evidence_items: list[dict[str, Any]] = []
    if resolved_evidence_paths is not None:
        prepared_pairs: list[_PairedEpisodeExecution] = []
        for paired in paired_executions:
            executions_by_arm = {
                "reference": paired.reference,
                "candidate": paired.candidate,
            }
            actual_order = (
                ("reference", "candidate")
                if paired.arm_order == REFERENCE_THEN_CANDIDATE
                else ("candidate", "reference")
            )
            prepared: dict[str, _EpisodeExecution] = {}
            for arm in actual_order:
                execution, metadata = _write_execution_action_evidence(
                    executions_by_arm[arm],
                    output_path=resolved_evidence_paths[(paired.world_index, paired.trial, arm)],
                )
                prepared[arm] = execution
                action_evidence_items.append(metadata)
            prepared_pairs.append(
                _PairedEpisodeExecution(
                    world_index=paired.world_index,
                    trial=paired.trial,
                    episode_seed=paired.episode_seed,
                    arm_order=paired.arm_order,
                    reference=prepared["reference"],
                    candidate=prepared["candidate"],
                )
            )
        paired_executions = prepared_pairs

    reference_executions: list[_EpisodeExecution] = []
    candidate_executions: list[_EpisodeExecution] = []
    order_by_key: dict[tuple[int, int], PairedArmOrder] = {}
    for paired in paired_executions:
        reference_first = paired.arm_order == REFERENCE_THEN_CANDIDATE
        reference_executions.append(
            _annotate_paired_arm_execution(
                paired.reference,
                role="reference",
                arm_order=paired.arm_order,
                position="first" if reference_first else "second",
            )
        )
        candidate_executions.append(
            _annotate_paired_arm_execution(
                paired.candidate,
                role="candidate",
                arm_order=paired.arm_order,
                position="second" if reference_first else "first",
            )
        )
        order_by_key[(paired.world_index, paired.trial)] = paired.arm_order

    report_common = {
        "world_indices": world_indices,
        "worlds": worlds,
        "trials": trials,
        "suite_seed": suite_seed,
        "workers": workers,
        "effective_workers": effective_workers,
        "process_start_method": process_start_method,
        "config": calibrated_config,
        "generated_corpus": generated_corpus,
        "manifest_hash": manifest_hash,
        "long_shield_stall_steps": long_shield_stall_steps,
    }
    reference_report = _build_sensor_faithful_report(
        spec=reference,
        executions=reference_executions,
        **report_common,
    )
    candidate_report = _build_sensor_faithful_report(
        spec=candidate,
        executions=candidate_executions,
        **report_common,
    )
    for arm_report in (reference_report, candidate_report):
        arm_report["execution"].update(
            {
                "paired_episode_execution": True,
                "arms_concurrent_within_pair": False,
            }
        )
        if resolved_evidence_paths is not None:
            arm_report["execution"]["action_evidence"] = {
                "enabled": True,
                "immutable_artifact_count": len(arm_report["episodes"]),
                "evaluator_overhead_included_in_controller_latency": False,
            }

    from .compare_barn import compare_barn_reports

    comparison = compare_barn_reports(reference_report, candidate_report)
    reference_by_key = {
        (int(item["world_index"]), int(item["trial"])): item
        for item in reference_report["episodes"]
    }
    candidate_by_key = {
        (int(item["world_index"]), int(item["trial"])): item
        for item in candidate_report["episodes"]
    }
    mode_affected = 0
    for pair in comparison["paired_episodes"]:
        key = (int(pair["world_index"]), int(pair["trial"]))
        causal = _causal_pair_fields(reference_by_key[key], candidate_by_key[key])
        pair.update(causal)
        pair["arm_order"] = order_by_key[key]
        mode_affected += int(bool(causal["mode_affected"]))
    comparison["mode_affected_episode_count"] = mode_affected
    comparison["causal_hash_contract"] = {
        "policy_observation": "exact normalized BarnObservation including full scan bytes",
        "published_action": "BarnRos2VelocityCommand forward/yaw values and stop flag",
        "published_action_note": "separate UTF-8 command-note digest excluded from motor action",
    }
    comparison["paired_execution"] = _paired_execution_metadata(paired_executions)
    if resolved_evidence_paths is not None:
        comparison["action_evidence"] = {
            "enabled": True,
            "format_id": action_evidence_items[0]["identity"]["format_id"],
            "immutable_artifact_count": len(action_evidence_items),
            "expected_immutable_artifact_count": 2 * len(paired_executions),
            "all_action_counts_match_published_traces": all(
                bool(item["action_count_matches_published_trace"]) for item in action_evidence_items
            ),
            "all_policy_observation_hashes_match_published_traces": all(
                bool(item["policy_observation_hashes_match_published_trace"])
                for item in action_evidence_items
            ),
            "all_records_format_read_and_recertified": all(
                bool(item["all_records_format_read_and_recertified"])
                for item in action_evidence_items
            ),
            "evaluator_overhead_included_in_controller_latency": False,
            "artifacts": [item["identity"] for item in action_evidence_items],
        }
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "evaluation_kind": (
            f"{BARN_SENSOR_FAITHFUL_EVALUATION_KIND}-counterbalanced-paired-comparison"
        ),
        "official_gazebo_score": False,
        "baseline": reference_report,
        "candidate": candidate_report,
        "comparison": comparison,
        "target_status": {
            "official_gate_pass": False,
            "note": "A paired calibrated native proxy cannot establish official rank.",
        },
    }


def run_sensor_faithful_comparison(
    *,
    assets_root: str | Path,
    world_indices: Sequence[int],
    candidate_spec: BarnPolicySpec | CalibratedPolicySpec,
    baseline_spec: BarnPolicySpec | CalibratedPolicySpec | None = None,
    trials: int = 1,
    suite_seed: int = 20260803,
    workers: int = 1,
    allow_experimental: bool = False,
    config: CalibratedBarnConfig | None = None,
    generated_corpus: bool = False,
    asset_manifest_sha256: str | None = None,
    long_shield_stall_steps: int = 50,
) -> dict[str, Any]:
    """Run paired arms on identical worlds/seeds and add causal hash evidence."""

    candidate = calibrated_policy_spec(candidate_spec)
    baseline = calibrated_policy_spec(baseline_spec or parcel_baseline_policy_spec())
    if not candidate.experimental:
        raise ValueError("candidate_spec must be explicitly marked experimental")
    if baseline.experimental:
        raise ValueError("baseline_spec must not be experimental")
    common = {
        "assets_root": assets_root,
        "world_indices": world_indices,
        "trials": trials,
        "suite_seed": suite_seed,
        "workers": workers,
        "config": config,
        "generated_corpus": generated_corpus,
        "asset_manifest_sha256": asset_manifest_sha256,
        "long_shield_stall_steps": long_shield_stall_steps,
    }
    baseline_report = run_sensor_faithful_suite(policy_spec=baseline, **common)
    candidate_report = run_sensor_faithful_suite(
        policy_spec=candidate,
        allow_experimental=allow_experimental,
        **common,
    )
    # Reuse the established scalar delta contract, then extend each pair with
    # exact policy-observation/published-action causal evidence.
    from .compare_barn import compare_barn_reports

    comparison = compare_barn_reports(baseline_report, candidate_report)
    baseline_by_key = {
        (int(item["world_index"]), int(item["trial"])): item for item in baseline_report["episodes"]
    }
    candidate_by_key = {
        (int(item["world_index"]), int(item["trial"])): item
        for item in candidate_report["episodes"]
    }
    mode_affected = 0
    for pair in comparison["paired_episodes"]:
        key = (int(pair["world_index"]), int(pair["trial"]))
        causal = _causal_pair_fields(baseline_by_key[key], candidate_by_key[key])
        pair.update(causal)
        mode_affected += int(bool(causal["mode_affected"]))
    comparison["mode_affected_episode_count"] = mode_affected
    comparison["causal_hash_contract"] = {
        "policy_observation": "exact normalized BarnObservation including full scan bytes",
        "published_action": "BarnRos2VelocityCommand forward/yaw values and stop flag",
        "published_action_note": "separate UTF-8 command-note digest excluded from motor action",
    }
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "evaluation_kind": f"{BARN_SENSOR_FAITHFUL_EVALUATION_KIND}-paired-comparison",
        "official_gazebo_score": False,
        "baseline": baseline_report,
        "candidate": candidate_report,
        "comparison": comparison,
        "target_status": {
            "official_gate_pass": False,
            "note": "A paired calibrated native proxy cannot establish official rank.",
        },
    }


__all__ = [
    "BARN_SENSOR_FAITHFUL_EVALUATION_KIND",
    "BARN_SENSOR_FAITHFUL_RUNNER_ID",
    "CALIBRATED_LIDAR_ANGLE_MAX_RAD",
    "CALIBRATED_LIDAR_ANGLE_MIN_RAD",
    "CALIBRATED_LIDAR_FORWARD_M",
    "CALIBRATED_LIDAR_FOV_DEG",
    "CALIBRATED_LIDAR_RANGE_MAX_M",
    "CALIBRATED_LIDAR_RANGE_MIN_M",
    "CALIBRATED_LIDAR_RAY_COUNT",
    "CALIBRATED_POLICY_INPUTS",
    "CALIBRATED_START_HEADING_RAD",
    "CALIBRATED_TRIAL_START_TRANSLATION_M",
    "CANDIDATE_THEN_REFERENCE",
    "REFERENCE_THEN_CANDIDATE",
    "CalibratedBarnConfig",
    "CalibratedPolicySpec",
    "SensorFaithfulBarnRunner",
    "SensorFaithfulConfig",
    "SensorFaithfulEpisodeResult",
    "SensorFaithfulEpisodeWithEvidence",
    "SensorTransportDiagnostics",
    "ShieldStallDiagnostics",
    "V8EpisodeEvidenceCaptureSpec",
    "alternating_paired_arm_order_schedule",
    "calibrated_experimental_config_spec",
    "calibrated_policy_spec",
    "calibrated_reference_config_spec",
    "cast_sensor_faithful_lidar",
    "run_sensor_faithful_comparison",
    "run_sensor_faithful_paired_comparison",
    "run_sensor_faithful_suite",
    "validate_paired_arm_order_schedule",
    "world_pose_to_odom",
]
