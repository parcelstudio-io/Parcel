"""Stratum-1 pose seam: estimate validation, providers, frames, health, chance constraint."""

from __future__ import annotations

import math

import pytest

from parcel_robot.navigation.approach import point_in_polygon_with_clearance
from parcel_robot.navigation.base import MAP_FRAME, ODOM_FRAME, NavObservation, pose_in
from parcel_robot.pose import (
    POSE_PROVIDER_KEY,
    ZERO_COVARIANCE,
    DriftingOdomProvider,
    Frame,
    OdometryNoiseParams,
    PoseEstimate,
    PoseHealth,
    PoseProvider,
    TruthPoseProvider,
    legacy_position_yaw,
    load_pose_config,
    observation_pose,
    p_inside_disc,
    p_inside_polygon,
    point_in_polygon_with_clearance_pure,
    use_pose_provider,
)

SQUARE = ((0.0, 0.0), (4.0, 0.0), (4.0, 3.0), (0.0, 3.0))


# --------------------------------------------------------------------------
# PoseEstimate — fail-closed validation
# --------------------------------------------------------------------------


def test_pose_estimate_defaults_are_exact_healthy_and_zero_covariance() -> None:
    pose = PoseEstimate(1.0, 2.0, 0.5, Frame.MAP)
    assert pose.xy == (1.0, 2.0)
    assert pose.covariance == ZERO_COVARIANCE
    assert pose.is_healthy and pose.is_exact
    assert pose.position_sigma_m == 0.0 and pose.yaw_sigma_rad == 0.0


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_non_finite_pose_components_are_rejected(bad: float) -> None:
    for kwargs in ({"x": bad}, {"y": bad}, {"yaw": bad}, {"stamp_monotonic_s": bad}):
        base = {"x": 0.0, "y": 0.0, "yaw": 0.0, "frame": Frame.MAP, **kwargs}
        with pytest.raises(ValueError):
            PoseEstimate(**base)


def test_covariance_must_be_a_row_major_3x3() -> None:
    with pytest.raises(ValueError, match="row-major 3x3"):
        PoseEstimate(0.0, 0.0, 0.0, Frame.MAP, covariance=(0.0, 0.0))


def test_negative_variance_is_rejected() -> None:
    cov = list(ZERO_COVARIANCE)
    cov[4] = -1.0
    with pytest.raises(ValueError, match="non-negative"):
        PoseEstimate(0.0, 0.0, 0.0, Frame.MAP, covariance=tuple(cov))


def test_asymmetric_covariance_is_rejected() -> None:
    cov = [1.0, 0.3, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0]
    with pytest.raises(ValueError, match="symmetric"):
        PoseEstimate(0.0, 0.0, 0.0, Frame.MAP, covariance=tuple(cov))


def test_indefinite_xy_block_is_rejected() -> None:
    # Symmetric but not PSD: correlation magnitude exceeds the variances.
    cov = [1.0, 2.0, 0.0, 2.0, 1.0, 0.0, 0.0, 0.0, 1.0]
    with pytest.raises(ValueError, match="positive semidefinite"):
        PoseEstimate(0.0, 0.0, 0.0, Frame.MAP, covariance=tuple(cov))


def test_frame_and_health_must_be_enum_members() -> None:
    with pytest.raises(TypeError):
        PoseEstimate(0.0, 0.0, 0.0, "map")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        PoseEstimate(0.0, 0.0, 0.0, Frame.MAP, health="lost")  # type: ignore[arg-type]


def test_position_sigma_is_the_Zr_handoff() -> None:
    cov = [0.09, 0.0, 0.0, 0.0, 0.16, 0.0, 0.0, 0.0, 0.04]
    pose = PoseEstimate(0.0, 0.0, 0.0, Frame.MAP, covariance=tuple(cov))
    assert pose.position_sigma_m == pytest.approx(0.5)
    assert pose.yaw_sigma_rad == pytest.approx(0.2)
    assert not pose.is_exact


# --------------------------------------------------------------------------
# TruthPoseProvider — the equality-preserving default
# --------------------------------------------------------------------------


def test_truth_provider_satisfies_the_protocol() -> None:
    assert isinstance(TruthPoseProvider(), PoseProvider)
    assert isinstance(DriftingOdomProvider(), PoseProvider)


def test_truth_provider_returns_identical_map_and_odom() -> None:
    provider = TruthPoseProvider()
    provider.update_truth(3.25, -1.5, 0.75, stamp_monotonic_s=12.5)
    map_pose = provider.get_pose(Frame.MAP)
    odom_pose = provider.get_pose(Frame.ODOM)
    assert (map_pose.x, map_pose.y, map_pose.yaw) == (odom_pose.x, odom_pose.y, odom_pose.yaw)
    assert map_pose.frame is Frame.MAP and odom_pose.frame is Frame.ODOM
    assert map_pose.covariance == ZERO_COVARIANCE
    assert map_pose.health is PoseHealth.HEALTHY
    assert map_pose.stamp_monotonic_s == 12.5


def test_truth_provider_is_bit_exact_on_the_floats_it_was_given() -> None:
    provider = TruthPoseProvider()
    for value in (0.1, 1e-9, -1234.56789, 2.0 / 3.0):
        provider.update_truth(value, -value, value / 3.0)
        pose = provider.get_pose(Frame.MAP)
        assert pose.x == value and pose.y == -value and pose.yaw == value / 3.0


def test_truth_provider_can_never_be_unhealthy() -> None:
    provider = TruthPoseProvider()
    for _ in range(50):
        provider.update_truth(1.0, 1.0, 1.0, stamp_monotonic_s=1e6)
        assert provider.get_pose(Frame.MAP).health is PoseHealth.HEALTHY


# --------------------------------------------------------------------------
# observation_pose — the one door
# --------------------------------------------------------------------------


def test_observation_pose_without_a_provider_is_truth_semantics() -> None:
    obs = NavObservation(position=(2.0, -3.0, 0.27), heading_deg=90.0)
    pose = observation_pose(obs, Frame.MAP)
    assert (pose.x, pose.y) == (2.0, -3.0)
    assert pose.yaw == pytest.approx(math.pi / 2)
    assert pose.covariance == ZERO_COVARIANCE
    assert pose.is_healthy
    # Both frames identical, exactly as TruthPoseProvider would return them.
    assert observation_pose(obs, Frame.ODOM).xy == pose.xy


def test_observation_pose_prefers_the_attached_provider() -> None:
    provider = TruthPoseProvider(9.0, 9.0, 1.0)
    obs = NavObservation(position=(0.0, 0.0, 0.0), extras={POSE_PROVIDER_KEY: provider})
    assert observation_pose(obs, Frame.MAP).xy == (9.0, 9.0)


def test_a_non_provider_in_extras_fails_closed() -> None:
    obs = NavObservation(extras={POSE_PROVIDER_KEY: object()})
    with pytest.raises(TypeError, match="PoseProvider"):
        observation_pose(obs, Frame.MAP)


def test_the_process_default_provider_is_fed_from_the_observation() -> None:
    """The injection seam has no other truth source, so it takes the caller's.

    That is what lets an unmodified eval runner — one that never heard of
    providers — still drive a drift tier: it keeps building the same
    observations, and the injected provider reads truth off them.
    """

    obs = NavObservation(position=(1.0, 1.0, 0.0), heading_deg=0.0)
    with use_pose_provider(TruthPoseProvider(5.0, 6.0, 0.0)):
        # A truth provider fed the observation's truth mirrors the observation.
        assert observation_pose(obs, Frame.MAP).xy == (1.0, 1.0)


def test_feeding_the_default_provider_is_idempotent_within_a_tick() -> None:
    """Several consumers read per tick; the second read must add no noise."""

    provider = load_pose_config(profile="stress").build()
    provider.reset()
    obs = NavObservation(position=(3.0, 0.0, 0.0), heading_deg=0.0)
    with use_pose_provider(provider):
        first = observation_pose(obs, Frame.ODOM)
        for _ in range(5):
            assert observation_pose(obs, Frame.ODOM).xy == first.xy


def test_the_default_provider_is_cleared_on_exit() -> None:
    drifting = load_pose_config(profile="stress").build()
    drifting.reset()
    final = NavObservation(position=(1.0, 1.0, 0.0))
    with use_pose_provider(drifting):
        # Several ticks of real motion, so drift has something to accumulate.
        for step in range(1, 11):
            observation_pose(
                NavObservation(position=(step * 0.1, step * 0.1, 0.0)), Frame.ODOM
            )
        assert observation_pose(final, Frame.ODOM).xy != (1.0, 1.0)
    # Back to the truth fallback, and no provider left installed.
    assert observation_pose(final, Frame.ODOM).xy == (1.0, 1.0)
    from parcel_robot.pose import default_pose_provider

    assert default_pose_provider() is None


def test_the_first_truth_sample_after_reset_is_a_baseline_not_a_delta() -> None:
    """A provider must not attribute drift to *arriving* at its start pose.

    Learned the hard way: reading the world once to learn the start pose
    perturbs the simulator's LiDAR-noise RNG and moved a frozen physics
    baseline by a step. Re-baselining on the first sample removes the need.
    """

    provider = load_pose_config(profile="stress").build()
    provider.reset()
    provider.update_truth(37.0, -19.0, 1.2, stamp_monotonic_s=0.0)
    pose = provider.get_pose(Frame.ODOM)
    assert (pose.x, pose.y, pose.yaw) == (37.0, -19.0, 1.2)
    assert provider.odom_error_m == 0.0
    assert provider.travelled_m == 0.0
    assert pose.is_exact


def test_attached_provider_outranks_the_process_default() -> None:
    obs = NavObservation(extras={POSE_PROVIDER_KEY: TruthPoseProvider(1.0, 1.0, 0.0)})
    with use_pose_provider(TruthPoseProvider(7.0, 7.0, 0.0)):
        assert observation_pose(obs, Frame.MAP).xy == (1.0, 1.0)


def test_a_provider_returning_the_wrong_frame_is_rejected() -> None:
    class Liar:
        def get_pose(self, frame: Frame) -> PoseEstimate:
            return PoseEstimate(0.0, 0.0, 0.0, Frame.ODOM)

    obs = NavObservation(extras={POSE_PROVIDER_KEY: Liar()})
    with pytest.raises(ValueError, match="frame"):
        observation_pose(obs, Frame.MAP)


def test_navigation_base_shim_matches_the_pose_module() -> None:
    obs = NavObservation(position=(1.5, 2.5, 0.27), heading_deg=45.0)
    for frame, alias in ((Frame.MAP, MAP_FRAME), (Frame.ODOM, ODOM_FRAME)):
        assert alias is frame
        assert pose_in(obs, alias).xy == observation_pose(obs, frame).xy


# --------------------------------------------------------------------------
# The preserved position[2]-as-yaw defect
# --------------------------------------------------------------------------


def test_legacy_position_yaw_reads_z_height_as_yaw_and_that_is_the_bug() -> None:
    """Pin the defect. ``position[2]`` is the standing height, not a heading.

    A standing Go2 has ``z = 0.27 m``; the legacy read turns that into
    0.27 rad = 15.5 degrees of imaginary heading while the true yaw is 0.
    This test exists so the defect cannot be "fixed" silently: changing the
    behavior must change this test, in its own paired-seed commit.
    """

    obs = NavObservation(position=(0.0, 0.0, 0.27), heading_deg=0.0)
    assert legacy_position_yaw(obs) == 0.27
    assert observation_pose(obs, Frame.MAP).yaw == 0.0  # the correct channel
    assert math.degrees(legacy_position_yaw(obs)) == pytest.approx(15.47, abs=0.01)


def test_legacy_yaw_reproduces_both_original_fallbacks() -> None:
    short = NavObservation(position=(1.0, 2.0), heading_deg=90.0)  # type: ignore[arg-type]
    assert legacy_position_yaw(short) == pytest.approx(math.pi / 2)
    assert legacy_position_yaw(short, zero_default=True) == 0.0


# --------------------------------------------------------------------------
# Health semantics
# --------------------------------------------------------------------------


def test_drifting_provider_reports_forced_health() -> None:
    provider = DriftingOdomProvider(forced_health=PoseHealth.LOST)
    assert provider.get_pose(Frame.MAP).health is PoseHealth.LOST
    assert provider.get_pose(Frame.ODOM).health is PoseHealth.LOST


def test_drifting_provider_goes_lost_after_the_configured_time() -> None:
    provider = DriftingOdomProvider(lost_after_s=2.0)
    provider.reset()
    provider.update_truth(0.0, 0.0, 0.0, stamp_monotonic_s=10.0)
    assert provider.get_pose(Frame.MAP).health is PoseHealth.HEALTHY
    provider.update_truth(0.5, 0.0, 0.0, stamp_monotonic_s=11.0)
    assert provider.get_pose(Frame.MAP).health is PoseHealth.HEALTHY
    provider.update_truth(1.0, 0.0, 0.0, stamp_monotonic_s=12.5)
    assert provider.get_pose(Frame.MAP).health is PoseHealth.LOST


def test_health_profiles_load_from_the_config() -> None:
    assert load_pose_config(profile="lost").forced_health is PoseHealth.LOST
    assert load_pose_config(profile="degraded").forced_health is PoseHealth.DEGRADED
    assert load_pose_config().provider == "truth"


def test_unknown_profile_and_unknown_keys_fail_closed(tmp_path) -> None:
    with pytest.raises(ValueError, match="not defined"):
        load_pose_config(profile="no_such_profile")
    bad = tmp_path / "pose.yaml"
    bad.write_text("provider: truth\nnonsense: 1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="unknown keys"):
        load_pose_config(bad)
    bad.write_text(
        "provider: truth\nprofiles:\n  x:\n    noise:\n      alpha9: 1\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="unknown odometry noise keys"):
        load_pose_config(bad, profile="x")


# --------------------------------------------------------------------------
# MAP / ODOM frame contract under drift
# --------------------------------------------------------------------------


def _drive(provider: DriftingOdomProvider, steps: int = 80, step: float = 0.1) -> float:
    provider.reset()
    t = 0.0
    x = 0.0
    for _ in range(steps):
        x += step
        t += 0.1
        provider.update_truth(x, 0.0, 0.0, stamp_monotonic_s=t)
    return x


def test_odom_drifts_while_map_stays_truth_by_default() -> None:
    provider = DriftingOdomProvider(load_pose_config(profile="calibrated_go2").noise)
    final_x = _drive(provider)
    assert provider.get_pose(Frame.MAP).xy == pytest.approx((final_x, 0.0), abs=1e-9)
    assert provider.odom_error_m > 0.0
    assert provider.get_pose(Frame.ODOM).xy != provider.get_pose(Frame.MAP).xy


def test_odom_covariance_grows_and_map_stays_exact() -> None:
    provider = DriftingOdomProvider(load_pose_config(profile="calibrated_go2").noise)
    _drive(provider)
    assert provider.get_pose(Frame.ODOM).position_sigma_m > 0.0
    assert provider.get_pose(Frame.MAP).is_exact


def test_reanchoring_map_error_resets_while_odom_error_only_grows() -> None:
    """REP-105 in one measurement: MAP is re-anchored, ODOM is not.

    A re-anchoring MAP tracks ODOM between corrections and snaps back to the
    global reference at each one, so its error against truth *sawtooths*. ODOM
    is never corrected, so its error against truth is (statistically) monotone.
    """

    provider = load_pose_config(profile="calibrated_go2_reanchoring").build()
    provider.reset()
    map_errors: list[float] = []
    t = 0.0
    x = 0.0
    for _ in range(400):
        x += 0.1
        t += 0.1
        provider.update_truth(x, 0.0, 0.0, stamp_monotonic_s=t)
        pose = provider.get_pose(Frame.MAP)
        map_errors.append(math.hypot(pose.x - x, pose.y))
    # Corrections happen: the MAP error returns to (near) zero repeatedly.
    resets = sum(1 for value in map_errors if value < 1e-9)
    assert resets >= 5, f"expected repeated re-anchors, saw {resets}"
    # ODOM keeps everything it accumulated; MAP does not.
    assert provider.odom_error_m > max(map_errors)


def test_truth_passthrough_map_never_moves_off_truth() -> None:
    provider = load_pose_config(profile="calibrated_go2").build()
    provider.reset()
    t = 0.0
    x = 0.0
    for _ in range(200):
        x += 0.1
        t += 0.1
        provider.update_truth(x, 0.0, 0.0, stamp_monotonic_s=t)
        pose = provider.get_pose(Frame.MAP)
        assert math.hypot(pose.x - x, pose.y) < 1e-9
    assert provider.odom_error_m > 0.0


def test_zero_noise_drifting_provider_reproduces_truth_exactly() -> None:
    """Degenerate correctness: no noise, no bias => odom IS truth."""

    provider = DriftingOdomProvider(
        OdometryNoiseParams(alpha1=0.0, alpha2=0.0, alpha3=0.0, alpha4=0.0)
    )
    provider.reset()
    t = 0.0
    for step in range(1, 60):
        t += 0.1
        provider.update_truth(step * 0.1, step * 0.05, step * 0.01, stamp_monotonic_s=t)
    pose = provider.get_pose(Frame.ODOM)
    assert pose.x == pytest.approx(5.9, abs=1e-9)
    assert pose.y == pytest.approx(2.95, abs=1e-9)
    assert pose.yaw == pytest.approx(0.59, abs=1e-9)
    assert provider.odom_error_m == pytest.approx(0.0, abs=1e-9)


# --------------------------------------------------------------------------
# B-5 chance-constrained membership
# --------------------------------------------------------------------------


@pytest.mark.parametrize("clearance", [0.0, 0.32])
def test_zero_covariance_reduces_exactly_to_boolean_membership(clearance: float) -> None:
    """The property that lets this be wired behind an equality: exact reduction."""

    for i in range(-2, 14):
        for j in range(-2, 12):
            point = (i * 0.35, j * 0.35)
            pose = PoseEstimate(point[0], point[1], 0.0, Frame.MAP)
            probability = p_inside_polygon(pose, SQUARE, clearance_m=clearance)
            boolean = point_in_polygon_with_clearance(point, SQUARE, clearance)
            assert probability in (0.0, 1.0)
            assert (probability == 1.0) is boolean


def test_pure_boolean_predicate_matches_the_production_one_on_a_dense_grid() -> None:
    """``pose.py`` keeps its own copy to stay low in the import graph — pin it."""

    for i in range(-3, 26):
        for j in range(-3, 20):
            point = (i * 0.19, j * 0.19)
            for clearance in (0.0, 0.15, 0.5):
                assert point_in_polygon_with_clearance_pure(
                    point, SQUARE, clearance
                ) is point_in_polygon_with_clearance(point, SQUARE, clearance)


def test_probability_falls_off_with_covariance_at_the_boundary() -> None:
    cov = (0.25, 0.0, 0.0, 0.0, 0.25, 0.0, 0.0, 0.0, 0.0)  # sigma = 0.5 m
    on_edge = PoseEstimate(0.0, 1.5, 0.0, Frame.MAP, covariance=cov)
    # Exactly on an edge with symmetric uncertainty: about half the mass is out.
    assert p_inside_polygon(on_edge, SQUARE) == pytest.approx(0.5, abs=0.02)
    deep = PoseEstimate(2.0, 1.5, 0.0, Frame.MAP, covariance=cov)
    assert p_inside_polygon(deep, SQUARE) > 0.99
    outside = PoseEstimate(-1.5, 1.5, 0.0, Frame.MAP, covariance=cov)
    assert p_inside_polygon(outside, SQUARE) < 0.01


def test_probability_is_monotone_decreasing_in_covariance_when_inside() -> None:
    previous = 1.1
    for sigma in (0.0001, 0.05, 0.1, 0.2, 0.4, 0.8):
        pose = PoseEstimate(
            0.3, 1.5, 0.0, Frame.MAP, covariance=(sigma**2, 0, 0, 0, sigma**2, 0, 0, 0, 0)
        )
        value = p_inside_polygon(pose, SQUARE)
        assert value <= previous
        previous = value


def test_probability_is_bounded_and_degenerate_polygons_are_refused() -> None:
    cov = (0.04, 0.0, 0.0, 0.0, 0.04, 0.0, 0.0, 0.0, 0.0)
    pose = PoseEstimate(2.0, 1.5, 0.0, Frame.MAP, covariance=cov)
    assert 0.0 <= p_inside_polygon(pose, SQUARE) <= 1.0
    assert p_inside_polygon(pose, ((0.0, 0.0), (1.0, 0.0))) == 0.0


def test_polygon_winding_does_not_change_the_answer() -> None:
    cov = (0.04, 0.0, 0.0, 0.0, 0.04, 0.0, 0.0, 0.0, 0.0)
    pose = PoseEstimate(1.0, 1.0, 0.0, Frame.MAP, covariance=cov)
    assert p_inside_polygon(pose, SQUARE) == pytest.approx(
        p_inside_polygon(pose, tuple(reversed(SQUARE)))
    )


def test_disc_membership_also_reduces_exactly() -> None:
    inside = PoseEstimate(0.5, 0.0, 0.0, Frame.MAP)
    assert p_inside_disc(inside, (0.0, 0.0), 1.0) == 1.0
    outside = PoseEstimate(1.5, 0.0, 0.0, Frame.MAP)
    assert p_inside_disc(outside, (0.0, 0.0), 1.0) == 0.0
    uncertain = PoseEstimate(
        1.0, 0.0, 0.0, Frame.MAP, covariance=(0.25, 0, 0, 0, 0.25, 0, 0, 0, 0)
    )
    assert p_inside_disc(uncertain, (0.0, 0.0), 1.0) == pytest.approx(0.5, abs=0.02)


def test_threshold_ships_at_the_planned_value() -> None:
    assert load_pose_config().inside_probability_threshold == 0.9
