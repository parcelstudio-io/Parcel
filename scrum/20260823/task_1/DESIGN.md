# ARCH-1 design — boundary-first modular monolith

Status: proposed for Fable review. Names illustrate ownership; they are not an
approved public API until Fable accepts them and the owning implementation card
preregisters exact contracts.

## Design judgment

Keep Python and keep a modular monolith for cognition, conversation, mission
logic, and most navigation policy. Add process/native boundaries only where
timing, crash containment, credentials, vendor SDKs, GPU ownership, or sensor
throughput provide a concrete reason.

Do not start by splitting `runtime.py` into arbitrary files. Freeze the minimum
bridge protocol/authority contract and begin a no-credential native fake-Sport
gateway bench in parallel with the smallest characterization/observation
slices. Broader imports, config, packaging, and facade extraction follow
without delaying that bench.

Post-landing application: `CLAUDE_WAVE3_DECOMPOSITION.md` applies this method
to every new/modified declaration group in Claude's exact `c1b8405` Wave 3
delta. Its scan-age, hard-skip, and resolved-profile corrections precede file
movement. Go2, array audio, CI, config, and web remain compatibility facades;
commissioned latches, replay cursors, pure LiDAR/resampler leaves, motion
refusals, and duplex lifecycle atomicity remain preserve-first boundaries.

## Required dependency direction

```text
versioned contracts / typed configuration / clocks
                    ↓
       pure domain reducers and policies
                    ↓
       service interfaces and coordinators
                    ↓
      bounded I/O and persistence adapters
                    ↓
      application composition roots / CLI / UI

sensor adapters → high-rate NavigationSnapshotV2 ─→ behavior proposals
                         │                              ↓
                         │         10 Hz Python supervisory pre-gate
                         │                              ↓
                         └───────→ 20–50 Hz native final governor
                                                        ↓
                           sole-vendor-writer gateway → vendor controller

sensor adapters → slower WorldSnapshotV2/history → cognition/behavior only

independent physical/operator E-stop ─────────────→ dominant out-of-band veto
```

Forbidden reverse edges:

- contracts/configuration → runtime, UI, vendor SDK, model provider;
- Python supervisory/native final-admission path → conversation, model, audio,
  HTTP, UI, SQLite, map
  persistence, blocking logging, or an unbounded queue;
- domain reducer → `RobotRuntime` or application factory;
- physical adapter → simulation truth or simulator authority;
- model/provider → control client or terminal-success authority.

## Target ownership map

| Boundary | Sole owner | Inputs | Outputs |
|---|---|---|---|
| configuration | `ConfigLoader` + typed root schema | base/profile/env/CLI overlays | immutable effective config + provenance |
| sensor evidence | per-device adapters | vendor packets and host receipt clock | stamped pose/scan/image/audio samples |
| high-rate navigation input | `NavigationSnapshotAssembler` | pose/scan/controller + TF/calibration/revisions | immutable bounded `NavigationSnapshotV2` with per-source age/lineage |
| slower world/history input | `WorldSnapshotAssembler` | linked navigation revision + image/semantic/audio/task data | immutable `WorldSnapshotV2`; never a liveness prerequisite for final admission |
| tasks | `MissionCoordinator` | accepted user/tool intents and snapshots | versioned behavior requests/cancellations |
| conversation | `ConversationCoordinator` | audio/text/provider events | utterances and untrusted tool proposals |
| navigation | `NavigationCoordinator` facade | snapshot + accepted goal | bounded motion proposal + evidence/terminal candidate |
| supervisory arbitration | deterministic Python pre-gate | proposals + bounded snapshot + lifecycle | one uncredentialed bounded command candidate/disposition |
| final positive admission | native final governor | fresh candidate + high-rate evidence + signed envelope | sole final clamp/admit or exact-zero/refuse decision |
| vendor write | native gateway | authenticated governor output | sole vendor call + acknowledgement/feedback/stop witness; veto-only checks never originate/increase motion |
| independent stop | operator-owned out-of-band mechanism | human action / dedicated hardware path | dominant intervention outside Python/Orin/software credentials to the extent hardware permits |
| terminal truth | task/navigation verifier | compatible independent evidence | typed complete/refuse/hold, never provider assertion |
| telemetry | observer services | immutable events/snapshots | bounded logs/UI data; never control authority |

## Contract sketches

The implementation card must refine these into exact versioned DTOs.

### Stamped sensor evidence

Every sample carries:

- source device and evidence origin;
- device timestamp, host monotonic receipt timestamp, and mapped timestamp;
- sequence, boot/session epoch, frame ID, and calibration/transform revision;
- covariance or declared uncertainty, health, and loss/drop counters;
- immutable payload and an explicit unavailable/invalid reason.

The two linked snapshot contracts are neutral: simulation, replay, and live
adapters construct them directly. Physical Go2 code no longer implements
`SimulatorBackend` or returns `SimObservation`. Slow modalities never gate the
high-rate navigation snapshot, and cached samples do not become fresh merely
because a new snapshot was assembled.

### Behavior and motion proposals

A proposal contains producer, task/revision/epoch, monotonic creation and
expiry, bounded candidate command, evidence references, and declared intent.
It carries no writer credential and no terminal-success authority.

The 10 Hz Python supervisory pre-gate performs, in order:

1. read one coherent snapshot;
2. join pose/scan/controller/config/capability health;
3. collect already-computed bounded proposals without blocking;
4. arbitrate ownership and preemption;
5. apply collision/reactive/yield and input-health gates;
6. shape only an admitted proposal within its supervisory envelope;
7. apply Python-side stop/refusal dominance without claiming final authority;
8. send one versioned uncredentialed candidate to the native governor;
9. emit bounded observer events outside the write chain.

The 20–50 Hz native governor independently revalidates freshness/envelope and
owns the only final positive clamp/admission. The sole-vendor-writer gateway
enforces credential, epoch, TTL, watchdog, and local hard limits and may
reject/zero but never originate or increase motion. Fable must decide whether
these two logical native boundaries are co-located or split and approve the
failure/IPC semantics before product credentials exist.

### Runtime compatibility facade

`RobotRuntime` remains the public compatibility surface while callers migrate.
Its target contents are assembly delegation, lifecycle delegation, public
command methods, and snapshot aggregation. It must not become a second copy of
service state.

### Declarative tools

One `ToolDefinition` registry owns name, JSON schema, parser, authority class,
consent rule, handler protocol, and result serializer. Legacy text-agent and
realtime hosted-lane adapters both consume this registry. Tool descriptions no
longer duplicate authorization or dispatch logic.

## Extraction method used by every card

1. **Characterize:** record accepted current product-path behavior and known
   defects separately. Do not make a golden trace the only oracle.
2. **Pin facade:** public imports, method signatures, DTOs, endpoint bodies,
   event ordering, config behavior, CLI, and gate JSON are enumerated.
3. **Extract one state owner:** move pure calculations first, then state, then
   I/O. No behavior cleanup in the same card.
4. **Shadow:** where safe, run old and new pure reducers against the same frozen
   input. Compare outputs; never send both to an actuator or billed provider.
5. **Cut over:** facade delegates to the new component; one implementation is
   authoritative.
6. **Delete or disable legacy path:** no permanent double routing, second
   writer, copied threshold, or old state cache.
7. **Measure simplification:** imports/cycles, class attributes, method/line
   count, complexity, locks, and callback edges must decrease or receive a
   written exception.
8. **Rollback:** one commit/card can restore the prior facade implementation;
   physical rollback always returns disarmed and rejects prior epochs.

## Staged decomposition DAG

### Stage 0 — freeze evidence and make structure measurable

Cards: `ARCH-F0-MIN` freezes the critical traces, bridge contract, API and live
lock/callback graph needed by the parallel rail; `ARCH-IG` and `ARCH-TEST` then
continue the broader characterization/debt ratchet without blocking the bench.

- capture startup/close, one nominal tick, stale pose/scan, E-stop/release,
  preemption, follow/navigation terminal, tool call, barge-in, browser/array
  audio, camera stale, and daemon-down traces;
- label known defects so parity does not approve them;
- inventory public imports, CLI names, endpoint JSON, config keys/defaults,
  wire fixtures, event schemas, gate stages/order, and stable test IDs;
- thin package `__init__` barrels and migrate production imports to leaves;
- add forbidden dependency edges and a no-new-cycle ratchet;
- make `tests/conftest.py` a thin plugin registry and put process/resource/write
  guards in repo-owned plugins/launcher;
- pin current file/class/function/complexity debt and reject new debt.

Exit: clean-checkout baseline reproducible, every critical guard has a seeded
failure, no product behavior change.

### Parallel P0 physical rail — begin after the minimum Stage 0 freeze

This rail does not wait for global import cleanup, full typed configuration,
packaging refactor, audio/realtime/navigation, mission, or runtime extraction:

1. freeze the existing bridge command/authority protocol and fake-Sport
   harness;
2. implement the no-credential native final-governor/gateway bench on host/CI
   against fake Sport; this makes no target or robot claim;
3. land only the `ARCH-OBS-MIN` navigation snapshot and physical composition
   slices needed for honest product input;
4. complete first-class `ARCH-DEPLOY` process/artifact/systemd/credential and
   restart-disarmed evidence;
5. after B25/deployment, repeat the identical signed artifact on Orin against
   fake Sport and measure its target timing/resources;
6. owner-approved independent-stop ladder, then B16 commissioning and B30
   product-path HIL.

The rail contains multiple bounded cards and one integration gate, not one
mega-card. No robot writer credential exists before its OBS/deploy/independent-
stop preconditions pass.

### Stage 1 — contract kernel and configuration

Cards: minimal `ARCH-OBS`, then bounded `ARCH-CONFIG`/`ARCH-PKG` slices; config
waits for HW-5 and packaging waits for HW-1/HW-7. The no-credential native
gateway bench may proceed in parallel after the bridge contract freezes.

- introduce stamped evidence and linked high-rate navigation/slower-world
  snapshot contracts;
- adapt simulator and replay first, then Go2 read-only composition;
- build typed/versioned config sections and one loader/cross-section validator;
- preserve `parcel_robot.config` as a facade; do not create a `config/` package
  beside `config.py`;
- inventory every read-site key and make one canonical owner for footprint,
  speed regime, stopping envelope, and social/navigation limits;
- move MuJoCo to a sim extra and prove a clean physical wheel imports without
  MuJoCo/OSMesa; keep vendor/capture/perception runtimes explicitly separated.

Exit: exact contract/config parity, physical profile cannot assemble with
simulation/unknown origins, clean wheel proof, no motion enabled.

### Stage 2 — physical I/O seams

Stages 2–4 are dependency branches, not a global priority order. Audio/camera
and then realtime may proceed after their contracts without waiting for the
ROS/localization decision; the latter is mandatory before any custom/map-
relative navigation leaf. None may delay the parallel physical rail.

Cards: `ARCH-AUDIO`, `ARCH-CAMERA`, then physical snapshot integration. D08
capture modules may proceed one file at a time after output fixtures freeze.

- split browser and array adapters from shared audio state, capture recording,
  and WebSocket protocol;
- split camera DTO validation, query state, detection/localization, worker, and
  publisher;
- read real captured Mid-360/Go2/D455/audio traces through the new contracts;
- measure queues, age, loss, transform, teardown, and device failure behavior.

Exit: all invalid evidence becomes typed HOLD/STOP, healthy replay parity is
preserved, no device path can mint freshness or authority.

### Stage 3 — realtime conversation and tool authority

Cards: `ARCH-REALTIME-REDUCER`, `ARCH-TOOLS`, `ARCH-VOICE`.

- extract server-event/response/barge-in/reconnect/accounting reducers from
  `RealtimeLane`;
- build the single declarative tool registry;
- split legacy `VoiceAgent` routing/admission/execution and make both lanes use
  the same motion door;
- separate duplex turn state, STT input, TTS output, device resolution, and
  latency observation;
- preserve spend ledger, consent, memory, cancellation, and sink ownership.

Exit: one utterance/tool authority, byte-compatible server/provider traces,
zero duplicate/stale tool admissions, no additional hosted spend on parity
runs.

### Stage 4 — navigation leaves

Before cutting leaves, run a first-class `ARCH-ROS`/`ARCH-LOCALIZATION`
keep/replace/provider decision. Retire or adapt legacy `ros_node.py`; define
typed ROS/QoS/tf2 and Nav2 candidate authority; prefer mature localization,
costmap, controller, and recovery providers. Decompose only retained custom
machinery while preserving Parcel's semantic/social/terminal differentiators.

One leaf per card, in this order:

1. person-aware motion and target tracking;
2. detection lock-on and candidate commitment;
3. semantic resolution and scan/search;
4. route-memory adapter;
5. progress and recovery supervisor;
6. arrival verifier and terminal-evidence service;
7. top-level `NavigatorState` reducer and facade cutover;
8. grid/occupancy/local-controller and follow-controller cleanup only after
   the facade and replay oracle are stable.

Keep A*, final collision/reactive gates, and strict DTO validators cohesive
unless property/mutation evidence supports a smaller pure interface.

Exit: old/new replay parity plus independent collision, unknown-space, false
arrival, and stale-evidence oracles. No physical performance claim.

### Stage 5 — mission services and runtime lifecycle

Cards: `ARCH-MISSION`, then `ARCH-RUNTIME-ASSEMBLY`, then
`ARCH-RUNTIME-LIFECYCLE`.

- extract mission/behavior/roam/owner/skill coordinators;
- pass immutable requests/proposals instead of reaching through runtime state;
- move constructor regions into explicit builders only after their contracts
  exist;
- move ordered start/close and rollback into lifecycle plans;
- turn runtime snapshots into aggregation rather than state duplication.

Exit: `RobotRuntime` facade materially smaller, no new back-imports, lock and
callback graph simplified, startup/close/preemption behavior equivalent.

### Stage 6 — physical-rail convergence and supervisory-loop boundary

The native bench, minimal observation slice, deployment, and B16/B30 work are
owned by the parallel physical rail and are not delayed until this document
section. At convergence, cut the product path over atomically, then
`ARCH-LOOP`; finally make an `ARCH-CONTROL` decision, not an assumed refactor.

- implement/test the native sole-writer gateway against fake Sport before a
  product credential exists;
- isolate the deterministic Python supervisory pre-gate from all
  mixed-criticality work; native final admission remains independent;
- after native cutover, keep, retire, or decompose `ControlManager`; default to
  preserve if it becomes sim/reference/commissioning-only, and never retain it
  as a second vendor writer;
- never combine this structural work with new motion capability.

Exit: gateway bench, then B16 commissioning HIL, then B30 product-client HIL.
Any unsafe or timing red stops the sequence.

### Stage 7 — supporting/tooling cleanup

These may run with disjoint ownership but cannot delay P0 physical boundaries:

- split `scripts/ci_gate.py` behind its existing import/CLI facade, preserving
  stage order, JSON, exit codes, and failure-complete behavior;
- split each capture giant separately with byte-identical report/replay
  fixtures;
- split simulation world/commands/observation/loop;
- split provider implementations/transport/parsers/factory;
- modularize the UI only after Panel API and audio endpoints freeze;
- move old sprint narratives/eval results out of the source-oriented index,
  retaining manifests and durable ADR decisions.

## Proposed follow-on card size

Each implementation card should normally change one facade plus one extracted
component family and its tests. A card is too large if it:

- changes both accepted behavior and structure;
- spans more than one authority boundary;
- requires two active implementations after close;
- owns both the safety loop and conversation/model code;
- changes config defaults while moving config parsing;
- changes gate logic while moving gate modules;
- needs unrelated shared-file regions or more than one executor on a facade.

## Structural acceptance ratchets

Initial ratchets are additive, not blanket cleanup requirements:

- no new product class above 1,000 lines;
- no new function above 100 lines or approximate complexity above 20;
- no constructor above 150 lines;
- no new dependency cycle, lock, thread, unbounded queue, or source-shape test;
- no new `Any` at a critical boundary;
- new boundary modules pass strict static typing;
- an extraction must reduce its source facade's methods, mutable attributes,
  direct internal imports, or lock/callback edges;
- targets ratchet downward after each accepted card. They are not achieved by
  moving code wholesale to a differently named monolith.

## Rollback and failure containment

- Pure/service cutovers use the existing facade, so rollback restores one
  delegation point.
- Schema evolution is versioned; old supported fixtures either round-trip or
  fail with an explicit version refusal.
- No database migration is destructive in a decomposition card.
- Process protocols support bounded old/new compatibility during one cutover,
  not indefinite dual operation.
- Gateway or target rollback invalidates the command epoch, disables the
  product credential, and boots disarmed.
- If equivalence and the independent safety oracle disagree, the card is held;
  neither result is averaged away.

## Explicit non-goals

- no all-C++ rewrite;
- no ROS 2 migration disguised as file cleanup;
- no algorithm tuning, speed increase, new behavior, or changed refusal policy;
- no reduction in tests merely to improve counts;
- no deletion of historical evidence until durable manifests/ADRs exist;
- no physical-readiness claim from desktop, mocks, replay, or simulation.
