# AUDIT — R1.6+R3 "Ears, Mouth, and Body" · Fable

**Date:** 2026-08-18 · **Card:** task_6 · **Executor:** Claude Opus (agent)
**Verdict:** **ACCEPT_CLOSE** — with §A (browser audio gateway) explicitly
carried forward as its own card, per the card's own priority clause.

## The milestone

**The sim dog moved on the voice model's proposals, through the full admission
chain.** Live smoke on `gpt-realtime-2.1-mini`, MuJoCo city, free-text persona:
"Wave at me please" → `play_gesture` → `SafetySupervisor.validate` →
coordinator → `Executing paw_wave`, dispatched to the backend. "Go to the
sidewalk" → `navigate_to` → router (`deterministic-v1.2`, fresh turn id) →
sketch admission → `NavigateTo` mission `state: running`. Zero server errors,
zero protocol refusals, $0.0124 for the smoke. This is owner directive 2
satisfied literally.

## The buried lede, verified: no live session had ever been configured

The executor found that `session.update` had been **refused whole on every live
session since R1.5** — `missing_required_parameter: 'session.type'` — so no
instructions, persona, voice, VAD, or transcription switch had ever actually
applied; the provider ran on defaults while our code believed otherwise.
R1.5's live test asserted only that a reply arrived, so it stayed green.

Audit corroboration: this is the SAME wire shape I fixed independently in the
corpus scraper (three live probes, task_3 addendum), and the new
`SessionUpdate.to_payload()` matches my probe evidence field-for-field
(`type: realtime`; `voice`/`turn_detection`/`transcription` under
`session.audio.*`; `format` as an object). The MUST-NOT-TOUCH deviation on
`protocol.py` is therefore **ACCEPTED** — same class and precedent as the
auditor's own `LifecycleEvent` fix, and the alternative (shipping a lane that
configures nothing) was not an option.

**Register lesson (second occurrence of the pattern):** a live test that
asserts "a reply arrived" verifies reachability, not configuration. S13's new
pin (transcription actually on) is the right shape; every future live-path
claim needs an assertion on the CONFIRMED session state, not the request.

## Independently verified

1. **Fresh full gate:** PASS — 6,107 passed, ruff `new 0`, parity and
   sentinels green (executor's run agrees).
2. **All 15 seeds re-run by the auditor:** 15/15 RED, tree restored, clean 167
   green. S10's first-pass-green disclosure (asserting the supervisor's
   guarantee rather than the broker's) is honest and its fix is the stronger
   test.
3. **Broker ordering:** `validate(call)` before any door
   (`tool_broker.py:513`); pose-under-e-stop and dedupe pinned by seeds.
4. **Deviation 4 corrected a card error of mine:** `propose_action`
   (runtime.py:3877) accepts only `kind="skill"` limited to catalog
   pose/trajectory — the card's `kind="pose"` literal was wrong; the
   executor's route is the correct one.
5. **Persona addendum works end-to-end:** free text from
   `configs/realtime.yaml.example` replaces the profile block, guardrails
   survive, digest moves on persona change (S12 pins fail-closed empties).
   The live smoke ran under a free-text persona.
6. **Deferral of §A is within the card's own sequencing clause** ("D, C, E
   are non-negotiable; A may land offline-complete or defer"): D, C, E are
   delivered and live-proven; `mode: audio` fails loudly at construction
   rather than pretending.

## Carry-forwards

1. **§A browser audio gateway** — the only thing between the owner and
   speaking to the dog by voice. Next card; `browser_sink.py` and the panel
   affordance already exist.
2. **Prompt-quality item, not a defect:** in one run the model narrated
   "I can't physically move your way" in the same turn its gesture executed —
   the SI's "never claim physical action" rule read as "deny physical
   ability." An SI v2 wording pass (with version bump) should distinguish
   "don't claim uncommanded outcomes" from "you cannot act at all."
3. The smoke substitutes the observation timestamp (recorded in the status
   doc) — fold real-clock observation into the first human-witnessed session.

## What remains unproven (endorsed from the executor's own list)

No human has spoken to it; no audio has played; barge-in and mark integrity
unproven; the mission ran but did not arrive; kinematic world, so "the leg
moved" is a dispatch record, not physics.
