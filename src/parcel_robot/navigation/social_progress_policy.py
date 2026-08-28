"""Deterministic decision policy for the proposal-only social-progress seam.

The public contracts live in :mod:`parcel_robot.navigation.social_progress`.
This leaf contains only the branching policy so the contracts stay reviewable
and no single decision function becomes a second state-machine monolith.
"""

from __future__ import annotations

from parcel_robot.navigation.social_progress_contracts import (
    CrosswalkPhaseV1,
    ElevatorPhaseV1,
    PassingSideV1,
    SemanticContextV1,
    SocialBlockCauseV1,
    SocialLivenessV1,
    SocialProgressConfigV1,
    SocialProgressDecisionV1,
    SocialProgressMemoryV1,
    SocialProgressStateV1,
    SocialProposalV1,
    SocialTrackEvidenceV1,
    SocialVenueV1,
    VisibilityEvidenceV1,
    VisibilityStateV1,
    _finite,
)


def _fresh(
    evidence: VisibilityEvidenceV1,
    now_s: float,
    config: SocialProgressConfigV1,
) -> bool:
    return (
        evidence.age_s(now_s) <= config.max_source_age_s
        and evidence.receive_monotonic_s - evidence.source_monotonic_s
        <= config.max_transport_delay_s
        and evidence.visibility is not VisibilityStateV1.STALE
    )


def _decision(
    *,
    state: SocialProgressStateV1,
    cause: SocialBlockCauseV1,
    proposal: SocialProposalV1,
    blocker_id: str | None,
    evidence_age_s: float | None,
    clear_streak: int,
    risk_upper_bound: float,
    recovery_budget_remaining: int,
    release_required: bool,
    last_clear_evidence_id: str | None,
    resume_eligible: bool = False,
) -> SocialProgressDecisionV1:
    memory = SocialProgressMemoryV1(
        prior_state=state,
        release_certificate_required=release_required,
        clear_streak=clear_streak if release_required else 0,
        last_clear_evidence_id=last_clear_evidence_id if release_required else None,
        recovery_budget_remaining=recovery_budget_remaining,
    )
    return SocialProgressDecisionV1(
        state=state,
        cause=cause,
        proposal=proposal,
        blocker_id=blocker_id,
        evidence_age_s=evidence_age_s,
        clear_streak=memory.clear_streak,
        risk_upper_bound=risk_upper_bound,
        recovery_budget_remaining=recovery_budget_remaining,
        resume_eligible=resume_eligible,
        next_memory=memory,
    )


def _semantic_hold(context: SemanticContextV1) -> SocialBlockCauseV1 | None:
    if not context.candidate_enters_resource:
        if context.venue is SocialVenueV1.ELEVATOR and context.elevator_car_moving:
            return SocialBlockCauseV1.ELEVATOR_MOVING
        return None
    if context.venue is SocialVenueV1.UNKNOWN:
        return SocialBlockCauseV1.UNKNOWN_RESOURCE
    if context.venue is SocialVenueV1.CROSSWALK:
        if context.crosswalk_phase is not CrosswalkPhaseV1.COMMIT_CROSS:
            return SocialBlockCauseV1.CROSSWALK_AUTHORITY
        if not context.traffic_authority_confirmed or not context.owner_committed:
            return SocialBlockCauseV1.CROSSWALK_AUTHORITY
        if not context.exit_visible_and_feasible or not context.sufficient_crossing_time:
            return SocialBlockCauseV1.CROSSWALK_EXIT_UNAVAILABLE
    if context.venue is SocialVenueV1.ELEVATOR:
        if context.elevator_phase is not ElevatorPhaseV1.ENTER_TRAILING_OWNER:
            return SocialBlockCauseV1.ELEVATOR_EGRESS
        if context.elevator_door_open_lidar != context.elevator_door_open_vision:
            return SocialBlockCauseV1.ELEVATOR_DOOR_DISAGREEMENT
        if not context.elevator_door_open_lidar:
            return SocialBlockCauseV1.ELEVATOR_DOOR_DISAGREEMENT
        if not context.elevator_egress_clear:
            return SocialBlockCauseV1.ELEVATOR_EGRESS
        if not context.elevator_capacity_available:
            return SocialBlockCauseV1.ELEVATOR_CAPACITY
        if not context.owner_entered_ahead:
            return SocialBlockCauseV1.ELEVATOR_OWNER_ORDER
        if context.elevator_car_moving:
            return SocialBlockCauseV1.ELEVATOR_MOVING
    return None


def _persistent_proposal(
    liveness: SocialLivenessV1,
    memory: SocialProgressMemoryV1,
    config: SocialProgressConfigV1,
) -> tuple[SocialProgressStateV1, SocialProposalV1, SocialBlockCauseV1, int] | None:
    if liveness.block_duration_s < config.recovery_after_s:
        return None
    budget = memory.recovery_budget_remaining
    if liveness.block_duration_s >= config.safe_hold_after_s or (
        budget == 0 and liveness.owner_query_already_made
    ):
        return (
            SocialProgressStateV1.SAFE_HOLD,
            SocialProposalV1.NONE,
            SocialBlockCauseV1.RECOVERY_BUDGET_EXHAUSTED,
            budget,
        )
    candidates = (
        (
            liveness.formation_switch_available,
            SocialProgressStateV1.FORMATION_SWITCH,
            SocialProposalV1.TRAILING_FORMATION_CANDIDATE,
        ),
        (
            liveness.safe_staging_candidate_available,
            SocialProgressStateV1.SAFE_STAGING,
            SocialProposalV1.SAFE_STAGE_PLAN_REQUEST,
        ),
        (
            liveness.safe_evasion_candidate_available,
            SocialProgressStateV1.EVASIVE_REPLAN,
            SocialProposalV1.EVASIVE_PATH_PLAN_REQUEST,
        ),
        (
            liveness.alternate_route_available,
            SocialProgressStateV1.REROUTE,
            SocialProposalV1.ALTERNATE_ROUTE_PLAN_REQUEST,
        ),
    )
    for available, state, proposal in candidates:
        if available and memory.prior_state is not state and budget > 0:
            return state, proposal, SocialBlockCauseV1.TRUE_DYNAMIC_BLOCK, budget - 1
    if liveness.block_duration_s >= config.ask_owner_after_s:
        cause = (
            SocialBlockCauseV1.RECOVERY_BUDGET_EXHAUSTED
            if budget == 0
            else SocialBlockCauseV1.TRUE_DYNAMIC_BLOCK
        )
        return SocialProgressStateV1.ASK_OWNER, SocialProposalV1.ASK_OWNER, cause, budget
    return None


def _generic_recovery_allowed(context: SemanticContextV1) -> bool:
    return not (
        context.venue is SocialVenueV1.CROSSWALK
        and context.crosswalk_phase is CrosswalkPhaseV1.COMMIT_CROSS
    )


def _validated_inputs(
    *,
    now_monotonic_s: float,
    tracks: tuple[SocialTrackEvidenceV1, ...],
    corridor_evidence: VisibilityEvidenceV1 | None,
    semantics: SemanticContextV1,
    liveness: SocialLivenessV1,
    memory: SocialProgressMemoryV1 | None,
    config: SocialProgressConfigV1 | None,
) -> tuple[float, SocialProgressConfigV1, SocialProgressMemoryV1, float]:
    now = _finite(now_monotonic_s, "now_monotonic_s", minimum=0.0)
    if not isinstance(tracks, tuple) or any(
        not isinstance(track, SocialTrackEvidenceV1) for track in tracks
    ):
        raise TypeError("tracks must be a tuple of SocialTrackEvidenceV1")
    if len(tracks) > 64:
        raise ValueError("tracks exceeds 64 items")
    track_ids = [item.track.track_id for item in tracks]
    if len(track_ids) != len(set(track_ids)):
        raise ValueError("tracks cannot contain duplicate track_id values")
    if corridor_evidence is not None and not isinstance(corridor_evidence, VisibilityEvidenceV1):
        raise TypeError("corridor_evidence must be VisibilityEvidenceV1 or None")
    evidence = [item.visibility_evidence for item in tracks]
    if corridor_evidence is not None:
        evidence.append(corridor_evidence)
    if any(item.source_monotonic_s > now or item.receive_monotonic_s > now for item in evidence):
        raise ValueError("evidence time cannot be after decision time")
    if not isinstance(semantics, SemanticContextV1):
        raise TypeError("semantics must be SemanticContextV1")
    if not isinstance(liveness, SocialLivenessV1):
        raise TypeError("liveness must be SocialLivenessV1")
    cfg = SocialProgressConfigV1() if config is None else config
    if not isinstance(cfg, SocialProgressConfigV1):
        raise TypeError("config must be SocialProgressConfigV1 or None")
    mem = (
        SocialProgressMemoryV1(recovery_budget_remaining=cfg.initial_recovery_budget)
        if memory is None
        else memory
    )
    if not isinstance(mem, SocialProgressMemoryV1):
        raise TypeError("memory must be SocialProgressMemoryV1 or None")
    risk = max((item.risk_upper_bound for item in tracks if item.in_swept_corridor), default=0.0)
    return now, cfg, mem, risk


def _health_or_semantic_decision(
    *,
    semantics: SemanticContextV1,
    liveness: SocialLivenessV1,
    memory: SocialProgressMemoryV1,
    risk: float,
) -> SocialProgressDecisionV1 | None:
    cause = None
    if not liveness.localization_healthy:
        cause = SocialBlockCauseV1.LOCALIZATION_FAILURE
    elif not liveness.planner_healthy:
        cause = SocialBlockCauseV1.PLANNER_FAILURE
    elif not liveness.sensor_health_ok:
        cause = SocialBlockCauseV1.STALE_SENSOR
    if cause is not None:
        return _decision(
            state=SocialProgressStateV1.HOLD_UNCERTAIN,
            cause=cause,
            proposal=SocialProposalV1.CONTINUE_PLANNING,
            blocker_id=None,
            evidence_age_s=None,
            clear_streak=0,
            risk_upper_bound=risk,
            recovery_budget_remaining=memory.recovery_budget_remaining,
            release_required=True,
            last_clear_evidence_id=None,
        )
    semantic_cause = _semantic_hold(semantics)
    if semantic_cause is None:
        return None
    return _decision(
        state=SocialProgressStateV1.HOLD_SEMANTIC,
        cause=semantic_cause,
        proposal=SocialProposalV1.CONTINUE_PLANNING,
        blocker_id=None,
        evidence_age_s=None,
        clear_streak=0,
        risk_upper_bound=risk,
        recovery_budget_remaining=memory.recovery_budget_remaining,
        release_required=memory.release_certificate_required,
        last_clear_evidence_id=None,
    )


def _occupied_decision(
    *,
    now: float,
    occupied: tuple[SocialTrackEvidenceV1, ...],
    semantics: SemanticContextV1,
    liveness: SocialLivenessV1,
    memory: SocialProgressMemoryV1,
    config: SocialProgressConfigV1,
    risk: float,
) -> SocialProgressDecisionV1:
    blocker = max(occupied, key=lambda item: item.risk_upper_bound) if occupied else None
    persistent = (
        _persistent_proposal(liveness, memory, config)
        if _generic_recovery_allowed(semantics)
        else None
    )
    state = SocialProgressStateV1.HOLD_OCCUPIED
    proposal = SocialProposalV1.CONTINUE_PLANNING
    cause = SocialBlockCauseV1.TRUE_DYNAMIC_BLOCK
    budget = memory.recovery_budget_remaining
    if persistent is not None:
        state, proposal, cause, budget = persistent
    return _decision(
        state=state,
        cause=cause,
        proposal=proposal,
        blocker_id=blocker.track.track_id if blocker is not None else None,
        evidence_age_s=blocker.visibility_evidence.age_s(now) if blocker else None,
        clear_streak=0,
        risk_upper_bound=max(risk, 1.0 if liveness.hard_envelope_violated else risk),
        recovery_budget_remaining=budget,
        release_required=True,
        last_clear_evidence_id=None,
    )


def _uncertain_decision(
    *,
    now: float,
    uncertain: tuple[SocialTrackEvidenceV1, ...],
    semantics: SemanticContextV1,
    liveness: SocialLivenessV1,
    memory: SocialProgressMemoryV1,
    config: SocialProgressConfigV1,
    risk: float,
) -> SocialProgressDecisionV1:
    blocker = max(uncertain, key=lambda item: item.existence_probability)
    visibility = blocker.visibility_evidence.visibility
    if not _fresh(blocker.visibility_evidence, now, config) or (
        visibility is VisibilityStateV1.STALE
    ):
        cause = SocialBlockCauseV1.STALE_SENSOR
    elif visibility is VisibilityStateV1.OUT_OF_FOV:
        cause = SocialBlockCauseV1.OUT_OF_FOV
    else:
        cause = SocialBlockCauseV1.UNCERTAIN_OCCLUSION
    persistent = (
        _persistent_proposal(liveness, memory, config)
        if _generic_recovery_allowed(semantics)
        else None
    )
    state = SocialProgressStateV1.HOLD_UNCERTAIN
    proposal = SocialProposalV1.CONTINUE_PLANNING
    budget = memory.recovery_budget_remaining
    if persistent is not None:
        state, proposal, _, budget = persistent
    return _decision(
        state=state,
        cause=cause,
        proposal=proposal,
        blocker_id=blocker.track.track_id,
        evidence_age_s=blocker.visibility_evidence.age_s(now),
        clear_streak=0,
        risk_upper_bound=risk,
        recovery_budget_remaining=budget,
        release_required=True,
        last_clear_evidence_id=None,
    )


def _track_block_decision(
    *,
    now: float,
    tracks: tuple[SocialTrackEvidenceV1, ...],
    semantics: SemanticContextV1,
    liveness: SocialLivenessV1,
    memory: SocialProgressMemoryV1,
    config: SocialProgressConfigV1,
    risk: float,
) -> SocialProgressDecisionV1 | None:
    corridor = tuple(
        item
        for item in tracks
        if item.in_swept_corridor and item.existence_probability >= config.active_existence_min
    )
    fresh = tuple(item for item in corridor if _fresh(item.visibility_evidence, now, config))
    occupied = tuple(
        item
        for item in fresh
        if item.visibility_evidence.visibility is VisibilityStateV1.VISIBLE
        and (item.within_hard_envelope or item.risk_upper_bound >= config.hold_risk_upper_bound)
    )
    if liveness.hard_envelope_violated or occupied:
        return _occupied_decision(
            now=now,
            occupied=occupied,
            semantics=semantics,
            liveness=liveness,
            memory=memory,
            config=config,
            risk=risk,
        )
    uncertain = tuple(
        item
        for item in corridor
        if item not in fresh
        or item.visibility_evidence.visibility
        in {VisibilityStateV1.OCCLUDED, VisibilityStateV1.OUT_OF_FOV, VisibilityStateV1.STALE}
    )
    if uncertain:
        return _uncertain_decision(
            now=now,
            uncertain=uncertain,
            semantics=semantics,
            liveness=liveness,
            memory=memory,
            config=config,
            risk=risk,
        )
    if not liveness.costmap_blocked_without_live_track:
        return None
    persistent = (
        _persistent_proposal(liveness, memory, config)
        if _generic_recovery_allowed(semantics)
        else None
    )
    state, proposal, budget = (
        (
            SocialProgressStateV1.HOLD_UNCERTAIN,
            SocialProposalV1.CONTINUE_PLANNING,
            memory.recovery_budget_remaining,
        )
        if persistent is None
        else (persistent[0], persistent[1], persistent[3])
    )
    return _decision(
        state=state,
        cause=SocialBlockCauseV1.COSTMAP_GHOST,
        proposal=proposal,
        blocker_id=None,
        evidence_age_s=None,
        clear_streak=0,
        risk_upper_bound=risk,
        recovery_budget_remaining=budget,
        release_required=True,
        last_clear_evidence_id=None,
    )


def _release_decision(
    *,
    now: float,
    corridor: VisibilityEvidenceV1 | None,
    liveness: SocialLivenessV1,
    memory: SocialProgressMemoryV1,
    config: SocialProgressConfigV1,
    risk: float,
) -> SocialProgressDecisionV1:
    valid = (
        corridor is not None
        and _fresh(corridor, now, config)
        and corridor.visibility is VisibilityStateV1.EXPLICIT_FREE
        and corridor.corridor_fully_observed
        and not corridor.contradictory_track_ids
        and risk <= config.resume_risk_upper_bound
    )
    if not valid:
        age = corridor.age_s(now) if corridor is not None else None
        stale = corridor is not None and not _fresh(corridor, now, config)
        return _decision(
            state=SocialProgressStateV1.HOLD_UNCERTAIN,
            cause=(
                SocialBlockCauseV1.STALE_SENSOR
                if stale
                else SocialBlockCauseV1.CLEAR_STREAK_INCOMPLETE
            ),
            proposal=SocialProposalV1.CONTINUE_PLANNING,
            blocker_id=None,
            evidence_age_s=age,
            clear_streak=0,
            risk_upper_bound=risk,
            recovery_budget_remaining=memory.recovery_budget_remaining,
            release_required=True,
            last_clear_evidence_id=None,
        )
    assert corridor is not None
    streak = memory.clear_streak
    if corridor.evidence_id != memory.last_clear_evidence_id:
        streak = min(streak + 1, config.clear_streak_required)
    if streak < config.clear_streak_required:
        return _decision(
            state=SocialProgressStateV1.HOLD_UNCERTAIN,
            cause=SocialBlockCauseV1.CLEAR_STREAK_INCOMPLETE,
            proposal=SocialProposalV1.CONTINUE_PLANNING,
            blocker_id=None,
            evidence_age_s=corridor.age_s(now),
            clear_streak=streak,
            risk_upper_bound=risk,
            recovery_budget_remaining=memory.recovery_budget_remaining,
            release_required=True,
            last_clear_evidence_id=corridor.evidence_id,
        )
    if liveness.stable_progress_confirmed:
        return _decision(
            state=SocialProgressStateV1.TRACK,
            cause=SocialBlockCauseV1.NONE,
            proposal=SocialProposalV1.CONTINUE_PLANNING,
            blocker_id=None,
            evidence_age_s=corridor.age_s(now),
            clear_streak=0,
            risk_upper_bound=risk,
            recovery_budget_remaining=config.initial_recovery_budget,
            release_required=False,
            last_clear_evidence_id=None,
        )
    return _decision(
        state=SocialProgressStateV1.PROBE_RESUME,
        cause=SocialBlockCauseV1.NONE,
        proposal=SocialProposalV1.PROBE_RESUME_CANDIDATE,
        blocker_id=None,
        evidence_age_s=corridor.age_s(now),
        clear_streak=streak,
        risk_upper_bound=risk,
        recovery_budget_remaining=memory.recovery_budget_remaining,
        release_required=True,
        last_clear_evidence_id=corridor.evidence_id,
        resume_eligible=True,
    )


def _steady_decision(
    *,
    semantics: SemanticContextV1,
    liveness: SocialLivenessV1,
    memory: SocialProgressMemoryV1,
    config: SocialProgressConfigV1,
    risk: float,
) -> SocialProgressDecisionV1:
    if (
        _generic_recovery_allowed(semantics)
        and liveness.reciprocal_oscillation
        and liveness.passing_side_candidate is not None
    ):
        proposal = (
            SocialProposalV1.COMMIT_PASS_LEFT_CANDIDATE
            if liveness.passing_side_candidate is PassingSideV1.LEFT
            else SocialProposalV1.COMMIT_PASS_RIGHT_CANDIDATE
        )
        return _decision(
            state=SocialProgressStateV1.COMMIT_PASSING_SIDE,
            cause=SocialBlockCauseV1.RECIPROCAL_OSCILLATION,
            proposal=proposal,
            blocker_id=None,
            evidence_age_s=None,
            clear_streak=0,
            risk_upper_bound=risk,
            recovery_budget_remaining=memory.recovery_budget_remaining,
            release_required=False,
            last_clear_evidence_id=None,
        )
    state = SocialProgressStateV1.TRACK
    cause = SocialBlockCauseV1.NONE
    proposal = SocialProposalV1.CONTINUE_PLANNING
    if risk >= config.slow_risk_upper_bound:
        state = SocialProgressStateV1.SLOW_YIELD
        cause = SocialBlockCauseV1.TRUE_DYNAMIC_BLOCK
        proposal = SocialProposalV1.SLOW_YIELD_CANDIDATE
    return _decision(
        state=state,
        cause=cause,
        proposal=proposal,
        blocker_id=None,
        evidence_age_s=None,
        clear_streak=0,
        risk_upper_bound=risk,
        recovery_budget_remaining=memory.recovery_budget_remaining,
        release_required=False,
        last_clear_evidence_id=None,
    )


def decide_social_progress(
    *,
    now_monotonic_s: float,
    tracks: tuple[SocialTrackEvidenceV1, ...],
    corridor_evidence: VisibilityEvidenceV1 | None,
    semantics: SemanticContextV1,
    liveness: SocialLivenessV1,
    memory: SocialProgressMemoryV1 | None = None,
    config: SocialProgressConfigV1 | None = None,
) -> SocialProgressDecisionV1:
    """Return one non-authoritative, deterministic planning proposal."""

    now, cfg, mem, risk = _validated_inputs(
        now_monotonic_s=now_monotonic_s,
        tracks=tracks,
        corridor_evidence=corridor_evidence,
        semantics=semantics,
        liveness=liveness,
        memory=memory,
        config=config,
    )
    if not cfg.enabled:
        return _decision(
            state=SocialProgressStateV1.TRACK,
            cause=SocialBlockCauseV1.FEATURE_DISABLED,
            proposal=SocialProposalV1.NONE,
            blocker_id=None,
            evidence_age_s=None,
            clear_streak=0,
            risk_upper_bound=risk,
            recovery_budget_remaining=mem.recovery_budget_remaining,
            release_required=False,
            last_clear_evidence_id=None,
        )
    early = _health_or_semantic_decision(
        semantics=semantics,
        liveness=liveness,
        memory=mem,
        risk=risk,
    )
    if early is not None:
        return early
    blocked = _track_block_decision(
        now=now,
        tracks=tracks,
        semantics=semantics,
        liveness=liveness,
        memory=mem,
        config=cfg,
        risk=risk,
    )
    if blocked is not None:
        return blocked
    if mem.release_certificate_required:
        return _release_decision(
            now=now,
            corridor=corridor_evidence,
            liveness=liveness,
            memory=mem,
            config=cfg,
            risk=risk,
        )
    return _steady_decision(
        semantics=semantics,
        liveness=liveness,
        memory=mem,
        config=cfg,
        risk=risk,
    )


__all__ = ["decide_social_progress"]
