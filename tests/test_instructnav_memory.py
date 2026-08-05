"""N-S2: SemanticMemory persistence, decay, forget, region channel."""

from __future__ import annotations

import pytest

from parcel_robot.instructnav.memory import SemanticMemory


def test_observe_once_recallable_after_leaving_frustum():
    mem = SemanticMemory(decay_half_life_s=600.0, min_confidence=0.05)
    mem.observe(
        [
            {
                "id": "bench_1",
                "label": "bench",
                "x": -2.5,
                "y": 3.0,
                "kind": "object",
                "confidence": 0.98,
            }
        ],
        now_s=0.0,
    )
    hits = mem.recall("bench", now_s=120.0)
    assert len(hits) == 1
    assert hits[0].entity_id == "bench_1"
    assert 0.05 < hits[0].confidence < 0.98


def test_decay_does_not_compound_across_recalls():
    mem = SemanticMemory(decay_half_life_s=600.0, min_confidence=0.05)
    mem.observe(
        [{"id": "bench_1", "label": "bench", "x": -2.5, "y": 3.0, "confidence": 0.98}],
        now_s=0.0,
    )
    mem.recall("bench", now_s=120.0)
    via_steps = mem.recall("bench", now_s=240.0)[0].confidence
    direct = SemanticMemory(decay_half_life_s=600.0, min_confidence=0.05)
    direct.observe(
        [{"id": "bench_1", "label": "bench", "x": -2.5, "y": 3.0, "confidence": 0.98}],
        now_s=0.0,
    )
    assert via_steps == pytest.approx(direct.recall("bench", now_s=240.0)[0].confidence)


def test_reobservation_refreshes_pose_and_confidence():
    mem = SemanticMemory(decay_half_life_s=60.0)
    mem.observe(
        [{"id": "lamp_1", "label": "lamppost", "x": 0.0, "y": 0.0, "confidence": 0.9}],
        now_s=0.0,
    )
    mem.observe(
        [{"id": "lamp_1", "label": "lamppost", "x": 1.0, "y": 2.0, "confidence": 0.95}],
        now_s=30.0,
    )
    hits = mem.recall("lamppost", now_s=30.0)
    assert hits[0].x == pytest.approx(1.0)
    assert hits[0].y == pytest.approx(2.0)
    assert hits[0].confidence == pytest.approx(0.95)


def test_forget_region_invalidates_stale_memory():
    mem = SemanticMemory()
    mem.observe(
        [{"id": "tree_1", "label": "tree", "x": 5.0, "y": 5.0, "confidence": 0.99}],
        now_s=0.0,
    )
    mem.forget_region(5.0, 5.0, 1.0, now_s=1.0)
    assert mem.recall("tree", now_s=1.0) == ()


def test_capacity_evicts_lowest_confidence_first():
    mem = SemanticMemory(capacity=2, decay_half_life_s=1e9)
    mem.observe(
        [
            {"id": "a", "label": "bench", "x": 0.0, "y": 0.0, "confidence": 0.2},
            {"id": "b", "label": "tree", "x": 1.0, "y": 0.0, "confidence": 0.9},
        ],
        now_s=0.0,
    )
    mem.observe(
        [{"id": "c", "label": "planter", "x": 2.0, "y": 0.0, "confidence": 0.8}],
        now_s=0.0,
    )
    ids = {e.entity_id for e in mem.recall_all(now_s=0.0)}
    assert "a" not in ids
    assert ids == {"b", "c"}


def test_region_channel_rasterizes_stuff_class():
    mem = SemanticMemory(region_resolution_m=1.0)
    mem.observe(
        [
            {
                "id": "sidewalk",
                "label": "sidewalk",
                "kind": "region",
                "polygon": [[0.0, 0.0], [3.0, 0.0], [3.0, 2.0], [0.0, 2.0]],
                "confidence": 0.98,
            }
        ],
        now_s=0.0,
    )
    cells = mem.recall_region_cells("sidewalk", now_s=0.0)
    assert len(cells) >= 2
    snap = mem.region_channel_snapshot(now_s=0.0)
    assert snap["resolution_m"] == pytest.approx(1.0)
    assert snap["cells"]
