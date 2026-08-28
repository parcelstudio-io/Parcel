"""Simulator adapter: one carrier tick in, one stamped snapshot out.

This is the complete adapter the A4 card owes (the physical one is a typed
skeleton; see :mod:`parcel_robot.observation.sources`).  It takes anything
shaped like
:class:`~parcel_robot.contracts.observation_carrier.ObservationCarrierV1` —
which is what every simulator backend already returns — and publishes a
:class:`~parcel_robot.contracts.navigation_snapshot_v2.NavigationSnapshotV2`.

It imports **no backend**: the carrier is structural, so the same function
serves the mujoco backend, the headless city and a recorded fixture, and the
observation spine keeps its no-vendor-no-simulator import property.

Two stamping decisions are load-bearing and neither is defaulted:

* ``range_convention`` — A2 NAV-GLUE's output handoff.  A carrier may combine
  planar and analytic subchannels with different source conventions, so an
  honest mixed-source caller declares both and this adapter normalizes them
  before minting the single traversability stamp.  Legacy callers default both
  sources to their requested output convention and remain lossless.
* ``origin`` — defaults to :attr:`EvidenceOrigin.SIMULATION` because that is
  what this adapter is; the physical profile then refuses it, which is the
  point.  ``fixture_label`` carries the carrier's own ``backend`` string, the
  same label ``core.input_health.evidence_origin`` produces today.
"""

from __future__ import annotations

import math
from typing import Any

from parcel_robot.contracts.evidence_header import EvidenceHeaderV1
from parcel_robot.contracts.navigation_snapshot_v2 import (
    RANGE_CONVENTION_BASE_CENTRE,
    RANGE_CONVENTION_BODY_SURFACE,
    RANGE_CONVENTIONS,
    BaseStateV1,
    DynamicTrackV2,
    LocalizationHealthV1,
    NavigationSnapshotV2,
    ObstacleReturnV1,
    OwnerBeliefV1,
    PersonProximityV1,
    SemanticObservationV1,
    SystemHealthV1,
    TransformV1,
    TraversabilityV1,
)
from parcel_robot.contracts.observation_carrier import ObservationCarrierV1
from parcel_robot.evidence_origin import EvidenceOrigin

#: Default TTL for a simulator-sourced channel: 250 ms, the same bound the
#: reactive-safety scan requirement already enforces
#: (``navigation/reactive_safety.py`` ``max_age_s=0.25``).
DEFAULT_SIM_MAX_AGE_NS = 250_000_000

MAP_FRAME = "map"
ODOM_FRAME = "odom"
BASE_FRAME = "base_link"


def _seconds_to_ns(value: float) -> int:
    return round(float(value) * 1_000_000_000)


def _header(
    *,
    source_id: str,
    frame_id: str,
    capture_monotonic_ns: int,
    sequence: int,
    process_epoch: int,
    fixture_label: str,
    origin: EvidenceOrigin,
    max_age_ns: int,
    calibration_hash: str,
    channel: str,
) -> EvidenceHeaderV1:
    return EvidenceHeaderV1(
        source_id=source_id,
        process_epoch=process_epoch,
        capture_monotonic_ns=capture_monotonic_ns,
        sequence=sequence,
        evidence_id=f"{source_id}.{channel}.{sequence}",
        frame_id=frame_id,
        calibration_hash=calibration_hash,
        origin=origin,
        max_age_ns=max_age_ns,
        transport_age_ns=0,
        fixture_label=fixture_label,
    )


def _semantics(carrier: Any, evidence_id: str) -> tuple[SemanticObservationV1, ...]:
    """Regions and objects, each linked to the evidence id that produced it."""

    rows: list[SemanticObservationV1] = []
    for region in getattr(carrier, "semantic_regions", ()) or ():
        rows.append(
            SemanticObservationV1(
                kind="region",
                entity_id=region.region_id,
                label=region.label,
                confidence=region.confidence,
                source=region.source,
                reachable=region.reachable,
                evidence_id=evidence_id,
                polygon=tuple(region.polygon),
                metadata=region.metadata,
            )
        )
    for item in getattr(carrier, "semantic_objects", ()) or ():
        rows.append(
            SemanticObservationV1(
                kind="object",
                entity_id=item.object_id,
                label=item.label,
                confidence=item.confidence,
                source=item.source,
                reachable=item.reachable,
                evidence_id=evidence_id,
                position=tuple(item.position),
                metadata=item.metadata,
            )
        )
    return tuple(rows)


def _traversability(
    carrier: Any,
    header: EvidenceHeaderV1,
    range_convention: str,
    footprint_radius_m: float,
    planar_source_convention: str,
    analytic_source_convention: str,
) -> TraversabilityV1:
    # Establish provenance compatibility before reading even one value.  An
    # all-NaN/inf raw scan is still an unsupported RAW_SENSOR -> BODY_SURFACE
    # conversion; sentinels may be preserved only after the pair is known.
    _validate_range_conversion(planar_source_convention, range_convention)
    _validate_range_conversion(analytic_source_convention, range_convention)
    # Validate the one conversion parameter before touching any carrier row.
    # In particular, do not let NaN/inf, bool, or a negative radius participate
    # in a BODY_SURFACE -> BASE_CENTRE conversion and disappear behind the
    # output convention's required zero footprint stamp.
    if isinstance(footprint_radius_m, bool) or not isinstance(footprint_radius_m, (int, float)):
        raise TypeError("footprint_radius_m must be numeric")
    footprint_radius_m = float(footprint_radius_m)
    if not math.isfinite(footprint_radius_m) or footprint_radius_m < 0.0:
        raise ValueError("footprint_radius_m must be finite and non-negative")
    output_footprint_m = (
        footprint_radius_m if range_convention == RANGE_CONVENTION_BODY_SURFACE else 0.0
    )
    return TraversabilityV1(
        header=header,
        range_convention=range_convention,
        footprint_radius_m=output_footprint_m,
        nearest_obstacle_m=_normalize_range(
            carrier.nearest_obstacle_m,
            source_convention=analytic_source_convention,
            output_convention=range_convention,
            footprint_radius_m=footprint_radius_m,
        ),
        nearest_obstacle_bearing_rad=carrier.nearest_obstacle_bearing_rad,
        nearest_obstacle_id=carrier.nearest_obstacle_id,
        obstacles=tuple(
            ObstacleReturnV1(
                _normalize_range(
                    item.distance_m,
                    source_convention=analytic_source_convention,
                    output_convention=range_convention,
                    footprint_radius_m=footprint_radius_m,
                ),
                item.bearing_rad,
                item.obstacle_id,
            )
            for item in carrier.lidar_obstacles
        ),
        ranges=tuple(
            _normalize_range(
                item,
                source_convention=planar_source_convention,
                output_convention=range_convention,
                footprint_radius_m=footprint_radius_m,
            )
            for item in carrier.lidar_ranges
        ),
        angle_min_rad=carrier.lidar_angle_min_rad,
        angle_increment_rad=carrier.lidar_angle_increment_rad,
        range_min_m=_normalize_range(
            carrier.lidar_range_min_m,
            source_convention=planar_source_convention,
            output_convention=range_convention,
            footprint_radius_m=footprint_radius_m,
        ),
        range_max_m=_normalize_range(
            carrier.lidar_range_max_m,
            source_convention=planar_source_convention,
            output_convention=range_convention,
            footprint_radius_m=footprint_radius_m,
        ),
    )


def _normalize_range(
    value: float | None,
    *,
    source_convention: str,
    output_convention: str,
    footprint_radius_m: float,
) -> float | None:
    """Normalize one range while preserving scan sentinel values.

    The carrier can combine base-centre planar rays with body-surface analytic
    clearances.  A snapshot cannot honestly stamp that mixture as one
    convention, so each finite subchannel is converted before construction.
    NaN and infinities retain their existing ignored/no-return meanings.
    """

    _validate_range_conversion(source_convention, output_convention)
    if value is None:
        return None
    # Preserve the DTO's strict scalar boundary.  ``float(True)`` and
    # ``float("1.30")`` would otherwise turn malformed carrier data into a
    # valid-looking clearance before TraversabilityV1 can reject it.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError("range values must be numbers")
    result = float(value)
    if not math.isfinite(result) or source_convention == output_convention:
        return result
    if (
        source_convention == RANGE_CONVENTION_BASE_CENTRE
        and output_convention == RANGE_CONVENTION_BODY_SURFACE
    ):
        return max(0.0, result - footprint_radius_m)
    if (
        source_convention == RANGE_CONVENTION_BODY_SURFACE
        and output_convention == RANGE_CONVENTION_BASE_CENTRE
    ):
        return result + footprint_radius_m
    raise ValueError(
        "cannot normalize range convention without a commissioned sensor extrinsic: "
        f"{source_convention} -> {output_convention}"
    )


def _validate_range_conversion(source_convention: str, output_convention: str) -> None:
    """Refuse an unsupported convention pair independently of sample values."""

    if source_convention not in RANGE_CONVENTIONS:
        raise ValueError(f"unsupported source range_convention: {source_convention}")
    if output_convention not in RANGE_CONVENTIONS:
        raise ValueError(f"unsupported output range_convention: {output_convention}")
    if source_convention == output_convention:
        return
    if {source_convention, output_convention} == {
        RANGE_CONVENTION_BASE_CENTRE,
        RANGE_CONVENTION_BODY_SURFACE,
    }:
        return
    raise ValueError(
        "cannot normalize range convention without a commissioned sensor extrinsic: "
        f"{source_convention} -> {output_convention}"
    )


def _owner_belief(carrier: Any, header: EvidenceHeaderV1) -> OwnerBeliefV1:
    owner = carrier.owner
    return OwnerBeliefV1(
        header=header,
        owner_id=owner.owner_id,
        x=owner.x,
        y=owner.y,
        visible=owner.visible,
        confidence=owner.confidence,
        state=owner.state,
        identity_source=owner.identity_source,
        identity_margin=owner.identity_margin,
    )


def _dynamic_tracks(carrier: Any) -> tuple[DynamicTrackV2, ...]:
    return tuple(
        DynamicTrackV2(
            track_id=item.agent_id,
            class_id=item.kind,
            x=item.x,
            y=item.y,
            vx=item.vx,
            vy=item.vy,
            radius_m=item.radius_m,
            yaw_rad=item.yaw,
            confidence=item.confidence,
        )
        for item in carrier.dynamic_agents
    )


def snapshot_from_carrier(
    carrier: ObservationCarrierV1,
    *,
    range_convention: str,
    footprint_radius_m: float = 0.0,
    planar_source_convention: str | None = None,
    analytic_source_convention: str | None = None,
    capture_monotonic_ns: int | None = None,
    source_id: str = "simulator",
    process_epoch: int = 0,
    sequence: int = 0,
    revision: int = 0,
    origin: EvidenceOrigin = EvidenceOrigin.SIMULATION,
    max_age_ns: int = DEFAULT_SIM_MAX_AGE_NS,
    calibration_hash: str = "uncommissioned",
    profile_name: str = "prototype",
    localization: LocalizationHealthV1 | None = None,
) -> NavigationSnapshotV2:
    """Stamp one carrier tick as a ``NavigationSnapshotV2``.

    Every channel receives the SAME capture stamp, because a simulator tick is
    genuinely synchronous — there is no image-versus-pose skew to report.  A
    live in-process adapter may supply ``capture_monotonic_ns`` at ingress when
    the carrier's timestamp belongs to an unrelated simulator clock.  Origin
    and fixture provenance remain the carrier's.  Replay and physical sources
    stamp each channel with their own capture time instead.
    """

    planar_convention = (
        range_convention if planar_source_convention is None else planar_source_convention
    )
    analytic_convention = (
        range_convention if analytic_source_convention is None else analytic_source_convention
    )
    if capture_monotonic_ns is None:
        stamp_ns = _seconds_to_ns(carrier.timestamp)
    else:
        if isinstance(capture_monotonic_ns, bool) or not isinstance(
            capture_monotonic_ns, int
        ):
            raise TypeError("capture_monotonic_ns must be an integer")
        if capture_monotonic_ns < 0:
            raise ValueError("capture_monotonic_ns must be non-negative")
        stamp_ns = capture_monotonic_ns
    shared = {
        "source_id": source_id,
        "capture_monotonic_ns": stamp_ns,
        "sequence": sequence,
        "process_epoch": process_epoch,
        "fixture_label": str(getattr(carrier, "backend", "") or ""),
        "origin": origin,
        "max_age_ns": max_age_ns,
        "calibration_hash": calibration_hash,
    }
    pose = carrier.robot
    scan_header = _header(frame_id=BASE_FRAME, channel="scan", **shared)
    return NavigationSnapshotV2(
        map_from_odom=TransformV1(
            header=_header(frame_id=MAP_FRAME, channel="map_from_odom", **shared),
            parent_frame=MAP_FRAME,
            child_frame=ODOM_FRAME,
        ),
        odom_from_base=TransformV1(
            header=_header(frame_id=ODOM_FRAME, channel="odom_from_base", **shared),
            parent_frame=ODOM_FRAME,
            child_frame=BASE_FRAME,
            x=pose.x,
            y=pose.y,
            z=pose.z,
            yaw_rad=pose.yaw,
        ),
        localization=localization if localization is not None else LocalizationHealthV1(),
        base=BaseStateV1(header=_header(frame_id=BASE_FRAME, channel="base", **shared)),
        traversability=_traversability(
            carrier,
            scan_header,
            range_convention,
            footprint_radius_m,
            planar_convention,
            analytic_convention,
        ),
        owner=_owner_belief(carrier, _header(frame_id=MAP_FRAME, channel="owner", **shared)),
        health=SystemHealthV1(
            collision=carrier.collision,
            emergency_stopped=carrier.emergency_stopped,
        ),
        dynamic_tracks=_dynamic_tracks(carrier),
        person_proximity=PersonProximityV1(
            distance_m=carrier.nearest_person_m,
            bearing_rad=carrier.nearest_person_bearing_rad,
            person_id=carrier.nearest_person_id,
            time_to_collision_s=carrier.nearest_person_ttc_s,
        ),
        semantics=_semantics(carrier, scan_header.evidence_id),
        assembled_monotonic_ns=stamp_ns,
        revision=revision,
        profile_name=profile_name,
    )


__all__ = [
    "BASE_FRAME",
    "DEFAULT_SIM_MAX_AGE_NS",
    "MAP_FRAME",
    "ODOM_FRAME",
    "snapshot_from_carrier",
]
