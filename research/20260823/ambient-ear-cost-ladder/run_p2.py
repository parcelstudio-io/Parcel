"""P2 — the local-first ladder: rows C6 and C8, and the pairs C7 is scored on.

    .parcel/bin/python run_p2.py        (research folder + repo root on PYTHONPATH)

The ladder, per turn:

1. **triage** (``voice/engagement.triage_in_exchange``). ``hear_only`` and
   ``acknowledge`` cost nothing and produce no hosted call.
2. **typed escalation** on the utterance (``escalation_for``): needs_tool,
   needs_memory, long_form. Those go straight to the hosted arm.
3. **local answer** for everything left, on the GPU reasoner, under the SAME
   rendered session instructions the hosted capture used.
4. **post-hoc escalation** (``escalation_after``): a local answer that hedged or
   said nothing is retried hosted, and counts as escalated.

Both triages are run and both are reported. The context-free one is the
tranche-2 card's literal function; the exchange-aware one is what the ladder
actually uses, and the gap between them is a result in itself.

The hosted arm is REPLAY: the corpus's own captured answer and its own captured
usage row. No socket is opened here and no money is spent.
"""

from __future__ import annotations

import json
import statistics
import subprocess
import sys
import time
from collections import Counter

from ladder import (
    AUDIO_TOKENS_PER_SECOND,
    CARDS,
    DAYS_PER_MONTH,
    LISTEN_HOURS_PER_DAY,
    RESULTS_DIR,
    audio_row_from_text_row,
    load_utterances,
    measured_words_per_second,
    write_result,
)
from local_arm import LocalArm

from evals.companion.realtime_convo_v1.schema import load_fixtures
from parcel_robot.realtime.prompting import render_session_instructions
from parcel_robot.voice.engagement import (
    TIER_ANSWER,
    escalation_after,
    triage,
    triage_in_exchange,
)

#: Modelled seconds between turns inside one captured thread. Any value under
#: ``EXCHANGE_WINDOW_S`` gives the same tiers; it is stated so the exchange
#: assumption is visible rather than implied.
TURN_GAP_S = 20.0

#: How much of the thread the local arm is shown. The reasoner is served with
#: an 8192-token context and the SI alone is ~600; six prior turns is the
#: deepest history any corpus thread reaches before this bites.
HISTORY_TURNS = 6


def nvidia_smi() -> str:
    try:
        out = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=memory.used,memory.total,utilization.gpu",
                "--format=csv,noheader",
            ],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        return out.stdout.strip()
    except (OSError, subprocess.SubprocessError) as error:  # pragma: no cover
        return f"unavailable: {error}"


def ladder_costs(rows: list[dict], hosted: list[dict]) -> dict[str, object]:
    """C8, three ways, from the measured facts rather than the assumed ones.

    ``transcript`` — the ladder escalates a TRANSCRIPT and the local voice reads
    the reply. That is what the corpus rows measure, exactly, so this figure is
    the one with the least modelling under it.

    ``audio`` — the ladder hands the hosted model the audio instead, so an
    escalated turn costs what P0's audio model says a turn costs.

    ``gated_listening`` — the extra input the hosted ear is billed while a
    P1-style gate holds the socket open. Computed on SPEECH seconds and not on
    open-gate seconds, because the live run measured that the provider bills the
    speech its own VAD finds, not the stream it was handed.
    """

    p1 = json.loads((RESULTS_DIR / "p1_vad_gate.json").read_text(encoding="utf-8"))
    gate = next(r for r in p1["owner"] if r["hangover_ms"] == 500.0 and r["preroll_ms"] == 500.0)
    utterances_seen = sum(1 for row in gate["rows"] if row["opened"])
    live = json.loads((RESULTS_DIR / "live_calibration.json").read_text(encoding="utf-8"))
    ratios = [
        int((r["raw_usage"].get("output_token_details") or {}).get("audio_tokens", 0) or 0)
        / max(1, int((r["raw_usage"].get("output_token_details") or {}).get("text_tokens", 0) or 0))
        for r in live["rows"]
        if int((r["raw_usage"].get("output_token_details") or {}).get("text_tokens", 0) or 0) >= 20
        and int((r["raw_usage"].get("output_token_details") or {}).get("audio_tokens", 0) or 0) > 0
    ]
    audio_ratio = statistics.mean(ratios) if ratios else 1.5
    wps = measured_words_per_second(load_utterances())

    # Audio seconds a gated ear would upload in a day: the P1 tape's measured
    # uploaded seconds per utterance, scaled to the pre-registered 174-turn day.
    # Uploaded, not spoken — it includes pre-roll and hangover, so the listening
    # term below is an OVERstatement, which is the safe direction for a ceiling.
    uploaded_s_per_utterance = float(gate["uploaded_s"]) / max(1, utterances_seen)
    uploaded_audio_s_per_day = uploaded_s_per_utterance * len(rows)

    out: dict[str, object] = {}
    for name, card in CARDS.items():
        transcript_day = sum(card.priced_usd(dict(r["usage"])) for r in hosted)
        all_day = sum(card.priced_usd(dict(r["usage"])) for r in rows)
        audio_day = 0.0
        carried: dict[str, int] = {}
        for row in hosted:
            usage = dict(row["usage"])
            audio_usage = audio_row_from_text_row(
                usage,
                owner_words=len(str(row["owner_text"]).split()),
                robot_words=len(str(row["hosted_text"]).split()),
                words_per_second=wps,
                history_audio_tokens=carried.get(str(row["thread"]), 0),
                audio_out_per_text_out=audio_ratio,
            )
            carried[str(row["thread"])] = carried.get(str(row["thread"]), 0) + int(
                audio_usage.pop("_new_history_audio")
            )
            audio_usage.pop("_robot_words", None)
            audio_day += card.priced_usd(audio_usage)
        listening_month = (
            uploaded_audio_s_per_day
            * AUDIO_TOKENS_PER_SECOND
            * card.audio_input_usd_per_mtok
            / 1e6
            * DAYS_PER_MONTH
        )
        out[name] = {
            "escalated_turns_transcript_usd_per_day": round(transcript_day, 6),
            "escalated_turns_audio_usd_per_day": round(audio_day, 6),
            "all_turns_hosted_transcript_usd_per_day": round(all_day, 6),
            "gated_listening_usd_per_month": round(listening_month, 4),
            "p2_usd_per_month_transcript_escalation": round(transcript_day * DAYS_PER_MONTH, 2),
            "p2_usd_per_month_audio_escalation": round(
                audio_day * DAYS_PER_MONTH + listening_month, 2
            ),
            "listen_hours_per_day": LISTEN_HOURS_PER_DAY,
            "uploaded_audio_s_per_day": round(uploaded_audio_s_per_day, 1),
            "p1_utterances_seen": utterances_seen,
            "p1_uploaded_s_per_utterance": round(uploaded_s_per_utterance, 3),
        }
    return out


def main() -> int:
    if "--recost" in sys.argv:
        payload = json.loads((RESULTS_DIR / "p2_ladder.json").read_text(encoding="utf-8"))
        rows = payload["rows"]
        payload["costs"] = ladder_costs(rows, [r for r in rows if r["route"] == "hosted"])
        write_result("p2_ladder.json", payload)
        print(json.dumps(payload["costs"], indent=1))
        return 0

    arm = LocalArm()
    if not arm.health():
        raise SystemExit(f"local arm at {arm.base_url} is not answering /health")

    gpu_before = nvidia_smi()
    started = time.time()
    rows: list[dict[str, object]] = []
    tiers_free: Counter[str] = Counter()
    tiers_exchange: Counter[str] = Counter()
    escalations: Counter[str] = Counter()

    for fixture in load_fixtures():
        system = render_session_instructions(profile_id=fixture.si_profile, flags=fixture.flags).text
        history: list[tuple[str, str]] = []
        for turn in fixture.turns:
            owner_text = turn.owner_text
            tiers_free[triage(owner_text).tier] += 1
            verdict = triage_in_exchange(
                owner_text,
                seconds_since_addressed=None if turn.index == 0 else TURN_GAP_S,
            )
            tiers_exchange[verdict.tier] += 1
            row: dict[str, object] = {
                "thread": fixture.thread_id,
                "family": fixture.family,
                "index": turn.index,
                "owner_text": owner_text,
                "hosted_text": turn.robot_text,
                "usage": dict(turn.usage),
                "tier": verdict.tier,
                "tier_reason": verdict.reason,
                "pre_escalation": verdict.escalation,
            }
            if verdict.tier == TIER_ANSWER:
                if verdict.escalation:
                    row["route"] = "hosted"
                    row["escalation"] = verdict.escalation
                    escalations[verdict.escalation] += 1
                else:
                    local = arm.answer(system, history[-HISTORY_TURNS * 2 :], owner_text)
                    row["local_text"] = local
                    post = escalation_after(local)
                    if post:
                        row["route"] = "hosted"
                        row["escalation"] = post
                        escalations[post] += 1
                    else:
                        row["route"] = "local"
                        row["escalation"] = ""
            else:
                row["route"] = "silent"
                row["escalation"] = ""
            rows.append(row)
            history.append(("user", owner_text))
            history.append(("assistant", turn.robot_text))
        print(f"  {fixture.thread_id}: {len(fixture.turns)} turns", flush=True)

    gpu_after = nvidia_smi()
    total = len(rows)
    hosted = [r for r in rows if r["route"] == "hosted"]
    local_rows = [r for r in rows if r["route"] == "local"]
    silent = [r for r in rows if r["route"] == "silent"]
    answered = hosted + local_rows

    costs = ladder_costs(rows, hosted)

    payload = {
        "harness": "p2_local_first_ladder",
        "turn_gap_s": TURN_GAP_S,
        "history_turns": HISTORY_TURNS,
        "local_model": arm.model,
        "local_base_url": arm.base_url,
        "gpu_before": gpu_before,
        "gpu_after": gpu_after,
        "wall_s": round(time.time() - started, 1),
        "turns": total,
        "tiers_context_free": dict(tiers_free),
        "tiers_in_exchange": dict(tiers_exchange),
        "escalations_by_reason": dict(escalations),
        "counts": {
            "hosted": len(hosted),
            "local": len(local_rows),
            "silent": len(silent),
            "answered_or_escalated": len(answered),
        },
        "escalation_rate_all_turns": round(len(hosted) / total, 4),
        "escalation_rate_answered": round(len(hosted) / len(answered), 4) if answered else None,
        "local_latency_s": {
            "n": len(arm.latencies_s),
            "p50": round(statistics.median(arm.latencies_s), 3) if arm.latencies_s else None,
            "p95": (
                round(sorted(arm.latencies_s)[max(0, int(0.95 * len(arm.latencies_s)) - 1)], 3)
                if arm.latencies_s
                else None
            ),
        },
        "costs": costs,
        "rows": rows,
    }
    write_result("p2_ladder.json", payload)
    print(json.dumps({k: v for k, v in payload.items() if k != "rows"}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
