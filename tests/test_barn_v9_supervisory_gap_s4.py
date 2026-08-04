from __future__ import annotations

import importlib.util
import math
import sys
from itertools import pairwise
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
    / "supervisory_gap_s4"
    / "experimental_sampled_predictive_tracker.py"
)


def _load_tracker_class():
    name = "parcel_robot.navigation._staged_barn_v9_supervisory_gap_s4"
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


def _gap_direction_state(*centers: float):
    def direction_state(bearing: float, _scan_value):
        if any(abs(_wrapped_difference(bearing, center)) <= 0.27 for center in centers):
            return "clear", 3.0
        return "blocked", 0.0

    return direction_state


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


def test_nominal_ignores_long_rollout_when_exact_projected_cap_is_safe() -> None:
    tracker = SampledPredictiveTracker()
    scan = _scan({0.0: 1.20})
    prepared, reason = tracker._prepare_scan(scan)

    assert reason == "ok" and prepared is not None
    assert tracker._projected_cap(0.30, 0.0, 0.0, prepared).output_vx_mps == pytest.approx(
        0.30
    )
    assert tracker._rollout_is_safe(0.30, 0.0, prepared.obstacle_xy) is False
    assert _select(tracker, scan=scan) is None


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
    assert third is not None and third.note.startswith("v9s4_escape_rotate")
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
        if command.note.startswith("v9s4_escape_advance"):
            break
    assert command.note.startswith("v9s4_escape_advance")

    # A small odometric heading disturbance demands a curved advance.  The
    # following tick must remain in advance rather than re-entering settle.
    disturbed = Pose2D(0.0, 0.0, heading - 0.08)
    first = _select(tracker, pose=disturbed, scan=_scan())
    second = _select(tracker, pose=disturbed, scan=_scan())
    assert first is not None and second is not None
    assert first.note.startswith("v9s4_escape_advance")
    assert second.note.startswith("v9s4_escape_advance")
    assert first.vx > 0.0 and second.vx > 0.0
    assert first.vyaw != 0.0 and second.vyaw != 0.0


def test_four_bin_w5002_residual_sweep_rotates_until_advance() -> None:
    tracker = SampledPredictiveTracker()
    scan = _scan(missing=_dropout(0.0, 4))
    pose = Pose2D(0.0, 0.0, 0.0)
    tracker._committed_heading_world_rad = math.radians(-3.5)
    tracker._settling = True
    tracker._settled = False

    notes: list[str] = []
    for _ in range(20):
        command = _select(tracker, pose=pose, scan=scan)
        assert command is not None
        notes.append(command.note)
        pose = Pose2D(
            pose.x,
            pose.y,
            pose.heading_rad + command.vyaw * tracker.control_dt_s,
        )
        if command.note.startswith("v9s4_escape_advance"):
            break

    assert any("trigger=final_sweep_unobserved" in note for note in notes)
    assert notes[-1].startswith("v9s4_escape_advance")
    assert not any("sweep_unknown_ticks=1" in note for note in notes)


def test_settle_checks_advance_yaw_not_minimum_in_place_alignment_rate() -> None:
    tracker = SampledPredictiveTracker()
    scan = _scan(missing=_dropout(0.0, 4))
    prepared, reason = tracker._prepare_scan(scan)
    assert reason == "ok" and prepared is not None
    heading_error = math.radians(-1.45)

    in_place_sweep = tracker._alignment_yaw_target(heading_error) * tracker.reaction_horizon_s
    assert tracker._sweep_is_observed(0.0, in_place_sweep, prepared) is False
    assert tracker._settle_sweep_is_observed(heading_error, prepared) is True

    pose = Pose2D(0.0, 0.0, 0.0)
    tracker._committed_heading_world_rad = heading_error
    tracker._settling = True
    tracker._settled = False
    settle = _select(tracker, pose=pose, scan=scan)
    advance = _select(tracker, pose=pose, scan=scan)

    assert settle is not None and settle.note.startswith("v9s4_escape_settle")
    assert advance is not None and advance.note.startswith("v9s4_escape_advance")
    assert advance.vx > 0.0


def test_settle_threshold_preserves_timing_without_snapping_published_yaw() -> None:
    tracker = SampledPredictiveTracker()
    pose = Pose2D(0.0, 0.0, 0.0)
    tracker._committed_heading_world_rad = 0.0
    tracker._commitment_start_goal_distance_m = 4.0
    tracker._detour_side = 1
    tracker._settling = True
    tracker._settled = False
    tracker._last_yaw_rate_rps = -0.20

    settle = _select(tracker, pose=pose, scan=_scan())
    assert settle is not None and settle.note.startswith("v9s4_escape_settle")
    assert settle.vyaw == pytest.approx(-0.02)
    assert abs(settle.vyaw - (-0.20)) <= tracker.max_yaw_delta_rps + 1e-12
    assert tracker._settled is True

    advance = _select(tracker, pose=pose, scan=_scan())
    assert advance is not None and advance.note.startswith("v9s4_escape_advance")
    assert advance.vx > 0.0


def test_settled_unknown_sweep_counter_persists_then_reselects() -> None:
    tracker = SampledPredictiveTracker(unknown_commitment_grace_ticks=2)
    scan = _scan(missing=_dropout(0.0, 4))
    pose = Pose2D(0.0, 0.0, 0.0)
    tracker._committed_heading_world_rad = math.radians(-3.5)
    tracker._escape_start_xy = pose.xy
    tracker._settled = True
    tracker._settling = False

    first = _select(tracker, pose=pose, scan=scan)
    second = _select(tracker, pose=pose, scan=scan)
    third = _select(tracker, pose=pose, scan=scan)

    assert first is not None and "sweep_unknown_ticks=1" in first.note
    assert second is not None and "sweep_unknown_ticks=2" in second.note
    assert third is not None
    assert "escape_forward_sweep_unobserved" not in third.note
    assert third.note.startswith("v9s4_escape_rotate")
    assert tracker._sweep_unknown_ticks == 0


def test_latched_side_is_strict_until_unproductive_escape_flips_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tracker = SampledPredictiveTracker()
    prepared, reason = tracker._prepare_scan(_scan())
    assert reason == "ok" and prepared is not None

    monkeypatch.setattr(tracker, "_direction_state", _gap_direction_state(-0.80))
    tracker._start_escape(
        pose=Pose2D(0.0, 0.0, 0.0),
        scan=prepared,
        target_heading_error=0.0,
        trigger="test_first",
        route_unavailable=True,
        goal_distance_m=4.0,
    )
    assert tracker._detour_side == -1
    first_heading = tracker._committed_heading_world_rad

    tracker._clear_commitment(keep_previous=True)
    monkeypatch.setattr(tracker, "_direction_state", _gap_direction_state(0.35))
    opposite_only = tracker._start_escape(
        pose=Pose2D(0.0, 0.0, 0.0),
        scan=prepared,
        target_heading_error=0.0,
        trigger="test_opposite_only",
        route_unavailable=True,
        goal_distance_m=4.0,
    )
    assert tracker._detour_side == -1
    assert tracker._committed_heading_world_rad is None
    assert tracker._previous_gap_heading_world_rad == first_heading
    assert opposite_only.note.startswith("v9s4_active_gap_search")
    assert (opposite_only.vx, opposite_only.vy) == (0.0, 0.0)
    assert opposite_only.vyaw < 0.0

    tracker._clear_gap_search()
    monkeypatch.setattr(tracker, "_direction_state", _gap_direction_state(-0.80))
    tracker._start_escape(
        pose=Pose2D(0.0, 0.0, 0.0),
        scan=prepared,
        target_heading_error=0.0,
        trigger="test_failure",
        route_unavailable=True,
        goal_distance_m=4.0,
    )
    tracker._settled = True
    tracker._settling = False
    tracker._escape_start_xy = (0.0, 0.0)
    failed = _select(
        tracker,
        pose=Pose2D(0.0, 0.30, 0.0),
        route_available=False,
        waypoint=None,
        nominal=MidLevelCommand(vyaw=0.0, note="grid_recover_scan"),
    )
    assert tracker._detour_side == 1
    assert tracker._previous_gap_heading_world_rad is None
    assert failed is not None and failed.note.startswith("v9s4_active_gap_search")

    repeated = _select(
        tracker,
        pose=Pose2D(0.0, 0.30, 0.0),
        route_available=False,
        waypoint=None,
        nominal=MidLevelCommand(vyaw=0.0, note="grid_recover_scan"),
    )
    assert tracker._detour_side == 1
    assert repeated is not None and repeated.note.startswith("v9s4_active_gap_search")
    assert repeated.vyaw > failed.vyaw


def test_detour_latch_releases_only_after_continuous_admitted_nominal_motion() -> None:
    tracker = SampledPredictiveTracker()
    tracker._detour_side = -1
    tracker._detour_latch_goal_distance_m = 4.0
    tracker._detour_originated_from_route_loss = True
    tracker._previous_gap_heading_world_rad = -0.8

    alignment = _select(
        tracker,
        pose=Pose2D(1.0, 0.0, 0.0),
        nominal=MidLevelCommand(vx=0.0, vyaw=0.2, note="grid_align"),
        route_available=True,
    )
    assert alignment is None
    assert tracker._detour_side == -1

    assert _select(tracker, pose=Pose2D(1.0, 0.0, 0.0)) is None
    assert _select(tracker, pose=Pose2D(1.44, 0.0, 0.0)) is None
    assert tracker._detour_side == -1

    _select(
        tracker,
        pose=Pose2D(1.44, 0.0, 0.0),
        nominal=MidLevelCommand(vx=0.0, vyaw=0.2, note="grid_align"),
    )
    assert _select(tracker, pose=Pose2D(1.45, 0.0, 0.0)) is None
    assert tracker._detour_side == -1
    assert _select(tracker, pose=Pose2D(1.90, 0.0, 0.0)) is None
    assert tracker._detour_side is None
    assert tracker._previous_gap_heading_world_rad is None


def test_no_gap_uses_bounded_pure_yaw_and_commits_when_view_reveals_gap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tracker = SampledPredictiveTracker(active_search_ticks=4)
    prepared, reason = tracker._prepare_scan(_scan())
    assert reason == "ok" and prepared is not None
    monkeypatch.setattr(tracker, "_direction_state", _gap_direction_state())

    first = tracker._start_escape(
        pose=Pose2D(0.0, 0.0, 0.0),
        scan=prepared,
        target_heading_error=0.0,
        trigger="test_no_gap",
        route_unavailable=True,
        goal_distance_m=4.0,
    )
    second = tracker._continue_gap_search(
        pose=Pose2D(0.0, 0.0, first.vyaw * tracker.control_dt_s),
        scan=prepared,
        target_heading_error=0.0,
        route_unavailable=True,
        goal_distance_m=4.0,
    )

    assert first.note.startswith("v9s4_active_gap_search")
    assert second.note.startswith("v9s4_active_gap_search")
    assert (first.vx, first.vy, second.vx, second.vy) == (0.0, 0.0, 0.0, 0.0)
    assert first.vyaw > 0.0 and second.vyaw > 0.0
    assert second.vyaw - first.vyaw <= tracker.max_yaw_delta_rps + 1e-12
    assert tracker._detour_side == 1

    monkeypatch.setattr(tracker, "_direction_state", _gap_direction_state(0.80))
    revealed = tracker._continue_gap_search(
        pose=Pose2D(0.0, 0.0, 0.05),
        scan=prepared,
        target_heading_error=0.0,
        route_unavailable=True,
        goal_distance_m=4.0,
    )
    assert revealed.note.startswith("v9s4_escape_rotate")
    assert "active_perception_after_test_no_gap" in revealed.note
    assert tracker._committed_heading_world_rad is not None
    assert tracker._searching_for_gap is False


def test_active_gap_search_exhaustion_flips_once_then_stays_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tracker = SampledPredictiveTracker(active_search_ticks=2)
    prepared, reason = tracker._prepare_scan(_scan())
    assert reason == "ok" and prepared is not None
    monkeypatch.setattr(tracker, "_direction_state", _gap_direction_state())

    commands = [
        tracker._start_escape(
            pose=Pose2D(0.0, 0.0, 0.0),
            scan=prepared,
            target_heading_error=0.0,
            trigger="test_exhaustion",
            route_unavailable=True,
            goal_distance_m=4.0,
        )
    ]
    for _ in range(3):
        commands.append(
            tracker._continue_gap_search(
                pose=Pose2D(0.0, 0.0, 0.0),
                scan=prepared,
                target_heading_error=0.0,
                route_unavailable=True,
                goal_distance_m=4.0,
            )
        )

    assert commands[2].note.startswith("v9s4_active_gap_search_exhausted")
    assert "reason=active_gap_search_exhausted" in commands[3].note
    assert tracker._searching_for_gap is True
    assert tracker._search_exhausted is True
    assert tracker._detour_side == -1
    assert all(command.vx == 0.0 and command.vy == 0.0 for command in commands)
    assert all(
        abs(right.vyaw - left.vyaw) <= tracker.max_yaw_delta_rps + 1e-12
        for left, right in pairwise(commands)
    )

    held_side = tracker._detour_side
    tracker._continue_gap_search(
        pose=Pose2D(0.0, 0.0, 0.0),
        scan=prepared,
        target_heading_error=0.0,
        route_unavailable=True,
        goal_distance_m=4.0,
    )
    assert tracker._detour_side == held_side

    monkeypatch.setattr(tracker, "_direction_state", _gap_direction_state(-0.80))
    dynamic_wakeup = tracker._continue_gap_search(
        pose=Pose2D(0.0, 0.0, 0.0),
        scan=prepared,
        target_heading_error=0.0,
        route_unavailable=True,
        goal_distance_m=4.0,
    )
    assert dynamic_wakeup.note.startswith("v9s4_escape_rotate")
    assert tracker._committed_heading_world_rad is not None
    assert tracker._searching_for_gap is False


def test_repeated_block_search_cannot_restart_on_unchanged_usable_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tracker = SampledPredictiveTracker(active_search_ticks=2)
    monkeypatch.setattr(tracker, "_direction_state", _gap_direction_state())
    blocked_scan = _scan({math.pi / 4.0: 0.8})

    commands = [_select(tracker, scan=blocked_scan) for _ in range(6)]

    assert commands[2] is not None and commands[2].note.startswith(
        "v9s4_active_gap_search"
    )
    assert commands[4] is not None and commands[4].note.startswith(
        "v9s4_active_gap_search_exhausted"
    )
    assert commands[5] is not None
    assert "reason=active_gap_search_exhausted" in commands[5].note
    assert tracker._searching_for_gap is True
    assert tracker._search_exhausted is True
    assert tracker._search_started_route_unavailable is False
    assert tracker._search_ticks == 2


def test_valid_scan_holds_brake_yaw_without_exceeding_low_acceleration_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tracker = SampledPredictiveTracker(
        max_yaw_accel=0.1,
        unknown_commitment_grace_ticks=2,
    )
    tracker._committed_heading_world_rad = 0.0
    tracker._commitment_start_goal_distance_m = 4.0
    tracker._detour_side = 1
    tracker._last_yaw_rate_rps = 0.35
    monkeypatch.setattr(tracker, "_direction_state", lambda *_args: ("unknown", 0.0))

    grace = _select(tracker)
    assert grace is not None and "committed_gap_temporarily_unobserved" in grace.note
    assert grace.vyaw == pytest.approx(0.34)
    assert 0.35 - grace.vyaw <= tracker.max_yaw_delta_rps + 1e-12

    prepared, reason = tracker._prepare_scan(_scan())
    assert reason == "ok" and prepared is not None
    tracker._clear_commitment(keep_previous=True)
    tracker._searching_for_gap = True
    tracker._search_exhausted = True
    tracker._search_trigger = "low_accel"
    tracker._search_started_route_unavailable = False
    tracker._last_yaw_rate_rps = 0.35
    monkeypatch.setattr(tracker, "_direction_state", _gap_direction_state())
    exhausted = tracker._continue_gap_search(
        pose=Pose2D(0.0, 0.0, 0.0),
        scan=prepared,
        target_heading_error=0.0,
        route_unavailable=False,
        goal_distance_m=4.0,
    )
    assert "reason=active_gap_search_exhausted" in exhausted.note
    assert exhausted.vyaw == pytest.approx(0.34)
    assert 0.35 - exhausted.vyaw <= tracker.max_yaw_delta_rps + 1e-12


def test_route_guidance_and_live_waypoint_drive_reselection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tracker = SampledPredictiveTracker(unknown_commitment_grace_ticks=0)
    pose = Pose2D(0.0, 0.0, 0.0)
    route_heading = tracker._target_heading_error(
        pose=pose,
        goal_world=(10.0, 0.0),
        route_waypoints_world=((0.0, 0.0), (0.0, 2.0), (10.0, 0.0)),
        waypoint=None,
    )
    assert route_heading == pytest.approx(math.pi / 2.0)
    progressed_target = tracker._route_guidance_target(
        pose=Pose2D(2.0, 0.0, 0.0),
        route_waypoints_world=((0.0, 0.0), (1.0, 0.0), (2.0, 0.0), (3.0, 1.0)),
    )
    assert progressed_target == (3.0, 1.0)
    off_route_target = tracker._route_guidance_target(
        pose=Pose2D(2.0, 2.0, 0.0),
        route_waypoints_world=((0.0, 0.0), (1.0, 0.0), (2.0, 0.0), (3.0, 0.0)),
    )
    assert off_route_target == (3.0, 0.0)

    live_waypoint = BodyWaypoint(
        world_xy=(1.0, 2.0),
        forward_m=1.0,
        left_m=2.0,
        distance_m=math.sqrt(5.0),
        heading_error_rad=1.10,
        route_index=1,
        is_final=False,
    )
    tracker._committed_heading_world_rad = 0.0
    tracker._commitment_start_goal_distance_m = 4.0
    tracker._detour_side = -1
    monkeypatch.setattr(tracker, "_direction_state", lambda *_args: ("unknown", 0.0))
    captured: dict[str, float] = {}

    def capture_start_escape(**kwargs):
        captured["target_heading_error"] = float(kwargs["target_heading_error"])
        return MidLevelCommand(note="captured")

    monkeypatch.setattr(tracker, "_start_escape", capture_start_escape)
    command = tracker.select(
        pose=pose,
        scan=_scan(),
        goal_world=(4.0, 0.0),
        route_waypoints_world=((0.0, 0.0), (4.0, 0.0)),
        nominal=MidLevelCommand(vx=0.3, note="grid_track"),
        waypoint=live_waypoint,
        route_available=True,
    )
    assert command.note == "captured"
    assert captured["target_heading_error"] == pytest.approx(1.10)


def test_repeated_block_recovery_retains_side_and_heading_on_route_available_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tracker = SampledPredictiveTracker()
    blocked_scan = _scan({math.pi / 4.0: 0.8})
    monkeypatch.setattr(tracker, "_direction_state", _gap_direction_state(-0.80))

    first_escape = None
    for _ in range(3):
        first_escape = _select(tracker, scan=blocked_scan, route_available=True)
    assert first_escape is not None and first_escape.note.startswith("v9s4_escape_rotate")
    assert tracker._detour_side == -1
    assert tracker._detour_originated_from_route_loss is False
    first_heading = tracker._committed_heading_world_rad

    tracker._settled = True
    tracker._settling = False
    tracker._escape_start_xy = (0.0, 0.0)
    completed = _select(
        tracker,
        pose=Pose2D(0.30, 0.0, 0.0),
        scan=_scan(),
        route_available=True,
    )
    assert completed is None
    assert tracker._detour_side == -1
    assert tracker._detour_originated_from_route_loss is False

    monkeypatch.setattr(
        tracker,
        "_direction_state",
        _gap_direction_state(-0.80, 0.35),
    )
    second_escape = None
    for _ in range(3):
        second_escape = _select(
            tracker,
            pose=Pose2D(0.30, 0.0, 0.0),
            scan=blocked_scan,
            route_available=True,
        )

    assert second_escape is not None and second_escape.note.startswith(
        "v9s4_escape_rotate"
    )
    assert tracker._detour_side == -1
    assert tracker._detour_originated_from_route_loss is False
    assert tracker._committed_heading_world_rad is not None
    assert tracker._committed_heading_world_rad < 0.0
    assert abs(_wrapped_difference(tracker._committed_heading_world_rad, first_heading)) < 0.4


def test_stop_reset_and_invalid_scan_clear_all_recovery_memory() -> None:
    tracker = SampledPredictiveTracker()

    def start_route_loss() -> None:
        command = _select(
            tracker,
            route_available=False,
            waypoint=None,
            nominal=MidLevelCommand(vyaw=0.0, note="grid_recover_scan"),
        )
        assert command is not None
        assert tracker._detour_side is not None
        assert tracker._previous_gap_heading_world_rad is not None

    def assert_cleared() -> None:
        assert tracker._committed_heading_world_rad is None
        assert tracker._previous_gap_heading_world_rad is None
        assert tracker._detour_side is None
        assert tracker._detour_latch_goal_distance_m is None
        assert tracker._detour_originated_from_route_loss is None
        assert tracker._direction_unknown_ticks == 0
        assert tracker._sweep_unknown_ticks == 0
        assert tracker._commitment_start_goal_distance_m is None
        assert tracker._searching_for_gap is False
        assert tracker._search_exhausted is False
        assert tracker._search_ticks == 0
        assert tracker._search_trigger is None
        assert tracker._search_start_goal_distance_m is None
        assert tracker._search_started_route_unavailable is None
        assert tracker._nominal_release_start_xy is None

    start_route_loss()
    _select(
        tracker,
        route_available=False,
        waypoint=None,
        nominal=MidLevelCommand(stop=True, note="stop"),
    )
    assert_cleared()

    start_route_loss()
    tracker.reset()
    assert_cleared()

    start_route_loss()
    invalid = _select(
        tracker,
        scan=_scan(fill=math.nan),
        route_available=False,
        waypoint=None,
        nominal=MidLevelCommand(vyaw=0.0, note="grid_recover_scan"),
    )
    assert invalid is not None and "scan_unavailable" in invalid.note
    assert_cleared()


def test_direction_and_curved_sweep_unknown_counters_are_independent() -> None:
    tracker = SampledPredictiveTracker(unknown_commitment_grace_ticks=3)
    pose = Pose2D(0.0, 0.0, 0.0)
    tracker._committed_heading_world_rad = math.radians(-3.5)
    tracker._escape_start_xy = pose.xy
    tracker._settled = True
    tracker._settling = False

    sweep_unknown_scan = _scan(missing=_dropout(0.0, 4))
    direction_unknown_scan = _scan(missing=_dropout(math.radians(-3.5), 5))

    first_sweep = _select(tracker, pose=pose, scan=sweep_unknown_scan)
    assert first_sweep is not None and "sweep_unknown_ticks=1" in first_sweep.note
    assert tracker._direction_unknown_ticks == 0
    assert tracker._sweep_unknown_ticks == 1

    direction_loss = _select(tracker, pose=pose, scan=direction_unknown_scan)
    assert direction_loss is not None
    assert "direction_unknown_ticks=1" in direction_loss.note
    assert tracker._direction_unknown_ticks == 1
    assert tracker._sweep_unknown_ticks == 1

    second_sweep = _select(tracker, pose=pose, scan=sweep_unknown_scan)
    assert second_sweep is not None and "sweep_unknown_ticks=2" in second_sweep.note
    assert tracker._direction_unknown_ticks == 0
    assert tracker._sweep_unknown_ticks == 2

    observed_advance = _select(tracker, pose=pose, scan=_scan())
    assert observed_advance is not None
    assert observed_advance.note.startswith("v9s4_escape_advance")
    assert tracker._direction_unknown_ticks == 0
    assert tracker._sweep_unknown_ticks == 0


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
        if command.note.startswith("v9s4_escape_advance"):
            break
    assert command.note.startswith("v9s4_escape_advance")

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
