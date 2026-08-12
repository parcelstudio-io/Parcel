# ruff: noqa - archived verbatim from FOLLOWUP_DESIGNS.md Appendix A (card Y-4). This
# file is a session-scratch diagnostic, not repo code: it is kept exactly as it
# was run, so its import style is not the repo's to fix. Everything below this
# banner is byte-identical to the archived original.
"""Step-trace pedestrian_group on the scratch tree (diagnostic, no ledger write)."""
import sys, math, json
from collections import Counter

sys.path.insert(0, "/tmp/claude-1000/-home-jaewoo-jang-Desktop-Projects/10414eee-ec95-484f-80ab-02978d7e3f5b/scratchpad/tree")
sys.path.insert(0, "/tmp/claude-1000/-home-jaewoo-jang-Desktop-Projects/10414eee-ec95-484f-80ab-02978d7e3f5b/scratchpad/tree/src")

from evals.companion_nav.runner import FollowBenchRunner
from evals.companion_nav.scenarios import FOLLOW_BENCH_V1
from evals.companion_nav import metrics as M

scenario = next(s for s in FOLLOW_BENCH_V1 if s.scenario_id == "pedestrian_group")
runner = FollowBenchRunner("/tmp/claude-1000/-home-jaewoo-jang-Desktop-Projects/10414eee-ec95-484f-80ab-02978d7e3f5b/scratchpad/tree/configs/robot.yaml")
result = runner.run(scenario)

steps = result.steps
band = [s for s in steps if 1.2 <= s.owner_distance_m <= 3.0]
print("steps:", len(steps), "band_fraction:", round(len(band)/len(steps), 4))

# where the band fails: above or below
above = sum(1 for s in steps if s.owner_distance_m > 3.0)
below = sum(1 for s in steps if s.owner_distance_m < 1.2)
print("above_band:", above, "below_band:", below, "max_dist:", round(max(s.owner_distance_m for s in steps), 3))

print("proximity_state counts:", Counter(s.proximity_state for s in steps))
print("reactive_state counts:", Counter(s.reactive_proximity_state for s in steps))
print("controller state counts:", Counter(s.state for s in steps))

# sample trace every 10 steps
print(f"{'t':>5} {'rx':>6} {'ry':>6} {'own_d':>6} {'vx':>6} {'pedsurf':>7} prox/react state note")
for i, s in enumerate(steps):
    if i % 10 == 0 or (s.proximity_state != "clear" and i % 3 == 0):
        note = s.note.split("|")[0][:40]
        print(f"{s.time_s:5.1f} {s.robot_x:6.2f} {s.robot_y:6.2f} {s.owner_distance_m:6.2f} {s.command_vx:6.3f} "
              f"{(s.nearest_pedestrian_surface_m if s.nearest_pedestrian_surface_m is not None else -1):7.3f} "
              f"{s.proximity_state}/{s.reactive_proximity_state} {s.state} {note}")

# throttle attribution: fraction of steps slowed/stopped while behind
slowed = [s for s in steps if s.proximity_state in ("slowing", "stopped")]
print("slowed_or_stopped steps:", len(slowed), "of", len(steps))
print("min ped surface:", round(min(s.nearest_pedestrian_surface_m for s in steps if s.nearest_pedestrian_surface_m is not None), 4))
