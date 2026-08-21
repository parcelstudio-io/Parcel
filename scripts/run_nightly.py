#!/usr/bin/env python
"""The nightly, stood up. Card R26 (``scrum/20260821/task_5``).

WHY THIS FILE EXISTS
--------------------
``scripts/ci_gate.py --tier nightly`` has existed since 2026-08-09 and
``.github/workflows/ci.yml`` has declared an 08:00 UTC cron for it. The full
audit (``scrum/20260820/AUDIT_FULL_FABLE.md`` §Tests) established that **it had
never produced a recorded run anywhere** — which means the 42 tests the commit
tier deselects, the entire voice-to-nav end-to-end tier among them, had never
run in this project's history. A gate whose green has never included the e2e
path is a green about something else.

Two things were missing, and this file is both of them:

1. **A durable, dated artifact.** ``ci_gate`` prints to a terminal and exits.
   Terminals are not evidence. Every eval pack in this repo answers "when did
   this last run and what did it say" from a folder and an append-only ledger;
   the nightly now does too, in the same shape.
2. **One command that runs everything the nightly is supposed to run** — the
   gate's nightly tier, EV-1's nightly judge/review-queue runner, and the
   future-clock time-bomb sweep — and returns ONE exit code that is not
   swallowed.

WHAT IT WRITES
--------------
``evals/nightly/<YYYYMMDD>T<HHMMSS>Z/``

``results.json``
    every stage with its status, detail and extras; the run's verdict; the
    environment it ran in (git head, dirty flag, interpreter, host load).
``README.md``
    the same thing for a human, including the failures. A run folder whose
    README omits what went wrong is a press release.
``gate.txt``
    the gate's own ``summarize()`` output, verbatim, so the artifact and the
    terminal cannot disagree.

and appends one row to ``evals/nightly/ledger.jsonl`` — the file that answers
"has the nightly ever run" without reading a status doc.

EXIT CODE
---------
Non-zero iff a HARD stage is red, and the folder is written **before** the exit,
so a red nightly still leaves its evidence behind. ``--allow-red`` exists for
one purpose — proving in ``tests/test_nightly_runner.py`` that the default does
NOT swallow the failure — and it prints a loud line saying it was used.

COST
----
The judge stage is the only stage that can spend money. It is off unless
``--judge`` is passed, it is bounded by ``evals.assertions.nightly``'s own
spend cap, and the estimate it reports is written into ``results.json``.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from scripts import load_guard
from scripts.ci_gate import (
    COMMIT_MARKERS,
    GateResult,
    run_nightly_tier,
    run_pytest,
    summarize,
)

DEFAULT_OUT = REPO / "evals" / "nightly"
LEDGER_NAME = "ledger.jsonl"

#: How far the time-bomb sweep moves the calendar. 400 days crosses a year
#: boundary, every month boundary, and a leap-year February from any start date,
#: which is what makes it a sweep of the CLASS rather than a spot check.
DEFAULT_FUTURE_CLOCK_DAYS = 400


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------


def _git(*args: str) -> str:
    """Run a git command and return stdout with only the TRAILING newline gone.

    ``.strip()`` was the obvious thing to write here and it was wrong: the first
    line of ``git status --porcelain`` begins with a space for an unstaged
    modification, so stripping ate it and the first entry of ``git_dirty_paths``
    came out as ``onfigs/realtime.yaml.example``. Caught by reading the FIRST
    nightly's own provenance block, which is the sort of thing an artifact is
    for; the run folder ``20260821T102132Z`` carries the truncated value and
    ``R26_STATUS.md`` §3.5 says so. ``rstrip("\\n")`` keeps every leading column.
    """

    try:
        proc = subprocess.run(
            ["git", *args], cwd=str(REPO), capture_output=True, text=True, check=False, timeout=30
        )
    except (OSError, subprocess.SubprocessError):  # pragma: no cover - no git
        return ""
    return (proc.stdout or "").rstrip("\n")


def environment() -> dict[str, Any]:
    """Everything a reader needs to know this run happened on THIS tree.

    The dirty flag matters more here than in most places: the wave this card
    lands into is largely uncommitted, so a nightly recorded against a clean
    HEAD sha alone would be attributing its result to code the sha does not
    contain. The list of dirty paths is recorded, not just the boolean.
    """

    dirty = [line for line in _git("status", "--porcelain").splitlines() if line.strip()]
    return {
        "git_head": _git("rev-parse", "HEAD"),
        "git_head_subject": _git("log", "-1", "--pretty=%s"),
        "git_dirty": bool(dirty),
        "git_dirty_paths": [line[3:] for line in dirty],
        "python": sys.version.split()[0],
        "executable": sys.executable,
        "platform": platform.platform(),
        "hostname": platform.node(),
        "cpus": os.cpu_count(),
        "load_at_start": load_guard.snapshot(),
        "mujoco_gl": os.environ.get("MUJOCO_GL", ""),
    }


# ---------------------------------------------------------------------------
# Stages
# ---------------------------------------------------------------------------


def stage_gate() -> tuple[list[GateResult], str, float]:
    """The nightly tier of the existing gate, unchanged and in full."""

    started = time.perf_counter()
    results = run_nightly_tier()
    elapsed = time.perf_counter() - started
    return results, summarize(results, "nightly", elapsed), elapsed


def stage_future_clock(days: int, *, markers: str = COMMIT_MARKERS) -> GateResult:
    """Run the fast suite with the calendar moved forward. Card R26 item 5.

    HARD on purpose. Everything it catches was already broken on a future date;
    the only question was whether this project found out here or in an unrelated
    card's commit gate a month from now. The sweep runs the ``not slow``
    selection because the slow tier's cost is dominated by simulation, not by
    anything calendar-dependent, and a second 40-minute pass buys little.
    """

    proc = run_pytest(
        (),
        markers=markers,
        plugins=["scripts.future_clock"],
        env_extra={
            "PARCEL_FUTURE_CLOCK_DAYS": str(days),
            # The sweep must not ALSO be measuring a contended machine: a
            # wall-clock red here would be attributed to the calendar.
            "PARCEL_LOAD_GUARD": "on",
        },
        extra_args=["-rf"],
        timeout=3600,
    )
    tail = (proc.stdout or "").strip().splitlines()
    summary = tail[-1] if tail else ""
    if proc.returncode == 0:
        return GateResult(
            "future-clock-sweep", "nightly", True, "pass",
            f"+{days}d: {summary}",
            extra={"days": days, "markers": markers},
        )
    fails = [ln for ln in tail if ln.startswith(("FAILED", "ERROR"))]
    return GateResult(
        "future-clock-sweep", "nightly", True, "fail",
        f"+{days}d: {summary}" + ("\n    " + "\n    ".join(fails[:20]) if fails else ""),
        extra={"days": days, "markers": markers, "failures": fails, "returncode": proc.returncode},
    )


def stage_assertion_nightly(*, judge: bool, k: int = 3) -> GateResult:
    """EV-1's nightly runner: trend lines and a review queue. NEVER gates.

    Soft by construction, and that is EV-1's measured decision, not laziness:
    the judge produced 2 hard false positives per run on human-PASSED behaviours
    and invented 6 incidents on a by-construction-clean session. Wiring a gate to
    it would make the nightly lie. It is here because the review queue is worth
    a human's morning.
    """

    name = "assertion-nightly"
    try:
        from evals.assertions.gate import FIXTURE_DIGESTS, FIXTURE_ROOT
        from evals.assertions.nightly import run_nightly
    except Exception as exc:  # noqa: BLE001
        return GateResult(name, "nightly", False, "error", f"import failed: {exc}")
    sessions = [FIXTURE_ROOT / folder for folder in sorted(FIXTURE_DIGESTS)]
    missing = [str(path) for path in sessions if not path.is_dir()]
    if missing:
        return GateResult(name, "nightly", False, "error", f"missing fixture(s): {missing}")
    try:
        payload = run_nightly(
            sessions, out_root=REPO / "evals" / "assertions" / "nightly", k=k, judge=judge
        )
    except Exception as exc:  # noqa: BLE001
        return GateResult(name, "nightly", False, "error", f"{type(exc).__name__}: {exc}")
    judged = payload["judge"]
    return GateResult(
        name, "nightly", False, "report",
        (
            f"{len(sessions)} fixture session(s), pass^{k}; review queue "
            f"{len(payload['review_queue'])} item(s); judge "
            f"{'on' if judge else 'OFF (--judge not passed)'}"
            f", estimated ${judged['estimated_spend_usd']} of ${judged['spend_cap_usd']} cap"
        ),
        extra={
            "run": payload["run"],
            "review_queue_size": len(payload["review_queue"]),
            "estimated_spend_usd": judged["estimated_spend_usd"],
            "judge_enabled": judged["enabled"],
            "judge_errors": sorted(
                {
                    unit["error"]
                    for unit in judged["units"].values()
                    if isinstance(unit, dict) and unit.get("error")
                }
            ),
        },
    )


# ---------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------


def _readme(payload: dict[str, Any], gate_text: str) -> str:
    red = [row for row in payload["stages"] if row["hard"] and row["status"] in {"fail", "error"}]
    soft_red = [
        row for row in payload["stages"] if not row["hard"] and row["status"] in {"fail", "error"}
    ]
    lines = [
        f"# Nightly run — {payload['run']}",
        "",
        (
            f"Started `{payload['started_at']}` · elapsed {payload['elapsed_s']:.1f}s · "
            f"verdict **{payload['verdict']}** (exit {payload['exit_code']})."
        ),
        "",
        "Produced by `scripts/run_nightly.py` (card R26). This folder is the whole",
        "record of the run, including what failed — a nightly that only publishes its",
        "greens is not a nightly.",
        "",
        "## Stages",
        "",
        "| Stage | Gating | Status | Detail |",
        "| --- | --- | --- | --- |",
    ]
    for row in payload["stages"]:
        detail = str(row["detail"]).replace("\n", "<br>").replace("|", "\\|")
        lines.append(
            f"| `{row['name']}` | {'HARD' if row['hard'] else 'soft'} | "
            f"**{row['status']}** | {detail} |"
        )
    lines += ["", "## What went red", ""]
    if red or soft_red:
        for row in red:
            lines.append(f"* **HARD `{row['name']}`** — {row['detail']}")
        for row in soft_red:
            lines.append(f"* soft `{row['name']}` (non-gating) — {row['detail']}")
    else:
        lines.append("Nothing. Every hard stage green, no report-only stage red.")
    lines += [
        "",
        "## Provenance",
        "",
        "```json",
        json.dumps(payload["environment"], indent=1, sort_keys=True),
        "```",
        "",
        "## Gate output, verbatim",
        "",
        "```",
        gate_text,
        "```",
        "",
    ]
    return "\n".join(lines)


def run(
    *,
    out_root: Path = DEFAULT_OUT,
    judge: bool = False,
    future_clock_days: int | None = DEFAULT_FUTURE_CLOCK_DAYS,
    k: int = 3,
) -> dict[str, Any]:
    """Run every stage, write the dated folder, return the payload."""

    started = time.perf_counter()
    started_at = datetime.now(timezone.utc)
    stamp = started_at.strftime("%Y%m%dT%H%M%SZ")
    env = environment()

    gate_results, gate_text, gate_elapsed = stage_gate()
    stages: list[GateResult] = list(gate_results)

    if future_clock_days:
        stages.append(stage_future_clock(future_clock_days))
    else:
        stages.append(
            GateResult(
                "future-clock-sweep", "nightly", True, "error",
                "the time-bomb sweep was disabled for this run; a nightly without it "
                "cannot see a test that has not broken yet (card R26 item 5)",
            )
        )
    stages.append(stage_assertion_nightly(judge=judge, k=k))

    elapsed = time.perf_counter() - started
    gating_red = [row for row in stages if row.gating_red]
    payload: dict[str, Any] = {
        "run": stamp,
        "schema": "parcel.nightly.v1",
        "started_at": started_at.isoformat(),
        "elapsed_s": round(elapsed, 3),
        "gate_elapsed_s": round(gate_elapsed, 3),
        "verdict": "FAIL" if gating_red else "PASS",
        "exit_code": 1 if gating_red else 0,
        "gating_red": [row.name for row in gating_red],
        "soft_red": [row.name for row in stages if row.is_red and not row.hard],
        "stages": [row.as_dict() for row in stages],
        "environment": env,
        "load_at_end": load_guard.snapshot(),
        "produced_by": "scripts/run_nightly.py (card R26, scrum/20260821/task_5)",
    }

    folder = Path(out_root) / stamp
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "results.json").write_text(
        json.dumps(payload, indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (folder / "gate.txt").write_text(gate_text + "\n", encoding="utf-8")
    (folder / "README.md").write_text(_readme(payload, gate_text), encoding="utf-8")

    ledger = Path(out_root) / LEDGER_NAME
    ledger.parent.mkdir(parents=True, exist_ok=True)
    with ledger.open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "run": stamp,
                    "started_at": payload["started_at"],
                    "elapsed_s": payload["elapsed_s"],
                    "verdict": payload["verdict"],
                    "exit_code": payload["exit_code"],
                    "gating_red": payload["gating_red"],
                    "soft_red": payload["soft_red"],
                    "git_head": env["git_head"],
                    "git_dirty": env["git_dirty"],
                    "folder": f"evals/nightly/{stamp}",
                },
                sort_keys=True,
            )
            + "\n"
        )
    payload["folder"] = str(folder)
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument(
        "--judge", action="store_true",
        help="enable EV-1's hosted judge (spends money, capped in evals.assertions.nightly)",
    )
    parser.add_argument("-k", type=int, default=3, help="pass^k for the assertion suites")
    parser.add_argument(
        "--future-clock-days", type=int, default=DEFAULT_FUTURE_CLOCK_DAYS,
        help="days to move the calendar for the time-bomb sweep",
    )
    parser.add_argument(
        "--no-future-clock", action="store_true",
        help="skip the time-bomb sweep; the stage is then recorded as an ERROR, not omitted",
    )
    parser.add_argument(
        "--allow-red", action="store_true",
        help="return 0 even when a hard stage is red (test-only; prints a loud line)",
    )
    args = parser.parse_args(argv)

    payload = run(
        out_root=args.out,
        judge=args.judge,
        future_clock_days=None if args.no_future_clock else args.future_clock_days,
        k=args.k,
    )
    print(Path(payload["folder"], "gate.txt").read_text(encoding="utf-8"), end="")
    print("=" * 78)
    for row in payload["stages"]:
        if row["name"] in {"future-clock-sweep", "assertion-nightly"}:
            flag = "HARD" if row["hard"] else "soft"
            print(f"[{row['status']:>6}] {flag}  {row['name']}  {row['detail']}")
    print("=" * 78)
    print(f"NIGHTLY {payload['verdict']} — evidence: {payload['folder']}")
    if payload["gating_red"]:
        print(f"  hard stage(s) red: {', '.join(payload['gating_red'])}")
    if payload["soft_red"]:
        print(f"  report-only red (non-gating): {', '.join(payload['soft_red'])}")
    if payload["exit_code"] and args.allow_red:
        print(
            "  --allow-red: RETURNING 0 DESPITE A RED HARD STAGE. This flag exists only so "
            "tests/test_nightly_runner.py can prove the default does not do this."
        )
        return 0
    return int(payload["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
