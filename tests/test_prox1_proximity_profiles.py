"""PROX-1 — capability proofs for context-selected person proximity.

One test per behaviour the card names, against the SHIPPED
``configs/robot.yaml`` and the real ``ReactiveSafetyPolicy``. No seeded-RED
battery, no combinatorial sweep: the owner's 2026-08-23 testing directive.

``configs/robot.yaml`` is SHA-locked (``evals/companion/embodied_plan_v1/
manifest.json`` -> ``scripts/ci_gate.py`` DIGEST_SENTINELS), and moving it needs
an owner-authorised re-pin this card has no authority to make. So the config
half is preregistered HERE, as :data:`PROPOSED_SAFETY_BLOCK` — the exact text
that goes under ``safety:`` — and every test below that would have read the
file reads that block instead. When the re-pin is authorised the block lands
verbatim and no code changes.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest
import yaml

from parcel_robot.authority import PERSON_SOCIAL_ZONE_FLOOR_M
from parcel_robot.navigation.proximity_profiles import (
    PREREGISTERED_PROXIMITY_PROFILES,
    ProximityContext,
    ProximityContextOwner,
    ProximityProfile,
    load_proximity_profiles,
    proximity_context_for_venue,
    resolve_proximity_profile,
)
from parcel_robot.navigation.reactive_safety import ReactiveSafetyPolicy

REPO = Path(__file__).resolve().parents[1]

#: The block that goes under ``safety:`` in ``configs/robot.yaml`` once the
#: SHA re-pin is authorised. Held here so it is PROVEN loadable and
#: floor-clearing before it ships, rather than after.
PROPOSED_SAFETY_BLOCK = """
proximity_profiles:
  default:
    person_stop_m: 1.2
    person_slow_m: 2.5
  indoor:
    person_stop_m: 0.95
    person_slow_m: 2.0
  narrow:
    person_stop_m: 0.7
    person_slow_m: 1.5
"""


def shipped_safety_section() -> dict:
    raw = yaml.safe_load((REPO / "configs" / "robot.yaml").read_text(encoding="utf-8"))
    return dict(raw["safety"])


def proposed_safety_section() -> dict:
    """The shipped safety section with the proposed block merged in."""

    safety = shipped_safety_section()
    safety.update(yaml.safe_load(PROPOSED_SAFETY_BLOCK))
    return safety


def shipped_policy() -> ReactiveSafetyPolicy:
    """The gate the shipped config commissions — the card's real base."""

    safety = shipped_safety_section()
    return ReactiveSafetyPolicy(
        obstacle_stop_m=float(safety["obstacle_stop_m"]),
        obstacle_slow_m=float(safety["obstacle_slow_m"]),
        person_stop_m=float(safety["person_stop_m"]),
        person_slow_m=float(safety["person_slow_m"]),
        telemetry_stale_s=float(safety["telemetry_stale_s"]),
    )


def test_the_shipped_ladder_shortens_and_every_rung_clears_the_existing_floor() -> None:
    """The owner's ask, measured: shorter, shorter still, and never under the floor."""

    policy = shipped_policy()
    profiles = load_proximity_profiles(proposed_safety_section(), base_policy=policy)

    stops = [
        resolve_proximity_profile(context, profiles).person_stop_m
        for context in (ProximityContext.DEFAULT, ProximityContext.INDOOR, ProximityContext.NARROW)
    ]
    assert stops == sorted(stops, reverse=True), stops
    assert stops[0] > stops[1] > stops[2]

    for context, profile in profiles.items():
        assert profile.person_stop_m >= PERSON_SOCIAL_ZONE_FLOOR_M, context
        assert profile.person_slow_m > profile.person_stop_m, context
        # The proof that it clears the floor is that the EXISTING validator
        # builds it — not an inequality this test restates.
        commissioned = profile.apply_to(policy)
        assert commissioned.person_stop_m == profile.person_stop_m
        assert commissioned.commissioned_envelope.person_social_zone_m == profile.person_stop_m


def test_a_context_switch_swaps_the_active_pair_on_the_real_gate() -> None:
    """The card's headline behaviour, through the envelope path it must use."""

    policy = shipped_policy()
    owner = ProximityContextOwner(
        policy, load_proximity_profiles(proposed_safety_section(), base_policy=policy)
    )

    assert owner.context is ProximityContext.DEFAULT
    assert owner.policy.person_stop_m == pytest.approx(1.2)
    assert owner.policy.person_slow_m == pytest.approx(2.5)

    active = owner.set_proximity_context("indoor", source="reasoner_proposal")
    assert owner.context is ProximityContext.INDOOR
    assert active is owner.policy
    assert owner.policy.person_stop_m == pytest.approx(0.95)
    assert owner.policy.person_slow_m == pytest.approx(2.0)
    # It went through SafetyEnvelope.with_person_social_zone, not around it.
    assert owner.policy.commissioned_envelope.person_social_zone_m == pytest.approx(0.95)
    assert owner.policy.person_stop_m < policy.person_stop_m

    owner.set_proximity_context(ProximityContext.NARROW)
    assert owner.policy.person_stop_m == pytest.approx(0.70)
    # Everything the card did NOT authorise this to move stays put.
    assert owner.policy.obstacle_stop_m == policy.obstacle_stop_m
    assert owner.policy.obstacle_slow_m == policy.obstacle_slow_m
    assert owner.policy.envelope == policy.envelope


def test_a_below_floor_profile_is_refused_by_the_unchanged_validator() -> None:
    """The card's own illustrative `narrow: 0.5` is a refusal, and says why."""

    policy = shipped_policy()
    safety = proposed_safety_section()
    safety["proximity_profiles"] = dict(safety["proximity_profiles"])
    safety["proximity_profiles"]["narrow"] = {"person_stop_m": 0.5, "person_slow_m": 1.2}

    with pytest.raises(ValueError) as refusal:
        load_proximity_profiles(safety, base_policy=policy)

    message = str(refusal.value)
    assert "narrow" in message
    assert str(PERSON_SOCIAL_ZONE_FLOOR_M) in message
    assert "PERSON_SOCIAL_ZONE_FLOOR_M" in message

    # And a table that was never validated cannot be smuggled past the owner.
    with pytest.raises(ValueError):
        ProximityContextOwner(policy, {ProximityContext.DEFAULT: ProximityProfile(0.5, 1.2)})


def test_no_new_config_keys_leaves_todays_behaviour_byte_identical() -> None:
    """Baseline: the block's absence must change nothing, for ANY commissioning."""

    policy = shipped_policy()
    without = shipped_safety_section()
    assert "proximity_profiles" not in without, "the SHA-locked base has not moved"

    profiles = load_proximity_profiles(without, base_policy=policy)
    default = resolve_proximity_profile(ProximityContext.DEFAULT, profiles)
    assert default.person_stop_m == policy.person_stop_m
    assert default.person_slow_m == policy.person_slow_m
    assert ProximityContextOwner(policy, profiles).policy == policy

    # Not only for the shipped numbers: a deployment that commissioned its own
    # person clearance keeps exactly that, rather than being reset to a constant.
    tighter = ReactiveSafetyPolicy(person_stop_m=0.8, person_slow_m=1.9)
    own_table = load_proximity_profiles(None, base_policy=tighter)
    assert ProximityContextOwner(tighter, own_table).policy == tighter


def test_a_reasoning_model_may_propose_a_context_but_never_mint_a_distance() -> None:
    """Architecture rule 2, enforced by type at the only public entry point."""

    owner = ProximityContextOwner(shipped_policy())
    owner.set_proximity_context(ProximityContext.INDOOR)
    before = owner.policy

    for minted in (0.4, 0, 1, True, 0.95):
        with pytest.raises(TypeError, match="may never mint a raw distance"):
            owner.set_proximity_context(minted)
    with pytest.raises(ValueError, match="unknown proximity context"):
        owner.set_proximity_context("very_narrow")

    # Every refusal left the gate exactly where it was.
    assert owner.policy == before
    assert owner.context is ProximityContext.INDOOR


def test_an_unknown_venue_gets_the_widest_profile() -> None:
    """The fail direction of an unknown space is MORE room, never less."""

    assert proximity_context_for_venue("go2_edu_plus") is ProximityContext.INDOOR
    for unknown in (None, "", "warehouse_x", "GO2_EDU_PLUS_v2"):
        assert proximity_context_for_venue(unknown) is ProximityContext.DEFAULT

    widest = resolve_proximity_profile(proximity_context_for_venue("warehouse_x"))
    assert widest == PREREGISTERED_PROXIMITY_PROFILES[ProximityContext.DEFAULT]
    assert widest.person_stop_m == max(
        profile.person_stop_m for profile in PREREGISTERED_PROXIMITY_PROFILES.values()
    )


def test_the_ladder_literals_still_match_their_stated_derivation() -> None:
    """A preregistration whose comment and number have parted company is a lie."""

    def up_to_5cm(metres: float) -> float:
        return math.ceil(metres * 20.0 - 1e-9) / 20.0

    narrow = PREREGISTERED_PROXIMITY_PROFILES[ProximityContext.NARROW]
    indoor = PREREGISTERED_PROXIMITY_PROFILES[ProximityContext.INDOOR]
    default = PREREGISTERED_PROXIMITY_PROFILES[ProximityContext.DEFAULT]

    assert narrow.person_stop_m == pytest.approx(up_to_5cm(PERSON_SOCIAL_ZONE_FLOOR_M))
    assert indoor.person_stop_m == pytest.approx(
        round((narrow.person_stop_m + default.person_stop_m) / 2.0 * 20.0) / 20.0
    )

    ratio = default.person_slow_m / default.person_stop_m
    for profile in (narrow, indoor):
        assert profile.person_slow_m == pytest.approx(up_to_5cm(profile.person_stop_m * ratio))

    # And the block awaiting the SHA re-pin preregisters the SAME ladder the
    # code ships, so landing it is a no-op rather than a second opinion.
    proposed = proposed_safety_section()["proximity_profiles"]
    for context, profile in PREREGISTERED_PROXIMITY_PROFILES.items():
        assert proposed[context.value]["person_stop_m"] == pytest.approx(profile.person_stop_m)
        assert proposed[context.value]["person_slow_m"] == pytest.approx(profile.person_slow_m)
