"""Habitat-style detection noise parameters (pure)."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field


DEFAULT_SIM_VOCABULARY = frozenset(
    {
        "person",
        "owner",
        "dog",
        "bicycle",
        "car",
        "truck",
        "bus",
        "traffic_cone",
        "bench",
        "chair",
        "table",
        "door",
        "storefront",
        "sign",
        "lamppost",
        "hydrant",
        "trash_can",
        "curb",
        "sidewalk",
        "crosswalk",
        "building",
        "plant",
        "unknown",
    }
)


def _finite_prob(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be numeric")
    number = float(value)
    if not math.isfinite(number) or not 0.0 <= number <= 1.0:
        raise ValueError(f"{name} must be in [0, 1]")
    return number


def _finite_nonneg(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be numeric")
    number = float(value)
    if not math.isfinite(number) or number < 0.0:
        raise ValueError(f"{name} must be a finite non-negative number")
    return number


@dataclass(frozen=True, slots=True)
class DetectionNoiseConfig:
    """Range cutoff, distance-dependent detect prob, confusion, and jitter.

    Mirrors Habitat / ObjectNav-style sensor noise so the stack is
    detector-shaped before pixels exist (hillclimb rung 7).
    """

    range_cutoff_m: float = 8.0
    p_detect_near: float = 0.95
    p_detect_far: float = 0.25
    p_detect_near_range_m: float = 1.5
    p_detect_far_range_m: float = 8.0
    bearing_jitter_std_rad: float = 0.04
    range_jitter_std_m: float = 0.12
    score_base: float = 0.85
    score_jitter_std: float = 0.05
    embedding_jitter_std: float = 0.02
    confusion: Mapping[str, Mapping[str, float]] = field(default_factory=dict)
    vocabulary: frozenset[str] = field(default_factory=lambda: DEFAULT_SIM_VOCABULARY)

    def __post_init__(self) -> None:
        _finite_nonneg(self.range_cutoff_m, "range_cutoff_m")
        if self.range_cutoff_m <= 0.0:
            raise ValueError("range_cutoff_m must be positive")
        _finite_prob(self.p_detect_near, "p_detect_near")
        _finite_prob(self.p_detect_far, "p_detect_far")
        near_r = _finite_nonneg(self.p_detect_near_range_m, "p_detect_near_range_m")
        far_r = _finite_nonneg(self.p_detect_far_range_m, "p_detect_far_range_m")
        if far_r <= near_r:
            raise ValueError("p_detect_far_range_m must exceed p_detect_near_range_m")
        for name, value in (
            ("bearing_jitter_std_rad", self.bearing_jitter_std_rad),
            ("range_jitter_std_m", self.range_jitter_std_m),
            ("score_jitter_std", self.score_jitter_std),
            ("embedding_jitter_std", self.embedding_jitter_std),
        ):
            _finite_nonneg(value, name)
        _finite_prob(self.score_base, "score_base")
        if not isinstance(self.confusion, Mapping):
            raise TypeError("confusion must be a mapping")
        frozen_conf: dict[str, dict[str, float]] = {}
        for true_cls, row in self.confusion.items():
            if not isinstance(true_cls, str) or not true_cls:
                raise ValueError("confusion keys must be non-empty class ids")
            if not isinstance(row, Mapping) or not row:
                raise ValueError(f"confusion[{true_cls!r}] must be a non-empty mapping")
            probs: dict[str, float] = {}
            total = 0.0
            for pred_cls, p in row.items():
                if not isinstance(pred_cls, str) or not pred_cls:
                    raise ValueError("confusion row keys must be non-empty class ids")
                prob = _finite_prob(p, f"confusion[{true_cls}][{pred_cls}]")
                probs[pred_cls] = prob
                total += prob
            if abs(total - 1.0) > 1e-6:
                raise ValueError(
                    f"confusion[{true_cls!r}] probabilities must sum to 1.0 (got {total})"
                )
            frozen_conf[true_cls] = probs
        object.__setattr__(self, "confusion", frozen_conf)
        if not isinstance(self.vocabulary, frozenset) or not self.vocabulary:
            raise ValueError("vocabulary must be a non-empty frozenset")
        for label in self.vocabulary:
            if not isinstance(label, str) or not label:
                raise ValueError("vocabulary entries must be non-empty strings")

    def p_detect(self, range_m: float) -> float:
        """Detection probability as a function of range (piecewise linear)."""

        distance = _finite_nonneg(range_m, "range_m")
        if distance > self.range_cutoff_m:
            return 0.0
        if distance <= self.p_detect_near_range_m:
            return self.p_detect_near
        if distance >= self.p_detect_far_range_m:
            return self.p_detect_far
        span = self.p_detect_far_range_m - self.p_detect_near_range_m
        t = (distance - self.p_detect_near_range_m) / span
        return self.p_detect_near + t * (self.p_detect_far - self.p_detect_near)


def default_person_confusion() -> dict[str, dict[str, float]]:
    """Mild person↔owner confusion for honest-sensor sims."""

    return {
        "person": {"person": 0.85, "owner": 0.10, "unknown": 0.05},
        "owner": {"owner": 0.80, "person": 0.15, "unknown": 0.05},
        "sign": {"sign": 0.90, "storefront": 0.07, "unknown": 0.03},
        "storefront": {"storefront": 0.88, "sign": 0.08, "building": 0.04},
    }
