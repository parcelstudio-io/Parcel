# Dynamic social progress · results

## Outcome

The reportable run contains 475 paired test episodes: 19 held-out templates ×
5 held-out sensor seeds × 5 arms. Every arm saw the same seed-specific sensor
mutation stream. **All four preregistered hypotheses were refuted, and no arm is
eligible for product carry-forward** because every arm had at least one contact.

This is useful negative evidence. A visibility-aware tracker prevented release
on missing detections in the occluded-survivor slice, and the semantic lattice
eliminated authorization, capacity, egress-priority, and moving hard-floor
violations. Neither mechanism supplied a collision-free staging/escape behavior
when a nonreactive person moved into a stopped robot.

| Arm | Complete | Contact episodes | Actor-into-stationary contacts | False block | Deadlocks | Semantic violation ticks |
|---|---:|---:|---:|---:|---:|---:|
| A0 radial wait | 63.2% | 25 | 20 | 684.0 s | 20 | 658 |
| A1 CV-TTC | 57.9% | 20 | 20 | 623.6 s | 25 | 640 |
| A2 uncertainty mixture | 57.9% | 20 | 20 | 642.8 s | 25 | 599 |
| A3 semantic lattice | 78.9% | 20 | 20 | 566.8 s | 20 | 0 |
| A4 soft critic | 77.9% | 20 | 20 | 586.7 s | 21 | 0 |

All A1–A4 contact episodes were caused by a scripted oncoming/egress actor
advancing into a robot that had commanded hold. A0 additionally contacted the
occluded stationary survivor. A2–A4 had zero stopped-to-moving releases while
the swept corridor was unobserved. “Hard-floor violation” here scores commanded
translation inside the floor, so zero such ticks does not erase contacts caused
by another actor moving into a stationary robot.

## Preregistered hypotheses

- **H1 — REFUTED.** A2's median truth-clear-to-motion latency on visible-clear
  events was 1.85 s, versus 0.80 s for A0; it missed both the ≤0.6 s and 50%
  improvement bars. Median explicit-evidence-to-motion latency was 0.10 s for
  A2. The separate occluded-survivor condition passed: zero A2 contacts and zero
  releases based only on missing detections.
- **H2 — REFUTED.** A2 reduced false-block time only 6.0%, not 40%, and
  completion fell 5.3 percentage points rather than improving 15 points. It had
  20 contacts. Near-contact episodes decreased from 25 to 20, but that cannot
  rescue the hypothesis.
- **H3 — REFUTED.** A3 improved combined crosswalk/elevator completion by 18.2
  points, did not worsen sidewalk completion (+25 points), and recorded zero
  semantic or moving hard-floor violations. It nevertheless had 20 contacts,
  so it fails the zero-contact bar and the preregistered eligibility rule.
- **H4 — REFUTED.** The critic separated synthetic nominal-continuation contact
  labels well (AUROC 0.945; Brier 0.093), but the dev-selected threshold's held-
  out false-negative rate was 4.12%, above 1%. A4 increased false-block time by
  3.5% relative to A3 and had 20 contacts. The dev/test shift (13.9% versus
  22.2% positive prevalence) is a warning against relying on a synthetic risk
  score as authority; this experiment kept it soft-only.

## Interpretation and next experiment

The strongest mechanism to retain for research is the *separation* of a fresh
free-space certificate, a retained uncertain track, semantic resource phases,
and the final hard monitor—not any measured distance or model threshold. The
next frozen experiment should add:

1. a timestamped swept-corridor evidence state that requires observed free rays
   and cannot be satisfied by tracker deletion;
2. an explicit safe staging region beside elevator egress and an evasive
   candidate for an approaching person, because “stop” is not a safe terminal
   action when another actor can keep moving;
3. a bounded liveness state machine (`HOLD → CLEAR_CONFIRM → CREEP → GO`, with
   `REPLAN/RETREAT` when occupancy persists) and separately score truth-clear,
   evidence-available, decision, and physical-motion times;
4. responsive pedestrians plus nonresponsive/adversarial variants, track
   association faults, ray-level occlusion, latency, and robot braking dynamics;
5. calibration by held-out scenario family before the A4 critic is allowed to
   influence ranking, while preserving deterministic candidate rejection.

The current product's differing decay horizons should also be tested directly:
the grid can require repeated clear rays, an occluded grid cell may not decay,
the tracker can delete after misses, and the close-range gate can clear on one
fresh scan. The standalone harness models these only as a coarse
`corridor_observed` certificate and existence decay; it does not replay the
product log-odds implementation.

## Integrity and limitations

- Result file: `results/results.json`
- Episode digest: `932167875fd16bbd67256f60ef8b555b074bfb23fb2eb4b3695aa5051578c1ad`
- Deterministic full replay: byte-identical, independently checked by
  `verify_results.py --rerun`.
- The pre-acceptance harness audit found and corrected four specification bugs:
  arm-dependent sensor RNG, vacuous `all([])` release during an unobserved
  corridor, traversal being credited in expected-refusal tasks, and reversed
  false-positive visibility timing. These were contract corrections, not
  threshold or behavior tuning; only the corrected paired run is reported.
- Tracks use authored actor IDs; semantic context and permission bits are oracle
  inputs. The free-space certificate is one idealized boolean. People are
  scripted and nonreactive. There is no association error, camera/LiDAR model,
  sidewalk/crosswalk/elevator perception, Go2 dynamics, ROS timing, Orin timing,
  human study, or physical test.

These results are research evidence only and do not support mounting or moving
the physical prototype around people.
