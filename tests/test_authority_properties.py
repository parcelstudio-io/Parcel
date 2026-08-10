"""Hypothesis property tests over the authority triple's parameter space.

The equality tests pin one point (Go2, today). These pin the *shape* of the
envelope over the whole admissible profile space, which is what a scaled robot
actually exercises. The plan names three of them explicitly:

* envelope orderings — ``stop_distance < person_stop``, both monotone in ``v``;
* ``person_stop >= 1.2 m`` **at every scale** (the HUMAN-BUCKET invariant);
* ``from_froude`` dimensional sanity.

Hypothesis is a test-only dependency and is not in ``pyproject.toml`` yet (that
file is owned by another lane this round), so the module skips cleanly where it
is absent rather than reddening someone else's build.
"""

from __future__ import annotations

import dataclasses
import math

import pytest

hypothesis = pytest.importorskip(
    "hypothesis",
    reason="hypothesis is a test-only dependency; see LANE_A_STATUS.md handoff note",
)

from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from parcel_robot.authority import (
    DEFAULT_SPEED_REGIME,
    GRAVITY_MPS2,
    PERSON_SOCIAL_ZONE_M,
    RegimeLimits,
    SafetyEnvelope,
    SpeedRegime,
    StandOffEnvelope,
    arbitrate_limits,
)
from parcel_robot.robot_profile import RobotProfile

SETTINGS = settings(
    max_examples=200,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)

# Profile bounds are the ones RobotProfile.__post_init__ enforces.
link_lengths = st.floats(min_value=0.03, max_value=0.7, allow_nan=False, allow_infinity=False)
footprints = st.floats(min_value=0.05, max_value=1.5, allow_nan=False, allow_infinity=False)
decels = st.floats(min_value=0.05, max_value=20.0, allow_nan=False, allow_infinity=False)
latencies = st.floats(min_value=0.0, max_value=2.0, allow_nan=False, allow_infinity=False)
speeds = st.floats(min_value=0.0, max_value=10.0, allow_nan=False, allow_infinity=False)
uncertainties = st.floats(min_value=0.0, max_value=2.0, allow_nan=False, allow_infinity=False)


@st.composite
def profiles(draw: st.DrawFn) -> RobotProfile:
    upper = draw(link_lengths)
    lower = draw(link_lengths)
    # Stance must be negative and strictly inside full leg extension.
    stance = -draw(
        st.floats(min_value=0.02, max_value=0.99, allow_nan=False, allow_infinity=False)
    ) * (upper + lower)
    assume(-1.5 <= stance <= -0.02)
    return RobotProfile(
        name="hypothesis",
        upper_link_m=upper,
        lower_link_m=lower,
        stance_z_m=stance,
        footprint_radius_m=draw(footprints),
        decel_max_mps2=draw(decels),
        reaction_latency_s=draw(latencies),
    )


@st.composite
def envelopes(draw: st.DrawFn) -> SafetyEnvelope:
    profile = draw(profiles())
    return SafetyEnvelope.from_profile(
        profile,
        sensing_intrusion_m=draw(uncertainties),
        pose_uncertainty_m=draw(uncertainties),
    )


# ---------------------------------------------------------------------------
# Envelope orderings
# ---------------------------------------------------------------------------


@SETTINGS
@given(envelope=envelopes(), speed=speeds)
def test_person_stop_is_never_below_the_bare_stopping_distance(
    envelope: SafetyEnvelope, speed: float
) -> None:
    stop = envelope.stop_distance(speed)
    person = envelope.person_stop(speed)
    assert person >= stop or person == PERSON_SOCIAL_ZONE_M
    # The only way person_stop can be below stop_distance is the social floor
    # binding on a body whose own stopping distance already exceeds 1.2 m —
    # a genuinely large/fast robot. Record that case rather than assert it away.
    if person < stop:
        assert stop > envelope.person_social_zone_m


@SETTINGS
@given(envelope=envelopes(), speed=speeds)
def test_person_stop_dominates_stop_distance_plus_the_human_allowance(
    envelope: SafetyEnvelope, speed: float
) -> None:
    """P0-H definition: metres = stop_m + closing_mps * latency_s."""

    allowance = envelope.stop_distance(speed) + speed * envelope.person_latency_s
    assert envelope.person_stop(speed) >= allowance
    assert envelope.person_stop(speed) >= envelope.person_social_zone_m


@SETTINGS
@given(envelope=envelopes(), speed=speeds, closing=speeds)
def test_person_stop_closing_term_is_dimensionally_metres(
    envelope: SafetyEnvelope, speed: float, closing: float
) -> None:
    """Closing speed × person_latency_s must add metres, never seconds."""

    base = envelope.stop_distance(speed)
    got = envelope.person_stop(speed, closing_speed_mps=closing)
    expected = max(
        envelope.person_social_zone_m,
        base + max(0.0, closing) * envelope.person_latency_s,
    )
    assert got == expected


@SETTINGS
@given(envelope=envelopes(), a=speeds, b=speeds)
def test_stop_distance_is_monotone_non_decreasing_in_speed(
    envelope: SafetyEnvelope, a: float, b: float
) -> None:
    lo, hi = min(a, b), max(a, b)
    assert envelope.stop_distance(lo) <= envelope.stop_distance(hi)
    assert envelope.person_stop(lo) <= envelope.person_stop(hi)


@SETTINGS
@given(envelope=envelopes())
def test_stop_distance_at_rest_is_exactly_the_static_terms(
    envelope: SafetyEnvelope,
) -> None:
    assert envelope.stop_distance(0.0) == (
        envelope.footprint_radius_m
        + envelope.sensing_intrusion_m
        + envelope.pose_uncertainty_m
    )


@SETTINGS
@given(envelope=envelopes(), speed=speeds, extra=uncertainties)
def test_pose_uncertainty_widens_the_envelope_by_exactly_itself(
    envelope: SafetyEnvelope, speed: float, extra: float
) -> None:
    """``Z_r`` is additive — the property Lane B relies on."""

    widened = dataclasses.replace(
        envelope, pose_uncertainty_m=envelope.pose_uncertainty_m + extra
    )
    assert widened.stop_distance(speed) == pytest.approx(
        envelope.stop_distance(speed) + extra, rel=1e-12, abs=1e-12
    )
    assert widened.person_stop(speed) >= envelope.person_stop(speed)


# ---------------------------------------------------------------------------
# The HUMAN-BUCKET invariant
# ---------------------------------------------------------------------------


@SETTINGS
@given(profile=profiles(), speed=speeds)
def test_person_stop_is_at_least_the_social_zone_at_every_scale(
    profile: RobotProfile, speed: float
) -> None:
    """A half-size dog does not get half a personal-space zone."""

    envelope = SafetyEnvelope.from_profile(profile)
    assert envelope.person_social_zone_m == PERSON_SOCIAL_ZONE_M
    assert envelope.person_stop(speed) >= PERSON_SOCIAL_ZONE_M


@SETTINGS
@given(profile=profiles())
def test_scaling_the_body_never_moves_a_human_bucket_field(
    profile: RobotProfile,
) -> None:
    envelope = SafetyEnvelope.from_profile(profile)
    for name in SafetyEnvelope.fields_in_bucket("human"):
        assert getattr(envelope, name) == getattr(SafetyEnvelope(), name)


@SETTINGS
@given(profile=profiles())
def test_embodiment_fields_do_follow_the_body(profile: RobotProfile) -> None:
    envelope = SafetyEnvelope.from_profile(profile)
    assert envelope.footprint_radius_m == profile.footprint_radius_m
    assert envelope.stop_distance(0.0) == profile.footprint_radius_m


@SETTINGS
@given(profile=profiles(), radius=st.floats(min_value=0.0, max_value=5.0))
def test_stand_off_ordering_holds_at_every_scale(
    profile: RobotProfile, radius: float
) -> None:
    envelope = StandOffEnvelope(envelope=SafetyEnvelope.from_profile(profile))
    assert envelope.minimum_vicinity(radius) <= envelope.stand_off(radius)
    assert envelope.stand_off(radius) > radius + envelope.footprint_radius_m
    assert envelope.point_anchor_stand_off() == envelope.vicinity(0.0)


# ---------------------------------------------------------------------------
# from_froude dimensional sanity
# ---------------------------------------------------------------------------


froude_numbers = st.floats(
    min_value=1e-3, max_value=3.0, allow_nan=False, allow_infinity=False
)


@SETTINGS
@given(profile=profiles(), froude=froude_numbers)
def test_from_froude_round_trips_through_the_froude_property(
    profile: RobotProfile, froude: float
) -> None:
    regime = SpeedRegime.from_froude(profile, froude)
    assert regime.froude == pytest.approx(froude, rel=1e-9)
    assert regime.leg_length_m == pytest.approx(profile.leg_length_m)


@SETTINGS
@given(profile=profiles(), froude=froude_numbers)
def test_from_froude_matches_the_closed_form_cruise_speed(
    profile: RobotProfile, froude: float
) -> None:
    regime = SpeedRegime.from_froude(profile, froude)
    assert regime.cruise.vx_mps == pytest.approx(
        math.sqrt(froude * GRAVITY_MPS2 * profile.leg_length_m)
    )


@SETTINGS
@given(profile=profiles(), froude=froude_numbers)
def test_from_froude_preserves_the_regime_speed_ordering(
    profile: RobotProfile, froude: float
) -> None:
    """CRUISE is the fastest regime and RECOVER the slowest, at any scale."""

    regime = SpeedRegime.from_froude(profile, froude)
    assert regime.cruise.vx_mps >= regime.approach.vx_mps
    assert regime.approach.vx_mps >= regime.search.vx_mps
    assert regime.search.vx_mps >= regime.recover.vx_mps


@SETTINGS
@given(
    profile=profiles(),
    froude=froude_numbers,
    ratio=st.floats(min_value=0.2, max_value=5.0, allow_nan=False, allow_infinity=False),
)
def test_constant_froude_gives_the_sqrt_L_speed_law(
    profile: RobotProfile, froude: float, ratio: float
) -> None:
    """``v ~ sqrt(lambda)``: the scaling law, not a global scale factor."""

    upper = profile.upper_link_m * ratio
    lower = profile.lower_link_m * ratio
    stance = profile.stance_z_m * ratio
    assume(0.03 <= upper <= 1.5)
    assume(0.03 <= lower <= 1.5)
    assume(-1.5 <= stance <= -0.02)
    assume(abs(stance) < upper + lower)
    scaled_profile = dataclasses.replace(
        profile, upper_link_m=upper, lower_link_m=lower, stance_z_m=stance
    )
    base = SpeedRegime.from_froude(profile, froude)
    scaled = SpeedRegime.from_froude(scaled_profile, froude)
    assert scaled.cruise.vx_mps == pytest.approx(
        base.cruise.vx_mps * math.sqrt(ratio), rel=1e-9
    )
    # ...and yaw rate goes the other way.
    assert scaled.cruise.vyaw_radps == pytest.approx(
        base.cruise.vyaw_radps / math.sqrt(ratio), rel=1e-9
    )
    # Linear acceleration is Froude-invariant.
    assert scaled.cruise.accel_mps2 == pytest.approx(base.cruise.accel_mps2, rel=1e-9)


@SETTINGS
@given(profile=profiles(), a=froude_numbers, b=froude_numbers)
def test_higher_froude_is_never_slower(
    profile: RobotProfile, a: float, b: float
) -> None:
    lo, hi = min(a, b), max(a, b)
    assert (
        SpeedRegime.from_froude(profile, lo).cruise.vx_mps
        <= SpeedRegime.from_froude(profile, hi).cruise.vx_mps
    )


# ---------------------------------------------------------------------------
# Arbitration
# ---------------------------------------------------------------------------


regime_limits = st.builds(
    RegimeLimits,
    vx_mps=st.floats(min_value=0.0, max_value=5.0, allow_nan=False),
    vy_mps=st.floats(min_value=0.0, max_value=5.0, allow_nan=False),
    vyaw_radps=st.floats(min_value=0.0, max_value=10.0, allow_nan=False),
    accel_mps2=st.floats(min_value=1e-3, max_value=20.0, allow_nan=False),
    yaw_accel_radps2=st.floats(min_value=1e-3, max_value=40.0, allow_nan=False),
)


@SETTINGS
@given(limits=st.lists(regime_limits, min_size=1, max_size=6))
def test_arbitration_is_a_lower_bound_on_every_contributor(
    limits: list[RegimeLimits],
) -> None:
    merged = arbitrate_limits(limits)
    for item in limits:
        assert merged.vx_mps <= item.vx_mps
        assert merged.vy_mps <= item.vy_mps
        assert merged.vyaw_radps <= item.vyaw_radps
        assert merged.accel_mps2 <= item.accel_mps2
        assert merged.yaw_accel_radps2 <= item.yaw_accel_radps2


@SETTINGS
@given(limits=st.lists(regime_limits, min_size=1, max_size=6))
def test_arbitration_is_order_independent(limits: list[RegimeLimits]) -> None:
    assert arbitrate_limits(limits) == arbitrate_limits(list(reversed(limits)))


@SETTINGS
@given(limits=st.lists(regime_limits, min_size=1, max_size=4))
def test_arbitration_is_idempotent(limits: list[RegimeLimits]) -> None:
    once = arbitrate_limits(limits)
    assert arbitrate_limits([once, *limits]) == once


def test_the_reference_regime_arbitrates_to_the_recover_floor() -> None:
    merged = DEFAULT_SPEED_REGIME.arbitrated()
    assert merged.vx_mps == DEFAULT_SPEED_REGIME.recover.vx_mps
