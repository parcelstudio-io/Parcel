# Day 41: The LLM as Untrusted Semantic Planner

## Mental model

A language model is a high-bandwidth *semantic proposal engine*, not a controller. It excels at turning messy human language into candidate meaning—goals, corrections, social tone, and multi-step stories. It is structurally unsuited to be the sole authority for physical motion: weights drift, context windows truncate, and fluent text carries no proof of feasibility, freshness, or safety margins.

Parcel’s central design principle (from `edu/INTRO.md`) states this bluntly: treat the LLM as an untrusted planner whose output must cross a strongly typed, validated boundary before it can affect the world. That boundary is not paranoia; it is how you keep replay, audits, and incident postmortems honest when something goes wrong on a sidewalk.

```text
trusted:   sensors, clocks, safety latch, typed contracts, admitted skills
untrusted: model tokens, paraphrases, affect guesses, “common sense” defaults
boundary:  schema parse → semantic validation → task admission → control
```

Fluency is not competence. A confident paragraph that says “I’ll sprint left around the crowd” is still a string until deterministic code admits a skill, checks fresh scene state, and issues a bounded velocity intent. The model never sees raw motor registers; even when it proposes `next_action`, Python re-validates against registries and strips fields the schema must not trust.

**Design tension:** richer model reasoning can improve PlanIR on compound commands, but every new output channel is another surface to validate. Parcel defaults to JSON contracts and a text cascade so operators can diff “what the model said” against “what the runtime admitted.”

## Software-engineering analogy

Think of a payment frontend that *suggests* a checkout intent versus a vault that *authorizes* a charge. The frontend may parse natural language from a support bot (“refund the last order”). It must never construct the processor wire format or hold HSM keys. The vault validates schema, rate limits, and fails closed.

Parcel’s `VoiceAgent` is the application vault entrance: transcripts enter; motor authority does not leave through the model path. `DeterministicIntentRouter` attaches routing metadata without paraphrasing—the transcript digest in `IntentFrame` is the audit anchor. Schema-constrained JSON from `LlamaCppProvider` is parsed again in Python (`from_mapping` on contracts). `SafetySupervisor.validate` and the control stack still own clamps, collision response, and E-stop regardless of conversational politeness.

Industry aside (light): robot “voice agents” in 2025–2026 demos often stream audio tokens end-to-end (speech-to-speech). Parcel keeps the text boundary so replay, schema validation, and safety gates stay inspectable—even if that costs some natural duplex latency. The trade is deliberate: inspectability and fail-closed admission beat demo fluency for a companion that shares pavement with strangers.

## ASCII diagram

```text
  transcript (final text only)
           |
           v
  DeterministicIntentRouter  -->  IntentFrame (route, speech_act, ...)
           |
     +-----+------+------------------+
     |            |                  |
 direct_skill  conversation    deliberative_plan
     |            |                  |
     |            v                  v
     |     JSON reply/tools/    PlanIR (≤12 steps)
     |     next_action          schema + skill registry
     |            |                  |
     +------+-----+--------+---------+
            v
     validation / CommitGuard / task executive
            |
            v
     typed skills → nav/arbiter → SafetySupervisor → Sport
```

## Map to Parcel / Go2

From `docs/VOICE_AI_MODELS.md` and `src/parcel_robot/voice/agent.py`:

- **Cascade, not native S2S.** Audio becomes text before action authority. Raw mic frames, Whisper features, and Fish codec tokens never become motor commands.
- **`VoiceAgent.handle_text` / `handle_text_guarded`.** Planning may run while a `CommitGuard` tracks whether the voice turn is still current; stale model results must not commit motion after barge-in.
- **Router first.** `DeterministicIntentRouter.route(..., is_final=True)` emits a versioned `IntentFrame`. Non-final ASR text routes to `clarify_or_abstain` and is never actionable. Emergency phrases (`stop`, `stop now`, …) bypass model generation via `direct_skill`.
- **Split contracts, one backbone by default.** Conversation and planner provider interfaces are independent; `planner_model` defaults to `language_model` (shared Gemma via llama.cpp). Both lanes receive the *original* transcript—not another model’s paraphrase.
- **Fail closed.** Unknown tools, poses, skills, joint values, and raw `set_velocity` from the conversation model are rejected. At most one motion-producing `next_action` is admitted per decision.

On Go2, Unitree Sport remains the actuator API behind clamps; the LLM’s job ends at typed motion intents the arbiter and reactive safety may still veto (Days 35, 20).

**Codebase anchors (untrusted planner boundary):**

- `voice/agent.py` → `VoiceAgent`, `CommitGuard`, `handle_text_guarded`, `_handle_text` (route switch to `_handle_plan` when `deliberative_plan`).
- `brain/router.py` → `DeterministicIntentRouter.route`, `ROUTER_VERSION`, emergency `_EMERGENCY_STOP` set, `clarify_or_abstain` for `is_final=False`.
- `brain/contracts.py` → `IntentFrame` (`INTENT_ROUTES`, transcript SHA-256), `PlanIR` (1..12 `PlanStep`, `requested_interrupt`).
- `providers.py` → `LlamaCppProvider` (schema JSON); comment that `SafetySupervisor` is a second validation boundary after parsing.
- `safety.py` → `SafetySupervisor.validate` on admitted tools/skills.
- `docs/VOICE_AI_MODELS.md` → engineered cascade, shared backbone default, fail-closed tool policy.

## Failure story

A team let the conversation model emit free-form “tool JSON” without a second validator. One turn returned a plausible `orbit` with `radius_m: 0.2` because the owner said “come in close.” The schema accepted a number; nothing checked keepout against follow/orbit keepouts and person-stop policy. In the simulator the dog clipped the owner mesh; on a sidewalk that would have been a social and safety failure. Fix: treat every numeric default as untrusted until feasibility code rebinds it against fresh camera/LiDAR state and admitted skill contracts—exactly the compile chain Day 45 names.

## Retrieval questions

1. Why is “the model said it would stop” insufficient as a safety argument?
2. Name three Parcel stages that sit between model JSON and Unitree Sport.
3. (Week-back) From Day 34/35: how does a task executive’s preemption relate to treating the LLM as untrusted?

## Optional 10-minute exercise

Open `src/parcel_robot/brain/router.py` and skim `DeterministicIntentRouter.route`. List the routes you see and note which rules bypass the LLM. Then open `docs/VOICE_AI_MODELS.md` §“engineered cascade” and write one sentence on why native speech-to-speech must not gain PlanIR authority yet.
