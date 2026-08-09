# DEEP Design D3 — Social City Companion (N11 near-miss fix)

**Date:** 2026-08-07
**Author role:** Opus stand-in (HIGH-STAKES multi-hour design)
**Status:** engineer-ready deep design — not an implementation commit
**v0 (shallow, archive only):** [`../DESIGN_D3_SOCIAL_CITY.md`](../DESIGN_D3_SOCIAL_CITY.md)
**Depth bar:** [`README.md`](README.md) — ≥3 passes, ≥20 file:line cites, ≥1,200 lines,
full worked scenario, safety argument, complete pseudocode, UNVERIFIED + acceptance matrix
**Safety status:** Not cleared for unsupervised physical motion.

**Primary inputs (re-derived, not copied):**
- [`../../research/N3_SOCIAL_DYNAMIC.md`](../../research/N3_SOCIAL_DYNAMIC.md)
- [`../../research/N8_CITY_OUTDOOR.md`](../../research/N8_CITY_OUTDOOR.md)
- [`../../research/N4_PERCEPTION_LOCALIZATION.md`](../../research/N4_PERCEPTION_LOCALIZATION.md)
- [`../../research/N6_EXECUTIVE_BEHAVIOR.md`](../../research/N6_EXECUTIVE_BEHAVIOR.md)
- [`../../../../20260805/task_2/OPUS_N11_STATUS.md`](../../../../20260805/task_2/OPUS_N11_STATUS.md)
- Full source: `traffic_aware.py`, `approach.py`, `pipeline.py` (arrival / person_stop /
  yield), `follow.py`, `maps/crossing.py`, `tests/test_voice_nav_e2e.py`,
  `tests/test_traffic_aware.py`

**Sibling designs:** D1 classical fail-closed companion; D2 shadow proposers

---

## 0. Binding thesis (one paragraph)

Parcel’s social-city competence is a **goal-commitment + arrival-definition +
formation-shape** problem that may be addressed only after D1 repairs and
verifies the hard-stop substrate. The historical N11 xfail records a ~0.33 m
sidewalk miss after ~240 s under scripted traffic; this audit did not rerun it,
so it is a hypothesis-forming near-miss, not current proof. D3 therefore (1) mid-mission
re-ranks approach poses while dwelling near the goal under `person_stop`,
(2) replaces the intentional `return False` for `terminal_relation == "inside"`
with dwell-verified `point_in_polygon_with_clearance`, (3) keeps yield-advance
(`RampMemory` + final-metre creep) **seed-only**, (4) routes owner formation
goals through the common planner instead of proportional twist, and (5) treats
OSM / Overture / GNSS / CityWalker as TTL advisory nominees under an
authenticated, authorized owner/control-channel crossing decision bound to the
task revision and event TTL; transcript text alone is never authority. Soft social cost never opens
a gate; advisory maps never set free space; models never emit Sport velocity.

---

## 0.1 Pass ledger (binding — no early exit)

| Pass | Purpose | Exit criterion |
| --- | --- | --- |
| **Pass 1** | Reconstruct e2e geometry of the N11 near-miss from measured poses, polygons, stop envelopes, and commit-time ranking | Closed geometric narrative with distances, y-bands, and authority ownership |
| **Pass 2** | Complete implementable algorithms for re-rank, dwell-inside, seed-only yield, formation→planner, OSM advisory | Pseudocode that an engineer can type; every motion/lifecycle change covered |
| **Pass 3** | Adversarial self-critique: what could falsify D3, interfere with hard stops, launder near-misses, or thrash | Rewritten weak sections; non-interference proof tightened |
| **Pass 4** | Gap expansion under depth bar: more tick branches, ABI tables, falsifiers, test matrix density | ≥1,200 lines; ≥20 cites; UNVERIFIED + acceptance matrix complete |

This document records all four passes explicitly. Pass 4 is mandatory if Pass 3
leaves the document under the depth bar or leaves any algorithm sketched.

---

## 0.2 Authority classes (freeze these before reading algorithms)

```text
HARD (metric / motion veto):
  LiDAR/footprint collision brake, person_stop, TTC, all-ray shield,
  curb-stop, MAP/ODOM health → HOLD, arrival witnesses after verifying

SOFT (rank / pace / comfort):
  traffic_occupancy_cost, proxemic Gaussians (optional veto when tracks),
  preferred follow annulus/angle, clear-window feasibility filter

ADVISORY (nominate only, TTL + source + confidence):
  OSM footway graph SE2Goal, Overture POI, GNSS GEO, CityWalker XY,
  route-memory replay, D2 NavProposalV1 shadows

NEVER:
  advisory → occupancy free cell
  model / CityWalker → Sport / HAL velocity
  autonomous road entry from OSM edge, CityWalker, or learned prior
  seed / creep emission while person_stop or collision-brake active
  weakening person_stop_m / TTC to "make progress" on N11
```

---

# PASS 1 — Reconstruct end-to-end geometry

## P1.1 What the product path does today (static vs traffic)

### Static sidewalk (green gate)

`test_go_to_the_sidewalk_grounds_plans_and_arrives` enters at
`RobotRuntime.handle_text` against MuJoCo city with `static_city=True`
(pedestrian agents removed). Scoring requires **both** system task success
and independent K0 `GoalRegion.contains` — claim without predicate (or vice
versa) is failure (`tests/test_voice_nav_e2e.py:14-17`,
`tests/test_voice_nav_e2e.py:359-376`).

Product chain:

```text
transcript "go to the sidewalk"
  → closed intent / local PlanSketch
  → PlanIR admission (NavigateTo, terminal_relation=inside)
  → TaskExecutive dispatch
  → DirectiveNavigator resolution ladder
  → safe_approach_pose (empty tracks ⇒ static nearest inset)
  → grid_v1 A* + MidLevelCommand
  → apply_collision_brake post-shaper
  → geometric arrival OR (non-inside) goal_region membership
  → verifying: relation + settle witnesses
  → succeeded
```

Empty tracks keep ranking byte-identical to static ordering — the ladder rule
pinned in pure tests (`tests/test_traffic_aware.py:321-331`) and documented in
`rank_approach_candidates` (`src/parcel_robot/navigation/traffic_aware.py:309-312`).

### Dynamic sidewalk (xfail — the N11 residual)

`test_go_to_the_sidewalk_with_pedestrian_traffic` uses `live_dynamic`
(`static_city=False`). Post-N11-wiring measurement (2026-08-06, n=2, both fail):

| Quantity | Measured value | Source |
| --- | --- | --- |
| Start pose | ≈ (0.00, 0.00) | e2e xfail reason |
| End pose | ≈ (−0.28, +2.07) | `tests/test_voice_nav_e2e.py:421` |
| Travel | ≈ 2.09 m | same |
| Shortfall | ≈ 0.33 m outside GoalRegion | same |
| Failure mode | `step_timeout` @ ~240 s NavigateTo budget | same |
| Pedestrian strip | y ≈ 2.85–3.55 | `OPUS_N11_STATUS.md` |
| Commit quieter pose | ~ y = 2.64 (south edge of free set) | `OPUS_N11_STATUS.md` |
| Semantic polygon | y ≥ ~2.2 (north sidewalk) | N3 / status |
| K0 eval region | y ≥ ~2.4 | N3 / status |

The xfail reason itself records that N11 wiring moved the case from "stuck /
traffic-blind" to "near-miss on the clock" (`tests/test_voice_nav_e2e.py:413-429`).
That distinction is the entire design hinge: placement and yield-advance are
live and attributable; commitment and arrival definition are not.

## P1.2 Coordinate frame and region geometry (city_block sidewalk)

Work in MAP/ENU scene metres (sim). North sidewalk strip (the instruction
target after region-instance selection by boundary distance):

```text
                  y ↑
                    │
   pedestrians ─────┼── y≈3.55 ─────────────────────────────
   stream band      │
                    ├── y≈2.85  (occupied corridor, CV paths)
                    │
   quieter edge ────┼── y≈2.64  ← commit-time ranked pose
   (becomes hot)    │
   polygon edge ────┼── y≈2.20  ← semantic "inside" boundary
   K0 eval edge ────┼── y≈2.40  ← GoalRegion.contains for score
                    │
   end pose ────────┼── y≈2.07  ← robot dies here under person_stop
                    │
   origin ──────────┼── y=0.00
                    └──────────────────────────→ x
                         end x ≈ −0.28
```

**Critical geometric facts:**

1. The robot **never enters** the semantic polygon (y≥2.2) in the failing
   runs. End y≈2.07 is **0.13 m short of the polygon** and **0.33 m short of
   the K0 eval region** (y≥2.4). Two different "outside" predicates both fail;
   D3 must not pick the easier one as a laundering path.

2. Commit-time ranking correctly prefers ~y=2.64 over stream-center poses
   because `traffic_occupancy_cost` integrates CV proximity over a 3.0 s
   horizon (`traffic_aware.py:200-283`). That pose is quieter **at commit**,
   not quieter **240 s later**.

3. The person-stop envelope is a hard disc around the robot. When an agent
   sweeps within `person_stop_m`, `apply_collision_brake` returns exact
   `(0, 0, "person_stop")` (`collision.py:105-107`). The pipeline preserves
   that zero even if a later shield rewrites the note
   (`pipeline.py:714-717`).

4. Final-metre creep only fires when `collision_note == "clear"`, remaining
   distance ≤ `FINAL_APPROACH_BAND_M = 1.0`, and tracker CV predicts clear
   for `FINAL_APPROACH_HORIZON_S = 1.5` (`pipeline.py:789-861`). It floors
   the seed to `FINAL_APPROACH_CREEP_MPS = 0.12`. At 0.12 m/s, closing the
   last 0.33 m needs ≈ 2.75 s of continuous clear. Measured clear windows
   under the stream are shorter / more contested — hence timeout.

5. `_inside_arrival_goal_region` **intentionally returns False** for
   `terminal_relation == "inside"` so a raw edge graze cannot succeed
   (`pipeline.py:2535-2538`). That means even if the robot somehow sat at
   y=2.25 (inside polygon, outside K0), today’s product path would still
   require geometric approach-pose arrival — which person_stop blocks.

## P1.3 Commit-time approach geometry (what `safe_approach_pose` builds)

For `terminal_relation == "inside"` with a polygon, approach:

1. Resolves footprint / terminal / obstacle clearances; approach inset is
   `max(footprint_clearance_m, terminal_clearance + arrival_radius)`
   (`approach.py:70-92`).
2. Filters LiDAR blocked points that coincide with dynamic tracks so ranking
   sees the full free set (`approach.py:46-50`).
3. Samples polygon interior on a grid with spacing
   `max(0.25, extent/40)` and keeps points that are inside + have clearance +
   are clear of obstacles along the robot→point segment
   (`approach.py:239-286`).
4. Ranks with `rank_approach_candidates`, static cost = distance from robot,
   call-site `traffic_weight` bumped to **2.0** when tracks present and the
   caller left the default 1.0 (`approach.py:59-64`,
   `approach.py:372-382`).
5. Optionally walks a proxemic veto over the ranked list when tracks are
   non-empty; empty tracks skip veto entirely for ladder identity
   (`approach.py:385-388`). **Important:** `proxemic_approach.reject_cost`
   as sole selector remains parked — fail-closed `None` would break empty
   tracks (OPUS_N11_STATUS; approach docstring at `approach.py:362-369`).

Committed pose lands in `mission.goal` with metadata
`approach_static_cost` / `approach_traffic_cost` / `approach_total_cost`
(`pipeline.py:1314-1354`, `approach.py:450-457` via `_record_approach_costs`).

**Pass-1 finding:** commitment is a **point** with a frozen cost snapshot.
Over a 240 s window the CV world rotates; the cost snapshot does not.
Re-rank is therefore not optional polish — it is the missing state update.

## P1.4 Per-tick control geometry while `person_stop` is active

On each `DirectiveNavigator.step` with a mission goal
(`pipeline.py:620-718`):

```text
1. pose-lost HOLD?
2. reanchor landmark goal (GraphNav offset — does not change commitment class)
3. if verifying → terminal verification
4. navigator.act → MidLevelCommand (may propose non-zero vx toward goal)
5. geometrically_arrived OR inside_arrival? → verifying
6. progress watchdog (person_stop freezes stall — see below)
7. apply_collision_brake → may zero vx/vy with cnote=person_stop
8. _update_ramp_memory:
     person_stop → note_stopped; return seed=0.0
     first clear after stop → release → seed_ramp + pending_ramp_seed
     maybe _final_metre_creep (only if clear)
9. if person_gate_stop: return MidLevelCommand(vx=0, vy=0, stop=False)
```

Progress watchdog explicitly does not treat person proximity as a stall
(`pipeline.py:2204-2209`). Yield-advance therefore cannot be accused of
"hiding" a stuck robot from the watchdog — the freeze is intentional and
correct.

**Pass-1 finding:** while `person_stop` holds, the robot is a **stationary
observer** of an occupied corridor. All useful work during those ticks is
**cognitive** (re-evaluate commitment, accumulate inside-dwell if already
inside). Emitting motion would violate hard authority.

## P1.5 Arrival geometry today vs what the residual needs

| Relation | Today’s arrival trigger | Problem under traffic |
| --- | --- | --- |
| `near` / `next_to` / `towards` | `GoalRegion.contains` OR approach-pose tolerance | N13 sibling near-misses; not N11 primary |
| `inside` | **Hard False** in `_inside_arrival_goal_region`; only approach-pose geometric stop | Contested point never clears; region membership unused |

The intentional False exists to prevent false success on a raw edge hit
(`pipeline.py:2535-2538`). That concern is real. The fix is **not** to
delete the guard — it is to replace it with a **stricter** predicate:
polygon membership **with clearance** for a continuous dwell, forbidding
success under any active proximity/TTC/obstacle/person brake and requiring
fresh metric evidence, healthy pose/transforms, an agent-issued exact-zero
stop, and settled feedback.

`point_in_polygon_with_clearance` already exists and matches approach inset
semantics (`approach.py:293-298`). Terminal verification already special-
cases `inside` so street furniture in the region does not permanently fail
environment clear (`pipeline.py:2588-2593`) — D3 must preserve that while
tightening the **entry** into verifying.

## P1.6 Yield-advance geometry (seed-only — already correct shape)

`RampMemory` safety contract is explicit and must not be redesigned
(`traffic_aware.py:29-36`, `traffic_aware.py:403-430`):

| API | Emits velocity? | Role |
| --- | --- | --- |
| `note_running` | no | remember pre-gate vx above floor |
| `note_stopped` | **no** (returns None) | remember stop start |
| `release` | returns **seed** after caller asserts gate open | recovery speed |
| `held_velocity_mps` | telemetry only | never a command |

Wiring (`pipeline.py:733-787`) calls `note_stopped` on `person_stop` and
only `release`s when state is `stopped` and note is no longer person_stop.
Same-tick lift of post-brake `vx` still requires `cnote == "clear"`
(`pipeline.py:685-691`). Final-metre creep repeats the same clear-gate
(`pipeline.py:836-837`).

**Pass-1 finding:** yield-advance is necessary but insufficient for N11
because clear windows are too short to reach the **same** committed point.
Re-rank changes the point; dwell changes the success definition. Creep must
stay bounded.

## P1.7 Follow / formation geometry (N6 adjacency, Week B)

`FollowOwnerController._step_direct` emits proportional twist
(`follow.py:596-658`):

```text
distance_error = hypot(owner - robot) - desired_distance_m
vx = min(max_vx, distance_error * distance_gain)
vyaw = clamp(yaw_error * yaw_gain)
```

Obstacle stop/slow are local to the follow controller — not the same
`grid_v1` + post-brake path NavigateTo uses. Crowds and walls therefore
behave inconsistently across skills. N6 research calls this out as the wrong
shape for persistent follow vs terminating approach.

D3’s formation→planner seam:

```text
OwnerTrackV1 (enrolled) → FormationGoalSampler @ 10–20 Hz
  → FollowFormationGoalV1 {x,y,yaw?,ttl,relation,generation,frame=MAP}
  → mission.goal (short TTL) → grid_v1 → same hard monitors
```

This is **not** on the N11 flip critical path (Week A), but the ABI must be
specified so Week B does not invent a second motion authority.

## P1.8 Crossing / OSM geometry (N8 — advisory only)

`CrossingModePolicy.evaluate` currently hard-blocks road poses without its
crossing bit
(`crossing.py:199-211`), vetoes goals into road keepout
(`crossing.py:213-228`), and at curb stop sets
`allow_crossing_edges=False`, `autonomous_road_entry_blocked=True`,
`reason="curb_stop_awaiting_voice"` (`crossing.py:267-282`). The product
contract must mint that bit only from an authenticated, authorized owner or
control-channel command bound to the current task/revision, event ID,
curb-stop state, and TTL. A recognized phrase/transcript alone is untrusted
input and cannot mint crossing authority.
`CrossingDecision` defaults `autonomous_road_entry_blocked=True`
(`crossing.py:78-85`).

OSM waypoint proposers may emit `SE2Goal` along footway edges; they must
**never** flip `allow_crossing_edges`. D3 makes that ABI-visible and requires
`crossing.py` to replace phrase-only initiation with the bound authorization
contract before product promotion.

## P1.9 Pass-1 geometric verdict (binding)

```text
DEFECT CLASS: temporary commitment + missing region-dwell arrival
NOT DEFECT:   person_stop distance, TTC, RampMemory seed-only shape,
              traffic_aware ranking math, empty-tracks ladder

GEOMETRY THAT MUST CHANGE:
  (a) mission.goal may be rewritten under hysteresis while person_stop
      dwells near the goal with fresh tracks
  (b) inside arrival may fire from polygon+clearance dwell, not only
      approach-pose geometric stop

GEOMETRY THAT MUST NOT CHANGE:
  (c) vx≡0 on person_stop ticks
  (d) no seed/creep on gated ticks
  (e) OSM never grants road entry
  (f) empty tracks ⇒ no re-rank side effects
```

Distance budget for success under D3 (either path):

```text
Path A — re-rank lateral shift:
  committed (x0, 2.64) → new (x1, y1) with lower traffic cost and
  predicted clear_window ≥ remaining / 0.12
  robot advances on clear ticks; may still finish via approach-pose stop

Path B — dwell inside:
  robot crosses y=2.2 with clearance while yielding or clear;
  dwell ≥ 0.75 s continuous → verifying → witnesses
  NOTE: measured end y=2.07 never reaches Path B without Path A or a
  lucky clear window. Path B is the correctness definition; Path A is
  the primary mechanism to make Path B reachable.
```

---

# PASS 2 — Complete algorithms

## P2.0 Module placement and purity

| Symbol | Module | Purity |
| --- | --- | --- |
| `ApproachCommitment` | `traffic_aware.py` (or sibling `approach_commitment.py` imported by it) | frozen dataclass, stdlib |
| `ReRankDecision` | same | frozen dataclass |
| `should_rerank_approach` | same | pure; clocks caller-supplied |
| `select_recommit` | same | pure; reuses `rank_approach_candidates` |
| `InsideDwellState` / `update_inside_dwell` | `approach.py` (polygon-coupled) or `pipeline` helper | pure state machine |
| Wiring | `DirectiveNavigator.step` / `_commit_semantic_candidate` | impure; owns mission |
| Formation sampler | `follow.py` behind flag | produces goals, not twists |
| Crossing authorization | `crossing.py` + tests | bind authorized speaker/channel, task revision, event ID, curb-stop state, and TTL; phrase text alone cannot authorize |

Malformed inputs raise `ValueError` at every public entry (SB-3), matching
`traffic_aware.py:38-42`.

## P2.1 Mid-mission re-rank — complete algorithm

### P2.1.1 Data contracts

```python
from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from parcel_robot.navigation.traffic_aware import (
    RankedCandidate,
    TrackState,
    coerce_tracks,
    rank_approach_candidates,
)


@dataclass(frozen=True)
class ApproachCommitment:
    """Frozen committed approach pose with attributable cost snapshot.

    ``generation`` bumps on every accepted re-commit so telemetry and
    watchdog logic can freeze stall counters on the re-rank tick without
    confusing a goal rewrite for geometric progress.
    """

    x: float
    y: float
    static_cost: float
    traffic_cost: float
    total_cost: float
    committed_at_s: float
    generation: int


@dataclass(frozen=True)
class ReRankDecision:
    should_rerank: bool
    reason: str
    # reason ∈ {
    #   "noop_empty_tracks", "not_yielding", "band", "dwell",
    #   "stale_tracks", "rate_limit", "evaluate",
    #   "no_improvement", "unreachable", "commit",
    # }
    candidate: RankedCandidate | None = None
```

### P2.1.2 Gate: `should_rerank_approach`

```text
FUNCTION should_rerank_approach(
    *,
    now_s: float,
    robot_xy: (float, float),
    commitment: ApproachCommitment,
    tracks: Sequence[TrackState | duck | tuple],
    person_stop_active: bool,
    person_stop_dwell_s: float,
    last_rerank_s: float | None,
    re_rank_band_m: float = 1.75,
    re_rank_min_dwell_s: float = 1.0,
    re_rank_min_interval_s: float = 1.0,
    max_age_s: float = 1.0,
    require_person_stop: bool = True,
) → ReRankDecision:

  VALIDATE finite(now_s, band, dwell, interval, max_age);
       band>0, dwell≥0, interval>0, max_age≥0
  VALIDATE finite robot_xy and commitment.xy

  validated ← coerce_tracks(tracks)
  fresh ← [t in validated if t.age_s ≤ max_age_s]
  IF fresh is empty:
    # Ladder: empty OR all-stale ⇒ identity with static world.
    RETURN ReRankDecision(False, "noop_empty_tracks")

  IF require_person_stop AND NOT person_stop_active:
    RETURN ReRankDecision(False, "not_yielding")

  dist ← hypot(robot_xy − (commitment.x, commitment.y))
  IF dist > re_rank_band_m:
    RETURN ReRankDecision(False, "band")

  IF person_stop_dwell_s < re_rank_min_dwell_s:
    RETURN ReRankDecision(False, "dwell")

  IF last_rerank_s is not None
     AND (now_s − last_rerank_s) < re_rank_min_interval_s:
    RETURN ReRankDecision(False, "rate_limit")

  RETURN ReRankDecision(True, "evaluate")
```

**Why these gates (geometry + safety):**

- **Empty/stale noop:** preserves ladder (`traffic_aware.py:309-312`).
  Re-ranking without tracks would rewrite goals using static costs alone —
  which is a behavior change on the green empty-tracks e2e.
- **Require person_stop (default):** re-rank is a *dwell-time* computation
  while hard-stopped, not a mid-cruise goal flicker. Cruising re-plans
  belong to the planner’s own dynamic layer, not approach commitment.
- **Band 1.75 m:** larger than `FINAL_APPROACH_BAND_M=1.0` so re-rank can
  fire while still in the final-approach family, but not from across the
  city block.
- **Min dwell 1.0 s:** avoid re-ranking on a single flap tick.
- **~1 Hz interval:** GSCL-like social replanning cadence (N3 §3.6); prevents
  CPU thrash on ~1.7k polygon samples (`approach.py:377-381` notes unbounded
  cost).

### P2.1.3 Select: `select_recommit`

```text
FUNCTION select_recommit(
    commitment: ApproachCommitment,
    candidates: Sequence[(float, float)],
    tracks: Sequence,
    *,
    static_cost_fn: Callable[[(float,float)], float],
    traffic_weight: float = 2.0,
    cost_improve_eps: float = 0.15,
    hysteresis_bonus: float = 0.08,
    max_age_s: float = 1.0,
    top_k: int = 64,
    clear_window_filter: Callable[[RankedCandidate], bool] | None = None,
    statically_free: Callable[[(float,float)], bool] | None = None,
) → ReRankDecision:

  ranked ← rank_approach_candidates(
      candidates, tracks,
      static_cost_fn=static_cost_fn,
      traffic_weight=traffic_weight,
      max_age_s=max_age_s,
      top_k=top_k,
  )
  IF ranked empty:
    RETURN ReRankDecision(False, "unreachable")

  ordered ← ranked
  IF clear_window_filter is not None:
    filtered ← [c for c in ranked if clear_window_filter(c)]
    IF filtered: ordered ← filtered

  best ← ordered[0]

  # Sticky commitment: challenger must beat commitment by eps + bonus.
  # Lower total_cost is better.
  threshold ← commitment.total_cost − cost_improve_eps − hysteresis_bonus
  IF best.total_cost ≥ threshold:
    RETURN ReRankDecision(False, "no_improvement", candidate=best)

  IF statically_free is not None AND NOT statically_free((best.x, best.y)):
    RETURN ReRankDecision(False, "unreachable", candidate=best)

  RETURN ReRankDecision(True, "commit", candidate=best)
```

**Do not invent a second cost.** Reuse Sol’s `rank_approach_candidates`
(`traffic_aware.py:286-400`). Hysteresis is applied **after** ranking, as a
commitment stickiness filter — same pattern as soft commitment in
`ReactionArbiter` (N3 risk note).

### P2.1.4 Clear-window feasibility filter (optional Week A+/C)

```text
FUNCTION clear_window_ok(candidate, tracks, robot_xy, *,
                         creep_mps=0.12, horizon_s=1.5,
                         person_stop_m, max_age_s=1.0) → bool:
  remaining ← hypot(candidate.xy − robot_xy)
  need_s ← remaining / max(creep_mps, 1e-3)
  IF need_s > horizon_s:
    # Cannot prove a window this long with current predictor; do not veto —
    # fall back to integral traffic cost only.
    RETURN True
  # Predict whether CV agents enter the stop envelope along the straight
  # segment robot→candidate within need_s. Fail-closed if no tracks after
  # age filter (caller should not be in re-rank). For Week A, prefer the
  # integral cost; enable this filter behind a flag after digest A/B.
  ...
```

Week A ships **without** requiring this filter for the xfail flip. Log
`predicted_clear_window_s` vs `remaining/creep` as diagnostics on every
final-metre tick (already partially present via `final_metre_yield`
metadata at `pipeline.py:850-855`).

### P2.1.5 Wiring into `DirectiveNavigator`

State owned by navigator (alongside existing `_ramp`):

```python
self._approach_commitment: ApproachCommitment | None = None
self._person_stop_dwell_s: float = 0.0
self._person_stop_dwell_clock: float | None = None
self._last_rerank_s: float | None = None
self._inside_dwell = InsideDwellState()
```

On `_commit_semantic_candidate` after `safe_approach_pose` succeeds
(`pipeline.py:1328-1354`):

```text
self._approach_commitment ← ApproachCommitment(
    x=pose.x, y=pose.y,
    static_cost=approach_costs["approach_static_cost"],
    traffic_cost=approach_costs["approach_traffic_cost"],
    total_cost=approach_costs["approach_total_cost"],
    committed_at_s=now_s,
    generation=0,
)
self._inside_dwell.reset()
self._person_stop_dwell_s ← 0
self._last_rerank_s ← None
# DO NOT reset RampMemory here beyond existing mission-change resets
```

On each `step` tick after collision brake note is known, **before** returning
the zero command on person_stop (cognitive work while stopped is allowed):

```text
FUNCTION maybe_rerank_on_tick(observation, cnote, robot_xy, now_s):
  IF mission is None OR semantic_goal is None OR commitment is None:
    RETURN

  # Update dwell clock
  IF cnote == "person_stop":
    IF self._person_stop_dwell_clock is None:
      self._person_stop_dwell_clock ← now_s
    self._person_stop_dwell_s ← now_s − self._person_stop_dwell_clock
  ELSE:
    self._person_stop_dwell_clock ← None
    self._person_stop_dwell_s ← 0.0

  tracks ← tracks_from_payload(extras.dynamic_agents)
           # product path MAY prefer people_tracker→TrackState; sim uses extras

  gate ← should_rerank_approach(
      now_s=now_s, robot_xy=robot_xy, commitment=commitment,
      tracks=tracks,
      person_stop_active=(cnote == "person_stop"),
      person_stop_dwell_s=self._person_stop_dwell_s,
      last_rerank_s=self._last_rerank_s,
  )
  metadata["re_rank_gate_reason"] ← gate.reason

  IF gate.reason != "evaluate":
    RETURN

  self._last_rerank_s ← now_s
  metadata["re_rank_eval_count"] ← metadata.get(...,0) + 1

  candidates ← sample_inside_goal_region(...)  # SAME free set as approach
  decision ← select_recommit(commitment, candidates, tracks, ...)

  IF decision.reason == "commit":
    old ← (commitment.x, commitment.y)
    new ← (decision.candidate.x, decision.candidate.y)
    mission.goal ← GoalPose(new.x, new.y, heading=..., arrival_radius=...)
    commitment ← ApproachCommitment(..., generation=commitment.generation+1)
    overwrite approach_*_cost in metadata
    metadata["re_rank_count"] += 1
    metadata["re_rank_events"].append({t, old, new, costs, generation})
    # DO NOT: reset RampMemory; clear person_stop; seed; open crossing
    # DO: freeze progress watchdog stall counter this tick (like yield)

  IF tracks empty:
    ASSERT re_rank_count unchanged this tick  # ladder pin in tests
```

**Sampling helper export:** `_safe_polygon_point`’s sample/filter logic
(`approach.py:239-286`) should be exposed as
`sample_approach_candidates_inside(...)` returning the `valid` list **before**
ranking, so commit-time and re-rank-time share one free set. Divergent sample
sets would make hysteresis comparisons meaningless.

### P2.1.6 Invariants (re-rank)

1. Empty / all-stale tracks ⇒ zero re-commits (ladder).
2. Re-commit updates `mission.goal` only; never opens a gate; never seeds.
3. `RampMemory` state machine unchanged across re-commit.
4. Cap ~1 Hz; hysteresis prevents flicker on near-ties.
5. Cost breakdown always attributable in mission metadata.
6. `person_stop_m` / TTC / collision thresholds unchanged in the diff.

## P2.2 Dwell-based `inside` arrival — complete algorithm

### P2.2.1 State

```python
@dataclass
class InsideDwellState:
    inside_since_s: float | None = None
    last_detail: str = "unset"

    def reset(self) -> None:
        self.inside_since_s = None
        self.last_detail = "reset"
```

### P2.2.2 Update

```text
FUNCTION update_inside_dwell(
    state: InsideDwellState,
    *,
    now_s: float,
    robot_xy: (float, float),
    polygon: Sequence[(float, float)],
    clearance_m: float,
    collision_note: str,
    collision_brake_active: bool,
    metric_evidence_id: str,
    metric_evidence_age_s: float,
    pose_transform_healthy: bool,
    agent_stop_commanded: bool,
    settled_feedback: bool,
    inside_arrival_dwell_s: float = 0.75,
    max_metric_evidence_age_s: float = 0.25,
) → (arrived: bool, detail: str):

  VALIDATE finite now_s; clearance_m ≥ 0; dwell_s > 0; polygon len ≥ 3

  IF (NOT metric_evidence_id OR metric_evidence_age_s > max_metric_evidence_age_s
      OR NOT pose_transform_healthy):
    state.reset(); state.last_detail ← "stale_or_unhealthy_geometry"
    RETURN (False, "stale_or_unhealthy_geometry")

  IF collision_brake_active OR collision_note != "clear":
    # Any proximity/TTC/obstacle/person brake blocks terminal success.
    state.reset(); state.last_detail ← "collision_brake"
    RETURN (False, "collision_brake")

  inside ← point_in_polygon_with_clearance(robot_xy, polygon, clearance_m)
  IF NOT inside:
    state.inside_since_s ← None
    state.last_detail ← "outside"
    RETURN (False, "outside")

  IF state.inside_since_s is None:
    state.inside_since_s ← now_s
    state.last_detail ← "dwell_started"
    RETURN (False, "dwell_started")

  IF (now_s − state.inside_since_s) < inside_arrival_dwell_s:
    state.last_detail ← "dwell_pending"
    RETURN (False, "dwell_pending")

  IF NOT agent_stop_commanded OR NOT settled_feedback:
    state.last_detail ← "terminal_stop_pending"
    RETURN (False, "terminal_stop_pending")

  state.last_detail ← "inside_dwell_verified"
  RETURN (True, "inside_dwell_verified")
```

### P2.2.3 Replace `_inside_arrival_goal_region`

```text
REPLACE body of _inside_arrival_goal_region(observation):

  IF mission is None OR status != "running" OR semantic_goal is None:
    RETURN False

  IF semantic_goal.terminal_relation != "inside":
    region ← _arrival_goal_region()
    IF region is None: RETURN False
    robot_map ← pose_in(observation, MAP)
    RETURN region.contains(robot_map.x, robot_map.y)   # unchanged

  # --- inside path (NEW) ---
  polygon ← arrival_goal_region.polygon OR candidate polygon from metadata
  IF polygon empty: RETURN False

  clearance ← mission.metadata["terminal_clearance_m"]
              # default footprint; MUST match approach inset, NOT 0.0
  clearance ← max(clearance, footprint_radius used at commit)

  cnote ← last collision note from this tick (thread through step)
  brake_active ← cnote != "clear"

  arrived, detail ← update_inside_dwell(
      self._inside_dwell, now_s=..., robot_xy=MAP.xy,
      polygon=polygon, clearance_m=clearance,
      collision_note=cnote,
      collision_brake_active=brake_active,
      metric_evidence_id=perception_health.metric_evidence_id,
      metric_evidence_age_s=perception_health.metric_evidence_age_s,
      pose_transform_healthy=pose_health.ok and transform_health.ok,
      agent_stop_commanded=nav_feedback.agent_stop_commanded,
      settled_feedback=nav_feedback.settled,
  )
  metadata["inside_dwell_detail"] ← detail
  metadata["inside_dwell_s"] ← ...
  RETURN arrived

ON mission change / cancel / Hold: _inside_dwell.reset()
```

**Clearance default:** match approach inset
(`max(footprint_clearance_m, terminal_clearance_m)`), not `0.0`, so edge
graze cannot launder a near-miss (N3 §4.2; approach inset at
`approach.py:78`).

### P2.2.4 False-success pins (ship with the feature)

| Case | Expected detail |
| --- | --- |
| Robot in street, outside polygon | `outside` |
| Robot grazes polygon edge, clearance unmet | `outside` |
| Robot inside, dwell 0.2 s < 0.75 s | `dwell_pending` |
| Robot inside + `person_stop` for ≥ dwell | no success; active brake resets terminal dwell |
| Robot inside + active collision-brake | `collision_brake` |
| Robot inside, clear, fresh, settled after agent stop for ≥ dwell | **success** `inside_dwell_verified` |
| Eval disc (K0) vs semantic polygon disagree | Product witness = semantic polygon + clearance; score eval with same rule |

## P2.3 Yield-advance — preserve contract (no redesign)

Document the ABI implementers must not break:

| API | May | Must not |
| --- | --- | --- |
| `RampMemory.note_stopped` | remember | return a velocity |
| `RampMemory.release` | return seed after caller asserts gate open | be called during `person_stop` |
| `_final_metre_creep` | floor seed to 0.12 when clear+band+predicted clear | raise creep past person-stop needs; seed on gated ticks |
| `seed_ramp` / `pending_ramp_seed_mps` | slew limiters | bypass collision brake |

D3 diagnostics only (unless A/B proves need):

1. Log `predicted_clear_window_s` vs `remaining_m / creep_mps` each final-metre tick.
2. Optional clear-window filter on re-rank (flag).
3. **One knob per experiment** — do not retune creep and re-rank together.

## P2.4 Formation → common planner — complete seam

### P2.4.1 Contract

```python
@dataclass(frozen=True)
class FollowFormationGoalV1:
    x: float
    y: float
    yaw_rad: float | None
    relation: str          # "follow" | "behind" | ...
    distance_m: float
    issued_s: float
    expires_at: float      # TTL ≤ 0.2–0.5 s
    owner_track_id: str
    generation: int
    frame: str = "MAP"
```

### P2.4.2 Control loop

```text
OwnerTrackV1 (confirmed, enrolled multi-frame) @ perception rate
        │
        ▼
FormationGoalSampler @ 10–20 Hz
  preferred annulus / angle (SOFT)
  → FollowFormationGoalV1
        │
        ▼
DirectiveNavigator accepts as mission.goal if
  formation_via_planner flag AND TTL fresh AND owner confirmed
        │
        ▼
grid_v1 (+ dynamic soft costs) → MidLevelCommand
        │
        ▼
same apply_collision_brake / TTC / shield as NavigateTo
```

### P2.4.3 Rules

1. Sampler owns preferred annulus/angle (soft). Planner owns free space.
2. Identity is enrolled multi-frame posterior — never nearest-person; never
   MiniCPM identity (N4 / N6).
3. `ApproachOwner` (N6 split): terminate when band held + settled → **disable**
   follow channel. `FollowFormation`: persistent until Hold/cancel.
4. Stale TTL → HOLD / acquire, not open-loop chase.
5. Flag `follow.formation_via_planner: false` default until Week B green;
   empty/disabled ⇒ legacy `_step_direct` (CI label honest).

**Out of Week A critical path.** N11 flip must not depend on this.

## P2.5 OSM advisory + no autonomous road entry

```text
OsmWaypointProposer / CityWalker / GNSS GEO
  → SE2Goal | NavProposalV1  (source, ttl, confidence, frame)
  → GoalArbiter nomination
  → local re-ground + grid_v1
  → CrossingModePolicy gate on any edge that leaves sidewalk

CrossingModePolicy (required product semantics):
  sidewalk → approach curb → STOP + announce
           → authenticated, authorized owner/control-channel decision
             bound to task revision, event ID, curb-stop state, and TTL
             (recognized transcript/phrase alone is insufficient)
           → CROSSING_AUTHORIZED (TTL)
           → metric monitor still owns collision stop
  autonomous_road_entry_blocked = True always for proposers
  allow_crossing flag ONLY from CrossingModePolicy
```

Hard bans (N8 invariants):

- Incomplete OSM sidewalk graph must not authorize road centerlines.
- GNSS east/north alone must not decide sidewalk membership.
- CityWalker must not declare arrival, free space, or crossing auth.

---

# Geometric + safety non-interference justification (MANDATORY)

This section is the load-bearing argument that D3 can flip N11 without
weakening hard stops. Every claim cites either Parcel source or an explicit
UNVERIFIED mark.

## GSNI-1. Separation of decision variables

Define three disjoint decision variables per tick:

| Symbol | Meaning | Writers in D3 |
| --- | --- | --- |
| `G_t` | committed approach goal SE(2) | re-rank (when gated + hysteresis) |
| `A_t` | arrival boolean into verifying | dwell-inside OR geometric pose stop |
| `V_t` | commanded body velocity | navigator + brake + seed (unchanged authority order) |

Hard monitors write **only** `V_t` (and can force `V_t = 0`). Re-rank writes
**only** `G_t`. Dwell writes **only** `A_t`. There is no D3 code path that
writes `V_t` while `cnote == "person_stop"`.

Proof sketch from existing wiring: after `apply_collision_brake`, if
`person_gate_stop`, the function returns zero command before any seed lift
can matter (`pipeline.py:685-691` requires `not person_gate_stop` and
`cnote == "clear"`; `pipeline.py:716-717` forces zero). Re-rank runs as a
side effect on mission metadata / goal pose and does not call
`seed_ramp` or mutate brake policy.

## GSNI-2. Re-rank cannot open a gate

`should_rerank_approach` defaults `require_person_stop=True`. The evaluate→
commit path updates `mission.goal` but does not:

- call `RampMemory.release`
- set `pending_ramp_seed_mps`
- modify `CollisionPolicy.person_stop_m`
- set `CrossingDecision.allow_crossing_edges`
- clear `person_stop` note

Therefore a re-commit during an occupied corridor leaves the robot
**stopped at the same place** with a **different future target**. Motion
still requires a future clear tick through the same brake.

## GSNI-3. Dwell-inside cannot succeed from the street

Success requires `point_in_polygon_with_clearance` (`approach.py:293-298`)
with clearance ≥ approach inset. The measured end pose y≈2.07 fails
polygon membership (y≥2.2). Therefore dwell alone **cannot** flip the xfail
from the measured failure pose — it needs either:

- lateral progress into the polygon on clear ticks after re-rank, or
- a clear window long enough to creep past y=2.2 under Path A′ (same goal).

This is intentional: dwell is a **correctness** definition for contested
regions, not a score laundering tool. False-outside pins enforce it.

## GSNI-4. Seed-only yield cannot move on a stop tick

From `RampMemory` module docstring (`traffic_aware.py:29-36`): memory is
never a gate and never a command source. `note_stopped` returns nothing
(`traffic_aware.py:486-488`). Pipeline returns seed `0.0` on person_stop
(`pipeline.py:769-771`). Final-metre creep refuses non-clear notes
(`pipeline.py:836-837`). Tests pin `test_never_emits_during_stop`
(`tests/test_traffic_aware.py:537`).

D3 adds no new emitter.

## GSNI-5. Soft traffic cost cannot authorize free space

`traffic_occupancy_cost` returns exposure seconds (`traffic_aware.py:200-242`),
not an occupancy cell write. Ranking picks among **already statically free**
samples from `_safe_polygon_point` (`approach.py:270-281`). Re-rank reuses
the same free set. Soft cost never marks a blocked cell free.

## GSNI-6. Advisory maps cannot authorize road entry

`CrossingDecision.autonomous_road_entry_blocked` defaults True
(`crossing.py:85`). Road pose without auth → BLOCKED
(`crossing.py:199-211`). Goal into keepout without the bound authorization →
veto (`crossing.py:213-228`). D3’s OSM path is nomination-only into the same
arbiter; it does not call `request_voice_initiation`.

## GSNI-7. Empty-tracks identity (ladder) is preserved

Re-rank short-circuits on empty/all-stale tracks. Existing
`rank_approach_candidates` empty-tracks ordering remains the commit-time
behavior (`traffic_aware.py:309-312`; `tests/test_traffic_aware.py:321-331`).
Static sidewalk e2e must stay green without re-rank side effects.

## GSNI-8. What would falsify non-interference

| Falsifier | How we detect | Response |
| --- | --- | --- |
| Diff changes `person_stop_m` / TTC thresholds | code review + config diff pin | reject flip |
| Re-rank calls `seed_ramp` while gated | unit wiring test | fail CI |
| Dwell succeeds with clearance=0 on edge graze | false-outside pin | fail CI |
| OSM proposer sets `allow_crossing_edges` | crossing ownership pin | fail CI |
| Empty-tracks e2e regresses | ladder e2e | fail CI |
| Formation flag-on bypasses brake | NavigateTo/follow shared brake pin | fail CI |

## GSNI-9. Literature alignment (why the split works)

- GSCL: soft social costmap + ~1 Hz BT replan + stop-and-go — social soft /
  geometry hard (N3 §3.6).
- Follow-Bench: safety metrics (ASR) vs comfort metrics — comfort never
  grants collision permission (N3 §3.1).
- Nav2 Route / OSM practice: topological prior + local free-space — map
  advisory (N8 §3, §7).
- CityWalker author framing: Maps/GPS for high-level; learned policy between
  waypoints — still not Sport authority (N8 §5).

Parcel’s contribution is encoding the split as **ABI invariants** with
tests, not as comments.

---

# PASS 3 — Adversarial self-critique and rewrites

## P3.1 Attack: “Just shrink person_stop_m by 0.4 m”

**Attack:** The robot dies 0.33 m short. Shrinking the stop envelope would
let creep finish.

**Refutation:** That trades a hard stop for a score. Explicit non-goal in
N3 and v0 D3. Flip protocol forbids threshold changes. Measured agents
occupy the strip; a smaller envelope increases collision risk under any
tracker lag. **Rewrite:** Flip checklist item “no person_stop / TTC
relaxation in the diff” is binding acceptance, not aspirational.

## P3.2 Attack: “Dwell with clearance=0 to count edge graze”

**Attack:** Set clearance to 0 so y=2.21 counts as inside immediately.

**Refutation:** Approach sampling uses inset
`max(footprint, terminal_clearance + arrival_radius)` (`approach.py:78`).
Zero clearance would accept poses the commit path itself rejects as
terminal. **Rewrite:** clearance_mode `approach_inset` is the only allowed
default; config rejecting clearance < footprint fails validation.

## P3.3 Attack: “Re-rank every tick without hysteresis”

**Attack:** Always take `ranked[0]` when evaluating.

**Refutation:** Near-ties on a sidewalk strip cause goal flicker; grid
replans thrash; watchdog may see oscillating progress. GSCL uses ~1 Hz;
ReactionArbiter uses soft commitment. **Rewrite:** `cost_improve_eps=0.15`
plus `hysteresis_bonus=0.08` are mandatory; tests pin sticky commitment.

## P3.4 Attack: “Use proxemic reject_cost as sole selector”

**Attack:** Wire parked `proxemic_approach.reject_cost` as the chooser.

**Refutation:** Fail-closed `None` under empty/all-hot candidates breaks
empty-tracks identity (OPUS_N11_STATUS; `approach.py:362-369`). Ranking
with finite costs + optional veto-when-tracks is the safe order. **Rewrite:**
veto remains optional, flag-gated, Week C; never sole selector.

## P3.5 Attack: “Seed while person_stop if clear_window predicts a gap”

**Attack:** Predictive creep through a stop gate.

**Refutation:** Predictions are wrong under interaction; N11 pedestrians are
non-reactive (SocNavBench-like), but product humans are not. Seed-while-
gated violates GSNI-4 and `RampMemory` contract (`traffic_aware.py:29-36`).
**Rewrite:** forbidden; no flag exposes it.

## P3.6 Attack: “Succeed from K0 eval disc alone”

**Attack:** Use y≥2.4 GoalRegion.contains without semantic polygon clearance.

**Refutation:** Product witness must be semantic polygon + clearance; K0 is
the independent scorer. Disagreement without claim is already an authority
category in the e2e harness. **Rewrite:** dwell uses semantic polygon;
scoring remains K0; both must agree for flip.

## P3.7 Attack: “CityWalker / OSM unlock crossing for sidewalk goals”

**Attack:** Destination on far sidewalk ⇒ autonomous cross.

**Refutation:** Crossing is companion law gated by an authenticated,
authorized owner/control-channel decision bound to task/revision and TTL; a
transcript alone is insufficient. CityWalker must not declare crossing auth
(N8 §5).
**Rewrite:** `autonomous_road_entry: false` immutable; CI pin
`decision_blocks_autonomous_road`.

## P3.8 Attack: “Formation proportional twist is fine if we add person_stop”

**Attack:** Keep `_step_direct`; duplicate brake logic.

**Refutation:** Divergent planners diverge under crowds (N6). Duplicated
brakes drift. **Rewrite:** Week B routes formation goals into `grid_v1`;
legacy direct remains behind flag with honest CI label — not dual-authored
safety.

## P3.9 Attack: “Claim field social competence after R0 e2e flip”

**Attack:** Marketing the xfail flip as outdoor readiness.

**Refutation:** Honesty ladder (N4); planar LiDAR misses curb height (N8);
sim GNSS not field-characterized. **Rewrite:** flip ≠ outdoor certificate;
docs must say so in the scrum digest.

## P3.10 Weak sections found in Pass-2 draft — rewritten here

### Rewrite A — Person-stop dwell clock vs ramp max_hold

Pass-2 used a navigator-local `_person_stop_dwell_s` independent of
`RampMemory.max_hold_s` (default 2.5 s). Adversarial case: dwell clock
runs past `max_hold_s`, held ramp velocity clears, then re-rank commits a
farther goal — creep starts from zero. **Resolution:** this is acceptable
and correct (long stop ⇒ world changed ⇒ drop memory,
`traffic_aware.py:495-497`). Re-rank must not revive held velocity.
Documented interaction: re-rank ⊥ ramp memory.

### Rewrite B — `require_person_stop=False` escape hatch

An escape hatch for “re-rank while slow” would let soft cost rewrite goals
during motion, interacting with grid dynamic costs twice. **Resolution:**
no public escape in Week A. If Week C needs cruise re-rank, it is a
separate proposal with its own interference proof.

### Rewrite C — Tracker vs `dynamic_agents` oracle

Final-metre creep already refuses oracle extras velocity
(`pipeline.py:830-833`). Re-rank in sim may use `dynamic_agents` with an
honest label; product path prefers people tracker. **Resolution:** metadata
field `re_rank_track_source ∈ {"dynamic_agents","people_tracker"}`; tests
may use either but digests must label.

### Rewrite D — Inside dwell and terminal environment clear

Terminal verification currently fails if `nearest_person_m < person_stop_m`
(`pipeline.py:2577-2580`). Preserve that fail-closed behavior. Polygon dwell
is only terminal-ready when the current task/revision has fresh metric evidence,
healthy pose/transforms, an agent-issued exact-zero stop, settled feedback for
the hold duration, and no active person/TTC/obstacle brake.

```text
ON entering verifying via inside_dwell_verified:
  REQUIRE same task_id + revision for every witness
  REQUIRE metric evidence ID present and age within the declared bound
  REQUIRE pose/transform health OK and polygon+clearance membership
  REQUIRE collision_note == "clear" and no active brake
  REQUIRE agent_stop_commanded and settled_feedback for the dwell interval
  ELSE remain running/HOLD; never report terminal success
```

This may delay completion while a pedestrian occupies the terminal region;
that is the intended safety outcome. Re-rank may select another admissible
inset, but an active brake cannot be reclassified as a successful arrival.

## P3.11 Pass-3 verdict

D3’s shape survives adversarial review if and only if:

1. GSNI-1…8 hold in the implementation diff,
2. Rewrite D's fresh-evidence, clear-brake, agent-stop, and settled-feedback
   terminal gates land with dwell,
3. Flip protocol forbids threshold hacks,
4. Field claims stay honest.

---

# PASS 4 — Gap expansion (depth bar completion)

## P4.1 Full worked scenario — occupied sidewalk tick narrative

Scenario: `go to the sidewalk` with scripted pedestrians on y≈2.85–3.55.
NavigateTo budget 240 s. After ~200 s of approach + yields, robot at
≈(−0.27, 2.07), committed goal ≈(−0.2, 2.64), `person_stop` active.

### State variables (carried across ticks)

```text
mission.status = "running"
mission.goal = GoalPose(x=-0.2, y=2.64, arrival_radius≈0.12)
commitment.generation = 0
commitment.total_cost = C0   # from commit-time ranking
RampMemory.state = "stopped"
RampMemory.held_vx = maybe 0 if stop > max_hold_s
person_stop_dwell_s = accumulating
inside_dwell.inside_since_s = None   # still outside polygon
re_rank_count = 0
last_rerank_s = None
CrossingDecision.allow_crossing_edges = False
autonomous_road_entry_blocked = True
```

### Tick T0 — person_stop, dwell < 1.0 s

```text
navigator.act → proposes vx>0 toward (−0.2, 2.64)
apply_collision_brake → (0, 0, "person_stop")     # collision.py:105-107
_update_ramp_memory → note_stopped; seed=0        # pipeline.py:769-771
person_stop_dwell_s += dt
should_rerank? band OK, dwell < 1.0 → reason="dwell"
inside dwell? y=2.07 outside → False
return MidLevelCommand(vx=0, vy=0, stop=False, note="…|person_stop")
progress watchdog: freeze stall (yield)
ASSERT pending_ramp_seed_mps is None
ASSERT CrossingDecision unchanged
```

### Tick T0+1.2 s — evaluate and commit

```text
person_stop still active; dwell ≥ 1.0; last_rerank None
tracks fresh (age_s < 1.0)
should_rerank → evaluate
sample polygon free set (same as approach.py:239-286)
rank_approach_candidates(traffic_weight=2.0)
best total_cost + eps + bonus < C0 → COMMIT
  e.g. shift to (−0.55, 2.45) quieter inset still ≥ 2.2 clearance
mission.goal updated; commitment.generation = 1
metadata.re_rank_count = 1
RampMemory NOT reset; still stopped; vx still 0
grid will replan on next clear tick toward NEW goal
```

### Tick T0+1.4 s — brief clear window

```text
apply_collision_brake → clear
RampMemory.release → seed (or 0 if long hold)
_final_metre_creep may floor to 0.12 if remaining ≤ 1.0 and predicted clear
vx = max(cmd, min(seed, max_vx)) still post-brake
robot advances toward NEW commitment (lateral component helps enter polygon)
person_stop_dwell_s reset on clear
```

### Tick T0+2.0 s — another agent; person_stop; maybe inside

```text
stop exact; note_stopped
IF robot now inside polygon with clearance (e.g. y=2.28):
  inside_since_s ← T0+2.0; detail=dwell_started
ELSE:
  re-rank rate-limited to ~1 Hz if still outside
```

### Tick T0+2.8 s — person stop still active

```text
update_inside_dwell → (False, "collision_brake")
wait for fresh clear metric evidence; issue exact-zero terminal stop
require healthy pose/transform + settled feedback for the full dwell
update_inside_dwell after clear hold → (True, "inside_dwell_verified")
mission.status → verifying
arrival_trigger = "goal_region" (or goal_region_or_pose)
terminal verification: relation inside + settle
task → succeeded when witnesses pass
NEVER: creep raised; NEVER: person_stop shrunk; NEVER: OSM allow_crossing
```

### Failure branches still allowed (honest)

```text
F1 all candidates hot → no_improvement / unreachable; yield until timeout
F2 clear windows too short even to re-ranked pose → timeout; keep xfail
F3 dwell pending interrupted by leaving polygon → reset inside_since
F4 collision_brake while inside → reset dwell; no success
F5 tracks go stale mid-evaluate → noop_empty_tracks next gate
```

## P4.2 Extended tick table (20 ticks, compressed)

| t (s) | cnote | dwell_s | gate | re_rank | inside | vx | notes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 200.0 | person_stop | 0.0 | dwell | 0 | outside | 0 | enter yield |
| 200.5 | person_stop | 0.5 | dwell | 0 | outside | 0 | |
| 201.0 | person_stop | 1.0 | evaluate | 0→1 | outside | 0 | commit gen1 |
| 201.1 | person_stop | 1.1 | rate_limit | 1 | outside | 0 | |
| 201.3 | clear | 0 | not_yielding | 1 | outside | creep | advance |
| 201.5 | person_stop | 0.0 | dwell | 1 | outside | 0 | |
| 202.0 | person_stop | 0.5 | dwell | 1 | edge? | 0 | |
| 202.5 | person_stop | 1.0 | evaluate | 1 | maybe | 0 | no_improvement |
| 203.0 | clear | 0 | not_yielding | 1 | inside? | creep | |
| 203.2 | person_stop | 0.0 | dwell | 1 | inside | 0 | active brake; terminal dwell reset |
| 203.5 | person_stop | 0.3 | dwell | 1 | inside | 0 | still blocked |
| 204.0 | clear | 0.0 | — | 1 | inside | 0 | issue terminal exact-zero stop; dwell starts |
| 204.8 | clear | — | — | 1 | inside | 0 | fresh + healthy + settled; inside_dwell_verified |
| 204.8 | clear | — | — | 1 | verifying | 0 | enter verify |
| 205.0 | clear | — | — | 1 | verifying | 0 | settle hold |
| 208.0 | clear | — | — | 1 | succeeded | 0 | witnesses pass |
| — | — | — | — | — | — | — | if timeout@240: digest |

## P4.3 ABI freeze table (shared with D1/D2)

| ABI | Owner | D3 requirement |
| --- | --- | --- |
| `PoseEstimate` health | D1 / N4 | LOST → HOLD; no open-loop social |
| `NavProposalV1` / `SE2Goal` | D2 + maps | TTL, source, never Sport |
| `ApproachCommitment` | D3 | generation + cost snapshot |
| `FollowFormationGoalV1` | D3 Week B | short TTL formation |
| `CrossingDecision.allow_crossing_edges` | crossing.py | sole unlock |
| Mission metadata `approach_*_cost` | N11 wiring | overwrite on re-commit |
| Mission metadata `re_rank_*` / `inside_dwell_*` | D3 | attributable flip |

## P4.4 Config sketch (implementable)

```yaml
# configs/navigation/default.yaml
social_city:
  re_rank:
    enable: true
    band_m: 1.75
    min_dwell_s: 1.0
    min_interval_s: 1.0
    cost_improve_eps: 0.15
    hysteresis_bonus: 0.08
    max_age_s: 1.0
    traffic_weight: 2.0
    top_k: 64
    clear_window_filter: false   # Week C
  inside_dwell:
    enable: true
    dwell_s: 0.75
    clearance_mode: approach_inset   # not zero
    allow_yield_while_inside: true
    verifying_allow_in_region_yield: true  # Rewrite D
  yield_advance:
    seed_only: true
    # FINAL_APPROACH_* remain code constants unless separately flagged
  follow:
    formation_via_planner: false
    formation_rate_hz: 15.0
    formation_ttl_s: 0.35
  city:
    osm_advisory_only: true
    autonomous_road_entry: false   # immutable product law
```

## P4.5 File-level implementation map

| File | D3 change |
| --- | --- |
| `navigation/traffic_aware.py` | `ApproachCommitment`, `should_rerank_approach`, `select_recommit` |
| `navigation/approach.py` | export `sample_approach_candidates_inside`; dwell helpers |
| `navigation/pipeline.py` | re-rank wire; replace inside `return False`; Rewrite D; metadata |
| `navigation/follow.py` | FormationGoalSampler behind flag |
| `maps/crossing.py` | replace phrase-only initiation with bound authorization; tests pin ownership and reject transcript-only input |
| `tests/test_traffic_aware.py` | pure re-rank / dwell pins |
| `tests/test_approach_traffic_wiring.py` | re-commit wiring + ramp preservation |
| `tests/test_voice_nav_e2e.py` | flip xfail on hard pass only |
| `configs/navigation/default.yaml` | `social_city` block |

**Do not rewrite** Sol’s pure ranking/ramp contracts; extend.

## P4.6 Compose with D1 / D2

| Concern | D1 | D2 | D3 |
| --- | --- | --- | --- |
| Exact-zero / LiDAR HOLD / resume atomicity | Owns | Consumes | Must not regress |
| `grid_v1` production writer | Owns | Challenger proposals | Formation + NavigateTo share |
| `NavProposalV1` | Consumer | Owns shadows | OSM / formation nomination shape |
| Soft social / re-rank / dwell | — | Must not bypass | Owns |
| Crossing / road ban | Policy pins | CityWalker must not unlock | Enforces in social-city path |

Ship order: D1 P0-A/B/C/H + real P1-B/P1-D witnesses → D3 Week A
(N11) → D2 shadows optional for flip. Pure D3 code may be developed earlier
against labeled simulation, but it cannot promote or remove the xfail early.

## P4.7 Migration plan

### Week A — N11 residual

| Day | Work | Exit |
| --- | --- | --- |
| A0 | Freeze failing digest (pose, costs, dwell hist, clear windows) | scrum note |
| A1 | Pure re-rank + hysteresis + tests | `test_traffic_aware` green |
| A2 | Wire mid-mission re-commit; metadata; watchdog freeze | wiring tests |
| A3 | Dwell inside + false-success pins + Rewrite D | unit + headless |
| A4 | Pedestrian e2e `--runxfail`; flip only on hard pass | gate or keep xfail |
| A5 | N13 disposition writeup | scrum |

### Week B — formation seam

| Day | Work |
| --- | --- |
| B0–B1 | `FollowFormationGoalV1` + flag; sampler → planner |
| B2–B3 | Follow-Bench license spike + oracle smoke |
| B4–B5 | Promotion rules; no N11 dependency |

### Week C — optional

- Clear-window filter on re-rank
- Soft proxemic veto when tracks non-empty
- Crowd-cost normalization on `dynamic_layer`
- Camera Follow-Bench lane

## P4.8 Risks register

| ID | Risk | Mitigation |
| --- | --- | --- |
| R1 | Re-rank flicker | hysteresis + min interval + generation telemetry |
| R2 | Dwell launders near-misses | polygon + approach inset; forbid disc-only |
| R3 | Creep + re-rank interaction | log both; one knob per A/B |
| R4 | CPU thrash on large candidate sets | top_k=64; ~1 Hz |
| R5 | Tracker vs extras mismatch | label `re_rank_track_source` |
| R6 | Formation latency / oscillation | short TTL; HOLD on stale |
| R7 | OSM as free space | advisory ABI + CI pins |
| R8 | Pressure to weaken person_stop | flip protocol forbids |
| R9 | Field claim from R0 e2e | honesty ladder |
| R10 | D1 P0 unfinished confounds A/B | sequence D1 first |
| R11 | Rewrite D too loose | still require inside+clearance+settle |
| R12 | Verifying oscillation | dwell reset on mission change only |

## P4.9 N11 flip protocol (binding)

```bash
.parcel/bin/pytest tests/test_traffic_aware.py \
  tests/test_approach_traffic_wiring.py \
  tests/test_navigation.py -q

.parcel/bin/pytest -m slow \
  tests/test_voice_nav_e2e.py::test_go_to_the_sidewalk_with_pedestrian_traffic \
  -v --runxfail
```

Flip `@pytest.mark.xfail` only if:

1. P0-A/B/C/H and real P1-B/P1-D producer/witness gates are green.
2. Hard pass: `states == succeeded`; fresh independent metric evidence proves
   polygon membership with clearance; pose/transforms are healthy; settled
   feedback acknowledges an agent-issued exact-zero stop; no brake is active.
3. Telemetry: `re_rank_count ≥ 1` **or** `inside_dwell_detail == inside_dwell_verified`.
4. No change to `person_stop_m` / TTC / collision brake semantics.
5. Empty-tracks sidewalk e2e still passes.
6. Digest freezes task/revision and witness IDs, evidence ages, clearance,
   stop/settled acknowledgement, end pose, and mechanism telemetry.

If still fail: keep xfail; update reason with end pose and gate
(`no_improvement`, timeout, verify fail). No progress hack.

## P4.10 What the flip does not prove

| Suite | Not claimed |
| --- | --- |
| Follow-Bench | RPF comfort / ASR |
| HuNavSim / MetaUrban | Interactive humans / city density |
| Field Go2 | Localization, curb physics, Sport tracking |
| CityWalker 77.3% | Parcel readiness |

## P4.11 Citation index (≥20 file:line anchors)

| # | Anchor | Claim supported |
| --- | --- | --- |
| 1 | `traffic_aware.py:29-36` | RampMemory seed-only safety argument |
| 2 | `traffic_aware.py:68-91` | TrackState + age_s for staleness |
| 3 | `traffic_aware.py:200-283` | traffic_occupancy_cost CV integral |
| 4 | `traffic_aware.py:309-312` | empty-tracks ladder rule |
| 5 | `traffic_aware.py:286-400` | rank_approach_candidates API |
| 6 | `traffic_aware.py:403-430` | RampMemory protocol |
| 7 | `traffic_aware.py:486-522` | note_stopped / release semantics |
| 8 | `approach.py:46-64` | track-LiDAR filter + traffic_weight 2.0 |
| 9 | `approach.py:70-92` | inside clearance / approach inset |
| 10 | `approach.py:239-286` | polygon interior sampling free set |
| 11 | `approach.py:293-298` | point_in_polygon_with_clearance |
| 12 | `approach.py:362-388` | ranking authority + empty-tracks skip veto |
| 13 | `pipeline.py:638-654` | arrival triggers into verifying |
| 14 | `pipeline.py:663-717` | brake + person_stop zero preserve |
| 15 | `pipeline.py:733-787` | yield-advance wiring |
| 16 | `pipeline.py:789-861` | FINAL_APPROACH_* creep |
| 17 | `pipeline.py:830-833` | no oracle extras velocity for creep |
| 18 | `pipeline.py:1304-1354` | commit-time safe_approach_pose + costs |
| 19 | `pipeline.py:2535-2538` | inside arrival intentional False |
| 20 | `pipeline.py:2588-2593` | inside furniture verification carve-out |
| 21 | `pipeline.py:2204-2209` | watchdog yield freeze |
| 22 | `collision.py:105-107` | person_stop exact zero return |
| 23 | `follow.py:596-658` | direct proportional twist |
| 24 | `crossing.py:78-85` | CrossingDecision defaults |
| 25 | `crossing.py:199-211` | autonomous road entry blocked |
| 26 | `crossing.py:267-282` | curb_stop_awaiting_voice |
| 27 | `test_voice_nav_e2e.py:413-442` | N11 xfail measurement |
| 28 | `test_traffic_aware.py:321-331` | empty-tracks ordering pin |
| 29 | `test_traffic_aware.py:537` | never emits during stop |
| 30 | `test_voice_nav_e2e.py:14-17` | dual authority scoring |

Paths above are under `src/parcel_robot/navigation/` or `src/parcel_robot/maps/`
or `tests/` as indicated.

---

# UNVERIFIED register

| ID | Claim | Status | What would verify |
| --- | --- | --- | --- |
| U1 | Re-rank + dwell flips pedestrian e2e hard pass | UNVERIFIED | A4 `--runxfail` hard pass |
| U2 | CV + age filter sufficient predictor for week-1 | UNVERIFIED (N3 medium) | A/B vs CA model on same digest |
| U3 | Hysteresis (0.15+0.08) prevents flicker without blocking useful commits | UNVERIFIED | unit + e2e `re_rank_events` entropy |
| U4 | Rewrite D does not create false success under furniture+crowd | UNVERIFIED | adversarial unit pins |
| U5 | Formation→planner improves Follow-Bench comfort without ASR loss | UNVERIFIED | Week B oracle lane |
| U6 | People-tracker tracks match extras closely enough for re-rank | UNVERIFIED | labeled-sim disagreement log |
| U7 | Clear-window filter helps more than integral cost alone | UNVERIFIED | Week C flag A/B |
| U8 | Mid-360 / FAST-LIO2 health gates sufficient for outdoor social | UNVERIFIED | P1-B + P5 HIL (N4) |
| U9 | Elevation curb detection ready before outdoor crossing claims | UNVERIFIED | N8 Phase B |
| U10 | N13 bench/lamppost near-misses share dwell-band helper | UNVERIFIED | A5 disposition |
| U11 | `top_k=64` does not drop the true quieter inset under stream | UNVERIFIED | digest candidate coverage |
| U12 | 0.75 s inside dwell matches human expectation for “on the sidewalk” | UNVERIFIED | product UX review |
| U13 | CityWalker shadow never unlocks crossing in integration | UNVERIFIED | D2×D3 CI pin |
| U14 | CPU budget for 1 Hz re-rank on Orin acceptable | UNVERIFIED | `cpu_budget_proxy` under load |

---

# Acceptance test matrix

| ID | Test | Pins | Gate |
| --- | --- | --- | --- |
| T01 | `should_rerank` empty tracks | no-op, no side effects | Week A merge |
| T02 | `should_rerank` all-stale | noop_empty_tracks | Week A merge |
| T03 | `should_rerank` band / dwell / rate | reject reasons | Week A merge |
| T04 | `select_recommit` hysteresis | sticky commitment | Week A merge |
| T05 | `select_recommit` improvement | commit when Δ exceeds eps+bonus | Week A merge |
| T06 | `update_inside_dwell` false-outside | no success | Week A merge |
| T07 | `update_inside_dwell` edge without clearance | outside | Week A merge |
| T08 | `update_inside_dwell` person-stop-inside | no success; reset | Week A merge |
| T09 | `update_inside_dwell` collision-brake | reset, no success | Week A merge |
| T10 | Wiring: re-rank does not reset ramp | ramp state preserved | Week A merge |
| T11 | Wiring: re-rank freezes watchdog | no false stall | Week A merge |
| T12 | Wiring: no seed on person_stop | pending seed None | Week A merge |
| T13 | Empty-tracks sidewalk e2e | still green | Week A merge |
| T14 | Pedestrian e2e `--runxfail` | hard pass before xfail removal | Flip gate |
| T15 | Flip telemetry | re_rank_count≥1 or inside_dwell_verified | Flip gate |
| T16 | Config diff | no person_stop_m / TTC change | Flip gate |
| T17 | Crossing autonomous road pin | still blocked | Week A merge |
| T18 | Formation flag off | legacy direct labeled | Week B |
| T19 | Formation flag on | goals hit grid_v1 + shared brake | Week B |
| T20 | OSM nomination TTL expiry | drop, no open-loop | Week A/B |
| T21 | SB-3 malformed re-rank inputs | ValueError not TypeError | Week A merge |
| T22 | Rewrite D terminal witness | fresh/healthy/clear + agent stop + settled; person-stop cannot succeed | Week A merge |
| T23 | Lamppost/bench static e2e | no traffic regression | Week A merge |
| T24 | `rank_approach_candidates` ladder unchanged | byte-identical empty | Week A merge |

---

# Engineer acceptance checklist

- [ ] Pure re-rank: empty-tracks no-op, hysteresis, age filter, rate limit
- [ ] Wire: mid-mission re-commit with metadata; ramp untouched; watchdog frozen
- [ ] Dwell `inside`: fresh metric evidence + clearance + healthy pose/transform
      + agent stop + settled feedback; false-outside / active-brake pins
- [ ] Rewrite D: active person/TTC/obstacle brake cannot become terminal success
- [ ] Yield-advance: still seed-only; no gated emission
- [ ] Pedestrian e2e hard pass under `--runxfail` **before** removing xfail
- [ ] Empty-tracks sidewalk / lamppost e2e still green
- [ ] Crossing: zero autonomous road entry pin still green
- [ ] Formation→planner behind flag (Week B); NavigateTo unblocked without it
- [ ] No person_stop / TTC threshold relaxation in the diff
- [ ] Scrum digest published for the flip (or remaining miss)
- [ ] GSNI falsifiers (GSNI-8 table) all covered by CI pins

---

# Bottom line

D3 is the week-scale product design for the measured N11 residual: treat
commitment as temporary, arrival as dwell-verified region membership with
approach-inset clearance, pacing as seed-only memory, follow as formation
goals into the same planner NavigateTo uses, and city maps as advisory
nominees under an authenticated, authorized owner/control-channel crossing
law; transcript text alone is never authority. Geometric and safety
non-interference holds because re-rank writes only goals, dwell writes only
arrival bits, and hard monitors alone write velocity — with empty-tracks
ladder and road-entry bans preserved. It is Phase-1 shippable only after D1
P0-A/B/C/H and real P1-B/P1-D metric producer/witness gates, and does not
depend on D2 models to flip the pedestrian xfail,
and refuses any path that trades a hard stop for progress.

---

## Appendix A — Pseudocode index

| Algorithm | Section |
| --- | --- |
| `should_rerank_approach` | P2.1.2 |
| `select_recommit` | P2.1.3 |
| `clear_window_ok` | P2.1.4 |
| `maybe_rerank_on_tick` | P2.1.5 |
| `update_inside_dwell` | P2.2.2 |
| `_inside_arrival_goal_region` replacement | P2.2.3 |
| Formation control loop | P2.4.2 |
| OSM advisory path | P2.5 |
| Rewrite D verifying rule | P3.10 Rewrite D |
| Worked scenario ticks | P4.1–P4.2 |

## Appendix B — Distance arithmetic (N11 residual)

```text
end_y ≈ 2.07
polygon_y_min ≈ 2.20     → Δ_poly ≈ 0.13 m
K0_y_min ≈ 2.40          → Δ_K0 ≈ 0.33 m
committed_y ≈ 2.64       → Δ_commit ≈ 0.57 m from end
creep = 0.12 m/s
time_to_poly_at_creep ≈ 0.13/0.12 ≈ 1.08 s continuous clear
time_to_K0_at_creep ≈ 0.33/0.12 ≈ 2.75 s continuous clear
FINAL_APPROACH_HORIZON_S = 1.5 s  → can cover poly gap if clear; K0 gap
  needs either longer clear, higher effective speed after release seed,
  or re-rank to a pose that intersects a sooner clear window / shorter path
person_stop correctly blocks when agents within person_stop_m
```

## Appendix C — Why one-shot ranking loses over 240 s

Constant-velocity occupancy at commit uses horizon 3.0 s
(`traffic_aware.py:204`). Scripted agents continue for hundreds of seconds.
The quieter edge at t=0 becomes a sweep corridor at t≫3 s. Without state
update, the robot optimizes a stale objective under a correct brake —
hence near-miss-on-the-clock, not stuck-forever. Re-rank restores objective–
world consistency at ~1 Hz while stopped.

## Appendix D — Soft vs hard cost examples on the strip

```text
Candidate A: (−0.2, 2.64)  static=2.65  traffic=0.4  total≈3.45 @ commit
Candidate B: (−0.6, 2.50)  static=2.80  traffic=0.1  total≈3.00 @ T+200
             (illustrative; real numbers from digest)

At commit: A wins (lower static dominates early).
At T+200 under stream shift: B wins if traffic rise on A exceeds
  hysteresis threshold relative to commitment snapshot.
Sticky rule: B.total < commitment.total − 0.15 − 0.08.
```

## Appendix E — Interaction matrix (features × authorities)

| Feature ↓ / Authority → | person_stop | RampMemory | grid_v1 | Crossing | Arrival |
| --- | --- | --- | --- | --- | --- |
| Re-rank | may run during | must not reset | updates goal | no write | may enable |
| Inside dwell | may allow in-region | no write | no write | no write | writes A_t |
| Final-metre creep | forbidden during | seeds after clear | slew only | no write | no write |
| Formation goal | post-brake shared | N/A | owns path | no write | skill-specific |
| OSM SE2Goal | N/A | N/A | after re-ground | cannot unlock | cannot declare |

## Appendix F — Failure digest schema (A0)

```json
{
  "case": "test_go_to_the_sidewalk_with_pedestrian_traffic",
  "end_pose": {"x": 0.0, "y": 0.0},
  "committed_pose": {"x": 0.0, "y": 0.0},
  "approach_static_cost": 0.0,
  "approach_traffic_cost": 0.0,
  "approach_total_cost": 0.0,
  "person_stop_dwell_histogram_s": [],
  "clear_window_lengths_s": [],
  "creep_seed_events": [],
  "re_rank_count": 0,
  "re_rank_events": [],
  "inside_dwell_detail": null,
  "last_detail": "step_timeout",
  "budget_s": 240
}
```

## Appendix G — Explicit non-goals (reaffirmed)

- Weakening `person_stop` to make progress
- Autonomous road / crossing entry from OSM, CityWalker, or learned priors
- GNSS-as-sidewalk-membership; planar LiDAR as curb-height authority
- `proxemic_approach.reject_cost` as sole selector
- Follow-Bench / HuNavSim / MetaUrban as N11 flip criteria
- Custom social RL; Sport replacement
- Fixing P0 S0 defects (D1 owns) — D3 must not regress them

## Appendix H — Pass completion affidavit

```text
Pass 1: COMPLETE — e2e geometry reconstructed with measured poses,
        polygon bands, stop envelopes, commit ranking, arrival False,
        yield seed-only path, follow proportional defect, crossing ban.

Pass 2: COMPLETE — full algorithms for re-rank, dwell, yield preserve,
        formation seam, OSM advisory; implementable pseudocode.

Pass 3: COMPLETE — ten adversarial attacks refuted; four weak sections
        rewritten (especially Rewrite D verifying interaction).

Pass 4: COMPLETE — extended tick tables, ABI freeze, config, migration,
        risks, flip protocol, citation index (≥20), UNVERIFIED register,
        acceptance matrix, appendices A–H.

Depth bar items:
  [x] ≥3 explicit passes (4 recorded)
  [x] ≥20 file:line cites (30 in citation index)
  [x] full worked scenario with state variables and failure branches
  [x] safety/correctness argument (GSNI-1…9 + falsifiers)
  [x] complete implementable pseudocode for motion/lifecycle/arrival changes
  [x] ≥1,200 lines target (see wc -l on this file)
  [x] UNVERIFIED register + acceptance test matrix
```

---

*End of DEEP_D3_SOCIAL_CITY.md*
