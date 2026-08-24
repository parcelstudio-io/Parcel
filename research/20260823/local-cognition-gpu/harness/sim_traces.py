"""Run the headless city and dump the state the gold-set author reads.

Not a measurement — a source of *real* situations, so the 60 digests in
``gold_set.py`` describe places, objects and nav states this repo's own
simulator actually produces, instead of ones an author imagined.

    .parcel/bin/python research/20260823/local-cognition-gpu/harness/sim_traces.py
"""

from __future__ import annotations

import json
from pathlib import Path

from parcel_robot.simulation.headless_city import HeadlessCityQualityHarness

FOLDER = Path(__file__).resolve().parents[1]
OUT = FOLDER / "results" / "sim_traces.json"

DIRECTIVES = (
    "go to the sidewalk",
    "go to the bench",
    "go to the fountain",
)


def main() -> int:
    harness = HeadlessCityQualityHarness()
    rows: list[dict[str, object]] = []
    for directive in DIRECTIVES:
        result = harness.run(directive, max_steps=600)
        observation = result.final_observation
        rows.append(
            {
                "directive": result.directive,
                "status": result.status,
                "reason": result.reason,
                "target_id": result.target_id,
                "steps": len(result.trace),
                "collisions": result.collision_count,
                "min_clearance_m": round(result.minimum_clearance_m, 3),
                "phases": sorted({sample.phase for sample in result.trace}),
                "notes": sorted({sample.note for sample in result.trace})[:24],
                "regions": sorted({region.region_id for region in observation.semantic_regions}),
                "objects": sorted({obj.object_id for obj in observation.semantic_objects}),
                "owner_visible": observation.owner is not None,
                "lidar_obstacles": len(observation.lidar_obstacles),
                "final_pose": [
                    round(observation.robot.x, 2),
                    round(observation.robot.y, 2),
                    round(observation.robot.yaw, 3),
                ],
            }
        )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(rows, indent=1, sort_keys=True) + "\n")
    print(json.dumps(rows, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
