# City navigation: current pipeline, design choices, and backend path

Implementation snapshot: 2026-08-04. Canonical authority context:
[COMPANION_NAVIGATION_ARCHITECTURE.md](COMPANION_NAVIGATION_ARCHITECTURE.md)
and [REDESIGN_2026_ARCHITECTURE.md](REDESIGN_2026_ARCHITECTURE.md). Living-city
scene details: [DYNAMIC_CITY_AND_BEHAVIOR.md](DYNAMIC_CITY_AND_BEHAVIOR.md).

## Reality check

- `src/parcel_robot/scenes/city_block.xml` is the active daily city scene. The
  normal simulator adds seeded pedestrian/cyclist routes, owner and actor
  telemetry, and an occlusion-true planar MuJoCo raycast.
- The configured navigator is **`grid_v1`**: rolling log-odds occupancy,
  footprint inflation, A*, observed-segment validation, and a rotate-first
  waypoint controller. Current dynamic tracks add a soft, constant-velocity
  predicted-cost field; they do not become hard occupancy.
- `grid_v1` is production-path software, but “production” currently means the
  default Parcel runtime and regression suite. It has not navigated a physical
  Go2 from this workstation.
- A missing or malformed calibrated scan switches `grid_v1` to the
  deterministic point-goal controller and emits a warning,
  `scan_missing_fallback`, and a counter. That is a loud degraded mode, not an
  equivalent mapped planner and not a hardware qualification.
- MetaUrban is not integrated. `MetaUrbanNavEnv(use_metaurban=False)` is an
  offline kinematic scaffold; `use_metaurban=True` raises
  `NotImplementedError` even when the vendor package is installed.

## End-to-end stack

```text
explicit destination directive
  -> reject negation / hypotheticals
  -> resolve configured POI, or create typed semantic object/region goal
  -> bounded camera semantic search (unknown goals only)
  -> collision-cleared terminal pose
  -> grid_v1 over odometry + calibrated planar LiDAR
       + per-tick soft predicted costs for dynamic tracks
  -> MidLevelCommand(vx, vy, vyaw)
  -> navigation-local collision brake and configured velocity bounds
  -> runtime CommandArbiter + smoother
  -> runtime-wide camera/LiDAR proximity and TTC vetoes
  -> jerk-limited actuator hand-off (environmental stop currently ramps)
  -> ControlManager -> selected locomotion controller
  -> odometry, LiDAR, semantic tracks, and measured velocity feed the next tick
```

The semantic model chooses *what relation should become true*. The geometric
planner chooses a route. The runtime decides which command source owns motion,
and the controller boundary owns delivery and stopping. No language-model
output is interpreted as a path, joint command, or raw velocity tick.

## Code and configuration map

```text
configs/navigation/
  default.yaml                 # active_model: grid_v1
  models/grid.yaml             # deployed planner/controller profile
  models/stub.yaml             # deterministic degraded/test controller
  models/grid_*.yaml           # explicitly experimental eval profiles
  models/{citywalker,navila,nomad,vint}.yaml  # metadata, no inference adapter
  cities/demo_pois.yaml        # static demo coordinates, not Google Maps

src/parcel_robot/navigation/
  goals.py                     # imperative grammar and SemanticGoal
  grounder.py                  # configured POI lookup
  search.py                    # bounded rotate-in-place semantic search
  semantic_map.py              # typed perception-track adapter
  approach.py                  # region interior / object stand-off pose
  pipeline.py                  # DirectiveNavigator mission state machine
  grid_planner.py              # rolling occupancy, inflation, A*, waypoints
  grid_navigator.py            # route tracking, recovery, loud fallback
  dynamic_costs.py             # constant-velocity agent costs and contact time
  dynamic_layer.py             # strict config/payload wiring and TTC verdict
  collision.py                 # navigation-local brake
  reactive_safety.py           # final runtime gate for every velocity source
  follow.py                    # direct and behind-owner formation control
  owner_prediction.py          # bounded lead-point prediction for follow
  search_owner.py              # last-seen, sweep, and frontier reacquisition
  spatial.py                   # bounded relative movement and owner orbit
  envs/metaurban_env.py        # offline scaffold only

src/parcel_robot/runtime.py    # sensor adapter, arbitration, terminal stop proof
src/parcel_robot/mujoco_lidar.py
evals/companion_nav/           # product-oriented companion scenarios
evals/external/                # research proxies (BARN / Habitat)
```

## Public API and actual runtime use

The standalone API is:

```python
from parcel_robot.navigation import DirectiveNavigator

nav = DirectiveNavigator.from_config("configs/navigation/default.yaml")
mission = nav.start("go to the crosswalk")
while not nav.done():
    command = nav.step(observation)
```

The product path calls the same pipeline through `Dog.navigate(...)` from
`RobotRuntime`. Runtime supplies pose, the full calibrated scan, bounded
camera/depth semantic tracks, LiDAR obstacle returns, freshness, and measured
motion feedback. The returned command still passes through runtime arbitration,
the shared reactive gate, and final shaping before `ControlManager` sees it.
The current reactive decision precedes that final S-curve shaper; the
2026-08-09 audit marks a post-shaper exact-zero reassertion as P0 work.

## Sensor and map contract

The dog is configured to use camera and LiDAR for its environment. It also
needs robot-state feedback/odometry to express a goal and accumulated scan in a
consistent frame.

| Input | Used for | Current implementation | Important limit |
| --- | --- | --- | --- |
| Planar LiDAR | Free/occupied evidence, A* route, local collision range | 360-ray MuJoCo `mj_multiRay`, 30 m reported maximum, 0.008 m seeded hit noise, 0.2% dropout; navigator subsamples with stride 2 and caps mapping at 12 m | One horizontal plane misses terrain, drop-offs, glass, and obstacles above/below the plane |
| Camera/depth semantic tracks | Owner identity/position; sidewalk/lamppost candidates; dynamic-agent tracks expected from a physical adapter | Simulator emits typed tracks from known scene objects with range/FOV filtering | No pixel detector, depth estimator, occlusion-aware semantic camera, or re-identification model is implemented |
| Odometry / body state | Robot pose, route frame, progress, stop verification | Simulator state or Unitree `SportModeState` contract | No SLAM, relocalization, loop closure, or drift correction is implemented |
| Static POI registry | Resolve known names to metric goals | `demo_pois.yaml` | A demo coordinate prior; hardware use requires a real localized map frame |
| Google Maps | Future context/route hint | Disabled `NullMapProvider` | Placeholder only: no key, request, route, or navigation authority |

The simulator keeps its truth oracles for test scoring, but the navigator API
does not accept collision geometry or an evaluator path. Nevertheless, the
current semantic-track generator itself is derived from known scene metadata.
Passing typed tracks across an adapter boundary is good architecture; it does
not make the simulator's semantic perception realistic.

## Geometric planner design and consequences

The default grid has 0.10 m cells and 161 cells per side (a 16.1 m rolling
window). It retains overlapping log-odds evidence as the window recenters and
inflates obstacles by the 0.32 m footprint plus a 0.10 m hard margin. Static
routes normally replan every five navigation ticks and immediately replan when
a newer scan invalidates the cached segment. When a valid dynamic-agent layer
is active, A* runs every tick so a cached route does not lag moving tracks.

| Choice | Advantage | Limitation / consequence |
| --- | --- | --- |
| Rolling local log-odds map | Bounded CPU/memory and incremental noise filtering | Old space falls out of the window; no globally consistent map or loop closure |
| Penalize unknown space in A* | A partial field of view can still suggest goal direction instead of treating the world as a wall | The controller executes only an observed clear segment; default `grid_v1` can enter scan-only recovery at an unknown frontier or local minimum |
| Binary footprint inflation | Simple, inspectable hard geometric clearance | Conservative rasterization narrows passages; it is flat 2-D and not terrain traversability |
| Known-free line-of-sight smoothing | Shorter paths without cutting an inflated corner | It cannot smooth through unseen space and may produce cautious stop/scan behavior |
| Replan periodically plus on invalidation | Reduces A* load while reacting immediately to a newly blocked cached segment | At the 10 Hz runtime and five-step interval, static-only global replans are about 0.5 s apart; any active dynamic layer increases this to every tick |
| Rotate-first hysteresis (`28°` enter, `7°` exit) | Removes diagonal slide and gives a stable heading mode | Slower than simultaneous rotate/translate and may look hesitant in a crowd |
| Nominal `vy=0` | Natural forward-facing travel and portability to non-strafing bases | Gives up useful holonomic sidesteps; a future local planner may intentionally use `vy` without changing the command contract |
| Scan-only default recovery | Avoids reversing into the rear blind wedge of a 270° eval/hardware scan and remains conservative in the 360° simulator | Rotation alone cannot escape every U-trap or wall-end local minimum |

The current speed values are deliberately layered. `grid.yaml` has a desired
cruise of `0.85 m/s`, but `default.yaml` clamps any navigation output to
`0.45 m/s`; `configs/robot.yaml` then has a broader body-level limit of
`1.0 m/s`. The 2026-08-04 cruise/global-limit retune improves tapering and
non-navigation motion, but does **not** make ordinary navigation a sustained
`0.85 m/s` controller. These simulator values are not a commissioned hardware
speed profile.

The planner has its own acceleration slew, and the runtime applies another
velocity smoother before the shared safety gate and an S-curve shaper after it.
This makes command changes gentler, but the nested filters add tracking lag.
The S-curve emergency branch currently decelerates rather than guaranteeing an
exact-zero final command on an ordinary proximity/TTC veto, so neither immediate
environmental stop behavior nor physical response may be inferred from the
kinematic simulation.

The current batched grid-update microbenchmark is documented in
[GRID_UPDATE_PERFORMANCE.md](GRID_UPDATE_PERFORMANCE.md). Its local-host timing
leaves headroom for the measured grid update inside a 10 Hz navigation period,
but it does not include every planning/runtime cost and is neither a real-time
deadline nor evidence about route quality.

### Experimental grid profiles

The `grid_clearance`, `grid_frontier_*`, `grid_safe_valley_*`,
`grid_recovery_reverse`, and enlarged-window YAML files are eval experiments,
not the default. They explore soft comfort clearance, observed-frontier
progress, bounded detours, fresh-sensor safe-valley advances, reverse recovery,
and a larger rolling map. Their presence beside `grid.yaml` does not make them
deployable. Promotion requires product-scenario improvement, invariant tests,
and a deliberate change to `default.yaml`.

In particular, the safe-valley profiles fail closed when scan/odometry frames
are stale or unsynchronised, while default `grid_v1` retains its older loud
point-goal fallback. That difference must remain visible in comparisons.

## Semantic goal design

Unknown places are not converted directly into guessed coordinates:

1. `SemanticGoal` classifies a bounded object or region relation.
2. The dog rotates and requires two confidence-qualified observations by
   default.
3. Region goals sample an interior pose with edge and obstacle clearance.
   Object goals sample a stand-off ring and may require a support polygon, such
   as standing on the sidewalk near a lamppost.
4. Lack of progress triggers at most two re-grounding attempts with the default
   config.
5. Arrival is published only when a fresh candidate still satisfies the
   relation, the environment is clear, and measured motion is settled.

Advantages: common-sense vicinity rather than exact-point semantics, explicit
uncertainty, bounded search/retry, and outcome-based success. Limitations: the
parser recognizes a bounded vocabulary; the simulator candidate metadata
contains hand-authored clearances; search is rotation-only; and there is no
learned open-vocabulary grounding or long-lived semantic SLAM on hardware.

## Dynamic people and collision handling

Dynamic actors can appear in the MuJoCo raycast and the runtime separately
publishes range, bearing, velocity, radius, and time-to-contact. `grid_v1`
projects at most 16 validated tracks with a constant-velocity model over a
two-second horizon. Decaying Gaussian lobes become an additive A* cost inside a
six-meter window; the owner is handled as a separate, lower-weight lobe so
following does not turn the owner into a wall. The layer is rebuilt and planned
against every tick while tracks exist. A malformed track payload is logged and
disables this **soft** layer for that tick rather than stopping the runtime.

Two independent outgoing-command checks remain authoritative. The universal
reactive gate consumes the simulator/adapter's selected nearest social
candidate (including the owner) and geometric proximity. The later configured
TTC gate recomputes constant-velocity contact against non-owner dynamic tracks
for the candidate command and can only scale the already-admitted command down.
Neither can release a proximity stop. This separation also protects
manual/follow commands that never use the grid.

This is bounded prediction, not full predictive crowd navigation. There is no
uncertainty propagation, learned intention forecast, time-indexed A* state,
multi-agent interaction model, ORCA local negotiation, or guarantee that a
soft cost changes the selected route. Smooth behavior in dense bidirectional
crowds is not yet demonstrated.

## Owner following and reacquisition

Direct and behind-owner following use camera owner tracks. A bounded motion
predictor is fed even while follow is idle and may move the controller's lead
point by `0.6 s`; low confidence scales translation down, and stale/invalid
tracks fall back to the measured owner rather than authorizing extrapolated
motion.

After the follow controller reports the owner lost for three seconds, the
default brain-enabled runtime can compile a deterministic `SearchOwner` system
task. The `search` source has priority 35 and performs three bounded phases:
return toward the last confident position, sweep in place, then visit
information-gain frontiers inside a reachability disk. It uses the rolling A*
planner when calibrated LiDAR is present and loudly degrades to direct steering
plus coverage-only frontier ranking without it. Reacquisition resumes follow
through the runtime's legacy saved follow tuple; generic `ResumeIntent`
consumption is not yet the end-to-end resume mechanism. The search gives up
after 45 seconds and holds rather than wandering indefinitely.

## Registry: working, degraded, and research-only

| Capability | Status today | What would make it deployable |
| --- | --- | --- |
| `grid_v1` | Default Parcel navigator, including soft dynamic-agent costs | Physical scan/localization commissioning and hardware eval |
| `stub_v0` | Tests and loud missing-scan fallback | Keep as a diagnostic; do not equate it with mapped navigation |
| POI lookup | Working against static demo YAML | Real map frame, localization, lifecycle/version policy |
| Semantic search and terminal verification | Working against typed simulator tracks | Physical camera/depth perception with freshness and calibration tests |
| CityWalker / NaVILA / NoMaD / ViNT | YAML metadata/checkpoint paths only; factory rejects their types | Inference adapter, exact observation/action contract, safety wrapping, tests |
| MetaUrban | Vendor install script plus kinematic scaffold | Versioned service/IPC adapter for reset, step, observations, actions, shutdown |
| Google Maps | Disabled placeholder | Privacy policy, network/cache behavior, grounding and localization adapter; never collision authority |

`ModelRegistry` loads all YAML metadata, but `build_navigator` intentionally
constructs only `stub` and `grid`. A checkpoint on disk is not an executable
navigator.

## Simulation and evaluation

Daily semantic behavior gate:

```bash
.parcel/bin/python -m pytest -q \
  tests/test_headless_city_tasks.py \
  tests/test_mujoco_lidar.py \
  tests/test_city_orbit_clearance.py
```

`HeadlessCityWorld` uses the real MuJoCo geometry and the same observation
types, but advances the base kinematically with `mj_forward`. It proves closed-
loop task predicates and collision geometry, not Unitree Sport tracking,
contact dynamics, foothold selection, sensor synchronization, or sim-to-real.

`evals/companion/embodied_plan_v1/` additionally executes accepted PlanIR
through the executive and headless controllers. It supports navigation,
owner-orbit, relative motion, and hold; `FollowFormation` is intentionally
reported as unsupported. Its committed result JSON is historical and predates
the current grid/speed configuration, so regenerate a result before quoting a
current metric.

`evals/companion_nav/` is the product-oriented follow/search gate with scripted
owners and pedestrians. Its expression portion drives the real expression
engine from scripted speech events, not the audio pipeline, and scripted emote
windows model base ownership rather than joint choreography. BARN and Habitat
under `evals/external/` remain planner research proxies and must not be reported
as Go2 companion performance.

## Later simulator backends

| Backend | Intended use | Current Parcel status |
| --- | --- | --- |
| MuJoCo Parcel scene | Daily deterministic behavior tests | Active |
| MetaUrban | Procedural SocialNav and richer crowds | Separate Python 3.9 vendor environment; Parcel step adapter absent |
| URBAN-SIM / Isaac Lab | Articulated Go2 city training | Research recommendation only |
| SimWorld | Photorealistic demonstration profile | Research recommendation only |

The install helper prepares vendor research but does not integrate it:

```bash
bash scripts/setup_metaurban.sh
```

Keep simulation engines behind `SimulatorBackend` or versioned process IPC.
Do not import a Python-3.9/GPU simulator into Parcel's Python 3.14 threaded
runtime, and keep `active_model: grid_v1` until a challenger passes the same
sensor, safety, and product-evaluation contracts.
