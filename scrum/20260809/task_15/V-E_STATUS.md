# Card V-E status — D3+D4 SEARCH→NAVIGATE lock-on + chance-constrained K0

**Executor:** Opus stand-in (Opus API limited)  
**Deps:** V-B (D1/D2 pure), V-A (B4 arrival ingress) — consumed, not edited  
**S-A2:** P0-A/B closed — MUST-NOT held (`reactive_safety.py`, `velocity_shaping.py`,
`core/hard_stop`, `core/input_health` untouched)

**Verdict:** **LANDED** — flag-gated D3+D4; T0 zero-cov byte-equal; ci_gate GREEN.

## Delivered (OWNS held)

### D4 — chance-constrained K0 (single arrival authority)
| Path | Change |
|---|---|
| `src/parcel_robot/instructnav/scoring.py` | `GoalRegion.contains` gains optional `anchor_covariance`; `P(inside)≥0.9` under D2 cov; zero/omitted cov = `_contains_exact` (T0 byte-equal). Added `p_inside_goal_region`, `INSIDE_PROBABILITY_THRESHOLD=0.9`. Scoring version → `v1.4-chance-constrained-k0`. `differential_arrival_verdict` accepts same cov. |
| `src/parcel_robot/instructnav/near_arrival.py` | `near_band_contains` delegates to `GoalRegion.contains` (no second predicate). |
| `src/parcel_robot/navigation/pipeline.py` | `_inside_arrival_goal_region` + `_semantic_arrival_verified` pass `arrival_anchor_covariance` when stamped; `_arrival_anchor_covariance()` helper. |

### D3 — detection-triggered SEARCH→NAVIGATE lock-on
| Path | Change |
|---|---|
| `src/parcel_robot/navigation/detection_lock_on.py` | **NEW** — `DetectionLockOnSession`: D1 `MultiViewConfirm` + D2 `MetricLocalizer` + SigLIP threshold → one `SE2Goal` via `build_se2_goal` stamped with `(task_id, plan_revision)`. `T_CAM_ORACLE_SR_MARGIN=0.10` pre-registered. |
| `src/parcel_robot/navigation/pipeline.py` | Flag `detection_lock_on=False` (default). Flag-on: RESOLVED path uses lock-on instead of frustum `required_observations` commit; publishes SE2Goal through ProposerBus/GoalArbiter; stores D2 cov on mission metadata. Soft-import of lock-on is **separate** from instructnav try (cannot disable GrounderV2 ladder). |
| Config | `detection_lock_on` readable from nav YAML / `from_mapping` overrides. |

### Tests + additive T-cam cell
| Path | Change |
|---|---|
| `tests/test_ve_detection_lock_on.py` | **NEW** — D4 T0 byte-equal / boundary fuzz; D3 M-of-N+SigLIP; P0-C mid-run correction flush; FP single-frame=0; paired-seed SR margin; flag on/off. |
| `evals/nav_instruct/cam_lock_on.py` | **NEW** additive T-cam-ve-lock-on report (file-disjoint from V-A/V-B cells). |

### runtime.py
**Not edited.** SE2Goal publish already lives in `DirectiveNavigator` via `proposer_bus` / `goal_arbiter` + `set_active_revision` stamp (P0-C product path). Lock-on reuses that seam; no runtime.py line required.

## MUST-NOT held
- `navigation/reactive_safety.py`, `velocity_shaping.py` — untouched
- `core/hard_stop.py`, `core/input_health.py` — untouched
- `camera_channel/**`, `counterfactual/**`, `personal_convo`, frozen packs — untouched

## VERDICT AFTER THE REAL RUN (lane E4, 2026-08-10) — SR margin NOT MET at tier level

`detection_lock_on` had never been run on `nav_instruct`. E4 ran it, paired,
frozen v3 minival, seed 20260804, `episode_digest 919a0fea…c556aa` on every arm
(n = 25; **each tier is n = 5**).

| arm | overall SR | Tier A | **Tier B** | Tier C | Tier D | Tier E | false_arrival |
|---|---|---|---|---|---|---|---|
| flag-OFF (oracle/frustum path) | **0.24** | 0.60 | **0.40** | 0.00 | 0.20 | 0.00 | 2 |
| `detection_lock_on` on | **0.16** | 0.60 | **0.00** | 0.00 | 0.20 | 0.00 | 1 |

Paired flips: **2 episodes lost, 0 gained** — both Tier B, both regressions.

| pre-registered gate | measured | verdict |
|---|---|---|
| `\|SR_lock − SR_oracle\| ≤ T_CAM_ORACLE_SR_MARGIN (0.10)` — aggregate | 0.24 → 0.16, gap **0.08** | within margin, but on n = 25 a single episode is 4 pp |
| same margin, **per tier** | Tier B 0.40 → 0.00, gap **0.40** | **FAIL** — 4× the pre-registered margin |

### The two lost episodes, attributed

| episode | flag-OFF | `detection_lock_on` ON |
|---|---|---|
| `nav-region_goal-B-05-586317e4` | success, `arrived_verified`, dtg 0.0 m, authority `agreement` | **failure class `false_arrival`** — mission still reports `arrived_verified` while **4.779 m** from the goal; authority `false_arrival` |
| `nav-object_relative-B-05-7d441aee` | success, dtg 0.0 m | grounding degrades **RESOLVED → UNSEEN**, times out `navigation_step_limit_inside_goal` |

The first is the safety-relevant one: lock-on committed an SE2 goal on an anchor
the terminal verifier then accepted, producing a **confident arrival 4.8 m from
the target**. That is precisely the failure mode the card's own FP gate was
supposed to exclude, and the proxy cell (`sr_gap=0.0`, `fp=0`) did not see it
because it never ran the product path.

This does **not** redden ci_gate hard-safety: that gate reads the latest
`frozen_baseline: true` row, and all four E4 arms are `mode=candidate`
(`frozen_baseline: false`). The frozen baseline is untouched.

**Card stays RETURNED on the SR margin.** The D4 chance-constrained-K0 work and
the T0 byte-equality below are unaffected and remain CONFIRMED.

## Gates

| Gate | Result |
|---|---|
| T0 zero-covariance = boolean | **PASS** — `test_zero_covariance_contains_matches_boolean_exactly`; cam_lock_on `t0_byte_equal_zero_covariance=true` |
| Noisy far / edge cov refuses arrival | **PASS** — edge P≈0.328 < 0.9 → refused |
| T-cam SR within pre-registered margin of oracle | **FAIL on the real run** — Tier B gap 0.40 ≫ `T_CAM_ORACLE_SR_MARGIN=0.10` (see above). The paired-seed **proxy** `sr_gap=0.0` over 16 constructed scenes is retained as a unit result only. |
| Differential authority / FP | **PASS in the pure cell** (single-frame commits 0; `false_positive_lock_commits=0`) — but the product run produced a **real false arrival at 4.779 m** under this flag, so the pure cell must not be read as an end-to-end FP claim. |
| P0-C mid-run correction e2e | **PASS** — `test_p0c_mid_run_correction_flushes_stale_lock_on_goal` (stamp + flush + new revision wins) |
| Flag-off byte-identical | **PASS by construction** — `detection_lock_on` defaults False; frustum path unchanged |
| S-A2 P0 wiring | **NOT REGRESSED** — MUST-NOT files clean |
| ci_gate `--tier commit` | **PASS** @ 2026-08-09T23:15:26Z |

```
.parcel/bin/python -m pytest -q tests/test_ve_detection_lock_on.py tests/test_k4_opus_wiring.py
→ 24 passed

.parcel/bin/python -m evals.nav_instruct.cam_lock_on
→ sr_lock_on=1.0 sr_oracle=1.0 sr_gap=0.0 t0_byte_equal=true boundary_fuzz_edge_refused=true fp=0

.parcel/bin/python scripts/ci_gate.py --tier commit
→ PASS — every hard gate green (elapsed 103.2s)
  ruff: 7 violation(s), baseline 7, new 0
  default-suite: 3283 passed, 9 skipped, 34 deselected
  frozen digests unmoved; model-off-non-inferiority green
```

## does_not_prove
- Full nav_instruct frozen-minival Tier A/B/C live SR under T-cam NoiseTier (paired-seed proxy only).
- Real D455 / open-vocab recognition (sim machinery + seg-truth / string-fallback SigLIP).
- Hardware mid-run voice correction e2e (sim ProposerBus/GoalArbiter stamp+flush only).
- Flag-on product city sim pack A/B vs oracle path.

## Note (cross-card import cycle, not owned)
`instructnav.arbiter` now imports `parcel_robot.core.arbiter` (C-B uncommitted). That pulls `core/__init__` → `motion_shaping` → `navigation`, which can race a partial arbiter load. V-E tests preload `navigation.pipeline` via `importlib` before importing arbiter. V-E did not edit `counterfactual/**` or revert C-B's arbiter import.
