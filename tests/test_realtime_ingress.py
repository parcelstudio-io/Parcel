"""Card R1: punctuation normalization, and the closed scope of the hosted ingress.

THE DEFECT THIS FILE PINS (binding constraint 2)
------------------------------------------------
A hosted transcriber writes ``"Stop."``. Every phrase set in this repo is an
EXACT-MATCH set of unpunctuated strings — ``EMERGENCY_STOP_PHRASES`` at
``closed_intents.py:28``, the router's ``_FOLLOW`` / ``_HOLD`` sets,
``parse_closed_intent``. ``"stop."`` matches none of them, and nothing anywhere
raises: the deterministic story simply stops being true on hosted audio, one
utterance at a time, forever. So every emergency phrase and every closed intent
is fed through this ingress in punctuated form here, and the seeded-failure
harness removes the normalizer to prove these tests notice.

THE SECOND DEFECT (binding constraint 1)
----------------------------------------
Scope. The answer space is closed: emergency, one closed intent, follow, hold,
or nothing. There is no branch that reaches a planner, a grammar, a
conversation model, or ``DuplexVoiceSession.submit_text``. Chit-chat — which is
almost all of a companion conversation — must classify as ``KIND_NONE`` and
move no motor.

THE THIRD THING WORTH PINNING
-----------------------------
No copied grammars. U33 cost a stop that stopped nothing because three copies
of the stop phrase set existed and one of them lacked "halt". The tests below
read the router's and the parser's own objects and assert identity with what
this module matches against.
"""

from __future__ import annotations

import pytest

from parcel_robot.brain import router as router_module
from parcel_robot.realtime.ingress import (
    EMERGENCY_STOP_PHRASES,
    INGRESS_KINDS,
    KIND_CLOSED_INTENT,
    KIND_EMERGENCY,
    KIND_FOLLOW,
    KIND_HOLD,
    KIND_NONE,
    fold,
    follow_phrases,
    hold_phrases,
    normalize,
    scan,
)
from parcel_robot.voice.closed_intents import (
    ClosedIntent,
    closed_intent_phrases,
    parse_closed_intent,
)

#: What a hosted transcriber actually appends. "…" is the streaming-ASR
#: continuation mark and appears on partial-looking finals.
PUNCTUATION_SUFFIXES = (".", "!", "?", "...", "…", ",")


# ---------------------------------------------------------- single-sourcing
def test_the_stop_grammar_is_the_repos_stop_grammar_not_a_copy() -> None:
    assert EMERGENCY_STOP_PHRASES is closed_intent_phrases(ClosedIntent.STOP)
    assert "halt" in EMERGENCY_STOP_PHRASES  # the phrase U33's copy dropped


def test_follow_and_hold_are_read_from_the_router_live() -> None:
    assert follow_phrases() == frozenset(router_module._FOLLOW)
    assert hold_phrases() == frozenset(router_module._HOLD)


def test_a_new_router_follow_phrase_reaches_this_lane_without_an_edit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Drift is impossible by construction: the set is read, never copied."""

    monkeypatch.setattr(router_module, "_FOLLOW", frozenset({"walkies"}))
    assert scan("Walkies!").kind == KIND_FOLLOW


# ------------------------------------------------------------- normalization
@pytest.mark.parametrize("phrase", sorted(EMERGENCY_STOP_PHRASES))
@pytest.mark.parametrize("suffix", PUNCTUATION_SUFFIXES)
def test_every_punctuated_emergency_phrase_still_latches(phrase: str, suffix: str) -> None:
    found = scan(f"{phrase.capitalize()}{suffix}")
    assert found.kind == KIND_EMERGENCY, found
    assert found.intent is ClosedIntent.STOP


@pytest.mark.parametrize(
    "intent",
    [
        ClosedIntent.PAUSE,
        ClosedIntent.RESUME,
        ClosedIntent.FASTER,
        ClosedIntent.SLOWER,
        ClosedIntent.COME,
    ],
)
@pytest.mark.parametrize("suffix", PUNCTUATION_SUFFIXES)
def test_every_punctuated_closed_intent_still_parses(intent: ClosedIntent, suffix: str) -> None:
    for phrase in sorted(closed_intent_phrases(intent)):
        found = scan(f"{phrase}{suffix}")
        assert found.kind == KIND_CLOSED_INTENT, (phrase, suffix, found)
        assert found.intent is intent


@pytest.mark.parametrize("suffix", PUNCTUATION_SUFFIXES)
def test_every_punctuated_follow_and_hold_phrase_still_matches(suffix: str) -> None:
    for phrase in sorted(follow_phrases()):
        assert scan(f"{phrase}{suffix}").kind == KIND_FOLLOW, (phrase, suffix)
    for phrase in sorted(hold_phrases()):
        assert scan(f"{phrase}{suffix}").kind == KIND_HOLD, (phrase, suffix)


def test_the_unnormalized_text_really_does_match_nothing() -> None:
    """The premise of this whole module, stated as an executable fact."""

    assert "stop." not in EMERGENCY_STOP_PHRASES
    assert parse_closed_intent("stop.") is None
    assert "follow me." not in router_module._FOLLOW
    assert "stay." not in router_module._HOLD


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Stop.", "Stop"),
        ("  follow   me!  ", "follow me"),
        ("wait here…", "wait here"),
        ("Pause that,", "Pause that"),
        ("stop...", "stop"),
        ("Well — I don't know, really.", "Well — I don't know, really"),
        ("", ""),
        ("...", ""),
    ],
)
def test_normalize_collapses_whitespace_and_strips_terminal_marks(raw: str, expected: str) -> None:
    assert normalize(raw) == expected


def test_normalize_preserves_case_for_the_ledger_and_folds_only_for_matching() -> None:
    assert normalize("Stop.") == "Stop"
    assert fold("Stop.") == "stop"
    assert scan("Stop.").normalized == "Stop"


def test_interior_punctuation_is_not_rewritten() -> None:
    """A normalizer, not a rewriter: the ledger keeps the owner's sentence."""

    assert normalize("It's fine, really — go on.") == "It's fine, really — go on"


def test_normalize_refuses_a_non_string() -> None:
    with pytest.raises(TypeError):
        normalize(object())  # type: ignore[arg-type]


# -------------------------------------------------------------------- scope
@pytest.mark.parametrize(
    "utterance",
    [
        "How was your day?",
        "Tell me about the park.",
        "I'm feeling a bit down today.",
        "What do you think about squirrels?",
        "Do you remember the bench by the water?",
        "Good dog!",
        "Nothing, never mind.",
        # Physical-sounding but NOT in a closed set: the local side must stay
        # out of it entirely; the hosted model answers and the robot does not
        # move. Reaching the planner from here is the double-execution defect.
        "go to the sidewalk",
        "walk behind me",
        "do your happy spin",
        "sit",
        "turn left",
    ],
)
def test_conversation_and_open_grammar_execute_nothing_locally(utterance: str) -> None:
    found = scan(utterance)
    assert found.kind == KIND_NONE, found
    assert found.actionable is False


def test_goal_amendments_are_deliberately_outside_this_ingress() -> None:
    """ "Actually, the other bench" is a re-plan, and re-planning is the planner."""

    for utterance in ("Actually, the other bench.", "No, change course.", "Instead, the park."):
        found = scan(utterance)
        assert found.kind == KIND_NONE, (utterance, found)
        assert found.intent is None


def test_every_scan_result_is_inside_the_closed_answer_space() -> None:
    corpus = [
        "Stop.",
        "halt!",
        "pause that",
        "come here.",
        "follow me.",
        "wait here.",
        "how was your day?",
        "",
        "   ",
        "actually, the other one",
        "go to the sidewalk and then sit",
    ]
    assert {scan(text).kind for text in corpus} <= INGRESS_KINDS


def test_empty_and_whitespace_only_transcripts_are_inert() -> None:
    for text in ("", "   ", "\n\t", "...", "?!"):
        found = scan(text)
        assert found.kind == KIND_NONE
        assert found.normalized == ""


def test_scan_keeps_the_original_verbatim_for_the_ledger() -> None:
    found = scan("  Stop.  ")
    assert found.original == "  Stop.  "
    assert found.normalized == "Stop"


# ------------------------------------------------------------------ ordering
def test_emergency_wins_over_every_other_reading() -> None:
    """STOP is a closed intent too; the latch must be reached first, always."""

    assert parse_closed_intent("stop") is ClosedIntent.STOP
    assert scan("stop").kind == KIND_EMERGENCY


def test_the_name_of_a_scan_is_the_intent_when_there_is_one() -> None:
    assert scan("pause.").name == "pause"
    assert scan("follow me.").name == KIND_FOLLOW
    assert scan("stay.").name == KIND_HOLD
    assert scan("hello there").name == KIND_NONE
