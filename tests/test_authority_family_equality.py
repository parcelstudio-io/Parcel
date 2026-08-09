"""Bit-for-bit equality proofs for the Lane A family-by-family migration.

Every test here asserts that a value now *derived* from the authority triple
(``parcel_robot.authority``) reproduces the literal it replaced **exactly** at
the current Go2 profile — ``==`` on floats, not ``pytest.approx``. These are the
"commit 1" half of branch-by-abstraction: they must be green *before* any value
change is applied, and they are what makes a later value change visible as a
value change rather than as refactor noise.

The literals below are transcribed from the pre-migration source and are
deliberately duplicated here. That duplication is the point: if someone edits
the authority, this file is the alarm.
"""

from __future__ import annotations

import math

import pytest

from parcel_robot.authority import (
    DEFAULT_SAFETY_ENVELOPE,
    DEFAULT_STAND_OFF_ENVELOPE,
    PERSON_SOCIAL_ZONE_M,
    SafetyEnvelope,
)
from parcel_robot.instructnav.scoring import object_near_envelope_m
from parcel_robot.navigation.collision import CollisionPolicy
from parcel_robot.navigation.proxemic_approach import ProxemicApproachConfig
from parcel_robot.robot_profile import DEFAULT_ROBOT_PROFILE, RobotProfile

# --- the retired literals, transcribed from the pre-migration source ---------

#: ``geometry.ROBOT_FOOTPRINT_RADIUS_M`` before 2026-08-07.
RETIRED_FOOTPRINT_RADIUS_M = 0.32
#: ``geometry.ROBOT_OBSTACLE_HEIGHT_M`` before 2026-08-07.
RETIRED_OBSTACLE_HEIGHT_M = 0.9
#: ``mujoco_lidar.DEFAULT_SCAN_HEIGHT_M`` before 2026-08-07.
RETIRED_SCAN_HEIGHT_M = 0.45
#: ``CollisionPolicy`` field defaults before 2026-08-07.
RETIRED_PERSON_STOP_M = 1.2
RETIRED_PERSON_SLOW_M = 2.5
RETIRED_OBSTACLE_STOP_M = 0.6
RETIRED_OBSTACLE_SLOW_M = 1.2
RETIRED_REACTION_TIME_S = 0.12
#: ``instructnav.scoring.object_near_envelope_m`` lamppost branch.
RETIRED_LAMPPOST_STAND_OFF_M = 1.32
#: ``navigation.approach.safe_approach_pose`` defaults.
RETIRED_TOWARDS_STOP_SHORT_M = 1.2
RETIRED_NEAR_STAND_OFF_FLOOR_M = 1.2
RETIRED_OBSTACLE_STOP_DEFAULT_M = 0.8
RETIRED_STAND_OFF_MARGIN_M = 0.04


# ---------------------------------------------------------------------------
# F-robot-radius
# ---------------------------------------------------------------------------


def test_profile_footprint_radius_equals_the_retired_geometry_literal() -> None:
    assert DEFAULT_ROBOT_PROFILE.footprint_radius_m == RETIRED_FOOTPRINT_RADIUS_M


def test_profile_obstacle_height_equals_the_retired_geometry_literal() -> None:
    assert DEFAULT_ROBOT_PROFILE.obstacle_clearance_height_m == RETIRED_OBSTACLE_HEIGHT_M


def test_geometry_shim_warns_but_still_returns_the_retired_footprint() -> None:
    """Still importable — three modules other lanes own read it today."""

    from parcel_robot import geometry

    with pytest.deprecated_call():
        assert geometry.ROBOT_FOOTPRINT_RADIUS_M == RETIRED_FOOTPRINT_RADIUS_M
    assert geometry.retired_constant_value("ROBOT_OBSTACLE_HEIGHT_M") == (
        RETIRED_OBSTACLE_HEIGHT_M
    )


def test_geometry_shim_hard_errors_on_the_name_with_zero_importers() -> None:
    """The ratchet: ROBOT_OBSTACLE_HEIGHT_M has no importers left, so it bites."""

    from parcel_robot import geometry

    assert geometry.RETIRED_CONSTANTS["ROBOT_OBSTACLE_HEIGHT_M"][2] is True
    assert geometry.RETIRED_CONSTANTS["ROBOT_FOOTPRINT_RADIUS_M"][2] is False
    with pytest.raises(AttributeError, match="was removed on 2026-08-07"):
        geometry.ROBOT_OBSTACLE_HEIGHT_M  # noqa: B018


def test_geometry_shim_rejects_anything_it_never_owned() -> None:
    from parcel_robot import geometry

    with pytest.raises(AttributeError):
        geometry.ROBOT_SOMETHING_ELSE_M  # noqa: B018


def test_lidar_scan_height_equals_the_retired_literal() -> None:
    from parcel_robot.mujoco_lidar import DEFAULT_SCAN_HEIGHT_M

    assert DEFAULT_SCAN_HEIGHT_M == RETIRED_SCAN_HEIGHT_M
    assert DEFAULT_SCAN_HEIGHT_M == DEFAULT_ROBOT_PROFILE.scan_height_m


def test_proxemic_config_resolves_the_radius_from_the_profile() -> None:
    assert ProxemicApproachConfig().robot_radius_m == RETIRED_FOOTPRINT_RADIUS_M


def test_proxemic_config_honours_an_injected_profile() -> None:
    """The whole point of killing the default argument."""

    half = RobotProfile(name="half", footprint_radius_m=0.16)
    assert ProxemicApproachConfig(profile=half).robot_radius_m == 0.16
    # An explicit radius still wins over the profile.
    assert ProxemicApproachConfig(profile=half, robot_radius_m=0.4).robot_radius_m == 0.4


def test_lidar_defaults_resolve_from_an_injected_profile() -> None:
    from parcel_robot.mujoco_lidar import _resolve_body

    half = RobotProfile(name="half", footprint_radius_m=0.16, obstacle_clearance_height_m=0.45)
    assert _resolve_body(None, None, None) == (
        RETIRED_FOOTPRINT_RADIUS_M,
        RETIRED_OBSTACLE_HEIGHT_M,
    )
    assert _resolve_body(half, None, None) == (0.16, 0.45)
    assert _resolve_body(half, 0.9, 2.0) == (0.9, 2.0)


def test_headless_world_resolves_radius_from_an_injected_profile() -> None:
    from parcel_robot.headless_city import HeadlessCityWorld

    world = HeadlessCityWorld()
    assert world.robot_radius_m == RETIRED_FOOTPRINT_RADIUS_M
    assert world.profile is DEFAULT_ROBOT_PROFILE


# ---------------------------------------------------------------------------
# F-proximity
# ---------------------------------------------------------------------------


def test_collision_policy_defaults_are_bit_equal_to_the_retired_literals() -> None:
    policy = CollisionPolicy()
    assert policy.person_stop_m == RETIRED_PERSON_STOP_M
    assert policy.person_slow_m == RETIRED_PERSON_SLOW_M
    assert policy.obstacle_stop_m == RETIRED_OBSTACLE_STOP_M
    assert policy.obstacle_slow_m == RETIRED_OBSTACLE_SLOW_M
    assert policy.reaction_time_s == RETIRED_REACTION_TIME_S


def test_person_stop_at_rest_is_the_social_zone_not_the_iso_sum() -> None:
    """The human floor binds at Go2 scale; the ISO sum at rest is 0.488 m."""

    envelope = DEFAULT_SAFETY_ENVELOPE
    iso_sum_at_rest = envelope.stop_distance(0.0) + 1.4 * envelope.reaction_latency_s
    assert iso_sum_at_rest < envelope.person_social_zone_m
    assert envelope.person_stop(0.0) == PERSON_SOCIAL_ZONE_M
    assert envelope.social_zone_is_binding


def test_stop_distance_reproduces_the_iso_ts_15066_shape() -> None:
    envelope = DEFAULT_SAFETY_ENVELOPE
    for speed in (0.0, 0.22, 0.35, 0.85, 1.0):
        expected = (
            envelope.footprint_radius_m
            + speed * envelope.reaction_latency_s
            + (speed * speed) / (2.0 * envelope.decel_max_mps2)
            + envelope.sensing_intrusion_m
            + envelope.pose_uncertainty_m
        )
        assert envelope.stop_distance(speed) == expected


def test_pose_uncertainty_widens_every_envelope_by_exactly_itself() -> None:
    """``Z_r`` is the single field Lane B sets when pose covariance goes live."""

    import dataclasses

    base = DEFAULT_SAFETY_ENVELOPE
    widened = dataclasses.replace(base, pose_uncertainty_m=0.25)
    for speed in (0.0, 0.5, 0.85):
        assert widened.stop_distance(speed) == base.stop_distance(speed) + 0.25
    # The person floor still binds until Z_r pushes the ISO sum past 1.2 m.
    assert widened.person_stop(0.0) == PERSON_SOCIAL_ZONE_M
    huge = dataclasses.replace(base, pose_uncertainty_m=2.0)
    assert huge.person_stop(0.0) > PERSON_SOCIAL_ZONE_M


def test_approach_stop_short_and_stand_off_floor_equal_the_retired_literals() -> None:
    envelope = DEFAULT_STAND_OFF_ENVELOPE
    assert envelope.towards_stop_short_m == RETIRED_TOWARDS_STOP_SHORT_M
    assert envelope.near_stand_off_floor_m == RETIRED_NEAR_STAND_OFF_FLOOR_M
    assert envelope.target_surface_clearance_m == RETIRED_OBSTACLE_STOP_DEFAULT_M
    assert envelope.stand_off_margin_m == RETIRED_STAND_OFF_MARGIN_M


# ---------------------------------------------------------------------------
# F-arrival — the stand-off composite
# ---------------------------------------------------------------------------


def _retired_object_near_envelope_m(
    object_radius_m: float,
    *,
    label: str = "",
) -> tuple[float, float, float]:
    """Verbatim copy of ``object_near_envelope_m`` before the decomposition."""

    radius = float(object_radius_m)
    if not math.isfinite(radius) or radius < 0.0:
        raise ValueError("object_radius_m must be finite and ≥ 0")
    stand_off = radius + 0.32 + 0.8 + 0.06 + 0.04
    if label == "lamppost":
        stand_off = 1.32
    minimum = radius + 0.32 + 0.8
    vicinity = radius + 0.32 + 1.0
    if label == "building":
        stand_off = max(stand_off, radius + 0.32 + 1.0)
        vicinity = max(vicinity, stand_off + 0.3)
        minimum = max(minimum, radius + 0.32 + 0.8)
    vicinity = max(vicinity, stand_off)
    if minimum > vicinity:
        raise ValueError("near envelope collapsed: minimum_vicinity > vicinity")
    return float(stand_off), float(minimum), float(vicinity)


#: Every radius the live city scene actually produces, plus the boundaries.
_SCENE_RADII = (
    0.0,
    0.06,  # lamp_post_1 / lamp_post_2
    0.45,  # planter_1 / planter_2
    0.58,  # tree_1 / tree_2
    0.733757,  # bench_1
    1.843909,  # bldg_2
    2.051828,  # bldg_3
    2.193171,  # bldg_4
    2.202272,  # bldg_5
    2.343075,  # bldg_1
    5.0,
)


@pytest.mark.parametrize("radius", _SCENE_RADII)
@pytest.mark.parametrize("label", ["", "lamppost", "building", "bench", "tree", "planter"])
def test_near_envelope_decomposition_is_bit_for_bit_equal(radius: float, label: str) -> None:
    """The named-term decomposition reproduces the literal sum exactly."""

    assert object_near_envelope_m(radius, label=label) == _retired_object_near_envelope_m(
        radius, label=label
    )


def test_lamppost_stand_off_decomposes_exactly_into_footprint_plus_vicinity() -> None:
    """``1.32`` was ``0.32 + 1.0`` all along — and that sum is exact in IEEE-754."""

    envelope = DEFAULT_STAND_OFF_ENVELOPE
    assert envelope.point_anchor_stand_off() == RETIRED_LAMPPOST_STAND_OFF_M
    assert envelope.point_anchor_stand_off() == envelope.vicinity(0.0)
    assert (
        envelope.footprint_radius_m + envelope.vicinity_margin_m
        == RETIRED_LAMPPOST_STAND_OFF_M
    )
    # The other plausible decomposition (the generic composite at a 0.1 m
    # reference radius) is NOT bit-equal — it lands one ULP high. Pinned so
    # nobody "simplifies" the lamppost branch into it.
    assert 0.1 + 0.32 + 0.8 + 0.06 + 0.04 != RETIRED_LAMPPOST_STAND_OFF_M


@pytest.mark.parametrize("radius", _SCENE_RADII)
def test_stand_off_terms_compose_left_to_right_like_the_literal_sum(radius: float) -> None:
    envelope = DEFAULT_STAND_OFF_ENVELOPE
    assert envelope.stand_off(radius) == radius + 0.32 + 0.8 + 0.06 + 0.04
    assert envelope.minimum_vicinity(radius) == radius + 0.32 + 0.8
    assert envelope.vicinity(radius) == radius + 0.32 + 1.0


def test_scene_derived_envelopes_are_unchanged_for_every_live_landmark() -> None:
    """End-to-end: the values city_semantics stamps into metadata do not move."""

    for radius in _SCENE_RADII:
        for label in ("", "lamppost", "building", "bench", "tree", "planter"):
            derived = object_near_envelope_m(radius, label=label)
            retired = _retired_object_near_envelope_m(radius, label=label)
            assert derived == retired, (radius, label, derived, retired)


# ---------------------------------------------------------------------------
# Scaling: the derivation actually moves when the body does
# ---------------------------------------------------------------------------


def test_a_half_size_envelope_halves_the_body_term_and_keeps_the_human_term() -> None:
    half = RobotProfile(
        name="half-go2",
        upper_link_m=0.1065,
        lower_link_m=0.1065,
        stance_z_m=-0.1325,
        footprint_radius_m=0.16,
        scan_height_m=0.225,
        obstacle_clearance_height_m=0.45,
    )
    envelope = SafetyEnvelope.from_profile(half)
    assert envelope.footprint_radius_m == 0.16
    assert envelope.stop_distance(0.0) == 0.16
    # HUMAN BUCKET: unchanged.
    assert envelope.person_social_zone_m == PERSON_SOCIAL_ZONE_M
    assert envelope.person_stop(0.0) == PERSON_SOCIAL_ZONE_M
    # ...and tau is unchanged too (latency bucket).
    assert envelope.reaction_latency_s == DEFAULT_SAFETY_ENVELOPE.reaction_latency_s
