# GATE-1 — gate truthfulness on skipping hosts + six-term envelope row (wave B)

**Tier B (behavior-change card, separately attributable) · Executor: Opus ·
Verifier: Fable.** Two verified gate-honesty defects from the ARCH-1 review
addendum (T12, R09/HW-6b). Both are hardware-integral: the Orin runs gates
on a host missing desktop tools, and the stopping row is what authorizes
speed on the dog.

## What to build
1. **Hard-skip exit semantics (T12).** Today `GateResult.is_red` = status in
   {fail,error}; typed hard SKIPs print truthfully but `main()` returns 0 —
   CI keying on the exit code reads a skipping host as green. Change: when
   any HARD row is `skip`, exit with a distinct code (2 = incomplete; 0 =
   full green; 1 = red). Summary text unchanged; JSON gains an
   `incomplete: true` field. Update the pinned tests that assert exit
   behavior (this is the sanctioned behavior change; name it in the STATUS).
2. **Six-term envelope row (R09 / HW-6b).** `evaluate_stopping_envelope`
   still calls the five-term V1 loader while V2 (with `scan_age_s`) exists.
   Swap to `derive_envelope_rows_v2` + `load_stopping_envelope_record_v2` so
   the row names `scan_age_s` (UNMEASURED on every host until B11) and can
   never print a five-term FITS. Delete the e7 gap-pin test HW-2's verifier
   flagged; keep HW-6's other 30 tests green unmodified.

## OWNS
`scripts/ci_gate.py` (marked regions `# ---- CARD GATE-1`; HW-6/HW-7/XD-1/
GATE-0b fences must not move), new test functions in
`tests/test_hw6_stopping_envelope.py` + `tests/test_hw7_gate_aarch64.py`,
`tests/test_ci_gate.py` pinned-string updates, this folder.

## MUST NOT TOUCH
Stage order, JSON schema beyond the additive field, other rows' logic,
`src/`, git. NEVER run `ci_gate.py --tier` (integrator only) — test through
the unit surface (`summarize`, `main` with stub stages) as the existing
tests do.

## Testing policy (owner — binding)
Capability tests: hard-skip → rc 2 + incomplete flag; all-green → rc 0
byte-identical summary; red → rc 1; stopping row prints six terms with
scan_age_s UNMEASURED. Short STATUS md.

## Execution rules
Guard wrapper `--label gate1`, `env -u TMPDIR`, no `-n auto`, no `noqa`,
ruff clean, no commit/push.
