"""The restricted transcript ingress for the Realtime lane (card R1, task_7).

THE DEFECT THIS MODULE EXISTS TO PREVENT
----------------------------------------
Two of them, both named by the adversarial review of the 2026-08-16 design.

**Punctuation.** A hosted transcriber writes ``"Stop."``. Every phrase set in
this repo is an EXACT-MATCH set of unpunctuated strings — the emergency latch
(``closed_intents.py:28``), the router's ``_FOLLOW`` / ``_HOLD`` sets, the
closed-intent parser. ``"stop."`` matches none of them. Without one
normalization step the entire deterministic story degrades to nothing on every
hosted utterance, silently, with no error anywhere. That is why
:func:`normalize` runs before any comparison and why the regression test feeds
punctuated variants of every phrase through this module.

**Scope.** ``submit_voice_text`` is not a thin latch; it is the front door to
the whole local agent. A hosted utterance routed there would run the local
planner and the local conversation model over audio the hosted model is already
answering (two replies), execute grammar-matched commands twice, and — through
``DuplexVoiceSession.submit_text``'s unconditional barge-in — interrupt-latch
the speaker sink and mute the hosted reply entirely. So this module answers ONE
question, ``what is the smallest safe local reading of this text?``, and the
answer space is closed: emergency, one closed intent, follow, hold, or nothing.

SINGLE-SOURCED GRAMMARS
-----------------------
Nothing here contains a copy of a phrase. ``EMERGENCY_STOP_PHRASES`` comes from
``closed_intent_phrases(ClosedIntent.STOP)``, closed intents from
``parse_closed_intent``, and follow/hold are re-exported from the router's own
module objects. U33 was exactly this class of bug — three copies of the stop
grammar, one of them missing ``"halt"`` — and it cost a stop that stopped
nothing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from parcel_robot.brain import router as _router
from parcel_robot.voice.closed_intents import (
    ClosedIntent,
    closed_intent_phrases,
    parse_closed_intent,
)

#: Terminal punctuation a hosted transcriber adds and the repo's phrase sets do
#: not contain. Stripped from BOTH ends before matching; the original text is
#: kept verbatim for the ledger.
_TERMINAL_PUNCTUATION = ".,!?…"
_PUNCTUATION_EDGES = re.compile(
    rf"^[{re.escape(_TERMINAL_PUNCTUATION)}\s]+|[{re.escape(_TERMINAL_PUNCTUATION)}\s]+$"
)

#: The one stop grammar, read from the closed-intent parser exactly as
#: ``agent.py`` and ``brain/router.py`` read it.
EMERGENCY_STOP_PHRASES = closed_intent_phrases(ClosedIntent.STOP)

KIND_EMERGENCY = "emergency"
KIND_CLOSED_INTENT = "closed_intent"
KIND_FOLLOW = "follow"
KIND_HOLD = "hold"
KIND_NONE = "none"

#: Everything a hosted utterance is allowed to mean locally.
INGRESS_KINDS = frozenset({KIND_EMERGENCY, KIND_CLOSED_INTENT, KIND_FOLLOW, KIND_HOLD, KIND_NONE})

#: Refused deliberately: GOAL_AMEND ("actually, the other bench") is a request
#: to re-plan, and re-planning is the deliberative planner — precisely what
#: this ingress may never reach. It reads as chit-chat here and the hosted model
#: answers it conversationally, which is honest: nothing local happened.
_EXCLUDED_CLOSED_INTENTS = frozenset({ClosedIntent.GOAL_AMEND})


def follow_phrases() -> frozenset[str]:
    """The router's ``_FOLLOW`` set, read live — never copied.

    Read through the module object rather than imported by value so that a
    future edit to ``brain/router.py`` reaches this lane on the same import,
    and a drifted copy is impossible by construction.
    """

    return frozenset(_router._FOLLOW)


def hold_phrases() -> frozenset[str]:
    """The router's ``_HOLD`` set, read live — never copied."""

    return frozenset(_router._HOLD)


def normalize(text: str) -> str:
    """Collapse whitespace and strip terminal punctuation. Case preserved.

    Case is preserved because the ledger stores what was said; matching folds
    case separately in :func:`fold`. Interior punctuation is untouched — this
    is a normalizer, not a rewriter.
    """

    if not isinstance(text, str):
        raise TypeError("realtime transcript must be a string")
    collapsed = " ".join(text.split())
    return _PUNCTUATION_EDGES.sub("", collapsed)


def fold(text: str) -> str:
    """The exact string the repo's phrase sets are compared against."""

    return normalize(text).lower()


@dataclass(frozen=True)
class IngressScan:
    """What the local side reads in one hosted utterance, and nothing more."""

    kind: str
    original: str
    normalized: str
    intent: ClosedIntent | None = None

    @property
    def actionable(self) -> bool:
        return self.kind != KIND_NONE

    @property
    def name(self) -> str:
        if self.intent is not None:
            return self.intent.value
        return self.kind

    def as_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "name": self.name,
            "normalized": self.normalized,
            "intent": None if self.intent is None else self.intent.value,
        }


def scan(text: str) -> IngressScan:
    """Classify a hosted transcript into the closed local action space.

    Order mirrors ``submit_voice_text`` / ``VoiceAgent._handle_text``: emergency
    first and unconditionally, then closed intents, then follow, then hold.
    Anything else is ``KIND_NONE`` — the hosted model answers it and the robot
    does not move.
    """

    original = text if isinstance(text, str) else str(text)
    clean = normalize(original)
    folded = clean.lower()
    if not folded:
        return IngressScan(kind=KIND_NONE, original=original, normalized=clean)
    if folded in EMERGENCY_STOP_PHRASES:
        return IngressScan(
            kind=KIND_EMERGENCY,
            original=original,
            normalized=clean,
            intent=ClosedIntent.STOP,
        )
    intent = parse_closed_intent(folded)
    if intent is not None and intent not in _EXCLUDED_CLOSED_INTENTS:
        return IngressScan(
            kind=KIND_CLOSED_INTENT,
            original=original,
            normalized=clean,
            intent=intent,
        )
    if folded in follow_phrases():
        return IngressScan(kind=KIND_FOLLOW, original=original, normalized=clean)
    if folded in hold_phrases():
        return IngressScan(kind=KIND_HOLD, original=original, normalized=clean)
    return IngressScan(kind=KIND_NONE, original=original, normalized=clean)


@dataclass(frozen=True)
class RealtimeTranscriptOutcome:
    """What the runtime did about one hosted utterance.

    Returned to the lane so it can post a factual item back to the model:
    the hosted agent NARRATES what the robot did; it never decides it.
    """

    kind: str
    name: str
    transcript: str
    reply: str
    executed: bool
    item_id: str | None = None
    session_id: str | None = None
    error: str = ""

    def as_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "name": self.name,
            "transcript": self.transcript,
            "reply": self.reply,
            "executed": self.executed,
            "item_id": self.item_id,
            "session_id": self.session_id,
            "error": self.error,
        }

    def narration(self) -> str:
        """One line the model is told, in plain words, after the fact."""

        if self.error:
            return f"[robot] tried to {self.name} and could not: {self.error}"
        if not self.executed:
            return ""
        return f"[robot] executed the local command {self.name!r}: {self.reply}"


__all__ = [
    "EMERGENCY_STOP_PHRASES",
    "INGRESS_KINDS",
    "KIND_CLOSED_INTENT",
    "KIND_EMERGENCY",
    "KIND_FOLLOW",
    "KIND_HOLD",
    "KIND_NONE",
    "IngressScan",
    "RealtimeTranscriptOutcome",
    "fold",
    "follow_phrases",
    "hold_phrases",
    "normalize",
    "scan",
]
