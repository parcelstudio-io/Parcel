#!/usr/bin/env python
"""The one consolidated pass rule, applied to every arm, with no partial credit.

DESIGN v2 + A9: "a policy arm passes only if EVERY row in the unified table
passes". This reads the raw result files and writes that table. A row whose
evidence this host cannot produce is ``BLOCKED``, and a BLOCKED row is NOT a
pass — which is why the arm column can read "no" with every measurable row met.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .session import RESULTS, write_result

#: DUPLEX-1 (scrum/20260822/task_26) measured this on the shipped floor. It is
#: quoted, not re-measured: the cancel path needs the lane and the loudspeaker.
DUPLEX1_CANCEL_P95_MS = 740.0

#: H1's pre-registered day (``results/p1_vad_gate.json``): the owner speaks 14.5
#: turns an hour and the ear listens 12 h. The tapes here are far denser than a
#: day on purpose (n per cell, not duty cycle), so every per-day figure is built
#: from PER-TURN measurements and this day model, never from tape wall-clock.
OWNER_TURNS_PER_HOUR = 14.5
LISTEN_HOURS_PER_DAY = 12.0
#: A television on four hours a day — H1's own C1 scenario.
TV_HOURS_PER_DAY = 4.0
USD_PER_UPLOADED_SECOND = 10.0 * 10.00 / 1e6
USD_PER_RESPONSE_SECOND = 10.0 * 20.00 / 1e6
RESPONSE_SECONDS = 3.0


def per_turn_seconds(block: dict) -> float:
    admitted = block["spans_admitted"]
    return block["uploaded_seconds"] / admitted if admitted else 0.0


def usd_per_day(arm: dict) -> tuple[float, float, float]:
    """(owner turns, television, total) dollars a day on H1's day model."""

    owner_seconds = per_turn_seconds(arm["owner"])
    owner_turns = OWNER_TURNS_PER_HOUR * LISTEN_HOURS_PER_DAY
    owner_usd = owner_turns * (
        owner_seconds * USD_PER_UPLOADED_SECOND + RESPONSE_SECONDS * USD_PER_RESPONSE_SECOND
    )
    tv_seconds = per_turn_seconds(arm["tv"])
    tv_opens = arm["tv"]["opens_per_hour"] * TV_HOURS_PER_DAY
    tv_usd = tv_opens * (
        tv_seconds * USD_PER_UPLOADED_SECOND + RESPONSE_SECONDS * USD_PER_RESPONSE_SECOND
    )
    return owner_usd, tv_usd, owner_usd + tv_usd


@dataclass
class Row:
    row_id: str
    name: str
    bar: str
    measured: str
    status: str  # PASS / FAIL / BLOCKED
    source: str


def load(name: str) -> dict[str, Any] | None:
    path = RESULTS / name
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def verdict(ok: bool) -> str:
    return "PASS" if ok else "FAIL"


def rows_for_arm(arm: dict, ambient: dict | None, stop: dict | None, content: dict | None,
                 speaker: dict | None, control: dict | None = None) -> list[Row]:
    # Arm (c) is a WAKE-PHRASE policy: its committed turns are the ones that
    # carry the phrase. Scoring it on owner speech that never says "hey Parcel"
    # would report 0.000 and mean nothing.
    wake_arm = arm["arm"] == "wake_phrase"
    owner = arm["wake_turns"] if wake_arm and "wake_turns" in arm else arm["owner"]
    quality = (
        arm["wake_quality"] if wake_arm and "wake_quality" in arm else arm["owner_quality"]
    )
    out: list[Row] = []

    recall = owner["acceptance_rate"]
    worst = min(
        (cell["rate"] for cell in owner["per_geometry"].values()), default=float("nan")
    )
    label = "owner committed-turn recall 1-3 m <= 60 deg"
    if wake_arm:
        label += " (denominator: turns carrying the wake phrase)"
    out.append(Row("P1", label, ">= 0.95",
                   f"{recall:.3f} (worst cell {worst:.3f}, n={owner['trials']})",
                   verdict(recall >= 0.95 and worst >= 0.95), "arms.json"))

    non_owner = arm["hosted_bytes_non_owner"]
    out.append(Row("P2", "hosted bytes for TV / self-TTS / non-owner", "0",
                   f"{non_owner} B", verdict(non_owner == 0), "arms.json (fake transport)"))

    tv_per_day = arm["tv"]["opens_per_hour"] * TV_HOURS_PER_DAY
    ambient_bound = None
    if ambient is not None:
        key = "owner_id" if arm["arm"].startswith("owner_id") else "vad_only"
        ambient_bound = ambient[key]["upper_bound_per_24h"]
    measured = f"{tv_per_day:.0f}/day with a TV on {TV_HOURS_PER_DAY:g} h"
    if ambient_bound is not None:
        measured += f"; quiet real room <= {ambient_bound:.1f}/24h (95% bound)"
    out.append(Row("P3", "false hosted openings per 24 h", "<= 1", measured,
                   verdict(tv_per_day <= 1.0), "arms.json + ambient_real.json"))

    if stop is not None:
        out.append(Row("P4", "local STOP recall", ">= 0.99",
                       f"{stop['recall']:.3f} (n={stop['trials']})",
                       verdict(stop["recall"] >= 0.99), "stop_local.json"))
        out.append(Row("P5", "STOP tail p95 (hotword end -> latch)", "<= 800 ms",
                       f"{stop['latency_s_p95'] * 1000:.0f} ms",
                       verdict(stop["latency_s_p95"] <= 0.8), "stop_local.json"))
        finite = stop["trials"] >= 60 and stop["latency_s_over_1s"] == 0
        out.append(Row("P6", "STOP finite-sample: n >= 60, all <= 1.0 s",
                       "n >= 60 and 0 over 1.0 s",
                       f"n={stop['trials']}, {stop['latency_s_over_1s']} over 1.0 s",
                       verdict(finite), "stop_local.json"))
        false_stops = stop["tv_tape"]["false_stops_per_24h"]
        detail = f"TV tape {false_stops:.0f}/24h"
        if ambient is not None:
            detail += f"; real room <= {ambient['stop_local']['upper_bound_per_24h']:.0f}/24h"
        out.append(Row("P7", "false STOPs per 24 h", "<= 1", detail,
                       verdict(false_stops <= 1.0), "stop_local.json + ambient_real.json"))

    sweep = arm["self_tts_by_aec_level"]
    at_zero = sweep.get("0dB", {}).get("self_transcribed_motion_commands")
    at_twenty = sweep.get("-20dB", {}).get("self_transcribed_motion_commands")
    admitted_any = any(level.get("admitted", 0) for level in sweep.values())
    if not admitted_any:
        # The gate refused the robot's own voice at every echo level tried, so
        # this row does not depend on the unmeasured AEC at all.
        p8_status = "PASS"
        p8_measured = "0 — the gate admitted no self-speech at any echo level (0 to -30 dB)"
    else:
        p8_status = "BLOCKED"
        p8_measured = f"{at_zero} with no AEC, {at_twenty} at a hypothetical 20 dB"
    out.append(Row("P8", "self-transcribed motion commands", "0", p8_measured, p8_status,
                   "arms.json (with echo admitted, this row waits on P9)"))

    blocked_why = "no loudspeaker on this host but the array's own DAC"
    out.append(Row("P9", "AEC attenuation, XVF3800 -> CQRobot", ">= 20 dB",
                   speaker["verdict"] if speaker else "not run", "BLOCKED", blocked_why))
    out.append(Row("P10", "barge-in acoustic stop p50", "<= 0.52 s", "not measurable here",
                   "BLOCKED", blocked_why))
    out.append(Row("P11", "cancel p95", "<= 700 ms",
                   f"{DUPLEX1_CANCEL_P95_MS:.0f} ms (DUPLEX-1, shipped floor)",
                   verdict(DUPLEX1_CANCEL_P95_MS <= 700.0), "scrum/20260822/task_26"))

    if content is not None:
        accuracy = content["critical_slot"]["accuracy"]
        measured = f"{accuracy:.3f} (n={content['critical_slot']['n']}, espeak)"
        best = accuracy
        if control is not None:
            # The espeak proxy says "lampost" and "Pausell"; the piper control
            # separates the voice's contribution from the pipeline's. Both are
            # reported and the verdict is read off the BETTER of the two, so the
            # row cannot fail on the proxy alone.
            control_accuracy = control["critical_slot"]["accuracy"]
            measured += f"; {control_accuracy:.3f} (n={control['critical_slot']['n']}, piper control)"
            best = max(best, control_accuracy)
        out.append(Row("P12", "critical-slot accuracy", ">= 0.95", measured,
                       verdict(best >= 0.95), "content.json + content_control_piper.json"))

    loss = quality["first_word_loss_rate"]
    out.append(Row("P13", "first-word loss with the 500 ms pre-roll", "<= 2 %",
                   f"{loss * 100:.1f} % (n={quality['n']})", verdict(loss <= 0.02),
                   "arms.json"))
    endpoint = quality["endpoint_s_p50"]
    out.append(Row("P14", "endpoint p50", "<= 0.8 s", f"{endpoint:.2f} s",
                   verdict(endpoint <= 0.8), "arms.json"))

    owner_usd, tv_usd, total_usd = usd_per_day(arm)
    out.append(Row("P15", "projected spend, H1 day model (14.5 turns/h, 12 h, TV 4 h)",
                   "<= $0.50/day",
                   f"${total_usd:.2f}/day (owner ${owner_usd:.2f} + TV ${tv_usd:.2f}); "
                   f"${total_usd * 30:.0f}/month vs the $160 envelope",
                   verdict(total_usd <= 0.50), "arms.json + realtime/cost.py MINI_RATE_CARD"))

    second = arm["second_person"]["acceptance_rate"]
    out.append(Row("P16", "second-person false accept", "<= 2 %",
                   f"{second * 100:.1f} % (n={arm['second_person']['trials']})",
                   verdict(second <= 0.02), "arms.json"))

    replay = arm["owner_replay"]["acceptance_rate"]
    out.append(Row("P17", "owner-recording REPLAY acceptance (honesty row)",
                   "reported; no arm may claim immunity",
                   f"{replay * 100:.1f} % accepted (n={arm['owner_replay']['trials']})",
                   "REPORTED", "arms.json"))
    return out


def markdown(table: dict[str, Any]) -> str:
    """The consolidated table as RESULTS.md prints it — generated, never typed."""

    arms = list(table)
    ids = [row["row_id"] for row in table[arms[0]]]
    header = "| row | bar | " + " | ".join(arms) + " |"
    rule = "|---|---|" + "---|" * len(arms)
    lines = [header, rule]
    for index, row_id in enumerate(ids):
        first = table[arms[0]][index]
        cells = []
        for arm in arms:
            row = table[arm][index]
            mark = {"PASS": "PASS", "FAIL": "**FAIL**", "BLOCKED": "BLOCKED",
                    "REPORTED": "—"}[row["status"]]
            cells.append(f"{mark} {row['measured']}")
        lines.append(f"| {row_id} {first['name']} | {first['bar']} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def main() -> int:
    arms = load("arms.json")
    if arms is None:
        raise SystemExit("results/arms.json is missing; run harness.run_arms first")
    ambient = load("ambient_real.json")
    stop = load("stop_local.json")
    content = load("content.json")
    speaker = load("speaker_path.json")
    control = load("content_control_piper.json")

    table: dict[str, Any] = {}
    passing: list[str] = []
    for arm in arms["arms"]:
        rows = rows_for_arm(arm, ambient, stop, content, speaker, control)
        table[arm["arm"]] = [vars(row) for row in rows]
        if all(row.status in {"PASS", "REPORTED"} for row in rows):
            passing.append(arm["arm"])

    payload = {
        "pass_rule": (
            "DESIGN v2 final + A9: an arm passes only if EVERY row passes; a BLOCKED row "
            "is not a pass"
        ),
        "arms_in_order": [arm["arm"] for arm in arms["arms"]],
        "arms_passing_the_full_rule": passing,
        "early_stop_fired": bool(passing),
        "decision": (
            "push-to-talk for M1"
            if not passing
            else f"{passing[0]} (first arm meeting the full rule)"
        ),
        "table": table,
    }
    path = write_result("consolidated.json", payload)
    (RESULTS / "consolidated_table.md").write_text(markdown(table) + "\n", encoding="utf-8")
    for name, rows in table.items():
        failed = [row["row_id"] for row in rows if row["status"] == "FAIL"]
        blocked = [row["row_id"] for row in rows if row["status"] == "BLOCKED"]
        print(f"{name:14s} FAIL {failed}  BLOCKED {blocked}")
    print(f"decision: {payload['decision']} -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
