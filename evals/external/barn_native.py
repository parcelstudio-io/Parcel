"""Deterministic, sensor-only native runner for the static BARN assets.

This module mirrors the static-world protocol and score calculation in the
current BARN Challenge evaluator pinned at commit
``bf5a226f6088ec96bf0d2dbee3253a8ea6119b83``.  It deliberately does *not*
claim to be the official evaluator: the official challenge runs a Jackal in
Gazebo/ROS, whereas this runner uses deterministic planar unicycle kinematics
and circular collision geometry.  Results must therefore be reported as
``barn-native-headless-non-official`` and never as leaderboard scores.

The policy boundary is intentionally narrow.  A policy receives localization
and LiDAR sensor data, plus the episode goal during ``reset``.  It is never
given the SDF world, cylinders, reference path, or optimal path length.
"""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import Protocol, runtime_checkable

import numpy as np

BARN_EVALUATOR_COMMIT = "bf5a226f6088ec96bf0d2dbee3253a8ea6119b83"
BARN_NATIVE_EVALUATION_KIND = "barn-native-headless-non-official"
# Historical CLI name: this is a deterministic 50-world proxy subset sampled
# from the repository's 300 public worlds, not the complete public corpus and
# not any of the 50 hidden official evaluation worlds.
BARN_PUBLIC_WORLD_INDICES = tuple(range(0, 300, 6))
JACKAL_MELODIC_REFERENCE_COMMIT = "0d8d76f96bd52102b69a3b9cb735fd5f9e15f695"
JACKAL_SIMULATOR_MELODIC_REFERENCE_COMMIT = "f72ffe1c160db5595dc033b323eb924abec539c4"

OFFICIAL_START_XY = (-2.25, 3.0)
OFFICIAL_START_HEADING_RAD = math.pi / 2.0
OFFICIAL_GOAL_XY = (-2.25, 13.0)
OFFICIAL_SUCCESS_RADIUS_M = 1.0
OFFICIAL_TIMEOUT_S = 100.0
OFFICIAL_STEP_DT_S = 0.1
OFFICIAL_REFERENCE_SPEED_MPS = 2.0

# BARN's C-space inflates obstacles by two 0.15 m cells.  A 0.32 m disc is a
# conservative planar approximation of the Jackal footprint.  This
# approximation is one reason this evaluator is explicitly non-official.
DEFAULT_ROBOT_RADIUS_M = 0.32

# The challenge sets JACKAL_LASER_MODEL=ust10.  The direct melodic Jackal
# dependency referenced by the pinned challenge container configures its Gazebo
# ray sensor with 720 samples, a 270 degree field of view, and 30 m maximum
# range.  Native scans are deterministic and omit the Gazebo model's 1 mm
# Gaussian noise, another reason these results remain explicitly non-official.
DEFAULT_LIDAR_ANGLE_MIN_RAD = -3.0 * math.pi / 4.0
DEFAULT_LIDAR_ANGLE_MAX_RAD = 3.0 * math.pi / 4.0
DEFAULT_LIDAR_RAY_COUNT = 720
DEFAULT_LIDAR_MAX_RANGE_M = 30.0


@dataclass(frozen=True)
class BarnObservation:
    """The complete sensor frame visible to a benchmark policy."""

    position_xy: tuple[float, float]
    heading_rad: float
    lidar_ranges_m: tuple[float, ...]
    lidar_angle_min_rad: float
    lidar_angle_increment_rad: float
    time_s: float


@dataclass(frozen=True)
class BarnAction:
    """A body-forward unicycle command for one native simulation tick."""

    vx_mps: float
    yaw_rate_rps: float
    stop: bool = False
    note: str = ""


@runtime_checkable
class BarnPolicy(Protocol):
    """Sensor-only policy interface used by :class:`BarnNativeRunner`."""

    def reset(
        self,
        start_xy: tuple[float, float],
        heading_rad: float,
        goal_xy: tuple[float, float],
    ) -> None:
        """Reset policy-owned state for a new episode."""

    def act(self, observation: BarnObservation) -> BarnAction:
        """Return one bounded body-frame command from the current sensors."""


@dataclass(frozen=True)
class CylinderObstacle:
    """A vertical SDF cylinder projected onto the navigation plane."""

    center_xy: tuple[float, float]
    radius_m: float
    source_name: str = ""


@dataclass(frozen=True)
class BarnWorld:
    """Private evaluator state loaded from one static BARN episode."""

    world_index: int
    cylinders: tuple[CylinderObstacle, ...]
    reference_path_grid: tuple[tuple[float, float], ...]
    reference_path_world: tuple[tuple[float, float], ...]
    optimal_path_length_m: float
    world_path: Path | None = None
    path_path: Path | None = None


@dataclass(frozen=True)
class BarnNativeConfig:
    """Configuration for deterministic native kinematics and sensors."""

    dt_s: float = OFFICIAL_STEP_DT_S
    timeout_s: float = OFFICIAL_TIMEOUT_S
    success_radius_m: float = OFFICIAL_SUCCESS_RADIUS_M
    robot_radius_m: float = DEFAULT_ROBOT_RADIUS_M
    max_forward_speed_mps: float = OFFICIAL_REFERENCE_SPEED_MPS
    max_reverse_speed_mps: float = OFFICIAL_REFERENCE_SPEED_MPS
    max_yaw_rate_rps: float = 4.0
    lidar_angle_min_rad: float = DEFAULT_LIDAR_ANGLE_MIN_RAD
    lidar_angle_max_rad: float = DEFAULT_LIDAR_ANGLE_MAX_RAD
    lidar_ray_count: int = DEFAULT_LIDAR_RAY_COUNT
    lidar_max_range_m: float = DEFAULT_LIDAR_MAX_RANGE_M

    def __post_init__(self) -> None:
        positive = {
            "dt_s": self.dt_s,
            "timeout_s": self.timeout_s,
            "success_radius_m": self.success_radius_m,
            "robot_radius_m": self.robot_radius_m,
            "max_forward_speed_mps": self.max_forward_speed_mps,
            "max_reverse_speed_mps": self.max_reverse_speed_mps,
            "max_yaw_rate_rps": self.max_yaw_rate_rps,
            "lidar_max_range_m": self.lidar_max_range_m,
        }
        for name, value in positive.items():
            if not math.isfinite(value) or value <= 0.0:
                raise ValueError(f"{name} must be finite and positive")
        if self.lidar_ray_count < 2:
            raise ValueError("lidar_ray_count must be at least 2")
        if self.lidar_angle_max_rad <= self.lidar_angle_min_rad:
            raise ValueError("lidar_angle_max_rad must exceed lidar_angle_min_rad")


@dataclass(frozen=True)
class BarnEvaluatorDiagnostics:
    """Trajectory diagnostics computed from evaluator-private state.

    These values are attached only after an episode has run.  They are never
    included in :class:`BarnObservation`, so a policy cannot use the SDF
    obstacle geometry or reference-path information as an oracle.
    """

    evaluator_private_state: bool
    initial_goal_distance_m: float
    closest_goal_distance_m: float
    closest_goal_time_s: float
    final_goal_distance_m: float
    net_goal_progress_m: float
    maximum_goal_progress_m: float
    maximum_goal_progress_fraction: float
    goal_progress_efficiency: float
    minimum_signed_obstacle_clearance_m: float | None
    mean_signed_obstacle_clearance_m: float | None
    clearance_sample_count: int
    traveled_to_reference_path_ratio: float
    successful_reference_route_efficiency: float | None
    mean_translational_speed_mps: float


@dataclass(frozen=True)
class BarnEpisodeResult:
    """One native result, explicitly unsuitable as an official BARN score."""

    evaluation_kind: str
    official_gazebo_score: bool
    world_index: int
    success: bool
    collided: bool
    timed_out: bool
    stopped: bool
    status: str
    elapsed_time_s: float
    navigation_metric: float
    optimal_path_length_m: float
    optimal_time_s: float
    traveled_distance_m: float
    final_position_xy: tuple[float, float]
    final_heading_rad: float
    steps: int
    last_action_note: str = ""
    evaluator_diagnostics: BarnEvaluatorDiagnostics | None = None


def path_coord_to_world(row: float, column: float) -> tuple[float, float]:
    """Apply the pinned official evaluator's path-to-Gazebo conversion.

    BARN paths use ``(row, column)`` coordinates.  The names and offsets below
    intentionally follow ``run.py`` and ``report_test.py`` in the pinned
    evaluator instead of deriving coordinates from the SDF.
    """

    cylinder_radius = 0.075
    row_shift = -cylinder_radius - (30 * cylinder_radius * 2)
    column_shift = cylinder_radius + 5
    return (
        float(row) * (cylinder_radius * 2) + row_shift,
        float(column) * (cylinder_radius * 2) + column_shift,
    )


def reference_path_length_m(
    path_grid: Sequence[Sequence[float]],
    *,
    start_xy: tuple[float, float] = OFFICIAL_START_XY,
    goal_xy: tuple[float, float] = OFFICIAL_GOAL_XY,
) -> float:
    """Compute the official static-world reference length including endpoints."""

    points = [start_xy]
    points.extend(path_coord_to_world(point[0], point[1]) for point in path_grid)
    points.append(goal_xy)
    length = sum(math.dist(first, second) for first, second in pairwise(points))
    if not math.isfinite(length) or length <= 0.0:
        raise ValueError("reference path length must be finite and positive")
    return length


def barn_navigation_metric(
    success: bool,
    actual_time_s: float,
    optimal_path_length_m: float,
) -> float:
    """Return the exact pinned BARN score: S * OT / clip(AT, 2OT, 8OT)."""

    if not math.isfinite(actual_time_s) or actual_time_s < 0.0:
        raise ValueError("actual_time_s must be finite and non-negative")
    if not math.isfinite(optimal_path_length_m) or optimal_path_length_m <= 0.0:
        raise ValueError("optimal_path_length_m must be finite and positive")
    if not success:
        return 0.0
    optimal_time_s = optimal_path_length_m / OFFICIAL_REFERENCE_SPEED_MPS
    clipped_time = min(max(actual_time_s, 2.0 * optimal_time_s), 8.0 * optimal_time_s)
    return optimal_time_s / clipped_time


def _pose2(element: ET.Element | None) -> tuple[float, float, float]:
    if element is None or not (element.text or "").strip():
        return (0.0, 0.0, 0.0)
    relative_to = (element.get("relative_to") or element.get("frame") or "").strip()
    if relative_to:
        raise ValueError(f"unsupported named SDF pose frame: {relative_to!r}")
    values = [float(value) for value in (element.text or "").split()]
    if len(values) != 6 or not all(math.isfinite(value) for value in values):
        raise ValueError("SDF pose must contain six finite numbers")
    return (values[0], values[1], values[5])


def _compose_pose2(
    parent: tuple[float, float, float],
    child: tuple[float, float, float],
) -> tuple[float, float, float]:
    cos_yaw = math.cos(parent[2])
    sin_yaw = math.sin(parent[2])
    return (
        parent[0] + cos_yaw * child[0] - sin_yaw * child[1],
        parent[1] + sin_yaw * child[0] + cos_yaw * child[1],
        _wrap_angle(parent[2] + child[2]),
    )


def parse_sdf_cylinders(world_path: str | Path) -> tuple[CylinderObstacle, ...]:
    """Parse top-level model/link/collision cylinder geometry from an SDF world.

    Only collision geometry is used.  Visual cylinders and ``<state>``
    snapshots are ignored, preventing duplicate obstacles.  Standard nested
    model/link/collision poses are composed in the navigation plane.
    """

    path = Path(world_path)
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError) as exc:
        raise ValueError(f"could not parse BARN SDF world {path}: {exc}") from exc

    world = root if root.tag == "world" else root.find("world")
    if world is None:
        raise ValueError(f"SDF file has no <world>: {path}")

    cylinders: list[CylinderObstacle] = []
    for model in world.findall("model"):
        model_pose = _pose2(model.find("pose"))
        model_name = model.get("name", "model")
        for link in model.findall("link"):
            link_pose = _compose_pose2(model_pose, _pose2(link.find("pose")))
            link_name = link.get("name", "link")
            for collision in link.findall("collision"):
                cylinder = collision.find("geometry/cylinder")
                if cylinder is None:
                    continue
                radius_text = cylinder.findtext("radius")
                if radius_text is None:
                    raise ValueError(f"cylinder collision without radius in {path}")
                radius = float(radius_text)
                if not math.isfinite(radius) or radius <= 0.0:
                    raise ValueError(f"invalid cylinder radius {radius!r} in {path}")
                collision_pose = _compose_pose2(link_pose, _pose2(collision.find("pose")))
                collision_name = collision.get("name", "collision")
                cylinders.append(
                    CylinderObstacle(
                        center_xy=(collision_pose[0], collision_pose[1]),
                        radius_m=radius,
                        source_name=f"{model_name}/{link_name}/{collision_name}",
                    )
                )
    return tuple(cylinders)


def _asset_paths(assets_root: str | Path, world_index: int) -> tuple[Path, Path]:
    if world_index < 0 or world_index >= 300:
        raise ValueError("static BARN world_index must be in [0, 299]")
    return _asset_paths_unbounded(assets_root, world_index)


def _asset_paths_unbounded(assets_root: str | Path, world_index: int) -> tuple[Path, Path]:
    if world_index < 0:
        raise ValueError("BARN world_index must be non-negative")
    root = Path(assets_root)
    world_candidates = (
        root / "world_files" / f"world_{world_index}.world",
        root / f"world_{world_index}.world",
    )
    path_candidates = (
        root / "path_files" / f"path_{world_index}.npy",
        root / f"path_{world_index}.npy",
    )
    world_path = next((path for path in world_candidates if path.is_file()), None)
    path_path = next((path for path in path_candidates if path.is_file()), None)
    if world_path is None:
        raise FileNotFoundError(f"missing world_{world_index}.world below {root}")
    if path_path is None:
        raise FileNotFoundError(f"missing path_{world_index}.npy below {root}")
    return world_path, path_path


def load_barn_world(assets_root: str | Path, world_index: int) -> BarnWorld:
    """Load one official static BARN SDF world and its reference path."""

    world_path, path_path = _asset_paths(assets_root, world_index)
    return _load_barn_world_files(world_index, world_path, path_path)


def _load_barn_world_files(
    world_index: int,
    world_path: Path,
    path_path: Path,
) -> BarnWorld:
    raw_path = np.load(path_path, allow_pickle=False)
    if raw_path.ndim != 2 or raw_path.shape[1] != 2 or raw_path.shape[0] == 0:
        raise ValueError(f"BARN path must be a non-empty Nx2 array: {path_path}")
    if not np.isfinite(raw_path).all():
        raise ValueError(f"BARN path contains non-finite coordinates: {path_path}")

    path_grid = tuple((float(row), float(column)) for row, column in raw_path)
    path_world = tuple(path_coord_to_world(row, column) for row, column in path_grid)
    return BarnWorld(
        world_index=world_index,
        cylinders=parse_sdf_cylinders(world_path),
        reference_path_grid=path_grid,
        reference_path_world=path_world,
        optimal_path_length_m=reference_path_length_m(path_grid),
        world_path=world_path,
        path_path=path_path,
    )


def load_generated_barn_world(assets_root: str | Path, world_index: int) -> BarnWorld:
    """Load a namespaced, generated BARN-style native-proxy world.

    Generated experiment IDs start above the immutable 0--299 public corpus so
    a result cannot silently masquerade as a public-world replay.  Geometry and
    path hashes are validated by the experiment manifest before this loader is
    called; the policy still receives only odometry, LiDAR, clock, and goal.
    """

    if world_index < 300:
        raise ValueError("generated BARN world_index must be at least 300")
    world_path, path_path = _asset_paths_unbounded(assets_root, world_index)
    return _load_barn_world_files(world_index, world_path, path_path)


def cast_lidar(
    position_xy: tuple[float, float],
    heading_rad: float,
    cylinders: Sequence[CylinderObstacle],
    *,
    angle_min_rad: float = DEFAULT_LIDAR_ANGLE_MIN_RAD,
    angle_max_rad: float = DEFAULT_LIDAR_ANGLE_MAX_RAD,
    ray_count: int = DEFAULT_LIDAR_RAY_COUNT,
    max_range_m: float = DEFAULT_LIDAR_MAX_RANGE_M,
) -> tuple[float, ...]:
    """Ray-cast a deterministic planar LiDAR frame against SDF cylinders."""

    if ray_count < 2:
        raise ValueError("ray_count must be at least 2")
    if max_range_m <= 0.0 or not math.isfinite(max_range_m):
        raise ValueError("max_range_m must be finite and positive")
    if not cylinders:
        return (float(max_range_m),) * ray_count

    centers = np.asarray([cylinder.center_xy for cylinder in cylinders], dtype=np.float64)
    radii = np.asarray([cylinder.radius_m for cylinder in cylinders], dtype=np.float64)
    relative_centers = centers - np.asarray(position_xy, dtype=np.float64)
    center_distance_squared = np.einsum("ij,ij->i", relative_centers, relative_centers)
    angles = heading_rad + np.linspace(angle_min_rad, angle_max_rad, ray_count)
    directions = np.stack((np.cos(angles), np.sin(angles)), axis=1)

    # Each row is one ray and each column one circle.  Intersect the ray with
    # the circle analytically, choosing the nearest non-negative root.
    projection = directions @ relative_centers.T
    perpendicular_squared = center_distance_squared[None, :] - projection * projection
    discriminant = radii[None, :] * radii[None, :] - perpendicular_squared
    hit_mask = discriminant >= 0.0
    root = np.sqrt(np.maximum(discriminant, 0.0))
    near = projection - root
    far = projection + root
    distances = np.where(near >= 0.0, near, np.where(far >= 0.0, far, np.inf))
    distances = np.where(hit_mask, distances, np.inf)
    nearest = np.min(distances, axis=1)
    nearest = np.minimum(nearest, max_range_m)
    nearest[~np.isfinite(nearest)] = max_range_m
    return tuple(float(distance) for distance in nearest)


class BarnNativeRunner:
    """Run a policy without exposing evaluator-owned map or path state."""

    def __init__(self, world: BarnWorld, config: BarnNativeConfig | None = None) -> None:
        self._world = world
        self._config = config or BarnNativeConfig()

    def run(self, policy: BarnPolicy) -> BarnEpisodeResult:
        """Execute one deterministic, collision-terminal native episode."""

        config = self._config
        position = OFFICIAL_START_XY
        heading = OFFICIAL_START_HEADING_RAD
        elapsed = 0.0
        traveled = 0.0
        steps = 0
        collided = _point_collides(position, self._world.cylinders, config.robot_radius_m)
        stopped = False
        last_note = ""
        max_steps = math.ceil(config.timeout_s / config.dt_s)
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

        policy.reset(OFFICIAL_START_XY, OFFICIAL_START_HEADING_RAD, OFFICIAL_GOAL_XY)

        while not collided and steps < max_steps:
            if math.dist(position, OFFICIAL_GOAL_XY) <= config.success_radius_m:
                return self._result(
                    success=True,
                    collided=False,
                    timed_out=False,
                    stopped=stopped,
                    status="succeeded",
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
                )

            angle_increment = (config.lidar_angle_max_rad - config.lidar_angle_min_rad) / (
                config.lidar_ray_count - 1
            )
            observation = BarnObservation(
                position_xy=position,
                heading_rad=heading,
                lidar_ranges_m=cast_lidar(
                    position,
                    heading,
                    self._world.cylinders,
                    angle_min_rad=config.lidar_angle_min_rad,
                    angle_max_rad=config.lidar_angle_max_rad,
                    ray_count=config.lidar_ray_count,
                    max_range_m=config.lidar_max_range_m,
                ),
                lidar_angle_min_rad=config.lidar_angle_min_rad,
                lidar_angle_increment_rad=angle_increment,
                time_s=elapsed,
            )
            action = policy.act(observation)
            if not isinstance(action, BarnAction):
                raise TypeError("BarnPolicy.act() must return BarnAction")
            if not math.isfinite(action.vx_mps) or not math.isfinite(action.yaw_rate_rps):
                raise ValueError("BarnAction velocities must be finite")
            last_note = action.note
            if action.stop:
                stopped = True
                break

            velocity = min(
                max(action.vx_mps, -config.max_reverse_speed_mps),
                config.max_forward_speed_mps,
            )
            yaw_rate = min(
                max(action.yaw_rate_rps, -config.max_yaw_rate_rps), config.max_yaw_rate_rps
            )
            next_position, next_heading, collided = _integrate_collision_terminal(
                position,
                heading,
                velocity,
                yaw_rate,
                min(config.dt_s, config.timeout_s - elapsed),
                self._world.cylinders,
                config.robot_radius_m,
            )
            if not collided:
                traveled += math.dist(position, next_position)
                position = next_position
                heading = next_heading
            steps += 1
            # Derive time from the integer tick to avoid a 1001st update when
            # repeated binary 0.1 additions land just below 100 seconds.
            elapsed = min(config.timeout_s, steps * config.dt_s)
            if collided:
                # Collision is detected against the swept trajectory.  The
                # retained pose is the last safe pose, but the swept path
                # reached zero signed clearance.
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

        if collided:
            status = "collided"
        elif stopped:
            status = "stopped_outside_goal"
        else:
            status = "timeout"
        return self._result(
            success=False,
            collided=collided,
            timed_out=(not collided and not stopped and elapsed >= config.timeout_s),
            stopped=stopped,
            status=status,
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
        )

    def _result(
        self,
        *,
        success: bool,
        collided: bool,
        timed_out: bool,
        stopped: bool,
        status: str,
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
    ) -> BarnEpisodeResult:
        length = self._world.optimal_path_length_m
        final_goal_distance = math.dist(position, OFFICIAL_GOAL_XY)
        net_progress = initial_goal_distance - final_goal_distance
        maximum_progress = initial_goal_distance - closest_goal_distance
        route_efficiency = length / traveled if success and traveled > 0.0 else None
        diagnostics = BarnEvaluatorDiagnostics(
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
            successful_reference_route_efficiency=route_efficiency,
            mean_translational_speed_mps=traveled / elapsed if elapsed > 0.0 else 0.0,
        )
        return BarnEpisodeResult(
            evaluation_kind=BARN_NATIVE_EVALUATION_KIND,
            official_gazebo_score=False,
            world_index=self._world.world_index,
            success=success,
            collided=collided,
            timed_out=timed_out,
            stopped=stopped,
            status=status,
            elapsed_time_s=elapsed,
            navigation_metric=barn_navigation_metric(success, elapsed, length),
            optimal_path_length_m=length,
            optimal_time_s=length / OFFICIAL_REFERENCE_SPEED_MPS,
            traveled_distance_m=traveled,
            final_position_xy=position,
            final_heading_rad=heading,
            steps=steps,
            last_action_note=last_note,
            evaluator_diagnostics=diagnostics,
        )


def _wrap_angle(angle: float) -> float:
    return (angle + math.pi) % (2.0 * math.pi) - math.pi


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
    """Return body-to-obstacle clearance without exposing it to the policy."""

    if not cylinders:
        return None
    return min(
        math.dist(position, cylinder.center_xy) - robot_radius_m - cylinder.radius_m
        for cylinder in cylinders
    )


def _segment_collides(
    start: tuple[float, float],
    end: tuple[float, float],
    cylinders: Sequence[CylinderObstacle],
    robot_radius_m: float,
) -> bool:
    delta_x = end[0] - start[0]
    delta_y = end[1] - start[1]
    length_squared = delta_x * delta_x + delta_y * delta_y
    for cylinder in cylinders:
        center_x, center_y = cylinder.center_xy
        if length_squared <= 1e-18:
            distance = math.dist(start, cylinder.center_xy)
        else:
            projection = (
                (center_x - start[0]) * delta_x + (center_y - start[1]) * delta_y
            ) / length_squared
            projection = min(max(projection, 0.0), 1.0)
            closest = (start[0] + projection * delta_x, start[1] + projection * delta_y)
            distance = math.dist(closest, cylinder.center_xy)
        if distance <= robot_radius_m + cylinder.radius_m:
            return True
    return False


def _integrate_collision_terminal(
    position: tuple[float, float],
    heading: float,
    velocity: float,
    yaw_rate: float,
    dt_s: float,
    cylinders: Sequence[CylinderObstacle],
    robot_radius_m: float,
) -> tuple[tuple[float, float], float, bool]:
    # Small substeps prevent a fast command from tunnelling through a cylinder
    # and keep curved arcs close to their exact unicycle trajectory.
    substeps = max(
        1,
        math.ceil(abs(velocity) * dt_s / 0.025),
        math.ceil(abs(yaw_rate) * dt_s / 0.05),
    )
    sub_dt = dt_s / substeps
    cursor = position
    cursor_heading = heading
    for _ in range(substeps):
        next_position, next_heading = _unicycle_step(
            cursor, cursor_heading, velocity, yaw_rate, sub_dt
        )
        if _segment_collides(cursor, next_position, cylinders, robot_radius_m):
            # Collision is terminal and no position correction or lateral slide
            # is applied.  The caller retains the last collision-free state.
            return position, heading, True
        cursor = next_position
        cursor_heading = next_heading
    return cursor, cursor_heading, False


__all__ = [
    "BARN_EVALUATOR_COMMIT",
    "BARN_NATIVE_EVALUATION_KIND",
    "BARN_PUBLIC_WORLD_INDICES",
    "DEFAULT_LIDAR_MAX_RANGE_M",
    "DEFAULT_LIDAR_RAY_COUNT",
    "JACKAL_MELODIC_REFERENCE_COMMIT",
    "JACKAL_SIMULATOR_MELODIC_REFERENCE_COMMIT",
    "OFFICIAL_GOAL_XY",
    "OFFICIAL_START_HEADING_RAD",
    "OFFICIAL_START_XY",
    "BarnAction",
    "BarnEpisodeResult",
    "BarnEvaluatorDiagnostics",
    "BarnNativeConfig",
    "BarnNativeRunner",
    "BarnObservation",
    "BarnPolicy",
    "BarnWorld",
    "CylinderObstacle",
    "barn_navigation_metric",
    "cast_lidar",
    "load_barn_world",
    "load_generated_barn_world",
    "parse_sdf_cylinders",
    "path_coord_to_world",
    "reference_path_length_m",
]
