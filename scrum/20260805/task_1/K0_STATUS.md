# K0 status — Goal-calibration fix

**Card:** K0 (kickoff board, ADJUDICATION D5)  
**Date:** 2026-08-05  
**Lane:** Opus (existing files)  
**Constraint:** hardware last; no Nav2 migration  
**Arbitration:** Fable upheld Sol REQUEST CHANGES → B1 + S1 + S2 applied

## Verdict

One **GoalRegion** arrival authority is now shared by city semantics, navigator
terminal verification, and the NAV_INSTRUCT scorer — including **`next_to`**
(full object `radius_m`, no generator ×0.5 shrink). Step-limit expiry while
inside that region attributes **L6 termination**, and terminal L6 now beats
stale earlier `planning_error` flags.

## Arbitration must-fixes (2026-08-05)

| ID | Fix |
|---|---|
| **B1** | `evals/nav_instruct/generator.py::_relative_goal` now builds episode goals via `arrival_goal_region_for_relation("next_to", …)` with full `landmark["radius_m"]`. Pipeline + `safe_approach_pose` already used full radius; left aligned. |
| **S1** | `_classify_failure` precedence is now refusal → grounding → search → **control** → **termination** → planning. Terminal `navigation_step_limit_inside_goal` / `termination_error` + inside/ever-inside + step_limit returns `FailureClass.TERMINATION` before stale `planning_error`. |
| **S2** | Minival freeze appended under `scrum/20260805/task_1/freeze/` (`nav-instruct-baseline-k0.json` + report). `20260804/task_6` freeze untouched. |

## Arrival contract

| Consumer | Authority |
|---|---|
| `city_semantics` object metadata | `object_near_goal_region` → `metadata["goal_region"]` (`relative_band`) |
| `DirectiveNavigator` | `mission.metadata["arrival_goal_region"]` from `arrival_goal_region_for_relation`; for object relations, geometric arrive **or** `GoalRegion.contains` enters verifying (`inside` keeps approach-pose trigger + clearance verify) |
| Semantic terminal check | Must be inside `arrival_goal_region`; `near` still applies surface/support clearance |
| NAV_INSTRUCT generator / scorer | Same builders (`object_near_*`, `object_towards_*`, `arrival_goal_region_for_relation` / `object_next_to_*`, `region_inside_*`) |

**Relation bands (constants in `instructnav/scoring.py`):**

- `near` — `[minimum_vicinity_m, vicinity_m]` via `object_near_envelope_m` (lamppost historical stand-off 1.32 m stays inside the band)
- `next_to` — `NEXT_TO_BAND_M = (0.4, 1.5)` with **`anchor_footprint_m = full radius_m`**
- `towards` — `TOWARDS_BAND_M = (0.6, 2.5)`
- `inside` — polygon GoalRegion

**Retired disagreement:** navigator default `arrive_radius_m=1.5` is no longer a
semantic success definition; approach-pose radius remains a *controller*
tolerance only. Eval no longer uses the ad-hoc `landmark_radius + 1.4`
(~1.46 m) disc. Eval no longer shrinks `next_to` footprint by ×0.5.

## Step-limit audit

- `evals/nav_instruct/runner.py`: on max-steps, if final pose is inside the
  episode GoalRegion → reason `navigation_step_limit_inside_goal` +
  `termination_error` on the trace.
- `headless_city.py`: same reason when mission `arrival_goal_region` contains
  the final pose (S3 accepted: structured flags stamped by NAV_INSTRUCT runner).
- `score_episode` / `_classify_failure`: inside / ever-inside + step-limit →
  `FailureClass.TERMINATION` → `AttributionLayer.L6_TERMINATION`, including when
  an earlier sample set `planning_error` / `unreachable`.

## Re-freeze (S2 done)

Minival baseline freeze executed after B1+S1 green:

```bash
.parcel/bin/python -m evals.nav_instruct.run_nav_instruct_v1 \
  --minival --mode baseline --freeze \
  --out evals/nav_instruct/results
```

Artifacts (new only; do not rewrite `20260804/task_6`):

- `scrum/20260805/task_1/freeze/nav-instruct-baseline-k0.json`
- `scrum/20260805/task_1/freeze/nav-instruct-baseline-k0-report.json`

| Field | Value |
|---|---|
| `runner_version` | `nav-instruct-v1.1-k0-arrival` |
| `k0_arrival_authority` | `GoalRegion` |
| `n` / `minival` | 25 / true |
| `sr` | 0.04 |
| `failure_histogram.termination` | 4 (L6 path present; not collapsed into planning-only) |
| `does_not_prove` | sim-semantics ≠ camera; absent-target open-vocab; VLM/VLA |

Full-matrix promote freeze still optional when replacing the historical baseline.

## Tests

- `tests/test_k0_arrival_authority.py` — near agreement; **next_to bench/planter
  eval ↔ pipeline ↔ approach footprint**; step-limit → L6; **S1 precedence**
  (earlier planning_error + terminal inside-goal → TERMINATION)
- `tests/test_instructnav_scoring.py` — pass-through goal → TERMINATION
- `tests/test_city_semantics.py` — object `goal_region` is `relative_band`

Focused run (2026-08-05): **21 passed**.

## Files touched

- `src/parcel_robot/instructnav/scoring.py`, `__init__.py`
- `src/parcel_robot/city_semantics.py`
- `src/parcel_robot/navigation/pipeline.py`, `approach.py`
- `src/parcel_robot/headless_city.py`
- `evals/nav_instruct/generator.py`, `runner.py`, `run_nav_instruct_v1.py`
- `tests/test_k0_arrival_authority.py`, `test_instructnav_scoring.py`,
  `test_city_semantics.py`
- `scrum/20260805/task_1/K0_STATUS.md`, `freeze/README.md`,
  `freeze/nav-instruct-baseline-k0.json`, `freeze/nav-instruct-baseline-k0-report.json`
