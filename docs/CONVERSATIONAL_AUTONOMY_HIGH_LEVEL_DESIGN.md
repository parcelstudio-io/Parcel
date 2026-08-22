# Parcel companion robot engineering handbook — current-code edition

**Executive high-level design, as-built audit, robotics textbook, quality and
procurement snapshot, tradeoff record, and gated delivery roadmap**

| Document control | Value |
| --- | --- |
| Status | Canonical living system design; second edition, fully re-audited against the current checkout |
| Audit date | 2026-08-22 |
| Committed baseline | `904edd24fc910bce5f160de3d2f242a03d447cd7` (`main`, also `origin/main` at the audit) |
| Worktree scope | At audit start: the committed C-1/C-2/C-3, W-1 and Wave-P0 code plus 41 pre-existing modified tracked files and the visible uncommitted P1-A through P1-E and P2-A/P2-B wave. This documentation rewrite adds its own diff. Worktree capabilities are labeled **experimental**, never released or commissioned. |
| Audited scale | 308 product Python files / 141,795 lines; 360 `test_*.py` modules / 166,629 test-support lines; 8,701 nodes collected on the local CPython 3.14 environment |
| Product objective | A capable conversational companion that safely executes long-running navigation tasks inside a declared operating design domain (ODD) |
| First proposed ODD | Supervised, flat, mapped, private indoor routes first; dry conditions, adequate light, walking speed, trained operator, physical tether/clearance as required, and an independent stop |
| Audience | Engineering executives, robotics/software engineers, safety reviewers, operators, and learners |

This handbook joins the physical robot, sensing, estimation, semantic perception,
mapping, planning, navigation, control, safety, conversation, task execution,
memory, deployment, and evaluation designs into one system view. It explains both
the engineering decisions and the robotics underneath them. It is intentionally
long-form: the main body supports design and investment decisions; the textbook
appendices derive the core concepts and walk through how this repository applies
them.

It is an architectural synthesis and quality audit, not a claim that the target
system is already operational. In particular, a high test count does not repair a
non-hermetic CI entry point; a physical camera class does not make the runtime use
physical pixels; a semantic landmark database is not SLAM; a Unitree Sport adapter
does not commission a body; and an accepted command does not prove the body moved.
Those distinctions are central to the design.

This edition supersedes the earlier `71b39a1` handbook snapshot. Stable equations
and robotics foundations were retained where the underlying mathematics did not
change, but every repository-specific application, capability statement, quality
number, risk, tradeoff, and roadmap was rechecked against the present code and
configuration. Git history remains the archive for the superseded wording.

### Suggested reading paths

- **Executive / procurement:** read the separate
  [ten-page engineering executive summary](ROBOT_ENGINEERING_EXECUTIVE_SUMMARY.md),
  then use sections 1-5 and 10-14 here for supporting detail.
- **Robotics engineer:** sections 3-11, then Appendices B-H.
- **AI / interaction engineer:** sections 6-10, then Appendices H-I.
- **Safety / release reviewer:** sections 1, 3, 5, 8-13, then Appendices D and G-H.
- **New learner:** Appendix A first, then B-G in order, followed by the main body.

## 1. How to read the claims

Parcel has accumulated implementation records, research proposals, simulator
results, worktree experiments, and physical-commissioning plans at different
dates. The following terms are used strictly:

| Term | Meaning |
| --- | --- |
| **Implemented** | Code exists in this checkout. |
| **Wired** | A normal product entry point reaches it. |
| **Default** | The canonical configuration enables it. |
| **Verified** | A repeatable test or measurement exercises the stated claim. |
| **Operational** | The required service, model, sensor, or device is available. |
| **Commissioned** | Evidence was collected on the intended physical robot and in the intended environment. |
| **Released** | The code and its required assets are committed, pass the release gates from a clean checkout, and have a traceable artifact. |
| **Experimental** | Visible worktree or opt-in code whose isolated evidence may be useful but which is not a released product capability. |
| **Target** | This document recommends it, but it is not a current capability. |

When a statement here disagrees with code, configuration, an executable test, or
a captured physical observation, those artifacts win in that order of relevance
to the claim. Historical Scrum records are useful evidence but are not silently
promoted into current capability. A targeted test result proves its stated seam;
it does not substitute for the interrupted integrated suite or a clean-clone gate.

### 1.1 Evidence planes used in this edition

| Plane | What was inspected | How it may be used |
| --- | --- | --- |
| Committed product | `904edd2`, tracked configs, runtime entry points and tests | Describes the reproducible source baseline, subject to the broken clean-checkout gate |
| Active worktree | Dirty P1/P2 modules, tests, configs, preregistrations and status records | Describes engineering progress, always marked experimental |
| Fresh execution | CPython 3.14 collection, marker partition, clean archive gate, import graph, Python 3.11 import/collection, and a partial serial suite | Current quality evidence with exact limitations |
| Recorded evaluations | Frozen eval ledgers and dated Scrum evidence | Historical or subsystem evidence; never silently generalized |
| Physical hardware | No connected Go2, D455/UVC camera, microphone array or independent stop was exercised in this audit | No L4/L5 physical claim is permitted |

The checkout is therefore both the subject and part of the evidence. This edition
does not hide a dirty tree, but it also does not let uncommitted code raise the
released maturity score.

## 2. Executive design and decision

The right architecture remains a **hybrid deterministic autonomy stack**:

1. Keep Python as the semantic application layer for dialogue, intent, mission
   policy, typed task execution, resource arbitration, and evaluation.
2. Use ROS 2/C++ sidecars selectively for sensor drivers, transforms,
   localization/SLAM, local mapping/tracking, and mature navigation algorithms.
3. Put the Unitree lease, `Move`/`StopMove`, command TTL, local limits, watchdog,
   feedback, stationary witness, and any separately allowlisted physical
   posture/gesture action in a native **sole-writer gateway**.
4. Treat every LLM, VLM, VLA, learned predictor, and sampling controller as an
   untrusted proposal source. Deterministic admission and safety decide whether a
   proposal can become a short-lived body command.
5. Build capability through persistent evidence, bounded recovery, and verified
   task completion. Do not build it by relaxing the model-to-motion boundary.

This design preserves Parcel's strongest semantic and safety work while isolating
the timing and failure domains that must not depend on Python, GPU inference,
logging, a UI, cloud dialogue, or ROS discovery. ROS 2/Nav2 and SLAM Toolbox are
appropriate providers for transforms, localization/SLAM, lifecycle supervision,
costmaps and planners; they should sit behind Parcel contracts rather than replace
the task, evidence, conversation and authority model.

The north-star behavior is deliberately demanding:

> While walking with its owner, the companion can discuss an unrelated topic,
> understand “after the red bench, wait near the entrance,” clarify which entrance
> is meant, navigate without crowding people, explain a blockage, accept “use the
> other entrance” as a revision, reacquire the correct owner after occlusion, and
> report success only after fresh evidence verifies the requested relation.

That scenario requires conversation, grounding, memory, revision, recovery,
identity, social navigation, and terminal truth to work as one system. A better
chat model or a better point-to-point planner alone cannot deliver it.

### 2.1 Executive snapshot at the audit cutoff

**Product judgment:** Parcel is an unusually broad, safety-minded robotics
research/development stack with an integrated MuJoCo companion demo. It is not a
commissioned physical robot product. On the maturity ladder defined in section
5.4, the integrated system remains **L2**: normal simulator paths are wired, several
subsystems reach L3 in deterministic simulation/replay, and no autonomy subsystem
has L4 physical evidence.

**What deserves continued investment:** the semantic-model trust boundary,
deterministic compiler/executive, revision handling, grid baseline, independent
arrival concept, layered stop/control lifecycle, evidence contracts, mutation
testing and adversarial record-keeping. These are harder to reconstruct than a
new model adapter and remain correct strategic foundations.

**What blocks a field claim:** no physical runtime composition, commissioned
localization/SLAM, synchronized physical observation, owner identity, native
sole-writer gateway, measured stopping envelope, independent-stop campaign,
through-air acoustic path, or repeated first-ODD mission evidence. Before any of
those, release truth itself is broken: a fresh checkout lacks the ignored Unitree
MJCF assets, the gate aborts before it reports later stages, the advertised Python
range is not tested, and eager package imports can silently remove semantic
navigation from the exercised product.

**What the newest work changes:** committed C-1/C-2/C-3 and W-1 establish camera,
semantic-memory, source-policy and appearance-generalization foundations. The
active P1/P2 wave goes farther: UVC/RealSense/recorded capture, an isolated GPU
detector daemon, runtime semantic-map writing, owner appearance galleries and
tracking, an ASK-oriented VLM veto, configurable social distance, consent-governed
owner facts, speaker labels, affect and bounded initiative. These are meaningful
engineering increments. They still do not create end-to-end physical perception,
SLAM, owner-safe following, or field motion because the runtime remains composed
around MuJoCo/truth observations and the live hardware rows are unexecuted.

**Recommended executive decision:** keep procurement and field claims behind a
red gate. Spend the immediate increment on hermetic CI, the real Python support
matrix, import/capability admission, the native physical authority boundary, and
the synchronized sensor/localization spine. Continue perception, memory and
learned navigation in replay/shadow. A Go2 EDU may be acquired only as a supervised
engineering instrument under the staged procurement policy below—not because this
checkout is ready to be mounted and released as a companion dog.

### 2.2 Procurement and mount-and-run answer

| Decision | Current answer | Rationale |
| --- | --- | --- |
| Is the software ready to mount on a Go2 EDU and run semiautonomously? | **No** | The normal runtime is simulator-composed; there is no physical observation assembler or localization/SLAM; default semantic truth is an oracle; owner perception is not live; stopping and authority are uncommissioned. |
| Is it ready to justify a production or companion-product hardware purchase? | **No—hold purchase approval** | The clean-checkout CI gate cannot run and the supported-Python/import contracts are false. Procurement would precede basic release integrity. |
| Is it mature enough for a vendor evaluation unit, loaner, or explicitly budgeted R&D platform? | **Conditionally yes** | The Unitree adapter, simulator, control contracts and commissioning plan make hardware feedback valuable, provided the organization accepts that it is a development instrument with supervised, separately armed experiments only. |
| What may proceed now? | Quote, lead-time, accessory, SDK/licensing, battery, compute, sensor-mount and return-policy research | These are reversible planning actions and reduce schedule uncertainty without claiming readiness. |
| What unlocks the purchase order? | IG-1 through IG-3 locally green, hosted evidence, an approved first-ODD/hazard plan, a sole-writer gateway design, named operator/stop equipment, and a funded sensor/localization bill | These gates prevent buying a locomotion base while assuming its onboard sensors solve the missing autonomy spine. |

The hardware choice also does not solve perception by itself. A Go2 EDU provides a
mobile, balanced quadruped and vendor development interfaces; Parcel still needs a
calibrated sensor suite, compute/network/power design, mounts, time synchronization,
localization, safety commissioning, operators and evidence storage. Purchase the
platform when the team is ready to learn from hardware every week and can protect
those sessions with an independent stop—not when software completeness is being
inferred from simulator coverage.

## 3. Current architecture, as built

### 3.0 What “current” means in this audit

The committed baseline is `main` at `904edd2`. It contains the perception cutover,
textured-scene wave and Wave P0 that the first edition treated as in flight. At
the documentation audit start, the active feature checkout added 5,715 insertions
and 171 deletions across 41 tracked files plus untracked P1/P2 packages, tests and
evidence. An engineer sees all of
that code, so this handbook explains it; only committed, cleanly reproducible code
may count toward release.

| Capability plane | Committed `904edd2` | Active worktree | Default / authority consequence |
| --- | --- | --- | --- |
| Simulation and appearance | MuJoCo city A/B, W-1 textures/meshes, ray-cast scan, dynamic actors, truth pose and semantic sidecars | Additional experiment records and integration fixes | Main launch path remains MuJoCo; official-looking robot geometry is not dynamic or physical validation |
| Camera ingress | Typed C-1 MuJoCo/synthetic observation ingress and legacy candidate ingress | P1-A adds UVC, RealSense, recorded sources and a Unix-socket detector/embed daemon | Classes exist, but `RobotRuntime` still creates MuJoCo/synthetic camera sources; launcher environment selection does not make physical pixels reach the runtime |
| Learned semantic map | C-2 evidence-bearing object/place map, persistence and C-3 `oracle`/`learned_map`/`shadow` policies | P1-B installs the selected learned map during runtime start, feeds camera frames, persists on close, and adds naming/thumbnail/embedding work | The old “no composition owner” claim is obsolete. The path is now composed for an off-oracle selected profile, but production default remains `oracle`, physical origin is unproved, and the map is not SLAM |
| Exploration | Bounded patrol/map-building evaluation runner | P1-B replays it against the product writer/persistence path | Evaluation utility, not a user-facing autonomy mission or coverage planner |
| Owner perception | Simulator owner tracks, follow/search and UWB-fusion seams | P1-C adds appearance enrollment, gallery, SigLIP-2 embeddings and an owner tracker | Runtime owner events/tracks still originate in MuJoCo mocap; held-out live owner rows were halted for lack of camera/hardware |
| Ambiguity and vocabulary | Deterministic abstention/contention and semantic cutover controls | P1-D adds an optional subtractive VLM veto, ASK outcomes and name growth | Naming scored 45% on its 40-entry fixture; VLM cannot grant motion, and unavailable/uncertain evidence must ASK or refuse |
| Social envelope | Shared safety concepts with a 1.2 m production person band | P1-E exposes a 0.70 m prototype band above a derived 0.68 m floor and a 1.25 m owner keepout | Simulator-only; planner and final gate do not yet consume one proven envelope despite the shared-number work |
| Personal memory | Recent SQLite conversation and dormant tiered memory | P2-A adds consent/provenance-bearing owner facts, remember/forget tools, deterministic policy and full-ledger replay | Deterministic probes pass; hosted model-selected storage is unrun, distillation scheduling is incomplete, and privacy must be audited across derived artifacts |
| Identity, affect and initiative | Voice-origin/authorization gates and bounded social expression | P2-B adds speaker labels, hosted affect, owner-event classes and bounded whisperer initiative | Labels are deliberately not motion credentials; speaker enrollment is absent and owner-presence events still derive from simulator truth |

Two configuration facts prevent accidental capability inflation:

1. `configs/navigation/default.yaml` still selects `semantic_source: oracle` and
   disables route memory. `configs/robot.yaml` still selects the simulator
   controller, leaves Unitree axes/frame/modes uncommissioned, and names an `rl`
   motion backend with an empty policy path—there is no actuating learned policy.
2. `configs/navigation/prototype.yaml` contains the learned-map and abstention
   experiment, but the robot prototype overlay does not by itself turn that file
   into the normal product profile. Effective configuration, not the existence of
   an option, defines authority.

The worktree has fixed part of the former C-1→C-2→C-3 composition gap. The remaining
truth gap is more fundamental: physical UVC/RealSense frames are not assembled with
physical pose, scan, tracks and controller state into the observation consumed by
navigation. A semantic source can be wired while the robot is still entirely a
simulator product.

### 3.1 End-to-end logical path

```text
microphone or text
        |
        v
VAD / endpointing / STT final transcript
        |
        v
DuplexVoiceSession turn + generation guard
        |
        v
VoiceAgent + DeterministicIntentRouter
   |
   +--> immediate STOP --------------------------> stop/cancel paths
   |
   +--> direct/legacy Dog, activity, or controller action --+
   |       (bypasses compiler/executive)                    |
   |                                                        |
   +--> local PlanSketch or deliberative PlanIR/PlanSketch  |
   |         -> compiler + fresh-snapshot validator                    |
   |         -> TaskExecutive + resource leases                       |
   |         -> SemanticTaskRuntimeAdapter                            |
   |         -> navigation/follow/spatial/activity controllers -------+
   |                                                        |
   +--> conversation model                                 |
           -> read-only tools -> text reply                |
           -> optional bounded social `next_action`        |
              -> deterministic validation/activity --------+
                                                            |
                         +----------------------------------+------------+
                         |                                               |
                         v                                               v
                  velocity intent                               pose/trajectory
                         |                                               |
       CommandArbiter -> pre-gate VelocitySmoother              stop locomotion
                      -> input health/reactive/TTC safety         + activity/E-stop gates
                      -> actuator S-curve shaper                  + backend.pose/trajectory
                      -> post-shaper hard/proximity stop
                         reassertion + reset
                         |
                         v
                ControlManager / velocity backend

 executive-managed controller/activity feedback
       -> ExecutionResult + VerifiedFact -> TaskExecutive
```

The stack has two interaction lanes. Hosted Realtime is the intended modern lane;
local endpointing/STT/Gemma/TTS remains the explicit legacy/offline path. The
checkout does not contain `configs/realtime.yaml`, so a constructor using only the
checked-in defaults disables the hosted lane until an example is copied and
credentials are declared. This is a deployment prerequisite, not an always-on
default capability. Both lanes terminate in a restricted tool or intent surface:
neither receives raw velocity, joint, lease, priority, or safety authority.

The current observation/evidence plane is equally important:

```text
                    canonical default                 selected experiment
MuJoCo socket ──> SimObservation ───────────────┐   MuJoCo/synthetic camera
      │                                         │            │
      ├── truth MAP/ODOM pose                   │      detector daemon
      ├── ray-cast scan -> rolling grid         │            │
      ├── mocap owner/dynamic tracks            │     typed detections
      └── oracle semantic rows -----------------+------┐     │
                                                       │     v
                                        semantic source selector <- OnlineMap
                                                       │       ^
                                                       v       │
                                         grounding/search/arrival
                                                               │
                                            P1-B runtime feed --+

Physical UVC/D455 classes ──X──> synchronized physical observation/runtime
Unitree telemetry          ──X──> pose/scan/tracks/controller evidence
```

The right-hand learned-map edges are now installed by the worktree runtime when an
off-oracle profile is effectively selected; this is an important correction from
the first edition. The crossed physical edges remain missing. `RobotRuntime` and
the web-panel builder still obtain simulator-shaped state from a
`MujocoSocketBackend`; the physical camera selector is consumed by new launcher/
backend code, not by the runtime's normal camera factory. Safety geometry remains
independent of semantic source. Choosing where the word “bench” comes from is not
allowed to choose whether the scan is fresh or whether a body command is admissible.

The most important existing architectural property is that the language model is
not a servo controller. Model work is outside the control loop; deterministic code
owns admission, resources, revisions, execution, completion, and final motion.

The most important missing architectural property is a real physical composition
root. A deployable root must select and health-check: sensor drivers, clock
discipline, extrinsics, robot-state estimator, MAP↔ODOM transform, perception
providers, synchronized world snapshot, controller state source, native gateway,
evidence store and capability manifest. Today, `launch_stack.sh` ultimately starts
the simulator path; the Unitree HAL and capture tools are parallel foundations.

### 3.2 Current capability matrix

| Area | Current checkout/default state | Architectural reading |
| --- | --- | --- |
| Turn handling | Hosted Realtime is the intended modern lane; explicit local/legacy speech remains. No canonical `configs/realtime.yaml` is tracked, so hosted behavior requires operator configuration. Final transcripts can act; partials may prepare/cancel but do not execute. Turn, generation, origin, spend and restricted-tool gates exist. | Strong software authority boundary, but deployment depends on credentials/network/config and no through-air AEC campaign exists. |
| Emergency and common intent | A deterministic router handles stop, follow, hold, navigation, status, corrections, and compound routing. | Correct least-latency, least-authority path. |
| Conversation | Config examples select current GPT Realtime models; local Gemma/llama.cpp remains a reasoning/planning and legacy-conversation service. Tools are schema-restricted and revalidated. P2-B adds affect and initiative plumbing. | Capable guarded prototype, not commissioned voice interaction. Model labels, affect and initiative never establish physical identity or motion authority. |
| Planning | The canonical config omits `planner_output_contract`, so model planning defaults to verbose `plan_ir_v1`; system-authored local plans use `PlanSketch`. | Safe because authority fields are overwritten, but the model contract exposes needless surface and prompt drift. |
| Plan admission | Skills, resources, preconditions, timeouts, success conditions, invariants, freshness, and semantic grounding structure are deterministically compiled and validated. `NavigateTo` may still begin an active search for an unseen target. | One of Parcel's strongest seams; admission is not proof that the destination is currently visible. |
| Task execution | `TaskExecutive` is deterministic and rejects stale revision/attempt feedback. | Strong state-machine core, but recovery and wait behavior are incomplete. |
| Physical action lifecycle | Follow, hold, spatial, and navigation normally use the brain path; simple walks, catalog skills, backend switching, and legacy fallbacks can bypass it. | `RobotRuntime` bypasses still traverse its downstream safety, but task/resource/progress authority is split. The legacy ROS JSON publisher has no product-path safety proof and should be isolated or retired. |
| World evidence | Rich `EvidenceEnvelopeV1` types, bounded logs and a semantic ingress exist. Planner snapshots still originate mainly in `SimObservation` and flatten calibration, covariance, identity and world revisions. | Contracts are stronger than the composed evidence plane; there is no synchronized backend-neutral physical `RobotObservationV2` or authoritative revisioned world model. |
| Camera acquisition | MuJoCo/synthetic ingress is composed. P1-A implements UVC, RealSense, recorded playback and a bounded Unix-socket detector/embed daemon. Synthetic/recorded measurements put process overhead at 0.6–1.8 ms p50 and detector round trip around 100.6–113.7 ms p50. | Good process-isolation proof. No live camera was attached; the physical backend is not selected by `RobotRuntime`; UVC has no metric depth path. |
| Semantic perception | Default T0/oracle reads simulator truth. OWLv2, pixel-depth localization, tracking, confirmation and abstention components exist. | Useful proposal infrastructure. Default authority is still an oracle and no physical precision/recall, calibration or freshness distribution is commissioned. |
| Pose/localization | `PoseProvider`, frame types, covariance/health checks and truth/drift providers exist. The default runtime hardcodes simulator truth for MAP and ODOM with zero covariance. | This is explicitly a seam, not an EKF, odometry system or SLAM. There is no production `T_map_odom`, transform buffer, scan matcher, loop closure or relocalizer. |
| Local navigation | `grid_v1` uses a rolling 161×161 grid at 0.1 m, log-odds ray updates, footprint inflation, A*, dynamic costs and a forward-preferred tracker. A grid-invalid scan can fall back to a point-goal stub, while downstream reactive checks accept a different scan-validity contract. | Strong deterministic simulator baseline with a degraded-path gap; missing/malformed required geometry should yield a typed HOLD rather than a less-informed translating controller. |
| Metric/global mapping | The actuating grid is a roughly 16.1 m robot-centered rolling window. There is no persistent metric map server, SLAM or long-range geometric planner. | Local occupancy is not global localization or a building map. |
| Semantic map | P1-B runtime hooks can install/feed/persist the `OnlineMap` for learned/shadow profiles. A recorded sim patrol created 69 active entries across 7 labels and reload continued to 85/8. | Object/place memory depends on pose correctness and is not free-space geometry. Evidence is simulated; duplicate rate/retrieval quality remain unmeasured, persistence is close-time oriented, and physical origin is unproved. |
| Semantic navigation | Deterministic grounding, relation parsing, current-view/memory/search/approach/progress/arrival logic exist. Learned-map source is instance-bound in the worktree, but default remains oracle. Eager imports can still make required InstructNav unavailable through a soft capability flag. | Substantial L2/L3 simulation logic with an integrity false-green risk. Required semantic capability must be admitted explicitly at startup. |
| Route memory | Place-graph and waypoint-proposal APIs connect to the navigation proposer path but remain default-off and session-oriented. | Useful topology proposal layer; not persistent validated relocalization, traversability truth or SLAM. |
| Patrol / map-building motion | The bounded patrol runner turns around people/geometry and exercises the semantic writer. | Evaluation driver, not a coverage planner, autonomous mission or product skill. Earlier single-run path/contact numbers remain historical rather than current release evidence. |
| Social/dynamic navigation | Dynamic soft costs, TTC and keepouts operate mainly on simulator tracks. P1-E configures a 0.70 m prototype stranger band with a 0.68 m computed authority floor and 1.25 m owner keepout. | Algorithms exist without physical track provenance. The smaller band is uncommissioned, and planner/gate envelopes are not yet one proven immutable derivation. |
| Owner identity/following | Follow, behind formation, prediction, search and UWB seams exist. P1-C adds an appearance gallery and tracker; real SigLIP crop embedding measured 3.44 ms p50 on the desktop. | Runtime identity remains mocap/simulator truth. Held-out owner recall and live two-person track tests are halted; appearance labels cannot yet authorize owner following. |
| Ambiguity/VLM | P1-D adds a subtractive VLM veto, ASK outcome and vocabulary/name-growth evidence. | The VLM may remove/ask, never grant motion. Fixture naming was 18/40 (45%); this is not dependable place naming or a wired voice clarification loop. |
| Expression/attention | Dialogue expression is subordinate to locomotion. P2-B adds affect/initiative and owner-event plumbing. | Social behavior is partly shadow/software-only; owner events remain simulator-derived and labels are not identity gates. |
| Audio | Local endpointing and hosted transcript deltas retain evidence, but only committed utterances act. Closed safety intents remain deterministic. | No commissioned microphone/playback reference, AEC, ego-noise, speaker-authentication or through-transducer latency/cutoff result exists. |
| Dual-stream research | The D0 TEXT+ACT frame path is shadow/logging telemetry and has no action authority. | Correct staging boundary; synchronous logging still needs removal from the semantic caller. |
| Safety/control | The normal velocity path has priority/TTL arbitration, input-health and reactive collision/person/TTC gates, two shaping stages, post-shaper hard/proximity-stop reassertion, and a sole `ControlManager` velocity writer. Pose/trajectory activities first stop locomotion, then call separate backend methods through activity/E-stop gates rather than the velocity safety chain. | Strong velocity-control design, but physical effect authority is split and no independent native gateway exists. |
| Physical bring-up | Unitree Sport adapter, controller registry, evidence origin and commissioning manager exist. Canonical axes/frame/modes are deliberately uncommissioned. Capture tooling is parallel to runtime. | No capability-admitting physical launcher, native sole-writer gateway, synchronized sensor spine or commissioned motion. |
| Deployment | Launch scripts and console entry points exist, but the web-panel/runtime builder is MuJoCo-centered and the main stack terminates in simulator launch. Service containers are incomplete. | Development composition, not a physical deployment topology. |
| Memory/personalization | Conversation SQLite is active. P2-A adds consented owner facts, deterministic store/refuse/forget policy and full-ledger replay; tiered, route and semantic memories remain separate. | Stronger privacy seam, not proven long-horizon personalization. Hosted model-selected storage, distiller scheduling and derived-data deletion need evidence. |
| Observability | Turn latency, component metrics, ledgers, duplex records, and recent transcript-origin logging exist as separate surfaces. | Broad instrumentation without one causal trace. |
| Packaging/CI | Runtime assets have a 91-item parity check, but the required Unitree MJCF tree is broadly gitignored and absent from Git. | A source-tree parity pass on a developer machine does not make a clean checkout hermetic; the aggregate gate currently crashes before later checks and tests. |

### 3.3 Code map

| Concern | Current owner |
| --- | --- |
| Main turn routing and model/tool handling | [`agent.py`](../src/parcel_robot/agent.py) |
| Hosted Realtime transport, admission, tools, evidence and spend | [`realtime/`](../src/parcel_robot/realtime/) |
| Runtime composition and final dispatch | [`runtime.py`](../src/parcel_robot/runtime.py) |
| Deterministic intent | [`brain/router.py`](../src/parcel_robot/brain/router.py) |
| Typed task/snapshot/result contracts | [`brain/contracts.py`](../src/parcel_robot/brain/contracts.py) |
| Cross-boundary evidence contracts | [`contracts/v1.py`](../src/parcel_robot/contracts/v1.py) |
| Current planner snapshot projection | [`brain/observations.py`](../src/parcel_robot/brain/observations.py) |
| Plan compilation and validation | [`brain/compiler.py`](../src/parcel_robot/brain/compiler.py), [`brain/validator.py`](../src/parcel_robot/brain/validator.py) |
| Task state machine and runtime binding | [`brain/executive.py`](../src/parcel_robot/brain/executive.py), [`brain/runtime_adapter.py`](../src/parcel_robot/brain/runtime_adapter.py) |
| Navigation mission coordinator | [`navigation/pipeline.py`](../src/parcel_robot/navigation/pipeline.py) |
| Rolling grid planner/controller | [`navigation/grid_planner.py`](../src/parcel_robot/navigation/grid_planner.py), [`navigation/grid_navigator.py`](../src/parcel_robot/navigation/grid_navigator.py) |
| Pose/localization seam | [`pose.py`](../src/parcel_robot/pose.py) |
| Pixel localization/tracking chain | [`detection_adapter/`](../src/parcel_robot/detection_adapter/), [`camera_channel/`](../src/parcel_robot/camera_channel/) |
| Physical/recorded camera adapters and detector process | [`camera_channel/backends/`](../src/parcel_robot/camera_channel/backends/), experimental worktree path `src/parcel_robot/perception_daemon/` |
| Robot-written semantic map and naming | [`online_map/`](../src/parcel_robot/online_map/) |
| Semantic-source selection/shadow comparison | [`perception_source/`](../src/parcel_robot/perception_source/) |
| Bounded patrol/evaluation driver | [`patrol/`](../src/parcel_robot/patrol/) |
| Owner appearance gallery and tracking | Experimental worktree path `src/parcel_robot/owner_tracking/`, [`uwb/fusion.py`](../src/parcel_robot/uwb/fusion.py) |
| VLM abstention/veto | Experimental worktree path `src/parcel_robot/vlm_veto/`, [`perception_abstention.py`](../src/parcel_robot/perception_abstention.py) |
| Consent-governed owner model | Experimental worktree path `src/parcel_robot/owner_model/`, [`memory.py`](../src/parcel_robot/memory.py) |
| Owner follow and search | [`navigation/follow.py`](../src/parcel_robot/navigation/follow.py), [`navigation/search_owner.py`](../src/parcel_robot/navigation/search_owner.py) |
| Route/place memory | [`route_memory/`](../src/parcel_robot/route_memory/) |
| Footway/crossing policy | [`maps/`](../src/parcel_robot/maps/) |
| Command admission and final stop | [`core/arbiter.py`](../src/parcel_robot/core/arbiter.py), [`core/input_health.py`](../src/parcel_robot/core/input_health.py), [`core/hard_stop.py`](../src/parcel_robot/core/hard_stop.py) |
| Physical control lifecycle | [`control/manager.py`](../src/parcel_robot/control/manager.py) |
| Authority/envelope derivation | [`authority.py`](../src/parcel_robot/authority.py) |
| Conversation memories | [`memory.py`](../src/parcel_robot/memory.py), [`tiered_memory.py`](../src/parcel_robot/tiered_memory.py) |
| Model provider and voice/audio loops | [`providers.py`](../src/parcel_robot/providers.py), [`voice_audio.py`](../src/parcel_robot/voice_audio.py), [`duplex/`](../src/parcel_robot/duplex/) |
| Voice arming and reaction selection | [`audio_arming.py`](../src/parcel_robot/audio_arming.py), [`voice/reaction_bridge.py`](../src/parcel_robot/voice/reaction_bridge.py) |
| Capture/replay foundation | [`capture/`](../src/parcel_robot/capture/) |

In the audited worktree, `runtime.py` is 13,127 lines and
`navigation/pipeline.py` is 6,604 lines. They are effective integration
laboratories, but their size, lock surface, mutable state, and cross-cutting
responsibilities now make authority, invariants, clocks, teardown, and failure
behavior difficult to audit. Decomposition is therefore a risk-reduction program,
not a style cleanup.

There is a more urgent structural problem than their size. Importing the leaf
`core.arbiter` or `navigation.velocity_shaping` currently pulls in 118 Parcel
modules, including `navigation.pipeline`, simulator environments and InstructNav,
because `core/__init__.py` and `navigation/__init__.py` eagerly re-export broad
surfaces. That cycle has previously caused a seven-hop import failure to set
`_HAS_INSTRUCTNAV = False`, converting semantic navigation into a no-op while tests
outside the real composition remained green. Thin package initializers, leaf
imports, import-graph tests and startup-fatal required-capability admission come
before the god-object split. Otherwise decomposition merely moves the same cycle.

## 4. What is already well designed

### 4.1 Semantic models, deterministic authority

The model can propose goals and bounded skills, but cannot author raw velocity,
joints, arbitrary skill names, controller priority, or actuator leases. The plan is
recompiled and checked against a fresh snapshot at acceptance. This contains model
hallucination and makes model replacement possible without rewriting control.

**Keep this boundary.** More autonomy should mean better perception, memory,
recovery, and task reasoning—not a shorter route from tokens to motors.

### 4.2 Revision-safe interaction

Committed transcripts, turn generations, task revisions, step attempts, and
revision-stamped navigation proposals prevent late work from silently overriding a
correction. This is essential for utterances such as “actually, use the other
door” while a slow planner is still running.

### 4.3 Independent completion evidence

Navigation distinguishes geometric arrival from task truth. Semantic arrival can
require a settled body, healthy pose, fresh perception, target continuity, and the
requested goal-region relation. Route-memory waypoints remain interim hints; they
cannot declare the true mission complete. This is substantially safer and more
honest than treating “planner path ended” as success.

### 4.4 Layered motion gates and exact-stop reassertion

Arbitration, limits, input freshness, directional reactive safety, TTC, two
smoothing stages, and final hard-stop logic are separate. Classified hard and
proximity stops are reasserted after actuator shaping, and the finalizer resets
stateful shaping when exact zero is required.

This is a strong exact-stop boundary, but it is not yet the complete independent
post-shaper governor described by the target design: it consumes the earlier
proximity disposition rather than re-evaluating geometry/evidence, and it does not
reassert every possible nonzero clamp. Threshold duplication also remains. The
target should preserve/reduce every disposition independently after shaping.

### 4.5 Classical default, learned challengers

The rolling occupancy grid and A* path are deterministic, inspectable, and
data-efficient. Optional learned perception/grounding and value-directed search
pieces are proposal-only or disabled. Learned navigator YAML metadata exists, but
the runtime builder supports only `stub` and `grid`; CityWalker, NaVILA, NoMaD, and
ViNT are not runnable navigator challengers in the current checkout. This is still
the correct promotion posture: a real adapter should first rank goals, frontiers,
routes, or cost priors under replay and shadow evaluation.

One configuration name needs special care: canonical `configs/robot.yaml` selects
`motion.backend: rl`, but its `policy_path` is empty. `RLPolicyBackend` therefore
runs as the `rl[stub]` intent facade; no learned locomotion policy is loaded or
executed. Simulator velocity still reaches the body through `ControlManager` and
the simulator controller. A literal `rl` key is not evidence of an actuating RL
policy.

### 4.6 Explicit ambiguity and failure states

Grounding can report resolved, remembered, unseen, or ambiguous. Search is bounded,
and navigation has progress/replan limits. The robot has the vocabulary to admit
uncertainty instead of driving toward the nearest convenient detection. The target
design should carry that honesty through to dialogue and mission repair.

## 5. Why the current system is not yet the objective

The primary limitation is integration, not a shortage of algorithms. Components
that are individually sensible do not yet share one evidence, authority, task, and
deployment contract.

### 5.1 High-impact gaps and design responses

| Gap | Consequence | Target response |
| --- | --- | --- |
| A clean checkout does not contain `third_party/unitree_mujoco`, although committed scenes require it. | The workflow-equivalent commit gate throws an unhandled MuJoCo asset error before JSON, later hard stages, or pytest. Local ignored files create a false reproducibility boundary. | Track a manifest-pinned minimal licensed Go2 asset pack (or fetch it deterministically before every consumer), verify hashes/provenance, and make `unitree-assets` a named failure-complete hard stage. |
| Packaging advertises Python `>=3.10`; CI runs only 3.12; `RetainedEvent.fields` fails dataclass import on 3.11. | The current 3.11 audit collected 6,067 nodes with 69 collection errors versus 8,701 on 3.14—a 2,634-node gap. The `websockets>=17` voice dependency also excludes 3.10. | Fix the field with an immutable default factory, define a real upper/lower support contract, test install/import/node-ID parity/default behavior across every claimed minor, and split or narrow incompatible extras explicitly. |
| Eager `core`/`navigation` barrels load 118 Parcel modules from leaf imports. | Optional/import-order failures contaminate unrelated modules; a seven-hop cycle can make `_HAS_INSTRUCTNAV=False` and turn required semantic navigation into a green no-op. | Make initializers side-effect-light, migrate product imports to leaves, add forbidden-edge/order tests, and replace required-capability soft fallback with startup-fatal admission. |
| CI stages are not independently exception-contained. | One setup/asset exception suppresses all later results, including the test suite, so absence of a reported failure can be mistaken for a pass. | Convert every stage exception to a bounded named `ERROR`, continue independent checks, always emit valid text/JSON, and preserve nonzero exit for any hard FAIL/ERROR. |
| Consequential physical actions have multiple lifecycle paths. | Cancellation, resources, progress, and verification are inconsistent. | Route every consequential non-emergency action through one semantic task gateway; keep decorative expression subordinate and STOP independent. |
| Pose/trajectory activities call separate backend methods after stopping base motion; they do not traverse the velocity reactive/TTC chain. | `ControlManager` is not a sole writer for every kind of physical effect, and the target velocity-only gateway contract would strand expression/posture authority. | Add a separately allowlisted `GatewayActionV1` or keep physical pose/trajectory/expression unsupported until it exists and is commissioned. |
| Planning is one-shot. | Terminal failures restart local controllers or end; they do not produce bounded mission repair, clarification, or a grounded explanation. | Add a budgeted `MissionSupervisor` above the deterministic executive. |
| Routing/planning/schema/validation can fail before a task exists, without one typed pre-admission disposition contract. | Dialogue can conflate “heard,” “unsupported,” “rejected,” and “accepted.” | Add `TurnDispositionV1`; reserve `TaskEventV2` for admitted transactions. |
| Executive-level compiled recovery is unreachable for accepted plans because compiled steps use `max_attempts=1`; navigation/controller-internal recovery still exists. | `PlanStep.recovery` looks available but cannot run. | Make retry policy a system-owned per-skill contract, with fresh evidence before redispatch. |
| Resource/precondition waits have no separate deadline. | A task can remain waiting indefinitely without a user-visible disposition. | Add admission, grounding, resource-wait, execution, and overall mission deadlines. |
| `TaskExecutive.tick()` returns at most one dispatch globally despite disjoint resources. | Voice/attention work cannot progress concurrently with a long base action. | Add bounded disjoint-resource concurrency with system priorities, fairness, and critical-phase vetoes. |
| The runtime adapter reports every in-progress poll as a checkpoint. | Current checkpoint replacement can mean “any poll,” not a controller-certified safe interrupt/persistence point. | Require a typed, expiring `ControllerCheckpoint` backed by settled/interruption evidence. |
| Typed navigation grounding is converted back to free text and reparsed. | The validated relation and the navigator's interpretation can diverge. | Pass a typed `NavigationTask` end to end; retain text only for audit/explanation. |
| Planner snapshots flatten rich evidence. | Models and verifiers lose frame, covariance, calibration, unique observation, and causal provenance. | Build query-scoped snapshots from an evidence-enveloped world store. |
| Camera candidates embed a detector sequence in string IDs but do not expose capture time/view identity as structured evidence, and cached reads are not deduplicated by consumers. | One cached frame can count as multiple independent observations for confirmation or arrival. | Require immutable perception snapshots and independence-aware deduplication. |
| Learned-map runtime feed now exists, but profile and physical-source composition are fragmented. | It activates only for an effectively selected learned/shadow navigation profile; the prototype robot overlay does not select that profile, and the physical-camera launcher setting is not consumed by the runtime factory. Operators can believe they selected physical learned navigation while running oracle/MuJoCo inputs. | Add one top-level schema/capability manifest and composition owner for effective profile → camera → map → source; report effective provenance and fail startup on incomplete or contradictory combinations. |
| P1-A detector process timing is promising, but no physical capture-to-consumer distribution exists. | Desktop synthetic/recorded daemon figures cannot justify a perception TTL, camera freshness, or safety authority; UVC is RGB-only. | Attach the intended D455/camera, measure hardware timestamp through consumer under contention, calibrate depth/extrinsics, account for drops/restarts, and keep semantic evidence proposal-only until physical tails and accuracy pass. |
| MuJoCo camera state is not fully synchronized with dynamic actors/joints. | A person can occupy different poses in the control and rendered worlds; simulator image evidence cannot validate dynamic-person safety. | Synchronize all safety-relevant scene state at capture time, record revisions, and test temporal alignment—while still treating this as simulation evidence. |
| `RobotRuntime` universally obtains a `SimObservation` from a `SimulatorBackend`; there is no production physical observation assembler. | Adding a Unitree actuator does not create physical autonomy: pose, scan, people and controller evidence still have no synchronized, physical-origin path into runtime safety and navigation. | Introduce a backend-neutral `RobotObservationV2` assembled from timestamped physical providers, then make simulator and replay explicit adapters rather than the universal data model. |
| The normal Unitree builder supplies a raw state source whose declared evidence origin resolves to `UNKNOWN`. | Physical input health correctly refuses the evidence even if the SDK, network, mode and actuator are otherwise available; test-only commissioned wrappers do not prove the product composition. | Require a reviewed `CommissionedStateSource(origin=PHYSICAL)` in the normal physical launcher and bind it to the versioned capability/calibration manifest. |
| Online-map persistence is close-time oriented and physical corpus quality is unmeasured. | Crash/power loss can lose recent observations; duplicate rate, geometry/name precision and retrieval quality are unknown; simulator growth counts do not establish a correct map. | Add periodic transactional checkpoints and recovery tests; measure precision/recall, duplicate rate, position error, name promotion, abstention and restart continuity on independent physical visits. |
| The learned online map is object-centric and has no native semantic-region representation. | Extended places such as sidewalks and plazas cannot be grounded or verified faithfully; forcing them into point objects loses topology and extent. | Add versioned region/surface beliefs with polygon uncertainty and observation provenance, or explicitly keep region questions on a separate source until that contract exists. |
| Learned-map naming/VLM evidence is below product quality. | The P1-D fixture named only 18/40 entries correctly; a fluent but wrong name can poison dialogue and navigation. | Preserve label-primary identity, make names secondary and revisable, require multi-visit evidence, use VLM only subtractively, and freeze held-out ASK/false-admit operating points before activation. |
| Default pose and dynamic tracks are simulator truth. | Navigation scores do not demonstrate field localization or person tracking. | Add production sensor/localization/tracking providers and deterministic replay before robot promotion. |
| MAP goals and ODOM poses lack a real timestamped transform. | Simulator truth hides frame inconsistency; physical tracking can be wrong after drift or relocalization. | Make a localization service own `T_map_odom`, covariance, health, and jump events. |
| Semantic-memory ingestion can fall back to time zero. | Age decay is ineffective in the normal path. | Make time and observation sequence mandatory evidence fields. |
| Search-frontier fallback can bypass the grid planner. | Collision gates remain, but exploration can stall or oscillate in clutter. | Send every translation-bearing search/recovery target through the behavior-scoped goal manager and local planner. |
| Static POI point goals do not use the full semantic terminal witness. | Controller termination can be interpreted more strongly than the available task evidence. | Require a typed terminal policy for every goal class and report exactly what was verified. |
| Road/crossing policy exists but is not wired into production goal, costmap, and final command authority. | A declared road invariant is metadata rather than a live geofence. | Enforce road state in three independent places and fail closed on poor localization/map provenance. |
| `GoalArbiter` is usually called on singleton proposals and has no production lethal-cost callback. | It is a validation helper, not one continuous subgoal authority. | After task/preemption selects the behavior owner, use a live behavior-scoped `GoalManager` for mission, route-memory, exploration, recovery, and operator navigation subgoals; keep moving formation distinct. |
| Route memory is disabled and its normal live hook is process-local, although save/load APIs exist. | It cannot provide wired cross-restart place continuity or relocalization. | Persist and load a versioned place graph with change detection; never treat it as free-space truth. |
| Owner following lacks commissioned identity/re-identification; the new appearance tracker is test-only. | Runtime still receives the owner from mocap truth. “Nearest/most similar person” without a calibrated operating point risks an identity swap. | Wire an explicit physical owner belief from enrolled appearance plus optional UWB, calibrate owner/stranger ROC and continuity, and make ambiguity/loss mean HOLD/search/clarify. |
| Detection lock-on can be enabled while verification-on-approach is disabled. | The configuration/API admits a combination already associated with a wrong-instance false arrival: roughly 4.78 m distance-to-go and success-rate regression from 0.32 to 0.24 in the recorded candidate evidence. A warning is not an admission control. | Reject the combination at schema/startup time and require fresh instance identity plus terminal verification whenever lock-on can influence motion or arrival. |
| Safety thresholds are duplicated across planner and runtime. | A planner-valid route can be executor-impossible and diagnoses are ambiguous. | Derive all planning envelopes from one immutable `RobotProfile x SpeedRegime x SafetyEnvelope`; keep the final gate independent. |
| Recoverable HOLD/proximity/missing-scan policies may preserve yaw, while a latched input-health fault is exact zero at finalization; a no-provider pose fallback can still report healthy zero-covariance state. | The boundary between permitted inspection rotation and full stop, plus terminal pose truth, remains under-specified for physical use. | Resolve each input-class/pose policy explicitly, then freeze exact dispositions with property tests. |
| Grid-invalid scan and malformed prediction have permissive internal fallbacks. Grid scan validity is stricter than reactive scan presence, so stub translation is not always suppressed. | Malformed calibration or prediction can leave more motion than the failed component can justify. | Make safety-relevant components return typed degraded/HOLD states under one calibrated evidence contract; retain downstream gates as independent defense. |
| The native physical gateway and capability-admitting physical launcher do not exist. | Python remains in the prospective physical command failure domain. | Land an isolated, restart-disarmed, sole-writer gateway before autonomous motion. |
| Shared llama.cpp serving has one active cancellation handle. | Conversation, planning, and summarization can cancel or starve each other. | Add an inference broker with role-scoped queues, deadlines, cancellation, and overload policy. |
| Tiered memory is disabled and fragmented from task/spatial memory. | The companion lacks durable reference, commitment, place, and failure continuity. | Introduce governed working, episodic, profile, and spatial memory stores. |
| The reaction arbiter's selected output is recorded but not enacted. | “Social reaction” evidence can be mistaken for product behavior. | Wire it only to bounded voice/attention/expression adapters or label it shadow-only. |
| No commissioned local acoustic AEC exists; hosted partial-ASR deltas are retained as evidence but never enter the behavioral/action path. | Physical barge-in, self-talk rejection and natural through-air latency remain weak or unmeasured even though the hosted protocol can stream partial evidence. | Commission capture identity and AEC; keep partials limited to preparation/interruption and admit only completed turns; measure through-transducer tails and cutoff. |
| Declarative invariants are stored as one replaceable runtime tuple and enforcement is distributed across subsystems. | Protection may exist, but a task/revision cannot be traced cleanly from invariant to monitor, intervention, and evidence. | Add per-task/revision invariant leases and a monitor registry through terminal state. |
| Duplex/session logging performs synchronous file work from the 10 Hz semantic caller. | Storage latency competes with motion dispatch even though the 50 Hz `ControlManager` thread is separate. | Enqueue bounded telemetry with drop accounting; move serialization/rotation/storage off all control callers. |
| Runtime and navigation are large shared-state coordinators, but package boundaries are already collapsed by eager barrels. | Changes have wide blast radius; ownership, import health, locks and teardown are difficult to audit. Splitting first can preserve the cycle in more files. | Thin package initializers and stabilize leaf contracts/admission first; then extract lifecycle-owned ports/services and split processes only at real fault/timing boundaries. |
| Reactive slow-band output is force-fed back into the upstream velocity smoother. | The same safety attenuation compounds across ticks; MOVE-1 measured roughly 2.2x less speed than one policy application intended. This is safe-directional but distorts behavior and every throughput/latency conclusion in the band. | Separate desired-state history from final gated output, add a closed-form steady-state property, and re-run follow/patrol baselines without weakening the stop boundary. |
| The first patrol acceptance run recorded 10 collision ticks and only narrowly cleared its 5 m path floor. | The dynamic-city collision signal mixes robot-caused contact with agents striking a stationary robot; a single narrow pass cannot establish reliable exploration. | Attribute contact by relative motion/causal responsibility, repeat across seeds, report path coverage and net progress, and keep zero-contact as a separately visible hard metric. |
| The MOVE-1 status references `evidence/MOVE1_EXIT_GATE.txt`, but that artifact is absent from the current task evidence. | A narrative pass cannot be independently reproduced or promoted from the referenced evidence package. | Regenerate the gate artifact from immutable inputs or mark the claim incomplete; add reference-existence checks to evidence governance. |
| The 91 generated runtime assets are parity-gated, but required third-party MJCF is outside that closure. | A byte-identical internal manifest can coexist with a clean checkout that cannot compile its scenes. Installed-wheel and deployed behavior are still separate claims. | Expand closure to every required runtime asset with provenance, keep clean-wheel tests, and add capability/deployment smoke; never equate parity with safety. |

### 5.2 Evidence baseline

The worktree is test-rich: 308 Python files under `src/parcel_robot` (141,795
lines, including experimental/untracked packages) and 360 top-level
`test_*.py` modules (166,629 Python lines including `conftest.py`). On the local
CPython 3.14.4 environment, collection found **8,701 nodes**: exactly 8,620 in the
commit selection and 81 in the slow selection. The marker inventory includes 50
`skipif`, 7 `xfail`, 3 `load_sensitive`, and zero `e2e` nodes. These are collection
properties, not runtime outcomes.

The larger footprint is a material strength. The current promotion result is still
**red and incomplete** because the aggregate gate is not hermetic or
failure-complete, the dirty worktree has new lint findings, the Python contract is
false, and no complete current integrated suite finished during this audit.

#### Current executable quality result

| Check | Current result | Engineering reading |
| --- | --- | --- |
| Fresh committed-checkout gate | **ERROR before report:** a `git archive HEAD` checkout exits in about 0.40 s when MuJoCo opens the missing ignored Go2 XML | `.gitignore` excludes `third_party/`; Git tracks no Unitree pack/submodule; Actions fetches nothing. The exception escapes before JSON, later hard gates or pytest. This is the first integrity blocker. |
| CPython 3.14 collection | **8,701 collected:** 8,620 commit + 81 slow | Useful inventory only. Collection success on one unsupported-by-workflow workstation version does not establish the advertised range. |
| CPython 3.11 collection | **6,067 collected, 69 collection errors; 2,634 current nodes absent relative to 3.14** | `realtime/protocol.py` uses `MappingProxyType({})` directly as a dataclass default; 3.11 rejects it. CI's 3.12-only lane cannot observe this. The earlier 2,214-drop report predates current suite growth. |
| Python 3.10 dependency contract | **Inconsistent** | Base metadata says `>=3.10`, while the voice extra's `websockets>=17` requires Python 3.11+. Support must be narrowed or dependencies split and tested. |
| Current Ruff evaluator | **FAIL:** 16 fingerprints—7 grandfathered and 9 new | The nine new rows are in untracked P1 evidence scripts. The aggregate runner computes this but crashes before summarizing it. A ratchet pass would still not be raw-lint cleanliness. |
| Targeted gate tests | **45 passed, 1 warning** for `tests/test_ci_gate.py` | Useful runner-unit evidence, but it does not seed the missing-asset case or prove that an exploding early aggregate stage still reports later stages. |
| Partial current serial suite | **Interrupted honestly at ~402 s / ~17%:** 1,542 passed, 3 failed, 81 deselected | Not a suite verdict. The three observed failures in `test_capture_ingest.py` assume `pyrealsense2` is absent although installed on this host—an environment-coupled defect to resolve. |
| Individual hard-stage probes on the developer tree | **Narrow positives:** 91-asset parity; frozen nav 0 modeled collisions/false arrivals; freshness mutation equal; seven Follow-Bench rows zero; five assertion fixtures/20 findings reproduced | These use the developer's ignored Unitree checkout. Assertion-evaluator green means expected findings were detected; two represented sessions intentionally remain red. None repairs the aggregate or proves hardware. |
| Hosted Actions / complete nightly | **Unverified / no current clean evidence** | Workflow text is not execution evidence. Required branch-protected hosted results and retained artifacts are still needed. |

The preceding operator reproduction found 118 of 170 observed failures sharing the
missing-asset cause. That was valuable diagnosis, but “170” is not the current suite
denominator because the hard gate aborts and the tree has since grown. The fresh
tracked-only archive result establishes the more fundamental fact: a clean checkout
cannot reach or report the remaining checks.

The current failures should not erase the repository's many good tests, and the
many tests must not erase the failures. The useful executive conclusion is:
**strong local regression engineering around a research simulator, currently
blocked by release-integrity defects and with no physical assurance.**

The exact corrective execution plan is
[`scrum/20260822/INTEGRITY_GATES_TODO.md`](../scrum/20260822/INTEGRITY_GATES_TODO.md).
It deliberately prioritizes hermetic assets/failure-complete reporting, the true
Python matrix, thin package boundaries and fail-closed semantic capability before
new features or god-object decomposition.

### 5.3 Quality-system strengths and limits

#### Strengths

- Exact-key immutable contracts, deterministic clocks and extensive negative cases.
- Pre-registered measurements with null/control arms and explicit misses.
- Seeded-defect/mutation panels that test whether important tests can actually fail.
- Frozen internal manifests, source/package parity, held-out leakage protection and
  owner-store isolation. The ignored Unitree pack is an explicit exception to close.
- Exact commit/slow marker partition across the current 8,701-node collection.
- Honest `does_not_prove` boundaries in many eval/status records.
- A sole normal velocity-writer feedback supervisor, layered command gates and
  exact-stop property tests at the application boundary; pose/trajectory backend
  effects remain a separate authority gap.

#### Gaps

- No line/branch coverage measurement or minimum; high test count cannot reveal
  which production branches are untouched.
- No mypy/pyright gate, despite a contract-heavy dynamically typed integration
  surface.
- No dependency-vulnerability, secret, license/SBOM or static-security promotion gate.
- Raw Ruff debt remains, and the active worktree adds nine unbaselined evidence-file
  findings. A ratchet guarantees “no new fingerprint,” not clean code.
- Two collection-time deprecation warnings still use the retired footprint constant.
- The gate is not hermetic or failure-complete; required third-party assets live only
  in ignored workstation state.
- CI declares Python 3.12 only while packaging declares Python `>=3.10`; 3.11 cannot
  import a core Realtime contract and the voice dependency range excludes 3.10.
- No import-graph or composition admission gate proves required semantic navigation
  is actually present; zero nodes currently carry an `e2e` marker.
- Hosted workflow installation uses broad `pyproject.toml` ranges rather than the
  repository lock, so local and hosted dependency resolution can differ.
- The workflow job timeout is 20 minutes while the internal default-suite timeout is
  30 minutes; a valid long gate can be killed by its wrapper.
- Capture tests make environment-dependent assumptions about optional RealSense
  installation; three such failures appeared before the partial suite was stopped.
- Complete current commit/nightly evidence and hosted Actions execution remain
  unverified; branch-protection enforcement is not recorded.
- Four of six latency-tail pins, the acoustic sentinel, E1 seal, dependency-lock
  completeness, Gemma provenance and the model-seat fixture gate are still tracked
  as eval-hygiene work; a green dedicated stage is narrower than full evidence trust.
- Only one of the two legacy `walk_with_me` ledger rows carries
  `hard_collision_total`; a hard-safety evaluator that passes available rows is not
  equivalent to complete historical collision instrumentation.

### 5.4 Capability maturity snapshot

This handbook uses an internal five-level ladder rather than borrowing an ambiguous
marketing TRL:

| Level | Meaning |
| --- | --- |
| L0 | Design/research only |
| L1 | Implemented in isolation |
| L2 | Wired through a normal development entry point |
| L3 | Repeatedly verified in deterministic simulation/replay for the stated scope |
| L4 | Verified on intended hardware under supervised bounded conditions |
| L5 | Commissioned for the declared ODD with repeated integrated evidence |

| Subsystem | Current level | Why it stops there |
| --- | ---: | --- |
| Deterministic task contracts/executive | L3 | Broad tests and simulated execution; consequential-action lifecycles and recovery remain split |
| Local grid navigation and semantic mission logic | L3 | Strong MuJoCo/replay coverage but a known semantic-arrival red, oracle perception and no physical localization |
| Velocity safety/control supervision | L3 | Property/fault/simulator evidence; no commissioned native gateway, stopping envelope or hardware independent-stop campaign |
| Hosted conversational lane | L2 | Implemented and launcher-selectable, but disabled in an unconfigured checkout; cloud/network/privacy dependency and no through-air physical campaign |
| Local acoustic lane | L2 | Piper/endpointing artifacts exist, but no commissioned physical PortAudio stream, AEC or through-air latency |
| MuJoCo camera ingress | L2 experimental | Normal simulator attachment exists; not physical observation evidence |
| Physical camera/daemon | L1 experimental | UVC/RealSense/recorded adapters and bounded daemon pass targeted tests; no attached-camera row and no runtime composition |
| Online semantic map/source cutover | L2 experimental | Worktree runtime installs/feeds/persists it under learned/shadow; default remains oracle and evidence is simulated |
| Owner appearance/tracking | L1 experimental | Isolated/gallery/encoder tests; live owner recall/continuity halted and runtime remains mocap-backed |
| VLM veto/naming | L1 experimental | Subtractive/ASK seam tested; 45% naming fixture and no physical calibration |
| Owner facts/initiative | L1-L2 experimental | Deterministic consent/replay/label logic is wired in the worktree; hosted/live and privacy end-to-end rows remain open |
| Patrol | L1-L2 experimental | Standalone runner exercises mapping; not a runtime skill, coverage guarantee or product mission |
| Unitree physical locomotion | L1 | Adapter/supervisor implemented; SDK/NIC/modes/axes/frame and body behavior are uncommissioned |
| Physical observation/localization/SLAM spine | L0-L1 | Capture/provider interfaces exist; no synchronized physical observation, estimator, `T_map_odom`, loop closure, localization integrity or runtime binding |
| Integrated companion product | **L2 overall** | A capable simulator/development stack, not fielded autonomous robot evidence |

### 5.5 Recorded product and experimental results

| Evidence set | Recorded result | What it does not prove |
| --- | --- | --- |
| Semantic navigation v4 | 25 episodes, success rate 0.24, SPL 0.1933, zero modeled collisions | General autonomy, physical perception or physical collision safety |
| Scripted follow/navigation | Follow 7/9; navigation 2/2 | Identity-safe owner following or ecological validity |
| Gemma conversation calibration | 6/10 machine cases; about 349 ms median first-token latency | Human companion quality or the hosted lane |
| Live PersonalConvo | 3/13 turns and 1/8 families | Long-horizon personal continuity |
| Planner quality v2 | 5/5 selected semantic cases; 5.657 s median usable-plan latency | Physical execution or acceptable interactive tail latency |
| Synthetic duplex | Five of nine gates fail | Through-air audio, AEC or natural barge-in |
| Embodied PlanIR | 4/4 supported deterministic MuJoCo cases; moving owner unsupported | Moving-owner behavior, field sensors or deployment readiness |
| Earlier C-1 MuJoCo camera | Safety gate p99 delta +0.735 ms; 562.6 ms median frame age; all 16 retained frames expired | Current P1-A daemon timing, physical freshness or grounding authority |
| P1-A detector daemon | Recorded synthetic/desk-clip detector p50 100.6/113.7 ms; process overhead p50 0.6/1.8 ms; 93 passed, 1 expected failure in the corrected targeted status | Live UVC/D455 capture, depth calibration, physical origin at runtime or consumer-age tails |
| P1-B map writer | Simulator patrol 69 active entries/7 labels; reload run 85/8; targeted status records 500 passed, 2 warnings | Physical map precision/recall, duplicate rate, retrieval quality, crash durability or SLAM |
| P1-C owner appearance | Real desktop SigLIP crop embed p50 3.44 ms; corrected GPU status 99 passed; CPU status 93 passed/6 skipped | Held-out live owner recall, owner/stranger ROC, continuity or runtime wiring; those rows were halted |
| P1-D VLM/name path | 18/40 (45%) naming fixture; corrected targeted 51 passed/1 skipped plus six real-seat GPU rows | Dependable naming, physical-domain calibration, full voice ASK flow or authority to admit motion |
| P1-E social band | Prototype 0.70 m band above a software-derived 0.68 m floor; status records 993 passed, 5 skipped, 1 expected failure | Physical stopping distance, perception latency, comfort, or one planner/gate envelope; the status explicitly withdraws that latter claim |
| P2-A owner facts | Nine deterministic probe families met; targeted status records 99 tests; hosted model-chosen storage missed/owner-gated | Privacy of every derived artifact, model judgment quality, scheduled distillation or a live hosted session |
| P2-B identity/affect/initiative | Targeted status records 125 tests and bounded label/event behavior | Speaker enrollment/authentication, physical owner presence, through-air affect quality or base authority |
| Earlier patrol evidence | 5.0137 m path, 57 entries, five place classes, 10 collision ticks, 0.134 m net displacement | Reliable exploration, causal contact attribution, map correctness or generalization |

External BARN/Habitat results remain algorithm proxies. They are useful for
regression and challenger selection but must not be used as product or physical
readiness claims.

## 6. Target system architecture

### 6.1 Process and fault-domain view

```text
┌──────────────────────── Python semantic application ────────────────────────┐
│                                                                             │
│ InteractionRuntime ──> CognitionCoordinator ──> MissionSupervisor           │
│       │                       │                       │                     │
│       │                       v                       v                     │
│       │                 InferenceBroker            TaskExecutive            │
│       │                       │                       │                     │
│       └──────────────> DialogueNarrator <─────────────┘                     │
│                                                       │                     │
│ WorldModel ──> Grounding ──> GoalManager ──> semantic/global route policy   │
└─────────────────────────────────────────────┼───────────────────────────────┘
                                              │ ExecutionGoal/global corridor
                                              v
┌──── deterministic local-autonomy + actuation-admission sidecar (20-50 Hz) ─┐
│ timestamped transforms | rolling local/elevation/dynamic maps               │
│ local planner/track -> MotionCandidateV2 -> final safety disposition        │
│ admitted ActionRequestV1 -> capability/resource/action safety admission     │
└─────────────────────────────────────────────┼───────────────────────────────┘
                                              │ GatewayCommandV1/GatewayActionV1
                                              │ over one bounded authority IPC
                                              v
┌──────────────────── native sole-writer robot gateway ───────────────────────┐
│ boot epoch | arm state | TTL | lease | limits | watchdog | StopMove         │
│ command/action sequence | feedback | stationary witness | local audit ring  │
└─────────────────────────────────────────────┬───────────────────────────────┘
                                              │ Unitree DDS / Sport API
                                              v
                                  onboard gait and balance

 camera/LiDAR/IMU ─> ROS2/C++ sensor + localization + tracking sidecars
                              ├──> bounded real-time local-autonomy inputs
                              └──> versioned evidence snapshots ──> WorldModel

 independent handheld stop ─────────────────────────> vendor/physical stop
 nonblocking trace recorder <──────────────────────── every typed boundary
```

An admitted Python `TaskActivityAdapter` sends `ActionRequestV1` to the sidecar for
allowlisted posture/gesture capabilities. Action admission does not pass through
the velocity planner, but it applies capability, resource, stationary-base, expiry,
and STOP rules. The sidecar is the one gateway authority client and emits either a
`GatewayCommandV1` or `GatewayActionV1`; incompatible leases cannot coexist.

The Python layer should become a **modular monolith**, not a fleet of small
services. Interaction, mission, task, world-model, semantic grounding, and global
route policy benefit from typed in-process calls and one composition root. The
current Python grid planner/controller remains a useful simulator/replay baseline
during migration. Deadline-critical local mapping, tracking, collision disposition,
and control should move behind an extractable deterministic C++/ROS 2 sidecar once
the replay contract is proven. Keeping them in Python beyond that point would
require measured isolation evidence showing that GIL stalls, model failures, and
logging cannot violate their deadlines.

Use separate processes only where timing, crash isolation, vendor lifecycle, GPU
scheduling, or ROS tooling justify the deployment cost:

- the native robot gateway;
- sensor/localization/mapping/tracking and deadline-critical local-autonomy sidecars;
- inference workers or broker when GPU contention requires it;
- a nonblocking recorder/exporter.

### 6.2 Authority hierarchy

| Layer | May propose | May reject or reduce | May command hardware |
| --- | --- | --- | --- |
| Conversation model | Reply, clarification, read-only tool request, bounded social-expression proposal | No | No |
| Planning model | Goal and bounded semantic skill sequence | No | No |
| Learned vision/navigation | Entity belief, cost/route/frontier/trajectory candidate | No | No |
| Mission supervisor | Retry, replan, clarify, terminate within budgets | Yes, at semantic level | No |
| Compiler/validator/executive | Admitted task transaction and resource leases | Yes | No |
| Task-managed activity adapter | Allowlisted posture/gesture `ActionRequestV1` | Yes | No direct vendor API |
| Goal manager/global route policy | Semantic goal/corridor | Yes | No |
| Local-autonomy/actuation-admission sidecar | Short-horizon motion candidate or admitted physical action and final disposition | Yes, monotonically | No direct vendor API |
| Native gateway | Short-lived vendor body command | Yes, monotonically | **Yes, sole writer** |
| Independent stop | Stop | **Always** | Independent authority |

Positive motion requires a complete chain of authority. Stop requests should have
broader admission and should not depend on a model, healthy logger, world database,
or planner.

### 6.3 Time-scale separation

| Time scale | Responsibilities | Rule |
| --- | --- | --- |
| 50 Hz gateway | Lease, watchdog, local caps, vendor write, feedback, stop witness | Native, bounded, allocation-conscious, independent of Python health |
| 20-50 Hz local motion | Costmap/trajectory tracking and collision/social disposition | No model calls, disk I/O, or unbounded queues |
| About 10 Hz semantic runtime | Snapshot publication, controller state, task dispatch, invariant monitors | Bounded work; telemetry enqueue only |
| Event-driven interaction | ASR finals, dialogue, planning, tools, mission repair | Revision/deadline guarded; may be slow or cancelled |
| Background | Summaries, embeddings, map persistence, evaluation export | Never required for motion liveness |

The exact frequencies are platform and controller choices. The architectural rule
is that a slower layer may fail to refresh authority, causing HOLD/STOP, but cannot
block a faster safety layer.

## 7. Core target contracts

Several names below are target contracts from the accepted production design, not
current product implementations. `WorldSnapshotV2` and the split gateway message
names refine that design: the proposed broader world view and the accepted
high-rate `NavigationSnapshotV2` are revision-linked projections over the same
evidence lineage, while `RobotGatewayV1` names the stateful protocol rather than
one message. All should be versioned in one
compatibility registry and generated into Python/native validators, fixtures, and
log decoders.

| Contract | Minimum content | Why it exists |
| --- | --- | --- |
| `CommittedTurnV1` | Session, turn/generation, exact immutable transcript text or content-addressed payload reference, content hash, normalization/version, capture source/epoch, speech timing, supersession and `authority_ref` | Makes planner/audit input explicit, revision-safe, and linked to separately validated authority. |
| `CommandAuthorityV1` | Principal, authentication/evidence, allowed capabilities, scope, expiry, revocation, source turn | Separates “what was heard” from who may authorize positive motion. |
| `TurnDispositionV1` | Turn/generation, route, heard/planning/clarification/unsupported/rejected/admitted outcome, typed reason/evidence, optional task reference and speech eligibility | Makes pre-admission failures and clarification truthful without inventing a task event. |
| `TaskTransactionV2` | Task/revision, source turn, goal, invariants, budgets, admitted skills, disposition | One atomic unit for submit, correct, pause, resume, cancel, and explain. |
| `ControllerCheckpointV1` | Task/revision/step/attempt, controller-certified interruptible and settled state, evidence/timestamp and expiry | Prevents “any poll” from being mistaken for a safe replacement or persistence point. |
| `NavigationTaskV2` | Task/revision/provenance plus a typed unresolved `NavigationIntentV2` and later grounded/execution references | Prevents lossy text reparsing without pretending geometry is known at admission. |
| `GroundedGoalV2` | Candidate hypotheses, selected entity, evidence/independence group, frame, covariance, confidence and expiry | Separates perception-backed grounding from language intent. |
| `ExecutionGoalV2` | Safe approach candidates, committed goal region, transform/envelope revision, terminal evidence policy | Gives local navigation a metric contract only after grounding. |
| `SensorFrameV2` | Sensor identity, capture/receive time, sequence, frame, calibration, payload reference, health | Removes simulator-shaped and duplicate evidence from production paths. |
| `EvidenceEnvelopeV2` | Evidence ID, source, origin, frame, timestamps, sequence, scene revision, covariance/confidence, expiry | Makes every belief auditable and freshness-checkable. |
| `WorldSnapshotV2` | Immutable snapshot ID/revision, transforms, robot/owner/entity beliefs, maps, health, evidence references | Broader, decision-bound view for planning/dialogue and source for narrower projections. |
| `NavigationSnapshotV2` | Bounded real-time projection, transform epoch, local maps/tracks, health, envelope and evidence sequence | Coherent local-navigation input that does not depend on history persistence. |
| `OwnerBeliefV1` | Enrolled identity, track state, ambiguity, covariance, visibility/occlusion, last evidence, expiry | Makes owner following identity-safe. |
| `GoalProposalV2` | Source, typed goal region, task/revision and raw score/evidence; system registry supplies priority, TTL and capabilities and calibrates confidence by source/provenance | Supports continuous subgoal arbitration without trusting proposal authority fields. |
| `MotionCandidateV2` | System-stamped candidate ID, producer, production timestamp/sequence, effective expiry, source task/revision, snapshot, short trajectory/command horizon and footprint/envelope version | Untrusted internal controller candidate whose freshness and reuse can be mechanically rejected by the final governor. |
| `ActionRequestV1` | Source task/revision, allowlisted semantic capability ID, bounded arguments, resource/precondition references and requested duration | Untrusted task/activity request entering actuation admission; never contains vendor calls or raw joints. |
| `SafetyDispositionV1` | `PASS < CLAMP < HOLD < STOP < LATCHED_STOP`, causes, monitors, evidence, reset obligations | Makes decreasing-only intervention explicit and composable. |
| `TerminalWitnessV2` | Task/revision, relation, pose belief, settled feedback, independent evidence IDs, uncertainty, disposition | Separates true completion from controller termination. |
| `TaskEventV2` | Accepted, waiting, started, progress, blocked, retrying, revised, completed/failed/cancelled plus cause/evidence and optional certified checkpoint reference | Feeds recovery, narration, replay, and evaluation without inventing interruptibility. |
| `RobotGatewayV1` | Protocol/version negotiation, boot/arm/lease state machine, writer identity, health and fault semantics | Defines the stateful sole-writer boundary. |
| `GatewayCommandV1` | Boot epoch, arm token, monotonic sequence, TTL, safety disposition, bounded body command, envelope/config hash | Sole safety-governor-to-gateway actuation request; prevents stale/replayed writes. |
| `GatewayActionV1` | System-stamped action ID/sequence, boot/arm/lease, task/revision, allowlisted capability/profile ID and hash, TTL, bounded duration/parameters, cancellation and completion policy | Sole admitted route for physical posture/trajectory/gesture; never accepts arbitrary joint arrays. |
| `GatewayFeedbackV1` | Boot/arm/lease state, accepted sequence/action, controller/action state, fault, timestamps, stationary witness | Closes command, action, and stop truth without consulting the model or world-history store. |

No authority-bearing field should travel in an unvalidated `dict`, `extras`, or
mission metadata bag. Extension fields are acceptable for diagnostics only and
must not change motion, success, identity, or authorization semantics.

## 8. Subsystem high-level designs

### 8.1 Interaction and conversation

#### Design

1. A capture service emits audio frames with endpoint identity and source sequence.
2. VAD/endpointing produces partial hypotheses and one committed final transcript.
3. Partials may update the UI, prepare context, and trigger provisional TTS ducking;
   they may never authorize physical action.
4. A deterministic router handles STOP/cancel/pause/resume and direct, closed skills.
5. Ordinary conversation starts immediately on the exact committed transcript.
6. Spatial, compound, ambiguous, or long-horizon turns also open a task-planning
   lane against the same turn and world revision.
7. One `DialogueActSequencer` owns speech for the turn. An action turn may receive
   a noncommittal “heard/working” acknowledgement. `TurnDispositionV1` may report
   pre-admission clarification, unsupported, planning-failed, or validation-rejected
   outcomes; only admitted `TaskEvent` evidence may say accepted, started, blocked,
   or completed. A correction invalidates pending narration by turn/task revision.
8. A `DialogueNarrator` converts those committed facts and task dispositions into
   concise, personality-appropriate speech.
9. A bounded two-pass read-only tool loop allows tool selection followed by a
   result-grounded response. Tool/retrieval content retains source and trust labels,
   cannot establish authorization or physical truth, and physical tools remain
   outside that loop.
10. Local cascades and managed native speech-to-speech services implement the same
    normalized provider/media event contracts. A managed session may supply
    transcripts, reply audio, and tool proposals, but local code still commits the
    turn, principal, task disposition, and every physical action. See the
    [replaceable voice-provider design](VOICE_PROVIDER_ARCHITECTURE.md).

#### Rationale

Fast deterministic triage keeps stop and common actions independent of model
latency. Parallel conversation avoids several seconds of silence while planning,
but shared turn/revision guards prevent a stale plan from committing. Separating an
acknowledgement (“I heard you”) from acceptance (“I can do that”) prevents fluent
speech from becoming a false capability claim.

The first ODD permits autonomous subgoals only inside an explicitly authorized
mission and its time/geofence/capability budget. The companion may initiate speech,
attention, or a clarification, but must not originate a new positive-motion mission
without the configured user/operator authorization. Authority is revocable at any
time. Broader proactive mobility is a later, separately consented product policy.

#### Improvements over current behavior

- Add streaming partial ASR, AEC, echo/junk rejection, and capture-principal
  evidence before relying on a physical microphone.
- Use a priority-aware speech queue so safety/task messages are not dropped when
  the speaker is busy; implement duck/restore around real barge-in.
- Resolve references against discourse and world state, not only one pending scene
  referent.
- Make task progress available to the prompt as typed state rather than a few
  summary strings.
- Enact reaction proposals only through bounded voice, gaze/attention, or
  expression adapters with expiry and locomotion critical-phase vetoes.

### 8.2 Cognition, mission repair, and task execution

#### Design

```text
CommittedTurn + WorldSnapshot
             |
             v
 deterministic intent + local skill policy
             |             \
             |              \ bounded planner, when needed
             v               v
                PlanSketch
                    |
          system compiler + validator
                    |
            TaskTransaction revision
                    |
             MissionSupervisor
                    |
             TaskExecutive
                    |
      verified task events and evidence
                    |
      retry / alternate / clarify / terminate
```

`PlanSketch` should be the default model output because it exposes only semantic
choices the model is actually allowed to make. The system compiler should remain
the sole author of resources, timeouts, retry budgets, success conditions,
interruptibility, and invariants.

Every consequential non-emergency physical request—including a one-step walk,
posture change, catalog gesture, follow, or navigation action—should become a task
transaction. This creates one place for resource ownership, revisions,
pause/resume, cancellation, progress, and completion. High-frequency decorative
expression may remain a subordinate expiring overlay behind `ExpressionGate`; it
must not acquire base authority or masquerade as task completion. If the overlay
has a physical effect, it still requires an allowlisted `GatewayActionV1` and
compatible lease; otherwise it remains simulator-only. STOP remains a direct,
dominant path.

The new `MissionSupervisor` is a bounded policy layer, not another motor
controller. Given a typed failure, it selects among:

- deterministic retry with fresh evidence;
- a local scan or alternate terminal approach;
- a different grounded instance or route;
- a bounded `PlanSketch` revision;
- an owner clarification;
- safe termination.

Budgets must include attempts, replans, elapsed time, distance, energy, and model
calls. A mission cannot recurse indefinitely. Any model revision re-enters normal
compilation, fresh-snapshot validation, and replacement only at a
controller-certified checkpoint (or after a dominant stop).

#### Rationale

The current task executive is intentionally deterministic, which is valuable, but
advanced autonomy needs semantic feedback around it. A bounded supervisor adds
closed-loop problem solving without placing nondeterministic reasoning in the
servo loop or letting a model waive safety invariants.

#### Required corrections

- Fix system-owned `max_attempts` so declared recovery is reachable.
- Add separate admission, grounding, resource-wait, execution, and mission
  deadlines.
- Persist task events and only controller-certified checkpoints; restore only after
  revalidation, and never persist or replay velocity commands.
- Support concurrency only for explicitly disjoint resources. Base/posture remain
  exclusive; voice/attention may proceed during long motion when the skill and
  critical-phase policies allow it. System-owned priorities, wait deadlines,
  fairness, and starvation/priority-inversion metrics govern that concurrency.
- Track invariant leases per task/revision until terminal, rather than storing one
  replaceable global tuple.

### 8.3 Evidence plane and world model

#### Design

The world model is the shared historical/semantic evidence plane, not a mutable bag
of “current facts.” Sensor, localization, detector, tracker, map, owner, task, and
gateway records enter as immutable envelopes. One `WorldModel` owns association,
belief history, and revisioned query projections. Deadline-critical local mapping
and safety receive the validated sensor stream directly and never wait for history
persistence or semantic association.

```text
validated sensor/localization/gateway streams
             |                         |
             |                         +--> high-rate NavigationSnapshotV2
             |                              -> local maps/safety/controller
             v
      append evidence record
             |
   association + belief updates
             |
WorldSnapshot(snapshot_id, scene_revision)
     |             |             |
  dialogue       planner      terminal verifier
```

The store must represent **unknown**, **unobserved**, **stale**, **ambiguous**, and
**observed absent** as different states. A remembered object is a hypothesis with
source, confidence, covariance, and expiry—not current free-space truth.

Snapshot projections should include:

- robot pose in ODOM and MAP plus timestamped `T_map_odom`;
- localization covariance, health, relocalization, and jump events;
- calibrated static occupancy/elevation and hard geofences;
- semantic entity tracks with stable identity and unique observations;
- dynamic tracks with velocity uncertainty and occlusion state;
- owner belief and authorization state;
- task/resource/invariant state;
- robot/gateway feedback, battery, thermal, and capability health;
- evidence references needed to justify dialogue and terminal success.

#### Rationale

A revisioned snapshot lets each decision bind to one coherent view and makes
cross-revision mixing detectable; it does not force asynchronous consumers to use
one simultaneous global “now.” High-rate local snapshots and slower semantic
snapshots are revision-linked and preserve per-sensor timestamps. Evidence
references enable replay and honest explanations. Adapters allow simulator,
rosbag, live ROS, and physical providers to exercise the same autonomy code without
exposing oracle fields in production contracts.

### 8.4 Memory and personalization

Memory should be separated by semantics and retention policy:

| Memory | Examples | Authority and retention |
| --- | --- | --- |
| Working dialogue | Recent turns, active referents, open questions | Session-scoped; may shape language, not establish physical truth alone |
| Episodic task | Commitments, task outcomes, obstacles, corrections | Append-only events plus compact summaries; bounded and replayable |
| Owner profile | Preferred formation side, name, accessibility preferences | Explicit/consented facts with confidence, edit, export, and delete |
| Spatial/semantic | Places, traversed edges, object hypotheses, change history | Evidence-backed, frame/revision-aware, decay and invalidation required |

Writes, summarization, distillation, and indexing should be asynchronous. Retrieval
is query-aware, read-only, deadline-bounded, and optional on timeout. A model may
propose a memory fact; a deterministic privacy/validation policy decides whether it
is stored. Physical beliefs require sensor/task evidence and can never become true
merely because the model wrote them.

This structure is a better tradeoff than one vector database for everything. It
preserves explainability and distinct forgetting rules while still enabling
cross-memory queries such as “take the quiet route we used yesterday.”

### 8.5 Semantic grounding and active perception

#### Design

1. Consume an unresolved typed `NavigationIntentV2` from `NavigationTaskV2`.
2. Resolve against current evidence, then stable spatial memory.
3. If unresolved, execute a bounded information-gathering policy: inspect, scan,
   choose an observed frontier, and reobserve.
4. Maintain multiple instance hypotheses rather than collapsing early to the
   nearest detection.
5. Accumulate positive and negative evidence by unique observation ID and
   independence group: capture/view token, temporal separation, viewpoint/parallax,
   source/model correlation, and track lineage.
6. Commit a `GroundedGoalV2`, then convert the chosen entity/relation into an
   uncertainty-aware `ExecutionGoalV2` with multiple safe approach candidates.
7. Clarify when hypotheses remain ambiguous or the search budget expires.

VLMs may rank candidates, frontiers, and likely semantic regions. They should not
create metric pose certainty, override a hard map, or declare arrival. The
deterministic grounder and verifier retain authority.

#### Rationale

Active perception is central to advanced conversational navigation: “the other
entrance” or “near the red bench” cannot always be resolved from the current
frustum. Treating perception as an action policy with a budget is more capable and
more honest than fabricating a coordinate from language.

### 8.6 Hierarchical navigation

#### Target layers

```text
ExecutionGoal / semantic goal region
               |
 task-selected navigation behavior owner
               |
     behavior-scoped GoalManager
               |
 semantic-place graph + route/topology planner
               |
       global corridor / subgoal sequence
               |
 rolling static + elevation + dynamic + social maps
               |
 observed-first A* corridor + deterministic path tracking
               |
 short-horizon MotionCandidate
               |
 independent safety kernel and gateway
```

The current rolling grid and A* should remain the initial actuating baseline. Add
observed-first receding-horizon behavior: plan toward the true goal, execute only
to the furthest safely observed/reachable frontier, reobserve, and replan. This
resolves the current mismatch where A* can use penalized unknown space but the
tracker refuses an uncleared segment.

The task/resource/preemption layer first selects the active behavior owner. A
behavior-scoped `GoalManager` then arbitrates its semantic approach, route-memory
proxy, exploration frontier, progress-making recovery, and crossing-staging
subgoals using system-owned source policy. It is not a second behavior arbiter.
Follow formation is a moving constraint/manifold rather than a forced sequence of
static poses, but it shares task revision, local-planner admission, and safety.

Every translation-bearing target must use the obstacle-aware local planner. A pure
scan rotation may use a bounded sensing controller, and stop/collision reflexes or
a tightly bounded system-owned escape primitive may remain available when global
goal planning is unavailable. Any escape remains inside local autonomy, uses a
fresh observed-space snapshot and the same hard traversability/geofence governor,
and never authorizes blind reverse. All still pass through task ownership, command
arbitration, input health, and final safety.

A regulated pure-pursuit style tracker is a reasonable next deterministic
controller challenger because it can incorporate curvature, clearance, and
goal-approach regulation. Promote it only against replay and simulator evidence;
the current tracker remains the rollback baseline. MPPI or learned trajectory
models should begin in shadow mode and may be promoted only as bounded candidates
under the same maps, envelope, verifier, and safety kernel.

#### Global continuity and route memory

The persistent place graph should record traversed, evidence-backed edges and
semantic landmarks. Nodes bind to map/submap IDs, transform revisions, and
covariance—not unversioned raw MAP coordinates. It proposes route topology; live
local perception determines whether an edge remains traversable. Loop closure or
relocalization updates or invalidates affected anchors explicitly, and large jumps
invalidate route hypotheses until reanchored.

Route memory complements SLAM; it does not replace metric localization, current
obstacle sensing, or terminal evidence.

#### Road and geofence authority

Hard keepouts and crossing state must be enforced at three boundaries:

1. goal admission rejects lethal/unauthorized regions **and** any proposed global
   corridor or connected-component transition that would cross a keepout;
2. the planner rasterizes the keepout as lethal cost;
3. the final safety kernel predicts footprint intersection and stops.

Road crossing is a hard deny in the first ODD. A later crossing authorization must
require an admitted route-specific ODD/capability manifest, commissioned
localization and map provenance, explicit operator policy, bounded revisioned
authority, and automatic expiry. A voice command alone can never expand the ODD.

Flat private routes can still contain curbs, stairs, drainage edges, and drop-offs.
Traversability/negative-obstacle evidence is therefore a required sensor contract,
hard planner cost, final safety disposition, and capability-admission item. The
current `low_viewpoint/` experiments are evidence seams, not live authority.

#### Recovery ownership

Local navigation owns bounded, cause-specific micro-recovery within a system budget
and emits a typed blocked cause when that budget is exhausted. `MissionSupervisor`
alone owns alternate instance, approach, route, semantic replan, clarification, or
termination. The two layers share one budget ledger so nested retries cannot
double-spend time, distance, or attempts.

### 8.7 Owner following and social navigation

Owner following is not ordinary target pursuit. It requires a persistent enrolled
identity and an explicit belief state:

```text
LOCKED -> OCCLUDED -> SEARCHING -> LOCKED
   |          |           |
   +----------+-----------+--> AMBIGUOUS / LOST -> HOLD + clarify/notify
```

Only a sufficiently healthy `LOCKED` belief permits translational following in the
first ODD. Nearest-person fallback is never an identity policy. `OCCLUDED` stops
translation and permits only explicitly safe bounded rotation/search; last-known
trajectory and covariance guide where to look, not where to drive. A later
`PREDICTED_LOCK` policy could permit low-speed, time/covariance-bounded translation,
but requires separate commissioning. Search never silently binds to a different
person.

Formation is a first-class task with side, distance band, visibility, yield,
passing, and conversation-attention policies. Dynamic prediction should begin with
a timestamped constant-velocity model plus uncertainty. More expressive predictors
may supply multimodal costs, but geometric safety and identity state remain
deterministic authorities.

Social comfort should be represented as costs and behavior policy, while collision
and geofence rules remain hard constraints. If comfort and mission progress conflict,
the companion slows, yields, waits, reroutes, or asks—never weakens a hard gate.

### 8.8 Final safety governor and physical gateway

#### Final safety governor

Safety dispositions have a monotone policy precedence:

```text
PASS < CLAMP < HOLD < STOP < LATCHED_STOP
```

| Disposition | Allowed motion | Task effect | Persistence/reset |
| --- | --- | --- | --- |
| `PASS` | Candidate unchanged | Continue | Recomputed each cycle |
| `CLAMP` | Reduced, possibly to zero | Continue with degraded-progress event | Recomputed each cycle |
| `HOLD` | Exact zero | Keep task pending and re-evaluate | Clears only on fresh satisfying evidence |
| `STOP` | Exact zero | Interrupt/fail/pause according to typed cause | Requires an explicit non-latched recovery transition |
| `LATCHED_STOP` | Exact zero | Task cannot resume | Authorized reset plus required fresh evidence |

Each monitor emits axis-specific motion constraints plus a lifecycle disposition,
cause, evidence reference, and reset obligation. Composition intersects the motion
constraints and separately selects the most restrictive lifecycle precedence; a
zero-valued `CLAMP` is still not lifecycle-equivalent to `HOLD` or `STOP`. A search
rotation is a separate, explicitly admitted sensing intent evaluated against fresh
sector evidence—not motion hidden inside `HOLD`. The planner consumes the same
immutable footprint, stopping model, speed regime, person bands, and geofence
versions used by the final governor, but the governor recomputes its verdict
independently after shaping.

The system must settle the open physical-policy decisions before commissioning:

- whether any rotation is permitted for each stale/invalid input class;
- the conservative pose-error reserve used by terminal and geofence checks;
- directional swept-footprint/closing relevance for collision braking;
- exactly which faults latch and which evidence clears them;
- how UI focus/blur commands interact with an admitted autonomous mission.

#### Native sole-writer gateway

The gateway is a small native process with one robot-network credential and one
vendor command writer. It owns:

- boot epoch and restart-disarmed state;
- explicit arm/disarm and capability manifest;
- one authenticated local client lease;
- strictly monotonic command sequence;
- short command TTL and watchdog;
- local velocity/acceleration/yaw caps;
- an allowlisted, versioned posture/gesture capability catalog with bounded
  parameters/duration, base-stationary preconditions, cancellation, and completion
  feedback;
- immediate stop dominance and `StopMove`;
- fresh controller feedback and a stationary witness;
- bounded local audit ring and health output.

It accepts only the versioned gateway contract over bounded local IPC. Unknown
fields, version mismatch, expired commands, wrong boot epoch, writer conflict,
missing feedback, or watchdog expiry cause HOLD/STOP, never permissive fallback.
Gateway velocity/acceleration handling cannot weaken the received safety ceiling:
comfortable slew may limit increases, but a new clamp, HOLD, STOP, or lower envelope
is an instantaneous hard ceiling, bypasses comfortable deceleration, and resets the
relevant shaper state. Exact zero remains exact zero at the vendor write.

`GatewayActionV1` is a distinct resource/lease path, not a way to smuggle raw joints
around velocity safety. It is mutually exclusive with incompatible base motion and
inherits STOP dominance. Until that action path and each capability profile are
implemented and physically commissioned, physical pose, trajectory, gesture, and
decorative expression remain unsupported even if their simulator versions exist.

“Short TTL” is an evidence requirement, not a convenient constant: worst-case
candidate age, IPC delay, gateway scheduling/watchdog period, vendor braking
latency, and sensor/localization uncertainty must fit inside the commissioned
stopping envelope at the active speed regime. The gateway intentionally rejects
hot concurrent writers. Controlled handover requires exact zero/stationary witness,
disarm, lease release, a new boot/arm epoch, and then revalidation; availability
never justifies overlapping authority.

The gateway is a software isolation boundary, not a certification claim. The first
physical ODD still requires an independent operator stop. A later public product
may move this contract to dedicated safety compute or an MCU without changing the
semantic application.

### 8.9 Inference broker

Conversation, planning, summarization, embeddings, and perception compete for GPU
and cancellation state. One broker should expose role-scoped queues/endpoints with:

- deadline and turn/task revision;
- priority and maximum concurrency;
- role-scoped cancellation rather than one global active handle;
- model/config/hash provenance;
- structured-output validation and one bounded repair attempt;
- circuit breaker, overload disposition, and deterministic fallback;
- token/cache/GPU budget metrics.

Sharing weights can remain the memory-efficient default. Separate model processes
should be introduced only when measured tail latency, cancellation interference,
or failure isolation justifies the cost. Logical isolation is mandatory even when
weights are shared.

The first ODD assumes local inference for private audio/vision and must never make
STOP, final safety, or continuation of an already admitted deterministic task
depend on cloud reachability. Any optional remote reasoning needs an explicit data
egress/retention policy, consent, redaction, deadline, and local degraded behavior;
its output remains an untrusted semantic proposal.

### 8.10 Observability, replay, and evaluation

Every event should carry a common causal envelope:

```text
run/session -> turn/generation -> task/revision -> step/attempt
            -> world snapshot/evidence sequence
            -> goal/motion candidate -> safety disposition
            -> gateway boot/command/feedback -> terminal witness
```

Also record monotonic/wall-clock mapping and release, config, model, calibration,
map, and capability hashes. Every refusal, clamp, retry, correction, and success
must be explainable from the trace.

Telemetry uses a bounded nonblocking queue with drop counts. Logging, rotation,
serialization, storage, model serving, and remote export must never be a dependency
of control or gateway liveness. Audio/transcripts/entity identities need explicit
PII classes, redaction, retention, export/delete, and a real logging kill switch.

Promotion follows an evidence ladder:

1. contract/unit/property/fuzz tests;
2. deterministic simulator scenarios and mutation tests;
3. recorded sensor/bag replay, including counterfactual challengers;
4. fault injection: process kill/stall/restart, clock jump, dropped/reordered
   evidence, writer conflict, model/logging/storage failure;
5. hardware-in-the-loop gateway and sensor timing;
6. supervised robot commissioning with independent stop;
7. repeated first-ODD missions with confidence intervals;
8. only then, separately scoped ODD expansion.

Conversation evaluation also needs held-out human review for helpfulness,
interruption, memory correctness, explanation truth, repair behavior, and comfort.
Automated parse/safety fixtures remain necessary but are not a proxy for companion
quality.

### 8.11 Configuration, packaging, and capability admission

The target configuration system should have:

- a strict, versioned root schema with unknown-key rejection;
- migrations and explicit source provenance;
- one derivation path for robot profile, speed regime, footprint, stopping model,
  social bands, and navigation limits;
- capability declarations for required sensors, frames, models, maps, and gateway;
- validated feature dependencies—for example, detection lock-on cannot start
  without verification-on-approach;
- signed release/config/model/map/calibration manifests for physical deployment;
- exact source-to-packaged-asset parity with generated digests;
- a build-wheel, install-in-empty-environment, runtime-resolution smoke test.

Before N27, the packaged navigation config had a 0.45 m/s cap where canonical source
had 0.9 m/s, a 400-tick timeout where source had 200, a 28-degree grid alignment
entry where source had 55, and omitted newer perception, route-memory, predictive,
and person-band configuration. N27 regenerated those assets and added a hard
zero-diff/manifest gate, so those files are now byte-identical. The nightly
build/install-wheel test remains unexecuted on this host; it must pass before calling
wheel behavior verified.

### 8.12 Maintainable module boundaries

Refactor incrementally behind existing contracts; do not rewrite working behavior.

| Current concentration | Extracted owner | Responsibility |
| --- | --- | --- |
| `RobotRuntime` | `InteractionRuntime` | Audio, duplex, committed turns, speech delivery |
| `RobotRuntime` | `CognitionCoordinator` | Routing, model lanes, compilation/admission |
| `RobotRuntime` | `WorldModel` | Evidence ingestion, association/beliefs, history, and immutable projections |
| `RobotRuntime` | `MissionSupervisor` | Budgets, recovery, clarification, narration events |
| `RobotRuntime` | `TaskExecutive` | Sole owner of task records, resource leases, checkpoints, and task events |
| `RobotRuntime` | `TaskActivityAdapter` | Map admitted posture/gesture tasks to `ActionRequestV1` and verified feedback |
| `RobotRuntime` | `BehaviorCoordinator` | Subordinate activity/expression overlays only |
| `RobotRuntime` | local-autonomy/actuation-admission sidecar | High-rate envelope, action admission, safety dispositions, and the sole gateway client session |
| `DirectiveNavigator` | `NavigationMission` | State transitions and mission progress only |
| `DirectiveNavigator` | `GroundingService` | Target/relation hypotheses and active perception |
| `DirectiveNavigator` | `GoalManager` | Behavior-scoped proposals, revision/system TTL/lethal admission |
| `DirectiveNavigator` | local-autonomy sidecar | High-rate local maps, route tracking, and micro-recovery candidates |
| `DirectiveNavigator` | `ArrivalVerifier` | Independent semantic/geometric terminal witness |

Keep a single explicit composition root that wires these ports. State has one
owner; other components receive snapshots/events instead of inspecting parallel
mutable dictionaries. This gives the benefits of modularity without distributed
systems overhead inside the semantic application.

## 9. Failure behavior

| Failure | Required behavior |
| --- | --- |
| Conversation/planning model unavailable | STOP and closed skills still work; active safe task may continue; user gets an honest degraded-mode message. |
| Planner exceeds deadline | Discard by turn/task revision; do not hold control resources while inference runs. |
| Sensor missing/stale/uncalibrated | Relevant positive motion becomes HOLD/STOP/LATCHED_STOP per explicit policy; never synthesize a simulator-like default. |
| Localization unhealthy or jumps | Stop translation, invalidate affected goals/routes, re-localize or request help; any allowed rotation is explicitly policy-bound. |
| Owner identity ambiguous | HOLD, preserve hypotheses, search/clarify; never switch to nearest person. |
| Map/geofence provenance invalid | Reject autonomous movement in affected region. |
| Python process stalls or dies | Gateway lease expires and issues stop. |
| Gateway restarts | Comes up disarmed with a new boot epoch; old commands cannot replay. |
| Logger/storage/export fails | Control continues; bounded queue drops are counted. The gateway retains only its local command/disposition/fault ring; higher-level semantic/evidence history may be incomplete and must be reported as such. |
| ROS discovery/node failure | Required evidence expires, local safety stops refreshing positive authority, and the gateway independently stops on TTL. |
| Configuration or schema mismatch | Refuse startup/arming with a precise diagnostic. |
| Learned candidate is malformed/late | Reject it and use the deterministic baseline or HOLD; learned failure cannot weaken safety. |
| Resource/precondition wait expires | Emit a typed blocked event; mission supervisor retries, clarifies, or terminates within budget. |
| Terminal evidence disagrees | Do not claim arrival; reobserve, adjust approach, or explain uncertainty. |

## 10. Important design tradeoffs

| Decision | Chosen tradeoff | Why it is better for the objective | Cost accepted |
| --- | --- | --- | --- |
| Hybrid agent vs end-to-end motor model | Semantic model proposals plus deterministic execution/safety | Auditable, replaceable, revision-safe, and compatible with strong conversation models | More contracts and explicit skill coverage |
| Modular Python + sidecars vs Python monolith | Keep semantic modules together; split real-time/vendor/ROS/GPU fault domains | Preserves tests and iteration speed while isolating physical control | IPC, deployment, clock, and health contracts |
| Selective ROS vs full ROS/Nav2 rewrite | Use ROS for infrastructure and selected algorithms, not final authority | Gains sensors/tf/bagging/localization without discarding custom semantic/task behavior | Two ecosystems to integrate |
| Thin leaf packages vs eager convenience barrels | Production imports leaves; any public barrel is lazy and compatibility-only | Restores true module/capability boundaries and prevents optional cycles from disabling required behavior | More explicit imports and migration work |
| PlanSketch vs model-authored PlanIR | Model chooses goal/skills; compiler owns mechanics | Smaller attack/error surface and less prompt-contract drift | Compiler/skill registry must be maintained |
| Shared model vs separate models | Shared weights behind role-isolated broker first | Lower GPU memory; retain independent deadlines/cancellation | Scheduling complexity and possible contention |
| Classical actuating baseline vs learned control | Deterministic planner/controller actuates; learned systems challenge/propose | Data-efficient, explainable rollback and safe shadow evaluation | May lag learned methods in complex scenes initially |
| Goal regions vs point targets | Relation- and uncertainty-aware regions | Matches language and prevents false precision/arrival | More grounding and terminal geometry |
| Persistent world model vs mission-local state | Versioned beliefs and place/task history | Enables object permanence, recovery, explanation, and long-range autonomy | Invalidation, privacy, schema, and storage complexity |
| Behavior-scoped goal manager vs ad hoc subcontrollers | Translation-bearing navigation subgoals share revision, system TTL, lethal, and planner checks after task ownership is selected | Prevents exploration/recovery/memory bypasses without creating a second behavior arbiter | Requires controller migration and a separate moving-formation contract |
| Independent final gate vs one shared planner check | Share envelope data, recompute final disposition | Defense in depth against planner/config/controller mistakes | Some intentional duplicated computation |
| Route memory vs full SLAM | Use both; topology proposes and live metric perception verifies | Long-horizon familiarity without mistaking memory for current geometry | Persistence and reanchoring work |
| Semantic object map vs metric SLAM | Keep distinct linked products | Names/objects have different uncertainty, decay and privacy semantics from robot pose/free space | Transform/revision association between stores |
| UVC vs RGB-D first physical sensor | Prefer calibrated RGB-D for metric grounding; retain UVC for dialogue/appearance experiments | Avoids pretending monocular RGB provides the current depth contract | Sensor cost, power, USB bandwidth and calibration |
| Unitree Sport vs low-level joint control | Use high-level Sport velocity for the first ODD | Buys vendor balance/gait and drastically narrows the physical assurance problem | Less gait/expression authority and opaque onboard behavior |
| Microservices vs modular monolith | Few process boundaries, strong in-process ports | Avoids distributed-system complexity where it buys no safety/timing isolation | Requires disciplined ownership inside Python |
| Autonomous initiative vs user authority | Autonomous subgoals only inside a bounded authorized mission in the first ODD | Enables recovery and mixed initiative without inventing positive-motion authority | More authorization, revocation, and narration state |
| One universal snapshot vs linked cadences | High-rate local-motion projections plus slower semantic history | Keeps control fresh while making cross-revision reasoning detectable | Transform/revision bookkeeping |
| Uniform task lifecycle vs expressive responsiveness | Task-manage consequential action; keep decorative expression subordinate and expiring | Consistent authority without turning every nod into durable workflow | Two clearly constrained lifecycle classes |
| Sole writer vs hot failover | Restart-disarmed controlled handover only | Eliminates concurrent-writer ambiguity and stale replay | Brief loss of availability during handover |
| Local vs remote inference | Hybrid: local deterministic safety/closed intents and optional deadline-bounded hosted dialogue; larger local planning may remain | Predictable safety degradation while retaining strong conversation | Two provider paths, cloud privacy/cost/connectivity and local compute pressure |
| Buy EDU now vs after product readiness | Release only as a supervised R&D instrument after integrity/procurement gates | Gains physical feedback before the entire autonomy stack is finished without calling it deployment-ready | Capital tied up before a companion product exists; operator and lab obligations begin immediately |
| Read-only tools vs trusted facts | Keep source/trust labels; tool text informs dialogue but cannot authorize or establish physical truth | Contains prompt injection and stale external data | Extra provenance and synthesis policy |

## 11. Delivery sequence and promotion gates

### Immediate prioritized lanes from this audit

| Priority lane | Action | Exit evidence |
| --- | --- | --- |
| IG-1 hermetic CI | Track/verify the minimal licensed Unitree asset closure and make every aggregate stage failure-complete | Fresh tracked-only checkout emits complete JSON and all independent stage results on green, missing-asset, tampered-asset and exploding-stage cases |
| IG-2 true Python contract | Fix `RetainedEvent`, settle 3.10/voice dependencies, declare a bounded range and test every claimed minor | Fresh installs, imports, equal node-ID sets and assigned behavioral lanes across the required matrix; no collection-error escape or version-specific node loss |
| IG-3 module/capability integrity | Thin `core`, `navigation`, `navigation.envs` and `instructnav` initializers; migrate product leaf imports; remove semantic soft-degrade | Leaf imports avoid pipeline/simulator/InstructNav, and product startup is hard-red if required semantic navigation is unhealthy |
| IG-4 independent closeout | Verify exact integrated tree locally and in hosted Actions; record artifacts/branch protection | Full commit gate and scheduled/slow evidence green from clean checkout, with exact environment/dependency identity and retained reports |
| PR-1 procurement readiness | Freeze Go2 EDU SKU/firmware/SDK, sensor/compute/mount/network/power BOM, vendor acceptance window, operator and hazard plan | Signed acceptance checklist, independent stop/tether and lab ready, budget explicitly classifies robot as R&D equipment |
| HW-1 physical substrate | Build the native sole-writer gateway and backend-neutral observation/replay contracts | Restart-disarmed fault campaign plus read-only Unitree/sensor replay; no autonomous body command yet |
| HW-2 localization and low-speed commission | Time-sync/calibrate sensors, provide `map→odom→base_link`, commission axes/frame/modes and stopping | Tethered one-axis then bounded velocity tests; ATE/RPE/health/dropout evidence; measured p50/p95/p99 stops and independent stop |
| PV-1 physical perception shadow | Wire RGB-D, detector/map/owner tracker without motion authority | Physical precision/recall, position error, owner/stranger ROC, ID switches, duplicate/name error, freshness and restart metrics pass frozen thresholds |
| AU-1 supervised mobility | Point-goal then semantic navigation in a bounded indoor ODD | Repeated multi-room missions, localization-loss recovery, dynamic-person course and terminal witness with zero unresolved hard event |
| CP-1 companion behavior | Add physical following, owner recovery, ego-noise voice and governed personalization | Cohort/through-air evidence, safe give-up, correction, consent/delete audit and operator handoff pass |

IG-1 through IG-4 are today's release-integrity block and are specified in the
linked integrity TODO. Interface design, BOM research and replay work may proceed
in parallel, but feature promotion, purchase approval and physical autonomous
motion do not bypass them. Later gates overlap only where their authority inputs
are already admitted; subsystem test counts never substitute for predecessor
evidence.

### Phase 0 — close release integrity, then freeze physical boundaries

Run IG-1, IG-2 and IG-3 in isolated worktrees with one integrator, then IG-4 on
the exact combined tree. Preserve the active P1/P2 work and do not narrow the
denominator to manufacture closure.

**Release/safety truth:**

- Provision and validate every required scene asset from a tracked-only checkout;
  independently pin upstream revision, license, size and digest.
- Make every gate stage exception-contained and always emit the complete report.
- Fix the 3.11 protocol import, 3.10 voice dependency contradiction and cross-minor
  node-ID parity.
- Make package barrels thin and required semantic capability startup-fatal.
- Make packaged/source config and prompts generated, zero-diff artifacts.
- Resolve no-provider pose fallback, terminal uncertainty reserve,
  input-class-specific rotation/HOLD behavior, and directional collision relevance;
  encode each decision as property/mutation evidence.
- Reject unsafe feature-flag combinations and uncommissioned capability profiles at
  startup.

**Physical authority:**

- Freeze the gateway and observation contracts at design/replay level after import
  and composition boundaries are healthy.
- Implement `RobotGatewayV1`, bounded IPC, restart-disarmed state, lease/TTL,
  stop/stationary witness, and a capability-admitting physical launcher.
- Implement and commission `GatewayActionV1` for any physical posture/gesture kept
  in scope, or make those capabilities fail closed as unsupported.
- Revoke robot-network credentials/vendor command access from legacy ROS,
  direct/debug Dog, UI, and Python paths; any retained physical command must route
  through the gateway before the first HIL motion.
- Run property/fuzz/fault campaigns for sequence, epoch, expiry, writer conflict,
  IPC corruption, process kill/stall/restart, and clock discontinuity.
- Begin gateway HIL/bench and explicitly armed single-axis commissioning only after
  the procurement/lab/safety gate admits it; do not wait for advanced navigation
  once that boundary is safe.

**Gate:** the clean commit and hosted gate are complete, not merely non-crashing;
no Parcel physical autonomous motion occurs without the gateway. Source/wheel/
third-party closure is exact; required capabilities cannot soft-disable; the
gateway's worst-case age/watchdog/braking chain fits the commissioned envelope and
stops independently on client death or command expiry.

### Phase 1 — establish the sensor, world-evidence, and localization spine

- Generalize the existing typed camera/capture contracts into
  `SensorFrameV2`/`SensorSource` and deterministic rosbag/file replay.
- Make one physical composition root consume the P1-A RGB-D backend, Unitree
  telemetry, LiDAR, IMU, controller state and clock mapping; normalize all of them
  into evidence envelopes and a synchronized backend-neutral `RobotObservationV2`.
- Implement `WorldModel` ownership, belief updates, immutable query projections,
  and the revision-linked high-rate `NavigationSnapshotV2` path.
- Benchmark at least two established odometry/localization/SLAM providers on the
  same bags; add timestamped `T_map_odom`, covariance, health, jump/relocalization
  events and explicit no-provider failure. Report ATE, RPE, drift per meter, lost
  rate, recovery time, latency and compute.
- Transform MAP goals into ODOM at the observation timestamp and preserve
  covariance; test delayed/missing transforms and loop-closure jumps.
- Remove oracle fields and simulator defaults from physical profiles.
- Remove or archive the now-credentialless legacy ROS JSON command topics and
  direct/debug Dog physical paths after their gateway replacement is proven.
- Interleave bag replay, HIL timing, bench sensors, and bounded robot checks for each
  new seam rather than deferring hardware feedback.

**Gate:** replay produces deterministic, internally coherent decision snapshots;
physical profiles cannot arm without commissioned capabilities. Sensor/ROS failure
expires motion authority and the gateway then stops on TTL. Failure of a
non-safety UI, GPU consumer, logger or optional store must not block
gateway/control liveness and need not stop a task **only if** the remaining
commissioned capabilities and mandatory evidence/retention policy still authorize
it. Loss of a safety-relevant perception provider or required evidence sink revokes
or degrades the affected capability.

### Phase 2 — close the conversational task loop

- Select `plan_sketch_v1` as the model default and align the planner prompt.
- Fix executive-level retries and admission/grounding/resource/execution deadlines.
- Route every consequential non-emergency physical action through `TaskExecutive`.
- Add `CommittedTurnV1`, `CommandAuthorityV1`, `TurnDispositionV1`, the inference
  broker, and one dialogue-act sequencer.
- Add controller-certified checkpoint events, task-aware narration, and bounded
  mission repair.
- Add query-aware, governed conversational/episodic memory and migrate dialogue,
  planning, semantic/global navigation, and terminal-verification reads to
  `WorldModel` projections. Local planning/safety continue to consume the direct,
  bounded `NavigationSnapshotV2` path.
- Pass typed navigation intent, grounding, and execution-goal semantics end to end.
- Add a bounded two-pass read-only tool loop with trust labels.
- Wire AEC, streaming partial ASR, ducking, and priority system speech.

**Gate:** correction, cancellation, pause/resume, failure explanation, clarification,
and recovery scenarios are revision-safe under delayed/reordered model outputs; no
partial, tool content, or untrusted principal can authorize motion. Replay detects
any consumer that mixes incompatible world revisions.

### Phase 3 — build and repeatedly field-check navigation capability

- Implement evidence-independence-safe detection/tracking and owner belief/re-ID.
- Make goal arbitration continuous within the task-selected navigation behavior;
  preserve a distinct moving-formation contract.
- Promote observed-first local navigation and route all translation-bearing
  frontiers/recovery targets through it.
- Persist semantic/place memory with map/submap revisions, change detection, and
  relocalization support.
- Enforce the private-ODD geofence and negative-obstacle/drop-off authority; keep
  road crossing hard denied.
- Add cause-aware recovery, alternate instance/approach selection, elevation, and
  uncertainty-aware social prediction.
- Evaluate regulated tracking and MPPI/learned challengers in shadow/replay.
- Interleave replay with supervised low-speed robot scenarios for perception,
  localization, stopping, owner occlusion, and terminal evidence.

**Gate:** held-out replay, simulator, and bounded robot evidence show no
duplicate/correlated-evidence success, identity swap, false arrival, geofence or
drop-off violation, or stale-revision motion; promoted challengers beat the
baseline without weakening hard gates.

### Phase 4 — supervised robot commissioning

- Freeze the integrated commissioned sensor, frame, timing, footprint, stopping,
  controller-feedback, stationary-witness, audio, and independent-stop manifest.
- Progress from the earlier single-axis and bounded low-speed checks to static
  obstacles, dynamic people, owner occlusion, conversation during motion,
  corrections, and multi-stage missions.
- Record every run with `does_not_prove` and environment/operator metadata.

**Gate:** repeated first-ODD missions meet declared safety, task, interaction, and
latency thresholds with confidence intervals and no unresolved hard-safety event.

### Phase 5 — learn only demonstrated residuals and expand cautiously

- Train or promote a learned component only for a repeatable residual failure with
  a suitable dataset and deterministic fallback.
- Expand one ODD dimension at a time: lighting, weather, terrain, crowd density,
  route novelty, or supervision—not all together.
- Consider a dedicated safety appliance only after gateway contracts and hazards
  are proven enough to justify the hardware split.

**Gate:** independent review and a new hazard/evidence package for every ODD claim.

## 12. Product acceptance scorecard

Exact thresholds belong to an evidence-dated release/ODD specification, but the
architecture should make these measures unavoidable:

| Objective | Measures |
| --- | --- |
| Conversational capability | Human-rated coherence/helpfulness, reference and correction accuracy, interruption success, truthful state reporting, memory precision/forget compliance, first-response and repair latency tails |
| Autonomous task capability | Goal completion, clarification efficiency, recovery success, intervention rate, time/distance/energy budget adherence, stale-revision rejection |
| Navigation truth | No false arrivals; terminal-witness completeness; semantic relation accuracy; route progress; identity continuity; pose/geofence uncertainty reserve |
| Social behavior | Owner-band/formation time, stranger clearance, yield/passing comfort, deadlock rate, unnecessary-stop rate |
| Hard safety | Collision/keepout/authority violations, stop latency and distance, stale-input dispositions, gateway watchdog/lease behavior, independent-stop success |
| Robustness | Performance under sensor loss, occlusion, relocalization, model outage, network/process/logging failure, and config mismatch |
| Portability | Capability-manifest admission and identical contract/eval results across simulator, replay, Unitree, and a second robot adapter |
| Reproducibility | Release/config/model/map/calibration hashes; deterministic replay; source/wheel parity; causal trace completeness |

Hard-safety failures are never averaged away by conversational or task-quality
scores. Likewise, a zero-collision stationary robot is not capable; progress,
success, and comfort metrics must be reported alongside safety.

## 13. Non-goals for the next architecture increment

- Unsupervised public-street, road, stair, hill, or dense-crowd autonomy.
- Direct token-to-velocity, token-to-joint, or VLA-to-actuator control.
- Replacing Unitree Sport's onboard gait/balance controller.
- A whole-codebase C++/Rust or ROS rewrite.
- Broad reinforcement learning before a measured residual failure exists.
- Treating a container, ROS QoS, simulator collision counter, or software E-stop as
  physical safety certification.
- Treating route memory, an external map, or a language model assertion as current
  free-space truth.
- Persisting private audio, identity, or profile facts without explicit policy and
  user controls.

## 14. Open decisions that require explicit ownership

1. For each invalid input class, may a separate bounded sensing-rotation intent be
   admitted, and under what fresh observed sector and duration, or is exact HOLD
   required?
2. What pose/covariance reserve is required for arrival and geofence decisions in
   the first ODD, and for crossing only in a later admitted ODD?
3. What swept-footprint and closing-relevance rule replaces the current scalar
   collision behavior without weakening safety?
4. What operator/UI actions pause an admitted mission versus cancel it?
5. What owner enrollment, re-identification, consent, and data-retention policy is
   acceptable?
6. Which physical sensor suite and localization implementation define the first
   supported capability manifest?
7. Which voice principal/authorization rules allow positive motion in a multi-person
   environment?
8. What task classes can resume after process restart, relocalization, or gateway
   re-arm?
9. What exact ODD-specific safety and interaction thresholds block release?
10. Does the supported interpreter contract remain CPython 3.10–3.14, or should
    base, voice, perception and Jetson deployment publish distinct tested ranges?
11. Which Go2 EDU SKU, firmware, battery, compute, camera/LiDAR, independent stop,
    mounts and network topology form the accepted R&D bill of materials?
12. Is metric SLAM delegated to an established provider (and which one), or does
    the team accept the cost of owning a localization/map stack?

These choices should become versioned ADRs and executable policies. They should not
remain magic constants or be silently inferred from a convenient simulator behavior.

## 15. Related durable designs and evidence

- [Design decisions](DESIGN_DECISIONS.md)
- [Retired 2026 layered-architecture redirect](REDESIGN_2026_ARCHITECTURE.md)
- [Companion navigation architecture](COMPANION_NAVIGATION_ARCHITECTURE.md)
- [Navigation algorithm decision](NAVIGATION_ALGORITHM_2026.md)
- [Runtime concurrency and clocks](RUNTIME_CONCURRENCY_AND_CLOCKS.md)
- [Duplex dual-stream design](DUPLEX_DUAL_STREAM_DESIGN.md)
- [Voice-agent evaluation and replaceable provider architecture](VOICE_PROVIDER_ARCHITECTURE.md)
- [Attention steering design](ATTENTION_STEERING_DESIGN.md)
- [Strata/generalization plan](STRATA_GENERALIZATION_PLAN.md)
- [Retired hardware-portability redirect](HARDWARE_PORTABILITY_AUDIT.md)
- [Current integrity-gate corrective TODO](../scrum/20260822/INTEGRITY_GATES_TODO.md)
- [Archived legacy implementation matrix](archive/LEGACY_IMPLEMENTATION_STATUS_2026-08-04_TO_09.md)
  — a retired August 4-9 historical record, never current authority
- [Accepted production convergence plan](../scrum/20260812/task_1/PRODUCTION_COMPANION_PLAN.md)
- [Current FIX-A validation record](../scrum/20260815/task_1/FIXA_STATUS.md)
- [Companion navigation result ledger](../evals/companion_nav/results/README.md)
- [Planner quality results](../evals/companion/planner_quality_v2/results/README.md)
- [Conversation quality results](../evals/companion/conversation_quality_v1/results/README.md)
- [Personal conversation results](../evals/companion/personal_convo_v1/results/README.md)
- [Duplex results](../evals/companion/duplex_v1/results/README.md)

### 15.1 External primary engineering anchors

- [Unitree Go2 product/EDU specifications](https://www.unitree.com/go2/) — platform
  mass, payload, speed, battery and development-compute options must be confirmed
  against the exact purchased SKU and quotation.
- [Unitree SDK2 Python](https://github.com/unitreerobotics/unitree_sdk2_python) and
  [SDK2 C++ Sport client](https://github.com/unitreerobotics/unitree_sdk2/blob/main/include/unitree/robot/go2/sport/sport_client.hpp)
  — the high-level `Move`/`StopMove` boundary used by Parcel. Unitree's own examples
  warn against conflicting high- and low-level command modes; Parcel's first ODD
  keeps Sport as the sole locomotion mode.
- [Unitree MuJoCo](https://github.com/unitreerobotics/unitree_mujoco) — useful
  official simulation assets and DDS-compatible development support, not evidence
  that Parcel's current kinematic simulator reproduces Go2 dynamics or stopping.
- [Nav2 concepts](https://docs.nav2.org/concepts/) — lifecycle supervision and the
  standard `map→odom→base_link` separation that the physical composition lacks.
- [SLAM Toolbox documentation](https://docs.ros.org/en/humble/p/slam_toolbox/) — a
  candidate 2-D pose-graph/localization provider requiring scans and valid odometry
  transforms; it is an integration option, not current Parcel code.
- [OpenAI GPT Realtime 2.1](https://developers.openai.com/api/docs/models/gpt-realtime-2.1)
  and [Realtime call/session API](https://developers.openai.com/api/reference/python/resources/realtime/subresources/calls/methods/accept)
  — current official support for audio/text sessions and tools. Parcel still owns
  tool schemas, authorization, budgets and every physical admission decision.

## 16. Final architectural judgment

Parcel already has the right safety philosophy and many of the right components.
Its best work is the semantic-model boundary, revision-safe task admission,
deterministic executive, independent semantic-arrival verification foundation, and
layered final motion gates. Replacing those with a more end-to-end agent would be a
regression.

The present program milestone is not “autonomous companion dog.” It is
**hermetic release integrity plus a safely commissioned, observable Go2 research
platform**. The integrity milestone comes first: until a clean checkout runs the
same admitted product across its claimed Python versions and cannot silently drop
semantic navigation, every higher capability statement has an unstable
denominator.

The path to a genuinely capable conversational navigator is to make those pieces
coherent end to end:

- one committed turn and authorization contract;
- one hermetic, failure-complete release gate and explicit capability admission;
- one task lifecycle for all consequential non-emergency physical work;
- one synchronized physical observation and `map→odom→base_link` localization spine;
- one evidence-enveloped, revisioned world model;
- one typed semantic goal through grounding and navigation;
- one behavior-scoped authority for translation-bearing navigation goals and
  independently verified completion;
- one bounded mission-repair loop that can explain itself;
- one immutable safety envelope with an independent final disposition;
- one native physical command writer;
- one causal replay/evaluation record.

That design gives models more useful context and more opportunities to propose
intelligent repairs while giving them no additional ability to manufacture truth or
motor authority. It is the best balance of capability, safety, portability,
testability, and incremental delivery for the stated objective. The current code is
ready to benefit from an EDU robot as supervised R&D equipment after the integrity
and lab gates; it is not ready to operate that robot as a semiautonomous companion.

---

## Appendix A — Robotics textbook: the system mental model

### A.1 A robot is a feedback system, not a chatbot with legs

A useful first model of Parcel is a closed loop:

```text
physical world -> sensors -> state/evidence -> estimation -> goals/plans
       ^                                                    |
       |                                                    v
       +--- body/contact <- actuators <- admitted command <- controller
```

The world changes while computation runs. Sensors are delayed and noisy. The
body has momentum, actuator limits, balance constraints, and contacts. People do
not follow the robot's plan. A correct decision made from old evidence can be an
unsafe command now. Robotics therefore depends on feedback: repeatedly observe,
estimate, decide, act for a short horizon, and observe the result.

Conversation adds another loop rather than replacing this one:

```text
owner utterance -> committed meaning -> authorized task -> physical loop
       ^                                                   |
       +------ explanation / clarification / result <------+
```

The task loop operates in symbols such as “owner,” “bench,” “next to,” and
“wait.” The physical loop operates in metres, radians, seconds, velocities,
forces, contact states, and uncertainty. Parcel's central architectural job is
to translate between those domains without allowing a plausible sentence to
become physical truth or motor authority.

### A.2 Plant, controller, estimator, planner, and executive

Robotics vocabulary is easier when each term has one job:

| Concept | General meaning | Parcel realization |
| --- | --- | --- |
| Plant | The physical system being controlled | Go2 body, onboard locomotion controller, motors, contacts and environment; MuJoCo approximates this in development |
| Sensor | Measures some function of the world or robot | Camera/RGB-D, LiDAR-like rays, pose/state feedback, microphones, controller telemetry |
| State | Minimal variables needed to predict/control behavior | Body pose/twist, owner/obstacle tracks, controller lifecycle, task revision, evidence freshness |
| Estimator | Infers state from noisy history | Track filters and owner prediction exist; a commissioned localization/SLAM estimator does not |
| Controller | Converts a desired state/trajectory into commands and uses feedback to reduce error | Grid tracker and follow controllers propose body velocity; Unitree Sport closes lower-level gait/balance loops |
| Planner | Searches over future actions or paths | PlanSketch/PlanIR at task level; A* in the local occupancy grid; search/frontier and approach logic |
| Executive | Owns task state, resources, retries, cancellation and completion | Deterministic `TaskExecutive` plus runtime adapters, with legacy bypasses still present |
| Safety monitor | Restricts or revokes commands independently of the goal | Arbitration, freshness/input health, proximity/TTC, final stop and controller watchdog layers |

The planner should answer “what route or skill could achieve the goal?” The
controller should answer “what short-lived command reduces current error?” The
safety monitor should answer “is that command justified right now?” Combining
all three inside a language model makes failures hard to detect and impossible
to bound. Parcel intentionally keeps them separate.

### A.3 Information flow and authority flow are different graphs

A component may know something without being allowed to cause motion. The
online semantic map may propose that a bench is near `(x, y)`. Route memory may
propose an interim waypoint. A learned navigator may score a frontier. The
conversation model may propose a task. These are information edges.

Authority edges are narrower:

```text
recognized principal + committed turn
        -> admitted typed task/revision
        -> resource-owning behavior
        -> short-lived velocity proposal
        -> current evidence and safety disposition
        -> sole locomotion writer
```

No proposal source may mint its own priority, lease, freshness, invariant, or
success result. This is the practical meaning of “models propose; deterministic
code disposes.” It is also why a `shadow` perception source can run beside the
oracle without changing behavior: it receives information access but no
actuation authority.

### A.4 Time-scale separation

Different robot problems require different rates. Faster is not automatically
better; a rate must be fast enough for the dynamics and deadline it governs,
and its worst-case execution time must fit its period.

| Approximate scale in this checkout | Responsibility | Why it belongs there |
| --- | --- | --- |
| Onboard / vendor high rate | Joint torque/position, foot contact, gait and balance | Python must not try to recreate the manufacturer's stabilizing controller over a network |
| 50 Hz (`20 ms`) | `ControlManager` body-command refresh/watchdog; expression channel also targets 50 Hz | Short command TTL and smooth actuator handoff; expression timing is faster but subordinate |
| 10 Hz (`100 ms`) | Main semantic/control tick and D0 frame cadence | Navigation updates, safety gating, activity/task polling, simulator state |
| Historical measured about 1.75 Hz | Committed MuJoCo CPU OWLv2 stream configured for 2 Hz | The earlier 0.56 s age made those frames diagnostic only |
| Roughly 100–114 ms detector p50 in P1-A evidence | Worktree Unix-socket GPU detector on synthetic/recorded input | Process isolation is inexpensive; no live-camera capture-to-consumer rate or age was measured |
| Hundreds of milliseconds to seconds | STT/turn endpointing, semantic grounding, LLM conversation/planning | These components may miss interactive deadlines and must be cancellable and outside control locks |
| Seconds to minutes | Search, patrol, navigation missions, conversation memory | Budgeted state machines, not blocking function calls |

For a periodic loop with period `T`, useful engineering checks are:

- worst-case execution time `C <= T` with reserve;
- input age plus compute plus transport remains below the consuming policy's
  freshness budget;
- output TTL exceeds expected jitter but remains below the maximum tolerated
  uncontrolled-motion duration;
- a missed deadline is visible and has a defined degraded disposition.

The earlier C-1 experiment illustrates why all four matter. Its safety-gate work
stayed well below the 10 Hz deadline because rendering/inference ran off-loop, yet
the resulting detections were too old for the 300 ms evidence TTL. P1-A then showed
that a process split adds only about 0.6–1.8 ms p50 around a roughly 100–114 ms
desktop detector path. That proves process isolation is affordable on that host;
it does not prove physical capture freshness, D455 alignment, model accuracy or a
consumer deadline. Control isolation, inference timing, observation age and task
quality are four different tests.

### A.5 State, events, and revisions

A robot mixes continuously changing physical state with discrete events:

- continuous: pose, velocity, distance, bearing, covariance, battery;
- discrete: transcript committed, task accepted, E-stop latched, goal reached,
  controller faulted;
- hybrid: a navigation state machine whose transitions depend on continuous
  geometry and timers.

Revision numbers turn asynchronous work into a linearizable transaction. If the
owner says “go to the bench,” then corrects “the other bench,” the first planner
may finish later. A result without the current task revision is stale even when
its geometry is valid. Parcel stamps turn generations, task revisions, attempts,
and navigation proposals so late work can be discarded rather than silently
resurrecting an old instruction.

### A.6 Evidence is a product, not a debug artifact

The claim ladder used throughout this handbook is a compact assurance case:

```text
implemented -> wired -> default -> verified -> operational -> commissioned
```

Each arrow needs evidence. Code inspection proves implementation. A composition
test proves wiring. Configuration inspection proves the default. A deterministic
test or recorded experiment verifies a scoped behavior. Service/device probes
show operational availability. Only intended-hardware, intended-environment
measurements commission a capability. Skipping a rung is how a simulator feature
gets described as a robot feature.

Parcel improves on ordinary prototype practice by storing pre-registrations,
negative controls, mutation results, frozen digests, and `does_not_prove`
statements. The remaining challenge is to make those records one causal product
trace rather than many specialist ledgers.

## Appendix B — Geometry, coordinate frames, pose, and uncertainty

### B.1 Why frames are contracts

The tuple `(2, 1)` is not a location until its frame and units are known. It may
mean two metres forward and one metre left of the body, a map coordinate, a pixel,
or two degrees and one metre by mistake. Robotics makes frames explicit because
mixing them produces confident but wrong motion.

The important conceptual frames are:

- **map:** a persistent/global frame in which destinations and long-lived
  landmarks are expressed;
- **odom:** a locally smooth frame that accumulates drift but should not jump;
- **base/body:** attached to the robot; body velocity commands are normally
  forward/lateral/yaw in this frame;
- **sensor:** camera optical or LiDAR frame, fixed to the body by calibrated
  extrinsics;
- **object/person track:** a measured or estimated target frame with time and
  uncertainty.

The current simulator effectively supplies MAP and ODOM truth with zero
covariance. That is convenient for algorithm development and dangerous for
field inference: it hides drift, map-to-odom correction, relocalization jumps,
calibration errors, and uncertainty reserve. A physical system needs a single
localization owner for timestamped `T_map_odom`, covariance, health and jump
events.

### B.2 Planar rigid-body pose: SE(2)

For mostly flat navigation, body pose is

```text
q = (x, y, theta)
```

where `(x, y)` is translation and `theta` is yaw. The homogeneous transform from
body coordinates to world coordinates is

```text
T_world_body = [ cos(theta)  -sin(theta)  x ]
               [ sin(theta)   cos(theta)  y ]
               [     0            0       1 ]
```

A point `p_body = (px, py)` becomes

```text
p_world = R(theta) p_body + t.
```

A body-frame velocity `(vx, vy)` becomes world velocity

```text
x_dot = cos(theta) vx - sin(theta) vy
y_dot = sin(theta) vx + cos(theta) vy
theta_dot = vyaw.
```

This is why reading a heading in degrees as radians is catastrophic even when
every value is finite. An early patrol integration found exactly that defect and
added a test against the runtime's degree conversion. Unit validation alone cannot
replace a frame contract.

Angles are periodic. Differences must be wrapped, commonly to `[-pi, pi)`, so
that a target at `-179 degrees` is two degrees—not 358 degrees—from a body at
`179 degrees`. Parcel's navigation, tracking and bearing utilities repeatedly
perform this wrapping.

### B.3 Three-dimensional pose: SE(3)

Camera projection, leg kinematics and body attitude require 3-D pose:

```text
T = [ R  t ]
    [ 0  1 ]
```

with `R` a 3x3 rotation and `t` a three-vector. Roll-pitch-yaw is intuitive but
order-dependent and singular near certain attitudes. Rotation matrices and unit
quaternions are safer composition representations. A calibrated camera extrinsic
is a fixed `T_body_camera`; a measured pixel/depth point moves through
`camera -> body -> map` using transforms at the capture timestamp, not the time
inference finishes.

The capture timestamp rule is essential. If the dog turns while a 500 ms detector
runs, projecting with the newest pose places the old pixel in the wrong part of
the map. The committed camera pose mailbox associates one fresh pose with one render and refuses
to reuse a missing pose, which is the correct shape for simulated evidence. A
physical implementation should instead use timestamped transform interpolation
from a bounded buffer.

### B.4 Twist, acceleration, and motion continuity

A **twist** describes rigid-body velocity: linear velocity `v` and angular
velocity `omega`. Parcel's body command is the planar subset `(vx, vy, vyaw)`.
Acceleration limits bound how quickly velocity changes; jerk limits bound how
quickly acceleration changes. Jerk limitation reduces mechanical shock and makes
motion socially legible, but it adds state and latency. Emergency stop paths must
bypass or reset that state so “smooth” cannot mean “kept moving through a veto.”

Two serial shaping stages currently exist around the safety chain. Their state
must be audited as part of authority. Patrol diagnosis showed that feeding post-gate output
back into an upstream smoother compounds a slow-band scale each tick. The output
is safer in magnitude but semantically wrong: one policy application no longer
means what its configured scale says.

### B.5 Covariance and confidence are not synonyms

Covariance describes uncertainty in a numeric estimate and its correlations. For
planar pose a covariance matrix might cover `(x, y, theta)`. A detector confidence
is usually a model score; it is not automatically a calibrated probability and
cannot replace geometric covariance.

If a measurement model is `z = h(x) + noise`, first-order propagation uses the
Jacobian `J = dh/dx`:

```text
Sigma_z approximately J Sigma_x J^T + R.
```

This matters for arrival. A point estimate can lie inside a goal region while a
large part of its uncertainty lies outside. A robust terminal witness reserves
margin for pose, target, map and stopping uncertainty. The current simulator's
zero-covariance truth makes this easy; the proposed physical ODD must specify the
reserve quantitatively.

### B.6 Transform time, interpolation, and uncertainty

A transform is valid at a time, not forever. Suppose camera evidence was captured
at `t_c`, the estimator publishes body poses at `t_0` and `t_1`, and inference
finishes at `t_f`. The correct world projection uses an interpolated
`T_map_camera(t_c)`, not `T_map_camera(t_f)`. For translation, bounded linear
interpolation is often adequate; for 3-D rotation, spherical interpolation of unit
quaternions avoids Euler-angle discontinuities. Extrapolation beyond a short,
declared horizon should fail rather than invent motion.

Transform uncertainty has two sources: uncertain extrinsics and uncertain robot
state. If a point is projected as `p_m = R p_s + t`, first-order covariance is

```text
Sigma_m = J_state Sigma_state J_state^T
        + J_sensor Sigma_sensor J_sensor^T
        + J_ext Sigma_ext J_ext^T.
```

Ignoring the extrinsic term is especially harmful on a low-mounted camera: a small
pitch error produces a position error that grows with range. Ignoring time skew is
equivalent to another pose error roughly proportional to body speed and latency.
The physical calibration manifest therefore needs transform value, uncertainty,
valid sensor/robot serials, calibration method, timestamp and software version—not
merely six nominal numbers.

Parcel's `PoseEstimate` and camera evidence carry many of the right fields, but it
has no TF-style time buffer, commissioned extrinsics or physical cross-clock map.
That is why adding a D455 class is not the same as obtaining metric world evidence.

### B.7 Distance conventions

“Distance to obstacle” may mean centre-to-centre, base-centre-to-surface,
footprint-to-surface, or ray range. Mixing these silently shifts safety bands by
the robot or object radius. Parcel explicitly names a base-centre-to-obstacle-
surface clearance convention in its authority and reactive-safety code, while
owner tracking also carries a collision envelope. A patrol/gate diagnosis closed to
about 1.8 mm only because it used the same convention as the running gate:

```text
owner centre standoff
  = person stop clearance
  + owner collision envelope
  + speed * reaction horizon.
```

Frame, timestamp, unit, and distance convention should be treated as type
information even when Python represents the underlying value as `float`.

## Appendix C — Quadruped mechanics, kinematics, dynamics, and locomotion

### C.1 What Parcel controls—and what it deliberately does not

A Go2-class quadruped has an articulated body with multiple joints per leg. At
the low level, stable locomotion requires joint sensing, contact estimation,
motor current/torque control, body attitude stabilization, swing-foot placement,
stance-force distribution and gait timing. Those loops run much faster and closer
to the hardware than Parcel's Python application.

Parcel normally asks the vendor/onboard locomotion layer for bounded body velocity
or a reviewed Sport action. It does not replace the balance controller with an
LLM or send language-model joint targets. This sacrifices direct control over
gait optimization in exchange for a dramatically smaller and safer application
boundary. Learned low-level locomotion remains a possible vendor/custom-controller
implementation behind the same body-level contract, not an excuse to bypass it.

### C.2 Degrees of freedom and forward kinematics

A degree of freedom (DoF) is an independent generalized coordinate. A rigid body
in free 3-D space has six: three translations and three rotations. Each revolute
leg joint adds an angle. The full configuration vector `q` includes floating-base
pose plus joint coordinates; `q_dot` contains body twist and joint velocities.

Forward kinematics computes an end-effector or foot pose from joint angles:

```text
p_foot = f(q).
```

It composes link transforms from hip to thigh to calf to foot. Inverse kinematics
asks for joint values that place the foot at a desired target. A quadruped controller
uses this constantly for swing trajectories and posture. Multiple solutions or no
solution may exist; joint limits and collision constraints make the problem more
than algebraic inversion.

The Jacobian linearizes this mapping:

```text
v_foot = J(q) q_dot
tau_joint = J(q)^T f_contact.
```

The first relation maps joint speed to foot speed. The transpose maps a desired
foot/contact force to generalized joint torque. Singular or ill-conditioned
Jacobians amplify commands and reduce controllability, which is one reason
reviewed posture/trajectory clips still require real-robot commissioning.

### C.3 Dynamics and contact

Rigid-body dynamics are commonly written

```text
M(q) q_ddot + C(q, q_dot) q_dot + g(q) = S^T tau + J_c(q)^T lambda,
```

where `M` is inertia, `C` captures velocity-dependent terms, `g` gravity, `tau`
actuator torque, and `lambda` contact force through contact Jacobian `J_c`.
Contacts are unilateral: a foot can push the ground but not pull it. Tangential
force is limited by friction, approximated by `||f_t|| <= mu f_n`. Exceed it and
the foot slips.

Static stability asks whether the projected centre of mass lies inside the
support polygon of contacting feet. Dynamic gaits may be stable even when that
condition is temporarily false because momentum and planned future contacts
matter. Zero-moment-point, centroidal dynamics, model-predictive control and
learned policies are different ways to reason about that problem.

Parcel's current city simulation is valuable for task, navigation, perception,
collision and software lifecycle testing, but base travel is not evidence that
the physical legged dynamics can execute the same trace. It should be read as a
kinematic/behavioral preview around a detailed model, not physical gait
commissioning.

### C.4 Nested control loops

A practical quadruped has nested loops:

```text
mission goal (seconds-minutes)
  -> route/local path (seconds)
  -> desired body velocity/heading (10-50 Hz)
  -> gait, feet and body attitude (hundreds of Hz)
  -> joint current/torque (higher rate)
  -> motors and contact
```

Outer loops assume inner loops are stable and obey declared capabilities. Parcel's
`ControlManager` supervises the application-to-locomotion boundary: lifecycle,
fresh state, limits, command TTL, refresh, stationary witness, stop retries,
faulting and E-stop. The Unitree Sport adapter then translates into vendor calls.
Physical configuration is intentionally fail-closed: axes/frame are uncommissioned
and the allowed-mode set is empty, so the repository cannot honestly claim a
working Go2 command path on this host.

### C.5 Trajectories, interpolation, and expressive motion

A pose is a configuration target. A trajectory is a time-indexed sequence of
targets. Good trajectory generation respects position, velocity, acceleration,
jerk, joint, balance and contact constraints. Naively interpolating joint angles
can drag a foot through the ground or move the centre of mass outside support.

Parcel's YAML pose/trajectory catalog is bounded and highly testable. In MuJoCo it
supports a useful commissioning gallery and personality expression. On hardware,
however, expressive whole-body clips are physical actions with the same need for
sole-writer authority, stop behavior and stability evidence as locomotion. The
target architecture therefore either gives them a separately allowlisted native
gateway contract or keeps them unsupported. “Decorative” describes product intent,
not mechanical consequence.

### C.6 Braking and stopping distance

For initial speed `v`, reaction/transport delay `t_r`, and guaranteed deceleration
`a_b > 0`, a simple planar stopping bound is

```text
d_stop = v t_r + v^2 / (2 a_b) + d_uncertainty + d_margin.
```

The first term is distance traveled before braking begins; the second is braking
distance under constant deceleration. The reserves cover state age, controller
tracking error, surface friction, slope, body footprint, localization and model
uncertainty. The speed-dependent reaction-plus-braking portion grows more than
twofold when speed doubles because it contains both linear and quadratic terms;
the total clearance grows superlinearly, although a fixed uncertainty/margin
reserve means the total does not necessarily double in every numerical regime.

The simulator's proximity constants are policy inputs, not commissioned physical
stopping evidence. The first ODD needs measured worst-case delay and deceleration
across battery, payload, surface and network conditions, then a single derived
safety envelope consumed consistently by planner, runtime and gateway.

### C.7 Sim-to-real implications

The reality gap includes friction, compliance, backlash, motor saturation, contact
geometry, sensor latency/noise, illumination, calibration, thermal throttling and
human behavior. Domain randomization and learned dynamics can help, but neither
turns simulation into certification. The disciplined ladder is:

1. pure contract/property tests;
2. deterministic replay;
3. MuJoCo functional and fault scenarios;
4. fake-vendor/process lifecycle tests;
5. hardware-in-the-loop without free motion;
6. independently stopped, low-speed, single-axis commissioning;
7. bounded scenarios inside the declared ODD;
8. repeated integrated evidence with confidence intervals.

Parcel is strong through the simulator/replay and fake-boundary portions of this
ladder. The physical rungs remain intentionally open.

### C.8 Unitree Sport versus low-level control

The high-level Sport interface accepts desired body velocity and lets the onboard
controller own contact schedule, balance and joints. A low-level interface exposes
joint position/velocity/torque targets and makes the application responsible for
far more of the stability chain. These modes are not interchangeable backends:
running publishers in both can create conflicting ownership, discontinuous posture
or a fall. One mode owner, one writer and an explicit stationary/disarmed handover
are safety invariants.

For the first companion ODD, Sport is the rational choice. Parcel needs to identify
its input/output behavior rather than reproduce it: commanded versus measured body
twist, deadband, saturation, acceleration, yaw/translation coupling, transport
delay, stop response, fault/mode transitions and behavior over battery/payload/
surface. That empirical model informs the outer controller and safety envelope.
It does not require access to the vendor's internal gait controller.

Low-level control becomes justified only if a measured product requirement—terrain,
energy, a posture, gait transition or expressiveness—cannot be met through Sport.
At that point the project inherits contact estimation, state estimation, torque
limits, fall recovery, motor thermal protection and far more hardware assurance.
An empty `policy_path` and an RL-shaped Python API are nowhere near that threshold.

### C.9 System identification and commissioning evidence

For each commanded axis, a simple first model is a delayed first-order response:

```text
v_dot = (K u(t - tau) - v) / T,
```

with gain `K`, delay `tau` and time constant `T`. Real behavior includes nonlinear
deadband, clipping, cross-axis coupling and surface-dependent braking. Step, ramp
and emergency-stop trials at deliberately low speeds estimate these properties.
Every run should retain command/state timestamps, firmware/SDK/config hashes,
battery, payload, surface, operator, stop method and stationary witness.

Commission signs and frames before tuning gains: a wrong lateral sign can look like
a badly tuned controller but is categorically more dangerous. The correct ladder is
read-only telemetry, raised/secured or otherwise approved axis verification,
single-axis low speed, combined planar velocity, stop/fault injection, and only then
path tracking. Simulator parameter fitting follows measurement; measurement must
not be selected to match the simulator.

## Appendix D — Sensors, perception, and evidence

### D.1 Measurement chains

A sensor does not directly output “truth.” It produces a signal through a chain:

```text
physical quantity
  -> transducer / optics
  -> analog electronics
  -> sampling and quantization
  -> driver timestamp
  -> calibration and frame transform
  -> filtering / inference
  -> typed evidence
  -> consumer-specific belief
```

Every stage can add bias, noise, latency, dropout or a frame error. A trustworthy
evidence record therefore needs more than a label and score. Useful fields include
capture start/end, monotonic and wall clocks where necessary, sensor/calibration
identity, frame, pose/transform revision, provider/model/precision, sequence,
uncertainty, input references, truncation/drop counts and expiry.

Parcel's camera envelope, committed detection frames and P1-A physical/replay
backends move in this direction. Its older
`SimObservation` projection is intentionally simpler, which is why it should not
become the physical world-model contract.

### D.2 Camera geometry

The pinhole model maps a camera-frame point `(X, Y, Z)` to a pixel `(u, v)`:

```text
u = fx X/Z + cx
v = fy Y/Z + cy,
```

where `fx, fy` are focal lengths in pixels and `(cx, cy)` is the principal point.
Given registered depth `Z`, back-projection is

```text
X = (u - cx) Z/fx
Y = (v - cy) Z/fy.
```

That point must then pass through the calibrated camera-to-body extrinsic and the
capture-time body pose. Depth uncertainty usually grows with range; pixel-centroid
error creates bearing error; the two become correlated world-position uncertainty.
Taking the median or robust inlier set over pixels is safer than trusting a single
depth sample at an object boundary.

The repository models a D455-like channel and nominal dog-height mount, carries
intrinsics/extrinsics, localizes pixel detections, and explicitly distinguishes
range uncertainty from measured surface relief. That last distinction matters:
a range-noise formula cannot tell whether a detection lies on a flat poster. The online map
correctly requires actual depth-patch samples for its planarity defense and labels
the check unmeasured when those samples are absent.

### D.3 Detection, segmentation, and open vocabulary

Object detection returns boxes, labels and scores. Segmentation returns per-pixel
regions. Open-vocabulary models compare visual features with arbitrary text prompts,
which is attractive for language-grounded robots but introduces several traps:

- scores vary with prompt wording and the other prompts in the batch;
- a high similarity is not a calibrated probability;
- a detector can confidently label a decal, reflection or texture;
- small/occluded/low-viewpoint people may be missed;
- the same frame reused by multiple consumers is still one observation;
- model latency can make geometrically correct localization temporally wrong.

Default navigation still consumes oracle semantic rows. The worktree can feed
MuJoCo/synthetic detections into the online map under a learned/shadow profile, and
P1-A provides physical UVC/RealSense classes plus an isolated detector process.
Those facts do not make physical perception wired: the normal runtime camera factory
still builds MuJoCo/synthetic sources, live camera rows were not run, and RGB-only
UVC cannot satisfy the current metric-depth contract.

P1-D adds an optional VLM veto/name path with the correct authority direction: it
may subtract or return ASK, never create ADMIT. Its 45% name fixture is a useful
warning. Open-ended vocabulary helps conversation only when labels retain primary
identity, names remain revisable secondary evidence, and uncertain outputs do not
become coordinates.

### D.4 LiDAR and range sensing

A 2-D LiDAR-like scan samples range by bearing. Each valid ray says:

- cells before the return were observed free;
- the return cell was occupied, subject to range/noise/geometry;
- space behind the return is unknown, not free;
- a no-return ray may mean clear to maximum range or missing data, depending on
  the sensor contract.

MuJoCo ray casting provides occlusion-true geometric observations for the rolling
grid. It is much stronger than reading every scene object directly because nearer
geometry hides farther geometry. It still lacks physical effects such as glass,
black/absorptive surfaces, rain, multipath, vibration, time skew and calibration
drift.

Directional relevance matters. The nearest obstacle anywhere around the body
should not necessarily stop forward motion if it is safely behind, but an orbit or
lateral command changes the swept region. Parcel filters ranges by command direction
for reactive safety and uses a footprint-inflated grid for planning. A mature final
governor should evaluate the swept footprint over the command horizon rather than a
single scalar nearest range.

### D.5 Inertial, proprioceptive, GNSS and UWB measurements

An IMU measures angular velocity and specific force, not absolute pose. Integrating
gyro bias produces orientation drift; integrating acceleration twice produces rapid
position drift. Joint encoders and motor/controller state provide proprioception.
GNSS can bound outdoor global drift but suffers occlusion and multipath; UWB can
provide local ranges/positions with anchor calibration and non-line-of-sight errors.

The repository contains typed/noise/fusion seams for GNSS and UWB and controller
feedback contracts. Their existence demonstrates interface planning, not live
localization. No physical sensor spine currently fuses these into the default pose
provider.

### D.6 Audio is also a robot sensor/actuator system

Microphones sample pressure; speakers alter the same acoustic field. Full duplex
creates feedback: the robot hears itself. Voice activity detection, endpointing,
ASR, identity, dialogue and TTS form a perception/action loop with latency and
authority implications. Acoustic echo cancellation estimates the speaker-to-mic
path and subtracts it; without AEC, an energy gate must conservatively distinguish
owner speech from robot playback.

The host currently enumerates a Seeed XVF3800/ReSpeaker USB array, correcting older
docs that said no transducer was attached, but the available desktop probe did not
show a working PipeWire source/sink path. Hardware presence therefore does not equal
operational capture, AEC, or through-air latency evidence. The hosted browser audio
lane and local PortAudio path also have different device boundaries and must be
measured separately.

### D.7 Freshness and negative evidence

“I saw no person” is evidence only if the sensor was healthy, covered the relevant
field of view, used a capable model, and the observation is fresh. An empty detection
frame is different from no frame. The camera contract preserves that distinction: empty observations
count as real frames; missing/stale/faulted streams have different states; last-frame
age and last-positive-detection age are separate.

Likewise, object absence should not instantly delete a semantic memory. The online map marks
decay after revisiting the relevant place without seeing the object, excludes decayed
entries from retrieval, preserves history, and permits later revival. This is a good
belief-management pattern: absence changes confidence and eligibility while leaving
an auditable record.

### D.8 Multi-view evidence and data association

Multiple views help reject false positives only when they are genuinely independent
enough. Two boxes from the same cached image are not two views. Adjacent video frames
may share the same failure. Useful independence keys include capture sequence,
camera pose, visit/session, model version and source crop/reference.

Data association asks whether a new observation belongs to an existing track/map
entry. Gating commonly uses geometric distance normalized by covariance (Mahalanobis
distance), semantic compatibility, embedding similarity and time. Fusion should
avoid averaging incompatible object instances. The online map keeps two same-class places apart
beyond a fuse radius and stores the best observed embedding rather than blending
across views; proposed names require distinct visits before promotion.

For predicted observation `z_hat`, innovation `nu = z - z_hat` and innovation
covariance `S`, the squared Mahalanobis distance is

```text
d_M^2 = nu^T S^-1 nu.
```

A chi-square threshold rejects geometrically implausible pairings while scaling for
uncertainty. The Hungarian algorithm then finds a minimum-cost one-to-one assignment
among accepted pairs. It is deterministic and bounded, but one-to-one commitment
can be brittle during long occlusion or dense crossings. JPDA retains association
probabilities; multi-hypothesis tracking retains alternative histories. Both improve
ambiguity representation at increased compute/state complexity. Parcel's first ODD
should start with deterministic tracking plus explicit `AMBIGUOUS/LOST` authority,
not with an algorithm that hides ambiguity behind one winning identity.

The P1-C gallery/tracker is a useful isolated implementation: it can reuse ingress
embeddings or compute SigLIP-2 features, and it has deterministic fusion seams. It
is not a calibrated person-verification system. A real gate needs owner/stranger
ROC, threshold preregistration, held-out people, multiple clothing/lighting/distance
conditions, occlusion/crossing ID switches and an explicit no-owner null set.

### D.9 Sensor synchronization and observability

Multi-sensor fusion assumes the measurements describe compatible times. Hardware
timestamps may live in camera, LiDAR, IMU, DDS or host clocks. A synchronizer needs
clock identity, offset/drift estimation, bounded queues and a rule for interpolation,
approximate matching or rejection. Wall time is useful for audit; monotonic time is
appropriate for local age/TTL. A clock reset or timestamp rollback is a health
event, not a negative duration.

Observability asks whether the available measurements can distinguish the state.
An IMU cannot provide absolute position; a featureless corridor gives weak visual
yaw/translation constraints; a planar LiDAR may not observe height/roll/pitch well;
leg odometry becomes unreliable during slip; UWB geometry is poor when anchors are
nearly collinear. More sensors do not automatically solve this—correlated failures,
bad extrinsics and time skew can make a fused estimate confidently worse.

The first physical data campaign should record raw and calibrated streams together,
retain original device timestamps, and make synchronization residuals observable.
Only then should an estimator benchmark determine which sensors materially improve
ATE/RPE, lost rate and recovery under the proposed ODD.

## Appendix E — State estimation, tracking, mapping, and memory

### E.1 Bayesian filtering

State estimation maintains a belief rather than a single fact. Given prior belief
`p(x_{t-1})`, action/control `u_t`, and observation `z_t`, a Bayes filter has two
steps:

```text
prediction: p(x_t | z_1:t-1, u_1:t)
            = integral p(x_t | x_t-1, u_t) p(x_t-1 | ...) dx

update:     p(x_t | z_1:t, u_1:t)
            proportional to p(z_t | x_t) p(x_t | z_1:t-1, u_1:t).
```

The Kalman filter is the linear-Gaussian case. Extended and unscented variants
handle nonlinear motion/measurement models approximately. Particle filters keep
multiple hypotheses and are useful when beliefs are multimodal—for example, owner
reacquisition after a long occlusion.

For a linear model `x_k = F x_{k-1} + B u_k + w` and
`z_k = H x_k + v`, with process covariance `Q` and measurement covariance `R`, the
Kalman equations are

```text
x^- = F x + B u                 P^- = F P F^T + Q
y   = z - H x^-                 S   = H P^- H^T + R
K   = P^- H^T S^-1              x   = x^- + K y
P   = (I - K H) P^-.
```

The innovation `y` is both a correction and a diagnostic. Normalized innovation
squared can reject outliers and expose a mis-tuned/no-longer-valid model. An EKF
linearizes nonlinear `f` and `h` about the current estimate; a UKF propagates sigma
points. Neither rescues an unobservable state, wrong timestamp, wrong frame or
incorrectly small noise covariance. A filter can be numerically stable and
physically overconfident.

Modern robot localization often uses smoothing/factor graphs rather than only a
forward filter. A filter summarizes the past into the present state; a smoother
optimizes a window or entire trajectory when delayed measurements and loop closures
arrive. The cost is greater compute, memory and global corrections. The correct
choice depends on latency, sensor suite, map lifecycle and relocalization needs—not
on which acronym is fashionable.

Parcel's owner predictor uses bounded classical filtering and confidence to lead a
moving target while braking as confidence falls. It is sensible as a proposal layer,
but identity and physical observations are still simulator-derived; prediction
cannot manufacture an owner track after identity is lost.

### E.2 Tracking and identity

A tracker needs prediction, measurement association, lifecycle and uncertainty.
Person tracking adds a safety-critical identity question: which track is the enrolled
owner? Choosing the nearest person after occlusion is not reacquisition; it is an
identity switch.

A robust `OwnerBelief` should carry candidate identities, embedding/model provenance,
last confirmed observation, motion prediction, ambiguity, consent/enrollment state,
and an explicit lost state. Positive follow authority requires a fresh, sufficiently
confident owner hypothesis. Ambiguity means hold, search, ask or return—not silently
select a stranger.

`SearchOwner` already expresses a bounded behavioral skeleton: travel toward the
last observation, sweep, explore frontiers and give up. It does not yet demonstrate
successful physical or even repeatable simulated reacquisition, and it maintains
search-local state rather than one world belief.

### E.3 Occupancy grids

An occupancy grid divides space into cells containing occupied/free/unknown belief.
Using log odds avoids repeated probability normalization:

```text
l_t(m_i) = l_t-1(m_i) + inverse_sensor_model(z_t, x_t) - l_0.
```

Ray updates decrease occupancy along observed free cells and increase it at a valid
return. Values are clamped to avoid absolute certainty. A rolling grid moves its
window with the robot and preserves local resolution without unbounded memory.

Parcel's default local planner uses a 161 by 161 grid at 0.1 m resolution—about
16.1 m across—fed by calibrated MuJoCo ray ranges. The grid is local evidence, not
a city map. It must not be extrapolated behind occlusion or across long-term drift.

### E.4 Inflation and configuration space

A path planner often treats the robot centre as a point after expanding obstacles by
the footprint radius plus margin. This is a Minkowski sum: obstacle space inflated
by the reflected robot footprint becomes configuration-space collision. It lets A*
reason about a finite body using point-cell transitions.

Inflation must match the body, speed and tracking error. Overinflation makes narrow
routes impossible; underinflation plans paths the body cannot follow. Parcel has
historically exposed mismatches between planner inflation, reactive stop distance,
goal bands and object-centre/surface conventions. The target `RobotProfile x
SpeedRegime x SafetyEnvelope` should derive them from one commissioned source while
preserving an independent final check.

### E.5 SLAM and localization

Simultaneous localization and mapping (SLAM) estimates trajectory and map together.
Visual, visual-inertial and LiDAR systems differ in measurements but share the need
for data association, loop closure, optimization and failure detection. Loop closure
may correct global drift and therefore jump the map-frame estimate; odom should remain
locally continuous, with `T_map_odom` absorbing the correction.

#### E.5.1 Dead reckoning, odometry, localization, mapping and SLAM

These terms name different products:

- **dead reckoning** integrates motion without external correction;
- **odometry** supplies a locally smooth incremental pose, commonly from wheels,
  legs, visual flow, LiDAR scan matching or their fusion;
- **localization** estimates pose in an existing map;
- **mapping** builds a representation assuming pose is known well enough;
- **SLAM** jointly estimates trajectory/map because neither is initially known;
- **relocalization** recovers a map pose after initialization or loss.

For a quadruped, leg odometry infers body motion from joint kinematics and feet
believed to be stationary in stance. Slip or a wrong contact state violates that
assumption. IMU preintegration constrains high-rate rotation/acceleration between
keyframes but must estimate bias and gravity. Visual odometry needs texture and
lighting; RGB-D adds scale/range but has range/field limits. LiDAR odometry needs
geometric structure and calibrated time/extrinsics. Fusion is valuable because the
failure modes differ, not because more streams automatically increase confidence.

#### E.5.2 Scan matching and pose graphs

Scan matching estimates a relative transform that aligns a new point/scan set with
a previous scan or local map. ICP minimizes point-to-point or point-to-plane error;
correlative methods search a bounded pose window; visual methods minimize feature
reprojection or photometric error. All need robust outlier handling and a score that
can reject a bad match.

A pose graph uses robot poses as variables and relative measurements as factors:

```text
x* = argmin_x sum_(i,j) || Log(z_ij^-1 (x_i^-1 x_j)) ||^2_(Omega_ij),
```

where `z_ij` is a measured relative transform and `Omega_ij` its information
matrix. Sequential factors form odometry; a loop-closure factor connects revisited
places and redistributes drift. Robust loss functions or switchable constraints are
essential because one false loop closure can deform an entire map.

#### E.5.3 MAP and ODOM roles

The controller wants continuity: a sudden pose jump can create a sudden error and
command. The mission wants global consistency: a loop closure should correct where
the destination lies. The standard separation is

```text
map --T_map_odom(t)--> odom --T_odom_base(t)--> base_link.
```

`T_odom_base` stays smooth and drifts. `T_map_odom` changes as global localization
corrects that drift. A MAP-frame goal must be transformed into ODOM at a coherent
timestamp before a local controller consumes it. Parcel's `GridNavigator` currently
has no such transform; truth pose makes both frames numerically identical and hides
the defect.

#### E.5.4 Loop closure, map lifecycle and localization health

Loop-closure retrieval proposes a revisited place; geometric verification decides
whether to add the constraint. After optimization, semantic landmarks and route
nodes must either be anchored to corrected submaps/poses or explicitly reprojected.
Persisting raw unversioned coordinates makes a route graph internally inconsistent
after correction.

Localization health should be a product state, not a log string. Useful signals
include covariance/information, innovation residuals, scan-match fitness, inlier
count, degeneracy, time since global constraint, map support, jump magnitude and
lost/relocalizing state. None alone is universal. Capability admission maps them to
behavior: normal navigation, speed clamp, rotation-only localization recovery,
HOLD, task failure or operator takeover.

Map lifecycle includes session/map IDs, origin, sensor/calibration/software hashes,
versioning, serialization integrity, change detection, rollback and privacy. A
home map is user data. A semantic object may move while walls remain stable. Long-
term operation must distinguish dynamic change from localization failure.

#### E.5.5 Candidate implementation strategy and evaluation

Parcel should not start by writing a bespoke SLAM system. Use identical timestamped
bags to compare at least two established providers compatible with the selected
sensor/compute platform. A 2-D LiDAR pose-graph system may be sufficient for a flat
indoor ODD; RGB-D/visual-inertial or 3-D LiDAR approaches may better support low
viewpoints and richer relocalization at greater compute/tuning cost. A small EKF can
fuse smooth odometry/IMU while the selected mapper owns global correction.

Report:

- absolute trajectory error (ATE) after alignment;
- relative pose error (RPE) over fixed time/distance horizons;
- translation/yaw drift per metre;
- lost/false-relocalization rate and recovery time;
- covariance/innovation calibration, not only mean error;
- loop-closure precision/recall and jump magnitude;
- timestamp-to-pose latency and CPU/GPU/RAM/power;
- behavior during sensor dropout, feature-poor corridors, moving crowds and map
  changes;
- replay determinism and map/version provenance.

SLAM is therefore not just a library selection. The first ODD needs calibrated
sensors, time synchronization, observability, relocalization, health semantics,
map lifecycle, change handling and failure policy. Parcel currently has provider/
frame contracts and simulation truth, not a wired physical SLAM/localization spine.

### E.6 Four different “maps” in Parcel

These stores should not be conflated:

| Representation | Contains | Can justify | Cannot justify |
| --- | --- | --- | --- |
| Rolling occupancy grid | Current local free/occupied evidence | Short-horizon collision-aware route | Global location, object identity, long-term permanence |
| Navigation semantic map / oracle | Simulator-declared visible labels/locations | Development grounding and deterministic tests | Physical perception or learned-map truth |
| Online semantic map (experimental) | Robot-observed object/place entries, provenance, visits, names, embeddings, decay | Candidate places, vocabulary, local semantic memory | Free space, localization, road/geofence safety |
| Route/place memory | Visited topological nodes/edges and semantic labels | Familiar interim waypoint proposal | Current traversability, obstacle clearance, relocalization by itself |

The target world model links these representations by revision and provenance
without merging their authority. A remembered café can propose where to look; a
fresh local grid must still justify how to move; localization must justify which
map region the grid occupies; terminal evidence must verify the requested relation.

### E.7 Online semantic map design and current limits

The worktree-composed map has several strong properties:

- no implicit store path and mechanical refusal of the owner's conversation store;
- volatile people are observed/counted but never persisted as places;
- size and optional measured-relief hygiene;
- reobservation strengthens instead of duplicating;
- absence marks/decays rather than deleting history;
- label/text candidate generation precedes embedding reranking;
- embeddings compare only inside a versioned model/preprocessing space;
- names require independent visits before text-channel promotion;
- every resolve returns evidence and an abstention verdict.

P1-B changes an important first-edition fact: when an effective learned/shadow
profile is selected, runtime start installs an instance-bound map, camera frames feed
it, and close persists it. The recorded simulator patrol grew 69 active entries
across seven labels and a reload continuation reached 85/eight. This proves a
writer/persistence path, not a correct physical map. Default navigation remains
oracle, the prototype robot overlay does not itself select the learned navigation
profile, and physical camera classes still do not reach that runtime factory.

The current blockers are map-quality and lifecycle evidence: no physical corpus,
unmeasured duplicate and retrieval quality, no independent geometric/name precision,
close-oriented persistence with a crash window, and no proof that every crop/
thumbnail/embedding can be migrated after a model change. P1-D improves the
abstention architecture but records only 18/40 correct names. Those are promotion
blockers, not reasons to discard the object-evidence design or confuse it with SLAM.

### E.8 Memory governance

Robots need several memories with different retention and trust:

- working memory for the current turn/task;
- episodic memory for prior interactions and outcomes;
- profile memory for user-approved stable preferences;
- spatial/place memory for revisitable locations;
- safety/incident evidence for audit;
- model caches, which are performance artifacts rather than facts.

The current conversation SQLite store, P2-A owner facts, tiered summarization,
route memory, semantic map and task records are fragmented. P2-A materially improves
the seam: consent/provenance-bearing fact records, deterministic remember/refuse/
forget policy, full-ledger replay and user-facing inspection exist in the worktree.
Its hosted model-chosen storage row is unrun, distillation scheduling is incomplete,
and deletion has not been audited across every derived index/artifact.

A governed design needs explicit purpose, consent, provenance, expiry, correction/
forget controls, encryption/access policy and query relevance. Retrieval must not
silently turn an old utterance or model summary into current physical truth. A
speaker label, appearance match or owner fact also cannot become a motion credential;
identity, authorization and personalization are separate contracts.

## Appendix F — Planning, navigation, following, and social motion

### F.1 Hierarchical planning

Navigation is not one algorithm. Parcel's intended hierarchy is:

```text
language / mission
  -> typed semantic goal and terminal relation
  -> grounding candidates / goal region
  -> global route or place-memory hints
  -> local observed-space path
  -> path/formation tracking command
  -> reactive and final safety
  -> locomotion manager / onboard gait
```

Each layer solves a different horizon and must preserve the task revision. A global
route may pass through stale space and therefore only proposes waypoints. A local
planner uses fresh geometry. A tracker converts the path into body command. A safety
gate can always reduce/revoke the proposal. Completion flows upward only after an
independent terminal witness.

### F.2 A* and cost design

A* expands nodes in order of

```text
f(n) = g(n) + h(n),
```

where `g` is accumulated path cost and `h` estimates remaining cost. An admissible
heuristic never overestimates and preserves optimality for the chosen grid/cost
model. Real robot planners add costs for obstacle proximity, people, direction
changes, unknown space and dynamic prediction. Those weights encode behavior and
must not override lethal occupancy.

Parcel's `grid_v1` is a strong default because it is deterministic, inspectable and
cheap. A* on an inflated rolling grid makes failure modes reproducible. Its limits
are discretization, local horizon, stale/dynamic-world mismatch, hardcoded envelopes
and dependence on a valid scan. Learned challengers may score frontiers or paths,
but should first operate in shadow and retain the grid/safety fallback.

### F.3 Tracking a path

A path is geometry; a controller must make the body follow it. A simple tracker
selects a lookahead point, computes heading/distance error, rotates when angular
error is large, then commands forward-preferred velocity. Rate limits prevent
instant command jumps. Lateral velocity can be available for compatible bodies but
should not be assumed across robot vendors.

Pure pursuit, regulated pure pursuit, dynamic-window methods and model-predictive
control trade computational cost against dynamic awareness and constraint handling.
Parcel's current tracker is intentionally simple and explainable. Promotion of a
more sophisticated controller should show fewer stalls/interventions and better
comfort without increasing collision, clearance, latency or stale-input violations.

### F.4 Goal regions and semantic relations

Natural language rarely specifies an exact point. “Near the entrance,” “beside the
bench,” and “at the crosswalk” describe regions and relations. Planning directly to
an object centre may be impossible or unsafe because the object occupies that space.

A semantic goal should contain:

- target identity/hypothesis and evidence revision;
- relation such as near, next-to, in-front-of or visible-from;
- admissible region with standoff and approach constraints;
- terminal observation/settling requirements;
- ambiguity and alternate-instance policy;
- time/distance/replan budget.

Parcel has relation parsing, affordances, safe approach sampling, arrival bands and
semantic verification, but some typed grounding is converted back to text and some
static POI paths do not receive the full terminal witness. Passing typed intent end
to end is an important next step.

### F.5 Search and active perception

An unseen target needs a sensing policy, not blind translation. Active perception
chooses motions or viewpoints that reduce uncertainty: rotate, scan, approach a
vantage point, inspect a candidate, or ask for clarification. Information gain,
expected success and motion risk can be combined, but the action still passes
normal safety and mission budgets.

Parcel's unknown semantic targets rotate and require repeated observation before
translation. Search/frontier and value-directed components exist, with bounded
replans and failure. Some recovery/frontier paths historically bypassed the full
grid goal lifecycle; the target goal manager must make every translation-bearing
subgoal revisioned, expiring and lethal-checked.

### F.6 Owner following

Following is control of a moving formation, not navigation to the owner's current
point. A desired relative pose might be behind the owner at distance `d`. The
controller needs owner position, heading/velocity, confidence and age. Prediction
can target

```text
p_target = p_owner + v_owner * lead_time + R(owner_heading) * formation_offset.
```

Prediction helps only if the track is accurate and the safety envelope leaves room
to use it. Parcel's measured direct-follow case showed little benefit because the
owner-clearance clamp left only about 0.05 m of effective lead. Production retains
the older 1.2 m stranger band; P1-E experimentally derives a configurable prototype
0.70 m band over a 0.68 m software floor and a 1.25 m owner keepout. The experiment
does not prove a physical stopping/comfort envelope or that planner and final gate
use one exact derivation.

Following also needs identity continuity, occlusion policy, pace negotiation,
reacquisition and social passing. Current simulator tracks exercise the controller;
they do not solve physical owner recognition.

### F.7 People, proxemics, and time to collision

Social navigation is not equivalent to collision avoidance. A robot can avoid
contact while crowding, cutting off or trapping a person. Proxemic costs encode
larger comfort bands, often anisotropic around a walking person. Prediction can
reserve a future corridor. Yield policy decides how long to wait, move aside,
replan or report blockage.

Time to collision (TTC) estimates when relative motion closes a separation. In a
one-dimensional projection,

```text
TTC = distance_along_closing_axis / closing_speed
```

when closing speed is positive. Covariance, acceleration and lateral crossing make
real TTC a distribution rather than one scalar. Parcel uses simulator tracks for
predictive costs/TTC plus geometric reactive safety. Malformed predictions currently
fall back to geometric-only gating; that is preferable to fabricated prediction but
needs an explicit degraded disposition and physical evidence contract.

### F.8 Patrol and exploration

Patrol is a closed-loop behavior that repeatedly senses, chooses a bounded local
action, moves, and records coverage/map growth. A robust exploration objective
should balance new observed area, semantic discovery, path efficiency, revisit,
battery/mission budget and risk. Merely accumulating path length can produce circles;
net displacement alone can miss useful local coverage.

The current patrol is deliberately smaller: budget/contact/person/geometry priority,
turn hysteresis, directional clearance and a fixed safe vocabulary. Its earlier
single run was useful plumbing evidence but narrowly passed a distance floor, made
little net displacement, used stale detections, left map correctness unscored and
recorded 10 collision ticks. P1-B later exercised the product writer/persistence
path and grew 69 entries/seven labels, then 85/eight after reload—still simulated.
Patrol should remain an evaluation driver until coverage, causal contact, map
precision/recall, repeatability and task/authority integration are demonstrated.

### F.9 Arrival is a claim requiring a witness

A controller returning “done” usually means its geometric error or path state met a
threshold. Product success may require more:

- the body is settled, not coasting through the region;
- pose/localization is fresh and sufficiently certain;
- the same target instance remains supported by independent current evidence;
- the requested relation holds with uncertainty reserve;
- no newer task revision superseded the goal;
- the terminal result is durable enough to explain and replay.

Parcel's semantic-arrival machinery embodies this principle and is one of its
strongest designs. Historical evaluation also shows it is hard: search and arrival
reliability across object classes remain open. A false arrival is worse than an
honest refusal because it teaches the user that explanations cannot be trusted.

### F.10 Navigation metrics and experiment design

Success rate alone cannot distinguish “stopped safely,” “never progressed,” “took
an absurd detour,” and “arrived for the wrong reason.” A useful navigation report
includes:

- success and false-arrival rate;
- SPL or path efficiency relative to a declared reference;
- collision/contact and minimum clearance, separately for people/objects;
- intervention, replan, stall, deadlock and localization-loss counts;
- time, path length, energy and compute/latency tails;
- jerk/acceleration and social-zone intrusion duration;
- semantic grounding precision, clarification and wrong-instance rate;
- terminal-witness completeness and evidence independence.

Random seeds are not independent environments if they reuse the same appearance,
geometry and oracle. Split development, validation and final held-out scenes before
tuning; include null targets and adversarial decoys; preserve failures. Simulator,
bag replay and physical trials answer different questions and should appear as
separate rows rather than one pooled score.

## Appendix G — Control, safety, authority, and fault containment

### G.1 Safety, reliability, and capability are separate axes

A reliable system repeats its behavior. A safe system avoids unacceptable risk. A
capable system achieves useful goals. A robot that reliably drives into a wall is
not safe; a robot that always stops is safe in a narrow sense but not capable. Parcel
therefore reports hard-safety metrics beside success, progress, comfort and latency
rather than averaging them into one score.

Safety is defined relative to an ODD and hazards. The proposed first ODD narrows
terrain, weather, speed, supervision and route class because evidence for a flat,
dry, private route says nothing about stairs, public roads or rain. Important hazard
classes include collision with people/objects, falls/drop-offs, identity-following
errors, uncontrolled motion after software/network failure, false arrival, unsafe
posture, acoustic/privacy failures and operator misunderstanding.

### G.2 Defense in depth

The current velocity path applies multiple independent restrictions:

```text
source proposal
  -> priority + TTL arbiter
  -> configured kinematic limits
  -> pre-gate smoothing
  -> input-health/freshness disposition
  -> directional person/obstacle/TTC reactive gate
  -> actuator acceleration/jerk shaping
  -> post-shaper hard/proximity stop reassertion + state reset
  -> ControlManager capability/lifecycle/watchdog
  -> simulator or vendor controller
```

Each layer catches a different class of failure. Arbitration prevents competing
writers. Limits reject malformed/excessive commands. Freshness prevents old evidence
from authorizing new motion. Reactive gates reduce commands based on current local
geometry. Post-shaper finalization prevents stateful smoothing from leaking motion
through a veto. `ControlManager` stops on stale commands/state and confirms a settled
boundary. A target native gateway adds process-death/network isolation.

Defense in depth is not blind duplication. Shared thresholds can drift; serial
attenuation can compound; two gates can both assume the other owns a failure. The
design should derive common envelope data once, then have the final layer recompute
its own disposition from independently delivered evidence.

### G.3 Priority, leases, TTL, and epochs

A **priority** orders simultaneous claims. A **lease** grants temporary ownership of
a resource. A **TTL** limits how long a command remains valid. An **epoch** prevents
old commands from replaying after restart or re-arm. Together they convert an ongoing
motion request into renewable, revocable authority rather than a one-time packet.

If a client dies, renewal stops and the gateway issues stop. If the gateway restarts,
it starts disarmed with a new epoch. If a delayed packet from the previous epoch
arrives, it is rejected even if its sequence number once looked valid. Sequence,
boot epoch, issue/deadline clocks and lease identity must all be explicit at the
physical boundary.

TTL sizing is a safety/availability tradeoff. Too short creates nuisance stops under
normal jitter. Too long extends motion after failure. It must be derived from measured
producer, transport, scheduling and gateway tails plus the commissioned stopping
envelope—not selected because `0.35` feels responsive.

### G.4 Clocks and freshness

Monotonic time is appropriate for age, deadlines and TTL because wall time can jump
under NTP or manual change. Wall time is useful for human audit and cross-session
ordering. Distributed sensors need a clock-synchronization and timestamp-origin
contract. A row should make clear whether time refers to exposure start, exposure
end, driver receipt, inference completion or publication.

Freshness is consumer-specific. A transcript may remain meaningful for seconds; a
person range used for braking may not. A map entry can persist for months as a belief
but cannot authorize local free space. A correct evidence envelope carries timestamps;
each consumer applies an explicit maximum age and degraded behavior.

### G.5 Stop semantics

Parcel distinguishes several stop-like conditions:

- **nominal stop:** smooth completion may ramp down while remaining monotone;
- **proximity stop:** translation becomes exact zero while bounded yaw may remain for
  observation, depending on policy;
- **hard stop:** all axes exact zero and every downstream stateful shaper resets;
- **latched E-stop:** remains stopped until an authorized explicit clear and fresh
  post-clear conditions;
- **hold/pause:** no positive motion, task state retained according to a separate
  resume contract;
- **cancel:** task/revision terminates; late work cannot resume it.

Conflating them creates surprising resume or residual motion. The finalizer models
intervention severity and reset obligations explicitly. Automatic semantic resume
is still incomplete in parts of the task/channel stack, so the handbook does not
claim a uniform pause/resume lifecycle.

### G.6 The hardware E-stop boundary

Software E-stop is valuable but shares power, processors, networks and bugs with the
thing it stops. Physical commissioning requires an independent operator stop that
does not depend on Python, the UI, hosted service, ROS discovery or the same network
path. The native sole-writer gateway should stop on client death and TTL expiry, but
it still does not replace an independent hardware stop.

Physical enablement should require a capability manifest: robot identity/firmware,
network interface, command/state frames, signs, allowed modes, state freshness,
limits, stationary witness, sensor/calibration set, ODD version and evidence hashes.
The current canonical config deliberately leaves Unitree axes/frame uncommissioned
and `allowed_modes` empty. This is correct fail-closed behavior.

### G.7 Runtime assurance for learned components

Runtime assurance places a complex or learned controller beside a simple verified
fallback and a monitor. The learned component may act only inside a safe set; the
monitor switches or projects commands when boundaries approach. For Parcel, an even
safer first stage is proposal/shadow mode: a learned model ranks goals/frontiers or
predicts motion while the deterministic baseline actuates.

Promotion requires more than average reward. It needs bounded latency, stale/malformed
handling, confidence/uncertainty behavior, no new hard-gate violations, improvement
on a repeatable residual, and rollback. A VLM or semantic map can be impressive in
conversation while remaining unfit for terminal or collision authority.

### G.8 Building a safety case

A safety case connects claims to arguments and evidence. A simplified top claim might
be “Parcel does not issue uncontrolled positive motion inside ODD v1.” Subclaims cover
single writer, command age, state age, limits, obstacle/person evidence, process death,
restart, E-stop and stationary confirmation. Evidence includes code review, property
tests, seeded defects, deterministic replay, fault injection, HIL and physical trials.

Tests must also attack the test system. Parcel's mutation panels have found green
tests that could not detect the defect they claimed to cover and guards comparing
`None` to `None`. This is excellent engineering practice: assurance evidence is
software too and can be wrong.

### G.9 Safety-envelope composition and monotonicity

Suppose independent authorities produce per-axis admissible magnitudes
`a_i = (v_x, v_y, omega)` and lifecycle dispositions. For aligned symmetric limits,
the final magnitude ceiling is the componentwise minimum; direction and swept-
footprint checks may reduce it further. No downstream stage may increase an upstream
ceiling. This **monotonic authority** property is more useful than testing a few
example constants:

```text
authority_out(command, evidence) <= authority_in(command)
```

for every axis and every more-restrictive evidence state. Stateful smoothing must
also obey an instantaneous lower ceiling; when a STOP arrives, previous velocity/
acceleration state cannot leak through. Property tests should generate non-finite
values, clock jumps, order permutations, threshold boundaries and reset histories.

P1-E exposes why one shared number is not the same as one safety envelope. The
prototype's 0.70 m band is above a software-derived 0.68 m floor, but planner
inflation, final reactive geometry, target standoff, owner envelope, speed regime,
pose uncertainty and physical braking are not yet one commissioned derivation.
The correct implementation shares immutable calibrated inputs and independently
recomputes final restriction; it does not delete defense in depth to eliminate drift.

### G.10 Release integrity is part of the safety argument

A safety mechanism that is not imported, collected or executed is not evidence.
The current eager-barrel cycle is therefore more than maintainability debt: it has
allowed a required semantic capability to soft-disable while a suite stayed green.
The missing ignored Unitree assets are also more than packaging debt: their unhandled
exception suppresses every later assurance result.

For each release, the assurance denominator must be explicit: exact source/artifact,
assets, interpreter/dependencies, collected node IDs, effective configuration,
admitted capabilities and completed stages. A failure-complete runner reports every
independent check even when an early one errors. “No failing result was printed” is
never equivalent to PASS. The integrity gates in section 11 are therefore a safety
prerequisite, not administrative cleanup.

## Appendix H — Task autonomy, language models, and deterministic execution

### H.1 From language to a typed task

Language is ambiguous and open-ended; actuators need closed contracts. The safe
translation pipeline is:

```text
utterance + context
  -> committed intent / clarification
  -> model or deterministic task proposal
  -> schema decode
  -> system-owned compilation
  -> fresh-snapshot validation and authority injection
  -> deterministic execution
  -> independent result evidence
  -> truthful narration
```

The model may choose among allowlisted semantic skills and arguments. The compiler
chooses mechanics, resources, timeouts, success conditions and invariants. The
validator rejects unknown skills, malformed geometry, stale snapshots, missing
capabilities or unsupported relations. The executive owns lifecycle. This minimizes
the model's authority while preserving its value in interpretation and repair.

### H.2 PlanSketch versus PlanIR

A concise PlanSketch lets a model express goal, ordered bounded skills and key
arguments. A richer PlanIR exposes more mechanics and therefore more surface for
prompt/schema drift and hallucination. Parcel supports both, but its architecture
recommends a small model-authored contract compiled into richer system-owned steps.

This is analogous to a high-level programming language compiling to an intermediate
representation: the author expresses intent; a trusted compiler enforces calling
conventions and safety. Model output should not carry raw velocity, arbitrary Python,
resource priority or a self-declared successful result.

### H.3 Deterministic intent before model inference

Emergency stop, hold, status, common follow/navigation and corrections should use a
deterministic router where semantics are clear. This reduces latency, cost and model
failure surface. The model handles genuinely open or ambiguous requests. A strong
agent is not one that calls the largest model for every sentence; it uses the least
authority and computation needed for the decision.

Parcel's immediate STOP path is therefore outside slow inference. Hosted or local
model outage must never disable stop or closed skills.

### H.4 Executive state and resource arbitration

A task executive tracks states such as proposed, admitted, waiting, running, paused,
blocked, succeeded, failed and canceled. Steps acquire resources—base, voice,
attention, body activity—through explicit leases. Feedback is accepted only for the
current task revision and step attempt.

Resource priority alone is insufficient. Preemption needs a checkpoint/settled
witness so an expressive pose cannot begin while the body still moves, and a paused
navigation task cannot silently regain control after a correction. Parcel has strong
deterministic revision rejection and resource concepts, but consequential actions
still take multiple legacy/direct lifecycles and executive-level recovery attempts
are limited.

### H.5 Mission repair

Real autonomy needs bounded repair:

- reobserve or choose another view when evidence is weak;
- choose another target instance or approach pose;
- wait/yield/replan around a person;
- recover localization or ask for help;
- explain why a step is blocked;
- accept a revision without restarting unrelated work.

Repair is not unlimited self-direction. It operates inside the user's authorized
mission, ODD, time/distance/energy budget and invariant leases. A target
`MissionSupervisor` should choose among system-defined repairs using fresh evidence,
record why, and terminate honestly when the budget expires.

### H.6 Tool use and trust

Read-only tools can provide weather, time, memory or map context. Their output is
untrusted data with source, age and scope—not a system prompt and not physical
evidence. A web result saying a business is open cannot prove the entrance is free.
An old memory saying “my owner wears red” cannot authorize following a red-shirted
stranger.

The hosted Realtime broker and local provider paths expose different tool/synthesis
flows. The long-term design should normalize them behind one typed tool-result
contract, a bounded synthesis pass, explicit principal, deadline and causal trace.

### H.7 Hallucination containment

Hallucination is not eliminated by asking the model to be careful. It is contained by:

- closed schemas and exact-key decoding;
- allowlists and capability manifests;
- compiler-owned authority fields;
- fresh evidence and source labels;
- independent success witnesses;
- bounded time/resources;
- model-outage fallbacks;
- narration generated from task state rather than model imagination.

The correct failure for “go to Narnia” is a grounded refusal or clarification, not
the nearest high-similarity place. The learned-map abstention work aims to preserve
that honesty after removing the simulator's closed label oracle. P1-D unblocks the
former universal refusal with a subtractive VLM/ASK seam, but 45% naming on the
registered fixture and no physical calibration mean the safe response is still to
withhold default promotion.

## Appendix I — Voice, dialogue, realtime interaction, and embodiment

### I.1 The speech pipeline

The local path can be viewed as:

```text
microphone -> acoustic framing -> VAD -> endpointing -> ASR
  -> committed turn -> dialogue/task -> text chunks -> TTS -> speaker
```

Hosted Realtime can combine transport, ASR and generation in a streaming session,
but robot authority still terminates in the restricted local tool broker. Config
examples select the hosted lane and current Realtime model family, while the
checkout has no active `configs/realtime.yaml`; unconfigured construction therefore
disables it. The lane is implemented and intended, not an always-on default fact.
It trades local independence for interaction quality and a cloud cost/privacy/
network surface.

### I.2 Turn commitment and partials

Partial ASR is useful for anticipation and interruption but unstable: words may be
revised. Parcel retains hosted transcription deltas as evidence while only a completed
transcript enters robot behavior. This is a sound authority rule. A partial may cancel
speech or prepare computation under a generation guard; it must not execute positive
motion.

Turn IDs, origin and generation guards prevent late replies from an interrupted turn
from speaking or acting. A future unified `CommittedTurnV1` should normalize browser
text, browser audio, local mic, operator/system events and trusted automation under
one principal/revision contract.

### I.3 Barge-in and echo cancellation

Barge-in requires detecting owner speech while the robot speaks, stopping/ducking
audio quickly, canceling old generation, and committing the new turn. Without AEC,
speaker leakage can trigger VAD/ASR and make the robot interrupt itself. An energy
ratio guard helps but is environment-dependent.

End-to-end measurement should timestamp owner acoustic onset, capture, VAD onset,
commit, old-audio cutoff, model first token, first TTS sample and audible output.
Browser events and fake-TTS callbacks are useful software measures but cannot prove
through-air latency.

### I.4 Voice identity and authority

Recognizing speech content is different from recognizing the speaker and authorizing
the requested action. A multi-person environment needs policy for owner enrollment,
confidence, replay/spoof resistance, ambiguous voices, emergency commands, privacy
and retention. The hosted lane contains voice-origin/identity evidence surfaces.
P2-B deliberately treats speaker identity as a label rather than an authorization
gate and adds an unenrolled-narration guard. No enrolled speaker model or household
validation exists; current live labels remain untrusted for positive motion.

STOP should remain broadly available and low latency. Positive motion may require a
more trusted principal. Conversation with a stranger can be allowed without granting
follow or navigation authority.

### I.5 Dialogue and task state

Good embodied dialogue says what the robot actually knows and is doing:

- “I heard you” is not “I accepted the task”;
- “I accepted” is not “I started moving”;
- “the command was accepted by the arbiter” is not “the safety gate delivered motion”;
- “the controller stopped” is not “I verified the bench beside me”;
- “I cannot see it” is not “it does not exist.”

An earlier patrol diagnosis is a useful example: every motion intent was accepted, but
the reactive person gate correctly stopped the body at the owner standoff. Product
narration should derive from post-gate/controller/task evidence so the user never has
to learn internal semantics by watching the dog fail to move.

### I.6 Expression and social embodiment

Expression can make intent legible—orienting, thinking pose, nod, bow, yielding—but
must remain subordinate to locomotion and safety. Parcel uses a faster additive
expression channel with gates for active skills, proximity, battery and E-stop.
Beat-scheduled head telemetry acknowledges timing even though Go2 has no neck and
cannot physically enact a literal head nod.

Personality may choose utterance/gesture style and numeric yield temperament inside
bounded policy. It must never choose smaller hard safety clearance, invent task
success or override authority. Social warmth is a presentation layer over truthful
state, not an alternative to it.

### I.7 Hosted Realtime sessions and tool boundaries

The checked-in examples distinguish a smaller Realtime model for the normal example
from the fuller model in the prototype profile. Current official Realtime models can
process audio/text and use tools, and a session can declare modalities, tool schema,
tool choice and output bounds. Those provider abilities are information and
interaction capabilities—not robot permissions.

Parcel's local broker must remain the authority boundary:

```text
provider event/tool proposal
  -> session/turn/generation validation
  -> exact schema and principal check
  -> spend/rate/deadline policy
  -> deterministic semantic tool implementation
  -> task compiler/fresh evidence/safety for any physical consequence.
```

Unknown tools, malformed arguments, old session generations, replayed call IDs or
budget exhaustion are refusals. Tool output returned to the model is untrusted
context. A provider reconnect must not replay a physical action, and a session
rollover must preserve only bounded approved state. Local STOP and gateway TTL
continue when the provider, network or payment path is unavailable.

### I.8 Affect, initiative, and the companion illusion

Affect estimation can adapt tone, response length and whether to interrupt. Initiative
can make a robot feel attentive: greet when the owner appears, mention a blocked task,
offer a reminder or ask whether to help. Both are inference under uncertainty. A
false confident claim about sadness, identity or intent can be socially harmful even
when no motor moves.

P2-B therefore uses bounded event classes, cooldowns, activity limits and labels that
do not grant base authority. Its current owner-presence events still originate in
simulator truth, so the feature is a software behavior seam. Physical promotion needs
explicit consent, an observed event source, null periods, false-interruption rate,
human rating and a privacy/retention decision. Silence is a valid action; initiative
should optimize helpfulness subject to interruption cost, not maximize utterances.

## Appendix J — Physical integration, compute, power, networking, and procurement

### J.1 The physical composition that does not yet exist

A physical robot is not created by replacing the final simulator velocity sink. The
minimum composition is a closed evidence-and-authority graph:

```text
 D455 / LiDAR / IMU / joints / controller / optional UWB
                  |
       device clocks + time synchronization
                  |
       calibrated sensor-frame providers
                  |
      odometry + localization/SLAM + transform buffer
                  |
 detection/tracking -------- local occupancy/dynamic maps
          |                              |
          +------ synchronized RobotObservationV2
                              |
 task/navigation -> short-lived candidate -> final safety
                              |
            native sole-writer Unitree gateway
                              |
               Sport body velocity + feedback
```

Every edge needs startup admission, health, timestamp, frame, calibration/provenance,
bounded buffering, loss behavior and replay. UI, cloud dialogue, semantic map and
history logging sit outside the deadline-critical stop island. They can improve
capability and explanation; they cannot keep the body moving when required local
evidence expires.

The current repository owns important pieces on both sides of the empty middle:
physical camera/capture and Unitree control classes, and a rich simulator autonomy
runtime. It does not own the assembled physical observation, estimator/SLAM, transform
tree, native gateway or deploy supervisor between them.

### J.2 Compute placement and scheduling

Robot compute must be budgeted by worst-case concurrent demand, not by model TOPS
alone. Representative workloads include camera decode/alignment, open-vocabulary
detection, image embedding, LiDAR processing, localization/SLAM, local planning,
audio/AEC/ASR/TTS, local language inference, UI, logging and compression. They
compete for CPU, GPU, RAM/VRAM, memory bandwidth, USB/Ethernet and thermal headroom.

A defensible topology is:

- native gateway and independent stop on the smallest, most isolated reliable path;
- sensor drivers, time sync, estimator and local safety on local robot compute;
- detector/embedding processes with bounded input/output queues and drop accounting;
- semantic runtime/mission application on local compute when feasible;
- hosted conversation optional and outside motion liveness;
- desktop/offboard compute allowed during R&D but declared as part of that experiment's
  ODD and network dependency.

The desktop's RTX measurements do not prove Jetson/Orin behavior. Python wheels,
CUDA/TensorRT/ONNX providers, aarch64 support, VRAM, cold-start, power mode and
thermal throttling all differ. In particular, the current perception dependency
floor and Python claims need an explicit aarch64 install proof before an Orin BOM is
accepted.

For each process, record nominal rate, deadline, worst-case execution, queue depth,
drop policy, memory ceiling, restart policy and whether failure revokes a capability.
High utilization with good average latency can still produce disastrous p99 tails.
Run thermal soak and inference contention while measuring the 10 Hz runtime and
50 Hz gateway/control deadlines.

### J.3 Power, thermal and network engineering

The energy budget contains locomotion, onboard controller, sensors, compute, network,
audio and conversion losses. Battery-runtime marketing is not mission runtime under
the final payload and compute mode. Measure energy per idle/stand/walk/search/dialogue
state, battery telemetry accuracy, brownout behavior, thermal derating and safe
shutdown. Payload and mount position affect gait/stability as well as runtime.

Network roles should be segmented:

- a dedicated Unitree DDS/NIC/domain with no casual debug writer;
- sensor links sized for raw RGB-D/LiDAR bandwidth;
- bounded authenticated local IPC to the sole-writer gateway;
- internet-facing hosted dialogue separated from the robot-control network;
- operator stop/telemetry designed to fail safely under loss.

Test packet loss, delay, reorder, duplicate, interface flap, DDS discovery failure,
process restart and clock discontinuity. Recovery should be explicit: positive motion
expires, the gateway stops, state is re-established, and a new arm epoch is required.
Automatic reconnection must never replay an old velocity or task action.

### J.4 What a Go2 EDU purchase buys—and does not buy

The EDU platform buys a balanced quadruped, onboard gait/controller, batteries,
vendor high-level development APIs, mechanical platform and selected onboard sensors/
compute depending on SKU. This avoids a person-months-to-years locomotion program.
It does not buy Parcel's calibrated physical observation contract, sensor mounts,
SLAM integration, identity model, independent stop, evidence campaign or companion
product assurance.

A procurement package should freeze:

| Item | Acceptance question |
| --- | --- |
| Exact SKU and firmware | Which Sport/SDK calls, sensors, compute and update policy are supported? |
| SDK/licensing/network | Can read-only state and `Move`/`StopMove` be reproduced on the accepted host/NIC/domain? |
| Batteries/charger/spares | Can the planned lab schedule run without unsafe charging or unavailable packs? |
| RGB-D/LiDAR/IMU | Do range/FOV/rate/interfaces support localization and low-view perception? |
| Compute | Does the actual aarch64 image install dependencies and meet thermal p99 budgets? |
| Mounts/cables/power | Are transforms rigid/repeatable and payload/centre-of-mass effects acceptable? |
| Independent stop/tether/PPE | Can an operator stop/contain motion without Python, UI or cloud? |
| Vendor acceptance/return window | Can inventory, telemetry, axes/frame, battery and low-speed response be checked before the window closes? |
| Lab/people/privacy | Is there a controlled area, named operator/safety reviewer and participant/data policy? |

The purchase order should say “supervised R&D/commissioning platform.” Any document
that says “autonomous companion” needs separate post-commissioning evidence.

### J.5 Physical bring-up sequence

The sequence is deliberately incremental because each rung identifies a different
class of defect:

1. Photograph/inventory serials, firmware, payload, batteries, sensors and stop gear.
2. Establish dedicated network/DDS and capture read-only state; issue no motion.
3. Calibrate clock offsets and static extrinsics; capture stationary and carried/
   pushed datasets as the safety plan permits.
4. Replay physical data through observation, localization, perception, map and safety
   with the gateway disconnected.
5. Commission command/state axes, units, signs and modes using the approved fixture/
   tether and one axis at a time.
6. Measure delay, tracking and stop/stationary witness at the minimum practical speed;
   inject client death, stale state and network loss.
7. Build a bounded velocity-only course with static obstacles, then dynamic people,
   while semantic/learned layers remain shadow-only.
8. Commission localization/SLAM loss and relocalization behavior; prove MAP↔ODOM
   corrections do not create command jumps.
9. Promote physical detector/map/owner belief from record-only to proposal only after
   frozen accuracy/freshness gates; retain deterministic HOLD/refusal.
10. Run supervised point-goal, semantic-goal, owner-follow and conversation-during-
    motion missions in that order, with independent stop and full evidence.

At every rung, stop when evidence contradicts the model. Re-tuning after seeing a
held-out result consumes that result; create a new holdout before claiming promotion.
