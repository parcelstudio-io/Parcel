# Arbitration — K0 (Sol REQUEST CHANGES on Opus)

**Date:** 2026-08-05  
**Arbiter:** Fable (Claude Fable stand-in; API-limited)  
**Inputs:** [ADJUDICATION.md](ADJUDICATION.md) D5, [K0_STATUS.md](K0_STATUS.md),
[REVIEW_SOL_ON_OPUS.md](REVIEW_SOL_ON_OPUS.md); code verification of B1.  
**Scope:** K0 gate only. K1 / K2′ assessed for clearance against this gate.

## Verdict

**Uphold Sol: REQUEST CHANGES. K0 is not APPROVED until B1 and S1 land, then
the documented re-freeze (S2) runs.**

D5 requires **one** arrival authority shared by navigator, semantics, and
scorer. Sol’s B1 is **factually true** (verified): for `next_to` / bench_1,
eval footprint is `0.35` and pipeline footprint is `0.7`; at center-distance
`0.50 m`, episode `GoalRegion.contains` is True and mission
`arrival_goal_region.contains` is False. That is two authorities. Fix it.

K2′ is **clear** for this gate. K1 is **clear** for this gate (separate card;
not blocked by K0 findings).

---

## Binding decisions

| ID | Finding | Decision |
|---|---|---|
| **B1** | `next_to` footprint: generator `radius×0.5` vs pipeline/approach full `radius_m` | **BINDING must-fix** |
| **S1** | `_classify_failure` lets earlier `planning_error` beat terminal step-limit-inside-goal | **BINDING must-fix** |
| **S2** | K0 re-freeze artifact missing | **BINDING must-fix** (after B1+S1; do not freeze before) |
| **S3** | Headless step-limit only rewrites `reason`, no structured flags | **accept** for this gate |
| **N1** | Region `goal_region` inlined vs `region_inside_goal_region` | **accept** |
| **N2** | Oracle denylist name-based / incomplete aliases | **accept** (MVP; extend at HR-8) |
| **N3** | `--freeze` sets `frozen_baseline: True` immediately | **defer** (optional polish; not gate-blocking) |
| **N4** | Default `arrive_radius_m=1.5` retained as controller tolerance | **accept** |

---

## B1 — BINDING must-fix (verified)

### Evidence

| Site | Footprint for `next_to` / bench_1 (`radius_m=0.7`) |
|---|---|
| `evals/nav_instruct/generator.py::_relative_goal` | `radius_m * 0.5` → **0.35** |
| `instructnav/scoring.py::arrival_goal_region_for_relation` (`relation=="next_to"`) | `meta["radius_m"]` → **0.7** |
| `navigation/approach.py::safe_approach_pose` (`terminal_relation=="next_to"`) | `candidate.metadata["radius_m"]` → **0.7** |

`GoalRegion.contains` for `relative_band` requires `dist >= anchor_footprint_m`
and band membership. At distance `0.50 m` with `NEXT_TO_BAND_M=(0.4, 1.5)`:

- eval / scorer: **contains True**
- navigator arrival region: **contains False**

`tests/test_k0_arrival_authority.py` locks **near**/lamppost only — no
`next_to` cross-check. K0_STATUS’s “one GoalRegion” claim is therefore false
for the full relation set.

### Authority rule (binding)

**Unify on full object `radius_m` as `anchor_footprint_m` / approach footprint
for `next_to`.** Pipeline + approach already agree; the generator `×0.5` shrink
is the outlier and is **struck**. Do not invent a third shrink factor.

Eval episode goals for `object_relative` / `next_to` must be built by the same
helper the navigator uses (`arrival_goal_region_for_relation` / 
`object_next_to_goal_region` with full radius), not a parallel footprint path.

---

## Exact Opus remediation

### 1. B1 — unify `next_to` footprint (required)

1. In `evals/nav_instruct/generator.py::_relative_goal`, **remove**
   `footprint = float(landmark["radius_m"]) * 0.5`.
2. Pass **full** `float(landmark["radius_m"])` into
   `object_next_to_goal_region`, **or** (preferred) build the episode goal via
   `arrival_goal_region_for_relation("next_to", center=..., object_radius_m=...,
   entity_id=..., metadata={"radius_m": ...})` so generator and pipeline cannot
   diverge again.
3. Confirm `arrival_goal_region_for_relation` and `safe_approach_pose` already
   use full `radius_m` — leave them aligned; do not reintroduce a half-radius
   shrink in approach.
4. Extend `tests/test_k0_arrival_authority.py`:
   - For `bench_1` and `planter_1`, assert eval `_relative_goal` ↔
     `arrival_goal_region_for_relation("next_to", ...)` equality on
     `center`, `band_m`, and `anchor_footprint_m`.
   - Assert a concrete disagreement case is gone: e.g. bench center-distance
     `0.50 m` is **outside** both regions (footprint `0.7`), and a point at
     e.g. `1.0 m` is **inside** both.
   - Optionally assert approach’s next_to footprint source
     (`metadata["radius_m"]`) equals that same `anchor_footprint_m`.
5. Re-run: `tests/test_k0_arrival_authority.py`,
   `tests/test_instructnav_scoring.py`, `tests/test_city_semantics.py`.

### 2. S1 — terminal L6 beats earlier planning flags (required)

1. In `instructnav/scoring.py::_classify_failure`, when the terminal condition
   is step-limit-inside-goal / termination+inside:
   - `flags["termination_error"]`, or
   - `"navigation_step_limit_inside_goal"` in texts, or
   - `(ever_inside or inside_final)` and (`flags["step_limit"]` or
     `"navigation_step_limit"` in texts),
   
   return **`FailureClass.TERMINATION` before** the
   `planning_error` / `unreachable` / `no_route` branch.
2. Keep refusal → grounding → search ahead of both. Control/collision still
   outranks termination if both are present (safety > attribution nicety).
3. Add a regression in `test_k0_arrival_authority` (or scoring tests): a trace
   with an earlier `planning_error`/`unreachable` sample **and** a final
   `navigation_step_limit_inside_goal` / `termination_error` + inside pose
   must score **`FailureClass.TERMINATION` / `L6_TERMINATION`**, not
   `PLANNING_ERROR`.

Rationale: K0’s purpose under D5 is that near-miss timeouts inside the
GoalRegion are L6, not planning. Precedence that lets a stale planning flag
win reopens the exact mislabel the card was written to kill.

### 3. S2 — honest re-freeze (required after 1–2)

1. **Do not** freeze until B1 and S1 are green.
2. Run the documented minival (and matrix when promoting) with runner
   `nav-instruct-v1.1-k0-arrival` per `freeze/README.md`.
3. Append a **new** freeze JSON + ledger line under
   `scrum/20260805/task_1/freeze/` (and/or evals ledger).
4. **Do not** rewrite `scrum/20260804/task_6/freeze/nav-instruct-baseline*`.
5. Keep `does_not_prove` honest (sim-semantics ≠ camera perception).

### 4. S3 — accept (no required change)

Headless `_run_navigation` rewriting `reason` only is acceptable for this gate
because NAV_INSTRUCT attribution goes through `evals/nav_instruct/runner.py`,
which already stamps structured flags. If headless traces later feed
`score_episode`, stamp `termination_error` / `step_limit` in parity with the
runner — out of K0 must-fix scope.

### 5. Nits

- **N1 accept:** behavior matches; optional later cleanup to call
  `region_inside_goal_region`.
- **N2 accept:** MVP denylist fine; extend aliases when real bags land (HR-8).
- **N3 defer:** prefer `--freeze` write `frozen_baseline: false` until owner
  acceptance; polish only, not a K0 blocker.
- **N4 accept:** controller approach-pose tolerance may keep `1.5`; tests must
  continue rejecting the legacy eval disc.

---

## Gate clearance

| Card | This gate |
|---|---|
| **K0** | **Not clear** — B1 + S1 + post-fix S2 required for APPROVE |
| **K1** | **Clear** — pure contract RFC/tests delivered; Fable RFC field review and Opus wiring are later/out-of-lane, not this K0 gate |
| **K2′** | **Clear** — bag schema/recorder/replayer, oracle rejection, HR-1…HR-9 ledger, draft ADRs; Sol’s pass stands; no must-fixes |

---

## Bottom line for Opus

Fix the generator’s `next_to` half-radius (unify on full `radius_m` / shared
builder), make terminal step-limit-inside-goal win over stale planning flags,
add the missing agreement + precedence tests, **then** append the K0 freeze
row. Until that lands, D5 is not satisfied and K0 stays REQUEST CHANGES.
