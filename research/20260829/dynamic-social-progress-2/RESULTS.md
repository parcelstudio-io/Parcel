# DSP-2 frozen results

## Executive result

All four preregistered hypotheses were **REFUTED** on the unseen test split.
S2 and S3 each recorded 25 contact episodes out of 145, all 25 caused by an
actor moving into a stationary robot. This fails the first hard gate and makes
both arms ineligible for carry-forward. These are deterministic authored 2-D
simulation results only; they are not physical-safety evidence.

## Protocol and integrity

- Population: 29 test families × 5 independently derived sensor seeds × 4
  arms = **580 episodes**; 145 episodes per arm.
- Per-arm context denominators: sidewalk 65, crosswalk 40, elevator 40.
- Test seeds (`8501`, `8513`, `8521`, `8537`, `8543`, then family-derived) and
  whole-episode trajectory signatures are disjoint from train, development,
  and the 2026-08-26 study.
- Source/fixture freeze SHA-256:
  `6b1a5785d62c61c2dc29b8ee86117674091a699451eb6335b31e8fd9e4819185`.
- Both fresh processes produced normalized episode digest
  `8537c48a8a89fc32f0477e14565e67e252ae70491fa1b642042b8715c228da3c`.
- The two pretty-printed digest manifests are byte-identical; each has file
  SHA-256 `ad05d0588cf434efba423948279c1c06a918bbda590d54bc53e9d5a0eab79530`.
- Full pass files differ only in run metadata such as PID/runtime. Their hashes
  are `4d98485d…884f` (pass 1) and `c15dbb76…3f9f` (pass 2).
- The independent verifier passed both full traces. Its pass-1 tamper self-test
  rejected the accepted-action, actor-trajectory, and semantic-phase mutations.
- Pass 1: 26.81 s wall time, 299,716 KiB max RSS. Pass 2: 27.05 s wall time,
  308,944 KiB max RSS. These are desktop Python simulator timings, not Orin or
  robot control-loop measurements.

## Arm-level outcomes

Completion is deliberately independent of safety. `Safe successes` is the
intersection of `task_success` with the separate episode safety gate; it does
not rewrite completion after a contact.

| Arm (n=145) | Contact eps | Near eps | Actor→stationary contact eps | Min / p05 surface clearance (m) | Current hard-floor ticks | Hard admissions | Task successes | Safe successes | False-block (s) | Stop/start transitions |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| S0 | 57 | 63 | 57 | -0.596000 / -0.595000 | 1,598 | 0 | 135 (93.10%) | 72 (49.66%) | 841.3 | 347 |
| S1 | 37 | 42 | 37 | -0.596000 / -0.590000 | 1,006 | 0 | 140 (96.55%) | 101 (69.66%) | 580.8 | 596 |
| S2 | 25 | 35 | 25 | -0.590886 / -0.566225 | 468 | 0 | 128 (88.28%) | 105 (72.41%) | 805.6 | 1,285 |
| S3 | 25 | 27 | 25 | -0.582423 / -0.564695 | 466 | 0 | 124 (85.52%) | 99 (68.28%) | 966.5 | 1,189 |

Authorization, reverse-after-entry, elevator egress, capacity, door-plane, and
staging-region violation ticks were zero in every arm. The negative clearances
and current hard-floor ticks above remain disqualifying even though no command
was labeled as a hard-envelope admission.

## Context outcomes

Each cell reports episodes, task successes, contacts, near contacts,
false-block seconds, and stop/start transitions.

| Arm/context | n | Success | Contact | Near | False-block s | Transitions |
|---|---:|---:|---:|---:|---:|---:|
| S0 sidewalk | 65 | 65 | 32 | 33 | 217.6 | 217 |
| S0 crosswalk | 40 | 35 | 0 | 5 | 287.7 | 70 |
| S0 elevator | 40 | 35 | 25 | 25 | 336.0 | 60 |
| S2 sidewalk | 65 | 57 | 10 | 20 | 270.6 | 599 |
| S2 crosswalk | 40 | 35 | 0 | 0 | 313.8 | 106 |
| S2 elevator | 40 | 36 | 15 | 15 | 221.2 | 580 |
| S3 sidewalk | 65 | 53 | 10 | 12 | 406.8 | 553 |
| S3 crosswalk | 40 | 35 | 0 | 0 | 314.0 | 114 |
| S3 elevator | 40 | 36 | 15 | 15 | 245.7 | 522 |

S2/S3 prevented all crosswalk contacts in this authored population. Their
contacts instead came from elevator exit-first/temporary-clear/flicker and
sidewalk group-gap/overtaking families.

## Stratum denominators

Cells are `n / task successes / contacts`; denominators are repeated explicitly
so that difficult episodes cannot disappear inside a percentage.

| Stratum | S0 | S1 | S2 | S3 |
|---|---:|---:|---:|---:|
| Responsive | 85 / 85 / 34 | 85 / 85 / 26 | 85 / 77 / 25 | 85 / 76 / 25 |
| Non-responsive | 45 / 35 / 23 | 45 / 40 / 11 | 45 / 36 / 0 | 45 / 33 / 0 |
| Otherwise-feasible non-responsive | 35 / 30 / 23 | 35 / 35 / 11 | 35 / 31 / 0 | 35 / 28 / 0 |
| Flicker or occlusion | 25 / 25 / 16 | 25 / 25 / 12 | 25 / 25 / 5 | 25 / 21 / 5 |
| Otherwise feasible | 130 / 125 / 57 | 130 / 130 / 37 | 130 / 118 / 25 | 130 / 114 / 25 |
| Expected refusal | 10 / 10 / 0 | 10 / 10 / 0 | 10 / 10 / 0 | 10 / 10 / 0 |

The narrow stop-only mechanism did generalize to the non-responsive stratum:
S2 and S3 had zero contacts there. It did not generalize to responsive actors;
all 25 contacts in each arm occurred in that stratum.

## Per-family results

Every family has five episodes per arm. Cells are `task success / contact /
near-contact` counts out of five. Expected refusals count as task success but
remain separate from the safety counters.

| Family (n=5/arm) | S0 | S1 | S2 | S3 |
|---|---:|---:|---:|---:|
| crosswalk_clear_flicker_test | 5/0/0 | 5/0/0 | 5/0/0 | 5/0/0 |
| crosswalk_late_entrant_test | 5/0/0 | 5/0/0 | 5/0/0 | 5/0/0 |
| crosswalk_lateral_flow_test | 5/0/0 | 5/0/0 | 5/0/0 | 5/0/0 |
| crosswalk_mid_intrusion_test | 5/0/5 | 5/0/0 | 5/0/0 | 5/0/0 |
| crosswalk_owner_group_test | 5/0/0 | 5/0/0 | 5/0/0 | 5/0/0 |
| crosswalk_persistent_blocker_test | 0/0/0 | 0/0/0 | 0/0/0 | 0/0/0 |
| crosswalk_short_authorization_test | 5/0/0 | 5/0/0 | 5/0/0 | 5/0/0 |
| crosswalk_unauthorized_test | 5/0/0 | 5/0/0 | 5/0/0 | 5/0/0 |
| elevator_clear_flicker_test | 5/5/5 | 5/5/5 | 5/5/5 | 5/5/5 |
| elevator_closing_reopening_test | 5/0/0 | 5/0/0 | 5/0/0 | 5/0/0 |
| elevator_exit_first_test | 5/5/5 | 5/5/5 | 5/5/5 | 5/5/5 |
| elevator_narrow_entry_test | 0/0/0 | 5/0/0 | 1/0/0 | 1/0/0 |
| elevator_nonresponsive_exit_test | 5/5/5 | 5/5/5 | 5/0/0 | 5/0/0 |
| elevator_occluded_egress_test | 5/5/5 | 5/5/5 | 5/0/0 | 5/0/0 |
| elevator_occupied_full_test | 5/0/0 | 5/0/0 | 5/0/0 | 5/0/0 |
| elevator_temporary_clear_test | 5/5/5 | 5/5/5 | 5/5/5 | 5/5/5 |
| sidewalk_advancing_nonresponsive_test | 5/5/5 | 5/0/0 | 5/0/0 | 2/0/0 |
| sidewalk_clear_flicker_test | 5/1/1 | 5/1/2 | 5/0/5 | 1/0/0 |
| sidewalk_crossing_test | 5/0/0 | 5/0/0 | 5/0/0 | 5/0/0 |
| sidewalk_cut_in_test | 5/0/0 | 5/0/0 | 5/0/0 | 5/0/0 |
| sidewalk_group_gap_test | 5/5/5 | 5/5/5 | 2/5/5 | 5/5/5 |
| sidewalk_occlusion_test | 5/5/5 | 5/1/1 | 5/0/0 | 5/0/0 |
| sidewalk_oncoming_nonresponsive_test | 5/3/3 | 5/0/0 | 5/0/0 | 5/0/0 |
| sidewalk_oncoming_test | 5/3/4 | 5/0/4 | 5/0/5 | 5/0/2 |
| sidewalk_overtaking_test | 5/5/5 | 5/5/5 | 5/5/5 | 5/5/5 |
| sidewalk_owner_alongside_test | 5/0/0 | 5/0/0 | 5/0/0 | 5/0/0 |
| sidewalk_same_flow_pass_test | 5/0/0 | 5/0/0 | 5/0/0 | 5/0/0 |
| sidewalk_sudden_stop_test | 5/0/0 | 5/0/0 | 5/0/0 | 5/0/0 |
| sidewalk_sudden_turn_test | 5/5/5 | 5/0/0 | 0/0/0 | 0/0/0 |

## Latency and censoring

Each entry reports `eligible / observed / censored; p50 / p95 seconds`. Only
observed legs contribute a percentile; censored denominators remain visible.

| Arm | Truth→evidence | Evidence→decision | Decision→motion |
|---|---|---|---|
| S0 | 183/168/15; 0.0/2.7 | 168/166/2; 0.1/0.1 | 166/166/0; 0.0/0.0 |
| S1 | 161/143/18; 0.0/7.29 | 143/143/0; 0.0/0.0 | 143/143/0; 0.0/0.0 |
| S2 | 157/152/5; 0.0/5.9 | 152/152/0; 0.0/0.8 | 152/152/0; 0.0/0.0 |
| S3 | 155/147/8; 0.0/8.96 | 147/147/0; 0.0/0.4 | 147/147/0; 0.0/0.0 |

S3 met the isolated H3 latency bounds exactly/comfortably, but its safety,
false-block, transition, and completion clauses failed.

## Motion proxies and diagnostic calibration

| Arm | Mean completed-path efficiency | Mean acceleration (m/s²) | Mean jerk proxy (m/s³) | Mean lateral travel (m) | Risk Brier / ECE (samples) |
|---|---:|---:|---:|---:|---:|
| S0 | 0.985478 | 0.186178 | 1.594737 | 0.235424 | 0.238344 / 0.288271 (21,599) |
| S1 | 0.937728 | 0.269665 | 2.794137 | 0.552674 | 0.356882 / 0.393979 (21,968) |
| S2 | 0.853092 | 0.269429 | 2.127578 | 0.766826 | 0.262863 / 0.273013 (25,368) |
| S3 | 0.868746 | 0.299095 | 2.590812 | 0.651973 | 0.237475 / 0.256670 (27,240) |

Minimum TTC was `0.0 s` in every arm because each arm contained contact
episodes. Calibration is diagnostic only and never admitted motion.

## Hypothesis decisions

- **D2-H1 — REFUTED.** S2 and S3 each had 25 contacts, 25
  actor-into-stationary contacts, and 468/466 current hard-floor ticks. Hard
  admissions were zero, but every clause is conjunctive.
- **D2-H2 — REFUTED.** Combined crosswalk/elevator completion was 70/80 for S0
  and 71/80 for S2: only **+1.25 percentage points**, below +15. Sidewalk
  completion also fell from 65/65 to 57/65. S2 near contacts were lower (35 vs
  63). All actual resource-boundary semantic counters were zero.
- **D2-H3 — REFUTED.** S3 false-block time was 19.97% worse than S2. It reduced
  transitions by only 7.47%, not 20%, and completion fell by 2.76 points. The
  `0.4 s` evidence-to-decision and `0.0 s` decision-to-motion p95 clauses passed,
  but H1 and the other conjuncts failed.
- **D2-H4 — REFUTED.** S3 completed 28/35 feasible non-responsive episodes
  (exactly 80%) and 21/25 flicker/occlusion episodes (84%), but H1 failed and
  30 releases were classified as missing/non-free-only.

### Frozen scorer audit note

The frozen H2 `zero_forbidden_events` helper conservatively sums current
hard-floor ticks together with semantic-resource events, so its JSON clause is
`false`. The preregistered H2 wording names entry/reverse/egress/staging events;
each of those actual counters is zero. Excluding hard-floor ticks post hoc would
make only that H2 sub-clause true and would **not** change H2's `REFUTED` status,
because the completion-gain and sidewalk-completion clauses independently fail.
The frozen JSON and verifier result are preserved unchanged.

## Development-to-test generalization gap

The final development split had zero S2/S3 contacts and hard-floor ticks, while
test had 25 contacts in each arm. The gap is concentrated in whole families
absent from development: responsive two-person group gaps, same-flow
overtaking, and several elevator exit schedules. This is direct evidence that
the development fixture inventory was too narrow and that candidate-level
robustness did not imply episode-level interaction robustness.

