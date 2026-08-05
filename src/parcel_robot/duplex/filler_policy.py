"""Predictive + watchdog filler policy state (pure timing; no I/O)."""

from __future__ import annotations

import math
import threading
from dataclasses import dataclass

from .fillers import FillerEntry, FillerPool


@dataclass(frozen=True)
class FillerFire:
    entry: FillerEntry
    reason: str  # "predictive" | "watchdog"
    latency_s: float


@dataclass
class FillerPolicy:
    """Tracks end-of-turn → first-audible-token timing and decides when to fill.

    Callers own TTS/playback. This object only answers "should a filler fire
    now?" and records latency / ceiling-breach counters for ``/api/state``.

    ``on_first_token`` means the first token reached the TTS queue (or the
    text-only delivery path) — not LLM text alone. Predictive and watchdog
    share a lock so only one filler fires per turn.
    """

    pool: FillerPool
    watchdog_s: float = 0.7
    ceiling_s: float = 2.0

    def __post_init__(self) -> None:
        if not math.isfinite(self.watchdog_s) or self.watchdog_s <= 0.0:
            raise ValueError("watchdog_s must be finite and positive")
        if not math.isfinite(self.ceiling_s) or self.ceiling_s <= 0.0:
            raise ValueError("ceiling_s must be finite and positive")
        self._lock = threading.Lock()
        self._turn_started_s: float | None = None
        self._first_token_s: float | None = None
        self._filler_fired = False
        self._filler_audible_s: float | None = None
        self._pending_reply: str | None = None
        self._awaiting_clause_boundary = False
        self._breach_counted_for_turn: float | None = None
        self.filler_latency_s: float | None = None
        self.response_ceiling_breaches = 0
        self.fillers_fired = 0
        self.last_filler_text: str | None = None
        self.last_filler_reason: str | None = None

    def on_turn_start(self, *, now_s: float) -> None:
        with self._lock:
            self._turn_started_s = float(now_s)
            self._first_token_s = None
            self._filler_fired = False
            self._filler_audible_s = None
            self._pending_reply = None
            self._awaiting_clause_boundary = False
            self._breach_counted_for_turn = None
            self.filler_latency_s = None
            self.last_filler_text = None
            self.last_filler_reason = None

    def on_first_token(self, *, now_s: float) -> None:
        """Mark first token on the TTS queue / audible delivery path."""

        with self._lock:
            if self._first_token_s is None:
                self._first_token_s = float(now_s)

    def on_filler_audible(self, *, now_s: float) -> None:
        with self._lock:
            if self._filler_audible_s is None and self._turn_started_s is not None:
                self._filler_audible_s = float(now_s)
                self.filler_latency_s = self._filler_audible_s - self._turn_started_s

    def note_clause_boundary_pending(self, reply: str) -> None:
        """Real reply arrived while a filler is mid-utterance."""

        with self._lock:
            self._pending_reply = str(reply)
            self._awaiting_clause_boundary = True

    def take_pending_reply(self) -> str | None:
        with self._lock:
            if not self._awaiting_clause_boundary:
                return None
            reply = self._pending_reply
            self._pending_reply = None
            self._awaiting_clause_boundary = False
            return reply

    @property
    def awaiting_clause_boundary(self) -> bool:
        with self._lock:
            return self._awaiting_clause_boundary

    def predictive_fire(
        self,
        *,
        now_s: float,
        personality_gain: float = 1.0,
        reason: str = "predictive",
    ) -> FillerFire | None:
        with self._lock:
            if self._filler_fired or self._first_token_s is not None:
                return None
            if self._turn_started_s is None:
                self._turn_started_s = float(now_s)
                self._first_token_s = None
                self._filler_audible_s = None
                self._pending_reply = None
                self._awaiting_clause_boundary = False
                self._breach_counted_for_turn = None
                self.filler_latency_s = None
                self.last_filler_text = None
                self.last_filler_reason = None
            entry = self.pool.pick(now_s=now_s, personality_gain=personality_gain)
            if entry is None:
                return None
            # Claim the fire slot before notify so a racing watchdog cannot also fire.
            self._filler_fired = True
            self.fillers_fired += 1
            self.last_filler_text = entry.text
            self.last_filler_reason = reason
            latency = float(now_s) - float(self._turn_started_s)
            self.pool.notify_spoken(entry, now_s=now_s)
            return FillerFire(entry=entry, reason=reason, latency_s=latency)

    def poll_watchdog(
        self,
        *,
        now_s: float,
        personality_gain: float = 1.0,
    ) -> FillerFire | None:
        with self._lock:
            if self._turn_started_s is None or self._filler_fired:
                return None
            if self._first_token_s is not None:
                return None
            elapsed = float(now_s) - float(self._turn_started_s)
            if elapsed + 1e-12 < self.watchdog_s:
                return None
        # Re-enter via predictive_fire so the claim stays under one code path.
        return self.predictive_fire(
            now_s=now_s,
            personality_gain=personality_gain,
            reason="watchdog",
        )

    def poll_ceiling_breach(self, *, now_s: float) -> bool:
        """Return True once if neither answer nor filler was audible in time."""

        with self._lock:
            if self._turn_started_s is None:
                return False
            elapsed = float(now_s) - float(self._turn_started_s)
            if elapsed + 1e-12 < self.ceiling_s:
                return False
            answered = self._first_token_s is not None
            filled = self._filler_audible_s is not None
            if answered or filled:
                return False
            if self._breach_counted_for_turn is self._turn_started_s:
                return False
            self._breach_counted_for_turn = self._turn_started_s
            self.response_ceiling_breaches += 1
            return True

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return {
                "watchdog_s": self.watchdog_s,
                "ceiling_s": self.ceiling_s,
                "filler_latency_s": self.filler_latency_s,
                "response_ceiling_breaches": self.response_ceiling_breaches,
                "fillers_fired": self.fillers_fired,
                "last_filler_text": self.last_filler_text,
                "last_filler_reason": self.last_filler_reason,
                "awaiting_clause_boundary": self._awaiting_clause_boundary,
                "filler_fired_this_turn": self._filler_fired,
                "first_token_seen": self._first_token_s is not None,
            }


__all__ = ["FillerFire", "FillerPolicy"]
