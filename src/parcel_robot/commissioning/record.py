"""``CommissioningRecordV1`` — the evidence a bring-up produces.

Contract source: ``scrum/20260812/task_1/PRODUCTION_COMPANION_PLAN.md``
§"CommissioningRecordV1" — "Signed evidence for axis signs, velocity frame,
sensor extrinsics, modes, QoS/rates, limits, stop request/settle latency and
distance, operator, date, and artifact hashes. Defaults fail closed. Product
configuration may reference but never manufacture it."

Three properties carry the weight here:

1. **Defaults fail closed.** A record built with nothing in it authorizes
   nothing. ``outcome`` defaults to ``FAILED``, every direction defaults to
   ``UNCERTAIN``, ``review`` defaults to absent, and every "confirmed" answer is
   *derived* from raw measurements rather than stored as a trusted flag.
2. **Derived answers are never read back from the file.** ``as_dict`` writes the
   derived booleans for a human reader, and ``from_mapping`` throws them away
   and recomputes from the raw numbers. Hand-editing ``"authorized": true`` into
   a record file changes nothing.
3. **Product configuration may reference but never manufacture it.**
   :func:`commissioned_control_config` is the only way a record turns into the
   flags ``control/factory.py`` requires, it refuses an unreviewed record, and
   nothing in ``control/`` calls it — an operator does, deliberately.

Why an axis sign needs an operator, not just feedback
-----------------------------------------------------
The vendor's ``Move`` command and its ``SportModeState`` feedback live in the
*same* vendor frame, and ``control/unitree_sport.py`` applies the configured
``lateral_sign``/``yaw_sign`` to both. Commanding ``+vy`` through sign ``s``
produces reported ``vy`` of ``s * (k * s * v) = k * v``: the ``s`` cancels. So
vendor feedback alone can never tell you whether the vendor's +y is your +y —
it can only tell you that the command/feedback loop is self-consistent. The
sign is established by a human watching which way the robot actually went, and
this record refuses to claim one without that observation
(:class:`ObservedDirection`, default ``UNCERTAIN``).
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from .limits import (
    MIN_LINEAR_MPS,
    SETTLED_LINEAR_MPS,
    CommissioningAxis,
    CommissioningLimits,
)

COMMISSIONING_RECORD_SCHEMA = "parcel.commissioning.record.v1"

#: Smallest yaw at which an ``odom`` vs ``base_link`` velocity-frame claim is
#: discriminating at all. Derived: a frame error puts ``v * sin(theta)`` into
#: the cross axis, and that must clear the sign-evidence floor, so
#: ``|sin(theta)| >= floor / v``. At the worst case (slowest commanded speed)
#: that ratio is ``SETTLED_LINEAR_MPS / MIN_LINEAR_MPS = 0.5``, hence
#: ``asin(0.5) = pi/6``. Below this yaw the two frames agree to within the noise
#: floor and the measurement proves nothing — so the record says so.
FRAME_DISCRIMINATION_YAW_RAD = math.asin(SETTLED_LINEAR_MPS / MIN_LINEAR_MPS)

_ISO_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$")

VELOCITY_FRAMES = ("odom", "base_link")


class CommissioningReviewError(RuntimeError):
    """Raised when an unreviewed or insufficient record is asked to authorize."""


class RecordOutcome(str, Enum):
    """Outcome of a commissioning session. ``FAILED`` is the default."""

    FAILED = "failed"
    ABORTED = "aborted"
    PASSED = "passed"


class ObservedDirection(str, Enum):
    """What the operator saw the robot do. ``UNCERTAIN`` is the default."""

    UNCERTAIN = "uncertain"
    NONE = "none"
    FORWARD = "forward"
    BACKWARD = "backward"
    LEFT = "left"
    RIGHT = "right"
    COUNTERCLOCKWISE = "counterclockwise"
    CLOCKWISE = "clockwise"


#: REP-103 body frame: +x forward, +y left, +yaw counter-clockwise.
_POSITIVE_DIRECTION = {
    CommissioningAxis.VX: ObservedDirection.FORWARD,
    CommissioningAxis.VY: ObservedDirection.LEFT,
    CommissioningAxis.VYAW: ObservedDirection.COUNTERCLOCKWISE,
}
_NEGATIVE_DIRECTION = {
    CommissioningAxis.VX: ObservedDirection.BACKWARD,
    CommissioningAxis.VY: ObservedDirection.RIGHT,
    CommissioningAxis.VYAW: ObservedDirection.CLOCKWISE,
}


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path | str) -> str:
    return sha256_bytes(Path(path).read_bytes())


def canonical_json(payload: object) -> str:
    """Deterministic serialization used for every digest in this module."""

    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _float(payload: Mapping[str, object], key: str, default: float = 0.0) -> float:
    value = payload.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"commissioning record field {key!r} must be a number")
    return float(value)


def _int(payload: Mapping[str, object], key: str, default: int = 0) -> int:
    value = payload.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"commissioning record field {key!r} must be an integer")
    return int(value)


def _ints(payload: Mapping[str, object], key: str) -> tuple[int, ...]:
    values = payload.get(key, ())
    if isinstance(values, (str, bytes)) or not isinstance(values, (list, tuple)):
        raise TypeError(f"commissioning record field {key!r} must be a list of integers")
    return tuple(int(value) for value in values)


def _text(payload: Mapping[str, object], key: str, default: str = "") -> str:
    return str(payload.get(key, default))


@dataclass(frozen=True)
class AxisSignEvidence:
    """One axis step: what was commanded, what the feedback said, what was seen."""

    axis: CommissioningAxis
    commanded_speed: float
    samples: int
    mean_measured_speed: float
    mean_cross_axis_speed: float
    mean_yaw_rad: float
    evidence_floor: float
    observed_direction: ObservedDirection = ObservedDirection.UNCERTAIN
    declared_velocity_frame: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.axis, CommissioningAxis):
            raise TypeError("axis evidence axis must be a CommissioningAxis")
        if not isinstance(self.observed_direction, ObservedDirection):
            raise TypeError("axis evidence observed_direction must be an ObservedDirection")
        values = (
            self.commanded_speed,
            self.mean_measured_speed,
            self.mean_cross_axis_speed,
            self.mean_yaw_rad,
            self.evidence_floor,
        )
        if any(not math.isfinite(value) for value in values):
            raise ValueError("axis evidence must contain only finite values")
        if isinstance(self.samples, bool) or not isinstance(self.samples, int) or self.samples < 0:
            raise ValueError("axis evidence sample count must be a non-negative integer")
        if self.evidence_floor <= 0.0:
            raise ValueError("axis evidence floor must be positive")
        if self.declared_velocity_frame and self.declared_velocity_frame not in VELOCITY_FRAMES:
            raise ValueError(f"declared velocity frame must be one of {VELOCITY_FRAMES}")

    @property
    def moved(self) -> bool:
        """Feedback shows motion above the floor this path calls stationary."""

        return abs(self.mean_measured_speed) >= self.evidence_floor

    @property
    def feedback_agrees(self) -> bool:
        """Vendor feedback moved the same way the command asked.

        Self-consistency of the command/feedback loop only. It does NOT
        establish the axis sign (see the module docstring).
        """

        if not self.moved or abs(self.commanded_speed) <= 0.0:
            return False
        return math.copysign(1.0, self.mean_measured_speed) == math.copysign(
            1.0, self.commanded_speed
        )

    @property
    def sign(self) -> int | None:
        """Axis sign to configure, or ``None`` when there is no evidence.

        Requires an operator observation. Commissioning always runs with
        identity signs, so the correction is exactly "did it go the way the
        positive convention says it should".
        """

        if self.samples <= 0 or not self.moved or not self.feedback_agrees:
            return None
        if self.observed_direction in {ObservedDirection.UNCERTAIN, ObservedDirection.NONE}:
            return None
        commanded_positive = self.commanded_speed > 0.0
        expected = (_POSITIVE_DIRECTION if commanded_positive else _NEGATIVE_DIRECTION)[self.axis]
        opposite = (_NEGATIVE_DIRECTION if commanded_positive else _POSITIVE_DIRECTION)[self.axis]
        if self.observed_direction is expected:
            return 1
        if self.observed_direction is opposite:
            return -1
        return None

    @property
    def frame_discriminating(self) -> bool:
        """True when this step could tell ``odom`` from ``base_link`` at all."""

        return self.axis is CommissioningAxis.VX and (
            abs(self.mean_yaw_rad) >= FRAME_DISCRIMINATION_YAW_RAD
        )

    @property
    def frame_confirmed(self) -> bool:
        """A forward step at a discriminating yaw that stayed on its own axis."""

        return (
            self.frame_discriminating
            and self.moved
            and self.feedback_agrees
            and abs(self.mean_cross_axis_speed) < self.evidence_floor
            and self.declared_velocity_frame in VELOCITY_FRAMES
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "axis": self.axis.value,
            "commanded_speed": self.commanded_speed,
            "samples": self.samples,
            "mean_measured_speed": self.mean_measured_speed,
            "mean_cross_axis_speed": self.mean_cross_axis_speed,
            "mean_yaw_rad": self.mean_yaw_rad,
            "evidence_floor": self.evidence_floor,
            "observed_direction": self.observed_direction.value,
            "declared_velocity_frame": self.declared_velocity_frame,
            # Derived, written for the reader and recomputed on load.
            "derived": {
                "moved": self.moved,
                "feedback_agrees": self.feedback_agrees,
                "sign": self.sign,
                "frame_discriminating": self.frame_discriminating,
                "frame_confirmed": self.frame_confirmed,
            },
        }

    @classmethod
    def from_mapping(cls, payload: Mapping[str, object]) -> AxisSignEvidence:
        """Rebuild from raw fields only. Any stored ``derived`` block is ignored."""

        return cls(
            axis=CommissioningAxis(_text(payload, "axis")),
            commanded_speed=_float(payload, "commanded_speed"),
            samples=_int(payload, "samples"),
            mean_measured_speed=_float(payload, "mean_measured_speed"),
            mean_cross_axis_speed=_float(payload, "mean_cross_axis_speed"),
            mean_yaw_rad=_float(payload, "mean_yaw_rad"),
            evidence_floor=_float(payload, "evidence_floor"),
            observed_direction=ObservedDirection(
                _text(payload, "observed_direction", ObservedDirection.UNCERTAIN.value)
            ),
            declared_velocity_frame=_text(payload, "declared_velocity_frame"),
        )


@dataclass(frozen=True)
class StopEvidence:
    """Stop request latency, feedback-confirmed settle latency, and distance."""

    request_latency_s: float
    settle_latency_s: float
    distance_m: float
    distance_method: str
    settled_linear_mps: float
    settled_yaw_rad_s: float
    confirmed: bool = False
    timeout_s: float = 0.0

    DISTANCE_METHODS = ("odom_delta", "speed_integral")

    def __post_init__(self) -> None:
        values = (
            self.request_latency_s,
            self.settle_latency_s,
            self.distance_m,
            self.settled_linear_mps,
            self.settled_yaw_rad_s,
            self.timeout_s,
        )
        if any(not math.isfinite(value) or value < 0.0 for value in values):
            raise ValueError("stop evidence must contain finite, non-negative values")
        if self.distance_method not in self.DISTANCE_METHODS:
            raise ValueError(f"stop distance method must be one of {self.DISTANCE_METHODS}")

    def as_dict(self) -> dict[str, object]:
        return {
            "request_latency_s": self.request_latency_s,
            "settle_latency_s": self.settle_latency_s,
            "distance_m": self.distance_m,
            "distance_method": self.distance_method,
            "settled_linear_mps": self.settled_linear_mps,
            "settled_yaw_rad_s": self.settled_yaw_rad_s,
            "confirmed": self.confirmed,
            "timeout_s": self.timeout_s,
        }

    @classmethod
    def from_mapping(cls, payload: Mapping[str, object]) -> StopEvidence:
        return cls(
            request_latency_s=_float(payload, "request_latency_s"),
            settle_latency_s=_float(payload, "settle_latency_s"),
            distance_m=_float(payload, "distance_m"),
            distance_method=_text(payload, "distance_method"),
            settled_linear_mps=_float(payload, "settled_linear_mps"),
            settled_yaw_rad_s=_float(payload, "settled_yaw_rad_s"),
            confirmed=bool(payload.get("confirmed", False)),
            timeout_s=_float(payload, "timeout_s"),
        )


@dataclass(frozen=True)
class ObservationEvidence:
    """Read-only phase: what the state stream looked like with nothing commanded."""

    samples: int
    duration_s: float
    modes_seen: tuple[int, ...] = ()
    error_codes_seen: tuple[int, ...] = ()
    max_interval_s: float = 0.0
    mean_interval_s: float = 0.0
    max_linear_speed_mps: float = 0.0
    max_yaw_speed_rad_s: float = 0.0
    declared_velocity_frame: str = ""
    state_source: str = ""

    def __post_init__(self) -> None:
        values = (
            self.duration_s,
            self.max_interval_s,
            self.mean_interval_s,
            self.max_linear_speed_mps,
            self.max_yaw_speed_rad_s,
        )
        if any(not math.isfinite(value) or value < 0.0 for value in values):
            raise ValueError("observation evidence must contain finite, non-negative values")
        if isinstance(self.samples, bool) or not isinstance(self.samples, int) or self.samples < 0:
            raise ValueError("observation sample count must be a non-negative integer")
        integer_fields = (
            ("modes_seen", self.modes_seen),
            ("error_codes_seen", self.error_codes_seen),
        )
        for name, codes in integer_fields:
            if any(isinstance(code, bool) or not isinstance(code, int) for code in codes):
                raise TypeError(f"observation {name} must contain integers")

    @property
    def sample_hz(self) -> float:
        if self.duration_s <= 0.0 or self.samples <= 0:
            return 0.0
        return self.samples / self.duration_s

    def as_dict(self) -> dict[str, object]:
        return {
            "samples": self.samples,
            "duration_s": self.duration_s,
            "modes_seen": list(self.modes_seen),
            "error_codes_seen": list(self.error_codes_seen),
            "max_interval_s": self.max_interval_s,
            "mean_interval_s": self.mean_interval_s,
            "max_linear_speed_mps": self.max_linear_speed_mps,
            "max_yaw_speed_rad_s": self.max_yaw_speed_rad_s,
            "declared_velocity_frame": self.declared_velocity_frame,
            "state_source": self.state_source,
            "derived": {"sample_hz": self.sample_hz},
        }

    @classmethod
    def from_mapping(cls, payload: Mapping[str, object]) -> ObservationEvidence:
        return cls(
            samples=_int(payload, "samples"),
            duration_s=_float(payload, "duration_s"),
            modes_seen=_ints(payload, "modes_seen"),
            error_codes_seen=_ints(payload, "error_codes_seen"),
            max_interval_s=_float(payload, "max_interval_s"),
            mean_interval_s=_float(payload, "mean_interval_s"),
            max_linear_speed_mps=_float(payload, "max_linear_speed_mps"),
            max_yaw_speed_rad_s=_float(payload, "max_yaw_speed_rad_s"),
            declared_velocity_frame=_text(payload, "declared_velocity_frame"),
            state_source=_text(payload, "state_source"),
        )


@dataclass(frozen=True)
class ReviewAttestation:
    """A named human accepting a specific record content digest.

    "Signed" here means *bound to a content digest by a named reviewer who is
    not the operator*. It is deliberately not a cryptographic signature and this
    module never claims one; see ``DOES_NOT_PROVE``.
    """

    reviewer: str
    reviewed_at: str
    record_digest: str
    accepted: bool = False
    notes: str = ""

    def __post_init__(self) -> None:
        if not self.reviewer.strip() or len(self.reviewer) > 80:
            raise ValueError("reviewer must be a short non-empty name")
        if not _ISO_UTC.match(self.reviewed_at):
            raise ValueError("reviewed_at must be an ISO-8601 UTC timestamp ending in Z")
        if not re.fullmatch(r"[0-9a-f]{64}", self.record_digest):
            raise ValueError("review record_digest must be a sha256 hex digest")

    def as_dict(self) -> dict[str, object]:
        return {
            "reviewer": self.reviewer,
            "reviewed_at": self.reviewed_at,
            "record_digest": self.record_digest,
            "accepted": self.accepted,
            "notes": self.notes,
        }

    @classmethod
    def from_mapping(cls, payload: Mapping[str, object]) -> ReviewAttestation:
        return cls(
            reviewer=_text(payload, "reviewer"),
            reviewed_at=_text(payload, "reviewed_at"),
            record_digest=_text(payload, "record_digest"),
            accepted=bool(payload.get("accepted", False)),
            notes=_text(payload, "notes"),
        )


@dataclass(frozen=True)
class CommissioningRecordV1:
    """Evidence from one commissioning session. Every default refuses."""

    record_id: str
    operator: str
    robot_serial: str
    performed_at: str
    platform: str = "unitree_sport"
    schema: str = COMMISSIONING_RECORD_SCHEMA
    outcome: RecordOutcome = RecordOutcome.FAILED
    failure_reason: str = ""
    declared_velocity_frame: str = ""
    observed_modes: tuple[int, ...] = ()
    axis_signs: tuple[AxisSignEvidence, ...] = ()
    observation: ObservationEvidence | None = None
    stop: StopEvidence | None = None
    limits: CommissioningLimits = field(default_factory=CommissioningLimits)
    artifact_hashes: tuple[tuple[str, str], ...] = ()
    journal_digest: str = ""
    software_revision: str = ""
    review: ReviewAttestation | None = None

    def __post_init__(self) -> None:
        if self.schema != COMMISSIONING_RECORD_SCHEMA:
            raise ValueError(f"commissioning record schema must be {COMMISSIONING_RECORD_SCHEMA}")
        for name in ("record_id", "operator", "robot_serial", "platform"):
            value = getattr(self, name)
            if not value.strip() or len(value) > 120:
                raise ValueError(f"commissioning record {name} must be a short non-empty string")
        if not _ISO_UTC.match(self.performed_at):
            raise ValueError("performed_at must be an ISO-8601 UTC timestamp ending in Z")
        if not isinstance(self.outcome, RecordOutcome):
            raise TypeError("commissioning record outcome must be a RecordOutcome")
        if self.declared_velocity_frame and self.declared_velocity_frame not in VELOCITY_FRAMES:
            raise ValueError(f"declared velocity frame must be one of {VELOCITY_FRAMES}")
        modes = tuple(self.observed_modes)
        if any(isinstance(mode, bool) or not isinstance(mode, int) for mode in modes):
            raise TypeError("observed_modes must contain integers")
        if any(mode < 0 or mode > 255 for mode in modes):
            raise ValueError("observed_modes must contain byte-sized integers")
        object.__setattr__(self, "observed_modes", modes)
        object.__setattr__(self, "axis_signs", tuple(self.axis_signs))
        seen: set[CommissioningAxis] = set()
        for evidence in self.axis_signs:
            if not isinstance(evidence, AxisSignEvidence):
                raise TypeError("axis_signs must contain AxisSignEvidence entries")
            if evidence.axis in seen:
                raise ValueError(f"axis {evidence.axis.value} appears twice in one record")
            seen.add(evidence.axis)
        hashes = tuple((str(name), str(digest)) for name, digest in self.artifact_hashes)
        for name, digest in hashes:
            if not name.strip():
                raise ValueError("artifact hash name cannot be empty")
            if not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise ValueError(f"artifact hash for {name!r} must be a sha256 hex digest")
        object.__setattr__(self, "artifact_hashes", hashes)
        if self.journal_digest and not re.fullmatch(r"[0-9a-f]{64}", self.journal_digest):
            raise ValueError("journal_digest must be a sha256 hex digest")

    # ---------------------------------------------------------------- evidence

    def evidence_for(self, axis: CommissioningAxis) -> AxisSignEvidence | None:
        for evidence in self.axis_signs:
            if evidence.axis is axis:
                return evidence
        return None

    def axis_sign(self, axis: CommissioningAxis) -> int | None:
        evidence = self.evidence_for(axis)
        return None if evidence is None else evidence.sign

    @property
    def velocity_frame_confirmed(self) -> bool:
        evidence = self.evidence_for(CommissioningAxis.VX)
        return bool(
            evidence is not None
            and evidence.frame_confirmed
            and evidence.declared_velocity_frame == self.declared_velocity_frame
            and self.declared_velocity_frame in VELOCITY_FRAMES
        )

    @property
    def axes_confirmed(self) -> bool:
        """Every axis has a definite operator-observed sign."""

        return all(self.axis_sign(axis) is not None for axis in CommissioningAxis)

    @property
    def stop_confirmed(self) -> bool:
        return self.stop is not None and self.stop.confirmed

    def missing_evidence(self) -> tuple[str, ...]:
        """Everything standing between this record and authorization."""

        missing: list[str] = []
        if self.outcome is not RecordOutcome.PASSED:
            missing.append(f"outcome={self.outcome.value}")
        for axis in CommissioningAxis:
            if self.axis_sign(axis) is None:
                missing.append(f"axis_sign:{axis.value}")
        if not self.velocity_frame_confirmed:
            missing.append("velocity_frame")
        if not self.observed_modes:
            missing.append("observed_modes")
        if self.observation is None or self.observation.samples <= 0:
            missing.append("observation")
        if not self.stop_confirmed:
            missing.append("stop_confirmation")
        if not self.journal_digest:
            missing.append("journal_digest")
        if not self.software_revision.strip():
            missing.append("software_revision")
        if not self.is_reviewed():
            missing.append("review")
        return tuple(missing)

    # ------------------------------------------------------------------ digest

    def content_payload(self) -> dict[str, object]:
        """Everything a review attests to. Excludes the review itself."""

        return {
            "schema": self.schema,
            "record_id": self.record_id,
            "operator": self.operator,
            "robot_serial": self.robot_serial,
            "performed_at": self.performed_at,
            "platform": self.platform,
            "outcome": self.outcome.value,
            "failure_reason": self.failure_reason,
            "declared_velocity_frame": self.declared_velocity_frame,
            "observed_modes": list(self.observed_modes),
            "axis_signs": [evidence.as_dict() for evidence in self.axis_signs],
            "observation": None if self.observation is None else self.observation.as_dict(),
            "stop": None if self.stop is None else self.stop.as_dict(),
            "limits": self.limits.as_dict(),
            "artifact_hashes": [list(pair) for pair in self.artifact_hashes],
            "journal_digest": self.journal_digest,
            "software_revision": self.software_revision,
        }

    def content_digest(self) -> str:
        return sha256_bytes(canonical_json(self.content_payload()).encode("utf-8"))

    # ------------------------------------------------------------------ review

    def is_reviewed(self) -> bool:
        review = self.review
        return bool(
            review is not None
            and review.accepted
            and review.record_digest == self.content_digest()
            and review.reviewer.strip().casefold() != self.operator.strip().casefold()
        )

    def reviewed_by(
        self,
        *,
        reviewer: str,
        reviewed_at: str,
        accepted: bool = False,
        notes: str = "",
    ) -> CommissioningRecordV1:
        """Attach an attestation bound to this record's current digest.

        The reviewer must not be the operator: a bring-up nobody but its own
        operator looked at is not reviewed evidence.
        """

        if reviewer.strip().casefold() == self.operator.strip().casefold():
            raise CommissioningReviewError(
                "a commissioning record must be reviewed by someone other than its operator"
            )
        attestation = ReviewAttestation(
            reviewer=reviewer,
            reviewed_at=reviewed_at,
            record_digest=self.content_digest(),
            accepted=accepted,
            notes=notes,
        )
        return self.replace(review=attestation)

    def authorizes_configuration(self) -> bool:
        return not self.missing_evidence()

    def replace(self, **changes: object) -> CommissioningRecordV1:
        payload = {
            "record_id": self.record_id,
            "operator": self.operator,
            "robot_serial": self.robot_serial,
            "performed_at": self.performed_at,
            "platform": self.platform,
            "schema": self.schema,
            "outcome": self.outcome,
            "failure_reason": self.failure_reason,
            "declared_velocity_frame": self.declared_velocity_frame,
            "observed_modes": self.observed_modes,
            "axis_signs": self.axis_signs,
            "observation": self.observation,
            "stop": self.stop,
            "limits": self.limits,
            "artifact_hashes": self.artifact_hashes,
            "journal_digest": self.journal_digest,
            "software_revision": self.software_revision,
            "review": self.review,
        }
        payload.update(changes)
        return CommissioningRecordV1(**payload)

    # ------------------------------------------------------------ persistence

    def as_dict(self) -> dict[str, object]:
        payload = self.content_payload()
        payload["review"] = None if self.review is None else self.review.as_dict()
        payload["derived"] = {
            "content_digest": self.content_digest(),
            "velocity_frame_confirmed": self.velocity_frame_confirmed,
            "axes_confirmed": self.axes_confirmed,
            "stop_confirmed": self.stop_confirmed,
            "reviewed": self.is_reviewed(),
            "authorizes_configuration": self.authorizes_configuration(),
            "missing_evidence": list(self.missing_evidence()),
        }
        return payload

    @classmethod
    def from_mapping(cls, payload: Mapping[str, object]) -> CommissioningRecordV1:
        """Rebuild from raw fields. Any stored ``derived`` block is discarded."""

        observation = payload.get("observation")
        stop = payload.get("stop")
        review = payload.get("review")
        limits = payload.get("limits") or {}
        return cls(
            record_id=_text(payload, "record_id"),
            operator=_text(payload, "operator"),
            robot_serial=_text(payload, "robot_serial"),
            performed_at=_text(payload, "performed_at"),
            platform=_text(payload, "platform", "unitree_sport"),
            schema=_text(payload, "schema", COMMISSIONING_RECORD_SCHEMA),
            outcome=RecordOutcome(_text(payload, "outcome", RecordOutcome.FAILED.value)),
            failure_reason=_text(payload, "failure_reason"),
            declared_velocity_frame=_text(payload, "declared_velocity_frame"),
            observed_modes=_ints(payload, "observed_modes"),
            axis_signs=tuple(
                AxisSignEvidence.from_mapping(entry)
                for entry in payload.get("axis_signs") or ()
            ),
            observation=(
                None if observation is None else ObservationEvidence.from_mapping(observation)
            ),
            stop=None if stop is None else StopEvidence.from_mapping(stop),
            limits=CommissioningLimits.from_mapping(dict(limits)),
            artifact_hashes=tuple(
                (str(pair[0]), str(pair[1])) for pair in payload.get("artifact_hashes") or ()
            ),
            journal_digest=_text(payload, "journal_digest"),
            software_revision=_text(payload, "software_revision"),
            review=None if review is None else ReviewAttestation.from_mapping(review),
        )

    def save(self, path: Path | str) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(self.as_dict(), indent=2, sort_keys=True) + "\n")
        return target

    @classmethod
    def load(cls, path: Path | str) -> CommissioningRecordV1:
        return cls.from_mapping(json.loads(Path(path).read_text()))


def commissioned_control_config(
    control_config: Mapping[str, object],
    record: CommissioningRecordV1,
) -> dict[str, object]:
    """Turn a *reviewed* record into the flags ``control/factory.py`` demands.

    This is the only supported way to set ``enable_lease`` /
    ``axes_commissioned`` / ``state_frame_commissioned`` / ``allowed_modes``.
    It refuses anything short of a complete, reviewed, passing record, and it
    never mutates its input. ``control/factory.py`` does not call this — an
    operator does, once, after a review.
    """

    if not isinstance(record, CommissioningRecordV1):
        raise TypeError("commissioned_control_config requires a CommissioningRecordV1")
    missing = record.missing_evidence()
    if missing:
        raise CommissioningReviewError(
            "commissioning record cannot enable normal configuration; missing: "
            + ", ".join(missing)
        )
    lateral_sign = record.axis_sign(CommissioningAxis.VY)
    yaw_sign = record.axis_sign(CommissioningAxis.VYAW)
    if lateral_sign is None or yaw_sign is None:  # pragma: no cover - missing_evidence covers it
        raise CommissioningReviewError("commissioning record has no axis signs to apply")
    updated = dict(control_config)
    existing = updated.get("unitree_sport") or {}
    sport: dict[str, object] = dict(existing) if isinstance(existing, dict) else {}
    sport.update(
        {
            "enable_lease": True,
            "axes_commissioned": True,
            "state_frame_commissioned": True,
            "allowed_modes": list(record.observed_modes),
            "lateral_sign": lateral_sign,
            "yaw_sign": yaw_sign,
            "state_velocity_frame": record.declared_velocity_frame,
            "commissioning_record_id": record.record_id,
            "commissioning_record_digest": record.content_digest(),
        }
    )
    updated["unitree_sport"] = sport
    return updated


def artifact_hashes_for(paths: Iterable[Path | str]) -> tuple[tuple[str, str], ...]:
    """``(name, sha256)`` pairs for every artifact a record should reference."""

    return tuple(sorted((Path(path).name, sha256_file(path)) for path in paths))


DOES_NOT_PROVE: tuple[str, ...] = (
    (
        "A review attestation is a named human bound to a content digest, not a "
        "cryptographic signature. Nothing here proves the reviewer's identity or "
        "that the file was not rewritten by whoever holds the file."
    ),
    (
        "Axis signs rest on an operator's eyes. This record proves the operator "
        "declared a direction and that vendor feedback was self-consistent with "
        "the command; it does not independently measure which way the robot went."
    ),
    (
        "Stop distance is the vendor's own odometry delta (or a speed integral "
        "when position is unavailable) over the settle window - not ground truth."
    ),
    (
        "Nothing in this module proves the robot is safe to run autonomously. It "
        "is the measurement receipt for four configuration flags, and no more."
    ),
)
