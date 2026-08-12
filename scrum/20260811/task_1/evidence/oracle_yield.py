# ruff: noqa - archived verbatim from FOLLOWUP_DESIGNS.md Appendix A (card Y-4). This
# file is a session-scratch diagnostic, not repo code: it is kept exactly as it
# was run, so its import style is not the repo's to fix. Everything below this
# banner is byte-identical to the archived original.
"""Oracle upper-bound for a lateral yield-aside on pedestrian_group (+ cut_in).

Emulates "the follow controller aims at a laterally shifted lane" by giving
follow.step() an observation whose OWNER point is shifted perpendicular to the
owner's travel direction; the dispatch gate, TTC, metrics, and the world all
see the TRUE observation. Diagnostic only, scratch tree only.
"""
import sys, math
from dataclasses import replace
from collections import Counter

sys.path.insert(0, "/tmp/claude-1000/-home-jaewoo-jang-Desktop-Projects/10414eee-ec95-484f-80ab-02978d7e3f5b/scratchpad/tree")
sys.path.insert(0, "/tmp/claude-1000/-home-jaewoo-jang-Desktop-Projects/10414eee-ec95-484f-80ab-02978d7e3f5b/scratchpad/tree/src")

import evals.companion_nav.runner as R
from evals.companion_nav.scenarios import FOLLOW_BENCH_V1

SHIFT = 0.0  # set per cell

_orig_step = None

def install(shift_y: float):
    import parcel_robot.navigation.follow as F
    global _orig_step
    if _orig_step is None:
        _orig_step = F.FollowOwnerController.step
    def shifted_step(self, observation, now=None, *, prediction=None):
        if observation is not None and shift_y != 0.0:
            owner = observation.owner
            observation = replace(observation, owner=replace(owner, y=owner.y + shift_y))
        return _orig_step(self, observation, now=now, prediction=prediction)
    F.FollowOwnerController.step = shifted_step

def restore():
    import parcel_robot.navigation.follow as F
    if _orig_step is not None:
        F.FollowOwnerController.step = _orig_step

def run_cell(scenario_id: str, shift_y: float):
    install(shift_y)
    try:
        scenario = next(s for s in FOLLOW_BENCH_V1 if s.scenario_id == scenario_id)
        runner = R.FollowBenchRunner("/tmp/claude-1000/-home-jaewoo-jang-Desktop-Projects/10414eee-ec95-484f-80ab-02978d7e3f5b/scratchpad/tree/configs/robot.yaml")
        result = runner.run(scenario)
        steps = result.steps
        n = len(steps)
        band = sum(1 for s in steps if 1.2 <= s.owner_distance_m <= 3.0) / n
        surfaces = [s.nearest_pedestrian_surface_m for s in steps if s.nearest_pedestrian_surface_m is not None]
        minsurf = min(surfaces) if surfaces else None
        dwell = sum(1 for v in surfaces if v < 1.2) * 0.1
        intimate = sum(1 for v in surfaces if v < 0.45) * 0.1
        stopped = sum(1 for s in steps if s.proximity_state == "stopped")
        coll = steps[-1].cumulative_static_collisions
        print(f"{scenario_id:24s} shift={shift_y:+.2f}  band={band:.4f}  min_surf={minsurf if minsurf is None else round(minsurf,4)}  dwell={dwell:.1f}s  intimate={intimate:.1f}s  gate_stops={stopped}  static_coll={coll}")
    finally:
        restore()

for shift in (0.0, 0.2, 0.4, 0.6, -0.3):
    run_cell("pedestrian_group", shift)
for shift in (0.0, 0.4, -0.4):
    run_cell("pedestrian_cut_in", shift)
