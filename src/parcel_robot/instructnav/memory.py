"""Persistent semantic memory: instance store + region/stuff channel (pure).

Hillclimb rung 1 / K4: ``SemanticMemory2D`` is the canonical name. The older
``SemanticMemory`` alias remains for task_6 callers.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from parcel_robot.contracts.v1 import DetectionMsg, GoalRegionV1


@dataclass(frozen=True)
class RememberedEntity:
    """Instance-store row: class + optional embedding + centroid + decay clock."""

    entity_id: str
    label: str
    x: float
    y: float
    last_seen_s: float
    confidence: float
    kind: str  # "object" | "region"
    polygon: tuple[tuple[float, float], ...] | None = None
    embedding: tuple[float, ...] | None = None
    class_id: str = ""

    def __post_init__(self) -> None:
        if not self.entity_id:
            raise ValueError("entity_id must be non-empty")
        if not self.label:
            raise ValueError("label must be non-empty")
        if self.kind not in {"object", "region"}:
            raise ValueError("kind must be 'object' or 'region'")
        if not all(math.isfinite(v) for v in (self.x, self.y, self.last_seen_s, self.confidence)):
            raise ValueError("entity numeric fields must be finite")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be in [0, 1]")
        if self.embedding is not None:
            if not self.embedding or len(self.embedding) > 2048:
                raise ValueError("embedding must contain 1..2048 floats when set")
            if any(
                isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
                for v in self.embedding
            ):
                raise ValueError("embedding components must be finite numbers")


@dataclass(frozen=True)
class RegionCell:
    """One cell of the region/stuff channel co-registered with a 2D grid."""

    ix: int
    iy: int
    label: str
    confidence: float
    last_seen_s: float


class SemanticMemory2D:
    """Seen-once-remembered store with confidence decay and a region channel.

    Region cells are co-registered with a metric grid (``region_resolution_m``).
    Instance rows carry ``{class, embedding optional, centroid, last_seen,
    decaying confidence}``. Alias matching is the caller's job (grounder);
    memory matches labels exactly (case-folded whitespace-normalized).
    """

    def __init__(
        self,
        *,
        decay_half_life_s: float = 600.0,
        min_confidence: float = 0.05,
        capacity: int = 256,
        region_resolution_m: float = 0.5,
        region_capacity: int = 4096,
    ) -> None:
        if not math.isfinite(decay_half_life_s) or decay_half_life_s <= 0.0:
            raise ValueError("decay_half_life_s must be finite and positive")
        if not 0.0 <= min_confidence <= 1.0:
            raise ValueError("min_confidence must be in [0, 1]")
        if capacity < 1:
            raise ValueError("capacity must be ≥ 1")
        if not math.isfinite(region_resolution_m) or region_resolution_m <= 0.0:
            raise ValueError("region_resolution_m must be finite and positive")
        if region_capacity < 1:
            raise ValueError("region_capacity must be ≥ 1")
        self._half_life_s = float(decay_half_life_s)
        self._min_confidence = float(min_confidence)
        self._capacity = int(capacity)
        self._region_resolution_m = float(region_resolution_m)
        self._region_capacity = int(region_capacity)
        self._entities: dict[str, RememberedEntity] = {}
        self._region_cells: dict[tuple[int, int], RegionCell] = {}

    def observe(self, entities: Sequence[Mapping[str, object]], *, now_s: float) -> None:
        now = _finite_time(now_s)
        for raw in entities:
            if not isinstance(raw, Mapping):
                continue
            try:
                entity = _parse_observation(raw, now)
            except (KeyError, TypeError, ValueError):
                continue
            self._entities[entity.entity_id] = entity
            if entity.kind == "region" and entity.polygon:
                self._rasterize_region(entity, now)
        self._evict_expired(now)

    def observe_detections(
        self,
        detections: Sequence[DetectionMsg | Mapping[str, object]],
        *,
        robot_x: float,
        robot_y: float,
        robot_yaw_rad: float,
        now_s: float,
    ) -> None:
        """Ingest detector-shaped observations (bearing/range → map centroid).

        Accepts ``DetectionMsg`` or plain mappings with the same fields. Pure:
        no runtime/sensor I/O — the caller supplies pose + detections.
        """

        now = _finite_time(now_s)
        if not all(math.isfinite(v) for v in (robot_x, robot_y, robot_yaw_rad)):
            raise ValueError("robot pose must be finite")
        for raw in detections:
            try:
                entity = _entity_from_detection(
                    raw,
                    robot_x=robot_x,
                    robot_y=robot_y,
                    robot_yaw_rad=robot_yaw_rad,
                    now_s=now,
                )
            except (KeyError, TypeError, ValueError):
                continue
            self._entities[entity.entity_id] = entity
        self._evict_expired(now)

    def observe_goal_region(
        self,
        goal: GoalRegionV1 | Mapping[str, object],
        *,
        label: str,
        now_s: float,
        confidence: float | None = None,
    ) -> None:
        """Remember a goal region's acceptable polygon as a stuff-class region."""

        now = _finite_time(now_s)
        if hasattr(goal, "acceptable_polygon"):
            polygon = tuple(tuple(p) for p in goal.acceptable_polygon)  # type: ignore[union-attr]
            goal_id = str(getattr(goal, "goal_id", "goal"))
            conf = float(
                confidence if confidence is not None else getattr(goal, "confidence", 0.98)
            )
        else:
            raw = goal  # type: ignore[assignment]
            if not isinstance(raw, Mapping):
                raise TypeError("goal must be GoalRegionV1 or mapping")
            poly_raw = raw.get("acceptable_polygon") or raw.get("polygon")
            if not isinstance(poly_raw, (list, tuple)) or len(poly_raw) < 3:
                raise ValueError("goal region requires acceptable_polygon ≥3 vertices")
            polygon = tuple((float(p[0]), float(p[1])) for p in poly_raw)
            goal_id = str(raw.get("goal_id") or raw.get("entity_id") or "goal")
            conf = float(
                confidence if confidence is not None else raw.get("confidence", 0.98)
            )
        key = _norm_label(label)
        if not key:
            raise ValueError("label must be non-empty")
        if not 0.0 <= conf <= 1.0:
            raise ValueError("confidence must be in [0, 1]")
        cx = sum(p[0] for p in polygon) / len(polygon)
        cy = sum(p[1] for p in polygon) / len(polygon)
        entity = RememberedEntity(
            entity_id=f"goal:{goal_id}",
            label=key,
            x=cx,
            y=cy,
            last_seen_s=now,
            confidence=conf,
            kind="region",
            polygon=polygon,
            class_id=key,
        )
        self._entities[entity.entity_id] = entity
        self._rasterize_region(entity, now)
        self._evict_expired(now)

    def observe_region_labels(
        self,
        cells: Sequence[Mapping[str, object]],
        *,
        now_s: float,
    ) -> None:
        """Direct region-channel update (label per grid cell)."""

        now = _finite_time(now_s)
        for raw in cells:
            if not isinstance(raw, Mapping):
                continue
            try:
                ix = int(raw["ix"])
                iy = int(raw["iy"])
                label = str(raw["label"]).strip().lower()
                conf = float(raw.get("confidence", 0.98))
            except (KeyError, TypeError, ValueError):
                continue
            if not label or not 0.0 <= conf <= 1.0:
                continue
            self._region_cells[(ix, iy)] = RegionCell(
                ix=ix,
                iy=iy,
                label=label,
                confidence=conf,
                last_seen_s=now,
            )
        self._evict_expired(now)

    def recall(self, label: str, *, now_s: float) -> tuple[RememberedEntity, ...]:
        now = _finite_time(now_s)
        key = _norm_label(label)
        if not key:
            return ()
        self._evict_expired(now)
        hits = [
            _with_decayed_confidence(entity, now=now, half_life_s=self._half_life_s)
            for entity in self._entities.values()
            if _norm_label(entity.label) == key
        ]
        return tuple(
            sorted(hits, key=lambda e: (-e.confidence, e.entity_id))
        )

    def recall_all(self, *, now_s: float) -> tuple[RememberedEntity, ...]:
        now = _finite_time(now_s)
        self._evict_expired(now)
        return tuple(
            sorted(
                (
                    _with_decayed_confidence(
                        entity, now=now, half_life_s=self._half_life_s
                    )
                    for entity in self._entities.values()
                ),
                key=lambda e: (-e.confidence, e.entity_id),
            )
        )

    def recall_region_cells(
        self,
        label: str,
        *,
        now_s: float,
    ) -> tuple[RegionCell, ...]:
        """Recall stuff-class cells whose label matches (exact, normalized)."""

        now = _finite_time(now_s)
        key = _norm_label(label)
        if not key:
            return ()
        self._evict_expired(now)
        hits = [
            _with_decayed_region_cell(cell, now=now, half_life_s=self._half_life_s)
            for cell in self._region_cells.values()
            if _norm_label(cell.label) == key
        ]
        return tuple(sorted(hits, key=lambda c: (-c.confidence, c.ix, c.iy)))

    def region_channel_snapshot(self, *, now_s: float) -> dict[str, object]:
        now = _finite_time(now_s)
        self._evict_expired(now)
        return {
            "resolution_m": self._region_resolution_m,
            "cells": [
                {
                    "ix": cell.ix,
                    "iy": cell.iy,
                    "label": cell.label,
                    "confidence": _decayed(
                        cell.confidence,
                        age_s=max(0.0, now - cell.last_seen_s),
                        half_life_s=self._half_life_s,
                    ),
                    "last_seen_s": cell.last_seen_s,
                    "x": (cell.ix + 0.5) * self._region_resolution_m,
                    "y": (cell.iy + 0.5) * self._region_resolution_m,
                }
                for cell in sorted(
                    self._region_cells.values(),
                    key=lambda c: (c.label, c.ix, c.iy),
                )
            ],
        }

    def forget_region(
        self,
        x: float,
        y: float,
        radius_m: float,
        *,
        now_s: float,
    ) -> None:
        """Invalidate memories near a looked-and-gone location."""

        now = _finite_time(now_s)
        if not all(math.isfinite(v) for v in (x, y, radius_m)) or radius_m < 0.0:
            raise ValueError("forget_region requires finite x,y and radius_m ≥ 0")
        drop_ids = [
            entity_id
            for entity_id, entity in self._entities.items()
            if math.hypot(entity.x - x, entity.y - y) <= radius_m
        ]
        for entity_id in drop_ids:
            del self._entities[entity_id]
        res = self._region_resolution_m
        drop_cells = [
            key
            for key, cell in self._region_cells.items()
            if math.hypot(
                (cell.ix + 0.5) * res - x,
                (cell.iy + 0.5) * res - y,
            )
            <= radius_m
        ]
        for key in drop_cells:
            del self._region_cells[key]
        # Touch clock for determinism even if nothing dropped.
        _ = now

    def snapshot(self) -> dict[str, object]:
        return {
            "decay_half_life_s": self._half_life_s,
            "min_confidence": self._min_confidence,
            "capacity": self._capacity,
            "entities": [
                {
                    "entity_id": e.entity_id,
                    "label": e.label,
                    "x": e.x,
                    "y": e.y,
                    "last_seen_s": e.last_seen_s,
                    "confidence": e.confidence,
                    "kind": e.kind,
                    "polygon": (
                        [list(p) for p in e.polygon] if e.polygon is not None else None
                    ),
                    "embedding": list(e.embedding) if e.embedding is not None else None,
                    "class_id": e.class_id,
                }
                for e in sorted(
                    self._entities.values(),
                    key=lambda item: item.entity_id,
                )
            ],
            "region_channel": {
                "resolution_m": self._region_resolution_m,
                "cell_count": len(self._region_cells),
            },
        }

    def _rasterize_region(self, entity: RememberedEntity, now: float) -> None:
        assert entity.polygon is not None
        res = self._region_resolution_m
        xs = [p[0] for p in entity.polygon]
        ys = [p[1] for p in entity.polygon]
        min_ix = math.floor(min(xs) / res)
        max_ix = math.floor(max(xs) / res)
        min_iy = math.floor(min(ys) / res)
        max_iy = math.floor(max(ys) / res)
        for ix in range(min_ix, max_ix + 1):
            for iy in range(min_iy, max_iy + 1):
                cx = (ix + 0.5) * res
                cy = (iy + 0.5) * res
                if _point_in_polygon((cx, cy), entity.polygon):
                    self._region_cells[(ix, iy)] = RegionCell(
                        ix=ix,
                        iy=iy,
                        label=_norm_label(entity.label),
                        confidence=entity.confidence,
                        last_seen_s=now,
                    )

    def _evict_expired(self, now: float) -> None:
        """Drop entities below min confidence; never mutate stored observe-time conf.

        Decay is always ``f(confidence_at_last_seen, now - last_seen)``. Writing
        decayed confidence back into the store would compound on every recall.
        """

        kept: dict[str, RememberedEntity] = {}
        for entity_id, entity in self._entities.items():
            conf = _decayed(
                entity.confidence,
                age_s=max(0.0, now - entity.last_seen_s),
                half_life_s=self._half_life_s,
            )
            if conf < self._min_confidence:
                continue
            kept[entity_id] = entity
        self._entities = kept
        while len(self._entities) > self._capacity:
            victim = min(
                self._entities.values(),
                key=lambda e: (
                    _decayed(
                        e.confidence,
                        age_s=max(0.0, now - e.last_seen_s),
                        half_life_s=self._half_life_s,
                    ),
                    e.last_seen_s,
                    e.entity_id,
                ),
            )
            del self._entities[victim.entity_id]

        region_kept: dict[tuple[int, int], RegionCell] = {}
        for key, cell in self._region_cells.items():
            conf = _decayed(
                cell.confidence,
                age_s=max(0.0, now - cell.last_seen_s),
                half_life_s=self._half_life_s,
            )
            if conf < self._min_confidence:
                continue
            region_kept[key] = cell
        self._region_cells = region_kept
        while len(self._region_cells) > self._region_capacity:
            victim_key = min(
                self._region_cells,
                key=lambda k: (
                    _decayed(
                        self._region_cells[k].confidence,
                        age_s=max(0.0, now - self._region_cells[k].last_seen_s),
                        half_life_s=self._half_life_s,
                    ),
                    self._region_cells[k].last_seen_s,
                    k,
                ),
            )
            del self._region_cells[victim_key]


# Backward-compatible alias (task_6 N-S2 name).
SemanticMemory = SemanticMemory2D


def _parse_observation(raw: Mapping[str, object], now: float) -> RememberedEntity:
    entity_id = str(raw.get("entity_id") or raw.get("id") or "").strip()
    label = str(raw.get("label") or raw.get("class_id") or "").strip()
    kind = str(raw.get("kind") or "object").strip().lower()
    if kind not in {"object", "region"}:
        kind = "object"
    pos = raw.get("position") or raw.get("xy")
    if pos is None and "x" in raw and "y" in raw:
        x, y = float(raw["x"]), float(raw["y"])  # type: ignore[arg-type]
    elif isinstance(pos, (list, tuple)) and len(pos) >= 2:
        x, y = float(pos[0]), float(pos[1])
    else:
        polygon_raw = raw.get("polygon")
        if isinstance(polygon_raw, (list, tuple)) and polygon_raw:
            pts = [(float(p[0]), float(p[1])) for p in polygon_raw]
            x = sum(p[0] for p in pts) / len(pts)
            y = sum(p[1] for p in pts) / len(pts)
        else:
            raise ValueError("missing position")
    polygon = None
    polygon_raw = raw.get("polygon")
    if isinstance(polygon_raw, (list, tuple)) and polygon_raw:
        polygon = tuple((float(p[0]), float(p[1])) for p in polygon_raw)
        if kind == "object" and "kind" not in raw:
            kind = "region"
    conf = float(raw.get("confidence", raw.get("score", 0.98)))
    last_seen = float(raw.get("last_seen_s", now))
    embedding = _optional_embedding(raw.get("embedding"))
    class_id = str(raw.get("class_id") or label).strip()
    return RememberedEntity(
        entity_id=entity_id,
        label=label,
        x=x,
        y=y,
        last_seen_s=last_seen,
        confidence=conf,
        kind=kind,
        polygon=polygon,
        embedding=embedding,
        class_id=class_id,
    )


def _entity_from_detection(
    raw: DetectionMsg | Mapping[str, object],
    *,
    robot_x: float,
    robot_y: float,
    robot_yaw_rad: float,
    now_s: float,
) -> RememberedEntity:
    if hasattr(raw, "class_id") and hasattr(raw, "bearing_rad"):
        class_id = str(raw.class_id)  # type: ignore[union-attr]
        bearing = float(raw.bearing_rad)  # type: ignore[union-attr]
        range_m = float(raw.range_m)  # type: ignore[union-attr]
        score = float(raw.score)  # type: ignore[union-attr]
        embedding = tuple(float(v) for v in raw.embedding)  # type: ignore[union-attr]
        track_id = str(getattr(raw, "track_id", "") or "")
        evidence_id = str(getattr(getattr(raw, "envelope", None), "evidence_id", "") or "")
    else:
        if not isinstance(raw, Mapping):
            raise TypeError("detection must be DetectionMsg or mapping")
        class_id = str(raw.get("class_id") or raw.get("label") or "").strip()
        bearing = float(raw["bearing_rad"])  # type: ignore[arg-type]
        range_m = float(raw["range_m"])  # type: ignore[arg-type]
        score = float(raw.get("score", raw.get("confidence", 0.98)))
        embedding = _optional_embedding(raw.get("embedding"))
        if embedding is None:
            raise ValueError("detection embedding required")
        track_id = str(raw.get("track_id") or "").strip()
        evidence_id = str(raw.get("evidence_id") or "").strip()
    if not class_id:
        raise ValueError("detection class_id must be non-empty")
    if not math.isfinite(bearing) or not math.isfinite(range_m) or range_m < 0.0:
        raise ValueError("bearing/range must be finite; range ≥ 0")
    if not 0.0 <= score <= 1.0:
        raise ValueError("detection score must be in [0, 1]")
    world_yaw = robot_yaw_rad + bearing
    x = robot_x + math.cos(world_yaw) * range_m
    y = robot_y + math.sin(world_yaw) * range_m
    entity_id = track_id or evidence_id or f"det:{class_id}:{x:.2f}:{y:.2f}"
    return RememberedEntity(
        entity_id=entity_id,
        label=class_id,
        x=x,
        y=y,
        last_seen_s=now_s,
        confidence=score,
        kind="object",
        embedding=embedding if isinstance(embedding, tuple) else tuple(embedding),
        class_id=class_id,
    )


def _optional_embedding(value: object) -> tuple[float, ...] | None:
    if value is None:
        return None
    if not isinstance(value, (list, tuple)):
        raise TypeError("embedding must be an array")
    if not value:
        raise ValueError("embedding must be non-empty when provided")
    return tuple(float(v) for v in value)


def _decayed(confidence: float, *, age_s: float, half_life_s: float) -> float:
    if age_s <= 0.0:
        return confidence
    return confidence * (0.5 ** (age_s / half_life_s))


def _with_decayed_confidence(
    entity: RememberedEntity,
    *,
    now: float,
    half_life_s: float,
) -> RememberedEntity:
    conf = _decayed(
        entity.confidence,
        age_s=max(0.0, now - entity.last_seen_s),
        half_life_s=half_life_s,
    )
    if conf == entity.confidence:
        return entity
    return RememberedEntity(
        entity_id=entity.entity_id,
        label=entity.label,
        x=entity.x,
        y=entity.y,
        last_seen_s=entity.last_seen_s,
        confidence=conf,
        kind=entity.kind,
        polygon=entity.polygon,
        embedding=entity.embedding,
        class_id=entity.class_id,
    )


def _with_decayed_region_cell(
    cell: RegionCell,
    *,
    now: float,
    half_life_s: float,
) -> RegionCell:
    conf = _decayed(
        cell.confidence,
        age_s=max(0.0, now - cell.last_seen_s),
        half_life_s=half_life_s,
    )
    if conf == cell.confidence:
        return cell
    return RegionCell(
        ix=cell.ix,
        iy=cell.iy,
        label=cell.label,
        confidence=conf,
        last_seen_s=cell.last_seen_s,
    )


def _norm_label(label: str) -> str:
    return " ".join(str(label).strip().lower().split())


def _finite_time(now_s: float) -> float:
    now = float(now_s)
    if not math.isfinite(now):
        raise ValueError("now_s must be finite")
    return now


def _point_in_polygon(
    point: tuple[float, float],
    polygon: tuple[tuple[float, float], ...],
) -> bool:
    x, y = point
    inside = False
    previous = polygon[-1]
    for current in polygon:
        x1, y1 = previous
        x2, y2 = current
        if (y1 > y) != (y2 > y):
            intersection = (x2 - x1) * (y - y1) / (y2 - y1) + x1
            if x < intersection:
                inside = not inside
        previous = current
    return inside
