# MOVE-1 — pre-registration

**Card:** `scrum/20260821/task_20/README.md` · **Executor:** Claude Opus ·
**Written:** 2026-08-22, BEFORE any diagnostic arm was run and BEFORE any line
of the mission runner existed.

Everything below is fixed in advance. Numbers that appear here are the numbers
that decide pass/fail; if a target is missed it is recorded as missed, and if a
hypothesis is refuted it is recorded as refuted.

---

## Part A — E2-D2, the displacement diagnosis

### A.0 What is already known at write time (inputs, not findings)

Read from C-1's evidence pack before writing this document. These are the
facts the hypotheses have to explain:

* `rerun_live_20260821T235718Z/summary.json`: `motion_accepted = 160`,
  `motion_rejected = 0`, `duration_s = 40.0`, in **both** arms.
* Final pose in `*_api_state.json`: OFF `robot.x = 0.23137 m`, ON
  `robot.x = 0.17050 m`, `y = 0.0`, `heading = 0.0` in both. So the *whole-cell*
  displacement is **0.231 m / 0.171 m over 40 s**, not "4 cm"; the 3.35 cm the
  audit corrected E-2 to is the path length across the 16 *retained* camera
  frames' 8.79 s window only. Both figures are recorded so the diagnosis is
  measured against the right denominator.
* `run_c1_rerun_live.py` lines 167–182: the drive loop submits
  `VelocityCommand(vx=0.25)` when `toggle % 2 == 0` and **`VelocityCommand()`
  — all zeros — otherwise**, every 250 ms. So of the 160 accepted requests,
  **80 commanded 0.25 m/s forward and 80 commanded a full stop.**
* `simulator_on.log` / `simulator_off.log`: over the whole 40 s the simulator
  received **28 / 31** `walk command` lines whose **maximum `vx` is 0.02 m/s**,
  against **126 / 110** `stop requested` lines. The commanded 0.25 m/s never
  reached the simulator once.
* Final `nearest_person`: `{"id": "cyclist-1", "bearing_rad": 0.0,
  "distance_m": 5.56, "time_to_collision_s": 3.27}` — a dynamic agent dead
  ahead of the robot's heading.

### A.1 The three worlds

* **H-A — harness artifact.** C-1's harness never commanded sustained
  displacement. Every second request is an explicit zero, which the dispatch
  path classifies as `zero_intent ⇒ stopping` and routes to the shaper's
  **emergency bypass (instant zero, never ramped)**, additionally
  force-resetting the acceleration smoother. With `linear_accel = 0.9 m/s²` at
  a 10 Hz loop (+0.09 m/s per tick), a ramp that is cancelled every 250 ms
  never reaches the requested 0.25 m/s.
* **H-B — safety gate.** The reactive proximity gate zeroes or scales
  translation on most ticks because a dynamic agent occupies the lane ahead
  (`person_stop_m = 1.2`, `person_slow_m = 2.5`, TTC stop ≤ 0.8 s, TTC slow
  < 1.8 s, `obstacle_stop_m = 0.65`, `obstacle_slow_m = 1.2`).
* **H-C — locomotion drop.** The path drops or attenuates commands regardless
  of intent shape and regardless of gate state: a real actuator/plumbing
  defect below the gate.

These are **not mutually exclusive.** The deliverable is an attribution with
shares, not the election of a single winner.

### A.2 The discriminating measurement (M1)

A per-tick instrumented trace of the **real** dispatch chain, taken by
wrapping instance attributes of a live runtime from the harness process only —
**no product source is edited**, and the wrappers observe and forward, never
alter, every value. Captured per control tick: the arbiter's active intent,
the post-smoother command, the post-reactive-gate command and its
`proximity_state`, what reached `control_manager.set_target`, and the pose.

Three arms, each 40 s (C-1's duration), each against a **fresh** simulator
(C-1's own latched-e-stop lesson), real `build_runtime`, `motion.backend: rl`
with `policy_path: ""` — i.e. C-1's configuration, changed in exactly one
axis per arm:

| Arm | Drive | City |
|---|---|---|
| `replicate` | C-1's exact alternating 0.25 / zero every 250 ms | dynamic (C-1's condition) |
| `held` | `vx = 0.25` re-submitted every 250 ms, **never zero** | dynamic |
| `held_static` | `vx = 0.25` held | `--static-city` (no moving pedestrians/cyclists) |

### A.3 Pre-registered discriminators

| id | Rule | Decides |
|---|---|---|
| **D0** | `replicate` reproduces C-1: path length ≤ **0.40 m** over 40 s. If it does not, the diagnosis is declared **INCONCLUSIVE** and no hypothesis is credited. | validity |
| **D1** | H-A **SUPPORTED** iff `held` path length ≥ **3×** `replicate` path length. | H-A |
| **D2** | H-B **SUPPORTED** iff, in `held`, ≥ **30 %** of ticks with a translating intent are zeroed or scaled by a *named* reactive-safety cause, **and** `held_static` path length ≥ **2×** `held` path length. | H-B |
| **D3** | H-C **SUPPORTED** iff `held_static` path length < **1.0 m** over 40 s **while** the trace shows commands ≥ **0.15 m/s** delivered to `set_target` on ≥ 20 % of ticks — commands issued but not executed. | H-C |
| **D4** | The status doc must state, as a percentage of the 40 s, the share of ticks in each cause bucket (`zero_intent`, `person_stop`, `ttc`, `obstacle`, `input_health`, `stale_telemetry`, `delivered_moving`). Missing bucket ⇒ the attribution is incomplete and says so. | reporting |

### A.4 Declared in advance

The instrumentation wraps `runtime.velocity_smoother.step`,
`runtime._collision_safe` and `runtime.control_manager.set_target` on the
**instance**. This is a deviation from "measure only through public API" and is
declared here: there is no public per-tick trace, and the alternative — editing
`runtime.py` — is outside OWNS and forbidden by the card.

### A.5 Addendum A1 — written AFTER M1's first run, BEFORE the confirmatory arm

Declared as an addendum rather than edited into §A.3, so the record shows what
was fixed when.

M1's first run (`diagnosis_20260822T030352Z/`) refuted H-A (D1: `held`/`replicate`
= 1.41, needed ≥ 3) and refuted H-B's second clause (D2: `held_static`/`held`
= 0.98, needed ≥ 2), and exposed **one defect in my own classifier**: the
`gate_zeroed_other` bucket (94 % of `held_static` ticks) is an artefact of
recording `nearest_obstacle_m` — the omnidirectional nearest — where the
product gate actually uses the **directional minimum over
`observation.lidar_obstacles` filtered by its `_toward` predicate**. The bucket
is therefore unattributed, not "other". Fixed by recording the directional
minimum with the product's own `_toward`.

Two things are added, and their predictions are fixed here first:

* **D5 — the blocked-heading test.** A `steered` arm: same 250 ms submit
  cadence, same runtime, dynamic city, but the command turns
  (`vyaw = 0.8 rad/s`) whenever the directional clearance ahead is below
  1.5 m and drives (`vx = 0.25`) otherwise. **Confirms** the blocked-heading
  attribution iff path length ≥ **3.0 m** in 40 s. **Refutes** it and reopens
  H-C iff path length < **1.0 m**. Between the two ⇒ recorded as equivocal.
* **D6 — the compounding-scale claim.** In the `held` arm the steady-state
  delivered speed must sit **below `s × 0.25`**, where `s` is the reactive
  gate's own slow-scale for that tick, for ≥ 50 % of `slowing` ticks. If
  delivered speed ≈ `s × 0.25` instead, the "compounding" claim is wrong and
  is withdrawn.

All four arms are re-run under the fixed instrumentation so that every number
reported in the status doc comes from one version of the harness.

---

## Part B — the patrol driver

Targets fixed here, before the module exists.

| id | Target | Number |
|---|---|---|
| **P1** | Path length in the dev scene (`city_block`) within the budget | **≥ 5.0 m** (also ≥ 20× C-1's 0.171 m whole-cell displacement = ≥ 3.41 m; the binding number is 5.0 m) |
| **P2** | Map entries at end of patrol, each carrying writer provenance | **≥ 3** |
| **P3** | Hard-safety violations | **collision count exactly 0** |
| **P4** | Budget honoured | wall clock ≤ **120 s** patrol + 20 s teardown; the runner must stop itself |
| **P5** | Deliverable shape | a mission runner invocable **per scene** with a fixed time budget, emitting a **path trace** (timestamped poses) and a **map-growth record** (entry count vs time with per-entry provenance) |

Recorded but **not** pass/fail (C-1's 562 ms p50 freshness limitation is a known
input this card does not fix): detection counts, map yield per query.

## Part C — E2-D3, the T1 detector query vocabulary

Design picked in advance from `scrum/20260821/cutover_research/SYNTHESIS.md`
and the card's steer, before measuring yield:

* **Map-building sweep (out of the decision loop):** an open-vocabulary noun
  batch of **place-like, non-volatile** classes, screened by C-2's
  `is_volatile_label` / `SIZE_PRIORS` so the patrol cannot spend its budget
  proposing people.
* **In-loop vocabulary:** owner-corpus nouns only.
* **T1 means no sidecar:** the batch is derived from the map package's own
  admissible vocabulary plus a static seed list carried by the runner — never
  from `scenes/` truth, never from a scene digest.

| id | Target | Number |
|---|---|---|
| **V1** | Distinct non-volatile map-eligible classes observed by the patrol in the dev scene | **≥ 2** |
| **V2** | Person/volatile observations persisted as map entries | **exactly 0** |

## Part D — house rules binding this card

* Seeds RED for every new behavioural test, with `__pycache__` purged per
  restore, a fresh-interpreter canary, a final sweep postdating the last source
  write, and a repo-root stray sweep.
* Owner store `parcel_memory.sqlite3` never opened read-write; SHA recorded
  before and after every arm.
* No git commit, stage, or stash. No edits outside OWNS.
* Failures recorded as failures. Deviations declared.
