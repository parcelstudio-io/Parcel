"""NAV-CORE rows N1-N7 and the five refuters.  One entry point, one JSON each.

``python bench.py`` runs the pre-registered corpus (20 episodes x 3 seeds x 2
arms) and the refuters, and writes ``results/corpus.json`` and
``results/refuters.json``.  Every number in RESULTS.md comes out of here.

The corpus is generated, never typed: episode ``e`` takes layout ``e % 4``,
goal ``PLACES[e % 6]`` and start ``STARTS[e % 5]``; ``lcm(4, 5) = 20`` so the
twenty episodes cover every (start, layout) pair exactly once and each goal
three or four times.
"""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import door
from arms import GATE_DEMAND_M, ArmA, ArmB, EpisodeSpec, _safety_policy
from room import (
    ALIASED_GOAL_ID,
    ALIASED_START,
    LAYOUTS,
    PLACES,
    PLACES_BY_ID,
    STARTS,
    alias_scan_agreement,
    audit_clearances,
)
from world_map import seed_room_map

from parcel_robot.perception_source.selection import (
    SOURCE_LEARNED_MAP,
    SemanticSourcePolicy,
    use_learned_map,
    use_semantic_source,
)

RESULTS = HERE / "results"
SEEDS = (101, 202, 303)
EPISODES = 20
#: The product's own typed non-arrival reasons, plus the door's refusal.  A
#: non-arrival outside this set is a SILENT stall, and N4 counts it as one.
TYPED_FAILURES = frozenset(
    {
        "not_found",
        "ambiguous",
        "unreachable",
        "stalled",
        "pose_lost",
        "unresolved",
        "verification_failed",
        "stop_not_confirmed",
        "door_refused",
        "pose_unhealthy",
        "arming_latched",
    }
)


def directive_for(place_id: str) -> str:
    return f"go to the {PLACES_BY_ID[place_id].label}"


def _episode_specs(seed_index: int, seed: int, learned: Any) -> list[EpisodeSpec]:
    specs = []
    for episode in range(EPISODES):
        place = PLACES[episode % len(PLACES)]
        specs.append(
            EpisodeSpec(
                episode=episode,
                seed_index=seed_index,
                seed=seed,
                layout=episode % len(LAYOUTS),
                goal_id=place.place_id,
                start=STARTS[episode % len(STARTS)],
                directive=directive_for(place.place_id),
                learned_map=learned,
            )
        )
    return specs


def _refused_row(arm: str, spec: EpisodeSpec, verdict: Any) -> dict[str, Any]:
    return {
        "arm": arm,
        "episode": spec.episode,
        "seed": spec.seed,
        "layout": str(spec.layout),
        "goal_id": spec.goal_id,
        "declared_arrival": False,
        "arrived": False,
        "false_arrival": False,
        "contacts": 0,
        "steps": 0,
        "failure_type": "door_refused",
        "note": verdict.detail[:120],
        "door_status": verdict.status,
        "truth_distance_m": None,
        "time_to_goal_s": None,
        "path_m": 0.0,
        "optimal_m": 0.0,
    }


def run_corpus(runtime: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for seed_index, seed in enumerate(SEEDS):
        learned = seed_room_map()
        use_learned_map(learned)
        for spec in _episode_specs(seed_index, seed, learned):
            verdict = door.ask(runtime, PLACES_BY_ID[spec.goal_id].label)
            for arm, cls in (("A", ArmA), ("B", ArmB)):
                if not verdict.admitted:
                    rows.append(_refused_row(arm, spec, verdict))
                    continue
                result = cls(spec).run()
                row = result.as_row()
                row["door_status"] = verdict.status
                row["route_rule"] = verdict.route_rule
                rows.append(row)
            print(
                f"  seed {seed} ep {spec.episode:2d} {spec.goal_id:14s} "
                f"L{spec.layout} A={rows[-2]['arrived']} B={rows[-1]['arrived']}",
                flush=True,
            )
    return rows


def _score(rows: list[dict[str, Any]], arm: str) -> dict[str, Any]:
    mine = [row for row in rows if row["arm"] == arm]
    arrived = [row for row in mine if row["arrived"]]
    non_arrivals = [row for row in mine if not row["declared_arrival"]]
    typed = [row for row in non_arrivals if row["failure_type"] in TYPED_FAILURES]
    ratios = [
        row["path_m"] / row["optimal_m"]
        for row in arrived
        if row.get("optimal_m")
    ]
    times = [row["time_to_goal_s"] for row in arrived if row["time_to_goal_s"]]
    resolvable = [row for row in mine if row["goal_id"] != "place_bed"]
    return {
        "episodes": len(mine),
        "N1_arrival_rate": len(arrived) / len(mine) if mine else 0.0,
        "N1_arrival_rate_object_class_goals": (
            sum(row["arrived"] for row in resolvable) / len(resolvable)
            if resolvable
            else 0.0
        ),
        "N2_false_arrivals": sum(row["false_arrival"] for row in mine),
        "N3_contacts": sum(row["contacts"] for row in mine),
        "N4_typed_failure_rate": len(typed) / len(non_arrivals) if non_arrivals else 1.0,
        "N5_median_time_to_goal_s": statistics.median(times) if times else None,
        "N5_median_path_over_optimal": statistics.median(ratios) if ratios else None,
        "failure_histogram": _histogram(row["failure_type"] for row in non_arrivals),
    }


def _histogram(values: Any) -> dict[str, int]:
    out: dict[str, int] = {}
    for value in values:
        key = str(value or "untyped")[:60]
        out[key] = out.get(key, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


def run_refuters(runtime: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for seed_index, seed in enumerate(SEEDS):
        learned = seed_room_map()
        use_learned_map(learned)
        base = {"seed_index": seed_index, "seed": seed, "learned_map": learned}

        # R1 — scan dropout mid-leg must not authorise translation.
        rows += _both(
            "R1_scan_dropout",
            EpisodeSpec(
                episode=100, layout=1, goal_id="place_counter",
                start=STARTS[2], directive=directive_for("place_counter"),
                scan_gap=(6.0, 8.0), **base,
            ),
        )
        # R2 — pose DEGRADED near the goal must refuse, not arrive.
        rows += _both(
            "R2_pose_degraded",
            EpisodeSpec(
                episode=101, layout=0, goal_id="place_bowl",
                start=STARTS[1], directive=directive_for("place_bowl"),
                degrade_within_m=1.2, **base,
            ),
        )
        # R3 — an obstacle appears across the committed route.
        rows += _both(
            "R3_moved_obstacle",
            EpisodeSpec(
                episode=102, layout=0, goal_id="place_desk",
                start=STARTS[0], directive=directive_for("place_desk"),
                moved_obstacle_at_s=5.0, **base,
            ),
        )
        # R4b — kidnap into the aliased corridor, three configurations.
        for label, gate, rescue in (
            ("R4b_kidnap_shipped", False, None),
            ("R4b_kidnap_gated", True, None),
            ("R4b_kidnap_gated_operator", True, 12.0),
        ):
            spec = EpisodeSpec(
                episode=103, layout="aliased", goal_id=ALIASED_GOAL_ID,
                start=ALIASED_START, directive=directive_for(ALIASED_GOAL_ID),
                kidnap_at_s=6.0, gate=gate, operator_rescue_at_s=rescue, **base,
            )
            rows += _both(label, spec)

        # R4 — the goal place was never learned; the DOOR must refuse.
        stripped = seed_room_map(omit="place_counter")
        use_learned_map(stripped)
        verdict = door.ask(runtime, PLACES_BY_ID["place_counter"].label)
        rows.append(
            {
                "refuter": "R4_place_absent",
                "arm": "door",
                "seed": seed,
                "door_status": verdict.status,
                "admitted": verdict.admitted,
                "detail": verdict.detail[:200],
                "declared_arrival": False,
                "false_arrival": False,
                "failure_type": "door_refused" if not verdict.admitted else "admitted",
            }
        )
        use_learned_map(learned)
    return rows


def _both(label: str, spec: EpisodeSpec) -> list[dict[str, Any]]:
    out = []
    for cls in (ArmA, ArmB):
        result = cls(spec).run()
        row = result.as_row()
        row["refuter"] = label
        out.append(row)
        print(
            f"  {label:28s} seed {spec.seed} arm {result.arm} "
            f"declared={result.declared_arrival} false={result.false_arrival} "
            f"dist={row['truth_distance_m']} latched={result.latched} "
            f"gap_translate={result.gap_translating_ticks}/{result.gap_ticks}",
            flush=True,
        )
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", default="all", choices=("all", "corpus", "refuters"))
    args = parser.parse_args()
    RESULTS.mkdir(exist_ok=True)
    use_semantic_source(SemanticSourcePolicy(source=SOURCE_LEARNED_MAP))
    scratch = Path(
        "/tmp/claude-1000/-home-jaewoo-jang-Desktop-Projects-Parcel/"
        "0b505906-665b-45ea-a2b7-686b3aecb89d/scratchpad/navcore"
    )
    use_learned_map(seed_room_map())
    runtime = door.build_runtime(scratch)
    policy = _safety_policy()
    environment = {
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "host": platform.node(),
        "python": platform.python_version(),
        "obstacle_stop_m": policy.obstacle_stop_m,
        "obstacle_slow_m": policy.obstacle_slow_m,
        "reaction_time_s": policy.reaction_time_s,
        "planner_inflation_m": policy.planner_inflation_m,
        "gate_demand_at_cruise_m": GATE_DEMAND_M,
        "room_worst_clearance_m": round(min(audit_clearances().values()), 4),
        "alias_scan_max_disagreement_m": alias_scan_agreement(),
    }
    try:
        if args.stage in ("all", "corpus"):
            started = time.perf_counter()
            print("corpus:", flush=True)
            rows = run_corpus(runtime)
            payload = {
                "environment": environment,
                "wall_s": round(time.perf_counter() - started, 1),
                "arms": {arm: _score(rows, arm) for arm in ("A", "B")},
                "rows": rows,
            }
            (RESULTS / "corpus.json").write_text(
                json.dumps(payload, indent=1), encoding="utf-8"
            )
            print(json.dumps(payload["arms"], indent=1))
        if args.stage in ("all", "refuters"):
            print("refuters:", flush=True)
            rows = run_refuters(runtime)
            (RESULTS / "refuters.json").write_text(
                json.dumps({"environment": environment, "rows": rows}, indent=1),
                encoding="utf-8",
            )
    finally:
        runtime.close()
        use_learned_map(None)
        use_semantic_source(None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
