"""Card A4 SPINE — the observation boundary, and every way it refuses.

``research/20260824/PORTABLE_LIVING_DOG_HLD.md`` §4.1/§4.2 and Gate 2 are the
contract under test; ``research/20260824/embodiment-kernel-portability`` rows
K3/K4/K6 are the findings it implements.

Every refusal cell here is written as a PAIR: the mutant that must be refused,
and the control one step inside the bound that must be accepted.  A refusal
test with no control is indistinguishable from a check that refuses everything,
and this file's whole subject is a gate that must be exactly as strict as it
claims and no stricter.
"""

from __future__ import annotations

import ast
import math
import time
from dataclasses import fields, replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from parcel_robot.audio.devices import AudioDeviceStatus
from parcel_robot.backends.base import (
    DynamicAgentTrack,
    LidarObstacle,
    OwnerTrack,
    RobotPose,
    SemanticObjectTrack,
    SemanticRegionTrack,
    SimObservation,
)
from parcel_robot.contracts.evidence_header import (
    REASON_MISSING_INPUT,
    REASON_STALE,
    REASON_SYNTHETIC_ORIGIN_IN_PHYSICAL_PROFILE,
    contributing_epochs,
    header_health_reasons,
    mixed_epoch_sources,
    physical_profile,
)
from parcel_robot.contracts.navigation_snapshot_v2 import (
    RANGE_CONVENTION_BASE_CENTRE,
    RANGE_CONVENTION_BODY_SURFACE,
    RANGE_CONVENTION_RAW_SENSOR,
    NavigationSnapshotV2,
    TraversabilityV1,
)
from parcel_robot.core.input_health import (
    HealthAction,
    InputFault,
    InputHealthVerdict,
    RequiredInput,
)
from parcel_robot.evidence_origin import EvidenceOrigin
from parcel_robot.localization.discontinuity import ArmingLatch, BodySignals
from parcel_robot.localization.installer import NOT_COMMISSIONED, install_localization
from parcel_robot.localization.pose_adapter import LocalizedPoseProvider
from parcel_robot.models import VelocityCommand
from parcel_robot.navigation.reactive_safety import (
    ReactiveSafetyPolicy,
    apply_reactive_safety,
    apply_reactive_safety_from_snapshot,
    scan_evidence_from_snapshot,
)
from parcel_robot.observation.assembler import (
    DEFAULT_WINDOW_NS,
    REASON_TIME_WINDOW,
    SnapshotAssembler,
    SnapshotInputs,
)
from parcel_robot.observation.carrier_view import carrier_view
from parcel_robot.observation.simulator_adapter import snapshot_from_carrier
from parcel_robot.observation.sources import (
    CarrierObservationSource,
    PhysicalObservationSource,
    PhysicalSourceNotCommissioned,
    ReplayObservationSource,
    restamp_origin,
)
from parcel_robot.pose import TruthPoseProvider
from parcel_robot.runtime import RobotRuntime

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src" / "parcel_robot"


# --------------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------------
def _carrier(timestamp: float = 12.5, **overrides: object) -> SimObservation:
    """A carrier with EVERY field populated — the byte-map test needs all 22."""

    base = {
        "timestamp": timestamp,
        "robot": RobotPose(1.5, -2.25, 0.375, 0.75),
        "owner": OwnerTrack("owner-1", 3.0, 4.0, True, 0.87, "confirmed", "pixel_reid", 0.125),
        "nearest_obstacle_m": 0.9,
        "nearest_obstacle_bearing_rad": 0.3,
        "nearest_obstacle_id": "wall-1",
        "lidar_obstacles": (LidarObstacle(0.9, 0.3, "wall-1"), LidarObstacle(1.4, -1.2, None)),
        "nearest_person_m": 2.0,
        "nearest_person_bearing_rad": -0.4,
        "nearest_person_id": "p1",
        "nearest_person_ttc_s": 3.5,
        "dynamic_agents": (DynamicAgentTrack("p1", "person", 2.0, 0.5, 0.1, -0.2, 0.3, 0.4, 0.9),),
        "semantic_regions": (
            SemanticRegionTrack(
                "r1", "bed", ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0)), 0.8, "perception", True, {"k": 1}
            ),
        ),
        "collision": False,
        "emergency_stopped": False,
        "backend": "mujoco",
        "semantic_objects": (
            SemanticObjectTrack("o1", "lamp", (1.0, 2.0, 3.0), 0.6, "camera", False, None),
        ),
        "lidar_ranges": (1.0, float("nan"), 5.0),
        "lidar_angle_min_rad": -3.14,
        "lidar_angle_increment_rad": 0.01,
        "lidar_range_min_m": 0.05,
        "lidar_range_max_m": float("inf"),
    }
    base.update(overrides)
    return SimObservation(**base)  # type: ignore[arg-type]


def _snapshot(carrier: SimObservation | None = None, **kwargs: object) -> NavigationSnapshotV2:
    return snapshot_from_carrier(
        carrier if carrier is not None else _carrier(),
        range_convention=RANGE_CONVENTION_BODY_SURFACE,
        footprint_radius_m=0.32,
        **kwargs,  # type: ignore[arg-type]
    )


def _now_ns(snapshot: NavigationSnapshotV2) -> int:
    return snapshot.odom_from_base.header.capture_monotonic_ns


def _equal(left: object, right: object) -> bool:
    """Field equality that treats NaN as equal to NaN (scan sentinels)."""

    if isinstance(left, float) and isinstance(right, float):
        return left == right or (math.isnan(left) and math.isnan(right))
    if isinstance(left, tuple) and isinstance(right, tuple):
        return len(left) == len(right) and all(_equal(a, b) for a, b in zip(left, right))
    if hasattr(left, "__dataclass_fields__") and hasattr(right, "__dataclass_fields__"):
        names = [item.name for item in fields(left)]
        return names == [item.name for item in fields(right)] and all(
            _equal(getattr(left, name), getattr(right, name)) for name in names
        )
    return bool(left == right)


# --------------------------------------------------------------------------
# adapter equivalence — the byte-map
# --------------------------------------------------------------------------
def test_the_simulator_adapter_maps_every_carrier_field_losslessly() -> None:
    """All 22 carrier fields survive carrier -> snapshot -> carrier view.

    Field-by-field rather than one ``==``: the view is this package's own
    record type (the spine imports no backend), so an ``==`` could only ever
    be False, and a per-field comparison names the offender.
    """

    carrier = _carrier()
    view = carrier_view(_snapshot(carrier))
    divergent = [
        item.name
        for item in fields(carrier)
        if not _equal(getattr(carrier, item.name), getattr(view, item.name))
    ]
    assert divergent == [], f"fields lost in the round trip: {divergent}"
    assert len(fields(carrier)) == 22, "the carrier grew a field the adapter has not mapped"


def test_seeded_red_a_dropped_field_is_caught_by_the_byte_map() -> None:
    """The control: mutate one carrier field and the same comparison reddens."""

    carrier = _carrier()
    view = carrier_view(_snapshot(carrier))
    mutant = replace(carrier, nearest_obstacle_m=7.77)
    divergent = [
        item.name
        for item in fields(mutant)
        if not _equal(getattr(mutant, item.name), getattr(view, item.name))
    ]
    assert divergent == ["nearest_obstacle_m"]


def test_the_pose_read_is_map_composed_from_odom_not_the_raw_odom_leg() -> None:
    """A non-identity MAP->ODOM must move the pose the carrier view reports."""

    snapshot = _snapshot()
    assert carrier_view(snapshot).robot.x == pytest.approx(1.5)
    shifted = replace(snapshot, map_from_odom=replace(snapshot.map_from_odom, x=10.0, y=-4.0))
    assert carrier_view(shifted).robot.x == pytest.approx(11.5)
    assert carrier_view(shifted).robot.y == pytest.approx(-6.25)


# --------------------------------------------------------------------------
# the range convention is stamped by the source (A2 NAV-GLUE's handoff)
# --------------------------------------------------------------------------
def test_a_source_that_will_not_state_its_range_convention_cannot_publish() -> None:
    with pytest.raises(TypeError):
        snapshot_from_carrier(_carrier())  # type: ignore[call-arg]
    with pytest.raises(ValueError, match="range_convention"):
        snapshot_from_carrier(_carrier(), range_convention="metres_probably")
    # The control: each of the three real conventions publishes.
    for convention in (
        RANGE_CONVENTION_BODY_SURFACE,
        RANGE_CONVENTION_BASE_CENTRE,
        RANGE_CONVENTION_RAW_SENSOR,
    ):
        snapshot = snapshot_from_carrier(_carrier(), range_convention=convention)
        assert snapshot.traversability.range_convention == convention


def test_only_a_body_surface_source_may_claim_a_subtracted_footprint() -> None:
    header = _snapshot().traversability.header
    with pytest.raises(ValueError, match="footprint"):
        TraversabilityV1(
            header=header, range_convention=RANGE_CONVENTION_RAW_SENSOR, footprint_radius_m=0.32
        )
    assert (
        TraversabilityV1(
            header=header,
            range_convention=RANGE_CONVENTION_BODY_SURFACE,
            footprint_radius_m=0.32,
        ).footprint_radius_m
        == 0.32
    )


def test_mixed_carrier_ranges_are_normalized_before_one_body_surface_stamp() -> None:
    carrier = _carrier(
        nearest_obstacle_m=0.98,
        lidar_obstacles=(LidarObstacle(0.98, 0.0, "wall"),),
        lidar_ranges=(1.30, float("nan"), float("inf")),
        lidar_range_min_m=0.40,
        lidar_range_max_m=1.30,
    )
    source = CarrierObservationSource(
        lambda: carrier,
        range_convention=RANGE_CONVENTION_BODY_SURFACE,
        footprint_radius_m=0.32,
        planar_source_convention=RANGE_CONVENTION_BASE_CENTRE,
        analytic_source_convention=RANGE_CONVENTION_BODY_SURFACE,
    )

    snapshot = source.poll(now_monotonic_ns=round(carrier.timestamp * 1_000_000_000))
    assert snapshot is not None
    scan = snapshot.traversability
    assert scan.range_convention == RANGE_CONVENTION_BODY_SURFACE
    assert scan.footprint_radius_m == pytest.approx(0.32)
    assert scan.nearest_obstacle_m == pytest.approx(0.98)
    assert scan.obstacles[0].distance_m == pytest.approx(0.98)
    assert scan.ranges[0] == pytest.approx(0.98)
    assert math.isnan(scan.ranges[1])
    assert scan.ranges[2] == float("inf")
    assert scan.range_min_m == pytest.approx(0.08)
    assert scan.range_max_m == pytest.approx(0.98)


@pytest.mark.parametrize("malformed", (True, "1.30"))
@pytest.mark.parametrize(
    "planar_source_convention",
    (RANGE_CONVENTION_BASE_CENTRE, RANGE_CONVENTION_BODY_SURFACE),
)
def test_range_normalization_never_coerces_malformed_carrier_scalars(
    malformed: object,
    planar_source_convention: str,
) -> None:
    carrier = _carrier(lidar_ranges=(malformed,))
    source = CarrierObservationSource(
        lambda: carrier,
        range_convention=RANGE_CONVENTION_BODY_SURFACE,
        footprint_radius_m=0.32,
        planar_source_convention=planar_source_convention,
        analytic_source_convention=RANGE_CONVENTION_BODY_SURFACE,
    )

    with pytest.raises(TypeError, match="range values must be numbers"):
        source.poll(now_monotonic_ns=round(carrier.timestamp * 1_000_000_000))


@pytest.mark.parametrize(
    ("footprint", "error_type"),
    (
        (True, TypeError),
        ("0.32", TypeError),
        (float("nan"), ValueError),
        (float("inf"), ValueError),
        (-0.01, ValueError),
    ),
)
def test_conversion_footprint_is_rejected_before_scan_iteration(
    footprint: object,
    error_type: type[Exception],
) -> None:
    class RangesMustNotIterate(tuple):
        def __iter__(self):
            raise AssertionError("scan iterated before footprint validation")

    carrier = _carrier(lidar_ranges=RangesMustNotIterate((1.30,)))
    source = CarrierObservationSource(
        lambda: carrier,
        range_convention=RANGE_CONVENTION_BODY_SURFACE,
        footprint_radius_m=footprint,  # type: ignore[arg-type]
        planar_source_convention=RANGE_CONVENTION_BASE_CENTRE,
        analytic_source_convention=RANGE_CONVENTION_BODY_SURFACE,
    )

    with pytest.raises(error_type, match="footprint_radius_m"):
        source.poll(now_monotonic_ns=round(carrier.timestamp * 1_000_000_000))


@pytest.mark.parametrize("sentinel", (float("nan"), float("inf")))
def test_nonfinite_scan_cannot_bypass_an_unsupported_raw_conversion(
    sentinel: float,
) -> None:
    carrier = _carrier(
        nearest_obstacle_m=None,
        nearest_obstacle_bearing_rad=None,
        lidar_ranges=(sentinel,) * 360,
        lidar_range_min_m=None,
        lidar_range_max_m=sentinel,
    )
    source = CarrierObservationSource(
        lambda: carrier,
        range_convention=RANGE_CONVENTION_BODY_SURFACE,
        footprint_radius_m=0.32,
        planar_source_convention=RANGE_CONVENTION_RAW_SENSOR,
        analytic_source_convention=RANGE_CONVENTION_BODY_SURFACE,
    )

    with pytest.raises(ValueError, match="commissioned sensor extrinsic"):
        source.poll(now_monotonic_ns=round(carrier.timestamp * 1_000_000_000))


@pytest.mark.parametrize(
    ("output_convention", "source_convention"),
    (
        (RANGE_CONVENTION_BODY_SURFACE, RANGE_CONVENTION_BASE_CENTRE),
        (RANGE_CONVENTION_BASE_CENTRE, RANGE_CONVENTION_BODY_SURFACE),
        (RANGE_CONVENTION_RAW_SENSOR, RANGE_CONVENTION_RAW_SENSOR),
    ),
)
def test_supported_convention_pairs_preserve_nan_and_infinity_sentinels(
    output_convention: str,
    source_convention: str,
) -> None:
    carrier = _carrier(
        nearest_obstacle_m=None,
        nearest_obstacle_bearing_rad=None,
        lidar_ranges=(float("nan"), float("inf")),
        lidar_range_min_m=float("nan"),
        lidar_range_max_m=float("inf"),
    )
    source = CarrierObservationSource(
        lambda: carrier,
        range_convention=output_convention,
        footprint_radius_m=0.32,
        planar_source_convention=source_convention,
        analytic_source_convention=output_convention,
    )

    snapshot = source.poll(now_monotonic_ns=round(carrier.timestamp * 1_000_000_000))
    assert snapshot is not None
    assert math.isnan(snapshot.traversability.ranges[0])
    assert snapshot.traversability.ranges[1] == float("inf")
    assert math.isnan(snapshot.traversability.range_min_m)
    assert snapshot.traversability.range_max_m == float("inf")


# --------------------------------------------------------------------------
# the four fail-closed assembly rows, each with its control
# --------------------------------------------------------------------------
def test_a_stale_channel_is_refused_and_a_fresh_one_is_not() -> None:
    snapshot = _snapshot()
    assembler = SnapshotAssembler()
    fresh = assembler.review(snapshot, now_monotonic_ns=_now_ns(snapshot))
    assert fresh.health_reasons == ()
    assert fresh.translation_allowed

    ttl = snapshot.traversability.header.max_age_ns
    inside = assembler.review(snapshot, now_monotonic_ns=_now_ns(snapshot) + ttl)
    assert inside.health_reasons == (), "one nanosecond inside the TTL must still pass"

    stale = assembler.review(snapshot, now_monotonic_ns=_now_ns(snapshot) + ttl + 1)
    assert f"traversability:{REASON_STALE}" in stale.health_reasons
    assert not stale.translation_allowed


def test_two_epochs_of_one_source_never_join_one_snapshot() -> None:
    snapshot = _snapshot()
    assert mixed_epoch_sources(snapshot.headers) == ()
    assembler = SnapshotAssembler()
    assert assembler.review(snapshot, now_monotonic_ns=_now_ns(snapshot)).health_reasons == ()

    restarted = replace(
        snapshot,
        traversability=replace(
            snapshot.traversability,
            header=replace(snapshot.traversability.header, process_epoch=1),
        ),
    )
    assert mixed_epoch_sources(restarted.headers) == ("simulator",)
    reviewed = assembler.review(restarted, now_monotonic_ns=_now_ns(snapshot))
    assert "simulator:mixed_epoch" in reviewed.health_reasons
    assert not reviewed.translation_allowed
    assert contributing_epochs(restarted.headers) == (("simulator", 0), ("simulator", 1))


def test_simulation_origin_is_refused_under_a_physical_profile() -> None:
    snapshot = _snapshot()
    profile = physical_profile(
        frames=("map", "odom", "base_link"), calibration_hashes=("uncommissioned",)
    )
    physical = SnapshotAssembler(profile=profile)
    refused = physical.review(snapshot, now_monotonic_ns=_now_ns(snapshot))
    assert f"traversability:{REASON_SYNTHETIC_ORIGIN_IN_PHYSICAL_PROFILE}" in refused.health_reasons
    assert not refused.translation_allowed

    # Control 1: the same snapshot under the prototype profile is accepted.
    assert (
        SnapshotAssembler().review(snapshot, now_monotonic_ns=_now_ns(snapshot)).health_reasons
        == ()
    )
    # Control 2: a genuinely physical stamp clears the same physical profile.
    physical_snapshot = _snapshot(origin=EvidenceOrigin.PHYSICAL)
    assert (
        physical.review(
            physical_snapshot, now_monotonic_ns=_now_ns(physical_snapshot)
        ).health_reasons
        == ()
    )


def test_an_unknown_frame_and_an_uncommissioned_hash_are_each_refused() -> None:
    snapshot = _snapshot(origin=EvidenceOrigin.PHYSICAL)
    profile = physical_profile(frames=("map", "odom"), calibration_hashes=("mid360-v3",))
    reasons = header_health_reasons(
        snapshot.traversability.header, now_monotonic_ns=_now_ns(snapshot), profile=profile
    )
    assert "unknown_frame" in reasons and "uncommissioned_calibration" in reasons
    ok = physical_profile(frames=("base_link",), calibration_hashes=("uncommissioned",))
    assert (
        header_health_reasons(
            snapshot.traversability.header, now_monotonic_ns=_now_ns(snapshot), profile=ok
        )
        == ()
    )


def test_a_missing_channel_is_reported_rather_than_raised() -> None:
    """HLD §4.2: the assembler REPORTS missing inputs.  It must not raise."""

    snapshot = _snapshot()
    now = _now_ns(snapshot)
    complete = SnapshotInputs(
        map_from_odom=snapshot.map_from_odom,
        odom_from_base=snapshot.odom_from_base,
        base=snapshot.base,
        traversability=snapshot.traversability,
        owner=snapshot.owner,
    )
    assembler = SnapshotAssembler()
    assert assembler.assemble(complete, now_monotonic_ns=now).health_reasons == ()

    without_scan = replace(complete, traversability=None)
    assert without_scan.missing() == ("traversability",)
    partial = assembler.assemble(without_scan, now_monotonic_ns=now)
    assert partial.missing_inputs == ("traversability",)
    assert f"traversability:{REASON_MISSING_INPUT}" in partial.health_reasons
    assert not partial.translation_allowed
    # It still carries the pose it DID receive, so a HOLD can be narrated.
    assert partial.odom_from_base.x == pytest.approx(1.5)


def test_a_fresh_scan_is_never_joined_to_an_old_pose() -> None:
    """The window check — the one refusal a synchronous simulator never needed."""

    snapshot = _snapshot()
    now = _now_ns(snapshot)
    assembler = SnapshotAssembler()
    inside = replace(
        snapshot,
        traversability=replace(
            snapshot.traversability,
            header=replace(
                snapshot.traversability.header,
                capture_monotonic_ns=now + DEFAULT_WINDOW_NS,
                max_age_ns=10 * DEFAULT_WINDOW_NS,
            ),
        ),
    )
    assert REASON_TIME_WINDOW not in assembler.review(inside, now_monotonic_ns=now).health_reasons

    outside = replace(
        snapshot,
        traversability=replace(
            snapshot.traversability,
            header=replace(
                snapshot.traversability.header,
                capture_monotonic_ns=now + DEFAULT_WINDOW_NS + 1,
                max_age_ns=10 * DEFAULT_WINDOW_NS,
            ),
        ),
    )
    reviewed = assembler.review(outside, now_monotonic_ns=now)
    assert REASON_TIME_WINDOW in reviewed.health_reasons
    assert not reviewed.translation_allowed


def test_the_revision_advances_once_per_assembly() -> None:
    snapshot = _snapshot()
    assembler = SnapshotAssembler()
    first = assembler.review(snapshot, now_monotonic_ns=_now_ns(snapshot))
    second = assembler.review(snapshot, now_monotonic_ns=_now_ns(snapshot))
    assert (first.revision, second.revision) == (1, 2)


# --------------------------------------------------------------------------
# the migrated consumers
# --------------------------------------------------------------------------
def test_scan_evidence_is_stamped_from_the_header_not_from_a_backend_string() -> None:
    """The V2 path's one substantive difference from the carrier path."""

    simulated = _snapshot()
    evidence = scan_evidence_from_snapshot(simulated)
    assert evidence is not None
    assert evidence.origin is EvidenceOrigin.SIMULATION
    assert evidence.fixture_label == "mujoco"
    assert evidence.frame_id == "base_link"

    # The carrier path cannot do this: every carrier stamps SIMULATION by
    # construction, whatever the producer was.
    physical = _snapshot(origin=EvidenceOrigin.PHYSICAL)
    physical_evidence = scan_evidence_from_snapshot(physical)
    assert physical_evidence is not None
    assert physical_evidence.origin is EvidenceOrigin.PHYSICAL

    # And it may not invent presence the snapshot lacks (HW-2's rule).
    empty = _snapshot(
        _carrier(
            nearest_obstacle_m=None,
            nearest_obstacle_bearing_rad=None,
            nearest_obstacle_id=None,
            lidar_obstacles=(),
            lidar_ranges=(),
        )
    )
    assert scan_evidence_from_snapshot(empty) is None


def test_the_v2_reactive_safety_path_is_strictly_stronger_than_the_carrier_path() -> None:
    policy = ReactiveSafetyPolicy()
    command = VelocityCommand(vx=0.4)
    now = 12.5
    healthy = _snapshot()
    carrier_result = apply_reactive_safety(command, carrier_view(healthy), policy=policy, now=now)
    snapshot_result = apply_reactive_safety_from_snapshot(command, healthy, policy=policy, now=now)
    assert snapshot_result == carrier_result, "a healthy snapshot must not change the gate"

    refused = SnapshotAssembler().review(healthy, now_monotonic_ns=_now_ns(healthy) + 10**9)
    stopped, reason = apply_reactive_safety_from_snapshot(command, refused, policy=policy, now=now)
    assert reason == "stopped"
    assert stopped.vx == pytest.approx(0.0)
    # ... while the same geometry through the carrier path still translates,
    # which is exactly the authority the snapshot adds.
    assert apply_reactive_safety(command, carrier_view(refused), policy=policy, now=now)[0].vx > 0.0


def test_a_latched_localization_refuses_translation_even_on_a_clean_snapshot() -> None:
    snapshot = _snapshot()
    latched = replace(snapshot, localization=replace(snapshot.localization, motion_latched=True))
    assert not latched.translation_allowed
    stopped, reason = apply_reactive_safety_from_snapshot(
        VelocityCommand(vx=0.4), latched, policy=ReactiveSafetyPolicy(), now=12.5
    )
    assert (reason, stopped.vx) == ("stopped", 0.0)


# --------------------------------------------------------------------------
# the three sources
# --------------------------------------------------------------------------
def test_the_physical_source_refuses_rather_than_substituting_truth() -> None:
    source = PhysicalObservationSource()
    assert source.origin is EvidenceOrigin.PHYSICAL
    assert source.missing_dependencies() == ("sensor_hub", "localizer", "perception")
    with pytest.raises(PhysicalSourceNotCommissioned, match="will not substitute simulator truth"):
        source.poll(now_monotonic_ns=0)
    # Even fully "supplied" it refuses: the body is unbuilt and says so.
    supplied = PhysicalObservationSource(
        sensor_hub=object(), localizer=object(), perception=object()
    )
    assert supplied.missing_dependencies() == ()
    with pytest.raises(PhysicalSourceNotCommissioned, match="HLD Gate 4"):
        supplied.poll(now_monotonic_ns=0)


def test_replay_restamps_every_header_and_never_upgrades_toward_physical() -> None:
    snapshot = _snapshot()
    source = ReplayObservationSource([snapshot])
    replayed = source.poll(now_monotonic_ns=_now_ns(snapshot))
    assert replayed is not None
    assert {header.origin for header in replayed.headers} == {EvidenceOrigin.REPLAY}
    assert source.poll(now_monotonic_ns=0) is None and source.exhausted
    with pytest.raises(ValueError, match="PHYSICAL"):
        restamp_origin(snapshot, EvidenceOrigin.PHYSICAL)


def test_the_carrier_source_stamps_an_increasing_sequence() -> None:
    carriers = [_carrier(timestamp=1.0), _carrier(timestamp=1.1)]
    source = CarrierObservationSource(
        lambda: carriers.pop(0), range_convention=RANGE_CONVENTION_BODY_SURFACE
    )
    first = source.poll(now_monotonic_ns=0)
    second = source.poll(now_monotonic_ns=0)
    assert first is not None and second is not None
    assert (
        first.traversability.header.sequence,
        second.traversability.header.sequence,
    ) == (1, 2)


# --------------------------------------------------------------------------
# the runtime composition
# --------------------------------------------------------------------------
def test_the_shipping_default_commissions_no_localizer() -> None:
    assert install_localization(None, odom_provider=TruthPoseProvider()) is NOT_COMMISSIONED
    for absent in ({}, {"provider": ""}, {"provider": "truth"}):
        assert not install_localization(absent, odom_provider=TruthPoseProvider()).installed


def test_a_commissioned_profile_installs_a3s_latch_and_journal() -> None:
    installation = install_localization(
        {"provider": "scan_match"}, odom_provider=TruthPoseProvider()
    )
    assert isinstance(installation.provider, LocalizedPoseProvider)
    assert isinstance(installation.latch, ArmingLatch)
    assert installation.journal is not None
    assert not installation.motion_latched
    # A3's flag ships OFF, exactly as A3 shipped it.
    assert installation.provider.localizer.config.require_relocalization_margin is False
    with pytest.raises(ValueError, match="unknown localization provider"):
        install_localization({"provider": "orb_slam4"}, odom_provider=TruthPoseProvider())


def test_the_latch_can_only_make_the_health_verdict_stricter() -> None:
    allow = InputHealthVerdict(action=HealthAction.ALLOW, faults=())
    unlatched = SimpleNamespace(_localization=NOT_COMMISSIONED)
    assert RobotRuntime._compose_localization_latch(unlatched, allow) is allow

    latch = ArmingLatch()
    latch.observe_signals(BodySignals(power_cycled=True), t_s=1.0)
    assert latch.latched
    latched = SimpleNamespace(_localization=replace(NOT_COMMISSIONED, latch=latch))
    escalated = RobotRuntime._compose_localization_latch(latched, allow)
    assert escalated.action is HealthAction.LATCHED_STOP
    assert not escalated.translation_allowed
    assert escalated.faults[-1].reason == "localization_discontinuity_latched"

    # Stricter ONLY: an already-latched verdict is returned unchanged.
    already = InputHealthVerdict(
        action=HealthAction.LATCHED_STOP,
        faults=(InputFault(RequiredInput.SCAN, "scan:missing", HealthAction.LATCHED_STOP),),
    )
    assert RobotRuntime._compose_localization_latch(latched, already) is already


@pytest.fixture
def spine_config(tmp_path: Path) -> Path:
    path = tmp_path / "robot.yaml"
    path.write_text(
        f"""
skills:
  root: {REPO / "configs" / "skills"}
navigation:
  enabled: false
motion:
  backend: rl
  max_vx: 0.6
  max_vy: 0.4
  max_vyaw: 1.0
  rl:
    enabled: true
    policy_path: ""
memory:
  path: ":memory:"
poses: {{}}
modules: []
""",
        encoding="utf-8",
    )
    return path


class _FakeBackend:
    name = "fake"

    def __init__(self, observation: SimObservation) -> None:
        self._observation = observation

    def observe(self) -> SimObservation:
        return self._observation

    def move(self, command: VelocityCommand) -> None:
        return None

    def stop(self) -> None:
        return None

    def pose(self, pose: object) -> None:
        return None

    def trajectory(self, skill: object) -> None:
        return None

    def expression(self, joint_offsets: dict[str, float]) -> None:
        return None

    def move_owner(self, dx: float, dy: float) -> None:
        return None


def _audio_status() -> AudioDeviceStatus:
    return AudioDeviceStatus(
        status="text mode",
        driver="test",
        capture_hardware=False,
        connected_input=False,
        connected_output=False,
        detail="A4 spine fixture",
    )


def test_the_runtime_publishes_a_stamped_snapshot_and_keeps_the_truth_provider(
    spine_config: Path,
) -> None:
    """Default profile: the spine publishes, and NOTHING about pose changed."""

    carrier = _carrier(timestamp=time.monotonic())
    runtime = RobotRuntime(spine_config, _FakeBackend(carrier), audio_status=_audio_status())
    try:
        assert isinstance(runtime._pose_provider, TruthPoseProvider)
        assert runtime._localization is NOT_COMMISSIONED
        assert runtime.navigation_snapshot() is None

        runtime._publish_navigation_snapshot(carrier)
        snapshot = runtime.navigation_snapshot()
        assert snapshot is not None
        assert runtime._navigation_snapshot_error == ""
        # The convention is stamped by the SOURCE, with the footprint it
        # subtracted (A2 NAV-GLUE's handoff).
        assert snapshot.traversability.range_convention == RANGE_CONVENTION_BODY_SURFACE
        assert snapshot.traversability.footprint_radius_m == pytest.approx(
            runtime.robot_profile.footprint_radius_m
        )
        assert snapshot.traversability.header.origin is EvidenceOrigin.SIMULATION
        assert carrier_view(snapshot).robot.x == pytest.approx(carrier.robot.x)
    finally:
        runtime.close()


def test_a_malformed_carrier_never_takes_the_control_loop_down(spine_config: Path) -> None:
    carrier = _carrier(timestamp=time.monotonic())
    runtime = RobotRuntime(spine_config, _FakeBackend(carrier), audio_status=_audio_status())
    try:
        runtime._publish_navigation_snapshot(carrier)
        good = runtime.navigation_snapshot()
        runtime._publish_navigation_snapshot(replace(carrier, robot=RobotPose(float("nan"))))
        assert runtime.navigation_snapshot() is good, "the last good snapshot must stand"
        assert runtime._navigation_snapshot_error != ""
    finally:
        runtime.close()


def test_the_control_loop_publishes_before_the_observation_sink_reads(
    spine_config: Path,
) -> None:
    """Ordering pin: the snapshot is stamped from the identity-overlaid carrier."""

    source = (SRC / "runtime.py").read_text(encoding="utf-8")
    body = next(
        ast.unparse(node)
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.FunctionDef) and node.name == "_control_loop_body"
    )
    overlay = body.index("self._ot2_apply_owner_identity(observation)")
    publish = body.index("self._publish_navigation_snapshot(observation)")
    sink = body.index("self._observation_sink")
    assert overlay < publish < sink


# --------------------------------------------------------------------------
# the structural properties the audit rows measure
# --------------------------------------------------------------------------
def _imports(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            names.add(module)
            names.update(f"{module}.{alias.name}" for alias in node.names)
    return names


def test_the_observation_spine_imports_no_backend_and_no_vendor() -> None:
    """The property that makes the observation boundary replaceable."""

    checked = 0
    for path in sorted((SRC / "observation").rglob("*.py")):
        checked += 1
        for name in _imports(path):
            assert "backends" not in name, f"{path.name} imports {name}"
            assert "simulation" not in name, f"{path.name} imports {name}"
            assert "unitree" not in name.lower(), f"{path.name} imports {name}"
            assert not name.startswith("parcel_robot.runtime"), f"{path.name} imports {name}"
    assert checked >= 4, "the scan lost the observation package"


def test_no_product_module_outside_backends_or_simulation_imports_simobservation() -> None:
    """Audit row K3, measured here so it cannot regress between audits."""

    offenders = []
    scanned = 0
    for path in sorted(SRC.rglob("*.py")):
        rel = path.relative_to(SRC).as_posix()
        if rel.startswith(("backends/", "simulation/")):
            continue
        scanned += 1
        if any(name.endswith("SimObservation") for name in _imports(path)):
            offenders.append(rel)
    assert scanned > 200, "the K3 scan collapsed"
    assert sorted(set(offenders)) == [], f"K3 regressed: {sorted(set(offenders))}"


def test_seeded_red_the_k3_scan_still_sees_a_reintroduced_import(tmp_path: Path) -> None:
    """The control: the K3 scan is not vacuously green."""

    mutant = tmp_path / "mutant.py"
    mutant.write_text("from parcel_robot.backends.base import SimObservation\n", encoding="utf-8")
    assert any(name.endswith("SimObservation") for name in _imports(mutant))


def test_every_owned_service_names_a_principal_and_boots_disarmed() -> None:
    """Audit row K6: five owned units, each disarmed, each with an honest TODO."""

    units = sorted((REPO / "deploy" / "orin" / "services").glob("*.service"))
    assert [path.name for path in units] == [
        "parcel-audio.service",
        "parcel-gateway.service",
        "parcel-lio.service",
        "parcel-runtime.service",
        "parcel-safety.service",
    ]
    for path in units:
        text = path.read_text(encoding="utf-8")
        assert "PARCEL_ARMED=0" in text, f"{path.name} does not boot disarmed"
        assert "User=parcel-" in text, f"{path.name} names no principal"
        assert "--disarmed" in text, f"{path.name} starts armed"
        assert "TODO" in text, f"{path.name} claims a readiness it does not have"
        assert "ExecStartPre=/usr/bin/test -x" in text, (
            f"{path.name} would report active for a binary that does not exist"
        )
