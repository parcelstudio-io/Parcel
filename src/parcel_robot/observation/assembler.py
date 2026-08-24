"""The snapshot assembler: time windows enforced, missing inputs reported.

HLD §4.2's last sentence is this module's whole job — *"the assembler enforces
time windows and reports missing/stale inputs; it does not silently mix a
fresh image with an old range or pose."*  Everything here is pure: given the
channel records and a decision timestamp it returns one immutable
``NavigationSnapshotV2`` whose ``health_reasons`` are empty only if every
check passed.

**It reports, it does not raise.**  A missing scan still yields a snapshot,
because the body has to be able to narrate the HOLD it is about to take, and a
consumer that only ever saw exceptions would have nothing to say.  What a
refusal costs is authority: ``snapshot.translation_allowed`` is False and the
reason is named.

Five refusal classes, each with a seeded-red row in ``tests/test_a4_spine.py``:

1. a required channel is absent            → ``<channel>:missing_input``
2. a channel is past its own TTL           → ``<channel>:stale``
3. two epochs of one source in one snapshot → ``<source>:mixed_epoch``
4. synthetic origin under a physical profile → ``<channel>:synthetic_origin_in_physical_profile``
5. the channels' capture stamps span more than the window → ``time_window_exceeded``

Class 5 is the one that has no equivalent anywhere in the product today: a
simulator tick is synchronous so the question never arose, and it is precisely
the question a Mid-360 at 10 Hz beside a D455 at 30 Hz forces.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from parcel_robot.contracts.evidence_header import (
    PROTOTYPE_PROFILE,
    REASON_MISSING_INPUT,
    EvidenceHeaderV1,
    EvidenceProfile,
    header_health_reasons,
    mixed_epoch_sources,
)
from parcel_robot.contracts.navigation_snapshot_v2 import (
    RANGE_CONVENTION_RAW_SENSOR,
    BaseStateV1,
    DynamicTrackV2,
    LocalizationHealthV1,
    NavigationSnapshotV2,
    OwnerBeliefV1,
    PersonProximityV1,
    SemanticObservationV1,
    SystemHealthV1,
    TransformV1,
    TraversabilityV1,
)
from parcel_robot.evidence_origin import EvidenceOrigin

#: Reason recorded when the contributing capture stamps are too far apart.
REASON_TIME_WINDOW = "time_window_exceeded"

#: Default synchronization window: 100 ms, one 10 Hz control period.  Two
#: channels captured further apart than one tick are not one observation of the
#: world, they are two — and joining them is the silent mixing §4.2 forbids.
DEFAULT_WINDOW_NS = 100_000_000

#: The channels a snapshot cannot be honest without.
REQUIRED_CHANNELS = ("map_from_odom", "odom_from_base", "base", "traversability", "owner")


@dataclass(frozen=True, slots=True)
class SnapshotInputs:
    """Whatever arrived this tick.  ``None`` means "this channel did not."""

    map_from_odom: TransformV1 | None = None
    odom_from_base: TransformV1 | None = None
    base: BaseStateV1 | None = None
    traversability: TraversabilityV1 | None = None
    owner: OwnerBeliefV1 | None = None
    localization: LocalizationHealthV1 | None = None
    health: SystemHealthV1 | None = None
    person_proximity: PersonProximityV1 | None = None
    dynamic_tracks: tuple[DynamicTrackV2, ...] = ()
    semantics: tuple[SemanticObservationV1, ...] = ()

    def missing(self) -> tuple[str, ...]:
        return tuple(name for name in REQUIRED_CHANNELS if getattr(self, name) is None)


def _placeholder_header(channel: str, now_monotonic_ns: int) -> EvidenceHeaderV1:
    """A header for a channel that did not arrive.

    Origin ``UNKNOWN`` is deliberate: an absent channel has no provenance, and
    ``header_health_reasons`` refuses UNKNOWN on its own.  The stamp is ``now``
    so the refusal reads ``missing_input`` rather than the misleading ``stale``.
    """

    return EvidenceHeaderV1(
        source_id="assembler",
        process_epoch=0,
        capture_monotonic_ns=now_monotonic_ns,
        sequence=0,
        evidence_id=f"missing.{channel}",
        frame_id="unknown",
        calibration_hash="uncommissioned",
        origin=EvidenceOrigin.UNKNOWN,
        max_age_ns=1,
        transport_age_ns=0,
        health_reasons=(REASON_MISSING_INPUT,),
    )


def _channel_headers(snapshot: NavigationSnapshotV2) -> tuple[tuple[str, EvidenceHeaderV1], ...]:
    return (
        ("map_from_odom", snapshot.map_from_odom.header),
        ("odom_from_base", snapshot.odom_from_base.header),
        ("base", snapshot.base.header),
        ("traversability", snapshot.traversability.header),
        ("owner", snapshot.owner.header),
    )


def snapshot_health_reasons(
    snapshot: NavigationSnapshotV2,
    *,
    now_monotonic_ns: int,
    profile: EvidenceProfile = PROTOTYPE_PROFILE,
    window_ns: int = DEFAULT_WINDOW_NS,
) -> tuple[str, ...]:
    """Every reason this snapshot must not authorize translation, in order.

    Pure: no clock read, no state.  ``now_monotonic_ns`` is the caller's one
    decision timestamp, the same discipline ``core.input_health`` uses.
    """

    reasons: list[str] = []
    channels = _channel_headers(snapshot)
    for channel, header in channels:
        reasons.extend(
            f"{channel}:{reason}"
            for reason in header_health_reasons(
                header, now_monotonic_ns=now_monotonic_ns, profile=profile
            )
        )
    for source in mixed_epoch_sources(header for _, header in channels):
        reasons.append(f"{source}:mixed_epoch")
    stamps = [header.capture_monotonic_ns for _, header in channels]
    if stamps and max(stamps) - min(stamps) > window_ns:
        reasons.append(REASON_TIME_WINDOW)
    seen: dict[str, None] = {}
    for reason in reasons:
        seen.setdefault(reason, None)
    return tuple(seen)


@dataclass
class SnapshotAssembler:
    """Stateful only in its revision counter; every decision is pure.

    The counter is what lets a consumer say "I already acted on revision 41":
    HLD §4.2 requires the snapshot revision, and a monotonically increasing
    per-assembler integer is the cheapest honest one.
    """

    profile: EvidenceProfile = PROTOTYPE_PROFILE
    window_ns: int = DEFAULT_WINDOW_NS
    _revision: int = field(default=0, repr=False)

    @property
    def revision(self) -> int:
        return self._revision

    def review(
        self, snapshot: NavigationSnapshotV2, *, now_monotonic_ns: int
    ) -> NavigationSnapshotV2:
        """Re-stamp an already-built snapshot with this assembler's verdict.

        This is the single code path every producer's output passes through —
        the simulator adapter builds a snapshot in one shot (its tick is
        genuinely synchronous) and still gets the same five checks as a
        multi-process physical assembly.
        """

        reasons = snapshot_health_reasons(
            snapshot,
            now_monotonic_ns=now_monotonic_ns,
            profile=self.profile,
            window_ns=self.window_ns,
        )
        missing = tuple(
            channel
            for channel, header in _channel_headers(snapshot)
            if REASON_MISSING_INPUT in header.health_reasons
        )
        self._revision += 1
        return replace(
            snapshot,
            health_reasons=reasons,
            missing_inputs=missing,
            revision=self._revision,
            profile_name=self.profile.name,
            assembled_monotonic_ns=now_monotonic_ns,
        )

    def assemble(self, inputs: SnapshotInputs, *, now_monotonic_ns: int) -> NavigationSnapshotV2:
        """Join this tick's channels into one reviewed snapshot."""

        if not isinstance(inputs, SnapshotInputs):
            raise TypeError("assemble requires SnapshotInputs")
        snapshot = NavigationSnapshotV2(
            map_from_odom=inputs.map_from_odom
            or TransformV1(
                header=_placeholder_header("map_from_odom", now_monotonic_ns),
                parent_frame="map",
                child_frame="odom",
            ),
            odom_from_base=inputs.odom_from_base
            or TransformV1(
                header=_placeholder_header("odom_from_base", now_monotonic_ns),
                parent_frame="odom",
                child_frame="base_link",
            ),
            localization=inputs.localization or LocalizationHealthV1(),
            base=inputs.base or BaseStateV1(header=_placeholder_header("base", now_monotonic_ns)),
            traversability=inputs.traversability
            or TraversabilityV1(
                header=_placeholder_header("traversability", now_monotonic_ns),
                # An empty geometry record's convention is vacuous — there are no
                # metres to interpret.  ``traversability:missing_input`` is the
                # operative fact and it is recorded above.
                range_convention=RANGE_CONVENTION_RAW_SENSOR,
            ),
            owner=inputs.owner
            or OwnerBeliefV1(header=_placeholder_header("owner", now_monotonic_ns)),
            health=inputs.health or SystemHealthV1(),
            dynamic_tracks=tuple(inputs.dynamic_tracks),
            person_proximity=inputs.person_proximity or PersonProximityV1(),
            semantics=tuple(inputs.semantics),
            assembled_monotonic_ns=now_monotonic_ns,
        )
        return self.review(snapshot, now_monotonic_ns=now_monotonic_ns)


__all__ = [
    "DEFAULT_WINDOW_NS",
    "REASON_TIME_WINDOW",
    "REQUIRED_CHANNELS",
    "SnapshotAssembler",
    "SnapshotInputs",
    "snapshot_health_reasons",
]
