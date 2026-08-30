# August 30 nightly remediation audit

**Evidence scope:** guarded desktop/headless simulation only
**Autonomous physical motion:** **NO-GO**
**Nightly release gate:** **RED**

## Controlling result

The 6,785.5-second extended nightly run completed rather than timing out. Its
non-slow repository selection was green, but the capability gate was red for two
independent reasons:

1. all six degraded-pose NAV_INSTRUCT arms missed their frozen success floors;
2. the slow selection initially returned 4 failed, 68 passed, 8 skipped, 3
   expected failures, 1 unexpected pass, and 3 setup errors.

The pose-drift result remains controlling and was not tuned away. Current truth
success is 7/61; the six drift arms score 1/61, 2/61, 1/61, 1/61, 1/61, and
1/61 against frozen count floors of 8, 5, 2, 6, 2, and 3. Read-only causal
attribution is in [`POSE_DRIFT_NIGHTLY_AUDIT.md`](POSE_DRIFT_NIGHTLY_AUDIT.md).

## Bounded remediation

| Initial finding | Attribution | Action | Verification |
| --- | --- | --- | --- |
| Retired social-corridor literals | One shadow-observer geometry had independent numeric copies | Derive reach and angle from the canonical person social zone and an observer-local width/margin | Literal/allowlist and social/dynamic regression selections pass |
| Held-out scene-name leak | A status document named the exact held-out fixture | Remove the exact fixture name from the status prose; no runtime/eval behavior changed | Held-out-scene ratchet passes |
| Three wheel setup errors | This Debian Python 3.14 build lacks `ensurepip`; wheel construction itself passed | Create the isolated venv without pip and use the parent environment's pip `--python` installation target | Wheel parity: 4/4 pass |
| `sit next to the lamppost` | A blocked terminal pose was treated as proof that the whole semantic instance was unreachable | Preserve the existing candidate-substitution ladder, then permit one same-candidate pose re-solve for the alternate through the unchanged solver, K0 region, clearance, etiquette, and arbiter gates | Focused recovery 13/13; geometry 27/27; live E2E passed twice in 79.89 s and 81.74 s |
| Undeclared-bystander person cell | Expected deadlock still occurs, but four startup slew requests are safely below the speed-dependent predictive boundary, making the veto ratio 28/32 = 0.875 rather than the pinned 0.90 | No product or evaluator change; retain the failure for preregistered maintenance | Deterministic standalone and clean-HEAD reproductions: deadlock, zero collisions, 0.028503 m along-route travel |

The lamppost retry is one-shot, exact-candidate bound, and fail-closed. A missing
candidate, unchanged/unsafe pose, K0-region escape, or arbiter veto immediately
falls back to the previous blacklist behavior. No arrival band, obstacle/person
distance, stopping rule, or frozen floor was weakened.

## Post-remediation runs

All pytest invocations used `pytest_guard.sh` and avoided the live owner stack,
the default simulator socket, and the default persistent database.

- Combined affected selection: **152 passed, 4 skipped, 2 warnings in 88.79 s**.
- Slow marker rerun:
  **1 failed, 74 passed, 8 skipped, 11,293 deselected, 3 expected failures,
  1 unexpected pass, 2 warnings in 2,007.26 s**.
- The only slow failure is
  `test_deadlock_signature_reproduces_with_an_undeclared_bystander` at
  `veto_fraction=0.875` versus its pinned `>=0.9` assertion. Its capability
  signature remains `deadlock`, with `collisions=0`, `blind_veto_ticks=28`,
  `progress_m=0.046747`, and `gate_vetoes_at_cruise=True`.

The full 7x61 drift matrix was not rerun after these unrelated repairs. Its
failure mechanism needs a hard-inflation-preserving reachable-frontier fallback,
direction-aware clearance, and a correct MAP-to-ODOM goal transform before one
targeted panel and then one full matrix rerun. Therefore the nightly gate, and
physical autonomous-motion readiness, remain **RED / NO-GO**.
