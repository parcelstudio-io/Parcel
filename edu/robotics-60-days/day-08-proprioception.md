# Day 08: Proprioception

## Mental model

**Proprioception** is sensing the robot’s own body: joint angles and rates, IMU orientation/angular rate/acceleration, contact or foot forces, motor current and temperature, battery health. It answers “how am I configured, accelerating, and straining?” — not “who is the owner?”

Without proprioception, balance and gait are blind. With only proprioception, the dog can stand and walk in an empty room but cannot socially navigate a sidewalk. Parcel’s product surface emphasizes camera and LiDAR, but a physical Go2 still needs encoders and an IMU inside Unitree’s loop (`edu/INTRO.md`).

A useful split:

```text
encoders + IMU (+ current/contact) = private body/runtime state
camera + LiDAR (+ mic)             = application-visible world perception
```

In config terms, `perception.spatial_sensors: [camera, lidar]` in `configs/robot.yaml` does **not** mean proprioception is optional on hardware.

## Software-engineering analogy

Proprioception is **process-private telemetry**: thread dumps, GC stats, disk SMART — vital to keep the service up, usually not the public API response. Exteroception is request/response payload about the outside world. Mixing them without labels is how you accidentally ship internal heap addresses to clients — or how you let an LLM “fix” a tip using a camera bounding box.

Freshness matters the same way lease expiry matters in distributed systems: a perfect encoder sample from 500 ms ago is a lie about now.

## Light equations / signals

```text
q, q̇          joint position, velocity   (encoders)
ω, a, attitude IMU angular rate, accel, orientation
F_foot         contact / force proxies
I_motor, T°    effort and thermal
age = t_now - t_stamp
usable ⇔ age < state_timeout_s   # ControlTiming
```

Fusion intuition (detail later): prediction from dynamics + correction from measurements. For today: **raw ≠ estimated ≠ actual**. Bias, delay, and missing contact still leave “actual” unobserved.

## ASCII diagram

```text
  encoders ─┐
  IMU ──────┼─► Sport / estimator ─► body pose, contact belief
  current ──┤         │
  foot F ───┘         │
                      ▼
              RobotMotionState (host-side sample)
                      │
                      ▼
              ControlManager freshness / tilt / settle

  camera/LiDAR ──► SimObservation ──► nav / follow  (Day 09)
```

## Map to Parcel / Go2

- Host-visible body feedback: `RobotMotionState` in `src/parcel_robot/control/models.py` — `roll/pitch/yaw`, `velocity` (contracted as `base_link` even when vendors report odom-frame rates), optional `joint_positions` / `joint_velocities` / `foot_forces`, `fault_reason`, monotonic `received_at` + increasing `sequence`.
- Sport state path: `configs/robot.yaml` → `control.unitree_sport.state_topic: rt/sportmodestate`. Comments require commissioning `state_velocity_frame` and `state_frame_commissioned` — wrong frame is a proprioceptive lie that looks like a tuning bug.
- `ControlTiming.state_timeout_s` and `ControllerStatus.feedback_age_ms`: stale proprioception ⇒ stop (`docs/MOTION.md`). Sequence monotonicity matters for stop confirmation.
- Tilt gate uses measured roll/pitch vs `max_tilt_rad` (Day 04). Settling uses measured speed vs `settled_linear_speed_mps` (Day 03).
- Battery proprio/health: `BatteryStateSnapshot` from runtime config until hardware replaces simulation (`brain/contracts.py`, `runtime.py`).
- Brain observations can carry `measured_velocity` into snapshots (`src/parcel_robot/brain/observations.py`) — label it measured, not commanded.

Application code should not need raw IMU at 1 kHz; it needs fresh, framed, fault-classified summaries — and must never block Sport’s private loop waiting for Python.

## Failure story

A commissioning host displayed Sport “velocity” without verifying `state_velocity_frame`. Operators tuned follow gains against odom-frame numbers interpreted as `base_link`. The dog crab-walked and oscillated on yaw. The sensors were fine; the **frame metadata** was ignored. Fix: fail closed until `state_frame_commissioned` is true; never silently reinterpret axes (`lateral_sign` / `yaw_sign` in the same YAML block).


## Building habit

Treat frame metadata as part of the sensor reading. A velocity without `state_velocity_frame` (and commissioning flags) is incomplete data—fail closed rather than assuming `base_link`. Monitor `feedback_age_ms` / `state_timeout_s` in the same dashboards as navigation latency; stale proprioception is a stop condition, not a warning toast. Keep product code on summarized `RobotMotionState` fields; do not pull raw IMU into the LLM context “for better balance.” When `joint_positions` is empty under Sport high-level mode, that is expected—do not invent joint PD features that require LowState until capabilities flip. Label brain snapshot velocities as measured when they come from feedback (`brain/observations.py`).

Proprioception owns the private survival loop. Exteroception (next day) owns the public world model. Crossing those streams without labels creates false confidence: a beautiful owner track does not mean the body is upright, and a perfect IMU sample does not mean the sidewalk is clear.


Contact sensing deserves special skepticism. Foot-force fields on `RobotMotionState` may be empty, delayed, or vendor-scaled; never treat absence as “no contact” without an explicit capability bit. Until low-level joint/contact feeds are commissioned, assume Sport’s private estimator owns contact truth and Parcel only consumes the summarized body state needed for tilt, settle, and fault classes.

## Retrieval questions

1. List four proprioceptive channels a Go2 balance stack needs that camera/LiDAR do not replace.
2. Which Parcel type carries host-side body feedback, and which timeout bounds its age?
3. (Day 01) If `joint_positions` is empty on Sport high-level mode, which state kinds are you missing for a custom joint PD idea?

## Optional 10-minute exercise

Open `RobotMotionState` and `configs/robot.yaml` `control.unitree_sport`. Write one sentence for each of: `state_topic`, `state_velocity_frame`, `state_timeout_s` — what bug each prevents.
