# A5 C8-FIX — executor status (Opus) · 2026-08-24 · HEAD 31f6869 · NOT COMMITTED

Card: `IMPLEMENTATION_PLAN.md` row A5. Binding spec: `CLAUDE_RESPONSE.md`
Addendum 2 **A8** (supersedes Addendum A1, which supersedes the F2 fix shape).
BUILD_BLOCKER discharged: goal amendment is now a transaction, and the proof
watches the **command stream**, not task state.

Files: `src/parcel_robot/brain/executive.py` (+27), `src/parcel_robot/runtime.py`
(+~480/-55), `tests/test_a5_goal_amend.py` (new, 15 rows). No other file touched.
Zero `noqa`, zero new `# ---- CARD` markers, zero new locks, no new config
section, safety floors / `_finalize_for_actuator` / `apply_reactive_safety`
untouched; git read-only throughout.

## 1. The defect, at the receiver

`VOICE_INTERRUPT_POLICY` had no `goal_amend` key → `_voice_interrupt_action`
fell to `"default": "overlap"` → `request_interrupt` returned
`InterruptDecision("overlap", (), "goal_amend")` → `_apply_goal_amend` discarded
the decision and set `_amendment_pending = True` regardless. An executive-only
task (`MoveRelative`, absent from `PAUSABLE_SKILL_CHANNELS`, so the old body's
navigation/follow/search loop never touched it) kept running **and kept
commanding the body** while its own goal was being revised. Reproduced on the
product path before the fix: three `ControlManager.set_target(source="spatial")`
calls in three ticks, with the record reading `suspended` (see §5, seed 3).

## 2. The policy mapping (executive)

| symbol | value | why |
|---|---|---|
| `GOAL_AMEND_SUSPEND_REASON` | `"goal_amend"` | duplicated from `voice.amendment.AMEND_SUSPEND_REASON` because `brain` must not import `voice`; the regression asserts the two are one string |
| `VOICE_INTERRUPT_POLICY["goal_amend"]` | `"suspend"` | inserted **before** `"explicit_directive"` (the resolver's fallback loop is substring-matched in insertion order) |
| `GOAL_AMEND_FORBIDDEN_ACTIONS` | `frozenset({"cancel_now"})` | A8: cancel destroys the goal being amended |
| `GOAL_AMEND_REFUSED_ACTION` | `"refused_goal_amend_cancel"` | a **refusal**, not a silent downgrade, so the caller can fail closed |

`request_interrupt`'s voice branch now refuses structurally: if the resolved
policy is in `GOAL_AMEND_FORBIDDEN_ACTIONS` and the reason names a goal
amendment, it returns the refusal and cancels nothing — no edit to the table can
make an amendment destroy its own goal. `executive.py` is 938 lines (ceiling
1,000); `request_interrupt` 73 lines (ceiling 100).

## 3. Transaction semantics (runtime)

`_apply_goal_amend` (66 lines) is now a transaction over 15 small helpers, all
under the existing `_command_lock` — the same lock every motion-authoring step
takes, which is why no control tick can interleave with a window.

**Phase order.** `HOLD` → suspend (fallible) → park controllers → verify
quiescence (fallible) → `_amendment_pending = True`.

* **HOLD first, before anything is suspended.** `_engage_amendment_hold`
  cancels the arbiter lease of every targeted motion source, publishes
  `_amendment_hold` (also on `snapshot()["dialogue_state"]["amendment_hold"]`),
  and emits `goal amend HOLD engaged over [...]`. HOLD is a command here: with
  no active intent, `_dispatch_active` has nothing to forward to
  `ControlManager.set_target`.
* **Suspend only, fail closed on the RETURNED decision.**
  `_suspend_for_amendment` requires `action == "suspend"` **and** the task in
  `affected_task_ids` **and** a post-state of `suspended`. Anything else is a
  failure.
* **Controllers, not just records.** `_quiesce_amendment_controllers` pauses
  navigation/follow/search (keeping their `ResumeIntent`) and `preempt`s the
  controllers that carry none (`spatial`). Suspending the executive record
  releases leases; it does not stop a spatial behaviour — that omission was half
  the live defect.
* **Quiescence gates the flag.** `_amendment_not_quiescent` refuses on: a
  channel still driving, `spatial.active`, any resource lease held by a targeted
  task, any targeted task not reading `suspended`, or an arbiter intent whose
  source is a targeted one. `_amendment_pending` is set only after it returns
  `None`.
* **Atomic or rolled back.** On ANY failure: `HOLD` (already on) → `refuse` →
  `rollback` → release HOLD. `_rollback_amendment` restores channels from their
  stored `ResumeIntent` and then picks each task's restore by what happened to
  its controller, exactly as the RESUME cap does (N14): still executing ⇒
  `resume_task_running` + `semantic_tasks.adopt` (a second dispatch would
  cold-start the mission); stopped ⇒ `semantic_tasks.cancel` + `resume_task`
  (fresh dispatch).
* **Commit / abandon.** Commit keeps the existing `_accept_plan` semantics
  (runtime.py ~:3363: `_amendment_pending = False`, `goal_amend_committed`,
  parked rows cancelled by the correction interrupt) and adds
  `_close_amendment_window("committed")` so the HOLD cannot outlive the
  amendment. Abandon is new: `_abandon_goal_amend` is reached from the RESUME
  cap when a window is open — previously that path answered "it's paused by
  something else right now" and stranded the mission behind a window nobody
  could close. The foreign-reason refusal is unchanged for every other reason
  (an owner summons still refuses).

### Journal samples (each step written BEFORE it is taken)

Forced partial failure (two tasks, second suspension refused):

```
1 hold_engage   spatial        planned      8  rollback_task task-a applied:running
2 hold_engage   spatial        applied      9  hold_release  rollback_complete planned
3 suspend       task-a         planned     10  hold_release  rollback_complete applied
4 suspend       task-a         applied
5 suspend       task-b         planned      →  task-a RESUMED (running), task-b never
6 suspend       task-b         failed:overlap  suspended (queued), amendment refused,
7 refuse        task-b:overlap applied         _amendment_pending False throughout
```

Abandon (`"actually…"` then `"resume"`):

```
1-2 hold_engage spatial planned/applied     8  rollback_task task-a planned
3-4 suspend     task-a  planned/applied     9  rollback_task task-a applied:queued
5-6 stop_unpausable spatial planned/applied 10 abandon      owner_resumed applied
7   abandon     owner_resumed planned       11 close        abandoned:owner_resumed
                                            12-13 hold_release abandoned:… planned/applied
```

Commit ends `… 7 close committed applied · 8-9 hold_release committed
planned/applied`.

## 4. Command-stream regression — `tests/test_a5_goal_amend.py` (15 rows)

Every headline row records `ControlManager.set_target` sources (the last
boundary before the actuator) around a real `MoveRelative` executive task
driving the `spatial` source through the real arbiter.

| row | evidence |
|---|---|
| executive-only suspend + stream stops | baseline `["spatial"×3]` in 3 ticks → after amend: state `suspended`, detail `suspended:goal_amend`, `_amendment_pending` True, `_amendment_hold.active` True with `sources == ["spatial"]`, HOLD event emitted, snapshot carries it → **`[]` over 5 ticks**, `arbiter.current()` is `None` |
| HOLD precedes the first suspension | journal `hold_engage` index < `suspend` index; row 1 is `("hold_engage","spatial","planned")` |
| **multi-task forced partial failure** | observed **from inside the window** (the monkeypatched receiver runs while `_command_lock` is held): `pending == [False, False]`, `hold == [True, True]`, `set_target` emitted from inside `== [0, 0]`, `arbiter.current() == [None, None]`; afterwards task-a `running` + `resumed…`, task-b `queued`, reply refuses, `goal_amend_reason == "refused:task-b:overlap"`, HOLD released with `reason == "rollback_complete"` |
| rollback journal | the exact 11-row sequence above, planned-before-applied |
| rolled-back work really drives again | `["spatial"×3]` resumes after the refusal |
| commit | `goal_amend_committed` True, window closed, HOLD off, parked task `cancelled`, exactly one replacement `queued` |
| abandon | `"resume"` → restores: journal `rollback_task…applied:queued`, HOLD off, `_step_brain` re-dispatches to `running`, `["spatial"×3]` again |
| `cancel_now` can never be taken | table seeded to `cancel_now` ⇒ decision `refused_goal_amend_cancel`, `affected_task_ids == ()`, task still `running`; end-to-end the amendment refuses with `refused:task-a:refused_goal_amend_cancel` |
| constants agree | `GOAL_AMEND_SUSPEND_REASON == AMEND_SUSPEND_REASON`; policy maps it to `suspend` |

## 5. Seeded red

In-test seeds (permanent rows): policy key deleted ⇒ refusal with
`refused:task-a:overlap`; decision that does not name the task ⇒
`refused:task-a:suspend`; controller teardown neutered ⇒
`refused:controller_active:spatial`; **`test_seeded_red_c8_defect_reproduced`**
breaks teardown *and* the quiescence gate and asserts the C8 defect returns
(`suspended` record + `["spatial"×3]`) — the anti-vacuity floor for every
"zero commands" row.

Product-file seeds (applied, measured, reverted; `sha256sum -c` verified clean
after each):

| seed | product edit | result |
|---|---|---|
| 1 | drop `GOAL_AMEND_SUSPEND_REASON: "suspend"` from the table | 9 failed / 6 passed |
| 2 | seed 1 + ignore the returned decision + skip the quiescence check | 12 failed / 3 passed |
| 3 | seed 2 + drop the unpausable-controller teardown (**exact pre-fix C8**) | 11 failed / 4 passed — including the headline `…suspends_an_executive_only_task_and_stops_its_commands` |

## 6. Suites

Guard label `a5-c8fix` on every run (`env -u TMPDIR
~/.cache/parcel-guard/pytest_guard.sh --label a5-c8fix …`); never `-n auto`;
`ci_gate --tier` not run (integrator's).

| suite | result |
|---|---|
| `tests/test_a5_goal_amend.py` | 15 passed |
| r24 `test_r24_lock_discipline.py` | passed |
| nominal-stop `test_nominal_stop_wiring.py` | passed |
| nm1 `test_nm1_promotion_and_asks.py` | passed |
| `test_dec0_debt_ratchet.py`, `test_decig2_import_ratchet.py` | passed |
| `test_runtime`, `test_brain_executive`, `test_preempt_runtime`, `test_navigator_pause` | passed |
| `test_closed_intent_product_path`, `test_p2_dialogue`, `test_contracts_v1`, `test_unknown_place_admission`, `test_realtime_ingress`, `test_resume_transaction`, `test_k6_voice_lanes`, `test_p0c_proposal_flush` | passed |
| combined verification set | **553 passed, 1 skipped** |
| whole tree, `pytest tests -q -n 8` | **10,277 passed**, 38 skipped, 3 xfailed, 10 failed, 17 errors — every one of them pre-existing (§6.1) |
| `ruff check` (both product files + the new test) | clean; no baseline fingerprint added |

### 6.1 Pre-existing failures in the whole-tree sweep (none caused here)

Proved by restoring both product files to `git show HEAD:` (working-tree copy,
no git write), re-running, and restoring mine — `sha256sum -c` clean both ways.
The identical set fails at pristine HEAD 31f6869:

| failure | cause |
|---|---|
| `test_person_cell.py::test_deadlock_signature_reproduces_with_an_undeclared_bystander` | reproduces at HEAD |
| `test_search_reground_bench.py` ×3 | reproduces at HEAD |
| `test_v4s_search_cells.py::test_all_four_digest_sentinels…` | `evals/companion/personal_convo_v1/manifest.json` sha `a3d6ff7287de` ≠ pin `d338f3352cd9`; that file is committed and untouched here |
| `test_held_out_scene.py` ×2 (`@pytest.mark.slow`, nightly tier) | `research/20260823/localization-delegation-bench/**` + `tests/test_h7_localization_contract.py` name the held-out scene and are not on `ALLOWED` |
| `test_voice_nav_e2e.py` ×17 **errors** | environmental: `MemoryPathRefused` (card R27) — the suite needs `PARCEL_MEMORY_PATH`, which `ci_gate` sets and a bare `pytest tests` does not. The owner's `parcel_memory.sqlite3` was never opened for writing |

**Zero re-pins.** No DEC-0 registry pin was ported or edited. The changes stay
inside `class RobotRuntime` in `runtime.py` and inside `brain/executive.py`, add
no lock and no lexical lock nesting beyond the already-pinned
`_command_lock → _lock`, and touch none of the seven `ast.unparse`-digested
stop-predicate symbols. Debt ratchet: `executive.py` 938 lines (< 1,000),
longest new function 66 lines (< 100), `# ---- CARD` count unchanged.

**One pre-existing flake observed, not caused here.**
`test_runtime.py::test_runtime_executes_bounded_owner_relative_steps_and_manual_preempts`
failed once under load with `"My LiDAR feed is stale right now"` (a wall-clock
freshness race in that fixture); it passed 3/3 alone and 2/2 as a whole file
immediately afterwards. It touches nothing this card changed.

## 7. Undone, and why

* **The RESUME cap now abandons an open amendment window.** This is a
  deliberate, in-scope behaviour change (A8 requires abandon to restore, and
  nothing else could close a window). The foreign-reason refusal is untouched
  for every other suspend reason. If the owner wants a distinct utterance for
  abandon ("never mind") instead of reusing RESUME, that is a one-line addition
  to the closed-intent grammar and is *not* done here.
* **A refused amendment can cold-start a stopped behaviour.** When the window
  had already parked controllers, rollback re-queues tasks whose controller
  carries no `ResumeIntent` (spatial), so that step restarts rather than
  resumes. That is the existing product contract for those behaviours
  (`_requeue_parked_tasks`); giving spatial a `ResumeIntent` is a separate card.
* **No `activities`/`Gesture` in the targeted-source map.** `ActivitiesChannel`
  publishes under the `voice` arbiter source, so cancelling it would cancel
  unrelated voice motion. Amendment therefore covers the four base-motion
  controllers only (navigation, follow, search, spatial). If a Gesture step must
  be amendable, it needs its own arbiter source first.
* **`_amendment_journal` is not surfaced on `snapshot()`** — only the HOLD is.
  The journal is on `agent.last_brain_metrics["goal_amend_journal"]` after a
  refusal and on `runtime._amendment_journal` after any close; a panel row for
  it was not part of this card.
* **Not committed, not pushed.** Working tree only: two modified product files
  plus one untracked test.
