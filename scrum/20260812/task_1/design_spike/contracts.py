"""Executable design contracts for the production-companion proposal.

This module is intentionally isolated from ``src/parcel_robot``.  It is a
review artifact, not a second runtime.  The point is to make the proposed
authority rules falsifiable before any product migration begins.

**Revision 2 (2026-08-12)** hardens the model against the Fable verdict
(``../FABLE_VERDICT.md``).  Revision 1 claimed invariants the code did not
enforce; the audit proved it with executed probes.  What changed:

* **RC-1a — boot epoch is enforced, not decoration.**  ``RobotGatewayV1`` is a
  stateful object whose fresh instance models a process restart: it starts
  ``DISARMED`` and cannot be constructed armed.  A lease whose epoch is not the
  gateway's current boot epoch cannot arm it, and a motion candidate presented
  under such a lease latches.
* **RC-1b — malformed time fails closed.**  Every clock, timestamp, TTL and
  reserve field is checked with :func:`_finite`, which is false for ``None``,
  ``NaN``, ``inf`` and non-numeric objects.  Comparison-only guards are the
  defect the audit found: ``NaN`` makes every comparison ``False``, so a bare
  ``if now >= deadline`` fails *open*.  Both the constructors and the verdict
  functions check, because a payload can cross a process boundary without
  re-running ``__post_init__``.
* **RC-1c — the latch is stateful.**  ``LATCHED_STOP`` is folded into
  ``RobotGatewayV1`` state by :meth:`RobotGatewayV1.observe` and persists across
  subsequent clean ticks until :meth:`RobotGatewayV1.clear_latch` is given an
  explicit operator acknowledgement *and* fresh physical stationary feedback.
* **RC-2 — the terminal witness carries a localization-uncertainty reserve.**
  ``TerminalWitnessV2`` requires both the arrival margin and the claim-tick pose
  uncertainty, and arrival is refused when the margin does not cover the
  reserve (the measured backlog B5 class).
* **N-1/N-2/N-3/N-4** — in-place search needs fresh surrounding collision
  evidence; :func:`authorize_motion` enforces the composition end to end instead
  of trusting the caller; a zero-gate composition is ``HOLD`` and
  :func:`speed_envelope_verdict` actually produces ``CLAMP``; ``Resource``
  carries the canonical six values.

What this model still does not prove is listed in ``README.md``.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import Enum, IntEnum

SCHEMA_VERSION = 2


def _finite(value: object) -> bool:
    """True only for a real, finite number.

    ``None``, ``NaN``, ``+/-inf``, ``bool`` and non-numeric objects are all
    false.  Every time-like field in this module is admitted through this
    predicate before any comparison, because a comparison against ``NaN`` is
    ``False`` and therefore fails open (RC-1b).
    """

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return math.isfinite(value)


def _positive_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def _non_negative_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


class EvidenceOrigin(str, Enum):
    """Where a sample came from.

    ``UNKNOWN`` exists so that un-provenanced input is *representable and
    refusable* rather than silently coerced to physical.  It is never a
    commissionable origin: :class:`RequiredEvidenceV1` rejects it outright.
    """

    PHYSICAL = "physical"
    SIMULATION = "simulation"
    REPLAY = "replay"
    UNKNOWN = "unknown"


#: The only origin that may authorize physical motion by default.
PHYSICAL_ONLY: frozenset[EvidenceOrigin] = frozenset({EvidenceOrigin.PHYSICAL})


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
    """The canonical six (N-4).

    The plan mandates one resource vocabulary; revision 1 of this spike shipped
    four values and so reproduced the dual-vocabulary defect it exists to retire.
    """

    BASE = "base"
    POSTURE = "posture"
    VOICE = "voice"
    ATTENTION = "attention"
    PERCEPTION_SCAN = "perception_scan"
    EXPRESSION_AUDIO = "expression_audio"


class GatewayPhase(str, Enum):
    """Persistent authority state of the sole-writer gateway."""

    DISARMED = "disarmed"
    ARMED = "armed"
    LATCHED = "latched"


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
        if not _positive_int(self.sequence):
            raise ValueError("sequence must be a positive integer")
        if not isinstance(self.origin, EvidenceOrigin):
            raise TypeError("origin must be typed EvidenceOrigin")
        if not _finite(self.received_at_monotonic_s):
            raise ValueError("receive timestamp must be finite")
        if not self.frame_id or not self.calibration_epoch:
            raise ValueError("frame and calibration epoch are required")
        if not isinstance(self.payload_valid, bool):
            raise TypeError("payload_valid must be a bool")
        if self.captured_at_source_s is not None and not _finite(self.captured_at_source_s):
            raise ValueError("source timestamp must be finite when present")
        if self.clock_uncertainty_ms is not None and (
            not _finite(self.clock_uncertainty_ms) or self.clock_uncertainty_ms < 0.0
        ):
            raise ValueError("clock uncertainty must be finite and non-negative")

    def age_s(self, now_monotonic_s: float) -> float:
        return now_monotonic_s - self.received_at_monotonic_s


@dataclass(frozen=True, slots=True)
class RequiredEvidenceV1:
    stream_id: str
    frame_id: str
    max_age_s: float
    allowed_origins: frozenset[EvidenceOrigin] = PHYSICAL_ONLY
    calibration_epoch: str | None = None

    def __post_init__(self) -> None:
        if not self.stream_id or not self.frame_id:
            raise ValueError("required stream and frame must be non-empty")
        if not _finite(self.max_age_s) or self.max_age_s <= 0.0:
            raise ValueError("max_age_s must be positive and finite")
        if not self.allowed_origins:
            raise ValueError("at least one evidence origin must be allowed")
        if any(not isinstance(origin, EvidenceOrigin) for origin in self.allowed_origins):
            raise TypeError("allowed origins must be typed EvidenceOrigin")
        if EvidenceOrigin.UNKNOWN in self.allowed_origins:
            raise ValueError("UNKNOWN origin can never be commissioned")


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
    """Compose independent gates without allowing a downstream relaxation.

    An empty gate set is a composition bug, not an authorization (N-3): there is
    no evidence that anything was evaluated, so the model holds.
    """

    if not verdicts:
        return SafetyVerdictV1(AuthorityDisposition.HOLD, ("no_gates_evaluated",))
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
    if not _finite(now_monotonic_s):
        return SafetyVerdictV1(AuthorityDisposition.LATCHED_STOP, ("decision_clock_malformed",))
    if not _finite(future_tolerance_s) or future_tolerance_s < 0.0:
        return SafetyVerdictV1(AuthorityDisposition.LATCHED_STOP, ("future_tolerance_malformed",))
    specs = tuple(required)
    if not specs:
        # Same class as a zero-gate composition (N-3): nothing was checked, so
        # there is no evidence of freshness to authorize on.
        return SafetyVerdictV1(AuthorityDisposition.HOLD, ("no_required_evidence",))
    for spec in specs:
        if not _finite(spec.max_age_s) or spec.max_age_s <= 0.0:
            faults.append(
                SafetyVerdictV1(
                    AuthorityDisposition.LATCHED_STOP,
                    (f"{spec.stream_id}:max_age_malformed",),
                )
            )
            continue
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
        pinned_epoch = spec.calibration_epoch
        if pinned_epoch is not None and sample.calibration_epoch != pinned_epoch:
            faults.append(
                SafetyVerdictV1(
                    AuthorityDisposition.LATCHED_STOP,
                    (f"{spec.stream_id}:calibration_epoch_mismatch",),
                )
            )
        if sample.payload_valid is not True:
            faults.append(
                SafetyVerdictV1(
                    AuthorityDisposition.LATCHED_STOP,
                    (f"{spec.stream_id}:payload_invalid",),
                )
            )
        if not _finite(sample.received_at_monotonic_s):
            faults.append(
                SafetyVerdictV1(
                    AuthorityDisposition.LATCHED_STOP,
                    (f"{spec.stream_id}:receive_time_malformed",),
                )
            )
            continue
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
    if not faults:
        return SafetyVerdictV1(AuthorityDisposition.PASS)
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
        if not _positive_int(self.revision):
            raise ValueError("revision must be positive")
        if not isinstance(self.owner_authorized, bool):
            raise TypeError("owner_authorized must be a bool")
        if not all(
            _finite(value)
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
        if any(not _finite(value) or value <= 0.0 for value in limits):
            raise ValueError("capability limits must be positive and finite")
        flags = (self.body_velocity, self.lateral_velocity, self.commissioned)
        if any(not isinstance(flag, bool) for flag in flags):
            raise TypeError("capability flags must be bools")


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
        if not _positive_int(self.task_revision):
            raise ValueError("candidate revision must be positive")
        if not _positive_int(self.sequence):
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
        if any(not _finite(value) for value in values):
            raise ValueError("candidate values must be finite")
        if self.valid_until_monotonic_s <= self.issued_at_monotonic_s:
            raise ValueError("candidate deadline must follow issuance")
        streams = [stream for stream, _ in self.evidence_sequences]
        if len(streams) != len(set(streams)):
            raise ValueError("candidate evidence streams must be unique")
        if any(not stream or not _positive_int(seq) for stream, seq in self.evidence_sequences):
            raise ValueError("candidate evidence references must be valid")


@dataclass(frozen=True, slots=True)
class LeaseV1:
    """A single-writer lease, valid only inside one gateway boot epoch."""

    writer_id: str
    epoch: int
    valid_until_monotonic_s: float

    def __post_init__(self) -> None:
        if not self.writer_id:
            raise ValueError("writer_id is required")
        if not _positive_int(self.epoch):
            raise ValueError("lease epoch must be positive")
        if not _finite(self.valid_until_monotonic_s):
            raise ValueError("lease deadline must be finite")


@dataclass(frozen=True, slots=True)
class StationaryWitnessV1:
    """Measured proof that the base is stopped — not a command echo.

    Clearing a latch requires this, so it must be physical: a simulated or
    replayed "we are stopped" is exactly the claim a latch exists to distrust.
    """

    origin: EvidenceOrigin
    observed_at_monotonic_s: float
    measured_speed_mps: float
    measured_yaw_rps: float
    settled_samples: int

    def __post_init__(self) -> None:
        if not isinstance(self.origin, EvidenceOrigin):
            raise TypeError("origin must be typed EvidenceOrigin")
        values = (
            self.observed_at_monotonic_s,
            self.measured_speed_mps,
            self.measured_yaw_rps,
        )
        if any(not _finite(value) for value in values):
            raise ValueError("stationary witness values must be finite")
        if not _non_negative_int(self.settled_samples):
            raise ValueError("settled_samples must be a non-negative integer")


def candidate_verdict(
    candidate: MotionCandidateV2,
    *,
    task: TaskTransactionV2,
    capability: HardwareCapabilityManifestV1,
    lease: LeaseV1,
    expected_writer_id: str,
    current_epoch: int,
    now_monotonic_s: float,
    current_evidence: Mapping[str, EvidenceEnvelopeV2],
) -> SafetyVerdictV1:
    """Admission gates that remain deterministic for learned candidates.

    This gate deliberately does **not** inspect evidence origin, frame or age —
    :func:`join_evidence` owns those.  Callers must therefore not use it alone;
    :func:`authorize_motion` is the enforced composition (N-2).
    """

    reasons: list[str] = []
    severity = AuthorityDisposition.PASS

    def fault(disposition: AuthorityDisposition, reason: str) -> None:
        nonlocal severity
        severity = max(severity, disposition)
        reasons.append(reason)

    # RC-1b: every comparison below is guarded, because `NaN >= x` is False and
    # an unguarded expiry check therefore authorizes a malformed payload.
    if not _finite(now_monotonic_s):
        return SafetyVerdictV1(AuthorityDisposition.LATCHED_STOP, ("decision_clock_malformed",))
    task_stamps = (task.created_at_monotonic_s, task.valid_until_monotonic_s)
    if not all(_finite(value) for value in task_stamps):
        fault(AuthorityDisposition.LATCHED_STOP, "task_time_malformed")
    if not _finite(lease.valid_until_monotonic_s):
        fault(AuthorityDisposition.LATCHED_STOP, "lease_time_malformed")
    if not all(
        _finite(value)
        for value in (candidate.issued_at_monotonic_s, candidate.valid_until_monotonic_s)
    ):
        fault(AuthorityDisposition.LATCHED_STOP, "candidate_time_malformed")
    if not all(
        _finite(value) for value in (candidate.vx_mps, candidate.vy_mps, candidate.yaw_rps)
    ):
        fault(AuthorityDisposition.LATCHED_STOP, "candidate_command_malformed")
    if severity is AuthorityDisposition.LATCHED_STOP:
        return SafetyVerdictV1(severity, tuple(reasons))

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
    # RC-1a: a lease minted in another boot epoch has no authority here.  A
    # writer that survived the gateway's restart is exactly the "resume prior
    # work" hazard the disarm rule exists for.
    if not _positive_int(current_epoch):
        fault(AuthorityDisposition.LATCHED_STOP, "gateway_epoch_malformed")
    elif lease.epoch != current_epoch:
        fault(AuthorityDisposition.LATCHED_STOP, "lease_epoch_mismatch")
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
    """Identity ambiguity never turns into following the most convenient person.

    Scope is deliberately narrow: this gate answers "may we translate toward the
    believed owner", not "is it safe to move".  The in-place case is guarded by
    :func:`in_place_search_verdict` instead (N-1).
    """

    if not isinstance(state, OwnerTrackState):
        raise TypeError("owner state must be typed OwnerTrackState")
    if not isinstance(candidate_is_translation, bool):
        raise TypeError("candidate_is_translation must be a bool")
    if not candidate_is_translation:
        return SafetyVerdictV1(AuthorityDisposition.PASS)
    if state is OwnerTrackState.LOCKED:
        return SafetyVerdictV1(AuthorityDisposition.PASS)
    if state is OwnerTrackState.OCCLUDED:
        return SafetyVerdictV1(AuthorityDisposition.HOLD, ("owner_occluded",))
    if state in {OwnerTrackState.AMBIGUOUS, OwnerTrackState.HOLD}:
        return SafetyVerdictV1(AuthorityDisposition.HOLD, ("owner_identity_ambiguous",))
    return SafetyVerdictV1(AuthorityDisposition.HOLD, ("owner_not_locked",))


def in_place_search_verdict(
    candidate: MotionCandidateV2,
    *,
    surrounding_evidence: EvidenceEnvelopeV2 | None,
    now_monotonic_s: float,
    max_age_s: float,
    allowed_origins: frozenset[EvidenceOrigin] = PHYSICAL_ONLY,
    translation_epsilon_mps: float = 1e-9,
) -> SafetyVerdictV1:
    """N-1: a bounded in-place search still needs fresh surrounding evidence.

    A yaw-only candidate is admitted by :func:`owner_motion_verdict` in every
    owner state by design.  That is only sound if something else proves the
    robot is not rotating into an obstacle it has no current evidence about.
    """

    if not _finite(now_monotonic_s):
        return SafetyVerdictV1(AuthorityDisposition.LATCHED_STOP, ("decision_clock_malformed",))
    if not _finite(max_age_s) or max_age_s <= 0.0:
        return SafetyVerdictV1(AuthorityDisposition.LATCHED_STOP, ("surround_max_age_malformed",))
    if not all(_finite(v) for v in (candidate.vx_mps, candidate.vy_mps, candidate.yaw_rps)):
        return SafetyVerdictV1(AuthorityDisposition.LATCHED_STOP, ("candidate_command_malformed",))
    translating = (
        abs(candidate.vx_mps) > translation_epsilon_mps
        or abs(candidate.vy_mps) > translation_epsilon_mps
    )
    rotating = abs(candidate.yaw_rps) > translation_epsilon_mps
    if translating or not rotating:
        return SafetyVerdictV1(AuthorityDisposition.PASS)
    if surrounding_evidence is None:
        return SafetyVerdictV1(AuthorityDisposition.HOLD, ("surround_evidence_missing",))
    if surrounding_evidence.origin not in allowed_origins:
        return SafetyVerdictV1(
            AuthorityDisposition.LATCHED_STOP, ("surround_origin_not_commissioned",)
        )
    if surrounding_evidence.payload_valid is not True:
        return SafetyVerdictV1(AuthorityDisposition.LATCHED_STOP, ("surround_payload_invalid",))
    if not _finite(surrounding_evidence.received_at_monotonic_s):
        return SafetyVerdictV1(AuthorityDisposition.LATCHED_STOP, ("surround_time_malformed",))
    if surrounding_evidence.age_s(now_monotonic_s) > max_age_s:
        return SafetyVerdictV1(AuthorityDisposition.HOLD, ("surround_evidence_stale",))
    return SafetyVerdictV1(AuthorityDisposition.PASS)


def speed_envelope_verdict(
    candidate: MotionCandidateV2,
    *,
    permitted_speed_mps: float,
) -> SafetyVerdictV1:
    """The evidence-derived speed envelope — the gate that produces CLAMP (N-3).

    Scope, stated so it is not over-read: this is a **magnitude-only** envelope.
    It does not model directional or closing relevance, which is exactly the
    wedge class backlog B6 measured on the product brake; that semantic belongs
    in the plan's final-governor spec (RC-3) and its product change is owner
    gated on B6.  See ``README.md``.
    """

    if not _finite(permitted_speed_mps) or permitted_speed_mps < 0.0:
        return SafetyVerdictV1(AuthorityDisposition.LATCHED_STOP, ("speed_envelope_malformed",))
    if not all(_finite(value) for value in (candidate.vx_mps, candidate.vy_mps)):
        return SafetyVerdictV1(AuthorityDisposition.LATCHED_STOP, ("candidate_command_malformed",))
    speed_mps = math.hypot(candidate.vx_mps, candidate.vy_mps)
    if speed_mps > permitted_speed_mps:
        return SafetyVerdictV1(AuthorityDisposition.CLAMP, ("speed_envelope_exceeded",))
    return SafetyVerdictV1(AuthorityDisposition.PASS)


@dataclass(slots=True)
class RobotGatewayV1:
    """The stateful half of the model: restart-disarm, sole writer, real latch.

    Revision 1 had no state at all, so two claimed invariants were unfalsifiable:
    "process restart is disarmed and cannot resume prior work" (RC-1a) and
    "malformed provenance latches" (RC-1c).  Both are properties of a *sequence*
    of ticks, so they need an object that remembers.

    Constructing an instance models a process boot: ``phase`` and ``lease`` are
    ``init=False``, so a fresh gateway cannot be born armed.
    """

    boot_epoch: int
    expected_writer_id: str
    # ``default_factory`` rather than ``default`` so the initial value is
    # assigned by ``__init__`` under ``slots=True`` on every supported Python.
    phase: GatewayPhase = field(init=False, default_factory=lambda: GatewayPhase.DISARMED)
    lease: LeaseV1 | None = field(init=False, default_factory=lambda: None)
    latch_reasons: tuple[str, ...] = field(init=False, default_factory=tuple)

    def __post_init__(self) -> None:
        if not _positive_int(self.boot_epoch):
            raise ValueError("boot_epoch must be a positive integer")
        if not self.expected_writer_id:
            raise ValueError("expected_writer_id is required")

    # -- internal -----------------------------------------------------------
    def _latched(self) -> SafetyVerdictV1:
        return SafetyVerdictV1(AuthorityDisposition.LATCHED_STOP, self.latch_reasons)

    def _latch(self, reasons: tuple[str, ...]) -> SafetyVerdictV1:
        if self.phase is not GatewayPhase.LATCHED:
            self.phase = GatewayPhase.LATCHED
            self.lease = None
            self.latch_reasons = reasons or ("latched_stop",)
        return self._latched()

    # -- lifecycle ----------------------------------------------------------
    def arm(self, lease: LeaseV1, *, now_monotonic_s: float) -> SafetyVerdictV1:
        """Acquire write authority for this boot epoch.

        Refusing to arm is not a protocol violation (nothing was commanded), so
        an epoch or expiry refusal leaves the gateway disarmed rather than
        latched.  A *foreign writer* attempting to arm is a violation and does
        latch.
        """

        if self.phase is GatewayPhase.LATCHED:
            return self._latched()
        if not _finite(now_monotonic_s):
            return self._latch(("gateway_clock_malformed",))
        if lease.writer_id != self.expected_writer_id:
            return self._latch(("writer_mismatch",))
        if lease.epoch != self.boot_epoch:
            return SafetyVerdictV1(AuthorityDisposition.STOP, ("lease_epoch_mismatch",))
        if not _finite(lease.valid_until_monotonic_s):
            return self._latch(("lease_time_malformed",))
        if now_monotonic_s >= lease.valid_until_monotonic_s:
            return SafetyVerdictV1(AuthorityDisposition.STOP, ("lease_expired",))
        self.phase = GatewayPhase.ARMED
        self.lease = lease
        return SafetyVerdictV1(AuthorityDisposition.PASS)

    def release(self) -> None:
        """Give up authority; the writer must re-arm before commanding again."""

        if self.phase is GatewayPhase.ARMED:
            self.phase = GatewayPhase.DISARMED
            self.lease = None

    def observe(
        self, verdict: SafetyVerdictV1, *, now_monotonic_s: float
    ) -> SafetyVerdictV1:
        """Fold one tick's composed verdict into persistent authority state.

        This is where ``LATCHED_STOP`` stops being a label: once observed, every
        later tick returns it regardless of how clean the new inputs are, until
        :meth:`clear_latch` succeeds.
        """

        if not _finite(now_monotonic_s):
            return self._latch(("gateway_clock_malformed",))
        if self.phase is GatewayPhase.LATCHED:
            return self._latched()
        if verdict.disposition is AuthorityDisposition.LATCHED_STOP:
            return self._latch(verdict.reasons)
        if self.phase is not GatewayPhase.ARMED:
            return dominant_verdict(
                verdict, SafetyVerdictV1(AuthorityDisposition.STOP, ("gateway_disarmed",))
            )
        return verdict

    def clear_latch(
        self,
        *,
        operator_ack: bool,
        stationary: StationaryWitnessV1 | None,
        now_monotonic_s: float,
        max_age_s: float,
        speed_epsilon_mps: float,
        yaw_epsilon_rps: float,
        required_settled_samples: int,
    ) -> SafetyVerdictV1:
        """Clear the latch only on an operator event *plus* measured stillness.

        Every threshold is a required argument: this spike derives no safety
        constants of its own, and a product port must supply values with
        commissioning provenance (stop latency, encoder noise floor).

        On success the gateway returns to ``DISARMED`` — clearing a latch never
        re-arms; the writer must ``arm`` again with a current-epoch lease.
        """

        if self.phase is not GatewayPhase.LATCHED:
            return SafetyVerdictV1(AuthorityDisposition.PASS)
        reasons: list[str] = []
        if operator_ack is not True:
            reasons.append("operator_ack_absent")
        thresholds = (max_age_s, speed_epsilon_mps, yaw_epsilon_rps)
        if not all(_finite(value) and value >= 0.0 for value in thresholds):
            reasons.append("clear_thresholds_malformed")
        if not _finite(now_monotonic_s):
            reasons.append("gateway_clock_malformed")
        if not _non_negative_int(required_settled_samples) or required_settled_samples < 1:
            reasons.append("required_settled_samples_malformed")
        if stationary is None:
            reasons.append("stationary_feedback_missing")
        elif not reasons:
            if stationary.origin is not EvidenceOrigin.PHYSICAL:
                reasons.append("stationary_feedback_not_physical")
            age_s = now_monotonic_s - stationary.observed_at_monotonic_s
            if age_s > max_age_s:
                reasons.append("stationary_feedback_stale")
            if age_s < 0.0:
                reasons.append("stationary_feedback_in_future")
            if abs(stationary.measured_speed_mps) > speed_epsilon_mps:
                reasons.append("robot_still_translating")
            if abs(stationary.measured_yaw_rps) > yaw_epsilon_rps:
                reasons.append("robot_still_rotating")
            if stationary.settled_samples < required_settled_samples:
                reasons.append("robot_not_settled")
        if reasons:
            return SafetyVerdictV1(
                AuthorityDisposition.LATCHED_STOP, tuple(reasons) + self.latch_reasons
            )
        self.phase = GatewayPhase.DISARMED
        self.lease = None
        self.latch_reasons = ()
        return SafetyVerdictV1(AuthorityDisposition.PASS)


def authorize_motion(
    gateway: RobotGatewayV1,
    candidate: MotionCandidateV2,
    *,
    task: TaskTransactionV2,
    capability: HardwareCapabilityManifestV1,
    lease: LeaseV1,
    required: Iterable[RequiredEvidenceV1],
    current_evidence: Mapping[str, EvidenceEnvelopeV2],
    owner_state: OwnerTrackState,
    candidate_is_translation: bool,
    now_monotonic_s: float,
    permitted_speed_mps: float,
    surrounding_max_age_s: float,
    surrounding_evidence: EvidenceEnvelopeV2 | None = None,
) -> SafetyVerdictV1:
    """The enforced composition (N-2) — the only sanctioned way to authorize.

    Revision 1 relied on the caller to run :func:`join_evidence` *and*
    :func:`candidate_verdict` *and* :func:`owner_motion_verdict` and to compose
    them monotonically.  Nothing forced that, so a caller that skipped the
    evidence half got physical-translation authority from sequence numbers
    alone.  Threading origin, frame and freshness end to end is this function's
    entire job; the gateway then folds the result into persistent state.
    """

    verdicts = (
        join_evidence(required, current_evidence, now_monotonic_s=now_monotonic_s),
        candidate_verdict(
            candidate,
            task=task,
            capability=capability,
            lease=lease,
            expected_writer_id=gateway.expected_writer_id,
            current_epoch=gateway.boot_epoch,
            now_monotonic_s=now_monotonic_s,
            current_evidence=current_evidence,
        ),
        owner_motion_verdict(owner_state, candidate_is_translation=candidate_is_translation),
        in_place_search_verdict(
            candidate,
            surrounding_evidence=surrounding_evidence,
            now_monotonic_s=now_monotonic_s,
            max_age_s=surrounding_max_age_s,
        ),
        speed_envelope_verdict(candidate, permitted_speed_mps=permitted_speed_mps),
    )
    return gateway.observe(dominant_verdict(*verdicts), now_monotonic_s=now_monotonic_s)


@dataclass(frozen=True, slots=True)
class BehaviorProposalV2:
    name: str
    resources: frozenset[Resource]
    emergency: bool
    valid_until_monotonic_s: float

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("behavior name is required")
        if not self.resources:
            raise ValueError("a behavior must claim at least one resource")
        if any(not isinstance(item, Resource) for item in self.resources):
            raise TypeError("behavior resources must be typed Resource")
        if not isinstance(self.emergency, bool):
            raise TypeError("emergency must be a bool")
        if not _finite(self.valid_until_monotonic_s):
            raise ValueError("behavior deadline must be finite")


def behavior_verdict(
    proposal: BehaviorProposalV2,
    *,
    navigation_owns_base: bool,
    now_monotonic_s: float,
) -> SafetyVerdictV1:
    # Emergency is evaluated first so that an e-stop bypasses every other gate,
    # including the expiry it would otherwise trip.
    if proposal.emergency:
        return SafetyVerdictV1(AuthorityDisposition.LATCHED_STOP, ("emergency",))
    if not _finite(now_monotonic_s):
        return SafetyVerdictV1(AuthorityDisposition.LATCHED_STOP, ("decision_clock_malformed",))
    if not _finite(proposal.valid_until_monotonic_s):
        return SafetyVerdictV1(AuthorityDisposition.LATCHED_STOP, ("behavior_deadline_malformed",))
    if now_monotonic_s >= proposal.valid_until_monotonic_s:
        return SafetyVerdictV1(AuthorityDisposition.HOLD, ("behavior_expired",))
    if navigation_owns_base and Resource.BASE in proposal.resources:
        return SafetyVerdictV1(AuthorityDisposition.HOLD, ("base_owned_by_navigation",))
    return SafetyVerdictV1(AuthorityDisposition.PASS)


@dataclass(frozen=True, slots=True)
class TerminalWitnessV2:
    """Evidence that a task actually finished, in the frame that has to be true.

    RC-2: ``arrival_margin_m`` and ``pose_uncertainty_m`` are **required**.
    Backlog B5 measured what happens without them — an arrival predicate that
    consumes 100 % of its band leaves no reserve for localization error, so the
    robot claims arrival inside its own map while standing outside the band in
    the world.  A contract that lets a witness omit the reserve re-creates that
    defect by construction, so the fields have no defaults.
    """

    task_id: str
    task_revision: int
    predicate_true: bool
    observed_at_monotonic_s: float
    evidence_sequences: tuple[tuple[str, int], ...]
    settled_samples: int
    arrival_margin_m: float
    pose_uncertainty_m: float

    def __post_init__(self) -> None:
        if not self.task_id:
            raise ValueError("terminal task id is required")
        if not _positive_int(self.task_revision):
            raise ValueError("terminal task revision must be positive")
        if not isinstance(self.predicate_true, bool):
            raise TypeError("predicate_true must be a bool")
        if not _finite(self.observed_at_monotonic_s):
            raise ValueError("terminal observation time must be finite")
        if not _non_negative_int(self.settled_samples):
            raise ValueError("terminal settled_samples must be a non-negative integer")
        if not _finite(self.arrival_margin_m):
            raise ValueError("arrival margin must be finite")
        if not _finite(self.pose_uncertainty_m) or self.pose_uncertainty_m < 0.0:
            raise ValueError("pose uncertainty must be finite and non-negative")
        streams = [stream for stream, _ in self.evidence_sequences]
        if len(streams) != len(set(streams)):
            raise ValueError("terminal evidence streams must be unique")
        if any(not stream or not _positive_int(seq) for stream, seq in self.evidence_sequences):
            raise ValueError("terminal evidence references must be valid")


def terminal_verdict(
    witness: TerminalWitnessV2,
    *,
    task: TaskTransactionV2,
    current_evidence: Mapping[str, EvidenceEnvelopeV2],
    now_monotonic_s: float,
    max_age_s: float,
    required_settled_samples: int,
    pose_reserve_multiplier: float = 1.0,
) -> SafetyVerdictV1:
    """Accept "done" only from fresh, settled, frame-honest evidence.

    ``pose_reserve_multiplier`` scales the localization reserve the arrival
    margin must cover.  It defaults to 1.0 — the weakest defensible rule, "the
    margin must at least cover the claimed uncertainty" — precisely because this
    spike derives no safety constants.  A product port must derive it (B5
    recorded the shipped covariance as 3.6x optimistic, which is an argument for
    a multiplier above 1.0, not a licence to hard-code 3.6 here).
    """

    reasons: list[str] = []
    malformed: list[str] = []
    if not _finite(now_monotonic_s):
        malformed.append("decision_clock_malformed")
    if not _finite(max_age_s) or max_age_s <= 0.0:
        malformed.append("terminal_max_age_malformed")
    if not _finite(pose_reserve_multiplier) or pose_reserve_multiplier < 1.0:
        malformed.append("pose_reserve_multiplier_malformed")
    if not _non_negative_int(required_settled_samples) or required_settled_samples < 1:
        malformed.append("required_settled_samples_malformed")
    if not _finite(witness.observed_at_monotonic_s):
        malformed.append("terminal_time_malformed")
    if not _non_negative_int(witness.settled_samples):
        malformed.append("terminal_settled_samples_malformed")
    if not _finite(witness.arrival_margin_m) or not _finite(witness.pose_uncertainty_m):
        malformed.append("terminal_pose_reserve_malformed")
    if malformed:
        return SafetyVerdictV1(AuthorityDisposition.LATCHED_STOP, tuple(malformed))

    if witness.task_id != task.task_id or witness.task_revision != task.revision:
        reasons.append("terminal_task_revision_mismatch")
    if witness.predicate_true is not True:
        reasons.append("terminal_predicate_false")
    if now_monotonic_s - witness.observed_at_monotonic_s > max_age_s:
        reasons.append("terminal_evidence_stale")
    if witness.observed_at_monotonic_s > now_monotonic_s + 0.05:
        reasons.append("terminal_time_in_future")
    if witness.settled_samples < required_settled_samples:
        reasons.append("robot_not_settled")
    # RC-2: the arrival margin must cover the localization reserve.
    if witness.arrival_margin_m < witness.pose_uncertainty_m * pose_reserve_multiplier:
        reasons.append("arrival_margin_below_pose_reserve")
    for stream_id, sequence in witness.evidence_sequences:
        current = current_evidence.get(stream_id)
        if current is None or current.sequence != sequence:
            reasons.append(f"{stream_id}:terminal_evidence_changed")
    if reasons:
        return SafetyVerdictV1(AuthorityDisposition.HOLD, tuple(reasons))
    return SafetyVerdictV1(AuthorityDisposition.PASS)


__all__ = [
    "PHYSICAL_ONLY",
    "SCHEMA_VERSION",
    "AuthorityDisposition",
    "BehaviorProposalV2",
    "EvidenceEnvelopeV2",
    "EvidenceOrigin",
    "GatewayPhase",
    "HardwareCapabilityManifestV1",
    "LeaseV1",
    "MotionCandidateV2",
    "OwnerTrackState",
    "ProposalKind",
    "RequiredEvidenceV1",
    "Resource",
    "RobotGatewayV1",
    "SafetyVerdictV1",
    "StationaryWitnessV1",
    "TaskTransactionV2",
    "TerminalWitnessV2",
    "authorize_motion",
    "behavior_verdict",
    "candidate_verdict",
    "dominant_verdict",
    "in_place_search_verdict",
    "join_evidence",
    "owner_motion_verdict",
    "speed_envelope_verdict",
    "terminal_verdict",
]
