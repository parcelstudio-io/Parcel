"""Resume intents and per-channel generation tokens (pure; stdlib only)."""

from __future__ import annotations

import threading
from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class ResumeIntent:
    channel: str
    payload: Mapping[str, object]  # typed per channel by the consumer
    suspend_reason: str
    suspended_at_s: float
    valid_for_s: float  # expiry; stale resumes are dropped
    requires_fresh_observation: bool = False

    def expired(self, now_s: float) -> bool:
        if not (self.valid_for_s >= 0.0):
            return True
        return float(now_s) >= float(self.suspended_at_s) + float(self.valid_for_s)


def resume_rejection_reason(
    intent: ResumeIntent | None,
    *,
    now_s: float,
    observation_fresh: bool | None = None,
) -> str | None:
    """Return a fail-closed rejection reason, or ``None`` when resume may proceed.

    Central gate for the suspend→resume transaction: expired intents and
    ``requires_fresh_observation`` without a proven-fresh sample never resume.
    """

    if intent is None:
        return "missing_intent"
    if intent.expired(now_s):
        return "expired"
    if intent.requires_fresh_observation and observation_fresh is not True:
        return "stale_observation"
    return None


class ResumeStore:
    """At most one intent per channel; replace-on-suspend, take-on-resume."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._intents: dict[str, ResumeIntent] = {}

    def record(self, intent: ResumeIntent) -> None:
        with self._lock:
            self._intents[intent.channel] = intent

    def take(self, channel: str, *, now_s: float) -> ResumeIntent | None:
        with self._lock:
            intent = self._intents.pop(channel, None)
            if intent is None:
                return None
            if intent.expired(now_s):
                return None
            return intent

    def peek(self, channel: str, *, now_s: float | None = None) -> ResumeIntent | None:
        """Return the intent if present and (when ``now_s`` given) unexpired.

        Expired intents are dropped so peek never resurrects a stale resume.
        """

        with self._lock:
            intent = self._intents.get(channel)
            if intent is None:
                return None
            if now_s is not None and intent.expired(now_s):
                self._intents.pop(channel, None)
                return None
            return intent

    def clear(self, channel: str | None = None) -> None:
        with self._lock:
            if channel is None:
                self._intents.clear()
            else:
                self._intents.pop(channel, None)

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return {
                channel: {
                    "channel": intent.channel,
                    "payload": dict(intent.payload),
                    "suspend_reason": intent.suspend_reason,
                    "suspended_at_s": intent.suspended_at_s,
                    "valid_for_s": intent.valid_for_s,
                    "requires_fresh_observation": intent.requires_fresh_observation,
                }
                for channel, intent in self._intents.items()
            }


class GenerationTokens:
    """Per-channel monotonic tokens replacing the global ``_behavior_generation``."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._tokens: dict[str, int] = {}

    def bump(self, channel: str) -> int:
        with self._lock:
            next_token = self._tokens.get(channel, 0) + 1
            self._tokens[channel] = next_token
            return next_token

    def current(self, channel: str) -> int:
        with self._lock:
            return self._tokens.get(channel, 0)

    def is_current(self, channel: str, token: int) -> bool:
        with self._lock:
            return self._tokens.get(channel, 0) == int(token)


__all__ = [
    "GenerationTokens",
    "ResumeIntent",
    "ResumeStore",
    "resume_rejection_reason",
]
