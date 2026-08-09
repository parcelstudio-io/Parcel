"""SearchEntity frontier scoring interface (pure).

Hillclimb rung 4 / K4: generalize SearchOwner's frontier machinery without
editing SearchOwner. Score = semantic prior − geodesic cost; the scorer is
swappable (VLFM value map later). Callers inject A* geodesic costs.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

# Default sidewalk-borders-road prior table (sim-now; VLFM replaces later).
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
