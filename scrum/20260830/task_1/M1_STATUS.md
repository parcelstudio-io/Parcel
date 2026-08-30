# M1 · MERGE — W1 + W4 onto the W2/W3 gate worktree (Opus integrator-executor)

**Card:** M1 (wave B merge) · **Worktree:** `/home/jaewoo-jang/.cache/parcel-0e/wb/gate`
(`git worktree`, detached at HEAD `c96ac345358ec2786748fc3a885c35d32710c5e2`).
**Spend:** $0.00 hosted, no network. **No `ci_gate.py --tier`. No `-n auto`. No `--pdb`. 0 `noqa`.**
Every pytest through `~/.cache/parcel-guard/pytest_guard.sh --label M1*`.

| pre-flight fact | value |
|---|---|
| `parcel_robot.__file__` | `/home/jaewoo-jang/.cache/parcel-0e/wb/gate/src/parcel_robot/__init__.py` — the GATE worktree, verified before the first edit and again after each pass |
| env, every shell | `PYTHONPATH=$PWD/src:$PWD`, `MUJOCO_GL=egl`, `OPENBLAS_NUM_THREADS=32`, `TMPDIR` unset |
| main repo | never edited except **this file** |
| the other executors' worktrees | READ only |
| W5 | **not applied** — the integrator layers it on this tree next |

**Two passes, by the integrator's instruction.** Pass A merged the 08:15 snapshots (`w1.patch`,
`w4.patch`) and produced the conflict analysis. Pass B — the deliverable — reset the worktree to
HEAD, rebuilt **HEAD + W2 + W3**, and merged the FINAL patches:

| input | sha256 | contents |
|---|---|---|
| `~/.cache/parcel-0e/wb/w2.patch` | (as given) | 11 tracked files + `tests/test_realtime_speech_act_install.py` |
| `~/.cache/parcel-0e/wb/w3.patch` | (as given) | 16 tracked files + `src/parcel_robot/navigation/world_identity.py` |
| `~/.cache/parcel-0e/wb/w1-out/W1.patch` (**W1 final, incl. F1**) | `8fe1a7a4bad6010239cf945e15c4585f53e97e7b11752d2c38e1fd23ad732f6b` | 4 modified + 2 new files as `diff --git` entries |
| `~/.cache/parcel-0e/wb/w4.final.patch` (**W4 final, incl. F4 + F5**) | `dd90da08960ece3f16894cffae85eca6e9e6dcc886f6297dd50e996a031be997` | 21 tracked files (F5 added `tests/test_poi_admission.py`) |
| `~/.cache/parcel-0e/wb/w4.newfiles.txt` | — | 32 new files, copied from `~/.cache/parcel-0e/wb/w4` |

W6's `research/20260830/value-changes-1/` was restored from the main repo after the reset.

**Method.** Each card was merged with `git merge-file` three-way (base = the HEAD blob, *ours* = the
gate tree as built so far, *theirs* = HEAD + that card's patch, rebuilt in a scratch tree so a
follow-up landing in the executor's own worktree could never leak into the merge). **The index was
never touched** — no `git add`, no `--3way`, no commit.

---

## 1 · Conflict table — every resolution, and why

Nine decisions. Three carried `<<<<<<<` markers in pass B (plus a fourth once W4-F5 landed); the
rest merged textually and were then checked for SEMANTIC survival by the added-line audit in §2.

| # | file : line | what OURS (W2/W3) wanted | what THEIRS (W1/W4) wanted | resolution | why |
|---|---|---|---|---|---|
| **C1** | `src/parcel_robot/runtime.py` : `_accept_plan` (HEAD ~3536/3546/3563) | **W2**: `plan_lineage = LINEAGE_REVISE` at the `replace()` branch, `= LINEAGE_NEW` at the `submit()` branch, handed to `self._whisper_plan_accepted(…, lineage=plan_lineage)` | **W1**: `self._bind_plan_lineage(plan)` one line after the `submission.accepted` raise, which consumes `_pending_plan_action` and records the queue policy's `new｜revise｜queue` | **SEMANTIC conflict; `merge-file` reported none — both sides landed and W1's answer went nowhere.** `_bind_plan_lineage` now **returns** `str｜None` (the steered lineage, `None` when unsteered) and `_accept_plan` reads `steered_lineage = self._bind_plan_lineage(plan)` / `if steered_lineage in WHISPER_PLAN_LINEAGES: plan_lineage = steered_lineage`. W2's door answer is the **fallback**; W1's queue answer **wins when there is one**. | Exactly the composition both STATUS files describe. W2_STATUS §1: "W1's queue is what turns those into their own `queue`-lineage receipts"; W2's F1(1) forbids guessing the lineage — it must come from the call site. The DOOR physically cannot see `queue`: a queued child is admitted through `submit()` like any fresh goal, so without this the owner is told a parked "after that…" turn is a brand-new mission. The vocabularies are the same strings by construction (`plan_queue.PLAN_LINEAGES` ⊇ `whisperer.PLAN_LINEAGES`), so the composition needs **no translation table** that could drift. `keep` never reaches here (a keep publishes no plan), which is why the membership test is the whisperer's frozenset and not the queue's tuple. **Proved by `tests/test_wave_b_integration.py`.** |
| **C1b** | `src/parcel_robot/runtime.py` : import block (~435) | — | — | added `from parcel_robot.realtime.whisperer import PLAN_LINEAGES as WHISPER_PLAN_LINEAGES` | `brain.plan_queue` exports a same-named `PLAN_LINEAGES` that also carries `keep`. Two different sets, one name: aliased at the import rather than letting the later import silently win. |
| **C2** | `src/parcel_robot/navigation/pipeline.py` : ~1169 (HEAD ~1156) | **W3**: `metadata=poi_metadata` — `ground_admitted_poi` now returns `(goal, metadata)`, the metadata carrying `identity_source` (on whose word the POI was admitted) | **W4**: `metadata=poi_goal_metadata(self.grounder, goal)` — the region-class POI's committed `arrival_goal_region` + `terminal_relation: inside` | `metadata={**poi_metadata, **poi_goal_metadata(self.grounder, goal)}` | Two different FACTS about one goal (attribution vs arrival authority) and the mission needs both. The union is **exact, not a precedence choice**: the only key both write is `goal_source`, and both write `"known_poi"`. Verified live — `parse("navigate to the crosswalk")` yields `identity_source=explicit` AND `goal_region_source=region_class_poi` on one mission — and by `tests/test_poi_admission.py` (27 rows, both cards'). |
| **C3** | `src/parcel_robot/navigation/poi_admission.py` : 507-648 (HEAD ~411) | **W3**: `poi_lookup_metadata(grounder, error, world_identity=None)` — a widened signature | **W4**: five new members inserted at the same anchor (`TERMINAL_RELATION_KEY`, `region_instance_for_poi`, `poi_goal_metadata`, `poi_terminal_relation`, `poi_region_arrival_admits`) followed by the OLD 2-arg `poi_lookup_metadata` | keep **all** of W4's insertions, then W3's widened signature | A pure insertion-vs-signature collision: W4 added members ABOVE the function W3 widened, and `merge-file` could not see that the tail of *theirs* was the unmodified original. No hunk dropped; the only product caller (`pipeline.py`) and every test call site agree with W3's arity. |
| **C4** | `src/parcel_robot/perception/city_semantics.py` : 24-39 (HEAD ~21) | **W3**: `from …poi_admission import publish_scene_semantics` + `from …navigation.world_identity import WorldIdentity` — W3 **moved** `scene_id_from_model` out of `poi_admission` into the new `world_identity` module and replaced this module's only call with `world_identity_of` | **W4**: `from …instructnav.scoring import (TERMINAL_SUPPORT_CLEARANCE_M, object_near_envelope_m, object_near_goal_region, support_surface_for)` + `from …poi_admission import (publish_scene_semantics, scene_id_from_model)` | the union of the two, **minus** `scene_id_from_model` | The naive union does not import: after W3 that name no longer lives in `poi_admission`. Dropping it is right rather than re-exporting it — W3's whole card is "one home for the world's identity", and W4's only use of it was the publication line W3 replaced. Caught by an import smoke check, not by any test. |
| **C5** | `src/parcel_robot/perception/city_semantics.py` : `extract_city_semantics` | W3 +16 lines (the identity publication + `world_identity_of`) | W4 +5 net (the shared `support_surface_for` rule, the band × support intersection, `TERMINAL_SUPPORT_CLEARANCE_M`) | extracted the object loop body into a new module-private `_object_track(instance_id, parts, regions)`; body moved **verbatim**, the loop is the list comprehension it always was | **A merge-CREATED ratchet red.** The function is 97 lines at HEAD, **102 with W4 alone**, **103 merged** — over DEC-0's 100-line ceiling, reddening `test_dec0_debt_ratchet::test_no_new_long_function`. No `noqa` and no baseline edit are permitted, so the bulk was split: `extract_city_semantics` **65**, `_object_track` **53**. The ratchet keys on leaf names, so a new name under the ceiling is clean. |
| **C6** | `src/parcel_robot/simulation/headless_city.py` : ~1071 | W3 threads `world_identity` (world → harness → navigator) and adds `HeadlessTaskResult.identity_source` | W4 adds the settle/receipt fields, `arrival_receipt(...)` as the single terminal authority, and (F4) the `LegIdentity` plumbing | textual merge clean; **verified by hand** that both survive in `_result(...)` — `identity_source = metadata.get("identity_source")` sits beside `receipt = arrival_receipt(...)` / `arrived_verified = receipt.arrived` | The card flagged this as a likely conflict; the two touched adjacent but disjoint lines of one method. Confirmed by §2's audit, not by eye. |
| **C7** | `src/parcel_robot/runtime.py` (W4's terminal-receipt + F4 `LegIdentity` hunks) | W1's `_accept_plan` / `_apply_goal_amend` / `_step_brain` hunks; W2's whisperer hunks | W4's `_cut_navigation_receipt`, `_log_mission_terminal(receipt=, leg=)`, `_narrate_mission_terminal(receipt=, leg=)` | textual merge clean; no hand edit | Disjoint regions of one very large file (W1 3500-5200, W2 350-600 + 16400-17700, W4 172 / 4014 / 7091 / 12589-12860 / 16025 / 16546). Confirmed by §2. |
| **C8** | `tests/test_poi_admission.py` : end of file (W4-F5) | W3 **appended** six world-identity rows | W4-F5 **appended** two arrival-latch rows | keep BOTH appended blocks, W3's first, each under its own section banner | Two cards appending at one anchor. 27 rows collected, and the file carries W3's fixtures (`world_identity=demo_scene_loaded`, `IDENTITY_EXPLICIT`) AND W4's `test_an_arrived_mission_is_never_un_arrived_by_the_narrowing` / `test_a_region_class_poi_outside_its_region_has_not_arrived`. |
| **C9** | `tests/test_runtime_whisperer_wiring.py` (4 sites) · `tests/test_realtime_speech_act_install.py` (1 site) | W2's tests call `runtime._narrate_mission_terminal(state="arrived", …)` and assert the ARRIVAL sentence | W4 + F4 make that door read the **receipt and the leg identity** and nothing else — "no receipt, no arrival sentence" | every `state="arrived"` call now hands over a real `arrival_receipt(...)` and its `LegIdentity`, through one commented helper `_arrived(goal)` | **Consequence of W4's contract, invisible to W4**: it never ran `test_runtime_whisperer_wiring.py`, and `test_realtime_speech_act_install.py` is W2's brand-new file that did not exist in W4's tree at all. Two of the five sites were red; three passed while silently exercising the FAILURE branch, so all five were corrected. **W4's authority is not weakened** — the alternative (falling back to `state in MISSION_ARRIVED_STATES` when the receipt is `None`) would have deleted B32. |

**Nothing was dropped to make a patch apply.** §2 accounts for every `+` line of all four patches.

### Two conflicts pass A found that W4's own follow-ups then removed

Recorded because they were real and the fix is now W4's, not the merge's:

* **`test_runtime.py::test_social_affect_action_defers_until_navigation_finishes`** teleported to
  `(3.5, -0.6)` — the crosswalk's surveyed POI **coordinate**, which is 0.2 m OUTSIDE the scene's
  committed polygon (`x∈[2.35, 3.85], y∈[-0.40, 2.00]`) — and expected arrival. Pass A had to move
  the pose. **W4-F5 fixed it at the source instead**, by restoring the latch inside
  `poi_region_arrival_admits` (`status == "arrived"` short-circuits, so a narrowing of the DECISION
  can never un-arrive a leg). Pass B carries W4's fix and no test edit.
* `_narrate_mission_terminal` gained a second required input between the passes (`leg`), which is
  why C9's helper builds a `LegIdentity` as well as a receipt.

---

## 2 · Every patch-added line accounted for (pass B)

Each `+` line of each final patch was checked for presence in the merged tree.

| patch | added lines | missing | which, and why |
|---|---|---|---|
| **W1 final** | 2207 | **3** | `# C6 PLAN-QUEUE-1: bind the accepted plan…`, `self._bind_plan_lineage(plan)`, `def _bind_plan_lineage(self, plan: PlanIR) -> None:` — **superseded by C1**, which keeps the call and the definition and makes them return the lineage |
| **W2** | 939 | **0** | |
| **W3** | 467 | **1** | `metadata=poi_metadata,` — **superseded by C2**'s union |
| **W4 final** | 1269 | **1 + 3 reflowed** | `metadata=poi_goal_metadata(self.grounder, goal),` — **superseded by C2**; and 3 comment lines inside `city_semantics` that C5 re-wrapped when moving them to a shallower indent (same words, different line breaks — every code line survives byte-for-byte ignoring indent) |

---

## 3 · Proof — **merge + F (final)**

All through the guard, from the gate worktree, one build, **no `-n auto`**:

```
pytest_guard.sh --label M1-final2 … 26 files -q -p no:cacheprovider
→ 671 passed, 1 xpassed, 0 failed in 121.13s
```

| suite | rows | result | note |
|---|---|---|---|
| `tests/test_plan_queue.py` | **74** | GREEN | W1 (71 pre-F1, +3 from F1) |
| `tests/test_brain_executive.py` | 11 | GREEN | stands in for the card's `tests/test_executive*.py`, which is **0 files at HEAD** (§4) |
| `tests/test_realtime_speech_act_install.py` | **28** | GREEN | W2, incl. the MB-1 corpus product-path row (b1 **75/75**) |
| `tests/test_runtime_whisperer_wiring.py` | 15 | GREEN | C9 applied |
| `tests/test_turn1_endpointing.py` | 73 | GREEN | |
| `tests/test_realtime_lane.py` | 66 | GREEN | the card's `test_realtime_lane*.py` — one file exists |
| `tests/test_whisperer_plan_accepted.py` | 29 | GREEN | |
| `tests/test_poi_admission.py` | **27** | GREEN | W3's 25 + W4-F5's 2 (C8) |
| `tests/test_c3_cutover.py` | 54 | GREEN | |
| `tests/test_navigation.py` | 38 | GREEN | |
| `tests/test_person_aware_nav.py` | 19 | GREEN | |
| `tests/test_runtime.py` | 61 | GREEN | incl. the two social-affect rows W4-F5's latch restored |
| `tests/test_arrival_receipt.py` | 10 | GREEN | W4 |
| `tests/test_arrival_receipt_wiring.py` | 7 | GREEN | W4-F4 |
| `tests/test_nav_instruct_receipt_authority.py` | 4 | GREEN | |
| `tests/test_k0_arrival_authority.py` | 9 | GREEN | |
| `tests/test_authority_half_scale_smoke.py` | 5 | GREEN | |
| `tests/test_embodied_plan_eval.py` | 10 | GREEN | |
| `tests/test_arrival_settle.py` | 11 | GREEN | |
| `tests/test_nav_instruct_digest_recipe.py` | 7 | GREEN | |
| `tests/test_brain_runtime_adapter.py` | 10 | GREEN | W4-F4's consumer |
| `tests/test_scene_surface_truth.py` | 52 | GREEN | |
| `tests/test_v4s_search_cells.py` | 28 | GREEN | |
| **`tests/test_wave_b_integration.py`** | **1** | **GREEN** | the merged-tree statement — §6 |
| `tests/test_dec0_debt_ratchet.py` | 8 | GREEN | **incl. `test_no_new_long_function`**, which C5 exists for |
| `tests/test_decig2_import_ratchet.py` | 15 | GREEN | |
| **total** | **672** | **671 passed, 1 xpassed, 0 failed** | |

**The one expected red, run separately and attributed:**

```
… + tests/test_ci_gate.py  →  1 failed, 762 passed, 1 xpassed in 142.30s
FAILED tests/test_ci_gate.py::test_real_frozen_sentinels_match_the_current_tree
tests/test_ci_gate.py:327: AssertionError: four immutable manifests are pinned
```

The sentinels themselves PASS and W4's v5 manifest sentinel is byte-correct; only the E8-idiom
**count literal** at `tests/test_ci_gate.py:327` is stale (`checked == 4`, reads **5**). Per the
integrator, **W5 owns the bump 4 → 6** on this worktree (v5 manifest + matrix artifact sentinels)
with the dated comment in the existing idiom. **Not fixed here.**
`tests/test_person_cell.py::…undeclared_bystander` is the wave's known pre-existing red, not in
this list and not touched.

### Proof — merge (pre-F), for the record

Pass A, against the 08:15 snapshots, same 22-file list: **566 passed, 1 xpassed, 3 failed** —
`test_runtime::test_social_affect_action_defers_until_navigation_finishes` ×2 (W4's D-15 narrowing,
fixed at the source by W4-F5) and the pass-A integration test (a fixture-collision bug of its own,
§6). The two arrival-narration reds and the DEC-0 long-function red that pass A first surfaced were
resolved by C9 and C5 and are green in both passes' final state.

---

## 4 · Test instruments: what the card names vs what exists at HEAD

* `tests/test_executive*.py` — **0 files at HEAD**; it is an artifact of the owner's uncommitted
  28-file diff (W1_STATUS records the same finding). `tests/test_brain_executive.py` was run in its
  place.
* `tests/test_realtime_lane*.py` — one file, `tests/test_realtime_lane.py`.
* Every other suite in the proof list exists and was run.

---

## 5 · Hygiene

| check | result |
|---|---|
| `ruff check` over **all 55** changed/new `.py` files | **All checks passed!** |
| `noqa` added by the diff | **0** |
| `wc -l src/parcel_robot/config.py` | **1000** — untouched, absent from the diff |
| `wc -l src/parcel_robot/navigation/pipeline.py` | **7221** (HEAD 7211; +10, all comment: C2's resolution note) |
| `wc -l src/parcel_robot/runtime.py` | 19027 |
| `wc -l src/parcel_robot/perception/city_semantics.py` | 382 |
| `wc -l src/parcel_robot/navigation/poi_admission.py` | 730 |
| `wc -l src/parcel_robot/simulation/headless_city.py` | 1355 |
| `wc -l tests/test_plan_queue.py` | 955 |
| hosted calls / network | none, **$0.00** |
| `ci_gate.py --tier` | never run |
| git writes | none — no `add`, no `commit`, no index change. `git checkout -- . && git clean -fd` once, on the integrator's explicit instruction, to start pass B |

---

## 6 · The merged-tree integration test

`tests/test_wave_b_integration.py`, **one test**:
`test_a_queue_steering_decision_reaches_the_whisperer_as_lineage_queue`. It exists because
**neither worktree contains both sides**: W1 proved the lineage with no whisperer, and W2 proved the
hook with a *fake* lineage at its own parameter (W2_STATUS §9: "no W1 symbol is imported or
depended on"). Four statements, in the order the runtime makes them:

1. an unsteered "go to the sidewalk" keeps the DOOR's lineage — the `plan_accepted` row's `text`
   opens with `PLAN_ACCEPTED_FACTS[LINEAGE_NEW]`, and C5 voices "Okay, I'll head to sidewalk.";
2. "after that, go to the bench" produces **exactly one** further `plan_accepted` receipt, it is
   `forwarded`, its `text` opens with `PLAN_ACCEPTED_FACTS[LINEAGE_QUEUE]` (and explicitly **not**
   the `new` rendering), the queue record's lineage is `queue`, and C5's contract voices
   **"Okay, I'll check bench after that."** — the merge assertion;
3. the queued child going terminal puts `resume_offer` and `plan_resumed` on the PARENT's record
   and produces **no third** acknowledgement (a resume publishes no plan);
4. a `keep` decision replies "I'll keep going with what I'm doing" and fires **nothing** at the hook.

Both cards' own fixtures are imported rather than re-expressed (`runtime` from
`test_closed_intent_product_path`, `_wire` from `test_realtime_speech_act_install`), for the reason
W1's suite gives for importing the first: a second copy is a second opinion about what "the product
path" means.

**Two fixture collisions the test had to name** (each written at the line, both discovered by
running it and neither a product defect):

* `_wire` replaces `runtime._observation` wholesale with one stamped from W2's **fake** clock
  (t = 5000). W1's half then admits plans through the real brain, whose snapshot reads sensor age
  against `time.monotonic()` — so every plan was refused with "I couldn't admit that command as a
  safe plan yet". The helper `_install` keeps W1's observation (the one the brain reads) and takes
  only the semantic objects from W2's, which is the single thing `_wire` puts there for
  `_realtime_places()`. `_pump` re-stamps the timestamp on every brain tick.
* An acknowledgement is priced with its own `PLAN_ACCEPTED_MIN_GAP_S = 2.0`, so back-to-back turns
  suppress the second as `min_gap` and prove nothing about the lineage. The test advances the
  whisperer's clock between the two owner turns — two turns a few seconds apart is the case under
  test.

---

## 7 · One process fault, recorded

During pass A a measurement script contained `subprocess.run(["git", "stash"])` behind a comment
calling it a no-op. **It was not**: it stashed the whole merged working tree. Caught within one
command (`git stash list` showed `stash@{0}`), restored with `git stash pop`, the stash dropped, and
every resolution re-verified afterwards. Untracked files were never at risk, and the tree that pass
B produced is built from the patches rather than from that state, so nothing of it survives into the
deliverable. No other unintended git write occurred in any worktree.

---

## 8 · `git -C <gate> diff --stat`

```
 evals/companion/run_embodied_plan_v1.py        |   9 +
 evals/companion_nav/runner.py                  |   4 +-
 evals/nav_instruct/README.md                   |  52 +-
 evals/nav_instruct/generator.py                |  79 +++
 evals/nav_instruct/person_cell.py              |   4 +-
 evals/nav_instruct/runner.py                   | 127 +++-
 evals/nav_instruct/surface_scoring.py          |   2 +-
 research/20260829/nav-gen-attribution-1/run.py |   5 +
 research/20260829/nav-interrupt-1/harness.py   |  32 +
 research/20260829/nav-interrupt-1/run.py       |  77 ++-
 scripts/ci_gate.py                             |  24 +
 src/parcel_robot/brain/executive.py            |  36 ++
 src/parcel_robot/brain/runtime_adapter.py      |  45 ++
 src/parcel_robot/instructnav/scoring.py        | 227 +++++++-
 src/parcel_robot/navigation/pipeline.py        |  64 +-
 src/parcel_robot/navigation/poi_admission.py   | 307 +++++++++-
 src/parcel_robot/perception/city_semantics.py  | 152 +++--
 src/parcel_robot/realtime/config.py            |  20 +-
 src/parcel_robot/realtime/lane.py              | 223 ++++++-
 src/parcel_robot/realtime/narration_matcher.py |   9 +
 src/parcel_robot/realtime/speech_acts.py       | 102 ++++
 src/parcel_robot/realtime/whisperer.py         | 230 ++++++++
 src/parcel_robot/runtime.py                    | 778 ++++++++++++++++++++++++-
 src/parcel_robot/simulation/headless_city.py   | 110 +++-
 src/parcel_robot/skills/api.py                 |  21 +-
 src/parcel_robot/voice/agent.py                |  74 ++-
 src/parcel_robot/voice/amendment.py            |  38 +-
 src/parcel_robot/web_panel.py                  |   9 +
 tests/test_arrival_settle.py                   |  31 +-
 tests/test_brain_runtime_adapter.py            |  47 +-
 tests/test_c3_cutover.py                       |  16 +-
 tests/test_k0_arrival_authority.py             |  87 ++-
 tests/test_nav_instruct_digest_recipe.py       |  29 +
 tests/test_navigation.py                       |  10 +-
 tests/test_person_aware_nav.py                 |  40 +-
 tests/test_poi_admission.py                    | 265 ++++++++-
 tests/test_realtime_spend_budget.py            |  19 +-
 tests/test_runtime.py                          |  20 +-
 tests/test_runtime_whisperer_wiring.py         | 111 +++-
 tests/test_scene_surface_truth.py              |  19 +
 tests/test_speech_acts.py                      |  14 +-
 tests/test_turn1_endpointing.py                |  21 +-
 tests/test_v4s_search_cells.py                 |  20 +-
 43 files changed, 3326 insertions(+), 283 deletions(-)
```

### Untracked new files in the gate worktree (44; `git diff` shows none of them)

| card | files |
|---|---|
| **W1** | `src/parcel_robot/brain/plan_queue.py`, `tests/test_plan_queue.py` |
| **W2** | `tests/test_realtime_speech_act_install.py` |
| **W3** | `src/parcel_robot/navigation/world_identity.py` |
| **W4** | `src/parcel_robot/instructnav/arrival_receipt.py`, `tests/test_arrival_receipt.py`, `tests/test_arrival_receipt_wiring.py`, `tests/test_nav_instruct_receipt_authority.py`, `evals/nav_instruct/bridge_v4_v5.py`, `evals/nav_instruct/results/bridge_v4_v5.json`, `evals/nav_instruct/episodes/v5/manifest.json` + **25** `evals/nav_instruct/episodes/v5/nav-*.json` |
| **W6** | `research/20260830/value-changes-1/` (7 files) |
| **M1** | `tests/test_wave_b_integration.py` |

(`.parcel` is the venv symlink and is not a deliverable.)

**W5 is not applied.** The tree is ready for it, and `tests/test_ci_gate.py:327` is the row it owns.
