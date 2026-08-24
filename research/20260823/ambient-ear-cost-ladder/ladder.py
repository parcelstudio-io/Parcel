"""H1 shared substrate: the corpora, the duty cycle, and the session cost model.

Every number in RESULTS.md that is not a stopwatch reading comes through here,
so that P0, P1 and P2 cannot quietly assume different days, different token
rates or different prices.

THE DUTY CYCLE IS PRE-REGISTERED, NOT TUNED
-------------------------------------------
DESIGN.md fixes it: 12 listening hours a day, 30 days a month, and one day of
conversation = the 174 owner turns of ``realtime_convo_v1``. Nothing in this
file may be changed to make a policy pass; the policies are compared against
each other on exactly this day.

THE MODELLING ASSUMPTIONS, STATED ONCE, AND WHAT THE LIVE RUN DID TO THEM
-------------------------------------------------------------------------
The corpus was captured in TEXT modality, so it carries no audio tokens at all.
An audio session's cost therefore has to be modelled:

* the owner's turn becomes ``words / WORDS_PER_SECOND`` seconds of audio at
  :data:`AUDIO_TOKENS_PER_SECOND`. The speech rate is MEASURED off
  ``acoustic_loop_v1`` (22 Piper utterances with ground-truth speech bounds).
* the robot's spoken reply costs ``audio_out_per_text_out`` audio tokens for
  every text token it emits. That ratio is MEASURED by the live run — it is not
  a reading rate, it is what the provider actually billed for the same words.
* audio already in the conversation is re-read as input on every later turn.
  Measured live: a second audio turn's input audio count is the sum of both.

And one assumption the live run KILLED: DESIGN.md's premise that an open socket
is billed for the silence it is streamed. It is not — 63.8 s of uploaded
silence and 3.8 s of uploaded silence produced the same 19 audio input tokens
for the same utterance. :func:`listening_usd_per_hour` is kept because the
projection it feeds is pre-registered and has to be reported, but it is labelled
REFUTED wherever it appears.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from parcel_robot.realtime.cost import FULL_RATE_CARD, MINI_RATE_CARD, RateCard

REPO = Path(__file__).resolve().parents[3]
CONVO_DIR = REPO / "evals" / "companion" / "realtime_convo_v1"
ACOUSTIC_DIR = REPO / "evals" / "companion" / "acoustic_loop_v1"
RESULTS_DIR = Path(__file__).resolve().parent / "results"

# ------------------------------------------------------------- the duty cycle
LISTEN_HOURS_PER_DAY = 12.0
DAYS_PER_MONTH = 30.0
#: The provider bills roughly 600 audio tokens per minute of audio, each way.
AUDIO_TOKENS_PER_SECOND = 10.0
AUDIO_TOKENS_PER_MINUTE = AUDIO_TOKENS_PER_SECOND * 60.0

CARDS: Mapping[str, RateCard] = {"mini": MINI_RATE_CARD, "full": FULL_RATE_CARD}


@dataclass(frozen=True)
class Turn:
    """One owner turn of the replay corpus, with the usage it actually cost."""

    thread_id: str
    family: str
    index: int
    owner_text: str
    robot_text: str
    usage: Mapping[str, int]
    tool_calls: tuple[str, ...]

    @property
    def owner_words(self) -> int:
        return len(self.owner_text.split())

    @property
    def robot_words(self) -> int:
        return len(self.robot_text.split())


def load_turns() -> list[Turn]:
    """The 174 owner turns, in thread order. The pre-registered replay day."""

    turns: list[Turn] = []
    for path in sorted((CONVO_DIR / "fixtures").glob("*.json")):
        fixture = json.loads(path.read_text(encoding="utf-8"))
        for raw in fixture["turns"]:
            turns.append(
                Turn(
                    thread_id=str(fixture["thread_id"]),
                    family=str(fixture["family"]),
                    index=int(raw["index"]),
                    owner_text=str(raw["owner_text"]),
                    robot_text=str(raw["robot_text"]),
                    usage={k: int(v) for k, v in dict(raw["usage"]).items()},
                    tool_calls=tuple(str(c["name"]) for c in raw.get("tool_calls", ())),
                )
            )
    return turns


@dataclass(frozen=True)
class Utterance:
    """One acoustic fixture: the wav, its text, and its speech boundaries."""

    name: str
    kind: str
    text: str
    path: Path
    duration_s: float
    #: ``None`` on the two noise fixtures: they contain no speech at all, which
    #: is exactly why they are the ambient tape.
    speech_start_s: float | None
    speech_end_s: float | None
    has_internal_pause: bool

    @property
    def speech_s(self) -> float:
        if self.speech_start_s is None or self.speech_end_s is None:
            return 0.0
        return max(0.0, self.speech_end_s - self.speech_start_s)

    @property
    def words(self) -> int:
        return len(self.text.split())


def load_utterances() -> list[Utterance]:
    """``acoustic_loop_v1``'s 22 frozen utterances with ground-truth bounds."""

    corpus = json.loads((ACOUSTIC_DIR / "fixtures" / "corpus.json").read_text(encoding="utf-8"))
    return [
        Utterance(
            name=str(u["name"]),
            kind=str(u["kind"]),
            text=str(u["text"]),
            path=ACOUSTIC_DIR / str(u["file"]),
            duration_s=float(u["duration_s"]),
            speech_start_s=None if u["speech_start_s"] is None else float(u["speech_start_s"]),
            speech_end_s=None if u["speech_end_s"] is None else float(u["speech_end_s"]),
            has_internal_pause=bool(u["has_internal_pause"]),
        )
        for u in corpus["utterances"]
    ]


def measured_words_per_second(utterances: Sequence[Utterance]) -> float:
    """Speaking rate, measured off the frozen acoustic corpus rather than assumed.

    Only the single-clause ``complete`` utterances are used: the pause-heavy and
    expressive fixtures carry deliberate silence inside the speech interval, so
    including them would understate the rate a talker actually reads at.
    """

    speech = [u for u in utterances if u.kind == "complete"]
    words = sum(u.words for u in speech)
    seconds = sum(u.speech_s for u in speech)
    return words / seconds if seconds > 0 else 0.0


# ------------------------------------------------------------- pricing helpers
def price_rows(rows: Iterable[Mapping[str, object]], card: RateCard) -> float:
    """Total dollars for a sequence of usage rows at one card's rates."""

    return sum(card.priced_usd(row) for row in rows)


def listening_usd_per_hour(card: RateCard) -> float:
    """What an open socket costs per hour of pure silence.

    The number that decides the architecture: audio streamed to the input buffer
    is billed as uncached audio input whether or not anybody spoke.
    """

    return AUDIO_TOKENS_PER_MINUTE * 60.0 * card.audio_input_usd_per_mtok / 1e6


def audio_row_from_text_row(
    usage: Mapping[str, int],
    *,
    owner_words: int,
    robot_words: int,
    words_per_second: float,
    history_audio_tokens: int,
    audio_out_per_text_out: float,
) -> dict[str, int]:
    """A text-modality usage row, re-expressed as the audio row it would have been.

    MODELLED, not measured. The construction, so a reader can disagree with it
    precisely:

    * the owner's own words become ``owner_words / rate`` seconds of audio in;
    * the reply's TEXT tokens become ``audio_out_per_text_out`` audio tokens
      each — the ratio the live run measured, rather than a reading rate;
    * the conversation tail the provider re-reads on every turn grows by both,
      and is charged as input on this and every later turn — which is why
      ``history_audio_tokens`` is threaded through by the caller rather than
      recomputed here;
    * the text side keeps the corpus's own measured instruction/tool tokens,
      i.e. total text input minus the words that just became audio;
    * the cached fraction of the (much larger) audio history is carried at the
      SAME ratio the corpus measured for its text history, because that ratio is
      a property of the provider's cache window, not of the modality.
    """

    rate = max(0.5, float(words_per_second))
    owner_audio = round(owner_words / rate * AUDIO_TOKENS_PER_SECOND)
    robot_audio = round(int(usage.get("output_tokens", 0)) * float(audio_out_per_text_out))
    text_in = int(usage.get("input_tokens", 0))
    cached = int(usage.get("cached_tokens", 0))
    cached_fraction = cached / text_in if text_in > 0 else 0.0
    audio_in_total = history_audio_tokens + owner_audio
    return {
        "input_tokens": text_in + audio_in_total,
        "input_audio_tokens": audio_in_total,
        "cached_tokens": round((text_in + audio_in_total) * cached_fraction),
        "output_tokens": int(usage.get("output_tokens", 0)) + robot_audio,
        "output_audio_tokens": robot_audio,
        "_new_history_audio": owner_audio + robot_audio,
        "_robot_words": int(robot_words),
    }


def write_result(name: str, payload: Mapping[str, object]) -> Path:
    """One raw-rows file per harness, so RESULTS.md never carries a lone number."""

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULTS_DIR / name
    path.write_text(json.dumps(payload, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return path


__all__ = [
    "ACOUSTIC_DIR",
    "AUDIO_TOKENS_PER_MINUTE",
    "AUDIO_TOKENS_PER_SECOND",
    "CARDS",
    "CONVO_DIR",
    "DAYS_PER_MONTH",
    "LISTEN_HOURS_PER_DAY",
    "RESULTS_DIR",
    "Turn",
    "Utterance",
    "audio_row_from_text_row",
    "listening_usd_per_hour",
    "load_turns",
    "load_utterances",
    "measured_words_per_second",
    "price_rows",
    "write_result",
]
