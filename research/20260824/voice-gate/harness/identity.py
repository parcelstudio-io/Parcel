#!/usr/bin/env python
"""The owner-ID arm, enrolled the way the product enrolls — on a research gallery.

The owner's real voice is not on this disk and the owner is not here, so the
"owner" is a designated proxy: one of the six human prompt voices in
``models/csm-1b/prompts``. That choice is stated in every row it touches.

THE GALLERY IS THE PRODUCT'S, THE PATH IS NOT
---------------------------------------------
Enrollment runs through ``tools/enroll_owner_voice.py`` — the same refusals, the
same self-consistency check, the same ``OwnerVoiceProfile`` on disk — but never
at the owner's own profile path. The tool refuses to write inside the repository
(``refuse_repo_path``: "it is biometric material about one person"), which is
also why the research gallery lives in the session scratchpad rather than under
``research/20260824/voice-gate/``. The owner's live gallery is never opened.
"""

from __future__ import annotations

import subprocess
import sys
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from parcel_robot.realtime.voice_identity import (
    DEFAULT_THRESHOLD,
    OwnerVoiceProfile,
    SherpaSpeakerEmbedder,
    cosine,
    load_owner_profile,
)

from .gate import Decision, Placement

REPO_ROOT = Path(__file__).resolve().parents[4]
RATE_HZ = 16_000
MODEL_PATH = REPO_ROOT / "models" / "speaker_id" / "nemo_en_titanet_small.onnx"


def to_pcm16(samples: np.ndarray) -> np.ndarray:
    return np.clip(np.rint(np.asarray(samples) * 32768.0), -32768, 32767).astype("<i2")


def write_wav(path: Path, samples: np.ndarray) -> None:
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(RATE_HZ)
        handle.writeframes(to_pcm16(samples).tobytes())


def voiced_segments(
    samples: np.ndarray, *, segment_s: float, hop_s: float, floor_db: float = 12.0
) -> list[tuple[float, np.ndarray]]:
    """Fixed-length windows whose energy is well above the clip's own quiet floor."""

    window = int(segment_s * RATE_HZ)
    hop = int(hop_s * RATE_HZ)
    block = 256
    usable = samples.size - samples.size % block
    frame_rms = np.sqrt(
        np.maximum(1e-12, (samples[:usable].reshape(-1, block) ** 2).mean(axis=1))
    )
    floor = float(np.percentile(frame_rms, 10.0))
    out: list[tuple[float, np.ndarray]] = []
    for start in range(0, max(0, samples.size - window + 1), hop):
        chunk = samples[start : start + window]
        level = float(np.sqrt(np.mean(chunk**2)) + 1e-12)
        if level >= floor * (10.0 ** (floor_db / 20.0)):
            out.append((start / RATE_HZ, chunk))
    return out


@dataclass
class Enrollment:
    profile_path: Path
    utterances: int
    stdout: str


def enroll_research_gallery(
    owner_samples: np.ndarray,
    scratch: Path,
    *,
    utterances: int = 6,
    segment_s: float = 2.5,
    enroll_until_s: float = 15.0,
) -> Enrollment:
    """Cut enrollment WAVs from the owner proxy's first seconds and run the tool."""

    scratch.mkdir(parents=True, exist_ok=True)
    head = owner_samples[: int(enroll_until_s * RATE_HZ)]
    segments = voiced_segments(head, segment_s=segment_s, hop_s=segment_s)[:utterances]
    if len(segments) < utterances:
        raise RuntimeError(
            f"owner proxy yielded {len(segments)} enrollment segments, needed {utterances}"
        )
    paths: list[Path] = []
    for index, (_offset, chunk) in enumerate(segments):
        path = scratch / f"enroll_{index}.wav"
        write_wav(path, chunk)
        paths.append(path)
    profile_path = scratch / "research_owner_voice.json"
    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "tools" / "enroll_owner_voice.py"),
            "--wav", *[str(path) for path in paths],
            "--out", str(profile_path),
        ],
        check=True,
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    return Enrollment(profile_path=profile_path, utterances=len(paths), stdout=result.stdout)


class OwnerIdentity:
    """TitaNet against the research gallery, at the product's own threshold."""

    def __init__(self, profile_path: Path, *, threshold: float = DEFAULT_THRESHOLD) -> None:
        profile = load_owner_profile(profile_path)
        if profile is None:
            raise RuntimeError(f"no usable owner profile at {profile_path}")
        self.profile: OwnerVoiceProfile = profile
        self.embedder = SherpaSpeakerEmbedder(MODEL_PATH)
        self.threshold = float(threshold)
        self.scores: list[float] = []

    def score(self, pcm16: np.ndarray) -> float:
        embedding = self.embedder.embed(np.asarray(pcm16, dtype="<i2").tobytes(), RATE_HZ)
        value = float(cosine(embedding, self.profile.embedding))
        self.scores.append(value)
        return value

    def arm(self, window: np.ndarray, _open_s: float, _placement: Placement | None) -> Decision:
        value = self.score(window)
        return Decision(
            admit=value >= self.threshold,
            reason="owner_id" if value >= self.threshold else "not_owner",
            score=value,
        )


def cosine_matrix(
    embedder: SherpaSpeakerEmbedder, panels: dict[str, list[np.ndarray]]
) -> dict[str, dict[str, float]]:
    """Mean cosine between every pair of voices — the identity proxy's own quality."""

    vectors = {
        label: [embedder.embed(to_pcm16(chunk).tobytes(), RATE_HZ) for chunk in chunks]
        for label, chunks in panels.items()
    }
    out: dict[str, dict[str, float]] = {}
    for left, left_vectors in vectors.items():
        out[left] = {}
        for right, right_vectors in vectors.items():
            values = [
                cosine(a, b)
                for index, a in enumerate(left_vectors)
                for jndex, b in enumerate(right_vectors)
                if not (left == right and index >= jndex)
            ]
            out[left][right] = float(np.mean(values)) if values else float("nan")
    return out


__all__ = [
    "MODEL_PATH",
    "Enrollment",
    "OwnerIdentity",
    "cosine_matrix",
    "enroll_research_gallery",
    "voiced_segments",
    "write_wav",
]
