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
``onnxruntime`` — the exact no-torch/no-sudo pattern the SigLIP-2 int8 ONNX
path proved (``instructnav/siglip2_onnx.py``). Text is tokenized with the
``tokenizers`` rust wheel (the CLIP tokenizer straight from ``tokenizer.json``);
images are preprocessed with numpy alone (pad-to-square + resize-960 + rescale +
CLIP mean/std). No PIL, no torch, no sudo.

Execution provider (card PG-1)
------------------------------
Which (execution provider, artifact) pair runs is no longer hard-coded: it is
resolved by :mod:`parcel_robot.perception_providers` with the documented
fallback order ``cuda_fp16 -> cpu_int8``, and **logged once at construction** on
:attr:`OwlV2Detector.resolution`. A machine with no ``CUDAExecutionProvider``
resolves to ``cpu_int8`` and is byte-for-byte the incumbent path. Nothing about
the ``Detector`` protocol changes; ``detect()`` has the same signature and the
same return type on either provider.

Preprocessing (card PG-1, items 2-3)
------------------------------------
Two SEPARATE changes live here, and conflating them would be the easiest way to
smuggle a quality regression past an audit, so they are kept apart by name:

``fast_preprocess`` (default **ON**, provably lossless)
    A restructuring of the same arithmetic. It (a) never materialises the
    ``max(H,W)`` padded square, resizing the content directly into a pre-filled
    grey canvas, and (b) does the horizontal blend once over the source rows
    instead of gathering four wide row-slices. Every element of the model input
    is **bit-identical** to the reference path — asserted, not asserted-by-
    docstring, in ``tests/test_owlv2_detector.py`` over the real 42-frame bench
    corpus plus adversarial shapes. It is guarded: when the content/pad seam does
    not land exactly on an output-pixel boundary (which happens whenever the
    source's long edge is *below* 960 and the model is up-sampling), the fast
    path provably would NOT be equal, and the code detects that case exactly and
    runs the reference path instead.

``source_max_edge`` (default **OFF**, genuinely lossy)
    Downscales the source before preprocessing. The PG-1 card inherited a claim
    that this is "a free 2.8x with bit-identical tensors". **Measured against
    this module's own preprocessor, that claim is false** — halving the source
    edge changes the model input by up to 1.278 (normalised units) across 5.5%
    of its elements. It is landed as an explicit, default-off, documented-lossy
    knob with a measured quality delta, never as a free win. See ``PG1_STATUS.md``.

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
from parcel_robot.perception_contention import PerceptionContentionGuard, default_guard
from parcel_robot.perception_providers import (
    PROVIDER_CPU_INT8,
    ProviderResolution,
    assert_provider_honoured,
    log_resolution,
    prepare_cuda_runtime,
    resolve_provider,
)

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

#: onnxruntime input type string -> numpy dtype name, for the feed-boundary cast.
_ORT_TO_NUMPY: dict[str, str] = {
    "tensor(float)": "float32",
    "tensor(float16)": "float16",
}

#: fp16 artifact for the CUDA path. Same ``onnx-community`` export repo and same
#: upstream Apache-2.0 checkpoint as the int8 file ``scripts/fetch_owlv2.sh``
#: already pins — a different *precision* of one model, not a different model.
_MODEL_ONNX_FP16_CANDIDATES = ("model_fp16.onnx",)

#: Preprocessing knobs. ``FAST_PREPROCESS_ENV`` defaults ON because the fast path
#: is bit-identical (pinned by test); the env var is an escape hatch, not a
#: feature flag. ``SOURCE_MAX_EDGE_ENV`` defaults OFF because it is NOT.
FAST_PREPROCESS_ENV = "PARCEL_OWLV2_FAST_PREPROCESS"
SOURCE_MAX_EDGE_ENV = "PARCEL_OWLV2_SOURCE_MAX_EDGE"

#: Queries naming a human make an inference SAFETY-RELEVANT: post-cutover these
#: are what the person-yield / reactive-stop path consumes. While such an
#: inference is in flight the contention guard refuses to let a long-running
#: generation START, so the yield path can never queue behind a scene
#: description (card PG-1 item 4). Deliberately narrow: a lease costs *speech*
#: latency, so widening it to every label would block generation permanently at
#: the CPU path's 1.8 Hz. Matching is on the normalised phrase, whole-word.
SAFETY_RELEVANT_LABELS = frozenset(
    {"person", "people", "pedestrian", "human", "owner", "child", "man", "woman"}
)

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
    (
        "Moving this model to CUDA fp16 changes LATENCY and numeric precision, not "
        "the world it looks at. The 2026-08-21 bench measured 0/69 person recall on "
        "Parcel renders vs 127/156 on real photos for this same checkpoint: the "
        "scene has no visual semantics. No recall/precision claim follows from the "
        "provider change, only a latency claim on the frames it was measured on."
    ),
    (
        "The contention guard refuses to START a long-running generation while a "
        "safety-relevant inference is in flight. It cannot PREEMPT a generation that "
        "is already running — that is not possible without killing it — so a "
        "generation begun before the lease still contends for its remaining duration."
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
    """True when a model ONNX + tokenizer.json are on disk (independent of the env switch).

    Either precision counts: an fp16-only install is a usable install on a CUDA
    box. The int8 names are probed first so a machine holding both keeps
    reporting on the incumbent artifact.
    """

    wd = weights_dir if weights_dir is not None else default_weights_dir()
    any_model = _first_present(wd, _MODEL_ONNX_CANDIDATES + _MODEL_ONNX_FP16_CANDIDATES)
    return any_model is not None and (wd / "tokenizer.json").is_file()


def fast_preprocess_enabled() -> bool:
    """Whether the bit-identical preprocessing fast path is on (default: yes)."""

    raw = os.environ.get(FAST_PREPROCESS_ENV, "").strip().lower()
    if not raw:
        return True
    return raw in {"1", "true", "yes", "on"}


def source_max_edge() -> int:
    """Configured lossy source-downscale long edge, or ``0`` when disabled (default).

    A malformed value disables the downscale rather than guessing: silently
    running at an unintended resolution is exactly the failure this knob is
    documented to avoid.
    """

    raw = os.environ.get(SOURCE_MAX_EDGE_ENV, "").strip()
    if not raw:
        return 0
    try:
        value = int(raw)
    except ValueError:
        logger.warning("bad %s=%r; source downscale stays OFF", SOURCE_MAX_EDGE_ENV, raw)
        return 0
    if value <= 0:
        return 0
    return value


def _threshold_default() -> float:
    raw = os.environ.get(THRESHOLD_ENV, "").strip()
    if raw:
        try:
            return float(raw)
        except ValueError:
            logger.warning("bad %s=%r; using default %s", THRESHOLD_ENV, raw, DEFAULT_OWLV2_THRESHOLD)
    return DEFAULT_OWLV2_THRESHOLD


def resolve_owlv2_provider(
    weights_dir: Path | None = None, *, requested: str | None = None, **kwargs: Any
) -> ProviderResolution:
    """Which (execution provider, artifact) pair this detector would run on.

    Exposed separately from the loader so the resolution table can be inspected
    and tested without constructing a session or touching a GPU.
    """

    wd = weights_dir if weights_dir is not None else default_weights_dir()
    return resolve_provider(
        wd,
        int8_candidates=_MODEL_ONNX_CANDIDATES,
        fp16_candidates=_MODEL_ONNX_FP16_CANDIDATES,
        requested=requested,
        **kwargs,
    )


def load_owlv2_detector(
    weights_dir: Path | None = None,
    *,
    threshold: float | None = None,
    require_env: bool = True,
    requested_provider: str | None = None,
) -> OwlV2Detector | None:
    """Load the OWLv2 ONNX detector, or ``None`` if disabled / unavailable.

    Returns ``None`` (never raises) when the env switch is off (and ``require_env``),
    a required file is missing, no execution provider in the documented fallback
    order is available, an explicitly pinned provider is unavailable, or
    ``onnxruntime`` / ``tokenizers`` / ``numpy`` are absent — the caller then
    degrades loudly to "detector unavailable" and any tier that keys on it stays
    byte-identical to the no-detector path. ``require_env`` is the opt-in gate;
    pass ``False`` only from a test/gate that has already decided to run the real
    model.
    """

    if require_env and not onnx_enabled():
        return None
    wd = weights_dir if weights_dir is not None else default_weights_dir()
    tokenizer_json = wd / "tokenizer.json"
    resolution = resolve_owlv2_provider(wd, requested=requested_provider)
    if resolution.selected is None or not tokenizer_json.is_file():
        # Log the full resolution (including every rejected provider) before
        # degrading, so "detector unavailable" is never an unexplained outcome.
        log_resolution(resolution, model="owlv2")
        logger.warning(
            "OWLv2 requested but unavailable under %s (provider=%s tokenizer=%s) — detector unavailable",
            wd, resolution.selected, tokenizer_json.is_file(),
        )
        return None
    try:
        return OwlV2Detector(
            wd,
            resolution.model_file,
            threshold=threshold if threshold is not None else _threshold_default(),
            resolution=resolution,
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

    #: Class-level defaults. These are set per-instance in ``__init__``; declaring
    #: them on the class keeps ``object.__new__(OwlV2Detector)`` shells (the
    #: no-weights test path) working and puts every default in one readable place.
    fast_preprocess: bool = True
    source_max_edge: int = 0
    provider: str = PROVIDER_CPU_INT8
    resolution: ProviderResolution | None = None
    guard: PerceptionContentionGuard | None = None
    safety_labels: frozenset[str] = SAFETY_RELEVANT_LABELS

    def __init__(
        self,
        weights_dir: Path,
        model_onnx: Path,
        *,
        threshold: float = DEFAULT_OWLV2_THRESHOLD,
        resolution: ProviderResolution | None = None,
        guard: PerceptionContentionGuard | None = None,
    ) -> None:
        import numpy as np
        import onnxruntime as ort
        from tokenizers import Tokenizer

        self._np = np
        self._weights_dir = Path(weights_dir)
        self.threshold = float(threshold)
        self.nms_iou = DEFAULT_NMS_IOU
        self.max_detections = DEFAULT_MAX_DETECTIONS
        self.fast_preprocess = fast_preprocess_enabled()
        self.source_max_edge = source_max_edge()
        self.guard = guard if guard is not None else default_guard()
        if resolution is None:
            resolution = resolve_owlv2_provider(self._weights_dir)
        self.resolution = resolution
        self.provider = resolution.selected or PROVIDER_CPU_INT8

        # CLIP tokenizer straight from tokenizer.json (rust fast tokenizer). It adds
        # <|startoftext|>/<|endoftext|> via its post-processor; OWLv2 lower-cases and
        # right-pads/truncates to a fixed 16 with pad id 0 ("!"), attention_mask 0 on pad.
        self._tok = Tokenizer.from_file(str(self._weights_dir / "tokenizer.json"))
        pad_id = self._tok.token_to_id("!")
        self._pad_id = int(pad_id) if pad_id is not None else 0

        opts = ort.SessionOptions()
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        opts.intra_op_num_threads = int(os.environ.get(THREADS_ENV, "0") or 0)
        providers = list(resolution.execution_providers) or ["CPUExecutionProvider"]
        prepare_cuda_runtime(resolution)  # must precede the session, see its docstring
        self._session = ort.InferenceSession(
            str(model_onnx), sess_options=opts, providers=providers
        )
        # Log the RESOLVED path once at construction, then FAIL CLOSED if ORT did
        # not actually honour it. Registration is not execution: onnxruntime-gpu
        # lists CUDAExecutionProvider from a stub and silently falls back to CPU
        # when its CUDA libraries are missing (measured on this machine during
        # PG-1: 726 ms/query while every log line still said "fp16").
        honoured = tuple(self._session.get_providers())
        log_resolution(resolution, model="owlv2")
        logger.info("[owlv2] onnxruntime honoured providers=%s", honoured)
        self.honoured_providers = honoured
        assert_provider_honoured(resolution, honoured, model="owlv2")

        inputs = {i.name: i for i in self._session.get_inputs()}
        for required in ("input_ids", "attention_mask", "pixel_values"):
            if required not in inputs:
                raise ValueError(
                    f"OWLv2 ONNX missing input {required!r}; got {sorted(inputs)}"
                )
        # The fp16 export declares pixel_values as tensor(float16). Preprocessing
        # stays in float32 (the reference numerics) and is cast ONCE at the feed
        # boundary, so the fast/reference bit-identity property is a property of
        # preprocessing and does not depend on which artifact is loaded.
        self._pixel_dtype = np.dtype(
            _ORT_TO_NUMPY.get(inputs["pixel_values"].type, "float32")
        )

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
        if rgb is None:
            return []
        phrases = _normalize_phrases(query)
        if not phrases:
            return []
        guard = self.guard
        if guard is not None and self.is_safety_relevant(phrases):
            # Declare the safety window. The detector never asks permission — it
            # runs. Holding the lease is what stops a scene description from
            # STARTING underneath a person query (card PG-1 item 4).
            with guard.mission_lease(f"owlv2 safety-relevant query: {'/'.join(phrases)}"):
                return self._detect_unguarded(rgb, phrases)
        return self._detect_unguarded(rgb, phrases)

    def is_safety_relevant(self, phrases: Sequence[str]) -> bool:
        """True when any normalised phrase names a human (whole-word match)."""

        labels = self.safety_labels
        return any(word in labels for phrase in phrases for word in str(phrase).split())

    def _detect_unguarded(self, rgb: Any, phrases: list[str]) -> list[PixelDetection]:
        np = self._np
        arr = np.asarray(rgb)
        if arr.ndim != 3 or arr.shape[2] < 3:
            raise ValueError(f"OWLv2 expects an HxWx3 RGB image, got shape {arr.shape}")
        h, w = int(arr.shape[0]), int(arr.shape[1])
        square = float(max(h, w))

        pixel_values = self._preprocess_image(arr)  # (1, 3, H, W) float32
        want = getattr(self, "_pixel_dtype", np.float32)
        if pixel_values.dtype != want:
            pixel_values = pixel_values.astype(want)
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

        Dispatches between :meth:`_preprocess_reference` (the original algorithm,
        kept verbatim as the numeric definition) and :meth:`_preprocess_fast`
        (bit-identical restructuring). ``source_max_edge``, when configured,
        applies a LOSSY downscale first — see the module docstring.
        """

        arr = self._np.asarray(arr)
        if self.source_max_edge:
            arr = self._downscale_source(arr, self.source_max_edge)
        if self.fast_preprocess:
            return self._preprocess_fast(arr)
        return self._preprocess_reference(arr)

    def _preprocess_reference(self, arr: Any) -> Any:
        """The reference preprocess — the DEFINITION the fast path is pinned against.

        Order matches ``Owlv2ImageProcessor``: rescale (1/255) -> pad to square with
        gray 0.5 (bottom-right) -> bilinear resize to 960 -> CLIP mean/std normalize.
        Kept byte-for-byte as it shipped so the equivalence test has a fixed
        reference and cannot drift along with the optimisation it is checking.
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

    def _preprocess_fast(self, arr: Any) -> Any:
        """Bit-identical restructuring of :meth:`_preprocess_reference`.

        Two independent, value-preserving moves:

        1. **Never build the padded square.** Resize the *content* straight to
           ``(960*h//side, 960*w//side)`` and paste it into a canvas pre-filled
           with the pad value. Valid only when no output sample straddles the
           content/pad seam — checked exactly by :meth:`_seam_is_clean`, never
           assumed. The canvas dtype must match the resize output: rounding to
           float32 before normalising double-rounds and drifts one ULP.
        2. **Blend horizontally once** (:meth:`_bilinear_resize_separable`).

        When the seam check fails the reference path runs, so this method is
        always exactly ``_preprocess_reference`` by value.
        """

        np = self._np
        arr = np.asarray(arr)
        h, w = int(arr.shape[0]), int(arr.shape[1])
        side = max(h, w)
        out_h = self._img_h * h // side
        out_w = self._img_w * w // side
        if not self._seam_is_clean(h, w, side, out_h, out_w):
            # The fast path provably would NOT be equal here. Fall back on the
            # UNTOUCHED input rather than silently changing the tensor.
            return self._preprocess_reference(arr)
        if arr.shape[2] == 4:
            arr = arr[:, :, :3]
        arr = arr.astype(np.float32) * self._rescale
        resized = self._bilinear_resize_separable(arr, out_h, out_w)
        canvas = np.full((self._img_h, self._img_w, 3), self._pad_value, dtype=resized.dtype)
        canvas[:out_h, :out_w, :] = resized
        canvas = (canvas - self._img_mean) / self._img_std
        chw = np.transpose(canvas, (2, 0, 1))
        return chw[None, ...].astype(np.float32)

    def _axis_samples(self, in_n: int, out_n: int) -> tuple[Any, Any, Any]:
        """Half-pixel-centred sample coordinates + the two source indices per output."""

        np = self._np
        zs = (np.arange(out_n, dtype=np.float32) + 0.5) * (in_n / out_n) - 0.5
        zs = np.clip(zs, 0, in_n - 1)
        z0 = np.floor(zs).astype(np.int64)
        z1 = np.minimum(z0 + 1, in_n - 1)
        return zs, z0, z1

    def _seam_is_clean(self, h: int, w: int, side: int, out_h: int, out_w: int) -> bool:
        """Exact test that no output sample mixes image content with grey padding.

        Content occupies rows ``[0, h)`` and columns ``[0, w)`` of the
        ``side x side`` square. The content-first path is equal to the reference
        iff output indices ``[0, out_n)`` sample only content and ``[out_n, 960)``
        sample only padding, on BOTH axes. That holds for 1280x720 and 1920x1080
        (the camera resolutions) and fails whenever the model is up-sampling a
        source whose long edge is under 960, where the boundary output pixel
        legitimately interpolates across the seam.
        """

        np = self._np
        for n_in, n_content, out_n, full in (
            (side, h, out_h, self._img_h),
            (side, w, out_w, self._img_w),
        ):
            _, z0, z1 = self._axis_samples(n_in, full)
            if not bool(np.all(z1[:out_n] <= n_content - 1)):
                return False
            if not bool(np.all(z0[out_n:] >= n_content)):
                return False
        return True

    def _downscale_source(self, arr: Any, max_edge: int) -> Any:
        """LOSSY source downscale to a long edge of ``max_edge``. Not bit-identical.

        Antialiases rather than aliases. Stride decimation (``arr[::2, ::2]``) is
        what the inherited bench used and it is nearly free, but it simply throws
        away three of every four pixels and folds high-frequency detail back into
        the image. This uses a box average instead, which is what a half-pixel
        bilinear kernel degenerates to at an exact integer reduction.

        Two paths, same result for the integer case:

        * **exact integer factor** (1280x720 -> 640x360 is factor 2): a reshape +
          ``mean`` over the block axes. Vectorised and cheap.
        * **any other factor**: the general separable bilinear resize, which costs
          about as much as the preprocessing resize it is trying to save. That is
          measured and reported rather than hidden — for non-integer factors this
          knob can be a net latency LOSS.
        """

        arr = self._np.asarray(arr)
        h, w = arr.shape[0], arr.shape[1]
        side = max(h, w)
        if side <= max_edge:
            return arr
        if arr.ndim == 3 and arr.shape[2] == 4:
            arr = arr[:, :, :3]
        factor = side // max_edge
        if factor >= 2 and side % max_edge == 0 and h % factor == 0 and w % factor == 0:
            blocks = arr.reshape(h // factor, factor, w // factor, factor, arr.shape[2])
            return blocks.astype(self._np.float32).mean(axis=(1, 3))
        scale = max_edge / float(side)
        out_h = max(1, round(h * scale))
        out_w = max(1, round(w * scale))
        return self._bilinear_resize_separable(arr.astype(self._np.float32), out_h, out_w)

    def _bilinear_resize(self, arr: Any, out_h: int, out_w: int) -> Any:
        in_h, in_w = arr.shape[0], arr.shape[1]
        if in_h == out_h and in_w == out_w:
            return arr
        # half-pixel-centered sampling (align_corners=False), matching PIL/HF bilinear.
        ys, y0, y1 = self._axis_samples(in_h, out_h)
        xs, x0, x1 = self._axis_samples(in_w, out_w)
        wy = (ys - y0)[:, None, None]; wx = (xs - x0)[None, :, None]
        top = arr[y0][:, x0] * (1 - wx) + arr[y0][:, x1] * wx
        bot = arr[y1][:, x0] * (1 - wx) + arr[y1][:, x1] * wx
        return top * (1 - wy) + bot * wy

    def _bilinear_resize_separable(self, arr: Any, out_h: int, out_w: int) -> Any:
        """Bit-identical to :meth:`_bilinear_resize`, with half the gathers.

        ``_bilinear_resize`` writes ``arr[y0]`` and ``arr[y1]`` twice each, so
        numpy materialises four ``out_h x in_w x 3`` row-gathers. Blending
        horizontally first over all ``in_h`` rows computes the *same* per-element
        expression — ``H[y] = arr[y][x0]*(1-wx) + arr[y][x1]*wx``, then
        ``top, bot = H[y0], H[y1]`` — with two narrow gathers instead.
        """

        in_h, in_w = arr.shape[0], arr.shape[1]
        if in_h == out_h and in_w == out_w:
            return arr
        ys, y0, y1 = self._axis_samples(in_h, out_h)
        xs, x0, x1 = self._axis_samples(in_w, out_w)
        wy = (ys - y0)[:, None, None]; wx = (xs - x0)[None, :, None]
        horiz = arr[:, x0] * (1 - wx) + arr[:, x1] * wx  # (in_h, out_w, 3)
        return horiz[y0] * (1 - wy) + horiz[y1] * wy

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
