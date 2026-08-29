# Sim-plan-2 design

## Question and evidence boundary

Does the additive `AffordancePlannerV2` goal-relevance proof eliminate the
three frozen `SIM-PLAN-1` false `needs_observation` dispositions without
regressing symbolic plan validity, hard-safety/admission checks, deterministic
ordering, exact input binding, or proposal-only authority?

This is **authored symbolic regression/shadow evidence only**. The 29-mission
matrix was held out for `SIM-PLAN-1`, but its three errors directly informed
V2, so it is a regression set here, not a fresh held-out generalization set.
There is no physics, perception, language grounding, learned locomotion,
authenticated commissioning, ROS 2, Unitree hardware, or motion gateway.

## Frozen inputs

- The experiment reads, but never copies or modifies,
  `../sim-plan-1/fixtures.json`.
- `observability.json` adds one frozen V2 input: a bounded set of readiness,
  clearance, and consent facts that an external observation receipt could
  resolve. Derived semantic state such as `owner.visible` and
  `robot.near_owner` is deliberately not directly observable; it must be
  produced by an admitted grounded skill.
- V2 runs each mission under the same canonical, reverse, and deterministic
  rotation orders used in `SIM-PLAN-1`.
- The existing shadow interpreter checks only authored preconditions,
  predicted effects, goals, forbidden/preserved facts, reliability
  suppression, and commissioned-skill admission. It never executes a skill.

## Pre-registered gates

These gates were written before the canonical `SIM-PLAN-2` experiment run.

- **H1 — disposition repair:** exact disposition accuracy is 29/29, every
  authored critical unknown is reported, and `greet-camera-false`,
  `greet-scan-uncommissioned`, and `follow-consent-false` all return
  `unreachable` with no uncertain facts.
- **H2 — no symbolic regression:** all 18 authored-solvable missions retain a
  valid goal plan and the V2 proposals create zero hard-safety or admission
  violations in the shadow interpreter.
- **H3 — boundary integrity:** all 87 proposals are invariant to operator
  order, bind the exact state, V2 problem, shadow-manifest, reliability, and
  observable-fact digests, and always have `authorizes_motion=false`.

`SUPPORTED_REGRESSION_SHADOW` means only that every frozen gate passed. It is
not independent evidence of generalized planning and grants no promotion or
motion authority.

## Reproduction

```bash
.parcel/bin/python research/20260828/sim-plan-2/experiment.py \
  --out research/20260828/sim-plan-2/results-run1.json
.parcel/bin/python research/20260828/sim-plan-2/experiment.py \
  --out research/20260828/sim-plan-2/results-run2.json
.parcel/bin/python research/20260828/sim-plan-2/verify_results.py \
  --write-canonical
```
