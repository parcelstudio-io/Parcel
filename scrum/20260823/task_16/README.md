# DEC-IG-2 — barrel thinning + the import ratchet (runtime-slot card)

Program: DECOMP_PROGRAM_FABLE.md §3. Prereqs: DEC-IG-1 landed (navigation
barrel drained, realtime symbol re-exports gone), DEC-0 registry (the
public surface list), wave A landed (runtime.py/lane.py unlocked).

## Build
1. Migrate the REMAINING barrel-mediated importers to leaves: runtime.py,
   agent.py, web_panel.py, realtime/*.py, voice_*, duplex/, whisperer.py,
   sim.py, scripts/, tools/ (worklist from your own AST scan; DEC-IG-1's
   resolver in its STATUS is the template).
2. Thin every subpackage barrel to DEC-0's public surface: keep only
   re-exports named in DEC0_REGISTRY's public-surface rows (external
   importers, tests included); delete the rest. Where a barrel exists
   only to execute submodules for side effects, keep the module import
   and say so in one comment line.
3. Take the deferred one-line win: remove `from . import lane` from
   realtime/__init__ TOGETHER WITH the two pins that hold it
   (tools/replay_turn_detection.py:679 import goes leaf; the TRUTH-1
   assertion updates — name both in the STATUS). Expected: SCC 7→5,
   ~6.8k lines off the import path (DEC-IG-1's measurement).
4. Break the 8 true (leaf-only) cycles where a leaf import or a deferred
   in-function import does it cleanly (runtime↔runtime_channels,
   config↔skills via the skills barrel, camera_channel.backends 4-cycle,
   commissioning↔control, arrival_semantics↔goals, +3 from the ratchet's
   list) — or grandfather explicitly: each surviving cycle gets one line
   in the forbidden-edge test's baseline with a reason.
5. Land the import ratchet: extend tests/test_decig1_leaf_imports.py (or
   a successor test_decig2_import_ratchet.py): no barrel-mediated
   intra-package imports tree-wide; no NEW cycle vs the explicit
   grandfather list; forbidden reverse edges from the ARCH-1 DESIGN
   (contracts/config → runtime/UI/vendor; domain → runtime; adapters →
   sim truth).
6. Re-measure and report: package-aware cycles/max-SCC (was 25/81) and
   leaf-only (8/4) — the 81-knot MUST shrink materially this card; the
   DEC-0 ratchet baseline may then be TIGHTENED by the verifier's
   instruction at close (never by you silently).

## OWNS
All package __init__.py files, import lines in the files listed in (1),
tools/replay_turn_detection.py:679's import, the one TRUTH-1 assertion
line (named), the ratchet test file, this folder.

## MUST NOT TOUCH
Behavior code anywhere; NARR-1/EAR-1's landed regions beyond import
lines; frozen baselines; git.

## Prove
Full `-m 'not slow'` suite through the wrapper WITH `--dist loadfile`
(match the gate's sharding); DEC-0 ratchet + import ratchet green;
ruff clean; before/after SCC numbers in the STATUS.
