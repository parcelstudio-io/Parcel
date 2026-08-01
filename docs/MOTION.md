# Motion backends: Sport Move and RL locomotion

Parcel routes walking through a single **motion router**. Exactly one locomotion
backend is active at a time:

```text
voice / LLM tool call
        │
        ▼
  SafetySupervisor ──► MotionRouter
                          │
              ┌───────────┴───────────┐
              ▼                       ▼
     SportMoveBackend          RLPolicyBackend
     (Unitree Move)            (policy / sim)
```

Poses (`sit`, `bow`, …) are separate from walking. Starting a pose stops the
active walk backend.

## Configure

In [`src/parcel_robot/config/robot.yaml`](../src/parcel_robot/config/robot.yaml):

```yaml
motion:
  backend: rl          # or sport
  max_vx: 0.6
  max_vy: 0.4
  max_vyaw: 1.0
  sport:
    enabled: false     # true only with unitree_sdk2py + DDS
    interface: lo
    domain_id: 1
  rl:
    enabled: true
    policy_path: ""    # optional .onnx or TorchScript .pt/.pth
    control_dt: 0.02
```

## Voice / text commands

```bash
source .parcel/bin/activate
parcel-agent --text "walk forward"
parcel-agent --text "walk backward"
parcel-agent --text "turn left"
parcel-agent --text "turn right"
parcel-agent --text "use sport backend"
parcel-agent --text "use rl backend"
parcel-agent --text "stop"
```

With MuJoCo preview:

```bash
# terminal 1
parcel-sim

# terminal 2
parcel-agent --sim --text "walk forward"
```

`parcel-sim` applies a crude free-base velocity for walk intents so the stack can
be tested end-to-end before a real gait policy is loaded.

## Sport Move backend

Uses Unitree Go2 SportClient `Move(vx, vy, vyaw)` when:

1. `motion.backend: sport`
2. `motion.sport.enabled: true`
3. `unitree_sdk2py` is installed and CycloneDDS is available
4. Official Unitree MuJoCo (`simulate_python`) or a physical dog is on the DDS domain

Until those are ready, leave `enabled: false`. The stub still records commands so
agent parsing and safety can be developed offline.

## RL policy backend

1. Train or obtain a Go2 locomotion policy (ONNX or TorchScript).
2. Set `motion.rl.policy_path` to that file.
3. Keep `motion.backend: rl`.
4. Call `RLPolicyBackend.act(observation)` from your control loop (sim or
   low-level robot). Parcel arms the velocity command; the loop must supply
   observations and apply joint targets/torques each tick.

Without a policy file the backend still accepts walk intents and can forward
them to `parcel-sim`.

## ROS topic

When running with `--ros`, walk intents are published on:

| Topic | Type | Payload |
| --- | --- | --- |
| `/parcel/walk_request` | `std_msgs/String` | `{"vx": …, "vy": …, "vyaw": …}` |

A downstream controller should subscribe and drive either Sport Move or an RL
runner—never both at once.

## Safety

`set_velocity` is fail-closed: non-finite values and velocities above
`max_vx` / `max_vy` / `max_vyaw` are rejected. `stop` engages the emergency latch
and stops the active backend.
