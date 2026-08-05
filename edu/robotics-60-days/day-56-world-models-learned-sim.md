# Day 56: World Models and Learned Simulation

## Mental model

A world model predicts future observations (or latent states) given actions. Model-based planning then rolls out imagined futures to choose actions. The senior-SE analogy is a load-test digital twin or a record/replay service: excellent for exploring failure modes and ranking candidates—dangerous if you treat simulated green as a production SLA.

```text
o_t, a_t  -->  world model  -->  ô_{t+1..t+H}
                 |
                 +--> planner / policy search in imagination
                 +--> synthetic experience for IL/RL
                 +--> offline eval / scenario mining
```

Inaccuracy is not a footnote. A world model that under-predicts pedestrian aggression, wet-tile slip, or LiDAR multipath manufactures false confidence—the same class of bug as a mock HTTP client that always returns 200 while production times out.

## Tradeoffs and industry trends

Trends: video/world models for robot planning; learned sims to cut real teleop cost; “evaluate policies in imagination before deploy.” Counter-pressure: the reality gap (Day 37) does not vanish because the simulator is neural. Generative rollouts optimize for visual plausibility unless you explicitly train and validate against the sensors you will use for safety.

| Use | Valuable when | Toxic when |
| --- | --- | --- |
| Scenario generation | Diversifies rare encounters | Treated as coverage proof |
| Offline policy ranking | Correlates with real metrics | Replaces hardware gates |
| Short-horizon prediction | Aids local foresight | Used as collision certificate |
| Full closed-loop control via imagined reward | Research curiosity | Sidewalk deployment |

Design choice: predict **which channels**? RGB-only dreams will miss geometric hazards Parcel’s LiDAR gates care about. Latent-only dreams are even harder to audit. Prefer world models that can be scored against logged `nearest_person_m` / obstacle ranges and `RobotMotionState`, not only against pretty video FID.

Module 6 interrogation:

1. **Observe?** Usually RGB/latent; Parcel also needs LiDAR ranges, owner tracks, battery/thermal.
2. **Act?** Imagined actions must match HAL types (`TimedVelocitySetpoint` twists or `SE2Goal`)—or ranking is fiction.
3. **Rate/latency?** Multi-step video rollouts rarely meet collision deadlines.
4. **Data/compute?** Pretrain + fine-tune budgets dwarf companion CI.
5. **Unitree transfer?** Dynamics of arms/cars ≠ Go2 contact; gait errors dominate.
6. **Safety layer?** World-model score cannot retire `apply_reactive_safety`.

## ASCII diagram

```text
  logs / MuJoCo / city scaffold
            |
            v
     learned world model
            |
     +------+------+----------------+
     |             |                |
     v             v                v
  synth demos   dream ranking   "safe?" heatmap
     |             |                |
     v             v                v
  train πθ     pick checkpoint   STILL NOT a shield
                     |
                     v
        real eval: DirectiveNavigator + gates + ControlManager
```

## Map to Parcel / Go2

Parcel still keeps physics-adjacent truth and product gates deterministic while research invents predictors.

Codebase-relative context:

- Headless/MuJoCo backends (`backends/mujoco.py`, `sim.py`) expose simulator-private state for debugging—hardware has no oracle twin. Do not design world-model APIs that require sim-only fields at runtime (Day 01 discipline).
- City scaffold: `MetaUrbanNavEnv` (`navigation/envs/metaurban_env.py`) + `social_nav_reward`—offline kinematics, not a learned safety case; `use_metaurban=True` remains fail-closed until a real adapter exists (`docs/NAVIGATION_CITY.md`).
- Product path unchanged: `DirectiveNavigator` → `apply_collision_brake` / runtime `apply_reactive_safety` → `CommandArbiter` → `ControlManager` → `UnitreeSportController`.
- RL stubs (`Go2Env`, `rl/rewards.py`) may consume synthetic experience, but `SafetySupervisor` still gates any `rl` backend switch.
- Eval promotion culture (BARN/companion ledgers under `evals/`) is the pattern: imagination may *propose* experiments; gates *promote* code.
- Duplex fillers must not claim “looks clear ahead” from a dream rollout; speech tracks real observations.

Classification: **prototype** world models for scenario mining and offline ranking correlated to real metrics; **shadow** dream-vs-real residual logs on the same routes; **reject** using imagined TTC as permission to move; **adopt** only tooling that feeds existing eval harnesses without changing the writer path.

Practical rule of thumb for Parcel reviews: if a PR says “world model says safe,” demand the same veto chain as a human teleop command—`CommandArbiter` TTL, reactive/collision gates, and `ControlManager` stop confirmation—before any Sport-facing enablement.

## Overconfidence story

A team trained a video world model on campus walks and showed “zero collisions” across 10k dreamed rollouts of a new local policy. On hardware, glare-blackened LiDAR returns (absent from RGB-centric dreams) hid a low planter. The dream eval had optimized visual plausibility, not sensor failure modes. Overconfidence was mistaking generative coherence for physical coverage. A Parcel-shaped postmortem would ask why the promotion gate did not require headless classical runs with corrupted scans—exercising the same `scan_missing_fallback` / stale-telemetry paths `DirectiveNavigator` and reactive safety already know—before any Sport-facing trial.

## Retrieval questions

1. Name two legitimate Parcel uses for a world model that do not grant motor authority.
2. Why can’t a low imagined-collision rate replace `ReactiveSafetyPolicy`?
3. (Week-back) From Day 36/37: what does the reality gap imply for neural sims specifically?

## Optional 10-minute exercise

Write a one-page “dream eval contract”: which observation channels are predicted, which Parcel log fields are required for correlation (`RobotMotionState`, nearest person/obstacle ranges), and which promotion gate in `evals/` must still pass on real or headless classical stacks before merge. Explicitly forbid dream-only green merges.
