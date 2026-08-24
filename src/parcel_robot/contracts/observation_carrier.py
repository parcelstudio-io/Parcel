"""``ObservationCarrierV1`` — the simulator-shaped carrier, named at last.

This Protocol exists for exactly one reason: to let the nine modules the
EMBODIMENT-KERNEL audit found coupled to ``backends.base.SimObservation``
(``research/20260824/embodiment-kernel-portability/RESULTS.md``, row K3) stop
importing a **backend** type while their behaviour stays byte-identical.  It
is a transitional port, and it says so:

* :class:`~parcel_robot.contracts.navigation_snapshot_v2.NavigationSnapshotV2`
  is the destination.  Every module that annotates against this Protocol also
  has a snapshot-consuming entry point, and the carrier annotation dies at
  cutover (HLD Gate 4).
* **Provenance authority is unchanged.**  ``core/input_health.evidence_origin``
  stamps every sample reaching it ``EvidenceOrigin.SIMULATION`` by
  construction (board decision D-1: the carrier type is the authority, not a
  producer's name).  That argument previously rested on the annotation reading
  ``SimObservation``; it now rests on this Protocol being *defined* as the
  simulator carrier.  A physical producer does not satisfy it by supplying the
  attributes — it publishes a ``NavigationSnapshotV2`` whose
  ``EvidenceHeaderV1`` declares :attr:`EvidenceOrigin.PHYSICAL`, and the
  snapshot path stamps from that header instead of from a backend string.

The Protocol is deliberately **not** ``runtime_checkable``: nothing in the
product may branch on whether an object "is" a carrier.  It is an annotation,
and the only structural check that matters is the one the health join already
performs on the evidence it is handed.
"""

from __future__ import annotations

from typing import Any, Protocol


class CarrierPose(Protocol):
    """The body pose the carrier publishes (``backends.base.RobotPose``)."""

    x: float
    y: float
    z: float
    yaw: float


class CarrierOwnerTrack(Protocol):
    """The owner track the carrier publishes (``backends.base.OwnerTrack``)."""

    owner_id: str
    x: float
    y: float
    visible: bool
    confidence: float
    state: str
    identity_source: str
    identity_margin: float


class ObservationCarrierV1(Protocol):
    """One simulator-shaped observation tick.

    The field list is the full ``SimObservation`` surface, in declaration
    order, because that is what the nine migrated modules read.  ``backend`` is
    the fixture LABEL, never an authority: see the module docstring.
    """

    timestamp: float
    robot: CarrierPose
    owner: CarrierOwnerTrack
    nearest_obstacle_m: float | None
    nearest_obstacle_bearing_rad: float | None
    nearest_obstacle_id: str | None
    lidar_obstacles: tuple[Any, ...]
    nearest_person_m: float | None
    nearest_person_bearing_rad: float | None
    nearest_person_id: str | None
    nearest_person_ttc_s: float | None
    dynamic_agents: tuple[Any, ...]
    semantic_regions: tuple[Any, ...]
    collision: bool
    emergency_stopped: bool
    backend: str
    semantic_objects: tuple[Any, ...]
    lidar_ranges: tuple[float, ...]
    lidar_angle_min_rad: float | None
    lidar_angle_increment_rad: float | None
    lidar_range_min_m: float | None
    lidar_range_max_m: float | None


__all__ = ["CarrierOwnerTrack", "CarrierPose", "ObservationCarrierV1"]
