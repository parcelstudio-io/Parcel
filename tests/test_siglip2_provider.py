"""PG-1 item 3 — SigLIP-2 execution-provider plumbing + bit-identical resize.

Kept in its own file so ``tests/test_siglip_real_embeddings.py`` — which owns
three of the nine deliberately-skipped gate cells — is not touched at all by this
card. Nothing here changes a skip condition.

Measured basis (``scrum/20260821/perception/bench_detectors.md``): the SigLIP-2
image encoder is **49.3 ms under onnxruntime-CPU int8 and 4.07 ms on GPU fp16**,
a 12x gap on a model the grounding path calls once per crop.
"""

from __future__ import annotations

import numpy as np
import pytest

from parcel_robot.instructnav.siglip2_onnx import (
    _OnnxSigLIP2Embedder,
    load_onnx_embedder,
    resolve_text_provider,
    resolve_vision_provider,
)
from parcel_robot.perception_providers import PROVIDER_CPU_INT8, PROVIDER_CUDA_FP16

CUDA_BOX = ("CUDAExecutionProvider", "CPUExecutionProvider")
CPU_BOX = ("CPUExecutionProvider",)


def _shell() -> _OnnxSigLIP2Embedder:
    """Preprocessing-only shell — no session, no weights, no onnxruntime."""

    emb = object.__new__(_OnnxSigLIP2Embedder)
    emb._np = np
    emb._img_h = 224
    emb._img_w = 224
    emb._img_mean = np.asarray([0.5, 0.5, 0.5], dtype=np.float32)
    emb._img_std = np.asarray([0.5, 0.5, 0.5], dtype=np.float32)
    emb._rescale = 1.0 / 255.0
    return emb


# ---------------------------------------------------------------------------
# bit-identical resize
# ---------------------------------------------------------------------------

#: Crop shapes the grounding path actually produces (``_crop_embedding`` slices a
#: detector box out of the frame), plus degenerate ones.
_CROP_SHAPES = [
    (720, 1280, 3),
    (224, 224, 3),
    (300, 120, 3),
    (37, 53, 3),
    (13, 400, 3),
    (400, 13, 3),
    (1, 1, 3),
    (1, 500, 3),
]


@pytest.mark.parametrize("shape", _CROP_SHAPES)
def test_the_separable_resize_is_bit_identical_to_the_reference(shape) -> None:
    """``np.array_equal``, not a tolerance: the encoder must see the SAME tensor."""

    emb = _shell()
    arr = np.random.default_rng(abs(hash(shape)) % 997).random(shape, dtype=np.float32)
    reference = emb._bilinear_resize_reference(arr, 224, 224)
    fast = emb._bilinear_resize(arr, 224, 224)
    assert np.array_equal(fast, reference), (
        f"{shape}: max|delta|="
        f"{np.abs(np.asarray(fast, np.float64) - np.asarray(reference, np.float64)).max()}"
    )


@pytest.mark.parametrize("shape", _CROP_SHAPES)
def test_the_whole_preprocess_is_bit_identical_end_to_end(shape) -> None:
    emb = _shell()
    img = np.random.default_rng(3).integers(0, 256, shape, dtype=np.uint8)
    out = emb._preprocess_image(img)
    assert out.shape == (1, 3, 224, 224)
    assert out.dtype == np.float32

    reference_emb = _shell()
    reference_emb._bilinear_resize = reference_emb._bilinear_resize_reference  # type: ignore[method-assign]
    assert np.array_equal(out, reference_emb._preprocess_image(img))


def test_a_greyscale_crop_still_preprocesses() -> None:
    emb = _shell()
    img = np.random.default_rng(4).integers(0, 256, (50, 70), dtype=np.uint8)
    assert emb._preprocess_image(img).shape == (1, 3, 224, 224)


# ---------------------------------------------------------------------------
# provider resolution — text and vision resolve INDEPENDENTLY
# ---------------------------------------------------------------------------


def test_text_and_vision_resolve_independently(tmp_path) -> None:
    """A weights dir may legitimately hold one precision of each encoder."""

    (tmp_path / "text_model_int8.onnx").write_bytes(b"x")
    (tmp_path / "vision_model_fp16.onnx").write_bytes(b"x")

    text = resolve_text_provider(tmp_path, available_execution_providers=CUDA_BOX)
    vision = resolve_vision_provider(tmp_path, available_execution_providers=CUDA_BOX)

    assert text.selected == PROVIDER_CPU_INT8  # no fp16 text file -> falls back
    assert text.degraded is True
    assert vision.selected == PROVIDER_CUDA_FP16
    assert vision.model_file.name == "vision_model_fp16.onnx"


def test_a_cuda_less_machine_stays_on_int8_for_both(tmp_path) -> None:
    for name in ("text_model_int8.onnx", "text_model_fp16.onnx",
                 "vision_model_int8.onnx", "vision_model_fp16.onnx"):
        (tmp_path / name).write_bytes(b"x")

    text = resolve_text_provider(tmp_path, available_execution_providers=CPU_BOX)
    vision = resolve_vision_provider(tmp_path, available_execution_providers=CPU_BOX)
    assert text.selected == vision.selected == PROVIDER_CPU_INT8
    assert text.model_file.name == "text_model_int8.onnx"
    assert vision.model_file.name == "vision_model_int8.onnx"
    assert text.execution_providers == ("CPUExecutionProvider",)


def test_the_gpu_box_prefers_fp16_for_both_when_present(tmp_path) -> None:
    for name in ("text_model_int8.onnx", "text_model_fp16.onnx",
                 "vision_model_int8.onnx", "vision_model_fp16.onnx"):
        (tmp_path / name).write_bytes(b"x")
    text = resolve_text_provider(tmp_path, available_execution_providers=CUDA_BOX)
    vision = resolve_vision_provider(tmp_path, available_execution_providers=CUDA_BOX)
    assert text.selected == vision.selected == PROVIDER_CUDA_FP16
    assert text.rejected == () and vision.rejected == ()


def test_the_loader_stays_opt_in_and_returns_none_when_unavailable(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("PARCEL_SIGLIP2_ONNX", raising=False)
    assert load_onnx_embedder(tmp_path) is None  # opt-in switch off

    monkeypatch.setenv("PARCEL_SIGLIP2_ONNX", "1")
    assert load_onnx_embedder(tmp_path) is None  # no weights -> loud degrade, no raise

    (tmp_path / "tokenizer.json").write_text("{}")
    (tmp_path / "text_model_int8.onnx").write_bytes(b"not-an-onnx")
    monkeypatch.setenv("PARCEL_PERCEPTION_PROVIDER", "cuda_fp16")
    assert load_onnx_embedder(tmp_path) is None  # pinned provider unavailable -> refuse


def test_class_defaults_are_the_incumbent_path() -> None:
    assert _OnnxSigLIP2Embedder.provider == PROVIDER_CPU_INT8
    assert _OnnxSigLIP2Embedder.resolution is None
    assert _OnnxSigLIP2Embedder.vision_resolution is None
