# Voice-enabled robot dog development stack

This is the implemented development profile for Parcel on the current desktop.
It keeps probabilistic AI outside the final motor-safety boundary and makes the
simulator replaceable when the project moves from local development to richer
urban training or a physical Go2.

Read [CURRENT_STATUS.md](CURRENT_STATUS.md) before setup: it records which
pieces are merely implemented, which are wired, and which are actually usable
on this desktop. [DESIGN_DECISIONS.md](DESIGN_DECISIONS.md) explains the
advantages and limitations behind the split below.

## Architecture

```text
browser text  and/or  MicrophoneVoiceLoop (VAD → STT)
              |
              v
       DuplexVoiceSession + endpointing
       | partial: interrupt only
       | final transcript
       v
 conversation Gemma / optional planner ----- reply text ---> Piper / Fish S2
              |                                    |
              v                                    v
  allowlist + limits + E-stop              SentenceChunkedSynthesizer
              |                                    |
              v                                    v
 follow / grid_v1 nav / spatial / manual      SpeakerSink (barge-in)
              |                                    |
              |                         ProsodyTap → expression overlay
              |
              v
 priority arbiter + TTL + proximity brake
              |
              v
  ControlManager → SimulatorBackend (MuJoCo) / Unitree Sport
```

See [REDESIGN_2026_ARCHITECTURE.md](REDESIGN_2026_ARCHITECTURE.md) for the
speech-stack wiring (`build_speech_stack`, VAD, echo-guard barge-in).

Every velocity command has a short lease. Manual control has priority over
voice, owner-follow, and autonomous navigation; the persistent emergency-stop
latch dominates all of them. A simulator or client failure therefore decays to
zero velocity. Telemetry loss also blocks translation. These guarantees apply
to commands entering through `RobotRuntime`; viewer hotkeys and direct debug
clients do not pass through its arbiter, although the simulator independently
enforces command bounds, a watchdog, collision stop, and a transport E-stop
latch. Pose and trajectory requests also stop long-running behaviors.

The local MuJoCo backend now provides:

- Go2 pose, trajectory, and scripted gait execution;
- timestamped robot/owner telemetry over a versioned Unix-socket protocol;
- a movable owner target, owner visibility/confidence, obstacle range/bearing,
  and collision status;
- persistent `grid_v1` point navigation over an occlusion-true raycast scan,
  with an explicit missing-scan fallback and runtime-wide reactive safety veto;
- owner-follow states for acquire, follow, hold, occlusion, loss, stale input,
  and blocked clearance;
- a final collision brake shared by manual, voice, follow, and navigation
  commands; and
- a simulator-side motion watchdog independent of the web application; and
- a subordinate 50 Hz expression channel: idle body offsets actuate in MuJoCo,
  while Go2 head/gaze and speech-accent nods are state/metrics only because the
  embodiment has no neck.

The simulator's base is still translated kinematically, semantic tracks derive
from scene metadata rather than pixels, and direct viewer/debug commands bypass
the runtime-wide arbiter. These are development affordances, not physical
quadruped or perception evidence.

The `SimulatorBackend` protocol is the seam for a later SimWorld, Isaac Sim, or
ROS 2 implementation. MuJoCo remains the best first environment here because
it already has the official Unitree model, fast leg/joint physics, minimal GPU
contention, and a short edit-test loop. SimWorld is attractive for later
large-scale visual/social navigation, but it is still under active development
and is not the right dependency for the first reliable quadruped-control slice.

## Installed local models

| Role | Selection | Local status | Resource profile |
| --- | --- | --- | --- |
| Conversation + shared PlanIR default | Gemma 4 26B-A4B IT QAT Q4 GGUF | Installed under `models/gemma-4-26b-a4b/`; served on port 8080 when launched | 14.4 GB file; CPU and admitted CUDA profiles |
| Optional planning specialist | Same provider contract | Supported by code; intentionally absent from canonical config after challenger regressions | Separate endpoint/resource budget if enabled |
| Speech synthesis default | Piper | **Not installed** at configured binary/voice/JSON paths | CPU, onboard-friendly once installed |
| Speech synthesis opt-in | Fish Audio S2 Pro | Isolated environment/weights present; server off by default | GPU-heavy; model license must be reviewed |
| Speech recognition | whisper.cpp `base.en` | Binary/model installed; server off by default | 142 MB; CPU profile |
| Voice activity / endpointing | `EnergyVad`; optional Silero + Smart Turn seam | Energy is effective; ONNX Runtime/weights absent | In process, CPU target |

Gemma 4 26B-A4B is the installed, tested baseline. Qwen3.6-35B-A3B Q4_K_M is
the recommended next A/B candidate for stronger conversation and semantic
planning; it should also run from system RAM so Fish S2 can retain the RTX 5000
Ada. Kimi K2.5 is not a sensible local target: its one-trillion-parameter
checkpoint is meant for multi-GPU serving. Exact tradeoffs are in [Audio,
latency, and spatial intelligence](AUDIO_LATENCY_AND_SPATIAL_INTELLIGENCE.md).

Piper is the intended onboard TTS default (CPU), but is absent on this host.
Fish S2 Pro is
an opt-in docked/GPU mode with an official streaming server and the Fish Audio
Research License (research/non-commercial by default). The Fish checkout uses
its own Python 3.12 + CUDA uv environment so Torch cannot destabilize Parcel's
Python 3.14 `.parcel` venv.

## Audio boundary and full duplex

Audio codec tokens are useful *inside* Fish S2: its RVQ codec has ten codebooks
that preserve speech detail. They are not appropriate instructions for a robot.
The **current** path is:

1. PortAudio capture → energy echo guard → energy or optional semantic VAD;
2. explicit turn commit → one buffered WAV → blocking whisper.cpp request;
3. finalized text only to Gemma and the deterministic safety layer;
4. reply text → the selected TTS provider (Piper in canonical config); and
5. cancellable sentence/audio chunks → `SpeakerSink`, interrupted on barge-in.

Hardware AEC, true acoustic ASR partials, and native Fish audio-chunk streaming
are targets, not properties of this path today.

`DuplexVoiceSession` implements partial/final text, stale-turn action-commit
suppression, cancellable TTS, and barge-in. The browser now sends debounced
partials and asynchronous finals to `/api/voice/text`; partial text is observable
but never executed. `FishSpeechProvider` exposes text-in/audio-out only, keeping
Fish's audio tokens inside the speech process.

`build_speech_stack` resolves the `speech:` config: whisper.cpp STT + Piper by
default, Fish S2 opt-in; `auto` degrades loudly to text mode. `MicrophoneVoiceLoop`
and `SpeakerSink` provide VAD-segmented capture and interruptible playback.
Microphone ASR currently submits one buffered WAV per committed utterance; it is
not yet token/frame-streaming ASR. Browser text partials exercise cancellation
semantics but are not evidence of acoustic streaming.

The canonical YAML now keeps device selectors, endpointing/model paths, echo
guard, and `fish_url` beneath the `speech:` section the runtime reads. Three
reserved keys (`fish_reference_id`, `fish_streaming`, and `barge_in`) are still
not consumed as switches; see [CURRENT_STATUS.md](CURRENT_STATUS.md) before
changing audio behavior.

The desktop has ALSA capture hardware plus a powered Bluetooth controller. No
headset is currently paired, PipeWire has no input/output endpoint, and the
native `libportaudio2` runtime required by Python `sounddevice` is absent.
Parcel therefore starts in **streaming text mode**. A USB array or headset must
be selected as both an input and an output-capable route; production duplex
audio also needs acoustic echo cancellation. For the XVF3800, the speaker must
use the array's own playback/DAC path so its AEC receives the reference signal.

## Run it

The standard stack starts the CPU reasoner, MuJoCo, and the browser control deck:

```bash
cd /home/jaewoo-jang/Desktop/Projects/Parcel
./scripts/launch_stack.sh
```

Open <http://127.0.0.1:8765> if the browser does not open automatically. The
panel supports hold-to-drive controls, keyboard dead-man control, owner movement,
follow/stay/stop/E-stop, telemetry, and natural-language text commands. Useful
commands include `follow me`, `stay`, `navigate to the crosswalk`, `walk away
from the owner 5 steps`, `walk in a circle around me`, `sit`, and `stop`. Open
`/latency` for the separate response/component latency dashboard.

Optional services:

```bash
# ASR service (useful after PortAudio and a microphone endpoint are available)
./scripts/launch_stack.sh --whisper

# Start Fish S2 Pro only (review its license; reserves most of the GPU).
# This does NOT select it; use an experimental config with
# speech.tts_provider: fish_s2.
./scripts/launch_stack.sh --fish

# Deterministic command parser, without Gemma
./scripts/launch_stack.sh --no-reasoner
```

Services can also be launched independently. Each long-running launcher below
needs its own terminal; do not paste them as one sequential startup script:

```bash
# terminal 1
./scripts/launch_reasoner.sh

# terminal 2 (optional)
./scripts/launch_whisper.sh

# terminal 3 (optional, and requires a Fish-selected runtime config)
./scripts/launch_fish_speech.sh

# final terminal
./scripts/launch_sim.sh --llm
```

## Development checks

```bash
source .parcel/bin/activate
.parcel/bin/python -m pytest -q
.parcel/bin/python -m ruff check .

python - <<'PY'
from parcel_robot.audio_io import detect_audio_devices
print(detect_audio_devices())
PY
```

Model downloads, third-party environments, and model weights are intentionally
ignored by Git. The tracked launch scripts and configuration make their expected
locations explicit.

Use `./scripts/run_speech_services.sh --check` for a non-mutating speech
readiness probe. It currently fails until whisper is running and Piper's binary,
voice, and metadata are installed.

## What is not production-ready

The current MuJoCo camera/LiDAR path includes an occlusion-true raycast scan
feeding `grid_v1`, but semantic detections derive from simulator geometry;
this is not yet a physical image/perception stack. Before physical deployment, add
authenticated enrollment and owner re-identification, real camera/LiDAR
localization, hardware AEC, a hardware emergency stop, fall recovery
validation, geofencing, and a separately verified Unitree controller. Never
connect the LLM directly to joint or torque commands.

Multi-step PlanIR has deterministic lifecycle/success checks, but the authored
pose/trajectory catalog is not a physically validated, transition-aware
choreography system. Conversation emotes are bounded and subordinate; their
intensity and beat timing have only simulator/test evidence. CityWalker/NaVILA
YAML entries and MetaUrban setup remain research scaffolding until vendor
inference and a real step adapter exist.

## Primary references

- [Google Gemma 4 26B-A4B QAT GGUF](https://huggingface.co/google/gemma-4-26B-A4B-it-qat-q4_0-gguf)
- [Kimi K2.5 model card](https://huggingface.co/moonshotai/Kimi-K2.5)
- [Fish Audio S2 Pro model card and license](https://huggingface.co/fishaudio/s2-pro)
- [Fish Speech installation guide](https://speech.fish.audio/install/)
- [whisper.cpp](https://github.com/ggml-org/whisper.cpp)
- [whisper.cpp Silero VAD weights](https://huggingface.co/ggml-org/whisper-vad)
- [Unitree MuJoCo](https://github.com/unitreerobotics/unitree_mujoco)
- [SimWorld documentation](https://simworld.readthedocs.io/en/latest/)
