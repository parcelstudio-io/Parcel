## T1 — NAV-GEN-1 A0, generated block (450 episodes)

| row | A0ref | off_disc | on_disc | off_full | on_full |
|---|---|---|---|---|---|
| strict success (MA-1 single-instance oracle) | 343 | 343 | 343 | 351 | 350 |
| strict success, any legal instance | 345 | 345 | 350 | 359 | 368 |
| settled success | 339 | 339 | 339 | 346 | 345 |
| `arrived_verified` | 295 | 295 | 300 | 307 | 316 |
| band entry (strict instance) | 355 | 355 | 359 | 361 | 364 |
| band entry, any instance | 358 | 358 | 367 | 370 | 382 |
| `navigation_no_progress` (all) | 49 | 49 | 10 | 32 | 2 |
| … non-POI (goal_source != known_poi) | 49 | 49 | 10 | 32 | 2 |
| … POI (goal_source == known_poi) | 0 | 0 | 0 | 0 | 0 |
| … non-crosswalk target (pre-registered split) | 26 | 26 | 10 | 18 | 2 |
| `semantic_target_unreachable` | 62 | 62 | 95 | 66 | 87 |
| false arrivals | 0 | 0 | 0 | 0 | 0 |
| wrong instance | 0 | 0 | 0 | 0 | 0 |
| **collisions** | 0 | 0 | 0 | 0 | 0 |
| **episodes with `minimum_clearance_m` < 0.65 m** | 1 | 1 | 1 | 4 | 3 |
| steps (total) | 128094 | 128094 | 133170 | 120506 | 123725 |
| steps (median) | 173.0 | 173.0 | 173.0 | 175.0 | 175.0 |
| rows `status=planned` with no terminal reason (A1) | 0 | 0 | 0 | 0 | 0 |

## T2 — NAV-GEN-1 A0, frozen demo block (80 episodes)

| row | A0ref | off_disc | on_disc | off_full | on_full |
|---|---|---|---|---|---|
| strict success | 22 | 22 | 22 | 25 | 25 |
| `arrived_verified` | 19 | 19 | 19 | 19 | 19 |
| `navigation_no_progress` | 18 | 18 | 17 | 16 | 15 |
| `semantic_target_unreachable` | 38 | 38 | 39 | 43 | 44 |
| false arrivals | 1 | 1 | 1 | 1 | 1 |
| **collisions** | 0 | 0 | 0 | 0 | 0 |
| **episodes < 0.65 m** | 1 | 1 | 1 | 1 | 1 |
| steps (total) | 29649 | 29649 | 29733 | 31953 | 32105 |

## T3 — rows moved vs `off_disc` (full-row comparison, 530 episodes)

| row | A0ref | on_disc | off_full | on_full |
|---|---|---|---|---|
| rows changed (full row) | 0 | 48 | 132 | 150 |
| rows byte-identical | 530 | 482 | 398 | 380 |
| rows with a changed terminal reason | 0 | 41 | 43 | 73 |
| strict regressions | 0 | 2 | 10 | 11 |
| strict gains | 0 | 2 | 21 | 21 |
| frozen-block rows changed | 0 | 1 | 34 | 34 |

## T4 — the v4 minival (25 episodes, frozen corpus)

| row | A0ref | off_disc | on_disc | off_full | on_full |
|---|---|---|---|---|---|
| report digest (first 16) | `021b67ab73c4e7be…` | `021b67ab73c4e7be…` | `021b67ab73c4e7be…` | `5e49ef1921fdabd4…` | `5e49ef1921fdabd4…` |
| = HEAD `021b67ab…` | **yes** | **yes** | **yes** | **NO** | **NO** |
| `episode_digest` (first 16) | `4113607b92c734df…` | `4113607b92c734df…` | `4113607b92c734df…` | `4113607b92c734df…` | `4113607b92c734df…` |
| SR | 0.2 | 0.2 | 0.2 | 0.2 | 0.2 |
| SR (frozen rule) | 0.12 | 0.12 | 0.12 | 0.12 | 0.12 |
| SPL | 0.153259 | 0.153259 | 0.153259 | 0.153259 | 0.153259 |
| mean DTG (m) | 8.362383 | 8.362383 | 8.362383 | 8.361944 | 8.361944 |
| collisions | 0 | 0 | 0 | 0 | 0 |
| authority disagreements | 5 | 5 | 5 | 5 | 5 |
| rows moved vs A0ref | 0 | 0 | 0 | 3 | 3 |
| rows whose VERDICT moved | 0 | 0 | 0 | 0 | 0 |

## T5 — the mutation panel

| row | A0ref | off_disc | on_disc | off_full | on_full |
|---|---|---|---|---|---|
| `passed` | True | True | True | True | True |
| survivors | — | — | — | — | — |
| equivalent mutants | — | — | — | — | — |
| clean authority | {"agreement": 4, "authority_disagreement": 1} | {"agreement": 4, "authority_disagreement": 1} | {"agreement": 4, "authority_disagreement": 1} | {"agreement": 4, "authority_disagreement": 1} | {"agreement": 4, "authority_disagreement": 1} |
| clean mean DTG (m) | 0.36168 | 0.36168 | 0.36168 | 0.36168 | 0.36168 |
| clean collisions | 0 | 0 | 0 | 0 | 0 |
| panel identical to A0ref | True | True | True | False | False |
| clean rows moved | 0 | 0 | 0 | 2 | 2 |

### T5b — kill channels per mutant

| mutant | A0ref | off_disc | on_disc | off_full | on_full |
|---|---|---|---|---|---|
| `arrival_radius_x2` | killed / 4 | killed / 4 | killed / 4 | killed / 4 | killed / 4 |
| `reactive_gate_disabled` | killed / 2 | killed / 2 | killed / 2 | killed / 3 | killed / 3 |
| `pose_offset_0m5` | killed / 1 | killed / 1 | killed / 1 | killed / 1 | killed / 1 |
| `inverted_relation` | killed / 4 | killed / 4 | killed / 4 | killed / 4 | killed / 4 |
| `dropped_detections` | killed / 4 | killed / 4 | killed / 4 | killed / 4 | killed / 4 |
| `doubled_envelope` | killed / 3 | killed / 3 | killed / 3 | killed / 3 | killed / 3 |
| `phantom_view_consistent` | killed / 5 | killed / 5 | killed / 5 | killed / 5 | killed / 5 |
