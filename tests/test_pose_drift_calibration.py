"""B-2 drift-injector calibration — measured against a published band, seeded.

The card asks for a unit-property calibration test: cumulative drift across N
seeds over a canned trajectory must land inside a documented band. Two things
are documented here rather than one, and the difference matters:

* the **yaw** band is the published DogLegs Go2 figure (0.2-0.5 deg/m), and the
  calibrated profile is tuned to sit mid-band at every trajectory length;
* the **translational** figure is *measured and pinned*, not claimed to match
  the published 0.5-1 %/distance band. Accumulated position error in any
  odometry model is dominated by heading error, so the two published numbers
  cannot both describe end-of-path drift on one 20 m run. See the derivation in
  ``configs/navigation/pose.yaml``. Pretending otherwise would be a fabricated
  calibration; measuring it and saying so is the honest version.
"""

from __future__ import annotations

import dataclasses
import math
import statistics

import pytest

from parcel_robot.pose import (
    DriftingOdomProvider,
    Frame,
    OdometryNoiseParams,
    load_pose_config,
)

SEEDS = 60
STEP_M = 0.1  # 0.1 s control tick at the ~1 m/s cruise the evals use

# Published DogLegs Go2 leg-odometry bands.
DOGLEGS_YAW_DEG_PER_M = (0.2, 0.5)
DOGLEGS_TRANSLATION_PCT = (0.5, 1.0)

# Measured end-of-path bands. These are pinned observations of THIS model on
# THIS trajectory, not specifications. A change outside them is a real change.
CALIBRATED_TRANSLATION_PCT_AT_20M = (1.2, 4.0)
STRESS_TRANSLATION_PCT_AT_20M = (12.0, 32.0)
STRESS_YAW_DEG_PER_M = (1.2, 3.2)


def canned_trajectory(total_m: float, step_m: float = STEP_M):
    """A square circuit: four straight legs with 90-degree turns between them.

    Turns are included on purpose — a straight line exercises only alpha2/alpha3
    and would leave the rotation coefficients unmeasured.
    """

    points: list[tuple[float, float, float]] = []
    x = y = yaw = 0.0
    leg = total_m / 4.0
    for _ in range(4):
        for _ in range(round(leg / step_m)):
            x += step_m * math.cos(yaw)
            y += step_m * math.sin(yaw)
            points.append((x, y, yaw))
        for _ in range(10):
            yaw += math.radians(9.0)
            points.append((x, y, yaw))
    return points


def drive(noise: OdometryNoiseParams, total_m: float) -> DriftingOdomProvider:
    provider = DriftingOdomProvider(noise)
    provider.reset()
    stamp = 0.0
    for x, y, yaw in canned_trajectory(total_m):
        stamp += 0.1
        provider.update_truth(x, y, yaw, stamp_monotonic_s=stamp)
    return provider


def sweep(profile: str, total_m: float, seeds: int = SEEDS) -> tuple[float, float]:
    """Mean (translation %% of distance, yaw deg/m) across ``seeds`` runs."""

    base = load_pose_config(profile=profile).noise
    translations: list[float] = []
    yaws: list[float] = []
    for seed in range(seeds):
        noise = OdometryNoiseParams(
            alpha1=base.alpha1,
            alpha2=base.alpha2,
            alpha3=base.alpha3,
            alpha4=base.alpha4,
            systematic_translation_scale_sigma=base.systematic_translation_scale_sigma,
            systematic_yaw_bias_sigma_rad_per_m=base.systematic_yaw_bias_sigma_rad_per_m,
            seed=seed,
        )
        provider = drive(noise, total_m)
        translations.append(100.0 * provider.odom_error_m / total_m)
        yaws.append(math.degrees(provider.odom_yaw_error_rad) / total_m)
    return statistics.mean(translations), statistics.mean(yaws)


# --------------------------------------------------------------------------
# The published band the model IS calibrated to
# --------------------------------------------------------------------------


@pytest.mark.parametrize("total_m", [10.0, 20.0, 40.0])
def test_calibrated_yaw_drift_is_inside_the_published_doglegs_band(total_m: float) -> None:
    _, yaw_deg_per_m = sweep("calibrated_go2", total_m)
    low, high = DOGLEGS_YAW_DEG_PER_M
    assert low <= yaw_deg_per_m <= high, (
        f"calibrated yaw drift {yaw_deg_per_m:.3f} deg/m at D={total_m} m left the "
        f"published DogLegs band {DOGLEGS_YAW_DEG_PER_M}"
    )


def test_calibrated_yaw_drift_is_length_independent() -> None:
    """A deg/m figure is only meaningful if it does not depend on D.

    This is what the per-run systematic bias buys: a pure alpha random walk
    grows as sqrt(D), so its deg/m figure halves every time the path
    quadruples.
    """

    values = [sweep("calibrated_go2", total)[1] for total in (10.0, 20.0, 40.0)]
    assert max(values) / min(values) < 1.6, f"deg/m varies too much with length: {values}"


def test_the_translational_scale_error_matches_the_published_band() -> None:
    """The part of the translational spec this model CAN honor directly.

    Measured on a straight run with rotation noise disabled, so the figure is
    the scale error alone and not the heading-induced cross-track error.
    """

    base = load_pose_config(profile="calibrated_go2").noise
    errors: list[float] = []
    for seed in range(SEEDS):
        noise = OdometryNoiseParams(
            alpha1=0.0,
            alpha2=0.0,
            alpha3=0.0,
            alpha4=0.0,
            systematic_translation_scale_sigma=base.systematic_translation_scale_sigma,
            seed=seed,
        )
        provider = DriftingOdomProvider(noise)
        provider.reset()
        stamp = 0.0
        x = 0.0
        for _ in range(200):
            x += STEP_M
            stamp += 0.1
            provider.update_truth(x, 0.0, 0.0, stamp_monotonic_s=stamp)
        errors.append(100.0 * provider.odom_error_m / x)
    mean = statistics.mean(errors)
    low, high = DOGLEGS_TRANSLATION_PCT
    assert low <= mean <= high, (
        f"scale error {mean:.3f} %% of distance left the published DogLegs band "
        f"{DOGLEGS_TRANSLATION_PCT}"
    )


# --------------------------------------------------------------------------
# The figures that are MEASURED, not specified
# --------------------------------------------------------------------------


def test_calibrated_accumulated_translation_drift_is_pinned_as_measured() -> None:
    translation, _ = sweep("calibrated_go2", 20.0)
    low, high = CALIBRATED_TRANSLATION_PCT_AT_20M
    assert low <= translation <= high, (
        f"measured accumulated drift {translation:.2f} %% / 20 m left its pinned band "
        f"{CALIBRATED_TRANSLATION_PCT_AT_20M}"
    )
    # And it is honestly outside the published translational band, because
    # heading error dominates. If this ever stops being true, the note in
    # configs/navigation/pose.yaml is wrong and must be rewritten.
    assert translation > DOGLEGS_TRANSLATION_PCT[1]


def test_stress_profile_is_pinned_and_strictly_worse_than_calibrated() -> None:
    stress_t, stress_y = sweep("stress", 20.0)
    calib_t, calib_y = sweep("calibrated_go2", 20.0)
    assert STRESS_TRANSLATION_PCT_AT_20M[0] <= stress_t <= STRESS_TRANSLATION_PCT_AT_20M[1]
    assert STRESS_YAW_DEG_PER_M[0] <= stress_y <= STRESS_YAW_DEG_PER_M[1]
    assert stress_t > calib_t and stress_y > calib_y
    # The stress tier must be recognisably outside the published band, or it
    # is not a stress tier.
    assert stress_y > DOGLEGS_YAW_DEG_PER_M[1]


# --------------------------------------------------------------------------
# Determinism and monotonicity
# --------------------------------------------------------------------------


def test_the_same_seed_reproduces_the_same_trajectory_exactly() -> None:
    noise = load_pose_config(profile="calibrated_go2").noise
    first = drive(noise, 20.0).get_pose(Frame.ODOM)
    second = drive(noise, 20.0).get_pose(Frame.ODOM)
    assert (first.x, first.y, first.yaw) == (second.x, second.y, second.yaw)


def test_different_seeds_produce_different_trajectories() -> None:
    base = load_pose_config(profile="calibrated_go2").noise
    poses = set()
    for seed in range(5):
        noise = OdometryNoiseParams(
            alpha1=base.alpha1,
            alpha2=base.alpha2,
            alpha3=base.alpha3,
            alpha4=base.alpha4,
            systematic_translation_scale_sigma=base.systematic_translation_scale_sigma,
            systematic_yaw_bias_sigma_rad_per_m=base.systematic_yaw_bias_sigma_rad_per_m,
            seed=seed,
        )
        pose = drive(noise, 20.0).get_pose(Frame.ODOM)
        poses.add((round(pose.x, 9), round(pose.y, 9)))
    assert len(poses) == 5


def test_reset_clears_accumulated_drift_and_covariance() -> None:
    provider = drive(load_pose_config(profile="calibrated_go2").noise, 20.0)
    assert provider.odom_error_m > 0.0
    provider.reset()
    assert provider.odom_error_m == 0.0
    assert provider.travelled_m == 0.0
    assert provider.get_pose(Frame.ODOM).is_exact


def test_covariance_grows_monotonically_with_distance() -> None:
    noise = load_pose_config(profile="calibrated_go2").noise
    sigmas = [
        drive(noise, total).get_pose(Frame.ODOM).position_sigma_m for total in (5.0, 10.0, 20.0)
    ]
    assert sigmas == sorted(sigmas)
    assert sigmas[0] > 0.0


def test_negative_alphas_are_rejected() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        OdometryNoiseParams(alpha3=-0.1)


# --------------------------------------------------------------------------
# DR-1: the degraded-pose LADDER (scrum/20260811/task_2)
#
# Everything above this line is byte-untouched. The two new rungs are measured
# by the SAME 60-seed harness, which is the point: "within envelope" means the
# figure this file already produces, not a new definition of the word.
#
# Each rung is a stated multiple k of the calibrated sigma, so its target band
# is `k x the published DogLegs band` and the single published anchor governs
# the whole ladder. See the derivation block in configs/navigation/pose.yaml.
# --------------------------------------------------------------------------

LADDER_MULTIPLE = {"go2_aggressive": 2.0, "go2_degraded": 4.0}

# Measured accumulated end-of-path drift at D = 20 m, pinned exactly as
# CALIBRATED_TRANSLATION_PCT_AT_20M is: an observation of THIS model on THIS
# trajectory (4.59 % and 9.22 %), never a claim to match the published band.
AGGRESSIVE_TRANSLATION_PCT_AT_20M = (2.5, 7.5)
DEGRADED_TRANSLATION_PCT_AT_20M = (5.0, 14.0)

# Mean slip events over a 20 m run, measured at 1.13 — the yaml derives the
# rate as "one expected event per 20 m", so this pin is that intent checked.
DEGRADED_SLIP_EVENTS_AT_20M = (0.5, 2.0)


def sweep_full(profile: str, total_m: float, seeds: int = SEEDS):
    """Like :func:`sweep`, but carries EVERY noise field, plus slip counts.

    ``sweep`` enumerates the six fields it copies, so it silently drops the
    slip knobs and would measure ``go2_degraded`` as if slip were off. Rather
    than edit a helper the twelve pinned tests above depend on, this variant
    uses ``dataclasses.replace`` — which cannot drop a field that is added
    later — and reports the slip-event count the pinned rate implies.
    """

    base = load_pose_config(profile=profile).noise
    translations: list[float] = []
    yaws: list[float] = []
    slips: list[int] = []
    for seed in range(seeds):
        provider = drive(dataclasses.replace(base, seed=seed), total_m)
        translations.append(100.0 * provider.odom_error_m / total_m)
        yaws.append(math.degrees(provider.odom_yaw_error_rad) / total_m)
        slips.append(provider.slip_events)
    return (
        statistics.mean(translations),
        statistics.mean(yaws),
        statistics.mean(slips),
    )


@pytest.mark.parametrize("profile", sorted(LADDER_MULTIPLE))
@pytest.mark.parametrize("total_m", [10.0, 20.0, 40.0])
def test_new_rungs_land_inside_their_scaled_published_yaw_band(
    profile: str, total_m: float
) -> None:
    """The gate the card calls 'within envelope', measured over 60 seeds."""

    k = LADDER_MULTIPLE[profile]
    _, yaw_deg_per_m, _ = sweep_full(profile, total_m)
    low, high = k * DOGLEGS_YAW_DEG_PER_M[0], k * DOGLEGS_YAW_DEG_PER_M[1]
    assert low <= yaw_deg_per_m <= high, (
        f"{profile} yaw drift {yaw_deg_per_m:.3f} deg/m at D={total_m} m left its "
        f"target band {k:g}x DogLegs = ({low:.2f}, {high:.2f})"
    )


@pytest.mark.parametrize("profile", sorted(LADDER_MULTIPLE))
def test_new_rungs_scale_error_lands_inside_the_scaled_published_band(profile: str) -> None:
    """The translational half, isolated the same way the calibrated test does.

    Straight run, rotation noise off, so the figure is the scale error alone
    rather than the heading-induced cross-track error that dominates the
    accumulated number.
    """

    k = LADDER_MULTIPLE[profile]
    base = load_pose_config(profile=profile).noise
    errors: list[float] = []
    for seed in range(SEEDS):
        noise = OdometryNoiseParams(
            alpha1=0.0,
            alpha2=0.0,
            alpha3=0.0,
            alpha4=0.0,
            systematic_translation_scale_sigma=base.systematic_translation_scale_sigma,
            seed=seed,
        )
        provider = DriftingOdomProvider(noise)
        provider.reset()
        stamp = 0.0
        x = 0.0
        for _ in range(200):
            x += STEP_M
            stamp += 0.1
            provider.update_truth(x, 0.0, 0.0, stamp_monotonic_s=stamp)
        errors.append(100.0 * provider.odom_error_m / x)
    mean = statistics.mean(errors)
    low, high = k * DOGLEGS_TRANSLATION_PCT[0], k * DOGLEGS_TRANSLATION_PCT[1]
    assert low <= mean <= high, (
        f"{profile} scale error {mean:.3f} %% left its target band "
        f"{k:g}x DogLegs = ({low:.2f}, {high:.2f})"
    )


@pytest.mark.parametrize("profile", sorted(LADDER_MULTIPLE))
def test_new_rungs_yaw_drift_is_length_independent(profile: str) -> None:
    """A deg/m band is only a band if it survives changing D — same as calibrated."""

    values = [sweep_full(profile, total)[1] for total in (10.0, 20.0, 40.0)]
    assert max(values) / min(values) < 1.6, f"{profile} deg/m varies with length: {values}"


def test_new_rungs_accumulated_translation_drift_is_pinned_as_measured() -> None:
    aggressive, _, _ = sweep_full("go2_aggressive", 20.0)
    degraded, _, _ = sweep_full("go2_degraded", 20.0)
    assert AGGRESSIVE_TRANSLATION_PCT_AT_20M[0] <= aggressive <= AGGRESSIVE_TRANSLATION_PCT_AT_20M[1]
    assert DEGRADED_TRANSLATION_PCT_AT_20M[0] <= degraded <= DEGRADED_TRANSLATION_PCT_AT_20M[1]


def test_the_ladder_is_strictly_monotone_and_interpolates_the_existing_anchors() -> None:
    """calibrated < aggressive < degraded < stress, in BOTH metrics.

    This is what makes the two new rungs a ladder rather than two more points:
    they sit strictly between the two tiers this repo already owned, so the
    published anchor at the bottom and the pinned stress tier at the top bound
    them from both sides.
    """

    calibrated_t, calibrated_y = sweep("calibrated_go2", 20.0)
    aggressive_t, aggressive_y, _ = sweep_full("go2_aggressive", 20.0)
    degraded_t, degraded_y, _ = sweep_full("go2_degraded", 20.0)
    stress_t, stress_y = sweep("stress", 20.0)

    assert calibrated_t < aggressive_t < degraded_t < stress_t, (
        f"translation ladder not monotone: {calibrated_t:.2f} {aggressive_t:.2f} "
        f"{degraded_t:.2f} {stress_t:.2f}"
    )
    assert calibrated_y < aggressive_y < degraded_y < stress_y, (
        f"yaw ladder not monotone: {calibrated_y:.3f} {aggressive_y:.3f} "
        f"{degraded_y:.3f} {stress_y:.3f}"
    )
    # And the bottom rung is still the only one inside the published band —
    # a degraded tier that a reader could mistake for nominal is not a tier.
    assert calibrated_y <= DOGLEGS_YAW_DEG_PER_M[1] < aggressive_y


def test_the_degraded_rung_actually_fires_slip_events() -> None:
    """Non-vacuity: the slip knob is not decoration on the profile that owns it."""

    _, _, aggressive_slips = sweep_full("go2_aggressive", 20.0)
    _, _, degraded_slips = sweep_full("go2_degraded", 20.0)
    assert aggressive_slips == 0.0, "only go2_degraded configures slip"
    low, high = DEGRADED_SLIP_EVENTS_AT_20M
    assert low <= degraded_slips <= high, (
        f"go2_degraded fired {degraded_slips:.2f} slip events per 20 m, outside the "
        f"pinned band {DEGRADED_SLIP_EVENTS_AT_20M} implied by rate=0.05/m"
    )
