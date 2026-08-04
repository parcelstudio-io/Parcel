"""Card W6: fail-closed configuration for the actuator-side S-curve shaper.

The shaper itself is Sol's pure `navigation.velocity_shaping` module. This is
only the `motion.shaping:` contract that decides whether it runs, with what
limits, and how far the calm-affect profile scales them down.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, fields
from typing import Any

from parcel_robot.navigation.velocity_shaping import ShaperLimits


def _positive(value: float, name: str) -> float:
    value = float(value)
    if not math.isfinite(value) or value <= 0.0:
        raise ValueError(f"motion.shaping.{name} must be finite and positive")
    return value


@dataclass(frozen=True)
class MotionShapingConfig:
    """Per-axis jerk limits for the SE2 hand-off, plus the calm-affect scale.

    Defaults are deliberately looser than the pre-existing acceleration
    smoother that runs before the collision gate: this stage exists to remove
    the remaining velocity steps the gate and arbiter introduce, not to become
    a second, slower rate limiter.
    """

    enabled: bool = False
    linear_max_accel: float = 1.2
    linear_max_jerk: float = 3.0
    yaw_max_accel: float = 2.4
    yaw_max_jerk: float = 6.0
    calm_scale: float = 0.6
    # Vocal arousal at or below this counts as the low-arousal affect state.
    calm_below_arousal: float = 0.35
    # Arousal evidence older than this stops steering the motion profile.
    arousal_valid_s: float = 20.0

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise TypeError("motion.shaping.enabled must be a boolean")
        for name in (
            "linear_max_accel",
            "linear_max_jerk",
            "yaw_max_accel",
            "yaw_max_jerk",
            "arousal_valid_s",
        ):
            _positive(getattr(self, name), name)
        if not math.isfinite(self.calm_scale) or not 0.0 < self.calm_scale <= 1.0:
            raise ValueError("motion.shaping.calm_scale must be within (0, 1]")
        if not math.isfinite(self.calm_below_arousal) or not 0.0 <= self.calm_below_arousal <= 1.0:
            raise ValueError("motion.shaping.calm_below_arousal must be within [0, 1]")

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> MotionShapingConfig:
        allowed = {item.name for item in fields(cls)}
        unknown = set(raw) - allowed
        if unknown:
            raise ValueError(f"unknown motion.shaping settings: {sorted(unknown)}")
        values: dict[str, Any] = {}
        for key, value in raw.items():
            if key == "enabled":
                if not isinstance(value, bool):
                    raise TypeError("motion.shaping.enabled must be a boolean")
                values[key] = value
            else:
                values[key] = float(value)
        return cls(**values)

    def limits(self) -> tuple[ShaperLimits, ShaperLimits, ShaperLimits]:
        """Return the ``(vx, vy, vyaw)`` limit triple in shaper order."""

        linear = ShaperLimits(self.linear_max_accel, self.linear_max_jerk)
        return (
            linear,
            ShaperLimits(self.linear_max_accel, self.linear_max_jerk),
            ShaperLimits(self.yaw_max_accel, self.yaw_max_jerk),
        )


__all__ = ["MotionShapingConfig"]
