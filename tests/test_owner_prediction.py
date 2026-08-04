import math
import time

import pytest

from parcel_robot.navigation.owner_prediction import OwnerMotionPredictor


def _straight_sequence(predictor: OwnerMotionPredictor, count: int = 30) -> None:
    for index in range(count):
        now = index * 0.1
        predictor.observe(1.2 * now, 0.0, now_s=now)


def test_straight_line_endpoint_and_confidence() -> None:
    predictor = OwnerMotionPredictor()
    _straight_sequence(predictor)
    predicted = predictor.predict(now_s=2.9)
    assert predicted is not None
    assert len(predicted.points) == 25
    assert predicted.points[-1] == pytest.approx((1.2 * 5.4, 0.0), abs=0.15)
    assert predicted.speed_mps == pytest.approx(1.2, abs=0.05)
    assert predicted.heading_rad == pytest.approx(0.0, abs=0.02)
    assert predicted.confidence > 0.8


def test_turn_redirects_prediction_within_three_observations() -> None:
    predictor = OwnerMotionPredictor()
    _straight_sequence(predictor, count=20)
    corner_x = 1.2 * 1.9
    for offset in range(1, 4):
        now = 1.9 + offset * 0.1
        predictor.observe(corner_x, 1.2 * offset * 0.1, now_s=now)
    predicted = predictor.predict(now_s=2.2)
    assert predicted is not None
    dx = predicted.points[-1][0] - corner_x
    dy = predicted.points[-1][1] - 0.36
    assert dy > abs(dx)
    assert predicted.heading_rad > math.pi / 4


def test_teleport_reduces_confidence_and_raises_nis() -> None:
    predictor = OwnerMotionPredictor()
    _straight_sequence(predictor)
    predictor.observe(20.0, -15.0, now_s=3.0)
    predicted = predictor.predict(now_s=3.0)
    assert predicted is not None
    assert predictor.nis > 10.0
    assert predicted.confidence < 0.3


def test_staleness_and_invisible_observation() -> None:
    predictor = OwnerMotionPredictor()
    predictor.observe(1.0, 2.0, now_s=0.0)
    predictor.observe(100.0, 100.0, now_s=1.0, visible=False)
    predicted = predictor.predict(now_s=1.4)
    assert predicted is not None
    assert predicted.points[0] == pytest.approx((1.0, 2.0))
    assert predictor.predict(now_s=1.500001) is None


def test_reset_determinism_and_invalid_inputs() -> None:
    first = OwnerMotionPredictor()
    second = OwnerMotionPredictor()
    for predictor in (first, second):
        _straight_sequence(predictor, count=12)
    assert first.predict(now_s=1.1) == second.predict(now_s=1.1)
    first.reset()
    assert first.predict(now_s=2.0) is None
    with pytest.raises(ValueError):
        second.observe(math.nan, 0.0, now_s=1.2)
    with pytest.raises(ValueError):
        second.predict(now_s=math.inf)


def test_observe_predict_performance() -> None:
    predictor = OwnerMotionPredictor()
    predictor.observe(0.0, 0.0, now_s=0.0)
    started = time.perf_counter()
    count = 2_000
    for index in range(1, count + 1):
        now = index * 0.01
        predictor.observe(now, 0.0, now_s=now)
        predictor.predict(now_s=now)
    elapsed_per_pair = (time.perf_counter() - started) / count
    assert elapsed_per_pair < 0.0005


def test_predict_is_side_effect_free_across_cadences() -> None:
    sparse = OwnerMotionPredictor()
    dense = OwnerMotionPredictor()
    for index in range(20):
        now = index * 0.1
        sparse.observe(1.2 * now, 0.0, now_s=now)
        dense.observe(1.2 * now, 0.0, now_s=now)
        # Interleave predicts strictly between this observation and the next
        # so the monotonic clock guard never fires.
        if index < 19:
            for micro in range(1, 10):
                dense.predict(now_s=now + micro * 0.01)
    assert sparse.predict(now_s=1.9) == dense.predict(now_s=1.9)
    assert sparse.nis == dense.nis
    assert sparse._state is not None and dense._state is not None
    assert sparse._covariance is not None and dense._covariance is not None
    assert sparse._state == pytest.approx(dense._state)
    assert sparse._covariance == pytest.approx(dense._covariance)
