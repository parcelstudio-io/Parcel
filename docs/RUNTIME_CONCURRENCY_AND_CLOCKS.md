# Runtime concurrency, clocks, and ownership

**Status:** implemented topology and known limitations, audited against the
2026-08-04 worktree. This document describes the normal source-checkout stack;
it is not a hard-real-time guarantee or a physical Go2 commissioning record.

Parcel is deliberately split by responsibility and timescale. The important
production property is not the number of threads: it is that concurrent work
cannot create a second locomotion authority.

Primary implementation references are
[`runtime.py`](../src/parcel_robot/runtime.py),
[`control/manager.py`](../src/parcel_robot/control/manager.py),
[`voice/pipeline.py`](../src/parcel_robot/voice/pipeline.py),
[`audio/voice_loop.py`](../src/parcel_robot/audio/voice_loop.py),
[`duplex/frames.py`](../src/parcel_robot/duplex/frames.py),
[`duplex/session_log.py`](../src/parcel_robot/duplex/session_log.py),
[`context/builder.py`](../src/parcel_robot/context/builder.py), and
[`sim.py`](../src/parcel_robot/sim.py).

## Process topology

```text
scripts/launch_stack.sh (lifecycle supervisor)
├── llama.cpp reasoner                    HTTP :8080
├── whisper.cpp ASR, when requested       TCP  :8178
├── Fish Speech, when requested           HTTP :8091
└── scripts/launch_sim.sh
    ├── parcel_robot.sim                  Unix socket; MuJoCo world owner
    └── parcel_robot.web_panel            HTTP :8765; RobotRuntime owner
```

`launch_sim.sh` stops the sibling process when either the simulator or panel
exits. `launch_stack.sh` stops only services it started; an already-healthy
service is reused and left running. The simulator is the sole MuJoCo world
writer and polls its Unix socket in the physics/viewer loop. The panel process
owns `RobotRuntime`, the command arbiter, voice session, dashboards, and the
simulator backend client.

The physical Unitree entry point is different: it constructs an explicit
commissioned-gateway `ControlManager` whose backend is only the typed Unix
client. The separate `parcel-gateway` process is the sole SDK/DDS writer.
Configuration alone cannot inject or arm that composition, and the standalone
commissioning CLI is mutually exclusive with the gateway under their shared
fixed writer lock.

## Threads inside the runtime process

| Execution context | Nominal cadence | Responsibility | Authority boundary |
| --- | ---: | --- | --- |
| `parcel-control-loop` | 10 Hz | Observe, update follow/search/spatial/navigation, tick the task executive, arbitrate, apply the reactive gate, dispatch motion, and produce a D0 duplex frame | The only behavior loop that selects the active body command |
| `parcel-*-control` | configured 50 Hz on an explicit/physical manager | Refresh the leased target, read feedback, enforce state/command watchdogs, confirm stops | Sole application-side controller writer; the gateway remains sole vendor writer; simulator mode is synchronously ticked instead |
| `parcel-expression` | 50 Hz | Add bounded breathing/reaction/beat offsets | Decorative and subordinate; no locomotion lease |
| `parcel-service-health` | every 10 s | Probe model services and, when enabled, audio devices | Observability only |
| `parcel-voice-input` | queue-driven | Serialize committed text turns and call deterministic routing/model/planner code | May propose/commit typed actions through the current-turn guard, never raw motor output |
| `parcel-voice-output-*` / filler worker | per utterance | Sentence-chunked TTS and cancellable sink handoff | Speech/expression only |
| `parcel-voice-microphone` | 30 ms capture frames | Echo guard, VAD/endpointing, utterance-buffered ASR submission, and barge-in | Partial text never executes |
| `parcel-voice-speaker` | queue-driven; about 50 ms interrupt blocks for the default player | Ordered device playback | Audio only |
| HTTP request threads | request-driven | UI, read-only state/latency endpoints, and Host/CSRF-checked command submission | Commands re-enter `RobotRuntime`; handlers do not write the controller directly |
| `context-*` workers | per enabled context build, 150 ms default budget | Collect opted-in local context sources in parallel | Read-only prompt context; timed-out results are discarded |

The simulator-backed manager is intentionally different from the physical
case. `RobotRuntime` builds it internally and calls it synchronously from the
10 Hz dispatch path. An explicitly supplied controller manager starts its own
thread at `control.control_hz` (50 Hz by default). Therefore a 50 Hz setting in
the YAML does not make the browser/MuJoCo behavior planner a 50 Hz loop.

## Command ownership and synchronization

```text
HTTP / final voice turn / autonomous channel
                 │
                 ▼
       semantic action or VelocityCommand
                 │
       current-turn + generation checks
                 │
                 ▼
       CommandArbiter (priority + TTL)
                 │
       reactive collision/safety veto
                 │
       jerk/acceleration shaping
                 │
                 ▼
       ControlManager leased target
                 │
                 ▼
       simulator adapter or Unitree Sport
```

Runtime locks protect different invariants rather than one global critical
section:

- `_command_lock` linearizes preemption, behavior cancellation, and motion
  submission;
- `_agent_lock` prevents concurrent agent reasoning state mutation;
- `_navigation_lock` protects mission/navigation state;
- `ControlManager` owns its lifecycle/target lock and serializes controller
  calls separately;
- the voice session owns turn/epoch state and does not hold that lock across
  simulator, model, or device I/O.

The last point matters: a new partial/final turn can cancel reasoning or audio
while a previous action is pending. Once an action crosses the guarded commit
point, later barge-in cannot undo physical work already performed; it can only
preempt subsequent execution through the normal channel rules.

## Queues, backpressure, and cancellation

- Final voice turns enter one input queue. New input increments the speech
  epoch, cancels active output/reasoning, and marks older queued turns
  superseded; partial transcripts never dispatch actions.
- Audio capture uses a bounded 64-frame queue and drops frames rather than
  blocking the PortAudio callback. Speaker output uses a bounded 256-chunk
  queue and drops new chunks on overflow. Both cases are observable warnings or
  counters, but neither currently has an admission-control policy.
- Speech output workers carry a cancellation event. Barge-in increments the
  epoch, flushes queued speaker chunks, and prevents stale output from being
  re-armed. The default speaker checks interruption about every 50 ms; injected
  players may only stop between chunks.
- D0 duplex TEXT events use an unbounded in-memory deque and drain one token per
  frame. ACT events are last-write-wins for the next frame. A long text burst
  can therefore lag behind speech at 10 Hz; D0 is an aligned observation/log
  stream, not the spoken-audio transport.
- The duplex session log writes synchronously from the 10 Hz runtime loop.
  Rotation and local disk latency can add loop jitter; this has not been load-
  tested for long sessions.

## Clock domains and metric meaning

| Clock/value | Use | What it does not prove |
| --- | --- | --- |
| `time.monotonic()` | Turn stages, deadlines, TTLs, controller freshness, loop work/overrun, filler policy | Cross-host or wall-clock correlation |
| `time.perf_counter()` | MuJoCo wall synchronization | Physical real-time fidelity when the simulator falls behind |
| `time.time()` | Human-correlatable `wall_s` in duplex JSONL | A monotonic latency interval |
| simulator `observation.timestamp` | Perception freshness | Hardware clock synchronization unless a hardware adapter supplies it |
| `DuplexFrame.t` | Monotonic frame sequence | A measured 10 Hz deadline |

`FrameInterleaver.tick()` always returns one frame when called, but it neither
sleeps nor catches up after a missed deadline. The caller supplies the cadence.
Its current `missing_frames` counter checks sequence discontinuity; because `t`
increments on every call, it does not detect wall-clock deadline misses. Use
`ControlLoopOverrun` and compare `expected_t_from_clock` with `t` when auditing
cadence until a dedicated deadline-miss counter is implemented.

Likewise, `tts_first_chunk` means synthesis produced a chunk and
`audio_first_playback` currently means the sink callback accepted it. Neither
is an acoustic presentation timestamp. `SpeakerSink` has a worker-thread
chunk-start callback, but the headline latency contract still needs a device-
presentation timestamp before it can claim end-of-speech-to-audible latency.

## Failure and shutdown behavior

- Runtime startup is transactional: if a sibling thread/controller fails to
  start, `close()` is invoked and startup reports the cleanup failure as well as
  the original error.
- Runtime close latches command acceptance off, interrupts the executive,
  preempts behavior channels, engages software E-stop, requests a controller
  stop, and joins workers with bounded waits.
- `ControlManager` treats stale commands or state, excessive tilt, controller
  exceptions, and unconfirmed stops as faults. Its emergency path can use a
  separate thread so a blocked ordinary controller call does not prevent a
  stop attempt.
- Missing microphone/audio dependencies degrade the normal browser runtime to
  text mode. Physical control must not depend on audio availability.
- Daemon threads improve developer shutdown behavior but are not durable job
  supervision. A production service manager must expose liveness, restart
  policy, and data-flush guarantees per process.

## Why this design, and its limits

**Advantages:** slow model/device work stays off the motion loop; each component
has a narrow authority; epochs make stale speech and D0 frames cheap to reject;
process isolation prevents ROS/model/simulator dependency conflicts; the same
contracts work in deterministic headless tests.

**Limitations:** Python threads and the GIL are not hard real time; the runtime
loop uses sleep-after-work and does not catch up missed behavior ticks; some
diagnostic logging occurs on the control path; HTTP/provider timeouts cannot
kill already-running Python work; timestamps stop at software boundaries; and
thread scheduling has not been characterized under simultaneous GPU inference,
ASR, TTS, logging, and simulator load.

Before physical production, measure P50/P95/P99 loop jitter and stop latency
under the full stack, move blocking logs off control threads, add bounded duplex
TEXT backpressure and real deadline-miss accounting, timestamp audio/device and
actuator presentation, and run the vendor driver in an OS-scheduled native
process while retaining the existing `ControlManager` contract.
