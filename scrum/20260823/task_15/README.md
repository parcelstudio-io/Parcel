# DEC-IG-1 — leaf-import migration, unlocked packages (Tier M-B, mechanical)

Program: scrum/20260823/DECOMP_PROGRAM_FABLE.md §2 M1, §3. Verified
context: the 62-module SCC exists only through 39 re-exporting subpackage
barrels; bypassed, largest true cycle = 4.

## Build
Across ONLY these packages' .py files (as importERS):
navigation/, brain/, online_map/, camera_channel/, detection_adapter/,
instructnav/, commissioning/, control/, backends/, lidar/, maps/,
route_memory/, scene_semantics/, city_semantics/, vlm_veto/,
perception_abstention/, core/, contracts/ — rewrite intra-parcel_robot
imports that go THROUGH a package barrel (`from parcel_robot.brain import
X` where X is re-exported by brain/__init__) to the defining leaf module
(`from parcel_robot.brain.contracts import X`). Rules:
- Barrels themselves are UNTOUCHED this card (they keep re-exporting;
  nothing can break).
- Do not edit: runtime.py, agent.py, web_panel.py, realtime/**, voice_*,
  duplex/**, whisperer.py, sim.py, scripts/, tools/, tests/ (except the
  one measurement test below). Those migrate in DEC-IG-2.
- Pure import-line rewrites only — no reordering beyond what ruff isort
  requires, no other code changes, no __future__ or TYPE_CHECKING
  restructuring unless an import cycle forces it (record each).
- Measure before/after with an AST script (scratchpad): barrel-mediated
  intra-package edges, SCC count/size. Report both in the STATUS.
- Add tests/test_decig1_leaf_imports.py: for the migrated packages, no
  intra-package import resolves through a sibling package barrel
  (AST-check, fast) — pinned to the packages you migrated, extensible by
  DEC-IG-2.

## OWNS
The listed packages' import lines, tests/test_decig1_leaf_imports.py,
this folder.

## Prove
Full targeted suites for the touched packages through the guard wrapper
(`--label decig1`): tests/test_hw2_go2_backend.py, test_hw3_mid360_band.py,
test_p1b_map_learns.py, test_cap1_admission.py, plus a broad
`-k "nav or brain or camera or map"` selection — then ONE suite-scale run
of the full default selection is allowed for this card (it is the
mechanical wide-touch card): `-m 'not slow'` through the wrapper, -n 8.
Ruff clean; ratchet 7; zero behavior diffs expected — any test that
reddens is a real import-order/cycle discovery: fix by leaf-importing the
other side or record and revert that file, never by reordering module
side effects silently.

## Rules
Guard wrapper, no -n auto (the wrapper caps -n 8), no --tier, no noqa,
git read-only, owner's stack/store untouched. Short DECIG1_STATUS.md with
the edge/SCC numbers before/after.
