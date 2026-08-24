# DEC-IG-2 — executor brief (Fable → Opus) · 2026-08-23

Read first: this file, then `README.md` (the card), then
`scrum/20260823/DECOMP_PROGRAM_FABLE.md` §2 (M1–M9) and
`scrum/20260823/task_14/DEC0_REGISTRY.md` §11 + §12. Base commit: the
DEC-IG-1 commit on `main` (HEAD when you start). Wave A is dead; nothing
else is in flight; the tree is yours alone for this card. You are the ONLY
writer of product files until you report — the integrator (Fable,
session parcel-fb) edits nothing under src/tests/scripts/tools while you run.

## The owner's goal, in one line
"SCC metrics need to be fixed." Today (ratchet, DEC-0 baseline):
package-aware cycles **25 / max SCC 81**; leaf-only **8 / 4**; 890
barrel-mediated symbol imports across 17 barrels. Target at close:
package-aware max SCC **≤ 10** (the 81-knot must die — it is a
navigation/brain/control/core/online_map/route_memory/vlm_veto/voice/
instructnav/commissioning/backends knot manufactured ONLY by barrels
executing cross-package submodules); leaf-only cycles **≤ 4**, each
survivor grandfathered with a one-line reason.

## Facts that change how you work (verified by the integrator)

1. **The ratchet's graph walks `ast.walk`**, so function-local imports AND
   `if TYPE_CHECKING:` imports count as edges (`tests/test_dec0_debt_ratchet.py:638-700`).
   Consequences: (a) a "deferred in-function import" does NOT break a cycle
   in the ratchet's model and is NOT a permitted fix here — it hides the
   cycle; (b) PEP 562 lazy `__getattr__` re-exports in a barrel still
   count — do not use them. Cycles die only by **emptying barrels** and by
   **moving the shared symbol to a leaf both sides import**, or by a
   `typing.Protocol` on the consumer side (M2), or by a type-only import
   under `if TYPE_CHECKING:` combined with the refinement in (2).
2. **One authorized ratchet refinement, exactly this:** `build_import_graph`
   skips import statements nested under `if TYPE_CHECKING:` (both models —
   they never execute). Nothing else changes in the measurement. Do it
   FIRST, measure the untouched tree with it (the "refined-before" row),
   then migrate, then measure again — so the STATUS isolates refinement
   effect from card effect. Re-freeze `BASELINE` and
   `BASELINE_CYCLE_COMPONENTS` to the post-card tree; every number may
   only move DOWN (`print_measured_baseline()` is the helper).
3. **There are no external consumers.** This is a single-repo prototype;
   the "public surface" in DEC-0 §11 is tests/examples/scripts/tools, all
   of which you migrate. Therefore every barrel becomes import-free:
   docstring + at most an `__all__` of *submodule names*. Two exceptions,
   each needing one comment line in the barrel naming the consumer: a
   submodule import kept purely for a side-effect registration that
   product code depends on; code that is *defined* in the `__init__`
   itself (e.g. `navigation/models/__init__.py`, 412 lines) stays — only
   re-export imports go.
4. **String patch targets do not route through barrels** (grep of
   `"parcel_robot.<pkg>.<Symbol>"` over src/tests/scripts/tools: zero
   hits), so `monkeypatch.setattr("parcel_robot.pkg.X")` breakage is not
   a risk class here. Namespace patching of a *module's* imported names IS
   (DEC0_REGISTRY §12.1): when you rewrite an import line in runtime.py,
   ci_gate.py, web_panel.py the bound NAME must stay identical (`from
   parcel_robot.x.leaf import http_service_health` keeps
   `runtime.http_service_health` patchable). Never alias.
5. **Vacuous-green oracles (DEC-0 finding F1).** Scanners keyed to a
   textual import pattern go GREEN when the pattern changes shape.
   Known instance: `tests/test_nm1_*` :550-564 scans runtime.py for
   forbidden `vlm_veto` imports. Before you rewrite any import line in a
   file DEC0_REGISTRY lists (§2–§10), read every TRANSITIONAL pin that
   keys on imports and port it in the same edit; list each ported pin
   (file:line, old→new) in the STATUS. `grep -n "import" DEC0_REGISTRY.md`
   finds them.
6. **Worklist size (integrator's AST inventory, symbol-level uses through
   each barrel → importing files):** brain 139→21, capture 124→20,
   online_map 74→11, commissioning 69→5, perception_source 57→11, lidar
   39→5, patrol 30→4, owner_model 23→3, control 22→6, core 14→5, duplex
   8→2, context 8→2, prompting 7→7, skills 4→4, backends 2→2,
   navigation.models 2→2, rl 1→1. Barrels with re-exports but ZERO symbol
   uses (empty them outright): realtime (35 syms), voice (28), navigation
   (26), bridge (15), attention (8), navigation.envs (2). Reusable
   starting points (read-only, copy to your own scratch):
   `/tmp/claude-1000/-home-jaewoo-jang-Desktop-Projects-Parcel/0b505906-665b-45ea-a2b7-686b3aecb89d/scratchpad/barrels.py`
   and `.../sccs.py` (prints SCC membership from the ratchet's own
   functions). Symbols resolve TRANSITIVELY (a barrel re-exporting from
   another barrel: land on the defining leaf).
7. **The one-line win** (card item 3): delete `from . import lane` and
   `"lane"` from `__all__` in `realtime/__init__.py`; update the docstring
   at `tools/replay_turn_detection.py:679` to say the barrel no longer
   executes `lane`; flip the TRUTH-1 assertion in
   `tests/test_truth1_texts.py::test_the_offline_modes_reach_lane_and_never_reach_ws_transport`
   from `"lane True"` to `"lane False"` (the stronger claim). Name all
   three edits in the STATUS.
8. **The 8 leaf-only cycles** (ratchet `BASELINE_CYCLE_COMPONENTS["leaf_only"]`):
   camera_channel.backends {physical, realsense, recorded, uvc};
   commissioning ↔ commissioning.session ↔ control ↔ control.factory;
   navigation ↔ navigation.envs ↔ envs.metaurban_env ↔ navigation.pipeline;
   perception_abstention ↔ vlm_veto.{bureau, runner, verifier};
   navigation.arrival_semantics ↔ navigation.goals;
   navigation.grid_navigator ↔ navigation.models;
   owner_model ↔ owner_model.distiller; runtime ↔ runtime_channels.
   The three that pass through a barrel should die with the emptying.
   For the rest: break where a leaf/Protocol/TYPE_CHECKING fix is clean
   and behavior-free (move a shared dataclass/constant to a same-package
   leaf — never `utils/`); otherwise grandfather with a reason line in
   the new ratchet. `runtime ↔ runtime_channels`: runtime_channels needs
   RobotRuntime only as a type — `if TYPE_CHECKING:` + string annotations
   is the expected fix; verify no runtime attribute access.

## Deliverables
- Every barrel-mediated symbol import in src/, tests/, scripts/, tools/,
  examples/, evals/ (evals/companion/run_*.py take brain/prompting/duplex
  symbols through barrels today; scrum/ python is history — untouched)
  rewritten to its defining leaf (`ruff check --select I --fix`
  for ordering; do NOT run `ruff format` on files that fail
  `ruff format --check` at HEAD — most do).
- Every `src/parcel_robot/**/__init__.py` import-free per fact 3.
- `tests/test_dec0_debt_ratchet.py`: the fact-2 refinement + downward
  re-freeze only.
- `tests/test_decig2_import_ratchet.py` (supersedes and absorbs
  `test_decig1_leaf_imports.py` — delete the old file if fully absorbed,
  else extend it): (a) tree-wide, no module imports a SYMBOL through a
  package barrel (submodule imports allowed); (b) no `__init__.py` under
  src/parcel_robot contains a re-export import, except an explicit
  allowlist with reasons; (c) cycle components equal an explicit
  grandfather list with a reason per cycle — a new or widened cycle
  reddens; (d) forbidden reverse edges from ARCH-1 DESIGN (measure which
  hold TODAY; a violated edge is fixed if trivial, else grandfathered by
  name — never faked green):
  `contracts/*, config.py, models.py, robot_profile.py, authority.py` →
  never import `runtime, web_panel, agent, realtime.*, providers,
  backends.*`; `navigation/*, core/*, brain/*` → never `runtime,
  web_panel`; `backends/go2.py, control/*` → never `sim, mujoco_lidar,
  headless_city, backends.mujoco`; nothing in src imports `web_panel`.
  Pure AST, no product imports, < 10 s, seeded-red once per assertion
  (scratch copy or monkeypatched measurement — cheapest honest red).
- `scrum/20260823/task_16/DECIG2_STATUS.md` (short, M9 register):
  table of package-aware cycles/max-SCC and leaf-only cycles/max-SCC at
  {before, refined-before, after}; barrel-mediated symbol imports
  before/after and per-barrel re-export counts before/after; files
  touched (count by top-level dir); every ported pin (fact 5); the three
  fact-7 edits; grandfather list with reasons; suites run with counts;
  anything you could not do and why.

## Proof (all through the guard wrapper; NEVER `-n auto`; NEVER `ci_gate.py --tier`)
`~/.cache/parcel-guard/pytest_guard.sh --label decig2 .parcel/bin/python -m pytest …`
with `TMPDIR` unset. Targeted first: the new ratchet, the DEC-0 ratchet,
`tests/test_truth1_texts.py`, `tests/test_import_order_no_cycle.py`,
`tests/test_runtime.py`, `tests/test_r24_lock_discipline.py`,
`tests/test_nominal_stop_wiring.py`, every `test_nm1_*`,
`tests/test_cap1_admission.py`. Then ONE full run:
`-m 'not slow' -n 8 --dist loadfile -p no:cacheprovider`. Known
pre-existing reds, disposition by re-run alone, never by relaxing:
`tests/test_yield_policy.py` (order-dependent under `--dist load`;
loadfile is unaffected) and
`tests/test_dynamic_costs.py::test_cost_field_vectorization_performance`
(R26 powersave perf pin, warm re-run passes). Any OTHER red is a real
import-order/cycle discovery: fix by leaf-importing the other side or
moving the shared symbol; never by reordering module side effects
silently; if you must revert a file, say which and why. `ruff check`
clean on every touched file; zero `noqa`.

## Rules (binding)
- Git is READ-ONLY: no add/commit/stash/checkout/restore. The integrator
  commits after verification.
- Edit by targeted replacement (exact-anchor `sed`, Python `str.replace`
  with a uniqueness check, or the Edit tool). Never rewrite a whole file
  you do not wholly own; the only files you wholly own are the two test
  files above, the STATUS, and the `__init__.py` barrels.
- Behavior code: untouched. Frozen baselines/eval fixtures/configs: untouched.
- Markers: add NO `# ---- CARD` lines (the count may only fall). Plain
  one-line comments are fine where a barrel keeps a side-effect import.
- Never touch `:8765`, `/tmp/parcel_sim.sock`, `parcel_memory.sqlite3`
  (owner's live stack); tests never open the store read-write.
- Reduced testing policy: capability-proof + error checks; no new
  combinatorial suites; the seeded reds above are the only ones owed.
- Do not stop at the first hard part: finish the tree-wide migration and
  the barrels even if some leaf cycles must be grandfathered. Report the
  numbers you actually measured, red or green.
