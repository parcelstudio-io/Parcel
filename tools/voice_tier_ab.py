#!/usr/bin/env python3
"""Full-size gpt-realtime vs mini: the probe list, the protocol, the comparison.

CARD P2-B, DELIVERABLE 4 — AND WHAT IT DELIBERATELY DOES NOT DO
---------------------------------------------------------------
It never opens a hosted session. Not with a flag, not with an environment
variable, not by accident: there is no provider client in this file and no
import that could reach one. The owner runs the session; this script writes the
probe list, states the protocol, watches the stack's own ``/api/state`` with
READ-ONLY GETs while the owner talks, and produces the comparison table
afterwards. A tier experiment that a script could start on its own is a tier
experiment that will get run twice by mistake, and each run is real money.

THE ONE CONFIG LINE
-------------------
``configs/realtime.yaml`` (or the prototype example) already carries it::

    model: gpt-realtime-2.1-mini      # A — the cheap sibling, every live run so far
    model: gpt-realtime-2.1           # B — full size

Nothing else changes between the two arms. That is the experiment: same
persona, same tools, same whisperer knobs, same probes, in the same room.

THE PROTOCOL, IN FOUR STEPS
---------------------------
1. ``voice_tier_ab.py --plan --out <dir>`` — writes ``probes.tsv`` and
   ``scoresheet.md``, and prints the run order.
2. Set ``model:`` to arm A, launch the stack, and run
   ``voice_tier_ab.py --capture --tier mini --port <port> --out <dir>``. Speak
   each probe when prompted; press ENTER when the robot has finished answering.
3. Stop the stack, set ``model:`` to arm B, relaunch, and repeat with
   ``--tier full``. **Same room, same day, same order** — the tiers differ by
   one line and everything else is a confounder.
4. ``voice_tier_ab.py --compare <dir>/mini.json <dir>/full.json`` — prints the
   table and writes ``comparison.md``.

WHAT IT MEASURES, AND WHAT ONLY THE OWNER CAN
---------------------------------------------
Mechanical, from ``/api/state``: wall-clock time to the owner pressing ENTER,
billed usage rows, month-to-date spend delta, tool calls the broker admitted and
refused, whisperer forwards, refused items, stalls and reconnects. Those are
facts and this script decides them.

Everything that makes the full-size model worth four times the money —
whether the reply was *warm*, whether it asked the right follow-up, whether the
gesture it chose fitted the sentence — is a judgement, and the scoresheet asks
for it in the owner's own words rather than inventing a number.

USAGE
-----
    .parcel/bin/python tools/voice_tier_ab.py --plan --out ~/.cache/parcel-p2b/tier_ab
    .parcel/bin/python tools/voice_tier_ab.py --capture --tier mini --port 8823 \
        --out ~/.cache/parcel-p2b/tier_ab
    .parcel/bin/python tools/voice_tier_ab.py --compare <dir>/mini.json <dir>/full.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

#: The owner's own stack. Card P2-B's standing rule and ``run_voice_corpus.py``'s
#: refusal 1, kept identical on purpose: a tool that will drive port 8765 because
#: it was the default is a tool that will one day interrupt a live session.
OWNER_PORT = 8765

#: The two arms. Values are what goes in ``model:`` and nothing else moves.
TIER_MODELS = {
    "mini": "gpt-realtime-2.1-mini",
    "full": "gpt-realtime-2.1",
}


@dataclass(frozen=True)
class Probe:
    """One thing the owner says, and what the tiers are expected to differ on."""

    probe_id: str
    say: str
    #: The property this probe is FOR. One clause, so the scoresheet reads as a
    #: list of questions and not as a list of sentences.
    tests: str
    #: What a good answer looks like — the owner's rubric, not the script's.
    good: str
    #: What the mechanical side should show if the probe worked at all.
    mechanical: str


#: TWELVE PROBES. Deliberately short: this is one session of the owner's time and
#: a list nobody finishes is a list that produces no data. Ordered so the cheap,
#: repeatable ones come first and the ones that need the room come last.
PROBES: tuple[Probe, ...] = (
    Probe(
        "P01",
        "Hey — how are you doing?",
        "baseline warmth; does the first turn sound like a companion",
        "one or two sentences, in character, no status dump, no menu of options",
        "one usage row, no tool calls",
    ),
    Probe(
        "P02",
        "I'm feeling sad today.",
        "affect on the hosted lane (card P2-B deliverable 2)",
        "acknowledges the feeling first; the BODY offers something (a comfort bow)",
        "an [affect sad] ledger row and one gesture proposal",
    ),
    Probe(
        "P03",
        "Go to the coffee place.",
        "unknown place: ask, do not refuse and do not set off (card P0-B)",
        "asks WHICH place, and names the places it does know",
        "unknown_place ask, no navigate_to dispatch",
    ),
    Probe(
        "P04",
        "Come here, then sit down, and stay until I say otherwise.",
        "multi-step instruction held across one turn",
        "does the parts in order, or says plainly which part it will not do",
        "two or more admitted tool calls, no refusals of the whole sentence",
    ),
    Probe(
        "P05",
        "What did I tell you about my morning?",
        "memory recall from the session ledger",
        "recalls what was actually said, and says it does not know when it does not",
        "no tool call; a reply that quotes the earlier turn",
    ),
    Probe(
        "P06",
        "Actually — wait. Never mind that, tell me a joke instead.",
        "mid-turn correction and barge-in",
        "drops the previous thread cleanly, no 'as I was saying'",
        "a barge-in, one usage row, no orphaned tool call",
    ),
    Probe(
        "P07",
        "Do you remember what I like?",
        "owner model (card P2-A's surface, exercised from the voice side)",
        "answers from remembered facts, or asks to be told; never invents one",
        "recall_memory call or a clean 'I do not know yet'",
    ),
    Probe(
        "P08",
        "Can you walk over to the door and check if it's open?",
        "grounding a real navigation goal with a perception clause",
        "goes, or says why it cannot; does not claim to have looked from here",
        "navigate_to admitted, or a refusal with a reason",
    ),
    Probe(
        "P09",
        "Stop.",
        "the emergency latch, unchanged by the tier",
        "stops immediately and says so plainly",
        "the latch, from the ingress, in well under a second",
    ),
    Probe(
        "P10",
        "(after releasing the stop) Okay, we're good — what should we do now?",
        "recovery and initiative after a latch",
        "notices it was stopped, offers something specific rather than a menu",
        "an emergency_clear narration, then one reply",
    ),
    Probe(
        "P11",
        "(say nothing for two minutes while staying in the room)",
        "owner-event bands: greeting_due / question_of_the_day (deliverable 3)",
        "one short, warm opening — NOT a status report, and not three of them",
        "at most one whisperer forward inside the window; the rest folded",
    ),
    Probe(
        "P12",
        "(walk out, wait a minute, walk back in)",
        "greet-on-appearance (deliverable 3, pre-registered row 1)",
        "greets you once, within a few seconds of you coming back",
        "exactly one owner_appeared forward per appearance",
    ),
)

#: The ``/api/state`` paths the comparison reads, as dotted paths into the
#: realtime blob. Missing paths are reported as ``None`` rather than zero: "the
#: build did not publish this" and "it published zero" are different facts, and
#: an A/B that quietly turns the first into the second is an A/B that lies.
METRIC_PATHS: tuple[tuple[str, str], ...] = (
    ("usage_rows", "lane.usage_rows"),
    ("spend_usd", "lane.month_to_date.usd"),
    ("narrations", "lane.narrations"),
    ("refused_items", "lane.items_refused"),
    ("stalls", "lane.stalls"),
    ("reconnects", "lane.reconnects"),
    ("system_initiated", "lane.system_initiated_responses"),
    ("whisperer_forwarded", "whisperer.forwarded"),
    ("whisperer_suppressed", "whisperer.suppressed"),
    ("tool_calls", "broker.dispatched"),
    ("tool_refusals", "broker.refused"),
    ("affect_rows", "identity_labels.rows_written"),
)


def _dig(blob: Any, path: str) -> Any:
    node: Any = blob
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def _fetch_state(port: int, timeout: float = 5.0) -> dict[str, Any]:
    """One READ-ONLY GET of ``/api/state``. The only network call in this file."""

    url = f"http://127.0.0.1:{int(port)}/api/state"
    request = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _realtime_blob(state: dict[str, Any]) -> dict[str, Any]:
    blob = state.get("realtime")
    return blob if isinstance(blob, dict) else {}


def _metrics(blob: dict[str, Any]) -> dict[str, Any]:
    return {name: _dig(blob, path) for name, path in METRIC_PATHS}


def _delta(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in before:
        start, end = before.get(key), after.get(key)
        if isinstance(start, (int, float)) and isinstance(end, (int, float)):
            out[key] = round(end - start, 6)
        else:
            out[key] = None
    return out


def _resolve_out(raw: str) -> Path:
    """Absolute, printed, and never resolved against the cwd twice.

    ``run_voice_corpus.py``'s refusal 3, for the same reason: the 2026-08-20
    scoring run deposited its artifacts under a doubled repo-relative prefix.
    """

    out = Path(raw).expanduser()
    if not out.is_absolute():
        out = Path.cwd() / out
    parts = out.parts
    for index in range(len(parts) - 1):
        if parts[index] and parts[index] == parts[index + 1]:
            raise SystemExit(f"refusing a doubled path segment in --out: {out}")
    return out


def _write_plan(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    tsv = out / "probes.tsv"
    with tsv.open("w", encoding="utf-8") as handle:
        handle.write("id\tsay\ttests\tgood_looks_like\tmechanical\n")
        for probe in PROBES:
            handle.write(
                f"{probe.probe_id}\t{probe.say}\t{probe.tests}\t{probe.good}\t"
                f"{probe.mechanical}\n"
            )
    sheet = out / "scoresheet.md"
    lines = [
        "# Voice-tier A/B — the owner's scoresheet",
        "",
        "Arm A = `model: gpt-realtime-2.1-mini`  ·  Arm B = `model: gpt-realtime-2.1`",
        "",
        "Same room, same day, same order. One line changes between the arms.",
        "For each probe write a word or two — not a score out of ten. The",
        "mechanical numbers come from `--capture`; this sheet is for the half a",
        "program cannot decide.",
        "",
        "| probe | what it tests | A (mini) | B (full) | which one, and why |",
        "|---|---|---|---|---|",
    ]
    lines.extend(f"| {probe.probe_id} | {probe.tests} |  |  |  |" for probe in PROBES)
    lines.extend(
        [
            "",
            "## The question this is for",
            "",
            "Full size costs about four times the money. Is it four times the",
            "companion? Write the answer here in two sentences when both arms are",
            "done, before looking at the mechanical table — the numbers are for",
            "checking that answer, not for producing it.",
            "",
        ]
    )
    sheet.write_text("\n".join(lines), encoding="utf-8")
    print(f"probe list  : {tsv}")
    print(f"scoresheet  : {sheet}")


def _print_plan(out: Path) -> None:
    print("VOICE-TIER A/B — the one line that changes:")
    for tier, model in TIER_MODELS.items():
        print(f"  {tier:5s}  model: {model}")
    print()
    print("Run order:")
    print("  1. set model to the mini value, launch the stack")
    print("  2. voice_tier_ab.py --capture --tier mini --port <port> --out <dir>")
    print("  3. stop, set model to the full-size value, relaunch")
    print("  4. voice_tier_ab.py --capture --tier full --port <port> --out <dir>")
    print("  5. voice_tier_ab.py --compare <dir>/mini.json <dir>/full.json")
    print()
    print(f"{len(PROBES)} probes:")
    for probe in PROBES:
        print(f"  {probe.probe_id}  {probe.say}")
        print(f"        tests: {probe.tests}")
    print()
    _write_plan(out)


def _capture(tier: str, port: int, out: Path) -> int:
    if port == OWNER_PORT:
        raise SystemExit(
            f"port {OWNER_PORT} is the owner's own stack. Launch the A/B stack on "
            "its own port and pass that instead; this script will not attach to "
            "a session somebody else is having."
        )
    out.mkdir(parents=True, exist_ok=True)
    try:
        state = _fetch_state(port)
    except (urllib.error.URLError, OSError, ValueError) as error:
        raise SystemExit(f"no stack answering on port {port}: {error}") from None
    blob = _realtime_blob(state)
    model = _dig(blob, "config.model")
    expected = TIER_MODELS.get(tier)
    print(f"stack on :{port} reports model = {model!r} (arm '{tier}' expects {expected!r})")
    if model and expected and str(model) != expected:
        print("  ! the running stack is NOT on this arm's model. Fix `model:` and relaunch,")
        print("    or re-run with the tier that matches. Recording anyway would produce a")
        print("    labelled file that is wrong, which is worse than no file.")
        return 2
    rows: list[dict[str, Any]] = []
    print()
    print("Speak each probe to the robot. Press ENTER when it has finished answering.")
    print("Type 's' + ENTER to skip a probe, 'q' + ENTER to stop early.")
    for probe in PROBES:
        print()
        print(f"--- {probe.probe_id} ---")
        print(f"  SAY: {probe.say}")
        print(f"  looking for: {probe.good}")
        before = _metrics(_realtime_blob(_fetch_state(port)))
        started = time.monotonic()
        answer = input("  [ENTER when answered] ").strip().lower()
        elapsed = time.monotonic() - started
        if answer.startswith("q"):
            break
        after = _metrics(_realtime_blob(_fetch_state(port)))
        row = {
            "probe": probe.probe_id,
            "say": probe.say,
            "tests": probe.tests,
            "skipped": answer.startswith("s"),
            "elapsed_s": round(elapsed, 2),
            "before": before,
            "after": after,
            "delta": _delta(before, after),
        }
        rows.append(row)
        print(f"  {row['delta']}")
    path = out / f"{tier}.json"
    path.write_text(
        json.dumps(
            {
                "tier": tier,
                "model": model,
                "port": port,
                "captured_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "probes": rows,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print()
    print(f"wrote {path}")
    print("Fill in the scoresheet NOW, while you remember how it felt.")
    return 0


def _compare(left: Path, right: Path) -> int:
    arms = []
    for path in (left, right):
        try:
            arms.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError) as error:
            raise SystemExit(f"cannot read {path}: {error}") from None
    names = [str(arm.get("tier") or "?") for arm in arms]
    by_probe: dict[str, list[dict[str, Any]]] = {}
    for index, arm in enumerate(arms):
        for row in arm.get("probes", []):
            by_probe.setdefault(str(row.get("probe")), [{}, {}])[index] = row
    lines = [
        "# Voice-tier A/B — the mechanical half",
        "",
        (
            f"Arms: **{names[0]}** ({arms[0].get('model')}) vs "
            f"**{names[1]}** ({arms[1].get('model')})"
        ),
        "",
        "A blank cell is a probe one arm did not run. `None` means the build did",
        "not publish that number — which is not the same as zero.",
        "",
        (
            f"| probe | {names[0]} s | {names[1]} s | {names[0]} usage "
            f"| {names[1]} usage | {names[0]} tools | {names[1]} tools |"
        ),
        "|---|---|---|---|---|---|---|",
    ]
    for probe_id in sorted(by_probe):
        pair = by_probe[probe_id]
        # Column order matches the header exactly: one metric at a time, both
        # arms side by side, so the eye compares the two numbers that belong
        # together rather than the two that happen to be adjacent.
        cells = [probe_id, *(str(row.get("elapsed_s", "")) for row in pair)]
        for key in ("usage_rows", "tool_calls"):
            for row in pair:
                value = (row.get("delta") or {}).get(key)
                cells.append("" if value is None else str(value))
        lines.append("| " + " | ".join(cells) + " |")
    lines.extend(["", "## Totals", "", "| metric | " + " | ".join(names) + " |", "|---|---|---|"])
    for name, _ in METRIC_PATHS:
        values = []
        for arm in arms:
            total = 0.0
            seen = False
            for row in arm.get("probes", []):
                value = (row.get("delta") or {}).get(name)
                if isinstance(value, (int, float)):
                    total += value
                    seen = True
            values.append(f"{round(total, 6)}" if seen else "—")
        lines.append(f"| {name} | " + " | ".join(values) + " |")
    lines.extend(
        [
            "",
            "## What this does not decide",
            "",
            "Warmth, taste, and whether the follow-up question was the right one.",
            "Those are on the scoresheet, in the owner's words, and they are the",
            "reason the experiment exists — the numbers above only say what each",
            "arm cost and how much it did.",
            "",
        ]
    )
    text = "\n".join(lines)
    print(text)
    out = left.parent / "comparison.md"
    out.write_text(text, encoding="utf-8")
    print(f"wrote {out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Voice-tier A/B: probe list, capture protocol, comparison table."
    )
    parser.add_argument("--plan", action="store_true", help="write the probe list and scoresheet")
    parser.add_argument("--capture", action="store_true", help="record one arm, probe by probe")
    parser.add_argument("--compare", nargs=2, metavar=("A_JSON", "B_JSON"))
    parser.add_argument("--tier", choices=sorted(TIER_MODELS), help="which arm --capture records")
    parser.add_argument("--port", type=int, default=0, help="the A/B stack's panel port")
    parser.add_argument("--out", default="", help="where artifacts are written")
    args = parser.parse_args(argv)

    if args.compare:
        return _compare(Path(args.compare[0]).expanduser(), Path(args.compare[1]).expanduser())
    if args.capture:
        if not args.tier or not args.port:
            parser.error("--capture needs --tier and --port")
        return _capture(args.tier, args.port, _resolve_out(args.out or "."))
    _print_plan(_resolve_out(args.out or "."))
    return 0


if __name__ == "__main__":  # pragma: no cover - a CLI entry point
    sys.exit(main())
