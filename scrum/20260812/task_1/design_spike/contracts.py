"""Executable design contracts for the production-companion proposal.

This module is intentionally isolated from ``src/parcel_robot``.  It is a
review artifact, not a second runtime.  The point is to make the proposed
authority rules falsifiable before any product migration begins.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import Enum, IntEnum

SCHEMA_VERSION = 1


class EvidenceOrigin(str, Enum):
    PHYSICAL = "physical"
    SIMULATION = "simulation"
    REPLAY = "replay"


class AuthorityDisposition(IntEnum):
    """Ordered so composition can only become more restrictive."""

    PASS = 0
    CLAMP = 1
    HOLD = 2
    STOP = 3
    LATCHED_STOP = 4


class OwnerTrackState(str, Enum):
    UNENROLLED = "unenrolled"
    ACQUIRING = "acquiring"
    LOCKED = "locked"
    OCCLUDED = "occluded"
    AMBIGUOUS = "ambiguous"
    SEARCHING = "searching"
    HOLD = "hold"


class ProposalKind(str, Enum):
    DETERMINISTIC = "deterministic"
    LEARNED = "learned"


class Resource(str, Enum):
    BASE = "base"
    POSTURE = "posture"
    VOICE = "voice"
    ATTENTION = "attention"


@dataclass(frozen=True, slots=True)
class EvidenceEnvelopeV2:
    """One authority-bearing sample at a process boundary.

    ``received_at_monotonic_s`` is the only watchdog clock.  A device/source
    timestamp is retained for alignment and debugging, but is not trusted for
    host freshness until a clock mapper has bounded its uncertainty.
    """

    stream_id: str
    sequence: int
    origin: EvidenceOrigin
    received_at_monotonic_s: float
    frame_id: str
    calibration_epoch: str
    payload_valid: bool = True
    captured_at_source_s: float | None = None
    clock_uncertainty_ms: float | None = None

    def __post_init__(self) -> None:
        if not self.stream_id or len(self.stream_id) > 96:
            raise ValueError("stream_id must be short and non-empty")
        if isinstance(self.sequence, bool) or self.sequence < 1:
            raise ValueError("sequence must be a positive integer")
        if not isinstance(self.origin, EvidenceOrigin):
            raise TypeError("origin must be typed EvidenceOrigin")
        if not math.isfinite(self.received_at_monotonic_s):
            raise ValueError("receive timestamp must be finite")
        if not self.frame_id or not self.calibration_epoch:
            raise ValueError("frame and calibration epoch are required")
        if self.captured_at_source_s is not None and not math.isfinite(self.captured_at_source_s):
            raise ValueError("source timestamp must be finite when present")
        if self.clock_uncertainty_ms is not None and (
            not math.isfinite(self.clock_uncertainty_ms) or self.clock_uncertainty_ms < 0.0
        ):
            raise ValueError("clock uncertainty must be finite and non-negative")

    def age_s(self, now_monotonic_s: float) -> float:
        return now_monotonic_s - self.received_at_monotonic_s


@dataclass(frozen=True, slots=True)
class RequiredEvidenceV1:
    stream_id: str
    frame_id: str
    max_age_s: float
    allowed_origins: frozenset[EvidenceOrigin] = frozenset({EvidenceOrigin.PHYSICAL})

    def __post_init__(self) -> None:
        if not self.stream_id or not self.frame_id:
            raise ValueError("required stream and frame must be non-empty")
        if not math.isfinite(self.max_age_s) or self.max_age_s <= 0.0:
            raise ValueError("max_age_s must be positive and finite")
        if not self.allowed_origins:
            raise ValueError("at least one evidence origin must be allowed")


@dataclass(frozen=True, slots=True)
class SafetyVerdictV1:
    disposition: AuthorityDisposition
    reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.disposition, AuthorityDisposition):
            raise TypeError("disposition must be typed")
        if any(not reason for reason in self.reasons):
            raise ValueError("safety reasons must be non-empty strings")


def dominant_verdict(*verdicts: SafetyVerdictV1) -> SafetyVerdictV1:
    """Compose independent gates without allowing a downstream relaxation."""

    if not verdicts:
        return SafetyVerdictV1(AuthorityDisposition.PASS)
    disposition = max(verdict.disposition for verdict in verdicts)
    reasons = tuple(
        reason
        for verdict in verdicts
        if verdict.disposition == disposition
        for reason in verdict.reasons
    )
    return SafetyVerdictV1(disposition, reasons)


def join_evidence(
    required: Iterable[RequiredEvidenceV1],
    current: Mapping[str, EvidenceEnvelopeV2],
    *,
    now_monotonic_s: float,
    future_tolerance_s: float = 0.05,
) -> SafetyVerdictV1:
    """Fail closed over the current pose, geometry, and feedback evidence."""

    faults: list[SafetyVerdictV1] = []
    if not math.isfinite(now_monotonic_s):
        return SafetyVerdictV1(AuthorityDisposition.LATCHED_STOP, ("decision_clock_malformed",))
    for spec in required:
        sample = current.get(spec.stream_id)
        if sample is None:
            faults.append(
                SafetyVerdictV1(AuthorityDisposition.HOLD, (f"{spec.stream_id}:missing",))
            )
            continue
        if sample.stream_id != spec.stream_id:
            faults.append(
                SafetyVerdictV1(
                    AuthorityDisposition.LATCHED_STOP,
                    (f"{spec.stream_id}:stream_mismatch",),
                )
            )
        if sample.origin not in spec.allowed_origins:
            faults.append(
                SafetyVerdictV1(
                    AuthorityDisposition.LATCHED_STOP,
                    (f"{spec.stream_id}:origin_not_commissioned",),
                )
            )
        if sample.frame_id != spec.frame_id:
            faults.append(
                SafetyVerdictV1(
                    AuthorityDisposition.LATCHED_STOP,
                    (f"{spec.stream_id}:frame_mismatch",),
                )
            )
        if sample.payload_valid is not True:
            faults.append(
                SafetyVerdictV1(
                    AuthorityDisposition.LATCHED_STOP,
                    (f"{spec.stream_id}:payload_invalid",),
                )
            )
        age_s = sample.age_s(now_monotonic_s)
        if age_s < -future_tolerance_s:
            faults.append(
                SafetyVerdictV1(
                    AuthorityDisposition.LATCHED_STOP,
                    (f"{spec.stream_id}:receive_time_in_future",),
                )
            )
        elif age_s > spec.max_age_s:
            faults.append(SafetyVerdictV1(AuthorityDisposition.HOLD, (f"{spec.stream_id}:stale",)))
    return dominant_verdict(*faults)


@dataclass(frozen=True, slots=True)
class TaskTransactionV2:
    task_id: str
    revision: int
    source_turn_id: str
    owner_authorized: bool
    created_at_monotonic_s: float
    valid_until_monotonic_s: float

    def __post_init__(self) -> None:
        if not self.task_id or not self.source_turn_id:
            raise ValueError("task and source turn IDs are required")
        if isinstance(self.revision, bool) or self.revision < 1:
            raise ValueError("revision must be positive")
        if not all(
            math.isfinite(value)
            for value in (
                self.created_at_monotonic_s,
                self.valid_until_monotonic_s,
            )
        ):
            raise ValueError("task timestamps must be finite")
        if self.valid_until_monotonic_s <= self.created_at_monotonic_s:
            raise ValueError("task validity must follow creation")


@dataclass(frozen=True, slots=True)
class HardwareCapabilityManifestV1:
    platform_id: str
    body_velocity: bool
    lateral_velocity: bool
    max_vx_mps: float
    max_vy_mps: float
    max_yaw_rps: float
    commissioned: bool

    def __post_init__(self) -> None:
        if not self.platform_id:
            raise ValueError("platform_id is required")
        limits = (self.max_vx_mps, self.max_vy_mps, self.max_yaw_rps)
        if any(not math.isfinite(value) or value <= 0.0 for value in limits):
            raise ValueError("capability limits must be positive and finite")


@dataclass(frozen=True, slots=True)
class MotionCandidateV2:
    """A proposed short horizon, never an actuator command."""

    task_id: str
    task_revision: int
    producer: str
    kind: ProposalKind
    sequence: int
    issued_at_monotonic_s: float
    valid_until_monotonic_s: float
    frame_id: str
    vx_mps: float
    vy_mps: float
    yaw_rps: float
    evidence_sequences: tuple[tuple[str, int], ...]

    def __post_init__(self) -> None:
        if not self.task_id or not self.producer:
            raise ValueError("candidate task and producer are required")
        if isinstance(self.task_revision, bool) or self.task_revision < 1:
            raise ValueError("candidate revision must be positive")
        if isinstance(self.sequence, bool) or self.sequence < 1:
            raise ValueError("candidate sequence must be positive")
        if self.frame_id != "base_link":
            raise ValueError("motion candidate must be in base_link")
        values = (
            self.issued_at_monotonic_s,
            self.valid_until_monotonic_s,
            self.vx_mps,
            self.vy_mps,
            self.yaw_rps,
        )
        if any(not math.isfinite(value) for value in values):
            raise ValueError("candidate values must be finite")
        if self.valid_until_monotonic_s <= self.issued_at_monotonic_s:
            raise ValueError("candidate deadline must follow issuance")
        streams = [stream for stream, _ in self.evidence_sequences]
        if len(streams) != len(set(streams)):
            raise ValueError("candidate evidence streams must be unique")
        if any(not stream or sequence < 1 for stream, sequence in self.evidence_sequences):
            raise ValueError("candidate evidence references must be valid")


@dataclass(frozen=True, slots=True)
class LeaseV1:
    writer_id: str
    epoch: int
    valid_until_monotonic_s: float

    def __post_init__(self) -> None:
        if not self.writer_id:
            raise ValueError("writer_id is required")
        if isinstance(self.epoch, bool) or self.epoch < 1:
            raise ValueError("lease epoch must be positive")
        if not math.isfinite(self.valid_until_monotonic_s):
            raise ValueError("lease deadline must be finite")


def candidate_verdict(
    candidate: MotionCandidateV2,
    *,
    task: TaskTransactionV2,
    capability: HardwareCapabilityManifestV1,
    lease: LeaseV1,
    expected_writer_id: str,
    now_monotonic_s: float,
    current_evidence: Mapping[str, EvidenceEnvelopeV2],
) -> SafetyVerdictV1:
    """Admission gates that remain deterministic for learned candidates."""

    reasons: list[str] = []
    severity = AuthorityDisposition.PASS

    def fault(disposition: AuthorityDisposition, reason: str) -> None:
        nonlocal severity
        severity = max(severity, disposition)
        reasons.append(reason)

    if not capability.commissioned or not capability.body_velocity:
        fault(AuthorityDisposition.LATCHED_STOP, "platform_not_commissioned")
    if not task.owner_authorized:
        fault(AuthorityDisposition.HOLD, "task_not_owner_authorized")
    if candidate.task_id != task.task_id or candidate.task_revision != task.revision:
        fault(AuthorityDisposition.HOLD, "stale_task_revision")
    if now_monotonic_s >= task.valid_until_monotonic_s:
        fault(AuthorityDisposition.HOLD, "task_expired")
    if now_monotonic_s >= candidate.valid_until_monotonic_s:
        fault(AuthorityDisposition.HOLD, "candidate_expired")
    if lease.writer_id != expected_writer_id:
        fault(AuthorityDisposition.LATCHED_STOP, "writer_mismatch")
    if now_monotonic_s >= lease.valid_until_monotonic_s:
        fault(AuthorityDisposition.STOP, "lease_expired")
    if not capability.lateral_velocity and abs(candidate.vy_mps) > 1e-9:
        fault(AuthorityDisposition.HOLD, "lateral_velocity_unsupported")
    if abs(candidate.vx_mps) > capability.max_vx_mps:
        fault(AuthorityDisposition.HOLD, "vx_limit_exceeded")
    if abs(candidate.vy_mps) > capability.max_vy_mps:
        fault(AuthorityDisposition.HOLD, "vy_limit_exceeded")
    if abs(candidate.yaw_rps) > capability.max_yaw_rps:
        fault(AuthorityDisposition.HOLD, "yaw_limit_exceeded")

    for stream_id, sequence in candidate.evidence_sequences:
        current = current_evidence.get(stream_id)
        if current is None or current.sequence != sequence:
            fault(AuthorityDisposition.HOLD, f"{stream_id}:evidence_revision_changed")

    # Retain only reasons at the winning severity in the production contract;
    # this spike keeps all reasons so a reviewer can inspect every simultaneous
    # fault while still enforcing the winning disposition.
    return SafetyVerdictV1(severity, tuple(reasons))


def owner_motion_verdict(
    state: OwnerTrackState,
    *,
    candidate_is_translation: bool,
) -> SafetyVerdictV1:
    """Identity ambiguity never turns into following the most convenient person."""

    if not candidate_is_translation:
        return SafetyVerdictV1(AuthorityDisposition.PASS)
    if state is OwnerTrackState.LOCKED:
        return SafetyVerdictV1(AuthorityDisposition.PASS)
    if state is OwnerTrackState.OCCLUDED:
        return SafetyVerdictV1(AuthorityDisposition.HOLD, ("owner_occluded",))
    if state in {OwnerTrackState.AMBIGUOUS, OwnerTrackState.HOLD}:
        return SafetyVerdictV1(AuthorityDisposition.HOLD, ("owner_identity_ambiguous",))
    return SafetyVerdictV1(AuthorityDisposition.HOLD, ("owner_not_locked",))


@dataclass(frozen=True, slots=True)
class BehaviorProposalV2:
    name: str
    resources: frozenset[Resource]
    emergency: bool
    valid_until_monotonic_s: float


def behavior_verdict(
    proposal: BehaviorProposalV2,
    *,
    navigation_owns_base: bool,
    now_monotonic_s: float,
) -> SafetyVerdictV1:
    if proposal.emergency:
        return SafetyVerdictV1(AuthorityDisposition.LATCHED_STOP, ("emergency",))
    if now_monotonic_s >= proposal.valid_until_monotonic_s:
        return SafetyVerdictV1(AuthorityDisposition.HOLD, ("behavior_expired",))
    if navigation_owns_base and Resource.BASE in proposal.resources:
        return SafetyVerdictV1(AuthorityDisposition.HOLD, ("base_owned_by_navigation",))
    return SafetyVerdictV1(AuthorityDisposition.PASS)


@dataclass(frozen=True, slots=True)
class TerminalWitnessV2:
    task_id: str
    task_revision: int
    predicate_true: bool
    observed_at_monotonic_s: float
    evidence_sequences: tuple[tuple[str, int], ...]
    settled_samples: int


def terminal_verdict(
    witness: TerminalWitnessV2,
    *,
    task: TaskTransactionV2,
    current_evidence: Mapping[str, EvidenceEnvelopeV2],
    now_monotonic_s: float,
    max_age_s: float,
    required_settled_samples: int,
) -> SafetyVerdictV1:
    reasons: list[str] = []
    if witness.task_id != task.task_id or witness.task_revision != task.revision:
        reasons.append("terminal_task_revision_mismatch")
    if not witness.predicate_true:
        reasons.append("terminal_predicate_false")
    if now_monotonic_s - witness.observed_at_monotonic_s > max_age_s:
        reasons.append("terminal_evidence_stale")
    if witness.observed_at_monotonic_s > now_monotonic_s + 0.05:
        reasons.append("terminal_time_in_future")
    if witness.settled_samples < required_settled_samples:
        reasons.append("robot_not_settled")
    for stream_id, sequence in witness.evidence_sequences:
        current = current_evidence.get(stream_id)
        if current is None or current.sequence != sequence:
            reasons.append(f"{stream_id}:terminal_evidence_changed")
    if reasons:
        return SafetyVerdictV1(AuthorityDisposition.HOLD, tuple(reasons))
    return SafetyVerdictV1(AuthorityDisposition.PASS)


__all__ = [
    "AuthorityDisposition",
    "BehaviorProposalV2",
    "EvidenceEnvelopeV2",
    "EvidenceOrigin",
    "HardwareCapabilityManifestV1",
    "LeaseV1",
    "MotionCandidateV2",
    "OwnerTrackState",
    "ProposalKind",
    "RequiredEvidenceV1",
    "Resource",
    "SafetyVerdictV1",
    "TaskTransactionV2",
    "TerminalWitnessV2",
    "behavior_verdict",
    "candidate_verdict",
    "dominant_verdict",
    "join_evidence",
    "owner_motion_verdict",
    "terminal_verdict",
]
