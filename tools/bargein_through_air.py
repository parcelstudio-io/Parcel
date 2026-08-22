#!/usr/bin/env python
"""Card AIR-1 — the through-air scorecard the week-3 purchase gate reads.

    tools/bargein_through_air.py \
        --capture recordings/<monologue-session> \
        --tv-capture recordings/<tv-session> \
        --events recordings/<monologue-session>/events.jsonl \
        --erle erle_report.json --probe probe.json --spend recordings/spend.jsonl \
        --out AIR1_SCORECARD.json

(``capture.dir`` resolves against the REPO ROOT, not the current directory and
not ``~/.local/share`` — ``realtime/config.resolve_capture_dir``. The default is
``recordings/``, with ``spend.jsonl`` a sibling of the per-session folders.)

WHAT IT IS
----------
An assembler, not a driver. The owner runs the session in the browser; this
reads what the session left behind — the R17 capture tee, the ERLE report, the
array probe, the spend ledger — and reduces it to seven rows with one threshold
each. Every threshold is pre-registered in :data:`ROWS` and
:func:`verify_scorecard` refuses a card whose thresholds do not match, because a
scorecard that can move its own goalposts is not evidence of anything.

THE ONE METRIC THE TEE GIVES FOR FREE
-------------------------------------
During a monologue with the owner silent, a robot utterance marked
``interrupted`` in ``index.json`` can only have been interrupted by the robot's
own echo. So the false-barge-in rate is ``interrupted / utterances`` over that
session, and the owner's silence is *checked* rather than assumed: the tool
reports ``owner.wav``'s own level and refuses to score the arm if the owner
stream carries speech-level energy.

THE METRIC THE TEE NOW STAMPS — AND THE HALF IT STILL ESTIMATES
--------------------------------------------------------------
Interrupt latency used to be unmeasurable here and it is now half measured, so
read the row's own ``n`` before believing it.

* **The interrupt instant is on disk.** MARK-1's correction pass made
  ``SessionAudioCapture.mark_interrupted`` write ``interrupted_at`` (the wall
  clock ``_offer`` read on the RELAY thread, i.e. when ``interrupt()`` actually
  ran) together with ``interrupted_byte`` and ``interrupted_t_s`` (where in
  ``robot.wav`` the reply stopped). This tool reads them. The handoff that used
  to stand here — "``note_interrupt`` queues a wall stamp and
  ``mark_interrupted`` throws it away" — is **closed**, and it was the half that
  could only be fixed in a product file this card does not own.
* **The onset instant is still an estimate.**
  ``input_audio_buffer.speech_started`` is not in
  ``protocol.RETAINED_EVENT_TYPES``, so the provider's own view of "the owner
  started talking" reaches no file. What the tee has instead is the OWNER
  stream's segmentation: a new ``owner_turn`` segment opens on the first
  microphone frame that follows ``owner_gap_s`` (0.75 s) of silence, and that
  frame is the gateway's view of a burst starting. It is later than the
  acoustic onset by the browser's encode-and-send latency and earlier than the
  provider's VAD decision, so a median built on it is a **bound, not a
  measurement**, and the scorecard says so in the row's mechanism.

``robot.wav`` is still no clock — the tee records what the gateway was asked to
play, which arrives faster than real time — so ``interrupted_t_s`` is used as a
position in the reply, never as a time. With neither an ``--events`` file nor a
capture that carries both halves, the row is **unmeasured with the precise
reason**, never a number.

READ-ONLY. It opens WAVs and JSON for reading and writes exactly one file: the
scorecard you name with ``--out``.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import wave
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "tools") not in sys.path:  # pragma: no cover - script entry
    sys.path.insert(0, str(REPO_ROOT / "tools"))

from xvf3800_probe import dbfs

SCORECARD_SCHEMA = "parcel.air1.scorecard.v1"

#: A verdict is one of these three, and "unmeasured" is a first-class answer.
VERDICTS: frozenset[str] = frozenset({"pass", "fail", "unmeasured"})

#: What ``tools/measure_erle.py --report`` writes, and the only verdicts it may
#: hand over. Checked rather than assumed: a mapping with no ``verdict`` key at
#: all was, until this was written, "not the literal string 'unmeasured'" and
#: therefore trusted — which is how an empty dict becomes a passing row.
ERLE_REPORT_SCHEMA = "parcel.air1.erle_report.v1"
ERLE_REPORT_VERDICTS: frozenset[str] = frozenset({"pass", "pass_lower_bound", "fail"})

#: THE TWO ROWS NOTHING IN THIS TREE CAN PRODUCE YET.
#:
#: Both need per-turn identity attribution with a WALL timestamp: which turns
#: the robot credited to the owner, and whether the sound that produced each one
#: was actually the owner. The runtime keeps exactly that — ``_stamp_speaker_label``
#: writes ``{"at_s", "speaker", "session_id", "item_id", **label}`` into a 400-row
#: ring readable through ``ChassisRuntime.speaker_label_rows()`` — but the ring is
#: not on ``/api/state``, nothing writes it to disk, and ``at_s`` is
#: ``time.monotonic()``, which cannot be joined to the capture's wall clock. The
#: evidence log carries no identity rows either. ``runtime.py`` is another card's
#: file, so AIR-1 files the schema as a handoff instead of writing it, and these
#: two rows are OWNER-GATED ON A TOOL THAT DOES NOT EXIST YET rather than
#: quietly "unmeasured".
MISSING_TURN_PRODUCER = (
    "no producer exists in this tree: per-turn identity attribution is kept in "
    "ChassisRuntime._speaker_labels (readable via speaker_label_rows()) but is not "
    "exposed on /api/state, never written to disk, and stamped with time.monotonic() "
    "rather than a wall clock, so it cannot be joined to the capture. See handoff "
    "RT-TURNS-1 in AIR1_STATUS.md. This row is OWNER-GATED ON A TOOL THAT DOES NOT "
    "EXIST YET, not merely unmeasured."
)

#: Above this frame level the owner stream is carrying speech, not room tone.
#: Used only to CHECK the silent arm was silent; never to detect turns.
OWNER_SILENCE_DBFS = -45.0

#: What fraction of frames has to be that loud before "somebody was talking" is
#: the better explanation than "a door closed". 2 % of a ten-minute arm is
#: twelve seconds of speech-level energy.
OWNER_SPEECH_FRACTION = 0.02


@dataclass(frozen=True)
class Row:
    """One pre-registered acceptance row. The thresholds are the card's."""

    row_id: str
    unit: str
    direction: str  # "max" — lower is better; "min" — higher is better
    threshold: float
    minimum_n: int
    what: str


#: THE PRE-REGISTERED ROWS (card task_25 "Pre-registered acceptance"). Frozen
#: here so the tool cannot quietly grade itself against a kinder number later.
ROWS: tuple[Row, ...] = (
    Row("erle_db", "dB", "min", 20.0, 0,
        "echo return loss enhancement at 1 m at normal level"),
    Row("robot_utterances_as_owner_turns", "turns", "max", 0.0, 20,
        "robot utterances transcribed as owner turns, out of 20"),
    Row("interrupt_p50_s", "s", "max", 0.52, 20,
        "inbound speech onset to sink.interrupt, median of 20"),
    Row("false_barge_in_rate", "fraction", "max", 0.02, 1,
        "utterances self-interrupted during a 10-min monologue, owner silent"),
    Row("tv_owner_attributed_turns", "turns", "max", 0.0, 0,
        "owner-attributed turns in a 10-min TV arm"),
    Row("doa_ok_fraction", "fraction", "min", 0.95, 100,
        "DOA_VALUE reads that succeeded"),
    Row("hosted_spend_usd", "usd", "max", 2.0, 0,
        "hosted spend for the whole session"),
)

ROWS_BY_ID: dict[str, Row] = {row.row_id: row for row in ROWS}
ROW_IDS: frozenset[str] = frozenset(ROWS_BY_ID)


# ================================================================ the schema
def verdict_for(row: Row, value: float | None) -> str:
    """The only place a verdict is decided. Comparison, not judgement."""

    if value is None:
        return "unmeasured"
    number = float(value)
    if not math.isfinite(number):
        return "unmeasured"
    if row.direction == "max":
        return "pass" if number <= row.threshold else "fail"
    return "pass" if number >= row.threshold else "fail"


def make_row(row_id: str, value: float | None, *, n: int = 0,
             evidence: Sequence[str] = (), mechanism: str = "",
             unmeasured_reason: str = "", override_reason: str = "") -> dict[str, Any]:
    """Build one scorecard row with its verdict already derived from its value.

    ``override_reason`` is the ONE way a verdict may disagree with its own
    value, and it only ever goes downward: a row whose number is inside the gate
    can still be called a **fail** when the session carried a fault the number
    does not see (the standing example is speech-level echo in the microphone
    stream — the false-barge-in count can be zero and the arm still be a
    failure). The reverse — a pass the value does not support — has no spelling
    here and is refused by :func:`verify_scorecard`.
    """

    row = ROWS_BY_ID[row_id]
    verdict = verdict_for(row, value)
    if override_reason and verdict == "pass":
        verdict = "fail"
    elif override_reason and verdict == "unmeasured":
        raise ValueError(f"{row_id}: cannot override a row that has no value")
    if verdict == "unmeasured" and not unmeasured_reason:
        unmeasured_reason = "no evidence was supplied for this row"
    return {
        "id": row.row_id,
        "what": row.what,
        "unit": row.unit,
        "direction": row.direction,
        "threshold": row.threshold,
        "minimum_n": row.minimum_n,
        "n": int(n),
        "value": None if verdict == "unmeasured" else round(float(value), 6),
        "verdict": verdict,
        "evidence": [str(item) for item in evidence],
        "mechanism": mechanism,
        "override_reason": override_reason,
        "unmeasured_reason": unmeasured_reason if verdict == "unmeasured" else "",
    }


def verify_scorecard(card: Any) -> list[str]:
    """Check a scorecard against its own invariants. Empty list ⇒ it holds.

    Six ways a scorecard can lie, and this is the list of them:

    1. it is not the schema the gate reads;
    2. a row is missing, duplicated, or invented;
    3. a threshold or direction was edited — the goalposts moved;
    4. a verdict does not follow from its own value;
    5. a ``pass`` cites no evidence, or an ``unmeasured`` gives no reason;
    6. a row claims a median of twenty from four samples.
    """

    problems: list[str] = []
    if not isinstance(card, Mapping):
        return [f"scorecard is {type(card).__name__}, not a mapping"]
    if card.get("schema") != SCORECARD_SCHEMA:
        problems.append(f"schema is {card.get('schema')!r}, expected {SCORECARD_SCHEMA!r}")
    rows = card.get("rows")
    if not isinstance(rows, list):
        return problems + [f"rows is {type(rows).__name__}, not a list"]

    seen: dict[str, int] = {}
    for position, entry in enumerate(rows):
        if not isinstance(entry, Mapping):
            problems.append(f"row {position} is {type(entry).__name__}, not a mapping")
            continue
        row_id = entry.get("id")
        if row_id not in ROWS_BY_ID:
            problems.append(f"row {position}: unknown row id {row_id!r}")
            continue
        seen[str(row_id)] = seen.get(str(row_id), 0) + 1
        expected = ROWS_BY_ID[str(row_id)]

        if entry.get("direction") != expected.direction:
            problems.append(
                f"{row_id}: direction is {entry.get('direction')!r}, pre-registered "
                f"{expected.direction!r}"
            )
        threshold = entry.get("threshold")
        if not isinstance(threshold, (int, float)) or isinstance(threshold, bool):
            problems.append(f"{row_id}: threshold is {threshold!r}, not a number")
        elif float(threshold) != expected.threshold:
            problems.append(
                f"{row_id}: threshold is {threshold}, pre-registered {expected.threshold} — "
                "the goalposts moved"
            )
        if entry.get("unit") != expected.unit:
            problems.append(f"{row_id}: unit is {entry.get('unit')!r}, expected {expected.unit!r}")

        verdict = entry.get("verdict")
        if verdict not in VERDICTS:
            problems.append(f"{row_id}: verdict is {verdict!r}, not one of {sorted(VERDICTS)}")
            continue
        value = entry.get("value")
        if verdict == "unmeasured":
            if value is not None:
                problems.append(f"{row_id}: unmeasured but carries the value {value!r}")
            if not str(entry.get("unmeasured_reason", "")).strip():
                problems.append(f"{row_id}: unmeasured with no reason — say what is missing")
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            problems.append(f"{row_id}: verdict {verdict} with value {value!r}")
            continue
        if not math.isfinite(float(value)):
            problems.append(f"{row_id}: verdict {verdict} with non-finite value {value!r}")
            continue
        derived = verdict_for(expected, float(value))
        override = str(entry.get("override_reason", "")).strip()
        if derived != verdict:
            # Worse than the number says is always allowed, with a reason.
            # Better than the number says is never allowed, with or without one.
            downgrade = derived == "pass" and verdict == "fail"
            if not downgrade:
                problems.append(
                    f"{row_id}: verdict {verdict!r} but {value} vs {expected.direction} "
                    f"{expected.threshold} is {derived!r}"
                )
            elif not override:
                problems.append(
                    f"{row_id}: called a fail although {value} is inside the gate, with no "
                    "override_reason — say what the number did not see"
                )
        elif override and verdict != "fail":
            problems.append(
                f"{row_id}: carries an override_reason but its verdict is {verdict!r}; "
                "an override only ever makes a row worse"
            )
        evidence = entry.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            problems.append(f"{row_id}: verdict {verdict} cites no evidence")
        count = entry.get("n")
        if not isinstance(count, int) or isinstance(count, bool):
            problems.append(f"{row_id}: n is {count!r}, not an integer")
        elif count < expected.minimum_n:
            problems.append(
                f"{row_id}: n={count} but this row is only meaningful at "
                f"n>={expected.minimum_n}"
            )
        if verdict == "fail" and not str(entry.get("mechanism", "")).strip():
            problems.append(
                f"{row_id}: a miss with no mechanism — say why it missed (clipping, "
                "AEC3 double-cancel, downmix)"
            )
        if verdict != "fail" and str(entry.get("mechanism", "")).strip():
            # A mechanism is an explanation of a miss. Carried on a passing row
            # it is either stale or decorative, and it is what makes the
            # "a miss must name its mechanism" check vacuous when a builder
            # fills the field unconditionally.
            problems.append(
                f"{row_id}: verdict {verdict} carries a mechanism; mechanisms explain misses"
            )

    for row_id in sorted(ROW_IDS - set(seen)):
        problems.append(f"missing pre-registered row {row_id!r}")
    for row_id, count in sorted(seen.items()):
        if count > 1:
            problems.append(f"row {row_id!r} appears {count} times")
    return problems


def summarise_scorecard(card: Mapping[str, Any]) -> dict[str, int]:
    counts = {"pass": 0, "fail": 0, "unmeasured": 0}
    for entry in card.get("rows", ()):
        verdict = str(entry.get("verdict", "unmeasured"))
        if verdict in counts:
            counts[verdict] += 1
    return counts


# ================================================================ the sources
def read_index(session_dir: Path) -> dict[str, Any]:
    path = Path(session_dir) / "index.json"
    return json.loads(path.read_text(encoding="utf-8"))


def wav_frame_levels(path: Path, *, frame_ms: int = 20) -> np.ndarray:
    """Per-frame RMS of a PCM16 WAV, in int16 counts."""

    with wave.open(str(path), "rb") as handle:
        channels = handle.getnchannels()
        rate = handle.getframerate()
        raw = handle.readframes(handle.getnframes())
    samples = np.frombuffer(raw, dtype=np.int16).astype(np.float64)
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)
    size = max(1, int(rate * frame_ms / 1000))
    usable = (samples.size // size) * size
    if usable == 0:
        return np.zeros(0, dtype=np.float64)
    return np.sqrt(np.mean(np.square(samples[:usable].reshape(-1, size)), axis=1))


def _parse_iso(text: Any) -> float | None:
    """ISO-8601 with a trailing ``Z`` to a unix timestamp. ``None`` when it isn't."""

    if not isinstance(text, str) or not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def robot_playback_spans(index: Mapping[str, Any]) -> list[tuple[float, float]]:
    """Wall spans during which the robot was being played, from the R17 index."""

    spans: list[tuple[float, float]] = []
    robot = index.get("streams", {}).get("robot", {})
    for segment in robot.get("segments", []):
        if int(segment.get("frames", 0)) <= 0:
            continue
        start = _parse_iso(segment.get("started_at"))
        end = _parse_iso(segment.get("ended_at"))
        if start is None or end is None or end < start:
            continue
        spans.append((start, end))
    spans.sort()
    return spans


def _in_any_span(when: float, spans: Sequence[tuple[float, float]]) -> bool:
    for start, end in spans:
        if start <= when <= end:
            return True
        if start > when:
            break
    return False


def owner_stream_analysis(session_dir: Path, index: Mapping[str, Any],
                          *, frame_ms: int = 20) -> dict[str, Any]:
    """Was the owner silent — and if the stream was loud, loud *when*?

    THE DISTINCTION THAT DECIDES THE ARM. During a silent monologue two very
    different things can put speech-level energy into ``owner.wav``:

    * **inside a robot playback span** — that is the robot's own voice coming
      back through the air. If it is at speech level, the echo path is broken
      (the standing cause is a speaker that is not on the array's own DAC), and
      that is a *finding*, not a reason to abandon the measurement: the
      false-barge-in count is still exactly what it was.
    * **in a gap between robot utterances** — nothing but a person makes that.
      The owner was not silent, interrupts cannot be attributed, and the arm is
      genuinely unmeasurable.

    Collapsing the two into one "was it quiet?" boolean is what let a broken
    echo path report as ``unmeasured`` instead of as the failure it is.
    """

    path = Path(session_dir) / "owner.wav"
    if not path.is_file():
        return {"checked": False, "reason": f"no {path.name}"}
    with wave.open(str(path), "rb") as handle:
        channels = handle.getnchannels()
        rate = handle.getframerate()
        raw = handle.readframes(handle.getnframes())
    samples = np.frombuffer(raw, dtype=np.int16).astype(np.float64)
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)
    size = max(1, int(rate * frame_ms / 1000))
    usable = (samples.size // size) * size
    if usable == 0:
        return {"checked": False, "reason": "owner.wav holds no audio"}
    levels = np.sqrt(np.mean(np.square(samples[:usable].reshape(-1, size)), axis=1))

    # Map every owner frame to a wall time. Owner audio arrives in real time, so
    # within a segment the byte cursor IS a clock; segments carry their own
    # wall start, which is what stitches the two streams onto one timeline.
    owner = index.get("streams", {}).get("owner", {})
    frame_times = np.full(levels.size, np.nan, dtype=np.float64)
    for segment in owner.get("segments", []):
        started = _parse_iso(segment.get("started_at"))
        if started is None:
            continue
        first = int(segment.get("start_byte", 0)) // (size * channels * 2)
        last = int(segment.get("end_byte", 0)) // (size * channels * 2)
        for position in range(max(0, first), min(levels.size, max(first, last))):
            frame_times[position] = started + (position - first) * (frame_ms / 1000.0)

    spans = robot_playback_spans(index)
    threshold = 10.0 ** (OWNER_SILENCE_DBFS / 20.0) * 32768.0
    loud = levels > threshold
    during = np.zeros(levels.size, dtype=bool)
    placed = np.zeros(levels.size, dtype=bool)
    for position in range(levels.size):
        when = frame_times[position]
        if math.isnan(when):
            continue
        placed[position] = True
        during[position] = _in_any_span(when, spans)

    loud_total = int(loud.sum())
    loud_during = int((loud & during & placed).sum())
    loud_in_gaps = int((loud & ~during & placed).sum())
    loud_unplaced = int((loud & ~placed).sum())
    ordered = np.sort(levels)
    return {
        "checked": True,
        "frames": int(levels.size),
        "frames_placed_on_the_wall_clock": int(placed.sum()),
        "robot_spans": len(spans),
        "p50_dbfs": round(dbfs(float(ordered[ordered.size // 2])), 2),
        "p99_dbfs": round(dbfs(float(ordered[int(0.99 * (ordered.size - 1))])), 2),
        "loud_frames": loud_total,
        "loud_during_playback": loud_during,
        "loud_in_robot_silent_gaps": loud_in_gaps,
        "loud_frames_off_the_clock": loud_unplaced,
        "fraction_loud_in_gaps": round(loud_in_gaps / levels.size, 5),
        "fraction_loud_during_playback": round(loud_during / levels.size, 5),
        # Somebody spoke in a gap: the arm is not a silent arm.
        "owner_spoke": bool(loud_in_gaps / levels.size >= OWNER_SPEECH_FRACTION),
        # The robot's own voice is arriving at speech level: the echo path is
        # broken, and that is a result rather than an obstacle.
        "echo_in_owner_stream": bool(
            loud_during / levels.size >= OWNER_SPEECH_FRACTION
        ),
    }


def score_monologue(session_dir: Path) -> dict[str, Any]:
    """False barge-ins from the R17 index: interrupted utterances / utterances."""

    index = read_index(session_dir)
    robot = index.get("streams", {}).get("robot", {})
    segments = [
        segment
        for segment in robot.get("segments", [])
        if segment.get("kind") == "utterance" and int(segment.get("frames", 0)) > 0
    ]
    interrupted = [segment for segment in segments if bool(segment.get("interrupted"))]
    total = len(segments)
    return {
        "session_id": index.get("session_id", ""),
        "utterances": total,
        "interrupted": len(interrupted),
        "rate": (len(interrupted) / total) if total else None,
        "robot_seconds": robot.get("duration_s"),
        "owner_silence": owner_stream_analysis(session_dir, index),
    }


def read_jsonl(path: Path, *, limit_bytes: int = 64 * 1024) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with Path(path).open("r", encoding="utf-8") as handle:
        for line in handle:
            text = line.strip()
            if not text or len(text.encode("utf-8")) > limit_bytes:
                continue
            try:
                entry = json.loads(text)
            except json.JSONDecodeError:
                continue
            if isinstance(entry, dict):
                rows.append(entry)
    return rows


def score_turns(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Turn-level rows: who was credited with speaking, and was it really them.

    Expects one JSON object per line with at least ``speaker``; ``origin`` and
    ``identity`` are used when present. Written for the shape the hosted lane's
    ledger export produces, and tolerant of extra keys.
    """

    owner_turns = 0
    robot_as_owner = 0
    for entry in rows:
        speaker = str(entry.get("speaker", "")).lower()
        if speaker != "owner":
            continue
        owner_turns += 1
        source = str(entry.get("source", entry.get("origin", ""))).lower()
        if "robot" in source or bool(entry.get("was_robot")):
            robot_as_owner += 1
    return {"owner_turns": owner_turns, "robot_as_owner": robot_as_owner}


#: Event names this tool will accept as "the owner started speaking".
#: The kind the R17 tee's OWNER segmentation contributes. Not a provider event:
#: the first microphone frame of a burst that follows ``owner_gap_s`` of
#: silence. Named apart from the provider's ``speech_started`` so a reader of
#: the scorecard's ``sources`` can always tell which clock a pair came from.
CAPTURE_ONSET_KIND = "capture.owner_burst"
#: ... and the kind MARK-1's ``interrupted_at`` contributes.
CAPTURE_INTERRUPT_KIND = "capture.interrupted"

ONSET_KINDS: frozenset[str] = frozenset(
    {"speech_started", "onset", "input_audio_buffer.speech_started", CAPTURE_ONSET_KIND}
)
#: ... and as "the lane cut the robot off".
INTERRUPT_KINDS: frozenset[str] = frozenset(
    {"interrupt", "sink.interrupt", "barge_in", "conversation.item.truncated",
     CAPTURE_INTERRUPT_KIND}
)

#: How close after the tee's own stamp a ``conversation.item.truncated`` has to
#: land before it is read as the SAME interrupt seen twice. The tee stamps the
#: instant ``interrupt()`` ran; the provider echoes the truncate it caused a
#: network hop later. Counting both would double ``interrupts`` and pair the
#: onset with whichever witness happened to be first.
INTERRUPT_DEDUPE_S = 2.0


def normalise_events(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Accept both the evidence log's real rows and a hand-written ``{t, kind}``.

    ``realtime/evidence_log.py`` writes
    ``{"seq", "stream", "wall": ISO, "kind": "retained_event", "type": <provider
    event>, "fields": {...}, "session_id": "rt_…"}``. A hand-made file may use
    ``{"t": <unix>, "kind": "speech_started"}``. Both are read here so a session
    that HAS an evidence log needs no extra instrumentation.
    """

    out: list[dict[str, Any]] = []
    for entry in rows:
        when = entry.get("t")
        if isinstance(when, bool) or not isinstance(when, (int, float)):
            when = _parse_iso(entry.get("wall")) or _parse_iso(entry.get("timestamp"))
        if when is None:
            continue
        # For a retained_event the interesting name is the provider event type.
        name = str(entry.get("type") or entry.get("kind") or "")
        out.append({
            "t": float(when),
            "kind": name,
            "session_id": str(entry.get("session_id", "") or ""),
        })
    out.sort(key=lambda item: item["t"])
    return out


def event_session_ids(rows: Iterable[Mapping[str, Any]]) -> list[str]:
    """The PROVIDER session ids an evidence log mentions — the spend-ledger join."""

    return sorted({
        str(entry.get("session_id", "")) for entry in rows
        if str(entry.get("session_id", "") or "").startswith("rt_")
    })


def capture_latency_events(index: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The wall-stamped halves of a barge-in that the R17 index itself holds.

    Two kinds come out of one file, and they are not the same quality of
    evidence:

    * ``capture.interrupted`` — one per robot segment carrying MARK-1's
      ``interrupted_at``. This is a real stamp of a real instant: the wall clock
      the relay thread read as it ran ``interrupt()``. ``interrupted_byte`` and
      ``interrupted_t_s`` travel with it as the POSITION in the reply where the
      audio stopped (``robot.wav`` is written faster than real time, so they are
      never used as a clock).
    * ``capture.owner_burst`` — one per owner segment AFTER the first, i.e. the
      first microphone frame following ``owner_gap_s`` of silence. The first
      segment is skipped on purpose: it starts when the microphone opens, which
      is a gesture rather than an onset. This is an estimate of the onset, and
      the caller is expected to say so.

    A capture whose owner stream never went quiet yields no onsets at all — one
    long segment — which is exactly the shape of the silent monologue arm, and
    is why the row can still come back ``unmeasured`` on a capture that carries
    interrupts.
    """

    streams = index.get("streams") if isinstance(index, Mapping) else None
    streams = streams if isinstance(streams, Mapping) else {}
    session = str(index.get("session_id", "") or "") if isinstance(index, Mapping) else ""
    out: list[dict[str, Any]] = []

    robot = streams.get("robot") if isinstance(streams.get("robot"), Mapping) else {}
    for segment in robot.get("segments", []) or ():
        if not isinstance(segment, Mapping):
            continue
        when = _parse_iso(segment.get("interrupted_at"))
        if when is None:
            continue
        entry: dict[str, Any] = {
            "t": float(when),
            "kind": CAPTURE_INTERRUPT_KIND,
            "session_id": session,
            "utterance": segment.get("utterance"),
        }
        for key in ("interrupted_byte", "interrupted_t_s"):
            value = segment.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                entry[key] = float(value)
        out.append(entry)

    owner = streams.get("owner") if isinstance(streams.get("owner"), Mapping) else {}
    for position, segment in enumerate(owner.get("segments", []) or ()):
        if not isinstance(segment, Mapping) or position == 0:
            continue
        when = _parse_iso(segment.get("started_at"))
        if when is None:
            continue
        out.append({"t": float(when), "kind": CAPTURE_ONSET_KIND, "session_id": session})

    out.sort(key=lambda item: item["t"])
    return out


def score_interrupt_latency(
    rows: Iterable[Mapping[str, Any]] = (),
    *,
    capture_events: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Median onset→interrupt, or the precise reason there is no median.

    WHAT IS AND IS NOT ON DISK TODAY, corrected by FINISH-1 once MARK-1's stamp
    landed:

    * **the interrupt half is stamped twice over.** ``conversation.item.truncated``
      is in ``protocol.RETAINED_EVENT_TYPES`` and reaches ``events.jsonl``; the
      R17 index now carries ``interrupted_at`` on the robot segment itself
      (:func:`capture_latency_events`), which is the earlier and the more
      precise of the two. Both are accepted and the pair is de-duplicated within
      :data:`INTERRUPT_DEDUPE_S` so one barge-in seen by two witnesses stays one
      barge-in.
    * **the onset half is estimated, never stamped.**
      ``input_audio_buffer.speech_started`` is still not a retained type, so the
      only onset available is the tee's owner-burst boundary. A session with no
      burst boundaries — the owner silent, the microphone streaming
      continuously — yields interrupts with nothing to subtract them from, and
      this returns ``p50_s: None`` with ``onsets: 0`` rather than a number.

    ``sources`` in the result says which clock every pair came from, because a
    median built on the estimate and a median built on a provider stamp are not
    the same number and must never look alike.
    """

    events = normalise_events(rows)
    extra = [dict(entry) for entry in capture_events]
    if extra:
        events = sorted([*events, *extra], key=lambda item: float(item["t"]))
    stamped = [entry["t"] for entry in events if entry["kind"] == CAPTURE_INTERRUPT_KIND]
    if stamped:
        # One interrupt, two witnesses: the provider's echo of the truncate this
        # tee already stamped. Keep the tee's, which is the instant itself.
        events = [
            entry
            for entry in events
            if not (
                entry["kind"] == "conversation.item.truncated"
                and any(0.0 <= entry["t"] - when <= INTERRUPT_DEDUPE_S for when in stamped)
            )
        ]
    onsets: list[float] = []
    interrupts = 0
    gaps: list[float] = []
    pending: float | None = None
    for entry in events:
        kind = entry["kind"]
        when = entry["t"]
        if kind in ONSET_KINDS:
            pending = when
            onsets.append(when)
        elif kind in INTERRUPT_KINDS:
            interrupts += 1
            if pending is not None:
                gaps.append(when - pending)
                pending = None
    gaps = [gap for gap in gaps if gap >= 0.0]
    gaps.sort()
    kinds = sorted({str(entry["kind"]) for entry in events})
    stamped_interrupts = sum(1 for entry in events if entry["kind"] == CAPTURE_INTERRUPT_KIND)
    estimated_onsets = sum(1 for entry in events if entry["kind"] == CAPTURE_ONSET_KIND)
    unpaired = ""
    if not gaps:
        if interrupts and not onsets:
            unpaired = (
                f"{interrupts} interrupt event(s) and 0 onsets: "
                "input_audio_buffer.speech_started is not in "
                "protocol.RETAINED_EVENT_TYPES, and this capture's owner stream never "
                "went quiet for owner_gap_s, so it carries no burst boundary to use "
                "instead — the onset is the half that is missing, not the interrupt"
            )
        elif not interrupts and not onsets:
            unpaired = "neither the event file nor the capture carries onsets or interrupts"
        else:
            unpaired = f"{len(onsets)} onset(s) and {interrupts} interrupt(s) never paired"
    return {
        "events": len(events),
        "onsets": len(onsets),
        "interrupts": interrupts,
        "pairs": len(gaps),
        "p50_s": round(gaps[len(gaps) // 2], 4) if gaps else None,
        "p95_s": round(gaps[int(0.95 * (len(gaps) - 1))], 4) if gaps else None,
        # Which clock the numbers came off. A median built on the tee's
        # owner-burst estimate is a bound; one built on a provider stamp is a
        # measurement; they must never be indistinguishable in the record.
        "kinds": kinds,
        # Where in the reply each barge-in landed, from MARK-1's
        # ``interrupted_t_s``. A POSITION, never a time: ``robot.wav`` is
        # written faster than real time, so this says how much of the sentence
        # the owner had heard, not when.
        "positions_into_reply_s": [
            round(float(entry["interrupted_t_s"]), 4)
            for entry in events
            if entry.get("interrupted_t_s") is not None
        ],
        "interrupted_bytes": [
            int(entry["interrupted_byte"])
            for entry in events
            if entry.get("interrupted_byte") is not None
        ],
        "interrupts_stamped_by_the_tee": stamped_interrupts,
        "onsets_estimated_from_owner_bursts": estimated_onsets,
        "onset_is_an_estimate": bool(estimated_onsets) and estimated_onsets == len(onsets),
        "unpaired_reason": unpaired,
    }


def score_spend(rows: Iterable[Mapping[str, Any]], *, session_ids: Sequence[str] = (),
                window: tuple[float, float] | None = None,
                margin_s: float = 120.0) -> dict[str, Any]:
    """Sum the ledger rows belonging to this session. Zero rows is NOT zero spend.

    THE JOIN THAT DOES NOT EXIST. The spend ledger is keyed by the PROVIDER's
    session id (``rt_ab12cd34…``); the capture tee names its folders with its own
    id (``sess_…``). They are different namespaces, so matching one against the
    other selects nothing, and "nothing" summed is ``$0.00`` — a passing row for
    a session that may have cost real money. Two joins actually work:

    * ``session_ids`` — provider ids, which the evidence log's rows carry
      (``--events`` recovers them for free), or which you can pass by hand with
      ``--spend-session``;
    * ``window`` — the capture's own wall span, matched against each ledger
      row's ``wall`` field, widened by ``margin_s`` at both ends because the
      first cost row lands after the first response.

    With neither, every row in the file is counted and the result says so. With
    either, **zero matched rows returns ``matched: False``** and the caller must
    render that as unmeasured, never as zero.
    """

    wanted = {str(item) for item in session_ids if item}
    total = 0.0
    counted = 0
    skipped = 0
    for entry in rows:
        usd = entry.get("estimated_usd")
        if isinstance(usd, bool) or not isinstance(usd, (int, float)):
            continue
        if wanted or window is not None:
            by_session = bool(wanted) and str(entry.get("session_id", "")) in wanted
            by_window = False
            if window is not None:
                when = _parse_iso(entry.get("wall"))
                by_window = when is not None and (
                    window[0] - margin_s <= when <= window[1] + margin_s
                )
            if not (by_session or by_window):
                skipped += 1
                continue
        total += float(usd)
        counted += 1
    selective = bool(wanted) or window is not None
    return {
        "usd": round(total, 6),
        "rows": counted,
        "rows_skipped": skipped,
        "sessions": sorted(wanted),
        "window": None if window is None else [round(window[0], 3), round(window[1], 3)],
        "selective": selective,
        # False means: the file was read and nothing in it belongs to this
        # session. That is an absence of evidence, not evidence of $0.00.
        "matched": bool(counted > 0),
        "note": (
            "" if selective else
            "no session id and no capture window were supplied, so this is the WHOLE "
            "ledger file and not this session's spend"
        ),
    }


def capture_wall_window(index: Mapping[str, Any]) -> tuple[float, float] | None:
    """The wall span an R17 capture covers, for joining against the spend ledger."""

    started = _parse_iso(index.get("started_at"))
    closed = _parse_iso(index.get("closed_at"))
    if started is None:
        return None
    if closed is None or closed < started:
        # A killed process leaves no closed_at. Fall back to the last segment
        # boundary either stream reached, which is a real observation.
        latest = started
        for stream in index.get("streams", {}).values():
            for segment in stream.get("segments", []):
                when = _parse_iso(segment.get("ended_at"))
                if when is not None and when > latest:
                    latest = when
        closed = latest
    return (started, closed)


# =================================================================== assemble
def _erle_report_problem(erle: Any) -> str:
    """Empty string when ``erle`` is a usable report; otherwise why it is not."""

    if erle is None:
        return "no --erle report"
    if not isinstance(erle, Mapping):
        return f"the --erle file holds a {type(erle).__name__}, not a report"
    schema = erle.get("schema")
    if schema != ERLE_REPORT_SCHEMA:
        return (
            f"the --erle file's schema is {schema!r}, not {ERLE_REPORT_SCHEMA!r}: this is "
            "not a report tools/measure_erle.py wrote"
        )
    verdict = erle.get("verdict")
    if verdict not in ERLE_REPORT_VERDICTS:
        problems = "; ".join(str(item) for item in erle.get("problems", ()))
        return (
            f"the ERLE report's own verdict is {verdict!r}"
            + (f": {problems}" if problems else "")
        )
    value = erle.get("asr_beam_echo_attenuation_db", erle.get("erle_db"))
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return f"the ERLE report carries no numeric attenuation (got {value!r})"
    return ""


def build_scorecard(
    *,
    monologue: dict[str, Any] | None = None,
    tv: dict[str, Any] | None = None,
    turns: dict[str, Any] | None = None,
    latency: dict[str, Any] | None = None,
    erle: Mapping[str, Any] | None = None,
    probe: Mapping[str, Any] | None = None,
    spend: dict[str, Any] | None = None,
    evidence: Mapping[str, str] | None = None,
    session_note: str = "",
) -> dict[str, Any]:
    """Every source is optional and every absence becomes an explicit ``unmeasured``."""

    paths = dict(evidence or {})
    rows: list[dict[str, Any]] = []

    # An ERLE report whose own verdict is "unmeasured" — the two legs were not
    # the same loudness — carries a number that is not evidence about an AEC.
    # It does not become a row here; laundering it into a pass is exactly the
    # thing the report refused to do one file upstream.
    # A "fail" IS trustworthy and must land as a miss with its mechanism; an
    # "unmeasured" — the legs were not comparable — has no row to give. Anything
    # that is not recognisably one of this tool's own reports is not evidence at
    # all: an allow-list, not a deny-list, because the deny-list version trusted
    # every mapping that merely lacked the word "unmeasured".
    erle_problem = _erle_report_problem(erle)
    erle_trustworthy = erle_problem == ""
    erle_value = None
    if isinstance(erle, Mapping):
        erle_value = erle.get("asr_beam_echo_attenuation_db", erle.get("erle_db"))
    rows.append(
        make_row(
            "erle_db",
            erle_value if (erle_trustworthy and isinstance(erle_value, (int, float))) else None,
            evidence=[paths["erle"]] if "erle" in paths else [],
            mechanism=(
                "; ".join(str(item) for item in erle.get("problems", ()))
                if (erle_trustworthy and str(erle.get("verdict")) == "fail")
                else ""
            ),
            unmeasured_reason="" if erle_trustworthy else erle_problem,
        )
    )

    rows.append(
        make_row(
            "robot_utterances_as_owner_turns",
            None if turns is None else float(turns["robot_as_owner"]),
            n=0 if turns is None else int(turns["owner_turns"]),
            evidence=[paths["turns"]] if "turns" in paths else [],
            unmeasured_reason="" if turns is not None else MISSING_TURN_PRODUCER,
        )
    )

    latency_value = None if latency is None else latency.get("p50_s")
    latency_evidence = [paths[key] for key in ("events", "capture") if key in paths]
    rows.append(
        make_row(
            "interrupt_p50_s",
            latency_value if isinstance(latency_value, (int, float)) else None,
            n=0 if latency is None else int(latency.get("pairs", 0)),
            evidence=latency_evidence,
            # NOT ``mechanism``: a mechanism is an explanation of a MISS and
            # ``verify_scorecard`` refuses one on a row that passed. The
            # provenance of this median — which clock each half came off, and
            # whether the onset was estimated — rides ``sources.latency``
            # (``kinds``, ``onset_is_an_estimate``) and is printed under the
            # table by the CLI.
            unmeasured_reason=(
                ""
                if isinstance(latency_value, (int, float))
                else (
                    "the INTERRUPT half is on disk — MARK-1's mark_interrupted now writes "
                    "interrupted_at/interrupted_byte/interrupted_t_s onto the robot "
                    "segment, and this tool reads it (handoff MARK-1-STAMP is CLOSED). "
                    "The ONSET half is not: input_audio_buffer.speech_started is not in "
                    "protocol.RETAINED_EVENT_TYPES, so the only onset available is the "
                    "tee's owner-burst boundary, and this session supplied none. Give it "
                    "a --capture whose owner stream goes quiet between bursts, or retain "
                    "speech_started. See handoff TURN-1-ONSET in AIR1_STATUS.md."
                    + (f" This session: {latency['unpaired_reason']}" if latency else "")
                )
            ),
        )
    )

    # The silent arm, and the two very different reasons it can be loud.
    silence = (monologue or {}).get("owner_silence", {})
    checked = bool(silence.get("checked"))
    owner_spoke = bool(silence.get("owner_spoke")) if checked else False
    echo_in_stream = bool(silence.get("echo_in_owner_stream")) if checked else False
    rate = None if monologue is None else monologue.get("rate")
    scorable = monologue is not None and checked and not owner_spoke and rate is not None

    false_reason = ""
    if not scorable:
        if monologue is None:
            false_reason = "no --capture monologue session"
        elif not checked:
            false_reason = f"the owner stream could not be read: {silence.get('reason', '')}"
        elif owner_spoke:
            false_reason = (
                "speech-level energy in the owner stream during robot-silent gaps "
                f"({silence.get('fraction_loud_in_gaps')} of frames): somebody was talking, "
                "so an interrupt cannot be attributed to echo. Re-run the arm in silence."
            )
        else:
            false_reason = "the monologue session carries no utterances to score"

    rows.append(
        make_row(
            "false_barge_in_rate",
            rate if scorable else None,
            n=0 if monologue is None else int(monologue.get("utterances", 0)),
            evidence=[paths["capture"]] if "capture" in paths else [],
            # A mechanism explains a miss. It is set when there IS a miss —
            # either because the rate breached the gate or because the override
            # below turned a passing rate into one.
            mechanism=(
                "speech-level energy in the owner stream during playback: the robot's own "
                "voice is reaching the microphone uncancelled — the standing cause is a "
                "speaker that is not on the array's own DAC"
                if (scorable and echo_in_stream)
                else (
                    "residual echo above the barge-in threshold"
                    if (scorable and rate is not None and rate > ROWS_BY_ID[
                        "false_barge_in_rate"].threshold)
                    else ""
                )
            ),
            override_reason=(
                f"{silence.get('fraction_loud_during_playback')} of owner-stream frames were "
                "at speech level DURING robot playback: the count of self-interrupts is real, "
                "but the echo path this arm exists to test is broken"
                if (scorable and echo_in_stream)
                else ""
            ),
            unmeasured_reason=false_reason,
        )
    )

    tv_value = None if tv is None else float(tv.get("owner_turns", 0))
    rows.append(
        make_row(
            "tv_owner_attributed_turns",
            tv_value,
            evidence=[paths["tv"]] if "tv" in paths else [],
            unmeasured_reason="" if tv is not None else MISSING_TURN_PRODUCER,
        )
    )

    doa = None if probe is None else probe.get("sections", {}).get("doa")
    doa_value = None if not isinstance(doa, Mapping) else doa.get("ok_fraction")
    rows.append(
        make_row(
            "doa_ok_fraction",
            doa_value if isinstance(doa_value, (int, float)) else None,
            n=0 if not isinstance(doa, Mapping) else int(doa.get("requested", 0)),
            evidence=[paths["probe"]] if "probe" in paths else [],
            mechanism="" if not isinstance(doa, Mapping) else str(doa.get("last_error", "")),
            unmeasured_reason=(
                "" if isinstance(doa_value, (int, float)) else "no --probe run with --doa"
            ),
        )
    )

    spend_matched = spend is not None and bool(spend.get("matched"))
    rows.append(
        make_row(
            "hosted_spend_usd",
            float(spend["usd"]) if spend_matched else None,
            evidence=[paths["spend"]] if "spend" in paths else [],
            unmeasured_reason=(
                ""
                if spend_matched
                else (
                    "no --spend ledger"
                    if spend is None
                    else "no ledger rows matched this session: the spend ledger is keyed by "
                    f"the provider's session id and {spend.get('rows_skipped', 0)} row(s) "
                    "were skipped. Pass --spend-session rt_… or --events so the provider id "
                    "can be recovered. Zero matched rows is an absence of evidence, not $0.00."
                )
            ),
        )
    )

    card: dict[str, Any] = {
        "schema": SCORECARD_SCHEMA,
        "note": session_note,
        "rows": rows,
        "sources": {
            "monologue": monologue,
            "tv": tv,
            "turns": turns,
            "latency": latency,
            "spend": spend,
        },
    }
    card["summary"] = summarise_scorecard(card)
    return card


# ======================================================================== CLI
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--capture", type=Path, default=None,
                        help="R17 session folder for the silent 10-min monologue arm")
    parser.add_argument("--tv-capture", type=Path, default=None,
                        help="R17 session folder for the TV arm")
    parser.add_argument("--turns", type=Path, default=None,
                        help="JSONL turn export (speaker/source per line)")
    parser.add_argument("--tv-turns", type=Path, default=None,
                        help="JSONL turn export for the TV arm")
    parser.add_argument("--events", type=Path, default=None,
                        help="JSONL wall-stamped events for interrupt latency")
    parser.add_argument("--erle", type=Path, default=None, help="tools/measure_erle.py --report")
    parser.add_argument("--probe", type=Path, default=None, help="tools/xvf3800_probe.py --json")
    parser.add_argument("--spend", type=Path, default=None, help="spend.jsonl")
    parser.add_argument("--spend-session", action="append", default=[], metavar="rt_...",
                        help="the PROVIDER session id(s) to bill this session for; repeatable. "
                             "Recovered automatically from --events when the evidence log is on")
    parser.add_argument("--note", default="", help="what this session was, in your words")
    parser.add_argument("--out", type=Path, default=None, help="write the scorecard here")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    evidence: dict[str, str] = {}
    session_ids: list[str] = []

    windows: list[tuple[float, float]] = []
    monologue = None
    if args.capture is not None:
        monologue = score_monologue(args.capture)
        evidence["capture"] = str(args.capture)
        window = capture_wall_window(read_index(args.capture))
        if window is not None:
            windows.append(window)

    tv = None
    if args.tv_turns is not None:
        tv = score_turns(read_jsonl(args.tv_turns))
        evidence["tv"] = str(args.tv_turns)
    if args.tv_capture is not None:
        tv_index = read_index(args.tv_capture)
        window = capture_wall_window(tv_index)
        if window is not None:
            windows.append(window)
        evidence.setdefault("tv", str(args.tv_capture))

    turns = None
    if args.turns is not None:
        turns = score_turns(read_jsonl(args.turns))
        evidence["turns"] = str(args.turns)

    latency = None
    event_rows: list[dict[str, Any]] = []
    if args.events is not None:
        event_rows = read_jsonl(args.events)
        # The evidence log names the PROVIDER session — the only id the spend
        # ledger is keyed by. Recovering it here is what turns the spend row
        # from a vacuous $0.00 into a real sum or an honest absence.
        session_ids.extend(event_session_ids(event_rows))
        evidence["events"] = str(args.events)
    # The capture is the SECOND source of latency evidence and on its own it is
    # enough for the interrupt half: MARK-1's stamp lives on the robot segment.
    capture_events = capture_latency_events(read_index(args.capture)) if args.capture else []
    if event_rows or capture_events:
        latency = score_interrupt_latency(event_rows, capture_events=capture_events)

    erle = None
    if args.erle is not None:
        erle = json.loads(args.erle.read_text(encoding="utf-8"))
        evidence["erle"] = str(args.erle)

    probe = None
    if args.probe is not None:
        probe = json.loads(args.probe.read_text(encoding="utf-8"))
        evidence["probe"] = str(args.probe)

    session_ids.extend(str(item) for item in args.spend_session)
    spend = None
    if args.spend is not None:
        span = None
        if windows:
            span = (min(start for start, _ in windows), max(end for _, end in windows))
        spend = score_spend(read_jsonl(args.spend), session_ids=session_ids, window=span)
        evidence["spend"] = str(args.spend)

    card = build_scorecard(
        monologue=monologue, tv=tv, turns=turns, latency=latency, erle=erle,
        probe=probe, spend=spend, evidence=evidence, session_note=args.note,
    )
    problems = verify_scorecard(card)
    if problems:
        for problem in problems:
            print(f"INVALID   {problem}")
        return 2

    for entry in card["rows"]:
        value = "—" if entry["value"] is None else entry["value"]
        arrow = "<=" if entry["direction"] == "max" else ">="
        print(
            f"{entry['verdict']:<10} {entry['id']:<32} {value!s:>10} {entry['unit']:<8} "
            f"{arrow} {entry['threshold']}"
            + (f"   ({entry['unmeasured_reason']})" if entry["verdict"] == "unmeasured" else "")
        )
    if (latency or {}).get("onset_is_an_estimate") and latency.get("pairs"):
        print(
            "\nNOTE  interrupt_p50_s: the interrupt instant is MARK-1's own "
            "interrupted_at stamp, but the onset is ESTIMATED from the tee's owner-burst "
            "boundary (first mic frame after owner_gap_s of silence). This median is a "
            "bound, not a provider-stamped measurement."
        )
    summary = card["summary"]
    print(f"\n{summary['pass']} pass · {summary['fail']} fail · {summary['unmeasured']} unmeasured")
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(card, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {args.out}")
    return 1 if summary["fail"] else 0


if __name__ == "__main__":  # pragma: no cover - script entry
    raise SystemExit(main())
