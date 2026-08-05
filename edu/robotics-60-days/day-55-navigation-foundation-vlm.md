# Day 55: Navigation Foundation Models and Vision-Language Navigation

## Mental model

Vision-language navigation (VLN) and navigation foundation models aim to turn language and egocentric sensing into movement through large spaces. The decisive architectural fork is the action interface:

```text
unsafe shape:   language + pixels -> motor / body-velocity authority
safer shape:    language + pixels -> waypoint / topology / subgoal
                then classical local planning + shields move the body
```

A waypoint is a *suggestion about where*. A motor command is a *permission to push energy into the world*. Parcel should almost always buy the first and rent the second from deterministic stacks. Software analogy: a search-ranking service may propose URLs; only the browser’s same-origin and permission checks may navigate. Fluency about “the cafe on the corner” is ranking. Clearing a crosswalk is permission.

## Tradeoffs and industry trends

Trends that matter:

- Topological maps + learned subgoals (image nodes, frontiers, landmarks) scale better than metric SLAM alone for “take me to the pharmacy vibe” tasks.
- NoMaD / CityWalker / NaVILA-class ideas (see Parcel `docs/DEPENDENCIES.md`) push generalist navigation with vision and language.
- End-to-end “pixels to twist” policies look magical in empty halls and fragile in dynamic cities.
- Evaluation is migrating from static VLN R2R-style datasets toward dynamic pedestrians and urban layouts (Habitat 3.0, MetaUrban—Day 59).

| Interface | What you gain | What you still need |
| --- | --- | --- |
| Discrete waypoint in map/odom | Auditability, shieldability | Local avoidance, progress monitors |
| Topological node hop | Long-range memory | Edge feasibility, recovery |
| Dense cost-map edit | Soft preferences | Hard collision constraints |
| Direct `vx,vy,vyaw` | Short path to demo | Proof against people + loco coupling |

Critical design choice: **latency budget split**. A foundation model that rethinks the global subgoal every 200–1000 ms is fine. A model that owns the 20 Hz local twist under partial LiDAR is not. Industry demos often collapse those loops for video; Parcel must not.

Module 6 interrogation for a nav foundation model:

1. **Observe?** RGB often; sometimes depth; rarely Parcel-grade LiDAR+owner track fusion.
2. **Act?** Prefer models that emit waypoints / paths; treat twist heads as research.
3. **Rate/latency?** Subgoal at 1–5 Hz is plenty; local shield stays faster.
4. **Data/compute?** Huge traversal datasets; fine-tune on your city still required.
5. **Unitree transfer?** Body plan transfers better than gait; keep Sport underneath.
6. **Safety layer?** Collision gate, TTC, speed caps, stop-on-track-loss—non-optional.

## ASCII diagram

```text
  "meet me at the corner cafe"
           |
           v
  VLN / nav foundation model
           |
           v
   candidate waypoints / graph edges
           |
           v
     GoalArbiter / ProposerBus   <--- classical frontier / follow goals
           |
           v
   metric local planner (grid_v1 A* family)
           |
           v
   collision / TTC / reactive shields  --->  bounded velocity
           |
           v
        ControlManager -> Unitree Sport
           |
           v
      measured progress; replan if stale / blocked / owner lost
```

## Map to Parcel / Go2

Parcel already thinks in proposers and arbiters. That is the correct docking port for navigation foundation models.

Codebase-relative context (foundations stay deterministic while research swaps proposers):

- Dock at `SE2Goal` / `ProposerBus` / `GoalArbiter` (`instructnav/arbiter.py`): TTL expiry and lethal-cost veto stay on while you hot-swap sources.
- Winner still feeds classical consumers inside `DirectiveNavigator` (`navigation/pipeline.py`); `GoalArbiter` docs state `grid_v1` A* remains the sole consumer of the winner.
- `ModelRegistry` (`navigation/registry.py`) already lets nav “models” be selected by id (`stub_v0`, experiment bundles)—foundation weights should look like another registered proposer/model, not a Sport bypass.
- Local vetoes stay on: `apply_collision_brake` (`navigation/collision.py`), runtime `apply_reactive_safety` (`navigation/reactive_safety.py`), then `CommandArbiter` (`core/arbiter.py`) + `ControlManager` (`control/manager.py`).
- Owner-follow competence lives in `FollowOwnerController` (`navigation/follow.py`)—a VLN model should propose, not replace follow’s progress monitors.
- Dynamic agents already enter planning via `dynamic_costs` / `dynamic_layer.py` on `grid_v1`; social predictors tip in there as costs, not as motor authority.
- `MetaUrbanNavEnv` is offline/fail-closed for vendor MetaUrban (`docs/NAVIGATION_CITY.md`); sim success ≠ Sport authority.
- Duplex may narrate “heading to the cafe” via `DuplexCoordinator`; speech must not outrank `CommandArbiter` TTLs while crossing.

Guidance: **adopt** waypoint-level authority separation now; **prototype** FM → `SE2Goal` with confidence/TTL; **shadow** log proposals vs human interventions on real outings; **reject** twist heads that skip shields because confidence is high. Foundations slow-think; shields fast-veto.

## Overconfidence story

A VLN model trained on indoor instruction-following achieved high success in simulation halls. Wired to body velocity, it entered a crosswalk while narrating a correct final destination—the language goal was fine; the *timing* relative to traffic lights and pedestrians was untrained. Stakeholders trusted the fluent instruction grounding (“it knew where the cafe was”) and underweighted the missing urban dynamics model. Overconfidence was semantic: correct place names, wrong permission to move. The fix that would have matched Parcel’s spine: emit an `SE2Goal` with short `ttl_s`, let `GoalArbiter` and `apply_reactive_safety` refuse motion when people enter the stop envelope.

## Retrieval questions

1. Why is a waypoint proposal safer than a learned motor policy even if both have the same average success rate in an empty map?
2. How should a nav foundation model connect to Parcel’s `GoalArbiter` / `ProposerBus` without owning Sport?
3. (Week-back) From Day 28/30: what local navigation responsibilities remain after a global waypoint is chosen?

## Optional 10-minute exercise

Write an interface sketch aligned to `SE2Goal`: `source`, `pose`/`waypoints`, `confidence`, `ttl_s`, `priority`. List five rejection reasons (TTL expiry, lethal cost, stale owner track, person_stop, E-stop). State the maximum mid-level speed allowed even when confidence is 0.99 (`SafetyLimits` / `ControlLimits` clamps still apply).
