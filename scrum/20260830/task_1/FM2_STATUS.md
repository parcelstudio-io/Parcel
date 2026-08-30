# F-M2 — the candidate review's three confirmed findings, fixed in the gate worktree

**Executor:** Opus (parcel F-M2) · **Verifier:** parcel-0e (Fable) · **Integrator:** parcel-fb
**Tree:** `~/.cache/parcel-0e/wb/gate` (detached at HEAD `c96ac34` + the wave-B stack, edited in place)
**Pre-flight:** `parcel_robot.__file__` = `/home/jaewoo-jang/.cache/parcel-0e/wb/gate/src/parcel_robot/__init__.py`
(`PYTHONPATH=<gate>/src:<gate>`, `MUJOCO_GL=egl`, `TMPDIR` / `PARCEL_MEMORY_*` unset, python `.parcel/bin/python`).
Every pytest below ran through `~/.cache/parcel-guard/pytest_guard.sh --label fm2-*`, serial (no `-n`).
No git write of any kind; no `ci_gate.py`, no mutation panel script, no eval runner, no simulator.

**Coordination:** a second executor (W4-F8) was editing `runtime.py`, `brain/runtime_adapter.py` and
`tests/test_arrival_leg_runtime.py` in the same tree throughout. I edited none of those files: my only
touch of `runtime.py` was the item-2 teeth check (one line commented and restored inside a single
command — `git hash-object` identical before and after, evidence below).

---

## ITEM 1 [HIGH] — two-worlds arrival region: a foreign polygon can no longer be the arrival authority

### What changed

| file:line | change |
|---|---|
| `src/parcel_robot/navigation/poi_admission.py:517` | new `GOAL_REGION_REFUSED_KEY = "goal_region_refused"` — the token a mission carries when a publication was refused as foreign (same shape as `poi_refused`) |
| `src/parcel_robot/navigation/poi_admission.py:520-563` | new `scene_for_identity(scene, world_identity) -> (SceneInstanceSet \| None, str)`. Resolves the identity through the EXISTING seam (`resolve_world_identity`, W3's own rule: explicit → published → none) and returns the publication only when it IS that world: `source != IDENTITY_EXPLICIT or identity.matches(scene.scene_id)`. Otherwise `(None, f"{OUTCOME_SCENE_MISMATCH}:{identity.scene_id}/{scene.scene_id}")` |
| `src/parcel_robot/navigation/poi_admission.py:600-637` | `poi_goal_metadata(grounder, goal, world_identity=None)` — third parameter (defaulted, so no caller breaks); the region instance is now selected from `scene_for_identity(active_scene_instances(), world_identity)` instead of `active_scene_instances()`, and a refusal writes `GOAL_REGION_REFUSED_KEY` instead of committing a polygon |
| `src/parcel_robot/navigation/pipeline.py:1183` | the product composition passes the navigator's own identity: `**poi_goal_metadata(self.grounder, goal, self.world_identity)` (the same value `ground_admitted_poi` is already given on line 1164). +3 comment lines at 1176-1178 recording that both halves of the M1 union are now asked with the SAME identity |

Net: `poi_admission.py` 730 → 792 lines (ceiling 1000, DEC-0 clear); `pipeline.py` 7221 → 7226 (+5:
3 for the split call expression, 2 for the comment) — recorded, since `pipeline.py` is a
"net-negative or leaf" file and this is a +5 comment/format growth inside one existing statement.

**Behaviour, exactly:** explicit identity + matching publication → the identical branch and the
identical dict as before. Explicit identity + a DIFFERENT published scene → no `arrival_goal_region`,
no `goal_region_source`, no `goal_region_instance_id`, no `terminal_relation`; the mission gets
exactly the dict a non-region POI has always carried, plus `goal_region_refused:
scene_mismatch:<navigator>/<published>`. Published fallback (`world_identity is None`) and the
no-scene case → untouched by construction (`source != IDENTITY_EXPLICIT` short-circuits first).

### The test that proves it (through the PRODUCT composition)

`tests/test_poi_admission.py:786` `test_a_foreign_worlds_polygon_is_never_the_committed_arrival_authority`
— publishes generated seed **880000** through the product publisher (`extract_city_semantics`),
builds `DirectiveNavigator.from_config(world_identity=WorldIdentity.from_scene_file(DEFAULT_CITY_SCENE))`
and calls **`navigator.parse("go to the crosswalk")`** — i.e. `pipeline.py`'s own metadata assembly,
not a helper copy. Asserts the POI is still admitted on the navigator's word
(`identity_source == explicit`, `poi_id == crosswalk_a`), that none of the four region keys is
present, that `goal_region_refused == "scene_mismatch:parcel_city_block/parcel_val_unseen_880000"`,
and then MEASURES the harm the old composition did: 880000's own crosswalk is > 1.5 m from
`(3.5, -0.6)` — the coordinate the mission actually drives to — so with that polygon committed
`poi_region_arrival_admits(..., geometrically_arrived=True, inside_region=False)` is `False`
(the arrival that can never happen), while the fixed mission returns `True`.

`tests/test_poi_admission.py:850` `test_the_navigators_own_world_still_commits_its_region` — the
control, in both directions: demo block published, navigator told the demo block **and** navigator
told nothing (the published fallback, the branch every frozen nav row takes). Both still commit
`terminal_relation: inside`, `goal_region_source: region_class_poi`, the scene's own instance id and
its own polygon, with `goal_region_refused` absent. Without this row a "commit nothing, ever" change
would pass the first test.

### Teeth (the defect row fails without the fix)

Reverted `pipeline.py:1183` to the pre-fix `poi_goal_metadata(self.grounder, goal)` and re-ran:

```
E  AssertionError: assert 'arrival_goal_region' not in {'arrival_goal_region': {...}, 'goal_region_instance_id': 'crosswalk', 'goal_region_source': 'region_class_poi', ...}
FAILED tests/test_poi_admission.py::test_a_foreign_worlds_polygon_is_never_the_committed_arrival_authority
1 failed, 1 passed, 27 deselected, 2 warnings in 1.04s
```

(the committed polygon in that failure is 880000's, `[[-0.346, 1.922], ...]` — the foreign world's).
Line restored in the same command; the control row passed in both states.

### Guarded runs

| suite | result |
|---|---|
| `tests/test_poi_admission.py tests/test_navigation.py tests/test_arrival_receipt_wiring.py tests/test_nav_instruct_receipt_authority.py` | **85 passed, 2 warnings in 34.95s** |
| `tests/test_poi_admission.py` alone (first pass) | 29 passed in 2.93s |
| extra nav regression, unasked: `test_k0_arrival_authority test_scene_surface_truth test_arrival_settle test_nav_instruct_scene_gen test_person_aware_nav` | **120 passed in 14.49s** |

### The v5 frozen evidence is untouched

| suite | result |
|---|---|
| `tests/test_nav_instruct_digest_recipe.py tests/test_mutation_panel_freshness.py` | **26 passed, 2 warnings in 1351.35s (0:22:31)** — includes the LIVE panel re-derivation ("committed fields reproduce live") |

**Why the eval path takes exactly the old branch, structurally:** `HeadlessCityWorld.__init__`
(`simulation/headless_city.py:251,255`) publishes the scene through `extract_city_semantics` **and**
sets `self.world_identity` from the same model; every eval navigator is built with that value
(`evals/nav_instruct/runner.py:829`, `headless_city.py:773`). One published scene whose id equals the
navigator's identity ⇒ `identity.matches(scene.scene_id)` is `True` ⇒ `scene_for_identity` returns
the same `SceneInstanceSet` the old code read out of the global ⇒ `region_instance_for_poi` receives
the identical argument. No artifact under `evals/nav_instruct/results/` was written during this card
(mtimes all 08:07–12:44, i.e. before this session; `mutation_panel.json` 12:44:23, `ledger.jsonl`
09:55:48, both W5/W5-F2's).

**Observation, not changed (for the follow-up list):** `admit_poi` still takes the raw publication for
its GEOMETRY DIAGNOSTIC (`poi_admission.py:498`), so on a two-worlds process `geometry_backed` /
`nearest_instance_id` on a refusal describe the foreign scene. It decides nothing (F1 demoted it and
the docstring says so), so I left it; identity-scoping the diagnostic is a one-line follow-up.

---

## ITEM 2 [HIGH] — `_resume_queued_parent`'s product caller is now tested

### What changed

No product change (the finding is a missing test). `runtime.py` is byte-identical to what it was
when I started: `git hash-object src/parcel_robot/runtime.py` = `bebd2505b9ae6edd3c89e240ab3168f1a0cf28be`
**before** the teeth check and `bebd2505b9ae6edd3c89e240ab3168f1a0cf28be` **after** it, and line 5249
reads `                self._resume_queued_parent(result.task_id, disposition.action)` in both.
(The call is at **:5249** in the gate tree, not :5244 — W4-F8's edits above it shifted the line.)

New tests: `tests/test_plan_queue.py:956-1105` (section 9), two rows plus two helpers.

| line | row |
|---|---|
| `tests/test_plan_queue.py:984` | `_hand_back_spy(runtime)` — records every `_resume_queued_parent(child, action)` and calls the real one through |
| `tests/test_plan_queue.py:1003` | `_queued_child_through_the_door(runtime, parent_directive)` — parks a live parent behind "after that, go to the bench" entirely through `handle_text`, and asserts the child's step is the ONLY live dispatch, so the terminal the poll produces can only be the child's |
| `tests/test_plan_queue.py:1027` | `test_step_brains_poll_loop_rebinds_the_parent_when_the_child_goes_terminal` — **FOLLOW parent, NAVIGATION child** (cross-channel, so the parent's `ResumeIntent` outlives the child): the child's mission is ended through the runtime's own terminal writer `_stop_navigation_channel(reason="navigation_no_progress", state="failed")`, then **one** `runtime._step_brain()`. Asserts the hand-back was called from the poll loop `[(child, "task_failed")]`, the parent's record carries `resume_offer` + `plan_resumed` and is `resumed`, **`resume_task_running` was invoked with the parent** (recorded via a call-through wrapper) and accepted, the executive row is `running` with `last_detail` ending `plan_queue_resume`, the parent was NOT dispatched again (`starts.count(parent) == 0` — a re-bind, not a second start), and the `follow` `ResumeIntent` was consumed |
| `tests/test_plan_queue.py:1082` | `test_step_brains_poll_loop_also_re_queues_a_same_channel_parent` — NAV-INT-1's own same-channel scenario (parent and child both on `navigation`): the parent's intent is already gone, so the honest fallback runs; asserts the same poll-loop hand-back plus `plan_resumed` detail `requeued_fresh_dispatch` and the row leaving `suspended` |

Nothing in either row calls `_resume_queued_parent`, `task_executive.report`, or the adapter: the
terminal travels `adapter.poll` → `executive.report` → the hook, inside `_step_brain`.

**Finding recorded while building this (worth a board line):** the queue door only admits
goal-directed navigation amendments — `"after that, follow me"` and `"after that, sit"` both answer
*"I did not understand that command"*. So a queued CHILD is always a navigation task, and with a
navigation PARENT the parent's `ResumeIntent` is always gone by the time the child goes terminal
(the note in `test_a_refused_rebind_never_leaves_a_channel_driving_over_a_parked_record` says the
same thing from the other side). The `resume_task_running` re-bind arm is therefore reachable through
the product door only with a non-navigation parent — which is why row 1 uses a FOLLOW parent, and it
is the first test in the suite to reach that arm without constructing the state by hand.

### Teeth (both rows fail without the single product line)

Commented out `runtime.py:5249` (replaced by `pass  # TEETH-F-M2`), ran, restored inside the same
command (elapsed under one minute; hash identical, see above):

**Without the line:**
```
>       assert calls == [(child, "task_failed")], (
E       assert [] == [('parcel-tas...task_failed')]
E         Right contains one more item: ('parcel-task-4c7a45eebf67fb1d35f10358', 'task_failed')
FAILED tests/test_plan_queue.py::test_step_brains_poll_loop_rebinds_the_parent_when_the_child_goes_terminal
FAILED tests/test_plan_queue.py::test_step_brains_poll_loop_also_re_queues_a_same_channel_parent
2 failed, 74 deselected, 2 warnings in 0.88s
```

**With the line restored:**
```
2 passed, 74 deselected, 2 warnings in 0.84s
```
```
tests/test_plan_queue.py tests/test_wave_b_integration.py:  77 passed, 2 warnings in 2.38s
```

---

## ITEM 3 [MEDIUM] — matrix-freshness residue

### What changed

| file:line | change |
|---|---|
| `tests/test_nav_instruct_matrix_freshness.py:146-159` | the nightly cell takes `tmp_path` and `capsys`; `out = tmp_path / "matrix-freshness"` — a per-invocation scratch dir OUTSIDE the repo (was `REPO / ".pytest-matrix-freshness"`, `mkdir(exist_ok=True)`) |
| `tests/test_nav_instruct_matrix_freshness.py:112-143` | new `report_written_by_this_run(out, printed)` — reads back the file **this** invocation produced: the fresh dir must hold exactly ONE report, and the path must equal the one the runner itself names in its closing `print(json.dumps({"report": ...}))` (`evals/nav_instruct/run_nav_instruct_v1.py:609-612`). Was `sorted(out.glob(...))[-1]`, i.e. recency |
| `tests/test_nav_instruct_matrix_freshness.py:176` | `report = report_written_by_this_run(out, capsys.readouterr().out)` |
| `tests/test_nav_instruct_matrix_freshness.py` (top) | the `REPO` constant removed — the repo-rooted scratch dir was its only reader |
| `tests/test_nav_instruct_matrix_freshness.py:201, 223` | two new COMMIT-tier rows for the reader: the run's own report is accepted; a directory holding a second report is refused (not resolved by sort order); a report the runner never named cannot certify freshness |
| `.gitignore:9-13` | `.pytest-matrix-freshness/` added under the existing test-scratch entries, with a three-line comment saying it is belt-and-braces now that the cell writes to scratch |
| — | the two 3,344,398-byte residue files and the directory `~/.cache/parcel-0e/wb/gate/.pytest-matrix-freshness/` **deleted** (`rm -rf`; the one deletion the card allows). `git status --porcelain` no longer lists it |

### Guarded run + the dry structural check

```
tests/test_nav_instruct_matrix_freshness.py -m 'not slow':  6 passed, 2 deselected in 0.16s
```

The `slow` nightly cell itself was NOT run (238 s matrix). Instead, a scratch-only pytest file
(`<scratchpad>/test_fm2_matrix_dry.py`, **not committed, not under `tests/`**) imported the module by
path, monkeypatched `evals.nav_instruct.run_nav_instruct_v1.main` with a stub that writes the
committed artifact's own content into whatever `--out` it is given and prints the runner's real
closing JSON blob, and called the nightly cell with pytest's `tmp_path`/`capsys`:

```
SCRATCH-OUT /tmp/pytest-of-jaewoo-jang/pytest-3178/test_the_nightly_cell_uses_a_s0/matrix-freshness
RESIDUE-IN-REPO False
1 passed, 3 warnings in 0.39s
```

i.e. the recipe is assembled and passed with `--no-ledger`, `--out` is under pytest's tmp root and
not under the repo, the read-back resolves through the runner-named path, and the comparison still
returns "reproduces". The only thing not exercised is the 238 s run itself.

---

## Close-out

**ruff** — clean on every file touched, zero `noqa` in any of them:

```
$ .parcel/bin/ruff check src/parcel_robot/navigation/poi_admission.py \
      src/parcel_robot/navigation/pipeline.py tests/test_poi_admission.py \
      tests/test_plan_queue.py tests/test_nav_instruct_matrix_freshness.py
All checks passed!
$ grep -c noqa <the five files>   ->  0 0 0 0 0
```
(`.gitignore` is not Python; ruff on it reports a syntax error by construction and was excluded.)

**`git -C ~/.cache/parcel-0e/wb/gate status --porcelain`** — the entries this card is responsible for
(the rest of the porcelain is the unchanged wave-B stack):

```
 M .gitignore                                     <- NEW this card (was clean at HEAD before F-M2)
 M src/parcel_robot/navigation/pipeline.py        <- wave B + F-M2 hunk at :1176-1183
 M src/parcel_robot/navigation/poi_admission.py   <- wave B + F-M2 hunks at :517-563, :600-637
 M tests/test_poi_admission.py                    <- wave B + F-M2 rows at :786-879
?? tests/test_plan_queue.py                       <- W1's new file + F-M2 section 9 at :956-1105
?? tests/test_nav_instruct_matrix_freshness.py    <- W5's new file + F-M2 edits (above)
(-) .pytest-matrix-freshness/                     <- residue deleted; no longer in the untracked set
```

**`git diff --stat`** for those paths (vs HEAD `c96ac34`, so this is wave B **plus** F-M2; the two
`??` files are untracked and therefore absent from a diffstat):

```
 .gitignore                                   |   4 +
 src/parcel_robot/navigation/pipeline.py      |  69 +++--
 src/parcel_robot/navigation/poi_admission.py | 369 +++++++++++++++++++++++---
 tests/test_poi_admission.py                  | 382 ++++++++++++++++++++++++++-
 4 files changed, 761 insertions(+), 63 deletions(-)
```

F-M2's own share of that, by line count of the files before/after this card:
`poi_admission.py` 730 → 792 (+62), `pipeline.py` 7221 → 7226 (+5), `test_poi_admission.py` 762 → 879
(+117), `test_plan_queue.py` +150 (section 9), `test_nav_instruct_matrix_freshness.py` 202 → 272
(+70), `.gitignore` +4.

**Constraints honoured:** no safety floor touched (`obstacle_stop_m`, `apply_reactive_safety`,
`finalize_command`, `core/hard_stop.py` unopened); `realtime/config.py` not touched; no `noqa`; no
git write; no `ci_gate.py` / `mutation_panel.py` / eval runner / simulator; every pytest through the
guard, serial; `TMPDIR` unset; owner's live stack and memory store untouched.

**Not done / for the verifier:**
1. The `slow` nightly matrix cell was proven structurally, not by a 238 s live run (see above).
2. The full v5 matrix was not re-derived; the frozen-evidence proof is the digest-recipe suite plus
   the panel's LIVE re-derivation (26 passed), plus the structural argument that the single-world
   branch is bit-identical.
3. `admit_poi`'s geometry DIAGNOSTIC still reads the raw publication (observation above) — left as a
   follow-up rather than widened here.
4. The pending HIGHs from the review workflow were not part of this dispatch; nothing here touches
   them.
