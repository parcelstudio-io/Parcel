# Sim-plan-1 independent verdict

**Overall verdict:** `INCONCLUSIVE` for generalized robot planning  
**Narrow composition hypothesis:** `CONFIRMED` at authored-symbolic shadow tier  
**Exact disposition hypothesis:** `REFUTED`  
**Proposal-boundary hypothesis:** `CONFIRMED` at authored-symbolic shadow tier

## Independent replay

The experiment was launched in two separate processes. `results-run1.json`
and `results-run2.json` are JSON-identical and share deterministic payload
SHA-256
`41842b1ee713cd6032923ee7a2db8afce3563e8e2212962d4c0c5eb5cdd52073`.
The verifier then recomputed both digests, checked source and fixture hashes,
compared the canonical copy, and performed a fresh in-process replay. All
12/12 verification checks passed.

This replay is independent at the process and integrity-check level, not at
the oracle level: both runs use the same authored fixture and shadow
interpreter. It therefore catches nondeterminism or artifact drift, not shared
modeling errors.

Headline re-measurement:

- planner valid solves: 18/18;
- fixed-template valid solves: 5/18;
- planner exact dispositions: 26/29;
- fixed-template exact dispositions: 5/29;
- planner-created shadow safety/admission violations: 0/0;
- fixed-template shadow safety/admission violations: 4/2.

The three planner disposition errors exactly match the recorded rows:
`greet-camera-false`, `greet-scan-uncommissioned`, and
`follow-consent-false`. All returned `needs_observation` where the authored
oracle required `unreachable`, so the frozen 90% disposition gate remains
missed at 89.6552%.

## Product-path check

`AffordancePlannerV1` lives in product source under
`src/parcel_robot/brain/affordance_planner.py`, and its reliability DTO is
compatible with `src/parcel_robot/learning_loop/skill_outcomes.py`. However,
repository search finds no runtime, executive, or navigation-pipeline caller.
Current consumers are tests and this research harness. The evaluated path is
therefore **harness-only**, defaults to no action, and cannot dispatch motion.

## Decision

Keep the bounded planner as a candidate for shadow integration because the
composition result is repeatable and materially exceeds this frozen baseline.
Do not claim generalized intelligence or promote it to robot control. First
fix goal-relevant uncertainty attribution and freeze the three misses as
regressions; then wire proposal-only runtime shadow logging and evaluate on
procedural scenes with perception noise, outcome-driven replanning, and a
stronger learned or search baseline. Physics, hardware, and sim-to-real
evidence remain absent.

