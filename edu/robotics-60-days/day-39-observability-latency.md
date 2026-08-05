# Day 39: Observability and Latency

## Mental model

If you cannot see ages and tails, you cannot operate a robot. Observability here means read-only traces and metrics for voice, planning, navigation, and control—not a second joystick. Latency is a vector, not a vibe: sensor age, tick gap, command age, stop latency, reasoning time, TTS time, end-to-end user delay.

```text
p50 impresses demos;  p95/p99/max + deadline misses  operate robots
```

D13: dashboards diagnose; they must not gain actuator authority. Logging is not control.

For companions, voice E2E latency and *motion safety latency* compete for attention. A witty reply at 400 ms is worthless if stop latency is 2 s. Ops views should place them side by side so product polish cannot hide control tails.

Sensor age is part of latency: a fast planner on a 700 ms-old scan is still late relative to the world. Couple perception freshness budgets to motion leases so “smart but stale” cannot remain authoritative.

## Software-engineering analogy

Distributed tracing (spans/stages) plus RED/USE metrics, with the twist that a late span can tip a body. You would not let Grafana’s “retry” button charge cards; do not let a latency panel publish `MotionIntent`s. Absolute monotonic timestamps stay inside the tracker; APIs expose durations relative to a stable reference (query end)—same idea as trace-relative spans.

**Tradeoffs:**

- High-cardinality logs → privacy risk and disk burn (especially raw audio).
- Sparse metrics → blind tails.
- Wall-clock stamps across laptop/robot → illusory intervals; prefer monotonic domains and explicit mapping on hardware (D13 revisit).

## Light equations (ages and percentiles)

```text
sensor_age   = t_now − t_stamp
command_age  = t_now − t_issued
stop_latency = t_motion_settled − t_estop_engage
```

Aggregate stage durations with p50/p95/p99/max (`observability._aggregate`). A single max miss can matter more than a pretty mean Hz.

## ASCII diagram

```text
  user query_end
       |
       +-- reasoning_start --> first_output --> action_commit_*
       |                              \
       +-- tts_start --> audio_first_playback --> turn_complete
       |
       v
  LatencyTracker (read-only) ---- /api/latency ---- latency.html
       |
       X---> no path to CommandArbiter / ControlManager

  parallel control metrics:
  feedback_age_ms, command_age_ms, watchdog stops, E-stop latch
```

## Map to Parcel / Go2

From `DESIGN_DECISIONS.md` D13, `observability.py`, and runtime:

- `RobotRuntime` owns a `LatencyTracker` and `ComponentMetrics` (e.g. filler/turn-commit).
- Voice/text stages are closed (`STAGES`); unknown stage names fail closed.
- Web panel serves latency UI and JSON snapshot without command APIs on that path.
- Control readiness already compares feedback age to `state_timeout_s`—ops must watch the same numbers.
- Stop latency and deadline misses belong next to conversation latency when judging “production.”
- Sensitive raw audio is not required for core latency measurement (D13).

**Design choice:** bounded in-memory turn history (`max_turns`) over infinite logs by default. Cost: short memory. Benefit: predictable overhead and less accidental corpus sprawl.

Replay discipline: log enough to reconstruct `MotionIntent` source/TTL, shield reason codes, and control ages—without requiring raw microphone buffers for every regression. When hardware arrives, add actuator-ACK markers and a monotonic map across host/robot clocks before trusting cross-device intervals (D13).

Stop-latency budget belongs in the same release checklist as voice p95: measure `t_estop_engage` → settled near-zero motion under blocked UI and under killed publisher. If you only chart TTS first chunk, you are optimizing the wrong loop for a robot dog.

**Codebase anchors (observability / latency):**

- `observability.py` → `TurnTrace`, `LatencyTracker.start/mark/finish/snapshot`, `ComponentMetrics.observe_ms`, `_aggregate` → `p95_ms`.
- `observability.STAGES` — `query_end`, `reasoning_*`, `action_commit_*`, `tts_*`, `filler_*`, `superseded`, `error`.
- `runtime.py` → `self.latency = LatencyTracker(...)`; `latency_snapshot()`; stage marks around commit/TTS.
- `web_panel.py` → `/latency`, `/api/latency` read-only handlers.
- `control/models.py` / `ControllerStatus` — `feedback_age_ms` / `command_age_ms` style readiness telemetry (wired through manager status).
- Duplex filler timing: `duplex/filler_policy.py` watchdog vs predictive filler — conversation latency, not motor authority.

Stratify cancelled/superseded turns when quoting p95 reply time—otherwise barge-in looks like a latency win. Control metrics need the same honesty: count watchdog stops and E-stop engagements as first-class events, not log noise. Publish those counters next to voice stages so on-call cannot claim “the model was fine” without checking motion health.

## Failure story

An operator trusted “model latency ~800 ms” on the panel while the dog clipped a doorway. Traces showed reasoning was fine; `feedback_age_ms` spiked when the Wi-Fi telemetry path stalled, and the motion lease was still valid. The team had optimized TTS first-byte and never graphing control ages. Fix: put command/feedback age and watchdog stops on the same ops surface as voice stages, and alert on max age, not mean reply time.

## Retrieval questions

1. Why must latency APIs avoid accepting velocity or E-stop clear commands?
2. Which percentile should gate a release if balance-adjacent supervision misses matter—p50 or max/p99?
3. (Week-back) How do Day 11 deadlines relate to `LatencyTracker` stages vs `ControlTiming` timeouts?

## Optional 10-minute exercise

Read `STAGES` in `observability.py` and `latency_snapshot` usage in `runtime.py` / `web_panel.py`. Sketch three SLOs: voice E2E p95, action-commit p95, and max `feedback_age_ms`. For each, write the fail action (page, slow, stop) and whether evidence today is software-only.
