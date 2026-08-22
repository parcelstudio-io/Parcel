# Task 18 — R30: evals hygiene (the audit's leftover majors)

**Executor:** Claude Opus (agent) · **Auditor:** Fable
**Authority:** AUDIT_FULL_FABLE remediation list, the undispatched tail.
**DISPATCH GATE: after M-1 (it rewrites latency claims M-1 re-measures).**

## Work
1. **Latency-tail ratchet de-vacuoused**: 4 of 6 pinned metrics currently
   vacuous; either populate them with real series (N19 fan-in, using M-1's
   FDB-v3 definitions) or shrink the pin to what is measured — no gate may
   overstate its check.
2. **acoustic_loop_v1 frozen flag enforced** (sentinel or de-flag, with the
   documented regeneration discipline).
3. **E1 pack manifest sealed over its R14 addendum files.**
4. **requirements-lock refreshed** to reproduce the working env (16 absent
   packages incl. sherpa-onnx — decide and document each: ship or dev-only).
5. **Gemma reasoner weight gets a provenance lock** (the judge has one; the
   14.4 GB production reasoner does not).
6. **Model-seat fixture gate**: the llmdet_tiny lesson mechanized — a
   pinned-fixture eval (EV-1 assertion style) that any model-seat swap must
   pass in CI before cutover.
OWNS: the named eval/gate surfaces, lock files, `R30_STATUS.md`.
MUST NOT TOUCH: frozen corpus fixtures, source behavior. DoD: gate green
(sentinels/parity included); ≥6 seeds RED; every gate's pass message
matches what it actually checked; standard register.
