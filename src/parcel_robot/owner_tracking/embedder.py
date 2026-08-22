"""Where this package gets its ``embed_fn`` — P1-B's seam first, SigLIP-2 second.

Card P1-C, work item 1: *"re-use P1-B's ``embed_fn`` seam — consume, don't
re-implement"*. The seam is the ``embed_fn`` attribute on
:class:`~parcel_robot.camera_channel.ingress.CameraIngress`: one positional
image, one L2-normalized float sequence out — the exact shape
``siglip2_onnx._OnnxSigLIP2Embedder.embed_image`` and
``route_memory.place_graph.stub_embed_image`` already have.

So the resolution order is:

1. **An ingress instance that already carries one.** If the runtime built the
   camera channel with an encoder, this package uses *that object*, so there is
   one session on the GPU and not two.
2. **The SigLIP-2 ONNX loader directly** (``instructnav.siglip2_onnx``). This is
   the path when the tracker runs outside the camera channel — enrollment, the
   recorded-clip tests, a bag replay.
3. **Nothing.** ``None``, loudly, and the tracker degrades to "no identity
   asserted" rather than to a fabricated one.

WHAT THIS COSTS TODAY, STATED
-----------------------------
``load_onnx_embedder`` builds the TEXT session eagerly (it is the grounding
hot path) and the vision session lazily. This package only ever wants vision, so
path 2 pays for a text session it will not use — 565 MB of fp16 weights and a
few hundred ms. That is a real cost and it is why path 1 exists: inside the
runtime the encoder is already loaded and shared. Recorded as a handoff in
``scrum/20260822/task_8/P1C_STATUS.md`` rather than fixed here, because the
narrower loader lives in ``instructnav/`` which this card does not own.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: The env switch ``siglip2_onnx`` already reads. Named here so the enrollment
#: tool can tell the owner exactly which variable to set.
SIGLIP2_ENABLE_ENV = "PARCEL_SIGLIP2_ONNX"

#: The provider knob every perception model shares (``perception_providers``).
PROVIDER_ENV = "PARCEL_PERCEPTION_PROVIDER"


@dataclass(frozen=True, slots=True)
class EmbedderResolution:
    """Which encoder answered, and — when none did — why not."""

    embed_fn: Callable[[Any], Sequence[float]] | None
    source: str
    model: str = ""
    provider: str = ""
    dim: int = 0
    reason: str = ""

    @property
    def available(self) -> bool:
        return self.embed_fn is not None


def default_weights_dir() -> Path:
    """``~/.cache/parcel/siglip2-b16`` unless ``PARCEL_SIGLIP2_DIR`` overrides it.

    Mirrors ``scripts/fetch_siglip2.sh``'s ``DEST_DIR`` exactly, so the fetch
    script and the loader cannot disagree about where the weights are.
    """

    override = os.environ.get("PARCEL_SIGLIP2_DIR", "").strip()
    if override:
        return Path(override).expanduser()
    return Path.home() / ".cache" / "parcel" / "siglip2-b16"


def from_ingress(ingress: Any) -> EmbedderResolution:
    """Path 1 — reuse the encoder the camera channel already loaded.

    Structural, not an ``isinstance``: P1-B owns ``ingress.py`` and is editing
    it right now, so this must not pin its type. It asks the only question that
    matters — is there a callable ``embed_fn`` on that object.
    """

    embed_fn = getattr(ingress, "embed_fn", None)
    if embed_fn is None:
        return EmbedderResolution(
            embed_fn=None, source="ingress", reason="ingress carries no embed_fn"
        )
    if not callable(embed_fn):
        return EmbedderResolution(
            embed_fn=None, source="ingress", reason="ingress embed_fn is not callable"
        )
    return EmbedderResolution(
        embed_fn=embed_fn,
        source="ingress",
        model=str(getattr(ingress, "embed_model", "") or "ingress.embed_fn"),
    )


def from_siglip2(weights_dir: Path | None = None) -> EmbedderResolution:
    """Path 2 — load SigLIP-2 ONNX directly and hand back ``embed_image``.

    Returns an unavailable resolution (never raises) when the env switch is off,
    the weights are absent, or onnxruntime/tokenizers are missing —
    ``load_onnx_embedder`` already has exactly that contract, and this function
    does not add a second one.
    """

    directory = weights_dir if weights_dir is not None else default_weights_dir()
    try:
        from parcel_robot.instructnav.siglip2_onnx import load_onnx_embedder, onnx_enabled
    except ImportError as error:  # pragma: no cover - the package is in-tree
        return EmbedderResolution(
            embed_fn=None, source="siglip2", reason=f"import failed: {error}"
        )
    if not onnx_enabled():
        return EmbedderResolution(
            embed_fn=None,
            source="siglip2",
            reason=f"{SIGLIP2_ENABLE_ENV} is not set — the real encoder is opt-in",
        )
    embedder = load_onnx_embedder(directory)
    if embedder is None:
        return EmbedderResolution(
            embed_fn=None,
            source="siglip2",
            reason=f"no usable SigLIP-2 encoder under {directory}",
        )
    # Name the VISION artefact, not the text one. ``load_onnx_embedder``
    # resolves text eagerly (it is the grounding hot path) and leaves
    # ``vision_resolution`` unset until the first ``embed_image``, so reading
    # ``embedder.resolution`` here would put "text_model_fp16.onnx" in the
    # gallery header — a model name that is not the model that produced the
    # vectors, which is the exact failure the header exists to prevent.
    # ``resolve_vision_provider`` is a pure resolution: no session is created.
    try:
        from parcel_robot.instructnav.siglip2_onnx import resolve_vision_provider

        resolution = resolve_vision_provider(directory)
    except Exception:  # noqa: BLE001 — fall back to whatever the object knows
        resolution = getattr(embedder, "vision_resolution", None) or getattr(
            embedder, "resolution", None
        )
    provider = str(getattr(resolution, "selected", "") or "")
    model_file = getattr(resolution, "model_file", None)
    model = f"siglip2-b16/{Path(model_file).name}" if model_file else "siglip2-b16"
    return EmbedderResolution(
        embed_fn=embedder.embed_image,
        source="siglip2",
        model=model,
        provider=provider,
        dim=int(getattr(embedder, "dim", 0) or 0),
    )


def resolve_embed_fn(
    *,
    ingress: Any | None = None,
    embed_fn: Callable[[Any], Sequence[float]] | None = None,
    weights_dir: Path | None = None,
) -> EmbedderResolution:
    """The documented order: explicit callable, then ingress, then SigLIP-2."""

    if embed_fn is not None:
        if not callable(embed_fn):
            raise TypeError("embed_fn must be callable")
        return EmbedderResolution(embed_fn=embed_fn, source="explicit", model="caller-supplied")
    if ingress is not None:
        resolved = from_ingress(ingress)
        if resolved.available:
            return resolved
        logger.info("owner_tracking: ingress embed_fn unusable (%s) — trying SigLIP-2", resolved.reason)
    return from_siglip2(weights_dir)


def vision_model_sha256(weights_dir: Path | None = None, *, limit_bytes: int = 1 << 20) -> str:
    """Hash of the FIRST ``limit_bytes`` of the vision artefact, or ``""``.

    A prefix hash and not the whole 186 MB file, and the docstring says so: it
    is an artefact *identity* for the gallery header, not an integrity proof.
    Hashing the whole file on every enrollment is a second of I/O for a claim
    nobody is making.
    """

    import hashlib

    directory = weights_dir if weights_dir is not None else default_weights_dir()
    for name in ("vision_model_fp16.onnx", "vision_model_int8.onnx", "vision_model.onnx"):
        candidate = directory / name
        if candidate.is_file():
            digest = hashlib.sha256()
            with candidate.open("rb") as stream:
                digest.update(stream.read(limit_bytes))
            return f"{name}:prefix{limit_bytes}:{digest.hexdigest()}"
    return ""


__all__ = [
    "PROVIDER_ENV",
    "SIGLIP2_ENABLE_ENV",
    "EmbedderResolution",
    "default_weights_dir",
    "from_ingress",
    "from_siglip2",
    "resolve_embed_fn",
    "vision_model_sha256",
]
