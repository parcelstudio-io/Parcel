"""Focused contract tests for the default-off SOCIAL-PROGRESS-1 leaf."""

from __future__ import annotations

from dataclasses import fields, replace

import pytest

from parcel_robot.contracts.navigation_snapshot_v2 import DynamicTrackV2
from parcel_robot.navigation.social_progress import (
    MAX_PUBLIC_INTEGER,
    MAX_TRACK_CLASS_ID_CHARS,
    MAX_TRACK_COVARIANCE_ENTRIES,
    MAX_TRACK_ID_CHARS,
    CrosswalkPhaseV1,
    ElevatorPhaseV1,
    PassingSideV1,
    SemanticContextV1,
    SocialBlockCauseV1,
    SocialLivenessV1,
    SocialProgressConfigV1,
    SocialProgressDecisionV1,
    SocialProgressMemoryV1,
    SocialProgressObservationV1,
    SocialProgressStateV1,
    SocialProposalV1,
    SocialTrackEvidenceV1,
    SocialVenueV1,
    VisibilityEvidenceV1,
    VisibilityStateV1,
    decide_social_progress,
    decide_social_progress_observation,
)

NOW = 10.0
ENABLED = SocialProgressConfigV1(enabled=True)
SIDEWALK = SemanticContextV1(venue=SocialVenueV1.SIDEWALK)
PROGRESS_REQUESTED = SocialLivenessV1(progress_requested=True)


def _visibility(
    evidence_id: str,
    state: VisibilityStateV1,
    *,
    source_s: float = 9.9,
) -> VisibilityEvidenceV1:
    if state is VisibilityStateV1.EXPLICIT_FREE:
        return VisibilityEvidenceV1(
            evidence_id=evidence_id,
            visibility=state,
            source_monotonic_s=source_s,
            receive_monotonic_s=source_s + 0.02,
            corridor_fully_observed=True,
            corridor_coverage=1.0,
            lidar_clear_evidence_refs=(f"ray:{evidence_id}",),
        )
    return VisibilityEvidenceV1(
        evidence_id=evidence_id,
        visibility=state,
        source_monotonic_s=source_s,
        receive_monotonic_s=source_s + 0.02,
        camera_evidence_refs=(f"camera:{evidence_id}",),
    )


def _track(
    state: VisibilityStateV1,
    *,
    risk: float = 0.8,
    hard: bool = False,
    source_s: float = 9.9,
    track_id: str = "person-1",
) -> SocialTrackEvidenceV1:
    return SocialTrackEvidenceV1(
        track=DynamicTrackV2(
            track_id=track_id,
            class_id="person",
            x=1.0,
            y=0.0,
            radius_m=0.3,
            confidence=0.9,
            covariance=(0.1, 0.0, 0.0, 0.1),
        ),
        existence_probability=0.9,
        visibility_evidence=_visibility(f"track:{track_id}", state, source_s=source_s),
        in_swept_corridor=True,
        risk_upper_bound=risk,
        within_hard_envelope=hard,
        owner_identity_lineage=("association:7",),
    )


def _decide(
    *,
    tracks: tuple[SocialTrackEvidenceV1, ...] = (),
    corridor: VisibilityEvidenceV1 | None = None,
    semantics: SemanticContextV1 = SIDEWALK,
    liveness: SocialLivenessV1 = PROGRESS_REQUESTED,
    memory: SocialProgressMemoryV1 | None = None,
    config: SocialProgressConfigV1 = ENABLED,
) -> SocialProgressDecisionV1:
    return decide_social_progress(
        now_monotonic_s=NOW,
        tracks=tracks,
        corridor_evidence=corridor,
        semantics=semantics,
        liveness=liveness,
        memory=memory,
        config=config,
    )


def test_feature_is_default_off_and_cannot_authorize_motion() -> None:
    decision = decide_social_progress(
        now_monotonic_s=NOW,
        tracks=(),
        corridor_evidence=None,
        semantics=SemanticContextV1(venue=SocialVenueV1.SIDEWALK),
        liveness=SocialLivenessV1(progress_requested=True),
    )

    assert decision.state is SocialProgressStateV1.TRACK
    assert decision.cause is SocialBlockCauseV1.FEATURE_DISABLED
    assert decision.proposal is SocialProposalV1.NONE
    assert decision.authorizes_motion is False
    assert decision.requires_downstream_safety_gate is True
    names = {item.name for item in fields(SocialProgressDecisionV1)}
    assert not names.intersection({"velocity", "vx", "vy", "yaw_rate", "command"})


def test_strict_config_mapping_keeps_missing_and_empty_sections_disabled() -> None:
    assert not SocialProgressConfigV1.from_mapping(None).enabled
    assert not SocialProgressConfigV1.from_mapping({}).enabled
    assert SocialProgressConfigV1.from_mapping({"enabled": True}).enabled

    with pytest.raises(TypeError, match="enabled must be a boolean"):
        SocialProgressConfigV1.from_mapping({"enabled": "false"})
    with pytest.raises(TypeError, match="enabled must be a boolean"):
        SocialProgressConfigV1.from_mapping({"enabled": 0})
    with pytest.raises(ValueError, match="unknown social progress config keys"):
        SocialProgressConfigV1.from_mapping({"enable": True})


def test_public_integer_contract_accepts_exact_unsigned_64_bit_maximum() -> None:
    config = SocialProgressConfigV1(
        clear_streak_required=MAX_PUBLIC_INTEGER,
        initial_recovery_budget=MAX_PUBLIC_INTEGER,
    )
    memory = SocialProgressMemoryV1(
        release_certificate_required=True,
        clear_streak=MAX_PUBLIC_INTEGER,
        last_clear_evidence_id="🐕" * 128,
        recovery_budget_remaining=MAX_PUBLIC_INTEGER,
    )
    decision = replace(
        _decide(),
        blocker_id="🐾" * 128,
        clear_streak=MAX_PUBLIC_INTEGER,
        recovery_budget_remaining=MAX_PUBLIC_INTEGER,
        next_memory=memory,
    )

    assert config.clear_streak_required == MAX_PUBLIC_INTEGER
    assert config.initial_recovery_budget == MAX_PUBLIC_INTEGER
    assert decision.clear_streak == MAX_PUBLIC_INTEGER
    assert decision.next_memory.recovery_budget_remaining == MAX_PUBLIC_INTEGER


def test_public_integer_contract_rejects_max_plus_one_and_hostile_huge_values() -> None:
    base = _decide()
    builders = (
        lambda value: SocialProgressConfigV1(clear_streak_required=value),
        lambda value: SocialProgressConfigV1(initial_recovery_budget=value),
        lambda value: SocialProgressMemoryV1(
            release_certificate_required=True,
            clear_streak=value,
        ),
        lambda value: SocialProgressMemoryV1(recovery_budget_remaining=value),
        lambda value: replace(base, clear_streak=value),
        lambda value: replace(base, recovery_budget_remaining=value),
    )

    for overbound in (MAX_PUBLIC_INTEGER + 1, 10**5000):
        for build in builders:
            with pytest.raises(ValueError, match="must be in"):
                build(overbound)


def test_retained_decision_identifiers_are_bounded() -> None:
    base = _decide()
    assert replace(base, blocker_id="🐕" * 128).blocker_id is not None
    assert (
        SocialProgressMemoryV1(last_clear_evidence_id="🐾" * 128).last_clear_evidence_id is not None
    )

    with pytest.raises(ValueError, match="blocker_id"):
        replace(base, blocker_id="🐕" * 129)
    with pytest.raises(ValueError, match="last_clear_evidence_id"):
        SocialProgressMemoryV1(last_clear_evidence_id="🐾" * 129)


def test_grouped_observation_prevents_future_or_cross_tick_evidence() -> None:
    observation = SocialProgressObservationV1(
        now_monotonic_s=NOW,
        tracks=(),
        corridor_evidence=None,
        semantics=SIDEWALK,
        liveness=PROGRESS_REQUESTED,
    )
    assert decide_social_progress_observation(observation, config=ENABLED).state is (
        SocialProgressStateV1.TRACK
    )

    with pytest.raises(ValueError, match="after observation time"):
        SocialProgressObservationV1(
            now_monotonic_s=NOW,
            tracks=(),
            corridor_evidence=_visibility(
                "future",
                VisibilityStateV1.EXPLICIT_FREE,
                source_s=NOW + 1.0,
            ),
            semantics=SIDEWALK,
            liveness=PROGRESS_REQUESTED,
        )


def test_absent_tracks_do_not_require_a_certificate_before_any_block() -> None:
    decision = _decide()

    assert decision.state is SocialProgressStateV1.TRACK
    assert decision.resume_eligible is False


def test_visible_hard_block_sets_release_certificate_latch() -> None:
    decision = _decide(tracks=(_track(VisibilityStateV1.VISIBLE, hard=True),))

    assert decision.state is SocialProgressStateV1.HOLD_OCCUPIED
    assert decision.cause is SocialBlockCauseV1.TRUE_DYNAMIC_BLOCK
    assert decision.blocker_id == "person-1"
    assert decision.next_memory.release_certificate_required
    assert not decision.resume_eligible


@pytest.mark.parametrize(
    ("visibility", "cause"),
    [
        (VisibilityStateV1.OCCLUDED, SocialBlockCauseV1.UNCERTAIN_OCCLUSION),
        (VisibilityStateV1.OUT_OF_FOV, SocialBlockCauseV1.OUT_OF_FOV),
        (VisibilityStateV1.STALE, SocialBlockCauseV1.STALE_SENSOR),
    ],
)
def test_non_disproving_visibility_holds_conservatively(
    visibility: VisibilityStateV1,
    cause: SocialBlockCauseV1,
) -> None:
    decision = _decide(tracks=(_track(visibility),))

    assert decision.state is SocialProgressStateV1.HOLD_UNCERTAIN
    assert decision.cause is cause
    assert decision.next_memory.clear_streak == 0


def test_track_disappearance_alone_does_not_release_a_previous_hold() -> None:
    memory = SocialProgressMemoryV1(
        prior_state=SocialProgressStateV1.HOLD_OCCUPIED,
        release_certificate_required=True,
    )

    decision = _decide(memory=memory)

    assert decision.state is SocialProgressStateV1.HOLD_UNCERTAIN
    assert decision.cause is SocialBlockCauseV1.CLEAR_STREAK_INCOMPLETE
    assert not decision.resume_eligible


def test_two_distinct_fresh_clear_bundles_are_required_for_probe() -> None:
    held = SocialProgressMemoryV1(
        prior_state=SocialProgressStateV1.HOLD_OCCUPIED,
        release_certificate_required=True,
    )
    first = _decide(memory=held, corridor=_visibility("clear-1", VisibilityStateV1.EXPLICIT_FREE))
    repeated = _decide(
        memory=first.next_memory,
        corridor=_visibility("clear-1", VisibilityStateV1.EXPLICIT_FREE),
    )
    second = _decide(
        memory=repeated.next_memory,
        corridor=_visibility("clear-2", VisibilityStateV1.EXPLICIT_FREE),
    )

    assert first.clear_streak == 1
    assert repeated.clear_streak == 1, "reusing one bundle must not manufacture a streak"
    assert not repeated.resume_eligible
    assert second.state is SocialProgressStateV1.PROBE_RESUME
    assert second.resume_eligible
    assert second.proposal is SocialProposalV1.PROBE_RESUME_CANDIDATE
    assert second.authorizes_motion is False


def test_stale_clear_bundle_resets_the_streak_and_fails_closed() -> None:
    memory = SocialProgressMemoryV1(
        prior_state=SocialProgressStateV1.HOLD_UNCERTAIN,
        release_certificate_required=True,
        clear_streak=1,
        last_clear_evidence_id="clear-1",
    )

    decision = _decide(
        memory=memory,
        corridor=_visibility("clear-2", VisibilityStateV1.EXPLICIT_FREE, source_s=9.0),
    )

    assert decision.state is SocialProgressStateV1.HOLD_UNCERTAIN
    assert decision.cause is SocialBlockCauseV1.STALE_SENSOR
    assert decision.clear_streak == 0


def test_probe_is_revoked_immediately_by_occluded_track() -> None:
    probing = SocialProgressMemoryV1(
        prior_state=SocialProgressStateV1.PROBE_RESUME,
        release_certificate_required=True,
        clear_streak=2,
        last_clear_evidence_id="clear-2",
    )

    decision = _decide(
        memory=probing,
        tracks=(_track(VisibilityStateV1.OCCLUDED),),
        corridor=_visibility("clear-3", VisibilityStateV1.EXPLICIT_FREE),
    )

    assert decision.state is SocialProgressStateV1.HOLD_UNCERTAIN
    assert decision.clear_streak == 0
    assert not decision.resume_eligible


def test_stable_progress_closes_probe_latch_and_resets_budget() -> None:
    probing = SocialProgressMemoryV1(
        prior_state=SocialProgressStateV1.PROBE_RESUME,
        release_certificate_required=True,
        clear_streak=2,
        last_clear_evidence_id="clear-2",
        recovery_budget_remaining=1,
    )

    decision = _decide(
        memory=probing,
        corridor=_visibility("clear-3", VisibilityStateV1.EXPLICIT_FREE),
        liveness=SocialLivenessV1(
            progress_requested=True,
            stable_progress_confirmed=True,
        ),
    )

    assert decision.state is SocialProgressStateV1.TRACK
    assert not decision.next_memory.release_certificate_required
    assert decision.recovery_budget_remaining == ENABLED.initial_recovery_budget


def test_crosswalk_entry_holds_without_independent_authority() -> None:
    context = SemanticContextV1(
        venue=SocialVenueV1.CROSSWALK,
        crosswalk_phase=CrosswalkPhaseV1.COMMIT_CROSS,
        candidate_enters_resource=True,
        owner_committed=True,
        exit_visible_and_feasible=True,
        sufficient_crossing_time=True,
        traffic_authority_confirmed=False,
    )

    decision = _decide(semantics=context)

    assert decision.state is SocialProgressStateV1.HOLD_SEMANTIC
    assert decision.cause is SocialBlockCauseV1.CROSSWALK_AUTHORITY


def test_crosswalk_entry_can_only_be_proposed_when_every_semantic_fact_is_true() -> None:
    context = SemanticContextV1(
        venue=SocialVenueV1.CROSSWALK,
        crosswalk_phase=CrosswalkPhaseV1.COMMIT_CROSS,
        candidate_enters_resource=True,
        traffic_authority_confirmed=True,
        owner_committed=True,
        exit_visible_and_feasible=True,
        sufficient_crossing_time=True,
    )

    decision = _decide(semantics=context)

    assert decision.state is SocialProgressStateV1.TRACK
    assert decision.authorizes_motion is False


def test_committed_crosswalk_suppresses_generic_passing_side_changes() -> None:
    context = SemanticContextV1(
        venue=SocialVenueV1.CROSSWALK,
        crosswalk_phase=CrosswalkPhaseV1.COMMIT_CROSS,
        candidate_enters_resource=True,
        traffic_authority_confirmed=True,
        owner_committed=True,
        exit_visible_and_feasible=True,
        sufficient_crossing_time=True,
    )
    decision = _decide(
        semantics=context,
        liveness=SocialLivenessV1(
            progress_requested=True,
            reciprocal_oscillation=True,
            passing_side_candidate=PassingSideV1.RIGHT,
        ),
    )

    assert decision.state is SocialProgressStateV1.TRACK
    assert decision.proposal is SocialProposalV1.CONTINUE_PLANNING


@pytest.mark.parametrize(
    ("overrides", "cause"),
    [
        ({"elevator_door_open_vision": False}, SocialBlockCauseV1.ELEVATOR_DOOR_DISAGREEMENT),
        ({"elevator_egress_clear": False}, SocialBlockCauseV1.ELEVATOR_EGRESS),
        ({"elevator_capacity_available": False}, SocialBlockCauseV1.ELEVATOR_CAPACITY),
        ({"owner_entered_ahead": False}, SocialBlockCauseV1.ELEVATOR_OWNER_ORDER),
    ],
)
def test_elevator_entry_holds_on_each_missing_semantic_precondition(
    overrides: dict[str, bool],
    cause: SocialBlockCauseV1,
) -> None:
    kwargs = {
        "venue": SocialVenueV1.ELEVATOR,
        "elevator_phase": ElevatorPhaseV1.ENTER_TRAILING_OWNER,
        "candidate_enters_resource": True,
        "elevator_door_open_lidar": True,
        "elevator_door_open_vision": True,
        "elevator_egress_clear": True,
        "elevator_capacity_available": True,
        "owner_entered_ahead": True,
    }
    kwargs.update(overrides)

    decision = _decide(semantics=SemanticContextV1(**kwargs))

    assert decision.state is SocialProgressStateV1.HOLD_SEMANTIC
    assert decision.cause is cause


def test_persistent_block_requests_safe_staging_and_spends_one_budget_unit() -> None:
    decision = _decide(
        tracks=(_track(VisibilityStateV1.VISIBLE, hard=True),),
        liveness=SocialLivenessV1(
            progress_requested=True,
            block_duration_s=2.0,
            safe_staging_candidate_available=True,
        ),
    )

    assert decision.state is SocialProgressStateV1.SAFE_STAGING
    assert decision.proposal is SocialProposalV1.SAFE_STAGE_PLAN_REQUEST
    assert decision.recovery_budget_remaining == ENABLED.initial_recovery_budget - 1
    assert decision.authorizes_motion is False


def test_persistent_block_can_request_bounded_evasion_not_spin_or_reverse() -> None:
    decision = _decide(
        tracks=(_track(VisibilityStateV1.VISIBLE, hard=True),),
        liveness=SocialLivenessV1(
            progress_requested=True,
            block_duration_s=2.0,
            safe_evasion_candidate_available=True,
        ),
    )

    assert decision.state is SocialProgressStateV1.EVASIVE_REPLAN
    assert decision.proposal is SocialProposalV1.EVASIVE_PATH_PLAN_REQUEST
    assert "spin" not in decision.proposal.value
    assert "reverse" not in decision.proposal.value


def test_exhausted_persistent_recovery_ends_in_safe_hold() -> None:
    memory = SocialProgressMemoryV1(
        prior_state=SocialProgressStateV1.ASK_OWNER,
        release_certificate_required=True,
        recovery_budget_remaining=0,
    )
    decision = _decide(
        tracks=(_track(VisibilityStateV1.VISIBLE, hard=True),),
        memory=memory,
        liveness=SocialLivenessV1(
            progress_requested=True,
            block_duration_s=6.0,
            owner_query_already_made=True,
        ),
    )

    assert decision.state is SocialProgressStateV1.SAFE_HOLD
    assert decision.cause is SocialBlockCauseV1.RECOVERY_BUDGET_EXHAUSTED
    assert decision.proposal is SocialProposalV1.NONE


def test_reciprocal_oscillation_commits_a_side_as_a_proposal_only() -> None:
    decision = _decide(
        liveness=SocialLivenessV1(
            progress_requested=True,
            reciprocal_oscillation=True,
            passing_side_candidate=PassingSideV1.LEFT,
        )
    )

    assert decision.state is SocialProgressStateV1.COMMIT_PASSING_SIDE
    assert decision.proposal is SocialProposalV1.COMMIT_PASS_LEFT_CANDIDATE
    assert not decision.authorizes_motion


def test_explicit_free_requires_full_lidar_clear_provenance() -> None:
    with pytest.raises(ValueError, match="complete swept-corridor"):
        VisibilityEvidenceV1(
            evidence_id="bad-clear",
            visibility=VisibilityStateV1.EXPLICIT_FREE,
            source_monotonic_s=9.9,
            receive_monotonic_s=9.91,
        )

    with pytest.raises(ValueError, match="clear-ray provenance"):
        VisibilityEvidenceV1(
            evidence_id="bad-clear",
            visibility=VisibilityStateV1.EXPLICIT_FREE,
            source_monotonic_s=9.9,
            receive_monotonic_s=9.91,
            corridor_fully_observed=True,
            corridor_coverage=1.0,
        )


def test_live_track_rejects_explicit_free_corridor_evidence() -> None:
    evidence = _visibility("clear-not-track", VisibilityStateV1.EXPLICIT_FREE)

    with pytest.raises(ValueError, match="live social track cannot carry explicit_free"):
        SocialTrackEvidenceV1(
            track=DynamicTrackV2(
                track_id="person-contradiction",
                class_id="person",
                x=1.0,
                y=0.0,
                radius_m=0.3,
                confidence=0.9,
            ),
            existence_probability=0.9,
            visibility_evidence=evidence,
            in_swept_corridor=True,
            risk_upper_bound=0.8,
        )


def test_track_nested_bounds_accept_exact_maximum() -> None:
    evidence = _visibility("max-track", VisibilityStateV1.VISIBLE)
    wrapped = SocialTrackEvidenceV1(
        track=DynamicTrackV2(
            track_id="t" * MAX_TRACK_ID_CHARS,
            class_id="c" * MAX_TRACK_CLASS_ID_CHARS,
            x=1.0,
            y=0.0,
            radius_m=0.3,
            confidence=0.9,
            covariance=(0.0,) * MAX_TRACK_COVARIANCE_ENTRIES,
        ),
        existence_probability=0.9,
        visibility_evidence=evidence,
        in_swept_corridor=True,
        risk_upper_bound=0.8,
    )

    assert len(wrapped.track.track_id) == MAX_TRACK_ID_CHARS
    assert len(wrapped.track.class_id) == MAX_TRACK_CLASS_ID_CHARS
    assert len(wrapped.track.covariance) == MAX_TRACK_COVARIANCE_ENTRIES


@pytest.mark.parametrize(
    ("track", "message"),
    (
        (
            DynamicTrackV2("t" * (MAX_TRACK_ID_CHARS + 1), "person", 1.0, 0.0),
            "track_id must be",
        ),
        (
            DynamicTrackV2("person", "c" * (MAX_TRACK_CLASS_ID_CHARS + 1), 1.0, 0.0),
            "class_id must be",
        ),
        (
            DynamicTrackV2(
                "person",
                "person",
                1.0,
                0.0,
                covariance=(0.0,) * (MAX_TRACK_COVARIANCE_ENTRIES + 1),
            ),
            "covariance exceeds",
        ),
    ),
)
def test_track_nested_bounds_reject_maximum_plus_one(
    track: DynamicTrackV2,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        SocialTrackEvidenceV1(
            track=track,
            existence_probability=0.9,
            visibility_evidence=_visibility("overbound", VisibilityStateV1.VISIBLE),
            in_swept_corridor=True,
            risk_upper_bound=0.8,
        )


def test_malformed_and_duplicate_track_inputs_fail_loudly() -> None:
    track = _track(VisibilityStateV1.VISIBLE)
    with pytest.raises(ValueError, match="duplicate track_id"):
        _decide(tracks=(track, track))
    with pytest.raises(TypeError, match="tuple"):
        decide_social_progress(
            now_monotonic_s=NOW,
            tracks=[],  # type: ignore[arg-type]
            corridor_evidence=None,
            semantics=SemanticContextV1(venue=SocialVenueV1.SIDEWALK),
            liveness=SocialLivenessV1(),
            config=ENABLED,
        )


def test_semantic_phase_must_match_venue() -> None:
    with pytest.raises(ValueError, match="invalid outside"):
        SemanticContextV1(
            venue=SocialVenueV1.SIDEWALK,
            crosswalk_phase=CrosswalkPhaseV1.WAIT_AUTHORITY,
        )
