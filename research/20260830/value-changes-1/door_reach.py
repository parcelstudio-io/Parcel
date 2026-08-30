"""W6 diagnostic — is the release door ever REACHED on the frozen corpora?

"The digest did not move" is two different findings depending on whether the
door fired and changed nothing, or was never armed at all.  This counts, over
the v4 minival's 25 episodes and the mutation panel's 5 clean episodes, with the
door ON:

  * ``watchdog_window_reached``  — the progress watchdog's 200-tick window
    expired with a semantic goal and replan budget left (the branch the door
    lives in);
  * ``door_consulted``           — ``stall_attribution.held_release_due`` calls;
  * ``door_released``            — calls that returned True (a release fired).

Harness-only: the counter wraps the leaf function in this process; nothing is
edited.  Run per arm with the arm's config tree, like ``values_harness.py``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

os.environ["OPENBLAS_NUM_THREADS"] = "1"
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from values_harness import ARM_BY_NAME, SCRATCH, build_arm_config, repo_root


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", required=True)
    a = ap.parse_args()
    arm = ARM_BY_NAME[a.arm]
    cfg = build_arm_config(arm)
    repo = repo_root()
    if str(repo) not in sys.path:
        sys.path.insert(0, str(repo))

    from parcel_robot.navigation import stall_attribution as stall
    from parcel_robot.simulation import headless_city

    if not arm.commissioned:
        headless_city._navigation_config_from_store = lambda _s, _p=cfg: _p

    counts = {"door_consulted": 0, "door_released": 0, "door_consulted_enabled": 0}
    original = stall.held_release_due

    def counting(metadata, route_status, body_is_still, *, enabled):
        counts["door_consulted"] += 1
        if enabled:
            counts["door_consulted_enabled"] += 1
        out = original(metadata, route_status, body_is_still, enabled=enabled)
        if out:
            counts["door_released"] += 1
        return out

    stall.held_release_due = counting

    from evals.nav_instruct.generator import EPISODE_SET_V4, generate_minival
    from evals.nav_instruct.runner import ARRIVAL_RULE_FOR_VERSION, NavInstructRunner

    runner = NavInstructRunner(
        max_steps=200, mode="baseline", arrival_rule=ARRIVAL_RULE_FOR_VERSION[EPISODE_SET_V4]
    )
    assert str(runner.harness.navigation_config) == str(cfg), "patch missed"
    nav = __import__(
        "parcel_robot.navigation.pipeline", fromlist=["DirectiveNavigator"]
    ).DirectiveNavigator.from_config(cfg)
    facts = {
        "held_stall_release": bool(nav.held_stall_release),
        "progress_timeout_steps": int(nav.progress_timeout_steps),
        "max_semantic_replans": int(nav.max_semantic_replans),
        "planner_inflation_radius_m": round(
            float(nav._navigator._planner.config.inflation_radius_m), 6
        ),
    }
    nav.close()

    episodes = list(generate_minival(version=EPISODE_SET_V4))
    per_ep = []
    for ep in episodes:
        before = dict(counts)
        runner.run_episode(ep)
        per_ep.append(
            {
                "episode_id": ep.episode_id,
                "door_consulted": counts["door_consulted"] - before["door_consulted"],
                "door_released": counts["door_released"] - before["door_released"],
            }
        )

    out = {
        "arm": arm.name,
        "config": str(cfg),
        "facts": facts,
        "corpus": "v4 minival, 25 episodes, max_steps 200",
        "totals": counts,
        "episodes_where_the_door_was_consulted": [
            e["episode_id"] for e in per_ep if e["door_consulted"]
        ],
        "episodes_where_the_door_released": [
            e["episode_id"] for e in per_ep if e["door_released"]
        ],
    }
    dest = SCRATCH / "door_reach"
    dest.mkdir(parents=True, exist_ok=True)
    (dest / f"{arm.name}.json").write_text(json.dumps(out, indent=2))
    print(json.dumps({k: v for k, v in out.items() if k != "facts"}))


if __name__ == "__main__":
    main()
