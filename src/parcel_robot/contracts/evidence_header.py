"""``EvidenceHeaderV1`` — the stamp every sensor-derived datum carries (A4 SPINE).

HLD ``research/20260824/PORTABLE_LIVING_DOG_HLD.md`` §4.1 is binding here: a
header names *where* a sample came from, *when* it was captured on which clock,
*which* frame and calibration it is expressed in, and *how* the producer wants
it to expire.  Consumers never infer any of that from a producer's class or
name — card W0-A retired inference for provenance and this module extends the
same discipline to time, frames and calibration.

Five conditions **fail closed** (§4.1's list), and each one is a named reason
rather than a bare boolean so a HOLD can say what went wrong:

* mixed process epochs among the headers contributing to one snapshot;
* an unknown transform (a frame the deployment never commissioned);
* a stale sample (measured transport age past the producer's own TTL);
* a simulation/replay origin inside a physical profile;
* an uncommissioned calibration hash.

This module is a LEAF: standard library plus
:mod:`parcel_robot.evidence_origin` only.  Nothing here imports the runtime,
navigation, a backend or a vendor SDK, so an adapter in any process may stamp.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from parcel_robot.evidence_origin import SYNTHETIC_ORIGINS, EvidenceOrigin

#: Contract version.  A consumer that does not recognise the version refuses
#: the sample; it never "best-effort" reads a header from the future.
EVIDENCE_HEADER_SCHEMA_VERSION = 1

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,127}$")

# --------------------------------------------------------------------------
# health reasons — the vocabulary a fail-closed refusal speaks
# --------------------------------------------------------------------------
REASON_STALE = "stale"
REASON_MIXED_EPOCH = "mixed_epoch"
REASON_UNKNOWN_FRAME = "unknown_frame"
REASON_UNCOMMISSIONED_CALIBRATION = "uncommissioned_calibration"
REASON_SYNTHETIC_ORIGIN_IN_PHYSICAL_PROFILE = "synthetic_origin_in_physical_profile"
REASON_UNKNOWN_ORIGIN = "unknown_origin"
REASON_CLOCK_MAP_UNCERTAIN = "clock_map_uncertain"
REASON_MISSING_INPUT = "missing_input"
REASON_UNSUPPORTED_SCHEMA = "unsupported_schema"

#: Every reason this module can mint.  Consumers may add their own, but a
#: reason outside a known vocabulary is still a refusal — never a pass.
HEADER_HEALTH_REASONS: frozenset[str] = frozenset(
    {
        REASON_STALE,
        REASON_MIXED_EPOCH,
        REASON_UNKNOWN_FRAME,
        REASON_UNCOMMISSIONED_CALIBRATION,
        REASON_SYNTHETIC_ORIGIN_IN_PHYSICAL_PROFILE,
        REASON_UNKNOWN_ORIGIN,
        REASON_CLOCK_MAP_UNCERTAIN,
        REASON_MISSING_INPUT,
        REASON_UNSUPPORTED_SCHEMA,
    }
)


def _identifier(value: object, name: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER.match(value):
        raise ValueError(f"{name} must be a short identifier (got {value!r})")
    return value


def _nonneg_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    if value < 0:
        raise ValueError(f"{name} must be non-negative")
    return value


def _unit_interval(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a number")
    number = float(value)
    if not math.isfinite(number) or not 0.0 <= number <= 1.0:
        raise ValueError(f"{name} must be a finite probability in [0, 1]")
    return number


def _reasons(value: object, name: str) -> tuple[str, ...]:
    if isinstance(value, str) or not isinstance(value, Iterable):
        raise TypeError(f"{name} must be a sequence of strings")
    rows = tuple(value)
    if len(rows) > 16:
        raise ValueError(f"{name} exceeds 16 entries")
    for item in rows:
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"{name} entries must be non-empty strings")
    return rows


@dataclass(frozen=True, slots=True)
class EvidenceHeaderV1:
    """Provenance, time, frame, calibration and expiry for one sample.

    ``capture_monotonic_ns`` is the producer's own monotonic clock.
    ``transport_age_ns`` is the *measured* age at the consumer — the two are
    kept separate on purpose: a sample whose capture stamp looks fresh but
    which spent 400 ms in a queue is stale, and only the measured age can say
    so.  ``clock_map_uncertainty_ns`` is how well the producer's clock is tied
    to the consumer's; a producer that does not know publishes its bound, and
    a bound wider than the TTL is itself a refusal.
    """

    source_id: str
    process_epoch: int
    capture_monotonic_ns: int
    sequence: int
    evidence_id: str
    frame_id: str
    calibration_hash: str
    origin: EvidenceOrigin
    max_age_ns: int
    transport_age_ns: int
    fixture_label: str = ""
    clock_map_uncertainty_ns: int = 0
    confidence: float = 1.0
    covariance: tuple[float, ...] = ()
    health_reasons: tuple[str, ...] = ()
    schema_version: int = EVIDENCE_HEADER_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _identifier(self.source_id, "source_id")
        _nonneg_int(self.process_epoch, "process_epoch")
        _nonneg_int(self.capture_monotonic_ns, "capture_monotonic_ns")
        _nonneg_int(self.sequence, "sequence")
        _identifier(self.evidence_id, "evidence_id")
        _identifier(self.frame_id, "frame_id")
        _identifier(self.calibration_hash, "calibration_hash")
        if not isinstance(self.origin, EvidenceOrigin):
            raise TypeError("origin must be an EvidenceOrigin — provenance is declared, not named")
        if _nonneg_int(self.max_age_ns, "max_age_ns") <= 0:
            raise ValueError("max_age_ns must be positive — a sample with no TTL cannot expire")
        _nonneg_int(self.transport_age_ns, "transport_age_ns")
        if not isinstance(self.fixture_label, str) or len(self.fixture_label) > 80:
            raise ValueError("fixture_label must be a string of at most 80 characters")
        _nonneg_int(self.clock_map_uncertainty_ns, "clock_map_uncertainty_ns")
        _unit_interval(self.confidence, "confidence")
        if not isinstance(self.covariance, tuple):
            raise TypeError("covariance must be a tuple of finite numbers")
        for item in self.covariance:
            if isinstance(item, bool) or not isinstance(item, (int, float)):
                raise TypeError("covariance entries must be numbers")
            if not math.isfinite(float(item)):
                raise ValueError("covariance entries must be finite")
        object.__setattr__(self, "health_reasons", _reasons(self.health_reasons, "health_reasons"))
        _nonneg_int(self.schema_version, "schema_version")

    @property
    def synthetic(self) -> bool:
        """True when the sample stands in for a physical sensor."""

        return self.origin in SYNTHETIC_ORIGINS

    def age_ns(self, now_monotonic_ns: int) -> int:
        """Age at ``now``: the larger of the measured transport age and the
        capture-to-now gap, so neither a lying stamp nor a slow queue hides."""

        _nonneg_int(now_monotonic_ns, "now_monotonic_ns")
        gap = now_monotonic_ns - self.capture_monotonic_ns
        return max(self.transport_age_ns, max(0, gap))

    def stale(self, now_monotonic_ns: int) -> bool:
        return self.age_ns(now_monotonic_ns) > self.max_age_ns

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "source_id": self.source_id,
            "process_epoch": self.process_epoch,
            "capture_monotonic_ns": self.capture_monotonic_ns,
            "sequence": self.sequence,
            "evidence_id": self.evidence_id,
            "frame_id": self.frame_id,
            "calibration_hash": self.calibration_hash,
            "origin": self.origin.value,
            "max_age_ns": self.max_age_ns,
            "transport_age_ns": self.transport_age_ns,
            "fixture_label": self.fixture_label,
            "clock_map_uncertainty_ns": self.clock_map_uncertainty_ns,
            "confidence": self.confidence,
            "covariance": list(self.covariance),
            "health_reasons": list(self.health_reasons),
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> EvidenceHeaderV1:
        if not isinstance(value, Mapping):
            raise TypeError("EvidenceHeaderV1 must be built from a mapping")
        unknown = set(value) - {
            "schema_version",
            "source_id",
            "process_epoch",
            "capture_monotonic_ns",
            "sequence",
            "evidence_id",
            "frame_id",
            "calibration_hash",
            "origin",
            "max_age_ns",
            "transport_age_ns",
            "fixture_label",
            "clock_map_uncertainty_ns",
            "confidence",
            "covariance",
            "health_reasons",
        }
        if unknown:
            raise ValueError(f"EvidenceHeaderV1 has unknown fields: {sorted(unknown)}")
        raw_origin = value.get("origin", EvidenceOrigin.UNKNOWN)
        origin = (
            raw_origin if isinstance(raw_origin, EvidenceOrigin) else EvidenceOrigin(raw_origin)
        )
        return cls(
            source_id=str(value["source_id"]),
            process_epoch=int(value["process_epoch"]),  # type: ignore[arg-type]
            capture_monotonic_ns=int(value["capture_monotonic_ns"]),  # type: ignore[arg-type]
            sequence=int(value["sequence"]),  # type: ignore[arg-type]
            evidence_id=str(value["evidence_id"]),
            frame_id=str(value["frame_id"]),
            calibration_hash=str(value["calibration_hash"]),
            origin=origin,
            max_age_ns=int(value["max_age_ns"]),  # type: ignore[arg-type]
            transport_age_ns=int(value["transport_age_ns"]),  # type: ignore[arg-type]
            fixture_label=str(value.get("fixture_label", "")),
            clock_map_uncertainty_ns=int(value.get("clock_map_uncertainty_ns", 0)),  # type: ignore[arg-type]
            confidence=float(value.get("confidence", 1.0)),  # type: ignore[arg-type]
            covariance=tuple(float(item) for item in value.get("covariance", ()) or ()),  # type: ignore[union-attr]
            health_reasons=tuple(str(item) for item in value.get("health_reasons", ()) or ()),  # type: ignore[union-attr]
            schema_version=int(value.get("schema_version", EVIDENCE_HEADER_SCHEMA_VERSION)),  # type: ignore[arg-type]
        )


@dataclass(frozen=True, slots=True)
class EvidenceProfile:
    """What a deployment will accept — the physical/simulation gate.

    ``allow_synthetic_origin=False`` is the physical profile: a SIMULATION or
    REPLAY sample reaching a physical robot is a refusal, not a warning.  Empty
    ``commissioned_frames``/``commissioned_calibration_hashes`` mean "this
    deployment has not commissioned a frame list yet"; that is permissive by
    construction and is exactly why the physical profile ships them non-empty.
    """

    name: str = "prototype"
    allow_synthetic_origin: bool = True
    commissioned_frames: frozenset[str] = frozenset()
    commissioned_calibration_hashes: frozenset[str] = frozenset()
    max_clock_map_uncertainty_ns: int = 0

    def __post_init__(self) -> None:
        _identifier(self.name, "profile name")
        if not isinstance(self.allow_synthetic_origin, bool):
            raise TypeError("allow_synthetic_origin must be a boolean")
        for field_name in ("commissioned_frames", "commissioned_calibration_hashes"):
            value = getattr(self, field_name)
            if not isinstance(value, frozenset):
                object.__setattr__(self, field_name, frozenset(value))
        _nonneg_int(self.max_clock_map_uncertainty_ns, "max_clock_map_uncertainty_ns")


#: The shipping default: the desktop/simulator profile, which accepts synthetic
#: evidence and has commissioned no frame list.  ``PHYSICAL_PROFILE`` below is
#: the shape a robot deployment fills in; it is deliberately NOT the default,
#: because a half-filled physical profile is worse than an honest prototype one.
PROTOTYPE_PROFILE = EvidenceProfile(name="prototype")


def physical_profile(
    *,
    frames: Iterable[str],
    calibration_hashes: Iterable[str],
    max_clock_map_uncertainty_ns: int = 5_000_000,
) -> EvidenceProfile:
    """A physical profile: synthetic origins refused, frames/hashes commissioned."""

    frame_set = frozenset(frames)
    hash_set = frozenset(calibration_hashes)
    if not frame_set or not hash_set:
        raise ValueError(
            "a physical profile must commission at least one frame and one calibration hash"
        )
    return EvidenceProfile(
        name="physical",
        allow_synthetic_origin=False,
        commissioned_frames=frame_set,
        commissioned_calibration_hashes=hash_set,
        max_clock_map_uncertainty_ns=max_clock_map_uncertainty_ns,
    )


def header_health_reasons(
    header: EvidenceHeaderV1,
    *,
    now_monotonic_ns: int,
    profile: EvidenceProfile = PROTOTYPE_PROFILE,
) -> tuple[str, ...]:
    """Every reason this header must be refused, in a stable order.

    An empty tuple is the ONLY acceptance.  The producer's own
    ``health_reasons`` are carried through unchanged: a source that already
    knows it is unhealthy can never be argued healthy by a consumer.
    """

    reasons: list[str] = []
    if header.schema_version != EVIDENCE_HEADER_SCHEMA_VERSION:
        reasons.append(REASON_UNSUPPORTED_SCHEMA)
    if header.origin is EvidenceOrigin.UNKNOWN:
        reasons.append(REASON_UNKNOWN_ORIGIN)
    if header.synthetic and not profile.allow_synthetic_origin:
        reasons.append(REASON_SYNTHETIC_ORIGIN_IN_PHYSICAL_PROFILE)
    if header.stale(now_monotonic_ns):
        reasons.append(REASON_STALE)
    if profile.commissioned_frames and header.frame_id not in profile.commissioned_frames:
        reasons.append(REASON_UNKNOWN_FRAME)
    if (
        profile.commissioned_calibration_hashes
        and header.calibration_hash not in profile.commissioned_calibration_hashes
    ):
        reasons.append(REASON_UNCOMMISSIONED_CALIBRATION)
    if (
        profile.max_clock_map_uncertainty_ns
        and header.clock_map_uncertainty_ns > profile.max_clock_map_uncertainty_ns
    ):
        reasons.append(REASON_CLOCK_MAP_UNCERTAIN)
    reasons.extend(header.health_reasons)
    seen: dict[str, None] = {}
    for reason in reasons:
        seen.setdefault(reason, None)
    return tuple(seen)


def mixed_epoch_sources(headers: Iterable[EvidenceHeaderV1]) -> tuple[str, ...]:
    """Source ids that contributed headers from more than one process epoch.

    One snapshot may never mix two incarnations of the same producer: a
    restarted LIO republishes sequence 0 with a fresh map, and joining that to
    the previous epoch's geometry is exactly the silent mixing §4.2 forbids.
    """

    epochs: dict[str, set[int]] = {}
    for header in headers:
        epochs.setdefault(header.source_id, set()).add(header.process_epoch)
    return tuple(sorted(name for name, seen in epochs.items() if len(seen) > 1))


def contributing_epochs(headers: Iterable[EvidenceHeaderV1]) -> tuple[tuple[str, int], ...]:
    """``(source_id, process_epoch)`` pairs, sorted — the snapshot's lineage."""

    return tuple(sorted({(header.source_id, header.process_epoch) for header in headers}))


def contributing_calibration_hashes(headers: Iterable[EvidenceHeaderV1]) -> tuple[str, ...]:
    """Sorted, de-duplicated calibration hashes behind a snapshot."""

    return tuple(sorted({header.calibration_hash for header in headers}))


__all__ = [
    "EVIDENCE_HEADER_SCHEMA_VERSION",
    "HEADER_HEALTH_REASONS",
    "PROTOTYPE_PROFILE",
    "REASON_CLOCK_MAP_UNCERTAIN",
    "REASON_MISSING_INPUT",
    "REASON_MIXED_EPOCH",
    "REASON_STALE",
    "REASON_SYNTHETIC_ORIGIN_IN_PHYSICAL_PROFILE",
    "REASON_UNCOMMISSIONED_CALIBRATION",
    "REASON_UNKNOWN_FRAME",
    "REASON_UNKNOWN_ORIGIN",
    "REASON_UNSUPPORTED_SCHEMA",
    "EvidenceHeaderV1",
    "EvidenceProfile",
    "contributing_calibration_hashes",
    "contributing_epochs",
    "header_health_reasons",
    "mixed_epoch_sources",
    "physical_profile",
]
