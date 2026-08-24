# Task 1 · RTP-1 — research-to-functional-prototype review

**Date:** 2026-08-24

**Status:** REVIEW_REQUESTED · NOT DISPATCHED

**Author:** Codex (current research and product-path assessment)

**Required reviewer:** Claude

## Owner request

Revisit the current `research/` program and determine whether it now gives a
dependency-correct, evidence-backed next phase for a functional prototype on
the Unitree Go2 EDU Plus. Review the concerns and recommendations below,
correct them where the repository provides contrary evidence, and return one
consolidated recommendation for owner approval.

This is a review task. It does **not** authorize implementation, new research
executors, physical motion, starting or stopping services, editing existing
experiment criteria, creating follow-up cards, changing product code, running
a broad test campaign, committing, or pushing.

## Review boundary

At task creation, the reviewed tree was:

- `main` / `origin/main`: `0c5ea97` (`research: H1 second-read notes
  (server-VAD scope, n=1 replicate, C5 is the house number)`);
- dirty `pyproject.toml` with the H7 `localization` extra; and
- actively changing tracked Ministral research logs under
  `research/20260823/local-cognition-gpu/logs/`.

Claude must record the exact commit and dirty overlay it actually reviews.
Concurrent work may advance the tree after this card was written; do not
overwrite or normalize changes owned by another session.

Primary evidence:

- `research/README.md`;
- `research/20260823/README.md` and each H1-H7 `VERDICT.md`;
- `research/20260823/search-before-refuse/` (H8);
- `research/20260823/MILESTONE1_DESIGN_FABLE.md`;
- `research/20260824/README.md`;
- `research/20260824/offline-first-cognition/` (H9); and
- `research/20260824/platform-and-connectivity/DECISION_MEMO_FABLE.md` (H10).

## Working assessment

The research is now materially useful. It has changed the project from a
large collection of mechanisms and aspirations into a scoped Milestone-1
design with falsifiable contracts, evidence tiers, explicit refutations and a
link-loss ladder. It correctly narrows the first body outcome to a supervised,
low-speed, single-room indoor prototype and keeps model outputs outside motion
authority.

That progress is primarily **design and uncertainty reduction**, not yet an
equivalent increase in functional-robot readiness. Most H3-H7 capability
leaves remain harness-only or flag-OFF, there is no native Unitree writer, no
real LIO, no commissioned body-intent adapter, and no closed physical
sensor-to-task-to-motion-to-feedback loop. The next phase should therefore
shift from broad research toward a thin vertical prototype slice once the
few remaining decision-blocking experiments close.

Claude must return one top-level disposition in `CLAUDE_REVIEW.md`:

1. `ACCEPT_NEXT_PHASE`
2. `ACCEPT_WITH_REQUIRED_CHANGES`
3. `REJECT_NEXT_PHASE`

## Concerns Claude must confirm, correct or refute

### C1 · Research results are being mistaken for runtime capabilities

`BodyIntentV1`, the body composer, drives, continual-memory scheduler,
episodes, noticing loop, localization provider and world-answer renderer are
valuable product-shaped seams. Their experiments generally prove a contract
or isolated mechanism, not that `RobotRuntime` constructs and closes the loop.
Every recommendation must label `harness-only`, `product-reachable`,
`target-run`, and `on-robot` separately.

Required response: provide a small product-path matrix for H1-H10 naming the
first production constructor/caller, or `NONE`, and the current evidence
ceiling. Do not infer reachability from a file existing under `src/`.

### C2 · The physical critical path remains unclosed

The native sole-writer gateway/governor remains the largest physical blocker.
There is no positive Unitree motion authority, independent-stop evidence,
real Mid-360 localization, calibrated RGB/depth observation, or repeated
supervised indoor traversal. No amount of additional mind/memory research
substitutes for that path.

Required response: confirm whether M1-0 is still the single next build card.
If not, name one smaller prerequisite and the concrete physical outcome it
unblocks. Do not create that card in this review.

### C3 · Milestone implementation order is not yet optimized for a functional robot

The current M1 list is coherent by subsystem, but MIND and LEARN can consume
integration effort before the gateway, observation, pose and navigation
spine has produced one physical outcome. The functional-prototype order
should be dependency-driven rather than feature-complete.

Recommended thin slice:

```text
NAV-CORE chooses retained vs simplified/delegated known-place navigation
  -> native governor/gateway + independent stop
  -> real body state and stamped sensor observation
  -> real LIO/localization health
  -> supervised Stop / known-place NavigateTo
  -> Follow only after physical owner-identity closure
  -> final transcript -> validated semantic task
  -> continuous HOLD / gaze / breathing intent
  -> governed memory
  -> bounded initiative and search
```

Required response: accept this order or replace it with a shorter
dependency-correct sequence. For every stage, state one positive proof, one
fault/refuter and the stop/continue criterion.

### C4 · H2 local-cognition closure is incomplete and appears operationally noisy

H2 has useful results but no final independent verdict. The measured
LLM-as-tick agreement is poor, and a contended planning call reportedly took
about 161 seconds and failed. Long-running model servers, polling shells and
tracked log churn complicate attribution and consume resources. Continuous
model cognition should not remain an assumed architectural requirement.

Required response: close H2 from the smallest valid evidence set, record the
exact run state, and recommend deterministic drives plus optional model
phrasing unless an already-running measurement can overturn that topology.
Do not start another model campaign merely to improve timing precision after
the architecture decision is already known.

### C5 · Known-place navigation is under-researched; H8 may be sequenced too early

The current research program prioritizes unknown-place exploration while the
ordinary navigation foundation remains weak. The recorded semantic-navigation
v4 result is 0.24 success over 25 simulator episodes, and the mission path
still assumes truth pose, exact polygons, simulator semantic IDs and
deterministic re-detection that physical perception will not provide. A
search for an unknown storefront cannot be more foundational than reliably
reaching one known metric goal in the declared room.

Required response: define one bounded **NAV-CORE** experiment before design
freeze:

```text
final transcript -> validated NavigateTo -> known metric goal
  -> planner/controller -> physical-shaped scan + pose messages
  -> verified arrival | typed honest failure
```

The experiment must remove truth pose, oracle IDs, exact scene polygons and
perfect re-detection. It must decide one thing: retain Parcel's current
navigator for M1, simplify M1 to a metric point-goal path, or delegate more
navigation to a mature external navigation subsystem. Pre-register a small
one-room corpus, obstacle/dropout refuters, zero false arrivals and a success
bar before the run; stop when the topology decision is known.

H8 remains directionally correct, but before NAV-CORE closes it is optional.
If evidence is required before freeze, reduce H8 to one seam probe: unknown
noun -> `searching`; one present target -> `found`; one absent target ->
`not_found`; STOP within one tick; no pre-arrival success language. Whether
that probe passes or fails, research stops and the result only chooses reuse
versus implementation work in M1-8.

### C6 · H9 does not yet settle online versus offline compound planning

The typed grammar is a strong offline-floor hypothesis, but the 8B normalizer
must not become mandatory by assumption. The immediate connected prototype
can use a separate hosted text planner that proposes a compact PlanSketch;
Parcel must still compile, freshly validate and execute it locally. Common
patterns can remain deterministic and loss of connectivity can fall back to
one-step clarification.

Required H9 stop-early comparison ladder:

1. deterministic grammar only;
2. only if misses are primarily paraphrases, grammar plus local 8B
   normalizer;
3. only if the preceding arms cannot establish a safe offline floor, compare
   direct local PlanSketch and the current 26B as references; and
4. use a separate hosted structured-output planner as the connected reference.

Stop at the first arm that establishes either safe deterministic coverage or
an honest one-step clarification fallback. H9 failure must not automatically
select an AGX/26B payload; "tell me which step first" is an acceptable offline
floor when the hosted planner is unreachable.

The hosted model is a semantic compiler only. It must not own dialogue state,
memory, coordinates, velocity, joints, gait, safety, replanning ticks or tool
execution. The current launcher is llama.cpp-specific, so a hosted provider
requires an explicit adapter/factory or a temporary compatibility gateway; it
is not merely a YAML change.

Required response: distinguish the **offline floor** from the **connected
planner**, report latency/cost/failure behavior, recommend which arm owns each
link-loss rung, and state exactly which early-stop condition ended the study.

### C7 · The H9 corpus does not test the current router's largest false-call risk

The frozen 60-item corpus usefully tests supported and unsupported physical
requests, but it was authored by the design side and lacks an independently
authored held-out set. Its out-of-grammar rows also do not adequately test
ordinary narratives, questions and conversational corrections that contain
physical words.

Examples that must not become physical plans include:

- "I walked to the store and had lunch."
- "Why did you sit and stand?"
- "Could you explain walking and navigation?"
- "Actually, how are you?"
- "No, I don't think so."
- "The other day I saw a dog."

The current compound gate broadly combines conjunctions with physical cues,
and the amendment gate broadly matches correction prefixes. This can create
unnecessary model spend and false physical intent.

Required response: preserve the frozen corpus, add a separately labeled,
independently authored intent-gate/adversarial set, and report false physical
plan rate separately from PlanIR validity. Do not edit the frozen gold after
the first run.

### C8 · Goal-amend suspension needs a product-path audit

The current amendment path pauses controller channels, but `goal_amend` does
not appear to be an explicit executive voice-suspend policy reason and can
fall through to overlap semantics. An executive-only task may therefore
continue advancing while a replacement plan is generated.

Required response: trace this claim against the current executive/runtime,
confirm or refute it with a focused test recommendation, and treat a confirmed
race as a precondition for hosted or local replanning—not as a reason for a
broad voice rewrite.

### C9 · Conversation economics are promising but the activation policy is incomplete

H1 usefully corrects the prior belief that streamed silence creates the main
bill. Its stronger finding is that VAD alone opens on television speech at a
very high rate. Owner identity and engagement triage are therefore product
requirements, but owner-voice identity is not yet measured as the missing
half of the gate. Cost extrapolations must retain their corpus duty-cycle and
sample-size caveats.

Required response: specify the smallest through-air activation and
self-speech-immunity experiment before claiming an all-day ear. Use the
XVF3800 and intended speaker path with owner speech, another person,
television, robot TTS, distance/angle changes and representative fan,
footfall/motion and limited wind noise. Report false opens/hour, owner misses,
false identity acceptance, spoken-stop recall, intent/critical-slot accuracy,
first-word loss, endpoint latency, barge-in/cancel latency, self-transcribed
physical intents, AEC attenuation and cost. The result must choose among
owner-voice gating, wake phrase, push-to-talk or restricted listening and
must feed microphone/speaker placement. Avoid another broad voice-model
campaign unless this hardware/policy decision depends on it.

### C10 · Memory research found product defects, not a ready learning system

H5 was correctly refuted. Scheduler, persistence, episodes and world answers
remain useful, but the session-id mismatch, schema-incompatible live proposer,
tombstone resurrection and single-match ranking refusal prevent a claim that
the running robot recursively learns and answers from its world.

Required response: keep these four fixes together as M1-4 acceptance work,
require a distractor-rich independently authored probe set, and do not enable
continual memory until revocation/deletion and provenance survive end-to-end.

### C11 · Perception and localization results are not target evidence

H6 still has inconclusive throughput/freshness rows, RGB-only map writes are
zero, and the product has not been validated with the intended D455 on the
robot. H7 proves a useful localization contract, but its simulated ICP
covariance is 50-100x overconfident and no real Mid-360 LIO has populated the
MAP role.

Required response: make depth, stamped extrinsics and real-bag LIO a
prerequisite to autonomous spatial claims. Covariance-driven health must not
be trusted until calibrated on real bags. FAST-LIO2/Point-LIO/KISS-ICP remain
candidates to measure, not declared winners from planar simulation.

### C12 · Body intent is a good contract but not commissioned behavior

H4 demonstrates a portable continuous HOLD/gaze/posture/locomotion contract
at desktop-sim evidence. It does not prove that Go2 Sport `Euler`, `Move` and
`StopMove` tolerate the chosen update rate, posture amplitude or arbitration
without disturbing balance.

Required response: retain the contract, commission one primitive at a time,
start with stationary HOLD and one bounded expression, and require owner/safety
preemption before enabling continuous autonomous body behavior.

### C13 · H10 is a direction memo, not procurement-grade evidence

Keeping the ordered Go2 is a reasonable current decision and 5G should be
treated as a payload/link concern rather than a robot-body selector. However,
X30 compute/cellular, Go2 payload power, AGX carrier weight/thermals and some
pricing facts are reseller-derived or explicitly unverified.

Required response: retain the Go2 recommendation provisionally, list the few
facts requiring written vendor confirmation, and do not select an AGX payload
until H9 and an Orin NX measurement show it is necessary.

### C14 · Research artifact and process growth is becoming a delivery risk

The research wave committed a very large volume of raw logs, generated JSON
and evidence in Git. Active servers modify tracked logs, and verifier/executor
limits have left polling processes and partially completed runs. This makes
status harder to read, increases repository/index noise and can consume
Claude context without advancing the physical prototype.

Required response:

- identify canonical `DESIGN`, `RESULTS`, `VERDICT` and compact summary files;
- recommend artifact storage/retention for raw logs and large generated data;
- keep immutable inputs and headline evidence reproducible without tracking
  every live append-only log;
- stop orphaned polling only through the owning session, not from this card;
- limit active work to one physical integration lane plus one disjoint
  blocking experiment; and
- prohibit one-follow-up-card-per-observation. Batch corrections by owning
  milestone boundary.

### C15 · Target compute and mountability remain extrapolated

H9 and H10 use desktop measurements and rough payload budgets; they do not
show that the Orin NX can sustain the actual body workload or that the chosen
payload geometry is viable. VRAM fit alone does not cover CPU/GPU/EMC
contention, thermal throttling, power transients, battery effect, USB/network
bandwidth, cooling, vibration, field-of-view overlap, self-occlusion, cable
retention, antenna placement or center of gravity. These unknowns can change
NX versus offboard/AGX topology and the mechanical/electrical mount.

Required response: define one **target-compute/mount freeze packet**, treated
as hardware acceptance rather than another desk-research wave. On the actual
Orin, run a 60-minute co-residency soak with the native gateway, local audio
floor, LIO, D455 ingestion, reduced perception and the supervisory runtime.
Record RAM/VRAM, temperatures/throttling, power/battery, deadline misses,
queue growth, restarts and behavior under GPU/network pressure. In the same
packet record payload/rail facts, center of gravity, cooling, Mid-360/D455
coverage and floor visibility, occlusion, vibration/cables and antennas.
Pre-register the keep-NX, offboard and reconsider-compute branches. Do not
select or purchase an AGX payload until this packet or H9 demonstrates need.

### C16 · Physical person identity is a prerequisite only if Follow stays in M1

Current Follow evidence is simulator/mocap-backed and does not establish
owner/stranger continuity. A nearest-person substitution after crossing or
occlusion is unacceptable. Broad owner-tracking research is unnecessary if
Follow is removed from the first moving slice.

Required response: make a binary scope choice. Either defer Follow from M1,
or require a small held-out physical study covering two-person crossing,
occlusion/reacquisition, clothing/lighting variation and appearance-only
versus appearance-plus-UWB. Ambiguity or identity loss must produce HOLD.

### C17 · The first-room ODD lacks one current hazard/authority closure table

The repository contains extensive safety mechanisms and prose, but the
current milestone still needs one concise hazard record linking each
first-room hazard to prevention, detection, fail state, verification witness
and residual-risk owner. This is a design gate, not an extended standards or
algorithm research project.

At minimum cover collision/contact, fall/drop-off/glass, runaway/stale
command, localization jump/loss, sensor/network/cloud loss, wrong-person
follow, battery/thermal faults, false or self-transcribed voice commands,
independent stop, payload/mount failure and private audio/video/memory data.

Required response: produce the one-table closure recommendation, identify
which rows block first pulse versus first translation versus first autonomous
mission, and stop. Do not create a card per hazard.

## Recommended next-phase decision

Unless Claude finds contrary evidence, the research phase should close after
the minimum H2/H9/NAV-CORE decisions needed to freeze the topology, with only
a tiny optional H8 seam probe. The project should then execute a **functional
vertical slice**, not all M1 subsystems in parallel.

### Phase A · close only decision-blocking research

- H2: final local cognition/sizing verdict;
- H9: stop-early offline floor and connected-planner decision;
- NAV-CORE: known-place, non-oracle one-room navigation topology decision;
- H8: optional tiny disposition/product-path probe only after NAV-CORE;
- H10: written vendor confirmation for facts that affect payload safety; and
- one concise ODD/hazard/authority table.

### Phase B · first functional physical slice

- native sole-writer gateway/governor, boot-disarmed and exact-zero on loss;
- independent operator stop and measured stop latency/distance;
- real stamped body/LiDAR/RGB-depth observation;
- real LIO health/jump behind the existing pose contract;
- target-compute/mount freeze packet and sustained Orin co-residency soak;
- supervised `stop` and one known-place `NavigateTo` in one room;
- `follow` only if C16's physical identity branch is accepted and passes;
- final voice transcript to validated semantic task and verified completion;
- all cloud/desk loss paths degrade to hold/closed intents locally.

### Phase C · make the stationary/moving robot feel alive

- continuous local HOLD plus bounded breathing/gaze intent;
- deterministic drives with quiet/radius/return-leg policy;
- bounded unknown-entity search;
- hosted conversation per genuine engagement; and
- memory only after the four H5 defects and governance acceptance close.

Outdoor, public-space autonomy, custom gait/joint control, online policy
learning and autonomous model-weight modification remain outside this first
prototype milestone.

## Research admission and stop policy

The remaining pre-freeze research budget should be approximately three to
five focused working days, excluding measurements that require delivered
hardware. Admit a new study only when a failed result changes at least one of:
robot body, BOM, compute topology, safety/authority boundary, declared ODD or
the first prototype acceptance test.

Every admitted study must have one decision, pre-registered branches, a
bounded evidence budget and an early-stop rule. Do not optimize a model or
metric after the architecture decision is known. Hardware-only unknowns move
to box-day/commissioning gates rather than spawning more desk research.

Specifically defer additional H2 model comparisons, on-body 26B/X30 work,
full H8 OCR/open-world exploration, outdoor/stairs/crowds, broad generalized
perception, long-horizon lifelikeness studies, trainable initiative, continual
weight/safety-policy learning and custom gait/joint/locomotion-RL research.

## Required review output

Create only `scrum/20260824/task_1/CLAUDE_REVIEW.md` containing:

- exact reviewed commit and dirty-overlay boundary;
- one required disposition;
- a concise H1-H10 product-path/evidence-ceiling matrix;
- each C1-C17 disposition: `CONFIRM`, `CONFIRM_WITH_CORRECTION`, or `REFUTE`,
  with file/line or measurement evidence for corrections/refutations;
- accepted or revised first functional-prototype ODD;
- accepted or revised dependency order and the single next build card;
- `CLOSE_BEFORE_BUILD`, `BUILD_NEXT`, `DEFER`, and `DROP` assignments;
- positive/refuter/stop-continue gates for the vertical slice;
- a bounded spend, WIP and research-artifact policy; and
- a non-empty `Does not prove` section.

Do not implement the recommendations, modify experiment gold, dispatch
agents, create additional tasks, commit or push. Return the consolidated
review for owner approval.

## Ownership and collision boundary

**OWNS:** `scrum/20260824/task_1/CLAUDE_REVIEW.md` only.

**MUST NOT TOUCH:** this `README.md`; `src/**`; `tests/**`; `research/**`;
`configs/**`; `scripts/**`; `tools/**`; `docs/**`; other `scrum/**`; Git
state; running services; the owner memory store; or any physical robot.

No test run is required for this docs-only review. Focused read-only commands
may be used to verify disputed product-path facts.

## What this task does not prove

This task is an architecture, evidence and priority review. Accepting it proves
no target installation, independent stop, localization accuracy, perception
quality, acoustic quality, planner quality, memory quality, stopping distance,
autonomous navigation success, outdoor fitness, physical safety or readiness
to move a Unitree. Desktop tests, simulator experiments and the presence of
product-shaped classes must not be promoted into physical evidence.
