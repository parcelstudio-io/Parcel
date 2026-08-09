"""CLI for the NAV_INSTRUCT headless matrix (baseline-first hard gate).

Usage:
    .parcel/bin/python -m evals.nav_instruct.run_nav_instruct_v1 \
        --minival --mode baseline --episode-version v2 \
        --out evals/nav_instruct/results

``--episode-version`` selects the frozen episode set (see
``evals/nav_instruct/generator.py``) and, with it, the arrival rule that set was
frozen under. ``v1`` replays the 2026-08-05/06 semantics exactly; ``v2`` is the
2026-08-07 re-freeze. Every report and ledger row carries
``baseline_version``/``arrival_rule``, so no two rows can be compared without
seeing whether they are comparable.
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from evals.nav_instruct.generator import (
    EPISODE_SET_V1,
    EPISODE_SETS,
    episode_set_spec,
    generate_episode_matrix,
    generate_minival,
    matrix_digest,
    write_episode_files,
)
from evals.nav_instruct.runner import (
    ARRIVAL_RULE_FOR_VERSION,
    ARRIVAL_RULES,
    DOES_NOT_PROVE,
    RUNNER_VERSION,
    NavInstructRunner,
    aggregate_results,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = Path(__file__).resolve().parent / "results"
LEDGER = Path(__file__).resolve().parent / "results" / "ledger.jsonl"


def _run_scene_split(args: argparse.Namespace) -> int:
    """``--scenes``: the val_seen / val_unseen generalization split.

    Kept in its own module because it is a different measurement from the
    single-scene matrix: the headline is the *gap*, not either side.
    """

    from evals.nav_instruct.unseen_split import markdown_table, run_split, write_report

    scenes = (
        None
        if str(args.scenes).strip().lower() == "all"
        else [Path(item.strip()) for item in str(args.scenes).split(",") if item.strip()]
    )
    payload = run_split(mode=args.mode, max_steps=args.max_steps, seed=args.seed, scenes=scenes)
    path = write_report(payload)
    print(markdown_table(payload))
    print(f"\nwrote {path}")
    return 0


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
    parser.add_argument(
        "--episode-version",
        default=EPISODE_SET_V1,
        choices=sorted(EPISODE_SETS),
        help="frozen episode set to run (default: v1, the immutable original)",
    )
    parser.add_argument(
        "--arrival-rule",
        default=None,
        choices=sorted(ARRIVAL_RULES),
        help="override the arrival rule (default: the one this episode set was frozen under)",
    )
    parser.add_argument(
        "--scene",
        type=Path,
        default=None,
        help="MJCF scene to run against (default: the frozen city block)",
    )
    parser.add_argument(
        "--scenes",
        default=None,
        help=(
            "run the scene-generalization split instead of a single-scene matrix:"
            " 'all' for the frozen val_unseen split, or a comma-separated list of"
            " generated scene paths. Reports the seen/unseen gap."
        ),
    )
    args = parser.parse_args(argv)

    if args.scenes:
        return _run_scene_split(args)

    version = args.episode_version
    spec = episode_set_spec(version)
    arrival_rule = args.arrival_rule or ARRIVAL_RULE_FOR_VERSION[version]

    episodes = (
        generate_minival(seed=args.seed, version=version)
        if args.minival
        else generate_episode_matrix(
            seed=args.seed, per_family=args.per_family, version=version
        )
    )
    if args.limit > 0:
        episodes = episodes[: args.limit]

    args.out.mkdir(parents=True, exist_ok=True)
    if args.write_episodes:
        write_episode_files(
            episodes, args.out / "episodes" / version, version=version, seed=args.seed
        )

    runner = NavInstructRunner(
        max_steps=args.max_steps,
        mode=args.mode,
        arrival_rule=arrival_rule,
        scene=args.scene,
    )
    started = time.perf_counter()
    results = [runner.run_episode(ep) for ep in episodes]
    elapsed_s = time.perf_counter() - started
    aggregate = aggregate_results(
        results, episode_set_version=version, scene=runner.scene
    )
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    suffix = "" if version == EPISODE_SET_V1 else f"-{version}"
    report_id = f"nav-instruct-v1-{args.mode}{suffix}-{stamp}"
    report = {
        "report_id": report_id,
        "runner_version": RUNNER_VERSION,
        "mode": args.mode,
        "seed": args.seed,
        "minival": bool(args.minival),
        "episode_digest": matrix_digest(episodes),
        "baseline_version": version,
        "episode_set_provenance": spec.provenance,
        "arrival_rule": arrival_rule,
        "scene": runner.scene,
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
        "mean_dtg_m": aggregate["mean_dtg_m"],
        "collision_total": aggregate["collision_total"],
        "failure_histogram": aggregate["failure_histogram"],
        # Instrument 5 — differential arrival verdicts, per run.
        "authority_histogram": aggregate["authority_histogram"],
        "arrival_epsilon_m": aggregate["arrival_epsilon_m"],
        "episode_digest": matrix_digest(episodes),
        "report": report_path.name,
        "frozen_baseline": args.mode == "baseline",
        "kind": "measured_run",
        # Re-freeze bookkeeping: which episode set, which arrival rule, and what
        # the superseded rule would have said about the same traces.
        "baseline_version": version,
        "arrival_rule": arrival_rule,
        "sr_frozen_rule": aggregate["sr_frozen_rule"],
        "arrival_branch_histogram": aggregate["arrival_branch_histogram"],
        "scene": runner.scene,
    }
    with LEDGER.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(ledger_row, sort_keys=True) + "\n")

    # K0: append freeze under 20260805/task_1/freeze — never rewrite the
    # 20260804/task_6 historical baseline pointer.
    if args.mode == "baseline" and args.freeze and version == EPISODE_SET_V1:
        freeze_dir = REPO_ROOT / "scrum" / "20260805" / "task_1" / "freeze"
        freeze_dir.mkdir(parents=True, exist_ok=True)
        freeze_row = {
            **ledger_row,
            "runner_version": RUNNER_VERSION,
            "k0_arrival_authority": "GoalRegion",
            "supersedes": "nav-instruct-v1-baseline-20260805T004302Z",
            "frozen_baseline": True,
            "does_not_prove": list(DOES_NOT_PROVE),
        }
        (freeze_dir / "nav-instruct-baseline-k0.json").write_text(
            json.dumps(freeze_row, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        (freeze_dir / "nav-instruct-baseline-k0-report.json").write_text(
            json.dumps(
                {
                    "report_id": report_id,
                    "runner_version": RUNNER_VERSION,
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
                "baseline_version": version,
                "arrival_rule": arrival_rule,
                "sr": aggregate["sr"],
                "sr_frozen_rule": aggregate["sr_frozen_rule"],
                "spl": aggregate["spl"],
                "mean_dtg_m": aggregate["mean_dtg_m"],
                "collision_total": aggregate["collision_total"],
                "failure_histogram": aggregate["failure_histogram"],
                "authority_histogram": aggregate["authority_histogram"],
                "n": aggregate["n"],
                "elapsed_s": round(elapsed_s, 2),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
