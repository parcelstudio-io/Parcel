# Day 36: What a Simulator Actually Computes

## Mental model

A simulator is not a smaller reality. It is a *computational process* that advances a private world state under models you chose: rigid bodies, collision geometry, contact solvers, sensors stubs, and integration timesteps. It can compute truths no onboard robot ever sees—exact poses, exact contacts, semantic IDs—while still lying about friction, latency, and perception.

```text
simulator-private truth  ≠  SimObservation  ≠  physical actual
```

MuJoCo integrates dynamics (or, in Parcel’s current city base path, often a kinematic/scripted base) at `model.opt.timestep`, applies your last command until a watchdog expires, and publishes a versioned observation. Deterministic seeds make the RNG and scenario layout replayable—not magically correct.

Ask of every sim feature: does it compute *plant physics*, *sensor stubs*, *scenario logic*, or *eval oracles*? Mixing those roles is how privileged collision checkers leak into “product metrics.” Contact solvers and self-collision constraints can be expensive and brittle; kinematic bases are honest about what they refuse to prove.

## Software-engineering analogy

Treat the sim like a fake database with admin APIs. Integration tests may use fixtures that production never has (`DELETE FROM users` without auth in a test harness). If application code calls the admin API in “prod mode,” you have a security bug. Likewise: planners must not query privileged world meshes; they consume `SimObservation` the same way hardware will consume sensors.

**Tradeoffs:**

- Fast kinematic base → snappy desktop iteration, weak evidence for balance/slip.
- Full contact-rich stepping → more fidelity, more flaky contacts, slower CI.
- Privileged labels for eval scoring → OK inside `evals/`; forbidden inside navigation authority (D5).

## Light equations (discrete time)

A simplistic integrator view:

```text
x_{k+1} = f(x_k, u_k, w_k; θ)
t_{k+1} = t_k + Δt
```

Here `θ` is model parameters (masses, friction, sensor noise), `w_k` process noise, `u_k` the commanded twist. Changing `Δt` changes numerical contact behavior. Seeded `w_k` gives reproducibility, not unbiased physics.

## ASCII diagram

```text
                 +---------------- privileged (sim process) ----------+
                 |  meshes, contacts, exact owner pose, seeds, RNG     |
                 +------------------------+----------------------------+
                                          | filter / project
                                          v
  RobotRuntime  <--- SimObservation ---  MujocoSocketBackend
       |              (timestamped,        observe()/move()/stop()
       |               typed, limited)
       v
  grid_v1 / follow / reactive_safety     ### must not peek above the line ###
```

## Map to Parcel / Go2

From `INTRO.md` (simulation section), `DESIGN_DECISIONS.md` D5/D9, and backends:

- Daily loop: MuJoCo in-process/IPC; richer urban stacks stay out of process (D9).
- Product perception authority is camera/LiDAR contracts—not simulator map dumps.
- Scripted gait / kinematic translation can look smooth while proving little about Sport balance.
- Headless city harnesses reuse the same observation types for regression.
- Eval code may know ground truth for scoring; that must stay behind `does_not_prove` honesty when claiming product readiness.

**Design choice:** keep one authoritative world process and a narrow `SimulatorBackend` Protocol. Cost: IPC/schema work. Benefit: swap engines without rewriting the brain.

What the Parcel sim *does* compute usefully: repeatable owner/obstacle layouts, occlusion-aware planar scans with explicit dropout/NaN policy, command watchdog/E-stop transport, and collision flags for harness scoring. What it must not be asked to compute for product authority: “true” semantic certainty, Sport-internal foot placements, or thermal/brownout curves of a fielded Go2.

**Codebase anchors (sim vs observation):**

- `backends/base.py` → `SimObservation`, `SimulatorBackend.observe/move/stop`; `perception/contract.py` advertises `"simulator_ground_truth": False` in reasoning visibility.
- `backends/mujoco.py` → `MujocoSocketBackend` parses socket telemetry into typed tracks/scans.
- `sim.py` → `model.opt.timestep`, `mujoco.mj_step`, `dynamic_city_seed`, independent motion watchdog (~0.65 s), transport `emergency_stopped`.
- `navigation/grid_planner.py` docstring forbids privileged simulator map / evaluator path as planning authority.
- `simulation/headless_city.py` → `HeadlessCityWorld` / `HeadlessCityQualityHarness` — deterministic scenario runner on the same observation seam.
- Expression overlays (`SimulatorBackend.expression`) are decorative capability, not locomotion proof.

Timestep choice is a design knob: smaller `Δt` can change contact chatter and CPU cost without magically adding missing actuator delay. If your CI only runs the kinematic base path, say so in the eval ledger—do not imply contact-rich Sport dynamics were validated.

## Failure story

A “collision-free” nav metric queried MuJoCo contact points directly while the planner only saw a sparse planar scan. The team celebrated zero collisions in CI. On a mocked scan dropout the planner drove through a chair the privileged checker still called a pass because the harness scored mesh penetration with a different threshold. Fix: score what the robot could know (`SimObservation` + command logs), and label privileged probes as debug-only with an explicit `does_not_prove` for onboard safety.

## Retrieval questions

1. Name two quantities a simulator can know that Parcel’s product stack must pretend not to know.
2. Why does a deterministic seed not close the reality gap?
3. (Week-back) How does Day 23’s “no-return / self-return” LiDAR lesson show up in `SimObservation.lidar_ranges` NaN/`range_max` conventions?

## Optional 10-minute exercise

Read `backends/base.py` (`SimObservation`) and the planning-authority comment in `navigation/grid_planner.py`. List five fields the planner may use and two privileged facts that must remain inside `sim.py` / eval scorers only. Note one field that is easy to misuse as ground truth.
