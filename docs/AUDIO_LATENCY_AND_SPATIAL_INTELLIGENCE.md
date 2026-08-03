# Bluetooth audio, latency, and local spatial intelligence

## Desktop Bluetooth/audio audit

The August 2026 read-only device audit found:

- a powered, unblocked MediaTek USB Bluetooth 5.2 controller (`hci0`);
- BlueZ 5.85, PipeWire, PipeWire Pulse, and WirePlumber running;
- Bluetooth audio codec support installed, including AAC/SBC and HFP codecs;
- headset, hands-free, audio-source, and audio-sink roles advertised; and
- `pw-record`, `pw-play`, and PipeWire's automatic headset-profile switching
  available.

No Bluetooth device was paired or connected during the audit. PipeWire therefore
reported no source and only Dummy Output, and Parcel correctly selected streaming
text mode. `AudioDeviceStatus` now distinguishes controller availability,
controller power, device connection, duplex readiness, and the likely transport
without storing a headset address. A background monitor refreshes this status
every ten seconds, outside the real-time control loop.

AirPods or another Bluetooth headset can be used after pairing in the desktop's
Bluetooth settings. A2DP gives high-quality playback but normally no headset
microphone. Opening the microphone makes WirePlumber switch to HFP/HSP duplex,
which supplies input and output at lower/mono call quality. This is expected
Bluetooth behavior; WirePlumber documents the A2DP and headset profiles and its
automatic switching hooks in its [Bluetooth configuration](https://pipewire.pages.freedesktop.org/wireplumber/daemon/configuration/bluetooth.html)
and [release documentation](https://pipewire.pages.freedesktop.org/wireplumber/resources/releases.html).

For the best spoken reply quality, prefer A2DP AirPods output plus a separate USB
or robot microphone. For one-device convenience, use the AirPods HFP microphone
and accept reduced playback fidelity.

`PipeWireAudioIO` now captures 16 kHz mono WAV from the current default source
and plays WAV to the current default sink, without hard-coded ALSA card numbers
or Bluetooth MAC-derived node names. It is a bounded utterance adapter, not an
acoustic echo canceller. The live browser path still accepts streaming text until
a paired headset is present and a continuous VAD/AEC capture service is enabled.

After pairing, validate without changing Parcel configuration:

```bash
bluetoothctl devices Connected
wpctl status
python - <<'PY'
from parcel_robot.audio_io import detect_audio_devices
print(detect_audio_devices())
PY
```

## Latency definitions and dashboard

Open <http://127.0.0.1:8765/latency> while the control deck is running. The page
is a separate, read-only dashboard backed by `/api/latency`; it does not add
transcripts or responses to metric labels.

The two primary metrics are:

- `UserQueryEndToFirstResponse`: final query submission to the first response
  made observable through logging or audio playback, whichever is first.
- `UserQueryEndToFirstReasoningResponse`: final query submission to the first
  streamed model output token. Deterministic and non-streaming paths use the
  completed validated reasoning result and label the provider detail accordingly.

Each bounded turn trace also contains:

- queue wait;
- reasoning duration;
- action-commit duration;
- reasoning-to-log delay;
- query-end-to-TTS-start;
- TTS time to first chunk and total synthesis time;
- query-end-to-first audio-sink handoff;
- total turn duration;
- model HTTP time, JSON validation time, token counts, and model TTFT when
  supplied by llama.cpp;
- completion, superseded, or error state; and
- the user query and final returned response.

Rolling component distributions include simulator observation RTT, perception
age, follow controller, spatial controller, navigation controller, activity
coordinator, collision gate, backend command send, motion dispatch, control-loop
work, and control-loop overrun. Every distribution reports latest, mean, p50,
p95, maximum, and sample count.

Headline p50/p95 cards include completed turns only. Superseded and failed
turns remain visible and receive separate status-stratified aggregates, so
barge-in experiments do not distort normal response latency.

The llama.cpp provider now accumulates bounded streamed JSON so model TTFT is
real while the complete JSON object still must validate before a tool can
commit. Non-thinking mode and a 256-token generation budget prevent ordinary
chat from spending tens of seconds on hidden reasoning. Conversation history is
also bounded by both message and character budgets. New partial/final input
cooperatively cancels the active llama.cpp stream, and pending finals are
compacted to the newest turn rather than growing an unbounded FIFO. TTS already
runs on an independent output worker. Model/audio health probes were moved off
the 10 Hz control loop, and trusted prompt files/profile lists are cached after
validation.

ASR endpointer and acoustic-presentation latency remain explicitly unavailable
in text mode. A first audio-sink handoff is only a software lower bound, not the
same as sound reaching a Bluetooth earpiece; exact acoustic presentation requires
PipeWire/Bluetooth presentation timestamps after a headset is connected.

## Camera/LiDAR knowledge boundary

The reasoning layer has an enforced spatial capability allowlist of `camera` and
`lidar`. Its dynamic prompt says that it may use only:

- camera-derived owner, object, and scene observations; and
- LiDAR-derived range, free-space, and collision observations.

It must not claim GPS, unseen objects, privileged simulator state, or map access.
The Google Maps provider is a `NullMapProvider` placeholder with `available:
false`; enabling it in configuration fails closed and never performs a network
request.

The MuJoCo backend still derives idealized detections from simulator truth for
repeatable development. Those values remain diagnostics/test-oracle data, not a
claim that a production detector exists. A physical backend must replace the
adapter with camera tracking, a LiDAR local costmap, and state estimation while
preserving this same observation contract. The microphone is a communication
transport, not an additional spatial perception source.

## Common-sense local motion

The language model never emits coordinates, waypoints, repeated raw velocity, or
town-scale paths. It may propose one strict semantic `run_spatial_behavior`, and
the deterministic controller compiles it under fresh camera/LiDAR checks:

```json
{"behavior":"move_steps","direction":"away_from_owner","steps":5}
```

```json
{"behavior":"orbit_owner","direction":"counterclockwise","size":"normal","revolutions":1}
```

Canonical wording is parsed before the LLM, so these work offline as well:

- `walk away from the owner 5 steps` — five 0.25 m steps, first face the owner,
  then reverse while keeping that heading;
- `take three steps backward`;
- `walk forward 2 steps`; and
- `walk in a small clockwise circle around me` — one local orbit with a radius
  selected from the bounded small/normal/wide profiles.

The hard limits are twelve steps, a 1.3–2.0 m orbit radius, one revolution, and a
120 second task timeout. The small radius includes enough owner clearance to
remain compatible with the final collision gate; configuration validation
rejects an orbit radius inside that safety envelope. Camera owner visibility is
required for owner-relative motion, a fresh observation is taken at commit time,
and the behavior cancels if the owner moves materially from the captured anchor.
Manual control, Stop, E-stop, navigation, and follow can cancel or preempt the
plan, and every control tick still passes through smoothing, LiDAR collision
braking, command TTL, and the backend safety boundary.

The simulator/backend observation now carries up to 64 bounded polar LiDAR
obstacle candidates, with simulator coordinates stripped at the IPC boundary.
The final brake selects the relevant return using the command being considered,
so a close obstacle behind the robot cannot hide a slightly farther obstacle in
front. Camera-derived person distance and bearing are checked against that same
candidate motion even when time-to-collision is unavailable on the first tick;
tangential orbit and retreat motion remain possible.

If LiDAR braking or another obstruction prevents any translational or rotational
progress for twenty seconds, the plan fails as `spatial_stalled` instead of
pushing indefinitely or waiting for the full task timeout.

## Conversational model recommendation

The installed Gemma 4 26B-A4B Q4 remains the tested rollback model. The best next
single-model A/B candidate is **Qwen3.6-35B-A3B Q4_K_M**: the official model is a
35B-total/3B-active multimodal MoE with a 256K context, tool use, switchable
thinking, and Apache-2.0 licensing. Its 20.4 GB llama.cpp Q4_K_M conversion fits
comfortably in this workstation's system RAM. See the [official Qwen model card](https://huggingface.co/Qwen/Qwen3.6-35B-A3B)
and [llama.cpp GGUF conversion](https://huggingface.co/ggml-org/Qwen3.6-35B-A3B-GGUF).

Run the reasoner on CPU while Fish S2 occupies the GPU. Use non-thinking mode for
ordinary conversation and canonical commands; reserve thinking for ambiguous
planning. Keep strict grammar/schema validation and the deterministic spatial
compiler regardless of model quality.

For an optional low-latency conversational front end, **Ministral 3 8B Instruct
Q4_K_M** is an Apache-2.0, instruction/chat-oriented edge model with official
GGUF support. It can produce a short noncommittal acknowledgement while the
larger planner works, but it must never promise an action before the coordinator
accepts it. See the [official model card](https://huggingface.co/mistralai/Ministral-3-8B-Instruct-2512)
and [official GGUF repository](https://huggingface.co/mistralai/Ministral-3-8B-Instruct-2512-GGUF).

Kimi K2.5 remains impractical on this single workstation because of its one
trillion total parameters. The model swap alone is not the intelligence system:
conversation memory, compact current context, semantic tools, deterministic
trajectory compilation, and safety revalidation are what turn better language
understanding into reliable robot behavior.
