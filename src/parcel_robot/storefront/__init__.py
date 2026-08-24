"""Phase-3 storefront / OCR sim slice (synthetic pixels, real OCR optional).

Fixture placards → CameraChannel-shaped RGB → fake OCR (CI) or optional
paddleocr (UNVERIFIED) → DetectionMsg evidence → SemanticMemory2D.

Honesty: does **not** prove wild storefront precision (HR-4 / U29).
"""

from __future__ import annotations

# Kept, not a re-export: the ``DOES_NOT_PROVE`` tuple defined below is composed
# from its leaves' own tuples, and `tests/test_p3_storefront_ocr.py` reads it from this package.
from parcel_robot.storefront.fixtures import DOES_NOT_PROVE as FIXTURE_DOES_NOT_PROVE
from parcel_robot.storefront.ingest import DOES_NOT_PROVE as INGEST_DOES_NOT_PROVE
from parcel_robot.storefront.ocr import UNVERIFIED_PADDLE_OCR

DOES_NOT_PROVE = FIXTURE_DOES_NOT_PROVE + INGEST_DOES_NOT_PROVE + UNVERIFIED_PADDLE_OCR

__all__ = [
    "DOES_NOT_PROVE",
]
