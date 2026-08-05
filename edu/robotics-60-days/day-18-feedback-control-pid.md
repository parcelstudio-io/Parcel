# Day 18: Feedback Control and PID

## Mental model

Feedback control compares desired and measured signals and drives the error down:

```text
e = r - y
u = Kp e + Ki ∫e dt + Kd de/dt
```

- **P** reacts now; high \(K_p\) → snappy, noisy, potentially oscillatory.
- **I** removes steady-state offset; winds up under saturation (integral grows while actuators cannot).
- **D** damps; amplifies high-frequency noise (pair with filtering — Day 12).

Feedforward predicts the effort you will need (e.g., nominal velocity) so feedback only corrects residuals. Saturation and anti-windup are mandatory on physical plants: motors clip, friction cones clip, Sport clips.

Parcel’s stack is **cascaded**, not one PID from LLM to torque. Navigation may use P-like heading/range behaviors; `VelocitySmoother` / S-curve shape setpoints; Sport runs the fast balance/gait controllers; motors run current loops. `ControlManager` is a supervisory feedback loop on freshness, limits, and faults — not a textbook body-velocity PID.

## Software-engineering analogy

PID is a closed-loop autoscaler with three knobs. P is reactive scaling; I is “we have been under capacity all hour”; D is “stop flapping.” Integral windup is a retry counter that increments while the circuit breaker is open — clear the integrator when saturated or when the setpoint is cancelled. Feedforward is a cache of the expected steady-state input so the feedback loop is not reinventing gravity each tick.

## Light equations

Discrete sketch:

```text
e[k]   = r[k] - y[k]
I[k]   = I[k-1] + e[k] Δt          (freeze/reset if saturated)
u[k]   = Kp e[k] + Ki I[k] + Kd (e[k]-e[k-1])/Δt
u[k]   = clip(u[k], u_min, u_max)
```

Stability intuition: delay (Day 11–12) + high gain → oscillation. Measure before you raise \(K_p\).

## ASCII diagram

```text
r_des --> + Σ --> PID / policy --> plant (Sport + body) --> y_meas
           ^                                        |
           +-------------- (delay + noise) ----------+

Parcel cascade:
  nav error -> VelocityCommand -> smooth/shape -> ControlManager lease
                                                    |
                                                    v
                                              Sport inner loops
```

## Map to Parcel / Go2

**Codebase anchors (feedback without a Parcel PID module):**

- There is **no** `PIDController` class in `src/parcel_robot/control/` today — do not invent one in docs. Outer behaviors emit `VelocityCommand`; examples of P-like yaw response appear in navigation/search code paths (e.g. yaw toward goals), not as a shared PID library.
- `ControlManager` feedback: stale state → stop; tilt/vendor fault → fault; lease expiry → stop; stop confirmation via settled measured speeds (`manager.py`, `ControlTiming`).
- `ControllerStatus.tracking_error` in `control/models.py` is diagnostic (target−measured). `docs/MOTION.md` states Parcel does not currently regulate that error away as a precision trajectory servo.
- Shaping (`VelocitySmoother`, `SCurveVelocityShaper`) is open-loop-on-command rate limiting, not PID on pose.
- Sport `Move`/`StopMove` (`unitree_sport.py`) hand setpoints to vendor closed loops — treat Sport as the inner controller you supervise.


## Why builders care

You will be tempted to paste a PID into `RobotRuntime` the first time Sport tracking looks soft. Resist until you have measured total delay (shape + DDS + Sport + state age) and decided which loop owns the error. Supervisory feedback (stale → stop) is mandatory; tracking feedback on body velocity is optional and dangerous at 10 Hz with integral action. Prefer feedforward-ish shaping (command the twist you mean, smoothly) and task-level replanning when error grows.

Interview yourself on every control PR: what is \(r\), what is \(y\), what is the deadline, what saturates, what resets the integrator on cancel?

Anti-windup patterns you should recognize in code review: freeze integrator while saturated; reset integrator when setpoint is zeroed by safety; never integrate across a mode change without clearing. Derivative-on-measurement (instead of on error) avoids setpoint spikes—same idea as not differentiating a step reference.

Parcel’s stop path is extreme anti-windup: clear shaper state, latch E-stop, require fresh settled samples. Copy that mentality whenever you add outer feedback.

Feedforward tip: a good outer planner that emits feasible twists reduces the need for heroic feedback gains downstream.

## Failure story

An engineer added a Python PID on `tracking_error.vx` at 10 Hz with aggressive \(K_i\) to “fix laggy Sport.” Integral windup during a proximity-forced zero commanded a surge when the gate cleared; the dog lurched into the owner’s personal space. Logs showed beautiful declining error afterward — and a near miss. Fix: do not close high-integral loops around opaque, delayed vendor plants from the behavior tick; keep Parcel supervisory; tune Sport/modes and shaping limits instead.

## Retrieval questions

1. What does each PID term do, and what is integral windup?
2. Is `ControlManager` a body-velocity PID? What errors does it actually act on?
3. (From Day 11) Why is a 10 Hz Python PID a poor place to stabilize balance-scale errors?

## Optional 10-minute exercise

Open `ControllerStatus.as_dict` in `src/parcel_robot/control/models.py` and the nested-loop notes in `docs/MOTION.md`. List three supervisory reactions in `ControlManager` that are feedback but not PID. Note one place a future tracking controller would have to live (and at what Hz).
