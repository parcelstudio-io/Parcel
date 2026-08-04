from __future__ import annotations

import importlib.util
import math
import sys
from pathlib import Path

import pytest

from parcel_robot.navigation.base import MidLevelCommand
from parcel_robot.navigation.experimental_all_ray_shield import apply_v8_all_ray_shield
from parcel_robot.navigation.grid_planner import BodyWaypoint, LidarScan, Pose2D

RAY_COUNT = 720
ANGLE_MIN_RAD = -math.pi
ANGLE_INCREMENT_RAD = 2.0 * math.pi / (RAY_COUNT - 1)
MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "evals"
    / "external"
    / "experiments"
    / "barn_sampled_predictive_tracker_v9"
    / "experimental_sampled_predictive_tracker.py"
)


def _load_tracker_class():
    # Give the staged file its eventual package parent so its production
    # relative imports are exercised without copying it into src.
    name = "parcel_robot.navigation._staged_barn_v9_sampled_predictive_tracker"
    spec = importlib.util.spec_from_file_location(name, MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module.SampledPredictiveTracker


SampledPredictiveTracker = _load_tracker_class()


def _index_near(bearing_rad: float) -> int:
    return min(
        range(RAY_COUNT),
        key=lambda index: abs(
            (ANGLE_MIN_RAD + index * ANGLE_INCREMENT_RAD - bearing_rad + math.pi) % (2.0 * math.pi)
            - math.pi
        ),
    )


def _scan(
    hits: dict[float, float] | None = None,
    *,
    fill: float = math.inf,
    ray_count: int = RAY_COUNT,
    angle_increment_rad: float = ANGLE_INCREMENT_RAD,
) -> LidarScan:
    values = [fill] * ray_count
    for bearing, distance in (hits or {}).items():
        values[_index_near(bearing)] = distance
    return LidarScan(
        ranges_m=tuple(values),
        angle_min_rad=ANGLE_MIN_RAD,
        angle_increment_rad=angle_increment_rad,
        range_min_m=0.05,
        range_max_m=25.0,
    )


def _waypoint(pose: Pose2D, world_xy: tuple[float, float] = (4.0, 0.0)) -> BodyWaypoint:
    dx = world_xy[0] - pose.x
    dy = world_xy[1] - pose.y
    cosine = math.cos(pose.heading_rad)
    sine = math.sin(pose.heading_rad)
    forward = cosine * dx + sine * dy
    left = -sine * dx + cosine * dy
    return BodyWaypoint(
        world_xy=world_xy,
        forward_m=forward,
        left_m=left,
        distance_m=math.hypot(dx, dy),
        heading_error_rad=(math.atan2(dy, dx) - pose.heading_rad + math.pi) % (2.0 * math.pi)
        - math.pi,
        route_index=1,
        is_final=True,
    )


def _select(
    tracker,
    *,
    pose: Pose2D | None = None,
    scan: LidarScan | None = None,
    nominal: MidLevelCommand | None = None,
):
    current_pose = pose or Pose2D(0.0, 0.0, 0.0)
    return tracker.select(
        pose=current_pose,
        scan=scan or _scan(),
        goal_world=(4.0, 0.0),
        route_waypoints_world=((0.0, 0.0), (4.0, 0.0)),
        nominal=nominal or MidLevelCommand(vx=0.30, vy=0.0, vyaw=0.0, note="grid_track"),
        waypoint=_waypoint(current_pose),
        route_available=True,
    )


def test_v9_open_startup_translates_on_the_first_clear_scan() -> None:
    tracker = SampledPredictiveTracker()

    command = _select(tracker, nominal=MidLevelCommand(vx=0.09, note="grid_track"))

    assert command is not None
    assert command.vx > 0.0
    assert command.vy == 0.0
    assert abs(command.vyaw) <= 0.8
    assert command.stop is False
    assert command.note.startswith("v9_sampled_track")


@pytest.mark.parametrize("obstacle_bearing", (math.pi / 4.0, -math.pi / 4.0))
def test_v9_exact_boundary_tangent_rotates_away_then_opens_translation(
    obstacle_bearing: float,
) -> None:
    tracker = SampledPredictiveTracker()
    heading = 0.0
    first = _select(
        tracker,
        scan=_scan({obstacle_bearing: 0.8}),
    )
    assert first is not None
    assert first.vx == 0.0
    assert first.vy == 0.0
    assert first.vyaw * obstacle_bearing < 0.0
    assert first.note.startswith("v9_gap_seed_rotate")

    command = first
    for _ in range(30):
        heading += command.vyaw * 0.1
        pose = Pose2D(0.0, 0.0, heading)
        body_bearing = obstacle_bearing - heading
        command = _select(
            tracker,
            pose=pose,
            scan=_scan({body_bearing: 0.8}),
        )
        assert command is not None
        assert command.vx >= 0.0
        assert command.vy == 0.0
        if command.vx > 0.0:
            break

    assert command.vx > 0.0
    assert "v9_sampled_track" in command.note
    assert "commitment=reused" in command.note


def test_v9_head_on_without_any_corridor_holds_without_rotation() -> None:
    tracker = SampledPredictiveTracker()

    command = _select(tracker, scan=_scan(fill=0.8))

    assert command is not None
    assert (command.vx, command.vy, command.vyaw) == (0.0, 0.0, 0.0)
    assert command.stop is False
    assert "reason=no_feasible_primitive" in command.note


def test_v9_is_bit_deterministic_for_equal_state_and_scan() -> None:
    left = SampledPredictiveTracker(sample_seed=121)
    right = SampledPredictiveTracker(sample_seed=121)
    scan = _scan({math.pi / 4.0: 0.8})

    assert _select(left, scan=scan) == _select(right, scan=scan)


@pytest.mark.parametrize(
    "nominal",
    (
        MidLevelCommand(vx=-0.30, vy=0.0, vyaw=0.0, note="reverse"),
        MidLevelCommand(vx=0.20, vy=0.25, vyaw=0.0, note="lateral"),
        MidLevelCommand(vx=0.30, vy=0.0, vyaw=-0.7, note="curved"),
    ),
)
def test_v9_barn_contract_never_emits_reverse_or_lateral(nominal: MidLevelCommand) -> None:
    tracker = SampledPredictiveTracker()

    command = _select(tracker, nominal=nominal)

    assert command is not None
    assert command.vx >= 0.0
    assert command.vy == 0.0
    assert abs(command.vyaw) <= 0.8


@pytest.mark.parametrize(
    ("scan", "reason"),
    (
        (_scan(ray_count=360, angle_increment_rad=ANGLE_INCREMENT_RAD), "scan_contract_invalid"),
        (_scan(fill=math.nan), "scan_unavailable"),
    ),
)
def test_v9_invalid_or_unavailable_scan_fails_closed(
    scan: LidarScan,
    reason: str,
) -> None:
    tracker = SampledPredictiveTracker()

    command = _select(tracker, scan=scan)

    assert command is not None
    assert (command.vx, command.vy, command.vyaw) == (0.0, 0.0, 0.0)
    assert command.stop is False
    assert reason in command.note


def test_v9_admits_a_strided_360_ray_incomplete_full_circle_scan() -> None:
    tracker = SampledPredictiveTracker()
    values = [math.inf] * 360
    values[0] = math.nan  # unknown rear seam; forward evidence remains explicit
    scan = LidarScan(
        ranges_m=values,
        angle_min_rad=ANGLE_MIN_RAD,
        angle_increment_rad=2.0 * ANGLE_INCREMENT_RAD,
        range_min_m=0.05,
        range_max_m=25.0,
    )

    command = _select(tracker, scan=scan)

    assert command is not None
    assert command.vx > 0.0
    assert command.vy == 0.0
    assert "v9_sampled_track" in command.note


@pytest.mark.parametrize(
    ("scan", "action"),
    (
        (_scan(), (0.45, 0.0, 0.0)),
        (_scan({0.0: 0.83}), (0.45, 0.0, 0.0)),
        (_scan({math.pi / 2.0: 0.801}), (0.45, 0.0, 0.8)),
        (
            _scan({-1.7: math.nan, 0.0: 0.82, 2.4: math.nan}),
            (0.30, 0.10, -0.35),
        ),
    ),
)
def test_v9_native_resolution_cap_matches_authoritative_v8_on_720_rays(
    scan: LidarScan,
    action: tuple[float, float, float],
) -> None:
    tracker = SampledPredictiveTracker()
    prepared, reason = tracker._prepare_scan(scan)
    assert reason == "ok" and prepared is not None
    ranges, angle_min, angle_increment, _ = prepared

    proxy = tracker._projected_cap(
        *action,
        ranges,
        angle_min=angle_min,
        angle_increment=angle_increment,
    )
    authoritative = apply_v8_all_ray_shield(
        *action,
        ranges,
        angle_min_rad=angle_min,
        angle_increment_rad=angle_increment,
    )

    assert proxy.applied_scale == pytest.approx(authoritative.applied_scale, abs=1e-12)
    assert proxy.output_vx_mps == pytest.approx(authoritative.output_vx_mps, abs=1e-12)
    assert proxy.output_vy_mps == pytest.approx(authoritative.output_vy_mps, abs=1e-12)


def test_v9_invalidates_a_gap_commitment_on_the_first_blocked_tick() -> None:
    tracker = SampledPredictiveTracker()
    initial = _select(tracker, scan=_scan({math.pi / 4.0: 0.8}))
    assert initial is not None and initial.note.startswith("v9_gap_seed_rotate")

    blocked = _select(tracker, scan=_scan(fill=0.8))

    assert blocked is not None
    assert (blocked.vx, blocked.vy, blocked.vyaw) == (0.0, 0.0, 0.0)
    assert "commitment=invalidated" in blocked.note


def test_v9_rotate_first_does_not_slide_during_a_large_route_heading_change() -> None:
    tracker = SampledPredictiveTracker()
    pose = Pose2D(0.0, 0.0, 0.0)
    target = (2.0, 2.0)
    waypoint = _waypoint(pose, target)

    command = tracker.select(
        pose=pose,
        scan=_scan(),
        goal_world=target,
        route_waypoints_world=((0.0, 0.0), target),
        nominal=MidLevelCommand(vx=0.2, vy=0.0, vyaw=0.4, note="grid_align"),
        waypoint=waypoint,
        route_available=True,
    )

    assert command is not None
    assert command.vx == 0.0
    assert command.vy == 0.0
    assert command.vyaw > 0.0
    assert command.note.startswith("v9_rotate_first")


def test_v9_bootstraps_a_short_safe_probe_when_no_route_is_available() -> None:
    tracker = SampledPredictiveTracker()
    pose = Pose2D(0.0, 0.0, 0.0)

    command = tracker.select(
        pose=pose,
        scan=_scan(),
        goal_world=(4.0, 0.0),
        route_waypoints_world=(),
        nominal=MidLevelCommand(vyaw=0.35, note="grid_recover_scan"),
        waypoint=None,
        route_available=False,
    )

    assert command is not None
    assert 0.0 < command.vx <= 0.09 + 1e-12
    assert command.vy == 0.0
    assert "source=bootstrap_" in command.note


def test_v9_enforces_per_tick_linear_and_yaw_slew_bounds() -> None:
    tracker = SampledPredictiveTracker(max_linear_accel=0.9, max_yaw_accel=1.8)
    first = _select(tracker, nominal=MidLevelCommand(vx=0.45, note="grid_track"))
    second = _select(tracker, nominal=MidLevelCommand(vx=0.45, note="grid_track"))
    assert first is not None and second is not None
    assert 0.0 <= first.vx <= 0.09 + 1e-12
    assert abs(first.vyaw) <= 0.18 + 1e-12
    assert abs(second.vx - first.vx) <= 0.09 + 1e-12
    assert abs(second.vyaw - first.vyaw) <= 0.18 + 1e-12

    pose = Pose2D(0.0, 0.0, 0.0)
    target = (2.0, 2.0)
    turning = tracker.select(
        pose=pose,
        scan=_scan(),
        goal_world=target,
        route_waypoints_world=((0.0, 0.0), target),
        nominal=MidLevelCommand(vx=0.0, vyaw=0.8, note="grid_align"),
        waypoint=_waypoint(pose, target),
        route_available=True,
    )
    assert turning is not None
    assert abs(turning.vx - second.vx) <= 0.09 + 1e-12
    assert abs(turning.vyaw - second.vyaw) <= 0.18 + 1e-12
