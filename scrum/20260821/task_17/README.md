# Task 17 — R28: arrival that works for every class (from the full audit)

**Executor:** Claude Opus (agent) · **Auditor:** Fable
**Authority:** AUDIT_FULL_FABLE (quality): "verified arrival works for
exactly 1 of 5 shipped object classes" — R14's own control data showed
planter/door failing semantic arrival while lamppost verified.
**DISPATCH GATE: after the W1–E2 chain closes** (W-1 changed the world;
C-3 changed grounding — diagnose against the NEW stack, not the old).

## Work
1. Re-measure arrival across ALL shipped classes (both tiers: T0 oracle and
   T1 perception where C-3 enables it) in the textured world; per-class
   verdicts with the PG-2 surface convention + null controls.
2. Root-cause each failing class (goal sampling? tolerance? class geometry?)
   and fix in the arrival/goal layer; frozen nav baseline must not move.
3. Corpus nav rows extend to cover every class as regressions.
OWNS: navigation arrival/goal-sampling layer, tests, `R28_STATUS.md`.
MUST NOT TOUCH: yield policy, realtime/*, perception seats. DoD: gate
green; ≥8 seeds RED; per-class arrival table before/after; live proof on
≥3 previously-failing classes; standard register.
