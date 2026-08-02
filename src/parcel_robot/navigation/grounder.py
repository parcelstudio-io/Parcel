from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from .base import GoalPose


class PlaceGrounder:
    """Map natural-language directives to city POI goals."""

    def __init__(self, pois: list[dict[str, Any]]):
        self.pois = pois

    @classmethod
    def from_yaml(cls, path: str | Path) -> PlaceGrounder:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        return cls(list(data.get("pois") or []))

    def ground(self, directive: str) -> GoalPose:
        text = directive.strip().lower()
        if not text:
            raise ValueError("empty navigation directive")

        scored: list[tuple[int, dict[str, Any]]] = []
        for poi in self.pois:
            score = 0
            label = str(poi.get("label") or poi.get("id") or "").lower()
            names = [str(n).lower() for n in (poi.get("names") or poi.get("aliases") or [])]
            street = str(poi.get("street", "")).lower()
            category = str(poi.get("category", "")).lower()

            for token in names + ([label] if label else []):
                if token and token in text:
                    score += 5
            if street and street in text:
                score += 3
            if category and category in text:
                score += 1
            for word in re.findall(r"[a-z0-9]+", " ".join(names) + " " + label):
                if len(word) >= 4 and word in text:
                    score += 1
            if score > 0:
                scored.append((score, poi))

        if not scored:
            raise LookupError(
                f"could not ground directive to a known place: {directive!r}. "
                f"Known POIs: {[p.get('id') for p in self.pois]}"
            )

        scored.sort(key=lambda item: item[0], reverse=True)
        poi = scored[0][1]
        xyz = poi.get("position") or poi.get("xyz") or [0.0, 0.0, 0.0]
        label = str(poi.get("label") or (poi.get("names") or [poi.get("id", "")])[0])
        return GoalPose(
            x=float(xyz[0]),
            y=float(xyz[1]),
            z=float(xyz[2]) if len(xyz) > 2 else 0.0,
            heading_deg=float(poi.get("heading_deg", 0.0)),
            poi_id=str(poi.get("id", "")),
            label=label,
        )
