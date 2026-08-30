# AUDIT · W6 VALUE-CHANGES-MEASURED-1 — verifier: Fable (parcel-0e), 07:4x 08-30

**Disposition: ACCEPT as a measurement (research only; nothing flipped).** Files: `research/20260830/value-changes-1/{DESIGN.md (pre-registered 06:43), RESULTS.md, results.json, tables.md, values_harness.py, analyze_values.py, door_reach.py}`; ruff clean; 0 `noqa`; no product/config/eval file written (the worktree's status is `research/20260830/` only); `results.json` arms `{A0ref, off_disc, on_disc, off_full, on_full}` with the plumbing control `A0ref` byte-identical to `off_disc` (530/530, minival digest, panel) — the arms are licensed.

## The decision table (from the register; verifier read the JSON keys and the control)

| | shipped | V1 release door ON | V2 planner 1.12 m | V1+V2 |
|---|---|---|---|---|
| strict / settled (450 gen) | 343 / 339 | 343 / 339 | 351 / 346 | 350 / 345 |
| `arrived_verified` | 295 | 300 | 307 | 316 |
| `navigation_no_progress` / `semantic_target_unreachable` | 49 / 62 | **10** / 95 | 32 / 66 | **2** / 87 |
| collisions | 0 | 0 | 0 | 0 |
| **episodes < 0.65 m / worst clearance** | 1 / 0.6275 | 1 / 0.6275 | **4 / 0.5837** | **3 / 0.5837** |
| v4 minival digest | `021b67ab…` | **unmoved** (0 rows) | moved (3 rows, 0 verdicts) | moved |
| mutation panel | pass {4,1} | identical | pass, 2 clean rows moved, gate mutant 3 channels | same |
| frozen demo rows moved (80) | — | 1 | **34** | 34 |

## Verifier's recommendation to the owner (the "frozen" decisions on these two values)
- **V1 (release door ON on the shipped profile): do not enable yet, and the reason is not E3.** The frozen minival and panel move by zero — but `door_reach.py` shows `held_release_due` is called **0 times** across all 25 minival episodes: `max_steps 200 == progress_watchdog.timeout_steps 200`, so the frozen corpora are **structurally blind** to the flag. "No frozen move" is evidence about the step budget, not about the door. Enabling it is defensible only after a corpus in which the watchdog can fire exists (raise `max_steps` for a dedicated tier or add a stall family), and then under the re-freeze policy. AUDIT_C3 §4.1's "NOT MEASURED" is now measured with that caveat.
- **V2 (planner demanding the full 1.12 m): NO.** +8 strict and fewer stalls, but < 0.65 m exposure rises 1 → 4 with the worst clearance **0.5837 m — below the 0.65 m stop band** — and 34/80 frozen demo rows move (four regressions on bench/planter/sidewalk against gains on crosswalk/lamppost). A value that trades stalls for stop-band exposure is a safety-floor question, not a re-freeze; the honest successor is the "directional inflation" design question C3 §2 named, not the full demand.
- Found for free: the 1.12 m demand needs no product edit to measure (`controller.map_hard_safety_margin_m: 0.80` reaches `inflation_radius_m == 1.12` through the first arm of the `max` at `grid_planner.py:339-341`; the line a real change would touch is `:341`, the `sin θ` term) — and C3 §F1.3 reproduced independently (48/530 rows, 2/2 strict, same four episodes).

## Notes
- The first analysis pass compared whole row dicts including each row's own `arm` label and read 530/530 changed for every arm, control included — caught by the plumbing control, recorded in both docs. Good.
- Worktree `~/.cache/parcel-0e/wb/w6` is prunable; raw rows in `~/.cache/parcel-0e/w6/`.
