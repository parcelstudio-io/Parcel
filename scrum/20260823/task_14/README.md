# DEC-0 — oracle & API classification + debt ratchet (Tier B, read-mostly)

Program: scrum/20260823/DECOMP_PROGRAM_FABLE.md §3. You produce the map
every later DEC card depends on. NO product-file edits.

## Build
1. **DEC0_REGISTRY.md** (this folder): for each first-target file
   (runtime.py, navigation/pipeline.py, realtime/lane.py,
   realtime/audio_gateway.py, web_panel.py, agent.py,
   realtime/tool_broker.py, scripts/ci_gate.py) list the tests that pin
   its SHAPE (AST/source-text/digest/lock-roster/callback-roster/marker
   pins — start from the ~186 source-shape test modules; grep patterns in
   the ARCH-1 verdict) and classify each pin: SUPPORTED-CONTRACT (public
   behavior a card must keep), TRANSITIONAL (ports with the code it pins
   — name the porting rule), INCIDENTAL (replaceable by a behavior test —
   name the behavior). Also enumerate the PUBLIC surface per file: what
   imports it from outside src/parcel_robot (tests count), which config
   keys/endpoints/CLI it owns.
2. **tests/test_dec0_debt_ratchet.py**: measured-baseline ratchet — no
   NEW module >1,000 lines, no NEW function >100 lines, no NEW cycle
   (import-graph SCC count against a pinned baseline), no NEW
   `# ---- CARD` marker net increase per commit... implement what is
   honestly measurable in one file with a frozen baseline dict (measure
   the tree, pin today's numbers, fail only on regression). Keep it fast
   (<10 s) — AST/grep only, no imports of product code.

## OWNS
This folder, tests/test_dec0_debt_ratchet.py. NOTHING else — read-only
everywhere.

## Prove
The ratchet test green on today's tree through the guard wrapper
(`--label dec0`); a seeded check that it REDDENS on a synthetic
1,001-line module written to the scratchpad tree copy or via monkeypatched
measurement (your choice — cheapest honest red). Registry spot-verified:
every claimed pin names its test file:line.

## Rules
Guard wrapper, no -n auto, no --tier, no noqa, ruff clean, git read-only,
owner's stack/store untouched. Short DEC0_STATUS.md.
