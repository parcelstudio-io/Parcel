#!/usr/bin/env python3
"""Endpointing, measured: replay recorded utterances through each turn_detection arm.

CARD TURN-1, WORK ITEM 3 — AND WHAT IT REFUSES TO PRETEND
---------------------------------------------------------
Until this card, endpointing on the hosted lane was the string literal
``"server_vad"`` inside ``realtime/protocol.py``. It is now
``realtime.turn_detection`` in the config. A knob nobody measured is a
preference, so this script is the instrument: it takes the owner's recorded
utterances, sends the SAME audio through the SAME lane under each arm, and
reports the two numbers card TURN-1 pre-registered — commit latency and
mid-sentence commits — per arm, so the prototype default is chosen from data.

It cannot invent the recording and it does not try. ``--replay`` without one is
an exit code and the exact command the owner runs, never a synthetic number
standing in for a person's voice.

THE FOUR MODES
--------------
``--arms``    print each arm and the exact ``session.update`` it produces. No
              network, no recording, no credential. This is also the
              payload-identity evidence: the ``server_vad`` arm's frame is
              byte-identical to the one this repo has sent since 2026-08-18.
``--check``   run the offline acceptance rows (payload identity, ranges, enums,
              cross-key refusals, unknown keys) and exit non-zero on the first
              miss. Safe in CI; opens nothing.
``--plan``    write the recording protocol the owner follows: 20 two-clause
              utterances, each with a deliberate ~400 ms pause in the middle,
              plus the ``arecord`` line for the reSpeaker array.
``--replay``  the measurement. Streams each recorded WAV up a hosted session
              under one arm and reports the rows. Needs the recording AND
              ``--live`` AND ``OPENAI_API_KEY``: three separate yeses, because
              this is the only mode that spends money.

WHAT "MID-SENTENCE COMMIT" MEANS HERE, EXACTLY
----------------------------------------------
Each recording is ONE two-clause utterance. Correct endpointing therefore
produces exactly ONE turn commit for it. Two or more means the endpointer cut
the owner off at the pause and started answering half a sentence — which is the
defect this card exists to fix, and it is countable without anyone annotating
where the pause was. ``mid_sentence_commits`` is the number of recordings that
produced more than one commit.

Commit latency is measured in the AUDIO domain, not against a wall clock: the
provider reports ``audio_end_ms`` — its own index into the input buffer — and
this script computes the end of speech in the same stream from its energy
envelope. The difference is the endpointer's silence tail with the network,
this process, and the owner's ADSL taken out of it. The lane's wall-clock
milestones (``speech_stopped -> response.created``, ``-> first sink byte``) are
reported beside it from ``lane.snapshot()["turn_timings"]``.

THE INSTRUMENT'S DOMAIN IS 24 kHz, AND TWO THINGS FOLLOW FROM IT
----------------------------------------------------------------
The array records at 16 kHz and offers nothing else; the session declares no
``audio.input.format``, so the provider assumes its 24 kHz default, which is
also what the browser ear resamples to before it sends a frame. So this tool
resamples 16 -> 24 kHz before streaming (:func:`to_provider_rate`) — the same
linear interpolation the ear uses, applied to every arm equally. Without it the
corpus plays at 1.5x, the deliberate ~400 ms pause arrives as ~267 ms, and every
arm is flattered on the one row that decides the default.

``audio_end_ms`` indexes the WHOLE session's input buffer, not the current file.
Each result therefore carries ``audio_offset_ms`` — the audio already fed when
that file started — and the reported commit is ``raw - offset``. Both numbers
are in the report so the arithmetic can be checked from the file alone.

AND THE ORIGIN ITSELF IS AN OPEN QUESTION, SO THE REPORT CARRIES BOTH (card TRUTH-1)
------------------------------------------------------------------------------------
Nothing in this repository settles whether the provider indexes ``audio_end_ms``
in APPENDED AUDIO or in the session's WALL CLOCK. The stream is paced in real
time, so on any single file the two are the same number and no measurement can
tell them apart. What separates them is ``--settle-s``: after each file this
tool pumps for ``settle_s`` seconds, adding wall milliseconds and no audio
milliseconds, so by file *n* the two origins differ by roughly ``n * settle_s``.

So every row carries ``wall_offset_ms`` and ``wall_elapsed_ms`` beside
``audio_offset_ms``, plus ``commits_wall_relative_ms`` and
``commit_latency_wall_ms`` — the same commits resolved against the other origin
— and the report carries ``settle_s`` and ``wall_minus_audio_ms_max`` at the
top. TURN-1's handoff said the first live run could *detect* a wall-indexed
``audio_end_ms`` but not *correct* it. With both columns in the file it can do
both, from one run, without re-recording the owner.

USAGE
-----
    .parcel/bin/python tools/replay_turn_detection.py --arms
    .parcel/bin/python tools/replay_turn_detection.py --check
    .parcel/bin/python tools/replay_turn_detection.py --plan \
        --out ~/.cache/parcel-turn1/recording
    .parcel/bin/python tools/replay_turn_detection.py --replay --live \
        --recording ~/.cache/parcel-turn1/recording --arm semantic_auto \
        --out ~/.cache/parcel-turn1/results
"""

from __future__ import annotations

import argparse
import array
import json
import math
import statistics
import sys
import time
import wave
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
if str(REPO / "src") not in sys.path:  # pragma: no cover - script bootstrap
    sys.path.insert(0, str(REPO / "src"))

from parcel_robot.realtime.config import (
    RealtimeConfigError,
    realtime_config_from_mapping,
)
from parcel_robot.realtime.protocol import PCM16_SAMPLE_RATE_HZ, SessionUpdate

#: Report schema id. Versioned for the same reason the capture index is: the
#: status doc and any later comparison both read these files, and a silently
#: changed shape is a silently wrong comparison.
#: v2 (card TRUTH-1) adds ``settle_s``, ``wall_minus_audio_ms_max`` and the five
#: per-row wall columns. The bump costs nothing: ``--replay`` is owner-gated on a
#: recording that does not exist yet, so no v1 report has ever been written, and
#: a reader that finds v1 in the wild is reading something hand-made.
REPORT_SCHEMA = "parcel.turn1.replay.v2"

#: The arms card TURN-1 names: today's endpointer, and semantic VAD at each
#: eagerness. Each value is exactly what goes under ``turn_detection:`` in
#: ``configs/realtime.yaml`` — copy one across when the numbers pick a winner.
#:
#: ``interrupt_response`` is TRUE on every semantic arm on purpose: the lane
#: barges in locally the moment it hears ``speech_started`` and the provider
#: cancelling its own reply is the other half of that behaviour. An arm where
#: only one half fires would compare two things at once.
ARMS: dict[str, dict[str, Any]] = {
    # The control. NO KEYS AT ALL — not "the defaults spelled out", which would
    # be a different frame. This is the arm whose payload must stay identical.
    "server_vad_default": {},
    "semantic_low": {"type": "semantic_vad", "eagerness": "low", "interrupt_response": True},
    "semantic_auto": {"type": "semantic_vad", "eagerness": "auto", "interrupt_response": True},
    "semantic_high": {"type": "semantic_vad", "eagerness": "high", "interrupt_response": True},
}

#: The payload this repo has sent since 2026-08-18, and which the control arm
#: must still produce exactly. Pinned as a literal rather than recomputed so the
#: check cannot pass by comparing a bug to itself.
SERVER_VAD_PAYLOAD: dict[str, Any] = {"type": "server_vad"}

#: Card TURN-1's recording protocol. Two clauses, one deliberate pause in the
#: middle, ordinary household things to say to a dog-shaped robot. Twenty of
#: them because that is what the pre-registration grades a p50 on.
UTTERANCES: tuple[str, ...] = (
    "I was going to take you out this morning ... but it started raining again",
    "Can you go and look in the kitchen ... and tell me if I left the light on",
    "There's a box by the front door ... I think it came while I was asleep",
    "I want you to remember something ... my sister is coming on Thursday",
    "Follow me down the hall ... and then wait by the bedroom door",
    "It's getting dark in here ... do you want me to turn a lamp on",
    "I had a really long day ... and I don't feel like cooking anything",
    "Go and have a look around ... then come back and tell me what changed",
    "The plant on the windowsill ... has been looking sad for about a week",
    "If you hear the door ... don't run at whoever comes through it",
    "I'm going to be out until six ... so the house is yours until then",
    "That noise you made earlier ... was that you or was it the pipes",
    "Let's try that again slowly ... turn left and then stop at the rug",
    "My phone is somewhere in here ... probably down the side of the sofa",
    "You've been very quiet today ... is everything working properly",
    "I put your charger away ... it's in the drawer under the television",
    "When I say the word wait ... I want you to stop exactly where you are",
    "There's someone at the window ... no, it's just the neighbour's cat",
    "I'd like to show you something ... come round to this side of the table",
    "Before I forget completely ... remind me to call the landlord tomorrow",
)

#: RMS below this (16-bit full scale 32768) is silence for the purpose of
#: finding where the owner stopped talking. Deliberately generous: the array
#: has a noise floor and a threshold that is too tight reports the end of speech
#: early, which would flatter every arm equally but still be wrong.
SILENCE_RMS = 500

#: Analysis window for the energy envelope, and the frame size the replay
#: streams. 20 ms is the gateway's own frame; keeping them equal means the
#: end-of-speech index and the send index are in the same units.
FRAME_MS = 20

#: Sample rate the reSpeaker XVF3800 records at, and the ONLY rate it offers
#: (AIR-1: PortAudio answers PaErrorCode -9997 for 22 050, 24 000, 44 100 and
#: 48 000 Hz on ``hw:2,0``). ``record.sh`` therefore writes 16 kHz WAVs.
INPUT_RATE_HZ = 16_000

#: WHAT THE PROVIDER ACTUALLY HEARS, AND WHY THIS TOOL RESAMPLES.
#:
#: ``session.update`` declares ``audio.output.format`` and deliberately does NOT
#: declare ``audio.input.format`` — adding one would move the payload-identity
#: row this card is built on. So the provider applies its own default, which is
#: the same 24 kHz :data:`~parcel_robot.realtime.protocol.PCM16_SAMPLE_RATE_HZ`
#: the codec pins, and the product path agrees: the browser ear resamples the
#: capture device to 24 kHz in ``encodeMicFrame`` before a frame is ever sent.
#:
#: Feeding 16 kHz bytes up that pipe plays the corpus at 1.5x — the deliberate
#: ~400 ms mid-sentence pause arrives as ~267 ms and EVERY arm looks better at
#: not cutting the owner off than it is. The resample below is not a liberty
#: taken with the recording; it is the product path, done here because the array
#: cannot produce 24 kHz itself.
PROVIDER_RATE_HZ = PCM16_SAMPLE_RATE_HZ

#: Bytes of mono PCM16 per millisecond at the provider's rate: 48. This is the
#: divisor that turns ``audio_end_ms``'s buffer index into milliseconds and the
#: multiplier that sizes one 20 ms frame.
PROVIDER_BYTES_PER_MS = PROVIDER_RATE_HZ * 2 / 1000.0

#: The lane's arming gate refuses a falsy handshake token (``CODE_NO_HANDSHAKE``,
#: "a reachable service is not consent"), so a replay that passes ``None`` dies
#: at ``open_session`` before a single frame goes up. This is the token this
#: process presents to its OWN lane. It is not a credential and it is not the
#: panel's CSRF token: there is no HTTP server here and nothing else can reach
#: this lane. The gesture it stands in for is the owner typing ``--live``.
REPLAY_HANDSHAKE_TOKEN = "replay_turn_detection"


class ReplayRefusal(RuntimeError):
    """This tool will not proceed, and says why. Never a silent no-op."""


# ------------------------------------------------------------------ the arms
def arm_payload(name: str) -> dict[str, Any]:
    """The ``session.update`` frame one arm produces, whole."""

    if name not in ARMS:
        raise ReplayRefusal(f"unknown arm {name!r}; known: {', '.join(sorted(ARMS))}")
    body: dict[str, Any] = {"enabled": True}
    if ARMS[name]:
        body["turn_detection"] = dict(ARMS[name])
    config = realtime_config_from_mapping(body, source=f"arm:{name}")
    return SessionUpdate(
        instructions="<instructions>",
        model=config.model,
        voice=config.voice,
        turn_detection=config.turn_detection,
    ).to_payload()


def print_arms() -> int:
    """Every arm, its yaml block, and the frame it produces."""

    for name, block in ARMS.items():
        payload = arm_payload(name)
        detection = payload["session"]["audio"]["input"]["turn_detection"]
        print(f"\n=== {name} ===")
        print("configs/realtime.yaml:")
        if block:
            print("  turn_detection:")
            for key, value in block.items():
                print(f"    {key}: {json.dumps(value)}")
        else:
            print("  (no turn_detection: block at all — this is the control)")
        print(f"session.audio.input.turn_detection: {json.dumps(detection, sort_keys=True)}")
    print(f"\n{len(ARMS)} arms.")
    return 0


# --------------------------------------------------------- the offline rows
@dataclass
class CheckResult:
    """One offline acceptance row and whether it held."""

    row: str
    passed: bool
    detail: str = ""


def _refuses(body: dict[str, Any]) -> tuple[bool, str]:
    try:
        realtime_config_from_mapping({"turn_detection": body})
    except RealtimeConfigError as error:
        return True, str(error)
    return False, "accepted"


def offline_checks() -> list[CheckResult]:
    """Card TURN-1's rows T1 and T3-T6, as assertions this script can run.

    Deliberately duplicated from ``tests/test_turn1_endpointing.py`` rather than
    imported from it: the tests prove the code is right, and this proves the
    TOOL the owner will run is looking at the same code the tests are. A replay
    harness that has drifted from the product is how a measurement ends up
    describing something nobody ships.
    """

    results: list[CheckResult] = []

    control = arm_payload("server_vad_default")["session"]["audio"]["input"]["turn_detection"]
    results.append(
        CheckResult(
            "T1 payload identity: no turn_detection: block ⇒ {'type': 'server_vad'}",
            control == SERVER_VAD_PAYLOAD,
            json.dumps(control, sort_keys=True),
        )
    )

    bare = SessionUpdate(instructions="i", model="m", voice="v").to_payload()
    results.append(
        CheckResult(
            "T1 payload identity: SessionUpdate with no turn_detection argument",
            bare["session"]["audio"]["input"]["turn_detection"] == SERVER_VAD_PAYLOAD,
            json.dumps(bare["session"]["audio"]["input"]["turn_detection"], sort_keys=True),
        )
    )

    for value, expect_refusal in ((200, False), (800, False), (199, True), (801, True)):
        refused, detail = _refuses({"silence_duration_ms": value})
        results.append(
            CheckResult(
                f"T3 silence_duration_ms={value} "
                f"{'refused' if expect_refusal else 'accepted'}",
                refused is expect_refusal,
                detail,
            )
        )

    for body, expect_refusal in (
        ({"type": "semantic_vad"}, False),
        ({"type": "server_vad"}, False),
        ({"type": "sever_vad"}, True),
        ({"type": "semantic_vad", "eagerness": "medium"}, False),
        ({"type": "semantic_vad", "eagerness": "eager"}, True),
    ):
        refused, detail = _refuses(body)
        results.append(
            CheckResult(
                f"T4 enum {json.dumps(body, sort_keys=True)} "
                f"{'refused' if expect_refusal else 'accepted'}",
                refused is expect_refusal,
                detail,
            )
        )

    for body in (
        {"eagerness": "low"},
        {"type": "semantic_vad", "threshold": 0.5},
        {"type": "semantic_vad", "prefix_padding_ms": 300},
        {"type": "semantic_vad", "silence_duration_ms": 400},
    ):
        refused, detail = _refuses(body)
        results.append(
            CheckResult(
                f"T5 cross-key {json.dumps(body, sort_keys=True)} refused", refused, detail
            )
        )

    refused, detail = _refuses({"silence_durations_ms": 400})
    results.append(CheckResult("T6 unknown key inside turn_detection refused", refused, detail))

    return results


def run_checks() -> int:
    results = offline_checks()
    for result in results:
        mark = "ok  " if result.passed else "MISS"
        print(f"[{mark}] {result.row}")
        if not result.passed:
            print(f"       got: {result.detail}")
    misses = [r for r in results if not r.passed]
    print(f"\n{len(results) - len(misses)}/{len(results)} rows held.")
    return 1 if misses else 0


# ------------------------------------------------------------ the recording
def write_plan(out: Path) -> int:
    """The owner's ten minutes, written down. Card TURN-1, work item 3."""

    out.mkdir(parents=True, exist_ok=True)
    lines = ["id\tutterance"]
    lines += [f"{index:02d}\t{text}" for index, text in enumerate(UTTERANCES, start=1)]
    (out / "utterances.tsv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    script = f"""#!/usr/bin/env bash
# TURN-1 endpointing corpus — 20 two-clause utterances through the XVF3800.
# The '...' in each line is a DELIBERATE pause of about 400 ms: say the first
# clause, take a breath as if thinking, then say the second. That pause is the
# whole experiment — an endpointer that commits during it has cut you off.
set -euo pipefail
cd "$(dirname "$0")"
DEV="${{PARCEL_MIC_DEV:-plughw:2,0}}"
tail -n +2 utterances.tsv | while IFS=$'\\t' read -r id text; do
  out="${{id}}.wav"
  [ -f "$out" ] && {{ echo "[$id] already recorded"; continue; }}
  echo
  echo "[$id/20] SAY (pause ~400 ms at the ...):"
  echo "    $text"
  read -r -p "    Enter to record (8s), s+Enter to skip: " ans </dev/tty
  [ "$ans" = "s" ] && continue
  arecord -D "$DEV" -f S16_LE -r {INPUT_RATE_HZ} -c 1 -d 8 "$out" >/dev/null 2>&1
  echo "    saved $out"
done
echo
echo "Done. Now: replay_turn_detection.py --replay --live --recording $(pwd) --arm <arm>"
"""
    path = out / "record.sh"
    path.write_text(script, encoding="utf-8")
    path.chmod(0o755)
    print(f"wrote {out / 'utterances.tsv'} and {path}")
    print("\nOwner, ~10 minutes:")
    print(f"    {path}")
    print("Then one replay per arm (each is one hosted session, a few cents):")
    for name in ARMS:
        print(
            f"    .parcel/bin/python tools/replay_turn_detection.py --replay --live "
            f"--recording {out} --arm {name} --out {out.parent / 'results'}"
        )
    return 0


def load_recording(directory: Path) -> list[tuple[str, Path]]:
    """The recorded WAVs, in id order. Refuses rather than measuring nothing."""

    if not directory.is_dir():
        raise ReplayRefusal(
            f"no recording at {directory}. This row is OWNER-GATED: the numbers "
            f"cannot exist until the owner records the corpus. Run:\n"
            f"    .parcel/bin/python tools/replay_turn_detection.py --plan --out {directory}\n"
            f"    {directory / 'record.sh'}"
        )
    wavs = sorted(directory.glob("*.wav"))
    if not wavs:
        raise ReplayRefusal(
            f"{directory} has no .wav files. This row is OWNER-GATED; run "
            f"{directory / 'record.sh'} (about 10 minutes)."
        )
    return [(path.stem, path) for path in wavs]


def read_pcm(path: Path) -> bytes:
    """One recording as mono PCM16 at :data:`INPUT_RATE_HZ`, unconverted.

    A recording at any OTHER rate is refused rather than resampled: the array
    offers one rate, ``record.sh`` asks for it, and a file that is not 16 kHz
    was made some other way — which is a second variable in an experiment about
    milliseconds. The 16 -> 24 kHz step that follows is not that: it is the
    product path (see :data:`PROVIDER_RATE_HZ`), applied to every arm equally,
    and it happens in :func:`to_provider_rate` where it can be read.
    """

    with wave.open(str(path), "rb") as reader:
        if reader.getnchannels() != 1 or reader.getsampwidth() != 2:
            raise ReplayRefusal(
                f"{path.name}: expected mono PCM16, got {reader.getnchannels()} channel(s) "
                f"at {reader.getsampwidth() * 8}-bit"
            )
        if reader.getframerate() != INPUT_RATE_HZ:
            raise ReplayRefusal(
                f"{path.name}: recorded at {reader.getframerate()} Hz, expected "
                f"{INPUT_RATE_HZ}. Re-record with record.sh rather than resampling: "
                f"a resample is a second variable in an experiment about milliseconds."
            )
        return reader.readframes(reader.getnframes())


def to_provider_rate(pcm: bytes) -> bytes:
    """The array's 16 kHz mono PCM16, at the rate the provider assumes.

    Linear interpolation, deliberately the same arithmetic as the browser ear's
    ``encodeMicFrame`` (``ui/index.html``): the point of this tool is to measure
    the endpointer on the audio the PRODUCT would have sent it, so the harness
    must not sound better than the product. Anything fancier here would be a
    third thing that differs between the replay and a real conversation.
    """

    return resample_pcm16(pcm, from_rate=INPUT_RATE_HZ, to_rate=PROVIDER_RATE_HZ)


def resample_pcm16(pcm: bytes, *, from_rate: int, to_rate: int) -> bytes:
    """Linear-interpolate mono PCM16 between two rates. Same rate is a no-op."""

    if from_rate == to_rate or not pcm:
        return pcm
    source = array.array("h")
    source.frombytes(pcm[: len(pcm) - (len(pcm) % 2)])
    if not source:
        return b""
    ratio = from_rate / to_rate
    count = int(len(source) / ratio)
    out = array.array("h", bytes(count * 2))
    last = len(source) - 1
    for index in range(count):
        position = index * ratio
        low = int(position)
        high = min(low + 1, last)
        blend = position - low
        value = source[low] * (1.0 - blend) + source[high] * blend
        out[index] = max(-32_768, min(32_767, round(value)))
    return out.tobytes()


def _window_rms(window: bytes) -> float:
    """RMS of one PCM16 window. Was ``audioop.rms``; that module left in 3.13.

    Twelve lines of arithmetic rather than a numpy dependency in a tool the
    owner runs from a shell: this file must import on any Python that can run
    the lane, and the analysis is one pass over eight seconds of 16 kHz mono.
    """

    if not window:
        return 0.0
    samples = array.array("h")
    samples.frombytes(window[: len(window) - (len(window) % 2)])
    if not samples:
        return 0.0
    return math.sqrt(sum(float(s) * float(s) for s in samples) / len(samples))


def end_of_speech_ms(pcm: bytes, *, rate_hz: int) -> float:
    """Where the owner actually stopped talking, in ms from the file's start.

    The last analysis window whose RMS is above :data:`SILENCE_RMS`. Returns the
    file's full length when nothing is ever above the floor, which reads as
    "this recording is silence" in the report instead of as a suspiciously fast
    commit.

    ``rate_hz`` is REQUIRED and has no default. This number is subtracted from
    the provider's ``audio_end_ms``, which is indexed in the provider's own
    24 kHz buffer; computing it against the array's 16 kHz stream instead would
    put a 1.5x error into every latency the card grades, silently.
    """

    step = int(rate_hz * FRAME_MS / 1000) * 2
    bytes_per_ms = rate_hz * 2 / 1000.0
    last_loud = 0
    for index in range(0, max(0, len(pcm) - step + 1), step):
        if _window_rms(pcm[index : index + step]) >= SILENCE_RMS:
            last_loud = index + step
    if last_loud == 0:
        return len(pcm) / bytes_per_ms
    return last_loud / bytes_per_ms


# ------------------------------------------------------------- the measurement
@dataclass
class UtteranceResult:
    """What one recording did under one arm."""

    utterance_id: str
    end_of_speech_ms: float
    #: ``audio_end_ms`` values the provider reported, made FILE-RELATIVE by
    #: subtracting :attr:`audio_offset_ms`. The raw values are kept beside them.
    commits: list[float] = field(default_factory=list)
    #: Milliseconds of audio this session had already been fed when this file
    #: started. ``audio_end_ms`` indexes the whole session's input buffer, so
    #: without this every file after the first reports a latency that includes
    #: every file before it.
    audio_offset_ms: float = 0.0
    #: WALL milliseconds since ``open_session`` returned, when this file's first
    #: frame went out — and when its settle window closed. Card TRUTH-1, from
    #: TURN-1's handoff: nothing in this repo settles whether the provider's
    #: ``audio_end_ms`` indexes APPENDED AUDIO or the session's WALL CLOCK, and
    #: the two are indistinguishable in a single-file report because the stream
    #: is paced in real time. They separate as soon as there is a second file:
    #: every settle window adds wall milliseconds and no audio milliseconds, so
    #: ``wall_offset_ms - audio_offset_ms`` grows by roughly ``settle_s`` per
    #: file. With both offsets in the report the first live run can DETECT which
    #: index the provider used and CORRECT the latency without re-recording —
    #: which is exactly what the report could not do before.
    wall_offset_ms: float = 0.0
    wall_elapsed_ms: float = 0.0
    commits_raw: list[int] = field(default_factory=list)
    commit_latency_ms: float | None = None
    response_created_ms: float | None = None
    first_audio_ms: float | None = None
    truncations: int = 0

    @property
    def mid_sentence(self) -> bool:
        """More than one commit for ONE two-clause utterance: it cut in."""

        return len(self.commits) > 1

    @property
    def wall_minus_audio_ms(self) -> float:
        """How far the two candidate origins have diverged by this file.

        Near zero on the first file whatever the truth is. If it is still near
        zero on the last file, the settle windows are not landing where this
        harness thinks they are and neither hypothesis is testable from the run.
        """

        return self.wall_offset_ms - self.audio_offset_ms

    @property
    def commits_wall_relative(self) -> list[float]:
        """The same raw commits, made file-relative against the WALL origin.

        The correction half. If the live run shows the provider indexing wall
        time, these are the numbers, and ``commit_latency_wall_ms`` is the row.
        """

        return [value - self.wall_offset_ms for value in self.commits_raw]

    @property
    def commit_latency_wall_ms(self) -> float | None:
        """:attr:`commit_latency_ms` computed against the wall origin instead."""

        if not self.commits_raw:
            return None
        return round(self.commits_wall_relative[0] - self.end_of_speech_ms, 1)

    def as_dict(self) -> dict[str, Any]:
        return {
            "utterance_id": self.utterance_id,
            "end_of_speech_ms": round(self.end_of_speech_ms, 1),
            "commits": [round(float(c), 1) for c in self.commits],
            # Published so the arithmetic above is auditable from the report
            # alone: file-relative commit = raw - offset.
            "commits_raw_ms": list(self.commits_raw),
            "audio_offset_ms": round(self.audio_offset_ms, 1),
            # Card TRUTH-1: the second candidate origin, published beside the
            # first so the arithmetic for BOTH hypotheses is in the file. See
            # `wall_offset_ms` for what separates them.
            "wall_offset_ms": round(self.wall_offset_ms, 1),
            "wall_elapsed_ms": round(self.wall_elapsed_ms, 1),
            "wall_minus_audio_ms": round(self.wall_minus_audio_ms, 1),
            "commits_wall_relative_ms": [round(c, 1) for c in self.commits_wall_relative],
            "commit_latency_wall_ms": self.commit_latency_wall_ms,
            "commit_latency_ms": self.commit_latency_ms,
            "response_created_ms": self.response_created_ms,
            "first_audio_ms": self.first_audio_ms,
            "truncations": self.truncations,
            "mid_sentence": self.mid_sentence,
        }


def summarise(arm: str, results: list[UtteranceResult]) -> dict[str, Any]:
    """The pre-registered rows, computed. Card TURN-1 G1/G2/G3.

    ``mid_sentence_commits`` is not optional and is not derived at read time by
    whoever writes the status doc: it is a field of the report, because the row
    it grades ("0/20 mid-sentence commits") is exactly the one a tired reporter
    would forget to include.
    """

    latencies = [r.commit_latency_ms for r in results if r.commit_latency_ms is not None]
    created = [r.response_created_ms for r in results if r.response_created_ms is not None]
    audio = [r.first_audio_ms for r in results if r.first_audio_ms is not None]
    return {
        "arm": arm,
        "turn_detection": arm_payload(arm)["session"]["audio"]["input"]["turn_detection"],
        # The domain every millisecond in this report lives in. Recorded because
        # the corpus is 16 kHz and the measurement is not.
        "analysis_rate_hz": PROVIDER_RATE_HZ,
        "recorded_rate_hz": INPUT_RATE_HZ,
        "utterances": len(results),
        "commit_latency_p50_ms": round(statistics.median(latencies), 1) if latencies else None,
        "commit_latency_p95_ms": (
            round(sorted(latencies)[int(0.95 * (len(latencies) - 1))], 1) if latencies else None
        ),
        "response_created_p50_ms": round(statistics.median(created), 1) if created else None,
        "first_audio_p50_ms": round(statistics.median(audio), 1) if audio else None,
        # G2. The row that decides whether the arm is usable at all.
        "mid_sentence_commits": sum(1 for r in results if r.mid_sentence),
        # G3. Present so a replay that silently stopped barging in is visible.
        "truncations": sum(r.truncations for r in results),
        "utterance_rows": [r.as_dict() for r in results],
    }


def _build_live_lane(arm: str, *, port_note: str = "") -> Any:
    """One lane on a real socket under one arm. Imported late, on purpose.

    ``ws_transport`` reaches the network. Keeping the import inside the only
    function that opens a session means ``--arms``, ``--check`` and ``--plan``
    never import it, which is the same rule ``voice_tier_ab.py`` states as
    "there is no provider client in this file".

    **Card TRUTH-1 corrects the older, wider claim.** This docstring used to
    extend the guarantee to ``lane`` as well, and that half was false — the
    claim is described rather than reproduced here, because the way a stale
    claim is kept dead is a grep for it. Every mode does reach ``lane``:
    the module-level ``from parcel_robot.realtime.config import ...`` executes
    ``parcel_robot.realtime.__init__``, which imports ``lane``, so
    ``parcel_robot.realtime.lane`` is in ``sys.modules`` for every mode
    (measured 2026-08-22: ``--arms`` → lane True, ws_transport False).
    ``ws_transport`` is the property that matters and the only one claimed here:
    importing ``lane`` opens nothing; importing ``ws_transport`` is what puts a
    websocket client in the process.
    """

    from parcel_robot.realtime.lane import RealtimeLane
    from parcel_robot.realtime.ws_transport import WebSocketTransport

    body: dict[str, Any] = {"enabled": True, "mode": "audio"}
    if ARMS[arm]:
        body["turn_detection"] = dict(ARMS[arm])
    config = realtime_config_from_mapping(body, source=f"arm:{arm}{port_note}")
    return RealtimeLane(
        config=config,
        instructions=(
            "You are a companion robot in a replay harness. Answer each thing you "
            "hear in one short sentence. Do not ask questions."
        ),
        transport_factory=lambda: WebSocketTransport(model=config.model).open(),
        sink_factory=_NullSink,
    )


class _NullSink:
    """A speaker that throws the audio away but keeps the timing honest.

    The replay measures WHEN the first byte reached the sink, not what it
    sounded like, and a real ``SpeakerSink`` here would put the robot's replies
    through the owner's speakers twenty times in a row while they are trying to
    listen for their own recordings.
    """

    def __init__(self) -> None:
        self.first_chunk_started_monotonic: float | None = None
        self.chunks = 0

    def begin_utterance(self) -> None:
        self.first_chunk_started_monotonic = None

    def enqueue(self, chunk: bytes, token: object = None) -> None:
        del token
        self.chunks += 1
        if self.first_chunk_started_monotonic is None:
            self.first_chunk_started_monotonic = time.monotonic()

    def interrupt(self) -> None:
        self.first_chunk_started_monotonic = None


def _live_failure_types() -> tuple[type[BaseException], ...]:
    """Exceptions a hosted attempt raises, resolved lazily.

    Imported here rather than at the top of the file for exactly the reason
    :func:`_build_live_lane` imports late: ``ws_transport`` is the module that
    can reach a socket, and ``--arms`` / ``--check`` / ``--plan`` never import
    it. Card TRUTH-1: ``lane`` is NOT in that claim — the realtime package's
    ``__init__`` imports it, so every mode of this tool already has it in
    ``sys.modules``, and saying otherwise made a true, checkable property look
    like a broken one. ``RealtimeAuthError``, ``RealtimeConnectError`` and
    ``RealtimeQuotaError`` are all subclasses of ``RealtimeTransportError`` and
    are covered by naming the base.
    """

    try:
        from parcel_robot.realtime.lane import RealtimeLaneError
        from parcel_robot.realtime.ws_transport import RealtimeTransportError
    except ImportError:  # pragma: no cover - a build without the transport
        return ()
    return (RealtimeLaneError, RealtimeTransportError)


def replay(
    *,
    arm: str,
    recording: Path,
    live: bool,
    settle_s: float,
    out: Path | None,
    build_lane: Callable[[str], Any] | None = None,
) -> int:
    """Stream every recording up one arm and report. The only mode that spends.

    ``build_lane`` is injectable so the harness itself can be tested end to end
    against an in-process transport — the arming, the session frame, the frame
    size and the per-file arithmetic are all things that were wrong once and
    would not have been caught by testing the pieces separately. It defaults to
    :func:`_build_live_lane`, the only thing that opens a socket.
    """

    if arm not in ARMS:
        raise ReplayRefusal(f"unknown arm {arm!r}; known: {', '.join(sorted(ARMS))}")
    files = load_recording(recording)
    if not live:
        raise ReplayRefusal(
            f"{len(files)} recording(s) found and the arm validates, but --replay "
            f"measures the PROVIDER's endpointer and that needs a hosted session. "
            f"Re-run with --live once you mean to spend a few cents:\n"
            f"    .parcel/bin/python tools/replay_turn_detection.py --replay --live "
            f"--recording {recording} --arm {arm}"
        )

    lane = (build_lane or _build_live_lane)(arm)
    results: list[UtteranceResult] = []
    #: One 20 ms frame AT THE PROVIDER'S RATE — 960 bytes, not 640. The stream
    #: is resampled before it is paced, so a frame is 20 ms of wall clock and
    #: 20 ms of audio at the same time.
    frame_bytes = int(PROVIDER_RATE_HZ * FRAME_MS / 1000) * 2
    # The lane refuses a falsy handshake token outright; see the constant.
    lane.open_session(handshake_token=REPLAY_HANDSHAKE_TOKEN, mic_gesture=True)
    #: Card TRUTH-1: the WALL origin, taken the instant the session is open.
    #: Everything wall-indexed in the report is measured from here, so the two
    #: candidate origins for ``audio_end_ms`` share a zero and can be compared.
    session_opened_at = time.monotonic()
    #: Milliseconds of audio fed to THIS session so far. ``audio_end_ms`` is an
    #: index into the session's whole input buffer, so this is what makes a
    #: per-file latency a per-file latency.
    audio_sent_ms = 0.0
    try:
        for utterance_id, path in files:
            stream = to_provider_rate(read_pcm(path))
            offset_ms = audio_sent_ms
            wall_offset_ms = (time.monotonic() - session_opened_at) * 1000.0
            before_commits = len(lane.turn_timings)
            before_truncations = len(lane.truncations)
            for index in range(0, len(stream), frame_bytes):
                frame = stream[index : index + frame_bytes]
                lane.send_audio(frame)
                audio_sent_ms += len(frame) / PROVIDER_BYTES_PER_MS
                lane.pump()
                # Real time, on purpose: the provider's endpointer is a function
                # of how the audio ARRIVES. Firing eight seconds of frames in
                # eighty milliseconds measures nothing about a silence tail.
                time.sleep(FRAME_MS / 1000.0)
            deadline = time.monotonic() + settle_s
            while time.monotonic() < deadline:
                lane.pump()
                time.sleep(0.02)
            rows = lane.turn_timings[before_commits:]
            raw = [int(row.get("audio_end_ms") or 0) for row in rows]
            result = UtteranceResult(
                utterance_id=utterance_id,
                # On the 24 kHz stream, because that is the buffer the provider
                # indexes ``audio_end_ms`` into.
                end_of_speech_ms=end_of_speech_ms(stream, rate_hz=PROVIDER_RATE_HZ),
                commits=[value - offset_ms for value in raw],
                audio_offset_ms=offset_ms,
                wall_offset_ms=wall_offset_ms,
                wall_elapsed_ms=(time.monotonic() - session_opened_at) * 1000.0,
                commits_raw=raw,
                truncations=len(lane.truncations) - before_truncations,
            )
            if rows:
                first = rows[0]
                result.commit_latency_ms = round(
                    (float(first.get("audio_end_ms") or 0) - offset_ms)
                    - result.end_of_speech_ms,
                    1,
                )
                created = first.get("response_created_ms")
                audio = first.get("first_audio_ms")
                result.response_created_ms = None if created is None else float(created)
                result.first_audio_ms = None if audio is None else float(audio)
            results.append(result)
            print(
                f"[{utterance_id}] commits={len(result.commits)} "
                f"latency={result.commit_latency_ms} ms "
                f"created={result.response_created_ms} ms"
            )
    finally:
        lane.close()

    report = {
        "schema": REPORT_SCHEMA,
        "recording": str(recording),
        "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        # Card TRUTH-1. `settle_s` is a FIELD, not a flag someone remembers to
        # write down, because it is the whole reason the wall clock and the
        # appended-audio clock separate: each file's settle window adds wall
        # milliseconds and no audio. A report without it cannot be read for the
        # `audio_end_ms` question at all, and a reader cannot tell the answer
        # from a report that simply used a different value.
        "settle_s": settle_s,
        "wall_minus_audio_ms_max": (
            round(max((r.wall_minus_audio_ms for r in results), default=0.0), 1)
        ),
        **summarise(arm, results),
    }
    text = json.dumps(report, indent=2, sort_keys=False)
    if out is not None:
        out.mkdir(parents=True, exist_ok=True)
        target = out / f"{arm}.json"
        target.write_text(text + "\n", encoding="utf-8")
        print(f"\nwrote {target}")
    print(
        f"\narm={arm} p50={report['commit_latency_p50_ms']} ms "
        f"mid_sentence_commits={report['mid_sentence_commits']}/{report['utterances']} "
        f"truncations={report['truncations']}"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--arms", action="store_true", help="print each arm and its frame")
    mode.add_argument("--check", action="store_true", help="run the offline acceptance rows")
    mode.add_argument("--plan", action="store_true", help="write the recording protocol")
    mode.add_argument("--replay", action="store_true", help="measure one arm (needs --live)")
    parser.add_argument("--arm", default="server_vad_default", help="which arm to replay")
    parser.add_argument("--recording", type=Path, help="directory of recorded WAVs")
    parser.add_argument("--out", type=Path, help="where to write the plan or the report")
    parser.add_argument(
        "--live",
        action="store_true",
        help="actually open a hosted session (spends money); --replay refuses without it",
    )
    parser.add_argument(
        "--settle-s",
        type=float,
        default=6.0,
        help="seconds to keep pumping after each recording, waiting for the answer",
    )
    args = parser.parse_args(argv)

    try:
        if args.arms:
            return print_arms()
        if args.check:
            return run_checks()
        if args.plan:
            if args.out is None:
                raise ReplayRefusal("--plan needs --out <dir>")
            return write_plan(args.out)
        if args.recording is None:
            raise ReplayRefusal("--replay needs --recording <dir>")
        try:
            return replay(
                arm=args.arm,
                recording=args.recording,
                live=args.live,
                settle_s=args.settle_s,
                out=args.out,
            )
        except _live_failure_types() as error:
            # A lane that refuses to arm, a socket that will not open, a key
            # the provider rejects, a quota. All of them are "this run produced
            # no measurement, here is why" — an exit code and a sentence, not a
            # traceback the owner has to read backwards at the end of a
            # ten-minute recording session.
            raise ReplayRefusal(
                f"the hosted session could not be used: {type(error).__name__}: {error}"
            ) from error
    except (ReplayRefusal, RealtimeConfigError) as error:
        print(f"refused: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover - script entry
    raise SystemExit(main())
