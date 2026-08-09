"""UwbSample — envelope-compatible owner-fob observation (pure).

Mirrors DetectionMsg freshness discipline via EvidenceEnvelopeV1 without
changing frozen K1 contracts. Bag topic ``uwb/state`` carries the same fields.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass

from parcel_robot.contracts import EvidenceEnvelopeV1, SCHEMA_VERSION


def _number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def _probability(value: object, name: str) -> float:
    number = _number(value, name)
    if not 0.0 <= number <= 1.0:
        raise ValueError(f"{name} must be in [0, 1]")
    return number


def _string(value: object, name: str, *, maximum: int, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    if (not allow_empty and not value) or len(value) > maximum:
        raise ValueError(f"{name} must be a non-empty string of at most {maximum} characters")
    return value


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


@dataclass(frozen=True, slots=True)
class UwbSample:
    """Owner-fob bearing/range sample shaped like Unitree ``rt/uwbstate``.

    Uses EvidenceEnvelopeV1 so freshness / TTL / frame ownership match
    DetectionMsg. ``multipath_suspect`` is an honesty flag for fusion (not
    privileged truth); scheduled dropouts omit the sample entirely.
    """

    envelope: EvidenceEnvelopeV1
    fob_id: str
    bearing_rad: float
    range_m: float
    quality: float
    multipath_suspect: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.envelope, EvidenceEnvelopeV1):
            raise TypeError("envelope must be EvidenceEnvelopeV1")
        _string(self.fob_id, "fob_id", maximum=128)
        bearing = _number(self.bearing_rad, "bearing_rad")
        if not -math.pi - 1e-9 <= bearing <= math.pi + 1e-9:
            raise ValueError("bearing_rad must be in [-π, π]")
        range_m = _number(self.range_m, "range_m")
        if range_m < 0.0 or range_m > 200.0:
            raise ValueError("range_m must be between 0 and 200")
        _probability(self.quality, "quality")
        if not isinstance(self.multipath_suspect, bool):
            raise TypeError("multipath_suspect must be a boolean")

    def require_fresh(self, now_monotonic_ns: int, *, max_age_ns: int | None = None) -> None:
        self.envelope.require_fresh(now_monotonic_ns, max_age_ns=max_age_ns)

    def expired(self, now_monotonic_ns: int) -> bool:
        return self.envelope.expired(now_monotonic_ns)

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> UwbSample:
        data = _mapping(value, "UwbSample")
        _exact_fields(
            data,
            {
                "envelope",
                "fob_id",
                "bearing_rad",
                "range_m",
                "quality",
                "multipath_suspect",
            },
            "UwbSample",
        )
        return cls(
            envelope=EvidenceEnvelopeV1.from_mapping(_mapping(data["envelope"], "envelope")),
            fob_id=_string(data["fob_id"], "fob_id", maximum=128),
            bearing_rad=_number(data["bearing_rad"], "bearing_rad"),
            range_m=_number(data["range_m"], "range_m"),
            quality=_number(data["quality"], "quality"),
            multipath_suspect=bool(data["multipath_suspect"]),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "envelope": self.envelope.as_dict(),
            "fob_id": self.fob_id,
            "bearing_rad": self.bearing_rad,
            "range_m": self.range_m,
            "quality": self.quality,
            "multipath_suspect": self.multipath_suspect,
        }

    def bag_payload(self) -> dict[str, object]:
        """Agent-path payload for bag topic ``uwb/state`` (no oracle fields)."""

        return {
            "fob_id": self.fob_id,
            "bearing_rad": self.bearing_rad,
            "range_m": self.range_m,
            "quality": self.quality,
            "multipath_suspect": self.multipath_suspect,
            "schema_version": SCHEMA_VERSION,
        }
