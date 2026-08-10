"""Load the P3 storefront / OCR fixture pack (manifest + placard textures)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from parcel_robot.paths import packaged_assets_root, parcel_roots
from parcel_robot.storefront.placards import ensure_placard_png

DOES_NOT_PROVE = (
    "Synthetic placard textures are not wild storefront photography.",
    "Fake OCR from fixture metadata does not validate PP-OCRv6 field recall.",
    "Passing CI OCR smoke does not prove ≥90% named-place precision outdoors.",
)

_RELATIVE = Path("fixtures") / "storefronts"
_MANIFEST_NAME = "manifest.yaml"


@dataclass(frozen=True, slots=True)
class StorefrontFixture:
    """One authored storefront sign used for OCR sim smoke."""

    id: str
    brand: str
    expected_text: str
    placard_file: str
    roi_norm: tuple[float, float, float, float]
    bearing_rad: float
    range_m: float
    bg_rgb: tuple[int, int, int]
    fg_rgb: tuple[int, int, int]
    sign_height_m: float
    placard_path: Path

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "brand": self.brand,
            "expected_text": self.expected_text,
            "placard_file": self.placard_file,
            "roi_norm": list(self.roi_norm),
            "bearing_rad": self.bearing_rad,
            "range_m": self.range_m,
            "bg_rgb": list(self.bg_rgb),
            "fg_rgb": list(self.fg_rgb),
            "sign_height_m": self.sign_height_m,
            "placard_path": str(self.placard_path),
        }


@dataclass(frozen=True, slots=True)
class StorefrontManifest:
    schema_version: int
    storefronts: tuple[StorefrontFixture, ...]
    does_not_prove: tuple[str, ...]
    root: Path

    def by_id(self, storefront_id: str) -> StorefrontFixture:
        for item in self.storefronts:
            if item.id == storefront_id:
                return item
        raise KeyError(f"unknown storefront id: {storefront_id!r}")

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "storefronts": [s.as_dict() for s in self.storefronts],
            "does_not_prove": list(self.does_not_prove),
            "root": str(self.root),
        }


def storefront_fixture_candidates() -> tuple[Path, ...]:
    """Ordered roots that may contain fixtures/storefronts/."""

    candidates: list[Path] = []
    for root in parcel_roots():
        candidates.append((root / _RELATIVE).resolve())
    packaged = packaged_assets_root() / _RELATIVE
    candidates.append(packaged.resolve())
    # Repo-root fixtures/ when paths.parcel_roots misses it.
    repoish = Path(__file__).resolve().parents[3] / _RELATIVE
    candidates.append(repoish.resolve())
    seen: set[Path] = set()
    ordered: list[Path] = []
    for path in candidates:
        if path not in seen:
            seen.add(path)
            ordered.append(path)
    return tuple(ordered)


def resolve_storefront_root() -> Path:
    for root in storefront_fixture_candidates():
        if (root / _MANIFEST_NAME).is_file():
            return root
    tried = [str(p / _MANIFEST_NAME) for p in storefront_fixture_candidates()]
    raise FileNotFoundError(f"storefront manifest not found; tried={tried}")


def _rgb_tuple(value: object, name: str) -> tuple[int, int, int]:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValueError(f"{name} must be a length-3 RGB list")
    out: list[int] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, int) or not 0 <= item <= 255:
            raise ValueError(f"{name} components must be ints in [0, 255]")
        out.append(item)
    return out[0], out[1], out[2]


def _roi(value: object) -> tuple[float, float, float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise ValueError("roi_norm must be [x0, y0, x1, y1]")
    nums = tuple(float(v) for v in value)
    if not all(0.0 <= v <= 1.0 for v in nums):
        raise ValueError("roi_norm components must be in [0, 1]")
    x0, y0, x1, y1 = nums
    if x1 <= x0 or y1 <= y0:
        raise ValueError("roi_norm must satisfy x1>x0 and y1>y0")
    return x0, y0, x1, y1


def load_manifest(
    *,
    root: Path | None = None,
    ensure_placards: bool = True,
) -> StorefrontManifest:
    """Load fixture pack; optionally materialize missing placard PNGs."""

    base = root.resolve() if root is not None else resolve_storefront_root()
    path = base / _MANIFEST_NAME
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise TypeError("storefront manifest must be a mapping")
    schema = int(raw.get("schema_version", 1))
    dnp = raw.get("does_not_prove") or list(DOES_NOT_PROVE)
    if not isinstance(dnp, list) or not dnp or any(not isinstance(x, str) or not x for x in dnp):
        raise ValueError("does_not_prove must be a non-empty list of strings")
    rows = raw.get("storefronts")
    if not isinstance(rows, list) or not rows:
        raise ValueError("storefronts must be a non-empty list")

    fixtures: list[StorefrontFixture] = []
    for row in rows:
        if not isinstance(row, dict):
            raise TypeError("storefront entry must be a mapping")
        sid = str(row["id"]).strip()
        brand = str(row["brand"]).strip()
        expected = str(row["expected_text"]).strip()
        placard_file = str(row["placard_file"]).strip()
        if not sid or not brand or not expected or not placard_file:
            raise ValueError("id/brand/expected_text/placard_file required")
        placard_path = (base / placard_file).resolve()
        bg = _rgb_tuple(row.get("bg_rgb", [20, 20, 20]), "bg_rgb")
        fg = _rgb_tuple(row.get("fg_rgb", [255, 255, 255]), "fg_rgb")
        if ensure_placards:
            ensure_placard_png(
                placard_path,
                expected,
                bg_rgb=bg,
                fg_rgb=fg,
            )
        elif not placard_path.is_file():
            raise FileNotFoundError(f"missing placard texture: {placard_path}")
        fixtures.append(
            StorefrontFixture(
                id=sid,
                brand=brand,
                expected_text=expected,
                placard_file=placard_file,
                roi_norm=_roi(row["roi_norm"]),
                bearing_rad=float(row["bearing_rad"]),
                range_m=float(row["range_m"]),
                bg_rgb=bg,
                fg_rgb=fg,
                sign_height_m=float(row.get("sign_height_m", 2.0)),
                placard_path=placard_path,
            )
        )
    return StorefrontManifest(
        schema_version=schema,
        storefronts=tuple(fixtures),
        does_not_prove=tuple(str(x) for x in dnp),
        root=base,
    )
