"""Typed grounding outcomes and frustum→memory resolution (pure)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any


class GroundingOutcome(str, Enum):
    RESOLVED = "RESOLVED"
    MEMORY_HIT = "MEMORY_HIT"
    UNSEEN = "UNSEEN"
    AMBIGUOUS = "AMBIGUOUS"


@dataclass(frozen=True)
class GroundingResult:
    outcome: GroundingOutcome
    candidate: Mapping[str, Any] | None
    candidates: tuple[Mapping[str, Any], ...]
    detail: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome.value,
            "candidate": dict(self.candidate) if self.candidate is not None else None,
            "candidate_count": len(self.candidates),
            "detail": self.detail,
        }


def resolve_grounding(
    *,
    frustum: Sequence[Mapping[str, Any]],
    memory: Sequence[Mapping[str, Any]],
    ambiguity_margin: float = 0.05,
    distance_ambiguity_m: float = 0.75,
) -> GroundingResult:
    """Apply the frustum → memory order; search/refusal are caller recovery.

    Ambiguity: two top candidates within ``ambiguity_margin`` confidence **and**
    within ``distance_ambiguity_m`` range of each other. Equal-confidence GT
    landmarks at clearly different ranges resolve to the nearer (already sorted)
    hit — otherwise every dual lamppost/bench scene would be AMBIGUOUS.
    """

    frustum_hits = tuple(frustum)
    if _is_ambiguous(frustum_hits, ambiguity_margin, distance_ambiguity_m):
        return GroundingResult(
            outcome=GroundingOutcome.AMBIGUOUS,
            candidate=None,
            candidates=frustum_hits,
            detail="ambiguous_frustum_match",
        )
    if frustum_hits:
        return GroundingResult(
            outcome=GroundingOutcome.RESOLVED,
            candidate=frustum_hits[0],
            candidates=frustum_hits,
            detail="frustum",
        )
    memory_hits = tuple(memory)
    if _is_ambiguous(memory_hits, ambiguity_margin, distance_ambiguity_m):
        return GroundingResult(
            outcome=GroundingOutcome.AMBIGUOUS,
            candidate=None,
            candidates=memory_hits,
            detail="ambiguous_memory_match",
        )
    if memory_hits:
        return GroundingResult(
            outcome=GroundingOutcome.MEMORY_HIT,
            candidate=memory_hits[0],
            candidates=memory_hits,
            detail="memory",
        )
    return GroundingResult(
        outcome=GroundingOutcome.UNSEEN,
        candidate=None,
        candidates=(),
        detail="unseen",
    )


def _is_ambiguous(
    hits: tuple[Mapping[str, Any], ...],
    ambiguity_margin: float,
    distance_ambiguity_m: float,
) -> bool:
    if len(hits) < 2:
        return False
    c0 = float(hits[0].get("confidence", 0.0))
    c1 = float(hits[1].get("confidence", 0.0))
    if abs(c0 - c1) > ambiguity_margin:
        return False
    d0 = _candidate_distance_m(hits[0])
    d1 = _candidate_distance_m(hits[1])
    if d0 is None or d1 is None:
        # No range signal — confidence tie stays ambiguous.
        return True
    return abs(d0 - d1) <= distance_ambiguity_m


def _candidate_distance_m(candidate: Mapping[str, Any]) -> float | None:
    if "distance_m" in candidate:
        try:
            value = float(candidate["distance_m"])  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return None
        return value if value >= 0.0 else None
    # Pipeline passes x/y; without robot pose we can only compare pairwise later.
    return None


def honest_not_found_reply(query: str, *, scanned: bool, searched: bool) -> str:
    """Refusal/report text that names the recovery attempted."""

    label = " ".join(str(query).strip().split()) or "that"
    if searched:
        return (
            f"I looked around and searched nearby but couldn't find a {label}. "
            "I am stopping here."
        )
    if scanned:
        return (
            f"I looked around and couldn't find a {label} nearby. "
            "I am stopping here."
        )
    return (
        f"I couldn't form a safe, grounded plan for {label!r} yet. "
        "Please clarify the task or let me inspect the scene again."
    )
