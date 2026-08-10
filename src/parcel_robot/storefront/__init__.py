"""Phase-3 storefront / OCR sim slice (synthetic pixels, real OCR optional).

Fixture placards → CameraChannel-shaped RGB → fake OCR (CI) or optional
paddleocr (UNVERIFIED) → DetectionMsg evidence → SemanticMemory2D.

Honesty: does **not** prove wild storefront precision (HR-4 / U29).
"""

from __future__ import annotations

from parcel_robot.storefront.fixtures import (
    DOES_NOT_PROVE as FIXTURE_DOES_NOT_PROVE,
)
from parcel_robot.storefront.fixtures import (
    StorefrontFixture,
    StorefrontManifest,
    load_manifest,
    resolve_storefront_root,
    storefront_fixture_candidates,
)
from parcel_robot.storefront.ingest import (
    DOES_NOT_PROVE as INGEST_DOES_NOT_PROVE,
)
from parcel_robot.storefront.ingest import (
    ingest_ocr_hits,
    ocr_hit_to_detection,
    ocr_hits_to_detections,
    recall_storefront,
)
from parcel_robot.storefront.ocr import (
    UNVERIFIED_PADDLE_OCR,
    FakeOcrEngine,
    OcrBackendKind,
    OcrEngine,
    OcrHit,
    PaddleOcrEngine,
    open_ocr_engine,
    paddleocr_available,
    texts_match,
)
from parcel_robot.storefront.placards import (
    ensure_placard_png,
    normalize_sign_text,
    render_placard_rgb,
    write_png_rgb,
)
from parcel_robot.storefront.render import (
    StorefrontCapture,
    StorefrontSyntheticAdapter,
    composite_storefront_frame,
)

DOES_NOT_PROVE = FIXTURE_DOES_NOT_PROVE + INGEST_DOES_NOT_PROVE + UNVERIFIED_PADDLE_OCR

__all__ = [
    "DOES_NOT_PROVE",
    "FIXTURE_DOES_NOT_PROVE",
    "INGEST_DOES_NOT_PROVE",
    "UNVERIFIED_PADDLE_OCR",
    "FakeOcrEngine",
    "OcrBackendKind",
    "OcrEngine",
    "OcrHit",
    "PaddleOcrEngine",
    "StorefrontCapture",
    "StorefrontFixture",
    "StorefrontManifest",
    "StorefrontSyntheticAdapter",
    "composite_storefront_frame",
    "ensure_placard_png",
    "ingest_ocr_hits",
    "load_manifest",
    "normalize_sign_text",
    "ocr_hit_to_detection",
    "ocr_hits_to_detections",
    "open_ocr_engine",
    "paddleocr_available",
    "recall_storefront",
    "render_placard_rgb",
    "resolve_storefront_root",
    "storefront_fixture_candidates",
    "texts_match",
    "write_png_rgb",
]
