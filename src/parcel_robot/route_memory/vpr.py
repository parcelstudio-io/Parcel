"""VPR embedding stubs for rendered-frame route memory (sim / UNVERIFIED).

GuideNav uses CosPlace-512; MegaLoc is the intended Jetson-class embedder.
This module ships a deterministic pose/frame stub so teach-and-repeat can be
exercised on sim walks without claiming real VPR recall.
"""

from __future__ import annotations

import hashlib
import math
import struct
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

DOES_NOT_PROVE = (
    (
        "StubVPREmbedder is a deterministic hash/pose stand-in for CosPlace / "
        "MegaLoc on rendered frames; it does not prove visual place recognition "
        "recall, viewpoint robustness at 35 cm, or GuideNav field VPR (HR-12)."
    ),
)


@runtime_checkable
class VPREmbedder(Protocol):
    """Embed a rendered frame (or pose stand-in) into a fixed vector."""

    dim: int

    def embed(
        self,
        *,
        pose: tuple[float, float, float] | None = None,
        frame_bytes: bytes | None = None,
        frame_id: str = "",
    ) -> tuple[float, ...]: ...


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    if len(a) != len(b) or not a:
        raise ValueError("embedding lengths must match and be non-empty")
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b, strict=True):
        xf = float(x)
        yf = float(y)
        if not math.isfinite(xf) or not math.isfinite(yf):
            raise ValueError("embedding components must be finite")
        dot += xf * yf
        na += xf * xf
        nb += yf * yf
    if na <= 0.0 or nb <= 0.0:
        return 0.0
    return max(-1.0, min(1.0, dot / math.sqrt(na * nb)))


@dataclass(frozen=True, slots=True)
class StubVPREmbedder:
    """Deterministic embedding from pose and/or frame bytes (sim only).

    Labeled UNVERIFIED for real CosPlace / MegaLoc. Suitable for CI and for
    wiring teach-and-repeat against rendered-frame bags without torch.
    """

    dim: int = 64
    quantize_m: float = 0.25
    label: str = "UNVERIFIED_stub_vpr"

    def __post_init__(self) -> None:
        if isinstance(self.dim, bool) or not isinstance(self.dim, int) or self.dim < 8:
            raise ValueError("dim must be an int ≥ 8")
        if not math.isfinite(self.quantize_m) or self.quantize_m <= 0.0:
            raise ValueError("quantize_m must be finite and positive")

    def embed(
        self,
        *,
        pose: tuple[float, float, float] | None = None,
        frame_bytes: bytes | None = None,
        frame_id: str = "",
    ) -> tuple[float, ...]:
        if pose is None and frame_bytes is None and not frame_id:
            raise ValueError("embed requires pose, frame_bytes, or frame_id")
        hasher = hashlib.sha256()
        hasher.update(b"parcel.stub_vpr.v1")
        hasher.update(struct.pack("<I", self.dim))
        if pose is not None:
            if len(pose) != 3 or not all(math.isfinite(float(v)) for v in pose):
                raise ValueError("pose must be finite (x, y, yaw)")
            qx = round(float(pose[0]) / self.quantize_m)
            qy = round(float(pose[1]) / self.quantize_m)
            qyaw = round(float(pose[2]) * 32.0 / math.pi)
            hasher.update(struct.pack("<iii", qx, qy, qyaw))
        if frame_bytes is not None:
            hasher.update(frame_bytes)
        if frame_id:
            hasher.update(frame_id.encode("utf-8"))
        digest = hasher.digest()
        # Expand digest into dim floats in [-1, 1].
        values: list[float] = []
        seed = digest
        while len(values) < self.dim:
            seed = hashlib.sha256(seed).digest()
            for i in range(0, len(seed), 4):
                if len(values) >= self.dim:
                    break
                raw = int.from_bytes(seed[i : i + 4], "little", signed=False)
                values.append((raw / 0xFFFFFFFF) * 2.0 - 1.0)
        # L2-normalize for cosine retrieval.
        norm = math.sqrt(sum(v * v for v in values)) or 1.0
        return tuple(v / norm for v in values)


def match_keyframe_index(
    query: Sequence[float],
    candidates: Sequence[Sequence[float]],
    *,
    min_similarity: float = 0.0,
) -> int | None:
    """Return index of best cosine match, or None if below threshold / empty."""

    if not candidates:
        return None
    best_i = -1
    best_s = float("-inf")
    for i, cand in enumerate(candidates):
        score = cosine_similarity(query, cand)
        if score > best_s:
            best_s = score
            best_i = i
    if best_i < 0 or best_s < min_similarity:
        return None
    return best_i
