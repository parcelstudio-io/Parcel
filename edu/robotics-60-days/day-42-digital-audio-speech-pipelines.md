# Day 42: Digital Audio and Speech Pipelines

## Mental model

Speech on a robot is a *sampled control-adjacent pipeline*, not a chat API with a microphone. Sound pressure becomes integers at a sample rate; frames become voice-activity decisions; a completed utterance becomes a transcript; a reply becomes PCM again. Every stage adds latency, failure modes, and a chance to confuse *hearing yourself* with *hearing the owner*.

Unlike a cloud voice assistant, the robot carries its own speaker inches from its own microphones. That geometry makes echo, motor noise, and wind as important as model quality. Debugging “the LLM was slow” without plotting VAD hangover and TTS buffer time is like blaming SQL when DNS is down.

```text
pressure → ADC → PCM frames → VAD/endpoint → ASR → text brain → TTS → DAC → air
```

Parcel’s production default is an engineered cascade with a text reasoning boundary (`docs/VOICE_AI_MODELS.md`). That keeps ASR, reasoning, and TTS replaceable—and keeps codec tokens out of the action vocabulary. Partial hypotheses may update UI or trigger barge-in cancellation, but only **final** text crosses into `VoiceAgent`.

## Software-engineering analogy

Treat the mic path like a request pipeline with backpressure and idempotency keys. Frames are packets. VAD is the load balancer deciding when a “request” (utterance) is complete. ASR is an upstream dependency that returns a body you must not execute until it is final—Whisper on the mic path is utterance-level, not streaming token ASR. TTS is a streaming response writer that can be cancelled mid-flight; `SentenceChunkedSynthesizer` makes cancellation sentence-granular. Bluetooth profile switches are like renegotiating TLS mid-connection: the duplex quality changes underneath you without any Python exception.

**Tradeoff:** energy VAD is cheap and deterministic; neural VAD/turn detectors (Silero, smart-turn ONNX paths) can reduce false endpoints on noisy sidewalks but add deployment weight. Parcel wires optional paths while keeping `EnergyVad` as the dependency-free default.

## Light equations (audio sampling)

```text
Nyquist: f_max < fs / 2
frame_duration = N_samples / fs
# Parcel mic path (docs): 16 kHz mono int16, ~30 ms energy frames
# hangover ≈ 12 frames ≈ 360 ms of silence before commit (EnergyVad default)
```

Latency you feel is the *sum* of hangover, ASR, model TTFT, first-sentence TTS, and speaker buffering—not any single mean. `docs/AUDIO_LATENCY_AND_SPATIAL_INTELLIGENCE.md` treats spatial audio and observability as part of the same story: if you cannot timestamp when text became final, you cannot attribute motion lag to the right stage.

## ASCII diagram

```text
  Mic (PortAudio / sounddevice)
       |  16 kHz mono int16
       v
  echo-energy guard  (while robot speaking; not true AEC)
       |
       v
  EnergyVad  or  Silero+Smart Turn (wired, optional ONNX)
       |
       v
  complete WAV buffer
       |
       v
  WhisperCppProvider  -->  /inference  -->  final text
       |
       v
  DuplexVoiceSession.submit_text(is_final=True)
       |
       v
  VoiceAgent  -->  reply text
       |
       v
  SentenceChunkedSynthesizer → Piper / Fish → SpeakerSink
```

## Map to Parcel / Go2

Concrete behavior from `docs/AUDIO_LATENCY_AND_SPATIAL_INTELLIGENCE.md` and voice modules:

- **`audio_io.detect_audio_devices()`** — advisory health (`AudioDeviceStatus`); PipeWire/Bluetooth capability ≠ connected usable endpoint. Live capture still uses PortAudio via `sounddevice`; `PipeWireAudioIO` / `AlsaAudioIO` are standalone bounded-utterance adapters.
- **`EnergyVad`** in `audio/voice_loop.py` — adaptive noise floor, hangover smoothing. Energy ≠ speech semantics; machinery can look like voice.
- **`MicrophoneVoiceLoop`** — buffers a complete utterance, then blocking whisper.cpp inference. **No ASR partials** from the mic path today; browser partials can interrupt but never execute.
- **`WhisperCppProvider`** — utterance-level STT (`base.en` prototype). Server-side whisper VAD trim ≠ Parcel’s live endpoint decision.
- **TTS:** Piper is the intended CPU default; Fish S2 is the expressive docked option. `FishSpeechProvider` keeps RVQ/audio tokens inside the service (text in / audio bytes out). Runtime wraps synthesizers in `SentenceChunkedSynthesizer`; `strip_emote_tags` in `providers.py` splits spoken text from `[emote:…]` markers before synthesis.
- **Bluetooth:** A2DP playback vs HFP/HSP duplex is normal profile behavior—good headphones ≠ good robot AEC reference.

On Go2 deployments, treat speaker placement and array reference paths as commissioning items, not afterthoughts once navigation works.

**Codebase anchors (capture → text):**

- `audio/devices.py` → `detect_audio_devices`, `AudioDeviceStatus`.
- `audio/voice_loop.py` → `EnergyVad`, `MicrophoneVoiceLoop` (`echo_guard_scale`, `echo_guard_suppressions`), `SpeakerSink`.
- `providers.py` → `WhisperCppProvider`, `SentenceChunkedSynthesizer`, `strip_emote_tags`.
- `voice/pipeline.py` → `DuplexVoiceSession.submit_text` (final-only into agent).
- `runtime.py` → speech stack wiring, `echo_guard_scale` from speech config, periodic `detect_audio_devices` refresh.
- `docs/AUDIO_LATENCY_AND_SPATIAL_INTELLIGENCE.md`, `docs/VOICE_AI_MODELS.md` → cascade rationale and latency budgets.

## Failure story

A demo used a Bluetooth speaker for “richer” TTS while the XVF3800-class array was supposed to cancel echo. Without the array’s amplifier/DAC reference path, hardware AEC never saw the true playback signal. The energy echo guard raised thresholds until the owner’s quiet barge-in was suppressed; the dog kept talking over them. The stack looked “duplex-ready” in software logs; acoustically it was half-duplex with a broken reference. Fix: treat speaker topology as part of the control contract, not as a cosmetic peripheral choice—then measure barge-in success with the same rigor as collision stops.

## Retrieval questions

1. Why does a 360 ms VAD hangover appear in *every* turn’s latency budget?
2. What Parcel boundary prevents Fish codec tokens from becoming action tokens?
3. (Week-back) From Day 39: name two latency metrics you would plot for a voice turn beyond model TTFT.

## Optional 10-minute exercise

Run the advisory check from the audio doc (or read `detect_audio_devices` in `src/parcel_robot/audio/devices.py`). Note whether the host reports connected input/output. Then skim `EnergyVad.__init__` defaults and compute hangover seconds at 30 ms/frame.
