# Claude Fable independent audit brief — task_7

## Assignment

Audit the navigation/locomotion research and proposed plan in this directory against
the **updated repository**, not against an assumed robotics stack. This is an
independent design review. Do not implement, install, download models, weaken tests, or
rewrite the plan while auditing.

Read, at minimum:

1. `scrum/20260809/task_7/{README,RESEARCH_REPORT,DESIGN_PLAN,SOURCE_LEDGER}.md`;
2. `scrum/20260809/task_2/README.md` and `scrum/20260809/task_4/README.md`;
3. `docs/{CURRENT_STATUS,NAVIGATION_ALGORITHM_2026,
   COMPANION_NAVIGATION_ARCHITECTURE,NAV_GENERALIZATION_AUDIT,MOTION,
   RUNTIME_CONCURRENCY_AND_CLOCKS,HARDWARE_PORTABILITY_AUDIT}.md`;
4. the current implementations under `src/parcel_robot/{runtime,headless_city,sim,
   mujoco_lidar,motion,pose}.py`, `navigation/`, `camera_channel/`, and `control/`;
5. current navigation/terrain eval code and ledgers under `evals/`;
6. every cited upstream primary source whose fact is material to a recommendation.

## Questions that require explicit answers

1. Does the audit of Parcel's live/default path match the code, including which camera,
   semantic, pose, LiDAR, locomotion, RL, and MetaUrban paths are actually wired?
2. Is the split among semantic task planning, terrain navigation, body-command
   locomotion, learned joint control, and final safety technically coherent?
3. Can the proposed interfaces replace Unitree Sport later without letting two writers
   control the body or silently changing units, frames, clock domains, or authority?
4. Is a 2.5-D elevation map plus 3-D occupancy/ESDF sufficient for stairs, slopes,
   negative obstacles, overhangs, multi-floor routing, and uncertainty? Identify the
   cases where it is not.
5. Does the stairs/hills algorithm distinguish *perceiving a traversable route* from
   *having a controller validated to execute it*?
6. Are learned components bounded so an LLM/VLM or policy cannot override freshness,
   collision, stability, stop, arrival, or task-revision authority?
7. Does the teacher/student plan avoid simulator-truth leakage at evaluation and
   deployment? Are train/validation/OOD/cross-sim splits actually disjoint by generator
   and asset family, rather than just seed?
8. Are Isaac Lab, Unitree RL Lab, MuJoCo, Gazebo, MetaUrban/URBAN-SIM, Habitat, and
   iGibson/OmniGibson assigned roles their public implementations can support today?
9. Which dependencies, checkpoints, or claimed features are unavailable, immature,
   non-commercial, GPL-bound, research-only, or otherwise unsuitable for a production
   dependency?
10. Is the proposed work ordered so evaluation, contracts, and untouched baselines land
    before score hill-climbing? Which phases can genuinely run in parallel?
11. Do the metrics distinguish normal foot contact from forbidden body/obstacle/human
    contact, and task completion from merely surviving?
12. Does the plan preserve simple voice commands without allowing voice/audio scope to
    consume the navigation program?
13. Does any claim imply universal collision avoidance, physical safety, or sim-to-real
    validation that the evidence cannot support?
14. Is the audited workstation suitable for the proposed first phase, given one RTX
    5000 Ada (32 GB), current driver, no `nvcc`, no Isaac install, and system Python
    3.14? Is the isolated-environment recommendation sufficient?

## Required red-team scenarios

Trace each scenario from sensor packet to final actuator command and identify the exact
component that must hold, slow, reroute, recover, or declare unsupported:

- stair descent when the landing is occluded;
- false positive “floor” beyond a glass edge or drop-off;
- cross-slope with low friction and increasing lateral slip;
- camera darkness plus stale/replayed LiDAR;
- 3-D LiDAR dropout while moving backward into the current rear blind region;
- camera–LiDAR extrinsic jump and timestamp skew;
- localization drift at a floor transition (`map -> odom` discontinuity);
- a low overhang clear in the elevation layer but not for the robot body/sensor mast;
- a moving person emerging from occlusion while the learned policy accelerates;
- learned controller inference timeout or NaN halfway down stairs;
- simulator-only semantic/truth fields accidentally entering the student observation;
- vendor controller capability exceeded by a route labeled “stairs”; and
- two control writers (Sport and learned joint process) becoming active concurrently.

## Required source audit

For every row in `SOURCE_LEDGER.md` that materially affects selection:

- open the primary/official source;
- verify the feature exists in the cited version or current branch;
- distinguish source code, released checkpoint, paper-only claim, and future/TODO;
- verify code and weight/data licenses separately;
- flag robot-specific assumptions (ANYmal/Barkour/Jackal/H1 versus Unitree Go2);
- flag ROS 1, Python/CUDA/Isaac version, and hardware constraints;
- replace any unstable numerical claim with a pinned version/commit or delete it.

Do not accept repository popularity, a demo video, or a paper success number as proof
that a production-ready Go2 artifact exists.

## Output contract

Create `scrum/20260809/task_7/CLAUDE_FABLE_REVIEW.md` with:

```text
# Claude Fable review — task_7
Verdict: APPROVE | REVISE | REJECT
Reviewed repository SHA: ...
Reviewed dirty-worktree summary: ...
Reviewed source date/versions: ...

## Executive finding
## Blocking corrections (P0)
## Important corrections (P1)
## Source and license corrections
## Architecture/interface review
## Safety and truth-leak red team
## Evaluation sensitivity and missing scenarios
## Feasibility/compute review
## Parallelization/dependency review
## Recommended exact edits
## What is approved to dispatch
```

Every finding must include either a current code/file reference or a direct primary
source URL. Clearly label inference. Record pre-existing worktree changes so the audit
does not attribute concurrent task_4 camera-foundation, task_6 conversation/eval, or
other dirty-worktree edits to task_7.

`APPROVE` means the P0 cards can be dispatched without an architectural rewrite;
non-blocking P1 corrections may remain. `REVISE` means exact plan corrections are
required first. `REJECT` means the proposed system boundary or simulator/training
strategy is unsound. Do not approve merely because the prose is comprehensive.
