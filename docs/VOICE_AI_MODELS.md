# Voice intelligence and model design

This document explains why Parcel separates speech recognition, intelligence,
safety, and speech generation, and how the selected open models fit together.

## Design principle

A language model is useful for interpreting flexible language, conversation, and
selecting tools. It is not a real-time controller and must never publish motor
commands or arbitrary joint targets.

Parcel uses this trust boundary:

```text
microphone
  → whisper.cpp
  → transcript
  → Gemma/llama.cpp
  → structured tool call
  → deterministic SafetySupervisor
  → named pose or stop request
  → ROS controller

spoken reply
  → isolated CSM-1B service
  → WAV audio
  → speaker
```

The probabilistic components are outside the motor-control boundary. Only named,
preconfigured actions can cross it.

## Why Gemma

Gemma provides useful small open-weight models that can run locally. There are
two sensible deployments:

1. **FunctionGemma 270M** for low-latency command routing on constrained edge
   hardware.
2. **Gemma 3 4B** for better conversation and multi-step interpretation on a
   companion GPU or workstation.

Start with one quantized Gemma 3 4B model in `llama.cpp`. If latency or power is
too high, use FunctionGemma for ordinary robot commands and reserve the larger
model for questions. The application talks to the OpenAI-compatible
`/v1/chat/completions` endpoint, but does not depend on an OpenAI service.

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

- [FunctionGemma model overview](https://ai.google.dev/gemma/docs/functiongemma)
- [Gemma 3 overview](https://deepmind.google/models/gemma/gemma-3/)

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
Do not retain raw microphone audio by default.

Official reference:

- [whisper.cpp](https://github.com/ggml-org/whisper.cpp)

## Why Sesame CSM-1B

CSM-1B generates conversational speech from text and optional voice context. It
does not reason or generate response text, so Gemma and CSM have separate jobs.

The model is attractive for an expressive robot voice, but has important
operational constraints:

- it requires access approval for the gated model files;
- the checkpoint is several gigabytes;
- the official project recommends a CUDA GPU and Python 3.10;
- its PyTorch/Transformers dependencies should not share a process with ROS;
- it primarily targets English;
- generated voices must not impersonate real people without consent.

For those reasons, `services/csm_server.py` is a separate HTTP service. The ROS
application sends `{text, speaker}` and receives WAV bytes. If it fails, the
robot can continue operating and use cached/prerecorded safety phrases.

Official references:

- [Sesame CSM source](https://github.com/SesameAILabs/csm)
- [CSM-1B model card](https://huggingface.co/sesame/csm-1b)
- [Transformers CSM documentation](https://huggingface.co/docs/transformers/main/model_doc/csm)

## Runtime layout

### Parcel/ROS environment

The `.parcel` environment contains the lightweight orchestration code, MuJoCo
Python bindings, YAML support, tests, and audio adapter. On a ROS 2 Humble
machine, recreate `.parcel` using its system Python 3.10 so `rclpy` remains ABI
compatible.

### Gemma server

Build `llama.cpp`, obtain a Gemma GGUF model under its model license, and run:

```bash
llama-server \
  --model /models/gemma.gguf \
  --host 127.0.0.1 \
  --port 8080 \
  --ctx-size 8192
```

Then enable `language_model.enabled` in `robot.yaml`, or test directly with:

```bash
parcel-agent --llm --text "Could you bow and tell me when you are done?"
```

Keep the server on loopback unless authentication and network encryption are
added.

### Whisper server

After building whisper.cpp and downloading a model:

```bash
whisper-server \
  --model /models/ggml-base.en.bin \
  --host 127.0.0.1 \
  --port 8178
```

Parcel expects WAV input at `/inference`.

### CSM service

CSM deliberately needs its own Python 3.10 CUDA environment:

```bash
python3.10 -m venv .csm
source .csm/bin/activate
python -m pip install -r services/csm-requirements.txt
huggingface-cli login
python services/csm_server.py
```

This is the one exception to the `.parcel` requirement because installing a
large CUDA PyTorch stack into the ROS virtual environment risks incompatible
Python and native dependencies. The Parcel-side CSM client remains in
`.parcel`.

Health check:

```bash
curl http://127.0.0.1:8090/health
```

## Safety behavior

`stop`, `stop now`, and `emergency stop` bypass Gemma entirely. A stop engages
the in-process safety latch and publishes `/parcel/stop_request`.

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
| First Gemma decision | under 800 ms |
| Safety validation | under 10 ms |
| First generated speech | under 1.5 seconds |
| Emergency-stop recognition | immediate deterministic path |

Warm the models at startup and cache common phrases such as “Stopping” and
“Battery low.” Optimize only after collecting latency measurements on the
actual companion computer.
