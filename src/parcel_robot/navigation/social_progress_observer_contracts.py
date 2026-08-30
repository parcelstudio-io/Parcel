"""Bounded value contracts for the shadow social-progress observer.

Kept separate from the observer mechanics so both leaves remain reviewable and
below Parcel's module-size ratchet.  These records contain evidence only; none
can dispatch or authorize motion.
"""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass, field, fields, is_dataclass
from enum import Enum

from parcel_robot.authority import PERSON_SOCIAL_ZONE_M
from parcel_robot.contracts.navigation_snapshot_v2 import DynamicTrackV2, NavigationSnapshotV2
from parcel_robot.navigation.social_progress import (
    MAX_PUBLIC_INTEGER,
    MAX_TRACK_ID_CHARS,
    SocialProgressConfigV1,
    SocialProgressDecisionV1,
    SocialTrackEvidenceV1,
    VisibilityEvidenceV1,
)

OBSERVER_SCHEMA_VERSION = 1
MAX_DYNAMIC_TRACKS = 64
MAX_OBSTACLE_ROWS = 64
MAX_PLANAR_SCAN_RAYS = 4096
MAX_OBSERVER_HISTORY = 128
MAX_PUBLIC_HISTORY_SUMMARIES = 16
MAX_OBSTACLE_ID_CHARS = MAX_TRACK_ID_CHARS
MAX_PUBLIC_SNAPSHOT_BYTES = 256 * 1024
# A V2 snapshot currently has five stamped contributors.  Eight leaves bounded
# schema-growth room while keeping direct sample construction absolutely sized.
MAX_SNAPSHOT_EVIDENCE_IDS = 8
MAX_SNAPSHOT_EPOCH_ROWS = 8

# The shadow observer's default corridor is one coherent geometry, not three
# independently tuned proximity literals. Its forward reach starts at the
# human-bucket social-zone authority and adds an observer-local reach margin;
# the latter preserves the swept-boundary contract while keeping the social
# distance's ownership explicit. Its angular view is then derived from that
# reach and the explicitly observer-local half-width. These remain
# uncommissioned proposal/evaluation defaults and cannot authorize motion.
DEFAULT_SOCIAL_CORRIDOR_REACH_MARGIN_M = 0.05
DEFAULT_SOCIAL_CORRIDOR_LOOKAHEAD_M = PERSON_SOCIAL_ZONE_M + DEFAULT_SOCIAL_CORRIDOR_REACH_MARGIN_M
DEFAULT_SOCIAL_CORRIDOR_HALF_WIDTH_M = 0.45
DEFAULT_SOCIAL_CORRIDOR_HALF_ANGLE_RAD = math.atan2(
    DEFAULT_SOCIAL_CORRIDOR_HALF_WIDTH_M,
    DEFAULT_SOCIAL_CORRIDOR_LOOKAHEAD_M,
)

_BAD_ROUTE_STATES = frozenset(
    {"error", "failed", "goal_blocked", "invalid", "no_path", "unavailable"}
)


def _finite(value: object, name: str, *, minimum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    if minimum is not None and result < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    return result


def _nonnegative_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    if value < 0 or value > MAX_PUBLIC_INTEGER:
        raise ValueError(f"{name} must be in [0, {MAX_PUBLIC_INTEGER}]")
    return value


def _bounded_text(value: object, name: str, *, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    if not isinstance(value, str) or not value or len(value) > 128:
        suffix = " or None" if optional else ""
        raise ValueError(f"{name} must be a non-empty string up to 128 characters{suffix}")
    return value


def _validate_snapshot_public_integers(snapshot: NavigationSnapshotV2) -> None:
    """Reject overbound snapshot values before hashing, derivation, or retention."""

    _nonnegative_int(snapshot.revision, "snapshot revision")
    _nonnegative_int(snapshot.assembled_monotonic_ns, "snapshot assembled_monotonic_ns")
    for index, header in enumerate(snapshot.headers):
        _bounded_text(header.source_id, f"snapshot header {index} source_id")
        _bounded_text(header.evidence_id, f"snapshot header {index} evidence_id")
        for name in (
            "process_epoch",
            "capture_monotonic_ns",
            "sequence",
            "max_age_ns",
            "transport_age_ns",
            "clock_map_uncertainty_ns",
            "schema_version",
        ):
            _nonnegative_int(getattr(header, name), f"snapshot header {index} {name}")


@dataclass(frozen=True, slots=True)
class VelocityPrimitiveV1:
    """A value-only body velocity, suitable for immutable observer samples."""

    vx_mps: float = 0.0
    vy_mps: float = 0.0
    wz_radps: float = 0.0
    schema_version: int = OBSERVER_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != OBSERVER_SCHEMA_VERSION or isinstance(self.schema_version, bool):
            raise ValueError(f"schema_version must equal {OBSERVER_SCHEMA_VERSION}")
        for name in ("vx_mps", "vy_mps", "wz_radps"):
            _finite(getattr(self, name), name)

    @classmethod
    def from_value(cls, value: object | None) -> VelocityPrimitiveV1:
        """Copy a command/feedback object without retaining command authority."""

        if value is None:
            return cls()
        if isinstance(value, cls):
            return value
        if hasattr(value, "vx_mps") and hasattr(value, "vy_mps"):
            vx = value.vx_mps  # type: ignore[attr-defined]
            vy = value.vy_mps  # type: ignore[attr-defined]
        elif hasattr(value, "vx") and hasattr(value, "vy"):
            vx = value.vx  # type: ignore[attr-defined]
            vy = value.vy  # type: ignore[attr-defined]
        else:
            raise TypeError("velocity value must expose vx/vy or vx_mps/vy_mps")
        if hasattr(value, "wz_radps"):
            wz = value.wz_radps  # type: ignore[attr-defined]
        elif hasattr(value, "vyaw"):
            wz = value.vyaw  # type: ignore[attr-defined]
        elif hasattr(value, "wz"):
            wz = value.wz  # type: ignore[attr-defined]
        else:
            raise TypeError("velocity value must expose wz_radps, vyaw, or wz")
        return cls(vx_mps=vx, vy_mps=vy, wz_radps=wz)

    @property
    def planar_speed_mps(self) -> float:
        return math.hypot(self.vx_mps, self.vy_mps)


@dataclass(frozen=True, slots=True)
class VelocityEvidenceV1:
    """One explicit requested/final/achieved velocity observation."""

    primitive: VelocityPrimitiveV1
    source: str
    sequence: int
    sample_monotonic_s: float
    age_s: float
    fresh: bool
    schema_version: int = OBSERVER_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != OBSERVER_SCHEMA_VERSION or isinstance(self.schema_version, bool):
            raise ValueError(f"schema_version must equal {OBSERVER_SCHEMA_VERSION}")
        if not isinstance(self.primitive, VelocityPrimitiveV1):
            raise TypeError("primitive must be VelocityPrimitiveV1")
        _bounded_text(self.source, "source")
        _nonnegative_int(self.sequence, "sequence")
        _finite(self.sample_monotonic_s, "sample_monotonic_s", minimum=0.0)
        _finite(self.age_s, "age_s", minimum=0.0)
        if not isinstance(self.fresh, bool):
            raise TypeError("fresh must be a boolean")

    @classmethod
    def from_value(
        cls,
        value: object | None,
        *,
        source: str,
        sequence: int,
        sample_monotonic_s: float,
        age_s: float = 0.0,
        fresh: bool = True,
    ) -> VelocityEvidenceV1:
        return cls(
            primitive=VelocityPrimitiveV1.from_value(value),
            source=source,
            sequence=sequence,
            sample_monotonic_s=sample_monotonic_s,
            age_s=age_s,
            fresh=fresh,
        )


@dataclass(frozen=True, slots=True)
class PlannerFactsV1:
    """The typed subset of ``DirectiveNavigator.snapshot()`` used here."""

    mission_status: str | None = None
    route_status: str | None = None
    body_is_still: bool = True
    steps_gate_blocked: int = 0
    progress_demand: bool = False
    paused: bool = False
    has_mission: bool = False
    steps_without_progress: int = 0
    terminal_verification_steps: int = 0
    schema_version: int = OBSERVER_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != OBSERVER_SCHEMA_VERSION or isinstance(self.schema_version, bool):
            raise ValueError(f"schema_version must equal {OBSERVER_SCHEMA_VERSION}")
        _bounded_text(self.mission_status, "mission_status", optional=True)
        _bounded_text(self.route_status, "route_status", optional=True)
        for name in ("body_is_still", "progress_demand", "paused", "has_mission"):
            if not isinstance(getattr(self, name), bool):
                raise TypeError(f"{name} must be a boolean")
        for name in (
            "steps_gate_blocked",
            "steps_without_progress",
            "terminal_verification_steps",
        ):
            _nonnegative_int(getattr(self, name), name)
        if self.paused and self.progress_demand:
            raise ValueError("a paused mission cannot publish progress_demand")

    @property
    def planner_healthy(self) -> bool:
        route = (self.route_status or "").strip().lower()
        mission = (self.mission_status or "").strip().lower()
        return route not in _BAD_ROUTE_STATES and mission not in {"failed", "error"}

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> PlannerFactsV1:
        if not isinstance(value, Mapping):
            raise TypeError("planner facts must be a mapping")
        allowed = {
            "mission_status",
            "route_status",
            "body_is_still",
            "steps_gate_blocked",
            "progress_demand",
            "paused",
            "has_mission",
            "steps_without_progress",
            "terminal_verification_steps",
            "schema_version",
        }
        if any(not isinstance(key, str) for key in value):
            raise TypeError("planner fact keys must be strings")
        unknown = sorted(set(value) - allowed)
        if unknown:
            raise ValueError(f"unknown planner fact keys: {unknown}")
        return cls(**dict(value))  # type: ignore[arg-type]


def _enabled_decision_config() -> SocialProgressConfigV1:
    return SocialProgressConfigV1(enabled=True)


@dataclass(frozen=True, slots=True)
class SocialProgressObserverConfigV1:
    """Strict, default-off configuration; ``shadow`` is the only mode."""

    enabled: bool = False
    mode: str = "shadow"
    history_size: int = MAX_OBSERVER_HISTORY
    missing_track_retention_s: float = 0.50
    lidar_max_age_s: float = 0.25
    max_clock_uncertainty_s: float = 0.05
    corridor_lookahead_m: float = DEFAULT_SOCIAL_CORRIDOR_LOOKAHEAD_M
    corridor_half_width_m: float = DEFAULT_SOCIAL_CORRIDOR_HALF_WIDTH_M
    corridor_half_angle_rad: float = DEFAULT_SOCIAL_CORRIDOR_HALF_ANGLE_RAD
    minimum_corridor_rays: int = 5
    max_corridor_ray_gap_rad: float = 0.10
    lidar_mark_tolerance_m: float = 0.25
    lidar_mark_angular_tolerance_rad: float = 0.10
    robot_footprint_radius_m: float | None = None
    hard_envelope_m: float = 0.45
    motion_epsilon_mps: float = 0.02
    decision_config: SocialProgressConfigV1 = field(default_factory=_enabled_decision_config)
    schema_version: int = OBSERVER_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != OBSERVER_SCHEMA_VERSION or isinstance(self.schema_version, bool):
            raise ValueError(f"schema_version must equal {OBSERVER_SCHEMA_VERSION}")
        if not isinstance(self.enabled, bool):
            raise TypeError("enabled must be a boolean")
        if self.mode != "shadow":
            raise ValueError("social progress observer mode must be 'shadow'")
        if (
            isinstance(self.history_size, bool)
            or not isinstance(self.history_size, int)
            or not 1 <= self.history_size <= MAX_OBSERVER_HISTORY
        ):
            raise ValueError(f"history_size must be an integer in [1, {MAX_OBSERVER_HISTORY}]")
        if (
            isinstance(self.minimum_corridor_rays, bool)
            or not isinstance(self.minimum_corridor_rays, int)
            or not 3 <= self.minimum_corridor_rays <= MAX_PLANAR_SCAN_RAYS
        ):
            raise ValueError(
                f"minimum_corridor_rays must be an integer in [3, {MAX_PLANAR_SCAN_RAYS}]"
            )
        for name in (
            "missing_track_retention_s",
            "lidar_max_age_s",
            "max_clock_uncertainty_s",
            "corridor_lookahead_m",
            "corridor_half_width_m",
            "corridor_half_angle_rad",
            "max_corridor_ray_gap_rad",
            "lidar_mark_tolerance_m",
            "lidar_mark_angular_tolerance_rad",
            "hard_envelope_m",
            "motion_epsilon_mps",
        ):
            if _finite(getattr(self, name), name, minimum=0.0) == 0.0:
                raise ValueError(f"{name} must be positive")
        if self.corridor_half_angle_rad >= math.pi / 2.0:
            raise ValueError("corridor_half_angle_rad must be less than pi/2")
        if self.max_corridor_ray_gap_rad >= math.pi:
            raise ValueError("max_corridor_ray_gap_rad must be less than pi")
        if self.lidar_mark_angular_tolerance_rad >= math.pi:
            raise ValueError("lidar_mark_angular_tolerance_rad must be less than pi")
        if self.robot_footprint_radius_m is not None:
            _finite(self.robot_footprint_radius_m, "robot_footprint_radius_m", minimum=0.0)
        if not isinstance(self.decision_config, SocialProgressConfigV1):
            raise TypeError("decision_config must be SocialProgressConfigV1")
        if not self.decision_config.enabled:
            raise ValueError("decision_config.enabled must be true inside an enabled shadow seam")

    @classmethod
    def from_mapping(cls, value: Mapping[str, object] | None) -> SocialProgressObserverConfigV1:
        if value is None:
            return cls()
        if not isinstance(value, Mapping):
            raise TypeError("social progress observer config must be a mapping or None")
        allowed = {
            "enabled",
            "mode",
            "history_size",
            "missing_track_retention_s",
            "lidar_max_age_s",
            "max_clock_uncertainty_s",
            "corridor_lookahead_m",
            "corridor_half_width_m",
            "corridor_half_angle_rad",
            "minimum_corridor_rays",
            "max_corridor_ray_gap_rad",
            "lidar_mark_tolerance_m",
            "lidar_mark_angular_tolerance_rad",
            "robot_footprint_radius_m",
            "hard_envelope_m",
            "motion_epsilon_mps",
            "decision",
            "schema_version",
        }
        if any(not isinstance(key, str) for key in value):
            raise TypeError("social progress observer config keys must be strings")
        unknown = sorted(set(value) - allowed)
        if unknown:
            raise ValueError(f"unknown social progress observer config keys: {unknown}")
        raw = dict(value)
        decision_raw = raw.pop("decision", None)
        if decision_raw is None:
            decision = _enabled_decision_config()
        else:
            if not isinstance(decision_raw, Mapping):
                raise TypeError("decision must be a mapping")
            if "enabled" in decision_raw and decision_raw["enabled"] is not True:
                raise ValueError("decision.enabled cannot disable an enabled shadow observer")
            decision = SocialProgressConfigV1.from_mapping({**dict(decision_raw), "enabled": True})
        return cls(decision_config=decision, **raw)  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class SocialProgressObserverSampleV1:
    """One immutable shadow result; it carries no velocity output field."""

    sample_sequence: int
    navigation_generation: int
    observed_monotonic_s: float
    snapshot_missing: bool
    snapshot_revision: int | None
    snapshot_assembled_monotonic_ns: int | None
    snapshot_evidence_ids: tuple[str, ...]
    snapshot_epochs: tuple[tuple[str, int], ...]
    requested_velocity: VelocityEvidenceV1
    final_velocity: VelocityEvidenceV1
    achieved_velocity: VelocityEvidenceV1
    planner: PlannerFactsV1
    tracks: tuple[SocialTrackEvidenceV1, ...]
    corridor_evidence: VisibilityEvidenceV1 | None
    decision: SocialProgressDecisionV1
    schema_version: int = OBSERVER_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != OBSERVER_SCHEMA_VERSION or isinstance(self.schema_version, bool):
            raise ValueError(f"schema_version must equal {OBSERVER_SCHEMA_VERSION}")
        _nonnegative_int(self.sample_sequence, "sample_sequence")
        _nonnegative_int(self.navigation_generation, "navigation_generation")
        _finite(self.observed_monotonic_s, "observed_monotonic_s", minimum=0.0)
        if not isinstance(self.snapshot_missing, bool):
            raise TypeError("snapshot_missing must be a boolean")
        if self.snapshot_missing != (self.snapshot_revision is None):
            raise ValueError("snapshot_missing and snapshot_revision disagree")
        if self.snapshot_revision is not None:
            _nonnegative_int(self.snapshot_revision, "snapshot_revision")
        if self.snapshot_assembled_monotonic_ns is not None:
            _nonnegative_int(
                self.snapshot_assembled_monotonic_ns,
                "snapshot_assembled_monotonic_ns",
            )
        if not isinstance(self.snapshot_evidence_ids, tuple):
            raise TypeError("snapshot_evidence_ids must be a tuple")
        if len(self.snapshot_evidence_ids) > MAX_SNAPSHOT_EVIDENCE_IDS:
            raise ValueError(f"snapshot_evidence_ids exceeds {MAX_SNAPSHOT_EVIDENCE_IDS} entries")
        for index, evidence_id in enumerate(self.snapshot_evidence_ids):
            _bounded_text(evidence_id, f"snapshot_evidence_ids[{index}]")
        if not isinstance(self.snapshot_epochs, tuple):
            raise TypeError("snapshot_epochs must be a tuple")
        if len(self.snapshot_epochs) > MAX_SNAPSHOT_EPOCH_ROWS:
            raise ValueError(f"snapshot_epochs exceeds {MAX_SNAPSHOT_EPOCH_ROWS} entries")
        for index, row in enumerate(self.snapshot_epochs):
            if not isinstance(row, tuple) or len(row) != 2:
                raise TypeError("snapshot_epochs rows must be (source_id, epoch) tuples")
            source_id, epoch = row
            _bounded_text(source_id, f"snapshot_epochs[{index}] source_id")
            _nonnegative_int(epoch, f"snapshot_epochs[{index}] epoch")
        for value in (self.requested_velocity, self.final_velocity, self.achieved_velocity):
            if not isinstance(value, VelocityEvidenceV1):
                raise TypeError("velocity samples must be VelocityEvidenceV1")
        if not isinstance(self.planner, PlannerFactsV1):
            raise TypeError("planner must be PlannerFactsV1")
        if not isinstance(self.tracks, tuple):
            raise TypeError("tracks must be a tuple of SocialTrackEvidenceV1")
        if len(self.tracks) > MAX_DYNAMIC_TRACKS:
            raise ValueError(f"tracks exceeds {MAX_DYNAMIC_TRACKS} entries")
        if any(not isinstance(value, SocialTrackEvidenceV1) for value in self.tracks):
            raise TypeError("tracks must be a tuple of SocialTrackEvidenceV1")
        if self.corridor_evidence is not None and not isinstance(
            self.corridor_evidence, VisibilityEvidenceV1
        ):
            raise TypeError("corridor_evidence must be VisibilityEvidenceV1 or None")
        if not isinstance(self.decision, SocialProgressDecisionV1):
            raise TypeError("decision must be SocialProgressDecisionV1")
        if self.decision.authorizes_motion:
            raise ValueError("a shadow observer decision cannot authorize motion")

    def as_dict(self) -> dict[str, object]:
        return {item.name: _plain(getattr(self, item.name)) for item in fields(self)}


@dataclass(frozen=True, slots=True)
class _RememberedTrack:
    track: DynamicTrackV2
    last_seen_monotonic_s: float
    last_snapshot_revision: int


@dataclass(frozen=True, slots=True)
class _ScanTiming:
    source_monotonic_s: float
    receive_monotonic_s: float
    effective_transport_s: float


def _plain(value: object) -> object:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value) and not isinstance(value, type):
        if hasattr(value, "as_dict"):
            return value.as_dict()  # type: ignore[no-any-return]
        return {item.name: _plain(getattr(value, item.name)) for item in fields(value)}
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, deque)):
        return [_plain(item) for item in value]
    return value


__all__ = [
    "MAX_DYNAMIC_TRACKS",
    "MAX_OBSERVER_HISTORY",
    "MAX_OBSTACLE_ID_CHARS",
    "MAX_OBSTACLE_ROWS",
    "MAX_PLANAR_SCAN_RAYS",
    "MAX_PUBLIC_HISTORY_SUMMARIES",
    "MAX_PUBLIC_SNAPSHOT_BYTES",
    "MAX_SNAPSHOT_EPOCH_ROWS",
    "MAX_SNAPSHOT_EVIDENCE_IDS",
    "OBSERVER_SCHEMA_VERSION",
    "PlannerFactsV1",
    "SocialProgressObserverConfigV1",
    "SocialProgressObserverSampleV1",
    "VelocityEvidenceV1",
    "VelocityPrimitiveV1",
]
