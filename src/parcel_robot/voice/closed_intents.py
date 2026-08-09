"""Closed companion intent enum (K6 / B-voice B1).

Only this reviewed set may map to executive / CommandArbiter caps. Positive
motion still requires PlanSketch → PlanIR admission (except emergency stop).
"""

from __future__ import annotations

import re
from enum import Enum

CLOSED_INTENT_NAMES = frozenset(
    {"pause", "resume", "faster", "slower", "stop", "come", "goal-amend"}
)


class ClosedIntent(str, Enum):
    PAUSE = "pause"
    RESUME = "resume"
    FASTER = "faster"
    SLOWER = "slower"
    STOP = "stop"
    COME = "come"
    GOAL_AMEND = "goal-amend"


_PHRASES: tuple[tuple[ClosedIntent, frozenset[str]], ...] = (
    (ClosedIntent.STOP, frozenset({"stop", "stop now", "emergency stop", "halt"})),
    (ClosedIntent.PAUSE, frozenset({"pause", "pause that", "hold on", "freeze"})),
    (ClosedIntent.RESUME, frozenset({"resume", "continue", "keep going", "carry on"})),
    (
        ClosedIntent.FASTER,
        frozenset({"faster", "speed up", "go faster", "a bit faster"}),
    ),
    (
        ClosedIntent.SLOWER,
        frozenset({"slower", "slow down", "go slower", "a bit slower"}),
    ),
    (
        ClosedIntent.COME,
        frozenset({"come", "come here", "come to me", "come over", "here boy"}),
    ),
)

_GOAL_AMEND = re.compile(
    r"^(?:actually|instead|no[, ]|change\s+(?:that|course)|correction\b|rather\b|"
    r"not\s+that\s+one|the\s+other\b)"
)


def closed_intent_phrases(intent: ClosedIntent) -> frozenset[str]:
    """Exact phrase set for one closed intent (empty for ``GOAL_AMEND``).

    Exported so the agent's emergency-stop fast path and the router's stop
    grammar read the SAME set this parser matches, instead of keeping their own
    copies. They did keep their own copies, and the copies disagreed: "halt"
    parsed as ``STOP`` here while ``EMERGENCY_STOP_PHRASES`` did not contain it,
    so `handle_text("halt")` was recognized as a stop and then stopped nothing
    (U33 — measured 2026-08-07).

    ``GOAL_AMEND`` returns the empty set because it is a regex, not a phrase
    list; callers that need it must use :func:`parse_closed_intent`.
    """

    if not isinstance(intent, ClosedIntent):
        raise TypeError("intent must be ClosedIntent")
    for candidate, phrases in _PHRASES:
        if candidate is intent:
            return phrases
    return frozenset()


def parse_closed_intent(transcript: str) -> ClosedIntent | None:
    """Map a normalized final transcript to one closed intent, or None.

    Partial / non-final ASR must not call this for positive motion; callers
    keep emergency stop on the existing fast path.
    """

    if not isinstance(transcript, str):
        raise TypeError("transcript must be a string")
    clean = " ".join(transcript.strip().lower().split())
    if not clean:
        return None
    for intent, phrases in _PHRASES:
        if clean in phrases:
            return intent
    if _GOAL_AMEND.search(clean):
        return ClosedIntent.GOAL_AMEND
    return None


def require_closed_intent(name: str) -> ClosedIntent:
    if name not in CLOSED_INTENT_NAMES:
        raise ValueError(f"closed intent is not allowed: {name!r}")
    return ClosedIntent(name)


__all__ = [
    "CLOSED_INTENT_NAMES",
    "ClosedIntent",
    "closed_intent_phrases",
    "parse_closed_intent",
    "require_closed_intent",
]
