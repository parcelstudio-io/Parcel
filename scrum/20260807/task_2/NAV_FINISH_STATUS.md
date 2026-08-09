# NAV-FINISH — the four highest-leverage remaining nav cards · status

**Date:** 2026-08-07 · **Cards:** F-1 (N11 final approach), F-2 (Lane A H-1
value change), F-3 (three sharp edges from
[REGION_INSTANCE_STATUS.md](../../20260806/task_3/REGION_INSTANCE_STATUS.md)),
F-4 (Z_r wiring).
**Entry state:** default suite 2643 passed / 0 failed / 5 xfailed; two `sit
next to X` placement pins and one traffic pin open; one live 1.25-vs-1.2 drift
unresolved.

**The one-line claim:** every mechanism named in the card was diagnosed with an
instrumented live run **before** anything was changed, and in two of the three
cases the diagnosis was *not* what the pin said — the failures had moved. Three
root-cause defects landed (band-edge arithmetic, a missing footprint radius, a
mission that could not act on its own gate's proof), **one xfail flipped to a
hard gate on three green observations**, and the two that did not flip are now
pinned with exhaustive geometry rather than a single trace. The 1.25 → 1.2
value change landed with paired FOLLOW_BENCH_V1 evidence. `Z_r` is wired and
proven inert at sim truth by object identity.

---

## F-1 — N11 final approach

### The instrumented runs, before any edit

Both sit cases were driven live on the product path (`--static-city`, one sim,
one `RobotRuntime`, `handle_text`) with read-only wrappers on
`safe_approach_pose`, `DirectiveNavigator.step` and `apply_reactive_safety`.

| case | pin said | **measured 2026-08-07, before any edit** |
|---|---|---|
| `sit next to the lamppost` | `semantic_arrival_verification_failed` at 18 s, 1.572 m from `lamp_post_1`, 0.072 m outside the band | **the failure had moved.** Grounding commits `lamp_post_2` (the only lamppost in the opening frustum, 7.3 m across the road); the body drives 0.61 m and then parks at **exactly 0.800 m** from `obstacle_bollard` with `grid_track err=0.0 goal=5.3 route=2 status=planned\|obstacle_stop`, `vx=0.0`, for **190 ticks**, until `navigation_no_progress` at 73 s. Zero displacement after the first 0.61 m. |
| `sit next to the bench` | `navigation_no_progress` at 85 s, 1.71 m from centre, 0.21 m outside | **reproduced exactly.** Ends (-0.846, 2.557) = 1.712 m from centre, 0.212 m outside, 91 s, 592 reactive-stop ticks, first stop with `bench_seat` at 0.663 m (predictive reactive stop = 0.65 + 0.108·0.12). Planned pose (-1.000, 3.045) — **1.5007 m from the anchor, i.e. the band's outer edge.** |

### Mechanism 1 — the pose is planned ON the band edge (the 7 cm class)

`NEXT_TO_BAND_M` is the band the **arrival authority verifies against**. It is
not the band a pose may be *planned* in, because `GridNavigator.act` declares
arrival at `goal_distance <= arrival_radius` — in **any** direction, including
radially away from the anchor. With the object metadata's
`arrival_radius_m = 0.06` raised to the branch's floor of 0.08, a pose at
1.5000 m admits a final pose at **1.5800 m**. The 2026-08-06 trace stopped at
1.572 m. The arithmetic and the measurement agree to a centimetre.

**Fix** (`navigation/approach.py::_next_to_planning_band`): plan inside a band
inset on both edges by `arrival_radius + StandOffEnvelope.stand_off_margin_m`
→ (0.52, 1.38) at the shipping values. This is a **narrowing**: every pose it
admits was already admissible. No band, tolerance or gate was widened.

### Mechanism 2 — a robot centre compared against a surface with a footprint-to-surface threshold

The `next_to` occupancy test was

```python
if oid in occupied_ids and math.hypot(px - ox, py - oy) < obstacle_stop_m:
```

where `(px, py)` is a candidate robot **centre** and `(ox, oy)` an observed
**surface** point. `obstacle_stop_m` is a footprint-to-surface clearance, so
**the body radius is simply missing from the comparison** — the branch would
place the robot with its own footprint inside the stop envelope of the object
it was asked to sit beside, and the runtime's reactive gate (which exempts
nothing, correctly) then refused to let it arrive. The sibling `near` branch
gets this right: `_safe_near_object_point` passes
`footprint + obstacle_stop + arrival + margin`.

The `oid in occupied_ids` guard is the second half: `occupied_ids` is built
from returns that *have* an id, so an **anonymous return was ignored entirely**
— the whole check was inert for any range sensor that does not share an id
space with the semantic channel, which is every real one (stratum 2).

**Fix:** clearance is `footprint_clearance_m + obstacle_stop_m + arrival_radius`
(= 1.20 m centre-to-surface at the shipping config) against **every** observed
return, id or not. `obstacle_stop_m` resolves in-body to
`StandOffEnvelope.target_surface_clearance_m` (0.8 m), which dominates the
runtime reactive gate (0.65 m), so a placement that clears this clears every
gate that does not exempt the target — and the runtime's never does.

### Mechanism 3 — routable and impassable: the planner and the gate disagree

The lamppost bollard park is a **third** defect, and it is general:

* `RollingGridPlanner` inflates obstacles by `inflation_radius_m` = 0.42 m, so
  a route may bring the body to 0.10 m of an observed surface and still report
  `planned`;
* `apply_collision_brake` hard-stops translation at
  `CollisionPolicy.obstacle_stop_m` = 0.8 m footprint-to-surface (1.12 m
  centre-to-surface) — `configs/navigation/default.yaml stop_distance_m`.

**A corridor between those two numbers is routable and impassable.** Measured:
the A\* route from (0,0) to the committed pose passes **0.71 m from the
bollard's centre** (0.53 m from its surface, > the 0.42 m inflation, < the
1.12 m the gate needs). Under `predictive_mode: projected_speed_cap` the body
decelerates smoothly to zero exactly at the boundary and the hard stop then
pins it there — a perfect deadlock, `status=planned|obstacle_stop`, forever.
The progress watchdog's replan re-grounds the same instance and re-derives the
same route; the existing `_unroutable_goal_recovery` cannot help because A\*
never says `goal_blocked`.

**Fix:** `DirectiveNavigator._gate_blocked_route_recovery`. Sixty consecutive
ticks of `cnote == "obstacle_stop"` **with zero goal progress** is proof that
this route is not executable by this body, and the mission releases the
commitment through the same door the unroutable-goal card built. `person_stop`
is deliberately excluded and pinned by a test: yielding to a person is the gate
doing its job, and releasing on it would make the robot abandon its goal every
time somebody walked past.

**Nothing about the gate changed.** It is believed, not bypassed, not retuned,
not second-guessed; the tests assert `vx == 0.0` on every blocked tick.

### Result, measured live after all three

| case | before | after |
|---|---|---|
| `sit next to the lamppost` | `failed` / `navigation_no_progress`, 73 s, 0.61 m travelled, `candidate_id='lamp_post_2'`, `replan_count=2` | **`succeeded` / `arrived_verified`, 46.6 s.** Releases `lamp_post_2` at ~26 s (`unreachable_candidates=['lamp_post_2']`), commits `lamp_post_1`, ends **1.493 m** from it — inside the band, K0 miss **0.000 m** — `arrival_trigger='goal_region'`, `terminal_relation_verified=True`, **`posture='sit'`** |
| `sit next to the bench` | `failed` / `navigation_no_progress`, 91 s, 592 reactive stops, 0.212 m outside | `failed` / **`semantic_target_unreachable`, 7.5 s**, 0.00 m travelled — the honest answer, see below |

### The bench is geometrically impossible, and this is the proof

Not "the approach falls short". **There is no admissible pose.** The K0
`next_to` band is 0.4–1.5 m from the anchor **centre** while every stand-off
authority is measured from its **surface**; `bench_1` is a 1.4 × 0.44 m box
whose circumscribed radius is 0.734 m, so the band's outer edge is 0.766 m from
the circumscribed surface — inside `target_surface_clearance_m` (0.8 m) before
the 0.32 m footprint is added.

Exhaustive sweep of the entire band against the **true** scene geometry (3601
bearings × 551 radii, bench boxes + `bldg_1`/`bldg_2` + `pedestrian_5`):

| requirement | admissible poses | nearest to spawn |
|---|---|---|
| 1.20 m centre-to-surface (footprint + stop + arrival) + 1.20 m person | **0** | — |
| 1.20 m + 1.40 m person | **0** | — |
| 0.97 m (runtime reactive gate only) + 1.20 m person | 1609 | (-3.197, 1.717) at **radius 1.500** — the band edge the arrival inset exists to forbid |
| 0.97 m, **ignoring the pedestrian** | 63713 | (-1.627, 1.825) |

`pedestrian_5` stands at **(-2.0, 1.8)** in the *static* city — 1.342 m from the
bench centre, i.e. **inside the bench's own next_to band** — and `bldg_1`'s
south face is 0.77 m north of the bench back. The shipped 5×24 placement
lattice contains no admissible point under any of these requirements, so `None`
is the truth and not a sampling artefact.

**This is a scene/authority decision, not a navigation fix**, and it is
deliberately not taken here: either `next_to`'s band scales with the anchor
footprint (a K0 change and a re-freeze), or `bench` drops `next_to` from its
sidecar affordances the way `building` already does. Note that
`tests/test_scene_semantics.py::test_declared_affordances_are_achievable_at_the_scene_s_real_radii`
checks band emptiness against the **footprint only**, not against the stand-off
envelope — which is exactly why it passes `bench` today. Strengthening it needs
`configs/scenes/**`, which this card does not own.

### The traffic case — measured, not flipped

`test_go_to_the_sidewalk_with_pedestrian_traffic`, dynamic city, **n=3 live**
post-everything: **3/3 fail** (242.4 s, 243.4 s, 240.3 s). The written
condition is ≥2/3, so the pin stays. The reason string was rewritten with the
new measurement, which is much sharper than the old one:

* ONE approach call, `relation='inside'`, pose (1.64, 2.64), `arrival_radius`
  0.12 — traffic-aware ranking placed it clear of the crosswalk stream;
* the robot reached (1.602, 2.485), which **is inside the scored sidewalk
  polygon** (K0 distance **0.000 m**, closest approach 0.000 m, path 2.97 m);
* it then held that spot for ~200 ticks with
  `grid_track err=0.0 goal=0.2 route=2 status=planned|person_stop`: **a
  pedestrian is parked on the last 0.2 m to the approach pose.**

Two deliberate design choices keep it there until the clock expires, and both
are individually correct: `_progress_watchdog` does not count person-stop ticks
as no-progress (N11's own fix, so yielding cannot false-fail a mission), so
nothing replans; and `_inside_arrival_goal_region` returns `False` for the
`inside` relation, because region arrival requires terminal clearance and the
robot is only 0.285 m inside the live sidewalk edge against a 0.32 m
requirement. **The residual is a yield-vs-deadline product decision** — how
long may a `NavigateTo` spend yielding before it reports "blocked by a person"
instead of `step_timeout`? — not final-approach geometry.

---

## F-2 — the 1.25 → 1.2 value change, with paired evidence

`FollowConfig.obstacle_slow_m` was the last of the six `obstacle_slow_m` copies
still carrying 1.25 (the other five: `collision.py`, `reactive_safety.py`,
`pipeline.py`, `headless_city.py`, `configs/robot.yaml`). It now reads
`DEFAULT_SAFETY_ENVELOPE.obstacle_comfort_band_m`. `configs/robot.yaml`'s
`owner_follow` block does not set the key, so this default is what both the
runtime and the bench actually use.

**Paired FOLLOW_BENCH_V1**, `--scenario all --features shipped`, before and
after. **The ledger rows were appended, then reverted — see "appending a
follow-bench row is not read-only" below.** The reports live in the session
scratchpad; the numbers live here:

| metric | before (1.25) | after (1.2) | delta |
|---|---|---|---|
| follow success | 9/9 | 9/9 | 0 |
| navigate success | 2/2 | 2/2 | 0 |
| hard collisions | 0 | 0 | 0 |
| pedestrian contacts | 0 | 0 | 0 |
| min pedestrian surface (m) | 0.3521053144272877 | 0.3521053144272877 | **0** |
| reactive gate stops | 4 | 4 | 0 |
| intimate / personal space (s) | 0.0 / 3.8 | 0.0 / 3.8 | 0 |
| mean band fraction | 0.7405618401206637 | 0.7433396178984414 | **+0.00278** |
| mean RMS commanded jerk (m/s³) | 0.6031 | 0.6046 | +0.0015 |

**Exactly one scenario moved**: `follow_turn_corner` band fraction
0.4375 → 0.4625. Every other per-scenario number is identical. No safety metric
moved at all.

**Ratchet:** the `("navigation/follow.py", 1.25)` allowlist entry is **deleted**
(not capped at 0 — the two-way rule wants the shrink visible in the diff), with
the paired numbers recorded at the deletion site.

### Appending a follow-bench ledger row is NOT a read-only operation — STOPPED AND REPORTED

The card authorised *running* evals and *appending* rows. Appending two rows to
`evals/companion_nav/results/ledger.jsonl` turned
`tests/test_duplex_v1.py` **3 red**:
`test_nav_regression_pins_post_speed_raise_rows` reads the ledger's **latest
`features="shipped"` row** and pins it against `FOLLOW_BENCH_POST_SPEED`, so an
appended row *is* a frozen-row move by another name. Both appended rows and the
two report JSONs were reverted; `tests/test_duplex_v1.py` is **3 passed** again
and nothing under `evals/` is modified by this card.

**And the failure exposed a real, pre-existing staleness that is not this
card's to fix.** The pin expects `follow_success: 8/9`; the live tree scores
**9/9**, and it did so in the **before** run as well as the after — i.e. the
drift is independent of the 1.25 → 1.2 change. Somewhere between 2026-08-04
(when the pinned row was written) and today, one follow scenario started
passing. Owner: whoever owns `evals/**` — the pin needs a re-measure and a
re-freeze, and until then the duplex report's `nav_regression` block describes
a tree that no longer exists.

**The second 1.25 (`city_semantics.py:219`) was read and deliberately NOT
resolved with it.** It is a different quantity in a different family:
`non_target_obstacle_clearance_m` is a centre-to-surface **stand-off
composite** that `safe_approach_pose` defaults to
`footprint(0.32) + obstacle_stop(0.8) + arrival_radius(0.06) + 0.05 = 1.23`;
the scene stamps 1.25, i.e. the composite plus 0.02 of commissioning margin.
Deriving it belongs to the `StandOffEnvelope` family, not to
`obstacle_comfort_band_m`. Documented on its allowlist entry.

---

## F-3 — the three sharp edges

### (a) first-confirmed-wins, closed — and the frozen row did not move

`search.observe`'s in-view branch gated on `len(qualified) >= 2` but minimised
over `confirmed`, so an instance that entered the frustum earlier (and
therefore confirmed earlier) beat a **nearer** instance that was already
visible and one sighting short. That is first-confirmed-wins in the exact case
ruling 2 outlaws. It is now
`len(confirmed) == len(qualified)`.

**Frozen-row check, run immediately after the edit:**
`tests/test_embodied_plan_eval.py` — **10 passed**, the 1250 row did not move.
Nothing was re-frozen and nothing under `evals/` was written by this card
except two appended FOLLOW_BENCH ledger rows.

**Negative control:** reverting the one-line condition makes
`test_a_confirmed_far_instance_does_not_beat_a_visible_nearer_unconfirmed_one`
fail and the other three pass; restoring it passes all four. The existing suite
could not catch it because every case shows both instances from tick one, where
the sighting counts advance together — the new cases script a *sweep*.

### (b) the 0.4 m sampling bias, and the sidewalk's true margin

`nearest_point_in_region` serves two callers with two different questions:

* `inset_m == 0` — the **DISTANCE** use, every interchangeable-goal ranking
  site — now answered **exactly**, by segment projection
  (`nearest_boundary_point` / `distance_to_region_m`);
* `inset_m > 0` — the **POSE** use, the approach solver's region fallback —
  keeps the inset-sample behaviour, because an inset point has to be tested for
  interior membership and edge clearance, which is what the sampler does.

Both are documented at the function. The bias removed, measured on the live
polygons from the origin:

| polygon | sampled | exact | error |
|---|---|---|---|
| `sidewalk` (north, near edge is its `min_y` side) | 2.20 | 2.20 | 0.00 |
| `sidewalk_south` (near edge is its `max_y` side) | 2.55 | **2.25** | **0.30** |

North still wins, so the arbitrated `default-origin` expectation does not move
— but **the true margin is 0.05 m**, not the 0.35 m the sampler reported, and
that is now pinned by a test.

### (c) `safe_approach_pose` returning `None`

Was: fail the whole mission. Now: release **that instance** through the same
exit as the other two proofs. All three release authorities — A\*
(`goal_blocked`/`no_path`), the obstacle gate, and the approach solver — share
one `_release_unreachable_candidate`: one per-mission memory, one exclusion
door (`_ExcludingSemanticMap`), one replan budget. Three authorities with three
ladders is the D5 defect class.

One honest-labelling change came with it: a ladder that exhausts **after
releasing something** now reports `semantic_target_unreachable`, not
`semantic_target_not_found`. It found the thing; it could not get to it.
Unchanged for every mission that never released anything.

---

## F-4 — `Z_r` wired

Lane B's hand-off 1: `PoseEstimate.position_sigma_m` (`sqrt(σ_xx + σ_yy)`) is
the scalar `SafetyEnvelope.pose_uncertainty_m` expects, and ISO/TS-15066 puts
it in `stop_distance(v)` as a plain additive term. So
`DirectiveNavigator.pose_aware_collision_policy(observation)` derives this
tick's `CollisionPolicy` from the MAP-frame pose: `σ` added to each of
`person_stop_m`, `person_slow_m`, `obstacle_stop_m`, `obstacle_slow_m`.

* **Inert at sim truth, by identity.** `TruthPoseProvider` reports exactly zero
  covariance, `σ == 0.0`, and the method returns `self.collision` — *the same
  object*. The equality assertion is `is`, not a float comparison, so no frozen
  row, eval digest or measured trace can have moved.
* **Widening under a drift provider**: every one of the four boundaries moves
  out by exactly σ; `slow_scale`, `reaction_time_s` and `predictive_mode` are
  untouched. Adding the same term to a stop and its slow band preserves
  `stop < slow`, so the policy still validates, and the transform is monotone —
  it can only ever brake earlier.
* Bounded at `MAX_POSE_UNCERTAINTY_M = 1.0`: a localizer reporting a 10 m sigma
  is broken, and the answer to *that* is the pose-health path (`PoseHealth.LOST`
  already refuses arrival claims), not a 10 m envelope with no way back.
* A pose object with no covariance (bundle/legacy stand-ins) reports 0.0 —
  absence reported as absence, never as an invented brake.

---

## Verification

| check | result |
|---|---|
| `tests/test_embodied_plan_eval.py` — the frozen 1250 row | **10 passed**, unmoved, re-checked after the `search.py` edit and again at the end |
| `ruff check` on every file this card touched | **clean** |
| `test_sit_next_to_the_lamppost_settles_beside_it_in_a_sit` | **PASSED** as a hard gate, 51.2 s (3rd green observation) |
| `test_sit_next_to_the_lamppost_emits_a_posture_step_and_reaches_it_if_it_arrives` | PASSED — the posture half now bites, and does |
| `test_sit_next_to_the_bench_settles_beside_it_in_a_sit` | XFAIL (reason rewritten with the exhaustive sweep) |
| `test_go_to_the_sidewalk_with_pedestrian_traffic` | XFAIL ×3 (reason rewritten with the person-on-the-pose measurement) |
| `test_go_to_the_sidewalk_grounds_plans_and_arrives` | PASSED (regression check on the region path) |
| FOLLOW_BENCH_V1 paired runs | 2 runs, delta above; ledger rows appended then **reverted** (they move a duplex pin — see F-2). `tests/test_duplex_v1.py` **3 passed** after the revert |
| new tests | **+26** across 5 files: `test_next_to_approach_geometry` 9 (new), `test_search_instance_selection` 4 (new), `test_pose_uncertainty_envelope` 5 (new), `test_unroutable_goal_release` 5 → 10, `test_instructnav_relations` 3 → 5 |
| `Z_r` per-tick cost | 3.43 µs/call (10 000-call loop) — one extra pose read per control tick at 10 Hz |

### Full default suite (`MUJOCO_GL=egl .parcel/bin/python -m pytest tests/ -q`)

Includes the live `-m slow` e2e block. Run twice — the first exposed the
ledger-append problem, the second is the final tree.

| run | result | wall |
|---|---|---|
| with the appended follow-bench ledger rows | `3 failed, 2770 passed, 14 skipped, 3 xfailed` — all three reds `tests/test_duplex_v1.py`, caused by the append | 907.1 s |
| **final tree**, rows reverted | **`2777 passed, 14 skipped, 3 xfailed, 0 failed, 0 xpassed`** | 884.5 s |

No xpasses in either run, so nothing is pinned that now passes. The two
remaining nav xfails are the bench sit and the traffic case, both re-measured
above; the third is `test_authority_half_scale_smoke`'s scale-covariance pin,
untouched. The traffic case xfailing inside this final run is its **fourth**
consecutive observation.

Two collateral reds were seen mid-card and are **not** this card's: a
transient `tests/test_emote_skill.py::test_text_only_path_fires_emotes_immediately`
(runtime `_speaker_sink`, another executor's in-flight edit, gone by the next
run) and five in `tests/test_nav_instruct_scene_gen.py` (an untracked file
created by the concurrent `evals/**` executor at 20:44, mid-edit). Neither
appears in the final run.

---

## Non-claims

1. **The bench is not fixed and cannot be fixed here.** It is proved
   impossible at the shipping envelopes and left honest. The decision that
   would change that (band scaling vs. sidecar affordance) belongs to whoever
   owns K0 and `configs/scenes/**`.
2. **The planner/gate inflation mismatch is contained, not resolved.** The
   right fix is for `RollingGridPlanner` to respect the gate's stop distance,
   and it was deliberately not made: it re-routes globally and would almost
   certainly move the frozen embodied row, which this card is instructed to
   stop and report on rather than move. What landed instead is the mission's
   ability to *notice* and try somewhere else.
3. **`GATE_BLOCKED_ROUTE_STEPS = 60` is a choice, not a measurement**, exactly
   like `UNROUTABLE_GOAL_STEPS`. It is bounded on both sides by measured things
   (6.0 s outlasts any transient blockage observed here; 60 ≪ 200 leaves the
   replan budget intact), but no experiment placed it at 60 rather than 40.
4. **Releasing a candidate because a *route* was blocked is a heuristic about
   which information is new.** It is right when an alternate instance exists
   (measured: the lamppost) and merely faster-and-more-honest when one does
   not. It is not a claim that a different route to the same instance could not
   have worked — nothing here searches for one.
5. **The traffic case's new diagnosis is one instrumented run** plus two
   node-id reproductions of the failure and its timing. The claim "a pedestrian
   is parked on the last 0.2 m" is read off that run's tick trace, not
   replicated across seeds.
6. **`Z_r` widening has never been exercised on the mission path**, because no
   shipping provider reports a non-zero covariance. The drift-provider tests
   are unit-level; the first real localizer is what will measure it.
7. **The exact boundary distance changes a number every interchangeable
   ranking reads.** The sidewalk outcome was checked and does not move, and the
   suite is green, but "no ranking anywhere flipped" is a suite result, not a
   proof.

---

## Files touched

| file | change |
|---|---|
| `src/parcel_robot/navigation/approach.py` | `_next_to_planning_band`; `next_to` branch: arrival-tolerance inset, footprint-correct surface clearance over **all** returns, `ValueError` → honest `None` |
| `src/parcel_robot/navigation/pipeline.py` | `_gate_blocked_route_recovery` + `GATE_BLOCKED_ROUTE_STEPS` + `_steps_gate_blocked` and its five resets; `_release_unreachable_candidate` (one exit for three authorities); `None`-pose release; `_target_missing_command`; `pose_aware_collision_policy` + `_pose_uncertainty_m` + `MAX_POSE_UNCERTAINTY_M` |
| `src/parcel_robot/navigation/search.py` | in-view commit requires every visible qualified instance confirmed |
| `src/parcel_robot/navigation/follow.py` | `FollowConfig.obstacle_slow_m` 1.25 → `DEFAULT_SAFETY_ENVELOPE.obstacle_comfort_band_m` |
| `src/parcel_robot/instructnav/relations.py` | `nearest_boundary_point`, `distance_to_region_m`, `_closest_point_on_segment`; `nearest_point_in_region` exact at `inset_m == 0` |
| `tests/test_voice_nav_e2e.py` | lamppost sit pin **removed** (provenance comment in its place); bench + traffic reasons rewritten with current measurements |
| `tests/test_next_to_approach_geometry.py` | **new**, 9 |
| `tests/test_search_instance_selection.py` | **new**, 4 |
| `tests/test_pose_uncertainty_envelope.py` | **new**, 5 |
| `tests/test_unroutable_goal_release.py` | +6 cases (gate-blocked release, the two non-triggers, `None`-pose release, the honest label) + scope note |
| `tests/test_instructnav_relations.py` | +2 cases (exact distance, the pose use unchanged) |
| `tests/test_authority_no_literal_drift.py` | `follow.py` 1.25 entry deleted with its paired evidence; `city_semantics.py` 1.25 entry documented as a different quantity |
| `evals/**` | **nothing.** Two FOLLOW_BENCH_V1 rows + reports were written and then reverted (they move a duplex pin); the tree is byte-identical to before this card |

**Not touched:** `navigation/reactive_safety.py`, `navigation/collision.py`,
`navigation/grid_planner.py`, `navigation/proxemic_approach.py`,
`navigation/traffic_aware.py`, `instructnav/grounding.py`, `authority.py`,
`pose.py`, `runtime.py`, `core/**`, `brain/**`, `voice/**`, `configs/**`,
`src/parcel_robot/scenes/**`, `evals/**` (code *or* data),
`tests/test_embodied_plan_eval.py`, `tests/test_duplex_v1.py`.

---

## Stopped and reported

1. **The follow-bench ledger append moved a duplex pin.** Reverted; the
   staleness it exposed (pinned 8/9 against a live 9/9, present in the
   **before** run too, so independent of the value change) is an `evals/**`
   re-freeze and not this card's.
2. **The bench `next_to` band is empty at the shipping envelopes.** Proved
   exhaustively, not fixed — it needs a K0 band change (with a re-freeze) or a
   sidecar affordance change, both outside this card's ownership.
3. **The planner/gate inflation mismatch (0.42 m vs 0.8 m) is real and
   general.** The root fix re-routes globally and would very likely move the
   frozen embodied 1250 row, so it was not attempted; what landed is the
   mission's ability to detect the symptom and go elsewhere.
4. **`tests/test_scene_semantics.py`'s affordance-achievability check is too
   weak** — it tests band emptiness against the anchor footprint only, not
   against the stand-off envelope, which is why `bench` still advertises
   `next_to`. Strengthening it needs `configs/scenes/**`.
