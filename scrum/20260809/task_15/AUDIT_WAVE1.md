# Wave-1 audit — 2026-08-09

> Full five-card wave audit NOT started (other cards still running). This file
> currently contains only the early cross-card arbitration for S-A.

## S-A early arbitration

**Arbiter:** Fable (early arbitration, requested before wave completion)
**Trigger:** S-A_STATUS.md STOP by Sol (`fe683adf-abd2-4ed6-8c50-155c9e4bf17f`)
**Verdict: SPLIT** (binding)

### Independent verification of Sol's locus claims (refute-first)

I attempted to refute each claim by reading the cited code, not the status doc.
All three claims survived; I additionally found the card's OWNS block was
internally inconsistent from the moment it was written.

**Claim 1 — P0-A locus is runtime.py (forbidden): CONFIRMED, and the defect is
real.** The dispatch pipeline is `runtime.py::_dispatch_active` (line 4375):
`velocity_smoother.step` → `_collision_safe` (reactive gate + TTC gate) →
`velocity_smoother.force` → `_shape_for_actuator` → `control_manager.set_target`.
On a stop decision, `_shape_for_actuator` calls
`SCurveVelocityShaper.step(..., emergency=True)` — and that path
(`navigation/velocity_shaping.py:102-105`) does **not** snap to zero; it ramps:
`_move_toward(velocity, 0.0, limits.max_accel * dt_s)`. With the default
`linear_max_accel=1.2` and dt clamped to ≤0.25 s, a 0.5 m/s command survives a
hard stop decision for one or more dispatched ticks as a nonzero
`set_target`. The comment at runtime.py:4411-4413 ("Stops route to the
emergency bypass so no stop decision is ever smoothed") is contradicted by the
code it annotates. P0-A's property — "the next dispatched command is exactly
zero" — is violated at the `set_target` boundary. Fix loci: `runtime.py`
(pipeline wiring, where a final zero-enforcing monitor must sit) and
`navigation/velocity_shaping.py` (emergency semantics). Both are MUST-NOT-TOUCH
for S-A; runtime.py is C-A-exclusive this wave (plan rule 5).

**Claim 2 — P0-B locus is navigation/reactive_safety.py (forbidden):
CONFIRMED, and the defect is real.** `apply_reactive_safety`
(`navigation/reactive_safety.py:43`) fails closed for `observation is None`
(line 55) and for stale telemetry (line 58), but a *present* observation with a
*missing scan* — empty `lidar_obstacles` and `nearest_obstacle_m is None` —
falls through to `if not toward_obstacle or distance is None: return command,
predictive_state` (line 152): the translation command passes unshaped. Missing
scan data is treated as "clear", the exact silently-satisfied-sensor case P0-B
forbids. This is the live final gate (called from `runtime.py::_collision_safe`
line 5251 on every dispatch tick), so the fix cannot land anywhere else.

**Claim 3 — a core-only parallel implementation would not change the product
path: CONFIRMED, with a sharper finding.** The card's OWNS line reads
"`src/parcel_robot/core/**` (collision.py, reactive_safety.py, authority.py,
arbiter.py — the safety core)". **`core/` contains no collision.py and no
reactive_safety.py.** Those two files live in `navigation/`, which the same
card forbids. The card OWNS parenthetical was wrong when written; the "safety
core" the card intended to own is split across `navigation/**` and
`runtime.py`. Also verified: `core/motion_shaping.py` is config-only (the
shaper implementation is `navigation/velocity_shaping.py`), and
`core/velocity_smoother.py` already exposes the `force()`/`reset()` primitives
— the smoother is not the residual-velocity source. A core-only "fix" would be
dead code claiming live blockers closed. Sol's STOP was correct under plan
rule 6 (honesty) and is upheld. **OVERRIDE is rejected.**

### Ruling: SPLIT

S-A lands the pure core safety boundary this wave; a new opus card wires it
after C-A releases runtime.py. This follows the plan's own orchestration model
(Sol = pure modules with frozen contracts; Opus = existing-file wiring) and
respects rule 5 (runtime.py has ONE owner per wave — C-A keeps it).

**S-A (Sol, resume now, Wave 1) — corrected scope, additive core/** only:**
1. Pure final-stop monitor module (suggested `core/hard_stop.py`): given
   intervention severity + candidate command, emits exactly `(0,0,0)` on hard
   intervention (translation-only zero with preserved vyaw remains the
   convention for proximity stops), and defines the reset contract for every
   downstream shaper/smoother stage. Property tests: model the
   smoother→gate→shaper pipeline, interrupt at every stage, assert the next
   command is exactly zero.
2. Pure fail-closed input-health module (suggested `core/input_health.py`):
   required-input table (pose, scan, controller feedback) with
   freshness/frame-consistency requirements → HOLD or latched STOP by
   severity; sim geometry only via an explicitly labeled fixture. Property
   tests: every missing/stale/malformed/frame-inconsistent combination forbids
   translation.
3. Frozen module contracts written down in the status doc so the wiring card
   is mechanical. MUST-NOT-TOUCH unchanged. Mutation-panel additions for the
   new modules per the original card. ci_gate green.
4. S-A's status doc MUST state that P0-A/P0-B remain OPEN on the product path
   after S-A lands. S-A landing is a boundary, not a fix.

**S-A2 (new card, opus, Wave 2) — the wiring, carries the original S-A gate:**
- Deps: C-A merged (runtime.py freed), S-A merged.
- OWNS: `runtime.py` (`_dispatch_active`, `_shape_for_actuator`,
  `_collision_safe`), `navigation/velocity_shaping.py` (emergency path becomes
  exact-zero or is superseded by the hard_stop monitor at the set_target
  boundary), `navigation/reactive_safety.py` (missing-scan fail-closed via
  input_health), + tests.
- GATE (transferred verbatim from S-A): property tests on the *live* pipeline
  green; mutation panel — new mutants killed; safety pins untouched-green; any
  frozen-row movement is STOP-and-report; ci_gate green. Only S-A2 may claim
  P0-A/P0-B closed.
- Sequencing: S-B (proximity unification) touches
  authority/collision/reactive_safety and MUST be dispatched after S-A2 or
  yield per rule 5 (later dispatch yields).

### does_not_prove (this arbitration)

- Does not prove the residual-nonzero command reaches the *actuator*: I read
  `_dispatch_active` end-to-end (no zeroing between shaper and
  `control_manager.set_target`) but did not audit `control/manager.py`
  internals; a manager-side clamp for latched e-stop would not cover
  proximity/collision stops in any case, so the P0-A property is violated at
  the set_target boundary regardless.
- Does not prove these are the *only* P0-A/P0-B defect sites (e.g. the TTC
  gate's scale-to-zero path and pose/feedback staleness handling were not
  exhaustively audited); that audit belongs to S-A2 with the live pipeline in
  scope.
- Static reading only — no reproducing test was run (implementation is
  explicitly out of scope for this arbitration).

---

## Wave-1 full audit

**Auditor:** Fable stand-in (Claude Fable agent `d6986114` hit API limit with
zero audit progress; this section is the stand-in run of the pre-registered
protocol in `NEXT_BATCH_PLAN.md` § Fable audit protocol).
**When:** 2026-08-09T22:37Z (ci_gate) / gates re-run same session.
**Base HEAD:** `60ecea24168f839cb107a818799d0bc424bfee1d` (dirty wave tree).

### 1. Fresh `scripts/ci_gate.py --tier commit`

```
CI GATE — tier=commit  (2026-08-09T22:37:01Z)
[  PASS] HARD  ruff                       7 violation(s), baseline 7, new 0
[  PASS] HARD  hard-safety                … walk_with_me: 1/2 row(s) with hard_collision_total, all 0 = True
[  PASS] HARD  frozen-digest-sentinels
[  skip] HARD  latency-tail-ledger        ledger rows=1 < window=5; ratchet skipped
[  PASS] HARD  model-off-non-inferiority
[  PASS] HARD  frozen-digest-integrity
[  PASS] HARD  mutation-panel-freshness
[  PASS] HARD  latency-tail
[  PASS] HARD  default-suite              3210 passed, 9 skipped, 34 deselected
RESULT: PASS — every hard gate green.  elapsed 101.2s
```

**Wave not returned for CI.** Habitat smoke (pre-dispatch sole red in
`DISPATCH_WAVE1.md` / C-A status) was **not** red on this fresh run — no
habitat attribution needed.

### 2–4. Per-card ownership / named gate / adversarial

#### V-A — CONFIRMED

- **OWNS held:** diffs/new files only
  `camera_channel/ingress.py`, `tests/test_runtime_activation.py`,
  `scrum/20260809/task_12/b4_gate.py`, `evals/nav_instruct/cam_arrival.py`,
  `tests/test_cam_arrival.py`. MUST-NOT clean (`instructnav/scoring.py`,
  `navigation/**`, `detection_adapter/**`, existing `cam_foundation.py` /
  `cam_detector.py` unmoved). `runtime.py` dirty belongs to C-A.
- **Named gate (independent):**
  `MUJOCO_GL=egl PARCEL_OWLV2_ONNX=1 .parcel/bin/python scrum/20260809/task_12/b4_gate.py A`
  → `arrival=succeeded`, `candidate_source=pixel_detector`,
  `mission_status=arrived` / `arrived_verified`, localization error ≈ 0.035 m.
- **Note (non-blocking):** plan text mentioned “pack entry as a new file”;
  delivered cell is pack-free offline envelope evidence (`cam_arrival.py`).
  Live b4 gate is the card GATE; no RETURN for pack absence.

#### V-B — CONFIRMED

- **OWNS held:** additive only
  `detection_adapter/multi_view_confirm.py`,
  `detection_adapter/metric_localizer.py`,
  `evals/nav_instruct/cam_multiview_metric.py`,
  `tests/test_vb_multiview_metric.py`. MUST-NOT clean (no
  `camera_channel/**`, no frozen pack edits, no `cam_arrival.py`).
- **Named gate:**
  `.parcel/bin/python -m pytest -q tests/test_vb_multiview_metric.py`
  → **10 passed**.
- **Note:** status-doc ci_gate FAIL (ruff on S-A `hard_stop`) was
  cross-card residue at write time; fresh wave ci_gate is green. Live EGL
  lamppost cell remains guarded/non-CI per plan — not required for this
  confirm.

#### V-C — RETURNED-with-findings

- **Named gate green:**
  `.parcel/bin/python -m pytest -q tests/test_semantic_value_map.py`
  → **9 passed**. Pure cone/fusion math looks present.
- **Ownership FAIL vs plan OWNS:**
  - Plan OWNS: `src/parcel_robot/navigation/value_map.py` +
    `tests/test_value_map.py` (named for Wave-2 C2/C3 stable import).
  - Delivered instead:
    `src/parcel_robot/instructnav/semantic_value_map.py` (new),
    `tests/test_semantic_value_map.py` (new).
  - Named OWNS paths **absent**. No existing file edited, but the card
    landed **outside** its OWNS list under `instructnav/**`.
- **Redispatch (V-C / Sol):** move (or re-export as the sole public surface)
  to exactly
  `src/parcel_robot/navigation/value_map.py` and
  `tests/test_value_map.py`; remove or thin-wrap the instructnav path so
  Wave-2 cites the pre-registered import; re-run the unit gate + commit
  ci_gate; update `V-C_STATUS.md`.

#### S-A — CONFIRMED (boundary; SPLIT)

- **SPLIT scope held:** additive
  `core/hard_stop.py`, `core/input_health.py`,
  `tests/test_core_hard_stop.py`, `tests/test_core_input_health.py` only.
  `runtime.py` / `navigation/**` not edited by S-A (runtime dirty = C-A).
- **Named gate:**
  `.parcel/bin/python -m pytest -q tests/test_core_hard_stop.py tests/test_core_input_health.py`
  → **43 passed**.
- **Adversarial (refute-first):**
  - Status correctly states **P0-A / P0-B remain OPEN** on the product path.
  - `runtime.py` / `reactive_safety.py` do **not** import `hard_stop` /
    `input_health` (boundary only; unwired).
  - Reproduced P0-B still open: `apply_reactive_safety` with empty
    `lidar_obstacles` + `nearest_obstacle_m=None` returns
    `VelocityCommand(vx=0.4, …)` / `"clear"` (missing scan still treated as
    clear at `reactive_safety.py:152-153`).
  - Frozen rows / `scripts/mutation_panel.py`: **UNMOVED** (no frozen-row
    claim to refute).
  - **Accepted exception:** mutation-panel seeding deferred to S-A2 with
    documented honesty (unwired modules would create surviving mutants).
    Consistent with SPLIT “boundary, not a fix.”
- Only S-A2 may claim P0-A/P0-B closed (`S-A2_CARD.md`).

#### C-A — CONFIRMED

- **OWNS held:** `runtime.py`, `observability.py`, `ui/latency.html`
  (metricNames only — verified), `evals/latency/*` (new), walk_with_me
  harness + ledger fields, `scripts/ci_gate.py`, ruff baseline re-pin
  39→7, plus ruff burn-down in non-excluded trees (storefront/uwb/
  route_memory/bags/voice/tests/tools/etc.). MUST-NOT clean for
  `core/**` sources, `detection_adapter/**`, S-A safety files,
  `voice_pipeline.py`. `camera_channel/**` / `test_runtime_activation.py`
  dirty = V-A, not C-A.
- **Named gate:**
  - `tests/test_acoustic_defects.py::test_n19_runtime_fans_in_acoustic_clocks_on_duplex_voice_path` PASS
  - `tests/test_ci_gate.py::test_latency_ledger_reddens_on_seeded_spike` PASS
  - ledger rows=1 `<` baseline window=5 → latency-tail-ledger skip (by design)
- Habitat sole-red claim in C-A status is superseded by this audit’s green
  default-suite; no C-A ownership issue.

### 5. Cross-card / overall

| Card | Verdict | Gate result | Ownership |
|---|---|---|---|
| V-A | **CONFIRMED** | b4 Mission A `arrival=succeeded` / `pixel_detector` | OK |
| V-B | **CONFIRMED** | `test_vb_multiview_metric` 10 passed | OK |
| V-C | **RETURNED** | `test_semantic_value_map` 9 passed | **path ≠ OWNS** |
| S-A | **CONFIRMED** (boundary) | hard_stop+input_health 43 passed; P0 OPEN | OK (SPLIT) |
| C-A | **CONFIRMED** | N19 duplex + latency ledger self-test | OK |

### Overall: **WAVE RETURNED**

Not WAVE CONFIRMED — V-C ownership path deviation is blocking.

**Redispatch instructions**
1. **V-C only** — relocate SemanticValueMap2D to the pre-registered OWNS
   paths (`navigation/value_map.py` + `tests/test_value_map.py`); keep
   formulas/tests equivalent; do not wire C2/C3 this wave; re-gate unit
   tests + `ci_gate --tier commit`; amend `V-C_STATUS.md`.
2. V-A / V-B / S-A / C-A need **no** product redispatch from this audit.
3. Wave-2 (incl. S-A2, V-D citing value-map import) stays gated until V-C
   re-audit CONFIRMED (or Fable records an explicit OWNS path amendment —
   not granted here).

---

## V-C re-audit

**Auditor:** Fable stand-in (Wave-1 re-audit after path fix)
**When:** 2026-08-09T22:41Z
**Prior verdict:** RETURNED (path ≠ OWNS — landed under `instructnav/semantic_value_map.py`)

### 1. Path check vs plan OWNS

| Path | Required | Observed |
|---|---|---|
| `src/parcel_robot/navigation/value_map.py` | PRESENT | **PRESENT** |
| `tests/test_value_map.py` | PRESENT | **PRESENT** |
| `src/parcel_robot/instructnav/semantic_value_map.py` | ABSENT | **ABSENT** |
| `tests/test_semantic_value_map.py` | ABSENT | **ABSENT** |

Ownership FAIL from first audit is cleared: sole public surface is the
pre-registered OWNS import path.

### 2. Named gate (independent re-run)

```
.parcel/bin/python -m pytest -q tests/test_value_map.py
→ 9 passed
```

### 3. Fresh `scripts/ci_gate.py --tier commit`

```
CI GATE — tier=commit  (2026-08-09T22:41:38Z)
[  PASS] HARD  ruff                       7 violation(s), baseline 7, new 0
[  PASS] HARD  hard-safety                …
[  PASS] HARD  frozen-digest-sentinels
[  skip] HARD  latency-tail-ledger        ledger rows=1 < window=5; ratchet skipped
[  PASS] HARD  model-off-non-inferiority
[  PASS] HARD  frozen-digest-integrity
[  PASS] HARD  mutation-panel-freshness
[  PASS] HARD  latency-tail
[  PASS] HARD  default-suite              3210 passed, 9 skipped, 34 deselected
RESULT: PASS — every hard gate green.  elapsed 103.3s
```

### Verdict: **V-C CONFIRMED**

No other open RETURNs remain (V-A / V-B / S-A / C-A already CONFIRMED in Wave-1
full audit).

### Overall: **WAVE CONFIRMED**
