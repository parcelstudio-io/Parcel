# Lane W3-Y — yield-aside (cards Y-1, Y-2, Y-3, Y-4)

**Executor:** Claude Opus. **Base:** `dd2e857` + the landed Wave-1/Wave-2 work
in the tree. **Spec:** `scrum/20260811/task_1/FOLLOWUP_DESIGNS.md` §4 and §6
cards Y-1…Y-4, binding, including both skeptic-corrected clauses.

## Verdict in one paragraph

All four cards are implemented and measured. Y-1 (pure proposer) and Y-2
(wiring) meet their gates: the closed-loop equilibrium and lagging stall-guard
properties hold with seeded-failure proofs, and the full FOLLOW_BENCH_V1 bench
reproduces every pre-existing field of the committed `dd2e857` row bit-identically
with the flag off. **Y-3 is a STOP-and-report**: on the pre-registered two-stage
measurement the yield-aside did not engage at all in the oncoming-corridor cell
and cost 0.476 of band in the wide cell, and the reason is structural, not a
tuning miss — the rotated-aim formulation is stall-guard-inadmissible everywhere
inside the follow band and its closed-loop equilibrium sits at 2.95–3.88 m,
outside the band's 3.0 m edge. Y-4 returns `pedestrian_group` to the owner as
the `person_slow_m` band decision with the derived bound, and adds a positive
control that confirms it. **The `yield_aside` flag stays code-default OFF and
this lane does not recommend flipping it.**

---

## Card Y-1 — `navigation/yield_aside.py` (pure proposer)

New files only: `src/parcel_robot/navigation/yield_aside.py`,
`tests/test_yield_aside.py` (30 tests, 7.5 s, ruff clean).

### Gate results

| gate | result |
|---|---|
| (a) `\|aim − owner\| == desired_distance_m`, `==` not approx | **PASS.** The emitted offset's `math.hypot` equals `desired_distance_m` bit-for-bit on every active proposal over a 400-case randomized sweep, and on 2000 random bearings directly. Achieved by a bounded ULP search (`circle_offset`): naive `radius*(cos,sin)` is exact ~79% of the time, rescaling gets ~92%, and at most 2 one-ULP steps closed the rest (measured over 50k bearings). Budget exhaustion REJECTS the candidate rather than emitting an off-circle aim. |
| (b) fail-closed triple | **PASS.** `no_strangers` / `no_scan` / `no_meaningful_aside` each tested; a blocked scan and a NaN-returning scan callable both fail closed. |
| (c) no candidate samples below `person_stop_m` | **PASS** over randomized FULL track sets (1–6 tracks, seeded). **Seeded-failure proof:** the same checker over a proposer with the reject removed reports violations. |
| (d) derived margins by reference | **PASS.** `MEANINGFUL_IMPROVEMENT_M is OWNER_STAND_OFF_MARGIN_M` (identity, not equality); `MAX_ASIDE_OFFSET_M == person_comfort_band_m − person_stop(0.0)` = 1.3; candidate step == `FollowConfig.distance_deadband_m` (0.18); horizon == `person_comfort_band_m / max_vx` (7.1429 s). No new literal is a threshold. |
| (e) determinism | **PASS.** 50 randomized cases, two calls each, dataclass equality and `repr` equality. |
| (f) asymmetric exit | **PASS.** Entry costs a full 0.10 m improvement, holding costs only parity, release is the un-offset path recovering the 2.5 m comfort band. A search over 400 random track sets finds the hold-but-would-not-enter arm and asserts its improvement is in [0, 0.10). |
| (g) **closed-loop equilibrium property** | **PASS.** 60 randomized geometries driven through the REAL `FollowOwnerController._step_direct` to its fixed point: minimum owner distance over the whole rollout ≥ `owner_keepout_m` (1.75) in every case, terminal distance too, with ≥ 5 cases exercising an active proposal. Control arm: the un-yielded law parks on `desired + deadband` = 2.03 m. |
| (h) **lagging stall guard** | **PASS** over randomized geometries; the skeptic's canned case (lag 2.77 m, offset 0.6 m → \|robot−aim\| 1.183 m) is re-derived in the test and must be rejected. |
| ruff / ci_gate | clean (see §ci_gate below). |

### The two mandated clauses, and their seeded-failure proofs

**Equilibrium.** The fixed point of the verified law under a rotated aim is
`r_eq(θ) = D·cosθ + sqrt(h² − D²·sin²θ)` with `h = D + deadband`; it decreases
in θ, so the family's floor is its value at the largest usable offset:
**2.946 m** for the shipped `D = 1.85, deadband = 0.18, offset ≤ 1.26` — versus
`owner_keepout_m` 1.75. `YieldAsideLimits` REFUSES TO CONSTRUCT when that floor
drops below the keepout. Two seeded-failure arms:

1. with `MAX_ASIDE_OFFSET_M` monkeypatched to 1.84, the constructor raises
   (`equilibrium_floor_m` 1.366 < 1.75);
2. the closed-loop checker, run over a rogue proposer that ignores the offset
   cap (θ = 1.5 rad), DETECTS rollouts inside the keepout.

"Safe by construction" appears nowhere in the module or in this doc.

**Stall guard.** The deadband is one-sided (`distance_error <= deadband` holds,
including negative errors), so while `|robot − owner| > desired + deadband` a
candidate is admissible only if `|robot − aim|` stays **strictly** above the
hold ring (strict, not the record's `>=`: at exact equality the law holds, so
strictness is the safety-closed reading). Seeded-failure proof: the same
checker over a proposer with the guard removed reports violations.

### Design choices worth an auditor's attention

* The predicted path used for scoring is `robot → predicted_stance(aim)`, where
  the stance is taken at `desired` (not `desired + deadband`) from the aim —
  the inner edge, so the predicted path is never shorter than the travelled
  one. When the law would HOLD, the predicted path is the degenerate point at
  the robot, which is what makes an inert flag provably inert.
* The entry condition carries a domain check the record's prose implies but does
  not state: the un-offset predicted path must be INSIDE `person_slow_m`. Without
  it a stranger 9 m away buys a lateral detour worth one improvement quantum of
  nothing (found by a test, not by inspection).
* `side` is the AIM's rotation sense; the robot's stance displaces the OTHER
  way (it parks on the far side of the aim). Documented on the dataclass and
  asserted in `test_clearance_outranks_the_latch`.
* The "owner-side preference" tiebreak is realized as *smallest offset that
  achieves the best clearance*, then the caller's latched side, then a fixed
  sign order — deterministic, and honest about what it is.
* `planar_free_range` reads the scan over a corridor as wide as the robot
  (window = `asin(footprint_radius / span)`), not a single ray. Derived from
  `DEFAULT_SAFETY_ENVELOPE.footprint_radius_m`; a fixed window would have been
  a new constant.

---

## Card Y-2 — wiring, flag plumbing, flag-off identity

Files: `src/parcel_robot/navigation/follow.py` (`FollowYieldConfig`, the
`_step_direct` aim swap immediately after `_clamped_lead`, `_yield_aim`, two
module-level input adapters, additive `FollowDecision` fields, additive
`snapshot()["yield_aside"]`), `src/parcel_robot/runtime.py` (ONLY the
`owner_follow.yield_aside` pop mirroring the prediction block at :528),
`evals/companion_nav/runner.py` (`BenchFeatures.yield_aside=False` +
`_follow_config_from_store` plumb), NEW `tests/test_follow_yield_wiring.py`
(16 tests).

### The diff itself

`git diff src/parcel_robot/navigation/follow.py` contains **no deletions at
all** — 14 hunks, every one a pure addition. Not one pre-existing line of the
batch's most-audited controller changed; the only edit to an existing statement
sequence is the single new call `owner_x, owner_y = self._yield_aim(...)`
inserted after `_clamped_lead`. `runtime.py` is two hunks (an import name and
the 8-line `yield_aside` pop mirroring the prediction block at :528).

### Gate 1 — flag-off byte-identity on the FULL bench: **PASS**

Full 11-scenario `run_follow_bench_v1` in a scratch tree, no ledger append,
diffed field-for-field against the committed `dd2e857` report
`follow-bench-v1-20260811023618Z-93eba090.json`:

| pinned field | committed | measured |
|---|---|---|
| `follow_success` | 7/9 | **7/9** |
| `mean_band_fraction` | 0.708782386458857 | **0.708782386458857** |
| `mean_rms_commanded_jerk_mps3` | 1.2187 | **1.2187** |
| report-aggregate `min_pedestrian_surface_m` | 0.5299999999999998 | **0.5299999999999998** |
| `personal_space_time_total_s` (dwell) | 2.3 | **2.3** |
| `hard_collision_total` | 0 | **0** |
| `navigate_success` | 2/2 | **2/2** |

A recursive diff over the whole report found **zero pre-existing field changes**.
The only differences are additive or volatile: J-C's landed
`mean_rms_commanded_jerk_nominal_mps3` (0.4818) and `nominal_jerk_episode_count`
(11) plus the per-episode nominal jerks, my `features.yield_aside: false`, and
`generated_at_utc` / `git_describe`. `model-off-non-inferiority` green (23
passed). Unit-level identity is pinned too: a controller built without the new
parameter and one built with `enabled=False` produce equal `FollowDecision`
objects over a 20-tick sequence WITH strangers present.

### Gate 2 — flag-ON inertness where no strangers: **PASS**

`straight_follow`, `owner_stops`, `owner_turn_90`, `follow_turn_corner`,
`owner_corner_loss` (and `doorway_gap`, both navigate cells) are bit-identical
between flag-off and flag-on: same band, same minimum clearance, same end pose,
same summed commanded vx to 6 decimals.

### Gate 2b — non-vacuity: the flag-on proposal DOES engage

Required so the identity result cannot be a flag that never fires. Measured on
the shipped bench with the flag on (scratch diagnostic over per-step decisions):

| scenario | steps with `yield_aside` active | what moved (flag-off → flag-on) |
|---|---|---|
| `pedestrian_group` | **108 / 250** | band 0.584 → 0.580; **min pedestrian surface 1.4336 → 1.6221 m**; end pose (3.298, −0.687) → (2.918, −0.754) |
| `pedestrian_cut_in` | **64 / 250** (+1 `clearance_recovered` — the asymmetric exit firing in a real episode) | band 0.525 → 0.525; **min pedestrian surface 1.4074 → 1.4346 m**; end pose (2.552, 1.500) → (2.547, 1.549) |
| `pedestrian_group_wide` (Y-3 tier) | **124 / 250** | band 1.0000 → 0.5240; min surface 2.0206 → 2.0933 m |

So the flag engages, in three separate cells, and where it engages it buys
pedestrian clearance and spends band.

### Gate 3 — the proposal is UPSTREAM of the gate: **PASS**

`test_the_gate_still_disposes_of_the_yielded_command`: for a fixed command and
observation the gate verdict is identical whether or not the aside is enabled
(the proposal cannot reach the gate's inputs), and the command the controller
derives from a YIELDED aim is still vetoed to `vx == 0.0` with
`proximity_state == "stopped"` by the untouched `apply_reactive_safety` when a
stranger is inside the person stop ring.

### Gate 4 — pins: **PASS**

`REACTIVE_SAFETY_PIN` untouched-green, 4/4 digest sentinels byte-identical,
no frozen row moved, `reactive_safety.py` not edited (zero owners this batch).

### `does_not_prove` (mandatory)

* **The `_clamped_lead` exemption.** An active aside REPLACES the (possibly
  clamped) lead point, so it bypasses that clamp's anticipation budget
  (`standoff − keepout` ≈ 0.10 m). The rationale is that the clamp polices
  LEAD-anticipation of a moving owner, not a stance rotation at constant owner
  distance — but that is a *rationale*, not a proof. What actually polices the
  yielded aim at runtime is (i) the proposer's unit-enforced equilibrium
  precondition and (ii) the untouched reactive gate's owner band. **The gate is
  the sole runtime protection here.** Asserted, not assumed, in
  `test_an_active_aside_replaces_the_clamped_lead_point`.
* **The nearest-scalar gate limitation.** `apply_reactive_safety`'s people list
  carries ONE stranger scalar plus the owner, so the proposer's rejection over
  the full `dynamic_agents` set is LOAD-BEARING, not belt-and-suspenders. If a
  second stranger sweeps a candidate path, only Y-1's property stands between
  it and the aim. Widening the gate's people list is §8 open question 7.
* **Bench scope.** Scripted, non-reactive pedestrians in a headless kinematic
  world; no real perception anywhere in the loop.
* **Behind mode is not wired** (the bench exercises direct mode only) —
  documented seam, unchanged from the record.
* **Owner-track disambiguation is geometric.** A `dynamic_agents` entry within
  the owner's collision envelope is dropped as "that is the owner"; a stranger
  standing inside the owner's own envelope would be dropped too. The gate still
  sees them.

---

## Card Y-3 — additive yield tier: **STOP-AND-REPORT**

Full detail and the per-step attribution table: `Y-3_STATUS.md`. Headlines:

* **Stage A (flag OFF), recorded first:** `pedestrian_oncoming_group` band
  **0.5040** with the stance **0.148 m INSIDE** the group's swept corridor at
  closest approach → the displacement failure the record asked for is
  confirmed, so no redesign was authorized and none was done. The Stage-B floor
  was then fixed at **0.5040 + 0.15 = 0.6540** (computed inside the harness from
  the Stage-A arm, and written into the scenario as `min_band_fraction=0.654`).
  `pedestrian_group_wide` measured band **1.0000**.
* **Stage B (flag ON): MISSED**, 7 registered misses. `pedestrian_oncoming_group`
  is **bit-identical to Stage A** (band 0.5040) — the proposer was active on
  **0 of 250 steps**. `pedestrian_group_wide` fell **1.0000 → 0.5240**
  (floor 0.75) with maximum owner distance 2.996 → 4.128 m.
* **V1 regression (flag ON, all 11): PASS.** No episode band below its
  `dd2e857` reference by more than 0.01 (worst: `pedestrian_group` −0.004), no
  per-episode pedestrian-surface decrease (two improved), aggregate
  `min_pedestrian_surface_m` **0.5299999999999998 unchanged**, dwell **2.3 s**,
  collisions 0.
* **Attribution (per-step, mandatory on a miss).** Of the 176 oncoming steps
  where the proposer ran: 62 had nothing to yield from yet, **65 had every
  candidate rejected by the stall guard**, 32 by the person-stop reject, 17 by
  the improvement quantum. Candidate-level: 902 stall-guard, 456 person-stop,
  238 below-quantum rejections.
* **Mechanism.** The stall guard admits a rotation only when the robot already
  lags ≳ 2.95 m, and the rotated aim's closed-loop equilibrium is 2.946–3.880 m
  — while the band's upper edge is 3.0 m. So the aside is inadmissible
  everywhere inside the band and, once admissible, parks the robot outside it.
  Rotating the aim preserves the distance law about the owner, and that is
  exactly what pushes the equilibrium out; the two mandated clauses did not
  cause this, they exposed it.

Nothing was retuned to recover a miss. The tier, its harness and its report
land as the measurement apparatus; the flag does not flip.

---

## Card Y-4 — infeasibility record + owner memo

Full memo: `YIELD_DESIGN_RECORD.md`; evidence archived at
`scrum/20260811/task_1/evidence/`. Headlines:

* `evidence/{trace_group.py,oracle_yield.py,minival_isolation.txt}` extracted
  from Appendix A and verified **byte-identical** to the session-scratch
  originals (checked while they still existed). One deviation, stated in the
  memo: a four-line `# ruff: noqa` banner on each `.py` so the hard lint gate
  stays green; the bodies below it are byte-identical.
* **`trace_group.py` re-run reproduces the record exactly** on the committed
  tree: band 0.5840, 104/250 above-band steps, 223 slowing / 0 stops, minimum
  pedestrian surface 1.4336 m. One correction: the record's "ends x=2.74" does
  not reproduce — the measured end is **x = 3.30**.
* **`oracle_yield.py` re-run reproduces 3 of 8 cells** (the three shift-0
  cells and `cut_in −0.4`). The five shifted cells differ by 1–3 steps out of
  250: measured 0.5720 / 0.5600 / 0.5440 / **0.6040** vs recorded
  0.568 / 0.552 / 0.540 / 0.616. Deterministic across process isolation and
  identical on `dd2e857` and on the Wave-1/2 working tree, so the difference
  is in the designer's vanished scratch copy, not in this tree. **Every
  conclusion survives** and the ceiling correction (0.6040 < 0.616) makes the
  refusal stronger, not weaker.
* **The derived bound is confirmed from the other side.** New control cell
  `pedestrian_group_wide`: same controller, same group, 5.0 m gap so clearance
  is ~2.3 m ≥ the derived 2.24 m → **band 1.0000** flag-off. The corridor, not
  the controller, is the constraint.
* The memo prices five owner options against E5 §4.4's two-sided
  `person_slow_m` table and E6 §4.2's owner-band factorial, and names the
  residual only the owner's band decision can move (the 2.77 m owner-entry
  equilibrium whenever any stranger is perceived).

---

## ci_gate

* **Baseline, verified fresh at lane start** (2026-08-11T17:06:03Z): PASS —
  `default-suite` 3594 passed, 9 skipped, 36 deselected; ruff 7 violations /
  baseline 7 / new 0; 4/4 digest sentinels; hard-safety green.
* **After the lane** (2026-08-11T18:01:55Z): `RESULT: FAIL — 1 hard gate(s)
  red: default-suite`, with every other gate green — ruff **7 / baseline 7 /
  new 0**, hard-safety green (follow-bench 7 rows, all `hard_collision_total`
  0), 4/4 digest sentinels, jerk ratchet 1.2187 <= 1.46244,
  model-off-non-inferiority 23 passed, mutation-panel freshness green.
  `default-suite`: **3667 passed, 1 failed**, 9 skipped, 36 deselected. The one
  failure is **not this lane's**:
  `tests/test_v4s_search_cells.py::test_checked_in_v4s_files_equal_a_fresh_generation`.
  **Attribution proven, not asserted:** in a scratch copy of the current tree
  with this entire lane reverted (four tracked files restored to `HEAD`, four
  new files deleted), the test fails identically (`1 failed, 27 passed`). The
  failure is that `evals/nav_instruct/episodes/v4s/` contains a `README.md` and
  an extra episode file that a fresh generation does not produce — files of the
  concurrent mini-lane AF-2 / card VS-6, which this lane never touches.
* One transient red of my own, found and fixed inside the lane: the archived
  evidence scripts tripped the ruff gate (4 new violations, F401/I001); the
  `# ruff: noqa` banner resolves it without editing the artifacts' bodies.
* `tests/test_runtime_activation.py::test_camera_ingress_live_owlv2_localizes_object`
  fails when the `slow` marker is not deselected; it fails identically on the
  committed tree `dd2e857`, and `ci_gate --tier commit` deselects it. Pre-existing,
  not this lane's.

## Files touched

| card | files |
|---|---|
| Y-1 | NEW `src/parcel_robot/navigation/yield_aside.py`, NEW `tests/test_yield_aside.py` |
| Y-2 | `src/parcel_robot/navigation/follow.py`, `src/parcel_robot/runtime.py`, `evals/companion_nav/runner.py`, NEW `tests/test_follow_yield_wiring.py` |
| Y-3 | `evals/companion_nav/scenarios.py` (append-only), NEW `evals/companion_nav/run_follow_bench_yield.py`, NEW `evals/companion_nav/results/yield-ext-20260811175456Z-bd950c37.json`, NEW `evals/companion_nav/results/yield-ext-ledger.jsonl`, NEW `scrum/20260811/task_1/Y-3_STATUS.md` |
| Y-4 | NEW `scrum/20260811/task_1/YIELD_DESIGN_RECORD.md`, NEW `scrum/20260811/task_1/evidence/{trace_group.py,oracle_yield.py,minival_isolation.txt}` |
| lane | NEW `scrum/20260811/task_1/W3_Y_STATUS.md` (this file) |

Not touched, by rule: `reactive_safety.py`, `collision.py`, `core/**`,
`configs/**`, `evals/companion_nav/results/ledger.jsonl`, every
`follow-bench-v1-*.json`, `run_follow_bench_v1.py`, `metrics.py`, and every
AF-2 file (`navigation/pipeline.py`, `lock_on_verify.py`,
`false_positive_memory.py`, `instructnav/arbiter.py`, `detection_lock_on.py`).
**Nothing committed.**

## Handoffs / open items for the owner

1. **`yield_aside` default stays OFF**, and this lane recommends it stays off:
   the rotated-aim mechanism is inadmissible inside the follow band by
   construction of the stall guard, and outside it by the equilibrium
   arithmetic (Y-3 §3.2). Reviving corridor displacement needs a different
   formulation, and the two obvious ones (lateral aim translation, `vy`
   strafing) are already refused in the record §4.3 — that makes it an owner
   design decision, not a card.
2. **`pedestrian_group ≥ 0.75`** returns to the owner as the `person_slow_m`
   band decision, priced in `YIELD_DESIGN_RECORD.md` §4 (five options).
3. **Yield telemetry in the bench record:** `metrics.StepRecord` needs a
   `yield_active` column before engagement counts can live in a report instead
   of a scratch diagnostic. Needs whichever card next owns `metrics.py`.
4. **Scenario-table validation** for `FOLLOW_BENCH_YIELD_EXT` currently runs
   inside the new harness; folding it into `tests/test_follow_bench_v1.py`
   needs an owner for that file.
5. **`dynamic_agents` widening of the reactive gate's people list** (§8 open
   question 7) is what would demote Y-1's all-tracks rejection from
   load-bearing to belt-and-suspenders.
6. **Record correction:** §4.1's "ends x=2.74" and the five shifted oracle
   cells in Appendix A do not reproduce (Y-4 §1, §3.2). The design record
   should carry the re-measured values if it is cited again.
