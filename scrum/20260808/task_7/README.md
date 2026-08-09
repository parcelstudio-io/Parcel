# Sprint 2026-08-08/09 · task_7 — coordinator close-out: owner directives

Two owner directives, both executed, plus the defect the second one exposed.

## Directive 1 — bench: "get to the band … or expand the k0 band"

Options measured, not assumed ([task_3](../task_3/BENCH_PLACEMENT_STATUS.md)):
- **stand beside the pedestrian** — REFUTED twice: the *bench itself* blocks it
  (1.195 m available vs 1.200 m required, even permitting contact with the
  person), and the clearance that would open the raw band is 0.331 m
  footprint-to-surface, inside the reactive gate's own 0.65 m stop.
- **far side of the bench** — REFUTED: bldg_1 is 0.77 m behind it; the best
  pose over all 360 bearings is 0.78 m from the surface, inside the gate's
  0.97 m envelope. Sampler checked for directional bias: clean.
- **expand the band** — the owner's fallback, and the only thing that works.

Root cause, bigger than the bench: `NEXT_TO_BAND_M` was a distance to the
anchor's **centre** while every stand-off authority measures to its
**surface**, so `next_to` was impossible for any anchor with radius > 0.38 m —
bench, tree and planter were all advertising an impossible affordance.

Fix ([task_6](../task_6/SURFACE_BAND_STATUS.md)): the band is now
**surface-anchored**, one definition (`next_to_band_from_centre`), planner and
arrival authority provably reading it identically. Episodes re-frozen v2 → v3
with a bridge table; v1/v2 byte-identical. Predicted blast radius confirmed
(one K0 flip, the bench) and one prediction **refuted** honestly: SR moved
+0.04 in both modes because the bench became a genuine success, and
`false_arrival` fell 2 → 1 (it had been a false arrival *because the band was
wrong*).

**Result: the bench case is a HARD GATE** — sits in band, both authorities
agree, 21–26 s. Coordinator applied the flip after also fixing the test-side
defect that masked it: the e2e file built the bench goal from the
hand-transcribed landmark table (centre 3.0, r 0.700) instead of the scene's
derived geometry (3.045, r 0.733757) — a band placed 7.8 mm wrong. It now
reads `scene_truth.derived_landmark_table()`; the lamppost entry is
byte-identical between tables, so lamppost cases could not move.

## Directive 2 — "person in scene is a personality decision; default ask for help, configurable"

Landed ([task_4](../task_4/YIELD_POLICY_STATUS.md)): `personality.yield_policy`
{patience_s, on_blocked, reask_interval_s, max_asks, release_grace_s} +
`yield_speech`, per personality, `on_blocked: ask_for_help` default on all
three. `wait` reproduces the old behaviour in one config line.

The live run found what unit tests could not: a pedestrian stream *chatters*
(~1 s gaps), so the first version asked 13 times in 240 s. Fixed by scope
separation — brief releases no longer refund patience; the ask budget is
per-mission and never refunded. Result: two asks, honest end at 54 s with
`blocked_by_person_unanswered` instead of a 240 s `step_timeout` that named
nothing. Honest trade-off recorded: the robot now stops 0.29 m outside the
polygon rather than drifting inside over 4 minutes.

## The defect directive 2 exposed — `Vocalize` was never audible

([task_5](../task_5/VOCALIZE_AUDIBLE_STATUS.md)) `_brain_vocalize` wrote chat +
event and never reached TTS, so **every planned utterance step in every
mission had been silent since the skill existed**. New
`DuplexVoiceSession.speak_system()` reuses the real output path (sink, chunk
tokens, playback clock, prosody tap, barge-in) and explicitly not the filler
bookkeeping. Concurrency policy: **skip, never overlap or queue** — one
ordered sink means overlap is corruption, and a queued ask delivered after the
person moved is a lie.

Rig evidence with a control: 5.27 s / 5.58 s of measured audio (peak 32729),
versus **0 s, peak 0** with the fix stubbed back to the old door and an
identical chat entry.

## Tree state

Default suite **2913 passed / 0 failed**. E2E **16 passed / 1 xfailed**
(traffic, reason rewritten with the yield measurements — its two named flip
conditions are N20 navigation-side release and U35's responsive pedestrian).
Frozen `evals/companion/**` byte-identical; embodied 1250 row unmoved.

Open, recorded: N20 (release when a person will not clear the pose), N22
(acoustic pack case needs a schema version bump), `building` next_to is now a
declared vocabulary choice rather than a derived exclusion, mutation panel
still runs against v2 episodes.
