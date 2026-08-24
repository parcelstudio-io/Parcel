"""Why the stalls stall: re-run the silent stalls and record the final geometry.

Both arms lose most of their episodes to ``silent_stall_step_limit``.  This
re-runs a sample of them and records, at the tick the body stopped moving, the
clearance the scan reported and the forward speed the controller was still
asking for.  If the gate's demand at that speed
(``obstacle_stop_m + vx * reaction_time_s``) exceeds the clearance on every
one, the stall is the planner and the gate disagreeing about the same corridor
rather than anything to do with semantics — which is the claim RESULTS makes.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from arms import ArmA, ArmB, EpisodeSpec, _safety_policy
from room import LAYOUTS, PLACES, STARTS
from world_map import seed_room_map

from parcel_robot.perception_source.selection import (
    SOURCE_LEARNED_MAP,
    SemanticSourcePolicy,
    use_learned_map,
    use_semantic_source,
)

SAMPLE = 8


def main() -> int:
    corpus = json.loads((HERE / "results" / "corpus.json").read_text(encoding="utf-8"))
    policy = _safety_policy()
    use_semantic_source(SemanticSourcePolicy(source=SOURCE_LEARNED_MAP))
    learned = seed_room_map()
    use_learned_map(learned)
    stalled = [
        row
        for row in corpus["rows"]
        if row["failure_type"] == "silent_stall_step_limit" and row["seed"] == 101
    ][:SAMPLE]
    out: list[dict[str, Any]] = []
    try:
        for row in stalled:
            episode = int(row["episode"])
            place = PLACES[episode % len(PLACES)]
            spec = EpisodeSpec(
                episode=episode,
                seed_index=0,
                seed=101,
                layout=episode % len(LAYOUTS),
                goal_id=place.place_id,
                start=STARTS[episode % len(STARTS)],
                directive=f"go to the {place.label}",
                learned_map=learned,
            )
            runner = (ArmA if row["arm"] == "A" else ArmB)(spec)
            original = runner.command
            last: dict[str, Any] = {}

            def probe(observation: Any, t_s: float, _original: Any = original,
                      _last: dict[str, Any] = last) -> Any:
                command, declared, note = _original(observation, t_s)
                _last.update(
                    requested_vx=command.vx,
                    scan_clearance_m=observation.nearest_obstacle_m,
                    note=note,
                )
                return command, declared, note

            runner.command = probe
            runner.run()
            demand = policy.obstacle_stop_m + float(
                last.get("requested_vx") or 0.0
            ) * policy.reaction_time_s
            clearance = last.get("scan_clearance_m")
            out.append(
                {
                    "arm": row["arm"],
                    "episode": episode,
                    "goal_id": place.place_id,
                    "final_xy": [round(runner.body.x, 3), round(runner.body.y, 3)],
                    "truth_clearance_m": round(
                        runner.world.clearance_m(runner.body.x, runner.body.y), 3
                    ),
                    "scan_clearance_m": None if clearance is None else round(clearance, 3),
                    "requested_vx_mps": round(float(last.get("requested_vx") or 0.0), 3),
                    "gate_demand_m": round(demand, 3),
                    "gate_stops": clearance is not None and demand >= clearance,
                    "note": str(last.get("note"))[:80],
                }
            )
            print(out[-1], flush=True)
    finally:
        use_learned_map(None)
        use_semantic_source(None)
    # Three independent clearance authorities, none of which the planner reads:
    #   planner inflation      0.42 m  (footprint 0.32 + map_safety_margin 0.10)
    #   pipeline collision brake 0.80 m (configs/navigation/default.yaml
    #                                    safety.stop_distance_m)
    #   reactive gate          0.752 m (obstacle_stop_m 0.65 + 0.85 * 0.12)
    pipeline_brake_m = 0.80
    inside = [
        row
        for row in out
        if row["scan_clearance_m"] is not None
        and (row["gate_stops"] or row["scan_clearance_m"] <= pipeline_brake_m)
    ]
    payload = {
        "obstacle_stop_m": policy.obstacle_stop_m,
        "reaction_time_s": policy.reaction_time_s,
        "grid_v1_cruise_vx_mps": 0.85,
        "planner_inflation_m_shipped": 0.42,
        "pipeline_collision_brake_m": pipeline_brake_m,
        "gate_stops_fraction": (
            sum(row["gate_stops"] for row in out) / len(out) if out else 0.0
        ),
        "stalled_inside_a_brake_ring_fraction": len(inside) / len(out) if out else 0.0,
        "rows": out,
    }
    (HERE / "results" / "stall_mechanism.json").write_text(
        json.dumps(payload, indent=1), encoding="utf-8"
    )
    print("stalled_inside_a_brake_ring", payload["stalled_inside_a_brake_ring_fraction"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
