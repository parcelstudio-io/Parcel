"""V1-A — opening-clause flush, the first unblocked slice of the Voice Spine M1.

Time-to-first-audio is set by how long the FIRST chunk takes to synthesize.
``SentenceChunkedSynthesizer`` chunks on sentence boundaries (up to 220 chars),
so a long opening sentence is fully synthesized before a single sample plays.
Flushing the opening clause shortens only that first chunk.

The flag is OFF by default and the off path must be byte-identical, because the
sentence-granular stream is what every committed acoustic and duplex baseline
was measured against.
"""

from __future__ import annotations

from parcel_robot.providers import SentenceChunkedSynthesizer

LONG = (
    "Okay, I am heading over to the sidewalk now and I will tell you when I get there. "
    "It should not take long."
)


class _RecordingSynth:
    """Blocking synthesizer that records exactly what it was asked to speak."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def synthesize(self, text: str) -> bytes:
        self.calls.append(text)
        return text.encode("utf-8")


def _stream(text: str, **kwargs) -> tuple[list[str], list[list[tuple[str, float]]]]:
    synth = _RecordingSynth()
    chunks = list(SentenceChunkedSynthesizer(synth, **kwargs).synthesize_stream(text))
    return synth.calls, [chunk.emotes for chunk in chunks]


def test_flag_off_is_byte_identical_to_the_sentence_stream() -> None:
    """The default path must not move: every committed baseline assumes it."""

    baseline, baseline_emotes = _stream(LONG)
    explicit_off, explicit_off_emotes = _stream(LONG, first_clause_chars=None)
    assert explicit_off == baseline
    assert explicit_off_emotes == baseline_emotes
    assert baseline[0].startswith("Okay, I am heading over")
    assert len(baseline) == 2, "unchanged: one chunk per sentence"


def test_flag_on_flushes_a_shorter_opening_clause_first() -> None:
    calls, _ = _stream(LONG, first_clause_chars=48)
    assert calls[0] == "Okay,", "first audio waits only on the opening clause"
    assert len(calls[0]) < len("Okay, I am heading over to the sidewalk now and I will tell you")
    # Nothing is dropped: the words still arrive, just later.
    assert "".join(call.replace(" ", "") for call in calls) == LONG.replace(" ", "")


def test_later_sentences_keep_their_sentence_shape() -> None:
    calls, _ = _stream(LONG, first_clause_chars=48)
    assert calls[-1] == "It should not take long."


def test_a_first_chunk_carrying_emotes_is_never_split() -> None:
    """Emote tags are anchored per word; re-anchoring across a split mistimes them."""

    text = "Okay, [emote:tail_wag] I am heading over to the sidewalk now and will report back."
    calls, emotes = _stream(text, first_clause_chars=48)
    assert calls[0].startswith("Okay,")
    assert "heading over to the sidewalk" in calls[0], "kept whole because it carries an emote"
    assert list(emotes[0]) == [("tail_wag", 1.0)]


def test_short_opening_sentence_is_left_alone() -> None:
    calls, _ = _stream("On my way. Stand by please.", first_clause_chars=48)
    assert calls[0] == "On my way."


def test_no_clause_boundary_leaves_the_sentence_whole() -> None:
    text = "I am walking towards the sidewalk right now without stopping anywhere at all."
    calls, _ = _stream(text, first_clause_chars=48)
    assert calls == [text]


def test_budget_is_validated_against_the_sentence_budget() -> None:
    import pytest

    with pytest.raises(ValueError, match="first clause budget"):
        SentenceChunkedSynthesizer(_RecordingSynth(), max_chars=220, first_clause_chars=3)
    with pytest.raises(ValueError, match="first clause budget"):
        SentenceChunkedSynthesizer(_RecordingSynth(), max_chars=60, first_clause_chars=200)


def test_config_key_is_allowlisted_and_absent_from_the_locked_default_config() -> None:
    """The key must be readable, and must NOT be set in the hash-locked config.

    ``configs/robot.yaml`` is pinned by ``evals/companion/embodied_plan_v1``
    and by ``DIGEST_SENTINELS``. Enabling this flag there would move a frozen
    digest, so the default config must stay silent and the flag is opt-in.
    """

    from pathlib import Path

    import yaml

    from parcel_robot.providers import _ALLOWED_SPEECH_KEYS

    assert "first_clause_chars" in _ALLOWED_SPEECH_KEYS
    repo = Path(__file__).resolve().parents[1]
    speech = yaml.safe_load((repo / "configs" / "robot.yaml").read_text(encoding="utf-8"))["speech"]
    assert "first_clause_chars" not in speech
