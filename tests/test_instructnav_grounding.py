"""Typed grounding outcomes (frustum → memory → UNSEEN)."""

from parcel_robot.instructnav.grounding import (
    GroundingOutcome,
    honest_not_found_reply,
    resolve_grounding,
)


def test_frustum_wins_over_memory():
    result = resolve_grounding(
        frustum=[{"id": "a", "confidence": 0.9}],
        memory=[{"id": "b", "confidence": 0.99}],
    )
    assert result.outcome == GroundingOutcome.RESOLVED
    assert result.candidate is not None
    assert result.candidate["id"] == "a"


def test_memory_hit_when_frustum_empty():
    result = resolve_grounding(
        frustum=[],
        memory=[{"id": "bench_1", "confidence": 0.7}],
    )
    assert result.outcome == GroundingOutcome.MEMORY_HIT


def test_ambiguous_and_unseen():
    amb = resolve_grounding(
        frustum=[
            {"id": "a", "confidence": 0.9},
            {"id": "b", "confidence": 0.88},
        ],
        memory=[],
    )
    assert amb.outcome == GroundingOutcome.AMBIGUOUS
    unseen = resolve_grounding(frustum=[], memory=[])
    assert unseen.outcome == GroundingOutcome.UNSEEN


def test_equal_confidence_prefers_clearly_nearer_candidate():
    result = resolve_grounding(
        frustum=[
            {"id": "near", "confidence": 0.98, "distance_m": 2.0},
            {"id": "far", "confidence": 0.98, "distance_m": 8.0},
        ],
        memory=[],
    )
    assert result.outcome == GroundingOutcome.RESOLVED
    assert result.candidate is not None
    assert result.candidate["id"] == "near"


def test_honest_reply_names_recovery():
    assert "looked around" in honest_not_found_reply("bench", scanned=True, searched=False)
    assert "searched" in honest_not_found_reply("bench", scanned=True, searched=True)
