# search-reground — status (task_2, 2026-08-09)

Card: the audit's #1 blocker — "SEARCH is the bar's first verb and it fails."
A bench 3.9 m from spawn is unfindable via "go to the bench"/"wait by the bench"
when it starts behind the robot, while a headless probe proves the semantic
channel emits `bench_1` whenever faced. Owner lane: `instructnav_recovery.py`,
the scan/re-ground/frontier block of `pipeline.py`, `instructnav/**` (new pure
module), `evals/nav_instruct/**` (append/new only), new test files. Did NOT
touch approach.py / agent.py / runtime.py / test_closed_intent_product_path.py /
evals/companion_nav/ / test_voice_nav_e2e.py (concurrent Opus executor's).

## 1. Root cause — tick-level, live-verified

Probe: `HeadlessCityWorld` + real `DirectiveNavigator`, episode
`nav-object_relative-B-09` ("wait by the bench", start `(-0.05, 0.03, yaw=-1.57)`
facing away; bench_1 at `(-2.5, 3.045)`, 3.9 m behind). The conversion to a
*commit* was never the problem — the commit happens and is then torn down:

| tick | event |
|---|---|
| t000–t014 | scan rotating in place, bench not in frustum, `grounding=UNSEEN` |
| t015 | bench enters the 70°/12 m frustum (`conf=0.98`, `reachable=True`, d=3.9); `grounding=RESOLVED`; `search.observe` → `seen{bench_1:1}` |
| t016 | `seen{bench_1:2}` reaches `required_observations` → `_commit_semantic_candidate(bench_1, RESOLVED)` |
| t016 | `safe_approach_pose(near, bench_1)` returns **None** → `_release_unreachable_candidate("bench_1")` → bench_1 added to per-mission `_unreachable_candidates` |
| t017+ | `_ExcludingSemanticMap` now hides bench_1 from **every** frustum/memory query — the bench is in view repeatedly but returns empty; robot spins out scan(80)+frontier(300) → `semantic_target_not_found` ("couldn't find a bench") |

Confirmed: bench_1 appears in the frustum on exactly 2 ticks, then is filtered
out forever (`frustum=[-]` for the remaining ~130 ticks while the robot sweeps
right past it).

**Why `safe_approach_pose(near)` returns None (the real mechanism).** For the
`near` relation the solver (`approach._safe_near_object_point`) places 32 stand
poses on a ring of radius `stand_off = 1.954 m` (driven by the bench's own
`radius_m = 0.734`) and requires each to lie **inside the object's
`support_polygon`** — the sidewalk it sits on, a 16 m × **2 m** strip
(`y∈[2.20, 4.20]`) flanked by `lamp_post_1` (~2.7 m E) and `tree_1` (~2.5 m W).
Instrumented at 5 robot poses (d = 0.98–3.9 m): `usable = 0` at **every** pose —
26/32 samples fall off the 2 m strip (`support_fail`), the ~6 that stay on it
land inside the flanking obstacles' clearance (`occ_fail`). The ring geometry is
robot-pose-independent, so the solver returns None from *anywhere*; moving
closer cannot help. Meanwhile the directive's own success test — the K0 `near`
band, `[r+0.4, r+1.5] = [1.134, 2.234] m`, **distance-only, no sidewalk
constraint** — has **1880 collision-clear points** (best due-S of the bench,
1.65 m clearance). So the arrival the mission is scored against is reachable;
only the support-gated *planner* pose is not. The release ladder mistook
"no support-surface pose" for "instance unreachable" and banished the target.

**Second defect (flickering confirmation).** Episode `nav-object_relative-B-05`
(start yaw 0.0): the bench enters on the frustum's *trailing edge*
(rel. bearing −68°) for a single tick. The multi-view confirmation rotated at a
fixed `+yaw_rate` — away from the target — pushing it back out before the 2nd
sighting, so `seen` stuck at 1, `required_observations` never reached, and the
scan spun out without ever committing.

## 2. Fix — Sol pure module + recovery-loop wiring (no approach.py edits)

**Sol lane (new pure module, frozen contract):**
`src/parcel_robot/instructnav/near_arrival.py :: near_band_fallback_point`.
Given the object centre, the K0 vicinity band `[inner, outer]`, the robot xy,
observed obstacle surfaces, and a clearance, it returns the collision-clear
point at the band **mid-radius** on the bearing closest to "object → robot"
(shortest, most natural approach), or `None` if every bearing is boxed in.
Pure, deterministic, no navigation imports, no globals. 6 unit tests pin the
contract.

**Recovery-loop wiring (pipeline.py, my lane):**
- `_commit_semantic_candidate`: on a `None` approach pose for a `near`/`next_to`
  candidate that is frustum-visible + reachable, try `_fallback_near_arrival_pose`
  **before** releasing. The fallback derives the pose from the SAME K0 band
  `_inside_arrival_goal_region` verifies against (`[minimum_vicinity_radius_m,
  vicinity_radius_m]` from the candidate's own metadata), keeps the full
  footprint-to-surface clearance (`ROBOT_FOOTPRINT_RADIUS_M + obstacle_stop_m`)
  from every observed non-target surface, and commits it. If it too finds no
  clear pose, the existing unreachable-release stands (honest fail).
- `_non_target_obstacle_points`: gathers observed LiDAR surfaces with the
  target's own body removed (radius + association slack) so the object never
  blocks its own band. No gate relaxed.
- Confirmation branch (`_step_semantic_resolution`, RESOLVED path): while
  confirming, steer the rotation TOWARD the mapped target (capped at the search
  yaw-rate) so a trailing-edge target stays in the frustum for the 2nd sighting.
  Gated to **non-interchangeable** goals — region/"nearest" sweeps are the
  deliberate look-around ranking and keep their existing behaviour untouched.

**Equality / safety.** The fallback runs only on the branch that previously
released unconditionally, so every case that already committed is byte-identical
(no currently-passing episode changes). The steer is gated off for
interchangeable goals, so region multiview is unchanged. Collision gate,
reactive safety, and terminal verification are untouched — no teleport, no
oracle. Honest not-found is preserved: an absent target never enters the frustum
→ no candidate → no commit → no fallback (Tier E still fails with no false
arrival; unit-tested).

## 3. Gate — evals/nav_instruct v3 minival (candidate mode)

Frozen episode payloads untouched: v2 digest `a17c04db…`, v3 digest
`919a0fea…` — `tests/test_nav_instruct_episodes_v3.py` + `_v2.py` **32 passed**.
No `--freeze`, no ledger edits, no new episode versions.

**Before → after, overall + per tier** (25-episode minival, `_fallback_near_arrival_pose` on/off A/B):

| budget | overall SR | Tier A | Tier B | Tier C | Tier D | Tier E |
|---|---|---|---|---|---|---|
| 200 (frozen) | 0.12 → 0.12 | 2/5 | 0/5→0/5 | 0/5 | 1/5 | 0/5 |
| 400 | 0.28 → **0.32** | 4/5 | 2/5 → **3/5** | 0/5 | 1/5 | 0/5 |
| 600 | — → 0.52 | — | — | 0/5 | — | — |

**Per-family the fix moves (object_relative, the bench family):**
- `object_relative|B` "wait by the bench" (**near**): before = `semantic_target_not_found` / UNSEEN, bench never committed (banished). After = grounds `RESOLVED`, commits via `near_band_fallback`, navigates, ends **inside the K0 goal band**; scores **success at a 400-step budget**. At the frozen 200-step budget it is `navigation_step_limit_inside_goal` — inside the goal but truncated by the ~7 s opening full-turn scan + slow terminal approach (the seamless-pacing card's domain, not this one).
- `object_relative|A` "sit next to the bench" (next_to): PASS before and after — `safe_approach_pose` succeeds there, the fallback is dormant (equality preserved).

**Budget:** near-bench converts to a grounded arrival at a **400-step (40 s)
budget**. Reported honestly: at the frozen 200-step budget the arrival is
grounded-and-inside-goal but step-limited.

**Tier C attribution (search-loop vs. routing — the card asks to separate).**
Tier C is NOT converted, and it is not a search-loop failure. Instrumented all
Tier C bench/lamppost episodes (near, next_to, towards): the target is visible
from the far Tier C start and **commits at t=1**, but the robot then
**`max_moved = 0.0 m` for the whole run** — A* returns no route from the far
Tier C start poses (fails even for a 2 m `towards` waypoint that never touches
the fallback), hitting `semantic_target_unreachable`. Fix ON and OFF give
**identical** Tier C outcomes. This is a routing/planner defect (the audit's
planner-vs-gate / safety-margin / seamless-pacing gaps), not the SearchEntity/
ScanBehavior re-ground loop. The search loop now grounds and commits the visible
target and the body *tries* to move; the block is downstream of this card.

**Live e2e probe** (new file `tests/test_search_reground_bench.py`, owned here —
NOT `test_voice_nav_e2e.py`): 12 tests, all green. `go to`/`wait by` the bench
from a bench-not-in-frustum start grounds, is not banished, and reaches the K0
goal band with `score.success`; the flickering B-05 case reaches two sightings
and commits; the absent-target Tier E case still fails honestly with no false
arrival; 6 unit tests pin the pure-module contract.

## 4. Verify

- **Full default suite** (`pytest -m 'not slow'`): **2933 passed, 7 failed,
  2 skipped**. All 7 failures are outside this card's files and none reference
  any symbol this card touched (verified by grep for `near_band_fallback` /
  `near_arrival` / `_fallback_near` / `_commit_semantic` /
  `_step_semantic_resolution` / `approach_pose_source` — zero hits in the 7
  files). They belong to the concurrent executor's emotion/gesture/social-affect
  + agent/runtime sprint (verified live in the working tree: modified `agent.py`,
  `runtime.py`, `prompts/*`, `configs/skills/*`, and new
  `test_emotion_gesture_library.py` / gesture trajectories):
  - `test_embodied_plan_eval.py` (2) — `physical_skill_episode_count` / gesture
    aggregate changed by the new skills (this is the embodied-1250-row movement,
    and it is **theirs, not mine** — this card never touches the embodied eval).
  - `test_conversation_quality_v1.py` (3) — conversation manifest locking (prompt/
    agent/runtime edits).
  - `test_runtime.py::test_social_affect_action_runs_from_idle_without_model` (1).
  - `test_dynamic_layer.py::test_the_collision_gate_behaviour_is_untouched_on_this_branch`
    (1) — an AST-vs-git-HEAD `CollisionPolicy` field baseline (`person_slow_m`);
    this card touches no collision/gate code.
- **This card's domain: 242 passed, 0 failed** (search_reground_bench, navigation,
  headless_city_tasks, k4_opus_wiring, unroutable_goal_release,
  arrival_authority_differential, owner_and_settle_plans, intelligence,
  nav_instruct_episodes_v2/v3, authority_no_literal_drift).
- **Ruff:** clean on all owned files.
- **Retired-literal drift ratchet** green — the two new `0.35` literals were
  removed (yaw-rate reads `self.search.yaw_rate`; arrival-radius clamp max moved
  off the retired 0.32/0.35 family to 0.5).
- **Frozen artifacts:** v2 digest `a17c04db…` + v3 digest `919a0fea…`
  byte-identical (32 passed); no frozen minival digest moved; ledger untouched;
  no `--freeze` run.

## 5. Non-claims

- Does **not** fix Tier C arrival — that is A*-routing-from-far-start
  (`max_moved=0.0`, identical fix on/off), a separate card.
- Does **not** touch the near-band terminal verification — the mission still
  reports `semantic_arrival_verification_failed` at ~1 cm on some benches; the K0
  scorer counts the arrival. The inset fix is the near-band-inset card (Opus).
- Does **not** improve the `object_goal|B` "walk towards the streetlight" score
  (now arrives but scored fail on a terminal *noun* mismatch — the siglip card).
- Does **not** touch frozen episode payloads, the collision gate, reactive
  safety, or introduce any new YAML/knob.

## 6. Files touched

- NEW `src/parcel_robot/instructnav/near_arrival.py` (Sol pure module + contract)
- `src/parcel_robot/instructnav/__init__.py` (export `near_band_fallback_point`, `DEFAULT_BEARING_SAMPLES`)
- `src/parcel_robot/navigation/pipeline.py` (soft import; `_commit_semantic_candidate` fallback branch; `_fallback_near_arrival_pose` + `_non_target_obstacle_points`; confirmation steer)
- NEW `tests/test_search_reground_bench.py` (6 unit + 6 live e2e)
