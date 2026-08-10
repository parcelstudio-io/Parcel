"""OCR engines for P3 storefront sim — fake (CI) + optional PP-OCR (UNVERIFIED).

Default path never imports paddleocr. The optional real-OCR path is marked
UNVERIFIED and skipped when the dependency is absent.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

import numpy as np

from parcel_robot.storefront.fixtures import StorefrontFixture
from parcel_robot.storefront.placards import normalize_sign_text

OcrBackendKind = Literal["fake", "paddleocr"]

# Vendor / optional dependency — never claimed as validated in CI.
UNVERIFIED_PADDLE_OCR = (
    ("Optional paddleocr / PP-OCR path is UNVERIFIED: not a CI dependency, "
    "not run on wild storefront pixels, and not a P5 hardware gate pass."),
    "PP-OCRv6 Orin latency/accuracy figures remain vendor-reported (U29).",
)


@dataclass(frozen=True, slots=True)
class OcrHit:
    """One text detection on a synthetic (or optional real-OCR) frame."""

    text: str
    score: float
    # Pixel bbox (x0, y0, x1, y1) in the RGB frame; None for metadata-only fake.
    bbox_xyxy: tuple[int, int, int, int] | None
    storefront_id: str = ""
    brand: str = ""
    bearing_rad: float | None = None
    range_m: float | None = None
    backend: OcrBackendKind = "fake"
    evidence_ref: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.text, str) or not self.text.strip():
            raise ValueError("text must be a non-empty string")
        if isinstance(self.score, bool) or not isinstance(self.score, (int, float)):
            raise TypeError("score must be numeric")
        if not 0.0 <= float(self.score) <= 1.0:
            raise ValueError("score must be in [0, 1]")
        if self.bbox_xyxy is not None:
            if len(self.bbox_xyxy) != 4:
                raise ValueError("bbox_xyxy must have length 4")
            x0, y0, x1, y1 = self.bbox_xyxy
            if x1 <= x0 or y1 <= y0:
                raise ValueError("bbox_xyxy must be a non-empty rectangle")

    def as_dict(self) -> dict[str, object]:
        return {
            "text": self.text,
            "score": float(self.score),
            "bbox_xyxy": list(self.bbox_xyxy) if self.bbox_xyxy is not None else None,
            "storefront_id": self.storefront_id,
            "brand": self.brand,
            "bearing_rad": self.bearing_rad,
            "range_m": self.range_m,
            "backend": self.backend,
            "evidence_ref": self.evidence_ref,
        }


@runtime_checkable
class OcrEngine(Protocol):
    kind: OcrBackendKind

    def recognize(
        self,
        rgb: np.ndarray,
        *,
        fixtures: Sequence[StorefrontFixture] = (),
        sequence: int = 0,
    ) -> tuple[OcrHit, ...]:
        """Return OCR hits for an RGB frame (H, W, 3) uint8."""


def _roi_pixels(
    roi_norm: tuple[float, float, float, float],
    *,
    width: int,
    height: int,
) -> tuple[int, int, int, int]:
    x0, y0, x1, y1 = roi_norm
    px0 = max(0, min(width - 1, round(x0 * width)))
    py0 = max(0, min(height - 1, round(y0 * height)))
    px1 = max(px0 + 1, min(width, round(x1 * width)))
    py1 = max(py0 + 1, min(height, round(y1 * height)))
    return px0, py0, px1, py1


class FakeOcrEngine:
    """CI OCR: emit hits from fixture metadata (does not read pixels).

    Honesty: this proves wiring (DetectionMsg / SemanticMemory ingest), not
    that a vision model can read the placard. Prefer ``open_ocr_engine``.
    """

    kind: OcrBackendKind = "fake"

    def recognize(
        self,
        rgb: np.ndarray,
        *,
        fixtures: Sequence[StorefrontFixture] = (),
        sequence: int = 0,
    ) -> tuple[OcrHit, ...]:
        if not isinstance(rgb, np.ndarray) or rgb.ndim != 3 or rgb.shape[2] != 3:
            raise TypeError("rgb must be HxWx3 ndarray")
        h, w = rgb.shape[:2]
        hits: list[OcrHit] = []
        for fixture in fixtures:
            bbox = _roi_pixels(fixture.roi_norm, width=w, height=h)
            text = normalize_sign_text(fixture.expected_text)
            hits.append(
                OcrHit(
                    text=text,
                    score=0.99,
                    bbox_xyxy=bbox,
                    storefront_id=fixture.id,
                    brand=fixture.brand,
                    bearing_rad=fixture.bearing_rad,
                    range_m=fixture.range_m,
                    backend="fake",
                    evidence_ref=f"ocr:fake:{fixture.id}:seq{sequence}",
                )
            )
        return tuple(hits)


class PaddleOcrEngine:
    """Optional PP-OCR wrapper — **UNVERIFIED**, not a CI dependency.

    Instantiation imports paddleocr only when constructed. Failures surface as
    ImportError / RuntimeError; callers should fall back via ``open_ocr_engine``.
    """

    kind: OcrBackendKind = "paddleocr"

    def __init__(self, *, min_score: float = 0.5) -> None:
        try:
            from paddleocr import PaddleOCR  # type: ignore[import-not-found]
        except Exception as exc:
            raise ImportError(
                "paddleocr is not installed; use FakeOcrEngine or "
                "open_ocr_engine(prefer='fake'). UNVERIFIED optional path."
            ) from exc
        if isinstance(min_score, bool) or not isinstance(min_score, (int, float)):
            raise TypeError("min_score must be numeric")
        if not 0.0 <= float(min_score) <= 1.0:
            raise ValueError("min_score must be in [0, 1]")
        self._min_score = float(min_score)
        # lang=en covers Latin storefront text in the fixture pack.
        self._ocr = PaddleOCR(use_angle_cls=True, lang="en", show_log=False)

    def recognize(
        self,
        rgb: np.ndarray,
        *,
        fixtures: Sequence[StorefrontFixture] = (),
        sequence: int = 0,
    ) -> tuple[OcrHit, ...]:
        if not isinstance(rgb, np.ndarray) or rgb.ndim != 3 or rgb.shape[2] != 3:
            raise TypeError("rgb must be HxWx3 ndarray")
        # PaddleOCR expects BGR ndarray historically.
        bgr = rgb[:, :, ::-1].copy()
        raw = self._ocr.ocr(bgr, cls=True)
        hits: list[OcrHit] = []
        lines = raw[0] if raw and raw[0] else []
        for index, line in enumerate(lines or []):
            box, (text, score) = line
            score_f = float(score)
            if score_f < self._min_score:
                continue
            xs = [float(p[0]) for p in box]
            ys = [float(p[1]) for p in box]
            bbox = (
                int(min(xs)),
                int(min(ys)),
                int(max(xs)),
                int(max(ys)),
            )
            matched = _match_fixture(text, bbox, fixtures, rgb.shape[1], rgb.shape[0])
            hits.append(
                OcrHit(
                    text=normalize_sign_text(str(text)),
                    score=score_f,
                    bbox_xyxy=bbox,
                    storefront_id=matched.id if matched else "",
                    brand=matched.brand if matched else "",
                    bearing_rad=matched.bearing_rad if matched else None,
                    range_m=matched.range_m if matched else None,
                    backend="paddleocr",
                    evidence_ref=f"ocr:paddle:{index}:seq{sequence}",
                )
            )
        return tuple(hits)


def _match_fixture(
    text: str,
    bbox: tuple[int, int, int, int],
    fixtures: Sequence[StorefrontFixture],
    width: int,
    height: int,
) -> StorefrontFixture | None:
    norm = normalize_sign_text(text)
    best: StorefrontFixture | None = None
    best_score = -1.0
    cx = 0.5 * (bbox[0] + bbox[2]) / max(1, width)
    cy = 0.5 * (bbox[1] + bbox[3]) / max(1, height)
    for fixture in fixtures:
        x0, y0, x1, y1 = fixture.roi_norm
        inside = x0 <= cx <= x1 and y0 <= cy <= y1
        expected = normalize_sign_text(fixture.expected_text)
        overlap = 1.0 if expected and expected in norm else 0.0
        if expected == norm:
            overlap = 1.5
        score = (2.0 if inside else 0.0) + overlap
        if score > best_score:
            best_score = score
            best = fixture
    return best if best_score > 0.0 else None


def paddleocr_available() -> bool:
    try:
        import importlib.util

        return importlib.util.find_spec("paddleocr") is not None
    except Exception:  # noqa: BLE001
        return False


def open_ocr_engine(
    prefer: Literal["auto", "fake", "paddleocr"] = "auto",
) -> tuple[OcrEngine, OcrBackendKind]:
    """Select OCR backend. Default CI path is always ``fake`` without deps."""

    if prefer == "fake":
        return FakeOcrEngine(), "fake"
    if prefer == "paddleocr":
        return PaddleOcrEngine(), "paddleocr"
    # auto
    if paddleocr_available():
        try:
            return PaddleOcrEngine(), "paddleocr"
        except Exception:  # noqa: BLE001 — fall back honestly
            return FakeOcrEngine(), "fake"
    return FakeOcrEngine(), "fake"


def texts_match(expected: str, observed: str) -> bool:
    """Loose match for smoke: normalized containment either way."""

    a = normalize_sign_text(expected)
    b = normalize_sign_text(observed)
    if not a or not b:
        return False
    return a == b or a in b or b in a
