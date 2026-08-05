# Day 11: Clocks, Sampling, Timescales, and Deadlines

## Mental model

A robot is not one loop. It is a stack of loops, each with a period, a deadline, and a maximum useful sensor age. Frequency and period are inverses:

```text
period = 1 / frequency
```

If a layer must finish before the physical phenomenon it controls changes too much, that finish time is a *deadline*. Missing the average is fine; missing the deadline is not. Jitter is variation in when the work actually runs. Stale data is a sample whose age exceeds the freshness budget for that loop. Aliasing is sampling a fast signal too slowly and inventing a false slow signal.

Nested timescales (illustrative, from `edu/INTRO.md` and `docs/MOTION.md`):

```text
conversation / LLM     event-driven, hundreds of ms to seconds
behavior / nav         ~10 Hz  (100 ms)   Parcel RobotRuntime
ControlManager         ~50 Hz  (20 ms)    lease + freshness watchdog
Unitree Sport gait     ~hundreds of Hz    onboard, opaque to Parcel
motor electronics      ~kHz               vendor firmware
```

Slow layers set goals. Fast layers reuse those goals while closing their own feedback. The language model is never in the balance loop.

## Software-engineering analogy

Think of a multi-tier service with SLOs at every hop.

- Conversation is a batch job: late answers annoy users but do not tip the dog.
- Navigation at 10 Hz is an API with a 100 ms budget: drop or reuse the last plan if you overrun.
- `ControlManager` at 50 Hz is a liveness probe: if feedback is older than `state_timeout_s` (default 0.25 s) or the command lease expires (`command_timeout_s`, default 0.35 s), stop — do not “best effort” crawl.
- Sport and motors are hard real-time workers you do not schedule from Python.

p50 latency is vanity. Production robotics logs p95, p99, max, missed deadlines, sensor age, and stop latency after a fault — the same way you treat tail latency in a payment path.

## Light equations

```text
age(sample)     = t_now - t_stamp
deadline_miss   ⇔  compute_time + queue_wait > period
usable(command) ⇔  t_now < valid_until   (TimedVelocitySetpoint lease)
usable(state)   ⇔  age(state) < state_timeout_s
```

Nyquist intuition: to track a phenomenon that changes at frequency \(f\), you need sampling well above \(2f\). A 10 Hz brain cannot stabilize a tip that develops in 20 ms; that belongs onboard.

## ASCII diagram

```text
t=0     IMU tip starts
t=1-5ms Sport + motors correct feet        <--- deadline that matters
t=20ms  ControlManager tick (may not even run yet)
t=100ms Navigation sees new pose
t=1s+   Conversation explains the stumble

clock domains (do not silently mix):
  host monotonic  |  DDS arrival time  |  vendor stamp  |  wall clock
       \________________ must convert / budget age explicitly ________/
```

## Map to Parcel / Go2

**Codebase anchors (clocks / Hz):**

- `RobotRuntime.__init__(..., loop_hz: float = 10.0)` in `src/parcel_robot/runtime.py` sets the ~10 Hz behavior tick (`self.loop_period = 1.0 / loop_hz`).
- `ControlTiming` in `src/parcel_robot/control/models.py`: `control_hz` (default 50), `command_timeout_s` (0.35), `state_timeout_s` (0.25), plus stop/settling budgets; `period_s` is `1/control_hz`.
- `TimedVelocitySetpoint` (`issued_at`, `valid_until`, `expired()`) is the leased body-velocity target; `frame` must be `"base_link"`.
- `ControlManager` (`src/parcel_robot/control/manager.py`) is the 50 Hz-class watchdog/writer; `ControllerStatus.feedback_age_ms` / `command_age_ms` expose age for readiness checks (see `runtime.py` comparing `feedback_age_ms` to `state_timeout_s`).
- `UnitreeSportController.update` calls SDK `Move`; `stop` calls `StopMove` — transport ACKs only (`src/parcel_robot/control/unitree_sport.py`). Freshness is `UnitreeSportStateSource.latest()` from `rt/sportmodestate`.
- `docs/MOTION.md` nested-loop section: nav ~10 Hz → ControlManager → onboard Sport → motors. Simulator sync manager is ticked by the runtime loop unless you pass an external `control_manager`.
- Python + host OS are not a certified crash-stop clock domain; keep robot-side watchdog + physical E-stop.

## Failure story

A follow controller assumed “10 Hz means every 100 ms.” Under CPU contention the runtime loop occasionally took 280 ms. Between ticks the last `vx` lease was still valid for 350 ms, so Sport kept walking while camera tracks aged past the perception TTL. The dog closed on a stale owner bearing and clipped a chair leg. The bug was not “follow math”; it was treating average loop rate as a deadline and not coupling command leases to *sensor* freshness. Fix: expire motion when either the command lease or the perception age budget fails, and measure max inter-tick gap, not only mean Hz.

## Retrieval questions

1. What is the difference between average loop rate and a deadline? Give a Parcel timeout that enforces the latter.
2. Why is the LLM disallowed from the balance timescale even if it is “smart”?
3. (From Day 01) If `Move` returns success but `RobotStateSource` samples are older than `state_timeout_s`, which state kinds do you trust, and what should `ControlManager` do?

## Optional 10-minute exercise

Read `ControlTiming` and the nested-loop section of `docs/MOTION.md`. Sketch a table with columns: layer, period, deadline, max sensor age, failure action. Fill rows for RobotRuntime (~10 Hz), ControlManager (50 Hz), and Unitree Sport (onboard). Mark which rows Parcel implements in Python versus which it only supervises.
