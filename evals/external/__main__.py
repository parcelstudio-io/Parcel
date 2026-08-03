"""CLI: python -m evals.external"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Allow `python -m evals.external` from the repo root without installing evals.
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from evals.external.compatibility import compatibility_table
from evals.external.runner import run_suite, write_report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run offline synthetic proxies of Habitat / BARN / 3WE / SocialNav metrics. "
            "Not an official leaderboard submission."
        )
    )
    parser.add_argument(
        "--suite",
        default="pointnav,barn_clutter,socialnav,objectnav,exploration",
        help="Comma-separated tasks",
    )
    parser.add_argument("--episodes", type=int, default=10, help="Episodes per task")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Optional JSON report path (default: evals/external/results/latest_report.json)",
    )
    parser.add_argument(
        "--compatibility-only",
        action="store_true",
        help="Print compatibility matrix JSON and exit",
    )
    args = parser.parse_args(argv)

    if args.compatibility_only:
        print(json.dumps(compatibility_table(), indent=2))
        return 0

    tasks = [part.strip() for part in args.suite.split(",") if part.strip()]
    report = run_suite(tasks=tasks, episodes_per_task=args.episodes, seed=args.seed)
    path = write_report(report, args.out)
    summary = {
        "written": str(path),
        "aggregate": report["aggregate"],
        "by_task": report["by_task"],
        "official_possible_today": {
            row["id"]: row["official_possible_today"] for row in report["compatibility"]
        },
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
