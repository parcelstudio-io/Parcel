# Day 30: Legged Locomotion Synthesis

## Mental model

Parcel chooses a semantic goal and a bounded body-motion request; Sport turns that request into dynamically balanced leg motion. Good goal tracking respects both geometry and embodiment. For ordinary travel, the dog should **turn toward the route first and move primarily forward**, because forward-facing motion keeps the camera/LiDAR view, stopping direction, and gait intent aligned. Lateral velocity remains a useful capability, but it is a bounded secondary correction—not the preferred way to cover large goal distance.

A complete motion decision checks heading, clearance, acceleration, traction, dynamic balance, and stopping margin every cycle. It also measures progress. A planned path or accepted command is never proof that the feet produced the requested displacement.

## Quantities, units, and assumptions

- Heading error `e_theta`: radians (`rad`).
- Forward/lateral velocity `(v_x, v_y)`: metres per second (`m/s`) in `base_link`.
- Yaw rate `omega`: radians per second (`rad/s`).
- Curvature `kappa = omega/v`: inverse metres (`1/m`) for forward-dominant planar motion with path speed `v > 0`.
- Friction estimate `mu`: dimensionless model parameter.
- Reaction delay and braking acceleration: seconds and `m/s²`.

Assume a locally planar surface, fresh pose and obstacle observations, and Sport available in its intended high-level mode. Real terrain and friction remain uncertain; safety gates must be conservative.

## Core equations

```text
heading error:
e_theta = wrap(atan2(y_goal-y, x_goal-x) - theta)

turn radius and lateral acceleration for an ideal forward arc with negligible `v_y`:
r = v/omega
a_curve = v²/r = v omega

idealized stopping margin:
d_stop = v t_reaction + v²/(2 a_brake)

traction check, simplified:
sqrt(F_x² + F_y²) <= mu N
```

A practical controller uses hysteresis: enter turn-first mode at a large heading error and leave only at a smaller threshold. That prevents chattering.

## ASCII diagram

```text
goal / sidewalk G
                *
               /
              / preferred travel
             ^
         [ dog ] initially facing right --->

1. TURN: vx=0, bounded yaw rate
2. DRIVE: vx>0, yaw trims path
3. OPTIONAL: small bounded vy for local correction
4. VERIFY: measured pose/semantics say goal vicinity is reached

all stages -> obstacle/TTC/tilt/freshness gates -> Sport
```

## Worked Parcel / Go2 example

**The following values are illustrative tuning examples, not Go2 limits.** A sidewalk goal has a `70 degree` body-relative bearing. An example policy enters align mode above `28 degrees` and exits below `7 degrees`:

1. While error is large, request `vx = 0`, `vy = 0`, and a capped yaw rate such as `0.60 rad/s`.
2. Once aligned, request illustrative `vx = 0.40 m/s` and a modest yaw correction.
3. Permit at most illustrative `|vy| <= 0.05 m/s` when fresh clearance supports a small local adjustment. The velocity direction is then only `atan(0.05/0.40) approximately 7.1 degrees` off body-forward.

If `omega = 0.30 rad/s` during forward tracking:

```text
r = 0.40/0.30 approximately 1.33 m
a_curve = 0.40*0.30 = 0.12 m/s²
```

With illustrative reaction delay `0.15 s` and braking magnitude `0.80 m/s²`:

```text
d_stop = 0.40(0.15) + 0.40²/(2*0.80) = 0.16 m
```

Obstacle inflation and arrival clearance must exceed a commissioned bound that also covers footprint, uncertainty, slope, and traction—not merely this ideal value.

## Software-engineering analogy

Turn-first/drive/verify is a state machine with hysteresis and an invariant-preserving admission path. Lateral velocity is an optional optimization behind a quota. It cannot bypass the same collision and freshness checks, just as a fast-path RPC cannot bypass authorization.

## Parcel / Go2 bridge

Parcel already represents high-level planar motion with `vx`, `vy`, and `vyaw`. Navigation should prefer rotate-then-forward behavior for goal travel while preserving bounded lateral capability for an embodiment-aware local planner. The exclusive control path, leased setpoints, measured stop confirmation, and reactive gates remain unchanged. Sport owns gait and balance; semantic completion uses perceived sidewalk/landmark vicinity plus measured pose, not path consumption.

Companion reading: [Smooth local navigation](../robotics-60-days/day-28-smooth-local-navigation.md), [Unitree Sport nested loop](../robotics-60-days/day-20-synthesis-unitree-sport-nested-loop.md), and [`docs/MOTION.md`](../../docs/MOTION.md).

## Failure and safety note

A holonomic simulator drives diagonally toward every waypoint. Paths look short, but the physical dog presents its side to obstacles, loses forward sensor coverage, and demands lateral traction. The opposite extreme—disabling `vy` everywhere—removes a legitimate controlled capability. Encode “forward preferred, lateral bounded,” then validate on headless semantic tasks before low-speed fenced hardware tests.

## Retrieval questions

1. Why is forward-preferred motion useful even though Go2 can generate lateral velocity?
2. What does hysteresis contribute to turn-first control?
3. Which measurements must agree before declaring “reached the sidewalk” complete?

## Optional 10-minute exercise

In a spreadsheet or tiny simulator, vary goal bearing from `0` to `180 degrees`. Implement illustrative align-enter/exit thresholds, a forward cap, and a lateral cap. Plot `(vx, vy, omega)` versus bearing and confirm commands still pass through a stop-distance/clearance gate. Do not run it on hardware.
