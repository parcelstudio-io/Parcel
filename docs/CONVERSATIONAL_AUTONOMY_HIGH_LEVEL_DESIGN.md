# Conversational autonomy high-level design

- **Status:** recommended target architecture, grounded in the current checkout
- **Audit date:** 2026-08-15
- **Audit commit:** `8473a5159babf9eb740dedf901e140a08163093d`
- **Product objective:** a capable conversational companion that can safely execute
  long-running, autonomous navigation tasks in a declared operating domain
- **First operating domain:** supervised, flat, mapped, private indoor/outdoor
  routes; dry conditions; adequate light; walking speed; trained operator with an
  independent stop

This document joins the conversational, task, perception, navigation, control,
memory, deployment, and evaluation designs into one system view. It is an
architectural synthesis, not a claim that the target system is already operational.
Subsystem details remain in the linked design documents near the end.

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

## 3. Current architecture, as built

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

The most important existing architectural property is that the language model is
not a servo controller. Model work is outside the control loop; deterministic code
owns admission, resources, revisions, execution, completion, and final motion.

### 3.2 Current capability matrix

| Area | Current checkout/default state | Architectural reading |
| --- | --- | --- |
| Turn handling | Final transcripts can act. The duplex API accepts non-executing partials for supersession, but the normal microphone path provides speech-onset/VAD barge-in and final-only ASR. Turn/generation guards discard superseded work. | Strong basis for linearizable conversational control; streaming partial ASR is not wired. |
| Emergency and common intent | A deterministic router handles stop, follow, hold, navigation, status, corrections, and compound routing. | Correct least-latency, least-authority path. |
| Conversation | A local Gemma/llama.cpp provider path is configured and is operational only when its external service/model is healthy. Tools are nonphysical and read-only results are appended without a second synthesis pass. A separate `next_action` field can propose a bounded social pose/trajectory through deterministic validation and an activity publisher. | Useful prototype with a guarded social-effect seam, not an effect-free or fully grounded tool-using conversation executive. |
| Planning | The canonical config omits `planner_output_contract`, so model planning defaults to verbose `plan_ir_v1`; system-authored local plans use `PlanSketch`. | Safe because authority fields are overwritten, but the model contract exposes needless surface and prompt drift. |
| Plan admission | Skills, resources, preconditions, timeouts, success conditions, invariants, freshness, and semantic grounding structure are deterministically compiled and validated. `NavigateTo` may still begin an active search for an unseen target. | One of Parcel's strongest seams; admission is not proof that the destination is currently visible. |
| Task execution | `TaskExecutive` is deterministic and rejects stale revision/attempt feedback. | Strong state-machine core, but recovery and wait behavior are incomplete. |
| Physical action lifecycle | Follow, hold, spatial, and navigation normally use the brain path; simple walks, catalog skills, backend switching, and legacy fallbacks can bypass it. | `RobotRuntime` bypasses still traverse its downstream safety, but task/resource/progress authority is split. The legacy ROS JSON publisher has no product-path safety proof and should be isolated or retired. |
| World evidence | Rich `EvidenceEnvelopeV1` types exist, while planner snapshots are rebuilt mainly from `SimObservation` and lose some provenance, covariance, calibration, and revision data. | Contracts are stronger than their live integration. |
| Semantic perception | Default T0 pass-through uses simulator semantic truth. The opt-in asynchronous pixel detector renders MuJoCo RGB/depth and falls back to simulator semantic truth when no pixel frame is ready. | Simulated pixel research path, not a physical-camera integration. |
| Pose/localization | `TruthPoseProvider` supplies simulator truth for MAP and ODOM with zero covariance. | A provider seam exists; physical localization and `T_map_odom` do not. |
| Local navigation | With a calibrated scan, `grid_v1` uses a rolling 161x161, 0.1 m occupancy grid, footprint inflation, A*, dynamic soft costs, and a forward-preferred tracker. An absent or grid-invalid scan invokes a loud point-goal stub fallback. Complete absence is normally stopped downstream, but malformed/missing calibration can be grid-invalid while simpler reactive presence checks still pass translation. | Good deterministic local baseline with a real degraded-path gap: the navigator must return typed HOLD rather than rely on non-equivalent downstream scan checks. |
| Global mapping | No live metric map server, SLAM, or global geometric planner; the active grid is about a 16.1 m rolling window. | Blocking field-deployment gap; route topology cannot supply metric localization. |
| Semantic navigation | A small deterministic relation/vocabulary parser plus demo POIs feed current-view, memory, scan, search/frontier, safe-approach, progress-watchdog, and terminal-verification logic. Semantic goals have strong independent checks; static POI point goals can still arrive from navigator stop without semantic re-verification. | Thoughtful mission logic, but verification is not uniform, semantic breadth is limited, simulator-backed, and concentrated in one large class. |
| Route memory | Topological place-graph persistence APIs and safe interim waypoint handoff exist; the live hook is disabled by default and neither loads nor saves, so normal use is session-local. | Valuable within-session topology proposal layer; not wired cross-restart continuity, SLAM, or relocalization. |
| Social/dynamic navigation | The grid's privileged simulator-track dynamic soft-cost layer is on; the pipeline's perception-derived person-aware overlay is off. TTC also consumes simulator tracks. Malformed predictive inputs disable prediction for that tick while geometric reactive safety remains. | Algorithms exist without field-grade evidence provenance; prediction currently fails open to geometric-only safety. |
| Expression/attention | Dialogue expression runs separately; the social reaction arbiter is selected and recorded, but its selected reaction is not enacted by the normal runtime path. | Partly shadow-wired and correctly subordinate to locomotion. |
| Audio | The owner-authorized semantic Silero/Smart Turn path is now canonical and its ONNX artifacts/runtime resolve; the microphone loop still transcribes a committed utterance rather than streaming partial ASR. No live-microphone latency/cutoff evidence or AEC stage exists. | The configured endpointing improvement is available but unmeasured through real transducers; text remains the honest reliable interaction mode in this environment. |
| Dual-stream research | The D0 TEXT+ACT frame path is shadow/logging telemetry and has no action authority. | Correct staging boundary; synchronous logging still needs removal from the semantic caller. |
| Safety/control | The normal velocity path has priority/TTL arbitration, input-health and reactive collision/person/TTC gates, two shaping stages, post-shaper hard/proximity-stop reassertion, and a sole `ControlManager` velocity writer. Pose/trajectory activities first stop locomotion, then call separate backend methods through activity/E-stop gates rather than the velocity safety chain. | Strong velocity-control design, but physical effect authority is split and no independent native gateway exists. |
| Physical bring-up | Typed evidence provenance and a narrow commissioning manager landed. A substantial capture stack exists but is not imported by runtime/navigation. No capability-admitting physical-production launcher supervising a native gateway and sensor spine, or commissioned autonomous motion, exists. | Parallel foundations only; not physical autonomy. |
| Deployment | Launch scripts and console entry points exist, but the deploy `safety-control` path is a synthetic 10 Hz navigator smoke and voice/perception services are placeholders. | A deployment skeleton, not the target gateway/sensor supervision topology. |
| Memory | SQLite recent conversation is active. Tiered summary/profile memory exists but is disabled by default; enabled runtime retrieval is not passed the current query and the distiller proposes no profile facts. Route and semantic memories are separate. | No coherent durable conversational-spatial-task memory. |
| Observability | Turn latency, component metrics, ledgers, duplex records, and recent transcript-origin logging exist as separate surfaces. | Broad instrumentation without one causal trace. |
| Packaging | N27 now generates and byte-checks 91 packaged assets/side-mirror files from canonical source; the previously divergent navigation files are byte-identical. The build/install-wheel nightly exists but has not run on this host. | The confirmed drift is repaired and guarded in-process; a real installed-wheel parity result remains unverified, and parity does not prove the values are safe. |

### 3.3 Code map

| Concern | Current owner |
| --- | --- |
| Main turn routing and model/tool handling | [`agent.py`](../src/parcel_robot/agent.py) |
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

`runtime.py` is roughly 6,662 lines and `navigation/pipeline.py` roughly 6,393
lines. They are effective integration laboratories, but their size and shared state
now make authority, invariants, clocks, and failure behavior difficult to audit.

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
| Default pose and dynamic tracks are simulator truth. | Navigation scores do not demonstrate field localization or person tracking. | Add production sensor/localization/tracking providers and deterministic replay before robot promotion. |
| MAP goals and ODOM poses lack a real timestamped transform. | Simulator truth hides frame inconsistency; physical tracking can be wrong after drift or relocalization. | Make a localization service own `T_map_odom`, covariance, health, and jump events. |
| Semantic-memory ingestion can fall back to time zero. | Age decay is ineffective in the normal path. | Make time and observation sequence mandatory evidence fields. |
| Search-frontier fallback can bypass the grid planner. | Collision gates remain, but exploration can stall or oscillate in clutter. | Send every translation-bearing search/recovery target through the behavior-scoped goal manager and local planner. |
| Static POI point goals do not use the full semantic terminal witness. | Controller termination can be interpreted more strongly than the available task evidence. | Require a typed terminal policy for every goal class and report exactly what was verified. |
| Road/crossing policy exists but is not wired into production goal, costmap, and final command authority. | A declared road invariant is metadata rather than a live geofence. | Enforce road state in three independent places and fail closed on poor localization/map provenance. |
| `GoalArbiter` is usually called on singleton proposals and has no production lethal-cost callback. | It is a validation helper, not one continuous subgoal authority. | After task/preemption selects the behavior owner, use a live behavior-scoped `GoalManager` for mission, route-memory, exploration, recovery, and operator navigation subgoals; keep moving formation distinct. |
| Route memory is disabled and its normal live hook is process-local, although save/load APIs exist. | It cannot provide wired cross-restart place continuity or relocalization. | Persist and load a versioned place graph with change detection; never treat it as free-space truth. |
| Owner following lacks commissioned identity/re-identification. | “Nearest person” behavior would risk an identity swap. | Use an explicit owner belief state; ambiguity or identity loss means HOLD/search/clarify. |
| Safety thresholds are duplicated across planner and runtime. | A planner-valid route can be executor-impossible and diagnoses are ambiguous. | Derive all planning envelopes from one immutable `RobotProfile x SpeedRegime x SafetyEnvelope`; keep the final gate independent. |
| Recoverable HOLD/proximity/missing-scan policies may preserve yaw, while a latched input-health fault is exact zero at finalization; a no-provider pose fallback can still report healthy zero-covariance state. | The boundary between permitted inspection rotation and full stop, plus terminal pose truth, remains under-specified for physical use. | Resolve each input-class/pose policy explicitly, then freeze exact dispositions with property tests. |
| Grid-invalid scan and malformed prediction have permissive internal fallbacks. Grid scan validity is stricter than reactive scan presence, so stub translation is not always suppressed. | Malformed calibration or prediction can leave more motion than the failed component can justify. | Make safety-relevant components return typed degraded/HOLD states under one calibrated evidence contract; retain downstream gates as independent defense. |
| The native physical gateway and capability-admitting physical launcher do not exist. | Python remains in the prospective physical command failure domain. | Land an isolated, restart-disarmed, sole-writer gateway before autonomous motion. |
| Shared llama.cpp serving has one active cancellation handle. | Conversation, planning, and summarization can cancel or starve each other. | Add an inference broker with role-scoped queues, deadlines, cancellation, and overload policy. |
| Tiered memory is disabled and fragmented from task/spatial memory. | The companion lacks durable reference, commitment, place, and failure continuity. | Introduce governed working, episodic, profile, and spatial memory stores. |
| The reaction arbiter's selected output is recorded but not enacted. | “Social reaction” evidence can be mistaken for product behavior. | Wire it only to bounded voice/attention/expression adapters or label it shadow-only. |
| No AEC or streaming partial-ASR path is wired. | Barge-in, self-talk, and natural turn latency remain weak on real audio. | Add capture identity, AEC, partials for preparation/interruption only, and priority speech delivery. |
| Declarative invariants are stored as one replaceable runtime tuple and enforcement is distributed across subsystems. | Protection may exist, but a task/revision cannot be traced cleanly from invariant to monitor, intervention, and evidence. | Add per-task/revision invariant leases and a monitor registry through terminal state. |
| Duplex/session logging performs synchronous file work from the 10 Hz semantic caller. | Storage latency competes with motion dispatch even though the 50 Hz `ControlManager` thread is separate. | Enqueue bounded telemetry with drop accounting; move serialization/rotation/storage off all control callers. |
| Runtime and navigation are large shared-state coordinators. | Changes have wide blast radius and ownership is unclear. | Extract typed ports and state owners inside a modular Python application; split processes only at real fault/timing boundaries. |
| Packaged navigation defaults are stale. | Source and installed-wheel behavior differ, including motion caps and alignment. | Generate assets from one source, verify digests/zero diff, and test the built wheel in an empty environment. |

### 5.2 Evidence baseline

The test posture is broad: 240 production Python files (about 92,389 lines) and
282 test modules. A current non-slow collection selects 5,384 of 5,420 tests; the
latest recorded commit gate for this HEAD lineage reports 5,375 passed, 9 skipped,
and 36 deselected. That is strong regression evidence, not physical validity.

The green result is a local, recorded runner result. The repository contains a
GitHub Actions workflow definition, but its own header and `docs/CI.md` say hosted
Actions are not yet wired; external per-commit/nightly execution is therefore
unverified. Slow coverage is much thinner (the latest voice-navigation run records
17 passes and one expected failure), and there is no HIL or physical-product proof.

The recorded product-facing and frozen calibration results explain the design
priorities:

| Evidence set | Recorded result | What it does not prove |
| --- | --- | --- |
| Semantic navigation v4 | 25 episodes, success rate 0.24, SPL 0.1933, zero modeled collisions | General autonomy, physical perception, or physical collision safety |
| Scripted follow/navigation | Follow 7/9; navigation 2/2 | Identity-safe owner following or ecological validity |
| Gemma conversation | 6/10 machine cases; about 349 ms median first-token latency | Human companion quality |
| Live PersonalConvo | 3/13 turns and 1/8 families | Long-horizon personal continuity |
| Planner quality v2 | 5/5 selected semantic cases; 5.657 s median usable-plan latency | Physical execution or acceptable interactive tail latency |
| Synthetic duplex | Five of nine gates fail | Through-air audio, echo cancellation, or natural barge-in |
| Embodied PlanIR | 4/4 supported deterministic MuJoCo cases; an additional moving-owner case was unsupported | Moving-owner behavior, field sensors, or deployment readiness |

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
expires motion authority and the gateway then stops on TTL. GPU, UI, logging, or
storage failure cannot block gateway/control liveness and need not stop an otherwise
safe deterministic task.

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
- [Historical operational snapshot](CURRENT_STATUS.md) — dated 2026-08-04 and
  therefore historical relative to this audit
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
