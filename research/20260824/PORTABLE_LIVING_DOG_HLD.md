# Portable Living-Dog Architecture · High-Level Design · 2026-08-24

Status: **adopted-with-amendments as the frozen Milestone 1 architecture
reference** by [`FABLE_HLD_CROSS_REVIEW.md`](FABLE_HLD_CROSS_REVIEW.md).
Existing research verdicts remain the evidence record; this document changes
the system synthesis and build order, not their measurements. The wave-2
amendments in §16 await independent Fable review.

## 0. Milestone definition

Milestone 1 is a supervised, one-room companion on a Unitree Go2 EDU-class
body that can:

- boot reproducibly on body compute, remain safe without internet or desk
  compute, and accept motion through exactly one commissioned writer;
- hold a natural, interruptible conversation with stable personality while
  enforcing a measured API budget;
- build/use a metric map and a small semantic world model, navigate to known
  points, and Follow only after owner-identity and loss behavior pass;
- remember explicit owner preferences and observed events with provenance,
  consent, correction and deletion;
- continuously perceive, maintain internal drives and refresh body intent;
- breathe/look/posture, react to salient events and sometimes initiate a
  short conversation without waiting for a command;
- degrade honestly to local STOP/HOLD and bounded local behavior when remote
  services fail; and
- move to a future custom quadruped by replacing body drivers, capability
  manifest and calibration, not conversation/navigation/memory code.

The first ODD is one private, flat, mapped indoor room, operator present with
an independent handheld E-stop, no children/pets/crowds/stairs, <=0.3 m/s,
sessions <=60 minutes, and self-initiated translation disabled. Outdoor
navigation, public-space autonomy, stairs, unrestricted exploration, custom
gait/RL and online model-weight updates are later milestones.

“Feels alive” does not mean an LLM runs every second. It means the robot's
local state continues to evolve; perception can interrupt it; its eyes/body
display attention; memory influences later behavior; actions have visible
beginnings and endings; and conversation is responsive and context-aware.

## 1. Binding architecture principles

1. **The body is safe without the brain.** Network, hosted model, desk GPU,
   main runtime, disk logging and perception may all disappear without
   preventing STOP/HOLD or allowing stale motion.
2. **Continuous local clocks; event-driven hosted calls.** Control, safety,
   state estimation, tracking, drives and body expression run locally at
   fixed rates. Hosted calls occur only for an admitted owner turn, an
   explicit structured-plan escalation or a bounded memory job.
3. **Models propose; typed local code disposes.** No language or vision model
   returns velocity, joint values or authority. Outputs carry schema,
   provenance, state revision, expiry and budget reservation and are compiled
   and validated locally.
4. **One physical writer.** Only `parcel-gateway` holds vendor credentials and
   sends body commands. All other components use a neutral gateway protocol.
5. **Every physical fact is stamped.** Time, frame, source epoch,
   calibration hash, age and uncertainty accompany every observation used to
   authorize motion.
6. **Every action owns a terminal.** Translation cannot end by merely
   stopping in a walkway. An action contract defines success, timeout,
   cancellation, cleanup/stand-aside/return and authority release.
7. **Learning is governed and reversible.** Online learning updates memory,
   maps, preferences and bounded policy statistics—not executable code or
   model weights. Promotion of a learned policy/model is offline, evaluated,
   signed and rollbackable.
8. **Capability loss is monotonic.** Missing gaze, posture, terrain or sensor
   support removes behavior; it never invents an approximation that can move
   more than requested.
9. **A modular monolith until isolation has a reason.** Split processes only
   for vendor/credential ownership, real-time safety, audio STOP, ROS/LIO
   dependencies or GPU/device fault containment. Avoid a network of tiny
   services for ordinary domain logic.
10. **Unitree is the first adapter, not the product ontology.** High-level
    packages use body-neutral contracts and REP-103-style frame semantics.

## 2. System topology

```text
  microphones     D455       Mid-360/IMU       body state       E-stop
       |            |             |                |               |
       v            v             v                v               |
 +-----------+ +-----------+ +-----------+  +-------------+        |
 | audio svc | | perception| | LIO/local |  | sensor hub  |        |
 | local STOP| | tracking  | | ization   |  | time/extr.  |        |
 +-----+-----+ +-----+-----+ +-----+-----+  +------+------+        |
       |             |             |               |               |
       +-------------+-------------+---------------+               |
                                     |                              |
                         NavigationSnapshotV2                       |
                                     |                              |
 +------------------- BODY-LOCAL COMPANION RUNTIME ----------------+|
 | World/event model -> active perception -> drives/action auction ||
 | conversation/persona -> governed memory -> behavior executive   ||
 |                               | ActionContractV1                 ||
 | task/global planner -> local trajectory/reflex safety            ||
 |                               | BodyIntentV1 / velocity proposal ||
 +-------------------------------+---------------------------------+|
                                 |                                  |
                         safety supervisor <-------------------------+
                                 |
                         MotionGatewayClient
                                 |
                  +--------------v---------------+
                  | parcel-gateway: sole writer  |
                  | auth/lease/TTL/clamp/watchdog|
                  | independent STOP + audit     |
                  +--------------+---------------+
                                 |
                    HighLevelBodyPort (neutral)
                           /                 \
              UnitreeSportPort          CustomWbcPort
                    |                        |
              Unitree gait/WBC       future gait/WBC/joints

 Optional remote proposal sources:
   hosted realtime conversation | structured task planner | rare VLM
   desk/edge inference           | offline training/evaluation
 All pass privacy, freshness, authority and spend governors.
```

### Two replaceable body boundaries

Portability requires both boundaries; H4 proves only part of the first.

1. **Actuation boundary:** `MotionGatewayClient` → versioned command/stop/
   state protocol → `HighLevelBodyPort`. Unitree Sport and a future custom
   WBC implement the port.
2. **Observation boundary:** device/localization/perception adapters →
   immutable `NavigationSnapshotV2`. Navigation, Follow, safety and the
   executive never receive `SimObservation`, truth helpers or vendor types.

## 3. Process and failure ownership

| process | owns | must not own |
|---|---|---|
| `parcel-gateway` | sole vendor SDK/DDS writer, credential check, lease/epoch, TTL, clamps, stop latch, stationary evidence, bounded audit | dialogue, navigation goals, memory, hosted calls |
| `parcel-safety` | independent STOP inputs, observation-health gate, final local motion envelope, gateway heartbeat | disk/network/model blocking work |
| `parcel-sensor-hub` | monotonic clock mapping, frames/extrinsics/calibration manifest, body/IMU/LiDAR/camera metadata | semantic decisions |
| `parcel-lio` | real LIO provider, MAP→ODOM, health/covariance/innovation/jump/relocalization evidence | mission success claims |
| `parcel-perception` | synchronized local detections/tracks/depth, owner belief, keyframe selection | motion authority |
| `parcel-audio` | one capture rail, AEC/VAD/endpointing, local STOP, speaker/engagement gate, short rejected ring buffer | direct physical tools |
| `parcel-runtime` | modular companion domain: world model, conversation, drives, behavior executive, memory and task compilation | vendor SDK/device handles |
| optional inference worker | bounded local GPU models | safety or control timing |
| optional remote connector | hosted calls, request reservations, retries, response validation | open-ended queue or direct executive mutation |

Services launch under systemd (or an equivalently supervised target
facility), with separate principals where authority differs. They use pinned
aarch64 artifacts, explicit data/log directories, bounded logs, readiness
and health contracts. Boot and every restart are disarmed. A service becoming
“ready” never rearms motion.

The vendor driver's `stop_move()` and `state()` have explicit deadlines. If
the SDK cannot guarantee them, vendor I/O runs behind process containment and
the stop mechanism has a separately testable path. No blocking vendor call
may execute while holding the gateway watchdog's core lock.

## 4. Contract set

Existing useful contracts are retained where possible; new versions are
introduced additively and adapters preserve simulator tests during migration.

### 4.1 Common evidence header

`EvidenceHeaderV1` is embedded in every sensor-derived message:

- schema version, source ID and process epoch;
- monotonic capture timestamp plus clock-map uncertainty;
- sequence number and immutable evidence/revision ID;
- coordinate frame and calibration/extrinsics hash;
- production/replay/simulation origin;
- maximum age/TTL and measured transport age;
- confidence/covariance and explicit health reasons.

Mixed epochs, unknown transforms, stale ages, simulation origin in a physical
profile, or uncommissioned hashes fail closed.

### 4.2 `NavigationSnapshotV2`

One immutable snapshot replaces `SimObservation` and authority-bearing
`extras`. It contains:

- MAP/ODOM/BASE transforms, covariance and localization health;
- base twist/contact/controller feedback and body capability state;
- local traversability/obstacle geometry with observation ages;
- dynamic tracks with velocity, covariance and identity class;
- `OwnerBeliefV1` with ambiguity/loss evidence—never just a pixel side
  channel;
- semantic place/object observations linked to evidence IDs;
- battery/thermal/link/input health and active safety reasons;
- contributing source epochs, calibration hashes and snapshot revision.

The assembler enforces time windows and reports missing/stale inputs; it does
not silently mix a fresh image with an old range or pose.

### 4.3 Motion and embodiment contracts

- `RobotCapabilityManifestV2`: body/firmware ID, supported locomotion mode,
  per-axis support/range/rate, posture/gaze/gesture allowlist, payload and
  frame/calibration hashes.
- `GatewayCommandV1`: retain epoch, lease, TTL, hash and body-frame velocity
  semantics. Extend only through versioned allowlisted channels.
- `BodyIntentV1`: retain locomotion/HOLD, gaze, posture and expression as
  independent desired channels with priority and expiry.
- `MotionGatewayClient`: acquire, heartbeat, command, stop, state and
  reconnect-disarmed behavior. It never exposes vendor client objects.
- `HighLevelBodyPort`: neutral driver interface implemented by
  `UnitreeSportPort` and later `CustomWbcVelocityPort`.

Do not put arbitrary joint arrays into the high-level gateway. A future
custom gait/RL stack owns joint-rate control in its own hard real-time WBC
process and exposes the same bounded body-level port upward.

### 4.4 Meaning and action contracts

- `WorldEventV1`: typed observation, dialogue, mission, health or memory
  event with subject, provenance, confidence, privacy class and revision.
- `WorldDigestV1`: bounded current-state view for deterministic drives and
  optional model phrasing; not a bag of raw sensors.
- `BehaviorProposalV1`: desired skill and rationale, triggering event,
  principal, preconditions, ODD/risk/cost estimate and expiry.
- `ActionContractV1`: admitted goal plus authority lease, resource claims,
  success predicate, timeout, cancellation, safe terminal/cleanup, recovery
  and maximum speed/radius.
- `PlanSketchV1`: hosted structured task proposal over an allowlisted skill
  vocabulary. A local compiler resolves references and a validator binds
  state revision, capabilities, permissions and safety constraints.
- `HostedRequestV1`: purpose/lane, privacy class, context manifest, token/cost
  reservation, deadline, state revision and idempotency key.
- `LearningCandidateV1`: proposed fact/map/preference update with source,
  consent class, corroboration, conflict, TTL and revocation lineage.

## 5. Authority and action lifecycle

Authority is a strict descending lattice:

1. physical remote/E-stop and vendor hard limits;
2. gateway stop latch, lease and TTL watchdog;
3. local safety supervisor and observation-health HOLD;
4. reactive geometry/dynamic-person avoidance;
5. active operator mission/action contract;
6. bounded deterministic drive proposal;
7. hosted/local model proposal.

Higher layers preempt lower layers in one supervisory tick. A lower layer
cannot rearm a higher-layer stop. Speech acknowledgment is not physical
acknowledgment; stop state comes from the gateway/body witness.

Every behavior follows:

```text
PROPOSED -> ADMITTED -> ACQUIRING -> EXECUTING -> TERMINATING -> COMPLETE
                  |         |            |             |
                  +---------+------------+-----------> ABORTED/HOLD
```

Admission freezes an `ActionContractV1`. Executing against a stale world
revision either triggers bounded revalidation or HOLD; it never silently
continues. Cancellation invokes the declared cleanup. Translational actions
must end at a safe terminal: return to a home/staging pose, stand aside, or
hand back to an explicit next contract. This directly addresses H3's
stationary-contact mechanism.

An **autonomy lease** makes owner intent concrete: allowed skills, room/zone,
radius, speed, time window and whether self-initiation may translate. M1's
lease permits speech/gaze/posture initiation and sets proactive translation
radius to zero.

## 6. Continuous life without a continuous LLM

### 6.1 Rate hierarchy

These are design targets to validate per body, not unmeasured Unitree claims:

| lane | target rate | work |
|---|---:|---|
| vendor gait/WBC | body-owned, typically hundreds of Hz | balance, contacts, joints |
| gateway refresh/watchdog | 20–50 Hz | leased setpoint or exact HOLD, TTL, stop witness |
| safety/local trajectory | 20–50 Hz | collision envelope, dynamic gates, final setpoint |
| body expression composer | 20–50 Hz | breathe/posture/gaze with capability degradation |
| localization/tracking | 10–30 Hz | LIO, geometry, people/owner state |
| snapshot/behavior executive | 10–20 Hz | synchronized state, action lifecycle, preemption |
| active perception/drive update | 1–10 Hz | information need, novelty, homeostasis, proposals |
| memory consolidation | event/idle batches | governed candidates, summaries, index maintenance |
| hosted model | admitted events only | dialogue, rare plan or perception escalation |

The global/task planner does **not** emit a new route every control tick. It
plans on a new goal or material map/state change. A local receding-horizon
controller continuously follows or refreshes HOLD. Breathing and looking are
separate expression intents, so “alive” motion cannot accidentally become
base translation.

### 6.2 Homeostatic drive/action auction

H2 rules out LLM judgment at the tick; H3 shows deterministic drives can
produce an attributable initiative economy. Generalize that into a local
**action auction**:

1. Drives update from committed events: social need, curiosity/information
   gap, comfort/battery, duty/pending owner goal and recovery/rest.
2. Skills bid with expected utility, information gain, social cost, energy,
   interruption cost, risk class, cooldown and required capabilities.
3. Admission applies dialogue, quiet-hour, autonomy-lease, ODD, health and
   authority gates.
4. The winning proposal becomes an action contract or is logged as refused.
5. Outcome updates bounded drive/cooldown statistics; it never edits code.

M1 allowlisted initiative skills are `LOOK_AT`, `SCAN_IN_PLACE`,
`POSTURE_SHIFT`, `REST`, `SHORT_REMARK`, `ASK_ONE_QUESTION` and local
acknowledgments. `APPROACH`, `ROAM` and self-initiated `NAVIGATE` remain
disabled until separate physical promotion.

### 6.3 Predictive active perception

Instead of asking a VLM continuously, the world model tracks what should be
visible in each place. Prediction error creates a local information event:

- known object absent where expected;
- stable new track persists across viewpoints;
- room-cell label/time combination is novel;
- owner disappears or an input becomes uncertain;
- semantic request cannot be grounded in current evidence.

The active-perception scheduler chooses the cheapest safe observation action:
wait for the next frame → redirect gaze → scan in place → move to a bounded
viewpoint under an operator mission → request rare model assistance. This
adds the spatial/track prior H6 requires and makes curiosity purposeful.

## 7. Conversation and compound instructions

### 7.1 One-capture, pre-cloud voice rail

```text
XVF PCM -> local AEC -> local STOP matcher -----------------> stop-only client
                 |
                 +-> VAD/endpoint -> speaker + engagement + privacy gate
                                      | reject: erase ring; no hosted bytes
                                      v admit
                                hosted audio OR local ASR->hosted text
                                      |
                         response/proposed tool -> local doors
```

Local STOP is always available and bypasses dialogue, identity, cloud and the
main runtime. A short in-memory pre-roll preserves the first word; rejected
audio expires immediately. Robot TTS feeds AEC/self-speech suppression and
cannot become a motion instruction. Barge-in cuts speaker output locally.

VOICE-GATE decides ambient versus push-to-talk. Until mounted through-air
evidence passes, push-to-talk is the honest M1 default. Speaker identity is a
social/privacy signal, not the only motion authenticator; physical action
still needs the principal/authority rules.

### 7.2 Dialogue path

The hosted realtime model owns conversational language quality, interruption
and optional function proposals. The local context builder sends only a
bounded approved view: persona, current dialogue, action/health summary and
consented retrieved memories. It excludes raw maps, unapproved facts and
unbounded transcript history.

System-initiated conversation starts from a deterministic admitted event.
The dog may use a local canned/compact TTS phrase or ask the hosted model to
phrase it within the initiative lane's budget. The model does not choose the
timing or grant motion.

### 7.3 Compound task path

Conversation and physical planning are separate calls. When an owner turn is
ambiguous or compound:

1. local engagement/identity admits the turn;
2. a provider-neutral structured planner returns `PlanSketchV1` over an
   allowlisted skill vocabulary;
3. local reference resolution grounds owner/place/object against the current
   snapshot/world revision;
4. compiler adds explicit preconditions, terminals and rollback;
5. validator checks authority, ODD, capability, freshness and autonomy lease;
6. executive either admits one action contract at a time or gives a typed
   clarification/refusal.

Timeout, malformed, duplicate, late or old-revision replies cause no partial
execution. The realtime model's current official card supports function
calling but not structured outputs, so a separate structured-output planner
adapter may be used rather than forcing task IR through the audio lane. The
adapter is replaceable and optional; simple known commands remain local.

## 8. Perception, SLAM and navigation

### 8.1 Layered perception

“Generalized perception” is implemented as a cascade:

| tier | location/rate | purpose | failure behavior |
|---|---|---|---|
| reflex geometry | body-local, 10–30 Hz | obstacles, clearance, drop/terrain evidence | HOLD/slow; never cloud |
| tracked semantics | body-local, 5–15 Hz | people, owner belief, persistent common objects | ambiguity/loss surfaced |
| open-vocab/keyframe | local/desk, event-gated | label a stable unknown or requested entity | abstain with evidence |
| rare hosted VLM | explicit event/privacy gate | difficult scene explanation, not navigation clearance | no call or typed unknown |

All detections bind pixels, depth/range, pose, frame ID and age. Map writes
require geometry and localization health. A label alone never authorizes
arrival, avoidance or approach.

### 8.2 World model

Use related but separate stores:

- **metric map:** occupancy/traversability and dynamic exclusion, owned by
  localization/navigation;
- **semantic-spatial graph:** places, objects, sightings, evidence and
  expected visibility;
- **social graph:** owner and known-person preferences/relations with consent;
- **episodic event log:** append-only dialogue, action, observation and health
  events;
- **working state:** bounded current snapshot/digest, never treated as durable
  fact automatically.

The semantic graph references metric frames/revisions; it does not duplicate
the safety map. Contradiction and expiry are explicit states. Answers say
“last seen,” confidence and time rather than presenting memory as present
truth.

### 8.3 Localization and map health

The physical provider consumes Mid-360 point clouds, IMU and body odometry in
its native process and publishes the useful half of H7's contract. Health is
not covariance alone. Independent monitors include source epochs, timestamp
quality, innovation, scan match ambiguity, transform discontinuity,
pickup/contact signatures and global relocalization margin.

DEGRADED/LOST or discontinuity commands HOLD. Rearm requires independently
discriminative relocalization or an operator pose-reset-and-validate
transaction. Mission code cannot declare arrival from a stale/uncertain pose.

### 8.4 Navigation stack

- task layer: semantic goal/reference and action contract;
- global layer: route through current metric/traversability map;
- local layer: receding-horizon trajectory/velocity under dynamic clearance;
- reflex layer: latest geometry/person/stop envelope can override;
- recovery layer: bounded stop, rotate/scan, replan, return/stand-aside or
  typed refusal; no unbounded wandering.

M1 proves a known metric point before semantic place navigation, then owner
tracking, then Follow. Bounded “look before refusing” may follow; full
frontier exploration does not block M1.

Outdoor autonomy is M2 because it adds GNSS/map alignment, terrain
classification, slope/traction, weather/water, geofence, road/vehicle risk,
sun/lighting, cellular dead zones, thermal/power and public-space policy.

## 9. Governed continuous learning

### 9.1 What changes online

Allowed online:

- append an episode or sighting with provenance;
- update spatial occupancy/semantic evidence under localization health;
- propose/confirm/correct/revoke an owner fact or preference;
- update bounded drive cooldowns, nuisance feedback and skill outcome
  statistics;
- create training/evaluation examples for later offline work.

Not allowed online in M1:

- modify Python/configuration/permissions;
- rewrite a policy or safety threshold from model prose;
- fine-tune/deploy model weights;
- grant itself a new skill, wider radius or authority;
- convert bystander/sensitive statements into owner facts automatically.

### 9.2 Candidate lifecycle

```text
observed -> candidate -> corroborated/owner-confirmed -> committed
    |             |                  |                    |
    +-> expired   +-> rejected       +-> conflicted       +-> corrected/revoked
```

Each committed item retains all source and consent lineage. Revocation writes
a durable tombstone checked by every proposer, retrieval path, summary and
export; new evidence cannot silently resurrect it. Forget cascades through
summaries, indexes, prompt caches and exports, not just one database row.

Memory jobs run off the control path through bounded queues. A model may
propose a candidate or summary but never commit it. For the first milestone,
explicit remember/forget and deterministic candidate extraction are the
default; automatic model proposals remain shadowed until H5's product-path
refuters pass.

### 9.3 Safe adaptation path

To exploit continuous experience later without losing control:

1. log input features, deterministic decision, refused alternatives and
   outcome;
2. train a candidate attention/initiative policy offline;
3. run it in **shadow mode** beside the deterministic policy and measure
   disagreement, nuisance, risk and demographic/site bias;
4. promote only inside a signed version with a narrow capability manifest;
5. canary under a smaller autonomy lease and retain instant rollback.

This creates recursive improvement of the product process, not uncontrolled
self-modification on the robot.

## 10. Cost, privacy and remote-compute policy

EVENT-BUDGET confirms the architecture under the frozen workload:

| scenario | monthly p95 |
|---|---:|
| nominal (174 owner turns/day) | $30.72 |
| heavy social (500/day) | $76.95 |
| hosted proactive stress | $32.13 |
| ungated TV | $572.36 |
| 1 Hz hosted text tick | $777.60 deterministic |

Use a **$160 application envelope plus $40 uncertainty/billing reserve**
inside the owner's $200 ceiling. Initial lane budgets are $110 owner
conversation, $20 initiative phrasing, $20 planner/tools and $10 memory/
background. Unused non-conversation capacity may roll to owner conversation;
no lane borrows from the reserve automatically.

`HostedCallGovernor` is the one entry point for every remote provider. It:

- loads a dated, model-matched official rate card;
- reserves worst-reasonable cost before request start;
- enforces per-lane daily pacing and a bounded burst bank;
- reconciles provider usage on completion and records missing/incomplete
  usage as uncertainty, not zero;
- deduplicates retries by idempotency key;
- projects p50/p95 month-end cost and degrades a lane before exhaustion;
- refuses new nonessential calls if ledger/rate/billing state is unknown;
- reconciles separately with provider organization billing/usage records.

Safety never consumes a hosted budget. Degradation is local gesture/silence
for initiative, typed clarification/refusal for planning, deferred memory
jobs and an honest local/offline line for conversation.

The rate card must be updated operationally; the model used by this review is
the current official
[GPT-Realtime-2.1 mini card](https://developers.openai.com/api/docs/models/gpt-realtime-2.1-mini).
Raw audio/camera remain local by default. Uploads contain only admitted audio
or the minimum structured/text context. Rejected buffers are erased; raw
capture retention is opt-in and TTL-bound; voice embeddings are local,
encrypted and deletable; private mode disables upload and retention.

## 11. Language and framework allocation

Python remains appropriate for the companion domain: dialogue, world model,
behavior executive, experiment harnesses, provider adapters, memory and most
supervisory logic. It maximizes iteration speed and fits the existing code.

Python is not the hard real-time gait layer. Allocation:

- vendor Unitree Sport controller: vendor implementation;
- future custom gait/WBC/joint loop: C++/CUDA (or an equivalently bounded
  real-time implementation), exposing `CustomWbcVelocityPort` upward;
- LIO and high-throughput perception: native/ROS2 components where the chosen
  stack already uses them, behind typed IPC;
- gateway reference may begin in Python for bench semantics, but physical
  deployment must demonstrate deadlines and fault containment; move the
  narrow driver/watchdog core native if Python/SDK behavior cannot meet them;
- Python companion runtime never enters direct joint control.

ROS2 may own sensor/LIO/WBC transport below adapters. It is not the domain
model: high-level business logic consumes Parcel contracts so a future body
or middleware switch does not rewrite cognition.

## 12. Dependency-correct implementation sequence

### Gate 0 — freeze “mountable” and the two boundaries

- freeze gateway V1 semantics, `NavigationSnapshotV2`, evidence header,
  body/deployment manifest and physical-profile no-truth rule;
- define service principals, boot/restart-disarmed behavior and target
  artifact/rollback;
- keep simulator adapters to preserve current tests.

### Gate 1 — adversarial gateway bench

- finish the fake-body gateway and production Unix client;
- add hung `stop_move`/`state`, stale feedback, duplicate/old epoch, lease
  theft, second writer, slow client, process kill and audit-full refuters;
- prove the watchdog/control loop cannot block on vendor or logging I/O.

### Gate 2 — observation and deployment spine

- build simulator/replay/physical `ObservationSource` adapters and snapshot
  assembler;
- package gateway, safety, sensor, LIO, audio, perception and runtime
  services for pinned Orin aarch64;
- reject truth pose, unknown calibration and mixed simulation origin in the
  physical profile; test every service restart.

### Gate 3 — local STOP and observe-only box day

- land stop-only credential/endpoint and always-local spoken STOP;
- capture time maps, extrinsics, body state, LiDAR, camera and audio without
  motion; run through-air and dropout campaigns;
- choose push-to-talk unless ambient bars pass.

### Gate 4 — real driver and controlled pulse

- implement `UnitreeSportPort` and runtime gateway client;
- commission one primitive/axis at a time on stand/tether;
- measure signs, units, rate, clamp, stopping envelope, exact HOLD,
  independent remote stop and restart behavior.

### Gate 5 — localization and supervised point goal

- integrate real LIO into snapshots and run bag refuters;
- prove health-loss HOLD and independent rearm;
- execute repeated leashed/supervised `NavigateTo(metric_point)` before
  semantic goals.

### Gate 6 — owner tracking and Follow

- install the tracker in the product, synchronize frame/range/pose evidence,
  decide UWB from measured ambiguity, and add bystander/dynamic clearance;
- prove ambiguity/loss→HOLD, reacquisition transaction and local STOP in
  one- and two-person trials.

### Gate 7 — conversation and task composition

- wire the pre-cloud activation gate, async hosted lane and hard call
  governor;
- prove barge-in, self-speech immunity and control isolation;
- add structured PlanSketch only if compound physical tasks are in M1.

### Gate 8 — governed memory and non-travel life

- fix H5's four defects and run consent/revoke/restart through the product;
- wire body composer, spatial noticing and deterministic action auction;
- enable posture/gaze/speech initiative under the zero-translation lease;
- run long soaks and human “alive/purposeful/not annoying” evaluation.

Transactional goal-amend correctness can proceed in parallel, but Follow,
memory or personality work does not move an earlier physical gate.

## 13. Verification plan

### Unit/contract tests

- schema round-trip/fuzz: NaN, ranges, malformed enum, unknown version;
- clock/epoch/TTL/calibration and mixed-origin rejection;
- capability degradation never invents a channel or expands a bound;
- action lifecycle, authority preemption, terminal/cleanup and autonomy lease;
- budget reservation/reconciliation, retry idempotency and fail-closed ledger;
- memory consent/conflict/tombstone/forget cascade;
- plan compiler/validator negation, expiry, duplicate and stale revision;
- deterministic drives, cooldowns, quiet hours and translation prohibition.

### Service/integration tests

- gateway conformance against fake Sport, real Unitree adapter and fake
  custom WBC;
- snapshot delay/drop/reorder/restart/transform-jump and sensor disagreement;
- every process killed/restarted; credential and second-writer violations;
- audio owner/housemate/TV/self-TTS/replay/network-loss corpus with hosted
  byte counters;
- hosted socket/ledger/model stalls while measuring control tick gaps;
- recorded Mid-360/D455/body/audio data through snapshot, navigation and
  event/memory paths;
- disk full, log rotation, network flap, thermal signal and queue storm.

### Quality/evaluation tests

- conversation: interruption, latency, relevance, persona stability,
  hallucinated embodiment claims and action narration correctness;
- plan quality: compound corpus plus independently authored adversarial set;
- perception: owner/bystander, open-vocab abstention, spatial novelty and map
  write correctness;
- memory: independent gold, consent matrix, correction/revocation, bounded
  prompt context and no sensitive/unverified grants;
- initiative: attributable actions, quiet/dialogue constraints, nuisance and
  zero self-initiated base motion;
- lifelike rating: blinded raters score alive, purposeful, natural and
  annoying; behaviors are also counted to detect scripted repetition.

Fable reviews preregistration before results and verifies headline rows from
canonical artifacts. A result without an independent verdict remains a
claim.

### Physical promotion tests

1. observe-only reboot/clock/extrinsics/service soak;
2. local STOP with cloud, runtime and desk each unavailable;
3. stand/tether pulse and stopping envelope;
4. localization loss/kidnap/discontinuity HOLD and rearm;
5. at least ten supervised known-point missions with no false arrival/contact;
6. two-person Follow ambiguity/loss trials;
7. mounted AEC/VAD/STOP/identity under fans, gait, TTS, wind and TV;
8. 4–8 h Orin thermal/co-residency plus disk/network/power faults;
9. ten 60-minute supervised companion sessions before M1 close.

## 14. M1 acceptance contract

M1 is complete only when all are true:

- one clean, documented Orin install boots supervised services disarmed and
  can roll back;
- exactly one vendor writer exists; stale, killed, disconnected or restarted
  command sources produce HOLD/stop;
- local physical and spoken STOP remain available with WAN/desk/runtime down;
- all motion uses measured calibration/manifest and synchronized physical
  observations—no truth fallback;
- real LIO loss/uncertainty prevents motion, rearm and false arrival;
- supervised known-point navigation passes; Follow passes its separate
  identity/ambiguity gate if included in the release;
- conversation is interruptible and no self-TTS/non-owner input becomes a
  physical instruction or unauthorized hosted exchange;
- explicit remember/correct/forget survives restart with provenance and no
  tombstone resurrection;
- continuous body intent meets its deadline while hosted/network/disk faults
  are injected;
- non-travel initiative obeys quiet/dialogue/cooldown rules, remains
  attributable, and meets the human nuisance bar;
- observed and projected hosted spend remain within the $160 application
  envelope and $200 owner ceiling;
- replacing the Unitree driver with the fake custom-WBC adapter passes the
  same gateway/snapshot/domain contract suite without edits above adapters.

Anything less may still be a valuable demo, but it is not the portable
living-dog milestone described here.

## 15. Explicit open decisions

- Ambient voice versus push-to-talk: VOICE-GATE + mounted acoustic packet.
- Unitree payload/JetPack/power/interfaces/warranty: written vendor response
  and receiving inspection.
- UWB for Follow: measured two-person/reacquisition ambiguity, not preference.
- Orin NX versus larger compute: target co-residency/thermal evidence; remove
  optional local 8B before changing bodies solely for model capacity.
- Structured planner in M1: only if compound physical commands are a binding
  first-milestone behavior.
- Full semantic exploration/OCR: after real known-place navigation.
- Self-initiated translation and outdoor ODD: post-M1 safety programs.

## 16. Prototype research wave-2 amendments · 2026-08-24

The evidence and full rationale are in
[`PROTOTYPE_RESEARCH_WAVE_2.md`](PROTOTYPE_RESEARCH_WAVE_2.md). These amendments
do not reorder Gates 0–8 or claim physical readiness.

1. **Fail-closed social admission.** `ConversationOpportunityGate` consumes a
   versioned typed candidate. Unknown/missing/wrong-type/non-finite/stale or
   mixed-epoch state returns `DROP_INVALID` before scoring. A raw dictionary
   with permissive defaults is prohibited. `OwnerBeliefV1` includes confidence,
   ambiguity, consent and source epoch; presence alone never proves owner.
2. **Structured world deltas.** Replace one novelty scalar with separate
   identity novelty, place novelty, change surprise and social opportunity,
   each linked to synchronized evidence. An uncertain delta first proposes
   `GAZE_VERIFY`; it cannot directly create translation, durable memory, speech
   or a hosted call.
3. **Explicit preferences, shadow adaptation.** M1 enacts only explicit
   per-owner likes/dislikes/quiet settings and deterministic cooldowns. An
   implicit preference learner remains shadow-only until a held-out
   longitudinal human study passes. It can never grant a skill, travel,
   authority or a safety-bound change.
4. **Safe-hold invariant for any future proactive travel.** Return-home plus
   stop-only TTC is refuted. Admission must prove a reachable safe-hold region,
   outbound success predicate and reserved return/yield budget. Execution must
   plan over static and predicted dynamic occupancy and terminate explicitly
   in `HOLD`, `RETURN`, `YIELD_ASIDE`, `FOLLOW_OWNER` or
   `RELEASE_AUTHORITY`. Until noisy-track and physical promotion tests pass,
   M1's self-initiated translation radius remains zero.

Independent Fable review is required before these amendments become
implementation acceptance rows.
