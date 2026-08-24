"""ONNX Runtime backend for the SigLIP-2 text+image embedder — no torch, no transformers.

This is the *real weights* path behind :class:`parcel_robot.instructnav.siglip.SigLIP2Matcher`.
It loads the int8 ONNX encoders that ``scripts/fetch_siglip2.sh`` lands in
``~/.cache/parcel/siglip2-b16`` and runs them under ``onnxruntime`` (CPU) — the
exact no-torch pattern the audio stack uses for Silero / smart-turn. Text is
tokenized with the ``tokenizers`` rust wheel (the SigLIP GemmaTokenizer, loaded
straight from the bundled ``tokenizer.json``); images are preprocessed with
numpy alone (resize-224 + rescale + mean/std normalize read from
``preprocessor_config.json``). No PIL, no torch, no sudo.

``embed_text`` / ``embed_image`` return L2-normalized float tuples of length
:data:`SIGLIP2_EMBED_DIM`, matching the synthetic/real seam the matcher expects.

Activation is deliberately **opt-in**: :func:`load_onnx_embedder` returns ``None``
unless ``PARCEL_SIGLIP2_ONNX`` is truthy, so merely landing the weights on disk
never flips the whole test suite / mission path onto a ~N-ms/query neural model.
The gate run sets the env var; everything else stays byte-identical to the
string fallback. This is the honest "don't silently make it in-loop" lever.

Execution provider (card PG-1, item 3)
--------------------------------------
The execution provider is resolved by :mod:`parcel_robot.perception.providers`
with the same documented fallback order as the detector — ``cuda_fp16 ->
cpu_int8`` — and logged once at construction. A machine with no
``CUDAExecutionProvider`` resolves to ``cpu_int8``: the same artifacts, the same
execution provider, and the same numbers as before this card. The 2026-08-21
bench measured the image encoder at **49.3 ms CPU int8 vs 4.07 ms GPU fp16**.

Text and vision resolve **independently**, because they are separate ONNX files
and a weights directory can legitimately hold one precision of each. Whichever
each resolves to is recorded on :attr:`_OnnxSigLIP2Embedder.resolution` /
``vision_resolution``.

Preprocessing shares the detector's bit-identical separable resize. SigLIP-2 does
NOT pad to a square (it resizes straight to 224x224), so the detector's
content/pad seam analysis does not apply here and is deliberately not copied.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from parcel_robot.perception.providers import (
    PROVIDER_CPU_INT8,
    ProviderResolution,
    assert_provider_honoured,
    log_resolution,
    prepare_cuda_runtime,
    resolve_provider,
)

logger = logging.getLogger(__name__)

#: SigLIP text encoder was trained with fixed-length 64-token sequences and has
#: NO attention-mask input (pad tokens are attended, and pooling reads the final
#: position). So text MUST be right-padded to exactly this length or the pooled
#: vector drifts off the trained distribution.
SIGLIP2_TEXT_SEQ_LEN = 64

#: Env switch. Truthy => attempt the real ONNX load; anything else => stay on the
#: string fallback even when the weights are present (keeps CI/mission byte-identical).
ONNX_ENABLE_ENV = "PARCEL_SIGLIP2_ONNX"

#: Filenames the fetch script writes (int8 variant). Text is the hot-path encoder;
#: vision is the deferred crop-embedding (B2) consumer and is loaded lazily.
_TEXT_ONNX_CANDIDATES = ("text_model_int8.onnx", "text_model_quantized.onnx", "text_model.onnx")
_VISION_ONNX_CANDIDATES = ("vision_model_int8.onnx", "vision_model_quantized.onnx", "vision_model.onnx")

#: fp16 artifacts for the CUDA path — same onnx-community export repo, same
#: upstream checkpoint, different precision.
_TEXT_ONNX_FP16_CANDIDATES = ("text_model_fp16.onnx",)
_VISION_ONNX_FP16_CANDIDATES = ("vision_model_fp16.onnx",)

#: onnxruntime input type string -> numpy dtype name, for the feed-boundary cast.
_ORT_TO_NUMPY: dict[str, str] = {"tensor(float)": "float32", "tensor(float16)": "float16"}


def onnx_enabled() -> bool:
    """True when the opt-in env switch selects the real ONNX path."""

    return os.environ.get(ONNX_ENABLE_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def _first_present(weights_dir: Path, names: tuple[str, ...]) -> Path | None:
    for name in names:
        candidate = weights_dir / name
        if candidate.is_file():
            return candidate
    return None


def resolve_text_provider(weights_dir: Path, **kwargs: Any) -> ProviderResolution:
    """Which (execution provider, artifact) pair the TEXT encoder would run on."""

    return resolve_provider(
        weights_dir,
        int8_candidates=_TEXT_ONNX_CANDIDATES,
        fp16_candidates=_TEXT_ONNX_FP16_CANDIDATES,
        **kwargs,
    )


def resolve_vision_provider(weights_dir: Path, **kwargs: Any) -> ProviderResolution:
    """Which (execution provider, artifact) pair the VISION encoder would run on."""

    return resolve_provider(
        weights_dir,
        int8_candidates=_VISION_ONNX_CANDIDATES,
        fp16_candidates=_VISION_ONNX_FP16_CANDIDATES,
        **kwargs,
    )


def load_onnx_embedder(weights_dir: Path) -> Any | None:
    """Load the ONNX SigLIP-2 embedder, or ``None`` if disabled / unavailable.

    Returns ``None`` (never raises) when the env switch is off, a required file
    is missing, no execution provider in the documented fallback order is
    available, an explicitly pinned provider is unavailable, or ``onnxruntime`` /
    ``tokenizers`` are absent — the matcher then degrades loudly to the string
    fallback exactly as before.
    """

    if not onnx_enabled():
        return None
    resolution = resolve_text_provider(weights_dir)
    tokenizer_json = weights_dir / "tokenizer.json"
    if resolution.selected is None or not tokenizer_json.is_file():
        log_resolution(resolution, model="siglip2-text")
        logger.warning(
            "SigLIP-2 ONNX enabled but unavailable under %s (provider=%s tokenizer=%s)",
            weights_dir, resolution.selected, tokenizer_json.is_file(),
        )
        return None
    try:
        return _OnnxSigLIP2Embedder(weights_dir, resolution.model_file, resolution=resolution)
    except Exception as exc:  # noqa: BLE001 — any load failure => degrade, never crash grounding
        logger.warning("SigLIP-2 ONNX load failed (%s: %s) — string fallback", type(exc).__name__, exc)
        return None


class _OnnxSigLIP2Embedder:
    """onnxruntime-backed SigLIP-2 text+image encoder (L2-normalized output)."""

    #: Class-level defaults, mirroring the detector: they document the defaults in
    #: one place and keep ``object.__new__`` shells (used by preprocessing tests)
    #: working without a session.
    provider: str = PROVIDER_CPU_INT8
    resolution: ProviderResolution | None = None
    vision_resolution: ProviderResolution | None = None

    def __init__(
        self,
        weights_dir: Path,
        text_onnx: Path,
        *,
        resolution: ProviderResolution | None = None,
    ) -> None:
        import numpy as np
        import onnxruntime as ort
        from tokenizers import Tokenizer

        self._np = np
        self._weights_dir = weights_dir
        if resolution is None:
            resolution = resolve_text_provider(weights_dir)
        self.resolution = resolution
        self.provider = resolution.selected or PROVIDER_CPU_INT8

        # Tokenizer: the SigLIP GemmaTokenizer straight from tokenizer.json (the
        # rust fast tokenizer). Its baked normalizer does NOT lowercase, but the
        # processor is do_lower_case=True, so we lowercase before encoding and
        # enforce SigLIP's fixed 64-length right padding + truncation ourselves.
        self._tok = Tokenizer.from_file(str(weights_dir / "tokenizer.json"))
        pad_id = self._tok.token_to_id("<pad>")
        if pad_id is None:
            pad_id = 0
        self._pad_id = int(pad_id)
        try:
            self._tok.enable_truncation(max_length=SIGLIP2_TEXT_SEQ_LEN)
            self._tok.enable_padding(
                length=SIGLIP2_TEXT_SEQ_LEN, pad_id=self._pad_id, pad_token="<pad>", direction="right"
            )
        except Exception as exc:  # noqa: BLE001 — _encode_ids pads/truncates manually anyway
            logger.debug("tokenizer pad/trunc config skipped (%s); using manual", exc)

        opts = ort.SessionOptions()
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        opts.intra_op_num_threads = int(os.environ.get("PARCEL_SIGLIP2_THREADS", "0") or 0)
        self._ort = ort
        self._session_options = opts
        providers = list(resolution.execution_providers) or ["CPUExecutionProvider"]
        prepare_cuda_runtime(resolution)  # must precede the session, see its docstring
        self._text_session = ort.InferenceSession(
            str(text_onnx), sess_options=opts, providers=providers
        )
        honoured = tuple(self._text_session.get_providers())
        log_resolution(resolution, model="siglip2-text")
        logger.info("[siglip2-text] onnxruntime honoured providers=%s", honoured)
        self.honoured_providers = honoured
        # Fail closed: a CUDA session ORT silently ran on the CPU is worse than
        # no session at all, because the caller sizes its budget on the label.
        assert_provider_honoured(resolution, honoured, model="siglip2-text")
        self._text_input = self._text_session.get_inputs()[0].name

        out_dim = self._text_session.get_outputs()[-1].shape[-1]
        self.dim = int(out_dim) if isinstance(out_dim, int) else 768

        # Image preprocessing params from preprocessor_config.json (fall back to
        # the published SigLIP defaults if the file is unexpectedly shaped).
        cfg = {}
        pcfg = weights_dir / "preprocessor_config.json"
        if pcfg.is_file():
            try:
                cfg = json.loads(pcfg.read_text())
            except Exception:  # noqa: BLE001
                cfg = {}
        size = cfg.get("size") or {}
        self._img_h = int(size.get("height", 224))
        self._img_w = int(size.get("width", 224))
        self._img_mean = np.asarray(cfg.get("image_mean", [0.5, 0.5, 0.5]), dtype=np.float32)
        self._img_std = np.asarray(cfg.get("image_std", [0.5, 0.5, 0.5]), dtype=np.float32)
        self._rescale = float(cfg.get("rescale_factor", 1.0 / 255.0))

        self._vision_session = None  # lazy — vision is the deferred B2 consumer
        # Deterministic embeddings => memoize. The label vocabulary is tiny and
        # queries repeat, so this drops a 6-encode match() from ~175 ms to one
        # ~29 ms query encode (labels served from cache). Bounded to stay small.
        self._text_cache: dict[str, tuple[float, ...]] = {}
        self._text_cache_cap = 4096

    # ---- text --------------------------------------------------------------
    def _encode_ids(self, text: str) -> Any:
        np = self._np
        enc = self._tok.encode(text.lower())
        ids = list(enc.ids)
        if len(ids) < SIGLIP2_TEXT_SEQ_LEN:
            ids = ids + [self._pad_id] * (SIGLIP2_TEXT_SEQ_LEN - len(ids))
        elif len(ids) > SIGLIP2_TEXT_SEQ_LEN:
            ids = ids[:SIGLIP2_TEXT_SEQ_LEN]
        return np.asarray([ids], dtype=np.int64)

    def embed_text(self, text: str) -> tuple[float, ...]:
        key = str(text).lower()
        cached = self._text_cache.get(key)
        if cached is not None:
            return cached
        ids = self._encode_ids(str(text))
        out = self._text_session.run(None, {self._text_input: ids})
        vec = self._np.asarray(out[-1])[0].astype(self._np.float32)  # pooler_output
        result = self._l2(vec)
        if len(self._text_cache) < self._text_cache_cap:
            self._text_cache[key] = result
        return result

    # ---- image -------------------------------------------------------------
    def _ensure_vision(self) -> None:
        if self._vision_session is not None:
            return
        # Vision resolves INDEPENDENTLY of text: they are separate ONNX files and
        # a weights dir may legitimately hold one precision of each.
        resolution = resolve_vision_provider(self._weights_dir)
        if resolution.selected is None:
            log_resolution(resolution, model="siglip2-vision")
            raise FileNotFoundError(
                f"no usable vision_model onnx under {self._weights_dir}: {resolution.reason}"
            )
        self.vision_resolution = resolution
        prepare_cuda_runtime(resolution)
        self._vision_session = self._ort.InferenceSession(
            str(resolution.model_file),
            sess_options=self._session_options,
            providers=list(resolution.execution_providers) or ["CPUExecutionProvider"],
        )
        honoured = tuple(self._vision_session.get_providers())
        log_resolution(resolution, model="siglip2-vision")
        logger.info("[siglip2-vision] onnxruntime honoured providers=%s", honoured)
        assert_provider_honoured(resolution, honoured, model="siglip2-vision")
        vision_input = self._vision_session.get_inputs()[0]
        self._vision_input = vision_input.name
        self._pixel_dtype = self._np.dtype(_ORT_TO_NUMPY.get(vision_input.type, "float32"))

    def embed_image(self, image: Any) -> tuple[float, ...]:
        self._ensure_vision()
        pixels = self._preprocess_image(image)  # (1, 3, H, W) float32
        want = getattr(self, "_pixel_dtype", None)
        if want is not None and pixels.dtype != want:
            pixels = pixels.astype(want)
        out = self._vision_session.run(None, {self._vision_input: pixels})
        vec = self._np.asarray(out[-1])[0].astype(self._np.float32)  # pooler_output
        return self._l2(vec)

    def _preprocess_image(self, image: Any) -> Any:
        """numpy-only SigLIP preprocess: HxWx3 [0..255] -> (1,3,224,224) normalized.

        Accepts a numpy array (H,W,3) or (H,W) or anything ``np.asarray`` turns
        into one (a PIL image works too, but PIL is NOT required). Bilinear
        resize matches the SiglipImageProcessor's ``resample=2``.
        """

        np = self._np
        arr = np.asarray(image)
        if arr.ndim == 2:
            arr = np.stack([arr] * 3, axis=-1)
        if arr.ndim != 3:
            raise ValueError(f"expected HxWx3 image, got shape {arr.shape}")
        if arr.shape[2] == 4:
            arr = arr[:, :, :3]
        arr = arr.astype(np.float32)
        resized = self._bilinear_resize(arr, self._img_h, self._img_w)
        resized = resized * self._rescale
        resized = (resized - self._img_mean) / self._img_std
        chw = np.transpose(resized, (2, 0, 1))  # HWC -> CHW
        return chw[None, ...].astype(np.float32)

    def _axis_samples(self, in_n: int, out_n: int) -> tuple[Any, Any, Any]:
        np = self._np
        zs = (np.arange(out_n, dtype=np.float32) + 0.5) * (in_n / out_n) - 0.5
        zs = np.clip(zs, 0, in_n - 1)
        z0 = np.floor(zs).astype(np.int64)
        z1 = np.minimum(z0 + 1, in_n - 1)
        return zs, z0, z1

    def _bilinear_resize_reference(self, arr: Any, out_h: int, out_w: int) -> Any:
        """The original resize, kept verbatim as the numeric DEFINITION.

        :meth:`_bilinear_resize` is pinned bit-identical against this in
        ``tests/test_siglip_real_embeddings.py``; keeping the reference in the
        tree means the equivalence test cannot drift along with the optimisation
        it is checking.
        """

        in_h, in_w = arr.shape[0], arr.shape[1]
        if in_h == out_h and in_w == out_w:
            return arr
        # half-pixel-centered sampling (align_corners=False), matching PIL/HF bilinear
        ys, y0, y1 = self._axis_samples(in_h, out_h)
        xs, x0, x1 = self._axis_samples(in_w, out_w)
        wy = (ys - y0)[:, None, None]; wx = (xs - x0)[None, :, None]
        top = arr[y0][:, x0] * (1 - wx) + arr[y0][:, x1] * wx
        bot = arr[y1][:, x0] * (1 - wx) + arr[y1][:, x1] * wx
        return top * (1 - wy) + bot * wy

    def _bilinear_resize(self, arr: Any, out_h: int, out_w: int) -> Any:
        """Bit-identical to :meth:`_bilinear_resize_reference`, with half the gathers.

        The reference expression writes ``arr[y0]`` and ``arr[y1]`` twice each, so
        numpy materialises four ``out_h x in_w x 3`` row-gathers. Blending
        horizontally first over all ``in_h`` rows computes the *same* per-element
        expression with two narrow gathers instead:
        ``H[y] = arr[y][x0]*(1-wx) + arr[y][x1]*wx``, then ``top, bot = H[y0], H[y1]``.
        """

        in_h, in_w = arr.shape[0], arr.shape[1]
        if in_h == out_h and in_w == out_w:
            return arr
        ys, y0, y1 = self._axis_samples(in_h, out_h)
        xs, x0, x1 = self._axis_samples(in_w, out_w)
        wy = (ys - y0)[:, None, None]; wx = (xs - x0)[None, :, None]
        horiz = arr[:, x0] * (1 - wx) + arr[:, x1] * wx  # (in_h, out_w, 3)
        return horiz[y0] * (1 - wy) + horiz[y1] * wy

    def _l2(self, vec: Any) -> tuple[float, ...]:
        np = self._np
        norm = float(np.linalg.norm(vec))
        if norm < 1e-12:
            norm = 1.0
        return tuple(float(v) for v in (vec / norm))
