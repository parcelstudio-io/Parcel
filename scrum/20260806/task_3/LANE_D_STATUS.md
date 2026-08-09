# Lane D — stratum 2, the perception chain · status

**Date:** 2026-08-07 · **Plan:** [docs/STRATA_GENERALIZATION_PLAN.md](../../../docs/STRATA_GENERALIZATION_PLAN.md)
stratum 2 + eval instrument 2 · **Concurrency:** Lane C ran in the same tree
throughout. Every number below was produced on an **isolated overlay** (Lane B's
method): a snapshot of `src/`, `evals/` and `configs/` taken before the first
Lane D edit, with **only Lane D's files** copied on top. Lane C's edits are
present in neither the before nor the after tree, so no delta here can be
theirs.

**The one-line claim:** the detection chain is now the only semantic ingress on
the mission path and it changed nothing (empty diff, identical sha256);
association is a classical tracker instead of an oracle-id join, and across the
whole round Lane D moves the frozen minival by **−0.027 m mean dtg on 10 of 25
episodes with SR and collisions flat**. Four reds remain, all from
one root cause in D-4, all attributed below — and three separate episodes
turned out to be mis-specified *goals* rather than navigation defects, which is
the most useful thing this round found.

## Outcome per card

| card | outcome |
|---|---|
| D-1 chain as mission-path ingress, pass-through first | **done.** Empty minival diff, identical sha256. |
| D-2 classical tracker + geometric association | **done.** 49 property tests; replacing the oracle-id join changed **3/25 episodes** (see the correction note below). |
| D-3 evidence-based arrival in K0 + FP memory + calibration | **done.** No episode change of its own at T0; threshold calibrated on 200 known-absent trials. |
| D-4 U34 phantom-yaw fix | **done.** 9/25 episodes moved; mean dtg −0.042 m on the final code; **4 reds remain**, one root cause, attributed below. |
| D-5 N11 residual — proxemic veto + final-metre yield | **landed and measured.** n=3 paired seeds. The xfail would still fail as written; evidence below, decision deferred as instructed. |
| D-6 noise tiers | **done.** T0 default (nothing moves), T1 measured; degradation table + FP/dropout attribution below. |

---

## VERIFY 1 — D-1 equality: the diff is empty

Determinism established first, so the equality means something: two consecutive
pre-change runs of the frozen NAV_INSTRUCT minival (candidate mode, 25 episodes,
full traces) are byte-identical.

| run | episode digest | SR | SPL | sha256 of per-episode JSON |
|---|---|---|---|---|
| before | `cf4d5384…` | 0.0400 (1/25) | 0.00016477 | `4dc64f55251da919f09ae14779beb3abfeae26b6cc8c7f16f5158d12a979faf7` |
| after (chain wired, T0) | `cf4d5384…` | 0.0400 (1/25) | 0.00016477 | `4dc64f55251da919f09ae14779beb3abfeae26b6cc8c7f16f5158d12a979faf7` |

**`diff before.json after.json` → empty.**

### Why it is exact, not approximately exact

`semantic_candidates_from_observation` is now the one ingress and it runs
`detection_adapter/perception_chain.py` on every frame, in the runtime and in
every headless harness. At tier T0 the chain:

1. lifts every row — objects *and* regions — to `GroundTruthDetection`, so the
   detector contract genuinely validates the mission path (a row the contract
   rejects is dropped at T0 too, and there is a test for that);
2. **draws no random number at all**, so no seeded stream anywhere downstream
   can shift. This is the defect Lane B hit with one extra `world.observe()`;
   it is pinned by `test_t0_draws_no_random_numbers`;
3. reconstructs each row through an **exactness short-circuit**: when the stage
   returned the class, bearing, range and score bit-identical to what was
   lifted, the reconstruction returns *the caller's own dict object* rather
   than re-deriving world coordinates through `hypot`/`atan2`/`cos`/`sin`.
   `test_t0_returns_the_callers_own_objects` asserts identity (`is`), not
   equality.

Same discipline as stratum 1's `p_inside_polygon` short-circuit at zero
covariance: the exact branch is what makes the seam safe to wire at all.

A `passthrough=True` tier that carries any noise **raises at construction** —
T0 is an equality commitment, not a low-noise setting, and nobody can quietly
turn it into one.

Injection is a process-default (`use_perception_chain`), deliberately mirroring
`pose.use_pose_provider`, so **no file under `evals/` was touched** to run the
tiers.

---

## D-2 — the classical tracker, and the id join it deletes

`src/parcel_robot/navigation/tracker.py` (new, ~430 lines with docs). Zero
learned parts, per the binding anti-goal:

- **motion:** 2D constant velocity, state `[x, y, vx, vy]`, continuous
  white-noise-acceleration `Q` (Bar-Shalom standard form), Joseph-form update
  so `P` stays symmetric positive-definite (the gate is meaningless otherwise);
- **gating:** squared Mahalanobis against the innovation covariance vs
  `CHI2_2DOF_95 = 5.991`;
- **assignment:** global, by Hungarian. **`scipy` is not installed in
  `.parcel`** (verified), so `hungarian()` is a pure-Python O(n³)
  shortest-augmenting-path implementation, checked against brute force on 25
  random matrices;
- **lifecycle:** 3-of-5 confirmation, 5-miss deletion, bounded track set that
  drops tentative tracks before confirmed ones.

**Class labels are evidence, not a gate.** With confusion on at T1 the same body
is `person` one frame and `owner` the next; a hard class gate would shred
exactly the tracks that matter. `Track.max_other_class_fraction` reports the
disagreement instead, and D-3 consumes it.

**IPDA: documented, not built.** `Track.existence_probability` is the named
landing site, is `None`, and no decision reads it
(`test_ipda_seam_is_present_and_unused`).

### Unit properties (49 tests, `tests/test_navigation_tracker.py`)

| property | how it is pinned |
|---|---|
| gate monotone in covariance | squared distance strictly decreases across σ ∈ {0.05 … 4.0} for four residuals; a separate test proves the ordering actually crosses 5.991 (monotonicity alone would be vacuous) |
| gate monotone in residual | strictly increases across five residuals |
| singular covariance fails **closed** | a degenerate `P` rejects rather than accepting everything |
| lifecycle partition | over 60 frames of a mixed scenario: ids unique, every live track in exactly one of tentative/confirmed, tentative ∩ confirmed = ∅, live ∩ deleted = ∅ |
| no track switch under crossing | two targets crossing at ±3 m/s keep their ids through the crossing — this is the test that forces *global* assignment rather than greedy |
| M-of-N / miss-streak | confirmation needs exactly M hits; a one-frame hit never confirms and dies at 5 misses; a confirmed track survives a 4-frame gap |
| out-of-gate detections | start a new track instead of teleporting the old one |
| Hungarian | matches brute force (25 seeds); never returns a forbidden (`inf`) pair; handles empty and all-forbidden |

### What the geometric association replaces

Four sites answered "is this the same thing?" with string equality on an oracle
id. All four are now geometric:

| site | was | is |
|---|---|---|
| `pipeline._control_observation` (target exemption) | `obstacle_id in {candidate_id, *associated_lidar_ids}` | the ray to the return points at the **tracked** target (lateral offset within `candidate_radius + 0.45 m`) and the return is not beyond it |
| `pipeline._terminal_environment_is_clear` | same id set | same geometric gate |
| `pipeline._current_target_clearance` → `_target_clearance` | same id set | same geometric gate |
| `pipeline._current_semantic_candidate` | `item["id"] == metadata["candidate_id"]` | nearest same-kind candidate within `0.75 m + radius` of the tracked target |
| `approach._safe_near_object_point` | `_associated_obstacle_ids(candidate)` | `_obstacles_excluding_target` — the same line-of-sight test |

`pipeline._obstacle_ids` is **deleted**, not deprecated; the comment in its place
says why. `associated_lidar_ids` survives as telemetry and nothing gates on it.

### A correction found by the suite, and what it changes about the numbers

The association gate was **first written as distance-from-the-return-to-the-
target's-centre**, and measured at **0/25 episodes changed**. The default test
suite then failed on a lamp post, and it was right to: the LiDAR contract
reports footprint-to-**surface** clearance, so a return on a body whose radius
the semantic channel does not carry lands a whole radius short of that body's
centre. A 0.88 m-radius lamp post reads 0.88 m "away from itself" and a
centre-distance gate rejects it — the gate failed on exactly the objects it
most needed to accept.

The corrected gate is a **line-of-sight** test (`pipeline._ray_hits_target`):
the return belongs to the target when the ray points at it (perpendicular
offset within radius + slack) **and** the return is not beyond it. For a convex
body of unknown radius, the first return along the bearing to that body *is*
its near surface.

**So the honest figure for the association change is 3 of 25 episodes, not 0.**
The 0/25 belongs to the superseded form and is recorded here only because it is
what the round measured first. Re-measured on the final code, isolated from
Lane C, with U34 held at its pre-fix value so this row is the association
change alone:

| metric | baseline | chain + tracker + evidence (no U34) | Δ |
|---|---|---|---|
| SR | 0.0400 | 0.0400 | 0 |
| mean dtg | 8.6404 m | 8.6548 m | +0.0144 m |
| episodes changed | — | **3 / 25** | — |
| `false_arrival` | 1 | **2** | +1 — **not a verification regression; see finding 3** |

Changed: `object_goal-B-05`, `object_relative-A-00`, `object_relative-D-15`.

What the correction does *not* change: the id join is still deleted, and the
lateral slack still bounds the only mistake the geometric gate can make (a body
on the line of sight within 0.45 m is exempted from **local evasion only** —
the reactive gate, the TTC gate and the runtime's final brake all still see the
unmodified sensor view on the same tick).

---

## D-3 — evidence-based arrival, and the death of `0.98`

`instructnav/scoring.py` gains (`SCORING_VERSION` → `instructnav-scoring-v1.3-arrival-evidence`):

- `ArrivalEvidence` — `{frames_seen, cumulative_confidence, max_other_class,
  confirming_frames, visible}`, every field a count or a mean **over frames**;
- `ApproachVerifyState` — `APPROACH → VERIFY → VERIFIED | REJECTED`;
- `evidence_arrival_verified(...)` — the evidence half of the ONE K0 predicate,
  asked in order: visibility → M-of-N → mean confidence + class agreement;
- `FalsePositiveMemory` — rejections keyed by **map cell + label**, not by
  candidate id (an id is exactly what a detector does not provide), with 8-cell
  neighbour lookup so a re-detection 20 cm across a boundary is still refused;
- `objectnav_arrival_radius_m()` — the community 1.0 m criterion **derived**
  from `StandOffEnvelope.vicinity_margin_m` plus the object radius, so a scaled
  robot's arrival radius scales instead of staying pinned to a Go2 number.

Wired into `pipeline._semantic_arrival_verified` **after** the geometry, so
geometry says "I am in the right place" and evidence says "and the thing I came
for is really there". Region membership deliberately keeps pure `GoalRegion`
geometry (the branch where no live candidate is required — standing inside a
region puts its centroid outside the frustum). `ARRIVAL_CONFIRMING_FRAMES_M`
is the *same* 3-of-5 as the tracker's, on purpose: two different M-of-N rules
would be a second authority.

Rejected candidates go to the FP memory and are filtered out of both the frustum
and the memory recall at the next grounding.

**Measured effect at T0: no episode change attributable to the evidence gate.**
Every target is tracked and confirmed long before arrival, and the sim's 0.98
clears the 0.55 floor. The one place it bites is a unit test that stepped the
navigator twice and then asserted arrival: two ticks resolve a goal but no
longer *claim* it, which is the card working. Two cases in
`tests/test_navigation.py` gained a third sighting, with the reason in a
comment; the geometry those cases exist to check is untouched.

### The calibration — 200 known-absent trials at T1

`scratchpad/calibrate_threshold.py`, real scene, real chain, real tracker.
Known-absent class `hydrant` (the city block contains only building / lamppost /
planter / tree); present class `building`. 200 trials × 40 frames each.

| statistic | value |
|---|---|
| absent trials whose phantom ever reached the predicate at all | **1 / 200** |
| that one phantom's mean confidence | **0.5851** |
| present trials reaching the predicate | **200 / 200** |
| present mean-confidence distribution | mean **0.8296**, sd 0.0391, min 0.7440 |

| threshold τ | false-accept rate | true-accept rate |
|---|---|---|
| 0.30 – 0.55 | 0.005 | 1.000 |
| **0.59** (first FAR = 0) | **0.000** | 1.000 |
| 0.60 – 0.70 | 0.000 | 1.000 |
| 0.75 | 0.000 | 0.995 |
| **0.76** (largest τ with FAR = 0 ∧ TAR ≥ 0.99) | 0.000 | 0.990 |
| 0.80 | 0.000 | 0.740 |
| 0.85 | 0.000 | 0.280 |
| 0.90 | 0.000 | 0.040 |

**Calibrated value: any τ ∈ [0.59, 0.76].** The shipping
`SemanticGoal.minimum_confidence = 0.55` sits at FAR 0.005 / TAR 1.000 — just
below the FAR-zero knee and already inside the usable band, which is why
`perception.arrival_confidence_threshold` ships as `null` ("use the goal's own
floor") rather than moving a value the data does not require moving.

**The honest reading, and it is the more interesting finding:** *the
confidence threshold is not what rejects false positives at T1 — the tracker's
M-of-N confirmation is.* 199 of 200 known-absent trials never reached the
predicate at all, because a phantom has to survive 3-of-5 association first. The
threshold is a second line that fires on the 0.5 % that get through. That is a
result about where the robustness actually lives, not a tuning outcome.

It is also weak evidence in one specific way, stated plainly: the first run of
this calibration returned **0/200** because memoryless phantoms teleport every
frame and the tracker kills them for free. That was a strawman, so
`NoiseTier.false_positive_persistence_frames` was added (default 4 at T1) to
make phantoms hold their place. **It is not a datasheet number** — no detector
datasheet quotes one — and it is labelled as a modelling choice in the code.
Every T1 number in this document was produced with it.

---

## D-4 — U34, the standing height read as a yaw

`NavObservation.position[2]` is the robot's standing height (0.27 m on a Go2)
and `pipeline.py` read it as yaw in radians: a constant **15.5°** phantom
heading error. Lane B named it and deliberately preserved it. Three sites in
`pipeline.py` now read `_pose_in(observation, MAP_FRAME).yaw`:

| site | what was wrong |
|---|---|
| `_step_semantic_resolution` | every grounding call's robot yaw |
| `_step_scan_behavior` | the full-turn scan's start heading, so every stop bearing was offset by the same constant |
| `_step_search_entity_frontier` | frontier bearings, so the align gate turned to a heading 15.5° off the frontier it had chosen |

The `legacy_yaw` import **and** the in-file bundle fallback are removed from
`pipeline.py`; `pose.legacy_position_yaw` itself is Lane B's file and untouched.

### Before / after, paired, isolated (this is a behaviour change)

Measured on the **final** code by reverting only the three yaw reads, so the
row is U34 alone and not U34-plus-association:

| metric | before (U34 live) | after (U34 fixed) | Δ |
|---|---|---|---|
| SR | 0.0400 (1/25) | 0.0400 (1/25) | 0 |
| **mean dtg** | 8.6548 m | **8.6133 m** | **−0.0415 m** |
| collisions | 0 | 0 | 0 |
| episodes changed | — | **9 / 25** | — |
| failure histogram | planning 17, termination 4, refusal 0 | planning **15**, termination **5**, refusal **1** | — |
| authority histogram | agreement 19, disagreement 4 | agreement **18**, disagreement **5** | — |

Cumulative Lane D vs the frozen baseline: SR 0.0400 → 0.0400, mean dtg
8.6404 → 8.6133 m (**−0.0271 m**), **10 / 25** episodes changed, 0 collisions.

The per-episode table below was measured on the mid-round code (mean dtg
−0.1237 m); the *direction and cause* of every row is unchanged, the magnitudes
moved when the association gate was corrected.

Per-episode attribution:

| episode | dtg before → after | reason before → after | reading |
|---|---|---|---|
| `object_relative-A-00` | 2.508 → **0.449** | step limit (both) | **−2.06 m.** The frontier align now turns to the frontier it picked. |
| `object_relative-E-20` | 54.955 → 53.920 | step limit (both) | −1.03 m, same cause |
| `object_relative-B-05` | 2.179 → 2.179 | `semantic_target_unreachable` → `semantic_target_not_found` | scan steps 1 → **79**. An honest not-found replaces a wrong unreachable; failure moves to `refusal`. |
| `region_goal-B-05` | 0.000 → 0.000 | `arrived_verified` → `navigation_step_limit_inside_goal` | **the one cost.** Scan steps 1 → 14: the scan now actually turns through its stops, and the episode runs out of budget before it can claim. It was already `success=False` under the frozen hold rule either way; it moves `planning_error` → `termination` and `agreement` → `authority_disagreement`. |
| 5 others | unchanged dtg | unchanged | trace-level differences only |

Net: the geometry improves where the geometry was the problem, and one episode
pays for the extra honest scanning with its clock. Nothing regressed on SR, SPL
or collisions.

---

## D-5 — N11 residual: the fail-closed veto and the final metre

### (a) Proxemic veto on the ranked winner — never a competing selector

`proxemic_approach.py` (PARKED since 2026-08-06) is wired at
`approach._rank_approach_point`. The shape is the whole point:

- ordering is **entirely** `traffic_aware`'s; the veto may only strike
  candidates off that ordering, walking it in order (bounded at
  `PROXEMIC_VETO_DEPTH = 16`);
- all struck → **`None`**, an honest "I have no safe approach pose", not the
  least-bad landing in the stream;
- **empty tracks skip the veto entirely**, so the ladder rule holds
  byte-identically;
- a veto that cannot be evaluated **defers to the ranking and says so**
  (`proxemic_veto: "unavailable"`) rather than silently passing or silently
  rejecting.

Two proxemic authorities that could disagree about which pose is *best* is the
D5 defect class. One that ranks and one that refuses cannot disagree, because
refusing is not ranking.

### (b) Final-metre yield on the tracker's predicted paths

Within `FINAL_APPROACH_BAND_M = 1.0` of the goal, on a tick where
`apply_collision_brake` **has already returned `clear`**, if the tracker's own
constant-velocity predictions say no confirmed person enters the person-stop
envelope within 1.5 s, the `RampMemory` release seed floors at a
`FINAL_APPROACH_CREEP_MPS = 0.12` creep instead of zero.

Safety argument, identical in kind to `RampMemory`'s own and deliberately no
stronger: it is not a gate and not a command source; it is only consulted after
the gate opened; it raises a *recovery* seed which `max_vx`, the reactive gate,
the TTC gate, the shaper and the arbiter all still bound on the same tick. It
cannot make the robot move on a tick it would otherwise have stopped on.
Fail-closed: no people tracker, or no confirmed person track, returns `False` —
an absence of tracks is not evidence of an empty pavement.

The predictions come from a **second, separate** `MultiObjectTracker` fed from
`extras['dynamic_agents']` **positions only**. The payload's `vx`/`vy` are
simulator truth; a policy that consumes oracle velocity in a dispositive
position is not a policy that survives a real detector. Separate from the
furniture tracker so a pedestrian standing beside the bench can never be bound
as the bench.

### (c) The measured traffic runs — n = 3 paired seeds

Same geometry as `test_go_to_the_sidewalk_with_pedestrian_traffic`: one sim
process with the dynamic city on, one `RobotRuntime`, `"go to the sidewalk"`
typed into `handle_text`. `tests/test_voice_nav_e2e.py` was **not touched**;
this is `scratchpad/n11_traffic.py`, which varies
`simulation.dynamic_city.seed`.

| seed | before | after |
|---|---|---|
| 7 | `failed` / **`step_timeout`**, 241.1 s, dtg **0.328**, end (−0.28, +2.07), path 2.09 m | `succeeded` / **`navigation_goal_verified`**, **46.0 s**, dtg 5.342, end (+1.53, −2.94), path 3.99 m |
| 11 | `failed` / `step_timeout`, 240.1 s, dtg **0.420**, end (+0.05, +1.98), path 1.98 m | `failed` / `step_timeout`, 240.1 s, dtg **0.295**, end (−0.37, +2.11), path **11.81 m** |
| 23 | `failed` / `step_timeout`, 241.1 s, dtg **0.330**, end (−0.27, +2.07), path 2.09 m | `succeeded` / `navigation_goal_verified`, **51.0 s**, dtg 5.814, end (+1.70, −3.41), path 4.93 m |

**The before column reproduces the pinned baseline exactly.** The backlog's N11
row records "travels 2.09 m from (0.00,0.00) to (−0.28,2.07), ends 0.33 m
outside the sidewalk GoalRegion, `last_detail='step_timeout'`". Seed 7 before:
2.09 m, (−0.28, +2.07), 0.328 m, `step_timeout`. The instrument is measuring
the right thing.

**What changed, honestly.** Two of three runs stop dying on the clock: they
terminate with a **verified arrival in ~50 s** instead of burning the full 240 s
budget. But they arrive at **`sidewalk_south`** (y ∈ [−3.75, −2.25]), not the
north `sidewalk` polygon the e2e case scores against — so `goal.contains(x, y)`
is `False` and the measured dtg is ~5.3–5.8 m.

The mechanism is visible in the numbers: the crosswalk pedestrian stream is on
the north side, the fail-closed veto strikes out every north-sidewalk approach
pose, `safe_approach_pose` returns `None`, the mission replans, and grounding's
documented region tie-break ("region goals are stuff classes; any same-label
instance satisfies the directive, so tie-break to the nearest") picks the other
sidewalk. **That is the veto working exactly as designed** — and the e2e
assertion is pinned to one of two equally valid instances.

The third run (seed 11) keeps the north sidewalk and still times out, but moves
**11.81 m of path** against the baseline's 1.98 m and lands **0.295 m** out
against 0.420 m. The final-metre policy produces real motion where the baseline
was frozen; it is not yet enough to close the last third of a metre inside the
budget.

**The xfail was not edited.** As instructed, the flip decision goes to the
review round. My reading of the evidence, offered not applied: the
`states == "succeeded"` half now passes on 2/3 seeds, the
`goal.contains(x, y)` half does not and will not until someone decides whether
"the sidewalk" means a specific polygon or any sidewalk. That is a Lane C
vocabulary question (region instance selection), not a perception one.

---

## D-6 — the noise ladder, measured

`configs/navigation/default.yaml` gains a `perception:` block: `tier` (T0
default), `seed`, `confidence_temperature`, `arrival_confidence_threshold`. The
runtime installs the configured tier once at construction
(`RobotRuntime._install_perception_chain`) and degrades to T0 on any config
problem.

Every T1 constant, and where it comes from:

| parameter | value | provenance |
|---|---|---|
| range sigma | `1.25e-3 · z²` m | D455: baseline 0.095 m, `f = 640/tan(43.5°) = 674.4` px at 1280 px / 87° HFOV, 0.08 px sub-pixel σ → 0.02 m at 4 m = 0.5 % RMS, consistent with the datasheet "<2 % at 4 m" **bound** at ~4σ |
| bearing sigma | 1.0e-2 rad | 2 px centroid = 3.0e-3 rad on the same intrinsics, **widened** for box jitter under partial occlusion. Widened, not derived — said so in the code |
| dropout | 0.1 at ≤1.5 m → 0.3 at ≥8 m, linear | the plan's published 0.1–0.3 band, range-scaled |
| false positives | 1.0 / 100 frames | published band 0.5–2.0, mid |
| FP persistence | mean 4 frames | **modelling choice, not a datasheet number** (see D-3) |
| confidence | TP `N(0.75, 0.12)`, FP `N(0.55, 0.15)`, truncated to [0,1] | overlapping by construction; `temperature` scales both σ |

### Degradation table — T0 → T1, same frozen minival

| metric | T0 | T1 | Δ |
|---|---|---|---|
| SR | 0.0400 (1/25) | 0.0400 (1/25) | 0 |
| SPL | 0.00016477 | 0.00016477 | 0 |
| **mean dtg** | 8.5167 m | **8.7438 m** | **+0.2271 m** |
| collisions | 0 | **0** | 0 |
| episodes changed | — | **11 / 25** | — |
| failure histogram | planning 16, termination 5, refusal 1, **false_arrival 1** | planning 17, termination 4, refusal **2**, **false_arrival 0** | — |
| authority histogram | agreement 19, disagreement 5, false_arrival 1 | agreement **21**, disagreement **4**, false_arrival **0** | — |

### Failure attribution — FP-accepted vs dropout-starvation

Attributed by the grounding-outcome transition, which is the only signal in the
persisted trace that separates the two:

| class | rule | count | episodes |
|---|---|---|---|
| **dropout-starvation** | RESOLVED at T0 → UNSEEN at T1 (the target stopped being detected) | **2** | `object_goal-E-20` (→ `semantic_target_not_found`, `refusal`), `object_relative-C-10` |
| **FP-accepted** | UNSEEN at T0 → RESOLVED at T1 (something was grounded that T0 never saw) | **1** | `object_relative-E-20` (dtg 53.920 → 53.999) |
| jitter / association | RESOLVED both sides, dtg or trace moved | **8** | incl. `region_goal-B-05` (dtg 0.000 → **5.228**, the largest single regression) |

**T1 is measurement, not a gate** (plan, eval instrument 2). Nothing in this
round is tuned against it and nothing gates on it.

---

## Three findings worth more than the cards that produced them

### 1. The standing `false_arrival` row is a goal-specification defect, not a perception one

W0 handed Lane D the open question of *which party is wrong* in
`nav-object_goal-D-15-109547e2` (`"walk towards the tree"`, mission claims
`arrived_verified`, scorer measures dtg 3.1995 m). Replayed tick by tick:

- the episode's `GoalRegion` is `anchor_entity='tree_1'`, centre **(−5.0, 3.15)**;
- from the episode's start pose, `tree_1` is **not visible at all**. The visible
  semantic objects are `bldg_2`, `bldg_3`, `bldg_4`, `lamp_post_1`, `planter_2`
  and **`tree_2` at (5.0, 3.1)**;
- the navigator grounds "the tree" → `tree_2` (the only tree it can see),
  walks towards it, and verifies `towards tree_2` correctly.

**The navigator is right and the goal is wrong.** The instruction says "the
tree", the scene has two, and the generator anchored the goal to the one the
robot cannot see. No amount of perception work removes this row; the fix is in
`evals/nav_instruct/generator.py`, which is explicitly not Lane D's file this
round. **The plan's stratum-2 gate "zero `false_arrival` rows at T0/T1" is
therefore not achievable by Lane D**, and the row it counts is not a
verification defect. (At T1 the count does reach 0 — but only because noise
prevented the claim, which is not a fix.)

Incidental, same replay: **`planter_2` and `tree_2` occupy the identical
position (5.0, 3.1)**. That belongs with W0-D's scene-truth deltas.

### 2. M-of-N, not the confidence threshold, is what rejects false positives

See the calibration table. 199 of 200 known-absent trials never reach the
arrival predicate at all. Worth knowing before anyone spends effort tuning a
threshold that is not the binding constraint.

### 3. A SECOND mis-specified episode — and this one is unambiguous

`false_arrival` goes 1 → 2 with the corrected association, and the new row is
**not** a verification regression. `nav-object_goal-B-05-0ee314d5` reads, in
full:

- instruction: **"walk towards the streetlight"**
- goal region: `relative_band`, **`anchor_entity='tree_1'`**, centre (−5.0, 3.15)

The episode asks for a streetlight and scores against a **tree** — and against
`tree_1` specifically, which (like D-15) is not visible from the start pose
(−0.4, −0.25): the frame contains `bldg_3`, `bldg_4`, `bldg_6`, `planter_2` and
`tree_2`. Whatever the navigator grounds "streetlight" to, its distance to
`tree_1` is meaningless. It scored `navigation_step_limit` at dtg 5.284 m
before and `arrived_verified` at 5.353 m after; both are ~5.3 m from a tree
nobody asked about.

Two of the 25 minival episodes therefore pair an instruction with a goal
anchored to a different, unobservable entity. That is an eval-integrity defect
of the same family as W0-D's transcription deltas, it is in
`evals/nav_instruct/generator.py` (not Lane D's file this round), and it means
**the `false_arrival` count is not currently a measurement of navigation
honesty at all.**

---

## The two reds Lane D leaves behind, and why

`tests/test_embodied_plan_eval.py::test_full_gate_executes_physics_and_separates_unsupported`
and `::test_sidewalk_and_lamppost_use_evaluator_truth_after_execution`.

**Attributed, not guessed.** Both pass on the pre-Lane-D snapshot and on the
overlay through D-3, and fail from D-4 onward. Isolated further by swapping
`approach.py` between trees: with the D-4/D-5 `pipeline.py` and the *old*
`approach.py` they still fail; with the pre-D-4 `pipeline.py` and the *new*
`approach.py` they pass. D-5 is inert here (no dynamic agents in the embodied
suite). **Cause: D-4, the U34 yaw fix.**

**The mechanism, exactly.** The frozen case `sidewalk_then_lamppost` starts at
(0, 0, 0) and runs "Walk to the sidewalk, then wait by the lamppost." The city
has two `sidewalk`-labelled regions; their centroids are 3.2 m (north) and
3.0 m (south) from the origin. With the phantom 15.5° heading, the north
sidewalk read as more "in front" and grounding took it. With the real heading,
the documented stuff-class tie-break — "any same-label instance satisfies the
directive, take the nearest" — takes the **south** one, by 0.2 m. Step 1 then
succeeds on the south sidewalk and step 2 fails
`semantic_target_unreachable`: the lamp post is at (0.2, 3.15), across the
road.

The same 0.2 m knife-edge is what moved
`test_headless_city_tasks::…[default-origin]`. That one **is** fixed here: the
robot still reaches a sidewalk and stops safely inside it, so the expectation
was updated to `sidewalk_south` with the reason in a comment, **and a new
`north-of-the-road` parametrisation was added** so the north polygon keeps a
case of its own. The embodied cases are different in kind — the second step
genuinely does not complete — so nothing was edited to make them pass.

**Why this is not fixed here.** The three available fixes are all outside Lane
D's charter this round:

1. change the tie-break (region instance selection is stratum 3, Lane C);
2. rank regions by distance **to the region** rather than to its centroid —
   which is the geometrically right measure for a 12 m sidewalk, and by that
   measure the north sidewalk *is* nearer (2.2 m vs 2.25 m). This was tried:
   it changes `ObservationSemanticMap.query`'s ordering but not the grounder's
   own tie-break, which lives in `instructnav/grounding.py` (Lane C's,
   do-not-touch). It was reverted rather than left in unmeasured;
3. re-anchor the frozen case's start pose — a re-freeze of
   `evals/companion/**`, which nobody should do inside a lane round.

**Recommendation for the review round:** sequence this with W0-D's scene-truth
adoption and U31 option 2, so the frozen inputs are re-decided once. The
underlying question is one sentence: *does "the sidewalk" mean a specific
polygon, or any sidewalk?* Every artefact in this document that still disagrees
with a frozen expectation disagrees about exactly that.

---

## Verification

| check | result |
|---|---|
| D-1 T0 equality, before vs after | **empty diff**, identical sha256 `4dc64f55…` |
| T0 determinism precondition | two pre-change runs byte-identical |
| D-2 geometric association delta (final code, U34 held) | **3 / 25 changed**, mean dtg +0.0144 m (the superseded centre-distance form measured 0/25 — see the correction note) |
| D-3 evidence arrival delta | no episode change of its own |
| D-4 U34 delta (final code, only the yaw reads reverted) | 9 / 25 changed, mean dtg −0.0415 m, SR flat, 0 collisions |
| D-5 delta on the traffic-free minival | **0 / 25 changed** (correct: no dynamic agents, so both the veto and the yield policy are inert) |
| **cumulative Lane D vs the frozen baseline** | SR 0.0400 → 0.0400, mean dtg 8.6404 → **8.6133 m (−0.0271)**, **10 / 25** changed, **0 collisions** |
| D-6 T1 degradation | 11 / 25 changed, mean dtg +0.2271 m, SR flat, **0 collisions** |
| N11 traffic runs | n = 3 paired seeds, table above; baseline reproduced exactly |
| frozen minival episode digest | `cf4d5384d1787d110cbc5a74e8b46699e6aa26eaaa576b1c24beb0fbb04adfbf` — **unchanged** |
| frozen ledger rows | **untouched** — Lane D appended nothing and rewrote nothing |
| new tests | **102** (tracker 49, perception chain 20, arrival evidence 20, proxemic veto 13) |
| existing tests adjusted, with the reason in a comment | 3 — `test_navigation.py` ×2 (a third sighting for M-of-N), `test_headless_city_tasks.py` ×1 (instance expectation + a new north-of-the-road case restoring the lost coverage) |
| `ruff check` on every Lane D file | **clean** |
| full default suite, final tree | **6 failed, 2627 passed, 7 skipped, 8 xfailed, 1 xpassed** (991 s) — from 15 failed at entry to this round's fix pass |
| **reds Lane D owns and leaves** | **4** — `test_embodied_plan_eval.py` ×2 and `test_voice_nav_e2e.py` ×2, all one root cause (D-4's sidewalk-instance tie-break), attributed by tree bisection, three possible fixes documented above |
| pre-existing `ruff` errors NOT fixed | 10 in `detection_adapter/{__init__,noise,sim_bridge}.py` — verified present in the pre-Lane-D snapshot |
| Lane C reds observed, verified theirs, not fixed | 6 `ruff` errors in `navigation/relation_registry.py` (a new Lane C file, absent from the snapshot); `test_authority_no_literal_drift.py` ×2 on `navigation/collision.py` (byte-identical to the pre-Lane-D snapshot, last written 02:37 — before the snapshot at 02:42 — so not Lane D's) |

### The full-suite runs, stated exactly

Two full `pytest tests/ -q` runs were made.

**Run 1** (13 min 15 s, started before the last two fixes landed):
`15 failed, 2565 passed, 7 skipped, 5 xfailed`. Every one of those 15 was then
triaged individually:

| failure | disposition |
|---|---|
| `test_approach_traffic_wiring` ×2 | **mine, fixed** — the final-metre helper reached for `self.mission` on the bare `object.__new__(DirectiveNavigator)` those tests build |
| `test_navigation` ×2 | **mine, fixed** — the centre-distance association gate (see the correction note); the tests then needed a third sighting for M-of-N |
| `test_headless_city_tasks` ×1 | **mine, resolved** — the sidewalk-instance tie-break; expectation updated + north coverage restored as a new case |
| `test_embodied_plan_eval` ×2 | **mine, OPEN** — see "The two reds Lane D leaves behind" |
| `test_authority_no_literal_drift` ×2 | **not mine** — `navigation/collision.py`, byte-identical to the pre-Lane-D snapshot |
| `test_planner_quality_v2` ×1 | **not reproducible** — passes standalone; contention flake |
| `test_voice_nav_e2e` ×5 | **live-sim, contaminated** — see below |

**Run 2**, on the final tree (16 min 31 s):
**`6 failed, 2627 passed, 7 skipped, 8 xfailed, 1 xpassed`** — down from 15
failed, and +62 passing.

| failure | disposition |
|---|---|
| `test_authority_no_literal_drift` ×2 | **not mine** — `navigation/collision.py`, byte-identical to the pre-Lane-D snapshot (last written 02:37; snapshot taken 02:42) |
| `test_embodied_plan_eval` ×2 | **mine, OPEN** — the D-4 sidewalk-instance tie-break, above |
| `test_voice_nav_e2e::test_go_to_the_sidewalk_grounds_plans_and_arrives` | **mine, OPEN** — same root cause: the case asserts the *north* `sidewalk` polygon contains the final pose |
| `test_voice_nav_e2e::test_walk_towards_the_lamppost_grounds_plans_and_arrives` | **mine, OPEN** — same family (which lamppost / which approach) |

A separate re-verification pass over every non-live file that failed in run 1
is green on the final tree: **308 passed** across the navigation, headless-city,
pose, tracker, chain, evidence, scoring and authority-differential suites.

**One `xpassed`.** The suite reports a pinned xfail that now passes. Which one
is being re-measured on a quiet machine before it is named here — reporting an
xfail flip off a contended run would be exactly the kind of claim this document
exists not to make. It is recorded as *observed, unattributed*.

**Why the live e2e results from this window are not usable evidence.** Lane C
was running the live `-m slow` e2e cases *and its own full suite* concurrently —
at one point two full `pytest tests/` processes plus three `parcel_robot.sim`
subprocesses were sharing one EGL device. The same contention killed several of
my batched N11 traffic runs outright (`sim died during startup`, `runtime never
received an observation`); all six reported traffic runs are individually
re-run and clean. Any live-sim red from this window should be re-measured on a
quiet machine before it is attributed to anyone.

---

## Files touched

| file | change |
|---|---|
| `src/parcel_robot/detection_adapter/perception_chain.py` | **new** — tiers, chain, T0 exactness, calibrated T1, injection seam |
| `src/parcel_robot/navigation/tracker.py` | **new** — Kalman + Mahalanobis + Hungarian + M-of-N |
| `src/parcel_robot/navigation/semantic_map.py` | the chain becomes the one ingress |
| `src/parcel_robot/navigation/pipeline.py` | tracker wiring, geometric association ×4, `_obstacle_ids` deleted, evidence gate in K0, FP memory, U34 ×3, final-metre yield, people tracker |
| `src/parcel_robot/navigation/approach.py` | proxemic veto, geometric target exclusion |
| `src/parcel_robot/instructnav/scoring.py` | `ArrivalEvidence`, `evidence_arrival_verified`, `FalsePositiveMemory`, `objectnav_arrival_radius_m`, version → v1.3 |
| `src/parcel_robot/runtime.py` | one method: install the configured perception tier |
| `configs/navigation/default.yaml` | `perception:` block (noise-tier keys only) |
| `tests/test_navigation_tracker.py` | **new**, 49 |
| `tests/test_perception_chain.py` | **new**, 20 |
| `tests/test_arrival_evidence.py` | **new**, 20 |
| `tests/test_approach_proxemic_veto.py` | **new**, 13 |
| `tests/test_navigation.py` | 2 cases gain a third sighting (M-of-N), reason in a comment |
| `tests/test_headless_city_tasks.py` | `default-origin` instance expectation + a new `north-of-the-road` case restoring the north-sidewalk coverage |

`proxemic_approach.py` itself is **unmodified** — it was already correct; it was
only ever unwired.

Not touched: `goals.py`, `local_plans.py`, `router.py`, `compiler.py`,
`agent.py`, `relations.py`, `grounding.py`, `attributes.py`,
`city_semantics.py`, `tests/test_voice_nav_e2e.py`, `authority.py`, `pose.py`,
`geometry.py`, `evals/**`.

## Non-claims

1. **There is no detector.** T1 is a noise model over oracle geometry. It has no
   pixels, no appearance, no occlusion reasoning, and its false positives are
   drawn from a uniform annulus rather than from anything that looks like the
   scene.
2. **The FP persistence figure is invented.** Mean 4 frames is a modelling
   choice with no datasheet behind it, and every T1 number depends on it.
   Halving it would make M-of-N look even more dominant; raising it would give
   the confidence threshold more work.
3. **The calibration is one scene, one absent class, one present class.** 200
   trials is enough to place the knee, not enough to claim a threshold that
   generalises across scenes.
4. **The geometric association was proven equal to the id join, not better.**
   0/25 changed is the correct result for a scene where the oracle ids happen to
   be right. It is evidence that nothing was lost, not evidence that anything
   was gained. What was gained is that the id join can no longer exist.
5. **The false-positive memory has never fired in a real run.** No T0 or T1
   episode produced a `class_disagreement` rejection. It is covered by unit
   tests only.
6. **Only class disagreement writes to the FP memory.** A `verification_failed`
   is deliberately *not* recorded: most are geometry (0.07 m outside a band),
   and remembering those would make the robot refuse to ever re-ground a real
   landmark. "Never re-tricked" therefore holds for phantoms that contradict
   themselves, not for every failed approach.
7. **The FP memory is per-mission.** It clears on `stop()`. Claiming it across a
   session needs a persistence story nothing here has.
8. **The final-metre creep has never been observed firing.** The traffic runs
   record no `final_metre_yield` metadata in the reported snapshots; the
   improvement on seed 11 is consistent with it but not attributed to it. The
   policy is unit-reachable and integration-unproven.
9. **`n = 3` traffic runs is three runs.** Two succeeded and one did not; that
   is a 2/3, not a rate.
10. **IPDA is not built**, and the tracker's covariance is the filter's own
    output with no existence reasoning anywhere.
11. **T0 equality covers the NAV_INSTRUCT minival only.** It is 25 episodes
    travelling 13.5 m in total; it is a strong exactness check and a weak
    coverage check, exactly as Lane B found. The association bug the suite
    caught — a centre-distance gate that rejected a lamp post's own surface —
    was invisible to it, which is the concrete cost of that weakness.
12. **The suite did not exit green.** Four cases are red — two
    `test_embodied_plan_eval`, two `test_voice_nav_e2e` — all Lane D's, all one
    root cause, none masked. Making them green requires a decision about
    region-instance selection or a re-freeze of `evals/companion/**`; taking
    either unilaterally inside a lane round would have been worse than leaving
    the red visible. The count went from 15 failing at the mid-round check to
    6 (4 mine, 2 Lane A's).
13. **The `false_arrival` count means less than it looks like it means.** Both
    rows it contains are mis-specified episodes (findings 1 and 3), so its
    movement 1 → 2 across this round is not a statement about arrival honesty.
