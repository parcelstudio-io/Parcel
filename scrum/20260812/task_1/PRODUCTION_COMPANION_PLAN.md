# Task 1 — production conversational companion convergence

- **Date:** 2026-08-12
- **Revision: r2** — folds every required change from `FABLE_VERDICT.md`
  (`ACCEPT_WITH_REQUIRED_CHANGES`, 2026-08-12): RC-2..RC-6 and N-5..N-8. Each revised
  passage names its verdict item inline; per-hunk traceability is in
  `../task_2/P1_STATUS.md`.
- **Status:** Iteration 3 accepted; Wave 0 accepted to begin now that the verdict's
  required changes are folded in.
- **Parent baseline (RC-6):** commit `7242660` — "Land route-memory arms, person-aware
  yield/keepout, and 20260811–12 scrum closes.", 2026-08-12 — plus
  `scrum/20260811/task_2/SLAM_M_PLAN.md`. r1 said "current dirty worktree"; that
  worktree landed as `7242660` during the Fable review, so every Wave-0 card below is
  re-baselined on `7242660` and r1's file-overlap stop condition is moot (verified: no
  W0-owned file carried uncommitted edits at the landing).
- **Owners:** Sol design/research; Fable independent refutation; implementation owners
  assigned only after verdict.

## Owner directive

Turn the current voice-enabled navigation prototype into a credible path toward
a robot dog that can converse naturally and autonomously follow its owner in a
declared, controlled operating domain. Preserve Unitree Go2 Sport locomotion for
balance/gait, preserve Parcel's typed intent and deterministic safety boundaries,
remain portable to another quadruped, and evaluate every promoted change.

This task is intentionally larger than a four-hour implementation. The research
and architecture review alone is estimated at 6–10 engineer-hours; the first
accepted implementation wave is estimated at 62–92 engineer-hours. These are
planning estimates, not claims about elapsed agent wall time.

## Recommendation in one paragraph

Build a **hybrid deterministic autonomy stack**. Keep the Python Parcel brain for
conversation, typed intent, semantic task execution, behavior/resource arbitration,
global mission logic, and evaluation. Put raw sensor drivers, transforms,
LiDAR-inertial localization, local mapping/tracking, and selected Nav2 algorithms in
ROS 2/C++ sidecars. Put the Unitree DDS lease, Sport `Move`/`StopMove`, a 50 Hz
watchdog, local limits, and measured-stop confirmation in a separate native
**sole-writer robot gateway**. Treat every LLM, VLM, VLA, MPPI, and learned predictor
as an untrusted proposal source. Typed task/evidence revisions, identity state,
capability admission, and a final monotone collision/safety governor decide whether
any proposal may become a short-lived body-velocity setpoint. Progress first to a
supervised fenced/private-route prototype; public-city autonomy is a later safety,
security, privacy, hardware, and regulatory program—not the next demo milestone.

## Decision record

Accepted for design:

1. **Python remains the semantic application layer.** A C++/Rust rewrite of the
   whole codebase would discard useful tests and would not create perception,
   localization, identity, or safety evidence.
2. **A native robot gateway is mandatory.** Unitree DDS/lease state and the only
   physical command writer live in one process isolated from Python, GPU models,
   the web UI, and ROS discovery.
3. **ROS 2 is selective infrastructure, not final authority.** Use it for sensor
   drivers, `tf2`, localization/SLAM, selected Nav2 components, and `rosbag2`.
   Default ROS QoS/lifecycle/security do not constitute a safety boundary.
4. **Conversation and task planning are logically split, not blindly duplicated.**
   A deterministic fast router handles stop/cancel/direct skills. Conversation and
   deliberative planning may run concurrently behind shared turn/scene revisions;
   only the validated task transaction affects behavior.
5. **The reasoning model does not output “the next motor move.”** It may output a
   bounded high-level goal, skill sequence, clarification, or reaction proposal.
   A navigation controller may output a short trajectory candidate. Only the
   gateway path produces commands.
6. **Unitree Sport remains the first locomotion controller.** Parcel supplies
   closed-loop supervision around Unitree's onboard gait/balance loop. Do not mix
   Sport and low-level joint commands.
7. **No broad RL training now.** First benchmark deterministic controllers and
   open navigation models in a proposal-only shadow harness. Train only a narrow
   component when a repeatable residual failure and suitable data are demonstrated.
8. **The first physical ODD is constrained.** Flat, mapped, private indoor/outdoor
   routes; daylight/adequate lighting; dry weather; walking speed; trained operator
   with independent stop. Roads, unsupervised crowds, stairs, hills, and public-city
   use remain outside until separately commissioned.

## Honest baseline: what Parcel is today

| Layer | Current evidence | Assessment |
|---|---|---|
| Typed intent/plan boundary | Bounded `IntentFrame`, `PlanIR`, resources, revisions, validation, and deterministic skills | Strong prototype foundation; retain |
| Simulator control safety | Single writer, TTL, limits, stale-state stop, in-flight stop dominance, post-stop confirmation | Strong design and unit evidence; no physical proof |
| Semantic navigation | Frozen 25-episode v4: SR 0.24, SPL 0.1933, zero modeled collisions; 19 failures across grounding/planning/refusal/termination | Research baseline, not usable autonomy |
| Scripted following | Latest 11 cases: follow 7/9, navigation 2/2, follow-band fraction 0.7088, zero kinematic hard collisions | Encouraging but too small/oracular for owner following |
| Conversation | Frozen Gemma: 6/10 machine cases and 10/10 parse; harder live PersonalConvo: 3/13 turns and 1/8 families | Conversation is not companion-grade |
| Synthetic duplex | Five of nine gates fail; endpoint p50 0.784 s, acoustic stop p50 0.78 s, false barge 1.0, ack p50 0.8 s | Not duplex-ready |
| Desktop audio | No usable active capture/playback endpoint or attached XVF3800 on 2026-08-12 | Text input is the only honest live mode today |
| Physical perception/localization | No production camera/L2 backend, owner re-ID, physical SLAM, or `map -> odom` correction | Blocking gap |
| Unitree path | Good Sport adapter seam, but injected doubles only; current runtime drops its physical state source | Close to supervised first movement, not autonomy |
| Test suite | Thousands of unit/sim tests and external-eval adapters; the commit gate at `7242660` passes 3,943 default-suite tests (RC-6; r1's "3,889" was an unrepeatable mid-batch transient — disclosed in `VALIDATION.md`) | Broad code regression coverage, weak physical/acoustic/ecological validity |
| Dynamic-cost timing | A <2 ms `test_cost_field_vectorization_performance` micro-gate repeatedly measured about 3.07–3.47 ms. The "210/211 focused run" that framed it recorded no test selection and is **unreproducible** (N-8); only the micro-gate measurement is evidence | Profile/separate city-scale tracking and planning; not itself a 20 ms control-period miss |

Readiness depends on the claim:

- Supervised, fenced, low-speed Sport body-velocity commissioning: roughly
  **60–70% of the software boundary**, but not runnable on this host/robot today.
- Safe voice-commanded indoor follower with real localization, owner perception,
  collision response, and stop evidence: roughly **30–40%**.
- Unsupervised city/stair/hill companion: **below 15–20%**. The current city and
  terrain evidence is simulation/kinematics, not a deployment claim.

## P0 defects discovered by the assessment

These are blockers, not roadmap polish:

1. `runtime.py:390-395` retains an injected manager's state source only when it is
   simulator-specific `BufferedRobotStateSource`; a `UnitreeSportStateSource` is
   discarded and physical input health sees no feedback.
2. `core/input_health.py:100-133` infers authority from source strings. The real
   source `unitree_sport` is classified as a simulator fixture while `unknown` is
   trusted as physical. Replace inference with typed, attested provenance.
3. Normal control construction requires commissioned axes/frame/modes before the
   current commissioning CLI can measure them. Add a narrower, explicitly armed,
   one-axis commissioning manager; never pre-set evidence flags.
4. There is no product hardware launcher. The web panel builds a MuJoCo backend;
   the Unitree CLI is a bounded test tool.
5. `pose.py` has no physical localization provider or real `map -> odom` transform.
6. A grid-navigation degraded branch may fall back to open-loop point motion when
   calibrated scan evidence is unavailable. Physical translation must instead hold.
7. Speaker work-queue timestamps can exist even if there is no playable endpoint;
   current metrics do not prove an audible first sample.
8. The acoustic evaluator can produce failed gates without failing its process, and
   its virtual rig is not a through-air/audio-hardware test.
9. The D0 duplex path performs synchronous serialization/file rotation/disk append
   from the **10 Hz `RobotRuntime` semantic loop** (`loop_hz=10`, `frame_hz=10`) — the
   loop that dispatches motion. r1 said "the 50 Hz control step"; executed, the 50 Hz
   `ControlManager` thread does no duplex logging (RC-5). The defect and its fix
   (W0-G) are unchanged in substance; only the rate figure and therefore the budget
   arithmetic change — a blocking write competes with a 100 ms dispatch period, not a
   20 ms one. Diagnostics must still leave that path.
10. The current shared Llama.cpp provider has one active cancellation handle, so
    concurrent conversation/planning/summarization can cancel one another without an
    inference broker.
11. Voice submission has no trusted principal/speaker/authorization/DoA/evidence
    contract, and two incompatible resource vocabularies can make overlay/preemption
    decisions disagree.

No public hardware motion work starts until 1–4 are corrected and independently
reviewed.

## Architecture iterations

### Iteration 1 — extend the Python monolith

Put camera, LiDAR, SLAM, more models, and the Unitree driver directly into
`RobotRuntime`.

Advantages:

- fastest simulator feature work;
- smallest initial diff;
- retains direct access to existing objects and tests.

Why rejected for production:

- one exception, GIL stall, allocation pause, model OOM, or logging blockage can
  share the physical control failure domain;
- Unitree SDK DDS/lease state is process-global and difficult to release cleanly;
- simulator-specific observation assumptions already break the injected physical path;
- Python model/audio workloads cannot own a 50 Hz physical watchdog credibly.

Use only as the current simulator reference while migration contracts are proven.

### Iteration 2 — rewrite around a ROS 2/Nav2 graph

Make voice and Parcel thin ROS nodes; let Nav2 own global planning, local control,
recovery, lifecycle, and `cmd_vel` into Unitree.

Advantages:

- mature sensor, transform, bagging, visualization, lifecycle, and navigation tooling;
- conventional flat-ground bring-up is faster;
- C++ components fit vendor and embedded ecosystems.

Why rejected as the center of the product now:

- it rewrites a large validated semantic/task/safety stack;
- owner identity, conversational interruption, semantic acceptance regions, terrain,
  and terminal truth remain custom work;
- QoS/discovery/component composition add failure modes and do not provide physical
  stop authority;
- Unitree's recommended Humble environment conflicts with the desktop's current OS.

Adopt algorithms and interfaces selectively; retain a separate sole-writer gateway.

### Iteration 3 — Parcel brain + autonomy sidecars + native gateway

This is the recommended prototype architecture.

```text
 owner speech/text
       |
       v
 audio I/O service ---> ASR partials (display/barge only)
       |                         |
       +---- final transcript ---+
                                  v
                       turn coordinator / fast router
                         |                     |
                  conversation lane       task/plan lane
                         |                     |
                         v                     v
                   speech proposal      TaskTransactionV2
                         |                     |
 camera + LiDAR + IMU --> perception/localization sidecars
                         |                     |
                         +--> versioned world evidence
                                               |
                                               v
                       behavior executive / semantic goal region
                                               |
                            route graph + global corridor
                                               |
                      RPP/DWPP baseline; MPPI/VLA shadow candidates
                                               |
                 final collision + social + capability safety governor
                                               |
                            short-lived MotionCandidateV2
                                               |
                    native sole-writer robot gateway (50 Hz)
                      lease | TTL | limits | StopMove | feedback
                                               |
                              Unitree Sport controller
                                               |
                                    onboard gait/balance

 Independent handheld stop ---------> physical/vendor stop authority
 External maps placeholder ----------> route hints only, never free-space truth
 Trace/eval recorder <---------------- every boundary and disposition
```

Advantages:

- preserves Parcel's strongest work;
- isolates hard control from Python/GPU/ROS/model failures;
- gets ROS sensor/localization value without making discovery the stop path;
- supports Unitree and another quadruped through capabilities and adapter evidence;
- learned components can be shadowed and rolled back without changing safety.

Costs:

- process and clock-domain contracts must be explicit;
- health/arbitration is intentionally checked at more than one boundary;
- integration, deployment, and fault testing are more work than an in-process demo.

### Iteration 4 — dedicated safety appliance/kernel

For a public product, evolve the gateway into a native C++/Rust supervisor,
potentially on separate safety compute/MCU, treating Parcel, ROS, networking, and all
models as untrusted proposal clients. It owns arming, geofence/speed envelopes,
hardware watchdog, physical E-stop I/O, update inhibit, power/thermal policy, and an
audit ring.

This is the best public-product destination but premature as the first refactor. A
container is not a physical safety boundary, and software cannot declare the
underlying uncertified robot safe. Iteration 3 contracts must allow migration here.

### Decision comparison

Scores are an architecture aid (1 poor, 5 strong), not a measured benchmark.

| Criterion | Python monolith | ROS 2 rewrite | Hybrid sidecars | Safety kernel end-state |
|---|---:|---:|---:|---:|
| Preserve tested semantic behavior | 5 | 2 | 5 | 4 |
| Fault containment | 1 | 3 | 4 | 5 |
| Sensor/localization ecosystem | 2 | 5 | 5 | 4 |
| Deterministic physical authority | 2 | 3 | 4 | 5 |
| Unitree bring-up practicality | 3 | 3 | 5 | 2 |
| Cross-platform portability | 2 | 4 | 5 | 5 |
| Time to useful hardware evidence | 4 | 2 | 4 | 1 |
| Long-term public-product assurance | 1 | 3 | 4 | 5 |

Decision: implement Iteration 3 now; preserve a contract-compatible path to
Iteration 4. Do not implement Iteration 1 further on the physical path or begin the
Iteration 2 rewrite.

#### Abandonment criteria for the hybrid architecture itself (N-7)

Brief question 12 asked what would falsify this architecture, and r1 answered only for
components. The hybrid is abandoned — escalated to Iteration 4 (safety appliance) or
reconsidered against Iteration 2 — if any of the following is *measured*, not argued:

1. **Stop authority cannot be isolated.** The gateway's stop path cannot be made
   independent of Python/ROS/GPU/logging liveness: any W0-C fault campaign shows a
   stop initiation later than the ratified deadline while a Parcel-side component is
   killed, frozen, or saturated, and no in-process fix closes it. → escalate to a
   separate safety compute/MCU (Iteration 4) rather than adding supervision inside
   the same failure domain.
2. **Sole-writer exclusivity cannot be enforced** against the vendor app, a rogue DDS
   participant, or a second local process on the shipped firmware. → the DDS trust
   boundary is not achievable in software; hardware arming/interlock becomes a
   precondition, not a later wave.
3. **The contract seam costs more than the rewrite it avoided.** If Wave-0/1 shows the
   evidence/snapshot boundary requires re-implementing localization, mapping, or
   tracking on both sides of the seam (i.e. the ROS sidecars cannot be consumed as
   sidecars), Iteration 2's cost model changes and is re-scored.
4. **Python semantic-layer preservation stops paying.** If the retained Parcel
   semantic suite must be rewritten anyway to satisfy the new contracts — the measure
   is the fraction of the 23 required product tests that cannot be written against
   existing Parcel code — the "preserve tested semantic behavior" 5 is wrong and the
   comparison is re-run.

Each criterion names the wave that can produce its evidence. None of them can be
declared from design review; they are recorded now so the architecture is falsifiable
later.

## Trust and authority model

| Producer | May propose | May authorize |
|---|---|---|
| Conversation LLM | reply text, clarification, affect/reaction proposal | no motion |
| Task-planning LLM/VLM | typed goal/skills/constraints with task revision | no skill execution or motion |
| Semantic detector/VLM | entity/referent hypotheses with evidence/covariance | no arrival or free-space truth |
| ViNT/NoMaD/NaVILA/CityWalker/MPPI challenger | subgoal or bounded trajectory candidate | no command |
| Deterministic executive | validated skill transaction and resource schedule | may request navigation |
| Deterministic local controller | short-horizon candidate | no final release |
| Safety governor | pass/clamp/hold/stop/latched-stop | may only restrict |
| Native robot gateway | short-lived commissioned body setpoint | sole software actuator authority |
| Independent operator/remote | physical stop/controlled re-arm | absolute operator authority |

Safety composition is monotone:

```text
PASS < CLAMP < HOLD < STOP < LATCHED_STOP
```

Once any active gate returns a stronger disposition, no downstream component can
relax it. A latched stop requires explicit operator clear plus fresh stationary
feedback; a model cannot clear it.

## Timescales and process topology

| Layer | Initial rate/trigger | Process/failure domain |
|---|---:|---|
| Unitree onboard gait/balance | vendor-owned fast loop | robot firmware |
| Robot gateway watchdog/state/control | 50 Hz | native sole-writer process, dedicated CPU budget |
| LiDAR-inertial odometry | 50–100 Hz target | C++/ROS 2 localization sidecar |
| Collision/elevation map | 20–50 Hz | mapping sidecar; no LLM dependency |
| Owner geometry tracking | 20–30 Hz | perception/tracking sidecar |
| Closed-set detection | 15–30 Hz target | GPU perception service |
| Re-identification | 2–10 Hz and on ambiguity | GPU perception service |
| Local navigation | 20–50 Hz | deterministic C++/ROS 2 component |
| Dynamic prediction | 10–20 Hz | navigation sidecar |
| Global route planning | event-driven, at most 1–2 Hz | Parcel/navigation service |
| Open-vocabulary grounding | query-triggered, 1–5 Hz | shed-able GPU service |
| Intent/task reasoning | final turn/event-driven | Parcel model service |
| Conversation generation | event-driven streaming | lowest physical priority model service |

The gateway, collision field, localization, and owner tracker never wait for
conversation.

**Load shedding order, reconciled (N-6).** r1's order shed conversation model size
*third* but the learned navigation challenger *last*, while the table above calls
conversation generation the "lowest physical priority" service — the two statements
read as a contradiction. They were measuring different things, and the fix is to say
so and then to reorder:

- *Physical priority* ranks a service by its authority over motion. Conversation is
  lowest on that axis: it has none. That is a statement about what may be trusted,
  not about what may be discarded.
- *Shed order* ranks a service by product harm per unit of resource freed, subject to
  the invariant that nothing with motion authority is ever shed.

By that second rule a shadow challenger sheds before a user-facing function, because
shedding a proposal-only component cannot change behavior by construction — it is the
cheapest possible cut. The corrected order is:

1. rendering/debug and non-essential telemetry;
2. **learned navigation challenger and every other shadow/proposal-only model**
   (MPPI-in-shadow, ViNT/NoMaD-class subgoal proposers) — no authority, so no
   behavioral delta;
3. optional TTS quality (fall back to the deterministic Piper path);
4. conversation model size;
5. open-vocabulary grounding queries — last of the shed-able set, because shedding it
   removes the ability to admit *new* semantic goals; already-admitted tasks continue
   on geometry and the deterministic baseline.

Tracking, geometry, control, and stop authority are never shed; if they cannot be
sustained, translation holds. A shed decision is recorded as evidence, and shedding
past step 5 is a hold, not a degraded-autonomy mode.

## Versioned boundary contracts

The executable reference is in `design_spike/contracts.py`. It is a design model,
not product code.

### `EvidenceEnvelopeV2`

Parcel already has a useful `contracts/v1.py::EvidenceEnvelopeV1` with source/receipt
timestamps, sequence, frame, expiry, calibration, scene revision, and provenance.
Evolve it with a new major version rather than creating a competing envelope or
silently changing v1 semantics.

Required fields:

- schema and producer/session identity;
- typed origin: `PHYSICAL | SIMULATION | REPLAY` (never inferred from strings);
- monotonic host receipt time;
- source/device timestamp and clock-domain identifier;
- sequence and boot/session epoch;
- frame and calibration revision;
- payload health, covariance/uncertainty, software/model revision;
- trace ID and bounded lifetime.

Host monotonic receipt authorizes watchdog freshness. Source time is retained for
fusion after a `ClockMapper` estimates offset, skew, and uncertainty; a backward jump
or large residual resets the mapper and degrades the stream. Across processes, send a
duration TTL and let the receiving process derive its own local deadline—absolute
monotonic values are not comparable.

### `HardwareCapabilityManifestV1`

Includes platform/edition/serial, firmware and API versions, verified services,
body/holonomic axes, gait/mode table, footprint, limits, stop semantics, sensors,
frames, compute/power options, payload/center of mass, and manifest hash. A capability
revision change invalidates admitted plans.

### `CommissioningRecordV1`

Signed evidence for axis signs, velocity frame, sensor extrinsics, modes, QoS/rates,
limits, stop request/settle latency and distance, operator, date, and artifact hashes.
Defaults fail closed. Product configuration may reference but never manufacture it.

### `TaskTransactionV2`

Carries task ID/revision, source turn and transcript hash, speaker authorization,
intent, constraints, invariants, resource needs, interruption policy, scene revision,
deadline, and confirmation requirement. Late model output for an old task/scene is
discarded, never patched into the current task.

### `OwnerBeliefV1`

```text
UNENROLLED -> ACQUIRING -> LOCKED -> OCCLUDED
                   ^          |          |
                   |          v          v
                 HOLD <- AMBIGUOUS <- SEARCHING
```

It carries candidate posteriors including `NONE`, top-one/runner-up margin, pose and
velocity covariance, modalities, last positive identity confirmation, and enrollment
revision. Only `LOCKED` authorizes follow translation. Occlusion/ambiguity holds;
bounded in-place search may be separately admitted. The nearest person is never an
identity fallback.

### `NavigationSnapshotV2`

One immutable revision containing `map -> odom -> base_link` transforms and
covariances, collision/elevation maps, dynamic tracks/predictions, owner belief,
semantic entities/regions, capability and calibration revisions, source evidence IDs,
and per-input health. Planning against a mutable bag of latest values is forbidden.

### `MotionCandidateV2`

Contains task/plan/snapshot revisions, producer/model/version, body-frame trajectory
or twist horizon, source-local issue time and TTL, footprint sweep, evidence sequence
references, predicted cost/uncertainty, and requested capability. It is not an
actuator command. Non-finite, stale, wrong-frame, unsupported, over-limit, or
superseded candidates hold.

### `SafetyDispositionV1`

Contains the monotone disposition, reason codes, governing evidence, clamps, and
decision time. The final governor reevaluates the candidate after smoothing. Stop
bypasses smoothing; no jerk/comfort feature may delay it.

### `RobotGatewayV1`

Use a length-bounded versioned binary protocol over local Unix `SOCK_SEQPACKET`
(protobuf or an equivalently fuzzed schema) for the first onboard deployment:

- `Hello/Capabilities/DriverStatus`;
- `Acquire/Heartbeat/Release` with one writer and boot epoch;
- `BodyTwistSetpoint` with sequence, duration TTL, frame, task/trace IDs;
- `Stop` and `EmergencyStop`;
- source-stamped `RobotMotionState` and post-stop stationary witness.

The gateway derives local expiry, starts disarmed after every restart, refuses a prior
epoch, and compensates with another stop if a late `Move` completes after a stop
boundary. The AI/UI user IDs cannot open the robot NIC, DDS socket, or gateway admin
endpoint.

### `TerminalWitnessV2` (REVISED per RC-2)

Success is a fresh predicate over the requested relation/acceptance region, current
semantic and geometric evidence, unchanged task/snapshot revisions, and consecutive
settled feedback samples. “Command sent,” “path exhausted,” and “model said done” are
not terminal truth.

**Required: a localization-uncertainty reserve term.** r1's contract let the arrival
predicate consume the entire acceptance band, which is exactly the defect this repo
has already measured and 4-0 audit-confirmed in `backlog/BLOCKED.md` **B5**: on the
`calibrated_go2_reanchoring` arm the controller stops 0.002–0.040 m inside the 2.5 m
outer band edge *in its own MAP frame* while claim-tick MAP error runs 0.007–0.239 m,
so 3 of 7 arrivals were TRUE-outside the band (−0.153 / −0.043 / −0.024 m). Neither
existing guard catches it: the provider reports `HEALTHY` at the claim tick and its
covariance is 3.6× optimistic by documented design. A contract that only requires
"fresh geometry" reproduces the defect at the contract layer.

`TerminalWitnessV2` therefore additionally requires, as a first-class field and not a
consumer's optional check:

- `pose_uncertainty_reserve_m` — the reserve withheld from the acceptance region for
  localization error, with its derivation recorded (distance-since-last-reanchor ×
  calibrated drift band, or an owner-set fixed reserve; the mechanism is B5's 2×2, the
  *requirement that a reserve exists* is not);
- the effective margin `region_margin_m − pose_uncertainty_reserve_m`, which must be
  **> 0** for the witness to pass;
- the claim-tick pose-error estimate and its provenance (which estimator, which frame,
  which evidence IDs), so a witness can be re-adjudicated from the record;
- an explicit statement that provider `HEALTHY` and reported covariance are **inputs
  to** the reserve, never substitutes for it — B5 enumerates DEGRADED gating,
  covariance gating, and epsilon widening as non-fixes with reasons.

A witness whose reserve is unknown, non-finite, or larger than the available margin
does not pass; it holds and reports insufficient localization confidence. Reserve
consumption is recorded per arrival so the honest arrival rate is auditable.

**Scope boundary.** This is the *contract*. Changing the shipping product's K0 arrival
predicate moves every frozen eval row and is owner-gated by B5's 2×2 (global rule 2:
frozen-row movement = STOP + 2×2). Wave 0 may land the contract, the spike fixture, and
the regression test; it may not retune the shipping predicate, the K0 band, the scorer
epsilon, or the eval arm. Until the owner decides, the standing nightly
`pose-drift-arms:safety` red is the record and must not be greened.

## Conversation, intent, and behavior design

### Rejected: one omnipotent LLM response

A single prompt returning prose plus free-form motor actions minimizes model calls but
couples conversational style to safety, makes corrections/races hard to resolve, and
lets latency or hallucination sit on the motion path.

### Rejected: two unconditional LLM calls per turn

Always running a conversation model and a planning model independently improves role
specialization but duplicates GPU/KV memory, can produce inconsistent commitments,
and adds latency even for “stop,” “yes,” or casual conversation.

### Accepted: deterministic triage with conditional parallel lanes

1. The audio service produces partial hypotheses for display/provisional barge-in.
   Only a final transcript starts a task-authority turn.
2. A deterministic closed-intent router recognizes emergency stop, cancel, pause,
   resume, direct follow/hold, and other high-confidence registered skills. It emits an
   immediate deterministic acknowledgement without waiting for a general LLM.
3. Conversation generation starts from the exact final transcript and memory snapshot.
4. A deliberative task lane runs only when spatial references, multi-step behavior, or
   low router confidence require it. It receives a bounded scene summary and emits
   `TaskTransactionV2`/`PlanIR`, never velocities.
5. A priority-aware inference broker owns model admission, cancellation, KV/cache
   lifecycle, VRAM budget, and deadlines. Sharing model weights is encouraged at first;
   sharing one unsafe cancellation handle is not. Direct commands never enter its queue.
6. Independent results share turn/task/scene revisions. A correction supersedes older
   output. Speech may continue while navigation owns the base; a reaction requiring
   base/posture is skipped or deferred according to TTL/resources.
7. The response states the actual disposition: accepted, clarifying, navigating,
   deferred, held, failed, or completed. It does not promise motion before admission.

Examples:

- “Walk to the sidewalk”: task lane grounds a sidewalk region, selects a reachable
  non-road acceptance region, plans a corridor, and terminally verifies `inside`
  sidewalk plus settled—not one guessed point.
- “Walk around me once”: owner must be `LOCKED`; the deterministic orbit skill
  generates a local-radius path around the current owner prediction, replanning around
  obstacles without scaling to the town.
- “That was funny”: conversation can stream a chuckle/voice response. A decorative
  gesture is proposed; if navigation owns the base it is skipped/deferred and cannot
  interrupt an important task.
- “Stop!”: deterministic stop/ack preempts every model and latches or cancels according
  to the safety policy. Speaker identity may be relaxed for emergency stopping but not
  for starting motion.

### Voice authority and resource contracts

Add these versioned types before increasing voice autonomy:

- `AudioFrameV1`: device/stream/sequence, capture monotonic time, PCM format, and
  far-end-reference sequence;
- `AecHealthV1`: healthy/converging/degraded/unavailable, ERLE/residual echo,
  reference delay, double-talk, observation time and expiry;
- `SpeechHypothesisV1`: utterance/revision/stable prefix/text, partial/final,
  confidence, speech start/end, speaker track/DoA and evidence refs;
- `CommandAuthorityV1`: trusted principal (`owner|operator|guest|unknown`),
  authentication method, scoped capabilities, validity window and evidence;
- `CommittedTurnV1`: exact transcript/hash, speech evidence, authority, epoch/source;
- one canonical resource enum: `base`, `posture`, `voice`, `attention`,
  `perception_scan`, `expression_audio`.

Trusted pairing/authentication code produces `CommandAuthorityV1`; an LLM, wake word,
voiceprint, Bluetooth RSSI, or nearest visible person cannot. A dedicated streaming
stop detector may issue a conservative protective hold from partial audio; only the
committed stop path latches the software stop, and only authorized operator/owner or
hardware control clears it. Accepting stop from a bystander is safe-side denial of
service and must be measured; accepting positive motion is forbidden.

Resource arbitration is track-level. A spoken reply or quiet chuckle can coexist with
following; an attention glance may coexist if sensors/control allow it; a bow or
excited leg motion that needs posture/base defers or expires. A blanket `base_busy`
veto is too coarse, but conversation never owns base velocity.

## Model selection and learned-policy policy

No model is labeled “best” until it passes an on-device tournament under concurrent
load. The current CPU-only Gemma result is not representative GPU deployment evidence.

### Conversation/task candidates

- The installed Gemma 4 26B-A4B Q4: admitted incumbent and regression anchor; run its
  existing CUDA profile through the updated tournament instead of judging the live
  CPU fallback as the deployment profile.
- Gemma 4 E4B and 12B quantized variants: lower-latency open-weight challengers because the
  official family supports system prompts, thinking control, multimodality, and
  function calling at sizes plausible for the 32-GB desktop GPU.
- The existing Ministral artifact: additional historical regression anchor.
- One additional license-compatible current instruct model: challenger chosen only
  after its official model card/license and memory budget are recorded.

Run 50–100 multi-turn cases across intent correctness, clarification, affect,
non-sycophancy, memory, contradiction, tool use, refusal, plan validity, TTFT, total
latency, tokens/energy, and human conversation ratings. Use current skill registry and
version the evaluator with the prompt/model; the stale-gesture rubric discovered in
today's ad hoc probe must not masquerade as model failure.

### Navigation candidates

- Deterministic RPP/DWPP forward-preferred baseline first.
- MPPI with social/uncertainty/comfort critics in shadow, then controlled promotion.
- ViNT/NoMaD, NaVILA/CityWalker-style models only as subgoal/trajectory proposal
  challengers with frozen adapters and embodiment-specific replay.
- OpenVLA/openpi are manipulation-heavy/experimental and are not direct Go2
  navigation policies.

Record counterfactual progress, collision margin, disagreement, deadline miss, compute,
and fallback rate. Promotion requires a preregistered held-out improvement with no
regression in hard gates. Shadow models cannot share the gateway credential.

#### Abandonment criteria for the RPP/DWPP baseline (N-7)

r1 stated promotion criteria for the challengers but never stated what would retire the
deterministic baseline, which makes "RPP first" unfalsifiable. RPP/DWPP is abandoned as
the *baseline* (not merely supplemented in shadow) if, on the same preregistered
held-out replay set and under identical safety inputs:

1. **Structural infeasibility, not tuning.** RPP cannot satisfy a required behavior at
   any parameter setting inside its documented envelope — the concrete candidates are
   dynamic-obstacle avoidance requiring lateral evasion in a corridor narrower than the
   turn-first preference permits, and social passing-side selection, neither of which
   RPP represents. Two independent parameter sweeps must fail before this is claimed,
   and the failing behavior must be named in advance.
2. **A challenger wins on hard gates, not on progress.** MPPI or a learned proposer
   shows a preregistered improvement with **zero** regression in collision margin,
   false-terminal rate, deadline misses, and fallback rate — and the win survives on a
   held-out set the challenger's tuning never saw.
3. **The determinism argument stops holding.** If RPP's replay-determinism advantage is
   lost in practice (nondeterministic costmap or transform inputs make its output
   irreproducible run-to-run), then its main non-performance justification is gone and
   the comparison is re-run on performance alone.
4. **Deadline economics invert.** RPP cannot hold the 20–50 Hz local-navigation budget
   on target compute while the challenger can.

Failing 1–4, RPP stays the baseline even if a challenger looks better on progress or
SPL; and in every case the deterministic fallback path must remain executable under
model failure (Wave-3 exit already requires this). Retiring the baseline requires a
recorded decision, not a benchmark table.

### RL decision

Do not train a general end-to-end policy now. If failures later isolate a narrow stable
gap, train one component—social trajectory critic, terrain traversability classifier,
or candidate ranker—on logged/replayable data. Identity authority, collision
protection, task revisions, terminal truth, and gateway ownership remain deterministic.

## Perception and navigation algorithms

### Sensors, calibration, and fusion

Only camera, LiDAR, and robot-internal proprioception/IMU provide local physical
evidence. Google Maps remains a route-hint placeholder and never proves traversability.

1. Preserve device and host receipt timestamps; estimate clock relation and uncertainty.
2. Deskew LiDAR with the LIO/IMU trajectory and transform at capture time.
3. Run high-rate closed-set people/vehicle/floor/curb/stair/obstacle perception.
4. Run lower-rate query-conditioned open-vocabulary grounding for lampposts,
   sidewalks, shops, signs, and novel referents.
5. Associate masks/detections with depth/LiDAR clusters; output 3-D covariance and
   repeated-evidence history. Detector `reachable=true` is never authority.
6. Keep people/dynamic objects out of the static map and in a predicted dynamic layer.
7. If geometry, calibration, timing, or localization is stale/incoherent, hold.

Owner enrollment collects consented front/back/side views at several distances. Track
all people geometrically; compute face/torso/body re-identification selectively and
fuse it with temporal/spatial motion plus a `NONE` hypothesis. Raw frames are retained
only under an explicit privacy policy.

### Localization and frames

Bake off GLIM, KISS-ICP, and the Unitree Point-LIO reference on identical official L2
bags, then on the exact mounted sensor. Compare initialization, ATE/RPE, loop closure,
relocalization, CPU/GPU/memory, timestamp faults, motion distortion, feature-poor
areas, and long-run drift.

The contract is REP-105-like:

- `odom -> base_link` is continuous and drives local control;
- `map -> odom` may correct global drift;
- a loop-closure jump invalidates the global plan but never jumps a body command;
- route memory/VPR proposes place identity; geometry verifies it.

### Semantic/global planning

1. Parse a semantic relation (`inside sidewalk`, `near lamppost`, `behind owner`).
2. Ground one or more entities/regions with uncertainty and absent-target support.
3. Build a safe acceptance region from semantics, reachability, road/terrain policy,
   footprint, clearance, visibility, and interaction pose.
4. Select a goal pose inside the region; avoid exact-center superstition.
5. Use the surveyed route graph for known long routes; fall back to a grid/Hybrid-A*
   corridor only over observed/commissioned terrain.
6. Replan on evidence revision, blockage, owner movement, or route-policy change.
7. Terminally verify relation + evidence + settled state.

### Local/social control

Initial controller:

- Regulated/Dynamic Window Pure Pursuit semantics;
- rotate toward path heading before substantial forward travel;
- forward motion preferred, normal `vy = 0`;
- lateral motion remains supported for bounded yielding/recovery and capable platforms;
- reverse disabled for ordinary point goals but available to explicit relative skills
  such as “back away five steps,” subject to rear geometry;
- curvature, obstacle distance, uncertainty, acceleration, jerk, and speed regulated;
- final collision governor runs after smoothing and can never be bypassed.

MPPI shadow critics include static/dynamic collision, anisotropic personal space,
social groups/passing side, route progress, forward preference/lateral penalty, yaw,
acceleration/jerk, terminal relation, and uncertainty. Learned multi-modal pedestrian
prediction may challenge constant velocity; low confidence inflates protected space
and reduces speed.

Terrain is a separate capability lane: 3-D occupancy/ESDF plus a 2.5-D elevation map
for slope, step height, roughness, support, overhang, and negative obstacles. Ramps and
stairs remain prohibited until the full approach/transition/retreat region is observed,
within a commissioned Sport gait envelope, and physically validated with spotters.

### Speed from evidence, not preference

For pilot speed `v`, require at least:

```text
clearance(theta) >= v * (sensor_age + compute_p99 + bridge_p99 + actuator_delay_p99)
                  + v^2 / (2 * verified_min_deceleration)
                  + geometry/localization uncertainty
                  + fixed risk margin
```

If measured clearance cannot satisfy this envelope, clamp or stop. The initial
0.3–0.5 m/s pilot limit is a ceiling pending physical stop-envelope measurement, not
an assertion of safety.

#### Directional and closing relevance are part of the envelope (RC-3)

`clearance` above is written `clearance(theta)` deliberately. r1 stated the envelope
over a **bare scalar** nearest-obstacle distance, and a bare scalar reproduces a wedge
class this repo has already measured and 8/8 refuter-confirmed —
`backlog/BLOCKED.md` **B6**: under the shipping config
(`safety.stop_distance_m: 0.8`) `apply_collision_brake` zeroes any command whenever
`nearest_obstacle_m ≤ 0.8` and the bearing has *any* positive closing fraction, so
`cos(−1.53 rad) = 0.041 > 1e-9` passes the relevance gate. A static crate at exactly
the stop radius and **87.7° off the travel axis** stops the robot dead for as long as
it stands there — 63 brake calls zeroing 0.09–0.85 m/s requests on one episode, and
40 of 42 route-memory-armed eval cells failed wedge-like. It is reachable flag-OFF: a
pre-existing product defect, not route memory's.

The final governor's specification is therefore not "nearest obstacle < radius ⇒
stop". It is:

1. **Clearance is directional.** The braking constraint is evaluated per bearing
   sector against the *swept footprint of the candidate*, not against a single
   nearest-return scalar. An obstacle outside the swept corridor constrains the speed
   at which the corridor may be widened, not the speed along it.
2. **Relevance requires a real closing rate, not a nonzero one.** A closing-fraction
   floor of `1e-9` is a floating-point test, not a physical one. The floor must be
   derived from the measured worst-case combination of pose uncertainty, obstacle
   position uncertainty, and one controller period of yaw authority — i.e. the
   smallest closing rate that could actually consume the margin before the next
   admissible correction — and it must be recorded with that derivation.
3. **Time-to-collision, not distance alone.** The gate is
   `ttc(theta) = clearance(theta) / max(closing_rate(theta), 0)` compared against the
   stop envelope above; a non-closing obstacle has infinite TTC at any distance.
4. **Lateral clearance is stated separately** from along-track clearance, so a path
   that is clear along track cannot be zeroed by a perpendicular return, and a path
   that is *not* laterally clear cannot be admitted by an along-track-only test.
5. **Monotonicity is preserved.** None of the above may *raise* a disposition:
   directional relevance can only decline to escalate a stop that a scalar test would
   have raised spuriously. Where the directional evidence is missing, stale, or
   ambiguous, the governor falls back to the conservative scalar test and holds. This
   is the property that keeps RC-3 inside "no safety weakening".

**Scope boundary.** As with RC-2, this is the *specification*. `apply_collision_brake`
is owner-gated by B6's 2×2 — the fix changes hard-safety semantics (when may a
near-perpendicular, non-closing obstacle inside the stop radius *not* stop the robot?)
and moves every frozen eval row. B6 records the candidate directions
(bearing-scaled stop radius vs a closing-fraction floor above `1e-9` vs a
lateral-clearance carve-out); each must re-prove the frozen `collision=0` rows. Wave 0
lands the spec and the regression test against the spec, not a product change.

## Audio and conversational embodiment

The purchased XVF3800 path is the intended prototype audio front end. It enumerates as
USB Audio Class 2, but an acoustic pass requires the speaker signal to traverse the
array's own USB/I2S-to-DAC reference path. A separate playback device defeats the
expected AEC reference.

Implementation rules:

1. Select input/output by stable commissioned identity, never “default device.”
2. Preflight both directions before constructing the speaker sink; no endpoint means
   text-only and no “spoken” metric.
3. Add actual device write/presentation timestamps where the host API permits; worker
   queue start remains explicitly a lower-bound metric.
4. Stream ASR partials to UI/barge logic; submit final text only to action reasoning.
5. Wire hardware AEC or a real far-end reference, then provisional duck/restore.
6. Piper remains the deterministic low-resource fallback. Fish Speech and Sesame CSM
   are TTS/prosody challengers; CSM explicitly is not a conversation LLM.
7. Measure through-air AEC/ERLE, double-talk, wind, traffic, footsteps, distance,
   accents, moving speakers, false accepts/rejects, endpointing, barge, audible ack,
   and thermal contention while following.

## Failure semantics

| Fault | Required response |
|---|---|
| Camera/LiDAR/pose/feedback missing or stale | exact hold; no physical open-loop fallback |
| Wrong frame, uncommissioned origin, malformed/non-finite payload | latched stop and operator-visible fault |
| Source clock jump/large mapping residual | reset mapping, degrade/hold; watchdog stays on receive-monotonic time |
| `map -> odom` discontinuity | hold local continuous odom, invalidate global plan, reconcile/replan |
| Owner occluded/ambiguous/possible ID switch | stop translation; bounded in-place search or ask user |
| Semantic target absent/ambiguous | observe another view or clarify; never invent arrival |
| Dynamic track lost in crowd | inflate uncertainty, slow/hold |
| Unknown/prohibited terrain | do not enter |
| Planner/model deadline miss | use only a still-valid previously admitted candidate briefly, then hold |
| Task/scene revision changed | discard late output |
| Lease/heartbeat lost, mode mismatch, stale robot state | stop locally and verify stationary |
| `Move` send succeeds but body does not progress | hold/stop from feedback discrepancy |
| `StopMove` fails or motion persists | compensating stop, latched fault, independent operator stop |
| GPU overload/thermal pressure | shed models in priority order; never shed control/safety |
| Low/critical power | deterministic derate/safe posture/shutdown policy; LLM cannot override |
| Process restart | disarmed; reject prior epoch; never auto-resume |
| Competing writer/app/remote | preflight block or stop/latch; operator resolves ownership |

## Security, privacy, and deployment

- Bind the robot gateway to a commissioned wired NIC/MAC and DDS domain; fail on a
  missing/ambiguous interface. Do not auto-pick Wi-Fi.
- Run gateway, sensors/navigation, Parcel brain, models, audio, UI, and telemetry as
  separate least-privilege identities. Only the gateway sees the Unitree NIC/DDS.
- Authenticate remote commands with device identity, mTLS, RBAC/capabilities, nonce,
  anti-replay, and audit. The current loopback web panel is not an outdoor UI.
- Enable and enforce ROS/DDS security if messages cross a trust boundary; permissive
  defaults are not acceptable.
- Raw owner audio/video and embeddings are privacy-classified, encrypted, minimized,
  consented, and retention-bounded. Derived metrics should not require raw content.
- Pin vendor/source SHAs, OS, Python/CycloneDDS/CUDA versions, model hashes, licenses,
  SBOM, calibration compatibility, and config in one release manifest.
- Use signed atomic A/B updates with boot confirmation/rollback. Updates and model
  swaps are inhibited while armed or moving.
- Add robot battery/current and compute temperature/throttle/fan/storage health with
  hysteresis. Current simulated battery data is not authority.
- Maintain a hazard log and independent safety review using applicable personal/service
  robot standards as process input; this plan does not claim certification.

## Evaluation ladder

Each higher rung inherits all lower gates. No rung is allowed to “prove” the next.

| Rung | Environment | Primary proof sought | Does not prove |
|---|---|---|---|
| L0 | pure contract/unit/property/fuzz | schemas, revisions, monotone authority | integration/timing |
| L1 | deterministic fake gateway/SDK | leases, deadlines, kill/stall/restart/stop dominance | vendor/physics |
| L2 | raw `rosbag2` + hashed Parcel evidence replay | real sensor formats, timing faults, deterministic decisions | live actuation |
| L3a | current fast simulator | broad task regressions and counterfactuals | camera/SLAM/terrain physics |
| L3b | MetaUrban/MetaDrive/Habitat adapters | held-out dynamic city, semantics, crowds | Unitree Sport/HIL |
| L3c | Unitree MuJoCo | DDS/IDL/LowState and future low-level work | high-level Sport lease/RPC |
| L4 | exact deploy image under resource faults | packaging, supervision, isolation, load shedding | physical stop |
| L5 | exact compute + robot/controller on stand | vendor state/command/stop/fault behavior | free locomotion |
| L6 | fenced flat indoor/private outdoor | supervised talk/follow/nav exposure | public city/terrain |
| L7 | separately commissioned ramps/stairs/crowds | narrow capability evidence | general autonomy |
| L8 | shadow public observation, then approved pilot | declared ODD evidence | unrestricted city safety |

Raw sensor data uses `rosbag2`; Parcel records derived evidence, decisions, commands,
health, and hashes linking the two. Every run stores run ID/date, software/config/model/
calibration hashes, seed/bag/scenario, platform/firmware, metrics, failures, explicit
`does_not_prove`, and reviewer verdict. An eval adapter may translate interfaces but
must not change Parcel behavior or benchmark success rules.

## Metrics and proposed promotion gates

These are starting prototype targets for Fable/risk review, not published standards.
Physical limits must be ratified from measured stopping and the declared ODD.

**Every numeric target in this section is `proposed pending hazard/ODD derivation`
(N-7).** Brief question 11 is conceded without qualification: not one number below was
derived from a hazard analysis or a declared operating domain. They are engineering
placeholders chosen to be falsifiable, and each is superseded the moment the hazard log
exists. Two consequences bind now: (a) no number here may be cited as a safety
argument, in this repo or outside it; (b) a target may not be *relaxed* to make a gate
pass — a missed target is evidence, and the hazard derivation is the only thing that
may move it. The `100%`/`zero`/`100/100` items are proposed acceptance *thresholds*
with the same status; "zero observed" is reported with a confidence bound, never as
"zero probability". Latency targets marked ⟂ additionally owe the W0-C TTL/latency
derivation (RC-4) before any constant is frozen.

### Safety/control

- Proposed: 100% reject malformed, non-finite, wrong-frame, stale, replayed,
  prior-epoch, uncommissioned-origin, and unsupported-capability commands.
- ⟂ Proposed: sensor invalidation to issued zero target, p99 ≤100 ms.
- ⟂ Proposed: recognized emergency stop to issued zero target, p99 ≤150 ms.
- ⟂ Proposed: client/process/IPC/lease loss to gateway stop initiation, p99 ≤150 ms;
  stationary time/distance recorded separately and within the commissioned envelope.
- Proposed: E-stop from every lifecycle state, 100/100, independent of AI/GPU/app
  network; clear requires operator plus fresh stationary evidence.
- Proposed: zero stale nonzero commands, unauthorized writers, false terminal credit, or
  automatic resume across a two-hour full-stack soak and 10 km-equivalent simulation.
- ⟂ Proposed: 50 Hz gateway p99 scheduling jitter <2 ms and zero deadline misses beyond
  TTL on target compute, to be revised from measurements.

### Owner/navigation

- Proposed: zero owner-ID transfers and pedestrian contacts in preregistered adversarial
  held-out suites; publish confidence bounds rather than infer safety from zero
  observations.
- Proposed: follow band ≥90% of unobstructed time; report loss/reacquisition, social
  intrusion, closest approach, jerk, and stop distance. **Conditioned on B6** (RC-3):
  see the Wave-2 exit note — this number is not reachable while the collision brake
  zeroes commands for perpendicular obstacles at the stop radius, so it may not be
  scheduled as an exit gate until the B6 owner decision lands.
- Proposed: product semantic task suite moves from SR 0.24 toward ≥90% before field
  promotion, with zero false-arrival credit and family/tier reporting. **Conditioned on
  B6** (RC-3) for the same reason, and its "zero false-arrival credit" clause is
  conditioned on **B5** (RC-2): the honest current rate is 3/61, not 1/61, and the
  arrival predicate cannot report zero false arrivals until a pose-error reserve exists.
- Proposed: every accepted semantic terminal witness contains fresh geometry + semantics
  + settled feedback at unchanged task/evidence revisions, **and a positive effective
  margin after the RC-2 localization-uncertainty reserve**.
- Proposed: map reanchor never causes a discontinuous local command.

### Conversation/audio

- Proposed: updated 50–100-turn machine suite, ≥90% intent/plan validity plus a
  human-rated conversation target agreed before the tournament; parse alone is
  insufficient.
- Proposed: acoustic endpoint p50 ≤500 ms, p90 ≤1.0 s, cutoff ≤5%.
- Proposed: barge detection p50 ≤400 ms; false barge <2%; acoustic stop p50 ≤520 ms.
- Proposed: first audible/detectable acknowledgement p50 ≤700 ms; no queue timestamp is
  labeled audible.
- ⟂ Proposed: across 50 simultaneous follow+talk episodes, speech/model load worsens
  stop p99 <10% and produces zero control TTL misses.
- Proposed: through-air corpus covers multiple speakers/accents, 0.5–5 m, motion, robot
  playback, wind/traffic/footsteps, double-talk, and AEC reference faults.

### Reliability/resource/security

- Proposed: one-hour concurrent scenario followed by an eight-hour soak with no
  deadlock, unbounded queue, stale motion, disk-corruption, or thermal-policy violation.
- Proposed: full disk, blocked telemetry exporter, model OOM, GPU saturation, network
  loss, and source-clock jumps do not delay local stop/watchdog behavior.
- Proposed: update signature failure, interrupted install, incompatible
  schema/calibration, and rollback are tested; every reboot starts disarmed.
- Proposed: unauthenticated/replayed remote motion is denied; model/UI identities cannot
  access the robot interface.

## Suggested implementation design

### Wave 0 — accepted contracts and P0 truth (62–92 engineer-hours)

This is the immediate implementation batch after Fable accepts/revises the design.

**Base pointer for every W0 card: commit `7242660` (RC-6).** r1 baselined the cards on
an unlanded dirty worktree; that worktree landed during the review. Each card's OWNS
set, its "simulator behavior unmoved" claim, and its byte-identity proofs are stated
against `7242660`, and any card re-run reports the commit it actually ran at. The r1
stop condition "current route-memory/pose-drift work overlaps an owned file without a
clean merge" is moot at this base: no W0-owned file (`control/base.py`,
`control/models.py`, the `runtime.py` state-source wiring, `core/input_health.py`,
`control/factory.py`, `unitree_control.py`, `providers.py`, `duplex/*`) carried
uncommitted edits at the landing. `runtime.py` stays single-owner (W0-A).

#### Card W0-A — physical feedback and typed provenance (8–12 h)

OWNS:

- `control/base.py`, `control/models.py`, narrow runtime state-source wiring,
  `core/input_health.py`, focused tests.

Implement:

- retain any read-only `RobotStateSource` for `.latest()`;
- create a separate simulator-only `ObservationSink.update_observation()` seam;
- put typed `EvidenceOrigin` on boundary data; remove string inference;
- reject `UNKNOWN` for physical authority;
- preserve vendor/source time, host receipt, session epoch, and sequence;
- make missing calibrated geometry an exact hold for physical deployments; preserve the
  existing simulator default until its frozen behavior is deliberately migrated.

Gates:

- physical `unitree_sport` feedback can satisfy a commissioned input-health join;
- simulator/replay cannot satisfy physical requirements;
- `unknown`, stale, reordered, future, wrong-frame, and invalid data hold/latch exactly;
- no missing scan/geometry path can emit physical translation;
- simulator behavior and frozen evals do not change.

#### Card W0-B — commissioning-only path (8–12 h)

OWNS:

- `control/factory.py`, `unitree_control.py`, new commissioning record module/tests.

Implement an explicitly armed manager that permits only one axis, 0.02–0.05 m/s
initially, short TTL/duration, fenced/support-rig instructions, stop confirmation, and
evidence output. It cannot enter the autonomous runtime. Normal factory gates remain.

Gates:

- commissioning works while flags are false;
- it cannot issue multi-axis/autonomous/over-limit/over-duration commands;
- interruption, state loss, process exit, or failed stop produces a latched failure;
- only a reviewed evidence record can enable normal configuration.

#### Card W0-C — gateway protocol and fake high-level Sport service (16–24 h)

OWNS:

- new isolated `bridge/` package/process, protocol schemas, fake transport, system tests;
- no changes to navigation behavior.

Implement the bounded UDS protocol, boot/session epoch, sole writer, local TTL/
heartbeat, status, stop confirmation, and fake service faults: delayed/no-reply `Move`,
late completion, lease loss, stale/out-of-order state, unknown modes, clock jumps,
process kill, writer conflict, and `StopMove` failure.

**Pre-freeze deliverable: the TTL/latency derivation table (RC-4).** Brief question 7
was never answered in r1. The live control TTL is **`command_timeout_s = 0.35 s`**
(`src/parcel_robot/control/models.py:69`, `configs/robot.yaml:116`, and the
`control/factory.py` default — verified in-tree at `7242660`), while the proposed p99
gates above (sensor invalidation ≤100 ms, e-stop ≤150 ms, client/lease loss ≤150 ms,
50 Hz jitter <2 ms) were stated without ever being reconciled against it. Two numbers
that were never put in the same table cannot both be design constants.

W0-C must publish, **before any protocol constant is frozen**, a table with one row per
proposed deadline and these columns: the proposed p99 gate; the 50 Hz loop period
(20 ms) and how many control periods the gate spans; the live 0.35 s TTL and how many
periods *it* spans (17.5); the worst-case distance travelled at the 0.3–0.5 m/s pilot
ceiling during each; whether the gate is dominated by the TTL (i.e. whether a stale
command can outlive the deadline the gate promises); and the derivation or measurement
each number rests on. The obvious tension to resolve on the record: a 150 ms
client-loss stop-initiation gate sits inside a 350 ms window during which the last
accepted setpoint remains valid, so "stop initiated" and "motion ended" are different
events with different numbers, and the plan must say which one each gate measures.

**Does Wave 0 retune `command_timeout_s`? Recommendation: no — derive first, retune
only from measurement.** 0.35 s is the shipping simulator constant and every frozen
eval row was produced under it; changing it in Wave 0 would move frozen behavior to
satisfy a number that has no hazard derivation yet (global rules 3 and 6, and N-7's
"proposed pending hazard/ODD derivation" marker applies to the gates, not to the live
constant). W0-C publishes the table and pins it in a test; retuning is a separate,
explicitly-justified change carrying stop-envelope measurement from L5, and if the
table shows the TTL and a gate are actually irreconcilable, that is a STOP-and-report,
not a quiet retune.

Gates:

- two clients cannot own motion;
- kill/freeze/client loss stops locally and never auto-resumes;
- prior-epoch/duplicate/out-of-order/non-finite/wrong-frame messages are rejected;
- late `Move` across a stop boundary produces compensating stop;
- fake send-success/no-motion is detected from feedback;
- the TTL/latency derivation table exists, is pinned by a test that fails if
  `command_timeout_s`, the control rate, or any proposed gate moves out of agreement
  with it, and no protocol constant is frozen before it lands (RC-4).

#### Card W0-D — output/audio truth and evaluator semantics (6–10 h)

OWNS:

- endpoint preflight, voice source labeling, audible-latency semantics, acoustic runner
  exit status, focused tests.

Do not implement full duplex yet. Make text simple and reliable; make audio claims
honest. Speaker construction requires output preflight, acoustic turns are labeled as
such, and failed gates produce a failing process. Preserve text input.

#### Card W0-E — evidence recording and clocks (8–12 h)

OWNS:

- clock mapper reference, raw/derived bag link, trace schema, fault tests.

Add dual timestamps/uncertainty/session/calibration/software hashes; raw ROS bags are
append-safe source evidence and Parcel decisions reference them by digest. Logging is
off the control path.

#### Card W0-F — CI/refutation harness (8–10 h)

OWNS:

- contract/property/fault tests, the new authority-invariant CI gate defined below, run
  manifest.

Port accepted spike invariants to canonical product tests, add process-level fault
campaigns, and ensure every evaluator returns nonzero on failed hard gates.

**Definition of the "Fable gate" (N-5).** r1 named a gate without defining it. It is a
new **hard** tier in `scripts/ci_gate.py` — call it `authority-invariants` — with this
contract:

- *What it gates:* the ported authority invariants, as product tests rather than spike
  tests. Concretely: typed-provenance admission (no `UNKNOWN`/simulator/replay origin
  satisfies a physical gate), boot-epoch refusal, fail-closed handling of
  NaN/None/inf in every clock, timestamp, and TTL field, latch persistence across a
  subsequent clean tick, monotone disposition composition, sole-writer exclusivity,
  the RC-4 TTL/latency derivation pin, the RC-2 pose-reserve arrival regression, and
  the RC-3 bearing-relevance brake regression. It also gates the mutation campaign:
  the ported invariant set must kill 20/20 of the audit's invariant-killing mutants,
  and the campaign's description must state its true class count.
- *When it runs:* in the `commit` tier — not nightly. These are cheap deterministic
  contract tests; an authority invariant that is only checked overnight is an
  invariant that ships broken for a day. The mutation-kill sub-gate runs on the
  `nightly` tier with a committed-vs-live freshness check, matching the existing
  `mutation-panel-freshness` pattern.
- *What reddens it:* any ported invariant test failing; the mutant kill count dropping
  below 20/20; a new authority-relevant seam landing without a corresponding invariant
  test (enforced by requiring the run manifest to enumerate the seams it covers, and
  failing when a seam is added to the contract module without a manifest entry); the
  derivation pin disagreeing with the live constants; or the manifest not reproducing.
  Red is STOP-and-report, never a waiver — this gate exists precisely to be the thing
  that cannot be tuned to green.
- *What it does not do:* it owns no product behavior and may not modify any evaluator's
  success rule. It is an observer with veto power over merge, nothing else. Naming it
  after the auditor does not delegate the audit to CI: a green
  `authority-invariants` is a precondition for a Fable review, not a substitute.

#### Card W0-G — cognition/audio authority and scheduler isolation (8–12 h)

OWNS:

- voice/audio authority schemas, canonical resources/interruption enum, inference
  broker, bounded asynchronous diagnostics, focused parity/fault tests.

Implement:

- exact committed turn + trusted command authority across text/acoustic sources;
- unknown/bystander cannot start or clear motion; any speaker may request stop;
- one canonical resource/interruption policy shared by prompts, runtime, and evals;
- priority-aware model broker so conversation/planning/summarization cannot
  cross-cancel and direct skills never queue behind inference;
- bounded nonblocking duplex/trace logging; diagnostics drop before control work;
- personality artifacts generated from one policy authority so skill/eval drift fails CI.

**Budget analysis uses the real loop (RC-5).** The synchronous duplex serialization /
rotation / disk append this card removes runs in the **10 Hz `RobotRuntime` semantic
loop** (`loop_hz=10`, `frame_hz=10`) — the loop that dispatches motion — not in the
50 Hz `ControlManager` thread, which does no duplex logging. The card's aim is
unchanged: a blocking disk write on the dispatch path is a defect at any rate. What
changes is the arithmetic the card must show. The budget is the 100 ms semantic-loop
period, and the quantity to bound is how long a blocked or rotating write can delay the
*next dispatch*, measured against the 0.35 s `command_timeout_s` (RC-4) — i.e. the
question is whether a stalled logger can let the previously issued setpoint expire
before a fresh one is dispatched, not whether it can miss a 20 ms control tick. Any
budget figure in this card that was computed from a 20 ms period is recomputed at
100 ms before it is cited.

Gates:

- shuffled partial/final/correction events never execute a partial or stale result;
- talk/chuckle/attention overlays do not alter the follow command trace;
- posture/base reactions defer/expire during critical navigation;
- inference/log/memory saturation produces zero control deadline changes, measured
  against the 10 Hz dispatch period and the live 0.35 s command TTL (RC-5);
- current text-only behavior and frozen task semantics remain intact.

MUST NOT TOUCH in Wave 0:

- frozen episode definitions/success rules;
- route-memory or pose-drift batch under `scrum/20260811/task_2` except conflict
  resolution agreed with its owner;
- collision thresholds or behavior to improve scores;
- the **B5** product surface — the K0 arrival predicate, the K0 band, the scorer
  epsilon, and the `calibrated_go2_reanchoring` arm — which is owner-gated (RC-2). The
  standing `pose-drift-arms:safety` nightly red is the record and is not to be greened;
- the **B6** product surface — `apply_collision_brake`, `safety.stop_distance_m`, and
  the `CollisionPolicy` relevance gate — which is owner-gated (RC-3);
- any physical auto-arm path;
- low-level joint control.

Wave 0 lands the RC-2 and RC-3 *contracts, specifications, fixtures, and regression
tests*. It does not land the product changes those specifications imply; both wait on
their 2×2.

### Wave 1 — sensor/localization spine (3–6 engineer-weeks)

Parallel lanes:

- Unitree L2/camera raw adapters, exact QoS/topic/rate discovery, calibration;
- GLIM/KISS-ICP/Point-LIO bag bake-off and `map -> odom` contract;
- 3-D collision/elevation mapping and stale-input invalidation;
- raw `rosbag2`/derived evidence replay;
- platform/network/API preflight and pinned Ubuntu 22.04/Humble bridge image.

Exit: recorded physical-format data can run unchanged through localization/world
evidence; no simulator metadata provides authority; exact loss/frame/time faults hold.

### Wave 2 — identity-safe flat-ground owner following (3–6 engineer-weeks)

Parallel lanes:

- consented multiview owner enrollment/re-ID;
- camera/LiDAR 3-D person association and identity posterior state machine;
- RPP/DWPP follow controller, loss/search/reacquire, dynamic/social layer;
- adversarial crowd scenarios and SocNavBench/HuNavSim/MetaUrban adapters;
- conversation/follow resource contention and acknowledgement behavior.

Exit: held-out identity/crowd/follow gates pass in sim/replay; then supervised low-speed
hardware trials with independent stop.

**This exit gate is conditioned on the B6 owner decision (RC-3).** The follow-band ≥90%
target is not reachable while `apply_collision_brake` zeroes commands for any obstacle
inside the 0.8 m stop radius with a closing fraction above `1e-9` — a static object
87.7° off-axis holds the robot indefinitely, and 40 of 42 route-memory-armed eval cells
already fail wedge-like, flag-OFF. Scheduling this exit before B6 is resolved would
schedule a gate the product cannot pass for reasons unrelated to following, and the
predictable failure mode is that someone relaxes the band rather than fixing the brake.
Therefore: Wave 2 may run and may report the band, but the ≥90% gate is **not armed as
an exit condition** until the B6 2×2 lands and the frozen `collision=0` rows are
re-proved under whichever mechanism the owner selects. If the owner declines to change
the brake, the band target is re-derived against the brake's actual behavior and
restated — it is not left standing as an unreachable number.

### Wave 3 — semantic city/indoor navigation (3–6 engineer-weeks)

- open-vocabulary referents with absent-target/uncertainty evidence;
- persistent semantic entities and acceptance regions;
- route graph and verified VPR/route memory;
- global corridor plus dynamic/social navigation;
- MPPI and learned subgoal challengers in shadow;
- current instruction suite expanded with real sensor/replay families.

Exit: preregistered ≥90% bounded task success, zero false terminals/contacts in held-out
evidence, and deterministic baseline fallback under model failure.

**Both halves of this exit gate are conditioned on owner decisions (RC-2, RC-3).** The
≥90% success target is conditioned on **B6** for the same reason as Wave 2: `v4r`-class
scenarios with wall-line clutter fail on both arms while the brake stands, so the
suite's ceiling is set by the brake, not by semantics. The "zero false terminals" half
is conditioned on **B5**: the arrival predicate has no pose-error reserve, the honest
measured rate is 3/61 rather than 1/61, and a suite cannot certify zero false arrivals
using the predicate that produces them. Neither half is armed as an exit condition
until its 2×2 lands; both may be measured and reported meanwhile, labelled with the
open defect. As in Wave 2, an owner decision not to change the product surface obliges
a re-derived target, not a standing unreachable one.

### Wave 4 — terrain and deployment hardening (4–8+ engineer-weeks plus hardware)

- elevation/traversability, overhang/negative-obstacle handling;
- capability-gated ramps, then shallow steps/stairs with spotters;
- onboard compute/power/thermal/payload/COM/occlusion characterization;
- security/provisioning/update/rollback/privacy;
- exact-compute HIL, long soaks, and constrained ODD field evidence.

Public roads/city pilot remains a separate go/no-go safety case.

## Parallelization and dependency graph

```text
W0-A provenance/state ----+
W0-B commissioning -------+--> W0-C gateway --> physical preflight/HIL
W0-E clocks/evidence -----+

sensor adapters ---> localization bake-off ---> world snapshot ---> flat follow
camera pipeline ---> owner enrollment/re-ID ---------------------> flat follow
terrain maps -----------------------------------------------------> terrain lane

voice truth ---> model/eval tournament ---> conversation + task lanes
semantic grounding -----------------------> semantic navigation

W0-F evaluation observes every lane and owns no product behavior.
```

Safe independent work before hardware:

- gateway/fake-Sport and process-fault harness;
- official L2 bag replay/localization bake-off;
- owner identity adversarial simulator/replay;
- MetaUrban/Habitat sensor adapters;
- RPP/MPPI differential replay;
- conversation model/rubric tournament;
- security/deployment manifests and update tests;
- through-air audio only after the purchased device arrives.

## Basic design tests completed in this task

The isolated reference model executes 43 tests and **a seeded campaign of 200 draws
over 12 single-fault evidence-corruption classes** — r1 called this a "200-case
corruption campaign", which overstates its breadth by a factor the audit measured
(verdict: CLAIMS THAT MUST BE DOWNGRADED). The r1 spike passed:

```text
43 passed in 0.10s
```

That figure is r1's. The spike is being hardened under card S-1 (RC-1: epoch
enforcement, fail-closed malformed time, a stateful latch, 20/20 mutant kills, and the
RC-2 B5 fixture), so both the test count and the campaign's class count are restated in
`../task_2/S1_STATUS.md`; `VALIDATION.md` records which of the two this revision
actually observed. The honest r1 claim is that 12 of 20 invariant-killing mutants
survived the 43-test suite — the campaign demonstrates the seam, not its coverage.

Covered properties:

- fresh typed physical evidence passes;
- missing/stale pose, geometry, or feedback holds;
- wrong frames, invalid origins/payloads, and future receive time latch;
- source-clock jumps cannot corrupt receive-time watchdogs;
- lab simulation requires an explicit simulation profile;
- the strongest safety disposition dominates;
- stale tasks, late model output, changed evidence, expired candidates, lease loss,
  second writers, uncommissioned platforms, unsupported lateral motion, and non-finite
  velocities cannot authorize motion;
- only a locked owner authorizes follow translation;
- voice-only replies coexist with navigation while base gestures cannot steal it;
- emergency stop dominates even if an activity expired;
- false/stale/unsettled terminal witnesses do not complete a task.

This proves only the small reference contract, not Parcel integration, timing, DDS,
perception, hardware stopping, or public safety. Accepted invariants must be ported to
canonical code and the spike deleted once redundant.

## Required product tests after Fable approval

1. `test_runtime_retains_protocol_state_source_for_physical_input_health`.
2. `test_simulator_observation_sink_is_not_required_by_physical_state_source`.
3. `test_typed_unitree_origin_is_physical_only_after_commissioning` and
   `test_unknown_origin_never_authorizes_translation`.
4. `test_commissioning_manager_measures_with_false_flags_but_cannot_enter_runtime`.
5. Wire schema fuzz/property tests: non-finite, unknown major version, wrong frame,
   stale/duplicate sequence, expiry, prior epoch, oversized message, source/receipt
   disagreement.
6. `kill -9`, SIGSTOP, OOM, client disconnect, NIC/discovery/lease loss while a nonzero
   fake command is active; assert local stop and disarmed restart.
7. Cross-process late-`Move`/stop-dominance and post-stop source timestamp + sequence +
   epoch confirmation.
8. Two-client and competing Unitree app/remote/rogue DDS writer tests.
9. Capability/config/calibration/software hash change cancels admitted work.
10. Golden `map -> odom -> base_link`, yaw/sign/axis calibration, and map-reanchor tests.
11. Sensor delay/drop/reorder/NaN/blind-sector/calibration mismatch and no-open-loop
    physical fallback.
12. Owner similar-clothing/crossing/occlusion/leave-and-stranger/no-owner/group tests.
13. Semantic absent/ambiguous target, viewpoint search, safe acceptance region, and
    fresh terminal witness tests.
14. RPP vs MPPI/learned differential replay under identical safety input.
15. Full disk, blocked exporter, CPU/GPU/memory pressure, clock jump, power and thermal
    derate tests.
16. Actual audio input/output preflight; through-air AEC/double-talk/noise/barge and
    audible-sample latency.
17. Update signature/interruption/schema/calibration incompatibility/rollback and
    motion-inhibit tests.
18. Deployment manifest: non-root, read-only root, dropped capabilities, pinned image,
    resource limits, only gateway access to robot NIC.
19. One-hour talk/follow scenario and eight-hour soak on exact compute.
20. Quarantined, explicitly armed HIL fault script with independent operator stop.
21. Authority matrix: unknown speaker cannot cause/clear positive motion; any speaker
    can stop; paired owner/operator scope and expiry are enforced.
22. Inference broker concurrency: conversation/planning/summarization cannot
    cross-cancel, and closed stop/direct commands never wait for a model.
23. Synchronous logging/memory failure, full queue, or blocked disk produces an
    identical control command/deadline trace.

The verdict adds the following to this list. Items 24–27 are the named required tests;
item 28 collects the missing failure cases that must be folded into the spike campaign
and W0-F.

24. **`test_terminal_witness_requires_pose_uncertainty_reserve`** (RC-2) — the
    pose-reserve arrival regression, with B5's measured episode as the named fixture:
    MAP margin 0.007 m against a claim-tick pose error of 0.239 m must **not** produce
    a passing terminal witness. Seeded-failure proof required: removing the reserve
    term must turn the test red. This is a contract/regression test; it does not modify
    the shipping predicate, which stays owner-gated.
25. **`test_collision_brake_relevance_is_bearing_and_closing_aware`** (RC-3) — the
    bearing-relevance brake regression, with B6's measured geometry as the fixture: a
    static obstacle at exactly the 0.8 m stop radius, 87.7° off the travel axis
    (closing fraction 0.041), must not zero a laterally clear forward command under the
    governor specification. The test must also assert the conservative direction:
    missing, stale, or ambiguous directional evidence still stops.
26. **TTL/latency derivation pinned** (RC-4) — a test that fails if
    `command_timeout_s` (0.35 s), the 50 Hz control rate, or any proposed p99 gate
    moves out of agreement with W0-C's published derivation table.
27. **20/20 spike mutants killed** (RC-1d) — each of the audit's invariant-killing
    mutants named by the test that kills it; the count is a gate, and a survivor is a
    missing invariant, not a scoring detail.
28. Missing failure cases to fold into the campaign and W0-F: prior-epoch lease;
    NaN/None/inf in every clock, timestamp, and TTL field; latch persistence across a
    subsequent clean tick; the B5 fixture (MAP margin < pose error at claim); the B6
    fixture (perpendicular obstacle at the stop radius must not zero a laterally clear
    path); bounded in-place search without fresh 360° collision evidence (N-1);
    a composed physical-translation pipeline threading SIMULATION/REPLAY/UNKNOWN origin
    at each stage (N-2); zero-gate dominant verdict must not return PASS, and at least
    one gate must produce CLAMP (N-3).

## Stop conditions

Stop the batch and ask for owner/Fable direction if:

- a change would modify frozen eval behavior or success definitions;
- current route-memory/pose-drift work overlaps an owned file without a clean merge;
- gateway TTL/stop cannot be made independent of Python/ROS/GPU;
- exact Unitree edition/API/service/firmware cannot be verified;
- no independent physical stop is available for motion commissioning;
- a model improves progress only by weakening collision, provenance, identity, or
  terminal gates;
- a simulator needs a behavior-changing adapter to improve the score;
- source/calibration/license/model provenance cannot be recorded.

## Fable audit directive

Fable should review this as a skeptical production and safety architect, not as a prose
editor. The requested verdict is one of:

- `ACCEPT_ITERATION_3_AND_WAVE_0`;
- `ACCEPT_WITH_REQUIRED_CHANGES` (enumerate blocking changes and tests);
- `REJECT` (identify a safer/faster architecture and falsifying evidence).

Refute first:

1. Does the gateway truly stop if Parcel, ROS, GPU, logging, IPC client, or model dies?
2. Can any second process/app/remote publish effective motion?
3. Is absolute monotonic time incorrectly compared across processes?
4. Can simulator/replay/unknown evidence satisfy a physical gate?
5. Does any LLM/VLM/VLA result become a command or terminal fact without validation?
6. Can an owner ID transfer to the nearest/most convenient person?
7. Does a loop closure jump local control?
8. Does any missing sensor degrade to open-loop physical motion?
9. Can speech/reaction interrupt base ownership or delay stop?
10. Are thresholds presented as standards rather than proposed targets requiring
    hardware/risk validation?
11. Are Unitree app features mistaken for stable SDK APIs?
12. Does an external eval change Parcel behavior or its success rule?
13. Does the plan claim public-city readiness from simulator passes?
14. Are power, thermal, updates, security, privacy, and independent stop absent from
    the production boundary?

Commands:

```bash
cd /home/jaewoo-jang/Desktop/Projects/Parcel
.parcel/bin/python -m pytest -q scrum/20260812/task_1/design_spike/test_contracts.py
.parcel/bin/python scripts/ci_gate.py --tier commit --json
git diff --check
```

Review the local evidence and primary-source ledger in `RESEARCH_LEDGER.md`. Fable
must preserve `does_not_prove` statements and distinguish a design-spike pass from a
product or hardware pass.

## Definition of done for this task

- Three materially different architectures and the production end-state are compared.
- Recommendation, trust boundaries, algorithms, interfaces, timescales, failure
  semantics, security/privacy, implementation waves, parallelism, and gates are
  explicit.
- Research claims trace to primary/official sources in `RESEARCH_LEDGER.md`.
- A design-only executable contract spike passes and states what it does not prove.
- Current product behavior is untouched by this task.
- Fable records a refute-first verdict before Wave 0 product edits begin.
