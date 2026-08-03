from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from zoneinfo import ZoneInfo

from .models import ContextField


class ContextProvider(Protocol):
    kind: str

    def collect(self, now: datetime) -> ContextField: ...


@dataclass(frozen=True)
class ClockContextProvider:
    timezone: str
    kind: str = "time"

    def collect(self, now: datetime) -> ContextField:
        local = now.astimezone(ZoneInfo(self.timezone))
        return ContextField(
            kind=self.kind,
            source="system_clock",
            observed_at=now,
            value={
                "local_iso": local.isoformat(),
                "timezone": self.timezone,
                "weekday": local.strftime("%A"),
                "hour": local.hour,
            },
        )


@dataclass(frozen=True)
class CallableContextProvider:
    kind: str
    callback: Callable[[datetime], ContextField]

    def collect(self, now: datetime) -> ContextField:
        result = self.callback(now)
        if result.kind != self.kind:
            raise ValueError(f"{self.kind} provider returned {result.kind} context")
        return result
