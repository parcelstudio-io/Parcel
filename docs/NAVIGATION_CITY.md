# City navigation: MetaUrban + open-weight navigators

## Reality check (this machine)

- Current MuJoCo `city_block.xml` is a compact living-city regression scene:
  seven moving pedestrians, one cyclist, seeded routes, and full track telemetry.
- The host has an RTX 5000 Ada (32 GB) and Python 3.14; MetaUrban still needs a
  separate Python 3.9 environment.
- Parcel now runs a persistent simulator navigation loop with rotate-first
  alignment, acceleration limits, person/obstacle telemetry, predictive TTC
  braking, and a final proximity gate. Full visual learned navigation remains a
  later stage.

## Recommended simulation platform

Use **MuJoCo first**, then add an urban simulator behind `SimulatorBackend`.
MuJoCo is the active platform because it provides the official Go2 body/joints,
fast physics, reproducible tests, and low GPU contention. For later city-scale
visual/social navigation, integrate
**[MetaUrban](https://github.com/metadriverse/metaurban)** first. Use
**[URBAN-SIM](https://github.com/metadriverse/urban-sim)** for later articulated
Go2/Isaac training and **[SimWorld](https://github.com/SimWorld-AI/SimWorld)**
for the most game-like photorealistic demo profile. iGibson is now a design
reference rather than the recommended backend. See
[Dynamic city and behavior architecture](DYNAMIC_CITY_AND_BEHAVIOR.md).

Why this over CARLA / Isaac / raw MuJoCo:

| Platform | City + pedestrians | Quadruped / micromobility | Gym / RL | Weight |
| --- | --- | --- | --- | --- |
| MetaUrban | Infinite compositional cities, SMPL pedestrians | Delivery bots, quadrupeds, etc. | Gym + SB3 | Lighter than Isaac |
| CARLA | Large cities + peds | Vehicle-centric | Yes | Heavy |
| Isaac Sim | High fidelity | Strong | Yes | Very heavy |
| MuJoCo Parcel scene | Compact block + owner + obstacles | Official Go2 | Custom | Active, light |
| SimWorld | Procedural city + traffic | Robotics module | Agent/waypoint APIs | Promising, active development |

Install (on a GPU Linux box with Conda Python 3.9):

```bash
./scripts/setup_metaurban.sh
```

## Recommended open-weight navigation models

Language directive → mid-level motion needs **two layers**:

1. **Language / urban navigator (high level)**  
   - **Primary (legged + language):** [NaVILA](https://navila-bot.github.io/) — VLA for quadrupeds; mid-level language actions + locomotion; Unitree Go2 demos.  
   - **Primary (urban visual nav):** [CityWalker](https://github.com/ai4ce/CityWalker) (CVPR 2025) — trained on web-scale city walking/driving video; open pretrained weights.  
   - **Foundation / RL fine-tune:** [ViNT](https://visualnav-transformer.github.io/) / [NoMaD](https://github.com/robodhruv/visualnav-transformer) — cross-embodiment visual nav; good RL/IL adaptation base.

2. **Obstacle-aware locomotion (low level)**  
   - Keep Parcel `motion` / Unitree Sport / RL locomotion policy for short-horizon collision-aware walking.  
   - NaVILA’s vision locomotion policy is the research target for “don’t bump people”.

**Parcel default wiring for directives like**  
`"go to the coffee shop at 42nd street"`:

```text
directive
  → Goal resolver (known POI → semantic map → bounded active visual search)
  → NavigatorModel (citywalker | navila | nomad | vint | stub)
  → MidLevelCommand (vx, vy, vyaw) or waypoints
  → Dog / MotionRouter / MuJoCo backend (implemented)
  → future MetaUrban action adapter (not implemented)
  → collision / social cost in RL reward
```

## Code layout

```text
configs/
  navigation/
    default.yaml
    models/
      stub.yaml
      citywalker.yaml
      navila.yaml
      nomad.yaml
      vint.yaml
    cities/
      demo_pois.yaml          # coffee shop @ 42nd, etc.
src/parcel_robot/navigation/
  __init__.py
  registry.py                 # multi-version model registry
  base.py                     # NavigatorProtocol, Mission, MidLevelCommand
  grounder.py                 # language → POI / goal pose
  pipeline.py                 # DirectiveNavigator
  models/
    __init__.py               # working stub; other types fail closed
  envs/
    metaurban_env.py          # offline kinematic Gym-like scaffold
    rewards.py                # social nav / collision penalties
docs/NAVIGATION_CITY.md
scripts/setup_metaurban.sh
```

Multiple **versions** of the same model type live as separate YAML entries (`citywalker_v1`, `citywalker_finetune_rl`, …) pointing at different `checkpoint` paths and `rl.enabled` flags.

## Public API

```python
from parcel_robot.navigation import DirectiveNavigator, MetaUrbanNavEnv

nav = DirectiveNavigator.from_config("configs/navigation/default.yaml")
mission = nav.start("I want you to go to the coffee shop at 42nd street")
while not nav.done():
    cmd = nav.step(observation)  # NavObservation: pose + person/obstacle range
    # apply cmd via Dog / MotionRouter / MetaUrban

env = MetaUrbanNavEnv(navigator=nav, density_ped=1.0)
obs, info = env.reset(options={"directive": mission.directive})
```

Despite its historical class name, that environment is the offline kinematic
scaffold. `use_metaurban=True` deliberately raises `NotImplementedError`: merely
importing/resetting the vendor environment is not a working Parcel backend.

Also exposed on `Dog.navigate(directive: str)` when `navigation.config` is set in `robot.yaml`.

### Open-world semantic goals

Unknown destination text no longer fails solely because it is absent from the
POI YAML. It becomes a typed semantic object/region goal. The active search
controller rotates in place, queries perception-provided candidates, requires
repeated confidence-qualified observations, constructs a footprint-cleared
interior or stand-off pose, and only then hands the mission to the point-goal
controller. Region goals such as `sidewalk` are verified geometrically at
arrival. Searches are bounded by `semantic_search.max_steps` and fail without
translating when no reachable target is confirmed.

Semantic completion is relation-specific rather than a generic point radius:

- `inside sidewalk` samples a collision-free interior pose, validates the
  swept centerline against LiDAR surfaces, keeps the complete robot footprint
  inside the region, turns to keep the region in view, and independently
  rechecks the current camera polygon after stopping;
- `near lamppost` associates the camera object with its LiDAR identity, chooses
  a safe stand-off on the sidewalk support surface, enforces both a minimum
  collision gap and maximum one-metre body-to-object vicinity, then rechecks
  the current object track and associated LiDAR surface range before holding;
- a progress watchdog re-observes and replans a stalled semantic mission twice,
  then fails closed instead of emitting an endless velocity command.

Geometric arrival enters a `verifying` phase rather than immediately reporting
success. Runtime sends an explicit locomotion stop and waits for fresh controller
feedback, the configured settled linear/yaw thresholds, and Unitree Sport stop
confirmation. The live spatial relation must still be valid after the body has
settled, and the camera/LiDAR observation used for that check must still be fresh.
Missing feedback, stale perception, a lost/changed target, or an unsafe target
range cannot produce an `arrived` result; stop verification is bounded and fails
closed.

The local baseline controller latches a specific blocking obstacle and a
world-frame tangent until both that obstacle and the direct-goal corridor are
clear. It still turns before translating and normally emits forward velocity,
while bounded lateral velocity remains available to future controllers. The
final runtime collision gate is a separate pure component shared by the live
runtime and the headless quality harness. Bounded simulator LiDAR preserves
closest-per-geometry hits and angular coverage before adding facade samples, so
dense returns behind the robot cannot evict a forward hazard.

MuJoCo publishes visible sidewalk/crosswalk polygons as a diagnostics-only
semantic-camera adapter for deterministic tests. Production deployments must
replace it with camera segmentation/open-vocabulary features fused with depth or
LiDAR; simulator semantic truth is never presented as a production sensor.

### Headless semantic-task quality gate

`HeadlessCityQualityHarness` loads the real `city_block.xml` with no viewer,
advances a fixed simulation clock, and runs the production command parser,
semantic resolver, point navigator, spatial controller, and reactive safety
gate. Controller inputs contain only typed camera/depth semantic tracks, LiDAR,
owner tracking, and odometry. A separate truth oracle evaluates outcomes and is
never fed back into planning. The harness loads its selected navigation
configuration plus collision, orbit, and settled-speed thresholds from the same
`configs/robot.yaml` used by runtime, so configuration changes are exercised by
the gate.

Run the commissioning gate with:

```bash
python -m pytest -q \
  tests/test_headless_city_tasks.py \
  tests/test_mujoco_lidar.py \
  tests/test_city_orbit_clearance.py
```

The gate currently proves:

1. sidewalk requests from two road starts end fully inside the correct sidewalk
   and off the road;
2. lamppost requests from a road approach and a cramped building-side start end
   on sidewalk support, safely outside the hard-stop envelope, within one metre
   from robot body to post surface, and stopped;
3. the default owner is acquired, approached, and orbited once with independent
   angular/radial/path assertions, complete 12-bin coverage, no contact, and a
   zero terminal command;
4. timeouts remain failures—the harness records the controller command before
   cleanup, so cleanup cannot make a moving failure look stopped.

The world uses MuJoCo geometry and exact oriented-surface LiDAR returns, but base
motion is intentionally kinematic (`mj_forward`, not contact-dynamics
`mj_step`). It is a fast behavior regression gate, not evidence that a learned
gait or Unitree Sport controller is physically qualified. Hardware-in-loop and
full contact-physics tests remain required before deployment.

### Local dynamic context

`parcel_robot.context.ContextBuilder` assembles typed location, time, map, and
scene fields in process. `query_context` flags gate both provider invocation and
prompt serialization and default off. Exact local coordinates are withheld from
the voice prompt unless `include_precise_coordinates_in_prompt` is enabled, while
authorized structured context remains available to deterministic navigation.
Provider interfaces can gain remote implementations later without making the
current context path a network service.

## RL organization

Each model YAML:

```yaml
id: citywalker_v1
type: citywalker
version: "1.0.0"
checkpoint: models/nav/citywalker.pt
rl:
  enabled: true
  trainable: true
  algo: ppo          # or il / finetune
  obs_keys: [rgb, goal, lidar]
  action_space: mid_level_velocity
  reward: social_nav_v1
```

`parcel_robot.navigation.envs.metaurban_env.MetaUrbanNavEnv` can exercise
PointNav/SocialNav loop shapes offline. A real MetaUrban training environment
still needs action/observation mapping, lifecycle, reward, and render wiring.
Keep Stable-Baselines3/custom loops **outside** the voice process.

## What works today vs later

| Capability | Today | Research integration required |
| --- | --- | --- |
| POI grounding for demo directives | Yes (`demo_pois.yaml`) | Expand map / VLM |
| Multi-model registry + versions | Metadata only beyond `stub_v0` | Implement vendor loaders/adapters |
| Stub navigator + persistent runtime loop | Yes | Implement and test CityWalker/NaVILA inference |
| Reactive obstacle bearing turn + final brake | Yes | Add learned/local map planner |
| Living city + pedestrians | Yes, compact seeded MuJoCo crowd | MetaUrban procedural backend |
| Don’t bump people | Person tracks, TTC/proximity braking | Predictive SocialNav/MPPI + real perception |
| Turn before translating | Yes, align/track hysteresis | Nav2 Rotation Shim + MPPI/RPP |

## Next host setup

1. Install Conda + Python 3.9 (the NVIDIA driver/CUDA-compatible GPU is ready).
2. Run `./scripts/setup_metaurban.sh`.
3. Implement MetaUrban as a separate versioned IPC service and test real steps and observations.
4. Implement CityWalker or NaVILA preprocessing/inference/output conversion.
5. Download the matching checkpoint, add regression fixtures, then change `active_model` from `stub_v0`.
6. Train/fine-tune with the real environment and `social_nav_v1` reward only after those adapters are verified.
