# Day 28: Smooth Local Navigation

## Mental model

A path is a string of poses. A **trajectory** (or tracked command stream) respects time, acceleration, and heading constraints. Local navigation converts the next waypoint into body velocities `(vx, vy, vyaw)` that a quadruped can track without sliding diagonally through inflated corners.

Parcel’s default style is **rotate-first, then drive forward** (`vy≈0`): if heading error is large, yaw in place; once aligned within hysteresis, translate primarily forward with a lookahead point (pure-pursuit intuition).

```text
waypoints -> lookahead point -> heading error
  if |err| large:  vyaw only
  else:            vx toward lookahead (+ limited vyaw)
```

Nested slew limits (navigator + runtime smoother + actuator shaper) trade responsiveness for jerk. The final dispatch boundary keeps safety semantics separate: hard stops are exact all-axis zero, proximity stops are exact-zero translation, and only an opt-in nominal stop may use a monotone, re-gated ramp.

## Software-engineering analogy

Waypoint tracking is a **state machine over a cursor into a list**, with hysteresis to avoid chatter — like TCP congestion control entering/exiting recovery, not flipping every RTT.

- Lookahead ≈ reading ahead in a buffer before acting.
- Align enter/exit thresholds ≈ Schmitt trigger on heading error.
- Accel clamps ≈ rate-limited API client; E-stop ≈ a fail-closed cancel that is reasserted after every limiter.

## Light equations

Pure-pursuit / heading error sketch:

```text
δ = wrap(atan2(y_look - y, x_look - x) - θ)
vx = cruise * taper(distance)
vyaw = clip(yaw_gain * δ, ±max_yaw_rate)
```

Hysteresis (from the current `grid.yaml`):

```text
enter align if |δ| >= 55°
exit  align if |δ| <= 7°
```

Speed layers: planner cruise is 0.85 m/s, `default.yaml` permits navigation up to 0.9 m/s, and the body envelope permits 1.0 m/s. The planner is therefore the smallest static forward-speed ceiling in that chain, but heading/distance taper, slew, arbitration, safety, and shaping can command less. These are simulator settings, not commissioned Go2 speeds.

## ASCII diagram

```text
  path:  *----*----*----G
              ^
           lookahead

  heading error large:   [rotate]  vx=0, vyaw≠0
  heading error small:   [drive]   vx>0, vyaw small
  near goal:             taper vx -> stop / verify
```

## Map to Parcel / Go2

- `GridNavigator` tracks `RollingGridPlanner.next_waypoint` with slew on `vx`/`vyaw` (`max_linear_accel`, `max_yaw_accel`, `control_dt_s=0.1`).
- Rotate-first hysteresis lives in controller config: `align_enter_deg: 55`, `align_exit_deg: 7` (`configs/navigation/models/grid.yaml`); also in `StubNavigator` / spatial orbit align thresholds.
- `MidLevelCommand(vx, vy, vyaw)` exits navigation; runtime arbiter + smoother + `reactive_safety.apply_reactive_safety` still gate motion.
- Recovery default: scan-in-place (`recovery_reverse_steps: 0`) to avoid reversing into a rear blind wedge.
- Orbit/spatial uses similar align hysteresis (`SpatialBehaviorConfig.align_enter_deg=25`, `align_exit_deg=8`).

**Codebase anchors (local nav):**

- `navigation/grid_navigator.py` → `GridNavigator.act`, `_slew`
- `navigation/grid_planner.py` → `next_waypoint`, `lookahead_m`, `BodyWaypoint`
- `navigation/models/__init__.py` → `StubNavigator` rotate-first hysteresis (fallback)
- `navigation/base.py` → `MidLevelCommand`
- `navigation/collision.py` → navigation-local brake; `reactive_safety.py` → runtime-wide gate
- `core/hard_stop.py` → post-shaper `finalize_command` dispatch disposition
- Speed honesty: `docs/NAVIGATION_CITY.md` cruise vs wrapper/body envelopes

## Tick-by-tick in Parcel

`next_waypoint` selects a point about `lookahead_m` ahead on the polyline. Heading error drives rotate-first hysteresis using `align_enter_deg` / `align_exit_deg`. Accel slew in `GridNavigator._slew` shapes `vx`/`vyaw` before `MidLevelCommand` leaves navigation. Navigation applies its local brake; runtime then applies another smoother, the runtime-wide proximity/TTC gates, the actuator shaper, and finally `finalize_command`. Shaping is for cruise and an optional nominal stop, never permission to relax a hard/proximity disposition. Nominal `vy=0` keeps motion forward-facing; future local planners may use lateral velocity without changing the `MidLevelCommand` contract.

## Failure story

In a historical tuning pass, `cruise_vx` was raised while the then-current `max_vx: 0.45` wrapper still kept the dog slow; weakening the reactive brake would have attacked the wrong layer. The wrapper is now 0.9 m/s, so that exact mismatch no longer exists, but the lesson survives: identify which taper, slew, envelope, arbiter, or safety gate is binding before changing any one of them. Smooth ≠ unsafe.

## Path vs trajectory vs command

Path = geometric polyline in odom. Trajectory ≈ timed motion satisfying accel limits. Parcel’s navigator emits a discrete-time velocity command stream at ~10 Hz that *approximates* a trajectory. Unitree Sport then tracks body velocity with its own gait dynamics. If the dog “cuts corners,” check lookahead, inflation, and hysteresis before blaming Sport. If it “feels sluggish,” check nested `max_vx` clamps and slew before raising cruise in isolation.

## Pure-pursuit intuition without the textbook trap

Classic pure pursuit picks a path point a fixed lookahead distance away and steers a bicycle model toward it. Parcel’s waypoint tracker is the discretized cousin: choose lookahead target, regulate heading with hysteresis, drive forward with speed taper near the goal (`slowdown_radius_m`). Curvature emerges from yaw rate vs forward speed, not from an explicit clothoid generator. If you need tighter corridors later, consider a local trajectory optimizer behind the same `MidLevelCommand` interface — do not bypass gates.

Jerk limits exist in nested layers: navigator slew, runtime smoother, then actuator hand-off. Trace a single stop command through those layers and classify it: shipped-config nominal zero, proximity translation stop, or hard stop. Confirm the post-shaper finalizer emits the promised command; only then consider separate physical stop-response evidence.

## Retrieval questions

1. Why use separate enter/exit heading thresholds instead of one angle?
2. What is the difference between a grid path and the velocity stream Sport receives?
3. (From Day 20) Which outer-loop rate is Parcel navigation on, and who owns balance?


When debugging motion feel, log `MidLevelCommand.note` — rotate, recovery, and fallback modes announce themselves there before you guess at Sport.

## Optional 10-minute exercise

Compare `cruise_vx` in `configs/navigation/models/grid.yaml` with `max_vx` in `configs/navigation/default.yaml` and `configs/robot.yaml`. Open `GridNavigator._slew`, then trace a proximity stop through `RobotRuntime._finalize_for_actuator` to `core.hard_stop.finalize_command`.
