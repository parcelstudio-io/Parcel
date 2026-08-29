# Sim-plan-1 results

**Overall:** `PARTIALLY_SUPPORTED_SHADOW`  
**Evidence:** authored symbolic shadow evaluation; no physics, hardware, or
motion  
**Matrix:** 29 held-out missions, 87 planner evaluations, 29 fixed-template
evaluations  
**Deterministic payload:**
`41842b1ee713cd6032923ee7a2db8afce3563e8e2212962d4c0c5eb5cdd52073`

Two independent runs were JSON-identical. The verifier passed 12/12 integrity
checks and a fresh in-process replay matched the canonical result.

## Outcomes

| Metric | Affordance planner | Fixed template | Delta |
|---|---:|---:|---:|
| Valid solve rate, 18 solvable missions | 100.00% | 27.78% | +72.22 pp |
| Exact disposition accuracy, all 29 | 89.66% | 17.24% | +72.41 pp |
| Shadow hard-safety proposal violations | 0 | 4 | — |
| Shadow admission proposal violations | 0 | 2 | — |

- **H1 `SUPPORTED_SHADOW` (4/4 gates):** all 18 solvable missions produced a
  valid goal-reaching composition with no planner-created hard-safety or
  admission violation.
- **H2 `REFUTED` (2/3 gates):** 89.6552% exact disposition accuracy missed the
  frozen 90% gate. The improvement and critical-unknown gates passed.
- **H3 `SUPPORTED_SHADOW` (3/3 gates):** all 87 planner evaluations were bound
  to their exact inputs, invariant across the three operator orders, and
  `authorizes_motion` was always false.

## Failure finding

Three logically unreachable missions returned `needs_observation`:

- `greet-camera-false`;
- `greet-scan-uncommissioned`;
- `follow-consent-false`.

In each case, a prerequisite was already contradicted or its producer was not
commissioned, but the search accumulated unknown facts from downstream
operators (`owner.visible` or `robot.near_owner`). The result is conservative
and non-authoritative, but its diagnosis is too broad: collecting that
observation cannot repair the blocked causal chain.

The immediate planner improvement is a backward relevance/reachability pass
for uncertainty attribution. Report `needs_observation` only when confirming a
fact could make a goal-supporting admitted chain applicable; otherwise return
`unreachable`. Freeze these three fixtures as regressions before changing the
algorithm.

## Interpretation limits

This supports retaining bounded symbolic composition as an executive-planning
candidate. It does **not** demonstrate generalized movement, learned
affordances, world-model accuracy, language understanding, recovery under
dynamics, sim-to-real transfer, stair locomotion, or safe physical execution.
All facts, operators, costs, goals, and expected dispositions were authored.
The baseline is intentionally small and fixed, so its poor score is not a
comparison against a learned task planner or current robotics foundation
model. No result in this directory authorizes promotion or motion.

