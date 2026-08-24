# A2 NAV-GLUE — executor register (Opus) · 2026-08-24

Card: `A2_NAVGLUE_BRIEF.md`. Grounding: `research/20260824/nav-core/{RESULTS,
VERDICT,REFUTER_4B_REMEASURE}.md`, plan row A2. Guard label `a2-navglue`,
never `-n auto`, never `ci_gate --tier`, git READ-ONLY, nothing committed.
Owner's stack (`:8765`, `/tmp/parcel_sim.sock`, `:8080`,
`parcel_memory.sqlite3`) untouched; `runtime.py` untouched; zero `noqa`; zero
new ruff fingerprints.

## THE DECISION (pre-registered rule, applied literally)

**Arm A did NOT clear 0.80 (0.10) ⇒ DO NOT RETAIN the semantic ladder for M1.
Arm B did not clear it either (0.483), so the "only arm B ≥ 0.80" branch does
not literally fire — but arm B remains the only arm that completes, so the rule's
fallback stands: SIMPLIFY. M1 ships arm B's shape plus a typed refusal; fixes 1
and 2 stay as post-M1 semantics.** No parameter was tuned after the run.

The decision is stronger than the bar alone, and the reason is a structural one
this card measured rather than guessed: for OBJECT/UNKNOWN-class goals the
ladder's `near` terminal stands the body **1.12–1.40 m** from the target — a
band derived from the pipeline's own 0.80 m collision brake plus the 0.32 m
footprint — while N1 scores arrival at **≤ 0.50 m** of the stored point. Arm A's
`N1_arrival_rate_object_class_goals` is therefore **0.00 by construction**, and
the four "false arrivals" below are that same fact in the other column. Closing
it needs either a looser brake (forbidden) or a re-derived stand-off family
(`StandOffEnvelope` / `safe_approach_pose`), which is a milestone-sized change
this card did not make. The ladder cannot meet an M1 band that sits inside its
own stopping envelope.

## Corpus re-run — `bench.py --stage corpus`, UNCHANGED (223.4 s, $0)

Same corpus, seeds (101/202/303), bars, door. Pre-A2 rows preserved beside the
new ones as `results/{corpus,refuters,stall_mechanism}_pre_a2.json`.

| row | bar | arm A pre → post | arm B pre → post |
|---|---|---|---|
| N1 arrival ≤ 0.5 m | ≥ 0.80 either arm | 0.00 → **0.10** | 0.483 → **0.483** |
| N1′ object-class goals only | (diagnostic) | 0.00 → 0.00 | 0.417 → 0.417 |
| N2 false arrivals | 0 | 0 → **4** | 0 → 0 |
| N3 contacts | 0 | 0 → **0** | 0 → **0** |
| N4 typed non-arrivals | 1.00 | 0.45 → **0.88** | 0.00 → 0.00 |
| N5 median time-to-goal (s) | reported | — → 46.95 | 11.20 → 11.20 |
| N5 median path/optimal | reported | — → 1.037 | 0.815 → 0.815 |

Arm A failure histogram 33 `silent_stall_step_limit` / 15 `verification_failed`
/ 12 `not_found` → **6 / 17 / 27** (plus 10 declared). All 27 `not_found` now
carry the note `semantic_target_unreachable`: the ladder released every instance
and spent its replan budget, which is a typed give-up where it used to be a
step-limit death.

**Arm B is byte-identical, and that is expected, not a miss.** The harness builds
arm B through `ModelRegistry.create` directly, which is not a production planner
site; an un-commissioned caller still gets the legacy 0.42 m inflation by design
(see the re-freeze scoping below). Arm B's 31 stalls are therefore the *pre-fix*
number and the A-vs-B comparison after A2 is a commissioned ladder against an
un-commissioned point-goal arm. Stated so the decision is not read off an
artifact: fixing arm B would require commissioning `configs/navigation/models/
grid.yaml` itself, whose blast radius is every BARN/eval consumer of `grid_v1`
(see UNDONE 1).

### N2 — the four declarations, named individually

| arm | seed | ep | goal | truth distance | relation |
|---|---|---|---|---|---|
| A | 101 | 8 | `place_couch` | 1.371 m | `near` |
| A | 101 | 15 | `place_bowl` | 1.436 m | `near` |
| A | 202 | 13 | `place_desk` | 1.394 m | `near` |
| A | 202 | 15 | `place_bowl` | 1.465 m | `near` |

Every one lies inside the band the mission itself committed to
(`[minimum_vicinity_radius_m 1.12, vicinity_radius_m ~1.40]`) with a fresh
detection of the goal class in hand. They are not wrong-place claims — the body
is standing exactly where "near the desk" means under the product's own arrival
contract — but under the corpus's ≤ 0.50 m definition they score as false
arrivals and **N2's zero bar is broken**. Recorded, not argued away.

### Did the body get there? (the fix-3 question, separable)

| arm A, over 60 episodes | pre | post |
|---|---|---|
| median final distance to the place | 3.455 m | **1.505 m** |
| episodes ending within 1.5 m | 9 | **30** |
| episodes ending within 0.5 m | 0 | **11** |

`stall_probe.py` re-run: `stalled_inside_a_brake_ring` **1.00 → 0.75**, and all
of the remaining 0.75 are arm B rows (un-commissioned planner, ~0.74 m against
the 0.752 m gate demand — the untouched pre-fix mechanism). The three arm-A rows
now sit at 0.982 / 0.673 / 1.106 m of scan clearance, one of them on
`obstacle_slow`, i.e. outside the stop rings entirely.

### Refuters — re-run, no regression

`bench.py --stage refuters` re-run in full: every row's disposition is identical
to pre-A2 (R1 0/6 gap-translating ticks, R2 arm B declares 3/3 with 0 false, R3
arm B 3/3 declared with **1 false arrival at p = 0.9922** unchanged, R4 door
refuses 3/3, R4b latched 3/3 in both gated configurations, 0 contacts
everywhere). R3's false arrival is a HARNESS chance constraint in `arms.py`
(`pose.p_inside_disc`), not the product's verification path, so no product fix
can move it; the product-side requirement is pinned instead by
`tests/test_a2_navglue.py::test_an_off_oracle_arrival_is_refused_on_confidence_alone`.
A3 owns the calibration.

## Per-fix deltas, where separable

The three fixes are causally chained (fix 3 must land before the body reaches
the place, fix 1 before a region goal resolves, fix 2 before anything can be
claimed), so a clean N1 ablation per fix is not available. What IS separable:

| fix | separable evidence | pre → post |
|---|---|---|
| 1 kind tolerance | the 12 `place_bed` episodes (the only region-class goals in the corpus) | 12/12 `not_found` → **6 verified, 5 silent stall, 1 not_found**. All six of arm A's arrivals are bed goals. |
| 2 off-oracle arrival | arm A declarations | 0 → 10 (6 inside 0.5 m, 4 at the `near` stand-off). `target_surface_unobserved` is no longer written on a learned-map target. |
| 3 one clearance authority | `silent_stall_step_limit`, and the reach table above | 33 → 6; median final distance 3.455 → 1.505 m |
| 3.4 brake→replan | arm A typed non-arrivals (N4) | 0.45 → **0.88** |

Staged single-seed development diagnostic (seed 101, arm A, episodes 0–5,
NOT the pre-registered corpus): after fix 3 alone, episode 2's final distance
went 5.218 → 0.66 m and episode 5 became a typed `verification_failed`; after
fix 1, the bed episodes drove to 0.079–0.272 m of the place but could not claim;
after fix 2, they claimed.

## The three fixes, as built

### Fix 3 — ONE clearance authority (DOOR-1 item H-2, CLOSED under this record)

The measured refinement the brief asked for turned out to have a second half.
Lifting the cap was necessary and **not sufficient**: `gate_lateral_clearance_m(
obstacle_stop_m)` = 0.593 m understates the gate's demand **by one footprint
radius**, because the gate compares its ring against
`SimObservation.nearest_obstacle_m` / `LidarObstacle.distance_m` and BOTH product
sources publish those footprint-subtracted —
`simulation/mujoco_lidar.py:242` (`signed_clearance = signed_center_distance -
robot_radius_m`) and the Go2 hardware seam `lidar/band.py:375`
(`clearance_m = max(0.0, distance - radius)`, whose docstring says it is
"`SimObservation.nearest_obstacle_m`, the sim's way") — while a grid planner
inflates from the body CENTRE. That is why the verifier's
`map_safety_margin_m = 0.45` probe (0.77 m inflation) recovered only 1 of 8
sampled stalls: the number it needed was 0.885 m, not 0.593 m.

* `authority.py` `ClearanceProfile` gains `gate_range_ring_m` (ring + footprint:
  the ring restated in the frame the grid inflates in) and
  `commissioned_planner_inflation_m` (its lateral demand, cap lifted). Both are
  ADDITIVE; no existing property moved, so `DEFAULT_CLEARANCE_PROFILE` and every
  pre-A2 number are unchanged.
* `reactive_safety.py` gains `planner_gate_ring_m` /
  `person_planner_gate_ring_m`, and the old `planner_inflation_m` keeps its value
  with a docstring that now says plainly not to feed it to a planner.
* `grid_navigator.py:_planner_coupling_ring_m` — the tighter-only `min()` cap is
  GONE for a commissioned ring; `None` (un-commissioned) still resolves to
  `legacy_equivalent_ring_m`, which reproduces the legacy inflation to the digit
  on every grid profile in the tree.
* `pipeline.py` gains `_planner_gate_ring_m()` + `_create_navigator()`:
  production site 1 is commissioned by the caller with **the brake that caller
  itself applies** (`self.collision.obstacle_stop_m`, 0.80 m on the shipped
  navigation config — a STRICTER authority than the runtime gate's 0.65 m, and
  the one arm A actually parked against). Only `type: grid` models receive it;
  `StubNavigator` has no map and a strict signature, and a number it would have
  to ignore is a number silently dropped.
* `search_owner.py` — production site 2 takes `policy.planner_gate_ring_m`.
* **Untouched, as instructed:** `obstacle_stop_m` 0.65, `apply_reactive_safety`,
  `apply_collision_brake`, `finalize_command`. The planner moved UP; no gate
  moved at all. `GridPlannerConfig`'s construction-time refusal ("a planner that
  relaxes the final gate is RED") still holds and is still asserted.

**Fix 3.4, brake→replan.** Both release paths (`_gate_blocked_route_recovery`,
`_unroutable_goal_recovery`) were gated on `_steps_without_progress > 0` — the
distance-to-goal watchdog. Measured on this tree: a semantic goal re-estimated
from a detector that scatters 0.15 m per axis keeps ratcheting that running
minimum down while the body stands still, so over a fully stopped 900-tick arm-A
episode `_steps_gate_blocked` **peaked at 4** against its 60-tick bound, and one
episode spent **778 consecutive ticks** in `grid_recover_scan
status=goal_blocked` without the release ever firing. Both now read one witness
computed once per tick, `_update_body_stillness` → `_body_is_still`: has the
body TRAVELLED (MAP frame, 0.10 m — one planner cell, and an order of magnitude
above the largest single-update MAP correction NAV-CORE measured, 0.029 m). In-place
recovery yaw reads correctly as "still" under it and as "progress" under the old
one. Result: N4 0.45 → 0.88, silent stalls 33 → 6.

### Fix 1 — region/object kind tolerance: at the QUERY, strict-first

Chosen at `ObservationSemanticMap.query`, **not** at the ingress, and the reason
is that the two `kind` fields answer different questions. The GOAL's kind is a
function of the owner's PHRASING — "go to the bed" compiles to `region`/`inside`,
"sit by the bed" to `object`/`next_to`, same place, same map row — so stamping
the ingress from the place-class table fixes the first sentence and breaks the
second. The map keeps saying what it saw; the join stops requiring the same word.

**Strict-first is what makes it additive:** wherever a same-kind candidate
exists the result is byte-identical in membership and order, so the relaxation
can only turn a `not_found` into a candidate and can never re-rank a resolution
that already had one. One consequential follow-on: `_resight_committed_candidate`
also demanded the GOAL's kind, so a region goal committed to an object row could
never be re-sighted and died `target_not_resighted` a metre from the place; it
now asks for the COMMITTED candidate's kind (`mission.metadata["candidate_kind"]`,
falling back to the goal's kind for frozen bundles).

### Fix 2 — off-oracle arrival: metric band + fresh detection, never covariance

`_semantic_arrival_verified` gains one branch, reached only where the oracle's
evidence is missing: `_arrival_target_is_off_oracle` is POSITIVE about
provenance (`metadata["semantic_source"] == "learned_map"` or
`source == "online_map"`) **and** requires no polygon and no
`associated_lidar_ids`. Provenance rather than absent fields is load-bearing —
the sim's own camera fixtures ship an object with neither, and answering their
`near` band from a metric distance relaxed a live oracle check (caught by
`test_near_object_arrival_requires_vicinity_and_safe_support_region`, which
stands one pose too far down the sidewalk and must refuse).

The claim then needs BOTH halves: a re-sighting of the goal class in THIS frame
(`_resight_committed_candidate`, unconditional) and the body inside the band the
mission itself committed to. The band's centre is the tracker's fused anchor,
not the single box this frame produced — a detector with 0.212 m radial RMS
cannot also be the ruler. Everything else on the path is unchanged and still
refuses: pose health, perception freshness, terminal-environment clearance, the
committed `GoalRegion` containment (kept for every target, oracle or not, so
`outside_arrival_region` stays a typed non-arrival rather than becoming a claim)
and the evidence gate. **No covariance and no probability threshold may verify
anything here — they may only refuse** (NAV-CORE R3, pinned).

## Re-freeze table — every frozen number that moved, with cause

Cause for all rows: *the planner now agrees with the commissioned gate, in the
gate's own range convention* (DOOR-1 item H-2, closed by integrator delegation).

| # | subject | old | new |
|---|---|---|---|
| 1 | product: pipeline planner (`from_config`) `gate_clearance_m` / `inflation_radius_m` | 0.460141 / 0.420000 | **1.120000 / 1.022296** |
| 2 | product: `SearchOwnerController` planner, SHIPPED policy | 0.460141 / 0.420000 | **0.970000 / 0.885381** |
| 3 | product: `SearchOwnerController` planner, PROTOTYPE policy (0.45 m ring) | 0.450000 / 0.420000 | **0.770000 / 0.702828** |
| 4 | product: `registry.create(..., map_gate_clearance_m=0.45)` | 0.450000 / 0.420000 | **0.770000 / 0.702828** |
| 5 | `tests/test_door1_doorway.py::test_the_grid_navigator_planner_is_never_built_with_none` | asserted the commissioned ring passed through unchanged | PORTED — asserts `gate_range_ring_m` / `commissioned_planner_inflation_m`; the un-commissioned arm is asserted UNCHANGED |
| 6 | `tests/test_door1_doorway.py::test_the_owner_search_planner_takes_the_runtimes_own_commissioned_ring` | `== PROTOTYPE_RING_M` | PORTED — `== policy.planner_gate_ring_m` |
| 7 | `tests/test_door1_doorway.py::test_the_owner_search_planner_keeps_its_legacy_inflation_when_shipped` | pinned the legacy inflation (the H-2 deferral) | **REPLACED** by `..._agrees_with_the_gate_it_holds`, which records rows 2–3 |
| 8 | `tests/test_navcore_probe.py::test_the_learned_map_cannot_answer_a_region_class_goal` | asserted the defect stands | **REPLACED** by `test_the_corpus_asks_both_kinds_of_goal_and_the_map_still_answers` (both premises kept; the fix's own pin moves to `test_a2_navglue.py`) |
| 9 | `research/20260824/nav-core/results/{corpus,refuters,stall_mechanism}.json` | the pre-A2 evidence | re-run in place; **originals preserved** as `*_pre_a2.json` beside them |

**Did NOT move, checked explicitly:** every un-commissioned grid profile's
inflation (9 profiles walked through the product constructor, exact equality,
including `grid_clearance.yaml`'s 0.35 m); `DEFAULT_CLEARANCE_PROFILE`; every
existing `ClearanceProfile` property; the literal-drift allowlist (no retired
family literal added anywhere); `card_markers` (no `# ---- CARD` marker added);
`long_function_count`.

### One moved row NOT re-pinned — a STOP, not a decision

`tests/test_barn_sensor_faithful.py::test_cached_world0_matches_live_causal_stall_signature_when_available`
is **RED**: the first published action's second component went **0.09 → 0.0**.
Diagnosis, precisely: `configs/navigation/experiments/barn_grid_v1.yaml` carries
`safety.stop_distance_m: 0.8`, so BARN's reference arm now commissions its
planner at 1.0223 m of inflation, which BARN corridors do not admit. **But the
BARN adapter does not share the product's range convention** —
`evals/external/parcel_barn_adapter.py:151,181` publishes RAW cluster ranges as
`nearest_obstacle_m`, where `mujoco_lidar` and the Go2 band seam publish
footprint-subtracted clearance. Under BARN's convention the agreeing inflation is
0.730 m, not 1.022 m: this card's number is 0.29 m too large *there and only
there*.

I did not re-pin the expectation (asserting a stall as correct is not a
re-freeze) and I did not change the BARN adapter (an eval-only path for a
foreign robot, and moving its brake would move more BARN rows than it fixes).
Handed up: **the clearance convention belongs to the observation SOURCE and must
be stamped by it** — which is card A4's stamped evidence header on
`NavigationSnapshotV2`. Related: `authority.CLEARANCE_CONVENTION` currently
declares `"base_center_to_obstacle_surface"`, and both product sources
contradict it; that string is stale, not the code.

## Suites — green through `~/.cache/parcel-guard/pytest_guard.sh --label a2-navglue`

| suite | result |
|---|---|
| `test_a2_navglue.py` (new, this card's pins) | 12 passed |
| `test_navcore_probe.py` (ported) | 4 passed |
| `test_dec0_debt_ratchet.py` + `test_decig2_import_ratchet.py` | 44 passed (with `test_pose_authority_archon`, `test_import_order_no_cycle`) |
| `test_navigation.py`, `test_grid_planner.py`, `test_grid_navigator.py`, `test_door1_doorway.py`, `test_p1e_social_zone_is_config.py` | in the 346-test combined run below |
| `test_value_directed_search.py`, `test_c3_cutover.py`, `test_rm2_*`, `test_rm3_*`, `test_unroutable_goal_release.py` | idem |
| **combined required set** | **346 passed** |
| `test_authority_no_literal_drift.py` (`-m ""`, it is nightly-marked) | 28 passed |
| broad sweep `-k "nav or route or approach or arrival or clearance or planner or semantic or grounder"` | 1209 passed, 8 skipped, 1 xfailed |
| barn / embodied-plan / habitat sweep | 650 passed, **1 failed** (the STOP above) |
| `test_arrival_etiquette_pipeline`, `test_ve_detection_lock_on`, `test_superlative_directives`, `test_portal_world`, `test_semantic_navigation_regressions`, `test_follow_bench_v1`, `test_dynamic_layer`, `test_perception_abstention` | 226 passed, 5 skipped |
| `test_voice_nav_e2e.py` (`PARCEL_MEMORY_PATH=:memory:`, R27) | 15 passed, 1 xfailed, **2 failed** — attributed below |

### The two `test_voice_nav_e2e.py` reds, attributed by in-process bisect

Bisected with a scratch pytest plugin that disables A2's fixes one at a time in
process (no file in the tree edited, nothing committed):

| test | A2 fully disabled | site 1 at the 0.65 m reactive ring | shipped (0.80 m brake) | verdict |
|---|---|---|---|---|
| `test_go_to_the_lamppost_grounds_plans_and_arrives` | **FAIL** | FAIL | FAIL | **PRE-EXISTING on this working tree — not A2.** Fails with all four fixes disabled (`fix1,fix2,fix3,fix34`). Reason `semantic_arrival_verification_failed`. Note this tree also carries several peers' in-flight edits. |
| `test_sit_next_to_the_lamppost_settles_beside_it_in_a_sit` | pass | **pass** | **FAIL** (`semantic_target_unreachable`) | **A2, and the cost of fix 3's magnitude.** |

The second one is the honest price of the fix and the frontier is now measured:
**the demo city admits a 0.885 m planner inflation and does not admit 1.022 m.**
The deeper item behind it, handed up rather than tuned away:
`GridPlannerConfig.inflation_radius_m` is ISOTROPIC and non-traversable, while
the gate it is being made to agree with is DIRECTIONAL (a ±1.15 rad cone).
`gate_lateral_clearance_m` is the correct worst-case bound — a straight corridor
travelled along its centreline — so applying it isotropically forbids routes the
gate would in fact allow. Pre-A2 the planner was under-conservative (0.42 m) and
NAV-CORE priced that in stalls; post-A2 it is worst-case-correct and this test
prices THAT. The middle is a directional cost layer rather than a wider
inflation, which is design work, not a number.

### Sensitivity (labelled diagnostic, run AFTER the decision, output restored)

The same corpus with site 1 commissioned from the reactive gate's 0.65 m ring
(0.885 m inflation — the city-compatible option above) instead of the pipeline's
own 0.80 m brake:

| row | shipped (0.80 m brake) | sensitivity (0.65 m ring) |
|---|---|---|
| arm A N1 | **0.10** | 0.05 |
| arm A N4 | **0.88** | 0.83 |
| arm A silent stalls | **6** | 9 |
| arm A `not_found` | 27 | 33 |
| arm B (all rows) | unchanged | unchanged |

So the DECISION is not sensitive to that choice — the shipped configuration is
the better of the two on both bars, and both are far from 0.80. The restored
`results/corpus.json` is the pre-registered run (N1 0.10, N4 0.88, 223.4 s).

**Known-red, NOT mine — `test_dynamic_costs.py::test_cost_field_vectorization_performance`.**
The R26 perf pin measures 3.31 ms against a 2 ms budget. `dynamic_layer.py` is
untouched by this card (`git diff --stat`), and the same benchmark run standalone
with no pipeline import at all measures 2.47–2.81 ms on a warm loop; the host
runs the `powersave` governor, which is exactly the attribution the test's own
docstring gives ("a failure here is very likely your machine, not your change").
The rest of `test_dynamic_costs.py` passes.

**Ruff:** zero new fingerprints (the one new fingerprint in the tree,
`research/20260823/search-before-refuse/runtime_probe.py::F401`, is in a file
this card never opened). `ruff format` is not part of this repo's gate and the
tree is not format-clean at HEAD.

## Undone, and why

1. **`configs/navigation/models/grid.yaml` was NOT commissioned.** It would give
   arm B (and every bare `registry.create` caller) the fix, but `grid_v1` is
   consumed by the BARN bundles, the follow-bench, nav_instruct and ~28 test
   files; that re-freeze is larger than this card can re-run responsibly, and
   the STOP row above shows why (convention divergence). Commissioning travels
   through the two PRODUCTION owners instead — the pipeline and `search_owner` —
   which is what the brief named as the two sites.
2. **The `near` stand-off family was not re-derived.** It is what puts N1′ at
   0.00 and produces the four N2 rows. Moving it means moving
   `StandOffEnvelope` / `safe_approach_pose` / `minimum_vicinity_radius_m`,
   i.e. every approach pose in the tree, and it is a milestone-sized decision
   about what "arrived at the desk" means — owner/integrator input, not an
   executor's.
3. **6 residual arm-A silent stalls.** Five are `place_bed` episodes cycling the
   search ladder inside the 900-tick budget without exhausting it (the mission is
   still working, just slower than the harness's clock); one is the terminal
   verification loop. Reducing them means budget work in the ladder, which the
   SIMPLIFY decision makes moot for M1.
4. **Arm B's N4 is structurally 0** in this harness: `arms.ArmB` never reads
   `mission.status`/`resolution_state`, so no product-side typed failure can
   reach that column. Not a product property; noted so nobody reads 0.00 as a
   regression.
5. **The R26 perf pin** was not re-derived (see above) — it is R26_STATUS §9's
   own open risk 1 and not this card's to re-pin.
6. **The isotropic-vs-directional inflation item** (see the e2e section) was
   measured and handed up, not resolved. It is the real successor to DOOR-1 H-2
   and it belongs with A4's observation spine, where the clearance convention
   gets stamped by its source.
7. **Nothing committed.** `git` was read-only throughout.
