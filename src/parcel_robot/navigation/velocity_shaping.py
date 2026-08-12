"""Per-axis jerk-limited target-velocity shaping."""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass

#: A nominal-stop step: ``(velocity, limits, dt_s) -> (vx, vy, vyaw)``.
#: ``parcel_robot.core.stop_ramp.nominal_stop_step`` is the only shipped
#: implementation. It is passed IN rather than imported so this module keeps no
#: dependency on ``core`` (``core.stop_ramp`` imports ``_move_toward`` from
#: here, and one direction is all the pair may have).
StopStep = Callable[
    [tuple[float, float, float], tuple["ShaperLimits", ...], float],
    Sequence[float],
]


@dataclass(frozen=True)
class ShaperLimits:
    max_accel: float
    max_jerk: float

    def __post_init__(self) -> None:
        if not math.isfinite(self.max_accel) or self.max_accel <= 0.0:
            raise ValueError("max_accel must be finite and positive")
        if not math.isfinite(self.max_jerk) or self.max_jerk <= 0.0:
            raise ValueError("max_jerk must be finite and positive")


def _move_toward(current: float, target: float, distance: float) -> float:
    if current < target:
        return min(current + distance, target)
    return max(current - distance, target)


def _is_braking_triple(current: tuple[float, float, float], candidate: object) -> bool:
    """True when ``candidate`` is a finite, per-axis braking successor."""

    if isinstance(candidate, (str, bytes)) or not isinstance(candidate, Sequence):
        return False
    if len(candidate) != 3:
        return False
    for index in range(3):
        value = candidate[index]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return False
        number = float(value)
        if not math.isfinite(number):
            return False
        if abs(number) > abs(current[index]) or current[index] * number < 0.0:
            return False
    return True


class SCurveVelocityShaper:
    """Per-axis jerk-limited tracking of a target velocity."""

    def __init__(self, vx: ShaperLimits, vy: ShaperLimits, vyaw: ShaperLimits) -> None:
        self._limits = (vx, vy, vyaw)
        self.reset()

    def reset(self, current: tuple[float, float, float] = (0.0, 0.0, 0.0)) -> None:
        if len(current) != 3 or not all(math.isfinite(value) for value in current):
            raise ValueError("current must contain three finite values")
        self._velocity = [float(value) for value in current]
        self._acceleration = [0.0, 0.0, 0.0]

    @staticmethod
    def _normal_step(
        velocity: float,
        acceleration: float,
        target: float,
        dt_s: float,
        limits: ShaperLimits,
    ) -> tuple[float, float]:
        error = target - velocity
        if error == 0.0 and acceleration == 0.0:
            return velocity, acceleration

        direction = 1.0 if error > 0.0 else -1.0 if error < 0.0 else 0.0
        # Cap acceleration by the positive root of
        #   error = a^2 / (2j) + a * switching_dt.
        # The first term reserves the velocity needed to ramp acceleration to
        # zero; the second is a conservative loop-jitter margin. Approaching
        # the target from one side therefore stays monotonic.
        switching_dt = max(dt_s, 0.05)
        acceleration_cap = (
            math.sqrt(
                (limits.max_jerk * switching_dt) ** 2
                + 2.0 * limits.max_jerk * abs(error)
            )
            - limits.max_jerk * switching_dt
        )
        desired_acceleration = direction * min(limits.max_accel, acceleration_cap)

        jerk_delta = limits.max_jerk * dt_s
        next_acceleration = _move_toward(
            acceleration, desired_acceleration, jerk_delta
        )
        next_acceleration = max(
            -limits.max_accel, min(limits.max_accel, next_acceleration)
        )
        candidate = velocity + next_acceleration * dt_s

        # Land exactly when doing so respects this tick's acceleration and
        # jerk bounds. This removes discretization overshoot without a snap.
        if error != 0.0 and (target - velocity) * (target - candidate) <= 0.0:
            landing_acceleration = error / dt_s
            if (
                abs(landing_acceleration) <= limits.max_accel
                and abs(landing_acceleration - acceleration) <= jerk_delta + 1e-12
            ):
                return target, landing_acceleration
        return candidate, next_acceleration

    def step(
        self,
        target: tuple[float, float, float],
        *,
        dt_s: float,
        emergency: bool = False,
        stop: StopStep | None = None,
    ) -> tuple[float, float, float]:
        if len(target) != 3 or not all(math.isfinite(value) for value in target):
            raise ValueError("target must contain three finite values")
        if not math.isfinite(dt_s) or dt_s <= 0.0:
            raise ValueError("dt_s must be finite and positive")

        if emergency:
            # Hard stops must not leave a residual ramp on the actuator.
            # Accel/jerk limits are intentionally ignored: the next command is
            # exact zero on every axis.
            self._acceleration = [0.0, 0.0, 0.0]
            self._velocity = [0.0, 0.0, 0.0]
            return (0.0, 0.0, 0.0)

        if stop is not None:
            # Card J-B: a NOMINAL stop decays instead of snapping. ``emergency``
            # above always wins, so no hard stop can reach this branch. The
            # target is ignored on purpose — a stop has exactly one target.
            return self._stop_step(stop, dt_s)

        for index, limits in enumerate(self._limits):
            next_velocity, next_acceleration = self._normal_step(
                self._velocity[index],
                self._acceleration[index],
                float(target[index]),
                dt_s,
                limits,
            )
            self._velocity[index] = next_velocity
            self._acceleration[index] = next_acceleration
        return tuple(self._velocity)

    def _stop_step(self, stop: StopStep, dt_s: float) -> tuple[float, float, float]:
        """Run a supplied nominal-stop step, failing closed to the exact zero.

        The supplied callable is untrusted: anything it returns that is not a
        finite, per-axis non-increasing, sign-preserving triple collapses to the
        emergency result. A stop stage can therefore only ever brake.
        """

        current = (self._velocity[0], self._velocity[1], self._velocity[2])
        try:
            candidate = stop(current, self._limits, dt_s)
        except Exception:  # noqa: BLE001 - an untrusted stop stage may not raise past here
            candidate = None
        if not _is_braking_triple(current, candidate):
            self._acceleration = [0.0, 0.0, 0.0]
            self._velocity = [0.0, 0.0, 0.0]
            return (0.0, 0.0, 0.0)
        for index in range(3):
            next_velocity = float(candidate[index])  # type: ignore[index]
            self._acceleration[index] = (next_velocity - current[index]) / dt_s
            self._velocity[index] = next_velocity
        return (self._velocity[0], self._velocity[1], self._velocity[2])

    def scaled(self, factor: float) -> SCurveVelocityShaper:
        if not math.isfinite(factor) or factor <= 0.0:
            raise ValueError("factor must be finite and positive")
        scaled_limits = tuple(
            ShaperLimits(limit.max_accel * factor, limit.max_jerk * factor)
            for limit in self._limits
        )
        result = SCurveVelocityShaper(*scaled_limits)
        result._velocity = self._velocity.copy()
        result._acceleration = [
            max(-limit.max_accel, min(limit.max_accel, acceleration * factor))
            for acceleration, limit in zip(self._acceleration, scaled_limits)
        ]
        return result
