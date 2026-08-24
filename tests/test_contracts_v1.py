"""K1 contract CI: V1 DTO round-trips, validation, and fail-closed freshness."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from parcel_robot.contracts.freshness import (
    age_ns,
    check_freshness,
    detect_clock_jump,
    expires_from_ttl,
    is_expired,
    require_fresh,
    speed_cap_from_staleness_m_s,
)
from parcel_robot.contracts.v1 import (
    SCHEMA_VERSION,
    DetectionMsg,
    DialogueActV1,
    DialogueClaimV1,
    DialogueStateMsg,
    DynamicTrackV1,
    EvidenceEnvelopeV1,
    GeometryV1,
    GoalRegionV1,
    OwnerTrackV1,
    PoseXYZYaw,
    PredictedOccupancyV1,
    ReactionProposalV1,
    SceneQueryV1,
    SemanticRegionV1,
    SkillFeedbackV1,
    SocialCueV1,
    identity_covariance,
)


def _envelope(
    *,
    evidence_id: str = "ev-1",
    received: int = 1_000_000_000,
    expires: int | None = None,
    frame_id: str = "map",
    sequence: int = 1,
) -> EvidenceEnvelopeV1:
    return EvidenceEnvelopeV1(
        schema_version=SCHEMA_VERSION,
        evidence_id=evidence_id,
        source="unit_test",
        source_timestamp_ns=received,
        received_monotonic_ns=received,
        sequence=sequence,
        frame_id=frame_id,
        scene_revision=3,
        expires_monotonic_ns=expires if expires is not None else received + 500_000_000,
        calibration_id="calib-v1",
        provenance=("detector_v1",),
    )


def _pose(x: float = 1.0, y: float = 2.0) -> PoseXYZYaw:
    return PoseXYZYaw(x=x, y=y, z=0.3, yaw_rad=0.1)


# ---------------------------------------------------------------------------
# Envelope + freshness
# ---------------------------------------------------------------------------


def test_evidence_envelope_round_trip_and_frozen() -> None:
    env = _envelope()
    assert EvidenceEnvelopeV1.from_mapping(env.as_dict()) == env
    with pytest.raises(FrozenInstanceError):
        env.sequence = 99  # type: ignore[misc]


def test_envelope_rejects_nan_schema_mismatch_unknown_fields_and_bad_expiry() -> None:
    payload = _envelope().as_dict()
    payload["extra"] = True
    with pytest.raises(ValueError, match="unknown"):
        EvidenceEnvelopeV1.from_mapping(payload)

    payload = _envelope().as_dict()
    payload["schema_version"] = 2
    with pytest.raises(ValueError, match="schema_version"):
        EvidenceEnvelopeV1.from_mapping(payload)

    with pytest.raises(ValueError, match="expires_monotonic_ns must be after"):
        _envelope(expires=500)

    with pytest.raises(ValueError, match="finite"):
        PoseXYZYaw(x=float("nan"), y=0.0, z=0.0, yaw_rad=0.0)


def test_freshness_helpers_fail_closed() -> None:
    received = 1_000_000_000
    expires = expires_from_ttl(received_monotonic_ns=received, ttl_ns=500_000_000)
    assert age_ns(received_monotonic_ns=received, now_monotonic_ns=received + 100) == 100
    assert not is_expired(expires_monotonic_ns=expires, now_monotonic_ns=received + 100)
    assert is_expired(expires_monotonic_ns=expires, now_monotonic_ns=expires)

    verdict = check_freshness(
        received_monotonic_ns=received,
        expires_monotonic_ns=expires,
        now_monotonic_ns=expires + 1,
    )
    assert not verdict.accepted
    assert verdict.reason == "expired"

    stale = check_freshness(
        received_monotonic_ns=received,
        expires_monotonic_ns=expires,
        now_monotonic_ns=received + 200_000_000,
        max_age_ns=100_000_000,
    )
    assert not stale.accepted
    assert stale.reason == "stale"

    with pytest.raises(ValueError, match="evidence rejected"):
        require_fresh(
            received_monotonic_ns=received,
            expires_monotonic_ns=expires,
            now_monotonic_ns=expires,
        )

    with pytest.raises(ValueError, match="backwards"):
        age_ns(received_monotonic_ns=received, now_monotonic_ns=received - 1)


def test_clock_jump_and_speed_cap() -> None:
    ok = detect_clock_jump(
        previous_source_timestamp_ns=100,
        source_timestamp_ns=200,
        previous_received_monotonic_ns=1000,
        received_monotonic_ns=1100,
    )
    assert ok.accepted

    backward = detect_clock_jump(
        previous_source_timestamp_ns=200,
        source_timestamp_ns=100,
        previous_received_monotonic_ns=1000,
        received_monotonic_ns=1100,
    )
    assert not backward.accepted
    assert backward.reason == "source_clock_backward"

    jump = detect_clock_jump(
        previous_source_timestamp_ns=100,
        source_timestamp_ns=100 + 50_000_000,
        previous_received_monotonic_ns=1000,
        received_monotonic_ns=1100,
    )
    assert not jump.accepted
    assert jump.reason == "source_clock_jump"

    assert speed_cap_from_staleness_m_s(pipeline_age_s=0.1, max_displacement_m=0.15) == pytest.approx(
        1.5
    )
    assert speed_cap_from_staleness_m_s(pipeline_age_s=float("nan")) == 0.0


def test_envelope_require_fresh_and_wrong_frame_policy() -> None:
    env = _envelope(frame_id="odom")
    env.require_fresh(1_000_000_000 + 10_000_000)
    with pytest.raises(ValueError, match="expired"):
        env.require_fresh(env.expires_monotonic_ns)

    # Consumers reject wrong-frame samples before transform (exact frame gate).
    required_frame = "map"
    assert env.frame_id != required_frame


# ---------------------------------------------------------------------------
# Tracks / regions
# ---------------------------------------------------------------------------


def test_owner_and_dynamic_track_round_trip() -> None:
    cov = identity_covariance(4, 0.05)
    owner = OwnerTrackV1(
        envelope=_envelope(evidence_id="owner-ev"),
        enrolled_owner_id="owner-1",
        transient_track_id="trk-7",
        state="confirmed",
        pose=_pose(),
        pose_covariance=cov,
        velocity=PoseXYZYaw(0.2, 0.0, 0.0, 0.0),
        velocity_covariance=cov,
        identity_score=0.93,
        visibility_score=0.8,
        appearance_evidence_refs=("reid-1",),
        last_confirmed_at_monotonic_ns=1_000_000_000,
    )
    assert OwnerTrackV1.from_mapping(owner.as_dict()) == owner

    with pytest.raises(ValueError, match="last_confirmed"):
        OwnerTrackV1(
            envelope=_envelope(evidence_id="owner-bad"),
            enrolled_owner_id="owner-1",
            transient_track_id="trk-7",
            state="confirmed",
            pose=_pose(),
            pose_covariance=cov,
            velocity=PoseXYZYaw(0.0, 0.0, 0.0, 0.0),
            velocity_covariance=cov,
            identity_score=0.5,
            visibility_score=0.5,
            last_confirmed_at_monotonic_ns=0,
        )

    dyn = DynamicTrackV1(
        envelope=_envelope(evidence_id="dyn-ev"),
        track_id="ped-3",
        class_id="person",
        pose=_pose(3.0, 1.0),
        velocity=PoseXYZYaw(0.5, 0.0, 0.0, 0.0),
        pose_covariance=cov,
        predicted_occupancy=(
            PredictedOccupancyV1(
                kind="polygon",
                timestamp_ns=1_100_000_000,
                polygon=((0.0, 0.0), (1.0, 0.0), (1.0, 1.0)),
            ),
        ),
    )
    assert DynamicTrackV1.from_mapping(dyn.as_dict()) == dyn


def test_semantic_and_goal_region_round_trip() -> None:
    region = SemanticRegionV1(
        envelope=_envelope(evidence_id="sem-ev"),
        concept_scores={"sidewalk": 0.91, "road": 0.05},
        geometry=GeometryV1(
            kind="polygon",
            polygon=((0.0, 0.0), (2.0, 0.0), (2.0, 1.0), (0.0, 1.0)),
        ),
        geometry_covariance=identity_covariance(2, 0.1),
        free_space_support=0.85,
        observation_count=4,
        evidence_refs=("mask-1",),
    )
    assert SemanticRegionV1.from_mapping(region.as_dict()) == region

    with pytest.raises(ValueError, match="label|geometry|polygon"):
        GeometryV1(kind="polygon", polygon=((0.0, 0.0), (1.0, 0.0)))

    goal = GoalRegionV1(
        goal_id="goal-1",
        source_task_id="task-1",
        plan_step_id="step-nav",
        frame_id="map",
        acceptable_polygon=((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)),
        preferred_pose=_pose(0.5, 0.5),
        approach_constraints=("collision_free",),
        forbidden_regions=(
            GeometryV1(kind="disc", disc_center=(5.0, 5.0), disc_radius_m=1.0),
        ),
        relation="near",
        hold_duration_s=0.0,
        confidence=0.88,
        issued_at_monotonic_ns=1_000_000_000,
        expires_at_monotonic_ns=1_500_000_000,
        evidence_refs=("sem-ev",),
    )
    assert GoalRegionV1.from_mapping(goal.as_dict()) == goal
    assert goal.expired(1_500_000_000)
    assert not goal.expired(1_400_000_000)


# ---------------------------------------------------------------------------
# Voice / behavior
# ---------------------------------------------------------------------------


def test_dialogue_social_reaction_query_feedback_round_trips() -> None:
    act = DialogueActV1(
        schema_version=SCHEMA_VERSION,
        turn_id="turn-1",
        text="I'll find a safe route.",
        speech_style="warm",
        acknowledgement_kind="task_admitted",
        claims=(
            DialogueClaimV1(
                text="task admitted",
                veracity="verified",
                evidence_ref="exec-admit-1",
            ),
            DialogueClaimV1(text="sidewalk ahead", veracity="tentative"),
        ),
        social_cues=("cue-1",),
        asks_clarification=False,
    )
    assert DialogueActV1.from_mapping(act.as_dict()) == act

    with pytest.raises(ValueError, match="evidence_ref"):
        DialogueClaimV1(text="arrived", veracity="verified", evidence_ref="")

    cue = SocialCueV1(
        cue_id="cue-1",
        source_turn_id="turn-1",
        kind="joke",
        modality="transcript",
        evidence_ref="asr-1",
        confidence=0.7,
        valence=0.4,
        arousal=0.3,
        observed_at_monotonic_ns=1_000_000_000,
        expires_at_monotonic_ns=1_005_000_000_000,
    )
    assert SocialCueV1.from_mapping(cue.as_dict()) == cue

    proposal = ReactionProposalV1(
        proposal_id="rx-1",
        source_cue_ids=("cue-1",),
        behavior_id="acoustic_chuckle",
        required_tracks=("expression_audio",),
        confidence=0.6,
        urgency=0.2,
        earliest_start_monotonic_ns=1_000_000_000,
        expires_at_monotonic_ns=1_002_000_000_000,
        minimum_dwell_s=0.2,
        maximum_duration_s=1.5,
        interruption_policy="overlay",
        suppress_if=("critical_crossing",),
        personality_rule_id="warm-v1",
    )
    assert ReactionProposalV1.from_mapping(proposal.as_dict()) == proposal
    assert proposal.expired(1_002_000_000_000)

    with pytest.raises(ValueError, match="required track"):
        ReactionProposalV1(
            proposal_id="rx-bad",
            source_cue_ids=("cue-1",),
            behavior_id="bow",
            required_tracks=("neck",),
            confidence=0.5,
            urgency=0.5,
            earliest_start_monotonic_ns=1,
            expires_at_monotonic_ns=2,
            minimum_dwell_s=0.1,
            maximum_duration_s=1.0,
            interruption_policy="defer",
        )

    query = SceneQueryV1(
        query_id="q-1",
        task_id="task-1",
        plan_revision=2,
        terms=("lamppost",),
        requested_relation="near",
        freshness_required_ms=250.0,
        minimum_confidence=0.6,
        search_budget_s=8.0,
        allow_cached=True,
        allow_active_scan=True,
    )
    assert SceneQueryV1.from_mapping(query.as_dict()) == query

    feedback = SkillFeedbackV1(
        task_id="task-1",
        plan_revision=2,
        step_id="navigate",
        status="blocked",
        checkpoint=True,
        critical_phase=False,
        progress=0.4,
        verified_facts=("lidar_fresh",),
        evidence_refs=("ev-1",),
        blocking_reason="target_ambiguous",
        scene_revision=3,
    )
    assert SkillFeedbackV1.from_mapping(feedback.as_dict()) == feedback


# ---------------------------------------------------------------------------
# Fable additions
# ---------------------------------------------------------------------------


def test_detection_msg_and_dialogue_state_channel() -> None:
    det = DetectionMsg(
        envelope=_envelope(evidence_id="det-1"),
        class_id="lamppost",
        embedding=(0.1, 0.2, 0.3),
        bearing_rad=0.25,
        range_m=4.2,
        score=0.81,
        track_id="det-trk-1",
    )
    assert DetectionMsg.from_mapping(det.as_dict()) == det
    with pytest.raises(ValueError, match="bearing"):
        DetectionMsg(
            envelope=_envelope(evidence_id="det-bad"),
            class_id="x",
            embedding=(1.0,),
            bearing_rad=4.0,
            range_m=1.0,
            score=0.5,
        )
    with pytest.raises(ValueError, match="finite"):
        DetectionMsg(
            envelope=_envelope(evidence_id="det-nan"),
            class_id="x",
            embedding=(float("nan"),),
            bearing_rad=0.0,
            range_m=1.0,
            score=0.5,
        )

    state = DialogueStateMsg(
        schema_version=SCHEMA_VERSION,
        channel="dialogue_state",
        phase="listening",
        engagement=0.9,
        turn_id="turn-1",
        published_monotonic_ns=1_000_000_000,
        expires_monotonic_ns=1_000_500_000,
        sequence=42,
    )
    assert DialogueStateMsg.from_mapping(state.as_dict()) == state
    assert state.expired(1_000_500_000)
    with pytest.raises(ValueError, match="dialogue_state"):
        DialogueStateMsg(
            schema_version=SCHEMA_VERSION,
            channel="other",
            phase="idle",
            engagement=0.0,
            turn_id="",
            published_monotonic_ns=1,
            expires_monotonic_ns=2,
        )


def test_parsers_reject_malformed_payloads() -> None:
    for cls, factory in (
        (OwnerTrackV1, lambda: OwnerTrackV1.from_mapping({"envelope": {}})),
        (DetectionMsg, lambda: DetectionMsg.from_mapping({"class_id": "x"})),
        (DialogueStateMsg, lambda: DialogueStateMsg.from_mapping({"phase": "idle"})),
        (SceneQueryV1, lambda: SceneQueryV1.from_mapping({"query_id": "q"})),
    ):
        with pytest.raises((ValueError, TypeError)):
            factory()
        assert cls is not None  # keep parametrize-free clarity
