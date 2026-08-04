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
    / "scratch_challengers"
    / "supervisory_gap_s1"
    / "experimental_sampled_predictive_tracker.py"
)


def _load_tracker_class():
    name = "parcel_robot.navigation._staged_barn_v9_supervisory_gap_s1"
    spec = importlib.util.spec_from_file_location(name, MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module.SampledPredictiveTracker


SampledPredictiveTracker = _load_tracker_class()


def _wrapped_difference(left: float, right: float) -> float:
    return (left - right + math.pi) % (2.0 * math.pi) - math.pi


def _index_near(bearing_rad: float) -> int:
    return min(
        range(RAY_COUNT),
        key=lambda index: abs(
            _wrapped_difference(ANGLE_MIN_RAD + index * ANGLE_INCREMENT_RAD, bearing_rad)
        ),
    )


def _scan(
    hits: dict[float, float] | None = None,
    *,
    missing: tuple[int, ...] = (),
    fill: float = math.inf,
) -> LidarScan:
    values = [fill] * RAY_COUNT
    for index in missing:
        values[index % RAY_COUNT] = math.nan
    for bearing, distance in (hits or {}).items():
        values[_index_near(bearing)] = distance
    return LidarScan(
        ranges_m=tuple(values),
        angle_min_rad=ANGLE_MIN_RAD,
        angle_increment_rad=ANGLE_INCREMENT_RAD,
        range_min_m=0.05,
        range_max_m=25.0,
    )


def _dropout(bearing_rad: float, count: int) -> tuple[int, ...]:
    center = _index_near(bearing_rad)
    start = center - (count - 1) // 2
    return tuple((start + offset) % RAY_COUNT for offset in range(count))


def _waypoint(pose: Pose2D, target: tuple[float, float] = (4.0, 0.0)) -> BodyWaypoint:
    dx = target[0] - pose.x
    dy = target[1] - pose.y
    cosine = math.cos(pose.heading_rad)
    sine = math.sin(pose.heading_rad)
    forward = cosine * dx + sine * dy
    left = -sine * dx + cosine * dy
    return BodyWaypoint(
        world_xy=target,
        forward_m=forward,
        left_m=left,
        distance_m=math.hypot(dx, dy),
        heading_error_rad=_wrapped_difference(math.atan2(dy, dx), pose.heading_rad),
        route_index=1,
        is_final=True,
    )


def _select(
    tracker,
    *,
    pose: Pose2D | None = None,
    scan: LidarScan | None = None,
    nominal: MidLevelCommand | None = None,
    route_available: bool = True,
    waypoint: BodyWaypoint | None | object = ...,
):
    current_pose = pose or Pose2D(0.0, 0.0, 0.0)
    selected_waypoint = _waypoint(current_pose) if waypoint is ... else waypoint
    return tracker.select(
        pose=current_pose,
        scan=scan or _scan(),
        goal_world=(4.0, 0.0),
        route_waypoints_world=((0.0, 0.0), (4.0, 0.0)),
        nominal=nominal or MidLevelCommand(vx=0.30, vy=0.0, vyaw=0.0, note="grid_track"),
        waypoint=selected_waypoint,
        route_available=route_available,
    )


def test_clear_positive_nominal_is_passed_through_unchanged() -> None:
    tracker = SampledPredictiveTracker()

    assert _select(tracker) is None


def test_deliberate_grid_alignment_zero_never_activates_gap_recovery() -> None:
    tracker = SampledPredictiveTracker()
    nominal = MidLevelCommand(vx=0.0, vy=0.0, vyaw=0.4, note="grid_align")

    assert all(_select(tracker, nominal=nominal) is None for _ in range(12))
    assert tracker._committed_heading_world_rad is None


def test_recovery_activates_only_after_three_blocked_positive_requests() -> None:
    tracker = SampledPredictiveTracker()
    blocked_scan = _scan({math.pi / 4.0: 0.8})

    first = _select(tracker, scan=blocked_scan)
    second = _select(tracker, scan=blocked_scan)
    third = _select(tracker, scan=blocked_scan)

    assert first is not None and "blocked_ticks=1" in first.note
    assert second is not None and "blocked_ticks=2" in second.note
    assert third is not None and third.note.startswith("v9s1_escape_rotate")
    assert third.vx == 0.0
    assert third.vy == 0.0
    assert third.vyaw * (math.pi / 4.0) < 0.0


@pytest.mark.parametrize("missing_count", (1, 4))
def test_bounded_forward_dropout_is_supported_by_two_sided_bracketing(
    missing_count: int,
) -> None:
    tracker = SampledPredictiveTracker()

    command = _select(tracker, scan=_scan(missing=_dropout(0.0, missing_count)))

    assert command is None


def test_five_bin_forward_blind_wedge_cannot_publish_translation() -> None:
    tracker = SampledPredictiveTracker()
    scan = _scan(missing=_dropout(0.0, 5))

    command = _select(tracker, scan=scan)

    assert command is not None
    assert (command.vx, command.vy, command.vyaw) == (0.0, 0.0, 0.0)
    assert "nominal_translation_gate_failed" in command.note


def test_two_sided_bracketing_handles_the_full_circle_seam() -> None:
    tracker = SampledPredictiveTracker()
    scan = _scan(missing=_dropout(math.pi, 1))
    prepared, reason = tracker._prepare_scan(scan)

    assert reason == "ok" and prepared is not None
    assert tracker._bearing_is_observed(math.pi, prepared) is True
    assert tracker._bearing_is_observed(-math.pi, prepared) is True


def test_gap_settles_once_then_consecutive_curved_ticks_keep_translating() -> None:
    tracker = SampledPredictiveTracker()
    blocked_scan = _scan({math.pi / 4.0: 0.8})
    _select(tracker, scan=blocked_scan)
    _select(tracker, scan=blocked_scan)
    command = _select(tracker, scan=blocked_scan)
    assert command is not None

    heading = 0.0
    pose = Pose2D(0.0, 0.0, heading)
    for _ in range(30):
        heading += command.vyaw * 0.1
        pose = Pose2D(0.0, 0.0, heading)
        command = _select(tracker, pose=pose, scan=_scan())
        assert command is not None
        if command.note.startswith("v9s1_escape_advance"):
            break
    assert command.note.startswith("v9s1_escape_advance")

    # A small odometric heading disturbance demands a curved advance.  The
    # following tick must remain in advance rather than re-entering settle.
    disturbed = Pose2D(0.0, 0.0, heading - 0.08)
    first = _select(tracker, pose=disturbed, scan=_scan())
    second = _select(tracker, pose=disturbed, scan=_scan())
    assert first is not None and second is not None
    assert first.note.startswith("v9s1_escape_advance")
    assert second.note.startswith("v9s1_escape_advance")
    assert first.vx > 0.0 and second.vx > 0.0
    assert first.vyaw != 0.0 and second.vyaw != 0.0


def test_escape_commitment_ends_by_measured_displacement_not_micro_ticks() -> None:
    tracker = SampledPredictiveTracker()
    pose = Pose2D(0.0, 0.0, 0.0)
    command = _select(
        tracker,
        pose=pose,
        route_available=False,
        waypoint=None,
        nominal=MidLevelCommand(vyaw=0.0, note="grid_recover_scan"),
    )
    assert command is not None

    for _ in range(10):
        command = _select(tracker, pose=pose, scan=_scan())
        assert command is not None
        if command.note.startswith("v9s1_escape_advance"):
            break
    assert command.note.startswith("v9s1_escape_advance")

    assert _select(tracker, pose=Pose2D(0.29, 0.0, 0.0), scan=_scan()) is not None
    assert _select(tracker, pose=Pose2D(0.30, 0.0, 0.0), scan=_scan()) is None


def test_default_legacy_tick_budget_covers_probe_but_one_fewer_does_not() -> None:
    assert (
        SampledPredictiveTracker()._maximum_ramp_distance(
            ticks=24,
            target_vx=0.2,
            maximum_delta=0.09,
            dt_s=0.1,
        )
        >= 0.45
    )
    with pytest.raises(ValueError, match="must cover the certified probe"):
        SampledPredictiveTracker(escape_translation_ticks=23)


@pytest.mark.parametrize(
    ("scan", "action"),
    (
        (_scan(), (0.45, 0.0, 0.0)),
        (_scan({0.0: 0.83}), (0.45, 0.0, 0.0)),
        (_scan({math.pi / 2.0: 0.801}), (0.45, 0.0, 0.8)),
    ),
)
def test_native_resolution_projected_cap_remains_equal_to_v8(
    scan: LidarScan,
    action: tuple[float, float, float],
) -> None:
    tracker = SampledPredictiveTracker()
    prepared, reason = tracker._prepare_scan(scan)
    assert reason == "ok" and prepared is not None

    proxy = tracker._projected_cap(*action, prepared)
    authoritative = apply_v8_all_ray_shield(
        *action,
        scan.ranges_m,
        angle_min_rad=scan.angle_min_rad,
        angle_increment_rad=scan.angle_increment_rad,
    )

    assert proxy.applied_scale == pytest.approx(authoritative.applied_scale, abs=1e-12)
    assert proxy.output_vx_mps == pytest.approx(authoritative.output_vx_mps, abs=1e-12)
    assert proxy.output_vy_mps == pytest.approx(authoritative.output_vy_mps, abs=1e-12)


def test_equal_state_replay_is_deterministic_and_never_lateral_or_reverse() -> None:
    left = SampledPredictiveTracker()
    right = SampledPredictiveTracker()
    scan = _scan({math.pi / 4.0: 0.8})

    for _ in range(8):
        left_command = _select(left, scan=scan)
        right_command = _select(right, scan=scan)
        assert left_command == right_command
        if left_command is not None:
            assert left_command.vx >= 0.0
            assert left_command.vy == 0.0
            assert abs(left_command.vyaw) <= 0.8
