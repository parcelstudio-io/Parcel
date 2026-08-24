# NAV-CORE v2 — RESULTS · Opus executor · 2026-08-24 · tier `desktop-sim`

## DECISION (pre-registered rule, applied literally)

**Both arms fail their bars, so the DESIGN's rule fires arm C: the delegation
scoping note, and stop.** Arm A (retained `DirectiveNavigator` + grid_v1
semantic ladder) arrived **0 / 60**. Arm B (metric point goal at the stored
coordinate, same controller, ladder bypassed) arrived **29 / 60 = 0.48**. The
bar was ≥ 0.80 for either arm. N4 (100 % typed non-arrivals) also failed on
both: 0.45 for A, 0.00 for B.

**The note's conclusion is that delegation is the wrong fix** (§arm C). The
defects behind these numbers all sit in Parcel's own glue, not in the planner a
Nav2-class subsystem would replace, and one — three uncoordinated clearance
rings — caps *both* arms and would cap a delegated planner identically. What
the evidence supports: fix the clearance coupling, re-run this corpus (250 s),
then decide retain-vs-simplify; if M1 must ship first, ship arm B's shape with
a typed refusal bolted on, because arm B is the only arm that ever completes.
Stopped at the decision; no parameter was tuned after the first corpus run.

## What was run

```
env -u TMPDIR .parcel/bin/python research/20260824/nav-core/bench.py --stage corpus
env -u TMPDIR .parcel/bin/python research/20260824/nav-core/bench.py --stage refuters
env -u TMPDIR .parcel/bin/python research/20260824/nav-core/stall_probe.py
env -u TMPDIR ~/.cache/parcel-guard/pytest_guard.sh --label navcore \
  .parcel/bin/python -m pytest tests/test_navcore_probe.py -q   # 4 passed, 0.5 s
```

Raw rows: `results/corpus.json` (60 episodes × 2 arms), `results/refuters.json`,
`results/stall_mechanism.json`. `report.py` regenerates every table below from
those files; no number here is typed by hand. Live logs are under `logs/`
(gitignored, C14). No GPU, no model server, no hosted call, **$0**. Corpus wall
time 250 s. Environment (also in each JSON): host jaewoo-jang-parcel, python
3.14.4, 2026-08-24T08:17Z; `obstacle_stop_m` 0.65, `obstacle_slow_m` 1.2,
`reaction_time_s` 0.12, `planner_inflation_m` 0.593, gate demand at grid_v1
cruise 0.752 m, room worst clearance 0.88 m, aliased-scan disagreement
8.9e-15 m.

## The stack under test

* **Door** — every goal enters through the product's hosted rail:
  `realtime_broker.handle(name="navigate_to")` → `_place_admission` →
  `intent_router.route` → `sketch_navigate` → `_admit_local_sketch` →
  `_accept_plan`. All six places admit with rule `navigation_directive`.
* **Pose** — `DriftingOdomProvider(calibrated_go2)` as ODOM under
  `ScanMatchLocalizer` as MAP, composed by `LocalizedPoseProvider`. Sim truth
  reaches the ODOM source only; `NavObservation.position` carries the MAP
  estimate, not truth; the obstacle channel is derived from the scan.
* **Semantics** — `perception_source = learned_map`, so `PlaceGrounder` is
  empty (no POI oracle) and candidates come from an `OnlineSemanticMap` fed ten
  evidence frames per place. Detector shaping on top: 0.20 dropout per
  re-detection (measured 0.200), per-axis σ = 0.15 m jitter (measured radial
  RMS 0.212 m = √2·0.15), polygons and `associated_lidar_ids` stripped.
* **Scan** — `raycast_planar_scan`, 360 rays at 0.45 m, occlusion-true, one 2 s
  gap per episode at a seed-determined phase.
* **Room** — 8 × 8 m, six known places, four nested clutter layouts; every
  place and start keeps ≥ 0.88 m clearance in every layout and is reachable on
  a 0.1 m grid inflated by 0.95 m (`audit_clearances`, pinned by the probe
  test), so a missed arrival is the navigator's result.

## Rows N1–N5

| row | bar | arm A | arm B |
|---|---|---|---|
| N1 arrival ≤ 0.5 m | ≥ 0.80 either arm | **0.00** | **0.48** |
| N1′ arrival, object-class goals only | (diagnostic) | 0.00 | 0.42 |
| N2 false arrivals (corpus) | 0 | **0** | **0** |
| N3 contacts | 0 | **0** | **0** |
| N4 typed non-arrivals | 1.00 | **0.45** | **0.00** |
| N5 median time-to-goal (s) | reported | — | 11.20 |
| N5 median path/optimal | reported | — | 0.81 |
| episodes | 60 each | 60 | 60 |

Non-arrival reasons — arm A: `silent_stall_step_limit` ×33,
`verification_failed` ×15, `not_found` ×12. Arm B: `silent_stall_step_limit`
×31.

`path/optimal` below 1 is expected: "optimal" is the straight line to the
stored point, arrival is scored at ≤ 0.5 m of it. Largest single-update MAP
discontinuity over all 120 episodes: **0.029 m** (median 0.009 m) — the first
measured value for `bridge/timing.py`'s `localization_jump_m`, UNMEASURED on
every host record.

## N6 — refuters: **3 of 5 kinds behave as specified**

R1, R2, R4 pass; R3 is mixed (one false arrival); R4b is failed by both shipped
arms.

| refuter | arm | n | declared | false arrivals | contacts | translating ticks during scan gap | latched |
|---|---|---|---|---|---|---|---|
| R1 scan dropout | A | 3 | 0 | 0 | 0 | 0 | 0 |
| R1 scan dropout | B | 3 | 0 | 0 | 0 | 0 | 0 |
| R2 pose DEGRADED | A | 3 | 0 | 0 | 0 | 0 | 0 |
| R2 pose DEGRADED | B | 3 | 3 | 0 | 0 | 0 | 0 |
| R3 moved obstacle | A | 3 | 0 | 0 | 0 | 0 | 0 |
| R3 moved obstacle | B | 3 | 3 | **1** | 0 | 0 | 0 |
| R4 place absent | door | 3 | 0 | 0 | 0 | 0 | 0 |
| R4b kidnap (3 configs × 2 arms) | — | 18 | 0 | 0 | 0 | 0 | 6 |

**R1 — PASS, mechanism worth naming.** Zero translating ticks in 1 200 scan-gap
ticks across the whole corpus. The HOLD comes from the *reactive gate* (P0-B),
not the controller: grid_v1 ships `safe_valley_micro_advance=False`, so
`GridNavigator` logs "degraded to point-goal fallback" and keeps commanding;
only `apply_reactive_safety` stops it. **R2 — PASS.** No arm declared arrival
with a non-HEALTHY pose; arm B held through the forced 2.5 s gap (0 / 45
translating ticks) and declared only after health recovered, inside the band.

**R3 — MIXED.** No contacts either arm. Arm B replanned around the injected box
and arrived 3 / 3 — but **one was a false arrival**: seed 303,
`arrival_confidence` 0.9922 against a 0.90 threshold, truth distance 0.534 m
against a 0.5 m band. The chance constraint was optimistic because the
localizer's covariance is optimistic — H7's missed L5/NEES row, reproduced as
an actual wrong claim. Arm A neither replanned nor typed a failure; it stalled.

**R4 — PASS.** With `place_counter` never learned the door refuses 3 / 3 and
names the places the map does hold ("…no place called 'kitchen counter'; the
places it does know nearby are…") — earned from perception, not a sidecar.

## Refuter 4b — the kidnap into the aliased corridor

The aliased world has exact two-fold rotational symmetry, so a pose and its
180° image produce scans agreeing to 8.9e-15 m, and the ODOM feed is re-based
across the jump (H7's mechanism) so proprioception cannot see it either. The
goal's C2 twin is a *real other place* (`place_counter` ↔ `place_shelf`).

| configuration | arm | post-kidnap path (m), 3 seeds | latched | false arrival |
|---|---|---|---|---|
| shipped | A | 0.84 / 0.27 / 0.71 | no | 0 |
| shipped | B | 0.23 / 0.06 / 0.01 | no | 0 |
| A4/A10 gate | A | 0.00 / 0.00 / 0.00 | **yes** | 0 |
| A4/A10 gate | B | 0.00 / 0.00 / 0.00 | **yes** | 0 |
| gate + operator reset | A | 2.18 / 2.19 / 1.95 | re-armed | 0 |
| gate + operator reset | B | 2.27 / 2.25 / 2.26 | re-armed | 0 |

Post-kidnap MAP health was HEALTHY on 840/840, 834/840 and 824/840 ticks in the
three seeds, in every configuration.

**FAILED by both shipped arms.** MAP reported HEALTHY on essentially every
post-kidnap tick (824–840 of 840) while tracking the wrong half of the room,
and both arms kept translating — 0.84 m for arm A. The bar is "NO motion
resumes on HEALTHY alone", and motion did. No false arrival occurred, but only
because the brake rings (below) stopped both arms short of the twin — luck, not
a defence.

The modelled A4/A10 latch caught it 3 / 3 and held motion at exactly 0.00 m.
Both A4 re-arm paths behaved as A4 predicts: path (a), the whole-map
second-best margin, **never fired** — `GlobalMatcher` measures margins of
2.2–30.7 in a normal layout against 0.002–0.03 in the aliased one, threshold
0.25 — and path (b), the journalled operator pose-reset-and-validation
transaction, re-armed after verifying scan agreement, after which both arms
moved ~2.2 m and still claimed nothing false.

## N7 — the A-vs-B delta

Arm B buys 29 arrivals arm A never gets. Arm A buys typed honest failure on
45 % of its non-arrivals against 0 % for arm B, and refusal to claim an arrival
it cannot verify. **On the corpus the ladder's advertised benefit was not
observable** — neither arm produced a false arrival, because arm B's goals are
exact stored coordinates with no positional error to be wrong about. The
difference appears once, in the refuters: R3 gave arm B a false arrival that
arm A's verification would have refused. The ladder's value is real but
unpriced here; its cost, 29 arrivals, is measured.

## Fix list (product; no product file was edited)

1. **Region-class goals cannot resolve from the learned map.**
   `goals.semantic_goal_from_directive("bed")` returns `kind="region"` (R10's
   place-class table); `learned_map_candidates` stamps every row
   `kind="object"`; `ObservationSemanticMap.query` requires equality. All 12
   `bed` episodes returned `not_found` in arm A while arm B reached the same
   place. Fix at the ingress or make the query kind-tolerant; pinned by
   `tests/test_navcore_probe.py`.
2. **Arrival verification demands evidence only the oracle supplies.** On
   15 / 60 arm-A episodes the target was resolved and driven to, and
   `_semantic_arrival_verified` wrote `arrival_not_verified_reason =
   "target_surface_unobserved"`. The learned map carries no polygon and no
   `associated_lidar_ids`, so that half of the check is unsatisfiable
   off-oracle: arm A is honest and unable to complete.
3. **Three uncoordinated clearance authorities — the row that caps both arms.**
   The planner inflates 0.42 m (footprint 0.32 + `map_safety_margin_m` 0.10);
   the pipeline's collision brake stops at `safety.stop_distance_m` 0.80 m; the
   reactive gate stops at `obstacle_stop_m` 0.65 + v·`reaction_time_s` 0.12 =
   0.752 m at grid_v1's 0.85 m/s cruise. `stall_probe.py`: **8 / 8** sampled
   stalls ended inside a brake ring with the route still `status=planned` — arm
   A at ~0.79 m (pipeline brake, note `|obstacle_stop`), arm B at ~0.74 m
   against the 0.752 m gate demand. No brake tells the planner to replan, and
   `ReactiveSafetyPolicy.planner_inflation_m` — which exists for exactly this
   and says so in its docstring — is passed by no product call site. Passing it
   changes nothing: `grid_navigator._planner_coupling_ring_m` caps the request
   "tighter-only, deliberately" pending card DOOR-1's halted item H-2. Cost:
   33 / 60 arm-A and 31 / 60 arm-B episodes.
4. **No second-best relocalization margin exists in the product.**
   `ScanMatchLocalizer._relocalize` scores keyframes, keeps the best and never
   reports a runner-up, so A4's "globally discriminative … second-best worse by
   a pre-registered margin across the whole map" is not computable today. The
   harness computes it (`relocalize.GlobalMatcher`: 0.4 m coarse grid, 0.1 m
   refinement of the two finalists, exact yaw sweep by circular shift). The
   product needs an equivalent before A4's re-arm rule can be wired at all, and
   A10's latch needs somewhere to publish its trigger value.
5. **The chance-constrained arrival trusts an uncalibrated covariance.** R3's
   false arrival was declared at p = 0.9922 with the body 0.534 m from the
   goal — H7's L5 miss reaching an arrival claim.
6. **`arrival_radius_m` 0.12 m** — the ladder commits to a 0.12 m terminal
   radius against a 0.5 m milestone band; why arm A's terminal phase is long
   and fragile under drift.

## Arm C — the delegation scoping note

A Nav2-class subsystem would replace global planner, local controller, costmap,
recoveries and their lifecycle. **Every one of those worked here.** In all 64
stalled episodes the route existed and read `status=planned`; the body stopped
because two brakes Parcel owns disagreed with the inflation Parcel's planner
used. Delegation leaves every substantive defect in place: 1 and 2 are Parcel's
semantic ingress and arrival contract, 4 is Parcel's localizer contract, and 3
reproduces identically the moment Parcel keeps its own reactive gate above a
delegated planner — which the safety core requires, `finalize_command` and the
reactive gate being untouchable.

Cost side: ROS 2 on an Orin-NX-class body, a TF/odom/scan/costmap bridge, a
lifecycle manager, and re-derivation of the stopping envelope through a second
authority — milestone-sized, and it buys none of the fixes.

**Scoping verdict: do not delegate for M1.** Do fix 3, re-run this corpus
unchanged, re-read N1: if arm A then clears 0.80, retain; if only arm B does,
simplify and take fixes 1–2 post-milestone. Fix 5 and the A4 latch (fix 4 plus
the modelled gate, measured to work) are BUILD_BLOCKER regardless of topology,
because refuter 4b is failed by both arms today.

## Does not prove

`desktop-sim` with physical-shaped inputs. Not physical navigation, not real
perception, not real localization: the scan is a ray engine, the detector noise
is synthetic (H6 owns detector fidelity), the body is kinematic, and the learned
map was seeded by the harness rather than built by looking. Nothing here speaks
to city scale, multi-room topology, or goals absent from the map (H8). The
A4/A10 latch and the whole-map margin are *harness models of a proposed
policy*, not product code. Per the Codex cross-review appended to DESIGN.md the
observation boundary is still `SimObservation` plus untyped `extras`, and
hardware promotion needs real localization health, real obstacle evidence,
sole-writer actuation, a local STOP and supervised point-goal trials whichever
arm wins.

## Cost

$0 hosted; no GPU, no model server, no judge. The owner's stack (`:8765`,
`/tmp/parcel_sim.sock`, `parcel_memory.sqlite3`) was never touched; the learned
map lives in `:memory:`. Git untouched — nothing committed.

