# Implementation: Skills catalog, city scene, and RL-ready Dog API

Implementation snapshot: 2026-08-04. This document describes Parcel’s skill
system, stylized city simulation scene, public `Dog` API, and
Gymnasium-oriented RL hooks. For operational status and deployment boundaries,
also read [CURRENT_STATUS.md](CURRENT_STATUS.md).

## Goals

- One YAML file per skill (26 enabled v1 skills), indexed by a catalog.
- User-selectable skills via voice, CLI, control panel, or Python API.
- Single public entry point: `Dog.execute(skill_id, ...)`.
- Stylized MuJoCo city block for locomotion / navigation testing.
- RL-ready env stubs without blocking product UI on trained policies.

## Taxonomy

| kind | Preview behavior | Example |
| --- | --- | --- |
| `pose` | Hold joint targets | sit, bow |
| `trajectory` | Timed keyframes | jump, kick_front |
| `gait` | Cyclic gait + body velocity | trot, run, crawl |
| `velocity` | Body-frame Move command | walk_forward |
| `policy` | ONNX/TorchScript runner slot | (filled later) |

Dynamic skills (jump / run / kick) ship as authored previews first. Each file may
include an `rl:` block so a trained policy can replace the preview later without
changing the public API.

“Preview” is load-bearing: the YAML proves catalog/dispatch/simulator plumbing,
not that a motion is dynamically stable or safe on a physical Go2. A skill with
`rl.policy_path` is only recognized as armed today; no general ONNX/TorchScript
inference runner is connected to `SkillExecutor`.

## Directory layout

```text
configs/
  robot.yaml
  skills/
    catalog.yaml
    poses/*.yaml
    trajectories/*.yaml
    gaits/*.yaml
    velocity/*.yaml
src/parcel_robot/
  skills/          # schema, catalog, executor, api
  rl/              # Go2Env, spaces, rewards
  scenes/city_block.xml
docs/IMPLEMENTATION_SKILLS_CITY_RL.md
```

## Skill YAML schema

```yaml
id: jump
name: Jump
kind: trajectory          # pose | trajectory | gait | velocity | policy
enabled: true
tags: [dynamic, aerial]
duration: 0.8             # pose / trajectory
joints:                   # pose only
  FL_hip_joint: 0.0
  # ...
keyframes:                # trajectory only
  - t: 0.0
    joints: { FL_thigh_joint: 0.9, ... }
  - t: 0.25
    joints: { FL_thigh_joint: 1.3, ... }
velocity:                 # velocity / gait defaults
  vx: 0.3
  vy: 0.0
  vyaw: 0.0
gait:                     # gait only
  style: trot             # trot | run | crawl
  frequency_hz: 1.6
rl:
  enabled: false
  policy_path: ""
  action_dim: 12
  obs_dim: 48
  reward: jump_height
  control_dt: 0.02
```

`configs/skills/catalog.yaml` lists skill ids (or discovers `**/*.yaml` and
filters by `enabled`).

## Public API

```python
from parcel_robot.skills.api import Dog

dog = Dog.from_config("configs/robot.yaml")
dog.list_skills(tag="locomotion")
dog.select("jump")
dog.execute("kick_front")
dog.execute("trot", vx=0.4)
dog.stop()
obs = dog.obs()
dog.step_policy(action)
```

`Dog` fails closed for unknown/disabled skill IDs and malformed skill
definitions. It does **not** validate arbitrary velocity overrides against the
runtime's limits or provide a general joint-safety boundary.

`Dog` is the reusable catalog/execution API, not the complete product safety
boundary. Direct `Dog.execute()` and simulator IPC calls do not provide
`RobotRuntime`'s activity priorities, fresh perception checks, collision veto,
or centralized E-stop semantics. Use the browser/runtime path for end-to-end
behavior and safety work; use direct `Dog` calls for bounded development and
tests.

This distinction is also a physical authority boundary. `RobotRuntime` rejects
physical pose/trajectory dispatch after stopping because no controller-owned
whole-body handoff exists. Constructing a `Dog` or `MotionRouter` directly must
not be treated as a supported way around that rejection.

## Simulation IPC

| type | payload |
| --- | --- |
| `pose` | name, duration, joints |
| `walk` | vx, vy, vyaw (+ optional gait style) |
| `trajectory` | name, keyframes |
| `expression` | additive joint offsets from the subordinate 50 Hz expression channel |
| `stop` | — |

## City scene

`src/parcel_robot/scenes/city_block.xml` includes the Unitree Go2 model and a
compact semantic city block: road/sidewalk/crosswalk regions, buildings,
storefront/POI and street-furniture geometry, owner, pedestrians, and cyclist
proxies. `DynamicCity` advances seeded actor routes; the simulator publishes
their tracks plus LiDAR and semantic regions/objects through versioned IPC.

This is deliberately a deterministic regression world. Actor trajectories are
scripted rather than mutually responsive ORCA behavior, semantic labels are
simulator-generated, and base motion remains kinematic. `grid_v1` can add a
soft constant-velocity predicted cost for published tracks, but that planner
feature does not make the actors interactive or the camera semantics
perception-realistic. See
[DYNAMIC_CITY_AND_BEHAVIOR.md](DYNAMIC_CITY_AND_BEHAVIOR.md) for the richer
backend plan.

Configured via `simulation.scene` in `configs/robot.yaml`.

## RL contract (honest stub)

- **Action:** 12 joint position targets (rad). With `use_mujoco=True`, the
  experimental env applies approximate PD in local MuJoCo. Otherwise the stub
  records the action in its observation only. No physical low-level policy
  runner is implemented.
- **Observation (v1, length 48):** base quaternion (4) + angular velocity (3) +
  joint q (12) + joint dq (12) + last action (12) + velocity command (3) +
  scalar skill index (1) + episode progress (1). The current simulator mapping
  is intentionally approximate and is not a stable learned-policy ABI yet.
- **Env:** `parcel_robot.rl.env.Go2Env` exposes a Gymnasium-like `reset` / `step`
  shape for experiments, but it is **not** a training-ready locomotion stack
  (rewards / termination, terrain, randomization, actuator/sensor delay, and
  sim-to-real validation are incomplete). Prefer the redesign deferred path
  (`unitree_rl_*` lineage → ONNX) when RL locomotion is funded.
- Training loops stay outside the voice process.

## Crucial design choices and tradeoffs

| Choice | Advantage | Limitation / consequence |
| --- | --- | --- |
| Data-driven skill catalog | Adding a curated pose, trajectory, gait, or velocity preview does not require editing the public API | YAML validity and catalog admission prove structure, not dynamic stability or physical safety |
| One `Dog.execute()` entry point | Tests, UI, voice adapters, and future training code share the same vocabulary | The direct API is intentionally below product arbitration and can accept unbounded velocity overrides; callers must not confuse composability with safety authority |
| Preview first, policy replacement later | Choreography and product flows can be exercised before funding locomotion training | A non-empty `policy_path` currently means “armed” only; no file validation, inference, observation normalization, or action delivery occurs |
| Kinematic city base motion | Fast, deterministic semantic and collision regression on the official Go2 geometry | It does not test balance, contact, slip, footholds, actuator limits, or Sport tracking |
| Fixed 48-value experimental observation | Small, inspectable scaffold for API experiments | Approximate field mapping, placeholder reward/termination, and no stable ABI make existing policies non-portable without an explicit versioned contract |
| Training outside the voice/runtime process | GPU jobs and simulator failures cannot stall the conversational control loop | A trained policy still needs a bounded serving/validation adapter before it can become a runtime controller |

## Migration

Legacy inline `poses:` in package `robot.yaml` remain readable as a shim.
Canonical skills live under `configs/skills/`. Prefer
`configs/robot.yaml` going forward.

## Catalog (v1 skill ids)

stand, sit, bow, lie_down, stretch, hello_pose, crouch, look_left, look_right,
jump, hop, kick_front, kick_side, paw_wave, shake, recover_standup, play_bow,
walk_forward, walk_backward, strafe_left, strafe_right, turn_left, turn_right,
trot, run, crawl
