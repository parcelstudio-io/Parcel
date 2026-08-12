"""RM-3 driver — the paired route-memory arms, one process per arm.

Card ``scrum/20260811/task_2/SLAM_M_PLAN.md`` (r2), Wave 3, RM-3.

Three commands:

* ``run`` — one arm (``--arm on|off``) over the ``v4r`` taught-prior-route
  substrate, persisting a candidate-only artifact under
  ``evals/nav_instruct/results/`` with the ``rm3-`` namespace prefix.
* ``both`` — spawns ``run`` twice, **as subprocesses**, one per arm. The card
  pre-registers isolated processes and this is how that is discharged; the
  parent process never constructs a navigator of either arm.
* ``pair`` — reads two artifacts and prints the paired table: the 2x2 flip
  decomposition, the net flips, and the EXACT McNemar p.

Three isolation properties, each for a measured reason
------------------------------------------------------
1. **One process per arm.** Pre-registered by the card.
2. **One WORLD per episode.** ``episodes/V4S_MATCHER_ARM.md`` records the
   harness fact this rests on: ``HeadlessCityWorld._scan_rng`` is seeded once
   per world construction and is never re-seeded by ``reset()``, so inside one
   runner process an arm that shortens one episode shifts the scan RNG for every
   LATER episode — "a per-episode number from a multi-episode run is not
   portable and must be re-measured with one world per episode". McNemar is
   *entirely* per-episode, so a shared world would break the pairing itself, not
   merely add noise. A fresh :class:`NavInstructRunner` per episode is therefore
   the DEFAULT here, not an option (AF-2 measured 4 apparent per-episode
   differences on a 60-cell paired arm that all vanished under isolation).
3. **A mission boundary per episode.** Verified rather than assumed, and
   reported in the artifact header: a fresh runner means a fresh
   ``DirectiveNavigator`` (so a fresh place graph AND a fresh semantic memory),
   and inside the episode ``DirectiveNavigator.start()`` /
   ``stop()`` call ``_reset_route_memory_track()`` at both the taught leg's
   boundaries — RM2_STATUS.md §2(1). The taught leg and the measured mission
   therefore share a graph (which is the point) and share no ingest track (which
   is the honesty rule).

What the arms are
-----------------
Both arms drive the SAME taught leg — identical scripted route, identical
physics, identical ticks — and differ in exactly one navigator flag. The taught
leg is a no-op for the OFF arm's place graph because the OFF arm has no place
graph, which is what makes the comparison a test of route memory rather than of
having driven around first.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import time
from itertools import pairwise
from pathlib import Path
from typing import Any

from evals.nav_instruct.route_memory_cells import (
    ROUTE_MEMORY_N_CELLS,
    ROUTE_MEMORY_PROVENANCE,
    ROUTE_MEMORY_SET_NAME,
    TaughtRoutePreDrive,
    cells_digest,
    generate_route_memory_cells,
    taught_route_of,
)
from evals.nav_instruct.runner import (
    RUNNER_VERSION,
    EpisodeRunResult,
    NavInstructRunner,
)

RESULTS_DIR = Path(__file__).resolve().parent / "results"

#: Namespace prefix for every artifact this card writes. Nothing outside it is
#: touched, and no ``v4r`` row is ever a frozen baseline.
ARTIFACT_PREFIX = "rm3"

#: Base step budget, before the per-episode ``scaled-path-v1`` scaling. Same 200
#: DR-2's drift arms use, for the same reason: it is the floor a scaled budget
#: can only ever ADD to.
BASE_MAX_STEPS = 200

#: The budget policy, and the whole of the probe-hold argument.
#:
#: ``scaled-path-v1`` derives each episode's budget from its own
#: ``shortest_path_m`` — which for a ``v4r`` cell IS its taught route length —
#: as ``120 + ceil(route_m / 0.03)`` ticks, capped at 1200. Both arms of a pair
#: run the SAME episode and therefore the SAME budget, so the budget cannot
#: favour an arm.
#:
#: **The ~9-tick probe hold cannot straddle it** (AUDIT_WAVE2_FABLE.md's binding
#: note). RM-2's hand-back probe holds the true goal for at most
#: ``2 x GRID_REPLAN_INTERVAL_STEPS = 10`` ticks, once per chain, and measured
#: +9 on RM-2's own corridor. The budget's FIXED overhead term alone is 120
#: ticks — 12x the worst-case hold — and the smallest budget any admitted cell
#: draws is 120 + ceil(19.13 / 0.03) = 758 ticks, i.e. 75x the hold. So no
#: outcome in this table can be decided by whether the probe held.
BUDGET_POLICY = "scaled-path-v1"

#: Candidate mode: ``instructnav_recovery`` on, i.e. the memory / scan /
#: frontier ladder available to BOTH arms. Deliberately the setting that gives
#: the flag-OFF control its best shot — and it is also required, because these
#: cells commit their goal from the navigator's semantic memory of the taught
#: leg, which is part of that ladder.
MODE = "candidate"

DOES_NOT_PROVE = (
    "one scene, one simulator, sim-truth semantics — not camera perception",
    "the taught leg is a scripted demonstration, not a learned or spoken teach",
    "route memory is session-scoped: nothing here measures cross-session recall",
)


# ---------------------------------------------------------------------------
# Exact McNemar
# ---------------------------------------------------------------------------


def mcnemar_exact(b: int, c: int) -> float:
    """Two-sided exact McNemar p for a discordant split ``(b, c)``.

    The exact (binomial) form, never the chi-square approximation: with the
    discordant counts this substrate produces the approximation is not valid,
    and the card pre-registers a threshold (0.031) that sits between two
    attainable exact values, so the estimator has to be the exact one.

    ``b + c == 0`` (no discordant pairs at all) returns 1.0: nothing was
    observed that could distinguish the arms.
    """

    n = int(b) + int(c)
    if n == 0:
        return 1.0
    k = max(int(b), int(c))
    tail = sum(math.comb(n, i) for i in range(k, n + 1)) / (2.0**n)
    return min(1.0, 2.0 * tail)


# ---------------------------------------------------------------------------
# Path fidelity (the teach-and-repeat measurement)
# ---------------------------------------------------------------------------


def _point_segment_distance(
    point: tuple[float, float],
    a: tuple[float, float],
    b: tuple[float, float],
) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    length_sq = dx * dx + dy * dy
    if length_sq <= 1e-12:
        return math.hypot(point[0] - a[0], point[1] - a[1])
    t = ((point[0] - a[0]) * dx + (point[1] - a[1]) * dy) / length_sq
    t = min(1.0, max(0.0, t))
    return math.hypot(point[0] - (a[0] + t * dx), point[1] - (a[1] + t * dy))


def path_fidelity(
    trace: tuple[dict[str, Any], ...], route: tuple[tuple[float, float], ...]
) -> dict[str, Any] | None:
    """How closely the MEASURED mission's path followed the taught line.

    ``mean_m`` / ``max_m`` are the deviation of every traced position from the
    taught polyline; ``coverage`` is the fraction of taught VERTICES the run
    came within one tracking tolerance of, which is the half of fidelity a
    deviation statistic cannot see (a robot that never leaves the start pose has
    a tiny mean deviation and covers nothing).
    """

    if not trace or len(route) < 2:
        return None
    points = [(float(step["x"]), float(step["y"])) for step in trace]
    deviations = [
        min(_point_segment_distance(point, a, b) for a, b in pairwise(route))
        for point in points
    ]
    covered = sum(
        1
        for vertex in route
        if any(math.hypot(p[0] - vertex[0], p[1] - vertex[1]) <= 0.5 for p in points)
    )
    return {
        "mean_m": sum(deviations) / len(deviations),
        "max_m": max(deviations),
        "vertices": len(route),
        "vertices_covered": covered,
        "coverage": covered / len(route),
        "path_m": sum(math.dist(a, b) for a, b in pairwise(points)),
    }


# ---------------------------------------------------------------------------
# One arm
# ---------------------------------------------------------------------------


def _row(result: EpisodeRunResult, episode: Any, wall_s: float) -> dict[str, Any]:
    payload = result.as_dict()
    route_memory = dict(payload.get("route_memory") or {})
    pre_drive = dict(route_memory.get("pre_drive") or {})
    baseline = dict(pre_drive.get("counters") or {})
    baseline_hook = dict(baseline.get("hook") or {})
    hook = dict(route_memory.get("hook") or {})

    def delta(name: str) -> int:
        return int(route_memory.get(name, 0)) - int(baseline.get(name, 0))

    def hook_delta(name: str) -> int:
        return int(hook.get(name, 0) or 0) - int(baseline_hook.get(name, 0) or 0)

    trace = result.trace
    first = trace[0] if trace else {}
    cell = (episode.placement_overrides or {}).get("route_memory_cell", {})
    return {
        "episode_id": result.episode_id,
        "family": result.family,
        "target_entity_id": episode.target_entity_id,
        "success": bool(result.score.success),
        "reason": result.reason,
        "mission_status": result.mission_status,
        "distance_to_goal_m": result.score.distance_to_goal_m,
        "spl": result.score.spl,
        "collision_count": result.collision_count,
        "scorer_arrival": result.scorer_arrival,
        "system_arrival": result.system_arrival,
        "authority_category": result.authority_category,
        "failure": result.score.failure.value,
        "max_steps": result.max_steps,
        "trace_len": len(trace),
        # Was the goal KNOWN on the opening tick? Measured, per episode.
        "opening_resolution_state": str(first.get("resolution_state") or ""),
        "opening_grounding_outcome": str(first.get("grounding_outcome") or ""),
        "cell": cell,
        "pre_drive": {
            key: value for key, value in pre_drive.items() if key != "counters"
        },
        # Measured-mission counters, as DELTAS against the taught leg's totals.
        "measured": {
            "routes_queried": hook_delta("routes_queried"),
            "routes_found": delta("routes_found"),
            "proposals": delta("proposals"),
            "wins": delta("wins"),
            "vetoes": delta("vetoes"),
            "chain_ticks": delta("chain_ticks"),
            "deferred_releases": delta("deferred_releases"),
            "handbacks": delta("handbacks"),
            "keyframes": delta("keyframes"),
            "flushes": delta("flushes"),
        },
        "taught_leg_counters": baseline,
        "route_memory_enabled": bool(route_memory.get("enabled")),
        # DR-2's per-episode drift evidence, carried verbatim on the drifted
        # report-only arm and ``None`` everywhere else.
        "pose_drift": payload.get("pose_drift"),
        # The graph as it stood at the end of the episode: the keyframe-integrity
        # evidence the drifted arm reports (MAP-frame discipline observed).
        "graph": hook or None,
        "fidelity": path_fidelity(trace, taught_route_of(episode)),
        "wall_s": round(wall_s, 2),
    }


#: The report-only substrate: v4s's LA (look-around) and BB (beyond-block) axes.
#: The plan registers them as "expected ≈ no-op — confirming the honesty rule,
#: not failing a gate": a v4s episode's own traversal is a straight corridor, so
#: the place graph it builds never covers a route the planner cannot already
#: see, and RM-1's router refuses to invent one. There is no taught leg here,
#: deliberately: that IS the arm.
V4S_REPORT_AXES: tuple[str, ...] = ("LA", "BB")


def _substrate_episodes(substrate: str, limit: int) -> tuple[Any, ...]:
    if substrate == ROUTE_MEMORY_SET_NAME:
        return generate_route_memory_cells(limit=limit)
    if substrate == "v4s":
        from evals.nav_instruct.generator import generate_v4s_matrix

        per_axis = max(1, limit // len(V4S_REPORT_AXES))
        episodes = generate_v4s_matrix(per_axis=per_axis)
        return tuple(ep for ep in episodes if ep.tier in V4S_REPORT_AXES)
    raise ValueError(f"unknown substrate {substrate!r}")


def run_arm(
    *,
    arm: str,
    limit: int,
    pose_drift_profile: str | None,
    matcher: str,
    substrate: str = ROUTE_MEMORY_SET_NAME,
) -> dict[str, Any]:
    """Run one arm end to end and return the artifact payload."""

    if arm not in {"on", "off"}:
        raise ValueError("arm must be 'on' or 'off'")
    episodes = _substrate_episodes(substrate, limit)
    teaches = substrate == ROUTE_MEMORY_SET_NAME
    started = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    t0 = time.time()
    rows: list[dict[str, Any]] = []
    for episode in episodes:
        episode_t0 = time.time()
        # ONE WORLD PER EPISODE — see the module docstring, isolation property 2.
        runner = NavInstructRunner(
            mode=MODE,
            max_steps=BASE_MAX_STEPS,
            budget_policy=BUDGET_POLICY,
            navigator_overrides={"route_memory": arm == "on"},
            pose_drift_profile=pose_drift_profile,
            pre_drive=TaughtRoutePreDrive() if teaches else None,
        )
        result = runner.run_episode(episode)
        rows.append(_row(result, episode, time.time() - episode_t0))
        print(
            f"[{arm}] {len(rows):>3}/{len(episodes)} {result.episode_id} "
            f"success={rows[-1]['success']} reason={result.reason} "
            f"found={rows[-1]['measured']['routes_found']} "
            f"chain={rows[-1]['measured']['chain_ticks']}",
            flush=True,
        )
    return {
        "artifact": f"{ARTIFACT_PREFIX}-{arm}",
        "card": "RM-3",
        "set": substrate,
        "taught_leg": teaches,
        "set_provenance": (
            ROUTE_MEMORY_PROVENANCE
            if teaches
            else "v4s LA/BB, candidate-only report-only arm (no taught leg)"
        ),
        "cells_digest": cells_digest(episodes),
        "n": len(episodes),
        "arm": arm,
        "route_memory": arm == "on",
        "matcher_arm": matcher,
        "pose_drift_profile": pose_drift_profile,
        "mode": MODE,
        "budget_policy": BUDGET_POLICY,
        "base_max_steps": BASE_MAX_STEPS,
        "runner_version": RUNNER_VERSION,
        "frozen_baseline": False,
        "isolation": {
            "process_per_arm": True,
            "world_per_episode": True,
            "navigator_per_episode": True,
            "mission_boundary_per_leg": True,
        },
        "generated": started,
        "elapsed_s": round(time.time() - t0, 1),
        "does_not_prove": list(DOES_NOT_PROVE),
        "episodes": rows,
        "aggregate": _aggregate(rows),
    }


def _aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = max(len(rows), 1)
    fidelities = [row["fidelity"] for row in rows if row.get("fidelity")]
    return {
        "n": len(rows),
        "successes": sum(1 for row in rows if row["success"]),
        "sr": sum(1 for row in rows if row["success"]) / n,
        "collisions": sum(int(row["collision_count"]) for row in rows),
        "false_arrival": sum(
            1
            for row in rows
            if row["system_arrival"] and not row["scorer_arrival"]
        ),
        "mean_dtg_m": sum(
            0.0
            if not math.isfinite(row["distance_to_goal_m"])
            else row["distance_to_goal_m"]
            for row in rows
        )
        / n,
        "episodes_goal_known_at_tick0": sum(
            1 for row in rows if row["opening_resolution_state"] == "resolved"
        ),
        "teach_completed": sum(
            1 for row in rows if (row["pre_drive"] or {}).get("completed")
        ),
        "teach_collisions": sum(
            int((row["pre_drive"] or {}).get("collisions") or 0) for row in rows
        ),
        "teach_ticks_total": sum(
            int((row["pre_drive"] or {}).get("teach_ticks") or 0) for row in rows
        ),
        "episodes_with_route_found": sum(
            1 for row in rows if row["measured"]["routes_found"] > 0
        ),
        "episodes_with_win": sum(1 for row in rows if row["measured"]["wins"] > 0),
        "chain_ticks_total": sum(row["measured"]["chain_ticks"] for row in rows),
        "deferred_releases_total": sum(
            row["measured"]["deferred_releases"] for row in rows
        ),
        "vetoes_total": sum(row["measured"]["vetoes"] for row in rows),
        "handbacks_total": sum(row["measured"]["handbacks"] for row in rows),
        "fidelity_mean_m": (
            sum(item["mean_m"] for item in fidelities) / len(fidelities)
            if fidelities
            else None
        ),
        "graph_keyframes_total": sum(
            int((row.get("graph") or {}).get("keyframes") or 0) for row in rows
        ),
        "graph_edges_total": sum(
            int((row.get("graph") or {}).get("edges") or 0) for row in rows
        ),
        "graph_reanchor_events_total": sum(
            int((row.get("graph") or {}).get("graph_reanchor_events") or 0)
            for row in rows
        ),
        "episodes_with_drift_row": sum(1 for row in rows if row.get("pose_drift")),
        "episodes_drift_in_band": sum(
            1 for row in rows if (row.get("pose_drift") or {}).get("in_band")
        ),
        "drift_pct_mean": (
            sum(
                float((row.get("pose_drift") or {}).get("divergence_pct") or 0.0)
                for row in rows
                if row.get("pose_drift")
            )
            / max(sum(1 for row in rows if row.get("pose_drift")), 1)
        ),
        "fidelity_coverage": (
            sum(item["coverage"] for item in fidelities) / len(fidelities)
            if fidelities
            else None
        ),
    }


# ---------------------------------------------------------------------------
# Pairing
# ---------------------------------------------------------------------------


def pair_arms(on: dict[str, Any], off: dict[str, Any]) -> dict[str, Any]:
    """The paired table. Refuses to compare artifacts that are not comparable."""

    problems: list[str] = []
    if on.get("set") != off.get("set"):
        problems.append("substrate differs")
    if on.get("cells_digest") != off.get("cells_digest"):
        problems.append("cells_digest differs — the arms did not run the same set")
    if on.get("matcher_arm") != off.get("matcher_arm"):
        problems.append("matcher_arm differs")
    if on.get("pose_drift_profile") != off.get("pose_drift_profile"):
        problems.append("pose_drift_profile differs")
    if on.get("arm") != "on" or off.get("arm") != "off":
        problems.append("arms mislabelled")
    on_rows = {row["episode_id"]: row for row in on["episodes"]}
    off_rows = {row["episode_id"]: row for row in off["episodes"]}
    shared = sorted(set(on_rows) & set(off_rows))
    if len(shared) != len(on_rows) or len(shared) != len(off_rows):
        problems.append("episode sets differ between the arms")
    both = on_only = off_only = neither = 0
    flips: list[dict[str, Any]] = []
    for episode_id in shared:
        won_on = bool(on_rows[episode_id]["success"])
        won_off = bool(off_rows[episode_id]["success"])
        if won_on and won_off:
            both += 1
        elif won_on:
            on_only += 1
        elif won_off:
            off_only += 1
        else:
            neither += 1
        if won_on != won_off:
            flips.append(
                {
                    "episode_id": episode_id,
                    "direction": "on_only" if won_on else "off_only",
                    "on_reason": on_rows[episode_id]["reason"],
                    "off_reason": off_rows[episode_id]["reason"],
                    "on_dtg_m": on_rows[episode_id]["distance_to_goal_m"],
                    "off_dtg_m": off_rows[episode_id]["distance_to_goal_m"],
                    "on_measured": on_rows[episode_id]["measured"],
                }
            )
    return {
        "artifact": f"{ARTIFACT_PREFIX}-pair",
        "n": len(shared),
        "matcher_arm": on.get("matcher_arm"),
        "pose_drift_profile": on.get("pose_drift_profile"),
        "cells_digest": on.get("cells_digest"),
        "table": {
            "both_succeed": both,
            "on_only": on_only,
            "off_only": off_only,
            "neither": neither,
        },
        "net_flips": on_only - off_only,
        "discordant": on_only + off_only,
        "mcnemar_p_exact": mcnemar_exact(on_only, off_only),
        "sr_on": on["aggregate"]["sr"],
        "sr_off": off["aggregate"]["sr"],
        "flips": flips,
        "problems": problems,
        "comparable": not problems,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _write(payload: dict[str, Any], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return path


def _artifact_name(
    arm: str, matcher: str, profile: str | None, stamp: str
) -> str:
    suffix = f"-{profile}" if profile else ""
    return f"{ARTIFACT_PREFIX}-{arm}-{matcher}{suffix}-{stamp}.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="one arm, in this process")
    run.add_argument("--arm", choices=("on", "off"), required=True)
    run.add_argument("--limit", type=int, default=ROUTE_MEMORY_N_CELLS)
    run.add_argument("--matcher", choices=("default", "siglip2"), default="default")
    run.add_argument("--pose-drift-profile", default=None)
    run.add_argument(
        "--substrate", choices=(ROUTE_MEMORY_SET_NAME, "v4s"), default=ROUTE_MEMORY_SET_NAME
    )
    run.add_argument("--out", default=None)

    both = sub.add_parser("both", help="both arms, one SUBPROCESS each")
    both.add_argument("--limit", type=int, default=ROUTE_MEMORY_N_CELLS)
    both.add_argument("--matcher", choices=("default", "siglip2"), default="default")
    both.add_argument("--pose-drift-profile", default=None)
    both.add_argument(
        "--substrate", choices=(ROUTE_MEMORY_SET_NAME, "v4s"), default=ROUTE_MEMORY_SET_NAME
    )
    both.add_argument("--sequential", action="store_true")

    pair = sub.add_parser("pair", help="paired table from two artifacts")
    pair.add_argument("on")
    pair.add_argument("off")
    pair.add_argument("--out", default=None)

    args = parser.parse_args(argv)

    if args.command == "run":
        payload = run_arm(
            arm=args.arm,
            limit=args.limit,
            pose_drift_profile=args.pose_drift_profile,
            matcher=args.matcher,
            substrate=args.substrate,
        )
        stamp = payload["generated"]
        path = Path(args.out) if args.out else RESULTS_DIR / _artifact_name(
            f"{args.substrate}-{args.arm}", args.matcher, args.pose_drift_profile, stamp
        )
        _write(payload, path)
        print(f"wrote {path}")
        print(json.dumps(payload["aggregate"], indent=2, sort_keys=True))
        return 0

    if args.command == "both":
        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        env = dict(os.environ)
        if args.matcher == "siglip2":
            env["PARCEL_SIGLIP2_ONNX"] = "1"
        else:
            env.pop("PARCEL_SIGLIP2_ONNX", None)
        outputs: dict[str, Path] = {}
        procs: dict[str, subprocess.Popen[bytes]] = {}
        for arm in ("on", "off"):
            path = RESULTS_DIR / _artifact_name(
                f"{args.substrate}-{arm}", args.matcher, args.pose_drift_profile, stamp
            )
            outputs[arm] = path
            command = [
                sys.executable,
                "-m",
                "evals.nav_instruct.run_route_memory_arms",
                "run",
                "--arm",
                arm,
                "--limit",
                str(args.limit),
                "--matcher",
                args.matcher,
                "--substrate",
                args.substrate,
                "--out",
                str(path),
            ]
            if args.pose_drift_profile:
                command += ["--pose-drift-profile", args.pose_drift_profile]
            print("spawn:", " ".join(command), flush=True)
            if args.sequential:
                subprocess.run(command, check=True, env=env)
            else:
                procs[arm] = subprocess.Popen(command, env=env)
        for arm, proc in procs.items():
            if proc.wait() != 0:
                raise SystemExit(f"arm {arm} failed with exit code {proc.returncode}")
        on = json.loads(outputs["on"].read_text())
        off = json.loads(outputs["off"].read_text())
        table = pair_arms(on, off)
        table["on_artifact"] = outputs["on"].name
        table["off_artifact"] = outputs["off"].name
        path = (
            RESULTS_DIR
            / f"{ARTIFACT_PREFIX}-pair-{args.substrate}-{args.matcher}-{stamp}.json"
        )
        _write(table, path)
        print(f"wrote {path}")
        print(json.dumps(table["table"], indent=2, sort_keys=True))
        print(
            f"net_flips={table['net_flips']} "
            f"mcnemar_p_exact={table['mcnemar_p_exact']:.6f} "
            f"sr_on={table['sr_on']:.4f} sr_off={table['sr_off']:.4f}"
        )
        return 0

    on = json.loads(Path(args.on).read_text())
    off = json.loads(Path(args.off).read_text())
    table = pair_arms(on, off)
    table["on_artifact"] = Path(args.on).name
    table["off_artifact"] = Path(args.off).name
    if args.out:
        _write(table, Path(args.out))
        print(f"wrote {args.out}")
    print(json.dumps(table, indent=2, sort_keys=True))
    return 0 if table["comparable"] else 1


if __name__ == "__main__":  # pragma: no cover - CLI
    raise SystemExit(main())
