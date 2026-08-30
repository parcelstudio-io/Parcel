# W3 · WORLD-IDENTITY-1 — STATUS (executor: Opus, 2026-08-30)

**Card:** `scrum/20260830/task_1/W3_WORLD_IDENTITY.md` (bars frozen) · **Verifier:** Fable
**Disposition: BUILD COMPLETE, EVERY ACCEPTANCE ROW GREEN.** One red in the wider sweep is
pre-existing at HEAD and proved so by an A/B (§6).

## 0. Pre-flight (integrator rule 1)

| row | value |
|---|---|
| worktree | `/home/jaewoo-jang/.cache/parcel-0e/wb/w3` (`git worktree add --detach … HEAD`) |
| worktree HEAD sha | `c96ac345358ec2786748fc3a885c35d32710c5e2` |
| `python -c "import parcel_robot; print(parcel_robot.__file__)"` | `/home/jaewoo-jang/.cache/parcel-0e/wb/w3/src/parcel_robot/__init__.py` ✅ the worktree, not the root |
| env | `PYTHONPATH=$PWD/src:$PWD`, `MUJOCO_GL=egl`, `OPENBLAS_NUM_THREADS=32`, `TMPDIR` unset, `PARCEL_MEMORY_PATH` → `~/.cache/parcel-0e/wb/w3-scratch/mem.sqlite3` (the owner's store is never opened) |
| host at launch | `06:36 up …, load 2.12`, 192 cpus; NAV-GEN-1 run at `load 2.19` with 16 workers (five other executors share the host) |
| main repo | never edited except this file; no `git add/commit/stash` anywhere |
| `?? .parcel` in `git status` | the venv symlink the dispatch asked for — not a file to stage |

## 1. What was built

**The value (new leaf):** `src/parcel_robot/navigation/world_identity.py` — `WorldIdentity(scene_id,
source, digest)`, frozen, with `from_model` (compiled MJCF; digest over the names blob + body/geom/
joint counts), `from_scene_file` (the MJCF's own `<mujoco model=…>` attribute + a digest of the file
bytes — for a root that has a path and no compiled model), `published` (the fallback's shape),
`matches(declared)` (the admission predicate: both sides must NAME something) and `as_dict`.
`scene_id_from_model` MOVED here from `poi_admission` — the primitive belongs with the type.
The module imports nothing from `navigation`, so a loader (`perception`, `simulation`, `evals`) can
hand the value to the policy (`navigation.poi_admission`) with no cycle.

**The policy:** `poi_admission.resolve_world_identity(world_identity, scene)` → `(identity, source)`
— **explicit first**, the process-scoped published scene second, `none` third; a value that is not a
`WorldIdentity` raises `TypeError` rather than falling back (a navigator told the wrong thing must
not look like one told nothing). `admit_poi(…, world_identity=…)` admits on `identity.matches(declared)`;
`PoiAdmission.identity_source` records who answered. `SceneInstanceSet` now carries the loader's typed
`identity`, so the FALLBACK is typed too (`publish_scene_semantics(…, identity=…)`).

**Reasons unchanged (bar 2):** `no_scene` and `scene_mismatch:<loaded>/<declared>` are F1's tokens
verbatim; an explicit identity changes only WHERE the loaded id comes from.

**The seam through the navigator:** `DirectiveNavigator(world_identity=…)` /
`from_config(…, world_identity=…)` → `self.world_identity` → `ground_admitted_poi` and
`poi_lookup_metadata`. `mission.metadata['identity_source']` is logged on **every** parse
(`explicit|published|none`), which is what carries the card's acceptance column into the rows.

**Composition roots that load a world and now pass it explicitly:**

| root | line at HEAD | what it passes |
|---|---|---|
| `simulation/headless_city.py` `HeadlessCityWorld.__init__` | :223 | `self.world_identity = world_identity_of(self.model)` |
| `simulation/headless_city.py` `HeadlessCityQualityHarness._run_navigation` | :735 | `from_config(…, world_identity=self.world.world_identity)` |
| `evals/nav_instruct/runner.py` `NavInstructRunner._navigator` (the minival AND the mutation panel) | :780 | `world_identity=self.world.world_identity` |
| `evals/nav_instruct/person_cell.py` | :263 | `world_identity=world.world_identity` |
| `evals/companion_nav/runner.py` `_run_navigate` | :373 | `world_identity=world.world_identity` |
| `runtime.py` `_attach_configured_camera_ingress` (the runtime's OWN model compile) | :13380 | `self.dog.set_world_identity(WorldIdentity.from_model(model))` |
| `web_panel.py` `RuntimeHTTPServer.__init__` (the scene this process is showing) | :226 | `runtime.dog.set_world_identity(WorldIdentity.from_scene_file(scene_path))`, guarded on the file existing |
| `skills/api.py` `Dog` (the runtime's navigator factory) | :148 | carries `world_identity` into the lazily built navigator; `set_world_identity` also updates a live one |

**Roots that load a world and have NOTHING to pass (recorded, not worked around):**

* `sim.py:204` (`run_simulator`) — a SEPARATE process that serves `/tmp/parcel_sim.sock`; it builds no
  `DirectiveNavigator` and holds no `Dog`. Its load publishes the same typed identity through
  `extract_city_semantics`, which is all a second process can offer.
* `web_panel.py:202` (`_extract_scene_geometry`) — a cached, runtime-free geometry payload for the
  viewer. The panel's explicit hand-off is made where the panel HAS the runtime (`RuntimeHTTPServer`).
* `navigation/envs/metaurban_env.py:38`, `safety_control_smoke.py:45`, `evals/cpu_budget_proxy.py:68`,
  `tools/release_parity_probe.py:37` — build a navigator with **no world loaded at all**; there is no
  identity to pass and inventing one would be the defect this card closes.
* `evals/external/*` (BARN v8 / habitat sidecars) — frozen bundle adapters, untouched.

## 2. Hunk adjacency (integrator rules 1 and the owner-diff constraint)

`git diff HEAD -- <file>` was read in the DIRTY ROOT first for every file I touch.

| file | my hunk headers (worktree) | the dirty root's hunk headers | overlap |
|---|---|---|---|
| `src/parcel_robot/runtime.py` | `@@ -13358` and `@@ -13380` — both inside `_attach_configured_camera_ingress`; **adjacent to `_attach_configured_camera_ingress`**, far from W1/W2's `_apply_goal_amend` / `_accept_plan` / `_narrate_mission` | 38, 422, 2196, 2254, 2508, 2658, 2670, 2685, 3193, 3777, 3803, 3819, 3833, 4950, 5106, 5331, 5356, 9428, 9545, 9574, 11481, 11855, 17968 | **none** |
| `src/parcel_robot/navigation/pipeline.py` | 107 (TYPE_CHECKING), 530 (ctor arg), 866 (ctor attr), 1093 (`from_config`), 1151/1172 (`parse`) | 11, 25, 1444, 1452, 3151, 3313, 3366, 4672, 4734, 5707, 5753 | **none** |
| `src/parcel_robot/simulation/headless_city.py` | 46, 162, 221, 732, 1079, 1100 | 28, 1160 | **none** (12 and 51 lines clear) |
| `perception/city_semantics.py`, `skills/api.py`, `web_panel.py`, `evals/*`, `tests/*` | — | not dirty in the root | — |

**MERGE NOTE the integrator must carry (a semantic adjacency, not a line overlap).** The dirty root
wraps `from .poi_admission import ground_admitted_poi, poi_lookup_metadata` (pipeline.py:28) in a
BARN-bundle `try/except` whose FALLBACK shims have the pre-W3 signatures
(`ground_admitted_poi(grounder, directive)` returning a goal; `poi_lookup_metadata(grounder, error)`).
W3 does not touch that region — it adds **no runtime import to pipeline.py** — but the two call sites
in `parse` now pass a third argument and unpack a `(goal, metadata)` pair. When the owner's diff and
this patch meet, those two shims need the same third parameter and the same pair (three lines). This
was the alternative to editing line 28, which the wave-B rule forbids.

## 3. Line-count and hygiene rows

| bar | before | after |
|---|---|---|
| `pipeline.py` net line count ("net-negative or unchanged") | **7211** | **7211** ✅ unchanged. +4 lines added (TYPE_CHECKING import, ctor arg, ctor attr, `from_config` passthrough); −4 by moving C1's five-line "why no POI answered" note into `poi_lookup_metadata`'s docstring, where the keys are actually built |
| `configs/` | untouched | untouched ✅ (`git status` shows no config path) |
| `config.py` | untouched | untouched ✅ |
| `noqa` added | 0 | **0** ✅ |
| `ruff check` on every touched file | — | **All checks passed** ✅ |
| safety floors / `semantic_source` / `pois_path` / reactive bands | untouched | untouched ✅ |
| cost | — | **$0** (no hosted call) |

## 4. Acceptance rows

### 4.1 Product-caller RED/GREEN pairs (the mechanism, in five lines)

Run in the worktree with `PARCEL_MEMORY_PATH` → scratch; `DirectiveNavigator.from_config(...).parse("go to the crosswalk near coffee, 42nd street")`:

| # | state | `goal_source` | `poi_refused` | `identity_source` |
|---|---|---|---|---|
| 1 | nothing loaded, nothing passed | `semantic_search` | **`no_scene`** | **`none`** |
| 2 | explicit demo-block identity, **nothing published** | **`known_poi`** (`crosswalk_a`) | — | **`explicit`** |
| 3 | published by the loader, nothing passed (F1's path) | `known_poi` | — | **`published`** |
| 4 | demo block PUBLISHED, navigator told it is on `parcel_val_unseen_880027` | `semantic_search` | `scene_mismatch:parcel_val_unseen_880027/parcel_city_block` | **`explicit`** |
| 5 | a directive naming no POI at all | `semantic_search` | *(absent — three facts stay three facts)* | `explicit` |

Row 2 is the capability the card adds (under C1/F1 it was `no_scene`); row 4 is the defect it closes;
rows 1/3/5 are F1's behaviour, unmoved. `WorldIdentity.from_model` and `from_scene_file` agree on
`parcel_city_block` and disagree on the digest by construction (different bytes) — pinned as a test.

### 4.2 NAV_INSTRUCT v4 minival digest — **BAR MET**

```
.parcel/bin/python -m evals.nav_instruct.run_nav_instruct_v1 --minival --mode baseline \
  --episode-version v4 --no-ledger --out ~/.cache/parcel-0e/wb/w3-scratch/minival
# digest: tests/test_nav_instruct_digest_recipe.report_digest(drop_aggregate_scene=True, compact=True)
```

| row | value |
|---|---|
| report digest | **`021b67ab73c4e7be647aba1a17e20a193ebf23b826a18d5b0990e296e5708496`** |
| the card's bar | `021b67ab73c4e7be647aba1a17e20a193ebf23b826a18d5b0990e296e5708496` |
| equal | **YES** ✅ |
| episodes | 25, elapsed 20.5 s |
| `nav-region_goal-D-15-1b8b2361` | keeps `reason = navigation_step_limit_inside_goal` (it still grounds through the table) ✅ |

The runner is a composition root that now passes the identity explicitly, and the digest did not move.

### 4.3 Mutation panel — **BAR MET**

```
.parcel/bin/python scripts/mutation_panel.py --out ~/.cache/parcel-0e/wb/w3-scratch/panel.json
```

| row | value | bar |
|---|---|---|
| `passed` | **True** | True ✅ |
| `survivors` | `[]` | `[]` ✅ |
| `clean_run.authority` | **`{"agreement": 4, "authority_disagreement": 1}`** | {4, 1} ✅ |
| `clean_checks` | `no_authority_disagreement False`, `no_false_arrival/path_length_plausible/zero_collisions True` | identical to the HEAD panel recorded in `C1_STATUS.md` §F1.4 ✅ |

(The panel ran at HEAD in this worktree; `scripts/mutation_panel.py` is dirty in the ROOT — Sol's
remediation, which is W5's card, not this one.)

### 4.4 NAV-GEN-1 A0 — **BARS MET** (byte-identical where only W3 differs; `explicit` on every row)

```bash
# scenes first, in my own scratch — the manifest is the SAME 30 worlds C1-F1 measured
env -u TMPDIR OPENBLAS_NUM_THREADS=32 NG1_SCRATCH=~/.cache/parcel-0e/wb/w3-ng1 \
  MA1_SCRATCH=~/.cache/parcel-0e/wb/w3-ng1/ma1recipe \
  .parcel/bin/python research/20260829/nav-gen-attribution-1/run.py --stage prepare
# -> {"scenes": 30, "manifest_sha256": "b698e0594a7d456050bb3740e2c961da7748dd19dd8f25b643904d1729b4ab43"}
#    == the manifest sha in C1's own scenes.json  ✅ (its 30 cached MJCFs were copied in, never written to)
… run.py --arms A0 --seed 20260829 --workers 16     # 530 episodes, wall 325.9 s, host load 2.2 at launch
```

**The attribution arm.** C1-F1's published rows were measured on 2026-08-29 in the DIRTY shared root;
this worktree is clean `HEAD c96ac34`. So the byte-identity row is measured where **only W3 differs**:
a `git archive HEAD` export (`~/.cache/parcel-0e/wb/w3-head`) ran the same command, same seed, same
16 workers, same scene cache, immediately before the build landed.

| row | HEAD (345.9 s) | **HEAD + W3 (325.9 s)** | bar |
|---|---|---|---|
| **rows differing on ANY pre-existing column** | — | **0 of 530** ✅ | byte-identical |
| columns present only in the W3 arm | — | `identity_source` (the card's own column) | — |
| **`identity_source == "explicit"`** | n/a (column absent) | **530 / 530** ✅ | on every row |
| generated `target_id == 'crosswalk_a'` | 0/90 | **0/90** ✅ | 0/90 |
| generated `target_id == 'crosswalk'` | 90/90 | **90/90** ✅ | — |
| generated crosswalk `false_arrival` | 0/90 | **0/90** ✅ | — |
| generated crosswalk strict | 55/90 = 0.6111 | **55/90 = 0.6111** ✅ | — |
| frozen demo block crosswalk `known_poi` | 16/16 | **16/16** ✅ | 16/16 known_poi |
| `known_poi` rows in the whole run | 16 of 530 | **16 of 530** ✅ | — |
| frozen-block rows changed | — | **0 of 80** ✅ | — |
| collisions | 0 | **0** ✅ | — |
| generated crosswalk `goal_source` / `poi_refused` | — | `semantic_search` 90/90, `scene_mismatch:parcel_val_unseen_8800NN/parcel_city_block` — each row its own scene | — |
| frozen crosswalk `goal_source` / `target_id` / `poi_refused` | — | `known_poi` / `crosswalk_a` / `None` | — |

**The C1-F1 comparison, and why it is not W3's.** Against C1's own `rows_A0.json`, 205 of 530 rows
differ — and they differ **identically at HEAD**: `C1-F1 vs HEAD` and `C1-F1 vs HEAD+W3` are the SAME
205 rows with the SAME values (checked key by key). W3 adds **exactly zero** to that pre-existing
drift. The moved columns are drive-path (`terminal_xy` 204, `path_length_m` 202, `steps` 180,
`minimum_clearance_m` 138) and the headline C1-F1 invariants all still hold at HEAD (`crosswalk_a`
0/90, false arrivals 0/90, frozen 16/16). Most likely cause, recorded for the integrator, NOT claimed:
C1's F1.2 rows were measured in the dirty root, whose uncommitted diff includes
`navigation/grid_planner.py` (+235) and `navigation/pipeline.py` (+470) — both on the drive path — and
two commits (`f3ecb5c`, `a379bf4`) have landed since. Whoever re-freezes NAV-GEN-1 numbers should
price this; it is visible at HEAD with or without this card.

Raw rows: `~/.cache/parcel-0e/wb/w3-ng1/raw/rows_A0.json` (W3) and
`~/.cache/parcel-0e/wb/w3-ng1-head/raw/rows_A0.json` (the HEAD arm).

**One line was added to the harness** (`research/20260829/nav-gen-attribution-1/run.py`, beside C2's
`goal_source` line): `row["identity_source"] = r.identity_source`. It is the only way the card's
"`identity_source=explicit` on every row" bar can be read off a row; the value is plumbed
`mission.metadata` → `HeadlessTaskResult.identity_source` → row, exactly as C2 plumbed `goal_source`.

## 5. Tests

| suite | result |
|---|---|
| `tests/test_poi_admission.py` | **25 passed** (was 19 at C1 close; +6 new W3 cases) ✅ |
| `tests/test_c3_cutover.py` | **54 passed** ✅ (B3 now asserts `identity_source == "explicit"`) |
| `tests/test_navigation.py` | **38 passed** ✅ |
| `tests/test_person_aware_nav.py` | **19 passed** ✅ (the two driving tests hand `_drive` the identity) |
| `tests/test_runtime.py` | **61 passed** ✅ |

The two tests the card names, by name:

* `test_no_identity_and_no_published_scene_refuses_with_no_scene` — no identity, no publication ⇒
  `poi_refused = "no_scene"`, `identity_source = "none"`, on the product caller AND on the leaf.
* `test_an_explicit_identity_wins_over_a_stale_published_scene` — both directions: the demo block
  PUBLISHED + a navigator told it is on `parcel_val_unseen_880000` ⇒ refused; a generated scene
  published + a navigator told it is on the demo block ⇒ `known_poi`.

Four more: `…_answers_with_nothing_published_at_all` (the new capability),
`…_scene_file_and_the_compiled_model_agree_on_the_identity` (two readers, one name),
`…_world_hands_its_identity_to_the_navigator_the_harness_builds` (the composition root end to end,
through `HeadlessCityQualityHarness`), `…_wrongly_typed_identity_raises_instead_of_falling_back`.

**Fixtures now supplying an explicit identity where they can:** the four F2/F3 `demo_scene_loaded`
fixtures now `yield world_identity_of(model)` (the same product load, as a value). Two callers take
it: `test_c3_cutover.py::test_B3…` (its subject IS the POI table) and `test_person_aware_nav.py`'s
`_drive` helper (the two tests that drive to `crosswalk_a`). `test_navigation.py` (10 controller
tests) and `test_runtime.py` (the runtime path) keep building their navigators as before and so
exercise the PUBLISHED fallback — deliberate: their subject is the controller and the runtime, the
fallback is the contract F1 froze for exactly that case, and rewriting 10 foreign call sites would be
churn with no claim behind it.

## 6. The regression sweep, and the one red (attributed)

27 POI/navigator/loader-touching files, run through the guard as ONE suite-scale invocation
(`pytest_guard.sh --label W3-sweep2`, `-p no:cacheprovider`, no `-n`):

```
1 failed, 583 passed, 7 skipped in 117.02s
FAILED tests/test_person_cell.py::test_deadlock_signature_reproduces_with_an_undeclared_bystander
```

Files: `test_poi_admission, test_c3_cutover, test_navigation, test_runtime, test_person_aware_nav,
test_city_semantics, test_headless_city_tasks, test_arrival_settle, test_a2_navglue,
test_k0_arrival_authority, test_unknown_place_admission, test_superlative_directives, test_agent,
test_cpu_budget_proxy, test_person_cell, test_dr2_pose_drift_arm, test_navigator_pause,
test_semantic_navigation_regressions, test_nav_metamorphic, test_web_panel, test_viewer_panel,
test_skills, test_dec0_debt_ratchet, test_decig2_import_ratchet, test_portability_proof,
test_all_ray_yaw_swept_shield_v8, test_scene_semantics`.

**The red is NOT W3's — A/B proved, not argued.** The same node id, run in the pure-`HEAD` export
(`~/.cache/parcel-0e/wb/w3-head`, no W3 files at all), fails identically:
`assert outcome.veto_fraction >= 0.9` → `0.875`. It is a frozen-threshold row about the D-15 gate,
and nothing in this card can move a veto fraction: `person_cell.run_cell` starts its navigator from a
prebuilt `Mission` object, so `parse` — the only method W3 touches — is never called on that path.
Recorded for whoever owns the D-15 register; the W3 hunk in that file is one keyword argument.

**One ratchet caught W3 and W3 paid it (first sweep, fixed):**
`tests/test_dec0_debt_ratchet.py::test_no_new_long_function` reddened with
`['extract_city_semantics']` — my six comment lines pushed a 97-line function to 103 against the
100-line ceiling. Fixed by moving the prose to `world_identity_of`'s docstring rather than by
touching the baseline: `extract_city_semantics` is **97 lines at HEAD → 98 now**, two under the
ceiling and one over where it started, and all 23 DEC-0 / DEC-IG2 ratchet cases
pass, including `test_no_new_import_cycle` (the new leaf imports nothing from `navigation`, so the
`skills → navigation.world_identity` and `web_panel → navigation.world_identity` edges close nothing).

## 7. The committed state IS the tested state

The `SceneInstanceSet.identity` equality tweak and the `city_semantics` comment move landed AFTER the
first instrument sweep, so all three headline instruments were re-run on the FINAL tree:

| instrument | first run | **final tree** |
|---|---|---|
| NAV-GEN-1 A0 | 530 rows, wall 325.9 s | **530 rows, wall 329.4 s — 0 rows differ from the first W3 run** (determinism), 0 rows differ from HEAD on any pre-existing column, `identity_source=explicit` 530/530 |
| v4 minival digest | `021b67ab…` | **`021b67ab…`** ✅ |
| mutation panel | passed True, `[]`, {4, 1} | **identical on every field except `generated_at`** ✅ |

## 8. Diff

```
 evals/companion_nav/runner.py                  |   4 +-
 evals/nav_instruct/person_cell.py              |   4 +-
 evals/nav_instruct/runner.py                   |   3 +
 research/20260829/nav-gen-attribution-1/run.py |   5 +
 src/parcel_robot/navigation/pipeline.py        |  16 +--
 src/parcel_robot/navigation/poi_admission.py   | 174 +++++++++++++++++++-----
 src/parcel_robot/perception/city_semantics.py  |  26 +++-
 src/parcel_robot/runtime.py                    |   6 +
 src/parcel_robot/simulation/headless_city.py   |  20 ++-
 src/parcel_robot/skills/api.py                 |  21 ++-
 src/parcel_robot/web_panel.py                  |   9 ++
 tests/test_c3_cutover.py                       |  16 ++-
 tests/test_navigation.py                       |  10 +-
 tests/test_person_aware_nav.py                 |  40 ++++--
 tests/test_poi_admission.py                    | 178 ++++++++++++++++++++++++-
 tests/test_runtime.py                          |  10 +-
 16 files changed, 467 insertions(+), 75 deletions(-)
+ NEW FILE (untracked): src/parcel_robot/navigation/world_identity.py — 156 lines, 0 noqa
  (`?? .parcel` is the venv symlink the dispatch asked for, not a file to stage)
```

**Tested at candidate sha `c96ac345358ec2786748fc3a885c35d32710c5e2` in worktree
`/home/jaewoo-jang/.cache/parcel-0e/wb/w3`** (integrator rule 4). The worktree contains W3's files and
nothing else: `git diff` there IS the patch, and the owner's/Sol's hunks are in none of it.

## 9. What this does NOT prove

* Nothing about physical motion (NO-GO stands) and nothing about off-oracle grounding — the identity
  gates the demo POI TABLE, not the learned map or the camera.
* The runtime hook is exercised only where the runtime compiles a world (`perception.camera_ingress`,
  OFF by shipping default), and the panel hook only when a panel is started with a scene path; both
  are unit-untested product paths in this card (the `Dog` seam beneath them is covered by
  `tests/test_runtime.py`'s 61 green cases running through the published fallback, which is the
  behaviour they had before).
* `sim.py`'s process still has no navigator to tell — the identity crosses that boundary as a socket
  protocol change nobody has asked for, and this card did not invent one.
* The 205-row NAV-GEN-1 drift between C1-F1's published rows and clean HEAD is MEASURED here, not
  explained; it exists with or without W3.
