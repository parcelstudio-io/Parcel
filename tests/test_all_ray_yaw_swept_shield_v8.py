from __future__ import annotations

import math
from pathlib import Path

import pytest
import yaml

from parcel_robot.navigation.base import GoalPose, MidLevelCommand, Mission, NavObservation
from parcel_robot.navigation.collision import CollisionPolicy, apply_collision_brake
from parcel_robot.navigation.experimental_all_ray_shield import (
    V8_ALL_RAY_MODE,
    V8_ALL_RAY_PROFILE_ID,
    V8AllRayShieldConfig,
    apply_v8_all_ray_shield,
    certify_v8_all_ray_action,
    verify_v8_all_ray_action_certificate,
)
from parcel_robot.navigation.pipeline import DirectiveNavigator

RAY_COUNT = 720
ANGLE_MIN_RAD = -math.pi
ANGLE_INCREMENT_RAD = 2.0 * math.pi / (RAY_COUNT - 1)
REPO_ROOT = Path(__file__).resolve().parents[1]
V8_CONFIG = (
    REPO_ROOT
    / "configs"
    / "navigation"
    / "experiments"
    / "barn_grid_v1_all_ray_yaw_swept_cap_0p8_v8.yaml"
)


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


def _apply(
    vx_mps: float,
    vy_mps: float,
    yaw_rate_rps: float,
    ranges_m: tuple[float, ...],
    *,
    preexisting_scale_limit: float = 1.0,
):
    return apply_v8_all_ray_shield(
        vx_mps,
        vy_mps,
        yaw_rate_rps,
        ranges_m,
        angle_min_rad=ANGLE_MIN_RAD,
        angle_increment_rad=ANGLE_INCREMENT_RAD,
        preexisting_scale_limit=preexisting_scale_limit,
    )


def test_v8_farther_forward_ray_cannot_be_hidden_by_nearer_tangential_ray() -> None:
    tangent_index = _index_near(math.pi / 2.0)
    forward_index = _index_near(0.0)
    tangent_distance = 0.81
    forward_distance = 0.83
    ranges = _scan({tangent_index: tangent_distance, forward_index: forward_distance})

    decision = _apply(0.45, 0.0, 0.0, ranges)

    forward_closing_speed = 0.45 * math.cos(_bearing(forward_index))
    expected_scale = (forward_distance - 0.8) / (0.12 * forward_closing_speed)
    # The unsafe one-nearest selector would choose the tangent return.
    assert tangent_distance < forward_distance
    assert decision.limiting_ray_index == forward_index
    assert decision.all_ray_scale_limit == pytest.approx(expected_scale)
    assert decision.output_vx_mps == pytest.approx(0.45 * expected_scale)
    assert decision.output_vy_mps == 0.0
    assert decision.certificate.observed_return_boundary_satisfied is True
    assert decision.certificate.examined_ray_count == 720
    assert decision.certificate.minimum_projected_margin_m == pytest.approx(0.0, abs=1e-12)


def test_v8_heading_sweep_caps_a_return_that_is_only_tangent_at_action_start() -> None:
    tangent_index = _index_near(math.pi / 2.0)
    ranges = _scan({tangent_index: 0.801})

    without_turn = _apply(0.45, 0.0, 0.0, ranges)
    turning_toward = _apply(0.45, 0.0, 0.8, ranges)

    assert without_turn.applied_scale == 1.0
    assert turning_toward.applied_scale < 1.0
    assert turning_toward.output_yaw_rate_rps == 0.8
    assert turning_toward.certificate.heading_sweep_rad == pytest.approx(0.096)
    assert turning_toward.certificate.observed_return_boundary_satisfied is True
    assert turning_toward.limiting_ray_index == tangent_index


def test_v8_negative_heading_sweep_caps_a_return_to_the_right() -> None:
    right_index = _index_near(-math.pi / 2.0)
    right_bearing = _bearing(right_index)
    ranges = _scan({right_index: 0.801})

    decision = _apply(0.45, 0.0, -0.8, ranges)

    expected_closing_speed = 0.45 * max(
        math.cos(-right_bearing),
        math.cos(-0.8 * 0.12 - right_bearing),
        0.0,
    )
    expected_scale = 0.001 / (0.12 * expected_closing_speed)
    assert decision.applied_scale == pytest.approx(expected_scale)
    assert decision.limiting_maximum_closing_speed_mps == pytest.approx(expected_closing_speed)
    assert decision.output_yaw_rate_rps == -0.8
    assert decision.certificate.observed_return_boundary_satisfied is True


@pytest.mark.parametrize("turn_sign", (1.0, -1.0))
def test_v8_heading_sweep_detects_alignment_across_angle_seam(turn_sign: float) -> None:
    speed = 0.45
    start_heading = turn_sign * (math.pi - 0.02)
    hazard_bearing = -turn_sign * (math.pi - 0.02)
    hazard_index = _index_near(hazard_bearing)
    ranges = _scan({hazard_index: 0.81})

    decision = _apply(
        speed * math.cos(start_heading),
        speed * math.sin(start_heading),
        turn_sign * 0.8,
        ranges,
    )

    assert decision.limiting_ray_index == hazard_index
    assert decision.limiting_maximum_closing_speed_mps == pytest.approx(speed)
    assert decision.applied_scale == pytest.approx(0.01 / (0.12 * speed))
    assert decision.certificate.observed_return_boundary_satisfied is True


@pytest.mark.parametrize("turn_sign", (1.0, -1.0))
@pytest.mark.parametrize("sweep_delta", (-0.2, 0.0, 0.2))
def test_v8_full_revolution_sweep_boundary_is_conservative(
    turn_sign: float,
    sweep_delta: float,
) -> None:
    speed = 0.45
    sweep = turn_sign * (2.0 * math.pi + sweep_delta)
    hazard_index = _index_near(-turn_sign * 0.1)
    hazard_bearing = _bearing(hazard_index)
    ranges = _scan({hazard_index: 0.85})

    decision = _apply(speed, 0.0, sweep / 0.12, ranges)

    if abs(sweep) >= 2.0 * math.pi:
        expected_closing_speed = speed
    else:
        expected_closing_speed = speed * max(
            math.cos(-hazard_bearing),
            math.cos(sweep - hazard_bearing),
            0.0,
        )
    assert decision.limiting_maximum_closing_speed_mps == pytest.approx(expected_closing_speed)
    assert decision.applied_scale == pytest.approx(0.05 / (0.12 * expected_closing_speed))
    assert decision.certificate.observed_return_boundary_satisfied is True


def test_v8_composes_by_minimum_scale_and_preserves_translation_direction() -> None:
    requested_vx = 0.3
    requested_vy = 0.4
    command_bearing = math.atan2(requested_vy, requested_vx)
    hazard_index = _index_near(command_bearing)
    ranges = _scan({hazard_index: 0.82})

    decision = _apply(
        requested_vx,
        requested_vy,
        0.3,
        ranges,
        preexisting_scale_limit=0.2,
    )

    assert decision.all_ray_scale_limit > 0.2
    assert decision.applied_scale == 0.2
    assert decision.output_vx_mps == pytest.approx(0.06)
    assert decision.output_vy_mps == pytest.approx(0.08)
    assert decision.output_vy_mps / decision.output_vx_mps == pytest.approx(
        requested_vy / requested_vx
    )
    assert decision.output_yaw_rate_rps == 0.3
    assert decision.note == "all_ray_preexisting_scale_preserved"
    assert decision.certificate.observed_return_boundary_satisfied is True


def test_v8_adding_returns_can_never_increase_translation() -> None:
    forward_index = _index_near(0.0)
    off_axis_index = _index_near(0.2)
    clear = _apply(0.45, 0.0, 0.0, _scan())
    one_return = _apply(0.45, 0.0, 0.0, _scan({forward_index: 0.84}))
    two_returns = _apply(
        0.45,
        0.0,
        0.0,
        _scan({forward_index: 0.84, off_axis_index: 0.81}),
    )

    assert clear.applied_scale >= one_return.applied_scale >= two_returns.applied_scale
    assert clear.output_vx_mps >= one_return.output_vx_mps >= two_returns.output_vx_mps
    assert two_returns.certificate.observed_return_boundary_satisfied is True


def test_v8_examines_dense_scan_with_more_than_sixty_four_closing_threats() -> None:
    ranges = tuple(0.81 + 0.0001 * (index % 19) for index in range(RAY_COUNT))

    decision = _apply(0.45, 0.0, 0.8, ranges)

    assert decision.certificate.examined_ray_count == 720
    assert decision.certificate.finite_return_count == 720
    assert decision.certificate.positive_closing_return_count > 64
    assert decision.positive_closing_return_count > 64
    assert decision.certificate.observed_return_boundary_satisfied is True
    assert decision.certificate.violating_return_count == 0


@pytest.mark.parametrize(
    ("vx_mps", "vy_mps", "hazard_bearing"),
    (
        (0.45, 0.0, 0.0),
        (0.0, 0.25, math.pi / 2.0),
        (-0.30, 0.0, math.pi),
    ),
)
def test_v8_positive_closing_return_at_hard_boundary_stops_translation(
    vx_mps: float,
    vy_mps: float,
    hazard_bearing: float,
) -> None:
    hazard_index = _index_near(hazard_bearing)

    decision = _apply(vx_mps, vy_mps, 0.0, _scan({hazard_index: 0.8}))

    assert decision.applied_scale == 0.0
    assert decision.output_vx_mps == 0.0
    assert decision.output_vy_mps == 0.0
    assert decision.note == "all_ray_hard_boundary_stop"
    assert decision.certificate.observed_return_boundary_satisfied is True


def test_v8_away_returns_do_not_restrict_translation() -> None:
    behind_index = _index_near(math.pi)
    rear_side_index = _index_near(2.0 * math.pi / 3.0)
    ranges = _scan({behind_index: 0.5, rear_side_index: 0.7})

    decision = _apply(0.45, 0.0, 0.0, ranges)

    assert decision.applied_scale == 1.0
    assert decision.output_vx_mps == 0.45
    assert decision.positive_closing_return_count == 0
    assert decision.note == "all_ray_clear"


def test_v8_duplicate_seam_return_does_not_change_the_cap() -> None:
    # -pi and +pi are the duplicated seam in the calibrated 720-ray scan.
    one = _scan({0: 0.82})
    duplicate = _scan({0: 0.82, RAY_COUNT - 1: 0.82})

    one_decision = _apply(-0.3, 0.0, 0.0, one)
    duplicate_decision = _apply(-0.3, 0.0, 0.0, duplicate)

    assert duplicate_decision.applied_scale == pytest.approx(one_decision.applied_scale)
    assert duplicate_decision.output_vx_mps == pytest.approx(one_decision.output_vx_mps)
    assert duplicate_decision.certificate.observed_return_boundary_satisfied is True


def test_v8_requires_the_complete_full_circle_720_ray_contract() -> None:
    with pytest.raises(ValueError, match="requires 720 rays"):
        apply_v8_all_ray_shield(
            0.2,
            0.0,
            0.0,
            (math.inf,) * 719,
            angle_min_rad=ANGLE_MIN_RAD,
            angle_increment_rad=ANGLE_INCREMENT_RAD,
        )
    with pytest.raises(ValueError, match="full-circle"):
        apply_v8_all_ray_shield(
            0.2,
            0.0,
            0.0,
            _scan(),
            angle_min_rad=ANGLE_MIN_RAD,
            angle_increment_rad=math.radians(270.0) / (RAY_COUNT - 1),
        )
    malformed = list(_scan())
    malformed[100] = -0.1
    with pytest.raises(ValueError, match="range 100"):
        _apply(0.2, 0.0, 0.0, tuple(malformed))


def test_v8_clear_and_unavailable_scans_have_fail_closed_distinct_semantics() -> None:
    clear = _apply(0.2, 0.0, 0.0, _scan())
    unavailable = _apply(0.2, 0.0, 0.0, _scan(fill=math.nan))

    assert clear.output_vx_mps == 0.2
    assert clear.certificate.clear_ray_count == 720
    assert clear.certificate.perception_available is True
    assert clear.certificate.perception_complete is True
    assert unavailable.output_vx_mps == 0.0
    assert unavailable.certificate.unavailable_ray_count == 720
    assert unavailable.certificate.perception_available is False
    assert unavailable.certificate.perception_complete is False
    assert unavailable.note == "all_ray_perception_unavailable_stop"


def test_v8_partial_unavailable_scan_is_explicitly_scoped_and_gate_visible() -> None:
    incomplete = list(_scan(fill=math.nan))
    incomplete[_index_near(0.0)] = math.inf

    decision = _apply(0.45, 0.0, 0.8, tuple(incomplete))

    assert decision.output_vx_mps == 0.45
    assert decision.output_vy_mps == 0.0
    assert decision.output_yaw_rate_rps == 0.8
    assert decision.applied_scale == 1.0
    assert decision.note == "all_ray_observed_returns_only_incomplete_scan"
    assert decision.certificate.perception_available is True
    assert decision.certificate.perception_complete is False
    assert decision.certificate.unavailable_ray_count == 719
    assert decision.certificate.boundary_scope == "observed_finite_returns_only"
    assert decision.certificate.observed_return_boundary_satisfied is True


def test_v8_certificate_is_recomputed_from_scan_and_final_action() -> None:
    tangent_index = _index_near(math.pi / 2.0)
    forward_index = _index_near(0.0)
    ranges = _scan({tangent_index: 0.81, forward_index: 0.83})
    decision = _apply(0.45, 0.0, 0.0, ranges)

    verified = verify_v8_all_ray_action_certificate(
        decision.certificate,
        decision.output_vx_mps,
        decision.output_vy_mps,
        decision.output_yaw_rate_rps,
        ranges,
        angle_min_rad=ANGLE_MIN_RAD,
        angle_increment_rad=ANGLE_INCREMENT_RAD,
    )
    unsafe = certify_v8_all_ray_action(
        0.45,
        0.0,
        0.0,
        ranges,
        angle_min_rad=ANGLE_MIN_RAD,
        angle_increment_rad=ANGLE_INCREMENT_RAD,
    )

    assert verified == decision.certificate
    assert unsafe.observed_return_boundary_satisfied is False
    assert unsafe.violating_return_count >= 1
    with pytest.raises(ValueError, match="does not match"):
        verify_v8_all_ray_action_certificate(
            decision.certificate,
            0.45,
            0.0,
            0.0,
            ranges,
            angle_min_rad=ANGLE_MIN_RAD,
            angle_increment_rad=ANGLE_INCREMENT_RAD,
        )


@pytest.mark.parametrize(
    ("vx_mps", "vy_mps", "yaw_rate_rps"),
    (
        (0.45, 0.0, 0.8),
        (0.45, 0.0, -0.8),
        (0.2, 0.2, 0.8),
        (-0.3, 0.1, -0.8),
        (0.0, -0.25, 0.4),
    ),
)
def test_v8_independent_certificate_holds_across_translation_and_yaw_sweeps(
    vx_mps: float,
    vy_mps: float,
    yaw_rate_rps: float,
) -> None:
    hits = {index: 0.8 + 0.002 * ((index // 37) % 11) for index in range(0, RAY_COUNT, 37)}

    decision = _apply(vx_mps, vy_mps, yaw_rate_rps, _scan(hits))

    assert decision.certificate.examined_ray_count == 720
    assert decision.certificate.observed_return_boundary_satisfied is True
    assert decision.certificate.violating_return_count == 0
    verify_v8_all_ray_action_certificate(
        decision.certificate,
        decision.output_vx_mps,
        decision.output_vy_mps,
        decision.output_yaw_rate_rps,
        _scan(hits),
        angle_min_rad=ANGLE_MIN_RAD,
        angle_increment_rad=ANGLE_INCREMENT_RAD,
    )


def test_v8_scan_digest_binds_nonlimiting_rays() -> None:
    forward_index = _index_near(0.0)
    first_scan = _scan({forward_index: 0.82})
    second_scan = _scan({forward_index: 0.82, _index_near(math.pi): 3.0})
    first = _apply(0.45, 0.0, 0.0, first_scan)
    second = _apply(0.45, 0.0, 0.0, second_scan)

    assert first.applied_scale == pytest.approx(second.applied_scale)
    assert first.certificate.scan_sha256 != second.certificate.scan_sha256
    with pytest.raises(ValueError, match="does not match"):
        verify_v8_all_ray_action_certificate(
            first.certificate,
            second.output_vx_mps,
            second.output_vy_mps,
            second.output_yaw_rate_rps,
            second_scan,
            angle_min_rad=ANGLE_MIN_RAD,
            angle_increment_rad=ANGLE_INCREMENT_RAD,
        )


def test_v8_experimental_config_is_exact_and_deployment_disabled() -> None:
    payload = yaml.safe_load(V8_CONFIG.read_text(encoding="utf-8"))
    safety = payload["safety"]
    profile = V8AllRayShieldConfig.from_mapping(safety["all_ray_yaw_swept_cap"])

    assert payload["deployment_enabled"] is False
    assert safety["predictive_mode"] == V8_ALL_RAY_MODE
    assert profile.profile_id == V8_ALL_RAY_PROFILE_ID
    assert profile.required_ray_count == 720
    assert profile.reaction_horizon_s >= profile.control_period_s
    assert profile.stop_distance_m == 0.8


def test_v8_reaction_horizon_cannot_be_shorter_than_control_period() -> None:
    with pytest.raises(ValueError, match="at least control_period_s"):
        V8AllRayShieldConfig(reaction_horizon_s=0.09, control_period_s=0.1)


def test_v8_profile_identity_cannot_hide_weaker_safety_constants() -> None:
    with pytest.raises(ValueError, match="requires stop_distance_m=0.8"):
        V8AllRayShieldConfig(stop_distance_m=0.01)
    with pytest.raises(ValueError, match="exactly 720"):
        V8AllRayShieldConfig(required_ray_count=720.0)  # type: ignore[arg-type]


class _FixedCommandNavigator:
    def __init__(self, command: MidLevelCommand) -> None:
        self.command = command

    def reset(self, mission: Mission) -> None:
        mission.status = "running"

    def act(self, observation: NavObservation, mission: Mission) -> MidLevelCommand:
        return self.command

    def close(self) -> None:
        return None


def _v8_pipeline(command: MidLevelCommand) -> DirectiveNavigator:
    navigator = DirectiveNavigator.from_config(V8_CONFIG)
    navigator._navigator.close()
    navigator._navigator = _FixedCommandNavigator(command)
    navigator.start(
        Mission(
            directive="BARN metric goal",
            goal=GoalPose(x=10.0, y=0.0, arrival_radius_m=0.75),
        )
    )
    return navigator


def test_v8_pipeline_applies_the_all_ray_shield_after_velocity_bounds() -> None:
    tangent_index = _index_near(math.pi / 2.0)
    forward_index = _index_near(0.0)
    ranges = _scan({tangent_index: 0.81, forward_index: 0.83})
    navigator = _v8_pipeline(MidLevelCommand(vx=0.9, vy=0.0, note="fixed_track"))

    try:
        output = navigator.step(
            NavObservation(
                position=(0.0, 0.0, 0.0),
                heading_deg=0.0,
                lidar=ranges,
                nearest_obstacle_m=0.81,
                extras={
                    "obstacle_bearing_rad": _bearing(tangent_index),
                    "lidar_angle_min_rad": ANGLE_MIN_RAD,
                    "lidar_angle_increment_rad": ANGLE_INCREMENT_RAD,
                },
            )
        )
    finally:
        navigator.close()

    # The configured 0.45 m/s component bound is applied before certification.
    assert 0.0 < output.vx < 0.45
    assert output.vy == 0.0
    assert output.stop is False
    assert "all_ray_yaw_swept_projected_cap" in output.note
    certificate = certify_v8_all_ray_action(
        output.vx,
        output.vy,
        output.vyaw,
        ranges,
        angle_min_rad=ANGLE_MIN_RAD,
        angle_increment_rad=ANGLE_INCREMENT_RAD,
    )
    assert certificate.observed_return_boundary_satisfied is True


def test_v8_delegates_the_hard_predictive_boundary_to_the_all_ray_finalizer() -> None:
    vx, vy, note = apply_collision_brake(
        0.45,
        0.0,
        nearest_person_m=None,
        nearest_obstacle_m=0.81,
        nearest_obstacle_bearing_rad=0.0,
        policy=CollisionPolicy(
            obstacle_stop_m=0.8,
            obstacle_slow_m=1.2,
            reaction_time_s=0.12,
            predictive_mode=V8_ALL_RAY_MODE,
        ),
    )

    # The legacy layer retains its comfort slowdown, but it does not perform
    # a one-nearest projected cap. The final 720-ray shield owns that hard
    # boundary and therefore cannot hide a farther positive-closing return.
    assert vx == pytest.approx(0.45 * 0.35)
    assert vy == 0.0
    assert note == "obstacle_slow"


def test_v8_pipeline_fails_closed_when_the_full_scan_contract_is_missing() -> None:
    navigator = _v8_pipeline(MidLevelCommand(vx=0.3, vy=0.1, note="fixed_track"))

    try:
        output = navigator.step(
            NavObservation(
                position=(0.0, 0.0, 0.0),
                heading_deg=0.0,
                lidar=None,
                extras={},
            )
        )
    finally:
        navigator.close()

    assert (output.vx, output.vy) == (0.0, 0.0)
    assert output.stop is False
    assert output.note.endswith("all_ray_contract_invalid_stop")
