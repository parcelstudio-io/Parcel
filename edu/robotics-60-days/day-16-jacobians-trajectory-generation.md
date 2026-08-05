# Day 16: Jacobians and Trajectory Generation

## Mental model

If FK says where the foot is, the **Jacobian** \(J(q)\) says how foot velocity relates to joint velocity:

```text
v_foot ≈ J(q) · q̇
```

Near a singularity, \(J\) loses rank: large joint rates produce tiny task motion (or the mapping blows up when inverting). Redundant robots have a null space: joint motion that does not move the task point — useful for posture optimization, dangerous if uncontrolled.

A **trajectory** is a timed path: not only “go to \(x\)” but \(x(t)\) with velocity and acceleration limits. Splines and S-curves bound jerk so actuators and contact do not chatter. Parcel’s outer stack generates *body-velocity* trajectories (and shapes them); Sport turns those into foothold timing internally.

## Software-engineering analogy

The Jacobian is a local linearization — like a derivative of an API mapping for small deltas. Inverting a near-singular Jacobian is dividing by a near-zero scale factor in a hot path: huge commands from tiny errors. Trajectory generation is rate-limiting and backpressure: you do not dump an unbounded burst onto a worker. Jerk limits are analogous to connection drain policies — change load gradually unless it is an emergency cancel.

## Light equations

```text
v = J(q) q̇
q̇ = J⁺ v + (I - J⁺ J) q̇_null     (redundant case)

spline / S-curve intuition:
  |a| ≤ a_max,  |jerk| ≤ j_max  ⇒  smoother tracking, more lag
```

Body SE(2) command shaping (Parcel) is the holonomic cousin: limit \(\dot v_x, \dot v_y, \dot v_{yaw}\) and their jerks before the vendor loop.

## ASCII diagram

```text
task space                  joints
  foot vel v  <--- J(q) ---  q̇
       ^                      |
       |   near singularity   |
       +---- ill-conditioned -+

Parcel trajectory (body):
  planner setpoints --> VelocitySmoother --> SCurveVelocityShaper --> lease
                                                         |
                                                    Sport gait (internal)
```

## Map to Parcel / Go2

**Codebase anchors (vel mapping / trajectories):**

- Outer “Jacobian substitute” for companion motion is not leg \(J\): it is bounded SE(2) command generation. `VelocitySmoother.step` (`src/parcel_robot/core/velocity_smoother.py`) limits accel/decel; `SCurveVelocityShaper` (`navigation/velocity_shaping.py`) limits jerk; both sit in `RobotRuntime` before `ControlManager`.
- `motion.shaping.*` in config / `docs/MOTION.md` (`linear_max_accel`, `linear_max_jerk`, yaw twins, `calm_scale`) tune that envelope — not foot-swing polynomials in Python.
- `ControllerStatus.tracking_error` exposes target−measured twist for logs; Parcel does **not** invert a plant Jacobian to null that error in the manager.
- Sim trajectories: `sim_ipc.publish_trajectory` / `RobotRuntime._run_trajectory` — physical path rejects direct backend trajectory when using a real `control_manager` (must be controller-owned).
- Future custom locomotion that disables Sport must own Jacobians, swing trajectories, and singularities inside a native high-rate process — see `docs/MOTION.md` custom controller sketch and “Never publish LowCmd while Sport mode is active.”


## Why builders care

Most Parcel “trajectory” work you will ship this quarter is SE(2) timing: accelerate, cruise, decelerate, and cancel without exciting gait. Leg Jacobians matter when you replace Sport—not when you circle an owner. Still, singularity intuition transfers: any map from task error to huge commands under a near-zero scale factor is a Jacobian-like hazard (including `tracking_error` / delay / high gain). Prefer bounded shaping and outer replanning over aggressive inversion.

Commission shaping limits on hardware the same way you commission axis signs: small moves, measure overshoot and stop time, then raise envelopes. Simulator snappiness is not evidence.

Differential kinematics also explains why rotate-first navigation is popular: large heading error mapped through a naive Cartesian controller produces ugly coupled sideways demands. Parcel’s turn-then-forward preference keeps the body Jacobian of the *task* better conditioned for companion readability, even though Sport could strafe.

Timed trajectories need cancel semantics: when the arbiter or E-stop wins, the shaped command must drop via emergency path, and `ControlManager` must confirm settle. A spline that continues playing after cancel is a trajectory generator bug with physical teeth.

If a PR claims “trajectory tracking,” demand the frame, the timing law, and which loop closes the error—shaper, Sport, or neither.

Keep the mental model crisp: equations guide reviews; code and commissioning make them real.

## Failure story

A nav tweak removed yaw accel limits to “turn snappier.” The S-curve still limited linear jerk, but yaw steps excited Sport’s gait into a brief spin-wobble that the tilt watchdog nearly faulted. Separately, a research branch tried numerical IK + Jacobian pseudoinverse in the 10 Hz Python loop for footholds; compute spikes missed Sport refresh and the lease watchdog stopped the dog mid-stride. Fix: keep body shaping limits commissioned; keep leg differentials off the behavior core.

## Retrieval questions

1. What does \(v \approx J(q)\dot q\) mean operationally, and what goes wrong near a singularity?
2. How does Parcel approximate “trajectory generation” today without computing leg Jacobians?
3. (From Day 12) Why does `emergency=True` on the S-curve matter when a trajectory is cancelled?

## Optional 10-minute exercise

Open `src/parcel_robot/navigation/velocity_shaping.py` and `runtime.py` around `_motion_shaper.step`. List the arguments of `step` and when `emergency` is set. Note one config knob from `docs/MOTION.md` that trades smoothness for lag.
