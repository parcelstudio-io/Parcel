# Implementation: Skills catalog, city scene, and RL-ready Dog API

This document is the source of truth for Parcel’s skill system, stylized city
simulation scene, public `Dog` API, and Gymnasium-oriented RL hooks.

## Goals

- One YAML file per skill (20+), indexed by a catalog.
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

Callers (voice agent, ROS, `parcel-control`) must go through `Dog`. Safety remains
fail-closed for unknown skills, unsafe joints, and velocity limits.

## Simulation IPC

| type | payload |
| --- | --- |
| `pose` | name, duration, joints |
| `walk` | vx, vy, vyaw (+ optional gait style) |
| `trajectory` | name, keyframes |
| `stop` | — |

## City scene

`src/parcel_robot/scenes/city_block.xml` includes the Unitree Go2 model and adds:

- asphalt-like ground plane
- sidewalk strip + curb
- several building boxes
- bench
- crosswalk stripe geoms
- spawn near the sidewalk

Configured via `simulation.scene` in `configs/robot.yaml`.

## RL contract

- **Action:** 12 joint position targets (rad), applied with PD in sim / low-level.
- **Observation (v1, length 48):** base quat (4) + gyro (3) + joint q (12) +
  joint dq (12) + last action (12) + velocity command (3) + skill one-hot truncated /
  padded id embedding (2 reserved floats for skill index + progress).
- **Env:** `parcel_robot.rl.env.Go2Env` with Gymnasium-like `reset` / `step`.
- Training loops stay outside the voice process.

## Migration

Legacy inline `poses:` in package `robot.yaml` remain readable as a shim.
Canonical skills live under `configs/skills/`. Prefer
`configs/robot.yaml` going forward.

## Catalog (v1 skill ids)

stand, sit, bow, lie_down, stretch, hello_pose, crouch, look_left, look_right,
jump, hop, kick_front, kick_side, paw_wave, shake, recover_standup, play_bow,
walk_forward, walk_backward, strafe_left, strafe_right, turn_left, turn_right,
trot, run, crawl
