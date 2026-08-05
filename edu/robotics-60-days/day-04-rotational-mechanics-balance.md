# Day 04: Rotational Mechanics and Balance

## Mental model

A standing quadruped is a balancing act: gravity pulls down through the center of mass (CoM); the ground pushes up through the feet. If the vertical projection of the CoM leaves the recoverable region defined by stance feet (the support polygon, simplified), tipping moments grow and the body rotates. **Balance is rotational mechanics under gravity and contact constraints**, not a boolean `is_upright` flag in your app state.

Parcel may command yaw rate and body velocity; the onboard controller fights roll/pitch disturbances using IMU and joint feedback at rates Parcel’s Python loop cannot match. Your job at the application layer is to avoid demanding motions that make recovery impossible — and to stop cleanly when attitude already looks lost.

In Parcel, attitude safety is a last-line gate: `ControlManager` faults when `|roll|` or `|pitch|` exceeds `limits.max_tilt_rad` (`src/parcel_robot/control/manager.py`), configured as `control.max_tilt_rad` in `configs/robot.yaml` (default 0.75 rad).

## Light equations

```text
τ = r F sinφ            # torque = lever arm × force (magnitude)
Στ = I α                # net torque → angular acceleration
L = I ω                 # angular momentum
# static intuition:
stable if CoM_horizontal ∈ support_polygon(stance feet)
tipping moment ~ m g * horizontal_offset_of_CoM
```

Roll tips sideways; pitch tips nose up/down; yaw spins about vertical (navigation’s usual rotation). `max_tilt_rad` fences measured attitude — it is **not** a balance controller and does not replace Sport.

## Software-engineering analogy

Balance is a hard real-time invariant maintained by a privileged kernel path (Unitree Sport + motor ISRs). Parcel is user space: it may request `vyaw` and body velocity, but it must not disable or starve the kernel path. Tilting past a limit is like a kernel panic watchdog — `FaultReason.TILT` — after which playful follow features are irrelevant until safe state is restored.

Narrow support (three-leg or two-leg phases in a gait) is like running with fewer redundant replicas: the same disturbance budget no longer holds. Scheduling a low-priority “cute gesture” onto the joints during that window is a priority inversion with bruises.

## ASCII diagram

```text
        CoM
         •
        /|\          gravity mg down
       / | \
      F  |  F        ground reactions at feet
     ====+====
     support polygon (top view)

     CoM projection inside → restoring possible
     CoM projection outside → growing tip τ = mg * d

     yaw command (Parcel)     roll/pitch recover (Sport)
           |                            |
           v                            v
        turn in place              keep CoM recoverable
```

## Map to Parcel / Go2

- Morphology: 12 actuated DoF via `RobotProfile` (`src/parcel_robot/robot_profile.py`) — legs `FL/FR/RL/RR` × `hip_joint` / `thigh_joint` / `calf_joint`. During gait the support polygon shrinks and moves every step.
- Yaw command: `VelocityCommand.vyaw` (rad/s), capped by `motion.max_vyaw` / `ControlLimits`. Used by face-owner / orbit behaviors under `spatial_behaviors` and `owner_follow` in `configs/robot.yaml`.
- Stand geometry: `stand_joint_angles_rad` and `stance_z_m` set a crouched CoM height (`stance_z_m ≈ -0.265`). Lower CoM generally improves tip resistance; extreme crouch can hurt mobility and joint torque margins.
- `ControllerCapabilities.high_level_balance=True` on Sport adapters (`control/unitree_sport.py`); `low_level_joint_control=False` — Parcel does not claim joint-level balance authority (`docs/MOTION.md`).
- Scripted simulator gaits and joint animations are open-loop previews (`edu/INTRO.md`). Physical deployments should rely on Unitree’s locomotion controller for balance.

If the dog begins tipping: IMU sees it in milliseconds; Sport adjusts legs in a few milliseconds; Parcel navigation may notice attitude/velocity change tens of ms later; conversation explaining the stumble is irrelevant to the save.

## Failure story

A “cute sit-from-walk” gesture blended a scripted rear-hip motion while Sport was still in a trot on a slope. The gesture briefly unloaded the uphill feet; CoM projection left the support polygon; roll grew; tilt fault fired; the dog caught itself in a sprawl that scared the owner. Root cause: a low-priority expression preempted stance assumptions only the balance controller understood. Policy fix: queue gestures behind locomotion stability; never inject open-loop joint theatre on hardware while gait is active (pose path vs velocity lease — see `docs/MOTION.md`).


## Building habit

Never schedule open-loop joint gestures while Sport owns an active gait on hardware; queue them behind a confirmed velocity stop (`docs/MOTION.md` pose vs velocity ownership). If you change stand height or crouch for aesthetics, re-check tip margin and torque on slopes conceptually before a fenced test. Treat `FaultReason.TILT` and `max_tilt_rad` trips as hard inhibits—do not auto-retry follow. When reviewing yaw-heavy behaviors (`owner_follow`, orbit), ask whether the support polygon during the gait phase can absorb the yaw transient. Keep `ControllerCapabilities.high_level_balance` as a reminder: Parcel supervises attitude fences; it does not replace onboard balance.

## Retrieval questions

1. In one sentence, when does a static quadruped begin to tip, in terms of CoM and support polygon?
2. Why must Parcel treat `vyaw` as a navigation input while leaving roll/pitch recovery to Sport?
3. (Day 03) How does a higher forward speed make rotational tip recovery harder even if yaw limits are unchanged?

## Optional 10-minute exercise

Sketch a rectangle for four stance feet and mark CoM. Move CoM outside one edge and draw the gravity lever arm `d`. Then find the tilt check near `max_tilt_rad` in `src/parcel_robot/control/manager.py` and note which lifecycle/fault path it triggers.
