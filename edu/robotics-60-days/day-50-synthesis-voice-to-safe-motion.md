# Day 50: Synthesis — Voice to Safe Motion

## Mental model

A companion turn is one story crossing many authority domains. Trace it without collapsing layers: audio → text → route → (chat or PlanIR) → validation → arbitration → navigation/follow → bounded velocity → Sport → speech/gesture feedback → metrics/recovery. Intelligence may be probabilistic; safety and actuation stay skeptical and typed.

```text
hear → understand → propose → admit → move → verify → speak
untrusted ---------->| boundary |---- trusted physical effects
```

This day binds Module 5 into one rehearsal you can re-run on any new feature. When debugging, name the hop that lied—ASR, router, validator, executive, follow controller, reactive safety, or actuator—before reaching for a bigger model.

**Design invariant:** only hops after validation + arbiter leases may translate intent into body motion. Everything upstream is advisory input with epochs, TTLs, and deny-by-default schemas.

## Software-engineering analogy

End-to-end request tracing in a payments + logistics platform: edge TLS, BFF, workflow engine, fraud rules, warehouse robot PLC. Each hop has logs, deadlines, and a deny-by-default ACL. Incidents need a span ID equivalent—here, duplex epoch + plan revision + command sequence—not “the AI felt confident.”

## ASCII diagram

```text
  [mic frames] VAD/turn → WAV → WhisperCppProvider
                      | final text
                      v
            DuplexVoiceSession (epoch, barge-in)
                      |
                      v
            DeterministicIntentRouter → IntentFrame
               /           |            \
        direct_skill  conversation   deliberative_plan
               \           |            /
                VoiceAgent + schemas + CommitGuard
                      |
                      v
         PlanIR → TaskExecutive → SemanticTaskRuntimeAdapter
                      |
                      v
         FollowOwnerController / nav / Gesture
                      |
                      v
         SafetySupervisor + ReactiveSafetyPolicy + clamps
                      |
                      v
              Unitree Sport / sim backend
                      |
                      v
         TTS (SpeechChunk) + DuplexCoordinator (FillerPolicy / FrameInterleaver)
                      |
                      v
              /latency + logs/duplex/*.jsonl + recovery
```

## Map to Parcel / Go2 — one interaction

Worked example: *“Follow me—actually, circle once and sit.”*

1. **Audio:** voice loop captures utterance; ASR finalizes text (browser text can substitute in dev).
2. **Duplex:** If the dog was mid-filler from a prior pause, barge-in bumps `speech_epoch`, cancels TTS, drops stale D0 frames (`DuplexCoordinator.set_epoch`).
3. **Router:** Correction + physical compound cues → `deliberative_plan` (`DeterministicIntentRouter`), not a half-applied `parse_follow_intent` alone.
4. **Planner:** `PlanIR` steps might cancel prior follow, `OrbitOwner`, `Gesture` sit—each name must appear in `SemanticTaskRuntimeAdapter.SUPPORTED_SKILLS`, ≤12 steps, interrupt policy set.
5. **Admission:** Fresh owner track + keepout + free space; reject microscopic radii; `AskClarification` if binding is ambiguous (`brain/validator.py`).
6. **Executive:** Preempt prior follow via `TaskExecutive`; run orbit with adapter-verified progress; sit only after predicate—not after optimistic TTS.
7. **Control:** Brain ~10 Hz intents; Sport balances. LLM silent at control rate.
8. **Personality:** Brief confirmations from active `prompts/personalities/*.yaml`; optional emote after gates (`strip_emote_tags` / `SpeechChunk`); never raises speed limits.
9. **Metrics:** Stage latencies on `/latency`; duplex JSONL for epoch/filler/barge_in; classify failures as ASR, route, plan, admit, execute, or acoustic.

Native speech-to-speech or model-produced ACT frames remain research/prototype behind duplex interfaces until typed reliability matches this path (`docs/VOICE_AI_MODELS.md`, duplex design notes). **`DuplexFrameConsumer` shadow-only** by default so narration does not double-drive motion.

**Codebase anchors (full-path touchpoints):**

- `audio/voice_loop.py` / `voice/pipeline.py` — capture, ASR, session wiring into agent.
- `brain/router.py` — deterministic routing; complements `parse_follow_intent` for follow-only utterances.
- `voice/agent.py` → `VoiceAgent`, **`CommitGuard`**, `handle_text_guarded`, `plan_publisher`.
- `brain/executive.py` → `TaskExecutive`; `brain/runtime_adapter.py` → `SUPPORTED_SKILLS` / `SYSTEM_SKILLS` (`SearchOwner`).
- `navigation/follow.py` → `FollowOwnerController`, `FollowConfig`; `navigation/spatial.py` → `parse_follow_intent`.
- `navigation/reactive_safety.py` → `ReactiveSafetyPolicy`, `apply_reactive_safety`.
- `safety.py` → `SafetySupervisor`, E-stop engagement paths with arbiter.
- `duplex/coordinator.py` → `DuplexCoordinator`, **`FillerPolicy`**, **`FrameInterleaver`**; `duplex/frames.py` epoch-stale frame drop.
- `core/activities.py` → `ActivityCoordinator` for queued social gestures parallel to executive skills.
- `providers.py` → `LlamaCppProvider`, `strip_emote_tags`, `SpeechChunk`.
- `docs/VOICE_AI_MODELS.md` — model/admission checklist at the intelligence boundary.

**First motor touch:** typically after validated skill dispatch and arbiter lease—never from raw LLM text or shadow duplex ACT decode alone.

## Failure story (whole-path)

Outdoor demo: ASR heard “circle the owner” as “hurdle the owner.” Router sent deliberative planning. PlanIR validated skill names but bound `OrbitOwner` with a default radius that intersected a bench the LiDAR saw only after motion started. Collision gate slowed too late in narrative terms; the dog brushed the bench, then sat because the step timeout marked orbit “done enough.” Personality cheerfully said “All done!” Voice-to-motion “worked” as a pipeline and failed as a product. Postmortem anchors: ASR confidence/clarify, feasibility against inflated obstacles, adapter completion predicates, and speech-after-verify. No single model upgrade would have fixed all four.

## Retrieval questions

1. Walk the example utterance through five Parcel components and name the authority each one has.
2. Where in the path should an emergency “stop” short-circuit, and which components must still run?
3. (Week-back) From Day 41 and Day 46: restate the untrusted-planner rule and one closed-loop completion rule in one sentence each.

## Optional 10-minute exercise

Pick the module path below and draw an 8-box sequence diagram on paper for the example utterance: `voice/pipeline.py` → `brain/router.py` → `voice/agent.py` → `brain/executive.py` → `navigation/follow.py` → `safety.py` → `duplex/coordinator.py` → `docs/VOICE_AI_MODELS.md` (boundary checklist). Mark the first box that may touch motors and one box that must remain LLM-free at 10 Hz.
