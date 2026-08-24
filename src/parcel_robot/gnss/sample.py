"""GnssFix — envelope-compatible ZED-F9P-shaped observation (pure).

Bag topic ``gnss/fix`` carries the same fields. Map-frame east/north meters
are the sim-local stand-in for lat/lon until P5 bags use WGS84.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass

from parcel_robot.contracts.v1 import SCHEMA_VERSION, EvidenceEnvelopeV1


def _number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def _nonneg(value: object, name: str) -> float:
    number = _number(value, name)
    if number < 0.0:
        raise ValueError(f"{name} must be non-negative")
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
class GnssFix:
    """Planar GNSS fix shaped for bag topic ``gnss/fix`` (HR-3).

    ``east_m`` / ``north_m`` are map-frame meters (sim local ENU). Covariance
    is the 2×2 horizontal block (ee, nn, en) in m². ``dropout`` samples are
    omitted entirely by the model; this DTO is only emitted on a usable fix.
    """

    envelope: EvidenceEnvelopeV1
    east_m: float
    north_m: float
    cov_east_m2: float
    cov_north_m2: float
    cov_cross_m2: float
    hdop: float
    num_sats: int
    fix_type: str
    horizontal_std_m: float

    def __post_init__(self) -> None:
        if not isinstance(self.envelope, EvidenceEnvelopeV1):
            raise TypeError("envelope must be EvidenceEnvelopeV1")
        _number(self.east_m, "east_m")
        _number(self.north_m, "north_m")
        _nonneg(self.cov_east_m2, "cov_east_m2")
        _nonneg(self.cov_north_m2, "cov_north_m2")
        _number(self.cov_cross_m2, "cov_cross_m2")
        _nonneg(self.hdop, "hdop")
        if isinstance(self.num_sats, bool) or not isinstance(self.num_sats, int):
            raise TypeError("num_sats must be an integer")
        if self.num_sats < 0 or self.num_sats > 64:
            raise ValueError("num_sats must be in [0, 64]")
        _string(self.fix_type, "fix_type", maximum=32)
        _nonneg(self.horizontal_std_m, "horizontal_std_m")

    def require_fresh(self, now_monotonic_ns: int, *, max_age_ns: int | None = None) -> None:
        self.envelope.require_fresh(now_monotonic_ns, max_age_ns=max_age_ns)

    def expired(self, now_monotonic_ns: int) -> bool:
        return self.envelope.expired(now_monotonic_ns)

    def usable(self, *, max_horizontal_std_m: float) -> bool:
        if isinstance(max_horizontal_std_m, bool) or not isinstance(
            max_horizontal_std_m, (int, float)
        ):
            raise TypeError("max_horizontal_std_m must be numeric")
        limit = float(max_horizontal_std_m)
        if not math.isfinite(limit) or limit <= 0.0:
            raise ValueError("max_horizontal_std_m must be positive")
        return self.horizontal_std_m <= limit and self.num_sats > 0

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> GnssFix:
        data = _mapping(value, "GnssFix")
        _exact_fields(
            data,
            {
                "envelope",
                "east_m",
                "north_m",
                "cov_east_m2",
                "cov_north_m2",
                "cov_cross_m2",
                "hdop",
                "num_sats",
                "fix_type",
                "horizontal_std_m",
            },
            "GnssFix",
        )
        return cls(
            envelope=EvidenceEnvelopeV1.from_mapping(_mapping(data["envelope"], "envelope")),
            east_m=_number(data["east_m"], "east_m"),
            north_m=_number(data["north_m"], "north_m"),
            cov_east_m2=_number(data["cov_east_m2"], "cov_east_m2"),
            cov_north_m2=_number(data["cov_north_m2"], "cov_north_m2"),
            cov_cross_m2=_number(data["cov_cross_m2"], "cov_cross_m2"),
            hdop=_number(data["hdop"], "hdop"),
            num_sats=int(data["num_sats"]),
            fix_type=_string(data["fix_type"], "fix_type", maximum=32),
            horizontal_std_m=_number(data["horizontal_std_m"], "horizontal_std_m"),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "envelope": self.envelope.as_dict(),
            "east_m": self.east_m,
            "north_m": self.north_m,
            "cov_east_m2": self.cov_east_m2,
            "cov_north_m2": self.cov_north_m2,
            "cov_cross_m2": self.cov_cross_m2,
            "hdop": self.hdop,
            "num_sats": self.num_sats,
            "fix_type": self.fix_type,
            "horizontal_std_m": self.horizontal_std_m,
        }

    def bag_payload(self) -> dict[str, object]:
        """Agent-path payload for bag topic ``gnss/fix`` (no oracle fields)."""

        return {
            "east_m": self.east_m,
            "north_m": self.north_m,
            "cov_east_m2": self.cov_east_m2,
            "cov_north_m2": self.cov_north_m2,
            "cov_cross_m2": self.cov_cross_m2,
            "hdop": self.hdop,
            "num_sats": self.num_sats,
            "fix_type": self.fix_type,
            "horizontal_std_m": self.horizontal_std_m,
            "schema_version": SCHEMA_VERSION,
        }
