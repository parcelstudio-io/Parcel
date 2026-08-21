"""Run the assertion suite over any session folder.

    .parcel/bin/python -m evals.assertions.run_assertions PATH [PATH ...]
    .parcel/bin/python -m evals.assertions.run_assertions --discover recordings
    .parcel/bin/python -m evals.assertions.run_assertions --gate
    .parcel/bin/python -m evals.assertions.run_assertions --self-test

Reads a session folder in either shape — an instrumented run folder
(``ledger.json`` + ``session_slices.json`` + ``state.json``) or an EV-1 session
folder (``events.jsonl`` beside the audio) — and prints the dimension matrix, a
verdict list and a review queue. ``--json`` emits the whole report.

Exit code is 1 when any dimension FAILED, so this is usable as a check in its
own right. A review-only run exits 0 and says so: a review candidate is a
question for a human, not a verdict, and an eval that exits non-zero on
questions trains people to ignore it.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from evals.assertions.evidence import discover_sessions
from evals.assertions.matrix import (
    STATUS_FAIL,
    build_matrix,
    render_matrix,
    score_session,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("paths", nargs="*", help="session folders to score")
    parser.add_argument("--discover", metavar="ROOT", help="score every session folder under ROOT")
    parser.add_argument("-k", type=int, default=1, help="pass^k trials for the e-stop (default 1)")
    parser.add_argument("--json", action="store_true", help="emit the full report as JSON")
    parser.add_argument("--gate", action="store_true", help="run the commit-tier gate and exit")
    parser.add_argument("--self-test", action="store_true", help="run the harness self-test and exit")
    args = parser.parse_args(argv)

    if args.gate:
        from evals.assertions.gate import run_assertion_gate

        status, detail, extra = run_assertion_gate(k=args.k)
        print(f"assertion-evals: {status.upper()}\n  {detail}")
        if args.json:
            print(json.dumps(extra, indent=2, sort_keys=True))
        return 0 if status == "pass" else 1

    if args.self_test:
        from evals.assertions.selftest import run_self_test

        report = run_self_test(k=args.k)
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0 if report["ok"] else 1

    targets = [Path(p) for p in args.paths]
    if args.discover:
        targets.extend(discover_sessions(args.discover))
    if not targets:
        parser.error("give at least one session folder, or --discover ROOT")

    results = [score_session(path, name=path.name, k=args.k) for path in targets]
    matrix = build_matrix(results)
    if args.json:
        print(json.dumps(
            {"matrix": matrix, "suites": [r.as_dict() for r in results]},
            indent=2, ensure_ascii=False, sort_keys=True,
        ))
    else:
        print(render_matrix(matrix))
        for result in results:
            print(f"\n=== {result.name} ({result.status}) ===")
            print(f"  evidence: {result.provenance}")
            print(f"  e-stop:   {result.estop}")
            for finding in result.verdicts:
                print(f"  VERDICT  {finding.check}: {json.dumps(finding.evidence, ensure_ascii=False)[:160]}")
            for finding in result.reviews:
                print(f"  review   {finding.check}: {json.dumps(finding.evidence, ensure_ascii=False)[:160]}")
    return 1 if any(r.status == STATUS_FAIL for r in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
