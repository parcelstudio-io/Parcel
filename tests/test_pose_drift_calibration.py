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
