# ARCH-1 current structure audit and decomposition register

Snapshot: current working tree at 2026-08-23 15:39 EDT, committed base
`0ce1c5f8bb4a`, with 64 uncommitted/untracked status entries owned by the
in-flight Wave 3 work.

## Census and selection rule

| Measure | Current result |
|---|---:|
| Product Python under `src/parcel_robot` | 317 files / about 158,693 lines |
| Python tests | 399 files / about 198,883 lines |
| Tests collected in the current tree | 9,918 |
| Product modules at least 500 lines | 94 |
| Classes at least 300 lines or 10 direct methods | 94 |
| Functions at least 100 lines or approximate decision count at least 20 | 140 |
| Operational-tooling classes/functions at the same thresholds | 9 / 59 |
| Ruff C901 findings in `src` + `scripts` when enabled | 203 |
| Largest product files | `runtime.py` 16,440; `navigation/pipeline.py` 6,604; `realtime/lane.py` 4,113 |

These thresholds select review candidates; they do not assert that every
candidate should be split. `EXTRACT` means state, timing, or authority is
mixed. `FACADE` means preserve the public object while moving collaborators.
`PRESERVE` means the symbol is large but cohesive or safety-critical and should
first receive stronger tests, not cosmetic fragmentation.

## Complete system-level register

| ID | Current system and principal seams | Proposed decomposition | Priority / risk |
|---|---|---|---|
| D01 | `runtime.py:RobotRuntime` constructs services, owns threads/locks/state, exposes UI snapshots, and tears everything down | `RuntimeAssembly`, immutable `RuntimeServices`, `RuntimeLifecycle`, snapshot aggregators; keep `RobotRuntime` facade | P0 / high |
| D02 | `runtime.py:10254-14576` mixes control tick, behaviors, dispatch, input health, safety records, and narration | deterministic Python `SupervisoryControlLoop`, `MotionDispatchPipeline`, `InputHealthSupervisor`, `SafetyEventRecorder`; native governor remains final after cutover | P0 / critical |
| D03 | Runtime mission/behavior regions own planning, preemption, roam, follow, search, spatial behavior, skills, activities | `MissionCoordinator`, `BehaviorSupervisor`, `RoamService`, `OwnerBehaviorService`, `SkillService` publishing proposals | P0 / high |
| D04 | `backends/base.py:SimObservation` plus `backends/go2.py` carry sim, replay, DDS, UDP, and scan authority | neutral stamped evidence contracts; `go2/{decode,replay,live,observer}`; sim/replay/live adapters | P0 / critical |
| D05 | `navigation/pipeline.py:DirectiveNavigator` owns 113 mutable attributes and the entire semantic-nav lifecycle | state/reducer, person motion, tracking, lock-on, semantic resolver, recovery, route-memory adapter, arrival verifier | P0 / critical |
| D06 | `realtime/audio_gateway.py` combines browser/array lifecycle, PortAudio, playback, capture persistence, acknowledgements, and WebSocket protocol | `AudioGateway` protocol, shared playback/utterance reducers, browser/array adapters, `CaptureRecorder`, `AudioWebSocketSession` | P0 / high |
| D07 | `control/manager.py:ControlManager` mixes lifecycle, locks/thread, freshness, lease/watchdog, stop delivery, confirmation, software E-stop, and teardown | preserve through native characterization, then keep/retire/decompose; extract reducers only if it retains live production risk and never as a second vendor writer | Post-gateway decision / maximum |
| D08 | `scripts/parcel_capture` and `capture/channels.py` mix schemas, device probes, decoders, clock fit, plausibility, attestation, phase runners, and reports | shared schemas; `decoders/{mcap,rosbag2,dds}`; clock-fit; plausibility; attestations; renderers; thin CLIs | P1 / high |
| D09 | `realtime/lane.py:RealtimeLane` owns arming, budget, transport, dispatch, audio assembly, barge-in, tools, beats, accounting, and snapshot | lifecycle, server-event reducer, response assembler, barge-in machine, reconnect policy, accounting | P1 / high |
| D10 | `agent.py` and `realtime/tool_broker.py` duplicate routing, validation, execution, memory, tool schemas, and motion-door concerns | declarative tool registry, `TurnRouter`, `DecisionExecutor`, `ConversationCoordinator`, legacy/realtime adapters | P1 / high |
| D11 | `config.py`, `realtime/config.py`, runtime config DTOs, web composition, profiles, and read-site validators share config authority | immutable section DTOs, one loader/overlay engine, cross-section validator, capability admission, `ApplicationFactory` | P1 / high |
| D12 | `web_panel.py` mixes route dispatch, auth, JSON, WebSocket/audio transport, and runtime construction | route table, small handlers, typed `PanelApi`, auth middleware, WS adapter, separate composition | P1 / medium |
| D13 | `camera_channel/ingress.py` mixes DTO validation, query state, worker lifecycle, detection, localization, and publishing | camera contracts, pure `DetectionLocalizer`, `QueryManager`, `IngressWorker`, `FramePublisher` | P1 / high |
| D14 | perception abstention, lazy VLM registry, online map ingest/resolution/persistence, and owner identity have overlapping admission concerns | pure admission engine, veto-client registry, thread guard; map ingest/resolution/store split; keep owner tracker cohesive initially | P1 / high |
| D15 | `voice_pipeline.py`, `voice_audio.py`, duplex reducers, STT/TTS, device discovery, AEC/VAD, and latency stamps overlap | turn reducer, STT pump, TTS scheduler, device resolver, acoustic chain, latency observer | P1 / high-medium |
| D16 | `scripts/ci_gate.py` combines result DTO, pytest runner, host capability discovery, evaluators, tier registry, rendering, and CLI | `quality/{contracts,runner,capabilities,registry,stages/*}` behind the existing facade | P2 / medium |
| D17 | `ui/index.html` combines about 73 JS functions, views, API, polling, safety, maps, chat, and WebAudio | ES modules/views for API, state, safety, arena, motion, audio, and logs; retain packaged bundle | P2 / medium-low |
| D18 | `sim.py:run_simulator` mixes MuJoCo setup, world state, agents, LiDAR, commands, rendering, IPC, and main loop | `SimWorld`, `SimCommandProcessor`, `SimObservationBuilder`, `SimLoop`, renderer adapter | P2 / medium |
| D19 | `providers.py` combines LLM/STT/TTS implementations, HTTP/msgpack, parsing, streaming, and factory work | provider modules, shared transport, typed parser, speech-stack factory | P2 / low-medium |
| D20 | grid planner/navigator, follow controller, and reactive safety still mix estimation, map update, route planning, local policy, recovery, and final gating | occupancy map vs global route vs local policy; follow estimator vs formation/yield; preserve final safety gate | P2 / critical-high |
| D21 | perception daemon protocol/client are already separated; server still owns socket, dispatch, and model seats | extract request handlers/model-seat lifecycle only if target measurements justify it | Monitor / medium |
| D22 | package initializers and barrel imports collapse domain boundaries and participate in cycles | thin `__init__` files, leaf imports, forbidden-edge and import-order tests, capability admission | Foundation / high leverage |
| D23 | test harness has global hooks, external guard dependency, source-shape pins, giant test modules, and fixture duplication | repo-owned bounded launcher; pytest plugins; shared fake clocks/builders; behavior/contract tests; stable node-ID map | Foundation / high leverage |
| D24 | packaging requires MuJoCo in base while physical target, sidecars, locks, wheel proof, and aarch64 evidence differ | sim extra, target-specific locked environments, clean wheel install, capability smoke, no editable production install | Foundation / high leverage |
| D25 | repository process artifacts and generated evidence dominate navigation and AI context | source-focused index; archive/freeze process records; manifests for external result stores; ADRs for durable decisions | Operations / low code risk |

## Class register

### Extract behind a compatibility facade

| Class | Current concentration | Proposed collaborators |
|---|---|---|
| `RobotRuntime` (`runtime.py:1481`) | 14,942 lines / 345 methods | D01–D03 services; D02 loop |
| `DirectiveNavigator` (`navigation/pipeline.py:494`) | 5,764 / 116 | D05 eight leaf services + reducer |
| `RealtimeLane` (`realtime/lane.py:910`) | 3,146 / 81 | D09 lifecycle/reducers/accounting |
| `VoiceAgent` (`agent.py:78`) | 1,476 / 35 | router, admission, executor, response coordinator |
| `ControlManager` (`control/manager.py:25`) | 1,177 / 27 | current Python writer facade; preserve through native characterization, then explicitly keep/retire/decompose; it must not remain a second vendor writer after cutover |
| `RealtimeToolBroker` (`realtime/tool_broker.py:1068`) | 1,100 / 23 | registry, validator, authority policy, one handler per tool family |
| `GridNavigator` (`navigation/grid_navigator.py:84`) | 1,025 / 17 | observation adapter, local policy, safe-valley/recovery, command shaper |
| `BrowserAudioGateway` (`audio_gateway.py:1014`) | 960 / 31 | browser adapter + shared gateway state + WS protocol |
| `ArrayAudioGateway` (`audio_gateway.py:2299`) | 903 / 31 | PortAudio adapter + shared gateway state + playback scheduler |
| `SessionAudioCapture` (`audio_gateway.py:591`) | 364 / 22 | bounded recorder, index builder/verifier |
| `OnlineSemanticMap` (`online_map.py:363`) | 953 / 33 | observation ingest, resolver, naming/admission, store adapter |
| `RollingGridPlanner` (`grid_planner.py:784`) | 947 / 23 | route search, observed-frontier policy, smoothing, cost policy |
| `RollingOccupancyGrid` (`grid_planner.py:436`) | 346 / 20 | retain as grid owner; extract mask/inflation calculators only if profiling warrants |
| `FollowOwnerController` (`follow.py:425`) | 929 / 26 | motion estimator, formation policy, yield policy, command generator |
| `CameraIngress` (`camera_channel/ingress.py:1023`) | 803 / 18 | query manager, localizer, worker, publisher |
| `DuplexVoiceSession` (`voice_pipeline.py:97`) | 757 / 29 | turn reducer, input pump, output scheduler, cancellation coordinator |
| `Whisperer` (`whisperer.py:808`) | 700 / 20 | observation differ, pacing policy, spend/admission, event recorder |
| `ConversationMemory` (`memory.py:335`) | 689 / 13 | store adapter, recall/ranking policy, realtime-turn writer |
| `TaskExecutive` (`brain/executive.py:199`) | 633 / 21 | task reducer, dispatch adapter, interruption/retry policy |
| `SearchOwnerController` (`search_owner.py:161`) | 613 / 28 | search state, observation update, candidate policy, terminal policy |
| `CommissioningSession` (`commissioning/session.py:375`) | 579 / 31 | protocol/lifecycle, drive procedure, attestation/reporting |
| `RoutePlaceGraph` (`route_memory/place_graph.py:282`) | 527 / 26 | graph core, serialization/parser, query/navigation adapter |
| `RuntimeRequestHandler` (`web_panel.py:243`) | 527 / 15 | route dispatch, auth middleware, endpoint handlers |
| `VoiceIdentityGate` (`voice_identity.py:1108`) | 513 / 21 | profile/store, scoring, decision reducer, evidence log |
| `SemanticTaskRuntimeAdapter` (`brain/runtime_adapter.py:120`) | 512 / 9 | request translator, result mapper, lifecycle adapter |
| `RealtimeDriver` (`realtime/driver.py:150`) | 502 / 17 | transport pump, protocol codec, reconnect/lifecycle |
| `SpatialBehaviorController` (`navigation/spatial.py:272`) | 486 / 21 | behavior reducer, geometry policy, progress/terminal logic |
| `HeadlessCityWorld` (`headless_city.py:128`) | 474 / 27 | scenario definition, world state, observation/application adapters |
| `PerceptionDaemon` (`perception_daemon/server.py:105`) | 415 / 20 | socket server, request router, model-seat lifecycle |
| `WebSocketTransport` (`realtime/ws_transport.py:216`) | 412 / 19 | codec/validation, connection lifecycle, sender/receiver pumps |
| `MicrophoneVoiceLoop` (`voice_audio.py:383`) | 387 / 15 | device/input pump, acoustic processor, endpointing/STT coordinator |
| `TurnController` (`duplex/turn_controller.py:135`) | 380 / 23 | retain reducer facade; extract transition policy and timers if mutation evidence improves |
| `PerceptionChain` (`perception_chain.py:267`) | 343 / 12 | detector orchestration, reconstruction/lift, admission adapter |
| `DeterministicIntentRouter` (`brain/router.py:130`) | 324 / 3 | declarative intent table + slot extractors + routing policy |

### Review locally; do not split solely because of size

The rest of the threshold-selected classes are assigned to their owning D-card
for local review. Cohesive contracts, algorithms, adapters, or test doubles are
`PRESERVE` unless a card demonstrates two state owners or two failure modes:

- mapping/navigation: `SemanticMemory2D`, `StubNavigator`, `PlanValidator`,
  `SkillContractRegistry`, `OwnerTracker`, `MultiObjectTracker`, `PatrolPolicy`,
  `LockOnVerifySession`, `ClearanceProfile`, `GoalArbiter`, `SemanticValueMap2D`,
  `CrossingModePolicy`, `ValueDirectedScanSession`, `ScanBehaviorController`,
  `RelationRegistry`, `SceneSemantics`;
- realtime/voice: `OwnerEventWatcher`, `ChatterScheduler`, `_CaptureStream`,
  `FillerPolicy`, `DuplexCoordinator`, `ActTokenCodec`, `SpeakerSink`,
  `SessionEventLog`;
- perception/I/O: `CameraChannel`, `PhysicalCameraBackendBase`,
  `OwlV2Detector`, `DaemonDetector`, `DaemonClient`, `MultiViewConfirm`,
  `NegativeEvidenceMemory`, `_OnnxSigLIP2Embedder`,
  `PerceptionContentionGuard`;
- storage/config/contracts: `MapEntry`, `OnlineMapStore`, `ConfigStore`,
  `CommissioningRecordV1`, `CommissioningJournal`, `TieredMemory`,
  `PromptLibrary`, `RouteMemoryStore`;
- simulation/evaluation/test doubles: `FakeGatewayCoreV1`,
  `FakeSportServiceV1`, `MujocoSocketBackend`, `HeadlessCityQualityHarness`,
  `MetaUrbanNavEnv`, `EvalPanelState`, `CityWalkerInferenceAdapter`;
- safety/domain leaves: `SafetySupervisor`, `CommandArbiter`, `ReactionHooks`,
  `ReactionArbiter`, `Dog`, `VerdictBureau`, `VetoRunner`,
  `DriftingOdomProvider`.

Fable should reject any follow-on card that silently turns this family-level
review into a blanket “one class per file” exercise.

## High-risk function register

The following are the action candidates from the 140-function threshold
census. Symbols not listed in this section fall into the preserve families in
the next section.

### Runtime and lifecycle — D01/D02/D03

- `RobotRuntime.__init__` `runtime.py:1484` → dependency builders and immutable
  service registry.
- `start` `:4297` and `close` `:4416` → ordered lifecycle plan with rollback.
- `_accept_plan` `:3092`, `_apply_closed_intent` `:3731`,
  `_start_navigation_locked` `:5943`, `_step_roam` `:5355`, and
  `_step_activities` `:6444` → mission/behavior services.
- `submit_voice_text` `:7050`, `submit_realtime_transcript` `:7156`,
  `_hosted_affect` `:7347`, `_build_realtime_sink` `:8185`, and
  `_realtime_navigate` `:9622` → conversation adapters.
- `snapshot` `:9996` and `camera_stream_snapshot` `:13409` → snapshot
  aggregators over immutable service snapshots.
- `_control_loop_body` `:10287`, `_dispatch_active` `:10521`, and
  `_step_navigation` `:11017` → D02 deterministic stages.
- `_attach_configured_camera_ingress` `:11692`,
  `_venue1_attach_physical_ingress` `:12035`, and
  `_venue1_reconcile_map_origin` `:12281` → application factory + ingress
  lifecycle.
- `_voice_stage` `:15932` → voice event reducer and observers.
- Module helpers `scene_report` `:932` and `scene_fact_lines` `:1115` → pure
  scene-report module.

### Navigation — D05/D20

- `DirectiveNavigator.__init__` `pipeline.py:497`, `from_config` `:855`,
  `start` `:1131`, and `step` `:1299` → construction vs reducer lifecycle.
- `_try_detection_lock_on` `:2318`, `_commit_semantic_candidate` `:3049`, and
  `_reanchor_landmark_goal` `:3495` → lock-on/candidate service.
- `_step_semantic_resolution` `:3582` → semantic resolver.
- `_step_scan_behavior` `:3973` and `_step_search_entity_frontier` `:4170` →
  scan/search service.
- `_route_memory_navigate` `:5138` → route-memory adapter.
- `_semantic_arrival_verified` `:5701` and
  `_terminal_environment_is_clear` `:6128` → arrival verifier.
- `GridNavigator.__init__` `grid_navigator.py:112`, `act` `:400`,
  `_safe_valley_command` `:647`, `_select_safe_valley` `:813` → local-policy
  reducer and recovery service.
- `RollingGridPlanner.plan` `grid_planner.py:848`,
  `_observed_goal_or_frontier_path` `:1150`, `_astar` `:1434` → keep A* pure;
  extract evidence/frontier/smoothing policies around it.
- `safe_approach_pose` `approach.py:21`, `resample_inside_region` `:488`,
  `propose_yield_aside` `yield_aside.py:495`, and
  `rank_approach_candidates` `traffic_aware.py:286` → pure geometry/policy
  leaves with property suites.
- `FollowOwnerController._step_behind` `follow.py:926` → formation policy.

### Realtime, tools, and audio — D06/D09/D10/D15

- `RealtimeLane.__init__` `lane.py:913`, `_inject_tail` `:1599`,
  `narrate_event` `:1831`, `_resolve_barge_in_hold` `:2844`,
  `_on_function_call` `:3155`, and `snapshot` `:3916` → D09 collaborators.
- `decide_realtime_arming` `lane.py:599` stays pure; split budget rendering
  from decision inputs only if its contract becomes smaller.
- `build_tool_specs` `tool_broker.py:576` → declarative registry records.
- `RealtimeToolBroker._remember_fact` `:1415` and `_navigate_to` `:1779` →
  memory and motion-authority handlers.
- `VoiceAgent._handle_text` `agent.py:244` and `_execute` `:1202` → turn router
  and decision executor; `tool_definitions` `:1431` consumes the shared
  registry.
- `BrowserAudioGateway.__init__` `audio_gateway.py:1022`,
  `ArrayAudioGateway.__init__` `:2330`, `serve_websocket` `:3228`, and
  `verify_capture_index` `:321` → adapter construction, WS session, recorder
  verifier.
- `DuplexVoiceSession._run_output` `voice_pipeline.py:614` → output scheduler.
- `detect_audio_devices` `audio_io.py:50` → probe adapters plus pure resolver.

### Brain, control, perception, and storage

- `DeterministicIntentRouter.route` `brain/router.py:141` → declarative match
  table and slot extractors.
- `SemanticTaskRuntimeAdapter._result_for` `brain/runtime_adapter.py:374` and
  `dispatch` `:181` → translation and result mapping.
- `TaskExecutive.request_interrupt` `brain/executive.py:549` and
  `_preconditions_satisfied` `:834` → pure task transition/policy functions.
- `build_observation_snapshot` `brain/observations.py:28` → snapshot assembler.
- `ControlManager.start` `control/manager.py:84`, `_tick_once` `:289`, and
  `close` `:711` → D07 collaborators while the facade retains authority.
- `CameraIngress._detect_and_localize` `camera_channel/ingress.py:1421` and
  `localize_detection` `pixel_detections.py:466` → pure localizer pipeline.
- `assess_place_query` `perception_abstention.py:1329` → pure admission engine.
- `OnlineSemanticMap._assess` `online_map.py:944`, `run_naming_pass`
  `online_map/naming.py:409`, and `ConversationMemory.recall`
  `memory.py:671` → policy vs storage separation.
- `ConversationMemory.write_realtime_turn` `memory.py:473` → append-only turn
  writer adapter.
- `OwnerFusionStub.fuse` `uwb/fusion.py:274` → measurement normalization,
  association, and fusion stages.

### Simulation, web, providers, and tooling

- `run_simulator` `sim.py:108` and local `apply_local` `:365` → D18 world,
  command, observation, and loop components.
- `RuntimeRequestHandler.do_GET` `web_panel.py:246`, `do_POST` `:340`,
  `_extract_scene_geometry` `:138` → route table, handlers, scene DTO builder.
- provider `_post_chat_stream` `providers.py:908` → transport vs decoder.
- `load_reasoner_gpu_profile` `reasoner_gpu.py:73` and
  `audit_reasoner_gpu_readiness` `:544` → schema parser, probes, decision, and
  renderer.
- `SkillExecutor.execute` `skills/executor.py:67` → validation, authority
  admission, dispatch, result mapping.
- `HeadlessCityQualityHarness._run_navigation` `headless_city.py:673` → fixture,
  runner, scorer, artifact writer.
- CI and capture hotspots are handled as D08/D16 cards rather than folded into
  product refactors.

## Threshold-selected functions to preserve first

These functions are large or branch-heavy, but they are pure safety kernels,
strict validators, or cohesive algorithms. First add property/mutation tests;
extract only if a later card demonstrates clearer authority without changing
the final oracle:

- safety/final gates: `SafetySupervisor.validate`, `apply_reactive_safety`,
  `apply_collision_brake`, `apply_v8_all_ray_shield`,
  `V8ActionCertificate.__post_init__`;
- strict DTO/config validation: `RobotProfile.__post_init__`,
  `GridPlannerConfig.__post_init__`, `ReactiveSafetyPolicy.__post_init__`,
  `AbstentionPolicy.__post_init__`, `ObservationSnapshot.__post_init__`,
  `CommissioningRecordV1.__post_init__`, `MapObservation.__post_init__`,
  `AppearanceGallery.__post_init__`, `RouteKeyframe.__post_init__`,
  `GroundTruthDetection.__post_init__`, `ArbitrationCandidateV1.__post_init__`;
- coherent algorithms: `RollingGridPlanner._astar`, `analyze_pcm16`,
  `MujocoSocketBackend.observe`, `score_episode`, `score_episode_with_oracle`,
  `_classify_failure`, `_collect_flags`, `_match_strength`,
  `CrossingModePolicy.evaluate`, `PlaceGrounder.ground`,
  `ReactionArbiter.tick`, `PatrolPolicy.sense_from_snapshot`,
  `semantic_goal_from_directive`, `StubNavigator.act`,
  `select_search_entity_frontier`, `rank_approach_candidates`;
- generated/declarative builders: `SkillContractRegistry.default`,
  `capability_entries`, and current tool-schema definitions after they consume
  a declarative registry.

The key distinction is boundary isolation versus cosmetic file splitting.
