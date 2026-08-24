# Day 43: Full-Duplex Conversation and Barge-In

## Mental model

Full duplex means the system can *listen while speaking* and treat the owner’s interruption as a first-class event—not as noise to ignore until TTS finishes. Barge-in is the policy layer on top: cancel outdated speech and reasoning, bump an epoch so queued audio and prosody die, and never commit actions from a superseded turn.

Half-duplex UX trains owners to shout over the robot; full-duplex UX trains the robot to yield. Both require engineering discipline. Without acoustic echo cancellation (AEC), the robot’s own voice re-enters the mic and either false-triggers endpointing or forces an energy guard that mutes the owner—the worst of both worlds.

```text
half-duplex:  listen XOR speak
full-duplex:  listen AND speak, with echo control + turn policy
barge-in:     new input → cancel epoch N → only epoch N+1 may commit
```

Application-level cancellation is necessary but not sufficient. Parcel implements cooperative cancel on llama.cpp streams, speaker flush, and `CommitGuard` fencing; acoustic reference for playback remains the long-lead hardware fix documented alongside XVF3800-class arrays.

## Software-engineering analogy

Barge-in is cooperative cancellation plus generation fencing—like aborting an HTTP handler when the client disconnects, invalidating in-flight cache writes with an epoch token, and dropping responses whose `request_id` is stale. Fillers are synthetic 100 Continue messages: they buy perceived responsiveness without granting business (motion) authority.

Systems such as [Moshi](https://github.com/kyutai-labs/moshi) show native full-duplex audio modeling. Parcel studies that architecture while keeping D0 framing as *observation* of existing decisions, not a new motor authority path. The lesson for senior engineers: dual-stream products need two scorecards—acoustic interrupt success *and* stale-action prevention—not one demo video.

**Tradeoff:** aggressive epoch bumps feel responsive but can discard nearly-finished safe replies; conservative bumps leave the owner talking over outdated TTS. Tune with recorded sessions, not lab quiet rooms.

## ASCII diagram

```text
  owner speech during TTS
           |
           v
  DuplexVoiceSession.submit_text / mic energy
           |
           +--> speech_epoch += 1
           +--> cancel llama.cpp stream (cooperative)
           +--> flush SpeakerSink / interrupt playback
           +--> invalidate pre-commit actions (CommitGuard)
           |
           v
  DuplexCoordinator.set_epoch(epoch)
           |
           v
  FrameInterleaver drops stale TEXT/ACT (epoch mismatch)
           |
           v
  only newest final transcript → VoiceAgent
```

## Map to Parcel / Go2

From `src/parcel_robot/voice/pipeline.py`, `duplex/`, and `docs/DUPLEX_DUAL_STREAM_DESIGN.md`:

- **`DuplexVoiceSession`** — text-first coordinator. Partials interrupt and update `on_partial` but **never** call `VoiceAgent.handle_text`. Finals enqueue; only the newest final wins. `speech_epoch` increments on new input; active output’s `cancel_event` is set.
- **`CommitGuard` path in `VoiceAgent.handle_text_guarded`** — model work may finish after cancellation; `_commit` must fail closed if the turn is stale (`runtime.py` wraps guarded calls from the voice session).
- **`DuplexCoordinator`** — D0 producer clock at nominal 10 Hz: `FrameInterleaver` emits `DuplexFrame {t, epoch, text, act}`. TEXT mirrors sentence text entering TTS; ACT mirrors post-gate twist / skills / emotes / fillers. **`DuplexFrameConsumer` is shadow-only** by default—decode does not drive the robot twice.
- **`FillerPolicy`** — predictive fillers for deliberative/info-tool paths; ~700 ms watchdog for other delays; ~2 s response ceiling is a logical marker, not an acoustic SLA.
- **Echo reality:** software has an energy echo guard (`echo_guard_scale` on `MicrophoneVoiceLoop`), not AEC. Browser-tested cancellation ≠ sidewalk-ready full duplex under motor noise.

Industry aside: many “duplex” demos are turn-taking with fast TTFT. True barge-in under motor noise and speaker bleed is a hardware + policy problem; software cancel without mic truth is theatre. Commissioning should include a scripted “interrupt during filler + interrupt during PlanIR” matrix, logged with epoch numbers and whether `handle_text_guarded` refused commit.

**Codebase anchors (duplex + fencing):**

- `voice/pipeline.py` → `DuplexVoiceSession`, `submit_text`, guarded agent dispatch.
- `voice/agent.py` → `CommitGuard`, `handle_text_guarded`, `_commit`.
- `duplex/coordinator.py` → `DuplexCoordinator`, `set_epoch`.
- `duplex/frames.py` → `FrameInterleaver`, `DuplexFrame`, `TEXT_SILENCE`, `ACT_IDLE`.
- `duplex/__init__.py` → public duplex exports wired from `runtime.py` (`DuplexConfig`, coordinator construction).
- `audio/voice_loop.py` → `SpeakerSink`, echo guard counters during playback.
- `docs/DUPLEX_DUAL_STREAM_DESIGN.md` → shadow ACT stream, epoch semantics.

## Failure story

During a planning pause the filler said “one second—” while PlanIR generation continued. The owner said “actually stop.” Energy during playback looked like residual TTS; the echo guard attenuated the mic, ASR never finalized, and the plan committed an `OrbitOwner` step. Logs showed a beautiful duplex JSONL stream with `barge_in: false`. The failure was acoustic policy, not missing cancel code. Fix: emergency lexicon must remain reachable on a path that does not wait for clean VAD under self-speech—and AEC must precede claiming production duplex. Cross-check Day 41: stop routes must not depend on a finished Whisper buffer when the owner is competing with the robot’s own voice.

## Retrieval questions

1. What is the difference between interrupting TTS and preventing a stale `next_action` from committing?
2. Why is D0 ACT framing “shadow” rather than a second controller?
3. (Week-back) From Day 41: why must Moshi-like audio tokens still not become PlanIR authority in Parcel?

## Optional 10-minute exercise

Open `DuplexVoiceSession.submit_text` in `src/parcel_robot/voice/pipeline.py` and trace what happens when `is_final=False` versus `True`. Then read `DuplexCoordinator.set_epoch` in `duplex/coordinator.py` and note how stale frames are rejected.
