# Lane B — stratum 1, the pose-authority seam · status

**Date:** 2026-08-07 · **Plan:** [docs/STRATA_GENERALIZATION_PLAN.md](../../../docs/STRATA_GENERALIZATION_PLAN.md)
stratum 1 · **Audit:** [docs/NAV_GENERALIZATION_AUDIT.md](../../../docs/NAV_GENERALIZATION_AUDIT.md)
stratum 1 · **Concurrency:** Lane A ran in the same tree. Lane-A-owned files
(`geometry.py`, `robot_profile.py`, `authority.py`, `configs/**` except the new
`configs/navigation/pose.yaml`) were **not** touched; `authority.py` was read
only, for the `Z_r` hand-off.

**The one-line claim: the seam landed and changed nothing.** NAV_INSTRUCT
candidate minival is **byte-identical** before and after
(sha256 `50d7e517…`, empty diff, 25/25 episodes). Everything else in this round
is measurement, not capability.

## Outcome per card

| card | outcome |
|---|---|
| B-1 PoseProvider seam + equality-preserving migration + archon rule | **done.** 13 call sites migrated, each naming its REP-105 frame. T0 diff empty. |
| B-2 DriftingOdomProvider + `configs/navigation/pose.yaml` + calibration test | **done, with an honest deviation** — the two published DogLegs bands are not jointly satisfiable; see below. |
| B-3 health / LOST semantics | **done.** K0 refuses arrival on unhealthy MAP; navigator stops-and-holds on LOST; walk_with_me surfaces it. |
| B-4 landmark-relative goals | **done.** Stored at commit, re-anchored on re-observation, gated to the same instance. |
| B-5 chance-constrained membership | **done**, wired behind the zero-covariance equality. |

---

## VERIFY 1 — T0 equality: the diff is empty

Because Lane A was editing the same tree, a naive before/after would have
measured Lane A. The run is isolated instead:

1. the source tree was snapshotted **before** any Lane B edit;
2. the after-tree is that same snapshot with **only** Lane B's 8 files overlaid
   (`diff -rq` confirms exactly: `pose.py` added; `runtime.py`,
   `headless_city.py`, `navigation/{pipeline,base,grid_navigator}.py`,
   `configs/navigation/pose.yaml`, `evals/walk_with_me/runner.py` changed).

So both runs share identical Lane-A state and differ only by Lane B.

| run | minival digest | SR | sha256 of per-episode JSON |
|---|---|---|---|
| before | `cf4d5384…` | 0.0400 (1/25) | `50d7e5173c1cec43ef390a851d8b1b491231c45e46025d7decd40e597b525835` |
| after (TruthPoseProvider active, all 5 cards) | `cf4d5384…` | 0.0400 (1/25) | `50d7e5173c1cec43ef390a851d8b1b491231c45e46025d7decd40e597b525835` |

**`diff before.json after.json` → empty.** The payload is
`EpisodeRunResult.as_dict()` for all 25 episodes including full traces; it
carries no timestamps at all, so nothing had to be stripped.

Determinism was established first, so the equality means something: two
consecutive pre-change runs are themselves byte-identical.

## VERIFY 2 — T1 drift smoke (measurement, not a gate)

Same frozen minival, same **unmodified** `evals/nav_instruct/**` (Wave-0-owned;
untouched). The provider reaches the runner through
`pose.use_pose_provider(...)`, a documented eval/test injection seam; a fresh
provider is built and reset per episode.

| profile | SR | mean dtg (m) | Δ dtg | collisions | episodes changed |
|---|---|---|---|---|---|
| truth (shipping) | 0.0400 | 8.6404 | — | 0 | — |
| `calibrated_go2` | 0.0400 | 8.6401 | −0.0003 | 0 | 3 / 25 |
| `stress` (α=0.2) | 0.0400 | 8.6407 | +0.0003 | 0 | 4 / 25 |

Changed episodes: `region_goal-D-15`, `object_goal-B-05`, `object_goal-D-15`
(calibrated) plus `region_goal-B-05` (stress, where an `arrived` at dtg 0.000
becomes dtg 0.155 — a real arrival lost to drift).

**Why the aggregate barely moves — the honest reading.** The frozen minival
gives drift almost nothing to work with:

- **Total distance travelled across all 25 episodes is 13.5 m** (max 3.8 m in
  one episode; 18 of 25 episodes travel under 0.5 m). Accumulated drift is
  0.008–0.057 m calibrated, 0.03–0.51 m stress. A model calibrated to
  0.3 deg/m cannot move an episode that never leaves its start pose.
- The **only** success in the whole minival (`follow_owner-D-15`) is on the
  spatial path, which the seam does not reach at all (below). So SR is
  structurally insensitive here — SR being flat is not evidence of robustness.

**Which consumers actually see drift** (the question the card asks):

- **Sees drift:** `grid_navigator` (the `grid_v1` shipping controller) — the
  single ODOM-bound consumer.
- **Does not see drift:** everything MAP-bound, because `DriftingOdomProvider`
  passes truth through on MAP by default (a perfect global reference standing
  in for a localizer — *not* a localizer, per the anti-goal).
- **Never reads a pose at all:** the reactive gate, the TTC gate, and
  `apply_collision_brake` / `apply_reactive_safety`. Verified by inspection:
  they consume LiDAR ranges, bearings, and nearest-distance scalars —
  body-relative quantities only. `reactive_safety.py` touches
  `observation.robot` solely to compute an owner *bearing*, a relative
  quantity. **This is why the collision gate is drift-invariant**, and it is a
  structural fact, not a lucky result.
- **Out of the seam's reach entirely:** `follow_owner` and `circle_owner`
  (FollowOwnerController / SpatialBehaviorController run their own loop and
  never build a `NavObservation`), and the `stub_v0` degraded controller
  (allowlisted). `object_relative` episodes in this minival fail before moving.

## VERIFY 3 — walk_with_me with drift: zero hard collisions

`--mode headless`, frozen 10-script pack, per pose profile:

| pose profile | n | SR | **collisions** | `control_error` | pose-LOST holds |
|---|---|---|---|---|---|
| truth | 10 | 0.60 | **0** | 0 | 0 |
| `calibrated_go2` | 10 | 0.60 | **0** | 0 | 0 |
| `stress` (α=0.2) | 10 | 0.50 | **0** | 0 | 0 |
| `lost` | 10 | 0.50 | **0** | 0 | **3** |

The gate holds at every tier including the 20 %/20 m stress tier. Under
`stress` one script moves success → `termination` (a navigation outcome, not a
safety one). Under `lost`, the three headless navigation scripts
(`wwm-sidewalk-from-road`, `wwm-lamppost-standoff`, `wwm-absent-target`) all
report `detail="pose_lost_stop_and_hold"` with `FailureClass.REFUSAL`.

## VERIFY 4 — two defects the full suite caught that T0 could not

Both were mine, both are fixed, and both are worth recording because they show
what a single equality harness does *not* cover.

**(a) An extra `world.observe()` shifted a frozen physics baseline.**
`HeadlessCityQualityHarness.new_pose_provider()` originally read the world once
to learn the robot's start pose. `HeadlessCityWorld.observe()` draws from the
simulator's seeded LiDAR-noise RNG, so that one extra call shifted the entire
noise sequence: `test_embodied_plan_eval` moved `simulator_step_count`
1072 → **1071**.

T0 was blind to it because `NavInstructRunner` runs its own loop and never calls
`harness.run()`, so `new_pose_provider()` was never reached there. Attribution
was proven by running the embodied suite three ways:

| tree | `simulator_step_count` |
|---|---|
| pre-change snapshot (no Lane B) | 1072 |
| snapshot + Lane B only, before the fix | **1071** — mine, not Lane A's |
| snapshot + Lane B only, after the fix | 1072 |

Fix: providers **re-baseline on their first truth sample** instead of being told
where they start (`DriftingOdomProvider.reset()` clears a `_seeded` flag; the
first `update_truth` adopts the sample as the origin of all three frames with no
delta and no noise). A real odometry source has exactly this property — it
cannot know where it started until its first sample arrives. Pinned by
`test_the_first_truth_sample_after_reset_is_a_baseline_not_a_delta`.

**(b) The seam broke the frozen BARN sidecar.** `pipeline.py` is a v8
*replacement* source copied into frozen bundles whose `navigation/base.py`
predates the seam. Importing `MAP_FRAME` / `pose_in` from a module that exists
but lacks the names raises `ImportError` just as a missing module does, and the
historical sidecar died with
`cannot import name '_HAS_POSE' from 'parcel_robot.navigation.base'`.

Fix: `pipeline.py`'s seam import is soft **on the names**, with a compact
in-file fallback reproducing the pre-seam read — the same discipline the file
already applies to `paths`, `attributes`, `traffic_aware`, and `instructnav`.
`grid_navigator.py` needs no such guard: it is not a replacement source, so a
bundle uses its own pre-seam copy. The archon rule was taught that a pose read
*inside* a function named `pose_in` / `legacy_yaw` **is** the seam wherever it
lives, so the fallback does not need an allowlist entry.

### One red remains, and it is Lane A's

`tests/test_barn_v8_policy_bundle.py::test_real_historical_bundle_derives_only_the_reviewed_v8_delta`
now fails with:

```
policy sidecar rejected request: "ModuleNotFoundError: No module named 'parcel_robot.authority'"
```

`navigation/collision.py` is also a v8 replacement source and now imports
`parcel_robot.authority` (Lane A's new module), which is absent from the frozen
bundle's `src` tree and is not in `V8_ADDITIONS`. `collision.py` and
`authority.py` are both on Lane B's do-not-touch list, so this is **verified as
Lane A's and reported, not fixed**. Two fixes are available to Lane A: add
`authority.py` to `V8_ADDITIONS`, or make `collision.py`'s import soft the way
`pipeline.py` does. Lane B's own ImportError on this test is gone.

---

## B-1 — the seam

`src/parcel_robot/pose.py` (new). `PoseEstimate` is a frozen SE(2) + row-major
3×3 covariance + `frame` + `health` + `stamp_monotonic_s`, validated
**fail-closed**: non-finite entries, wrong covariance length, negative
variance, asymmetry, and an indefinite xy block all raise rather than letting a
corrupt estimate reach an arrival check.

`observation_pose(observation, frame)` is the only sanctioned pose read.
Resolution order: provider attached to `extras` (production) → process-default
provider (eval/test injection) → **the observation's own truth fields**. That
third branch is what makes the migration equality-preserving: every unmigrated
caller and every test that builds a bare `NavObservation` gets exactly the
floats it always did, because the fallback *is* `TruthPoseProvider` semantics.

### Frame-role binding — every migrated call site

| # | call site | frame | why |
|---|---|---|---|
| 1 | `pipeline._memory_candidates` (ranking recalled entities) | MAP | semantic memory is a world-frame store |
| 2 | `pipeline._commit_semantic_candidate` (watchdog seed distance) | MAP | measured against a world-frame approach pose |
| 3 | `pipeline._reanchor_landmark_goal` (via B-4 metadata) | MAP | landmark anchoring is a MAP operation |
| 4 | `pipeline._step_semantic_resolution` (grounding origin) | MAP | candidates are world-frame semantics |
| 5 | `pipeline._step_search_entity_frontier` (robot xy, viewpoints) | MAP | frontier targets are world-frame |
| 6 | `pipeline._progress_watchdog` | MAP | range to a world-frame goal; an ODOM read would report drift as "no progress" and fail a converging mission |
| 7 | `pipeline._semantic_arrival_verified` (K0) | MAP | K0 is the single arrival authority; arrival is a world claim |
| 8 | `pipeline._inside_arrival_goal_region` (K0) | MAP | `GoalRegion` is a world-frame object |
| 9 | `pipeline._terminal_environment_is_clear` (LiDAR projection) | MAP | projects returns into the MAP-frame arrival polygon |
| 10 | `pipeline._pose_lost_hold` (health) | MAP | MAP health is what K0 depends on |
| 11 | **`grid_navigator.act`** | **ODOM** | short-horizon control; the rolling grid needs *continuity*, and a MAP correction jump would smear obstacles across it |

Three yaw reads (`_step_semantic_resolution`, `_step_scan_behavior`,
`_step_search_entity_frontier`) go through `_legacy_yaw` — see the defect below.

`test_pose_authority_archon.py::test_every_migrated_pose_read_names_its_frame`
AST-checks that no seam read is ever made without an explicit frame constant.

### Defect found (pre-existing, deliberately NOT fixed)

**`NavObservation.position[2]` is the robot's standing height, and
`pipeline.py` has always read it as yaw in radians.** `position` is
`(x, y, z)`; a standing Go2 has `z = 0.27 m`, so four sites believed the robot
was facing **15.5°** off its true heading during scan and frontier geometry.
Confirmed live: `HeadlessCityWorld().observe()` → `z = 0.27, yaw = 0.0`.

Fixing it changes behavior, so it belongs in its own paired-seed commit (plan:
equality first, value changes separately). It is now collapsed from four
anonymous sites into **one named function**,
`pose.legacy_position_yaw`, whose docstring says it is a bug and whose deletion
is the fix. Both of the original fallbacks (three sites fell back to
`radians(heading_deg)`, one to `0.0`) are reproduced exactly rather than
unified — unifying them would be a behavior change hiding inside a refactor.
Pinned by `test_pose_seam.py::test_legacy_position_yaw_reads_z_height_as_yaw_and_that_is_the_bug`.

### Archon rule and allowlist state

`tests/test_pose_authority_archon.py` — plain AST walk, no new lint plugin (a
binding anti-goal). Seam: `pose.py`, `navigation/base.py`.

| allowlisted file | sites | reason |
|---|---|---|
| `navigation/approach.py` | 3 | `safe_approach_pose` geometry — not Lane B's file |
| `navigation/instructnav_recovery.py` | 3 | memory-ingest origin + the same `position[2]` yaw defect |
| `navigation/semantic_map.py` | 1 | `ObservationSemanticMap.query` frustum origin |
| `navigation/models/__init__.py` | 2 | `StubNavigator` point-goal fallback (degraded controller) |

**9 sites in 4 files.** The list can only shrink: a parametrized test fails if
an allowlisted file has no direct read left (stale entry), and a separate test
pins `pipeline.py` and `grid_navigator.py` as clean so a silent un-migration is
red.

## B-2 — drift injector, and where the calibration honestly deviates

`DriftingOdomProvider` implements the Probabilistic-Robotics Table 5.6
alpha odometry model on incremental truth deltas, seeded per run, plus optional
per-run systematic bias (a miscalibrated body, drawn once). MAP is truth
passthrough by default; `calibrated_go2_reanchoring` makes MAP follow ODOM and
snap back every 5 s, which is the only way to exercise REP-105's "MAP may jump".

**The deviation, stated plainly.** The card asks for cumulative drift inside the
published DogLegs bands (0.5–1 %/distance translational, 0.2–0.5 deg/m yaw).
**Those two numbers cannot both describe end-of-path drift on one 20 m run**,
and forcing a pass would have been a fabricated calibration:

- Accumulated position error is dominated by *heading* error. A mid-band
  0.35 deg/m carried over 20 m contributes ≈ `D·θ/2` = 0.6 m ≈ 3 % of distance
  before any translational noise is added at all.
- Measured from the other side: changing `alpha3` by 10× (0.01 → 0.001) moves
  end-of-path drift by **under 1 % relative** (1.68 % → 1.67 %). Translational
  noise is not what sets the number.
- The published translational figure is a short-sub-segment relative error
  (KITTI-style RPE), not an accumulated one.

So `calibrated_go2` calibrates to the band that governs the outcome and is
length-independent, and **pins the other as measured**:

| quantity | value | status |
|---|---|---|
| yaw drift, D = 10 / 20 / 40 m | 0.378 / 0.311 / 0.275 deg/m | **in** the published 0.2–0.5 band, at every length |
| translational **scale** error (rotation noise off) | 0.60 % of distance | **in** the published 0.5–1 % band |
| accumulated end-of-path translation, D = 20 m | 2.3 % of distance | **measured and pinned**, honestly above the published band |
| `stress` (α = 0.2), D = 20 m | 20.3 % / 2.12 deg/m | pinned stress tier, ~20× the published band |

Yaw is made length-independent by using the per-run **bias** as the primary
knob (`E|bias| = σ√(2/π) = 0.28 deg/m`): a pure alpha random walk grows as
`√D`, so its deg/m figure halves every time the path quadruples. The alphas
stay small and non-zero so runs differ stochastically, not only by drawn bias.

The plan's literal `alpha* = 0.2` survives as the **dataclass defaults** and as
the `stress` profile; the config comment shows the full derivation.
`tests/test_pose_drift_calibration.py` (12 tests, 60 seeds) enforces every row
above, plus determinism-per-seed, seed-diversity, monotone covariance growth,
and a degenerate check that zero noise reproduces truth exactly.

## B-3 — health / LOST

- `TruthPoseProvider` is `HEALTHY` by construction and **can never** reach these
  paths (pinned by test).
- **K0**: `_semantic_arrival_verified` returns not-verified with
  `mission.metadata["arrival_not_verified_reason"] = "pose_unhealthy"` when MAP
  health is not `HEALTHY`. Honest refusal, not a crash, and not a mission
  failure — the verification budget is untouched and health can return.
- **DEGRADED does not stop the body.** It only blocks the arrival claim. That is
  the smallest honest response to "I am less sure than usual".
- **LOST stops the body**: `_pose_lost_hold` returns
  `MidLevelCommand(stop=True, note="pose_lost_hold")` with the mission left
  *running*, and releases when health returns.
- **walk_with_me** surfaces it through the existing failure/attribution
  machinery: `FailureClass.REFUSAL`, `detail="pose_lost_stop_and_hold"`, a
  `pose_lost` flag and an owner-facing `reply` on the final trace sample. No new
  event channel was invented.

## B-4 — landmark-relative goals

At commit, `_commit_semantic_candidate` stores `goal_landmark_id`,
`goal_landmark_position` and `goal_landmark_offset` **alongside** the
world-frame goal, which remains primary and is the only fallback. On any tick
where the *same* `candidate_id` is re-observed at a different position, the goal
is re-derived as `fresh_landmark + stored_offset`, the arrival `GoalRegion` is
translated by the same delta (otherwise K0 would verify against a stale
polygon), and the progress-watchdog baseline is reset (a goal that moved is not
a robot that stalled).

Hard constraints, both tested: **re-anchor only, never switch** (a different
instance id cannot move the goal), and **world-frame remains the fallback** (a
goal with no landmark id — POIs — is untouched). An unmoved landmark is a strict
no-op below `LANDMARK_REANCHOR_EPSILON_M = 1e-9`, which is what keeps T0 exact:
without it a float round-trip through the offset could move the goal by an ULP.

## B-5 — chance-constrained membership

`p_inside_polygon(pose, polygon, clearance_m)` — product of per-edge
`Φ(d_i / σ_i)` with `σ_i² = nᵀΣ_xy n`, the standard half-space chance
constraint (exact for convex polygons, an upper bound otherwise; documented).
At zero xy covariance it **short-circuits to the boolean predicate**, so it
returns exactly 1.0 or 0.0 and cannot disagree with today's geometry by a ULP —
that exactness is what allows it to be wired at all.

Wired at `pipeline._inside_polygon_verified`, used by both inside-relation
branches of `_semantic_arrival_verified`. Threshold 0.9, read from
`configs/navigation/pose.yaml` (one place, resolved lazily, with a documented
fallback for frozen BARN bundles that ship no configs).

`pose.py` keeps its own copy of the boolean predicate to stay at the bottom of
the import graph; a dense-grid test pins it against
`approach.point_in_polygon_with_clearance`, including the `+1e-9` clearance
slack — copying that slack was load-bearing, since a bare `>=` disagrees by one
ULP on points exactly `clearance` from an edge.

---

## Hand-offs

1. **`Z_r` → Lane A's `SafetyEnvelope`.** `PoseEstimate.position_sigma_m`
   (`sqrt(σ_xx + σ_yy)`) is the scalar Lane A's
   `SafetyEnvelope.pose_uncertainty_m` field expects. Nothing is wired: with
   `TruthPoseProvider` it is exactly 0.0, which is the value Lane A already
   ships. Wiring it is a behavior change and belongs in a paired-seed commit.
2. **Owner-channel LOST announcement.** The navigator stops and walk_with_me
   records it; the runtime does **not** yet speak it to the owner. The reply
   text exists on the trace sample, unspoken. Later card, as scoped.
3. **`map` → `odom` transform.** `grid_navigator` is ODOM-bound but
   `mission.goal` is a MAP quantity, and there is no transform between them.
   With `TruthPoseProvider` the frames are identical so nothing moves; the
   moment a real localizer occupies the MAP role, `grid_navigator.act` is the
   one call site that needs the transform. This is named in the code.
4. **Sites not migrated** — the 9 allowlisted reads in 4 files above, none of
   which Lane B owns this round.
5. **Attribution taxonomy has no localization layer.** L1–L6 has nowhere for
   "lost localization", so the walk_with_me LOST row carries no attribution
   override; `detail` carries the cause. Inventing a layer would have been
   worse than reporting none.
6. **`pipeline.py` still imports the deprecated `ROBOT_FOOTPRINT_RADIUS_M`**
   and emits Lane A's `DeprecationWarning`. That migration is Lane A's
   family-by-family card, deliberately not done here to avoid a cross-lane
   conflict.

## Non-claims

1. **There is no localizer.** No SLAM, no EKF, no filter of any kind. `MAP`
   under the drift provider is sim truth passed through, standing in for a
   perfect global reference so the binding can be measured. A real localizer
   slots into the MAP role behind `PoseProvider` — that is the point, and it is
   still a P5 HR-ledger item.
2. **The drift model is a stand-in for leg odometry, not a model of one.** It
   is calibrated to one published yaw band on one canned trajectory. It has no
   terrain dependence, no slip, no gait coupling, no IMU.
3. **T1 is measurement, not a gate, and it is weak evidence.** The frozen
   minival travels 13.5 m in total across 25 episodes; drift accumulates
   0.008–0.51 m. A flat SR here says almost nothing about robustness — the only
   success in the set is on a code path the seam does not touch.
4. **The covariance is not a filter output.** `DriftingOdomProvider` accumulates
   the model's own per-step variances as an isotropic xy term plus a yaw term.
   It is a documented approximation, not an estimate.
5. **The chance constraint has never fired in a real run.** Every run in this
   round used zero covariance on the K0 path, so the non-zero branch is covered
   by unit tests only.
6. **Landmark re-anchoring has never fired in a real run either.** In the sim,
   a landmark's observed position is truth and does not move, so
   `_reanchor_landmark_goal` is a no-op on every episode measured here. It is
   proven against synthetic drift, not against a moved landmark in the city.
7. **The `position[2]`-as-yaw defect is named, not fixed.** Every number in this
   round was produced with the defect live, exactly as every previous number was.
8. **`follow_owner` / `circle_owner` are outside the seam.** They never build a
   `NavObservation`, so no pose profile reaches them and no claim here covers
   them.
9. **The `stub_v0` controller is not on the seam** and would keep using truth
   under a drifting provider. Allowlisted and tested as such.

## Files touched

| file | change |
|---|---|
| `src/parcel_robot/pose.py` | **new** — the whole seam: frames, health, estimate, providers, config, chance constraint |
| `configs/navigation/pose.yaml` | **new** — 5 profiles + the calibration derivation + threshold |
| `src/parcel_robot/navigation/base.py` | `MAP_FRAME`/`ODOM_FRAME`, `pose_in`, `legacy_yaw` (shared by pipeline and controller) |
| `src/parcel_robot/navigation/pipeline.py` | 12 migrated reads, LOST hold, K0 health gate, chance-constrained inside, landmark storage + re-anchoring |
| `src/parcel_robot/navigation/grid_navigator.py` | the single ODOM-bound read |
| `src/parcel_robot/headless_city.py` | per-run provider on the harness, provider threaded into `_nav_observation` (optional arg — the eval runner is unchanged) |
| `src/parcel_robot/runtime.py` | one `TruthPoseProvider` per runtime, fed from every observation |
| `evals/walk_with_me/runner.py` | `pose_profile` plumb-through + LOST outcome |
| `evals/walk_with_me/run_walk_with_me_v1.py` | `--pose-profile` flag |
| `tests/test_pose_seam.py` | **new** — 44 tests |
| `tests/test_pose_drift_calibration.py` | **new** — 12 tests |
| `tests/test_pose_consumers.py` | **new** — 19 tests |
| `tests/test_pose_authority_archon.py` | **new** — 7 tests (the architecture rule) |
| `backlog/UNVERIFIED.md` | **U34** appended — the seam-is-not-a-localizer HR row |

`evals/nav_instruct/**`, `tests/test_voice_nav_e2e.py`, `instructnav/scoring.py`,
and every Lane-A-owned file: **untouched**.

## Verification

| check | result |
|---|---|
| T0 NAV_INSTRUCT candidate minival, before vs after | **empty diff**, identical sha256 `50d7e517…` (re-verified after every card, and again after both fixes) |
| T0 determinism precondition | two pre-change runs byte-identical |
| embodied_plan frozen physics baseline | `simulator_step_count` 1072, unchanged (three-way lane attribution above) |
| T1 drift smoke (3 profiles × 25 episodes) | run; table above; 0 collisions at every tier |
| walk_with_me headless (4 profiles × 10 scripts) | **0 hard collisions at every tier**, LOST fires 3/3 |
| new tests | **82** (44 + 12 + 19 + 7) |
| `ruff check` on every Lane B file | clean (9 pre-existing errors elsewhere in `tests/` untouched) |
| full default suite | **2398 passed, 7 skipped, 5 xfailed, 1 failed** (666 s) — the single red is the Lane-A BARN-bundle `parcel_robot.authority` import above |
| record | `backlog/UNVERIFIED.md` gains **U34** (the HR-ledger row: seam, not localizer) |
