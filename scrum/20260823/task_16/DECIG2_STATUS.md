# DEC-IG-2 — barrel thinning + the import ratchet — STATUS

Card: `scrum/20260823/task_16/README.md`, executor brief `BRIEF_FABLE.md`.
Base: `43e6cfc` (DEC-IG-1). Integrator amendment adopted: `evals/` added to the
importer roots (8 eval runners took barrel symbols; all rewritten).
Git untouched — no add/commit/stash/checkout.

## 1. M9 metrics

### 1.1 Import cycles (the headline)

| quantity | before | refined-before | after | target |
|---|---|---|---|---|
| cycles, package-edge model | 25 | 24 | **8** | — |
| **max SCC, package-edge model** | **81** | **80** | **5** | ≤ 10 ✅ |
| **cycles, leaf-only model** | **8** | **7** | **4** | ≤ 4 ✅ |
| max SCC, leaf-only model | 4 | 4 | 4 | — |

*before* = the DEC-0 baseline, reproduced exactly on the untouched tree.
*refined-before* = the same untouched tree measured with the ONE authorized
refinement (`build_import_graph` skips imports nested under `if TYPE_CHECKING:`
— they never execute, in both models). *after* = this card.

**What the refinement alone did, and nothing else:** `parcel_robot.navigation.base`
left the 81-knot (81 → 80), and the `runtime ↔ runtime_channels` cycle
disappeared from BOTH models (25 → 24, 8 → 7). The brief expected DEC-IG-2 to
break that one with `if TYPE_CHECKING:` + string annotations; **it was already
written that way** — `runtime_channels.py:10-16` imports `RobotRuntime` only
under the guard, and no attribute is touched at import time. Only the
*measurement* was wrong. Nothing was edited to bank that win.

**What this card did:** everything else. 81 → 5 is the death of the
navigation/brain/control/core/online_map/route_memory/vlm_veto/voice/
instructnav/commissioning/backends knot; it existed only because importing
`pkg.leaf` executes `pkg/__init__.py` and 38 of those `__init__`s executed
cross-package submodules to re-export names.

### 1.2 Barrels

| quantity | before | after |
|---|---|---|
| barrel-mediated SYMBOL imports (aliases) | **941** | **0** |
| ...in import statements / files | 204 / 127 | 0 / 0 |
| true re-exports (names an `__init__` imports and never uses) | **929** across 38 barrels | **0** across 0 |
| package `__init__`s that import anything at all | 39 of 40 | **5** of 40 |
| total lines in `src/parcel_robot/**/__init__.py` | 3,105 | **886** |

The brief's "890 across 17 barrels" is the same population counted over five
roots; with `evals/` added and `contracts`/`counterfactual`/`gnss`/etc. resolved
through absolute-form re-exports the AST sweep finds 941 aliases across 32
barrels with symbol traffic (38 barrels re-exported; 6 had zero callers).

Per-barrel re-export count before → after (all → 0 unless noted; the five with
kept imports consume them in code DEFINED in the `__init__`, and re-export none):

| barrel | re-exports before | sym-aliases taken through it | after |
|---|---|---|---|
| brain | 50 | 183 | 0 |
| capture | 29 | 124 | 0 |
| contracts | 32 | 89 | 0 |
| online_map | 63 | 74 | 0 |
| commissioning | 45 | 69 | 0 |
| perception_source | 27 | 57 | 0 |
| lidar | 29 | 39 | 0 |
| patrol | 17 | 30 | 0 |
| route_memory | 49 | 28 | 0 (keeps 8 imports for `DOES_NOT_PROVE`) |
| owner_model | 25 | 23 | 0 |
| control | 19 | 22 | 0 |
| counterfactual | 12 | 17 | 0 |
| low_viewpoint | 24 | 17 | 0 |
| camera_channel | 37 | 16 | 0 |
| detection_adapter | 31 | 15 | 0 |
| uwb | 20 | 15 | 0 (keeps 2) |
| core | 22 | 14 | 0 |
| storefront | 27 | 14 | 0 (keeps 3) |
| vlm_veto | 53 | 14 | 0 |
| gnss | 13 | 13 | 0 |
| duplex | 16 | 11 | 0 |
| prompting | 3 | 11 | 0 |
| perception_daemon | 10 | 10 | 0 |
| maps | 33 | 9 | 0 (keeps 4) |
| context | 7 | 8 | 0 |
| bags | 14 | 5 | 0 |
| camera_channel.backends | 9 | 4 | 0 |
| skills | 5 | 4 | 0 |
| backends | 12 | 2 | 0 |
| navigation.models | 6 | 2 | 0 (not a barrel; keeps 6) |
| navigation.envs | 2 | 1 | 0 |
| rl | 6 | 1 | 0 |
| instructnav | 67 | 0 | 0 |
| realtime | 35 | 0 | 0 |
| voice | 28 | 0 | 0 |
| navigation | 26 | 0 | 0 |
| owner_tracking | 25 | 0 | 0 |
| bridge | 15 | 0 | 0 |
| attention | 8 | 0 | 0 |

Five `__init__`s still import, each allowlisted with its reason in the new
ratchet: `maps`, `route_memory`, `storefront`, `uwb` each compose a
package-level `DOES_NOT_PROVE` tuple from their leaves' own tuples (code
*defined* in the `__init__`, read from the package by
`tests/test_p{2_uwb_noise,3_city_layer,3_storefront_ocr,4_route_memory}.py`);
`navigation/models/__init__.py` is not a barrel at all — 412 lines that define
`StubNavigator` and `build_navigator` and import the types they use.

### 1.3 Other ratcheted quantities (all down or flat)

`oversized_modules` 45 → 45 · `long_function_count` 153 → 153 ·
`card_markers` 178 → **176** (two `# ---- CARD HW-2` fences died with
`backends/__init__.py`) · `scoped_files` 364 → 364.

## 2. Files touched — 174

| dir | files |
|---|---|
| tests | 83 |
| src | 63 |
| scripts | 14 |
| evals | 8 |
| tools | 2 |
| docs | 2 |
| examples | 1 |
| repo root (`README.md`) | 1 |

173 modified, 1 deleted (`tests/test_decig1_leaf_imports.py`), 1 added
(`tests/test_decig2_import_ratchet.py`). Diff: +751 / −3,386.

Method: AST rewrite driven by a transitive resolver (a barrel re-exporting from
another barrel lands on the DEFINING leaf), line-range splice per import
statement, then `ruff check --select I --fix` for ordering. **Verified
behaviour-neutral by construction:** every file's set of import-bound NAMES was
snapshotted before and after — 924 modules, **0 files whose bindings changed**.
No name was ever aliased away (§12.1's namespace-monkeypatch risk); where a
barrel itself renamed a re-export the `as` clause moved with it.

`ruff format` was NOT run on migrated product files (most fail
`ruff format --check` at HEAD); it WAS run on the two files this card wholly
owns (`test_dec0_debt_ratchet.py`, `test_decig2_import_ratchet.py`), which were
already format-clean.

## 3. The fact-7 one-line win (three edits, plus one rename)

1. `src/parcel_robot/realtime/__init__.py` — `from . import lane` and the whole
   `__all__` deleted with the rest of the barrel. `lane.py` + `tool_broker.py`
   (~6.8k lines) leave the import path of every process that only wants
   `realtime.config`.
2. `tools/replay_turn_detection.py:675` — `_build_live_lane`'s docstring now
   says the barrel is import-free and the offline arms reach NEITHER `lane` nor
   `ws_transport`; the retracted wording stays described, never reproduced (the
   `"cannot reach"` grep guard still holds).
3. `tests/test_truth1_texts.py:600` — `"lane True"` → `"lane False"`, the
   stronger claim. The cell is renamed
   `test_the_offline_modes_reach_lane_and_never_reach_ws_transport` →
   `test_the_offline_modes_reach_neither_lane_nor_ws_transport`, because a test
   name that asserts the opposite of its body is the same vacuity hazard the
   card exists to retire. Nothing outside `scrum/` referenced the old name.

## 4. Ported pins (fact 5 / DEC-0 F1) — 14 code pins + 6 documentation truths

Every one was found BEFORE the edit by a sweep the AST scan cannot do: a regex
for `from parcel_robot.<pkg> import <name>` over string literals, docstrings,
`.md` and `.sh` — subprocess programs are invisible to an import scan.

| file:line | old → new | why it would have broken / gone vacuous |
|---|---|---|
| `tests/test_truth1_texts.py:600` | `"lane True"` → `"lane False"` | fact-7 win (above) |
| `tools/replay_turn_detection.py:675` | docstring claim | fact-7 win (above) |
| `tests/test_hw2_go2_backend.py:471` | `lines[1] == "['socket']"` → `"[]"` | A6 recorded that `socket` arrived via `backends/__init__` → `.mujoco` → `sim_ipc`; the drained barrel means `import parcel_robot.backends.go2` no longer executes the mujoco sibling. Measured, then re-pinned; the docstring says so |
| `tests/test_capture_envelope.py:1207` | `_modules("import parcel_robot.capture")` → probe `capture.channels, capture.envelope` | the exact-set probe expected the barrel to execute both leaves. Now probes the consumer path, and a NEW assertion pins that the package itself executes nothing |
| `tests/test_c3_cutover.py:1155` | `"from parcel_robot.online_map import"` → `"from parcel_robot.online_map."` | source-text pin keyed on the barrel spelling; would have reddened, and the naive fix would have gone vacuous |
| `tests/test_c3_cutover.py:1172` | subprocess `perception_source` → `perception_source.selection` | fresh-interpreter program; ImportError after draining |
| `tests/test_c2_online_map.py:598` | subprocess `online_map` → `.entries` / `.online_map` / `.store` | same |
| `tests/test_c2_online_map.py:848` | `test_route_memory_is_untouched_by_this_card` → `test_route_memory_is_bound_to_never_forked_by_this_card` | a `git diff --name-only HEAD` emptiness pin: a claim about the runner's working tree, vacuous once committed, red for ANY later card chartered to touch `route_memory/`. Replaced by the property it stood for (C-2's package imports no `route_memory` module and re-declares none of its five types) — the same treatment `test_c3_cutover.py` already gave its sibling |
| `tests/test_capture_ingest.py:431` | subprocess `capture` → `capture.channels` | same |
| `tests/test_capture_ingest.py:2383` | `monkeypatch.setattr(parcel_robot.capture, "CHANNELS")` → `parcel_robot.capture.channels` | §12.1 namespace patching, at PACKAGE level: `dds.py` binds `CHANNELS` from the leaf now, so patching the drained package is a no-op |
| `tests/test_capture_sidecar.py:410` | `_CRASH_CHILD` program → `capture.channels` | same |
| `tests/test_w0b_commissioning.py:863` | child program → `commissioning.session` | same |
| `tests/test_nightly_runner.py:274` | `(repo/relpath).exists()` → "git knows it (disk, index, or HEAD)" | the pin's claim is "the porcelain first column was not eaten"; `exists()` was a proxy that is FALSE for any deleted tracked file, so it reddens on every card that removes one. Kept its teeth: a first-character-eaten path is in none of the three places |
| `scripts/launch_stack.sh:503` | `python -c 'from parcel_robot.perception_daemon import default_socket_path'` → `.protocol` | the owner's launcher; it would have died at stack start |

Documentation truths corrected by the same sweep (they became false statements
*because of* this card): `src/parcel_robot/lidar/__init__.py:20` and
`src/parcel_robot/perception_daemon/__init__.py:21` (usage examples in the
barrels' own docstrings), `README.md` ×2, `docs/MOTION.md:452`,
`docs/NAVIGATION_CITY.md:98`.

Pins checked and found UNAFFECTED (no edit owed, recorded so the next card does
not re-check): `test_nm1_promotion_and_asks.py:564` and `test_p1d_vlm_veto.py:416`
(runtime.py's import set — none of its 18 rewritten statements resolves to a
`vlm_veto` leaf; verified module-by-module), `test_approach_traffic_wiring.py:200`
(`from .traffic_aware import RampMemory` is not a barrel import),
`test_perception_abstention.py:811`, `test_import_order_no_cycle.py:65`,
`test_capture_sidecar.py:1382`, `test_syncevents.py:1371`, `test_clockmap.py:1535`.

## 5. Cycles: broken vs grandfathered

**Package-edge: 25 → 8.** Twenty of the twenty-five baseline components are
gone outright — every cycle that existed only because a barrel executed its own
submodules: `realtime` (7), `detection_adapter` (6), `config↔skills` (5),
`duplex` (4), `bags`, `camera_channel`, `camera_channel.backends`, `context`,
`gnss`, `owner_model`, `perception_daemon` (3 each), `attention`, `capture`,
`contracts`, `counterfactual`, `lidar`, `low_viewpoint`, `owner_tracking`, `rl`
(2 each), and `runtime ↔ runtime_channels` (2, killed by the refinement). The
81-module knot fragmented into four small residual components (`route_memory` 5,
`perception_abstention ↔ vlm_veto` 4, `arrival_semantics ↔ goals` 2,
`grid_navigator ↔ models` 2), and `storefront` shrank 5 → 4 while `uwb` (4),
`camera_channel.backends.*` (4) and `maps` (3) persisted. Every current
component is a SUBSET of a baseline component, so nothing was swapped for a
same-sized new tangle.

**Leaf-only: 8 → 4.** `commissioning ↔ commissioning.session ↔ control ↔
control.factory` (4), `navigation ↔ envs ↔ metaurban_env ↔ pipeline` (4) and
`owner_model ↔ owner_model.distiller` (2) all died with the barrels; `runtime ↔
runtime_channels` (2) died with the refinement.

**Grandfathered — 4 leaf-only, 8 package-edge**, each with a one-line reason in
`GRANDFATHERED_CYCLES` in the new ratchet:

| model | cycle | reason |
|---|---|---|
| both | `camera_channel.backends.{physical,realsense,recorded,uvc}` (4) | `physical.py` holds BOTH the shared base classes and the `build_physical_backend` factory, whose per-kind lazy imports point back at the three concrete backends. Breaking it is a code MOVE (factory → `backends/factory.py`), not an import rewrite — out of scope for a behaviour-free card |
| both | `perception_abstention ↔ vlm_veto.{bureau,runner,verifier}` (4) | deliberate and pinned: the abstention vocabulary is declared in `perception_abstention` so the runtime can import it without importing a package that can import torch (`test_p1d_vlm_veto.py::test_the_runtime_imports_no_veto_module`). The reverse edge is one guarded function-local `from parcel_robot.vlm_veto.bureau import bureau_for` at `perception_abstention.py:893`; the ratchet counts function-local imports on purpose, so it stays visible. Retiring it needs an M2 Protocol seam |
| both | `navigation.arrival_semantics ↔ navigation.goals` (2) | `goals` imports the relation table at module scope; `arrival_semantics:382` reads `goals.OWNER_REFERENT_TABLE` back through a documented function-local import so there is ONE authority for "the owner". Retiring it means moving the shared table to a third leaf — a code move |
| both | `navigation.grid_navigator ↔ navigation.models` (2) | `models/__init__.py` defines `StubNavigator` AND `build_navigator`, which lazily builds `GridNavigator` (`models:404`), which lazily falls back to `StubNavigator` (`grid_navigator:236`) — the same factory/implementation knot as the camera backends |
| package-edge only | `route_memory` (5), `storefront` (4), `uwb` (4), `maps` (3) | the package `__init__` composes its `DOES_NOT_PROVE` tuple from its leaves' own tuples. That is code DEFINED in the `__init__` (the brief's stated exception), and any `__init__` importing its own leaf is a 2-cycle in the package-edge model by construction. The leaves themselves are acyclic |

No cycle was hidden by moving an import into a function: fact 1 says that does
not break a cycle in this model and is not a permitted fix, and none was used.
No `noqa` anywhere; no `# ---- CARD` marker added.

## 6. ARCH-1 forbidden reverse edges — all four hold TODAY

Measured over `src/parcel_robot`, zero violations, so every grandfather list in
`FORBIDDEN_EDGES` is **empty** — a hit is a real regression, never inherited debt:

- `contracts/*, config.py, models.py, robot_profile.py, authority.py` → never
  `runtime, web_panel, agent, realtime.*, providers, backends.*` — **0**
- `navigation/*, core/*, brain/*` → never `runtime, web_panel` — **0**
- `backends/go2.py, control/*` → never `sim, mujoco_lidar, headless_city,
  backends.mujoco` — **0**
- nothing in `src` imports `web_panel` — **0**

The rule roots are asserted to be real modules, so a renamed target cannot make
a rule silently vacuous.

## 7. The two ratchets

`tests/test_dec0_debt_ratchet.py` — the fact-2 refinement (`_is_type_checking_test`,
`_type_checking_import_ids`, one skip in `build_import_graph`) and a **downward-only**
re-freeze of `BASELINE` + `BASELINE_CYCLE_COMPONENTS`; every number verified to
have moved down or stayed. Header comment records what moved and why. 8 passed.

`tests/test_decig2_import_ratchet.py` — new, 15 cells, pure AST, imports no
product code, cold measurement **5.3 s** (budget 10 s), whole file 18.6 s.
Roots: `src, tests, scripts, tools, examples, evals`. Asserts:

- (a) no module imports a SYMBOL through a package barrel. Keyed on *is this
  name a submodule, or defined in the `__init__` itself* — NOT on what the
  barrel re-exports today, so it stays honest if a barrel is re-filled;
- (b) no `__init__.py` binds an imported name its own code never uses, and the
  set of `__init__`s that import at all equals `BARRELS_WITH_KEPT_IMPORTS`
  (allowlist with a reason each; a stale allowlist entry also reddens);
- (b2) `__all__` advertises only names the barrel binds;
- (c) every SCC sits inside one named `GRANDFATHERED_CYCLES` entry, count and
  width may only fall, and every grandfather entry must still name real modules
  and carry a real reason;
- (d) the four ARCH-1 rules;
- plus `test_the_graph_agrees_with_the_dec0_debt_ratchet` — one measurement,
  two ratchets: the two cycle models are asserted identical on the real tree so
  they cannot drift apart.

Six seeded-red cells, one per assertion (barrel symbol import · re-export
barrel · unbound `__all__` · new cycle · **widened** cycle · forbidden reverse
edge). Each re-runs the REAL measurement over the REAL tree plus one mutant
source, so a check that has gone vacuous cannot pass it; the barrel-symbol cell
also feeds the legal submodule form and asserts it stays clean.

`tests/test_decig1_leaf_imports.py` **deleted** — fully absorbed. Its
`MIGRATED_BARRELS` per-barrel check is subsumed by (a) tree-wide; its eight
`realtime` symbol pins by (b), which is strictly stronger (no barrel may
re-export anything); its `__all__` honesty check by (b2). Left in place it
would have gone RED-then-vacuous: its own guard-the-guard cell
(`test_migrated_barrels_have_reexports_to_protect`) requires the navigation
barrel to still re-export something.

## 8. Proof

All through `~/.cache/parcel-guard/pytest_guard.sh --label decig2` with `TMPDIR`
unset; never `-n auto`; never `ci_gate.py --tier`; the owner's `:8765` /
`/tmp/parcel_sim.sock` / `parcel_memory.sqlite3` untouched.

| suite | result |
|---|---|
| post-migration, pre-drain: `import_order_no_cycle`, `runtime`, `capture_envelope`, `hw2_go2_backend`, `w0b_commissioning` | 267 passed |
| post-drain, the pin-bearing files (8 suites) | 3 failed → all three diagnosed and ported (§4) → **534 passed** |
| brief's targeted set: `import_order_no_cycle`, `runtime`, `r24_lock_discipline`, `nominal_stop_wiring`, `cap1_admission`, `nm1_promotion_and_asks`, `p1d_vlm_veto`, `perception_abstention`, `approach_traffic_wiring` | 298 passed, 1 skipped |
| `test_dec0_debt_ratchet.py` | 8 passed |
| `test_decig2_import_ratchet.py` | 15 passed |
| **full `-m 'not slow' -n 8 --dist loadfile -p no:cacheprovider`, run 1** | 9,931 passed, 18 skipped, 1 xfailed, **1 failed** |
| **full, run 2 (after the run-1 fix)** | **9,932 passed, 18 skipped, 1 xfailed, 0 failed** |
| **full, run 3 (final tree, confirming)** | **9,932 passed, 18 skipped, 1 xfailed, 0 failed** |

Run 1's single red was NOT one of the two named pre-existing flakes:
`test_nightly_runner.py::test_the_dirty_path_list_keeps_whole_paths`, diagnosed
as a real (pre-existing) defect — see §4, row 13. Neither
`tests/test_yield_policy.py` nor
`test_dynamic_costs.py::test_cost_field_vectorization_performance` fired in
either run; `--dist loadfile` is the disposition DEC-IG-1 predicted.

**ruff:** `ruff check .` fingerprints vs `scripts/ci_ruff_baseline.json` —
**0 new**, and one baselined fingerprint RETIRED
(`src/parcel_robot/camera_channel/__init__.py::RUF022`, the unsorted `__all__`,
gone with the barrel). Zero `noqa` added anywhere.

## 9. Not done, and why

1. **`CODEBASE_INDEX.md` is stale and cannot be regenerated from this working
   tree.** `tools/codebase_index.py` enumerates `git ls-files` (`:79`) and reads
   every path unguarded (`inspect_py`, `:109`), so a tracked-but-DELETED file
   (`tests/test_decig1_leaf_imports.py`) makes both the tool and `--check` die
   with `FileNotFoundError`. Nothing in `ci_gate.py` runs it, so this does not
   gate the commit. **Integrator: regenerate after committing the deletion**
   (post-commit the path leaves `ls-files`), and consider a one-line existence
   guard in the tool — it will hit every future decomposition card.
2. **The four `DOES_NOT_PROVE` package-edge self-cycles were kept, not broken.**
   Killing them means moving a defined constant out of the `__init__` into a
   leaf and re-pointing 4 test imports — a code move, which this card forbids.
   Package-edge max SCC is 5 either way; the target was ≤ 10.
3. **The four leaf-only cycles are grandfathered, not broken** (§5). Each needs
   a code move or an M2 Protocol seam, both out of a behaviour-free import card.
4. **`navigation/models/__init__.py` was left byte-identical.** It is a
   412-line module, not a barrel; its 6 imports all serve code it defines. It is
   allowlisted with that reason rather than edited.
5. **Docs outside the brief's roots were corrected, not migrated wholesale.**
   `README.md`, `docs/MOTION.md`, `docs/NAVIGATION_CITY.md` each carried one
   import example this card made false; those lines were fixed. No other doc
   text was touched. If the verifier prefers zero doc edits, those four lines
   are the whole surface.
