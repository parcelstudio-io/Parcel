# Parcel robotics code design

**A concise guide to the system boundaries, robotics concepts, design rationale,
and deliberate tradeoffs behind the code**

| Document control | Value |
| --- | --- |
| Status | Living high-level code design for the current checkout; the root README governs the latest verification verdict |
| Design cutoff | 2026-08-26; based on committed tip `f3ecb5c` plus the accompanying P0 companion, research, and social-progress release unit |
| Audience | Software engineers, robotics engineers, technical leaders, and reviewers |
| Scope | Why Parcel exists, how information and authority move through the code, and what the architecture deliberately does not claim |
| Current truth sources | [Root README](../README.md) for readiness/gate status; [production runtime code map](PRODUCTION_RUNTIME_CODE_MAP.md) for the shortest as-built call path |
| Deep reference | [Conversational autonomy engineering handbook](CONVERSATIONAL_AUTONOMY_HIGH_LEVEL_DESIGN.md) |
| Decision record | [Crucial design decisions](DESIGN_DECISIONS.md) |

## 1. Why this software exists

Parcel is intended to become a conversational quadruped companion: a robot that
can understand an owner's intent, navigate and follow over time, behave considerately
around people, accept corrections, and report outcomes truthfully. The current
checkout is a simulation-first autonomy and integration stack. It is not a
motion-commissioned physical Go2 product.

The normal application builder currently does not provide a capability manifest,
matching deployment target, or commissioning authenticator. Automatic embodied and
navigation requests therefore fail closed at admission even in MuJoCo. Manual
browser motion and the separately scoped pose-review gallery remain available; code
existence is deliberately wider than current product admission.

The software exists because a language model, a navigation algorithm, and a vendor
robot controller solve different problems:

- a language model can interpret an open-ended request, but cannot certify a clear
  floor, a fresh owner track, or a safe stopping distance;
- a planner can find a geometric route, but cannot decide who is authorized to move
  the robot or whether a spoken command was final;
- a vendor locomotion controller can balance the body, but does not know the mission,
  social context, or whether the observed bench is the requested bench; and
- a simulator can make failures reproducible, but cannot establish real sensor,
  network, contact, payload, or braking behavior.

Parcel connects those responsibilities without collapsing their authority. Models
propose semantic work. Deterministic code validates, schedules, observes, and admits
it. A short-lived local command passes through separately owned software-safety
restriction and stop logic. Only a sole motion writer may ultimately reach the body.

That separation is the central design choice. It lets the team improve conversation,
perception, navigation, and learning without granting each new model a new path to
the motors.

## 2. The robotics model behind the architecture

### 2.1 A robot is a feedback system

A normal web request can succeed after producing a response. A robot action succeeds
only if the physical world changes as intended and fresh measurements confirm the
change. Parcel therefore implements a repeated feedback loop:

```text
mission intent
     |
     v
observe -> estimate -> choose -> admit -> command -> physical/simulated plant
   ^                                                     |
   +---------------- measured outcome -------------------+
```

The important pieces are:

- **plant:** the simulated or physical Go2 and its environment;
- **observation:** timestamped camera, range, pose, owner, dynamic-agent, semantic,
  and controller evidence;
- **estimation:** a belief about pose, tracks, occupancy, identity, and health;
- **planning:** selection of a goal, path, local motion, or bounded recovery;
- **control:** feedback-supervised execution of velocity or stop requests; and
- **executive:** mission state, resources, revisions, progress, and terminal truth.

These pieces operate at different rates and fail differently. Parcel uses typed
boundaries rather than one end-to-end loop so that a slow semantic model cannot
become the balance controller and a stale conversation cannot become a persistent
velocity command.

### 2.2 Frames, time, and uncertainty are part of every value

Robotic numbers are meaningless without labels. A position needs a coordinate frame;
a velocity needs a body/world convention; an observation needs a source clock and
capture time; and a detection needs uncertainty and provenance. Parcel's
[`EvidenceHeaderV1`](../src/parcel_robot/contracts/evidence_header.py),
[`NavigationSnapshotV2`](../src/parcel_robot/contracts/navigation_snapshot_v2.py),
and pose contracts make those labels explicit.

This is why V2 consumers reject or limit translation when evidence is stale, has
mixed epochs, lacks calibration, changes frames unexpectedly, or crosses a
localization discontinuity. The V2 cutover is not complete: selected navigation,
Follow, and shadow consumers use the snapshot, while the final runtime reactive-
safety path still consumes the legacy observation carrier. Repeating the same
correlated observation five times is not five independent witnesses. A high-
confidence label is not metric geometry. An old clear scan cannot authorize movement
through a corridor that may now be occupied.

### 2.3 Planning and control are different loops

The navigation stack plans over a local occupancy representation and produces a
mid-level body command. The locomotion stack supervises short-lived setpoints and
body feedback. The robot/vendor layer owns the faster balance and foot-contact loop.

This nested arrangement is intentional. The rates below are design classes, not
measured physical loop rates for the current uncommissioned robot:

```text
mission / semantic goal             seconds to minutes
global/local route decisions        roughly 1-10 Hz
runtime safety and command update   roughly 10-50 Hz
vendor balance/contact control      faster, inside Unitree Sport
```

Each lower layer may restrict or stop an upper-layer proposal. No upper layer may
extend the lower layer's authority window.

### 2.4 Arrival is an evidence claim

Distance to a coordinate is not enough to say “we arrived.” Localization may have
jumped, the semantic object may be an alias, the requested relation may be wrong,
or the body may still be moving. Parcel separates route progress from terminal
claims through arrival semantics, revision keys, and receipt-shaped contracts.

An owner-facing arrival is deliberately two phase. The robot first approaches while
facing the semantic target, stops, and satisfies the existing live target, K0
geometry, support/clearance, and feedback checks. Only then may it make a bounded
yaw-only turn toward a freshly tracked owner. Success is withheld until the final
heading and stop are confirmed; a proposed translation, more than 2 cm of measured
displacement, owner loss, stale or unhealthy pose/feedback, invalidated K0 geometry,
or timeout clears the first-phase latch and fails closed. This costs another state
transition and can reject an otherwise usable
pose, but it prevents social etiquette from rotating the target out of view before
the robot has established that it really arrived.

The experimental independent-completion latch goes further by requiring separate
place identity, pose-epoch recovery, and conservative target-relative geometry.
Its latest research gate was refuted, so it remains default-disabled and outside
the product navigation pipeline. That outcome illustrates the rule: a promising
mechanism is not promoted by rounding up a failed result.

## 3. Information flow and authority flow

The same data may inform several decisions, but authority moves through a narrower
graph. The diagram is the target authority architecture; only portions are wired
today, and the current boundaries are called out below:

```text
browser / microphone / text                     camera / LiDAR / body state
             |                                                |
   committed turn + principal                    stamped observation source
             |                                                |
 deterministic intent router                       NavigationSnapshotV2
             |                                                |
  PlanSketch / PlanIR proposal <----- bounded planning context-+
             |
 compiler + validator + capability/consent admission
             +---- current normal builder has no manifest/attestation -> REFUSE
             |
 TaskExecutive + resource/revision ownership
             |
 follow / navigation / spatial / activity controller
             |
 priority + TTL arbiter
             |
 intent smoother
             |
 input health + obstacle/person/TTC final software safety
             |
 post-gate state sync + actuator-side S-curve shaping
             |
 exact-stop reassertion
             |
 ControlManager -> Unix motion gateway -> Unitree Sport -> body
```

STOP is deliberately shorter. A local stop phrase, E-stop, expired lease, stale
feedback, or final safety veto does not wait for deliberative planning.

The admission branch is also a current boundary, not merely a target safety box.
`web_panel.build_runtime` constructs no capability manifest, deployment target, or
commissioning authenticator today. The automatic route therefore ends in a typed
refusal before navigation, Follow, roam, poses, or gestures receive effect authority.
Manual simulator velocity uses the restricted runtime door and still crosses
arbitration and final safety.

The final physical segment in this diagram is the target authority path. In the
current normal-runtime gateway composition, the adapter is permanently disarmed:
it can query state and transmit stop, but has no acquire or velocity-command call.
Desktop tests use fake Sport. Native SDK2/DDS motion, Orin deployment, and physical
feedback remain unimplemented or uncommissioned on this path.

Simulator poses and trajectories are coordinated on separate effect routes:
admitted plan steps, local catalog calls, and pose review can reach `_run_pose` or
`_run_trajectory` after locomotion is stopped, while expression is a subordinate
simulator lane. Physical external control refuses pose and trajectory execution,
and Go2 expression is snapshot-only. The velocity diagram is therefore the primary
locomotion authority path, not a claim that every current simulator effect shares it.

## 4. Code map and ownership boundaries

### 4.1 Composition and runtime coordination

[`config.py`](../src/parcel_robot/config.py) resolves profiles and rejects invalid
physical configuration. [`web_panel.build_runtime`](../src/parcel_robot/web_panel.py)
is the full normal product composition root: it selects the backend and models and
constructs `RobotRuntime`. [`runtime.py`](../src/parcel_robot/runtime.py) is the main
integration coordinator: it owns the simulator-facing tick, installs channels,
builds observations, arbitrates behavior, applies safety, and dispatches the final
command.

`RobotRuntime` is intentionally the integration root, but its size is also known
debt. New algorithms should live in pure or lifecycle-owned modules and be injected
through typed seams. Adding another hidden command path to avoid touching the
runtime is worse than extending the explicit composition boundary.

### 4.2 Conversation and semantic task intent

The [`realtime`](../src/parcel_robot/realtime/) and
[`voice`](../src/parcel_robot/voice/) packages own capture/session behavior,
turn commitment, speaker/ear gates, hosted transport, local intent handling, and
tool proposals. The [`brain`](../src/parcel_robot/brain/) package owns typed plans,
deterministic compilation, validation, task resources, interruption, and the runtime
adapter.

The boundary is semantic rather than motor-level:

- the model may propose `NavigateTo`, `Follow`, a bounded skill, wording, or a
  clarification;
- deterministic code checks schema, capability, identity, consent, current state,
  and allowed resources; and
- raw joints, torque, safety priority, `force`, leases, and arbitrary velocity are
  not model-owned fields.

Hosted speaker binding remains fail-closed scaffolding: the current one-shot verdict
is consumed and normalized to `voice_binding_unavailable`, so it cannot authorize
hosted motion. Production speaker enrollment and a continuously trusted binding are
still missing.

The new companion contracts in
[`companion_v1.py`](../src/parcel_robot/contracts/companion_v1.py) and
[`dialogue_state_v1.py`](../src/parcel_robot/contracts/dialogue_state_v1.py) model
action proposals, admissions, receipts, corrections, repetitions, and terminal
language. They are strict local boundaries, not yet a fully wired live-session
executive or a grant of motion authority.

### 4.3 Capability truth

[`capabilities/manifest.py`](../src/parcel_robot/capabilities/manifest.py) derives an
effective manifest from the selected deployment, adapters, exact asset digests, and
authenticated process-local commissioning evidence. Prompt text, an enum member,
or serialized `commissioned: true` is not enough to make a capability available.

This prevents a common robotics failure: a system advertises a gesture, planner, or
physical action because code for it exists, even though the installed robot cannot
execute it. The manifest is designed to make implementation, deployment, and
commissioning different facts.

The mechanism is implemented, but normal-builder composition is not. With no
manifest, matching deployment target, or trusted commissioning input,
`RobotRuntime` and `VoiceAgent` treat motion as disarmed. Explicitly commissioned
test fixtures can exercise the downstream path; they do not describe the normal
application's admitted capability set.

### 4.4 Observation and world evidence

The [`observation`](../src/parcel_robot/observation/) package adapts simulator,
replay, and future physical sources into one immutable navigation snapshot. The
snapshot carries pose/localization health, obstacle returns, traversability, dynamic
tracks, owner belief, semantic observations, system health, timestamps, calibration,
and provenance.

The current simulator adapter is the working product path. The physical source is
a fail-closed skeleton, and the observe-only Go2 backend refuses positive motion.
The migration is deliberately dual-representation today: V2 is published beside a
legacy carrier, selected consumers use V2, and final reactive safety still consumes
the carrier. That preserves compatibility but creates divergence/provenance risk
until the cutover closes. Simulator metadata may generate deterministic oracle
semantics, but code outside the adapter should consume evidence contracts rather
than query privileged world truth.

Metric localization and semantic memory remain separate:

- localization answers “where is the body in a consistent metric frame?”;
- occupancy answers “where is traversable now?”; and
- semantic memory answers “what might this place or object be, and when was it
  observed?”

Keeping them separate prevents a remembered label or cloud map from manufacturing
fresh free space.

### 4.5 Navigation and social behavior

The [`navigation`](../src/parcel_robot/navigation/) package contains semantic
grounding, rolling occupancy mapping, A* routing, path tracking, owner follow,
search/approach behaviors, person keepouts, time-to-collision checks, arrival
semantics, and recovery policies. `grid_v1` is the selected command-producing
navigator implementation when navigation has been explicitly admitted. The normal
builder currently admits no automatic navigation because its capability composition
is absent. Learned navigator configurations are challenger metadata only; some
semantic and value components can make bounded proposals, but the navigator factory
rejects the learned navigator types today.

The navigation design has three distinct concerns:

1. **goal semantics:** what place, person, or relation the owner meant;
2. **geometric feasibility:** what route and local motion fit current free space;
3. **safety/authority:** whether fresh evidence permits the command now.

The social-progress work keeps that separation. Its prototype observer samples the
requested arbiter winner before dispatch, then records final and achieved velocity,
track visibility, and swept-corridor evidence after the unchanged final gate. It
retains and exposes a bounded in-memory typed shadow trace for research; it cannot
issue motion, shrink a person envelope, authorize a road crossing, or enter an
elevator.

### 4.6 Command arbitration, safety, and control

The [`core`](../src/parcel_robot/core/) package owns command priority, TTLs,
preemption/resume contracts, input health, shaping configuration, and final stop
semantics. [`reactive_safety.py`](../src/parcel_robot/navigation/reactive_safety.py)
separately inspects obstacle, person, and scan evidence within the software process.
The post-shaper
[`finalize_command`](../src/parcel_robot/core/hard_stop.py) boundary reasserts exact
zero for hard stops so smoothing can never turn a stop into residual motion.

[`ControlManager`](../src/parcel_robot/control/manager.py) is the supervised
locomotion owner. It checks controller capability and feedback freshness, refreshes
short-lived targets, handles faults and the software E-stop, and requires stationary
evidence where configured. Backends implement vendor-neutral protocols; Unitree
Sport is one implementation, not the application API.

The deployable [`gateway`](../gateway/) is a separate process/package boundary with
lease, epoch, TTL, restart-disarmed, watchdog, bounded vendor-I/O, and sole-writer
semantics. [`motion_gateway.py`](../src/parcel_robot/control/motion_gateway.py)
currently connects the normal runtime only at the permanently disarmed rung. This
lets the team verify the production-shaped lifecycle without pretending that a
positive physical command path is ready. A legacy direct Unitree Sport controller
also remains in tree for explicit commissioning; it is not the admitted normal-
runtime sole-writer path. One gateway writer is therefore the product invariant, not
a claim that every historical adapter already routes through it.

### 4.7 Simulation, research, and learning

MuJoCo and the deterministic headless city are the inner development loops. They
make seeded failures, replay, timing, and regression inexpensive. The tracked Go2
MJCF proves asset/package integrity and finite articulated simulation, not physical
dynamics or an SDK2/DDS control path.

The default-off [`research_plane`](../src/parcel_robot/research_plane/) admits only
bounded summary events into a separate spool and deterministic bundle format. It
has consent, retention, revocation, byte-governor, and verifier seams, but no real
production encryption, key service, uploader, object store, or remote deletion
provider.

The [`learning_loop`](../src/parcel_robot/learning_loop/) provides immutable split
registries, failure-mined proposals, evaluation records, safety counters, signed
human-review inputs, and rollback artifacts. It is proposal-only: passing an
offline gate cannot activate a model in the product. Deployment remains a separate
authority boundary.

## 5. Failure behavior

Parcel prefers an explicit degraded state to guessed continuity:

| Failure | Required behavior |
| --- | --- |
| Uncommitted/partial speech | May prepare context or interrupt playback; cannot dispatch a physical action |
| Unknown speaker or missing consent | Conversation may continue; consequential owner-relative action is refused or clarified |
| Missing capability or commissioning evidence | Drop/refuse the action; never substitute a nearby physical skill |
| Stale/mixed sensor evidence | HOLD or STOP; stale absence never becomes observed free space |
| Localization jump | Revoke translation/completion authority until a separately evidenced re-arm path succeeds |
| No route or prolonged blockage | Emit typed progress/terminal cause within a budget; do not wait forever or declare success |
| Model, GPU, hosted API, or perception-worker failure | Lose semantic quality/capability without extending motion |
| Runtime/gateway disconnect, lease expiry, or stale body state | Decay to disarmed/stop through local deadlines and watchdogs |
| Software E-stop | Dominates all channels, emits exact zero, and requires explicit safe recovery |

“Fail closed” does not mean “freeze forever.” A stationary robot can still be struck,
block a doorway, or strand a mission. Safe progress therefore needs typed causes,
continuous replanning, bounded recovery, and explicit handoff—not shorter safety
timers or a generic spin/back-up behavior.

## 6. Why the software is built this way

### 6.1 Typed contracts instead of implicit dictionaries

Robotics integrates code that runs at different rates, on different machines, with
different clocks and failure modes. Versioned, bounded contracts make units, frames,
timestamps, provenance, optionality, and authority reviewable. They also support
deterministic replay and mutation tests. The cost is more schema code and migration
work, which the project accepts at safety- and evidence-bearing seams.

### 6.2 One composition root and one motion writer

Central composition makes the effective profile, selected adapters, and command
path inspectable. A single locomotion writer prevents two individually reasonable
controllers from fighting over the body. The cost is pressure on `RobotRuntime` and
the gateway. The response is to extract cohesive services behind explicit protocols,
not to add bypasses.

### 6.3 Deterministic restriction around probabilistic intelligence

Language, perception, prediction, and learned policies are useful because the world
is ambiguous. They remain proposals because their errors are correlated, hard to
enumerate, and sensitive to distribution shift. Deterministic validation cannot
make a bad model good, but it can bound output vocabulary, freshness, resources,
speed, stop behavior, and activation authority.

### 6.4 Simulation first, evidence levels always visible

Simulation is the fastest place to find logic defects and compare algorithms. It
also provides cleaner semantics, perfect clocks, and simplified contact/dynamics.
Parcel records whether evidence is unit, desktop simulation, replay, target, bench,
or physical so a green simulator gate cannot silently become a hardware claim.

### 6.5 Defaults are part of the safety case

Experimental perception, route memory, independent completion, social progress,
research export, learned policies, and physical motion remain disabled, shadow, or
proposal-only until their declared gates pass. Configuration is validated because
the available code is wider than the admitted product.

## 7. Principal tradeoffs

| Decision | Why we chose it | Benefit | Accepted cost / limitation | Revisit when |
| --- | --- | --- | --- | --- |
| Models propose; deterministic code admits | Semantic reasoning is valuable but not physical evidence | Replaceable models, auditable actions, bounded authority | More contracts; novel requests need explicit skills | A challenger clears semantic and embodied gates without weakening the boundary |
| `grid_v1` is the selected command-producing implementation when admitted; learned navigation challenges | Current data and physical evidence are limited | Deterministic replay, CPU viability, inspectable failure reasons | The normal builder currently admits no automatic navigation; 2-D grids and A* can also deadlock or behave conservatively in crowds | MPC/MPPI or learned proposals improve frozen product scenarios under the same admission and final gate |
| Unitree Sport owns gait/balance | Initial product needs body motion, not custom torque control | Much smaller controls and safety program | Vendor opacity and less expressive gait authority | Repeated missions require dynamics Sport cannot provide and a replacement clears HIL/physical gates |
| Python semantic application plus isolated native/driver domains | Most product iteration is semantic and orchestration-heavy | Fast development and testing; mature libraries where useful | IPC, packaging, two language/runtime ecosystems | Measured deadline or fault-containment evidence requires moving a boundary |
| MuJoCo/headless as daily loop | Determinism and throughput matter early | Cheap regression, fault injection, repeatable comparisons | Reality gap; kinematic success is not braking/contact proof | Never replace it entirely; add same-contract native sim, bags, HIL, and physical tiers |
| Semantic memory separate from SLAM/free space | Names persist differently from geometry | Prevents stale/cloud labels from authorizing motion | Transform, revision, decay, and re-anchoring work | Keep separation even if one service implements both representations |
| Hosted conversation plus local safety/closed intents | Hosted models can improve interaction quickly | Better conversation without cloud motion dependency | Privacy, cost, network dependence, dual paths | A local speech model meets quality/latency, or hosted policy changes; STOP remains local |
| Separately owned final software-safety recomputation | Planner bugs and configuration drift are credible | Defense in depth and monotone restriction | It shares process/evidence/config, duplicates checks, and may stop conservatively; it is not a safety-rated physical stop | Shared inputs may improve, but final restriction remains separately owned and independent physical stopping is still required |
| Evidence-backed completion | False success is more damaging than an honest uncertainty | Truthful dialogue and safer mission handoff | More abstention and occasional missed true arrivals | Separate identity/localization/geometry evidence passes untouched replay and physical gates |
| Two-phase owner-facing arrival | Target verification and social final orientation can require opposite headings | Preserves live semantic evidence before a bounded yaw-only etiquette turn | Extra latency/state, owner tracking dependency, and more fail-closed outcomes | A commissioned multi-camera or equivalent evidence path proves target and owner continuity through terminal motion |
| Summary-first, off-robot research | Raw multimodal collection is costly and privacy-sensitive | Bounded bandwidth, deterministic replay, deletion surface | Less data for future training; provider work incomplete | A consented pilot proves encryption, deletion, utility, Orin load, and network cost |
| V2 snapshot beside a legacy carrier during migration | A flag-day conversion would destabilize many consumers | Incremental adoption and replay comparison | Dual truth can diverge; final safety is not yet universally V2/provenance-governed | Every authority-bearing consumer uses V2 and parity/refuter gates permit carrier retirement |
| 2-D SE(2) occupancy planning | Flat indoor navigation is the first bounded ODD | Simple geometry, fast deterministic search, inspectable costs | No elevation, foothold, stair, overhang, or full drop-off reasoning | A commissioned 2.5-D/3-D terrain contract clears simulation and physical gates |
| Python supervisory loop around an isolated gateway | Product logic changes quickly and benefits from Python tooling | Fast iteration, tests, and clear semantic contracts | Python/GIL/jitter is not hard real time; isolation does not prove deadlines | Measured target jitter or fault containment moves a bounded loop native without changing authority contracts |

## 8. Current boundary and next architectural move

The current system is strongest as a deterministic simulator and desktop integration
platform. It has substantial contracts, regression coverage, a deployable gateway,
and useful research seams. A prior completed whole-working-tree audit was **RED** at
the default-suite and Ruff hard gates; the [root README](../README.md) owns the exact
latest result and any superseding guarded close. The checkout remains non-releaseable
until that source records a repaired close. The capability ceiling is similarly
explicit:

- automatic Navigate, Follow, roam, poses, and gestures fail closed in the normal
  simulator application because its builder supplies no trusted capability
  composition; manual browser velocity and the separate pose-review gallery remain;
- physical motion, autonomous navigation, Follow, search, greeting, stairs, and
  unattended operation on a Go2 are **NO-GO**;
- conversation quality is **NO-GO** on the current fresh multi-turn evidence;
- the normal-runtime Unix gateway rung is implemented only while permanently
  disarmed and using fake Sport in tests; and
- social-progress, independent-completion, research-export, and learning work is
  shadow, isolated, default-off, or proposal-only.

The next architecture move is not more model authority. It is a same-contract Go2
simulation and evidence spine:

1. keep one deployment-bound capability truth;
2. preserve the gateway as sole writer and add the pinned native Unitree MuJoCo
   SDK2/DDS simulation boundary without creating a second command path;
3. wire typed dialogue/action receipts and mission progress into the live session,
   initially for stationary behavior;
4. build synchronized pose/scan/person/controller evidence and test localization
   discontinuities and completion on untouched replay; and
5. only then execute the stationary Stage-0 and tethered physical commissioning
   ladder with an independent stop.

## 9. Change rules

An extension belongs in the product path only if reviewers can answer all of these:

1. What typed input does it consume, with what frame, clock, freshness, uncertainty,
   provenance, and revision?
2. Does it provide information, propose an action, restrict an action, or own an
   actuator? Those are different authorities.
3. What happens on timeout, restart, stale evidence, malformed output, dependency
   loss, and cancellation?
4. Can it increase motion authority, or only preserve/reduce it?
5. Which default configuration selects it, and what capability/commissioning record
   proves that selection is real?
6. What deterministic replay, adversarial refuter, target result, and physical gate
   justify its maturity claim?
7. How is it disabled or rolled back without weakening STOP?

For the current readiness and exact gate verdict, start with the
[root README](../README.md). For the shortest current call path and admission ceiling,
use the [production runtime code map](PRODUCTION_RUNTIME_CODE_MAP.md). The
[executive summary](ROBOT_ENGINEERING_EXECUTIVE_SUMMARY.md) provides the broader
decision and hardware judgment, while the dated
[2026-08-26 research synthesis](../research/20260826/FINAL_REPORT.md) preserves its
evidence ledger. For the full robotics theory, equations, subsystem designs, and
promotion gates, use the
[engineering handbook](CONVERSATIONAL_AUTONOMY_HIGH_LEVEL_DESIGN.md).
