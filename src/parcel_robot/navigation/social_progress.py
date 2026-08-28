"""Public facade for the proposal-only social-progress contract and policy.

The dependency graph is deliberately acyclic: value contracts are a leaf,
the deterministic policy consumes them, and this compatibility facade
re-exports both for existing callers.
"""

from __future__ import annotations

from parcel_robot.navigation.social_progress_contracts import (
    MAX_PUBLIC_INTEGER,
    MAX_TRACK_CLASS_ID_CHARS,
    MAX_TRACK_COVARIANCE_ENTRIES,
    MAX_TRACK_ID_CHARS,
    CrosswalkPhaseV1,
    ElevatorPhaseV1,
    FlowRoleV1,
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
)
from parcel_robot.navigation.social_progress_policy import decide_social_progress


def decide_social_progress_observation(
    observation: SocialProgressObservationV1,
    *,
    memory: SocialProgressMemoryV1 | None = None,
    config: SocialProgressConfigV1 | None = None,
) -> SocialProgressDecisionV1:
    """Evaluate one already-grouped tick without allowing cross-tick mixing."""

    if not isinstance(observation, SocialProgressObservationV1):
        raise TypeError("observation must be SocialProgressObservationV1")
    return decide_social_progress(
        now_monotonic_s=observation.now_monotonic_s,
        tracks=observation.tracks,
        corridor_evidence=observation.corridor_evidence,
        semantics=observation.semantics,
        liveness=observation.liveness,
        memory=memory,
        config=config,
    )


__all__ = [
    "MAX_PUBLIC_INTEGER",
    "MAX_TRACK_CLASS_ID_CHARS",
    "MAX_TRACK_COVARIANCE_ENTRIES",
    "MAX_TRACK_ID_CHARS",
    "CrosswalkPhaseV1",
    "ElevatorPhaseV1",
    "FlowRoleV1",
    "PassingSideV1",
    "SemanticContextV1",
    "SocialBlockCauseV1",
    "SocialLivenessV1",
    "SocialProgressConfigV1",
    "SocialProgressDecisionV1",
    "SocialProgressMemoryV1",
    "SocialProgressObservationV1",
    "SocialProgressStateV1",
    "SocialProposalV1",
    "SocialTrackEvidenceV1",
    "SocialVenueV1",
    "VisibilityEvidenceV1",
    "VisibilityStateV1",
    "decide_social_progress",
    "decide_social_progress_observation",
]
