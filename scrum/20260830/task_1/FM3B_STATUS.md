# F-M3b — receipt API (E), region-less POI (F), README (G), diagnostic (H)

**Executor:** Opus · **Verifier:** parcel-0e (Fable) · **Integrator:** parcel-fb
**Where:** the gate worktree `/home/jaewoo-jang/.cache/parcel-0e/wb/gate` (detached at `c96ac34`, wave-B stack + F-M2 + W4-F8 uncommitted). Edited in place.

## Pre-flight

```
$ cd /home/jaewoo-jang/.cache/parcel-0e/wb/gate
$ export PYTHONPATH=<wt>/src:<wt> MUJOCO_GL=egl ; unset TMPDIR PARCEL_MEMORY_PATH PARCEL_MEMORY_PURPOSE
$ .parcel/bin/python -c "import parcel_robot, sys; print(parcel_robot.__file__); print(sys.executable)"
/home/jaewoo-jang/.cache/parcel-0e/wb/gate/src/parcel_robot/__init__.py
/home/jaewoo-jang/.cache/parcel-0e/wb/gate/.parcel/bin/python
```

`runtime.py` **not touched at all** (see item F): zero overlap with F-M3a by construction.
Every pytest through `~/.cache/parcel-guard/pytest_guard.sh`, `PARCEL_XDIST_WORKERS=2`, never `-n auto`. No `ci_gate.py`, no eval runner, no simulator, no git write. Zero `noqa` (`grep -c noqa` over every touched file = 0).

---

## ITEM E — `inside_region=True` bypassed `NO_REGION`. **FIXED.**

### E1 · the product guard — `src/parcel_robot/instructnav/arrival_receipt.py:436`

```python
-    elif region is None and inside is None:
+    elif region is None:
         refusal = NO_REGION
```

A caller-supplied `inside_region` may now only **refine** a verdict that already has a committed region. With no `arrival_goal_region` the refusal is `no_committed_arrival_region` whatever the caller passes — including `False`, which used to fall through to `outside_arrival_region` and so named the second missing thing instead of the first. Docstring rewritten at `:398-420` (`**It may only REFINE a verdict that has a committed region** (F-M3b item E)`) and the `NO_REGION` paragraph at `:398` no longer says "and no observed region verdict".

**Blast radius, checked at source** — three non-test callers pass `inside_region`:
* `evals/nav_instruct/runner.py:1198` (the FROZEN v5 cut) — does **not** pass it. Untouched.
* `src/parcel_robot/runtime.py:13127` (`_cut_navigation_receipt`) — does **not** pass it. Untouched.
* `src/parcel_robot/simulation/headless_city.py:1137` — passes the settle window's verdict, and `_observe_settle` returns `None` whenever `_arrival_region(mission)` is `None` (`headless_city.py:932-937`), so region-`None` never arrives with a non-`None` flag. Byte-identical behaviour.
* `evals/companion/run_brain_v1.py:145` — the one real caller of the bypass. Fixed in E2.

### E2 · `tests/test_arrival_receipt.py:120` — the row the card asked for

`test_a_caller_supplied_inside_region_cannot_stand_in_for_a_region`: `inside_region=True, metadata={}, pose=None → no_committed_arrival_region` (and `region_id == ""`, `arrived is False`); the same for `inside_region=False`; plus three control rows proving the refinement the flag exists for is untouched (`PARKED + True → outside_support_polygon`, `STANDABLE + True → arrived_verified`, `STANDABLE + False → outside_arrival_region`). The `_receipt` helper grew an `inside_region` parameter (`:70-91`).

### E3 · `evals/companion/run_brain_v1.py` — the venue made honest

**What was there:** `_SimulatedController.observe` cut every receipt with `metadata=None, pose_xy=None, inside_region=True if navigation_state in _ARRIVED_STATES else None`. The class docstring claimed `_ARRIVED_STATES` was "the product's own set, imported rather than re-typed" (it was a locally typed `frozenset({"arrived"})`) and that the flag "is not a status read dressed up as geometry" (it was exactly that). Under the E1 guard that path now refuses, so the venue had to become real.

**What is there now** (`:74-197`):
* `_VENUE_SIDEWALK` + `_venue_scene()` — the venue's OWN declared scene, in the two shapes `perception/city_semantics` publishes for the same two classes, built by the product's own helpers:
  * `sidewalk` → `scoring.region_inside_goal_region(polygon, entity_id="sidewalk")`, body stops at `(0.0, 3.2)`;
  * `lamppost` → `scoring.object_near_goal_region((1.5, 2.6), 0.15, support_polygon=_VENUE_SIDEWALK, support_clearance_m=0.32)` — the K0 band **∩** the support surface at B32's clearance — body stops at `(2.87, 3.0)` (1.427 m from the anchor, band `[1.27, 1.47]`, 0.48 m inside the support boundary).
* `observe` commits the region for the place the frame **names** (`navigation_goal`), extends the leg with it via `leg.committed(committed_region_id(metadata))` *before* the cut — the runtime's own order — and passes `metadata` + `pose_xy` + `commitment_index`. `inside_region` is gone. A goal the venue's scene does not declare commits nothing and is refused `no_committed_arrival_region`.
* `_ARRIVED_STATES` deleted; the two false docstring claims replaced by a paragraph that names the defect and by an explicit stated limit ("the scene is the VENUE'S, not a world anything perceived — the frozen corpus declares no coordinates, and no byte of it moved").

**Dispositions changed: NONE.** No frozen byte moved (`integration_cases.jsonl` / `manifest.json` / `report.schema.json` untouched; the SHA-256 lock test still passes), and no expected-results file needed updating. Run output:

```
passed: True
   case_count = 15   passed_case_count = 15   failed_case_count = 0
   expected_boundary_outcome_accuracy = 1.0
   expected_fail_closed_case_count = 7   fail_closed_expectation_accuracy = 1.0
   intent_frames_validated = 15   plan_contracts_parsed = 16
   plans_admitted = 12   plans_rejected = 4
   stale_reports_ignored = 1
   verified_facts_emitted = 10   verified_facts_accepted = 9
   physical_navigation_episode_count = 0   physical_navigation_success_rate = None
```

Every one of those equals the value `tests/test_companion_brain_eval.py` pins.

**Teeth (E1).** `elif region is None:` reverted to `elif region is None and inside is None:`:
`1 failed, 10 passed` — `test_a_caller_supplied_inside_region_cannot_stand_in_for_a_region` fails with `+ arrived_verified` (the bypass, verbatim). Restored: `git hash-object` = `530a11bfc8c4cf446799b6a846844c1d46ce5a69` (pre-teeth value).

**Teeth (E3).** `_venue_scene` monkeypatched so the sidewalk pose moves off the polygon and the lamppost pose sits **on** the anchor (outside its band), region objects unchanged:

```
passed: False
RED: sidewalk_inside_boundary            -> failed [... 'task_failed'] []
RED: lamppost_near_boundary              -> failed [... 'task_failed'] []
RED: correction_at_checkpoint_boundary   -> failed
restored passed: True 15
```

i.e. the suite's arrival dispositions are now decided by the product's region math over a pose, not by a status string. Under the OLD code every one of those would still have passed.

---

## ITEM F — region-less POI narrated as a failure. **MEASURED; no product change (reason below).**

### F1 · the probe (scratch, not under `tests/`), through the product path

Published the demo block through the real `perception.city_semantics.extract_city_semantics`, grounded through a real `DirectiveNavigator.from_config()`, then drove a real `RobotRuntime` (the `tests/test_arrival_leg_runtime.py` fixture pattern) to an honest terminal on exactly that metadata.

```
scene_id: parcel_city_block
region labels: ['crosswalk', 'sidewalk']
object labels: ['bench', 'building', 'door', 'lamppost', 'planter', 'tree']

=== directive: go to the bookstore
    goal: GoalPose(x=12.0, y=-3.0, poi_id='bookstore_main', label='bookstore', arrival_radius_m=None)
    metadata keys: ['goal_source', 'identity_source']
    arrival_goal_region: None
region_instance_for_poi(bookstore_main): None

=== runtime at the honest arrival
  leg:     LegIdentity(goal_id='go to the bookstore', sequence=1, committed_region_ids=())
  receipt: ArrivalReceipt(goal_id='go to the bookstore', sequence=1, region_id='', claimed=True,
           inside_region=None, support_clearance_ok=True, settled=True,
           verified_by='runtime.navigation_terminal', reason='no_committed_arrival_region')
  mission_log: {... 'state': 'arrived', 'reason': 'arrived_verified', 'level': 'warning',
                'text': 'Mission to bookstore ended (arrived): arrived_verified.'}
  event:       {'role': 'navigation', 'level': 'error',
                'text': 'Navigation failed for bookstore: no_committed_arrival_region'}
```

**The finding reproduces exactly.**

### F2 · the second measurement — which POIs have geometry at all

The card's fix is "the same way the EVAL already scores them — `object_near_goal_region` (band ∩ support around the object)", with the explicit carve-out **"Keep `NO_REGION` for goals with no geometry at all."** So the first question is which of the shipped POIs actually have an object to build a band around. Measured against the demo block's own instance set:

| POI | class tokens | instances of that class in `parcel_city_block` | `region_instance_for_poi` | `geometry_diagnostic` |
|---|---|---|---|---|
| `crosswalk_a` | crosswalk, crosswalk near coffee | `['crosswalk']` | `crosswalk` (polygon) | `(True, 'crosswalk', 0.20)` |
| `coffee_42nd` | cafe, coffee shop, … | `[]` | `None` | `(None, '', None)` |
| `bookstore_main` | shop, bookstore, main street bookstore | `[]` | `None` | `(None, '', None)` |
| `park_entrance` | park, park entrance, city park | `[]` | `None` | `(None, '', None)` |

The scene's object classes are `bench / building / door / lamppost / planter / tree`; matching is exact on a normalised class name (`poi_class_tokens`), so `shop` does not reach `building`'s `storefront` alias and `park entrance` does not reach `door`'s `entrance` alias.

**So `bookstore_main` is not "an object-class POI whose region is missing". It is a surveyed coordinate with NO geometry anywhere in the scene it declares** — no polygon, no object, nothing to intersect a band with. Behind the claim there is only the table's coordinate and the navigator's `arrive_radius_m`, which is the C0/D-15 shape verbatim ("the demo POI table answered with a coordinate, no region was ever committed, and 'the point radius was satisfied' used to be enough"). Under the card's own carve-out `no_committed_arrival_region` is the honest verdict, and manufacturing a region around the coordinate would re-open exactly the defect W4 exists to close. **Nothing changed for that case, by the card's own rule.**

### F3 · the residual gap that IS real, and why it is not fixed here

There is a real hole one step over: a POI whose class **is** an object the scene declares. `region_instance_for_poi` filters to `len(item.polygon) >= 3` and its docstring says so on purpose ("Objects are deliberately excluded"), so such a POI also gets the bare dict. Measured with a `bench`-class row against the demo block:

```
matching instances:      [('bench_1', (-2.5, 3.045), (1.8537574531137657, 2.0537574531137657))]
region_instance_for_poi: None
```

Fixing that honestly needs **more than a metadata line**: `SceneInstance` keeps only `center` + `band_m` (`poi_admission.py:289-329` drops `support_polygon` / `terminal_support_clearance_m` when it builds instances from the extractor's specs), so `object_near_goal_region(..., support_polygon=…, support_clearance_m=…)` — the **∩ support** half, which is the whole of B32 — cannot be reconstructed from a `SceneInstance`. The fix is: carry the support surface onto `SceneInstance`, let `region_instance_for_poi` (or a sibling) answer for objects, and have `poi_goal_metadata` commit the band ∩ support with `TERMINAL_RELATION_KEY = "near"`.

Every one of those lines is in `navigation/poi_admission.py` **outside this card's OWNS** ("ONLY the `admit_poi` diagnostic"), in the module F-M2 landed 40 minutes earlier; and the alternative site the card offers — "the cut" — would mean `_cut_navigation_receipt` building an arrival region out of the process-scoped `active_scene_instances()`. That is precisely the fourth opinion B32 removed (`arrival_receipt`'s own docstring: "the region the navigator COMMITTED, **not one rebuilt here from a scene**"; `_cut_navigation_receipt`: "Every input is this loop's own"), and it would re-open the two-worlds hole F-M2 closed. Per the board's integrator rule 1 ("If your change cannot be expressed as such a hunk, stop and write it up") I stopped and wrote it up. **Recommended as a follow-up card: `SceneInstance` carries its support surface; object-class POIs commit `object_near_goal_region` band ∩ support in `poi_goal_metadata`.**

### F4 · what I DID land — the product-path rows (`tests/test_arrival_leg_runtime.py:478-679`)

Three rows, all driven through `RobotRuntime._step_navigation` with the metadata a real `DirectiveNavigator` produced on the real published demo block (fixture `demo_block_metadata`, `:519`), and the pose taken from the runtime's own observation:

1. `test_a_region_class_poi_arrival_is_verified_by_geometry_on_the_product_path` — `crosswalk_a`, body at `(3.1, 0.8)` (inside the scene's committed polygon `[[2.35,-0.4],[3.85,-0.4],[3.85,2.0],[2.35,2.0]]`) → receipt `arrived_verified`, `region_id == "crosswalk"`, `leg.committed_region_ids == ("crosswalk",)`, `inside_region is True`, mission log `success` / `"Arrived at crosswalk."`, panel event `"Arrived at crosswalk"`. **This is the card's asked-for positive: an honest POI arrival with a region id and "Arrived at …" emitted.**
2. `test_a_stop_short_of_the_committed_region_is_refused_and_narrated_unverified` — same POI, same navigator claim (`status="arrived"`, `note="arrived_verified"`), body 1.5 m short at `(3.1, -1.9)` → `claimed is True`, `inside_region is False`, `reason == outside_arrival_region`, mission log `warning`, panel event `"Navigation failed for crosswalk: outside_arrival_region"`.
3. `test_a_poi_with_no_geometry_anywhere_in_its_scene_stays_no_region` — `bookstore_main` → `arrival_goal_region` absent from the product's metadata, `region_id == ""`, `committed_region_ids == ()`, `reason == no_committed_arrival_region`, panel event `"Navigation failed for bookstore: no_committed_arrival_region"`. The row's docstring records that the WORDING is a narration question and not the arrival authority's.

The section header carries the F2 table so the next reader does not have to re-derive the measurement, and rows 1+2 pin the table's own coordinate `(3.5, -0.6)` as 0.2 m OUTSIDE the crosswalk polygon (the D-15 geometry, unchanged).

**Teeth (F4).** `poi_goal_metadata`'s `metadata["arrival_goal_region"] = region_inside_goal_region(...)` temporarily removed: `2 failed, 5 passed` — both crosswalk rows fail on `assert '' == 'crosswalk'`, i.e. they read the PRODUCT's metadata assembly and not a hand-written dict. Restored: `git hash-object src/parcel_robot/navigation/poi_admission.py` = `83b64e98b3fab6995220787059b79593ee476a39` (pre-teeth value). Rows 1 vs 2 differ **only** in the observed pose, which is the other half of the teeth: the geometry decides, the status string does not.

---

## ITEM G — README v5 artifact names. **FIXED.**

`evals/nav_instruct/README.md:213-214`. The two names were preview timestamps that no file carries:

```
- results/nav-instruct-v1-baseline-v5-20260830T122614Z.json
+ results/nav-instruct-v1-baseline-v5-20260830T135548Z.json
- results/nav-instruct-v1-matrix-v5-20260830T122035Z.json
+ results/nav-instruct-v1-matrix-v5-20260830T135527Z.json
```

The replacements are the committed files (`ls evals/nav_instruct/results/`) and are the same two paths `tests/test_nav_instruct_digest_recipe.py:282-283` and `scripts/ci_gate.py:397,483` already point at. Nothing else in the README touched (two lines, `-2/+2`).

---

## ITEM H — `admit_poi`'s geometry diagnostic read the raw publication. **FIXED.**

`src/parcel_robot/navigation/poi_admission.py:425` (the one-liner F-M2's follow-up asked for):

```python
-    backed, nearest_id, distance = geometry_diagnostic(poi, scene)
+    backed, nearest_id, distance = geometry_diagnostic(
+        poi, scene_for_identity(scene, world_identity)[0]
+    )
```

plus two sentences in `admit_poi`'s docstring saying why ("a diagnostic that names another map's crosswalk is not a weaker fact about this one; it is a fact about somewhere else, printed into this admission's detail line"). `scene_for_identity` is defined below `admit_poi` and resolved at call time — no reordering. Single-world behaviour is unchanged in both directions: with no explicit identity the source is `IDENTITY_PUBLISHED` and `scene_for_identity` hands the publication straight back, which is why `test_crosswalk_poi_admission_per_scene`'s three rows (incl. the 880027 `geometry_backed is True` demotion evidence) still read exactly as before.

**Assertion added to F-M2's two-worlds row** (`tests/test_poi_admission.py:842-851`, inside `test_a_foreign_worlds_polygon_is_never_the_committed_arrival_authority`), with the contrast rather than a bare equality so the row cannot pass vacuously:

```python
assert geometry_diagnostic(CROSSWALK_POI, published)[1] == foreign.instance_id  # un-scoped
assert diagnosed.nearest_instance_id == ""                                      # scoped
assert diagnosed.geometry_backed is None
assert diagnosed.nearest_distance_m is None
```

(`diagnosed = admit_poi(CROSSWALK_POI, scene=published_880000, declared_scene_id=DEMO_SCENE_ID, world_identity=<demo block>)` — the same composition the navigator runs; outcome stays `admitted`, W3's rule untouched.)

**Teeth.** The one-liner reverted: `1 failed, 28 passed` — the row fails on `assert 'crosswalk' == ''`, i.e. the diagnostic naming 880000's own instance. Restored: `git hash-object` = `83b64e98b3fab6995220787059b79593ee476a39`.

---

## Proof

Ruff, every touched file, zero `noqa`:

```
$ .parcel/bin/ruff check src/parcel_robot/instructnav/arrival_receipt.py \
    src/parcel_robot/navigation/poi_admission.py evals/companion/run_brain_v1.py \
    tests/test_arrival_receipt.py tests/test_arrival_leg_runtime.py tests/test_poi_admission.py
All checks passed!
```

The FINISH list, one guarded invocation (`--label fm3b-finish`, `PARCEL_XDIST_WORKERS=2`, `TMPDIR` unset):

```
$ ~/.cache/parcel-guard/pytest_guard.sh --label fm3b-finish <wt>/.parcel/bin/python -m pytest \
    tests/test_arrival_receipt.py tests/test_arrival_receipt_wiring.py tests/test_arrival_leg_runtime.py \
    tests/test_nav_instruct_receipt_authority.py tests/test_nav_instruct_digest_recipe.py \
    tests/test_companion_brain_eval.py tests/test_poi_admission.py tests/test_k0_arrival_authority.py \
    tests/test_brain_runtime_adapter.py -q -p no:cacheprovider
110 passed, 2 warnings in 36.06s
```

Per-suite, as run during the work:

| suite | result |
|---|---|
| `test_arrival_receipt.py` + `test_arrival_receipt_wiring.py` (after E1/E2) | `25 passed in 0.65s` |
| `test_companion_brain_eval.py` (after E3) | `11 passed in 0.22s` |
| `test_poi_admission.py` (after H) | `29 passed in 2.92s` |
| `test_arrival_leg_runtime.py` (after F4) | `7 passed in 1.87s` |
| **frozen v5 evidence** — `test_nav_instruct_receipt_authority.py` + `test_nav_instruct_digest_recipe.py` | **`19 passed, 2 warnings in 31.25s`** |
| fast FINISH set (7 suites) | `91 passed in 4.80s` |

**Frozen v5 artifacts and the eval runner's receipt cut: untouched.** `evals/nav_instruct/runner.py` not edited (`RECEIPT_ARRIVAL_FAMILIES` and the cut at `:1194-1219` byte-identical); `evals/nav_instruct/results/*v5*`, `mutation_panel.json`, `ledger.jsonl` not edited; the only README change is the two file names in the v5 table. Digest-recipe + receipt-authority green after every product change.

## `git status --porcelain` / `git diff --stat` — my files

```
 M evals/companion/run_brain_v1.py              | 182 +++++++++++-
 M evals/nav_instruct/README.md                 |  98 ++++++-
 M src/parcel_robot/navigation/poi_admission.py | 378 ++++++++++++++++++++++---
 M tests/test_poi_admission.py                  | 400 ++++++++++++++++++++++++++-
?? src/parcel_robot/instructnav/arrival_receipt.py   (462 lines; new in wave B — untracked, so no diff row)
?? tests/test_arrival_receipt.py                     (374 lines; new in wave B)
?? tests/test_arrival_leg_runtime.py                 (679 lines; new in wave B)
```

The four `M` stats are the whole wave-B stack for those paths, not F-M3b alone; F-M3b's own hunks are the ones cited by line number above. `src/parcel_robot/runtime.py` carries **no** F-M3b hunk. `src/parcel_robot/instructnav/scoring.py` read only — the object-region helper needed no new product-facing entry point (`object_near_goal_region` and `region_inside_goal_region` are already public and are what the venue and the tests call).

## Not done, and why

* **Item F's product fix.** Measured and reproduced (F1); the finding's own example is a coordinate-only POI for which `NO_REGION` is the card's own stated keep (F2); the real residual gap (object-class POI **with** scene geometry) needs `SceneInstance` to carry its support surface plus `region_instance_for_poi` / `poi_goal_metadata` changes — all outside this card's OWNS, and the only in-OWNS alternative (build the region in `_cut_navigation_receipt` from `active_scene_instances()`) would restore the fourth arrival authority B32 deleted and the two-worlds hole F-M2 closed. Written up as a follow-up card in F3. The behaviour is now **pinned** by three product-path rows so the gap cannot close or widen silently.
* No safety-floor change; no `ci_gate.py`; no eval runner, mutation panel or simulator invoked directly; nothing written into
  the owner's live stack, `parcel_memory.sqlite3` or `~/.config/parcel/realtime.env`. (`tests/test_voice_nav_e2e.py` spins up
  its own `parcel_robot.sim` in a pytest tmp socket — that is the test's own rig, run through the guard, and it is torn down
  with the test.)
* **Item I** was dispatched by the coordinator mid-card and extends this card's `runtime.py` OWNS to the terminal emit in
  `_step_navigation`; it is recorded below the original four items.

---

## ITEM I — the terminal line printed a refusal token where the navigator's reason was the story. **FIXED.**

**Dispatched by the coordinator after F-M3a's wider sweep** found `tests/test_voice_nav_e2e.py::test_paraphrase_find_the_fountain_still_reports_honestly` red (slow/nightly, not in the commit tier; `FM3A_STATUS.md` §"Not done / for the verifier" referred it here):

```
E  AssertionError: no honest not-found report:
   events=['Navigation failed for fountain: no_system_arrival_claim']
```

### I1 · the fix — `src/parcel_robot/runtime.py:13712-13729` (inside `_step_navigation`'s terminal branch only)

```python
+            # F-M3b item I: WHICH of the two facts this line is about. The
+            # refusal tokens exist for a claim the receipt REFUSED — stale, off
+            # the support surface, another place. `no_system_arrival_claim` is
+            # not that: it says the navigator never claimed to have finished, so
+            # the navigator's own reason (`not_found`, `unreachable`) IS the
+            # story and the token merely restates that there is nothing to
+            # refuse. Printing the token there masked `not_found` behind a
+            # sentence that says only "no claim was made", which is the one
+            # thing the owner can already tell.
+            detail = reason if refusal == NO_CLAIM else (refusal or reason)
             if not refusal:
                 self._emit("navigation", f"Arrived at {place}", "success")
             else:
                 self._emit(
                     "navigation",
-                    f"Navigation failed for {place}: {refusal or reason}",
+                    f"Navigation failed for {place}: {detail}",
                     "error",
                 )
```

plus `NO_CLAIM` added to the existing `from parcel_robot.instructnav.arrival_receipt import (...)` block at `:186-194` (the way `receipt_refusal` / `committed_region_id` are already imported there).

**Scope, checked:**
* `receipt_refusal` **not touched**; no consumer logic touched. `detail` is a fresh local — the only `detail =` binding anywhere in `_step_navigation` (`:13477-13735`); `self._navigation_detail` is a different name and is unchanged.
* The success arm (`if not refusal:`) is unchanged, so `"Arrived at <place>"` is byte-identical.
* `_log_mission_terminal` and `_narrate_mission_terminal` still receive `reason=reason` — the mission log's level/text and the whisperer's fact are untouched, so this moves one panel event string and nothing else.
* Nothing in the product parses that string (`grep -rn "Navigation failed for" --include=*.py src/` → the emit itself, one comment at `:13568`, the yield-give-up emit at `:13813`, and `voice/agent.py:1604`'s own separate line).
* **Region check for the concurrent executor:** F-M3a's runtime.py regions are `_build_brain_snapshot`, `_accept_plan`, `_step_brain`, the `KIND_MISSION_ENDED` fact/klass builder and `_whisper_plan_accepted`. `_step_navigation` (`:13477-13735`) is none of them; the shared import block hunk is a different statement from F-M3a's `OBSTACLE_BLOCK_NOTE` import. No overlap.

### I2 · the rows (`tests/test_arrival_leg_runtime.py:683-781`), both sides

* `test_an_unclaimed_terminal_names_the_navigators_reason_not_the_refusal` — leg to `find the fountain`, navigator terminal `status="failed"`, `note="semantic_target_not_found"`, no committed region. Asserts the refusal really **is** `NO_CLAIM` (so the emit is choosing, not falling through), then `event["text"] == "Navigation failed for fountain: semantic_target_not_found"` and `NO_CLAIM not in event["text"]`, and that the mission log row is still `warning` — not-arrived is still not-arrived.
* `test_a_refused_claim_still_names_its_refusal_token` — same terminal shape, but the navigator DID claim (`status="arrived"`, `note="arrived_verified"`) and committed `sidewalk` with the body at `(9.0, 9.0)`, outside it. Asserts `event["text"] == "Navigation failed for sidewalk: outside_arrival_region"` and that the now-misleading `arrived_verified` is **not** what printed.

A shared `_terminate` helper drives both through `start_navigation` + `_step_navigation` on the product path (no seeded receipt, no seeded leg).

### I3 · proof

`tests/test_voice_nav_e2e.py` carries `pytestmark = pytest.mark.slow` and `[tool.pytest.ini_options]` sets only `testpaths`, so slow rows are **not** deselected by default — no `-m ''` override was needed.

```
$ ~/.cache/parcel-guard/pytest_guard.sh --label fm3b-e2e-fountain <wt>/.parcel/bin/python -m pytest \
    "tests/test_voice_nav_e2e.py" -k "fountain or not_found" -q -p no:cacheprovider
2 passed, 16 deselected, 4 warnings in 44.83s
```

(the two selected are `test_go_to_the_fountain_is_asked_about_rather_than_searched_for` and the case F-M3a referred out, `test_paraphrase_find_the_fountain_still_reports_honestly` — **green**.)

```
$ … --label fm3b-itemI      … -m pytest tests/test_arrival_leg_runtime.py -q     → 9 passed, 2 warnings in 2.18s
$ … --label fm3b-runtime-nav … -m pytest tests/test_runtime.py -k navigation -q  → 5 passed, 56 deselected, 2 warnings in 1.83s
$ .parcel/bin/ruff check src/parcel_robot/runtime.py tests/test_arrival_leg_runtime.py … → All checks passed!
```

### I4 · teeth — the one line reverted to `detail = refusal or reason`

```
teeth A — tests/test_arrival_leg_runtime.py
E  AssertionError: assert 'Navigation f...arrival_claim' == 'Navigation f...get_not_found'
E    - Navigation failed for fountain: semantic_target_not_found
E    + Navigation failed for fountain: no_system_arrival_claim
FAILED tests/test_arrival_leg_runtime.py::test_an_unclaimed_terminal_names_the_navigators_reason_not_the_refusal
1 failed, 8 passed, 2 warnings in 2.15s

teeth B — the e2e case itself
FAILED tests/test_voice_nav_e2e.py::test_paraphrase_find_the_fountain_still_reports_honestly
1 failed, 3 warnings in 40.85s   (tests/test_voice_nav_e2e.py:1297 — the "no honest not-found report" assertion)
```

Note the second row of the pair (`test_a_refused_claim_still_names_its_refusal_token`) stays GREEN under the revert, which is the point: it is the side the old expression already got right, and it guards against "fixing" this by printing `reason` unconditionally.

**Restored byte-identically:** `git hash-object src/parcel_robot/runtime.py` = `e59e79b95e6bbcd6b8bf53c6aa795cbb2a20918f`, the pre-teeth value.

### I5 · re-run after the restore, on the restored bytes

```
$ … --label fm3b-finish2       … -m pytest <the nine FINISH suites> -q          → 112 passed, 2 warnings in 35.52s
$ … --label fm3b-runtime-nav2  … -m pytest tests/test_runtime.py -k navigation  → 5 passed, 56 deselected, 2 warnings in 1.82s
$ … --label fm3b-e2e-fountain2 … -m pytest tests/test_voice_nav_e2e.py \
                                    -k "fountain or not_found" -q              → 2 passed, 16 deselected, 4 warnings in 44.89s
```

The FINISH count moves 110 → **112**: the two item-I rows, and nothing else. `git hash-object src/parcel_robot/runtime.py` at the end of this card = **`e59e79b95e6bbcd6b8bf53c6aa795cbb2a20918f`** (F-M3a shares this file; a later hunk of theirs will move it, and that sha is F-M3b's last write).

---

## ITEM J — gate #4 red: `test_arrival_settle` leaned on the bypass item E closed. **FIXED (the fixture).**

Reported by the coordinator from close gate #4 on the S4 bytes:

```
tests/test_arrival_settle.py::test_arrived_verified_needs_the_claim_the_region_and_the_settle[arrived-arrived_verified-True-True-True]
HeadlessTaskResult(directive='go to the lamppost', status='arrived', reason='arrived_verified',
                   target_id='lamp_post_1', …, committed_region_ids=()).arrived_verified == False
```

### J1 · root cause — the FIXTURE, not the venue

`_result_for` (`tests/test_arrival_settle.py:154-184`) hand-built every result with

```python
        inside_arrival_region=inside,
        mission_metadata={},          # ← no committed region, ever
```

so the six parametrised rows asserted a "committed K0 region" that was never committed: the only thing standing in for it was the `inside_arrival_region` flag. That is **exactly the bypass item E removed** — `arrival_receipt`'s `region is None and inside is None` guard let a caller-supplied `True` skip `NO_REGION`. With E's `elif region is None:` the receipt honestly reports `no_committed_arrival_region`, `committed_region_id({})` is `""`, and `_result`'s `LegIdentity(directive, seq, committed_region_id(metadata) or None)` therefore carries the empty chain the failure line prints. The fixture is the defect; **`headless_city` is innocent and unchanged**.

Two things confirm the venue is fine and E's guard is right:
* `_observe_settle` (`headless_city.py:932-937`) returns `inside_at_terminal = None` whenever `_arrival_region(mission)` is `None`, so on the REAL settle path a missing region never arrives with a non-`None` flag — the interaction the coordinator asked me to check does not exist there.
* This same file's two `@pytest.mark.slow` end-to-end rows (`test_a_verified_arrival_holds_still_inside_the_committed_region`, `test_a_poi_arrival_with_no_committed_region_is_not_verified`) run real missions with real navigator metadata and were green throughout — they always committed a region.

The W4-F8 `w4f8-receipts` run was green because it predates item E; the bypass was still open then, which is precisely what made the fixture's claim invisible.

### J2 · the fix — the fixture commits the region it claims

`tests/test_arrival_settle.py`, the only file that moved:

* new module constants + helper (`:61-99`): `LAMP_POST_1_ID = "lamp_post_1"`, `LAMP_POST_1_XY = (0.2, 3.15)`, `LAMP_POST_1_FOOTPRINT_M = 0.06`, and `_committed_lamppost_region()` building the region with the product's own `scoring.object_near_goal_region(...)`. The numbers are the **city block's own published geometry**, not invented: `active_scene_instances()` on a `HeadlessCityWorld` declares `lamp_post_1` at `(0.2, 3.15)` with band `(1.18, 1.38)`, and a 0.06 m footprint is the radius `object_near_envelope_m(r, label="lamppost")` reproduces that band from exactly.
* `_result_for` now passes `mission_metadata=_committed_lamppost_region()` and `target_id=LAMP_POST_1_ID`.
* The `("arrived", "arrived_verified", None, False, False)` row's comment was reworded to say what it now measures (the region IS committed in all three negative rows; what they vary is the window's OBSERVATION of it and the settle). **No parametrised tuple changed** — all six `(status, reason, inside, settled, expected)` values are byte-identical.

Deliberately **no support polygon** on the committed region (the pre-B32 "nothing to fail" answer `arrival_receipt` documents), with the reason written into the helper's docstring: `world` is module-scoped and the slow rows move the body, so a support constraint would make these rows depend on where the robot happens to be parked — which is not what a unit over *claim x region x settle* means to measure. The support half keeps its own witnesses (`tests/test_arrival_receipt.py`'s B32 bench rows) and its end-to-end one (the two slow rows in this file).

**E's guard was not weakened.** `arrival_receipt.py` is untouched by item J — `git hash-object` still `530a11bfc8c4cf446799b6a846844c1d46ce5a69`, the value it has had since item E. A caller-supplied `inside_region` still cannot stand in for a region.

### J3 · teeth

Run as a scratch probe rather than a file revert **on purpose**: three sessions share this worktree and `parcel-fb-s4-panel` / `parcel-0e-mergeproof-s4` were holding the guard lock, so reverting a tracked test file would have corrupted somebody else's gate result. The probe calls the same product function the row calls (`HeadlessCityQualityHarness._result`) with identical arguments, varying only `mission_metadata` — `{}` is literally the reverted fixture:

```
OLD fixture (mission_metadata={}) — the reverted state:
    arrived_verified = False
    receipt.reason   = no_committed_arrival_region
    receipt.region_id= ''
    arrival_leg      = LegIdentity(goal_id='go to the lamppost', sequence=0, committed_region_ids=())
NEW fixture (commits the region it claims):
    arrived_verified = True
    receipt.reason   = arrived_verified
    receipt.region_id= 'lamp_post_1'
    arrival_leg      = LegIdentity(goal_id='go to the lamppost', sequence=0, committed_region_ids=('lamp_post_1',))
```

The first block reproduces the gate's failure signature exactly, `committed_region_ids=()` included.

### J4 · proof

```
$ ~/.cache/parcel-guard/pytest_guard.sh --label fm3b-settle <wt>/.parcel/bin/python -m pytest \
    tests/test_arrival_settle.py tests/test_arrival_receipt.py tests/test_arrival_leg_runtime.py \
    tests/test_k0_arrival_authority.py tests/test_headless_city_tasks.py \
    tests/test_nav_instruct_digest_recipe.py -q -p no:cacheprovider
65 passed, 2 warnings in 25.19s
```

All six suites green, the slow settle rows included (nothing was deselected — this file's `@pytest.mark.slow` rows ran). `tests/test_nav_instruct_digest_recipe.py` in the same invocation is the frozen-digest evidence: **untouched**.

```
$ .parcel/bin/ruff check tests/test_arrival_settle.py … → All checks passed!   (0 noqa)
```

### J5 · what moved

| file | `git hash-object` | `sha256` |
|---|---|---|
| `tests/test_arrival_settle.py` (**the only file item J moved**) | `637f0397fbb537e29abd40c6e4c067061829e025` | `731967253fa4403138407ca8ffe7a471162bf61b690f55ade27c1e4799783864` |

Unmoved by item J, for the record: `src/parcel_robot/instructnav/arrival_receipt.py` = `530a11bfc8c4cf446799b6a846844c1d46ce5a69` (item E's value — the guard was **not** weakened) and `src/parcel_robot/simulation/headless_city.py` = `17e6d5c23596c47dfe7158faa7d8973b6c124391` (the venue's W4 hunks are wave-B's, not F-M3b's; this card never edited that file).

`src/parcel_robot/runtime.py` reads `c73477d1cbc677f0ccf053dd6ea87428c7bcdc1b` at this point — **F-M3a's concurrent narration split moved it after item I's write** (`e59e79b95e6bbcd6b8bf53c6aa795cbb2a20918f`). Item I's hunk survives intact and was re-verified at source: `detail = reason if refusal == NO_CLAIM else (refusal or reason)` at `:13780`, the emit at `:13786`, the `NO_CLAIM` import at `:187`.
