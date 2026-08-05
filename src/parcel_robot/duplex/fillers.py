"""Deterministic filler variation pool (pure; numpy/stdlib only)."""

from __future__ import annotations

import math
import random
from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class FillerEntry:
    text: str
    gesture: str | None = None  # e.g. "<thinking_pose>"
    min_gap_s: float = 20.0  # no-repeat window for this entry

    def __post_init__(self) -> None:
        if not str(self.text).strip():
            raise ValueError("filler text must be non-empty")
        if not math.isfinite(float(self.min_gap_s)) or float(self.min_gap_s) < 0.0:
            raise ValueError("min_gap_s must be finite and non-negative")


class FillerPool:
    def __init__(
        self,
        entries: Iterable[FillerEntry],
        *,
        rng_seed: int | None,
    ) -> None:
        self._entries = tuple(entries)
        if any(not isinstance(entry, FillerEntry) for entry in self._entries):
            raise TypeError("entries must be FillerEntry instances")
        self._rng = random.Random(rng_seed)
        self._last_spoken_s: dict[str, float] = {}
        self._last_pick_text: str | None = None

    @property
    def size(self) -> int:
        return len(self._entries)

    def texts(self) -> tuple[str, ...]:
        return tuple(entry.text for entry in self._entries)

    def pick(
        self,
        *,
        now_s: float,
        personality_gain: float = 1.0,
    ) -> FillerEntry | None:
        now = float(now_s)
        if not math.isfinite(now):
            raise ValueError("now_s must be finite")
        gain = float(personality_gain)
        if not math.isfinite(gain) or gain < 0.0:
            raise ValueError("personality_gain must be finite and non-negative")
        if not self._entries:
            return None

        available: list[FillerEntry] = []
        for entry in self._entries:
            last = self._last_spoken_s.get(entry.text)
            if last is not None and (now - last) < entry.min_gap_s:
                continue
            if self._last_pick_text is not None and entry.text == self._last_pick_text:
                # Consecutive picks never repeat even inside the gap window.
                continue
            available.append(entry)

        if not available:
            # Never go mute past the 2 s ceiling because of no-repeat:
            # fall back to the least-recently-used entry.
            return min(
                self._entries,
                key=lambda entry: self._last_spoken_s.get(entry.text, float("-inf")),
            )

        if gain <= 0.0:
            return available[0]
        # Soft personality bias: higher gain prefers earlier (canonical) entries.
        weights = [max(1e-6, (len(available) - index) ** gain) for index in range(len(available))]
        return self._rng.choices(available, weights=weights, k=1)[0]

    def notify_spoken(self, entry: FillerEntry, *, now_s: float) -> None:
        now = float(now_s)
        if not math.isfinite(now):
            raise ValueError("now_s must be finite")
        if not isinstance(entry, FillerEntry):
            raise TypeError("entry must be a FillerEntry")
        self._last_spoken_s[entry.text] = now
        self._last_pick_text = entry.text

    @classmethod
    def default(cls, *, rng_seed: int | None = None) -> FillerPool:
        entries = (
            FillerEntry("Hmm, let me think…", gesture="<thinking_pose>"),
            FillerEntry("Just a sec while I check that…", gesture="<thinking_pose>"),
            FillerEntry("Give me a moment…", gesture="<thinking_pose>"),
            FillerEntry("Good question — checking…", gesture="<thinking_pose>"),
            FillerEntry("One second — looking into it…", gesture="<thinking_pose>"),
            FillerEntry("Hang on, working on that…", gesture="<thinking_pose>"),
            FillerEntry("Alright, let me see…", gesture="<thinking_pose>"),
        )
        return cls(entries, rng_seed=rng_seed)


__all__ = ["FillerEntry", "FillerPool"]
