from __future__ import annotations

import math
import time
from dataclasses import dataclass, field

from parcel_robot.models import VelocityCommand


@dataclass
class VelocitySmoother:
    """Bound velocity changes while allowing safety paths to stop immediately."""

    linear_accel: float = 0.9
    linear_decel: float = 1.4
    yaw_accel: float = 1.8
    max_dt: float = 0.25
    _current: VelocityCommand = field(default_factory=VelocityCommand, init=False)
    _updated_at: float | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        values = (self.linear_accel, self.linear_decel, self.yaw_accel, self.max_dt)
        if any(not math.isfinite(value) or value <= 0.0 for value in values):
            raise ValueError("velocity smoother limits must be positive and finite")

    def step(self, target: VelocityCommand, *, now: float | None = None) -> VelocityCommand:
        current_time = time.monotonic() if now is None else now
        if self._updated_at is None:
            dt = min(0.1, self.max_dt)
        else:
            dt = max(0.0, min(self.max_dt, current_time - self._updated_at))
        result = VelocityCommand(
            vx=self._linear_axis(self._current.vx, target.vx, dt),
            vy=self._linear_axis(self._current.vy, target.vy, dt),
            vyaw=self._axis(self._current.vyaw, target.vyaw, self.yaw_accel * dt),
        )
        self._current = result
        self._updated_at = current_time
        return result

    def force(self, command: VelocityCommand, *, now: float | None = None) -> None:
        """Synchronize with a command changed by a lower-level safety gate."""

        self._current = command
        self._updated_at = time.monotonic() if now is None else now

    def reset(self, *, now: float | None = None) -> None:
        self.force(VelocityCommand(), now=now)

    def _linear_axis(self, current: float, target: float, dt: float) -> float:
        # Use the stronger braking limit whenever magnitude is falling or the
        # command reverses direction.
        slowing = current * target < 0.0 or abs(target) < abs(current)
        limit = (self.linear_decel if slowing else self.linear_accel) * dt
        return self._axis(current, target, limit)

    @staticmethod
    def _axis(current: float, target: float, maximum_delta: float) -> float:
        return current + max(-maximum_delta, min(maximum_delta, target - current))
