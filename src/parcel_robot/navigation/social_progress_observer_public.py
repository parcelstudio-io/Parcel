"""Bounded JSON-ready projection of retained social-progress evidence."""

from __future__ import annotations

import hashlib
import math

from parcel_robot.navigation.social_progress import (
    SocialProgressDecisionV1,
    SocialTrackEvidenceV1,
    VisibilityEvidenceV1,
    VisibilityStateV1,
)
from parcel_robot.navigation.social_progress_observer_contracts import (
    PlannerFactsV1,
    SocialProgressObserverSampleV1,
    VelocityEvidenceV1,
    VelocityPrimitiveV1,
)


def public_primitive(value: VelocityPrimitiveV1) -> dict[str, float]:
    return {
        "vx_mps": value.vx_mps,
        "vy_mps": value.vy_mps,
        "wz_radps": value.wz_radps,
    }


def public_velocity(value: VelocityEvidenceV1) -> dict[str, object]:
    return {
        "primitive": public_primitive(value.primitive),
        "source": value.source,
        "sequence": value.sequence,
        "sample_monotonic_s": value.sample_monotonic_s,
        "age_s": value.age_s,
        "fresh": value.fresh,
    }


def public_planner(value: PlannerFactsV1) -> dict[str, object]:
    return {
        "mission_status": value.mission_status,
        "route_status": value.route_status,
        "planner_healthy": value.planner_healthy,
        "body_is_still": value.body_is_still,
        "steps_gate_blocked": value.steps_gate_blocked,
        "progress_demand": value.progress_demand,
        "paused": value.paused,
        "has_mission": value.has_mission,
        "steps_without_progress": value.steps_without_progress,
        "terminal_verification_steps": value.terminal_verification_steps,
    }


def public_corridor(
    value: VisibilityEvidenceV1 | None,
    *,
    detailed: bool,
) -> dict[str, object] | None:
    if value is None:
        return None
    row: dict[str, object] = {
        "evidence_id": value.evidence_id,
        "visibility": value.visibility.value,
    }
    if detailed:
        row.update(
            {
                "source_monotonic_s": value.source_monotonic_s,
                "receive_monotonic_s": value.receive_monotonic_s,
                "corridor_fully_observed": value.corridor_fully_observed,
                "corridor_coverage": value.corridor_coverage,
                "camera_evidence_count": len(value.camera_evidence_refs),
                "lidar_mark_evidence_count": len(value.lidar_mark_evidence_refs),
                "lidar_clear_evidence_count": len(value.lidar_clear_evidence_refs),
                "contradictory_track_count": len(value.contradictory_track_ids),
            }
        )
    return row


def public_identifier(value: str | None) -> str | None:
    """Fixed-size diagnostic correlation ref; never expose attacker-sized IDs."""

    if value is None:
        return None
    return f"sha256:{hashlib.sha256(value.encode('utf-8')).hexdigest()}"


def public_decision(
    value: SocialProgressDecisionV1,
    *,
    detailed: bool,
) -> dict[str, object]:
    row: dict[str, object] = {
        "state": value.state.value,
        "cause": value.cause.value,
        "proposal": value.proposal.value,
    }
    if detailed:
        row.update(
            {
                "blocker_ref": public_identifier(value.blocker_id),
                "evidence_age_s": value.evidence_age_s,
                "clear_streak": value.clear_streak,
                "risk_upper_bound": value.risk_upper_bound,
                "recovery_budget_remaining": value.recovery_budget_remaining,
                "resume_eligible": value.resume_eligible,
                "requires_downstream_safety_gate": value.requires_downstream_safety_gate,
                "authorizes_motion": value.authorizes_motion,
                "next_memory": {
                    "prior_state": value.next_memory.prior_state.value,
                    "release_certificate_required": (
                        value.next_memory.release_certificate_required
                    ),
                    "clear_streak": value.next_memory.clear_streak,
                    "last_clear_evidence_id": value.next_memory.last_clear_evidence_id,
                    "recovery_budget_remaining": (value.next_memory.recovery_budget_remaining),
                },
            }
        )
    return row


def track_counts(
    sample: SocialProgressObserverSampleV1,
) -> tuple[dict[str, int], dict[str, int]]:
    visibility = {state.value: 0 for state in VisibilityStateV1}
    in_corridor = 0
    within_hard = 0
    for row in sample.tracks:
        visibility[row.visibility_evidence.visibility.value] += 1
        in_corridor += int(row.in_swept_corridor)
        within_hard += int(row.within_hard_envelope)
    counts = {
        "total": len(sample.tracks),
        "in_swept_corridor": in_corridor,
        "within_hard_envelope": within_hard,
    }
    return counts, visibility


def public_track(value: SocialTrackEvidenceV1) -> dict[str, object]:
    covariance_entries = len(value.track.covariance)
    dimension = math.isqrt(covariance_entries)
    if dimension * dimension != covariance_entries:
        dimension = 0
    evidence = value.visibility_evidence
    return {
        "track": {
            "track_ref": public_identifier(value.track.track_id),
            "class_ref": public_identifier(value.track.class_id),
            "x": value.track.x,
            "y": value.track.y,
            "vx": value.track.vx,
            "vy": value.track.vy,
            "radius_m": value.track.radius_m,
            "yaw_rad": value.track.yaw_rad,
            "confidence": value.track.confidence,
        },
        "covariance_metadata": {
            "entry_count": covariance_entries,
            "square_dimension": dimension or None,
        },
        "existence_probability": value.existence_probability,
        "in_swept_corridor": value.in_swept_corridor,
        "risk_upper_bound": value.risk_upper_bound,
        "within_hard_envelope": value.within_hard_envelope,
        "owner_identity_lineage_count": len(value.owner_identity_lineage),
        "owner_identity_probability": value.owner_identity_probability,
        "group_ref": public_identifier(value.group_id),
        "flow_role": value.flow_role.value,
        "visibility_evidence": {
            "evidence_id": evidence.evidence_id,
            "visibility": evidence.visibility.value,
            "source_monotonic_s": evidence.source_monotonic_s,
            "receive_monotonic_s": evidence.receive_monotonic_s,
            "corridor_fully_observed": evidence.corridor_fully_observed,
            "corridor_coverage": evidence.corridor_coverage,
            "camera_evidence_count": len(evidence.camera_evidence_refs),
            "lidar_mark_evidence_count": len(evidence.lidar_mark_evidence_refs),
            "lidar_clear_evidence_count": len(evidence.lidar_clear_evidence_refs),
            "contradictory_track_count": len(evidence.contradictory_track_ids),
        },
    }


def public_latest(sample: SocialProgressObserverSampleV1) -> dict[str, object]:
    counts, visibility = track_counts(sample)
    return {
        "record_schema": "social_progress_latest_v1",
        "sample_sequence": sample.sample_sequence,
        "navigation_generation": sample.navigation_generation,
        "observed_monotonic_s": sample.observed_monotonic_s,
        "snapshot_missing": sample.snapshot_missing,
        "snapshot_revision": sample.snapshot_revision,
        "snapshot_assembled_monotonic_ns": sample.snapshot_assembled_monotonic_ns,
        "snapshot_evidence_ids": list(sample.snapshot_evidence_ids),
        "snapshot_epochs": [list(row) for row in sample.snapshot_epochs],
        "requested_velocity": public_velocity(sample.requested_velocity),
        "final_velocity": public_velocity(sample.final_velocity),
        "achieved_velocity": public_velocity(sample.achieved_velocity),
        "planner": public_planner(sample.planner),
        "track_counts": counts,
        "visibility_counts": visibility,
        "tracks": [public_track(row) for row in sample.tracks],
        "corridor_evidence": public_corridor(sample.corridor_evidence, detailed=True),
        "decision": public_decision(sample.decision, detailed=True),
    }


def public_summary(sample: SocialProgressObserverSampleV1) -> dict[str, object]:
    counts, visibility = track_counts(sample)
    return {
        "record_schema": "social_progress_summary_v1",
        "sample_sequence": sample.sample_sequence,
        "navigation_generation": sample.navigation_generation,
        "observed_monotonic_s": sample.observed_monotonic_s,
        "snapshot_missing": sample.snapshot_missing,
        "snapshot_revision": sample.snapshot_revision,
        "requested_velocity": public_primitive(sample.requested_velocity.primitive),
        "final_velocity": public_primitive(sample.final_velocity.primitive),
        "achieved_velocity": public_primitive(sample.achieved_velocity.primitive),
        "planner": {
            "planner_healthy": sample.planner.planner_healthy,
            "progress_demand": sample.planner.progress_demand,
            "body_is_still": sample.planner.body_is_still,
            "steps_gate_blocked": sample.planner.steps_gate_blocked,
            "steps_without_progress": sample.planner.steps_without_progress,
        },
        "track_counts": counts,
        "visibility_counts": visibility,
        "corridor_evidence": public_corridor(sample.corridor_evidence, detailed=False),
        "decision": public_decision(sample.decision, detailed=False),
    }


__all__ = ["public_latest", "public_summary"]
