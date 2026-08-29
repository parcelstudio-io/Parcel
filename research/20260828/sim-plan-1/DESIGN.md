# Sim-plan-1 design

## Question and evidence boundary

Does `AffordancePlannerV1` compose system-authored semantic skills on held-out
symbolic missions better than a fixed-template plan selector, while preserving
hard constraints and proposal-only authority boundaries?

This is **authored symbolic/shadow evidence only**. It does not exercise a
physics simulator, perception, learned locomotion, language grounding, an
authenticated capability manifest, ROS 2, Unitree hardware, or a motion
gateway. A valid symbolic plan is not evidence that a Go2 can execute it.

## Frozen comparison

`fixtures.json` contains five development templates and 29 evaluation missions.
The fixed-template baseline retrieves one unchanged development sequence by
mission family. It performs no search, replanning, uncertainty classification,
or constraint-conditioned adaptation.

The evaluation missions are not template records. They include:

- unchanged-skill but held-out nominal contexts;
- new multi-goal compositions;
- partial-progress states requiring skipped steps;
- hard distance and stability constraints;
- frozen safety-history and commissioned-skill restrictions;
- unknown prerequisites, contradicted prerequisites, and an initially unsafe
  state.

The planner receives exactly the same authored facts and operators as the
baseline evaluator. Each planner mission is evaluated three times with
canonical, reverse, and deterministic-rotation operator orders. The shadow
interpreter independently checks preconditions, predicted effects, goals,
hard-forbidden facts, preserved facts, reliability suppression, and the skill
allowlist. It never invokes a skill.

The `capability_manifest_digest` is explicitly a digest of an authored shadow
skill set, not an authenticated commissioning artifact. It exists to test
input binding only.

## Preregistered gates

The gates are encoded in `experiment.py` and were not weakened after observing
the outputs.

- **H1 — composition:** planner solve rate on solvable missions is at least
  90%, at least 40 percentage points above the template baseline, with zero
  planner-created hard-safety or admission violations.
- **H2 — disposition:** exact `planned` / `needs_observation` / `unreachable` /
  `unsafe_state` accuracy is at least 90%, at least 50 percentage points above
  baseline, and every authored critical unknown is reported.
- **H3 — boundary integrity:** proposals are invariant to operator input order,
  bind the exact world/problem, shadow-manifest and reliability digests, and
  never authorize motion.

`SUPPORTED_SHADOW` means only that every gate for that hypothesis passed in
this authored symbolic matrix. It is not a promotion or hardware-readiness
decision.

## Reproduction

```bash
.parcel/bin/python research/20260828/sim-plan-1/experiment.py \
  --out research/20260828/sim-plan-1/results-run1.json
.parcel/bin/python research/20260828/sim-plan-1/experiment.py \
  --out research/20260828/sim-plan-1/results-run2.json
.parcel/bin/python research/20260828/sim-plan-1/verify_results.py \
  --write-canonical
```

