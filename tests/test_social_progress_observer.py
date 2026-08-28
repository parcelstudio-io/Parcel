"""Focused contract tests for the shadow-only social-progress observer."""

from __future__ import annotations

import ast
import json
import math
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from parcel_robot.contracts.evidence_header import EvidenceHeaderV1
from parcel_robot.contracts.navigation_snapshot_v2 import (
    RANGE_CONVENTION_BASE_CENTRE,
    RANGE_CONVENTION_BODY_SURFACE,
    RANGE_CONVENTION_RAW_SENSOR,
    BaseStateV1,
    DynamicTrackV2,
    LocalizationHealthV1,
    NavigationSnapshotV2,
    ObstacleReturnV1,
    OwnerBeliefV1,
    PersonProximityV1,
    SystemHealthV1,
    TransformV1,
    TraversabilityV1,
)
from parcel_robot.evidence_origin import EvidenceOrigin
from parcel_robot.models import VelocityCommand
from parcel_robot.navigation.social_progress import (
    MAX_PUBLIC_INTEGER,
    MAX_TRACK_CLASS_ID_CHARS,
    MAX_TRACK_COVARIANCE_ENTRIES,
    MAX_TRACK_ID_CHARS,
    SocialBlockCauseV1,
    SocialProgressStateV1,
    VisibilityStateV1,
)
from parcel_robot.navigation.social_progress_observer import (
    MAX_DYNAMIC_TRACKS,
    MAX_OBSERVER_HISTORY,
    MAX_OBSTACLE_ID_CHARS,
    MAX_OBSTACLE_ROWS,
    MAX_PLANAR_SCAN_RAYS,
    MAX_PUBLIC_HISTORY_SUMMARIES,
    MAX_PUBLIC_SNAPSHOT_BYTES,
    MAX_SNAPSHOT_EPOCH_ROWS,
    MAX_SNAPSHOT_EVIDENCE_IDS,
    PlannerFactsV1,
    SocialProgressObserverConfigV1,
    SocialProgressObserverV1,
    VelocityEvidenceV1,
    VelocityPrimitiveV1,
)

MODULE = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "parcel_robot"
    / "navigation"
    / "social_progress_observer.py"
)


def _header(
    capture_s: float,
    evidence_id: str,
    sequence: int = 1,
    *,
    transport_age_s: float = 0.0,
    clock_uncertainty_s: float = 0.0,
    source_id: str = "test-lidar",
    process_epoch: int = 1,
    calibration_hash: str = "test-calibration",
    health_reasons: tuple[str, ...] = (),
) -> EvidenceHeaderV1:
    return EvidenceHeaderV1(
        source_id=source_id,
        process_epoch=process_epoch,
        capture_monotonic_ns=int(capture_s * 1_000_000_000),
        sequence=sequence,
        evidence_id=evidence_id,
        frame_id="base_link",
        calibration_hash=calibration_hash,
        origin=EvidenceOrigin.SIMULATION,
        max_age_ns=500_000_000,
        transport_age_ns=int(transport_age_s * 1_000_000_000),
        fixture_label="social-progress-test",
        clock_map_uncertainty_ns=int(clock_uncertainty_s * 1_000_000_000),
        health_reasons=health_reasons,
    )


def _snapshot(
    now_s: float,
    *,
    revision: int = 1,
    evidence_id: str = "lidar-1",
    tracks: tuple[DynamicTrackV2, ...] = (),
    ranges: tuple[float, ...] | None = None,
    angle_min_rad: float = -math.pi,
    angle_increment_rad: float = math.pi / 180.0,
    obstacles: tuple[ObstacleReturnV1, ...] = (),
    person_proximity: PersonProximityV1 | None = None,
    range_convention: str = RANGE_CONVENTION_BASE_CENTRE,
    footprint_radius_m: float = 0.0,
    localization_health: str = "healthy",
    capture_s: float | None = None,
    transport_age_s: float = 0.0,
    clock_uncertainty_s: float = 0.0,
    source_sequence: int | None = None,
    source_id: str = "test-lidar",
    process_epoch: int = 1,
    calibration_hash: str = "test-calibration",
    header_health_reasons: tuple[str, ...] = (),
) -> NavigationSnapshotV2:
    header = _header(
        now_s if capture_s is None else capture_s,
        evidence_id,
        revision if source_sequence is None else source_sequence,
        transport_age_s=transport_age_s,
        clock_uncertainty_s=clock_uncertainty_s,
        source_id=source_id,
        process_epoch=process_epoch,
        calibration_hash=calibration_hash,
        health_reasons=header_health_reasons,
    )
    if ranges is None:
        ranges = tuple(5.0 for _ in range(360))
    scan = TraversabilityV1(
        header=header,
        range_convention=range_convention,
        footprint_radius_m=footprint_radius_m,
        obstacles=obstacles,
        ranges=ranges,
        angle_min_rad=angle_min_rad,
        angle_increment_rad=angle_increment_rad,
        range_min_m=0.05,
        range_max_m=5.0,
    )
    transform = TransformV1(
        header=header,
        parent_frame="map",
        child_frame="odom",
    )
    odom = TransformV1(
        header=header,
        parent_frame="odom",
        child_frame="base_link",
    )
    base = BaseStateV1(header=header)
    owner = OwnerBeliefV1(header=header)
    return NavigationSnapshotV2(
        map_from_odom=transform,
        odom_from_base=odom,
        localization=LocalizationHealthV1(health=localization_health),
        base=base,
        traversability=scan,
        owner=owner,
        health=SystemHealthV1(),
        dynamic_tracks=tracks,
        person_proximity=person_proximity or PersonProximityV1(),
        assembled_monotonic_ns=int(now_s * 1_000_000_000),
        revision=revision,
        profile_name="simulation",
    )


def _velocity(
    now_s: float,
    *,
    vx: float,
    vy: float = 0.0,
    source: str,
    sequence: int = 1,
    fresh: bool = True,
    age_s: float = 0.0,
) -> VelocityEvidenceV1:
    return VelocityEvidenceV1(
        primitive=VelocityPrimitiveV1(vx_mps=vx, vy_mps=vy),
        source=source,
        sequence=sequence,
        sample_monotonic_s=now_s - age_s,
        age_s=age_s,
        fresh=fresh,
    )


def _velocities(
    now_s: float,
    *,
    requested_vx: float = 0.4,
    requested_vy: float = 0.0,
    achieved_vx: float = 0.0,
    fresh: bool = True,
):
    return {
        "requested_velocity": _velocity(
            now_s,
            vx=requested_vx,
            vy=requested_vy,
            source="navigator",
        ),
        "final_velocity": _velocity(now_s, vx=0.0, source="control-manager"),
        "achieved_velocity": _velocity(
            now_s,
            vx=achieved_vx,
            source="controller-feedback",
            fresh=fresh,
        ),
    }


def _planner(**overrides: object) -> PlannerFactsV1:
    values: dict[str, object] = {
        "mission_status": "running",
        "route_status": "planned",
        "body_is_still": True,
        "steps_gate_blocked": 0,
        "progress_demand": True,
        "paused": False,
        "has_mission": True,
        "steps_without_progress": 1,
        "terminal_verification_steps": 0,
    }
    values.update(overrides)
    return PlannerFactsV1(**values)  # type: ignore[arg-type]


def _enabled(**overrides: object) -> SocialProgressObserverV1:
    values: dict[str, object] = {
        "enabled": True,
        "mode": "shadow",
        "robot_footprint_radius_m": 0.30,
    }
    values.update(overrides)
    return SocialProgressObserverV1(values)


def test_config_is_strict_default_off_and_shadow_only() -> None:
    default = SocialProgressObserverConfigV1.from_mapping(None)
    assert default.enabled is False
    assert default.mode == "shadow"
    with pytest.raises(ValueError, match="mode must be 'shadow'"):
        SocialProgressObserverConfigV1.from_mapping({"enabled": True, "mode": "active"})
    with pytest.raises(ValueError, match="unknown social progress"):
        SocialProgressObserverConfigV1.from_mapping({"enabeld": True})
    with pytest.raises(TypeError, match="enabled must be a boolean"):
        SocialProgressObserverConfigV1.from_mapping({"enabled": "false"})
    with pytest.raises(ValueError, match="decision.enabled"):
        SocialProgressObserverConfigV1.from_mapping(
            {"enabled": True, "decision": {"enabled": False}}
        )
    assert SocialProgressObserverConfigV1(history_size=MAX_OBSERVER_HISTORY).history_size == 128
    with pytest.raises(ValueError, match=r"history_size must be an integer in \[1, 128\]"):
        SocialProgressObserverConfigV1(history_size=MAX_OBSERVER_HISTORY + 1)
    with pytest.raises(ValueError, match=r"history_size must be an integer in \[1, 128\]"):
        SocialProgressObserverConfigV1.from_mapping({"history_size": 4096})


def test_disabled_observer_is_a_mutation_free_noop() -> None:
    observer = SocialProgressObserverV1()
    result = observer.observe(
        navigation_generation=1,
        now_monotonic_s=1.0,
        snapshot=None,
        planner=_planner(),
        **_velocities(1.0),
    )
    assert result is None
    assert observer.snapshot() == {
        "schema_version": 1,
        "public_schema": "social_progress_observer_public_v1",
        "enabled": False,
        "mode": "shadow",
        "navigation_generation": None,
        "history_capacity": 128,
        "sample_count": 0,
        "public_history_limit": 16,
        "public_history_count": 0,
        "history_truncated": False,
        "latest": None,
        "history": [],
    }


def test_velocity_values_are_copied_without_importing_command_authority() -> None:
    assert VelocityPrimitiveV1.from_value(VelocityCommand(0.2, -0.1, 0.3)) == (
        VelocityPrimitiveV1(0.2, -0.1, 0.3)
    )
    assert VelocityPrimitiveV1.from_value(
        SimpleNamespace(vx_mps=0.4, vy_mps=0.2, wz_radps=-0.3)
    ) == VelocityPrimitiveV1(0.4, 0.2, -0.3)
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert not any(
        name.startswith(
            (
                "parcel_robot.runtime",
                "parcel_robot.control",
                "parcel_robot.backends",
            )
        )
        for name in imported
    )


def test_missing_snapshot_is_observable_and_fail_closed() -> None:
    observer = _enabled()
    sample = observer.observe(
        navigation_generation=4,
        now_monotonic_s=10.0,
        snapshot=None,
        planner=_planner(),
        **_velocities(10.0),
    )
    assert sample is not None
    assert sample.snapshot_missing is True
    assert sample.snapshot_revision is None
    assert sample.snapshot_evidence_ids == ()
    assert sample.decision.state is SocialProgressStateV1.HOLD_UNCERTAIN
    assert sample.decision.cause is SocialBlockCauseV1.STALE_SENSOR
    assert sample.decision.authorizes_motion is False
    assert "command" not in sample.as_dict()


def test_track_is_visible_only_when_fresh_lidar_corroborates_it() -> None:
    track = DynamicTrackV2(
        track_id="person-1",
        class_id="person",
        x=0.8,
        y=0.0,
        radius_m=0.2,
        confidence=0.9,
    )
    ranges = [5.0 for _ in range(360)]
    ranges[180] = 0.6
    observer = _enabled()
    visible = observer.observe(
        navigation_generation=1,
        now_monotonic_s=1.0,
        snapshot=_snapshot(1.0, tracks=(track,), ranges=tuple(ranges)),
        planner=_planner(),
        **_velocities(1.0),
    )
    assert visible is not None
    assert visible.tracks[0].visibility_evidence.visibility is VisibilityStateV1.VISIBLE
    assert visible.tracks[0].visibility_evidence.lidar_mark_evidence_refs == ("lidar-1",)
    assert visible.decision.state is SocialProgressStateV1.HOLD_OCCUPIED

    uncorroborated = _enabled().observe(
        navigation_generation=1,
        now_monotonic_s=1.0,
        snapshot=_snapshot(1.0, tracks=(track,)),
        planner=_planner(),
        **_velocities(1.0),
    )
    assert uncorroborated is not None
    assert uncorroborated.tracks[0].visibility_evidence.visibility is VisibilityStateV1.OCCLUDED
    assert uncorroborated.decision.state is SocialProgressStateV1.HOLD_UNCERTAIN


def test_missing_track_is_retained_and_never_treated_as_free_space() -> None:
    track = DynamicTrackV2("person-1", "person", 0.8, 0.0, radius_m=0.2, confidence=0.9)
    observer = _enabled(missing_track_retention_s=0.5)
    first = observer.observe(
        navigation_generation=1,
        now_monotonic_s=1.0,
        snapshot=_snapshot(1.0, tracks=(track,)),
        planner=_planner(),
        **_velocities(1.0),
    )
    assert first is not None
    missing = observer.observe(
        navigation_generation=1,
        now_monotonic_s=1.1,
        snapshot=_snapshot(1.1, revision=2, evidence_id="lidar-2"),
        planner=_planner(),
        **_velocities(1.1),
    )
    assert missing is not None
    assert len(missing.tracks) == 1
    assert missing.tracks[0].visibility_evidence.visibility is VisibilityStateV1.OCCLUDED
    assert missing.corridor_evidence is None
    assert missing.decision.resume_eligible is False


def test_explicit_free_needs_complete_fresh_lidar_and_distinct_evidence() -> None:
    track = DynamicTrackV2("person-1", "person", 0.8, 0.0, radius_m=0.2, confidence=0.9)
    observer = _enabled(missing_track_retention_s=0.05)
    initial = observer.observe(
        navigation_generation=1,
        now_monotonic_s=1.0,
        snapshot=_snapshot(1.0, tracks=(track,)),
        planner=_planner(),
        **_velocities(1.0),
    )
    assert initial is not None

    clear_one = observer.observe(
        navigation_generation=1,
        now_monotonic_s=1.1,
        snapshot=_snapshot(1.1, revision=2, evidence_id="clear-a"),
        planner=_planner(),
        **_velocities(1.1),
    )
    assert clear_one is not None
    assert clear_one.corridor_evidence is not None
    assert clear_one.corridor_evidence.visibility is VisibilityStateV1.EXPLICIT_FREE
    assert clear_one.decision.clear_streak == 1

    repeated = observer.observe(
        navigation_generation=1,
        now_monotonic_s=1.15,
        snapshot=_snapshot(
            1.15,
            revision=3,
            evidence_id="relabeled-clear-a",
            capture_s=1.1,
            source_sequence=2,
        ),
        planner=_planner(),
        **_velocities(1.15),
    )
    assert repeated is not None
    assert repeated.corridor_evidence is not None
    assert repeated.corridor_evidence.evidence_id == clear_one.corridor_evidence.evidence_id
    assert repeated.decision.clear_streak == 1
    assert repeated.decision.resume_eligible is False

    clear_two = observer.observe(
        navigation_generation=1,
        now_monotonic_s=1.2,
        snapshot=_snapshot(
            1.2,
            revision=4,
            evidence_id="relabeled-clear-a",
            source_sequence=4,
        ),
        planner=_planner(),
        **_velocities(1.2),
    )
    assert clear_two is not None
    assert clear_two.corridor_evidence is not None
    assert clear_two.corridor_evidence.evidence_id != clear_one.corridor_evidence.evidence_id
    assert clear_two.decision.state is SocialProgressStateV1.PROBE_RESUME
    assert clear_two.decision.resume_eligible is True
    assert clear_two.decision.authorizes_motion is False
    public_corridor = observer.snapshot()["history"][-1]["corridor_evidence"]
    assert public_corridor == {
        "evidence_id": clear_two.corridor_evidence.evidence_id,
        "visibility": VisibilityStateV1.EXPLICIT_FREE.value,
    }


@pytest.mark.parametrize(
    ("snapshot_mutator", "expected"),
    [
        (
            lambda snapshot: replace(
                snapshot,
                traversability=replace(snapshot.traversability, ranges=(5.0, 5.0)),
            ),
            "incomplete",
        ),
        (
            lambda snapshot: replace(
                snapshot,
                traversability=replace(
                    snapshot.traversability,
                    range_convention=RANGE_CONVENTION_RAW_SENSOR,
                ),
            ),
            "raw",
        ),
        (
            lambda snapshot: replace(
                snapshot,
                traversability=replace(
                    snapshot.traversability,
                    header=replace(
                        snapshot.traversability.header,
                        capture_monotonic_ns=0,
                        max_age_ns=10_000_000,
                    ),
                ),
            ),
            "stale",
        ),
    ],
)
def test_incomplete_raw_or_stale_scan_cannot_mint_clearance(
    snapshot_mutator, expected: str
) -> None:
    del expected
    observer = _enabled()
    snapshot = snapshot_mutator(_snapshot(2.0))
    sample = observer.observe(
        navigation_generation=1,
        now_monotonic_s=2.0,
        snapshot=snapshot,
        planner=_planner(),
        **_velocities(2.0),
    )
    assert sample is not None
    assert sample.corridor_evidence is None


def test_base_centre_scan_needs_explicit_footprint_conversion() -> None:
    observer = SocialProgressObserverV1({"enabled": True, "mode": "shadow"})
    sample = observer.observe(
        navigation_generation=1,
        now_monotonic_s=2.0,
        snapshot=_snapshot(2.0),
        planner=_planner(),
        **_velocities(2.0),
    )
    assert sample is not None
    assert sample.corridor_evidence is None


@pytest.mark.parametrize("side_deg", (-60, 60))
def test_full_swept_rectangle_checks_near_field_on_both_sides(side_deg: int) -> None:
    ranges = [5.0 for _ in range(360)]
    ranges[180 + side_deg] = 0.50
    observer = _enabled()
    sample = observer.observe(
        navigation_generation=1,
        now_monotonic_s=2.0,
        snapshot=_snapshot(2.0, ranges=tuple(ranges)),
        planner=_planner(),
        **_velocities(2.0),
    )
    assert sample is not None
    assert sample.corridor_evidence is None


def _scan_index(angle_rad: float) -> int:
    return round(((angle_rad + math.pi) % (2.0 * math.pi)) / (math.pi / 180.0)) % 360


def test_swept_rectangle_handles_arbitrary_heading_and_angle_wrap() -> None:
    heading = math.radians(170.0)
    obstacle_angle = heading + math.radians(60.0)
    blocked_ranges = [5.0 for _ in range(360)]
    blocked_ranges[_scan_index(obstacle_angle)] = 0.50
    observer = _enabled()
    blocked = observer.observe(
        navigation_generation=1,
        now_monotonic_s=2.0,
        snapshot=_snapshot(2.0, ranges=tuple(blocked_ranges)),
        planner=_planner(),
        **_velocities(
            2.0,
            requested_vx=0.4 * math.cos(heading),
            requested_vy=0.4 * math.sin(heading),
        ),
    )
    assert blocked is not None
    assert blocked.corridor_evidence is None

    clear_ranges = list(blocked_ranges)
    clear_ranges[_scan_index(obstacle_angle)] = 0.55
    clear = _enabled().observe(
        navigation_generation=1,
        now_monotonic_s=2.0,
        snapshot=_snapshot(2.0, ranges=tuple(clear_ranges)),
        planner=_planner(),
        **_velocities(
            2.0,
            requested_vx=0.4 * math.cos(heading),
            requested_vy=0.4 * math.sin(heading),
        ),
    )
    assert clear is not None
    assert clear.corridor_evidence is not None


@pytest.mark.parametrize(
    ("convention", "footprint", "boundary_reported"),
    (
        (RANGE_CONVENTION_BASE_CENTRE, 0.0, 1.55),
        (RANGE_CONVENTION_BODY_SURFACE, 0.30, 1.25),
    ),
)
def test_swept_boundary_converts_base_centre_and_body_surface_ranges(
    convention: str,
    footprint: float,
    boundary_reported: float,
) -> None:
    blocked_ranges = [5.0 for _ in range(360)]
    blocked_ranges[180] = boundary_reported
    blocked = _enabled().observe(
        navigation_generation=1,
        now_monotonic_s=2.0,
        snapshot=_snapshot(
            2.0,
            ranges=tuple(blocked_ranges),
            range_convention=convention,
            footprint_radius_m=footprint,
        ),
        planner=_planner(),
        **_velocities(2.0),
    )
    assert blocked is not None
    assert blocked.corridor_evidence is None

    clear_ranges = list(blocked_ranges)
    clear_ranges[180] = boundary_reported + 0.01
    clear = _enabled().observe(
        navigation_generation=1,
        now_monotonic_s=2.0,
        snapshot=_snapshot(
            2.0,
            ranges=tuple(clear_ranges),
            range_convention=convention,
            footprint_radius_m=footprint,
        ),
        planner=_planner(),
        **_velocities(2.0),
    )
    assert clear is not None
    assert clear.corridor_evidence is not None


@pytest.mark.parametrize(
    "snapshot",
    (
        _snapshot(
            2.0,
            ranges=tuple(5.0 for _ in range(181)),
            angle_min_rad=-math.pi / 2.0,
        ),
        _snapshot(
            2.0,
            ranges=tuple(5.0 for _ in range(60)),
            angle_increment_rad=2.0 * math.pi / 60.0,
        ),
        _snapshot(
            2.0,
            ranges=tuple(math.nan if index == 17 else 5.0 for index in range(360)),
        ),
    ),
)
def test_scan_endpoints_coarse_gaps_and_unusable_rays_refuse_full_coverage(
    snapshot: NavigationSnapshotV2,
) -> None:
    sample = _enabled().observe(
        navigation_generation=1,
        now_monotonic_s=2.0,
        snapshot=snapshot,
        planner=_planner(),
        **_velocities(2.0),
    )
    assert sample is not None
    assert sample.corridor_evidence is None


def test_snapshot_health_refusal_prevents_clear_certificate() -> None:
    observer = _enabled()
    unhealthy = replace(_snapshot(2.0), health_reasons=("stale",))
    sample = observer.observe(
        navigation_generation=1,
        now_monotonic_s=2.0,
        snapshot=unhealthy,
        planner=_planner(),
        **_velocities(2.0),
    )
    assert sample is not None
    assert unhealthy.translation_allowed is False
    assert sample.corridor_evidence is None
    assert sample.decision.cause is SocialBlockCauseV1.STALE_SENSOR


@pytest.mark.parametrize(
    "proximity",
    (
        PersonProximityV1(distance_m=0.8, bearing_rad=0.0, person_id="front"),
        PersonProximityV1(
            distance_m=0.50,
            bearing_rad=math.radians(60.0),
            person_id="side",
        ),
        PersonProximityV1(distance_m=100.0, bearing_rad=None, person_id="unknown-bearing"),
    ),
)
def test_fresh_person_proximity_contradicts_explicit_free(
    proximity: PersonProximityV1,
) -> None:
    sample = _enabled().observe(
        navigation_generation=1,
        now_monotonic_s=2.0,
        snapshot=_snapshot(2.0, person_proximity=proximity),
        planner=_planner(),
        **_velocities(2.0),
    )
    assert sample is not None
    assert sample.corridor_evidence is None


@pytest.mark.parametrize(
    "proximity",
    (
        PersonProximityV1(distance_m=2.0, bearing_rad=0.0, person_id="beyond-end"),
        PersonProximityV1(
            distance_m=0.70,
            bearing_rad=math.radians(60.0),
            person_id="beyond-side",
        ),
    ),
)
def test_known_person_outside_swept_rectangle_does_not_mask_lidar_clearance(
    proximity: PersonProximityV1,
) -> None:
    sample = _enabled().observe(
        navigation_generation=1,
        now_monotonic_s=2.0,
        snapshot=_snapshot(2.0, person_proximity=proximity),
        planner=_planner(),
        **_velocities(2.0),
    )
    assert sample is not None
    assert sample.corridor_evidence is not None


def test_effective_transport_exact_bound_is_preserved_and_over_bound_refused() -> None:
    config = {
        "decision": {"max_transport_delay_s": 0.08},
        "max_clock_uncertainty_s": 0.02,
    }
    track = DynamicTrackV2("person-transport", "person", 0.8, 0.0, radius_m=0.2)
    exact_observer = _enabled(missing_track_retention_s=0.01, **config)
    exact_observer.observe(
        navigation_generation=1,
        now_monotonic_s=9.9,
        snapshot=_snapshot(9.9, tracks=(track,)),
        planner=_planner(),
        **_velocities(9.9),
    )
    exact = exact_observer.observe(
        navigation_generation=1,
        now_monotonic_s=10.20,
        snapshot=_snapshot(
            10.08,
            capture_s=10.0,
            transport_age_s=0.08,
        ),
        planner=_planner(),
        **_velocities(10.20),
    )
    assert exact is not None
    assert exact.corridor_evidence is not None
    assert exact.corridor_evidence.source_monotonic_s == pytest.approx(10.0)
    assert exact.corridor_evidence.receive_monotonic_s == pytest.approx(10.08)
    assert exact.decision.clear_streak == 1

    over = _enabled(**config).observe(
        navigation_generation=1,
        now_monotonic_s=10.20,
        snapshot=_snapshot(
            10.080_000_002,
            capture_s=10.0,
            transport_age_s=0.080_000_002,
        ),
        planner=_planner(),
        **_velocities(10.20),
    )
    assert over is not None
    assert over.corridor_evidence is None
    assert over.decision.cause is SocialBlockCauseV1.STALE_SENSOR


def test_clock_uncertainty_exact_configured_bound_passes_and_over_bound_refuses() -> None:
    exact = _enabled(max_clock_uncertainty_s=0.02).observe(
        navigation_generation=1,
        now_monotonic_s=11.0,
        snapshot=_snapshot(11.0, clock_uncertainty_s=0.02),
        planner=_planner(),
        **_velocities(11.0),
    )
    assert exact is not None
    assert exact.corridor_evidence is not None

    over = _enabled(max_clock_uncertainty_s=0.02).observe(
        navigation_generation=1,
        now_monotonic_s=11.0,
        snapshot=_snapshot(11.0, clock_uncertainty_s=0.020_000_002),
        planner=_planner(),
        **_velocities(11.0),
    )
    assert over is not None
    assert over.corridor_evidence is None


@pytest.mark.parametrize(
    "snapshot",
    (
        _snapshot(12.0, capture_s=12.01),
        _snapshot(12.0, header_health_reasons=("stale",)),
    ),
)
def test_future_capture_and_header_health_cannot_mint_clearance(
    snapshot: NavigationSnapshotV2,
) -> None:
    sample = _enabled().observe(
        navigation_generation=1,
        now_monotonic_s=12.0,
        snapshot=snapshot,
        planner=_planner(),
        **_velocities(12.0),
    )
    assert sample is not None
    assert sample.corridor_evidence is None
    assert sample.decision.cause is SocialBlockCauseV1.STALE_SENSOR


def test_planner_facts_derive_costmap_ghost_without_parsing_notes() -> None:
    observer = _enabled()
    sample = observer.observe(
        navigation_generation=1,
        now_monotonic_s=3.0,
        snapshot=_snapshot(3.0),
        planner=_planner(steps_gate_blocked=3),
        **_velocities(3.0),
    )
    assert sample is not None
    assert sample.decision.cause is SocialBlockCauseV1.COSTMAP_GHOST
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    assert not any(
        isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and "command.note" in node.value
        for node in ast.walk(tree)
    )


@pytest.mark.parametrize(
    "obstacles",
    (
        (ObstacleReturnV1(4.0, 0.0, "person-1"),),
        (ObstacleReturnV1(0.6, 1.0, "person-1"),),
    ),
)
def test_matching_obstacle_id_without_spatial_agreement_is_not_visible(
    obstacles: tuple[ObstacleReturnV1, ...],
) -> None:
    track = DynamicTrackV2("person-1", "person", 0.8, 0.0, radius_m=0.2, confidence=0.9)
    sample = _enabled().observe(
        navigation_generation=1,
        now_monotonic_s=3.0,
        snapshot=_snapshot(3.0, tracks=(track,), obstacles=obstacles),
        planner=_planner(),
        **_velocities(3.0),
    )
    assert sample is not None
    assert sample.tracks[0].visibility_evidence.visibility is VisibilityStateV1.OCCLUDED


def test_matching_obstacle_id_with_spatial_agreement_is_visible() -> None:
    track = DynamicTrackV2("person-1", "person", 0.8, 0.0, radius_m=0.2, confidence=0.9)
    sample = _enabled().observe(
        navigation_generation=1,
        now_monotonic_s=3.0,
        snapshot=_snapshot(
            3.0,
            tracks=(track,),
            obstacles=(ObstacleReturnV1(0.6, 0.0, "person-1"),),
        ),
        planner=_planner(),
        **_velocities(3.0),
    )
    assert sample is not None
    assert sample.tracks[0].visibility_evidence.visibility is VisibilityStateV1.VISIBLE


@pytest.mark.parametrize(
    ("snapshot", "message"),
    (
        (
            _snapshot(
                3.0,
                tracks=tuple(
                    DynamicTrackV2(f"person-{index}", "person", 3.0, 0.0)
                    for index in range(MAX_DYNAMIC_TRACKS + 1)
                ),
            ),
            "dynamic_tracks exceeds",
        ),
        (
            _snapshot(
                3.0,
                obstacles=tuple(
                    ObstacleReturnV1(3.0, 0.0, f"obstacle-{index}")
                    for index in range(MAX_OBSTACLE_ROWS + 1)
                ),
            ),
            "obstacles exceeds",
        ),
        (
            _snapshot(
                3.0,
                ranges=tuple(5.0 for _ in range(MAX_PLANAR_SCAN_RAYS + 1)),
            ),
            "planar scan exceeds",
        ),
    ),
)
def test_oversized_rows_are_refused_before_derivation(
    monkeypatch: pytest.MonkeyPatch,
    snapshot: NavigationSnapshotV2,
    message: str,
) -> None:
    observer = _enabled()

    def must_not_derive(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise AssertionError("row-wise derivation ran before the constant-time bound")

    monkeypatch.setattr(observer, "_derive_tracks", must_not_derive)
    with pytest.raises(ValueError, match=message):
        observer.observe(
            navigation_generation=1,
            now_monotonic_s=3.0,
            snapshot=snapshot,
            planner=_planner(),
            **_velocities(3.0),
        )


@pytest.mark.parametrize(
    ("snapshot", "message"),
    (
        (
            _snapshot(
                3.0,
                tracks=(
                    DynamicTrackV2(
                        "t" * (MAX_TRACK_ID_CHARS + 1),
                        "person",
                        3.0,
                        0.0,
                    ),
                ),
            ),
            "track_id",
        ),
        (
            _snapshot(
                3.0,
                tracks=(
                    DynamicTrackV2(
                        "person",
                        "c" * (MAX_TRACK_CLASS_ID_CHARS + 1),
                        3.0,
                        0.0,
                    ),
                ),
            ),
            "class_id",
        ),
        (
            _snapshot(
                3.0,
                tracks=(
                    DynamicTrackV2(
                        "person",
                        "person",
                        3.0,
                        0.0,
                        covariance=(0.0,) * (MAX_TRACK_COVARIANCE_ENTRIES + 1),
                    ),
                ),
            ),
            "covariance exceeds",
        ),
        (
            _snapshot(
                3.0,
                obstacles=(
                    ObstacleReturnV1(
                        3.0,
                        0.0,
                        "o" * (MAX_OBSTACLE_ID_CHARS + 1),
                    ),
                ),
            ),
            "obstacle_id",
        ),
        (
            replace(
                _snapshot(3.0),
                traversability=replace(
                    _snapshot(3.0).traversability,
                    nearest_obstacle_id="n" * (MAX_OBSTACLE_ID_CHARS + 1),
                ),
            ),
            "nearest_obstacle_id",
        ),
        (
            _snapshot(
                3.0,
                person_proximity=PersonProximityV1(
                    distance_m=3.0,
                    bearing_rad=0.0,
                    person_id="p" * (MAX_OBSTACLE_ID_CHARS + 1),
                ),
            ),
            "person_id",
        ),
    ),
)
def test_nested_maximum_plus_one_is_refused_before_derivation(
    monkeypatch: pytest.MonkeyPatch,
    snapshot: NavigationSnapshotV2,
    message: str,
) -> None:
    observer = _enabled()
    derived = False

    def must_not_derive(*args: object, **kwargs: object) -> None:
        nonlocal derived
        del args, kwargs
        derived = True
        raise AssertionError("derivation began for overbound nested input")

    monkeypatch.setattr(observer, "_derive_tracks", must_not_derive)
    with pytest.raises(ValueError, match=message):
        observer.observe(
            navigation_generation=1,
            now_monotonic_s=3.0,
            snapshot=snapshot,
            planner=_planner(),
            **_velocities(3.0),
        )
    assert derived is False
    assert observer.snapshot()["sample_count"] == 0


def test_250k_covariance_is_rejected_before_iteration_derivation_or_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class CovarianceMustNotIterate(tuple):
        def __iter__(self):
            raise AssertionError("overbound covariance was iterated")

    covariance = CovarianceMustNotIterate((0.0,) * 250_000)
    oversized = _snapshot(
        3.0,
        tracks=(
            DynamicTrackV2(
                "person-huge-covariance",
                "person",
                3.0,
                0.0,
                covariance=covariance,
            ),
        ),
    )
    observer = _enabled()
    derived = False

    def must_not_derive(*args: object, **kwargs: object) -> None:
        nonlocal derived
        del args, kwargs
        derived = True
        raise AssertionError("derivation began for overbound covariance")

    monkeypatch.setattr(observer, "_derive_tracks", must_not_derive)
    with pytest.raises(ValueError, match="covariance exceeds"):
        observer.observe(
            navigation_generation=99,
            now_monotonic_s=3.0,
            snapshot=oversized,
            planner=_planner(),
            **_velocities(3.0),
        )
    assert derived is False
    assert observer.snapshot()["navigation_generation"] is None
    assert observer.snapshot()["sample_count"] == 0


def test_observer_contract_accepts_exact_unsigned_64_bit_maximum() -> None:
    now = 3.0
    velocities = {
        name: replace(value, sequence=MAX_PUBLIC_INTEGER)
        for name, value in _velocities(now).items()
    }
    planner = _planner(
        steps_gate_blocked=MAX_PUBLIC_INTEGER,
        steps_without_progress=MAX_PUBLIC_INTEGER,
        terminal_verification_steps=MAX_PUBLIC_INTEGER,
    )
    observer = _enabled()
    sample = observer.observe(
        navigation_generation=MAX_PUBLIC_INTEGER,
        now_monotonic_s=now,
        snapshot=_snapshot(
            now,
            revision=MAX_PUBLIC_INTEGER,
            source_sequence=MAX_PUBLIC_INTEGER,
            process_epoch=MAX_PUBLIC_INTEGER,
        ),
        planner=planner,
        **velocities,
    )
    assert sample is not None
    evidence_ids = tuple(f"{index}" + "🐾" * 127 for index in range(MAX_SNAPSHOT_EVIDENCE_IDS))
    epochs = tuple(
        (f"{index}" + "🐕" * 127, MAX_PUBLIC_INTEGER) for index in range(MAX_SNAPSHOT_EPOCH_ROWS)
    )
    direct = replace(
        sample,
        sample_sequence=MAX_PUBLIC_INTEGER,
        snapshot_assembled_monotonic_ns=MAX_PUBLIC_INTEGER,
        snapshot_evidence_ids=evidence_ids,
        snapshot_epochs=epochs,
    )

    assert direct.sample_sequence == MAX_PUBLIC_INTEGER
    assert direct.navigation_generation == MAX_PUBLIC_INTEGER
    assert direct.snapshot_revision == MAX_PUBLIC_INTEGER
    assert direct.snapshot_assembled_monotonic_ns == MAX_PUBLIC_INTEGER
    assert direct.snapshot_epochs[-1][1] == MAX_PUBLIC_INTEGER
    assert planner.terminal_verification_steps == MAX_PUBLIC_INTEGER
    assert velocities["requested_velocity"].sequence == MAX_PUBLIC_INTEGER


def test_observer_contract_rejects_all_overbound_retained_integer_fields() -> None:
    observer = _enabled()
    sample = observer.observe(
        navigation_generation=1,
        now_monotonic_s=3.0,
        snapshot=_snapshot(3.0),
        planner=_planner(),
        **_velocities(3.0),
    )
    assert sample is not None

    for overbound in (MAX_PUBLIC_INTEGER + 1, 10**5000):
        with pytest.raises(ValueError, match="must be in"):
            _velocity(3.0, vx=0.0, source="source", sequence=overbound)
        for counter in (
            "steps_gate_blocked",
            "steps_without_progress",
            "terminal_verification_steps",
        ):
            with pytest.raises(ValueError, match="must be in"):
                replace(_planner(), **{counter: overbound})
        for field_name in (
            "sample_sequence",
            "navigation_generation",
            "snapshot_revision",
            "snapshot_assembled_monotonic_ns",
        ):
            with pytest.raises(ValueError, match="must be in"):
                replace(sample, **{field_name: overbound})
        with pytest.raises(ValueError, match="snapshot_epochs.*epoch must be in"):
            replace(sample, snapshot_epochs=(("source", overbound),))


def test_direct_sample_evidence_rows_have_absolute_count_and_text_bounds() -> None:
    observer = _enabled()
    sample = observer.observe(
        navigation_generation=1,
        now_monotonic_s=3.0,
        snapshot=_snapshot(3.0),
        planner=_planner(),
        **_velocities(3.0),
    )
    assert sample is not None

    with pytest.raises(ValueError, match="snapshot_evidence_ids exceeds"):
        replace(
            sample,
            snapshot_evidence_ids=("evidence",) * (MAX_SNAPSHOT_EVIDENCE_IDS + 1),
        )
    with pytest.raises(ValueError, match=r"snapshot_evidence_ids\[0\]"):
        replace(sample, snapshot_evidence_ids=("🐕" * 129,))
    with pytest.raises(ValueError, match="snapshot_epochs exceeds"):
        replace(
            sample,
            snapshot_epochs=(("source", 1),) * (MAX_SNAPSHOT_EPOCH_ROWS + 1),
        )
    with pytest.raises(ValueError, match=r"snapshot_epochs\[0\] source_id"):
        replace(sample, snapshot_epochs=(("🐾" * 129, 1),))


def test_huge_snapshot_integers_are_rejected_before_derivation_or_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observer = _enabled()
    derived = False

    def must_not_derive(*args: object, **kwargs: object) -> None:
        nonlocal derived
        del args, kwargs
        derived = True
        raise AssertionError("derivation began for an overbound public integer")

    monkeypatch.setattr(observer, "_derive_tracks", must_not_derive)
    for overbound in (MAX_PUBLIC_INTEGER + 1, 10**5000):
        with pytest.raises(ValueError, match="navigation_generation must be in"):
            observer.observe(
                navigation_generation=overbound,
                now_monotonic_s=3.0,
                snapshot=_snapshot(3.0),
                planner=_planner(),
                **_velocities(3.0),
            )
        malformed_snapshots = (
            _snapshot(3.0, revision=overbound, source_sequence=1),
            replace(_snapshot(3.0), assembled_monotonic_ns=overbound),
            _snapshot(3.0, process_epoch=overbound, source_sequence=1),
            _snapshot(3.0, source_sequence=overbound),
        )
        for snapshot in malformed_snapshots:
            with pytest.raises(ValueError, match="must be in"):
                observer.observe(
                    navigation_generation=1,
                    now_monotonic_s=3.0,
                    snapshot=snapshot,
                    planner=_planner(),
                    **_velocities(3.0),
                )

    assert derived is False
    assert observer.snapshot()["navigation_generation"] is None
    assert observer.snapshot()["sample_count"] == 0


def test_maximum_history_has_one_compact_latest_and_bounded_public_summaries() -> None:
    tracks = tuple(
        DynamicTrackV2(
            # Max-character Unicode refuter: default JSON expands each emoji
            # into a UTF-16 surrogate pair. Public diagnostics hash IDs.
            track_id=f"{index:02d}" + "🐕" * (MAX_TRACK_ID_CHARS - 2),
            class_id="🐾" * MAX_TRACK_CLASS_ID_CHARS,
            x=3.0,
            y=0.0,
            radius_m=0.3,
            confidence=0.9,
            covariance=(-1.7976931348623157e308,) * MAX_TRACK_COVARIANCE_ENTRIES,
        )
        for index in range(MAX_DYNAMIC_TRACKS)
    )
    obstacles = tuple(
        ObstacleReturnV1(
            4.0,
            0.0,
            f"{index:02d}" + "🚧" * (MAX_OBSTACLE_ID_CHARS - 2),
        )
        for index in range(MAX_OBSTACLE_ROWS)
    )
    observer = _enabled()
    sample = None
    for sequence in range(1, MAX_OBSERVER_HISTORY + 1):
        now = 3.0 + sequence / 100.0
        velocities = {
            name: replace(
                value,
                source="🐕" * 128,
                sequence=MAX_PUBLIC_INTEGER,
            )
            for name, value in _velocities(now).items()
        }
        sample = observer.observe(
            navigation_generation=MAX_PUBLIC_INTEGER,
            now_monotonic_s=now,
            snapshot=_snapshot(
                now,
                revision=MAX_PUBLIC_INTEGER - MAX_OBSERVER_HISTORY + sequence,
                evidence_id="e" * 128,
                tracks=tracks,
                obstacles=obstacles,
                ranges=(),
                source_sequence=MAX_PUBLIC_INTEGER,
                source_id="s" * 128,
                process_epoch=MAX_PUBLIC_INTEGER,
                calibration_hash="c" * 128,
            ),
            planner=_planner(
                mission_status="🐾" * 128,
                route_status="🐕" * 128,
                steps_gate_blocked=MAX_PUBLIC_INTEGER,
                steps_without_progress=MAX_PUBLIC_INTEGER,
                terminal_verification_steps=MAX_PUBLIC_INTEGER,
            ),
            **velocities,
        )
    assert sample is not None
    assert len(sample.tracks) == MAX_DYNAMIC_TRACKS
    public = observer.snapshot()
    utf8 = json.dumps(
        public,
        allow_nan=False,
        ensure_ascii=False,
    ).encode("utf-8")
    # Exercise json.dumps' default ensure_ascii=True path as served by the API.
    ascii_json = json.dumps(public, allow_nan=False).encode("ascii")
    assert len(utf8) <= MAX_PUBLIC_SNAPSHOT_BYTES
    assert len(ascii_json) <= MAX_PUBLIC_SNAPSHOT_BYTES
    assert public["sample_count"] == MAX_OBSERVER_HISTORY
    assert public["history_capacity"] == MAX_OBSERVER_HISTORY
    assert public["public_history_limit"] == MAX_PUBLIC_HISTORY_SUMMARIES
    assert public["public_history_count"] == MAX_PUBLIC_HISTORY_SUMMARIES
    assert public["history_truncated"] is True
    assert len(public["history"]) == MAX_PUBLIC_HISTORY_SUMMARIES
    assert public["latest"]["sample_sequence"] == MAX_OBSERVER_HISTORY
    assert public["navigation_generation"] == MAX_PUBLIC_INTEGER
    assert public["latest"]["snapshot_revision"] == MAX_PUBLIC_INTEGER
    assert public["latest"]["requested_velocity"]["sequence"] == MAX_PUBLIC_INTEGER
    assert public["latest"]["planner"]["steps_gate_blocked"] == MAX_PUBLIC_INTEGER
    public_tracks = public["latest"]["tracks"]
    assert len(public_tracks) == MAX_DYNAMIC_TRACKS
    assert all(
        row["covariance_metadata"]
        == {"entry_count": MAX_TRACK_COVARIANCE_ENTRIES, "square_dimension": 6}
        for row in public_tracks
    )
    assert all("covariance" not in row["track"] for row in public_tracks)
    assert all("track_id" not in row["track"] for row in public_tracks)
    assert all("class_id" not in row["track"] for row in public_tracks)
    assert all("tracks" not in row for row in public["history"])
    assert all("track_counts" in row for row in public["history"])
    summary = public["history"][-1]
    assert set(summary) == {
        "record_schema",
        "sample_sequence",
        "navigation_generation",
        "observed_monotonic_s",
        "snapshot_missing",
        "snapshot_revision",
        "requested_velocity",
        "final_velocity",
        "achieved_velocity",
        "planner",
        "track_counts",
        "visibility_counts",
        "corridor_evidence",
        "decision",
    }
    assert summary["record_schema"] == "social_progress_summary_v1"
    assert set(summary["requested_velocity"]) == {"vx_mps", "vy_mps", "wz_radps"}
    assert set(summary["planner"]) == {
        "planner_healthy",
        "progress_demand",
        "body_is_still",
        "steps_gate_blocked",
        "steps_without_progress",
    }
    assert set(summary["decision"]) == {"state", "cause", "proposal"}
    assert public["latest"]["record_schema"] == "social_progress_latest_v1"
    assert [row["sample_sequence"] for row in public["history"]] == list(
        range(MAX_OBSERVER_HISTORY - MAX_PUBLIC_HISTORY_SUMMARIES + 1, MAX_OBSERVER_HISTORY + 1)
    )


def test_bound_check_is_structurally_before_sorting_and_corridor_traversal() -> None:
    source = MODULE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    observer_class = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "SocialProgressObserverV1"
    )
    observe = next(
        node
        for node in observer_class.body
        if isinstance(node, ast.FunctionDef) and node.name == "observe"
    )
    validate = next(
        node
        for node in observer_class.body
        if isinstance(node, ast.FunctionDef) and node.name == "_validated_observe_context"
    )
    rendered = ast.unparse(observe)
    validated = rendered.index("self._validated_observe_context")
    validate_rendered = ast.unparse(validate)
    public_integers = validate_rendered.index("_validate_snapshot_public_integers(snapshot)")
    nested_bounds = validate_rendered.index("self._validate_snapshot_bounds(snapshot)")
    assert public_integers < nested_bounds
    assert validated < rendered.index("self._derive_tracks")
    assert validated < rendered.index("self._derive_corridor_evidence")


def test_public_snapshot_only_visits_latest_and_bounded_reverse_slice() -> None:
    source = MODULE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    observer_class = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "SocialProgressObserverV1"
    )
    snapshot = next(
        node
        for node in observer_class.body
        if isinstance(node, ast.FunctionDef) and node.name == "snapshot"
    )
    rendered = ast.unparse(snapshot)
    assert "islice(reversed(self._history), MAX_PUBLIC_HISTORY_SUMMARIES)" in rendered
    assert "tuple(self._history)" not in rendered
    assert ".as_dict()" not in rendered


def test_track_churn_keeps_current_plus_retained_work_bounded() -> None:
    observer = _enabled()
    first_tracks = tuple(
        DynamicTrackV2(f"first-{index}", "person", 3.0, 0.0) for index in range(MAX_DYNAMIC_TRACKS)
    )
    second_tracks = tuple(
        DynamicTrackV2(f"second-{index}", "person", 3.0, 0.0) for index in range(MAX_DYNAMIC_TRACKS)
    )
    first = observer.observe(
        navigation_generation=1,
        now_monotonic_s=3.0,
        snapshot=_snapshot(3.0, tracks=first_tracks),
        planner=_planner(),
        **_velocities(3.0),
    )
    second = observer.observe(
        navigation_generation=1,
        now_monotonic_s=3.1,
        snapshot=_snapshot(3.1, revision=2, tracks=second_tracks),
        planner=_planner(),
        **_velocities(3.1),
    )
    assert first is not None and len(first.tracks) == MAX_DYNAMIC_TRACKS
    assert second is not None and len(second.tracks) == MAX_DYNAMIC_TRACKS
    assert len(observer._remembered_tracks) == MAX_DYNAMIC_TRACKS


def test_history_is_bounded_and_generation_change_resets_all_state() -> None:
    observer = _enabled(history_size=2)
    for sequence in range(1, 4):
        now = 4.0 + sequence / 10.0
        observer.observe(
            navigation_generation=7,
            now_monotonic_s=now,
            snapshot=_snapshot(now, revision=sequence, evidence_id=f"lidar-{sequence}"),
            planner=_planner(),
            **_velocities(now),
        )
    before = observer.snapshot()
    assert before["sample_count"] == 2
    assert [row["sample_sequence"] for row in before["history"]] == [2, 3]

    after_reset = observer.observe(
        navigation_generation=8,
        now_monotonic_s=5.0,
        snapshot=None,
        planner=_planner(),
        **_velocities(5.0),
    )
    assert after_reset is not None
    assert after_reset.sample_sequence == 1
    after = observer.snapshot()
    assert after["navigation_generation"] == 8
    assert after["sample_count"] == 1
    assert after["latest"]["snapshot_missing"] is True


def test_stale_achieved_feedback_is_preserved_and_fails_closed() -> None:
    observer = _enabled()
    sample = observer.observe(
        navigation_generation=1,
        now_monotonic_s=6.0,
        snapshot=_snapshot(6.0),
        planner=_planner(),
        **_velocities(6.0, achieved_vx=0.4, fresh=False),
    )
    assert sample is not None
    assert sample.achieved_velocity.primitive.vx_mps == 0.4
    assert sample.achieved_velocity.fresh is False
    assert sample.decision.state is SocialProgressStateV1.HOLD_UNCERTAIN
    assert sample.decision.cause is SocialBlockCauseV1.STALE_SENSOR


def test_planner_mapping_is_strict_and_no_path_is_unhealthy() -> None:
    facts = PlannerFactsV1.from_mapping(
        {
            "mission_status": "running",
            "route_status": "no_path",
            "body_is_still": True,
            "steps_gate_blocked": 1,
            "progress_demand": True,
            "paused": False,
            "has_mission": True,
            "steps_without_progress": 4,
            "terminal_verification_steps": 0,
        }
    )
    assert facts.planner_healthy is False
    with pytest.raises(ValueError, match="unknown planner fact"):
        PlannerFactsV1.from_mapping({"command_note": "obstacle_stop"})
