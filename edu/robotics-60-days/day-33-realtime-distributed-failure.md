# Day 33: Real-Time and Distributed Failure Semantics

## Mental model

A companion robot is a small distributed system with irreversible actuators. Processes die, queues fill, clocks drift, Wi-Fi drops, GC pauses, and vendors wedge. “Real-time” here means *predictable enough to meet a deadline*, not “fast on average.” Failure semantics must be explicit:

```text
no message      →  decay to safe stop (TTL / lease expiry)
late message    →  discard or stop (staleness), never act “catching up”
duplicate msg   →  idempotent apply or sequence reject
split brain     →  single writer + generation/epoch
watchdog bark   →  stop + fault class, then require clear
E-stop          →  latch; clear is a separate privileged act
```

Parcel encodes this with motion leases, command timeouts, state freshness, stop confirmation, and a persistent emergency latch—not with optimism.

## Software-engineering analogy

Treat locomotion like a leadership lease in etcd/Consul: you may write only while you hold a fresh lease; expiry fences you. Watchdogs are like liveness probes that *fence traffic*, not dashboards. Bounded queues with backpressure beat unbounded buffers that postpone OOM into a sudden freeze mid-crosswalk.

**Tradeoffs:**

- Short TTL → snappy fail-safe, more chatter, sensitive to jitter.
- Long TTL → smoother under load, longer runaway if a publisher wedged “last good cmd.”
- Process isolation → crash containment vs IPC latency and schema versioning.
- Soft real-time Python ticks (~10–50 Hz paths) vs hard real-time motor loops: different budgets; do not pretend one runtime fits both (D10).

## Light equations (freshness and leases)

```text
lease_valid(t)  ⇔  t < t_grant + TTL
cmd_fresh(t)    ⇔  t − t_stamp < command_timeout
state_fresh(t)  ⇔  t − t_state < state_timeout
safe_cmd(t)     =  cmd if lease∧fresh∧¬estop else STOP
```

Illustrative Parcel defaults from `ControlTiming`: `command_timeout_s ≈ 0.35`, `state_timeout_s ≈ 0.25`. The arbiter’s intent TTL is the application-level lease; the manager’s timeouts are the physical writer’s lease.

## ASCII diagram

```text
  Producer A (follow) --TTL-->\
  Producer B (manual) --TTL--+--> CommandArbiter --lease--> shaped cmd
  Producer C (nav)    --TTL-->/          |                    |
                                    E-stop latch              v
                                                         ControlManager
                                                         /     |      \
                                                   timeout   watchdog  state age
                                                       \     |      /
                                                         STOP + confirm
                                                              |
                                                         Sport / sim
```

## Map to Parcel / Go2

From `DESIGN_DECISIONS.md` D2, `core/arbiter.py`, `control/manager.py`, `safety.py`, and `INTRO.md` deadlines section:

- `CommandArbiter`: higher priority owns motion; every `MotionIntent` expires; `engage_emergency_stop` clears active intent and latches.
- `ControlManager`: single writer; feedback watchdog; stop delivery generations; E-stop can latch while slow `activate` returns; post-stop confirmation uses increasing state sequence numbers.
- `reactive_safety`: telemetry older than `telemetry_stale_s` (~0.6 s) blocks translation—stale perception is a stop, not a shrug.
- Simulator independently enforces bounds, watchdog, collision stop, and transport E-stop; debug hotkeys bypass the runtime arbiter—commissioning must not confuse those paths with product guarantees.
- Unitree Sport lease (`enable_lease` must be true for physical control in `control/factory.py`) is a vendor-level exclusive ownership story aligned with Parcel’s single-writer rule.
- Clock domains: use monotonic clocks for TTLs inside a process; never mix wall-clock NTP steps into lease maths without a mapped timeline (foreshadow Day 39).

**Design choice:** fail closed on missing/stale data. Cost: more defensive stops and possible deadlock in crowds. Benefit: a dead UI cannot leave a nonzero velocity “forever.”

**Codebase anchors (leases / TTL / watchdogs):**

- `core/commands.py` → `MotionIntent.ttl` (default 0.35) + `expired(now)`; `SOURCE_PRIORITIES` (`manual` 80 > `follow` 40 > `navigation` 30).
- `core/arbiter.py` → `CommandArbiter.current` drops expired intents; `stop()` clears lease; `engage_emergency_stop()` latches.
- `control/models.py` → `ControlTiming.command_timeout_s` / `state_timeout_s`; `TimedVelocitySetpoint.expired`.
- `control/manager.py` → stops on `command_watchdog_expired` / `command_expired_during_delivery`; E-stop can latch during slow `activate`.
- `runtime.py` → builds `MotionIntent(..., ttl=ttl)`; calls `control_manager.stop("intent_expired")` when the arbiter lease dies.
- `navigation/reactive_safety.py` → `telemetry_stale_s` blocks translation; `sim.py` independent motion watchdog (~0.65 s) + transport `emergency_stop`.
- `control/factory.py` → physical Sport requires `enable_lease=True`.

## Failure story

During a sidewalk demo, the laptop UI thread blocked on a model call and stopped renewing teleop leases—but an older navigation intent had been given a 5 s TTL “for comfort.” The dog continued the last nav velocity while the operator stared at a spinning cursor. A pedestrian stepped in; software E-stop worked only after the UI unblocked enough to send it. Postmortem: TTLs were tuned for convenience, not hazard; navigation renewals and UI heartbeats were not separated; stop path shared the blocked thread. Fix: short motion leases, independent E-stop channel, and never stretch TTL to hide planner latency.

## Retrieval questions

1. What is the difference between cancelling the current lease and engaging the emergency latch?
2. Why are p95 latency and max deadline-miss count both required, not only the mean tick rate?
3. (Week-back) How do Day 11’s nested timescales argue that the LLM process must not be on the stop-critical path?

## Optional 10-minute exercise

In `core/arbiter.py` and `control/models.py` (`ControlTiming`), list every timeout/TTL. For each, write the failure mode if it were 10× larger and if it were 10× smaller. Propose one pair of values for fenced hardware bring-up vs sidewalk companion operation and justify the asymmetry.
