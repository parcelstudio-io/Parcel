# Production design — trainable duplex companion navigation and conversation

Date: 2026-08-29. Target: Unitree Go2 EDU+ with AGX Orin 64 GB, camera,
Mid-360-class LiDAR, microphone array, speaker, and Starlink. Status: design
and desktop evidence only; physical motion remains **NO-GO**.

## Decision

The proposed Model A / Model B split is the right abstraction if “model” means
a trainable component inside a typed, multi-rate control system. It is unsafe
and currently unsupported if Model A means one foundation model that consumes
all raw streams and directly owns global planning, joint/base control,
completion, and speech.

Build this instead:

```text
 camera / lidar / IMU / robot state / audio / owner context
               │                         │
       local perception + tracking       ├── local STOP / addressee gate
               │                         │
               ▼                         ▼
       EmbodiedFrameV1 @ 10 Hz      final transcript/event
               │                         │
       ┌───────┴──────────────┐     Model B ingress
       │ Model A fast proposal│◄── SteeringEventV1
       │ + slow plan proposal │
       └───────┬──────────────┘
               │ SemanticControlV1 (short lease, task/revision bound)
               ▼
   task executive → arbiter → collision/safety/freshness gates → 50 Hz control
          ▲                                              │
          │ accepted ExecutionResult / authenticated receipt
          └──────────────────────┬───────────────────────┘
                                 ▼
                         Model B egress
                    ExecutionNarrativeEventV1
                                 │
             compact event → hosted Realtime → speech
                                 │
                     never a motion authority
```

This follows the two-level pattern demonstrated by
[NaVILA](https://arxiv.org/abs/2412.04453), which emits spatial mid-level
language actions into a locomotion policy, and the asynchronous fast-policy /
slow-reasoner pattern in
[TIC-VLA](https://ucla-mobility.github.io/TIC-VLA/). Streaming visual
navigation work also uses bounded fast context plus compressed slow memory
rather than replaying unlimited raw history
([StreamVLN](https://streamvln.github.io/)). None of those systems establishes
safe conversational Go2 autonomy by itself.

## Clocks and authority

| lane | target cadence | owns | never owns |
|---|---:|---|---|
| vendor locomotion / actuator loop | vendor-defined; measure on target | gait and joint stabilization | language, task meaning |
| Parcel `ControlManager` | 50 Hz today | leased body velocity, stale-feedback watchdog, stop confirmation, tilt/fault handling | route or dialogue |
| collision/reactive gate | at every 10 Hz runtime dispatch; raise after profiling | final admissible local command | goal selection |
| Model A fast head | 10 Hz | bounded semantic proposal and confidence | raw joints, stop override, completion |
| tracker / local trajectory policy | 20–50 Hz target | braking-safe committed prefix and revisable tail | task identity |
| global planner / Model A slow head | event-driven, usually 0.5–2 Hz | route/subgoal proposal | actuator authority |
| task executive | on command/receipt and 10 Hz tick | task, revision, step, attempt, queue, suspend/resume, success transition | prose |
| Model B ingress | every final owner utterance; local STOP earlier | steering classification and grounding proposal | executing it |
| Model B egress | accepted state changes; rate-gated | typed narration frame | declaring an unverified result |
| hosted Realtime | audio-rate provider session | natural voice and conversational realization | safety, plan ledger, motion |

These rates are an engineering starting point, not a hardware claim. Parcel
already has a 10 Hz runtime (`RobotRuntime`,
[`runtime.py`](../../src/parcel_robot/runtime.py)), a 50 Hz default control
contract ([`control/models.py`](../../src/parcel_robot/control/models.py)), and
a 50 Hz expression channel. The physical target must be profiled under real
Orin load before freezing deadlines.

## The production contracts

### `EmbodiedFrameV1`

Do not tokenize “all sensors” directly into one model. Specialized local
perception should turn raw camera, LiDAR, audio, and state into a time-aligned
frame, while raw data goes to the research recorder.

```text
header: schema, boot_epoch, sequence, monotonic_ns
provenance: source IDs, calibration IDs, model versions
freshness: age per channel, missing/stale mask, clock uncertainty
robot: SE(3) pose/covariance, body velocity, gait/mode, tilt, battery, faults
local_world: traversability/occupancy BEV, semantic regions, door/elevator state
agents[]: stable track ID, class, pose/velocity/covariance, predicted occupancy
owner: track ID, relative pose, voice/addressee confidence, consent scope
mission: task/revision/step/attempt, goal, queue/suspended IDs, route generation
path: committed prefix, revisable tail, corridor width, braking envelope
dialogue: turn/epoch, speaking/listening/barge-in, last accepted SteeringEvent
safety: stop latch, proximity state, sensor health, capability manifest digest
history: age-binned event summary for 60 s plus durable-memory reference IDs
```

Every continuous feature carries units and coordinate frame. Every modality
has explicit missingness; a zero value must never mean “camera missing.” The
hot history is a ring buffer, not a raw minute-long video context. Suggested
bins are full-rate for 2 s, pooled features/events for 2–15 s, and sparse
changes for 15–60 s. Durable owner/world memory is retrieved by ID with consent
and provenance, never silently folded into weights.

### `SemanticControlV1` — Model A output

```text
proposal_id, source_frame_sequence, task_id, plan_revision
valid_from_ns, valid_until_ns
plan_operation: keep | request_replan | hold | request_clarification
local_target: short SE(2) trajectory/corridor or bounded behavior vector
attention_target: none | owner | sound_track | semantic_track
expression: named reviewed overlay + gain + expiry
predicted_outcome: horizon, progress, uncertainty, risk features
narration_candidate: closed event code + evidence references
```

The gate rejects stale frame/task/revision, expired lease, unsupported
capability, occupied/braking-unsafe prefix, and critical-zone expression. A
“narration candidate” is only a prediction. It may say “I intend to head to the
sofa”; it may not say “done.” Global replan is a request that the planner and
executive can accept or reject.

Movement character belongs in a reviewed behavior vector—gait frequency,
speed scale, body height, head/gaze target, expression gain—not random joint
noise. Small “alive” motions should be deterministic-seeded, rate-limited, and
suppressed while stopping, on stairs/crosswalks, entering an elevator, near a
person, under poor traction, or during any critical control phase.

### `SteeringEventV1` — Model B ingress

```text
dialogue_turn_id, speaker_track_id, owner_confidence, addressee_confidence
utterance_digest, parsed_operation:
  stop | revise | interrupt_now | queue | keep | resume | status | clarify
grounded_target + confidence + evidence IDs
scope: active task ID/revision or explicit new task ID
priority, requested_checkpoint policy, created/expiry time
```

The local stop hotword/latch acts before this model. Ambiguous owner or target
identity yields `clarify`, not motion. Model B proposes; the task executive
realizes the transaction. A correction that should later return to the old
goal is a new child interruption task plus a suspended parent, not a destructive
overwrite.

### `ExecutionNarrativeEventV1` — Model B egress

```text
event_id, event: accepted | started | progress | blocked | replanned |
                       succeeded | failed | cancelled | resumed | resume_offer
task_id, revision, step_id, attempt
receipt_id, receipt_status, receipt_sequence, accepted_at_ns
evidence: observation/result IDs and validator disposition
tense: intended | running | waiting | terminal
resume_target_task_id, safe_to_speak, urgency, dedup_key
```

The validator must bind every claimed field to an authenticated, unexpired,
ordered receipt and the currently admitted task/step/attempt. DMC-1 proved why
this matters: its simplified validator accepted a completion with a wrong step
and attempt, accepted `started` after terminal, and accepted a fabricated task
claim carrying an unrelated trusted receipt ID. Reuse the stronger product
seams in [`brain/executive.py`](../../src/parcel_robot/brain/executive.py) and
[`voice/companion_state.py`](../../src/parcel_robot/voice/companion_state.py);
do not copy the research ledger.

## Door → sofa → keys → resume, as a transaction

1. Executive owns `door-trip` revision 1 and dispatches a short navigation
   step. Model A proposes local trajectories bound to that tuple.
2. Owner says, “Actually go back to the sofa and see if my keys are there.”
   Local audio cancels/truncates current speech; Model B emits an
   `interrupt_now` steering proposal with a grounded sofa target.
3. Executive requests a safe checkpoint, suspends `door-trip`, creates
   `sofa-keys` with parent `door-trip`, invalidates old proposal leases, and
   emits an accepted receipt. Only now may Realtime say, “Sure—I’ll check the
   sofa.”
4. Model A receives the new task/revision in its next frame. The global planner
   changes the revisable route tail; the tracker completes the committed
   braking-safe prefix and turns toward the sofa.
5. Camera/object search may report “keys not yet seen,” “keys found,” or
   “search exhausted.” Arrival and object detection are separate receipts.
6. On an accepted terminal receipt, Model B emits a terminal event plus
   `resume_offer=door-trip`. Realtime can say, “I checked the sofa. I found the
   keys. Want me to continue to the door?” It must not collapse “arrived” and
   “found keys.”
7. “Yes” emits an explicit resume steering event. The executive reissues from
   the saved checkpoint with lineage; implicit transformer memory is not the
   resume mechanism.

## Hosted Realtime integration and budget

The repository's hosted evaluation used `gpt-realtime-2.1-mini` in text-output
mode. OpenAI's current model card lists a 128,000-token context window, 32,000
max output tokens, function calling, and WebRTC/WebSocket/SIP access. Its
published prices are $0.60/M input text, $0.06/M cached text, $2.40/M output
text, $10/M input audio, $0.30/M cached audio, and $20/M output audio. The full
`gpt-realtime-2.1` card lists $4/$0.40/$24 per million text tokens and
$32/$0.40/$64 per million audio tokens. The full model is an unmeasured
quality challenger, not a result inherited by the mini arm
([mini model](https://developers.openai.com/api/docs/models/gpt-realtime-2.1-mini),
[full model](https://developers.openai.com/api/docs/models/gpt-realtime-2.1)).
Treat availability and prices as time-sensitive and meter actual usage.

Use small change-triggered text items or bound `function_call_output` records,
then request a response; the official conversation guide requires binding a
tool output to its `call_id`. On WebSocket barge-in, stop local playback and
truncate the unplayed audio from conversation state; otherwise the model's
history contains words the owner never heard
([Realtime conversation guide](https://developers.openai.com/api/docs/guides/realtime-conversations)).

Do not stream camera/LiDAR/10 Hz state to the hosted session. DMC-1 measured a
99.7% byte reduction from change-triggered event frames, though its fact-recall
oracle was invalid. The architectural conclusion still stands: push only
accepted task changes, deviations, questions, and terminal receipts.

Budget controls:

- hard monthly ledgers: Realtime $300, deliberative text $100; daily warning
  envelopes of roughly $10 and $3.33 without silently borrowing between them;
- local AEC/VAD, owner/addressee gate, and silence suppression before uplink;
- `response.done` usage recorded by session/mission and a hard refusal when
  the ledger is unknown or exhausted;
- session compaction by task/event summaries, not by replaying raw transcripts;
- a 7-day duty-cycle pilot before forecasting minutes/month—the official price
  is per token, so an assumed dollars-per-minute value is not an audit; and
- Starlink/network loss must only degrade speech/remote reasoning. Local STOP,
  safety, tracking, and task state continue offline.

The existing companion prompt already has the requested relationship default:
[`realtime/relationship_prompt.py`](../../src/parcel_robot/realtime/relationship_prompt.py)
and [`runtime_assets/prompts/system/core.md`](../../src/parcel_robot/runtime_assets/prompts/system/core.md)
say the robot is an ongoing companion friend, maintains consented continuity,
and never turns “sticking around” into surveillance or movement authority.

## Preventing false stalls around people

A global distance threshold cannot learn that proximity is “safe.” Safety
depends on relative velocity, predicted path overlap, uncertainty, body
orientation, free corridor, braking distance, social zone, and task. Use a
three-part design:

1. **Track and predict.** Fuse camera detections and LiDAR clusters into stable
   pedestrian tracks with velocity/covariance. Predict occupied space over a
   short horizon and retain multiple modes where intent is ambiguous. Track
   age and sensor freshness explicitly.
2. **Plan socially.** Optimize a local corridor against collision probability,
   time-to-collision, progress, lateral comfort, visibility, and jerk. A person
   moving beside the dog at matched velocity is different from one crossing
   its path. Prediction may reduce unnecessary conservatism but never weaken
   the hard emergency/braking envelope.
3. **Resume quickly.** Use an asymmetric blocker state machine: enter STOP on
   one high-risk fresh observation; leave only after a fresh, reachable corridor
   is clear for 2–4 consecutive frames and predicted risk stays below threshold.
   Keep a braking-safe committed trajectory prefix and calculate a revisable
   tail while waiting, so clearance resumes locally without a cloud/global-plan
   round trip. Replan only if the route—not merely one transient sample—is
   invalid.

DMC-1's authored slice suggests 0.3 s p95 clearance with explicit two-frame
hysteresis versus 0.7 s for a conservative six-frame rule, while the explicit
controller had lower mean hold than the GRU. That is a tuning hypothesis, not
a pedestrian result. Calibrate it in sensor replay and physics simulation with
false-clear flicker and dropout before product use.

Scenario-specific rules:

- **Sidewalk alongside humans:** formation-relative track, side preference,
  speed matching, overtaking/cut-in prediction, minimum usable corridor, and
  progress-without-contact metrics. Do not repeatedly stop for a same-direction
  track outside the swept-volume corridor.
- **Crosswalk:** require crosswalk/curb/ramp semantics, signal or owner policy,
  time-to-clear margin, traffic-object tracking, and an abort/continue rule that
  avoids freezing in the vehicle lane. This is a separately commissioned
  capability; social proximity learning is insufficient.
- **Elevator:** model door plane/state, threshold/gap, car occupancy, people
  exiting first, narrow-corridor priority, and a bounded entry/turn/exit state
  machine. Loss of door state or localization holds outside the threshold.
- **Stairs:** a locomotion and perception skill with pitch/step geometry and
  payload-specific validation. It is never a generic navigation waypoint.

Recommended navigation metrics are contact count/severity, minimum TTC,
personal-space intrusion integral, false-stop rate, clear-to-progress p50/p95,
progress efficiency, time in stop-and-go, replans per minute, crosswalk
exposure time, elevator entry/exit success, sensor-stale motion, and human
comfort ratings. [SocNavBench](https://arxiv.org/abs/2103.00047) provides a
grounded social-navigation evaluation precedent, while
[HuNavSim](https://arxiv.org/abs/2305.01303) provides ROS 2 human behavior and
metric machinery; neither certifies this robot.

## Simulator and learning system

Do not build a new physics engine. Build one scenario/evidence orchestrator
over complementary simulators:

| layer | purpose | use now |
|---|---|---|
| deterministic contract/replay | millions of task, revision, receipt, loss, and dialogue-order cases | keep; rebuild trace-first with an external oracle |
| current headless city | fast product navigation and instruction regression | teacher/replay collection, not dynamics |
| current MuJoCo city | runtime integration and semantic navigation | add dynamic humans/audio timing; not photoreal perception |
| Unitree `unitree_rl_mjlab` | vendor-supported Go2 MuJoCo locomotion training/play/sim-to-real path | install in an isolated environment; first reproduce an unmodified Go2 flat-velocity baseline |
| Isaac Lab / Isaac Sim | RGB-D/LiDAR, contacts, lighting, payload/terrain randomization, large parallel training | primary perception+dynamics world; preserve identical policy I/O across engines |
| HuNavSim / social replay | controlled pedestrian behaviors and social metrics | sidewalk/crosswalk/elevator scenario overlay |
| hardware-in-loop | Orin timing, gateway, sensor clocks, recorded/replayed actuators | required before stationary/tethered robot stages |

Unitree's current official
[`unitree_rl_mjlab`](https://github.com/unitreerobotics/unitree_rl_mjlab) is a
better starting point than a bespoke Go2 dynamics model. Isaac Lab's official
sim-to-sim guidance says the same checkpoint may be transferred between PhysX
and Newton only when action/observation/state/timing/mechanism/episode contracts
match; expect similar behavior, not identical trajectories, and treat it only
as a first step toward sim-to-real
([guide](https://isaac-sim.github.io/IsaacLab/develop/source/how-to/transfer_policies_between_physx_and_newton.html)).

Every scenario manifest should freeze:

- simulator/asset/calibration/version digests and seeds;
- layout, route, lighting/weather, friction, payload/center-of-mass, actuator
  delay/gain, sensor extrinsics/noise/dropout, clock skew, and network
  jitter/loss;
- pedestrian trajectories and hidden intent, owner voice/addressee/ASR truth,
  interruption text/audio/timing, task/receipt corruption schedule; and
- independent success, safety, social, conversation, and latency oracles.

Family-disjoint splits must hold out buildings/layouts, object/place
compositions, command paraphrase authors, owner voices, pedestrian trajectory
families, lighting, and sensor/network regimes. Keep sentinels/oracles and the
deterministic L1 baseline. Report pass^k and seed-level failures, not one mean.

### Governed self-learning loop

1. On-robot ring records aligned observations, proposed/admitted/executed
   commands, gate reasons, task ledger, receipts, conversation events, and
   human feedback with schema/model/calibration versions.
2. A bounded encrypted spool uploads consented bundles when connected.
3. External storage keeps MCAP/object blobs; PostgreSQL holds mission/event
   metadata and consent/deletion lineage; object/semantic memory uses explicit
   records and optional vector indexes; an experiment registry links dataset,
   code, seed manifest, checkpoint, and eval.
4. Offline jobs derive deterministic labels first, then human review for
   ambiguity. Never use the model's narration as ground truth.
5. Train candidate heads on a server; evaluate against frozen family-disjoint
   suites, a second physics backend, corruption/fault injection, and calibration.
6. Deploy challenger in shadow on Orin. Compare its raw risk, progress, latency,
   energy, and disagreement with the executed deterministic champion.
7. Promote only through signed, versioned configuration after safety review;
   rollback remains one action. No autonomous on-robot weight updates or
   self-authored acceptance bars.

This is closer to [RMA](https://arxiv.org/abs/2107.04034)—a fixed base policy
with rapid adaptation to environment factors—than to unrestricted online
self-modification. Language-motion interfaces such as
[RT-H](https://rt-hierarchy.github.io/) are useful for correction collection,
while closed-loop environment/success/human feedback follows the direction of
[Inner Monologue](https://arxiv.org/abs/2207.05608). Asynchronous action
chunking such as [RTC](https://www.physicalintelligence.company/download/real_time_chunking.pdf)
is worth testing for trajectory continuity, but its published evidence is
mainly manipulation/controlled tasks and it must not blur the STOP boundary.

## Evaluation matrix

Before physical motion, run matched P0–P5 arms:

- P0 current product;
- P1 deterministic ledger + explicit temporal local controller (recommended
  champion);
- P2 Model A shadow only;
- P3 Model B typed ingress/egress only;
- P4 coordinated A+B candidate; and
- P5 naïve joint A+B sentinel expected to expose coupling failures.

Minimum suites:

1. transaction traces: addition/revision/retraction/queue/stop/resume/status,
   wrong task/revision/step/attempt, illegal order, duplicate, forgery, expiry,
   restart epoch, loss/reorder, and completion during barge-in;
2. navigation generalization: point/object/region/follow/search, unseen layouts
   and composition, recovery, and independent arrival authority;
3. social/dynamic navigation: sidewalk alongside/cut-in/overtake, crosswalk,
   elevator, groups/children/strollers, occlusion, clear flicker, sensor stale;
4. conversation: multi-turn context, interruption, grounding, capability
   honesty, receipt tense/timing, side talk, owner ambiguity, echo, packet loss;
5. dynamics/perception: payload, center of mass, slopes/stairs, friction,
   lighting/exposure, LiDAR interference, calibration/time skew; and
6. deployment: Orin p50/p95/p99 CPU/GPU/RAM/thermal/power, 24-hour process soak,
   gateway TTL/stop/feedback, network removal, log backpressure.

Hard gates require zero authenticated false completion, zero stale-revision
execution, zero post-STOP movement authorization, zero admitted occupied/
braking-unsafe corridor, and zero contacts in acceptance scenarios. Estimate
rare-event bounds with enough exposures; a handful of green demonstrations is
not a safety rate.

## Current evidence and readiness

- Two fresh NAV_INSTRUCT v4 invocations selected the same 125 episodes and
  reproduced SR 0.272 / SPL 0.205777 / mean DTG 8.193 m. Broad navigation is
  not ready: 36 planning, 24 termination, 13 grounding, 11 search, and seven
  false-arrival failures remain.
- Two current follow-bench invocations reproduced 7/9 follow and 2/2
  navigation successes. The `pedestrian_group` and `pedestrian_cut_in` follow
  cases miss their contracts, and the broader 475-episode dynamic-social study
  retained contacts in every arm.
- Same-day conversation replay is 6 PASS / 8 MIXED / 11 FAIL across 25 threads,
  with 66 risk flags. It is a historical captured model corpus, not a current
  hosted-model measurement.
- The incomplete hosted Model B stage stopped at 61 robot turns, below its
  registered floor, with 0.819 grounding, 0.294 coverage, and 19
  machine-flagged invented actions. It lacks the hosted direct arm and blind
  adjudication, so it is negative stage evidence rather than a completed
  comparison.
- The repaired 25-case null-sink acoustic suite completed three times. Its gate
  vector was stable at 5/9 pass: endpoint p50, acoustic stop p50, duplex
  acknowledgment p50, and prosody timing fail. One barge-in case also changed
  verdict across runs. Physical microphone, loudspeaker, AEC, and room
  acoustics remain unmeasured.
- NAV-INT-1 completed after the first report draft and refuted all three
  registered hypotheses. Admission was 24/32, amended-goal success 11/28,
  return 8/9 with 1.4905 mean oracle path ratio, and arrival authorities
  disagreed on 17/80 legs. Its blind steering classifier is 0.827 overall;
  queue is 0.667 and clarify 0.800. A post-hoc 0.973 classifier is useful
  engineering but not blind evidence.
- DMC-1's learned A1 missed promotion, made more raw-unsafe/wrong-route
  proposals than deterministic arms, and its narration/receipt oracle failed
  independent counterexamples.
- DMC-2 independently verified 8,448 cases per run across the real executive
  seam and the real dialogue receipt/claim seam, with identical normalized
  roots on two runs. The architecture gate is nevertheless red: the product
  still lacks a trustworthy executive-to-receipt bridge carrying task,
  revision, step, attempt, source epoch, and speech generation.
- The current five-case embodied product-path evaluation passes all four
  supported frozen cases with zero kinematic collisions, while moving-owner
  `FollowFormation` is explicitly unsupported. This is integration evidence,
  not generalization or physical evidence.
- The existing runtime has valuable production boundaries: the executive
  checks task/revision/step/attempt; the authenticated dialogue reducer checks
  identity, TTL, sequence, and transitions; the arbiter/collision/finalization
  path is the sole dispatch route; `ControlManager` fails closed on stale
  feedback. None has been validated on this Go2/Orin hardware.

Simulator feasibility is **high** for task transactions, conversation-motion
alignment, fault injection, dataset generation, and social-policy ranking;
**moderate** for perception and locomotion transfer when multiple physics
engines and domain randomization are used; and **low as proof of physical
safety or acoustic/mechanical integration**. Simulation should drive most
capability development, but it cannot waive hardware commissioning.

## Prioritized implementation

### P0 — next 1–2 weeks

1. Freeze the four contracts above and add append-only traces at the real
   executive/receipt/dispatch/Realtime boundaries.
2. Implement a real plan stack with parent/child lineage and explicit resume
   offer; do not rely on destructive amendment or LLM context.
3. Use the completed DMC-2 seam benchmark as a regression test, then build the
   missing production bridge that mints receipts from exact executive results;
   extend DMC-2 to make its architecture-level rows evaluable and green.
4. Use the repaired acoustic evaluator to fix endpointing, acoustic stop,
   acknowledgment, and prosody timing; then add real AEC/mic/speaker replay,
   owner/addressee ambiguity, and receipt-grounded narration.
5. Keep L1-style temporal blocker logic as champion; add A0/A1 only in shadow.

### P1 — next 2–6 weeks

1. Integrate official Go2 MuJoCo baseline and reproduce it untouched.
2. Build the same scenario API in Isaac Lab; run the PhysX↔second-backend
   matrix with identical policy contracts.
3. Add tracked-human predicted occupancy and sidewalk/elevator/crosswalk
   suites; tune asymmetric stop/resume hysteresis from replay, not intuition.
4. Add AEC/audio/noise/network emulation and a deterministic fake-Realtime
   provider; paid Realtime is a small final arm with an enforced ledger.
5. Stand up the encrypted spool + object store + metadata/consent/experiment
   registry; begin champion/challenger shadow data collection.

### P2 — only after simulator gates

1. Benchmark on the actual AGX Orin 64 GB, including concurrent perception,
   audio, logging, and thermal soak; choose model size from measured headroom.
2. Hardware-in-loop gateway/state/clock/TTL/e-stop tests with motor authority
   disabled, followed by stationary commissioned Stage 0.
3. Measure payload/center-of-mass, power, thermal, EMI, sensor extrinsics/time
   sync, acoustic echo, stop latency, and braking distance.
4. Proceed to tethered, speed-capped, cleared-space motion only after signed
   review. Sidewalk, crosswalk, elevator, and stairs each require their own
   later promotion gate.

**Overall mount verdict: the software architecture is converging, but the
system is not ready for motion-enabled physical mounting.** It is reasonable
to mount powered-off/observe-only hardware for mechanical, sensor, time-sync,
audio, and HIL work after an engineering checklist; it is not reasonable to
enable autonomous base motion yet.
