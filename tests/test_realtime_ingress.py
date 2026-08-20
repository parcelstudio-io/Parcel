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

import re
from pathlib import Path

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
    SPOKEN_EMERGENCY_PHRASE,
    SPOKEN_EMERGENCY_VARIANTS,
    fold,
    follow_phrases,
    hold_phrases,
    matches_spoken_emergency,
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


# ==================================================== card R9: "Die Stop"
# Owner policy ruling, 2026-08-19, verbatim: "Space bar should be the e-stop.
# In voice command it should be 'Die Stop'."
#
# R7 measured the exact-phrase latch failing live three times over the hosted
# transcriber (R7_STATUS.md open risk 1): "Stop." came back as "Soap" and as
# "Top", and a correctly transcribed "Stop. Stop right now, please stop." made
# no match at all because the WHOLE utterance was not one of the four phrases.
# The tests below pin BOTH halves of the answer to that: what the spoken phrase
# now tolerates, and what it still refuses to latch on.

#: What a transcriber writes between two shouted words. Empty string included
#: on purpose: "Diestop" is a real whisper spelling of one breath.
_SEPARATORS = ("", " ", ", ", "-", ". ", "! ", "  ", "… ", "... ")

#: The spellings this card promises to latch on, written out as LITERALS.
#:
#: Deliberately not ``SPOKEN_EMERGENCY_VARIANTS``. Parametrizing over the
#: module's own tuple is a test that agrees with whatever the module currently
#: says: delete three entries and the suite runs three fewer cases and stays
#: green — a vacuous pass, and precisely the shape of "the test does not pin the
#: fix". These are the promise; the assertion below holds the module to it.
_ASR_SPELLINGS = ("die", "dye", "dai", "di")


def test_the_owners_spoken_phrase_is_defined_and_is_the_ruling() -> None:
    assert SPOKEN_EMERGENCY_PHRASE == "die stop"
    assert scan("Die Stop").kind == KIND_EMERGENCY
    assert scan("Die Stop").intent is ClosedIntent.STOP
    assert scan("Die Stop").name == "stop", "it must be indistinguishable downstream"


def test_the_accepted_spellings_are_exactly_the_ones_this_card_promised() -> None:
    """Narrowing the variant list is a MISSED LATCH, and silent without this.

    Widening it is the other failure (see the "day" test below), so the set is
    pinned in both directions rather than only against growth.
    """

    assert SPOKEN_EMERGENCY_VARIANTS == _ASR_SPELLINGS


@pytest.mark.parametrize("variant", _ASR_SPELLINGS)
@pytest.mark.parametrize("separator", _SEPARATORS)
def test_every_asr_variant_and_separator_latches(variant: str, separator: str) -> None:
    """THE seed catcher for "variant tolerance removed, exact-only again".

    Each of these is a spelling a hosted ASR can hand back for one spoken
    "Die Stop". A missed latch is the failure that matters, so every one of them
    has to reach the emergency branch.
    """

    utterance = f"{variant.capitalize()}{separator}stop"
    found = scan(utterance)
    assert found.kind == KIND_EMERGENCY, (utterance, found)
    assert found.intent is ClosedIntent.STOP
    assert matches_spoken_emergency(utterance) is True


@pytest.mark.parametrize("suffix", PUNCTUATION_SUFFIXES)
@pytest.mark.parametrize(
    "utterance",
    [
        # A transcriber that heard two stressed syllables writes two sentences.
        "Die. Stop",
        "Die! Stop",
        "Die... stop",
        "Die — stop",
        "Die, stop",
        "Die-stop",
        "Diestop",
        "Die stop",
    ],
)
def test_a_sentence_break_between_the_two_words_still_latches(
    utterance: str, suffix: str
) -> None:
    """THE seed catcher for "the separator class narrowed to a space".

    A hosted transcriber punctuates what it hears, and a shouted "DIE. STOP."
    comes back as two sentences at least as often as one phrase. Treating the
    sentence break as a reason NOT to latch would be the missed latch this whole
    card exists to prevent, so any run of up to four non-word characters — or
    none at all — joins the two words.
    """

    found = scan(f"{utterance}{suffix}")
    assert found.kind == KIND_EMERGENCY, (utterance, suffix, found)


@pytest.mark.parametrize(
    "utterance",
    [
        "Die stop! Die stop!",
        "Hey — die stop.",
        "no no no die stop",
        "Die stop right now please",
        "Okay, die stop, I mean it.",
        "DIE STOP",
        "   die    stop   ",
    ],
)
def test_the_spoken_phrase_latches_anywhere_inside_the_utterance(utterance: str) -> None:
    """A frightened owner does not speak a tidy two-word sentence.

    This is the precise defect R7 measured: "Stop. Stop right now, please stop."
    was transcribed CORRECTLY and matched nothing, because the whole utterance
    was not one of the four exact phrases. Whole-utterance matching is the wrong
    rule for a transcript, and this pins that it is no longer the rule here.
    """

    assert scan(utterance).kind == KIND_EMERGENCY, utterance


# ------------------------------------------ what the LIVE transcriber returned
#: Every owner row the hosted transcriber wrote during R9's live proof, verbatim
#: from the ledger (``scrum/20260819/task_2/R9_STATUS.md``, live-proof table).
#: Real measurements, not invented strings — which is the only reason the two
#: ``False`` rows are allowed to sit here at all.
#:
#: The two misses are the SAME failure, and it is a second-word failure, not a
#: variant-list failure: this transcriber drops the leading /s/ of "stop" after
#: an /aɪ/ word, exactly as R7 measured a bare spoken "Stop." coming back as
#: "Top". Accepting "top" as well as "stop" would catch both — and would also
#: latch on "I love your tie-dye top", a sentence a companion actually hears.
#: That trade is a GRAMMAR WIDENING for a safety latch beyond what the owner's
#: ruling authorised, so it is reported and left owner-gated rather than taken
#: unilaterally. The owner's own phrase measured 4/4 live.
LIVE_TRANSCRIPTS: tuple[tuple[str, str, bool], ...] = (
    ("Die stop.", "Die stop", True),
    ("Die stop! Die stop!", "Die Stop! Die Stop!", True),
    ("Die stop.", "Die Stop!", True),
    ("Die stop, die stop, please die stop.", "Die Stop! Die Stop! Please Die Stop!", True),
    ("Dye stop.", "Dice top", False),
    ("Dye. Stop.", "die top", False),
    ("Let's stop by the store on the way home.", "Let's stop by the store on the way home.", False),
)


@pytest.mark.parametrize(("spoken", "heard", "latches"), LIVE_TRANSCRIPTS)
def test_the_live_transcripts_still_classify_the_way_they_were_measured(
    spoken: str, heard: str, latches: bool
) -> None:
    """The live proof, frozen as a regression — including where it fell short.

    Four of these rows are the card working. Two are the honest gap, kept here
    rather than in prose so that the day somebody widens the second word, this
    test turns red and makes them say so on purpose. A limitation nobody can
    trip over is a limitation nobody fixes.
    """

    del spoken
    assert (scan(heard).kind == KIND_EMERGENCY) is latches, heard


# ------------------------------------------------------ and what it must NOT do
@pytest.mark.parametrize(
    "utterance",
    [
        # The card's named negative class: "stop" mid-thought, in a sentence
        # nobody meant as a command.
        "let's stop by the store",
        "Let's stop by the store on the way home, okay?",
        "I'll stop for coffee first.",
        "The bus stop is over there.",
        "Don't stop believing.",
        "Can we stop and look at the ducks?",
        "We should stop by the park later.",
        "Stop signs are red.",
        # The deliberately excluded high-frequency homophone. "day" is not a
        # variant precisely because this is a sentence people say.
        "Let's call it a day, stop the recording.",
        # Word-boundary neighbours of the variants. None of these is the phrase.
        "That sounds like a dystopian nightmare.",
        "The comedian stopped mid-sentence.",
        "Set the stopwatch and dye the fabric.",
        "Nairobi stopover, then home.",
    ],
)
def test_an_ordinary_sentence_containing_stop_never_latches(utterance: str) -> None:
    """THE seed catcher for "the negative case latches".

    The spoken phrase widened what an EMERGENCY looks like; it must not have
    widened what "stop" alone looks like. "stop" is still only ever matched as a
    WHOLE normalized utterance against the typed phrase set, so a sentence that
    merely contains the word stops nothing.
    """

    found = scan(utterance)
    assert found.kind == KIND_NONE, (utterance, found)
    assert found.actionable is False
    assert matches_spoken_emergency(utterance) is False


def test_the_bare_word_stop_inside_a_sentence_is_still_not_a_latch() -> None:
    """Stated as the rule rather than as examples, so the rule cannot drift."""

    assert scan("stop").kind == KIND_EMERGENCY, "the whole utterance IS the phrase"
    assert scan("please stop the car").kind == KIND_NONE
    assert scan("stop by later").kind == KIND_NONE


def test_a_high_frequency_homophone_is_deliberately_not_a_variant() -> None:
    """"day" was considered and refused; this records the refusal executably."""

    assert "day" not in SPOKEN_EMERGENCY_VARIANTS
    assert scan("day stop").kind == KIND_NONE


# ------------------------------------------------------------- single-sourcing
def test_the_typed_grammar_was_not_widened_by_the_spoken_phrase() -> None:
    """The typed set is shared with the local agent and the router. Untouched.

    ``closed_intents.py`` is the grammar ``agent.py``, ``brain/router.py`` and
    this ingress all read for TYPED text, where exact matching is correct. The
    spoken phrase is an ingress-only rule and must not have leaked into it.
    """

    assert EMERGENCY_STOP_PHRASES is closed_intent_phrases(ClosedIntent.STOP)
    assert EMERGENCY_STOP_PHRASES == frozenset({"stop", "stop now", "emergency stop", "halt"})
    assert parse_closed_intent("die stop") is None
    assert parse_closed_intent("dye stop") is None


def test_the_spoken_phrase_exists_exactly_once_in_the_source_tree() -> None:
    """U33 cost a stop that stopped nothing because a grammar had three copies.

    This phrase has one definition, in ``realtime/ingress.py``, and it is
    exported. A second literal anywhere under ``src/`` is the beginning of the
    same bug, so it is a test failure rather than a code review's job.
    """

    src = Path(__file__).resolve().parents[1] / "src"
    pattern = re.compile(r"die\W{0,4}stop", re.IGNORECASE)
    offenders = [
        str(path.relative_to(src))
        for path in sorted(src.rglob("*.py"))
        if path.name != "ingress.py" and pattern.search(path.read_text(encoding="utf-8"))
    ]
    assert offenders == [], f"the spoken emergency phrase was copied into {offenders}"
