# S-A2 STATUS — Wave-2 P0 wiring (Opus stand-in)

**Executor:** Opus stand-in (prior `103a6767` API-limited with zero progress)  
**Deps:** C-A freed `runtime.py`; S-A landed pure `core/hard_stop` + `core/input_health`  
**Arbitration:** `AUDIT_WAVE1.md` § S-A early arbitration — SPLIT wiring card  
**Verdict:** **LANDED** — live dispatch consumes the S-A boundaries.

## P0-A / P0-B — CLOSED (S-A2 claim)

| Blocker | Product-path fix | Evidence |
|---|---|---|
| **P0-A** | Emergency shaper snaps to exact `(0,0,0)`; `finalize_command` runs immediately before `set_target` with HARD_STOP resets | `tests/test_sa2_live_pipeline.py` + `tests/test_velocity_shaping.py` |
| **P0-B** | Missing/stale/malformed scan/pose/feedback → HOLD/LATCHED_STOP; missing scan cannot pass translation | `reactive_safety` scan join + runtime `_collision_safe` full join; live tests |

Only this card claims P0-A/P0-B closed.

## Delivered (OWNS held)

| Path | Change |
|---|---|
| `src/parcel_robot/runtime.py` | `_dispatch_active` → `_finalize_for_actuator` before `set_target`; `_collision_safe` input-health join (pose/scan/feedback) |
| `src/parcel_robot/navigation/velocity_shaping.py` | `emergency=True` → exact-zero, clears accel/velocity caches |
| `src/parcel_robot/navigation/reactive_safety.py` | Missing-scan fail-closed via `evaluate_input_health` (`scan_evidence_from_observation`) |
| `tests/test_sa2_live_pipeline.py` | Live-pipeline property tests (set_target exact-zero, missing-scan HOLD, interrupt-at-every-stage) |
| Supporting test fixtures | Far-field scan samples where fixtures previously treated `None` as “clear” |

**MUST-NOT held:** no edits to `instructnav/**`, `camera_channel/**`, `detection_adapter/**`, `core/hard_stop.py`, `core/input_health.py`, `personal_convo`.

## Wiring contracts (mechanical)

### P0-A — hard_stop at set_target

After `_shape_for_actuator`, `_finalize_for_actuator` maps:

| Condition | Severity | Command |
|---|---|---|
| `emergency_stopped` or `_input_health_latched` | `HARD_STOP` | exact `(0,0,0)` + reset `velocity_smoother` + `actuator_shaper` |
| `proximity_state == "stopped"` | `PROXIMITY_STOP` | translation zero; gated yaw preserved |
| `active is None` or zero intent | `HARD_STOP` | exact `(0,0,0)` + resets |
| else | `CLEAR` | shaped candidate unchanged |

Emergency path in `SCurveVelocityShaper.step` no longer ramps residual velocity.

### P0-B — input_health before translation authority

- `apply_reactive_safety`: translating + unhealthy scan → `_stop_translation` (never `"clear"`).
- `_collision_safe`: full `evaluate_input_health` on pose/scan/controller feedback; HOLD zeros translation; `LATCHED_STOP` sets `_input_health_latched` for HARD_STOP finalize.

## Mutation panel / frozen rows

- **Frozen rows: UNMOVED** (`mutation_panel.json` / digests untouched).
- NAV_INSTRUCT mutation panel does not exercise `RobotRuntime._dispatch_active` / `set_target` hard_stop; seeding hard_stop mutants there would be equivalent. Live-pipeline oracles in `tests/test_sa2_live_pipeline.py` kill residual-nonzero and missing-scan-as-clear classes.
- W4 git-status pin on `reactive_safety.py` converted to behavioural pin (`test_the_reactive_safety_authority_gate_behaviour_holds`) — S-A2 is authorized to edit that file.

## Evidence

- `.parcel/bin/python -m pytest -q tests/test_sa2_live_pipeline.py tests/test_velocity_shaping.py tests/test_motion_shaping.py tests/test_core_hard_stop.py tests/test_core_input_health.py`
- `.parcel/bin/python scripts/ci_gate.py --tier commit` (2026-08-09T22:58:44Z)
  - **PASS — every hard gate green**
  - ruff: `7 violation(s), baseline 7, new 0`
  - default-suite: `3256 passed, 9 skipped, 34 deselected`
  - hard-safety / frozen-digest-* / mutation-panel-freshness / latency-tail: PASS
  - elapsed 102.7s

## does_not_prove

- Does not prove actuator HAL internals beyond `control_manager.set_target` boundary.
- Does not re-run the nightly NAV_INSTRUCT mutation panel live (freshness guard only; commit tier).
- Does not unify proximity thresholds across authority/collision (S-B).
