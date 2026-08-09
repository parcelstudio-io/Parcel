"""VLFM-pattern value-map scorer stub for SearchEntity (rung 6 / headless).

Real VLFM (arXiv:2312.03275) builds a frontier value map from VLM scores.
This module ships a heuristic stand-in that implements ``FrontierScorer`` so
SearchEntity can swap scorers without changing the call site. Labeled
UNVERIFIED for real VLFM.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field

from parcel_robot.instructnav.search_entity import (
    SIDEWALK_BORDERS_ROAD_PRIORS,
    FrontierCandidate,
    semantic_prior_for_label,
)

DOES_NOT_PROVE = (
    (
        "HeuristicVLFMScorer is a headless value-map stand-in (label prior + "
        "radial bias); it does not prove VLFM VLM scoring, frontier value-map "
        "quality, or tier-C SearchEntity gains (HR-14)."
    ),
)


@dataclass(frozen=True, slots=True)
class ValueMapCell:
    """One cell in a coarse headless value map."""

    x: float
    y: float
    value: float
    label: str = ""

    def __post_init__(self) -> None:
        for name, value in (("x", self.x), ("y", self.y), ("value", self.value)):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"{name} must be numeric")
            if not math.isfinite(float(value)):
                raise ValueError(f"{name} must be finite")
        if not 0.0 <= float(self.value) <= 1.0:
            raise ValueError("value must be in [0, 1]")


@dataclass
class HeuristicValueMap:
    """Sparse value map queried by nearest cell (sim / headless)."""

    cells: tuple[ValueMapCell, ...] = ()
    default_value: float = 0.35
    radius_m: float = 2.5

    def __post_init__(self) -> None:
        if not isinstance(self.cells, tuple):
            raise TypeError("cells must be a tuple")
        for cell in self.cells:
            if not isinstance(cell, ValueMapCell):
                raise TypeError("cells must contain ValueMapCell")
        if not 0.0 <= self.default_value <= 1.0:
            raise ValueError("default_value must be in [0, 1]")
        if not math.isfinite(self.radius_m) or self.radius_m <= 0.0:
            raise ValueError("radius_m must be finite and positive")

    def value_at(self, x: float, y: float) -> float:
        if not self.cells:
            return float(self.default_value)
        best = None
        best_d = float("inf")
        for cell in self.cells:
            d = math.hypot(cell.x - x, cell.y - y)
            if d < best_d:
                best_d = d
                best = cell
        if best is None or best_d > self.radius_m:
            return float(self.default_value)
        return float(best.value)

    @classmethod
    def from_label_priors(
        cls,
        positions: Mapping[tuple[float, float], str],
        *,
        table: Mapping[str, float] | None = None,
        radius_m: float = 2.5,
        default_value: float = 0.35,
    ) -> HeuristicValueMap:
        cells = tuple(
            ValueMapCell(
                x=float(xy[0]),
                y=float(xy[1]),
                value=semantic_prior_for_label(label, table=table),
                label=str(label),
            )
            for xy, label in positions.items()
        )
        return cls(cells=cells, default_value=default_value, radius_m=radius_m)


@dataclass(frozen=True, slots=True)
class HeuristicVLFMScorer:
    """FrontierScorer: value_map(x,y) − travel_weight · geodesic (+ optional prior).

    Drop-in for ``select_frontier(..., scorer=...)``. Marked UNVERIFIED.
    """

    value_map: HeuristicValueMap = field(default_factory=HeuristicValueMap)
    travel_weight: float = 0.06
    map_weight: float = 1.0
    prior_blend: float = 0.25
    label: str = "UNVERIFIED_heuristic_vlfm"

    def __post_init__(self) -> None:
        if not isinstance(self.value_map, HeuristicValueMap):
            raise TypeError("value_map must be HeuristicValueMap")
        for name, value in (
            ("travel_weight", self.travel_weight),
            ("map_weight", self.map_weight),
            ("prior_blend", self.prior_blend),
        ):
            if not math.isfinite(value) or value < 0.0:
                raise ValueError(f"{name} must be finite and ≥ 0")
        if self.prior_blend > 1.0:
            raise ValueError("prior_blend must be ≤ 1")

    def score(self, candidate: FrontierCandidate) -> float:
        if not isinstance(candidate, FrontierCandidate):
            raise TypeError("candidate must be FrontierCandidate")
        map_v = self.value_map.value_at(candidate.x, candidate.y)
        # Blend authored semantic_prior when present (SearchEntity table path).
        prior = candidate.semantic_prior
        blended = (1.0 - self.prior_blend) * map_v + self.prior_blend * prior
        return (
            self.map_weight * blended
            + 0.0 * candidate.coverage_gain  # coverage reserved for later
            - self.travel_weight * candidate.geodesic_cost_m
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "label": self.label,
            "travel_weight": self.travel_weight,
            "map_weight": self.map_weight,
            "prior_blend": self.prior_blend,
            "cell_count": len(self.value_map.cells),
            "does_not_prove": list(DOES_NOT_PROVE),
            "unverified": True,
            "default_prior_table_keys": sorted(SIDEWALK_BORDERS_ROAD_PRIORS),
        }
