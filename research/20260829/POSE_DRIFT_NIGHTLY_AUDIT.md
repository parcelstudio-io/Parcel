# Pose-drift nightly floor audit — 2026-08-30

## Verdict

The extended-nightly `pose-drift-arms:floors` failure is a legitimate
navigation behavior regression with a stale feasibility assumption in the
benchmark. It is not a scoring-version mismatch or a flake. Keep the nightly
row hard red; do not move the floors or revert the commissioned safety envelope.

## Evidence

Current and frozen runs use the same 61-cell `v4d` substrate, candidate mode,
`scaled-path-v1`, 200-step base budget, and `nav-instruct-v1.1-k0-arrival`
runner. The frozen Stage A and B arm payloads are byte-identical after deleting
wall-clock `elapsed_s`; each floor remains Stage-A SR minus exactly 1/61.

The last recorded green nightly on 2026-08-21 measured truth/calibrated/
aggressive/degraded/calibrated-lost/degraded-lost/reanchoring SR of
0.180/0.148/0.098/0.033/0.115/0.049/0.082. The current run measured
0.115/0.016/0.033/0.016/0.016/0.016/0.016, with zero collisions and false
arrivals and all 147 banded episodes in their intended drift bands. Current
success counts are 7/61 truth and 1/2/1/1/1/1 for the six drift arms; the
frozen drift-arm count floors are 8/5/2/6/2/3.

## Causal reproduction

The strongest causal change is the August 24 A2 commissioning of the pipeline
planner from the legacy 0.42 m inflation to approximately 1.0222956 m derived
from the collision brake. A2's own status record notes the unresolved mismatch:
the reactive gate is directional, while grid inflation makes the same clearance
isotropically non-traversable.

On frozen-success cell `nav-drift-object_goal-00-1d1e67a2`, current truth and
calibrated arms both fail `semantic_target_unreachable`. Truth advances only
about 0.8 m before `grid_recover_scan status=goal_blocked|clear`, with the goal
still about 10.1 m away, and later releases the semantic target. A read-only
in-process counterfactual restoring the legacy planner construction—without
changing current scoring or arrival code—restores success for both arms.

The exact-cell-arrival repair is not the reproduced cause. The current failure
returns `goal_blocked` when the ray-clipped window has no traversable candidate,
before the exact-arrival branch. The planner does not try a lateral reachable
frontier at that point. Separately, the local planner consumes ODOM pose while
comparing it with a MAP-frame mission goal without an explicit MAP→ODOM
transform; this plausibly amplifies drift-arm losses.

## Required repair and evaluation order

1. Preserve hard inflation, but choose a reachable observed/window frontier
   toward the global goal when the clipped ray target is blocked.
2. Add direction-aware clearance (or an equivalent non-isotropic constraint)
   that cannot propose motion the brake rejects without banning safe lateral
   corridors.
3. Transform the mission goal explicitly from MAP to ODOM for the local planner.
4. Reconcile generated-cell feasibility with the commissioned robot-clearance
   contract while preserving the frozen artifact.
5. First test the named counterexample plus one object-relative cell across
   truth/calibrated/degraded profiles, with zero collision and false arrival.
   Then run truth and calibrated 61-cell arms once; only then rerun all 7×61.

Controlling code and evidence:

- [`evals/nav_instruct/run_drift_arms.py`](../../evals/nav_instruct/run_drift_arms.py)
- [`evals/nav_instruct/results/drift-arms-stage-a-20260812T061640Z.json`](../../evals/nav_instruct/results/drift-arms-stage-a-20260812T061640Z.json)
- [`evals/nav_instruct/results/drift-arms-stage-b-20260812T064743Z.json`](../../evals/nav_instruct/results/drift-arms-stage-b-20260812T064743Z.json)
- [`src/parcel_robot/navigation/grid_planner.py`](../../src/parcel_robot/navigation/grid_planner.py)
- [`src/parcel_robot/navigation/grid_navigator.py`](../../src/parcel_robot/navigation/grid_navigator.py)
- [`scrum/20260824/task_2/A2_STATUS.md`](../../scrum/20260824/task_2/A2_STATUS.md)
