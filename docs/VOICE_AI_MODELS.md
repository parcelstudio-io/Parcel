# Voice intelligence and model design

Last checked against the repository, installed artifacts, and retained
evaluation records on **2026-08-04**. This document separates implemented code
from the active host profile and from research proposals.

## The implemented architecture

```text
browser partial/final text       16 kHz microphone frames
          |                     -> VAD/optional semantic endpoint
          |                     -> utterance WAV -> whisper.cpp
          +-----------------------------+
                                        v
                            finalized transcript only
                                        |
                         deterministic intent router
                         /          |             \
                direct command   conversation   deliberative task
                      |           JSON model      PlanIR model lane
                      |              |             |
                      +------ validation / task executive ------+
                                        |
                         deterministic controllers + safety
                                        |
                                  simulator / Go2

reply text -> sentence/emote adapter -> Piper or Fish -> SpeakerSink
                              `-> ProsodyTap -> expression scheduler

validated reply + post-gate runtime events
          -> D0 TEXT/ACT interleaver -> shadow decoder + local JSONL
```

The control boundary is intentionally text and typed semantics. Raw audio,
Whisper features, Fish codec tokens, and prosody never become motor commands.
The model may propose only allowlisted tools, a strict plan contract, or one
bounded next action. Deterministic code owns joint values, trajectory
compilation, task admission, collision response, and E-stop.

## Effective status

| Part | Repository status | Effective desktop status |
| --- | --- | --- |
| Deterministic intent router | Implemented and active | Active for every final transcript |
| Conversation model lane | Implemented through llama.cpp | Gemma artifact installed; server must be launched |
| Deliberative planner lane | Implemented as an independent provider boundary | Uses the same Gemma provider by default; no separate planner model is configured |
| Structured model output | Implemented | JSON-schema constrained, parsed, then safety-validated |
| Dynamic prompt composition | Implemented and active | Owner profile, current situation, emote policy, and stub weather tool are composed under character budgets |
| whisper.cpp | Provider, server binary, and `base.en` weights installed | Server was not running in this audit; no microphone endpoint connected |
| Energy endpointing | Implemented and default | Becomes active only when STT is healthy and capture starts |
| Silero v6 + Smart Turn v3 | Implemented and runtime-wired | ONNX artifacts and `onnxruntime` absent; not active |
| Piper | Provider and install/run scripts implemented | Configured default, but binary and voice absent |
| Fish S2 | Provider and isolated service implemented | Optional; not the configured default and not running |
| Duplex cancellation | Implemented | Browser-tested; acoustic barge-in awaits a device/AEC integration |
| D0 TEXT/ACT framing | Implemented and enabled | Observes existing reply/action events at the nominal control-loop cadence; shadow-only and not model-generated |
| Deterministic filler policy | Implemented and enabled | Predictive for planner/info-tool paths plus a 700 ms watchdog; real speaker behavior is unverified on this host |
| Native speech-to-speech model | Research only | No native-audio model has dispatch authority |
| Dual-head TEXT/ACT model | Planned D1 | No installed model emits Parcel's frame vocabulary and no live ACT adapter exists |

### Runtime endpoint and artifact paths

`RobotRuntime` never opens a GGUF directly. Its `LlamaCppProvider` calls the
OpenAI-compatible endpoint configured by `language_model.base_url` (canonical
`http://127.0.0.1:8080`) and uses `language_model.model` as the server alias.
The launcher owns artifact selection:

| Path | Role |
| --- | --- |
| `models/gemma-4-26b-a4b/gemma-4-26B_q4_0-it.gguf` | Installed admitted Gemma artifact used by both CPU and default GPU launchers |
| `third_party/llama.cpp-bin/llama-b10235/llama-server` | CPU rollback server used by `scripts/launch_reasoner.sh` on port 8080 |
| `configs/reasoner/llama_cpp_cuda12_oci_b10236.json` | Provenance, hash, model, device, and memory admission profile for the CUDA server |
| `third_party/llama.cpp-oci/llama-b10236-cuda12/rootfs/app/llama-server` | Staged admitted CUDA binary; `scripts/launch_reasoner_gpu.sh` defaults to port 8081 unless overridden |
| `models/reasoner/ministral-3-8b-*/` | Installed rejected challenger artifacts; no canonical runtime selects them |

At this audit no reasoner was listening on 8080 or 8081. Starting the GPU
launcher on its default 8081 does not connect the canonical runtime; use an
explicit port override or a matching experimental `base_url`. See
[Parcel llama.cpp CUDA profiles](REASONER_GPU_PROFILE.md) for immutable hashes
and retained measurements.

## Crucial design choice: engineered cascade, not native speech-to-speech

Parcel uses an engineered speech cascade with a text reasoning boundary:

```text
audio -> endpoint -> ASR final -> text brain -> validated semantics -> TTS
```

Advantages:

- the exact transcript, model decision, and accepted action can be logged and
  replayed independently;
- ASR, reasoning, TTS, and endpointing can be replaced and benchmarked one at
  a time;
- strict JSON schemas and deterministic validators sit between probability
  and physical motion;
- audio codec tokens cannot be mistaken for robot-action tokens; and
- the same safe path works from a browser when audio hardware is absent.

Limitations:

- endpointing, complete-utterance STT, model generation, and first-sentence TTS
  are serial today, so natural conversational latency is higher than a native
  duplex model;
- although llama.cpp is read as a stream for cancellation and TTFT, Parcel must
  accumulate and validate the complete structured JSON decision before any
  reply text reaches TTS;
- finalized text discards tone, hesitation, laughter, speaker overlap, and
  other paralinguistic evidence;
- an ASR error becomes the model's semantic input unless a later layer notices
  inconsistency;
- microphone ASR emits no partials, so speculative conversation cannot yet
  hide model latency; and
- interruption is energy/speech driven rather than content aware, so a brief
  backchannel can cancel a reply.

A native speech-to-speech model may later supply expressive audio or an
inner-monologue proposal, but it should not gain direct PlanIR or actuator
authority until it demonstrates typed tool reliability at the robot's safety
bar. The cascade boundary remains the production default.

## Crucial design choice: router, conversation, and planning lanes

Parcel does not run “Gemma to extract intent, then another LLM to plan.” Every
final transcript first passes through `DeterministicIntentRouter`, which emits
a versioned `IntentFrame` and selects one of three paths:

1. reviewed direct commands (stop, follow, bounded spatial movement, catalog
   skills, navigation grammar) bypass model inference;
2. ordinary language goes to the fast conversation contract; and
3. compound/corrective physical tasks go to the deliberative PlanIR contract.

The conversation and planner provider interfaces are independent, but
`VoiceAgent` defaults `planner_model` to `language_model`. Thus the active
design is **split contracts and routing over one resident Gemma backbone**, not
two deployed brains. Both lanes receive the original transcript; one model's
paraphrase never becomes another model's instruction.

This choice saves memory, avoids another lossy intent-extraction hop, and lets
deterministic commands stay fast. Independent interfaces still permit a later
small conversational model or specialist planner. The trade-offs are resource
contention and correlated failure: a slow, unavailable, or systematically
wrong shared model affects both lanes. Before splitting models, a challenger
must beat the incumbent on conversation quality, semantic planning, latency,
memory, and recovery behavior—not merely TTFT.

The planner is not a controller. It produces schema-constrained PlanIR (or the
experimental PlanSketch contract), which is context-bound, validated against
fresh camera/LiDAR state and a skill registry, and admitted by the task
executive. Control-rate execution makes no LLM call.

## Structured conversation and action authority

The fast model returns one JSON object containing `reply`, up to four tool
calls, `intent`, optional bounded affect, and at most one `next_action`.
llama.cpp converts the response schema to a generation grammar; Parcel then
parses and validates the result again.

Important guards include:

- the conversation model cannot call raw `set_velocity` or switch a motion
  backend;
- a negated, hypothetical, or information-seeking utterance cannot trigger
  model-produced physical motion;
- only one motion-producing action is admitted per decision;
- affect-driven actions require confidence at or above 0.75, must match the
  active personality mapping, and must be a cataloged social trajectory;
- unknown tools, poses, skills, fields, and joint values fail closed; and
- a newer partial/final turn can supersede a model result before its action
  crosses the commit guard.

Emergency phrases (`stop`, `stop now`, `emergency stop`) bypass model
generation and latch the safety path synchronously. The model-facing safety
layer is still not a hardware safety controller; Unitree velocity, torque,
temperature, heartbeat, stale-command, and physical E-stop enforcement remain
separate obligations.

## Dynamic prompts, personality, and memory

The system prompt comes from versioned personality/function templates plus
`DynamicPromptComposer`. The composer renders stable sections first and a
bounded volatile turn tail, exposes its last assembly at `GET /api/prompt`, and
contains source failures rather than failing the voice turn.

The trusted assembly boundary is explicit:

- [`system/core.md`](../prompts/system/core.md) owns immutable safety,
  conversational, sensor, and output rules;
- [`system/action_policy.md`](../prompts/system/action_policy.md) defines the
  turn-level `next_action` proposal contract;
- [`personalities/`](../prompts/personalities/) changes tone and maps clear
  sad, happy, and explicit strong-anticipation cues to admitted social skills;
- [`functions/`](../prompts/functions/) adds companion, navigation, spatial,
  patrol, or manual-assistant guidance;
- [`dynamic/runtime_context.md.tmpl`](../prompts/dynamic/runtime_context.md.tmpl)
  labels serialized runtime state as untrusted and potentially stale; and
- [`schemas/agent_decision.schema.json`](../prompts/schemas/agent_decision.schema.json)
  documents the base fast-response shape. The live llama.cpp schema is built
  programmatically by `_decision_response_schema(tools)` so tool arguments
  match the current admitted definitions; this file is not loaded at runtime.

Implemented sources are:

- short owner-profile facts;
- current battery/simulator/task state;
- the admitted emote catalog and use policy;
- recent information-tool results; and
- a read-only weather tool with a clearly labeled deterministic stub.

This is inspectable and prevents unbounded context growth. It is not a full
retrieval system: budgets are character counts rather than token counts,
overflowing turn sections are dropped whole, the weather result is not live,
and the “stable” plane is ordering for prefix reuse rather than an explicit
application-managed KV cache. Operational/manual facts still need a cited,
permissioned retrieval layer.

The prompt contract is deliberately turn-level. It never asks the model for
`DuplexFrame`, `<idle>`, gaze/twist tokens, joint values, or a continuous
attention policy. Filler phrases are currently hard-coded in Python rather
than authored per personality, and the pure attention arbiter is not wired to
these profiles. This separation protects control authority, but it also means
personality does not yet shape fillers or 10 Hz attention decisions.
Keeping the live response schema next to provider code makes the admitted tool
surface dynamic, but the separate reference JSON can drift; a generated-schema
parity test would be safer than treating both as authorities.

`ConversationMemory` stores text roles/messages in SQLite and never raw
microphone audio. Prompt retrieval is bounded, but the database itself has no
retention/pruning bound. Persistence is not yet opt-in or encrypted, and no
user-facing erase workflow is implemented; those are production requirements.

## Model selection: evidence before promotion

### Admitted incumbent: Gemma 4 26B-A4B Q4

The installed 14.4 GB Gemma GGUF is Parcel's tested shared backbone. The CPU
launcher remains the rollback path. A provenance-pinned llama.cpp b10236 CUDA
profile was separately admitted with 31/31 layers offloaded and about 15.3 GB
attributed idle GPU memory.

Retained evidence is deliberately scoped:

- frozen PlanIR generation: 5/5 cases; warm median TTFT 855.379 ms and median
  complete usable plan 5,657.459 ms on the admitted GPU profile;
- machine conversation suite: 10/10 parsed, 6/10 machine-case acceptance,
  10/10 affect checks, 9/10 structured-safety checks, and 7/10 semantic
  heuristics, with no human quality score; and
- embodied frozen-plan execution is tested separately, so the language-model
  result alone proves no navigation or Unitree behavior.

Ordinary conversation disables thinking and caps generation at 256 tokens.
Deliberative mode has a separate 1,024-token budget but also defaults to no
thinking because prior hidden reasoning could exhaust the budget before valid
JSON. See [the admitted GPU profile](REASONER_GPU_PROFILE.md) and the
[conversation ledger](../evals/companion/conversation_quality_v1/results/README.md).

### Installed but rejected: Ministral 3 8B challengers

The Instruct Q4_K_M artifact is installed and achieved much faster median TTFT
(101.944 ms), but it scored 5/10 machine conversation acceptance and 3/5
PlanIR cases, with no complete-call latency win over Gemma. It was not
promoted. The separate Reasoning checkpoint failed its predeclared one-case
PlanSketch compatibility gate after malformed/repeated output exhausted 1,024
tokens. It is also not active.

This is the key model-selection lesson: fewer active parameters and faster
first tokens do not guarantee faster valid structured output or safer task
semantics.

### Research candidates, not runtime claims

Qwen3.6-35B-A3B Q4_K_M remains a plausible A/B candidate for nuanced
conversation and tool use, but it is **not downloaded, profiled, or evaluated
in this repository**. It must pass the same frozen conversation, PlanIR, and
embodied gates before documentation calls it better. Kimi K2.5 remains
impractical for this single workstation because its checkpoint targets a much
larger serving footprint.

Official model references:

- [Gemma 4 26B-A4B QAT GGUF](https://huggingface.co/google/gemma-4-26B-A4B-it-qat-q4_0-gguf)
- [Qwen3.6-35B-A3B](https://huggingface.co/Qwen/Qwen3.6-35B-A3B)
- [Ministral 3 8B Instruct](https://huggingface.co/mistralai/Ministral-3-8B-Instruct-2512)
- [Kimi K2.5](https://huggingface.co/moonshotai/Kimi-K2.5)

Check each model card's current license before distribution; the runtime
architecture does not imply that all model artifacts share one software
license.

## ASR, VAD, and turn endpointing

`WhisperCppProvider` sends a completed WAV utterance to the local
`/inference` endpoint. `base.en` is the installed English prototype model. It
is modular and local, but the call re-decodes the utterance after endpointing;
it is not incremental streaming ASR.

The default runtime segmenter is dependency-free `EnergyVad`. The optional
semantic mode is already implemented and wired:

- stateful Silero v6 probability on exact 512-sample/16 kHz frames;
- Smart Turn v3 over the last eight seconds with Whisper-Tiny-compatible
  80-bin log-mel features;
- 0.20 s silence for a predicted-complete turn and 2.5 s for an incomplete
  turn; and
- explicit warnings and fixed-timeout/energy fallbacks when models fail.

It is not active on this desktop: the runtime ONNX weights and `onnxruntime`
are missing, and the effective config remains energy endpointing. See [Audio,
latency, expression, and spatial intelligence](AUDIO_LATENCY_AND_SPATIAL_INTELLIGENCE.md)
for the precise fallback and configuration behavior.

Official references:

- [whisper.cpp](https://github.com/ggml-org/whisper.cpp)
- [Silero VAD](https://github.com/snakers4/silero-vad)
- [Pipecat Smart Turn](https://github.com/pipecat-ai/pipecat/tree/main/src/pipecat/audio/turn/smart_turn)

## TTS and audio tokens

Piper is the intended onboard default: CPU-resident, simple, and suitable for
short first-sentence synthesis. Parcel spawns its binary for each sentence and
wraps raw PCM in WAV using the voice metadata's native sample rate. Missing
binary or voice files fail closed at provider resolution; they are currently
missing on this host.

Fish S2 Pro remains the expressive docked/GPU option in an isolated Python
3.12/Torch environment. `FishSpeechProvider` keeps Fish's semantic/RVQ audio
tokens inside the service and exposes only text-in/audio-bytes-out. This is the
right safety boundary: the action brain gains nothing from codec tokens and
would become harder to validate if they entered its vocabulary.

Although the Fish adapter implements its native streaming endpoint,
`RobotRuntime` currently wraps all synthesizers in
`SentenceChunkedSynthesizer`, whose stream calls the inner blocking
`synthesize()` once per sentence. Effective Fish playback is therefore
sentence-chunked, not token/chunk streamed, and in-flight synthesis cannot be
cancelled until that blocking request returns. This should be corrected or
explicitly benchmarked before calling the Fish path low-latency streaming.

Inline `[emote:name:intensity]` tags are removed before TTS and routed through
the validated Gesture proposal path. They are useful sentence-level body
language. With audio they ride the containing `SpeechChunk` and fire from the
speaker-worker chunk-start callback; in text mode they fire when the reply is
logged. Worker start is not a device/acoustic presentation timestamp, and the
gesture is ignored/rejected when activity gates do not admit it.

Fish S2 Pro's model has a research-oriented license; commercial deployment
requires a separate license review. Sesame CSM artifacts exist locally as a
legacy experiment, but no Sesame provider is selected by `build_speech_stack`.

Official references:

- [Fish Audio S2 Pro](https://huggingface.co/fishaudio/s2-pro)
- [Fish Speech source](https://github.com/fishaudio/fish-speech)
- [Piper source](https://github.com/rhasspy/piper)

## Duplex behavior, D0 framing, and expressive output

`DuplexVoiceSession` serializes final turns while TTS runs on an independent
worker. A newer partial or final:

- cancels the active llama.cpp stream cooperatively;
- keeps only the newest queued final;
- invalidates stale actions before the commit point;
- interrupts and flushes speech output; and
- increments a shared speech epoch so queued prosody motion is discarded.

This is genuine concurrency and cancellation at the application boundary, but
not yet robust acoustic full duplex. There is no AEC, microphone ASR does not
emit partials, and the energy guard can suppress quiet barge-in. Hardware AEC
through the XVF3800 speaker-reference path is the intended next integration.

Separately, the enabled `DuplexCoordinator` renders one D0 frame per nominal
10 Hz control-loop tick. TEXT is complete sentence text observed at the TTS
wrapper (or the completed reply in text mode), split into whitespace tokens and
drained one per frame. ACT mirrors post-gate `vx`/`vyaw`, deterministic gaze
callbacks, admitted skills/emotes, and filler events. The consumer decodes in
shadow mode so behavior is not executed twice.

This is useful coarsely time-indexed instrumentation, not a new reasoning model. llama.cpp
does not emit ACT tokens, lateral `vy` is absent from the v1 codec, simultaneous
ACT events collapse last-write-wins, and the unbounded TEXT queue can lead or
trail speech. Setting `shadow_consumer: false` still does not route decoded commands
through the runtime. See [Duplex dual-stream voice agent](DUPLEX_DUAL_STREAM_DESIGN.md)
for logging, clock, privacy, and D1 promotion limits.

The active filler path acknowledges deliberative planning and information tools
predictively, or other TTS delays via the watchdog. A filled answer waits for
the short filler worker to finish synthesis/enqueue before starting. The
configured two-second ceiling uses generated/queued or text-mode logical
markers; it is not an acoustic service-level guarantee.

Expression is intentionally subordinate to task motion. The 50 Hz layer adds
bounded idle body offsets, owner-orient/thinking state, and prosody-timed head
nod state. It turns off for E-stop, critical battery, proximity hazards, and
skills, and becomes head-only during locomotion. That priority design is safe
and composable, but Go2's lack of a neck means beat nods and head-only motion
are not physically embodied yet; only body height/pitch offsets actuate in the
MuJoCo stance.

## Runtime and installation

The app environment stays lightweight. Fish keeps its Torch/CUDA stack in its
own Python 3.12 environment; llama.cpp and whisper.cpp are separate native
servers. This avoids ROS/MuJoCo/Python ABI conflicts and lets each heavy service
restart independently.

Reasoner:

```bash
# CPU rollback profile on port 8080
scripts/launch_reasoner.sh

# Admitted pinned CUDA profile (doctor runs before launch)
scripts/launch_reasoner_gpu.sh
```

Speech prerequisites and service lifecycle:

```bash
scripts/install_speech_services.sh --help
scripts/install_speech_services.sh
scripts/run_speech_services.sh
scripts/run_speech_services.sh --check
```

The installer places whisper.cpp and Piper in ignored repository directories;
the service script starts whisper and verifies Piper. Fish remains separate:

```bash
scripts/launch_fish_speech.sh
```

`speech.mode: auto` uses whichever STT/TTS roles are healthy and otherwise
keeps text control available. `speech.mode: audio` requires both roles and
fails startup if either is unavailable. The default `configs/robot.yaml` now
places supported audio settings under `speech:`. `fish_reference_id` is a real
Fish-provider input. `fish_streaming` and `barge_in` are absent from that
canonical file and survive only in the divergent packaged fallback
`src/parcel_robot/config/robot.yaml`; current fail-closed validation rejects
them. Barge-in is wired by microphone-loop construction rather than a boolean
toggle. Do not assume a visible YAML key is effective without a consumer and
contract test.

Keep every model service on loopback unless authentication, authorization, and
transport encryption are added.

## Latency and evaluation policy

`/latency` records model TTFT, complete reasoning, planner stages, TTS stages,
action commit, status, query, and response. The current final-text clock starts
after microphone endpointing and STT, and first “spoken” audio is only a queue
handoff, so the dashboard does not yet prove acoustic end-to-end latency. A
filler can become the first audio response in an audio turn; in text mode the
same filler is only a logical marker and does not count as the logged first
response. Filled turns also reuse one turn id, so first-write TTS stage metrics
can describe the filler while `turn_complete` describes the eventual answer.

Initial product gates should remain:

| Boundary | Target / policy |
| --- | --- |
| Complete semantic silence tail | about 200 ms when Smart Turn predicts complete |
| Final STT | measure from semantic commit; not yet instrumented |
| Conversation TTFT | report warm/cold and valid-JSON completion separately |
| Safety validation | under 10 ms and never bypassed |
| First acoustic speech | under 500 ms P50 only after presentation timing exists |
| Emergency stop | deterministic, synchronous, and independent of model health |

Warm models before a latency run, retain failed/superseded traces, and never
promote a model on TTFT alone. Conversation needs human review; planning needs
schema/semantic gates; physical capability needs headless embodied execution
and eventually Unitree evidence.

## Remaining production gaps

- connected and explicitly selected microphone/speaker endpoints;
- hardware AEC and robot ego-noise testing;
- true streaming ASR partials and content-aware interruption;
- endpoint/STT/acoustic-presentation timestamps in the latency ledger;
- native Fish chunk streaming through the runtime wrapper;
- bounded D0 TEXT backpressure, wall-clock frame deadline accounting, and
  asynchronous/privacy-hardened duplex logging;
- a D1 live ACT adapter through typed validation, arbitration, and collision
  safety before any dual-head model can gain execution authority;
- physical expression/neck embodiment and calibrated motion/audio lag;
- encrypted, opt-in memory with an erase workflow;
- authenticated service endpoints and operator enrollment; and
- independently verified Unitree low-level safety, watchdog, and hardware
  emergency-stop behavior.
