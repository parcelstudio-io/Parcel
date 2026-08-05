"""CLI for NAV_INSTRUCT_V1 headless matrix (baseline-first hard gate).

Usage:
    .parcel/bin/python -m evals.nav_instruct.run_nav_instruct_v1 \
        --minival --mode baseline --out evals/nav_instruct/results
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from evals.nav_instruct.generator import (
    generate_episode_matrix,
    generate_minival,
    matrix_digest,
    write_episode_files,
)
from evals.nav_instruct.runner import (
    DOES_NOT_PROVE,
    RUNNER_VERSION,
    NavInstructRunner,
    aggregate_results,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = Path(__file__).resolve().parent / "results"
LEDGER = Path(__file__).resolve().parent / "results" / "ledger.jsonl"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=20260804)
    parser.add_argument("--per-family", type=int, default=25)
    parser.add_argument("--minival", action="store_true", help="25-episode CI slice")
    parser.add_argument("--mode", default="baseline", choices=("baseline", "candidate"))
    parser.add_argument("--max-steps", type=int, default=200)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="optional cap on episodes (0 = all)",
    )
    parser.add_argument(
        "--write-episodes",
        action="store_true",
        help="also dump episode JSON specs",
    )
    parser.add_argument(
        "--freeze",
        action="store_true",
        help="overwrite scrum/.../freeze/ baseline pointer (opt-in; historical row is pinned)",
    )
    args = parser.parse_args(argv)

    episodes = (
        generate_minival(seed=args.seed)
        if args.minival
        else generate_episode_matrix(seed=args.seed, per_family=args.per_family)
    )
    if args.limit > 0:
        episodes = episodes[: args.limit]

    args.out.mkdir(parents=True, exist_ok=True)
    if args.write_episodes:
        write_episode_files(episodes, args.out / "episodes")

    runner = NavInstructRunner(max_steps=args.max_steps, mode=args.mode)
    started = time.perf_counter()
    results = [runner.run_episode(ep) for ep in episodes]
    elapsed_s = time.perf_counter() - started
    aggregate = aggregate_results(results)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report_id = f"nav-instruct-v1-{args.mode}-{stamp}"
    report = {
        "report_id": report_id,
        "runner_version": RUNNER_VERSION,
        "mode": args.mode,
        "seed": args.seed,
        "minival": bool(args.minival),
        "episode_digest": matrix_digest(episodes),
        "elapsed_s": elapsed_s,
        "aggregate": aggregate,
        "does_not_prove": list(DOES_NOT_PROVE),
        "episodes": [item.as_dict() for item in results],
    }
    report_path = args.out / f"{report_id}.json"
    report_path.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8")

    ledger_row = {
        "report_id": report_id,
        "mode": args.mode,
        "seed": args.seed,
        "minival": bool(args.minival),
        "n": aggregate["n"],
        "sr": aggregate["sr"],
        "spl": aggregate["spl"],
        "collision_total": aggregate["collision_total"],
        "failure_histogram": aggregate["failure_histogram"],
        "episode_digest": matrix_digest(episodes),
        "report": report_path.name,
        "frozen_baseline": args.mode == "baseline",
    }
    with LEDGER.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(ledger_row, sort_keys=True) + "\n")

    # Freeze pointer is opt-in so the historical pre-rewire hard-gate row stays pinned.
    if args.mode == "baseline" and args.freeze:
        freeze_dir = REPO_ROOT / "scrum" / "20260804" / "task_6" / "freeze"
        freeze_dir.mkdir(parents=True, exist_ok=True)
        (freeze_dir / "nav-instruct-baseline.json").write_text(
            json.dumps(ledger_row, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        (freeze_dir / "nav-instruct-baseline-report.json").write_text(
            json.dumps(
                {
                    "report_id": report_id,
                    "aggregate": aggregate,
                    "by_family_tier": aggregate["by_family_tier"],
                },
                sort_keys=True,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    print(
        json.dumps(
            {
                "report": str(report_path),
                "sr": aggregate["sr"],
                "spl": aggregate["spl"],
                "collision_total": aggregate["collision_total"],
                "failure_histogram": aggregate["failure_histogram"],
                "n": aggregate["n"],
                "elapsed_s": round(elapsed_s, 2),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
