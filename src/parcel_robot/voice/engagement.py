"""Ambient engagement triage: what does a heard sentence actually deserve?

Card ENG-1 (``scrum/20260823/TRANCHE2_MIND_DESIGN_FABLE.md``, axis A), built
here because H1 needs it to measure the cost ladder.

THE PROBLEM
-----------
Today the hosted lane answers everything it hears. With server VAD and one
always-open session, a television in the next room is a conversation partner:
every detected speech segment becomes a committed turn, every committed turn
becomes a billed response, and the dog talks over the news. That is a money
problem (H1) and a personality problem (a dog that answers the television is
not listening to you).

The fix is a rung below "answer" that has never existed: the dog may HEAR
something, remember it, and say nothing. Three tiers, and only the first one
opens a mouth:

``answer``
    Addressed to the dog and asking for something. Goes to a lane.
``acknowledge``
    Addressed to the dog, but asking for nothing — a greeting, praise, a
    farewell. Deserves a look and at most a short sound; it does not deserve a
    hosted response and it never deserves a paragraph.
``hear_only``
    Not addressed to the dog. REMEMBERED (the memory ledger), possibly offered
    to the curiosity door as a state event, and never spoken to. This rung is
    the whole card.

WHY THIS MODULE IS PURE AND KNOWS NOTHING
-----------------------------------------
It takes a committed transcript and returns a verdict. It does not own a
socket, a model, a ledger or a clock, and nothing here can speak. The call site
is the voice pipeline; the runtime is not touched. That is deliberate: an
engagement tier that could act would be a second command path, and the repo has
one of those already.

Grammars are single-sourced, per the ingress module's rule: the closed-intent
phrases come from ``voice/closed_intents.py`` and normalization from
``realtime/ingress.py``. Nothing here is a copy of a phrase that lives
somewhere else.

THE SAFETY DIRECTION
--------------------
Every uncertain case resolves UPWARD, toward answering. A sentence wrongly
called ``hear_only`` is a dog that ignored its owner; a sentence wrongly called
``answer`` costs a fraction of a cent. Those are not symmetric, and the code
takes the cheap side of the asymmetry. The one exception is the emergency
grammar, which is not a tier decision at all: it is answered before any of this
runs, and :func:`triage` returns ``answer`` for it unconditionally so that a
future caller which forgets the latch still cannot swallow a stop.

ONE SENTENCE IS NOT ENOUGH CONTEXT, AND THE MEASUREMENT SAYS SO
---------------------------------------------------------------
:func:`triage` is the card's function: one committed transcript in, one tier
out, no state. Measured on the 174 owner turns of ``realtime_convo_v1`` — all
of which the owner said TO the dog — it calls 84 of them ``hear_only``, because
mid-conversation replies ("yes that one", "the one by the petrol station") carry
no second-person marker at all. A dog that ignores half of what its owner says
is worse than one that answers the television.

So the mechanism needs a second, still-pure input: how long ago the dog was last
addressed. :func:`triage_in_exchange` takes it and promotes ``hear_only`` back to
``answer`` inside an open exchange. It owns no clock — the caller passes the
elapsed seconds — so this module stays a function of its arguments. Both
functions are kept: the context-free one is what the tier grammar can do alone,
and the difference between them is the measurement.

ESCALATION IS A SECOND, SEPARATE QUESTION
-----------------------------------------
"Should the dog answer this?" and "can the LOCAL model answer this?" are
different questions with different failure modes, so they are different
functions. :func:`escalation_for` types an utterance the local arm should not
attempt (``needs_tool`` / ``needs_memory`` / ``long_form``), and
:func:`escalation_after` types a local answer that came back hedging
(``uncertainty``). Both are needed: the first is free and catches the classes
we can name, the second catches the ones we cannot.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from parcel_robot.realtime.ingress import matches_spoken_emergency, normalize
from parcel_robot.voice.closed_intents import parse_closed_intent

# ------------------------------------------------------------------- tiers
#: The dog opens its mouth and a lane produces a reply.
TIER_ANSWER = "answer"
#: The dog reacts — a look, a tail, at most a short sound. No lane, no tokens.
TIER_ACKNOWLEDGE = "acknowledge"
#: The dog listens and remembers. Nothing is said. The point of the card.
TIER_HEAR_ONLY = "hear_only"

TIERS = (TIER_ANSWER, TIER_ACKNOWLEDGE, TIER_HEAR_ONLY)

# -------------------------------------------------------------- escalations
ESCALATE_NONE = ""
#: The local answer hedged or refused. Only :func:`escalation_after` sets it.
ESCALATE_UNCERTAINTY = "uncertainty"
#: The turn asks the body to do something. The local arm has no tool broker.
ESCALATE_NEEDS_TOOL = "needs_tool"
#: The turn refers to something only the owner model or the map knows.
ESCALATE_NEEDS_MEMORY = "needs_memory"
#: The turn asks for a paragraph, not a sentence.
ESCALATE_LONG_FORM = "long_form"

ESCALATIONS = (
    ESCALATE_UNCERTAINTY,
    ESCALATE_NEEDS_TOOL,
    ESCALATE_NEEDS_MEMORY,
    ESCALATE_LONG_FORM,
)

# ------------------------------------------------------------------ grammars
#: Fewer real words than this and there is nothing to answer. Two, not one:
#: "yes" alone is an acknowledgement, and a one-word fragment out of a
#: television is the commonest thing a VAD hands over.
MIN_ANSWERABLE_WORDS = 2

#: More words than this in one turn is a request for a paragraph.
LONG_FORM_WORDS = 25

#: Bare social openings and closings. Addressed to the dog, asking nothing.
_SOCIAL = frozenset(
    {
        "hi",
        "hey",
        "hello",
        "morning",
        "good morning",
        "good evening",
        "good night",
        "goodnight",
        "night",
        "bye",
        "goodbye",
        "see you",
        "see you later",
        "thanks",
        "thank you",
        "thanks buddy",
        "good boy",
        "good girl",
        "good dog",
        "well done",
        "nice one",
        "love you",
        "yes",
        "yeah",
        "no",
        "nope",
        "ok",
        "okay",
        "sure",
        "right",
        "cool",
        "nice",
    }
)

#: Second-person address. A sentence containing one of these is talking to
#: somebody present, and the dog is the only listener that answers.
_ADDRESS_WORDS = frozenset({"you", "your", "you're", "youre", "yours", "yourself", "we", "us"})

#: Question openers. A wh-word or an auxiliary in first position is a question
#: even when the transcriber dropped the question mark, which it usually does.
_QUESTION_OPENERS = frozenset(
    {
        "what",
        "where",
        "when",
        "who",
        "why",
        "how",
        "which",
        "whose",
        "can",
        "could",
        "would",
        "will",
        "should",
        "do",
        "does",
        "did",
        "is",
        "are",
        "was",
        "were",
        "have",
        "has",
        "am",
        "shall",
        "may",
    }
)

#: Imperatives aimed at a body. Present tense, first word, no subject.
_IMPERATIVE_VERBS = frozenset(
    {
        "go",
        "come",
        "stop",
        "wait",
        "stay",
        "sit",
        "look",
        "watch",
        "follow",
        "find",
        "fetch",
        "take",
        "bring",
        "lead",
        "walk",
        "run",
        "head",
        "turn",
        "move",
        "show",
        "tell",
        "say",
        "check",
        "remember",
        "forget",
        "call",
        "play",
        "wave",
        "spin",
        "circle",
        "let's",
        "lets",
    }
)

#: Asking the body to act. These are the turns a local text model cannot honour
#: on its own: there is no tool broker behind it and no admission gate.
_TOOL_MARKERS = (
    "go to",
    "go back",
    "take me",
    "walk to",
    "walk with",
    "head over",
    "head to",
    "get to",
    "lead me",
    "navigate",
    "follow me",
    "come here",
    "come with",
    "let's go",
    "lets go",
    "can you see",
    "can you look",
    "look at",
    "have a look",
    "check the",
    "check on",
    "wait by",
    "wait at",
    "wait for",
    "stay close",
    "circle",
    "wave",
    "sit down",
    "lie down",
    "play dead",
    "shake",
)

#: Asking about something only a store knows: the owner model, the episodic
#: log, the learned map. A local model answering these invents them.
_MEMORY_MARKERS = (
    "remember",
    "you said",
    "i said",
    "i told you",
    "last time",
    "yesterday",
    "this morning",
    "earlier",
    "we always",
    "we usually",
    "the one we",
    "my name",
    "what's my",
    "whats my",
    "do you know where",
    "where is",
    "where's",
    "wheres",
    "where did",
    "have you seen",
    "did we",
    "did i",
)

#: Asking for a paragraph rather than a sentence.
_LONG_FORM_MARKERS = (
    "tell me about",
    "explain",
    "why do",
    "why does",
    "why is",
    "what do you think about",
    "how does",
    "how do you",
    "talk to me about",
    "tell me a story",
)

#: A local answer that says this has not answered. Hedges and refusals — the
#: shapes a small model produces when it is out of its depth.
_HEDGES = (
    "i'm not sure",
    "im not sure",
    "i am not sure",
    "i don't know",
    "i dont know",
    "i do not know",
    "i can't tell",
    "i cant tell",
    "i cannot tell",
    "i'm unable",
    "im unable",
    "i can't help",
    "i cant help",
    "i don't have",
    "i dont have",
    "no idea",
    "as an ai",
    "i'm just",
    "im just",
)

#: Openers that carry no meaning and hide the word that does. "hey, wait by
#: the door" is an imperative wearing a hat, and testing its FIRST word finds
#: "hey". Skipped before the first-word tests, never before the whole-sentence
#: ones (a bare "hey" is still an acknowledgement).
_VOCATIVES = frozenset({"hey", "hi", "hello", "so", "well", "listen", "ok", "okay", "right",
                        "oh", "um", "uh", "erm", "yeah", "yes", "no", "actually", "alright"})

#: Contractions the word regex keeps whole. Expanded for matching only.
_CONTRACTION = re.compile(r"'(s|re|ve|ll|d|m)$")

#: How long an exchange stays open after the dog was last addressed. Long
#: enough to carry a normal back-and-forth including a pause to think; short
#: enough that leaving the room ends it. Not tuned against any criterion.
EXCHANGE_WINDOW_S = 45.0

_WORD = re.compile(r"[a-z0-9']+")


@dataclass(frozen=True)
class EngagementVerdict:
    """One heard sentence, triaged. Pure data; nothing here can act.

    ``escalation`` is empty for every tier but ``answer`` — a sentence the dog
    is not going to answer cannot need a better model to answer it, and letting
    the field carry a value there would invite a caller to escalate a turn the
    triage just decided to stay quiet about.
    """

    text: str
    tier: str
    reason: str
    addressed: bool
    escalation: str = ESCALATE_NONE
    #: hear-only is REMEMBERED. The card's word, and the field a caller writes
    #: the memory ledger from. Acknowledged and answered turns are remembered
    #: by the paths that already remember them.
    remember: bool = False

    @property
    def speaks(self) -> bool:
        """Does this verdict open a lane? Only ``answer`` does."""

        return self.tier == TIER_ANSWER

    @property
    def escalates(self) -> bool:
        return bool(self.escalation)

    def as_dict(self) -> dict[str, object]:
        return {
            "text": self.text,
            "tier": self.tier,
            "reason": self.reason,
            "addressed": self.addressed,
            "escalation": self.escalation,
            "remember": self.remember,
            "speaks": self.speaks,
        }


def _words(folded: str) -> list[str]:
    return _WORD.findall(folded)


def _stems(words: list[str]) -> list[str]:
    """Words with their contraction tails removed: ``we're`` reads as ``we``.

    Address and question detection both key on function words that English
    almost always contracts in speech, and a transcriber writes the contraction.
    Without this, "we're taking Mochi to the vet" contains no address word and
    "there's someone at the door" opens with no question word.
    """

    return [_CONTRACTION.sub("", word) for word in words]


def _after_vocative(words: list[str]) -> list[str]:
    """The sentence with its leading hellos and hesitations removed."""

    index = 0
    while index < len(words) - 1 and words[index] in _VOCATIVES:
        index += 1
    return words[index:]


def _folded(text: str) -> str:
    """Normalized, lowercased, punctuation-stripped — the matching surface."""

    return normalize(str(text)).lower()


def triage(text: str) -> EngagementVerdict:
    """Which tier does this committed transcript deserve? Pure; deterministic.

    The order of the rules IS the policy, and it resolves upward at every step:
    emergency, then closed intent, then "is it a request", then "is it social",
    then hear-only. Only the last rule can produce silence.
    """

    raw = str(text)
    folded = _folded(raw)
    words = _words(folded)

    if matches_spoken_emergency(raw):
        # Not really a tier decision. The latch answered this before we ran;
        # returning anything else here would let a forgetful caller lose a stop.
        return EngagementVerdict(raw, TIER_ANSWER, "spoken emergency", addressed=True)

    if not words:
        return EngagementVerdict(
            raw, TIER_HEAR_ONLY, "nothing was said", addressed=False, remember=False
        )

    if parse_closed_intent(raw) is not None:
        return EngagementVerdict(raw, TIER_ANSWER, "closed intent", addressed=True)

    if folded in _SOCIAL or (len(words) <= 3 and " ".join(words) in _SOCIAL):
        return EngagementVerdict(raw, TIER_ACKNOWLEDGE, "bare social phrase", addressed=True)

    if len(words) < MIN_ANSWERABLE_WORDS:
        # One word that is not a greeting and not an intent. A fragment.
        return EngagementVerdict(
            raw, TIER_HEAR_ONLY, "one-word fragment", addressed=False, remember=True
        )

    reason = _address_reason(folded, words)
    if reason:
        return EngagementVerdict(
            raw,
            TIER_ANSWER,
            reason,
            addressed=True,
            escalation=escalation_for(raw),
        )

    return EngagementVerdict(
        raw, TIER_HEAR_ONLY, "not addressed to the dog", addressed=False, remember=True
    )


def triage_in_exchange(
    text: str,
    *,
    seconds_since_addressed: float | None,
    window_s: float = EXCHANGE_WINDOW_S,
) -> EngagementVerdict:
    """:func:`triage`, plus the one thing a single sentence cannot carry.

    ``seconds_since_addressed`` is how long ago the dog was last spoken TO —
    ``None`` when it never has been, or when the last exchange has been closed
    by the caller. Inside the window, a sentence the grammar could not place is
    read as a continuation and answered; outside it, nothing changes.

    Only ``hear_only`` is promoted. An acknowledgement stays an acknowledgement
    inside an exchange ("thanks" mid-conversation is still not a question), and
    nothing is ever demoted: an open exchange cannot make the dog quieter.
    """

    verdict = triage(text)
    if verdict.tier != TIER_HEAR_ONLY:
        return verdict
    if seconds_since_addressed is None or seconds_since_addressed > float(window_s):
        return verdict
    if verdict.reason == "nothing was said":
        return verdict
    return EngagementVerdict(
        verdict.text,
        TIER_ANSWER,
        "continuation of an open exchange",
        addressed=True,
        escalation=escalation_for(verdict.text),
    )


def _is_addressed(folded: str, words: list[str]) -> bool:
    """Is this sentence talking to the listener, or in front of it?"""

    return _address_reason(folded, words) != ""


def _address_reason(folded: str, words: list[str]) -> str:
    """WHY it counts as addressed, or ``""`` when it does not. One rule set.

    Kept as one function returning the reason rather than a predicate plus a
    parallel explainer: two copies of this ladder would drift, and the reason is
    what a reader of the ledger needs.
    """

    stems = _stems(words)
    head = _after_vocative(words)
    # BOTH spellings of the first word are tested. The stem finds "we" inside
    # "we're"; the raw word finds "let's", which is an imperative whose stem
    # ("let") is not one. Stripping only would lose "let's go to the park".
    first = {head[0], _CONTRACTION.sub("", head[0])} if head else {""}
    if "?" in folded or first & _QUESTION_OPENERS:
        return "question"
    if first & _IMPERATIVE_VERBS:
        return "imperative"
    if any(word in _ADDRESS_WORDS for word in stems):
        return "second person address"
    # A sentence in the first person is the owner telling the dog something:
    # "I am hungry" is addressed; "he said he was hungry" is not.
    if first & {"i", "im"}:
        return "first person statement"
    return ""


def escalation_for(text: str) -> str:
    """Which typed escalation, if any, this utterance needs BEFORE it is tried.

    Empty means "the local arm may attempt it". The three classes here are the
    ones a local text model provably cannot do: it has no tool broker, no store,
    and no budget for a paragraph. Checked in cost order — tool first, because a
    tool turn is the one where a wrong local answer becomes a wrong action.
    """

    folded = _folded(text)
    if any(marker in folded for marker in _TOOL_MARKERS):
        return ESCALATE_NEEDS_TOOL
    if any(marker in folded for marker in _MEMORY_MARKERS):
        return ESCALATE_NEEDS_MEMORY
    if any(marker in folded for marker in _LONG_FORM_MARKERS):
        return ESCALATE_LONG_FORM
    if len(_words(folded)) > LONG_FORM_WORDS:
        return ESCALATE_LONG_FORM
    return ESCALATE_NONE


def escalation_after(answer: str, *, min_words: int = 4) -> str:
    """Did the local answer actually answer? ``uncertainty`` when it did not.

    The second rung of the ladder, and the one that cannot be written as a
    grammar over the QUESTION. A hedge is a model saying it is out of its depth
    in the only vocabulary it has; taking it at its word costs one hosted turn
    and saves the owner a non-answer.
    """

    folded = _folded(answer)
    if len(_words(folded)) < min_words:
        return ESCALATE_UNCERTAINTY
    if any(hedge in folded for hedge in _HEDGES):
        return ESCALATE_UNCERTAINTY
    return ESCALATE_NONE


__all__ = [
    "ESCALATE_LONG_FORM",
    "ESCALATE_NEEDS_MEMORY",
    "ESCALATE_NEEDS_TOOL",
    "ESCALATE_NONE",
    "ESCALATE_UNCERTAINTY",
    "ESCALATIONS",
    "EXCHANGE_WINDOW_S",
    "LONG_FORM_WORDS",
    "MIN_ANSWERABLE_WORDS",
    "TIERS",
    "TIER_ACKNOWLEDGE",
    "TIER_ANSWER",
    "TIER_HEAR_ONLY",
    "EngagementVerdict",
    "escalation_after",
    "escalation_for",
    "triage",
    "triage_in_exchange",
]
