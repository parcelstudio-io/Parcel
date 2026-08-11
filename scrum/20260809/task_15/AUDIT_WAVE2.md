# Wave-2 audit — 2026-08-09

**Auditor:** Fable stand-in (Claude Fable/Opus API often limited; this run follows
the pre-registered protocol in `NEXT_BATCH_PLAN.md` § Fable audit protocol).
**When:** 2026-08-09T23:17Z (ci_gate) / named gates + adversarial same session.
**Base HEAD:** `60ecea24168f839cb107a818799d0bc424bfee1d` (dirty wave tree:
Wave-1 + Wave-2a/2b uncommitted).
**Scope:** all Wave-2a + Wave-2b cards claiming DONE in `DISPATCH_WAVE2.md`.

---

## 1. Fresh `scripts/ci_gate.py --tier commit`

```
CI GATE — tier=commit  (2026-08-09T23:17:44Z)
[  PASS] HARD  ruff                       7 violation(s), baseline 7, new 0
[  PASS] HARD  hard-safety                … walk_with_me: 1/2 row(s) with hard_collision_total, all 0 = True
[  PASS] HARD  frozen-digest-sentinels    2 immutable manifest(s) byte-identical to pin
[  skip] HARD  latency-tail-ledger        ledger rows=1 < window=5; ratchet skipped
[  PASS] HARD  model-off-non-inferiority  23 passed
[  PASS] HARD  frozen-digest-integrity    6 passed
[  PASS] HARD  mutation-panel-freshness   1 passed
[  PASS] HARD  latency-tail               6 passed
[  PASS] HARD  default-suite              3283 passed, 9 skipped, 34 deselected
RESULT: PASS — every hard gate green.
  elapsed 102.5s
```

**Wave not returned for CI.** Frozen digests / mutation panel: **UNMOVED**
(`scripts/mutation_panel.py` clean vs HEAD; only `scripts/ci_ruff_baseline.json`
appears in frozenish-name diffs — Wave-1 C-A residue, not a Wave-2 silent freeze).

> **FALSE — CORRECTED 2026-08-10 (lane E3).** "Frozen digests: UNMOVED" is wrong.
> `evals/companion/personal_convo_v1/manifest.json` kept `"frozen": true` while
> its `pack_digest` moved `7e904d5335e049ac… → fc1af2f76f2b4914…` under card
> **M-A**, and rule 2's STOP-and-report never fired. The check that produced this
> line looked at *frozen-ish filenames in the diff*, which a manifest edit does
> not announce, and `ci_gate`'s `DIGEST_SENTINELS` byte-pinned only two manifests
> — this was not one of them, so a green gate agreed. The delta is additive-only
> (15 → 23 locks, +8 / −0 / repin 0, independently recomputed by Fable) and there
> is no tampering; the defect is process plus CI blindness. Sentinel added,
> provenance written into the manifest, key order restored — see `M-A_STATUS.md`
> and `E3_EVAL_INTEGRITY_STATUS.md`. The `mutation_panel.json` half of the claim
> is accurate and stands.

---

## 2–4. Per-card ownership / named gate / adversarial

### Wave 2a

#### S-A2 — CONFIRMED (P0-A/P0-B CLOSED on product path)

- **OWNS held** (`S-A2_CARD.md`): `runtime.py` (`_finalize_for_actuator` before
  `set_target`; `_collision_safe` / `_evaluate_dispatch_input_health` join),
  `navigation/velocity_shaping.py` (`emergency=True` → exact `(0,0,0)` + cache
  clear), `navigation/reactive_safety.py` (missing-scan via
  `evaluate_input_health`), `tests/test_sa2_live_pipeline.py`.
- **MUST-NOT clean:** no edits to `instructnav/**`, `camera_channel/**`,
  `detection_adapter/**`, `core/hard_stop.py`, `core/input_health.py`,
  `personal_convo`.
- **Accepted collateral:** far-field `nearest_obstacle_m=10.0` (and similar)
  fixture stamps in other tests so P0-B fail-closed does not false-fail
  unrelated suites — documented in status; not product-path logic.
- **Named gate (independent):**
  `.parcel/bin/python -m pytest -q tests/test_sa2_live_pipeline.py`
  → **11 passed**.
- **Adversarial (refute-first, safety):**
  - Attempted to keep Wave-1 P0-B defect: empty `lidar_obstacles` +
    `nearest_obstacle_m=None` + translating command → **stopped /
    translation zero** (no longer `"clear"`). Refute **failed** (fix holds).
  - Attempted residual emergency ramp: `SCurveVelocityShaper.step(...,
    emergency=True)` after nonzero seed → exact `(0,0,0)`. Refute **failed**.
  - Live path: `_finalize_for_actuator` + `finalize_command` sit immediately
    before `control_manager.set_target`; HARD_STOP resets smoother/shaper.
  - Frozen rows: **UNMOVED** (no silent mutation-panel / digest rewrite).
    > **CORRECTED 2026-08-10 (lane E3):** true for the mutation panel, false as a
    > blanket claim — `personal_convo_v1`'s frozen `pack_digest` moved under card
    > M-A. See the correction at the head of this file.
  - **P0-A / P0-B may be claimed CLOSED** (only this card).
    > **QUALIFIED 2026-08-10 (lane E3):** the P0-A *product path* is closed, but
    > the oracle cited as evidence,
    > `test_mutation_oracle_residual_nonzero_after_hard_stop_is_killed`, was a
    > tautology comparing two `VelocityCommand` constants and proved nothing. It
    > has been rewritten to drive the real dispatch path and now demonstrably
    > kills a seeded `finalize_command` pass-through mutant. The CLOSED verdict
    > survives on the rewritten evidence; it was not supported by the evidence
    > this audit accepted.

#### V-D — CONFIRMED

- **OWNS held:** `navigation/value_directed_scan.py` (NEW),
  `navigation/instructnav_recovery.py` (opt-in value session),
  `navigation/pipeline.py` (`value_directed_search` flag-gated),
  `instructnav/search_entity.py` (C3 scorers / plan-time prior),
  `instructnav/__init__.py` exports, `tests/test_value_directed_search.py`.
- **MUST-NOT clean:** no `runtime.py`, `velocity_shaping.py`,
  `reactive_safety.py`, `camera_channel/**`, `detection_adapter/**`,
  `instructnav/scoring.py`, `core/hard_stop.py`, `core/input_health.py`.
- **Named gate:**
  `.parcel/bin/python -m pytest -q tests/test_value_directed_search.py`
  → **12 passed** (Tier B/C proxy + lease/suspend checks included).
- **Note (non-blocking):** full nav_instruct frozen-minival SR remains
  `does_not_prove` (proxy paired-seed only) — matches status honesty.

#### M-A — CONFIRMED

- **OWNS held:** `evals/companion/personal_convo_v1/**` (judge, calibration
  pack 3+3 frozen cases, live_provider, runner wire, additive manifest locks,
  live result JSON) + `tests/test_personal_convo_pc4.py`.
- **MUST-NOT clean:** no `runtime.py`, `navigation/**`, `core/**`,
  `camera_channel/**`, `detection_adapter/**`, `instructnav/**`.
- **Named gate:**
  `.parcel/bin/python -m pytest -q tests/test_personal_convo_pc4.py`
  → **8 passed** (calibrate → qualified; drift → disqualified / scores
  omitted; report-only pins).
- **Note:** live summarizer measurement is report-only / mixed fallback
  (`used_fallback=true`) per status — not a silent quality claim.

#### C-B sol — CONFIRMED

- **OWNS held (pure only):** `src/parcel_robot/counterfactual/**` (NEW) +
  `tests/test_counterfactual_oracle.py`. No product wiring in the sol half.
- **MUST-NOT clean for sol cut:** no `runtime.py`, `navigation/**`,
  `instructnav/**`, `camera_channel/**`.
- **Named gate:**
  `.parcel/bin/python -m pytest -q tests/test_counterfactual_oracle.py`
  → **15 passed** (selector, digest, bit-identical replay, oracle gap).
- Historical sol-cut tree-level ci red (parallel Wave-2a) is superseded by
  this audit’s green commit gate.

### Wave 2b

#### V-E — CONFIRMED

- **OWNS held:** `instructnav/scoring.py` (chance-constrained K0 /
  `p_inside_goal_region`, T0 zero-cov byte-equal path),
  `instructnav/near_arrival.py` (delegates to single predicate),
  `navigation/detection_lock_on.py` (NEW), `navigation/pipeline.py`
  (`detection_lock_on` flag-gated; soft-import separate from instructnav),
  `tests/test_ve_detection_lock_on.py`, `evals/nav_instruct/cam_lock_on.py`
  (NEW, file-disjoint from V-A/V-B cells). `runtime.py` **not** edited.
- **MUST-NOT clean:** `reactive_safety.py`, `velocity_shaping.py`,
  `core/hard_stop.py`, `core/input_health.py`, `camera_channel/**`,
  `counterfactual/**`, `personal_convo`, frozen packs.
- **Named gate:**
  `.parcel/bin/python -m pytest -q tests/test_ve_detection_lock_on.py`
  → **14 passed**.
  Plus present additive cell:
  `.parcel/bin/python -m evals.nav_instruct.cam_lock_on`
  → `sr_gap=0.0`, `t0_byte_equal_zero_covariance=true`,
  `boundary_fuzz_edge_refused=true`, `false_positive_lock_commits=0`.
- **Note (non-blocking):** import-cycle preload workaround vs C-B arbiter
  import documented in status; no revert of C-B contracts.

#### S-B — CONFIRMED

- **OWNS held:** `authority.py` (CLEARANCE_CONVENTION + `PERSON_LATENCY_S` /
  P0-H dimensional fix), `navigation/collision.py`,
  `navigation/reactive_safety.py` (envelope-derived defaults; **input_health
  path preserved**), `core/arbiter.py` (`waypoints_trigger_lethal_veto`),
  family-equality / no-literal-drift / lethal tests.
- **Documented OWNS exception (accepted):** one lethal-veto site in
  `instructnav/arbiter.py` — required by plan one-liner (mixed-lethal /
  arbiter:141); replaces `all()` with `any()` via core helper. Coexists with
  C-B’s flag-gated log in the same file (complementary hunks).
- **MUST-NOT:** `runtime.py` not edited. P0-C `_accept_plan` nav-plan filter
  **not tightened** (honesty: not OWNS) — deferred, not silently claimed.
- **Named gate (independent; includes S-A2 non-regression):**
  ```
  .parcel/bin/python -m pytest -q \
    tests/test_authority_family_equality.py \
    tests/test_authority_properties.py \
    tests/test_authority_no_literal_drift.py \
    tests/test_core_arbiter_lethal.py \
    tests/test_sa2_live_pipeline.py
  → 152 passed
  ```
- **Adversarial (refute-first, safety):**
  - Attempted safety *loosening*: bare reactive `person_stop_m` moved
    1.0 → **1.2** (tightens); `obstacle_stop_m` stays **0.65** via
    `max(envelope.floor, 0.65)` with undercut guard. Refute of “S-B weakened
    stops” **failed**.
  - P0-A/B product path still closed: S-A2 live tests green in the named gate;
    missing-scan fail-closed still present at `reactive_safety` join.
  - Mixed-lethal: old `all(self._lethal…)` removed; `waypoints_trigger_lethal_veto`
    is `any()`.
  - Frozen rows: **UNMOVED**.
    > **CORRECTED 2026-08-10 (lane E3):** same correction as above — the frozen
    > `personal_convo_v1` `pack_digest` moved under card M-A. This audit repeated
    > the claim without a check that could have seen a manifest edit.
  - Status-doc STOP (ci_gate ruff red on V-E/`pipeline`/`__init__` at S-B cut)
    is **cleared** by this audit’s fresh green gate — cross-card residue, not
    an S-B ownership breach.
- **Honesty retained:** robot.yaml still injects legacy
  `person_stop_m=1.0` / `person_slow_m=2.0` into reactive policy via runtime
  (not OWNS) — bare-default unification landed; product yaml retune deferred.

#### C-B opus — CONFIRMED

- **OWNS held:** `instructnav/arbiter.py` flag-gated `build_arbitration_log` at
  `GoalArbiter.resolve` + `report_counterfactual`;
  `tests/test_counterfactual_arbiter_wire.py`. Frozen counterfactual contracts
  consumed only (not rewritten).
- **MUST-NOT clean for semantic edits:** no `runtime.py`,
  `reactive_safety.py`, `velocity_shaping.py`, `collision.py`,
  `instructnav/scoring.py`, `camera_channel/**`, `personal_convo/**`.
- **Accepted mechanical only:** status admits `ruff --fix` import-order on
  `instructnav/__init__.py` + `navigation/pipeline.py` while parallel V-E
  dirt reddened the gate — no semantic V-E/V-D edits attributed; fresh ruff
  new=0.
- **Named gate:**
  `.parcel/bin/python -m pytest -q tests/test_counterfactual_arbiter_wire.py`
  → **7 passed** (flag-off noop, wire+replay, HOLD, plan-step, oracle report,
  env flag).

---

## 5. Cross-card / overall

| Card | Verdict | Gate result | Ownership |
|---|---|---|---|
| S-A2 | **CONFIRMED** | `test_sa2_live_pipeline` 11 passed; P0-A/B CLOSED | OK |
| V-D | **CONFIRMED** | `test_value_directed_search` 12 passed | OK |
| M-A | **CONFIRMED** | `test_personal_convo_pc4` 8 passed | OK |
| C-B sol | **CONFIRMED** | `test_counterfactual_oracle` 15 passed | OK (pure) |
| V-E | **CONFIRMED** | `test_ve_detection_lock_on` 14 + cam_lock_on metrics | OK |
| S-B | **CONFIRMED** | family/lethal/S-A2 152 passed; no loosen / no freeze move | OK (+arbiter lethal exception) |
| C-B opus | **CONFIRMED** | `test_counterfactual_arbiter_wire` 7 passed | OK |

### Overall: **WAVE CONFIRMED**

All Wave-2a + Wave-2b cards CONFIRMED. No product redispatch required from
this audit.

**Non-blocking follow-ups (not RETURNs):**
1. S-B / runtime owner later: retune `configs/robot.yaml` safety inject so
   product-path reactive thresholds match bare-default unification.
2. Deferred S-B item: P0-C `_accept_plan` nav-plan filter (runtime OWNS).
3. V-D / V-E `does_not_prove`: live nav_instruct frozen-minival SR under
   flag-on remains unmeasured at commit tier.
