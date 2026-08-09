"""Arrival-evidence + false-positive-memory tests (Lane D, stratum 2, card D-3)."""

from __future__ import annotations

import pytest

from parcel_robot.authority import DEFAULT_STAND_OFF_ENVELOPE
from parcel_robot.instructnav.scoring import (
    ARRIVAL_CONFIRMING_FRAMES_M,
    ARRIVAL_CONFIRMING_WINDOW_N,
    ARRIVAL_MAX_OTHER_CLASS_FRACTION,
    ApproachVerifyState,
    ArrivalEvidence,
    FalsePositiveMemory,
    evidence_arrival_verified,
    objectnav_arrival_radius_m,
)


def _evidence(**overrides: object) -> ArrivalEvidence:
    base = {
        "frames_seen": 5,
        "cumulative_confidence": 5 * 0.8,
        "max_other_class": 0.0,
        "confirming_frames": 4,
        "visible": True,
    }
    base.update(overrides)
    return ArrivalEvidence(**base)  # type: ignore[arg-type]


# --- the predicate ----------------------------------------------------------


def test_a_single_high_confidence_frame_is_never_enough() -> None:
    """The exact defect the 0.98 literal hid: one frame satisfying arrival."""

    once = ArrivalEvidence(
        frames_seen=1, cumulative_confidence=0.98, confirming_frames=1, visible=True
    )
    verdict = evidence_arrival_verified(once, minimum_confidence=0.55)
    assert not verdict.verified
    assert verdict.state is ApproachVerifyState.VERIFY
    assert verdict.reason == "insufficient_confirming_frames"


def test_m_of_n_confirming_frames_is_the_gate() -> None:
    for hits in range(ARRIVAL_CONFIRMING_FRAMES_M):
        verdict = evidence_arrival_verified(
            _evidence(confirming_frames=hits), minimum_confidence=0.55
        )
        assert not verdict.verified, hits
    verdict = evidence_arrival_verified(
        _evidence(confirming_frames=ARRIVAL_CONFIRMING_FRAMES_M),
        minimum_confidence=0.55,
    )
    assert verdict.verified


def test_invisible_target_is_approach_not_verified() -> None:
    verdict = evidence_arrival_verified(_evidence(visible=False), minimum_confidence=0.55)
    assert verdict.state is ApproachVerifyState.APPROACH
    assert verdict.reason == "target_not_visible"


def test_mean_confidence_below_threshold_refuses() -> None:
    weak = _evidence(cumulative_confidence=5 * 0.40)
    assert not evidence_arrival_verified(weak, minimum_confidence=0.55).verified
    assert evidence_arrival_verified(weak, minimum_confidence=0.35).verified


def test_the_threshold_is_on_the_mean_not_the_last_frame() -> None:
    """Four bad frames and one great one must not clear a 0.55 threshold."""

    spiky = ArrivalEvidence(
        frames_seen=5,
        cumulative_confidence=0.1 + 0.1 + 0.1 + 0.1 + 0.99,
        confirming_frames=5,
        visible=True,
    )
    assert spiky.mean_confidence == pytest.approx(1.39 / 5.0)
    assert not evidence_arrival_verified(spiky, minimum_confidence=0.55).verified


def test_class_disagreement_is_the_only_rejection() -> None:
    disagreeing = _evidence(max_other_class=ARRIVAL_MAX_OTHER_CLASS_FRACTION + 0.01)
    verdict = evidence_arrival_verified(disagreeing, minimum_confidence=0.55)
    assert verdict.rejected
    assert verdict.state is ApproachVerifyState.REJECTED
    assert verdict.reason == "class_disagreement"
    # And it outranks everything else — a rejection is not "not yet".
    still_rejected = evidence_arrival_verified(
        _evidence(
            max_other_class=1.0, visible=False, confirming_frames=0, frames_seen=0
        ),
        minimum_confidence=0.0,
    )
    assert still_rejected.rejected


def test_agreeing_labels_at_the_boundary_are_accepted() -> None:
    verdict = evidence_arrival_verified(
        _evidence(max_other_class=ARRIVAL_MAX_OTHER_CLASS_FRACTION),
        minimum_confidence=0.55,
    )
    assert verdict.verified


def test_zero_frames_can_never_verify() -> None:
    empty = ArrivalEvidence()
    assert not evidence_arrival_verified(empty, minimum_confidence=0.0).verified


def test_verdict_serialises_every_field() -> None:
    payload = evidence_arrival_verified(_evidence(), minimum_confidence=0.55).as_dict()
    for key in (
        "state",
        "reason",
        "frames_seen",
        "cumulative_confidence",
        "mean_confidence",
        "max_other_class",
        "confirming_frames",
        "visible",
    ):
        assert key in payload


def test_predicate_rejects_impossible_arguments() -> None:
    with pytest.raises(ValueError):
        evidence_arrival_verified(_evidence(), minimum_confidence=1.5)
    with pytest.raises(ValueError):
        evidence_arrival_verified(_evidence(), minimum_confidence=0.5, confirming_frames_m=0)


def test_evidence_rejects_impossible_values() -> None:
    with pytest.raises(ValueError):
        ArrivalEvidence(frames_seen=-1)
    with pytest.raises(ValueError):
        ArrivalEvidence(max_other_class=1.5)
    with pytest.raises(ValueError):
        ArrivalEvidence(cumulative_confidence=-0.1)


def test_window_constant_matches_the_tracker() -> None:
    from parcel_robot.navigation.tracker import TrackerConfig

    config = TrackerConfig()
    assert config.confirm_hits == ARRIVAL_CONFIRMING_FRAMES_M
    assert config.confirm_window == ARRIVAL_CONFIRMING_WINDOW_N


# --- profile-derived arrival radius ----------------------------------------


def test_objectnav_radius_is_derived_from_the_envelope_not_written() -> None:
    assert objectnav_arrival_radius_m(0.0) == DEFAULT_STAND_OFF_ENVELOPE.vicinity_margin_m
    # The community criterion at Go2 scale is the familiar 1.0 m.
    assert objectnav_arrival_radius_m(0.0) == pytest.approx(1.0)
    assert objectnav_arrival_radius_m(0.7) == pytest.approx(1.7)
    with pytest.raises(ValueError):
        objectnav_arrival_radius_m(-1.0)


# --- false-positive memory --------------------------------------------------


def test_a_rejected_place_is_remembered_by_location_not_id() -> None:
    memory = FalsePositiveMemory()
    memory.reject(3.0, 4.0, "bench", reason="class_disagreement")
    # Same place, brand-new detection id: still refused.
    assert memory.is_rejected(3.05, 4.05, "bench")
    assert memory.is_rejected(3.0, 4.0, "BENCH")
    assert not memory.is_rejected(3.0, 4.0, "lamppost")


def test_rejection_survives_a_cell_boundary() -> None:
    memory = FalsePositiveMemory(cell_m=1.0)
    memory.reject(0.98, 0.98, "tree")
    # 4 cm across the boundary into the next cell.
    assert memory.is_rejected(1.02, 1.02, "tree")


def test_a_distant_instance_of_the_same_class_is_not_refused() -> None:
    memory = FalsePositiveMemory(cell_m=1.0)
    memory.reject(0.0, 0.0, "tree")
    assert not memory.is_rejected(10.0, 10.0, "tree")


def test_repeated_rejections_count_rather_than_duplicate() -> None:
    memory = FalsePositiveMemory()
    for _ in range(5):
        memory.reject(1.0, 1.0, "sign", reason="class_disagreement")
    assert len(memory) == 1
    assert memory.entries()[0]["count"] == 5


def test_memory_is_bounded_and_clearable() -> None:
    memory = FalsePositiveMemory(max_entries=4)
    for index in range(20):
        memory.reject(index * 10.0, 0.0, "sign")
    assert len(memory) == 4
    memory.clear()
    assert len(memory) == 0


def test_memory_rejects_a_non_finite_location() -> None:
    memory = FalsePositiveMemory()
    with pytest.raises(ValueError):
        memory.reject(float("nan"), 0.0, "bench")


def test_memory_construction_validates() -> None:
    with pytest.raises(ValueError):
        FalsePositiveMemory(cell_m=0.0)
    with pytest.raises(ValueError):
        FalsePositiveMemory(max_entries=0)
