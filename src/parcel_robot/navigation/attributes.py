"""Attribute filtering for qualified navigation targets ("the big tree").

Pure functions only — no sensors, no mission state. Attributes filter the
candidate set *before* superlative selection, so "the closest big tree" means
"among the big trees, the closest", not "the closest tree, hopefully big".

v1 vocabulary is size-only and grounded in scene metadata (``radius_m``, with
``height_m`` as a fallback) compared against the **per-class median**. That is
an honest, relative reading of a relative word: with two identical trees the
median equals both radii and — because the comparison is inclusive — both
survive a "big tree" filter, which is the truthful answer (neither is bigger).

Chosen semantics, pinned by tests:

* ``big``/``large``/``tall``  → keep candidates with size ``>=`` class median.
* ``small``/``little``       → keep candidates with size ``<=`` class median.
* A single candidate of a class is trivially both the biggest and the smallest
  one, so it passes any size attribute.
* A candidate with **no** size metadata cannot be judged. It is dropped and
  named in ``unmeasurable`` — never silently kept as if it matched.
* An attribute this module does not know is reported in ``unsupported`` and
  filters nothing (the parser leaves unknown adjectives inside the noun query,
  so this is a defensive path).

The tables below are the seam the stratum-3 per-scene semantics sidecar takes
over: replace the literals, keep the functions.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

#: Attribute surface word → comparison polarity against the class median.
SIZE_POLARITY_TABLE: dict[str, str] = {
    "big": "at_least",
    "large": "at_least",
    "tall": "at_least",
    "little": "at_most",
    "small": "at_most",
}

#: Metadata keys read as a size, in priority order.
SIZE_METADATA_KEYS: tuple[str, ...] = ("radius_m", "height_m")


@dataclass(frozen=True)
class AttributeFilterResult:
    """Outcome of an attribute filter over one candidate source."""

    kept: tuple[Any, ...]
    applied: tuple[str, ...] = ()
    unsupported: tuple[str, ...] = ()
    unmeasurable: tuple[str, ...] = ()

    @property
    def detail(self) -> str:
        """Short, attribute-naming reason string for mission metadata."""

        parts: list[str] = []
        if self.applied:
            parts.append("attribute_size:" + ",".join(self.applied))
        if self.unmeasurable:
            parts.append("attribute_unmeasurable:" + ",".join(self.unmeasurable))
        if self.unsupported:
            parts.append("attribute_unsupported:" + ",".join(self.unsupported))
        return " ".join(parts)


def merge_results(*results: AttributeFilterResult) -> AttributeFilterResult:
    """Combine per-source results into one report (``kept`` is not merged).

    Used when the same attribute is applied to several candidate sources
    (frustum and memory) and only a single detail string is reported.
    """

    def _union(field: str) -> tuple[str, ...]:
        ordered: dict[str, None] = {}
        for result in results:
            for value in getattr(result, field):
                ordered[value] = None
        return tuple(ordered)

    return AttributeFilterResult(
        kept=(),
        applied=_union("applied"),
        unsupported=_union("unsupported"),
        unmeasurable=_union("unmeasurable"),
    )


def supported_attributes(attributes: Sequence[str]) -> tuple[str, ...]:
    """Return the subset of ``attributes`` this module can evaluate."""

    words = (str(item).lower() for item in attributes)
    return tuple(word for word in words if word in SIZE_POLARITY_TABLE)


def filter_candidates_by_attributes(
    candidates: Sequence[Any],
    attributes: Sequence[str],
) -> AttributeFilterResult:
    """Keep only candidates whose class-relative size matches ``attributes``.

    ``candidates`` may be mappings or objects exposing ``label``/``metadata``
    (``SemanticCandidate`` and the grounder's candidate dicts both qualify).
    An empty ``attributes`` keeps everything untouched.
    """

    items = tuple(candidates)
    words = tuple(str(item).lower() for item in attributes)
    applied = tuple(word for word in words if word in SIZE_POLARITY_TABLE)
    unsupported = tuple(word for word in words if word not in SIZE_POLARITY_TABLE)
    if not applied or not items:
        return AttributeFilterResult(
            kept=items, applied=(), unsupported=unsupported, unmeasurable=()
        )

    medians: dict[str, float] = {}
    grouped: dict[str, list[float]] = {}
    for item in items:
        size = candidate_size(item)
        if size is not None:
            grouped.setdefault(candidate_class(item), []).append(size)
    for class_id, sizes in grouped.items():
        medians[class_id] = float(statistics.median(sizes))

    kept: list[Any] = []
    unmeasurable = False
    for item in items:
        size = candidate_size(item)
        if size is None:
            unmeasurable = True
            continue
        median = medians.get(candidate_class(item))
        if median is None:
            unmeasurable = True
            continue
        if all(_matches_size(word, size, median) for word in applied):
            kept.append(item)
    return AttributeFilterResult(
        kept=tuple(kept),
        applied=applied,
        unsupported=unsupported,
        unmeasurable=applied if unmeasurable else (),
    )


def candidate_class(candidate: Any) -> str:
    """Class key a size comparison is relative to (a tree vs other trees)."""

    if isinstance(candidate, Mapping):
        value = candidate.get("class_id") or candidate.get("label") or ""
    else:
        value = getattr(candidate, "class_id", None) or getattr(candidate, "label", "")
    return str(value).strip().lower()


def candidate_size(candidate: Any) -> float | None:
    """Read a comparable size from candidate metadata, else None."""

    metadata: Any
    if isinstance(candidate, Mapping):
        metadata = candidate.get("metadata")
        direct = candidate
    else:
        metadata = getattr(candidate, "metadata", None)
        direct = None
    for key in SIZE_METADATA_KEYS:
        for holder in (metadata, direct):
            if not isinstance(holder, Mapping) or key not in holder:
                continue
            try:
                value = float(holder[key])
            except (TypeError, ValueError):
                continue
            if math.isfinite(value) and value > 0.0:
                return value
    return None


def _matches_size(word: str, size: float, median: float) -> bool:
    polarity = SIZE_POLARITY_TABLE[word]
    if polarity == "at_least":
        return size >= median
    return size <= median


__all__ = [
    "SIZE_METADATA_KEYS",
    "SIZE_POLARITY_TABLE",
    "AttributeFilterResult",
    "candidate_class",
    "candidate_size",
    "filter_candidates_by_attributes",
    "merge_results",
    "supported_attributes",
]
