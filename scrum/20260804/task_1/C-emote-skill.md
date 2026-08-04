# Workstream C — conversation-reactive emotes

## C1 — `Emote` PlanIR skill + inline TTS tags · **Owner: Claude Opus** · after A1

Goal: the LLM can make the dog shrug, paw-scrape, bow, stretch — keyed to what
it is saying — through the same validated dispatch path as every other skill.
Selection, not generation: the model picks from an authored catalog; the
system owns safety. Design source:
[../../../docs/RESEARCH_2026_ROADMAPS.md](../../../docs/RESEARCH_2026_ROADMAPS.md) §2
steps 2–3 (do step 2 now; step 3's schema upgrade is a later sprint).

**Scope (deliberately v1-small):**

1. **Skill contract** `Emote(clip_id, intensity)` in the brain registry:
   - `clip_id` validated against an *emote manifest* — a curated allowlist
     subset of the existing 26-skill catalog (start with: `sit`, `bow`,
     `stretch`, `paw_wave`, `play_bow` — whatever of these exist in
     `configs/skills/`; check ids, don't guess).
   - `intensity` float in [0.5, 1.5], v1 semantics: scales hold durations
     only (amplitude scaling waits for the schema upgrade).
   - Compiled preconditions: stationary only (no active navigation/follow
     dispatch), not battery-critical, E-stop clear — mirror how
     `ReturnToSafePose`'s contract compiles its gates in
     `brain/validator.py`, and validate pose ids against the same
     runtime-supplied catalog the registry already receives (pose_names
     pattern — see the 2026-08-04 review fix; do not build a second
     vocabulary).
2. **Adapter dispatch** (`brain/runtime_adapter.py` + runtime callback):
   route through the existing activity coordinator / pose runner so emotes
   respect the same interruption machinery as social gestures; completion =
   clip finished + robot stationary (feedback-verified, like
   `ReturnToSafePose` — never asserted).
3. **Inline tags in speech**: the conversation layer may emit
   `[emote:play_bow]` / `[emote:stretch:0.7]` inside reply text.
   `SentenceChunkedSynthesizer` strips tags from the spoken text and surfaces
   them as `(sentence_index, clip_id, intensity)`; the runtime converts each
   to an `ActionProposal` through the **existing** proposal + cooldown
   arbiter (`propose_action`) at that sentence's playback start. Unknown clip
   id in a tag → tag dropped with a warning event, speech unaffected.
   Barge-in cancels pending tag-emotes (reuse the A4 epoch-tagging).
4. **Prompting**: add a stable `ToolPolicySource`-style section (new
   `EmotePolicySource` in `dynamic_prompting.py` or a static section) listing
   available emote ids + one-line usage guidance ("at most one emote per
   reply; only when it matches the emotional beat"). Keep it in the *stable*
   plane — the catalog rarely changes.

**Not in scope:** new clips, Laban parameterization, walking emotes,
per-keyframe variability — all later sprints.

**Acceptance:**
- Validator tests: unknown clip rejected; intensity bounds; moving-robot plan
  rejected (snapshot admission), stationary accepted.
- Adapter test: dispatch → pose runner call → verified completion; failure
  leaves robot stopped.
- Tag pipeline test: reply with `[emote:...]` speaks clean text, fires one
  proposal at the right sentence, respects cooldowns, cancels on barge-in.
- Prompt test: emote policy section present in `/api/prompt` with the
  manifest ids.
- Full suite + ruff green; `configs/robot.yaml` hash re-frozen if touched.
