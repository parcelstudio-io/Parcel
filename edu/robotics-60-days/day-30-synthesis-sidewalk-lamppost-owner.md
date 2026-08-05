# Day 30: Synthesis — Sidewalk, Lamppost, and Owner-Orbit

## Mental model

Module 3 ends by tracing one companion city loop end-to-end: language becomes a typed semantic goal, perception yields candidates with uncertainty, geometry picks a collision-cleared terminal pose, the rolling map + A* propose a route, local control emits velocities, and **predicates** — not command budgets — decide success.

```text
directive -> SemanticGoal -> candidates -> safe GoalPose
         -> grid_v1 (log-odds + A* + soft dynamics)
         -> MidLevelCommand -> gates -> locomotion
         -> verify relation still true + settled motion
```

Three product vignettes share that spine: walk onto/inside the sidewalk, stand near the lamppost, orbit the owner.

## Software-engineering analogy

This is a **workflow engine with typed stages and compensating transactions**:

- Parser/grounding = request validation.
- Search/re-ground = retries with bounded attempts (`max_semantic_replans`).
- Arrival verification = read-after-write consistency check on the world.
- Reactive brake = out-of-band kill switch independent of the workflow.

The LLM (later modules) may propose the directive; it never supplies the path or torque.

## ASCII diagram

```text
  "go to the sidewalk" / "wait by the lamppost" / "walk around me"
              |
              v
     goals.py / spatial.py parse
              |
              v
     semantic_map candidates (camera tracks)
              |
              v
     search.py (rotate) + approach.safe_approach_pose
       or SpatialBehaviorController (orbit)
              |
              v
     GridNavigator + RollingGridPlanner      owner soft costs / reactive
              |
              v
     HeadlessCityQualityHarness / living city predicates
```

## Map to Parcel / Go2 — three tasks

**Sidewalk (region / inside):**  
`SemanticGoal` with region relation → polygon candidate → `safe_approach_pose` samples an interior point with edge/obstacle clearance (`instructnav.relations.nearest_point_in_region` fallback) → `grid_v1` routes → arrival only if a fresh candidate still satisfies the relation.

**Lamppost (object / near):**  
Object stand-off ring via `next_to_placement` / near relation; may require support polygon (stand on sidewalk near lamppost). Needs two confidence-qualified observations by default.

**Owner orbit:**  
`parse_spatial_intent` / `orbit_owner` → `SpatialBehaviorController` with radius bounds (default ~1.6 m), align hysteresis, `minimum_safe_orbit_radius` vs reactive stop distance; `apply_reactive_safety(..., owner_orbit=True)` adjusts owner interaction. Progress is angular, not “path length consumed.”

**Codebase anchors (synthesis):**

- `navigation/goals.py` → `navigation_directive_from_text`, `semantic_goal_from_directive`, `SemanticGoal`
- `navigation/pipeline.py` → `DirectiveNavigator.start` / `step` → `MidLevelCommand`
- `navigation/semantic_map.py` → `ObservationSemanticMap`, `SemanticCandidate`
- `navigation/search.py` → bounded scan; `approach.safe_approach_pose`
- `navigation/grid_navigator.py` + `grid_planner.RollingGridPlanner`
- `navigation/spatial.py` → `SpatialBehaviorController`, `orbit_owner`
- `navigation/dynamic_layer.py` + `follow.py` / `search_owner.py` when people/owner move
- `perception.PerceptionContract` — camera+LiDAR contract
- `instructnav.relations` / optional `resolve_grounding` / `SemanticMemory`
- Eval: `headless_city.HeadlessCityQualityHarness`, `tests/test_headless_city_tasks.py`, `tests/test_city_orbit_clearance.py`
- Spec: `docs/NAVIGATION_CITY.md` end-to-end stack + semantic goal design

## Tick-by-tick checklist (all three tasks)

Use this as a code-reading spine:

1. **Parse** — `navigation_directive_from_text` / `parse_spatial_intent` (reject negation/hypotheticals).
2. **Ground** — `ObservationSemanticMap` or owner track; optional `instructnav` recovery.
3. **Terminal geometry** — `safe_approach_pose` or orbit radius selection with clearance.
4. **Map/plan** — `RollingGridPlanner` log-odds + A*; soft dynamics if people present.
5. **Track** — rotate-first waypoint control to `MidLevelCommand`.
6. **Gate** — collision brake + reactive/TTC.
7. **Verify** — fresh candidate still satisfies relation / orbit progress; measured settle.

`HeadlessCityQualityHarness` is the daily proof for sidewalk/lamppost-style directives; orbit clearance has dedicated tests. Neither replaces Sport tracking on hardware.

## Module 3 habits to keep

- Uncertainty is part of the API (`confidence`, log-odds, freshness), not a log line.
- Camera proposes semantics; LiDAR proposes free space; odom is drifting glue.
- Soft dynamic costs bend A*; reactive gates own collision vetoes.
- Completion is a world predicate (Day 01 state kinds), never command-budget exhaustion.
- Mapping without SLAM is honest local competence — name it accurately in design docs.

## Failure story (integrated)

“Sit by the lamppost then circle me” was marked done when navigation emitted stop and the orbit skill finished its yaw budget. Under partial occlusion the lamppost candidate was a signpost; odom slip extended the orbit; a pedestrian soft-cost failed to bend the cached route until the reactive gate slammed brakes mid-circle. Postmortem checklist: (1) semantic verification on fresh candidates, (2) measured progress for orbit radians, (3) dynamic replan every tick when tracks exist, (4) never equate Sport ack with predicate success (Day 01).

## Worked contrast

| Task | Semantic object | Terminal check | Motion owner |
| --- | --- | --- | --- |
| sidewalk | region polygon | inside + clear + settled | `DirectiveNavigator` + `grid_v1` |
| lamppost | object candidate | near/stand-off + support | same |
| orbit | owner track | revolutions/progress + clearance | `SpatialBehaviorController` |

Shared infrastructure: `PerceptionContract`, calibrated LiDAR when mapping, reactive safety always. Divergent infrastructure: orbit may idle the grid planner while still needing collision envelopes around the owner.

## Retrieval questions

1. Name the stages from directive to `MidLevelCommand` for “go near the lamppost.”
2. How does sidewalk-inside sampling differ from lamppost-near stand-off in `safe_approach_pose`?
3. (From Day 26) Why can a successful headless sidewalk run still fail on a long physical loop without SLAM?

## Optional 10-minute exercise

Read `docs/NAVIGATION_CITY.md` end-to-end diagram, then skim `DirectiveNavigator.step` and `safe_approach_pose`. For one directive (`walk to the sidewalk` or `orbit_owner`), list the symbol that owns: parse, ground, plan, track, verify. Mark any step that is still simulator-oracle today.
