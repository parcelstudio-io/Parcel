# D-15 ATTRIBUTION — `nav-object_goal-D-15-109547e2` (card D15-C)

**What happened:** the episode flipped SUCCESS → FAIL on a single
owner-authorized config knob, `safety.person_stop_m` 1.0 → 1.2 (lane E5,
2026-08-10). **The retune is correct and stays.** What it exposed is two real
gaps — a capability gap (a compliant robot deadlocks behind a human) and an
eval-honesty gap (an undeclared stationary bystander lives inside every
nav_instruct episode). This file is the record of the attribution, the
mechanism, the isolation evidence, and what is NOT proved.

Source of the bisect and the isolation minival: the batch design record
`scrum/20260811/task_1/FOLLOWUP_DESIGNS.md` §1.1 and Appendix A.3. Numbers
marked **[re-measured]** were reproduced by this card on the current tree; the
rest carry their original protocol from the record.

---

## 1 — Mechanism (one knob, one inequality)

The headless world places a DEFAULT OWNER at **(2.00, −0.50)** in every
nav_instruct episode even though the runner resets with `owner=None`
(`HeadlessCityWorld.reset` leaves the owner mocap at its scene pose), and
`apply_reactive_safety` correctly treats a visible owner as a person.

On D-15's route the robot reaches (0.29, 0.11): owner centre distance 1.8132 m,
so clearance = 1.8132 − 0.55 (`owner_collision_envelope_m`) = **1.2632 m**. The
gate's predictive person stop at the grid_v1 cruise speed is

```
person_stop_m + |v|·reaction_time_s = 1.2 + 0.85·0.12 = 1.3020 m  ≥ 1.2632 m
→ _stop_translation, every tick
```

Under the old value the same tick passed: `1.0 + 0.85·0.12 = 1.1020 < 1.2632`.

The veto is INVISIBLE to the planner: the pipeline note stays
`grid_track … status=planned|clear` with zero planning error, the step-220
`semantic_replan_after_no_progress` re-plans the SAME straight route, and the
episode times out at the step budget — reported as `planning_error`.

**[re-measured]** The signature reproduces end-to-end on the current tree, on a
synthetic declared-bystander episode at `person_stop_m` = 1.2 with the real
pipeline, planner, world and gate (`evals/nav_instruct/person_cell.py`,
`signature` row): veto fraction **0.985** of translating ticks, **200** of those
vetoes on ticks whose planner note says `status=planned…|clear`, along-route
progress **0.027 m**, collisions 0.

---

## 2 — Bisect table (from the record §1.1; scratch worktrees, v3 episodes,
baseline mode, scaled-path-v1, pipeline-first import per E7 §2.1)

| # | Arm | Result |
|---|---|---|
| 1 | `6bd945d` old src+evals | SUCCESS, dtg 0.0 |
| 2 | `dd2e857` full | FAIL, dtg 3.0301 |
| 3 | revert E1 set | FAIL 3.0301 (E1 exonerated) |
| 4 | revert perception set | FAIL 3.0301 (exonerated) |
| 5 | revert 4× `robot.yaml` + `reactive_safety.py` + `follow.py` | SUCCESS 0.0 |
| 6 | revert code only, keep new yamls | FAIL 3.1124 (config is the driver) |
| 7 | **`person_stop_m` 1.2 → 1.0 alone** (old reactive code to pass the guard) | **SUCCESS 0.0, 106 steps — THE KNOB** |

---

## 3 — Isolation minival (record Appendix A.3; 25 episodes, `person_stop_m`
restored to 1.0 — the counterfactual arm)

The four episodes that moved, and how they read under the old knob:

| episode | frozen v4 (new knob) | isolation (old knob) | reading |
|---|---|---|---|
| `nav-region_goal-D-15-1b8b2361` | dtg 2.1021 | dtg **1.8967** | ≈ frozen-old 1.8999 |
| `nav-object_relative-D-15-61f68ad6` | dtg 4.1822 | dtg **4.3258** | ≈ frozen-old 4.3301 |
| `nav-object_goal-B-05-0ee314d5` | dtg 0.3955, `planning_error` | dtg **0.3242**, `false_arrival` | old FAILURE CLASS restored |
| `nav-object_goal-D-15-109547e2` | dtg 3.0283, `planning_error` | dtg **0.0067** (in-context) / 0.0 (alone) | back to the band edge |

All four attribute to the single knob.

---

## 4 — Marginality of the moved episodes **[re-measured: goal geometry and the
frozen v4 dtg column, read from `evals/nav_instruct/results/nav-instruct-v1-baseline-v4-20260811T070536Z.json`]**

`dtg` is distance to the GOAL REGION, so it is itself the margin: 0.0 means
inside, and a small positive number is how far outside the band the run ended.

| episode | goal region | frozen v4 dtg (m) | old-knob dtg (m) | margin under the old knob |
|---|---|---|---|---|
| `nav-object_goal-D-15-109547e2` | band 0.6–2.5 m around `tree_2` (5.0, 3.1) | 3.0283 | 0.0067 in-context / 0.0 alone | **6.7 mm outside the band in context; the record's single-episode arm arrives 2.49 m against a 2.50 m outer edge — a 1 cm episode either way** |
| `nav-object_goal-B-05-0ee314d5` | band 0.6–2.5 m around `lamp_post_1` (0.2, 3.15) | 0.3955 | 0.3242 | fails under both knobs; only the failure CLASS moves (`false_arrival` → `planning_error`) |
| `nav-object_relative-D-15-61f68ad6` | band 0.85–1.95 m around `planter_1` (−5.0, 3.15), footprint 0.45 | 4.1822 | 4.3258 | fails by metres under both; not marginal |
| `nav-region_goal-D-15-1b8b2361` | crosswalk polygon | 2.1021 | 1.8967 | fails by metres under both; not marginal |

Only `object_goal-D-15` is a knife-edge episode. That is why the design record
refuses to "fix" it by widening a band or a tolerance (§1.3): the 1 cm margin
would only be relocated, and moving a tolerance is the prohibited silent change.
The honest eventual fix is an owner-authorized v5 with margin-aware goal bands
(record §8, OPEN QUESTION 3) — not this batch.

**Protocol dependence (measured):** D-15's dtg is 3.0301 single-episode,
3.0268 in a 4-episode context, 3.0293 in E8's 25-episode row, and **3.0283
[re-measured]** in this card's fresh 25-episode minival. The spread is
cross-episode state leakage in the harness (shared world, LiDAR-noise RNG seeded
once per world), recorded as OPEN QUESTION 4 and owned by nobody yet. No frozen
number is comparable outside its own protocol.

---

## 5 — The declared-bystander sweep (this card's new measurement)

`evals/nav_instruct/person_cell.py` runs the real stack against a SYNTHETIC
episode: the route is the ray from D-15's own start pose through the world's
real default bystander (clear of static obstacles for 10 m, measured), the
bystander stands ON that route at a chosen clearance, and the run is repeated
per clearance × declaration channel × `person_aware_nav` arm. Full numbers:
`scrum/20260811/task_1/W1_D15_STATUS.md` §D15-C.

Headlines **[re-measured]**, `person_stop_m` = 1.2, cruise 0.85 m/s, veto
boundary 1.3020 m (standing-start boundary 1.2000 m):

* **UNDECLARED** (the frozen condition) — deadlock at every clearance in
  1.10…3.00 m. The robot always stalls at a min clearance of **1.234–1.302 m**,
  i.e. exactly inside the `person_stop_m … person_stop_m + v·reaction` band. At
  1.10 m (inside `person_stop_m`) it never moves at all: veto fraction **1.000**,
  progress **0.000 m**.
* **DECLARED as a bystander** (`dynamic_agents`, the planner's existing stranger
  cost layer) — **detour at every clearance**: along-route 2.00–2.32 m, lateral
  excursion 2.13–2.72 m, veto fraction **0.000**, min clearance never below the
  placed clearance. Declaring the human is what removes the deadlock.
* **DECLARED as the owner** (`owner_track`, reduced cost weight 0.6) — still a
  deadlock flag-off (veto 0.985); with `person_aware_nav` ON it becomes a
  COMPLIANT YIELD: veto fraction **0.050**, 207 compliant-speed cap ticks, and
  the robot holds at a min clearance of exactly **1.2000 m** = `person_stop_m`.
* `person_aware_nav` ON with NOTHING declared changes nothing at all (byte-equal
  outcome rows). The capability needs perception; it cannot invent it.

### `person_stop_m = 1.0` — derived, not run

E5's undercut guard raises `ValueError` for any `person_stop_m` below
`SafetyEnvelope.person_stop(0.0)` (verified, adjudication #12), so the old arm
cannot be CONSTRUCTED on this tree. Computed from the gate's own inequality and
labelled `derived-not-run` in the cell's report:

```
predictive stop = 1.0 + 0.85·0.12 = 1.1020 m  <  1.2632 m clearance → NO veto
```

which is exactly why the episode passed before the retune.

---

## 6 — Correction note for E5 (additive; E5's own file is untouched)

`scrum/20260809/task_15/E5_PERSON_CLEARANCE_STATUS.md` records "cost of
`person_stop_m` 1.0 → 1.2: **zero** (9/9 preserved)". That claim is TRUE AS
SCOPED — it was measured on FOLLOW_BENCH_V1 — and it is FALSIFIED for
nav_instruct, where the same knob costs D-15 (and moves three more episodes).
E5 did not re-measure nav_instruct (E8 §9), and E8 could not A/B the knob on new
code because E5's own guard refuses the old value. The honest statement is:

> `person_stop_m` 1.0 → 1.2 costs zero on FOLLOW_BENCH_V1 and costs one
> episode (plus three moved dtg values) on the nav_instruct v4 minival.

No number in E5 is edited by this card; this is a cross-reference.

---

## 7 — `does_not_prove`

* Does **not** prove the retune optimal — only that it is the CAUSE of the flip.
  1.2 m is the authority's HUMAN-bucket social zone; the alternative is an owner
  decision, not a measurement.
* Does **not** prove detour safety at higher pedestrian density: the sweep
  declares exactly one stationary bystander.
* Does **not** re-measure any frozen row. The cell runs its own synthetic
  placements and writes its own report; the frozen v4 row was re-run once,
  unmodified, and reproduced bit-for-bit (W1_D15_STATUS.md §D15-B gate 1).
* The `person_stop_m = 1.0` row is DERIVED from the gate's inequality, not run.
* Sweep outcomes are budget-limited (800 steps): a run that neither deadlocks
  nor arrives inside the budget is reported as it ended, never extrapolated.
* Says nothing about the undeclared default owner in the follow/circle worlds,
  or the four unexplained `circle_owner` authority disagreements E8 left open
  (record §8, OPEN QUESTION 5).
