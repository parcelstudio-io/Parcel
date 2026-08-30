# C1 · POI-ORACLE-1 — executor status (Opus)

**Card:** `scrum/20260829/task_2/C1_POI_ORACLE.md` (+ Amendment A1) · **Verifier:** Fable · **Second lens:** parcel-fb
**Written incrementally:** pre-flight → RED → fix → GREEN → close.

---

## 0. Pre-flight

| fact | value |
|---|---|
| host at start | `21:39 EDT`, load 1.72 / 3.80 / 4.89, 192 cores (shared with other executors — all runs capped at 16 workers) |
| scratch | `NG1_SCRATCH=/home/jaewoo-jang/.cache/parcel-0e/c1/ng1` (own; the 08-29 run's `~/.cache/parcel-0e/ng1` is read-only reference) |
| scene manifest | `prepare` rebuilt all 30 scenes in my scratch: `manifest_sha256 = b698e0594a7d456050bb3740e2c961da7748dd19dd8f25b643904d1729b4ab43` — **byte-identical to the 08-29 run's manifest**, so RED/GREEN are on the same geometry |
| `pipeline.py` lines BEFORE | **7203** |
| `config.py` | untouched (unread, unedited) |
| configs | untouched — `configs/navigation/default.yaml`, `demo_pois.yaml`, `semantic_source`, `pois_path` all unchanged (**Amendment A1 (1)**) |
| `noqa` added | **0** (`grep -c noqa` on both new files = 0) |
| hosted calls | none, $0 |
| git | read-only; no commits, no checkout, no stash |

**Amendment A1 recorded.** (1) No config changes on this card — none were made. (2) "crosswalk strict ≥ 0.60" measures the semantic ladder, not the fix: it is reported below beside the bar and **the ladder was not tuned**; the fix's own rows are `target_id == 'crosswalk_a'` and false arrivals on generated scenes.

### 0.1 The geometry that decides this card (measured, not assumed)

The merged `crosswalk` region (`perception/city_semantics._merge_crosswalk_regions`) of each scene, and its distance to the POI coordinate `crosswalk_a = (3.5, -0.6)`:

| scene | crosswalk polygon | distance from (3.5, −0.6) |
|---|---|---|
| **demo block** `src/parcel_robot/scenes/city_block.xml` | `[2.35, −0.40] .. [3.85, 2.00]` | **0.200 m — the POI is OUTSIDE the demo crosswalk** |
| generated 880027 | `[2.739, −0.732] .. [4.239, 1.570]` | **0.000 m (inside)** |
| generated 880018 | `[1.943, −0.945] .. [3.443, 1.561]` | 0.057 m |
| generated 880009 | `[1.906, −0.893] .. [3.406, 1.659]` | 0.094 m |
| generated 880008 | `[2.653, −0.341] .. [4.153, 1.733]` | 0.259 m |
| generated 880020 | `[2.064, −0.290] .. [3.564, 2.142]` | 0.310 m |
| the other 25 generated seeds | — | 0.616 m … 5.671 m |

This is the fact that decides the shape of the fix, and it is measured off the scene files themselves (`scenes/city_block.xml`, `~/.cache/parcel-0e/c1/ng1/ma1recipe/scenegen/configs/scenes/generated/ma1_8800NN.xml`).

---

## 1. RED — the defect reproduced, in my own scratch

> **Bar (verbatim):** "RED first: `env -u TMPDIR OPENBLAS_NUM_THREADS=32 .parcel/bin/python research/20260829/nav-gen-attribution-1/run.py --arms A0 --seed 20260829 --workers 16` (set `NG1_SCRATCH` to your own scratch) reproduces crosswalk `false_arrival` 42/90 and `target_id == 'crosswalk_a'` 90/90 before the fix."

```bash
env -u TMPDIR OPENBLAS_NUM_THREADS=32 NG1_SCRATCH=/home/jaewoo-jang/.cache/parcel-0e/c1/ng1 \
  .parcel/bin/python research/20260829/nav-gen-attribution-1/run.py --stage prepare
env -u TMPDIR OPENBLAS_NUM_THREADS=32 NG1_SCRATCH=/home/jaewoo-jang/.cache/parcel-0e/c1/ng1 \
  .parcel/bin/python research/20260829/nav-gen-attribution-1/run.py --arms A0 --seed 20260829 --workers 16
# 530 episodes, wall 331.4 s, 16 workers; rows kept as raw/rows_A0_RED.json
```

| RED row | measured | card's number |
|---|---|---|
| generated crosswalk `target_id == 'crosswalk_a'` | **90/90** | 90/90 ✅ |
| generated crosswalk `false_arrival` | **42/90** | 42/90 ✅ |
| generated crosswalk strict success | 6/90 = 0.0667 | 6 "succeed by accident" ✅ |
| generated crosswalk reasons | `navigation_no_progress` ×48 (42 failures + the 6 accidental successes), `arrived` ×42 | ✅ |
| generated per-target strict | bench 0.7222 · lamppost 0.8333 · planter 0.7000 · sidewalk 0.9333 | RESULTS.md §7.1 ✅ |
| generated collisions | **0** | 0 ✅ |
| frozen demo block crosswalk `target_id == 'crosswalk_a'` | **16/16** | 16/16 ✅ |

RED is an exact reproduction of NAV-GEN-1's A0 arm on independently rebuilt scenes.

---

## 2. The fix

**Shape:** one leaf module + a net-negative hook in `parse`, exactly as the card asks — plus **one publication line in a file outside my OWNS, declared in §5.**

| file | change |
|---|---|
| `src/parcel_robot/navigation/poi_admission.py` | **NEW leaf** (435 lines). Typed scene-instance set, the admission predicate, the process-scoped published scene, `PoiRefused(LookupError)`, and the two functions `parse` calls. Imports only `math`, `collections.abc`, `dataclasses`, `typing`, `robot_profile` — no navigation import, so nothing can cycle. |
| `src/parcel_robot/navigation/pipeline.py` | `goal = self.grounder.ground(directive)` → `goal = ground_admitted_poi(self.grounder, directive)`; `except LookupError` → `except LookupError as poi_error`; the 6-line `poi_disabled` block → `**poi_lookup_metadata(self.grounder, poi_error)`; one import added at the existing grounder import. **2 changed lines inside `parse` + 1 import; net −3 lines** (see §6.1 — the shared file also carries C3's concurrent edit, so the −3 is attributed by reconstruction). |
| `src/parcel_robot/navigation/grounder.py` | docstring only: `ground()` still answers the TABLE; whether the scene lets the answer stand is decided one layer up. No behaviour change (`PlaceGrounder.ground` is byte-identical, which is why the direct-grounder tests in `test_c3_cutover.py` / `test_superlative_directives.py` are untouched). |
| `src/parcel_robot/perception/city_semantics.py` | **+7 lines (6 comment, 1 call) + 1 import**: `visible_city_semantics` publishes the specs it was handed. See §5. |
| `tests/test_poi_admission.py` | **NEW**, 15 tests, table-driven over the demo block and NAV-GEN-1 seeds 880000 / 880027 built by `evals.nav_instruct.scene_gen.build_scene` into pytest scratch. |

**The rule.** A POI answers unless the loaded scene *refutes* it: the scene declares an instance of that POI's class and the nearest one is further than the body's own footprint radius (`DEFAULT_ROBOT_PROFILE.footprint_radius_m` = 0.32 m) from the POI coordinate. Then `PoiRefused` (a `LookupError`, the signal `parse` already falls through on) carries the reason into `metadata['poi_refused']` and the semantic ladder runs. Admitted → `metadata['goal_source']` stays `known_poi`, unchanged.

**Why the band is the footprint and not the region's declared `arrival_radius_m` (0.12 m).** The demo POI is **0.200 m OUTSIDE** the demo block's crosswalk (§0.1) — a stand-just-before-it pose, not a point in the region. A region goal in this stack "succeeds by footprint containment" (`navigation/arrival_semantics.py:211`), so "a body standing here touches the region" is the product's own predicate and it is the *smallest declared* band that keeps the demo block grounding — which E3 requires: `evals/nav_instruct/episodes/v4/nav-region_goal-*` is `"go to the crosswalk"` on that scene.

**The reason a harness reads** (seed 880000, through `DirectiveNavigator.parse`, `mission.metadata['poi_refused']`):

```
POI crosswalk_a at (3.50, -0.60): the loaded scene declares 1 'crosswalk' instance(s)
and the nearest ('crosswalk') is 2.41 m away, outside the 0.32 m body band — this
scene does not contain that place
```

**Three refusal-adjacent facts are kept apart** so a harness can tell them apart: `poi_grounding_disabled` (card C-3, off-oracle empty table), `poi_refused` (this card), and "the directive named no POI" (neither key — the shipped, untagged path).

**Measured, on generated seed 880000, through `DirectiveNavigator.parse`:**

```
go to the coffee shop    known_poi        coffee_42nd      (cafe: not modelled by any city scene)
go to the bookstore      known_poi        bookstore_main   (shop: not modelled)
go to the park           known_poi        park_entrance    (park: not modelled)
go to the crosswalk      semantic_search  -                (REFUTED: 2.41 m > 0.32 m)
go to the bench          semantic_search  -                (never a POI directive)
```

**Deliberately narrower than the card's literal text, and this is the one design deviation.** "The scene declares no instance of that class at all" (a cafe, a bookstore, a park — no shipped city scene models any of them) is **not** a refutation, so those three demo POIs are untouched on every scene. Refusing there would change grounding for 3 of the 4 demo POIs everywhere on zero measured evidence — the card's own "Does not prove" line reserves the other three classes. The outcome is named (`class_not_modelled`) and is one line away from being flipped to a refusal if the verifier wants it.

---

## 3. GREEN — the same instrument, after the fix

```bash
env -u TMPDIR OPENBLAS_NUM_THREADS=32 NG1_SCRATCH=/home/jaewoo-jang/.cache/parcel-0e/c1/ng1 \
  .parcel/bin/python research/20260829/nav-gen-attribution-1/run.py --arms A0 --seed 20260829 --workers 16
# 530 episodes, wall 329.8 s, 16 workers; rows at raw/rows_A0.json (RED kept at raw/rows_A0_RED.json)
```

| bar (verbatim) | RED | GREEN | verdict |
|---|---|---|---|
| "`target_id == 'crosswalk_a'` **0/90** on generated scenes" | 90/90 | **15/90** | **NOT MET — and it is unreachable; proof in §4.** 75/90 refused |
| board row's "`target_id == 'crosswalk'` 90/90" (the scene's own instance) | 0/90 | **75/90** | the 15 remainder are the seeds whose own crosswalk *does* back the coordinate |
| "crosswalk false arrivals **0/90**" | 42/90 | **6/90** | **NOT MET.** All 6 are on the 15 rows the E3 band must admit; 0/75 on every row the fix moved |
| "crosswalk strict success **≥ 0.60**" | 0.0667 | **0.5333** (48/90) — **0.6400** (48/75) on the rows the fix moved | measured, **not tuned** (Amendment A1 (2)) |
| "**0 collisions**" | 0 | **0** | ✅ |
| "all other targets' rows **byte-identical** to the RED run" | — | **0 of 360 non-crosswalk generated rows changed**; bench 0.7222 / lamppost 0.8333 / planter 0.7000 / sidewalk 0.9333 unchanged | ✅ |
| "Frozen block … crosswalk on the demo block still grounds via `known_poi` (16/16)" | 16/16 | **16/16** `target_id == 'crosswalk_a'` | ✅ |
| "every other frozen row byte-identical" | — | **0 of 80 frozen rows changed at all** (crosswalk included) | ✅ |

**What actually moved.** Exactly 75 rows changed, all of them generated `crosswalk`:

| subset | n | `target_id` | strict | false arrivals | vs RED |
|---|---|---|---|---|---|
| refused → semantic ladder | 75 | `crosswalk` (the scene's own region) | **48 = 0.6400** | **0** | all 75 changed |
| admitted (scene backs the coordinate) | 15 | `crosswalk_a` | 0 | 6 | **byte-identical to RED, 15/15** |

The 15 admitted rows are seeds 880008 (3), 880009 (3), 880018 (3), 880020 (3), 880027 (3) — §0.1's five scenes whose own crosswalk is within a body of the POI coordinate. Their 6 false arrivals stop 0.63–1.86 m from the nearest crosswalk band: that is the **POI point goal's 1.5 m arrive radius**, i.e. the arrival authority C2 owns, not the admission rule. Nothing else in the 530 rows moved.

Reasons, generated crosswalk: RED `navigation_no_progress` ×48 / `arrived` ×42 → GREEN `arrived_verified` ×46 / `navigation_no_progress` ×28 / `semantic_target_unreachable` ×10 / `arrived` ×6.

---

## 4. The `0/90` bar is unreachable — proof, not an excuse

The card asks for **both** `target_id == 'crosswalk_a'` 0/90 on generated scenes **and** 16/16 on the demo block, from a rule that reads "the scene's semantic instance set contains an instance of that class whose geometry contains or abuts the POI coordinate". Those three requirements are jointly unsatisfiable, and the geometry says why (§0.1, measured off the scene files):

* the **demo block's** crosswalk is **0.200 m** from the POI coordinate — the POI is *outside* it;
* generated **880027 contains it (0.000 m)**, **880018 is 0.057 m**, **880009 is 0.094 m** — all three *strictly closer* than the demo block.

So for any admission rule that is a monotone function of POI-to-instance distance (which "contains or abuts within a band" is), admitting the demo block admits at least those three scenes: **≥ 9/90 is the floor, whatever band is chosen**, and 0/90 is only reachable by refusing the demo block too — which breaks the card's own frozen 16/16 bar and E3's `nav-region_goal-*` episodes. The card's own unit-test row says the same thing from the other side: it *requires* 880027 to be admitted.

Sensitivity, so the verifier can pick a different point without re-running:

| band | demo block | generated `crosswalk_a` | note |
|---|---|---|---|
| 0.12 m (region's declared `arrival_radius_m`) | **REFUSED — E3 breach** | 9/90 | worse on both bars |
| 0.21–0.258 m (a number picked from the fixture; declared nowhere) | admitted | 9/90 | the floor of the proof — still not 0 |
| **0.32 m (body footprint — shipped)** | admitted | **15/90** | the smallest *declared* band that keeps E3 |
| 1.5 m (the POI point-goal arrive radius) | admitted | 33/90 | — |

Under the honest reading of the fix's intent — *the table must not answer where the scene contradicts it* — the fix is complete: **75/75 of the scenes that contradict the coordinate now refuse it, 0 false arrivals among them, and 0 non-crosswalk rows moved.** The residual 15/6 are scenes that do **not** contradict it. I did not move the criterion; it is recorded here for the verifier, together with the one-line sensitivity to change the band.

---

## 5. OWNS deviation, declared: one publication line outside my card

**What I changed outside OWNS:** `src/parcel_robot/perception/city_semantics.py` — one import and one call (plus a 6-line comment) at the top of `visible_city_semantics`:

```python
    # Card C1 (POI-ORACLE-1). The venue that is DRIVING publishes the scene it
    # loaded, so `navigation.poi_admission` can refuse a demo POI whose
    # coordinate the scene refutes. This function — not `extract_city_semantics`
    # — is the hook because only a world stepping a robot calls it, so a truth
    # or eval extraction never speaks for a venue. Re-publishing the same two
    # lists is an identity check, not a rebuild.
    publish_scene_semantics(regions, objects)
```

**Why it was unavoidable.** The card says to consult "the same source `HeadlessCityWorld` / the learned map expose as `legal_instance_ids`". I looked for that seam and **it does not exist**: `DirectiveNavigator` is built from a config path (`headless_city.py:735`), every scene fact reaches it through per-frame `observation.extras['semantic_candidates']`, and `parse` runs *before the first observation*. `HeadlessCityWorld` holds `_region_specs` / `_object_specs` and hands them to nobody but the extractor. With `headless_city.py` off-limits (C2's) and `runtime.py` off-limits (owner's diff), there is no in-OWNS place from which the loaded scene can reach `parse`. So the hook is the smallest typed one I could find, and it is *not* a new global: it is the same process-scoped published-source idiom `perception_source.selection` already uses for `active_semantic_source()` / `active_learned_map()`, with the state and the types living in the C1 leaf module.

**Why `visible_city_semantics` and not `extract_city_semantics`.** Only a world that is *stepping a robot* calls the visible-set function (`HeadlessCityWorld.observe`, `sim.py:300`); `extract_city_semantics` is also called by truth/eval helpers (`evals/nav_instruct/scene_truth.py`) and by tests that merely inspect a scene file. Hooking the extractor would let a scene nobody is driving speak for the venue and make POI grounding order-dependent across a pytest process. `HeadlessCityWorld.__init__` calls `reset()`, which ends in `observe()` — so the scene is published before any navigator exists, which is what makes the decision available at `parse` time.

**If the verifier prefers it elsewhere:** the whole seam is `publish_scene_semantics(regions, objects, scene=...)`. Moving the call into `HeadlessCityWorld.__init__` (C2's file) or into `runtime.py` is a one-line move with no change to this card's rows; the venue simply has to publish before it parses.

**Blast radius of the publication.** A venue that publishes a scene declaring `crosswalk` instances more than 0.32 m from `(3.5, −0.6)` now refuses `crosswalk_a` in `parse`. That is: NAV-GEN-1's generated scenes (the point of the card), the alternate held-out validation scene if a world is ever built on it, and nothing else in the tree — the demo block admits, and cafe/bookstore/park are `class_not_modelled` everywhere. `PlaceGrounder.ground` itself is untouched, so every direct-grounder test (`test_c3_cutover.py:409`, `test_superlative_directives.py:195`) is unaffected by construction.

---

## 6. Tests, line counts, hygiene

### 6.1 `pipeline.py` line count — before / after, attributed

C3 is editing the same file concurrently (the watchdog region, `~4616`), so a raw before/after would be confounded. Both numbers are reported:

| reading | lines |
|---|---|
| `git show HEAD:…/pipeline.py` (a379bf4) | 7203 |
| tree immediately BEFORE my edit (21:54) | **7203** |
| tree immediately AFTER my edit (22:07) | **7200** |
| tree now (C1 + C3's concurrent leaf extraction) | 7198 |
| **tree now with only C1's two hunks reversed** | **7201** |

**C1's own contribution: −3 lines.** `pipeline.py` did not grow. `config.py` untouched.

### 6.2 Test runs (every one through the guard, `TMPDIR` unset, never `-n auto`)

```bash
env -u TMPDIR ~/.cache/parcel-guard/pytest_guard.sh --label C1 .parcel/bin/python -m pytest \
  tests/test_a2_navglue.py tests/test_k0_arrival_authority.py tests/test_voice_nav_e2e.py \
  -k "crosswalk or poi or ground" -q
# 3 passed, 35 deselected, 83.97s   <- the card's named subset

env -u TMPDIR ~/.cache/parcel-guard/pytest_guard.sh --label C1 .parcel/bin/python -m pytest \
  tests/test_poi_admission.py -q
# 15 passed, 1.68s                  <- the card's new unit tests

env -u TMPDIR ~/.cache/parcel-guard/pytest_guard.sh --label C1 .parcel/bin/python -m pytest \
  tests/test_mutation_panel_freshness.py -q
# 2 failed, 2 passed, 37.07s        <- the pre-existing D-15 red; attribution below

env -u TMPDIR ~/.cache/parcel-guard/pytest_guard.sh --label C1 .parcel/bin/python -m pytest \
  tests/test_poi_admission.py tests/test_c3_cutover.py tests/test_navigation.py \
  tests/test_superlative_directives.py tests/test_agent.py tests/test_voice_nav_e2e.py \
  tests/test_a2_navglue.py tests/test_k0_arrival_authority.py tests/test_headless_city_tasks.py \
  tests/test_semantic_navigation_regressions.py tests/test_unknown_place_admission.py \
  tests/test_portal_world.py tests/test_scene_surface_truth.py tests/test_scene_semantics.py \
  tests/test_arrival_etiquette_pipeline.py -q
# 372 passed, 1 failed, 1 xfailed, 1 error, 681.80s   <- wider POI/scene/nav sweep

env -u TMPDIR ~/.cache/parcel-guard/pytest_guard.sh --label C1 .parcel/bin/python -m pytest \
  tests/test_voice_nav_e2e.py -q                       # C1 active, file alone
# 1 failed, 16 passed, 1 xfailed, 723.75s
env -u TMPDIR PYTHONPATH=~/.cache/parcel-0e/c1 ~/.cache/parcel-guard/pytest_guard.sh --label C1 \
  .parcel/bin/python -m pytest tests/test_voice_nav_e2e.py -q -p c1_disable_admission
# 1 failed, 16 passed, 1 xfailed, 726.73s              <- identical with C1 off (§7.2)

env -u TMPDIR ~/.cache/parcel-guard/pytest_guard.sh --label C1 .parcel/bin/python -m pytest \
  tests/test_decig2_import_ratchet.py tests/test_dec0_debt_ratchet.py -q
# 2 failed, 21 passed, 40.11s   <- import ratchet green; both debt reds are the owner's diff (§7.3)
```

### 6.3 The new unit tests (the card's list, verbatim)

| card's row | test |
|---|---|
| "POI admitted on the demo scene" | `test_crosswalk_poi_admission_per_scene[demo-block-abuts]`, `test_parse_grounds_or_refuses_by_scene[demo-block-keeps-known_poi]` |
| "refused on a generated scene with no crosswalk near the coordinate" | `…[generated-no-crosswalk-near]`, `…[generated-refuses]`, `test_the_driving_venue_publishes_its_own_scene` |
| "admitted on a generated scene whose crosswalk polygon contains the coordinate (seed 880027)" | `…[generated-polygon-contains]`, `…[generated-that-contains-it-keeps-known_poi]` |
| "`poi_refused` reason carried" | `test_refusal_and_disabled_and_not_a_poi_are_told_apart` (all three metadata shapes), `test_parse_grounds_or_refuses_by_scene[generated-refuses]` |
| "`goal_source` logged" | every `parse` case asserts `goal_source`; `known_poi` on admit, `semantic_search` + reason on refuse |
| (added) the band, the identity check, the BARN-bundle grounder shape, the untouched shipped path | `test_the_band_is_the_body_and_the_demo_block_needs_all_of_it`, `test_publishing_the_same_specs_twice_is_an_identity_check`, `test_a_grounder_without_a_table_still_admits_by_the_goals_own_label`, `test_parse_is_unchanged_when_no_venue_published_a_scene` |

The generated scenes in these tests are built by `evals.nav_instruct.scene_gen.build_scene` into pytest's own scratch (with the `third_party` symlink the emitted MJCF needs) — nothing is written into the repo, and no research scratch is read.

### 6.4 Hygiene

* `ruff check` clean on all five files; **0 `noqa` added** (`grep -c noqa` = 0 in `poi_admission.py` and `tests/test_poi_admission.py`).
* No `config.py`, no config YAML, no safety floor, no `semantic_source`, no frozen eval, no `headless_city.py`, no file from the owner's uncommitted diff.
* No git writes (no commit, checkout, stash, worktree). `CODEBASE_INDEX.md` NOT regenerated — it is shared with the other executors' new files; the integrator regenerates once at close.
* Import order checked in both directions (`perception.city_semantics` first, `navigation.pipeline` first, `simulation.headless_city`): no cycle — `poi_admission` imports only `math`, `dataclasses`, `collections.abc`, `typing`, `robot_profile`.

---

## 7. Every red on this tree is attributed — by A/B, not by argument

Both reds were re-run with C1's admission **neutralised at runtime** — a scratch pytest plugin that makes `poi_admission.active_scene_instances()` return `None`, which restores the exact pre-C1 answer (the table answers whatever the scene is) while leaving every other line of the tree, including the publication call and its timing, in place:

```python
# scratch plugin, not in the repo
def pytest_configure(config):
    poi_admission.active_scene_instances = lambda: None
```

### 7.1 `tests/test_mutation_panel_freshness.py` — 2 failed (C0's D-15 row)

| run | result |
|---|---|
| C1 active | `committed={'authority': {'agreement': 4, 'authority_disagreement': 1}, …}` vs `live={'authority': {'agreement': 5}, …}`; `payload["passed"] is False` |
| **C1 neutralised** | **byte-identical failure text**, same two tests |

This is exactly the red `C0_C2_ARRIVAL_SETTLE.md` opens with ("red on `main` (a379bf4) on the `nav-region_goal-D-15-1b8b2361` row … parcel-fb's clean-worktree bisection attributes it to the owner's a379bf4"). It is also structurally impossible for C1 to have caused it: `nav-region_goal-D-15` runs on the demo block, whose crosswalk **admits** the POI (the frozen NAV-GEN-1 block proves it, 16/16 unchanged), and its `placement_overrides` are `{'robot': …}` only — no region is moved or removed. Across the whole frozen v4 set the only override keys are `robot`, `absent_target`, `remove_entities`, `owner_path`, `pedestrian_distractors`, `distractors`.

### 7.2 `tests/test_voice_nav_e2e.py::test_sit_next_to_the_lamppost_settles_beside_it_in_a_sit` — 1 failed

| run | result |
|---|---|
| C1 active, in the 15-file sweep | `failed / semantic_target_unreachable`, `unreachable_candidates: ['lamp_post_1', 'lamp_post_2']`, `gate_blocked_steps: 60` |
| **C1 neutralised, file alone** | same failure, same reason, same unreachable candidates, same `gate_blocked_steps: 60` — `1 failed, 16 passed, 1 xfailed in 726.73s` |
| **C1 active, file alone** | same failure again — `1 failed, 16 passed, 1 xfailed in 723.75s` |

The two isolated runs are the same test, the same reason and the same counts with the admission on and off: the red is on the tree, not on this card.

"sit next to the lamppost" never touches the POI table (`lamppost` is not a `demo_pois.yaml` row; the mission carries `goal_source: semantic_search` with no `poi_*` key in **both** runs). The tree currently also carries **C3's concurrent `pipeline.py` watchdog/stall-leaf edit** (`from . import stall_attribution as stall`, `_progress_watchdog` rewritten), which is the other change live in this file today — flagging it for the integrator rather than diagnosing another card's region.

### 7.3 DEC ratchets — `test_decig2_import_ratchet.py` green, `test_dec0_debt_ratchet.py` 2 failed (owner's diff)

Not on the card's list; I ran them because C1 adds a module and a cross-package import edge.

* **`tests/test_decig2_import_ratchet.py`: green.** The new edge is
  `perception.city_semantics → navigation.poi_admission`; `navigation/__init__.py` is a
  docstring only and `poi_admission` imports nothing from `perception`, so no SCC gains a
  member and no ARCH-1 reverse edge is crossed. My import is a submodule import, not a barrel
  symbol.
* **`tests/test_dec0_debt_ratchet.py`: 2 failed, both the OWNER's uncommitted diff.**
  `new module(s) above 1000 lines: audio/voice_loop.py, brain/executive.py, bridge/protocol.py,
  control/motion_gateway.py`; `new function(s) above 100 lines: _accept_wire_state_locked,
  _play, _run_session, _transition, arm_and_set_target,
  build_motion_gateway_commissioned_control_manager, from_mapping, report, request_interrupt`.
  Every path and every name is from the gateway/bridge/control/executive diff the board puts
  off-limits in wave A. C1's own module is **435 lines** with a **50-line** longest function
  (`admit_poi`), so it appears in neither list — and `pipeline.py` shrank.

The `ERROR` on `test_come_here_closes_on_the_owner_and_stay_releases_the_hold` in the 15-file sweep did **not** reproduce when the file was run alone (16 passed there): it is a cross-file ordering artifact of the combined run, not a standing red.

---

## 8. Close

### 8.1 Every bar, one line each

| bar | status |
|---|---|
| RED reproduced (`crosswalk_a` 90/90, false arrivals 42/90) | ✅ exact |
| GREEN `target_id == 'crosswalk_a'` 0/90 | ❌ **15/90** — unreachable, proof in §4; 75/75 of the refuting scenes refuse |
| GREEN crosswalk false arrivals 0/90 | ❌ **6/90** — all 6 on the 15 rows E3 forces to admit; **0/75** on every row the fix moved |
| GREEN crosswalk strict ≥ 0.60 | ⚠️ **0.5333** over all 90; **0.6400** over the 75 the fix moved. Measured, not tuned (A1 (2)) |
| GREEN 0 collisions | ✅ 0 |
| GREEN other targets byte-identical | ✅ 0 of 360 rows changed |
| Frozen block `known_poi` 16/16 | ✅ 16/16 |
| Frozen block every other row byte-identical | ✅ 0 of 80 frozen rows changed |
| Named regression subset green | ✅ 3 passed |
| `test_mutation_panel_freshness.py` | ⚠️ 2 failed — **proved not C1's** by A/B (§7.1) |
| `test_dec0_debt_ratchet.py` (not card-required) | ⚠️ 2 failed — every path/name is the **owner's diff** (§7.3); `test_decig2_import_ratchet.py` green |
| New table-driven unit tests | ✅ 15 passed |
| No `noqa`, `config.py` unchanged, `pipeline.py` not longer | ✅ 0 / unchanged / **−3** |

### 8.2 What the verifier should re-run through the product caller

```bash
# 1. the rows (RED kept beside GREEN in my scratch)
.parcel/bin/python ~/.cache/parcel-0e/c1/rows.py \
  ~/.cache/parcel-0e/c1/ng1/raw/rows_A0_RED.json ~/.cache/parcel-0e/c1/ng1/raw/rows_A0.json
# 2. the geometry behind §0.1 and §4
.parcel/bin/python ~/.cache/parcel-0e/c1/crosswalk_geometry_survey.py
# 3. the A/B that attributes the two reds (scratch pytest plugin, not in the repo)
env -u TMPDIR PYTHONPATH=~/.cache/parcel-0e/c1 ~/.cache/parcel-guard/pytest_guard.sh --label C1 \
  .parcel/bin/python -m pytest tests/test_mutation_panel_freshness.py -q -p c1_disable_admission
# 4. the product caller itself, no harness:
#    HeadlessCityWorld(<generated scene>) then DirectiveNavigator.from_config().parse(
#    "go to the crosswalk") -> goal_source semantic_search + metadata['poi_refused'];
#    HeadlessCityWorld() (demo block) -> known_poi / crosswalk_a.
#    That is tests/test_poi_admission.py::test_the_driving_venue_publishes_its_own_scene.
```

### 8.3 Open decisions left for the verifier (none of them taken by me)

1. **The band.** Shipped at the body footprint, 0.32 m. §4's table gives the exact `crosswalk_a` count at 0.12 / 0.21–0.258 / 0.32 / 1.5 m. Nothing below 0.20 m keeps E3.
2. **`class_not_modelled` → refusal?** One line in `admit_poi` (§2). It would refuse coffee shop / bookstore / park on every city scene; no evidence on this card measures that, so I left it admitting.
3. **Where the publication call lives.** `visible_city_semantics` today (§5); moving it into `HeadlessCityWorld.__init__` (C2) or `runtime.py` (owner's diff) is a one-line move and changes no row here.
4. **The 6 residual false arrivals** are the POI point goal's 1.5 m arrive radius on scenes that genuinely contain the crosswalk — C2's arrival authority, not admission.

### 8.4 Files touched

```
NEW   src/parcel_robot/navigation/poi_admission.py      (leaf, 435 lines, 0 noqa)
NEW   tests/test_poi_admission.py                       (15 tests)
NEW   scrum/20260829/task_2/C1_STATUS.md                (this file)
EDIT  src/parcel_robot/navigation/pipeline.py           (parse hook, net −3)
EDIT  src/parcel_robot/navigation/grounder.py           (docstring only)
EDIT  src/parcel_robot/perception/city_semantics.py     (publication, OUTSIDE OWNS — §5)
```

Nothing else. No git writes, no hosted calls, no config, no `headless_city.py`, no owner-diff file, no research folder written.

---

# Follow-up F1 — scene IDENTITY replaces geometric admission

**Integrator's ruling (parcel-fb, adopted), verbatim in effect:** the POI table's
coordinates are facts about ONE scene; a polygon on seed 880027 that happens to contain
`(3.5, −0.6)` does not make "crosswalk near coffee, 42nd street" true there. Geometric
admission answered on coincidence — and §3's own rows priced it: the 15 coincidence-admitted
episodes carried all 6 remaining false arrivals while the 75 refused ones carried none.

**RED for F1 = §3's GREEN** (the geometric cut): `crosswalk_a` 15/90, false arrivals 6/90,
crosswalk strict 0.5333. Rows kept at `~/.cache/parcel-0e/c1/ng1/raw/rows_A0_F1RED.json`.

## F1.1 What the rule is now

| requirement | where |
|---|---|
| (1) the table declares its scene | `configs/navigation/cities/demo_pois.yaml` top-level **`scene_id: parcel_city_block`**, documented in a 19-line header block. The value is the scene's own identity — the MJCF `<mujoco model="…">` name of `src/parcel_robot/scenes/city_block.xml` — not a nickname, so it cannot drift from the scene |
| (2) admission = identity | `poi_admission.admit_poi(...)`: `loaded == declared` and nothing else. The loaded id rides on the published scene (`SceneInstanceSet.scene_id`), read from the compiled model by `scene_id_from_model` |
| (3) no published scene ⇒ REFUSED | `OUTCOME_NO_SCENE`, token `no_scene`. Fail-closed: a real robot under the oracle source is never answered by the demo table |
| (4) the token | `metadata['poi_refused'] = "scene_mismatch:<loaded>/<declared>"` or `"no_scene"`. An undeclared table yields `scene_mismatch:<loaded>/` — empty after the slash — so it matches nothing, everywhere |
| (5) geometry is a diagnostic | `geometry_diagnostic()` → `PoiAdmission.geometry_backed / nearest_instance_id / nearest_distance_m`. Computed, reported, **never consulted**. On 880027 it says `True` on a refusal — that disagreement is the point |
| (6) E3 | frozen demo block 16/16 `known_poi`; NAV_INSTRUCT v4 minival digest unchanged (F1.4) |

**Where the identity is published (addendum 2).** In the LOADER, once:
`perception.city_semantics.extract_city_semantics(model)` — the single place that holds both the
compiled model (the identity) and the specs. Every product path that loads a city scene goes
through it before it builds a navigator: `HeadlessCityWorld.__init__` (the headless harness **and**
the NAV_INSTRUCT eval runner, `evals/nav_instruct/runner.py:712`), `sim.py:204` (the runtime's sim
adapter), `web_panel.py:202`. C1's first cut published from `visible_city_semantics` (per-frame,
driving venues only); F1 **moved** the hook because the identity only exists where the model does,
and one publication in the loader is what makes "no published scene" impossible on any product
path that actually loaded the demo block.

## F1.2 GREEN — NAV-GEN-1 A0, same command, same scratch

```bash
env -u TMPDIR OPENBLAS_NUM_THREADS=32 NG1_SCRATCH=/home/jaewoo-jang/.cache/parcel-0e/c1/ng1 \
  .parcel/bin/python research/20260829/nav-gen-attribution-1/run.py --arms A0 --seed 20260829 --workers 16
# 530 episodes, wall 330.1 s, 16 workers (host load 5.5 at launch; C3's suite was running)
```

| bar | C1 geometric (F1's RED) | **F1 GREEN** |
|---|---|---|
| generated `target_id == 'crosswalk_a'` (bar **0/90**) | 15/90 | **0/90** ✅ |
| generated `target_id == 'crosswalk'` (the scene's own region) | 75/90 | **90/90** ✅ |
| generated crosswalk `false_arrival` (bar **0/90**) | 6/90 | **0/90** ✅ |
| crosswalk strict success on the 90 ladder rows (expect ≈ 0.60) | 0.5333 | **54/90 = 0.6000** ✅ *measured, not tuned* |
| collisions | 0 | **0** ✅ |
| frozen demo block crosswalk `known_poi` | 16/16 | **16/16** ✅ |

**Now measured directly, not by proxy.** C2 landed `goal_source` / `poi_refused` in
`HeadlessTaskResult` (card item 3, moved to C2), so the rows say it themselves:

* generated crosswalk: `goal_source` **`semantic_search` 90/90**, each row carrying
  `poi_refused = scene_mismatch:parcel_val_unseen_8800NN/parcel_city_block` — its own scene id;
* frozen demo block crosswalk: `goal_source` **`known_poi` 16/16**, `poi_refused` null;
* whole run: exactly **16 of 530** rows are `known_poi`, and they are the demo block's crosswalk.

Generated crosswalk reasons: `arrived_verified` ×52, `semantic_target_unreachable` ×38 — no
`arrived` (the false-arrival class) at all.

## F1.3 Clean attribution — HEAD vs HEAD+C1-F1, isolated

The shared tree moved between §3's run and F1's: **C2** landed the settle work (the rows gained
`settled`, `settle_frames_observed`, `settled_success`, `arrived_verified`,
`inside_arrival_region`, `arrival_not_verified_reason` — and `goal_source` / `poi_refused`, card
item 3, which was moved to C2) and **C3** landed the stall class (`navigation_no_progress` →
`semantic_target_unreachable` on 24 non-crosswalk rows). A before/after against my own earlier run
can no longer attribute anything, so the "byte-identical" row is measured where only C1 differs:
two trees extracted from `HEAD 704ba5c` with `git archive` (no git write), the same 30 cached
scenes (`MA1_SCRATCH` shared), the same seed, 16 workers, run one after the other.

```bash
git archive HEAD | tar -x -C ~/.cache/parcel-0e/c1/wt-head     # pure HEAD
git archive HEAD | tar -x -C ~/.cache/parcel-0e/c1/wt-f1       # + C1-F1 files only
env -u TMPDIR OPENBLAS_NUM_THREADS=32 MUJOCO_GL=egl PYTHONPATH=$WT/src:$WT \
  MA1_SCRATCH=~/.cache/parcel-0e/c1/ng1/ma1recipe NG1_SCRATCH=~/.cache/parcel-0e/c1/ab/<arm> \
  .parcel/bin/python $WT/research/20260829/nav-gen-attribution-1/run.py \
  --arms A0 --seed 20260829 --workers 16
```

| row | HEAD (337.1 s) | **HEAD + C1-F1** (325.9 s) |
|---|---|---|
| generated `target_id == 'crosswalk_a'` | 90/90 | **0/90** ✅ |
| generated `target_id == 'crosswalk'` | 0/90 | **90/90** ✅ |
| generated crosswalk `false_arrival` | 41/90 | **0/90** ✅ |
| generated crosswalk strict | 6/90 = 0.0667 | **55/90 = 0.6111** ✅ |
| bench / lamppost / planter / sidewalk strict | 0.7222 / 0.8333 / 0.7111 / 0.9333 | **identical** |
| **non-crosswalk generated rows changed** | — | **0 of 360** ✅ |
| collisions | 0 | **0** ✅ |
| **frozen demo block rows changed** | — | **0 of 80** ✅ (crosswalk `crosswalk_a` 16/16) |
| rows changed in total | — | 90, every one a generated crosswalk |

## F1.4 E3 — the two frozen demo-block instruments, in isolated worktrees

Both run from `git archive HEAD` trees with `.parcel` symlinked, `PYTHONPATH=<wt>/src:<wt>`,
`MUJOCO_GL=egl`, no owner diff — the arm named "+C1-F1" carries only `poi_admission.py`,
`grounder.py`, `city_semantics.py`, `demo_pois.yaml` and C1's three `pipeline.py` hunks.

**NAV_INSTRUCT v4 minival** (`python -m evals.nav_instruct.run_nav_instruct_v1 --minival --mode
baseline --episode-version v4 --no-ledger --out <scratch>`; digest by
`tests/test_nav_instruct_digest_recipe.report_digest(drop_aggregate_scene=True, compact=True)`):

| arm | report digest |
|---|---|
| HEAD | `021b67ab73c4e7be647aba1a17e20a193ebf23b826a18d5b0990e296e5708496` |
| **HEAD + C1-F1** | **`021b67ab73c4e7be647aba1a17e20a193ebf23b826a18d5b0990e296e5708496`** ✅ equal |

All **25 of 25 rows byte-identical**, and `nav-region_goal-D-15-1b8b2361` keeps
`reason = navigation_step_limit_inside_goal` (it still grounds through the table). The
`10251e42…` the integrator measured came from a mid-edit snapshot of my tree: at that moment
`poi_admission` already required an identity while the publication still came from
`visible_city_semantics`, which has no model and therefore published `scene_id = ""` — every scene
mismatched. Moving the hook into the loader is what fixed it (F1.1).

**Mutation panel** (`scripts/mutation_panel.py`, same isolated recipe):

| arm | passed | survivors | clean authority | clean checks |
|---|---|---|---|---|
| HEAD | True | `[]` | `{agreement: 4, authority_disagreement: 1}` | `no_authority_disagreement` False, other three True |
| **HEAD + C1-F1** | **True** | **`[]`** | **`{agreement: 4, authority_disagreement: 1}`** | **identical** |

The two panel payloads are **byte-identical on every field except `generated_at`**, and both match
the committed `evals/nav_instruct/results/mutation_panel.json` on `passed`, `survivors`,
`clean_run` and `clean_checks` (the committed artifact's only other difference is the
`episode_set_provenance` sentence C0 appended in this working tree).

## F1.5 The addendum-4 pair, as a test

`tests/test_poi_admission.py::test_the_eval_and_panel_runner_path_keeps_known_poi`:

| | call | result |
|---|---|---|
| RED | `DirectiveNavigator.from_config().parse("go to the crosswalk")`, nothing loaded | `goal_source=semantic_search`, `poi_refused="no_scene"` |
| GREEN | the same call after `NavInstructRunner(...)` (the eval **and** panel runner) constructs its world | `goal_source=known_poi`, `poi_id=crosswalk_a`, `poi_refused=None` |
| GREEN | the same call after `HeadlessCityWorld()` | `known_poi` |

`no_scene` and `scene_mismatch` stay **distinct** tokens
(`test_no_scene_and_scene_mismatch_stay_distinct_reasons`): a real robot under the oracle source
with no map loaded is legitimately `no_scene` and that refusal is correct there. The runners were
never supposed to be in that state, and now cannot be — the identity is published by the loader
they all go through.

## F1.6 Fallout the ruling creates, reported not fixed (foreign OWNS)

Requirement (3) — "no published scene ⇒ REFUSED" — changes a contract that **11 unit tests in two
files I do not own** assert: they parse a POI directive with no world anywhere in the process and
expect the table to answer.

```
tests/test_c3_cutover.py::test_B3_oracle_keeps_the_poi_table_and_its_known_poi_grounding
tests/test_navigation.py  (10)  test_dog_navigate_api · test_metaurban_env_stub_episode ·
  test_directive_navigator_stub_aligns_then_moves_toward_goal ·
  test_directive_navigator_turns_away_from_close_obstacle ·
  test_stub_exits_avoidance_without_a_bearing_when_obstacle_clears[None] · [1.5] ·
  test_stub_latches_obstacle_identity_and_world_tangent_until_corridor_is_clear ·
  test_stub_uses_full_lidar_to_make_bounded_progress_around_static_obstacle ·
  test_navigation_pipeline_preserves_intentional_lateral_motion ·
  test_stub_turns_in_place_for_goal_behind_robot
```

Mechanism: each does `nav.start("go to the crosswalk")` / `dog.navigate("go to the coffee shop on
42nd")` and then reads `mission.goal`, which is now `None` (`AttributeError`) or `goal_source ==
semantic_search`. Measured in isolation: `test_c3_cutover.py` **1 failed / 53 passed**,
`test_navigation.py` **10 failed / 28 passed**.

**They are order-dependent, which is worth the integrator's attention.** In a process where any
earlier test builds a demo-block world (`tests/test_mutation_panel_freshness.py`,
`tests/test_headless_city_tasks.py`, …) the scene is published and the same 11 tests pass — the
run `test_mutation_panel_freshness + test_c3_cutover + test_navigation + test_agent +
test_superlative_directives + test_cpu_budget_proxy + test_unknown_place_admission` is **212
passed, 2 failed** (the two failures are C0's D-15, §7.1). This is inherent to a process-scoped
seam plus a fail-closed default, not to the identity rule: the same 11 tests are green the moment
their venue exists. The honest fix is one line per file (build a `HeadlessCityWorld()` — or
publish the demo scene — in a fixture, or assert the refusal); both files are outside my OWNS, so
I have changed neither. **The integrator's call.**

`tests/test_superlative_directives.py` and `tests/test_c3_cutover.py`'s other POI cells are
unaffected: they call `PlaceGrounder.ground` directly, and that method is still the table's own
answer, unchanged.

## F1.7 Hygiene after F1

| check | value |
|---|---|
| `pipeline.py` | **7211** lines now (C3 is still editing it); with only C1's three hunks reversed **7214** → **C1's own delta is still −3**. F1 changed one comment inside `parse`, net 0 |
| `poi_admission.py` | 487 lines, longest function `admit_poi` 54 lines (DEC-0 ceilings: 1000 / 100) |
| `noqa` added | **0** across all five files |
| `ruff check` | clean on all five |
| `config.py` | untouched. The only config-tree edit is **`demo_pois.yaml`**, the data file F1 requirement (1) names |
| git | still read-only: the isolated trees are `git archive HEAD | tar -x`, no `worktree add`, no commit, no stash |
| tests | `tests/test_poi_admission.py` **19 passed** (2.27 s); card subset `test_a2_navglue + test_k0_arrival_authority + test_voice_nav_e2e + test_poi_admission -k "crosswalk or poi or ground or admission or scene"` **20 passed** (83.17 s) |

## F1.8 F1 close — the four rows the addenda ask for

| acceptance row | result |
|---|---|
| isolated-worktree minival digest == HEAD's `021b67ab…` | ✅ **equal**, 25/25 rows byte-identical, D-15 keeps `navigation_step_limit_inside_goal` |
| isolated-worktree `scripts/mutation_panel.py` → passed True, survivors `[]`, clean authority `{agreement 4, authority_disagreement 1}`, byte-identical to the committed panel | ✅ all four, and byte-identical to the pure-HEAD panel run on every field but `generated_at` |
| NAV-GEN-1 frozen control 16/16 `known_poi` | ✅ 16/16 (now read from the rows' own `goal_source`, not inferred), 0 of 80 frozen rows changed |
| NAV-GEN-1 generated `crosswalk_a` **0/90** | ✅ **0/90**, with `poi_refused = scene_mismatch:<own scene>/parcel_city_block` on all 90 |
| (card) generated crosswalk false arrivals 0/90 | ✅ **0/90** |
| (card) crosswalk strict ≈ 0.60 | **0.6000** (54/90) on the shared tree; **0.6111** (55/90) in the isolated A/B. Measured, never tuned |
| (card) bench/lamppost/planter/sidewalk byte-identical, 0 collisions | ✅ **0 of 360 rows changed**, 0 collisions (isolated A/B; on the shared tree C2/C3's landed work moves 24 of those rows for reasons that are theirs) |

**Files touched by F1** (same set as C1 plus the YAML the ruling requires):

```
src/parcel_robot/navigation/poi_admission.py   rewritten for identity; geometry demoted to a diagnostic
configs/navigation/cities/demo_pois.yaml       + `scene_id: parcel_city_block` and its header block
src/parcel_robot/navigation/grounder.py        carries `scene_id` from the YAML (docstring + 2 small edits)
src/parcel_robot/perception/city_semantics.py  publication MOVED into the loader, with the scene's identity
src/parcel_robot/navigation/pipeline.py        unchanged except one comment (hook is the same; C1 delta −3)
tests/test_poi_admission.py                    19 tests: identity, the flipped 880027 row, the runner path
scrum/20260829/task_2/C1_STATUS.md             this record
```

---

# Follow-up F2 — the 11 order-dependent tests, fixed

**Integrator's call:** they encode the OLD contract ("a POI directive grounds with no world in the
process"); the new contract is the card's, so fix them.

## F2.1 What changed, and why each test got route (a)

All 11 turned out to be route **(a)** — their subject is POI grounding or a controller that needs a
POI GOAL to drive toward, never the no-world path itself, so none of them wanted its assertion
flipped and nothing was deleted or skipped (rule c). Each file gained **one fixture** that loads the
demo block **the product way** — `extract_city_semantics(MjModel.from_xml_path(DEFAULT_CITY_SCENE))`,
the loader every venue (headless world, NAV_INSTRUCT runner, sim adapter, viewer) goes through and
the place that publishes the scene's identity — and the affected tests request it by name. **No
global is poked**: nothing calls `publish_scene_semantics` directly, and each fixture calls
`clear_scene_instances()` on teardown so it cannot leak the demo scene into another file's tests
(which would mask exactly the refusal this card exists to produce).

| file | fixture | tests requesting it |
|---|---|---|
| `tests/test_c3_cutover.py` | `demo_scene_loaded` (function-scoped; the file's `_restore_process_defaults` autouse fixture is untouched) | `test_B3_oracle_keeps_the_poi_table_and_its_known_poi_grounding` |
| `tests/test_navigation.py` | `demo_scene_loaded` (module-scoped — one MJCF compile for the file) | 9 functions / 10 cases: `…stub_aligns_then_moves_toward_goal`, `…turns_away_from_close_obstacle`, `…exits_avoidance_without_a_bearing_when_obstacle_clears[None]`+`[1.5]`, `…latches_obstacle_identity_and_world_tangent…`, `…uses_full_lidar_to_make_bounded_progress…`, `…preserves_intentional_lateral_motion`, `test_metaurban_env_stub_episode`, `test_dog_navigate_api`, `…turns_in_place_for_goal_behind_robot` |

`test_B1_B2_poi_table_is_empty_off_oracle…` and `test_ground_coffee_42nd` were already green and are
untouched: the first runs off-oracle (the grounder is empty before admission is ever consulted), the
second calls `PlaceGrounder.ground` directly, which is still the table's own answer.

**Diff stat (F2):** `tests/test_c3_cutover.py | 24 +-`, `tests/test_navigation.py | 52 +-` —
**2 files, 66 insertions, 10 deletions**, all of it the two fixtures and the requesting signatures.

## F2.2 Before → after, through the guard (`--label C1`, `TMPDIR` unset, never `-n auto`)

| run | before F2 | **after F2** |
|---|---|---|
| `tests/test_navigation.py` **alone** | 10 failed, 28 passed | **38 passed, 0 failed** |
| `tests/test_c3_cutover.py` **alone** | 1 failed, 53 passed | **54 passed, 0 failed** |
| both alone again with `pytest-randomly` ON (order-independence) | — | **38 passed / 54 passed** |
| the F1 sweep that produced the 11 (`c3_cutover, agent, cpu_budget_proxy, navigation, superlative_directives, a2_navglue, k0_arrival_authority, unknown_place_admission, headless_city_tasks`) | 11 failed, 222 passed | **233 passed, 0 failed** |
| the 212/2 sweep order (`mutation_panel_freshness, c3_cutover, navigation, agent, superlative_directives, cpu_budget_proxy, unknown_place_admission`) | 212 passed, 2 failed | **212 passed, 2 failed — the same two** |
| card subset + C1's own tests (`poi_admission, a2_navglue, k0_arrival_authority, voice_nav_e2e -k "crosswalk or poi or ground or admission or scene"`) | 20 passed | **22 passed** (the two new F1 addendum tests) |

**The only remaining reds are C0's two D-15 rows in this dirty tree** —
`test_committed_panel_safety_fields_still_reproduce` and
`test_mutation_panel_runs_on_the_current_frozen_set_live`, both proved C1-independent by the
neutralisation A/B in §7.1 and by the isolated-worktree panel in §F1.4 (`passed True`, survivors
`[]`, byte-identical to pure HEAD).

`ruff check` clean on both test files; **0 `noqa`**; no test deleted, skipped or xfailed.

---

# Follow-up F3 — the runtime pair, and the grep for every other no-world POI test

**Integrator's finding:** the isolated wave-A close gate failed two runtime cases that pass at HEAD.
Same class as F2 — they encode the old no-world contract.

## F3.1 The two runtime cases

`tests/test_runtime.py::test_social_affect_action_defers_until_navigation_finishes[I am very
happy-…-paw_wave]` and `[…-excited_paw_taps]` call
`runtime.handle_text("navigate to the crosswalk")` through the product runtime on a
`FakeSimulatorBackend`, then set the body to `(3.5, −0.6)` — `crosswalk_a`'s coordinate — to make
the mission arrive. Their subject is POI grounding, so route **(a)**: a function-scoped
`demo_scene_loaded` fixture that loads the demo block **the product way**
(`extract_city_semantics(MjModel.from_xml_path(DEFAULT_CITY_SCENE))`, teardown
`clear_scene_instances()`), requested by that one parametrized test. **The fake backend and the
runtime are untouched** — nothing was made to publish a scene it does not have.

| run (isolated worktree: HEAD + C1-F1 src, `PYTHONPATH` pinned) | before F3 | **after F3** |
|---|---|---|
| `tests/test_runtime.py -k social_affect_action_defers` | **2 failed**, 59 deselected | **2 passed** |
| `tests/test_runtime.py` (whole file, alone) | — | **61 passed, 0 failed** |

## F3.2 The grep — one more file was hiding behind test order

Every `tests/*.py` that names a POI directive ("crosswalk", "coffee shop", "bookstore", "park")
**and** drives a parse-level entry point (`.parse/.start/.handle_text/.navigate/.run`), plus every
file naming `known_poi` / `coffee_42nd` / `crosswalk_a` / `bookstore_main` / `park_entrance`, was
run **alone** through the guard. 17 candidates; 16 green; one red:

**`tests/test_person_aware_nav.py::test_flag_on_cap_lets_the_untouched_gate_approve_the_d15_geometry`**
— its `_drive()` helper starts `DIRECTIVE = "go to the coffee shop at 42nd street"` with no world,
so under the new contract the mission has no goal and the person cap never engages. It did not
appear in the gate's list because in a full-suite order another test had already loaded the demo
block — the same order dependence F2 removed. Attribution is not a judgement call: isolated
worktrees, same test file, **HEAD → 19 passed; HEAD + C1-F1 → 1 failed, 18 passed**.

Fixed by route (a): a `demo_scene_loaded` fixture in that file, requested by the two tests that call
`_drive` (`test_flag_off_person_channel_changes_nothing` too — with no goal its "changes nothing"
assertion would pass **vacuously**, comparing two goal-less searches).

| run | before F3 | **after F3** |
|---|---|---|
| `tests/test_person_aware_nav.py` alone (main tree) | 1 failed, 18 passed | **19 passed, 0 failed** |
| `tests/test_person_aware_nav.py` + `tests/test_runtime.py`, isolated worktree | 3 failed, 77 passed | **80 passed, 0 failed** |

The other 16 candidates pass alone unchanged: `test_agent` 4 · `test_c2_online_map` 68 ·
`test_ot2_memory_principal` 34 · `test_p2_dialogue` 13 · `test_duplex_transaction_v4` 11 ·
`test_dynamic_prompting` 13 · `test_viewer_panel` 5 · `test_p1d_vlm_veto` 46 ·
`test_perception_abstention` 55 · `test_realtime_idle_hangup` 38 · `test_realtime_tool_broker` 52 ·
`test_semantic_navigation_regressions` 9 · `test_superlative_directives` 49 ·
`test_unknown_place_admission` 54 · `test_yield_aside` 30 · `test_arrival_settle` 11 — all passed,
0 failed. (`test_agent`'s coffee-shop line and `test_superlative_directives`'s crosswalk line go
through `PlaceGrounder.ground` or a semantic path, neither of which admission touches.)

**Diff stat (F3):** `tests/test_person_aware_nav.py | 32 +-`, `tests/test_runtime.py | 26 +` —
**2 files, 56 insertions, 2 deletions**, all fixture + requesting signatures. No test deleted,
skipped or xfailed; `ruff` clean; 0 `noqa`.

**F2 + F3 together:** 4 test files, **122 insertions, 12 deletions**, 14 test cases moved from the
old no-world contract to the card's, every one of them by loading the demo scene through the
product loader rather than by touching a global, a backend or a product default.
