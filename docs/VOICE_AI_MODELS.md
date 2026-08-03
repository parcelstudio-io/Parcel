# Voice intelligence and model design

This document explains why Parcel separates speech recognition, intelligence,
safety, and speech generation, and how the selected open models fit together.

## Design principle

A language model is useful for interpreting flexible language, conversation, and
selecting tools. It is not a real-time controller and must never publish motor
commands or arbitrary joint targets.

Parcel uses this trust boundary:

```text
microphone (future device transport; text stream is active now)
  → whisper.cpp
  → finalized transcript
  → Gemma 4 / llama.cpp
  → structured tool call
  → deterministic SafetySupervisor
  → priority arbiter + TTL + proximity brake
  → simulator or ROS controller

spoken reply
  → isolated Fish S2 Pro service
  → cancellable WAV stream
  → speaker
```

The probabilistic components are outside the motor-control boundary. Only named,
preconfigured actions can cross it.

## Why Gemma 4 26B-A4B

This workstation runs Google's official instruction-tuned **Gemma 4 26B-A4B
QAT Q4 GGUF**. It is a mixture-of-experts model with 25.2B total and about 3.8B
active parameters. That gives substantially stronger reasoning than the former
Gemma 3 4B plan while retaining responsive CPU inference. The 14.4 GB GGUF is
served from system RAM on 48 of the machine's 96 CPU cores so Fish Speech can
reserve the 32 GB GPU. The model is Apache-2.0 and supports configurable
thinking plus native function calling.

Kimi K2.5 was evaluated but rejected for this device: its one-trillion-parameter
checkpoint is designed for multi-GPU serving and is hundreds of gigabytes even
when quantized. The application talks to llama.cpp's OpenAI-compatible
`/v1/chat/completions` endpoint and does not depend on a hosted service.

Parcel gives the model a dynamically generated list of allowable pose names. It
requests exactly this response shape:

```json
{
  "reply": "Sitting down.",
  "tool_calls": [
    {"name": "run_pose", "arguments": {"name": "sit"}}
  ]
}
```

The response is parsed strictly:

- it must be JSON;
- at most four tool calls are accepted;
- tool names and arguments are validated again by `SafetySupervisor`;
- unknown poses and tools are rejected;
- joint values never come from the language model;
- an invalid response falls back to deterministic command parsing.

Gemma may still hallucinate facts. Robot manuals and operational information
should therefore be supplied through a later retrieval layer with citations,
not assumed to exist in the model.

Official references:

- [Gemma 4 26B-A4B QAT GGUF](https://huggingface.co/google/gemma-4-26B-A4B-it-qat-q4_0-gguf)
- [Kimi K2.5 model card](https://huggingface.co/moonshotai/Kimi-K2.5)

## Why whisper.cpp

`whisper.cpp` provides local Whisper inference, quantized models, CPU/GPU
backends, and an HTTP server. Parcel's `WhisperCppProvider` sends a WAV utterance
to its `/inference` endpoint. This keeps speech recognition replaceable and
avoids putting a large Python ML stack inside ROS.

Recommended initial model:

- `base.en` for a responsive English prototype;
- move to `small.en` if command recognition is not accurate enough;
- use a multilingual model only when required.

Voice activity detection should segment 16 kHz mono input before transcription.
The installed launcher enables the official Silero VAD v6.2 model by default;
set `PARCEL_WHISPER_VAD=0` only for diagnostics. Do not retain raw microphone
audio by default.

Official reference:

- [whisper.cpp](https://github.com/ggml-org/whisper.cpp)
- [whisper.cpp Silero VAD weights](https://huggingface.co/ggml-org/whisper-vad)

## Why Fish Audio S2 Pro

Fish S2 Pro provides the expressive side of the conversation while Gemma
generates reply text and action plans. It has an official streaming API,
multilingual generation, long-context/multi-speaker support, and fine prosody
control. It runs in an isolated Python 3.12 + Torch CUDA 12.9 environment and
uses most of the RTX 5000 Ada's VRAM, so it is opt-in during development.

Fish's RVQ audio tokens remain private to the speech server. Parcel sends text
and receives ordered WAV/PCM chunks; audio tokens never cross into robot action
reasoning. `DuplexVoiceSession` cancels active output on barge-in and only sends
finalized transcripts to `VoiceAgent`. Partial ASR hypotheses are never actions.

Fish S2 Pro uses the Fish Audio Research License. Research and non-commercial
use are permitted, but production/commercial use needs a separate Fish license.
Sesame CSM remains only as a legacy adapter and was not selected for this host.

Official references:

- [Fish Audio S2 Pro](https://huggingface.co/fishaudio/s2-pro)
- [Fish installation guide](https://speech.fish.audio/install/)
- [Fish Speech source](https://github.com/fishaudio/fish-speech)

## Runtime layout

### Parcel/ROS environment

The `.parcel` environment contains the lightweight orchestration code, MuJoCo
Python bindings, YAML support, tests, and audio adapter. On a ROS 2 Humble
machine, recreate `.parcel` using its system Python 3.10 so `rclpy` remains ABI
compatible.

### Gemma server

The official llama.cpp binary and Gemma GGUF are installed locally. Run:

```bash
./scripts/launch_reasoner.sh
```

Then enable `language_model.enabled` in `robot.yaml`, or test directly with:

```bash
parcel-agent --llm --text "Could you bow and tell me when you are done?"
```

Keep the server on loopback unless authentication and network encryption are
added.

### Whisper server

The official whisper.cpp server and `base.en` weights are installed:

```bash
./scripts/launch_whisper.sh
```

Parcel expects WAV input at `/inference`.

This starts the ASR service only. Browser/ALSA capture is not wired to it on the
current no-endpoint desktop.

### Fish service

Fish has a dedicated uv-managed Python 3.12 environment under its ignored
third-party checkout. Start its fp16 CUDA server with:

```bash
./scripts/launch_fish_speech.sh
```

Keeping this 187-package Torch stack outside `.parcel` avoids Python and native
dependency conflicts with MuJoCo or a future ROS environment.

This starts the TTS service only. `FishSpeechProvider` and cancellable duplex
output are implemented and tested, but speaker playback is intentionally not
constructed until an output endpoint and echo-canceling transport exist.

Health check:

```bash
python - <<'PY'
from urllib.request import urlopen
print(urlopen("http://127.0.0.1:8091/v1/health").read().decode())
PY
```

## Safety behavior

`stop`, `stop now`, and `emergency stop` bypass Gemma entirely. A stop engages
the in-process safety latch and publishes `/parcel/stop_request`.

For streamed text, a newer partial/final turn invalidates an older model turn
before its tools can commit. Multiple tools in one model response are validated
up front, but Parcel does not yet schedule pose/velocity choreography over time;
do not treat consecutive tool calls as choreography—represent timed motion as
an authored trajectory until a cancellable sequence scheduler is added.

Before controlling hardware, the downstream Unitree controller must also:

- maintain its own emergency-stop latch;
- enforce robot-specific position, velocity, torque, and temperature limits;
- reject stale commands;
- interpolate poses rather than stepping directly to targets;
- require an explicit operator action to clear an emergency stop;
- stop safely if ROS, DDS, network, or companion-computer heartbeats disappear.

The current supervisor validates intent. It is not a replacement for the
robot-specific low-level safety controller.

## Privacy and memory

`ConversationMemory` stores text roles and messages in SQLite. It does not store
raw audio. A production deployment should:

- make persistence opt-in;
- provide a command to erase stored conversations;
- encrypt sensitive data at rest;
- never store voice-reference audio without explicit consent;
- keep operational logs separate from personal conversation memory.

## Performance targets

Measure each stage independently:

| Stage | Initial target |
| --- | --- |
| End-of-speech detection | under 300 ms |
| Final transcript | under 1 second after speech ends |
| First Gemma decision (CPU profile) | measure; currently interactive, not real-time |
| Safety validation | under 10 ms |
| First generated speech | under 1.5 seconds |
| Emergency-stop recognition | immediate deterministic path |

Warm the models at startup and cache common phrases such as “Stopping” and
“Battery low.” Optimize only after collecting latency measurements on the
actual companion computer.
