"""GNSS observation model: GT east/north → noisy GnssFix (or dropout)."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

from parcel_robot.contracts import SCHEMA_VERSION, EvidenceEnvelopeV1, expires_from_ttl
from parcel_robot.gnss.noise import GnssNoiseConfig
from parcel_robot.gnss.sample import GnssFix

# Conservative until P5 characterization; GNSS is slower than UWB.
DEFAULT_GNSS_TTL_NS = 1_000_000_000  # 1 s


@dataclass(frozen=True, slots=True)
class GroundTruthGnss:
    """Oracle map-frame position before the GNSS noise model (test/scorer only)."""

    east_m: float
    north_m: float

    def __post_init__(self) -> None:
        for name, value in (("east_m", self.east_m), ("north_m", self.north_m)):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"{name} must be numeric")
            if not math.isfinite(float(value)):
                raise ValueError(f"{name} must be finite")


class GnssNoiseModel:
    """Pure sim stand-in for ZED-F9P-class ``gnss/fix`` (HR-3).

    Applies east/north Gaussian jitter, diagonal covariance, HDOP jitter, and
    the canyon/cold-start dropout schedule. Dropped ticks return ``None``.
    Post-dropout ticks inflate covariance for a few samples.
    """

    def __init__(
        self,
        config: GnssNoiseConfig | None = None,
        *,
        source: str = "sim.gnss",
        frame_id: str = "map",
        ttl_ns: int = DEFAULT_GNSS_TTL_NS,
    ) -> None:
        self._config = config if config is not None else GnssNoiseConfig()
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
        self._ticks_since_dropout = self._config.post_dropout_inflate_ticks + 1

    @property
    def config(self) -> GnssNoiseConfig:
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
        self._ticks_since_dropout = self._config.post_dropout_inflate_ticks + 1

    def observe(
        self,
        truth: GroundTruthGnss,
        *,
        rng: random.Random,
        received_monotonic_ns: int,
        source_timestamp_ns: int | None = None,
        scene_revision: int = 0,
        evidence_id_prefix: str = "gnss",
    ) -> GnssFix | None:
        """Emit one noisy fix, or None on canyon / cold-start dropout."""

        if not isinstance(truth, GroundTruthGnss):
            raise TypeError("truth must be GroundTruthGnss")
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

        draw = rng.random() if cfg.dropout.p_dropout > 0.0 else None
        if cfg.dropout.is_dropout(tick, rng_draw=draw):
            self._ticks_since_dropout = 0
            return None

        self._ticks_since_dropout += 1
        inflate = (
            cfg.post_dropout_cov_scale
            if self._ticks_since_dropout <= cfg.post_dropout_inflate_ticks
            else 1.0
        )

        noisy_east = truth.east_m + rng.gauss(0.0, cfg.east_jitter_std_m)
        noisy_north = truth.north_m + rng.gauss(0.0, cfg.north_jitter_std_m)
        cov_e = cfg.cov_east_m2 * inflate
        cov_n = cfg.cov_north_m2 * inflate
        cov_c = cfg.cov_cross_m2 * inflate
        horizontal_std = math.sqrt(max(cov_e, cov_n))
        if horizontal_std > cfg.max_horizontal_std_m:
            return None

        hdop = max(0.5, cfg.hdop_base * inflate + rng.gauss(0.0, cfg.hdop_jitter_std))
        sats = max(0, cfg.num_sats_nominal - (2 if inflate > 1.0 else 0))

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
            provenance=("gnss_noise_model_v1",),
        )
        return GnssFix(
            envelope=envelope,
            east_m=noisy_east,
            north_m=noisy_north,
            cov_east_m2=cov_e,
            cov_north_m2=cov_n,
            cov_cross_m2=cov_c,
            hdop=hdop,
            num_sats=sats,
            fix_type=cfg.fix_type,
            horizontal_std_m=horizontal_std,
        )
