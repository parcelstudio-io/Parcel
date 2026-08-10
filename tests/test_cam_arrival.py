"""Additive T-cam-arrival gates for Card V-A (pixel near-envelope metadata)."""

from __future__ import annotations

from evals.nav_instruct.cam_arrival import TIER_ID, evaluate_cells


def test_cam_arrival_pixel_candidate_carries_near_envelope() -> None:
    report = evaluate_cells()
    assert report["tier_id"] == TIER_ID
    assert report["candidate_source"] == "pixel_detector"
    assert report["pixel_source_tag"] is True
    assert report["envelope_matches_object_near_envelope_m"] is True
    assert report["stand_off_inside_planning_band"] is True
    assert abs(report["radius_m"] - report["expected_radius_m"]) < 1e-3
    assert report["radius_m"] > 0.2  # ~0.4 m sphere half-width at 3 m


def test_cam_arrival_report_is_deterministic() -> None:
    assert evaluate_cells() == evaluate_cells()
