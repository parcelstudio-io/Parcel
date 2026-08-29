# Sim-plan-2 results

**Overall:** `SUPPORTED_REGRESSION_SHADOW`  
**Evidence:** authored symbolic regression/shadow only; no physics, hardware,
or motion  
**Matrix:** 29 frozen missions, 87 V2 evaluations across three operator orders  
**Deterministic payload:**
`29a345e8dea589b5a45f408f03d00021b2392d5004903b755bfe198d523c0007`

Two separate process runs produced identical JSON and file SHA-256 values.
The verifier passed all 12 integrity and frozen-claim checks, including a fresh
in-process replay.

## Outcomes

| Metric | Frozen V1 | V2 follow-up |
|---|---:|---:|
| Exact typed dispositions | 26/29 (89.66%) | 29/29 (100.00%) |
| Valid plans on authored-solvable missions | 18/18 | 18/18 |
| Shadow hard-safety violations | 0 | 0 |
| Shadow admission violations | 0 | 0 |
| Frozen false observation requests repaired | — | 3/3 |

- **H1 `SUPPORTED_REGRESSION_SHADOW` (3/3 gates):** all 29 dispositions were
  exact, every authored critical unknown remained reported, and the three V1
  false observation requests became `unreachable` with no uncertain facts.
- **H2 `SUPPORTED_REGRESSION_SHADOW` (3/3 gates):** all 18 valid symbolic
  plans were retained with zero shadow hard-safety or admission violations.
- **H3 `SUPPORTED_REGRESSION_SHADOW` (3/3 gates):** all 87 evaluations were
  operator-order invariant, exactly bound to state/problem/manifest/
  reliability/observability digests, and never authorized motion.

The repaired cases were `greet-camera-false`,
`greet-scan-uncommissioned`, and `follow-consent-false`. V1 accumulated
downstream unknowns even though a contradicted prerequisite or uncommissioned
producer made the goal chain impossible. V2 requested an observation only
after a bounded optimistic pass proved that one or more explicitly observable
unknowns could support a complete admitted, invariant-preserving goal chain.

## Interpretation limits

This is a regression confirmation, not a new generalization result. The V1
matrix and failures directly informed V2, the observability set is authored,
and the operators still use idealized symbolic effects. The result does not
measure perception correctness, changing-world observability, plan execution,
outcome recovery, physics, learned affordances, generalized movement,
sim-to-real transfer, latency, or Unitree readiness. No hosted API was used;
measured hosted cost was `$0`. No result in this directory authorizes runtime
integration, promotion, or motion.
