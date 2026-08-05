"""Persistent semantic memory: instance store + region/stuff channel (pure)."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class RememberedEntity:
    entity_id: str
    label: str
    x: float
    y: float
    last_seen_s: float
    confidence: float
    kind: str  # "object" | "region"
    polygon: tuple[tuple[float, float], ...] | None = None

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


@dataclass(frozen=True)
class RegionCell:
    """One cell of the region/stuff channel co-registered with a 2D grid."""

    ix: int
    iy: int
    label: str
    confidence: float
    last_seen_s: float


class SemanticMemory:
    """Seen-once-remembered store with confidence decay and a region channel.

    Alias matching is the caller's job (grounder). Memory matches labels
    exactly (case-folded whitespace-normalized).
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


def _parse_observation(raw: Mapping[str, object], now: float) -> RememberedEntity:
    entity_id = str(raw.get("entity_id") or raw.get("id") or "").strip()
    label = str(raw.get("label") or "").strip()
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
    conf = float(raw.get("confidence", 0.98))
    last_seen = float(raw.get("last_seen_s", now))
    return RememberedEntity(
        entity_id=entity_id,
        label=label,
        x=x,
        y=y,
        last_seen_s=last_seen,
        confidence=conf,
        kind=kind,
        polygon=polygon,
    )


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
