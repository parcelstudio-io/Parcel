"""UWB bearing/range noise + multipath dropout schedule (pure, sim stand-in).

HR-2: these parameters are *not* field-characterized. P5 re-runs against
``rt/uwbstate`` decide whether to keep, retune, or invert channel primary.
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
class MultipathWindow:
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
class MultipathDropoutSchedule:
    """Deterministic multipath dropout windows + optional Bernoulli dropouts.

    Schedule windows force dropouts independent of RNG (for CI reproducibility).
    ``p_dropout`` adds random dropouts outside scheduled windows.
    """

    windows: tuple[MultipathWindow, ...] = ()
    p_dropout: float = 0.0
    # Periodic pattern: every ``period_ticks`` ticks, drop ``burst_ticks``.
    period_ticks: int = 0
    burst_ticks: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.windows, tuple):
            raise TypeError("windows must be a tuple")
        for window in self.windows:
            if not isinstance(window, MultipathWindow):
                raise TypeError("windows must contain MultipathWindow")
        _finite_prob(self.p_dropout, "p_dropout")
        period = _nonneg_int(self.period_ticks, "period_ticks")
        burst = _nonneg_int(self.burst_ticks, "burst_ticks")
        if period == 0 and burst > 0:
            raise ValueError("burst_ticks requires period_ticks > 0")
        if period > 0 and burst > period:
            raise ValueError("burst_ticks must not exceed period_ticks")

    def is_dropout(self, tick: int, *, rng_draw: float | None = None) -> bool:
        """Return True when tick should drop the UWB sample."""

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
class UwbNoiseConfig:
    """Go2-fob-shaped bearing/range noise for the sim stand-in (HR-2).

    Defaults are order-of-magnitude placeholders for unit tests — not
    commissioned Unitree ``rt/uwbstate`` statistics.
    """

    range_cutoff_m: float = 30.0
    bearing_jitter_std_rad: float = 0.08
    range_jitter_std_m: float = 0.25
    quality_base: float = 0.9
    quality_jitter_std: float = 0.05
    # Mild range-dependent quality roll-off (near → far).
    quality_near_range_m: float = 2.0
    quality_far_range_m: float = 20.0
    quality_far: float = 0.55
    multipath: MultipathDropoutSchedule = field(
        default_factory=MultipathDropoutSchedule
    )
    calibration_id: str = "uwb-sim-v1-nominal"

    def __post_init__(self) -> None:
        _finite_pos(self.range_cutoff_m, "range_cutoff_m")
        for name, value in (
            ("bearing_jitter_std_rad", self.bearing_jitter_std_rad),
            ("range_jitter_std_m", self.range_jitter_std_m),
            ("quality_jitter_std", self.quality_jitter_std),
        ):
            _finite_nonneg(value, name)
        _finite_prob(self.quality_base, "quality_base")
        _finite_prob(self.quality_far, "quality_far")
        near_r = _finite_nonneg(self.quality_near_range_m, "quality_near_range_m")
        far_r = _finite_nonneg(self.quality_far_range_m, "quality_far_range_m")
        if far_r <= near_r:
            raise ValueError("quality_far_range_m must exceed quality_near_range_m")
        if not isinstance(self.multipath, MultipathDropoutSchedule):
            raise TypeError("multipath must be MultipathDropoutSchedule")
        if not isinstance(self.calibration_id, str) or not self.calibration_id:
            raise ValueError("calibration_id must be non-empty")

    def expected_quality(self, range_m: float) -> float:
        """Nominal quality before jitter (piecewise linear in range)."""

        distance = _finite_nonneg(range_m, "range_m")
        if distance <= self.quality_near_range_m:
            return self.quality_base
        if distance >= self.quality_far_range_m:
            return self.quality_far
        span = self.quality_far_range_m - self.quality_near_range_m
        t = (distance - self.quality_near_range_m) / span
        return self.quality_base + t * (self.quality_far - self.quality_base)


def schedule_from_windows(
    windows: Sequence[tuple[int, int]],
    *,
    p_dropout: float = 0.0,
    period_ticks: int = 0,
    burst_ticks: int = 0,
) -> MultipathDropoutSchedule:
    """Build a schedule from ``(start, end)`` tick pairs."""

    return MultipathDropoutSchedule(
        windows=tuple(MultipathWindow(start, end) for start, end in windows),
        p_dropout=p_dropout,
        period_ticks=period_ticks,
        burst_ticks=burst_ticks,
    )
