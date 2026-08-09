"""UWB observation model: GT bearing/range → noisy UwbSample (or dropout)."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

from parcel_robot.contracts import SCHEMA_VERSION, EvidenceEnvelopeV1, expires_from_ttl
from parcel_robot.uwb.noise import UwbNoiseConfig
from parcel_robot.uwb.sample import UwbSample

# Conservative until P5 characterization; matches track-class budgets.
DEFAULT_UWB_TTL_NS = 500_000_000  # 500 ms


def _wrap_bearing(bearing: float) -> float:
    wrapped = (bearing + math.pi) % (2.0 * math.pi) - math.pi
    return max(-math.pi, min(math.pi, wrapped))


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


@dataclass(frozen=True, slots=True)
class GroundTruthUwb:
    """Oracle owner-fob pose before the UWB noise model (test/scorer only)."""

    fob_id: str
    bearing_rad: float
    range_m: float

    def __post_init__(self) -> None:
        if not isinstance(self.fob_id, str) or not self.fob_id:
            raise ValueError("fob_id must be non-empty")
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


class UwbNoiseModel:
    """Pure sim stand-in for Go2 ``rt/uwbstate`` (HR-2).

    Applies bearing/range Gaussian jitter, quality roll-off, range cutoff, and
    the multipath dropout schedule. Dropped ticks return ``None``.
    """

    def __init__(
        self,
        config: UwbNoiseConfig | None = None,
        *,
        source: str = "sim.uwb",
        frame_id: str = "base_link",
        ttl_ns: int = DEFAULT_UWB_TTL_NS,
    ) -> None:
        self._config = config if config is not None else UwbNoiseConfig()
        if not isinstance(source, str) or not source:
            raise ValueError("source must be non-empty")
        if not isinstance(frame_id, str) or not frame_id:
            raise ValueError("frame_id must be non-empty")
        if isinstance(ttl_ns, bool) or not isinstance(ttl_ns, int) or ttl_ns <= 0:
            raise ValueError("ttl_ns must be a positive integer")
        self._source = source
        self._frame_id = frame_id
        self._ttl_ns = ttl_ns
        self._sequence = 0
        self._tick = 0

    @property
    def config(self) -> UwbNoiseConfig:
        return self._config

    @property
    def tick(self) -> int:
        return self._tick

    def reset(self, *, sequence: int = 0, tick: int = 0) -> None:
        if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 0:
            raise ValueError("sequence must be a non-negative integer")
        if isinstance(tick, bool) or not isinstance(tick, int) or tick < 0:
            raise ValueError("tick must be a non-negative integer")
        self._sequence = sequence
        self._tick = tick

    def observe(
        self,
        truth: GroundTruthUwb,
        *,
        rng: random.Random,
        received_monotonic_ns: int,
        source_timestamp_ns: int | None = None,
        scene_revision: int = 0,
        evidence_id_prefix: str = "uwb",
        force_multipath_suspect: bool = False,
    ) -> UwbSample | None:
        """Emit one noisy sample, or None on cutoff / multipath dropout."""

        if not isinstance(truth, GroundTruthUwb):
            raise TypeError("truth must be GroundTruthUwb")
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

        cfg = self._config
        tick = self._tick
        self._tick += 1

        draw = rng.random() if cfg.multipath.p_dropout > 0.0 else None
        if cfg.multipath.is_dropout(tick, rng_draw=draw):
            return None
        if truth.range_m > cfg.range_cutoff_m:
            return None

        noisy_bearing = _wrap_bearing(
            truth.bearing_rad + rng.gauss(0.0, cfg.bearing_jitter_std_rad)
        )
        noisy_range = max(0.0, truth.range_m + rng.gauss(0.0, cfg.range_jitter_std_m))
        if noisy_range > cfg.range_cutoff_m:
            return None
        quality = _clamp01(
            cfg.expected_quality(truth.range_m) + rng.gauss(0.0, cfg.quality_jitter_std)
        )

        self._sequence += 1
        envelope = EvidenceEnvelopeV1(
            schema_version=SCHEMA_VERSION,
            evidence_id=f"{evidence_id_prefix}-{self._sequence}",
            source=self._source,
            source_timestamp_ns=src_ts,
            received_monotonic_ns=received_monotonic_ns,
            sequence=self._sequence,
            frame_id=self._frame_id,
            scene_revision=scene_revision,
            expires_monotonic_ns=expires_from_ttl(
                received_monotonic_ns=received_monotonic_ns, ttl_ns=self._ttl_ns
            ),
            calibration_id=cfg.calibration_id,
            provenance=("uwb_noise_model_v1",),
        )
        return UwbSample(
            envelope=envelope,
            fob_id=truth.fob_id,
            bearing_rad=noisy_bearing,
            range_m=noisy_range,
            quality=quality,
            multipath_suspect=bool(force_multipath_suspect),
        )
