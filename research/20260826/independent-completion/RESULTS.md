# Independent completion authority — results

**Verdict:** `REFUTED` (19/20 preregistered checks passed)
**Evidence:** deterministic synthetic architecture experiment; no robot hardware
**Matrix:** 360 cases x 3 arms = 1,080 executed rows
**Deterministic payload:**
`cd8ae7f55d0f194215dbf3492c04eef921caabf10843b240d7152678236c0e76`

## Result in one sentence

The independent arm converted all 120 catastrophic C2 alias completions into
typed uncertainty, including all 15 cases where its discontinuity sensor was
blind, but it missed the preregistered nominal-recall gate: 116/120 true
arrivals versus a required 118/120 and 117/120 for the covariance control.

## Primary outcomes

| Family | Arm | True arrival | False arrival | `localization_uncertain` | Silent timeout | Contacts |
|---|---|---:|---:|---:|---:|---:|
| nominal, 120 | covariance only | 117 | 3 | 0 | 0 | 0 |
| nominal, 120 | five-tick streak | 116 | 4 | 0 | 0 | 0 |
| nominal, 120 | independent witness + latch | **116** | **4** | 0 | 0 | 0 |
| alias, 120 | covariance only | 0 | **120** | 0 | 0 | 0 |
| alias, 120 | five-tick streak | 0 | **120** | 0 | 0 | 0 |
| alias, 120 | independent witness + latch | 0 | **0** | **120** | 0 | 0 |
| witness dropout, 120 | covariance only | 115 | 5 | 0 | 0 | 0 |
| witness dropout, 120 | five-tick streak | 116 | 4 | 0 | 0 | 0 |
| witness dropout, 120 | independent witness + latch | **85** | **3** | **32** | 0 | 0 |

The controls falsely arrived in every alias opportunity. Their terminal truth
distance was 4.905--6.694 m. The candidate made no alias completion claim, so
this is a change from catastrophic false success to an explicit refusal; it is
not successful relocalization or task completion.

## Latency and dropout

- Nominal independent authorization: p50 0.4 s, p95 0.7 s.
- Short blackouts (0.6/1.2/1.8 s): 85/90 true arrivals, 3 boundary false
  arrivals and 2 typed uncertain outcomes. Recovered-case p95 authorization
  latency was 2.4 s, under the 2.5 s gate.
- Long 4.2 s blackouts: 30/30 ended `localization_uncertain` at the registered
  3.5 s deadline; none silently waited or falsely arrived.
- Registered false latches: 30/36 re-armed. The other six were in unavailable
  evidence paths. Re-arm latency p95 was 2.4 s.

## Why the hypothesis was refuted

The nominal threshold required at least 118/120 true candidate arrivals. The
candidate achieved 116/120. All four misses were declared arrivals scored just
outside the frozen 0.50 m truth band:

| Case coordinate | Candidate truth distance |
|---|---:|
| L0 / S4 / bed | 0.508495 m |
| L1 / S4 / bed | 0.501041 m |
| L2 / S1 / bed | 0.500089 m |
| L3 / S4 / bed | 0.514404 m |

Three of these already fail under covariance-only completion. The fourth
(L0/S4/bed) exposes a loop detail: the inherited covariance arm integrates its
last requested command after making its completion claim and finishes at
0.496496 m, whereas both waiting arms correctly hold during quarantine and
remain at 0.508495 m. The candidate must not recover its metric by allowing a
post-claim motion. Its identity witness needs a separate, calibrated terminal
geometry witness.

The result therefore distinguishes two problems:

1. The descriptor margin supplies independent *place identity* evidence and
   rejects the large C2 alias.
2. Its broad 0.90--2.30 m wall-landmark range is not precise evidence that the
   body lies inside a 0.50 m goal disc. MAP drift still decides that boundary.

## Non-oracle evidence audit

The policy schema and scorer schema had no fields in common. The candidate
received only time, MAP claim/health, noisy discontinuity score and noisy
target/runner-up/range evidence.

- 15/120 alias cases deliberately lost the discontinuity sample.
- In those 15 blind cells, the candidate reached the wrong MAP completion
  point and received 241 landmark frames. 236 had a raw target score >=0.65,
  but zero beat the correct physical twin by the registered margin. All 15
  terminated uncertain with zero false arrivals.
- Across all candidate cases, 1,568/3,717 scheduled witness queries were
  missing, including 350 with no visible landmark.
- Across all alias cases, 895 raw-high-target frames occurred. The witness was
  therefore noisy/confusable rather than a disguised `is_at_goal` oracle.
- The discontinuity stream contained 15 blind jump samples and 36 injected
  false artifacts.

These checks constrain the software experiment. They do not establish that a
real visual descriptor or pickup detector has the simulated distributions.

## Acceptance ledger

Passed:

- exact 120/120/120 matrix and all 1,080 arm rows;
- 120 covariance alias opportunities and both controls false on 100%;
- zero candidate alias false arrivals, including blind-discontinuity cases;
- zero candidate contact and no nominal contact regression;
- 85/90 short-dropout recovery and 2.4 s p95 authorization latency;
- all unresolved alias/dropout cases typed uncertain;
- all 30 long outages typed uncertain, zero silent timeouts;
- 30 false-latch re-arms with 2.4 s p95 latency;
- policy/scorer schema separation and deliberately non-perfect evidence; and
- exact deterministic replay plus source, matrix and row integrity.

Failed:

- candidate nominal recall >=118/120: observed **116/120**.

## Reproduction and integrity

```bash
.parcel/bin/python research/20260826/independent-completion/experiment.py \
  --out research/20260826/independent-completion/results-run1.json
.parcel/bin/python research/20260826/independent-completion/experiment.py \
  --out research/20260826/independent-completion/results-run2.json
.parcel/bin/python research/20260826/independent-completion/verify_results.py \
  --write-canonical
```

Run wall times were 608.749 s and 609.232 s. Both produced the same
deterministic payload digest. `verification.json` records 17/17 integrity
checks as true; canonical `results.json` is an exact copy of run 1.

## Evidence limits

This result is synthetic and architectural. It does not calibrate camera
appearance, active viewing, landmark occlusion, LiDAR alias frequency, IMU
pickup signals, real localization covariance, Go2 motion, foot contact,
stairs, transport latency or physical stop behavior. It cannot authorize a
mount or provide a field false-arrival probability.
