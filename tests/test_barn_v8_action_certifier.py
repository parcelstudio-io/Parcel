from __future__ import annotations

import inspect
import math
import struct
from pathlib import Path

import pytest

from evals.external import barn_v8_action_certifier as certifier_module
from evals.external.barn_v8_action_certifier import (
    BARN_V8_BOUNDARY_ALGORITHM_ID,
    BARN_V8_BOUNDARY_RULE_SCOPE,
    BARN_V8_BOUNDARY_SCOPE,
    BARN_V8_CERTIFIER_ID,
    BARN_V8_PROFILE_ID,
    BARN_V8_UNCERTIFIED_DOMAINS,
    FROZEN_V8_BARN_EVALUATOR_PROFILE,
    V8BarnEvaluatorProfile,
    certify_v8_published_barn_action,
)

RAY_COUNT = 720
ANGLE_MIN_RAD = -math.pi
ANGLE_INCREMENT_RAD = 2.0 * math.pi / (RAY_COUNT - 1)


def _bearing(index: int) -> float:
    return ANGLE_MIN_RAD + index * ANGLE_INCREMENT_RAD


def _index_near(bearing_rad: float) -> int:
    return min(
        range(RAY_COUNT),
        key=lambda index: abs(
            (_bearing(index) - bearing_rad + math.pi) % (2.0 * math.pi) - math.pi
        ),
    )


def _scan(
    hits: dict[int, float] | None = None,
    *,
    fill: float = math.inf,
) -> tuple[float, ...]:
    values = [fill] * RAY_COUNT
    for index, distance in (hits or {}).items():
        values[index] = distance
    return tuple(values)


def _certify(
    vx_mps: float,
    yaw_rate_rps: float,
    ranges_m: tuple[float, ...],
    *,
    angle_min_rad: float = ANGLE_MIN_RAD,
    angle_increment_rad: float = ANGLE_INCREMENT_RAD,
    control_period_s: float = 0.1,
):
    return certify_v8_published_barn_action(
        vx_mps,
        yaw_rate_rps,
        ranges_m,
        angle_min_rad=angle_min_rad,
        angle_increment_rad=angle_increment_rad,
        control_period_s=control_period_s,
    )


def _float32(value: float) -> float:
    return struct.unpack("<f", struct.pack("<f", value))[0]


def test_certifier_is_source_isolated_from_the_candidate_shield() -> None:
    source = Path(inspect.getfile(certifier_module)).read_text(encoding="utf-8")

    assert "parcel_robot" not in source
    assert "experimental_all_ray_shield" not in source


def test_certificate_pins_the_exact_profile_and_all_720_clear_bins() -> None:
    certificate = _certify(0.45, 0.0, _scan())

    assert certificate.schema_version == 1
    assert certificate.certifier_id == BARN_V8_CERTIFIER_ID
    assert certificate.profile_id == BARN_V8_PROFILE_ID
    assert certificate.profile_sha256 == (
        "71401cd344bcc187846236e942e27849db72d32f479a284914c890aaaae4a7c7"
    )
    assert certificate.boundary_algorithm_id == BARN_V8_BOUNDARY_ALGORITHM_ID
    assert certificate.ray_count == certificate.examined_ray_count == 720
    assert certificate.finite_return_count == 0
    assert certificate.clear_ray_count == 720
    assert certificate.unavailable_ray_count == 0
    assert certificate.perception_available is True
    assert certificate.perception_complete is True
    assert certificate.observed_return_boundary_satisfied is True
    assert certificate.maximum_observed_closing_speed_mps == 0.0
    assert certificate.maximum_swept_projected_displacement_m == 0.0
    assert certificate.minimum_projected_margin_m is None
    assert certificate.published_vy_mps == 0.0
    assert certificate.stop_distance_m == 0.8
    assert certificate.reaction_horizon_s == 0.12
    assert certificate.control_period_s == 0.1


def test_exact_profile_accepts_float32_ros_scan_geometry() -> None:
    certificate = _certify(
        0.0,
        0.0,
        _scan(),
        angle_min_rad=_float32(-math.pi),
        angle_increment_rad=_float32(2.0 * math.pi / (RAY_COUNT - 1)),
    )

    assert certificate.ray_count == 720
    assert certificate.perception_complete is True


def test_farther_head_on_return_cannot_hide_behind_nearer_tangential_return() -> None:
    tangent_index = _index_near(math.pi / 2.0)
    forward_index = _index_near(0.0)
    ranges = _scan({tangent_index: 0.81, forward_index: 0.83})

    certificate = _certify(0.45, 0.0, ranges)

    expected_closing_speed = 0.45 * math.cos(_bearing(forward_index))
    expected_margin = 0.83 - 0.8 - 0.12 * expected_closing_speed
    assert ranges[tangent_index] < ranges[forward_index]
    assert certificate.examined_ray_count == 720
    assert certificate.finite_return_count == 2
    assert certificate.limiting_ray_index == forward_index
    assert certificate.limiting_ray_index != tangent_index
    assert certificate.limiting_maximum_closing_speed_mps == pytest.approx(
        expected_closing_speed
    )
    assert certificate.minimum_projected_margin_m == pytest.approx(expected_margin)
    assert certificate.minimum_projected_margin_m < 0.0
    assert certificate.violating_return_count == 1
    assert certificate.observed_return_boundary_satisfied is False


@pytest.mark.parametrize("side", (1.0, -1.0))
def test_signed_yaw_toward_near_tangent_return_is_not_treated_as_yaw_away(
    side: float,
) -> None:
    tangent_index = _index_near(side * math.pi / 2.0)
    bearing = _bearing(tangent_index)
    ranges = _scan({tangent_index: 0.801})

    toward = _certify(0.45, side * 0.8, ranges)
    away = _certify(0.45, -side * 0.8, ranges)

    toward_sweep = side * 0.8 * 0.12
    expected_toward_speed = 0.45 * max(
        math.cos(-bearing),
        math.cos(toward_sweep - bearing),
        0.0,
    )
    assert toward.heading_sweep_rad == pytest.approx(toward_sweep)
    assert toward.maximum_observed_closing_speed_mps == pytest.approx(
        expected_toward_speed
    )
    assert toward.maximum_observed_closing_speed_mps > (
        20.0 * away.maximum_observed_closing_speed_mps
    )
    assert toward.observed_return_boundary_satisfied is False
    assert away.observed_return_boundary_satisfied is True


def test_near_tangent_no_yaw_does_not_inherit_full_forward_speed() -> None:
    tangent_index = _index_near(math.pi / 2.0)
    certificate = _certify(0.45, 0.0, _scan({tangent_index: 0.801}))

    expected_speed = 0.45 * max(math.cos(_bearing(tangent_index)), 0.0)
    assert 0.0 < expected_speed < 0.002
    assert certificate.maximum_observed_closing_speed_mps == pytest.approx(expected_speed)
    assert certificate.maximum_swept_projected_displacement_m == pytest.approx(
        0.12 * expected_speed
    )
    assert certificate.observed_return_boundary_satisfied is True


def test_reverse_command_checks_returns_behind_the_robot() -> None:
    rear_index = 0
    ranges = _scan({rear_index: 0.82})

    reverse = _certify(-0.3, 0.0, ranges)
    forward = _certify(0.3, 0.0, ranges)

    assert _bearing(rear_index) == -math.pi
    assert reverse.maximum_observed_closing_speed_mps == pytest.approx(0.3)
    assert reverse.maximum_swept_projected_displacement_m == pytest.approx(0.036)
    assert reverse.minimum_projected_margin_m == pytest.approx(-0.016)
    assert reverse.observed_return_boundary_satisfied is False
    assert forward.maximum_observed_closing_speed_mps == 0.0
    assert forward.positive_closing_return_count == 0
    assert forward.observed_return_boundary_satisfied is True


@pytest.mark.parametrize("turn_sign", (1.0, -1.0))
def test_full_signed_revolution_finds_alignment_without_yaw_sampling(
    turn_sign: float,
) -> None:
    arbitrary_index = _index_near(1.1)
    yaw_rate = turn_sign * 2.0 * math.pi / 0.12

    certificate = _certify(0.4, yaw_rate, _scan({arbitrary_index: 0.84}))

    assert certificate.maximum_observed_closing_speed_mps == pytest.approx(0.4)
    assert certificate.maximum_swept_projected_displacement_m == pytest.approx(0.048)
    assert certificate.minimum_projected_margin_m == pytest.approx(-0.008)
    assert certificate.observed_return_boundary_satisfied is False


def test_nan_is_unavailable_and_positive_infinity_is_clear_without_conflation() -> None:
    forward_index = _index_near(0.0)
    unavailable_index = _index_near(1.0)
    ranges = list(_scan({forward_index: 1.0}))
    ranges[unavailable_index] = math.nan

    incomplete = _certify(0.1, 0.0, tuple(ranges))
    complete_ranges = list(ranges)
    complete_ranges[unavailable_index] = math.inf
    complete = _certify(0.1, 0.0, tuple(complete_ranges))

    assert incomplete.finite_return_count == 1
    assert incomplete.clear_ray_count == 718
    assert incomplete.unavailable_ray_count == 1
    assert incomplete.perception_available is True
    assert incomplete.perception_complete is False
    assert incomplete.scan_sha256 != complete.scan_sha256
    assert complete.finite_return_count == 1
    assert complete.clear_ray_count == 719
    assert complete.unavailable_ray_count == 0
    assert complete.perception_complete is True


def test_all_nan_result_is_vacuous_and_explicitly_does_not_claim_missing_space() -> None:
    certificate = _certify(0.45, 0.8, _scan(fill=math.nan))

    assert certificate.finite_return_count == 0
    assert certificate.clear_ray_count == 0
    assert certificate.unavailable_ray_count == 720
    assert certificate.perception_available is False
    assert certificate.perception_complete is False
    assert certificate.observed_return_boundary_satisfied is True
    assert certificate.boundary_scope == BARN_V8_BOUNDARY_SCOPE
    assert certificate.boundary_rule_scope == BARN_V8_BOUNDARY_RULE_SCOPE
    assert certificate.uncertified_domains == BARN_V8_UNCERTIFIED_DOMAINS
    assert certificate.uncertified_domains == (
        "unavailable_nan_directions",
        "angular_space_between_discrete_scan_rays",
        "objects_moving_during_reaction_horizon",
        "robot_geometry_or_swept_footprint",
    )


@pytest.mark.parametrize(
    ("ranges", "error_type", "message"),
    (
        ((math.inf,) * 719, ValueError, "exactly 720 rays"),
        (_scan({10: -0.01}), ValueError, "non-negative, NaN, or positive infinity"),
        (_scan({10: -math.inf}), ValueError, "non-negative, NaN, or positive infinity"),
        (_scan({10: "1.0"}), TypeError, "range 10 must be numeric"),
        (_scan({10: True}), TypeError, "range 10 must be numeric"),
    ),
)
def test_malformed_scan_bins_fail_closed(
    ranges: tuple[float, ...],
    error_type: type[Exception],
    message: str,
) -> None:
    with pytest.raises(error_type, match=message):
        _certify(0.1, 0.0, ranges)


@pytest.mark.parametrize(
    ("overrides", "message"),
    (
        ({"angle_min_rad": 0.0}, "calibrated -pi scan origin"),
        ({"angle_increment_rad": ANGLE_INCREMENT_RAD * 0.9}, "full-circle coverage"),
        ({"angle_increment_rad": 0.0}, "must be positive"),
        ({"control_period_s": 0.11}, "control period"),
    ),
)
def test_malformed_scan_geometry_or_dt_metadata_fails_closed(
    overrides: dict[str, float],
    message: str,
) -> None:
    arguments = {
        "angle_min_rad": ANGLE_MIN_RAD,
        "angle_increment_rad": ANGLE_INCREMENT_RAD,
        "control_period_s": 0.1,
    }
    arguments.update(overrides)
    with pytest.raises(ValueError, match=message):
        certify_v8_published_barn_action(0.1, 0.0, _scan(), **arguments)


@pytest.mark.parametrize(
    ("vx_mps", "yaw_rate_rps", "error_type", "message"),
    (
        (math.inf, 0.0, ValueError, "vx_mps must be finite"),
        (0.1, math.nan, ValueError, "yaw_rate_rps must be finite"),
        (True, 0.0, TypeError, "vx_mps must be a number"),
    ),
)
def test_malformed_published_action_fails_closed(
    vx_mps: float,
    yaw_rate_rps: float,
    error_type: type[Exception],
    message: str,
) -> None:
    with pytest.raises(error_type, match=message):
        _certify(vx_mps, yaw_rate_rps, _scan())


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("profile_id", "different-profile"),
        ("stop_distance_m", 0.81),
        ("reaction_horizon_s", 0.1),
        ("control_period_s", 0.11),
        ("required_ray_count", 719),
        ("closing_epsilon_mps", 1e-6),
        ("certificate_tolerance_m", 1e-6),
    ),
)
def test_profile_cannot_be_silently_relaxed(field: str, value: object) -> None:
    values = FROZEN_V8_BARN_EVALUATOR_PROFILE.identity_payload()
    values[field] = value

    with pytest.raises(ValueError, match="v8 evaluator profile requires"):
        V8BarnEvaluatorProfile(**values)
