# Task 3 — R14: a world with a door

**Executor:** Claude Opus (agent) · **Auditor:** Fable
**Trigger:** E1 `door-etiquette` FAIL: no shipped scene contains a portal, so
R10's door arrival semantics (near, do-not-cross, face owner, ask-next) have
never executed end to end.

## Work
1. Add a doorway to the city scene: MJCF geometry + a `portal`-class entry in
   the scene semantics sidecar, positioned reachably (not inside pedestrian
   keepout churn).
2. This touches PACKAGED, digest-pinned assets — follow the full
   regeneration discipline: `tools/sync_runtime_assets.py --write`, sentinel
   manifests regenerated per their own documented procedure, release-parity
   green afterward. A hand-edited pin is an audit failure.
3. Re-run the E1 door-etiquette scenario harness against the new world and
   append the result to `evals/20260819/run_1/scenario_door-etiquette/` as a
   dated ADDENDUM (the original FAIL row stays — history is not retconned).
   Expected: near + no-cross + face-owner + the model ASKS what's next.

OWNS: scene MJCF + semantics sidecar, regenerated manifests via the sync
tool, the E1 addendum, tests (portal-class arrival now exercisable in the
default suite — add the offline pins R10 could not run), `R14_STATUS.md`.
MUST NOT TOUCH: navigation source (R10's code is presumed correct until the
world proves otherwise — a code defect found here is REPORTED, not patched),
`realtime/*`, yield policy. DoD: gate green incl. sentinels/parity; ≥4 seeds
RED (portal class removed from sidecar; door crossed; face-goal regression;
ask-hint dropped); live door proof with transcript + path; standard register.
