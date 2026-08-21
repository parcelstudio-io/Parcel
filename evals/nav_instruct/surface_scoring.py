"""Per-class perception scoring against the surface convention (card PG-2).

WHAT THIS REPLACES
------------------
Grading a perception answer by its distance to a geom **centre**. The
2026-08-21 mapping bench (`scrum/20260821/perception/bench_mapping.md`) built a
semantic map from 120 rendered RGB-D frames and measured building entries at
**1–3 cm from the visible facade and 1.2–1.7 m from the geom centre, 6/6 in the
oracle arm and 5/6 in the open-vocab arm**. A depth camera sees surfaces and
never centroids, so centre-grading marks a correct pipeline wrong. This module
scores against `scene_truth.json`'s ``surfaces`` section instead.

THE NULL CONTROL IS NOT DECORATION
----------------------------------
The same bench disclosed a flaw in its own metric: containment scoring is
**uninformative for large regions**. Asked "is some map entry on the sidewalk",
a map whose entries were re-scattered *uniformly at random* also scored
**0.00 m — p=1.00 for sidewalk, p=0.52 for crosswalk**. Two of eight queries
beat chance; the pre-registered scoring had said GO.

So this module makes the null control **structural rather than optional**:

* :class:`LocalizationClaim` cannot be constructed without a
  :class:`NullControl`. It is a required field with no default, and
  ``__post_init__`` re-checks its type and its draw count.
* :attr:`LocalizationClaim.verdict` is a *property*, not a stored field, so a
  caller cannot write ``verdict="pass"`` over a claim that did not beat chance.
* A statistic that passes but does not beat the null returns
  :data:`VERDICT_UNINFORMATIVE` — explicitly **not** a pass. That is the honest
  reading of sidewalk-scores-0.00-against-random, and it is the verdict the
  bench's own numbers should have carried.

THE TWO MEASURES, AND WHERE THEY COME FROM
------------------------------------------
Which class is measured how is NOT decided here. It is read from
:func:`parcel_robot.navigation.arrival_semantics.localization_target`, the table
that already owns what arrival means per class, and it is recorded per entity in
the answer key so a scorer never has to re-derive it.

``surface`` (near-class: object, portal, person, unknown)
    ``surface_error_m`` = the smallest unsigned distance from the answer point
    to any part's footprint **outline**. Unsigned on purpose: a point buried
    inside a solid is as wrong as one floating outside it, because no depth ray
    could have produced either. Passes at
    :data:`SURFACE_BUDGET_M`, which is the repo's own
    ``RECOGNITION_LOCALIZATION_BUDGET_M`` imported rather than re-typed.

``interior`` (inside-class: region)
    Containment of the answer point — the existing R10 arrival predicate,
    unchanged — **plus** ``evidence_inside_fraction``: the fraction of the
    answering entry's own supporting points that lie in the region. The second
    term is what a random map cannot pass. A random point is inside the sidewalk
    with probability equal to its area share (~22% of the bench's mapped box),
    so a *point* answer can never be evidence for a large region; a *population*
    answer can, because the null distribution of a fraction over thousands of
    points concentrates tightly on that area share.

WHAT THIS MODULE DOES NOT DO
----------------------------
It does not plan, and nothing on the robot's control path imports it. Changing
what a measurement is compared against must never change where the robot goes:
``near`` goal regions are still built by
``instructnav.scoring.object_near_goal_region`` from centre + radius, and
``inside`` goal regions are still the region polygon.

Pure stdlib by choice — no numpy — so the scorer is cheap to run, deterministic
given a seed, and testable in the commit tier.
"""

from __future__ import annotations

import math
import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from evals.nav_instruct.cam_detector import RECOGNITION_LOCALIZATION_BUDGET_M
from parcel_robot.navigation.arrival_semantics import (
    LOCALIZATION_INTERIOR,
    LOCALIZATION_SURFACE,
    LOCALIZATION_TARGETS,
)

__all__ = [
    "DIRECTION_HIGHER_IS_BETTER",
    "DIRECTION_LOWER_IS_BETTER",
    "MIN_NULL_DRAWS",
    "NULL_ALPHA",
    "NULL_DRAWS",
    "NULL_EVIDENCE_CAP",
    "NULL_SEED",
    "REGION_EVIDENCE_MAJORITY",
    "SURFACE_BUDGET_M",
    "VERDICT_FAIL",
    "VERDICT_PASS",
    "VERDICT_UNINFORMATIVE",
    "LocalizationClaim",
    "MappedArea",
    "NullControl",
    "evidence_inside_fraction",
    "facade_faces",
    "inside_any",
    "interior_contains",
    "interior_polygons",
    "score_inside_class",
    "score_localization",
    "score_near_class",
    "surface_error_m",
    "visible_facade",
]

#: The pass budget for a ``surface`` measurement. DERIVED, never re-spelled:
#: this is the same 0.30 m recognition-localization budget
#: ``evals/nav_instruct/cam_detector.py`` already grades OWLv2 against, so the
#: two cells cannot come to disagree about what "localized" means.
SURFACE_BUDGET_M: float = RECOGNITION_LOCALIZATION_BUDGET_M

#: The ``interior`` evidence floor. A bare MAJORITY — more of the answering
#: entry's evidence inside the region than outside it. Deliberately not a tuned
#: number: a tuned threshold fitted on this scene would be exactly the kind of
#: metric the bench caught, one that looks decisive and measures nothing. The
#: discrimination comes from the null control, which is why the null is required
#: and this floor is only the coarse sanity half.
REGION_EVIDENCE_MAJORITY: float = 0.5

#: Null-control draw count. 500 is the bench's own figure, kept so the two sets
#: of p-values are directly comparable.
NULL_DRAWS: int = 500

#: Floor on draws. Below this a p-value has no resolution worth reporting: at
#: 200 draws the smallest distinguishable p is 0.005, an order of magnitude
#: under :data:`NULL_ALPHA`.
MIN_NULL_DRAWS: int = 200

#: Significance level. 0.05, the bench's, so "beats null" means the same thing
#: in both places.
NULL_ALPHA: float = 0.05

#: Default RNG seed, so a re-run reproduces the same p-values byte for byte.
NULL_SEED: int = 20260821

#: Cap on how many points one null draw re-scatters for an ``interior`` claim.
#: A map entry can own tens of thousands of points and 500 x that is slow in
#: pure Python. Scattering FEWER points than were observed widens the null's
#: spread, which can only make the null look better and the p-value larger — the
#: cap is therefore conservative, never flattering. The observed statistic
#: always uses every point.
NULL_EVIDENCE_CAP: int = 1000

DIRECTION_LOWER_IS_BETTER = "lower_is_better"
DIRECTION_HIGHER_IS_BETTER = "higher_is_better"

VERDICT_PASS = "pass"
VERDICT_FAIL = "fail"
VERDICT_UNINFORMATIVE = "uninformative"


class SurfaceScoringError(ValueError):
    """A claim that cannot be scored honestly. Never downgraded to a warning."""


# ---------------------------------------------------------------------------
# geometry — footprint primitives
# ---------------------------------------------------------------------------


def _xy(point: Any) -> tuple[float, float]:
    try:
        x, y = float(point[0]), float(point[1])
    except (TypeError, IndexError, ValueError) as error:
        raise SurfaceScoringError(f"not an (x, y) point: {point!r}") from error
    if not (math.isfinite(x) and math.isfinite(y)):
        raise SurfaceScoringError(f"point is not finite: {point!r}")
    return x, y


def _segment_distance(
    point: tuple[float, float],
    start: tuple[float, float],
    end: tuple[float, float],
) -> float:
    px, py = point
    ax, ay = start
    bx, by = end
    dx, dy = bx - ax, by - ay
    length_sq = dx * dx + dy * dy
    if length_sq <= 0.0:
        return math.hypot(px - ax, py - ay)
    t = ((px - ax) * dx + (py - ay) * dy) / length_sq
    t = 0.0 if t < 0.0 else (min(t, 1.0))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def polygon_boundary_distance(
    point: Any, polygon: Sequence[Sequence[float]]
) -> float:
    """Unsigned distance from ``point`` to a closed polygon's OUTLINE.

    Not "0 if inside". The outline is the surface; a point inside the solid did
    not come off it either.
    """

    ring = [_xy(vertex) for vertex in polygon]
    if len(ring) < 3:
        raise SurfaceScoringError(f"polygon needs >= 3 vertices, got {len(ring)}")
    target = _xy(point)
    return min(
        _segment_distance(target, ring[index], ring[(index + 1) % len(ring)])
        for index in range(len(ring))
    )


def polygon_contains(point: Any, polygon: Sequence[Sequence[float]]) -> bool:
    """Even-odd ray cast. Same predicate ``city_semantics._inside`` uses."""

    ring = [_xy(vertex) for vertex in polygon]
    if len(ring) < 3:
        raise SurfaceScoringError(f"polygon needs >= 3 vertices, got {len(ring)}")
    x, y = _xy(point)
    inside = False
    previous = ring[-1]
    for current in ring:
        x1, y1 = previous
        x2, y2 = current
        if (y1 > y) != (y2 > y):
            intersection = (x2 - x1) * (y - y1) / (y2 - y1) + x1
            if x < intersection:
                inside = not inside
        previous = current
    return inside


def _part_surface_distance(point: tuple[float, float], part: Mapping[str, Any]) -> float:
    shape = str(part.get("shape", ""))
    if shape == "rect":
        return polygon_boundary_distance(point, part["polygon"])
    if shape == "circle":
        centre = _xy(part["center"])
        radius = float(part["radius_m"])
        if not math.isfinite(radius) or radius < 0.0:
            raise SurfaceScoringError(f"circle part has bad radius: {part!r}")
        return abs(math.hypot(point[0] - centre[0], point[1] - centre[1]) - radius)
    raise SurfaceScoringError(
        f"unknown footprint shape {shape!r}; the convention is closed, so a new "
        f"primitive needs a deliberate rule rather than a fallback"
    )


def _require_measure(surface: Mapping[str, Any], expected: str) -> None:
    measure = str(surface.get("measure", ""))
    if measure not in LOCALIZATION_TARGETS:
        raise SurfaceScoringError(
            f"surface record declares measure {measure!r}, which is not one of "
            f"{sorted(LOCALIZATION_TARGETS)}"
        )
    if measure != expected:
        raise SurfaceScoringError(
            f"surface record is measured by {measure!r}, not {expected!r}; "
            f"routing it here would grade it by the wrong rule"
        )


def surface_error_m(point: Any, surface: Mapping[str, Any]) -> float:
    """Distance from an answer point to the entity's nearest measurable surface.

    ``min`` over the nearest-surface set: a depth ray hits whichever part faces
    the robot, so the bench's four separate box geoms are four candidate
    surfaces and the closest one is the one that was seen.
    """

    _require_measure(surface, LOCALIZATION_SURFACE)
    parts = surface.get("parts") or ()
    if not parts:
        raise SurfaceScoringError("surface record carries no parts to measure against")
    target = _xy(point)
    return min(_part_surface_distance(target, part) for part in parts)


def interior_contains(point: Any, surface: Mapping[str, Any]) -> bool:
    """Is the answer point inside the region? The unchanged R10 predicate."""

    _require_measure(surface, LOCALIZATION_INTERIOR)
    return polygon_contains(point, surface["interior_polygon"])


def interior_polygons(
    surface: Mapping[str, Any],
    also_satisfied_by: Sequence[Mapping[str, Any]] = (),
) -> list[Sequence[Sequence[float]]]:
    """The polygons a query naming this class would accept, validated."""

    _require_measure(surface, LOCALIZATION_INTERIOR)
    for other in also_satisfied_by:
        _require_measure(other, LOCALIZATION_INTERIOR)
    return [surface["interior_polygon"]] + [
        other["interior_polygon"] for other in also_satisfied_by
    ]


def inside_any(point: Any, polygons: Sequence[Sequence[Sequence[float]]]) -> bool:
    """Containment in ANY accepted instance. "The sidewalk" is two strips."""

    return any(polygon_contains(point, polygon) for polygon in polygons)


def evidence_inside_fraction(
    points: Sequence[Any],
    surface: Mapping[str, Any],
    *,
    also_satisfied_by: Sequence[Mapping[str, Any]] = (),
) -> float:
    """Fraction of an entry's supporting points that lie in the region.

    The discriminating half of the ``interior`` rule, and the ONE definition of
    it: :func:`score_inside_class` calls this rather than recomputing the same
    sum, so the statistic a claim reports and the statistic a caller can measure
    by hand cannot come apart.

    An empty evidence set scores 0.0 — "no evidence" is not "perfect evidence".
    """

    polygons = interior_polygons(surface, also_satisfied_by)
    total = len(points)
    if total == 0:
        return 0.0
    return sum(1 for point in points if inside_any(point, polygons)) / total


# ---------------------------------------------------------------------------
# facades — which surface an observer can actually see
# ---------------------------------------------------------------------------


def facade_faces(surface: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Every straight face of every rect part, with its outward normal.

    Circle parts have no faces (a cylinder's facade is wherever you stand), so
    they are absent from this list by construction rather than by omission.
    """

    _require_measure(surface, LOCALIZATION_SURFACE)
    faces: list[dict[str, Any]] = []
    for part in surface.get("parts") or ():
        if str(part.get("shape", "")) != "rect":
            continue
        ring = [_xy(vertex) for vertex in part["polygon"]]
        centre = (
            sum(v[0] for v in ring) / len(ring),
            sum(v[1] for v in ring) / len(ring),
        )
        for index, start in enumerate(ring):
            end = ring[(index + 1) % len(ring)]
            mid = ((start[0] + end[0]) / 2.0, (start[1] + end[1]) / 2.0)
            outward = (mid[0] - centre[0], mid[1] - centre[1])
            norm = math.hypot(*outward)
            if norm <= 0.0:
                continue
            faces.append(
                {
                    "geom": part.get("geom"),
                    "start": start,
                    "end": end,
                    "midpoint": mid,
                    "normal": (outward[0] / norm, outward[1] / norm),
                }
            )
    return faces


def visible_facade(surface: Mapping[str, Any], observer_xy: Any) -> list[dict[str, Any]]:
    """The faces an observer at ``observer_xy`` can see: outward normal toward them.

    This is what "the facade" means operationally — not a stored polygon but the
    subset of the surface that faces the robot from where it stands. The bench's
    building entries land on exactly this subset, which is why they read as
    1–3 cm errors under the surface convention and 1.2–1.7 m under the old one.
    """

    observer = _xy(observer_xy)
    seen: list[dict[str, Any]] = []
    for face in facade_faces(surface):
        mid = face["midpoint"]
        normal = face["normal"]
        to_observer = (observer[0] - mid[0], observer[1] - mid[1])
        if normal[0] * to_observer[0] + normal[1] * to_observer[1] > 0.0:
            seen.append(face)
    return seen


# ---------------------------------------------------------------------------
# the mapped area a null control re-scatters into
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MappedArea:
    """The region a null control re-scatters into: the area actually mapped.

    Explicit and required, never inferred: "random" is meaningless without
    saying random *where*, and quietly widening the area is the easiest way to
    make a null control flattering.
    """

    min_xy: tuple[float, float]
    max_xy: tuple[float, float]

    def __post_init__(self) -> None:
        low = _xy(self.min_xy)
        high = _xy(self.max_xy)
        if not (high[0] > low[0] and high[1] > low[1]):
            raise SurfaceScoringError(
                f"mapped area has no extent: {self.min_xy} .. {self.max_xy}"
            )
        object.__setattr__(self, "min_xy", low)
        object.__setattr__(self, "max_xy", high)

    @property
    def area_m2(self) -> float:
        return (self.max_xy[0] - self.min_xy[0]) * (self.max_xy[1] - self.min_xy[1])

    def sample(self, rng: random.Random) -> tuple[float, float]:
        return (
            rng.uniform(self.min_xy[0], self.max_xy[0]),
            rng.uniform(self.min_xy[1], self.max_xy[1]),
        )

    @classmethod
    def from_points(cls, points: Sequence[Any]) -> MappedArea:
        """Bounding box of the mapped points — the bench's own null area."""

        rows = [_xy(point) for point in points]
        if not rows:
            raise SurfaceScoringError("cannot build a mapped area from no points")
        return cls(
            min_xy=(min(r[0] for r in rows), min(r[1] for r in rows)),
            max_xy=(max(r[0] for r in rows), max(r[1] for r in rows)),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "min_xy": list(self.min_xy),
            "max_xy": list(self.max_xy),
            "area_m2": round(self.area_m2, 4),
        }


# ---------------------------------------------------------------------------
# the null control and the claim it is welded to
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NullControl:
    """What the same measurement scores when the map is replaced by chance."""

    statistic: str
    direction: str
    observed: float
    draws: int
    seed: int
    #: Number of null draws that did AT LEAST AS WELL as the real map.
    at_least_as_good: int
    null_median: float
    #: The null's 5th percentile when lower is better, 95th when higher is.
    null_tail: float
    area: MappedArea
    alpha: float = NULL_ALPHA
    #: What was re-scattered, and how many of it. Denominators travel with the
    #: number so a reader never has to guess the population.
    population: str = ""
    population_size: int = 0

    def __post_init__(self) -> None:
        if self.direction not in {DIRECTION_LOWER_IS_BETTER, DIRECTION_HIGHER_IS_BETTER}:
            raise SurfaceScoringError(f"unknown null direction {self.direction!r}")
        if self.draws < MIN_NULL_DRAWS:
            raise SurfaceScoringError(
                f"null control ran {self.draws} draws, below the {MIN_NULL_DRAWS} "
                f"floor; a p-value at that resolution is not a result"
            )
        if not 0 <= self.at_least_as_good <= self.draws:
            raise SurfaceScoringError("null tally outside 0..draws")

    @property
    def p_value(self) -> float:
        return self.at_least_as_good / self.draws

    @property
    def beats_null(self) -> bool:
        return self.p_value < self.alpha

    def as_dict(self) -> dict[str, Any]:
        return {
            "statistic": self.statistic,
            "direction": self.direction,
            "observed": round(self.observed, 6),
            "draws": self.draws,
            "seed": self.seed,
            "population": self.population,
            "population_size": self.population_size,
            "at_least_as_good": self.at_least_as_good,
            "p_value": round(self.p_value, 4),
            "alpha": self.alpha,
            "null_median": round(self.null_median, 6),
            "null_tail": round(self.null_tail, 6),
            "beats_null": self.beats_null,
            "area": self.area.as_dict(),
        }


@dataclass(frozen=True)
class LocalizationClaim:
    """One graded perception answer. **Cannot exist without its null control.**

    ``null`` is a required field with no default. ``verdict`` is a property, not
    a field, so no caller can stamp ``pass`` on a claim that lost to chance.
    Together those two facts are the whole of "a number without its null control
    is not a result", expressed as something the type system enforces rather
    than as a convention someone has to remember.
    """

    entity_id: str
    label: str
    place_class: str
    measure: str
    statistic: str
    value: float
    threshold: float
    raw_pass: bool
    null: NullControl
    #: Free-form denominators — n frames, n entries, n evidence points.
    denominators: dict[str, Any] = field(default_factory=dict)
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.null, NullControl):
            raise SurfaceScoringError(
                "a localization claim requires a NullControl; the bench scored "
                "sidewalk and crosswalk at 0.00 m against a RANDOM map, so an "
                "unqualified number here means nothing"
            )
        if self.measure not in LOCALIZATION_TARGETS:
            raise SurfaceScoringError(f"unknown measure {self.measure!r}")

    @property
    def verdict(self) -> str:
        """``pass`` only when the statistic passed AND beat chance."""

        if not self.raw_pass:
            return VERDICT_FAIL
        if not self.null.beats_null:
            return VERDICT_UNINFORMATIVE
        return VERDICT_PASS

    @property
    def is_pass(self) -> bool:
        return self.verdict == VERDICT_PASS

    def as_dict(self) -> dict[str, Any]:
        return {
            "entity_id": self.entity_id,
            "label": self.label,
            "place_class": self.place_class,
            "measure": self.measure,
            "statistic": self.statistic,
            "value": round(self.value, 6),
            "threshold": self.threshold,
            "raw_pass": self.raw_pass,
            "verdict": self.verdict,
            "null_control": self.null.as_dict(),
            "denominators": dict(self.denominators),
            "notes": list(self.notes),
        }


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        raise SurfaceScoringError("no null draws to summarise")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = fraction * (len(ordered) - 1)
    low = math.floor(position)
    high = math.ceil(position)
    if low == high:
        return ordered[low]
    weight = position - low
    return ordered[low] * (1.0 - weight) + ordered[high] * weight


# ---------------------------------------------------------------------------
# the two per-class scoring rules
# ---------------------------------------------------------------------------


def score_near_class(
    *,
    entity_id: str,
    surface: Mapping[str, Any],
    answer_xy: Any,
    area: MappedArea,
    candidate_entries: int,
    also_satisfied_by: Sequence[Mapping[str, Any]] = (),
    draws: int = NULL_DRAWS,
    seed: int = NULL_SEED,
    budget_m: float = SURFACE_BUDGET_M,
    denominators: Mapping[str, Any] | None = None,
    notes: Sequence[str] = (),
) -> LocalizationClaim:
    """Grade a ``near``-class answer against the entity's surface.

    ``candidate_entries`` is how many places the answering procedure could have
    picked from — the map's entry count for a retrieval answer. The null
    re-scatters that many entries and takes the best, which is the CONSERVATIVE
    choice: it asks "could a random map of this size have had *something* on
    that surface", not the easier "could one random point have". Required with
    no default, because a null that silently assumed one entry would flatter
    every large map.

    ``also_satisfied_by`` names the OTHER instances of the queried class — the
    six buildings when the owner said "the building". Both the observed
    statistic and the null are taken over the whole set, because a null that may
    only hit one of six targets is *lenient*: it understates how easy the
    question was and so overstates the answer. Empty is correct only when the
    query genuinely names one instance.
    """

    _require_measure(surface, LOCALIZATION_SURFACE)
    if candidate_entries < 1:
        raise SurfaceScoringError("candidate_entries must be >= 1")
    instances = [surface, *also_satisfied_by]
    for other in also_satisfied_by:
        _require_measure(other, LOCALIZATION_SURFACE)

    def _best(point: Any) -> float:
        return min(surface_error_m(point, instance) for instance in instances)

    observed = _best(answer_xy)
    rng = random.Random(seed)
    nulls: list[float] = []
    for _ in range(draws):
        best = math.inf
        for _entry in range(candidate_entries):
            best = min(best, _best(area.sample(rng)))
        nulls.append(best)
    at_least_as_good = sum(1 for value in nulls if value <= observed)
    null = NullControl(
        statistic="surface_error_m",
        direction=DIRECTION_LOWER_IS_BETTER,
        observed=observed,
        draws=draws,
        seed=seed,
        at_least_as_good=at_least_as_good,
        null_median=_percentile(nulls, 0.5),
        null_tail=_percentile(nulls, 0.05),
        area=area,
        population="map entries re-scattered uniformly, best taken",
        population_size=candidate_entries,
    )
    return LocalizationClaim(
        entity_id=entity_id,
        label=str(surface.get("label", "")),
        place_class=str(surface.get("place_class", "")),
        measure=LOCALIZATION_SURFACE,
        statistic="surface_error_m",
        value=observed,
        threshold=float(budget_m),
        raw_pass=observed <= float(budget_m),
        null=null,
        denominators={
            "class_instances": len(instances),
            **dict(denominators or {}),
        },
        notes=tuple(notes),
    )


def score_inside_class(
    *,
    entity_id: str,
    surface: Mapping[str, Any],
    answer_xy: Any,
    evidence_xy: Sequence[Any],
    area: MappedArea,
    also_satisfied_by: Sequence[Mapping[str, Any]] = (),
    draws: int = NULL_DRAWS,
    seed: int = NULL_SEED,
    floor: float = REGION_EVIDENCE_MAJORITY,
    evidence_cap: int = NULL_EVIDENCE_CAP,
    denominators: Mapping[str, Any] | None = None,
    notes: Sequence[str] = (),
) -> LocalizationClaim:
    """Grade an ``inside``-class answer: containment PLUS an evidence majority.

    ``evidence_xy`` is the answering entry's own supporting points. Bare
    containment is kept — it is the R10 arrival predicate and it is what the
    owner means by "on the sidewalk" — but it is not sufficient, because the
    bench measured it at 0.00 m against a random map (p=1.00). The fraction of
    the entry's evidence that lands in the region is the term a random map
    cannot pass, and the null control proves it scene by scene.

    ``also_satisfied_by`` is the other instances the query would equally have
    accepted — "the sidewalk" is two separate strips in this scene — and it
    widens BOTH the observed statistic and the null, for the same reason it does
    for a ``near`` query: a null that may only land on one of the acceptable
    answers understates how easy the question was.
    """

    polygons = interior_polygons(surface, also_satisfied_by)
    contained = inside_any(answer_xy, polygons)
    total = len(evidence_xy)
    if total == 0:
        raise SurfaceScoringError(
            f"{entity_id}: an inside-class claim needs the answering entry's "
            f"supporting points; with none, containment of a single point is "
            f"exactly the uninformative metric this convention replaced"
        )
    # ONE definition of the statistic — the public helper, not a second sum.
    observed = evidence_inside_fraction(
        evidence_xy, surface, also_satisfied_by=also_satisfied_by
    )
    scatter = min(total, max(1, evidence_cap))
    rng = random.Random(seed)
    nulls: list[float] = []
    for _ in range(draws):
        hits = sum(1 for _ in range(scatter) if inside_any(area.sample(rng), polygons))
        nulls.append(hits / scatter)
    at_least_as_good = sum(1 for value in nulls if value >= observed)
    null = NullControl(
        statistic="evidence_inside_fraction",
        direction=DIRECTION_HIGHER_IS_BETTER,
        observed=observed,
        draws=draws,
        seed=seed,
        at_least_as_good=at_least_as_good,
        null_median=_percentile(nulls, 0.5),
        null_tail=_percentile(nulls, 0.95),
        area=area,
        population="supporting points re-scattered uniformly",
        population_size=scatter,
    )
    note_list = list(notes)
    if scatter < total:
        note_list.append(
            f"null scattered {scatter} of {total} points (cap {evidence_cap}); "
            f"fewer points widen the null, so p is an upper bound"
        )
    return LocalizationClaim(
        entity_id=entity_id,
        label=str(surface.get("label", "")),
        place_class=str(surface.get("place_class", "")),
        measure=LOCALIZATION_INTERIOR,
        statistic="evidence_inside_fraction",
        value=observed,
        threshold=float(floor),
        raw_pass=bool(contained and observed >= float(floor)),
        null=null,
        denominators={
            "answer_point_contained": contained,
            "evidence_points": total,
            "class_instances": len(polygons),
            **dict(denominators or {}),
        },
        notes=tuple(note_list),
    )


def score_localization(
    *,
    entity_id: str,
    surface: Mapping[str, Any],
    answer_xy: Any,
    area: MappedArea,
    candidate_entries: int | None = None,
    evidence_xy: Sequence[Any] | None = None,
    **kwargs: Any,
) -> LocalizationClaim:
    """Route an answer to its class's rule, reading the measure off the key.

    The dispatcher exists so no caller writes its own ``if region: ... else:
    ...``; a second such branch is how the answer key and the scorer would drift
    back apart.
    """

    measure = str(surface.get("measure", ""))
    if measure == LOCALIZATION_SURFACE:
        if candidate_entries is None:
            raise SurfaceScoringError(
                "a near-class claim needs candidate_entries for its null control"
            )
        return score_near_class(
            entity_id=entity_id,
            surface=surface,
            answer_xy=answer_xy,
            area=area,
            candidate_entries=candidate_entries,
            **kwargs,
        )
    if measure == LOCALIZATION_INTERIOR:
        if evidence_xy is None:
            raise SurfaceScoringError(
                "an inside-class claim needs the answering entry's evidence points"
            )
        return score_inside_class(
            entity_id=entity_id,
            surface=surface,
            answer_xy=answer_xy,
            evidence_xy=evidence_xy,
            area=area,
            **kwargs,
        )
    raise SurfaceScoringError(
        f"surface record for {entity_id!r} declares measure {measure!r}, which "
        f"has no scoring rule"
    )
