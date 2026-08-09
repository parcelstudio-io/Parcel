"""GNSS covariance + dropout schedule (pure, sim stand-in for ZED-F9P-class).

HR-3: these parameters are *not* field-characterized. P5 re-runs against
recorded sidewalk/bench GNSS logs decide whether to keep or retune.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field


def _finite_prob(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be numeric")
    number = float(value)
    if not math.isfinite(number) or not 0.0 <= number <= 1.0:
        raise ValueError(f"{name} must be in [0, 1]")
    return number


def _finite_nonneg(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be numeric")
    number = float(value)
    if not math.isfinite(number) or number < 0.0:
        raise ValueError(f"{name} must be a finite non-negative number")
    return number


def _finite_pos(value: object, name: str) -> float:
    number = _finite_nonneg(value, name)
    if number <= 0.0:
        raise ValueError(f"{name} must be positive")
    return number


def _nonneg_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    if value < 0:
        raise ValueError(f"{name} must be non-negative")
    return value


@dataclass(frozen=True, slots=True)
class GnssDropoutWindow:
    """Inclusive start / exclusive end tick indices that force a dropout."""

    start_tick: int
    end_tick: int

    def __post_init__(self) -> None:
        start = _nonneg_int(self.start_tick, "start_tick")
        end = _nonneg_int(self.end_tick, "end_tick")
        if end <= start:
            raise ValueError("end_tick must exceed start_tick")
        object.__setattr__(self, "start_tick", start)
        object.__setattr__(self, "end_tick", end)

    def contains(self, tick: int) -> bool:
        return self.start_tick <= tick < self.end_tick


@dataclass(frozen=True, slots=True)
class GnssDropoutSchedule:
    """Deterministic canyon / cold-start dropout windows + optional Bernoulli.

    Schedule windows force dropouts independent of RNG (for CI reproducibility).
    ``p_dropout`` adds random dropouts outside scheduled windows.
    """

    windows: tuple[GnssDropoutWindow, ...] = ()
    p_dropout: float = 0.0
    period_ticks: int = 0
    burst_ticks: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.windows, tuple):
            raise TypeError("windows must be a tuple")
        for window in self.windows:
            if not isinstance(window, GnssDropoutWindow):
                raise TypeError("windows must contain GnssDropoutWindow")
        _finite_prob(self.p_dropout, "p_dropout")
        period = _nonneg_int(self.period_ticks, "period_ticks")
        burst = _nonneg_int(self.burst_ticks, "burst_ticks")
        if period == 0 and burst > 0:
            raise ValueError("burst_ticks requires period_ticks > 0")
        if period > 0 and burst > period:
            raise ValueError("burst_ticks must not exceed period_ticks")

    def is_dropout(self, tick: int, *, rng_draw: float | None = None) -> bool:
        tick_i = _nonneg_int(tick, "tick")
        for window in self.windows:
            if window.contains(tick_i):
                return True
        if self.period_ticks > 0 and self.burst_ticks > 0:
            phase = tick_i % self.period_ticks
            if phase < self.burst_ticks:
                return True
        if self.p_dropout > 0.0:
            if rng_draw is None:
                raise ValueError("rng_draw required when p_dropout > 0")
            draw = _finite_prob(rng_draw, "rng_draw")
            if draw < self.p_dropout:
                return True
        return False


@dataclass(frozen=True, slots=True)
class GnssNoiseConfig:
    """ZED-F9P-shaped planar GNSS noise for the sim stand-in (HR-3).

    Defaults are order-of-magnitude placeholders for unit tests — not
    commissioned urban-canyon / NTRIP statistics.
    """

    # Horizontal position jitter (map-frame meters).
    east_jitter_std_m: float = 1.5
    north_jitter_std_m: float = 1.5
    # Diagonal covariance reported on the fix (m^2); inflated under dropout exit.
    cov_east_m2: float = 2.25
    cov_north_m2: float = 2.25
    cov_cross_m2: float = 0.0
    # After a dropout burst, inflate covariance for ``post_dropout_inflate_ticks``.
    post_dropout_cov_scale: float = 4.0
    post_dropout_inflate_ticks: int = 3
    # Reject fixes whose reported horizontal std exceeds this.
    max_horizontal_std_m: float = 25.0
    hdop_base: float = 1.2
    hdop_jitter_std: float = 0.15
    num_sats_nominal: int = 12
    fix_type: str = "3d"
    dropout: GnssDropoutSchedule = field(default_factory=GnssDropoutSchedule)
    calibration_id: str = "gnss-sim-v1-nominal"

    def __post_init__(self) -> None:
        for name, value in (
            ("east_jitter_std_m", self.east_jitter_std_m),
            ("north_jitter_std_m", self.north_jitter_std_m),
            ("cov_east_m2", self.cov_east_m2),
            ("cov_north_m2", self.cov_north_m2),
            ("hdop_jitter_std", self.hdop_jitter_std),
        ):
            _finite_nonneg(value, name)
        _finite_nonneg(self.cov_cross_m2, "cov_cross_m2")
        _finite_pos(self.post_dropout_cov_scale, "post_dropout_cov_scale")
        _nonneg_int(self.post_dropout_inflate_ticks, "post_dropout_inflate_ticks")
        _finite_pos(self.max_horizontal_std_m, "max_horizontal_std_m")
        _finite_pos(self.hdop_base, "hdop_base")
        if isinstance(self.num_sats_nominal, bool) or not isinstance(
            self.num_sats_nominal, int
        ):
            raise TypeError("num_sats_nominal must be an integer")
        if self.num_sats_nominal < 0 or self.num_sats_nominal > 64:
            raise ValueError("num_sats_nominal must be in [0, 64]")
        if not isinstance(self.fix_type, str) or not self.fix_type:
            raise ValueError("fix_type must be non-empty")
        if not isinstance(self.dropout, GnssDropoutSchedule):
            raise TypeError("dropout must be GnssDropoutSchedule")
        if not isinstance(self.calibration_id, str) or not self.calibration_id:
            raise ValueError("calibration_id must be non-empty")


def schedule_from_windows(
    windows: Sequence[tuple[int, int]],
    *,
    p_dropout: float = 0.0,
    period_ticks: int = 0,
    burst_ticks: int = 0,
) -> GnssDropoutSchedule:
    """Build a schedule from ``(start, end)`` tick pairs."""

    return GnssDropoutSchedule(
        windows=tuple(GnssDropoutWindow(start, end) for start, end in windows),
        p_dropout=p_dropout,
        period_ticks=period_ticks,
        burst_ticks=burst_ticks,
    )
