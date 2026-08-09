"""Property tests for the classical tracker (Lane D, stratum 2, card D-2)."""

from __future__ import annotations

import itertools
import math
import random

import numpy as np
import pytest

from parcel_robot.navigation.tracker import (
    CHI2_2DOF_95,
    Detection,
    MultiObjectTracker,
    Track,
    TrackerConfig,
    TrackStatus,
    hungarian,
)

# --- the gate --------------------------------------------------------------


def test_gate_constant_is_the_published_chi2_value() -> None:
    assert CHI2_2DOF_95 == 5.991


def _distance_at_covariance(position_sigma: float, residual_m: float) -> float:
    tracker = MultiObjectTracker(TrackerConfig(measurement_sigma_m=1e-6))
    track = Track(
        track_id=1,
        mean=np.array([0.0, 0.0, 0.0, 0.0]),
        covariance=np.diag([position_sigma**2, position_sigma**2, 1.0, 1.0]),
    )
    det = Detection(x=residual_m, y=0.0)
    cov, inv = tracker._innovation(track, det)
    return tracker._mahalanobis2(track, det, cov, inv)


@pytest.mark.parametrize("residual", [0.1, 0.5, 1.0, 3.0])
def test_gate_is_monotone_decreasing_in_covariance(residual: float) -> None:
    """A less certain track accepts a fixed residual more readily, never less."""

    sigmas = [0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 4.0]
    distances = [_distance_at_covariance(s, residual) for s in sigmas]
    for previous, current in itertools.pairwise(distances):
        assert current < previous


def test_growing_covariance_actually_flips_the_gate() -> None:
    """Monotonicity would be vacuous if it never crossed the threshold."""

    tight = _distance_at_covariance(0.05, 1.0)
    loose = _distance_at_covariance(2.0, 1.0)
    assert tight > CHI2_2DOF_95 > loose


def test_gate_is_monotone_increasing_in_residual() -> None:
    residuals = [0.1, 0.3, 0.6, 1.0, 2.0]
    distances = [_distance_at_covariance(0.3, r) for r in residuals]
    for previous, current in itertools.pairwise(distances):
        assert current > previous


def test_singular_innovation_covariance_fails_closed() -> None:
    """A degenerate covariance must reject, never accept everything."""

    tracker = MultiObjectTracker(TrackerConfig(measurement_sigma_m=1e-9))
    track = Track(
        track_id=1,
        mean=np.array([0.0, 0.0, 0.0, 0.0]),
        covariance=np.zeros((4, 4)),
    )
    det = Detection(x=1.0, y=0.0)
    cov, inv = tracker._innovation(track, det)
    assert tracker._mahalanobis2(track, det, cov, inv) > CHI2_2DOF_95


# --- lifecycle -------------------------------------------------------------


def test_track_lifecycle_is_a_partition() -> None:
    """Every track is in exactly one status, and live/deleted never overlap."""

    tracker = MultiObjectTracker(TrackerConfig(confirm_hits=3, confirm_window=5, max_misses=5))
    rng = random.Random(7)
    seen_ids: set[int] = set()
    for frame in range(60):
        dets = []
        if frame % 7 != 3:  # occasional whole-frame dropout
            dets.append(Detection(x=0.1 * frame, y=0.0, label="bench", score=0.8))
        if 10 <= frame < 40:
            dets.append(Detection(x=5.0, y=0.2 * (frame - 10), label="person", score=0.7))
        if rng.random() < 0.1:
            dets.append(
                Detection(x=rng.uniform(-9, 9), y=rng.uniform(-9, 9), label="sign", score=0.5)
            )
        tracker.step(dets, dt_s=0.1)

        live = tracker.tracks
        live_ids = [t.track_id for t in live]
        assert len(live_ids) == len(set(live_ids)), "track ids must be unique"
        for track in live:
            assert track.status in {TrackStatus.TENTATIVE, TrackStatus.CONFIRMED}
        tentative_ids = {t.track_id for t in tracker.tentative}
        confirmed_ids = {t.track_id for t in tracker.confirmed}
        assert tentative_ids.isdisjoint(confirmed_ids)
        assert len(tracker.tentative) + len(tracker.confirmed) == len(live)
        for track in tracker.deleted:
            assert track.status is TrackStatus.DELETED
        assert set(live_ids).isdisjoint({t.track_id for t in tracker.deleted})
        seen_ids.update(live_ids)
    assert seen_ids, "the scenario must actually produce tracks"


def test_m_of_n_confirmation_needs_m_hits() -> None:
    tracker = MultiObjectTracker(TrackerConfig(confirm_hits=3, confirm_window=5))
    for frame in range(2):
        tracker.step([Detection(x=1.0, y=1.0, label="bench")], dt_s=0.1)
        assert not tracker.confirmed, f"confirmed too early at frame {frame}"
    tracker.step([Detection(x=1.0, y=1.0, label="bench")], dt_s=0.1)
    assert len(tracker.confirmed) == 1


def test_one_frame_hit_never_confirms_and_dies_on_the_miss_streak() -> None:
    tracker = MultiObjectTracker(TrackerConfig(confirm_hits=3, confirm_window=5, max_misses=5))
    tracker.step([Detection(x=2.0, y=2.0, label="sign")], dt_s=0.1)
    assert len(tracker.tracks) == 1
    assert not tracker.confirmed
    for _ in range(5):
        tracker.step([], dt_s=0.1)
    assert tracker.tracks == ()
    assert len(tracker.deleted) == 1
    assert tracker.deleted[-1].status is TrackStatus.DELETED


def test_a_confirmed_track_survives_a_gap_shorter_than_the_miss_streak() -> None:
    tracker = MultiObjectTracker(TrackerConfig(confirm_hits=3, confirm_window=5, max_misses=5))
    for _ in range(3):
        tracker.step([Detection(x=1.0, y=0.0, label="bench")], dt_s=0.1)
    assert len(tracker.confirmed) == 1
    original = tracker.confirmed[0].track_id
    for _ in range(4):
        tracker.step([], dt_s=0.1)
    assert len(tracker.tracks) == 1
    tracker.step([Detection(x=1.0, y=0.0, label="bench")], dt_s=0.1)
    assert tracker.tracks[0].track_id == original


# --- association -----------------------------------------------------------


def test_no_track_switch_when_two_targets_cross() -> None:
    """Two constant-velocity targets crossing must keep their identities.

    Nearest-neighbour-by-distance is the classic failure here: at the crossing
    the two detections are equidistant from both predictions, and a greedy
    match happily swaps them. The Kalman prediction plus a *global* assignment
    is what keeps them apart, and this test is the reason the assignment is
    global rather than greedy.
    """

    tracker = MultiObjectTracker(TrackerConfig(confirm_hits=3, confirm_window=5))
    dt = 0.1
    # A moves +x along y=0; B moves -x along y=0 — they meet at x=0.
    a0, b0 = -3.0, 3.0
    va, vb = 3.0, -3.0
    ids: dict[str, int] = {}
    for frame in range(61):
        t = frame * dt
        ax = a0 + va * t
        bx = b0 + vb * t
        dets = [
            Detection(x=ax, y=0.0, label="person", score=0.8, source_id="A"),
            Detection(x=bx, y=0.0, label="person", score=0.8, source_id="B"),
        ]
        tracker.step(dets, dt_s=dt)
        if frame == 20:  # well before the crossing; both confirmed
            assert len(tracker.confirmed) == 2
            for track in tracker.confirmed:
                key = "A" if track.mean[2] > 0 else "B"
                ids[key] = track.track_id
    assert set(ids) == {"A", "B"}
    # After the crossing, the track moving +x must still be the original A.
    final = {("A" if t.mean[2] > 0 else "B"): t.track_id for t in tracker.confirmed}
    assert final == ids, f"identity swapped across the crossing: {ids} -> {final}"


def test_out_of_gate_detections_start_new_tracks_instead_of_teleporting() -> None:
    tracker = MultiObjectTracker(TrackerConfig(confirm_hits=1, confirm_window=1))
    tracker.step([Detection(x=0.0, y=0.0, label="bench", sigma_m=0.05)], dt_s=0.1)
    first = tracker.tracks[0].track_id
    tracker.step([Detection(x=40.0, y=40.0, label="bench", sigma_m=0.05)], dt_s=0.1)
    ids = {t.track_id for t in tracker.tracks}
    assert first in ids and len(ids) == 2
    assert math.hypot(*tracker.track_by_id(first).position) < 1.0


def test_prediction_extrapolates_at_constant_velocity() -> None:
    tracker = MultiObjectTracker(TrackerConfig(confirm_hits=2, confirm_window=3))
    for frame in range(12):
        tracker.step([Detection(x=0.5 * frame * 0.1, y=0.0, label="person")], dt_s=0.1)
    track = tracker.confirmed[0]
    vx, _ = track.velocity
    assert vx == pytest.approx(0.5, abs=0.1)
    x_now, _ = track.position
    x_future, _ = track.predicted_position(2.0)
    assert x_future == pytest.approx(x_now + vx * 2.0, abs=1e-9)


# --- class evidence --------------------------------------------------------


def test_class_confusion_is_evidence_not_a_gate() -> None:
    """A body reported under two labels stays one track, and reports the split."""

    tracker = MultiObjectTracker(TrackerConfig(confirm_hits=3, confirm_window=5))
    labels = ["person", "person", "owner", "person", "owner", "person"]
    for label in labels:
        tracker.step([Detection(x=1.0, y=1.0, label=label, score=0.7)], dt_s=0.1)
    assert len(tracker.tracks) == 1
    track = tracker.tracks[0]
    assert track.dominant_label == "person"
    assert track.max_other_class_fraction == pytest.approx(2.0 / 6.0)
    assert track.mean_score == pytest.approx(0.7)


def test_unanimous_labels_report_zero_disagreement() -> None:
    tracker = MultiObjectTracker()
    for _ in range(5):
        tracker.step([Detection(x=0.0, y=0.0, label="bench", score=0.9)], dt_s=0.1)
    assert tracker.tracks[0].max_other_class_fraction == 0.0


# --- assignment ------------------------------------------------------------


def _brute_force_min_cost(matrix: np.ndarray) -> float:
    rows, cols = matrix.shape
    best = math.inf
    for size in range(min(rows, cols), -1, -1):
        for row_set in itertools.combinations(range(rows), size):
            for col_set in itertools.permutations(range(cols), size):
                total = sum(matrix[r, c] for r, c in zip(row_set, col_set, strict=True))
                if math.isfinite(total):
                    best = min(best, total)
        if math.isfinite(best):
            return best
    return best


@pytest.mark.parametrize("seed", range(25))
def test_hungarian_matches_brute_force_on_small_matrices(seed: int) -> None:
    rng = random.Random(seed)
    rows = rng.randint(1, 4)
    cols = rng.randint(1, 4)
    matrix = np.array(
        [[rng.uniform(0.0, 5.0) for _ in range(cols)] for _ in range(rows)],
        dtype=float,
    )
    pairs = hungarian(matrix)
    assert len(pairs) == min(rows, cols)
    assert len({r for r, _ in pairs}) == len(pairs)
    assert len({c for _, c in pairs}) == len(pairs)
    total = sum(matrix[r, c] for r, c in pairs)
    assert total == pytest.approx(_brute_force_min_cost(matrix), abs=1e-9)


def test_hungarian_never_returns_a_forbidden_pair() -> None:
    matrix = np.array([[1.0, math.inf], [math.inf, math.inf]], dtype=float)
    assert hungarian(matrix) == [(0, 0)]


def test_hungarian_handles_empty_and_all_forbidden() -> None:
    assert hungarian(np.zeros((0, 3))) == []
    assert hungarian(np.zeros((3, 0))) == []
    assert hungarian(np.full((2, 2), math.inf)) == []


# --- contract --------------------------------------------------------------


def test_config_rejects_impossible_m_of_n() -> None:
    with pytest.raises(ValueError):
        TrackerConfig(confirm_hits=6, confirm_window=5)


def test_detection_rejects_non_finite() -> None:
    with pytest.raises(ValueError):
        Detection(x=float("nan"), y=0.0)


def test_step_rejects_negative_dt() -> None:
    with pytest.raises(ValueError):
        MultiObjectTracker().step([], dt_s=-0.1)


def test_ipda_seam_is_present_and_unused() -> None:
    """The upgrade seam exists, is None, and nothing reads it."""

    tracker = MultiObjectTracker()
    tracker.step([Detection(x=0.0, y=0.0, label="bench")], dt_s=0.1)
    assert tracker.tracks[0].existence_probability is None


def test_track_cap_drops_tentative_before_confirmed() -> None:
    tracker = MultiObjectTracker(
        TrackerConfig(confirm_hits=2, confirm_window=3, max_tracks=8)
    )
    for _ in range(3):
        tracker.step(
            [Detection(x=float(i), y=0.0, label="bench", sigma_m=0.02) for i in range(4)],
            dt_s=0.1,
        )
    assert len(tracker.confirmed) == 4
    tracker.step(
        [Detection(x=float(i), y=0.0, label="bench", sigma_m=0.02) for i in range(4)]
        + [Detection(x=100.0 + i, y=100.0, label="sign", sigma_m=0.02) for i in range(20)],
        dt_s=0.1,
    )
    assert len(tracker.tracks) <= 8
    assert len(tracker.confirmed) == 4
