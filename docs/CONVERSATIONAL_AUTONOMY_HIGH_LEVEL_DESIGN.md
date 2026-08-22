# Parcel robot engineering handbook

**Executive high-level design, robotics foundations, current quality snapshot,
tradeoffs, and delivery roadmap**

| Document control | Value |
| --- | --- |
| Status | Canonical living system design and evidence-dated quality snapshot |
| Audit date | 2026-08-22 |
| Committed baseline | `71b39a1ad66bb2fb2f6e647dbc94d351fd75d665` (`main`) |
| Worktree scope | Baseline plus the visible, uncommitted C-1/C-2/C-3 perception-map cutover and MOVE-1 patrol wave; those changes are reported as in-flight, not shipped |
| Product objective | A capable conversational companion that safely executes long-running navigation tasks inside a declared operating design domain (ODD) |
| First proposed ODD | Supervised, flat, mapped, private indoor/outdoor routes; dry conditions; adequate light; walking speed; trained operator with an independent stop |
| Audience | Engineering executives, robotics/software engineers, safety reviewers, operators, and learners |

This handbook joins the physical robot, sensing, estimation, semantic perception,
mapping, planning, navigation, control, safety, conversation, task execution,
memory, deployment, and evaluation designs into one system view. It explains both
the engineering decisions and the robotics underneath them. It is intentionally
long-form: the main body supports design and investment decisions; the textbook
appendices derive the core concepts and walk through how this repository applies
them.

It is an architectural synthesis and quality audit, not a claim that the target
system is already operational. In particular, a green simulator regression suite
does not commission a physical Go2, a detector module does not create trustworthy
perception, and an accepted command does not prove the body moved. Those distinctions
are central to the design.

### Suggested reading paths

- **Executive / product:** sections 1-5, 10-14, then Appendix A.
- **Robotics engineer:** sections 3-11, then Appendices B-H.
- **AI / interaction engineer:** sections 6-10, then Appendices H-I.
- **Safety / release reviewer:** sections 1, 3, 5, 8-13, then Appendices D and G-H.
- **New learner:** Appendix A first, then B-G in order, followed by the main body.

## 1. How to read the claims

Parcel has accumulated implementation records, research proposals, simulator
results, and physical-commissioning plans at different dates. The following terms
are used strictly:

| Term | Meaning |
| --- | --- |
| **Implemented** | Code exists in this checkout. |
| **Wired** | A normal product entry point reaches it. |
| **Default** | The canonical configuration enables it. |
| **Verified** | A repeatable test or measurement exercises the stated claim. |
| **Operational** | The required service, model, sensor, or device is available. |
| **Commissioned** | Evidence was collected on the intended physical robot and in the intended environment. |
| **Target** | This document recommends it, but it is not a current capability. |

When a statement here disagrees with code, configuration, or an executable test,
those artifacts win. Historical Scrum records are useful evidence but are not
silently promoted into current capability.

## 2. Executive decision

The right architecture is a **hybrid deterministic autonomy stack**:

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

This is a better tradeoff than either extending the Python monolith or rewriting
the product around ROS/Nav2. It preserves Parcel's strongest, well-tested semantic
and safety work while isolating the timing and failure domains that must not depend
on Python, GPU inference, logging, a UI, or ROS discovery.

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

**Product judgment:** Parcel is an unusually well-instrumented, safety-minded
robotics research/development stack with an integrated MuJoCo companion demo. It
is not a commissioned physical robot product. On the maturity ladder defined in
section 5.2, the integrated system is **L2**: normal development paths are wired,
with several L3 simulation/replay subsystems and no L4 physical autonomy.

**What deserves continued investment:** the semantic-model trust boundary,
deterministic compiler/executive, revision handling, grid baseline, independent
arrival concept, layered stop/control lifecycle, evidence contracts, mutation
testing and adversarial record-keeping. These are harder to reconstruct than a
new model adapter and remain correct strategic foundations.

**What blocks a field claim:** no commissioned physical localization/perception,
owner identity, native sole-writer gateway, stopping envelope, independent-stop
campaign, acoustic path, or repeated first-ODD mission evidence. The current
commit gate is red; the slow tier has environmental/setup errors plus a real
semantic-arrival failure; the only recorded nightly is red.

**What the newest work changes:** C-1/C-2/C-3 and MOVE-1 add meaningful camera,
semantic-memory, source-policy and patrol components, but not an end-to-end visual
navigation capability. The CPU frames are stale, the map misses its live corpus,
the learned admission signal refuses the shadow set, and production never binds
camera -> map -> learned source. Treat the wave as experimental infrastructure.

**Recommended executive decision:** freeze feature-led field claims. Spend the
next increment on release truth, complete composition/fail-closed admission,
arrival reliability, the native physical authority boundary, sensor/localization
evidence, and repeated low-speed commissioning. Continue learned navigation and
open-vocabulary work in shadow until it beats a deterministic baseline without
weakening hard gates.

## 3. Current architecture, as built

### 3.0 What “current” means in this audit

The committed baseline is `main` at `71b39a1`. The checkout also contains an
uncommitted but internally recorded engineering wave. This handbook audits both,
because an engineer opening the tree encounters both, but it never treats the
worktree wave as a released capability.

| Layer | Committed baseline | Visible in-flight worktree | Default / authority consequence |
| --- | --- | --- | --- |
| World appearance | MuJoCo development city with built-in/stylized materials | W-1 adds photo-derived textures/meshes, provenance, packaging globs, primary-scene edits and a separate held-out appearance/layout fixture | The edited development scene is visible only in the current worktree; its perception evidence is not committed, and held-out evidence has not been spent |
| Legacy navigation-candidate camera ingress | `camera_ingress.enabled` / `PARCEL_CAMERA_INGRESS`, MuJoCo EGL and OWLv2 could replace navigation candidates when manually attached, but had no normal composition-root attachment | Existing path retained | Default off; this is a potential semantic-authority path, not the C-1 observation queue |
| C-1 observation camera ingress | Shared camera/provider primitives existed | `perception.camera_ingress` normally attaches a config-gated 2 Hz worker with typed bounded frames, evidence logging, state/UI telemetry and a pose mailbox | Default off; simultaneous legacy/C-1 enablement is refused; measured CPU frames were stale and no production consumer drains this stream into the online map |
| Online semantic map | Route memory and simulator-side semantic map existed; no persistent robot-written object/place map | C-2 adds evidence/provenance-bearing entries, hygiene, persistence isolation, fusion, decay, label-primary retrieval and place-graph binding | The package is exercised by tests/harnesses but is not installed by a normal composition root; its live corpus result was 0/5 and a persistence defect drops the source crop |
| Semantic source | Simulator oracle semantics and hard-coded demo POIs supplied candidate truth | C-3 defines `oracle`, `learned_map`, and behavior-preserving `shadow` policies, POI behavior, and divergence records | Integration is incomplete: YAML is parsed for POI behavior, while the candidate function still reads a process-global selector/map that production never installs. A non-oracle YAML can disable POIs yet still leave oracle candidates driving. |
| Exploration | Navigation/search controllers existed, but no reusable patrol loop built a map while moving | MOVE-1 adds a bounded proposer/runner that turns around people/geometry and sweeps a nonvolatile vocabulary | Research/evaluation utility only; it is not a user-facing mission or safety authority |

This distinction matters operationally: changing a YAML key from `oracle` to
`learned_map` is neither a harmless backend swap nor currently a complete one.
It empties the POI table but does not install the map-backed process-global
candidate source. Until one composition root owns that binding and camera-to-map
drain, non-oracle startup should fail closed rather than create a mixed-provenance
runtime.

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

The committed stack now has two interaction lanes. A bare production launcher
requires the hosted Realtime lane and its local credential/config declaration;
`--legacy` deliberately selects the local endpointing/STT/Gemma/TTS path for
rollback and end-to-end testing. Both lanes terminate in a restricted tool or
intent surface: neither receives raw velocity, joint, lease, priority, or safety
authority.

The current observation/evidence plane is equally important:

```text
                 canonical default                       optional/in-flight
MuJoCo state ──> oracle semantic rows ───────────────┐   RGB-D render / OWLv2
      │                                              │          │
      ├── ray-cast LiDAR ─> rolling occupancy grid   │   typed camera frames
      ├── owner/dynamic tracks ─> social/TTC gates   │          │
      └── truth pose (MAP and ODOM, zero covariance) │   evidence log   online map
                                                     │          │
                                      semantic_source selector <─┘
                                               │
                                               v
                                   grounding / search / arrival
```

The right-hand camera-to-map-to-selector edges are currently connected only by
test/evaluation harnesses, not the normal runtime composition root. Safety
geometry remains independent of the semantic-source selector. In other
words, choosing where the word “bench” comes from is not allowed to choose whether
the LiDAR sector is clear or whether a body command is admissible.

The most important existing architectural property is that the language model is
not a servo controller. Model work is outside the control loop; deterministic code
owns admission, resources, revisions, execution, completion, and final motion.

### 3.2 Current capability matrix

| Area | Current checkout/default state | Architectural reading |
| --- | --- | --- |
| Turn handling | The production launcher requires a hosted Realtime lane; an explicit `--legacy` path retains local endpointing/STT/Gemma/TTS. Final transcripts can act. Partials may prepare/cancel but do not execute. Turn, generation, origin, voice-identity, spend, and restricted-tool gates now exist. | Stronger live-interaction path, but it introduces cloud availability, cost, credential, privacy, and network-tail dependencies. Local through-air audio/AEC remains uncommissioned. |
| Emergency and common intent | A deterministic router handles stop, follow, hold, navigation, status, corrections, and compound routing. | Correct least-latency, least-authority path. |
| Conversation | Hosted GPT Realtime is the declared production interaction lane; local Gemma/llama.cpp remains the reasoning/planning service and the explicit legacy conversation path. Realtime tools are schema-restricted and revalidated by the runtime; local read-only tool results still lack a general bounded second synthesis pass. | Capable, guarded prototype with an honest fail-loud launcher. It is not an offline product, a field-validated voice interface, or a single coherent dialogue/task lifecycle yet. |
| Planning | The canonical config omits `planner_output_contract`, so model planning defaults to verbose `plan_ir_v1`; system-authored local plans use `PlanSketch`. | Safe because authority fields are overwritten, but the model contract exposes needless surface and prompt drift. |
| Plan admission | Skills, resources, preconditions, timeouts, success conditions, invariants, freshness, and semantic grounding structure are deterministically compiled and validated. `NavigateTo` may still begin an active search for an unseen target. | One of Parcel's strongest seams; admission is not proof that the destination is currently visible. |
| Task execution | `TaskExecutive` is deterministic and rejects stale revision/attempt feedback. | Strong state-machine core, but recovery and wait behavior are incomplete. |
| Physical action lifecycle | Follow, hold, spatial, and navigation normally use the brain path; simple walks, catalog skills, backend switching, and legacy fallbacks can bypass it. | `RobotRuntime` bypasses still traverse its downstream safety, but task/resource/progress authority is split. The legacy ROS JSON publisher has no product-path safety proof and should be isolated or retired. |
| World evidence | Rich `EvidenceEnvelopeV1` types and bounded event/session logs exist. C-1 adds exact-key camera-detection frames and C-2 adds provenance-bearing map observations/entries, while planner snapshots are still rebuilt mainly from `SimObservation` and flatten calibration, covariance, identity and world revisions. | Contracts are stronger than end-to-end integration; there is not yet one authoritative revisioned world model. |
| Semantic perception | Default T0/oracle reads simulator semantic truth. The in-flight C-1 worker can render MuJoCo RGB/depth, run OWLv2 on CPU, localize detections, publish a bounded typed stream and write evidence rows. Its measured 562.6 ms median capture-to-publish age exceeds the 300 ms TTL; all retained frames were stale. | Useful diagnostic/proposal evidence, not a physical camera and not fresh enough for grounding or safety authority. |
| Pose/localization | `TruthPoseProvider` supplies simulator truth for MAP and ODOM with zero covariance. | A provider seam exists; physical localization and `T_map_odom` do not. |
| Local navigation | With a calibrated scan, `grid_v1` uses a rolling 161x161, 0.1 m occupancy grid, footprint inflation, A*, dynamic soft costs, and a forward-preferred tracker. An absent or grid-invalid scan invokes a loud point-goal stub fallback. Complete absence is normally stopped downstream, but malformed/missing calibration can be grid-invalid while simpler reactive presence checks still pass translation. | Good deterministic local baseline with a real degraded-path gap: the navigator must return typed HOLD rather than rely on non-equivalent downstream scan checks. |
| Global mapping | The actuating planner still has no live global metric map server, SLAM, or global geometric planner; its active grid is about a 16.1 m rolling window. The in-flight online semantic map stores robot-observed object/place evidence and may bind labels to the place graph, but is not a geometric free-space map or localization system. | Object/place memory is useful context, not a substitute for metric localization, traversability, or current obstacle evidence. |
| Semantic navigation | A deterministic relation/vocabulary parser plus demo POIs feed current-view, memory, scan, search/frontier, safe-approach, progress-watchdog, and terminal-verification logic. C-3 implements policy/helpers for removing the POI oracle and reading a learned map, but the production composition root never installs the process-global source/map; only tests/harnesses do. The shadow study produced 0/18 agreements (0/7 comparable), all `indecisive_ranking`, with zero admission flips. | The cutover is experimental and partially wired. Non-oracle configuration can create a mixed state and should fail startup until one owner binds all edges. Verification remains uneven, simulator-backed, and concentrated in one large coordinator. |
| Route memory | Topological place-graph persistence APIs and safe interim waypoint handoff exist; the live hook is disabled by default and neither loads nor saves, so normal use is session-local. | Valuable within-session topology proposal layer; not wired cross-restart continuity, SLAM, or relocalization. |
| Patrol / map-building motion | The standalone in-flight MOVE-1 runner proposes budgeted cruise/turn commands with person-first priority, directional clearance, hysteresis, and a separate nonvolatile map vocabulary. One 120 s development-scene run covered 5.0137 m and wrote 57 provenanced entries across five place classes, but recorded 10 collision ticks and ended only 0.134 m from its start. No production runtime references the patrol package. | A useful evaluation driver and a narrow acceptance-floor pass, not a wired skill, exploration planner, coverage guarantee, production mission, or generalization result. |
| Social/dynamic navigation | The grid's privileged simulator-track dynamic soft-cost layer is on; the pipeline's perception-derived person-aware overlay is off. TTC also consumes simulator tracks. Malformed predictive inputs disable prediction for that tick while geometric reactive safety remains. | Algorithms exist without field-grade evidence provenance; prediction currently fails open to geometric-only safety. |
| Expression/attention | Dialogue expression runs separately; the social reaction arbiter is selected and recorded, but its selected reaction is not enacted by the normal runtime path. | Partly shadow-wired and correctly subordinate to locomotion. |
| Audio | The semantic Silero/Smart Turn path is canonical on the local lane. Hosted Realtime retains input-transcription deltas as evidence but only completed transcription enters robot behavior; the local microphone path likewise acts on committed utterances. No commissioned local acoustic AEC or through-transducer latency/cutoff result exists. | Partial evidence supports responsiveness/observability without partial action authority. Reliable physical barge-in and self-speech rejection remain unproven. |
| Dual-stream research | The D0 TEXT+ACT frame path is shadow/logging telemetry and has no action authority. | Correct staging boundary; synchronous logging still needs removal from the semantic caller. |
| Safety/control | The normal velocity path has priority/TTL arbitration, input-health and reactive collision/person/TTC gates, two shaping stages, post-shaper hard/proximity-stop reassertion, and a sole `ControlManager` velocity writer. Pose/trajectory activities first stop locomotion, then call separate backend methods through activity/E-stop gates rather than the velocity safety chain. | Strong velocity-control design, but physical effect authority is split and no independent native gateway exists. |
| Physical bring-up | Typed evidence provenance and a narrow commissioning manager landed. A substantial capture stack exists but is not imported by runtime/navigation. No capability-admitting physical-production launcher supervising a native gateway and sensor spine, or commissioned autonomous motion, exists. | Parallel foundations only; not physical autonomy. |
| Deployment | Launch scripts and console entry points exist. The default stack now fails loudly unless hosted-Realtime configuration and credentials are present; `--legacy` is explicit. The deploy `safety-control` path remains a synthetic 10 Hz navigator smoke and service containers are incomplete. | Better composition honesty, still a development launcher rather than the target native gateway/sensor supervision topology. |
| Memory | SQLite recent conversation is active. Tiered summary/profile memory exists but is disabled by default; enabled runtime retrieval is not passed the current query and the distiller proposes no profile facts. Route and semantic memories are separate. | No coherent durable conversational-spatial-task memory. |
| Observability | Turn latency, component metrics, ledgers, duplex records, and recent transcript-origin logging exist as separate surfaces. | Broad instrumentation without one causal trace. |
| Packaging | N27 generates and byte-checks 91 runtime assets; the worktree also packages referenced scene textures/meshes and updates their manifest. Source/package parity is a hard gate, while installed-wheel validation belongs to the slow tier and must be reported separately from source-tree success. | Drift prevention is materially better. A wheel test is still not a deployment, and current slow-tier health must be read from the quality snapshot rather than inferred from the manifest. |

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
| In-flight robot-written semantic map | [`online_map/`](../src/parcel_robot/online_map/) |
| In-flight semantic-source selection/shadow comparison | [`perception_source/`](../src/parcel_robot/perception_source/) |
| In-flight bounded patrol/evaluation driver | [`patrol/`](../src/parcel_robot/patrol/) |
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

In the audited worktree, `runtime.py` is 11,895 lines and
`navigation/pipeline.py` is 6,604 lines. They are effective integration
laboratories, but their size, lock surface, mutable state, and cross-cutting
responsibilities now make authority, invariants, clocks, teardown, and failure
behavior difficult to audit. Decomposition is therefore a risk-reduction program,
not a style cleanup.

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
| The C-1 queue, C-2 map and C-3 source policy have no single production composition owner. | Camera frames are not drained into the map; `use_learned_map()` / `use_semantic_source()` are test-only call sites; YAML affects the POI grounder without binding the candidate source. A configuration can therefore look cut over while oracle candidates still drive. | Create one explicit, non-global `PerceptionSource` object, bind ingress -> map -> snapshot at startup, reject incomplete combinations, expose effective provenance in state/evidence, and test the normal launcher rather than manual installers. |
| The C-1 CPU detector publishes at roughly 562.6 ms median age against a 300 ms TTL. | Every retained measured frame is stale before a consumer sees it; using it for grounding would turn latency into false spatial confidence. | Keep it proposal/diagnostic-only; reduce model/render latency or move inference to an admitted accelerator, then remeasure capture-start-to-consumption tails under contention. |
| The C-1 camera renders from a static scene copy and synchronizes the robot pose, but not moving actors or joint state. | A person can occupy different poses in the control world and the camera world; this invalidates dynamic-person safety conclusions from the current image stream. | Synchronize all safety-relevant dynamic state at a declared capture time, record the scene revision, and test cross-sensor temporal alignment before using camera detections for motion. |
| `RobotRuntime` universally obtains a `SimObservation` from a `SimulatorBackend`; there is no production physical observation assembler. | Adding a Unitree actuator does not create physical autonomy: pose, scan, people and controller evidence still have no synchronized, physical-origin path into runtime safety and navigation. | Introduce a backend-neutral `RobotObservationV2` assembled from timestamped physical providers, then make simulator and replay explicit adapters rather than the universal data model. |
| The normal Unitree builder supplies a raw state source whose declared evidence origin resolves to `UNKNOWN`. | Physical input health correctly refuses the evidence even if the SDK, network, mode and actuator are otherwise available; test-only commissioned wrappers do not prove the product composition. | Require a reviewed `CommissionedStateSource(origin=PHYSICAL)` in the normal physical launcher and bind it to the versioned capability/calibration manifest. |
| The online-map source crop exists in memory but is omitted by the persisted representation. | After restart, a model upgrade cannot re-embed from the original bounded evidence; the record silently loses the artifact meant to support migration. | Persist/restore a bounded, integrity-checked crop reference or bytes and test fresh-interpreter re-embedding. |
| The learned online map is object-centric and has no native semantic-region representation. | Extended places such as sidewalks and plazas cannot be grounded or verified faithfully; forcing them into point objects loses topology and extent. | Add versioned region/surface beliefs with polygon uncertainty and observation provenance, or explicitly keep region questions on a separate source until that contract exists. |
| Learned-map label-primary retrieval currently makes the robust ranking margin exactly zero in the measured distribution. | The provisional PG-3 gate refuses every measured shadow answer; enabling it would create near-universal refusal, while disabling it removes the intended absent-place protection. | Replace or re-derive the signal on textured data, add the registered VLM veto if retained, freeze operating points, and promote only from held-out shadow evidence. |
| Default pose and dynamic tracks are simulator truth. | Navigation scores do not demonstrate field localization or person tracking. | Add production sensor/localization/tracking providers and deterministic replay before robot promotion. |
| MAP goals and ODOM poses lack a real timestamped transform. | Simulator truth hides frame inconsistency; physical tracking can be wrong after drift or relocalization. | Make a localization service own `T_map_odom`, covariance, health, and jump events. |
| Semantic-memory ingestion can fall back to time zero. | Age decay is ineffective in the normal path. | Make time and observation sequence mandatory evidence fields. |
| Search-frontier fallback can bypass the grid planner. | Collision gates remain, but exploration can stall or oscillate in clutter. | Send every translation-bearing search/recovery target through the behavior-scoped goal manager and local planner. |
| Static POI point goals do not use the full semantic terminal witness. | Controller termination can be interpreted more strongly than the available task evidence. | Require a typed terminal policy for every goal class and report exactly what was verified. |
| Road/crossing policy exists but is not wired into production goal, costmap, and final command authority. | A declared road invariant is metadata rather than a live geofence. | Enforce road state in three independent places and fail closed on poor localization/map provenance. |
| `GoalArbiter` is usually called on singleton proposals and has no production lethal-cost callback. | It is a validation helper, not one continuous subgoal authority. | After task/preemption selects the behavior owner, use a live behavior-scoped `GoalManager` for mission, route-memory, exploration, recovery, and operator navigation subgoals; keep moving formation distinct. |
| Route memory is disabled and its normal live hook is process-local, although save/load APIs exist. | It cannot provide wired cross-restart place continuity or relocalization. | Persist and load a versioned place graph with change detection; never treat it as free-space truth. |
| Owner following lacks commissioned identity/re-identification. | “Nearest person” behavior would risk an identity swap. | Use an explicit owner belief state; ambiguity or identity loss means HOLD/search/clarify. |
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
| Runtime and navigation are large shared-state coordinators. | Changes have wide blast radius and ownership is unclear. | Extract typed ports and state owners inside a modular Python application; split processes only at real fault/timing boundaries. |
| Reactive slow-band output is force-fed back into the upstream velocity smoother. | The same safety attenuation compounds across ticks; MOVE-1 measured roughly 2.2x less speed than one policy application intended. This is safe-directional but distorts behavior and every throughput/latency conclusion in the band. | Separate desired-state history from final gated output, add a closed-form steady-state property, and re-run follow/patrol baselines without weakening the stop boundary. |
| The first patrol acceptance run recorded 10 collision ticks and only narrowly cleared its 5 m path floor. | The dynamic-city collision signal mixes robot-caused contact with agents striking a stationary robot; a single narrow pass cannot establish reliable exploration. | Attribute contact by relative motion/causal responsibility, repeat across seeds, report path coverage and net progress, and keep zero-contact as a separately visible hard metric. |
| The MOVE-1 status references `evidence/MOVE1_EXIT_GATE.txt`, but that artifact is absent from the current task evidence. | A narrative pass cannot be independently reproduced or promoted from the referenced evidence package. | Regenerate the gate artifact from immutable inputs or mark the claim incomplete; add reference-existence checks to evidence governance. |
| Generated package assets are now parity-gated, but installed-wheel and deployed-process behavior remain separate claims. | A byte-identical manifest can still package unsafe values or miss environment/service assumptions. | Keep clean-wheel tests in the recorded slow tier and add capability admission plus deployment smoke; never equate parity with safety. |

### 5.2 Evidence baseline

The worktree is test-rich: 285 Python files under `src/parcel_robot` (126,788
lines, including experimental and current untracked packages) and 342
top-level test modules across 343 test Python files (154,565 lines). Collection on 2026-08-22 found **8,022
tests**: 7,980 selected by the commit marker expression and 42 by the slow tier.
The larger test footprint is a material strength, but the current promotion result
is **red**, not green.

#### Current executable quality result

| Check | Current result | Engineering reading |
| --- | --- | --- |
| Exact commit gate | **FAIL:** 1 failed, 7,970 passed, 9 skipped, 42 deselected; 352.4 s total | The sole failure is the protected held-out-scene identifier appearing in an untracked MOVE-1 status document without an allowlist seat. It is evidence-governance leakage rather than runtime behavior, but the gate correctly blocks promotion. |
| Dedicated hard stages | **PASS** | Ruff ratchet; hard-safety evaluators; four digest sentinels; 91-asset release parity; latency ledger/tails; follow jerk ratchet; assertion-eval self-test; tier coverage; model-off 23; frozen-digest 6; release-parity tests 10; mutation freshness 2; owner-store isolation 6. |
| Raw Ruff | **FAIL:** 12 findings across seven grandfathered `(file, rule)` fingerprints | The CI ratchet is green because no new fingerprint was added. The codebase is not raw-lint clean; the baseline is debt, not a pass in the ordinary Ruff sense. |
| Direct local slow suite under nightly variables | **ERROR:** 11 passed, 7 skipped, 4 xfailed, 20 errors | This was direct `pytest -m slow`, not a complete successful official-nightly run. Three installed-wheel tests cannot create a venv because Python 3.14 `ensurepip`/venv support is absent. Seventeen voice-navigation setups are refused by the owner-store isolation guard because the nightly environment lacks a scratch `PARCEL_MEMORY_PATH`. |
| Voice-navigation slow slice with isolated memory | **FAIL:** 16 passed, 1 xfailed, 1 failed | Removing the setup blocker exposes the known lamppost terminal failure: `semantic_arrival_verification_failed`. This is behavioral, not environmental. |
| Recorded nightly | **FAIL:** one recorded run, three hard-red stages | There is no clean recorded nightly and no verified hosted GitHub Actions run. The recorded candidate report includes success rate 0.28 and one false arrival; those are report-only and cannot authorize promotion. |

The current red gate should not erase what passed, and 7,970 passing tests should
not erase the red. The useful executive conclusion is: **strong local regression
engineering around a research simulator, with incomplete release/evidence hygiene
and no physical assurance.**

The seven slow-suite skips also hide work rather than proving it: five closed-loop
Follow-Bench cases require the second opt-in `PARCEL_FOLLOW_BENCH_SLOW=1`, so the
scheduled nightly does not refresh them, and two live-provider cases require
credentials and explicit spend authorization. The four expected failures are
measured capability gaps—half-scale covariance, two region-goal transform cases,
and pedestrian-stream navigation—not benign infrastructure skips. Likewise, the
green assertion-evaluator stage means five frozen fixtures reproduced 20 expected
findings and seeded broken evaluators were detected; two fixture sessions
intentionally contain failing overall/safety matrices, so that stage is not a claim
that the represented robot sessions were good.

#### Quality-system strengths

- Exact-key immutable contracts, deterministic clocks and extensive negative cases.
- Pre-registered measurements with null/control arms and explicit misses.
- Seeded-defect/mutation panels that test whether important tests can actually fail.
- Frozen manifests, source/package parity, held-out leakage protection and owner-store
  isolation.
- Separate commit/slow tier coverage with no collected orphan between the marker sets.
- Honest `does_not_prove` boundaries in many eval/status records.
- A sole normal velocity-writer feedback supervisor, layered command gates and
  exact-stop property tests at the application boundary; pose/trajectory backend
  effects remain a separate authority gap.

#### Quality-system gaps

- No line/branch coverage measurement or minimum; high test count cannot reveal
  which production branches are untouched.
- No mypy/pyright gate, despite a contract-heavy dynamically typed integration
  surface.
- No dependency-vulnerability, secret, license/SBOM or static-security promotion gate.
- Raw Ruff debt remains; the ratchet guarantees “no new fingerprint,” not clean code.
- Three active deprecation warnings still use the retired footprint constant.
- CI declares Python 3.12 only while packaging declares Python `>=3.10`; the audited
  workstation runs Python 3.14.4.
- Hosted workflow installation uses broad `pyproject.toml` ranges rather than the
  repository lock, so local and hosted dependency resolution can differ.
- The workflow job timeout is 20 minutes while the internal default-suite timeout is
  30 minutes; a valid long gate can be killed by its wrapper.
- The first recorded nightly is red, slow setup depends on environment details, and
  hosted Actions execution remains unverified.
- Four of six latency-tail pins, the acoustic sentinel, E1 seal, dependency-lock
  completeness, Gemma provenance and the model-seat fixture gate are still tracked
  as eval-hygiene work; a green dedicated stage is narrower than full evidence trust.
- Only one of the two legacy `walk_with_me` ledger rows carries
  `hard_collision_total`; a hard-safety evaluator that passes available rows is not
  equivalent to complete historical collision instrumentation.

#### Capability maturity snapshot

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
| Hosted conversational lane | L2-L3 | Wired default and recorded software sessions; cloud/network/privacy dependency and no owner-reviewed through-air physical campaign |
| Local acoustic lane | L2 | Piper/endpointing artifacts exist, but no commissioned physical PortAudio stream, AEC or through-air latency |
| C-1 camera ingress | L2 experimental | Normal config attachment exists; measured frames are stale and never drain to the online map |
| C-2 online semantic map | L1-L2 experimental | Strong isolated/replay tests; no normal composition owner, 0/5 live corpus, persistence defect |
| C-3 source cutover | L1 experimental | Helpers/tests exist; production binding is incomplete and measured learned arm refuses all comparisons |
| MOVE-1 patrol | L1-L2 experimental | Standalone runner completed one narrow development run; not a runtime skill and contact/generalization remain open |
| Unitree physical locomotion | L1 | Adapter/supervisor implemented; SDK/NIC/modes/axes/frame and body behavior are uncommissioned |
| Physical observation/localization spine | L0-L1 | Typed capture/provider foundations exist, but no normal physical observation assembly, sensor fusion, `T_map_odom`, localization integrity or runtime binding exists |
| Integrated companion product | **L2 overall** | A capable simulator/development stack, not fielded autonomous robot evidence |

#### Recorded product/evaluation results

| Evidence set | Recorded result | What it does not prove |
| --- | --- | --- |
| Semantic navigation v4 | 25 episodes, success rate 0.24, SPL 0.1933, zero modeled collisions | General autonomy, physical perception or physical collision safety |
| Scripted follow/navigation | Follow 7/9; navigation 2/2 | Identity-safe owner following or ecological validity |
| Gemma conversation calibration | 6/10 machine cases; about 349 ms median first-token latency | Human companion quality or the hosted lane |
| Live PersonalConvo | 3/13 turns and 1/8 families | Long-horizon personal continuity |
| Planner quality v2 | 5/5 selected semantic cases; 5.657 s median usable-plan latency | Physical execution or acceptable interactive tail latency |
| Synthetic duplex | Five of nine gates fail | Through-air audio, AEC or natural barge-in |
| Embodied PlanIR | 4/4 supported deterministic MuJoCo cases; moving owner unsupported | Moving-owner behavior, field sensors or deployment readiness |
| C-1 live camera | Safety gate p99 delta +0.735 ms; 562.6 ms median frame age; all 16 retained frames expired | Fresh perception or grounding authority |
| C-2 online map | Isolated structure/persistence tests strong; live corpus 0/5 and one false-positive entry | Correct robot-written place memory |
| C-3 shadow cutover | 0/18 agreement, 0 admission flips; all learned refusals `indecisive_ranking` | A usable learned source or production binding |
| MOVE-1 patrol | 5.0137 m path, 57 entries, five place classes, 10 collision ticks, 0.134 m net displacement | Reliable exploration, map correctness or generalization |

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
| PlanSketch vs model-authored PlanIR | Model chooses goal/skills; compiler owns mechanics | Smaller attack/error surface and less prompt-contract drift | Compiler/skill registry must be maintained |
| Shared model vs separate models | Shared weights behind role-isolated broker first | Lower GPU memory; retain independent deadlines/cancellation | Scheduling complexity and possible contention |
| Classical actuating baseline vs learned control | Deterministic planner/controller actuates; learned systems challenge/propose | Data-efficient, explainable rollback and safe shadow evaluation | May lag learned methods in complex scenes initially |
| Goal regions vs point targets | Relation- and uncertainty-aware regions | Matches language and prevents false precision/arrival | More grounding and terminal geometry |
| Persistent world model vs mission-local state | Versioned beliefs and place/task history | Enables object permanence, recovery, explanation, and long-range autonomy | Invalidation, privacy, schema, and storage complexity |
| Behavior-scoped goal manager vs ad hoc subcontrollers | Translation-bearing navigation subgoals share revision, system TTL, lethal, and planner checks after task ownership is selected | Prevents exploration/recovery/memory bypasses without creating a second behavior arbiter | Requires controller migration and a separate moving-formation contract |
| Independent final gate vs one shared planner check | Share envelope data, recompute final disposition | Defense in depth against planner/config/controller mistakes | Some intentional duplicated computation |
| Route memory vs full SLAM | Use both; topology proposes and live metric perception verifies | Long-horizon familiarity without mistaking memory for current geometry | Persistence and reanchoring work |
| Microservices vs modular monolith | Few process boundaries, strong in-process ports | Avoids distributed-system complexity where it buys no safety/timing isolation | Requires disciplined ownership inside Python |
| Autonomous initiative vs user authority | Autonomous subgoals only inside a bounded authorized mission in the first ODD | Enables recovery and mixed initiative without inventing positive-motion authority | More authorization, revocation, and narration state |
| One universal snapshot vs linked cadences | High-rate local-motion projections plus slower semantic history | Keeps control fresh while making cross-revision reasoning detectable | Transform/revision bookkeeping |
| Uniform task lifecycle vs expressive responsiveness | Task-manage consequential action; keep decorative expression subordinate and expiring | Consistent authority without turning every nod into durable workflow | Two clearly constrained lifecycle classes |
| Sole writer vs hot failover | Restart-disarmed controlled handover only | Eliminates concurrent-writer ambiguity and stale replay | Brief loss of availability during handover |
| Local vs remote inference | Local default; remote is optional, privacy-governed, deadline-bounded, and never required for safety | Predictable degradation and private first-ODD operation | Less elastic compute and potentially smaller models |
| Read-only tools vs trusted facts | Keep source/trust labels; tool text informs dialogue but cannot authorize or establish physical truth | Contains prompt injection and stale external data | Extra provenance and synthesis policy |

## 11. Delivery sequence and promotion gates

### Immediate prioritized lanes from this audit

| Priority lane | Action | Exit evidence |
| --- | --- | --- |
| P0-A release truth | Restore promotion truth | Current commit gate green without weakening the held-out rule; slow runner uses an isolated store; clean recorded nightly; installed-wheel cells **run and pass** in the designated release/hosted environment. An explained local skip may document a workstation limitation, but leaves release evidence incomplete. |
| P0-B physical authority | Land the native physical authority boundary in parallel with P0-A | Restart-disarmed sole writer, epoch/TTL/lease/watchdog/stationary witness, credential isolation and fault campaign pass before autonomous hardware motion |
| P0-C physical evidence | Establish the physical evidence/localization spine in parallel at the interface/replay level | Timestamped sensor frames, calibrated transforms, `T_map_odom`, covariance/health/jump behavior and deterministic replay; capability profile fails closed when any commissioned prerequisite is absent |
| P1 behavior truth | Fix semantic arrival reliability | Lamppost and every shipped object/relation class pass repeated terminal-witness episodes; no false arrival; baseline re-frozen only after the defect closes |
| P2 composition | Complete or reject the perception cutover | One composition root owns camera -> map -> source; incomplete/global mixed states refuse startup; effective provenance visible in snapshots; oracle remains a tested rollback |
| P3 learned-map evidence | Repair persistence and admission evidence | Source crop survives persistence; ranking/abstention signals re-derived on textured evidence; nulls, decoys and independent visits pass; no threshold tuned on the final held-out scene |
| P4 perception timing | Make camera evidence fresh enough or keep it diagnostic | Capture-start-to-consumer p95 below the declared TTL under CPU/GPU/control contention, with loss accounting; otherwise configuration cannot grant grounding authority |
| P5 motion/evaluation | Fix measured distortions | Remove compounding slow-band attenuation without weakening stops; attribute contact causally; repeat patrol across seeds with coverage, net progress, map precision/recall and zero volatile persistence |
| P6 quality infrastructure | Enforce missing quality controls | Raw Ruff debt and deprecations removed; coverage/type/security/dependency controls enforced in CI or covered by an explicit dated risk acceptance; Python-version matrix and lock usage aligned; timeout hierarchy coherent |
| P7 commissioning | Run the staged first-ODD ladder after its owning gates | Independent stop, single-axis/low-speed bench, static/dynamic obstacles, owner occlusion, conversation during motion and terminal truth repeated with confidence intervals |

These are claim-blocking lanes, not a single serialized feature queue. P0-A, P0-B
and the software/replay portion of P0-C start immediately in parallel; physical
motion remains gated, while P1-P6 may overlap so long as none is used to bypass a
predecessor's admission evidence.

### Phase 0 — parallel P0: release truth and the physical authority boundary

Run two workstreams immediately; neither waits for new semantic features.

**Release/safety truth:**

- Make packaged/source config and prompts generated, zero-diff artifacts.
- Resolve no-provider pose fallback, terminal uncertainty reserve,
  input-class-specific rotation/HOLD behavior, and directional collision relevance;
  encode each decision as property/mutation evidence.
- Reject unsafe feature-flag combinations and uncommissioned capability profiles at
  startup.

**Physical authority:**

- Implement `RobotGatewayV1`, bounded IPC, restart-disarmed state, lease/TTL,
  stop/stationary witness, and a capability-admitting physical launcher.
- Implement and commission `GatewayActionV1` for any physical posture/gesture kept
  in scope, or make those capabilities fail closed as unsupported.
- Revoke robot-network credentials/vendor command access from legacy ROS,
  direct/debug Dog, UI, and Python paths; any retained physical command must route
  through the gateway before the first HIL motion.
- Run property/fuzz/fault campaigns for sequence, epoch, expiry, writer conflict,
  IPC corruption, process kill/stall/restart, and clock discontinuity.
- Begin gateway HIL/bench and explicitly armed single-axis commissioning as soon as
  the safety review admits it; do not wait for advanced navigation.

**Gate:** no Parcel physical autonomous motion occurs without the gateway. Source/wheel
parity is exact; owner-gated safety semantics are decided; the gateway's worst-case
age/watchdog/braking chain fits the commissioned envelope and stops independently
on client death or command expiry.

### Phase 1 — establish the sensor, world-evidence, and localization spine

- Introduce `SensorFrameV2`/`SensorSource` and deterministic rosbag/file replay.
- Normalize camera, LiDAR, IMU, controller, and timing into evidence envelopes.
- Implement `WorldModel` ownership, belief updates, immutable query projections,
  and the revision-linked high-rate `NavigationSnapshotV2` path.
- Add timestamped localization with `T_map_odom`, covariance, health, jump events,
  and explicit no-provider failure.
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

These choices should become versioned ADRs and executable policies. They should not
remain magic constants or be silently inferred from a convenient simulator behavior.

## 15. Related durable designs and evidence

- [Design decisions](DESIGN_DECISIONS.md)
- [2026 layered architecture](REDESIGN_2026_ARCHITECTURE.md)
- [Companion navigation architecture](COMPANION_NAVIGATION_ARCHITECTURE.md)
- [Navigation algorithm decision](NAVIGATION_ALGORITHM_2026.md)
- [Runtime concurrency and clocks](RUNTIME_CONCURRENCY_AND_CLOCKS.md)
- [Duplex dual-stream design](DUPLEX_DUAL_STREAM_DESIGN.md)
- [Voice-agent evaluation and replaceable provider architecture](VOICE_PROVIDER_ARCHITECTURE.md)
- [Attention steering design](ATTENTION_STEERING_DESIGN.md)
- [Strata/generalization plan](STRATA_GENERALIZATION_PLAN.md)
- [Hardware portability audit](HARDWARE_PORTABILITY_AUDIT.md)
- [Archived legacy implementation matrix](archive/LEGACY_IMPLEMENTATION_STATUS_2026-08-04_TO_09.md)
  — a retired August 4-9 historical record, never current authority
- [Accepted production convergence plan](../scrum/20260812/task_1/PRODUCTION_COMPANION_PLAN.md)
- [Current FIX-A validation record](../scrum/20260815/task_1/FIXA_STATUS.md)
- [Companion navigation result ledger](../evals/companion_nav/results/README.md)
- [Planner quality results](../evals/companion/planner_quality_v2/results/README.md)
- [Conversation quality results](../evals/companion/conversation_quality_v1/results/README.md)
- [Personal conversation results](../evals/companion/personal_convo_v1/results/README.md)
- [Duplex results](../evals/companion/duplex_v1/results/README.md)

## 16. Final architectural judgment

Parcel already has the right safety philosophy and many of the right components.
Its best work is the semantic-model boundary, revision-safe task admission,
deterministic executive, independent semantic-arrival verification foundation, and
layered final motion gates. Replacing those with a more end-to-end agent would be a
regression.

The path to a genuinely capable conversational navigator is to make those pieces
coherent end to end:

- one committed turn and authorization contract;
- one task lifecycle for all consequential non-emergency physical work;
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
testability, and incremental delivery for the stated objective.

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
| Measured about 1.75 Hz | In-flight CPU OWLv2 camera stream configured for 2 Hz | Open-vocabulary perception is expensive; current 0.56 s age makes it diagnostic only |
| Hundreds of milliseconds to seconds | STT/turn endpointing, semantic grounding, LLM conversation/planning | These components may miss interactive deadlines and must be cancellable and outside control locks |
| Seconds to minutes | Search, patrol, navigation missions, conversation memory | Budgeted state machines, not blocking function calls |

For a periodic loop with period `T`, useful engineering checks are:

- worst-case execution time `C <= T` with reserve;
- input age plus compute plus transport remains below the consuming policy's
  freshness budget;
- output TTL exceeds expected jitter but remains below the maximum tolerated
  uncontrolled-motion duration;
- a missed deadline is visible and has a defined degraded disposition.

C-1 illustrates why all four matter. Its safety-gate work stayed well below the
10 Hz deadline because rendering/inference ran off-loop, yet the resulting
detections were still too old for the 300 ms evidence TTL. Control isolation
passed; perception freshness failed. Those are different tests.

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
every value is finite. MOVE-1 found exactly that integration defect in its first
patrol implementation and added a test against the runtime's degree conversion.
Unit validation alone cannot replace a frame contract.

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
the map. The C-1 pose mailbox associates one fresh pose with one render and refuses
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
must be audited as part of authority. MOVE-1 showed that feeding post-gate output
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

### B.6 Distance conventions

“Distance to obstacle” may mean centre-to-centre, base-centre-to-surface,
footprint-to-surface, or ray range. Mixing these silently shifts safety bands by
the robot or object radius. Parcel explicitly names a base-centre-to-obstacle-
surface clearance convention in its authority and reactive-safety code, while
owner tracking also carries a collision envelope. The MOVE-1 diagnosis closed to
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

Parcel's camera envelope and C-1 detection frame move in this direction. Its older
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
a range-noise formula cannot tell whether a detection lies on a flat poster. C-2
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

Parcel keeps the in-flight C-1 observation stream diagnostic/proposal-only.
Separately, the legacy camera-ingress path can replace navigation candidates when
manually attached; it is off by default and must not be conflated with C-1. In the
uncommitted W-1 textured-scene wave, all eight declared place classes fired and VLM
scene reading improved materially, but person recall at the pre-registered threshold
remained 1/74 (0.014). Lowering a threshold after looking at the result would fit the
detector to the development world and inflate false positives; the status record
correctly leaves the miss visible.

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
frame is different from no frame. C-1 preserves that distinction: empty observations
count as real frames; missing/stale/faulted streams have different states; last-frame
age and last-positive-detection age are separate.

Likewise, object absence should not instantly delete a semantic memory. C-2 marks
decay after revisiting the relevant place without seeing the object, excludes decayed
entries from retrieval, preserves history, and permits later revival. This is a good
belief-management pattern: absence changes confidence and eligibility while leaving
an auditable record.

### D.8 Multi-view evidence and data association

Multiple views help reject false positives only when they are genuinely independent
enough. Two boxes from the same cached image are not two views. Adjacent video frames
may share the same failure. Useful independence keys include capture sequence,
camera pose, visit/session, model version and source crop.

Data association asks whether a new observation belongs to an existing track/map
entry. Gating commonly uses geometric distance normalized by covariance (Mahalanobis
distance), semantic compatibility, embedding similarity and time. Fusion should
avoid averaging incompatible object instances. C-2 keeps two same-class places apart
beyond a fuse radius and stores the best observed embedding rather than blending
across views; proposed names require distinct visits before promotion.

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

SLAM is not just a library selection. The first ODD needs calibrated sensors, time
synchronization, observability in texture/geometry-poor regions, relocalization,
covariance/health semantics, map lifecycle, change handling and failure policy.
Parcel currently has provider/contracts and simulation truth, not a wired physical
SLAM/localization spine.

### E.6 Four different “maps” in Parcel

These stores should not be conflated:

| Representation | Contains | Can justify | Cannot justify |
| --- | --- | --- | --- |
| Rolling occupancy grid | Current local free/occupied evidence | Short-horizon collision-aware route | Global location, object identity, long-term permanence |
| Navigation semantic map / oracle | Simulator-declared visible labels/locations | Development grounding and deterministic tests | Physical perception or learned-map truth |
| Online semantic map (in-flight) | Robot-observed object/place entries, provenance, visits, names, embeddings, decay | Candidate places, vocabulary, local semantic memory | Free space, localization, road/geofence safety |
| Route/place memory | Visited topological nodes/edges and semantic labels | Familiar interim waypoint proposal | Current traversability, obstacle clearance, relocalization by itself |

The target world model links these representations by revision and provenance
without merging their authority. A remembered café can propose where to look; a
fresh local grid must still justify how to move; localization must justify which
map region the grid occupies; terminal evidence must verify the requested relation.

### E.7 Online semantic map design and current limits

The in-flight map has several strong properties:

- no implicit store path and mechanical refusal of the owner's conversation store;
- volatile people are observed/counted but never persisted as places;
- size and optional measured-relief hygiene;
- reobservation strengthens instead of duplicating;
- absence marks/decays rather than deleting history;
- label/text candidate generation precedes embedding reranking;
- embeddings compare only inside a versioned model/preprocessing space;
- names require independent visits before text-channel promotion;
- every resolve returns evidence and an abstention verdict.

Its current blockers are equally concrete. The only live input corpus produced one
false-positive place and missed all five target queries. The source crop is lost on
store round-trip. The ranking-margin signal is structurally zero under the measured
label-primary background, so the provisional admission gate refuses the shadow set.
Those are promotion blockers, not reasons to discard the architecture.

### E.8 Memory governance

Robots need several memories with different retention and trust:

- working memory for the current turn/task;
- episodic memory for prior interactions and outcomes;
- profile memory for user-approved stable preferences;
- spatial/place memory for revisitable locations;
- safety/incident evidence for audit;
- model caches, which are performance artifacts rather than facts.

The current conversation SQLite store, tiered summarization, route memory, semantic
map and task records are fragmented. A governed design needs explicit purpose,
consent, provenance, expiry, correction/forget controls, encryption/access policy
and query relevance. Retrieval must not silently turn an old utterance or model
summary into current physical truth.

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
owner-clearance clamp left only about 0.05 m of effective lead. The stack now derives
an owner comfort band from the same stand-off authority while retaining the same
hard person stop as for a stranger.

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

MOVE-1's patrol is deliberately smaller: budget/contact/person/geometry priority,
turn hysteresis, directional clearance and a fixed safe vocabulary. Its first run is
valuable plumbing evidence—camera to map while moving—but the 5.0137 m path floor
was passed by only 1.4 cm, net displacement was 0.134 m, all detections were stale,
map correctness was unscored, and 10 collision ticks occurred. It should remain an
evaluation driver until repeated, causally attributed and promoted through the
normal task/authority lifecycle.

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
that honesty after removing the simulator's closed label oracle; its current signal
failure means the safe response is to withhold promotion.

## Appendix I — Voice, dialogue, realtime interaction, and embodiment

### I.1 The speech pipeline

The local path can be viewed as:

```text
microphone -> acoustic framing -> VAD -> endpointing -> ASR
  -> committed turn -> dialogue/task -> text chunks -> TTS -> speaker
```

Hosted Realtime can combine transport, ASR and generation in a streaming session,
but robot authority still terminates in the restricted local tool broker. Parcel's
launcher now makes the hosted lane an explicit production dependency and labels the
legacy lane. That is operationally honest, though it trades local independence for
better interaction quality and a cloud cost/privacy/network surface.

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
and retention. The hosted lane contains a voice-identity gate and evidence surfaces,
but one-minute enrollment and physical household validation remain owner actions.

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

MOVE-1's diagnosis is a perfect example: 160/160 motion intents were accepted, but
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
