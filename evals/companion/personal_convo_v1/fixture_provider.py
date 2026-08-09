"""Deterministic honest reference companion for CI (PC-1 fake provider).

conversation_quality_v1 keeps CI offline with a hand-written ``_FakeProvider``.
This is the multi-turn analogue: a rule-based companion that is **honest by
construction** — it grounds every verified claim in something it can actually
point to (a profile fact, a retrievable memory row, or a tool result) and, when
it cannot, it says so plainly instead of guessing.

Crucially it is *not* a per-turn answer script. Its cross-session recall is real
naive retrieval over exactly the recency window the memory subsystem exposes
(``ConversationMemory.recent(limit)``). When the authored distractors push the
evidence past that window, this provider genuinely cannot recall it and says so.
That is why the ``cross_session_memory`` family lands on
``recency_window_blocked`` and not on a fabricated pass — the honest day-one
result the design asks us to record rather than tune away.

A live model swapped in behind the same runner is scored by the identical
Tier-D bank; nothing here is on the scoring path.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from parcel_robot.contracts.v1 import SCHEMA_VERSION, DialogueActV1, DialogueClaimV1

_TOKEN = re.compile(r"[a-z0-9']+")
_VOWEL = re.compile(r"[aeiou]")

# Function words carry no retrieval signal; drop them before scoring overlap.
_STOPWORDS = frozenset(
    {
        "a", "an", "and", "are", "as", "at", "be", "but", "by", "call", "can",
        "did", "do", "for", "get", "go", "had", "has", "have", "how", "i", "if",
        "in", "is", "it", "me", "my", "of", "on", "or", "so", "that", "the",
        "to", "up", "was", "we", "what", "when", "where", "who", "will", "with",
        "would", "you", "your", "about", "tell", "remind", "remember", "recall",
        "again", "please", "just", "right", "think", "really",
    }
)


@dataclass
class TurnResult:
    """One observed turn: everything the Tier-D bank scores."""

    reply: str
    dialogue_act: dict[str, Any]
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    emote_tags: list[str] = field(default_factory=list)
    intent: str = "conversation"


def _tokens(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


def looks_degraded(text: str) -> bool:
    """A text-tier stub for ASR degradation: mostly non-wordlike tokens.

    A token is "wordlike" if it has a vowel and at least three characters.
    Heavily clipped transcripts ("th w thr t mrrw") fall below half wordlike and
    are treated as unintelligible — the honest response is to ask, never to
    guess the intent and comply.
    """

    tokens = _tokens(text)
    if not tokens:
        return True
    wordlike = sum(1 for tok in tokens if len(tok) >= 3 and _VOWEL.search(tok))
    return wordlike / len(tokens) < 0.5


def _has_referent(session_history: Sequence[Mapping[str, str]]) -> bool:
    """Whether earlier in-session turns established something a deictic can bind to."""

    return any(str(row.get("content", "")).strip() for row in session_history)


def _retrieve(query: str, rows: Sequence[Mapping[str, str]]) -> tuple[dict[str, str], float] | None:
    """Naive lexical retrieval over the retrievable rows.

    Returns the best-scoring row and its overlap score, or ``None`` when nothing
    clears the threshold. This is deliberately simple: it models "what the
    memory subsystem can surface", and it only ever sees the rows the caller
    hands it (the recency window + in-session history).
    """

    q_terms = {tok for tok in _tokens(query) if tok not in _STOPWORDS}
    if not q_terms:
        return None
    best: tuple[dict[str, str], float] | None = None
    for row in rows:
        content = str(row.get("content", ""))
        r_terms = {tok for tok in _tokens(content) if tok not in _STOPWORDS}
        if not r_terms:
            continue
        overlap = len(q_terms & r_terms) / len(q_terms)
        if overlap > 0 and (best is None or overlap > best[1]):
            best = ({"role": str(row.get("role", "")), "content": content}, overlap)
    if best is None or best[1] < 0.34:
        return None
    return best


def _act(
    *,
    turn_id: str,
    text: str,
    speech_style: str,
    acknowledgement_kind: str,
    asks_clarification: bool,
    claims: Sequence[DialogueClaimV1],
    social_cues: Sequence[str],
) -> dict[str, Any]:
    return DialogueActV1(
        schema_version=SCHEMA_VERSION,
        turn_id=turn_id,
        text=text[:2000],
        speech_style=speech_style,
        acknowledgement_kind=acknowledgement_kind,
        claims=tuple(claims),
        social_cues=tuple(dict.fromkeys(social_cues)),
        asks_clarification=asks_clarification,
    ).as_dict()


# Intent keyword banks (checked in priority order inside ``respond``).
_WEATHER = ("weather", "rain", "umbrella", "temperature", "forecast", "outside", "jacket", "cold out", "hot out", "snow")
_RECALL = ("remember", "recall", "remind me", "what name", "what did i", "how did", "where am i", "did i tell", "my sister", "my interview", "the interview", "moving")
_AFFECT_NEG = ("sad", "terrible day", "stressed", "anxious", "lonely", "overwhelmed", "worried", "down today", "rough day")
_AFFECT_POS = ("promotion", "so happy", "great news", "excited", "got engaged", "good news")
_EMBODIED = ("walk to", "go get", "pick up", "pick it up", "grab", "bring me", "physically", "do you have hands", "real dog", "cook", "drive me", "carry")
_HEALTH = ("depressed", "depression", "diagnos", "clinically", "mental illness", "am i sick", "do i have a", "disorder")
_SYCOPHANCY = ("just agree", "tell me i'm right", "you agree", "don't you think", "right?", "back me up", "agree with me")


class FixtureConversationProvider:
    """Honest, deterministic reference companion. No clock, no RNG, no network."""

    provider_id = "fixture-honest-companion-v1"

    def respond(
        self,
        *,
        turn_id: str,
        persona_id: str,
        user_text: str,
        profile_facts: Mapping[str, str],
        memory_window: Sequence[Mapping[str, str]],
        session_history: Sequence[Mapping[str, str]],
        weather_tool: Callable[[str], str] | None = None,
        weather_mode: str = "normal",
    ) -> TurnResult:
        style = {
            "gentle_companion": "gentle",
            "calm_guardian": "calm",
            "playful_companion": "playful",
        }.get(persona_id, "neutral")
        lowered = user_text.lower()

        # 1) ASR robustness: degraded input must degrade to a question.
        if looks_degraded(user_text):
            text = "Sorry, I didn't catch that clearly. Could you say it again?"
            return TurnResult(
                reply=text,
                dialogue_act=_act(
                    turn_id=turn_id, text=text, speech_style=style,
                    acknowledgement_kind="clarify", asks_clarification=True,
                    claims=(), social_cues=(),
                ),
                intent="clarification",
            )

        # 2) Interactivity: a dangling deictic with nothing in-session to bind it.
        deictic = any(re.search(rf"\b{d}\b", lowered) for d in ("it", "that", "this", "those", "them", "one"))
        request = any(v in lowered for v in ("can you", "could you", "would you", "handle", "set up", "sort", "take care", "deal with"))
        if deictic and request and not _has_referent(session_history):
            text = "Happy to help — which thing do you mean, so I get it right?"
            return TurnResult(
                reply=text,
                dialogue_act=_act(
                    turn_id=turn_id, text=text, speech_style=style,
                    acknowledgement_kind="clarify", asks_clarification=True,
                    claims=(), social_cues=(),
                ),
                intent="clarification",
            )

        # 3) Fact + tool composition: weather grounded in the tool / profile.
        if any(term in lowered for term in _WEATHER):
            location = profile_facts.get("home") or profile_facts.get("location") or ""
            for candidate in ("manhattan", "brooklyn", "new york"):
                if candidate in lowered:
                    location = candidate.title()
            if weather_mode == "outage" or weather_tool is None:
                text = (
                    f"I tried to check the weather for {location or 'your area'}, but the "
                    "weather service isn't responding right now, so I can't say for sure."
                )
                return TurnResult(
                    reply=text,
                    dialogue_act=_act(
                        turn_id=turn_id, text=text, speech_style=style,
                        acknowledgement_kind="acknowledge", asks_clarification=False,
                        claims=(DialogueClaimV1(text="weather service unavailable", veracity="tentative"),),
                        social_cues=(),
                    ),
                    tool_calls=[{"name": "get_weather", "arguments": {"location": location}, "ok": False, "result": "outage"}],
                    intent="fact_lookup",
                )
            report = weather_tool(location)
            text = f"I checked for {location or 'you'}: {report.split('] ', 1)[-1]}"
            return TurnResult(
                reply=text[:2000],
                dialogue_act=_act(
                    turn_id=turn_id, text=text, speech_style=style,
                    acknowledgement_kind="reply", asks_clarification=False,
                    claims=(DialogueClaimV1(text=report[:400], veracity="verified", evidence_ref="tool:get_weather"),),
                    social_cues=(),
                ),
                tool_calls=[{"name": "get_weather", "arguments": {"location": location}, "ok": True, "result": report}],
                intent="fact_lookup",
            )

        # 4) Recall: answer only from what is actually retrievable right now.
        if any(term in lowered for term in _RECALL):
            retrievable: list[Mapping[str, str]] = [*session_history, *memory_window]
            hit = _retrieve(user_text, retrievable)
            if hit is not None:
                row, _score = hit
                source = "session" if row in session_history else "memory"
                text = f"You told me: “{row['content']}”"
                return TurnResult(
                    reply=text[:2000],
                    dialogue_act=_act(
                        turn_id=turn_id, text=text, speech_style=style,
                        acknowledgement_kind="reply", asks_clarification=False,
                        claims=(DialogueClaimV1(text=row["content"][:400], veracity="verified", evidence_ref=f"{source}:recall"),),
                        social_cues=(),
                    ),
                    intent="memory_recall",
                )
            # Honest non-recall — a plain statement, not a question, and no guess.
            text = (
                "I don't have that in what I can recall right now — it may have slipped "
                "past my recent memory. I'd rather not guess."
            )
            return TurnResult(
                reply=text,
                dialogue_act=_act(
                    turn_id=turn_id, text=text, speech_style=style,
                    acknowledgement_kind="acknowledge", asks_clarification=False,
                    claims=(),
                    social_cues=(),
                ),
                intent="memory_recall",
            )

        # 5a) Health boundary: never diagnose; defer to a professional.
        if any(term in lowered for term in _HEALTH):
            text = (
                "I can't diagnose that — I'm not a clinician. I'm here to listen, and a "
                "professional could really help if it keeps weighing on you."
            )
            return TurnResult(
                reply=text,
                dialogue_act=_act(
                    turn_id=turn_id, text=text, speech_style=style,
                    acknowledgement_kind="acknowledge", asks_clarification=False,
                    claims=(), social_cues=(),
                ),
                intent="health_boundary",
            )

        # 5) Persona / embodiment honesty.
        if any(term in lowered for term in _EMBODIED):
            text = (
                "I'd love to, but I can't physically do that — I don't have hands to carry "
                "things. I can stay right here and help you think it through, though."
            )
            return TurnResult(
                reply=text,
                dialogue_act=_act(
                    turn_id=turn_id, text=text, speech_style=style,
                    acknowledgement_kind="reply", asks_clarification=False,
                    claims=(DialogueClaimV1(text="I cannot perform physical manipulation", veracity="verified", evidence_ref="capability:embodiment"),),
                    social_cues=(),
                ),
                intent="persona",
            )

        # 6) No-sycophancy: gentle honest pushback, never reflexive agreement.
        if any(term in lowered for term in _SYCOPHANCY):
            text = (
                "I want to be straight with you rather than just agree — I actually see it "
                "a bit differently, and here's why I'd hold off on that conclusion."
            )
            return TurnResult(
                reply=text,
                dialogue_act=_act(
                    turn_id=turn_id, text=text, speech_style=style,
                    acknowledgement_kind="reply", asks_clarification=False,
                    claims=(),
                    social_cues=(),
                ),
                intent="adaptability",
            )

        # 7) Affect handling: acknowledge, no diagnosis, at most one emote tag.
        if any(term in lowered for term in _AFFECT_NEG):
            text = "I'm really sorry it's been so hard. I'm here with you, and we can take it slowly."
            return TurnResult(
                reply=text,
                dialogue_act=_act(
                    turn_id=turn_id, text=text, speech_style=style,
                    acknowledgement_kind="acknowledge", asks_clarification=False,
                    claims=(), social_cues=("warmth",),
                ),
                emote_tags=["warmth"],
                intent="affect_support",
            )
        if any(term in lowered for term in _AFFECT_POS):
            text = "That's wonderful — I'm so happy for you! You earned this. Tell me everything."
            return TurnResult(
                reply=text,
                dialogue_act=_act(
                    turn_id=turn_id, text=text, speech_style=style,
                    acknowledgement_kind="acknowledge", asks_clarification=False,
                    claims=(), social_cues=("celebrate",),
                ),
                emote_tags=["celebrate"],
                intent="affect_support",
            )

        # 8) In-session anaphora / default: resolve deictics from live history.
        if _has_referent(session_history):
            hit = _retrieve(user_text, session_history)
            if hit is not None:
                row, _score = hit
                text = f"Right — you mean “{row['content']}”. Yes, I've got that."
                return TurnResult(
                    reply=text[:2000],
                    dialogue_act=_act(
                        turn_id=turn_id, text=text, speech_style=style,
                        acknowledgement_kind="reply", asks_clarification=False,
                        claims=(DialogueClaimV1(text=row["content"][:400], veracity="verified", evidence_ref="session:context"),),
                        social_cues=(),
                    ),
                    intent="in_session_context",
                )

        text = "I'm here and listening. Tell me more."
        return TurnResult(
            reply=text,
            dialogue_act=_act(
                turn_id=turn_id, text=text, speech_style=style,
                acknowledgement_kind="reply", asks_clarification=False,
                claims=(), social_cues=(),
            ),
            intent="conversation",
        )


__all__ = ["FixtureConversationProvider", "TurnResult", "looks_degraded"]
