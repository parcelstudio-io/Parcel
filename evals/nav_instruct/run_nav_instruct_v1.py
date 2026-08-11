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
    ALLOWED_NAVIGATOR_OVERRIDES,
    ARRIVAL_RULE_FOR_VERSION,
    ARRIVAL_RULES,
    BUDGET_POLICIES,
    DEFAULT_BUDGET_POLICY,
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
    parser.add_argument(
        "--budget-policy",
        default=DEFAULT_BUDGET_POLICY,
        choices=sorted(BUDGET_POLICIES),
        help=(
            "step-budget policy (default: 'fixed', the frozen flat budget every "
            "persisted row used). 'scaled-path-v1' scales the per-episode budget "
            "by shortest_path_m (floored at --max-steps) so a tier-E truncation "
            "is attributable to a genuine miss, not to budget starvation."
        ),
    )
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
        "--navigator-flag",
        action="append",
        default=[],
        metavar="NAME",
        choices=sorted(ALLOWED_NAVIGATOR_OVERRIDES),
        help=(
            "turn ON a pre-registered pipeline flag for this run (repeatable). "
            "Default: none — the flag-OFF arm is the navigator every frozen row "
            "was measured with. The chosen flags are recorded on the report and "
            "on the ledger row, so a flag-on row can never be read as a flag-off "
            "one."
        ),
    )
    parser.add_argument(
        "--refreeze-provenance",
        default=None,
        metavar="TEXT",
        help=(
            "stamp a re-freeze provenance note on the report and the ledger row. "
            "A frozen-baseline row that SUPERSEDES an earlier one must say why in "
            "the ledger itself — the pin is what ci_gate's hard-safety gate reads, "
            "and a reader of that row should not have to find the status doc to "
            "learn that the episode set moved under an authorization. Optional and "
            "omitted when unset, so an ordinary row stays byte-identical in shape "
            "to every row already in the ledger."
        ),
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

    navigator_flags = sorted(set(args.navigator_flag or ()))
    if navigator_flags and args.freeze:
        parser.error(
            "--freeze refuses a flag-on run: a frozen baseline pointer must "
            "describe the default navigator, never one reconfigured by a flag"
        )
    runner = NavInstructRunner(
        max_steps=args.max_steps,
        mode=args.mode,
        arrival_rule=arrival_rule,
        scene=args.scene,
        budget_policy=args.budget_policy,
        navigator_overrides={name: True for name in navigator_flags},
    )
    started = time.perf_counter()
    results = [runner.run_episode(ep) for ep in episodes]
    elapsed_s = time.perf_counter() - started
    aggregate = aggregate_results(
        results, episode_set_version=version, scene=runner.scene
    )
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    suffix = "" if version == EPISODE_SET_V1 else f"-{version}"
    # A flag-on run gets its own visible name. Two rows that differ only by a
    # pipeline flag must not be distinguishable solely by reading a key most
    # readers will not look at.
    flag_suffix = "-flagon" if navigator_flags else ""
    report_id = f"nav-instruct-v1-{args.mode}{suffix}{flag_suffix}-{stamp}"
    report = {
        "report_id": report_id,
        "navigator_flags": navigator_flags,
        "runner_version": RUNNER_VERSION,
        "mode": args.mode,
        "seed": args.seed,
        "minival": bool(args.minival),
        "episode_digest": matrix_digest(episodes),
        "baseline_version": version,
        "episode_set_provenance": spec.provenance,
        "arrival_rule": arrival_rule,
        "budget_policy": args.budget_policy,
        "max_steps": args.max_steps,
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
        # Budget provenance (card budget-honest-minival): the policy and the base
        # budget. Under "fixed" every episode ran at max_steps; under
        # "scaled-path-v1" this is the floor and each report episode row carries
        # its own scaled ``max_steps``. No two rows are comparable across policies.
        "budget_policy": args.budget_policy,
        "max_steps": args.max_steps,
        "sr_frozen_rule": aggregate["sr_frozen_rule"],
        "arrival_branch_histogram": aggregate["arrival_branch_histogram"],
        "scene": runner.scene,
    }
    if navigator_flags:
        # Only stamped when non-empty: a flag-off row stays byte-identical in
        # shape to every row already in the ledger.
        ledger_row["navigator_flags"] = navigator_flags
    if args.refreeze_provenance:
        # Same convention as navigator_flags: present only when it means
        # something, so an ordinary row's shape does not move.
        report["refreeze_provenance"] = args.refreeze_provenance
        ledger_row["refreeze_provenance"] = args.refreeze_provenance
        report_path.write_text(
            json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8"
        )
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
                "navigator_flags": navigator_flags,
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
