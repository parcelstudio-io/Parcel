"""Overture Places brand-tile client stub over cached fixtures (offline)."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from parcel_robot.paths import packaged_assets_root, resolve_asset

DEFAULT_OVERTURE_RELATIVE = "maps/overture_places_v1.json"

DOES_NOT_PROVE = (
    "Cached Overture places fixture is not a live Overture Maps download (HR-10).",
    "Brand/category fields are authored for cascade tests, not CDLA field truth.",
)


def _finite(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be numeric")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite")
    return number


@dataclass(frozen=True, slots=True)
class OverturePlace:
    id: str
    name: str
    brand: str | None
    category: str
    x: float
    y: float
    aliases: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not self.id:
            raise ValueError("id must be non-empty")
        if not isinstance(self.name, str) or not self.name:
            raise ValueError("name must be non-empty")
        if self.brand is not None and (not isinstance(self.brand, str) or not self.brand):
            raise ValueError("brand must be None or non-empty")
        if not isinstance(self.category, str) or not self.category:
            raise ValueError("category must be non-empty")
        _finite(self.x, "x")
        _finite(self.y, "y")
        if not isinstance(self.aliases, tuple):
            raise TypeError("aliases must be a tuple")

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "name": self.name,
            "brand": self.brand,
            "category": self.category,
            "x": self.x,
            "y": self.y,
            "aliases": list(self.aliases),
        }


@dataclass(frozen=True, slots=True)
class OvertureTile:
    tile_id: str
    fixture_id: str
    places: tuple[OverturePlace, ...]
    bbox: tuple[float, float, float, float]
    does_not_prove: tuple[str, ...] = DOES_NOT_PROVE

    def query_near(
        self,
        x: float,
        y: float,
        *,
        radius_m: float = 25.0,
        brand: str | None = None,
        category: str | None = None,
    ) -> tuple[OverturePlace, ...]:
        _finite(x, "x")
        _finite(y, "y")
        radius = _finite(radius_m, "radius_m")
        if radius < 0.0:
            raise ValueError("radius_m must be non-negative")
        hits: list[tuple[float, OverturePlace]] = []
        brand_l = brand.lower() if isinstance(brand, str) else None
        cat_l = category.lower() if isinstance(category, str) else None
        for place in self.places:
            if brand_l is not None:
                candidates = [place.brand or "", place.name, *place.aliases]
                if not any(brand_l in c.lower() for c in candidates if c):
                    continue
            if cat_l is not None and place.category.lower() != cat_l:
                continue
            d = math.hypot(place.x - x, place.y - y)
            if d <= radius:
                hits.append((d, place))
        hits.sort(key=lambda item: (item[0], item[1].id))
        return tuple(place for _, place in hits)

    def match_brand_text(self, text: str, *, limit: int = 5) -> tuple[OverturePlace, ...]:
        """Fuzzy-ish brand/name contains match for OCR cascade (offline stub)."""

        if not isinstance(text, str) or not text.strip():
            return ()
        needle = " ".join(text.strip().lower().split())
        scored: list[tuple[int, OverturePlace]] = []
        for place in self.places:
            haystacks = [place.name, place.brand or "", *place.aliases]
            best = 0
            for hay in haystacks:
                clean = hay.lower()
                if not clean:
                    continue
                if needle == clean:
                    best = max(best, 100)
                elif needle in clean or clean in needle:
                    best = max(best, 80)
                elif any(tok and tok in clean for tok in needle.split()):
                    best = max(best, 40)
            if best > 0:
                scored.append((best, place))
        scored.sort(key=lambda item: (-item[0], item[1].id))
        return tuple(place for _, place in scored[: max(0, int(limit))])


class OvertureTileClient:
    """Offline brand-tile client — loads only cached fixtures (no network)."""

    def __init__(self, path: str | Path | None = None) -> None:
        self._path = resolve_overture_fixture(path)
        self._tile = load_overture_tile(self._path)

    @property
    def path(self) -> Path:
        return self._path

    @property
    def tile(self) -> OvertureTile:
        return self._tile

    def fetch_tile(self, tile_id: str | None = None) -> OvertureTile:
        """Return the cached tile. Unknown tile_id fails closed."""

        if tile_id is not None and tile_id != self._tile.tile_id:
            raise LookupError(
                f"overture tile {tile_id!r} not in cached fixture "
                f"(have {self._tile.tile_id!r}); offline client does not fetch"
            )
        return self._tile


def resolve_overture_fixture(path: str | Path | None = None) -> Path:
    if path is not None:
        candidate = Path(path).expanduser()
        if candidate.is_file():
            return candidate.resolve()
        raise FileNotFoundError(f"overture fixture missing: {candidate}")
    try:
        return resolve_asset(*Path(DEFAULT_OVERTURE_RELATIVE).parts, kind="file")
    except FileNotFoundError:
        fallback = packaged_assets_root() / DEFAULT_OVERTURE_RELATIVE
        if fallback.is_file():
            return fallback.resolve()
        raise


def load_overture_tile(path: str | Path | None = None) -> OvertureTile:
    fixture_path = resolve_overture_fixture(path)
    raw = json.loads(fixture_path.read_text(encoding="utf-8"))
    return tile_from_mapping(raw)


def tile_from_mapping(raw: Mapping[str, Any]) -> OvertureTile:
    if not isinstance(raw, Mapping):
        raise TypeError("fixture must be a mapping")
    places_raw: Sequence[Mapping[str, Any]] = raw.get("places", [])
    places = tuple(
        OverturePlace(
            id=str(item["id"]),
            name=str(item["name"]),
            brand=None if item.get("brand") is None else str(item["brand"]),
            category=str(item["category"]),
            x=float(item["x"]),
            y=float(item["y"]),
            aliases=tuple(str(a) for a in item.get("aliases", [])),
        )
        for item in places_raw
    )
    bbox_raw = raw.get("bbox", {})
    bbox = (
        float(bbox_raw.get("min_x", 0.0)),
        float(bbox_raw.get("min_y", 0.0)),
        float(bbox_raw.get("max_x", 0.0)),
        float(bbox_raw.get("max_y", 0.0)),
    )
    dnp = tuple(str(s) for s in raw.get("does_not_prove", DOES_NOT_PROVE))
    return OvertureTile(
        tile_id=str(raw.get("tile_id", "unknown")),
        fixture_id=str(raw.get("fixture_id", "unknown")),
        places=places,
        bbox=bbox,
        does_not_prove=dnp,
    )
