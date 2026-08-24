"""Which coverage candidate to walk at — ROAM-2's open H2, made selectable.

THE PROBLEM THIS ANSWERS, IN THE WORDS OF THE CARD THAT FOUND IT
----------------------------------------------------------------
``scrum/20260822/task_33/ROAM2_STATUS.md`` §7 H2: *"the objective is
anti-exploratory on a home-clustered map, and this is a design question, not a
bug. ``exclude_visible=True`` means the nearest candidate is always just
outside visibility, i.e. behind the dog. Options worth designing (none
implemented): a minimum candidate distance; a forward bearing preference;
ranking by age and by distance from the path already walked; or a frontier
over unexplored space."*

``OnlineSemanticMap.coverage_candidates`` answers *what has not been seen
lately, oldest first*. Today's consumer takes row 0. This module is the
SELECTION over those rows, and it is a separate module for the same reason
the query lives on the map: the visibility rule is the map's, the yield
ladder is the patrol's, and *which of several stale places is worth the walk*
is neither — it is a preference, and preferences belong somewhere a card can
change them without touching either.

DEFAULT = TODAY, EXACTLY
------------------------
:class:`CoverageSelection`'s defaults are all zero weights and a zero minimum
distance, and :func:`select_coverage_candidate` then returns ``rows[0]`` — the
same row the shipped consumer reads. ROAM-1's and ROAM-2's measured baselines
therefore cannot move unless a caller says so in words.

IT FAILS OPEN, ALWAYS
---------------------
Every filter here can empty the list, and an empty list would read to the
patrol as *no objective*, which degrades to ROAM-1's wander. That is safe but
it is not what a filter means: dropping every candidate because they are all
close is "nothing is far enough", not "the map is silent". So a filter that
removes everything is discarded and the unfiltered rows are ranked instead.
No branch in this module can return ``None`` for a non-empty input.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

#: The config section this selection reads, when a caller reads config at all.
COVERAGE_CONFIG_KEY = "coverage"


@dataclass(frozen=True)
class CoverageSelection:
    """How to choose among stale places. Every default reproduces today."""

    #: H2's first option. A candidate closer than this is not worth a leg —
    #: it is the row that is "just outside visibility, i.e. behind the dog".
    #: ``0.0`` (the default) filters nothing.
    min_candidate_distance_m: float = 0.0
    #: H2's second option. Weight on ``cos(bearing)``: 1.0 dead ahead, -1.0
    #: dead astern. ``0.0`` (the default) is indifferent to bearing, which is
    #: what makes the shipped behaviour a pure age ranking.
    forward_bearing_weight: float = 0.0
    #: Weight on normalized age (1.0 = the oldest row in this sample).
    age_weight: float = 1.0
    #: H2's third option. Weight on distance from the path already walked,
    #: normalized by :attr:`path_novelty_span_m`. ``0.0`` disables it.
    path_novelty_weight: float = 0.0
    path_novelty_span_m: float = 6.0

    def __post_init__(self) -> None:
        numbers = (
            "min_candidate_distance_m",
            "forward_bearing_weight",
            "age_weight",
            "path_novelty_weight",
            "path_novelty_span_m",
        )
        for name in numbers:
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"CoverageSelection.{name} must be a number")
            if not math.isfinite(float(value)):
                raise ValueError(f"CoverageSelection.{name} must be finite")
        if self.min_candidate_distance_m < 0.0:
            raise ValueError("min_candidate_distance_m must be non-negative")
        if self.path_novelty_span_m <= 0.0:
            raise ValueError("path_novelty_span_m must be positive")

    @property
    def is_shipped_default(self) -> bool:
        """True when this selection is byte-equivalent to taking row 0."""

        return (
            self.min_candidate_distance_m == 0.0
            and self.forward_bearing_weight == 0.0
            and self.path_novelty_weight == 0.0
        )


def coverage_selection_from_config(section: Mapping[str, Any] | None) -> CoverageSelection:
    """Read a ``coverage`` mapping; absent keys keep the shipped default.

    Fails closed on spelling for the same reason
    ``awareness_limits_from_config`` does: a key nothing reads is
    indistinguishable from a key nobody wrote.
    """

    if not section:
        return CoverageSelection()
    if not isinstance(section, Mapping):
        raise TypeError(f"{COVERAGE_CONFIG_KEY!r} configuration must be a mapping")
    defaults = CoverageSelection()
    known = {
        "min_candidate_distance_m",
        "forward_bearing_weight",
        "age_weight",
        "path_novelty_weight",
        "path_novelty_span_m",
    }
    unknown = set(section) - known
    if unknown:
        raise ValueError(
            f"unknown {COVERAGE_CONFIG_KEY!r} configuration keys: {sorted(unknown)!r}"
        )
    values: dict[str, float] = {}
    for name in known:
        if name not in section:
            continue
        value = section[name]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError(f"{COVERAGE_CONFIG_KEY}.{name} must be a number (got {value!r})")
        values[name] = float(value)
    return CoverageSelection(
        min_candidate_distance_m=values.get(
            "min_candidate_distance_m", defaults.min_candidate_distance_m
        ),
        forward_bearing_weight=values.get(
            "forward_bearing_weight", defaults.forward_bearing_weight
        ),
        age_weight=values.get("age_weight", defaults.age_weight),
        path_novelty_weight=values.get("path_novelty_weight", defaults.path_novelty_weight),
        path_novelty_span_m=values.get("path_novelty_span_m", defaults.path_novelty_span_m),
    )


@dataclass(frozen=True)
class CoverageChoice:
    """The chosen row plus the evidence for why — the refute-first surface."""

    row: Mapping[str, Any]
    considered: int
    after_min_distance: int
    filtered_out_all: bool
    score: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "entry_id": self.row.get("entry_id"),
            "label": self.row.get("label"),
            "distance_m": self.row.get("distance_m"),
            "bearing_rad": self.row.get("bearing_rad"),
            "age_s": self.row.get("age_s"),
            "considered": self.considered,
            "after_min_distance": self.after_min_distance,
            "filtered_out_all": self.filtered_out_all,
            "score": round(self.score, 6),
        }


def select_coverage_candidate(
    rows: Sequence[Mapping[str, Any]],
    *,
    selection: CoverageSelection | None = None,
    path: Sequence[tuple[float, float]] = (),
) -> CoverageChoice | None:
    """Pick one row from ``coverage_candidates``. ``None`` only for no rows.

    With the default :class:`CoverageSelection` this returns ``rows[0]`` — the
    map's own oldest-first ordering, which is what every caller does today.
    """

    if not rows:
        return None
    policy = selection or CoverageSelection()
    if policy.is_shipped_default:
        return CoverageChoice(
            row=rows[0],
            considered=len(rows),
            after_min_distance=len(rows),
            filtered_out_all=False,
            score=0.0,
        )

    far_enough = [
        row
        for row in rows
        if _number(row.get("distance_m")) is not None
        and float(row["distance_m"]) >= policy.min_candidate_distance_m
    ]
    filtered_out_all = not far_enough
    pool = list(rows) if filtered_out_all else far_enough

    ages = [age for age in (_number(row.get("age_s")) for row in pool) if age is not None]
    oldest = max(ages) if ages else 0.0
    scored = [(_score(row, policy, oldest=oldest, path=path), row) for row in pool]
    # TIES ARE BROKEN GEOMETRICALLY, NEVER BY THE MAP'S ROW ORDER, and that is
    # a reproducibility requirement rather than a preference: map entry ids are
    # ``uuid.uuid4()`` (``online_map.py``), so ``coverage_candidates`` breaks
    # its own age ties on a value that differs between PROCESSES. A selection
    # that inherited that order would give a different answer on a re-run of
    # the same seed. Distance, then bearing, then the surface point — all of
    # them properties of the world, none of them of the id.
    best_score, best_row = max(scored, key=lambda item: (item[0], *_tie_key(item[1])))
    return CoverageChoice(
        row=best_row,
        considered=len(rows),
        after_min_distance=len(far_enough),
        filtered_out_all=filtered_out_all,
        score=best_score,
    )


def _tie_key(row: Mapping[str, Any]) -> tuple[float, float, float, float]:
    """A total order over rows that never reads ``entry_id``."""

    distance = _number(row.get("distance_m")) or 0.0
    bearing = _number(row.get("bearing_rad"))
    return (
        distance,
        -abs(bearing if bearing is not None else math.pi),
        _number(row.get("surface_x")) or 0.0,
        _number(row.get("surface_y")) or 0.0,
    )


def _score(
    row: Mapping[str, Any],
    policy: CoverageSelection,
    *,
    oldest: float,
    path: Sequence[tuple[float, float]],
) -> float:
    age = _number(row.get("age_s"))
    age_term = 0.0 if age is None or oldest <= 0.0 else min(1.0, age / oldest)
    bearing = _number(row.get("bearing_rad"))
    forward_term = 0.0 if bearing is None else math.cos(bearing)
    novelty_term = 0.0
    if policy.path_novelty_weight != 0.0 and path:
        x = _number(row.get("surface_x"))
        y = _number(row.get("surface_y"))
        if x is not None and y is not None:
            nearest = min(math.hypot(x - px, y - py) for px, py in path)
            novelty_term = min(1.0, nearest / policy.path_novelty_span_m)
    return (
        policy.age_weight * age_term
        + policy.forward_bearing_weight * forward_term
        + policy.path_novelty_weight * novelty_term
    )


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


__all__ = [
    "COVERAGE_CONFIG_KEY",
    "CoverageChoice",
    "CoverageSelection",
    "coverage_selection_from_config",
    "select_coverage_candidate",
]
