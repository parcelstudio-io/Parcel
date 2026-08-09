"""K4 Sol: SemanticMemory2D decay/embeddings, Grounder v2, Scan, SearchEntity."""

from __future__ import annotations

import math

import pytest

from parcel_robot.contracts.v1 import (
    SCHEMA_VERSION,
    DetectionMsg,
    EvidenceEnvelopeV1,
    GoalRegionV1,
    PoseXYZYaw,
)
from parcel_robot.instructnav.grounding import (
    GrounderV2,
    GroundingOutcome,
    resolve_grounding,
)
from parcel_robot.instructnav.memory import SemanticMemory, SemanticMemory2D
from parcel_robot.instructnav.scan import (
    ScanRecoveryAction,
    full_turn_scan_spec,
    recovery_for_outcome,
    scan_stops,
)
from parcel_robot.instructnav.search_entity import (
    FrontierCandidate,
    SemanticMinusGeodesicScorer,
    ring_frontier_candidates,
    score_frontier,
    select_frontier,
    semantic_prior_for_label,
)
from parcel_robot.instructnav.siglip import SigLIP2Matcher


def _envelope(evidence_id: str = "det_1") -> EvidenceEnvelopeV1:
    return EvidenceEnvelopeV1(
        schema_version=SCHEMA_VERSION,
        evidence_id=evidence_id,
        source="test",
        source_timestamp_ns=1_000,
        received_monotonic_ns=1_000,
        sequence=1,
        frame_id="base_link",
        scene_revision=0,
        expires_monotonic_ns=1_000 + 200_000_000,
        calibration_id="test_cal",
        provenance=("unit",),
    )


# ---------------------------------------------------------------------------
# SemanticMemory2D
# ---------------------------------------------------------------------------


def test_semantic_memory_2d_alias_is_same_type():
    assert SemanticMemory is SemanticMemory2D


def test_memory_decay_half_life_and_no_compounding():
    mem = SemanticMemory2D(decay_half_life_s=100.0, min_confidence=0.01)
    mem.observe(
        [
            {
                "id": "bench_1",
                "label": "bench",
                "x": 1.0,
                "y": 2.0,
                "confidence": 1.0,
                "embedding": (1.0, 0.0, 0.0),
            }
        ],
        now_s=0.0,
    )
    at_half = mem.recall("bench", now_s=100.0)[0]
    assert at_half.confidence == pytest.approx(0.5)
    assert at_half.embedding == (1.0, 0.0, 0.0)
    # Second recall at same clock must not compound.
    again = mem.recall("bench", now_s=100.0)[0]
    assert again.confidence == pytest.approx(0.5)


def test_observe_detections_projects_bearing_range():
    mem = SemanticMemory2D()
    det = DetectionMsg(
        envelope=_envelope("e1"),
        class_id="lamppost",
        embedding=(0.1, 0.2, 0.3),
        bearing_rad=0.0,
        range_m=3.0,
        score=0.9,
        track_id="trk_1",
    )
    mem.observe_detections(
        [det],
        robot_x=0.0,
        robot_y=0.0,
        robot_yaw_rad=0.0,
        now_s=1.0,
    )
    hits = mem.recall("lamppost", now_s=1.0)
    assert len(hits) == 1
    assert hits[0].entity_id == "trk_1"
    assert hits[0].x == pytest.approx(3.0)
    assert hits[0].y == pytest.approx(0.0)
    assert hits[0].embedding == (0.1, 0.2, 0.3)


def test_observe_goal_region_rasterizes_channel():
    mem = SemanticMemory2D(region_resolution_m=1.0)
    goal = GoalRegionV1(
        goal_id="g1",
        source_task_id="t1",
        plan_step_id="s1",
        frame_id="map",
        acceptable_polygon=((0.0, 0.0), (2.0, 0.0), (2.0, 2.0), (0.0, 2.0)),
        preferred_pose=PoseXYZYaw(1.0, 1.0, 0.0, 0.0),
        approach_constraints=(),
        forbidden_regions=(),
        relation="inside",
        hold_duration_s=1.0,
        confidence=0.95,
        issued_at_monotonic_ns=1,
        expires_at_monotonic_ns=1_000_000,
        evidence_refs=(),
    )
    mem.observe_goal_region(goal, label="sidewalk", now_s=0.0)
    cells = mem.recall_region_cells("sidewalk", now_s=0.0)
    assert len(cells) >= 1
    assert mem.recall("sidewalk", now_s=0.0)[0].kind == "region"


# ---------------------------------------------------------------------------
# Grounder v2
# ---------------------------------------------------------------------------


def test_grounder_v2_resolved_from_detection():
    grounder = GrounderV2(matcher=SigLIP2Matcher(weights_dir="/nonexistent/siglip"))
    result = grounder.ground(
        "bench",
        detections=[
            {
                "id": "d1",
                "class_id": "bench",
                "score": 0.9,
                "bearing_rad": 0.1,
                "range_m": 2.0,
                "embedding": (1.0, 0.0),
            }
        ],
        memory=[],
        robot_xy=(0.0, 0.0),
    )
    assert result.outcome == GroundingOutcome.RESOLVED
    assert result.candidate is not None
    assert result.candidate["id"] == "d1"


def test_grounder_v2_memory_hit_and_unseen():
    grounder = GrounderV2(matcher=SigLIP2Matcher(weights_dir="/nonexistent/siglip"))
    mem_hit = grounder.ground(
        "tree",
        detections=[],
        memory=[{"id": "t1", "label": "tree", "confidence": 0.8, "x": 4.0, "y": 0.0}],
        robot_xy=(0.0, 0.0),
    )
    assert mem_hit.outcome == GroundingOutcome.MEMORY_HIT
    unseen = grounder.ground("hydrant", detections=[], memory=[])
    assert unseen.outcome == GroundingOutcome.UNSEEN


def test_grounder_v2_ambiguous_near_tie():
    grounder = GrounderV2(
        matcher=SigLIP2Matcher(weights_dir="/nonexistent/siglip"),
        ambiguity_margin=0.1,
        distance_ambiguity_m=1.0,
    )
    result = grounder.ground(
        "bench",
        detections=[
            {
                "id": "a",
                "class_id": "bench",
                "score": 0.9,
                "distance_m": 2.0,
                "embedding": (1.0,),
            },
            {
                "id": "b",
                "class_id": "bench",
                "score": 0.88,
                "distance_m": 2.2,
                "embedding": (1.0,),
            },
        ],
    )
    assert result.outcome == GroundingOutcome.AMBIGUOUS


def test_resolve_grounding_still_frustum_over_memory():
    result = resolve_grounding(
        frustum=[{"id": "live", "confidence": 0.7}],
        memory=[{"id": "mem", "confidence": 0.99}],
    )
    assert result.outcome == GroundingOutcome.RESOLVED
    assert result.candidate is not None
    assert result.candidate["id"] == "live"


# ---------------------------------------------------------------------------
# ScanBehavior
# ---------------------------------------------------------------------------


def test_full_turn_scan_stops_cover_circle():
    spec = full_turn_scan_spec(n_stops=8, dwell_s=0.2)
    stops = scan_stops(0.0, spec)
    assert len(stops) == 8
    assert stops[0].yaw_rad == pytest.approx(0.0)
    assert abs(stops[4].yaw_delta_from_start_rad - math.pi) < 1e-9
    step = spec.as_plan_step()
    assert step["skill"] == "ScanBehavior"
    assert step["arguments"]["populate_memory"] is True
    assert spec.estimated_duration_s() > 0.0


def test_recovery_ladder_unseen_scan_search_report():
    assert recovery_for_outcome(GroundingOutcome.UNSEEN) == ScanRecoveryAction.SCAN
    assert (
        recovery_for_outcome(GroundingOutcome.UNSEEN, already_scanned=True)
        == ScanRecoveryAction.SEARCH
    )
    assert (
        recovery_for_outcome(
            GroundingOutcome.UNSEEN, already_scanned=True, already_searched=True
        )
        == ScanRecoveryAction.REPORT
    )
    assert recovery_for_outcome(GroundingOutcome.AMBIGUOUS) == ScanRecoveryAction.CLARIFY
    assert recovery_for_outcome(GroundingOutcome.MEMORY_HIT) == ScanRecoveryAction.NAVIGATE


# ---------------------------------------------------------------------------
# SearchEntity
# ---------------------------------------------------------------------------


def test_semantic_prior_sidewalk_over_road():
    assert semantic_prior_for_label("sidewalk") > semantic_prior_for_label("road")
    assert semantic_prior_for_label("bench") == semantic_prior_for_label("sidewalk")


def test_frontier_score_prefers_high_prior_low_geodesic():
    near_sidewalk = FrontierCandidate(
        x=2.0, y=0.0, geodesic_cost_m=2.0, semantic_prior=0.95, candidate_id="a"
    )
    far_road = FrontierCandidate(
        x=10.0, y=0.0, geodesic_cost_m=10.0, semantic_prior=0.08, candidate_id="b"
    )
    scorer = SemanticMinusGeodesicScorer(travel_weight=0.06)
    assert score_frontier(near_sidewalk, scorer=scorer).score > score_frontier(
        far_road, scorer=scorer
    ).score
    chosen = select_frontier([far_road, near_sidewalk], scorer=scorer)
    assert chosen is not None
    assert chosen.candidate_id == "a"


def test_ring_frontier_injects_geodesic_and_drops_unreachable():
    def costs(xy: tuple[float, float]) -> float | None:
        if xy[0] < 0.0:
            return None
        return math.hypot(xy[0], xy[1])

    cands = ring_frontier_candidates(
        origin_xy=(0.0, 0.0),
        robot_xy=(0.0, 0.0),
        rings=1,
        bearings=4,
        ring_step_m=2.0,
        geodesic_cost_fn=costs,
        prior_fn=lambda xy: semantic_prior_for_label("sidewalk"),
        label="sidewalk",
    )
    assert cands
    assert all(c.geodesic_cost_m >= 0.0 for c in cands)
    assert all(c.x >= -1e-9 for c in cands)
    best = select_frontier(cands, travel_weight=0.1)
    assert best is not None
