# Day 59: Social Robotics in Dynamic Cities

## Mental model

Social navigation is collision avoidance plus norms: personal space, yielding, side choice, crosswalk patience, multi-party attention. Metrics that only count geometric collisions will ship a rude, scary dog that is “safe” on paper. Companion robotics is social by default—owner follow is a continuous proxemics problem.

```text
geometry:  free space, TTC, footprint
social:    who matters, how close, who yields, what looks aggressive
Parcel:    owner track + people distances + follow formation + speech
```

Software analogy: a rate limiter can keep a service “up” while still being hostile to users (thundering 429s). Likewise, a dog can avoid contact while still lunging into personal space. Social success needs different predicates than `collision_count == 0`.

## Tradeoffs and industry trends

Benchmarks: Habitat 3.0 (social rearrangement / embodied agents) and MetaUrban / MetaDrive-family urban scenes are shaping evaluation. Industry trend: learned pedestrian predictors + classical avoidance. Risk trend: averaging cultural norms into one policy and calling it universal; or trusting ORCA-like agents in sim as stand-ins for chaotic humans.

| Design choice | Tradeoff |
| --- | --- |
| Large person_stop_m | Safer/ruder; blocks crowded sidewalks |
| Aggressive gap acceptance | Efficient/scary |
| Owner-centric cost | Good companion; may inconvenience others |
| Multimodal pass-left/right | Natural; needs arbitration |
| Speech while maneuvering | Affordance for humans; duplex load / distraction |

Critical analysis: social predictors improve *expected* costs; they do not create rights to motion. A confident “pedestrian will yield” is still a proposal. Module 6 interrogation: social models observe tracks/images; they should act as cost proposers or yield flags—not motor owners; rates of 1–10 Hz; data is culture- and city-specific; Unitree transfer is about footprint and speed caps; deterministic gates remain.

## ASCII diagram

```text
  pedestrians / owner / cyclists
           |
           v
  predict + associate + reacquire
           |
           v
  social costs / follow formation
           |
           v
  DirectiveNavigator / FollowOwnerController
           |
           v
  CollisionPolicy + ReactiveSafetyPolicy
           |
           v
  CommandArbiter -> ControlManager -> Sport
           |
           v
  duplex speech (explain / yield)  [non-blocking on motion writer]
```

## Map to Parcel / Go2

Parcel still keeps hard social distance gates deterministic while research improves prediction and norms.

Codebase-relative context:

- Hard brakes: `CollisionPolicy` person/obstacle stop & slow distances (`navigation/collision.py`); `ReactiveSafetyPolicy` person envelope + owner orbit margins (`navigation/reactive_safety.py`).
- Companion behavior: `FollowOwnerController` / `FollowConfig` / prediction hooks (`navigation/follow.py`, `owner_prediction.py`)—still downstream of gates.
- Planner-side dynamic agents: `dynamic_costs.py` + `dynamic_layer.py` wiring into `grid_v1`—correct tip-in for learned predictors as *costs*, not twists.
- City research scaffold: `MetaUrbanNavEnv` + `social_nav_reward` (`navigation/envs/`); `docs/DYNAMIC_CITY_AND_BEHAVIOR.md` / `NAVIGATION_CITY.md` warn MetaUrban is not product-integrated (`use_metaurban=True` fail-closed).
- Attention / multi-stimuli: `attention/` arbiter patterns compete for gaze—not for raw torque.
- Speech norms: `DuplexCoordinator` fillers/emotes (`duplex/`) must not steal motion ownership from `CommandArbiter` during crowded navigation; explaining “I’ll wait” is cheap compared to cutting a gap.
- PlanIR invariants already name social intent: `yield_to_people`, `preserve_owner_visibility`, `keep_collision_margin` (`brain/validator.py`).
- Identity uncertainty: when owner re-ID is weak, follow should degrade (stop/search) rather than socially weave toward the wrong person—tie to Day 47 patterns and `search_owner` flows.

Classification: **adopt** tightening/monitoring of person stop/slow metrics and follow evals; **prototype** learned pedestrian predictors as cost layers behind classical planners; **shadow** MetaUrban-style episodes for ranking; **reject** end-to-end social policies that bypass reactive safety because “the predictor is confident.”

Also keep speech honest: duplex should narrate waits and yields from *gate outcomes* (“I’m waiting for space”), not from predictor bravado. That keeps social UX aligned with the same deterministic spine that protects bystanders.

Cross-city transfer is another trap: a policy tuned on campus plazas can look “polite” while cutting bike lanes elsewhere. Treat each city’s follow-bench and person-stop histograms as release evidence, not a one-time MetaUrban leaderboard screenshot. Social competence is local until proven otherwise.

## Overconfidence story

A predictor scored well on MetaUrban pedestrians. Deployed as a speed advisor, it assumed unidirectional sidewalk flow; a street performer stepped backward into a posed photo. The model’s mode was “pedestrian continues forward.” Geometry gates saved a collision; the social failure was still real—an intimidating lunge that made a bystander yell. Overconfidence was benchmark fit without chaos literacy. Parcel’s postmortem metric should include near-miss braking events (`person_slow` / `person_stop` notes), `CommandArbiter` ownership, and human interventions—not only contacts counted in sim.

## Retrieval questions

1. Why can zero collisions still mean failed social navigation for a companion dog?
2. Which Parcel policies encode person stop/slow distances today?
3. (Week-back) From Day 47/29: what should happen to motion when owner identity becomes uncertain in a crowd?

## Optional 10-minute exercise

Using `FollowConfig` and `ReactiveSafetyPolicy` defaults, sketch a crowded-sidewalk scenario with two pedestrians and the owner. Write the priority order among follow goal, person_stop, and duplex filler speech. State what logged fields prove the dog yielded (brake note, zeroed `vx`, who owned `CommandArbiter`).
