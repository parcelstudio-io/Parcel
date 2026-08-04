# City navigation: grid planner, registry, and MetaUrban path

Canonical architecture context:
[REDESIGN_2026_ARCHITECTURE.md](REDESIGN_2026_ARCHITECTURE.md) and
[COMPANION_NAVIGATION_ARCHITECTURE.md](COMPANION_NAVIGATION_ARCHITECTURE.md).
City scene / social behavior details:
[DYNAMIC_CITY_AND_BEHAVIOR.md](DYNAMIC_CITY_AND_BEHAVIOR.md).

## Reality check

- MuJoCo `city_block.xml` is the active living-city regression scene (seeded
  pedestrians, cyclist, owner, track telemetry).
- Production navigator is **`grid_v1`**: rolling log-odds occupancy + inflated
  footprint + A* over the calibrated raycast planar scan. Missing scan
  degrades **loudly** (`scan_missing_fallback` note + warning), not silently.
- Host note: RTX-class GPU + Python 3.14 `.parcel` venv. MetaUrban still needs
  a separate Conda Python 3.9 environment and must not be imported into the
  Parcel runtime.

## Stack

```text
directive
  → Goal resolver (POI → semantic map → bounded active visual search)
  → NavigatorModel (grid | stub; learned types fail closed)
  → MidLevelCommand (vx, vy, vyaw) or stop
  → Dog / runtime arbiter / collision gate
  → ControlManager → LocomotionController
  → SimulatorBackend (MuJoCo now; MetaUrban / URBAN-SIM / SimWorld later)
```

## Code layout

```text
configs/navigation/
  default.yaml                 # active_model: grid_v1
  models/{grid,stub,...}.yaml
  cities/demo_pois.yaml
  experiments/                 # offline BARN / planner experiment profiles
src/parcel_robot/navigation/
  pipeline.py                  # DirectiveNavigator
  grid_navigator.py            # production grid planner wrapper
  grid_planner.py              # LidarScan + RollingOccupancyGrid + A*
  models/__init__.py           # stub + grid only
  envs/metaurban_env.py        # offline kinematic scaffold
evals/companion_nav/           # product companion scenarios
evals/external/                # BARN / Habitat research proxies
```

## Public API

```python
from parcel_robot.navigation import DirectiveNavigator

nav = DirectiveNavigator.from_config("configs/navigation/default.yaml")
mission = nav.start("I want you to go to the coffee shop at 42nd street")
while not nav.done():
    cmd = nav.step(observation)
```

`MetaUrbanNavEnv` is an offline kinematic scaffold. `use_metaurban=True` raises
`NotImplementedError` by design: importing the vendor env is not a Parcel
backend. Also exposed on `Dog.navigate(...)` when `navigation.config` is set.

### Open-world semantic goals

Unknown destinations become typed semantic object/region goals. The search
controller rotates in place, requires repeated confidence-qualified
observations, builds a footprint-cleared pose, then hands off to the point-goal
navigator. Progress and terminal-stop verification fail closed on stale
perception or unsettled velocity. Simulator semantic polygons are diagnostics
only — production must use real camera/LiDAR features.

### Headless gate

```bash
python -m pytest -q \
  tests/test_headless_city_tasks.py \
  tests/test_mujoco_lidar.py \
  tests/test_city_orbit_clearance.py
```

Base motion in that gate is kinematic (`mj_forward`); it is a behavior
regression, not Sport or learned-gait qualification.

## Registry: what works vs research

| Capability | Today | Later |
| --- | --- | --- |
| `grid_v1` over raycast scan | Production default | Terrain / elevation mapping |
| `stub_v0` point-goal | Loud fallback / tests | Keep for A/B |
| POI + semantic search | Yes | Real open-vocab perception |
| CityWalker / NaVILA / NoMaD / ViNT | YAML metadata + checkpoints only | Inference adapter + tests |
| Living-city pedestrians | Seeded MuJoCo | MetaUrban IPC service |
| Product companion eval | `evals/companion_nav/` | Expand scenario ledger |
| Offline BARN / Habitat | `evals/external/` | Never treat as product score |

`build_navigator` accepts only `stub` and `grid`. Selecting a learned type
raises; re-add a type only with a working adapter.

## Recommended later simulation backends

| Backend | Best use |
| --- | --- |
| MetaUrban | First procedural SocialNav service (Python 3.9 IPC) |
| URBAN-SIM / Isaac Lab | Articulated Go2 city training |
| SimWorld | Photoreal demo profile |
| MuJoCo Parcel scene | Daily tests (active) |

Install MetaUrban on a Conda 3.9 + GPU host:

```bash
./scripts/setup_metaurban.sh
```

Keep `active_model: grid_v1` until a learned adapter is tested end-to-end.

## Local context

`parcel_robot.context.ContextBuilder` builds typed location/time/map/scene
fields in-process. `query_context` flags default off; exact coordinates stay
out of the voice prompt unless explicitly enabled.
