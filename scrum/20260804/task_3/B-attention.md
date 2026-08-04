# Workstream B — stimulus bus, arbiter, behaviors, eval (V2–V7)

## V2 — Stimulus bus (pure module) · **Sol** · days

New `src/parcel_robot/attention/stimuli.py` + tests. Numpy/stdlib only.
Typed events with the Incremental-Unit lifecycle (ADD/REVOKE/COMMIT):
`SPEECH_ONSET, SUMMONS_PROSODY, NAME_HIT, AFFECT, KEYWORD, SPEECH_END`.
Includes: prosody summons scorer (F0 mean/rise/variance + energy over a
300–500 ms window from 16 kHz PCM — pitch-contour driven, content-free) and
a fusion scorer combining name-posterior × owner-facing-angle × distance
(never hard-gates on the name detector). Contracts frozen in the card;
deterministic tests with synthetic contours; a REVOKE retracts an event's
not-yet-committed consequences.

## V3 — ReactionArbiter core (pure module) · **Sol** · days

New `src/parcel_robot/attention/arbiter.py` + tests. The selection engine
only (no runtime imports): reaction declarations {tier, tracks, score
factors, cooldown, habituation key}; resource-track table; hard filters as
multiplicative zeros; Improv-form scoring `w = Scale(Π fᵢ^gᵢ)` with gains
supplied per personality; seeded weighted draw; ~1.25× commitment bonus +
min dwell; habituation: cooldown + repetition penalty + Kismet signed decay
(w → −W, τ configurable, reset on disengagement) for gaze-class stimuli.
Every decision returns the full audit record (features, weights, draw, seed)
for the episode log. Deterministic under seed; statistical tests for rate
bands over 10k draws.

## V4 — T2 behaviors wired · **Opus** · week · after V1+V2+V3

Glance (head_gaze track: expression-layer orient, probabilistic, habituated,
escalation ladder head→body-rotation) and chuckle bounce (expressive-posture
track per HAL decision; BeatLayer-style stance oscillation, joy-affect
trigger, amplitude from arousal). Sensor-suppression guard during glances
(suppress owner-track-lost + follow-heading corrections). `/api/social`
inspection endpoint (features, last N draws with probabilities, habituation
state, temperament in effect). **Episode logging from the first tick**:
`(features, draw, seed, behavior, outcome, observable owner response)` —
this is Stage B's training set. Config: `attention:` section, fail-closed.

## V5 — T1 summons/recall · **Opus** · week · after V1, V4

The full sequence as one channel: confirm (NAME_HIT + SUMMONS_PROSODY within
300–800 ms) → suspend running task (executive SUSPENDED + nav pause +
ResumeIntent) → get-in → stop-turn toward speaker bearing → attend
(engagement posture, listening state) → resolve: new directive → existing
at-checkpoint interrupt/replace path with the structured suspension record
shown to the planner; owner turn yields with no directive → resume as fresh
dispatch (re-validate tail, re-acquire lease, fresh-observation gate after
long suspensions, get-in re-commit); timeout → await per temperament
(`patience` parameter). SOURCE_PRIORITIES placement per V0 decision.

## V6 — Temperament, engagement, LLM-as-data · **Opus** · days

`temperament:` block (sociability, reactivity, patience, playfulness,
independence; 0–1) consumed as scoring gains; engagement-mode enum
{Unengaged, SemiEngaged, FullyEngaged} on profiles and per plan step
(compiled by the validator like invariants); arousal scalar wired to
probability + amplitude; skills post success/failure affect events; offline
LLM-authored variant pools (5–15 reviewed parameter variants per reaction
per personality, sampled at runtime).

## V7 — `ATTENTION_V1` eval · **Opus** · week · after V4, V5

Headless scenarios with scripted voice-event traces (no audio hardware
needed — events injected at the bus): ambient-talk-during-walk (glance rate
within per-temperament band over N seeded episodes; zero collision increase;
follow band held), summons-mid-walk-away (suspend→attend→resume; mission
completes within bounded delay; correct legibility events), habituation
(third consecutive ambient event → response rate decays), never-respond
cases (E-stop latched, proximity active → zero reactions, always).
**Regression gate:** existing follow-bench + embodied suites run in the same
CI lane; any drift fails the card. Ledger + `does_not_prove` (scripted
events ≠ real prosody detection; that closes only with B1 audio hardware).

## Stage-B trigger (standing, Fable)

When the episode log holds a few hundred labeled episodes: train the fusion
MLP call-score, evaluate against the hand-tuned score on held-out episodes,
swap only if it wins. Re-adjudicate the full "separate brain" question
against the written falsification criteria in the design doc — with the log
as evidence either way.
