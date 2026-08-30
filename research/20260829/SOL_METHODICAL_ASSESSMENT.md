# Sol methodical assessment: duplex companion autonomy

**Research date:** 2026-08-29
**Final synthesis:** 2026-08-30
**Target:** Unitree Go2 EDU+; likely AGX Orin 64 GB; camera; Mid-360-class
LiDAR; microphone array; speaker; Starlink uplink
**Evidence status:** desktop code, replay, deterministic simulation, and
procedural semantic simulation only
**Physical-motion decision:** **NO-GO**
**Observe-only / motors-disabled mount:** **CONDITIONAL**, after an engineering
checklist
**Document status:** **FINAL. DSOAK-1 is complete as a self-reported, partially
corroborated run with post-run aggregate-consistency verification; the
commit tier is green, while the extended nightly tier has controlling red
capability/regression findings recorded below.**

**Independent closeout:** three fresh read-only Sol Ultra audit passes retained
physical NO-GO. Bounded source defects in profile/target wiring, checkout provenance,
revision exception atomicity, navigation failure mapping, Model-B drain
lineage/freshness, terminal-pose geometry identity, and the explicit disarmed
launch assertion were repaired and regression-tested. The second pass then found
service lifetime/environment precedence, valid Model-B lifecycle, and concurrent
revision-compensation defects; their postfix panels passed 33, 14, and 14 tests,
with a combined 91/91 selection. A third pass found stale service parity,
non-fail-loud target activation, broader owner-valid lifecycle, and shared-sink
lock-order gaps; its exact adversarial panel passed 19/19 after repair. The controlling hardware,
nightly, sensing, privacy, and deployment-artifact blockers remain open; see
[`SOL_ULTRA_FINAL_AUDIT.md`](SOL_ULTRA_FINAL_AUDIT.md) and
[`SOL_ULTRA_POSTFIX_AUDIT.md`](SOL_ULTRA_POSTFIX_AUDIT.md).

This final assessment consolidates the evidence available in the 2026-08-29 research
artifacts. It deliberately separates architectural promise, harness conformance,
simulated capability, and physical evidence. Five hundred *simulated* stream-hours
in DMC-1 are not twelve wall-clock hours and are not a substitute for hardware
qualification. The completed DSOAK-1 result is included with its late-monitor,
verifier, and oracle-validity limitations.

## Executive outcome

The proposed Model A / Model B idea is directionally right, but it should not be
implemented as one end-to-end foundation model that owns sensor interpretation,
global planning, quadruped control, task completion, and speech. The production
shape should be a typed, multi-rate system:

- **Model A** is a trainable embodied-policy package with a shared temporal state,
  a 10 Hz fast proposal head, and an event-driven 0.5–2 Hz planning head. It may
  propose short trajectories, attention, expression, risk, progress, and replans.
  It does not own joint stabilization, final collision/braking authority, STOP, or
  mission completion.
- **Model B** is two independently evaluated functions. Its ingress converts an
  owner-qualified utterance into a typed steering proposal; its egress converts an
  independently accepted execution event into a compact narration frame. Hosted
  Realtime realizes friendly prose and prosody but never establishes that an action
  happened.
- A deterministic **task executive, arbiter, safety shield, motion gateway, and
  receipt validator** remain the authority spine. Every motion proposal has a short
  lease and exact task lineage. Every completion statement must be licensed by an
  authenticated result for that exact task, revision, step, attempt, process epoch,
  and speech generation.

The architecture is plausible and aligns with the reviewed streaming-navigation,
hierarchical-policy, intervention, feedback, and real-time chunking literature. The
current implementation and evaluations do not establish generalized autonomy. Fresh
NAV_INSTRUCT success is 34/125; two scripted follow cases fail; DSP-2's S2/S3
arms each contact in 25/145 episodes; all registered interruption hypotheses
are refuted; corrected acoustic v2 passes 6 gates, fails 3, and leaves 2
unmeasured, including four invalid endpoint fixtures and a 0.790 s virtual
audible acknowledgement; the machine-scored
hosted-Q narrator fails every absolute gate; and DMC-4's passing source-level
transaction now reaches only a process-local, non-speaking runtime observer—not
the live session, provider, or audio path.

The correct near-term strategy is therefore:

1. keep explicit temporal logic as the executed champion;
2. keep learned Model A heads shadow-only;
3. extend the new process-local DMC-4 observer through a restart-safe cursor,
   live speech epoch, provider context, cancellation, and audio delivery;
4. build family-disjoint, dynamic-human, audio/network, and multi-engine simulator
   curricula around the production contracts; and
5. proceed through motors-disabled HIL, stationary commissioning, and tethered
   low-speed testing only after the simulator and transaction gates close.

## Readiness decision card

| Item | Decision | Basis |
|---|---|---|
| Multi-rate Model A / typed Model B design | **Proceed** | Matches the production safety boundary and literature pattern |
| One model consuming all raw streams and directly controlling the body | **Reject** | Cannot meet independent authority, timing, observability, or fail-closed requirements |
| Learned Model A in command | **Do not promote** | In MA-2, teacher/reflex/direct each solved 198/198 held missions while every S/C16 learned seed solved 0/198 |
| Model A mounted proposal path | **Absent** | No qualified learned artifact exists; the standard launcher neither injects nor arms a commissioned physical manager, and normal backend observations are wrapped with simulation provenance |
| Receipt-grounded spoken completion | **Disarmed runtime frames green; live speech red** | DMC-4's frames preserve exact available authority lineage and are revalidated at drain; persistent cursor, commit-time timestamp, independently authenticated live speech epoch, provider/audio acknowledgement, and authoritative separate-child resume lineage are absent; LIT-1 retains 5/5 old-path false terminal claims |
| Simulator-first capability program | **Proceed aggressively** | High value for contracts, coverage, fault injection, counterfactual replay, and relative ranking |
| Powered-off / observe-only / motors-disabled integration | **Conditional** | Useful for mechanical, sensor, clock, audio, data, and HIL work after checklist review |
| Autonomous physical movement | **NO-GO** | Generalization, social safety, acoustics, physical sensing, Orin timing, gateway qualification, and stop distance are not proven |
| Sidewalk, crosswalk, elevator, or stair autonomy | **NO-GO** | Each remains a separate uncommissioned capability requiring its own promotion gate |

## Recommended production architecture

```text
camera / LiDAR / IMU / robot state / acoustic features / owner context
                  |
       local perception + tracking
                  |
             EmbodiedFrameV1
                              @ 10 Hz
                                 |
               +-----------------+------------------+
               |                                    |
       Model A fast proposal               Model A slow planner
          nominally 10 Hz                 event-driven, 0.5–2 Hz
               +-----------------+------------------+
                                 |
             SemanticControlV1, task/revision bound, short lease
                                 |
       task executive -> arbiter -> safety/freshness/braking gates
                                 |
                  ControlManager @ nominal 50 Hz
                                 |
                    gateway -> vendor locomotion
                                 |
            authenticated observation / execution result
                                 |
             ExecutionNarrativeEventV1 -> Model B egress
                                 |
             compact accepted event -> hosted Realtime -> speech

owner utterance -> local endpoint/addressee -> Model B ingress
                -> SteeringEventV1 -> task executive / plan stack

local STOP ==================> latched safety / ControlManager stop boundary
                              (never waits for Model A, Model B, or the network)
```

The cadences above are design targets, not measured Go2/Orin guarantees. The
checkout already has a 10 Hz `RobotRuntime`, a nominal 50 Hz control contract, and
a separate expression lane, but concurrent target-hardware timing, thermals, power,
and deadline tails remain unmeasured. The vendor locomotion controller should retain
gait and joint stabilization. Parcel should command only bounded, reviewed semantic
or base-velocity interfaces through one sole-writer gateway.

### Contract boundaries

The four proposed contracts should be frozen and versioned before a larger learned
model is added:

- `EmbodiedFrameV1`: time-aligned local state, modality freshness/missingness,
  pose and robot health, occupancy/traversability, tracked people and predicted
  occupancy, owner/addressee confidence, exact mission lineage, path prefix/tail,
  dialogue state, safety state, and age-binned history.
- `SemanticControlV1`: a bounded trajectory or behavior proposal, attention and
  reviewed expression proposal, plan operation, calibrated progress/risk, source
  frame, expiry, and exact task/revision identity.
- `SteeringEventV1`: owner-qualified `stop|revise|interrupt_now|queue|keep|resume|
  status|clarify`, grounded target/evidence, exact scope, priority, checkpoint
  policy, and expiry.
- `ExecutionNarrativeEventV1`: accepted execution state and exact task/revision/
  step/attempt/epoch/speech-generation identity, receipt and evidence, tense,
  resume target, and deduplication key.

Raw camera, point clouds, and minute-long audio/video should be retained only by the
consented research recorder. Model A should receive specialized representations,
explicit uncertainty, and explicit missingness. A useful hot-memory allocation is
full-rate features for the last 2 seconds, pooled features/events from 2–15 seconds,
and sparse changes from 15–60 seconds. Durable memories should be retrieved as
versioned records with provenance and consent, not hidden inside model weights.

### Door → sofa → keys → resume

The user's example should be implemented as an explicit transaction, not as implicit
LLM context:

1. The executive owns the door mission and dispatches a short step. Model A proposals
   carry its task/revision/step/attempt tuple.
2. The owner says, “Actually go back to the sofa and see if my keys are there.” Local
   audio truncates current unheard speech; Model B proposes `interrupt_now` with a
   grounded sofa target.
3. The executive reaches or requests a braking-safe checkpoint, suspends the door
   task, creates a child sofa/keys task, invalidates old leases, and emits an accepted
   event. Only then may the voice acknowledge the change.
4. Model A receives the new authoritative task in the next frame. A committed safe
   prefix finishes; only the revisable route tail turns toward the sofa.
5. Arrival, object search, “keys found,” and “search exhausted” remain separate
   receipts. Reaching the sofa never implies seeing the keys.
6. After a verified terminal event, Model B may offer the suspended door task. A
   spoken “yes” becomes an explicit resume event and the executive reissues work from
   the saved checkpoint.

This transaction is what tightly couples body and dialogue without giving prose
motion authority.

## Model A recommendation

Model A should be one *trainable package* but not one clock and not one command
authority. A shared temporal encoder can support several separately calibrated heads:

- a 0.5–1.0 second local trajectory chunk or bounded behavior vector;
- progress, deviation, time-to-recover, collision-risk, and out-of-distribution
  estimates;
- predicted multi-modal occupancy for tracked people;
- a short subgoal or `keep|request_replan|hold|request_clarification` operation;
- an attention target and reviewed expression with expiry; and
- a candidate narration event code that still requires independent validation.

The fast input should include proprioception and gateway freshness, compact LiDAR
and traversability features, cached visual/depth embeddings, stable semantic and
human tracks, exact mission/task state, committed-path prefix and revisable tail,
audio events, and age-binned memory. The slow visual/map lane can reuse cached
features, but no Orin-resident language model should be required to meet a 10–50 Hz
safety deadline.

Train with deterministic-teacher and successful teleoperation traces first, then
DAgger/counterexample replay in simulation, then consented physical shadow data only
after commissioning. Store raw proposals separately from admitted and executed
commands. Safety-gate acceptance must never become a label generated by Model A
itself. Promotion requires blind-family improvement in mission success and progress
calibration with no regression in raw risk, false arrival, gate intervention,
latency, or STOP behavior.

The current learned candidate has not earned execution scope. In DMC-1, A1 reached
1,496/1,500 procedural mission success, but deterministic L0 reached 1,500/1,500;
A1 emitted 3,781 raw-unsafe proposals and 296 wrong-route moves. The temporal GRU's
held-out macro-F1 improvement over the snapshot MLP was 0.01886, below the frozen
0.05 promotion margin, and the generator leaked authored cues. L1 explicit temporal
logic matched A1's 0.3 s liveness p95 with lower mean excess hold. The controlling
decision is explicit temporal logic as champion and learned heads as offline/shadow
challengers.

MA-2 is the controlling causal follow-up. It produced a leakage-checked
300-episode teacher substrate and held out scene, target-role, task-family, and
combined factors. Teacher, sector reflex, and direct-bearing controls each
solved 198/198 held missions; all three seeds of both the snapshot MLP and
16-frame GRU solved **0/198**. On the hardest frozen rows, learned direction
accuracy was still 0.990–0.998 and MSE 0.00133–0.00182, showing that open-loop
scores concealed immediate state-distribution shift. P2 should collect
learner-visited recovery states through DAgger/interventions and test a residual
or hybrid challenger with the direct/reflex controller retained as fallback;
scaling the same offline cloning objective is not justified.

Model A is also not physically composed. No qualified learned checkpoint is
loaded by the normal runtime, the standard Go2 profile selects a simulator
controller, and no non-test caller invokes `ControlManager.arm_and_set_target()`.
`Go2Backend` can observe selected telemetry but deliberately rejects move/pose/
trajectory calls. Normal runtime wraps `backend.observe()` in
`CarrierObservationSource` with `SIMULATION` origin, while
`PhysicalObservationSource` remains a fail-closed skeleton. These are independent
NO-GO blockers even if an offline policy later scores well.

“Alive” behavior should not be random joint twitch. Use reviewed, rate-limited,
deterministically seeded behavior parameters—gait frequency, speed, body height,
gaze/attention, expression gain—and suppress them during STOP, stairs, crosswalks,
elevator entry, close-person interaction, poor traction, or other critical phases.

## Model B and hosted conversation recommendation

Model B should be split into independently scored steering and narration stages:

1. **Steer:** final owner/addressee-qualified transcript plus task stack and world
   context becomes a typed operation and grounded scope. A local STOP path acts
   before this model. Ambiguous speaker, referent, or target produces `clarify`, not
   movement.
2. **Narrate:** accepted execution changes and authenticated receipts become small
   typed state items. A deterministic validator selects tense and whether speech is
   licensed; the hosted model selects natural wording and prosody.

Hosted Realtime should receive change-triggered accepted events, not camera/LiDAR or
10 Hz state. Its connection may fail without affecting STOP, safety, tracking, the
task ledger, or offline canned status. On barge-in, local playback must stop and the
unheard output must be truncated from hosted conversation state. Tool outputs must
remain bound to their exact calls. Hosted speech is advisory and expressive; it is
never an execution ledger.

The companion prompt already encodes the requested default: the robot is an ongoing
companion friend that maintains consented continuity and supports the owner without
turning “sticking around” into surveillance or movement authority. Seventy-one prompt
contract tests passed. That is a prompt-contract result, not proof of warmth,
multi-turn quality, owner recognition, or grounded embodiment in a live room.

DMC-4 closes a narrow source-level executive-to-narration transaction for every
constructible frozen transition family: the authority owner appends a bounded
journal of immutable records, and a journal-only consumer maps contiguous rows
one-to-one into authenticated non-actuating events. Two runs each covered 1,824
accepted mutations; 256 corruptions, replay, concurrency, and overflow failed
closed. Post-evidence maintenance restored resource-conflict diagnostics and
reproduced the exact trace roots.

The source schema is not yet a complete production contract.
`RobotRuntime` now keeps the bare executive as owner and polls DMC-4 through a
process-local authenticated, fail-closed observer into bounded non-actuating
frames. Post-review hardening retains plan, revision, step, attempt, mission,
action, evidence, source epoch, speech generation, and deadline in each frame,
then atomically revalidates epoch/generation/deadline immediately before drain.
Production still needs key ownership beyond one process, persisted executive/
outbox and read/consume/provider-ack cursors, independently authenticated live
`source_epoch` and speech-generation binding, separate-child resume lineage,
provider-context delivery, and cancellation/backpressure across restart and
barge-in. Commit-time freshness remains absent because the bridge still starts
TTL when it polls a transition rather than when the executive committed it.
LIT-1's five failed
bench missions at about 3.33 m that produced five
“I've reached the bench” claims remain valid counterexamples for the old path.
No prompt can repair an unwired authority path.

## Literature synthesis

The detailed source review is in
[`literature/LITERATURE_REVIEW.md`](literature/LITERATURE_REVIEW.md). Its controlling
design conclusions are:

- NaVILA supports a hierarchy in which language produces spatial mid-level actions
  for a locomotion policy; it does not justify direct language-to-joint authority.
- TIC-VLA and related systems support asynchronous slow reasoning over a faster
  policy. StreamVLN supports bounded recent context plus compressed history instead
  of unlimited raw-stream replay.
- Hi Robot is a useful precedent for rerunning a high-level language/vision layer on
  an utterance while a faster chunked controller continues acting.
- RT-H and Inner Monologue support correction and closed-loop environment/success/
  human feedback, while RMA supports fixed-policy adaptation rather than unrestricted
  on-robot self-modification.
- Real-Time Chunking motivates committed action prefixes with revisable tails, but
  its evidence does not remove the independent STOP boundary.
- SocNavBench and HuNavSim provide social-scenario and metric machinery; neither
  certifies a Go2 for sidewalks, crosswalks, or elevators.

The literature does not contain a demonstrated equivalent of this whole target:
full-duplex owner dialogue, robust multi-turn task interruption, faithful embodied
narration, dynamic-human social navigation, Go2 dynamics, onboard Orin compute, and
Starlink degradation. The architecture therefore uses literature as design evidence,
not as transferred safety evidence.

## Exact evaluation results

### Navigation, social behavior, and instruction following

| Evaluation | Exact result | What it establishes | What it does not establish |
|---|---:|---|---|
| NAV_INSTRUCT v4, two fresh runs | 34/125 success = **0.272 SR**; SPL 0.2057774523; mean DTG 8.1932787 m; identical episode digest | Reproducible current generalized-navigation failure profile | Camera/LiDAR perception, dynamics, or physical collision safety |
| NAV_INSTRUCT failure taxonomy | 36 planning; 24 termination; 13 grounding; 11 search; 7 false arrival; 34 success | Failure priorities and independent authority disagreements | A promotion-ready navigator |
| Follow bench, two runs | **7/9 follow**, 2/2 navigate; 0 scripted contacts; minimum pedestrian surface 0.53 m | Reproducible scripted/oracle-track behavior | Re-identification or real sidewalk/crosswalk behavior |
| Follow misses | `pedestrian_group`, `pedestrian_cut_in` | Concrete dynamic-human gaps | Safe close-person operation |
| DSP-2 dynamic social | 580 episodes, 145/arm; contacts S0/S1/S2/S3 = 57/37/25/25; every S2/S3 contact was actor-into-stationary; H1–H4 refuted | Responsive-person and elevator/sidewalk family failures survive prediction/hysteresis | A usable physical contact rate or permission to reduce proximity globally |
| Embodied plan v1 | 4/4 supported cases pass; 1 moving-owner `FollowFormation` unsupported; 0 kinematic collisions/timeouts; 1,051 steps | Frozen `PlanIR` → executive → semantic-runtime integration | Unseen plans, gait/contact physics, real sensors, or moving-owner following |
| NAV-INT-1 | 40/40 runner-complete; instruction admission 24/32; amended success 11/28; return 8/9; path ratio 1.4905 | A reproducible interruption benchmark and red baseline | Reliable correction/resume |
| NAV-INT blind steering | 91/110 = 0.8273; revise 0.9000; keep 0.9333; queue 0.6667; clarify 0.8000; adversarial 27/40 | Realistic steering error profile | The post-hoc 0.9727 classifier is not blind evidence |
| NAV-INT authority | disagreement on 17/80 scored legs | Arrival truth is not consistently owned | Permission to narrate arrivals |
| LHO-1 guarded handoff | four runs × 1,980 paired schedules / 5,940 arm episodes; C/D have verified distinct sequential local-process provenance; G0 waiting 676.75 s vs B0 8,388 s (**-91.93%**), gaps 555 vs 6,183 (**-91.02%**); zero authored stale/safety violations | Latency-sized committed-prefix/revisable-tail scheduling is promising | Learned/2-D navigation, perception, dynamics, physical braking, Orin timing, or remote attestation |

Zero simulator collisions in NAV_INSTRUCT and the embodied-plan smoke test must not
be read as physical safety evidence: those paths use semantic ground truth and/or
deterministic kinematics. The broader dynamic-human evidence is explicitly red.

### Conversation, duplex timing, and action authority

| Evaluation | Exact result | Controlling interpretation |
|---|---:|---|
| Brain v1 | 15/15; all 7 expected fail-closed cases matched; 0 physical episodes | Typed admission/execution facts work on frozen cases |
| Scripted duplex v1 | 7/7 hard gates; 216 10 Hz frames; synthetic TTFT p50 35.53 ms | Text-injected harness only; no microphone, speaker, AEC, current hosted model, or production network |
| Corrected acoustic v2 | 25 cases / 223.4 s; **6 pass, 3 fail, 2 not measured**; endpoint cutoff and validity-failure rates each 0.3077; valid-only ep50/ep90 0.274/0.2916 s; virtual audible ack p50 0.790 s | Measurement validity is repaired on the virtual rig; semantic endpointing and audible acknowledgement remain red, while isolated acoustic STOP and physical motion sync remain unmeasured |
| Endpoint-policy sensitivity | two byte-identical 1,560-cell direct replays; 0/30 declared points pass; corrected-rig parity fails; closest semantic row is 49/52 valid with valid-only ep90 2.577 s | No production threshold/timeout change or provisional motion admission is supported; a frozen human/AEC holdout is required |
| Historical Realtime corpus | 25 threads, 174 turns, 0 machine hard failures, 66 review flags; semantic review 6 pass / 8 mixed / 11 fail | Historical, unblinded, uncalibrated corpus; current model/prompt not measured |
| Personal conversation fixture | 13/13 across eight families | Deterministic reference/harness ceiling only |
| MB-1 scripted Q vs scripted direct | grounding 1.000 / 0.8854; coverage 0.9688 / 0.7688 | Demonstrates harness sensitivity only; neither arm is a model result |
| MB-1 local Qwen2.5-7B Q4, CPU | grounding 0.9637; coverage 0.5225; 6 machine flags; new-goal acknowledgment 18/75; completion 51/55; resume 2/10; keys constraint 0/15; TTFT p50 633 ms; total p50 1.612 s | Incomplete event coverage; not an Orin/GPU result |
| MB-1 hosted Q | 120/120 scenarios, 164 robot turns; grounding 0.6120–0.7274; coverage 0.2283–0.2883; acknowledgment 99/225; completion 11–27/165; resume 10–11/30; keys 1/25; 45 machine action flags; exact latency n=5, TTFT p50/p95 1.271/1.990 s, total 3.337/3.967 s | Candidate Q failed every absolute gate; hosted D stopped at 2/120, so Q-minus-D and calibrated human quality remain unmeasured |
| DMC-2 | 8,448 cases/run, two runs, all independently correct; identical normalized trace and chain roots | Existing executive, receipt, and terminal-license seams conform independently |
| DMC-3 | H1–H3 passed twice; H4 partial/red | Pure consumer continuity works; owner-authored complete composition was then tested in DMC-4 |
| DMC-4 | two identical 1,824-mutation runs; 256/256 corruptions; replay, concurrency, bounded overflow; maintained source reproduced exact roots; post-review drain-expiry/lineage regressions pass | Owner journal → process-local non-actuating Model-B frames is wired with drain-time freshness; commit-time timestamp, restart-safe state/cursors, live session/provider/audio, and authoritative separate-child resume lineage remain red |
| LIT-1 grounding audit | **5/5 false terminal arrival claims** after `task_failed` / `semantic_target_unreachable` | Blocking counterexample for narration authority |

Historical acoustic v1's four red numbers were measurement-invalid: it sampled
endpointing after full WAV playback, inferred robot STOP from contaminated mixed
audio, misplayed acknowledgement rate, mixed prosody clock origins, reused matches,
and observed no motion. Corrected v2 instead records every commit on the sample
clock, requires exact post-final validity, uses rate-correct audio, separates
write-attempt and virtual-audible clocks, and performs monotonic one-to-one prosody
matching.

The corrected rig found `incomplete_02`, `incomplete_04`, `pause_01`, and
`pause_03` invalid. Six other complete and `pause_02` valid endpoints had ep50
0.274 s and ep90 0.2916 s, but the 30.77% semantic invalidity is controlling.
Virtual audible acknowledgement p50 was 0.790 s (p90 2.633 s), also red. Generic
barge-in detection/flush, noise false-trigger, and audio-transport prosody (13/14)
passed. Isolated robot-output acoustic STOP and physical motion/audio sync are
explicitly `not_measured`.

The follow-up direct sensitivity study evaluated 30 confidence/silence points over
52 phase variants twice. No point passed, direct-vs-rig parity failed, and the
apparently most semantically complete row (`0.98`) still had 3/52 premature cells
and valid-only ep90 2.577 s. A corrected diagnostic further found that, among 12
acknowledgements followed by resumed speech, the one-shot SmartTurn/0.85 s policy
canceled only 2 before commit and committed 10 before contradiction. This is
negative evidence against threshold tuning or provisional motion admission, not a
candidate policy. Two additional source-pinned runs drove all 52 default cells
through the actual `MicrophoneVoiceLoop` and matched the duplicate runner at every
30 ms sample-frame index, so the negative direct-replay result is not explained by
a state-machine transcription mismatch.

The real speaker sink now uses generation-bound, one-way cancellation and reports a
worker-observed first write attempt. A guarded 101-test runtime/acoustic selection
passed with four expected warnings; the corrected evaluator selection passed 23
tests. That clock is not DAC audibility, and Python callback/GIL/driver behavior is
not hard real time. All evaluation audio remains synthesized/null-sink. Physical
microphone/speaker geometry, walking noise, AEC, owner voice, room response, and
Starlink remain unmeasured. See [`ACOUSTIC_LOOP_V1_AUDIT.md`](ACOUSTIC_LOOP_V1_AUDIT.md),
[`acoustic-eval-v2/RESULTS.md`](acoustic-eval-v2/RESULTS.md), and
[`endpoint-policy-1/VERDICT.md`](endpoint-policy-1/VERDICT.md).

### MA-2 controlling learned-policy result

MA-2 P0 passed its causal teacher and transaction substrate on 300 episodes. In
P1, teacher/reflex/direct each reached 198/198 across seven held split families;
every snapshot-MLP and C16-GRU seed reached 0/198. The six learned runs incurred
322,573 rate/safety interventions while diverging, although the independent
gate admitted zero unsafe, stale-revision, ineligible-resume, or unbacked
terminal transitions. The verifier checked 1,980 closed traces / 677,784 frames,
42 open traces / 153,684 rows, 120,000 latency samples, and detected five of
five tamper mutations. `P1_REFUTED` is the controlling model-selection result.

### DMC-1 historical model study and durability status

DMC-1 ran 1,000 frozen plus 500 adversarial procedural episodes for five arms,
representing 500 simulated stream-hours, and 5,000 dedicated blocker cases. Its key
arm results were:

| Arm | Mission success | Raw unsafe | Admitted unsafe | Wrong route | Premature completion |
|---|---:|---:|---:|---:|---:|
| F0 flat/latest intent | 0/1,500 | 369 | 0 | 0 | 1,508 |
| L0 ledger + conservative snapshot | **1,500/1,500** | 458 | 0 | 0 | 0 |
| L1 ledger + explicit time | 1,495/1,500 | 372 | 0 | 0 | 0 |
| A0 ledger + snapshot MLP | 1,494/1,500 | 249 | 0 | 0 | 0 |
| A1 ledger + history GRU | 1,496/1,500 | **3,781** | 0 | **296** | 0 |

The zero admitted-unsafe counts came from an ideal semantic gate whose check was
definition-bound to the generator's occupancy field. They are not an independent
collision test or evidence that the learned proposals were physically safe.

Independent review invalidated DMC-1's receipt/narration oracle: it accepted a
terminal result with the wrong step and attempt, accepted `started` after terminal,
and licensed a fabricated task completion using an unrelated trusted receipt ID.
Its generator also exposed authored cues. The controlling verdict is **REFUTED for
promotion of learned Model A** and **INCONCLUSIVE for Model B truthfulness**. The
99.717% byte reduction from change-triggered event frames is useful transport
evidence only.

**DSOAK-1 completed with the scoped verdict `SUPPORTED_PROCEDURAL_SOAK`.** The
retained artifact self-reports 43,380.014 monotonic seconds (12.050004 hours) and
66,434 primary episodes (33,218 frozen and 33,216 adversarial), and recorded 664
sampled deterministic replays with zero mismatches. A1 succeeded on
66,116/66,434 missions (0.995213); all 17 serialized gate predicates were
recomputed true from retained counters. RSS moved from 729.703 to 751.133 MiB
with a fitted post-10-minute slope of 0.000817 MiB/hour. The verifier's 32-case
mutation campaign met all expected outcomes.

This pass does not promote A1: deterministic L0 succeeded on 66,433/66,434
missions, while A1 emitted 172,427 raw-unsafe proposals and 13,257 wrong-route
moves. Nor does it establish narration truth or independent safety. The DMC-1
receipt/narration oracle is refuted; `stale_action_acceptances` is unreachable;
and admitted-unsafe/post-STOP zeroes are coupled same-thread invariants. The
external monitor began 8,512.470 seconds (2.365 hours) after start, covers only
80.377% of final elapsed time, and has no hash chain. Successful replay digests
were not retained. It does not strictly bind process identity, temporal
ordering, source drift, or final-file handoff. The green result therefore
supports self-reported, partially corroborated frozen desktop procedural
durability only.

### Code and regression evidence

All listed pytest runs used the project guard and avoided the live owner stack,
simulator socket, and default persistent memory database:

- corrected acoustic-v2 evaluator/validity selection: **23 passed**;
- post-remediation runtime/beat/emote/acoustic selection: **101 passed** with
  four expected warnings;
- endpoint-policy deterministic self-check and fail-closed retained-run verifier:
  both passed; the experimental conclusion remains red;
- DMC-2 product seams: **2 passed in 0.41 s**;
- task executive plus companion-state authority: **63 passed**;
- companion relationship/dynamic/Realtime prompt contracts: **71 passed in
  0.80 s**; and
- final guarded hardening shards—mount boundary **659 passed / 4 skipped**;
  DMC/runtime **159 passed**; conversation **419 passed**; duplex/acoustic
  **264 passed / 1 skipped**; social navigation **279 passed / 7 skipped**;
  portability **485 passed**; and
- second-review postfix service/Model-B/revision selections: **33 passed**,
  **14 passed**, and **14 passed**, with a combined **91 passed**; and
- August 30 guarded commit tier—all hard rows passed; tier coverage selected
  **11,330 unique non-slow tests** from **11,417 total** (87 slow), with the
  default parallel/serial selections green and no new Ruff fingerprint beyond
  the 72-row baseline. A preliminary pass detected concurrent shared-root
  writes as intended; the quiet **280.3 s** repeat matched start/finish checkout
  identity (`f8518f…`) and passed every hard row.

The 6,785.5-second extended nightly tier is a controlling red result. Its
default suite passed 11,262 with 23 skips and 5 expected failures, mutation
testing killed 7/7 defects, and the final metamorphic duplicate passed 5 tests
with 2 expected failures. However, six degraded-pose arms missed their frozen
success floors. The slow selection reported 4 failed / 68 passed / 8 skipped /
3 expected failures / 1 unexpected pass plus three wheel-fixture setup errors.
Read-only attribution confirmed the current and frozen arms use the same 61-cell
substrate, runner, scoring rule, budget, and SR metric; this is a real behavior
regression, not a metric mismatch or flake. Current truth succeeds on 7/61;
the six drift arms succeed on 1/61, 2/61, 1/61, 1/61, 1/61, and 1/61 against
frozen count floors of 8, 5, 2, 6, 2, and 3. The strongest reproduced cause is
the later safety-driven increase from 0.42 m legacy grid inflation to about
1.0223 m isotropic clearance: a previously successful cell now reaches
`goal_blocked`/`semantic_target_unreachable`, while an in-process legacy-planner
counterfactual restores its success. Do not revert the safety envelope or move
the floors. Repair clipped-subgoal/frontier planning with directional clearance
and the correct MAP→ODOM goal transform, validate targeted counterexamples, then
rerun all 7×61 arms once.

The bounded follow-up did not rerun or waive those arms. It removed the retired
literal and held-out-name findings, made the wheel parity fixture independent of
this host's missing `ensurepip`, and added a one-shot alternate terminal-pose
re-solve behind the unchanged candidate, K0-region, clearance, etiquette, and
arbiter authorities. The affected focused selection passed 152 with 4 skips,
and the live lamppost E2E passed twice (79.89 s and 81.74 s). The repeated slow
selection returned **1 failed / 74 passed / 8 skipped / 3 expected failures /
1 unexpected pass** in 2,007.26 s. Its sole failure is the retained
undeclared-bystander assertion: the intended zero-collision deadlock reproduces,
but four safe startup slew requests make the veto fraction 28/32 = 0.875 rather
than the pinned 0.90. The evaluator was not changed after seeing the result.
See [`NIGHTLY_REMEDIATION_AUDIT.md`](NIGHTLY_REMEDIATION_AUDIT.md).

The broad selected suite initially returned 1,570 pass, 37 fail, and one expected
failure. Thirty-six failures were traced to cross-test SQLite accumulation. A clean
in-memory rerun returned 356 pass and one expected incompatibility with the explicit
persistence-migration test; that migration test passed with the override removed.
The remaining transient navigation failure passed alone. These results are useful
for software regression, not capability promotion. The final shard results are
desktop/injected-binding evidence, not SDK2-on-Go2, aarch64 execution, physical
sensor, stop-distance, or payload evidence. The shard totals overlap and are not
a unique-test count.

## Preventing false stalls around pedestrians

The robot should not learn a single smaller “safe distance.” Safe progress depends
on relative velocity, predicted path overlap, uncertainty, body orientation,
braking distance, corridor geometry, social zone, and task semantics.

Recommended design:

1. Fuse camera detections and LiDAR clusters into stable person tracks with velocity,
   covariance, age, and freshness. Predict multi-modal occupied tubes, especially
   when intent is ambiguous.
2. Optimize a short local corridor for collision probability, minimum TTC, progress,
   lateral comfort, visibility, jerk, and social intrusion. A matched-velocity person
   beside the dog is not the same as a person crossing the swept volume.
3. Enter STOP on one fresh high-risk observation. Resume only after a fresh reachable
   corridor is below risk for 2–4 consecutive frames. Recompute a revisable tail while
   stopped, preserving a braking-safe committed prefix, so clearance does not wait
   for cloud speech or a global replan.
4. Keep the emergency/braking envelope independent. Prediction can prevent needless
   conservatism but may not weaken the hard stop geometry.

DSP-2 performed that first comparison over 29 held-out family types and refuted
all four hypotheses. S2/S3 eliminated contacts in the narrow non-responsive
stratum but each retained 25 responsive-actor contacts, concentrated in group
gaps, overtaking, and elevator exit/temporary-clear schedules. All were actors
moving into a stationary robot, which reveals a missing **controllability and
escape** model: STOP alone cannot avoid an actor whose future swept volume enters
the stopped dog's body. S3 also made false blocking 19.97% worse than S2.

The next study should therefore add learner-visited responsive-person cases,
multi-modal intent, counterfactual “was any admissible escape available?” labels,
side-step/withdraw/refuse-entry actions, staged safe havens outside elevator
doors, and separate any-contact, robot-caused, and preventable-contact metrics.
The hard acceptance corpus still requires zero contacts; impossible authored
trajectories must be labeled expected refusal/non-constructible rather than
silently averaged away.

LHO-1 independently supports the local scheduling mechanism: its guarded
latency-sized prefix reduced authored waiting 91.93% and gaps 91.02% versus
blocking while preserving stale-tail/STOP/occupied-prefix gates. Implement it
only after sizing the prefix from measured target latency, uncertainty-aware
2-D/3-D free corridor, and commissioned braking. It is not evidence that a
person's proximity is safe.

Crosswalk, elevator, and stairs cannot be treated as generic proximity variants:

- Crosswalk logic needs curb/ramp/crosswalk semantics, traffic and signal policy,
  time-to-clear margin, and an explicit continue/abort rule that avoids freezing in
  the vehicle lane.
- Elevator logic needs door-plane and door-state perception, gap/threshold handling,
  exit-first social priority, car occupancy, and a bounded entry/turn/exit state
  machine. State uncertainty holds outside the threshold.
- Stairs need a payload-specific perception and locomotion skill with geometry,
  pitch, contact, stability, and recovery validation.

## Simulator and recursive-learning feasibility

Simulation is the right main capability-development environment, with carefully
bounded claims:

MJLAB-1 tested the official `unitreerobotics/unitree_rl_mjlab` stack at commit
`1425b15`. Its strict clean-install gate failed because unconstrained transitive
versions selected incompatible MuJoCo/Warp APIs. With explicit environment-only
pins, two 64-environment CUDA runs delivered **5,933–6,199 environment-steps/s**
over 32,768 timed steps with finite tensors. The upstream trainer then executed
4,608 PPO steps, checkpoints, reload, and ONNX export in 13.20 s / 3.009 GiB.
Reward worsened over three iterations and resets were common, so this establishes
practical lower-locomotion plumbing—not a useful walking policy or transfer.

SOS-1 now has controlling current-source maintenance evidence for a distinct
stop-only Unix principal: it can observe and latch exact-zero STOP but cannot
acquire or send arbitrary motion. Concurrent maintenance first exposed a real
READY-before-signal-handler race; the red evidence was retained, the product
ordering was repaired, and review then replaced an instantaneous process-state
oracle and tightened a false-positive verifier. Two parallel and two sequential
256-case runs now pass H1-H5 with one normalized digest and strict hash/schema/
tamper checks. This remains a software deployment primitive—not a physical
E-stop; real GPIO/remote/voice inputs, target timing, firmware, braking, and
simultaneous Orin/gateway failure remain untested.

- **High feasibility:** task transactions, queue/interruption semantics, narration
  corruption, fault injection, dataset generation, counterfactual replay, scenario
  coverage, social-policy ranking, latency scheduling, and deterministic regression.
- **Moderate feasibility:** perception and locomotion transfer when the same policy
  contract is exercised in multiple engines with payload, dynamics, sensing, visual,
  latency, and network randomization.
- **Low feasibility as proof:** mount integrity, power/thermal/EMI margins, real AEC
  and acoustics, sensor calibration, foot-ground contact, actuator braking, human
  comfort, or real stop distance.

Do not build another physics engine first. Build one manifest/evidence orchestrator
over complementary backends:

1. deterministic task/receipt/dialogue schedules for millions of cheap transaction
   corruptions;
2. the current headless semantic city for instruction, recovery, and replay data;
3. the current MuJoCo city for runtime integration;
4. official Unitree `unitree_rl_mjlab`, beginning with an untouched Go2
   flat-velocity baseline;
5. Isaac Lab/Isaac Sim for camera/depth/LiDAR, contacts, lighting, terrain, payload,
   and parallel randomization;
6. HuNavSim or compatible ROS 2 social scenarios for controlled pedestrians and
   social metrics; and
7. the exact Orin process topology in motors-disabled HIL before stationary or
   tethered robot stages.

One scenario manifest should freeze engine and asset versions, seeds, layout and
route, lighting, friction, payload/center of mass, actuator delay/gain, sensor
extrinsics/noise/dropout, clock skew, network loss/jitter, pedestrian hidden intent,
voice/addressee truth, instruction timing, and independent oracles. Splits must hold
out layout families, place/object compositions, paraphrase authors, owner voices,
pedestrian families, lighting, and sensor/network regimes together. Report exact
failures, confidence/calibration, and pass-to-a-power across seeds—not one favorable
mean.

The self-learning loop should be governed, offline, and reversible:

1. record aligned observation, proposal, admission, execution, gate, task, receipt,
   conversation, model, calibration, and human-feedback events on a bounded encrypted
   robot spool;
2. upload only consented bundles;
3. keep content-addressed MCAP/media/model blobs in an encrypted object store and
   task/event/consent/dataset/experiment/deployment lineage in PostgreSQL;
4. derive deterministic labels first and use blinded humans for ambiguous dialogue
   and comfort judgments;
5. train candidates server-side, test on frozen family-disjoint suites and a second
   engine, then run them shadow-only on Orin;
6. promote only through a signed versioned configuration and retain one-action
   rollback.

There should be no autonomous on-robot weight update, no self-authored acceptance
bar, and no use of the robot's own narration as ground truth. An optional vector
index may accelerate retrieval, but explicit consented relational records remain the
source of truth.

## Physical mount and sim-to-real verdict

### Motion-enabled mount: NO-GO

The following blockers are independently sufficient:

- generalized instruction navigation succeeds on only 27.2% of the frozen set and
  includes seven false arrivals;
- the scripted follow bench misses group and cut-in cases, and dynamic-social arms
  retain contact failures;
- interruption, queue, clarify, resume efficiency, and arrival authority are below
  their bars;
- corrected acoustic v2 finds four invalid endpoint fixtures and slow virtual
  audible acknowledgement, cannot measure isolated acoustic STOP or physical
  motion sync, and has no mounted audio/AEC evidence;
- hosted-Q completed machine evaluation but failed every absolute MB-1 gate;
  calibrated human quality and paired hosted direct effect remain unmeasured;
- DMC-4's source transaction and disarmed runtime-frame observer pass, but live
  session, persistent cursor, separate-child resume lineage, provider, and
  audio composition remain absent; the old path retains a concrete 5/5
  false-arrival counterexample;
- no qualified learned Model A artifact or production proposal binding exists;
  the normal launcher neither injects nor arms a commissioned manager, and its
  carrier observation path declares simulation rather than physical provenance;
- `Go2Backend` is deliberately observe-only and the synchronized physical
  observation source is a fail-closed skeleton;
- SOS-1's current desktop source/fake-gateway maintenance passes after a real
  startup-race repair, but no physical independent E-stop/STOP input has been
  commissioned;
- no physical Go2/SDK2, Orin concurrent-load, synchronized camera/LiDAR/LIO,
  locomotion, stop-distance, payload, stairs, crosswalk, or elevator evidence
  exists; and
- the Orin service topology is still explicitly a skeleton and has not been run.

### Observe-only / motors-disabled mount: conditional

A powered-off or motors-disabled integration can be valuable for mechanical fit,
sensor field of view, extrinsic and clock calibration, audio capture/AEC development,
data logging, network loss, and HIL. It should proceed only after an engineering
checklist covers at least:

- payload retention, mass, center of gravity, cable strain relief, pinch points, and
  collision geometry;
- fused power, grounding, battery and current limits, thermal load/airflow, and EMI;
- independent physical e-stop, gateway stop latch, watchdog, boot/restart-disarmed
  behavior, and an explicit operator authority procedure;
- camera/LiDAR/audio extrinsics, clock domains, freshness, and missing-data behavior;
- data consent, retention, deletion, encryption, and log backpressure; and
- no vendor motion writer reachable during observe-only/HIL operation.

The deployment skeleton documents additional physical gates: a pinned aarch64
artifact, system users and directories, a tethered Unitree qualification record,
observed-robot identity or authenticated-DDS binding, a physical V2 observation
source, a real LIO provider, and sensor clock/extrinsics manifests. Launch-supplied
hashes show local configuration compatibility; they do not authenticate the robot or
DDS peer.

After simulator gates close, the staged ladder is motors-disabled HIL → stationary
commissioned Stage 0 → tethered, speed-capped motion in cleared space → separately
approved scenario capabilities. Simulator results never skip a rung.

## Prioritized implementation and experiment plan

### P0 — next 1–2 weeks: close authority and measurement gaps

1. **Build the independent physical stop boundary.** Wire real remote/GPIO STOP
   inputs to SOS-1's separate principal, install a physically independent E-stop,
   and measure gateway/robot stop timing and braking before any motion authority.
2. **Finish the new DMC-4 runtime composition.** Keep its owner-authored journal
   and process-local fail-closed observer plus its new drain-time lineage and
   freshness checks; add production key ownership,
   persisted/restart-safe cursor, live source/speech epochs, separate-child
   resume lineage, provider context, and speech cancellation/backpressure.
3. **Complete the task stack in that composition.** Parent/child interruptions,
   safe checkpoints, explicit resume offers, and reissue lineage live in the
   executive, not an LLM transcript. Run door → sofa → keys → resume with exact
   arrival and object-search receipts under restart/corruption faults.
4. **Act on corrected acoustic v2 without tuning to the discovery corpus.** Build
   a frozen human/room/AEC holdout; repair premature endpointing and persistent
   pre-warmed playback latency; add isolated owner/robot STOP channels and actual
   BeatLayer motion traces. Then test the mounted microphone/loudspeaker, AEC,
   walking noise, owner/non-owner ambiguity, interruption, and receipt-grounded
   speech before spending heavily on hosted evaluations.
5. **Keep explicit/reflex control in command.** Preregister MA-2 P2 with
   learner-visited DAgger/recovery data and residual/hybrid challengers; require
   closed-loop wins on every held split with no risk/false-arrival/intervention/
   latency regression.

### P1 — next 2–6 weeks: build transferable capability

1. Hermetically pin the now-working MJLAB-1 environment, train and gate an actual
   lower-locomotion policy, then freeze its policy I/O and timing contract.
2. Reproduce that contract in Isaac Lab or a second physics backend and randomize
   payload, center of mass, terrain, friction, actuator delay/gain, sensor noise,
   lighting, calibration, and clocks.
3. Implement LHO-1's committed-prefix/revisable-tail transaction in the disarmed
   runtime, then repeat every invariant using measured Orin delay, 2-D/3-D swept
   volumes, localization/perception uncertainty, and commissioned braking.
4. Add camera/LiDAR human tracking, multi-modal predicted occupancy, and asymmetric
   resume hysteresis. Build held-out sidewalk, crosswalk, and elevator suites, with
   zero-contact acceptance and independent intent truth.
5. Add audio, echo, addressee, ASR, Starlink loss/jitter, hosted timeout, session
   rollover, and offline fallback to the common scenario manifest.
6. Stand up the encrypted spool, object store, PostgreSQL catalog, consent/deletion
   service, dataset manifests, experiment registry, and signed promotion records.

### P2 — only after simulator gates: target-hardware evidence

1. Benchmark the exact concurrent stack on the AGX Orin 64 GB: perception, tracking,
   audio/AEC, Model A heads, slow planner, logging, gateway, hosted lane, CPU/GPU/RAM,
   p50/p95/p99 latency, power, and thermal soak.
2. Run gateway/state/clock/TTL/restart/e-stop/log-backpressure HIL with motor authority
   disabled; qualify SDK2 and the observed-robot identity boundary.
3. Measure payload/center of gravity, sensor extrinsics/time sync, acoustic echo,
   command-to-state latency, stop latency, and braking distance.
4. Only after signed review, run tethered and speed-capped motion in cleared space.
   Promote sidewalk, crosswalk, elevator, and stairs independently.

## Promotion gates

At minimum, physical-motion consideration should require:

- zero authenticated false terminal or progress claims;
- zero stale-revision execution and zero post-STOP motion authorization;
- zero admitted occupied or braking-unsafe committed prefixes;
- zero contacts across the acceptance social corpus, with rare-event exposure counts
  and confidence bounds reported;
- family-disjoint navigation, recovery, follow, interruption, queue, clarify, and
  resume performance above preregistered bars, with zero false arrivals;
- moving-owner tracking and re-identification without identity-perfect oracle tracks;
- physical mic/speaker/AEC and network-loss acoustic gates green;
- multi-engine dynamics/perception transfer with identical contracts;
- Orin deadline, memory, thermal, power, restart, and log-backpressure gates green;
- commissioned gateway identity, freshness, TTL, and e-stop behavior; and
- measured stationary and tethered stop-distance evidence reviewed and signed.

The registered Model B steering target is greater than 95% family-blind exact
operation/target/scope accuracy, queue and clarify each above 90%, zero STOP misses,
and exact resume lineage. Narration requires zero false terminal/progress claims,
complete required deviation/terminal recall, correct tense, and no stale speech after
barge-in. These are engineering promotion gates, not statistical guarantees of
universal safety.

## Compute, API, and Starlink budget guidance

Keep safety, tracking, fast policy, VAD/AEC, task state, and offline status on the
Orin. The literature supports a small slow visual-language lane around 0.5–2 Hz, not
a 10 Hz VLM. AGX Orin 64 GB capacity alone does not select a model: choose the slow
lane only after concurrent end-to-end profiling. MB-1's 7B local row ran on desktop
CPU, had only 0.5225 event coverage, and is not an Orin sizing result.

For the planned monthly budgets:

- Put a hard **$300/month Realtime ledger** around final natural-voice arms and small
  owner pilots. Use a roughly $10/day warning envelope, record actual usage per
  session/mission, and refuse unmetered or exhausted experimental calls. Do not use
  paid voice for bulk simulator rollouts.
- Put a separate hard **$100/month text ledger** around scenario generation,
  independent semantic adjudication, and a small planner challenger, with a roughly
  $3.33/day warning envelope. Freeze/cache generated corpora and never use the same
  model as both generator and acceptance oracle.
- Use deterministic fake voice for regression and open/offline models for bulk
  training and replay. Reserve hosted calls for matched final arms after local
  contract and acoustic gates pass.
- At the official audio-token rates (600 input tokens/minute and 1,200 output
  tokens/minute), `gpt-realtime-2.1-mini` has a raw-new-audio floor of about
  $0.006 per heard minute and $0.024 per spoken minute. Eight hours/day of
  ungated listening alone is therefore about $86.40/month before context,
  text, tools, and special tokens. The full 2.1 model is about $276.48/month
  for the same listening alone, leaving effectively no room for speech or
  context inside a $300 cap. Use local AEC/VAD/addressee gating, mini for
  routine conversation, and the full model only as a measured challenger or
  explicitly escalated difficult turn.
- Meter `response.done` usage and run a seven-day representative duty-cycle pilot
  before forecasting monthly conversation minutes. Pricing is token-based and
  time-sensitive; a fixed assumed cost per minute is not auditable.
- The completed hosted-Q wave added $1.32843624 and moved the shared research
  ledger from $0.87959880 to $2.20803504. Hosted D stopped at 2/120. Those are
  experiment ledger data, not a production cost forecast.
- Starlink loss must degrade only hosted speech and remote reasoning. Local STOP,
  tracking, planning state, safety, and canned status remain available offline.

The hosted experiment used `gpt-realtime-2.1-mini` in text-output mode. On the
2026-08-29 design date, its official list prices are $0.60/M input text,
$0.06/M cached text, $2.40/M output text, $10/M input audio, $0.30/M cached
audio, and $20/M output audio. The unmeasured full `gpt-realtime-2.1` challenger
is $4/$0.40/$24 per million text tokens and $32/$0.40/$64 per million audio
tokens. Recheck official prices when implementing the budget service.

## Limitations and non-claims

This assessment does **not** claim:

- that DSOAK-1's 12.05 desktop wall-clock hours are physical qualification or
  that its late-start monitor independently witnessed the whole interval;
- that 500 simulated stream-hours are physical or wall-clock qualification;
- that passing unit/integration tests measures generalized capability;
- that zero collision counts in semantic/kinematic fixtures imply safe locomotion;
- that the historical Realtime corpus measures the current hosted model;
- that MB-1 machine flags are a calibrated human failure rate;
- that DMC-1 narration scores survive independent audit;
- that any current model recognizes the owner reliably in walking noise;
- that a 7B offline model meets Orin real-time, thermal, or power requirements;
- that launch hashes authenticate the observed robot or DDS transport;
- that simulation establishes physical stop distance, gait/payload stability,
  acoustics, or human comfort; or
- that observe-only mounting authorizes any motor command.

The authenticated `claude.ai/code/artifact/...` page supplied for the mount
review could not be retrieved from this environment. The Claude assessment in
this report is therefore based on the shared local checkout, its dated task
cards/status files, source diffs, retained artifacts, processes, and fresh tests;
it is not a claim to have inspected content visible only behind that URL.

The independent current-checkout review of Claude Task 2 is retained in
[`CLAUDE_TASK2_REVIEW.md`](CLAUDE_TASK2_REVIEW.md). It rejects the integrated
work as mount-ready. Its initial C0 run exposed a stale mutation artifact and a
surviving `reactive_gate_disabled`; the subsequent independent repair now pins
the full matrix, records direct intervention coverage, and killed 7/7 mutants
in two identical nine-row campaigns, but still has no hard-stop witness. C6
queue/revise/keep lineage is unimplemented;
C2 settle authority is harness-only and remains 10/80 rather than the ≤2/80
bar; C1 uses process-global scene identity and has unresolved regressions; and
C3's enabled arm trades fewer stalls for more semantic-unreachable outcomes.
C7 is useful evaluator repair, while C4/C5 are tested but unwired leaves. These
findings are based on source and guarded current-tree tests, not card-status
claims.

The work so far provides strong evidence that typed authority, deterministic replay,
and multi-rate decomposition are the correct engineering direction. It also provides
strong negative evidence against declaring the current robot autonomous or
mount-ready for motion.

## Code and artifact pointers

### Production-shaped runtime and authority

- Production runtime overview:
  [`../../docs/PRODUCTION_RUNTIME_CODE_MAP.md`](../../docs/PRODUCTION_RUNTIME_CODE_MAP.md)
- Main runtime and observation/dispatch loop:
  [`../../src/parcel_robot/runtime.py`](../../src/parcel_robot/runtime.py)
- Task lifecycle and semantic adapter:
  [`../../src/parcel_robot/brain/executive.py`](../../src/parcel_robot/brain/executive.py),
  [`../../src/parcel_robot/brain/executive_journal.py`](../../src/parcel_robot/brain/executive_journal.py),
  [`../../src/parcel_robot/brain/executive_interrupts.py`](../../src/parcel_robot/brain/executive_interrupts.py),
  [`../../src/parcel_robot/brain/executive_revision_transaction.py`](../../src/parcel_robot/brain/executive_revision_transaction.py),
  [`../../src/parcel_robot/brain/runtime_adapter.py`](../../src/parcel_robot/brain/runtime_adapter.py)
- Navigation pipeline:
  [`../../src/parcel_robot/navigation/pipeline.py`](../../src/parcel_robot/navigation/pipeline.py)
- Final control and stop path:
  [`../../src/parcel_robot/control/manager.py`](../../src/parcel_robot/control/manager.py),
  [`../../src/parcel_robot/core/hard_stop.py`](../../src/parcel_robot/core/hard_stop.py)
- Product Unix gateway client and runtime composition:
  [`../../src/parcel_robot/bridge/gateway_client.py`](../../src/parcel_robot/bridge/gateway_client.py),
  [`../../src/parcel_robot/bridge/state_v2_codec.py`](../../src/parcel_robot/bridge/state_v2_codec.py),
  [`../../src/parcel_robot/control/motion_gateway.py`](../../src/parcel_robot/control/motion_gateway.py),
  [`../../src/parcel_robot/control/motion_gateway_commissioned.py`](../../src/parcel_robot/control/motion_gateway_commissioned.py),
  [`../../src/parcel_robot/control/motion_gateway_session.py`](../../src/parcel_robot/control/motion_gateway_session.py),
  [`../../src/parcel_robot/control/unitree_sport.py`](../../src/parcel_robot/control/unitree_sport.py)
- Orin service skeleton and explicit commissioning gaps:
  [`../../deploy/orin/services/README.md`](../../deploy/orin/services/README.md)

### Conversation, companion behavior, and truthfulness

- Realtime lane and bounded tool boundary:
  [`../../src/parcel_robot/realtime/lane.py`](../../src/parcel_robot/realtime/lane.py),
  [`../../src/parcel_robot/realtime/tool_broker.py`](../../src/parcel_robot/realtime/tool_broker.py)
- Current context whisperer:
  [`../../src/parcel_robot/realtime/whisperer.py`](../../src/parcel_robot/realtime/whisperer.py)
- Authenticated dialogue reducer:
  [`../../src/parcel_robot/voice/companion_state.py`](../../src/parcel_robot/voice/companion_state.py)
- Owner journal, journal-only mapper, and disarmed runtime observer:
  [`../../src/parcel_robot/brain/executive_journal.py`](../../src/parcel_robot/brain/executive_journal.py),
  [`../../src/parcel_robot/brain/execution_narrative_bridge.py`](../../src/parcel_robot/brain/execution_narrative_bridge.py),
  [`../../src/parcel_robot/voice/execution_narrative_runtime.py`](../../src/parcel_robot/voice/execution_narrative_runtime.py)
- Local microphone/playback and distinct hosted audio lanes:
  [`../../src/parcel_robot/audio/voice_loop.py`](../../src/parcel_robot/audio/voice_loop.py),
  [`../../src/parcel_robot/audio/speaker.py`](../../src/parcel_robot/audio/speaker.py),
  [`../../src/parcel_robot/realtime/audio_gateway.py`](../../src/parcel_robot/realtime/audio_gateway.py),
  [`../../src/parcel_robot/realtime/browser_sink.py`](../../src/parcel_robot/realtime/browser_sink.py)
- Companion-friend prompt:
  [`../../src/parcel_robot/realtime/relationship_prompt.py`](../../src/parcel_robot/realtime/relationship_prompt.py),
  [`../../src/parcel_robot/runtime_assets/prompts/system/core.md`](../../src/parcel_robot/runtime_assets/prompts/system/core.md)

### Learning and research data

- Proposal-only learning contracts and promotion machinery:
  [`../../src/parcel_robot/learning_loop/`](../../src/parcel_robot/learning_loop/)
- Default-off governed research plane:
  [`../../src/parcel_robot/research_plane/`](../../src/parcel_robot/research_plane/)
- Read-only capture envelope:
  [`../../src/parcel_robot/capture/`](../../src/parcel_robot/capture/)
- Training, curriculum, hypothesis, and database plan:
  [`TRAINING_AND_DATA_PLAN.md`](TRAINING_AND_DATA_PLAN.md)

### Research evidence

- Full architecture:
  [`DUPLEX_PRODUCTION_ARCHITECTURE.md`](DUPLEX_PRODUCTION_ARCHITECTURE.md)
- Literature review:
  [`literature/LITERATURE_REVIEW.md`](literature/LITERATURE_REVIEW.md)
- Product eval ledger and controlling verdict:
  [`product-evals/RESULTS.md`](product-evals/RESULTS.md),
  [`product-evals/VERDICT.md`](product-evals/VERDICT.md),
  [`product-evals/TEST_RUNS.md`](product-evals/TEST_RUNS.md),
  [`product-evals/summary.json`](product-evals/summary.json)
- DMC-1 learned-policy study and independent verdict:
  [`duplex-mission-control-1/RESULTS.md`](duplex-mission-control-1/RESULTS.md),
  [`duplex-mission-control-1/VERDICT.md`](duplex-mission-control-1/VERDICT.md)
- DMC-2 transaction study:
  [`duplex-transaction-2/RESULTS.md`](duplex-transaction-2/RESULTS.md),
  [`duplex-transaction-2/VERDICT.md`](duplex-transaction-2/VERDICT.md)
- DMC-4 authoritative journal and maintained source:
  [`duplex-transaction-4/RESULTS.md`](duplex-transaction-4/RESULTS.md),
  [`duplex-transaction-4/MAINTENANCE_RESULTS.md`](duplex-transaction-4/MAINTENANCE_RESULTS.md),
  [`DMC4_RUNTIME_COMPOSITION_AUDIT.md`](DMC4_RUNTIME_COMPOSITION_AUDIT.md)
- MA-2 causal/closed-loop study:
  [`model-a-stream-2/RESULTS.md`](model-a-stream-2/RESULTS.md),
  [`model-a-stream-2/VERDICT.md`](model-a-stream-2/VERDICT.md)
- Dynamic social and false-stall study:
  [`dynamic-social-progress-2/RESULTS.md`](dynamic-social-progress-2/RESULTS.md),
  [`dynamic-social-progress-2/VERDICT.md`](dynamic-social-progress-2/VERDICT.md)
- Extended-nightly degraded-pose attribution:
  [`POSE_DRIFT_NIGHTLY_AUDIT.md`](POSE_DRIFT_NIGHTLY_AUDIT.md)
- Latency-handoff study and audit supplement:
  [`latency-handoff-1/RESULTS.md`](latency-handoff-1/RESULTS.md),
  [`latency-handoff-1/FRESH_PROCESS_SUPPLEMENT_PLAN.md`](latency-handoff-1/FRESH_PROCESS_SUPPLEMENT_PLAN.md)
- Official Unitree mjlab feasibility:
  [`mjlab-feasibility-1/RESULTS.md`](mjlab-feasibility-1/RESULTS.md),
  [`mjlab-feasibility-1/VERDICT.md`](mjlab-feasibility-1/VERDICT.md)
- Stop-only safety principal:
  [`stop-only-safety-1/RESULTS.md`](stop-only-safety-1/RESULTS.md),
  [`stop-only-safety-1/VERDICT.md`](stop-only-safety-1/VERDICT.md),
  [`stop-only-safety-1/MAINTENANCE_RESULTS.md`](stop-only-safety-1/MAINTENANCE_RESULTS.md),
  [`stop-only-safety-1/MAINTENANCE_VERDICT.md`](stop-only-safety-1/MAINTENANCE_VERDICT.md)
- Independent Claude Task 2 review:
  [`CLAUDE_TASK2_REVIEW.md`](CLAUDE_TASK2_REVIEW.md)
- Independent false-arrival audit:
  [`lit1-grounding-audit/RESULTS.md`](lit1-grounding-audit/RESULTS.md),
  [`lit1-grounding-audit/VERDICT.md`](lit1-grounding-audit/VERDICT.md)
- Navigation interruption:
  [`nav-interrupt-1/RESULTS.md`](nav-interrupt-1/RESULTS.md)
- Model B stage evidence:
  [`model-b-narration-1/RESULTS.md`](model-b-narration-1/RESULTS.md)
- Corrected acoustic measurement and endpoint sensitivity:
  [`acoustic-eval-v2/RESULTS.md`](acoustic-eval-v2/RESULTS.md),
  [`acoustic-eval-v2/VERDICT.md`](acoustic-eval-v2/VERDICT.md),
  [`endpoint-policy-1/RESULTS.md`](endpoint-policy-1/RESULTS.md),
  [`endpoint-policy-1/VERDICT.md`](endpoint-policy-1/VERDICT.md)
- Completed wall-clock soak, strict result, and controlling verdict:
  [`duplex-soak-1/DESIGN.md`](duplex-soak-1/DESIGN.md),
  [`duplex-soak-1/RESULTS.md`](duplex-soak-1/RESULTS.md),
  [`duplex-soak-1/VERDICT.md`](duplex-soak-1/VERDICT.md),
  [`duplex-soak-1/final-verification.json`](duplex-soak-1/final-verification.json)

## Bottom line

The project now has a credible *shape* for a conversational autonomous companion:
a local, multi-rate embodied policy; explicit task transactions; independent motion
safety; receipt-grounded narration; hosted natural voice; and an external,
consent-aware learning loop. The most valuable current result is not that autonomy
works—it does not—but that the critical boundaries, failure modes, and next
experiments are concrete and testable.

Proceed with simulator capability development, DMC-4 live-session composition,
responsive-human prediction and escape actions, acoustic repair, and governed
data infrastructure. Treat the learned policy as shadow-only. Permit only
checklist-approved observe-only or motors-disabled integration. Do not enable
autonomous physical motion on the Go2.
