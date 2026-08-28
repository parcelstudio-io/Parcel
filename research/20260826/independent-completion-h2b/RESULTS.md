# H2b independent completion — results

**Verdict:** `REFUTED` (9/10 preregistered gates passed)
**Evidence:** deterministic synthetic architecture holdout; no hardware
**Matrix:** 600 cases x 3 arms = 1,800 rows
**Canonical payload:**
`8207f05d9dfeb7add8b156b43f2653732519c90276bff314f2ed59f2b29a7daf`

## Result in one sentence

The strict identity -> verified new pose epoch -> conservative geometry chain
made zero false claims across 360 alias, outside-boundary and lineage-attack
opportunities and preserved 120/120 nominal completion, but recovered only
113/120 alias cases against the frozen requirement of 114/120.

## Primary outcomes

| Family, 120 each | Arm | True claims | False claims | Typed uncertain |
|---|---|---:|---:|---:|
| nominal | map only | 120 | 0 | 0 |
| nominal | H2 identity/range | 120 | 0 | 0 |
| nominal | **H2b chain** | **120** | **0** | **0** |
| alias recovery | map only | 0 | 120 | 0 |
| alias recovery | H2 identity/range | 0 | 80 | 40 |
| alias recovery | **H2b chain** | **113** | **0** | **7** |
| outside boundary | map only | 0 | 120 | 0 |
| outside boundary | H2 identity/range | 0 | 120 | 0 |
| outside boundary | **H2b chain** | **0** | **0** | **120** |
| sensor dropout | map only | 120 | 0 | 0 |
| sensor dropout | H2 identity/range | 80 | 0 | 40 |
| sensor dropout | **H2b chain** | **0** | **0** | **120** |
| lineage attack | map only | 0 | 120 | 0 |
| lineage attack | H2 identity/range | 0 | 120 | 0 |
| lineage attack | **H2b chain** | **0** | **0** | **120** |

H2b resolvable coverage was 233/240 (97.08%), above the preregistered
232/240 selective-coverage gate. Alias recovery p95 latency was 0.372 s,
well below 2.50 s. Seven registered recovery-frame losses ended typed
`localization_uncertain`; the gate allowed at most six.

## Safety and contract findings

- All 40 identity attacks, 40 residual attacks and 40 terminal-geometry
  attacks blocked the adversarial first alias candidate.
- The 120 endpoints 0.501--0.580 m outside the truth band produced zero H2b
  claims. The broad H2 range control falsely claimed all 120.
- All 120 sensor dropouts and all 120 broken-lineage cases terminated typed
  uncertain; there were no silent outcomes in the canonical pair.
- Policy DTO fields had no intersection with scorer-only fields. The decision
  exposed no velocity/command fields and `authorizes_motion` remained false in
  every H2b row.
- Schema-v2 evidence is bound to a per-goal nonce, cannot predate goal start,
  and rechecks cached pose-verification expiry on every step.
- Current post-result hardening admits identity, pose-reset and geometry records
  only through role-specific process-local HMAC wrappers. Exact provider and
  verifier IDs are bound into each tag, and an enabled latch requires three
  distinct commissioned provider/verifier/key channels. Raw, changed or
  wrong-channel records fail closed without changing the frozen outcome.
- Map-only controls falsely claimed 120/120 alias, 120/120 boundary and 120/120
  lineage cases, so the negative controls bit.

## Acceptance ledger

Passed: matrix/seed separation, negative controls, zero H2b false claims,
120/120 nominal recall, typed uncertainty/no silence, all three attack layers,
233/240 selective coverage, field/motion audit, and deterministic replay.

Failed: alias recovery >=114/120. Observed **113/120**; the seven failures were
the preregistered deterministic 5% recovery-frame-loss branch. The frozen
threshold is not weakened after observation.

## Reproduction and integrity

```bash
.parcel/bin/python research/20260826/independent-completion-h2b/experiment.py \
  --out research/20260826/independent-completion-h2b/results-run4.json
.parcel/bin/python research/20260826/independent-completion-h2b/experiment.py \
  --out research/20260826/independent-completion-h2b/results-run5.json
.parcel/bin/python research/20260826/independent-completion-h2b/verify_results.py \
  --write-canonical
```

Runs 4 and 5 were regenerated after the process-local provenance hardening and
produced identical payloads. The verifier passed 13/13 integrity checks, all
five recorded source digests matched, and run 4 was copied to `results.json`.

Runs 1--3 remain as excluded pilot evidence rather than being overwritten.
Run 1 sampled the timeout 2 ms before `first_candidate + 4 s`; runs 2--3 fixed
that but revealed that the identity-missing harness had omitted its initial
candidate. Those were harness deviations from the frozen design. The fixed
source adds the missing candidate and samples after the deadline; neither fix
changes a threshold, seed, noise draw or recovery outcome. The canonical pair
still refutes H2b on 113/120 recovery.

## Evidence limits

The harness supplies a successful post-reset replan when recovery evidence is
available. It does not implement or validate global relocalization, active
viewing, a navigation controller, camera/Mid-360/IMU calibration, transport,
Go2 dynamics or physical stop behavior. The distributions are synthetic and
not hardware-calibrated. This result supports retaining and replay-testing the
isolated contract; it does not support pipeline promotion or physical motion.
The new authentication boundary proves only process-local interface integrity
and exact software-channel provenance. Its deterministic harness keys and
distinct IDs do not establish independent physical sensors, processes,
administrators, calibration, key custody or failure domains; production sensor
independence remains untested.
