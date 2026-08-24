"""P1 — the local VAD gate: rows C2, C3, C4, C5.

    .parcel/bin/python -m run_p1        (with research folder on PYTHONPATH)

Three tapes, one gate:

* ``owner``   — the 22 frozen ``acoustic_loop_v1`` utterances spaced at the
  pre-registered day's rate (174 turns / 12 h = 14.5 an hour). C2, C3, C4.
* ``room``    — the two non-speech noise fixtures on repeat for an hour. C5.
* ``tv``      — speech attenuated 20 dB, laid down almost continuously, which
  is what a television in the next room actually is. C5's hard case.

The pre-roll sweep (300 / 500 / 800 ms) is run on the owner tape as DESIGN.md
specifies; the pre-roll changes only what is uploaded, never what the gate
decides, so one Silero pass per gate configuration is enough and the sweep is
arithmetic on its spans.
"""

from __future__ import annotations

import json
import statistics
import time
from collections.abc import Sequence

import numpy as np
from ladder import DAYS_PER_MONTH, LISTEN_HOURS_PER_DAY, load_utterances, write_result
from vad_gate import (
    GateConfig,
    GateSpan,
    Placement,
    Tape,
    build_tape,
    read_wav_16k,
    run_gate,
    to_pcm16,
)

#: 174 owner turns spread over a 12-hour listening day.
TURNS_PER_HOUR = 174.0 / LISTEN_HOURS_PER_DAY
OWNER_GAP_S = 3600.0 / TURNS_PER_HOUR

#: The dither floor of "silence". int16 LSB-scale noise: a digital-silence tape
#: would flatter the VAD, and a real room floor is not available to measure.
DITHER = 0.0008

#: A television across a room, relative to the owner at conversational
#: distance. -20 dB is roughly one extra room's worth of distance.
TV_ATTENUATION_DB = -20.0
TV_GAP_S = 0.4
AMBIENT_HOUR_S = 3600.0

PREROLLS_MS = (300.0, 500.0, 800.0)
HANGOVERS_MS = (300.0, 500.0, 800.0)


def _clips(names: Sequence[str] | None = None) -> list[tuple[str, str, np.ndarray, float, float]]:
    clips = []
    for utterance in load_utterances():
        if utterance.speech_start_s is None or utterance.speech_end_s is None:
            continue
        if names is not None and utterance.name not in names:
            continue
        clips.append(
            (
                utterance.name,
                utterance.kind,
                read_wav_16k(utterance.path),
                utterance.speech_start_s,
                utterance.speech_end_s,
            )
        )
    return clips


def owner_tape() -> Tape:
    return build_tape(_clips(), gap_s=OWNER_GAP_S, dither=DITHER, seed=20260823)


def room_tape() -> Tape:
    """An hour of the two non-speech noise fixtures, back to back."""

    noises = [read_wav_16k(u.path) for u in load_utterances() if u.kind == "noise"]
    span = sum(clip.size for clip in noises) / 16_000
    repeats = max(1, int(AMBIENT_HOUR_S / span))
    return Tape(samples=np.concatenate(noises * repeats), placements=[])


def tv_tape() -> Tape:
    """An hour of attenuated speech: the case a pure VAD cannot win."""

    gain = 10.0 ** (TV_ATTENUATION_DB / 20.0)
    clips = [
        (name, kind, to_pcm16(clip.astype(np.float64) / 32768.0 * gain), start, end)
        for name, kind, clip, start, end in _clips()
    ]
    span = sum(clip.size for _, _, clip, _, _ in clips) / 16_000 + len(clips) * TV_GAP_S
    repeats = max(1, int(AMBIENT_HOUR_S / span))
    return build_tape(clips * repeats, gap_s=TV_GAP_S, dither=DITHER, seed=20260824)


def _covering(spans: Sequence[GateSpan], placement: Placement) -> list[GateSpan]:
    """Every span overlapping this utterance.

    More than one means the gate CLOSED INSIDE a sentence and reopened — a
    split. The corpus's pause-heavy fixtures carry a deliberate 0.75 s internal
    pause and exist to catch exactly that, so the count is reported rather than
    hidden by taking the first or the last span: a split turn is two hosted
    responses and half an answer, which is worse than either metric alone says.
    """

    return [
        span
        for span in spans
        if span.close_s >= placement.speech_start_s and span.open_s <= placement.speech_end_s
    ]


def score_owner(tape: Tape, spans: Sequence[GateSpan], preroll_ms: float) -> dict[str, object]:
    """C2/C3/C4 for one pre-roll, from one already-computed set of spans."""

    preroll_s = preroll_ms / 1000.0
    uploaded_s = 0.0
    for span in spans:
        uploaded_s += max(0.0, span.close_s - max(0.0, span.open_s - preroll_s))
    rows: list[dict[str, object]] = []
    truncated = 0
    endpoints: list[float] = []
    missed = 0
    split = 0
    for placement in tape.placements:
        covering = _covering(spans, placement)
        if not covering:
            missed += 1
            rows.append({"name": placement.name, "opened": False})
            continue
        if len(covering) > 1:
            split += 1
        upload_from = max(0.0, covering[0].open_s - preroll_s)
        # The EARLIER of the two independent onsets, so a gate cannot be
        # credited by the witness that shares its own model.
        onset = min(placement.speech_start_s, placement.energy_onset_s)
        lost_ms = max(0.0, upload_from - onset) * 1000.0
        # Endpoint is measured on the span that carries the END of the
        # sentence, so a mid-sentence split does not report as a negative
        # (impossibly early) endpoint.
        endpoint_s = covering[-1].close_s - placement.speech_end_s
        endpoints.append(endpoint_s)
        if lost_ms > 0.0:
            truncated += 1
        rows.append(
            {
                "name": placement.name,
                "kind": placement.kind,
                "opened": True,
                "spans": len(covering),
                "onset_s": round(onset, 4),
                "upload_from_s": round(upload_from, 4),
                "first_word_lost_ms": round(lost_ms, 1),
                "endpoint_s": round(endpoint_s, 4),
            }
        )
    total = len(tape.placements)
    return {
        "preroll_ms": preroll_ms,
        "utterances": total,
        "missed_utterances": missed,
        "split_utterances": split,
        "gate_opens": len(spans),
        "listening_s": round(tape.seconds, 2),
        "uploaded_s": round(uploaded_s, 2),
        "reduction_x": round(tape.seconds / uploaded_s, 2) if uploaded_s else None,
        "truncated": truncated,
        "truncation_rate": round(truncated / total, 4) if total else None,
        "max_first_word_lost_ms": round(
            max((float(r.get("first_word_lost_ms", 0.0)) for r in rows if r["opened"]), default=0.0),
            1,
        ),
        "endpoint_p50_s": round(statistics.median(endpoints), 4) if endpoints else None,
        "endpoint_p95_s": (
            round(sorted(endpoints)[max(0, int(0.95 * len(endpoints)) - 1)], 4)
            if endpoints
            else None
        ),
        "rows": rows,
    }


def main() -> int:
    started = time.time()
    payload: dict[str, object] = {
        "harness": "p1_vad_gate",
        "duty_cycle": {
            "turns_per_hour": round(TURNS_PER_HOUR, 3),
            "owner_gap_s": round(OWNER_GAP_S, 2),
            "listen_hours_per_day": LISTEN_HOURS_PER_DAY,
            "days_per_month": DAYS_PER_MONTH,
        },
        "dither_amplitude": DITHER,
        "tv_attenuation_db": TV_ATTENUATION_DB,
    }

    owner = owner_tape()
    print(f"owner tape: {owner.seconds / 60:.1f} min, {len(owner.placements)} utterances")
    hangover_results: list[dict[str, object]] = []
    for hangover_ms in HANGOVERS_MS:
        config = GateConfig(hangover_ms=hangover_ms)
        spans = run_gate(owner, config)
        for preroll_ms in PREROLLS_MS:
            scored = score_owner(owner, spans, preroll_ms)
            scored["hangover_ms"] = hangover_ms
            hangover_results.append(scored)
            print(
                f"  hangover {hangover_ms:5.0f} ms  preroll {preroll_ms:5.0f} ms  "
                f"reduction {scored['reduction_x']}x  trunc {scored['truncation_rate']}  "
                f"ep p50 {scored['endpoint_p50_s']}s  opens {scored['gate_opens']}"
            )
    payload["owner"] = hangover_results

    ambient: list[dict[str, object]] = []
    for label, tape in (("room_noise", room_tape()), ("tv_speech", tv_tape())):
        spans = run_gate(tape, GateConfig())
        opens_per_hour = len(spans) / (tape.seconds / 3600.0)
        open_fraction = sum(s.close_s - s.open_s for s in spans) / tape.seconds
        ambient.append(
            {
                "tape": label,
                "seconds": round(tape.seconds, 2),
                "gate_opens": len(spans),
                "opens_per_hour": round(opens_per_hour, 2),
                "open_fraction": round(open_fraction, 4),
            }
        )
        print(f"  {label}: {opens_per_hour:.2f} opens/h, gate open {open_fraction * 100:.1f}% of it")
    payload["ambient"] = ambient
    payload["wall_s"] = round(time.time() - started, 1)

    path = write_result("p1_vad_gate.json", payload)
    print(f"wrote {path}")
    print(json.dumps({k: v for k, v in payload.items() if k != "owner"}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
