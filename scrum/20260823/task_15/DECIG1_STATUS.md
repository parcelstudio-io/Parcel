# DEC-IG-1 — leaf-import migration, unlocked packages — STATUS

Card: `scrum/20260823/task_15/README.md`, amended by DEC-0's measured
findings (`scrum/20260823/task_14/DEC0_REGISTRY.md` §11.1).
Measurement script (scratchpad, disposable): an independent AST resolver
written for this card; it reproduces the DEC-0 ratchet's four numbers
exactly (25/81 package-aware, 8/4 leaf-only) before any edit, which is what
makes the before/after comparable.

## 1. Worklist, re-derived

DEC-0 said **11 files**; an AST scan (parenthesized-import aware) finds
**12 files / 57 symbol imports**. DEC-0's list was keyed on
`DirectiveNavigator` and so missed `tests/test_runtime.py:25`, which reaches
`GoalPose, MidLevelCommand, Mission, SemanticGoal` through the same barrel.
Everything else in DEC-0's list reproduced.

`from parcel_robot.navigation import <submodule>` (16 sites: `goals`,
`pipeline`, `reactive_safety`, `approach`, …) is a **module** import, not a
barrel re-export, and was correctly left alone.

## 2. Files touched (13 statements, import lines only)

Migrated `parcel_robot.navigation` barrel -> defining leaf module:

| file | statements |
|---|---|
| `examples/nav_city_smoke.py` | 1 |
| `src/parcel_robot/skills/api.py` | 2 (both function-local; indentation preserved) |
| `tests/test_arrival_etiquette_pipeline.py` | 1 |
| `tests/test_k4_opus_wiring.py` | 1 |
| `tests/test_navigation.py` | 1 |
| `tests/test_portal_world.py` | 1 |
| `tests/test_pose_consumers.py` | 1 |
| `tests/test_runtime.py` | 1 |
| `tests/test_semantic_navigation_regressions.py` | 1 |
| `tests/test_superlative_directives.py` | 1 |
| `tests/test_value_directed_search.py` | 1 |
| `tests/test_ve_detection_lock_on.py` | 1 |

Symbols resolve **transitively**: `navigation.envs` is itself a barrel, so
`MetaUrbanNavEnv` lands on `navigation.envs.metaurban_env`.

Also: `src/parcel_robot/realtime/__init__.py` — the 8 lane re-exports
deleted (see §4); `tests/test_decig1_leaf_imports.py` — new.

Ordering done with `ruff check --select I --fix`, which also merged the
duplicate `navigation.goals` block it created in `tests/test_navigation.py`.
`ruff check` clean on every touched file; **zero** `noqa` added.
`ruff format` NOT run: 11 of the 13 files already fail `ruff format --check`
at HEAD (verified against pristine `git show HEAD:` copies), so formatting
them would have produced a large diff unrelated to this card.

## 3. Numbers, before -> after

| quantity | before | after | note |
|---|---|---|---|
| barrel-mediated edges, whole tree | 947 | **890** | −57 |
| ...via `parcel_robot.navigation` | 57 | **0** | barrel fully drained |
| import cycles, package-aware | 25 | 25 | unchanged |
| max SCC, package-aware | 81 | 81 | unchanged |
| import cycles, leaf-only | 8 | 8 | unchanged |
| max SCC, leaf-only | 4 | 4 | unchanged |

`tests/test_dec0_debt_ratchet.py` is **green**; no baselined number improved,
so there is nothing to re-freeze.

### Why the package-aware count did not drop

The dispatch expected it to. It cannot, from this card's permitted edits, for
two measured reasons:

1. **Leaf-migrating an importer cannot remove a package-aware edge, by
   construction.** Python executes `navigation/__init__.py` when you import
   `navigation.pipeline`, so `from parcel_robot.navigation.pipeline import
   DirectiveNavigator` charges the *same* ancestor edge as the barrel form.
   The migration is real but documentary — it only pays off once the barrel
   itself is thinned. (Compounding this: 11 of the 12 migrated files are
   tests/examples, which are outside the ratchet's graph scope entirely.
   `src/parcel_robot/skills/api.py` is the only graph node in the worklist.)
2. **The 81-module SCC contains zero `realtime` modules.** It is a
   navigation / brain / control / core / online_map / route_memory /
   vlm_veto / voice / instructnav / commissioning / backends knot. Breaking
   it means thinning *those* barrels, which this card explicitly forbids
   ("Barrels themselves are UNTOUCHED this card"). **The 81 belongs to
   DEC-IG-2.**

## 4. Discovery — the realtime lane re-exports (needs a decision)

DEC-0 is right that the 8 lane symbols have **zero** importers: an AST sweep
of `src/ tests/ scripts/ tools/ examples/` finds none, and there is no
string-form monkeypatch target (`"parcel_robot.realtime.<sym>"`) either.
All 8 symbol re-exports are therefore **deleted**, and `__all__` went 43 -> 35.

But DEC-0's scan was symbol-level, and it could not see a **side-effect**
user. Deleting the `from .lane import ...` line also stops
`parcel_robot/realtime/__init__.py` from *executing* `lane.py`, and that is
pinned:

- `tools/replay_turn_detection.py:679` — docstring stating that the
  module-level `from parcel_robot.realtime.config import ...` "executes
  `parcel_robot.realtime.__init__`, which imports `lane`".
- `tests/test_truth1_texts.py::test_the_offline_modes_reach_lane_and_never_reach_ws_transport`
  — asserts `"lane True"` from a fresh-interpreter subprocess probe,
  explicitly to keep that docstring honest.

Dropping the submodule import is a **real win**: `lane.py` + `tool_broker.py`
(~6.8k lines) leave the import path of every process that touches
`realtime.config`, and the realtime SCC falls **7 -> 5** (modules trapped in
some cycle 158 -> 156). Measured, both ways.

**It is not taken here.** Taking it needs a co-edit of `tools/` (LOCKED for
this card) and of another card's test (`tests/test_truth1_texts.py`, not this
card's OWNS) — and CLAUDE.md says edit only your card's OWNS. So this card
deletes the eight **symbol** re-exports (the mandate's substance:
`from parcel_robot.realtime import RealtimeLane` now fails) and deliberately
**retains `from . import lane`**, preserving the pinned side effect and every
boundary. The retained line carries a comment pointing here.

**Decision for the verifier / DEC-IG-2**, one line to take the win:
delete `from . import lane` and `"lane"` from `__all__`, update the
`replay_turn_detection.py` docstring, and flip that TRUTH-1 assertion to
`"lane False"` — which is the stronger claim the tool's docstring originally
tried to make.

## 5. Proof

Through `~/.cache/parcel-guard/pytest_guard.sh --label decig1`, never `-n auto`,
never `ci_gate.py --tier`, git read-only.

- 10 migration-touched suites + `test_truth1_texts.py` — 9 passed, 1 failed
  (the §4 discovery, before it was resolved).
- `test_dec0_debt_ratchet.py`, `test_p1b_map_learns.py`,
  `test_cap1_admission.py`, `test_runtime.py`,
  `test_import_order_no_cycle.py`, `test_relation_registry.py`,
  `test_approach_traffic_wiring.py` — **171 passed**.
- `tests/test_decig1_leaf_imports.py` — 5 passed, and **mutation-checked**:
  re-introducing one barrel import reddens it, and re-adding one deleted
  re-export reddens it. It is not a vacuous guard.
- Full `-m 'not slow'` suite, `-n 8`: **9921 passed, 1 failed** — the failure
  is `tests/test_yield_policy.py`, which this card never touched.

### The one red is a PRE-EXISTING suite flake, proven by control

`tests/test_yield_policy.py` fails nondeterministically in a full-suite shard
and passes in isolation. It cannot be reached by this card: it already used
leaf `navigation.*` imports before the migration, and this card's
`realtime/__init__.py` executes an **identical submodule set** to HEAD
(`config, ingress, lane, protocol, spend_ledger, transport, voice_identity`),
so import-time side effects are unchanged; nothing anywhere reads the barrel
namespace dynamically (`getattr`/`import_module`/`vars` sweep: zero hits).

Measured, four full-suite runs at `-n 8`:

| tree state | failures (all in `test_yield_policy.py`) |
|---|---|
| DEC-IG-1 applied, run 1 | **1** |
| DEC-IG-1 applied, run 2 | **9** |
| **clean HEAD, no DEC-IG-1 changes**, run 1 | **12** |
| **clean HEAD, no DEC-IG-1 changes**, run 2 | **14** |

The control was taken by restoring `git show HEAD:` content over this card's
13 files and hiding the new test, running, then restoring (git itself stayed
read-only; the working tree was byte-identical afterwards, re-verified by
`git diff --stat` and a green re-run). **The failure is strictly worse at HEAD
than with this card applied**, so DEC-IG-1 does not cause or worsen it.

Mechanism: the suite sets no `dist` mode, so xdist uses round-robin
`--dist load`; `test_yield_policy.py`'s runtime fixtures pick up cross-file
state from whichever neighbours share their worker, and the neighbour set
changes every run. `tests/test_yield_policy.py -n 8` **alone** is 90/90 green.
This is a real latent defect in the suite's parallel isolation and belongs to
whoever owns `test_yield_policy.py` / `yield_aside` — flagged, not adopted.

## 6. New test

`tests/test_decig1_leaf_imports.py` — pure AST, imports no product code (same
discipline as the DEC-0 ratchet, so import-time side effects cannot perturb
it). Asserts: (a) no module reaches a re-exported symbol through a migrated
barrel, submodule imports excepted; (b) the symbols DEC-IG-1 removed from the
`realtime` barrel stay gone, in both the re-exports and `__all__`; (c)
`__all__` advertises nothing the barrel does not bind. Extension points for
DEC-IG-2 are the module constants `MIGRATED_BARRELS` and `THINNED_BARRELS`.
A scan-sanity test fails if the file walk ever collapses to nothing.
