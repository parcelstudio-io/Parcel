### 4.1 The sweep (generated block, 450 episodes per arm)

| arm | sweep | `map_safety_margin_m` | `safety.stop_distance_m` | **live planner inflation (m)** | strict success | 95 % Wilson CI | any-instance strict | band entry | nav-claimed | grounding-class episodes | false arrivals | collisions | episodes with min clearance < 0.65 m |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A0 **(commissioned)** | A | 0.10 | 0.80 | 1.0223 | 293/450 = **0.6511** | [0.6060, 0.6937] | 0.6556 | 0.6889 | 0.6311 | 90 | 42 | **0** | 1 |
| A0c | A | 0.10 | 0.80 | 1.0223 | 293/450 = **0.6511** | [0.6060, 0.6937] | 0.6556 | 0.6889 | 0.6311 | 90 | 42 | **0** | 1 |
| A1 | A | 0.07 | 0.80 | 1.0223 | 293/450 = **0.6511** | [0.6060, 0.6937] | 0.6556 | 0.6889 | 0.6311 | 90 | 42 | **0** | 1 |
| A2 | A | 0.05 | 0.80 | 1.0223 | 293/450 = **0.6511** | [0.6060, 0.6937] | 0.6556 | 0.6889 | 0.6311 | 90 | 42 | **0** | 1 |
| A3 | A | 0.02 | 0.80 | 1.0223 | 293/450 = **0.6511** | [0.6060, 0.6937] | 0.6556 | 0.6889 | 0.6311 | 90 | 42 | **0** | 1 |
| A4 | A | 0.00 | 0.80 | 1.0223 | 293/450 = **0.6511** | [0.6060, 0.6937] | 0.6556 | 0.6889 | 0.6311 | 90 | 42 | **0** | 1 |
| B1 | B | 0.10 | 0.65 | 0.8854 | 302/450 = **0.6711** | [0.6264, 0.7129] | 0.6756 | 0.7000 | 0.6400 | 90 | 42 | **0** | 3 |
| B2 | B | 0.10 | 0.50 | 0.7485 | 298/450 = **0.6622** | [0.6173, 0.7044] | 0.6644 | 0.6956 | 0.6356 | 90 | 41 | **0** | 13 |
| B3 | B | 0.10 | 0.40 | 0.6572 | 298/450 = **0.6622** | [0.6173, 0.7044] | 0.6644 | 0.6956 | 0.6333 | 90 | 40 | **0** | 18 |
| B4 | B | 0.10 | 0.32 | 0.5842 | 296/450 = **0.6578** | [0.6128, 0.7001] | 0.6600 | 0.6933 | 0.6222 | 90 | 40 | **0** | 15 |

### 4.2 Gain vs the commissioned arm

| arm | live planner inflation (m) | gain (points, strict) | collisions | zero collisions |
|---|---|---|---|---|
| A0c | 1.0223 | +0.00 | 0 | yes |
| A1 | 1.0223 | +0.00 | 0 | yes |
| A2 | 1.0223 | +0.00 | 0 | yes |
| A3 | 1.0223 | +0.00 | 0 | yes |
| A4 | 1.0223 | +0.00 | 0 | yes |
| B1 | 0.8854 | +2.00 | 0 | yes |
| B2 | 0.7485 | +1.11 | 0 | yes |
| B3 | 0.6572 | +1.11 | 0 | yes |
| B4 | 0.5842 | +0.67 | 0 | yes |

### 5.1 Reason histogram — strict failures, commissioned arm, generated block

n = 157 strict failures of 450 episodes.

| reason | n | share | of which grounding-class (wrong instance) |
|---|---|---|---|
| `navigation_no_progress` | 68 | 0.433 | 42 |
| `semantic_target_unreachable` | 44 | 0.280 | 0 |
| `arrived` | 42 | 0.268 | 42 |
| `arrived_verified` | 2 | 0.013 | 0 |
| `semantic_target_ambiguous` | 1 | 0.006 | 0 |

### 5.2 Top-5 failure reasons with one example episode each

| reason | n | example episode id | example DTG (m) | example inside 2x band |
|---|---|---|---|---|
| `navigation_no_progress` | 68 | `gen:880000:crosswalk:0` | 1.9556 | False |
| `semantic_target_unreachable` | 44 | `gen:880000:bench:1` | 3.4981 | False |
| `arrived` | 42 | `gen:880000:crosswalk:1` | 2.6865 | False |
| `arrived_verified` | 2 | `gen:880014:planter:1` | 8.8064 | False |
| `semantic_target_ambiguous` | 1 | `gen:880008:planter:2` | 6.9251 | False |

### 5.3 H-NG1a's two clauses

| quantity | commissioned arm | any-instance oracle | excluding `crosswalk` |
|---|---|---|---|
| strict failures (n) | 157 | 155 | 73 |
| inside 2x band | 0.2357 | 0.2387 | 0.3288 |
| reason in the DESIGN's list | 0.2803 | 0.2839 | 0.6027 |
| **covered by H-NG1a clause 1** | 0.4459 | 0.4516 | 0.7808 |
| **grounding failures** | 0.535 | 0.5419 | 0.0 |
| false arrivals | 0.2675 | 0.271 | 0.0 |
| sensitivity: + `navigation_no_progress` | 0.7261 | 0.7355 | 0.9589 |

### 5.4 False arrivals — distance to the goal, commissioned arm

| quantity | value |
|---|---|
| false arrivals (n) | 42 |
| min DTG (m) | 0.6287 |
| median DTG (m), interpolated (`statistics.median`) | 3.1722 |
| median DTG (m), upper-middle order statistic `dtg[n//2]` | 3.2492 |
| worst DTG (m) | 7.169 |
| by target | `crosswalk` x42 |

### 6.1 Frozen demo block, per target (commissioned arm, 16 episodes each)

| target | band entry | rate | 95 % CI | strict | MA-1 published probe | delta vs MA-1 | within +-0.15 of MA-1 | DESIGN's quoted value | within +-0.15 of DESIGN |
|---|---|---|---|---|---|---|---|---|---|
| `bench` | 2/16 | **0.1250** | [0.035, 0.360] | 0.0625 | 0.19 | -0.0650 | yes | 0.0 | yes |
| `lamppost` | 6/16 | **0.3750** | [0.185, 0.614] | 0.3750 | 0.44 | -0.0650 | yes | 0.6 | NO |
| `planter` | 2/16 | **0.1250** | [0.035, 0.360] | 0.0625 | 0.06 | +0.0650 | yes | -- | -- |
| `sidewalk` | 13/16 | **0.8125** | [0.570, 0.934] | 0.8125 | 0.75 | +0.0625 | yes | 0.75 | yes |
| `crosswalk` | 1/16 | **0.0625** | [0.011, 0.283] | 0.0625 | 0.12 | -0.0575 | yes | -- | -- |

### 6.2 Frozen block vs generated block (commissioned arm, one predicate)

| block | episodes | strict success | rate | 95 % Wilson CI |
|---|---|---|---|---|
| frozen demo block | 80 | 22 | **0.2750** | [0.1892, 0.3814] |
| generated block | 450 | 293 | **0.6511** | [0.6060, 0.6937] |
| generated - frozen (points) | -- | -- | **+37.61** | -- |

### 7.1 Per target, generated block, commissioned arm

| target | strict | rate | 95 % CI | band entry | top failure reasons |
|---|---|---|---|---|---|
| `bench` | 65/90 | 0.7222 | [0.622, 0.804] | 0.8222 | `semantic_target_unreachable` x22, `navigation_no_progress` x3 |
| `lamppost` | 75/90 | 0.8333 | [0.743, 0.896] | 0.8333 | `navigation_no_progress` x8, `semantic_target_unreachable` x7 |
| `planter` | 63/90 | 0.7000 | [0.599, 0.785] | 0.7333 | `navigation_no_progress` x14, `semantic_target_unreachable` x10, `arrived_verified` x2 |
| `sidewalk` | 84/90 | 0.9333 | [0.862, 0.969] | 0.9333 | `semantic_target_unreachable` x5, `navigation_no_progress` x1 |
| `crosswalk` | 6/90 | 0.0667 | [0.031, 0.138] | 0.1222 | `navigation_no_progress` x42, `arrived` x42 |

### 7.2 Goal-band clearance vs outcome (commissioned arm, generated block)

| best standable clearance inside the goal band | episodes | strict success rate |
|---|---|---|
| 1.00-2.00 m | 276 | 0.7572 |
| >=2.00 m | 174 | 0.4828 |

### 7.2b Is `semantic_target_unreachable` an inflation effect?

| quantity | value |
|---|---|
| live planner inflation, centre-to-surface (m) | 1.0223 |
| band surface clearance the planner therefore demands (m) | 0.7023 |
| `semantic_target_unreachable` episodes | 49 |
| their goal-band best clearance, min (m) | 1.0 |
| their goal-band best clearance, median (m) | 1.4238 |
| of those, below the planner's demand | 0 |
| all 450 episodes: goal-band best clearance, min (m) | 1.0 |
| all 450 episodes: below the planner's demand | 0 |

### 7.3 Reconciliation with MA-1's 4.5 %

| quantity | value |
|---|---|
| episodes | 450 |
| strict success, 1800-step budget | 0.6511 |
| band entry, 1800-step budget | 0.6889 |
| band entry within MA-1's 420-frame per-goal budget | 0.6778 |
| median steps | 170 |
| MA-1 held-out teacher SR | 0.045 |

### 8.1 Host and run provenance (rendered, never typed)

| when | loadavg (1/5/15) | cpus | GPU (used / total, util) | UTC |
|---|---|---|---|---|
| sweep A start | 12.94 / 23.51 / 16.13 | 192 | 2058 MiB, 32760 MiB, 25 % | 2026-08-30T00:38:51Z |
| sweep A end | 3.95 / 12.86 / 17.14 | 192 | 2031 MiB, 32760 MiB, 25 % | 2026-08-30T00:52:07Z |
| sweep B start | 2.91 / 10.08 / 15.73 | 192 | 2030 MiB, 32760 MiB, 27 % | 2026-08-30T00:53:45Z |
| sweep B end | 15.04 / 23.44 / 21.07 | 192 | 2026 MiB, 32760 MiB, 41 % | 2026-08-30T00:57:42Z |

| quantity | value |
|---|---|
| sweep A wall (s) | 530.4 |
| sweep B wall (s) | 236.6 |
| workers | not recorded |
| BLAS threads per worker | not recorded |
| provenance note | NOT RECORDED by the run that produced these rows — run.py records it from this commit on, and RESULTS.md says 'not recorded' rather than repeating one of the three hand-typed values (24/32/40) |
