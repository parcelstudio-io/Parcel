# Parcel companion robot — engineering executive summary

**Ten-page current-code brief: architecture, quality, physical readiness,
tradeoffs, procurement, risks, and next gates**

| Document control | Value |
| --- | --- |
| Status | Executive summary of the canonical engineering handbook |
| Audit date | 2026-08-22 |
| Committed baseline | `904edd24fc910bce5f160de3d2f242a03d447cd7` (`main`) |
| Worktree scope | Baseline plus the visible experimental P1-A–P1-E and P2-A/P2-B feature wave; worktree code is not released or commissioned |
| Audience | Engineering/product executives, technical program leads, robotics leads, safety reviewers, and procurement owners |
| Canonical detail | [Parcel companion robot engineering handbook](CONVERSATIONAL_AUTONOMY_HIGH_LEVEL_DESIGN.md) |

This brief is the decision-oriented version of the full handbook. It is designed
to be read in one sitting and to answer five questions:

1. What robot has actually been built in code?
2. How good is the current engineering and evidence?
3. What prevents this from becoming a semiautonomous Unitree companion dog?
4. When is hardware procurement justified?
5. What sequence converts the research stack into a bounded physical product?

The answer in one sentence is:

> Parcel is a credible, safety-conscious simulator autonomy stack with strong
> semantic/task boundaries and meaningful experimental perception and memory work;
> it is not a physical companion product because release integrity, physical
> observation, localization/SLAM, owner identity, native command isolation, and
> hardware commissioning are not closed.

## 1. Executive decision

### 1.1 Product judgment

Parcel should be funded and managed as a **simulation-first supervisory-autonomy
platform entering physical integration**, not as a field-ready companion robot.
The integrated product is approximately **L2** on the maturity ladder used here:

| Level | Meaning |
| --- | --- |
| L0 | Absent or research proposal only |
| L1 | Implemented in isolation or unit-test-only |
| L2 | Composed through a normal simulator/development path |
| L3 | Repeated deterministic simulation/replay evidence for the stated scope |
| L4 | Supervised bench/tethered evidence on intended hardware |
| L5 | Repeated integrated evidence in a declared operating design domain (ODD) |

Several deterministic subsystems reach L3 in simulation. The integrated physical
robot remains L0–L1 because no normal runtime consumes a synchronized physical
observation and no autonomy path has commissioned Go2 motion, localization,
perception, stopping, identity, or through-air voice.

The strongest product assets are worth preserving:

- language/model proposals do not directly control velocity or joints;
- task plans are compiled and admitted by deterministic code;
- task revisions reject late work after corrections;
- semantic arrival can require evidence beyond controller termination;
- motion passes priority, TTL, input-health, collision/person/TTC, shaping, final
  stop, controller-watchdog, and stationary-witness layers;
- learned components are generally staged as proposal, shadow, or subtractive
  veto sources rather than motor authorities;
- tests include negative cases, frozen evidence, mutation/seeded-defect panels,
  provenance boundaries, and explicit `does_not_prove` statements.

The immediate problem is not a shortage of AI models. It is that the release and
physical evidence chain is incomplete. More semantic features should not be used to
defer the following foundations:

1. a clean checkout that can execute and completely report its gates;
2. a true supported-Python/import/capability contract;
3. a backend-neutral synchronized physical observation;
4. a real `map → odom → base_link` localization/SLAM spine;
5. a native sole-writer Unitree gateway and independent stop;
6. calibrated physical perception/owner identity and repeated first-ODD evidence.

### 1.2 Procurement judgment

The code does **not** justify purchasing hardware on the assumption that it can be
mounted and run as a semiautonomous companion dog. It can justify a Go2 EDU as a
supervised R&D and commissioning instrument once the release-integrity and lab
readiness gates are closed.

| Question | Decision |
| --- | --- |
| Buy for autonomous companion deployment? | **No.** Physical autonomy prerequisites are absent or uncommissioned. |
| Buy as an engineering platform today? | **Conditional hold.** Quotes, lead-time and BOM research may proceed; release the PO after integrity, acceptance and lab-safety gates. |
| What must the PO say? | Supervised R&D/data-collection/commissioning platform, not an autonomous product. |
| What should happen before delivery? | Prepare independent stop/tether, controlled area, named operator/reviewer, dedicated network, sensor/compute mounts, capture station and vendor acceptance checklist. |
| What should happen in the return window? | Inventory, read-only telemetry, firmware/SDK compatibility, battery/sensor checks, axes/frame verification and only then approved minimum-speed motion. |

Procurement should be driven by whether the team can learn from the body every week,
not by whether the simulator is feature-rich. A robot that sits unused while CI,
sensor selection and lab safety are unresolved creates cost without reducing the
critical uncertainty.

## 2. Product objective and first operating domain

The north-star product is a conversational quadruped companion that can follow its
owner, navigate to semantically described places, accept corrections, recover from
ordinary ambiguity or blockage, interact naturally, and report completion only when
fresh evidence verifies the requested outcome.

A representative target mission is:

> “Walk with me, and after the red bench wait near the entrance.” The robot should
> discuss an unrelated topic while moving, clarify which entrance is meant, avoid
> crowding people, accept “use the other entrance,” reacquire the correct owner
> after occlusion, and say it arrived only after pose, target, relation and settled
> motion evidence agree.

That mission combines six systems that are often evaluated separately:

- conversation and turn commitment;
- task interpretation, authorization, revision and recovery;
- semantic perception and memory;
- localization, mapping and navigation;
- owner identity, prediction and social behavior;
- physical control, stopping and terminal truth.

The recommended first ODD is intentionally narrow: supervised private indoor routes,
flat/dry surfaces, adequate lighting, low walking speed, a mapped/calibrated area,
trained operator, independent stop and controlled participants. Road crossing,
stairs, elevators, public crowds, adverse weather and unsupervised operation remain
out of scope until separately evidenced.

ODD restriction is an engineering tool, not a marketing limitation. It bounds sensor
conditions, stopping requirements, maps, people density, recovery policy and the
evidence needed for release. “Works indoors under supervision” cannot be extrapolated
to “works outside around the public.”

## 3. Current architecture as built

### 3.1 End-to-end authority path

The current design is a hybrid deterministic autonomy stack:

```text
text / microphone / hosted Realtime
              |
   committed transcript + principal
              |
 deterministic intent router ---------> immediate STOP/cancel
              |
 local PlanSketch or model PlanIR proposal
              |
 compiler + fresh-snapshot validator
              |
 TaskExecutive + resources + task revision
              |
 navigation / follow / spatial / activity controller
              |
 priority + TTL command arbiter
              |
 input health + obstacle/person/TTC safety
              |
 smoothing/shaping + post-shaper exact-stop reassertion
              |
 ControlManager / simulator command sink
```

The model supplies semantic value: interpreting open-ended language, proposing
bounded tasks, responding conversationally and eventually suggesting recovery.
It does not own raw velocity, joints, safety priority, actuator leases or successful
completion. This boundary should not be weakened as models improve.

The code still has more than one consequential-action lifecycle. Navigation,
following and typed tasks normally use the brain/executive path, while some legacy
walk, catalog skill, pose/trajectory and fallback paths bypass portions of it. They
still encounter downstream safety in the simulator runtime, but task resources,
pause/resume, progress and verification are not uniform. The target is one semantic
task gateway for every non-emergency physical effect, plus a separate dominant STOP.

### 3.2 Normal composition remains simulation-first

The normal UI/runtime builder constructs a `MujocoSocketBackend`; the stack launcher
ultimately starts the simulator. The runtime's central observation is still
`SimObservation`, carrying truth pose, ray-cast scan, simulator owner/dynamic tracks
and semantic sidecars.

Canonical configuration reinforces this:

- controller: simulator;
- Unitree command axes: uncommissioned;
- Unitree state frame: uncommissioned;
- allowed physical modes: empty;
- navigation model: deterministic `grid_v1`;
- semantic source: simulator `oracle`;
- route memory: disabled;
- `rl`-named motion backend: empty policy path, therefore no actuating learned
  locomotion policy.

This is good fail-closed configuration. It also means changing a launcher option or
adding a vendor class does not create a physical product.

### 3.3 Navigation and mapping

The default local navigator is a strong deterministic baseline:

- rolling 161×161 occupancy grid at 0.1 m resolution, approximately 16.1 m across;
- log-odds ray updates with free, occupied and unknown state;
- footprint inflation and comfort costs;
- eight-connected A*;
- path compression/lookahead and forward-preferred tracking;
- dynamic-agent soft costs plus downstream reactive/TTC safety.

Its limits are important. The grid is robot-centered and local; it is not a
persistent building map. Unknown space is traversable with a penalty. A missing or
grid-invalid scan can fall back to a less-informed point-goal controller, while the
downstream reactive layer uses a different scan-validity contract. A physical
profile should return typed HOLD when required geometry is absent rather than rely
on a weaker fallback being stopped later.

Parcel has four different map-like products:

| Representation | Current use | What it is not |
| --- | --- | --- |
| Rolling occupancy grid | Immediate collision-aware local planning | Persistent global map or localization |
| Simulator semantic/oracle rows | Repeatable development grounding | Physical perception |
| `OnlineMap` | Experimental object/place evidence, visits, names, embeddings and decay | Free-space map or SLAM |
| Route/place memory | Optional topological waypoint proposals | Metric pose, current traversability or relocalization by itself |

The worktree corrects an old integration gap: for an effectively selected
`learned_map` or `shadow` profile, runtime start can install an instance-bound map,
feed camera observations and persist it on close. Recorded simulator patrol evidence
grew 69 entries/seven labels and then 85/eight after reload. Default navigation still
uses the oracle, the robot prototype overlay does not itself select the learned
navigation profile, and no physical camera feeds the runtime. The online map is
useful semantic memory, not SLAM.

### 3.4 Localization and SLAM

The repository explicitly provides a localization **seam**, not a localizer. It has
typed MAP/ODOM frames, pose covariance/health validation, simulator truth and a
synthetic drifting-odometry provider. The normal runtime hardcodes truth pose in MAP
and ODOM with zero covariance.

It does not have:

- a robot-state EKF/UKF or factor-graph estimator;
- leg/contact odometry or IMU bias fusion;
- visual or LiDAR odometry/scan matching;
- a transform buffer or production `T_map_odom`;
- loop closure, pose-graph optimization or persistent metric SLAM;
- relocalization and localization-integrity monitoring;
- a map lifecycle tied to calibration, sensor and software revisions.

This is the largest functional gap between simulator navigation and physical
semiautonomy. In a physical system, ODOM must remain smooth for control while MAP
may correct after relocalization/loop closure. A MAP goal cannot be passed directly
to an ODOM controller without a timestamped transform. Simulator truth makes the
frames identical and hides the error.

The recommended strategy is to compare established providers on identical physical
bags rather than begin with custom SLAM. Report absolute trajectory error, relative
pose error, drift per metre, lost/false-relocalization rate, recovery time,
innovation/covariance calibration, latency and compute. Parcel should own the pose/
health contract and failure policy even if ROS 2 sidecars own estimation.

### 3.5 Control and safety

The normal velocity path is one of the codebase's strongest areas. It includes:

- priority arbitration and short command TTL;
- kinematic limits and finite-value checks;
- input freshness/frame/origin validation;
- directional obstacle/person and TTC constraints;
- acceleration/jerk shaping;
- post-shaper hard/proximity stop reassertion and state reset;
- single-writer `ControlManager` lifecycle, state watchdog and stationary witness;
- deterministic spoken STOP path.

However, it is still software supervision, not a physical safety case. There is no
native sole-writer gateway isolated from Python, no independent hardware stop
campaign, no commissioned physical braking envelope and no repeated fault campaign
on the intended body. Unitree `StopMove` is useful but is not an independent power
cut.

The prototype's P1-E work exposes a 0.70 m stranger band above a software-derived
0.68 m floor and a 1.25 m owner keepout. Those figures are simulator policy, not
physical stopping evidence. Planner inflation, final gate geometry, pose error,
sensor age, Sport response, surface friction, payload and operator margin must be
derived from measurements. The P1-E status also correctly withdraws the stronger
claim that planner and final gate already agree on one complete envelope.

### 3.6 Voice, cognition and memory

Parcel has local and hosted interaction lanes. The intended hosted Realtime lane
supports streaming session/tool behavior; the local cascade retains endpointing,
ASR, Gemma/llama.cpp reasoning and TTS. A clean checkout has no active
`configs/realtime.yaml`, so hosted interaction is disabled until an operator creates
configuration and credentials. Only committed transcripts can authorize behavior;
partials remain evidence/preparation/interruption signals.

The worktree adds meaningful companion features:

- P2-A: consent/provenance-bearing owner facts, deterministic remember/refuse/
  forget policy, full-ledger replay and user-facing inspection;
- P2-B: speaker labels, affect history, bounded initiative/owner events and
  unenrolled narration controls.

These are not yet long-horizon companion proof. Hosted model-selected fact storage
was not run, distillation scheduling is incomplete, deletion has not been audited
across every derived artifact, speaker enrollment/authentication is absent, and
owner-presence events still derive from simulator truth. Identity labels, appearance
similarity, voice affect and memories must never become motion credentials.

## 4. Experimental P1/P2 capability snapshot

The active worktree is materially ahead of committed `904edd2`. It should be read as
engineering progress, not released capability.

| Wave | What exists | Recorded evidence | Why it remains experimental |
| --- | --- | --- | --- |
| P1-A physical camera/process | UVC, RealSense, recorded backends; Unix-socket detector/embed daemon | Synthetic/recorded detector p50 about 100.6/113.7 ms; process overhead p50 0.6/1.8 ms; corrected targeted 93 pass/1 expected failure | No camera attached; physical backends not selected by normal runtime; UVC lacks metric depth |
| P1-B learned map | Runtime install/feed/persist, thumbnails/naming/embeddings | Sim patrol 69 entries/7 labels; reload continuation 85/8; status records 500 pass/2 warnings | Default remains oracle; no physical precision/recall, duplicate/retrieval score or crash-durability proof |
| P1-C owner appearance | Enrollment gallery, embeddings, tracker and UWB fusion seam | Desktop SigLIP crop embed p50 3.44 ms; corrected GPU status 99 pass | Held-out owner recall/live two-person continuity halted; runtime owner still mocap truth |
| P1-D VLM veto/names | Subtractive veto, ASK outcome, vocabulary/name growth | 18/40 (45%) naming fixture; corrected targeted 51 pass/1 skip | Low naming accuracy, no physical calibration, no authority to admit motion |
| P1-E social zone | Configurable prototype band and derived authority floor | Large targeted simulator sweep recorded | No physical braking/comfort evidence; full planner/final-gate envelope unification not delivered |
| P2-A owner facts | Structured fact store, consent, replay, remember/forget tools | Nine deterministic probe families met | Hosted model-chosen row unrun; privacy/distillation lifecycle incomplete |
| P2-B identity/affect/initiative | Labels rather than gates, affect and bounded event plumbing | Targeted software matrices recorded | No speaker enrollment or physical owner event source; no base authority |

The correct promotion pattern is consistent across these features:

1. keep default behavior unchanged;
2. run the challenger on deterministic fixtures and nulls;
3. measure real sensor/model timing and accuracy;
4. run shadow on independent physical data;
5. freeze thresholds before final held-out evaluation;
6. promote only as a proposal source under existing deterministic admission;
7. preserve rollback and exact evidence provenance.

## 5. Current quality and integrity snapshot

### 5.1 Scale and collection

At the audit, the active tree contained 308 product Python files / 141,795 lines and
360 `test_*.py` modules / 166,629 Python test-support lines. CPython 3.14.4 collected
8,701 nodes: exactly 8,620 in the commit selection and 81 slow. Marker inventory
included 50 `skipif`, 7 `xfail`, 3 `load_sensitive` and zero `e2e` nodes.

This is a substantial engineering test surface. It is not a green release verdict.

### 5.2 Four integrity breaks

**1. The clean-checkout gate cannot run.** `third_party/` is ignored, Git tracks no
Unitree MuJoCo asset pack or submodule, and Actions fetches nothing. A tracked-only
archive fails in about 0.40 seconds when the first scene consumer opens the missing
Go2 XML. The exception escapes before JSON, later independent stages or pytest.
Local ignored assets are workstation state, not reproducibility.

**2. The Python support claim is false.** Packaging declares Python `>=3.10`; CI
tests only 3.12. Python 3.11 rejects `RetainedEvent.fields` because it uses a direct
`MappingProxyType({})` dataclass default. The fresh 3.11 audit collected 6,067 nodes
with 69 errors, leaving 2,634 current nodes absent versus 3.14. The voice dependency
`websockets>=17` also conflicts with Python 3.10.

**3. Eager package barrels collapse module boundaries.** Importing a core/navigation
leaf can load 118 Parcel modules, including the large navigation pipeline, simulator
environments and InstructNav. A seven-hop cycle previously allowed
`_HAS_INSTRUCTNAV=False`, turning required semantic navigation into a no-op while
other tests remained green. The highest-leverage structural fix is thin package
initializers, leaf imports and startup-fatal capability admission—before splitting
the god objects.

**4. The gate is not failure-complete.** One evaluator exception suppresses later
results. Every stage must convert exceptions into bounded named `ERROR` results,
continue independent checks, emit valid text/JSON and preserve nonzero exit.

### 5.3 Current execution evidence

No complete current green suite can be claimed:

- direct current Ruff evaluation: 16 fingerprints, seven grandfathered plus nine
  new rows in untracked evidence scripts;
- `tests/test_ci_gate.py`: 45 pass/one warning, but it does not seed missing assets
  or aggregate-stage exception containment;
- partial serial default run stopped honestly around 17%/402 seconds: 1,542 pass,
  three environment-coupled RealSense expectation failures, 81 deselected;
- hosted Actions/branch protection: unverified;
- last recorded nightly: red.

There are useful narrow positives on the developer tree: 91 internal assets are
byte-parity checked; frozen navigation and several safety/latency/freshness panels
reproduce their expected results; assertion fixtures reproduce 20 pinned findings.
They demonstrate good test ideas. They do not repair the clean aggregate or qualify
physical hardware.

The executive quality statement is therefore:

> Strong local regression engineering around a research simulator, currently
> blocked by release-integrity defects and without physical assurance.

## 6. Physical Unitree readiness

### 6.1 What exists

Parcel has a useful high-level Unitree foundation:

- lazy Unitree Sport controller factory;
- high-level body-velocity mapping to `Move`/`StopMove`;
- controller state source and mode handling;
- leases, command/state freshness, limits, faults, tilt response, stop retries and
  stationary confirmation in `ControlManager`;
- explicit axes/frame/mode commissioning records and CLI concepts;
- evidence-origin controls intended to distinguish physical from synthetic state.

Using Unitree Sport for the first ODD is the correct tradeoff. The vendor controller
owns high-rate balance, contact and gait, while Parcel supplies bounded body-velocity
requests. Moving to low-level joints or learned torque control would multiply the
safety and controls program without being necessary for initial companion behavior.

### 6.2 What is missing

The normal runtime does not instantiate the Unitree manager and a physical sensor
spine together. It lacks:

- synchronized camera/LiDAR/IMU/joint/controller evidence;
- hardware clock mapping and commissioned extrinsics;
- physical odometry/localization/SLAM and transform health;
- a backend-neutral physical observation accepted by navigation/safety;
- a calibrated owner/stranger belief;
- a native restart-disarmed sole-writer gateway;
- an external independent stop integrated into the test plan;
- measured velocity response, stop distance, slope/surface/payload/battery behavior;
- a capability-admitting deploy supervisor and repeated physical scenarios.

Starting a detector daemon or selecting a camera environment variable does not close
this gap: normal runtime camera attachment still creates MuJoCo/synthetic sources.
Likewise, an official Go2 model in MuJoCo is not proof that the simulator uses
physical locomotion dynamics; current base travel is principally a behavioral/
kinematic integration test.

### 6.3 First physical architecture

```text
physical sensors + Unitree state
          |
 timestamps / calibration / provenance
          |
 odometry + localization/SLAM + transforms
          |
 synchronized RobotObservationV2
          |
 local grid / tracks / semantic proposals
          |
 task-selected controller candidate
          |
 independent final safety disposition
          |
 native sole-writer gateway (epoch/lease/TTL/watchdog)
          |
 Unitree Sport Move/StopMove + stationary feedback
```

UI, hosted dialogue, history persistence and large semantic models remain outside
the stop island. Their failure may reduce experience or task capability; it cannot
extend positive-motion authority.

## 7. Target architecture and principal changes

The target is not a whole-codebase ROS or C++ rewrite. It is a modular semantic
application with a few deliberately isolated physical/timing domains.

### 7.1 Target process boundaries

1. **Python semantic application:** interaction, intent, PlanSketch compilation,
   mission supervision, deterministic task executive, memory, semantic world model
   and narration.
2. **Sensor/localization sidecars:** drivers, timestamping, transforms, odometry/
   SLAM, local maps and tracking using ROS 2/C++ where mature infrastructure helps.
3. **Local-autonomy/admission sidecar:** high-rate bounded navigation snapshots,
   local planning candidates and final safety disposition.
4. **Native Unitree gateway:** one robot-network credential/writer, boot epoch,
   arm/disarm, authenticated lease, monotonic sequence, TTL, local limits, watchdog,
   stop dominance and stationary witness.
5. **Optional inference workers:** detector/embedding and language services behind
   bounded queues, deadlines, cancellation and capability health.

### 7.2 Structural refactor order

The order matters:

1. make `core`, `navigation`, `navigation.envs` and `instructnav` initializers thin;
2. migrate production consumers to leaf imports;
3. add forbidden-import/order and capability-admission tests;
4. define synchronized observation, transforms and gateway contracts;
5. then split the 13,127-line `runtime.py` and 6,604-line navigation coordinator
   into lifecycle-owned services.

Splitting the giant files first would move code while preserving the import cycle
and ambiguous capability boundary. Package integrity is the higher-leverage first
step.

## 8. Principal design tradeoffs

| Decision | Selected tradeoff | Benefit | Accepted cost |
| --- | --- | --- | --- |
| Hybrid agent vs token-to-motor | Models propose; deterministic code admits/executes | Replaceable models, bounded authority and truthful replay | More contracts and explicit skills |
| Classical actuating baseline vs learned navigation | A*/tracker actuate; learned systems shadow/propose | Data-efficient, inspectable rollback | May initially underperform advanced methods |
| Unitree Sport vs low-level control | Vendor balance/gait; Parcel body velocity | Much smaller physical assurance problem | Less gait/expression authority |
| Semantic map vs metric SLAM | Keep linked but separate | Correct uncertainty/decay/authority semantics | Transform/revision bookkeeping |
| Route memory vs current geometry | Memory proposes; fresh grid verifies | Familiar long-horizon routes without stale free-space authority | Persistence/reanchoring work |
| UVC vs RGB-D | RGB-D first for metric grounding | Matches current depth/localization contract | Cost, power, USB and calibration |
| Selective ROS vs ROS rewrite | Use ROS for sensors/tf/bags/localization | Gains mature infrastructure while preserving task/safety design | Two ecosystems and IPC contracts |
| Hosted vs local voice | Hosted conversation optional; local closed intents/STOP | Interaction quality without cloud safety dependency | Privacy, cost, network and dual paths |
| Independent final gate vs shared check | Share calibrated inputs, recompute restriction | Defense against planner/config mistakes | Intentional duplicate computation |
| Buy EDU now vs later | Buy after integrity/lab gates as R&D equipment | Earlier physical learning without deployment claim | Capital/operator obligations before product readiness |

Two policies should remain non-negotiable:

- No learned/model/memory component may manufacture physical truth or increase
  downstream motor authority.
- Route memory, semantic names, external maps and language assertions may propose
  where to look; only fresh geometry/localization and deterministic admission may
  justify how to move or whether arrival is true.

## 9. Gated delivery plan

### Gate A — release integrity

- track/verify the minimal licensed Unitree scene asset closure;
- make the runner failure-complete;
- fix the Python 3.11 dataclass defect and settle the 3.10 voice contract;
- test fresh install/import/equal node IDs and behavior on every claimed minor;
- remove eager barrels and semantic soft-degrade;
- obtain clean local and hosted branch-protected evidence.

**Exit:** a tracked-only checkout emits complete reports and runs the same admitted
product/test set across supported environments. No feature promotion or PO approval
precedes this gate.

### Gate B — procurement and lab readiness

- freeze exact Go2 EDU SKU, firmware, SDK, battery, sensor, compute, mount, network
  and licensing assumptions;
- match the vendor return window to acceptance tests;
- prepare controlled area, independent stop/tether, operator and reviewer;
- prepare dedicated network, capture station and data/privacy procedure.

**Exit:** signed R&D acceptance plan and funded BOM; team can collect read-only data
on day one.

### Gate C — physical substrate

- inventory and read-only telemetry;
- synchronize clocks and calibrate sensor extrinsics;
- record physical bags and replay through observation/perception/safety;
- implement native gateway and failure campaign;
- commission axes/frame/modes one at a time;
- measure command response, state age, stop latency/distance and stationary witness.

**Exit:** tethered minimum-speed body motion stops independently on command expiry,
client death, state loss and operator action.

### Gate D — localization and physical perception shadow

- compare estimator/SLAM candidates on the same bags;
- provide MAP↔ODOM transform, covariance, health, jump and relocalization events;
- wire D455/LiDAR physical observations;
- measure detector precision/recall, metric error, freshness and calibration;
- measure semantic duplicate/name/retrieval quality;
- calibrate owner/stranger ROC and track ID switches;
- keep all learned/identity outputs record-only or proposal-only.

**Exit:** frozen physical accuracy/timing/health thresholds pass on independent
visits and people; no synthetic/physical evidence mixing.

### Gate E — supervised autonomous mobility

- tethered point-goal navigation in the first indoor ODD;
- doorways, cul-de-sacs, changing obstacles and dynamic people;
- localization dropout/jump/recovery and sensor/network/process faults;
- semantic goals with independent terminal witness;
- repeated seeds/routes with collision, clearance, intervention, success/SPL,
  latency and false-arrival reporting.

**Exit:** repeated missions meet hard safety and capability thresholds with no
unresolved hard event and an operator can always stop/recover.

### Gate F — companion behavior

- physical owner enrollment and consent;
- following, occlusion, crossing, stranger cut-in and safe give-up;
- voice under gait/fan/room noise with AEC and barge-in;
- correction, pause/resume, clarification and mission repair;
- owner-fact remember/forget/export/delete and derived-data audit.

**Exit:** bounded companion missions succeed with truthful narration, identity
continuity, acceptable social comfort and explicit operator handoff.

### Gate G — ODD expansion

Expand one dimension at a time—surface, lighting, route novelty, crowd density,
outdoor exposure or supervision level. Roads, stairs, elevators and unsupervised
public operation require separate hazards, architecture and evidence.

## 10. Executive risks and decisions required

### 10.1 Top risk register

| Risk | Impact | Immediate mitigation |
| --- | --- | --- |
| False-green release/capability admission | Features silently absent while tests appear green | Integrity Gate A; thin imports; startup-fatal required capabilities |
| No physical localization/SLAM | Global goals, maps and arrival invalid on hardware | Select sensor/estimator candidates; physical bags; MAP↔ODOM health contract |
| Simulator-to-real overclaim | Unsafe procurement/field expectations | Separate evidence levels; physical system identification and stopping campaign |
| Owner identity switch | Robot follows a stranger | Explicit enrolled belief, ROC/ID-switch gates, ambiguity means HOLD |
| Duplicated safety envelopes | Planner/gate disagreement or unexplained stops | One immutable calibrated envelope input; independent monotone final recomputation |
| Python/GPU/cloud failure in motion path | Extended motion or loss of stop | Native sole-writer gateway; local TTL/watchdog; independent stop |
| Personal data leakage/false memory | Trust, privacy and regulatory harm | Consent/provenance, purpose/retention, delete-derived audit, labels not credentials |
| Compute/thermal/dependency mismatch on Orin | Missed deadlines or unusable deployment image | aarch64 install proof, worst-load profiling, thermal soak and power budget |
| Large mutable coordinators | Wide blast radius, lock/teardown defects | Fix import boundaries, then extract lifecycle-owned services |

### 10.2 Decisions leadership must own

1. Exact first ODD, supervision model and hard release thresholds.
2. Go2 EDU SKU/firmware, sensor, compute, battery, mount, stop and network BOM.
3. Supported Python/deployment matrix, including ROS/Humble and Jetson/aarch64.
4. Selected localization/SLAM provider and whether Parcel owns or integrates it.
5. Physical speed regimes and measured stopping/uncertainty reserves.
6. Owner enrollment, identity, consent, retention and multi-person voice authority.
7. Which pose/gesture actions remain simulator-only versus receive a separately
   commissioned gateway capability.
8. What task state may resume after process restart, relocalization or gateway re-arm.
9. Who signs safety review, operates the lab and accepts each promotion gate.

### 10.3 Recommended next milestone

The next milestone should be named:

> **Hermetic software integrity plus a safely commissioned, observable Go2 research
> platform.**

It should not be named “autonomous companion dog.” That later milestone becomes
credible only after the physical estimation–perception–control evidence spine and
repeated first-ODD companion missions exist.

## 11. Source map and further reading

- [Canonical engineering handbook](CONVERSATIONAL_AUTONOMY_HIGH_LEVEL_DESIGN.md)
  — full current architecture, quality evidence, subsystem designs and robotics
  textbook.
- [Documentation index](README.md) — authority and specialist routing.
- [CI gate reference](CI.md) — intended runner/cadence plus current integrity warning.
- [Dependency/environment guide](DEPENDENCIES.md) — host/dependency state and
  Python/asset warnings.
- [Motion and Unitree commissioning](MOTION.md) — controller lifecycle and cautious
  physical bring-up.
- [Runtime concurrency and clocks](RUNTIME_CONCURRENCY_AND_CLOCKS.md) — threads,
  queues, clock domains and scheduling limits.
- [Integrity-gate corrective TODO](../scrum/20260822/INTEGRITY_GATES_TODO.md) — exact
  current closure work.
- [Official Unitree Go2](https://www.unitree.com/go2/) and
  [Unitree SDK2 Python](https://github.com/unitreerobotics/unitree_sdk2_python) —
  platform and Sport-development boundary.
- [Nav2 concepts](https://docs.nav2.org/concepts/) and
  [SLAM Toolbox](https://docs.ros.org/en/humble/p/slam_toolbox/) — standard
  lifecycle/frame/localization integration references.
- [OpenAI GPT Realtime 2.1](https://developers.openai.com/api/docs/models/gpt-realtime-2.1)
  — hosted interaction capability; Parcel retains local tool and physical authority.

The engineering rule for every future status update is simple: name the exact
artifact, default configuration, evidence environment and highest maturity level
actually passed. Implemented is not wired; wired is not verified; simulator-verified
is not hardware-commissioned; fluent narration is not physical truth.
