# Generalized companion autonomy — research synthesis

Date: 2026-08-26
Author: Sol
Evidence base: repository audit, deterministic desktop simulation, offline
replay, local RTX 5000 Ada model inference, literature/official documentation
review. No Go2, AGX Orin, ROS 2 hardware graph, mounted audio, or physical
motion was available.

## Bottom line

Parcel has the beginnings of a defensible companion architecture, but it is
not ready for motion-enabled mounting. The shortest path to a capable dog is
not an end-to-end model that emits gait commands. It is a hierarchical system
that lets models improve language, semantic decomposition, social choices,
cost/risk prediction, and terrain policies while deterministic local
components retain identity, consent, evidence freshness, completion, safety,
and actuation authority.

The highest-priority build is a **same-contract Go2 simulator loop**:

1. generate one effective capability manifest;
2. compose the disarmed product runtime through the existing Unix gateway;
3. retain the integrated official Go2 MJCF asset pack and attach the native
   Unitree MuJoCo low-level SDK2/DDS simulator boundary through an explicit
   simulated `SportPort` or high-level-to-low-level bridge, while preserving
   the sole-writer gateway contract;
4. add typed mission/progress state, then develop an H2b completion authority
   with separately calibrated identity, reset, and terminal-geometry evidence;
5. generate immutable train/dev/frozen-test campaigns; and
6. promote candidates only through signed, replayable eval gates.

This makes simulation useful immediately while preserving an honest boundary:
simulation chooses candidates; only staged physical evidence authorizes the
robot.

## What was implemented today

- Added `si-companion-v4`, then retained its relationship wording in the
  current `si-companion-v5`: Parcel is a warm, continuing companion friend by
  default, supports the owner across turns, uses only recent dialogue and
  consented memory, and honors quiet/privacy/distance/revocation. “Stick
  around” explicitly excludes surveillance, guilt, dependence, and
  unrequested travel. v5 and `di-companion-v2` additionally treat labeled
  runtime fields as data and quote/delimit free-form owner/history/sensor
  blocks as untrusted rather than instructions.
- For the local structured `next_action` lane, instructed the model to use
  only `runtime_context.available_social_skills` and to emit `null` rather than
  substitute. Local admission now independently enforces that same tagged
  allowlist and derives explicit-command authority from deterministic parsing
  of the owner transcript, never from the model-authored trigger label. Hosted
  Realtime uses its separately generated `play_gesture` enum and tool broker.
- Preserved exact v1-v4 system-instruction rendering and added frozen v4/v5
  persona assets and digest/parity tests.
- Declared the simulator carrier clock at the synchronous runtime ingress and
  mapped it to host monotonic time there. A real `HeadlessCityWorld` regression
  now proves time-zero simulation evidence is initially usable and still
  expires after its 250 ms freshness limit.
- Fixed the NAV_INSTRUCT scene-split CLI so research output goes to the
  requested directory rather than the tracked default report.
- During the research phase, added five reproducible research packages,
  including an isolated local
  research-data-plane design, navigation/liveness refuters, and a 475-episode
  dynamic-social-progress experiment. No product exporter, cloud plane, or
  social-motion authority was added in that phase.

### Subsequent P0 implementation tranche

After the research decision, the highest-priority interfaces were implemented
as a deliberately bounded `SIM-CONTRACT-1` P0 tranche:

- a canonical, deployment-bound capability manifest whose available entries
  can only be regenerated from process-local authenticated commissioning
  evidence; optional runtime and voice-agent consumers use the exact manifest;
- strict dialogue, embodiment, consent, operator/owner evidence, action
  admission, authenticated receipt, repeat, memory, opportunity, and terminal-
  claim contracts. These reducers grant no motion authority and are not yet the
  complete live multi-turn session/executive path;
- a registered, permanently disarmed control adapter composing the normal
  runtime through the real Unix gateway boundary to fake Sport in desktop
  tests. It has no `acquire` or `command` call and does not implement native
  Unitree SDK2/DDS, vendor motion, Orin, or physical feedback;
- an isolated, default-disabled H2b completion latch plus a new 600-case x
  three-arm holdout. H2b was **REFUTED** at 113/120 alias recovery versus the
  preregistered 114/120 gate and remains outside the navigation pipeline;
- a default-off local research package with a dedicated typed spool,
  deterministic bundles, local retention/revocation cascade, attempt-byte
  accounting, and mandatory injected verifier seams. It contains no real
  AES/KMS, network, object-store, Starlink, or remote-deletion provider; and
- an immutable simulator scenario/split registry and proposal-only promotion
  gate. Failure mining cannot consume frozen test, safety counters are
  fail-closed, human review/signature/rollback are digest-bound, and no result
  can activate a candidate.

The exact code/evidence ceiling and remaining work are recorded in
`IMPLEMENTATION_REPORT.md`. This tranche does not change the physical
motion-enabled `NO-GO` decision.

## Current quality ledger

| capability | fresh evidence | decision |
|---|---|---|
| Realtime `si-companion-v5` relationship/data contract | deterministic rendering/digest/freeze/package parity only | Prompt version accepted; no model/realtime behavior claim |
| Local structured fast-conversation prompt | 10/10 parse, 10/10 structured safety, 7/10 machine cases; **all ten actions null** | One stochastic same-corpus run; fail-closed suppression, no successful conversation-to-motion witness |
| Personal multi-turn conversation | 3/13 turns; 2/8 families pass | **NO-GO** |
| Captured hosted/realtime corpus | 6 PASS / 8 MIXED / 11 FAIL threads; 43/76 expectations | **NO-GO**; unblinded offline review |
| Fresh compound planner | 3/5 for full plan and 3/5 for PlanSketch | **NO-GO** |
| NAV_INSTRUCT | 25/125, SR 0.20, SPL 0.1348, one false arrival | **NO-GO** |
| Seen/unseen semantic scenes | SR 0.133/0.253; 16 unseen false arrivals | Diagnostic only; **NO-GO** |
| Walk-with-me | 5/10 headless | **NO-GO** |
| Follow | 7/9 scripted Follow; no real owner perception | **NO-GO** |
| Social yield | one simulated human contact/hard collision | **NO-GO** |
| Dynamic social progress | 475 paired authored 2-D episodes; all four hypotheses refuted; every arm had contact | Research mechanisms only; **NO-GO** |
| Independent completion H2 (first follow-up) | 360 cases x three arms; candidate blocked 120/120 alias false arrivals but nominal recall was 116/120 below the 118/120 gate | Overall **REFUTED**; superseded as a research lead by H2b, never integrated |
| Independent completion H2b | isolated contract; 600 cases x three arms; zero false claims across 360 false opportunities and 120/120 nominal, but alias recovery 113/120 versus a 114/120 gate | Overall **REFUTED**; default-disabled and outside the navigation pipeline |
| Acoustic conversation | four frozen virtual gates red; no mounted run | **NO-GO** |
| Go2 actuation path | normal runtime -> Unix gateway -> fake Sport is composed only through a permanently disarmed adapter; no acquire/command surface; no native SDK2/DDS or compatible vendor/physical writer | Desktop disarmed rung implemented; motion-enabled path **NO-GO** |
| Tracked official Go2 MJCF | two 1,000-step finite runs; `nq=19`, `nv=18`, `nu=12`, 41 sensors; final-state digest repeated | Asset/mechanics smoke only; no DDS/controller/physical claim |
| Research summary plane | 14,532-event deterministic probe plus a default-off local product package with strict spool/bundle/governor/provider seams | Local development boundary only; no production crypto, network, cloud, or remote deletion |
| Simulator learning promotion | immutable split registry, proposal-only failure mining/evaluation/review/rollback contracts | Default-off and cannot activate; no trainer, signer service, deployer, or hot swap |

Zero collisions in NAV_INSTRUCT does not rescue a 20% success rate or one
false completion. Conversely, a 7/10 language heuristic score does not erase
the useful structural result that unavailable actions can be closed locally.
The release decision is conjunctive: each safety-critical boundary must pass.

## Hypothesis results

### Conversational embodiment

The static product audit found that only **1/9** personality affect mappings
exists in the effective Go2 realtime gesture enum. Eight names are preferences
for capabilities that the installed surface does not expose.

On authored, already-parsed semantic frames:

- a typed capability/identity/body/consent envelope scored 32/32 with zero
  unavailable or unsafe executions, versus a weak persona-only proxy with nine
  unavailable and 20 unsafe executions;
- receipt- and time-aware dialogue state scored 20/20 with zero false
  completion or unsupported memory answer, versus three of each for a
  tail-only proxy;
- a strict typed initiative gate admitted 0/36 malformed candidates and had
  precision/recall 1.0 on 20 valid authored cases, while a permissive proxy
  admitted 30/36 malformed candidates; and
- a risk-first router preserved all 16 author-labeled hosted routes in the
  authored mix while reducing routed hosted generations 46.67% and assigning
  all five author-labeled safety cases locally.

These results support the interfaces, not conversational quality: the same
researcher authored frames and labels, NLU/audio were bypassed, and no owner
rated the behavior. Details are in
`conversational-embodiment/{DESIGN,RESULTS,VERDICT}.md`.

### Navigation generalization

- A `no_path`-only liveness supervisor was refuted because seven of 24
  blockers stayed `goal_blocked` until the 900-tick ceiling.
- A post-hoc typed set `{no_path, goal_blocked}` terminated 24/24 blockers and
  preserved all 60/60 nominal outcomes. Carry it forward only to a new,
  untouched dynamic holdout.
- Five consecutive high-confidence arrival claims failed in all 3/3 aliased
  localization cases, still 5.21–5.30 m from truth. Temporal confirmation of
  correlated evidence is not independent evidence.
- Two exact reruns and a deterministic artifact-verification script from the
  same research lane reproduced the digests across 516 episode executions.
- A separate preregistered 360-case follow-up converted 120/120 aliased-map
  false completions into typed uncertainty, including 15 cases with a blind
  discontinuity detector. It still failed its nominal-recall gate: 116/120
  true arrivals versus the required 118/120. Four declarations were
  0.00009--0.01440 m outside the frozen 0.50 m truth band, showing that place
  identity is not independently calibrated terminal geometry. The overall
  hypothesis is therefore `REFUTED`, with no product integration.

The design implication is strict: learning may propose routes and estimate
risk, but `PlannerOutcome`, progress budgets, localization authority, and
completion evidence must be explicit. The subsequent H2b implementation did
separate (a) discriminative place identity, (b) a verified new pose epoch and
residual-consistent reset, and (c) conservative target-relative terminal
geometry. In its 600-case x three-arm holdout it retained 120/120 nominal
completion and made zero false claims across 360 false opportunities, but
alias recovery was 113/120 versus the frozen 114/120 gate. H2b is therefore
also `REFUTED`, default-disabled, and not integrated. Details are in
`navigation-generalization/{DESIGN,RESULTS,VERDICT}.md`,
`independent-completion/{DESIGN,RESULTS,VERDICT}.md`, and
`independent-completion-h2b/{DESIGN,RESULTS,VERDICT}.md`.

### Dynamic social progress addendum

A new paired desktop study tested radial waiting, CV-TTC, a visibility/
uncertainty mixture, a sidewalk/crosswalk/elevator semantic time-lattice, and a
small soft learned risk critic across 475 authored 2-D episodes. All four
preregistered hypotheses were refuted and no arm is promotable:

- requiring explicit observed-corridor evidence eliminated the tested
  missing-only resumes, but A2 visible-clear-to-motion latency was 1.85 s
  versus 0.80 s for the radial proxy; most delay was evidence/tracking, since
  evidence-to-motion was 0.10 s;
- the semantic arm improved crosswalk/elevator completion 18.2 points,
  sidewalk completion 25 points, and had zero semantic or moving-hard-floor
  violations, but still had 20/95 contact episodes; and
- the soft critic achieved AUROC 0.945 while missing its held-out 1% false-
  negative gate (4.12%) and worsening false-block time 3.5%.

All A1–A4 contacts were scripted nonreactive actors advancing into a stationary
held robot. This does not excuse them; it proves that hold alone is not a safe
terminal policy. The next simulator task needs explicit free-ray evidence,
proactive safe staging/evasion, typed social progress, companion formation,
and crosswalk/elevator state machines behind the unchanged final reactive
gate. Details are in
`dynamic-social-progress/{REPO_AUDIT,DESIGN,RESULTS,SYSTEM_DESIGN,VERDICT}.md`.

### Off-robot research plane

A standard-library prototype admitted, spooled, bundled, byte-capped, and
replayed 14,532 typed synthetic summary events twice with identical event and
manifest digests. It rejected three negative-control event classes, added no
rows for 100 duplicates, detected a one-byte corruption, and compressed to
9.07% of canonical NDJSON size.

The 0.363 GB/month summary figure extrapolates one synthetic hour to eight
hours/day. The 762.048 GB/month raw sensitivity scenario derives PCM from
16-kHz mono audio but assumes camera traffic of 5 fps at 150 kB/frame and
LiDAR traffic of 100 kB/s; those two rates are not measurements. This strongly
favors testing a summary-first design. It does not validate encryption,
privacy compliance, Starlink, object storage, physical rates, Orin load,
deletion, or learned-model promotion. Details are in
`research-data-plane/{DESIGN,RESULTS,VERDICT}.md`.

The subsequent product package implements only the local side of that design:
strict summary admission, a separate bounded spool, deterministic bundles,
local revocation/expiry cascade, per-attempt byte accounting, and mandatory
injected AEAD/remote-receipt verifier seams. It has no cryptographic or key
provider, uploader, object store, Starlink client, or remote deletion executor.
Provider-shaped callbacks are trust boundaries, not evidence that AES, KMS,
transport, or deletion occurred. See
`research-data-plane/IMPLEMENTATION.md`.

## Recommended system architecture

```text
                  HOSTED / DESK (optional accelerators)
       realtime voice       deliberative text       offline training
              |                    |                       |
              +--------- typed proposals / phrasing ------+
                                   |
ON AGX ORIN                        v
 microphone -> AEC/VAD/ASR -> DialogueStateV1 <-> companion memory
                                   |
                         CompanionMission graph
                  intent -> constrained subgoals -> receipts
                                   |
 camera/LiDAR/body -> scene graph / owner posterior / metric-elevation map
                                   |
                      EmbodimentEnvelopeV1 + local broker
             capability + consent + identity + freshness + body state
                                   |
                   planner / skill -> independent completion latch
                                   |
             reactive safety -> E-stop -> sole motion gateway -> SDK2/DDS
                                   |
                                GO2 BODY

SIDE PLANE, NEVER CONTROL:
 selected local MCAP + typed summaries -> isolated spool
 -> planned client-encrypted bundles -> versioned/hash-bound dataset + lineage
 -> train/evaluate -> human-approved signed release
```

### 1. Capability is a runtime fact

Create `CapabilityManifestV1` from the effective robot profile and commissioned
adapters:

```text
manifest_digest
tools[{name, schema_digest, commissioned}]
gestures[{name, tags, trajectory_digest, commissioned}]
poses[{name, tags, trajectory_digest, commissioned}]
navigation_modes[{name, required_evidence, commissioned}]
```

Generate prompt context, model tool enums, personality closure checks, UI,
eval manifests, action logs, and simulator availability from this object.
Never silently map `comfort_bow` to `play_bow` or infer semantics from a bare
name. A name becomes usable only after trajectory review and physical
commissioning, not merely because it appears in a config.

### 2. Conversation is stateful and embodied, but not an actuator

Add:

- `DialogueStateV1`: current referent, pending clarification, corrections,
  action start/terminal receipts, memory source/time/consent/revocation, and
  retrieval result IDs;
- `EmbodimentEnvelopeV1`: effective manifest digest, verified-owner evidence,
  initiator, E-stop/body mode, locomotion health, affordance/space state,
  pending action, busy reason, and separately scoped consent for speech,
  stationary expression, approach, and following; and
- `OpportunityCandidateV1`: exact types/version, evidence age, novelty,
  subject, privacy/quiet state, owner-speaking/TTS state, and consent.

The language model proposes a reply and at most one typed semantic act. The
local broker validates the exact capability and trigger. The executive emits
an action receipt; only a matching terminal receipt licenses “I did it.”
Expressions during locomotion are separately scheduled and safety-gated.

Recent preprints provide useful hypotheses—not product proof—for affect-action
feedback and context-aware social behavior. They should be tested against
Parcel's own owner preferences and risk constraints rather than copied as
policies ([AffectLoop](https://arxiv.org/abs/2608.16686),
[Mind the Context](https://arxiv.org/abs/2608.13448)).

### 3. Use three cognition lanes

1. **Local deterministic:** STOP/HOLD, admission, identity/consent/privacy,
   receipt acknowledgement, malformed input, initiative drops, spending, and
   other closed acts.
2. **Realtime voice:** greetings, emotional support, ordinary multi-turn
   conversation, clarification, short grounded tool turns, and barge-in.
3. **Deliberative:** novel multi-constraint missions, long-memory comparison,
   research, and diagnosis. It is invoked as a bounded tool after an immediate
   acknowledgement and never writes motion.

This follows the broader lesson of grounding language-model suggestions in
robot affordances rather than trusting fluent text as authority
([SayCan](https://arxiv.org/abs/2204.01691)). Parcel's tested Gemma 4
26B-A4B Q4 is the current local baseline. Today's artifact verifies a
14,439,363,584-byte GGUF; a prior repository memo reports about 15.3 GB of
attributed idle desktop GPU memory but retains no raw process sample in this
research package. An AGX Orin 64 GB should have capacity for the artifact, but
useful latency under concurrent perception/audio/navigation, power modes, and
thermal load must be measured on the exact device. The fresh 3/5 planner score
argues against promoting it merely because it fits.

### 4. Navigation is a hierarchy with independent truth checks

Represent a compound request as a `CompanionMission` graph:

```text
intent
  -> constrained semantic subgoal
  -> metric or target-relative goal
  -> selected skill
  -> progress / blocked / unreachable / completed transition
  -> conversational receipt and optional safe expression
```

Maintain three different memories:

- local metric/elevation map for geometry and traversability;
- semantic/topological scene graph for objects, rooms, relations, and route
  hypotheses; and
- episodic memory for last-seen owner/place/mission events with provenance and
  uncertainty.

Semantic retrieval may propose; geometry and fresh observation authorize.
Owner following needs an identity posterior with lineage, covariance,
distractor margin, occlusion state, bounded search, and an explicit “unknown.”
Never switch to the nearest person. Long-horizon target tracking benchmarks
such as TPT-Bench and social following benchmarks such as Follow-Bench provide
scenario ideas, but Parcel must retain its own Go2 geometry, consent, and
clearance gates ([TPT-Bench](https://arxiv.org/abs/2505.07446),
[Follow-Bench](https://arxiv.org/abs/2509.10796)).

For completion, a pose estimate and goal transformed by the same map hypothesis
are correlated. After a discontinuity, require one registered independent
witness: a discriminative place match with runner-up margin, a fresh
target-relative observation, a carried physical reference, or a bounded
operator reset. Safe mapping literature similarly treats odometry drift as a
correctness problem rather than a confidence-threshold problem
([certifiably-correct mapping](https://www.roboticsproceedings.org/rss21/p007.html)).

### 5. Separate terrain policy from mission semantics

The navigation/locomotion contract should carry elevation, slope, step height,
roughness, edge/drop, corridor width, clearance, uncertainty, desired body
attitude, and allowed abort/retreat. Train privileged teachers and adaptation
policies with friction, actuator, latency, payload, sensor, and terrain
randomization, then export a pinned policy behind the deterministic shell.

Quadruped sim-to-real work supports this pattern, but it does not eliminate
physical commissioning ([Rapid Motor Adaptation](https://www.roboticsproceedings.org/rss17/p011.html),
[agile quadruped sim-to-real](https://www.roboticsproceedings.org/rss14/p10.html),
[egocentric terrain locomotion](https://arxiv.org/abs/2211.07638)). A recent
Go2-focused preprint, CARO, is promising as a comparison point but remains a
preprint and is not validation of Parcel's hardware or software
([CARO](https://arxiv.org/abs/2608.24217)).

## Simulator program and feasibility

| layer | feasibility | build/use now | evidence ceiling |
|---|---|---|---|
| Typed dialogue/world-event replay | **High** | multi-turn reference, corrections, receipts, memory, initiative, cost/network faults | no natural speech or owner preference |
| Virtual audio/timeline | **High** | overlap, cancellation, endpoint logic, self-TTS, packet jitter | no mounted AEC/room response |
| Existing deterministic city/refuters | **High** | no-route, false-arrival, scene splits, crowds, mutation testing | simplified dynamics/synthetic semantics |
| Official Unitree MuJoCo | **Medium-high**; official Go2 MJCF assets are integrated, native SDK2/DDS control is not | native low-level SDK2/DDS, articulated Go2, terrain, plus a Parcel-built simulated `SportPort` or high-level bridge | no drop-in high-level Sport emulator; no physical stopping/system identification |
| Official Unitree RL Mjlab | **Medium-high**, lightweight second engine | Go2 velocity-policy training/play, ONNX export and sim-to-sim challenger after the DDS contract | not Parcel's command seam, safety shell, payload model, or physical validation |
| Unitree RL / Isaac Lab | **Medium-high** | terrain/expressive-policy curriculum, massive randomization, teacher/student training | train on desktop/cloud; profile/deploy on Orin; transfer still unproven |
| MetaUrban | **Medium, second wave** | procedural urban/social diversity after a real adapter and assets | current Parcel adapter is a stub |
| Habitat | **Low-medium, second wave** | indoor semantic/social scenes if assets and pinned stack exist | public project warns active development ended after v0.3.4 |
| Stage-0 MCAP paired replay | **Highest value after capture** | exact clocks, extrinsics, dropout, sim/real residual curriculum | replay still cannot prove actuation |

Unitree's official ROS 2 path recommends Ubuntu 22.04/ROS 2 Humble and
CycloneDDS, with Go2 high-level Sport examples. Its official MuJoCo simulator
supports Go2 at low-level `LowCmd`/`LowState` plus `SportModeState`, but it is
not a drop-in high-level Sport-command emulator; Parcel needs a simulated
`SportPort` or an explicit high-level-to-low-level bridge. It focuses on
low-level controller development and sim-to-real rather than complete autonomy
([unitree_ros2](https://github.com/unitreerobotics/unitree_ros2),
[unitree_mujoco](https://github.com/unitreerobotics/unitree_mujoco)). Unitree's
official Mjlab project now lists a `Unitree-Go2-Flat` velocity task and ONNX
export; use it as a lighter learning/sim-to-sim lane after the native DDS
contract, not instead of that contract
([Unitree RL Mjlab](https://github.com/unitreerobotics/unitree_rl_mjlab)).
Isaac Lab is well suited to GPU-parallel sensors, RL, motion planning, and
domain randomization. Official Unitree RL Lab supports Go2 upstream, but Parcel
has not installed, pinned, run, profiled, or validated either training stack's
policy export/deployment; integration work remains real
([Isaac Lab](https://isaac-sim.github.io/IsaacLab/),
[Unitree Isaac Lab](https://github.com/unitreerobotics/unitree_rl_lab)).

### Scenario generator

Build episodes from independently controlled axes and freeze their Cartesian
subsets by digest:

- scene: room geometry, outdoor block, stairs, clutter, lighting;
- language: paraphrase, reference, correction, negation, quotation,
  code-switch, multi-turn amendment;
- goal: object, region, relation, owner-relative, route sequence;
- perception: miss/false positive, ambiguity, stale result, distractor,
  occlusion, identity swap;
- localization: drift, loop alias, kidnapping, restart, clock skew;
- dynamics: moving people/doors, friction, payload, actuator and command delay;
- systems: process death, DDS loss, network jitter/loss, disk/thermal pressure;
- social: distance, formation, group crossing, quiet/private zone, consent; and
- terrain: slope, step, stairs, roughness, edge/drop, affordance uncertainty.

Do not optimize one aggregate. Report success/SPL, false transition, collision,
human contact and clearance, owner identity swap, blocked-terminal latency,
subgoal completion, correction recovery, dialogue grounding, action receipt
accuracy, acoustic interruption, power/thermal/deadline behavior, and cost.

## Governed self-learning loop

```text
immutable run + provenance
        -> failure classifier and counterfactual candidates
        -> train/dev curriculum (failure-mined + broad randomization)
        -> untouched frozen holdout + minimal refuters
        -> sim-to-sim / real-bag paired residual check
        -> human review for conversation/social behavior
        -> signed candidate release
        -> shadow mode
        -> staged physical rung with rollback
        -> new evidence, never direct self-promotion
```

Use hash-bound MCAP plus content-addressed summary bundles and versioned dataset
manifests. Keep owner memory, operational evidence, and research data as
distinct stores. MCAP is a robotics-native indexed log format with schemas,
channels, chunks, CRCs, and summaries
([MCAP specification](https://mcap.dev/spec)). Raw capture remains default off;
when explicitly enabled, keep raw windows local unless separately scoped
upload authority exists. Export only purpose-approved pseudonymous summaries,
and treat pseudonymous data as personal/linkable rather than anonymous. The
new local package keeps its spool under a separately resolved research root,
refuses a configured root that contains owner memory, and has focused path-
guard tests. It still has no production network exporter, owner-memory
capability sandbox, or external storage provider. The research plane has no
direct arrow to control.

Initial retention recommendations, pending privacy/legal review, are 90 days
for summaries; up to one year for pseudonymous feedback; at most 30 days for
separately approved redacted text or exact GNSS; seven days, extendable to at
most 30 for a named study, for raw audio; and 7–30 days for named-protocol raw
image/video/MCAP. Face and voice embeddings are never exported by default.
Expiry and revocation must be enforced across spool, object store, catalog,
cache, derived datasets, and backups. Seeded regex/forbidden-key tests do not
prove de-identification.

The learning loop should be recursive in *experimentation*, not in authority.
Recent work on automatically generated, falsifiable navigation experiments is
a useful research-direction signal, but candidates still require frozen tests
and human/physical gates ([AI Scientist for robot navigation, preprint](https://arxiv.org/abs/2608.07542)).

The P0 `learning_loop` package now makes the first part executable: immutable
train/dev/frozen-test registries, leakage-group checks, deterministic same-
split failure-case proposals, canonical candidate evaluations, zero-tolerance
safety counters, and a default-off digest/signature/rollback review gate. Even
an accepted result is only `propose_for_activation` and always reports
`authorizes_activation == false`; no trainer, external signer, deployer,
rollback executor, or hot-swap path was added.

## Conversation and navigation release evaluations

### Conversation

- Raw audio, not only pre-parsed frames: accent, disfluency, correction,
  overlap, barge-in, TV, non-owner, self-TTS, room noise, gait/fan/wind.
- Multi-turn: reference resolution, pending action, “again,” cancel/pause/
  resume, stale/mismatched receipt, fact correction/revocation, cross-session
  retrieval, honest abstention.
- Embodiment: exact capability closure, hypothetical/negated/quoted emotion,
  one-action limit, body-busy deferral, no travel from inferred affect,
  expression-motion scheduling.
- Social quality: blinded owner ratings for warmth, naturalness, interruption,
  repetition, support, boundaries, and unwanted clinginess over multi-hour
  sessions.
- Release floors: 100% schema parse; zero unauthorized/unavailable action,
  premature completion, unsupported perception, or unsupported memory on the
  frozen high-risk set; at least 95% exact intent/action decision per high-risk
  family; all virtual-acoustic gates green; then mounted gates.

### Navigation

- Freeze train/dev/test splits by scene, instruction, target, relation,
  disturbance, dynamics, terrain, and system fault—not random episode rows
  from one generator seed.
- Score every transition and subgoal, not only final arrival.
- Treat one false arrival, identity swap, human contact, or authority bypass as
  red regardless of aggregate success.
- Require zero silent timeouts and bounded typed `blocked`, `unreachable`,
  `lost_target`, `identity_ambiguous`, `terrain_unsupported`, or `evidence_lost`
  outcomes.
- Add paired real-bag residuals after Stage 0. Simulator gains without measured
  sim/real correlation do not promote physical readiness.

## Compute, network, and monthly budget

Run all 10–100 Hz perception, state estimation, planning, safety, target
tracking, and locomotion locally. Starlink, if configured and measured, must
remain a conversational/research uplink and never a motion dependency. The
local link-loss policy must finish only a permitted bounded action or hold and
must never re-arm. No Starlink or link-loss path was exercised today.

Recommended monthly allocation:

| envelope | allocation | behavior when forecast is exceeded |
|---|---:|---|
| OpenAI Realtime | $210 owner-initiated conversation; $45 admitted proactive/embodied turns; $30 frozen/shadow eval; $15 reserve | stop hosted proactive phrasing first, preserve owner turns and local safety |
| Hosted text | $60 deliberate planning/research; $20 offline labeling/eval; $20 reserve | queue deep work or ask permission; local closed acts continue |
| Research sync (proposed) | 50 MiB/day for P0 control, P1 feedback/manifests, and P2 summaries; separate 5 GB/month defense-in-depth summary ceiling | P3 raw stays off on metered links; reserve at least 1 MiB/day outside the ordinary cap for consent/tombstone control |

As checked on 2026-08-26, the exact named model pages list these prices per
million tokens:

| model | text input / cached / output | audio input / cached / output |
|---|---:|---:|
| `gpt-realtime-2.1` | $4.00 / $0.40 / $24.00 | $32.00 / $0.40 / $64.00 |
| `gpt-realtime-2.1-mini` | $0.60 / $0.06 / $2.40 | $10.00 / $0.30 / $20.00 |

The repository defaults to the first and its example deployment selects the
second. These are official current alias prices, not a guaranteed monthly
forecast; pin the production snapshot and recheck its official rate before
launch ([OpenAI `gpt-realtime-2.1`](https://developers.openai.com/api/docs/models/gpt-realtime-2.1),
[OpenAI `gpt-realtime-2.1-mini`](https://developers.openai.com/api/docs/models/gpt-realtime-2.1-mini)).
Prompt caching, local closed acts, compact state deltas, and an actual usage
ledger remain important. Do not convert the $300 envelope into a promised
number of hours until real audio-token usage, session duration, context
growth, cache hits, reconnects, and retries are measured. OpenAI's official
cost guide describes truncation, caching, and session-cost controls
([Realtime cost management](https://developers.openai.com/api/docs/guides/realtime-costs)).

The default-off local package now has durable daily/monthly byte accounting
for every distinct candidate ciphertext transfer attempt, with separate
ordinary/control buckets. It is not a network-byte measurement or uploader:
there is no transport/provider ledger, and no Starlink or object-store traffic
has occurred. A fully used 50 MiB/day would be about 1.57 GB per 30 days. The
synthetic
90-day summary projection is 1.090 GB and about $0.016/month of R2 Standard
storage. Its 15,840 monthly puts are about $0.071 gross and $0 after the cited
free tier. Those time-sensitive estimates exclude compute, catalog, retrieval,
tax, labor, and all Starlink subscription/overage; no cloud or link dollar
budget was validated.

For offline continuity on AGX 64 GB, retain the exact evaluated Gemma baseline
behind the typed schema, whisper.cpp/Silero for the existing local speech
floor, and Piper as the degraded TTS path. Then run an exact-device bakeoff
against smaller candidates; choose by valid structured outcomes and spoken
latency under concurrent load, not parameter count. Required measurements are
TTFT, first audible chunk, complete usable frame, cancellation, tokens/s,
RAM/VRAM, power, thermals, deadline misses, and capability/safety accuracy.

## Immediate execution order

### P0 — start now

1. Build `CapabilityManifestV1`, close all personality/runtime mappings, and
   supply typed semantics to the conversation agent.
2. Compose the normal runtime through the disarmed gateway against fake Sport.
   Retain the existing official Go2 MJCF assets, and separately bridge the
   native Unitree MuJoCo low-level SDK2/DDS simulator surface into a simulated
   `SportPort` or explicit high-level controller without creating a second
   writer.
3. Implement typed `PlannerOutcome` liveness budgets. Preregister H2b and test
   independent identity, verified pose reset, and independently calibrated
   terminal geometry on untouched dynamic/localization holdouts before any
   completion-authority integration.
4. Implement `DialogueStateV1`, `EmbodimentEnvelopeV1`, action receipts, and
   the `CompanionMission` graph.
5. Turn the present red conversation/navigation cases into immutable minimal
   refuters. Fix the two reproducible lamppost product-path failures.

Implementation status: the capability contract, optional manifest consumer,
disarmed runtime-to-Unix-gateway-to-fake-Sport slice, dialogue/envelope/receipt
contracts, and isolated H2b latch now exist. H2b failed its gate. The native
Unitree MuJoCo SDK2/DDS bridge, full planner-outcome/mission integration, live
companion receipt path, and remaining frozen product refuters are still open.

### P1 — after P0 contract proof

1. Build the multidimensional scenario generator and frozen split registry.
2. Add owner-posterior tracking and Follow/search/crossing/occlusion campaigns.
3. Extend the new default-off local research spool from provider-verifier seams
   to real client encryption/KMS, authenticated upload, object/catalog/derived
   deletion, and empty-workspace replay before any off-robot pilot.
4. Run the local speech/model stack and candidate bakeoff on the actual AGX
   under camera/LiDAR/navigation load.

### P2 — after Stage-0 evidence

1. Replay stationary Stage-0 MCAP through the exact product observation path
   to validate clocks, freshness/dropout, calibration plumbing, and stationary
   pose stability. Collect later controlled-motion/dynamic-obstacle recordings
   before claiming genuine LIO, R3/R4b, or arrival evidence; fault-mutated
   stationary replay tests software failure handling only.
2. Train expressive stationary and terrain policies in articulated simulation,
   then sim-to-sim/HIL/profile on Orin.
3. Conduct blinded owner conversation/social-preference sessions and mounted
   acoustic campaigns.
4. Advance through the physical ladder in `MOUNT_READINESS.md`; preserve
   default-off Follow, proactive speech, approach/search, and stairs until their
   own gates pass.

## Repository verification

The required one-time commit-tier close gate ran once. Its dedicated rows were
green, but its default-suite row recorded two deterministic maintenance
failures after 10,510 passes: a stale 100-versus-102 packaged-asset expectation
and the SI prompt module exceeding the existing 1,000-line ratchet by 37 lines.
Both exact defects were fixed. Their post-fix guarded regression was 2/2, and
the broader affected suite was 111 passed with four skips. Subsequent
adversarial closure added the v5/DI-v2 prompt boundary, deterministic action
authority check, and simulator-clock mapping; its prompt/action/freeze/parity
suite passed 265 tests and its real-HeadlessCity clock node passed 1/1. The
current parity truth is 15 prompt pins across five versions and 105 packaged
files plus one external side-mirror comparison. Lint, all new JSON, and diff
whitespace checks were green. A final cross-surface focused suite passed 269
tests. The broader clock/runtime suite passed 167 tests and hit one previously
documented load-sensitive stale-LiDAR startup race; that exact node passed on
its immediate 1/1 rerun. The full gate was not rerun under its
once-per-close rule, so the recorded full-gate result remains red before those
fixes and is not represented here as a post-fix green run.

The later P0 implementation tranche has separate focused and merged-tree
verification. Focused P0, commissioned-runtime, and architecture/import runs
are green. The guarded merged non-slow suite is **RED**: 10,811 passed,
111 failed, 23 skipped, 83 deselected, and 5 xfailed in 549.20 seconds. The
dominant red surface is legacy motion-test setup that supplies no commissioned
capability manifest and is therefore correctly disarmed; two W0B ratchets also
encode the older rule that runtime must not import commissioning. This report
does not relabel that migration debt as a product green or weaken fail-closed
admission to satisfy it.

## Review boundaries

The linked Claude artifact was inaccessible (`Page not found`) and cannot be
used as evidence. Claude's committed motion seam was reviewed and remains
accepted at desktop/bench tier only. Nothing in this report claims a physical
test, an Orin result, official benchmark score, privacy/legal compliance, or
human conversation preference.

The original research card is `../../scrum/20260826/task_1/README.md`; the P0
implementation card is `../../scrum/20260826/task_3/README.md`. The exact
readiness measurements are in
`system-readiness/RESULTS.md`; individual hypothesis preregistrations, raw
results, source manifests, and independent verdicts remain in their respective
subdirectories.
