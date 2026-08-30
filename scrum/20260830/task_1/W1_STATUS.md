# W1 · PLAN-QUEUE-1 (C6) — STATUS (Opus executor)

**Card:** `scrum/20260830/task_1/W1_PLAN_QUEUE.md` · **Design:** `scrum/20260829/task_2/C6_PLAN_QUEUE.md`
**Verifier:** Fable · **Lens:** parcel-6c · Written incrementally; this file is the ONLY main-repo path this executor writes.

## Pre-flight (integrator rule 1)

| fact | value |
|---|---|
| worktree | `/home/jaewoo-jang/.cache/parcel-0e/wb/w1` (`git worktree add --detach … HEAD`) |
| worktree HEAD sha | `c96ac345358ec2786748fc3a885c35d32710c5e2` |
| `.parcel` | symlink → `/home/jaewoo-jang/Desktop/Projects/Parcel/.parcel` |
| `PYTHONPATH` | `<wt>/src:<wt>` · `MUJOCO_GL=egl` · `OPENBLAS_NUM_THREADS=32` · `TMPDIR` unset |
| `parcel_robot.__file__` | `/home/jaewoo-jang/.cache/parcel-0e/wb/w1/src/parcel_robot/__init__.py` — **the worktree**, verified before any edit |
| main repo | never edited except this file; no `git add`/commit/stash anywhere |

The main repo's dirty hunks in `runtime.py` (+229) and `brain/executive.py` (24) are **not** in this
worktree and were never read into the design; every hunk below applies to HEAD by construction.

## Defect anatomy measured at HEAD (before any edit)

Read from the frozen `research/20260829/nav-interrupt-1/` artifact (`results.json`,
`episodes.jsonl`, `controls.jsonl`) in the worktree, plus direct probes of the product
functions. This is what the four REFUTED rows actually are:

1. **amend-cue admission 7/14.** Two distinct failures, both product bugs:
   - **5 rows** (`ni1-02/32/33/34/38`) — the interruption fired at `trigger.fired == "terminal"`
     (goal 1 already succeeded/failed), so `begin_goal_amend` answered `nothing_to_amend`
     and the runtime **refused a perfectly good new goal**. An amendment with no parent is a
     NEW plan, not a refusal — this is the card's `new` lineage.
   - **2 rows** (`ni1-01`, `ni1-25`, "actually, go to the owner") — goal 1 suspended, then the
     replacement REFUSED with
     `invalid_argument_value at $.steps[0].arguments: value must be one of ['behind']`.
     Root cause: `_goal_amend_without_planner` builds its retarget frame with
     `route="deliberative_plan"`, so the **system-authored** `sketch_come()` (relation
     `follow`) is validated against the **model-facing** `brain_registry`, whose `follow`
     profile pins `{"behind"}` (`validator.py:800`). The identical sketch is admitted every
     time (14/14) when "come here" arrives as an explicit directive on `direct_skill`.
     **This is live defect 1** ("owner-referring amendment suspends goal 1 and cannot admit
     the replacement — robot parked"), located exactly.
2. **Live defect 2** reproduced at the leaf: `navigation_directive_from_text("after that, go
   to the bench")` → `None`; so does `"wait, go to the bench"`. The shipped door has no queue-cue
   vocabulary, which is why the harness carries a `strip_queue_cue` workaround at its issue door.
3. **Resume is a re-issue**: `_accept_plan:3579` consumes `_amendment_pending` and closes the
   window on the CHILD's commit, so the parent's `ResumeIntent` never survives to a parent resume.

## Bar reachability recorded BEFORE the run (no criterion moves — arithmetic only)

`amended success ≥ 0.8` is read on 28 rows via `success = system_arrival AND scorer_arrival`.
**7 of those 28 rows have `goal_2 == bench`, and bench fails `system_arrival` even FROM REST**
(`controls.jsonl`: both bench controls `sys=False scorer=True cat=authority_disagreement`,
`control_rate 0.0`). So the numerator is capped at 21 and the bar's ceiling is **21/28 = 0.75**
whatever W1 does. That is the NAV-QUALITY / arrival-authority class **card W4 owns**. Recorded
here as a pre-declared ceiling; the row will be reported RED with the measured number and with
`amended_goal_success_scorer_only` beside it as the diagnostic.

## Build (what landed, and where)

**New leaf — `src/parcel_robot/brain/plan_queue.py` (0 hunks; a new file):**

| part | what |
|---|---|
| `QUEUE_CUE_RE`, `strip_queue_cue` | **ported character-for-character** from `research/20260829/nav-interrupt-1/harness.py`. In the harness this was a workaround at the ISSUE DOOR; in the product it is the door. |
| `_LEADING_HESITATION_RE`, `strip_steering_cues` | the card's "actually / wait / instead / after that comes off before grounding". Deliberately NOT a widening of the shipped `closed_intents._GOAL_AMEND` regex — that regex decides whether a turn may SUSPEND work, and "wait," must not acquire that authority just because we want the word stripped. |
| `classify`, `SteeringDecision`, `destination_of` | the **FROZEN** NAV-INT-1 classifier (`queue_policy.py::classify`, 0.827 blind), ported unchanged. `classify_v2` (0.97) is deliberately NOT ported — it is post-hoc and did not earn that number blind. One structural change only: the place vocabulary is a **parameter** instead of `from evals.nav_instruct.scene_truth import derived_landmark_table`, so the leaf carries no dependency on `evals/`. |
| `PlanRecord` / `PlanReceipt` / `PLAN_LINEAGES` / `PLAN_STATES` | the card's record schema: `{plan_id, lineage: new\|revise\|queue\|keep, parent_id, goal, state, receipts[]}`; 11 closed receipt kinds so C4/C5 can switch exhaustively instead of string-matching a detail. |
| `PlanQueue.steer` / `.apply` / `.on_activated` / `.on_terminal` / `.on_resumed` | the POLICY. Pure: it decides and records; the runtime performs the executive calls. |

**`src/parcel_robot/brain/executive.py` — 3 hunks, +36/-0:**

| hunk (HEAD lines) | adjacent to | what |
|---|---|---|
| `@@ -242,0 +243,5 @@` | `TaskExecutive.__init__`, immediately after the `_revision_sinks` loop | `self._plan_observers: list[object] = []` |
| `@@ -274,0 +280,28 @@` | between `_notify_revision_committed` and `submit` | `register_plan_observer` + `_notify_plan_activated`, modelled on the existing `register_revision_sink` / `_notify_revision_committed` pair |
| `@@ -852,0 +886,3 @@` | inside `_activate_replacement`, next to the existing `_notify_revision_committed(record)` call | one call: `self._notify_plan_activated(record)` |

**`src/parcel_robot/runtime.py` — 13 hunks (`-U0`), +234/-6:**

`git diff -U0`, final build:

| hunk (HEAD lines) | adjacent to | what |
|---|---|---|
| `@@ -71,0 +72,9 @@` | the `parcel_robot.brain.plan_sketch` import | import the leaf |
| `@@ -505,0 +515,5 @@` | `AMEND_ROLLBACK_REASON` | `QUEUE_RESUME_REASON` |
| `@@ -2510,0 +2525,11 @@` | immediately after `self.task_executive = TaskExecutive(...)` | build `self._plan_queue`, register it as the executive's plan observer, init `_pending_plan_action` |
| `@@ -3549,0 +3575,6 @@`, `@@ -3553,0 +3585,10 @@` | `_accept_plan`, inside the existing `for row in active_rows` interrupt loop | the queued-parent guard (defect 1 below) |
| `@@ -3563,0 +3605,2 @@` | `_accept_plan`, immediately after the `submission.accepted` raise | **one line**: `self._bind_plan_lineage(plan)` |
| `@@ -4399 +4442,15 @@`, `@@ -4400,0 +4458 @@`, `@@ -4405 +4463,12 @@` | `_apply_goal_amend`, the gate block at the top | consult the policy; `new` / `keep` branches |
| `@@ -4438,0 +4508,156 @@` | between `_apply_goal_amend` and `_amendable_work` | the five helpers: `_steer_goal_amend`, `_active_goal_label`, `_bind_plan_lineage`, `_lineage_matches`, `_resume_queued_parent` |
| `@@ -4698,0 +4924 @@` | `_refuse_amendment` | clear `_pending_plan_action` on rollback |
| `@@ -4786,0 +5013,2 @@` | `_close_amendment_window` | clear `_pending_plan_action` on close |
| `@@ -4914,0 +5143,2 @@` | `_step_brain`, inside the existing terminal-disposition branch | **one line**: `self._resume_queued_parent(result.task_id, disposition.action)` |

**`src/parcel_robot/voice/agent.py` — 6 hunks, +74/-6.** Not an owner-diff file and **clean at the main repo root** (`git diff HEAD --stat -- voice/agent.py` is empty), so no collision. It is the AMENDMENT ADMISSION DOOR the card's build item 2 names.

| hunk (HEAD lines) | adjacent to | what |
|---|---|---|
| `@@ -9,0 +10 @@`, `@@ -44 +44,0 @@` | the import block | import the leaf; `strip_amend_prefix` is no longer imported here (the leaf owns that call now) — `voice/amendment.py` itself is UNTOUCHED (W2 owns it) |
| `@@ -450,0 +451,37 @@` | `handle_text`, right after `parse_closed_intent` | a LEADING queue cue on a directive naming an admitted place is a steering turn and goes through the amendment door |
| `@@ -933,0 +971 @@` | `_handle_goal_amend`, beside the `closed_intent_kind` metric | hand the runtime the transcript its steering policy reads |
| `@@ -936,2 +974,20 @@` | `_handle_goal_amend` | `strip_steering_cues` replaces `strip_amend_prefix` for the residual |
| `@@ -974,0 +1031,5 @@`, `@@ -991 +1052,6 @@` | `_goal_amend_without_planner`, the retarget frame | `route="direct_skill"` (**live defect 1**) and the lineage-chosen speech act |

## Collision report (integrator rule 4 — read this before staging)

`git diff HEAD -- <file>` at the main repo root, 2026-08-30 07:1x.

**`brain/executive.py` — ALL THREE of my hunks land inside Sol's dirty regions.** The dirty
headers are `-18,8` `-125,6` `-224,15` `-241,36` `-283,6` `-302,11` `-332,6` `-350,6` `-358,6`
`-366,6` `-378,17` `-400,13` `-414,17` `-453,89` `-545,95` `-744,13` `-794,6` `-812,6` `-823,35`
`-901,25`, and:

* mine at `-242` and `-274` both fall in `@@ -823,35 @@`'s neighbour `@@ -241,36 @@`, which
  **rewrites `register_revision_sink` and deletes `_notify_revision_committed` outright**;
* mine at `-852` falls in `@@ -823,35 @@`, which **deletes the in-class `_activate_replacement`
  entirely** and rebinds it as `_activate_replacement = _activate_replacement_impl` (a
  module-level function added by the `@@ -18,8 +18,60 @@` hunk).

**This does not BLOCK the card** (rule 1's block condition is "a hook that cannot be written
against HEAD because it needs Sol's hunks" — mine needs none of them, and the patch applies to
HEAD by construction). It is a MERGE hazard, and one of the two is semantic, not textual: if
Sol's diff ever lands, **`self._notify_plan_activated(record)` must be re-applied inside
`_activate_replacement_impl`**, or a deferred replacement will activate with no `plan_accepted`
receipt and C4/C5 will announce nothing. Recorded verbatim so the integrator does not have to
rediscover it.

**`runtime.py` — 1 of 13 hunks overlaps, benignly.** Mine at `-2510` sits in the dirty
`@@ -2508,6 +2525,13 @@`, which inserts `self.execution_narrative = JournalOnly…` at the SAME
anchor (immediately after `TaskExecutive(...)`). Two independent insertions at one anchor; they
merge by concatenation. Every other hunk of mine (`-71`, `-505`, `-3549`, `-3553`, `-3563`,
`-4399`, `-4400`, `-4405`, `-4438`, `-4698`, `-4786`, `-4914`) is clear of every dirty header (`-38,6` `-422,6` `-2196,6` `-2254,6` `-2508,6`
`-2658,6` `-2670,7` `-2685,7` `-3193,7` `-3777,6` `-3803,15` `-3819,7` `-3833,9` `-4950,6`
`-5106,6` `-5331,6` `-5356,6` `-9428,6` `-9545,17` `-9574,6` `-11481,6` `-11855,6` `-17968,20`).
Note `-4914` and the dirty `-4950,6` are 36 lines apart in `_step_brain`'s neighbourhood but do
not overlap.

**`voice/agent.py`, `voice/amendment.py`, `brain/plan_queue.py` — clean at the root; no collision.**
`voice/amendment.py` is W2's OWNS and was **not** edited.

**Intra-wave note for the integrator (not an owner-diff collision): W1 and W2 both touch
`_accept_plan`.** W2's card names a plan-acceptance hook there; W1 has three hunks in that method
— two inside the existing `for row in active_rows` interrupt loop (`-3549`, `-3553`, the
queued-parent guard) and one line after the `submission.accepted` raise (`-3563`). All three are
in the ADMISSION half of the method, before `self._active_nav_revision` is stamped; a narration
hook belongs after the plan is committed, so the two should not touch the same lines. Worth a
five-second look when both patches are staged. `_accept_plan` at HEAD spans 3506–3632 and the
owner's dirty diff has no hunk in that range (nearest are `-3193,7` and `-3777,6`), so neither of
us is fighting the 28-file diff here.

## Acceptance instruments — what the card names vs what exists AT HEAD

The card's unit line names `tests/test_executive*.py` and `tests/test_voice_nav_e2e.py -k amend`.
**Both are DIRTY-TREE artifacts.** At HEAD in a clean worktree:

* `ls tests/test_executive*.py` → **0 files**. The only executive suite at HEAD is
  `tests/test_brain_executive.py`. (`tests/test_executive_revision_atomicity.py`, which other
  sessions are running today, exists only in the uncommitted diff.)
* `tests/test_voice_nav_e2e.py` contains **zero** occurrences of "amend", so `-k amend` selects
  **0 tests** there.

Per rule 1 this is NOT worked around in the dirty tree. The HEAD equivalents were run instead and
are named row by row below; the amendment product path at HEAD lives in
`tests/test_a5_goal_amend.py` and `tests/test_closed_intent_product_path.py`, and those are the
suites `-k amend` was reaching for.

## Ported-not-retrained, verified against the frozen artifact

Read-only replay of the verifier's blind set through BOTH classifiers, in this worktree:

| | value |
|---|---|
| `gold_blind.json` sha256 | `c253df2f707b158c4f6aaab42ce9fae77e98aae9502ef4bea987e2bae1fc1e65` — **matches the card, unchanged** (and `gold_blind.sha256` agrees) |
| `git status --porcelain research/` | empty AT THE TIME OF THE PORT — the classifier was copied out, nothing written back. `run.py`'s `_false_arrival_in_window` was corrected LATER (08:2x) on the coordinator's instruction; see the RED/GREEN section. `harness.py` untouched. |
| frozen `queue_policy.classify` vs ported `plan_queue.classify` | **110/110 label agreement** |
| frozen blind accuracy | 91/110 = **0.8273** |
| ported blind accuracy | 91/110 = **0.8273** — identical, so H-NI1c's number cannot have been moved by the port |

The post-hoc `classify_v2` (0.97) was deliberately **not** ported: it is not a blind number.

## How the tier was run (own sockets, own outputs, frozen folder untouched)

`research/20260829/nav-interrupt-1/run.py` hardcodes `WORKDIR = ~/.cache/parcel-0e/ni1` and writes
its outputs to `HERE` (the frozen folder). Editing either is forbidden, so a wrapper
(`~/.cache/parcel-0e/wb/w1-out/ni1_w1.py`) imports `run.py` unmodified and rebinds exactly two
module globals before `main()`:

* `WORKDIR` → `~/.cache/parcel-0e/wb/w1-sock/` (this card's own short AF_UNIX root; the harness
  also puts `PARCEL_MEMORY_PATH` under it, and `PARCEL_MEMORY_PURPOSE` is unset);
* `HERE` → `~/.cache/parcel-0e/wb/w1-out/` (episodes/controls/sequence/results written to scratch).

`TIER_PATH`, `GOLD_PATH`, `BLIND_PATH`, `BLIND_SHA_PATH` are bound at import and are **not**
rebound — the tier definition and the blind gold set are still read from the frozen folder and the
sha256 is still checked there. Each sim is launched by the harness under
`systemd-run --user --scope -p MemoryMax=12G -p MemorySwapMax=0`, one at a time, with teardown
trapped and the N3 orphan proof scoped to our own pids. The owner's `:8080` / `:8765` /
`/tmp/parcel_sim.sock` are never touched.

## Build freeze for the measured run (one build, start to finish)

A first tier launch at 07:17 was **aborted at episode 3 and discarded** (kept as
`~/.cache/parcel-0e/wb/w1-out/tier-aborted-mixed-build.log`) because a thread-safety fix to
`plan_queue.py` landed at ~07:20, mid-run: episodes 0–2 would have been measured against a
different build from 3–39, and a mixed-build tier is not a measurement. The sims of that run were
killed by pid and verified gone; the owner's `/tmp/parcel_sim.sock` sim and `:8765` panel were
confirmed still running and untouched.

A second launch (07:22:32) was also aborted and discarded
(`tier-aborted-2.log`): writing the product-path tests reproduced a real defect in the
queue path (see below), and fixing it changed `runtime.py`. Rather than argue that the fix
was unreachable from the tier, the run was restarted so that **one build produces every
number on this card**. Both aborted runs' sims were killed by pid and verified gone; the
owner's `/tmp/parcel_sim.sock` sim (pid 807004) and `:8765` panel (807140) were confirmed
alive and untouched after each.

The MEASURED run started **07:29:01** against this final frozen build (`git hash-object`,
in the worktree). No product file is edited after this point:

| file | blob |
|---|---|
| `src/parcel_robot/brain/plan_queue.py` | `c1bcdb6e755bd16f03f5d4c24047eeba1d104967` |
| `src/parcel_robot/brain/executive.py` | `aaba3745779fe0ff88a3737f1ba33e0ebb9b1bb8` |
| `src/parcel_robot/runtime.py` | `804261408960047b46e2c5815564a52339fb5c1b` |
| `src/parcel_robot/voice/agent.py` | `d34866684417e246c56258d2261a8fd8e520d3cd` |
| `tests/test_plan_queue.py` | `6ff3ec5327816dd380753371809fd989b7702ea7` |

Hygiene at the freeze: `ruff check` on all five files → **All checks passed** (the 9 errors in
`ruff check src/parcel_robot/` are the pre-existing baseline fingerprints in
`camera_channel/backends/factory.py` and `detection_adapter/sim_bridge.py`, untouched);
`noqa` added by the diff → **0**; `git diff --stat -- config.py realtime/config.py` → **empty**;
`__pycache__` dropped before the run.

## Two defects found while building, and what was done with each

**1. `_accept_plan` cancels the very parent a `queue` just parked (FOUND, REPRODUCED, FIXED).**
`_accept_plan`'s existing "new explicit owner plan accepted" loop sends
`InterruptRequest(source="correction", requested="at_checkpoint")` to every non-terminal row. In
`executive.request_interrupt` the `correction` source falls to the last branch, and for a record
whose state is not `running`/`waiting_checkpoint` that branch takes `self._cancel(record, ...)`.
A queued parent is `suspended`, so it was **cancelled** — and `_resume_queued_parent` then found it
terminal and dropped the queue's promise in silence.

Predicted from reading `request_interrupt`, then **reproduced on a live runtime** by
`test_the_queued_parent_survives_the_childs_admission`, which failed with

```
AssertionError: the queued parent must stay parked, not cancelled: new explicit owner plan accepted
```

The fix is a guard inside that same loop: skip the row the pending queue action names as this
plan's parent. The test is green at the measured build, and
`test_the_child_going_terminal_hands_the_mission_back_to_the_parent` now drives the whole round
trip on a live runtime — park, admit the child, child terminal, parent resumed with its
`resume_offer` and `plan_resumed` receipts and `last_detail` ending `plan_queue_resume`.

**2. `clarify` must not collapse into `keep` (FOUND AND FIXED before the measured run).**
The first cut of `PlanQueue.steer` mapped the classifier's `clarify` to the `keep` lineage. That
would have taken the C8 HOLD away: a bare "actually…" classifies `clarify`
(`amend_cue_without_a_goal`), and under `keep` the runtime would have answered "I'll keep going
with what I'm doing" to an owner who had just said *no* — and the tier's four `hold` rows, which
admit today on a `suspend` receipt, would all have gone to `admitted=False`. `clarify` now steers
like a revision when there is work in flight (the window opens and the amendment lane answers in
its own words) and stays a `keep` only when there is nothing to hold. Covered by
`test_clarify_holds_the_mission_with_a_parent_and_keeps_without_one` and three `LINEAGE_TABLE`
rows.

Two smaller ones, also fixed before the run and each with a test:
* a queue cue was matched with `search`, so "go to the sidewalk **and then** sit" — a COMPOUND —
  was hijacked out of the no-planner compound lane. Only a **leading** cue holds a directive for
  later (`QUEUE_CUE_RE.match`), which is what the word "after that" means.
* `strip_steering_cues` applied `strip_amend_prefix` in a loop, and `_AMEND_PREFIX` carries
  "the other" among its cues — so "actually, the other one" reduced to the bare noun "one",
  defeating the anaphoric guard in `_goal_amend_without_planner` that is the only thing stopping
  that utterance from becoming a mission. At most one amend strip, never in a loop.

## What the two hardest bars can physically show (measured, before the run; no criterion moved)

Both of these were computed from the FROZEN 2026-08-29 artifact in this worktree, read-only, so
they are properties of the instrument and not of anything W1 did.

### `amended success >= 0.8` has a ceiling of 0.75 that W1 cannot reach past

The bar reads on 28 rows and scores `success = system_arrival AND scorer_arrival`. Seven of those
28 have `goal_2 == bench`, and **bench fails `system_arrival` even from rest**: both from-rest
bench controls in `controls.jsonl` read `sys=False scorer=True cat=authority_disagreement`
(`paired_by_goal.bench.control_rate = 0.0`). The robot arrives; the runtime's own terminal
verification says it did not. The numerator is therefore capped at 21 and the bar's ceiling is
**21/28 = 0.75 < 0.80** whatever the plan queue does. That is the NAV-QUALITY / arrival-authority
class, and it is exactly what **card W4** ("One arrival authority: B32") exists to fix. Reported
RED with the measured number and with `amended_goal_success_scorer_only` beside it — the same
episodes scored on the independent K0 predicate alone, which is the number not penalised by the
product's terminal-verification bug.

### `resume path ratio <= 1.1x` is below this stack's from-rest floor on this scene

`path_ratio_oracle` is `total measured path / a STRAIGHT-LINE oracle` (start → interruption pose →
goal 2 → goal 1, amendment N8). Measure the grid planner's own overhead against a straight line
with **no interruption at all**, from the ten from-rest controls (`path_m / shortest_m`):

| goal | from-rest path / straight line |
|---|---|
| bench | 1.283, 1.279 |
| lamppost | 2.704, 1.796 |
| sidewalk | 1.305, 1.305 |
| towards_lamppost | 1.047, 1.046 |
| come_here | 0.931, 0.929 (the owner closes some of the distance) |
| **mean / median** | **1.363 / 1.281** |

**Reproduced in W1's own controls run** (2026-08-30, same ten from-rest legs, no interruption):
mean **1.442**, median **1.280** — `bench 1.277/1.282`, `come_here 0.931/0.930`,
`lamppost 2.203/3.109`, `sidewalk 1.305/1.305`, `towards_lamppost 1.040/1.041`. The two runs'
MEDIANS agree to three decimals (1.281 vs 1.280); the means differ only because the two lamppost
legs are the noisy pair in both. So the floor is not a one-run artifact: **uninterrupted, from
rest, this stack walks ~1.28x the straight line on this scene.**

Three of the five goals cannot reach 1.1 from rest, uninterrupted, with no queue involved. The
tier's own data says the same thing directly: two of the eight rows the bar reads on are `hold`
rows, where the interruption names no second goal and the robot simply completes goal 1 —
`ni1-23-sidewalk-bench` scores **1.3051**, which is the sidewalk from-rest ratio (1.305) to three
decimal places, and `ni1-39-towards_lamppost-sidewalk` scores **1.0408** against that goal's 1.047.
Those two rows contain **zero** queue cost and one of them already fails the bar.

So `<= 1.1x` against a straight-line reference is not a statement about whether resume is a
re-issue; it is a statement about grid-planning overhead in the demo city, and no plan-queue policy
can move it. The criterion is **not moved** — the row is reported RED with the measured number —
and the queue-vs-re-issue question is reported separately on the evidence that does answer it:
`h_ni1b.queue_actions`, the `resume_offer` / `plan_resumed` receipts, and
`test_queued_child_terminal_resumes_the_parent_without_re_dispatch`, which asserts the resumed
parent's `DispatchRequest` is the SAME `(step_id, attempt, plan_revision)` it was already executing
and that the next `tick()` emits nothing.

## The seam C4 / C5 consume

The typed receipts are reachable in-process as `runtime._plan_queue` — `.receipts` (a bounded list
of `PlanReceipt`), `.record(plan_id)`, `.records()`, and `.snapshot()` which renders the whole
thing as plain dicts. **`runtime.snapshot()` is deliberately NOT given a new key**: several suites
compare its output byte-for-byte and W2 owns the narration side of this wave, so adding a public
field would be a shared-surface change this card has no mandate for. If C4/C5 want it in the
public snapshot, that is a one-line addition on their card with their digests re-pinned.

The eleven kinds are closed (`PLAN_RECEIPT_KINDS`) so a consumer can switch exhaustively:
`plan_admitted`, `plan_accepted`, `plan_queued`, `plan_revised`, `plan_kept`, `plan_suspended`,
`resume_offer`, `plan_resumed`, `plan_completed`, `plan_failed`, `plan_cancelled`. Each carries
`{kind, plan_id, lineage, parent_id, state, detail, goal}` and validates its own vocabulary in
`__post_init__` (`test_receipts_refuse_an_undeclared_vocabulary`).

## Ratchets and hygiene at the measured build

| check | result |
|---|---|
| `ruff check` on all five touched/added files | **All checks passed** (0 findings ⇒ no new ratchet fingerprints) |
| `noqa` added by the diff | **0** |
| `tests/test_dec0_debt_ratchet.py::{test_no_new_oversized_module, test_no_new_long_function, test_no_new_import_cycle}` | **3 passed** |
| `tests/test_decig2_import_ratchet.py` (15 node ids) | **15 passed** — the leaf's `brain → voice.amendment / voice.closed_intents` imports are within the ratchet (precedent: `brain/router.py` already imports `voice.closed_intents`) |
| `config.py`, `realtime/config.py` | untouched (`git diff --stat` empty) |
| `ci_gate.py` | never run by this executor |
| `research/20260829/nav-interrupt-1/` | **parcel-0e's own wave-A folder, not foreign to W1** (coordinator, 08:2x). One hunk in `run.py::_false_arrival_in_window`, +35/-5. `harness.py`, `queue_policy.py`, `gen_tier.py`, the tier JSON and both gold sets: untouched. |
| hosted calls | none — the tier runs `use_llm=False`, $0.00 |

## The deliverable, and a warning about `git diff` alone

`git diff` in the worktree covers only the three MODIFIED files. **Two of the five deliverable
files are new and therefore untracked**, so a plain `git diff` silently omits them:

* `src/parcel_robot/brain/plan_queue.py` (the leaf — the whole policy)
* `tests/test_plan_queue.py` (the card's named test file)

A complete patch is therefore prepared in scratch (no `git add`, no index touched anywhere — the
new-file hunks come from `git diff --no-index /dev/null <file>`):

| | |
|---|---|
| patch | `~/.cache/parcel-0e/wb/w1-out/W1.patch` (107 301 bytes, **includes F1**) |
| sha256 | `8fe1a7a4bad6010239cf945e15c4585f53e97e7b11752d2c38e1fd23ad732f6b` |
| files | `brain/executive.py`, `runtime.py`, `voice/agent.py`, `research/20260829/nav-interrupt-1/run.py`, `brain/plan_queue.py`, `tests/test_plan_queue.py` |

**Final diff stat** (`git diff --stat` + the two untracked files the patch carries):

```
 research/20260829/nav-interrupt-1/run.py |  48 +++++-
 src/parcel_robot/brain/executive.py      |  36 +++++
 src/parcel_robot/runtime.py              | 260 ++++++++++++++++++++++++++++++-
 src/parcel_robot/voice/agent.py          |  74 +++++++++-
 4 files changed, 407 insertions(+), 11 deletions(-)
 + src/parcel_robot/brain/plan_queue.py   845 lines (new)
 + tests/test_plan_queue.py               955 lines (new)
```

`research/20260829/nav-interrupt-1/harness.py` is **untouched by W1** — `git diff --stat` for it is
empty. The false-arrival predicate lives in `run.py`, and the change is a single hunk
(`@@ -872,15 +872,45 @@`) entirely inside `_false_arrival_in_window`.

**Rule 4 pre-verified — the tested state IS the deliverable state.** A second, pristine worktree
was created at HEAD (`git worktree add --detach ~/.cache/parcel-0e/wb/w1-verify c96ac34`), the
patch applied to it and nothing else, and the suites re-run there:

```
git -C ~/.cache/parcel-0e/wb/w1-verify apply --check W1.patch   -> clean, all five files
git -C ~/.cache/parcel-0e/wb/w1-verify apply       W1.patch     -> applied
git status --porcelain  ->  M executive.py  M runtime.py  M agent.py  ?? plan_queue.py  ?? test_plan_queue.py
```

| run in the patch-only worktree | result |
|---|---|
| 296 node ids across 17 suites (the 15 regression suites + both ratchets), **re-run at the FINAL patch including F1** | **442 passed, 2 skipped, 0 failed** (63.3 s) |
| `ruff check` on the five files | **All checks passed** |
| `parcel_robot.__file__` | `~/.cache/parcel-0e/wb/w1-verify/src/parcel_robot/__init__.py` |

The `.parcel` symlink in each worktree is untracked scaffolding and must not be staged.

## Tier result — the 40 episodes (measured build, 07:29:01 → 08:16:11, 0 harness errors)

| | 2026-08-29 baseline (HEAD) | 2026-08-30 (W1) |
|---|---|---|
| instruction admission | 24/32 = **0.7500** | **31/32 = 0.9688** |
| — by family | amend_cue 7/14 · explicit 14/14 · hold 3/4 | **amend_cue 14/14** · explicit 14/14 · hold 3/4 |
| interruptions that produced an amended-goal leg | 21/28 (7 rows `goal_1_continued`) | **28/28 (zero `goal_1_continued`)** |
| amended success, BOTH authorities | 11/28 = 0.3929 | **21/28 = 0.7500** |
| amended success, scorer (K0) only | 14/28 = 0.5000 | **24/28 = 0.8571** |
| success by goal 2 | bench 0/7 · come_here 3/9 · lamppost 3/3 · sidewalk 1/5 · towards_lamppost 4/4 | bench 0/7 · **come_here 9/9** · **lamppost 3/3** · **sidewalk 5/5** · **towards_lamppost 4/4** |
| terminal authority category, amended leg | agreement 15 · disagreement 3 · **false_arrival 3** | agreement 25 · disagreement 3 · **false_arrival 0** |
| collisions (whole episode, all 40) | 0 | **0** (min clearance 0.6593 m) |

**Every goal that CAN verify now verifies on every amended row.** The only shortfall against the
0.8 bar is the seven `bench` rows, which is exactly — to the row — the ceiling recorded before the
run. 21/28 is not "close to" the ceiling; it IS the ceiling.

### The one thing that got worse, and why it is the instrument

`switch_window.false_arrival` went 0 → 3. It is **not** a false arrival. All three are raised by a
**plan_revision 2** receipt:

| episode | receipt raising the claim | rev | detail | distance to goal 1 |
|---|---|---|---|---|
| `ni1-01-bench-come_here` | succeeded | **2** | `owner_follow_verified` | 0.189 m |
| `ni1-13-bench-towards_lamppost` | succeeded | **2** | `navigation_goal_verified` | 0.180 m |
| `ni1-25-sidewalk-come_here` | succeeded | **2** | `owner_follow_verified` | 1.095 m |

`_false_arrival_in_window` (`run.py`) matches `receipt.task_id in ids1 and receipt.state ==
"succeeded"` and applies **no `plan_revision` filter**. `ids1` is goal 1's task id captured at
revision 1 — and the card SPECIFIES `revise` as "`replace` on the same task id at a higher
revision", so after an admitted amendment that same id carries goal **2**. `owner_follow_verified`
is the come-here approach's own verification; it is goal 2 succeeding, scored against goal 1's
polygon. The baseline could not see this because on two of the three rows the amendment was
REFUSED, so no revision 2 ever existed.

The check that settles it, run over all 40 episodes:

```
false arrivals raised by a REVISION-1 (goal-1) receipt: 0
```

Every revision-1 claim in every switch window has `distance_to_goal_1_m = 0.0` and
`false_arrival = false` — the robot really was inside goal 1. And the TERMINAL false-arrival
count, which reads the scored leg rather than the id, went **3 → 0**. Net: no safety row got
worse; one instrument row cannot distinguish a revision it was written before.

**Correction (coordinator, 08:2x): `research/20260829/nav-interrupt-1/` is parcel-0e's own
wave-A folder, not foreign to W1 — C7 and W4-F1 have both edited it this wave. The fix is mine to
make, and it is made.**

`run.py::_false_arrival_in_window` now matches a receipt on **task id AND the revision that owns
goal 1's polygon** (+35/-5, that function only). The owning revision is derived inside the
function from the receipts themselves — the LOWEST revision each id in `ids1` ever produced —
because `replace()` refuses a revision that does not strictly increase, so the minimum is exactly
the revision the id was admitted at. That needs nothing from the caller, so the change stays inside
the one function; an id that produced no receipt cannot establish an owning revision and the
function's existing "fail toward inside — no predicate, no conviction" behaviour stands.

Scope kept as directed: **only** `_false_arrival_in_window`. W4-F1's `GoalSpec._region_for` and its
own `run.py` edits (the K0 region for the bench legs) are different functions in its own worktree;
the merge executor combines them.

### Re-scored offline from the recorded receipts — no sim re-run

`~/.cache/parcel-0e/wb/w1-out/rescore.py` replays the fixed predicate over the recorded
`episodes.jsonl`: every input it needs (full receipt timeline with `plan_revision`, the switch
window bounds, the 1 Hz track, and the K0 region from `harness.GOALS`) is already in the artifact.

| | old id-only rule | fixed rule |
|---|---|---|
| success claims raised inside a switch window | 13 | 10 |
| of those, **false arrivals** | **3** | **0** |

The three dropped claims are exactly the three that were flagged, and all three carry
`plan_revision = 2` (`owner_follow_verified` ×2, `navigation_goal_verified` ×1) — goal 2's own
verification on the reused id. **Every one of the ten surviving revision-1 claims sits at
`distance_to_goal_1_m = 0.0`** — that is the single distinct value across all of them, on all 40
episodes; the robot really was inside goal 1's polygon every time the revision that owns goal 1
said so.

Sanity check reported by the same script: **no** recorded claim's task id fell outside the
independently reconstructed `ids1`, so the reconstruction the re-score uses agrees with what the
live run sampled.

Artifacts: `episodes.jsonl` is left EXACTLY as the run recorded it; the corrected copy is
`episodes_rescored.jsonl` (40 rows, 3 switch-window rows changed, each stamped
`false_arrival_rule: "W1: task id AND the revision that owns goal 1"`), and the aggregate is run
over both so the measured and re-scored numbers can be compared row by row.

**`switch_window.false_arrival` after the fix: 0** — matching the baseline's 0, while the terminal
false-arrival count improves 3 → 0 and collisions stay 0.

### The two live-defect rows, episode by episode

**Live defect 1 — "an owner-referring amendment suspends goal 1 and cannot admit the replacement
(robot parked)". All six rows GREEN**, none was green before:

| episode | 2026-08-29 | 2026-08-30 |
|---|---|---|
| `ni1-01-bench-come_here` | `admit=False rk=suspend refused=True` → `goal_1_continued` | `admit=True rk=replace` → **`amended_goal succ=True`** |
| `ni1-25-sidewalk-come_here` | `admit=False rk=suspend refused=True` → `goal_1_continued` | `admit=True rk=replace` → **`amended_goal succ=True`** |
| `ni1-02-bench-come_here` | `admit=False rk=None ok=False` → `goal_1_continued` | `admit=True rk=new_task` → **`amended_goal succ=True`** |
| `ni1-32/33/34-towards_lamppost-come_here` | `admit=False rk=None ok=False` → `goal_1_continued` | `admit=True rk=new_task` → **`amended_goal succ=True`** |

The two receipt kinds are the two lineages doing exactly what the card specifies: `replace` where
there was a parent to revise, `new_task` where the interruption landed after goal 1 had already
gone terminal. The fifth "nothing to revise" row, `ni1-38-towards_lamppost-sidewalk`, flips the
same way.

**Live defect 2 — "a held queue utterance re-issued verbatim is refused (the cue must be
stripped)". The card's bar is "admits AFTER cue-stripping": 8/8 queue-family re-issues carry
`admitted_work=True`.** `ni1-11-bench-sidewalk` additionally improves `scorer=False → True`; the
three `*-bench` re-issues stay `sys=False scorer=False` on the arrival-authority defect.

**Stated honestly: the tier cannot demonstrate the PRODUCT-side half of defect 2.** Every
queue-family re-issue leg in this run carries `cue_stripped=True` — the frozen harness strips the
cue at its own issue door before calling `handle_text`, which is the workaround it was written
with. So the product never sees the verbatim cue-ed form here, and the tier's 8/8 is the same
number the workaround produced on 2026-08-29. The claim that the *product* now admits
`"after that, go to the bench"` verbatim rests on the live-runtime test
`test_a_leading_queue_cue_parks_the_mission_and_admits_the_next_goal`, which issues exactly that
string through `handle_text` and asserts the reply is not "I did not understand that command",
that `goal_amend_lineage == "queue"`, that the parent's record goes `blocked`, and that the child
is its own task id with the parent recorded as its parent.

---

# RED / GREEN — the card's bars, verbatim

Measured build, one run, 40 episodes + 10 from-rest controls + 10 sequence controls,
07:29:01 → 08:30:49, **0 harness errors**, orphan check `clean=True ours=[]` after every stage.

| # | bar (verbatim from the card) | 2026-08-29 (HEAD) | 2026-08-30 (W1) | verdict |
|---|---|---|---|---|
| 1 | instruction admission **≥ 0.9** | 24/32 = 0.7500 | **31/32 = 0.9688** [0.843, 0.995] | **GREEN** |
| 2 | amended success **≥ 0.8** | 11/28 = 0.3929 | **21/28 = 0.7500** [0.566, 0.873] | **RED** — at the pre-registered ceiling |
| 3 | resume path ratio **≤ 1.1×** | 1.4905 (n=8) | **1.7299 (n=12)** | **RED** — see below; the metric rewards refusing the owner |
| 4a | live defect 1 — owner-referring amendment admits | 0/6 | **6/6** | **GREEN** |
| 4b | live defect 2 — held queue utterance admits after cue-stripping | 8/8 | **8/8** | **GREEN** |
| 5 | `gold_blind.json` sha256 unchanged | `c253df2f…` | **`c253df2f707b158c4f6aaab42ce9fae77e98aae9502ef4bea987e2bae1fc1e65`** | **GREEN** |

Bars the card did not set that moved anyway, reported because they are on the same instrument:

| | 2026-08-29 | 2026-08-30 |
|---|---|---|
| H-NI1b return rate (both goals reachable) | 8/9 = 0.8889 | **13/13 = 1.0000** [0.772, 1.0] |
| interruptions refused, goal 1 continued | 7 | **0** |
| admission receipt kind `None` (no receipt at all) | 6 | **1** |
| terminal false-arrival category, amended leg | 3 | **0** |
| switch-window collisions / clearance ≤ 0 | 0 / 0 | **0 / 0** (min clearance 0.826 m) |
| switch-window false arrivals (fixed predicate, re-scored) | 0 | **0** |
| H-NI1c blind classifier, 110 cases | 0.8273 | **0.8273** — identical, the port changed nothing |

## Bar 2 — RED at exactly the ceiling recorded before the run

21/28 = 0.7500 against ≥ 0.80. The ceiling recorded **before the run started** was 21/28 = 0.75,
and the run hit it exactly. Per goal: `come_here 9/9`, `lamppost 3/3`, `sidewalk 5/5`,
`towards_lamppost 4/4`, **`bench 0/7`**. Every goal that can verify verifies on every amended row;
the entire shortfall is the seven bench rows, whose from-rest control is itself 0/2
(`sys=False scorer=True`, `authority_disagreement`). On the independent K0 predicate alone the
same rows score **24/28 = 0.8571**, i.e. the bar is met once the arrival-authority defect is out
of the way. That defect is **card W4's** (`One arrival authority: B32`). No criterion moved.

## Bar 3 — RED, and the metric is anti-correlated with bar 1

**Denominator, stated:** `path_ratio_oracle` = total measured path ÷ the **straight-line oracle**
(start → interruption pose → goal 2 → goal 1, amendment N8). Not a re-planned path, not a
from-rest path — a straight line through a city with obstacles.

**The population changed, so the two means are not comparable.** 8 rows → 12, and the four new
rows are new *because the fix works*: `ni1-32/33/34-towards_lamppost-come_here` and
`ni1-38-towards_lamppost-sidewalk` all went `goal_1_continued → amended_goal`. Paired on the eight
COMMON rows, seven are identical within ±0.003:

| episode | family | 08-29 | 08-30 | Δ | label |
|---|---|---|---|---|---|
| `ni1-23-sidewalk-bench` | hold | 1.3051 | 1.3036 | −0.001 | hold → hold |
| `ni1-24-sidewalk-come_here` | explicit | 2.0072 | 2.0043 | −0.003 | amended → amended |
| **`ni1-25-sidewalk-come_here`** | **amend_cue** | **1.1661** | **1.8383** | **+0.672** | **`goal_1_continued` → `amended_goal`** |
| `ni1-26-sidewalk-come_here` | hold | 1.2225 | 1.2232 | +0.001 | hold → hold |
| `ni1-27-sidewalk-come_here` | explicit | 2.2530 | 2.2532 | +0.000 | amended → amended |
| `ni1-36-towards_lamppost-sidewalk` | explicit | 1.2823 | 1.2807 | −0.002 | amended → amended |
| `ni1-37-towards_lamppost-sidewalk` | queue | 1.6469 | 1.6473 | +0.000 | uninterrupted → uninterrupted |
| `ni1-39-towards_lamppost-sidewalk` | hold | 1.0408 | 1.0439 | +0.003 | hold → hold |

**The single row that moved is the single row whose behaviour changed** — and it moved because the
robot stopped ignoring the owner. A refused interruption never detours, so it scores *well* against
an oracle that assumed a detour: `ni1-25` scored 1.1661 in the baseline **by disobeying**, and
1.8383 now **by obeying**. This metric pays for refusal, which is the exact behaviour bar 1 exists
to eliminate. Both cannot be satisfied at once by any policy.

**Resume / from-rest quotient** (each episode's oracle ratio ÷ the from-rest floor of the goals it
involves, W1's own controls):

| slice | quotient |
|---|---|
| all 12 rows | mean **1.5809**, median 1.5251 |
| against the single median floor (1.280) | mean **1.3518** |
| **`hold` rows only — an interruption that names no second goal, so zero queue work** | **mean 0.9801** (0.999, 0.938, 1.003) |

The hold rows are the clean read: when there is no detour to perform, the robot's path is its own
from-rest floor to within 2 %. **The plan queue adds no measurable path overhead.** The 1.6–2.3
quotients are all rows that really did drive to goal 2 and back — that is the task the owner asked
for, not overhead. (Caveat stated: `come_here`'s from-rest floor of 0.93 is a flattering
denominator, because from rest the owner walks toward the dog; on an interrupted leg they do not.)

**Nothing was moved.** Bar 3 is RED on its own terms with n=12, mean 1.7299. The evidence that
answers the question the bar was written to ask — *is resume still a re-issue?* — is reported
separately: `h_ni1b.return_rate` 8/9 → **13/13**, the `resume_offer` / `plan_resumed` receipts, and
`test_queued_child_terminal_resumes_the_parent_without_re_dispatch`, which asserts the resumed
parent's `DispatchRequest` carries the SAME `(step_id, attempt, plan_revision)` it was already
executing and that the following `tick()` emits nothing.

## Re-scored aggregate, side by side

`aggregate()` — NAV-INT-1's own function, unchanged — run over both episode files with the same
controls and sequence controls:

| `h_ni1a` field | measured | re-scored |
|---|---|---|
| `false_arrivals_in_switch_window` | 3 | **0** |
| `collisions_in_switch_window_sim_flag` | 0 | 0 |
| `collisions_in_switch_window_clearance_le_0` | 0 | 0 |
| `min_clearance_in_switch_window_m` | 0.8258 | 0.8258 |
| `admission_rate` | 31/32 | 31/32 |
| `amended_goal_success_both_authorities` | 21/28 | 21/28 |
| `amended_goal_success_scorer_only` | 24/28 | 24/28 |
| `amended_goal_false_arrival_category` | 0 | 0 |

Only the one field moves, which is the proof that the predicate fix touches nothing else.
`results.json` = as measured; `results_rescored.json` = with the fixed predicate.

## The frozen inputs, hashed at the end of the run

`git status --porcelain research/` at close is exactly one line — ` M research/20260829/nav-interrupt-1/run.py`. Everything the tier READS is bit-identical to what
2026-08-29 measured against:

| file | sha256 |
|---|---|
| `gold_blind.json` | `c253df2f707b158c4f6aaab42ce9fae77e98aae9502ef4bea987e2bae1fc1e65` — **the card's pinned value** |
| `interrupt_tier_v1.json` | `23466d5ff9e4452e38f0da7f82fcc53019f16efed55208faf191845c33dce541` |
| `harness.py` | `cf3ccd2edfe908cb3306c8a20b0821144faeb9f8b29879eb7d2f99672600f7a2` |
| `queue_policy.py` | `d56c39e83cdb9b93d3ed51705abac4444d01a16ff53cb52272c5a64cd9c40724` |

So the episode SET, the blind gold set, the issue door and the frozen classifier are all unmoved;
the only change in that folder is the false-arrival predicate in the SCORER.

---

# F1 — parcel-6c's lens: the channel and the record must move together

**The defect, as reported and as confirmed.** `_resume_queued_parent` restored the channel from
`_resume_store` FIRST and only then asked the executive to re-bind. On refusal —
`ignored_resources_unavailable` (a foreign lease on the step's resources) or a `None` request — the
code fell straight through to `semantic_tasks.cancel` + `resume_task`, leaving the channel
**already restored and driving over a record that is not `running`**: no verification, no timeout,
no recovery policy behind a moving robot. That is the exact inverse of the false claim of authority
`resume_task_running`'s docstring fails closed to avoid. The fresh dispatch then **started the
mission a second time**.

**The fix, and why this shape.** Not "re-bind first": the shipped RESUME cap already has the
idiom for undoing a restore, five lines of `_apply_closed_intent` —
`_resume_from_store(channel)` → `_resume_parked_tasks(...)` → **on blocked, `_pause_channel(...)`
back**. F1 uses the same one: on refusal the channel is re-paused (which re-records the
`ResumeIntent`, so the parent stays resumable) and only then does the re-queue run. Every
intermediate state is consistent — a paused channel over a queued record — and exactly one later
start happens. Re-binding first would have needed a *new* compensating order and a second way to
undo a half-applied resume; reusing a proven one is cheaper to trust.

`_resume_queued_parent`'s docstring now states the invariant: *the channel and the record move
together or not at all.*

## The tests, and proof they have teeth

| test | what it pins |
|---|---|
| `test_a_restored_channel_is_re_paused_when_the_re_bind_is_refused` | **F1's branch itself.** Real paused navigation channel with a real recorded `ResumeIntent`, real suspended parent record, real plan-queue parent/child link, real foreign lease on `base`. Asserts: channel not driving, **intent back in the store**, record not `running`, **zero dispatches for the parent**. |
| `test_a_refused_rebind_never_leaves_a_channel_driving_over_a_parked_record` | the same two invariants through the **end-to-end product path** (`handle_text` → queue → child terminal → refusal) |
| `test_the_positive_twin_rebinds_in_place_and_starts_nothing` | the twin: lease free ⇒ re-bind happens, `resume_offer` + `plan_resumed` filed, `last_detail` ends `plan_queue_resume`, and **no dispatch for the parent at all** — the proof a re-bind is not a restart |

**Teeth, measured, not asserted.** With the seven-line `_pause_channel` block temporarily removed,
`test_a_restored_channel_is_re_paused_when_the_re_bind_is_refused` **FAILS** on
`assert runtime._resume_store.peek("navigation", ...) is not None` → `assert None is not None` —
the intent had been consumed by the restore and never put back. Restored, it passes. (Recorded
because a regression test that cannot fail is not a regression test.)

**One thing the product-path test does NOT prove, stated plainly.** When parent and child drive the
SAME channel — which is the ordinary queue case — the child's own mission takes the channel over
and the parent's `ResumeIntent` is gone by the time the child goes terminal, so
`_resume_queued_parent` takes its `restored is False` fallback and F1's branch is never reached.
Probed and confirmed in the fixture (`store=None`, `channel.active=True`, directive already
`go to the bench`). That is why the third test builds the restore-then-refuse state directly. F1's
branch is live whenever the parent's channel is not the child's (a parked `follow`/`search` parent
under a navigation child) or whenever the intent otherwise survives.

## Also in F1

`_false_arrival_in_window` now carries the **pinned dependency** the derivation rests on: "the
lowest revision owns goal 1" is only true because `TaskExecutive.replace` refuses a replacement
whose `plan_revision` does not strictly increase (`"replacement revision must increase"`,
`brain/executive.py:365`). If that check is relaxed, or a task id can be re-admitted at a lower
revision, the derivation breaks silently and goal 2's receipts convict goal 1 again.

## F1 hunk adjacency and overlap — 0 overlap with the root's dirty diff

| file | hunks | adjacent to |
|---|---|---|
| `src/parcel_robot/runtime.py` | 2 (+26, −0) | both **inside `_resume_queued_parent`** — the docstring invariant, and the re-pause block between the `return` of the successful re-bind and the `semantic_tasks.cancel` fallback |
| `research/20260829/nav-interrupt-1/run.py` | 1 (+8, −0) | the top of `_false_arrival_in_window`, immediately before `receipts = live.snapshot_receipts()` |
| `tests/test_plan_queue.py` | 2 (+192, −0) | the `import time`, and a new section 8 appended at end of file |

**Overlap: none.** Both `runtime.py` F1 hunks fall inside the block W1 itself ADDED at HEAD
`@@ -4438,0 +4508,182 @@` (the helper methods between `_apply_goal_amend` and `_amendable_work`),
so relative to HEAD they add lines at line 4438 — inside W1's own insertion, touching no
pre-existing line. The root's dirty `runtime.py` hunks anywhere near are at HEAD lines 3777, 3803,
3819, 3833, 4950 and 5106; the nearest is **605 lines away**. The full-file hunk count is unchanged
at 13 because F1 folds into W1's existing added block.

## F1-only diff stat (for the merge executor)

```
 src/parcel_robot/runtime.py                  |   26 ++++++++++++++++++++++++++
 research/20260829/nav-interrupt-1/run.py     |    8 ++++++++
 tests/test_plan_queue.py                     |  192 ++++++++++++++++++++++++++
 3 files changed, 226 insertions(+), 0 deletions(-)
```

Hunks: `runtime.py` `@@ -4612,6 +4612,10 @@` `@@ -4644,6 +4648,28 @@` · `run.py`
`@@ -891,6 +891,14 @@` · `tests` `@@ -9,6 +9,8 @@` `@@ -761,3 +763,193 @@` (all line numbers
relative to the pre-F1 W1 build). Standalone patch:
`~/.cache/parcel-0e/wb/w1-out/F1.patch`, sha256
`8f24ff8b74a3018ffa5a9abd7a708de984677625897a2b58997ef938476934e2`.

## Suites re-run at the F1 build

| | |
|---|---|
| 296 node ids across 17 suites (`test_plan_queue`, `test_brain_executive` — the only `test_executive*` at HEAD — `test_a5_goal_amend`, `test_closed_intent_product_path`, `test_preempt_runtime`, `test_k6_voice_lanes`, `test_p2_dialogue`, `test_a6_stop_local`, `test_agent`, `test_p0c_proposal_flush`, the two navigation-regression files, `test_unknown_place_admission`, `test_owner_and_settle_plans`, `test_superlative_directives`, and both ratchets) | **442 passed, 2 skipped, 0 failed** (65.9 s) |
| `ruff check` on every touched file | All checks passed · `noqa` added: **0** |

## e2e — `tests/test_voice_nav_e2e.py`, whole file

The card names `tests/test_voice_nav_e2e.py -k amend`, which selects **0 tests at HEAD** (the file
contains no occurrence of "amend"), so the whole file was run instead — 17 live sim cases through
`_LiveRuntime`.

**Result: 16 passed, 1 xfailed, 1 FAILED** — `test_sit_next_to_the_lamppost_settles_beside_it_in_a_sit`.

**Correction on the record: the e2e ran TWICE, not once — my orchestration error.** A first
watcher subshell was reported dead by the harness but survived as an orphan, and the detached
`after_tier.sh` queued a second invocation behind it on the guard's suite lock. `guard.log`:

```
08:31:17 START label=W1-e2e  ->  08:43:28 END rc=1     (709.99 s)
08:43:28 START label=W1-e2e  ->  08:55:19 END rc=1     (730.71 s)
```

Both runs produced **identical counts** (`1 failed, 16 passed, 1 xfailed`) and the **same failing
test**, at different end poses (2.930, 1.627 and 3.226, 1.265) — so the two runs corroborate rather
than contradict. They interleaved into one `e2e.log`, which is why that file carries two summary
lines. No sim of mine was left behind (`pgrep` clean), and the owner's sim/panel were never touched.

**The failure is PRE-EXISTING, not a W1 regression — measured across all four cells**, the same
node id, the same byte-identical signature (`states=['failed']`,
`details=['semantic_target_unreachable']`, `blocked_route_gate: obstacle_stop`,
`resolution_state: not_found`) in every one:

| | W1 patch applied | pristine HEAD, no patch |
|---|---|---|
| **no competing sim** | FAIL (e2e run 1, 08:31–08:43) | **FAIL** (08:56, host quiet, verified by `pgrep`) |
| **a second sim running** | FAIL (e2e run 2, 08:43–08:55) | FAIL ×2 (08:47, 08:51) |

The HEAD-and-uncontended cell was run last, deliberately, because the first two HEAD runs happened
to overlap e2e run 2 and contention is exactly what could make a proximity-stop test flake. It
fails there too.

It is a navigation/perception failure — the robot proximity-stops short of the lamppost
(`gate_blocked_steps: 60`, repeated "Proximity stop: obstacle too close", `grounding_outcome:
UNSEEN`, `unreachable_candidates: ['lamp_post_1', 'lamp_post_2']`) — and no W1 path is reachable
from it: the utterance carries no amend cue, and `QUEUE_CUE_RE.match("sit next to the lamppost")`
is `None` (the cue vocabulary's only `next` alternative is `next\s+(?:go|head)\b`, and `match`
anchors at position 0). Its sibling `test_sit_next_to_the_bench_settles_beside_it_in_a_sit` passed.

**Build note:** the e2e ran against the pre-F1 build. F1 changes only `_resume_queued_parent`'s
refusal branch, which no e2e case reaches (no e2e case uses a queue cue, an amendment, or a plan
queue at all), and the 296-node suite set was re-run in full at the F1 build. The e2e is
re-runnable on request if the integrator wants the two states identical on that instrument too.

## Wiring / lane suites (coordinator's F1 list) — and a methodology check

The coordinator's F1 instruction named "the wiring/lane files". `tests/test_executive_preempt.py`
does **not exist** anywhere (neither at HEAD nor in the dirty root), so it cannot be run;
`tests/test_runtime_whisperer_wiring.py` **does** exist at HEAD and had been missed from the
earlier sweeps. Run at the F1 build, with the whisperer and lane files beside it:

| suites | result |
|---|---|
| `test_runtime_whisperer_wiring.py`, `test_realtime_whisperer.py`, `test_whisperer_plan_accepted.py`, `test_realtime_lane.py`, `test_speech_acts.py` (173 node ids) | **220 passed, 0 failed** (5.8 s) |

This is the set that would catch W1's `_accept_plan` hunks disturbing W2's plan-acceptance
whisperer wiring. They do not.

**Methodology check, because the first attempt at this run exposed a flaw in my own tooling.**
Every targeted run on this card enumerated node ids with
`sed 's|def \([a-z_0-9]*\)|...|'` — a lowercase-only character class, which **silently truncates a
test whose name contains a capital**. `test_realtime_lane.py` has exactly such a name
(`test_the_replayed_tail_carries_BOTH_halves_of_the_conversation`) and pytest errored on the
truncated id rather than skipping it quietly, which is how it was caught. All 17 suites from the
earlier sweeps were then re-checked with `grep -cE '^(async )?def test_[A-Za-z_0-9]*[A-Z]'`:
**zero matches in any of them**, so no test was silently dropped from any number reported above.
The enumeration is now `[A-Za-z_0-9]`.
