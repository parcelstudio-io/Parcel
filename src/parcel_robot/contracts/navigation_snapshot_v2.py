"""``NavigationSnapshotV2`` — one immutable, stamped view of the body's world.

HLD ``research/20260824/PORTABLE_LIVING_DOG_HLD.md`` §4.2 is binding: one
snapshot replaces ``SimObservation`` and every authority-bearing ``extras``
side channel.  Navigation, Follow, reactive safety and the executive read this
and nothing else once the cutover lands; until then the simulator adapter
publishes one per tick alongside the legacy carrier.

Two properties are worth stating before the field list.

**Every geometric channel carries its own :class:`EvidenceHeaderV1`.**  A
snapshot is not "fresh" or "stale" as a whole — the pose can be 4 ms old while
the scan is 300 ms old, and the assembler
(:mod:`parcel_robot.observation.assembler`) is what decides whether that
combination may authorize translation.  Mixing a fresh image with an old pose
is the failure §4.2 names explicitly, and it is only detectable because each
channel is stamped separately.

**The range convention is stamped BY THE SOURCE.**  A2 NAV-GLUE measured the
cost of leaving it implicit: ``mujoco_lidar`` and the Go2 band seam publish
footprint-subtracted clearance, the BARN adapter publishes raw cluster ranges,
and the planner inflates from the body centre — three conventions, one field
name, and a 0.29 m disagreement that surfaced as a stalled corridor
(``scrum/20260824/task_2/A2_STATUS.md``, "One moved row NOT re-pinned").
``TraversabilityV1.range_convention`` is therefore required, not defaulted:
a producer must say which of the three it publishes.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, fields, is_dataclass
from enum import Enum
from types import MappingProxyType

from parcel_robot.contracts.evidence_header import (
    EvidenceHeaderV1,
    contributing_calibration_hashes,
    contributing_epochs,
)

NAVIGATION_SNAPSHOT_SCHEMA_VERSION = 2

# --------------------------------------------------------------------------
# range conventions — A2 NAV-GLUE's handoff
# --------------------------------------------------------------------------
#: The producer already subtracted the body footprint: the number is clearance
#: from the robot's SURFACE to the obstacle's surface.  This is what
#: ``simulation/mujoco_lidar.py`` and the Go2 band seam actually publish.
RANGE_CONVENTION_BODY_SURFACE = "body_surface_to_obstacle_surface"
#: Range measured from the body CENTRE — what ``authority.CLEARANCE_CONVENTION``
#: declares and what the planner's inflation assumes.
RANGE_CONVENTION_BASE_CENTRE = "base_center_to_obstacle_surface"
#: Raw sensor range with nothing subtracted — the BARN adapter's convention.
RANGE_CONVENTION_RAW_SENSOR = "raw_sensor_range"

RANGE_CONVENTIONS: frozenset[str] = frozenset(
    {
        RANGE_CONVENTION_BODY_SURFACE,
        RANGE_CONVENTION_BASE_CENTRE,
        RANGE_CONVENTION_RAW_SENSOR,
    }
)

#: Localization health vocabulary, matching ``parcel_robot.pose.PoseHealth``.
LOCALIZATION_HEALTH_STATES: frozenset[str] = frozenset({"healthy", "degraded", "lost"})


def _number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite")
    return number


def _optional_number(value: object, name: str) -> float | None:
    return None if value is None else _number(value, name)


def _scalar(value: object, name: str) -> float:
    """A number that MAY be non-finite.

    The planar-scan contract uses ``NaN`` for an ignored ray and ``range_max``
    — sometimes ``inf`` — for "no return".  Rejecting those here would make the
    snapshot unable to carry a scan the product already publishes, so range
    channels validate type only and leave the sentinel meaning to the reader.
    """

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a number")
    return float(value)


def _optional_scalar(value: object, name: str) -> float | None:
    return None if value is None else _scalar(value, name)


def _header(value: object, name: str) -> EvidenceHeaderV1:
    if not isinstance(value, EvidenceHeaderV1):
        raise TypeError(f"{name} must carry an EvidenceHeaderV1 — unstamped evidence is refused")
    return value


def _strings(value: object, name: str) -> tuple[str, ...]:
    if isinstance(value, str) or not isinstance(value, Iterable):
        raise TypeError(f"{name} must be a sequence of strings")
    rows = tuple(value)
    for item in rows:
        if not isinstance(item, str):
            raise TypeError(f"{name} entries must be strings")
    return rows


@dataclass(frozen=True, slots=True)
class TransformV1:
    """One stamped rigid transform, ``parent_frame`` → ``child_frame`` (SE(2)+z)."""

    header: EvidenceHeaderV1
    parent_frame: str
    child_frame: str
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    yaw_rad: float = 0.0
    covariance: tuple[float, ...] = ()

    def __post_init__(self) -> None:
        _header(self.header, "transform header")
        for name in ("parent_frame", "child_frame"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name):
                raise ValueError(f"{name} must be a non-empty string")
        for name in ("x", "y", "z", "yaw_rad"):
            _number(getattr(self, name), name)
        if not isinstance(self.covariance, tuple):
            raise TypeError("transform covariance must be a tuple")
        for item in self.covariance:
            _number(item, "transform covariance entry")

    def as_tuple(self) -> tuple[float, float, float]:
        """The SE(2) triple the localization package speaks."""

        return (self.x, self.y, self.yaw_rad)


@dataclass(frozen=True, slots=True)
class LocalizationHealthV1:
    """What the localizer says about itself — never inferred by a consumer.

    ``motion_latched`` is A3's discontinuity latch (``localization/
    discontinuity.py``): once a jump, a boot-epoch change or an ambiguous
    whole-map match latches it, translation is refused until a journalled
    re-arm, no matter what ``health`` says.  NAV-CORE refuter 4b measured what
    trusting ``health`` alone costs: 824/840 HEALTHY ticks after a kidnap.
    """

    health: str = "healthy"
    jump_m: float = 0.0
    motion_latched: bool = False
    relocalization_margin: float | None = None
    covariance: tuple[float, ...] = ()
    reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.health not in LOCALIZATION_HEALTH_STATES:
            raise ValueError(
                f"localization health must be one of {sorted(LOCALIZATION_HEALTH_STATES)}"
            )
        _number(self.jump_m, "jump_m")
        if not isinstance(self.motion_latched, bool):
            raise TypeError("motion_latched must be a boolean")
        _optional_number(self.relocalization_margin, "relocalization_margin")
        if not isinstance(self.covariance, tuple):
            raise TypeError("localization covariance must be a tuple")
        for item in self.covariance:
            _number(item, "localization covariance entry")
        object.__setattr__(self, "reasons", _strings(self.reasons, "localization reasons"))


@dataclass(frozen=True, slots=True)
class BaseStateV1:
    """Body twist, contact and controller feedback plus the capability state."""

    header: EvidenceHeaderV1
    vx_mps: float = 0.0
    vy_mps: float = 0.0
    wz_radps: float = 0.0
    feet_in_contact: int = 0
    controller_state: str = ""
    capabilities: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _header(self.header, "base state header")
        for name in ("vx_mps", "vy_mps", "wz_radps"):
            _number(getattr(self, name), name)
        if isinstance(self.feet_in_contact, bool) or not isinstance(self.feet_in_contact, int):
            raise TypeError("feet_in_contact must be an integer")
        if self.feet_in_contact < 0:
            raise ValueError("feet_in_contact must be non-negative")
        if not isinstance(self.controller_state, str):
            raise TypeError("controller_state must be a string")
        object.__setattr__(self, "capabilities", _strings(self.capabilities, "capabilities"))


@dataclass(frozen=True, slots=True)
class ObstacleReturnV1:
    """One bounded polar obstacle return, in the traversability's convention."""

    distance_m: float
    bearing_rad: float
    obstacle_id: str | None = None

    def __post_init__(self) -> None:
        _scalar(self.distance_m, "obstacle distance_m")
        _scalar(self.bearing_rad, "obstacle bearing_rad")
        if self.obstacle_id is not None and not isinstance(self.obstacle_id, str):
            raise TypeError("obstacle_id must be a string or None")


@dataclass(frozen=True, slots=True)
class TraversabilityV1:
    """Local geometry, with the convention its producer measured it in.

    ``range_convention`` has no default on purpose (A2's handoff): a source
    that will not say what its metres mean cannot publish geometry.
    ``footprint_radius_m`` is what the producer already subtracted — zero for
    a raw or centre-frame source — so a consumer can convert instead of guess.
    """

    header: EvidenceHeaderV1
    range_convention: str
    footprint_radius_m: float = 0.0
    nearest_obstacle_m: float | None = None
    nearest_obstacle_bearing_rad: float | None = None
    nearest_obstacle_id: str | None = None
    obstacles: tuple[ObstacleReturnV1, ...] = ()
    ranges: tuple[float, ...] = ()
    angle_min_rad: float | None = None
    angle_increment_rad: float | None = None
    range_min_m: float | None = None
    range_max_m: float | None = None

    def __post_init__(self) -> None:
        _header(self.header, "traversability header")
        if self.range_convention not in RANGE_CONVENTIONS:
            raise ValueError(
                "range_convention must be stamped by the source; "
                f"expected one of {sorted(RANGE_CONVENTIONS)}"
            )
        _number(self.footprint_radius_m, "footprint_radius_m")
        if self.footprint_radius_m < 0.0:
            raise ValueError("footprint_radius_m must be non-negative")
        if self.range_convention != RANGE_CONVENTION_BODY_SURFACE and self.footprint_radius_m:
            raise ValueError(
                "footprint_radius_m is only meaningful when the source subtracted a footprint"
            )
        for name in (
            "nearest_obstacle_m",
            "nearest_obstacle_bearing_rad",
            "angle_min_rad",
            "angle_increment_rad",
            "range_min_m",
            "range_max_m",
        ):
            _optional_scalar(getattr(self, name), name)
        if self.nearest_obstacle_id is not None and not isinstance(self.nearest_obstacle_id, str):
            raise TypeError("nearest_obstacle_id must be a string or None")
        if not isinstance(self.obstacles, tuple):
            raise TypeError("obstacles must be a tuple")
        for item in self.obstacles:
            if not isinstance(item, ObstacleReturnV1):
                raise TypeError("obstacles must contain ObstacleReturnV1")
        if not isinstance(self.ranges, tuple):
            raise TypeError("ranges must be a tuple")
        for item in self.ranges:
            if isinstance(item, bool) or not isinstance(item, (int, float)):
                raise TypeError("range entries must be numbers")

    @property
    def scan_present(self) -> bool:
        """True when any commissioned scan channel carried a sample this tick."""

        return bool(self.obstacles) or self.nearest_obstacle_m is not None or bool(self.ranges)


@dataclass(frozen=True, slots=True)
class DynamicTrackV2:
    """One tracked mover with velocity, extent and identity class."""

    track_id: str
    class_id: str
    x: float
    y: float
    vx: float = 0.0
    vy: float = 0.0
    radius_m: float = 0.0
    yaw_rad: float = 0.0
    confidence: float = 1.0
    covariance: tuple[float, ...] = ()

    def __post_init__(self) -> None:
        for name in ("track_id", "class_id"):
            if not isinstance(getattr(self, name), str):
                raise TypeError(f"{name} must be a string")
        for name in ("x", "y", "vx", "vy", "radius_m", "yaw_rad", "confidence"):
            _number(getattr(self, name), name)
        if not isinstance(self.covariance, tuple):
            raise TypeError("track covariance must be a tuple")


@dataclass(frozen=True, slots=True)
class PersonProximityV1:
    """The people-clearance channel: nearest person, bearing, id and TTC."""

    distance_m: float | None = None
    bearing_rad: float | None = None
    person_id: str | None = None
    time_to_collision_s: float | None = None

    def __post_init__(self) -> None:
        for name in ("distance_m", "bearing_rad", "time_to_collision_s"):
            _optional_number(getattr(self, name), name)
        if self.person_id is not None and not isinstance(self.person_id, str):
            raise TypeError("person_id must be a string or None")


@dataclass(frozen=True, slots=True)
class OwnerBeliefV1:
    """Owner belief with its ambiguity and loss evidence — never a pixel side channel.

    ``ambiguous``/``lost`` are the two states Follow must branch on (HLD Gate 6:
    ambiguity or loss ⇒ HOLD + canned line).  They are DERIVED from the
    producer's own ``state`` here rather than from a confidence threshold,
    because card OT-2 measured that thresholding the float is what let a
    ground-truth 1.0 and an uncalibrated cosine 0.97 mean the same thing.
    """

    header: EvidenceHeaderV1
    owner_id: str = "owner-1"
    x: float = 0.0
    y: float = 0.0
    visible: bool = False
    confidence: float = 0.0
    state: str = ""
    identity_source: str = ""
    identity_margin: float = 0.0
    ambiguity_reason: str = ""
    last_confirmed_monotonic_ns: int = 0

    def __post_init__(self) -> None:
        _header(self.header, "owner belief header")
        for name in ("owner_id", "state", "identity_source", "ambiguity_reason"):
            if not isinstance(getattr(self, name), str):
                raise TypeError(f"owner {name} must be a string")
        for name in ("x", "y", "confidence", "identity_margin"):
            _number(getattr(self, name), name)
        if not isinstance(self.visible, bool):
            raise TypeError("owner visible must be a boolean")
        if isinstance(self.last_confirmed_monotonic_ns, bool) or not isinstance(
            self.last_confirmed_monotonic_ns, int
        ):
            raise TypeError("last_confirmed_monotonic_ns must be an integer")

    @property
    def ambiguous(self) -> bool:
        return self.state == "ambiguous"

    @property
    def lost(self) -> bool:
        return self.state == "lost" or (not self.visible and self.state in {"", "searching"})


@dataclass(frozen=True, slots=True)
class SemanticObservationV1:
    """A place or object observation, linked to the evidence that produced it."""

    kind: str
    entity_id: str
    label: str
    confidence: float = 0.0
    source: str = "perception"
    reachable: bool = True
    evidence_id: str = ""
    polygon: tuple[tuple[float, float], ...] = ()
    position: tuple[float, float, float] | None = None
    metadata: Mapping[str, object] | None = None

    def __post_init__(self) -> None:
        if self.kind not in {"region", "object"}:
            raise ValueError("semantic observation kind must be 'region' or 'object'")
        for name in ("entity_id", "label", "source", "evidence_id"):
            if not isinstance(getattr(self, name), str):
                raise TypeError(f"semantic {name} must be a string")
        _number(self.confidence, "semantic confidence")
        if not isinstance(self.reachable, bool):
            raise TypeError("semantic reachable must be a boolean")
        if not isinstance(self.polygon, tuple):
            raise TypeError("semantic polygon must be a tuple")
        if self.position is not None:
            if not isinstance(self.position, tuple) or len(self.position) != 3:
                raise ValueError("semantic position must be a 3-tuple or None")
            for item in self.position:
                _number(item, "semantic position component")
        if self.metadata is not None:
            if not isinstance(self.metadata, Mapping):
                raise TypeError("semantic metadata must be a mapping or None")
            object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True, slots=True)
class SystemHealthV1:
    """Battery, thermal, link and input health plus the active safety reasons."""

    battery_fraction: float | None = None
    thermal_c: float | None = None
    link_ok: bool = True
    input_health_action: str = "allow"
    collision: bool = False
    emergency_stopped: bool = False
    active_safety_reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _optional_number(self.battery_fraction, "battery_fraction")
        _optional_number(self.thermal_c, "thermal_c")
        for name in ("link_ok", "collision", "emergency_stopped"):
            if not isinstance(getattr(self, name), bool):
                raise TypeError(f"{name} must be a boolean")
        if not isinstance(self.input_health_action, str):
            raise TypeError("input_health_action must be a string")
        object.__setattr__(
            self,
            "active_safety_reasons",
            _strings(self.active_safety_reasons, "active_safety_reasons"),
        )


@dataclass(frozen=True, slots=True)
class NavigationSnapshotV2:
    """One tick of the world, assembled and stamped — the observation boundary.

    ``health_reasons`` is empty only when every contributing channel passed the
    assembler's checks.  A non-empty tuple is a refusal a consumer must honour:
    the snapshot still carries whatever geometry arrived (so a HOLD can be
    narrated), but ``translation_allowed`` is False and no consumer may treat
    the geometry as an authorization.
    """

    map_from_odom: TransformV1
    odom_from_base: TransformV1
    localization: LocalizationHealthV1
    base: BaseStateV1
    traversability: TraversabilityV1
    owner: OwnerBeliefV1
    health: SystemHealthV1
    dynamic_tracks: tuple[DynamicTrackV2, ...] = ()
    person_proximity: PersonProximityV1 = field(default_factory=PersonProximityV1)
    semantics: tuple[SemanticObservationV1, ...] = ()
    assembled_monotonic_ns: int = 0
    revision: int = 0
    profile_name: str = "prototype"
    missing_inputs: tuple[str, ...] = ()
    health_reasons: tuple[str, ...] = ()
    schema_version: int = NAVIGATION_SNAPSHOT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for name, kind in (
            ("map_from_odom", TransformV1),
            ("odom_from_base", TransformV1),
            ("localization", LocalizationHealthV1),
            ("base", BaseStateV1),
            ("traversability", TraversabilityV1),
            ("owner", OwnerBeliefV1),
            ("health", SystemHealthV1),
            ("person_proximity", PersonProximityV1),
        ):
            if not isinstance(getattr(self, name), kind):
                raise TypeError(f"{name} must be a {kind.__name__}")
        if not isinstance(self.dynamic_tracks, tuple):
            raise TypeError("dynamic_tracks must be a tuple")
        for track in self.dynamic_tracks:
            if not isinstance(track, DynamicTrackV2):
                raise TypeError("dynamic_tracks must contain DynamicTrackV2")
        if not isinstance(self.semantics, tuple):
            raise TypeError("semantics must be a tuple")
        for item in self.semantics:
            if not isinstance(item, SemanticObservationV1):
                raise TypeError("semantics must contain SemanticObservationV1")
        for name in ("assembled_monotonic_ns", "revision", "schema_version"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if not isinstance(self.profile_name, str) or not self.profile_name:
            raise ValueError("profile_name must be a non-empty string")
        object.__setattr__(self, "missing_inputs", _strings(self.missing_inputs, "missing_inputs"))
        object.__setattr__(self, "health_reasons", _strings(self.health_reasons, "health_reasons"))

    @property
    def headers(self) -> tuple[EvidenceHeaderV1, ...]:
        """Every contributing header, in a stable order."""

        return (
            self.map_from_odom.header,
            self.odom_from_base.header,
            self.base.header,
            self.traversability.header,
            self.owner.header,
        )

    @property
    def contributing_epochs(self) -> tuple[tuple[str, int], ...]:
        return contributing_epochs(self.headers)

    @property
    def calibration_hashes(self) -> tuple[str, ...]:
        return contributing_calibration_hashes(self.headers)

    @property
    def translation_allowed(self) -> bool:
        """False whenever the assembler recorded any refusal reason.

        This is a gate, never a permission: a caller that wants to translate
        must ALSO clear the reactive-safety envelope and the latch.  Nothing
        here moves what ``apply_reactive_safety`` enforces.
        """

        return not self.health_reasons and not self.localization.motion_latched

    @property
    def base_in_map(self) -> tuple[float, float, float]:
        """BASE composed into MAP: ``map_from_odom * odom_from_base``."""

        mx, my, myaw = self.map_from_odom.as_tuple()
        ox, oy, oyaw = self.odom_from_base.as_tuple()
        cos_yaw, sin_yaw = math.cos(myaw), math.sin(myaw)
        return (mx + cos_yaw * ox - sin_yaw * oy, my + sin_yaw * ox + cos_yaw * oy, myaw + oyaw)

    def as_dict(self) -> dict[str, object]:
        """A plain JSON-ready mapping — for journals and diagnostics, not the wire."""

        return {name: _plain(getattr(self, name)) for name in _field_names(self)}


def _field_names(record: object) -> tuple[str, ...]:
    return tuple(item.name for item in fields(record))  # type: ignore[arg-type]


def _plain(value: object) -> object:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value) and not isinstance(value, type):
        if hasattr(value, "as_dict"):
            return value.as_dict()
        return {name: _plain(getattr(value, name)) for name in _field_names(value)}
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


__all__ = [
    "LOCALIZATION_HEALTH_STATES",
    "NAVIGATION_SNAPSHOT_SCHEMA_VERSION",
    "RANGE_CONVENTIONS",
    "RANGE_CONVENTION_BASE_CENTRE",
    "RANGE_CONVENTION_BODY_SURFACE",
    "RANGE_CONVENTION_RAW_SENSOR",
    "BaseStateV1",
    "DynamicTrackV2",
    "LocalizationHealthV1",
    "NavigationSnapshotV2",
    "ObstacleReturnV1",
    "OwnerBeliefV1",
    "PersonProximityV1",
    "SemanticObservationV1",
    "SystemHealthV1",
    "TransformV1",
    "TraversabilityV1",
]
