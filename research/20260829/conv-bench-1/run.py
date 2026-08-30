"""CONV-1 runner — H-CV1a / H-CV1b / H-CV1c in one pass.

    .parcel/bin/python research/20260829/conv-bench-1/run.py --all

Writes ``results.json`` next to this file and leaves every per-suite artifact
under ``results/``.  Nothing here modifies ``evals/``: the two product evals are
invoked as modules with their outputs redirected, and the one write they make
into the tree regardless of ``--out`` (``evals/latency/ledger.jsonl``, appended
by ``run_duplex_v1``) is redirected with ``PARCEL_LATENCY_LEDGER``.

The acoustic loop is the only step that touches PipeWire and the only one that
costs minutes.  It therefore defaults to ``--acoustic reuse``: the recorded
artifact is read, not re-measured.  ``--acoustic run`` re-measures; it creates
its own null sinks and never opens a real device.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

FOLDER = Path(__file__).resolve().parent
REPO_ROOT = FOLDER.parents[2]
RESULTS = FOLDER / "results"
LOGS = FOLDER / "logs"
PY = str(REPO_ROOT / ".parcel/bin/python")

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# QEV-1's numbers (scrum/20260824/task_4/QUALITY_EVAL_REPORT.md), the rows
# H-CV1a and H-CV1b are read against.  Pre-registered; never edited to match.
QEV1 = {
    "corpus_threads": 25,
    "corpus_turns": 174,
    "corpus_hard_failures": 0,
    "corpus_review_flags": 66,
    "duplex_hard_gates": 7,
    "duplex_ttft_p50_ms": 35.7,
    "acoustic_cases": 25,
    "acoustic_gates_pass": 5,
    "acoustic_gates_total": 9,
    "acoustic_ep50_s": 0.812,
    "acoustic_bargein_stop_p50_s": 1.080,
    "acoustic_duplex_ack_p50_s": 0.850,
    "acoustic_prosody_apex": 0.5714,
}


def _env() -> dict[str, str]:
    env = dict(os.environ)
    env.pop("TMPDIR", None)
    env["PARCEL_LATENCY_LEDGER"] = str(RESULTS / "duplex" / "latency-ledger.jsonl")
    env["PARCEL_MEMORY_PATH"] = str(
        Path.home() / ".cache/parcel-0e/cv1/scratch_memory.sqlite3"
    )
    return env


def _run(argv: list[str], log: str) -> dict[str, Any]:
    LOGS.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    proc = subprocess.run(
        argv, cwd=REPO_ROOT, env=_env(), capture_output=True, text=True, check=False
    )
    wall = round(time.monotonic() - started, 3)
    (LOGS / f"{log}.stdout.txt").write_text(proc.stdout, encoding="utf-8")
    (LOGS / f"{log}.stderr.txt").write_text(proc.stderr, encoding="utf-8")
    return {"argv": argv[1:], "exit_code": proc.returncode, "wall_s": wall}


# ------------------------------------------------------------------- H-CV1a


def h_cv1a() -> dict[str, Any]:
    out = RESULTS / "cv1a-corpus-reviewed.json"
    review = (
        REPO_ROOT
        / "evals/companion/realtime_convo_v1/reviews/20260824-unblinded-ai-review.json"
    )
    row = _run(
        [
            PY,
            "-m",
            "evals.companion.realtime_convo_v1.score_corpus",
            "--review",
            str(review),
            "--require-review",
            "--output",
            str(out),
        ],
        "cv1a-reviewed",
    )
    report = json.loads(out.read_text(encoding="utf-8"))
    observed = {
        "corpus_threads": report["corpus"]["thread_count"],
        "corpus_turns": report["corpus"]["turn_count"],
        "corpus_hard_failures": report["machine"]["hard_failure_count"],
        "corpus_review_flags": report["machine"]["review_flag_count"],
    }
    expected = {k: QEV1[k] for k in observed}
    row.update(
        {
            "hypothesis": "H-CV1a",
            "artifact": str(out.relative_to(REPO_ROOT)),
            "observed": observed,
            "qev1_expected": expected,
            "reproduced": observed == expected,
            "machine_status": report["machine"]["status"],
            "review_flags_by_check": dict(
                sorted(
                    Counter(
                        f["check_id"]
                        for f in report["machine"]["findings"]
                        if f["severity"] == "review"
                    ).items()
                )
            ),
            "semantic_review": {
                "status": report["semantic_review"]["status"],
                "thread_verdicts": report["semantic_review"]["thread_verdicts"],
                "expectation_verdicts": report["semantic_review"][
                    "expectation_verdicts"
                ],
            },
            "prior_artifact_in_evals_results": (
                REPO_ROOT / "evals/companion/realtime_convo_v1/results"
            ).exists(),
        }
    )
    return row


# ------------------------------------------------------------------- H-CV1b


def h_cv1b_duplex() -> dict[str, Any]:
    out_dir = RESULTS / "duplex"
    before = {p.name for p in out_dir.glob("duplex-v1-*.json")} if out_dir.exists() else set()
    row = _run(
        [PY, "-m", "evals.companion.duplex_v1.run_duplex_v1", "--out", str(out_dir)],
        "cv1b-duplex",
    )
    fresh = sorted(
        p for p in out_dir.glob("duplex-v1-*.json") if p.name not in before
    ) or sorted(out_dir.glob("duplex-v1-*.json"))
    report = json.loads(fresh[-1].read_text(encoding="utf-8"))
    gates = report["hard_gates"]
    ttft_ms = round(report["metrics"]["ttft_p50_s"] * 1000, 3)
    row.update(
        {
            "hypothesis": "H-CV1b/duplex",
            "artifact": str(fresh[-1].relative_to(REPO_ROOT)),
            "hard_gates": gates,
            "hard_gates_passed": sum(1 for v in gates.values() if v),
            "hard_gates_total": len(gates),
            "hard_gates_pass": report["hard_gates_pass"],
            "ttft_p50_ms": ttft_ms,
            "qev1_ttft_p50_ms": QEV1["duplex_ttft_p50_ms"],
            "ttft_delta_ms": round(ttft_ms - QEV1["duplex_ttft_p50_ms"], 3),
            "reproduced": (
                sum(1 for v in gates.values() if v) == QEV1["duplex_hard_gates"]
                and report["hard_gates_pass"]
                and ttft_ms < 1000.0
            ),
            "nav_regression_unchanged": gates["nav_regression_unchanged"],
        }
    )
    return row


def _acoustic_row(path: Path, source: str, run_row: dict[str, Any] | None) -> dict[str, Any]:
    report = json.loads(path.read_text(encoding="utf-8"))
    gates = report["gates"]
    tally = Counter(g["status"] for g in gates.values())
    row: dict[str, Any] = {
        "hypothesis": "H-CV1b/acoustic",
        "source": source,
        "artifact": str(path.relative_to(REPO_ROOT)),
        "families": report["families"],
        "case_count": report["case_count"],
        "duration_s": report["duration_s"],
        "teardown_clean": report["teardown_clean"],
        "orphan_nodes_after_teardown": report["orphan_nodes_after_teardown"],
        "orphan_processes_after_teardown": report["orphan_processes_after_teardown"],
        "audio_profile": report["audio_profile"],
        "gates": {k: {"value": v.get("value"), "limit": v["limit"], "status": v["status"]}
                  for k, v in gates.items()},
        "gate_tally": dict(sorted(tally.items())),
        "gates_passed": report["gates_passed"],
        "qev1_expected": {
            "cases": QEV1["acoustic_cases"],
            "gates_pass": QEV1["acoustic_gates_pass"],
            "gates_total": QEV1["acoustic_gates_total"],
            "ep50_s": QEV1["acoustic_ep50_s"],
            "bargein_acoustic_stop_p50_s": QEV1["acoustic_bargein_stop_p50_s"],
            "duplex_acoustic_ack_p50_s": QEV1["acoustic_duplex_ack_p50_s"],
            "prosody_apex": QEV1["acoustic_prosody_apex"],
        },
    }
    if run_row:
        row.update({k: run_row[k] for k in ("argv", "exit_code", "wall_s")})
    else:
        row["exit_code"] = _quality_exit_code(report)
        row["exit_code_note"] = (
            "derived by applying the runner's own quality_exit_code() to the "
            "persisted report; not re-measured"
        )
    row["reproduced"] = (
        report["case_count"] == QEV1["acoustic_cases"]
        and tally.get("pass", 0) == QEV1["acoustic_gates_pass"]
    )
    return row


def _quality_exit_code(report: dict[str, Any]) -> int:
    from evals.companion.acoustic_loop_v1.run_acoustic_loop_v1 import quality_exit_code

    return quality_exit_code(report)


def h_cv1b_acoustic(mode: str) -> dict[str, Any]:
    out = RESULTS / "acoustic" / "acoustic-loop-v1-cv1b-subset.json"
    if mode == "skip":
        return {"hypothesis": "H-CV1b/acoustic", "source": "skipped"}
    if mode == "run":
        target = RESULTS / "acoustic" / f"acoustic-loop-v1-run-{int(time.time())}.json"
        run_row = _run(
            [
                PY,
                "-m",
                "evals.companion.acoustic_loop_v1.run_acoustic_loop_v1",
                "--output",
                str(target),
            ],
            "cv1b-acoustic",
        )
        if not target.exists():
            return {
                "hypothesis": "H-CV1b/acoustic",
                "source": "run",
                "artifact": None,
                "exit_code": run_row["exit_code"],
                "wall_s": run_row["wall_s"],
                "reproduced": False,
                "note": "runner produced no report; see logs/cv1b-acoustic.stderr.txt",
            }
        return _acoustic_row(target, "run", run_row)
    if not out.exists():
        return {
            "hypothesis": "H-CV1b/acoustic",
            "source": "reuse",
            "artifact": None,
            "reproduced": False,
            "note": f"no recorded artifact at {out}; use --acoustic run",
        }
    return _acoustic_row(out, "reuse", None)


# ------------------------------------------------------------------- H-CV1c


def h_cv1c() -> dict[str, Any]:
    """Self-test the bridge, then prove it is the SAME instrument as QEV-1."""

    out = RESULTS / "cv1c-self-test.json"
    row = _run(
        [
            PY,
            str(FOLDER / "bridge.py"),
            "--self-test",
            "--output",
            str(out),
        ],
        "cv1c-self-test",
    )
    report = json.loads(out.read_text(encoding="utf-8"))

    # Instrument equivalence: push the captured 25-thread corpus through the
    # bridge's lexical layer and check it lands on the scorer's own flag count.
    equivalence = _instrument_equivalence()

    # Machinery demonstration on the six fixtures (NOT the H-CV1c row: the real
    # ratio needs MB-1's transcripts, which do not exist yet).
    demo_out = RESULTS / "cv1c-fixture-arms.json"
    demo_row = _run(
        [
            PY,
            str(FOLDER / "bridge.py"),
            "--transcripts",
            str(FOLDER / "fixtures"),
            "--output",
            str(demo_out),
        ],
        "cv1c-fixture-arms",
    )
    demo = json.loads(demo_out.read_text(encoding="utf-8"))

    row.update(
        {
            "hypothesis": "H-CV1c",
            "artifact": str(out.relative_to(REPO_ROOT)),
            "self_test": report["self_test"],
            "instrument_equivalence": equivalence,
            "fixture_arm_demo": {
                "exit_code": demo_row["exit_code"],
                "artifact": str(demo_out.relative_to(REPO_ROOT)),
                "arms": demo["arms"],
                "ratio_q_over_d": demo["h_cv1c"]["ratio_q_over_d"],
                "note": (
                    "hand-written fixtures, not MB-1 output: this demonstrates "
                    "the ratio machinery, it is NOT the H-CV1c result"
                ),
            },
            "headline_ratio": None,
            "headline_ratio_blocked_by": (
                "research/20260829/model-b-narration-1/ has produced no "
                "transcripts yet; run bridge.py --transcripts <path> when it has"
            ),
            "reproduced": (
                report["self_test"]["status"] == "pass" and equivalence["identical"]
            ),
        }
    )
    return row


def _instrument_equivalence() -> dict[str, Any]:
    """The bridge's lexical layer over the captured corpus == the scorer's."""

    from scorer_bridge import Turn, score_turns

    from evals.companion.realtime_convo_v1.schema import load_fixtures, load_scenarios
    from evals.companion.realtime_convo_v1.score_corpus import machine_findings

    scenarios = load_scenarios()
    fixtures = load_fixtures()
    scorer = [f for f in machine_findings(scenarios, fixtures) if f.severity == "review"]

    turns: list[Turn] = []
    for fixture in fixtures:
        for turn in fixture.turns:
            turns.append(
                Turn(fixture.thread_id, "corpus", turn.index, "owner", turn.owner_text, ())
            )
            turns.append(
                Turn(fixture.thread_id, "corpus", turn.index, "robot", turn.robot_text, ())
            )
    bridge = [f for f in score_turns(turns) if f.layer == "lexical"]

    # turn_index is None for the per-thread repeated_refusal_language row.
    scorer_key = sorted(
        (f.thread_id, -1 if f.turn_index is None else f.turn_index, f.check_id)
        for f in scorer
    )
    bridge_key = sorted(
        (f.scenario_id, -1 if f.turn_index is None else f.turn_index, f.check_id)
        for f in bridge
    )
    return {
        "corpus": "evals/companion/realtime_convo_v1 (25 captured threads)",
        "scorer_review_flags": len(scorer),
        "bridge_lexical_flags": len(bridge),
        "qev1_expected": QEV1["corpus_review_flags"],
        "identical": scorer_key == bridge_key,
        "by_check": dict(sorted(Counter(k[2] for k in bridge_key).items())),
        "note": (
            "the bridge imports RISK_PATTERNS/REFUSAL_PATTERN from the scorer; "
            "this run proves the flag SET, not merely the count, matches"
        ),
    }


# ----------------------------------------------------------------------- main


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--all", action="store_true")
    parser.add_argument(
        "--only", choices=["cv1a", "cv1b", "cv1c"], action="append", default=[]
    )
    parser.add_argument(
        "--acoustic",
        choices=["reuse", "run", "skip"],
        default="reuse",
        help="reuse the recorded artifact (default), re-measure, or skip",
    )
    parser.add_argument("--output", type=Path, default=FOLDER / "results.json")
    args = parser.parse_args(argv)
    wanted = set(args.only) or ({"cv1a", "cv1b", "cv1c"} if args.all else set())
    if not wanted:
        parser.error("pass --all or --only <hypothesis>")

    RESULTS.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    rows: dict[str, Any] = {}
    if "cv1a" in wanted:
        rows["h_cv1a"] = h_cv1a()
    if "cv1b" in wanted:
        rows["h_cv1b_duplex"] = h_cv1b_duplex()
        rows["h_cv1b_acoustic"] = h_cv1b_acoustic(args.acoustic)
    if "cv1c" in wanted:
        rows["h_cv1c"] = h_cv1c()

    result = {
        "schema_version": 1,
        "experiment": "CONV-1",
        "folder": "research/20260829/conv-bench-1",
        "design": "research/20260829/conv-bench-1/DESIGN.md",
        "amendments_present": (FOLDER / "AMENDMENTS.md").exists(),
        "evidence_tiers": ["replay (corpus, duplex)", "desktop-sim (acoustic null sinks)"],
        "hosted_calls": 0,
        "hosted_spend_usd": 0.0,
        "qev1_reference": QEV1,
        "acoustic_mode": args.acoustic,
        "wall_s": round(time.monotonic() - started, 3),
        "rows": rows,
    }
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    summary = {
        name: {
            k: row.get(k)
            for k in ("exit_code", "reproduced", "wall_s")
            if k in row
        }
        for name, row in rows.items()
    }
    print(json.dumps({"output": str(args.output), "summary": summary}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
