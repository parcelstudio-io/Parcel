from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

from .base import NavObservation
from .goals import SemanticGoal

if TYPE_CHECKING:
    from parcel_robot.backends.base import SimObservation


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
        if self.kind not in {"object", "region"}:
            raise ValueError("semantic candidate kind is invalid")
        if not isinstance(self.reachable, bool):
            raise TypeError("semantic candidate reachable must be a boolean")
        if self.observed_at is not None and not math.isfinite(self.observed_at):
            raise ValueError("semantic candidate observation time must be finite")
        if any(not math.isfinite(axis) for point in self.polygon for axis in point):
            raise ValueError("semantic candidate polygon must be finite")


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
            if candidate.kind == goal.kind and _matches(
                goal.query, candidate.label, candidate.metadata.get("aliases")
            ):
                candidates.append(candidate)
        robot_x, robot_y = observation.position[:2]
        return sorted(
            candidates,
            key=lambda item: (
                -item.confidence,
                math.hypot(item.x - robot_x, item.y - robot_y),
                item.candidate_id,
            ),
        )


def semantic_candidates_from_observation(observation: SimObservation) -> list[dict[str, Any]]:
    """Convert validated camera/depth tracks into the navigator's typed payload."""

    candidates: list[dict[str, Any]] = [
        {
            "id": region.region_id,
            "label": region.label,
            "polygon": [list(point) for point in region.polygon],
            "confidence": region.confidence,
            "kind": "region",
            "source": region.source,
            "reachable": region.reachable,
            "metadata": dict(region.metadata or {}),
        }
        for region in observation.semantic_regions
    ]
    candidates.extend(
        {
            "id": item.object_id,
            "label": item.label,
            "position": list(item.position),
            "confidence": item.confidence,
            "kind": "object",
            "source": item.source,
            "reachable": item.reachable,
            "metadata": dict(item.metadata or {}),
        }
        for item in observation.semantic_objects
    )
    return candidates


def lidar_payload_from_observation(observation: SimObservation) -> list[dict[str, Any]]:
    return [
        {
            "id": item.obstacle_id,
            "distance_m": item.distance_m,
            "bearing_rad": item.bearing_rad,
        }
        for item in observation.lidar_obstacles
    ]


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
    reachable = item.get("reachable", True)
    if not isinstance(reachable, bool):
        raise TypeError("candidate reachable must be a boolean")
    kind = item.get("kind", "object")
    if kind not in {"object", "region"}:
        raise ValueError("candidate kind is invalid")
    return SemanticCandidate(
        candidate_id=str(item.get("id") or f"candidate-{index}"),
        label=str(item["label"]),
        x=float(center[0]),
        y=float(center[1]),
        z=float(center[2]) if len(center) > 2 else 0.0,
        confidence=float(item.get("confidence", 0.0)),
        kind=kind,
        polygon=polygon,
        source=str(item.get("source", "perception")),
        observed_at=(float(item["observed_at"]) if item.get("observed_at") is not None else None),
        reachable=reachable,
        metadata=dict(metadata),
    )


def _matches(query: str, label: str, aliases: Any) -> bool:
    normalized_query = _normalized(query)
    if not normalized_query:
        return False
    texts = [label]
    if isinstance(aliases, (list, tuple)):
        texts.extend(str(alias) for alias in aliases[:16])
    for text in texts:
        normalized_text = _normalized(text)
        if normalized_text and (
            normalized_query in normalized_text or normalized_text in normalized_query
        ):
            return True
    return False


def _normalized(value: object) -> str:
    return "".join(re.findall(r"[a-z0-9]+", str(value).lower()))
