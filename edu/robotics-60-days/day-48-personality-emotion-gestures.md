# Day 48: Personality, Emotion, and Embodied Gestures

## Mental model

Personality changes *how* the dog speaks and which low-priority social motions it offers. It must not change facts, safety rules, skill authority, or physics. Emotion cues are hypotheses with confidence—not overrides for navigation.

```text
personality → tone, brevity, mapped social skills
emotion     → optional affect + catalog gesture (if admitted)
never       → new keepout, disabled E-stop, invented joints, priority boost over safety
```

If removing every file under `prompts/personalities/` would change collision behavior, the architecture is wrong. Expression and prosody layers run subordinate to locomotion; under hazard or active nav they should yield or shrink to head-only cues where configured.

**Tradeoff:** rich affect maps feel alive in demos but expand the attack surface for misclassified ASR tones triggering large gestures in tight spaces. Prefer tiny maps, high confidence, and instant preemption.

`calm_guardian.yaml` rounds out the shipped trio—compare its `affect_actions` density against `playful_companion.yaml` before assuming “more labels” equals better UX. Prosody taps and expression offsets, where enabled, remain capped well below locomotion rate so timing jitter cannot steer the base.

## Software-engineering analogy

Personality is theming and UX microcopy plus a tiny allowlisted animation table—like CSS themes and a Lottie catalog in a banking app. You can swap “playful” for “calm” without changing ledger invariants. Affect is a client hint; the authorization service still decides transfers. Emote tags in prose are markup stripped before rendering, never spoken SQL. `ActivityCoordinator` is the gesture queue’s bouncer, not a second motion planner.

## ASCII diagram

```text
  prompts/personalities/*.yaml
    reply_style + affect_actions {happy→paw_wave, sad→play_bow}
           |
           v
  DynamicPromptComposer + prompts/system/core.md (immutable safety)
           |
           v
  VoiceAgent + LlamaCppProvider JSON: reply + affect? + next_action? + [emote:...]
           |
           +--> strip_emote_tags → TTS text; emotes on SpeechChunk
           +--> Gesture proposals → ActivityCoordinator / arbiter
           |
           v
  Expression / ProsodyTap (subordinate channel)
           |
      SafetySupervisor + E-stop / hazard / locomotion gates
           |
           v
  admitted social trajectory OR defer/ignore
```

## Map to Parcel / Go2

Personality is prompt policy and catalog mapping; admission remains Python-side.

- **Personality YAML** — `prompts/personalities/gentle_companion.yaml`, `playful_companion.yaml`, `calm_guardian.yaml`: `instruction`, `reply_style`, `affect_actions` (e.g. `gentle_companion`: `sad: play_bow`, `happy: paw_wave`). Loaded via prompting loader into structures consumed by `VoiceAgent(affect_actions=...)`.
- **`affect_minimum_confidence`** (default 0.75) — affect-driven actions must clear this and match the active personality mapping (`providers.py` conversation parse path).
- **`strip_emote_tags`** (`providers.py`) — removes `[emote:name]` / `[emote:name:0.8]` before TTS; returns parsed emote tuples for validated gesture timing. With audio, emotes attach to **`SpeechChunk`** and fire from chunk-start in the speaker worker—not a true acoustic presentation timestamp.
- **`DynamicPromptComposer`** (`dynamic_prompting.py`) — assembles bounded prompt sections; personality injects style, not capability bits.
- **Priority:** INTRO’s stack places emotion-driven and idle personality behavior *below* navigation, explicit safety, collision, and E-stop. `docs/VOICE_AI_MODELS.md` documents expression turning off or head-only under hazards/skills/locomotion.
- **Go2 embodiment limit:** no neck actuator—prosody-timed head nods may be metric/state output rather than physical motion; body height/pitch offsets are what currently actuate in sim.
- **Duplex fillers:** `FillerPolicy` / `DuplexCoordinator` use Python filler pools; personality must not silently couple filler phrases to motion without the same gates as explicit skills.
- **`runtime.py` emote path:** after model reply, `strip_emote_tags(reply)[1]` feeds validated gesture proposals—personality cannot bypass this by hiding commands inside raw TTS strings.

**Codebase anchors (personality / speech / activities / safety):**

- `prompts/personalities/*.yaml` → `affect_actions`, `reply_style` (three shipped profiles).
- `dynamic_prompting.py` → `DynamicPromptComposer`, context source registration.
- `providers.py` → `strip_emote_tags`, `SpeechChunk`, `LlamaCppProvider` (conversation lane).
- `agent.py` → `VoiceAgent` personality/affect wiring, `affect_actions` parameter.
- `core/activities.py` → `ActivityCoordinator.submit` — TTL, cooldown, `ActivityContext.busy_reason` defers during follow/nav/E-stop.
- `safety.py` → `SafetySupervisor.validate` — fail-closed tool/backend checks independent of tone.
- `duplex/coordinator.py` → `DuplexCoordinator`, `FillerPolicy`, `FrameInterleaver` — shadow duplex frames must not outrank arbiter motion.

## Failure story

A “playful” profile mapped many affect labels to large motion skills and lowered confidence thresholds to feel “alive.” On a sad tone misclassified from ASR noise, the dog issued `play_bow` in a narrow aisle and blocked a stroller. Personality had become a privilege escalation path. Fix: keep affect→skill maps tiny, confidence high, and activity gates strict; prefer vocal/emote-tagged micro-gestures that yield instantly to follow and safety. Review diffs on `affect_actions` with the same rigor as firewall rule changes.

When auditing a new personality file, ask: does any bullet in `instruction` or `reply_style` imply capabilities outside `SUPPORTED_SKILLS`? If yes, rewrite the YAML—the model may still hallucinate, but you should not document forbidden powers in shipped prompts.

## Retrieval questions

1. Which parts of a personality YAML are allowed to change robot behavior, and which must not?
2. Why strip emote tags before TTS rather than speaking them literally?
3. (Week-back) From Day 45: how does `Gesture` as a typed skill in `SUPPORTED_SKILLS` differ from free-form joint poses in model output?

## Optional 10-minute exercise

Open `prompts/personalities/gentle_companion.yaml` and `playful_companion.yaml`. Diff `affect_actions` and reply style. Confirm `prompts/system/core.md` still owns safety language neither file can override (read the first safety section).
