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

## Gates (measured)

| Gate | Result |
|---|---|
| T0 zero-covariance = boolean | **PASS** — `test_zero_covariance_contains_matches_boolean_exactly`; cam_lock_on `t0_byte_equal_zero_covariance=true` |
| Noisy far / edge cov refuses arrival | **PASS** — edge P≈0.328 < 0.9 → refused |
| T-cam SR within pre-registered margin of oracle | **PASS** — paired-seed proxy `sr_gap=0.0` ≤ `T_CAM_ORACLE_SR_MARGIN=0.10` (16 scenes) |
| Differential authority / FP | **PASS** — single-frame commits 0; `false_positive_lock_commits=0` |
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
