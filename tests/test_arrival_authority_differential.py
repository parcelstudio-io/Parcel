"""Differential arrival authority + the ``false_arrival`` class (U32, W0-B/C).

The rule under test, stated once: the scorer's ``GoalRegion`` predicate is a
*derived view* of arrival, not a peer of the navigator, so the invariant is
one-way — ``scorer_arrival ⇒ system_arrival``. Both verdicts are recorded on
every episode; the four (dis)agreement outcomes are named; and a claim that the
predicate contradicts is ``false_arrival``, never ``planning_error``.

The load-bearing safety property is at the bottom: adding the claim as a scorer
input can change *which failure* an episode is attributed to, and can never
change whether it succeeded.
"""

from __future__ import annotations

import math

import pytest

from parcel_robot.instructnav.scoring import (
    ARRIVAL_BOUNDARY_EPSILON_M,
    AttributionLayer,
    AuthorityCategory,
    FailureClass,
    GoalRegion,
    differential_arrival_verdict,
    score_episode,
    system_arrival_claim,
)

DISC = GoalRegion(kind="disc", center=(0.0, 0.0), radius_m=1.0)
POLY = GoalRegion(
    kind="polygon",
    polygon=((-1.0, -1.0), (1.0, -1.0), (1.0, 1.0), (-1.0, 1.0)),
)
BAND = GoalRegion(
    kind="relative_band",
    center=(0.0, 0.0),
    band_m=(1.0, 2.0),
    anchor_footprint_m=0.3,
)


def _trace(*points, stopped: bool = True):
    return [
        {"t_s": 0.1 * i, "x": x, "y": y, "stopped": stopped, "attempted": True}
        for i, (x, y) in enumerate(points)
    ]


# --------------------------------------------------------------- signed margin
def test_signed_distance_is_negative_inside_and_positive_outside() -> None:
    assert DISC.signed_distance_to_boundary(0.0, 0.0) == pytest.approx(-1.0)
    assert DISC.signed_distance_to_boundary(1.5, 0.0) == pytest.approx(0.5)
    assert DISC.signed_distance_to_boundary(1.0, 0.0) == pytest.approx(0.0)

    assert POLY.signed_distance_to_boundary(0.0, 0.0) == pytest.approx(-1.0)
    assert POLY.signed_distance_to_boundary(0.0, 0.9) == pytest.approx(-0.1)
    assert POLY.signed_distance_to_boundary(0.0, 1.2) == pytest.approx(0.2)


def test_signed_distance_on_a_band_measures_the_nearest_edge() -> None:
    # Inside the annulus, closer to the inner edge.
    assert BAND.signed_distance_to_boundary(1.2, 0.0) == pytest.approx(-0.2)
    # Inside, closer to the outer edge.
    assert BAND.signed_distance_to_boundary(1.9, 0.0) == pytest.approx(-0.1)
    # Outside, inner side and outer side.
    assert BAND.signed_distance_to_boundary(0.5, 0.0) == pytest.approx(0.5)
    assert BAND.signed_distance_to_boundary(2.5, 0.0) == pytest.approx(0.5)


def test_signed_distance_agrees_with_contains_at_every_sign() -> None:
    for goal, anchor in ((DISC, None), (POLY, None), (BAND, (0.0, 0.0))):
        for x in [i * 0.13 for i in range(-25, 26)]:
            for y in [j * 0.17 for j in range(-15, 16)]:
                margin = goal.signed_distance_to_boundary(x, y, anchor_xy=anchor)
                if abs(margin) < 1e-9:
                    continue  # exactly on the boundary — either verdict is fine
                assert goal.contains(x, y, anchor_xy=anchor) == (margin < 0.0)


# ------------------------------------------------------------------ the claim
def test_only_real_arrival_claims_count_as_claims() -> None:
    assert system_arrival_claim("arrived", "arrived_verified") is True
    assert system_arrival_claim("completed", "at_follow_distance") is True
    assert system_arrival_claim("succeeded", "") is True
    # A follow that is still tracking has asserted nothing about arrival.
    assert system_arrival_claim("completed", "tracking_owner") is False
    assert system_arrival_claim("timed_out", "spatial_step_limit") is False
    assert system_arrival_claim("failed", "semantic_target_not_found") is False
    assert system_arrival_claim(None, None) is False


# ------------------------------------------------------------ verdict matrix
def test_agreement_when_both_authorities_say_the_same_thing() -> None:
    both = differential_arrival_verdict(DISC, (0.0, 0.0), system_arrival=True)
    assert both.category is AuthorityCategory.AGREEMENT
    neither = differential_arrival_verdict(DISC, (5.0, 0.0), system_arrival=False)
    assert neither.category is AuthorityCategory.AGREEMENT


def test_claim_far_outside_the_region_is_a_false_arrival() -> None:
    verdict = differential_arrival_verdict(DISC, (4.2, 0.0), system_arrival=True)
    assert verdict.category is AuthorityCategory.FALSE_ARRIVAL
    assert verdict.scorer_arrival is False
    assert verdict.system_arrival is True
    assert verdict.distance_to_goal_m == pytest.approx(3.2)


def test_predicate_without_a_claim_is_an_authority_disagreement() -> None:
    """``scorer_arrival ⇒ system_arrival`` is the invariant; this violates it."""

    verdict = differential_arrival_verdict(DISC, (0.0, 0.0), system_arrival=False)
    assert verdict.scorer_arrival is True
    assert verdict.system_arrival is False
    assert verdict.category is AuthorityCategory.AUTHORITY_DISAGREEMENT
    # Well inside, so it is a real split rather than boundary quantisation.
    assert verdict.boundary_margin_m == pytest.approx(-1.0)
    assert verdict.distance_to_goal_m == 0.0
    # It is emphatically NOT a false arrival: nothing untrue was asserted.
    assert verdict.category is not AuthorityCategory.FALSE_ARRIVAL


def test_boundary_zone_is_tolerated_on_both_sides() -> None:
    eps = ARRIVAL_BOUNDARY_EPSILON_M
    # Just outside, claimed: quantisation, not a false arrival.
    outside = differential_arrival_verdict(
        DISC, (1.0 + eps / 2.0, 0.0), system_arrival=True
    )
    assert outside.category is AuthorityCategory.TOLERATED_BOUNDARY
    # Just inside, unclaimed: quantisation, not a disagreement.
    inside = differential_arrival_verdict(
        DISC, (1.0 - eps / 2.0, 0.0), system_arrival=False
    )
    assert inside.category is AuthorityCategory.TOLERATED_BOUNDARY


def test_beyond_the_boundary_zone_the_split_is_named() -> None:
    eps = ARRIVAL_BOUNDARY_EPSILON_M
    outside = differential_arrival_verdict(DISC, (1.0 + eps * 4, 0.0), system_arrival=True)
    assert outside.category is AuthorityCategory.FALSE_ARRIVAL
    inside = differential_arrival_verdict(DISC, (1.0 - eps * 4, 0.0), system_arrival=False)
    assert inside.category is AuthorityCategory.AUTHORITY_DISAGREEMENT


def test_missing_system_verdict_is_unknown_never_a_fabricated_agreement() -> None:
    verdict = differential_arrival_verdict(DISC, (0.0, 0.0), system_arrival=None)
    assert verdict.category is AuthorityCategory.UNKNOWN
    assert verdict.system_arrival is None
    assert verdict.scorer_arrival is True


def test_epsilon_must_be_finite_and_non_negative() -> None:
    with pytest.raises(ValueError):
        differential_arrival_verdict(
            DISC, (0.0, 0.0), system_arrival=True, epsilon_m=-0.1
        )
    with pytest.raises(ValueError):
        differential_arrival_verdict(
            DISC, (0.0, 0.0), system_arrival=True, epsilon_m=math.inf
        )


# -------------------------------------------------------- scorer integration
def test_a_claim_outside_the_region_scores_false_arrival_not_planning_error() -> None:
    """The U32 shape: mission says arrived, K0 says 3.2 m away."""

    trace = _trace((0.0, 0.0), (2.0, 0.0), (4.2, 0.0))
    score = score_episode(
        trace,
        DISC,
        shortest_path_m=4.0,
        max_time_s=20.0,
        arrival_hold_s=1.0,
        system_arrival=True,
    )
    assert score.success is False
    assert score.failure is FailureClass.FALSE_ARRIVAL
    assert score.failure is not FailureClass.PLANNING_ERROR
    assert score.attribution_layer is AttributionLayer.L6_TERMINATION
    assert score.authority_category is AuthorityCategory.FALSE_ARRIVAL
    assert "claim_without_predicate" in score.detail
    assert "3.2" in score.detail


def test_the_same_trace_without_a_claim_stays_a_planning_error() -> None:
    trace = _trace((0.0, 0.0), (2.0, 0.0), (4.2, 0.0))
    score = score_episode(trace, DISC, shortest_path_m=4.0, max_time_s=20.0)
    assert score.failure is FailureClass.PLANNING_ERROR
    assert score.authority_category is AuthorityCategory.UNKNOWN


def test_a_claim_the_predicate_supports_is_not_a_false_arrival() -> None:
    trace = _trace((3.0, 0.0), (1.5, 0.0), (0.0, 0.0))
    score = score_episode(
        trace,
        DISC,
        shortest_path_m=3.0,
        max_time_s=20.0,
        arrival_hold_s=0.0,
        system_arrival=True,
    )
    assert score.success is True
    assert score.failure is FailureClass.NONE
    assert score.authority_category is AuthorityCategory.AGREEMENT


def test_a_claim_inside_the_boundary_zone_is_never_a_false_arrival() -> None:
    eps = ARRIVAL_BOUNDARY_EPSILON_M
    trace = _trace((3.0, 0.0), (1.0 + eps / 2.0, 0.0))
    score = score_episode(
        trace,
        DISC,
        shortest_path_m=2.0,
        max_time_s=20.0,
        arrival_hold_s=1.0,
        system_arrival=True,
    )
    assert score.failure is not FailureClass.FALSE_ARRIVAL
    assert score.authority_category is AuthorityCategory.TOLERATED_BOUNDARY


def test_the_claim_can_be_read_from_an_explicit_trace_flag() -> None:
    trace = _trace((0.0, 0.0), (4.2, 0.0))
    trace[-1]["system_arrival"] = True
    score = score_episode(trace, DISC, shortest_path_m=4.0, max_time_s=20.0)
    assert score.failure is FailureClass.FALSE_ARRIVAL


def test_free_text_notes_are_never_sniffed_for_a_claim() -> None:
    """Only explicit booleans count, so history cannot be reclassified by prose."""

    trace = _trace((0.0, 0.0), (4.2, 0.0))
    trace[-1]["note"] = "arrived_verified"
    score = score_episode(trace, DISC, shortest_path_m=4.0, max_time_s=20.0)
    assert score.authority_category is AuthorityCategory.UNKNOWN
    assert score.failure is FailureClass.PLANNING_ERROR


def test_a_collision_still_outranks_a_false_arrival() -> None:
    """Safety beats attribution — the precedence rule this module already had."""

    trace = _trace((0.0, 0.0), (4.2, 0.0))
    trace[-1]["collision"] = True
    score = score_episode(
        trace, DISC, shortest_path_m=4.0, max_time_s=20.0, system_arrival=True
    )
    assert score.failure is FailureClass.CONTROL_ERROR


# ----------------------------------------------------------- safety property
@pytest.mark.parametrize("hold_s", [0.0, 1.0])
@pytest.mark.parametrize("claim", [True, False, None])
def test_the_arrival_claim_can_never_change_success(hold_s: float, claim) -> None:
    """Property: the claim is an attribution input only.

    Swept over traces that succeed, that stop just outside, that never stop, and
    that never move — under both hold conventions the runner uses.
    """

    traces = [
        _trace((3.0, 0.0), (1.0, 0.0), (0.0, 0.0), (0.0, 0.0)),
        _trace((3.0, 0.0), (1.2, 0.0)),
        _trace((3.0, 0.0), (0.0, 0.0), stopped=False),
        _trace((0.0, 0.0)),
        _trace((5.0, 5.0)),
    ]
    for trace in traces:
        reference = score_episode(
            trace, DISC, shortest_path_m=3.0, max_time_s=20.0, arrival_hold_s=hold_s
        )
        with_claim = score_episode(
            trace,
            DISC,
            shortest_path_m=3.0,
            max_time_s=20.0,
            arrival_hold_s=hold_s,
            system_arrival=claim,
        )
        assert with_claim.success == reference.success
        assert with_claim.spl == reference.spl
        assert with_claim.distance_to_goal_m == reference.distance_to_goal_m
        assert with_claim.time_to_goal_s == reference.time_to_goal_s


# ------------------------------------------------- voice_nav_e2e evidence path
# The e2e suite itself is ``-m slow`` and drives a live sim, so its evidence
# helpers are exercised here against synthetic evidence dicts — the recording
# and the gate are pure functions and must not need a robot to be verified.
def _voice_module():
    import sys
    from pathlib import Path

    tests_dir = str(Path(__file__).resolve().parent)
    if tests_dir not in sys.path:
        sys.path.insert(0, tests_dir)
    import test_voice_nav_e2e

    return test_voice_nav_e2e


def test_voice_evidence_records_both_verdicts_and_the_category() -> None:
    voice = _voice_module()
    evidence = {"end": (4.2, 0.0), "system_arrival": True}
    verdict = voice._score_arrival_authority(evidence, DISC)
    assert evidence["scorer_arrival"] is False
    assert evidence["system_arrival"] is True
    assert evidence["authority_category"] == AuthorityCategory.FALSE_ARRIVAL.value
    assert evidence["arrival_authority"]["distance_to_goal_m"] == pytest.approx(3.2)
    assert verdict.category is AuthorityCategory.FALSE_ARRIVAL


def test_voice_agreement_gate_rejects_both_disagreement_directions() -> None:
    voice = _voice_module()
    for pose, claim in (((4.2, 0.0), True), ((0.0, 0.0), False)):
        evidence = {"end": pose, "system_arrival": claim}
        voice._score_arrival_authority(evidence, DISC)
        with pytest.raises(AssertionError, match="arrival authorities disagree"):
            voice._assert_authorities_agree(evidence)


def test_voice_agreement_gate_passes_when_both_authorities_arrive() -> None:
    voice = _voice_module()
    evidence = {"end": (0.0, 0.0), "system_arrival": True}
    voice._score_arrival_authority(evidence, DISC)
    voice._assert_authorities_agree(evidence)  # must not raise


def test_a_success_can_never_be_classified_as_a_false_arrival() -> None:
    trace = _trace((3.0, 0.0), (0.0, 0.0), (0.0, 0.0))
    score = score_episode(
        trace,
        DISC,
        shortest_path_m=3.0,
        max_time_s=20.0,
        arrival_hold_s=0.0,
        system_arrival=True,
    )
    assert score.success is True
    assert score.failure is FailureClass.NONE
