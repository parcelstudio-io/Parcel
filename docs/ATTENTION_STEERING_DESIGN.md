# Voice-steered attention: design record

**Date:** 2026-08-04 · **Status:** approved direction (owner decisions
incorporated); delegation in [../scrum/20260804/task_3/](../scrum/20260804/task_3/).
**Method:** 3 code audits (navigation 7/10, brain 8/10, runtime arbitration
6/10) + 3 research passes (arbitration architectures, voice-as-steering,
suspend/resume) + adjudicated synthesis. Full agent output preserved in the
session task log; key sources at the end.

## The feature, precisely

Voice must *influence* in-flight behavior with personality-dependent,
non-trivial probability: owner talks while the dog walks → possible glance
without abandoning the walk; owner calls while the dog walks away → stop,
turn, attend, then resume or await; something is funny → chuckle bounce.

## The triangulated finding that shapes everything

The one capability this needs most — **non-destructive pause with resume —
is missing independently at all three layers**:

- `Dog.stop → nav.stop` destroys the `Mission` (navigator has only
  start/stop);
- the executive's `voice` interrupt source is a **hardcoded no-op** and
  `TASK_STATES` has no `suspended` entry;
- runtime preemption is destructive and hand-enumerated at **16 call
  sites**, with exactly one bespoke resume precedent
  (`_resume_follow_after_search`, hand-cleared at 5 sites).

Hence the owner-approved sequencing: **foundations refactor first.** Without
it the arbitration layer scores an effective 4/10 for this project; with it,
"attention" becomes one channel entry plus one priority-table line.

## Architecture: a second loop, with a trainable core

A deterministic **attention/reaction layer** between the PlanIR executive
and the 50 Hz expression layer, ticked on the existing 10 Hz control loop
(Kismet precedent: >10 Hz unnecessary), fed by a typed stimulus bus, shaped
as a Vector-style tiered priority stack over an explicit resource table.

**Layer 0 — stimulus bus.** Typed, timestamped, *revocable* events
(ADD/REVOKE/COMMIT, extending the existing barge-in epoch concept):
`SPEECH_ONSET` (~0 ms), `SUMMONS_PROSODY` (F0 rise/energy over 300–500 ms —
the species-correct cue; real dogs key on pitch contour, not content),
`NAME_HIT` (owner-enrolled keyword, ~80–160 ms, never hard-gated — custom
names are the weakest detector), `AFFECT`, `KEYWORD` (partial-ASR via the
router), `SPEECH_END`; later `TURN_BOUNDARY` (VAP) for resume timing.

**Layer 1 — reaction arbiter** (grows out of `ActivityCoordinator`, not a
parallel mechanism). A reaction is a proposal carrying {tier, resource
tracks, score factors, cooldown, habituation key}. The **resource table** is
the load-bearing move (Vector's tracks / QRIO's resource-conflict SLEEP):
`base_lease` (existing CommandArbiter TTL), `head_gaze` (existing
ExpressionGate authority), `voice_tts`, `expressive_posture` (new; HAL
decision below). A glance claims `head_gaze` only → contends with nothing →
"attend without abandoning" is solved *by construction*. The seed already
ships: `reactions.on_speech_start` orients at 50 Hz today; this project
makes it probabilistic, habituated, and escalatable.

**Tiers.** T0 safety (collision gate, TTC, E-stop — untouched ceiling).
T1 summons/recall: a real behavior channel claiming the base lease at a new
priority (~55; placement is a live discussion item), which **suspends — not
cancels** — the running task. T2 ambient: gaze/posture tracks only, never
the lease. Escalation ladder head → body-rotation → whole-body; T2 upgrades
to T1 only when `NAME_HIT` + `SUMMONS_PROSODY` confirm within 300–800 ms —
the glance itself fires on prosody alone at ~200–300 ms, before ASR.

**Selection per tick:** hard filters (cooldown, track availability, T0
vetoes as multiplicative zeros) → Improv-form scoring
`w = Scale(Π factorᵢ^influenceᵢ)` where personality YAML supplies only
exponents/gains → seeded weighted-random draw (the "non-trivial chance",
literal) → ~1.25× commitment bonus + minimum dwell so near-ties don't
flicker at 10 Hz.

**Probability, temperament, habituation.** One arousal scalar (Anki's
shipped regression from 9 affect dims to 1 scalar + 5 emotions) scales
probability and amplitude. A `temperament:` block (continuous 0–1:
sociability, reactivity, patience, playfulness, independence) conditions
scoring — same equation, different numbers per profile; **every knob is
config** (owner decision #2) with fail-closed validation and a live
`/api/social` inspection surface (features, last N draws with probabilities,
habituation levels). Habituation: hard cooldown before sampling (shipped
Vector pattern; `ActivityCoordinator` has it) + repetition penalty keyed on
event name + Kismet's signed decay (w → −W, τ≈5 s, reset on disengagement)
for the glance — the negative tail produces dwell→disengage→reacquire
instead of metronome reactions. Base rates start low (Erica corpus: only
~14% of laughs warranted response; always-responding underperformed):
name-glance-while-walking ~0.3–0.5, ambient glance lower, chuckle ~0.1–0.2.
Engagement mode {Unengaged, SemiEngaged, FullyEngaged} is a first-class enum
on profiles *and plan steps* — "this errand is important" costs no new
machinery.

**Pause/resume (the genuinely new machinery).** Suspension is an
executive-owned record, never plan-embedded (BT.CPP's halt-state bugs and
the industrial FSM-above-the-tree precedent). `SUSPENDED` is a **status, not
an outcome** (PLEXIL) — the verifier must never read a pause as failure.
Resume is a **fresh dispatch**: re-validate the step tail against the
current world (Nav2's lesson), re-acquire the TTL lease (expiry during
suspension is a feature — a stale pre-pause twist cannot land), re-verify
preconditions, guard double-dispatch via the existing
(task, revision, step, attempt) identity + a completed-set, and require a
fresh observation after long suspensions (the stale-costmap failure class).
Legibility: suspend plays no get-out; resume plays a short get-in; cancel
plays a get-out — that is what makes resume vs await vs abandoned readable.
One Kismet guard adopted: during a glance, suppress owner-track-lost
transitions and follow-heading corrections (the glance yaws the sensors),
or the glance triggers SearchOwner.

**HAL decision (open, pending week-one spike).** A chuckle bounce is not
expressible in SE2. Option A: capability-gated expressive-posture channel
(Go2 Euler pitch/roll + BodyHeight; no-op elsewhere) — recommended,
contingent on the spike: public docs are *verifiably silent* on whether
Euler/BodyHeight composes with Move while trotting (Spot's equivalent
restricts absolute body pose to standing; commands silently saturate — read
achieved posture back). Option B fallback: bounded additive twist deltas
upstream of the gate; glance degrades to heading-bias + cadence dip.

## The trainable core (owner decision #1, reconciled with the evidence)

The owner requires the steering decision to be **trainable, with model
output at ≤1 s intervals**. The research is unambiguous that a runtime
LLM/planner in this loop fails on latency (glance budget 200–300 ms; LLM
round-trips are 1.7–7.8 s in the best-instrumented companion system),
compute (Orin-class TTFT variance), data economics (Erica: ~80 teleoperated
dialogues → ONE binary decision), and safety (action hallucination). The
reconciliation — which *exceeds* the ≤1 s requirement rather than resisting
it:

- The arbiter ticks at **10 Hz**: a behavior decision every 100 ms, 10×
  faster than asked. Its decision function is the swappable, trainable core.
- **Stage A (ships first):** hand-parameterized stochastic tables
  (temperament-conditioned, seed-deterministic in evals). Every tick logs
  `(features, draw, seed, emitted behavior, execution outcome, observable
  owner response)` — the training set starts accumulating on day one.
- **Stage B (first trained component):** a small **fusion MLP** replaces the
  hand-tuned call score as a drop-in — needs a few hundred logged episodes,
  runs in microseconds, changes nothing structural.
- **Stage C (the model brain, earned):** if the falsification criteria fire
  (repertoire >20–30 behaviors whose appropriateness depends on scene
  semantics the feature vector can't enumerate, or logged episodes show the
  hand-tuned score underperforming), adopt the **Helix shape**: a slow model
  emitting a conditioning latent/policy to the fast deterministic layer —
  never twists or joint targets. The arbiter is deliberately the substrate
  that signal plugs into; nothing built now is discarded.
- Offline, the LLM is an authoring tool from day one: 5–15 reviewed
  parameter variants per reaction per personality, sampled at runtime —
  generative variety, zero runtime latency, no hallucinated motion.

Safety framing is invariant across stages: randomness and learning live
only in *whether and which* named, pre-authored reaction is proposed —
never in trajectory content. Every motion-claiming reaction flows through
the unchanged chain (arbiter → reactive safety → TTC → shaper →
unconditional collision gate).

## Quality gate (owner decision #4)

The foundations refactor exits **only** with the full suite green and the
follow-bench + embodied-plan ledger rows *byte-identical* (a pure refactor
moves no eval number). Steering phases add interaction scenarios: glance
during walk must not increase collisions or leave the follow band;
stop-turn-attend-resume completes the mission within bounded delay; Stage-A
runs deterministic assertions, Stage-B runs statistical bands (response
rates per temperament, zero safety-gate violations across N seeded runs).

## Remaining open decisions (for discussion)

1. **Priority placement:** attention at ~55 (below voice-commanded motion)
   or sharing 60 — can a summons interrupt a voice-commanded walk?
2. **Mask-vs-suspend threshold:** lease-masking already gives auto-resume
   free for short interruptions (~≤2 s) but leaves navigation ticking
   (burning the 400-tick progress watchdog in ~40 s); explicit suspension is
   honest but heavier. Keep both with a duration threshold?
3. **Resume-vs-await:** deterministic default (resume when the owner's turn
   yields, unless a new directive arrived → existing interrupt/replace path
   with a structured suspension record shown to the planner). Planner
   consulted on *every* resume is socially smarter but re-inserts 2–8 s.
4. **HAL Option A vs B** — decided by the week-one hardware spike.
5. **Live randomness:** seeded-deterministic per session vs true-random live
   (evals seeded either way). Recommendation: true-random live.
6. **Scope:** may a summons interrupt SearchOwner in v1? If yes, the
   shared-map refactor moves from "later" into this project (search resumes
   amnesiac today).

## Key sources

Vector/Anki behavior stack + affect regression; Kismet attention system
(rates, signed habituation w=W·max(−1, 1−dt/τ)); QRIO resource conflicts;
NAOqi engagement modes + escalation ladder; PLEXIL suspended-status
semantics; BT.CPP issues #884/#635 (halt-state loss, double-tick); Nav2
pause/replan lessons; Helix dual-rate architecture; Erica shared-laughter
corpus; VAP turn-taking (2.7 s → 1.5 s response delay); dog-directed speech
prosody literature; openWakeWord custom-keyword limits; Spot body-pose
composition restrictions.
