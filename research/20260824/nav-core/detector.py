"""Detector-shaped semantic evidence: the pre-registered dropout and jitter.

The navigator's one semantic ingress is
``extras["semantic_candidates"]``, and under the ``learned_map`` source those
rows come from :func:`navigation.semantic_map.learned_map_candidates` — the
dog's own map, no oracle ids, no polygons, no stamped 0.98.  This module is the
*re-detection* layer on top of that: a place the map holds is not automatically
a place the dog sees this frame.

**Why not the product's own ``NoiseTier`` T1.**  ``PerceptionChain`` already
models range-scaled dropout and D455 range/bearing sigma, and it was the first
choice.  It also replaces every row's score with a draw from its
``ConfidenceModel`` — a third noise axis NAV-CORE did not pre-register, and one
that would move the ladder's confidence gate underneath the measurement.  The
two knobs the DESIGN fixed (``p = 0.2`` per re-detection, ``sigma = 0.15 m``
isotropic position jitter) are therefore applied here, literally, and the
earned ``evidence_confidence`` is left alone.  ``NoiseTier`` remains the right
home for this once the confidence model is a separable axis; that is a fix-list
line in RESULTS, not a change made mid-study.
"""

from __future__ import annotations

import random
from typing import Any

#: Pre-registered.  Probability that a place the map holds is NOT re-detected
#: this frame.  Flat in range: the room is 8 m across, and a range-scaled curve
#: would put a second, unregistered variable into the corpus.
DROPOUT_P = 0.20
#: Pre-registered.  Isotropic 1-sigma position error of a re-detection, metres.
JITTER_SIGMA_M = 0.15

#: Keys the oracle path carries that a detector cannot: exact polygons and the
#: LiDAR-id join.  Stripped here so a ladder that reaches for them measures
#: their absence rather than silently keeping the oracle.
_ORACLE_KEYS = ("polygon", "associated_lidar_ids")


class DetectorNoise:
    """One seeded re-detection stream.  Fresh per episode, like the map."""

    def __init__(self, seed: int) -> None:
        self._rng = random.Random(int(seed))
        self.offered = 0
        self.dropped = 0
        self.jitter_samples: list[float] = []

    def apply(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Drop and jitter one frame of learned-map candidates."""

        out: list[dict[str, Any]] = []
        for row in rows:
            self.offered += 1
            if self._rng.random() < DROPOUT_P:
                self.dropped += 1
                continue
            noisy = dict(row)
            for key in _ORACLE_KEYS:
                noisy.pop(key, None)
            metadata = dict(noisy.get("metadata") or {})
            for key in _ORACLE_KEYS:
                metadata.pop(key, None)
            metadata["semantic_source"] = "learned_map"
            metadata["detector_noise"] = "navcore_p20_s015"
            noisy["metadata"] = metadata
            position = list(noisy.get("position") or (0.0, 0.0, 0.0))
            while len(position) < 3:
                position.append(0.0)
            dx = self._rng.gauss(0.0, JITTER_SIGMA_M)
            dy = self._rng.gauss(0.0, JITTER_SIGMA_M)
            position[0] = float(position[0]) + dx
            position[1] = float(position[1]) + dy
            noisy["position"] = position
            self.jitter_samples.append((dx * dx + dy * dy) ** 0.5)
            out.append(noisy)
        return out

    @property
    def measured_dropout(self) -> float:
        return self.dropped / self.offered if self.offered else 0.0

    @property
    def measured_jitter_rms_m(self) -> float:
        if not self.jitter_samples:
            return 0.0
        return (sum(v * v for v in self.jitter_samples) / len(self.jitter_samples)) ** 0.5
