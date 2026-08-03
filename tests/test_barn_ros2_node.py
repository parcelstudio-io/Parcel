from __future__ import annotations

import math

import pytest

from evals.external.barn_ros2_node import (
    STARTUP_LIVENESS_EXIT_CODE,
    StartupLivenessSnapshot,
    StartupLivenessTracker,
    _parser,
    _validate_startup_limits,
    classify_startup_liveness,
    startup_translation_is_live,
)


def _snapshot(**overrides: float) -> StartupLivenessSnapshot:
    values = {
        "elapsed_s": 10.0,
        "odometry_count": 100,
        "scan_count": 100,
        "policy_command_count": 100,
        "cumulative_forward_opportunity_m": 0.5,
        "cumulative_yaw_opportunity_rad": 1.0,
        "max_xy_response_m": 0.0,
        "max_yaw_response_rad": 0.5,
    }
    values.update(overrides)
    return StartupLivenessSnapshot(
        elapsed_s=float(values["elapsed_s"]),
        odometry_count=int(values["odometry_count"]),
        scan_count=int(values["scan_count"]),
        policy_command_count=int(values["policy_command_count"]),
        cumulative_forward_opportunity_m=float(values["cumulative_forward_opportunity_m"]),
        cumulative_yaw_opportunity_rad=float(values["cumulative_yaw_opportunity_rad"]),
        max_xy_response_m=float(values["max_xy_response_m"]),
        max_yaw_response_rad=float(values["max_yaw_response_rad"]),
    )


@pytest.mark.parametrize(
    "missing",
    [
        {"odometry_count": 0},
        {"scan_count": 0},
        {"policy_command_count": 0},
    ],
)
def test_startup_liveness_classifies_missing_inputs(missing: dict[str, float]) -> None:
    assert classify_startup_liveness(_snapshot(**missing)) == "no_inputs"
    assert classify_startup_liveness(_snapshot(max_xy_response_m=0.10, **missing)) == "no_inputs"


def test_startup_liveness_preserves_turn_first_window_then_requires_translation() -> None:
    turning = _snapshot(
        elapsed_s=9.999,
        cumulative_forward_opportunity_m=0.0,
        cumulative_yaw_opportunity_rad=2.5,
        max_yaw_response_rad=1.4,
    )

    assert classify_startup_liveness(turning) is None
    assert (
        classify_startup_liveness(
            _snapshot(
                cumulative_forward_opportunity_m=0.0,
                cumulative_yaw_opportunity_rad=2.5,
                max_yaw_response_rad=1.4,
            )
        )
        == "policy_no_translation"
    )


def test_startup_liveness_separates_actuator_failure_from_small_xy_response() -> None:
    assert classify_startup_liveness(_snapshot()) == "actuator_no_response"
    assert classify_startup_liveness(_snapshot(max_xy_response_m=0.02)) is None


def test_startup_liveness_does_not_accept_xy_drift_without_forward_policy_output() -> None:
    without_policy = _snapshot(
        policy_command_count=0,
        cumulative_forward_opportunity_m=0.0,
        max_xy_response_m=0.10,
    )
    turn_only = _snapshot(
        cumulative_forward_opportunity_m=0.0,
        max_xy_response_m=0.10,
    )

    assert startup_translation_is_live(without_policy) is False
    assert classify_startup_liveness(without_policy) == "no_inputs"
    assert startup_translation_is_live(turn_only) is False
    assert classify_startup_liveness(turn_only) == "policy_no_translation"


def test_tracker_counts_inputs_integrates_opportunity_and_wraps_yaw_response() -> None:
    tracker = StartupLivenessTracker(started_s=5.0)
    tracker.observe_scan()
    tracker.observe_scan()
    tracker.observe_odometry(1.0, -2.0, math.pi - 0.05)
    tracker.observe_policy_command(0.4, -0.5, opportunity_period_s=0.1)
    tracker.observe_odometry(1.012, -1.984, -math.pi + 0.05)
    tracker.observe_policy_command(-0.2, 0.25, opportunity_period_s=0.1)

    snapshot = tracker.snapshot(now_s=7.0)

    assert snapshot.elapsed_s == pytest.approx(2.0)
    assert snapshot.odometry_count == 2
    assert snapshot.scan_count == 2
    assert snapshot.policy_command_count == 2
    assert snapshot.cumulative_forward_opportunity_m == pytest.approx(0.04)
    assert snapshot.cumulative_yaw_opportunity_rad == pytest.approx(0.075)
    assert snapshot.max_xy_response_m == pytest.approx(0.02)
    assert snapshot.max_yaw_response_rad == pytest.approx(0.10)


def test_tracker_anchors_xy_response_at_first_positive_forward_command() -> None:
    tracker = StartupLivenessTracker(started_s=0.0)
    tracker.observe_scan()
    tracker.observe_odometry(0.0, 0.0, 0.0)
    tracker.observe_odometry(0.50, 0.0, 0.25)
    tracker.observe_policy_command(0.0, 0.5, opportunity_period_s=0.1)

    before_forward = tracker.snapshot(now_s=1.0)
    assert before_forward.max_xy_response_m == 0.0
    assert before_forward.max_yaw_response_rad == pytest.approx(0.25)

    tracker.observe_policy_command(0.4, 0.0, opportunity_period_s=0.1)
    tracker.observe_odometry(0.51, 0.0, 0.25)
    after_forward = tracker.snapshot(now_s=2.0)

    assert after_forward.max_xy_response_m == pytest.approx(0.01)
    assert startup_translation_is_live(after_forward) is False

    tracker.observe_odometry(0.52, 0.0, 0.25)
    assert startup_translation_is_live(tracker.snapshot(now_s=3.0)) is True


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        ({"startup_window_s": 1.99}, "startup-window"),
        ({"startup_window_s": 60.01}, "startup-window"),
        ({"min_xy_response_m": 0.0009}, "startup-min-xy-response"),
        ({"min_xy_response_m": 0.101}, "startup-min-xy-response"),
        ({"min_forward_opportunity_m": 0.004}, "startup-min-forward-opportunity"),
        ({"min_forward_opportunity_m": 2.01}, "startup-min-forward-opportunity"),
        (
            {"min_xy_response_m": 0.08, "min_forward_opportunity_m": 0.05},
            "at least",
        ),
    ],
)
def test_startup_cli_limits_fail_closed(
    arguments: dict[str, float],
    message: str,
) -> None:
    limits = {
        "startup_window_s": 10.0,
        "min_xy_response_m": 0.02,
        "min_forward_opportunity_m": 0.05,
    }
    limits.update(arguments)

    with pytest.raises(ValueError, match=message):
        _validate_startup_limits(**limits)


def test_startup_cli_defaults_are_bounded_and_failure_exit_is_nonzero() -> None:
    args = _parser().parse_args(["--navigation-config", "navigation.yaml"])

    _validate_startup_limits(
        startup_window_s=args.startup_window,
        min_xy_response_m=args.startup_min_xy_response,
        min_forward_opportunity_m=args.startup_min_forward_opportunity,
    )
    assert args.startup_window == pytest.approx(10.0)
    assert STARTUP_LIVENESS_EXIT_CODE != 0
