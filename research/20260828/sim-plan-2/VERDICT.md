# Sim-plan-2 replay and product-path verdict

**Regression hypothesis:** `CONFIRMED` at authored-symbolic shadow tier  
**Generalized planning:** `INCONCLUSIVE`  
**Generalized movement / physical motion:** `NO-GO`

## Replay

`results-run1.json` and `results-run2.json` are JSON-identical and share
deterministic payload SHA-256
`29a345e8dea589b5a45f408f03d00021b2392d5004903b755bfe198d523c0007`.
The verifier recomputed the payload and all source hashes, checked the exact
29/18/11 mission split, checked all three named regressions, compared the
canonical artifact, and performed a fresh replay. All 12/12 checks passed.

The replay confirms the implementation and frozen-regression claim, not the
authored oracle. Both runs use the same V1 fixture, authored V2 observability
boundary, and symbolic shadow interpreter. Because those V1 failures guided
the V2 design, the 100% disposition result must not be described as fresh
held-out performance.

## Product-path check

`AffordancePlannerV2`, `PlanningProblemV2`, and `PlanProposalV2` live in product
source, but repository search finds no runtime, executive, navigation, or
motion-pipeline caller. Current consumers are the focused tests and this
research harness. V2 is therefore harness-only and proposal-only. Its contract
rejects motion authorization, and its problem/proposal digests bind the exact
externally-observable fact boundary in addition to the V1 state, operator,
commissioning, reliability, safety, and budget inputs.

## Decision

Keep V2 as the candidate for a future proposal-only runtime shadow lane; do
not replace the live planner or grant execution authority from this result.
The next evidence step is a newly generated procedural matrix that was not
used to design V2, with noisy/stale observation receipts, dynamic fact changes,
outcome-driven replanning, and adversarial commissioning/safety cases. After
that, evaluate planning over physics-backed Go2 skills whose success/failure
comes from simulator receipts rather than authored effects. Physical motion
remains `NO-GO` until the separate locomotion, terrain, gateway, and hardware
promotion gates pass.
