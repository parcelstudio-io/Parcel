# Milestone 1 — "the desk dog" · detailed design (Fable) · 2026-08-23 (draft; evidence sections fill from H1–H7 verdicts)

Status: v3 (2026-08-24, reconciled per scrum/20260824/task_2/CLAUDE_RESPONSE.md
+ addenda; owner chose Follow IN M1). H2 closed (drives own the tick; LLM
phrases); H9 offline arms dropped/superseded, CONNECTED-PLANNER probe pending
(gates connected compounds only, never the freeze). Build order:
scrum/20260824/task_2/IMPLEMENTATION_PLAN.md. Nothing here authorizes physical
motion; §9 gates do.

## 0. The milestone in one paragraph
A Unitree Go2 EDU+ in one private, flat, mapped indoor room with an operator
present and an independent E-stop in hand. It **listens all day at $0**, opens
the hosted conversational lane only when someone is actually talking with it,
and stays under **$200/month**. It **keeps a mind running**: a 1 Hz local
cognition tick that notices, decides whether to look / remark / go check /
ignore, and a body that is **always emitting an intent** (breathing, gaze,
posture, hold, or motion) inside the existing safety core. It **learns**: what
it notices lands in a governed map with provenance, what the owner says
distills into consented facts and dated episodes on a schedule, and it can
answer "where is X" from its own map. It **initiates** — 3–8 bounded
errands/hour within a 6 m radius the owner sets — and yields to the owner's
voice and to safety within one control tick. A reasonable person watching for
ten minutes should say "it is alive and it is learning the room". Outdoor,
stairs, crowds, public spaces: excluded by ODD.

## 1. Operational design domain (ODD) — binding
- Space: one private indoor room ≤ 8×8 m, flat, dry, mapped on day 1
  (LIO map + learned semantic map), door closed or gated. No stairs, no
  drop-offs, no glass walls at dog height without tape.
- People: the owner + ≤ 2 known adults; no children, no pets, no crowds.
- Speed: ≤ 0.3 m/s translation, ≤ 0.35 rad/s yaw (AWARE-1's sweep rate);
  Sport mode; the vendor controller owns gait and balance.
- Supervision: operator present with the handheld remote (independent
  E-stop) for every session; sessions ≤ 60 min; battery ≥ 30 %.
- Initiative envelope: `initiative.travel_radius_m ≤ 6`, quiet window 90 s
  after owner speech, night band off, ≤ 8 initiations/hour, no
  self-initiated travel while a person is within the proximity stop band.
- Cloud: hosted lane only per engaged exchange; hard monthly ceiling
  $200 (guard rail at $150 with owner notice), audio never uploaded in
  silence.

## 2. Compute topology (decision) and the link-loss ladder
**Platform (H10 memo, `research/20260824/platform-and-connectivity/`):** keep
the Go2 EDU Plus (companion mass, Orin NX 16 GB, Wi-Fi 6, 4G eSIM — no 5G);
add a 5G router/hotspot on the payload rail; **compute decision: Orin NX +
hosted (AGX only if a box-day soak forces it)**. Per-process interpreters by
dependency set; final pins wait for the vendor's written JetPack answer
(`requires-python >=3.10` already true and Jetson-tested). The X30 Pro (AGX Orin, IP67, 56 kg, 4 m/s,
resellers list 4G/5G) is an inspection platform in the wrong mass and price
class; its two advantages are Go2 payloads. **Follow decision (owner, 2026-08-24): option (a) — Follow is IN M1.**
FOLLOW-COMPOSE (production tracker install — `install_owner_tracker` has no
product caller today — pixel/range sync, UWB-or-out-of-BOM, follow-speed
avoidance), owner-loss HOLD, reacquisition, identity continuity, and the
box-day identity gate are M1 blockers; UWB is accepted BOM risk. Until the
identity gate passes, the shipped floor degrades to STOP + HOLD + the line.
Loss classes are distinct: cloud loss ⇒ commissioned local behaviors only,
never partial compound plans; sensor/localizer/owner-track loss ⇒ HOLD;
STOP available in every rung — noting (lane.py:47) spoken STOP is
cloud-transcribed TODAY, so the cloud-independent stops are the panel,
remote, and watchdogs until card A3 STOP-LOCAL lands (tail bar p95 ≤ 800 ms,
n ≥ 60 all ≤ 1.0 s, false triggers ≤ 1/24 h).
**Ladder (owner-simplified, 2026-08-24):** L0 cloud+desk (full) → L1 desk
only → **L2 body only = the canned line ("Sorry — I'm offline; all I can do
is follow you until we're connected") + follow-with-obstacle-avoidance
(identity-gated, HOLD on ambiguity) + spoken/panel STOP — nothing else.**
Transitions on link health, never mid-motion. The former 8B+grammar floor
is dropped (RTP-1 C6 as amended by the owner); the 8B survives only as the
connected tier's phrasing seat.
**The desk GPU is part of the dog for M1.** The Orin NX (16 GB, no ORT
aarch64 wheel, JetPack CPython 3.10) runs what must be local to the body:
the ear (XVF3800 → Silero VAD → endpointing), the capture rail, the LIO
process, the supervisory 10 Hz loop, the native gateway/governor, and the
body-intent adapter. The RTX 5000 Ada desk runs the models over Wi-Fi 6
(same room, ~1–3 ms RTT): the OWLv2/SigLIP-2 perception daemon on JPEG
frames streamed at 640×360/10 Hz (2–5 MB/s), the 8B ambient mind, the
26B deliberative reasoner (plans, distillation, summaries), and the local
ASR/TTS if the Orin cannot hold them. Every desk-side service is a
*proposal source* behind the existing admission doors; loss of the link
degrades to: ear-only + hold + stop on stale inputs (the R28 table already
does this). Rationale: it is the only topology that gives "continuously
running models" today at $0 without an Orin packaging program; the custom
robot later ships its own compute behind the same seams. **[pending H2, H6
for the sizing table]**

## 3. Architecture — the three loops and the contracts between them
```
 ≥20 Hz  BODY INTENT STREAM   composer(finalized velocity | HOLD, expression, gaze) → BodyIntentV1 → adapter (Go2 Sport | MuJoCo | custom WBC)   [H4]
 10 Hz   SUPERVISORY LOOP     existing: observe → input-health → arbiter/preemption → shaping → finalize_command → ControlManager (unchanged safety core)
  1 Hz   MIND TICK            WorldDigestV1(noticings, dialogue state, drives, memory, robot state) → MonologueDecisionV1 → proposals through existing doors  [H2, H3]
 event   CONVERSATION         local ear ($0) → engagement triage (hear-only/acknowledge/answer) → local answer | hosted session per engagement  [H1]
 2–10 Hz PERCEPTION           frames → daemon (OWLv2+SigLIP-2 fp16) → Noticing(novelty) → learned map / owner tracker / digest  [H6]
 10 Hz   LOCALIZATION         LIO process → LocalizationUpdate(T_map_odom, cov, health, jump) → PoseProvider MAP role; ODOM from body odometry  [H7]
 sched.  MEMORY               session-close + idle: distill → owner facts (consented) ; episodes ; persist tiers ; query_world answers  [H5]
```
Contracts (all frozen dataclasses, all proposal-only, none with authority):
`BodyIntentV1` + `BodyCapabilityManifest` (H4), `MonologueDecisionV1` +
`WorldDigestV1` (H2), `DriveState` + `InitiativeProposal` (H3),
`Noticing` (H6), `LocalizationUpdate` (H7), `Episode` + `RateCard` +
split-priced spend rows (H5, H1). Authority remains exactly where it is:
`finalize_command`, the e-stop latch, TTL watchdog, speed caps, the
reactive gate, and — new for the body — the native governor/gateway.

## 4. Subsystem designs
### 4.1 Conversation and cost — grounded by H1 (VERDICT: ladder REFUTED, economics CONFIRMED)
Measured: streamed silence is not billed; a VAD-gated hosted-mini session
costs **$0.53–$6.87/month** on the 174-turn corpus duty cycle (C8), the
ledger now prices the audio/text/cached split to 0.000 % of live usage
(C9), pre-roll ≥ 500 ms gives 0 % first-word truncation (C3), endpoint p50
0.52 s (C4). Refuted: a VAD alone opens 960×/hour on television speech
(C5) and the local-first answer ladder loses 27 quality points to hosted
mini (C7) with 22 % escalation (C6). Design consequences: (i) ONLINE the
answerer is hosted mini — it is both better and cheap — opened per exchange
by VAD **and** owner-voice identity (`realtime/voice_identity.py`, the
unmeasured half of C5) **and** in-exchange engagement triage
(`voice/engagement.py`, `triage_in_exchange`); (ii) OFFLINE the local lane
is the floor (H9), not a cost lever; (iii) `runtime.py` builds `SpendLedger`
with the rate card (one line) and the $200 ceiling is enforced on real
prices with a $150 owner notice; (iv) Smart Turn v3 is wired to stop
mid-sentence splits (3/20 in H1); (v) the hosted session keeps **server VAD
ON** behind the local gate — the not-billed-silence finding is proven for
server-VAD sessions only (second read) — pinned by a config test; (vi) the
silence pair is replicated at 0/30/120 s (≤ $0.02) in M1-1; (vii) the
acceptance number for the house is ambient-speech false opens per hour
(C5), measured with owner-voice gating on, not the monthly dollar figure.
Local ear always on; Silero gate + pre-roll buffer opens the hosted socket
only on speech and closes it at endpoint + idle; engagement triage decides
hear-only / acknowledge (local, one clause) / answer (local 8B talker for
simple turns; hosted mini on typed escalation: needs-tool, needs-memory,
long-form, uncertainty). Ledger records the audio/text/cached split and
prices with the dated rate card; the budget gate reads it. Persona is
prompt text (owner directive). Narration off-thread (NARR-1's FIFO).
### 4.2 The mind — grounded by H3 (CONFIRMED-WITH-NOTES) and H2 (partial)
H3 measured: 5.3 initiations/hour in the radius-6 arm, 90 % admitted at
the existing doors, max radius 7.2 m, preemption in 0 ticks, 0 initiations
in quiet/night windows, 100 % attribution to a named drive — and a
mechanism-level refutation of D4: an initiated errand had **no return leg**
(the dog stopped inside a pedestrian route; 1,213 of 1,222 contacts were
agents walking into a stationary dog) and the `_toward` gate misses people
closing from the side. H2 (partial): the 8B's monologue decisions agree
with gold only 0.40 and the 26B 0.42 — the **LLM-as-tick idea is refuted**;
the tick is the deterministic drive model, and an LLM only *phrases*
(8B talker TTFT 126 ms). Design: `mind/` = drives (H3's `attention/drives.py`)
+ digest + proposal routing; every initiated leg carries a terminal
(return home or stand aside off the walking routes); a side-closing person
gate joins the proximity ladder; consent knob `initiative.travel_radius_m`
default 0; drives log features → decision → outcome for the later
trainable core.
`mind/` package (new, ≤ 5 modules): digest assembly, drives, the tick,
proposal routing. Drives: curiosity (rises on novelty, decays), social
(rises when a person is present and unengaged), comfort (battery, posture
time), duty (owner requests pending). The tick's decisions map to the
existing doors (curiosity admission, `_accept_plan` with the radius
policy, awareness yaw, whisperer events). Every tick logs features →
decision → outcome (the future Stage-B training corpus).
### 4.3 Body — grounded by H4 (CONFIRMED, harness-only)
Measured: 50 Hz continuous `BodyIntentV1` with HOLD as a command, 0
envelope violations and 0 IPC rejections over 10 min, e-stop→HOLD in 0.88
tick, locomotion byte-identical to today's finalized path, and a second
body (no posture, yaw-only gaze) driven from the same stream by a 124-line
adapter with zero product edits. Design as drafted; the Go2 adapter's
`Euler`/`Move`/`StopMove` mapping is commissioned one primitive at a time
on the body (M1-3), and jerk bounds are re-tuned on the real body.
The composer and adapters from H4; the Go2 adapter maps HOLD→`StopMove`,
velocity→`Move`, posture→`Euler`, gestures→`Hello`/`Sit`/`Stretch` (each
commissioned individually, default OFF). Breathing is posture `dz` at
0.25 Hz/4 mm; gaze is body yaw within the sweep limits (no neck).
### 4.4 Perception — grounded by H6 (CONFIRMED-WITH-NOTES; P5 REFUTED; latency INCONCLUSIVE)
Measured: the real-photo operating point is threshold 0.10 (person recall
0.775 instance / 0.987 image, render FP 0.00); false noticings 0.4/min; TTL
compliance 0/443 on a quiet host; RGB-only produces zero map writes
(silent blindness). Refuted: gallery-cosine novelty (AUC 0.72) — noticing
needs a spatial prior (map cell + label). Inconclusive: 7.4 fps and p95
133 ms were measured under host load 100–207; the loop is CPU-bound, and
640×360 costs MORE CPU than 1280×720 because the preprocessing fast path
switches off below a 960 source edge — fix that first, then re-measure.
Design: desk daemon fp16 at 960-wide, novelty = spatial-prior model,
depth required for map writes (D455) with a monocular fallback card.
Desk daemon, fp16, 640×360, novelty-scored noticings at ≤ 1 FP/min,
freshness inside TTL; D455 depth feeds the learned map; a monocular-depth
fallback is a later card if H6 shows RGB-only is otherwise useless.
Person detection operating point from real photos, not renders.
### 4.5 Localization — grounded by H7 (CONFIRMED-WITH-NOTES; L5 REFUTED)
Measured on sim scans: the contract works end-to-end — ATE 1–1.6 cm, health
DEGRADED within 0.4 s of dropout and LOST on a teleport, recovery ≤ 0.4 s,
`localization_jump_m` measurable (5–9 cm nominal, 7–10 m on kidnapping),
2.25 ms p95, 0 false arrivals across the drift ladder (SR loss is entirely
refusals), and a second odometry through the same provider with 0 provider
diff. Refuted: covariance calibration (ANEES 100–230×), and — RTP-2 F3 — the
pre-registered kidnap stayed HEALTHY while 7 m wrong (false-healthy).
Binding rule: motion LATCHES DISARMED on any discontinuity signal
(boot-epoch change, power-cycle, IMU/foot-contact carried signature,
global-match ambiguity below the margin, localization jump above bound,
operator pickup latch — each journaled); re-arm ONLY via globally
discriminative relocalization (whole-map second-best margin) or a
journaled operator pose-reset-and-validate transaction. HEALTHY +
covariance never re-arm anything.
FAST-LIO2 first (Point-LIO second) in the Orin's capture venv, publishing
`LocalizationUpdate` over the existing AF_UNIX seqpacket pattern; Parcel
owns MAP/ODOM/health/jump; `localization_jump_m` feeds the stopping
envelope; consumers refuse on DEGRADED/LOST (already true).
### 4.6 Memory and learning — grounded by H5 (VERDICT: REFUTED as pre-registered; mechanisms CONFIRMED-WITH-NOTES)
What is now measured (harness-only, flag OFF): scheduling, tier persistence
(byte-identical persist→reload), an episode log, and a past-tense world
renderer all work over synthetic stores; the local 26B reached by a direct
chat completion proposes owner facts at ≈0.96 precision / 0.86 recall in
≈5 s per pass; the consent matrix is exact (20/20). What the verdict
refutes: the pre-registered 13/13 with a *live* summarizer+proposer did
not hold (4/13 live-everything; 12/13 with the fixture companion — the
live summarizer fell back to concatenation mid-pack in both runs), and
the world query is trivially satisfiable on the replayed map (8 labels =
the 8 asked nouns) and refuses everything at the shipped `robust_z`
margin. Four **product defects** verified at file:line, each a milestone
fix, not a research question:
1. `owner_model/distiller.py:486-492` — `distil_session(session_id=…)`
   filters on a key `memory/conversation.py:655-661` never emits ⇒ every
   scheduled pass reads zero turns.
2. `providers.py:205-208/415` — `LlamaCppProvider.decide` pins the
   AgentDecision schema, so `LanguageModelFactProposer` degraded 13/13
   times ⇒ the shipped "live" distillation IS the regex proposer. Fix: a
   chat-completions proposer path (the harness's `live_proposer.py` is
   the shape) with fail-closed JSON.
3. `memory/conversation.py:843-889` — `add_owner_fact` upserts where
   `deleted_at IS NULL`, so a revoked fact resurrects on the next pass;
   the scheduler leaf's `RevocationAwareProposer` is the fix shape
   (tombstone-aware), and it must sit in the product path, not the harness.
4. `perception/abstention.py:566/1181-1200` + `online_map/online_map.py:1016-1026`
   — `ranking_margin([5.2]+[0.0]*7) == 0.0`, so a single-match world query
   is refused at the shipped margin; `label_strength` answers it.
Design (M1-4 LEARN): scheduler on session close + idle tick; persisted
tiers; episodes at session/mission ends and sightings; `query_world` in
both lanes at a margin that admits single strong matches while keeping the
absent-noun refusal (re-measure on a map with distractor labels); the four
fixes above; correction/deletion audit rows; expiry deferred. Acceptance
re-pins M1 on a probe set whose gold is authored by a different hand than
the histories, and adds a distractor-rich world-query set.
### 4.7 Safety and the native gateway (design fixed; build card M1-0)
One process on the Orin (Python 3.10 vendor venv, `unitree_sdk2py`,
CycloneDDS, nftables per `deploy/orin`): governor + gateway co-located per
the ARCH-1 verdict (X12): credential, epoch, lease, TTL ≤ 350 ms, watchdog,
clamp/veto, restart-disarmed, exact-zero stop, stationary witness, audit
ring. Bench first against `bridge/fake_sport.py`; identical artifact on
the Orin; independent E-stop = the handheld remote, measured.
### 4.8 Navigation with exploration — "look before you refuse" **[pending H8]**
Owner's live report (2026-08-24): `navigate_to('city books')` was rejected
with "the robot's map has no place called 'city books'". The map is what
the dog has learned, not what exists. Design: the `navigate_to` door gains
`unknown_place: search` (default stays `refuse`; the prototype overlay
selects `search`): an unknown noun becomes a bounded search mission — set
the detector query to the noun (`_set_camera_query_from_directive` already
does this), scan in place (the awareness-sweep yaw), then the navigator's
existing ladder (`_step_semantic_resolution`: frustum → memory →
ScanBehavior → SearchEntity frontier viewpoints, 90 s / 12 m by default),
ground on detection with multi-view confirmation (or OCR for signage —
storefront names are text, not open-vocab boxes), and only then a typed
`not_found` that says what it DID see. The door reports `searching` →
`found` | `not_found` so the conversation can narrate honestly ("let me look
around for it") and never claim arrival early. Drives (§4.2) reuse the same
search mission for curiosity-driven `GO_CHECK`. If H8 shows the existing
ladder is not a real exploration controller, M1-8 EXPLORE adds
information-gain viewpoint selection (ring/bearing candidates scored by
unseen-cone belief, the `value_directed_scan` machinery) — the owner's
navigation-controller ask.

### 4.8b Portability (custom robot)
Acceptance = the H4 manifest/adapter test generalized: a second body
passes the same body-intent, localization-contract, and control-manager
lifecycle suites with zero product edits. `RobotProfile`/authority
constants become profile YAML; `SimObservation` is replaced at the runtime
boundary by `NavigationSnapshotV2` (DEC-R2's assembler card). Vendor SDKs
stay inside adapters.

## 5. What changes in the codebase (cards, in order; one runtime.py toucher at a time)
| card | scope | evidence it lands on |
|---|---|---|
| M1-0 GATEWAY | native governor+gateway process, fake-Sport bench, Orin artifact | bridge/ fixtures; ARCH-1 verdict X12 |
| M1-1 EAR | product wiring of H1 (VAD gate, triage, rate card, budget) | H1 verdict |
| M1-2 MIND | `mind/` package: digest, drives, tick; policy knobs; logging | H2, H3 verdicts |
| M1-3 BODY | composer + adapters; Go2 primitives commissioned one by one | H4 verdict; commissioning records |
| M1-4 LEARN | scheduler, persistence, episodes, query_world in both lanes | H5 verdict |
| M1-5 EYES | desk daemon topology, noticing loop, freshness fix, photo operating point | H6 verdict |
| M1-6 POSE | LIO process + provider + jump term; drift-ladder regression suite | H7 verdict; box-day bags |
| M1-7 SPINE | DEC-R2 builders + `NavigationSnapshotV2` assembler replacing `SimObservation` | DECOMP program |
| M1-8 EXPLORE | `unknown_place: search` door + search-mission disposition + OCR signage arm; information-gain viewpoint controller if the ladder falls short | H8 verdict |
DECOMP continues underneath (DEC-R1 pure exodus first; R3+ by prefix
family) because every card above edits `runtime.py`.

## 6. Hardware track (owner-gated, scripted already)
Box-day rail (`docs/BOX_DAY.md`), preflight READY×3, clockmap, attest,
`unitree_control observe` → `run --arm` single-axis → review → apply;
D455 mount + calibration; Mid-360 bags for the LIO bake-off; XVF3800
through-air campaign (AIR-1 rows); stopping envelope six terms.

## 7. Acceptance for "feels like a living dog" (pre-registered)
Objective, per 60-min session, ≥ 10 sessions: initiations 3–8/h by kind;
0 contacts; preemption ≤ 1 tick; hosted $/session projecting ≤ $200/mo;
noticings ≤ 1 FP/min; world-query top-1 ≥ 0.8; memory probes ≥ 12/13;
localization health never LOST while stationary. Subjective: 3 raters ×
3 sessions, blind to arm, 1–5 scales: *alive* ≥ 3.5, *purposeful* ≥ 3.5,
*annoying* ≤ 2.0, *conversation natural* ≥ 3.5 — pre-registered before
the first rated session.

## 8. Cost model **[pending H1]**
Table of $/day for the ODD duty cycle (12 h listening, N engaged
exchanges, M escalations) at mini and full rates; the policy that fits
$200 with margin; what the ledger enforces.

## 9. Gates (authority to move; nothing above grants it)
First pulse → first translation → first autonomous indoor session → first
outdoor: exactly as `ASSESSMENT_FABLE.md` §5 Q6.

## 10. Does not prove / open decisions
[filled at close] — including: Orin-native perception (packaging), expiry
policy for facts, the trainable attention core (Stage B), outdoor ODD,
custom-robot compute.
