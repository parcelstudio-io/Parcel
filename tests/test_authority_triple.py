"""Contract tests for the embodiment authority triple.

Covers the pieces card A-2 establishes: profile additions, ``SpeedRegime``
(including ``from_froude`` and the elementwise-min arbitration rule),
``SafetyEnvelope``, and the PX4-style field metadata every field must carry.
Nothing here is wired into navigation yet — these tests pin the authority's own
behaviour so the later wiring cards have something to break.
"""

from __future__ import annotations

import dataclasses
import math

import pytest

from parcel_robot.authority import (
    DEFAULT_SAFETY_ENVELOPE,
    DEFAULT_SPEED_REGIME,
    DEFAULT_STAND_OFF_ENVELOPE,
    GRAVITY_MPS2,
    HUMAN_BUCKET,
    REGIME_NAMES,
    SCALING_BUCKETS,
    FieldMeta,
    RegimeLimits,
    SafetyEnvelope,
    SpeedRegime,
    StandOffEnvelope,
    arbitrate_limits,
)
from parcel_robot.robot_profile import DEFAULT_ROBOT_PROFILE, RobotProfile


def half_scale_profile() -> RobotProfile:
    """A geometrically half-size Go2 (embodiment bucket halved, nothing else)."""

    return RobotProfile(
        name="half-go2",
        upper_link_m=DEFAULT_ROBOT_PROFILE.upper_link_m / 2.0,
        lower_link_m=DEFAULT_ROBOT_PROFILE.lower_link_m / 2.0,
        stance_z_m=DEFAULT_ROBOT_PROFILE.stance_z_m / 2.0,
        footprint_radius_m=DEFAULT_ROBOT_PROFILE.footprint_radius_m / 2.0,
        scan_height_m=DEFAULT_ROBOT_PROFILE.scan_height_m / 2.0,
        obstacle_clearance_height_m=DEFAULT_ROBOT_PROFILE.obstacle_clearance_height_m / 2.0,
    )


# ---------------------------------------------------------------------------
# RobotProfile additions
# ---------------------------------------------------------------------------


def test_profile_leg_length_is_the_sum_of_the_existing_link_lengths() -> None:
    profile = DEFAULT_ROBOT_PROFILE
    assert profile.leg_length_m == profile.upper_link_m + profile.lower_link_m
    assert profile.leg_length_m == pytest.approx(0.426)


def test_profile_gained_decel_and_reaction_latency_with_config_provenance() -> None:
    assert DEFAULT_ROBOT_PROFILE.decel_max_mps2 == 1.4
    assert DEFAULT_ROBOT_PROFILE.reaction_latency_s == 0.12


def test_profile_from_config_accepts_the_new_keys_and_still_fails_closed() -> None:
    profile = RobotProfile.from_config(
        {"profile": {"decel_max_mps2": 2.0, "reaction_latency_s": 0.2}}
    )
    assert profile.decel_max_mps2 == 2.0
    assert profile.reaction_latency_s == 0.2
    with pytest.raises(ValueError, match="unsupported robot.profile keys"):
        RobotProfile.from_config({"profile": {"decel_max_mps3": 1.0}})


@pytest.mark.parametrize(
    "overrides",
    [
        {"decel_max_mps2": 0.0},
        {"decel_max_mps2": float("nan")},
        {"reaction_latency_s": -0.1},
        {"reaction_latency_s": 5.0},
        {"obstacle_clearance_height_m": 0.0},
    ],
)
def test_profile_rejects_out_of_range_dynamics(overrides: dict[str, float]) -> None:
    with pytest.raises(ValueError):
        dataclasses.replace(DEFAULT_ROBOT_PROFILE, **overrides)


# ---------------------------------------------------------------------------
# FieldMeta / buckets
# ---------------------------------------------------------------------------


def test_bucket_vocabulary_is_exactly_the_four_documented_buckets() -> None:
    assert SCALING_BUCKETS == {"embodiment", "dynamics", "latency", "human"}
    assert HUMAN_BUCKET == "human"


def test_field_meta_fails_closed_on_an_unknown_bucket() -> None:
    with pytest.raises(ValueError, match="unknown scaling bucket"):
        FieldMeta(unit="m", source="x", date="2026-08-07", bucket="vibes")


@pytest.mark.parametrize("cls", [RegimeLimits, SafetyEnvelope, StandOffEnvelope])
def test_every_field_carries_metadata(cls: type) -> None:
    assert cls.metadata_covers_every_field()
    for name in cls.FIELD_META:
        meta = cls.field_meta(name)
        assert meta.unit and meta.source and meta.date
        assert meta.bucket in SCALING_BUCKETS


def test_field_meta_lookup_fails_closed() -> None:
    with pytest.raises(KeyError):
        SafetyEnvelope.field_meta("not_a_field")


def test_the_person_social_zone_carries_the_human_bucket_marker() -> None:
    meta = SafetyEnvelope.field_meta("person_social_zone_m")
    assert meta.bucket == HUMAN_BUCKET
    assert meta.never_scales
    assert "never scales" in meta.note.lower()


def test_the_body_terms_are_embodiment_and_the_latency_term_is_latency() -> None:
    assert SafetyEnvelope.field_meta("footprint_radius_m").bucket == "embodiment"
    assert SafetyEnvelope.field_meta("reaction_latency_s").bucket == "latency"
    assert SafetyEnvelope.field_meta("decel_max_mps2").bucket == "dynamics"
    assert not SafetyEnvelope.field_meta("footprint_radius_m").never_scales


def test_pose_uncertainty_and_sensing_intrusion_never_scale() -> None:
    for name in ("pose_uncertainty_m", "sensing_intrusion_m"):
        assert SafetyEnvelope.field_meta(name).never_scales


def test_fields_in_bucket_is_queryable_for_docs() -> None:
    human = SafetyEnvelope.fields_in_bucket("human")
    assert "person_social_zone_m" in human
    assert "footprint_radius_m" not in human
    with pytest.raises(ValueError):
        SafetyEnvelope.fields_in_bucket("nope")


# ---------------------------------------------------------------------------
# SpeedRegime
# ---------------------------------------------------------------------------


def test_all_four_regimes_are_present_and_addressable_by_name() -> None:
    assert REGIME_NAMES == ("cruise", "search", "approach", "recover")
    for name in REGIME_NAMES:
        assert isinstance(DEFAULT_SPEED_REGIME.limits(name), RegimeLimits)
    with pytest.raises(KeyError):
        DEFAULT_SPEED_REGIME.limits("sprint")


def test_regime_velocity_triple_and_accel_pair_shapes() -> None:
    cruise = DEFAULT_SPEED_REGIME.cruise
    assert cruise.velocity_triple == (cruise.vx_mps, cruise.vy_mps, cruise.vyaw_radps)
    assert cruise.accel_pair == (cruise.accel_mps2, cruise.yaw_accel_radps2)


def test_reference_regimes_match_the_live_config_they_were_transcribed_from() -> None:
    """If someone raises cruise_vx in grid.yaml, this is the reminder."""

    assert DEFAULT_SPEED_REGIME.cruise.vx_mps == 0.85
    assert DEFAULT_SPEED_REGIME.cruise.vyaw_radps == 0.90
    assert DEFAULT_SPEED_REGIME.search.vx_mps == 0.22
    assert DEFAULT_SPEED_REGIME.approach.vx_mps == 0.35
    assert DEFAULT_SPEED_REGIME.recover.vx_mps == 0.12
    assert set(SpeedRegime.REGIME_SOURCES) == set(REGIME_NAMES)


def test_froude_number_is_the_documented_ratio() -> None:
    regime = DEFAULT_SPEED_REGIME
    expected = (regime.cruise.vx_mps**2) / (GRAVITY_MPS2 * regime.leg_length_m)
    assert regime.froude == expected
    # A walking quadruped sits well below the Fr=1 walk/run transition.
    assert 0.0 < regime.froude < 1.0


def test_from_froude_reproduces_the_reference_regime_at_its_own_froude() -> None:
    regime = SpeedRegime.from_froude(DEFAULT_ROBOT_PROFILE, DEFAULT_SPEED_REGIME.froude)
    for name in REGIME_NAMES:
        got = regime.limits(name)
        want = DEFAULT_SPEED_REGIME.limits(name)
        for field_name in ("vx_mps", "vy_mps", "vyaw_radps", "accel_mps2", "yaw_accel_radps2"):
            assert getattr(got, field_name) == pytest.approx(getattr(want, field_name))


def test_from_froude_applies_the_sqrt_L_law_not_a_global_scale_factor() -> None:
    half = half_scale_profile()
    scaled = SpeedRegime.from_froude(half, DEFAULT_SPEED_REGIME.froude)
    reference = DEFAULT_SPEED_REGIME
    root_two = math.sqrt(2.0)
    # Speed: /sqrt(2), NOT /2.
    assert scaled.cruise.vx_mps == pytest.approx(reference.cruise.vx_mps / root_two)
    assert scaled.cruise.vx_mps > reference.cruise.vx_mps / 2.0
    # Yaw rate: *sqrt(2) — a small robot turns faster, not slower.
    assert scaled.cruise.vyaw_radps == pytest.approx(reference.cruise.vyaw_radps * root_two)
    # Linear acceleration: invariant.
    assert scaled.cruise.accel_mps2 == pytest.approx(reference.cruise.accel_mps2)
    # Yaw acceleration: *2 (1/lambda).
    assert scaled.cruise.yaw_accel_radps2 == pytest.approx(
        reference.cruise.yaw_accel_radps2 * 2.0
    )
    # ...and the Froude number is preserved, which is the whole point.
    assert scaled.froude == pytest.approx(reference.froude)


def test_from_froude_rejects_a_non_positive_froude_number() -> None:
    with pytest.raises(ValueError):
        SpeedRegime.from_froude(DEFAULT_ROBOT_PROFILE, 0.0)


def test_arbitration_is_the_elementwise_minimum() -> None:
    a = RegimeLimits(
        vx_mps=0.9, vy_mps=0.5, vyaw_radps=1.5, accel_mps2=1.2, yaw_accel_radps2=2.4
    )
    b = RegimeLimits(
        vx_mps=0.85, vy_mps=0.25, vyaw_radps=1.6, accel_mps2=0.9, yaw_accel_radps2=1.8
    )
    merged = arbitrate_limits([a, b])
    assert merged == RegimeLimits(
        vx_mps=0.85, vy_mps=0.25, vyaw_radps=1.5, accel_mps2=0.9, yaw_accel_radps2=1.8
    )
    assert merged == a.elementwise_min(b) == b.elementwise_min(a)


def test_arbitration_can_never_raise_a_contributing_cap() -> None:
    contributors = [DEFAULT_SPEED_REGIME.limits(name) for name in REGIME_NAMES]
    merged = arbitrate_limits(contributors)
    for item in contributors:
        assert merged.vx_mps <= item.vx_mps
        assert merged.vy_mps <= item.vy_mps
        assert merged.vyaw_radps <= item.vyaw_radps
        assert merged.accel_mps2 <= item.accel_mps2
        assert merged.yaw_accel_radps2 <= item.yaw_accel_radps2


def test_arbitration_of_nothing_fails_closed() -> None:
    """An absent authority must never read as permission."""

    with pytest.raises(ValueError, match="at least one"):
        arbitrate_limits([])


def test_speed_regime_from_mapping_fails_closed_on_unknown_keys() -> None:
    with pytest.raises(ValueError, match="unsupported speed regime keys"):
        SpeedRegime.from_mapping({"cruse": {}})
    with pytest.raises(ValueError, match="unsupported regime limits keys"):
        RegimeLimits.from_mapping(
            {
                "vx_mps": 1.0,
                "vy_mps": 0.0,
                "vyaw_radps": 1.0,
                "accel_mps2": 1.0,
                "yaw_accel_radps2": 1.0,
                "vz_mps": 1.0,
            }
        )
    with pytest.raises(ValueError, match="missing regime limits keys"):
        RegimeLimits.from_mapping({"vx_mps": 1.0})


def test_speed_regime_round_trips_through_a_mapping() -> None:
    payload = DEFAULT_SPEED_REGIME.as_dict()
    assert SpeedRegime.from_mapping(payload) == DEFAULT_SPEED_REGIME


def test_regime_limits_reject_negative_and_non_finite_values() -> None:
    with pytest.raises(ValueError):
        RegimeLimits(
            vx_mps=-0.1, vy_mps=0.0, vyaw_radps=0.5, accel_mps2=1.0, yaw_accel_radps2=1.0
        )
    with pytest.raises(ValueError):
        RegimeLimits(
            vx_mps=0.1, vy_mps=0.0, vyaw_radps=0.5, accel_mps2=0.0, yaw_accel_radps2=1.0
        )


# ---------------------------------------------------------------------------
# SafetyEnvelope
# ---------------------------------------------------------------------------


def test_envelope_from_profile_carries_only_body_dynamics_and_latency() -> None:
    half = half_scale_profile()
    envelope = SafetyEnvelope.from_profile(half)
    assert envelope.footprint_radius_m == half.footprint_radius_m
    assert envelope.decel_max_mps2 == half.decel_max_mps2
    assert envelope.reaction_latency_s == half.reaction_latency_s
    assert envelope.person_social_zone_m == DEFAULT_SAFETY_ENVELOPE.person_social_zone_m


def test_envelope_from_profile_rejects_unknown_overrides() -> None:
    with pytest.raises(ValueError, match="unsupported safety envelope override keys"):
        SafetyEnvelope.from_profile(DEFAULT_ROBOT_PROFILE, person_zone_m=1.0)


def test_envelope_from_mapping_fails_closed() -> None:
    assert SafetyEnvelope.from_mapping({"pose_uncertainty_m": 0.3}).pose_uncertainty_m == 0.3
    with pytest.raises(ValueError, match="unsupported safety envelope keys"):
        SafetyEnvelope.from_mapping({"Z_r": 0.3})


def test_stop_distance_rejects_a_negative_speed() -> None:
    with pytest.raises(ValueError):
        DEFAULT_SAFETY_ENVELOPE.stop_distance(-0.1)


def test_stand_off_envelope_from_mapping_fails_closed_and_nests() -> None:
    envelope = StandOffEnvelope.from_mapping(
        {"envelope": {"footprint_radius_m": 0.16}, "vicinity_margin_m": 0.5}
    )
    assert envelope.footprint_radius_m == 0.16
    assert envelope.vicinity(0.0) == 0.66
    with pytest.raises(ValueError, match="unsupported stand-off envelope keys"):
        StandOffEnvelope.from_mapping({"lamppost_stand_off_m": 1.32})


def test_stand_off_envelope_tracks_its_safety_envelope() -> None:
    scaled = StandOffEnvelope(envelope=SafetyEnvelope.from_profile(half_scale_profile()))
    assert scaled.footprint_radius_m == 0.16
    assert scaled.stand_off(0.0) == 0.16 + 0.8 + 0.06 + 0.04
    # The default view is untouched by constructing a scaled one.
    assert DEFAULT_STAND_OFF_ENVELOPE.footprint_radius_m == 0.32


def test_the_core_path_re_exports_the_same_objects() -> None:
    """``parcel_robot.core.authority`` is the plan's path; same objects, no copies."""

    from parcel_robot.core import authority as core_authority

    assert core_authority.DEFAULT_SAFETY_ENVELOPE is DEFAULT_SAFETY_ENVELOPE
    assert core_authority.SafetyEnvelope is SafetyEnvelope
    assert core_authority.SpeedRegime is SpeedRegime
