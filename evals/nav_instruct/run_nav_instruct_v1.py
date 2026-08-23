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

from evals.nav_instruct.drift_cells import (
    DRIFT_PROVENANCE,
    DRIFT_SEED,
    DRIFT_SET_NAME,
    generate_drift_cells,
)
from evals.nav_instruct.generator import (
    EPISODE_SET_V1,
    EPISODE_SETS,
    V4S_EPISODES_PER_AXIS,
    V4S_SEED,
    episode_set_spec,
    generate_episode_matrix,
    generate_minival,
    generate_v4s_matrix,
    matrix_digest,
    write_episode_files,
)
from evals.nav_instruct.runner import (
    ALLOWED_NAVIGATOR_OVERRIDES,
    ARRIVAL_RULE_FOR_VERSION,
    ARRIVAL_RULES,
    BUDGET_POLICIES,
    DEFAULT_ARRIVAL_RULE,
    DEFAULT_BUDGET_POLICY,
    DIVERGENCE_REFERENCE_PCT,
    DOES_NOT_PROVE,
    RUNNER_VERSION,
    NavInstructRunner,
    aggregate_results,
)

#: The frozen matrix seed every persisted row was generated with.
DEFAULT_MATRIX_SEED = 20260804

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = Path(__file__).resolve().parent / "results"
LEDGER = Path(__file__).resolve().parent / "results" / "ledger.jsonl"

# ---- CARD GATE-0b (scrum/20260822/task_30): the ledger appends ON PURPOSE ----
#
# THE DEFECT. Every run of this CLI appended one row to append-only provenance
# — including runs that were never provenance. Card ROAM-1 wrote two rows from
# two verification minivals, one of them from a tree with `time_s` seeded OUT,
# and the verifier had to restore the file by hand
# (`AUDIT_WEEK1_FABLE.md` §ROAM-1 finding 4). A ledger that records
# experiments nobody meant to keep is a ledger you cannot cite.
#
# THE RULE. The default is UNCHANGED — a plain `--minival --mode candidate`
# still appends exactly where it always did, because `ci_gate`'s
# `evaluate_nav_instruct_candidate` diffs this file before and after the run
# and the frozen-baseline pointer `evaluate_hard_safety` follows lives in it.
# What is new is that a run can SAY it is not provenance:
#
#   --no-ledger        measure and report; append nothing
#   --ledger PATH      append somewhere else (a scratch ledger for a seed run)
#   PARCEL_NAV_LEDGER  the same choice for a harness that cannot edit argv:
#                      a path, or `off`/`none` for --no-ledger
#
# AND THE GUARD. A run started from inside pytest that did not say where to
# append does not append to the tracked ledger: it says so, by name, and
# carries on. This is a provenance rule, not a fail-closed one — nothing
# refuses, the run still measures and still writes its report, and an EXPLICIT
# `--ledger <the tracked path>` is honoured, because a person who typed the
# path is not overruled by a heuristic (the rule card XD-1 chose for
# `resolve_xdist_workers`).

#: THE FILE THE GUARD PROTECTS. Deliberately a SECOND name for the same path:
#: `LEDGER` above is the module's default target and callers monkeypatch it to
#: redirect a run (`tests/test_dr2_pose_drift_arm.py:722` does exactly that, and
#: has since long before this card). A redirect IS a caller saying where to
#: append, so the guard below must not fire on it — it fires only when the
#: resolved target is still this, the tracked provenance file.
TRACKED_LEDGER = Path(__file__).resolve().parent / "results" / "ledger.jsonl"

#: Redirect (a path) or disable (`off` / `none`) the ledger without touching argv.
LEDGER_ENV = "PARCEL_NAV_LEDGER"

#: Set by pytest in every test process. Its presence is how a verification run
#: is recognised; nothing else about pytest is imported or assumed.
PYTEST_MARKER_ENV = "PYTEST_CURRENT_TEST"

_LEDGER_OFF_WORDS = frozenset({"off", "none", "no", "0"})


def resolve_ledger_path(
    *,
    no_ledger: bool = False,
    ledger: Path | None = None,
    env: dict[str, str] | None = None,
    default: Path | None = None,
) -> tuple[Path | None, str]:
    """Return ``(target, provenance)``; ``None`` means "append nothing".

    Pure with respect to its arguments so both directions are testable without
    running a matrix. Precedence: ``--no-ledger`` > ``--ledger`` > the
    environment > the default. ``default`` is read from the module global at
    CALL time (not captured as an argument default) so a caller that
    monkeypatches :data:`LEDGER` still redirects the run, and the pytest guard
    only withholds when the target is still :data:`TRACKED_LEDGER`.
    """

    import os

    source = os.environ if env is None else env
    resolved_default = LEDGER if default is None else default
    if no_ledger:
        return None, "--no-ledger"
    if ledger is not None:
        return Path(ledger), f"--ledger {ledger}"
    raw = (source.get(LEDGER_ENV) or "").strip()
    if raw:
        if raw.lower() in _LEDGER_OFF_WORDS:
            return None, f"{LEDGER_ENV}={raw}"
        return Path(raw), f"{LEDGER_ENV}={raw}"
    if source.get(PYTEST_MARKER_ENV) and resolved_default == TRACKED_LEDGER:
        return None, (
            f"withheld: this run is inside pytest ({PYTEST_MARKER_ENV} is set) and "
            f"did not say where to append, so the tracked ledger {TRACKED_LEDGER} is "
            "left alone. Pass --ledger <path> to record somewhere, or --ledger "
            f"{TRACKED_LEDGER} to append here on purpose."
        )
    return resolved_default, "default"
# ---- END CARD GATE-0b -------------------------------------------------------


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
    parser.add_argument("--seed", type=int, default=DEFAULT_MATRIX_SEED)
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
        "--episode-set",
        dest="episode_version",
        default=EPISODE_SET_V1,
        choices=sorted(EPISODE_SETS),
        help=(
            "episode set to run (default: v1, the immutable original). The two "
            "spellings are the same seam: a frozen baseline set is named by its "
            "version, an additive tier (v4s) by its name."
        ),
    )
    parser.add_argument(
        "--per-axis",
        type=int,
        default=V4S_EPISODES_PER_AXIS,
        help=(
            "episodes per axis for an additive search tier (v4s). Ignored by "
            "every frozen matrix set, which is sized by --per-family."
        ),
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
        "--pose-drift-profile",
        default=None,
        metavar="PROFILE",
        choices=sorted(DIVERGENCE_REFERENCE_PCT),
        help=(
            "run the whole arm under a degraded-pose profile from "
            "configs/navigation/pose.yaml (card DR-2). Default: none — the "
            "shipping truth passthrough every frozen row was measured with. "
            "Each episode builds ONE FRESH provider whose seed is the profile "
            "seed XOR a stable hash of the episode id, and the profile, the "
            "seed and the measured truth-vs-ODOM divergence are recorded on "
            "every persisted episode row."
        ),
    )
    parser.add_argument(
        "--drift-cells",
        action="store_true",
        help=(
            "run the DR-2 long-travel substrate (evals/nav_instruct/drift_cells.py) "
            "instead of a frozen matrix: every scene cell whose target is visible "
            "from the start down a clear corridor at least 10 m of route away. "
            "Candidate-only and never a frozen baseline."
        ),
    )
    # ---- CARD GATE-0b (scrum/20260822/task_30) -----------------------------
    ledger_group = parser.add_mutually_exclusive_group()
    ledger_group.add_argument(
        "--no-ledger",
        action="store_true",
        help=(
            "measure and write the report, but append NOTHING to "
            "evals/nav_instruct/results/ledger.jsonl. For verification and "
            "seeded runs, whose numbers are not provenance."
        ),
    )
    ledger_group.add_argument(
        "--ledger",
        type=Path,
        default=None,
        help=(
            "append the run's row to this file instead of the tracked ledger "
            f"(env {LEDGER_ENV} does the same; `off` there means --no-ledger)"
        ),
    )
    # ---- END CARD GATE-0b --------------------------------------------------
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

    if args.pose_drift_profile and args.freeze:
        parser.error(
            "--freeze refuses a degraded-pose run: a frozen baseline pointer "
            "must describe the shipping truth passthrough every frozen row was "
            "measured under, never a run reconfigured by a drift profile"
        )
    if args.drift_cells and args.freeze:
        parser.error(
            f"--freeze refuses the additive {DRIFT_SET_NAME!r} drift substrate: "
            "it is not a frozen baseline, and a freeze pointer that named it "
            "would claim it is"
        )
    if args.drift_cells and args.minival:
        parser.error(
            "--minival is a slice of a family x tier matrix; the drift cells "
            "are neither — drop --minival, or use --limit for a prefix"
        )

    version = args.episode_version
    spec = episode_set_spec(version)
    # An additive search tier carries the arrival rule of the frozen set it was
    # built on top of — it adds cells, never a rule. ``ARRIVAL_RULE_FOR_VERSION``
    # is the frozen sets' table and stays their property (it lives in the
    # runner, which this card does not own); the default it falls back to IS the
    # v4 rule, and ``--arrival-rule`` still overrides either way.
    arrival_rule = args.arrival_rule or ARRIVAL_RULE_FOR_VERSION.get(
        version, DEFAULT_ARRIVAL_RULE
    )
    if args.drift_cells:
        # The drift cells are built by the LIVE K0 builders, exactly as v4s is,
        # so they carry the live arrival rule and never v1's frozen hold — which
        # is what ``--episode-version``'s default would otherwise hand them.
        arrival_rule = args.arrival_rule or DEFAULT_ARRIVAL_RULE

    if args.drift_cells:
        episodes = generate_drift_cells(
            seed=(DRIFT_SEED if args.seed == DEFAULT_MATRIX_SEED else args.seed)
        )
    elif spec.search_axes:
        if args.freeze:
            parser.error(
                f"--freeze refuses the additive search tier {version!r}: it is "
                "not a frozen baseline this cycle, and a freeze pointer that "
                "named it would claim it is"
            )
        if args.minival:
            parser.error(
                f"--minival is a slice of a family x tier matrix; {version!r} "
                "is an axis tier — use --per-axis"
            )
        # v4s has its own seed. ``--seed`` still overrides it, but leaving the
        # matrix default in place must not silently generate a different set
        # from the one checked in under episodes/v4s/.
        episodes = generate_v4s_matrix(
            seed=(V4S_SEED if args.seed == DEFAULT_MATRIX_SEED else args.seed),
            per_axis=args.per_axis,
        )
    else:
        episodes = (
            generate_minival(seed=args.seed, version=version)
            if args.minival
            else generate_episode_matrix(
                seed=args.seed, per_family=args.per_family, version=version
            )
        )
    if args.limit > 0:
        episodes = episodes[: args.limit]

    # What the persisted rows call this set, and where its provenance comes
    # from. The drift cells are NOT a member of ``EPISODE_SETS`` — registering
    # them as an episode-set *version* is precisely what would let --freeze and
    # the frozen-baseline ledger flag reach them.
    set_label = DRIFT_SET_NAME if args.drift_cells else version
    set_provenance = DRIFT_PROVENANCE if args.drift_cells else spec.provenance

    args.out.mkdir(parents=True, exist_ok=True)
    if args.write_episodes:
        write_episode_files(
            episodes,
            args.out / "episodes" / set_label,
            # ``version=`` makes the manifest quote an EPISODE-SET spec, and the
            # drift cells deliberately are not one. Omitting it keeps the
            # manifest to what is actually true of them: the ids, the count and
            # the digest.
            version=None if args.drift_cells else version,
            seed=args.seed,
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
        pose_drift_profile=args.pose_drift_profile,
    )
    started = time.perf_counter()
    results = [runner.run_episode(ep) for ep in episodes]
    elapsed_s = time.perf_counter() - started
    aggregate = aggregate_results(
        results,
        episode_set_version=None if args.drift_cells else version,
        scene=runner.scene,
    )
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    suffix = (
        f"-{DRIFT_SET_NAME}"
        if args.drift_cells
        else ("" if version == EPISODE_SET_V1 else f"-{version}")
    )
    # A flag-on run gets its own visible name. Two rows that differ only by a
    # pipeline flag must not be distinguishable solely by reading a key most
    # readers will not look at.
    flag_suffix = "-flagon" if navigator_flags else ""
    # Same rule as the flag suffix: an arm measured under injected pose drift
    # must be distinguishable from a truth-pose arm by its NAME, not only by a
    # key a reader might not open.
    drift_suffix = f"-{args.pose_drift_profile}" if args.pose_drift_profile else ""
    report_id = (
        f"nav-instruct-v1-{args.mode}{suffix}{flag_suffix}{drift_suffix}-{stamp}"
    )
    report = {
        "report_id": report_id,
        "navigator_flags": navigator_flags,
        "runner_version": RUNNER_VERSION,
        "mode": args.mode,
        "seed": args.seed,
        "minival": bool(args.minival),
        "episode_digest": matrix_digest(episodes),
        "baseline_version": set_label,
        "episode_set_provenance": set_provenance,
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
    # NOTE: the report is WRITTEN once, below, after every conditional stamp has
    # been applied. It used to be written here and then re-written only on the
    # ``--refreeze-provenance`` path, which silently dropped
    # ``pose_drift_profile`` from every persisted drift-arm report (the episode
    # rows carried it; the report header did not). Measured on
    # ``nav-instruct-v1-candidate-v4d-go2_degraded-20260812T055104Z.json``.

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
        # An additive tier is NEVER a frozen baseline, whatever mode it ran in:
        # ``ci_gate``'s hard-safety gate certifies from the LATEST row flagged
        # here, and a v4s row flagged True would silently retarget that gate at
        # a set no baseline was ever measured on.
        # A drift arm and the additive substrate are BOTH disqualifying, for the
        # same reason the search tier is: this flag is what ci_gate's hard-safety
        # gate follows, and a row flagged True would retarget that gate at a set
        # or a pose source no baseline was ever measured on.
        "frozen_baseline": (
            args.mode == "baseline"
            and not spec.search_axes
            and not args.drift_cells
            and args.pose_drift_profile is None
        ),
        "kind": "measured_run",
        # Re-freeze bookkeeping: which episode set, which arrival rule, and what
        # the superseded rule would have said about the same traces.
        "baseline_version": set_label,
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
    if args.pose_drift_profile:
        # Same convention: stamped only on a drift arm, so a truth-pose row's
        # shape does not move. ``aggregate["pose_drift"]`` carries the arm-level
        # non-vacuity evidence (per-episode in-band counts, distance travelled,
        # LOST and re-anchor events); every episode row carries its own.
        report["pose_drift_profile"] = args.pose_drift_profile
        ledger_row["pose_drift_profile"] = args.pose_drift_profile
        ledger_row["pose_drift"] = aggregate.get("pose_drift")
    if args.drift_cells:
        ledger_row["episode_set"] = DRIFT_SET_NAME
    if args.refreeze_provenance:
        # Same convention as navigator_flags: present only when it means
        # something, so an ordinary row's shape does not move.
        report["refreeze_provenance"] = args.refreeze_provenance
        ledger_row["refreeze_provenance"] = args.refreeze_provenance
    report_path.write_text(
        json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    # ---- CARD GATE-0b (scrum/20260822/task_30) -----------------------------
    ledger_target, ledger_provenance = resolve_ledger_path(
        no_ledger=args.no_ledger, ledger=args.ledger
    )
    if ledger_target is None:
        print(f"ledger: not appended [{ledger_provenance}]")
    else:
        ledger_target.parent.mkdir(parents=True, exist_ok=True)
        with ledger_target.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(ledger_row, sort_keys=True) + "\n")
        if ledger_provenance != "default":
            print(f"ledger: appended to {ledger_target} [{ledger_provenance}]")
    # ---- END CARD GATE-0b --------------------------------------------------

    # K0: append freeze under 20260805/task_1/freeze — never rewrite the
    # 20260804/task_6 historical baseline pointer.
    if (
        args.mode == "baseline"
        and args.freeze
        and version == EPISODE_SET_V1
        and not args.drift_cells
        and args.pose_drift_profile is None
    ):
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
                "pose_drift_profile": args.pose_drift_profile,
                "pose_drift": aggregate.get("pose_drift"),
                "baseline_version": set_label,
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
