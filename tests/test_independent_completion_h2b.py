"""Focused contract tests for the isolated H2b completion latch."""

from __future__ import annotations

from dataclasses import fields, replace

import pytest

import parcel_robot.navigation.independent_completion_evidence as evidence_leaf
from parcel_robot.navigation.independent_completion import (
    AuthenticatedPlaceIdentityEvidenceV1,
    AuthenticatedPoseEpochVerificationV1,
    AuthenticatedTerminalGeometryEvidenceV1,
    CompletionDispositionV1,
    CompletionReasonV1,
    IndependentCompletionConfigV1,
    IndependentCompletionGoalV1,
    IndependentCompletionLatchV1,
    IndependentCompletionObservationV1,
    PlaceIdentityEvidenceV1,
    PoseEpochVerificationV1,
    TerminalGeometryEvidenceV1,
    TrustedPlaceIdentityVerifierV1,
    TrustedPoseEpochVerifierV1,
    TrustedTerminalGeometryVerifierV1,
)

SECOND = 1_000_000_000
GOAL_ID = "goal:front-door"
GOAL_NONCE = "nonce:h2b-test:front-door"
IDENTITY_KEY = b"h2b-test-identity-channel-key-v1!"
POSE_EPOCH_KEY = b"h2b-test-pose-epoch-channel-key-v1!"
GEOMETRY_KEY = b"h2b-test-geometry-channel-key-v1!"
IDENTITY_VERIFIER = TrustedPlaceIdentityVerifierV1(
    provider_id="test-provider:place-identity",
    verifier_id="test-verifier:place-identity",
    key=IDENTITY_KEY,
)
POSE_EPOCH_VERIFIER = TrustedPoseEpochVerifierV1(
    provider_id="test-provider:pose-epoch",
    verifier_id="test-verifier:pose-epoch",
    key=POSE_EPOCH_KEY,
)
GEOMETRY_VERIFIER = TrustedTerminalGeometryVerifierV1(
    provider_id="test-provider:terminal-geometry",
    verifier_id="test-verifier:terminal-geometry",
    key=GEOMETRY_KEY,
)


def _goal(
    *,
    epoch: int = 7,
    goal_id: str = GOAL_ID,
    goal_nonce: str = GOAL_NONCE,
    started_ms: int = 0,
) -> IndependentCompletionGoalV1:
    return IndependentCompletionGoalV1(
        goal_id=goal_id,
        goal_nonce=goal_nonce,
        target_place_id="place:front-door",
        baseline_pose_epoch=epoch,
        success_radius_m=0.50,
        started_at_monotonic_ns=started_ms * 1_000_000,
    )


def _enabled_latch(
    goal: IndependentCompletionGoalV1 | None = None,
    config: IndependentCompletionConfigV1 | None = None,
) -> IndependentCompletionLatchV1:
    return IndependentCompletionLatchV1(
        goal or _goal(),
        config or IndependentCompletionConfigV1(enabled=True),
        identity_verifier=IDENTITY_VERIFIER,
        pose_epoch_verifier=POSE_EPOCH_VERIFIER,
        geometry_verifier=GEOMETRY_VERIFIER,
    )


def _identity(
    observation_id: str,
    *,
    place_id: str = "place:front-door",
    epoch: int,
    captured_ms: int,
    score: float = 0.96,
    runner_up: float = 0.20,
    goal_id: str = GOAL_ID,
    goal_nonce: str = GOAL_NONCE,
) -> PlaceIdentityEvidenceV1:
    captured = captured_ms * 1_000_000
    return PlaceIdentityEvidenceV1(
        observation_id=observation_id,
        goal_id=goal_id,
        goal_nonce=goal_nonce,
        place_id=place_id,
        pose_epoch=epoch,
        captured_at_monotonic_ns=captured,
        received_at_monotonic_ns=captured + 1_000_000,
        target_score=score,
        runner_up_score=runner_up,
    )


def _verification(
    anchor: PlaceIdentityEvidenceV1,
    *,
    epoch: int,
    reset_ms: int,
    scan_residual_m: float = 0.04,
    landmark_residual_m: float = 0.05,
) -> PoseEpochVerificationV1:
    return PoseEpochVerificationV1(
        verification_id=f"verification:{epoch}",
        goal_id=anchor.goal_id,
        goal_nonce=anchor.goal_nonce,
        reset_id=f"reset:{epoch}",
        anchor_observation_id=anchor.observation_id,
        parent_pose_epoch=anchor.pose_epoch,
        pose_epoch=epoch,
        reset_at_monotonic_ns=reset_ms * 1_000_000,
        verified_at_monotonic_ns=(reset_ms + 20) * 1_000_000,
        received_at_monotonic_ns=(reset_ms + 21) * 1_000_000,
        scan_residual_m=scan_residual_m,
        landmark_residual_m=landmark_residual_m,
    )


def _geometry(
    identity: PlaceIdentityEvidenceV1,
    *,
    captured_ms: int,
    distance_m: float = 0.30,
    variance_m2: float = 0.0001,
    epoch: int | None = None,
) -> TerminalGeometryEvidenceV1:
    captured = captured_ms * 1_000_000
    return TerminalGeometryEvidenceV1(
        evidence_id=f"geometry:{captured_ms}",
        goal_id=identity.goal_id,
        goal_nonce=identity.goal_nonce,
        target_place_id=identity.place_id,
        identity_observation_id=identity.observation_id,
        pose_epoch=identity.pose_epoch if epoch is None else epoch,
        captured_at_monotonic_ns=captured,
        received_at_monotonic_ns=captured + 1_000_000,
        relative_x_m=distance_m,
        relative_y_m=0.0,
        covariance_xx_m2=variance_m2,
        covariance_xy_m2=0.0,
        covariance_yy_m2=variance_m2,
    )


def _step(
    latch: IndependentCompletionLatchV1,
    *,
    now_ms: int,
    epoch: int,
    candidate: bool = True,
    healthy: bool = True,
    discontinuity: float | None = None,
    identity: PlaceIdentityEvidenceV1 | None = None,
    verification: PoseEpochVerificationV1 | None = None,
    geometry: TerminalGeometryEvidenceV1 | None = None,
):
    return latch.step(
        IndependentCompletionObservationV1(
            now_monotonic_ns=now_ms * 1_000_000,
            current_pose_epoch=epoch,
            map_completion_candidate=candidate,
            map_healthy=healthy,
            discontinuity_score=discontinuity,
            place_identity=(None if identity is None else IDENTITY_VERIFIER.authenticate(identity)),
            pose_epoch_verification=(
                None if verification is None else POSE_EPOCH_VERIFIER.authenticate(verification)
            ),
            terminal_geometry=(
                None if geometry is None else GEOMETRY_VERIFIER.authenticate(geometry)
            ),
        )
    )


def _load_valid_chain(
    latch: IndependentCompletionLatchV1,
    *,
    parent_epoch: int = 7,
    new_epoch: int = 8,
    offset_ms: int = 0,
) -> tuple[PlaceIdentityEvidenceV1, PlaceIdentityEvidenceV1]:
    anchor = _identity(
        f"identity:anchor:{new_epoch}",
        place_id="place:hallway-anchor",
        epoch=parent_epoch,
        captured_ms=offset_ms + 10,
        goal_id=latch.goal.goal_id,
        goal_nonce=latch.goal.goal_nonce,
    )
    _step(
        latch,
        now_ms=offset_ms + 20,
        epoch=parent_epoch,
        identity=anchor,
    )
    verification = _verification(
        anchor,
        epoch=new_epoch,
        reset_ms=offset_ms + 30,
    )
    _step(
        latch,
        now_ms=offset_ms + 60,
        epoch=new_epoch,
        candidate=False,
        verification=verification,
    )
    target = _identity(
        f"identity:target:{new_epoch}",
        epoch=new_epoch,
        captured_ms=offset_ms + 80,
        goal_id=latch.goal.goal_id,
        goal_nonce=latch.goal.goal_nonce,
    )
    _step(
        latch,
        now_ms=offset_ms + 90,
        epoch=new_epoch,
        candidate=False,
        identity=target,
    )
    return anchor, target


def test_default_disabled_is_fail_closed_and_has_no_motion_surface() -> None:
    latch = IndependentCompletionLatchV1(_goal())
    decision = _step(latch, now_ms=10, epoch=7)

    assert decision.disposition is CompletionDispositionV1.HOLD
    assert decision.reason is CompletionReasonV1.FEATURE_DISABLED
    assert decision.terminal_claim_authorized is False
    assert decision.authorizes_motion is False
    names = {field.name for field in fields(decision)}
    assert not names.intersection({"velocity", "vx", "vy", "yaw_rate", "command"})


def test_public_module_reexports_the_import_cycle_safe_evidence_leaf() -> None:
    assert PlaceIdentityEvidenceV1 is evidence_leaf.PlaceIdentityEvidenceV1
    assert PoseEpochVerificationV1 is evidence_leaf.PoseEpochVerificationV1
    assert TerminalGeometryEvidenceV1 is evidence_leaf.TerminalGeometryEvidenceV1
    assert TrustedPlaceIdentityVerifierV1 is evidence_leaf.TrustedPlaceIdentityVerifierV1
    assert TrustedPoseEpochVerifierV1 is evidence_leaf.TrustedPoseEpochVerifierV1
    assert TrustedTerminalGeometryVerifierV1 is evidence_leaf.TrustedTerminalGeometryVerifierV1


def test_enabled_latch_requires_three_distinct_commissioned_channels() -> None:
    with pytest.raises(ValueError, match="requires three evidence verifier channels"):
        IndependentCompletionLatchV1(_goal(), IndependentCompletionConfigV1(enabled=True))

    duplicate_provider = TrustedPoseEpochVerifierV1(
        provider_id=IDENTITY_VERIFIER.provider_id,
        verifier_id="test-verifier:duplicate-provider",
        key=b"h2b-test-duplicate-provider-key-v1!",
    )
    with pytest.raises(ValueError, match="provider IDs must be distinct"):
        IndependentCompletionLatchV1(
            _goal(),
            IndependentCompletionConfigV1(enabled=True),
            identity_verifier=IDENTITY_VERIFIER,
            pose_epoch_verifier=duplicate_provider,
            geometry_verifier=GEOMETRY_VERIFIER,
        )


def test_raw_identity_reset_and_geometry_records_are_refused() -> None:
    anchor = _identity("identity:raw-anchor", epoch=7, captured_ms=10)
    verification = _verification(anchor, epoch=8, reset_ms=30)
    target = _identity("identity:raw-target", epoch=8, captured_ms=80)
    geometry = _geometry(target, captured_ms=110)

    for field_name, raw_evidence, epoch, now_ms in (
        ("place_identity", anchor, 7, 20),
        ("pose_epoch_verification", verification, 8, 60),
        ("terminal_geometry", geometry, 8, 120),
    ):
        with pytest.raises(TypeError, match="Authenticated"):
            IndependentCompletionObservationV1(
                now_monotonic_ns=now_ms * 1_000_000,
                current_pose_epoch=epoch,
                map_completion_candidate=True,
                map_healthy=True,
                **{field_name: raw_evidence},
            )


def test_tampered_authenticated_records_hold_before_lineage_ingestion() -> None:
    anchor = _identity("identity:tampered-anchor", epoch=7, captured_ms=10)
    verification = _verification(anchor, epoch=8, reset_ms=30)
    target = _identity("identity:tampered-target", epoch=8, captured_ms=80)
    geometry = _geometry(target, captured_ms=110)
    authenticated = (
        (
            "place_identity",
            IDENTITY_VERIFIER.authenticate(anchor),
            replace(anchor, target_score=0.95),
            7,
            20,
        ),
        (
            "pose_epoch_verification",
            POSE_EPOCH_VERIFIER.authenticate(verification),
            replace(verification, scan_residual_m=0.05),
            8,
            60,
        ),
        (
            "terminal_geometry",
            GEOMETRY_VERIFIER.authenticate(geometry),
            replace(geometry, relative_x_m=0.31),
            8,
            120,
        ),
    )
    for field_name, signed, changed_evidence, epoch, now_ms in authenticated:
        first = "0" if signed.auth_tag[0] != "0" else "1"
        tag_tampered = replace(signed, auth_tag=first + signed.auth_tag[1:])
        payload_tampered = replace(signed, evidence=changed_evidence)
        for tampered in (tag_tampered, payload_tampered):
            latch = _enabled_latch()
            decision = latch.step(
                IndependentCompletionObservationV1(
                    now_monotonic_ns=now_ms * 1_000_000,
                    current_pose_epoch=epoch,
                    map_completion_candidate=True,
                    map_healthy=True,
                    **{field_name: tampered},
                )
            )
            assert decision.disposition is CompletionDispositionV1.HOLD
            assert decision.reason is CompletionReasonV1.EVIDENCE_AUTHENTICATION_FAILED
            assert "authenticated_evidence" in decision.unmet_requirements
            assert not decision.terminal_claim_authorized


def test_wrong_provider_channel_is_refused_for_each_evidence_role() -> None:
    anchor = _identity("identity:wrong-channel-anchor", epoch=7, captured_ms=10)
    verification = _verification(anchor, epoch=8, reset_ms=30)
    target = _identity("identity:wrong-channel-target", epoch=8, captured_ms=80)
    geometry = _geometry(target, captured_ms=110)
    wrong_identity = TrustedPlaceIdentityVerifierV1(
        provider_id=POSE_EPOCH_VERIFIER.provider_id,
        verifier_id="wrong-verifier:identity-on-pose-channel",
        key=b"h2b-test-wrong-identity-channel-key!",
    ).authenticate(anchor)
    wrong_pose_epoch = TrustedPoseEpochVerifierV1(
        provider_id=GEOMETRY_VERIFIER.provider_id,
        verifier_id="wrong-verifier:pose-on-geometry-channel",
        key=b"h2b-test-wrong-pose-channel-key-v1!",
    ).authenticate(verification)
    wrong_geometry = TrustedTerminalGeometryVerifierV1(
        provider_id=IDENTITY_VERIFIER.provider_id,
        verifier_id="wrong-verifier:geometry-on-identity-channel",
        key=b"h2b-test-wrong-geometry-key-v1!!!",
    ).authenticate(geometry)

    for field_name, signed, epoch, now_ms in (
        ("place_identity", wrong_identity, 7, 20),
        ("pose_epoch_verification", wrong_pose_epoch, 8, 60),
        ("terminal_geometry", wrong_geometry, 8, 120),
    ):
        latch = _enabled_latch()
        decision = latch.step(
            IndependentCompletionObservationV1(
                now_monotonic_ns=now_ms * 1_000_000,
                current_pose_epoch=epoch,
                map_completion_candidate=True,
                map_healthy=True,
                **{field_name: signed},
            )
        )
        assert decision.disposition is CompletionDispositionV1.HOLD
        assert decision.reason is CompletionReasonV1.EVIDENCE_AUTHENTICATION_FAILED
        assert not decision.authorizes_motion

    assert isinstance(IDENTITY_VERIFIER.authenticate(anchor), AuthenticatedPlaceIdentityEvidenceV1)
    assert isinstance(
        POSE_EPOCH_VERIFIER.authenticate(verification),
        AuthenticatedPoseEpochVerificationV1,
    )
    assert isinstance(
        GEOMETRY_VERIFIER.authenticate(geometry),
        AuthenticatedTerminalGeometryEvidenceV1,
    )


def test_all_three_independent_authorities_are_required_for_claim() -> None:
    latch = _enabled_latch()
    _anchor, target = _load_valid_chain(latch)

    before_geometry = _step(latch, now_ms=100, epoch=8)
    assert before_geometry.disposition is CompletionDispositionV1.HOLD
    assert "fresh_terminal_geometry" in before_geometry.unmet_requirements

    decision = _step(
        latch,
        now_ms=120,
        epoch=8,
        geometry=_geometry(target, captured_ms=110),
    )
    assert decision.disposition is CompletionDispositionV1.AUTHORIZE_TERMINAL_CLAIM
    assert decision.terminal_claim_authorized
    assert not decision.authorizes_motion

    replay = _step(latch, now_ms=130, epoch=8)
    assert replay.disposition is CompletionDispositionV1.HOLD
    assert replay.reason is CompletionReasonV1.ALREADY_CLOSED


@pytest.mark.parametrize(
    ("score", "runner_up"),
    [(0.69, 0.10), (0.90, 0.76), (0.70, 0.56)],
)
def test_ambiguous_or_low_identity_cannot_seed_pose_reset(
    score: float,
    runner_up: float,
) -> None:
    latch = _enabled_latch()
    anchor = _identity(
        "identity:ambiguous",
        place_id="place:anchor",
        epoch=7,
        captured_ms=10,
        score=score,
        runner_up=runner_up,
    )
    first = _step(latch, now_ms=20, epoch=7, identity=anchor)
    assert first.reason is CompletionReasonV1.IDENTITY_AMBIGUOUS

    verification = _verification(anchor, epoch=8, reset_ms=30)
    second = _step(
        latch,
        now_ms=60,
        epoch=8,
        verification=verification,
    )
    assert second.disposition is CompletionDispositionV1.HOLD
    assert second.reason is CompletionReasonV1.EVIDENCE_LINEAGE_MISMATCH


def test_same_epoch_and_inconsistent_residuals_fail_closed() -> None:
    latch = _enabled_latch()
    anchor = _identity(
        "identity:anchor",
        place_id="place:anchor",
        epoch=7,
        captured_ms=10,
    )
    _step(latch, now_ms=20, epoch=7, identity=anchor)

    with pytest.raises(ValueError, match="strictly newer"):
        _verification(anchor, epoch=7, reset_ms=30)

    bad = _verification(anchor, epoch=8, reset_ms=30, scan_residual_m=0.121)
    decision = _step(latch, now_ms=60, epoch=8, verification=bad)
    assert decision.reason is CompletionReasonV1.RESIDUAL_INCONSISTENT
    assert "verified_new_pose_epoch" in decision.unmet_requirements


def test_covariance_expanded_terminal_geometry_rejects_boundary_mean() -> None:
    latch = _enabled_latch()
    _anchor, target = _load_valid_chain(latch)
    # The mean is inside 0.50 m, but 0.47 + 3*0.02 = 0.53 exceeds the
    # conservative 0.49 m limit after the 0.01 m guard.
    decision = _step(
        latch,
        now_ms=120,
        epoch=8,
        geometry=_geometry(
            target,
            captured_ms=110,
            distance_m=0.47,
            variance_m2=0.0004,
        ),
    )
    assert decision.disposition is CompletionDispositionV1.HOLD
    assert decision.reason is CompletionReasonV1.TERMINAL_GEOMETRY_OUTSIDE
    assert "conservative_terminal_geometry" in decision.unmet_requirements


def test_discontinuity_invalidates_proofs_and_requires_another_new_epoch() -> None:
    latch = _enabled_latch()
    old_anchor, old_target = _load_valid_chain(latch)
    old_geometry = _geometry(old_target, captured_ms=110)

    discontinuity = _step(
        latch,
        now_ms=120,
        epoch=8,
        discontinuity=0.95,
        geometry=old_geometry,
    )
    assert discontinuity.disposition is CompletionDispositionV1.HOLD
    assert discontinuity.required_newer_than_epoch == 8
    assert latch.discontinuity_latched

    old_epoch = _step(
        latch,
        now_ms=140,
        epoch=8,
        verification=_verification(old_anchor, epoch=8, reset_ms=30),
        geometry=old_geometry,
    )
    assert not old_epoch.terminal_claim_authorized
    assert "verified_new_pose_epoch" in old_epoch.unmet_requirements

    _new_anchor, new_target = _load_valid_chain(
        latch,
        parent_epoch=8,
        new_epoch=9,
        offset_ms=160,
    )
    recovered = _step(
        latch,
        now_ms=280,
        epoch=9,
        geometry=_geometry(new_target, captured_ms=270),
    )
    assert recovered.disposition is CompletionDispositionV1.AUTHORIZE_TERMINAL_CLAIM
    assert recovered.required_newer_than_epoch == 8
    assert not recovered.authorizes_motion


def test_cross_epoch_geometry_and_replayed_identity_are_refused() -> None:
    latch = _enabled_latch()
    _anchor, target = _load_valid_chain(latch)
    wrong_epoch = _step(
        latch,
        now_ms=120,
        epoch=8,
        geometry=_geometry(target, captured_ms=110, epoch=9),
    )
    assert wrong_epoch.reason is CompletionReasonV1.EVIDENCE_LINEAGE_MISMATCH
    assert not wrong_epoch.terminal_claim_authorized

    stale_target = _identity(
        "identity:stale-target",
        epoch=8,
        captured_ms=100,
    )
    stale_geometry = _geometry(stale_target, captured_ms=3_700)
    stale = _step(
        latch,
        now_ms=3_710,
        epoch=8,
        identity=stale_target,
        geometry=stale_geometry,
    )
    assert stale.reason is CompletionReasonV1.EVIDENCE_STALE
    assert not stale.terminal_claim_authorized


def test_evidence_is_bound_to_one_goal_nonce_and_cannot_cross_goal_replay() -> None:
    prior_goal = _goal(goal_nonce="nonce:prior-goal")
    prior = _enabled_latch(prior_goal)
    _prior_anchor, prior_target = _load_valid_chain(prior)
    prior_geometry = _geometry(prior_target, captured_ms=110)

    current = _enabled_latch(_goal(goal_nonce="nonce:current-goal"))
    replay = _step(
        current,
        now_ms=120,
        epoch=8,
        identity=prior_target,
        geometry=prior_geometry,
    )
    assert replay.disposition is CompletionDispositionV1.HOLD
    assert replay.reason is CompletionReasonV1.EVIDENCE_LINEAGE_MISMATCH
    assert not replay.terminal_claim_authorized


def test_evidence_captured_before_goal_start_cannot_seed_completion() -> None:
    latch = _enabled_latch(_goal(started_ms=1_000))
    pre_goal = _identity(
        "identity:pre-goal",
        epoch=7,
        captured_ms=900,
    )
    decision = _step(latch, now_ms=1_010, epoch=7, identity=pre_goal)
    assert decision.disposition is CompletionDispositionV1.HOLD
    assert decision.reason is CompletionReasonV1.EVIDENCE_LINEAGE_MISMATCH
    assert not decision.terminal_claim_authorized


def test_cached_epoch_verification_is_revalidated_and_expires() -> None:
    latch = _enabled_latch(
        config=IndependentCompletionConfigV1(
            enabled=True,
            epoch_verification_max_age_s=0.05,
        ),
    )
    _anchor, target = _load_valid_chain(latch)
    decision = _step(
        latch,
        now_ms=120,
        epoch=8,
        geometry=_geometry(target, captured_ms=110),
    )
    assert decision.disposition is CompletionDispositionV1.HOLD
    assert decision.reason is CompletionReasonV1.EVIDENCE_STALE
    assert "verified_new_pose_epoch" in decision.unmet_requirements
    assert not decision.terminal_claim_authorized


def test_unresolved_candidate_becomes_typed_uncertainty_without_silent_wait() -> None:
    latch = _enabled_latch()
    start = _step(latch, now_ms=10, epoch=7)
    assert start.disposition is CompletionDispositionV1.HOLD

    timeout = _step(latch, now_ms=4_010, epoch=7)
    assert timeout.disposition is CompletionDispositionV1.LOCALIZATION_UNCERTAIN
    assert timeout.reason is CompletionReasonV1.WAIT_TIMEOUT
    assert timeout.unmet_requirements
    assert not timeout.terminal_claim_authorized
    assert not timeout.authorizes_motion


def test_time_regression_and_non_psd_geometry_fail_closed() -> None:
    latch = _enabled_latch()
    _step(latch, now_ms=100, epoch=7, candidate=False)
    regressed = _step(latch, now_ms=99, epoch=7, candidate=False)
    assert regressed.disposition is CompletionDispositionV1.LOCALIZATION_UNCERTAIN
    assert regressed.reason is CompletionReasonV1.TIME_REGRESSION

    target = _identity("identity:target", epoch=8, captured_ms=10)
    with pytest.raises(ValueError, match="positive semidefinite"):
        TerminalGeometryEvidenceV1(
            evidence_id="geometry:bad-covariance",
            goal_id=target.goal_id,
            goal_nonce=target.goal_nonce,
            target_place_id=target.place_id,
            identity_observation_id=target.observation_id,
            pose_epoch=8,
            captured_at_monotonic_ns=20_000_000,
            received_at_monotonic_ns=21_000_000,
            relative_x_m=0.2,
            relative_y_m=0.0,
            covariance_xx_m2=0.01,
            covariance_xy_m2=0.02,
            covariance_yy_m2=0.01,
        )


def test_goal_radius_cannot_be_smaller_than_fixed_guard() -> None:
    latch = _enabled_latch(
        goal=IndependentCompletionGoalV1(
            goal_id="goal:tiny",
            goal_nonce="nonce:tiny",
            target_place_id="place:tiny",
            baseline_pose_epoch=1,
            success_radius_m=0.005,
            started_at_monotonic_ns=0,
        ),
        config=IndependentCompletionConfigV1(enabled=True, geometry_guard_m=0.01),
    )
    decision = _step(latch, now_ms=1, epoch=1)
    assert decision.disposition is CompletionDispositionV1.HOLD
    assert not decision.terminal_claim_authorized
