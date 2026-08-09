"""SigLIP-2 text+image embedding matcher for Grounder v2.

Real neural path: ``siglip2-base-patch16-224`` (Apache-2.0, ~86M, 768-dim), run
via **onnxruntime** — NO torch, NO transformers. ``scripts/fetch_siglip2.sh``
lands the int8 ONNX encoders + tokenizer under ``~/.cache/parcel/siglip2-b16``
(the advertised cache); :mod:`parcel_robot.instructnav.siglip2_onnx` loads them
the same no-torch way the audio stack runs Silero / smart-turn. When present and
enabled, :meth:`SigLIP2Matcher.embed_text` / :meth:`embed_image` return
L2-normalized vectors and :meth:`match` decides identity by cosine — so
``"streetlight"`` grounds to ``"lamppost"`` by MEANING, without an alias row.

The real path is **opt-in** behind ``PARCEL_SIGLIP2_ONNX`` (see
:mod:`.siglip2_onnx`): merely landing the weights never flips the whole suite /
mission path onto a neural model. When the switch is off, weights are absent, or
the load fails, the matcher degrades **loudly** to the exact/alias string match,
byte-for-byte identical to the pre-neural stub, so offline CI is unchanged.
``available`` is ``True`` only when a real embedder actually loaded (or one was
injected) — never merely because a file exists — which is what lets the wiring in
:mod:`grounding` / :mod:`semantic_map` gate the FP-suppressing real path behind a
*usable* model rather than a present-but-unloadable one.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from parcel_robot.instructnav.siglip2_onnx import load_onnx_embedder, onnx_enabled

logger = logging.getLogger(__name__)

DEFAULT_WEIGHTS = Path.home() / ".cache" / "parcel" / "siglip2-b16"

#: Canonical model + embedding contract (VSEARCH A1). The base/patch16 family is
#: published per input resolution; the 224 variant is the light default. A weights
#: dir that carries its own ``config.json`` overrides this id.
SIGLIP2_MODEL_ID = "google/siglip2-base-patch16-224"
SIGLIP2_EMBED_DIM = 768

#: The 0.24 gate below was tuned for the char-hash stub, whose cosines cluster
#: near zero. Real SigLIP-2 is an image-TEXT model, so its text↔text cosines
#: cluster HIGH and overlapping (present [0.84, 0.99] vs cross-class [0.76, 0.93]
#: on the scene vocabulary), NOT near zero — the old 0.30 provisional would have
#: accepted everything. :data:`SIGLIP2_MATCH_THRESHOLD` is the **real-weight**
#: operating point recalibrated by :func:`calibrate_threshold` against the scene
#: vocabulary's cross-class trials (see ``SIGLIP_REAL_STATUS.md`` for the FAR/TAR
#: curve). 0.90 sits above the two cross-class false_arrival pairs
#: (streetlight/tree 0.869, tree/lamppost 0.872 → both refused) and below the
#: real synonym streetlight/lamppost 0.962 → kept. Override with the env var for
#: a sweep; curated synonyms are still caught upstream by the alias table.
LEGACY_HASH_THRESHOLD = 0.24
SIGLIP2_MATCH_THRESHOLD = float(os.environ.get("PARCEL_SIGLIP2_THRESHOLD", "0.90"))


@dataclass(frozen=True)
class EmbeddingMatch:
    label: str
    score: float
    source: str  # "siglip2" | "string_fallback"


@runtime_checkable
class TextImageEmbedder(Protocol):
    """The neural seam A1 exposes; real (transformers) or synthetic (tests)."""

    dim: int

    def embed_text(self, text: str) -> tuple[float, ...]: ...

    def embed_image(self, image: Any) -> tuple[float, ...]: ...


class SigLIP2Matcher:
    """Text/image cosine matcher with a loud degrade when weights are missing."""

    def __init__(
        self,
        weights_dir: str | Path | None = None,
        *,
        embedder: TextImageEmbedder | None = None,
        real_threshold: float = SIGLIP2_MATCH_THRESHOLD,
    ) -> None:
        self.weights_dir = Path(weights_dir) if weights_dir else DEFAULT_WEIGHTS
        self.real_threshold = float(real_threshold)
        if embedder is not None:
            # Injected (synthetic fixture / hardware swap). Trust it as available.
            self._embedder: TextImageEmbedder | None = embedder
            self._available = True
            return
        self._embedder = None
        # Only attempt a load when the real path is enabled AND weights are
        # present, so the common (opt-out / weights-absent) construction stays
        # fast and byte-identical to the pre-neural stub.
        if onnx_enabled() and self._probe():
            self._embedder = _load_neural_embedder(self.weights_dir)
        self._available = self._embedder is not None
        if onnx_enabled() and not self._available:
            # Only loud when the operator explicitly asked for the real path but
            # it could not load. The default opt-out is silent (expected).
            logger.warning(
                "SigLIP-2 ONNX requested but not usable at %s — degrading to "
                "string match (real neural path OFF; U25)",
                self.weights_dir,
            )

    @property
    def available(self) -> bool:
        return self._available

    def _probe(self) -> bool:
        # Presence check only — real usability is decided by the load attempt.
        markers = (
            "open_clip_model.safetensors",  # open_clip layout (stub's advertised path)
            "model.safetensors",  # transformers layout
            "config.json",
        )
        return any((self.weights_dir / marker).is_file() for marker in markers)

    def embed_text(self, text: str) -> tuple[float, ...] | None:
        """L2-normalized text embedding, or ``None`` when the real path is off."""

        if self._embedder is None:
            return None
        return self._embedder.embed_text(str(text))

    def embed_image(self, image: Any) -> tuple[float, ...] | None:
        """L2-normalized image embedding, or ``None`` when the real path is off."""

        if self._embedder is None:
            return None
        return self._embedder.embed_image(image)

    def match(
        self,
        query: str,
        labels: Sequence[str],
        *,
        threshold: float | None = None,
    ) -> EmbeddingMatch | None:
        if not labels:
            return None
        if self._embedder is not None:
            # Real neural cosine. Gates on the recalibrated real_threshold unless
            # an explicit threshold is passed (calibration sweeps do that).
            gate = self.real_threshold if threshold is None else float(threshold)
            q = self._embedder.embed_text(str(query))
            best: tuple[float, str] | None = None
            for label in labels:
                score = _cosine(q, self._embedder.embed_text(str(label)))
                if best is None or score > best[0]:
                    best = (score, str(label))
            assert best is not None
            if best[0] >= gate:
                return EmbeddingMatch(label=best[1], score=float(best[0]), source="siglip2")
            return None
        # Loud string fallback — byte-identical to the pre-neural stub. The
        # `threshold` argument is inert here (a substring hit scores 1.0); it is
        # retained only so the signature is stable across the degrade.
        norm_q = _norm(query)
        for label in labels:
            if norm_q and (_norm(label) in norm_q or norm_q in _norm(label)):
                return EmbeddingMatch(label=label, score=1.0, source="string_fallback")
        return None


def _load_neural_embedder(weights_dir: Path) -> TextImageEmbedder | None:
    """Load the real SigLIP-2 embedder (ONNX), or ``None`` if unavailable.

    Delegates to :func:`parcel_robot.instructnav.siglip2_onnx.load_onnx_embedder`,
    which runs the int8 encoders under ``onnxruntime`` (no torch / transformers)
    and returns ``None`` — never raises — when the env switch is off, a required
    file is missing, or ``onnxruntime`` / ``tokenizers`` are absent. The loud
    warning is the caller's job.
    """

    return load_onnx_embedder(weights_dir)


def calibrate_threshold(
    embedder: TextImageEmbedder,
    present_pairs: Sequence[tuple[str, str]],
    absent_pairs: Sequence[tuple[str, str]],
    *,
    steps: int = 101,
) -> dict[str, Any]:
    """Sweep the cosine gate over labelled trials; pick the Youden-J operating point.

    ``present_pairs`` are ``(query, correct_label)`` synonym trials that SHOULD
    match; ``absent_pairs`` are ``(query, wrong_label)`` cross-class trials that
    must NOT. Returns the chosen threshold plus the full FAR/TAR curve so the
    caller can record it. This is the harness the real-weight recalibration runs;
    here it is exercised on the synthetic fixture to prove the machinery.
    """

    def cos(a: str, b: str) -> float:
        return _cosine(embedder.embed_text(a), embedder.embed_text(b))

    present = [cos(q, lbl) for q, lbl in present_pairs]
    absent = [cos(q, lbl) for q, lbl in absent_pairs]
    curve: list[dict[str, float]] = []
    best: tuple[float, float] | None = None  # (youden_j, threshold)
    for i in range(steps):
        thr = i / (steps - 1)
        tar = sum(1 for c in present if c >= thr) / max(1, len(present))
        far = sum(1 for c in absent if c >= thr) / max(1, len(absent))
        curve.append({"threshold": thr, "tar": tar, "far": far})
        j = tar - far
        if best is None or j > best[0]:
            best = (j, thr)
    assert best is not None
    return {
        "threshold": best[1],
        "youden_j": best[0],
        "present_cos_min": min(present) if present else None,
        "present_cos_max": max(present) if present else None,
        "absent_cos_min": min(absent) if absent else None,
        "absent_cos_max": max(absent) if absent else None,
        "curve": curve,
    }


def _norm(value: str) -> str:
    return "".join(ch for ch in value.lower() if ch.isalnum())


def _cosine(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))
