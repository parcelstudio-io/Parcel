"""P0 — hosted-always: row C1, and the per-turn price table P2 re-uses.

    .parcel/bin/python run_p0.py        (research folder on PYTHONPATH)

P0 is today's shipped default: ONE session, server VAD, ``idle_close_after_s:
0``. The socket is open for the whole listening day, so the provider is billed
for every second of it whether or not anybody spoke, and every speech segment
server VAD detects becomes a committed turn and a billed response — including
the television's.

THE FLOOR IS REPORTED TWICE, BECAUSE THE LIVE RUN REFUTED IT
------------------------------------------------------------
DESIGN.md's premise is that an open socket is billed for the silence it is
streamed (600 audio tokens a minute, ~$130/month on mini at 12 h/day). The
$2 live calibration measured otherwise: the SAME utterance preceded by 63.8 s
of uploaded silence and by 3.8 s of uploaded silence billed the SAME 19 audio
input tokens. Server VAD discards non-speech before it is tokenised.

So both floors appear below. ``floor_assumed`` is the pre-registered
projection, reported because it was pre-registered. ``floor_measured`` is zero,
and it is the one the conclusions use.

NUMBERS, AND THE EVIDENCE UNDER EACH
------------------------------------
``floor``
    the open socket in silence. Arithmetic on the published audio-input rate —
    and REFUTED by measurement.
``text_day``
    the floor plus the 174 corpus turns priced from THEIR OWN measured token
    counts. Fully measured, and a hard LOWER bound: the corpus was captured in
    text modality, which is the cheapest way this conversation could happen.
``audio_day``
    the floor plus the same 174 turns re-expressed as audio. Modelled — see
    ``ladder.audio_row_from_text_row`` — and the honest estimate of what the
    shipped ``mode: audio`` default costs.
``audio_day_with_tv``
    ``audio_day`` plus the responses server VAD would commit from a television,
    at the open rate P1 measured on the TV tape.
"""

from __future__ import annotations

import json
import statistics

from ladder import (
    CARDS,
    DAYS_PER_MONTH,
    LISTEN_HOURS_PER_DAY,
    RESULTS_DIR,
    audio_row_from_text_row,
    listening_usd_per_hour,
    load_turns,
    load_utterances,
    measured_words_per_second,
    write_result,
)

#: How many hours a day a television is audible. A scenario band, not a
#: measurement: nobody has measured this owner's living room.
TV_HOURS = (0.0, 4.0, 12.0)


def audio_out_ratio() -> tuple[float, list[float]]:
    """Audio output tokens per TEXT output token, measured on the live run.

    Not a reading rate: the provider emits its own spoken form, and this is the
    ratio it actually billed for the words it said. Averaged over the live audio
    responses that produced any text at all.
    """

    path = RESULTS_DIR / "live_calibration.json"
    if not path.exists():
        raise SystemExit("run live.sh first: the audio model is calibrated on its rows")
    live = json.loads(path.read_text(encoding="utf-8"))
    ratios = []
    for row in live["rows"]:
        detail = row["raw_usage"].get("output_token_details") or {}
        text_out = int(detail.get("text_tokens", 0) or 0)
        audio_out = int(detail.get("audio_tokens", 0) or 0)
        if text_out >= 20 and audio_out > 0:
            ratios.append(audio_out / text_out)
    if not ratios:
        raise SystemExit("no live audio responses to calibrate the audio model on")
    return statistics.mean(ratios), ratios


def silence_is_billed() -> dict[str, object]:
    """Did uploaded silence cost anything? Read straight off the two probes."""

    live = json.loads((RESULTS_DIR / "live_calibration.json").read_text(encoding="utf-8"))
    probes = [
        {
            "phase": r["phase"],
            "uploaded_s": r.get("audio_uploaded_s"),
            "input_audio_tokens": r["flat_row"]["input_audio_tokens"],
        }
        for r in live["rows"]
        if r["phase"].startswith("audio") and r.get("audio_uploaded_s")
    ]
    first = [p for p in probes if p["phase"] == "audio_60s_silence"]
    second = [p for p in probes if p["phase"] == "audio_no_silence"]
    billed = bool(first and second and first[0]["input_audio_tokens"] != second[0]["input_audio_tokens"])
    return {"billed": billed, "probes": probes}


def priced_day(card, *, words_per_second: float, audio_out_per_text_out: float) -> dict[str, object]:
    """Every corpus turn priced twice — as captured (text) and as audio."""

    text_rows: list[dict[str, object]] = []
    audio_rows: list[dict[str, object]] = []
    history: dict[str, int] = {}
    for turn in load_turns():
        usage = dict(turn.usage)
        text_rows.append(
            {
                "thread": turn.thread_id,
                "index": turn.index,
                "family": turn.family,
                "usd": card.priced_usd(usage),
                "usage": usage,
            }
        )
        carried = history.get(turn.thread_id, 0)
        audio_usage = audio_row_from_text_row(
            usage,
            owner_words=turn.owner_words,
            robot_words=turn.robot_words,
            words_per_second=words_per_second,
            history_audio_tokens=carried,
            audio_out_per_text_out=audio_out_per_text_out,
        )
        history[turn.thread_id] = carried + int(audio_usage.pop("_new_history_audio"))
        audio_usage.pop("_robot_words", None)
        audio_rows.append(
            {
                "thread": turn.thread_id,
                "index": turn.index,
                "family": turn.family,
                "usd": card.priced_usd(audio_usage),
                "usage": audio_usage,
            }
        )
    return {"text": text_rows, "audio": audio_rows}


def _tv_opens_per_hour() -> float:
    path = RESULTS_DIR / "p1_vad_gate.json"
    if not path.exists():
        raise SystemExit("run_p1.py first: P0's television term reads its measured open rate")
    p1 = json.loads(path.read_text(encoding="utf-8"))
    for row in p1["ambient"]:
        if row["tape"] == "tv_speech":
            return float(row["opens_per_hour"])
    raise SystemExit("p1_vad_gate.json has no tv_speech row")


def main() -> int:
    words_per_second = measured_words_per_second(load_utterances())
    tv_opens_per_hour = _tv_opens_per_hour()
    ratio, ratios = audio_out_ratio()
    silence = silence_is_billed()
    payload: dict[str, object] = {
        "harness": "p0_hosted_always",
        "words_per_second_measured": round(words_per_second, 3),
        "audio_out_per_text_out_measured": round(ratio, 4),
        "audio_out_ratios": [round(r, 4) for r in ratios],
        "silence_billing": silence,
        "tv_opens_per_hour_measured": tv_opens_per_hour,
        "listen_hours_per_day": LISTEN_HOURS_PER_DAY,
        "days_per_month": DAYS_PER_MONTH,
        "models": {},
    }
    per_turn_table: dict[str, object] = {}

    for name, card in CARDS.items():
        day = priced_day(
            card, words_per_second=words_per_second, audio_out_per_text_out=ratio
        )
        text_day = sum(float(r["usd"]) for r in day["text"])
        audio_day = sum(float(r["usd"]) for r in day["audio"])
        median_audio_turn = statistics.median(float(r["usd"]) for r in day["audio"])
        floor_assumed = listening_usd_per_hour(card) * LISTEN_HOURS_PER_DAY * DAYS_PER_MONTH
        floor_month = 0.0 if not silence["billed"] else floor_assumed
        tv_months = {
            f"{hours:.0f}h": round(
                floor_month
                + audio_day * DAYS_PER_MONTH
                + tv_opens_per_hour * hours * DAYS_PER_MONTH * median_audio_turn,
                2,
            )
            for hours in TV_HOURS
        }
        payload["models"][name] = {
            "model": card.model,
            "as_of": card.as_of,
            "listening_usd_per_hour_assumed": round(listening_usd_per_hour(card), 5),
            "floor_usd_per_month_assumed_refuted": round(floor_assumed, 2),
            "floor_usd_per_month_measured": round(floor_month, 2),
            "turns_usd_per_day_text_measured": round(text_day, 5),
            "turns_usd_per_day_audio_modelled": round(audio_day, 5),
            "median_turn_usd_audio_modelled": round(median_audio_turn, 6),
            "text_day_usd_per_month": round(floor_month + text_day * DAYS_PER_MONTH, 2),
            "audio_day_usd_per_month": round(floor_month + audio_day * DAYS_PER_MONTH, 2),
            "audio_day_with_tv_usd_per_month": tv_months,
        }
        per_turn_table[name] = [
            {"thread": r["thread"], "index": r["index"], "usd": r["usd"]} for r in day["text"]
        ]
        per_turn_table[f"{name}_audio"] = [
            {"thread": r["thread"], "index": r["index"], "usd": r["usd"]} for r in day["audio"]
        ]
        print(
            f"{name:5s} floor ${floor_month:8.2f}/mo | text-day ${text_day:.4f} "
            f"| audio-day ${audio_day:.4f} | P0 audio ${payload['models'][name]['audio_day_usd_per_month']}/mo"
        )

    write_result("p0_hosted_always.json", payload)
    write_result("per_turn_prices.json", per_turn_table)
    print(json.dumps(payload["models"], indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
