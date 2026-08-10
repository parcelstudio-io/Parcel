# Card S-A2 [opus] — Wave 2 wiring (Fable SPLIT)

**Deps:** C-A merged (`runtime.py` freed), S-A merged (pure `hard_stop` + `input_health`).  
**Source arbitration:** `AUDIT_WAVE1.md` § S-A early arbitration.

## OWNS
- `runtime.py` (`_dispatch_active`, `_shape_for_actuator`, `_collision_safe`)
- `navigation/velocity_shaping.py` (emergency → exact-zero, or superseded by hard_stop at `set_target`)
- `navigation/reactive_safety.py` (missing-scan fail-closed via `input_health`)
- tests for the live pipeline

## GATE (transferred from original S-A)
Property tests on the *live* pipeline green; mutation panel — new mutants killed;
safety pins untouched-green; frozen-row movement = STOP-and-report; ci_gate green.
**Only S-A2 may claim P0-A/P0-B closed.**

## Sequencing
S-B (proximity unification) MUST dispatch after S-A2 or yield on overlapping safety files.