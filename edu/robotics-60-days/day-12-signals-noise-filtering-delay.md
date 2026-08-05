# Day 12: Signals, Noise, Filtering, and Delay

## Mental model

Every sensor stream is a signal plus garbage. Useful taxonomy:

```text
bias      — systematic offset (IMU gyro drifts a constant rate)
variance  — random scatter around the true value
outliers  — rare spikes (LiDAR multipath, packet glitches)
delay     — the value describes the past, not now
```

Filtering reduces variance (and sometimes bias, if you model it) at the cost of *extra delay* and attenuated real motion. A low-pass filter makes a trace look “clean” while shifting peaks later in time. In a feedback loop, that phase lag can turn a stable controller into an oscillator: the correction arrives after the plant has already moved the other way.

Responsiveness versus smoothness is a product decision with physics consequences. Companion motion wants calm velocity shaping; safety stops must bypass gradual filters.

## Software-engineering analogy

Filtering is like adding caching and debounce to an event stream.

- A moving average is a short TTL cache of recent samples.
- An exponential low-pass (`y ← y + α(x − y)`) is an EWMA dashboard metric.
- Debouncing a button is rejecting high-frequency chatter — same idea as ignoring one-sample LiDAR spikes.
- Too much debounce on a kill switch is how outages get longer: you traded noise for latency on the wrong signal.

In distributed systems you already know “eventual consistency + retry storms.” In control, “heavy smoothing + high gain” is the analogous failure mode.

## Light equations

First-order low-pass (discrete):

```text
y[k] = y[k-1] + α (x[k] - y[k-1])     0 < α ≤ 1
```

Small α → smooth, slow. Large α → responsive, noisy.

Phase-lag intuition for a loop:

```text
total_delay ≈ sensor_delay + filter_delay + compute + actuation
stability risk rises as (gain × total_delay) grows
```

You do not need Bode plots today. You need the rule: every filter you add is a delay you must budget in the layer that closes the loop.

## ASCII diagram

```text
true body speed ----+----> sensor (noise + delay) ----> raw
                    |                                      |
                    |         α-filter / smoother          v
                    |                              filtered (lagged)
                    |                                      |
                    +------ compare to command <-----------+
                                   |
                                   v
                            corrective effort
                            (late if filter too heavy)
```

## Map to Parcel / Go2

**Codebase anchors (filtering / delay):**

- `VelocitySmoother` in `src/parcel_robot/core/velocity_smoother.py` — accel/decel-limited `step()`; `force()` / `reset()` snap state (used when gradual ramp must not apply).
- `SCurveVelocityShaper` in `src/parcel_robot/navigation/velocity_shaping.py` — per-axis jerk limits; `RobotRuntime` calls `_motion_shaper.step(..., emergency=stopping)` so stop/zero paths bypass the calm ramp (`runtime.py`).
- `_reset_motion_shaper()` clears shaper state on hard stops / watchdog sync so a filtered “current velocity” cannot outlive a real stop.
- Pipeline order is documented in `docs/MOTION.md`: arbiter → `VelocitySmoother` → proximity/TTC (`_collision_safe`) → S-curve → `ControlManager`.
- `ControllerStatus.as_dict()` reports `tracking_error` (target − measured) for telemetry — that is **not** a closed outer PID. Do not add high-gain Python tracking on Sport without budgeting filter delay.
- IMU bias / joint noise are consumed onboard; Parcel must not “fix balance” by low-passing Sport state at 10 Hz.


## Why builders care

Companion motion wants calm acceleration; collision gates want honesty. Those goals fight through delay. When you tune `motion.smoothing` / `motion.shaping`, you choose phase lag on the outer plant Sport presents. Log pre-shape and post-shape `VelocityCommand` plus `ControllerStatus.feedback_age_ms` before calling a tuning finished. If a filter makes plots pretty but stop latency worse, the filter is wrong for that path.

Rule of thumb: filter measurements inside the loop that will correct them; do not double-filter the same signal in nav and again in control. Prefer rejecting stale samples (TTL) over averaging them into a zombie estimate.

## Failure story

A spatial-behavior PR low-pass-filtered LiDAR closest-obstacle range with α = 0.05 to stop “twitchy” slowdowns. On a hallway approach the filtered range lagged ~0.4 s behind truth. The proximity gate thought clearance was still comfortable while the dog was already inside the intended slowdown envelope; braking started late and looked aggressive. Logs showed a beautiful smooth range trace — and a late deceleration. Fix: keep reactive safety on a short freshness window with light or no smoothing; put heavy smoothing on *command generation* for comfort, never on the last collision gate, and always preserve an unsmoothed emergency path.

## Retrieval questions

1. How can a filter that reduces noise make a closed loop *less* stable?
2. In Parcel’s motion stack, which path must bypass gradual velocity shaping, and why?
3. (From Day 08/09 intuition) Name one proprioceptive and one exteroceptive signal Parcel uses, and which is allowed to drive Sport balance directly.

## Optional 10-minute exercise

Open `docs/MOTION.md` and sketch the pipeline from behavior `VelocityCommand` → arbiter → smoother → proximity/TTC gates → S-curve → `ControlManager`. Mark each stage as “adds delay,” “may zero command,” or “bypass on stop.” Circle the last place a heavy low-pass would be unacceptable.
