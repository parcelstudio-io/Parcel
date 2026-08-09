# P3 Status — Storefront / OCR sim slice (synthetic pixels)

**Phase:** 3 (sim) · **Owner lane:** Opus + Sol-shaped pure helpers ·
**Date:** 2026-08-05 · **State:** DONE (fixtures + CI smoke; no wild OCR claims)

Binding: [ADJUDICATION.md](ADJUDICATION.md) Owner amendment P3
(“storefront signage rendered as textures in the MuJoCo CameraChannel so the
real PP-OCRv6 model runs on synthetic renders — real perception models,
synthetic pixels”). Ledger: [hardware-readiness.md](hardware-readiness.md)
**HR-4**.

## Delivered

| Artifact | Path |
|---|---|
| Fixture pack (manifest + placard PNGs) | `fixtures/storefronts/` + packaged `src/parcel_robot/runtime_assets/fixtures/storefronts/` |
| Storefront package | `src/parcel_robot/storefront/` |
| Placard rasterizer (stdlib PNG) | `…/storefront/placards.py` |
| Synthetic RGB adapter (CameraChannel-shaped) | `…/storefront/render.py` |
| Fake OCR + optional paddleocr (UNVERIFIED) | `…/storefront/ocr.py` |
| DetectionMsg → SemanticMemory2D ingest | `…/storefront/ingest.py` |
| CI tests | `tests/test_p3_storefront_ocr.py` |
| Hardware-readiness HR-4 update | [hardware-readiness.md](hardware-readiness.md) |

## Checklist

- [x] Storefront/signage **texture fixture pack** (manifest + generated text placards)
- [x] Adapter exposes **synthetic RGB** with readable signage (D455-nominal 1280×720)
- [x] **Fake OCR** reads fixture metadata when paddleocr is absent (default CI)
- [x] **Optional PP-OCR path** marked UNVERIFIED; not a dependency; skipped if missing
- [x] OCR hits → `DetectionMsg` evidence refs → `SemanticMemory2D` (pure helper)
- [x] Explicit `DOES_NOT_PROVE` / HR-4 honesty strings
- [x] No Nav2

## Pipeline (MVP)

```text
manifest.yaml + placard PNG
        │
        ▼
StorefrontSyntheticAdapter.capture()  →  RGB @ D455 intrinsics / 35 cm mount
        │
        ▼
FakeOcrEngine (CI)  or  PaddleOcrEngine (optional, UNVERIFIED)
        │
        ▼
ocr_hits_to_detections / ingest_ocr_hits
        │
        ▼
DetectionMsg + SemanticMemory2D.recall("nike")
```

Placard PNGs are written next to the manifest and are suitable as MuJoCo geom
textures when an EGL CameraChannel backend is available. CI does **not**
require EGL — the synthetic compositor paints the same textures into the frame.

## Explicit non-claims

- **Does not prove wild storefront precision.** Synthetic placards ≠ outdoor
  photography, motion blur, or domain gap (HR-4 / U29).
- Fake OCR proves **wiring**, not vision-model recall.
- Optional paddleocr greens (if someone installs it) are still sim evidence only.
- No Nav2, no OSM/GNSS/Overture in this slice.

## Test command

```bash
pytest tests/test_p3_storefront_ocr.py -q
```
