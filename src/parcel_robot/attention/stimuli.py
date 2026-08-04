"""Typed stimulus bus with ADD/REVOKE/COMMIT lifecycle (pure; numpy/stdlib)."""

from __future__ import annotations

import math
import threading
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum

import numpy as np


class StimulusKind(str, Enum):
    SPEECH_ONSET = "speech_onset"
    SUMMONS_PROSODY = "summons_prosody"
    NAME_HIT = "name_hit"
    AFFECT = "affect"
    KEYWORD = "keyword"
    SPEECH_END = "speech_end"


@dataclass(frozen=True)
class Stimulus:
    kind: StimulusKind
    at_s: float
    confidence: float  # 0..1
    payload: Mapping[str, object] = field(default_factory=dict)
    unit_id: int = 0  # IU lifecycle identity

    def __post_init__(self) -> None:
        if not math.isfinite(self.at_s):
            raise ValueError("stimulus timestamp must be finite")
        if not math.isfinite(self.confidence) or not 0.0 <= self.confidence <= 1.0:
            raise ValueError("stimulus confidence must be in [0, 1]")


class StimulusBus:
    """Incremental-unit bus: ADD → optional REVOKE → COMMIT → drain."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._next_id = 1
        self._pending: dict[int, Stimulus] = {}
        self._committed: list[Stimulus] = []

    def add(self, stimulus: Stimulus) -> int:
        with self._lock:
            unit_id = self._next_id
            self._next_id += 1
            stored = Stimulus(
                kind=stimulus.kind,
                at_s=stimulus.at_s,
                confidence=stimulus.confidence,
                payload=dict(stimulus.payload),
                unit_id=unit_id,
            )
            self._pending[unit_id] = stored
            return unit_id

    def revoke(self, unit_id: int) -> bool:
        with self._lock:
            return self._pending.pop(int(unit_id), None) is not None

    def commit(self, unit_id: int) -> bool:
        with self._lock:
            stimulus = self._pending.pop(int(unit_id), None)
            if stimulus is None:
                return False
            self._committed.append(stimulus)
            return True

    def drain(
        self,
        *,
        now_s: float,
        max_age_s: float = 2.0,
    ) -> tuple[Stimulus, ...]:
        """Return committed, fresh stimuli in FIFO order; drop stale."""

        if not math.isfinite(now_s) or not math.isfinite(max_age_s) or max_age_s < 0.0:
            raise ValueError("drain clock and max_age must be finite and non-negative")
        with self._lock:
            kept: list[Stimulus] = []
            fresh: list[Stimulus] = []
            for stimulus in self._committed:
                age = now_s - stimulus.at_s
                if age <= max_age_s:
                    fresh.append(stimulus)
                    kept.append(stimulus)
            # Drain removes delivered events; stale ones are discarded.
            self._committed = []
            return tuple(fresh)


def summons_prosody_score(pcm: np.ndarray, sample_rate_hz: int) -> float:
    """Score a short PCM window for summons-like rising F0 + energy.

    Rising-contour high-energy calls score high; flat conversation and silence
    score low. Uses autocorrelation F0 estimates — content-free.
    """

    if sample_rate_hz <= 0:
        raise ValueError("sample_rate_hz must be positive")
    samples = np.asarray(pcm, dtype=np.float64).reshape(-1)
    if samples.size < max(32, sample_rate_hz // 50):
        return 0.0
    peak = float(np.max(np.abs(samples)))
    if peak <= 1e-9:
        return 0.0
    if peak > 1.0 + 1e-6:
        samples = samples / 32768.0
    energy = float(np.sqrt(np.mean(samples * samples)))
    if energy < 0.01:
        return 0.0

    # Split into early/late halves for F0 rise.
    mid = samples.size // 2
    f0_early = _estimate_f0_hz(samples[:mid], sample_rate_hz)
    f0_late = _estimate_f0_hz(samples[mid:], sample_rate_hz)
    if f0_early <= 0.0 and f0_late <= 0.0:
        return float(np.clip(energy * 0.15, 0.0, 1.0))

    f0_mean = 0.5 * (max(f0_early, 1.0) + max(f0_late, 1.0))
    rise = 0.0
    if f0_early > 0.0 and f0_late > 0.0:
        rise = (f0_late - f0_early) / max(f0_early, 1.0)
    # Variance proxy: relative half difference.
    variance = abs(f0_late - f0_early) / max(f0_mean, 1.0)

    energy_term = float(np.clip(energy / 0.25, 0.0, 1.0))
    rise_term = float(np.clip(rise / 0.35, 0.0, 1.0))
    var_term = float(np.clip(variance / 0.40, 0.0, 1.0))
    # Rising high-energy dominates; flat conversation stays low.
    score = 0.45 * energy_term + 0.40 * rise_term + 0.15 * var_term
    return float(np.clip(score, 0.0, 1.0))


def name_fusion_score(
    name_posterior: float,
    facing_deg: float,
    distance_m: float,
) -> float:
    """Soft-fuse name detector with facing and distance (never hard-gates)."""

    if not math.isfinite(name_posterior) or not 0.0 <= name_posterior <= 1.0:
        raise ValueError("name_posterior must be in [0, 1]")
    if not math.isfinite(facing_deg):
        raise ValueError("facing_deg must be finite")
    if not math.isfinite(distance_m) or distance_m < 0.0:
        raise ValueError("distance_m must be finite and non-negative")

    facing = abs(((facing_deg + 180.0) % 360.0) - 180.0)
    facing_term = max(0.0, 1.0 - facing / 90.0)
    # Prefer conversational distance (~0.8–2.5 m); degrade outside.
    if distance_m <= 0.4:
        distance_term = distance_m / 0.4
    elif distance_m <= 2.5:
        distance_term = 1.0
    else:
        distance_term = max(0.0, 1.0 - (distance_m - 2.5) / 3.5)

    # Never hard-gate on the name detector: even a weak hit contributes.
    fused = (
        0.55 * float(name_posterior)
        + 0.25 * facing_term
        + 0.20 * distance_term
    )
    return float(min(1.0, max(0.0, fused)))


def _estimate_f0_hz(samples: np.ndarray, sample_rate_hz: int) -> float:
    """Cheap autocorrelation F0 in a voice-ish band (80–400 Hz)."""

    if samples.size < 16:
        return 0.0
    window = samples - float(np.mean(samples))
    if float(np.max(np.abs(window))) <= 1e-12:
        return 0.0
    min_lag = max(2, int(sample_rate_hz / 400))
    max_lag = min(samples.size - 1, int(sample_rate_hz / 80))
    if max_lag <= min_lag:
        return 0.0
    best_lag = 0
    best_corr = 0.0
    energy = float(np.dot(window, window)) + 1e-12
    for lag in range(min_lag, max_lag + 1):
        corr = float(np.dot(window[:-lag], window[lag:])) / energy
        if corr > best_corr:
            best_corr = corr
            best_lag = lag
    if best_lag <= 0 or best_corr < 0.25:
        return 0.0
    return float(sample_rate_hz) / float(best_lag)


__all__ = [
    "Stimulus",
    "StimulusBus",
    "StimulusKind",
    "name_fusion_score",
    "summons_prosody_score",
]
