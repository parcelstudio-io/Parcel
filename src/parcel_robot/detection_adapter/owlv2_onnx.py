"""OWLv2 open-vocabulary DETECTOR behind the ``Detector`` protocol — ONNX Runtime, no torch.

This is the **B3 real detector**: the one that makes camera-search real behind the
proven ``detection_adapter.pixel_detections.Detector`` seam. Where
:class:`~parcel_robot.detection_adapter.pixel_detections.SegTruthDetector` reads
MuJoCo segmentation-truth as a *perfect* detector (geometry-only ruler), this runs
a real open-vocabulary model on the rendered RGB and returns boxes with
``label``/``score`` and ``seg_id=None`` — the localizer then falls back to the
box-interior valid-depth mask. The only new error it introduces is RECOGNITION,
which shows up as a non-zero localization error and a right-object rate < 1.0
against the same seg-truth ruler (that DELTA is the honest recognition number the
P0 stance predicts).

Model
-----
``google/owlv2-base-patch16-ensemble`` (**Apache-2.0**), fetched as the int8 ONNX
export ``onnx-community/owlv2-base-patch16-ensemble-ONNX`` by
``scripts/fetch_owlv2.sh`` into ``~/.cache/parcel/owlv2-b16``. Runs under
``onnxruntime`` (CPU) — the exact no-torch/no-sudo pattern the SigLIP-2 int8 ONNX
path proved (``instructnav/siglip2_onnx.py``). Text is tokenized with the
``tokenizers`` rust wheel (the CLIP tokenizer straight from ``tokenizer.json``);
images are preprocessed with numpy alone (pad-to-square + resize-960 + rescale +
CLIP mean/std). No PIL, no torch, no sudo.

The fused ONNX takes ``(input_ids[Q,16], attention_mask[Q,16], pixel_values[1,3,960,960])``
and returns ``logits[1,3600,Q]`` (one logit per candidate box × text query) and
``pred_boxes[1,3600,4]`` (cxcywh, normalized to the padded square). Decoding:
``score = sigmoid(logit)``; a detection is a (box, query) pair over the threshold,
its box mapped back to original-image pixels by ``* max(H, W)`` (OWLv2 pads
bottom-right, so the top-left origin is shared).

Activation is deliberately **opt-in**: :func:`load_owlv2_detector` returns ``None``
unless ``PARCEL_OWLV2_ONNX`` is truthy, so merely landing the weights on disk never
flips CI/mission onto a heavy CPU model. Absent weights / absent onnxruntime /
absent tokenizers => a **loud degrade** to "detector unavailable" (``None``), never
a crash — CI without weights stays byte-identical.

HONESTY (P0)
------------
Rendered MuJoCo textures are NOT photoreal, so OWLv2 recall on them tests the
pixels->localize->ground->lock-on pipeline + a *floor* of recognition, NOT
real-world D455 recognition (that is a hardware re-earn). No real-world recognition
accuracy is claimed from any sim number.
"""

from __future__ import annotations

import json
import logging
import math
import os
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from parcel_robot.detection_adapter.pixel_detections import PixelDetection

logger = logging.getLogger(__name__)

#: OWLv2 text encoder is a CLIP text tower with fixed 16-token sequences
#: (``model_max_length`` in tokenizer_config.json). Text MUST be padded/truncated
#: to exactly this or the pooled query vector drifts off the trained distribution.
OWLV2_TEXT_SEQ_LEN = 16

#: OWLv2-base-patch16 renders at 960×960 → (960/16)² = 3600 candidate boxes.
OWLV2_IMAGE_SIZE = 960
OWLV2_NUM_PATCHES = 3600

#: Env switch. Truthy => attempt the real ONNX load; anything else => stay
#: "detector unavailable" even when the weights are present (keeps CI/mission
#: byte-identical — the honest "don't silently make it in-loop" lever).
ONNX_ENABLE_ENV = "PARCEL_OWLV2_ONNX"

#: Weights-dir + threshold overrides (mirror the SigLIP env knobs).
WEIGHTS_DIR_ENV = "PARCEL_OWLV2_DIR"
THRESHOLD_ENV = "PARCEL_OWLV2_THRESHOLD"
THREADS_ENV = "PARCEL_OWLV2_THREADS"

#: Detection score gate. sigmoid(logit) below this is dropped. 0.1 is the common
#: transformers OWLv2 default; env-overridable for calibration on a real pack.
DEFAULT_OWLV2_THRESHOLD = 0.1

#: Per-query NMS IoU: boxes overlapping more than this keep only the top score.
DEFAULT_NMS_IOU = 0.3

#: Cap detections per frame so a low threshold cannot explode the localizer.
DEFAULT_MAX_DETECTIONS = 64

_MODEL_ONNX_CANDIDATES = ("model_int8.onnx", "model_quantized.onnx", "model_uint8.onnx", "model.onnx")

DOES_NOT_PROVE = (
    (
        "OWLv2 runs on rendered MuJoCo pixels, which are NOT photoreal: its recall "
        "here tests the pixels->localize->ground->lock-on pipeline + a FLOOR of "
        "recognition, NOT real-world D455 recognition (that is a hardware re-earn)."
    ),
    (
        "The right-object / localization DELTA between OWLv2 and SegTruthDetector is "
        "the honest sim RECOGNITION error on top of already-proven geometry; it is "
        "not a claim about field recall/precision."
    ),
)


def onnx_enabled() -> bool:
    """True when the opt-in env switch selects the real ONNX detector path."""

    return os.environ.get(ONNX_ENABLE_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def default_weights_dir() -> Path:
    """Cache dir ``scripts/fetch_owlv2.sh`` writes (``PARCEL_OWLV2_DIR`` override)."""

    override = os.environ.get(WEIGHTS_DIR_ENV, "").strip()
    if override:
        return Path(override).expanduser()
    return Path.home() / ".cache" / "parcel" / "owlv2-b16"


def _first_present(weights_dir: Path, names: tuple[str, ...]) -> Path | None:
    for name in names:
        candidate = weights_dir / name
        if candidate.is_file():
            return candidate
    return None


def owlv2_weights_present(weights_dir: Path | None = None) -> bool:
    """True when the model ONNX + tokenizer.json are on disk (independent of the env switch)."""

    wd = weights_dir if weights_dir is not None else default_weights_dir()
    return _first_present(wd, _MODEL_ONNX_CANDIDATES) is not None and (wd / "tokenizer.json").is_file()


def _threshold_default() -> float:
    raw = os.environ.get(THRESHOLD_ENV, "").strip()
    if raw:
        try:
            return float(raw)
        except ValueError:
            logger.warning("bad %s=%r; using default %s", THRESHOLD_ENV, raw, DEFAULT_OWLV2_THRESHOLD)
    return DEFAULT_OWLV2_THRESHOLD


def load_owlv2_detector(
    weights_dir: Path | None = None,
    *,
    threshold: float | None = None,
    require_env: bool = True,
) -> OwlV2Detector | None:
    """Load the OWLv2 ONNX detector, or ``None`` if disabled / unavailable.

    Returns ``None`` (never raises) when the env switch is off (and ``require_env``),
    a required file is missing, or ``onnxruntime`` / ``tokenizers`` / ``numpy`` are
    absent — the caller then degrades loudly to "detector unavailable" and any tier
    that keys on it stays byte-identical to the no-detector path. ``require_env`` is
    the opt-in gate; pass ``False`` only from a test/gate that has already decided to
    run the real model.
    """

    if require_env and not onnx_enabled():
        return None
    wd = weights_dir if weights_dir is not None else default_weights_dir()
    model_onnx = _first_present(wd, _MODEL_ONNX_CANDIDATES)
    tokenizer_json = wd / "tokenizer.json"
    if model_onnx is None or not tokenizer_json.is_file():
        logger.warning(
            "OWLv2 requested but files missing under %s (model=%s tokenizer=%s) — detector unavailable",
            wd, model_onnx is not None, tokenizer_json.is_file(),
        )
        return None
    try:
        return OwlV2Detector(
            wd, model_onnx, threshold=threshold if threshold is not None else _threshold_default()
        )
    except Exception as exc:  # noqa: BLE001 — any load failure => degrade, never crash the pipeline
        logger.warning("OWLv2 ONNX load failed (%s: %s) — detector unavailable", type(exc).__name__, exc)
        return None


class OwlV2Detector:
    """onnxruntime-backed OWLv2 open-vocab detector satisfying ``detection_adapter.Detector``.

    ``detect(*, rgb, depth, seg, query) -> list[PixelDetection]`` runs the model on
    ``rgb`` (HxWx3 uint8/float, RGB) for the free-text ``query`` phrase(s) and returns
    boxes with ``seg_id=None`` (the localizer falls back to the box-interior mask).
    ``depth`` / ``seg`` are ignored — a real detector is box-only.
    """

    name = "owlv2"

    def __init__(self, weights_dir: Path, model_onnx: Path, *, threshold: float = DEFAULT_OWLV2_THRESHOLD) -> None:
        import numpy as np
        import onnxruntime as ort
        from tokenizers import Tokenizer

        self._np = np
        self._weights_dir = Path(weights_dir)
        self.threshold = float(threshold)
        self.nms_iou = DEFAULT_NMS_IOU
        self.max_detections = DEFAULT_MAX_DETECTIONS

        # CLIP tokenizer straight from tokenizer.json (rust fast tokenizer). It adds
        # <|startoftext|>/<|endoftext|> via its post-processor; OWLv2 lower-cases and
        # right-pads/truncates to a fixed 16 with pad id 0 ("!"), attention_mask 0 on pad.
        self._tok = Tokenizer.from_file(str(self._weights_dir / "tokenizer.json"))
        pad_id = self._tok.token_to_id("!")
        self._pad_id = int(pad_id) if pad_id is not None else 0

        opts = ort.SessionOptions()
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        opts.intra_op_num_threads = int(os.environ.get(THREADS_ENV, "0") or 0)
        self._session = ort.InferenceSession(
            str(model_onnx), sess_options=opts, providers=["CPUExecutionProvider"]
        )
        names = {i.name for i in self._session.get_inputs()}
        for required in ("input_ids", "attention_mask", "pixel_values"):
            if required not in names:
                raise ValueError(f"OWLv2 ONNX missing input {required!r}; got {sorted(names)}")

        # Image preprocessing params from preprocessor_config.json (fall back to the
        # published OWLv2 / CLIP defaults if the file is unexpectedly shaped).
        cfg: dict[str, Any] = {}
        pcfg = self._weights_dir / "preprocessor_config.json"
        if pcfg.is_file():
            try:
                cfg = json.loads(pcfg.read_text())
            except Exception:  # noqa: BLE001
                cfg = {}
        size = cfg.get("size") or {}
        self._img_h = int(size.get("height", OWLV2_IMAGE_SIZE))
        self._img_w = int(size.get("width", OWLV2_IMAGE_SIZE))
        self._img_mean = np.asarray(
            cfg.get("image_mean", [0.48145466, 0.4578275, 0.40821073]), dtype=np.float32
        )
        self._img_std = np.asarray(
            cfg.get("image_std", [0.26862954, 0.26130258, 0.27577711]), dtype=np.float32
        )
        self._rescale = float(cfg.get("rescale_factor", 1.0 / 255.0))
        self._pad_value = 0.5  # OWLv2 pads the rescaled image to square with gray 0.5

    # ---- Detector protocol -------------------------------------------------
    def detect(
        self,
        *,
        rgb: Any | None,
        depth: Any | None,  # box-only detector ignores depth/seg (the localizer uses them)
        seg: Any | None,
        query: str | Sequence[str] | None,
    ) -> list[PixelDetection]:
        np = self._np
        if rgb is None:
            return []
        phrases = _normalize_phrases(query)
        if not phrases:
            return []
        arr = np.asarray(rgb)
        if arr.ndim != 3 or arr.shape[2] < 3:
            raise ValueError(f"OWLv2 expects an HxWx3 RGB image, got shape {arr.shape}")
        h, w = int(arr.shape[0]), int(arr.shape[1])
        square = float(max(h, w))

        pixel_values = self._preprocess_image(arr)  # (1, 3, H, W)
        input_ids, attention_mask = self._tokenize(phrases)  # (Q, 16) each

        logits, pred_boxes = self._session.run(
            ["logits", "pred_boxes"],
            {
                "input_ids": input_ids,
                "attention_mask": attention_mask,
                "pixel_values": pixel_values,
            },
        )
        # logits: (1, 3600, Q); pred_boxes: (1, 3600, 4) cxcywh normalized-to-square.
        logits = np.asarray(logits)[0]
        boxes_cxcywh = np.asarray(pred_boxes)[0]
        scores = 1.0 / (1.0 + np.exp(-logits))  # sigmoid

        raw: list[tuple[float, str, tuple[int, int, int, int]]] = []
        for qi, phrase in enumerate(phrases):
            col = scores[:, qi]
            hits = np.where(col >= self.threshold)[0]
            for p in hits:
                box = self._box_to_pixels(boxes_cxcywh[p], square, w, h)
                if box is None:
                    continue
                raw.append((float(col[p]), phrase, box))

        kept = _nms(raw, self.nms_iou, self.max_detections)
        out: list[PixelDetection] = []
        for score, label, (u0, v0, u1, v1) in kept:
            out.append(
                PixelDetection(
                    label=label,
                    score=float(min(1.0, max(0.0, score))),
                    box=(u0, v0, u1, v1),
                    seg_id=None,
                    instance_key=None,
                )
            )
        # Deterministic order: top-down then left-right (matches SegTruthDetector).
        out.sort(key=lambda d: (d.box[1], d.box[0], -d.score))
        return out

    # ---- text --------------------------------------------------------------
    def _tokenize(self, phrases: list[str]) -> tuple[Any, Any]:
        np = self._np
        ids_rows: list[list[int]] = []
        mask_rows: list[list[int]] = []
        for phrase in phrases:
            enc = self._tok.encode(phrase.lower())
            ids = list(enc.ids)[:OWLV2_TEXT_SEQ_LEN]
            mask = [1] * len(ids)
            if len(ids) < OWLV2_TEXT_SEQ_LEN:
                pad = OWLV2_TEXT_SEQ_LEN - len(ids)
                ids = ids + [self._pad_id] * pad
                mask = mask + [0] * pad
            ids_rows.append(ids)
            mask_rows.append(mask)
        return (
            np.asarray(ids_rows, dtype=np.int64),
            np.asarray(mask_rows, dtype=np.int64),
        )

    # ---- image -------------------------------------------------------------
    def _preprocess_image(self, arr: Any) -> Any:
        """numpy-only OWLv2 preprocess: HxWx3 [0..255] -> (1,3,960,960) normalized.

        Order matches ``Owlv2ImageProcessor``: rescale (1/255) -> pad to square with
        gray 0.5 (bottom-right) -> bilinear resize to 960 -> CLIP mean/std normalize.
        """

        np = self._np
        arr = np.asarray(arr)
        if arr.shape[2] == 4:
            arr = arr[:, :, :3]
        arr = arr.astype(np.float32) * self._rescale
        h, w = arr.shape[0], arr.shape[1]
        side = max(h, w)
        if h != side or w != side:
            padded = np.full((side, side, 3), self._pad_value, dtype=np.float32)
            padded[:h, :w, :] = arr
            arr = padded
        resized = self._bilinear_resize(arr, self._img_h, self._img_w)
        resized = (resized - self._img_mean) / self._img_std
        chw = np.transpose(resized, (2, 0, 1))  # HWC -> CHW
        return chw[None, ...].astype(np.float32)

    def _bilinear_resize(self, arr: Any, out_h: int, out_w: int) -> Any:
        np = self._np
        in_h, in_w = arr.shape[0], arr.shape[1]
        if in_h == out_h and in_w == out_w:
            return arr
        # half-pixel-centered sampling (align_corners=False), matching PIL/HF bilinear.
        ys = (np.arange(out_h, dtype=np.float32) + 0.5) * (in_h / out_h) - 0.5
        xs = (np.arange(out_w, dtype=np.float32) + 0.5) * (in_w / out_w) - 0.5
        ys = np.clip(ys, 0, in_h - 1)
        xs = np.clip(xs, 0, in_w - 1)
        y0 = np.floor(ys).astype(np.int64); y1 = np.minimum(y0 + 1, in_h - 1)
        x0 = np.floor(xs).astype(np.int64); x1 = np.minimum(x0 + 1, in_w - 1)
        wy = (ys - y0)[:, None, None]; wx = (xs - x0)[None, :, None]
        top = arr[y0][:, x0] * (1 - wx) + arr[y0][:, x1] * wx
        bot = arr[y1][:, x0] * (1 - wx) + arr[y1][:, x1] * wx
        return top * (1 - wy) + bot * wy

    # ---- box decode --------------------------------------------------------
    def _box_to_pixels(
        self, box_cxcywh: Any, square: float, img_w: int, img_h: int
    ) -> tuple[int, int, int, int] | None:
        """cxcywh (normalized to the padded square) -> integer (u0,v0,u1,v1) in image px.

        OWLv2 pads the image bottom-right to a square of side ``max(H, W)`` before
        resizing, so a normalized coordinate maps to original-image pixels by
        ``* square`` (top-left origin shared). Boxes are clipped to the image; a box
        that lands entirely in the padded region (or has no positive extent after
        clipping) is dropped.
        """

        cx, cy, bw, bh = (float(v) for v in box_cxcywh)
        x0 = (cx - bw / 2.0) * square
        y0 = (cy - bh / 2.0) * square
        x1 = (cx + bw / 2.0) * square
        y1 = (cy + bh / 2.0) * square
        u0 = math.floor(max(0.0, min(x0, x1)))
        v0 = math.floor(max(0.0, min(y0, y1)))
        u1 = math.ceil(min(float(img_w), max(x0, x1)))
        v1 = math.ceil(min(float(img_h), max(y0, y1)))
        if u1 <= u0 or v1 <= v0:
            return None
        return (u0, v0, u1, v1)


def _normalize_phrases(query: str | Sequence[str] | None) -> list[str]:
    """Query -> ordered unique free-text phrases; ``_``/`-` -> space for sim nouns."""

    if query is None:
        return []
    items = [query] if isinstance(query, str) else list(query)
    seen: set[str] = set()
    out: list[str] = []
    for q in items:
        phrase = str(q).replace("_", " ").replace("-", " ").strip().lower()
        if phrase and phrase not in seen:
            seen.add(phrase)
            out.append(phrase)
    return out


def _iou(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    ix0, iy0 = max(ax0, bx0), max(ay0, by0)
    ix1, iy1 = min(ax1, bx1), min(ay1, by1)
    iw, ih = max(0, ix1 - ix0), max(0, iy1 - iy0)
    inter = iw * ih
    if inter == 0:
        return 0.0
    area_a = (ax1 - ax0) * (ay1 - ay0)
    area_b = (bx1 - bx0) * (by1 - by0)
    return inter / float(area_a + area_b - inter)


def _nms(
    raw: list[tuple[float, str, tuple[int, int, int, int]]], iou_thresh: float, max_keep: int
) -> list[tuple[float, str, tuple[int, int, int, int]]]:
    """Per-label greedy NMS, then cap to ``max_keep`` by score."""

    kept: list[tuple[float, str, tuple[int, int, int, int]]] = []
    for score, label, box in sorted(raw, key=lambda r: r[0], reverse=True):
        if any(lbl == label and _iou(box, kbox) > iou_thresh for _, lbl, kbox in kept):
            continue
        kept.append((score, label, box))
        if len(kept) >= max_keep:
            break
    return kept
