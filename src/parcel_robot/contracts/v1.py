"""Versioned V1 cross-process contracts for Parcel (pure dataclasses, no I/O).

Sol K1 / Phase-0 freeze: EvidenceEnvelopeV1 plus the track, region, voice, and
perception DTO family. Consumers must apply fail-closed freshness helpers from
``parcel_robot.contracts.freshness`` before acting on any sample.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

SCHEMA_VERSION = 1

OWNER_TRACK_STATES = frozenset({"confirmed", "ambiguous", "lost"})
GOAL_RELATIONS = frozenset({"inside", "near", "behind", "orbit", "hold", "visible"})
SOCIAL_CUE_KINDS = frozenset(
    {"explicit_affect", "joke", "greeting", "praise", "frustration", "attention_bid"}
)
SOCIAL_CUE_MODALITIES = frozenset({"transcript", "prosody", "camera"})
RESOURCE_TRACKS = frozenset(
    {"base", "posture", "voice", "attention", "perception_scan", "expression_audio"}
)
INTERRUPTION_POLICIES = frozenset(
    {"overlay", "defer", "suppress", "expire", "checkpoint", "never"}
)
DIALOGUE_PHASES = frozenset({"speaking", "listening", "thinking", "idle"})
SKILL_FEEDBACK_STATUSES = frozenset(
    {
        "in_progress",
        "succeeded",
        "blocked",
        "failed",
        "cancelled",
        "timed_out",
        "deferred",
        "expired",
    }
)
CLAIM_VERACITY = frozenset({"verified", "tentative"})
GEOMETRY_KINDS = frozenset({"polygon", "raster", "point_cloud", "disc"})
PREDICTED_OCCUPANCY_KINDS = frozenset({"polygon", "gaussian"})

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


# ---------------------------------------------------------------------------
# Shared validation helpers (local; keep contracts free of brain imports)
# ---------------------------------------------------------------------------


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} must be an object")
    return value


def _exact_fields(data: Mapping[str, object], fields: set[str], name: str) -> None:
    actual = set(data)
    if actual != fields:
        missing = sorted(fields - actual)
        unknown = sorted(actual - fields)
        detail = []
        if missing:
            detail.append(f"missing={missing}")
        if unknown:
            detail.append(f"unknown={unknown}")
        raise ValueError(f"{name} fields are invalid ({', '.join(detail)})")


def _version(value: object) -> None:
    if isinstance(value, bool) or value != SCHEMA_VERSION:
        raise ValueError(f"schema_version must equal {SCHEMA_VERSION}")


def _string(value: object, name: str, *, maximum: int, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    if (not allow_empty and not value) or len(value) > maximum:
        qualifier = "possibly empty " if allow_empty else "non-empty "
        raise ValueError(f"{name} must be a {qualifier}string of at most {maximum} characters")
    return value


def _short_string(value: object, name: str, maximum: int) -> None:
    _string(value, name, maximum=maximum)


def _identifier(value: object, name: str) -> None:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"{name} must be a bounded identifier")


def _enum(value: object, allowed: frozenset[str], name: str) -> None:
    if value not in allowed:
        raise ValueError(f"{name} is not allowed: {value!r}")


def _number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def _optional_number(value: object, name: str) -> float | None:
    return None if value is None else _number(value, name)


def _integer(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    return value


def _nonneg_int(value: object, name: str) -> int:
    result = _integer(value, name)
    if result < 0:
        raise ValueError(f"{name} must be non-negative")
    return result


def _boolean(value: object, name: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"{name} must be a boolean")
    return value


def _probability(value: object, name: str) -> None:
    _bounded_number(value, name, minimum=0.0, maximum=1.0)


def _bounded_number(
    value: object,
    name: str,
    *,
    minimum: float,
    maximum: float | None,
) -> None:
    number = _number(value, name)
    if number < minimum or (maximum is not None and number > maximum):
        upper = "infinity" if maximum is None else str(maximum)
        raise ValueError(f"{name} must be between {minimum} and {upper}")


def _sequence(value: object, name: str, *, maximum: int) -> list[object] | tuple[object, ...]:
    if not isinstance(value, (list, tuple)):
        raise TypeError(f"{name} must be an array")
    if len(value) > maximum:
        raise ValueError(f"{name} exceeds {maximum} items")
    return value


def _string_tuple(value: object, name: str, *, maximum_items: int) -> tuple[str, ...]:
    if not isinstance(value, tuple):
        # allow list at construction time via coercion sites
        if isinstance(value, list):
            value = tuple(value)
        else:
            raise TypeError(f"{name} must be a tuple")
    if len(value) > maximum_items:
        raise ValueError(f"{name} exceeds {maximum_items} items")
    for item in value:
        _short_string(item, name, 160)
    if len(set(value)) != len(value):
        raise ValueError(f"{name} cannot contain duplicates")
    return value  # type: ignore[return-value]


def _strings(value: object, name: str, maximum: int) -> tuple[str, ...]:
    items = _sequence(value, name, maximum=maximum)
    result = tuple(_string(item, name, maximum=160) for item in items)
    if len(set(result)) != len(result):
        raise ValueError(f"{name} cannot contain duplicates")
    return result


def _finite_tuple(values: Sequence[float], name: str, *, length: int | None = None) -> None:
    if length is not None and len(values) != length:
        raise ValueError(f"{name} must have length {length}")
    for item in values:
        if isinstance(item, bool) or not isinstance(item, (int, float)) or not math.isfinite(item):
            raise ValueError(f"{name} components must be finite numbers")


def _optional_float_tuple(
    value: object, name: str, *, length: int
) -> tuple[float, ...] | None:
    if value is None:
        return None
    if not isinstance(value, (list, tuple)):
        raise TypeError(f"{name} must be an array or null")
    if len(value) != length:
        raise ValueError(f"{name} must have length {length}")
    result = tuple(_number(item, name) for item in value)
    return result


# ---------------------------------------------------------------------------
# Geometry / pose primitives
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PoseXYZYaw:
    """Metric pose in a named frame: x, y, z, yaw_rad."""

    x: float
    y: float
    z: float
    yaw_rad: float

    def __post_init__(self) -> None:
        for name, value in (
            ("x", self.x),
            ("y", self.y),
            ("z", self.z),
            ("yaw_rad", self.yaw_rad),
        ):
            _number(value, name)

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> PoseXYZYaw:
        data = _mapping(value, "pose")
        _exact_fields(data, {"x", "y", "z", "yaw_rad"}, "pose")
        return cls(
            x=_number(data["x"], "x"),
            y=_number(data["y"], "y"),
            z=_number(data["z"], "z"),
            yaw_rad=_number(data["yaw_rad"], "yaw_rad"),
        )

    def as_dict(self) -> dict[str, object]:
        return {"x": self.x, "y": self.y, "z": self.z, "yaw_rad": self.yaw_rad}

    def as_tuple(self) -> tuple[float, float, float, float]:
        return (self.x, self.y, self.z, self.yaw_rad)


@dataclass(frozen=True, slots=True)
class CovarianceND:
    """Row-major covariance; length must be dim² and values finite."""

    values: tuple[float, ...]
    dim: int

    def __post_init__(self) -> None:
        if isinstance(self.dim, bool) or not isinstance(self.dim, int) or self.dim < 1:
            raise ValueError("covariance dim must be a positive integer")
        expected = self.dim * self.dim
        if len(self.values) != expected:
            raise ValueError(f"covariance must contain {expected} values")
        _finite_tuple(self.values, "covariance")

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> CovarianceND:
        data = _mapping(value, "covariance")
        _exact_fields(data, {"values", "dim"}, "covariance")
        raw = _sequence(data["values"], "covariance values", maximum=256)
        return cls(
            values=tuple(_number(item, "covariance value") for item in raw),
            dim=_integer(data["dim"], "covariance dim"),
        )

    def as_dict(self) -> dict[str, object]:
        return {"values": list(self.values), "dim": self.dim}


@dataclass(frozen=True, slots=True)
class GeometryV1:
    """Semantic/goal geometry — never a bare label."""

    kind: str
    polygon: tuple[tuple[float, float], ...] = ()
    disc_center: tuple[float, float] | None = None
    disc_radius_m: float | None = None
    point_cloud: tuple[tuple[float, float, float], ...] = ()
    raster_ref: str = ""

    def __post_init__(self) -> None:
        _enum(self.kind, GEOMETRY_KINDS, "geometry kind")
        if self.kind == "polygon":
            if len(self.polygon) < 3:
                raise ValueError("polygon geometry requires ≥3 vertices")
            for point in self.polygon:
                _finite_tuple(point, "polygon vertex", length=2)
        elif self.kind == "disc":
            if self.disc_center is None or self.disc_radius_m is None:
                raise ValueError("disc geometry requires center and radius")
            _finite_tuple(self.disc_center, "disc center", length=2)
            _bounded_number(self.disc_radius_m, "disc radius", minimum=1e-6, maximum=1_000.0)
        elif self.kind == "point_cloud":
            if not self.point_cloud:
                raise ValueError("point_cloud geometry requires points")
            if len(self.point_cloud) > 4096:
                raise ValueError("point_cloud exceeds 4096 points")
            for point in self.point_cloud:
                _finite_tuple(point, "point_cloud point", length=3)
        else:  # raster
            _short_string(self.raster_ref, "raster_ref", 200)

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> GeometryV1:
        data = _mapping(value, "geometry")
        _exact_fields(
            data,
            {
                "kind",
                "polygon",
                "disc_center",
                "disc_radius_m",
                "point_cloud",
                "raster_ref",
            },
            "geometry",
        )
        poly_raw = _sequence(data["polygon"], "polygon", maximum=256)
        cloud_raw = _sequence(data["point_cloud"], "point_cloud", maximum=4096)
        center = data["disc_center"]
        return cls(
            kind=_string(data["kind"], "geometry kind", maximum=32),
            polygon=tuple(
                (
                    _number(_sequence(pt, "polygon vertex", maximum=2)[0], "x"),
                    _number(_sequence(pt, "polygon vertex", maximum=2)[1], "y"),
                )
                for pt in poly_raw
            ),
            disc_center=_optional_float_tuple(center, "disc_center", length=2),
            disc_radius_m=_optional_number(data["disc_radius_m"], "disc_radius_m"),
            point_cloud=tuple(
                (
                    _number(_sequence(pt, "point", maximum=3)[0], "x"),
                    _number(_sequence(pt, "point", maximum=3)[1], "y"),
                    _number(_sequence(pt, "point", maximum=3)[2], "z"),
                )
                for pt in cloud_raw
            ),
            raster_ref=_string(data["raster_ref"], "raster_ref", maximum=200, allow_empty=True),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "polygon": [list(p) for p in self.polygon],
            "disc_center": list(self.disc_center) if self.disc_center is not None else None,
            "disc_radius_m": self.disc_radius_m,
            "point_cloud": [list(p) for p in self.point_cloud],
            "raster_ref": self.raster_ref,
        }


@dataclass(frozen=True, slots=True)
class PredictedOccupancyV1:
    """Timestamped predicted occupancy for dynamic tracks."""

    kind: str
    timestamp_ns: int
    polygon: tuple[tuple[float, float], ...] = ()
    mean_xy: tuple[float, float] | None = None
    covariance_2x2: tuple[float, float, float, float] | None = None

    def __post_init__(self) -> None:
        _enum(self.kind, PREDICTED_OCCUPANCY_KINDS, "predicted occupancy kind")
        _nonneg_int(self.timestamp_ns, "timestamp_ns")
        if self.kind == "polygon":
            if len(self.polygon) < 3:
                raise ValueError("predicted polygon requires ≥3 vertices")
            for point in self.polygon:
                _finite_tuple(point, "predicted polygon vertex", length=2)
        else:
            if self.mean_xy is None or self.covariance_2x2 is None:
                raise ValueError("gaussian occupancy requires mean_xy and covariance_2x2")
            _finite_tuple(self.mean_xy, "gaussian mean", length=2)
            _finite_tuple(self.covariance_2x2, "gaussian covariance", length=4)

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> PredictedOccupancyV1:
        data = _mapping(value, "predicted occupancy")
        _exact_fields(
            data,
            {"kind", "timestamp_ns", "polygon", "mean_xy", "covariance_2x2"},
            "predicted occupancy",
        )
        poly_raw = _sequence(data["polygon"], "polygon", maximum=64)
        cov = data["covariance_2x2"]
        cov_t: tuple[float, float, float, float] | None = None
        if cov is not None:
            items = _sequence(cov, "covariance_2x2", maximum=4)
            if len(items) != 4:
                raise ValueError("covariance_2x2 must have length 4")
            cov_t = (
                _number(items[0], "c00"),
                _number(items[1], "c01"),
                _number(items[2], "c10"),
                _number(items[3], "c11"),
            )
        return cls(
            kind=_string(data["kind"], "kind", maximum=16),
            timestamp_ns=_integer(data["timestamp_ns"], "timestamp_ns"),
            polygon=tuple(
                (
                    _number(_sequence(pt, "vertex", maximum=2)[0], "x"),
                    _number(_sequence(pt, "vertex", maximum=2)[1], "y"),
                )
                for pt in poly_raw
            ),
            mean_xy=_optional_float_tuple(data["mean_xy"], "mean_xy", length=2),
            covariance_2x2=cov_t,
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "timestamp_ns": self.timestamp_ns,
            "polygon": [list(p) for p in self.polygon],
            "mean_xy": list(self.mean_xy) if self.mean_xy is not None else None,
            "covariance_2x2": list(self.covariance_2x2) if self.covariance_2x2 is not None else None,
        }


# ---------------------------------------------------------------------------
# Evidence envelope
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EvidenceEnvelopeV1:
    """Common envelope for every cross-process observation and proposal."""

    schema_version: int
    evidence_id: str
    source: str
    source_timestamp_ns: int
    received_monotonic_ns: int
    sequence: int
    frame_id: str
    scene_revision: int
    expires_monotonic_ns: int
    calibration_id: str
    provenance: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _version(self.schema_version)
        _identifier(self.evidence_id, "evidence_id")
        _short_string(self.source, "source", 80)
        _nonneg_int(self.source_timestamp_ns, "source_timestamp_ns")
        _nonneg_int(self.received_monotonic_ns, "received_monotonic_ns")
        _nonneg_int(self.sequence, "sequence")
        _short_string(self.frame_id, "frame_id", 64)
        if isinstance(self.scene_revision, bool) or not isinstance(self.scene_revision, int):
            raise TypeError("scene_revision must be an integer")
        if self.scene_revision < 0:
            raise ValueError("scene_revision must be non-negative")
        _nonneg_int(self.expires_monotonic_ns, "expires_monotonic_ns")
        if self.expires_monotonic_ns <= self.received_monotonic_ns:
            raise ValueError("expires_monotonic_ns must be after received_monotonic_ns")
        _short_string(self.calibration_id, "calibration_id", 80)
        object.__setattr__(
            self,
            "provenance",
            _string_tuple(self.provenance, "provenance", maximum_items=16),
        )

    def expired(self, now_monotonic_ns: int) -> bool:
        from parcel_robot.contracts.freshness import is_expired

        return is_expired(
            expires_monotonic_ns=self.expires_monotonic_ns,
            now_monotonic_ns=now_monotonic_ns,
        )

    def require_fresh(self, now_monotonic_ns: int, *, max_age_ns: int | None = None) -> None:
        from parcel_robot.contracts.freshness import require_fresh

        require_fresh(
            received_monotonic_ns=self.received_monotonic_ns,
            expires_monotonic_ns=self.expires_monotonic_ns,
            now_monotonic_ns=now_monotonic_ns,
            max_age_ns=max_age_ns,
        )

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> EvidenceEnvelopeV1:
        data = _mapping(value, "EvidenceEnvelopeV1")
        _exact_fields(
            data,
            {
                "schema_version",
                "evidence_id",
                "source",
                "source_timestamp_ns",
                "received_monotonic_ns",
                "sequence",
                "frame_id",
                "scene_revision",
                "expires_monotonic_ns",
                "calibration_id",
                "provenance",
            },
            "EvidenceEnvelopeV1",
        )
        return cls(
            schema_version=_integer(data["schema_version"], "schema_version"),
            evidence_id=_string(data["evidence_id"], "evidence_id", maximum=128),
            source=_string(data["source"], "source", maximum=80),
            source_timestamp_ns=_integer(data["source_timestamp_ns"], "source_timestamp_ns"),
            received_monotonic_ns=_integer(
                data["received_monotonic_ns"], "received_monotonic_ns"
            ),
            sequence=_integer(data["sequence"], "sequence"),
            frame_id=_string(data["frame_id"], "frame_id", maximum=64),
            scene_revision=_integer(data["scene_revision"], "scene_revision"),
            expires_monotonic_ns=_integer(data["expires_monotonic_ns"], "expires_monotonic_ns"),
            calibration_id=_string(data["calibration_id"], "calibration_id", maximum=80),
            provenance=_strings(data["provenance"], "provenance", 16),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "evidence_id": self.evidence_id,
            "source": self.source,
            "source_timestamp_ns": self.source_timestamp_ns,
            "received_monotonic_ns": self.received_monotonic_ns,
            "sequence": self.sequence,
            "frame_id": self.frame_id,
            "scene_revision": self.scene_revision,
            "expires_monotonic_ns": self.expires_monotonic_ns,
            "calibration_id": self.calibration_id,
            "provenance": list(self.provenance),
        }


# ---------------------------------------------------------------------------
# Navigation / perception tracks and regions
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class OwnerTrackV1:
    envelope: EvidenceEnvelopeV1
    enrolled_owner_id: str
    transient_track_id: str
    state: str
    pose: PoseXYZYaw
    pose_covariance: CovarianceND
    velocity: PoseXYZYaw
    velocity_covariance: CovarianceND
    identity_score: float
    visibility_score: float
    appearance_evidence_refs: tuple[str, ...] = ()
    last_confirmed_at_monotonic_ns: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.envelope, EvidenceEnvelopeV1):
            raise TypeError("envelope must be EvidenceEnvelopeV1")
        _identifier(self.enrolled_owner_id, "enrolled_owner_id")
        _identifier(self.transient_track_id, "transient_track_id")
        _enum(self.state, OWNER_TRACK_STATES, "owner track state")
        if not isinstance(self.pose, PoseXYZYaw) or not isinstance(self.velocity, PoseXYZYaw):
            raise TypeError("pose/velocity must be PoseXYZYaw")
        if not isinstance(self.pose_covariance, CovarianceND):
            raise TypeError("pose_covariance must be CovarianceND")
        if not isinstance(self.velocity_covariance, CovarianceND):
            raise TypeError("velocity_covariance must be CovarianceND")
        if self.pose_covariance.dim != 4 or self.velocity_covariance.dim != 4:
            raise ValueError("owner pose/velocity covariance must be 4×4")
        _probability(self.identity_score, "identity_score")
        _probability(self.visibility_score, "visibility_score")
        object.__setattr__(
            self,
            "appearance_evidence_refs",
            _string_tuple(self.appearance_evidence_refs, "appearance_evidence_refs", maximum_items=16),
        )
        _nonneg_int(self.last_confirmed_at_monotonic_ns, "last_confirmed_at_monotonic_ns")
        if self.state == "confirmed" and self.last_confirmed_at_monotonic_ns <= 0:
            raise ValueError("confirmed owner track requires last_confirmed_at_monotonic_ns")

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> OwnerTrackV1:
        data = _mapping(value, "OwnerTrackV1")
        _exact_fields(
            data,
            {
                "envelope",
                "enrolled_owner_id",
                "transient_track_id",
                "state",
                "pose",
                "pose_covariance",
                "velocity",
                "velocity_covariance",
                "identity_score",
                "visibility_score",
                "appearance_evidence_refs",
                "last_confirmed_at_monotonic_ns",
            },
            "OwnerTrackV1",
        )
        return cls(
            envelope=EvidenceEnvelopeV1.from_mapping(_mapping(data["envelope"], "envelope")),
            enrolled_owner_id=_string(data["enrolled_owner_id"], "enrolled_owner_id", maximum=128),
            transient_track_id=_string(
                data["transient_track_id"], "transient_track_id", maximum=128
            ),
            state=_string(data["state"], "state", maximum=32),
            pose=PoseXYZYaw.from_mapping(_mapping(data["pose"], "pose")),
            pose_covariance=CovarianceND.from_mapping(
                _mapping(data["pose_covariance"], "pose_covariance")
            ),
            velocity=PoseXYZYaw.from_mapping(_mapping(data["velocity"], "velocity")),
            velocity_covariance=CovarianceND.from_mapping(
                _mapping(data["velocity_covariance"], "velocity_covariance")
            ),
            identity_score=_number(data["identity_score"], "identity_score"),
            visibility_score=_number(data["visibility_score"], "visibility_score"),
            appearance_evidence_refs=_strings(
                data["appearance_evidence_refs"], "appearance_evidence_refs", 16
            ),
            last_confirmed_at_monotonic_ns=_integer(
                data["last_confirmed_at_monotonic_ns"], "last_confirmed_at_monotonic_ns"
            ),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "envelope": self.envelope.as_dict(),
            "enrolled_owner_id": self.enrolled_owner_id,
            "transient_track_id": self.transient_track_id,
            "state": self.state,
            "pose": self.pose.as_dict(),
            "pose_covariance": self.pose_covariance.as_dict(),
            "velocity": self.velocity.as_dict(),
            "velocity_covariance": self.velocity_covariance.as_dict(),
            "identity_score": self.identity_score,
            "visibility_score": self.visibility_score,
            "appearance_evidence_refs": list(self.appearance_evidence_refs),
            "last_confirmed_at_monotonic_ns": self.last_confirmed_at_monotonic_ns,
        }


@dataclass(frozen=True, slots=True)
class DynamicTrackV1:
    envelope: EvidenceEnvelopeV1
    track_id: str
    class_id: str
    pose: PoseXYZYaw
    velocity: PoseXYZYaw
    pose_covariance: CovarianceND
    predicted_occupancy: tuple[PredictedOccupancyV1, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.envelope, EvidenceEnvelopeV1):
            raise TypeError("envelope must be EvidenceEnvelopeV1")
        _identifier(self.track_id, "track_id")
        _short_string(self.class_id, "class_id", 64)
        if not isinstance(self.pose, PoseXYZYaw) or not isinstance(self.velocity, PoseXYZYaw):
            raise TypeError("pose/velocity must be PoseXYZYaw")
        if not isinstance(self.pose_covariance, CovarianceND) or self.pose_covariance.dim != 4:
            raise ValueError("dynamic track pose_covariance must be 4×4 CovarianceND")
        if not isinstance(self.predicted_occupancy, tuple):
            raise TypeError("predicted_occupancy must be a tuple")
        if len(self.predicted_occupancy) > 32:
            raise ValueError("predicted_occupancy exceeds 32 items")
        if any(not isinstance(item, PredictedOccupancyV1) for item in self.predicted_occupancy):
            raise TypeError("predicted_occupancy must contain PredictedOccupancyV1")

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> DynamicTrackV1:
        data = _mapping(value, "DynamicTrackV1")
        _exact_fields(
            data,
            {
                "envelope",
                "track_id",
                "class_id",
                "pose",
                "velocity",
                "pose_covariance",
                "predicted_occupancy",
            },
            "DynamicTrackV1",
        )
        occ = _sequence(data["predicted_occupancy"], "predicted_occupancy", maximum=32)
        return cls(
            envelope=EvidenceEnvelopeV1.from_mapping(_mapping(data["envelope"], "envelope")),
            track_id=_string(data["track_id"], "track_id", maximum=128),
            class_id=_string(data["class_id"], "class_id", maximum=64),
            pose=PoseXYZYaw.from_mapping(_mapping(data["pose"], "pose")),
            velocity=PoseXYZYaw.from_mapping(_mapping(data["velocity"], "velocity")),
            pose_covariance=CovarianceND.from_mapping(
                _mapping(data["pose_covariance"], "pose_covariance")
            ),
            predicted_occupancy=tuple(
                PredictedOccupancyV1.from_mapping(_mapping(item, "predicted occupancy"))
                for item in occ
            ),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "envelope": self.envelope.as_dict(),
            "track_id": self.track_id,
            "class_id": self.class_id,
            "pose": self.pose.as_dict(),
            "velocity": self.velocity.as_dict(),
            "pose_covariance": self.pose_covariance.as_dict(),
            "predicted_occupancy": [item.as_dict() for item in self.predicted_occupancy],
        }


@dataclass(frozen=True, slots=True)
class SemanticRegionV1:
    envelope: EvidenceEnvelopeV1
    concept_scores: Mapping[str, float]
    geometry: GeometryV1
    geometry_covariance: CovarianceND
    free_space_support: float
    observation_count: int
    evidence_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.envelope, EvidenceEnvelopeV1):
            raise TypeError("envelope must be EvidenceEnvelopeV1")
        if not isinstance(self.concept_scores, Mapping) or not self.concept_scores:
            raise ValueError("concept_scores must be a non-empty mapping")
        if len(self.concept_scores) > 64:
            raise ValueError("concept_scores exceeds 64 keys")
        frozen_scores: dict[str, float] = {}
        for key, score in self.concept_scores.items():
            _short_string(key, "concept score key", 80)
            _probability(score, "concept score")
            frozen_scores[key] = float(score)
        object.__setattr__(self, "concept_scores", frozen_scores)
        if not isinstance(self.geometry, GeometryV1):
            raise TypeError("geometry must be GeometryV1")
        if not isinstance(self.geometry_covariance, CovarianceND):
            raise TypeError("geometry_covariance must be CovarianceND")
        _probability(self.free_space_support, "free_space_support")
        if isinstance(self.observation_count, bool) or not isinstance(self.observation_count, int):
            raise TypeError("observation_count must be an integer")
        if self.observation_count < 1:
            raise ValueError("observation_count must be ≥ 1")
        object.__setattr__(
            self,
            "evidence_refs",
            _string_tuple(self.evidence_refs, "evidence_refs", maximum_items=32),
        )

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> SemanticRegionV1:
        data = _mapping(value, "SemanticRegionV1")
        _exact_fields(
            data,
            {
                "envelope",
                "concept_scores",
                "geometry",
                "geometry_covariance",
                "free_space_support",
                "observation_count",
                "evidence_refs",
            },
            "SemanticRegionV1",
        )
        scores_raw = _mapping(data["concept_scores"], "concept_scores")
        scores = {
            _string(key, "concept key", maximum=80): _number(val, "concept score")
            for key, val in scores_raw.items()
        }
        return cls(
            envelope=EvidenceEnvelopeV1.from_mapping(_mapping(data["envelope"], "envelope")),
            concept_scores=scores,
            geometry=GeometryV1.from_mapping(_mapping(data["geometry"], "geometry")),
            geometry_covariance=CovarianceND.from_mapping(
                _mapping(data["geometry_covariance"], "geometry_covariance")
            ),
            free_space_support=_number(data["free_space_support"], "free_space_support"),
            observation_count=_integer(data["observation_count"], "observation_count"),
            evidence_refs=_strings(data["evidence_refs"], "evidence_refs", 32),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "envelope": self.envelope.as_dict(),
            "concept_scores": dict(self.concept_scores),
            "geometry": self.geometry.as_dict(),
            "geometry_covariance": self.geometry_covariance.as_dict(),
            "free_space_support": self.free_space_support,
            "observation_count": self.observation_count,
            "evidence_refs": list(self.evidence_refs),
        }


@dataclass(frozen=True, slots=True)
class GoalRegionV1:
    """Navigation goal region shared by scorer and task verifier."""

    goal_id: str
    source_task_id: str
    plan_step_id: str
    frame_id: str
    acceptable_polygon: tuple[tuple[float, float], ...]
    preferred_pose: PoseXYZYaw | None
    approach_constraints: tuple[str, ...]
    forbidden_regions: tuple[GeometryV1, ...]
    relation: str
    hold_duration_s: float
    confidence: float
    issued_at_monotonic_ns: int
    expires_at_monotonic_ns: int
    evidence_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _identifier(self.goal_id, "goal_id")
        _identifier(self.source_task_id, "source_task_id")
        _identifier(self.plan_step_id, "plan_step_id")
        _short_string(self.frame_id, "frame_id", 64)
        if len(self.acceptable_polygon) < 3:
            raise ValueError("acceptable_polygon requires ≥3 vertices")
        for point in self.acceptable_polygon:
            _finite_tuple(point, "acceptable_polygon vertex", length=2)
        if self.preferred_pose is not None and not isinstance(self.preferred_pose, PoseXYZYaw):
            raise TypeError("preferred_pose must be PoseXYZYaw or null")
        object.__setattr__(
            self,
            "approach_constraints",
            _string_tuple(self.approach_constraints, "approach_constraints", maximum_items=16),
        )
        if not isinstance(self.forbidden_regions, tuple):
            raise TypeError("forbidden_regions must be a tuple")
        if len(self.forbidden_regions) > 16:
            raise ValueError("forbidden_regions exceeds 16 items")
        if any(not isinstance(item, GeometryV1) for item in self.forbidden_regions):
            raise TypeError("forbidden_regions must contain GeometryV1")
        _enum(self.relation, GOAL_RELATIONS, "goal relation")
        _bounded_number(self.hold_duration_s, "hold_duration_s", minimum=0.0, maximum=3_600.0)
        _probability(self.confidence, "goal confidence")
        _nonneg_int(self.issued_at_monotonic_ns, "issued_at_monotonic_ns")
        _nonneg_int(self.expires_at_monotonic_ns, "expires_at_monotonic_ns")
        if self.expires_at_monotonic_ns <= self.issued_at_monotonic_ns:
            raise ValueError("expires_at_monotonic_ns must be after issued_at_monotonic_ns")
        object.__setattr__(
            self,
            "evidence_refs",
            _string_tuple(self.evidence_refs, "evidence_refs", maximum_items=32),
        )

    def expired(self, now_monotonic_ns: int) -> bool:
        from parcel_robot.contracts.freshness import is_expired

        return is_expired(
            expires_monotonic_ns=self.expires_at_monotonic_ns,
            now_monotonic_ns=now_monotonic_ns,
        )

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> GoalRegionV1:
        data = _mapping(value, "GoalRegionV1")
        _exact_fields(
            data,
            {
                "goal_id",
                "source_task_id",
                "plan_step_id",
                "frame_id",
                "acceptable_polygon",
                "preferred_pose",
                "approach_constraints",
                "forbidden_regions",
                "relation",
                "hold_duration_s",
                "confidence",
                "issued_at_monotonic_ns",
                "expires_at_monotonic_ns",
                "evidence_refs",
            },
            "GoalRegionV1",
        )
        poly = _sequence(data["acceptable_polygon"], "acceptable_polygon", maximum=256)
        forbidden = _sequence(data["forbidden_regions"], "forbidden_regions", maximum=16)
        preferred_raw = data["preferred_pose"]
        preferred = (
            None
            if preferred_raw is None
            else PoseXYZYaw.from_mapping(_mapping(preferred_raw, "preferred_pose"))
        )
        return cls(
            goal_id=_string(data["goal_id"], "goal_id", maximum=128),
            source_task_id=_string(data["source_task_id"], "source_task_id", maximum=128),
            plan_step_id=_string(data["plan_step_id"], "plan_step_id", maximum=128),
            frame_id=_string(data["frame_id"], "frame_id", maximum=64),
            acceptable_polygon=tuple(
                (
                    _number(_sequence(pt, "vertex", maximum=2)[0], "x"),
                    _number(_sequence(pt, "vertex", maximum=2)[1], "y"),
                )
                for pt in poly
            ),
            preferred_pose=preferred,
            approach_constraints=_strings(
                data["approach_constraints"], "approach_constraints", 16
            ),
            forbidden_regions=tuple(
                GeometryV1.from_mapping(_mapping(item, "forbidden region")) for item in forbidden
            ),
            relation=_string(data["relation"], "relation", maximum=32),
            hold_duration_s=_number(data["hold_duration_s"], "hold_duration_s"),
            confidence=_number(data["confidence"], "confidence"),
            issued_at_monotonic_ns=_integer(
                data["issued_at_monotonic_ns"], "issued_at_monotonic_ns"
            ),
            expires_at_monotonic_ns=_integer(
                data["expires_at_monotonic_ns"], "expires_at_monotonic_ns"
            ),
            evidence_refs=_strings(data["evidence_refs"], "evidence_refs", 32),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "goal_id": self.goal_id,
            "source_task_id": self.source_task_id,
            "plan_step_id": self.plan_step_id,
            "frame_id": self.frame_id,
            "acceptable_polygon": [list(p) for p in self.acceptable_polygon],
            "preferred_pose": (
                self.preferred_pose.as_dict() if self.preferred_pose is not None else None
            ),
            "approach_constraints": list(self.approach_constraints),
            "forbidden_regions": [item.as_dict() for item in self.forbidden_regions],
            "relation": self.relation,
            "hold_duration_s": self.hold_duration_s,
            "confidence": self.confidence,
            "issued_at_monotonic_ns": self.issued_at_monotonic_ns,
            "expires_at_monotonic_ns": self.expires_at_monotonic_ns,
            "evidence_refs": list(self.evidence_refs),
        }


# ---------------------------------------------------------------------------
# Voice / behavior contracts
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DialogueClaimV1:
    text: str
    veracity: str
    evidence_ref: str = ""

    def __post_init__(self) -> None:
        _short_string(self.text, "claim text", 400)
        _enum(self.veracity, CLAIM_VERACITY, "claim veracity")
        if self.veracity == "verified" or self.evidence_ref:
            _short_string(self.evidence_ref, "claim evidence_ref", 160)

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> DialogueClaimV1:
        data = _mapping(value, "dialogue claim")
        _exact_fields(data, {"text", "veracity", "evidence_ref"}, "dialogue claim")
        return cls(
            text=_string(data["text"], "claim text", maximum=400),
            veracity=_string(data["veracity"], "veracity", maximum=32),
            evidence_ref=_string(
                data["evidence_ref"], "evidence_ref", maximum=160, allow_empty=True
            ),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "text": self.text,
            "veracity": self.veracity,
            "evidence_ref": self.evidence_ref,
        }


@dataclass(frozen=True, slots=True)
class DialogueActV1:
    schema_version: int
    turn_id: str
    text: str
    speech_style: str
    acknowledgement_kind: str
    claims: tuple[DialogueClaimV1, ...]
    social_cues: tuple[str, ...]
    asks_clarification: bool

    def __post_init__(self) -> None:
        _version(self.schema_version)
        _identifier(self.turn_id, "turn_id")
        _short_string(self.text, "dialogue text", 2000)
        _short_string(self.speech_style, "speech_style", 64)
        _short_string(self.acknowledgement_kind, "acknowledgement_kind", 64)
        if not isinstance(self.claims, tuple) or any(
            not isinstance(item, DialogueClaimV1) for item in self.claims
        ):
            raise TypeError("claims must be a tuple of DialogueClaimV1")
        if len(self.claims) > 16:
            raise ValueError("claims exceeds 16 items")
        object.__setattr__(
            self,
            "social_cues",
            _string_tuple(self.social_cues, "social_cues", maximum_items=8),
        )
        if not isinstance(self.asks_clarification, bool):
            raise TypeError("asks_clarification must be a boolean")

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> DialogueActV1:
        data = _mapping(value, "DialogueActV1")
        _exact_fields(
            data,
            {
                "schema_version",
                "turn_id",
                "text",
                "speech_style",
                "acknowledgement_kind",
                "claims",
                "social_cues",
                "asks_clarification",
            },
            "DialogueActV1",
        )
        claims = _sequence(data["claims"], "claims", maximum=16)
        return cls(
            schema_version=_integer(data["schema_version"], "schema_version"),
            turn_id=_string(data["turn_id"], "turn_id", maximum=128),
            text=_string(data["text"], "text", maximum=2000),
            speech_style=_string(data["speech_style"], "speech_style", maximum=64),
            acknowledgement_kind=_string(
                data["acknowledgement_kind"], "acknowledgement_kind", maximum=64
            ),
            claims=tuple(
                DialogueClaimV1.from_mapping(_mapping(item, "dialogue claim")) for item in claims
            ),
            social_cues=_strings(data["social_cues"], "social_cues", 8),
            asks_clarification=_boolean(data["asks_clarification"], "asks_clarification"),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "turn_id": self.turn_id,
            "text": self.text,
            "speech_style": self.speech_style,
            "acknowledgement_kind": self.acknowledgement_kind,
            "claims": [item.as_dict() for item in self.claims],
            "social_cues": list(self.social_cues),
            "asks_clarification": self.asks_clarification,
        }


@dataclass(frozen=True, slots=True)
class SocialCueV1:
    cue_id: str
    source_turn_id: str
    kind: str
    modality: str
    evidence_ref: str
    confidence: float
    valence: float
    arousal: float
    observed_at_monotonic_ns: int
    expires_at_monotonic_ns: int

    def __post_init__(self) -> None:
        _identifier(self.cue_id, "cue_id")
        _identifier(self.source_turn_id, "source_turn_id")
        _enum(self.kind, SOCIAL_CUE_KINDS, "social cue kind")
        _enum(self.modality, SOCIAL_CUE_MODALITIES, "social cue modality")
        _short_string(self.evidence_ref, "evidence_ref", 160)
        _probability(self.confidence, "social cue confidence")
        _bounded_number(self.valence, "valence", minimum=-1.0, maximum=1.0)
        _bounded_number(self.arousal, "arousal", minimum=0.0, maximum=1.0)
        _nonneg_int(self.observed_at_monotonic_ns, "observed_at_monotonic_ns")
        _nonneg_int(self.expires_at_monotonic_ns, "expires_at_monotonic_ns")
        if self.expires_at_monotonic_ns <= self.observed_at_monotonic_ns:
            raise ValueError("social cue expires_at must be after observed_at")

    def expired(self, now_monotonic_ns: int) -> bool:
        from parcel_robot.contracts.freshness import is_expired

        return is_expired(
            expires_monotonic_ns=self.expires_at_monotonic_ns,
            now_monotonic_ns=now_monotonic_ns,
        )

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> SocialCueV1:
        data = _mapping(value, "SocialCueV1")
        _exact_fields(
            data,
            {
                "cue_id",
                "source_turn_id",
                "kind",
                "modality",
                "evidence_ref",
                "confidence",
                "valence",
                "arousal",
                "observed_at_monotonic_ns",
                "expires_at_monotonic_ns",
            },
            "SocialCueV1",
        )
        return cls(
            cue_id=_string(data["cue_id"], "cue_id", maximum=128),
            source_turn_id=_string(data["source_turn_id"], "source_turn_id", maximum=128),
            kind=_string(data["kind"], "kind", maximum=40),
            modality=_string(data["modality"], "modality", maximum=32),
            evidence_ref=_string(data["evidence_ref"], "evidence_ref", maximum=160),
            confidence=_number(data["confidence"], "confidence"),
            valence=_number(data["valence"], "valence"),
            arousal=_number(data["arousal"], "arousal"),
            observed_at_monotonic_ns=_integer(
                data["observed_at_monotonic_ns"], "observed_at_monotonic_ns"
            ),
            expires_at_monotonic_ns=_integer(
                data["expires_at_monotonic_ns"], "expires_at_monotonic_ns"
            ),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "cue_id": self.cue_id,
            "source_turn_id": self.source_turn_id,
            "kind": self.kind,
            "modality": self.modality,
            "evidence_ref": self.evidence_ref,
            "confidence": self.confidence,
            "valence": self.valence,
            "arousal": self.arousal,
            "observed_at_monotonic_ns": self.observed_at_monotonic_ns,
            "expires_at_monotonic_ns": self.expires_at_monotonic_ns,
        }


@dataclass(frozen=True, slots=True)
class ReactionProposalV1:
    proposal_id: str
    source_cue_ids: tuple[str, ...]
    behavior_id: str
    required_tracks: tuple[str, ...]
    confidence: float
    urgency: float
    earliest_start_monotonic_ns: int
    expires_at_monotonic_ns: int
    minimum_dwell_s: float
    maximum_duration_s: float
    interruption_policy: str
    suppress_if: tuple[str, ...] = ()
    personality_rule_id: str = ""

    def __post_init__(self) -> None:
        _identifier(self.proposal_id, "proposal_id")
        object.__setattr__(
            self,
            "source_cue_ids",
            _string_tuple(self.source_cue_ids, "source_cue_ids", maximum_items=8),
        )
        if not self.source_cue_ids:
            raise ValueError("source_cue_ids must be non-empty")
        _identifier(self.behavior_id, "behavior_id")
        object.__setattr__(
            self,
            "required_tracks",
            _string_tuple(self.required_tracks, "required_tracks", maximum_items=8),
        )
        if not self.required_tracks:
            raise ValueError("required_tracks must be non-empty")
        for track in self.required_tracks:
            _enum(track, RESOURCE_TRACKS, "required track")
        _probability(self.confidence, "reaction confidence")
        _probability(self.urgency, "reaction urgency")
        _nonneg_int(self.earliest_start_monotonic_ns, "earliest_start_monotonic_ns")
        _nonneg_int(self.expires_at_monotonic_ns, "expires_at_monotonic_ns")
        if self.expires_at_monotonic_ns <= self.earliest_start_monotonic_ns:
            raise ValueError("reaction expires_at must be after earliest_start")
        _bounded_number(self.minimum_dwell_s, "minimum_dwell_s", minimum=0.0, maximum=60.0)
        _bounded_number(self.maximum_duration_s, "maximum_duration_s", minimum=0.0, maximum=120.0)
        if self.maximum_duration_s < self.minimum_dwell_s:
            raise ValueError("maximum_duration_s must be ≥ minimum_dwell_s")
        _enum(self.interruption_policy, INTERRUPTION_POLICIES, "interruption_policy")
        object.__setattr__(
            self,
            "suppress_if",
            _string_tuple(self.suppress_if, "suppress_if", maximum_items=16),
        )
        if self.personality_rule_id:
            _identifier(self.personality_rule_id, "personality_rule_id")

    def expired(self, now_monotonic_ns: int) -> bool:
        from parcel_robot.contracts.freshness import is_expired

        return is_expired(
            expires_monotonic_ns=self.expires_at_monotonic_ns,
            now_monotonic_ns=now_monotonic_ns,
        )

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> ReactionProposalV1:
        data = _mapping(value, "ReactionProposalV1")
        _exact_fields(
            data,
            {
                "proposal_id",
                "source_cue_ids",
                "behavior_id",
                "required_tracks",
                "confidence",
                "urgency",
                "earliest_start_monotonic_ns",
                "expires_at_monotonic_ns",
                "minimum_dwell_s",
                "maximum_duration_s",
                "interruption_policy",
                "suppress_if",
                "personality_rule_id",
            },
            "ReactionProposalV1",
        )
        return cls(
            proposal_id=_string(data["proposal_id"], "proposal_id", maximum=128),
            source_cue_ids=_strings(data["source_cue_ids"], "source_cue_ids", 8),
            behavior_id=_string(data["behavior_id"], "behavior_id", maximum=128),
            required_tracks=_strings(data["required_tracks"], "required_tracks", 8),
            confidence=_number(data["confidence"], "confidence"),
            urgency=_number(data["urgency"], "urgency"),
            earliest_start_monotonic_ns=_integer(
                data["earliest_start_monotonic_ns"], "earliest_start_monotonic_ns"
            ),
            expires_at_monotonic_ns=_integer(
                data["expires_at_monotonic_ns"], "expires_at_monotonic_ns"
            ),
            minimum_dwell_s=_number(data["minimum_dwell_s"], "minimum_dwell_s"),
            maximum_duration_s=_number(data["maximum_duration_s"], "maximum_duration_s"),
            interruption_policy=_string(
                data["interruption_policy"], "interruption_policy", maximum=32
            ),
            suppress_if=_strings(data["suppress_if"], "suppress_if", 16),
            personality_rule_id=_string(
                data["personality_rule_id"], "personality_rule_id", maximum=128, allow_empty=True
            ),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "proposal_id": self.proposal_id,
            "source_cue_ids": list(self.source_cue_ids),
            "behavior_id": self.behavior_id,
            "required_tracks": list(self.required_tracks),
            "confidence": self.confidence,
            "urgency": self.urgency,
            "earliest_start_monotonic_ns": self.earliest_start_monotonic_ns,
            "expires_at_monotonic_ns": self.expires_at_monotonic_ns,
            "minimum_dwell_s": self.minimum_dwell_s,
            "maximum_duration_s": self.maximum_duration_s,
            "interruption_policy": self.interruption_policy,
            "suppress_if": list(self.suppress_if),
            "personality_rule_id": self.personality_rule_id,
        }


@dataclass(frozen=True, slots=True)
class SceneQueryV1:
    query_id: str
    task_id: str
    plan_revision: int
    terms: tuple[str, ...]
    requested_relation: str
    freshness_required_ms: float
    minimum_confidence: float
    search_budget_s: float
    allow_cached: bool
    allow_active_scan: bool

    def __post_init__(self) -> None:
        _identifier(self.query_id, "query_id")
        _identifier(self.task_id, "task_id")
        if isinstance(self.plan_revision, bool) or not isinstance(self.plan_revision, int):
            raise TypeError("plan_revision must be an integer")
        if self.plan_revision < 1:
            raise ValueError("plan_revision must be ≥ 1")
        object.__setattr__(
            self, "terms", _string_tuple(self.terms, "terms", maximum_items=16)
        )
        if not self.terms:
            raise ValueError("terms must be non-empty")
        _enum(self.requested_relation, GOAL_RELATIONS, "requested_relation")
        _bounded_number(
            self.freshness_required_ms, "freshness_required_ms", minimum=0.0, maximum=60_000.0
        )
        _probability(self.minimum_confidence, "minimum_confidence")
        _bounded_number(self.search_budget_s, "search_budget_s", minimum=0.0, maximum=300.0)
        if not isinstance(self.allow_cached, bool) or not isinstance(self.allow_active_scan, bool):
            raise TypeError("allow_cached/allow_active_scan must be booleans")

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> SceneQueryV1:
        data = _mapping(value, "SceneQueryV1")
        _exact_fields(
            data,
            {
                "query_id",
                "task_id",
                "plan_revision",
                "terms",
                "requested_relation",
                "freshness_required_ms",
                "minimum_confidence",
                "search_budget_s",
                "allow_cached",
                "allow_active_scan",
            },
            "SceneQueryV1",
        )
        return cls(
            query_id=_string(data["query_id"], "query_id", maximum=128),
            task_id=_string(data["task_id"], "task_id", maximum=128),
            plan_revision=_integer(data["plan_revision"], "plan_revision"),
            terms=_strings(data["terms"], "terms", 16),
            requested_relation=_string(data["requested_relation"], "requested_relation", maximum=32),
            freshness_required_ms=_number(data["freshness_required_ms"], "freshness_required_ms"),
            minimum_confidence=_number(data["minimum_confidence"], "minimum_confidence"),
            search_budget_s=_number(data["search_budget_s"], "search_budget_s"),
            allow_cached=_boolean(data["allow_cached"], "allow_cached"),
            allow_active_scan=_boolean(data["allow_active_scan"], "allow_active_scan"),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "query_id": self.query_id,
            "task_id": self.task_id,
            "plan_revision": self.plan_revision,
            "terms": list(self.terms),
            "requested_relation": self.requested_relation,
            "freshness_required_ms": self.freshness_required_ms,
            "minimum_confidence": self.minimum_confidence,
            "search_budget_s": self.search_budget_s,
            "allow_cached": self.allow_cached,
            "allow_active_scan": self.allow_active_scan,
        }


@dataclass(frozen=True, slots=True)
class SkillFeedbackV1:
    task_id: str
    plan_revision: int
    step_id: str
    status: str
    checkpoint: bool
    critical_phase: bool
    progress: float
    verified_facts: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    blocking_reason: str
    scene_revision: int

    def __post_init__(self) -> None:
        _identifier(self.task_id, "task_id")
        if isinstance(self.plan_revision, bool) or not isinstance(self.plan_revision, int):
            raise TypeError("plan_revision must be an integer")
        if self.plan_revision < 1:
            raise ValueError("plan_revision must be ≥ 1")
        _identifier(self.step_id, "step_id")
        _enum(self.status, SKILL_FEEDBACK_STATUSES, "skill feedback status")
        if not isinstance(self.checkpoint, bool) or not isinstance(self.critical_phase, bool):
            raise TypeError("checkpoint/critical_phase must be booleans")
        _probability(self.progress, "progress")
        object.__setattr__(
            self,
            "verified_facts",
            _string_tuple(self.verified_facts, "verified_facts", maximum_items=16),
        )
        object.__setattr__(
            self,
            "evidence_refs",
            _string_tuple(self.evidence_refs, "evidence_refs", maximum_items=32),
        )
        _string(self.blocking_reason, "blocking_reason", maximum=200, allow_empty=True)
        if isinstance(self.scene_revision, bool) or not isinstance(self.scene_revision, int):
            raise TypeError("scene_revision must be an integer")
        if self.scene_revision < 0:
            raise ValueError("scene_revision must be non-negative")

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> SkillFeedbackV1:
        data = _mapping(value, "SkillFeedbackV1")
        _exact_fields(
            data,
            {
                "task_id",
                "plan_revision",
                "step_id",
                "status",
                "checkpoint",
                "critical_phase",
                "progress",
                "verified_facts",
                "evidence_refs",
                "blocking_reason",
                "scene_revision",
            },
            "SkillFeedbackV1",
        )
        return cls(
            task_id=_string(data["task_id"], "task_id", maximum=128),
            plan_revision=_integer(data["plan_revision"], "plan_revision"),
            step_id=_string(data["step_id"], "step_id", maximum=128),
            status=_string(data["status"], "status", maximum=32),
            checkpoint=_boolean(data["checkpoint"], "checkpoint"),
            critical_phase=_boolean(data["critical_phase"], "critical_phase"),
            progress=_number(data["progress"], "progress"),
            verified_facts=_strings(data["verified_facts"], "verified_facts", 16),
            evidence_refs=_strings(data["evidence_refs"], "evidence_refs", 32),
            blocking_reason=_string(
                data["blocking_reason"], "blocking_reason", maximum=200, allow_empty=True
            ),
            scene_revision=_integer(data["scene_revision"], "scene_revision"),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "task_id": self.task_id,
            "plan_revision": self.plan_revision,
            "step_id": self.step_id,
            "status": self.status,
            "checkpoint": self.checkpoint,
            "critical_phase": self.critical_phase,
            "progress": self.progress,
            "verified_facts": list(self.verified_facts),
            "evidence_refs": list(self.evidence_refs),
            "blocking_reason": self.blocking_reason,
            "scene_revision": self.scene_revision,
        }


# ---------------------------------------------------------------------------
# Fable additions: DetectionMsg + dialogue-state channel
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DetectionMsg:
    """Detector-shaped observation shared by sim-noise adapter and real detectors.

    Fields match the hillclimb ladder: class, embedding, bearing, range, score,
    wrapped in EvidenceEnvelopeV1 so freshness/frame ownership stay enforceable.
    """

    envelope: EvidenceEnvelopeV1
    class_id: str
    embedding: tuple[float, ...]
    bearing_rad: float
    range_m: float
    score: float
    track_id: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.envelope, EvidenceEnvelopeV1):
            raise TypeError("envelope must be EvidenceEnvelopeV1")
        _short_string(self.class_id, "class_id", 64)
        if not isinstance(self.embedding, tuple):
            raise TypeError("embedding must be a tuple")
        if not self.embedding or len(self.embedding) > 2048:
            raise ValueError("embedding must contain 1..2048 floats")
        _finite_tuple(self.embedding, "embedding")
        _number(self.bearing_rad, "bearing_rad")
        if not -math.pi - 1e-9 <= self.bearing_rad <= math.pi + 1e-9:
            raise ValueError("bearing_rad must be in [-π, π]")
        _bounded_number(self.range_m, "range_m", minimum=0.0, maximum=200.0)
        _probability(self.score, "detection score")
        if self.track_id:
            _identifier(self.track_id, "track_id")

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> DetectionMsg:
        data = _mapping(value, "DetectionMsg")
        _exact_fields(
            data,
            {
                "envelope",
                "class_id",
                "embedding",
                "bearing_rad",
                "range_m",
                "score",
                "track_id",
            },
            "DetectionMsg",
        )
        emb = _sequence(data["embedding"], "embedding", maximum=2048)
        return cls(
            envelope=EvidenceEnvelopeV1.from_mapping(_mapping(data["envelope"], "envelope")),
            class_id=_string(data["class_id"], "class_id", maximum=64),
            embedding=tuple(_number(item, "embedding component") for item in emb),
            bearing_rad=_number(data["bearing_rad"], "bearing_rad"),
            range_m=_number(data["range_m"], "range_m"),
            score=_number(data["score"], "score"),
            track_id=_string(data["track_id"], "track_id", maximum=128, allow_empty=True),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "envelope": self.envelope.as_dict(),
            "class_id": self.class_id,
            "embedding": list(self.embedding),
            "bearing_rad": self.bearing_rad,
            "range_m": self.range_m,
            "score": self.score,
            "track_id": self.track_id,
        }


@dataclass(frozen=True, slots=True)
class DialogueStateMsg:
    """10 Hz StimulusBus dialogue-state channel (Fable white-space differentiator).

    Phase ∈ {speaking, listening, thinking, idle}; engagement ∈ [0, 1].
    T2 maps this to gaze/gait/pace; planner may defer non-urgent autonomy when
    engagement is high mid-sentence.
    """

    schema_version: int
    channel: str
    phase: str
    engagement: float
    turn_id: str
    published_monotonic_ns: int
    expires_monotonic_ns: int
    sequence: int = 0

    def __post_init__(self) -> None:
        _version(self.schema_version)
        if self.channel != "dialogue_state":
            raise ValueError("DialogueStateMsg.channel must be 'dialogue_state'")
        _enum(self.phase, DIALOGUE_PHASES, "dialogue phase")
        _probability(self.engagement, "engagement")
        if self.turn_id:
            _identifier(self.turn_id, "turn_id")
        _nonneg_int(self.published_monotonic_ns, "published_monotonic_ns")
        _nonneg_int(self.expires_monotonic_ns, "expires_monotonic_ns")
        if self.expires_monotonic_ns <= self.published_monotonic_ns:
            raise ValueError("dialogue-state expires must be after published")
        _nonneg_int(self.sequence, "sequence")

    def expired(self, now_monotonic_ns: int) -> bool:
        from parcel_robot.contracts.freshness import is_expired

        return is_expired(
            expires_monotonic_ns=self.expires_monotonic_ns,
            now_monotonic_ns=now_monotonic_ns,
        )

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> DialogueStateMsg:
        data = _mapping(value, "DialogueStateMsg")
        _exact_fields(
            data,
            {
                "schema_version",
                "channel",
                "phase",
                "engagement",
                "turn_id",
                "published_monotonic_ns",
                "expires_monotonic_ns",
                "sequence",
            },
            "DialogueStateMsg",
        )
        return cls(
            schema_version=_integer(data["schema_version"], "schema_version"),
            channel=_string(data["channel"], "channel", maximum=40),
            phase=_string(data["phase"], "phase", maximum=32),
            engagement=_number(data["engagement"], "engagement"),
            turn_id=_string(data["turn_id"], "turn_id", maximum=128, allow_empty=True),
            published_monotonic_ns=_integer(
                data["published_monotonic_ns"], "published_monotonic_ns"
            ),
            expires_monotonic_ns=_integer(data["expires_monotonic_ns"], "expires_monotonic_ns"),
            sequence=_integer(data["sequence"], "sequence"),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "channel": self.channel,
            "phase": self.phase,
            "engagement": self.engagement,
            "turn_id": self.turn_id,
            "published_monotonic_ns": self.published_monotonic_ns,
            "expires_monotonic_ns": self.expires_monotonic_ns,
            "sequence": self.sequence,
        }


def identity_covariance(dim: int, variance: float = 1.0) -> CovarianceND:
    """Convenience diagonal covariance for tests and stubs."""

    _bounded_number(variance, "variance", minimum=0.0, maximum=None)
    values = []
    for i in range(dim):
        for j in range(dim):
            values.append(float(variance) if i == j else 0.0)
    return CovarianceND(values=tuple(values), dim=dim)
