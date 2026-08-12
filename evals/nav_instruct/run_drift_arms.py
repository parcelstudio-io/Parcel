"""DR-2 — the standing degraded-pose arms, and the two-stage floor protocol.

One entry point, two stages, and the rule between them fixed before either ran.

**Stage A** runs every pre-registered arm on the long-travel drift cells and
REPORTS. It asserts nothing derived; it only enforces what is hard from day one
(zero collisions, zero false arrivals) and the injection's own non-vacuity.

**Stage B** re-runs the identical arms and asserts the floors derived from Stage
A. The derivation is mechanical and total:

    floor(profile, metric) = Stage-A measured value - one episode quantum (1/n)

No other margin. No per-profile discretion. No metric gets a different rule.
That is the whole protocol, and it is written here rather than in a status doc
so that a later reader cannot reconstruct a friendlier one. ``DRIFT_FLOORS``
below is filled in from the Stage-A table and from nothing else; the Stage-A
numbers land in ``scrum/20260811/task_2/DR2_STATUS.md`` before any floor is
asserted.

Why floors at all, and why only these
-------------------------------------
A floor's job is to catch a REGRESSION, not to certify a capability. So SR gets
a floor, and the two safety invariants are hard rather than floored: a
collision or a false arrival is not a number that may drift by one episode, it
is a thing that must not happen.

The re-anchor assertion is scoped to ``calibrated_go2_reanchoring`` alone.
``MAP`` is truth-passthrough on every other profile — the count there is
pre-known to be 0 and asserting "> 0" on them would be asserting a bug. The
``*_lost`` arms instead assert what only they can show: the scheduled window
HELD and then RECOVERED.
"""

from __future__ import annotations

import argparse
import json
import math
import time
from datetime import datetime, timezone
from itertools import pairwise
from pathlib import Path
from typing import Any

from evals.nav_instruct.drift_cells import (
    DRIFT_PROVENANCE,
    DRIFT_SET_NAME,
    generate_drift_cells,
)
from evals.nav_instruct.runner import (
    RUNNER_VERSION,
    NavInstructRunner,
    aggregate_results,
)

DEFAULT_OUT = Path(__file__).resolve().parent / "results"

#: The arms, pre-registered. ``None`` is the truth-pose control: it carries no
#: floor (it is the reference the others are read against) and it is what proves
#: the substrate itself is clean under the shipping pose source.
DRIFT_ARMS: tuple[str | None, ...] = (
    None,
    "calibrated_go2",
    "go2_aggressive",
    "go2_degraded",
    "calibrated_go2_lost",
    "go2_degraded_lost",
    "calibrated_go2_reanchoring",
)

#: Run parameters. Fixed here so Stage A and Stage B cannot differ by one.
DRIFT_MODE = "candidate"
DRIFT_BUDGET_POLICY = "scaled-path-v1"
#: Base step budget, left at the CLI's own default. Under ``scaled-path-v1``
#: the per-episode budget is ``max(base, 120 + route/0.03)``, which on this
#: substrate's 10.0-13.5 m routes is 453-570 steps — 2-3x the base, so the base
#: is not the binding constraint and the budget every cell runs under is the
#: path-scaled one.
#:
#: MEASURED, on the full 61-cell substrate under the truth-pose control, before
#: any arm was run (``scrum/20260811/task_2/DR2_STATUS.md`` §3):
#:
#:   base 200 (scaled budget binds) -> SR 0.1639, mean path 5.84 m
#:   base 800 (flat budget binds)   -> SR 0.1967, mean path 6.55 m
#:
#: So a 4x base moves SR by two episodes and mean travel by 0.7 m; most of what
#: it buys is re-LABELLING a ``navigation_step_limit`` as the honest
#: ``semantic_target_unreachable`` / ``navigation_no_progress`` the episode was
#: heading for anyway. The base stays at 200 because raising it to 800 would
#: make a FLAT budget bind on every cell, which is the "fixed" policy the
#: budget-honest card replaced, and because re-picking a constant after seeing
#: which value scores better is the tuning-to-a-gate move rule 6 forbids. The
#: numbers are recorded here so the choice is auditable rather than asserted.
DRIFT_MAX_STEPS = 200

#: One episode quantum is ``1/n``. The floor protocol subtracts exactly one.
FLOOR_QUANTUM_EPISODES = 1

#: Stage-A measured SR per profile, and therefore the Stage-B floor.
#: ``sr_floor = sr_stage_a - 1/n``, computed by :func:`derive_floors` from the
#: Stage-A artifact named in :data:`DRIFT_FLOORS_PROVENANCE` and from nothing
#: else. n = 61, so one episode quantum is 1/61 = 0.016393442622950821.
#: ``tests/test_dr2_pose_drift_arm.py`` re-derives every entry below from that
#: artifact's own arm rows, so a hand-edited floor cannot survive a commit.
#:
#: The trailing comment on each line is the Stage-A measured SR the floor was
#: subtracted from — the number that also appears in the Stage-A table in
#: ``scrum/20260811/task_2/DR2_STATUS.md`` §4, which was written BEFORE any of
#: these were pinned (the Y-3 lesson).
DRIFT_FLOORS: dict[str, dict[str, float]] = {
    "calibrated_go2": {"sr": 0.13114754098360656},              # 9/61 - 1/61
    "calibrated_go2_lost": {"sr": 0.09836065573770492},         # 7/61 - 1/61
    "calibrated_go2_reanchoring": {"sr": 0.04918032786885246},  # 4/61 - 1/61
    "go2_aggressive": {"sr": 0.08196721311475409},              # 6/61 - 1/61
    "go2_degraded": {"sr": 0.032786885245901634},               # 3/61 - 1/61
    "go2_degraded_lost": {"sr": 0.032786885245901634},          # 3/61 - 1/61
}

#: The Stage-A run the floors above were derived from — so a floor can always be
#: traced to the invocation that produced it. The file lives next to this
#: module's other outputs in ``evals/nav_instruct/results/``.
#:
#: **That Stage-A run FAILED its hard invariant** (one ``false_arrival`` on
#: ``calibrated_go2_reanchoring``) and the failure is a live, reproduced,
#: owner-facing finding, not a flake — see DR2_STATUS.md §5. The floors are
#: pinned anyway and deliberately: they are SR regression catchers, a different
#: gate from ``:safety``, and leaving them unpinned would have traded a real
#: red (``:safety``) for a silent one (``:floors`` skipping forever). The safety
#: gate stays red until the finding is adjudicated; nothing here makes it green.
DRIFT_FLOORS_PROVENANCE = (
    "drift-arms-stage-a-20260812T061640Z.json — Stage A, 7 arms x 61 cells, "
    "candidate mode, scaled-path-v1, runner nav-instruct-v1.1-k0-arrival; "
    "floors = that run's per-arm SR minus 1/61, mechanically, no discretion"
)


def run_arm(
    profile: str | None,
    episodes: tuple[Any, ...],
    *,
    mode: str = DRIFT_MODE,
    max_steps: int = DRIFT_MAX_STEPS,
    budget_policy: str = DRIFT_BUDGET_POLICY,
) -> dict[str, Any]:
    """Run every cell under one pose profile and return its measured row.

    A FRESH ``NavInstructRunner`` per arm: the world's scan RNG is seeded once
    per world construction and never re-seeded by ``reset()``
    (``episodes/V4S_MATCHER_ARM.md``), so two arms sharing a runner would not be
    sharing a scan sequence. One runner per arm makes every arm start from the
    identical RNG state, which is the only way the arms are comparable at all.
    """

    runner = NavInstructRunner(
        max_steps=max_steps,
        mode=mode,
        budget_policy=budget_policy,
        pose_drift_profile=profile,
    )
    started = time.perf_counter()
    results = [runner.run_episode(ep) for ep in episodes]
    elapsed = time.perf_counter() - started
    aggregate = aggregate_results(results, scene=runner.scene)
    authority = aggregate["authority_histogram"]
    distances = [
        _path_length(result.trace) for result in results
    ]
    row: dict[str, Any] = {
        "profile": profile,
        "n": aggregate["n"],
        "sr": aggregate["sr"],
        "spl": aggregate["spl"],
        "mean_dtg_m": aggregate["mean_dtg_m"],
        "collision_total": aggregate["collision_total"],
        "false_arrival": int(authority.get("false_arrival", 0)),
        "authority_histogram": authority,
        "failure_histogram": aggregate["failure_histogram"],
        # Measured from the traces, so the distance column is the robot's real
        # path and not the generator's planned route.
        "path_m_total": sum(distances),
        "path_m_mean": sum(distances) / max(len(distances), 1),
        "elapsed_s": elapsed,
        "pose_drift": aggregate.get("pose_drift"),
        "episodes": [
            {
                "episode_id": result.episode_id,
                "success": bool(result.score.success),
                "reason": result.reason,
                "authority": result.authority_category,
                "path_m": distance,
                "pose_drift": result.pose_drift,
            }
            for result, distance in zip(results, distances, strict=True)
        ],
    }
    return row


def _path_length(trace: tuple[dict[str, Any], ...]) -> float:
    return sum(
        math.hypot(
            float(trace[i]["x"]) - float(trace[i - 1]["x"]),
            float(trace[i]["y"]) - float(trace[i - 1]["y"]),
        )
        for i in range(1, len(trace))
    )


def hard_invariants(row: dict[str, Any]) -> list[str]:
    """Hard from day one, every profile, both stages. Returns the violations."""

    problems: list[str] = []
    if int(row["collision_total"]) != 0:
        problems.append(f"{row['profile']}: collisions={row['collision_total']} != 0")
    if int(row["false_arrival"]) != 0:
        problems.append(f"{row['profile']}: false_arrival={row['false_arrival']} != 0")
    return problems


def non_vacuity(row: dict[str, Any]) -> list[str]:
    """The injection really ran, really drifted, and drifted in its own band."""

    profile = row["profile"]
    if profile is None:
        # The control: the shipping truth passthrough must record NO drift at
        # all. If it ever does, the arms are not measuring what they claim.
        if row.get("pose_drift") is not None:
            return ["truth control recorded a pose_drift block"]
        return []
    drift = row.get("pose_drift")
    if not drift:
        return [f"{profile}: no pose_drift evidence recorded"]
    problems: list[str] = []
    if int(drift["episodes"]) != int(row["n"]):
        problems.append(
            f"{profile}: {drift['episodes']} drift rows for {row['n']} episodes"
        )
    if int(drift["seeds_distinct"]) != int(drift["episodes"]):
        problems.append(
            f"{profile}: {drift['seeds_distinct']} distinct seeds over "
            f"{drift['episodes']} episodes — the per-episode seed did not vary"
        )
    if int(drift["episodes_banded"]) < 1:
        problems.append(f"{profile}: no episode travelled far enough to be banded")
    if int(drift["episodes_in_band"]) != int(drift["episodes_banded"]):
        problems.append(
            f"{profile}: {drift['episodes_in_band']}/{drift['episodes_banded']} "
            f"banded episodes inside {drift['band_pct']}"
        )
    if float(drift["divergence_m_mean"]) <= 0.0:
        problems.append(f"{profile}: mean truth-vs-ODOM divergence is 0")
    # Scoped metrics: asserted only where the mechanism exists.
    if profile.endswith("_lost"):
        if int(drift["episodes_with_lost"]) < 1:
            problems.append(f"{profile}: the scheduled LOST window never held")
        elif int(drift["episodes_lost_recovered"]) != int(drift["episodes_with_lost"]):
            problems.append(
                f"{profile}: {drift['episodes_lost_recovered']}/"
                f"{drift['episodes_with_lost']} LOST episodes recovered"
            )
    if profile.endswith("_reanchoring") and int(drift["reanchor_events_total"]) < 1:
        problems.append(f"{profile}: no MAP re-anchor event was observed")
    return problems


def ladder_monotone(rows: list[dict[str, Any]]) -> list[str]:
    """The tiers must separate at the ARM level, which is where they can.

    Per episode they cannot — DR1_STATUS §6 shows one profile's distribution
    spanning three tiers — so this is asserted on the arm mean, the statistic
    the per-episode seed variation makes meaningful in the first place.
    """

    by_profile = {row["profile"]: row for row in rows}
    ladder = ["calibrated_go2", "go2_aggressive", "go2_degraded"]
    means = []
    for name in ladder:
        row = by_profile.get(name)
        if row is None or not row.get("pose_drift"):
            return []
        means.append(float(row["pose_drift"]["divergence_pct_mean"]))
    if not all(a < b for a, b in pairwise(means)):
        return [
            "the drift ladder is not monotone at the arm mean: "
            + " / ".join(f"{n}={m:.2f}%" for n, m in zip(ladder, means, strict=True))
        ]
    return []


def derive_floors(rows: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    """Stage-A value minus exactly one episode quantum. The whole derivation."""

    floors: dict[str, dict[str, float]] = {}
    for row in rows:
        profile = row["profile"]
        if profile is None:
            continue
        quantum = FLOOR_QUANTUM_EPISODES / float(row["n"])
        floors[profile] = {"sr": max(0.0, float(row["sr"]) - quantum)}
    return floors


def check_floors(rows: list[dict[str, Any]]) -> list[str]:
    """Stage B: every arm at or above its pinned floor."""

    problems: list[str] = []
    for row in rows:
        profile = row["profile"]
        if profile is None:
            continue
        floor = DRIFT_FLOORS.get(profile)
        if floor is None:
            problems.append(f"{profile}: no Stage-B floor is pinned for this arm")
            continue
        if float(row["sr"]) < float(floor["sr"]):
            problems.append(
                f"{profile}: sr={row['sr']:.4f} below floor {floor['sr']:.4f}"
            )
    return problems


def run_stage(
    stage: str,
    *,
    limit: int = 0,
    arms: tuple[str | None, ...] = DRIFT_ARMS,
) -> dict[str, Any]:
    """Run every arm once and evaluate the checks this stage is allowed to make.

    ``limit`` truncates the substrate. That is legitimate for a smoke run and
    illegitimate for a floor verdict, and the difference is enforced rather than
    documented: :data:`DRIFT_FLOORS` was derived on n = 61, so an arm's SR over
    a PREFIX of those cells is a statistic about a different set. Certifying it
    either way would be wrong, and certifying it green would hand anyone a
    one-flag way to dodge a red floor (``--stage b --limit 3``).

    So a truncated Stage B does not run :func:`check_floors` at all, records
    ``floors_certified: False``, and **cannot pass** — it appends its own
    problem saying why. The full run is the only run that can be green.
    """

    stage = str(stage).strip().lower()
    if stage not in {"a", "b"}:
        raise ValueError("stage must be 'a' or 'b'")
    episodes = generate_drift_cells()
    if limit > 0:
        episodes = episodes[:limit]
    rows = [run_arm(profile, episodes) for profile in arms]
    problems: list[str] = []
    for row in rows:
        problems.extend(hard_invariants(row))
        problems.extend(non_vacuity(row))
    problems.extend(ladder_monotone(rows))
    derived = derive_floors(rows)
    # Stage A never certifies anything derived, so the flag is only meaningful
    # on B; ``False`` on A is the honest reading, not a failure.
    floors_certified = stage == "b" and limit <= 0
    if floors_certified:
        problems.extend(check_floors(rows))
    elif stage == "b":
        problems.append(
            f"stage B ran with limit={limit} on {len(episodes)} of "
            f"{len(generate_drift_cells())} cells: the pinned floors were derived "
            "on the full substrate and a prefix cannot certify them — re-run "
            "without --limit"
        )
    return {
        "floors_certified": floors_certified,
        "stage": stage,
        "runner_version": RUNNER_VERSION,
        "episode_set": DRIFT_SET_NAME,
        "episode_set_provenance": DRIFT_PROVENANCE,
        "n": len(episodes),
        "mode": DRIFT_MODE,
        "budget_policy": DRIFT_BUDGET_POLICY,
        "max_steps": DRIFT_MAX_STEPS,
        "generated_at": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "arms": rows,
        "derived_floors": derived,
        "pinned_floors": DRIFT_FLOORS,
        "pinned_floors_provenance": DRIFT_FLOORS_PROVENANCE,
        "problems": problems,
        "passed": not problems,
    }


def markdown_table(payload: dict[str, Any]) -> str:
    header = (
        "| profile | SR | collisions | false_arrival | path m (total/mean) | "
        "divergence % (mean/min/max) | in band | LOST (held/recovered) | re-anchors |"
    )
    lines = [header, "|---|---|---|---|---|---|---|---|---|"]
    for row in payload["arms"]:
        drift = row.get("pose_drift") or {}
        name = row["profile"] or "truth (control)"
        if drift:
            div = (
                f"{drift['divergence_pct_mean']:.2f} / "
                f"{drift['divergence_pct_min']:.2f} / "
                f"{drift['divergence_pct_max']:.2f}"
            )
            band = f"{drift['episodes_in_band']}/{drift['episodes_banded']}"
            lost = f"{drift['episodes_with_lost']}/{drift['episodes_lost_recovered']}"
            anchors = str(drift["reanchor_events_total"])
        else:
            div, band, lost, anchors = "—", "—", "—", "—"
        lines.append(
            f"| `{name}` | {row['sr']:.4f} | {row['collision_total']} | "
            f"{row['false_arrival']} | {row['path_m_total']:.1f} / "
            f"{row['path_m_mean']:.2f} | {div} | {band} | {lost} | {anchors} |"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("a", "b"), default="a")
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help=(
            "cap episodes (0 = all). A smoke knob only: under --stage b a "
            "truncated run does NOT certify the pinned floors and cannot pass."
        ),
    )
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    payload = run_stage(args.stage, limit=args.limit)
    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out / f"drift-arms-stage-{args.stage}-{payload['generated_at']}.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(markdown_table(payload))
    print()
    if payload["problems"]:
        for problem in payload["problems"]:
            print(f"RED: {problem}")
    if args.stage == "b":
        print(
            "floors: "
            + ("CERTIFIED on the full substrate" if payload["floors_certified"]
               else f"NOT CERTIFIED (limit={args.limit})")
        )
    print(f"\nstage {args.stage}: {'PASS' if payload['passed'] else 'FAIL'}  ->  {path}")
    if args.json:
        print(json.dumps(payload["derived_floors"], indent=2, sort_keys=True))
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
