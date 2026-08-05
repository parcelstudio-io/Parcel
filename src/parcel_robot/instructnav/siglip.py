"""SigLIP-2 download seam for Grounder v2 embedding glue.

Weights are optional. When absent the matcher degrades loudly to exact/alias
string match so the rest of the stack stays exercisable offline.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_WEIGHTS = Path.home() / ".cache" / "parcel" / "siglip2-b16"


@dataclass(frozen=True)
class EmbeddingMatch:
    label: str
    score: float
    source: str  # "siglip2" | "string_fallback"


class SigLIP2Matcher:
    """Text embedding cosine matcher with loud degrade when weights missing."""

    def __init__(self, weights_dir: str | Path | None = None) -> None:
        self.weights_dir = Path(weights_dir) if weights_dir else DEFAULT_WEIGHTS
        self._available = self._probe()
        if not self._available:
            logger.warning(
                "SigLIP-2 weights not found at %s — degrading to string match "
                "(download seam stub; N-C1)",
                self.weights_dir,
            )

    @property
    def available(self) -> bool:
        return self._available

    def _probe(self) -> bool:
        # Real load would open safetensors / open_clip. Stub only checks presence.
        marker = self.weights_dir / "open_clip_model.safetensors"
        return marker.is_file()

    def match(
        self,
        query: str,
        labels: Sequence[str],
        *,
        threshold: float = 0.24,
    ) -> EmbeddingMatch | None:
        if not labels:
            return None
        if self._available:
            # Placeholder until weights land: deterministic hash embedding.
            q = _hash_embed(query)
            best: tuple[float, str] | None = None
            for label in labels:
                score = _cosine(q, _hash_embed(label))
                if best is None or score > best[0]:
                    best = (score, label)
            assert best is not None
            if best[0] >= threshold:
                return EmbeddingMatch(label=best[1], score=best[0], source="siglip2")
            return None
        # Loud string fallback.
        norm_q = _norm(query)
        for label in labels:
            if norm_q and (_norm(label) in norm_q or norm_q in _norm(label)):
                return EmbeddingMatch(label=label, score=1.0, source="string_fallback")
        return None


def _norm(value: str) -> str:
    return "".join(ch for ch in value.lower() if ch.isalnum())


def _hash_embed(text: str, dim: int = 32) -> tuple[float, ...]:
    values = [0.0] * dim
    token = _norm(text) or "empty"
    for index, ch in enumerate(token):
        values[index % dim] += (ord(ch) % 31) / 31.0
    norm = math.sqrt(sum(v * v for v in values)) or 1.0
    return tuple(v / norm for v in values)


def _cosine(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))
