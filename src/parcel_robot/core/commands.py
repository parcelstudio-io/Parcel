from __future__ import annotations

import math
import time
from dataclasses import dataclass, field

from parcel_robot.models import VelocityCommand

SOURCE_PRIORITIES: dict[str, int] = {
    "navigation": 30,
    "follow": 40,
    "voice": 60,
    "manual": 80,
    "safety": 100,
}


@dataclass(frozen=True)
class MotionIntent:
    """A time-limited request to move from one named command source."""

    command: VelocityCommand
    source: str
    ttl: float = 0.35
    issued_at: float = field(default_factory=time.monotonic)
    priority: int | None = None

    def __post_init__(self) -> None:
        if self.source not in SOURCE_PRIORITIES:
            raise ValueError(f"unknown command source: {self.source}")
        if not math.isfinite(self.issued_at):
            raise ValueError("issued_at must be finite")
        if not math.isfinite(self.ttl) or self.ttl <= 0:
            raise ValueError("ttl must be a positive finite duration")
        values = (self.command.vx, self.command.vy, self.command.vyaw)
        if any(not math.isfinite(value) for value in values):
            raise ValueError("motion command values must be finite")

    @property
    def effective_priority(self) -> int:
        return self.priority if self.priority is not None else SOURCE_PRIORITIES[self.source]

    def expired(self, now: float | None = None) -> bool:
        current = time.monotonic() if now is None else now
        return current >= self.issued_at + self.ttl
