# RM-2 status — route memory on the product path

Card: `scrum/20260811/task_2/SLAM_M_PLAN.md` (r2), Wave 2, RM-2.
Executor: Claude Opus 5. Date: 2026-08-12. **Not committed.**
Concurrent card: DR-2 on `evals/nav_instruct/**` + `scripts/ci_gate.py` — untouched
by this card (attribution note in §6).

**Revision 2 (2026-08-12) — closing the Fable Wave-2 audit RETURN.** Four
adjudicated findings, all addressed: two code fixes (§4 D6 for finding 1, §4 D7
for finding 2, each with the auditor's own repro re-run before and after), one adjudicated
doc-and-design-record with a pinning test and NO code change (§5.6 finding 3),
and one ownership correction (§6 finding 4). The audit's three no-action notes
are recorded in §7.

---

## 1. Frozen surface consumed (RM-1), and what RM-2 added to it

Consumed verbatim from `RM1_STATUS.md` §1, no amendment requested and none made:

```python
RoutePlaceGraph.record_visit(pose, *, semantic_labels, timestamp_tick,
                             view_embedding, reanchored) -> RouteKeyframe | None
RoutePlaceGraph.reset_track() -> None
RoutePlaceGraph.waypoints_toward(goal_xy, from_xy) -> tuple[RouteKeyframe, ...]
DEFAULT_KEYFRAME_SPACING_M = 0.50      DEFAULT_ATTACH_RADIUS_M = 8.05
```

The load-bearing clause, quoted because every RM-2 branch is written against it:

> The empty tuple is the only failure value and it means "memory has no route" —
> never "maybe"; RM-2 must treat `()` as today's behaviour verbatim, fail-closed.

RM-2's own new surface, in the two files RM-1 named as RM-2's:

| where | what |
|---|---|
| `route_memory/proposer.py` | `PLACE_ROUTE_SOURCE`, `DEFAULT_WAYPOINT_REACHED_M`, `chain_length_m`, `next_waypoint_keyframe`, `waypoint_goal_from_chain` — the chain → **one** stamped `SE2Goal` conversion RM-1 explicitly located here |
| `route_memory/runtime_hook.py` | `RouteMemoryPlaceHook` (session graph + falsifiability counters), `provider_reanchor_count` |
| `navigation/pipeline.py` | the flag, the three mechanisms, the triggers, the flushes |
| `configs/navigation/default.yaml` | `route_memory: false` |

`memory.py`, `teach_repeat.py`, `vpr.py`, `place_graph.py` and
`tests/test_p4_place_graph.py` are **byte-untouched by this card**.

---

## 2. Mechanisms, as built

### (1) AUTO-TEACH — `_route_memory_teach`, called first in `step()`

Every tick of an active mission offers the MAP-frame pose (through
`navigation.base.pose_in`, the sanctioned seam) to a session-scoped
`RoutePlaceGraph`. Labels come from the mission's **resolved** candidate, not
from every phantom in the frustum. It runs **before** the `PoseHealth.LOST`
hold, deliberately: RM-1 refuses a LOST pose and breaks its own track on it, and
that break is exactly what must be recorded, because MAP jumps on recovery.

`reset_track()` at **both** mission boundaries — `start()` and `stop()` — which is
`AUDIT_WAVE1_FABLE.md`'s named failure (§ cross-lane intel: without it the
teleport from one episode's end pose to the next one's start pose is recorded as
a traversal). Pinned by `test_every_mission_boundary_breaks_the_ingest_track`,
which carries its own control: the same teleport with the boundary skipped
produces a `crossed_reanchor` edge, so the assertion is not vacuous.

### (2) BEYOND-REACH TRIGGER — two doors, one deferral

* **(i)** inside `_unroutable_goal_recovery`, **before**
  `_release_unreachable_candidate`. The release is irreversible for the mission
  (a blacklisted candidate can never be re-grounded), so the question has to be
  asked there or it can never be asked.
* **(ii)** `_route_memory_partial_recovery`, on prolonged non-progress while
  `last_route_status == "partial"`. This is the case the card's r2 correction
  named: `RollingGridPlanner.plan` CLIPS a beyond-window goal and reports
  `partial`, which is a healthy status, so the beyond-window case never reaches
  door (i) at all.

At-range vs inside-obstacle (`_route_memory_goal_is_at_range`) requires **both**
readings to say at-range: goal distance > `ROUTE_MEMORY_RANGE_M`, **and** the
planner's own `RoutePlan.planning_target_world != requested_goal_world` when it
exposes one. A goal inside the window that is still unroutable is buried in an
inflated obstacle; memory has nothing to say about that and those keep today's
release path exactly.

Both doors run through **one** function, `_route_memory_defer_release`, which is
the whole answer to "is the release suspended right now?" — see §4 D1/D2.

### (3) CONSUMPTION — proposal, arbitration, interim target

`_publish_route_memory_waypoint` is the **only** writer of
`_route_memory_target`. It stamps the proposal with the pipeline's active
`(task_id, plan_revision)` (the lock-on precedent), publishes it into the shared
`ProposerBus` so the P0-C flush can reach it, sets the arbiter's plan step, and
resolves. It writes an interim target **only** when
`chosen.source == proposed.source`. The goal's `waypoints` carry the whole
`start..target` slice, so `GoalArbiter`'s lethal veto is evaluated over every
intermediate point of the leg, not just its tip.

The winner becomes a `GoalPose` handed to the navigator inside a **proxy**
`Mission`. `self.mission` is never written: its `goal` is still the committed
approach pose, `metadata["arrival_goal_region"]` is still K0's region built from
the true target, and `_inside_arrival_goal_region` — evaluated by `step()`
against the real mission on every tick, chain ticks included — remains the only
thing that can claim an arrival. Reaching a waypoint returns
`MidLevelCommand(stop=False, note="route_memory_waypoint_reached")`.

**Measured, not asserted:** in the gate-(b) corridor run the mission arrives at
tick 440 at (2.44, 10.96) — its own approach pose — *while the live waypoint was
still (0.0, 11.0)*. The arrival was decided by the mission's own predicate
against the true goal, mid-chain, with a memory waypoint live. That is the
authority boundary working, observed.

The **hand-back probe** that ends a chain is described in §5.5: it hands the
navigator the TRUE goal and holds it there until the planner has demonstrably
planned FOR that goal, because a status read one tick after a goal change is a
statement about whatever the planner last planned — usually the waypoint.

### (4) FLUSHES — six doors, one revision-neutral, source-scoped withdrawal

`_flush_route_memory_waypoints` drops the chain and the interim target and calls
`_withdraw_route_memory_proposal`, which purges route memory's OWN buffered
proposal under **the task it was published under** (`_route_memory_published_task`,
recorded at publish time — never the live `_active_task_id`, which a correction
may already have re-pointed). It never touches `commit_revision`: doing so from
the pipeline is the measured AF-2 BLOCKING defect (proposer self-commits
`plan_revision + 1`, the runtime restamps lower, the task is vetoed forever).

The withdrawal is SOURCE-scoped. `ProposerBus.flush_task` is task-scoped by
AF-2's design and drops every source's proposal for that task; on a
route-memory-private event no other proposer's goal became invalid, so the
scoped withdrawal is composed from the arbiter's public surface (read the buffer,
flush the task, put everyone else back). `instructnav/arbiter.py` is consumed,
not amended. Both corrections are audit finding 1 — §4 D6, §5.7.

| door | when | reason string |
|---|---|---|
| `set_active_revision` | the active revision key CHANGES — i.e. a correction, **including one that switches task** | `revision_changed` |
| `_flush_lock_on_proposal` | a lock-on refutation | `lock_on_refusal` |
| `_begin_semantic_replan` | the single release funnel (A*, obstacle gate, approach solver, runtime's `release_current_candidate`, the progress watchdog) | `candidate_released` |
| `_route_memory_teach` | the pose provider reports a NEW map correction | `map_reanchor` |
| `_reset_route_memory_track` | mission boundary (`start` / `stop`) | `mission_boundary` |
| `_publish_route_memory_waypoint` | a correction landed between `resolve` and the store | — (fails closed, no target written) |

---

## 3. Derived constants — every one by reference, none tuned to a gate

| constant | value | derivation | pinned by |
|---|---|---|---|
| `DEFAULT_WAYPOINT_REACHED_M` | 0.25 m | `DEFAULT_KEYFRAME_SPACING_M / 2`. RM-1 admits keyframes ≥ 0.50 m apart precisely so their arrival discs do not overlap, so half a spacing is the largest radius for which "the robot is AT this keyframe" is unambiguous. It coincides with `GridPlannerConfig.goal_tolerance_m` because RM-1's spacing derivation *is* `2 × goal_tolerance_m`. | `test_the_waypoint_reached_radius_is_derived_from_rm1s_spacing` |
| `ROUTE_MEMORY_RANGE_M` | 8.05 m | `= DEFAULT_ATTACH_RADIUS_M`, RM-1's own half-window (`161 × 0.10 / 2`). **No second constant**: the same number answers "is the goal out of live-map range" and "has it come back in". | same test, by identity |
| `next_waypoint_keyframe` reach bound | 8.05 m of **recorded path length** | the whole safety argument: bounding the RECORDED length (not the straight line) by half the window guarantees every metre of the remembered leg lies inside one window of live occupancy. A U-shaped corridor puts a keyframe 6 m away in a straight line and 30 m away along the route; aiming at it is memory inventing the shortcut RM-1's router refuses to invent. | `test_property_a_waypoint_leg_never_exceeds_the_recorded_reach` + `test_seeded_a_euclidean_nearest_target_would_break_the_recorded_bound` |
| `ROUTE_MEMORY_STALL_STEPS` | 60 ticks | `= UNROUTABLE_GOAL_STEPS`, deliberately not a new number: the deferral it bounds is a **suspension of exactly that budget**, so it is the same clock. | same test, by identity |
| `GRID_REPLAN_INTERVAL_STEPS` | 5 | mirror of `controller.replan_interval_steps` in every shipping grid model config. Mirrored rather than imported because the pipeline is handed a NAVIGATOR, not a config; the navigator's own attribute is preferred whenever it publishes one. | `test_the_real_grid_navigators_cadence_is_the_one_the_probe_budget_assumes` reads the yaml AND the live `GridNavigator` |
| probe hold budget | 2 × the planner's cadence (10 ticks shipped) | one cadence period is the smallest hold that can contain a plan computed for the probed goal (the planner does not replan because the goal changed); two gives a whole period of slack for the phase the probe happened to be armed on. | `test_the_probe_budget_is_two_of_the_planners_own_cadence_periods` |
| `ttl_s` 2.0 / `priority` 3 / `confidence` 0.8 | — | carried over from `RouteMemoryProposer`'s already-published defaults rather than re-picked. Priority 3 keeps a remembered waypoint strictly below the grounder's committed approach pose (priority 10) in any pool that ever contains both. | — |

### The deferral's bound — corrected (audit finding 3)

The **retirement** bound is derived and holds:
`ROUTE_MEMORY_STALL_STEPS + UNROUTABLE_GOAL_STEPS = 120` ticks — one stall clock
for the chain to prove it is not advancing, plus one `_steps_goal_unroutable`
re-accumulation after the deferral zeroed it. Measured in §5.4: **120 ticks
exactly** from the arming of a chain that never advances to the release.

**What revision 1 of this document got wrong, and the auditor caught.** It framed
that as "one chain per committed instance", and that is **false**.
`_route_memory_spent` is keyed on the candidate id and cleared at every mission
boundary, and — deliberately — the release funnel's own flush
(`_begin_semantic_replan`, reason `candidate_released`) does NOT mark the
instance spent. A 400-tick progress-watchdog replan therefore re-grounds and
re-commits the same candidate and gets a FRESH chain. In a doomed dense-traffic
world the auditor measured the release landing at **t = 865**, not at the
120-tick bound, with two chains armed (`osc_timeline.py`).

**The honest bound**, and the one this document now claims: the deferral only
ever suspends the release while a chain is ADVANCING, and termination is
guaranteed by the **flag-independent** `progress_timeout_steps` (400) ×
`max_semantic_replans` (2) ladder, which route memory neither extends nor resets.
§5.6 records why the "obvious" fix was rejected on measured evidence, and
`test_a_watchdog_replan_re_commits_and_re_arms_by_design` pins the behaviour as
INTENDED so it cannot drift silently.

---

## 4. Defects found in the pre-written implementation, and what was done

A prior session wrote the implementation and was interrupted before any test
existed. Verifying it mechanism by mechanism against the card found five real
defects (D1-D5). Every one is a seam the Wave-2 audit protocol pre-registered.

**Revision 2** adds D6 and D7 — the two upheld findings from the audit that then
ran against the closed card, each reproduced with the auditor's own script before
the fix and re-run after it (§5.5, §5.7).

### D1 (blocking) — the deferred blacklist was a LIVELOCK, not a deferral

`_route_memory_hand_back` retired a chain that stopped advancing, but nothing
stopped the very next unroutable tick from re-querying memory, getting **the
same recorded chain** back (the graph has not changed), re-arming it, and
deferring the release again. The release the deferral suspended never came back:
the mission died on the 400-tick progress watchdog instead of blacklisting the
instance and re-grounding an alternate — strictly worse than the flag-off
behaviour it replaced.

**Fix:** `_route_memory_spent`, a mission-scoped set of committed instance ids,
keyed off the same `metadata["candidate_id"]` slot `_release_unreachable_candidate`
blacklists (so "memory already tried this instance" and "this instance was
released" cannot disagree about which instance they mean). Marked on both
retirements that are not a successful hand-back — `chain_stalled` and
`chain_spent` — and checked at the top of `_arm_route_memory_chain`. Reset with
the track at every mission boundary, because a new directive is entitled to
memory's help even on an instance the previous one could not reach: the robot is
somewhere else by then.

**Reproduced and killed, measured** — §5.4.

### D2 — re-arming a LIVE chain hid its own stall

`_unroutable_goal_recovery` and `_route_memory_partial_recovery` both called
`_arm_route_memory_chain` unconditionally. `_arm_route_memory_chain` sets
`_steps_route_memory_stalled = 0` and `_route_memory_best_remaining_m = None`,
so a chain that had been stalled for 59 ticks had its stall clock reset every
time the unroutable hysteresis came round — the livelock by a second door, and
one D1 alone does not close. `_route_memory_partial_recovery`'s guard was also
the wrong one (`_route_memory_target is not None`), which is False on the single
tick a hand-back probe is in flight, so a probe could be silently overwritten.

**Fix:** one function, `_route_memory_defer_release`, replaces both call sites.
A live chain means "already deferring, do not re-query"; only an absent chain
arms a new one. The partial-recovery guard is now the CHAIN, not the target.
Pinned by `test_an_advancing_chain_is_never_re_armed_and_never_hides_its_own_stall`.

### D3 — a released candidate left its chain driving

`_begin_semantic_replan` is the single funnel every release authority ends up in
(A*, the obstacle gate, the approach solver, the runtime's
`release_current_candidate`). It set `mission.goal = None` and left
`_route_memory_chain` / `_route_memory_target` alive. On the next commit the
pipeline would have driven a waypoint derived for a goal the mission had already
given up.

**Fix:** `_flush_route_memory_waypoints("candidate_released")` in the funnel.
Pinned by `test_a_released_candidate_takes_its_chain_with_it`, which drives the
runtime's own entry point (`release_current_candidate`).

### D4 — a MAP re-anchor left a stale chain live

`RouteMemoryPlaceHook.reanchored_from_provider` computed the provider's own
correction signal and handed it to `record_visit`, but the LIVE chain — a list
of MAP snapshots taken *before* the jump — kept being driven. RM-1 refuses to
ROUTE across a jump for exactly this reason; driving a chain extracted across
one is the same claim through another door.

**Fix:** `_flush_route_memory_waypoints("map_reanchor")` when the provider
reports a new correction. This is also `AUDIT_WAVE1_FABLE.md`'s "prefer
`reanchored=True` from the pose provider's own correction event" acted on, not
merely plumbed. Pinned by
`test_a_map_reanchor_reported_by_the_provider_flushes_the_live_chain`.

### D5 — three telemetry / blast-radius defects, fixed because the counters are the evidence

* `route_memory_flushes` was incremented on every `_flush_lock_on_proposal`
  call, pending chain or not — a count of call sites, not of withdrawals.
* `route_memory_handbacks` was not incremented on the `chain_stalled`
  retirement, the one retirement that matters most.
* `_flush_route_memory_waypoints` purged the SHARED proposer bus even when route
  memory had nothing pending, so the flag reached into other proposers' buffered
  goals on every revision change. It now returns 0 immediately when nothing of
  this card's is pending.

**Not changed** (verified correct, left alone): the soft-import ladder, the
at-range double reading, the proxy-mission consumption, the one-probe-per-chain
hand-back, the stamping, `chain_length_m` / `next_waypoint_keyframe`'s recorded
bound, and every existing docstring's reasoning.

### D6 (audit finding 1, upheld) — the withdrawal keyed off the WRONG task

`set_active_revision` overwrote `_active_task_id` first and only then flushed the
bus **under the new task**. A correction that SWITCHES tasks is reachable in
product — `runtime` re-points the key on every accepted plan, non-nav voice plans
included, and restamps a running navigator — so the old task's
`route_memory_place` proposal stayed buffered, neither stale nor expired, and
still WON `GoalArbiter.resolve` inside its TTL. Reproduced by the auditor's
`rm2_p0c_attacks.py` attack A.

**Fix:** the task a proposal was published under is now RECORDED at publish time
(`_route_memory_published_task`) and every withdrawal keys off that, never off
the live `_active_task_id`. Ordering stops being load-bearing.

Three related upheld minors swept in the same seam:

* **(a) mission boundaries never cleared the bus.** `stop()` + `start()` keep the
  same `(task_id, plan_revision)`, so mission N's waypoint was neither stale nor
  flushed and survived into mission N+1's bus (attack B).
  `_reset_route_memory_track` now goes through `_flush_route_memory_waypoints`.
* **(b) blast radius.** `ProposerBus.flush_task` is TASK-scoped by AF-2's design
   — it drops every source's proposal for that task — so a route-memory-private
  event (`map_reanchor`, `candidate_released`) purged other proposers' live,
  same-revision goals (attack C). `_withdraw_route_memory_proposal` composes a
  SOURCE-scoped withdrawal out of the arbiter's public surface (read the buffer,
  flush the task, put everyone else back). `arbiter.py` is still consumed, not
  amended. `publish` refuses a stale proposal, so the restore can only ever be a
  subset of what was there — never a resurrection.
* **(c) exception ordering.** RM-2's first shape computed
  `(str(task_id), int(plan_revision))` ahead of the assignments, so a
  non-integer revision left BOTH fields untouched where pre-RM-2 it left the task
  id already updated. The pre-RM-2 two-assignment body is restored verbatim and
  the changed-predicate is computed from the stored values afterwards.

A fourth, found while re-running the attacks and fixed with them: **a correction
landing between `resolve()` returning a winner and the pipeline storing it** left
an interim target with no chain behind it (attack F — inert, because
`_route_memory_navigate` refuses to drive without a chain, but an invariant
break). `_publish_route_memory_waypoint` now re-checks the chain and the stamp
before the store and fails closed.

### D7 (audit finding 2, upheld) — the probe read a plan about the WRONG goal

The hand-back probe handed the navigator the true goal for one act and read
`last_route_status` the next tick. That read is not a verdict about the true
goal: `GridNavigator` replans on its own cadence (`replan_interval_steps`, 5 in
every shipping model config) and **never because the goal changed**, and
suppresses replans entirely under a committed detour. So the probe was reading
the cached WAYPOINT plan's status, and a cached `planned` was taken as "the true
goal is routable again".

**Measured consequence** (auditor's `repro_probe_pipeline.py`, 5 cadence phases):
a false hand-back the moment the true goal entered the 8.05 m disc while still
walled off → chain destroyed → re-arm refused (the goal is in range now) →
release + irreversible blacklist → **mission failed at dtg 9.10 m on 5/5 phases**,
in exactly the scenario class route memory exists to win, where the per-tick
stand-in arrived. The gate-(b) suite's own `_CorridorNavigator` replans every
act and is structurally blind to it.

**Fix, entirely in `pipeline.py`** (`grid_navigator.py` is not in OWNS and needed
no edit): `goal_routable` is returned only on a DEMONSTRABLE verdict —

1. the planner publishes a `RoutePlan` whose `requested_goal_world` **is** the
   probed goal (the same field `_route_memory_goal_is_at_range` already reads);
   that ends the hold immediately, or
2. the planner publishes no `RoutePlan` at all **and** the probe has been HELD
   for its full budget — at least two of the shipping cadence's periods of
   consecutive true-goal acts, after which no cadenced planner can still be
   answering about the waypoint.

Anything else is "ask again", and an "ask again" that survives the budget fails
closed to REFUTED. Every path is biased toward KEEPING the chain, which is the
direction that cannot destroy a route the robot has actually driven.

---

## 5. Gate evidence

### 5.1 GATE (a) — flag-off byte-identity

**Half 1: the v4 minival, AF-2's own digest recipe.** Protocol: v4 minival,
`--budget-policy scaled-path-v1`, `--max-steps 200`, `--seed 20260804`, in a
scratch rsync outside the tree, no in-tree ledger row, at this card's FINAL
source state.

```
--mode baseline (the frozen row):
  episode rows byte-equal      25 / 25
  episode_digest               4113607b92c734dfdd46004b6e77baf6575fc2a1c493e5d9dc5a12c6c5490222  (unmoved)
  path-dependent   ee234c63…   reproduced exactly
  path-independent 897d6ce7…   reproduced exactly   (default separators)
  path-independent c172da37…   reproduced exactly   (compact separators)
  episodes payload bfb21cd2…   reproduced exactly
  aggregate sr 0.24 / spl 0.19325925214230982 / collisions 0 / false_arrival 0

--mode candidate (the arm AF-2 §6.2 names):
  report digest (VS-5 recipe)  58aa1aa1643fca94879d4178568662d45c9edacf976689e3c7173ab4dd91358c
                               == AF2_STATUS.md §6.2's value, to the last byte
```

Both arms carry `navigator_flags: []`, i.e. the shipped default, which is
`route_memory: false`.

**Re-proved after the revision-2 audit fixes**, same protocol, same scratch:
baseline rows **25/25 byte-equal**, `episode_digest` unmoved, all three report
digests and the sorted episodes payload reproduced, and the candidate arm's VS-5
digest still exactly `58aa1aa1…`. Structurally this had to hold — every audit fix
lives behind `self._route_memory is not None` except the `set_active_revision`
assignment restructure, which exists precisely to *restore* the pre-RM-2 order —
but it was measured rather than argued.

**Half 2: the `_unroutable_goal_recovery` release path, traced tick for tick.**
`test_flag_off_and_empty_memory_produce_the_same_release_tick_for_tick` runs the
release scenario twice — flag-OFF, and flag-ON with a graph that has been taught
nothing — and compares `(vx, vy, vyaw, stop, note, mission_status, goal_xy)` on
every one of the 65 ticks plus every non-`route_memory*` metadata field. Equal.

This is the strongest available instance of RM-1's `()` contract because the
flag-ON arm is fully live: the committed instance sits at 12.53 m, beyond
`ROUTE_MEMORY_RANGE_M`, so `_route_memory_goal_is_at_range` says at-range and
`routes_queried >= 1` while `routes_found == 0` — memory is really asked, and
really answers empty, on every tick. (The 7.3 m instance
`tests/test_unroutable_goal_release.py` uses is INSIDE the window, where memory
is never consulted and the comparison would be satisfied by an implementation
with no memory in it at all. That was found and corrected while writing this
cell.)

**Structural half:** `test_flag_off_never_enters_a_single_route_memory_branch`
replaces all six RM-2 entry points with tripwires and runs the release scenario
flag-off: zero trips.

### 5.2 GATE (b) — non-vacuity, paired control, DELTA pre-registered

**Substrate.** A scripted U corridor. Free space is three legs around a solid
block; A = (0, 0), B = (0, 11) — **11.0 m apart in a straight line** (the card's
10–12 m band, and beyond the planner's 8.05 m reach) and **27.0 m apart along the
only corridor that connects them**. The robot drives A → B → A on the product
path, so the graph is filled by AUTO-TEACH and by nothing else. The planner
stand-in is a window-limited breadth-first search: one 16.1 m window centred on
the robot, a beyond-window goal clipped to the window along the straight line,
`goal_blocked` / `no_path` when no traversable route exists inside the window.
Motion is integrated from the **returned** (brake-filtered) command.

**Pre-registered before the arms were run** (asserted in the test file itself,
`test_the_corridor_substrate_is_the_one_the_card_specified`):

* `BUDGET = 600` ticks `= round(27.0 m / (0.6 m/s × 0.1 s)) + UNROUTABLE_GOAL_STEPS + 90`
  = 450 travel + 60 proving unroutability + 90 (1.5 × the same hysteresis) for
  the probe, the grounding ladder's opening ticks and the terminal settle.
* `N = UNROUTABLE_GOAL_STEPS = 60` ticks — the minimum advantage that counts.
  Anything smaller could be nothing but flag-ON declining to release for 60
  ticks, which is not navigation.
* Claim: `T_on + N <= BUDGET`, **and** neither control arm arrives at all.

**Measured, three arms, one scenario, one budget:**

| arm | arrived | terminal | final pos | dtg | keyframes | routes found | proposals / wins / vetoes | chain ticks | deferrals |
|---|---|---|---|---|---|---|---|---|---|
| **flag-ON, taught** | **tick 440** | `arrived_verified` | (2.44, 10.96) | **2.44 m** | 44 | 1 | 4 / 4 / 0 | 369 | 1 |
| flag-OFF (control) | — | `semantic_target_unreachable` @ 440 | (0.00, 0.00) | 11.00 m | 0 | 0 | 0 / 0 / 0 | 0 | 0 |
| **flag-ON, untaught** (the paired control) | — | `semantic_target_unreachable` @ 440 | (0.00, 0.00) | 11.00 m | 1 | **0** | 0 / 0 / 0 | 0 | 0 |

`440 + 60 = 500 ≤ 600` ✓. **DELTA = 600 − 440 = 160 ticks ≥ N = 60**, against an
arm that never arrives at all and never moves (0.00 m travelled — the flag-off
arm's problem is not that it is slow).

*(Revision 2: the flag-ON arrival moved 431 → 440 — exactly the 9 extra ticks the
finding-2 probe hold costs. The pre-registered claim is unaffected and was not
re-derived to fit.)*

**The paired control is the load-bearing row.** Flag-ON with the teaching drive
skipped reproduces the flag-OFF outcome *exactly* — same tick, same terminal
note, same blacklist — with `routes_found == 0`. The win comes from the
RECORDED route, not from having the flag on.

Two further non-vacuity cells:
`test_the_taught_route_is_what_flag_on_actually_drove` asserts every interim goal
lies within half a keyframe spacing of the recorded polyline and that the run
visited x > 7 (the east leg, which the straight line from A to B never touches);
`test_the_corridor_run_is_deterministic` runs it twice.

### 5.3 GATE (c) — the lethal veto on a waypoint proposal

| arm | proposals | wins | vetoes | interim target | deferrals | terminal |
|---|---|---|---|---|---|---|
| `lethal_cost` everywhere | 1 | **0** | 1 | `None` | **0** | `semantic_target_unreachable` @ 440 — flag-off's outcome |
| `lethal_cost` only on `3.0 ≤ x ≤ 5.0` (mid-leg, tip clear) | 1 | **0** | 1 | `None` | 0 | same |

The second row is the one that proves the leg is really published: the tip sits
at x ≈ 8.0 in free space, and only the intermediate points touch the lethal band.
Its pure companions:
`test_the_published_waypoint_carries_the_whole_leg_as_waypoints` (every published
point is a recorded keyframe in recorded order) and
`test_seeded_tip_only_waypoints_would_survive_a_lethal_leg` — strip `waypoints`
to just the tip, the pre-hardening shape, and the SAME lethal function **admits**
it. The veto is carried by the waypoints, demonstrated in both directions.

Because a veto returns `False` from `_arm_route_memory_chain`, the release is not
deferred at all: `deferred_releases == 0` and the mission takes today's path on
the same tick.

### 5.4 The LIVELOCK seam (audit-pre-registered) — D1's proof

Same corridor, taught the same way, but the recorded route is **plugged at
x ∈ [3.0, 3.6] after teaching**: memory remembers a route it drove, and something
is standing in it now. Budget 1400 ticks.

| arm | released | terminal note | blacklist | wins | chain ticks | handbacks | deferrals |
|---|---|---|---|---|---|---|---|
| flag-OFF | tick **440** | `semantic_target_unreachable` | `['lamp-b']` | — | — | — | — |
| flag-ON (guard present) | tick **560** | `semantic_target_unreachable` | `['lamp-b']` | 1 | 60 | 1 (`chain_stalled`) | 2 |
| flag-ON, **guard seeded off** | tick 1205 | `navigation_no_progress` | **`None`** | 9 | 540 | 9 | **18** |

* Guard present: **560 − 440 = 120 ticks = the derived bound exactly**, and the
  release comes back to the SAME blacklist entry and the SAME terminal note as
  flag-off. The deferral costs one stall clock plus one hysteresis, once.
* Guard seeded off (`_route_memory_spent` replaced by a set that forgets every
  `add` — literally the pre-fix implementation): the chain is re-armed **nine**
  times, the release **never** happens (`unreachable_candidates` is `None`), and
  the mission dies on the progress watchdog with a different, worse terminal
  reason. That is the livelock, reproduced.

The robot never moves in the guarded arm: the interim waypoint is beyond the new
obstruction, the window search refuses it, and no motion authority is granted.
The planner keeping the veto is visible in the trace, not argued for.

### 5.5 The HAND-BACK PROBE under a cadenced planner (audit finding 2)

Same corridor. The probe fires mid-chain here — the true goal enters the 8.05 m
disc while the block is still between — so a planner whose cached plan is the
WAYPOINT's is exactly the adversarial case. `_CadenceNavigator` is the gate-(b)
stand-in with `GridNavigator`'s ACTUAL replan policy: replan only on its own
5-tick cadence or when it has no plan, never because the goal changed.

| arm | arrived | terminal | dtg | blacklist | hand-back |
|---|---|---|---|---|---|
| per-tick stand-in (reference) | 440 | `arrived_verified` | 2.44 m | none | — |
| cadence phase 0 | 446 | `arrived_verified` | 2.50 m | none | — |
| cadence phase 1 | 445 | `arrived_verified` | 2.50 m | none | — |
| cadence phase 2 | 444 | `arrived_verified` | 2.50 m | none | — |
| cadence phase 3 | 443 | `arrived_verified` | 2.50 m | none | — |
| cadence phase 4 | 447 | `arrived_verified` | 2.50 m | none | — |
| **seeded pre-audit probe** (one tick, believe the cached status) | **never** | ladder spent, searching | 8.15 m | **`['lamp-b']`** | **`goal_routable`** |

The seeded row is the companion proof — one line different
(`_route_memory_probe_verdict` restored to the one-tick read) and the chain is
destroyed on a goal that is in RANGE and not routable, on every phase.

The auditor's own repro, re-run at this state:

```
repro_probe_pipeline.py    BEFORE                                AFTER
  arm FRESH                arrived @519, dtg 2.47                arrived @528, dtg 2.47
  arm CADENCE phase 0..4   FAILED semantic_target_unreachable    arrived @533..537, dtg 2.45
                           dtg 9.10, blacklist ['lamp-b'], 5/5   blacklist None, 5/5
```

Two cells pin the verdict rule against the **REAL** `GridNavigator` at the
shipped cadence, in both directions the audit named:
`test_a_stale_planned_status_is_never_a_hand_back_verdict` (cached `planned` for
an open goal, probed goal behind a window-spanning wall → the verdict is `None`
until the planner replans, then `False`) and
`test_a_stale_blocked_status_is_never_a_hand_back_refusal` (the mirror: cached
`no_path`, probed goal open → `None`, then `True`).
`test_the_real_grid_navigator_does_not_replan_because_the_goal_changed` pins the
mechanism itself on the shipping planner: after a goal swap with the pose and the
scan held constant, at least one tick inside one cadence period still reports
`planned` for the goal the caller is no longer asking about.

### 5.6 The watchdog-replan re-arm — a two-sided decision, recorded (finding 3)

The audit's panel split 1–1 and adjudicated: **do not add the spent-marking.**
Both refuters confirmed the mechanism; the dissenting refuter proved by execution
that the "obvious one-line fix" is a regression.

| world | `_begin_semantic_replan` marks spent? | outcome |
|---|---|---|
| doomed (dense traffic, `osc_timeline.py`) | no (shipped) | release @ **t = 865**, 2 chains armed, `semantic_target_unreachable` |
| recoverable (`refute_fix_cost.py`) | no (shipped) | **ARRIVES @ t = 771, dtg 2.48 m** — the SECOND chain is the one that works |
| recoverable | yes (the "fix") | release @ t = 463, **`semantic_target_unreachable` @ 842, dtg 11.5 m, blacklist `['lamp-b']`** |

So the cost of NOT marking is a doomed world's release postponed from the
120-tick bound to the watchdog cadence; the cost of marking is destroying an
arrival in the adjacent recoverable world. Recorded rather than silently
resolved, with the honest bound restated in §3, the false "one chain per
committed instance" claim struck from the `_arm_route_memory_chain` docstring,
and `test_a_watchdog_replan_re_commits_and_re_arms_by_design` pinning the
behaviour as INTENDED (the funnel flushes, does not spend; the same candidate
re-commits and re-arms; termination still comes from the flag-independent
400 × 2 ladder).

### 5.7 The P0-C interleaving attacks (audit finding 1), re-run

`rm2_p0c_attacks.py`, the auditor's own harness, at this state:

```
                                                       BEFORE     AFTER
A task-switch correction clears the bus                 DEFECT     PASS
B mission boundary clears the bus                       DEFECT     PASS
C map_reanchor flush is scoped to route memory's entry  DEFECT     PASS
D executive-only commit (no restamp)                    PASS       PASS
E correction between arming and publish: fail-closed    PASS       PASS
F mid-publish correction: no orphaned state             DEFECT     PASS
G refusal mid-probe clears chain + probe state          PASS       PASS
```

Attack A's evidence, verbatim from `rm2_attack.py` section E at this state —
route memory's own entry is withdrawn and the OTHER source's entry for the same
old task is deliberately left alone, which is finding 1(b) working:

```
buffered before switch:      {'grounder': ('T1', 1), 'route_memory_place': ('T1', 1)}
chain after switch:          ()   target: None
buffered after task-switch:  {'grounder': ('T1', 1)}
```

(The `FINDING:` line that script prints afterwards is a hard-coded string from
the audit run, not a computed verdict; the dictionaries above are the data.)

Five new cells pin each half:
`test_a_correction_that_switches_task_withdraws_the_old_tasks_waypoint` (with the
seeded companion showing the stranded entry really would have won `resolve`),
`test_a_mission_boundary_withdraws_the_buffered_waypoint_too`,
`test_a_route_memory_private_flush_leaves_other_proposers_buffers_alone` (with
the companion showing the task-wide purge it replaced would have taken the
bystander), `test_set_active_revision_keeps_its_pre_rm2_exception_ordering`
(both flag states), and
`test_a_correction_landing_between_resolve_and_store_leaves_no_orphan`.

### 5.8 GATE (d) — correction mid-chain (AF-2 interleaving EXTENSION)

Three cells added to `tests/test_ve_detection_lock_on.py`, **additive only**,
immediately after `test_flush_task_clears_the_buffer_without_moving_the_ledger`,
against AF-2's own `AF2_TASK_ID` and its own `_committed_and_stamped` reading:

| test | pins |
|---|---|
| `test_rm2_a_correction_mid_chain_flushes_the_pending_waypoints` | a live chain + a buffered `route_memory_place` proposal; `set_active_revision(task, 2)` clears the chain, the target and the buffer entry; `_committed_and_stamped == (0, 0, 2)` — the ledger did NOT move; `_publish_and_resolve(2)` still wins; the mission GOAL is untouched |
| `test_rm2_a_lock_on_refusal_mid_chain_withdraws_the_waypoint_too` | the refutation path withdraws the waypoint, revision-neutrally: `(0, 0, 1)` and the task still resolves |
| `test_rm2_a_real_executive_revision_still_drops_a_stale_waypoint` | P0-C is not weakened by adding a proposer to it: a revision-1 waypoint cannot re-buffer and cannot win after the executive commits 2, and `_route_memory_stale()` reaches the same verdict from the pipeline's own side |

### 5.9 Property tests and their seeded-failure companions

| property | test | seeded-failure companion |
|---|---|---|
| flag-off release is byte-identical | `test_flag_off_and_empty_memory_produce_the_same_release_tick_for_tick` | `test_seeded_memory_makes_the_flag_off_comparison_fail` — a fabricated chain is injected at RM-1's frozen query; the traces MUST diverge and the release MUST be deferred |
| the waypoint leg never exceeds the recorded reach | `test_property_a_waypoint_leg_never_exceeds_the_recorded_reach` (3 chain shapes × every third attach point) | `test_seeded_a_euclidean_nearest_target_would_break_the_recorded_bound` — on a 6 m-across / 30 m-around U, the keyframe a proximity-only proposer would find most attractive is inside the 8.05 m disc and 30 m along the route; the recorded bound rejects it and the emitted tip is provably not it |
| lethal veto covers the leg | `test_a_lethal_cell_on_the_leg_vetoes_the_whole_waypoint_not_just_the_tip` | `test_seeded_tip_only_waypoints_would_survive_a_lethal_leg` |
| the deferral gives the release back | `test_a_chain_that_stops_advancing_gives_the_release_back` | `test_seeded_removal_of_the_spent_guard_reproduces_the_livelock` (§5.4 row 3) |
| a spent chain returns `None`, not a zero-length goal | `test_property_a_spent_chain_returns_none_rather_than_a_zero_length_goal` | in-test control: one keyframe short of the end it still has work |
| the proposal is stamped | `test_property_the_proposal_is_stamped_with_the_callers_revision_key` | in-test control: an UNSTAMPED proposal survives the same correction — the defect stamping exists to prevent |
| mission boundaries break the track | `test_every_mission_boundary_breaks_the_ingest_track` | in-test control: the same teleport with the boundary skipped produces a `crossed_reanchor` edge |
| no re-arm of a live chain | `test_an_advancing_chain_is_never_re_armed_and_never_hides_its_own_stall` | asserts `routes_found` does not move across an explicit `_route_memory_defer_release` call |
| a cadenced planner reaches the same hand-back verdict as a per-tick one | `test_a_cadenced_planner_reaches_the_same_verdict_as_a_per_tick_one` (all 5 phases) | `test_seeded_one_tick_probe_reproduces_the_false_hand_back` — restore the pre-audit one-tick read and the chain is destroyed and the candidate blacklisted |
| a stale plan is never a hand-back verdict, in either direction | `test_a_stale_planned_status_is_never_a_hand_back_verdict` / `test_a_stale_blocked_status_is_never_a_hand_back_refusal`, both on the **REAL** `GridNavigator` at the shipped cadence | `test_the_real_grid_navigator_does_not_replan_because_the_goal_changed` measures the mechanism on the shipping planner, so neither cell is asserting a property of the fixture |
| a task-switching correction withdraws the old task's waypoint | `test_a_correction_that_switches_task_withdraws_the_old_tasks_waypoint` | in-test control: the stranded entry the pre-fix code left behind is resolved and **wins**, so "it is gone" is a claim with teeth |
| a route-memory-private flush is source-scoped | `test_a_route_memory_private_flush_leaves_other_proposers_buffers_alone` | in-test control: the task-wide purge it replaced is run afterwards and takes the bystander |

Authority cells (the audit's second pre-registered hunt):
`test_a_waypoint_never_replaces_the_mission_goal_or_its_arrival_region`,
`test_reaching_a_waypoint_is_not_an_arrival` (the waypoint-reached tick is
non-terminal, the mission is still `running`, and the robot is > 1 m from the
target when it fires — with the case asserted non-vacuous),
`test_a_released_candidate_takes_its_chain_with_it`.

### 5.10 ci_gate

See §8 for the verbatim block.

---

## 6. OWNS compliance

Touched, all inside OWNS:

| file | +/− (this card's share) | note |
|---|---|---|
| `src/parcel_robot/navigation/pipeline.py` | **≈ 918 added** of the file's 2238/19 batch diff | soft import 32, `__init__` 68, the RM-2 method block 760, 58 in scattered guarded call sites. (Revision 1 was ≈ 718; the audit fixes added ≈ 200.) The remaining ≈ 1320 insertions and all 19 deletions are earlier cards' in this shared uncommitted batch. |
| `src/parcel_robot/route_memory/proposer.py` | 198 / 2 | additive block below the pre-existing surface. The 2 deletions are both **import lines gaining names** (`collections.abc` → `+Sequence`, `route_memory.memory` → `+RouteKeyframe`); no pre-existing function, class or default changed |
| `src/parcel_robot/route_memory/runtime_hook.py` | 173 / 1 | same shape — the 1 deletion is `collections.abc` gaining `Iterable` |
| **`src/parcel_robot/route_memory/__init__.py`** | **+18 / −2 of the file's 39/2**, on top of RM-1's audited 21/0 | **enumerated out-of-literal-OWNS note — see below** |
| `configs/navigation/default.yaml` | 13 of 24 / 0 | the `route_memory: false` block. The other 11 are DOC-1's `person_slow_m` divergence note, not this card's. |
| `tests/test_ve_detection_lock_on.py` | **143 added, 1 line modified** of the file's 916/1 batch diff | the RM-2 extension block (139 lines, appended after `test_flush_task_clears_the_buffer_without_moving_the_ledger`) + a 4-line import note. The one modified line is `from parcel_robot.navigation.base import NavObservation` gaining `MidLevelCommand`; **no existing test body, name or assertion was changed**, which is what "extension ONLY" means here. |
| `tests/test_rm2_route_memory_product_path.py` | **NEW**, 1933 lines, 40 cells | 27 at revision 1 + 13 closing the audit |
| `scrum/20260811/task_2/RM2_STATUS.md` | NEW | this file |

**Enumerated note — `src/parcel_robot/route_memory/__init__.py` (audit finding
4, upheld).** Revision 1 of this document attributed the whole of this file's
diff to RM-1 and said "RM-2 opened none of them". **That was wrong**, and it is
corrected here rather than left for a second audit. The Wave-1 audit pinned the
file at **21 insertions / 0 deletions**; it now stands at **39 / 2**, and the
`+18 / −2` delta is RM-2's, made by this card's implementation session:

* the **18 added lines** re-export symbols that did not exist at RM-1's close —
  `DEFAULT_WAYPOINT_REACHED_M`, `PLACE_ROUTE_SOURCE`, `chain_length_m`,
  `next_waypoint_keyframe`, `waypoint_goal_from_chain` (proposer.py), and
  `PLACE_EXTRAS_KEY`, `RouteMemoryPlaceHook`, `provider_reanchor_count`
  (runtime_hook.py) — plus their `__all__` entries;
* the **2 deleted lines are import-block interleaving only**, verified line by
  line against `git diff`: the pre-existing
  `from parcel_robot.route_memory.proposer import (DOES_NOT_PROVE as
  PROPOSER_DOES_NOT_PROVE,)` block is re-emitted two blocks lower, where isort
  puts it once the `place_graph` imports are inserted above. **No existing
  export is altered, renamed or removed**, and `PROPOSER_DOES_NOT_PROVE` still
  appears in `__all__` and still resolves to the same object.

The file is named literally in neither OWNS nor MUST-NOT-TOUCH. It is claimed
here on exactly RM-1's own precedent for the same file (`RM1_STATUS.md` §6):
re-exporting is the completion of "NEW files in the package", and a consumer's
`from parcel_robot.route_memory import ...` needs it. Flagged rather than left
for the audit to find — twice.

**`src/parcel_robot/runtime.py`: in OWNS, NOT edited.** RM-2 needs nothing there
— `set_active_revision` and `release_current_candidate` are already the seams,
and both now flush. `grep -n route_memory src/parcel_robot/runtime.py` returns
nothing; its 212/22 diff is earlier cards' in this batch.

**Untouched, as required:** `instructnav/arbiter.py` (consumed only — the lethal
veto, `flush_task` and `committed_revision` are read, never amended),
`instructnav/scoring.py` / K0, `navigation/collision.py`,
`navigation/reactive_safety.py`, `navigation/grid_planner.py`,
`navigation/grid_navigator.py`, `evals/**`, `scripts/**`, `pose.py`,
`configs/navigation/pose.yaml`, `tests/test_e4_evidence_seams.py`,
`tests/test_person_aware_nav.py`, and every Wave-1 route-memory module
(`memory.py`, `teach_repeat.py`, `vpr.py`, `place_graph.py`) with its test file
`tests/test_p4_place_graph.py` and `tests/test_p4_route_memory.py`.

Three of those Wave-1 files DO show a `git diff` (`memory.py` 68/1,
`teach_repeat.py` 10/0, `tests/test_p4_route_memory.py` 74/0) and
`place_graph.py` / `tests/test_p4_place_graph.py` are untracked. All of THAT is
**RM-1's**, already present in the working tree when this card opened and
enumerated in `RM1_STATUS.md` §2 and §6. RM-2 opened none of those five.
`route_memory/__init__.py` is the exception and is owned above, not here.

**Ruff.** `.parcel/bin/ruff check` over every file this card touched:
`All checks passed`. Seven new fingerprints appeared while writing the test file
(`RUF007` ×3, `RUF046`, `RUF023`, `RUF100`, `PLC3002`) and were **fixed, not
baselined**. Repo ratchet stays `new 0` against `scripts/ci_ruff_baseline.json`.

**DR-2 attribution.** `evals/nav_instruct/runner.py`,
`evals/nav_instruct/run_nav_instruct_v1.py`, `evals/nav_instruct/drift_cells.py`,
`evals/nav_instruct/run_drift_arms.py`, `scripts/ci_gate.py` and
`tests/test_dr2_pose_drift_arm.py` are DR-2's concurrent Wave-2 card. RM-2 **ran**
those runners read-only, from an rsync outside the tree, and edited none of them.
Any red in those files is DR-2's.

---

## 7. does_not_prove

* **The corridor gate is a scripted substrate, not the sim.** The planner
  stand-in is a window-limited breadth-first search that models exactly one
  property faithfully — the planner can only route inside one rolling window —
  and models none of `RollingGridPlanner`'s frontier fallbacks, its inflation,
  its detour commitment or its A* costs. It proves the PIPELINE mechanism: that
  a recorded route is consulted, arbitrated, driven and retired correctly. It
  proves nothing about success rate on the real sim. **RM-3 is the measurement
  card**, and no SR claim is made here.
* **No eval arm ran flag-ON.** `route_memory` is not in the eval runner's
  navigator-override allowlist and that file is DR-2's this wave, so the only
  measured eval evidence is the flag-OFF byte-identity of §5.1. What route
  memory does to the v4 minival, to v4s, or to any live cell is **unmeasured**.
* **Zero real-camera and zero real-localizer evidence.** The place graph is a
  MAP-frame visit log over sim-truth poses; RM-1's own `does_not_prove` stands
  unchanged. A recorded edge is a record that the robot walked there once, and
  nothing re-checks that the corridor is still open — the reactive gate and
  grid_v1 remain the sole motion authority and are what actually keeps the robot
  out of a newly-placed obstacle on a remembered edge.
* **The provider re-anchor path is wired and sim-inert.** `pose.py` publishes no
  correction counter today (§8 handoff 1), so `provider_reanchor_count` returns
  `None` on every shipping provider and the flush in §2(4) can only fire behind
  a provider that grows one. Its evidence is a unit control with a synthetic
  provider, exactly like AF-2's item 4.
* **The waypoint is chosen at the FURTHEST keyframe inside the recorded bound**,
  i.e. at the edge of the window where the planner has the least look-ahead
  margin. That is a deliberate reading of RM-1's derivation, not a measured
  optimum; nothing here compares it to a shorter, more conservative leg.
* **`_route_memory_spent` is NOT "one chain per committed instance"** — see §3
  and §5.6. It is one chain per *commitment*, and the progress watchdog re-commits.
  Within one commitment, if a route that was blocked becomes open again memory
  will not re-offer it; that is the fail-closed direction (it costs a capability,
  never safety). Across watchdog replans it will, deliberately.
* **The lethal veto over a waypoint leg is POINT-SAMPLED** at RM-1's keyframe
  spacing (0.50 m), and it never covers the attach segment between the robot and
  the FIRST keyframe of the leg. That is pre-existing `GoalArbiter` /
  `lethal_veto` behaviour, not something this card introduced or could fix from
  here, and the defence in depth for the gaps is the planner's inflated costmap
  and the reactive gate — which own every velocity regardless. Measured by the
  audit's `rm2_attack.py` B1/B2. A waypoint is an aim point, never a clearance
  claim.
* **A won interim waypoint outlives its 2.0 s TTL.** The TTL bounds the freshness
  of a PROPOSAL at `resolve` time; once a proposal has won, the interim target is
  driven for the whole leg (up to 8.05 m, tens of seconds) with no re-arbitration.
  That is the sanctioned design and is exactly what the grounder's committed
  approach pose already does; it is bounded by the leg length and by every
  hand-back and flush condition in §2, not by the TTL. Measured by the audit's
  `rm2_attack.py` C/D.
* **The priority-3 ordering is verified but vacuous today.** Every `resolve` pool
  the product actually builds is a single-element tuple, so "strictly below the
  grounder's priority 10" has never been exercised by a real contest. It is a
  property of the constant, not of an observed arbitration.
* **A pause is not a mission boundary.** If the robot is moved while paused, the
  track is stitched across the move and RM-1's distance backstop — not an
  authoritative signal — is what flags it.
* **`GoalArbiter.flush_task` still does nothing** (AF-2's own note). The whole
  of the waypoint purge is the `ProposerBus` half.

---

## 8. ci_gate, and handoffs

### 8.1 `scripts/ci_gate.py --tier commit`

Fresh run at this card's FINAL (revision 2) source state,
2026-08-12T06:56:55Z:

```
CI GATE — tier=commit  (2026-08-12T06:56:55Z)
==============================================================================
[  PASS] HARD  ruff                       7 violation(s), baseline 7, new 0
[  PASS] HARD  hard-safety                nav frozen baseline nav-instruct-v1-baseline-v4-20260811T070536Z: collisions=0 false_arrival=0 | mutation panel clean: collisions=0 no_false_arrival=True | mutation panel freshness: committed fields reproduce live = True | follow-bench: 7 row(s), hard_collision_total all 0 = True | walk_with_me: 1/2 row(s) with hard_collision_total, all 0 = True
[  PASS] HARD  frozen-digest-sentinels    4 immutable manifest(s) byte-identical to pin
[  PASS] HARD  latency-tail-ledger        latest row latency-20260810T082415Z-4d83035f: 6 metric series within 1.2x tail ceiling (rows=5, window=5)
[  PASS] HARD  follow-bench-jerk-ratchet  latest shipped row follow-bench-v1-20260811023618Z-93eba090.json: 1.2187 <= 1.46244 (baseline 1.2187 x 1.2)
[  PASS] HARD  model-off-non-inferiority  23 passed in 0.49s
[  PASS] HARD  frozen-digest-integrity    6 passed, 1 warning in 0.33s
[  PASS] HARD  mutation-panel-freshness   2 passed, 3 warnings in 4.28s
[  PASS] HARD  latency-tail               6 passed, 2 warnings in 0.31s
[  PASS] HARD  default-suite              3902 passed, 9 skipped, 36 deselected, 5 warnings in 139.84s (0:02:19)
==============================================================================
RESULT: PASS — every hard gate green.
  elapsed 151.3s
```

**Suite delta, revision 2.** Card-open baseline **3778**. RM-2 now adds **43**:
`tests/test_rm2_route_memory_product_path.py` **40** (27 at revision 1 + 13
closing the audit) and `tests/test_ve_detection_lock_on.py` 32 → 35 (**+3**, the
AF-2 extension). 3778 + 43 = **3821**; the remaining **+81** are DR-2's
`tests/test_dr2_pose_drift_arm.py` (81 cells collected), and DR-2's skip count
moved 9 → 11 → 9 across the two runs — all of it in their files, none in RM-2's.

Revision 1's run, kept for the record:

```
CI GATE — tier=commit  (2026-08-12T06:05:49Z)
==============================================================================
[  PASS] HARD  ruff                       7 violation(s), baseline 7, new 0
[  PASS] HARD  hard-safety                nav frozen baseline nav-instruct-v1-baseline-v4-20260811T070536Z: collisions=0 false_arrival=0 | mutation panel clean: collisions=0 no_false_arrival=True | mutation panel freshness: committed fields reproduce live = True | follow-bench: 7 row(s), hard_collision_total all 0 = True | walk_with_me: 1/2 row(s) with hard_collision_total, all 0 = True
[  PASS] HARD  frozen-digest-sentinels    4 immutable manifest(s) byte-identical to pin
[  PASS] HARD  latency-tail-ledger        latest row latency-20260810T082415Z-4d83035f: 6 metric series within 1.2x tail ceiling (rows=5, window=5)
[  PASS] HARD  follow-bench-jerk-ratchet  latest shipped row follow-bench-v1-20260811023618Z-93eba090.json: 1.2187 <= 1.46244 (baseline 1.2187 x 1.2)
[  PASS] HARD  model-off-non-inferiority  23 passed in 0.51s
[  PASS] HARD  frozen-digest-integrity    6 passed, 1 warning in 0.33s
[  PASS] HARD  mutation-panel-freshness   2 passed, 3 warnings in 4.46s
[  PASS] HARD  latency-tail               6 passed, 2 warnings in 0.30s
[  PASS] HARD  default-suite              3887 passed, 11 skipped, 36 deselected, 5 warnings in 141.09s (0:02:21)
==============================================================================
RESULT: PASS — every hard gate green.
  elapsed 152.9s
```

**Suite delta, attributed.** Card-open baseline (the Wave-1-audited tree)
**3778 passed, 9 skipped**. RM-2 adds exactly **30**:

| file | before | after | + |
|---|---|---|---|
| `tests/test_rm2_route_memory_product_path.py` | — | 27 | +27 (new file) |
| `tests/test_ve_detection_lock_on.py` | 32 (AF2_STATUS §6.1) | 35 | +3 (the AF-2 extension) |

3778 + 30 = **3808**. The remaining **+79** are DR-2's concurrent Wave-2 card:
`tests/test_dr2_pose_drift_arm.py` collects **81** cells and skipped moved 9 → 11
(+2), i.e. 3808 + 81 − 2 = **3887**. RM-2 touched none of DR-2's files.

Every RM-2 cell also passes in isolation:
`188 passed` over the selection
`test_ve_detection_lock_on / test_rm2_route_memory_product_path /
test_unroutable_goal_release / test_p4_route_memory / test_p4_place_graph /
test_p0c_proposal_flush / test_p0c_flush_product_path / test_instructnav_arbiter /
test_next_to_approach_geometry / test_resume_transaction / test_brain_executive`.

### 8.2 Handoffs

1. **`pose.py` has no re-anchor event counter.** `DriftingOdomProvider` performs
   the correction inside `_maybe_correct_map` and publishes nothing.
   `route_memory/runtime_hook.py::provider_reanchor_count` duck-types
   `map_correction_events` / `reanchor_events` and returns `None` otherwise, so
   the moment DR-1's file grows one the preferred signal lights up with no RM-2
   change. `pose.py` is out of this card's OWNS; not added.
2. **`route_memory` is not in the eval runner's navigator-override allowlist.**
   RM-3 needs it to run ON-vs-OFF arms. `evals/nav_instruct/runner.py` is DR-2's
   this wave; this is the one-line handoff.
3. **Cross-session persistence is still OFF.** `RoutePlaceGraph.save/load` exists
   (RM-1) and RM-2 never calls it: the hook's graph is session-scoped, so a route
   is forgotten when the process ends. Owner-gated OPEN item in SLAM_M_PLAN.
4. **The taught graph grows without bound** within a session (44 keyframes for a
   54 m drive at 0.5 m spacing). No pruning, no retention policy. Fine for an
   episode; not fine for a day. Ties to the same OPEN item.
5. **Trigger (ii) has no paired-control gate.** `_route_memory_partial_recovery`
   is exercised by the implementation and reachable, but the corridor substrate's
   beyond-window goal lands on the `goal_blocked` door, so every measured row in
   §5 came through trigger (i). Trigger (ii)'s own non-vacuity is unmeasured and
   is RM-3's to close on a substrate where the clip target is traversable.
6. **The probe hold costs ticks, and the cost is only bounded, not tuned.** The
   hand-back probe now holds the true goal for up to 2 × the planner's cadence
   (10 ticks shipped) once per chain. Measured cost on the gate-(b) corridor:
   +9 ticks (431 → 440). The early exit fires as soon as the planner publishes a
   `RoutePlan` for the probed goal, so on the real `GridNavigator` the typical
   hold is shorter; nothing here measures the distribution.
7. **`GridNavigator` suppresses replans under a committed detour**
   (`_committed_detour_target`), which is the case the probe's fail-closed
   timeout exists for and the reason the timeout answers REFUTED. A planner-side
   "replan because the goal changed" would make the probe exact instead of
   bounded. `navigation/grid_navigator.py` is not in this card's OWNS; filed as
   a handoff, not attempted.
8. **`ProposerBus` has no per-source withdrawal.**
   `_withdraw_route_memory_proposal` composes one out of poll / `flush_task` /
   re-`publish` because `instructnav/arbiter.py` is consume-only for this card.
   A `ProposerBus.withdraw(source)` amendment would make it one call and remove
   the re-publish window entirely; that is the arbiter owner's to make.
