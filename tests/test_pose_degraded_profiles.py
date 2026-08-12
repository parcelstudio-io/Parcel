"""DR-1 — the additive degraded-pose extensions, and proof they cost nothing.

``scrum/20260811/task_2/SLAM_M_PLAN.md`` card DR-1 is an EXTEND card: scheduled
LOST windows that recover, foot-slip jumps, and two new profile rungs get added
to machinery that already shipped, and **nothing that already shipped may
move**.  That second half is the hard part and most of this file, because
``DriftingOdomProvider`` draws every sample from one shared RNG stream: a single
stray draw on a disabled code path silently re-rolls every calibrated figure in
``tests/test_pose_drift_calibration.py`` while every one of those tests keeps
passing on its band.

So the byte-neutrality proofs here are pinned at three depths, captured from the
tree BEFORE the extension landed:

1. the raw yaml mapping of each pre-existing profile (canonical digest),
2. its parsed :class:`PoseConfig` (every field),
3. the ODOM pose it drives to over the canned trajectory (the RNG fingerprint —
   the only one of the three that can catch a stray draw).
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import math
from pathlib import Path

import pytest
import yaml
from test_pose_drift_calibration import drive  # the harness DR-1 reuses, not a copy

from parcel_robot.pose import (
    DriftingOdomProvider,
    Frame,
    OdometryNoiseParams,
    PoseHealth,
    load_pose_config,
    provider_from_config,
)

POSE_YAML = Path(__file__).resolve().parents[1] / "configs/navigation/pose.yaml"

#: Profiles that existed before DR-1.  None of their numbers may move.
PRE_EXISTING = ("stress", "calibrated_go2", "calibrated_go2_reanchoring", "lost", "degraded")

#: Profiles DR-1 adds.  The by-name contract Wave-2's DR-2 consumes.
NEW_PROFILES = (
    "go2_aggressive",
    "go2_degraded",
    "calibrated_go2_lost",
    "go2_aggressive_lost",
    "go2_degraded_lost",
)

#: sha256(json(profile mapping, sorted))[:16], captured pre-extension.
BASELINE_RAW_DIGEST = {
    "calibrated_go2": "b54044cc36fb85ba",
    "calibrated_go2_reanchoring": "9ab13b1209b45f81",
    "degraded": "0bde3a76b86ce0eb",
    "lost": "df6bbaceea4b7e02",
    "stress": "a9137a7430ccceec",
}

#: (x, y, yaw) of ODOM after the 20 m canned circuit, captured pre-extension.
#: Exact equality, not a band: this is the RNG stream fingerprint.
BASELINE_ODOM_ENDPOINT = {
    "calibrated_go2": (0.032388019441, 0.039168085, -0.016629364578),
    "calibrated_go2_reanchoring": (0.032388019441, 0.039168085, -0.016629364578),
    "degraded": (-0.072875542135, 0.148539576874, -0.060044507358),
    "lost": (-0.072875542135, 0.148539576874, -0.060044507358),
    "stress": (-0.643125285871, 2.118524768364, -0.880073219765),
}

#: Every field of every pre-existing parsed config, captured pre-extension.
_CAL_NOISE = (0.002, 0.001, 0.003, 0.001, 0.0075, 0.0061, 20260807)
_BARE_NOISE = (0.002, 0.001, 0.003, 0.001, 0.0, 0.0, 20260807)
BASELINE_PARSED = {
    "stress": ((0.2, 0.2, 0.2, 0.2, 0.0, 0.0, 20260807), False, 5.0, None, None, 0.0),
    "calibrated_go2": (_CAL_NOISE, False, 5.0, None, None, 0.0),
    "calibrated_go2_reanchoring": (_CAL_NOISE, True, 5.0, None, None, 0.0),
    "lost": (_BARE_NOISE, False, 5.0, PoseHealth.LOST, None, 0.0),
    "degraded": (_BARE_NOISE, False, 5.0, PoseHealth.DEGRADED, None, 0.0),
}


def noise_tuple(noise: OdometryNoiseParams):
    return (
        noise.alpha1,
        noise.alpha2,
        noise.alpha3,
        noise.alpha4,
        noise.systematic_translation_scale_sigma,
        noise.systematic_yaw_bias_sigma_rad_per_m,
        noise.seed,
    )


def drive_stamped(provider: DriftingOdomProvider, ticks: int, *, step_m: float = 0.1):
    """Walk a straight line at 10 Hz from stamp 0.0, yielding (elapsed_s, pose)."""

    provider.reset()
    x = 0.0
    out = []
    for tick in range(ticks):
        stamp = tick * 0.1
        provider.update_truth(x, 0.0, 0.0, stamp_monotonic_s=stamp)
        out.append((stamp, provider.get_pose(Frame.ODOM)))
        x += step_m
    return out


# --------------------------------------------------------------------------
# 1. Nothing that already shipped moved
# --------------------------------------------------------------------------


@pytest.mark.parametrize("profile", PRE_EXISTING)
def test_pre_existing_profile_yaml_is_byte_untouched(profile: str) -> None:
    """The yaml mapping itself — comments and new siblings may change, this may not."""

    raw = yaml.safe_load(POSE_YAML.read_text(encoding="utf-8"))["profiles"][profile]
    blob = json.dumps(raw, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(blob.encode()).hexdigest()[:16]
    assert digest == BASELINE_RAW_DIGEST[profile], (
        f"pre-existing profile {profile!r} changed: {digest} != "
        f"{BASELINE_RAW_DIGEST[profile]}. DR-1 is additive; this file's existing "
        f"profiles are frozen."
    )


@pytest.mark.parametrize("profile", PRE_EXISTING)
def test_pre_existing_parsed_config_is_unchanged(profile: str) -> None:
    """Every parsed field, including the ones DR-1 added (which must default off)."""

    cfg = load_pose_config(profile=profile)
    noise, correction, interval, forced, lost_after, floor = BASELINE_PARSED[profile]
    assert cfg.provider == "drifting_odom"
    assert noise_tuple(cfg.noise) == noise
    assert cfg.map_correction_enabled is correction
    assert cfg.map_correction_interval_s == interval
    assert cfg.forced_health is forced
    assert cfg.lost_after_s is lost_after
    assert cfg.map_covariance_floor_m2 == floor
    assert cfg.inside_probability_threshold == 0.9
    # The new fields must be inert on every pre-existing profile.
    assert cfg.lost_windows == ()
    assert cfg.noise.slip_jump_magnitude_m == 0.0
    assert cfg.noise.slip_jump_rate_per_m == 0.0
    assert cfg.noise.slip_enabled is False


@pytest.mark.parametrize("profile", PRE_EXISTING)
def test_pre_existing_profiles_drive_to_the_same_odom_pose(profile: str) -> None:
    """The RNG fingerprint — the pin that catches a stray draw on a disabled path.

    Exact float equality is deliberate. A slip implementation that consumed a
    random number even when slip is off would shift this by a full sample and
    still leave every calibration band satisfied.
    """

    pose = drive(load_pose_config(profile=profile).noise, 20.0).get_pose(Frame.ODOM)
    expected = BASELINE_ODOM_ENDPOINT[profile]
    assert (round(pose.x, 12), round(pose.y, 12), round(pose.yaw, 12)) == expected


def test_the_truth_default_is_still_the_shipping_provider() -> None:
    cfg = load_pose_config()
    assert cfg.provider == "truth"
    assert cfg.lost_windows == ()
    assert provider_from_config().get_pose(Frame.ODOM).is_exact


# --------------------------------------------------------------------------
# 2. Slip is off by default, and the guard needs BOTH knobs
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "slip",
    [
        {"slip_jump_magnitude_m": 0.0, "slip_jump_rate_per_m": 0.0},
        {"slip_jump_magnitude_m": 0.25, "slip_jump_rate_per_m": 0.0},
        {"slip_jump_magnitude_m": 0.0, "slip_jump_rate_per_m": 0.5},
    ],
)
def test_disabled_slip_consumes_no_randomness(slip: dict[str, float]) -> None:
    """A half-configured slip is OFF, and off means bit-identical, not merely close.

    Either knob at zero makes the process incapable of producing a displacement
    (zero magnitude) or of ever firing (zero rate). Both must therefore skip the
    draw entirely, or a profile that sets one knob while tuning the other would
    silently re-roll its own calibration.
    """

    base = load_pose_config(profile="calibrated_go2").noise
    plain = drive(base, 20.0).get_pose(Frame.ODOM)
    with_slip = drive(dataclasses.replace(base, **slip), 20.0).get_pose(Frame.ODOM)
    assert (plain.x, plain.y, plain.yaw) == (with_slip.x, with_slip.y, with_slip.yaw)
    assert plain.covariance == with_slip.covariance


def test_enabled_slip_moves_the_trajectory_so_the_neutrality_pins_can_fail() -> None:
    """The seeded-failure proof for every 'byte-identical' assertion above.

    If enabling slip did NOT move these numbers, the pins would be vacuous and
    would keep passing through a genuinely broken guard.
    """

    base = load_pose_config(profile="calibrated_go2").noise
    plain = drive(base, 20.0)
    slipped = drive(
        dataclasses.replace(base, slip_jump_magnitude_m=0.15, slip_jump_rate_per_m=0.05),
        20.0,
    )
    assert slipped.slip_events > 0, "the mechanism did not fire; this proves nothing"
    assert plain.slip_events == 0
    assert slipped.get_pose(Frame.ODOM).xy != plain.get_pose(Frame.ODOM).xy
    # And the pinned endpoint is what would break — stated explicitly.
    moved = slipped.get_pose(Frame.ODOM)
    assert (round(moved.x, 12), round(moved.y, 12)) != BASELINE_ODOM_ENDPOINT[
        "calibrated_go2"
    ][:2]


def test_slip_widens_the_reported_covariance() -> None:
    """Uncertainty must grow with the process, not only the realized jump.

    ``travelled_m`` rather than the nominal 20 m: the first sample after a
    reset re-baselines instead of integrating (a provider cannot know where it
    started until its first sample), so the integrated distance is one step
    short. Asserting against the nominal figure would fail by exactly 0.5 %.
    """

    base = load_pose_config(profile="calibrated_go2").noise
    plain = drive(base, 20.0)
    slipped = drive(
        dataclasses.replace(base, slip_jump_magnitude_m=0.15, slip_jump_rate_per_m=0.05),
        20.0,
    )
    plain_cov = plain.get_pose(Frame.ODOM).covariance[0]
    slipped_cov = slipped.get_pose(Frame.ODOM).covariance[0]
    assert slipped_cov > plain_cov
    # Expected contribution over D metres is rate*D*m^2/2, per axis.
    expected = 0.05 * slipped.travelled_m * 0.15**2 / 2.0
    assert slipped_cov == pytest.approx(plain_cov + expected, rel=1e-9)


def test_negative_slip_parameters_are_rejected() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        OdometryNoiseParams(slip_jump_magnitude_m=-0.1)
    with pytest.raises(ValueError, match="non-negative"):
        OdometryNoiseParams(slip_jump_rate_per_m=-0.1)


# --------------------------------------------------------------------------
# 3. Scheduled LOST windows RECOVER, and compose with drift
# --------------------------------------------------------------------------


def test_a_scheduled_window_drops_out_and_comes_back() -> None:
    """The whole point: ``lost_after_s`` cannot do this, and recovery is the gate."""

    provider = DriftingOdomProvider(
        load_pose_config(profile="calibrated_go2").noise,
        lost_windows=[(1.0, 0.5)],
    )
    healths = {
        round(elapsed, 3): pose.health for elapsed, pose in drive_stamped(provider, 25)
    }
    assert healths[0.0] is PoseHealth.HEALTHY
    assert healths[0.9] is PoseHealth.HEALTHY
    # Half-open [start, start+duration): the window is exactly 0.5 s long.
    assert healths[1.0] is PoseHealth.LOST
    assert healths[1.4] is PoseHealth.LOST
    assert healths[1.5] is PoseHealth.HEALTHY
    assert healths[2.0] is PoseHealth.HEALTHY
    assert PoseHealth.LOST in healths.values()


def test_multiple_windows_compose_and_each_one_recovers() -> None:
    provider = DriftingOdomProvider(
        load_pose_config(profile="calibrated_go2").noise,
        lost_windows=[(1.5, 0.4), (0.5, 0.3)],  # deliberately unsorted
    )
    healths = {
        round(elapsed, 3): pose.health for elapsed, pose in drive_stamped(provider, 25)
    }
    assert healths[0.4] is PoseHealth.HEALTHY
    assert healths[0.5] is PoseHealth.LOST
    assert healths[0.8] is PoseHealth.HEALTHY
    assert healths[1.5] is PoseHealth.LOST
    assert healths[1.9] is PoseHealth.HEALTHY
    assert provider.lost_windows == ((0.5, 0.3), (1.5, 0.4))


def test_windows_do_not_corrupt_drift_state() -> None:
    """Health is a channel, not a mutation: the ODOM track is bit-identical.

    A localizer announcing it is lost does not stop the legs, so drift must
    keep integrating through the window — and must integrate *the same way* it
    would have without one.
    """

    noise = load_pose_config(profile="calibrated_go2").noise
    plain = DriftingOdomProvider(noise)
    windowed = DriftingOdomProvider(noise, lost_windows=[(0.4, 0.6)])
    plain_track = [(p.x, p.y, p.yaw) for _, p in drive_stamped(plain, 40)]
    windowed_track = [(p.x, p.y, p.yaw) for _, p in drive_stamped(windowed, 40)]
    assert plain_track == windowed_track
    assert plain.travelled_m == windowed.travelled_m
    assert plain.odom_error_m == windowed.odom_error_m
    assert plain.get_pose(Frame.ODOM).covariance == windowed.get_pose(Frame.ODOM).covariance
    # ...and the windowed run really did report LOST, or this proves nothing.
    assert any(p.health is PoseHealth.LOST for _, p in drive_stamped(windowed, 40))


def test_a_window_survives_reset_and_re_arms() -> None:
    """Fresh episode, fresh clock — DR-2 builds one provider per episode."""

    provider = DriftingOdomProvider(
        load_pose_config(profile="calibrated_go2").noise,
        lost_windows=[(0.5, 0.3)],
    )
    first = {round(e, 3): p.health for e, p in drive_stamped(provider, 15)}
    second = {round(e, 3): p.health for e, p in drive_stamped(provider, 15)}
    assert first == second
    assert first[0.5] is PoseHealth.LOST


def test_windows_apply_on_both_frames() -> None:
    provider = DriftingOdomProvider(
        load_pose_config(profile="calibrated_go2").noise,
        lost_windows=[(0.5, 0.3)],
    )
    provider.reset()
    provider.update_truth(0.0, 0.0, 0.0, stamp_monotonic_s=0.0)
    provider.update_truth(0.6, 0.0, 0.0, stamp_monotonic_s=0.6)
    assert provider.get_pose(Frame.ODOM).health is PoseHealth.LOST
    assert provider.get_pose(Frame.MAP).health is PoseHealth.LOST


def test_health_precedence_forced_beats_trapdoor_beats_window() -> None:
    """A recovering window must never resurrect a permanently-lost provider."""

    noise = load_pose_config(profile="calibrated_go2").noise
    # The one-way trapdoor wins outside the window: still LOST after recovery.
    trapdoor = DriftingOdomProvider(noise, lost_after_s=0.5, lost_windows=[(0.1, 0.2)])
    healths = {round(e, 3): p.health for e, p in drive_stamped(trapdoor, 15)}
    assert healths[0.1] is PoseHealth.LOST  # window
    assert healths[0.3] is PoseHealth.HEALTHY  # recovered, trapdoor not yet armed
    assert healths[0.5] is PoseHealth.LOST  # trapdoor
    assert healths[1.0] is PoseHealth.LOST  # and it never comes back
    # forced_health outranks everything, window included.
    forced = DriftingOdomProvider(
        noise, forced_health=PoseHealth.DEGRADED, lost_windows=[(0.1, 0.2)]
    )
    assert all(p.health is PoseHealth.DEGRADED for _, p in drive_stamped(forced, 10))


@pytest.mark.parametrize(
    "windows",
    [
        [(-1.0, 2.0)],  # negative start
        [(1.0, 0.0)],  # zero duration
        [(1.0, -2.0)],  # negative duration
        [(1.0,)],  # wrong arity
        [(1.0, 2.0, 3.0)],  # wrong arity
        ["nonsense"],  # not a pair
        [(float("inf"), 1.0)],  # non-finite
    ],
)
def test_malformed_windows_fail_closed(windows) -> None:
    with pytest.raises((ValueError, TypeError)):
        DriftingOdomProvider(OdometryNoiseParams(), lost_windows=windows)


# --------------------------------------------------------------------------
# 4. The new profiles, and the by-name contract DR-2 consumes
# --------------------------------------------------------------------------


@pytest.mark.parametrize("profile", NEW_PROFILES)
def test_every_new_profile_constructs_a_ready_provider_by_name(profile: str) -> None:
    """The entire DR-2 integration surface: name in, working provider out."""

    provider = provider_from_config(profile=profile)
    assert isinstance(provider, DriftingOdomProvider)
    provider.reset()
    provider.update_truth(0.0, 0.0, 0.0, stamp_monotonic_s=0.0)
    provider.update_truth(1.0, 0.0, 0.0, stamp_monotonic_s=1.0)
    pose = provider.get_pose(Frame.ODOM)
    assert pose.frame is Frame.ODOM
    assert math.isfinite(pose.x) and math.isfinite(pose.y)
    assert provider.travelled_m == pytest.approx(1.0)


@pytest.mark.parametrize(
    ("variant", "base"),
    [
        ("calibrated_go2_lost", "calibrated_go2"),
        ("go2_aggressive_lost", "go2_aggressive"),
        ("go2_degraded_lost", "go2_degraded"),
    ],
)
def test_lost_variants_are_their_base_profile_plus_a_window(variant: str, base: str) -> None:
    """The duplicated yaml noise blocks cannot silently drift apart."""

    variant_cfg = load_pose_config(profile=variant)
    base_cfg = load_pose_config(profile=base)
    assert variant_cfg.noise == base_cfg.noise
    assert base_cfg.lost_windows == ()
    assert variant_cfg.lost_windows == ((4.0, 3.0),)
    assert variant_cfg.forced_health is None
    assert variant_cfg.lost_after_s is None


def test_the_derived_window_recovers_inside_a_short_travel_episode() -> None:
    """Pins the yaml's window derivation: drop AND recovery inside ~12 s."""

    provider = provider_from_config(profile="calibrated_go2_lost")
    healths = {round(e, 3): p.health for e, p in drive_stamped(provider, 120)}
    assert healths[3.9] is PoseHealth.HEALTHY  # healthy lead-in
    assert healths[4.0] is PoseHealth.LOST
    assert healths[6.9] is PoseHealth.LOST
    assert healths[7.0] is PoseHealth.HEALTHY  # recovered, with time to spare
    assert healths[11.9] is PoseHealth.HEALTHY
    lost_ticks = sum(1 for h in healths.values() if h is PoseHealth.LOST)
    assert lost_ticks == 30, f"expected a 3.0 s hold at 10 Hz, got {lost_ticks} ticks"


def test_only_the_degraded_rungs_enable_slip() -> None:
    for profile in ("go2_degraded", "go2_degraded_lost"):
        assert load_pose_config(profile=profile).noise.slip_enabled is True
    for profile in ("calibrated_go2", "go2_aggressive", "go2_aggressive_lost", "stress"):
        assert load_pose_config(profile=profile).noise.slip_enabled is False


def test_the_ladder_multiples_are_exactly_what_the_yaml_derivation_claims() -> None:
    """alphas x k^2, systematic sigmas x k — the k^2 is the easy thing to get wrong."""

    cal = load_pose_config(profile="calibrated_go2").noise
    for profile, k in (("go2_aggressive", 2.0), ("go2_degraded", 4.0)):
        rung = load_pose_config(profile=profile).noise
        for alpha in ("alpha1", "alpha2", "alpha3", "alpha4"):
            assert getattr(rung, alpha) == pytest.approx(getattr(cal, alpha) * k * k), (
                f"{profile}.{alpha} is not {k:g}^2 x calibrated — alphas are VARIANCE "
                f"coefficients (pose.py), so sigma scales as sqrt(alpha)"
            )
        assert rung.systematic_translation_scale_sigma == pytest.approx(
            cal.systematic_translation_scale_sigma * k
        )
        assert rung.systematic_yaw_bias_sigma_rad_per_m == pytest.approx(
            cal.systematic_yaw_bias_sigma_rad_per_m * k
        )


# --------------------------------------------------------------------------
# 5. The new schema keys still fail closed
# --------------------------------------------------------------------------


def _write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "pose.yaml"
    path.write_text(body, encoding="utf-8")
    return path


def test_unknown_slip_key_fails_closed(tmp_path: Path) -> None:
    bad = _write(
        tmp_path,
        "provider: truth\nprofiles:\n  x:\n    noise:\n      slip_jump_magnitude: 1\n",
    )
    with pytest.raises(ValueError, match="unknown odometry noise keys"):
        load_pose_config(bad, profile="x")


def test_unknown_health_key_fails_closed(tmp_path: Path) -> None:
    """Previously fail-OPEN. Adding a health key without closing this would widen it."""

    bad = _write(tmp_path, "provider: truth\nprofiles:\n  x:\n    health:\n      los_after_s: 3\n")
    with pytest.raises(ValueError, match="unknown keys in pose profile 'x' health"):
        load_pose_config(bad, profile="x")


def test_unknown_map_correction_key_fails_closed(tmp_path: Path) -> None:
    bad = _write(
        tmp_path,
        "provider: truth\nprofiles:\n  x:\n    map_correction:\n      enable: true\n",
    )
    with pytest.raises(ValueError, match="unknown keys in pose profile 'x' map_correction"):
        load_pose_config(bad, profile="x")


@pytest.mark.parametrize(
    ("body", "error", "match"),
    [
        # Wrong shape -> TypeError; well-shaped but invalid -> ValueError.
        ("      lost_windows: 4.0\n", TypeError, "must be a list"),
        ("      lost_windows:\n        - [4.0, 3.0]\n", TypeError, "must be mappings"),
        ("      lost_windows:\n        - start_s: 4.0\n", ValueError, "missing keys"),
        (
            "      lost_windows:\n        - start_s: 4.0\n          dur_s: 3.0\n",
            ValueError,
            "unknown keys",
        ),
        (
            "      lost_windows:\n        - start_s: -1.0\n          duration_s: 3.0\n",
            ValueError,
            "non-negative",
        ),
        (
            "      lost_windows:\n        - start_s: 4.0\n          duration_s: 0\n",
            ValueError,
            "positive",
        ),
    ],
)
def test_malformed_lost_windows_in_yaml_fail_closed(
    tmp_path: Path, body: str, error: type[Exception], match: str
) -> None:
    bad = _write(tmp_path, "provider: truth\nprofiles:\n  x:\n    health:\n" + body)
    with pytest.raises(error, match=match):
        load_pose_config(bad, profile="x")


def test_lost_windows_round_trip_from_yaml_into_a_provider(tmp_path: Path) -> None:
    good = _write(
        tmp_path,
        "provider: truth\nprofiles:\n  x:\n    health:\n      lost_windows:\n"
        "        - start_s: 2.0\n          duration_s: 1.0\n"
        "        - start_s: 0.5\n          duration_s: 0.25\n",
    )
    cfg = load_pose_config(good, profile="x")
    assert cfg.lost_windows == ((0.5, 0.25), (2.0, 1.0))
    assert cfg.build().lost_windows == ((0.5, 0.25), (2.0, 1.0))
