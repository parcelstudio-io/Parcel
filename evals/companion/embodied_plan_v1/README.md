# Embodied PlanIR execution gate v1

This gate starts where `planner_quality_v2` stops. It takes the exact admitted
plans from the frozen Gemma run, validates them again, submits them through
`TaskExecutive`, dispatches them through `SemanticTaskRuntimeAdapter`, and
executes controller commands in `HeadlessCityWorld`.

The policy boundary receives camera semantic tracks, LiDAR, the camera-derived
owner track, and robot odometry. Simulator polygons, object centers, collision
geometry, winding, and clearance are evaluator-only truth and are read only
after controller execution. Base integration is deterministic kinematics in
MuJoCo geometry; this is not Unitree contact-physics or hardware evidence.

The immutable episode seeds and start poses live in `episodes.json`. The
manifest pins that file, the city scene, robot/controller configuration, the
frozen planner cases, the admitted-plan result, and the result schema by
SHA-256. The runner refuses changed inputs and refuses to overwrite results.

Scored outcomes are:

- sidewalk terminal interior and off-road support;
- lamppost surface distance at most 1 m while remaining on sidewalk;
- five 0.25 m owner-relative steps, with bounded distance error;
- orbit winding, angular coverage, radial corridor, endpoint closure, and
  collision/clearance;
- task correction deferred and activated at a reported checkpoint;
- collisions, minimum clearance, timeouts, terminal stop, and simulator steps.

`FollowFormation` is deliberately unsupported in this fixed-owner headless
world. The orbit prefix is physically executed and scored, but the compound
case is marked `unsupported`; it cannot contribute a fake pass. A future v2
needs a moving-owner camera-track episode and the production formation
controller.

Run the frozen accepted plans:

```bash
.parcel/bin/python evals/companion/run_embodied_plan_v1.py \
  --output evals/companion/embodied_plan_v1/results/embodied-plan-v1-<run>.json \
  --description "Describe the controller or planner change"
```

Exit status is nonzero only for supported-case failures. Unsupported cases are
reported separately.

Immutable runs are indexed in the [result ledger](results/README.md).
