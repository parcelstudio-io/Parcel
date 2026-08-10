# S-B STATUS — proximity unification + P0-H + mixed-lethal (Sol stand-in)

**Executor:** Sol stand-in (Sol API limited)  
**Deps:** S-A2 LANDED (P0-A/B CLOSED on product path — not reopened)  
**Verdict:** **LANDED (core + proximity)** — ci_gate **RED on foreign ruff** (see STOP)

## Delivered

| Item | Result |
|---|---|
| One clearance convention | `CLEARANCE_CONVENTION = "base_center_to_obstacle_surface"` on `authority`; `CollisionPolicy` / `ReactiveSafetyPolicy` derive distances from `DEFAULT_SAFETY_ENVELOPE`; reactive rejects foreign convention / undercut of envelope obstacle floor |
| P0-H dimensional fix | Replaced `person_latency_factor` (dimensionless→metres) with `person_latency_s` (0.168 s); `person_stop(v, closing_speed_mps=…)` = `max(social, stop(v) + max(0,v_close)*latency_s)` |
| Mixed-lethal waypoint | Core helper `waypoints_trigger_lethal_veto` (`any()` fail-closed); consumed by `GoalArbiter._veto_reason` |
| Family-equality ratchet | Extended: reactive defaults + clearance convention pins; no-literal-drift allowlist shrank (reactive `1.2` literal removed) |
| S-A2 P0 wiring | Property tests still green (see Evidence) — hard_stop / input_health / missing-scan fail-closed preserved |
| P0-C `_accept_plan` nav-plan filter | **Not in OWNS** (`runtime.py` MUST NOT) — left as task_14 nuance; not tightened |

## OWNS / MUST-NOT

| Path | Action |
|---|---|
| `authority.py` | P0-H + `CLEARANCE_CONVENTION` / `PERSON_LATENCY_S` |
| `navigation/collision.py` | Convention docstring + frozen-bundle P0-H surface |
| `navigation/reactive_safety.py` | Envelope-derived defaults; input_health path **untouched** |
| `core/arbiter.py` | `waypoints_trigger_lethal_veto` |
| `instructnav/arbiter.py` | **OWNS exception** — one lethal-veto site (verdict arbiter mixed-lethal / plan “arbiter:141”); MUST-NOT said `instructnav/**` but card item 3 has no other product-path site |
| tests / family-equality / no-literal-drift | Extended |
| `runtime.py` | Not edited |

## Numeric unification (defaults)

| Field | Was (ReactiveSafetyPolicy) | Now |
|---|---|---|
| `person_stop_m` | 1.0 | `envelope.person_stop(0.0)` = **1.2** (tightens) |
| `person_slow_m` | 2.0 | `envelope.person_comfort_band_m` = **2.5** |
| `obstacle_slow_m` | 1.2 | `envelope.obstacle_comfort_band_m` = **1.2** (same) |
| `obstacle_stop_m` | 0.65 | `max(envelope.floor 0.6, commissioning 0.65)` = **0.65** (not loosened) |
| `reaction_time_s` | 0.12 | `envelope.reaction_latency_s` = **0.12** |

`CollisionPolicy` bit-equality to retired literals **unchanged** (obstacle floor stays 0.6).

## Evidence

```text
.parcel/bin/python -m pytest -q \
  tests/test_authority_family_equality.py \
  tests/test_authority_properties.py \
  tests/test_authority_no_literal_drift.py \
  tests/test_core_arbiter_lethal.py \
  tests/test_p0c_proposal_flush.py \
  tests/test_dynamic_layer.py \
  tests/test_sa2_live_pipeline.py \
  tests/test_core_hard_stop.py \
  tests/test_core_input_health.py \
  tests/test_velocity_shaping.py \
  tests/test_motion_shaping.py
# 268 passed

.parcel/bin/python scripts/ci_gate.py --tier commit  (2026-08-09T23:04:43Z)
# hard-safety / frozen-digest-* / mutation-panel / model-off / latency-tail: PASS
# default-suite: 3269 passed, 9 skipped, 34 deselected
# frozen rows: UNMOVED
# ruff: FAIL — 10 violation(s), baseline 7, new 3
#   -> instructnav/__init__.py I001+RUF022, navigation/pipeline.py I001
#   (V-E / concurrent Wave-2; not S-B OWNS; S-B surfaces ruff-clean)
```

## STOP

**ci_gate RED on ruff** from out-of-OWNS files (`instructnav/__init__.py`, `navigation/pipeline.py`). S-B did not edit those; did not self-service re-pin baseline. Frozen digests UNMOVED.

## does_not_prove

- Does not retune `configs/robot.yaml` safety block — runtime still **injects** yaml `person_stop_m=1.0` / `person_slow_m=2.0` / `obstacle_stop_m=0.65` into `ReactiveSafetyPolicy` (runtime.py not OWNS). Bare-default unification is landed; product-path yaml override is unchanged.
- Does not reconcile planner `stop_distance_m=0.8` (F-stop-distance handoff).
- Does not prove commissioned physical brake distance / human latency on hardware.
- Does not tighten `_accept_plan` nav-plan filter (runtime OWNS).
