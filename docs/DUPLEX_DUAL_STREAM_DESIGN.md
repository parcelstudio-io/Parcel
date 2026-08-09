# Duplex dual-stream voice agent: design and implementation record

Last checked against the 2026-08-04 worktree, including
[`src/parcel_robot/duplex/`](../src/parcel_robot/duplex/), the voice pipeline,
runtime wiring, prompts, configuration, and `DUPLEX_V1` tests.

**Status:** D0 system-composed framing, fillers, epoch cancellation, shadow
decode, and local logging are implemented and enabled in the canonical config.
D1 model-produced frames, live ACT execution, and streaming audio input are
planned. The sprint record is in
[`scrum/20260804/task_5/`](../scrum/20260804/task_5/).

## What is active, and what is not

| Capability | Current state | Boundary |
| --- | --- | --- |
| 10 Hz `DuplexFrame` production | **Active when the runtime control loop is running** | One frame is produced per caller tick. The interleaver itself does not schedule, sleep, or catch up. |
| TEXT frames | **Active observer** | They mirror sentence text entering TTS, or the completed reply in text mode. They do not drive TTS and are not direct LLM-token streaming. |
| ACT frames | **Active observer, shadow-consumed** | They encode selected runtime events and the post-gate body command. They do not drive the robot. |
| Predictive/watchdog fillers | **Active application path** | Predictive hooks cover deliberative planning and information tools; a 700 ms watchdog covers other delayed output. Acoustic behavior is not verified on this host. |
| Epoch cancellation | **Active at application boundaries** | Barge-in/supersession invalidates old TEXT/ACT frames, cancels model/output work cooperatively, and flushes the built-in speaker queue. |
| Local JSONL corpus | **Active by default** | Synchronous, rotating, unencrypted local output under `logs/duplex/`; it is not yet a complete training example schema. |
| D1 dual-head model | **Not implemented** | No downloaded model emits Parcel's TEXT/ACT vocabulary. |
| Live ACT consumer | **Not implemented** | Even `shadow_consumer: false` only records decoded non-idle commands in memory; it has no adapter into runtime admissibility or control. |
| Full-duplex audio input | **Not implemented** | Microphone ASR remains turn-buffered; browser partial text can interrupt but never execute. |

The canonical configuration is:

```yaml
duplex:
  enabled: true
  filler_watchdog_s: 0.7
  response_ceiling_s: 2.0
  frame_hz: 10.0
  logging: true
  log_dir: logs/duplex
  log_rotate_bytes: 2000000
  rng_seed: 20260804
  shadow_consumer: true
```

Unknown keys fail startup. `DuplexConfig` also defaults `enabled` and `logging`
to true when the section is absent, so deployments that do not want local
transcript-derived logs must explicitly set `duplex.logging: false` (or disable
duplex). Disabling logging does not erase existing files.

## Why retain an always-present frame contract

The target design gives speech and behavior one shared, epoch-scoped clock. A
future model can continuously express “say nothing” and “do nothing” without a
special absence-of-output state, while deterministic code retains final motion
authority. This is useful for replay, counterfactual training, and swapping a
producer without changing downstream contracts.

```text
DuplexFrame {
  t: int              # monotonically incremented call/frame index
  epoch: int          # speech epoch; stale queued content is dropped
  text: str           # one whitespace token | <silence>
  act: str            # one discrete ACT token | <idle>
}
```

The contract is “one frame per `tick()` call,” not “proof that 10 Hz was met.”
`RobotRuntime` calls it from the nominal 10 Hz control loop. `t` increments by
one regardless of elapsed wall time, and `missing_frames` compares adjacent
`t` values, so the current counter cannot detect a late or skipped wall-clock
deadline. `expected_t_from_clock` is diagnostic only. See
[Runtime concurrency, clocks, and ownership](RUNTIME_CONCURRENCY_AND_CLOCKS.md)
for the controlling clock and jitter limitations.

## D0 producer: where frames really come from

D0 composes already-existing decisions onto the frame stream:

| Frame source | Actual producer semantics |
| --- | --- |
| TEXT with audio | `SentenceChunkedSynthesizer.on_sentence` emits a complete sentence before its blocking inner synthesis. The coordinator splits it on whitespace and drains at most one word per 10 Hz frame. |
| TEXT without audio | The complete validated reply is observed at `reasoning_response`, split on whitespace, and drained the same way. |
| Twist ACT | The runtime encodes the last command actually sent after arbitration, collision checks, and shaping, but only when `vx` or `vyaw` is non-zero. |
| Gaze ACT | Existing deterministic speech-start/end `ReactionHooks` emit owner/bearing/release observations. They are not decisions from `ReactionArbiter`. |
| Skill/emote ACT | Runtime skill and emote dispatch points mirror their allowlisted names. |
| Filler ACT | A fired filler mirrors one filler-gesture token and separately uses the normal TTS path. |
| Empty frame | The interleaver fills `<silence>` and/or `<idle>`. |

This distinction matters. llama.cpp may stream bytes internally to measure
provider TTFT, but Parcel waits for the complete schema-valid `AgentDecision`
before a reply reaches TTS. D0 does not expose raw generation tokens.

TEXT has an unbounded deque and a maximum drain rate of ten whitespace tokens
per second. Because a sentence is queued before its blocking synthesis, frames
can lead that sentence's audio; because they drain slowly, they can also lag
behind playback. An epoch bump can drop the remainder. ACT is last-write-wins
within a frame window; a twist pushed by
the control-loop tail can mask a gaze, skill, or emote pushed earlier in that
window. These are corpus-fidelity limitations, not motion-safety failures,
because D0 is observational.

## ACT vocabulary and authority

The v1 codec is discrete and allowlisted:

| Class | Current tokens | D0 meaning |
| --- | --- | --- |
| Idle | `<idle>` | No observed ACT event for this frame. |
| Locomotion | 7 `vx` bins × 5 `vyaw` bins | Quantized observation of the outgoing command. Lateral `vy` is not represented, even though the robot stack can use lateral velocity. |
| Gaze | owner, release, and 8 bearing bins | Logical gaze event; Go2 has no articulated neck. |
| Skill/emote | Runtime registry/catalog names | Observation of a validated dispatch, not arguments or completion. |
| Filler | 4 speech tokens + 4 gesture tokens | The runtime currently pushes gesture index 0; speech tokens are in the vocabulary but not emitted by this wiring. |

Unknown tokens fail decoding, and out-of-range twist observations quantize to
edge bins. This codec is not itself a safety boundary. A future live consumer
must decode into typed proposals, revalidate allowlists/arguments and fresh
state, acquire the appropriate lease, and pass the unchanged reactive and
collision gates. `DuplexFrameConsumer` does none of that today; non-shadow mode
only appends decoded commands to an internal list.

## Prompt and model boundary

The current personality, function, and system prompts still request one
turn-level JSON `AgentDecision` with a spoken reply, allowlisted tool calls,
optional affect, and at most one bounded `next_action` skill proposal. They do
not mention `DuplexFrame`, `<idle>`, gaze tokens, or twist bins. The PlanIR lane
separately produces semantic task steps.

That is intentional for D0: prompt changes cannot silently give a language
model continuous control authority. It also means aligned frames are
post-processed observations, not behavior generated by a dual-head model. Any
D1 prompt/tokenizer contract must be versioned separately and evaluated before
promotion.

## Filler policy and the two-second target

The configured product goal is an early acknowledgement when useful output is
slow:

1. `VoiceAgent` invokes the predictive hook immediately before deliberative
   planning and immediately before an admitted information-tool call.
2. The nominal 10 Hz control loop polls a watchdog; if no first TTS chunk (or
   text-mode reply delivery) is observed by 700 ms, one filler wins the
   lock-protected fire slot.
3. The filler uses the ordinary cancellable TTS/speaker path and may trigger
   the thinking expression. Barge-in cancels filler and pending answer together.

Ordinary conversation-model inference has no predictive hook, and there is no
generic “model search” integration; those turns rely on the watchdog. The
seven-entry pool is hard-coded in `fillers.py`, uses a fixed seed in canonical
config, avoids an immediate repeat when alternatives exist, and falls back to
least-recently-used rather than going mute. The pool is not personality YAML,
and runtime currently supplies the default personality gain of 1.0.

“Audible” is currently a software name, not an acoustic fact:

- with audio, `tts_first_chunk` clears the watchdog before the speaker enqueue,
  and `filler_audible` is recorded after the sink callback accepts the first
  chunk;
- in text-only mode, a filler is marked logically audible/delivered immediately
  even though no sound or chat utterance exists; and
- no speaker-worker, PipeWire, device, or microphone-loopback presentation
  timestamp closes the acoustic boundary.

Consequently, `response_ceiling_breaches == 0` means the software saw a reply
chunk or logical/queued filler within the policy window. It does not prove that
the owner heard speech within two seconds.

If the real answer arrives while a filler worker is active, the answer waits
until that entire short filler sentence has completed synthesis/enqueue, then
starts its own output job. The ordered speaker queue preserves source order,
but the handoff is not a confirmed acoustic clause-end timestamp.

### System-initiated speech is not a filler and is not a turn

`DuplexVoiceSession.speak_system` (2026-08-09,
[U35](../backlog/UNVERIFIED.md)) speaks the utterances nobody asked for — the
`Vocalize` skill, localization-health announcements, the yield policy's
ask/re-ask/give-up. It reuses `_run_output`, so the sink, chunk tokens,
playback clock and barge-in behave exactly as they do for a reply, but it
touches **none** of the filler bookkeeping and emits
`system_utterance_start` / `system_utterance_complete` (both registered in
`observability.STAGES`) rather than `filler_*`. A request for help must not
enter `FillerLatency` or be scored against the two-second acknowledgement
ceiling.

Two consequences for this document's contracts. First, the concurrency rule is
**skip, never queue**: if a reply or filler owns the speaker, the system
utterance is dropped and its caller retries on its own timer, because two
output workers would interleave their chunks in one ordered sink. Second, D0
does **not** observe it — every stage it emits carries `kind="system"` and the
runtime short-circuits those before `_duplex_on_voice_stage`, so the TEXT
stream reads `<silence>` while the robot is speaking one. Letting it through
would cancel the in-flight turn's filler watchdog and write a `ttft_s` for a
turn nobody started. This is a corpus-fidelity limitation of the same class as
the ACT last-write-wins rule above, and it is listed here rather than
discovered later.

## Input and cancellation

The active microphone path remains turn-based: VAD/endpointing buffers a whole
utterance, whisper.cpp returns one final transcript, and that final enters the
same guarded voice session as typed input. The canonical endpoint is energy
VAD; Silero + Smart Turn is optional but its artifacts are absent on this host.
Only browser/future recognizer partials currently exercise text-partial
cancellation.

Every final/partial input bumps the speech epoch as appropriate and cooperatively
cancels reasoning/output. The interleaver rejects old-epoch pushes and drops old
queued text; its shadow consumer also rejects frames whose epoch is not current.
This gives a strong application-level stale-work boundary. It cannot retract an
action already committed before the new input, and acoustic barge-in still needs
hardware AEC and real audio devices.

## Logging and privacy

When enabled, D0 synchronously appends compact JSONL from the control loop:

```json
{"type":"frame","t":42,"epoch":3,"text":"there","act":"<idle>","context":{"activity":null,"follow_enabled":false,"expression":{},"owner":{"x_m":1.2,"y_m":0.4,"visible":true}},"wall_s":0.0}
{"type":"turn_outcome","turn_id":7,"ttft_s":0.31,"filler_used":null,"filler_reason":null,"filler_audible":false,"barge_in":false,"wall_s":0.0}
```

The log includes reply-derived text and potentially precise owner coordinates.
It does not currently include the user transcript, model/provider identity,
accepted task result, audio timestamps, sensor provenance, or a stable schema
version, so it is not by itself a complete D1 supervised example. Joinability
with other ledgers is also not defined.

Rotation keeps the current file plus one `.1` generation, deleting the older
`.1` on the next rotation. `log_rotate_bytes: 2000000` is a per-file rotation
threshold, not evidence of the original <2 MB/hour target. Long-session
throughput, disk jitter, and privacy properties have not been measured. Writes
and rotation happen synchronously on the control loop; logs are gitignored but
not encrypted, redacted, permission-hardened, or automatically expired.

## Evaluation and promotion gates

[`DUPLEX_V1`](../evals/companion/duplex_v1/) is an implemented headless harness.
It uses scripted text, deterministic delays, and a synthetic in-memory TTS sink
to check filler arbitration, frame/index continuity under explicitly supplied
ticks, epoch atomicity, codec round trips, and frozen navigation-ledger values.
The results directory currently contains its README but no retained immutable
JSON run or ledger row.

The harness does **not** prove production model TTFT, a 10 Hz wall-clock
deadline, live audio/AEC, acoustic filler latency, model-produced ACT quality,
live ACT admissibility, navigation quality from newly executed episodes, or
Unitree behavior. In particular, its zero-missing-frame assertion cannot catch
late caller ticks for the clock reason described above.

Before D1 can be promoted:

- add a versioned input/context/target schema that includes the user turn and
  preserves lateral motion or explicitly excludes it;
- bound TEXT backpressure, preserve simultaneous ACT events, and move log I/O
  off the control loop;
- implement a real decoded-command adapter through semantic validation,
  arbitration, safety, and epoch/current-turn guards;
- compare D1 with D0 on identical embodied episodes, including idle precision,
  task success, collisions, interruption, and social appropriateness; and
- retain immutable eval evidence, then add streaming ASR/audio input only after
  the output/action contract is safe.

The advantage of this staging is composability: D0 collects inspectable traces
without changing robot behavior, and D1 can be shadowed behind one contract.
The limitation is equally important: an always-present observer stream is not
an always-streaming intelligent agent until a model produces it and a guarded
consumer can execute it.
