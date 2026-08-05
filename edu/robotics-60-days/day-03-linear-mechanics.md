# Day 03: Linear Mechanics

## Mental model

A robot dog’s body is a mass that changes velocity only when net force acts on it — mostly through foot contact with the ground. Software “velocity commands” ask the locomotion stack to *try* to produce a body velocity; **Newton’s laws still decide** whether the mass accelerates. If friction is low, the battery sags, or the gait cannot place feet, your `vx` setpoint is a wish.

For Parcel navigation you mostly think in body-frame linear velocities `(vx, vy)` and path geometry in metres. Underneath, every start, stop, and bump is force, momentum, and energy. Speed is not a cosmetic “liveliness” dial; it scales kinetic energy and stopping distance.

In Parcel, acceleration/deceleration budgets appear as `motion.smoothing.linear_accel` / `linear_decel` and jerk limits under `motion.shaping` in `configs/robot.yaml`, implemented by `VelocitySmoother` (`src/parcel_robot/core/velocity_smoother.py`) and `SCurveVelocityShaper` (`src/parcel_robot/navigation/velocity_shaping.py`). `docs/MOTION.md` notes that safety stops bypass gradual braking — kill switches must not wait for a polite S-curve.

## Light equations

```text
ΣF = m a                 # net force produces acceleration
p = m v                  # momentum
J = ∫ F dt = Δp          # impulse changes momentum
KE = ½ m v²              # kinetic energy grows with v²
d_stop ≈ v² / (2 a_brake)
```

Implications you will use as an SE:

1. Double speed ⇒ ~4× kinetic energy and roughly 4× stopping distance if braking acceleration is unchanged.
2. Short contact impulses (curbs, ankles) mean large peak force even when average force looks modest.
3. Desired velocity changes must be shaped; unbounded `vx` steps ask for impossible acceleration.

## Software-engineering analogy

Think of body velocity as a rate-limited resource with inertia — like autoscaling a stateful shard. You cannot jump from 0 to capacity without paying a ramp cost. Velocity smoothers and acceleration caps are admission controllers protecting the physical plant the way circuit breakers protect downstream services. Collision kinetic energy is the blast radius of an oversized request. An E-stop that “still eases down for comfort” is a product bug dressed as UX.

## ASCII diagram

```text
  commanded vx ──► Sport gait ──► foot forces F ──► body mass m
                                      │
                                      ▼
                                 a = ΣF / m → measured v_body
                                      │
                      navigation compares to plan / gates

  order-of-magnitude stop distance:
  v=0.6 m/s, a=1.5 m/s²  =>  d ≈ 0.12 m
  v=1.2 m/s, same a      =>  d ≈ 0.48 m   (4×)
```

## Map to Parcel / Go2

- Speed caps: `configs/robot.yaml` → `motion.max_vx` (in-repo comments record a raise from 0.6 toward 1.0 m/s for sim pace). `ControlLimits` and commissioning CLIs may still use tighter clamps — read the active path before a lobby demo. `SafetyLimits.max_vx` in `src/parcel_robot/safety.py` clamps tool-level `set_velocity` as well.
- Footprint geometry: `ROBOT_FOOTPRINT_RADIUS_M = 0.32` in `src/parcel_robot/geometry.py`, mirrored on `RobotProfile.footprint_radius_m`. Planners inflate obstacles in metres; stopping still needs real deceleration distance beyond the footprint.
- “Stopped enough” for post-stop confirmation: `control.settled_linear_speed_mps` (default 0.08) compared against **measured** speed inside `ControlManager` — commanded zero is not confirmation (`docs/MOTION.md`).
- Reactive proximity/TTC gates consume fresh camera/LiDAR fields on `SimObservation` (`nearest_person_ttc_s`, obstacle distances) before the actuator hand-off.
- Go2 mass is ~15 kg class plus payload. You do not need the datasheet memorized; remember KE and impulse scale with that mass near people.

Navigation plans paths; locomotion converts body velocity into contact forces. Parcel’s brain should keep `vx/vy` feasible for people-nearby operation and never assume an instantaneous stop.

## Failure story

A demo raised max forward speed to “look more alive” without revisiting obstacle inflation or stop distance. At ~1.2 m/s in a lobby, a late LiDAR cluster appeared inside the old 0.6 m/s stopping envelope. The collision gate commanded zero; Sport began braking; residual momentum still carried the body into a soft barrier. No joint-limit fault fired — pure linear mechanics. Rollback restored a lower cap and increased buffer. Postmortem: “we changed energy by ~4× and left distance budgets alone.”


## Building habit

Any PR that raises `motion.max_vx` or relaxes deceleration must recompute stop distance and revisit obstacle inflation / TTC gates in the same change. Read `docs/MOTION.md` so you know which path bypasses smoothing on emergency stop. When validating “stopped,” assert measured speed under `settled_linear_speed_mps`, not the last commanded zero. Keep footprint (`ROBOT_FOOTPRINT_RADIUS_M`) and braking distance as separate budgets: clearing the body disk does not mean residual momentum is gone. For companion demos near people, treat kinetic energy as the blast radius metric in the design review, not average FPS of the planner.

## Retrieval questions

1. Why does kinetic energy make speed caps a safety control, not only a UX preference?
2. Parcel marks motion “settled” using a measured linear speed threshold. Why is commanded `vx=0` insufficient?
3. (Day 02) Confirm that `d = v²/(2a)` is dimensionally metres. What units must `a` have?

## Optional 10-minute exercise

Assume `m = 15 kg`, `v = 0.6 m/s`, `a = 2.0 m/s²`. Compute KE, stop distance, and stop time `v/a`. Repeat at `v = 1.2 m/s`. Then open `configs/robot.yaml` `motion.smoothing` / `motion.shaping` and note which keys bound deceleration vs jerk. Write one PR sentence you would require before raising `max_vx`.
