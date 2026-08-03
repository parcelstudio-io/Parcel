from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Protocol

from .base import NavObservation
from .goals import SemanticGoal


@dataclass(frozen=True)
class SemanticCandidate:
    candidate_id: str
    label: str
    x: float
    y: float
    z: float = 0.0
    confidence: float = 0.0
    kind: str = "object"
    polygon: tuple[tuple[float, float], ...] = ()
    source: str = "perception"
    observed_at: float | None = None
    reachable: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        values = (self.x, self.y, self.z, self.confidence)
        if not all(math.isfinite(value) for value in values):
            raise ValueError("semantic candidate values must be finite")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("semantic candidate confidence must be between zero and one")
        if not self.candidate_id or len(self.candidate_id) > 128:
            raise ValueError("semantic candidate id is invalid")
        if not self.label or len(self.label) > 160:
            raise ValueError("semantic candidate label is invalid")


class SemanticMap(Protocol):
    def query(self, goal: SemanticGoal, observation: NavObservation) -> list[SemanticCandidate]: ...


class ObservationSemanticMap:
    """Read validated semantic candidates produced by an on-robot perception adapter."""

    def query(self, goal: SemanticGoal, observation: NavObservation) -> list[SemanticCandidate]:
        raw = observation.extras.get("semantic_candidates", [])
        if not isinstance(raw, (list, tuple)):
            return []
        candidates: list[SemanticCandidate] = []
        for index, item in enumerate(raw[:64]):
            try:
                candidate = _candidate(item, index)
            except (KeyError, TypeError, ValueError):
                continue
            if _matches(goal.query, candidate.label, candidate.metadata.get("aliases")):
                candidates.append(candidate)
        return sorted(candidates, key=lambda item: item.confidence, reverse=True)


def _candidate(item: Any, index: int) -> SemanticCandidate:
    if isinstance(item, SemanticCandidate):
        return item
    if not isinstance(item, dict):
        raise TypeError("candidate must be a mapping")
    polygon_raw = item.get("polygon") or []
    if not isinstance(polygon_raw, (list, tuple)) or len(polygon_raw) > 256:
        raise TypeError("candidate polygon is invalid")
    polygon = tuple((float(point[0]), float(point[1])) for point in polygon_raw)
    center = item.get("position") or item.get("centroid")
    if center is None and polygon:
        center = (
            sum(point[0] for point in polygon) / len(polygon),
            sum(point[1] for point in polygon) / len(polygon),
            0.0,
        )
    if not isinstance(center, (list, tuple)) or len(center) < 2:
        raise TypeError("candidate requires a position or polygon")
    metadata = item.get("metadata") or {}
    if not isinstance(metadata, dict):
        raise TypeError("candidate metadata must be a mapping")
    return SemanticCandidate(
        candidate_id=str(item.get("id") or f"candidate-{index}"),
        label=str(item["label"]),
        x=float(center[0]),
        y=float(center[1]),
        z=float(center[2]) if len(center) > 2 else 0.0,
        confidence=float(item.get("confidence", 0.0)),
        kind=str(item.get("kind", "object")),
        polygon=polygon,
        source=str(item.get("source", "perception")),
        observed_at=(float(item["observed_at"]) if item.get("observed_at") is not None else None),
        reachable=bool(item.get("reachable", True)),
        metadata=dict(metadata),
    )


def _matches(query: str, label: str, aliases: Any) -> bool:
    query_words = set(query.lower().split())
    texts = [label]
    if isinstance(aliases, (list, tuple)):
        texts.extend(str(alias) for alias in aliases[:16])
    return any(
        query.lower() in text.lower() or bool(query_words & set(text.lower().split()))
        for text in texts
    )
