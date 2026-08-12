# RM-3 status — does place memory convert the bottleneck?

Card: `scrum/20260811/task_2/SLAM_M_PLAN.md` (r2), Wave 3, RM-3.
Executor: Claude Opus 5. Date: 2026-08-12. **Not committed.**
Base: `dd2e857` + the audited uncommitted batch (AUDIT_WAVE2_FABLE: both Wave-2
cards CONFIRMED, ci_gate PASS 3909/0).

**Revision 2 (2026-08-12) — closing the Fable Wave-3 audit RETURN.** The
MEASUREMENT was confirmed honest (pre-drive parity, isolation, digest, McNemar
arithmetic and budget derivation all independently verified; two auditors
reproduced the artifact rows bit-for-bit with the shipped driver). Four majors
were upheld 8/8, **all against this document's causal narrative, none against a
number in the artifacts**: §7.1(4)/§9.1 exonerated `apply_collision_brake` using
the wrong `CollisionPolicy`; §7.1(3) claimed a permanent, arm-identical stall
that the artifact refutes; §6.3 conflated three counters; and Pilot B's
membership in the gated 60 was not disclosed. All four are corrected in place
and marked *(Revision 2)*. **No sweep was re-run and no artifact changed** — the
corrections are to the reading of them. Each correction was re-verified here
against the code and the persisted rows before it was written.

This card is a **measurement** card. `src/**` is frozen for it: every defect
below is a handoff (§9), never an edit.

> ## ⛔ HEADLINE — the pre-registered gate FAILED, on honest numbers
>
> **0 net paired flips (pre-registered ≥ 6), exact McNemar p = 1.000
> (pre-registered ≤ 0.031), n = 60, SR 7/60 on BOTH arms.** Nothing was tuned to
> the gate; the pre-registration (§1) was frozen before the sweep, the pilot it
> rests on is recorded as a pilot (§2, §3), and no constant, ordering or
> admission rule was touched after any measurement.
>
> **The mechanism is not the reason.** It is live and safe on the real product
> path — the first eval arm that has EVER run `route_memory` flag-ON: **42 of 60
> measured missions** consulted the place graph, got a recorded route, published
> a stamped `SE2Goal`, **won** arbitration (0 vetoed) and drove the waypoint
> chain for **4892 ticks**; the ON arm travels **49 % further** and the arms
> differ on **31 of 60** cells by distance-to-goal. Collisions **0** and
> `false_arrival` **0** on both arms.
>
> **The reason is measured, and it is a pre-existing product defect route memory
> merely exposes (§7.1):** with a live chain, a `planned` route to a waypoint
> 7.9 m away and a tracking error of 0.2°, `apply_collision_brake` — under the
> policy the product actually builds, `obstacle_stop_m = 0.8` /
> `projected_speed_cap` from `configs/navigation/default.yaml` — returns
> `(0.0, 0.0, 'obstacle_stop')` for every requested speed, because an *unmapped*
> obstacle sits at exactly 0.80 m, 88° off the travel axis, and the
> projected-mode relevance gate admits any positive closing fraction. 63 brake
> calls zeroed requests of 0.09–0.85 m/s on one cell. The wedge reproduces
> **flag-OFF** on the same cell. Route memory supplies an aim point; an aim
> point cannot restore a velocity the brake has taken. Handoff §9.1.
>
> Also closed here: **trigger (ii) is no longer unmeasured** — 40 of the 42
> armed episodes exercised it exclusively, and at least 51 of the 53 armings
> came through it (§6.3), which is the audit's binding Wave-3 item.

---

## 1. Pre-registration — frozen BEFORE any arm of the gated sweep ran

Written into this file **before** the paired sweep was launched. §2 records the
pilot that this pre-registration rests on, and §3 records what the pilot itself
refuted — a substrate that was changed *before* anything was pre-registered on
it, which is the Y-3 lesson applied rather than quoted.

**What is evidenced, precisely** *(Revision 2, audit correction 5c — revision 1
claimed the driver was frozen too, and mtime does not evidence that).* What
predates the sweep is **the pre-registration text in this file and the substrate
itself**: the admission rule, every derived constant, the ordering, n = 60 and
the `cells_digest` `a23c802b…` were all fixed in
`evals/nav_instruct/route_memory_cells.py` before the arms were launched, and
the digest is stamped on both artifacts, so a substrate change after the fact
would be visible. **The DRIVER was edited mid-session** and that is disclosed in
§6.5; none of its edits touch the gated claim, the estimator, the budget or the
substrate.

**Pilot B's six cells ARE cells 00–05 of the gated 60** — see the disclosure in
§3, which states the overlap, its bias direction and the robustness check.

### 1.1 The gated claim

> On the `v4r` taught-prior-route substrate, n = 60, route_memory ON vs OFF,
> paired per episode, isolated processes, default matcher arm:
> **≥ 6 net paired flips (on_only − off_only) AND exact McNemar p ≤ 0.031.**

Estimator: the **exact** two-sided McNemar (binomial) p, never the chi-square
approximation — `run_route_memory_arms.mcnemar_exact`. The threshold matters at
this resolution: (b=6, c=0) gives p = 0.03125, which **fails** ≤ 0.031, while
(b=7, c=0) gives 0.015625 and passes. The pre-registration is read literally;
both conditions must hold.

### 1.2 The substrate, and n

* Set `v4r`, `evals/nav_instruct/route_memory_cells.py`. Additive,
  candidate-only, **not** a member of `generator.EPISODE_SETS` (DR-2's `v4d`
  precedent), so `--freeze` and the frozen-baseline ledger flag cannot reach it.
* Admission rule (every clause a generation-time test; full derivations in the
  module docstring):
  1. the target is **out of frustum range** from the start
     (`range_m > VISIBILITY_MAX_RANGE_M = 12.0`) — so it cannot be sighted on
     tick 0 and a committed goal can only be **KNOWN**, from the taught leg;
  2. the goal is **beyond planner reach** in the strictest form — start to the
     NEAREST point of the scored region > `8.05 m` (RM-1's
     `DEFAULT_ATTACH_RADIUS_M`, which is the pipeline's `ROUTE_MEMORY_RANGE_M`);
  3. the **straight corridor is blocked**, asserted against the world's own
     occupancy (`HeadlessCityWorld.truth_minimum_clearance` ≤ the gate's
     `obstacle_stop_floor_m`), not against the landmark-disc approximation;
  4. a **driveable detour exists** on that same occupancy, at least one keyframe
     spacing (0.50 m) longer than the straight line to its own end point;
  5. the **start** is driveable (clearance > `TEACH_MIN_CLEARANCE_M`);
  6. **both attach ends** within 8.05 m of the taught route (start end: 0.00 m,
     the robot stands on the first keyframe; goal end: the last taught point
     lies inside the scored region).
* The rule admits **434** cells. **n = 60** is the pre-registered gated set: the
  first 60 of the deterministic round-robin order (longest detour first within
  each target, round-robin across targets), an order fixed by the admission rule
  and by nothing measured. Balanced 10 cells per target across all six.
* Set digest (`cells_digest`):
  `a23c802bbbf73cb3051149c73738342f7a5e55045b3681df594906672c3a064a`.

### 1.3 The arms, and what differs between them

| | ON | OFF |
|---|---|---|
| navigator override | `route_memory=True` | `route_memory=False` |
| taught leg | driven, identical script | driven, identical script |
| mode | `candidate` | `candidate` |
| budget | `scaled-path-v1`, base 200 | identical, per episode |
| process | its own | its own |

**Exactly one thing differs.** Both arms drive the same taught leg — same
polyline, same physics, same tick count — so the comparison is a test of route
memory, not of having driven around first. The taught leg is a no-op for the OFF
arm's place graph because the OFF arm *has* no place graph.

### 1.4 Budget derivation, and the probe-hold allowance (binding, stated)

Budget per episode = `scaled_step_budget(episode, 200, "scaled-path-v1")` =
`120 + ceil(taught_route_m / 0.03)` ticks, capped at 1200. Both arms of a pair
run the same episode and therefore the identical budget.

`AUDIT_WAVE2_FABLE.md` binds RM-3 to state that the paired budgets do not
straddle the hand-back probe hold. They cannot:

* the probe holds the true goal for at most `2 × GRID_REPLAN_INTERVAL_STEPS`
  = **10 ticks**, once per chain (RM2_STATUS §3), and cost **+9** on RM-2's own
  corridor;
* the budget's FIXED overhead term alone is **120 ticks = 12× the worst-case
  hold**, and the smallest budget any admitted cell draws is
  `120 + ceil(19.13/0.03)` = **758 ticks ≈ 75× the hold**.

No outcome in the paired table can be decided by whether the probe held.

### 1.5 Isolation (pre-registered, and verified — §6.4)

1. **One process per arm** — `run_route_memory_arms both` spawns one subprocess
   per arm; the parent constructs no navigator.
2. **One WORLD per episode.** `episodes/V4S_MATCHER_ARM.md`:
   `HeadlessCityWorld._scan_rng` is seeded once per world construction
   (`np.random.default_rng(7)`) and is never re-seeded by `reset()`, so inside
   one process an arm that shortens one episode shifts the RNG for every LATER
   episode — "a per-episode number from a multi-episode run is not portable".
   McNemar is *entirely* per-episode, so this is a correctness requirement for
   the pairing, not a refinement. A fresh `NavInstructRunner` per episode is the
   only mode the driver has.
3. **A mission boundary per leg.** Fresh runner ⇒ fresh `DirectiveNavigator` ⇒
   fresh place graph and fresh semantic memory; inside the episode the taught
   leg's `start()`/`stop()` each call `_reset_route_memory_track()`
   (RM2_STATUS §2(1)), so the taught leg and the measured mission share a graph
   and share no ingest track.

### 1.6 Report-only arms (no gate)

* **v4s LA/BB, ON vs OFF** — expected ≈ no-op, which is the memory-honesty rule
  confirming itself rather than a gate failing.
* **One drifted arm** — `calibrated_go2 × route_memory ON` on `v4r`; keyframe
  integrity under drift reported, not gated. B5 does not contaminate it: MAP is
  truth-passthrough on `calibrated_go2`.
* **Teach-and-repeat** — SR and path fidelity vs the taught line, measured on
  the same `v4r` runs (stated as derived, DR-2's precedent for derived tables).

### 1.7 Trigger (ii)

`AUDIT_WAVE2_FABLE.md` binds RM-3 either to measure trigger (ii)
(`_route_memory_partial_recovery`, partial-plan non-progress) or to report it as
still unmeasured. It is measured here: **40 of the 42 armed episodes exercised
trigger (ii) exclusively**, and at least 51 of the 53 armings came through it —
see §6.3 for the counter units, which revision 1 got wrong.

---

## 2. Pilot A — the SIGHTED substrate, and why it was thrown away

The card is explicit: *"do NOT pre-register a gate the mechanism structurally
cannot flip — validate reachability-under-memory on a pilot cell BEFORE freezing
the pre-registration, and record the pilot as such."* This is that pilot, and it
came back negative. **No gate was ever registered on this substrate.**

### 2.1 What it was

The first `v4r` draft took the SIGHTED half of "sighted-or-known": the target
inside the 12 m frustum with the start yaw facing it, so the mission commits on
tick 1. Everything else was as §1.2: beyond reach, corridor blocked, driveable
detour, taught leg driven, then a teleport back to the start.

### 2.2 What the pilot measured (4 cells, ON arm, per-episode instrumentation)

| cell | measured-mission route queries | routes found | chains armed | outcome |
|---|---|---|---|---|
| 00 | **0** | 0 | 0 | `navigation_no_progress`, dtg 6.75 |
| 01 | **0** | 0 | 0 | `arrived_verified` |
| 02 | **0** | 0 | 0 | `navigation_no_progress`, dtg 6.33 |
| 03 | **0** | 0 | 0 | `navigation_step_limit`, dtg 1.59 |

Route memory was **never consulted in the measured mission on any cell**. Every
query the counters showed (140, 124, 1, 0) belonged to the **taught leg**, which
is why the counters are now reported as deltas against a taught-leg baseline
(§6.2) rather than as totals.

### 2.3 The mechanism, and why it is structural rather than unlucky

`_route_memory_goal_is_at_range` requires the committed goal to be further than
`ROUTE_MEMORY_RANGE_M = 8.05 m`. A SIGHTED target is at most
`VISIBILITY_MAX_RANGE_M = 12.0 m` away, and the committed approach pose sits
inside the scored region, i.e. up to `band_outer = 2.5 m` nearer:

```
max committed distance ≈ 12.0 − 2.5 = 9.5 m
memory's window        = 9.5 − 8.05 = 1.45 m of travel
```

Both triggers need **60 consecutive ticks** of non-progress (trigger (i)'s
`UNROUTABLE_GOAL_STEPS`, trigger (ii)'s hysteresis) before they ask memory
anything. A robot that is moving at all closes 1.45 m in far less than 60 ticks;
a robot that is not moving at all is wedged (§7.1). Either way the door is shut
before it can be knocked on. **On a sighted substrate this mechanism cannot be
reached, and a McNemar gate registered there would have been unflippable by
construction** — the Y-3 mistake, avoided by measuring rather than assuming.

### 2.4 What was changed, and when

The substrate moved to the **KNOWN** half of the same clause (§1.2 rule 1) and
the teleport was replaced by an out-and-back taught leg (§5.2), **before** §1
was written. Two further corrections were folded in at the same time, both
measured in this pilot and both about the substrate rather than the mechanism:

* occupancy moved from the landmark-disc model to the world's own
  (`truth_minimum_clearance`) — a start at `(3.5, 2.5)` that the disc model
  called free has **0.157 m** of true clearance against an unmapped crate, and
  its taught leg spent 1257 ticks without moving 3.5 m. DR-2's handoff 2,
  acted on;
* the taught-leg tick budget became a derived worst case
  (`2 x travel + one full reversal per vertex`) instead of a flat 40 ticks/m,
  which two cells had exhausted.

---

## 3. Pilot B — the accepted substrate, and the reachability it establishes

Same protocol, 6 cells, ON and OFF, isolated processes, per-episode
instrumentation, **before** the pre-registration was frozen.

| cell | ON | OFF | ON reason | OFF reason | measured queries → found | chain ticks |
|---|---|---|---|---|---|---|
| 00 | ✗ | ✗ | `semantic_target_unreachable` | `navigation_no_progress` | 1 → 1 | 60 |
| 01 | ✓ | ✓ | `arrived_verified` | `arrived_verified` | 0 → 0 | 0 |
| 02 | ✗ | ✗ | `navigation_no_progress` | `navigation_no_progress` | 0 → 0 | 0 |
| 03 | ✗ | ✗ | `navigation_no_progress` | `navigation_no_progress` | 1 → 1 | 60 |
| 04 | ✗ | ✗ | `navigation_no_progress` | `semantic_target_unreachable` | 1 → 1 | 140 |
| 05 | ✗ | ✗ | `semantic_target_unreachable` | `semantic_target_unreachable` | 1 → 1 | 60 |

**What the pilot establishes, and what it does not.**

* **Reachable — measured.** On 4 of 6 cells the MEASURED mission consulted
  memory, got a recorded route, published a stamped waypoint, **won**
  arbitration, and drove the chain for 60–140 ticks. The mechanism the gate is
  about is live on this substrate, which is the reachability the card asks the
  pilot to establish, and it is what Pilot A could not show.
* **Not a promise of flips.** The pilot produced **0 net flips on 6 cells** (one
  cell succeeded on both arms; five failed on both). The pre-registration was
  frozen anyway, unchanged, because the card's instruction is explicit: a
  pre-registered gate that fails on honest numbers is a reportable scientific
  result, and the thing that must not happen is tuning the gate — or the
  substrate — after seeing the numbers. **No constant, threshold, ordering or
  admission rule was touched after this pilot.**

The per-episode goal-known measurement, which is what makes the substrate work
at all: `opening_resolution_state == "resolved"` on every episode of both arms,
with the committed goal 12–15 m away — i.e. grounded from the navigator's own
memory of the taught drive, not from a sighting.

### 3.1 DISCLOSURE — Pilot B's cells are inside the gated sample

*(Revision 2, audit correction 4. Revision 1 did not state this and it should
have.)*

Pilot B ran `generate_route_memory_cells()[0:6]`, i.e. **episodes 00–05 of the
pre-registered gated 60** — verified: the six ids are exactly the first six of
the gated order. So **10 % of the gated sample had known paired outcomes at the
moment §1 was frozen**, and that is a real, if small, contamination of the
pre-registration.

* **What was known:** the six paired outcomes — one cell concordant-success
  (`…d7c1f694`), five concordant-failure. **No discordant pair was known**, and
  no flip in either direction had ever been observed on this substrate.
* **Bias direction: toward the observed null, not away from it.** Six cells known
  to be concordant make the pre-registered "≥ 6 net flips" *harder* to reach,
  not easier, because they are six cells that cannot contribute a flip. Had the
  gate PASSED, this disclosure would matter; it failed, and the known cells are
  part of why 6 flips were a demanding bar on 60 cells.
* **Robustness check, computed from the same artifacts:** excluding all six
  pilot cells, the paired table on the remaining **n = 54** is
  `both 6 / on_only 0 / off_only 0 / neither 48` — **net 0, exact McNemar
  p = 1.000**, identical to the full-set verdict. The result does not depend on
  the contaminated cells in any way.
* Nothing about the substrate, the ordering, the estimator or the thresholds was
  chosen after those six outcomes were seen; §3's "the pre-registration was
  frozen anyway, unchanged" is the record of that, and it is the reason the
  contamination is disclosable rather than disqualifying.

---

## 4. The substrate as built — `evals/nav_instruct/route_memory_cells.py`

| property | value |
|---|---|
| cells the admission rule admits | **434** |
| gated n (pre-registered prefix) | **60**, 10 per target × 6 targets |
| `cells_digest` | `a23c802b…64a` |
| sighting range (start → landmark) | 12.01 / 13.69 / 17.42 m (min/mean/max) |
| goal edge distance (beyond-reach) | 9.54 / 11.33 / 14.92 m |
| taught route length | 19.13 / 26.94 / 32.90 m |
| detour excess over the straight line | 5.03 / 13.27 / 17.59 m |
| straight-corridor min TRUE clearance | −1.76 / −0.74 / −0.38 m (all negative: the straight line runs INSIDE an obstacle) |
| taught-route min TRUE clearance | 0.85 / 0.89 / 0.93 m (all above the gate's 0.60 m stop floor) |
| start TRUE clearance | 1.04 / 2.05 / 3.64 m |
| goal-side attach distance | 1.80 / 2.22 / 2.41 m (all ≪ 8.05 m) |

Every number above is a generation-time measurement carried on the episode's own
`placement_overrides["route_memory_cell"]` block, so a persisted row is
self-describing and a claim about a cell can always be re-derived from the row.

**Derived constants, each by reference and pinned by
`tests/test_rm3_route_memory_arms.py::test_every_derived_constant_equals_its_live_source`:**

| constant | value | derivation |
|---|---|---|
| `ROUTE_MEMORY_REACH_M` | 8.05 m | `place_graph.DEFAULT_ATTACH_RADIUS_M`, asserted equal to `DirectiveNavigator.ROUTE_MEMORY_RANGE_M` — the number the mechanism itself uses |
| `OBSTACLE_STOP_FLOOR_M` | 0.60 m | `DEFAULT_SAFETY_ENVELOPE.obstacle_stop_floor_m`, live |
| `TEACH_WAYPOINT_TOLERANCE_M` | 0.25 m | `DEFAULT_KEYFRAME_SPACING_M / 2` — RM-2's own `DEFAULT_WAYPOINT_REACHED_M` derivation |
| `TEACH_MIN_CLEARANCE_M` | 0.85 m | stop floor + tracking tolerance: the gate's STOP branch cannot bind anywhere the follower can be. The weaker claim is the true one — the comfort band (1.2 m) is wider, so a taught leg may still be SLOWED, which the tick budget absorbs |
| `ROUTE_MEMORY_MIN_DETOUR_M` | 0.50 m | one `DEFAULT_KEYFRAME_SPACING_M`: the finest distinction the place graph can record, hence the smallest detour that is representable rather than a grid artefact |
| teach tick budget | derived | `2 × travel_ticks + one full π reversal per vertex`, both at the leg's own cruise / yaw rate |

None of them was re-picked after any measurement.

---

## 5. The taught leg — teaching by DRIVING, and its cost accounting

### 5.1 The seam

`NavInstructRunner` gained ONE additive parameter, `pre_drive`, invoked once per
navigation episode **after** the navigator is constructed and **before**
`navigator.start(directive)` — i.e. before the measured mission exists and before
one tick of its budget is spent. Default `None`, and `None` is not "an empty
pre-drive": `_run_navigation` never calls it, so the measured path gains no code.

### 5.2 Out and back, not out-then-teleport

The first draft drove out and then `world.reset(...)`-ed back to the start. That
is dishonest in a way that matters: `reset()` sets `data.time = 0`, so the
grounder's semantic memory would be recalling entities it observed *in the
future*, and RM-1's ingest track would have to be broken across a teleport that
never happened. The taught leg now drives **out and back over the same
polyline**, so the taught leg and the measured mission are one continuous
session: monotone clock, unbroken pose history, and a memory whose observations
are all in the past. It is also what RM-2's own gate-(b) corridor did (A→B→A,
then task a goal near B).

Consequences, all recorded rather than assumed:

* the measured mission starts within `final_gap_m` of the declared start pose
  (measured 0.21–0.25 m, i.e. inside the follower's own 0.25 m tolerance);
* the world's collision counter is **not** zeroed — the taught leg's motion
  really happened, so its collisions belong to the episode. Measured: zero, on
  every cell of both arms;
* the taught leg's ticks are reported (`teach_ticks`) and charged to nothing.

### 5.3 Why the navigator's own commands are discarded

The measured task is exactly "can normal planning get there". Letting normal
planning drive the taught leg would either succeed — in which case the cell is
not a beyond-reach cell — or fail, in which case there is no taught route. The
card allows either form ("scripted pre-drive **or** a first directive leg"); on
this substrate only the scripted form can produce the route. The pipeline is
still stepped on every tick, which is how `_route_memory_teach` ingests and how
the grounder's memory sees the target.

### 5.4 The counters are deltas, not totals

The pipeline is LIVE during the taught leg and does query memory there — Pilot A
measured up to 140 taught-leg queries on one cell. Every measured-mission
counter in this document is therefore a **delta** against a snapshot taken at
the end of the taught leg (`pre_drive.counters`), so a taught-leg query can
never be reported as a measured-mission one.

---

## 6. Measured

### 6.0 The two runner seams are inert on the frozen path — re-measured

RM-3's edits live in `_run_navigation`, which is the frozen measurement path, so
"additive" had to be measured rather than argued. AF-2's own recipe, at this
card's final source state, v4 minival, `--mode baseline`,
`--budget-policy scaled-path-v1`, `--max-steps 200`, `--seed 20260804`, driven
through `NavInstructRunner` directly so no ledger row is written:

```
episode_digest            4113607b92c734dfdd46004b6e77baf6575fc2a1c493e5d9dc5a12c6c5490222   (unmoved)
episodes payload sha256   bfb21cd25be4db9e02b3944479cfaf068d8f17f333743c32adc25c0b9d6ea8ca   (reproduced exactly)
any row carrying route_memory   False
any row carrying pose_drift     False
```

Both values are RM2_STATUS §5.1's, to the last byte. The row SHAPE is unchanged
too: a run that names neither `route_memory` nor a pose profile stamps neither
key, which is the same rule DR-2 established.

### 6.1 GATED — the paired arms, and the pre-registered verdict

> ## ⛔ THE PRE-REGISTERED GATE **FAILS** ON HONEST NUMBERS
>
> **0 net paired flips** against a pre-registered ≥ 6, and an exact McNemar
> **p = 1.000** against a pre-registered ≤ 0.031. Nothing was tuned, nothing was
> dropped, no constant was re-derived after the numbers were seen, and the
> substrate was not touched after the pre-registration was frozen. Per the card
> this is a reportable scientific result and it is recorded as one.

n = 60, default matcher, isolated processes, one world per episode.

| | ON | OFF |
|---|---|---|
| SR | **0.11667** (7/60) | **0.11667** (7/60) |
| mean distance-to-goal | 9.8507 m | 9.7822 m |
| mean path travelled | **7.51 m** | **5.04 m** |
| collisions | **0** | **0** |
| `false_arrival` | **0** | **0** |
| elapsed | 1153.8 s | 1115.3 s |

**The paired 2×2, which is the actual gate:**

| | OFF succeeds | OFF fails |
|---|---|---|
| **ON succeeds** | **7** | **0** (`on_only`) |
| **ON fails** | **0** (`off_only`) | **53** |

* net flips = `on_only − off_only` = **0** (pre-registered ≥ 6) — **FAIL**
* discordant pairs = **0**
* exact McNemar p = **1.000** (pre-registered ≤ 0.031) — **FAIL**

**Failure-class histograms are identical between the arms:**
`navigation_no_progress` 30, `semantic_target_unreachable` 23,
`arrived_verified` 7 — on both.

**And yet the arms are NOT the same run.** This is the part that makes the
result informative rather than vacuous:

| | measured |
|---|---|
| cells whose terminal reason differs between the arms | **10 / 60** |
| cells whose distance-to-goal differs by > 0.05 m | **31 / 60** |
| cells whose trace length differs | **27 / 60** |
| distance-to-goal delta (ON − OFF) | mean +0.069 m, median 0.000, range **−8.358 … +7.917 m** |
| path travelled | ON **+49 %** (7.51 m vs 5.04 m) |

Route memory changed what the robot did on roughly half the substrate, moved it
half again as far, and moved **no episode across the success boundary in either
direction**. The 7 successes are the *same 7 cells* on both arms, and **not one
of them armed a chain** (`chain_ticks = 0` on all seven): the cells route memory
helps with and the cells the robot can already solve are disjoint here.

### 6.2 Non-vacuity — the ON arm's counters, measured-mission only

Every number below is a DELTA against the taught leg (§5.4), i.e. the measured
mission's own activity.

| counter | value |
|---|---|
| episodes that queried memory | **42 / 60** |
| episodes memory returned a route for | **42** |
| episodes whose waypoint **won** arbitration | **42** |
| armings (`routes_found`, total) | **53** across those 42 episodes — 10 re-armed (§6.3) |
| waypoints that won arbitration (`wins`, total) | **54** — armings plus one mid-chain advance |
| waypoints vetoed | **0** |
| chain ticks driven | **4892** (mean 116 per armed cell) |
| chain-tick distribution over armed cells | 14, 52, 53, 53, 60 ×20, 135 ×2, 140 ×3, 142, 144, 183, 188, 197, 200 ×5, 276, 280, **420** |
| hand-backs | **31** |
| deferred releases (trigger (i) only) | **4**, on 2 cells |
| armed cells that then SUCCEEDED | **0 / 42** |

So the mechanism is not merely reachable, it is **routinely exercised**: on 70 %
of the substrate the pipeline consulted the place graph, got a recorded route,
published a stamped `SE2Goal`, won arbitration against the lethal veto, and
drove the waypoint chain — 4892 ticks of motion that the flag-OFF arm did not
have. The conversion of that into arrivals is **zero**, and §7.1 is the measured
reason.

The OFF arm's control row is the other half: `routes_found = 0`,
`chain_ticks = 0`, `hook = None` on every episode. It is not "route memory that
found nothing", it is route memory that does not exist there.

### 6.3 Trigger (ii) coverage — the audit's binding item, CLOSED

`AUDIT_WAVE2_FABLE.md`: *"Trigger (ii) is unmeasured. RM-3's cell set should
include at least one partial-plan non-progress cell, or report it as still
unmeasured."*

**Measured, and trigger (ii) is dominant — but the units matter.** *(Revision 2,
audit correction 3: revision 1 reported "38 of 42 / 4 of 42", which conflated
three different quantities. The corrected decomposition is below, and every
number in it is the artifact's.)*

Three counters, three meanings, none of them interchangeable:

| counter | what it counts | total | episodes |
|---|---|---|---|
| `routes_found` | **armings** — `waypoints_toward` returned a non-empty chain | **53** | 42 (histogram: 32×1, 9×2, 1×3 ⇒ **10 episodes re-armed**) |
| `wins` | **waypoints that won arbitration**, armings *plus* mid-chain advances | **54** | 42 |
| `deferred_releases` | **deferral EVENTS** — ticks on which trigger (i)'s door suspended the release. `_route_memory_defer_release` returns `True` for an already-live chain *without arming* (`pipeline.py:4504`), so this is not an arming count | **4** | **2** |

Honest decomposition of the 42 armed episodes:

* **40 episodes show zero trigger-(i) activity**, so every one of their armings
  came through `_route_memory_partial_recovery`, trigger (ii);
* **2 episodes** (`…07-dcd45d5f`, `…13-575cb864`) show trigger-(i) deferral
  events, 2 each. Each of those armed **exactly once** (`routes_found = 1`,
  `wins = 1`), so **at most 2 of the 53 armings** are attributable to trigger
  (i) and **at least 51 to trigger (ii)**.

The 10 re-armed episodes are RM-2 finding F3's watchdog re-arm behaviour, which
`RM2_STATUS.md` §5.6 records as a two-sided design decision and
`test_a_watchdog_replan_re_commits_and_re_arms_by_design` pins as **INTENDED**:
a 400-tick progress-watchdog replan re-grounds and re-commits the same candidate
and gets a fresh chain. Seeing it 10 times in 60 episodes is that pinned
behaviour appearing on a live substrate for the first time.

Corroborated directly rather than only by arithmetic: the instrumented
single-cell trace in §7.1 reads
`mission.metadata["route_memory_trigger"] == "partial_non_progress"` at the tick
the chain arms, with `last_route_status == "partial"` and
`_steps_without_progress` past the 60-tick hysteresis.

The counter semantics above are now pinned by
`test_deferred_releases_counts_deferral_ticks_not_armings` so the next reader
cannot repeat the conflation.

This is the exact complement of RM-2's own evidence, whose measured rows all
came through trigger (i) on a scripted corridor. Between the two cards both
doors are now measured — on different substrates (§9 handoff 3).

### 6.4 Isolation, verified rather than asserted

| pre-registered property | verification |
|---|---|
| one process per arm | `both` spawned two `run` subprocesses; the parent constructed no navigator. Their elapsed times differ (1153.8 s vs 1115.3 s) because they are separate processes. |
| one world per episode | a fresh `NavInstructRunner` per episode by construction — the driver has no other mode. `HeadlessCityWorld._scan_rng = np.random.default_rng(7)` per construction, so every episode draws the same scan stream in both arms. |
| mission boundary per leg | fresh navigator ⇒ fresh place graph and fresh semantic memory; inside the episode the taught leg's `start()`/`stop()` each call `_reset_route_memory_track()`. Measured consequence: the ON arm's per-episode `taught_leg_counters.keyframes` is bounded by that episode's own drive (mean 47), never cumulative. |
| **the taught leg is identical between the arms** | **0 of 60 episodes** differ in `teach_ticks` or `final_gap_m`; 60/60 taught legs completed and reached the goal end; **0 taught-leg collisions on either arm**. Total taught ticks 70 292 per arm, identical. |
| determinism | the 2-cell smoke run and the 60-cell sweep produce bit-identical rows for the cells they share. |

Taught-leg cost, for the record: 834–1436 ticks per episode (mean 1172), and
none of it charged to the measured budget (758–1200 ticks, §1.4).

### 6.5 Artifacts

All candidate-only, all under the `rm3-` namespace, none a frozen baseline, and
no ledger row written by this card:

| file | what |
|---|---|
| `evals/nav_instruct/results/rm3-on-default-20260812T083551Z.json` | gated ON arm, n = 60 |
| `evals/nav_instruct/results/rm3-off-default-20260812T083551Z.json` | gated OFF arm, n = 60 |
| `evals/nav_instruct/results/rm3-pair-default-20260812T083551Z.json` | the paired table above |
| `evals/nav_instruct/results/rm3-v4s-on-default-20260812T084541Z.json` | report-only v4s LA/BB, ON |
| `evals/nav_instruct/results/rm3-v4s-off-default-20260812T084541Z.json` | report-only v4s LA/BB, OFF |
| `evals/nav_instruct/results/rm3-pair-v4s-default-20260812T084541Z.json` | its paired table |
| `evals/nav_instruct/results/rm3-v4r-on-default-calibrated_go2-20260812T085436Z.json` | report-only drifted arm, n = 6 |

Both gated artifacts carry the same `cells_digest`
(`a23c802b…`), the same `n`, the same matcher arm and the same (null) pose
profile — `pair_arms` refuses to build a table otherwise.

**Two disclosures about the artifacts themselves** *(Revision 2, audit
corrections 5a and 5b)*:

* **The persisted `set_provenance` string is STALE.** It reads "every scene cell
  whose target is **sighted** from the start…", which is Pilot A's admission
  rule; the substrate that actually ran is the KNOWN / out-of-frustum one (§1.2
  rule 1). It is a **wording defect in a header string only** — no admission
  test, no cell, no measured number is affected, and the authoritative
  description of every cell is its own `placement_overrides["route_memory_cell"]`
  block, which carries `visible_from_start: False` and
  `visibility_max_range_m: 12.0` on all 60 rows. The string is fixed in
  `route_memory_cells.py` for future runs; **the persisted artifacts were NOT
  regenerated**, so the ones quoted here still carry the stale wording.
* **The gated artifacts predate a mid-session driver revision.** The
  `20260812T083551Z` pair was written by the driver as it stood when the sweep
  launched; the shipped `run_route_memory_arms.py` has since gained a
  `taught_leg` header field, `graph` / `pose_drift` row keys (added for the
  drifted arm) and a substrate-qualified artifact filename. So the gated rows
  carry a slightly older schema than the v4s and drifted artifacts. **The audit
  verified that the shipped driver reproduces the gated rows bit-identically**,
  which is what makes the schema difference cosmetic; none of the added fields
  feeds the paired table, and `pair_arms` reads only fields present in both.

### 6.6 Report-only — v4s LA/BB, ON vs OFF (no gate)

n = 120 (LA 60 + BB 60), default matcher, isolated processes, no taught leg —
**and the absence of a taught leg IS the arm**. These cells are straight
corridors, so an episode's own traversal never covers a route the planner cannot
already see, which is precisely why the plan re-registered the gate away from
them.

| | ON | OFF |
|---|---|---|
| SR | **0.0000** | **0.0000** |
| mean dtg | **12.2193 m** | **12.2193 m** |
| collisions | 0 | 0 |
| `false_arrival` | **11** | **11** |
| place-graph keyframes / edges | **1241 / 1122** | 0 / 0 (no graph) |
| routes found / proposals / wins | **0 / 0 / 0** | 0 / 0 / 0 |
| chain ticks | 0 | 0 |
| elapsed | 405.9 s | 404.5 s |

**Verdict: a measured no-op, in the strongest available form.** The 2×2 is
`both 0 / on_only 0 / off_only 0 / neither 120`, net flips 0, exact McNemar
p = 1.000, and the two arms agree on the mean distance-to-goal *to four decimal
places* — i.e. the arms did not merely score the same, they behaved the same.

The load-bearing row is the last two: auto-teach **ran** (1241 keyframes, 1122
edges recorded across the 120 episodes), memory was **available**, and it
offered a route **zero** times. That is RM-1's fail-closed `()` contract doing
exactly what the honesty rule says it must on a substrate where no recorded
route can help, observed on a live product path rather than argued.

The 11 `false_arrival` verdicts are **identical on both arms** and are the
pre-existing default-matcher cross-class artefact `episodes/V4S_MATCHER_ARM.md`
documents (owner decision-queue item 4). Route memory neither caused nor changed
one of them, which is the only claim this card makes about them.

### 6.7 Report-only — the drifted arm (`calibrated_go2` × route_memory ON)

**Stated prefix, not the full set: n = 6**, the first six cells of the same
round-robin order. Report-only, no gate, no floor. Two runs at larger n were
started and abandoned to CPU contention rather than presented at a truncated
size after the fact; this one ran to completion (126.5 s) and is the whole of
what is claimed. Artifact:
`rm3-v4r-on-default-calibrated_go2-20260812T085436Z.json`.

B5 does not contaminate it, exactly as the audit says: `calibrated_go2` has
`map_correction` off, so `_maybe_correct_map` assigns `MAP := truth` every tick
and the arrival predicate reads an exact pose.

| episode | ODOM divergence | in band | graph keyframes / edges | re-anchor events | routes found / chain ticks | truth-arm outcome |
|---|---|---|---|---|---|---|
| …95c11929 | 3.61 % (0.295 m / 8.17 m) | ✓ | 51 / 50 | **0** | 2 / 200 | `semantic_target_unreachable` |
| …d7c1f694 | 7.66 % (0.620 m / 8.10 m) | ✓ | 72 / 71 | **0** | 0 / 0 | **`arrived_verified`** |
| …09d9541d | 1.61 % (0.038 m / 2.37 m) | n/a | 45 / 44 | **0** | 0 / 0 | `navigation_no_progress` |
| …8249b0a1 | 1.73 % (0.043 m / 2.47 m) | n/a | 51 / 50 | **0** | 1 / 60 | `navigation_no_progress` |
| …49d40d2e | 1.57 % (0.228 m / 14.52 m) | ✓ | 82 / **82** | **0** | 1 / 140 | `navigation_no_progress` |
| …3302fe0d | 4.09 % (0.257 m / 6.28 m) | ✓ | 63 / 62 | **0** | 1 / 56 | `semantic_target_unreachable` |

Arm totals: SR **0.000** (0/6, against 1/6 on the truth arm over the same six
cells), collisions **0**, `false_arrival` **0**, 6 distinct per-episode seeds,
4 of 6 episodes in DR-2's pre-registered band (the other two travelled less than
`DIVERGENCE_BAND_MIN_TRAVEL_M = 5.95 m`, where DR-2's own rule does not apply
the band and records the raw metres instead), arm-mean divergence 3.38 %.

**Keyframe integrity under drift — what is and is not shown.**

* **`graph_reanchor_events = 0` on every episode.** No edge was laid across a
  MAP discontinuity, and RM-1's distance backstop (`max_contiguous_step_m`)
  never fired either — every recorded edge is a contiguous, routable traversal.
* **Edges = keyframes − 1 on five of six**, i.e. an unbroken chain; the sixth
  (82 / 82) has one extra edge, which is the out-and-back leg closing a loop
  onto a keyframe it had already recorded. Both shapes are what a continuous
  drive should produce; neither is a jump.
* **MAP-frame discipline is OBSERVED, not tested.** On this profile MAP *is*
  truth, so the keyframes are exact by construction. What the arm demonstrates
  is that the ingestion path stays on the MAP seam and produces a clean graph
  while ODOM diverges 1.6–7.7 % underneath it — it cannot demonstrate that the
  graph survives a MAP that actually moves. That needs a `map_correction`
  profile, i.e. B5's territory, which the card deliberately keeps out of RM-3
  (§8, §9.4).
* **Route memory still fires under drift**: 4 of 6 episodes armed and won a
  chain, 456 chain ticks. One cell that arrives on the truth arm
  (`…d7c1f694`) fails here — a drift effect on the CONTROLLER, not on the
  graph, and n = 6 is far too small to say anything more than that.

### 6.8 Teach-and-repeat — SR and path fidelity vs the taught line

Derived from the gated arms rather than run as a third sweep (DR-2's precedent
for a derived table, and stated as derived). The "repeat" is the memory-driven
replay: the taught leg is the demonstration, and the measured mission is the
robot's attempt to get there again, with the recorded route available to it.

**Fidelity** is measured two ways on purpose, because either alone is
misleading: `mean_m` is the deviation of every traced position from the taught
polyline, and `coverage` is the fraction of taught vertices the run came within
0.5 m of. A robot frozen at the start scores a *perfect* mean deviation and
repeats nothing —
`test_seeded_a_run_that_never_left_the_start_has_tiny_deviation_and_no_cover`
pins exactly that failure.

| | ON | OFF |
|---|---|---|
| SR ("repeat succeeds") | 0.11667 (7/60) | 0.11667 (7/60) |
| mean deviation from the taught line | 1.959 m | 1.859 m |
| median deviation | 1.831 m | 1.764 m |
| taught-vertex coverage | **0.150** | **0.148** |
| path travelled | **7.51 m** | 5.04 m |
| — restricted to the 42 chain-driven cells — | | |
| mean deviation | 1.682 m | 1.539 m |
| coverage | 0.154 | 0.152 |

**Read honestly: teach-and-repeat does not replay the taught line here.**
Coverage is ~15 % on both arms, and the ON arm's deviation is if anything
slightly *larger* than the OFF arm's. That is not a contradiction of §6.2 — the
chain is driven, and the ON arm travels 49 % further — it is what the mechanism
is: RM-2 aims at the furthest recorded keyframe inside an 8.05 m *recorded-path*
bound and hands the leg to grid_v1, which drives its own route to that aim
point. The waypoint is an aim point, never a path to be tracked
(RM2_STATUS §7 says the same about the lethal veto). A card that wants literal
replay wants `teach_repeat.follow`, which has no product consumer today.

The one thing the fidelity table does establish: the ON arm's extra 2.5 m of
travel per episode is not random wandering — it is spent no further from the
taught line than the OFF arm's shorter path was.

---

## 7. Defects found, and the one that decides this card's result

`src/**` is frozen for a measurement card, so every item here is a **handoff**
(§9), reproduced and stated, never edited.

### 7.1 The velocity wedge — measured, and the reason an aim point cannot help

**Reproduced on** `nav-rmem-object_goal-00-95c11929`, ON arm, ticks 118–160,
with per-tick instrumentation of the pipeline's own returned command:

```
tick pos            heading  cmd            obstacle  bearing  chain  note
118  (7.26, 1.52)   -152 deg vx=0.000 …     0.80 m    -0.33    51     grid_align  err=69.1 route=2 status=planned|obstacle_slow
137  (7.26, 1.52)    -89 deg vx=0.000 …     0.80 m    -1.43    51     grid_track  err=6.0  goal=7.9 route=2 status=planned|…
150  (7.26, 1.52)    -84 deg vx=0.000 …     0.80 m    -1.52    51     grid_track  err=0.8  goal=7.9 route=2 status=planned|…
160  (7.26, 1.52)    -84 deg vx=0.000 …     0.80 m    -1.53    51     grid_track  err=0.2  goal=7.9 route=2 status=planned|…
```

Read it in order:

1. Route memory did **everything it is supposed to do**: a chain of 51 recorded
   keyframes is live, the interim waypoint won arbitration, and the planner
   reports `planned` with a 2-waypoint route to it, 7.9 m away.
2. The controller aligns to that route — the tracking error decays 69° → 0.2°.
3. And the commanded `vx` is **0.000 on every one of those ticks** — a
   **chain-live wedge of ~61 consecutive zero-`vx` ticks** at `(7.26, 1.52)`.
   *(Revision 2, audit correction 2.)* Revision 1 said the robot "sat there for
   the remaining ~450 ticks… identically on the flag-OFF arm". **Both halves of
   that were wrong**, and the artifact refutes them:
   * the wedge is bounded, not permanent — **163 of the 419 post-wedge ticks**
     are `vx = 0`, and the episode ends at `(12.878, 1.498)`, **5.6 m away** from
     the wedge, having travelled **6.06 m** in total;
   * the arms are **not** identical on this cell. ON ends
     `semantic_target_unreachable`, dtg **15.454 m**, trace 579, path 6.06 m;
     OFF ends `navigation_no_progress`, dtg **9.865 m**, trace 646, path
     **0.43 m**. On this cell the flag-OFF arm is the one that barely moved, and
     the ON arm ended **materially further from the goal**.

   That correction strengthens the null result rather than weakening it: route
   memory does break the wedge and does move the robot, and the motion it buys
   is not motion toward an arrival.
4. **`apply_collision_brake` IS the module that zeroes the command.** *(Revision
   2, audit correction 1 — revision 1 exonerated it, and did so by feeding it
   the wrong policy.)*

   Revision 1 evaluated the brake with the **module-default** `CollisionPolicy()`
   — `obstacle_stop_m = 0.6`, `predictive_mode = "stop"` — and got `'clear'`.
   The quoted "projected speed limit 40.9 m/s" is itself the fingerprint of that
   mistake: `(0.80 − 0.60) / 0.12 / cos(1.53) = 40.9`, i.e. a 0.60 m stop radius.

   The pipeline does not use that policy. `DirectiveNavigator.from_config` builds
   `CollisionPolicy(obstacle_stop_m = safety.stop_distance_m, predictive_mode =
   safety.predictive_mode)` from `configs/navigation/default.yaml`
   (`pipeline.py:819`, `:861-863`), where `stop_distance_m: 0.8` and
   `predictive_mode: projected_speed_cap` (`default.yaml:92`, `:97`). Under a
   truth pose `pose_aware_collision_policy` returns that same object. Re-run with
   the policy the product actually builds:

   ```
   CollisionPolicy(obstacle_stop_m=0.8, predictive_mode='projected_speed_cap')
   nearest_obstacle_m = 0.800, bearing = -1.53  (closing_fraction = 0.041)
     request vx=0.09  ->  (0.0, 0.0, 'obstacle_stop')
     request vx=0.30  ->  (0.0, 0.0, 'obstacle_stop')
     request vx=0.85  ->  (0.0, 0.0, 'obstacle_stop')
   ```

   The grid controller **was** requesting 0.09 → 0.85 m/s across ticks 137–165;
   the audit instrumented **63 brake calls zeroing a non-zero request** on this
   cell. So the mechanism is exact: `nearest_obstacle_m = 0.800 ≤
   obstacle_stop_m = 0.8` reaches the hard stop (`collision.py:152-155`) because
   the projected-mode relevance gate admits **any positive closing fraction**
   (`collision.py:135`) — and 0.041 is positive. A static obstacle sitting at
   exactly the configured stop radius, **88° off the travel axis**, hard-stops
   the body.
5. The obstacle is an **unmapped crate** — `obstacle_crate`, in the MuJoCo scene
   and in no landmark table — 0.80 m from the robot's footprint at a bearing of
   ≈ −88°, i.e. very nearly perpendicular to the direction of travel.

**Ownership: this is a pre-existing product defect, not route memory's.** The
audit executed the same cell **flag-OFF** and reached the same wedge; the OFF
arm's 0.43 m of travel on this cell is what being wedged from the first tick
looks like. Route memory does not cause it — it **exposes it at scale**, because
a memory waypoint keeps handing the controller reachable targets that the brake
then refuses to move toward. That is exactly why the gate nulled.

**What this means for RM-3, precisely.** Route memory's entire output is an
*aim point*; grid_v1 and the reactive gate own every velocity (rule 4, and
RM2_STATUS §7 says the same). When the brake zeroes the command, a better aim
point changes nothing — and on this substrate that is the dominant failure mode.
The mechanism is reachable (it arms, wins, and drives) and its conversion is
bounded above by whether the body is allowed to move at all.

### 7.2 The unmapped-obstacle class, and DR-2's handoff 2 confirmed

`obstacle_crate` is in the world's occupancy and in **neither** the landmark
table nor `_v4s_blocking_discs`. That is DR-2's handoff 2 ("the admission rule
under-approximates geometry… the single largest driver of the substrate's low
SR") in a stronger form than DR-2 stated it: the disc model is not merely
optimistic about building shape, it is **blind to an entire scene object**.
`v4r` closes it for itself by taking occupancy from
`HeadlessCityWorld.truth_minimum_clearance`; `v4d` cannot, because a floor
derived from the current cell set is pinned against it.

---

### 7.3 What the negative result does and does not say about route memory

Stated plainly, because a failed gate is easy to over-read in either direction:

* **It is not "the flag does nothing".** 42 of 60 measured missions consulted
  memory, won arbitration and drove a chain; the arms differ on 31 of 60 cells
  by distance-to-goal and the ON arm travels 49 % further. The wiring RM-2 built
  works end to end on the real product path, which no eval had ever shown.
* **It is not "route memory is harmful" either.** `off_only = 0`: no episode was
  lost to having the flag on. Collisions 0 and `false_arrival` 0 on both arms,
  so the safety invariants are untouched — a memory waypoint is arbitrated, and
  0 of 42 were vetoed while 0 of 60 episodes collided.
* **What it says is that on THIS substrate the bottleneck is not the one route
  memory converts.** The card's question is "does place memory convert the
  measured bottleneck (planner ~8 m vs sensing 12+ m)?" On `v4r` the answer is
  **no, because a different bottleneck binds first**: the reactive brake zeroes
  the body's velocity (§7.1) before the aim point can matter, and it does so
  flag-OFF too. Route memory hands the planner a reachable target; it cannot
  hand the body a velocity that the brake has taken.
* **And the substrate is the honest one to have asked on.** Every clause of the
  memory-honesty rule is a generation-time test, the taught route is driven
  rather than declared, the goal is genuinely beyond reach and genuinely known,
  and the ON/OFF arms differ in exactly one flag with the identical taught leg.
  If the mechanism had a flip in it on this scene, this is where it would show.

---

## 8. does_not_prove

* **One scene, one simulator, sim-truth semantics.** Every cell is
  `HeadlessCityWorld`'s single city block with the default matcher's
  string/alias fallback. Nothing here is camera perception, and RM-1's and
  RM-2's own `does_not_prove` stand unchanged underneath this card.
* **The taught leg is a SCRIPTED demonstration.** A human did not drive it, a
  voice did not ask for it, and no policy learned it. What it proves is that the
  product path ingests, routes over and drives a graph built from real motion —
  not that any of the ways a user would actually teach a route work.
* **Nothing here measures cross-session recall.** The place graph is
  session-scoped (RM-2 never calls `save`/`load`), so "the robot remembers the
  route" means "within this process". The owner-gated persistence OPEN item is
  untouched.
* **The gated result is a statement about THIS substrate.** `v4r` is 60 cells
  drawn from 434 admissible ones by a fixed rule on one scene. A different scene
  — one with longer detours relative to the planner window, or without the
  wedge of §7.1 — could give a different answer, and this card does not bound
  that either way.
* **A paired flip is a success/failure flip, and nothing finer.** The
  pre-registered estimator reads `score.success` only. Distance-to-goal, path
  and tick deltas are reported next to it and are not part of the gate.
* **The drifted arm reports keyframe integrity, not drift robustness.** On
  `calibrated_go2` MAP is truth-passthrough (`pose.py:564-570`), so the place
  graph's MAP-frame keyframes are exact by construction and the arm can only
  confirm that the discipline is observed — it cannot test the graph against a
  drifting MAP. That test needs a `map_correction` profile, which is exactly
  where backlog **B5** lives, and the card explicitly keeps B5 out of RM-3.
* **The v4s report-only arm proves a no-op, which is weaker than it sounds.**
  It confirms that route memory does not fire where the memory-honesty rule says
  it cannot; it does not prove the flag is inert in general.
* **The taught leg's own success is not the mechanism's.** Every admitted cell's
  taught leg completes because the substrate was built so that it can. A cell
  where the demonstration itself failed would be excluded, and none of the
  reported numbers describe how hard the route was to drive.
* **`route_memory` telemetry is append-only evidence.** No number in the
  `route_memory` block is read by any decision, in the pipeline or here.

---

## 9. Handoffs

1. **[OWNER / a reactive-safety or config card] The perpendicular hard stop at
   the configured stop radius (§7.1).** *(Re-targeted in revision 2 — revision 1
   pointed this at the grid controller on the strength of an exoneration that
   used the wrong `CollisionPolicy`. `grid_navigator.py` is NOT the target.)*

   **The defect is the brake/config interaction.** With the policy the product
   actually builds — `CollisionPolicy(obstacle_stop_m = 0.8, predictive_mode =
   'projected_speed_cap')` from `configs/navigation/default.yaml:92,97` via
   `pipeline.py:819,861-863` — a **static** obstacle at `nearest_obstacle_m =
   0.800`, i.e. exactly the configured stop radius, and at a bearing **88° off
   the travel axis**, returns `(0.0, 0.0, 'obstacle_stop')` for every requested
   speed. The reason is that in the projected-cap modes the relevance gate is
   `closing_fraction > 1e-9` (`collision.py:135`), which admits a closing
   fraction of **0.041**, and the hard-stop test that follows
   (`collision.py:152-155`) is a bare `nearest_obstacle_m <= obstacle_stop_m`
   with no directional term. The comment above the gate says "purely
   tangential/away motion remains free"; at 88° the motion is very nearly
   tangential and it is not free.

   Measured consequence on `nav-rmem-object_goal-00-95c11929`: **63 brake calls
   zeroing requests of 0.09–0.85 m/s** across ticks 137–165, a ~61-tick wedge
   with a live memory chain and a valid `planned` route, and 163 of the 419
   post-wedge ticks still at `vx = 0`.

   **It is flag-independent** — the audit reproduced the wedge on the same cell
   with `route_memory` OFF, where the episode travels 0.43 m in 646 ticks. Route
   memory does not cause it; it exposes it at scale, which is why the gate
   nulled. The decision is whether the hard stop should carry a directional term
   (or whether `obstacle_stop_m` should be below the clearances the scene
   actually produces). `navigation/collision.py`, `navigation/pipeline.py` and
   `configs/navigation/default.yaml` are all outside this card's OWNS; not
   attempted. Reproduction:
   `evals/nav_instruct/run_route_memory_arms.py run --arm on --limit 1` with
   per-tick instrumentation of `DirectiveNavigator.step` and of
   `apply_collision_brake`'s arguments.
2. **[SUBSTRATE / DR-2's handoff 2, strengthened] Unmapped scene objects.**
   `obstacle_crate` is a MuJoCo obstacle that appears in no landmark table, so
   every disc-model admission rule in `generator.py` is blind to it. `v4r` reads
   `HeadlessCityWorld.truth_minimum_clearance` instead and the module documents
   why; the v1–v4s and `v4d` generators still do not, and `v4d`'s pinned floors
   mean the fix there is a re-derivation rather than an edit.
3. **[RM-2] The two triggers are measured on disjoint substrates.** RM-2's own
   measured rows all came through trigger (i) on a scripted corridor; on `v4r`,
   **40 of the 42 armed episodes show no trigger-(i) activity at all**, and of
   the 53 armings **at most 2** are attributable to trigger (i) (§6.3), because
   `RollingGridPlanner` reports `partial` rather than `goal_blocked` for a
   clipped beyond-window goal. Between the two cards both doors are now
   measured, but neither has been exercised on the other card's substrate, and
   no substrate exercises both in quantity.
4. **[OWNER] `ARRIVAL_BOUNDARY_EPSILON_M` / B5 is untouched here.** The gated
   arms run truth MAP, so the Wave-2 arrival-honesty finding cannot contaminate
   them, and this card adds nothing to it.
5. **[CI] No nightly arm was added.** A 60-cell paired sweep with taught legs is
   ~40 minutes of simulation per invocation — far outside the "cheap and clearly
   labeled" bar the card sets for a `ci_gate` addition. `ci_gate --tier commit`
   gains only `tests/test_rm3_route_memory_arms.py` (pure + world-construction
   only). Registering the sweep nightly is a follow-up decision, not this card's.

---

## 10. OWNS compliance, with git-diff numbers

| file | numstat | RM-3's share |
|---|---|---|
| `evals/nav_instruct/runner.py` | +584 / −17 | **+143 / −0**. The other +441 / −17 is DR-2's drift plumbing (+431 / −12, DR2_STATUS §8) plus the earlier `ALLOWED_NAVIGATOR_OVERRIDES` growth (+10 / −5) of cards D15-B / VS-4. RM-3 deleted **no** line of this file: the allowlist comment lines it rewrote were added inside this batch, not in `HEAD`. |
| `evals/nav_instruct/route_memory_cells.py` | NEW, 1035 lines | RM-3 |
| `evals/nav_instruct/run_route_memory_arms.py` | NEW, 617 lines | RM-3 |
| `tests/test_rm3_route_memory_arms.py` | NEW, 519 lines, **34 tests** | RM-3 |
| `tests/test_e4_evidence_seams.py` | +24 / −1 | **+10 / −0**: one line in the set literal (`"route_memory"`) plus a 9-line enumerated-amendment citation. The other +14 / −1 is the earlier `person_aware_nav` / `lock_on_verify_on_approach` growth of cards D15-B / VS-4, already in this batch. |
| `tests/test_person_aware_nav.py` | (untracked in `HEAD`) | one assertion `== 4` → `== 5` with its amendment citation |
| `scrum/20260811/task_2/RM3_STATUS.md` | NEW | this file |
| `evals/nav_instruct/results/rm3-*.json` | NEW | candidate-only artifacts, own `rm3-` namespace |

**In OWNS, NOT edited:** `evals/nav_instruct/run_nav_instruct_v1.py`. RM-3 needs
nothing there — the paired sweep is its own driver, so the frozen CLI keeps its
frozen shape. `grep -n route_memory evals/nav_instruct/run_nav_instruct_v1.py`
returns nothing; its +194 / −23 diff is DR-2's and earlier cards'.

**MUST-NOT-TOUCH honoured.** `src/**` is byte-untouched by this card —
`git status --porcelain src/` lists only the concurrent batch's files, and
`git diff` on none of them contains a Wave-3 hunk. Frozen episodes and digests
are untouched (`v4r` is not a member of `generator.EPISODE_SETS`, so `--freeze`
cannot reach it and no `v4r` row is ever a frozen baseline);
`configs/navigation/default.yaml` still ships `route_memory: false` and every
ON arm is a per-run override; `scripts/ci_gate.py` is untouched (§9 handoff 5).

**Two enumerated amendments**, both pinned-allowlist test edits the card
pre-authorises as such:

* `tests/test_e4_evidence_seams.py` — the exact-set assertion gains
  `"route_memory"`, with the amendment citation naming the card, the handoff it
  closes (RM2_STATUS §8.2 handoff 2) and the default-False guarantee that makes
  a one-name growth safe;
* `tests/test_person_aware_nav.py` — the EXACT count assertion moves 4 → 5, with
  the same citation. The count stays exact on purpose: no flag may appear
  undeclared.

**Ruff.** `.parcel/bin/ruff check` over every file this card touched: **All
checks passed**. Several new fingerprints appeared while writing
(`RUF007`, `RUF046`, `SIM102`, `I001`) and were **fixed, not baselined**.

**Revision 2's own diff**, for the audit's re-check — three files, all inside
OWNS, no sweep re-run and no artifact rewritten:

| file | revision-2 change |
|---|---|
| `scrum/20260811/task_2/RM3_STATUS.md` | the four upheld corrections, each marked *(Revision 2)* in place: §7.1(3), §7.1(4), §9.1, §6.3, §3.1 (new), §1, §6.5 |
| `evals/nav_instruct/route_memory_cells.py` | `ROUTE_MEMORY_PROVENANCE` wording only (audit 5a), with a comment recording that the already-persisted artifacts keep the old string and were NOT regenerated. No admission test, constant or generated cell changes — `cells_digest` is still `a23c802b…`, re-verified after the edit. |
| `tests/test_rm3_route_memory_arms.py` | **+1 cell**, `test_deferred_releases_counts_deferral_ticks_not_armings` (audit 3), pinning the three counters' units against the pipeline source |

---

## 11. ci_gate

Fresh run at this card's FINAL (revision 2) source state,
2026-08-12T09:51:41Z:

```
CI GATE — tier=commit  (2026-08-12T09:51:41Z)
==============================================================================
[  PASS] HARD  ruff                       7 violation(s), baseline 7, new 0
[  PASS] HARD  hard-safety                nav frozen baseline nav-instruct-v1-baseline-v4-20260811T070536Z: collisions=0 false_arrival=0 | mutation panel clean: collisions=0 no_false_arrival=True | mutation panel freshness: committed fields reproduce live = True | follow-bench: 7 row(s), hard_collision_total all 0 = True | walk_with_me: 1/2 row(s) with hard_collision_total, all 0 = True
[  PASS] HARD  frozen-digest-sentinels    4 immutable manifest(s) byte-identical to pin
[  PASS] HARD  latency-tail-ledger        latest row latency-20260810T082415Z-4d83035f: 6 metric series within 1.2x tail ceiling (rows=5, window=5)
[  PASS] HARD  follow-bench-jerk-ratchet  latest shipped row follow-bench-v1-20260811023618Z-93eba090.json: 1.2187 <= 1.46244 (baseline 1.2187 x 1.2)
[  PASS] HARD  model-off-non-inferiority  23 passed in 0.51s
[  PASS] HARD  frozen-digest-integrity    6 passed, 1 warning in 0.33s
[  PASS] HARD  mutation-panel-freshness   2 passed, 3 warnings in 4.39s
[  PASS] HARD  latency-tail               6 passed, 2 warnings in 0.29s
[  PASS] HARD  default-suite              3943 passed, 9 skipped, 36 deselected, 5 warnings in 175.78s (0:02:55)
==============================================================================
RESULT: PASS — every hard gate green.
  elapsed 187.4s
```

Revision 1's run, kept for the record: same 10/10 hard gates PASS at
`2026-08-12T09:01:00Z`, default-suite **3942 passed**, i.e. one cell fewer —
the counter-semantics test revision 2 adds is the whole difference.

**Suite delta, attributed.** Card-open baseline (the Wave-2-audited tree)
**3909 passed, 9 skipped** (AUDIT_WAVE2_FABLE §1). RM-3 adds exactly **34**:
`tests/test_rm3_route_memory_arms.py` collects 34 cells (33 at revision 1, plus
the counter-semantics cell revision 2 adds). 3909 + 34 = **3943** ✓, with the
skip count unmoved at 9. No existing test was removed, renamed or
weakened; the two pinned allowlist assertions were amended in place (§10).

`ruff` stays at **7 violations = baseline 7, new 0**, and all four frozen digest
sentinels are byte-identical to their pins — the `v4r` namespace cannot reach
them by construction (§10).

Also green in isolation: `tests/test_rm3_route_memory_arms.py` **34 passed** in
32 s, and `tests/test_e4_evidence_seams.py` + `tests/test_person_aware_nav.py` +
`tests/test_dr2_pose_drift_arm.py` **120 passed** — i.e. DR-2's 88 pins are
untouched by the additive runner edits.

---

## 12. Open items

* **The gate failed; the mechanism did not.** Whether route memory keeps its
  default-OFF flag, gains a different substrate, or waits on §9 handoff 1 is an
  owner decision this card does not make. What it hands over is: the wiring is
  live and safe on the real product path (42/60 chains won, 0 vetoes, 0
  collisions, 0 false arrivals), and it converts nothing while §7.1 stands.
* **A nightly arm for the `v4r` sweep** — ~40 minutes per invocation, deliberately
  not added (§9.5).
* **The real-weights matcher arm was not run.** `episodes/V4S_MATCHER_ARM.md`
  measures the real-encoder arms at ~90× slower per episode (≈6 CPU minutes vs
  ≈4 seconds); at n = 60 × 2 arms with taught legs that is over a day of
  simulation. The pre-registration names the DEFAULT matcher arm and every
  artifact stamps `matcher_arm`, so the second arm is one flag
  (`--matcher siglip2`) and a machine-day away, not a code change. Reported as
  not run rather than quietly omitted.
* Unchanged from the plan: cross-session place-graph persistence, the voice
  surface for teach-and-repeat, drift-arm floors nightly-vs-commit, B5, and
  CityWalker A/B + VLFM-real.
