# City navigation: MetaUrban + open-weight navigators

## Reality check (this machine)

- Current MuJoCo `city_block.xml` is a **stylized block**, not a living city.
- Full cities with walking humans need a dedicated urban sim.
- Host today: **Python 3.14 only**, **no NVIDIA GPU / nvidia-smi**. MetaUrban expects **Python ~3.9** and a GPU.
- Parcel therefore ships a **navigation stack + model registry** that targets MetaUrban, while staying runnable offline (stubs) until a compatible env exists.

## Recommended simulation platform

**[MetaUrban / metaurban](https://github.com/metadriverse/metaurban)** (ICLR 2025)

Why this over CARLA / Isaac / raw MuJoCo:

| Platform | City + pedestrians | Quadruped / micromobility | Gym / RL | Weight |
| --- | --- | --- | --- | --- |
| MetaUrban | Infinite compositional cities, SMPL pedestrians | Delivery bots, quadrupeds, etc. | Gym + SB3 | Lighter than Isaac |
| CARLA | Large cities + peds | Vehicle-centric | Yes | Heavy |
| Isaac Sim | High fidelity | Strong | Yes | Very heavy |
| MuJoCo parcel scene | Boxes only | Go2 meshes | Custom | Light, not a city |

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
  → SemanticGrounder (POI / map / optional VLM)
  → NavigatorModel (citywalker | navila | nomad | vint | stub)
  → MidLevelCommand (vx, vy, vyaw) or waypoints
  → Dog / MotionRouter / MetaUrban env step
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
    stub.py
    citywalker.py             # weight download + inference adapter (optional deps)
    navila.py
    nomad.py
    vint.py
  envs/
    metaurban_env.py          # Gym wrapper when metaurban is installed
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

Also exposed on `Dog.navigate(directive: str)` when `navigation.config` is set in `robot.yaml`.

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

`parcel_robot.navigation.envs.metaurban_env.MetaUrbanNavEnv` is the training env (PointNav / SocialNav) once MetaUrban is installed. Use Stable-Baselines3 / custom loops **outside** the voice process.

## What works today vs later

| Capability | Today | After MetaUrban + GPU + weights |
| --- | --- | --- |
| POI grounding for demo directives | Yes (`demo_pois.yaml`) | Expand map / VLM |
| Multi-model registry + versions | Yes | Load real checkpoints |
| Stub navigator (straight to goal) | Yes | Replace with CityWalker/NaVILA |
| Living city + pedestrians | No (need MetaUrban) | `drive_in_dynamic_env` |
| Don’t bump people | Reward stubs + velocity clamp | SocialNav + vision policy |

## Next host setup

1. Install Conda + Python 3.9, NVIDIA drivers/CUDA.  
2. `./scripts/setup_metaurban.sh`  
3. Download CityWalker and/or NaVILA checkpoints into `models/nav/`.  
4. Set `configs/navigation/default.yaml` → `active_model: citywalker_v1` (or `navila_v1`).  
5. Train / fine-tune via `MetaUrbanNavEnv` with `rl.reward: social_nav_v1`.
