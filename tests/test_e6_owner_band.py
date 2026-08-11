"""Lane E6: the OWNER's comfort band is separated from the STRANGER's.

The claim under test, in one sentence: ``apply_reactive_safety`` now applies a
narrower *comfort* band to a positively-identified owner than to a stranger, and
**nothing else about the owner is relaxed** — the hard stop, the predictive
stop, the TTC brake and the collision gate are bit-identical for both.

Why the change exists: one 2.5 m social band applied to the owner throttled the
follow controller at every distance it operates at. Measured by lane E5 on
FOLLOW_BENCH_V1, ``person_slow_m`` 2.0 -> 2.5 alone dropped ``follow_success``
9/9 -> 6/9, including ``owner_turn_90``, a scenario with zero pedestrians. Full
factorial in ``scrum/20260809/task_15/E5_PERSON_CLEARANCE_STATUS.md`` §4 and the
owner-band factorial in ``E6_OWNER_BAND_STATUS.md``.

The two tests the card names explicitly are
``test_an_unidentified_person_receives_the_stranger_band`` (fail closed) and
``test_the_owners_hard_stop_is_bit_identical_to_a_strangers``.
"""

from __future__ import annotations

import math

import pytest

from parcel_robot.backends.base import OwnerTrack, RobotPose, SimObservation
from parcel_robot.models import VelocityCommand
from parcel_robot.navigation import reactive_safety as reactive_safety_module
from parcel_robot.navigation.follow import FollowConfig
from parcel_robot.navigation.reactive_safety import (
    OWNER_IDENTITY_CONFIDENCE_MIN,
    OWNER_STAND_OFF_MARGIN_M,
    ReactiveSafetyPolicy,
    _owner_identity_trusted,
    apply_reactive_safety,
)
from parcel_robot.navigation.search_owner import SearchOwnerConfig

#: A track the perception stack positively identified as the owner.
IDENTIFIED = OwnerTrack(owner_id="owner-1", visible=True, confidence=1.0)

NOW = 1.0
CRUISE = VelocityCommand(vx=0.35)


def _scene(
    *,
    owner: OwnerTrack,
    owner_center_m: float,
    stranger_m: float | None = None,
    stranger_bearing_rad: float | None = None,
    ttc_s: float | None = None,
) -> SimObservation:
    """Robot at the origin facing +x; owner dead ahead at ``owner_center_m``.

    A far obstacle is supplied because a translating command with no scan at all
    fails closed through the input-health join (P0-B), which would mask every
    person-band result.
    """

    return SimObservation(
        timestamp=NOW,
        robot=RobotPose(),
        owner=OwnerTrack(
            owner_id=owner.owner_id,
            x=owner_center_m,
            y=0.0,
            visible=owner.visible,
            confidence=owner.confidence,
        ),
        nearest_obstacle_m=10.0,
        nearest_obstacle_bearing_rad=0.0,
        nearest_person_m=stranger_m,
        nearest_person_bearing_rad=stranger_bearing_rad,
        nearest_person_ttc_s=ttc_s,
        backend="e6-owner-band",
    )


def _gate(observation: SimObservation, command: VelocityCommand = CRUISE):
    return apply_reactive_safety(command, observation, policy=POLICY, now=NOW)


POLICY = ReactiveSafetyPolicy()


def _center_for_clearance(clearance_m: float) -> float:
    return clearance_m + POLICY.owner_collision_envelope_m


# ---------------------------------------------------------------------------
# 1. The derivation
# ---------------------------------------------------------------------------


def test_the_owner_band_is_the_follow_stand_off_expressed_in_gate_coordinates() -> None:
    """Not a number: the controller's own stand-off, converted, exactly.

    The gate reasons in CLEARANCE (owner center distance minus the owner
    collision envelope) and the controller reasons in CENTER distance, so the
    envelope cancels and the owner band is ``person_stop_m`` plus the authority's
    stand-off margin. Asserted with ``==`` rather than ``approx``: the identity
    holds in IEEE-754 double, and an approximate match would let a re-tuned
    literal hide inside the tolerance.
    """

    follow = FollowConfig()

    assert POLICY.owner_slow_m == POLICY.person_stop_m + OWNER_STAND_OFF_MARGIN_M
    # ... and that ring, put back into center distance, IS the stand-off.
    assert POLICY.owner_slow_m + POLICY.owner_collision_envelope_m == (
        follow.desired_distance_m
    )
    # The margin the ramp occupies is the authority's, not a chosen one. This
    # one needs ``approx``, unlike the two above: 1.85 - 1.75 is 0.1 + 9e-17 in
    # binary, whereas the identities above are exact because both sides are the
    # same sum of the same doubles.
    assert OWNER_STAND_OFF_MARGIN_M == pytest.approx(
        follow.desired_distance_m - follow.owner_keepout_m
    )
    # Shipped values, stated once so a config retune is visible in this diff.
    assert (POLICY.person_stop_m, POLICY.person_slow_m) == (1.2, 2.5)
    assert POLICY.owner_slow_m == 1.3


def test_the_owner_band_is_derived_and_cannot_be_configured() -> None:
    """``owner_slow_m`` is a property, not a field: nothing can inject one."""

    assert "owner_slow_m" not in {field.name for field in ReactiveSafetyPolicy.__dataclass_fields__.values()}
    with pytest.raises(TypeError):
        ReactiveSafetyPolicy(owner_slow_m=2.0)  # type: ignore[call-arg]


def test_the_owner_band_is_never_wider_than_the_stranger_band() -> None:
    """Under an unusual commissioning the derivation is clamped, not inverted."""

    tight = ReactiveSafetyPolicy(person_slow_m=1.25)
    assert tight.person_stop_m + OWNER_STAND_OFF_MARGIN_M > tight.person_slow_m
    assert tight.owner_slow_m == tight.person_slow_m


def test_a_degenerate_stand_off_margin_is_a_construction_error() -> None:
    """The derivation must leave a real ramp, or the policy refuses to exist."""

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(reactive_safety_module, "OWNER_STAND_OFF_MARGIN_M", 0.0)
        with pytest.raises(ValueError, match="owner comfort band"):
            ReactiveSafetyPolicy()


def test_the_owner_identity_threshold_is_the_stacks_only_owner_threshold() -> None:
    """One answer to "is this track the owner?", shared by gate and controllers.

    The gate must never be *more* willing to believe a track than the controller
    that acts on it, and a fork between these three would be exactly that.
    """

    assert FollowConfig.min_confidence == OWNER_IDENTITY_CONFIDENCE_MIN
    assert SearchOwnerConfig.owner_confidence_min == OWNER_IDENTITY_CONFIDENCE_MIN


# ---------------------------------------------------------------------------
# 2. Identity: fail closed (the card's first named test)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("label", "owner"),
    [
        ("no confidence at all (the dataclass default)", OwnerTrack(visible=True)),
        (
            "confidence one ulp under the threshold",
            OwnerTrack(
                owner_id="owner-1",
                visible=True,
                confidence=math.nextafter(OWNER_IDENTITY_CONFIDENCE_MIN, 0.0),
            ),
        ),
        (
            "a plausible but unconfirmed detection",
            OwnerTrack(owner_id="owner-1", visible=True, confidence=0.5),
        ),
        (
            "an unlabeled track",
            OwnerTrack(owner_id="", visible=True, confidence=1.0),
        ),
        (
            "a whitespace label",
            OwnerTrack(owner_id="   ", visible=True, confidence=1.0),
        ),
        (
            "a non-finite confidence",
            OwnerTrack(owner_id="owner-1", visible=True, confidence=float("nan")),
        ),
    ],
)
def test_an_unidentified_person_receives_the_stranger_band(
    label: str, owner: OwnerTrack
) -> None:
    """FAIL CLOSED. Anything short of a positive identification is a stranger.

    Stated behaviourally, not by reading the predicate: at 1.65 m of clearance a
    positively-identified owner is outside the owner band and runs unthrottled,
    while every track in this table is inside the 2.5 m social band and is slowed
    by exactly the stranger ramp.
    """

    clearance = 1.65
    center = _center_for_clearance(clearance)
    assert POLICY.owner_slow_m < clearance < POLICY.person_slow_m

    trusted, trusted_state = _gate(_scene(owner=IDENTIFIED, owner_center_m=center))
    assert (trusted.vx, trusted_state) == (CRUISE.vx, "clear"), (
        "an identified owner outside the owner band must not be throttled"
    )

    gated, state = _gate(_scene(owner=owner, owner_center_m=center))
    stranger_scale = (clearance - POLICY.person_stop_m) / (
        POLICY.person_slow_m - POLICY.person_stop_m
    )
    assert state == "slowing", label
    assert gated.vx == pytest.approx(CRUISE.vx * stranger_scale), label
    assert not _owner_identity_trusted(_scene(owner=owner, owner_center_m=center).owner)


def test_the_owner_band_is_granted_only_on_the_owners_own_evidence() -> None:
    """No proxy for identity: "nearest person" never buys the relaxed band.

    A stranger standing exactly where the owner would be gets the social band.
    """

    center = _center_for_clearance(1.65)
    stranger_only = SimObservation(
        timestamp=NOW,
        robot=RobotPose(),
        owner=OwnerTrack(visible=False),
        nearest_obstacle_m=10.0,
        nearest_obstacle_bearing_rad=0.0,
        nearest_person_m=1.65,
        nearest_person_bearing_rad=0.0,
        backend="e6-owner-band",
    )
    gated, state = apply_reactive_safety(
        CRUISE, stranger_only, policy=POLICY, now=NOW
    )
    assert state == "slowing"
    assert gated.vx < CRUISE.vx
    assert center > 0.0  # geometry sanity: the scene is the same ring


# ---------------------------------------------------------------------------
# 3. The hard stop is NOT relaxed (the card's second named test)
# ---------------------------------------------------------------------------


def _measured_stop_ring_m(owner: OwnerTrack, command: VelocityCommand) -> float:
    """Bisect the gate's own verdict for the clearance at which it stops."""

    def stops(clearance_m: float) -> bool:
        observation = _scene(owner=owner, owner_center_m=_center_for_clearance(clearance_m))
        _, state = apply_reactive_safety(command, observation, policy=POLICY, now=NOW)
        return state == "stopped"

    low, high = 0.5, 2.4
    assert stops(low) and not stops(high)
    for _ in range(80):
        middle = (low + high) / 2.0
        if stops(middle):
            low = middle
        else:
            high = middle
    return high


def test_the_owners_hard_stop_is_bit_identical_to_a_strangers() -> None:
    """1.2 m of clearance stops the robot, owner or not. MEASURED, not asserted.

    The stop ring is found by bisecting the gate's own verdict rather than by
    restating the constant, so a relaxation hidden anywhere in the stop path —
    the ring, the predictive term, or the new identity branch — shows up here as
    a moved number. Run at two speeds, because the ring is speed-dependent and a
    relaxation could have been hidden in the speed term alone.
    """

    stranger_shaped = OwnerTrack(owner_id="owner-1", visible=True, confidence=0.1)
    assert not _owner_identity_trusted(stranger_shaped)

    for command in (VelocityCommand(vx=1e-4), CRUISE, VelocityCommand(vx=0.6)):
        expected = POLICY.person_stop_m + command.vx * POLICY.reaction_time_s
        owner_ring = _measured_stop_ring_m(IDENTIFIED, command)
        stranger_ring = _measured_stop_ring_m(stranger_shaped, command)
        assert owner_ring == stranger_ring, command
        assert owner_ring == pytest.approx(expected, abs=1e-9), command

    # And the plain statement of the same fact at the slowest speed the gate
    # still counts as translating (``_translating`` ignores anything under
    # 1e-6 m/s): the ring is ``person_stop_m`` itself, for an identified owner.
    at_ring = _scene(owner=IDENTIFIED, owner_center_m=_center_for_clearance(POLICY.person_stop_m))
    _, state = apply_reactive_safety(VelocityCommand(vx=1e-5), at_ring, policy=POLICY, now=NOW)
    assert state == "stopped"


@pytest.mark.parametrize(
    "owner",
    [IDENTIFIED, OwnerTrack(owner_id="owner-1", visible=True, confidence=0.1)],
    ids=["identified-owner", "unidentified-person"],
)
def test_the_predictive_stop_still_scales_with_speed_for_the_owner(
    owner: OwnerTrack,
) -> None:
    """The speed-dependent stop margin is not part of the relaxation."""

    predictive = POLICY.person_stop_m + CRUISE.vx * POLICY.reaction_time_s
    assert predictive > POLICY.person_stop_m

    inside = _scene(owner=owner, owner_center_m=_center_for_clearance(predictive - 1e-6))
    _, state = _gate(inside)
    assert state == "stopped"


@pytest.mark.parametrize(
    "owner",
    [IDENTIFIED, OwnerTrack(visible=True)],
    ids=["identified-owner", "unidentified-person"],
)
def test_the_ttc_brake_does_not_know_about_identity(owner: OwnerTrack) -> None:
    """TTC is untouched: an imminent contact stops the base either way."""

    scene = _scene(
        owner=owner,
        owner_center_m=_center_for_clearance(3.0),
        ttc_s=0.5,
    )
    _, state = _gate(scene)
    assert state == "stopped"


# ---------------------------------------------------------------------------
# 4. The third-party interlock
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("stranger_m", [1.0, 2.49, 2.51, 10.0, 40.0])
def test_any_perceived_stranger_takes_the_relaxation_away(stranger_m: float) -> None:
    """The relaxation is a two-body contract; ANY bystander ends it.

    Presence, not range — including a stranger 40 m away, far outside every band
    in the policy. The stranger here is also BEHIND the robot, so the stranger's
    own band cannot be what slows the command (``_toward`` is false for it): the
    only thing that can slow it is the owner entry losing its relaxed band.

    The range-based version of this interlock was measured and rejected; see
    ``_owner_comfort_band_m`` and E6_OWNER_BAND_STATUS.md §4.
    """

    center = _center_for_clearance(1.65)

    alone, alone_state = _gate(_scene(owner=IDENTIFIED, owner_center_m=center))
    assert (alone.vx, alone_state) == (CRUISE.vx, "clear")

    accompanied, state = _gate(
        _scene(
            owner=IDENTIFIED,
            owner_center_m=center,
            stranger_m=stranger_m,
            stranger_bearing_rad=math.pi,
        )
    )
    assert state == "slowing"
    assert accompanied.vx == pytest.approx(
        CRUISE.vx
        * (1.65 - POLICY.person_stop_m)
        / (POLICY.person_slow_m - POLICY.person_stop_m)
    )


def test_the_band_decision_is_exhaustive_and_one_directional() -> None:
    """Every input combination returns one of two values, and the relaxed one
    requires BOTH a positive identification and a scene with nobody else in it.

    The second assertion is the invariant that makes the whole change safe to
    reason about: whatever the inputs, the band handed to the ramp is strictly
    outside the shared stop ring and never wider than a stranger's.
    """

    band = reactive_safety_module._owner_comfort_band_m
    center = _center_for_clearance(1.65)
    for identified in (True, False):
        for stranger in (None, 1.0, 2.49, 2.51, 10.0):
            owner = IDENTIFIED if identified else OwnerTrack(visible=True)
            scene = _scene(
                owner=owner,
                owner_center_m=center,
                stranger_m=stranger,
                stranger_bearing_rad=0.0 if stranger is not None else None,
            )
            value = band(scene, POLICY)
            alone = stranger is None
            expected = POLICY.owner_slow_m if (identified and alone) else POLICY.person_slow_m
            assert value == expected, (identified, stranger)
            assert POLICY.person_stop_m < value <= POLICY.person_slow_m


# ---------------------------------------------------------------------------
# 5. Nothing else moved
# ---------------------------------------------------------------------------


def test_the_stranger_band_is_untouched_at_every_distance() -> None:
    """The stranger ramp is the same function it was before the separation."""

    for clearance in (1.25, 1.5, 2.0, 2.4, 2.49):
        scene = SimObservation(
            timestamp=NOW,
            robot=RobotPose(),
            owner=OwnerTrack(visible=False),
            nearest_obstacle_m=10.0,
            nearest_obstacle_bearing_rad=0.0,
            nearest_person_m=clearance,
            nearest_person_bearing_rad=0.0,
            backend="e6-owner-band",
        )
        gated, state = apply_reactive_safety(CRUISE, scene, policy=POLICY, now=NOW)
        expected = max(
            0.15,
            (clearance - POLICY.person_stop_m)
            / (POLICY.person_slow_m - POLICY.person_stop_m),
        )
        assert state == "slowing"
        assert gated.vx == pytest.approx(CRUISE.vx * expected)


def test_an_invisible_owner_is_not_in_the_people_list_at_all() -> None:
    """Unchanged pre-existing behaviour, restated so the new branch cannot own it."""

    scene = _scene(
        owner=OwnerTrack(owner_id="owner-1", visible=False, confidence=1.0),
        owner_center_m=_center_for_clearance(0.1),
    )
    gated, state = _gate(scene)
    assert (gated.vx, state) == (CRUISE.vx, "clear")
