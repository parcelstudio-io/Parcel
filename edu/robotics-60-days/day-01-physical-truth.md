# Day 01: Physical Truth vs Software State

## Mental model

In a web service, a successful write usually means the system state changed. On a robot, a successful *command* only means a message left your process. Keep five notions of state separate:

```text
commanded  -> what you asked for
acked      -> what the transport/controller admitted receiving
measured   -> what sensors reported (noisy, delayed)
estimated  -> your fused belief about the body/world
actual     -> what physics did (never fully observed)
```

Command success ≠ motion. Ack ≠ measurement. Measurement ≠ truth. Estimation ≠ ground truth. Parcel’s companion brain reasons on estimates and beliefs; Unitree Sport and the motors own the physical chain that approximates actual state.

The deepest SE habit in this course: **never let a green log line from the wrong state kind authorize a physical claim.** “RPC OK,” “path length consumed,” and “sit skill dispatched” are not “dog moved safely.”

In Parcel, commanded vs measured body velocity shows up side-by-side on `ControllerStatus.target` and `ControllerStatus.measured` in `src/parcel_robot/control/models.py` (plus `tracking_error` in `as_dict()`).

## Software-engineering analogy

Treat the robot like a distributed database with an unreliable replica and no transactional commit across physics.

- Publishing a `VelocityCommand` (`src/parcel_robot/models.py`) is enqueueing a write.
- Sport accepting an RPC is the primary accepting the request — still not durable motion.
- Joint encoders and IMU samples are laggy replica reports from another node.
- Odometry / owner track is a materialized view: useful, eventually inconsistent.
- Reality is the durable store you cannot query; you only get stale, lossy projections.

You would never mark a payment “settled” because the message broker returned 200. Do not mark “walked 1.5 m around owner” because navigation emitted a trajectory or Sport accepted a setpoint.

## Light equations

```text
t_actual_effect  ≥  t_command_sent + transport_delay + actuator_delay
age(measurement) = t_now - t_sensor_stamp
usable(estimate) ⇔ age(measurement) < freshness_budget
```

Stale estimates are expired cache. `TimedVelocitySetpoint.valid_until` and `ControlTiming.state_timeout_s` in `control/models.py` encode leases and feedback age budgets. `docs/MOTION.md` describes the same idea as nested closed loops with watchdogs: transport delivery is not a met motion deadline.

## ASCII diagram

```text
  LLM / behavior          Parcel ~10 Hz           Unitree Sport
  "circle owner"   --->   VelocityCommand   --->  gait/balance loop
       |                      |                      |
   semantic belief      commanded vx,vy,vyaw    joint torques
       |                      |                      |
   "task done?"  <---   estimated pose/owner  <--- encoders + IMU
                         (measured + fused)

  actual body pose/velocity: only approximated by the right-hand chain
```

## Map to Parcel / Go2

- Application motion is a body-frame `VelocityCommand`. The exclusive writer is `ControlManager` (`src/parcel_robot/control/manager.py`). The authority ladder (arbiter → smoother → gates → manager → Sport) is spelled out in `docs/MOTION.md`.
- Leased setpoints are `TimedVelocitySetpoint` (`frame` must be `base_link`). Timing/limits knobs live under `control:` in `configs/robot.yaml` (`command_timeout_s`, `state_timeout_s`, `settled_linear_speed_mps`).
- `RobotStateSource.latest()` feeds `RobotMotionState`: measured velocity, roll/pitch/yaw, optional `joint_positions` / `foot_forces`, and `fault_reason` (`TILT`, `COMMS`, `POWER`). Sequence numbers must increase so stop confirmation can trust ordering.
- Simulator backends expose MuJoCo-private truth via `SimObservation` (`src/parcel_robot/backends/base.py`). Hardware has no equivalent “ask the world oracle” API — do not design features that require it.
- Product sensors are declared as `perception.spatial_sensors: [camera, lidar]` in `configs/robot.yaml`. Encoders and IMU remain private body/runtime state for Sport even when the product UI never shows them.

Classify every logged field: `cmd`, `ack`, `meas`, `est`, or `belief`. If you cannot classify it, you do not understand the next production bug.

## Failure story

A follow skill marked success when the last controller `update()` returned without error and the planned path length was consumed. On wet tile the Go2’s feet slipped; Sport kept accepting velocity setpoints while body progress stalled. Owner-relative error grew; the dog “completed” the orbit in software, sat on command, and was still beside a planter short of the intended circle. The ack path was green; measured crawl and LiDAR owner bearing never agreed with the plan. Fix: completion predicates must use measured/estimated progress with timeouts — the same spirit as `ControllerStatus.stop_confirmed` requiring settled *measured* speed, not merely a zero command.


## Building habit

Before merging any motion feature, force the PR description to answer: what is commanded, what is measured, and what predicate proves completion? If the answer cites only RPC success or path-length consumption, reject it. Prefer logging `ControllerStatus` fields (`target`, `measured`, `command_age_ms`, `feedback_age_ms`, `stop_confirmed`) over inventing a parallel “motion OK” boolean in behavior code. When writing evals, assert on `SimObservation` / `RobotMotionState` quantities with timeouts, and keep simulator-private truth out of production APIs. Treat `configs/robot.yaml` timeouts (`command_timeout_s`, `state_timeout_s`) as product safety knobs, not tuning trivia—changing them changes which stale commands can still move a Go2.

## Retrieval questions

1. Name the five state kinds and give one Parcel symbol or field for commanded vs measured velocity.
2. Why can Sport acknowledging a setpoint still leave task-complete logic wrong?
3. (Preview) If Parcel runs ~10 Hz and Sport balances faster, which layer may own joint torques, and why?

## Optional 10-minute exercise

Open `src/parcel_robot/control/models.py`. For `TimedVelocitySetpoint`, `RobotMotionState`, and `ControllerStatus`, label each field as commanded, measured, estimated, lifecycle, or bookkeeping. Note one unsafe “success” signal if you confuse `target` with `measured`.
