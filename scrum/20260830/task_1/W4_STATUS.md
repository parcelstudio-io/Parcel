# W4 STATUS — ARRIVAL-AUTHORITY-1 (B32) · Opus executor

**Card:** `scrum/20260830/task_1/W4_ARRIVAL_AUTHORITY.md` · **Amendments A1, A2, A3 read and applied** (recorded below).
**Worktree:** `/home/jaewoo-jang/.cache/parcel-0e/wb/w4` (detached), HEAD **`c96ac345358ec2786748fc3a885c35d32710c5e2`**.
**Pre-flight:** `python -c "import parcel_robot; print(parcel_robot.__file__)"` →
`/home/jaewoo-jang/.cache/parcel-0e/wb/w4/src/parcel_robot/__init__.py` ✓ (the worktree, not the dirty root).
Every shell: `PYTHONPATH=$PWD/src:$PWD MUJOCO_GL=egl OPENBLAS_NUM_THREADS=32`, `TMPDIR` unset.
Scratch `/home/jaewoo-jang/.cache/parcel-0e/wb/w4-scratch/`, socket root `~/.cache/parcel-0e/wb/w4-sock/`,
`PARCEL_MEMORY_PATH` → scratch. Sims killed (`[N3 orphan check] clean=True ours=[] other_processes=[]`).
Never touched `:8080` / `:8765` / `/tmp/parcel_sim.sock`. **Spend $0** (no hosted call anywhere).

---

## Amendments, recorded

**A1 (v5, not a v4 rewrite).** Applied in full: `EPISODE_SET_V5` added to `generator.EPISODE_SETS` with an
`EpisodeSetSpec` whose provenance names B32 and the intersect rule; `ARRIVAL_RULE_FOR_VERSION["v5"]` added;
`evals/nav_instruct/bridge_v4_v5.py` written in `bridge_v3_v4.py`'s idiom. v4 stays byte-identical and superseded;
its `episode_digest` `4113607b…` is UNMOVED and the bridge asserts it against a live regeneration. The freshness
test `_CURRENT_FROZEN_EPISODE_SET` advances to v5 ⇒ the committed v4 panel reddens **by design in this worktree**;
panel files untouched, **W5 layers the v5 panel + the v5 ledger row on this patch**.

**A2 (explicit budget policy, `--no-ledger` always).** Recipe of record used for **every** run below:
`--budget-policy scaled-path-v1 --max-steps 200 --seed 20260804 --no-ledger`. One recorded baseline row had been
appended before A2 arrived; it was **reverted** (`git checkout -- evals/nav_instruct/results/ledger.jsonl`, report
moved to scratch) and the ledger is byte-identical to HEAD (last row `nav-instruct-v1-candidate-v4-20260821T102746Z`).
`tests/test_nav_instruct_digest_recipe.py` therefore publishes **no v5 report digests** — that is W5's, with its row.
What W4 pins instead is the episode SET: `scripts/ci_gate.py` `DIGEST_SENTINELS["evals/nav_instruct/episodes/v5/manifest.json"] = 05c6a99a…`.

**A3 (`nav-region_goal-B-09-3ee156e4` by principle).** Measured, characterised, recorded as a bridge row and a test.
**It is NOT closed, and the second author is named** — see §6. No per-episode exception anywhere in code.

---

## 1 · What was built

**(1) The intersection, in ONE function.** `instructnav/scoring.py`:
`object_near_goal_region(..., support_polygon=, support_clearance_m=)` now returns the `near` band **∩** the
object's support surface. `GoalRegion` carries `support_polygon` / `support_clearance_m`; membership,
`distance_to`, `signed_distance_to_boundary` and `p_inside_goal_region` all go through one `on_support()`.
`as_dict()` emits the two new keys **only when a support polygon is present**, which is what keeps v1–v4
regenerating byte-identically. Two shared helpers land beside it: `support_surface_for()` (THE support rule,
now called by `perception.city_semantics` **and** by the episode generator, replacing two separate copies —
`city_semantics._inside` was deleted as the second copy) and `TERMINAL_SUPPORT_CLEARANCE_M`, derived from
`authority.DEFAULT_SAFETY_ENVELOPE.footprint_radius_m` instead of the `0.32` that had been typed separately in
`city_semantics` and `pipeline`. `SCORING_VERSION` → `instructnav-scoring-v1.5-support-intersected-k0`.
Three callers, one authority: extractor, generator, `arrival_goal_region_for_relation`.
`pipeline._on_support_surface` is now **one delegation to the region** (`region.on_support(x, y)`) instead of a
second reading of the metadata.

**(2) The region-class POI (D-15 / B32 pair 1).** `poi_admission.poi_goal_metadata()` commits the loaded scene's
own polygon as the mission's `arrival_goal_region` with `terminal_relation: "inside"` when a POI's class is a
region in that scene; `poi_region_arrival_admits()` makes that region the sole judge for a POI mission (the 1.5 m
point radius may still request a stop, it may no longer declare arrival); `poi_terminal_relation()` is the one
reader of the relation. Object-class POIs are untouched.

**(3) ONE typed `ArrivalReceipt`** — new leaf `src/parcel_robot/instructnav/arrival_receipt.py`. Fields:
`goal_id`, `sequence`, `region_id`, `claimed`, `inside_region`, `support_clearance_ok`, `settled`, `verified_by`,
`reason`. Refusal tokens in test order: `no_system_arrival_claim` → `no_committed_arrival_region` →
`no_terminal_pose` → `outside_support_polygon` → `outside_arrival_region` → `not_settled` → `arrived_verified`.
Produced only by the K0 seam from the loop's own observations (`headless_city._result` over its settle window;
`runtime._cut_navigation_receipt` from the pose that loop measured); never from a scorer verdict, a harness field
or a planner claim. `receipt_says_arrived(receipt, goal_id=, sequence=, region_id=)` is THE consumer predicate:
missing, stale (wrong leg) or wrong-place receipt = **not arrived**. Consumers migrated:
`headless_city.arrived_verified` (now literally `receipt.arrived`), the **executive's** NavigateTo verifier
(`brain/runtime_adapter._result_for`, detail `no_arrival_receipt`), `runtime._log_mission_terminal`,
`runtime._narrate_mission_terminal` (the whisperer C4 + speech acts C5), and `evals/companion/run_embodied_plan_v1.py`.

**(4) The re-freeze as v5.** `episodes/v5/` (25 files + manifest), `bridge_v4_v5.py`, README version table,
`ci_gate.py` sentinel + a full provenance comment naming the cause.

**Nothing BLOCKED.** The one-receipt composition needed **no symbol from the dirty root's `executive.py`**: the
executive's terminal fact for a navigation step is decided in `brain/runtime_adapter._result_for`, which is not in
the owner's diff. `brain/executive.py` is untouched by this card.

---

## 2 · Acceptance rows (bar quoted, then the measurement)

| # | bar (verbatim) | result |
|---|---|---|
| 1 | NAV-INT-1 tier: authority disagreements **≤ 2/80** | **RED — NOT RUN AT FULL SCALE** (§5) |
| 2 | bench `system_failed_but_arrived` **0/29** | **GREEN on the legs run (2/2), RED as a 29-leg claim** (§5) |
| 3 | NAV-GEN-1 A0 `arrived_verified` per target before/after | **RED — not run** (§5); the same defect measured on the panel instead (§4) |
| 4 | `test_k0_arrival_authority.py` green | **GREEN** (§3) |
| 5 | `test_authority_half_scale_smoke.py` green | **GREEN** (§3) |
| 6 | `test_embodied_plan_eval.py` green | **GREEN** (§3) |
| 7 | re-freeze record complete (bridge, provenance, pinned numbers) | **GREEN** (§7) |
| 8 | `mutation_panel.py --out <scratch>` reported, D-15's verdict before/after | **GREEN — D-15 AGREES** (§4) |
| 9 | no safety floor touched; `config.py` unchanged; `pipeline.py` net-negative or unchanged | **GREEN** (§8) |
| 10 | A3: `nav-region_goal-B-09` false_arrival = 0 by receipt absence | **RED in the eval — second author found and named** (§6); the receipt itself refuses the claim |
| 11 | A3: the matrix `false_arrival` total reported | **1 in BOTH v4 and v5** (§7) — the single row is B-09 |

---

## 3 · Suites (all through `~/.cache/parcel-guard/pytest_guard.sh --label W4`, never `-n auto`, no `--pdb`)

```
pytest tests/test_arrival_receipt.py tests/test_brain_runtime_adapter.py tests/test_k0_arrival_authority.py
       tests/test_authority_half_scale_smoke.py tests/test_embodied_plan_eval.py
       tests/test_nav_instruct_digest_recipe.py tests/test_nav_instruct_episodes_v{2,3,4}.py
       tests/test_v4s_search_cells.py tests/test_nav_instruct_generator.py tests/test_arrival_settle.py
       tests/test_arrival_authority_differential.py tests/test_headless_city_tasks.py
       tests/test_arrival_etiquette_pipeline.py tests/test_poi_admission.py tests/test_c3_cutover.py
       tests/test_scene_surface_truth.py tests/test_city_semantics.py tests/test_backends.py
       tests/test_authority_family_equality.py tests/test_nav_instruct_rescoring.py
       tests/test_nav_instruct_ledger_guard.py tests/test_navigation.py tests/test_scene_assets.py
       tests/test_portal_world.py tests/test_person_aware_nav.py -q -p no:randomly
→ 570 passed, 1 xpassed, 0 failed (58.4 s)
```

Tested at candidate sha **c96ac34 + this worktree's uncommitted diff**, in worktree
`/home/jaewoo-jang/.cache/parcel-0e/wb/w4`.

**Six tests moved, each because the behaviour they pinned is what this card changed** (no criterion relaxed):

| test | why it moved |
|---|---|
| `test_k0_arrival_authority::test_semantics_and_eval_object_goal_regions_agree` | now compares semantics ≡ generator ≡ pipeline at the **live** set (v5) and pins that v4 does **not** carry the support constraint — the same idiom `test_next_to_eval_pipeline_approach_footprint_agree` already used for v3 |
| `test_arrival_settle::test_a_poi_arrival_with_no_committed_region_is_not_verified` | its own docstring predicted this: *"when C1 lands and the crosswalk grounds to the scene region, `inside_arrival_region` stops being `None` here"*. It has. |
| `test_arrival_settle::…needs_the_claim_the_region_and_the_settle[…True]` | the venue's settle-window region verdict is now what the receipt uses (`inside_region=`), instead of a second single-frame opinion beside it |
| `test_brain_runtime_adapter::…requires_terminal_verifier` | a NavigateTo terminal now needs a receipt; the state string alone returns `failed/no_arrival_receipt` |
| `test_scene_surface_truth::…building_is_still_built_from_the_centre` | rebuilt with the same support the extractor found; the BAND and footprint are asserted unmoved, and a building (no support surface) is asserted byte-identical to the pre-B32 region |
| `test_v4s_search_cells::test_all_four_digest_sentinels…` | renamed to `…every_digest_sentinel…`; the sentinel COUNT grows with every re-freeze, so it asserts `== len(DIGEST_SENTINELS)` and `>= 4` plus "the newest set is pinned" instead of the literal 4 |

New: `tests/test_arrival_receipt.py` (13 cells) — the B32 bench pose refused with the contract's own token, the
refusal ordering, staleness, wrong-place, and **the headline**
`test_a_scorer_true_system_false_leg_is_not_arrived_for_any_consumer`: three seeded legs × four consumers
(executive verifier, mission log, whisperer, speech acts), all "not arrived", with a control that a real arrival
reaches all four.

---

## 4 · The mutation panel — **D-15 now AGREES**

`python scripts/mutation_panel.py --out <scratch>/panel.json` (committed panel untouched):

| | before (C0's recorded run) | after (this worktree) |
|---|---|---|
| `nav-region_goal-D-15-1b8b2361` | `navigation_step_limit_inside_goal`, 1.5151 m from the POI point against a 1.50 m radius — a **15 mm** miss; `no_authority_disagreement` **declared disabled as a kill channel** | **`success: True`, `failure: none`, `distance_to_goal_m: 0.0`**, final pose (2.677, 0.8194) — inside the crosswalk polygon |
| `clean_checks.no_authority_disagreement` | true but DISABLED (the C0 declaration) | **true and LIVE** |
| `reactive_gate_disabled` | killed | **SURVIVED** |
| panel verdict | passed with a declared disable | **FAILED — survivor `reactive_gate_disabled`** |

**D-15's verdict: it AGREES, and it agrees for the reason B32 required** — "the system and the scorer judge the
same region", not because a 0.4 mm nudge crossed a radius. **W5 may withdraw the declared disable**, by
regeneration and not by hand.

And the coupled half B32 predicted lands exactly as AUDIT_C0_C2 §4 said it would: *"'D-15 agrees again' and 'the
gate never fires' are the same event"*. `reactive_gate_disabled` is now a survivor, so the panel EPISODES must be
re-chosen on cells where the gate binds — **W5 / Sol's remediation**, unchanged in scope. The panel also still
stamps `episode_set_version: v4` while `_CURRENT_FROZEN_EPISODE_SET` is now v5: `tests/test_mutation_panel_freshness.py`
is RED in this worktree **by design** (A1), and W5 owns it. I touched no panel file.

---

## 5 · NAV-INT-1 and NAV-GEN-1 — what was run, and the harness finding

**A harness-side stale copy of the K0 authority.** `research/20260829/nav-interrupt-1/harness.py`
`GoalSpec._region_for` builds `object_near_goal_region(position, radius, label=, entity_id=)` — a **bare annulus**,
with no support surface. Since B32 that is the superseded convention. Left as is, the harness's scorer certifies
ground the product refuses and **every bench leg is `system_failed_but_arrived` by construction**, whatever the
product does. It is a foreign folder (standing constraint: *"foreign folders never edited"*), so I did **not**
edit it in the worktree; the required delta is one call-site change, stated here for the integrator:

```python
support = support_surface_for(landmark["position"],
    ((str(r.get("label","")), r["polygon"]) for r in self.table.values() if r.get("polygon")))
return object_near_goal_region(..., support_polygon=support,
    support_clearance_m=TERMINAL_SUPPORT_CLEARANCE_M if support is not None else 0.0)
```

**Measured instead**, on a scratch copy of the harness (`<scratch>/ni1/`, WORKDIR → `~/.cache/parcel-0e/wb/w4-sock/`,
`REPO` → this worktree, the above delta applied, `systemd-run --user --scope -p MemoryMax=12G`), through the live
`RobotRuntime.handle_text` product path:

```
run.py --stage controls --only bench --seed 20260829
[control] ctl-bench#0 sys=False scorer=False cat=agreement dtg=0.243 39.6s
[control] ctl-bench#1 sys=False scorer=False cat=agreement dtg=0.243 40.0s
[N3 orphan check] clean=True ours=[] other_processes=[]
```

**2/2 bench legs: `agreement`, `system_failed_but_arrived` = 0**, at dtg **0.243 m** — the same 0.244 m shortfall
B32 recorded, now reported by BOTH authorities instead of only one. Before this card those legs were
`scorer=True sys=False cat=system_failed_but_arrived`.

**Bars 1–3 are RED as stated bars.** The full 80-leg / 29-leg tier is a ~2–2.5 h single-simulator sweep and
NAV-GEN-1 A0 is a second multi-hour sweep; five executors share this host (load 3–7 through the session) and I did
not have the wall clock for either. What is measured is above; what is claimed is only what is measured.
**Recommended for the verifier:** land the harness delta, then `run.py --all --seed 20260829` and the NAV-GEN-1 A0
frozen block. (`~/.cache/parcel-0e/wb/w4-scratch/ni1/` holds the patched copy, ready to run.) The mechanism is not in doubt — §4's D-15 row and §3's `test_arrival_receipt` cells exercise the same
two predicates the tier bars read.

---

## 6 · A3 — `nav-region_goal-B-09-3ee156e4`, measured and NOT closed

Run under both sets on this tree (recipe of record, `--no-ledger`):

Full matrix, recipe of record, `--no-ledger`, `--per-family 25` (the A3 row):
**`false_arrival` total = 1 under v4 and 1 under v5, and the single row IS B-09.**

| | v4 | v5 |
|---|---|---|
| goal kind | polygon, `band_m: null`, no support | **identical** |
| terminal | `arrived/arrived_verified` | `arrived/arrived_verified` |
| dtg to the answer key | 4.7739 m | **4.7739 m** |
| authority | `false_arrival` | **`false_arrival`** |

**Correction (f) does not reach it, and the bridge says so rather than implying otherwise**
(`bridge_v4_v5.KNOWN_UNMOVED_FALSE_ARRIVAL`, citing `research/20260824/nav-quality/RESULTS.md` §5.1). It is a
region_goal whose K0 region is a POLYGON with `band_m: null`; (f) intersects a `near` BAND with a support surface.

**Measured root cause (instrumented `_semantic_arrival_verified`):** the navigator **committed `sidewalk_south`**
(polygon y ∈ [−3.75, −2.25], `goal_source: semantic_search`, `terminal_relation: inside`) and ended at
**(−0.0563, −2.5739)** — genuinely inside it with terminal clearance. The terminal contract verified an arrival
that is **true of the place the system chose**. The frozen episode's answer key names the OTHER instance,
`sidewalk` (north, y ∈ [2.2, 4.2]), 4.7739 m away. It is a wrong-**INSTANCE** mismatch about *which sidewalk* —
the C1 goal-representation family (W3's card), not the band-vs-support pair.

**What the receipt says (A3's own test):** the receipt cut on that terminal carries `region_id: "sidewalk_south"`.
`receipt_says_arrived(receipt, goal_id=…, sequence=…, region_id="sidewalk")` — the leg's own asked-for place — is
**False**. So the receipt rule *does* refuse the claim, by principle and with no per-episode exception: a receipt
about another place is not this leg's receipt. `ArrivalReceipt.is_for()` gained that third identity and
`tests/test_arrival_receipt.py::test_a_receipt_about_another_place_is_not_this_legs_receipt` pins it on B-09's own
geometry.

**The second author, named:** `evals/nav_instruct/runner.py` still derives `system_arrival` from
`system_arrival_claim(result.status, result.reason)` — **a status STRING**, not the receipt. That is why the eval
still records `false_arrival` on B-09 even though the receipt refuses it. **I did not migrate it in this card**, and
that is a decision with a measured reason, not an omission: `follow_owner` commits no K0 arrival region at all, so a
receipt-based `system_arrival` refuses `no_committed_arrival_region` on **3/5** minival `follow_owner` rows and
rewrites the eval's authority semantics for every version. Rewriting the scorer's notion of "the system claimed
arrival" inside a re-freeze commit is exactly what re-freeze condition (i) exists to prevent. **Recorded as a named
finding for the board**, with the fix shape already in the leaf (`region_id=`) and pinned by a test.

---

## 7 · Re-freeze conditions (i)–(iii), as a checklist with the numbers

Both cells run in **one process, on one tree**, recipe of record (`bridge_v4_v5 --run` → `results/bridge_v4_v5.json`):

| | v4 episodes × this tree | v5 episodes × this tree |
|---|---|---|
| SR | **0.24** | **0.24** |
| SPL | **0.18509069363202812** | **0.18509069363202812** |
| `sr_frozen_rule` | 0.12 | 0.12 |
| mean dtg | 8.362188 m | 8.392188 m |
| **collisions** | **0** | **0** |
| **false_arrival** | **0** | **0** |
| agreement / disagreement | 21 / 4 | 21 / 4 |

**(i) Not a re-baseline of a red SAFETY result.** collisions **0 → 0**, false arrivals **0 → 0**, bit-identical.
`episodes_gained: []`, `episodes_lost: []`, `verdict_changed: []`, `system_arrival_moved: []`. The only measured
delta in the whole minival is one episode's dtg. No check is carried red; nothing is declared disabled by W4.
`PINNED_FROZEN_FALSE_ARRIVAL` stays **0** (never relaxed).

**(ii) Every moved row attributed to a named commit/card.** `cause = "B32 / card W4 (ARRIVAL-AUTHORITY-1), owner E3
decision 2026-08-30"` on every row, in `bridge_v4_v5.py` and in the v5 manifest provenance.

* **minival: 1 of 25 moved** — `nav-object_goal-C-10-68aa2ab8` ("go to the lamp post", `lamp_post_2`):
  band **[1.18, 1.38] → [1.18, 1.38] (UNCHANGED)**, support surface **none → the south sidewalk @ 0.32 m**,
  `shortest_path_m` **2.5 → 3.0**, dtg **1.870000 → 2.620000**, reason `failed/semantic_target_unreachable` →
  `failed/semantic_target_unreachable`, authority `agreement` → `agreement`.
* **full matrix: 5 of 125 moved** (45 embed a `band_m` and *could* have): the five `object_goal` `near` episodes
  whose target stands on a sidewalk. `next_to`/`towards` bands are not support-gated by the terminal contract and
  buildings have no support surface, so the other 40 are untouched **by construction**, and the bridge asserts it
  (`only_object_goal_moved`, `every_moved_target_stands_on_a_support_surface`, `no_band_moved`, all true;
  `unattributed_moves: []`).
* Digests: minival `4113607b… → 2822ebfd…`; full matrix `e7c302dd… → 5ea2cd93…`.

**(iii) The frozen `episode_digest` never moves.** v1 `da245f6f…`, v2 `2f8c0153…`, v3 `a1d43298…`,
**v4 `e7c302dd…` (matrix) / `4113607b…` (minival)** all regenerate byte-identically; `episodes/v1…v4/` files and
manifests are untouched (`git status` clean for them) and their ci_gate pins are unchanged. The bridge reads v4's
digest out of the committed ledger row and asserts it against a live regeneration
(`v4_episode_digest_unmoved: true`), and `test_the_v5_refreeze_did_not_move_the_v4_row` pins it in the suite.

**The bench witness, re-measured rather than cited** (`bridge_v4_v5.derivation_check`, 399 424 area-uniform samples):
unstandable fraction of the certified annulus **0.7728** (B32 recorded 0.7726 — reproduces); the parking pose
(−0.68, 2.28) is admitted by v4 (**True**) and refused by v5 (**False**) at **0.2400 m** short (B32: 0.244 m).

**And at matrix scale** (125 episodes, both versions, recipe of record, `--no-ledger`;
`nav-instruct-v1-baseline-v4-20260830T114051Z` / `…-v5-20260830T114458Z`, recorded in
`bridge_v4_v5.RECORDED_FULL_MATRIX` with the exact command):

| | v4 × this tree | v5 × this tree |
|---|---|---|
| SR | **0.232** | **0.232** |
| `sr_frozen_rule` | 0.136 | 0.136 |
| SPL | 0.16191322072332956 | **0.1648644951026271** |
| mean dtg | 8.400684 m | 8.412604 m |
| **collisions** | **0** | **0** |
| **false_arrival** | **1** | **1** |
| agreement / tolerated / disagreement | 102 / 1 / 21 | 102 / 1 / 21 |
| failure histogram | 24/2/13/0/21/35/1/29 | **identical** |

SR, `sr_frozen_rule`, collisions and BOTH histograms are bit-identical; SPL **rises** 0.161913 → 0.164864,
because four of the five moved episodes now route to a band point the contract will stand on rather than one it
would refuse. The one `false_arrival` in each column is B-09 (§6), unmoved by construction.

**Superseded artifact kept:** `nav-instruct-v1-baseline-v4-20260811T070536Z.json` and `bridge_v3_v4.py` untouched.
**Known drift, NOT this card's:** a fresh v4 cell on this tree does not reproduce the 2026-08-11 committed row —
that is card A2's clearance work and `a379bf4`'s D-15 suffix, and it is **W5's** row-by-row record. Measuring both
cells on one tree is precisely what keeps that off correction (f)'s account.

---

## 8 · Constraints

* **No safety floor touched.** No change to `apply_reactive_safety`, `apply_collision_brake`, `finalize_command`,
  the A3 latch or the A6 stop. The only "narrowing" is the arrival TRIGGER, never a widening of any band.
* **`config.py` unchanged** (0 lines in the diff).
* **`pipeline.py`: 7211 lines at HEAD → 7211 lines. UNCHANGED** — four edits in place (import block, POI mission
  metadata, the arrival admission, the relation read) plus `_on_support_surface` collapsed to a delegation.
* **0 `noqa`** in the diff. **Ruff: `All checks passed!`** on every file I touched; the 10 findings that remain in
  the tree are the pre-existing baseline in files I did not modify (`camera_channel/backends/factory.py`,
  `detection_adapter/sim_bridge.py`, `scripts/mutation_panel.py`). **No new fingerprints.**
* **No `ci_gate.py --tier` run** (executors never run it).
* **Git read-only** apart from `git worktree add` and two `git checkout -- <file>` restores of my own worktree.
* **Owner facts respected:** `parcel_memory.sqlite3` never opened (PARCEL_MEMORY_PATH → scratch); the owner's live
  stack untouched.

**Hunk adjacency — `runtime.py`.** My hunks: `@@ -172`, `-4014`, `-4031`, `-7091`, `-12589`, `-12679`, `-12789`,
`-16025`, `-16546`, all **adjacent to `_step_navigation` / `start_navigation` / `_brain_runtime_state` /
`_log_mission_terminal` / `_narrate_mission_terminal`** — the terminal-receipt path only. The dirty root's hunks in
that file are at `@@ -38, -422, -2196, -2254, -2508, -2658, -2670, -2685, -3193, -3777, -3803, -3819, -3833, -4950,
-5106, -5331, -5356, -9428, -9545, -9574, -11481, -11855, -17968`. **None overlap.**
`brain/executive.py` is **not touched by this card**; the executive's terminal fact is decided in
`brain/runtime_adapter.py`, which carries no owner hunks. **Nothing is BLOCKED on the 28-file diff.**

---

## 9 · `git diff --stat` (worktree, vs HEAD `c96ac34`)

```
 evals/companion/run_embodied_plan_v1.py       |   6 +
 evals/nav_instruct/README.md                  |  52 +++++-
 evals/nav_instruct/generator.py               |  79 +++++++++
 evals/nav_instruct/runner.py                  |   6 +
 evals/nav_instruct/surface_scoring.py         |   2 +-
 scripts/ci_gate.py                            |  24 +++
 src/parcel_robot/brain/runtime_adapter.py     |  27 +++
 src/parcel_robot/instructnav/scoring.py       | 227 +++++++++++++++++++++++++-
 src/parcel_robot/navigation/pipeline.py       |  40 ++---
 src/parcel_robot/navigation/poi_admission.py  | 122 ++++++++++++++
 src/parcel_robot/perception/city_semantics.py |  49 +++---
 src/parcel_robot/runtime.py                   | 127 +++++++++++++-
 src/parcel_robot/simulation/headless_city.py  |  65 +++++++-
 tests/test_arrival_settle.py                  |  31 ++--
 tests/test_brain_runtime_adapter.py           |  40 ++++-
 tests/test_k0_arrival_authority.py            |  87 +++++++++-
 tests/test_nav_instruct_digest_recipe.py      |  29 ++++
 tests/test_scene_surface_truth.py             |  19 +++
 tests/test_v4s_search_cells.py                |  20 ++-
 19 files changed, 955 insertions(+), 97 deletions(-)
```

New files (untracked in the worktree):
`evals/nav_instruct/bridge_v4_v5.py`, `evals/nav_instruct/episodes/v5/` (25 + manifest),
`evals/nav_instruct/results/bridge_v4_v5.json` (diagnostic, `frozen_baseline: false`),
`src/parcel_robot/instructnav/arrival_receipt.py`, `tests/test_arrival_receipt.py`.
(`.parcel` is the venv symlink — not part of the patch.)

---

# F1 · NAV-INT-1 at full scale, harness fixed

**Coordinator ruling recorded:** `research/20260829/nav-interrupt-1/` is parcel-0e's folder (wave A, C7 edited
it) — **not foreign to this wave**. The delta I had reported as "for the integrator" is therefore applied in the
worktree and is part of the patch.

**`harness.py` `GoalSpec._region_for` — the one call site.** It built the **bare annulus**, the superseded K0
convention: the terminal contract has always ALSO required the robot to stand on the object's support surface
(`pipeline._on_support_surface`, refusal `outside_support_polygon`), and the two were never intersected. On this
harness that meant **77.26 %** of the band scored around `bench_1` was ground the contract will never accept, so
all 11 bench legs were `system_failed_but_arrived` **by construction, whatever the product did**. It now asks
`support_surface_for(...)` — the shared W4 authority — of the SAME scene truth the table already holds, and passes
`TERMINAL_SUPPORT_CLEARANCE_M`. **C7-F1's committed-instance rule is untouched:** `region_with_provenance` still
decides WHICH instance is scored; `_region_for` only builds the region for the instance it chose.

**`run.py` — provenance and isolation, no behaviour change.** Two env overrides, both defaulting to the recorded
values so the README's reproduce command is byte-unchanged:
`NI1_WORKDIR` (sockets + per-session memory; this run uses `~/.cache/parcel-0e/wb/w4-sock/`, never the shared
`~/.cache/parcel-0e/ni1`) and `NI1_OUT_PREFIX` (this run writes `w4-b32-{controls,sequence_controls,episodes}.jsonl`,
`w4-b32-results.json`, `w4-b32-sample_episode.txt`). **The recorded `controls.jsonl` / `sequence_controls.jsonl` /
`episodes.jsonl` / `results.json` / `sample_episode.txt` are not written to.**
`gold_blind.json` sha unchanged: `c253df2f707b158c4f6aaab42ce9fae77e98aae9502ef4bea987e2bae1fc1e65` = `gold_blind.sha256`.

```
git diff --stat -- research/
 research/20260829/nav-interrupt-1/harness.py | 32 +++++++++++++++++++++++++++
 research/20260829/nav-interrupt-1/run.py     | 29 ++++++++++++++++++------
```

New artifacts this run writes (untracked, beside the recorded ones):
`w4-b32-controls.jsonl`, `w4-b32-sequence_controls.jsonl`, `w4-b32-episodes.jsonl`, `w4-b32-results.json`,
`w4-b32-sample_episode.txt`.

**Started** (background, own sockets, `systemd-run --user --scope -p MemoryMax=12G`, `PARCEL_MEMORY_PATH` → scratch):

```
NI1_WORKDIR=~/.cache/parcel-0e/wb/w4-sock NI1_OUT_PREFIX=w4-b32- \
  python run.py --all --seed 20260829
```

Bars 1–2 (≤ 2/80; bench 0/29) reported when it finishes. **Early evidence already recorded** (§5): the two bench
control legs run before the sweep read `sys=False scorer=False cat=agreement dtg=0.243` — agreement, not
`system_failed_but_arrived`.

---

# F2 · The second author, migrated

`evals/nav_instruct/runner.py` derived `system_arrival` from `system_arrival_claim(status, reason)` — **a status
string**. For the three navigation families it now **cuts an `ArrivalReceipt` from its own loop** (the region the
mission committed, the pose the loop applied, its own terminal stop) and requires it to be a receipt for **this leg
and this place**:

```python
RECEIPT_ARRIVAL_FAMILIES = frozenset({"object_goal", "object_relative", "region_goal"})
claim = receipt_says_arrived(receipt, goal_id=episode.instruction,
                             sequence=self._leg_sequence, region_id=episode.target_entity_id)
```

No receipt ⇒ `False`. `follow_owner` / `circle_owner` **keep the status path** — they are driven by the follow and
spatial controllers, which commit **no `arrival_goal_region` at all**, so a receipt could only ever say
`no_committed_arrival_region` and the migration would *delete* their claims rather than verify them. Stated in the
`RECEIPT_ARRIVAL_FAMILIES` docstring and pinned by `tests/test_nav_instruct_receipt_authority.py` (4 cells, all
green): the family split, B-09's `wrong_instance`, the spatial families' claims surviving with no receipt label,
and the refusal-token vocabulary.

**B-09 — `false_arrival` by receipt absence, reported as `wrong_instance`:**

| `nav-region_goal-B-09-3ee156e4` | before F2 | after F2 |
|---|---|---|
| terminal | `arrived/arrived_verified` | `arrived/arrived_verified` (unchanged — honest about the place the system chose) |
| `system_arrival_claim(status, reason)` | True | **True** (the status string still says yes) |
| `score.system_arrival` | True | **False** |
| trace `arrival_receipt` | — | **`wrong_instance`** |
| authority | `false_arrival` | **`agreement`** |
| failure class | `false_arrival` | `planning_error` |

The receipt says `arrived` about `region_id: "sidewalk_south"`; the leg was issued to `sidewalk`; a receipt about
another place is not this leg's receipt. **Still open** (not W4's): the instance SELECTION itself — F2 stops the
eval mis-scoring it as an arrival, it does not make the navigator commit the sidewalk the directive meant. That is
W3's per-navigator world identity.

**Re-run, recipe of record (`--budget-policy scaled-path-v1 --max-steps 200 --seed 20260804 --no-ledger`):**

| minival (25) | v4 | v5 |
|---|---|---|
| SR | 0.24 | 0.24 |
| SPL | 0.18509069363202812 | 0.18509069363202812 |
| collisions | 0 | 0 |
| **false_arrival** | **0** | **0** |
| agreement / disagreement | 21 / 4 | 21 / 4 |

| matrix (125, `--per-family 25`) | v4 | v5 |
|---|---|---|
| SR | **0.232** | **0.232** |
| `sr_frozen_rule` | 0.136 | 0.136 |
| SPL | 0.16191322072332956 | **0.1648644951026271** |
| mean dtg | 8.400684 m | 8.412604 m |
| **collisions** | **0** | **0** |
| **false_arrival** | **0** (was 1) | **0** (was 1) |
| agreement / tolerated / disagreement | 103 / 1 / 21 | 103 / 1 / 21 |
| failure histogram | 24/2/14/0/21/35/**0**/29 | **identical** |

**Moved rows, named.** F2 moves **exactly one episode, in both versions**: `nav-region_goal-B-09-3ee156e4`
(`false_arrival` → `agreement`, failure `false_arrival` → `planning_error`, `planning_error` 13 → 14,
`agreement` 102 → 103). **The minival does not move at all** — it carries no wrong-instance row. SR, SPL, mean dtg
and collisions are unchanged by F2 in every column. The v4↔v5 delta is still the single re-freeze row
`nav-object_goal-C-10-68aa2ab8` (band unchanged, `shortest_path_m` 2.5 → 3.0, dtg 1.870 → 2.620).

**F2 verification sweep** (guard, `--label W4`): the 20 nav_instruct / arrival / receipt / POI / headless files —
**301 passed, 1 xpassed, 0 failed**. Every other consumer of `NavInstructRunner` re-run too
(`test_dr2_pose_drift_arm`, `test_e4_evidence_seams`, `test_nav_scene_split_output`, `test_person_cell`,
`test_rm3_route_memory_arms`, `test_search_reground_bench`, `test_nav_metamorphic`): **162 passed, 7 skipped,
3 xfailed, 1 failed**. The one failure,
`test_person_cell.py::test_deadlock_signature_reproduces_with_an_undeclared_bystander`
(`veto_fraction 0.875 >= 0.9`), is **PRE-EXISTING at clean `c96ac34`** — re-run alone in a throwaway clean
worktree at HEAD, same failure, same number. Not W4's, and reported rather than absorbed.

**Re-freeze conditions re-checked under F2:** collisions **0 → 0**, false arrivals **0 → 0**, both bit-identical
across v4 and v5. Condition (i) still holds, and the matrix false-arrival total is now **0 rather than 1** — better,
never relaxed. `PINNED_FROZEN_FALSE_ARRIVAL` stays 0. v1–v4 minival digests re-verified byte-identical
(`cf4d5384… / a17c04db… / 919a0fea… / 4113607b…`). The bridge was regenerated on the F2 tree and carries the
`closed_by` / `still_open` record.

---

# F3 · The v4 row on the CODE axis — W4 owns two of the seven moves

**Correction to §7's wording.** The cell labelled "v4 episodes × this tree" is **v4 × HEAD+W4**. Clean `c96ac34`
reads **SR 0.20 / SPL 0.153259**; HEAD+W4 reads **SR 0.24 / SPL 0.185091**. That pair is **W4's**, and naming it is
the point of measuring both columns on one tree.

**The v4 frozen row's history: seven moves, three causes.**

| cause | moves | note |
|---|---|---|
| **A2** | 4 | ≤ 2026-08-24, the clearance work — including the lost `nav-object_relative-A-00` success recorded as a **LOSS** citing NAV-QUALITY §1.4. **W5's** row-by-row record |
| **`a379bf4`** | 1 | the D-15 suffix. **W5's** record |
| **W4** | 2 | **this card's**, named below |

**W4's two, differenced v4 × clean-HEAD-behaviour vs v4 × HEAD+W4:**

1. **`nav-region_goal-D-15-1b8b2361`** — `timed_out/navigation_step_limit_inside_goal` + `authority_disagreement`
   → **`arrived`** + **`agreement`**, **system True AND scorer True**, dtg `1.89994 → 0.0`, success **False → True**.
   Cause: W4's region-class POI fix (a crosswalk is a REGION; the scene's own polygon is committed and the 1.5 m
   point radius stops deciding). **This IS "D-15 agrees", and it accounts for the +1 success and the ENTIRE SR
   0.20 → 0.24 / SPL 0.153259 → 0.185091 move.**
2. **`nav-object_relative-D-15-61f68ad6`** — `failed/semantic_target_not_found` →
   `failed/semantic_target_unreachable`. A **reason-only relabel**; authority, success and dtg all unmoved.

**Attribution, stated plainly: the SR/SPL pair moves because of W4's D-15 fix — never because of the re-freeze.**
Correction (f) does not touch either episode; v4 and v5 are byte-identical for both. §7's earlier phrase "known
drift, NOT this card's" was wrong about two of the seven rows and is superseded by this section.

**The loop that closes.** The same product change that makes D-15 agree is what lets C0's declared
`no_authority_disagreement` disable be **withdrawn** AND what **blinds the `reactive_gate_disabled` mutant on the
old five panel rows** — "D-15 agrees again" and "the gate never fires" are one event, not two (AUDIT_C0_C2 §4).
That is precisely why **W5 must select the panel rows BY MEASUREMENT** — per-episode intervention counts showing
the gate binds on each row — and never by hand.

Recorded in code as `bridge_v4_v5.V4_ROW_CODE_AXIS_HISTORY` (and in the module's THE CODE AXIS docstring), so a
reader differencing the committed row against a fresh v4 cell finds the attribution beside the numbers.

---

# F1 RESULT · NAV-INT-1 tier at full scale — **BOTH BARS GREEN**

`run.py --all --seed 20260829`, harness fixed, own sockets, `MemoryMax=12G`, `PARCEL_MEMORY_PATH` → scratch.
Wall **3478.7 s** (58 min). 10 controls + 10 sequence controls + **40 tier episodes, 0 tier errors**.
Orphan check **clean**: 60 sims launched by this process, `survivors_ours: []`, `survivors_other_processes: []`.
Written to `w4-b32-{controls,sequence_controls,episodes}.jsonl` + `w4-b32-results.json`; the recorded
`controls.jsonl` / `sequence_controls.jsonl` / `episodes.jsonl` / `results.json` are **untouched**
(`git status research/` shows only `harness.py`, `run.py` modified and the four `w4-b32-*` files new).

| bar | measured | verdict |
|---|---|---|
| authority disagreements **≤ 2/80** | **0 / 80** | **GREEN** |
| bench `system_failed_but_arrived` **0/29** | **0 / 29** | **GREEN** |

```
totals: n_scored_legs 80 · agreement 80 · tolerated_boundary 0
        system_failed_but_arrived 0 · system_succeeded_but_not_arrived 0 · unknown 0
```

| goal | n | agreement | `system_failed_but_arrived` | `system_succeeded_but_not_arrived` |
|---|---|---|---|---|
| **bench** | **29** | **29** | **0** (was **11/29**) | 0 |
| sidewalk | 17 | 17 | 0 | 0 |
| towards_lamppost | 17 | 17 | 0 | 0 |
| lamppost | 10 | 10 | 0 | 0 |
| come_here | 7 | 7 | 0 | 0 |

The bench denominator reproduces B32's exactly (29 legs: 2 control, 15 re-issue, 7 amended, 3 uninterrupted,
2 continued). **Every one of the 80 scored legs is now `agreement`** — the tier's authority-disagreement class is
empty, not merely under the bar.

**Read it honestly.** The bench legs are agreement at **`mean_dtg_m` 0.2435 m** — B32's 0.244 m, now reported by
BOTH authorities instead of only one. The dog still does **not reach** standable ground at the bench (controls
`success_both` 0/2): B32's fix makes the scorer stop certifying the road, it does not widen the 2 m strip flanked
by a lamppost and a tree that `near_arrival.py` documents. **The bar was `system_failed_but_arrived` 0/29, and it
is 0/29 — the honest failure is now scored as a failure instead of as an arrival.**

---

# F4 · The expected identity comes from the runtime, not from the receipt

**The defect (integrator's lens, confirmed).** All three product consumers read the expected identity **off the
receipt they were holding** — `receipt_says_arrived(receipt, goal_id=getattr(receipt, "goal_id", ""), sequence=
getattr(receipt, "sequence", -1))` — which asks the receipt whether it is itself, and never passed `region_id`.
So `is_for()` was a tautology on the product path and two things the card forbids survived: **(a)** a receipt cut
on generation *N* still verified the terminal of leg *N+1* — the re-issue inheriting the previous walk's receipt;
**(b)** B-09's other-place refusal existed only in the eval runner, so the real dog would have narrated an arrival
at `sidewalk_south` when asked for the north sidewalk.

**The fix.** A typed `LegIdentity(goal_id, sequence, region_id)` carried by the caller's own state:

* `runtime._navigation_leg` — established at the same site that cuts the receipt, from the **same `directive` and
  `generation`** (`arrival_receipt(goal_id=directive, sequence=generation, …)`). Its `region_id` is snapped the
  **first** time the leg commits a region and is not moved afterwards, so a mission that re-commits to another
  instance mid-leg terminates with a receipt about a place this leg was not issued for.
* `headless_city.HeadlessTaskResult.arrival_leg` — the venue's own directive, its own leg counter, its own
  committed region. `arrived_verified` is now the leg-checked predicate, and `run_embodied_plan_v1.py` passes
  `arrival_leg=result.arrival_leg` through rather than re-deriving.
* `SemanticRuntimeState.arrival_leg` — the executive's leg, filled from `_brain_runtime_state`.

`committed_region_id(metadata)` is the ONE derivation used by both the receipt and the leg snapshot, so the
comparison can never be a spelling mismatch. `receipt_refusal(...)` is now the implementation and
`receipt_says_arrived` its boolean, so the refusal has a printable name: **`no_arrival_leg`** (the caller holds no
leg — distinct from `no_arrival_receipt`, because "a receipt and no idea what walk it belongs to" is a different
fault), **`stale_arrival_receipt`**, **`arrival_receipt_for_another_place`**, then the receipt's own tokens.

**Consumer sites, all three:** `brain/runtime_adapter._result_for` (detail code is the refusal token),
`runtime._log_mission_terminal`, `runtime._narrate_mission_terminal` (whisperer C4 + speech acts C5). `leg is None`
⇒ not arrived, for the same reason `receipt is None` is.

**The wiring test** — new `tests/test_arrival_receipt_wiring.py`. One **good** receipt (asserted `arrived`) held up
against four legs, through all three consumers, plus the positive twin so "always refuse" cannot pass:

| cell | leg | every consumer says |
|---|---|---|
| `stale_generation` | gen 7 receipt, leg **gen 8** | not arrived · `stale_arrival_receipt` |
| `other_place` | receipt for `sidewalk_south`, leg for **`sidewalk`** | not arrived · `arrival_receipt_for_another_place` |
| `other_place_mirrored` | receipt for `sidewalk`, leg for **`sidewalk_south`** | not arrived · `arrival_receipt_for_another_place` |
| `no_leg` | receipt, **leg `None`** | not arrived · `no_arrival_leg` |
| **positive twin** | same generation, same region | **arrived** — executive `succeeded`, log "Arrived at the sidewalk.", whisperer `mission_arrived` |

Plus a property cell asserting the two identities are genuinely different objects (so the negatives cannot pass
trivially) and one pinning that the leg snapshot and the receipt name the region through the same derivation.

**Suites through the guard:** `test_arrival_receipt_wiring.py`, `test_arrival_receipt.py`,
`test_brain_runtime_adapter.py`, `test_k0_arrival_authority.py`, `test_arrival_settle.py` → **47 passed**.
Widened to every receipt consumer (`test_embodied_plan_eval`, `test_nav_instruct_receipt_authority`,
`test_headless_city_tasks`, `test_authority_half_scale_smoke`, `test_poi_admission`, `test_backends`,
`test_arrival_etiquette_pipeline`) → **123 passed, 1 xpassed**.

**Two tests moved with the behaviour** (neither is F4's — both are the region-class POI fix landing):
`test_brain_runtime_adapter`'s unverified cell now reads `no_arrival_leg` (it supplies neither receipt nor leg),
and `test_runtime.py::test_social_affect_action_defers_until_navigation_finishes` teleported the body to the
surveyed POI point `(3.5, -0.6)` — **0.2 m outside the crosswalk polygon**, the exact D-15 coordinate B32 names.
"At the crosswalk" now means inside it, so the teleport moves to `(3.1, 0.8)`, inside with the terminal clearance.

**A latch defect F4's own sweep found, and fixed.** Running `test_runtime.py` for the first time under the
receipt seam surfaced `test_social_affect_action_defers_until_navigation_finishes` hanging at
`wait_for_trajectories`. Instrumented on the live navigator: `mission.status` was already `arrived`, so
`_inside_arrival_goal_region` returned `False` on its own first guard (`status != "running"`), and my
`poi_region_arrival_admits` narrowing — `return bool(inside_region)` for a POI mission with a committed region —
then refused to emit the stop on **every subsequent tick**. The mission reported `arrived` while the runtime never
saw a terminal and the navigator drove on inside its own goal. The original condition
`geometrically_arrived or inside_arrival` carried the latch (`geometrically_arrived` is
`cmd.stop or status == "arrived"`) and my narrowing had dropped it. Fixed in `poi_admission.py`: the latch is
tested FIRST — an already-arrived mission is never un-arrived, because that decision was taken on the tick the
narrowing applies to. The D-15 narrowing is untouched (the first arrival decision still needs the region).

Re-measured after the fix, everything bit-identical to F2: panel `no_authority_disagreement` **true and live**,
D-15 `success: True / failure: none / dtg 0.0` at (2.677, 0.8194), `reactive_gate_disabled` still the survivor;
minival v4/v5 SR 0.24 / SPL 0.185090694 / collisions 0 / false_arrival 0 / agreement 21 / disagreement 4; matrix
v4 SR 0.232 SPL 0.161913221 and v5 SR 0.232 SPL 0.164864495, collisions 0, **false_arrival 0**, agreement 103,
disagreement 21 in both. `pipeline.py` still 7211 lines.

**Final confirmation sweep, after the latch fix** (guard, `--label W4`, 29 files: the whole receipt/arrival/POI
surface plus `test_navigation`, `test_runtime`, `test_scene_assets`, `test_portal_world`, `test_person_aware_nav`
and every nav_instruct file) — **545 passed, 1 xpassed, 0 failed** (94.3 s, exit 0). `test_person_cell.py` is
deliberately not in that list: its one failure is pre-existing at clean `c96ac34` (proved in a throwaway clean
worktree) and is reported above rather than absorbed here.

**Hunk adjacency, re-checked after F4.** `runtime.py` hunks unchanged in position:
`@@ -172, -4014, -4031, -7091, -12589, -12679, -12789, -16025, -16546` — still only the terminal-receipt path
(`_step_navigation` / `start_navigation` / `_brain_runtime_state` / `_log_mission_terminal` /
`_narrate_mission_terminal`, plus the import). The dirty root's are at
`-38, -422, -2196, -2254, -2508, -2658, -2670, -2685, -3193, -3777, -3803, -3819, -3833, -4950, -5106, -5331,
-5356, -9428, -9545, -9574, -11481, -11855, -17968`. Nearest neighbours are `-3833` (ends ~3841) vs my `-4014`
and `-11855` (ends ~11861) vs my `-12589`. **0 overlap.** `brain/executive.py` still untouched; `pipeline.py`
untouched by F4 and still 7211 lines; `config.py` unchanged; 0 `noqa`; ruff clean on every file I touched.

---

# F5 · A direct witness for the latch

The F4 latch fix in `poi_admission.poi_region_arrival_admits` was proved only *indirectly* — by
`test_social_affect_action_defers_until_navigation_finishes` stopping hanging. That test reaches the rule through
a whole runtime, so it names the symptom, not the rule. Two rows added to `tests/test_poi_admission.py`, against a
three-field mission double (status / semantic_goal / metadata — no navigator, no sim, no scene):

| test | inputs | asserts |
|---|---|---|
| `test_an_arrived_mission_is_never_un_arrived_by_the_narrowing` | `status="arrived"`, committed region, `geometrically_arrived=False`, `inside_region=False` | **True** |
| `test_a_region_class_poi_outside_its_region_has_not_arrived` | `status="running"`, committed region, `geometrically_arrived=True`, `inside_region=False` | **False** (+ the same tick with `inside_region=True` ⇒ **True**) |

The first is deliberately the worst case: every input except the status argues against arrival, so a rule that
answers `False` there is not stricter — it is **stuck**, and the runtime waits for a stop the pipeline has decided
never to emit again. The second is the anti-vacuity twin: it is B32's pair 1 in one assertion (standing inside the
surveyed point's 1.5 m radius while outside the crosswalk polygon is not an arrival), and without it the latch row
would pass just as well against a rule that always says `True`.

**Seeded-red, measured rather than asserted.** Re-evaluating both rows against the PRE-F4 rule:

```
latch  (status=arrived, geom=False, inside=False)  expected=True   new=True   old=False  -> old REDDENS
twin   (status=running, geom=True,  inside=False)  expected=False  new=False  old=False  -> old passes
twin+  (status=running, geom=False, inside=True )  expected=True   new=True   old=True   -> old passes
```

So the latch row is a genuine witness (it fails on the code F4 replaced) and the twin is doing exactly the job it
is there for — pinning that the narrowing itself did not go away.

`~/.cache/parcel-guard/pytest_guard.sh --label W4 … pytest tests/test_poi_admission.py -q -p no:randomly`
→ **21 passed** (was 19), exit 0. Ruff: `All checks passed!`. **Test-only: `tests/test_poi_admission.py` is the
single file F5 touches, 505 → 592 lines (+87).** No product file, no other test, no artifact.

---

# F6 · The companion brain eval — the third second-author, on the merged tree

Worked in the merged gate worktree `/home/jaewoo-jang/.cache/parcel-0e/wb/gate` (the defect only appears there).
Did not touch `scripts/mutation_panel.py`, `scripts/ci_gate.py`, `evals/nav_instruct/*`, `tests/test_ci_gate.py`,
`tests/test_mutation_panel_freshness.py`, `tests/test_nav_instruct_*`, `tests/test_v4s_search_cells.py` (W5's) or
`research/20260829/nav-interrupt-1/` (T1's).

## Diagnosis — the refusal token

Instrumented `SemanticTaskRuntimeAdapter._result_for` (read-only spy) over `run_suite()`. Every NavigateTo
terminal poll in the three failing cases:

```
('task-sidewalk',              'arrived', enabled=False, 'failed', 'no_arrival_leg', receipt=None, leg=None)
('task-lamppost',              'arrived', enabled=False, 'failed', 'no_arrival_leg', receipt=None, leg=None)
('task-corrected-navigation',  'arrived', enabled=False, 'failed', 'no_arrival_leg', receipt=None, leg=None)
```

**The token is `no_arrival_leg` on all three** (both `arrival_receipt` and `arrival_leg` are `None`) — not
`outside_support_polygon`, not `stale`, not other-place. The negative control
`failed_navigation_verifier_no_fact` refuses on `target_lost` exactly as before, and the `verifying` frames are
`in_progress` on `settling` / `checkpoint`, so nothing else in the suite was reading the receipt gate at all.

**Root cause: the same second-author class F2 found in the NAV_INSTRUCT runner, on the brain eval path.**
`evals/companion/run_brain_v1.py::_runtime_state` built `SemanticRuntimeState` from a frozen controller frame of
**status strings only** — its whitelist has 14 fields and neither receipt nor leg is among them. The suite handed
the executive "the controller says `arrived`" and nothing that could back it. Under W4's rule ("a loop that cannot
produce a receipt has not proved an arrival") the executive refused, correctly. The eval's venue was the thing at
fault, not the product.

## Fix — the venue cuts the receipt through the product function

New `_SimulatedController` in `run_brain_v1.py`: the eval's VENUE, i.e. the loop that drives and therefore cuts
the receipt. It reports its **own** terminal observations into the product's `arrival_receipt(...)`, held against
the leg **it** issued, and the product decides. No venue-local "succeeded", no product change, no per-case
exception:

* `goal_id` / `sequence` — the directive it was told to drive, and its own leg counter, bumped on every `navigate`
  callback. The stale half stays live and is genuinely exercised: the correction case's superseded leg reports a
  terminal after its replacement is queued.
* `settled` — `navigation_enabled is False`, i.e. this controller stopped.
* `inside_region` — `True` only on a terminal state in `_ARRIVED_STATES`. **Not a status read dressed as
  geometry:** `mission.status` becomes `"arrived"` in the product ONLY through `_step_terminal_verification` (the
  region + settle branch) or the region-class arrival branch, so a controller reporting that state is reporting
  the outcome of its own region check — precisely the role `inside_region=` was added for when `headless_city`
  passes its settle-window verdict.

**The frozen artifacts do not move.** The frame stays the controller's report; the receipt and the leg are the
venue's, cut from that frame and never fields a case may declare. `_runtime_state`'s whitelist is unchanged,
`integration_cases.jsonl` and `manifest.json` are byte-untouched, and no expectation was re-labelled.

**Stated limit, in the code and here.** This venue is **non-geometric**: no pose, no polygon, so the receipt's
geometric halves (pose containment, `outside_support_polygon`) are **vacuous** in this suite and only its
claim / leg / settle halves are attested. The geometric halves are exercised over the same executive seam by
`run_embodied_plan_v1.py`, which drives a real `headless_city` venue. Recorded rather than papered over.

## The split the integrator asked for

| case | half | outcome |
|---|---|---|
| `sidewalk_inside_boundary` | **(i)** harness second-author defect | **fixed** — `succeeded` once the venue cuts a receipt |
| `lamppost_near_boundary` | **(i)** harness second-author defect | **fixed** |
| `correction_at_checkpoint_boundary` | **(i)** harness second-author defect | **fixed** |
| — | (ii) legitimately refused | **none** |

**No case is in half (ii), and none needed re-labelling.** All three refused on `no_arrival_leg` — the venue not
holding a leg at all — never on a band/support token, so none of them is the "eval is wrong about the contract"
case. Nothing was widened and no expectation moved.

## Proof

* `run_suite()` → **15/15 passed**, `failed_case_count: 0`, `matched_fail_closed_case_count: 7/7`.
* Both named tests through the guard (`--label W4F6`): **2 passed**, exit 0.
* Widened sweep (`test_companion_brain_eval`, `test_embodied_plan_eval`, `test_brain_runtime_adapter`,
  `test_arrival_receipt`, `test_arrival_receipt_wiring`, `test_poi_admission`): **75 passed**.
* **Machine metrics unchanged — measured, not asserted.** Dumped every per-case `metrics` and `actual` block plus
  the aggregate on the merged+F6 tree and on a throwaway **pristine `c96ac34`** worktree (which passes 15/15) and
  diffed them: **byte-identical**. The venue adds no report field, so there are no arrival-receipt fields in the
  report to differ either.
* Ruff `All checks passed!`; **0 `noqa`**.

```
git diff --stat -- evals/companion/run_brain_v1.py
 evals/companion/run_brain_v1.py | 111 ++++++++++++++++++++++++++++++++++++++--
 1 file changed, 106 insertions(+), 5 deletions(-)
```

**Eval-side only, one file.** `run_brain_v1.py` was unmodified in the merged tree before F6, so the whole
+106/−5 is this follow-up's. No product source touched.

---

# F7 · The leg's place is a COMMITMENT CHAIN, checked at the CURRENT commitment

Defect **F-T1-1**, found by T1's merged-tree NAV-INT-1 tier — **the first tier that actually ran F4**. My own F1
tier imported the modules before F4 landed at 08:19, which is why `arrival_receipt_for_another_place` appears
**0×** in my artifacts and **24×** in T1's. Worked in the merged gate worktree
`/home/jaewoo-jang/.cache/parcel-0e/wb/gate`; did not touch W5's files (`scripts/mutation_panel*.py`,
`scripts/ci_gate.py`, `evals/nav_instruct/*`, `tests/test_ci_gate.py`, `tests/test_mutation_panel_freshness.py`,
`tests/test_nav_instruct_*`, `tests/test_v4s_search_cells.py`) or T1's research outputs.

## The defect

F4 froze `leg.region_id` at the **first** committed region, reasoning that a mission re-committing mid-leg must
not narrate an arrival at the place it started out for. Perception's lock-on **legitimately refines the instance
inside one leg** — `lamp_post_2` at 4.2 s becomes `lamp_post_1` at 19.8 s, same directive, same generation. So 24
terminals that were claimed, inside, support-ok, settled, `arrived_verified`, with the harness's own
`committed_entity_id_raw == scored_entity_id` and the K0 scorer arriving on 23 of them, were refused
`arrival_receipt_for_another_place`. **Bar 2 fell 21/28 → 16/28 and disagreements read 7/85.**
Freezing the first commitment does not identify the leg's place; it identifies the leg's first **guess**.

## The fix, with the integrator's U32 tightening

`LegIdentity` carries `committed_region_ids: tuple[str, ...]` — every region **this generation** committed, in
order — and a derived `commitment_index` (`len(chain) - 1`, floored at 0), so "which place" and "how many times it
moved" cannot disagree. `ArrivalReceipt` carries the `commitment_index` **it was cut under**.

`is_for` / `receipt_refusal` require, in this order: same generation (else `stale_arrival_receipt`), the receipt's
region **in the chain** (else `arrival_receipt_for_another_place`), and the receipt's commitment index **equal to
the leg's** (else the new printable token **`arrival_receipt_superseded`**). Membership alone was too loose — it
would let a receipt cut for `lamp_post_2` at 4.2 s survive the refinement and still say "arrived" for a place the
leg no longer intends. The 24 legitimate terminals are cut **at the terminal, after the last refinement**, so they
pass; **expected bar 2 = 21/28 unchanged.**

`LegIdentity.committed(region_id)` returns a NEW leg with the id appended, idempotent when the id is already
current. The runtime's `_navigation_leg_identity` calls it on every tick from the **K0 seam's own mission
metadata**; a new directive or generation starts a fresh chain. `LegIdentity`'s third argument normalises a bare
`str` into a one-element chain — deliberate, because a bare string IS iterable and
`LegIdentity(d, n, "sidewalk")` against a raw tuple field would silently become a chain of eight characters.
`IDENTITY_REFUSALS` names the four identity tokens, so `is_for` is exactly "none of these" and a receipt honestly
reporting `outside_support_polygon` is still a receipt *for* this leg.

**Refinements are product-driven only.** The chain is extended in exactly one place — the runtime's K0 seam,
reading what perception's lock-on wrote. `LegIdentity` is frozen and `committed()` returns a new object, so a
consumer holding a leg cannot grow it. The eval runners never hold a leg at all: they pass their **answer key**,
which normalises to a one-element chain and carries no index, so no "refinement" can widen it.

## The six rows (`tests/test_arrival_receipt_wiring.py`, through every consumer)

| # | row | result |
|---|---|---|
| 1 | refine (`lamp_post_2` → `lamp_post_1`) then terminal | **arrived** — executive `succeeded`, log + whisperer arrival |
| 2 | receipt cut BEFORE the refinement, terminal after | refused **`arrival_receipt_superseded`** (in the chain, but behind) |
| 3 | receipt for a place this leg never committed (`bench_1`) | refused **`arrival_receipt_for_another_place`** |
| 4 | receipt from another generation | refused **`stale_arrival_receipt`** |
| 5 | B-09 through the eval runner's one-element answer-key chain | refused → **`wrong_instance`** |
| 6 | re-issue (new generation) | fresh empty chain, index 0; the previous walk's receipt is **stale** and cannot be inherited |

Plus `test_f7_refinements_are_product_driven_only`: `committed()` returns a new leg, the original is untouched,
the frozen field cannot be assigned, and a re-commit of the current place is not a refinement.

## Proof

* `tests/test_arrival_receipt_wiring.py` → **14 passed**.
* Required suites through the guard (`--label W4F7`): `test_arrival_receipt_wiring`, `test_arrival_receipt`,
  `test_nav_instruct_receipt_authority`, `test_k0_arrival_authority`, `test_brain_runtime_adapter`,
  `test_runtime`, `test_companion_brain_eval`, `test_embodied_plan_eval`, `test_poi_admission`,
  `test_arrival_settle` → **167 passed**, exit 0.
* **B-09 explicitly, through the eval runner after F7:** terminal `arrived/arrived_verified`,
  `system_arrival False`, trace label **`wrong_instance`**, authority `agreement`, failure `planning_error` —
  unchanged, so the matrix row cannot drift green by "refinement".
* v5 under the recipe of record (`scaled-path-v1`, max-steps 200, seed 20260804, `--no-ledger`) —
  **bit-identical to F2/F4**:

| | minival (25) | matrix (125) |
|---|---|---|
| SR | 0.24 | **0.232** |
| SPL | 0.185090694 | 0.164864495 |
| collisions | 0 | **0** |
| **false_arrival** | **0** | **0** |
| agreement / disagreement | 21 / 4 | 103 / 21 |
| `none` / `planning_error` | 6 / 3 | 29 / 14 |

* Ruff `All checks passed!` on every file F7 touched; **0 `noqa`**.

## Diff stat — F7 only

```
src/parcel_robot/instructnav/arrival_receipt.py  +135  -21
src/parcel_robot/runtime.py                       +27   -9
src/parcel_robot/simulation/headless_city.py      +21   -3
src/parcel_robot/brain/runtime_adapter.py          +5   -1
tests/test_arrival_receipt_wiring.py             +168   -0
```

(The gate worktree's own `git diff` is the whole merged wave; these are F7's own deltas — the four source files
measured against my `wb/w4` worktree, and `runtime.py` measured by reverting F7's four edits and diffing, because
`runtime.py` in the gate also carries W1/W2/W3's hunks.)

**Runtime hunk adjacency: F7 opens NO new region.** Its four edits are all inside the five regions W4 already
owns — `_navigation_leg_identity` / `_cut_navigation_receipt`, the `_step_navigation` terminal, and the two
consumers `_log_mission_terminal` / `_narrate_mission_terminal`. My hunk starts are unchanged from the W4 set
(`-172, -4014, -4031, -7091, -12589, -12679, -12789, -16025, -16546`), which do not overlap the owner's dirty
hunks (`-38, -422, -2196, -2254, -2508, -2658, -2670, -2685, -3193, -3777, -3803, -3819, -3833, -4950, -5106,
-5331, -5356, -9428, -9545, -9574, -11481, -11855, -17968`); nearest neighbours remain `-3833` (ends ~3841) vs
`-4014` and `-11855` (ends ~11861) vs `-12589`. `brain/executive.py` still untouched.

---

# F8 · runtime-maintained `LegIdentity` (executor)

Worked in the merged gate worktree `/home/jaewoo-jang/.cache/parcel-0e/wb/gate` (detached at `c96ac34` + the
whole wave-B stack). Pre-flight: `parcel_robot.__file__` →
`/home/jaewoo-jang/.cache/parcel-0e/wb/gate/src/parcel_robot/__init__.py`, Python 3.14.4, `TMPDIR` unset.
`runtime.py` edited only by targeted string replacement (card F-M2 is live in the same tree); F-M2's files
(`poi_admission.py`, `pipeline.py`, `test_poi_admission.py`, `test_plan_queue.py`,
`test_nav_instruct_matrix_freshness.py`, `.gitignore`) untouched, and `runtime.py`'s sha was verified unchanged
across each teeth window (see below), so nothing of F-M2's was clobbered.

## The defect, confirmed on the file before touching it

`self._navigation_leg` was assigned at exactly ONE site — the receipt cut, `:12981` — by
`_navigation_leg_identity(directive, sequence, metadata)`, i.e. the SAME three inputs `arrival_receipt(...)` was
cut from three lines later (`:12985-12998`, `commitment_index=self._navigation_leg.commitment_index`).
`self._navigation_receipt` was written only there too. The seven sites that set or clear
`self._navigation_directive` (`:3342, :7344, :7407, :7421, :7446, :7583, :13152`) touched neither. So at every
consumption leg and receipt agreed **by construction**, and the whole identity half of the contract —
`stale_arrival_receipt`, `arrival_receipt_for_another_place`, `arrival_receipt_superseded` — was unreachable on
the product path. `tests/test_arrival_receipt_wiring.py` never saw it because it seeds the leg by hand. Both
halves are now measured, not argued: see the teeth check.

## What changed (`src/parcel_robot/runtime.py`, before → after)

| # | site | before | after | change |
|---|---|---|---|---|
| 1 | `_stop_navigation_channel` (abandon) | `:3342` | `:3342-3347` | `_end_navigation_leg()` beside the directive clear |
| 2 | `_start_or_resume_navigation_locked` (resume) | `:7344` | `:7349-7357` | `_begin_navigation_leg(clean, nav generation)` |
| 3 | `_start_navigation_locked` (generation) | `:7369-7371` | `:7375-7381` | `nav_generation = self._generation.current("navigation")` read once |
| 4 | `_start_navigation_locked` (cold start) | `:7407` | `:7425-7432` | `_begin_navigation_leg(clean, nav_generation)` — the line that closes defect (b) |
| 5 | `_start_navigation_locked` ("already there") | `:7419-7440` | `:7444-7472` | observe → **cut** → clear (was clear → cut); the leg captured for the log |
| 6 | `_start_navigation_locked` (unreachable) | `:7446` | `:7479-7483` | `_end_navigation_leg()` |
| 7 | `_apply_channel_resume_bookkeeping` | `:7583` | `:7618-7628` | `_begin_navigation_leg(...)` |
| 8 | leg lifecycle (new) | — | `:12997`, `:13022`, `:13041` | `_begin_navigation_leg` / `_end_navigation_leg` / `_observe_navigation_leg` |
| 9 | `_cut_navigation_receipt` | `:12950-12999` | `:13077-13141` | READS the held leg, guards on `(directive, sequence)`, refuses + `logger.warning` when there is none, cuts under `leg.goal_id / leg.sequence / leg.commitment_index`; returns `ArrivalReceipt \| None` |
| 10 | `_navigation_leg_identity` | `:13001-13037` | **removed** | the "rebuild the leg from the cut's own inputs" helper is gone |
| 11 | `_step_navigation` (K0 seam) | — | `:13208` | `_observe_navigation_leg(directive, generation, mission.metadata)`, before the still-current gate |
| 12 | `_step_navigation` (terminal clear) | `:13152` | `:13235` | directive only — the leg and its receipt survive their OWN terminal (see deviation A) |

`runtime.py` 19042 → **19163** lines (+121 net; anchor `def _log_mission_terminal` `:16501` → `:16622`).
No new hunk region: every edit is inside the five regions W4 already owns (`_stop_navigation_channel`,
`_start_navigation_locked` / `_start_or_resume_navigation_locked` + the resume bookkeeping, the receipt
lifecycle, `_step_navigation`). `brain/executive.py`, `pipeline.py`, `config.py`, `poi_admission.py`,
`arrival_receipt.py` and every eval file: **untouched**. No safety-floor symbol touched. 0 `noqa` added
(`runtime.py` carries 69 at HEAD and 69 now — pre-existing `BLE001`).

## Deviations from the card's shape, and why (all measured)

**A. The two TERMINAL sites clear the directive only, not the leg + receipt.** The card says "at every site
that clears the directive, set both to None". Applied literally at `_step_navigation:13235` and the
"already there" branch, that destroys the terminal fact three lines after cutting it: the executive learns a
NavigateTo step succeeded through `_brain_runtime_state` → `runtime_adapter._result_for`, which runs AFTER the
directive is cleared and reads exactly that pair, and `_log_mission_terminal` / `_narrate_mission_terminal`
below the clear read it too. Nulling there fails every navigation step closed. So a leg that ends at its own
terminal keeps both, and they are retired by the next `_begin_navigation_leg` — which is where the defect
actually lived. The ABANDONMENT sites (channel stop, unreachable-at-start) do clear both, as asked.

**B. The chain extension moved OUT of the cut into `_observe_navigation_leg`.** Card item 2 puts the
`committed(...)` extension at the cut. But the cut runs on **every** `_step_navigation` tick, not only at
terminals, so leg and receipt would still move together every tick and `arrival_receipt_superseded` would stay
unreachable — row (ii) would have no teeth. The extension now happens in the mission step, from the navigator's
own `arrival_goal_region`, BEFORE the still-current gate: a commitment perception made is a fact even on a tick
the runtime then drops (latched stop, follow taking the body, a re-issue landing). It is still the ONE mutation
site, still product-driven only, and a leg that does not match `(directive, sequence)` is left alone.

**C. The leg's sequence is the NAVIGATION generation at both cut sites.** Before F8 `_start_navigation_locked`
cut with `self._behavior_generation` (the legacy aggregate that follow, search and spatial also bump) while
`_step_navigation` cut with `self._generation.current("navigation")` — two counters for one walk, invisible
while the leg was rebuilt at each cut from whichever counter that site happened to pass. One sequence now, and
the cut guards on it.

**D. A hand-seeded `_navigation_directive` gets no leg, so no receipt.** Eleven suites set the attribute
directly; those legs now narrate a failure at the terminal instead of an arrival, which is the fail-closed
direction and is pinned by row (iv). Measured across all of them: **370 passed, 0 failed** — none asserted an
arrival off a seeded directive.

## Rows — `tests/test_arrival_leg_runtime.py` (new, 471 lines, 4 rows, product path)

Driven through a real `RobotRuntime` (`start_navigation` → `_start_navigation_locked` → `_step_navigation`),
no simulator, **no seeded receipt and no seeded leg**; the navigator is the only double. Consumers read back
through `_brain_runtime_state` → the real `SemanticTaskRuntimeAdapter.poll`, and through
`_log_mission_terminal` (the call `_step_navigation`'s terminal branch makes).

| # | row | what it drives | verdict |
|---|---|---|---|
| iii | `test_the_current_legs_receipt_arrives_through_the_product` | one walk, one terminal | `reason == arrived_verified`, log "Arrived at the sidewalk.", adapter `succeeded` via `navigation_terminal_verifier` — **the positive twin, listed first because three rows below assert a refusal** |
| i | `test_a_new_directive_retires_the_previous_walks_receipt` | A arrives → owner asks for the bench → poll BEFORE B terminates | `state.arrival_receipt is None`, leg is B with an empty chain, `receipt_refusal == no_arrival_receipt`, adapter `failed` |
| ii | `test_a_receipt_cut_before_a_refinement_is_superseded` | commits `lamp_post_2`, cuts; next tick refines to `lamp_post_1` and is dropped by the e-stop latch | chain `("lamp_post_2", "lamp_post_1")`, held receipt still index 0 → `arrival_receipt_superseded` at the adapter AND at `_log_mission_terminal`; the identity verdict flips from PASS (`no_system_arrival_claim`, the receipt's own reason) to refused |
| iv | `test_a_cut_with_no_leg_refuses_and_logs` | directive installed behind the runtime's back, terminal tick with `status="arrived"` | no receipt, no leg, `logger.warning` naming the directive, terminal narrated as a failure |

Row (i) forces exactly two lane fields (`navigation_state`, `navigation_enabled`) and nothing else, because the
success-state STRING gate is what was covering the defect: with it in the way the adapter never reaches the
receipt, so the row asks whether the RECEIPT half refuses on its own. Rows (ii)/(iii) read the runtime's own
receipt and leg objects.

## Proof (every pytest through `~/.cache/parcel-guard/pytest_guard.sh`, `PARCEL_XDIST_WORKERS=2`, never `-n auto`)

* `--label w4f8-new` → `tests/test_arrival_leg_runtime.py` → **4 passed** in 0.97 s, exit 0.
* `--label w4f8-receipts` → `test_arrival_receipt_wiring`, `test_arrival_receipt`,
  `test_nav_instruct_receipt_authority`, `test_brain_runtime_adapter`, `test_k0_arrival_authority`,
  `test_arrival_settle` → **58 passed** in 42.16 s, exit 0.
* `--label w4f8-green` → `test_runtime`, `test_wave_b_integration`, `test_nav_instruct_digest_recipe`,
  `test_arrival_leg_runtime` → **81 passed** in 9.37 s, exit 0.
* `--label w4f8-seeded` → the eleven directive-seeding suites plus the venue/eval consumers
  (`test_mission_log`, `test_owner_estop`, `test_resume_transaction`, `test_preempt_runtime`,
  `test_k6_voice_lanes`, `test_yield_policy`, `test_roam1_behavior`, `test_pose_health_announcement`,
  `test_realtime_completion_tense`, `test_runtime_whisperer_wiring`, `test_realtime_speech_act_install`,
  `test_social_progress_runtime`, `test_embodied_plan_eval`, `test_companion_brain_eval`,
  `test_headless_city_tasks`) → **370 passed** in 37.72 s, exit 0.
* `--label w4f8-final` — MUST-STAY-GREEN, all in one run at the final `runtime.py`
  (`sha256 9d1bdd4c34519a75…`): `test_arrival_receipt_wiring`, `test_arrival_receipt`,
  `test_nav_instruct_receipt_authority`, `test_brain_runtime_adapter`, `test_k0_arrival_authority`,
  `test_arrival_settle`, `test_wave_b_integration`, `test_nav_instruct_digest_recipe`, `test_runtime`,
  `test_arrival_leg_runtime` → **139 passed, 0 failed** in 50.71 s, exit 0. (`test_runtime.py`'s
  `-k 'navigation or arrival or receipt'` slice is inside that full-file run.)

**Frozen v5 evidence untouched.** `evals/nav_instruct/runner.py:1194-1219` cuts its receipts by calling
`arrival_receipt(...)` directly with its own `_leg_sequence` and the answer key, and checks with
`region_id=episode.target_entity_id` and **no** `commitment_index` — it never holds a `LegIdentity` and never
enters `RobotRuntime`. F8 edits `runtime.py` only, so `RECEIPT_ARRIVAL_FAMILIES`' cut cannot move.
`tests/test_nav_instruct_digest_recipe.py` green in two of the runs above as the evidence row; no eval file,
artifact or pinned number touched.

## Teeth — the leg maintenance reverted, then restored byte-identically

`scratchpad/f8_teeth.py revert` neuters the three maintenance seams and puts the pre-F8 shape back in the cut
(`leg = LegIdentity(directive, sequence, region)` when the held leg does not match, else `leg.committed(region)`
— the file's own `_navigation_leg_identity` logic, inline). Ruff clean in that state too, so the revert is a
behaviour change and not a syntax accident.

```
FIXED sha: 9d1bdd4c34519a75      REVERTED sha: 74244f003d009c70
tests/test_arrival_leg_runtime.py:311  AssertionError: assert ArrivalReceipt(goal_id='go to the sidewalk',
    sequence=1, region_id='sidewalk', ..., reason='arrived_verified', commitment_index=0) is None
tests/test_arrival_leg_runtime.py:400  AssertionError: assert ('lamp_post_2',) == ('lamp_post_2', 'lamp_post_1')
tests/test_arrival_leg_runtime.py:465  AssertionError: assert ArrivalReceipt(goal_id='go to the sidewalk',
    sequence=0, region_id='sidewalk', ..., reason='arrived_verified', commitment_index=0) is None
FAILED test_a_new_directive_retires_the_previous_walks_receipt        (i)
FAILED test_a_receipt_cut_before_a_refinement_is_superseded           (ii)
FAILED test_a_cut_with_no_leg_refuses_and_logs                        (iv)
3 failed, 1 passed
pre-restore sha: 74244f003d009c70   RESTORED sha: 9d1bdd4c34519a75
```

With the fix: **4 passed**. Reverted: **(i) and (ii) both fail** — (i) with leg A's `arrived_verified` receipt
still standing while the owner's new walk is under way (the defect, printed), (ii) because the refinement was
invisible to the leg, so the chain never grew past its first guess and no receipt could ever be superseded.
(iv) reddens too (the cut fabricates a leg for a walk the runtime never owned). **(iii), the positive twin,
passes in BOTH states** — so the fix is not "always refuse". The pre-restore sha equals the reverted sha in both
windows, so no concurrent editor's work was overwritten, and the restored file is byte-identical to the tested
one.

## Finding for the integrator (not fixed here)

`arrival_receipt_superseded` is reachable only where the leg can advance **without** a cut, because
`_cut_navigation_receipt` runs on every `_step_navigation` tick rather than only at terminals. The window row
(ii) uses is a tick the runtime DROPS after the navigator committed (e-stop latch, follow taking the body, a
concurrent re-issue). A consequence worth stating plainly: a receipt whose reason is `arrived_verified` can
never be superseded on the product path, because `settled=True` is only ever passed on the terminal branch and
that branch ends the leg. Making an ARRIVED receipt supersedable would mean cutting the receipt only at
terminals — a larger change than F8, with `_brain_runtime_state` reporting `None` mid-mission — and is left for
a decision rather than taken here.

## Housekeeping

* `.parcel/bin/ruff check src/parcel_robot/runtime.py tests/test_arrival_leg_runtime.py` → `All checks passed!`;
  0 `noqa` in either file's new lines.
* `git status --porcelain`: ` M src/parcel_robot/runtime.py`, `?? tests/test_arrival_leg_runtime.py`.
* `git diff --stat -- src/parcel_robot/runtime.py`: `887 insertions(+), 27 deletions(-)` — that is the WHOLE
  merged wave (W1 + W2 + W3 + W4/F4/F5/F7 + F8) in the gate tree, as F7 recorded for the same reason; F8's own
  delta is the site table above (+121 net lines).
* Not done: no CI gate, no mutation panel, no eval runner, no simulator, no git write, no `-n auto`.
