# Runtime / handoffs lane — status · 2026-08-07

**Scope:** the runtime-side halves of Lane C's and Lane B's hand-offs, plus
backlog N14. **Owned files:** `runtime.py`, `core/**`, `brain/**`, `voice/**`,
`agent.py`, `runtime_channels.py`, `attention/**` and their tests. Everything
landing in `navigation/**`, `instructnav/**`, `evals/**` or `scripts/` is
**forwarded, not edited** — listed at the bottom with an owner.

**Read with:** [LANE_C_HANDOFFS.md](../../20260806/task_3/LANE_C_HANDOFFS.md)
(H1–H8), [LANE_C_STATUS.md](../../20260806/task_3/LANE_C_STATUS.md),
[LANE_B_STATUS.md](../../20260806/task_3/LANE_B_STATUS.md) hand-offs 2 and 3.

## Outcome per card

| card | outcome |
|---|---|
| R-1 — N14 resume join | **done.** xfail flipped on measured behaviour; the pinned measurement was itself corrected (below). 5 further product-path cases added. |
| R-2 — Lane C H1–H8 | **H2 done, H7 done, H6 partly done + corrected, H3 = R-1.** H1/H4/H5/H6(N-SUP) forwarded. |
| R-3 — Lane B hand-offs | **done.** Owner-facing LOST announcement wired — and a larger defect behind it found and fixed. `map`→`odom` recorded as backlog N15. |
| R-4 — backlog hygiene | **done.** N14 closed, N15 opened, U20/U28/U33/U34 updated with measurements. |

---

## R-1 / H3 / N14 — RESUME left the executive task suspended

### The pin was right about the defect and wrong about its shape

Lane C pinned: after `pause` → `resume` the navigation channel reads
`state="searching"`, `reason="navigation_resumed"` and is *"advancing"*, while
the task record stays `suspended` **"across further `_step_brain()` ticks"**.

Re-measured on the product path before touching anything, the channel does not
keep advancing. The **first** tick after the resume puts it back:

| after | navigation channel | executive task |
|---|---|---|
| `pause` | `paused` / `closed_intent_pause` | `suspended:closed_intent_pause` |
| `resume` | `searching` / `navigation_resumed` | `suspended` — unchanged |
| `_step_brain()` ×1 | **`paused` / `task_suspended`** | `suspended` |
| ×2, ×3 | `paused` / `task_suspended` | `suspended` |

`_reconcile_semantic_tasks` sees a still-suspended task, drops its dispatch
record and re-pauses the channel. So the real failure was **quieter and worse**
than pinned: a spoken RESUME held for less than one control tick, then parked
the mission permanently. The fix and its pins are written against that
measurement, not the original one.

### The fix: the two halves resume together or not at all

The tempting one-liner — call `resume_task` and let the next `tick`
re-dispatch — is wrong here, and the K3 summons path shows why it *looks*
right: there the controller was torn down, so a fresh dispatch is the honest
restore. After a closed-intent pause the controller was **paused with a stored
`ResumeIntent`**, and re-dispatching would run
`_start_or_resume_navigation_locked` against a navigator that is no longer
paused and a store that is now empty — i.e. a cold start that throws away the
mission it just restored. Worse, when no control tick separated the pause from
the resume, the adapter still holds the dispatch key and the re-dispatch raises
`semantic dispatch is already active` → `dispatch_failed`.

So a second, narrow verb was added next to `resume_task`:

- **`TaskExecutive.resume_task_running(task_id, reason=, now=)`** → returns a
  suspended task to `running` **without** re-dispatching: resources
  re-acquired, `step_started_at` restarted at `now` (the pause must not eat the
  step timeout), `last_detail="resumed_running:<reason>"`. Fail-closed: if the
  step's resources are held by someone else it stays suspended and the
  disposition says `ignored_resources_unavailable`, because a `running` record
  over an un-leased resource is a false claim of authority.
- **`SemanticTaskRuntimeAdapter.adopt(request, now=)`** — re-binds tracking to
  a step whose controller is already executing. Replaces any existing record so
  the adapter's elapsed clock matches the executive's restarted one.
- `TaskExecutive.tick` and `resume_task_running` now build their
  `DispatchRequest` through one `_dispatch_request` helper, so the two cannot
  describe the same step differently.
- The executive snapshot row gained `"skill"` — the runtime needs it to know
  which channel a suspended task owns.

**The join is on the suspend reason.** Only tasks whose `last_detail` is
`suspended:closed_intent_pause` are restored. This is not fastidiousness: the
first version filtered only on that reason when *resuming*, and a task parked
by an owner summons then had its channel released underneath it — the same N14
defect through a different door, caught by a test written for the opposite
purpose. A channel whose owning task is parked by anyone else is now refused
outright, with the honest "I couldn't resume yet" reply and the channel left
paused.

**Fail-closed behaviours K3/B1 established are preserved and pinned:** empty
store → *"There's nothing paused to resume right now."*; freshness rejection →
neither half moves; a blocked executive task → the channel is re-paused rather
than left driving.

**Three refusals, said three different ways.** The first version reported a
"someone else holds this" refusal with the freshness sentence, which would send
the owner to fix the wrong thing. They are now separate: *"There's nothing
paused to resume right now."* / *"I couldn't resume yet — the observation isn't
fresh enough, or the paused task expired."* / *"I can't resume that yet — it's
paused by something else right now."*

**Tasks with no pausable channel** (a `Hold` step, a gesture, a spatial
behaviour) are parked by PAUSE too, and a suspend *stops* their controller
rather than pausing it — there is no `ResumeIntent` to re-bind to. Those are
re-queued for a fresh dispatch, which is the honest restore for a controller
that was torn down. Before this, `stay` → `pause` → `resume` answered *"There's
nothing paused to resume right now"* and left the task suspended forever;
measured, and pinned by
`test_a_parked_task_with_no_pausable_channel_is_re_queued` (queued → running →
`succeeded`/`motion_stop_verified`).

**Constants:** `CLOSED_INTENT_PAUSE_REASON` / `CLOSED_INTENT_RESUME_REASON` now
live in `brain/executive.py` beside `VOICE_INTERRUPT_POLICY`, which must map
the pause reason to `suspend` or a pause would cancel instead of park. Three
parties agreed on that string by coincidence before.

**Pins** (all in `tests/test_closed_intent_product_path.py`, xfail removed):

| test | what it holds |
|---|---|
| `test_resume_also_restores_the_executive_task_record` | `running` — not merely "not suspended". `queued` would clear the old pin while ordering the cold start. |
| `test_resume_survives_a_control_tick_between_pause_and_resume` | the product shape, i.e. the state the corrected measurement found |
| `test_resume_continues_the_paused_mission_rather_than_restarting_it` | the mission object survives (`is` identity) |
| `test_a_stale_resume_leaves_both_the_channel_and_the_task_paused` | fail-closed in the joined direction |
| `test_resume_does_not_restart_work_it_did_not_pause` | reason-scoped, and the channel is not released either — with the refusal named for what it is |
| `test_a_parked_task_with_no_pausable_channel_is_re_queued` | the other half of the pair: stopped controllers are re-dispatched, not re-bound |

---

## R-2 — Lane C H1–H8

### H2 — the settle plan was acknowledged as "I'll stay here." · done

`_plan_acknowledgement` keyed on `goal.relation`, and a settle plan wears
`hold`/`current_pose` because that is the only goal shape the validator admits
for a terminal `Pose` step. So *"sit next to the bench"* answered **"Okay—I'll
stay here."**

The `hold` branch now reads the *plan*: a `hold` goal whose steps contain a
`NavigateTo` is a settle, and is acknowledged as travel plus posture —
**"Okay—I'll head over to bench and sit down."** The posture verb comes from
`SETTLE_POSE_PHRASES` in `voice/local_plans.py` (next to `SETTLE_POSE_NAME`),
which covers only poses that exist in `configs/skills/poses`; anything else
acknowledges with the neutral "settle" rather than describing a posture the
robot may not have. Nothing claims arrival.

Pinned by `test_the_settle_plan_is_acknowledged_as_travel_plus_posture` and
`test_a_plain_hold_plan_still_says_it_will_stay` (the branch is narrowed, not
replaced).

### H7 — the compiler's runtime-authored contract fallback · removed

`_materialize_brain_planner_output` now selects the registry by route —
`system_registry` for `direct_skill`, `brain_registry` otherwise — exactly the
way `_accept_plan` always has. With that, `compiler._contract_for` and
`_system_contracts` were **deleted**; `compile_plan_contracts` resolves
contracts through `registry.get(skill)` and nothing else.

`RUNTIME_AUTHORED_SKILLS` in `SkillContractRegistry.get()` stays — it is what
makes the system registry admit `Pose` at validation. The model-facing surface
is unchanged and now refuses the settle step one step *earlier* (at compile
time as well as at admission), which the updated pin asserts both ways.
`configs/robot.yaml` untouched.

### H6 — carried-forward items

- **`detector_query_set()` "has no consumer".** Half wrong, and corrected in
  the docstring: `voice/scene_reference.known_scene_words()` already reads it
  as the set of scene words an utterance may name. Its *named* consumer — the
  open-vocabulary detector prompt list — does not exist in the tree at all
  (`grep` for nanoowl/open-vocab finds no detector prompt list;
  `detection_adapter`'s `vocabulary` is the noise model's confusion set). So
  there is nothing to wire, and no fourth copy of the vocabulary was created.
- **N-SUP-1 / N-SUP-2** live in `instructnav/**` — forwarded.

### H6 follow-up found while reading it: the clarification could not be answered

Not in the hand-off doc; found by driving the clarify fallback through
`handle_text`. Measured before the fix:

```
"befriend the bench" → "I'm not sure what you want me to do with the bench —
                        I can go to it, sit next to it, or walk towards it."
"go to it"           → "Okay—I'll go wait near it safely."   ← plan admitted,
                                                                target = "it"
```

The clarification put words in the owner's mouth that the grammar then compiled
into a mission for a landmark that cannot exist. Exactly U33's pattern — every
component correct, the composition wrong — one layer out from where U33 found
it. Two halves, both narrow:

1. **The referent binds the next turn's pronoun, for exactly one turn.**
   `resolve_pending_reference` (pure, in `voice/scene_reference.py`) rewrites a
   bare `it` / `that` / `that one` to `the <class>`, before routing, so route,
   grammar, grounding and reply all see one resolved utterance. It refuses when
   the utterance already names a scene class — resolution binds pronouns, it
   does not overwrite what the owner did say. The pending referent is consumed
   by *whatever* comes next, answered or not. The substitution is reported on
   `agent.last_resolved_reference` and in `last_brain_metrics`, never silent.
2. **A pronoun destination with no referent is asked about, not admitted:**
   *'I'm not sure what "it" refers to — could you name the place?'* Word
   boundaries, so `go to the summit` is untouched.

8 pins in `tests/test_owner_and_settle_plans.py`, including one that walks
**every phrase the clarification offers** and asserts each reaches a plan about
the right class.

---

## R-3 — Lane B hand-offs

### Owner-channel LOST announcement — and the defect underneath it

Lane B's hand-off says the navigator stops and walk_with_me records it, and the
runtime "does not yet speak it". Measured on the product path, the runtime was
doing something worse than staying silent.

`_pose_lost_hold` returns `MidLevelCommand(stop=True, note="pose_lost_hold")`
with the mission **left running on purpose** — the goal is still valid and
health can return. `_step_navigation` had no branch for it, so it fell into the
generic `command.stop` arm:

```
navigation: {enabled: False, reason: "pose_lost_hold"}
_navigation_directive: None                       ← mission destroyed
event: "Navigation failed for sidewalk: pose_lost_hold"  (level=error)
```

The runtime tore down a mission the navigator was holding open, restored the
directive pace, and told the operator the navigation had failed. It had not.

Both halves fixed together — announcing a LOST hold while silently killing the
mission would have been worse than silence:

- **The hold is a hold.** `state="waiting"`, `enabled=True`, directive kept,
  lease cancelled (the command *is* a stop). `"waiting"` is already
  `NAVIGATION_IN_PROGRESS_STATES` in the adapter, so the plan step stays
  `running` instead of failing — measured.
- **The owner is told, once per transition**, through `_brain_vocalize` — the
  same door the `Vocalize` skill uses, no new announcement channel. The
  sentence is the one Lane B already wrote on the trace sample: *"I've lost
  track of where I am, so I've stopped and I'm holding here."* Edge-triggered
  because the hold fires on every control tick.
- **The recovery line cannot outrun the fact.** *"I know where I am again —
  carrying on."* is reachable only from a tick on which the navigator issued a
  non-stop command, which `_pose_lost_hold` makes impossible while health is
  `LOST`.

6 pins in `tests/test_pose_health_announcement.py`, including "nothing is
announced when localization never drops".

**Not claimed:** exercised by injecting the exact command `_pose_lost_hold`
returns, not by a drift provider reaching `LOST` in a live run; and the
sentence has never been spoken by real TTS.

### `map` → `odom` — recorded, not implemented

Lane B hand-off 3, now backlog **N15** so it lives somewhere other than a code
comment. `grid_navigator` is ODOM-bound, `mission.goal` is a MAP quantity, no
transform connects them; under `TruthPoseProvider` the frames are identical so
nothing moves today. Named in the code at `navigation/grid_navigator.py:333`,
which is the one call site that needs it. Owner: `navigation/**`.

N15 also records a smaller residue this round created: `"pose_lost_hold"` now
exists as a literal in three trees (`navigation/pipeline.py`, `runtime.py`,
`evals/walk_with_me/runner.py`). Three copies of a control string is how "halt"
got lost. The shared home is `navigation/base.py`; not made, wrong lane.

---

## R-4 — backlog

| entry | change |
|---|---|
| **N14** | closed, with the corrected measurement written down and the fix shape recorded |
| **N15** | opened: `map`→`odom` transform + the `pose_lost_hold` literal residue |
| **U20** (suspend→resume, blocker) | fifth defect added — and the note that the four before it were all found by *unit* pins while this one survived them. Still a blocker: no live-mission integration. |
| **U28** (K4 ScanBehavior/SearchEntity) | re-measured, **unchanged** — the adapter is still constructed without those two callbacks. Not fixed; it is a card, not hygiene. |
| **U33** (closed intents) | N14 marked closed; the `router_cases.jsonl` freeze re-attributed; the clarify-fallback finding added as the same pattern one layer out |
| **U34** (pose seam) | Lane B hand-off 2 closed, with the terminal-failure defect it uncovered, and what is still unexercised |

---

## Verification

This lane ran with two other executors landing work in the same tree, so the
suite numbers moved under it. All of them are recorded, not just the flattering
one.

**At the last edit made by this lane** (non-e2e):
**2668 passed, 7 skipped, 1 xfailed, 0 failed** (90 s). Entry state was 2
failed (the Lane A `test_authority_no_literal_drift` pair, H5) — both already
green before the first edit here, fixed by another lane.

**Full default suite, `MUJOCO_GL=egl`, everything including e2e** (883 s):
**2715 passed, 10 skipped, 3 xfailed, 1 xpassed, 6 failed.** The six were
`tests/test_nav_instruct_scene_gen.py` ×5 and
`tests/test_barn_experiment_harness.py` ×1 — a **new** test file (untracked,
mtime 20:52) that another executor wrote *while the run was executing*. All 42
tests in those two files pass when re-run: `42 passed in 3.37s`. Mid-run edit
artifact, `evals/**`.

**Final non-e2e re-run, 40 minutes after this lane's last code change:**
**2759 passed, 14 skipped, 1 xfailed, 3 failed.** The three are
`tests/test_duplex_v1.py::{test_duplex_v1_hard_gates_pass,
test_nav_regression_pins_post_speed_raise_rows,
test_duplex_v1_cli_writes_report_and_ledger}`, they reproduce in isolation, and
they are **not** a mid-run artifact — they are `evals/**`:

```
AssertionError: assert '9/9' == '8/9'
```

Another executor appended two follow-bench rows to
`evals/companion_nav/results/ledger.jsonl` at `20260808T004956Z` and
`20260808T005037Z`, moving the latest shipped `follow_success` from `8/9` to
`9/9`, while `evals/companion/duplex_v1/run_duplex_v1.py`'s
`FOLLOW_BENCH_POST_SPEED` still pins `8/9`. That is a real red and it is a
genuinely good result someone needs to re-pin — but the pin and the ledger are
both in `evals/**`, which this lane must not edit. **Forwarded to E2.**

**Nothing in this lane's files is red in any of those runs**, and the two
test-count jumps (2668 → 2715 → 2759) are other lanes' tests arriving.

**ruff:** clean on every touched file.

**One red was inherited and fixed, and it was nobody's code.**
`tests/test_emote_skill.py::test_text_only_path_fires_emotes_immediately`
asserts `runtime._speaker_sink is None`, and got that by accident:
`build_speech_stack` defaults to `mode: auto`, so whether a synthesizer exists
depends on whether `models/piper/voice.onnx` is on disk. That file was created
at **20:23 today** by a concurrent lane, and the assertion flipped. The test's
config now declares `speech: {mode: text}`, so the text-only path is stated
rather than inferred. A test that changes verdict with an unrelated asset
download is not testing what it says.

**Also observed once and not reproduced:**
`tests/test_run_barn.py::test_spawn_workers_...` failed with
`AttributeError: 'DirectiveNavigator' object has no attribute
'_gate_blocked_route_recovery'` at `navigation/pipeline.py:678` during one
mid-session run, and passed on every run before and after. `navigation/**` was
being edited concurrently; no file in this lane is in that path.

**e2e (`tests/test_voice_nav_e2e.py`, `MUJOCO_GL=egl`, real sim):**
**14 passed, 2 xfailed, 1 xpassed, 0 failed** in 766 s. The file is not owned
by this lane and was not edited. Two things in that result belong to whoever
owns `navigation/**` and should be acted on:

- **The approach path is green again.** `test_go_to_the_sidewalk_...` and
  `test_walk_towards_the_lamppost_...` — the two pre-existing hard gates Lane C
  recorded as red at its exit (H8, `safe_approach_pose → None`) — both pass,
  and so do all four cases Lane C had to pin as unverified (the two
  paraphrases and the two superlatives), whose pins are gone from the file.
  **Lane C's two never-observed-green superlative claims are now observed
  green**, which is what their pins asked for.
- **`test_sit_next_to_the_lamppost_settles_beside_it_in_a_sit` XPASSes.** That
  is N13's *placement* half — the defect Lane C explicitly did not claim to
  have fixed — passing on a real run. The xfail should be flipped by its owner
  after a confirming re-run; this lane did not touch that file. The bench
  variant still xfails, so the placement fix is not uniform.

---

## Forwarded — not edited, with owners

| item | lives in | owner |
|---|---|---|
| **H1** — RelationSpec registry consumption (`arrival_goal_region_for_relation`, `_terminal_relation_verified`, the `PROXIMITY_FAMILY` and polygon-ness branches), plus the soft-import discipline frozen BARN bundles need | `instructnav/scoring.py`, `navigation/pipeline.py` | E1 |
| **H4** — freeze the eight closed-intent routes in `router_cases.jsonl` | `evals/companion/brain_v1/` | E2 |
| **duplex_v1 red** — `FOLLOW_BENCH_POST_SPEED` pins `8/9`; the ledger's latest shipped row is now `9/9`. Re-pin the improvement (3 tests red as of 2026-08-08 00:52) | `evals/companion/duplex_v1/run_duplex_v1.py`, `evals/companion_nav/results/ledger.jsonl` | E2 |
| **H5** — the two `1.2` literals in the `_FrozenBundleEnvelope` fallback: allowlist with a family tag or derive | `navigation/collision.py`, `tests/test_authority_no_literal_drift.py` | Lane A / E1 — **already green at this lane's entry**, so it was fixed by someone before this round started |
| **H6 / N-SUP-1** — distance-first ordering for explicit superlatives; one `superlative`-aware sort key at `_rank_candidates` | `instructnav/grounding.py` | E1 |
| **H6 / N-SUP-2** — `RememberedEntity` carries size | `instructnav/memory.py` | E1 |
| **H8** — `safe_approach_pose → None` for plain near-object goals | `navigation/approach.py`, `navigation/pipeline.py` | E1 — **appears fixed**: all seven reddened tests and both hard gates pass, measured 2026-08-07 |
| **N13 placement half** — `test_sit_next_to_the_lamppost_settles_beside_it_in_a_sit` now **XPASSes** live; flip the pin after a confirming re-run (the bench variant still xfails) | `tests/test_voice_nav_e2e.py` | E1 |
| **N15** — `map`→`odom` transform at `grid_navigator.act` | `navigation/grid_navigator.py` | E1 |
| **N15b** — one home for the `pose_lost_hold` note literal | `navigation/base.py` (+ the `evals` copy) | E1 / E2 |
| **U28** — bind `scan_behavior` / `search_entity` in the runtime adapter | `runtime.py` — **this lane's file**, but a card, not a hand-off; not started | next runtime card |

## Non-claims

1. **Nothing here ran in live sim.** Every measurement is the product-path
   layer: a real `RobotRuntime` over a fake backend, entered at `handle_text`.
   That is where route → registry → admission → executive → channel actually
   compose, and it is not physics.
2. **The LOST path was exercised by injection**, not by a pose provider that
   reaches `LOST` on its own, and the announcement has never been spoken aloud.
3. **The pronoun binding is one turn and three words** (`it`, `that`,
   `that one`). It is not an anaphora model and does not resolve "the first
   one", "the other one" (that is the amendment grammar's), or anything across
   two turns.
4. **`resume_task_running` has never been called by anything but the RESUME
   cap.** The summons path still uses `resume_task` + re-dispatch, correctly —
   its controller really was torn down.
5. **U28 was re-measured, not fixed.**
6. **No new harness, no config framework, no new event channel.** The LOST
   announcement reuses the `Vocalize` door; the resume join reuses the existing
   ResumeIntent store and executive; the compiler lost code rather than gaining
   it.

## Files touched

**Source:** `src/parcel_robot/runtime.py`, `src/parcel_robot/agent.py`,
`src/parcel_robot/brain/executive.py`,
`src/parcel_robot/brain/runtime_adapter.py`,
`src/parcel_robot/brain/compiler.py` (net deletion),
`src/parcel_robot/voice/local_plans.py`,
`src/parcel_robot/voice/scene_reference.py`,
`src/parcel_robot/scene_semantics.py` (docstring correction only)

**Tests:** `tests/test_closed_intent_product_path.py` (xfail flipped, +4),
`tests/test_owner_and_settle_plans.py` (+10),
`tests/test_pose_health_announcement.py` (new, 6),
`tests/test_emote_skill.py` (declare the text-only speech mode)

**Records:** this file, `backlog/NEXT.md` (N14 closed, N15 opened),
`backlog/UNVERIFIED.md` (U20, U28, U33, U34)

**Not touched, per file ownership:** `navigation/**`, `instructnav/**`,
`evals/**`, `scripts/`, `tests/test_voice_nav_e2e.py`, `authority.py`,
`pose.py`, `configs/robot.yaml`, scene files.
