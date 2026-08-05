# Day 29: Dynamic Obstacles, Owner Tracking, and Social Motion

## Mental model

Static occupancy is not enough in a city. People move. Parcel splits the problem:

1. **Hard geometry** — LiDAR occupancy / inflation (do not plan through walls).
2. **Soft predicted costs** — constant-velocity Gaussians for tracked agents (prefer to go around future occupied space).
3. **Authoritative reactive gates** — proximity / TTC that can only slow or stop, never release a stop.
4. **Owner as special case** — follow/orbit must not treat the owner as a lethal wall, but must still respect personal space.

```text
tracks -> CV rollout -> additive A* cost (soft)
owner track -> follow / search / lower-weight lobe
reactive gate -> last-millisecond veto on every source
```

Data association (which blob is which person) and occlusion/reacquisition are first-class failure modes.

## Software-engineering analogy

- Soft dynamic layer ≈ **degradable QoS hints** to the scheduler (A*).
- Reactive TTC/proximity ≈ **kernel hard limit** that user space cannot raise.
- Owner weight < stranger weight ≈ priority inheritance so the followee is not starved/blocked as an obstacle.
- Lost owner → `SearchOwner` ≈ lease expiry then bounded rediscovery, not infinite gossip.

## Light equations

Constant-velocity prediction:

```text
x(t) = x0 + vx t
y(t) = y0 + vy t
```

Soft cost: decaying Gaussians along the rollout (`agent_cost_at`), clipped to `[0,1]`, scaled by `dynamic_agents.weight`. Owner uses `owner_weight` (0.6 vs 2.5 default strangers).

TTC: earliest circle-circle contact time under relative CV motion (`time_to_collision_s`) — used to scale commands, not to invent free space.

## ASCII diagram

```text
  stranger track ----CV---- soft cost lobes ----+
                                                +--> A* each tick
  owner track -- lower weight lobe -------------+
       |
       +--> FollowOwnerController / SearchOwnerController

  ALL commands --> reactive_safety / TTC gate --> Sport
```

## Map to Parcel / Go2

From `docs/NAVIGATION_CITY.md`:

- Up to 16 validated tracks; horizon 2.0 s; window 6 m; rebuild + replan every tick while active.
- Malformed track payload: log and disable soft layer for that tick — do not crash the runtime.
- Follow: `FollowOwnerController` + `OwnerMotionPredictor` (`lead_s=0.6`); lost for 3 s can compile `SearchOwner` (priority 35): last-seen → sweep → frontiers; give up ~45 s.
- Orbit: `SpatialBehaviorController` with `orbit_owner`, clearance via `minimum_safe_orbit_radius`.
- Honesty: no ORCA, no learned intention model, no guarantee soft cost changes the route.

**Codebase anchors (dynamics / owner):**

- `navigation/dynamic_costs.py` → `AgentTrack`, `agent_cost_at`, `time_to_collision_s`
- `navigation/dynamic_layer.py` → `DynamicAgentCostConfig`, `tracks_from_payload`, `merged_cost_mask`, `time_to_collision_verdict`
- `navigation/follow.py` → `FollowOwnerController`, `FollowPredictionConfig`
- `navigation/search_owner.py` → `SearchOwnerController`, `SearchOwnerConfig`
- `navigation/spatial.py` → `SpatialBehaviorController`, `orbit_owner`
- `navigation/reactive_safety.py` → `apply_reactive_safety(..., owner_orbit=...)`
- Config: `configs/navigation/models/grid.yaml` → `dynamic_agents.*`
- Eval: `evals/companion_nav/` follow/search gates; headless city for semantic tasks

## Tick-by-tick in Parcel

When `observation.extras` carries agent tracks, `GridNavigator._refresh_dynamic_costs` builds an additive mask via `merged_cost_mask` and forces A* every tick. Owner tracks also feed follow/orbit/search behaviors at the arbitration layer with their own priorities. The reactive gate still sees nearest social candidate (including owner) and can stop translation even if A* routed through a soft lobe. Personal space is therefore layered: soft preference in planning, hard veto in safety. Occlusion handling is explicit in `SearchOwnerController` phases — do not invent unbounded wandering as “social intelligence.”

## Failure story

A crowd demo treated soft costs as hard walls. The dog froze in a corridor of mild Gaussians while the reactive gate was clear. Opposite bug: disabled owner lobe weight so follow “worked,” then A* routed through the owner’s future path and relied on the brake. Fix: keep soft≠hard separation, owner_weight < stranger weight, and never let planning authority override the reactive veto.

## Social motion without theatre

Personal space is encoded as geometry and costs, not as personality text. Owner follow formations (direct / behind) adapt speed with confidence; search is time-bounded. Pedestrians get soft future costs; they do not get a negotiation protocol. When writing demos, say “bounded CV prediction + reactive TTC,” not “understands crowds.” That honesty keeps Module 6 research comparisons grounded.

## Association and reacquisition

Wrong data association (swapping two pedestrians, or locking onto a stranger as owner) is more dangerous than mild range noise. Parcel’s simulator tracks are pre-associated; hardware must add explicit identity confidence and loss timeouts. `SearchOwnerController` encodes the product policy when identity/geometry is lost: last pose, sweep, information-gain frontiers, then hold. Copy that boundedness into any learned re-ID module you try later.

TTC verdicts scale admitted commands down; they cannot unsay a proximity stop. That asymmetry is intentional: social comfort is soft, collision prevention is hard.

## Retrieval questions

1. Why are dynamic tracks soft costs instead of painted occupied cells?
2. What happens after the owner is lost for three seconds in the default brain-enabled runtime?
3. (From Day 25) How does prediction confidence change follow translation?


Read `docs/NAVIGATION_CITY.md` “Dynamic people and collision handling” once after the code: it states the non-goals (no ORCA, no learned intentions) as clearly as the features.

## Optional 10-minute exercise

Open `dynamic_costs.agent_cost_at` and `grid.yaml` `dynamic_agents`. Sketch one tick: payload → `tracks_from_payload` → `merged_cost_mask` → A*. Note the owner_weight special case.
