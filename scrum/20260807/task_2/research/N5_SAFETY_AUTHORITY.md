# N5 — Safety / motion authority

**Workstream:** Opus research wave N5 (`OPUS_RESEARCH_WAVE.md`)  
**Date:** 2026-08-07  
**Code basis:** working tree under `/home/jaewoo-jang/Desktop/Projects/Parcel`  
**Scope:** final motion authority — residual velocity after proximity/TTC +
S-curve shaping; LiDAR missing/malformed open-loop fallback; literature and
in-repo authority contracts that should govern P0-A / P0-B.

This is a **source verification + design research** note, not a physical safety
certification. External Nav2 / ISO references are architectural evidence, not
Parcel compliance claims.

---

## Verdict

Two defects invalidate treating the current stack as a closed safety authority
on physical motion:

1. **Ordinary proximity/TTC stops can retain nonzero residual velocity** on the
   same dispatch tick that declared `stopped`, because the S-curve shaper runs
   *after* the gate and its `emergency=True` path only decelerates at
   `max_accel`, not exact-zero.
2. **Default `grid_v1` substitutes an open-loop point-goal translator** when the
   calibrated planar LiDAR scan is missing or malformed. Occupancy mapping is
   off; translation continues. The fail-closed HOLD path exists only behind the
   opt-in `safe_valley_micro_advance` flag.

Preserve: latched E-stop → `ControlManager.emergency_stop()`, TTL leases, typed
HAL, Sport gait ownership, and the elementwise-min authority triple. Fix
ordering and sensing fail-closed before any learned proposer gains runtime
authority.

**Confidence:** high on source findings (direct code + pinning test behavior);
medium on physical stop distance until measured e2e latency and deceleration
are plugged into `SafetyEnvelope`.

---

## 1. Motion pipeline as coded

Relevant slice of `RobotRuntime._dispatch_active`:

```text
arbiter intent
  → VelocitySmoother.step
  → _collision_safe  (reactive proximity + TTC scale)
  → velocity_smoother.force(gated command)
  → _shape_for_actuator(..., stopping= proximity_state=="stopped" | …)
  → ControlManager.set_target(shaped command)
```

| Stage | File:line | Role |
| --- | --- | --- |
| Dispatch | `runtime.py:3796–3847` | Orders gate **before** shaper |
| Collision + TTC | `runtime.py:4412–4477` | Scales/stops intent; cannot raise a prior stop |
| Actuator shape | `runtime.py:3941–3975` | Jerk-limited track; `emergency=stopping` |
| Emergency slew | `velocity_shaping.py:102–105` | Toward 0 at `max_accel * dt`, not snap |
| Latched E-stop | `runtime.py:2040–2050` | Bypasses this path via manager stop + shaper reset |

Comments and YAML still claim “every stop is unsmoothed”:

- `runtime.py:3832–3834` — “Stops route to the emergency bypass so no stop
  decision is ever smoothed.”
- `configs/robot.yaml:147–150` — “every stop path takes the shaper's emergency
  bypass and is never smoothed.”
- `docs/MOTION.md:60` — “every stop uses the emergency bypass.”

Those statements are **stale relative to residual accel-limited slew**. The
bypass removes the jerk limit; it does not force HAL-visible zero.

---

## 2. Residual velocity after TTC / shaper — verified

### 2.1 Gate can emit an exact zero *intent*

Reactive proximity stop clears translation and returns `"stopped"`:

```196:197:src/parcel_robot/navigation/reactive_safety.py
def _stop_translation(command: VelocityCommand) -> tuple[VelocityCommand, str]:
    return VelocityCommand(vyaw=command.vyaw), "stopped"
```

TTC may independently force `scale <= 0` and rewrite proximity to `"stopped"`
when the robot was still translating (`dynamic_layer.py:304–306`). The runtime
then multiplies the command (`runtime.py:4472–4477`), so the **pre-shaper**
command can be exact zero translation.

### 2.2 Shaper still emits nonzero on that tick

`_dispatch_active` passes `stopping=(proximity_state == "stopped" | …)` into
`_shape_for_actuator` (`runtime.py:3835–3846`). The shaper call sets
`emergency=stopping` (`runtime.py:3969–3973`).

Emergency branch:

```102:105:src/parcel_robot/navigation/velocity_shaping.py
            if emergency:
                next_velocity = _move_toward(velocity, 0.0, limits.max_accel * dt_s)
                self._acceleration[index] = (next_velocity - velocity) / dt_s
                self._velocity[index] = next_velocity
```

With shipped limits `linear_max_accel: 1.2` (`configs/robot.yaml:154`) and a
typical `dt_s ≈ 0.1` (`runtime.py:3967`):

| Prior shaped `vx` | Max drop / tick | Post-stop tick `vx` |
| --- | --- | --- |
| 0.60 m/s | 0.12 m/s | **0.48 m/s** |
| 0.60 m/s | — | ~**5 ticks** to exact 0 at this bound |

So the gate’s `"stopped"` verdict and a zero *intent* do **not** imply a zero
command at `ControlManager.set_target` on the same dispatch.

### 2.3 The pinning test preserves residual motion

`tests/test_motion_shaping.py:395–412`
(`test_stop_entry_point_6_a_proximity_stop_is_not_smoothed`) only asserts that
the emergency bypass drops faster than a comfort ramp:

```text
assert bypass_drop > smoothed_drop
```

It does **not** assert `gated.vx == 0`. That matches CURRENT_STACK_AUDIT P0.1
and README Phase-0 defect #1.

### 2.4 What is *not* broken

Explicit latched E-stop still engages the manager stop path and resets the
shaper (`runtime.py:2040–2050`, `_reset_motion_shaper` at `4010–4021`).
Navigation terminal stop and several preemption paths also reset shaper state
to exact zero (`test_motion_shaping.py` entry points 7–9). The defect is
narrower: **ordinary sensor safety stops that stay inside `_dispatch_active`
and only flip `stopping=True`**.

Angular residual: proximity `_stop_translation` preserves `vyaw`
(`reactive_safety.py:197`). TTC scales all three axes including yaw
(`runtime.py:4472–4476`). A pure geometric stop can therefore still hand a
nonzero yaw rate into the same accel-limited emergency slew.

---

## 3. LiDAR open-loop fallback — verified

### 3.1 Module contract (default)

`grid_navigator.py` module docstring (`1–7`) states missing/uncalibrated scans
**fall back** to the deterministic point-goal controller for incremental
deployability.

Active product model is `grid_v1` (`configs/navigation/default.yaml:8`).
`configs/navigation/models/grid.yaml` does **not** enable
`safe_valley_micro_advance` (defaults `False` at `grid_navigator.py:99`).

### 3.2 Missing / malformed scan path

```335:357:src/parcel_robot/navigation/grid_navigator.py
        scan = self._scan_from_observation(observation)
        if scan is None:
            if self.safe_valley_micro_advance:
                ...
                return self._safe_valley_hold("calibrated_lidar_unavailable")
            ...
            command = self._fallback.act(observation, mission)
            fallback_note = "scan_missing_fallback"
            ...
            return replace(command, note=fallback_note)
```

`_scan_from_observation` (`964–989`) returns `None` when ranges are absent,
wrong type/length, or calibration extras (`lidar_angle_min_rad`,
`angle_increment`, `range_max`, …) are non-numeric. That is the open-loop
substitution trigger.

### 3.3 What “fallback” does

`_fallback` is `StubNavigator` (`grid_navigator.py:242`). Once past arrival /
align, it slews a positive `vx` toward the goal (`models/__init__.py:216–236`)
using optional soft brakes from `nearest_person_m` / `nearest_obstacle_m` and
optional `lidar_obstacles` extras — **not** the rolling occupancy map. With a
missing calibrated scan and empty obstacle extras, corridor avoidance is empty
and the controller **translates open-loop** toward the goal while stamping
`scan_missing_fallback`.

Telemetry is loud (`scan_fallback_count`, warning log once per transition) but
does not HOLD.

### 3.4 Fail-closed path exists but is opt-in

When `safe_valley_micro_advance=True` (challenger YAMLs
`grid_safe_valley_v5.yaml` / `grid_safe_valley_guard_v6.yaml` only):

- missing scan → `_safe_valley_hold("calibrated_lidar_unavailable")`
  (`337–341`, hold implementation `698–708` zeros `vx/vy/vyaw`);
- stale / unsynchronised lidar↔odom stamps → HOLD
  (`363–368`, freshness `930–949`).

Default product path does **not** take this branch. That matches CURRENT_STACK
AUDIT P0.2 and README Phase-0 defect #2.

Downstream comment still claims TTC/reactive remain authority after navigator
slew (`grid_navigator.py:278–279`). True for geometric person/obstacle scalars
when present; **false as a LiDAR occupancy substitute** when the scan that
builds the map is gone and the stub is driving.

---

## 4. In-repo safety authority (what to keep)

### 4.1 Embodiment authority triple

`parcel_robot/authority.py` already encodes the correct *shape* of a stopping
envelope (ISO/TS 15066 vocabulary):

```text
stop_distance(v) = r_foot + v·τ + v²/(2·a) + Zs + Zr
```

(`authority.py:478–494`). Arbitration rule is **elementwise minimum** across
speed authorities (`authority.py:62–68`) — no authority may raise another’s
cap. Wiring every site into `arbitrate_limits` is still incomplete (documented
as a later card), but the derivation contract is the right P0/P1 spine.

### 4.2 Soft vs hard layers

Soft dynamic A* cost may prefer routes away from predicted people
(`COMPANION_NAVIGATION_ARCHITECTURE.md`); malformed tracks currently disable
the soft layer for a tick without granting the predictor stop authority. Hard
geometry/TTC must remain independent. N5 finding: hard path is incomplete
because (a) residual after shaping and (b) planner substitution without LiDAR.

### 4.3 Target architecture already states the fix

`TARGET_ARCHITECTURE.md` “Final safety contract” (≈173–190): last component
before `ControlManager` consumes freshest metric geometry and the **actual
shaped** command; hard stop forces **exact zero after shaping** and resets
state; loss of a required source is STOP/HOLD, not point-goal fallback. N5
verifies the current code does not yet meet that contract.

---

## 5. External research (architectural)

### 5.1 Nav2 Collision Monitor ordering

Nav2’s documented velocity chain places the Collision Monitor **last**, after
the velocity smoother, publishing the final `cmd_vel`
([Using Collision Monitor](https://docs.nav2.org/tutorials/docs/using_collision_monitor.html);
historical fix discussion in
[navigation2#3744](https://github.com/ros-navigation/navigation2/issues/3744)).
Stop/slowdown actions operate on the post-smoothed command so a safety veto
cannot be re-smoothed into residual motion.

Parcel inverts that for ordinary stops: gate → shaper → HAL. Aligning with
Nav2’s lesson does **not** require adopting ROS; it requires a final
independent monitor that re-evaluates the **shaped** command (or forces zero
and resets shaper state) before `set_target`.

### 5.2 Envelope math vs residual slew

ISO/TS 15066-style envelopes assume a known reaction latency and braking
deceleration. Parcel’s `SafetyEnvelope` already uses that form, but the
runtime geometric thresholds in `configs/robot.yaml` (`obstacle_stop_m: 0.65`,
etc.) are not yet proven equal to
`margin + v·e2e_latency + v²/(2·a_meas)` under residual shaped velocity. Any
stop that still commands ~0.5 m/s for several ticks lengthens the true
stopping distance beyond the gate’s assumed intent.

### 5.3 Sensing fail-closed

Industry local planners (Nav2 collision monitor `source_timeout`, industrial
AMR practice) treat missing/stale required range data as stop/hold for the
affected ODD, not as permission to continue with a mapless translator.
Parcel’s opt-in safe-valley HOLD is consistent with that; default `grid_v1`
is not.

---

## 6. Required corrections (P0)

### P0-A — Final hard-zero safety ordering

1. Distinguish `comfort_stop` (accel/jerk limited) from `hard_safety_stop`
   (exact zero) in types / proximity state.
2. After shaping (and any learned proposal), **re-assert** the latched raw
   sensor / TTC verdict; if hard-stop, emit `(0,0,0)`, reset smoother +
   shaper (`_reset_motion_shaper`), and prefer manager stop where appropriate.
3. Pin under test: same-dispatch HAL/observed command is exactly zero when
   proximity/TTC declares stopped; replace
   `bypass_drop > smoothed_drop` as the sole proximity-stop criterion.
4. Derive stop thresholds from measured latency and deceleration using
   `SafetyEnvelope.stop_distance(v)`.

### P0-B — Sensing fail-closed (LiDAR / pose / transforms)

1. Physical / product `grid_v1`: missing, malformed, stale, or
   frame-unsynchronised LiDAR → HOLD/STOP (same semantics as
   `_safe_valley_hold`), never `StubNavigator` translation.
2. Keep loud degraded telemetry; do not allow continuity of motion to depend
   on soft person/obstacle scalars alone.
3. Simulator-labeled modes may retain fallback only when explicitly tagged;
   default must match the target architecture ODD rule.

Preserve latched E-stop, leases, Sport, and authority triple derivation.

---

## 7. What N5 does *not* claim

- That every stop path is broken (E-stop and several reset paths work).
- That Nav2 Collision Monitor alone is a certification case for Parcel.
- That enabling `safe_valley_micro_advance` alone finishes P0-B (pose health,
  transforms, and ControlManager feedback remain separate P0-B/P1 work).
- Physical collision probability without commissioned hardware measurements.

---

## 8. Evidence index

| Claim | Primary cite |
| --- | --- |
| Gate then shaper order | `runtime.py:3825–3847` |
| TTC only scales down | `runtime.py:4441–4477`, `dynamic_layer.py:287–311` |
| Emergency ≠ exact zero | `velocity_shaping.py:102–105` |
| Accel limits | `configs/robot.yaml:152–157` |
| Test allows residual | `tests/test_motion_shaping.py:395–412` |
| Default open-loop fallback | `grid_navigator.py:335–357`, `configs/navigation/default.yaml:8` |
| Stub still translates | `navigation/models/__init__.py:216–236` |
| Opt-in HOLD | `grid_navigator.py:337–341`, `698–708` |
| Stale “never smoothed” docs | `configs/robot.yaml:147–150`, `docs/MOTION.md:60` |
| Envelope formula | `authority.py:478–494` |
| Target hard-zero contract | `TARGET_ARCHITECTURE.md` § Final safety contract |

---

## 9. Recommendation for synthesis

Treat P0-A and the LiDAR HOLD half of P0-B as **blocking** for physical motion
and for any model A/B that claims safety-comparable control. Classical Nav2
sidecar work (N1/N3) should assume Parcel retains an independent post-shape
metric monitor; learned proposers (N4/RL*) remain TTL-bound and vetoable
downstream of that monitor.
