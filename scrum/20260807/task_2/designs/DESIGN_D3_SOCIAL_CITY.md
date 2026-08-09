# Design D3 — Social city companion

**Date:** 2026-08-07  
**Author role:** Opus stand-in (team design review)  
**Status:** engineer-ready proposal — not an implementation commit  
**Inputs:** [`../RESEARCH_THESIS.md`](../RESEARCH_THESIS.md),
[`../research/N3_SOCIAL_DYNAMIC.md`](../research/N3_SOCIAL_DYNAMIC.md),
[`../research/N8_CITY_OUTDOOR.md`](../research/N8_CITY_OUTDOOR.md),
[`../research/N4_PERCEPTION_LOCALIZATION.md`](../research/N4_PERCEPTION_LOCALIZATION.md),
[`../research/N6_EXECUTIVE_BEHAVIOR.md`](../research/N6_EXECUTIVE_BEHAVIOR.md),
[`../../../20260805/task_2/OPUS_N11_STATUS.md`](../../../20260805/task_2/OPUS_N11_STATUS.md),
`src/parcel_robot/navigation/traffic_aware.py`  
**Sibling designs:** D1 classical fail-closed companion; D2 shadow proposers  
**Safety status:** Not cleared for unsupervised physical motion.

---

## 0. One-line thesis

Parcel’s social-city competence is a **commitment + arrival + formation**
problem on top of working hard stops: mid-mission re-rank contested approach
poses, dwell-verify `inside` arrival, keep yield-advance seed-only, route
formation goals through the common planner, and treat OSM as advisory —
**never** autonomous road entry.

---

## 1. Goals

### 1.1 Product goals (what D3 ships)

| ID | Goal | Exit evidence |
| --- | --- | --- |
| G1 | After P0-A/B/C/H and real P1-B/P1-D witnesses, flip N11 xfail `test_go_to_the_sidewalk_with_pedestrian_traffic` on a **hard pass** without weakening `person_stop` / TTC / collision brake | `--runxfail` green with fresh metric geometry, clearance, settled feedback, agent-issued stop, and no active brake → remove `@pytest.mark.xfail` |
| G2 | Mid-mission approach re-rank (~1 Hz, hysteresis, empty-tracks no-op) while dwelling near the goal under `person_stop` | Unit + wiring pins; mission metadata `re_rank_count` |
| G3 | Dwell-based `inside` arrival via `point_in_polygon_with_clearance` + dwell timer | Unit pins for false-outside / true-inside; e2e uses same predicate as InstructNav scoring |
| G4 | Yield-advance remains **seed-only** (`RampMemory` + final-metre creep); never a gate or command source | Existing ramp safety pins stay green; no creep on `person_stop` ticks |
| G5 | Owner follow emits SE(2) formation goals → `grid_v1` (common planner), not proportional twist | Follow path uses planner; collision/TTC shared with NavigateTo |
| G6 | OSM / Overture / GNSS / CityWalker stay **advisory nomination**; metric geometry owns free space, curb-stop, arrival | Crossing requires an authenticated, authorized owner/control-channel decision; a transcript alone is insufficient; `autonomous_road_entry_blocked=True` |

### 1.2 Non-goals (explicit)

- Weakening `person_stop` to “make progress.”
- Autonomous road / crossing entry from OSM edges, CityWalker, or learned priors.
- GNSS-as-sidewalk-membership; planar LiDAR as curb-height authority.
- Wiring `proxemic_approach.reject_cost` as the sole selector (empty-tracks
  identity break); optional veto only when tracks non-empty, flag-gated, later.
- Follow-Bench / HuNavSim / MetaUrban as N11 flip criteria.
- Custom social RL; Sport replacement; MiniCPM/CityWalker as motion authority.
- Fixing P0 S0 defects (exact-zero stop, LiDAR open-loop, resume atomicity,
  safety-envelope units) — those are **D1** / Phase-0. D3 may be developed
  against labeled simulation in parallel, but cannot promote until P0-A/B/C/H
  and real P1-B/P1-D producer/witness gates are green.

### 1.3 Binding constraints (from thesis + N3/N8)

```text
HARD (metric authority):  LiDAR/footprint collision, person_stop, TTC,
                          curb-stop, MAP/ODOM health → HOLD, arrival witnesses
SOFT (rank / pace):       traffic_occupancy_cost, proxemic Gaussians,
                          preferred follow annulus/angle
ADVISORY (nominate):      OSM footway graph, Overture POI, GNSS GEO,
                          CityWalker XY, route memory
NEVER:                    advisory → occupancy free; model → Sport;
                          autonomous road entry; seed while gated
```

---

## 2. Architecture diagram

```text
                    ┌─────────────────────────────────────────┐
                    │  Language / closed intents (PlanIR)      │
                    │  NavigateTo | ApproachOwner | Follow…   │
                    └──────────────────┬──────────────────────┘
                                       │ typed goals
         ┌─────────────────────────────┼─────────────────────────────┐
         │                             ▼                             │
         │              ┌──────────────────────────┐                 │
         │              │  Goal commitment layer   │  ◄── D3 core    │
         │              │  · commit approach pose  │                 │
         │              │  · mid-mission re-rank   │                 │
         │              │  · dwell inside arrival  │                 │
         │              └────────────┬─────────────┘                 │
         │                           │ SE(2) goal                    │
         │   formation SE(2) @10–20Hz│                               │
         │              ┌────────────▼─────────────┐                 │
   OSM/  │              │  Common planner          │                 │
 CityW.  │              │  grid_v1 A* + occupancy  │ ◄── D1 writer   │
 GNSS    │              └────────────┬─────────────┘                 │
 SE2Goal │                           │ MidLevelCommand               │
 (TTL)   │              ┌────────────▼─────────────┐                 │
 ───────►│ GoalArbiter  │  Yield-advance (seed)    │                 │
 advisory│ (optional)   │  RampMemory + creep      │                 │
 only    │              │  NEVER gate / NEVER emit │                 │
         │              │  while person_stop       │                 │
         │              └────────────┬─────────────┘                 │
         │                           │                               │
         │              ┌────────────▼─────────────┐                 │
         │              │  Hard monitors (post)    │ ◄── D1 P0-A/B  │
         │              │  collision / TTC /       │                 │
         │              │  person_stop / shield    │                 │
         │              └────────────┬─────────────┘                 │
         │                           │ vx≡0 when gated               │
         │              ┌────────────▼─────────────┐                 │
         │              │  CrossingModePolicy      │ ◄── N8 contract │
         │              │  curb-stop → bound auth │                 │
         │              │  zero autonomous road    │                 │
         │              └────────────┬─────────────┘                 │
         │                           ▼                               │
         │                     Unitree Sport                         │
         └───────────────────────────────────────────────────────────┘

Tracks (CV + age_s) ──► traffic_aware.rank_approach_candidates
                     ──► soft cost only; empty tracks ⇒ static identity
```

**Authority split:** D3 owns commitment/arrival/formation *proposal shape*.
D1 owns fail-closed monitors and `grid_v1` as production writer. D2 owns
shadow `NavProposalV1` (MiniCPM / CityWalker) that may feed the same arbiter
as OSM — still advisory.

---

## 3. Detailed algorithms

### 3.1 Mid-mission re-rank (primary N11 fix)

**Problem (measured):** `safe_approach_pose` runs once at commit. Quieter
south-edge pose (~y=2.64) becomes a person-stop corridor over ~240 s.
Person-stop correctly refuses the last ~0.3 m; end pose ≈ (−0.27, +2.07).

**Pure API (stdlib, in/near `traffic_aware.py`):**

```python
@dataclass(frozen=True)
class ApproachCommitment:
    x: float
    y: float
    static_cost: float
    traffic_cost: float
    total_cost: float
    committed_at_s: float
    generation: int  # bumps on every re-commit


@dataclass(frozen=True)
class ReRankDecision:
    should_rerank: bool
    reason: str          # "noop_empty_tracks" | "band" | "dwell" |
                         # "stale_tracks" | "rate_limit" | "no_improvement" |
                         # "commit" | "unreachable"
    candidate: RankedCandidate | None = None


def should_rerank_approach(
    *,
    now_s: float,
    robot_xy: tuple[float, float],
    commitment: ApproachCommitment,
    tracks: Sequence[TrackState],
    mission_state: str,           # "running" | "person_stop_dwell" | …
    person_stop_active: bool,
    person_stop_dwell_s: float,
    last_rerank_s: float | None,
    # knobs (defaults below)
    re_rank_band_m: float = 1.75,
    re_rank_min_dwell_s: float = 1.0,
    re_rank_min_interval_s: float = 1.0,   # ~1 Hz GSCL-like
    cost_improve_eps: float = 0.15,        # absolute total_cost Δ
    hysteresis_bonus: float = 0.08,        # commitment sticky bonus
    max_age_s: float = 1.0,
    require_person_stop: bool = True,
) -> ReRankDecision:
    """Pure gate: whether to evaluate / accept a new approach pose.

    Ladder: empty or all-stale tracks ⇒ never re-rank (byte-identical static
    world). Malformed inputs raise ValueError (SB-3).
    """
    ...
```

**Implementable decision body:**

```text
FUNCTION should_rerank_approach(...):
  VALIDATE finite now_s, band, dwell, interval, eps, bonus; ages ≥ 0

  fresh ← filter tracks where age_s ≤ max_age_s
  IF fresh is empty:
    RETURN ReRankDecision(False, "noop_empty_tracks")

  IF require_person_stop AND NOT person_stop_active:
    RETURN ReRankDecision(False, "not_yielding")

  dist ← hypot(robot − commitment.xy)
  IF dist > re_rank_band_m:
    RETURN ReRankDecision(False, "band")

  IF person_stop_dwell_s < re_rank_min_dwell_s:
    RETURN ReRankDecision(False, "dwell")

  IF last_rerank_s is not None
     AND (now_s − last_rerank_s) < re_rank_min_interval_s:
    RETURN ReRankDecision(False, "rate_limit")

  RETURN ReRankDecision(True, "evaluate")   # caller ranks next


FUNCTION select_recommit(
    commitment, candidates, tracks, *, static_cost_fn, traffic_weight,
    cost_improve_eps, hysteresis_bonus, clear_window_filter=None
) → ReRankDecision:
  # Reuse Sol ranking; do not invent a second cost.
  ranked ← rank_approach_candidates(
      candidates, tracks,
      static_cost_fn=static_cost_fn,
      traffic_weight=traffic_weight,   # call-site default 2.0 when tracks
      max_age_s=..., top_k=...         # SB-5 bounds
  )
  IF ranked empty:
    RETURN ReRankDecision(False, "unreachable")

  best ← ranked[0]
  IF clear_window_filter is not None:
    # Optional week-A feasibility: prefer candidates whose CV occupancy
    # predicts clear_horizon ≥ remaining_distance / FINAL_APPROACH_CREEP_MPS
    filtered ← [c in ranked if clear_window_filter(c)]
    IF filtered: best ← filtered[0]

  # Sticky commitment: challenger must beat commitment by eps + bonus
  threshold ← commitment.total_cost − cost_improve_eps − hysteresis_bonus
  IF best.total_cost >= threshold:   # lower is better; no win
    RETURN ReRankDecision(False, "no_improvement", candidate=best)

  IF NOT statically_free(best.xy):   # same free-space as approach.py
    RETURN ReRankDecision(False, "unreachable", candidate=best)

  RETURN ReRankDecision(True, "commit", candidate=best)
```

**Wiring (`DirectiveNavigator.step`, after collision brake note known):**

```text
ON each tick with mission.goal and semantic_goal:
  tracks ← tracks_from_payload(observation.extras.get("dynamic_agents"))
             OR people_tracker → TrackState  # prefer tracker for product path
  dwell_s ← update_person_stop_dwell(cnote, now_s)

  gate ← should_rerank_approach(
      now_s, robot_xy, commitment, tracks,
      person_stop_active=(cnote == "person_stop"),
      person_stop_dwell_s=dwell_s, last_rerank_s=...
  )

  IF gate.should_rerank OR gate.reason == "evaluate":
    candidates ← sample_inside_goal_region(...)  # same free set as approach
    decision ← select_recommit(commitment, candidates, tracks, ...)
    metadata["re_rank_eval_count"] += 1
    IF decision.reason == "commit":
      mission.goal ← GoalPose(decision.candidate.x, decision.candidate.y, ...)
      commitment ← ApproachCommitment(... generation=commitment.generation+1)
      record approach_static/traffic/total_cost  # overwrite with new breakdown
      metadata["re_rank_count"] += 1
      metadata["re_rank_events"].append({t, old_xy, new_xy, costs})
      # DO NOT reset RampMemory; DO NOT clear person_stop; DO NOT seed
      # Progress watchdog: freeze stall counter on re-rank tick (like yield)

  IF tracks empty:
    ASSERT no re-rank side effects  # ladder pin
```

**Invariants:**

1. Empty / all-stale tracks ⇒ zero re-commits (ladder).
2. Re-commit updates goal pose only; never opens a gate.
3. `RampMemory` state machine unchanged across re-commit.
4. Cap ~1 Hz; hysteresis prevents flicker on near-ties.
5. Cost breakdown always attributable in mission metadata.

### 3.2 Dwell-based `inside` arrival

**Problem:** Today `_inside_arrival_goal_region` **intentionally returns
False** for `terminal_relation == "inside"` so a raw edge hit cannot
succeed. Contested strips may never yield a long clear window to the
committed *point*, yet the robot can already be **inside** the semantic
polygon (or within clearance) while yielding.

**Replace the hard `return False` with dwell verification:**

```python
@dataclass
class InsideDwellState:
    inside_since_s: float | None = None
    last_clear_or_yield_s: float | None = None

    def reset(self) -> None:
        self.inside_since_s = None
        self.last_clear_or_yield_s = None


def update_inside_dwell(
    state: InsideDwellState,
    *,
    now_s: float,
    robot_xy: tuple[float, float],
    polygon: Sequence[tuple[float, float]],
    clearance_m: float,
    collision_note: str,          # "clear" | "person_stop" | ...
    collision_brake_active: bool, # any proximity/TTC/obstacle/person brake
    metric_evidence_id: str,
    metric_evidence_age_s: float,
    pose_transform_healthy: bool,
    agent_stop_commanded: bool,
    settled_feedback: bool,
    inside_arrival_dwell_s: float = 0.75,
    max_metric_evidence_age_s: float = 0.25,
) -> tuple[bool, str]:
    """Return (arrived, detail).

    Success requires polygon+clearance membership for a continuous dwell,
    fresh independent metric evidence, healthy pose/transforms, settled
    feedback after an agent-issued stop, and no active brake.
    """
    ...
```

**Implementable body:**

```text
FUNCTION update_inside_dwell(...):
  VALIDATE finite now_s, clearance_m ≥ 0, dwell_s > 0

  IF (NOT metric_evidence_id OR metric_evidence_age_s > max_metric_evidence_age_s
      OR NOT pose_transform_healthy):
    state.reset()
    RETURN (False, "stale_or_unhealthy_geometry")

  IF collision_brake_active OR collision_note != "clear":
    state.reset()
    RETURN (False, "collision_brake")

  inside ← point_in_polygon_with_clearance(robot_xy, polygon, clearance_m)
  IF NOT inside:
    state.inside_since_s ← None
    RETURN (False, "outside")

  IF state.inside_since_s is None:
    state.inside_since_s ← now_s
    RETURN (False, "dwell_started")

  IF (now_s − state.inside_since_s) < inside_arrival_dwell_s:
    RETURN (False, "dwell_pending")

  IF NOT agent_stop_commanded OR NOT settled_feedback:
    RETURN (False, "terminal_stop_pending")

  RETURN (True, "inside_dwell_verified")
```

**Pipeline integration:**

```text
REPLACE _inside_arrival_goal_region:

  IF semantic_goal.terminal_relation != "inside":
    # existing GoalRegion.contains path for near/next_to/...
    RETURN region.contains(robot)   # unchanged

  polygon ← arrival_goal_region.polygon OR candidate.polygon
  IF polygon empty: RETURN False

  clearance ← terminal_clearance_m from metadata
              (default footprint_radius; same as approach sampler inset)

  arrived, detail ← update_inside_dwell(
      self._inside_dwell, now_s=..., robot_xy=MAP,
      polygon=polygon, clearance_m=clearance,
      collision_note=last_cnote,
      collision_brake_active=(last_cnote != "clear"),
      metric_evidence_id=perception_health.metric_evidence_id,
      metric_evidence_age_s=perception_health.metric_evidence_age_s,
      pose_transform_healthy=pose_health.ok and transform_health.ok,
      agent_stop_commanded=nav_feedback.agent_stop_commanded,
      settled_feedback=nav_feedback.settled,
  )
  metadata["inside_dwell_detail"] = detail
  metadata["inside_dwell_s"] = ...
  RETURN arrived

# On mission change / cancel / Hold: _inside_dwell.reset()
# Entering verifying still runs relation + settle witnesses (unchanged).
```

**False-success pins (must ship with the feature):**

| Case | Expected |
| --- | --- |
| Robot in street, outside polygon | `outside` — no success |
| Robot grazes polygon edge, clearance unmet | `outside` |
| Robot inside, dwell 0.2 s < 0.75 s | `dwell_pending` |
| Robot inside + `person_stop` for ≥ dwell | no success; active brake resets terminal dwell |
| Robot inside + active collision-brake | `collision_brake` — no success |
| Robot inside, clear, fresh, settled after agent stop for ≥ dwell | **success** (`inside_dwell_verified`) |
| Eval disc (K0) vs semantic polygon disagree | Use **semantic polygon + clearance** as product witness; score eval with same rule (W0-D / stratum-3) |

**Clearance default:** match approach inset
(`max(footprint_clearance_m, terminal_clearance_m)`), not `0.0`, so edge
graze cannot launder a near-miss.

### 3.3 Yield-advance (seed-only — preserve)

No redesign. Document the contract implementers must not break:

| API | May | Must not |
| --- | --- | --- |
| `RampMemory.note_stopped` | remember | return a velocity |
| `RampMemory.release` | return seed **after** caller asserts gate open | be called during `person_stop` |
| `_final_metre_creep` | floor seed to `FINAL_APPROACH_CREEP_MPS` when clear + band + predicted clear | raise creep past person-stop needs; seed on gated ticks |
| `seed_ramp` / `pending_ramp_seed_mps` | slew limiters | bypass collision brake |

**D3 tweaks (diagnostics only unless A/B proves need):**

1. Log `predicted_clear_window_s` vs `remaining_m / creep_mps` on each
   final-metre tick (feeds re-rank feasibility filter).
2. When re-rank moves the goal laterally, optionally prefer candidates with
   clear-window ≥ travel time at creep (see `clear_window_filter` above).
3. **One knob per experiment** — do not retune creep and re-rank together.

### 3.4 Formation → common planner

**Problem (P1.1 / N6):** `FollowOwnerController` `direct` mode emits
proportional twist; bypasses obstacle-aware `grid_v1`. Crowds and walls are
inconsistent with NavigateTo.

**Target control loop:**

```text
OwnerTrackV1 (confirmed) @ perception rate
        │
        ▼
FormationGoalSampler @ 10–20 Hz
  behind / side / ApproachOwner settle band
  → FollowFormationGoalV1 {x, y, yaw?, ttl, relation, generation}
        │
        ▼
DirectiveNavigator / GoalArbiter accepts as mission.goal (short TTL)
        │
        ▼
grid_v1 (+ dynamic soft costs) → MidLevelCommand
        │
        ▼
same hard monitors as NavigateTo
```

**Rules:**

1. Sampler owns preferred annulus / angle (soft). Planner owns free space.
2. Identity is enrolled multi-frame posterior (`OwnerTrackV1`) — never
   nearest-person; never MiniCPM identity.
3. `ApproachOwner` (N6 split): terminate when band held + settled + optional
   hold duration → **disable** follow channel. `FollowFormation`: persistent
   until Hold/cancel.
4. TTL on formation goals ≤ 0.2–0.5 s; stale → HOLD / acquire, not open-loop
   chase.
5. Soft import / feature flag `follow.formation_via_planner: true` for
   ladder migration; empty/disabled ⇒ legacy direct (CI label honest).

**Out of D3 week-1 critical path:** full Follow-Bench adapter (Week B in N3).
Ship the formation→planner seam so Follow-Bench can attach later.

### 3.5 OSM advisory only + no autonomous road entry

Reuse existing contracts; D3 makes them **ABI-visible** in the social-city
path:

```text
OsmWaypointProposer / CityWalker / GNSS GEO
    → SE2Goal | NavProposalV1  (source, ttl, confidence, frame)
    → GoalArbiter nomination
    → local re-ground + grid_v1
    → CrossingModePolicy gate on any edge that leaves sidewalk

CrossingModePolicy:
  sidewalk → approach curb → STOP + announce
           → authenticated, authorized owner/control-channel decision
             bound to task revision, event ID, curb-stop state, and TTL
             (a recognized transcript alone is never authorization)
           → CROSSING_AUTHORIZED (TTL)
           → metric monitor still owns collision stop
  autonomous_road_entry_blocked = True always for proposers
  allow_crossing flag ONLY from CrossingModePolicy, never from OSM/CityWalker
```

**Hard bans:**

- OSM incomplete sidewalk graph must **not** authorize road centerlines.
- GNSS east/north alone must **not** decide sidewalk membership.
- CityWalker must **not** declare arrival, free space, or crossing auth
  (gate stays off until D2 provenance; even then proposer-only).

---

## 4. Interfaces

### 4.1 Pure module extensions (`traffic_aware.py` or sibling)

| Symbol | Role |
| --- | --- |
| `ApproachCommitment` | Frozen committed pose + cost + generation |
| `ReRankDecision` | Gate result + optional `RankedCandidate` |
| `should_rerank_approach(...)` | Band/dwell/rate/age/empty-tracks gate |
| `select_recommit(...)` | Rank + hysteresis + optional clear-window filter |
| `InsideDwellState` / `update_inside_dwell(...)` | Dwell arrival (may live in `approach.py` if polygon-coupled) |

All stdlib-pure where possible; clocks caller-supplied; `ValueError` on
malformed input (SB-3). Empty-tracks identity pinned by tests.

### 4.2 Pipeline / approach wiring

| Seam | Change |
| --- | --- |
| `approach.safe_approach_pose` | Unchanged ranking API; expose candidate sampling helper for re-rank reuse |
| `DirectiveNavigator._commit_semantic_candidate` | Store `ApproachCommitment` + initial costs in mission metadata |
| `DirectiveNavigator.step` | Call re-rank gate; dwell `inside` trigger |
| `RampMemory` ownership | Unchanged; soft import retained |
| Mission metadata | `re_rank_count`, `re_rank_events`, `inside_dwell_*`, existing `approach_*_cost` |

### 4.3 Formation / follow

| Contract | Fields (minimum) |
| --- | --- |
| `FollowFormationGoalV1` | `x, y, yaw_optional, relation, distance_m, issued_s, expires_at, owner_track_id, generation, frame=MAP` |
| Config | `follow.formation_via_planner`, `formation_rate_hz`, `formation_ttl_s` |

### 4.4 City advisory

| Contract | Rule |
| --- | --- |
| `SE2Goal` / `NavProposalV1` | TTL + source + never Sport |
| `CrossingDecision.allow_crossing_edges` | Sole unlock for crossing edges |
| Road keepout | Metric after localization; OSM polygon is seed only |

### 4.5 Perception dependencies (N4 handoff — not blocking week-1 sim)

| Need | Week-1 sim | Field |
| --- | --- | --- |
| Dynamic tracks | `extras['dynamic_agents']` + people tracker | Fast det + track; `age_s` mandatory |
| Pose | Truth labeled-sim OK for N11 e2e | FAST-LIO2/Point-LIO; HOLD on LOST |
| Sidewalk semantics | Scene polygons | Fast seg + elevation for curb (not planar-only) |
| Owner | Sim `OwnerTrack` | Enrolled ReID multi-frame |

D3 week-1 N11 flip runs on R0/R1 sim. Do not claim field social competence
from that flip.

---

## 5. Occupied-sidewalk tick narrative

Scenario: `go to the sidewalk` with scripted pedestrians on y≈2.85–3.55
(the N11 e2e). Robot at ≈(−0.27, 2.07), committed goal ≈(−0.2, 2.64),
`person_stop` active, NavigateTo budget remaining.

```text
t = T0  (person_stop tick, robot outside polygon, dwell accumulating)
  apply_collision_brake → (0, 0, "person_stop")
  RampMemory.note_stopped(T0)           # remembers; emits nothing
  person_stop_dwell_s += dt
  should_rerank? band OK, dwell < 1.0s → reason="dwell"
  inside dwell? outside polygon → False
  MidLevelCommand(vx=0, vy=0, stop=False, note="…|person_stop")
  progress watchdog: freeze stall (yield)

t = T0+1.2s  (still person_stop, dwell ≥ 1.0s, last_rerank None)
  tracks fresh (age_s < 1.0)
  should_rerank → evaluate
  sample polygon free set; rank_approach_candidates(traffic_weight=2.0)
  best total_cost + eps + bonus < commitment → COMMIT new pose
    e.g. shift laterally along strip to quieter inset (y still ≥ 2.2)
  metadata.re_rank_count = 1
  RampMemory NOT reset; still stopped
  goal updated; grid will replan next clear tick
  MidLevelCommand still zero (gate holds)

t = T0+1.4s  (brief clear window — pedestrian gap)
  apply_collision_brake → clear
  RampMemory.release → seed; seed_ramp(seed); maybe final_metre_creep
  vx = max(cmd, min(seed, max_vx)) still post-brake
  robot advances toward NEW commitment
  person_stop_dwell_s reset on clear

t = T0+2.0s  (another agent sweeps; person_stop again)
  stop exact; note_stopped
  if still outside: re-rank rate-limited to ~1 Hz
  if robot now inside polygon with clearance:
    inside_since_s ← T0+2.0; dwell_pending

t = T0+2.8s  (person_stop while inside)
  update_inside_dwell → (False, "collision_brake")
  wait for a clear metric observation; issue exact-zero terminal stop
  require fresh evidence + healthy pose/transform + settled feedback
  update_inside_dwell after clear hold → (True, "inside_dwell_verified")
  mission.status → verifying
  arrival_trigger = "goal_region" (or goal_region_or_pose)
  terminal verification: relation inside + settle witnesses
  task → succeeded when witnesses pass
  NEVER: creep raised; NEVER: person_stop distance shrunk;
  NEVER: OSM flipped allow_crossing
```

**Failure modes still allowed (honest):**

- All candidates stay hot → re-rank `no_improvement` / `unreachable`; robot
  keeps yielding until timeout (better than false success).
- Clear windows too short even to re-ranked pose → timeout; publish digest;
  do **not** flip xfail.

---

## 6. Compose with D1 / D2

| Concern | D1 (classical fail-closed) | D2 (shadow proposers) | D3 (this) |
| --- | --- | --- | --- |
| Exact-zero stop / LiDAR HOLD / resume atomicity | **Owns** | Consumes | Must not regress; may assume fixed |
| `grid_v1` production writer | **Owns** | Challenger proposals into arbiter | Formation + NavigateTo share it |
| `NavProposalV1` ABI | Consumer | **Owns** MiniCPM/CityWalker shadow | OSM / formation goals use same nomination shape |
| Soft social cost / re-rank / dwell | — | Must not bypass | **Owns** |
| Crossing / road ban | Policy pins | CityWalker must not unlock | **Enforces** in social-city path |
| Shared ABI freeze | Pose/Perception/Safety | Proposal schema | `ApproachCommitment`, `FollowFormationGoalV1`, dwell metadata |

**Composition rule for Phase-1 ship:**

```text
Ship order: D1 P0 substrate → D3 N11 residual (+ formation seam)
            → D2 shadows behind TTL (optional for N11 flip)
```

D3 **must not** require D2 models to flip the pedestrian xfail. D3 **must
not** weaken D1 monitors to pass it.

**Shared review questions (designs/README):**

1. Phase-1 shippable: D1 + D3 week-A (re-rank + dwell + seed-only).
2. Phase-2: formation→planner default-on, Follow-Bench, Nav2 sidecar,
   D2 shadows.
3. Shared ABI: `NavProposalV1` / `SE2Goal`, hard-monitor post-shaper hook,
   mission metadata cost/dwell/re_rank fields, crossing allow flag ownership.

---

## 7. Evaluation

### 7.1 N11 flip protocol (binding)

```bash
# Before claiming green:
.parcel/bin/pytest tests/test_traffic_aware.py \
  tests/test_approach_traffic_wiring.py \
  tests/test_navigation.py -q

.parcel/bin/pytest -m slow \
  tests/test_voice_nav_e2e.py::test_go_to_the_sidewalk_with_pedestrian_traffic \
  -v --runxfail
```

**Flip `@pytest.mark.xfail` only if:**

1. P0-A/B/C/H and real P1-B/P1-D producer/witness gates are green.
2. Hard pass (not xpass flake): `states == succeeded`; fresh independent
   metric evidence proves polygon membership with clearance; healthy pose and
   transforms are recorded; settled feedback acknowledges an agent-issued
   exact-zero stop; and no collision/person brake is active.
3. Telemetry shows either `re_rank_count ≥ 1` **or**
   `inside_dwell_detail == inside_dwell_verified` (attributable mechanism).
4. No change to `person_stop_m` / TTC thresholds / collision brake semantics.
5. Empty-tracks sidewalk e2e still passes (ladder).
6. Digest freezes task/revision and evidence IDs, evidence ages, end pose,
   clearance, stop/settled acknowledgements, `approach_*_cost`, dwell
   histogram, re-rank events, and clear-window stats → scrum note.

**If still fail:** keep xfail; update reason with new end pose and which
gate fired (`no_improvement`, timeout, verify fail). Do not ship a
“progress” hack.

### 7.2 Unit / wiring matrix

| Test | Pins |
| --- | --- |
| `should_rerank` empty tracks | no-op |
| `should_rerank` band / dwell / rate | reject |
| `select_recommit` hysteresis | sticky commitment |
| `update_inside_dwell` false-outside | no success |
| `update_inside_dwell` person-stop-inside | no success; reset |
| `update_inside_dwell` clear/fresh/settled agent-stop | success after dwell |
| Wiring: re-rank does not reset ramp | ramp state preserved |
| Wiring: re-rank freezes watchdog | no false stall |
| Formation flag off | legacy direct behavior labeled |

### 7.3 What this eval does **not** prove

| Suite | Not claimed by N11 flip |
| --- | --- |
| Follow-Bench | RPF comfort / ASR |
| HuNavSim / MetaUrban | Interactive humans / city density |
| Field Go2 | Localization, curb physics, Sport tracking |
| CityWalker 77.3% | Parcel readiness |

### 7.4 Sibling gates (disposition, not blockers)

N13 static near-misses (bench ~0.21 m, lamppost ~0.072 m): same final-approach
family **without** traffic. After N11 flip, triage shared dwell-band helper
vs “not this card.” Do not launder static misses as traffic wins.

---

## 8. Migration plan

### Week A — N11 residual (critical path)

| Day | Work | Owner surface |
| --- | --- | --- |
| A0 | Freeze failing artifact digest (pose, costs, dwell, clear windows) | scrum note |
| A1 | Pure `should_rerank_approach` + hysteresis + tests | `traffic_aware` (+tests) |
| A2 | Wire mid-mission re-commit in `DirectiveNavigator`; metadata; watchdog | `pipeline.py` |
| A3 | Dwell `inside` arrival + false-success pins | `pipeline` / `approach` |
| A4 | Pedestrian e2e `--runxfail`; flip **only** on hard pass | `test_voice_nav_e2e.py` |
| A5 | N13 disposition writeup | scrum |

### Week B — formation seam + social metrics spine

| Day | Work |
| --- | --- |
| B0–B1 | `FollowFormationGoalV1` + flag; formation sampler → planner |
| B2–B3 | Follow-Bench license spike + oracle lane smoke (eval only) |
| B4–B5 | Promotion rules in eval README; no N11 dependency |

### Week C — optional (after A flip)

- Clear-window feasibility filter on re-rank.
- Soft proxemic veto when tracks non-empty (flag).
- Crowd-cost normalization on `dynamic_layer` (P1.3).
- Camera Follow-Bench lane; MetaUrban terms spike.

### Config / feature flags

```yaml
# configs/navigation/default.yaml (sketch)
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
  inside_dwell:
    enable: true
    dwell_s: 0.75
    clearance_mode: approach_inset   # not zero
  yield_advance:
    seed_only: true                  # hard-coded contract; not a soft disable of gates
  follow:
    formation_via_planner: false     # default off until B green
  city:
    osm_advisory_only: true
    autonomous_road_entry: false     # immutable product law
```

### Rollout

1. Flags default **on** for re-rank + inside dwell in sim/CI once tests green.
2. Formation planner default **off** until paired follow regression passes.
3. Physical profiles: D3 social features require D1 P0-B pose/LiDAR health;
   otherwise HOLD — no open-loop social creep outdoors.

---

## 9. Risks

| ID | Risk | Mitigation |
| --- | --- | --- |
| R1 | Re-rank flicker near cost ties | Hysteresis bonus + min interval + generation telemetry |
| R2 | Dwell launders near-misses outside true semantics | Polygon + approach inset clearance; forbid eval-disc-only success |
| R3 | Creep + re-rank interaction | Log both; one knob per A/B; never seed while gated |
| R4 | Re-rank thrash CPU on large candidate sets | `top_k` (SB-5); ~1 Hz cap |
| R5 | Tracker vs `dynamic_agents` oracle mismatch | Prefer people tracker on product path; sim may use extras with label |
| R6 | Formation→planner latency / oscillation | Short TTL; rate limit; HOLD on stale owner |
| R7 | OSM / CityWalker treated as free space | Advisory ABI + crossing allow sole ownership + CI pins |
| R8 | Pressure to weaken person-stop to flip xfail | Explicit non-goal; flip protocol forbids threshold changes |
| R9 | Claiming field competence from R0 e2e | Honesty ladder (N4); flip ≠ outdoor certificate |
| R10 | D1 P0 unfinished → D3 A/B confounded | Sequence D1 first; quarantine claims if P0 open |

---

## 10. File-level implementation map

| File | D3 change |
| --- | --- |
| `navigation/traffic_aware.py` | `ApproachCommitment`, `should_rerank_approach`, `select_recommit` |
| `navigation/approach.py` | Export sampling helper; optional dwell helpers; keep ranking |
| `navigation/pipeline.py` | Re-rank wire; replace inside `return False`; dwell state; metadata |
| `navigation/follow.py` | Formation goal sampler behind flag |
| `maps/crossing.py` / `waypoints.py` | No semantic change; pin advisory + allow_crossing ownership in tests |
| `tests/test_traffic_aware.py` | Pure re-rank / dwell pins |
| `tests/test_approach_traffic_wiring.py` | Re-commit wiring + ramp preservation |
| `tests/test_voice_nav_e2e.py` | Flip xfail on hard pass only |
| `configs/navigation/default.yaml` | `social_city` block |

**Do not rewrite** Sol’s pure `traffic_aware` ranking/ramp contracts; extend.

---

## 11. Acceptance checklist (engineer)

- [ ] Pure re-rank: empty-tracks no-op, hysteresis, age filter, rate limit
- [ ] Wire: mid-mission re-commit with metadata; ramp untouched; watchdog frozen
- [ ] Dwell `inside`: fresh metric geometry + clearance + dwell + settled
      agent-stop feedback; false-outside / active-brake pins
- [ ] Yield-advance: still seed-only; no gated emission
- [ ] Pedestrian e2e hard pass under `--runxfail` **before** removing xfail
- [ ] Empty-tracks sidewalk / lamppost e2e still green
- [ ] Crossing: zero autonomous road entry pin still green
- [ ] Formation→planner behind flag (Week B); NavigateTo path unblocked without it
- [ ] No person_stop / TTC threshold relaxation in the diff
- [ ] Scrum digest published for the flip (or for the remaining miss)

---

## 12. Bottom line for team review

**D3 is the week-scale product design for the measured N11 residual:** treat
commitment as temporary, arrival as dwell-verified region membership, pacing
as seed-only memory, follow as formation goals into the same planner that
NavigateTo uses, and city maps as advisory nominees under an authenticated,
authorized owner/control-channel crossing law. A transcript alone is not
authorization. It is Phase-1 shippable **after** D1 authority fixes and real
metric producer/witness gates, does
**not** depend on D2 models to flip the pedestrian xfail, and refuses any
path that trades a hard stop for progress.
