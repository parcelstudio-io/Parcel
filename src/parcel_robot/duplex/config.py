"""Fail-closed ``duplex:`` configuration (D0)."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, fields
from typing import Any


@dataclass(frozen=True)
class DuplexConfig:
    """Owner ceiling and D0 producer/logging switches.

    Unknown keys fail closed. Defaults keep fillers and the frame producer on
    so a missing section still obeys the ≤2 s audible-filler rule when wired.
    """

    enabled: bool = True
    filler_watchdog_s: float = 0.7
    response_ceiling_s: float = 2.0
    frame_hz: float = 10.0
    logging: bool = True
    log_dir: str = "logs/duplex"
    log_rotate_bytes: int = 2_000_000
    rng_seed: int | None = 20260804
    shadow_consumer: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise TypeError("duplex.enabled must be a boolean")
        if not isinstance(self.logging, bool):
            raise TypeError("duplex.logging must be a boolean")
        if not isinstance(self.shadow_consumer, bool):
            raise TypeError("duplex.shadow_consumer must be a boolean")
        for name in ("filler_watchdog_s", "response_ceiling_s", "frame_hz"):
            value = float(getattr(self, name))
            if not math.isfinite(value) or value <= 0.0:
                raise ValueError(f"duplex.{name} must be finite and positive")
        if float(self.filler_watchdog_s) >= float(self.response_ceiling_s):
            raise ValueError("duplex.filler_watchdog_s must be < response_ceiling_s")
        if int(self.log_rotate_bytes) < 4_096:
            raise ValueError("duplex.log_rotate_bytes must be >= 4096")
        if not str(self.log_dir).strip():
            raise ValueError("duplex.log_dir must be non-empty")

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any] | None) -> DuplexConfig:
        if raw is None:
            return cls()
        if not isinstance(raw, Mapping):
            raise TypeError("duplex config must be a mapping")
        allowed = {item.name for item in fields(cls)}
        unknown = set(raw) - allowed
        if unknown:
            raise ValueError(f"unknown duplex settings: {sorted(unknown)}")
        values: dict[str, Any] = {}
        for key, value in raw.items():
            if key in {"enabled", "logging", "shadow_consumer"}:
                if not isinstance(value, bool):
                    raise TypeError(f"duplex.{key} must be a boolean")
                values[key] = value
            elif key == "log_dir":
                values[key] = str(value)
            elif key == "log_rotate_bytes":
                values[key] = int(value)
            elif key == "rng_seed":
                values[key] = None if value is None else int(value)
            else:
                values[key] = float(value)
        return cls(**values)


__all__ = ["DuplexConfig"]
