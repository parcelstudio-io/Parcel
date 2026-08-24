"""Project a ``NavigationSnapshotV2`` back onto the simulator-shaped carrier.

This is the migration shim, and it is temporary by design.  The nine modules
the EMBODIMENT-KERNEL audit found coupled to ``SimObservation`` each gained a
snapshot-consuming entry point in card A4; those entry points accept a real
``NavigationSnapshotV2`` and re-project it here rather than reading V2 fields
natively, because rewriting the internals of ``follow.py`` (14 signatures),
``spatial.py`` (14) and ``search_owner.py`` (13) in the same card that
introduces the contract would have shipped an unreviewable diff.

What that buys, precisely: the snapshot is the thing that crosses the seam
today, so an adapter — simulator, replay or physical — is already the only
producer, and the cutover that follows is a per-module rewrite with a green
round-trip test behind it, not another boundary change.  What it does NOT
buy: these modules do not yet *understand* V2's stamped headers.  The one
place where that mattered for safety — reactive safety's evidence stamping —
reads the header natively instead (``scan_evidence_from_snapshot``).

The view classes are this package's own frozen records, not the backend's, so
the observation spine imports no backend.  Equivalence with the carrier is
therefore field-by-field (``tests/test_a4_spine.py``), which names the
offending field on a divergence instead of failing one opaque ``==``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from parcel_robot.contracts.navigation_snapshot_v2 import NavigationSnapshotV2


@dataclass(frozen=True, slots=True)
class ViewPose:
    """``RobotPose``-shaped view of ``odom_from_base``."""

    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    yaw: float = 0.0


@dataclass(frozen=True, slots=True)
class ViewOwnerTrack:
    """``OwnerTrack``-shaped view of :class:`OwnerBeliefV1`."""

    owner_id: str = "owner-1"
    x: float = 0.0
    y: float = 0.0
    visible: bool = False
    confidence: float = 0.0
    state: str = ""
    identity_source: str = ""
    identity_margin: float = 0.0


@dataclass(frozen=True, slots=True)
class ViewObstacle:
    """``LidarObstacle``-shaped view of :class:`ObstacleReturnV1`."""

    distance_m: float
    bearing_rad: float
    obstacle_id: str | None = None


@dataclass(frozen=True, slots=True)
class ViewDynamicAgent:
    """``DynamicAgentTrack``-shaped view of :class:`DynamicTrackV2`."""

    agent_id: str
    kind: str
    x: float
    y: float
    vx: float
    vy: float
    radius_m: float
    yaw: float = 0.0
    confidence: float = 1.0


@dataclass(frozen=True, slots=True)
class ViewSemanticRegion:
    """``SemanticRegionTrack``-shaped view of a ``kind="region"`` observation."""

    region_id: str
    label: str
    polygon: tuple[tuple[float, float], ...]
    confidence: float
    source: str = "perception"
    reachable: bool = True
    metadata: Mapping[str, object] | None = None


@dataclass(frozen=True, slots=True)
class ViewSemanticObject:
    """``SemanticObjectTrack``-shaped view of a ``kind="object"`` observation."""

    object_id: str
    label: str
    position: tuple[float, float, float]
    confidence: float
    source: str = "perception"
    reachable: bool = True
    metadata: Mapping[str, object] | None = None


@dataclass(frozen=True, slots=True)
class SnapshotCarrierView:
    """A ``NavigationSnapshotV2`` wearing the carrier's field names.

    Satisfies :class:`~parcel_robot.contracts.observation_carrier.ObservationCarrierV1`
    structurally.  ``snapshot`` is kept so a consumer that HAS migrated can
    reach the stamped truth without a second lookup.
    """

    snapshot: NavigationSnapshotV2
    timestamp: float
    robot: ViewPose
    owner: ViewOwnerTrack
    nearest_obstacle_m: float | None
    nearest_obstacle_bearing_rad: float | None
    nearest_obstacle_id: str | None
    lidar_obstacles: tuple[ViewObstacle, ...]
    nearest_person_m: float | None
    nearest_person_bearing_rad: float | None
    nearest_person_id: str | None
    nearest_person_ttc_s: float | None
    dynamic_agents: tuple[ViewDynamicAgent, ...]
    semantic_regions: tuple[ViewSemanticRegion, ...]
    collision: bool
    emergency_stopped: bool
    backend: str
    semantic_objects: tuple[ViewSemanticObject, ...]
    lidar_ranges: tuple[float, ...]
    lidar_angle_min_rad: float | None
    lidar_angle_increment_rad: float | None
    lidar_range_min_m: float | None
    lidar_range_max_m: float | None


def carrier_view(snapshot: NavigationSnapshotV2) -> SnapshotCarrierView:
    """Re-project ``snapshot`` onto the carrier field names, losslessly.

    The pose read is ``base_in_map``: MAP composed from ODOM, which is the
    frame the carrier's ``robot`` field always meant.  For a simulator adapter
    ``map_from_odom`` is identity, so this is bit-identical to the carrier's
    own pose; for a real localizer it is the corrected pose, which is exactly
    the upgrade the seam exists to deliver.
    """

    if not isinstance(snapshot, NavigationSnapshotV2):
        raise TypeError("carrier_view requires a NavigationSnapshotV2")
    traversability = snapshot.traversability
    owner = snapshot.owner
    person = snapshot.person_proximity
    x, y, yaw = snapshot.base_in_map
    regions = tuple(
        ViewSemanticRegion(
            region_id=item.entity_id,
            label=item.label,
            polygon=item.polygon,
            confidence=item.confidence,
            source=item.source,
            reachable=item.reachable,
            metadata=item.metadata,
        )
        for item in snapshot.semantics
        if item.kind == "region"
    )
    objects = tuple(
        ViewSemanticObject(
            object_id=item.entity_id,
            label=item.label,
            position=item.position or (0.0, 0.0, 0.0),
            confidence=item.confidence,
            source=item.source,
            reachable=item.reachable,
            metadata=item.metadata,
        )
        for item in snapshot.semantics
        if item.kind == "object"
    )
    return SnapshotCarrierView(
        snapshot=snapshot,
        timestamp=snapshot.odom_from_base.header.capture_monotonic_ns / 1e9,
        robot=ViewPose(x=x, y=y, z=snapshot.odom_from_base.z, yaw=yaw),
        owner=ViewOwnerTrack(
            owner_id=owner.owner_id,
            x=owner.x,
            y=owner.y,
            visible=owner.visible,
            confidence=owner.confidence,
            state=owner.state,
            identity_source=owner.identity_source,
            identity_margin=owner.identity_margin,
        ),
        nearest_obstacle_m=traversability.nearest_obstacle_m,
        nearest_obstacle_bearing_rad=traversability.nearest_obstacle_bearing_rad,
        nearest_obstacle_id=traversability.nearest_obstacle_id,
        lidar_obstacles=tuple(
            ViewObstacle(item.distance_m, item.bearing_rad, item.obstacle_id)
            for item in traversability.obstacles
        ),
        nearest_person_m=person.distance_m,
        nearest_person_bearing_rad=person.bearing_rad,
        nearest_person_id=person.person_id,
        nearest_person_ttc_s=person.time_to_collision_s,
        dynamic_agents=tuple(
            ViewDynamicAgent(
                agent_id=item.track_id,
                kind=item.class_id,
                x=item.x,
                y=item.y,
                vx=item.vx,
                vy=item.vy,
                radius_m=item.radius_m,
                yaw=item.yaw_rad,
                confidence=item.confidence,
            )
            for item in snapshot.dynamic_tracks
        ),
        semantic_regions=regions,
        collision=snapshot.health.collision,
        emergency_stopped=snapshot.health.emergency_stopped,
        backend=snapshot.traversability.header.fixture_label,
        semantic_objects=objects,
        lidar_ranges=traversability.ranges,
        lidar_angle_min_rad=traversability.angle_min_rad,
        lidar_angle_increment_rad=traversability.angle_increment_rad,
        lidar_range_min_m=traversability.range_min_m,
        lidar_range_max_m=traversability.range_max_m,
    )


__all__ = [
    "SnapshotCarrierView",
    "ViewDynamicAgent",
    "ViewObstacle",
    "ViewOwnerTrack",
    "ViewPose",
    "ViewSemanticObject",
    "ViewSemanticRegion",
    "carrier_view",
]
