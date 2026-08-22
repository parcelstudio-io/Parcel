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

One phrase is DEFINED here rather than read from elsewhere: the owner's spoken
emergency phrase (card R9, ``SPOKEN_EMERGENCY_PHRASE``). That is not a copy —
it is the only definition of it anywhere in the repo, and it is exported so the
next surface that needs it reads this one instead of growing a fifth stop
grammar. See the block above it for why it does not live in
``closed_intents.py``.
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

#: The one TYPED stop grammar, read from the closed-intent parser exactly as
#: ``agent.py`` and ``brain/router.py`` read it. Matched as a WHOLE normalized
#: utterance and nothing else, which is what keeps "let's stop by the store"
#: from stopping a robot dog.
EMERGENCY_STOP_PHRASES = closed_intent_phrases(ClosedIntent.STOP)

# ---------------------------------------------------------------------------
# Card R9 — THE SPOKEN EMERGENCY PHRASE
#
# Owner policy ruling, 2026-08-19, verbatim: "Space bar should be the e-stop.
# In voice command it should be 'Die Stop'."
#
# WHY IT IS NOT IN ``closed_intents.py``. That set is the grammar the local
# agent, the router and this ingress all share for TYPED text, where exact
# matching is right because a text box delivers exactly what was typed. This
# phrase is for a TRANSCRIPT, and it is matched by a different rule (below);
# putting a fuzzy rule inside ``parse_closed_intent``'s exact-set contract
# would change what every other caller of that parser means.
#
# WHY THE RULE IS DIFFERENT IN KIND. R7 measured this exact latch failing live
# three times (scrum/20260818/task_4/R7_STATUS.md, open risk 1): a spoken
# "Stop." came back from the hosted transcriber as "Soap" and as "Top", and a
# correctly transcribed "Stop. Stop right now, please stop." matched nothing at
# all because the WHOLE utterance was not one of the four exact phrases. So the
# spoken phrase is matched:
#
#   * with the near-homophones of "die" an ASR actually returns;
#   * with any punctuation, or none, between the two words — "Die stop",
#     "Die, stop!", "die-stop", "Diestop" are the same instruction;
#   * ANYWHERE inside the utterance, because a frightened owner says
#     "Die stop! Die stop!", not a tidy two-word sentence.
#
# THE ASYMMETRY IS THE OWNER'S. A false latch is a stopped dog that the panel
# releases in one click; a missed latch is the failure that matters. What is
# deliberately NOT relaxed is the word "stop" on its own: it is still only ever
# matched as a whole normalized utterance against ``EMERGENCY_STOP_PHRASES``,
# so ordinary sentences that merely contain "stop" latch nothing.

#: The phrase, lowercase, exactly as the owner said it. Exported so no second
#: copy of it is ever written.
SPOKEN_EMERGENCY_PHRASE = "die stop"

#: The transcription variants of "die" this latch accepts. Kept deliberately
#: short: each entry widens the mouth of the latch, and these four are all
#: low-frequency English tokens, so "<variant> stop" stays a bigram that
#: essentially never occurs by accident. A HIGH-frequency homophone ("day") is
#: excluded for exactly that reason — "call it a day, stop the recording" is a
#: sentence people say, and admitting it would trade a rare false latch for a
#: routine one.
SPOKEN_EMERGENCY_VARIANTS = ("die", "dye", "dai", "di")

#: Up to four non-word characters may sit between the two words, which covers
#: every separator a transcriber writes ("die stop", "die, stop", "die-stop",
#: "die... stop") and zero of them ("diestop"). The trailing ``\b`` is what
#: stops "dystopia"-shaped words from ever reaching this branch.
_SPOKEN_EMERGENCY = re.compile(
    rf"\b(?:{'|'.join(SPOKEN_EMERGENCY_VARIANTS)})\W{{0,4}}stop\b"
)

KIND_EMERGENCY = "emergency"
KIND_CLOSED_INTENT = "closed_intent"
KIND_FOLLOW = "follow"
KIND_HOLD = "hold"
KIND_NONE = "none"

# ---------------------------------------------------------------------------
# Card ROAM-1 — "GO EXPLORE" AS A CLOSED INTENT
#
# Two new kinds, APPENDED. Nothing above this block moves and no existing
# phrase set is touched: the classification ladder in ``scan`` keeps its exact
# order (emergency, closed intents, follow, hold) and these are read after it,
# so "stop" is still only ever an emergency and "come here" is still only ever
# COME.
#
# WHY THE PHRASES LIVE HERE AND NOT IN ``voice/closed_intents.py``. That module
# is the grammar the local agent, the router and this ingress all share, and
# every one of its members maps to an executive/CommandArbiter cap that already
# exists (pause, resume, faster, slower, stop, come). Roam has no such cap: it
# is a RUNTIME BEHAVIOR the runtime owns, reached through
# ``RobotRuntime.start_roam`` the way follow is reached through
# ``set_behavior``. Follow and hold are already classified here for exactly
# that reason — they are behaviors, not caps — and roam joins them rather than
# widening what ``parse_closed_intent`` means for its other four callers.
#
# THE STOP SIDE IS DELIBERATELY WIDER THAN THE START SIDE. Starting a roam is a
# positive motion request and gets an exact whole-utterance match. Stopping one
# is the owner taking the body back, so "stop roaming", "stop exploring",
# "stop wandering" and "come back" all land. What is NOT widened is the bare
# word "stop": it is matched above, by ``EMERGENCY_STOP_PHRASES``, and it
# latches the e-stop — which is a strictly stronger answer to the same request.
KIND_ROAM = "roam"
KIND_ROAM_STOP = "roam_stop"

#: Start phrases. Exact, whole-utterance, unpunctuated — the same contract every
#: other phrase set in this repo has, matched after :func:`normalize`.
ROAM_START_PHRASES = frozenset(
    {
        "roam",
        "go roam",
        "go explore",
        "explore",
        "go exploring",
        "go and explore",
        "have a wander",
        "go for a wander",
        "wander around",
        "go look around",
        "look around",
        "go have a look around",
    }
)

#: Stop phrases. See the block above for why this set is the wider of the two.
ROAM_STOP_PHRASES = frozenset(
    {
        "stop roaming",
        "stop exploring",
        "stop wandering",
        "stop looking around",
        "stop roaming around",
        "come back",
        "that's enough exploring",
        "thats enough exploring",
        "done exploring",
    }
)

#: Everything a hosted utterance is allowed to mean locally. The two roam kinds
#: are appended; the five above them are unchanged.
INGRESS_KINDS = frozenset(
    {
        KIND_EMERGENCY,
        KIND_CLOSED_INTENT,
        KIND_FOLLOW,
        KIND_HOLD,
        KIND_ROAM,
        KIND_ROAM_STOP,
        KIND_NONE,
    }
)

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


def _spoken_emergency_in(folded: str) -> bool:
    """Does this ALREADY-folded text carry the owner's spoken e-stop phrase?

    Private because it trusts its input; :func:`matches_spoken_emergency` is the
    door for anyone who has not folded yet.
    """

    return _SPOKEN_EMERGENCY.search(folded) is not None


def matches_spoken_emergency(text: str) -> bool:
    """Public predicate for the card R9 spoken emergency phrase.

    Exported so that a future surface — a hardware hotword, a second panel, a
    replay harness — reads THIS definition instead of writing the fifth copy of
    a stop grammar in this repo. U33 is what the fourth copy cost.
    """

    return _spoken_emergency_in(fold(text))


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

    Two emergency readings, in one branch and therefore at the same priority:
    the exact TYPED phrase set, and the owner's spoken phrase (card R9). Both
    are reached before any other classification and before the caller has asked
    the cloud anything.
    """

    original = text if isinstance(text, str) else str(text)
    clean = normalize(original)
    folded = clean.lower()
    if not folded:
        return IngressScan(kind=KIND_NONE, original=original, normalized=clean)
    if folded in EMERGENCY_STOP_PHRASES or _spoken_emergency_in(folded):
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
    # Card ROAM-1. APPENDED, and appended for a reason that is part of the
    # contract: every branch above this line either latches the body or hands it
    # to a behavior the owner named explicitly, and a roam must never be able to
    # shadow one of them. Stop is read before start so an utterance that somehow
    # matched both would end a roam rather than begin one.
    if folded in ROAM_STOP_PHRASES:
        return IngressScan(kind=KIND_ROAM_STOP, original=original, normalized=clean)
    if folded in ROAM_START_PHRASES:
        return IngressScan(kind=KIND_ROAM, original=original, normalized=clean)
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
    "KIND_ROAM",
    "KIND_ROAM_STOP",
    "ROAM_START_PHRASES",
    "ROAM_STOP_PHRASES",
    "SPOKEN_EMERGENCY_PHRASE",
    "SPOKEN_EMERGENCY_VARIANTS",
    "IngressScan",
    "RealtimeTranscriptOutcome",
    "fold",
    "follow_phrases",
    "hold_phrases",
    "matches_spoken_emergency",
    "normalize",
    "scan",
]
