# Voice-enabled robot dog development stack

This is the implemented development profile for Parcel on the current desktop.
It keeps probabilistic AI outside the final motor-safety boundary and makes the
simulator replaceable when the project moves from local development to richer
urban training or a physical Go2.

## Architecture

```text
browser text  and/or  MicrophoneVoiceLoop (VAD → STT)
              |
              v
       DuplexVoiceSession
       | partial: interrupt only
       | final transcript
       v
  Gemma structured plan ----- reply text ---> Piper (default) / Fish S2
              |                                    |
              v                                    v
  allowlist + limits + E-stop              SentenceChunkedSynthesizer
              |                                    |
              v                                    v
 follow / grid_v1 nav / spatial / manual      SpeakerSink (barge-in)
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
- persistent point navigation with a simple reactive obstacle-turn fallback;
- owner-follow states for acquire, follow, hold, occlusion, loss, stale input,
  and blocked clearance;
- a final collision brake shared by manual, voice, follow, and navigation
  commands; and
- a simulator-side motion watchdog independent of the web application.

The `SimulatorBackend` protocol is the seam for a later SimWorld, Isaac Sim, or
ROS 2 implementation. MuJoCo remains the best first environment here because
it already has the official Unitree model, fast leg/joint physics, minimal GPU
contention, and a short edit-test loop. SimWorld is attractive for later
large-scale visual/social navigation, but it is still under active development
and is not the right dependency for the first reliable quadruped-control slice.

## Installed local models

| Role | Selection | Location / endpoint | Resource profile |
| --- | --- | --- | --- |
| Action reasoning | Gemma 4 26B-A4B IT QAT Q4 GGUF | `models/gemma-4-26b-a4b/`, port 8080 | 14.4 GB file; CPU profile |
| Speech synthesis (default) | Piper | local ONNX / configured binary | CPU, onboard-friendly |
| Speech synthesis (opt-in) | Fish Audio S2 Pro | `third_party/fish-speech/...`, port 8091 | ~11 GB weights; 24+ GB VRAM |
| Speech recognition | whisper.cpp `base.en` | `models/whisper/`, port 8178 | 142 MB; CPU profile |
| Voice activity detection | `EnergyVad` in `voice_audio.py` (Silero later) | in-process | CPU; adaptive noise floor |

Gemma 4 26B-A4B is the installed, tested baseline. Qwen3.6-35B-A3B Q4_K_M is
the recommended next A/B candidate for stronger conversation and semantic
planning; it should also run from system RAM so Fish S2 can retain the RTX 5000
Ada. Kimi K2.5 is not a sensible local target: its one-trillion-parameter
checkpoint is meant for multi-GPU serving. Exact tradeoffs are in [Audio,
latency, and spatial intelligence](AUDIO_LATENCY_AND_SPATIAL_INTELLIGENCE.md).

Piper is the onboard TTS default (low first-audio latency, CPU). Fish S2 Pro is
an opt-in docked/GPU mode with an official streaming server and the Fish Audio
Research License (research/non-commercial by default). The Fish checkout uses
its own Python 3.12 + CUDA uv environment so Torch cannot destabilize Parcel's
Python 3.14 `.parcel` venv.

## Audio boundary and full duplex

Audio codec tokens are useful *inside* Fish S2: its RVQ codec has ten codebooks
that preserve speech detail. They are not appropriate instructions for a robot.
Parcel therefore uses this boundary:

1. capture + echo cancellation + VAD;
2. streaming ASR hypotheses;
3. finalized text only to Gemma and the deterministic safety layer;
4. reply text to Fish; and
5. cancellable audio streaming, interrupted immediately on barge-in.

`DuplexVoiceSession` implements partial/final text, stale-turn action-commit
suppression, cancellable TTS, and barge-in. The browser now sends debounced
partials and asynchronous finals to `/api/voice/text`; partial text is observable
but never executed. `FishSpeechProvider` exposes text-in/audio-out only, keeping
Fish's audio tokens inside the speech process.

`build_speech_stack` resolves the `speech:` config: whisper.cpp STT + Piper by
default, Fish S2 opt-in; `auto` degrades loudly to text mode. `MicrophoneVoiceLoop`
and `SpeakerSink` exist for VAD-segmented capture and interruptible playback;
without a paired mic/speaker this desktop still starts in **streaming text
mode**. Hardware AEC is still required before reliable duplex demos.

The desktop has an ALSA Realtek ALC1220 driver plus a powered MediaTek Bluetooth
5.2 controller with BlueZ/PipeWire headset support. No headset is currently
paired, so PipeWire reports no source and only Dummy Output and Parcel starts in
**streaming text mode**. `PipeWireAudioIO` follows default nodes for a later
AirPods/USB-headset connection; `AlsaAudioIO` remains a direct fallback.
Production duplex audio also needs acoustic echo cancellation.

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
# ASR service (useful after a microphone endpoint is connected)
./scripts/launch_stack.sh --whisper

# Fish S2 Pro (review its license; reserves most of the GPU)
./scripts/launch_stack.sh --fish

# Deterministic command parser, without Gemma
./scripts/launch_stack.sh --no-reasoner
```

Services can also be launched independently:

```bash
./scripts/launch_reasoner.sh
./scripts/launch_whisper.sh
./scripts/launch_fish_speech.sh
./scripts/launch_sim.sh --llm
```

## Development checks

```bash
source .parcel/bin/activate
pytest -q
ruff check .

python - <<'PY'
from parcel_robot.audio_io import detect_audio_devices
print(detect_audio_devices())
PY
```

Model downloads, third-party environments, and model weights are intentionally
ignored by Git. The tracked launch scripts and configuration make their expected
locations explicit.

## What is not production-ready

The current MuJoCo camera/LiDAR path includes an occlusion-true raycast scan
feeding `grid_v1`, but detections can still derive from simulator geometry;
this is not yet a physical perception stack. Before physical deployment, add
authenticated enrollment and owner re-identification, real camera/LiDAR
localization, hardware AEC, a hardware emergency stop, fall recovery
validation, geofencing, and a separately verified Unitree controller. Never
connect the LLM directly to joint or torque commands.

Multi-tool model output is validated as one allowlisted plan, but there is not
yet a duration-aware action-sequence scheduler; do not use consecutive pose or
velocity tools as choreography. CityWalker/NaVILA YAML entries and MetaUrban
setup remain research scaffolding until vendor inference and a real step
adapter exist.

## Primary references

- [Google Gemma 4 26B-A4B QAT GGUF](https://huggingface.co/google/gemma-4-26B-A4B-it-qat-q4_0-gguf)
- [Kimi K2.5 model card](https://huggingface.co/moonshotai/Kimi-K2.5)
- [Fish Audio S2 Pro model card and license](https://huggingface.co/fishaudio/s2-pro)
- [Fish Speech installation guide](https://speech.fish.audio/install/)
- [whisper.cpp](https://github.com/ggml-org/whisper.cpp)
- [whisper.cpp Silero VAD weights](https://huggingface.co/ggml-org/whisper-vad)
- [Unitree MuJoCo](https://github.com/unitreerobotics/unitree_mujoco)
- [SimWorld documentation](https://simworld.readthedocs.io/en/latest/)
