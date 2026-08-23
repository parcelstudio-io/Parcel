# DEC-R1 — runtime.py: the pure exodus (runtime-slot card, after DEC-IG-2)

Program: DECOMP_PROGRAM_FABLE.md §2 M5/M6/M7, §3. The first direct
shrink of the 16.4k-line file: move PURE code out; move ZERO state.

## Build
Candidates (verify each is pure — no self, no locks, no I/O):
module-level `scene_report` (~:932) + `scene_fact_lines` (~:1115) → a new
`parcel_robot/scene/report.py` (or the existing owning package if one
fits); pure config-shaped helper dataclasses/parsers trapped in
runtime.py; pure formatting/geometry helpers found by an AST sweep
(functions with no attribute access on self and no imports of runtime
state). For each move:
- destination is the FEATURE package (M6), never utils/;
- the runtime.py import updates to the leaf; public compatibility: if
  DEC0_REGISTRY lists external importers of the symbol from runtime,
  keep a one-line re-export at the old name with a comment;
- admission.py filename rosters extend if the new file reads config
  sections (DEC-0 finding b);
- any shape-test pin classified TRANSITIONAL in DEC0_REGISTRY ports in
  this card (the vacuous-green trap: a scanner keyed to runtime.py must
  gain the new path — DEC-0 finding a); INCIDENTAL pins may be replaced
  by the named behavior test;
- marked-region markers inside moved code dissolve (M7) — net marker
  count must drop; the ci_gate fence oracles (opens==closes>0) stay
  satisfied.

## Metrics (M9 — the card is judged on these)
runtime.py lines before/after (target: −1,500 or a written reason);
RobotRuntime method/attr count unchanged (this card moves NO state);
marker count delta; ratchet green with the verifier authorized to
tighten the >100-line-function baseline if moves demote entries.

## OWNS
runtime.py (import/removal hunks + the marked regions being dissolved),
the new destination modules, admission.py roster lines, the named
TRANSITIONAL pin tests, tests/test_decr1_pure_exodus.py (thin: each
moved function importable from its new home + one behavior spot-check),
this folder.

## MUST NOT TOUCH
RobotRuntime's class body state/methods (beyond deleting moved
module-level code), locks, callbacks, frozen baselines, git.

## Prove
Suites: r24 + nominal-stop oracles (zero unexplained re-pins),
test_runtime.py, the full `-m 'not slow'` with --dist loadfile through
the wrapper, ratchet, ruff.
