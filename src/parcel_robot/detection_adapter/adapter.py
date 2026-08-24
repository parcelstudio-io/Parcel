"""DetectionMsg noise adapter — GT / clean detections → Habitat-style noise.

Produces and consumes ``contracts.DetectionMsg``. Pure RNG + math; no pixels.
"""

from __future__ import annotations

import math
import random
from collections.abc import Sequence
from dataclasses import dataclass, replace

from parcel_robot.contracts.freshness import DEFAULT_DETECTION_TTL_NS, expires_from_ttl
from parcel_robot.contracts.v1 import SCHEMA_VERSION, DetectionMsg, EvidenceEnvelopeV1
from parcel_robot.detection_adapter.noise import (
    DetectionNoiseConfig,
    default_person_confusion,
)


@dataclass(frozen=True, slots=True)
class GroundTruthDetection:
    """Oracle / GT observation before the detector-shaped adapter."""

    class_id: str
    embedding: tuple[float, ...]
    bearing_rad: float
    range_m: float
    track_id: str = ""
    score: float = 1.0

    def __post_init__(self) -> None:
        if not isinstance(self.class_id, str) or not self.class_id:
            raise ValueError("class_id must be non-empty")
        if not isinstance(self.embedding, tuple) or not self.embedding:
            raise ValueError("embedding must be a non-empty tuple")
        if len(self.embedding) > 2048:
            raise ValueError("embedding exceeds 2048 dims")
        for item in self.embedding:
            if isinstance(item, bool) or not isinstance(item, (int, float)) or not math.isfinite(
                float(item)
            ):
                raise ValueError("embedding components must be finite numbers")
        if isinstance(self.bearing_rad, bool) or not isinstance(self.bearing_rad, (int, float)):
            raise TypeError("bearing_rad must be numeric")
        if not math.isfinite(float(self.bearing_rad)):
            raise ValueError("bearing_rad must be finite")
        if not -math.pi - 1e-9 <= float(self.bearing_rad) <= math.pi + 1e-9:
            raise ValueError("bearing_rad must be in [-π, π]")
        if isinstance(self.range_m, bool) or not isinstance(self.range_m, (int, float)):
            raise TypeError("range_m must be numeric")
        if not math.isfinite(float(self.range_m)) or float(self.range_m) < 0.0:
            raise ValueError("range_m must be a finite non-negative number")
        if self.track_id and (not isinstance(self.track_id, str)):
            raise TypeError("track_id must be a string")
        if isinstance(self.score, bool) or not isinstance(self.score, (int, float)):
            raise TypeError("score must be numeric")
        if not 0.0 <= float(self.score) <= 1.0:
            raise ValueError("score must be in [0, 1]")


def _wrap_bearing(bearing: float) -> float:
    wrapped = (bearing + math.pi) % (2.0 * math.pi) - math.pi
    # Keep strictly inside DetectionMsg's inclusive [-π, π] with float noise.
    return max(-math.pi, min(math.pi, wrapped))


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


class DetectionNoiseAdapter:
    """GT → DetectionMsg with range cutoff, p_detect(d), confusion, jitter.

    Also accepts clean ``DetectionMsg`` inputs (re-noise for stress tests).
    """

    def __init__(
        self,
        config: DetectionNoiseConfig | None = None,
        *,
        source: str = "sim.detection_adapter",
        calibration_id: str = "d455-intrinsics-nominal",
        frame_id: str = "base_link",
        ttl_ns: int = DEFAULT_DETECTION_TTL_NS,
    ) -> None:
        self._config = config if config is not None else DetectionNoiseConfig(
            confusion=default_person_confusion()
        )
        if not isinstance(source, str) or not source:
            raise ValueError("source must be non-empty")
        if not isinstance(calibration_id, str) or not calibration_id:
            raise ValueError("calibration_id must be non-empty")
        if not isinstance(frame_id, str) or not frame_id:
            raise ValueError("frame_id must be non-empty")
        if isinstance(ttl_ns, bool) or not isinstance(ttl_ns, int) or ttl_ns <= 0:
            raise ValueError("ttl_ns must be a positive integer")
        self._source = source
        self._calibration_id = calibration_id
        self._frame_id = frame_id
        self._ttl_ns = ttl_ns
        self._sequence = 0

    @property
    def config(self) -> DetectionNoiseConfig:
        return self._config

    @property
    def vocabulary(self) -> frozenset[str]:
        return self._config.vocabulary

    def p_detect(self, range_m: float) -> float:
        return self._config.p_detect(range_m)

    def reset_sequence(self, sequence: int = 0) -> None:
        if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 0:
            raise ValueError("sequence must be a non-negative integer")
        self._sequence = sequence

    def adapt_ground_truth(
        self,
        detections: Sequence[GroundTruthDetection],
        *,
        rng: random.Random,
        received_monotonic_ns: int,
        source_timestamp_ns: int | None = None,
        scene_revision: int = 0,
        evidence_id_prefix: str = "det",
    ) -> list[DetectionMsg]:
        """Apply Habitat-style noise to GT detections → DetectionMsg list."""

        if not isinstance(rng, random.Random):
            raise TypeError("rng must be random.Random")
        if isinstance(received_monotonic_ns, bool) or not isinstance(
            received_monotonic_ns, int
        ):
            raise TypeError("received_monotonic_ns must be an integer")
        if received_monotonic_ns < 0:
            raise ValueError("received_monotonic_ns must be non-negative")
        src_ts = (
            received_monotonic_ns
            if source_timestamp_ns is None
            else source_timestamp_ns
        )
        if isinstance(src_ts, bool) or not isinstance(src_ts, int) or src_ts < 0:
            raise ValueError("source_timestamp_ns must be a non-negative integer")

        out: list[DetectionMsg] = []
        for gt in detections:
            if not isinstance(gt, GroundTruthDetection):
                raise TypeError("detections must contain GroundTruthDetection")
            msg = self._maybe_emit(
                class_id=gt.class_id,
                embedding=gt.embedding,
                bearing_rad=gt.bearing_rad,
                range_m=gt.range_m,
                track_id=gt.track_id,
                rng=rng,
                received_monotonic_ns=received_monotonic_ns,
                source_timestamp_ns=src_ts,
                scene_revision=scene_revision,
                evidence_id_prefix=evidence_id_prefix,
            )
            if msg is not None:
                out.append(msg)
        return out

    def adapt_detections(
        self,
        detections: Sequence[DetectionMsg],
        *,
        rng: random.Random,
        received_monotonic_ns: int | None = None,
        reissue_envelope: bool = True,
    ) -> list[DetectionMsg]:
        """Re-apply noise to existing DetectionMsg (consume → produce)."""

        if not isinstance(rng, random.Random):
            raise TypeError("rng must be random.Random")
        out: list[DetectionMsg] = []
        for det in detections:
            if not isinstance(det, DetectionMsg):
                raise TypeError("detections must contain DetectionMsg")
            recv = (
                det.envelope.received_monotonic_ns
                if received_monotonic_ns is None
                else received_monotonic_ns
            )
            msg = self._maybe_emit(
                class_id=det.class_id,
                embedding=det.embedding,
                bearing_rad=det.bearing_rad,
                range_m=det.range_m,
                track_id=det.track_id,
                rng=rng,
                received_monotonic_ns=recv,
                source_timestamp_ns=det.envelope.source_timestamp_ns,
                scene_revision=det.envelope.scene_revision,
                evidence_id_prefix="redet",
                base_envelope=None if reissue_envelope else det.envelope,
            )
            if msg is not None:
                out.append(msg)
        return out

    def _maybe_emit(
        self,
        *,
        class_id: str,
        embedding: tuple[float, ...],
        bearing_rad: float,
        range_m: float,
        track_id: str,
        rng: random.Random,
        received_monotonic_ns: int,
        source_timestamp_ns: int,
        scene_revision: int,
        evidence_id_prefix: str,
        base_envelope: EvidenceEnvelopeV1 | None = None,
    ) -> DetectionMsg | None:
        cfg = self._config
        if range_m > cfg.range_cutoff_m:
            return None
        if rng.random() > cfg.p_detect(range_m):
            return None

        pred_class = self._sample_confused_class(class_id, rng)
        if pred_class not in cfg.vocabulary:
            # Widened vocab still fail-closed: unknown labels collapse to unknown.
            pred_class = "unknown" if "unknown" in cfg.vocabulary else next(iter(cfg.vocabulary))

        noisy_bearing = _wrap_bearing(
            bearing_rad + rng.gauss(0.0, cfg.bearing_jitter_std_rad)
        )
        noisy_range = max(0.0, range_m + rng.gauss(0.0, cfg.range_jitter_std_m))
        if noisy_range > cfg.range_cutoff_m:
            return None
        noisy_score = _clamp01(cfg.score_base + rng.gauss(0.0, cfg.score_jitter_std))
        noisy_embedding = tuple(
            float(v) + rng.gauss(0.0, cfg.embedding_jitter_std) for v in embedding
        )

        if base_envelope is None:
            self._sequence += 1
            envelope = EvidenceEnvelopeV1(
                schema_version=SCHEMA_VERSION,
                evidence_id=f"{evidence_id_prefix}-{self._sequence}",
                source=self._source,
                source_timestamp_ns=source_timestamp_ns,
                received_monotonic_ns=received_monotonic_ns,
                sequence=self._sequence,
                frame_id=self._frame_id,
                scene_revision=scene_revision,
                expires_monotonic_ns=expires_from_ttl(
                    received_monotonic_ns=received_monotonic_ns, ttl_ns=self._ttl_ns
                ),
                calibration_id=self._calibration_id,
                provenance=("detection_noise_adapter_v1",),
            )
        else:
            envelope = replace(
                base_envelope,
                provenance=tuple(
                    dict.fromkeys([*base_envelope.provenance, "detection_noise_adapter_v1"])
                ),
            )

        return DetectionMsg(
            envelope=envelope,
            class_id=pred_class,
            embedding=noisy_embedding,
            bearing_rad=noisy_bearing,
            range_m=noisy_range,
            score=noisy_score,
            track_id=track_id,
        )

    def _sample_confused_class(self, true_class: str, rng: random.Random) -> str:
        row = self._config.confusion.get(true_class)
        if not row:
            return true_class
        draw = rng.random()
        cumulative = 0.0
        last = true_class
        for pred, prob in row.items():
            cumulative += prob
            last = pred
            if draw <= cumulative:
                return pred
        return last


def ground_truth_from_detection(msg: DetectionMsg) -> GroundTruthDetection:
    """Lift a DetectionMsg into GT form (for round-trip tests)."""

    return GroundTruthDetection(
        class_id=msg.class_id,
        embedding=msg.embedding,
        bearing_rad=msg.bearing_rad,
        range_m=msg.range_m,
        track_id=msg.track_id,
        score=msg.score,
    )
