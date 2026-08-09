"""Perception-chain tier tests (Lane D, stratum 2, cards D-1 / D-6)."""

from __future__ import annotations

import math
import random

import pytest

from parcel_robot.detection_adapter.perception_chain import (
    D455_DEPTH_SIGMA_COEFF_PER_M,
    TIER_T0,
    TIER_T1,
    ConfidenceModel,
    NoiseTier,
    PerceptionChain,
    active_perception_chain,
    tier_t0,
    tier_t1,
    use_perception_chain,
)

_OBJECT = {
    "id": "bench_1",
    "label": "bench",
    "position": [2.0, 1.0, 0.0],
    "confidence": 0.98,
    "kind": "object",
    "source": "perception",
    "reachable": True,
    "metadata": {"radius_m": 0.7},
}
_REGION = {
    "id": "sidewalk",
    "label": "sidewalk",
    "polygon": [[-6.0, 2.4], [6.0, 2.4], [6.0, 3.6], [-6.0, 3.6]],
    "confidence": 0.98,
    "kind": "region",
    "source": "perception",
    "reachable": True,
    "metadata": {},
}


def _frame() -> list[dict]:
    return [dict(_OBJECT), dict(_REGION)]


# --- T0: the equality commitment -------------------------------------------


def test_t0_returns_the_callers_own_objects() -> None:
    """Not "equal to" — *the same objects*. That is what makes T0 exact."""

    chain = PerceptionChain(tier_t0())
    candidates = _frame()
    out = chain.process(candidates, robot_x=0.3, robot_y=-1.7, robot_yaw_rad=0.9)
    assert len(out) == len(candidates)
    for original, produced in zip(candidates, out, strict=True):
        assert produced is original


def test_t0_draws_no_random_numbers() -> None:
    """A tier that consumed RNG could shift any other seeded stream."""

    chain = PerceptionChain(tier_t0(), seed=17)
    before = chain._rng.getstate()
    for _ in range(50):
        chain.process(_frame(), robot_x=1.0, robot_y=2.0, robot_yaw_rad=0.4)
    assert chain._rng.getstate() == before


def test_t0_never_injects_a_false_positive() -> None:
    chain = PerceptionChain(tier_t0(), seed=5)
    for _ in range(500):
        out = chain.process(_frame(), robot_x=0.0, robot_y=0.0, robot_yaw_rad=0.0)
        assert len(out) == 2


def test_t0_still_validates_through_the_detector_contract() -> None:
    """The chain is authoritative even at T0: a row the contract rejects is gone."""

    chain = PerceptionChain(tier_t0())
    broken = [{"id": "x", "label": "", "position": [1.0, 1.0, 0.0], "kind": "object"}]
    assert chain.process(broken, robot_x=0.0, robot_y=0.0, robot_yaw_rad=0.0) == []


def test_a_passthrough_tier_may_not_carry_noise() -> None:
    with pytest.raises(ValueError, match="equality commitment"):
        NoiseTier(name="fake-T0", passthrough=True, dropout_near=0.1)
    with pytest.raises(ValueError, match="equality commitment"):
        NoiseTier(name="fake-T0", passthrough=True, false_positives_per_100_frames=1.0)


def test_the_process_default_chain_is_t0() -> None:
    use_perception_chain(None)
    try:
        assert active_perception_chain().tier.name == TIER_T0
        assert active_perception_chain().tier.passthrough is True
    finally:
        use_perception_chain(None)


# --- T1: the calibrated tier ------------------------------------------------


def test_t1_is_seeded_and_deterministic() -> None:
    a = PerceptionChain(tier_t1(), seed=99)
    b = PerceptionChain(tier_t1(), seed=99)
    for _ in range(30):
        left = a.process(_frame(), robot_x=0.0, robot_y=0.0, robot_yaw_rad=0.0)
        right = b.process(_frame(), robot_x=0.0, robot_y=0.0, robot_yaw_rad=0.0)
        assert left == right


def test_reset_restores_the_seeded_stream() -> None:
    chain = PerceptionChain(tier_t1(), seed=4)
    first = [
        chain.process(_frame(), robot_x=0.0, robot_y=0.0, robot_yaw_rad=0.0)
        for _ in range(20)
    ]
    chain.reset()
    second = [
        chain.process(_frame(), robot_x=0.0, robot_y=0.0, robot_yaw_rad=0.0)
        for _ in range(20)
    ]
    assert first == second


def test_t1_drops_detections_and_the_rate_tracks_range() -> None:
    near = _dropout_rate(range_m=1.0)
    mid = _dropout_rate(range_m=4.0)
    far = _dropout_rate(range_m=9.0)
    assert near < mid < far
    assert 0.05 < near < 0.16
    # Beyond the 8 m cutoff nothing survives at all.
    assert far == 1.0


def _dropout_rate(*, range_m: float, trials: int = 600) -> float:
    chain = PerceptionChain(tier_t1(), seed=1234)
    misses = 0
    for _ in range(trials):
        item = dict(_OBJECT)
        item["position"] = [range_m, 0.0, 0.0]
        out = chain.process([item], robot_x=0.0, robot_y=0.0, robot_yaw_rad=0.0)
        real = [row for row in out if not row.get("metadata", {}).get("false_positive")]
        if not real:
            misses += 1
    return misses / trials


def test_range_sigma_is_the_quadratic_d455_model() -> None:
    tier = tier_t1()
    assert tier.range_sigma_m(0.0) == 0.0
    assert tier.range_sigma_m(4.0) == pytest.approx(D455_DEPTH_SIGMA_COEFF_PER_M * 16.0)
    # Quadratic: doubling range quadruples sigma.
    assert tier.range_sigma_m(2.0) * 4.0 == pytest.approx(tier.range_sigma_m(4.0))


def test_t1_confidence_is_no_longer_the_literal() -> None:
    chain = PerceptionChain(tier_t1(), seed=8)
    scores = []
    for _ in range(400):
        for row in chain.process(_frame(), robot_x=0.0, robot_y=0.0, robot_yaw_rad=0.0):
            if not row.get("metadata", {}).get("false_positive"):
                scores.append(float(row["confidence"]))
    assert scores
    assert all(score != 0.98 for score in scores)
    mean = sum(scores) / len(scores)
    assert 0.6 < mean < 0.85


def test_tp_and_fp_distributions_actually_overlap() -> None:
    """If they did not overlap, no threshold would need calibrating."""

    model = ConfidenceModel()
    rng = random.Random(3)
    tp = [model.sample_true_positive(rng) for _ in range(4000)]
    fp = [model.sample_false_positive(rng) for _ in range(4000)]
    # Some false positives score above the true-positive mean, and some true
    # positives score below the false-positive mean.
    assert any(score > model.tp_mean for score in fp)
    assert any(score < model.fp_mean for score in tp)
    assert sum(tp) / len(tp) > sum(fp) / len(fp)


def test_temperature_widens_the_overlap() -> None:
    rng = random.Random(11)
    narrow = ConfidenceModel(temperature=0.5)
    wide = ConfidenceModel(temperature=2.0)
    spread_narrow = _spread([narrow.sample_true_positive(rng) for _ in range(3000)])
    spread_wide = _spread([wide.sample_true_positive(rng) for _ in range(3000)])
    assert spread_wide > spread_narrow


def _spread(values: list[float]) -> float:
    mean = sum(values) / len(values)
    return (sum((v - mean) ** 2 for v in values) / len(values)) ** 0.5


def test_t1_injects_false_positives_at_roughly_the_configured_rate() -> None:
    chain = PerceptionChain(tier_t1(), seed=21)
    frames = 4000
    phantom_frames = 0
    for _ in range(frames):
        out = chain.process(_frame(), robot_x=0.0, robot_y=0.0, robot_yaw_rad=0.0)
        if any(row.get("metadata", {}).get("false_positive") for row in out):
            phantom_frames += 1
    # 1.0 per 100 frames birth rate, each living ~4 frames, so the fraction of
    # frames containing a phantom is ~4 %. The band is wide on purpose: this
    # test pins the order of magnitude, not a tuned value.
    assert 0.01 < phantom_frames / frames < 0.12


def test_a_persistent_false_positive_holds_its_place() -> None:
    tier = NoiseTier(
        name="fp-stress",
        passthrough=False,
        range_cutoff_m=30.0,
        false_positives_per_100_frames=100.0,
        false_positive_persistence_frames=6.0,
    )
    chain = PerceptionChain(tier, seed=2)
    seen: dict[str, set[tuple[float, float]]] = {}
    for _ in range(40):
        for row in chain.process([], robot_x=0.0, robot_y=0.0, robot_yaw_rad=0.0):
            if not row.get("metadata", {}).get("false_positive"):
                continue
            position = (row["position"][0], row["position"][1])
            seen.setdefault(str(row["id"]), set()).add(position)
    assert seen, "the stress tier must produce phantoms"
    # A phantom never moves while it lives — that is what makes it trackable,
    # and therefore what makes the confidence threshold do any work.
    assert all(len(positions) == 1 for positions in seen.values())
    assert any(True for _ in seen)


def test_class_confusion_relabels_and_records_the_truth() -> None:
    chain = PerceptionChain(tier_t1(), seed=6)
    relabelled = 0
    for _ in range(600):
        item = dict(_OBJECT)
        item["label"] = "person"
        item["position"] = [1.0, 0.0, 0.0]
        for row in chain.process([item], robot_x=0.0, robot_y=0.0, robot_yaw_rad=0.0):
            if row.get("metadata", {}).get("false_positive"):
                continue
            if row["label"] != "person":
                relabelled += 1
                assert row["metadata"]["true_class"] == "person"
                assert row["metadata"]["detector_class"] == row["label"]
    assert relabelled > 0


def test_t1_moves_positions_but_not_far() -> None:
    chain = PerceptionChain(tier_t1(), seed=13)
    offsets = []
    for _ in range(400):
        for row in chain.process([dict(_OBJECT)], robot_x=0.0, robot_y=0.0, robot_yaw_rad=0.0):
            if row.get("metadata", {}).get("false_positive"):
                continue
            offsets.append(
                math.hypot(row["position"][0] - 2.0, row["position"][1] - 1.0)
            )
    assert offsets
    assert max(offsets) < 0.5
    assert sum(offsets) / len(offsets) > 0.0


def test_region_polygons_translate_with_their_centroid() -> None:
    chain = PerceptionChain(tier_t1(), seed=15)
    for _ in range(200):
        for row in chain.process([dict(_REGION)], robot_x=0.0, robot_y=0.0, robot_yaw_rad=0.0):
            if row.get("metadata", {}).get("false_positive") or row["kind"] != "region":
                continue
            polygon = row["polygon"]
            assert len(polygon) == 4
            width = polygon[1][0] - polygon[0][0]
            height = polygon[2][1] - polygon[1][1]
            # Rigid translation: the shape is preserved exactly.
            assert width == pytest.approx(12.0, abs=1e-9)
            assert height == pytest.approx(1.2, abs=1e-9)


# --- construction -----------------------------------------------------------


def test_from_tier_accepts_the_two_shipping_names() -> None:
    assert PerceptionChain.from_tier("t0").tier.name == TIER_T0
    assert PerceptionChain.from_tier("T1").tier.name == TIER_T1
    with pytest.raises(ValueError, match="unknown perception tier"):
        PerceptionChain.from_tier("T9")


def test_ipda_seam_is_declared_as_absent() -> None:
    assert tier_t0().existence_probability_source == "none"
    assert tier_t1().existence_probability_source == "none"
