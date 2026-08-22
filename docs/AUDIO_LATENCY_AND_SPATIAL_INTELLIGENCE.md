# Audio, latency, expression, and local spatial intelligence

The host/audio audit was performed on **2026-08-04**; the endpointing and
release-package state was rechecked on **2026-08-16**. In this document,
**active** means selected by `configs/robot.yaml` and usable in the software
runtime, **wired** means connected through `RobotRuntime` but dependent on
optional artifacts or hardware, **fallback** means deliberately degraded
behavior, and **planned** means no runtime path exists yet. “Active” is not a
claim of live-microphone or on-robot acoustic evidence.

> **2026-08-22 reconciliation.** The XVF3800 now enumerates over USB, and Piper's
> configured binary, voice and metadata are present. Native `sounddevice` /
> PortAudio and a usable product source/sink were still unavailable during the
> recheck; whisper.cpp was installed but stopped. No opened physical audio stream,
> AEC/DoA integration or through-air result is commissioned. The dated desktop
> audit later in this page remains useful history, not the current device list.

## Current status at a glance

| Capability | Status | What is true today |
| --- | --- | --- |
| Browser partial/final text | **Active** | Partials interrupt but never execute; finals enter the same guarded turn path as ASR text. |
| Microphone capture and speaker playback | **Wired, inactive on this host** | `MicrophoneVoiceLoop` and `SpeakerSink` use `sounddevice`/PortAudio. Native `libportaudio2` is absent and no default PipeWire input or output endpoint was connected in the audit. |
| Default endpointing | **Semantic path selected; no live-mic proof** | The canonical profile selects Silero v6 plus Smart Turn v3. The models resolve and `onnxruntime` loads; obviously complete turns use the configured 0.20 s decision and incomplete turns may wait up to 2.5 s. Those are thresholds, not measured acoustic latency. |
| Energy endpointing | **Fallback** | Adaptive `EnergyVad` remains the dependency-free degrade path and historical segmenter. The runtime reports degradation rather than silently claiming the semantic stack. |
| whisper.cpp STT | **Adapter and weights installed; service stopped** | The runtime submits a completed WAV to `/inference`. This is utterance-level, not streaming ASR. |
| Piper TTS | **Artifacts present; playback uncommissioned** | The configured binary, voice and metadata exist. A usable physical output stream and through-air behavior have not been demonstrated. |
| Fish S2 TTS | **Optional service/adapter installed** | The provider exposes streaming, but the runtime's sentence wrapper currently calls blocking `synthesize()` once per sentence, so cancellation and first audio are sentence-granular. |
| Acoustic echo cancellation | **Planned hardware integration** | The software path has only an energy echo guard. An XVF3800-class array must provide the real speaker reference. |
| D0 duplex frames and fillers | **Active in software** | The runtime mirrors reply/action events into a 10 Hz shadow stream and can play deterministic fillers. Frames observe existing behavior; they do not drive speech or motion. |
| Idle/reaction expression | **Active in the runtime** | A separate 50 Hz layer drives bounded body offsets in MuJoCo and reports head/gaze state. |
| ProsodyTap + beat scheduling | **Wired** | Synthesized WAV chunks are analyzed before playback and nod timing is anchored when the sink starts a chunk. Go2 has no neck actuator, so the current head-pitch nod is state/metric output, not physical Go2 motion. |
| Latency dashboard | **Active** | `/latency` shows bounded per-turn traces and rolling component distributions. Audio input and acoustic output boundaries remain incomplete; details are below. |

## Desktop Bluetooth and audio audit

The read-only audit found:

- a powered, unblocked MediaTek USB Bluetooth 5.2 controller (`hci0`);
- BlueZ 5.85, PipeWire, PipeWire Pulse, and WirePlumber running;
- Bluetooth AAC/SBC and hands-free codec support; and
- ALSA capture hardware and drivers.

In the 2026-08-04 audit, no Bluetooth or USB audio endpoint was connected. PipeWire reported only a
dummy output, no source, and no real default sink; `lsusb` showed no XVF3800 or
other USB audio device. Accordingly, `detect_audio_devices()` returned `text
mode`, `connected_input: false`, `connected_output: false`, and `transport:
none`. A powered adapter with A2DP/HFP roles is capability evidence, not a
connected usable headset. This is not a missing Bluetooth driver. It is
compounded by a separate software prerequisite: the installed Python
`sounddevice` distribution cannot import until the missing `libportaudio2`
runtime is installed. The 2026-08-22 reconciliation above supersedes only the
device/artifact inventory; it does not create an operational audio path.

AirPods and similar headsets can be used after pairing. A2DP normally gives
good playback without the headset microphone; opening the microphone switches
to HFP/HSP duplex with lower, typically mono call quality. This is normal
Bluetooth behavior; see WirePlumber's [Bluetooth
configuration](https://pipewire.pages.freedesktop.org/wireplumber/daemon/configuration/bluetooth.html).

The live runtime does **not** use `PipeWireAudioIO`. It uses PortAudio through
`sounddevice`, with an optional device index or case-insensitive name resolved
by `resolve_audio_device()`. `detect_audio_devices()` is an advisory health
monitor, while capture still performs a PortAudio preflight and degrades loudly
if the selected stream cannot open. `PipeWireAudioIO` and `AlsaAudioIO` remain
standalone bounded-utterance adapters.

Inspect the host without changing configuration:

```bash
bluetoothctl devices Connected
wpctl status
.parcel/bin/python - <<'PY'
from parcel_robot.audio_io import detect_audio_devices
print(detect_audio_devices().as_dict())
PY

.parcel/bin/python -c "import sounddevice; print(sounddevice.query_devices())"
```

The final command is expected to fail on the audited host until
`libportaudio2` is installed.

### Current configuration semantics

The audio group in `configs/robot.yaml` is under `speech:`, matching the
runtime. Supported keys that reach their consumers include `fish_url`, device
selectors, `endpointing`, `vad_model`, `turn_model`, `echo_guard_scale`, and
`fish_reference_id` (used when `tts_provider: fish_s2`). The canonical config
now chooses semantic endpointing, leaves devices on the system default, and
selects Piper rather than Fish. Silero v6 and Smart Turn v3 were present and
loadable when that default was owner-authorized on 2026-08-16; the first live
microphone session and measured cutoff/latency evidence are still outstanding.

The canonical config does **not** contain `fish_streaming` or `barge_in` because
the strict speech schema does not accept them. Barge-in is enabled by
construction when a microphone loop exists, not by a YAML toggle. N27 replaced
the previously divergent deployable copies with generated, byte-equal runtime
assets and a release-parity gate. That proves source/package equality for the
checked assets, not a built-wheel installation or working acoustic device.

## Audio path and endpointing choices

The implemented microphone path is:

```text
PortAudio 16 kHz mono int16 frames
  -> echo-energy guard while the robot is speaking
  -> EnergyVad, or optional Silero raw speech decisions
  -> fixed hangover, or optional Smart Turn dual-timeout decision
  -> complete buffered WAV
  -> blocking whisper.cpp /inference request
  -> final text
  -> DuplexVoiceSession
```

`EnergyVad` is small, deterministic, dependency-free, and can adapt its noise
floor. Its limitations are equally important: energy is not speech semantics,
the default 360 ms hangover is paid on every turn, machinery or music can look
like speech, and it has no echo estimate.

The optional semantic path re-buffers the 480-sample capture blocks into the
512-sample windows Silero v6 expects. Smart Turn sees at most the last eight
seconds, left-padded for short turns, and classifies once at the first silence:

- probability at least 0.5: commit after 0.20 s of silence;
- incomplete/uncertain: wait up to 2.5 s; and
- missing/broken Smart Turn: warn and use the fixed 2.5 s timeout.

This avoids clipping natural mid-sentence pauses while making obviously
complete turns faster. It also costs an optional ONNX runtime, can inherit
domain/language bias from its training data, and currently buffers the entire
utterance in memory. If `SileroVad.process()` fails, raw speech detection falls
back to energy. If the turn endpointer itself raises in the microphone loop,
the loop switches to the historical energy segmenter; the in-progress semantic
utterance is not migrated and may need to be repeated.

The whisper.cpp launcher's own Silero model can trim a submitted utterance, but
it does not determine when Parcel commits the live microphone turn. The local
Smart Turn/Silero path and the server-side whisper VAD are separate boundaries.

The biggest remaining latency limitation is STT: `MicrophoneVoiceLoop` sends no
ASR partials. `DuplexVoiceSession` supports partial text, but today those
partials come from the browser or another future streaming recognizer, not from
whisper.cpp capture. Speculative reasoning on stable ASR partials is therefore
still planned.

## AEC, barge-in, and device implications

The current echo guard requires microphone energy during playback to exceed
`noise_rms * threshold_scale * echo_guard_scale`. This reduces self-triggering
but can suppress a quiet owner, especially when the speaker is close to the
microphone. It is not acoustic echo cancellation and does not make hands-free
duplex production-ready.

For the planned XVF3800 path, the speaker must be connected to the array's own
amplifier/DAC reference path. A separate USB or Bluetooth speaker prevents the
array from seeing the exact reference signal and defeats its hardware AEC.
Software still needs to select the array's capture/playback endpoints and test
barge-in under robot motor noise. Bluetooth headphones can validate ordinary
I/O, but HFP latency/quality and the absent shared AEC reference make them a
weaker robot integration target.

Barge-in itself is implemented:

- speech onset above the guard cancels the active model stream and output;
- `SpeakerSink` flushes queued audio and checks cancellation at about 50 ms
  blocks for its built-in player;
- stale TTS chunks cannot re-arm an interrupted sink; and
- the same speech epoch clears scheduled beat motion.

The current policy interrupts on detected speech immediately. Backchannel
classification (letting “mm-hmm” pass without killing a reply), provisional
ducking, and post-AEC confirmation are planned.

## Latency definitions and what they actually measure

Open <http://127.0.0.1:8765/latency>. It is a read-only dashboard backed by
`GET /api/latency`, with the user query and returned response kept in trace
rows rather than metric labels.

The headline metrics are:

- `UserQueryEndToFirstResponse`: final-text submission to the first response
  observable in the application log or audio queue, whichever occurs first.
  A queued filler can win this race in audio mode; a text-only logical filler
  does not create `response_logged` or `audio_first_playback` and therefore
  does not count here.
- `UserQueryEndToFirstReasoningResponse`: final-text submission to the first
  streamed provider output. Deterministic and non-streaming paths use their
  guarded/complete result. A provider TTFT sample is not yet a speakable reply:
  Parcel withholds output until the complete JSON decision validates.
- `QueryEndToFirstSpokenAudio`: final-text submission to first audio-sink
  enqueue, including a filler if it is first. Despite the name, this is not an
  acoustic timestamp.
- `UserQueryEndToFirstPlanOutput` and `UserQueryEndToAcceptedPlan`: planning
  TTFT and validated task-executive admission for deliberative turns.

Per-turn decomposition also includes queue wait, reasoning, action commit,
TTS start/first chunk/total, turn total, planner route/snapshot/decode/
validation/admission, model HTTP and JSON validation time, provider token
usage, completion status, and bounded provider details. Completed-turn p50,
p95, and p99 aggregates exclude errored and superseded turns; separate
status-stratified aggregates retain those cases.

Rolling component metrics include the control/simulator path plus
`TurnCommitLatency`, `ProsodyAnalysis`, `ExpressionLayer`, and
`VoiceEndOfSpeechToFirstAudio`, plus `FillerLatency` and `DuplexProducer` when
D0 duplex is enabled. `ResponseCeilingBreach` is a cumulative counter in
`GET /api/state` under `duplex`, not a duration distribution. Every rolling
component reports latest, mean, p50, p95, p99, maximum, and sample count where
applicable.

### Measurement gaps

For typed input, “query end” is the final HTTP submission. For microphone
input it is currently recorded **after** endpointing and blocking STT, when the
recognized final text is submitted. Therefore the headline metrics omit the
silence tail and ASR request and cannot yet be called acoustic
end-of-speech-to-response latency. The trace source is also currently labeled
`text` for both typed and recognized finals.

`TurnCommitLatency` currently measures speech-onset-to-commit duration, not the
silence-tail decision alone. `audio_first_playback` is emitted after the chunk
is enqueued; `SpeakerSink` has the real worker-side chunk-start callback, but
that callback currently anchors only beat motion, not the latency ledger.
PipeWire/Bluetooth presentation timestamps are not collected. The dashboard's
audio values are thus software lower bounds.

D0 filler timing uses the same caveat. With an audio sink, `tts_first_chunk`
marks the turn answered before the subsequent enqueue, and `filler_audible`
means the enqueue callback returned. In text-only mode it is an immediate
logical-delivery marker despite there being no sound. The two-second ceiling
counter therefore proves only that software observed a generated reply chunk
or logical/queued filler, not that a listener heard one. Because filler and
real reply reuse the same turn id and the latency tracker keeps the first value
for most stages, `tts_start`, `tts_first_chunk`, `audio_first_playback`, and
`tts_complete` can describe the filler while `turn_complete` describes the
later answer. This is useful for first-response latency but makes the current
`TTSTotal` decomposition ambiguous on filled turns.

The duplex frame counter is not a timing metric either. `FrameInterleaver`
increments `t` once per caller tick and never sleeps or catches up; its current
`missing_frames` counter cannot detect a late 10 Hz control-loop deadline. See
[Runtime concurrency, clocks, and ownership](RUNTIME_CONCURRENCY_AND_CLOCKS.md)
and [Duplex dual-stream design](DUPLEX_DUAL_STREAM_DESIGN.md) for the exact
producer and corpus boundaries.

Production measurement needs four additional clocks:

1. capture/VAD speech-end and semantic-commit timestamps;
2. STT request start, first partial, and final transcript;
3. speaker-worker first-sample start; and
4. device/acoustic presentation feedback where the platform exposes it.

Until those are wired, do not claim the roadmap's P50 end-of-speech-to-audio
target from `/latency` alone.

## Expressive speech and motion

The current design deliberately separates **what** from **when**:

- the text brain may select one validated semantic gesture or emit one
  `[emote:name:intensity]` marker from an admitted catalog;
- `SentenceChunkedSynthesizer` strips the marker from speech, attaches it to
  the containing `SpeechChunk`, and the speaker-worker chunk-start callback
  dispatches it through the activity/proposal coordinator; and
- `ProsodyTap` analyzes synthesized PCM with a 10 ms RMS envelope,
  pitch/onset-gated accents, and a bounded arousal score. `BeatLayer` schedules
  those accents against the actual chunk-start callback.

The advantage is that no language model invents joint values, while generated
audio supplies precise timing with pre-playback lookahead. Prosody analysis is
NumPy-only, optional, and failure-isolated: an invalid audio chunk is still
spoken without beat motion. Speech epochs make audio and pending nods cancel
together.

The `ExpressionEngine` runs independently at 50 Hz. It composes deterministic
breathing/weight shifts, VAD-driven owner orientation, a query-pending thinking
pose, and beat timing. One clamp owns all amplitudes. Expression is off during
E-stop, critical battery, proximity events, and authored skills; navigation,
following, or spatial motion permits only the logical head channels.

Current embodiment limitations:

- Go2 has no articulated head/neck. Head yaw/pitch appear in runtime state and
  the 2.5D viewer can show gaze, but `stance_joint_offsets()` maps only body
  height/pitch to leg joints. Beat nods therefore do not physically move Go2.
- Head-only mode during navigation is effectively snapshot-only on Go2.
- Idle body offsets work in MuJoCo, but a physical Unitree expression channel
  and hardware validation are not implemented.
- With audio, inline emotes fire when the speaker worker begins their containing
  chunk; in text mode they fire when the reply is logged. Worker start is closer
  to the words than synthesis time but still not a device/acoustic presentation
  timestamp. Emotes remain constrained to stationary bounded skills.
- Arousal currently changes nod amplitude only. It is not an input to the
  reasoning model or the TTS provider, and no user-voice affect classifier is
  implemented.
- Body bounce, entry/exit blending, backchannel gestures, DoA-based orientation,
  and calibrated hardware actuation lag remain planned.

## Camera/LiDAR knowledge boundary

The reasoning layer's spatial allowlist is `camera` and `lidar`. It must not
claim GPS, privileged simulator state, unseen objects, or map access. The
Google Maps integration remains a fail-closed `NullMapProvider` placeholder.

MuJoCo still derives some idealized detections from simulator truth for
repeatable development. They are test-oracle/adapter data, not evidence that a
production detector exists. Hardware must replace them with camera tracking, a
LiDAR costmap, and state estimation while preserving the observation contract.
The microphone is a communication channel, not another spatial sensor.

The language model does not publish waypoints, repeated velocity commands, or
joint targets. Canonical local commands and bounded model proposals compile to
deterministic spatial behaviors under fresh camera/LiDAR checks. Manual input,
Stop, E-stop, navigation, and follow can cancel or preempt them; smoothing,
collision braking, command TTL, and the backend boundary still apply every
tick. See [Companion navigation architecture](COMPANION_NAVIGATION_ARCHITECTURE.md)
for the full navigation design.

## Model decision summary

The installed and evaluated language-model decision is maintained in [Voice
intelligence and model design](VOICE_AI_MODELS.md). In short: Gemma 4 remains
the admitted local/legacy conversation and shared PlanIR backbone; the normal
launcher uses hosted Realtime for interaction while retaining local semantic
admission. Installed Ministral 8B challengers were not promoted; Qwen is a
research candidate, not an installed or evaluated runtime profile. Model
quality does not remove the deterministic router, schema validation, task
executive, or motor-safety boundary.

## Local runbook

The current host has whisper weights and a prebuilt whisper server; that service
was stopped in the 2026-08-22 recheck. Piper's binary, voice and metadata are
present, while physical capture/playback remains uncommissioned. The installation
and service scripts are:

```bash
# Inspect requirements and pinned destinations.
scripts/install_speech_services.sh --help

# Install/verify whisper.cpp and Piper under ignored repo directories.
scripts/install_speech_services.sh

# Start whisper and verify both whisper and Piper.
scripts/run_speech_services.sh
scripts/run_speech_services.sh --check

# Start the simulator/control deck after attaching input and output devices.
scripts/launch_sim.sh --llm
```

Keep `speech.mode: auto` during development so an unavailable optional service
falls back to text. Use `speech.mode: audio` only for a fail-closed integration
test that intentionally requires healthy STT and TTS roles.
