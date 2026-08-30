# Navigational and conversational fluidity: Model A / Model B — study report

Date: 2026-08-29 · Author: Fable (session parcel-0e) · Status: **FINAL + §8 continuation (21:xx EDT 2026-08-29)** — every experiment has RESULTS and a Fable verdict; physical motion remains NO-GO.
Physical motion: **NO-GO**, unchanged; nothing here gains actuation authority.

> **Historical snapshot.** This report preserves the earlier five-experiment
> Fable wave and its execution history. The [August 29 research
> index](README.md), the current Sol assessment, and each later experiment's
> `VERDICT.md` control current readiness. A post-cutoff addendum at the end
> reconciles evidence completed after this report's original close.

## 0. The owner's ask, restated as testable questions

1. Is there a **trainable, fully duplex Model A** that reads constant streams
   (sensors, voice, user context, the world now and over the last minute,
   global history) and emits local movement (or a global-plan update) plus a
   representation the hosted voice can narrate from — and can it be trained
   in simulation?
2. Can a **Model B** on top of A turn an owner-recognized voice command into
   a steering injection (revise / keep / queue the global plan) and turn A's
   output stream into narration so the hosted voice says "Sure, I'll check
   the sofa" … "Done! Should I go back to the door now?" at the right
   moments, with the plan history as its memory?
3. What do **robust evaluations** of navigation, instruction following with
   interruptions, and conversation look like for this — and what is a
   well-instrumented sim-to-real harness where the LLM converses while the
   robot navigates?

## 1. Where the product is today (measured, not inferred)

- **Navigation.** NAV_INSTRUCT v4: SR 0.20 / SPL 0.13 on the full
  125-episode matrix (5 families × 5 tiers), 0 collisions, 1 false arrival;
  failure mix 53 planning / 24 termination / 7 grounding / 3 search / 6
  false-arrival, 22 authority disagreements (QEV-1, 2026-08-25); Sol's two
  fresh 08-29 runs on the same recipe: 34/125 = 0.272 SR, SPL 0.206,
  36 planning / 24 termination / 13 grounding / 11 search / 7 false arrival
  (`product-evals/RESULTS.md`, not re-run by me). Room-scale
  point-goal acceptance: 60/60 (NAV-ACCEPT). Kidnap: 3/3 false arrivals at
  5.2 m without the discontinuity latch.
- **Instruction following mid-task.** The executive has submit / suspend /
  resume / replace and a transactional goal amendment (C8); there is **no
  plan-queue policy** — after an amended goal completes nothing returns to
  the original goal, and "after that, …" has no representation.
- **Conversation.** Captured realtime corpus: 25 threads / 174 turns, 0 hard
  failures, 66 risk flags; semantic review 6 PASS / 8 MIXED / 11 FAIL;
  capability grounding **2/10** — the hosted model invents actions the body
  lacks (`comfort_bow`, `happy_wiggle` …) and claims arrivals; personal
  conversation 3/13; acoustic gates 5/9 (endpointing 0.81 s vs 0.50 bar).
- **The Model-B seams already exist, deterministic by design.**
  `realtime/whisperer.py` forwards a `StateDigest` (nav state/goal, blocked
  class, following, battery, e-stop, position) on two bands + three
  mechanisms — a local LLM judge was benched and **lost** (delayed an
  e-stop by 9.8 s); `realtime/tool_broker.py` admits hosted proposals only
  through `SafetySupervisor.validate` into the same doors typed commands
  use; `developer_note.py` renders robot facts inside an untrusted-data
  boundary. Nothing today narrates *plans* (started / queued / resumed) or
  A's intent.
- **Sims.** Headless city (kinematic, fast, the nav stack runs in it) and
  MuJoCo static/dynamic city through the live runtime (`_LiveRuntime`:
  sim subprocess + `handle_text`); neither has audio.

## 2. Literature: what has been tried, verified

Full review: `literature/LITERATURE_REVIEW.md` (ten topics, every claim
fetched and adversarially re-fetched; `literature/sweep.json`). The facts
that shape the design:

1. **Nobody runs a language model at 10 Hz on a robot.** Every real legged
   deployment is dual-rate: a 0.5–4 Hz language/plan lane (StreamVLN,
   DualVLN 2 Hz, NaVILA ~1 Hz, TIC-VLA 0.5 Hz — the only one on an onboard
   Jetson, 0.75 SR on a Go2) over a 10–50 Hz policy. Even so they stall
   (LiveVLN: 30 % idle, 95 % stop-and-go on a G1) until a committed-prefix /
   revisable-tail handoff is added.
2. **The Model B precedent exists and works:** Hi Robot's high level re-runs
   every ~1 s *and* on every user interjection, emits a language command
   plus a spoken reply (76 % instruction accuracy vs 30 % for a GPT-4o high
   level); Yell-At-Your-Robot's override switch is the injection mechanism.
   Speaking and acting in one network costs control quality (ELLSA).
3. **No benchmark scores spoken mid-task instruction changes for a moving
   robot.** InterruptBench (web agents: ~20 % success), EchoChain (voice:
   inertia / amnesia / displacement, < 50 % pass), IHBench (enterprise) —
   Parcel must define its own and cannot claim comparability.
4. **The hosted voice is slower and more fragile than its demos:** GPT-4o
   Realtime resumes after side-talk 2 % of the time; tool-bearing turns take
   4–7 s; voice agents retain 30–45 % of text capability (τ-Voice); async
   function calling (GA) is what lets "Sure, I'll check the sofa" be said in
   the same turn the robot moves.
5. **Narration is rate- and reliability-dependent:** what + why on every
   deviation keeps trust (Kox, η² = .18); explanations help only unreliable
   robots (Wang); users dislike non-stop chatter; "done" must come from
   detectors/receipts, never from the voice model's belief.
6. **The Orin numbers (gap sweep, §12 of the review):** a ≤ 2 B VLM is a
   ~2 Hz lane on the AGX Orin (1 Hz with an 8-frame memory); SigLIP-class
   encoders cost 98–160 ms per frame; nothing language-shaped fits the 10 Hz
   loop; the Go2 holds the last `Move` for 1 s (a 200–300 ms gateway watchdog
   is mandatory); far-field owner verification on a robot body is 10–18 %
   EER, so the owner/addressee gate is a local two-tier cascade, not the
   hosted model; Starlink spikes +74 ms every 15 s and drops ~2.7 % of the
   time in motion, so the control loop never touches the link.
7. **Memory is bounded and age-tiered, plans are explicit:** bounded pruned
   memory beats unbounded (StreamVLN 45.5 vs 40.0); implicit transformer
   memory does not carry across instructions; plan snapshots + a
   completed-steps ledger are what resume needs.

## 3. Designs: Model A and Model B on Parcel's seams

The owner's two boxes map onto seams that already exist; the study's job is
to say which parts should become *trainable* and which must stay
deterministic, and to measure the difference.

```
 owner speech ──► ASR / hosted Realtime lane ──► owner-recognized utterance
                                                     │
                       ┌───────────────── MODEL B ────┴──────────────────────┐
                       │ STEER: utterance × plan-queue state → {revise, keep, │
                       │        queue, clarify} → executive replace / suspend+ │
                       │        push / no-op / ask   (router + amendment today; │
                       │        queue + clarify-with-plan-context are new)      │
                       │ NARRATE: A's narration events × plan queue → the      │
                       │        "plan-queue whisper" inside the developer-note │
                       │        untrusted-data boundary → hosted voice speaks   │
                       │        (whisperer StateDigest today; plans are new)    │
                       └────────┬──────────────────────────────▲──────────────┘
                                │ steering cue tokens           │ narration events
                                ▼                               │
   STATE OF THE WORLD (10 Hz) ─► MODEL A ─► act token ──► filter ─► body lane ─► sim / gateway
   sensors · owner track · DoA   (streaming policy;      (idle/twist/gaze/     (50 Hz)
   dialogue phase · cues ·        BM-1 family, ~5 M       emote/skill/hold)
   goal · local free-space ·      params; or a duplex
   plan step · blocked ·          backbone's act stream)
   last-minute event summary ·    ┃ narration token: nav.start/progress/blocked/
   plan queue                     ┃ replan/arrived/failed, plan.revised/queued/
                                  ┃ resumed, attend.sound/owner, none
   global plan ◄── executive (submit/suspend/resume/replace; receipts) ◄── graph planner
```

**What Model A outputs, precisely.** Two tokens per 100 ms frame: the act
(the existing codec) and a *narration event* from a closed vocabulary whose
every entry is backed by a product receipt or mission-block class. That
second token is the owner's "representation ChatGPT live can use": it is
small, discrete, timestamped, and — because each entry has a deterministic
witness — cannot claim an arrival that did not happen. Model A proposes
global-plan *updates* only as `plan.revised/queued/resumed` events that
the executive realizes; it never owns the plan, the base lease, or stop.

**What Model B is, precisely.** Two functions, not a second big model:
`steer(utterance, queue) → {revise, keep, queue, clarify}` realized through
the executive's existing verbs, and `narrate(events, queue) → whisper`,
rendered as untrusted data for the hosted voice, refreshed on every event
and at most every 2 s, with the vocabulary of claimable facts constrained to
the capability registry (the QEV-1 failure mode is structurally excluded).
The whisperer's own bench is the reason B stays deterministic where it can:
a local LLM judge in that seat *lost* to forty lines of state machine.

**The "last minute" and "global history".** The last minute enters A as a
bounded event summary (the last K narration events with age bins — the same
mechanism BM-1 used for owner history) plus the frame's own 12.8 s
attention window; global history is the executive's plan queue and the
owner model, which B reads and A receives as tokens. Neither is a raw
transcript in a context window.

**Where the trainable parts are, and where they are not.** Trainable: A's
act head (BM-1 showed a sequence model earns its place only where memory
is required — look-back — and loses to a reflex table on reactive
behaviours), A's narration head (MA-1 tests whether events are learned
right and on time), and, later, an act stream on a duplex speech backbone
(DS-1 measured it feasible on the desktop, not on the Orin). Deterministic:
steering realization, the plan queue, the safety filter, the whisper
rendering, the tool broker's admission.

**Relation to the parallel DMC-1 design in this folder** (another author,
same directive): DMC-1 is procedural-only (no Parcel runtime), with a task
ledger, a graph planner, an admission gate, and small trainable proposal
heads; this wave runs the *real* stack as the teacher and target (MA-1
clones it in the headless city; NAV-INT-1 measures it through the live
runtime). The two are complementary: DMC-1's H3 (receipt-grounded Model B)
and H6 (earned scope for a trainable A) ask the same questions on synthetic
histories that MB-1 and MA-1 ask on the product's own streams.

## 4. Experiments

Five pre-registered experiments (`DESIGN.md` frozen; a three-lens adversarial
design review produced `AMENDMENTS.md` in each folder — pre-run for MB-1 and
LIT-1, post-start and labelled for the others; a code-verified peer lens
from parcel-6c added the re-issue/tail-seam/governor facts). **Execution
record:** Opus executors ran all five from 15:4x; the account's monthly spend
limit killed all four remaining executors at ~19:30 (session reset). By then
MA-1, NAV-INT-1 and MB-1 had complete artifacts; LIT-1 had all its runs but
only stub result sections; CONV-1 had finished earlier. I finished solo:
NAV-INT-1's H-NI1a/b sections and LIT-1's analysis were written by me from
the artifacts; CONV-1's rows were re-run by my own hands. **A second,
foreign agent (Sol, the owner's other session) worked the same directive in
this folder in parallel**: it wrote `VERDICT.md` files into my three
experiment folders (17:31–18:38), rewrote the folder README into its own
assessment structure, and created eleven further folders (DMC-1/2, DSOAK-1,
MA-2, a LIT-1 grounding audit, product-evals, …) plus
`SOL_METHODICAL_ASSESSMENT.md`. My verdicts are the `VERDICT_FABLE.md`
files; where Sol's audits made checkable claims (MA-1's three blocking code
findings; LIT-1's 5/5 false terminal statements) I verified them in the code
and artifacts and concur. The owner should read the two assessments as
independent replications that agree.

| id | question | tier | verdict |
|---|---|---|---|
| NAV-INT-1 | interruptions on the shipped stack; a plan-queue policy | desktop-sim (MuJoCo city, live runtime, text) | **all three REFUTED**: admission 0.75 (amend-cue path 7/14), amended-goal success 0.39 vs 0.75 from rest, return 8/9 where reachable but path ratio 1.49, blind classifier 0.83 (queue 0.67, clarify 0.80); two live defects; authority disagreement 17/80 legs |
| MA-1 | a streaming Model A cloned from the real nav stack, closed-loop on held-out generated geometry | desktop-sim (headless city, real MJCF variants) | **REFUTED, and not promotion-quality evidence either way** (oracle leak into inputs, scorer window > goal mask, gold band changed post hoc — confirmed in code). Load-bearing fact: the **shipped navigator succeeds on 4.5 % of generated held-out layouts** (straight-line reference 21.7 %); Model A 3.7 %, reflex table 19.8 %; narration F1 0.50 vs 0.70 for rules |
| MB-1 | Model B narration/steering: grounded, timely, no invented actions; local vs hosted | replay + hosted-live ($2.21 of $5) | **REFUTED on the hosted model** (grounding 0.61–0.73, new-goal ack 0.44, completion 0.07–0.16, 45 invented-action flags of which a blind judge confirms 4; D arm truncated by the provider's daily quota); the scripted responder scores 1.00 on the same instrument and a **local Qwen-7B grounds 0.96** (CPU, 633 ms TTFT); two product facts: no whisperer class for plan acceptance, `KIND_REROUTE` dead code |
| LIT-1 | the well-lit loop: sim + runtime + Model B + fake/hosted voice, replayable | desktop-sim; hosted unmeasured | **harness CONFIRMED** (5/5 structurally identical receipt sequences, switch ≈ 0.32 s local, teardown proven, HTML replay) — **scenario REFUTED on the product**: the mid-route re-target fails `semantic_target_unreachable` every run, the robot does not move on re-issue, and the harness narrated "I've reached the bench" on a failed receipt (5/5, concurring with Sol's audit); hosted items `delivered: false` |
| CONV-1 | conversation rows: frozen scorer, duplex/acoustic gates, grounding bridge | replay | At this report's cutoff: **H-CV1a CONFIRMED** (25/174/0/66 identical), **duplex CONFIRMED** (7/7, 35.4 ms), acoustic runner crash, H-CV1c bridge delivered. Post-cutoff, the acoustic fix ran three full times at 5/9 gates; MB-1 D reached 2/120, not zero, while Q-minus-D remains unmeasured. |

## 5. Results and verdicts — what the day established

1. **Navigation generalization is the binding constraint, not conversation.**
   On procedurally generated held-out geometry the shipped stack succeeds
   4.5 % strictly (65 % on band entry); in the live MuJoCo city a mid-route
   re-target to the bench fails every time with `semantic_target_unreachable`
   and the robot parks; 17 of 80 scored legs disagree between the system's
   terminal and the independent arrival predicate. The owner's door → sofa →
   keys example cannot be executed by the product today for navigation
   reasons; the conversation layer never gets a true terminal to narrate.
2. **A Model A cloned from that teacher learns nothing usable** (3.7 %
   success; loses to a straight-line reference and to a frozen reflex table
   on every axis), and the run had validity defects that make even that
   number unusable as evidence about sequence models. The corrective step is
   a teacher/causality probe before any training (Sol's MA-2), on a fixed
   navigator.
3. **The steering half of Model B is measurable and currently fails on
   product mechanics:** amend-cue admission 50 %, no queue (resume intent
   consumed on commit → re-issue at 1.3–1.5× path), two live defects, a
   keyword classifier at 0.83 blind.
4. **The narration half of Model B is a wording contract, and free-form
   hosted wording fails it:** with the plan-queue whisper injected, the hosted
   mini grounds 0.61–0.73 and invents actions; a scripted responder scores
   1.00 and a local 7B 0.96 on the identical instrument. The product voice
   today cannot acknowledge a new goal or a reroute from receipts at all.
5. **The instruments now exist and reproduce:** the frozen conversation
   scorer (identical by my hands), the duplex gates, an interruption tier
   with a blind steering set, a receipt-grounded narration scorer with a
   coverage term, the LIT-1 loop with every hop timestamped and a replay —
   and a product-eval defect (the acoustic runner's negative-offset crash)
   with its fix recorded.
6. **Hosted spend:** $2.21 of the $5 cap (906 responses, gpt-realtime-2.1-mini
   text); the owner's own ledger untouched; the provider's daily request
   quota, not the cap, ended the hosted schedule.

## 6. Recommended ideas (each item closes with what the experiments said)

**R1 — Build Model A as a dual-rate object, and name the rates.** A 10 Hz
act-token loop (the existing frame clock; BM-1's ~5 M-param family or a
LiDAR-ray policy in the REASAN shape) and a 0.5–2 Hz plan lane. On the AGX
Orin a ≤ 2 B VLM is a 2 Hz lane with 1–2 frames and ~1 Hz with an 8-frame
memory; nothing language-shaped fits the 10 Hz loop. The two lanes are
joined by a LiveVLN-style contract in the act codec — a committed prefix
sized from measured sense + inference latency that the executive never
revokes, plus a revisable tail — so motion never stalls while the plan lane
thinks. Adopt a 400 ms block (LCM of 100 ms act, 80 ms audio, ~1 s plan) with
every lane filled by an explicit idle token and a one-block delay line for
the plan lane. MA-1 answered: on this substrate the learned loop lost to a reflex table and to a straight line, and the run's validity defects mean the sequence-model question is **open, not closed** — re-ask it after the navigator is fixed and MA-2's causality probe passes.

**R2 — The "state of the world" is a contract with provenance, not a
prompt.** Dense channels the product already produces (owner track, DoA,
dialogue phase, `base_busy`, task/receipts, localization health), LiDAR
tokens from the Mid-360 (tens to a few hundred), one annotated map image for
the plan lane, event tokens on the clock, and a bounded age-tiered memory
(a 12.8 s attention window + per-class last-60-s channels with age bins +
the executive's plan queue). Bounded beats unbounded in every ablation
found; global history is a ledger, not video. MA-1 A5 did not earn it (the history channel carried leaked labels; ablating it improved switching) — the question stands for MA-2.

**R3 — Model A's narration representation is a small closed vocabulary
with witnesses.** Two heads: witnessed `narr.*` (arrived / blocked / replan /
failed, each mapped to a product receipt or mission-block class) and
proposal `prop.*` (replan / resume-queued / abandon / clarify) that the
executive realizes. Terminal tokens carry **no authority**: only an accepted
receipt may say "arrived" — the false-arrival class is the one QEV-1 and
NAV-QUALITY both flagged. MA-1 A7: product-backed narration F1 0.006 vs research-only 0.75 — the witnessed vocabulary is the right idea and the model did not learn it; rules did (0.70).

**R4 — Model B is two deterministic functions plus a gate, not a second big
model.** `steer(utterance, queue) → {revise, keep, queue, clarify}` realized
through the executive's verbs (Hi Robot's cadence: re-run on every owner
utterance; Yell-At-Your-Robot's override switch), with "resume" as a
re-issue with lineage because the product's amendment transaction consumes
the parked intent; `narrate(receipts, queue) → whisper` pushed into the
hosted session as an unbilled conversation item (replace-not-append) with a
trigger table for robot-initiated speech that reuses the whisperer's band
discipline. The owner/addressee gate is local and two-tier (a ~1 MB
personal VAD every frame; per-utterance verification fused with DoA and
head-pose, planned at 10–18 % far-field EER) — hosted models cannot tell who
is being addressed. NAV-INT-1: steer 0.83 blind, queue = re-issue; MB-1: hosted free-form narration fails the contract, a local paraphraser over receipt-typed templates is the path (Sol's recommendation, concurred).

**R5 — The plan queue becomes a product seam.** One queue-record schema
{directive text, grounded goal, originating task id, admitted_at, status}
on the executive with DMC-1's fact taxonomy {accepted, running, blocked,
completed, failed, cancelled, resumed}; a snapshot per suspended goal; a
completed-steps ledger; explicit resume-by-re-issue. NAV-INT-1's two live defects (owner-referring amendment parks the robot; a held queue utterance must be cue-stripped), the 50 % amend-cue admission, and the arrival-authority disagreement are the first work items — before the seam. Two more, verified at HEAD by parcel-6c (`whisperer._diff` :1009 has no `nav_goal` branch; `nav_state` → `KIND_NAV_TICK` :1060 in `NEVER_BAND` :348; `KIND_REROUTE` declared :123, ALWAYS :322, `CRITICAL_KINDS` :381, exported :2454, never constructed — the only other "reroute" is `SocialProgressStateV1.REROUTE`, a navigation state no code maps to a `StateEvent`): a **plan-acceptance kind** fed from the executive's admission receipt, and a **constructed reroute fact** fed from `SocialProgressStateV1.REROUTE` — with one caveat that must be decided first: `KIND_REROUTE` is in `CRITICAL_KINDS`, so the first constructor of it would bypass the spend ceiling; choose its band before writing the constructor.

**R6 — Keep the hosted voice off every control path and design for its
failure modes.** Async function calling so acknowledgement and motion share
a turn; robot facts pushed as small text items; a fast local barge-in
reflex (speech_started → soft hold) with a slow decision; session rotation
at a natural pause well before the 60-minute cap with a byte-identical
instruction prefix; WebRTC with a jitter buffer that covers Starlink's
+74 ms period spike; the 10 Hz loop never waits on the link. LIT-1: local switch ≈ 0.32 s; hosted narration unmeasured (items not delivered on the live lane; provider quota) — the loop is ready to measure it once the injection door is fixed.

**R7 — Define Parcel's Interrupt-Nav benchmark and report it honestly.**
No external benchmark scores spoken mid-task instruction changes on a moving
robot. Keep NAV-INT-1's additive tier (never the frozen v1–v4), stratify by
amend-cue vs explicit-directive vs queue phrasing and by trigger fraction,
score the switch window at ≥ 10 Hz, tally authority disagreement as its own
row, report pass^k with CIs, and add EchoChain's three failure modes
(inertia, amnesia, displacement) as named rows. For conversation, keep the
66-flag corpus scorer as the pin, join flags to events (CONV-1's bridge),
adjudicate blind, and correct every LLM judge for chance.

**R8 — The well-lit harness is the deliverable that compounds.** LIT-1's
loop (sim + runtime + Model B + fake/hosted voice, every hop timestamped
with a provenance column, replayable to HTML) is the instrument every later
claim runs through. Its real-swappable hops — mic → XVF3800 + ASR, voice →
hosted, body lane → gateway protocol v1 fake gateway — are how sim-to-real
is approached one hop at a time; an LLM owner-simulator ranks variants but
only recorded owners set an acceptance bar (PARTNR: 0.30 vs 0.91).

**R9 — Gateway and safety facts to build into the seam now.** The Go2 holds
the last `Move` for 1 s: the gateway owns a 200–300 ms watchdog that zeroes
velocity; clamp and slew-limit in the act-token decoder; a velocity-layer
shield (REASAN-shaped, 180 rays, sub-ms) inside the 10 Hz tick; one writer
thread for all sport calls; never write from a DDS callback.

**R10 — What to train, in what order, on this desk.** S1 clone the real
navigation stack in the headless city on real MJCF geometry variants (MA-1);
S2 the owner table and steer rules from NAV-INT-1's traces; S3 the narration
head against receipts; S4 the LiDAR-ray policy + shield in MuJoCo with the
Go2 twin; the duplex speech backbone (DS-1) stays a desktop research track.
Every stage ends in a shadow-mode log behind `DuplexFrameConsumer`, never in
actuation; physical motion remains NO-GO.

## 7. What is NOT proven, and the record for the integrator

Nothing physical: every row is desktop simulation, replay, or one hosted
provider on one date; no physical audio was captured (post-cutoff, the fixed
synthetic/null-sink acoustic runner passed 5/9 gates three times); no Orin; no
Go2. MA-1's numbers are not evidence about sequence models (see its verdict);
MB-1's hosted D arm stopped at 2/120 (provider quota), so the Q − D contrast is
unmeasured; LIT-1's hosted tier delivered no items; NAV-INT-1 is
n = 40 on four landmarks with text commands. The literature's 2026-dated
sources were verified by finder + verifier agents only.

**Execution record.** Executors killed by the account spend limit at ~19:30
(after 18:27 the day before); MA-1/NAV-INT-1/MB-1 artifacts complete, LIT-1
sections and NAV-INT-1's H-NI1a/b written by the verifier from artifacts;
CONV-1 rows re-run by the verifier. Foreign, live, same-directive work by
Sol in the same folder: its `VERDICT.md` files, README rewrite, eleven
folders and `SOL_METHODICAL_ASSESSMENT.md` are the owner's and were
never edited by this wave; my verdicts are `VERDICT_FABLE.md`. Shared-wave
month-to-date hosted spend was about $2.21; MB-1's completed-Q increment was
$1.32843624 (ledger `~/.cache/parcel-0e/wave20260829/spend.jsonl`). No
product code touched; no git writes; the index line added at close:
`research/README.md` → "- `20260829/FLUIDITY_REPORT.md` — nav + conversational
fluidity wave (Model A/B: NAV-INT-1, MA-1, MB-1, LIT-1, CONV-1; verified
literature; Sol's parallel assessment in the same folder)."

## Post-cutoff evidence addendum

These results completed after the historical wave above and supersede any
conflicting readiness sentence without rewriting that wave's authorship:

- **MA-2:** the causal substrate passed, but teacher/reflex/direct each solved
  198/198 held missions while every snapshot/16-frame learned seed solved
  0/198. Offline row accuracy did not survive closed-loop distribution shift.
- **DSP-2:** 580 held episodes; S2 and S3 each contacted in 25/145 and all four
  hypotheses were refuted. S3 increased false blocking 19.97% versus S2.
- **DMC-4:** two identical 1,824-mutation runs and 256/256 corruptions support
  the source-level owner-authored journal → authenticated narrative-event
  transaction. A later 26-test hardening step wires a process-local,
  journal-only observer into normal runtime and emits no speech. Post-review
  hardening preserves exact available authority/deadline lineage and rejects
  expired queued frames; commit-time timestamp, live authenticated session,
  persistent cursor, provider/audio, and authoritative separate-child resume
  lineage remain absent.
- **LHO-1:** in four 5,940-arm-episode scalar runs, a guarded latency-sized prefix
  reduced waiting 91.93% and visible gaps 91.02% versus blocking with zero
  authored stale/safety violations. Its additive supplement verified C/D as
  distinct sequential local processes and passed ten provenance-tamper checks.
  It has no 2-D, learned, dynamics, braking, Orin, remote-attestation, or
  physical scope.
- **MJLAB-1:** upstream clean installation failed. With explicit pins, official
  Go2 MuJoCo-Warp ran 5,933–6,199 environment-steps/s and a 4,608-step PPO/
  checkpoint/ONNX plumbing smoke; it did not train a useful walking policy.
- **SOS-1:** maintenance exposed and repaired READY-before-handler ordering and
  evaluator defects; two parallel and two sequential current-source 256-case
  source/fake-gateway runs now support a distinct stop-only software
  UID/principal. No real STOP input, physical E-stop, Go2, Orin timing, or
  braking evidence exists.
- **Acoustic v1 audit:** the historical 5/9 gate score remains, but none of its
  four red values validly measures the capability it names. Exact inspection
  found premature commits in all three 750 ms pause fixtures and one incomplete
  turn. Direct PortAudio abort during device drain and a post-open worker-write
  clock now pass guarded regressions; mounted audio/AEC and audible timing remain
  red.

These additions strengthen the architecture and its testability. They do not
change the physical-motion verdict: **NO-GO**.

## 8. Continuation (20:13–21:xx EDT, after the owner asked for the verdict)

Two bounded probes were pre-registered, run and verified after §1–§7 were
written; the owner's verdict document is `VERDICT_RESEARCH_QUESTION.md`.

- **NAV-GEN-1** (`nav-gen-attribution-1/`, 5,510 headless episodes, 0
  collisions): §1's "4.5 % on generated geometry" was over-attributed. One
  plain directive on 30 generated scenes succeeds **0.651 strict / 0.689
  band-entry** (reproduced 530/530 rows); MA-1's plain-episode band entry is
  0.775. **MA-1's 0.045 was a harness artefact** — its 5-frame-settle gold is
  never observable because the loop breaks one frame after `done()`
  (erratum in `model-a-stream-1/VERDICT_FABLE.md`). Generated
  scenes are *easier* than the frozen block (0.275). Failures: 68 stalls
  (`navigation_no_progress`, route still planned), 44 unreachable, **42
  false arrivals — every one from "the crosswalk" resolving to the demo POI
  table's hardcoded `crosswalk_a`** (`configs/navigation/cities/demo_pois.yaml:38`)
  on scenes where no such point exists (median 3.25 m off, worst 7.17 m).
  Clearance is not the lever: `map_safety_margin_m` is inert in effect on the
  shipped profile — read, but it cannot bind (the planner is commissioned from the brake ring,
  `navigation/pipeline.py:1108-1120`, inflation 1.02 m — NAV-CORE's 0.42 m
  is pre-A2), and sweeping the brake 0.80 → 0.32 m buys +2 points. → R1's
  "clearance/termination re-freeze" becomes: **fix terminal stopping, the
  stall watchdog and place grounding; do not tune clearance.**
- **MB-2** (`model-b-contract-2/`, $0, 0 hosted calls): a receipt-typed
  speech-act contract (9 acts, templates) scores grounding 1.000 / coverage
  0.969 / 0 invented / 15/15 capability refusals at 0.4 ms, reproduced from
  a scratch copy; a local Qwen-7B paraphrase behind a post-condition
  checker falls back on 32/180 turns (0.178) and, ungated, **deleted the
  "I have no camera" refusal on 15/15 keys turns while MB-1's grounding
  metric scored those turns 1.0** — grounding is blind to omission. The
  naturalness preference is unmeasured (position-biased judge). → R6's
  "local paraphraser" becomes: **ship templates; a paraphraser only behind a
  required-statement checker.** Adversarial panels (6 + 5 refuters, 1 reproducer, 2
  critics) refuted one of eleven claims (the MA-1 script attribution,
  adopted); caveats in each VERDICT.md.
