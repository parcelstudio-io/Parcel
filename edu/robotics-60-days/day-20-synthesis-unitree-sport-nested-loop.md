# Day 20: Synthesis — Unitree Sport as a Nested Closed Loop

## Mental model

Module 2’s pieces snap into one architecture:

```text
slow semantic goals  →  body-velocity intent  →  fast balance/gait  →  motors
     (estimate)              (supervise)              (Sport)         (kHz)
```

Parcel closes outer loops with perception and odometry. `ControlManager` closes a mid loop on leases, freshness, limits, and stop confirmation. Unitree Sport closes the inner loop on IMU, joints, and contact. A successful `Move` is transport; measured `SportModeState` (via `UnitreeSportStateSource`) is how Parcel knows what the body reports. Actual physics remains Day 01’s unreachable ground truth — approximate it, never assume the ack.

This is nested **closed-loop** control, not open-loop gait playback from Python.

## Software-engineering analogy

Think of a three-tier production system:

| Tier | Parcel role | Analogy |
| --- | --- | --- |
| Product API | voice / nav / follow | request validation, auth, TTL |
| Edge proxy | `ControlManager` | rate limits, health checks, circuit breaker |
| Data plane | Unitree Sport + motors | the latency-critical path you do not reimplement in the API server |

You would not put payment clearing inside a Node request handler. Do not put balance inside the LLM or the 10 Hz runtime.

## Light equations (contracts, not plant ID)

```text
usable(cmd)   ⇔  now < valid_until  ∧  cmd ∈ ControlLimits  ∧  ¬E-stop
usable(state) ⇔  age(state) < state_timeout_s  ∧  |roll|,|pitch| ≤ max_tilt
stop_done     ⇔  N fresh settled samples after StopMove  (sequenced)
```

Layers reuse goals across their periods: nav may update at ~10 Hz while Sport tracks the latest leased twist many times per second.

## ASCII diagram

```text
voice/nav/follow/spatial/manual
            |
            v
     CommandArbiter (priority + TTL)
            |
            v
     VelocitySmoother ---> proximity/TTC ---> SCurveVelocityShaper
            |                                      (emergency bypass)
            v
     TimedVelocitySetpoint (base_link, leased)
            |
            v
     ControlManager @ control_hz (~50)
       freshness | limits | faults | stop confirm
            |
            +-----> UnitreeSportController.Move(vx,vy,vyaw)
            |              |
            |              v
            |         Sport gait/balance (onboard)
            |              |
            +---- UnitreeSportStateSource.latest()
                   RobotMotionState (rpy, vel, foot_forces, ...)
```

## Map to Parcel / Go2

**Codebase anchors (end-to-end nested loop):**

- Pipeline and authority table: `docs/MOTION.md` (read once end-to-end today).
- `RobotRuntime` (`src/parcel_robot/runtime.py`): `loop_hz=10`, owns `CommandArbiter`, `VelocitySmoother`, `_collision_safe`, `_motion_shaper` (`SCurveVelocityShaper`), dispatches into `control_manager`.
- `ControlManager` + `ControlTiming` / `ControlLimits` / `TimedVelocitySetpoint` / `RobotMotionState`: `src/parcel_robot/control/`.
- `UnitreeSportController` + `UnitreeSportStateSource`: `src/parcel_robot/control/unitree_sport.py` (`Move`, `StopMove`, `rt/sportmodestate`).
- Factory commissioning gates: `axes_commissioned`, `state_frame_commissioned`, nonempty `allowed_modes` in `control/factory.py`.
- Physical pose/trajectory still fail closed on the Sport path (`_run_pose` / `_run_trajectory`).
- Explicit non-claims (`docs/MOTION.md`): no precision commanded-vs-measured velocity servo; no certified host crash-stop; camera/LiDAR perception is separate from Sport body feedback.


## Why builders care

Day 20 is the hiring bar for Parcel motion work: can you point to the file that owns each responsibility and name what happens when each deadline misses? If you can, you will not put balance in Python, frames in comments, or success bits on RPC returns. Re-read `docs/MOTION.md` whenever you add a motion producer; new skills must enter through the arbiter and die through the same stop confirmation path.

Carry forward: clocks (11), delay (12), frames (13–14), kinematics boundary (15–16), contact humility (17), feedback vs supervision (18), constraints (19)—all present in one nested diagram.

Checklist before any physical PR merge: (1) single writer through `ControlManager`; (2) leased `base_link` setpoints; (3) commissioned frames/axes/modes; (4) stop confirmation from sequenced feedback; (5) shaping emergency bypass; (6) no pose/joint side channel; (7) independent hardware E-stop. If any box is unchecked, the nested loop is incomplete for unsupervised use.

Simulators help you test arbitration and TTLs; they do not waive commissioning.

Success metric for this module: you can explain why Parcel is nested closed-loop around Sport without claiming Parcel balances the dog.

## Failure story (integration)

Commissioning used the CLI path without populating `allowed_modes` and with `state_frame_commissioned: false`. The factory refused to build — good. A workaround temporarily forced the simulator adapter against a live DDS topic in a mixed config: commands looked fine in logs, feedback ages made no sense, and a stop could not confirm settled samples. The nested loop was mis-wired across clock/frame domains. Fix: dedicated physical driver process, commissioned frame/axes/modes, operator on hardware E-stop, and treat every layer’s timeout as a product requirement (Days 11–13), not a nuisance.

## Retrieval questions

1. Draw the nested loops and assign each: goal rate, feedback source, and failure action.
2. Why is Sport RPC success insufficient for “task complete” or “stopped”?
3. (Cumulative) Pick one concept from Days 11–19 (deadline, filter delay, frame, tilt, IK boundary, shaping, contact, PID vs supervisor, MPC intuition) and name the exact Parcel type or module that embodies it.

## Optional 10-minute exercise

Trace one imaginary `VelocityCommand(vx=0.2)` from `RobotRuntime` to `UnitreeSportController.update`. List the functions you would set breakpoints on (arbiter, smoother, collision gate, shaper, `ControlManager`, `Move`, `latest`). Note which timestamps you would log to verify leases and feedback age.
