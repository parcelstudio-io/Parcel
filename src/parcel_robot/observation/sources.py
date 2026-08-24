"""The three observation sources: simulator, replay, and the physical skeleton.

One Protocol, three implementations at three honesty tiers — which is the
point of the tier being declared rather than inferred:

* :class:`CarrierObservationSource` — **complete**.  Wraps any callable that
  returns a carrier-shaped observation (every simulator backend's ``observe``)
  and publishes a stamped snapshot with ``EvidenceOrigin.SIMULATION``.
* :class:`ReplayObservationSource` — **complete** for recorded snapshots.  It
  re-stamps every header ``EvidenceOrigin.REPLAY``, so a recording can never
  be mistaken for live evidence no matter what it was when it was captured.
* :class:`PhysicalObservationSource` — **a typed skeleton, and it says so.**
  It refuses to produce anything until a sensor hub, a localizer and a
  calibration manifest are supplied, and it will not fall back to a truth
  pose (HLD Gate 2: "reject truth pose, unknown calibration and mixed
  simulation origin in the physical profile").  A skeleton that returned
  plausible zeros would be worse than one that refuses.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import replace
from typing import Any, Protocol, runtime_checkable

from parcel_robot.contracts.navigation_snapshot_v2 import NavigationSnapshotV2
from parcel_robot.evidence_origin import EvidenceOrigin
from parcel_robot.observation.simulator_adapter import snapshot_from_carrier


@runtime_checkable
class ObservationSource(Protocol):
    """One adapter tick.  ``None`` means "nothing new", never "nothing wrong"."""

    name: str
    origin: EvidenceOrigin

    def poll(self, *, now_monotonic_ns: int) -> NavigationSnapshotV2 | None: ...


def restamp_origin(snapshot: NavigationSnapshotV2, origin: EvidenceOrigin) -> NavigationSnapshotV2:
    """Re-stamp every contributing header with ``origin``.

    Used by the replay source so a recording made from live evidence is
    published as REPLAY.  Provenance may be DOWNGRADED by a carrier this way;
    nothing anywhere upgrades it toward PHYSICAL.
    """

    if origin is EvidenceOrigin.PHYSICAL:
        raise ValueError("re-stamping toward PHYSICAL is never permitted")
    return replace(
        snapshot,
        map_from_odom=replace(
            snapshot.map_from_odom, header=replace(snapshot.map_from_odom.header, origin=origin)
        ),
        odom_from_base=replace(
            snapshot.odom_from_base, header=replace(snapshot.odom_from_base.header, origin=origin)
        ),
        base=replace(snapshot.base, header=replace(snapshot.base.header, origin=origin)),
        traversability=replace(
            snapshot.traversability,
            header=replace(snapshot.traversability.header, origin=origin),
        ),
        owner=replace(snapshot.owner, header=replace(snapshot.owner.header, origin=origin)),
    )


class CarrierObservationSource:
    """The simulator adapter as an :class:`ObservationSource`.

    ``observe`` is duck-typed on purpose: this module imports no backend, so
    the same source serves the mujoco backend, the headless city harness and a
    hand-built fixture.  ``range_convention`` has no default — the caller owns
    the A2 stamping decision and must state it.
    """

    origin = EvidenceOrigin.SIMULATION

    def __init__(
        self,
        observe: Callable[[], Any],
        *,
        range_convention: str,
        footprint_radius_m: float = 0.0,
        source_id: str = "simulator",
        process_epoch: int = 0,
        name: str = "simulator",
    ) -> None:
        if not callable(observe):
            raise TypeError("observe must be callable")
        self.name = name
        self._observe = observe
        self._range_convention = range_convention
        self._footprint_radius_m = footprint_radius_m
        self._source_id = source_id
        self._process_epoch = process_epoch
        self._sequence = 0

    def poll(self, *, now_monotonic_ns: int) -> NavigationSnapshotV2 | None:
        carrier = self._observe()
        if carrier is None:
            return None
        return self.snapshot_for(carrier, now_monotonic_ns=now_monotonic_ns)

    def snapshot_for(
        self, carrier: Any, *, now_monotonic_ns: int | None = None
    ) -> NavigationSnapshotV2:
        """Stamp one already-obtained carrier — the runtime's per-tick path."""

        self._sequence += 1
        snapshot = snapshot_from_carrier(
            carrier,
            range_convention=self._range_convention,
            footprint_radius_m=self._footprint_radius_m,
            source_id=self._source_id,
            process_epoch=self._process_epoch,
            sequence=self._sequence,
        )
        if now_monotonic_ns is None:
            return snapshot
        return replace(snapshot, assembled_monotonic_ns=now_monotonic_ns)


class ReplayObservationSource:
    """Recorded snapshots, published in order and stamped REPLAY."""

    origin = EvidenceOrigin.REPLAY
    name = "replay"

    def __init__(self, snapshots: Sequence[NavigationSnapshotV2], *, loop: bool = False) -> None:
        rows = tuple(snapshots)
        for item in rows:
            if not isinstance(item, NavigationSnapshotV2):
                raise TypeError("replay source requires NavigationSnapshotV2 records")
        self._rows = rows
        self._loop = bool(loop)
        self._index = 0

    def __len__(self) -> int:
        return len(self._rows)

    @property
    def exhausted(self) -> bool:
        return not self._loop and self._index >= len(self._rows)

    def poll(self, *, now_monotonic_ns: int) -> NavigationSnapshotV2 | None:
        if not self._rows:
            return None
        if self._index >= len(self._rows):
            if not self._loop:
                return None
            self._index = 0
        snapshot = self._rows[self._index]
        self._index += 1
        return restamp_origin(snapshot, EvidenceOrigin.REPLAY)


class PhysicalSourceNotCommissioned(RuntimeError):
    """Raised when a physical source is polled before it has real inputs."""


class PhysicalObservationSource:
    """Typed skeleton for the on-robot source.  Refuses rather than pretends.

    The three collaborators it needs do not exist in the product yet, and each
    one is a card:

    * ``sensor_hub`` — monotonic clock map, frames/extrinsics and the
      calibration manifest (HLD §3, ``parcel-sensor-hub``);
    * ``localizer`` — the real LIO provider publishing MAP→ODOM with health,
      covariance, jump and relocalization evidence (A3 shipped the latch and
      the matcher; the LIO itself is Gate 5);
    * ``perception`` — synchronized detections/tracks and owner belief
      (Gate 6).

    ``truth_pose`` is not a parameter and never will be: a physical profile
    that can fall back to simulator truth is not a physical profile.
    """

    origin = EvidenceOrigin.PHYSICAL
    name = "physical"

    def __init__(
        self,
        *,
        sensor_hub: Any = None,
        localizer: Any = None,
        perception: Any = None,
    ) -> None:
        self._sensor_hub = sensor_hub
        self._localizer = localizer
        self._perception = perception

    def missing_dependencies(self) -> tuple[str, ...]:
        """Which collaborators are still absent, in commissioning order."""

        return tuple(
            name
            for name, value in (
                ("sensor_hub", self._sensor_hub),
                ("localizer", self._localizer),
                ("perception", self._perception),
            )
            if value is None
        )

    def poll(self, *, now_monotonic_ns: int) -> NavigationSnapshotV2 | None:
        missing = self.missing_dependencies()
        raise PhysicalSourceNotCommissioned(
            "the physical observation source is a skeleton: "
            f"missing {', '.join(missing) if missing else 'the adapter body (HLD Gate 4)'}. "
            "It will not substitute simulator truth."
        )


__all__ = [
    "CarrierObservationSource",
    "ObservationSource",
    "PhysicalObservationSource",
    "PhysicalSourceNotCommissioned",
    "ReplayObservationSource",
    "restamp_origin",
]
