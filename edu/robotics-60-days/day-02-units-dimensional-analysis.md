# Day 02: Units and Dimensional Analysis

## Mental model

Robotics bugs often look like logic bugs but are unit bugs: radians vs degrees, millimeters vs meters, body frame vs map frame, or a normalized joystick treated as m/s. **Every numeric literal in robot software is a physical claim.** If you cannot name its unit and frame, it is not ready to cross an actuator boundary.

Dimensional analysis is the cheapest type system physics gives you. Before you trust an equation or a config default, cancel units until only the quantity you meant remains. A formula that “almost works in sim” after a silent unit conversion is worse than a loud crash at startup.

Parcel leans on name suffixes (`*_m`, `*_rad`, `*_s`, `*_hz`, `*_mps`) in `configs/robot.yaml` and dataclasses — a poor man’s newtype over raw `float`. Enforce the convention in review even when the type system cannot.

## Core quantities

| Quantity | SI | Parcel cue |
| --- | --- | --- |
| Length | m | `step_length_m`, `upper_link_m`, `ROBOT_FOOTPRINT_RADIUS_M` |
| Time | s | `command_timeout_s`, `stall_timeout_s` |
| Angle | rad | `max_tilt_rad`, `sweep_amplitude_rad` |
| Linear vel | m/s | `motion.max_vx`, `VelocityCommand.vx` |
| Yaw rate | rad/s | `motion.max_vyaw`, `vyaw` |
| Force / torque | N, N·m | joint effort at vendor layer |
| Power / energy | W, J | battery + thermal budgets |
| Frequency | Hz | `control.control_hz` |

Prefer radians in math and control. Convert at UI/log boundaries only. Degrees in a YAML that feeds kinematics without an explicit convert is a classic fall hazard.

## Light equations

```text
v = Δx/Δt [m/s]     ω = Δθ/Δt [rad/s]     a = Δv/Δt [m/s²]
F = m a [N]         τ = r F sinφ [N·m]    P = τ ω [W]
E = P Δt [J]
d = v²/(2a)  →  [m²/s²]/[m/s²] = [m] ✓
```

If your “distance” formula yields seconds or newtons, the model is wrong before any test runs. Likewise, `45` as yaw rate is either mild (deg/s) or violent (rad/s) — the digit alone is meaningless.

## Software-engineering analogy

Units are nominal types that share a machine representation (`float64`) but must not mix — like using bare `string` for both user IDs and HTML. TypeScript cannot save you; naming and parse-time checks can.

`RobotProfile.from_config` in `src/parcel_robot/robot_profile.py` fails closed on unknown keys. Treat mystery numbers the same way: reject at the boundary rather than “cast and hope.”

## ASCII diagram

```text
  Three different "0.6" values
  ---------------------------
  UI slider 0.6           normalized 0..1     ≠ m/s
  motion.max_vx: 0.6      m/s (older default) ✓ speed
  image bbox width 0.6    fraction of frame   ≠ metres

  Rule: number + unit + frame + timestamp
        before it crosses a trust boundary
```

## Map to Parcel / Go2

- `VelocityCommand` (`src/parcel_robot/models.py`): `vx`,`vy` in m/s, `vyaw` in rad/s, interpreted as body-frame rates once leased as a `TimedVelocitySetpoint` (`frame="base_link"`).
- `configs/robot.yaml` → `motion.max_vx` / `max_vy` / `max_vyaw` (in-repo values have moved over time; comments note an older 0.6/0.4/1.0 companion set) and `control.max_tilt_rad: 0.75`. `ControlLimits` in `control/models.py` is the last-line clamp; `control/factory.py` wires config + `SafetyLimits` (`src/parcel_robot/safety.py`).
- `RobotProfile.go2()`: link lengths in metres; stand angles `(0.0, 0.9, -1.8)` in **radians**. Skill YAMLs under `configs/skills/` must match.
- LiDAR geometry on `SimObservation` uses `lidar_angle_min_rad` / `lidar_angle_increment_rad` / `lidar_range_*_m` (`backends/base.py`).
- `owner_search.sweep_amplitude_rad: 2.094…` in `configs/robot.yaml` is explicitly radians (±120°). Degrees pasted into that key would over-sweep by ~57×.
- Footprint: `ROBOT_FOOTPRINT_RADIUS_M = 0.32` in `src/parcel_robot/geometry.py` — metres of body extent for planners and clearance, not a pixel radius.

When you add a constant, suffix the name and document the frame (`base_link`, `odom`, `map`, `owner`) even if the type is still `float`.

## Failure story

An engineer ported “max turn rate = 45” from a vendor app note into a Parcel `vyaw` field. The note used deg/s; Parcel and Sport expect rad/s. At follow time the dog spun aggressively on heading error, tripped tilt/fault paths, and dumped the owner-follow task. Logs showed `vyaw=45` with no unit. Fix took hours; a one-line dimensional check (“45 rad/s is absurd for a companion dog”) would have caught it in review.


## Building habit

Add a one-line unit audit to every robotics PR checklist: each new literal has a suffix or a named constant with unit in the identifier, plus a frame when spatial. Prefer failing closed at parse time (unknown keys, non-finite values) the way `RobotProfile.from_config` and `ControlLimits.validate` already do. When porting vendor docs, convert in a single choke point and leave a comment with the source unit. Never reuse a bare float across UI normalization, image coordinates, and body velocity—three types that happen to share `0.6` will eventually share a bug. If a number looks “about right” in sim after a silent scale factor, stop and find the unit error instead of absorbing it into a gain.

## Retrieval questions

1. Show the units of `P = τ ω` and explain why motor thermal risk tracks power, not position error alone.
2. `control.max_tilt_rad` is `0.75`. What unit is that, and what breaks if a UI sends degrees into the same field?
3. (Day 01) Sport accepts `vx=0.6`. Which state kinds are still missing before claiming the dog moved 0.6 m?

## Optional 10-minute exercise

Open `configs/robot.yaml` and `src/parcel_robot/robot_profile.py`. List five numeric literals as `value → unit → frame_or_N/A → trust_boundary`. Flag any name missing a unit suffix.
