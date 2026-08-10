"""SearchEntity frontier scoring interface (pure).

Hillclimb rung 4 / K4: generalize SearchOwner's frontier machinery without
editing SearchOwner. Score = semantic prior − geodesic cost; the scorer is
swappable (VLFM value map / C3 ValueMapFrontierScorer). Callers inject A*
geodesic costs. Semantic priors are sourced at PLAN TIME only (LGR pattern).
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

# Default sidewalk-borders-road prior table (sim-now; plan-time cache replaces
# in-loop model calls — C3 ValueMapFrontierScorer never invokes a runtime model).
SIDEWALK_BORDERS_ROAD_PRIORS: dict[str, float] = {
    "sidewalk": 0.95,
    "footway": 0.92,
    "crosswalk": 0.80,
    "crossing": 0.80,
    "curb": 0.55,
    "plaza": 0.50,
    "grass": 0.25,
    "road": 0.08,
    "driveway": 0.15,
    "parking": 0.12,
    "unknown": 0.35,
}


@dataclass(frozen=True)
class FrontierCandidate:
    """One search viewpoint / frontier cell."""

    x: float
    y: float
    geodesic_cost_m: float
    semantic_prior: float = 0.0
    coverage_gain: float = 0.0
    label: str = ""
    candidate_id: str = ""

    def __post_init__(self) -> None:
        if not all(
            math.isfinite(v)
            for v in (self.x, self.y, self.geodesic_cost_m, self.semantic_prior, self.coverage_gain)
        ):
            raise ValueError("frontier numeric fields must be finite")
        if self.geodesic_cost_m < 0.0:
            raise ValueError("geodesic_cost_m must be ≥ 0")
        if not 0.0 <= self.semantic_prior <= 1.0:
            raise ValueError("semantic_prior must be in [0, 1]")
        if not 0.0 <= self.coverage_gain <= 1.0:
            raise ValueError("coverage_gain must be in [0, 1]")


@dataclass(frozen=True)
class FrontierScore:
    candidate: FrontierCandidate
    score: float
    detail: str

    def as_dict(self) -> dict[str, object]:
        return {
            "x": self.candidate.x,
            "y": self.candidate.y,
            "geodesic_cost_m": self.candidate.geodesic_cost_m,
            "semantic_prior": self.candidate.semantic_prior,
            "coverage_gain": self.candidate.coverage_gain,
            "label": self.candidate.label,
            "candidate_id": self.candidate.candidate_id,
            "score": self.score,
            "detail": self.detail,
        }


@runtime_checkable
class FrontierScorer(Protocol):
    """Swappable frontier scorer (table now; VLFM value map later)."""

    def score(self, candidate: FrontierCandidate) -> float: ...


@dataclass(frozen=True)
class SemanticMinusGeodesicScorer:
    """score = prior_weight · semantic_prior − travel_weight · geodesic_cost.

    Optional coverage term mirrors SearchOwner's information-gain ranking.
    """

    travel_weight: float = 0.06
    prior_weight: float = 1.0
    coverage_weight: float = 0.0

    def __post_init__(self) -> None:
        for name, value in (
            ("travel_weight", self.travel_weight),
            ("prior_weight", self.prior_weight),
            ("coverage_weight", self.coverage_weight),
        ):
            if not math.isfinite(value) or value < 0.0:
                raise ValueError(f"{name} must be finite and ≥ 0")

    def score(self, candidate: FrontierCandidate) -> float:
        return (
            self.prior_weight * candidate.semantic_prior
            + self.coverage_weight * candidate.coverage_gain
            - self.travel_weight * candidate.geodesic_cost_m
        )


def semantic_prior_for_label(
    label: str,
    *,
    table: Mapping[str, float] | None = None,
    default: float = 0.35,
) -> float:
    """Lookup sidewalk-borders-road (or custom) prior for a class/region label."""

    key = " ".join(str(label).strip().lower().split())
    priors = table if table is not None else SIDEWALK_BORDERS_ROAD_PRIORS
    if not key:
        return float(default)
    if key in priors:
        return float(priors[key])
    # Soft synonym hooks (Grounder-adjacent; keep table small).
    synonyms = {
        "streetlight": "unknown",
        "lamppost": "unknown",
        "lamp": "unknown",
        "bench": "sidewalk",
        "planter": "sidewalk",
        "storefront": "sidewalk",
    }
    mapped = synonyms.get(key)
    if mapped is not None and mapped in priors:
        return float(priors[mapped])
    return float(default)


def score_frontier(
    candidate: FrontierCandidate,
    *,
    scorer: FrontierScorer | None = None,
    travel_weight: float = 0.06,
    prior_weight: float = 1.0,
    coverage_weight: float = 0.0,
) -> FrontierScore:
    """Score one frontier; default scorer is semantic prior − geodesic cost."""

    active = scorer or SemanticMinusGeodesicScorer(
        travel_weight=travel_weight,
        prior_weight=prior_weight,
        coverage_weight=coverage_weight,
    )
    value = float(active.score(candidate))
    return FrontierScore(
        candidate=candidate,
        score=value,
        detail="semantic_prior_minus_geodesic",
    )


def select_frontier(
    candidates: Sequence[FrontierCandidate],
    *,
    scorer: FrontierScorer | None = None,
    travel_weight: float = 0.06,
    prior_weight: float = 1.0,
    coverage_weight: float = 0.0,
    min_score: float | None = None,
) -> FrontierCandidate | None:
    """Pick the highest-scoring frontier; ties broken by candidate_id then (x,y)."""

    if not candidates:
        return None
    scored = [
        score_frontier(
            c,
            scorer=scorer,
            travel_weight=travel_weight,
            prior_weight=prior_weight,
            coverage_weight=coverage_weight,
        )
        for c in candidates
    ]
    scored.sort(
        key=lambda s: (
            -s.score,
            s.candidate.candidate_id,
            s.candidate.x,
            s.candidate.y,
        )
    )
    best = scored[0]
    if min_score is not None and best.score < min_score:
        return None
    return best.candidate


def ring_frontier_candidates(
    *,
    origin_xy: tuple[float, float],
    robot_xy: tuple[float, float],
    rings: int = 3,
    bearings: int = 12,
    ring_step_m: float = 2.0,
    max_radius_m: float | None = None,
    geodesic_cost_fn: Callable[[tuple[float, float]], float | None] | None = None,
    prior_fn: Callable[[tuple[float, float]], float] | None = None,
    coverage_fn: Callable[[tuple[float, float]], float] | None = None,
    label: str = "",
) -> tuple[FrontierCandidate, ...]:
    """Generate SearchOwner-style polar ring candidates (pure; costs injected).

    ``geodesic_cost_fn`` should return A* path length in metres, or ``None`` to
    drop unreachable cells. When omitted, Euclidean distance from the robot is
    used as a geodesic stand-in (announced via empty label prefix is avoided —
    callers that care should inject real costs).
    """

    if rings < 1 or bearings < 1:
        raise ValueError("rings and bearings must be ≥ 1")
    if not math.isfinite(ring_step_m) or ring_step_m <= 0.0:
        raise ValueError("ring_step_m must be finite and positive")
    ox, oy = float(origin_xy[0]), float(origin_xy[1])
    rx, ry = float(robot_xy[0]), float(robot_xy[1])
    if not all(math.isfinite(v) for v in (ox, oy, rx, ry)):
        raise ValueError("origin_xy and robot_xy must be finite")
    reach = max_radius_m if max_radius_m is not None else rings * ring_step_m
    if not math.isfinite(reach) or reach <= 0.0:
        raise ValueError("max_radius_m must be finite and positive")

    out: list[FrontierCandidate] = []
    index = 0
    for ring in range(1, rings + 1):
        radius = ring * ring_step_m
        if radius > reach + 1e-9:
            break
        for step in range(bearings):
            bearing = 2.0 * math.pi * step / bearings
            xy = (ox + math.cos(bearing) * radius, oy + math.sin(bearing) * radius)
            index += 1
            if geodesic_cost_fn is not None:
                cost = geodesic_cost_fn(xy)
                if cost is None:
                    continue
                geodesic = float(cost)
            else:
                geodesic = math.hypot(xy[0] - rx, xy[1] - ry)
            if not math.isfinite(geodesic) or geodesic < 0.0:
                continue
            prior = float(prior_fn(xy)) if prior_fn is not None else 0.35
            prior = max(0.0, min(1.0, prior))
            coverage = float(coverage_fn(xy)) if coverage_fn is not None else 0.0
            coverage = max(0.0, min(1.0, coverage))
            out.append(
                FrontierCandidate(
                    x=xy[0],
                    y=xy[1],
                    geodesic_cost_m=geodesic,
                    semantic_prior=prior,
                    coverage_gain=coverage,
                    label=label,
                    candidate_id=f"ring{ring}_b{step}",
                )
            )
    return tuple(out)


@dataclass(frozen=True)
class SearchEntityPlanSpec:
    """PlanIR-shaped SearchEntity step (skill name only; no brain import)."""

    skill: str = "SearchEntity"
    query: str = ""
    budget_s: float = 90.0
    plan_step_id: str = "search_entity"
    max_radius_m: float = 12.0
    rings: int = 3
    bearings: int = 12
    ring_step_m: float = 2.0
    travel_weight: float = 0.06

    def __post_init__(self) -> None:
        if self.skill != "SearchEntity":
            raise ValueError("SearchEntityPlanSpec.skill must be 'SearchEntity'")
        if not self.query.strip():
            raise ValueError("query must be non-empty")
        if not math.isfinite(self.budget_s) or self.budget_s <= 0.0:
            raise ValueError("budget_s must be finite and positive")
        if not math.isfinite(self.max_radius_m) or self.max_radius_m <= 0.0:
            raise ValueError("max_radius_m must be finite and positive")

    def as_plan_step(self) -> dict[str, object]:
        return {
            "step_id": self.plan_step_id,
            "skill": self.skill,
            "arguments": {
                "query": self.query,
                "budget_s": self.budget_s,
                "max_radius_m": self.max_radius_m,
                "rings": self.rings,
                "bearings": self.bearings,
                "ring_step_m": self.ring_step_m,
                "travel_weight": self.travel_weight,
            },
        }


# ---------------------------------------------------------------------------
# C3 — value-map FrontierScorer + plan-time prior (no runtime model calls)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PlanTimePriorCache:
    """Cached noun×region-class relevance scores (LGR: plan-time only).

    Built once when the SearchEntity plan step is authored. The 10 Hz control
    tick must only *read* this table — never call an LLM/SigLIP here.
    """

    query: str
    noun_region_scores: Mapping[str, float] = field(default_factory=dict)
    default: float = 0.35

    def __post_init__(self) -> None:
        if not str(self.query).strip():
            raise ValueError("query must be non-empty")
        if not 0.0 <= float(self.default) <= 1.0:
            raise ValueError("default must be in [0, 1]")
        for key, value in self.noun_region_scores.items():
            if not 0.0 <= float(value) <= 1.0:
                raise ValueError(f"prior for {key!r} must be in [0, 1]")

    def prior_for_region(self, region_class: str) -> float:
        key = " ".join(str(region_class).strip().lower().split())
        if key in self.noun_region_scores:
            return float(self.noun_region_scores[key])
        # Fall back to the sidewalk-borders-road table (still plan-time data).
        return semantic_prior_for_label(key, default=self.default)

    @classmethod
    def from_query_table(
        cls,
        query: str,
        *,
        table: Mapping[str, float] | None = None,
        default: float = 0.35,
    ) -> PlanTimePriorCache:
        """Freeze SIDEWALK_BORDERS_ROAD_PRIORS (or custom) at plan time."""

        source = dict(table if table is not None else SIDEWALK_BORDERS_ROAD_PRIORS)
        return cls(query=query, noun_region_scores=source, default=default)


@dataclass(frozen=True, slots=True)
class TargetExistenceBelief:
    """V_e — Gaussian target-existence belief over where the noun likely is."""

    mean_xy: tuple[float, float]
    variance_m2: float = 16.0
    peak: float = 1.0

    def __post_init__(self) -> None:
        if not all(math.isfinite(v) for v in self.mean_xy):
            raise ValueError("mean_xy must be finite")
        if not math.isfinite(self.variance_m2) or self.variance_m2 <= 0.0:
            raise ValueError("variance_m2 must be finite and positive")
        if not 0.0 <= self.peak <= 1.0:
            raise ValueError("peak must be in [0, 1]")

    def value_at(self, x: float, y: float) -> float:
        dx = float(x) - self.mean_xy[0]
        dy = float(y) - self.mean_xy[1]
        r2 = dx * dx + dy * dy
        return float(self.peak * math.exp(-0.5 * r2 / self.variance_m2))


@dataclass(frozen=True, slots=True)
class BeliefInheritance:
    """V_p — belief inheritance across scans (confidence-weighted map carry)."""

    weight: float = 0.35

    def __post_init__(self) -> None:
        if not math.isfinite(self.weight) or not 0.0 <= self.weight <= 1.0:
            raise ValueError("weight must be finite and in [0, 1]")

    def value(self, map_value: float, map_confidence: float) -> float:
        """Inherited belief rises with both fused value and observation weight."""

        conf_factor = min(1.0, max(0.0, float(map_confidence)))
        return self.weight * float(map_value) * conf_factor


@runtime_checkable
class ValueMapReader(Protocol):
    """Minimal read surface (SemanticValueMap2D or test double)."""

    resolution_m: float

    def read(self, cell: tuple[int, int]) -> tuple[float, float]: ...

    def unknown_fraction(self, region: Sequence[tuple[int, int]]) -> float: ...


@dataclass(frozen=True, slots=True)
class ValueMapFrontierScorer:
    """FrontierScorer: value-map + V_e + V_p − travel; plan-time prior blend.

    Drop-in for ``select_frontier(..., scorer=...)``. Zero runtime model calls —
    ``plan_prior`` and ``value_map`` are pre-populated / pure-math lookups.
    """

    value_map: ValueMapReader
    plan_prior: PlanTimePriorCache
    existence: TargetExistenceBelief | None = None
    inheritance: BeliefInheritance = field(default_factory=BeliefInheritance)
    travel_weight: float = 0.06
    map_weight: float = 1.0
    existence_weight: float = 0.55
    prior_blend: float = 0.25
    coverage_weight: float = 0.45
    sensor_radius_m: float = 3.0

    def __post_init__(self) -> None:
        for name, value in (
            ("travel_weight", self.travel_weight),
            ("map_weight", self.map_weight),
            ("existence_weight", self.existence_weight),
            ("prior_blend", self.prior_blend),
            ("coverage_weight", self.coverage_weight),
            ("sensor_radius_m", self.sensor_radius_m),
        ):
            if not math.isfinite(value) or value < 0.0:
                raise ValueError(f"{name} must be finite and ≥ 0")
        if self.prior_blend > 1.0:
            raise ValueError("prior_blend must be ≤ 1")

    def score(self, candidate: FrontierCandidate) -> float:
        if not isinstance(candidate, FrontierCandidate):
            raise TypeError("candidate must be FrontierCandidate")
        map_v, map_c = self._sample_map(candidate.x, candidate.y)
        v_p = self.inheritance.value(map_v, map_c)
        v_e = self.existence.value_at(candidate.x, candidate.y) if self.existence else 0.0
        # Plan-time prior for the queried noun × candidate label / region.
        plan_v = self.plan_prior.prior_for_region(candidate.label or "unknown")
        # Prefer authored candidate.semantic_prior when the ring builder stamped it.
        table_prior = candidate.semantic_prior if candidate.semantic_prior > 0.0 else plan_v
        blended_map = (1.0 - self.prior_blend) * map_v + self.prior_blend * table_prior
        coverage = candidate.coverage_gain
        if coverage <= 0.0:
            coverage = self._unknown_coverage(candidate.x, candidate.y)
        return (
            self.map_weight * blended_map
            + self.existence_weight * v_e
            + v_p
            + self.coverage_weight * coverage
            - self.travel_weight * candidate.geodesic_cost_m
        )

    def _sample_map(self, x: float, y: float) -> tuple[float, float]:
        res = float(self.value_map.resolution_m)
        cell = (math.floor(x / res), math.floor(y / res))
        return self.value_map.read(cell)

    def _unknown_coverage(self, x: float, y: float) -> float:
        """SearchOwner-style information gain via value-map unknown_fraction."""

        res = float(self.value_map.resolution_m)
        radius_cells = max(1, math.ceil(self.sensor_radius_m / res))
        cx = math.floor(x / res)
        cy = math.floor(y / res)
        cells = [
            (cx + dx, cy + dy)
            for dy in range(-radius_cells, radius_cells + 1)
            for dx in range(-radius_cells, radius_cells + 1)
            if dx * dx + dy * dy <= radius_cells * radius_cells
        ]
        if not cells:
            return 1.0
        try:
            return float(self.value_map.unknown_fraction(cells))
        except ValueError:
            return 1.0


@dataclass(frozen=True, slots=True)
class NearestFrontierScorer:
    """Baseline for Tier C: nearest reachable frontier (geodesic only)."""

    def score(self, candidate: FrontierCandidate) -> float:
        return -float(candidate.geodesic_cost_m)
