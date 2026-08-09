# Region-instance selection — the fallout card · status

**Date:** 2026-08-07 · **Card:** finish REGION-INSTANCE SELECTION (named unassigned
in [LANE_C_STATUS.md](LANE_C_STATUS.md) non-claim 7 and
[LANE_D_STATUS.md](LANE_D_STATUS.md) "the two reds Lane D leaves behind").
**Entry state:** the Fable arbiter had landed the core an hour earlier and the
default suite carried **15 reds** from the fallout.

**The one-line claim:** the arbiter's core is intact and unreverted, its two new
pose reads are now on the stratum-1 seam, and **all 15 reds are adjudicated —
every one of them category (i)**, verified by driving each case past the new
look-around and observing that the behaviour it exists to check is bit-for-bit
what it always asserted. The default suite goes **15 failed → 1 failed**, and
the one remaining red is a pre-existing Lane D approach defect on a
*non*-interchangeable goal, proven below to be outside this card's code paths.
Three e2e cases that had **never been observed green on any machine state**
now pass and their pins are flipped.

---

## The rulings, as landed (nothing reverted)

| # | ruling | where it lives | state |
|---|---|---|---|
| 1 | interchangeable goals rank by **boundary** distance, not centroid | `instructnav/grounding.py::_region_aware_memory_distance_m`, `navigation/instructnav_recovery.py::_region_aware_distance_m`, `navigation/pipeline.py::_candidate_ground_distance_m` (soft-import fallback dicts only) | untouched |
| 2 | no first-seen-wins commit; ≥2 qualified in one view → commit boundary-nearest, exactly one visible → complete the look-around first | `pipeline._step_scan_behavior` (`interchangeable_scan`), `search.ActiveSemanticSearch.observe` | untouched behaviourally; two pose reads migrated, one comment corrected to what it measurably does |
| 3 | embodied re-freeze 1072 → 1250 and the duplex mirror/hard-pin | `tests/test_embodied_plan_eval.py`, `evals/companion/duplex_v1/run_duplex_v1.py` | untouched, and green |

`interchangeable` is `goal.kind == "region" or goal.superlative == "nearest"` at
every site. Object goals with no superlative take none of these branches — that
fact is load-bearing for the attribution of the one remaining red.

---

## A — pose-seam compliance

The archon rule (`tests/test_pose_authority_archon.py`) flagged **three** new
direct reads, all of them the arbiter's, all in code written this hour. New code
has no legacy excuse, so all three were **migrated, not allowlisted**. The
allowlist is unchanged at 9 sites in 4 files and did not grow.

| file:line | was | is | frame + why |
|---|---|---|---|
| `navigation/pipeline.py:1954` | `(observation.position[0], observation.position[1])` | `robot_map = _pose_in(observation, MAP_FRAME)`, then `.xy` / `.yaw` | MAP — the scan-completion ranking is over world-frame region polygons; it now shares one pose read with the yaw on the next line, which was already on the seam |
| `navigation/search.py:71` | same literal | `pose_in(observation, MAP_FRAME).xy` | MAP — "which instance is nearest" is a world-frame question |
| `navigation/search.py:90` | same literal | `pose_in(observation, MAP_FRAME).xy` | MAP, same reason |

`search.py` takes a **hard** import of `MAP_FRAME`/`pose_in` from `navigation/
base.py`, deliberately unlike `pipeline.py`'s soft one: `V8_REPLACEMENTS`
(`evals/external/barn_v8_policy_bundle.py`) contains only `collision.py` and
`pipeline.py`, so a frozen BARN bundle uses **its own** pre-seam `search.py` and
never imports this file. `grid_navigator.py` needed no guard for exactly the
same reason.

`tests/test_pose_authority_archon.py` — **7 passed**, including
`test_the_migrated_consumers_are_actually_clean` (pipeline is clean again) and
`test_every_migrated_pose_read_names_its_frame`.

**The four `test_pose_consumers` failures were NOT the pose seam.** Verified,
not assumed: all four fail on `mission.status == "arrived"` after a fixed number
of steps, and all four reach their frame assertions first and pass them
(`"odom" in provider.seen` / `"map" in provider.seen` both hold). They share the
single root cause below with the other eleven. In particular
`test_the_stub_controller_is_not_yet_on_the_seam` is **not** a pre-existing
xfail-shaped item — its allowlist claim is intact; only its arrival tick count
moved.

---

## B — per-test adjudication, all 15

**One root cause, measured.** `ActiveSemanticSearch.observe` is called from three
places, and one of them is `pipeline._step_semantic_resolution`'s NAVIGATE
branch — the multi-view confirmation of a candidate the frustum has *already*
resolved. Under ruling 2 an interchangeable goal with a single visible instance
must complete the look-around, so that branch now spins for the search budget
before committing where it used to commit on the second sighting. Every red is
a case that steps a region-goal navigator twice and asserts `mission.goal is not
None`.

**Nothing was blanket-updated.** Each case was driven past the look-around in a
standalone probe *before* its test was touched, and the assertion it exists for
was checked against what the code now does. Had any of them changed, it would be
category (ii) and the implementation would have been the thing that moved.

| # | test | call | evidence |
|---|---|---|---|
| 1 | `test_navigation::test_unknown_sidewalk_uses_bounded_multiview_semantic_search` | **(i)** | after the sweep: first command `semantic_search_scan` with `vyaw>0`, last `MidLevelCommand(note="semantic_target_resolved")`, `poi_id="observed-sidewalk-1"`, `candidate_source="test_semantic_camera"`, `status="running"` — every original assertion, unchanged. The case's own word "bounded" is now asserted explicitly: `len(commands) == 80`. |
| 2 | `test_navigation::test_semantic_region_arrival_requires_robot_inside_region` | **(i)** | after the sweep: stepping to the goal gives `stop`, `status="arrived"`, `resolution_state="verified"` |
| 3 | `test_navigation::test_semantic_region_uses_tight_tolerance_and_rejects_an_outside_arrival` | **(i)** | after the sweep: `arrival_radius_m == 0.12`, road point 0.494 m from the goal (< the old 1.5 m), command not `stop`, `status="running"`, `_semantic_arrival_verified` False |
| 4 | `test_navigation::test_semantic_arrival_waits_for_fresh_measured_stop_feedback` | **(i)** | after the sweep: `semantic_stop_requested` → `semantic_waiting_for_stop_confirmation` → `arrived_verified`, `status="arrived"` — the exact three-tick sequence |
| 5 | `test_semantic_navigation_regressions::test_progress_watchdog_replans_then_fails_closed_instead_of_running_forever` | **(i)** | after the sweep: 10 no-progress steps → `semantic_replan_after_no_progress`, `status="searching"`, `goal=None`, `replan_count=1`; replan resets the search, second sweep, 10 more → `navigation_no_progress`, `status="failed"`. **The watchdog does not fire during the look-around** (it needs a committed goal), so there is no watchdog/sweep interaction defect. |
| 6 | `test_semantic_navigation_regressions::test_terminal_verification_fails_closed_without_measured_stop_feedback` | **(i)** | after the sweep: `semantic_stop_requested` then `terminal_stop_not_confirmed`, `status="failed"` |
| 7 | `test_semantic_navigation_regressions::test_terminal_verification_rejects_stale_semantic_perception` | **(i)** | after the sweep: `semantic_arrival_verification_failed`, `status="failed"`, `terminal_relation_verified is False` |
| 8 | `test_semantic_navigation_regressions::test_terminal_verification_checks_nearest_obstacle_when_lidar_list_is_empty` | **(i)** | after the sweep: same three, identical |
| 9 | `test_headless_city_tasks::…[default-origin]` | **(i)** | instance expectation only — see below |
| 10 | `test_pose_consumers::test_inside_verification_is_unchanged_at_zero_covariance` | **(i)** | after the sweep: `status="arrived"`, `"inside_probability" not in metadata` (the chance constraint still never engages at zero covariance) |
| 11 | `test_pose_consumers::test_a_wide_covariance_at_the_polygon_edge_refuses_the_arrival_claim` | **(i)** | after the sweep: deep-inside σ=0.02 → arrived, p=1.0; edge σ=1.0 → not arrived, p=0.435, threshold 0.9. The whole point of the case survives intact. |
| 12 | `test_pose_consumers::test_grid_v1_the_shipping_controller_reads_odom_while_k0_reads_map` | **(i)** | after the sweep: `odom` seen, `map` seen, `status="arrived"` |
| 13 | `test_pose_consumers::test_the_stub_controller_is_not_yet_on_the_seam` | **(i)** | after the sweep: `map` seen, `odom` **not** seen, `status="arrived"` |
| 14–15 | `test_pose_authority_archon` ×2 | **(i) in form, but fixed in the SOURCE** | the rule was right and the new code was wrong; the three reads were migrated (section A). No test text changed. |

**Category (ii) count: zero.** The card flagged the four terminal-verification
failures as smelling like (ii). They are not: all four fail on `assert
mission.goal is not None`, *before* any terminal-verification assertion runs, and
the terminal-verification behaviour reproduces exactly once a goal exists. The
scan-completion block did not change the path a resolved mission takes, and no
import side effect is involved.

### What changed in the tests, and what did not

Each of the three test files gained one small documented helper —
`_resolve_region_goal(navigator, observation)` — that steps until the goal
commits, bounded by the search budget (80) and raising if it never does. Nothing
else about any case moved. The provenance comment above each helper names the
2026-08-07 region-instance arbitration and says which rule it encodes.

### The headless-city instance expectation, measured

`walk to the sidewalk` from `(0,0,0)` has moved twice, and the row now records
all three states:

| ranking | north `sidewalk` | south `sidewalk_south` | winner |
|---|---|---|---|
| U34 phantom yaw live (pre-2026-08-07) | — | — | north ("more in front" by 15.5° of phantom heading) |
| centroid (Lane D card D-4) | 3.20 m | **3.00 m** | south |
| **boundary (this arbitration)** | **2.20 m** | 2.55 m | **north** |

The expectation goes back to `"sidewalk"`. The south instance keeps its own case
in `safety-rationale-from-road` (from `(0,-1)`, boundary 1.55 m south vs 3.20 m
north — both measures agree there), and Lane D's added `north-of-the-road` case
keeps its coverage from `(0,+1)`. All three parametrisations pass:

| start | target | steps / budget | outcome |
|---|---|---|---|
| `(0,-1,-π/2)` | `sidewalk_south` | 219 / 300 | `arrived_verified` |
| `(0,0,0)` | `sidewalk` | 282 / 400 | `arrived_verified` |
| `(0,+1,+π/2)` | `sidewalk` | 232 / 400 | `arrived_verified` |

---

## C — sweep cost, measured

**The look-around costs 80 ticks = 8.0 s, not 180 ticks / 18 s.** Measured
identically on three independent harnesses (`test_navigation`'s
`_semantic_nav`, a bare `DirectiveNavigator`, and `test_pose_consumers`'
`_region_navigator`): a lone-visible interchangeable goal commits at exactly
`ActiveSemanticSearch.max_steps`.

The reason is worth writing down because the code claimed otherwise. `observe`
ends the sweep on **whichever comes first** — the search budget, or one
revolution at `yaw_rate` on the 10 Hz tick. At the shipping values
(`configs/navigation/default.yaml semantic_search: max_steps 80, yaw_rate 0.35`)
the budget **always** binds first: 80 ticks is 8.0 s and **2.8 rad = 160° of
body rotation, not a full turn**, which would need 180 ticks. The revolution
term is live only for a configuration turning at ≥ 0.79 rad/s. The comment in
`search.py` said "Full sweep = one revolution"; it now says what it measurably
does, with the numbers. **No constant was changed** — raising the budget to buy
a true revolution would move a shipping knob and the frozen physics rows.

### e2e budget: the slow sidewalk case fits, with room

| case | budget (`CASE_DEADLINE_S`) | measured | result |
|---|---|---|---|
| `test_go_to_the_sidewalk_grounds_plans_and_arrives` | 270 s | **32.0 s** (11.9 %) | **PASSED**, live, quiet box, dedicated node-id run |

No e2e case was pushed over budget and no budget was raised. The other live
timings observed this round, for the record: `find the nearest lamppost` 23.0 s,
`run to the nearest lamppost` 21.0 s, `please move onto the sidewalk` 31.0 s,
`walk towards the lamppost` 65.1 s (the failing case — it burns its watchdog,
see below).

---

## D — suite state

`MUJOCO_GL=egl .parcel/bin/python -m pytest tests/ -q` (full default gate,
includes the live `-m slow` e2e block; uncontended box, nothing else running).
Run twice — before and after the three pin flips below:

| run | result | wall |
|---|---|---|
| after the 15 adjudications | `1 failed, 2633 passed, 7 skipped, 6 xfailed, **3 xpassed**` | 1068.6 s |
| **final**, after the pin flips | **`1 failed, 2636 passed, 7 skipped, 6 xfailed`** — no xpasses left | 1067.9 s |

Against the card's entry state of 15 failed. `ruff check` clean on every touched
file.

### The one red, and why it is not this card's

`tests/test_voice_nav_e2e.py::test_walk_towards_the_lamppost_grounds_plans_and_arrives`
— `states=['failed']`, reproduced **4/4** (two full-suite runs, two standalone
runs). It is deterministic, not a live-sim flake.

**It is not caused by the region-instance work, and the argument is a code-path
one rather than a single-run one.** The mission is
`query='lamppost'`, `kind='object'`, `directive_superlative=None` (read off the
live mission metadata), so `interchangeable` is `False` at *every* site the
arbitration touches: `search.observe` takes the old first-confirmed return,
`_step_scan_behavior` takes the old early commit, `resolve_grounding` skips the
stuff-class branch entirely, and `_region_aware_distance_m` /
`_region_aware_memory_distance_m` both fall through to centroid distance for a
candidate with no polygon. This card's edits (three pose reads, all inside
interchangeable-only branches) are unreachable from it.

**What it actually is**, traced live by instrumenting `_commit_semantic_candidate`:

```
COMMIT {'committed': 'lamp_post_2', 'robot': (0.0, 0.0), 'frustum': [('lamp_post_2', 7.3)], 'outcome': 'RESOLVED',    'replans': 0}
COMMIT {'committed': 'lamp_post_2', 'robot': (0.0, 0.0), 'frustum': [('lamp_post_2', 7.3)], 'outcome': 'RESOLVED',    'replans': 1}
COMMIT {'committed': 'lamp_post_2', 'robot': (0.0, 0.0), 'frustum': [],                     'outcome': 'MEMORY_HIT', 'replans': 2}
```

From the spawn pose the **only** lamppost in the frustum is `lamp_post_2` at
7.30 m; `lamp_post_1` (3.16 m) is not visible. Grounding takes the one it can
see, which is the correct frustum→memory order. The robot then **never moves at
all** — start `(0.0, 0.0)`, end `(0.0, 0.0)` after 120 s — and the progress
watchdog fails the mission with `navigation_no_progress` after two replans
(`resolution_state='stalled'`). That is Lane D's declared open red
([LANE_D_STATUS.md](LANE_D_STATUS.md) run-2 table: *"mine, OPEN — same family
(which lamppost / which approach)"*), also observed at Lane C exit, and it lives
in the approach/no-progress family (`navigation/approach.py`,
`pipeline.py`), not in instance selection.

**It is not claimed fixed and it was not touched.** The card's "0 failed" bar is
therefore **not met**: the suite is at 1 failed, and this is the honest reason.

### Three xfails flipped, per their own written protocol

The suite reported 3 `xpassed`. Each was re-run once more as a dedicated
node-id run on a quiet box and passed again (2 independent green observations
each). All three pins named the exact condition for their own removal, and the
condition is now measured, so the pins were removed and replaced with a
provenance comment carrying their history:

| case | pin's own condition | met? |
|---|---|---|
| `test_find_the_nearest_lamppost_selects_and_approaches_the_near_one` | *"RE-RUN AND FLIP once the approach path is green — this pin is a measurement gap, not an accepted defect"* | yes — PASSED ×2, commits `lamp_post_1`, closes > 1 m |
| `test_run_to_the_nearest_lamppost_applies_the_pace_cap_during_motion` | same text; pin recorded *"pace assertions passed; displacement did not"* | yes — PASSED ×2, displacement half now holds |
| `test_paraphrase_move_onto_the_sidewalk_resolves_the_same_way` | *"it flips when the baseline does; do not flip it separately"* | yes — the baseline `test_go_to_the_sidewalk_grounds_plans_and_arrives` is green (32.0 s) |

A fourth pin, `test_paraphrase_head_towards_the_lamppost_resolves_the_same_way`,
also XPASSed on one run and was **deliberately left pinned**: its condition is
*"this case flips when the approach path is green again"*, and its baseline
`test_walk_towards_the_lamppost_grounds_plans_and_arrives` is the one remaining
red. Its own pin already records that it XPASSes alone on an uncontended box
while its baseline fails, and is non-strict for exactly that reason.

The whole e2e file, re-run after the flips: **`1 failed, 12 passed, 3 xfailed,
1 xpassed`** in 969.7 s — the three flipped cases pass as hard gates, and the
only red is the lamppost case below.

These two superlative cases had **never been observed green on any machine
state** (Lane C non-claim 6). The mechanism is the arbitration's: with an
explicit "nearest" the goal becomes interchangeable, so the navigator completes
the bounded look-around instead of committing to `lamp_post_2` — the only
instance in the opening frustum — and finds `lamp_post_1` behind it. That is the
same rule, on the same tick budget, that turned `sidewalk_then_lamppost`
semantically correct.

---

## Residual defects — reported, deliberately NOT fixed

1. **`search.observe` can still commit a first-confirmed instance when ≥2 are
   visible.** The in-view branch is `if interchangeable and len(qualified) >= 2
   and confirmed:` and it minimises over `confirmed`, not over `qualified`. If
   instance A entered the frustum first and has reached
   `required_observations` while a **nearer** B has not yet, A is committed —
   which is first-confirmed-wins in the exact case ruling 2 outlaws. It cannot
   fire when both instances are visible from the same tick (their sighting
   counts advance together), which is why nothing in the suite catches it. The
   one-line change is to keep sweeping until every visible qualified instance is
   confirmed. **Not applied here**: it is a behaviour change on the frozen
   embodied/duplex physics path (ruling 3), no red exposes it, and it is outside
   the reds this card adjudicates. It should be measured against the 1250 row
   before it lands.
2. **The boundary ranking is quantised by `nearest_point_in_region`'s sampler,
   and the sidewalk decision is inside that quantisation.** The function returns
   the nearest point of an **inset sample grid** anchored at `(min_x, min_y)`
   with spacing `max(0.15, min(0.5, span/40))` — 0.4 m for a 16 m sidewalk — not
   the true nearest boundary point. The north polygon's near edge is its `min_y`
   side so it samples exactly (2.20 m, true value 2.20 m); the south polygon's
   near edge is its `max_y` side so the nearest sample lands 0.30 m short
   (2.55 m measured, 2.25 m true). North wins under both the sampled and the
   true measure, so the outcome recorded above is right — but it is decided by a
   **0.05 m true margin measured with a 0.4 m grid**, and the ranking carries a
   systematic bias of up to one grid spacing favouring regions approached from
   their min-x/min-y side. Changing the sampler would ripple into
   `approach.py` and the K0 goal-region geometry; it belongs in its own card.
3. **The `+178 = one full sweep` derivation in the 1250 re-freeze comment is not
   supported by the code as configured.** The number 178 is a real measurement
   (1072 → 1250 across the 5-case embodied suite) and **the row was not moved**,
   per ruling 3. But the legacy sweep it is attributed to is bounded at
   `max_steps = 80`, so no single sweep can cost 178 ticks; 2π/(0.35·0.1) = 180
   is a threshold the shipping configuration never reaches. The comment text was
   left exactly as the arbiter wrote it — rewriting an arbitrated provenance
   note was not this card's call — and the discrepancy is recorded here instead.

---

## Non-claims

1. **The look-around is not a look-around.** It is 160° of body rotation at the
   shipping `yaw_rate`, not a revolution. Combined with the camera FOV it covers
   most but not all of the circle, so "commits the boundary-nearest of
   everything confirmed" means *everything confirmed inside a bounded partial
   turn*, not everything that exists.
2. **Every (i) call is a claim about the assertions in those 15 cases, not
   about the arbitration being right.** What was verified is that the
   watchdog, the three terminal-verification behaviours, the chance-constrained
   inside test, the two frame bindings and the tight-tolerance rejection all
   reproduce exactly once a goal is committed. Whether an 8 s look-around before
   every region goal is the correct product behaviour is a design decision the
   arbitration made, not something this card measured the value of.
3. **No frozen artifact moved.** The 1250 embodied re-freeze and its duplex
   mirror are byte-identical to the arbiter's version, and nothing under
   `evals/` was written.
4. **The remaining red is diagnosed, not fixed.** The diagnosis is one traced
   live run plus two reproductions of the failure; the *cause* of the zero
   displacement (whether `safe_approach_pose` returns `None`, or the body is
   gated) was not isolated, because that is Lane D's approach card.
5. **Three e2e xfails were flipped on two green observations each.** Two
   observations of a live-sim case is enough to satisfy each pin's own written
   re-run instruction; it is not a stability claim. If any of them flakes, the
   pin's history is preserved in the comment that replaced it.
6. **The suite is not green.** 1 failed. It is named, attributed, and reproduced
   three times.

---

## Files touched

| file | change |
|---|---|
| `src/parcel_robot/navigation/search.py` | 2 pose reads → `pose_in(observation, MAP_FRAME).xy`; seam import from `.base`; the sweep-bound comment corrected to the measured 80 ticks / 160° |
| `src/parcel_robot/navigation/pipeline.py` | 1 pose read in the scan-completion block → one `_pose_in(observation, MAP_FRAME)` shared by `.xy` and `.yaw` |
| `tests/test_navigation.py` | `_resolve_region_goal` helper + provenance; 4 cases; the "bounded" case now asserts the bound (80) explicitly |
| `tests/test_semantic_navigation_regressions.py` | same helper + provenance; 4 cases |
| `tests/test_pose_consumers.py` | same helper + provenance; 4 cases |
| `tests/test_headless_city_tasks.py` | `default-origin` expectation back to `sidewalk`, with the three-state history and the boundary/centroid numbers |
| `tests/test_voice_nav_e2e.py` | 3 xfail pins removed per their own protocol, each replaced by a provenance comment |
| `scrum/20260806/task_3/REGION_INSTANCE_STATUS.md` | this file |

**Not touched:** `instructnav/grounding.py`, `navigation/instructnav_recovery.py`,
`tests/test_embodied_plan_eval.py`, `evals/**`, `configs/**`,
`tests/test_pose_authority_archon.py` (the rule was right; the source moved).

---
---

# Follow-up card — the one red, closed: unroutable-goal release

**Date:** 2026-08-07 · **Card:** the last suite red,
`test_voice_nav_e2e::test_walk_towards_the_lamppost_grounds_plans_and_arrives`,
diagnosed above as *"reported, not fixed"* (non-claim 4: *"the cause of the zero
displacement was not isolated"*). **Entry state:** default suite 1 failed,
reproduced 4/4.

**The one-line claim:** the cause is isolated, and it is neither instance
selection nor the approach pose. `safe_approach_pose` returns a perfectly good
`towards` pose for `lamp_post_2`; the **A\* planner then proves that pose has no
traversable cell**, and the grid controller's only answer to that proof is an
in-place yaw, forever. The mission now **releases a commitment the planner has
proved unroutable**, rescans, and commits the alternate. Default suite
**1 failed → 0 failed**, and the last pinned lamppost xfail flips to a hard
gate on three green observations.

---

## The mechanism, isolated

Two instrumented live runs (`--static-city`, `handle_text("can you walk towards
the lamppost")` from spawn), the second wrapping `RollingGridPlanner.plan`.

**1 — the approach pose is fine.** Grounding commits `lamp_post_2` (the only
lamppost in the opening frustum, 7.30 m, across the road) exactly as the rules
above require, and `safe_approach_pose` returns

```
APPROACH {'candidate': 'lamp_post_2', 'cand_xy': (-6.7, -2.9),
          'pose': (-5.6, -2.42, -156.6, 0.2), 'costs': {}}
```

on **every** attempt. No `None`, no proxemic veto (`tracks` is empty in the
static city, so the veto is not even consulted), no traffic ranking. The
`towards` branch of `approach.py` is pure `towards_waypoint` — stop 1.2 m short
along the robot→target ray — and it has no obstacle test at all. Nothing in the
approach/veto family fires.

**2 — the planner refuses that pose, and says exactly why.**

```
{'status': 'goal_blocked', 'note': 'no_traversable_cell_in_goal_region',
 'goal': (-5.6, -2.42), 'tol': 0.2, 'cell': (24, 55),
 'bounds': ((-8.0, -8.0), (8.1, 8.1)), 'inside': True,
 'resolution_m': 0.1, 'inflation_radius_m': 0.42, 'allow_unknown': True,
 'occupied_within_1.2m': [(0.14, (-5.55, -2.55)), (0.28, (-5.35, -2.55)),
                          (0.34, (-5.35, -2.65)), (0.41, (-5.35, -2.75)),
                          (0.49, (-5.35, -2.85)), (0.64, (-5.45, -3.05)),
                          (0.74, (-5.45, -3.15)), (0.83, (-5.05, -3.05)),
                          ...  (1.13, (-6.65, -2.85)), (1.18, (-6.65, -2.95))]}
```

The goal is inside the rolling window and its cell is known-observed. It is
**0.14 m from an observed occupied cell**. `_candidate_goal_cells` searches
`ceil(0.2 / 0.1) = 2` cells around the goal and every one of them is inside the
**0.42 m** footprint inflation, so the candidate set is empty.

The geometry is real, not a mapping artefact. `city_block.xml`:
`bldg_5` is a box at `(-5.5, -4.5)` with half-size `(1.7, 1.4)`, so its north
face is at **y = −3.1**; `sidewalk_south` spans **y ∈ [−3.75, −2.25]**. *The
building stands on the south sidewalk.* The walkable strip in front of
`lamp_post_2` is y ∈ (−3.1, −2.25) — **0.85 m**, narrower than two inflation
radii. The returns at y ≈ −3.05/−3.15, x ∈ [−5.85, −4.95] are that face; the
two at (−6.65, −2.85/−2.95) are `lamp_post_2` itself. The towards-waypoint lands
in the middle of that strip and there is no admissible cell there.

**3 — and the controller's answer to `goal_blocked` is to spin.**
`GridNavigator.act` → `waypoint is None` → `_recovery_command(status)`, which at
the shipping `recovery_reverse_steps = 0` never reaches its reverse branch:
every tick is `grid_recover_scan`, `_last_vx = 0.0`, pure yaw.

```
--- grid_align err=-90.8 route=17 status=planned      pose=(0.00, 0.00, -90.3)
--- grid_align err=-90.9 route=10 status=planned      pose=(0.00, 0.00, -90.2)
--- grid_recover_scan status=goal_blocked   (×190)    pose=(0.00, 0.00, …)
```

x and y never leave `(0.00, 0.00)`; only yaw moves.

**4 — and the watchdog's replan re-commits the same instance.** After
`timeout_steps: 200` the progress watchdog calls `_begin_semantic_replan`, which
re-grounds from the same frustum, re-picks `lamp_post_2`, and re-derives the
byte-identical unroutable pose. Three times, `max_semantic_replans: 2`, then
`navigation_no_progress`.

**Measured before-run:** start `(0.0, 0.0)` → end `(0.0, 0.0)`, **0.00 m over
65.0 s / 647 navigator ticks**, task `failed`/`failed`,
`resolution_state='stalled'`, `replan_count=2`, `candidate_id='lamp_post_2'` on
all three attempts.

So the defect is **not** which lamppost was chosen, and **not** the approach
pose. It is that *the commitment is never released* — the mission cannot act on
a proof it already has.

---

## The fix

`goal_blocked` / `no_path` is **not** a slow-progress heuristic; it is A\*
reporting that the goal region contains no traversable cell. The mission is the
only authority that can act on that, so it now sees it and does.

| piece | where |
|---|---|
| the planner's verdict becomes readable | `GridNavigator.last_route_status` — a read-only property over `_last_plan.status` |
| 60 consecutive unroutable ticks **with zero goal progress** → release | `DirectiveNavigator._unroutable_goal_recovery`, `UNROUTABLE_GOAL_STEPS = 60` |
| the released instance is remembered, per-mission | `_unreachable_candidates`, cleared by `start()` and `stop()` exactly like `FalsePositiveMemory` |
| and cannot come back through any door | `_ExcludingSemanticMap` wraps the map handle given to `ActiveSemanticSearch.observe` and the ScanBehavior branch; `_memory_candidates` filters at its own return |
| then the existing ladder runs | `_begin_semantic_replan(note="semantic_replan_after_unroutable_goal")` — same reset, same budget, no new machinery |

**Why 60 ticks and why the progress guard.** 6.0 s at 10 Hz: long enough that a
transient blockage (a pedestrian standing on the goal cell) clears first, and
far short of `progress_timeout_steps = 200`, so the release happens **while the
ladder still has replans to spend on an alternate** rather than after the
watchdog has burned them on the same one. The `_steps_without_progress == 0`
guard means *unroutable while the gap is closing* — a bounded detour in
progress — never releases. `getattr(..., "last_route_status", None)` makes the
whole path inert for navigator models that publish no plan status.

**What this is not.** No teleport, no keepout weakened, no veto or proximity
gate touched, no e2e budget raised, no ranking changed. Nothing about *which*
instance grounding picks first changed — `lamp_post_2` is still committed first,
and still correctly. What changed is that the mission may now stop being
committed to it.

**Measured after-run**, same harness: start `(0.0, 0.0)` → end `(−0.00, 0.686)`,
**18.0 s / 180 ticks**, task `succeeded` / `navigation_goal_verified`,

```
resolution_state='verified'   replan_count=1   recovery_phase='scan'
candidate_id='lamp_post_1'    candidate_position=(0.2, 3.15, 0.0)
unreachable_candidates=['lamp_post_2']   unroutable_route_status='goal_blocked'
arrival_trigger='goal_region'            terminal_relation_verified=True
```

— release, rescan, alternate, arrive. Exactly the `alternate_candidate` /
`rescan` vocabulary `brain/validator.py` already carries for `NavigateTo`.

---

## Verification

| what | result |
|---|---|
| `test_walk_towards_the_lamppost_grounds_plans_and_arrives`, dedicated node | **passed, 20.2 s** (was: failed at 65 s, 0.00 m, 4/4) |
| the same case inside both full-suite runs | passed |
| `test_find_the_nearest_lamppost_selects_and_approaches_the_near_one` + `test_run_to_the_nearest_lamppost_applies_the_pace_cap_during_motion` (same geometry) | **2 passed, 48.1 s** |
| `tests/test_embodied_plan_eval.py` — the frozen 1250 row | **10 passed**; the row did not move |
| `ruff check` on every touched file | clean |
| full default `pytest tests/ -q`, first run | **2637 passed, 7 skipped, 5 xfailed, 1 xpassed, 0 failed** (974.2 s) — collected before the new test file existed, so 2650 of 2655 |
| `tests/test_unroutable_goal_release.py` standalone | **5 passed** |
| full default `pytest tests/ -q`, **final tree** | **2643 passed, 7 skipped, 5 xfailed, 0 failed, 0 xpassed** (971.2 s) — 2643 + 7 + 5 = 2655, the whole collection, nothing outside it |

### The fourth lamppost pin, flipped

`test_paraphrase_head_towards_the_lamppost_resolves_the_same_way` was the one
xfail this document deliberately left pinned, because *"its condition is 'this
case flips when the approach path is green again', and its baseline … is the one
remaining red."* The baseline is now a green hard gate and the mechanism behind
both is fixed, so the pin's own condition is met. Flipped on **three
independent green observations** — XPASS inside the full suite, plus two
dedicated node-id runs on a quiet box (25.2 s, 20.2 s) — then re-run as a hard
gate: **passed, 20.3 s**. The pin's own hedge (*"run ALONE this case XPASSES
while its baseline fails … the towards band is marginal here"*) described
exactly the asymmetry that is now gone.

---

## Non-claims

1. **The band is still generous.** The robot verifies arrival at 2.47 m from
   `lamp_post_1` because `TOWARDS_BAND_M = (0.6, 2.5)` starts 0.66 m from the
   spawn pose. It travels 0.69 m and the case's own `moved > 0.3` gate is what
   stops that from being vacuous. Nothing here made the towards contract
   tighter, and whether a 1.9 m-wide "towards" band is the right product
   behaviour is not a question this card measured.
2. **`bldg_5` standing on `sidewalk_south` was not fixed.** The scene really
   does put a building face 0.85 m from the south curb, so `lamp_post_2` has no
   admissible `towards` pose from the origin at the shipping inflation radius.
   The robot now says so and goes elsewhere; the scene was not edited and the
   inflation was not shrunk to make the pose fit.
3. **`safe_approach_pose` returning `None` is a sibling defect, untouched.**
   `_commit_semantic_candidate` still fails the mission outright on a `None`
   pose instead of releasing and trying an alternate. It is the same defect
   class, but it does not *freeze* — it fails immediately — so it is not the
   red this card adjudicates, and changing it would move the N11 traffic
   measurements in LANE_D_STATUS.md D-5 without re-running them.
4. **`UNROUTABLE_GOAL_STEPS = 60` is a choice, not a measurement.** It is
   bounded on both sides by things that are measured (6.0 s > any transient
   blockage observed here; 60 ≪ 200 leaves the replan budget intact), but no
   experiment placed it at 60 rather than 40 or 80.
5. **The release is per-mission and forgets on `stop()`.** A second "walk
   towards the lamppost" in the same session will commit `lamp_post_2` again and
   spend another 6 s proving it unroutable. Claiming it across a session needs
   the persistence story `FalsePositiveMemory` also does not have.
6. **The `towards`-goal geometry is the only case observed to trigger this.**
   The `no_path` half of the trigger has never been seen fire in a live run; it
   is covered by unit tests only.

---

## Files touched

| file | change |
|---|---|
| `src/parcel_robot/navigation/grid_navigator.py` | `last_route_status` property (read-only view of `_last_plan.status`) |
| `src/parcel_robot/navigation/pipeline.py` | `UNROUTABLE_GOAL_STEPS`, `_unroutable_goal_recovery` (called from `step` after the watchdog), `_unreachable_candidates` + `_steps_goal_unroutable` with their `start`/`stop`/commit/replan resets, `_resolution_semantic_map` + `_ExcludingSemanticMap`, unreachable filter in `_memory_candidates` |
| `tests/test_unroutable_goal_release.py` | **new**, 5 — release, exclusion→alternate, the detour-in-progress non-trigger, the no-route-status non-trigger, and the new property |
| `tests/test_voice_nav_e2e.py` | the 4th lamppost xfail pin removed per its own condition, replaced by a provenance comment |
| `scrum/20260806/task_3/REGION_INSTANCE_STATUS.md` | this section |

**Not touched:** `navigation/approach.py`, `navigation/proxemic_approach.py`,
`navigation/traffic_aware.py`, `navigation/grid_planner.py`,
`instructnav/grounding.py`, `instructnav/scoring.py`,
`tests/test_embodied_plan_eval.py`, `evals/**`, `configs/**`,
`src/parcel_robot/scenes/**`.
