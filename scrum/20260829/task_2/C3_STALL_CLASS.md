# C3 · STALL-CLASS-1 — `navigation_no_progress` with the route still planned

**Executor:** Opus · **Verifier:** Fable · **Second lens:** parcel-fb · **Wave:** A

## Defect (NAV-GEN-1; NAV-CORE's stall class)

68/157 strict failures on generated scenes end `navigation_no_progress`: the progress watchdog (`navigation/pipeline.py:4634-4656`) fires after semantic replans are exhausted with `mission.status = failed`, `resolution_state = stalled`, while the route is still `status=planned`. 42 of the 68 are the C1 POI defect; **26 non-POI stalls remain unattributed**, and `semantic_target_unreachable` (44 strict, 22 on bench) is shown NOT to be inflation (0 of 49 goals below the planner demand) but otherwise unexplained. Clearance is not the lever: the planner is commissioned from the brake ring (`pipeline.py:1108-1120`, inflation 1.02 m; `grid.yaml map_safety_margin_m` inert in effect), and sweeping the brake 0.80 → 0.32 m buys +2 points while breaching the stop-band clause. NAV-CORE's "planner 0.42 m / margin 0.45 recovered stalls" is pre-A2 and does not transfer. Evidence: `nav-gen-attribution-1/{VERDICT.md §2, §5.2, §5.3; RESULTS.md §5.1, §7.2b}`.

## Build

1. **Attribute first** (research-tier, in the card's own scratch): for the 26 non-POI stalls and the 44 unreachable, log per step: planned-path length, distance to next waypoint, minimum LiDAR clearance vs brake ring (0.8 m body-surface) vs planner inflation (1.02 m centre), whether the brake zeroed the command while the planner still had a route, replan count. Produce a histogram with one example per class; this is the STATUS file's first section and gates the fix.
2. **Fix the dominant class** as a leaf module (`navigation/stall_attribution.py` or the class's natural home; `pipeline.py` net-negative): expected candidates are (a) brake ring < planner inflation mismatch at corridor mouths (the A2 "one clearance authority" gap in the other direction), (b) the watchdog counting brake-held ticks as no-progress, (c) waypoint reached-tolerance vs inflation. Do NOT change `obstacle_stop_m`, `stop_distance_m`, or any floor; if the honest fix is a value change, stop and write it up for the owner (re-freeze policy).
3. Correct `results.json` `arm_config_facts` (A0–A4 rows carry the pre-A2 schema `planner_inflation_radius_m 0.42` with `map_gate_clearance_m: null`) — research file, `nav-gen-attribution-1/analyze.py` — so the record reads the live inflation.

**Shared-file rule:** C1 also edits `navigation/pipeline.py` (the `parse` hook only). Before touching `pipeline.py`, run `git diff --stat src/parcel_robot/navigation/pipeline.py` and confine your edit to the watchdog region (~4634-4656) + the leaf import; never reformat the file.

## Acceptance (verbatim bars)

- RED: NAV-GEN-1 `--arms A0` reproduces 68 `navigation_no_progress` / 44 `semantic_target_unreachable` (or their post-C1 counts if C1 has landed — record which).
- GREEN: non-POI stall count **halves** (≤ 13 of the 26, or ≤ half of the post-C1 count) at **0 collisions** and **no increase** in episodes below the 0.65 m stop band (A0 has 1); every other reason count unchanged or improved; frozen NAV_INSTRUCT digest unchanged.
- `test_nav_core*.py` / `test_a2_*.py` / `test_grid_*` subsets green through the guard (list them in STATUS).
- The attribution histogram is in STATUS before any product line changes.

## Does not prove
Anything off-oracle or physical; the residual ~10-point MA-1-vs-NAV-GEN-1 difference (different episodes) is out of scope.

## Amendment A1 (21:5x, parcel-fb's second lens — binding; tightens, does not loosen)

Candidate (b) "the watchdog counting brake-held ticks as no-progress" carries a real hazard: NAV-ACCEPT found the R3 silent stall ALIVE; exempting brake-held ticks can trade a loud `navigation_no_progress` for a robot that sits blocked forever with `status=planned`. Any exemption needs a **hard tick cap and its own terminal reason** (e.g. `brake_held_timeout`). **GREEN row added:** no episode ends with `status=planned` and no terminal reason (scan all 450 + 80 rows). Halving is a bar the fix must earn from attribution, not from loosening the watchdog.
