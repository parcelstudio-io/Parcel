# ARCH-1 threshold-complete symbol census

Generated at 2026-08-23 15:39 EDT from committed base `0ce1c5f8bb4a` plus the
then-current Wave 3 dirty overlay. This appendix makes
the word “all” auditable: every class with at least 300 lines or 10 direct
methods, and every function with at least 100 lines or an approximate decision
count of 20, appears exactly once below. It is a snapshot, not a generated
product artifact or a demand to split every row.

Dispositions: `EXTRACT_FACADE` means a named facade migration in `DESIGN.md`;
`EXTRACT_FAMILY` means the function moves with its owning component;
`PRESERVE_FIRST` means strengthen property/mutation evidence before any split;
`POST_GATEWAY_DECISION` means keep/retire/decompose only after native cutover;
`LOCAL_REVIEW` means Fable/the owning card decides based on state and failure
ownership, not length alone.

## Classes

| Location | Class | Span / methods | Disposition | Owner |
|---|---|---:|---|---|
| `src/parcel_robot/agent.py:78` | `VoiceAgent` | 1476 / 35 | `EXTRACT_FACADE` | D10 |
| `src/parcel_robot/authority.py:935` | `ClearanceProfile` | 212 / 14 | `LOCAL_REVIEW` | local owner |
| `src/parcel_robot/backends/go2.py:427` | `LiveGo2Sources` | 228 / 10 | `LOCAL_REVIEW` | D04 |
| `src/parcel_robot/backends/go2.py:657` | `Go2Backend` | 286 / 18 | `LOCAL_REVIEW` | D04 |
| `src/parcel_robot/backends/mujoco.py:46` | `MujocoSocketBackend` | 165 / 11 | `PRESERVE_FIRST` | local owner |
| `src/parcel_robot/brain/executive.py:199` | `TaskExecutive` | 633 / 21 | `EXTRACT_FACADE` | D10 |
| `src/parcel_robot/brain/router.py:130` | `DeterministicIntentRouter` | 324 / 3 | `EXTRACT_FACADE` | D10 |
| `src/parcel_robot/brain/runtime_adapter.py:120` | `SemanticTaskRuntimeAdapter` | 512 / 9 | `EXTRACT_FACADE` | D10 |
| `src/parcel_robot/brain/validator.py:141` | `SkillContractRegistry` | 362 / 6 | `PRESERVE_FIRST` | D10 |
| `src/parcel_robot/brain/validator.py:522` | `PlanValidator` | 454 / 10 | `LOCAL_REVIEW` | D10 |
| `src/parcel_robot/bridge/client.py:34` | `FakeGatewayClientV1` | 78 / 10 | `LOCAL_REVIEW` | local owner |
| `src/parcel_robot/bridge/fake_gateway.py:42` | `FakeGatewayCoreV1` | 342 / 21 | `PRESERVE_FIRST` | local owner |
| `src/parcel_robot/bridge/fake_sport.py:158` | `FakeSportServiceV1` | 124 / 11 | `PRESERVE_FIRST` | local owner |
| `src/parcel_robot/camera_channel/backends/physical.py:438` | `PhysicalCameraBackendBase` | 209 / 17 | `LOCAL_REVIEW` | D13 |
| `src/parcel_robot/camera_channel/channel.py:100` | `CameraChannel` | 162 / 14 | `LOCAL_REVIEW` | D13 |
| `src/parcel_robot/camera_channel/ingress.py:1023` | `CameraIngress` | 803 / 18 | `EXTRACT_FACADE` | D13 |
| `src/parcel_robot/commissioning/record.py:456` | `CommissioningRecordV1` | 270 / 17 | `LOCAL_REVIEW` | local owner |
| `src/parcel_robot/commissioning/session.py:104` | `CommissioningJournal` | 155 / 11 | `LOCAL_REVIEW` | local owner |
| `src/parcel_robot/commissioning/session.py:375` | `CommissioningSession` | 579 / 31 | `EXTRACT_FACADE` | local owner |
| `src/parcel_robot/config.py:362` | `ConfigStore` | 238 / 15 | `LOCAL_REVIEW` | D11 |
| `src/parcel_robot/control/manager.py:25` | `ControlManager` | 1177 / 27 | `POST_GATEWAY_DECISION` | D07 |
| `src/parcel_robot/conversation_store.py:314` | `SqliteConversationStore` | 151 / 10 | `LOCAL_REVIEW` | local owner |
| `src/parcel_robot/core/arbiter.py:28` | `CommandArbiter` | 112 / 10 | `PRESERVE_FIRST` | local owner |
| `src/parcel_robot/detection_adapter/false_positive_memory.py:133` | `NegativeEvidenceMemory` | 153 / 13 | `LOCAL_REVIEW` | D14 |
| `src/parcel_robot/detection_adapter/multi_view_confirm.py:106` | `MultiViewConfirm` | 193 / 12 | `LOCAL_REVIEW` | D14 |
| `src/parcel_robot/detection_adapter/owlv2_onnx.py:331` | `OwlV2Detector` | 414 / 14 | `LOCAL_REVIEW` | D14 |
| `src/parcel_robot/detection_adapter/perception_chain.py:267` | `PerceptionChain` | 343 / 12 | `EXTRACT_FACADE` | D14 |
| `src/parcel_robot/duplex/act_codec.py:43` | `ActTokenCodec` | 122 / 12 | `LOCAL_REVIEW` | D15 |
| `src/parcel_robot/duplex/coordinator.py:21` | `DuplexCoordinator` | 213 / 21 | `LOCAL_REVIEW` | D15 |
| `src/parcel_robot/duplex/filler_policy.py:20` | `FillerPolicy` | 167 / 11 | `LOCAL_REVIEW` | D15 |
| `src/parcel_robot/duplex/turn_controller.py:135` | `TurnController` | 380 / 23 | `PRESERVE_FIRST` | D15 |
| `src/parcel_robot/eval_panel.py:29` | `EvalPanelState` | 294 / 11 | `LOCAL_REVIEW` | local owner |
| `src/parcel_robot/expression.py:263` | `ReactionHooks` | 108 / 10 | `PRESERVE_FIRST` | local owner |
| `src/parcel_robot/headless_city.py:128` | `HeadlessCityWorld` | 474 / 27 | `EXTRACT_FACADE` | D18 |
| `src/parcel_robot/headless_city.py:604` | `HeadlessCityQualityHarness` | 323 / 8 | `LOCAL_REVIEW` | D18 |
| `src/parcel_robot/instructnav/arbiter.py:219` | `GoalArbiter` | 209 / 14 | `LOCAL_REVIEW` | D20 |
| `src/parcel_robot/instructnav/memory.py:65` | `SemanticMemory2D` | 385 / 13 | `LOCAL_REVIEW` | D20 |
| `src/parcel_robot/instructnav/siglip2_onnx.py:147` | `_OnnxSigLIP2Embedder` | 227 / 10 | `LOCAL_REVIEW` | D20 |
| `src/parcel_robot/maps/crossing.py:100` | `CrossingModePolicy` | 221 / 11 | `LOCAL_REVIEW` | local owner |
| `src/parcel_robot/memory.py:335` | `ConversationMemory` | 689 / 13 | `EXTRACT_FACADE` | local owner |
| `src/parcel_robot/navigation/envs/metaurban_env.py:13` | `MetaUrbanNavEnv` | 187 / 10 | `LOCAL_REVIEW` | D20 |
| `src/parcel_robot/navigation/follow.py:425` | `FollowOwnerController` | 929 / 26 | `EXTRACT_FACADE` | D20 |
| `src/parcel_robot/navigation/grid_navigator.py:84` | `GridNavigator` | 1025 / 17 | `EXTRACT_FACADE` | D20 |
| `src/parcel_robot/navigation/grid_planner.py:436` | `RollingOccupancyGrid` | 346 / 20 | `PRESERVE_FIRST` | D20 |
| `src/parcel_robot/navigation/grid_planner.py:784` | `RollingGridPlanner` | 947 / 23 | `EXTRACT_FACADE` | D20 |
| `src/parcel_robot/navigation/instructnav_recovery.py:42` | `ScanBehaviorController` | 155 / 11 | `LOCAL_REVIEW` | D20 |
| `src/parcel_robot/navigation/lock_on_verify.py:647` | `LockOnVerifySession` | 212 / 14 | `LOCAL_REVIEW` | D20 |
| `src/parcel_robot/navigation/models/__init__.py:19` | `StubNavigator` | 378 / 12 | `LOCAL_REVIEW` | D20 |
| `src/parcel_robot/navigation/owner_prediction.py:22` | `OwnerMotionPredictor` | 175 / 10 | `LOCAL_REVIEW` | D20 |
| `src/parcel_robot/navigation/pipeline.py:494` | `DirectiveNavigator` | 5764 / 116 | `EXTRACT_FACADE` | D05 |
| `src/parcel_robot/navigation/relation_registry.py:383` | `RelationRegistry` | 79 / 10 | `LOCAL_REVIEW` | D20 |
| `src/parcel_robot/navigation/search_owner.py:161` | `SearchOwnerController` | 613 / 28 | `EXTRACT_FACADE` | D20 |
| `src/parcel_robot/navigation/spatial.py:272` | `SpatialBehaviorController` | 486 / 21 | `EXTRACT_FACADE` | D20 |
| `src/parcel_robot/navigation/tracker.py:208` | `MultiObjectTracker` | 249 / 21 | `LOCAL_REVIEW` | D20 |
| `src/parcel_robot/navigation/value_directed_scan.py:52` | `ValueDirectedScanSession` | 171 / 11 | `LOCAL_REVIEW` | D20 |
| `src/parcel_robot/navigation/value_map.py:71` | `SemanticValueMap2D` | 222 / 12 | `LOCAL_REVIEW` | D20 |
| `src/parcel_robot/online_map/entries.py:658` | `MapEntry` | 245 / 11 | `LOCAL_REVIEW` | D14 |
| `src/parcel_robot/online_map/online_map.py:363` | `OnlineSemanticMap` | 953 / 33 | `EXTRACT_FACADE` | D14 |
| `src/parcel_robot/online_map/store.py:165` | `OnlineMapStore` | 269 / 15 | `LOCAL_REVIEW` | D14 |
| `src/parcel_robot/owner_tracking/tracker.py:351` | `OwnerTracker` | 332 / 15 | `LOCAL_REVIEW` | D14 |
| `src/parcel_robot/patrol/mission.py:383` | `PatrolPolicy` | 241 / 10 | `LOCAL_REVIEW` | D20 |
| `src/parcel_robot/perception_contention.py:251` | `PerceptionContentionGuard` | 226 / 10 | `LOCAL_REVIEW` | D14 |
| `src/parcel_robot/perception_daemon/client.py:95` | `DaemonClient` | 138 / 12 | `LOCAL_REVIEW` | D21 |
| `src/parcel_robot/perception_daemon/client.py:243` | `DaemonDetector` | 213 / 13 | `LOCAL_REVIEW` | D21 |
| `src/parcel_robot/perception_daemon/server.py:105` | `PerceptionDaemon` | 415 / 20 | `EXTRACT_FACADE` | D21 |
| `src/parcel_robot/pose.py:366` | `DriftingOdomProvider` | 284 / 10 | `LOCAL_REVIEW` | local owner |
| `src/parcel_robot/prompting/loader.py:32` | `PromptLibrary` | 199 / 15 | `LOCAL_REVIEW` | local owner |
| `src/parcel_robot/realtime/audio_gateway.py:415` | `_CaptureStream` | 170 / 11 | `LOCAL_REVIEW` | D06 |
| `src/parcel_robot/realtime/audio_gateway.py:591` | `SessionAudioCapture` | 364 / 22 | `EXTRACT_FACADE` | D06 |
| `src/parcel_robot/realtime/audio_gateway.py:1014` | `BrowserAudioGateway` | 960 / 31 | `EXTRACT_FACADE` | D06 |
| `src/parcel_robot/realtime/audio_gateway.py:2299` | `ArrayAudioGateway` | 903 / 31 | `EXTRACT_FACADE` | D06 |
| `src/parcel_robot/realtime/driver.py:150` | `RealtimeDriver` | 502 / 17 | `EXTRACT_FACADE` | local owner |
| `src/parcel_robot/realtime/evidence_log.py:128` | `SessionEventLog` | 306 / 16 | `LOCAL_REVIEW` | local owner |
| `src/parcel_robot/realtime/lane.py:910` | `RealtimeLane` | 3146 / 81 | `EXTRACT_FACADE` | D09 |
| `src/parcel_robot/realtime/tool_broker.py:1068` | `RealtimeToolBroker` | 1100 / 23 | `EXTRACT_FACADE` | D10 |
| `src/parcel_robot/realtime/voice_identity.py:1108` | `VoiceIdentityGate` | 513 / 21 | `EXTRACT_FACADE` | local owner |
| `src/parcel_robot/realtime/whisperer.py:808` | `Whisperer` | 700 / 20 | `EXTRACT_FACADE` | local owner |
| `src/parcel_robot/realtime/whisperer.py:1560` | `OwnerEventWatcher` | 237 / 11 | `LOCAL_REVIEW` | local owner |
| `src/parcel_robot/realtime/whisperer.py:1951` | `ChatterScheduler` | 197 / 10 | `LOCAL_REVIEW` | local owner |
| `src/parcel_robot/realtime/ws_transport.py:216` | `WebSocketTransport` | 412 / 19 | `EXTRACT_FACADE` | local owner |
| `src/parcel_robot/route_memory/citywalker.py:146` | `CityWalkerInferenceAdapter` | 179 / 10 | `LOCAL_REVIEW` | D20 |
| `src/parcel_robot/route_memory/memory.py:257` | `RouteMemoryStore` | 86 / 10 | `LOCAL_REVIEW` | D20 |
| `src/parcel_robot/route_memory/place_graph.py:282` | `RoutePlaceGraph` | 527 / 26 | `EXTRACT_FACADE` | D20 |
| `src/parcel_robot/runtime.py:1481` | `RobotRuntime` | 14942 / 345 | `EXTRACT_FACADE` | D01–D03 |
| `src/parcel_robot/safety.py:115` | `SafetySupervisor` | 203 / 10 | `PRESERVE_FIRST` | local owner |
| `src/parcel_robot/scene_semantics.py:109` | `SceneSemantics` | 68 / 10 | `LOCAL_REVIEW` | local owner |
| `src/parcel_robot/skills/api.py:40` | `Dog` | 220 / 18 | `LOCAL_REVIEW` | local owner |
| `src/parcel_robot/tiered_memory.py:200` | `TieredMemory` | 231 / 14 | `LOCAL_REVIEW` | local owner |
| `src/parcel_robot/vlm_veto/bureau.py:223` | `VerdictBureau` | 254 / 16 | `LOCAL_REVIEW` | local owner |
| `src/parcel_robot/vlm_veto/runner.py:190` | `VetoRunner` | 232 / 12 | `LOCAL_REVIEW` | local owner |
| `src/parcel_robot/voice_audio.py:383` | `MicrophoneVoiceLoop` | 387 / 15 | `EXTRACT_FACADE` | D15 |
| `src/parcel_robot/voice_audio.py:772` | `SpeakerSink` | 228 / 14 | `LOCAL_REVIEW` | D15 |
| `src/parcel_robot/voice_pipeline.py:97` | `DuplexVoiceSession` | 757 / 29 | `EXTRACT_FACADE` | D15 |
| `src/parcel_robot/web_panel.py:243` | `RuntimeRequestHandler` | 527 / 15 | `EXTRACT_FACADE` | D12 |

Class rows: **94**.

## Functions and methods

| Location | Qualified symbol | Span / decisions | Disposition | Owner |
|---|---|---:|---|---|
| `src/parcel_robot/admission.py:258` | `broker_scan` | 89 / 20 | `LOCAL_REVIEW` | local owner |
| `src/parcel_robot/admission.py:831` | `capability_entries` | 131 / 13 | `PRESERVE_FIRST` | local owner |
| `src/parcel_robot/agent.py:85` | `VoiceAgent.__init__` | 107 / 7 | `EXTRACT_FAMILY` | D10 |
| `src/parcel_robot/agent.py:244` | `VoiceAgent._handle_text` | 396 / 59 | `EXTRACT_FAMILY` | D10 |
| `src/parcel_robot/agent.py:1202` | `VoiceAgent._execute` | 189 / 69 | `EXTRACT_FAMILY` | D10 |
| `src/parcel_robot/agent.py:1431` | `VoiceAgent.tool_definitions` | 123 / 4 | `EXTRACT_FAMILY` | D10 |
| `src/parcel_robot/attention/arbiter.py:82` | `ReactionArbiter.tick` | 101 / 23 | `PRESERVE_FIRST` | local owner |
| `src/parcel_robot/audio_io.py:50` | `detect_audio_devices` | 125 / 26 | `EXTRACT_FAMILY` | D15 |
| `src/parcel_robot/backends/mujoco.py:55` | `MujocoSocketBackend.observe` | 124 / 38 | `PRESERVE_FIRST` | local owner |
| `src/parcel_robot/brain/contracts.py:845` | `ObservationSnapshot.__post_init__` | 41 / 20 | `PRESERVE_FIRST` | D10 |
| `src/parcel_robot/brain/executive.py:834` | `_preconditions_satisfied` | 47 / 27 | `EXTRACT_FAMILY` | D10 |
| `src/parcel_robot/brain/executive.py:549` | `TaskExecutive.request_interrupt` | 67 / 25 | `EXTRACT_FAMILY` | D10 |
| `src/parcel_robot/brain/observations.py:28` | `build_observation_snapshot` | 119 / 25 | `EXTRACT_FAMILY` | D10 |
| `src/parcel_robot/brain/router.py:141` | `DeterministicIntentRouter.route` | 282 / 40 | `EXTRACT_FAMILY` | D10 |
| `src/parcel_robot/brain/runtime_adapter.py:181` | `SemanticTaskRuntimeAdapter.dispatch` | 96 / 24 | `EXTRACT_FAMILY` | D10 |
| `src/parcel_robot/brain/runtime_adapter.py:374` | `SemanticTaskRuntimeAdapter._result_for` | 258 / 64 | `EXTRACT_FAMILY` | D10 |
| `src/parcel_robot/brain/validator.py:173` | `SkillContractRegistry.default` | 246 / 2 | `PRESERVE_FIRST` | D10 |
| `src/parcel_robot/brain/validator.py:779` | `PlanValidator._validate_argument_profile` | 75 / 23 | `EXTRACT_FAMILY` | D10 |
| `src/parcel_robot/camera_channel/ingress.py:1421` | `CameraIngress._detect_and_localize` | 265 / 25 | `EXTRACT_FAMILY` | D13 |
| `src/parcel_robot/commissioning/record.py:478` | `CommissioningRecordV1.__post_init__` | 36 / 23 | `PRESERVE_FIRST` | local owner |
| `src/parcel_robot/control/factory.py:225` | `build_unitree_sport_commissioning_session` | 116 / 6 | `LOCAL_REVIEW` | local owner |
| `src/parcel_robot/control/manager.py:84` | `ControlManager.start` | 103 / 23 | `POST_GATEWAY_DECISION` | D07 |
| `src/parcel_robot/control/manager.py:289` | `ControlManager._tick_once` | 183 / 50 | `POST_GATEWAY_DECISION` | D07 |
| `src/parcel_robot/control/manager.py:711` | `ControlManager.close` | 197 / 49 | `POST_GATEWAY_DECISION` | D07 |
| `src/parcel_robot/counterfactual/arbitration_log.py:46` | `ArbitrationCandidateV1.__post_init__` | 25 / 22 | `PRESERVE_FIRST` | local owner |
| `src/parcel_robot/detection_adapter/adapter.py:37` | `GroundTruthDetection.__post_init__` | 28 / 21 | `PRESERVE_FIRST` | D14 |
| `src/parcel_robot/detection_adapter/pixel_detections.py:466` | `localize_detection` | 149 / 12 | `EXTRACT_FAMILY` | D14 |
| `src/parcel_robot/headless_city.py:252` | `HeadlessCityWorld.apply_placement_overrides` | 86 / 26 | `EXTRACT_FAMILY` | D18 |
| `src/parcel_robot/headless_city.py:673` | `HeadlessCityQualityHarness._run_navigation` | 101 / 19 | `EXTRACT_FAMILY` | D18 |
| `src/parcel_robot/instructnav/grounding.py:304` | `_as_candidate_dict` | 94 / 28 | `EXTRACT_FAMILY` | D20 |
| `src/parcel_robot/instructnav/memory.py:456` | `_parse_observation` | 41 / 20 | `EXTRACT_FAMILY` | D20 |
| `src/parcel_robot/instructnav/scoring.py:1535` | `score_episode` | 104 / 19 | `PRESERVE_FIRST` | D20 |
| `src/parcel_robot/instructnav/scoring.py:1641` | `score_episode_with_oracle` | 138 / 15 | `PRESERVE_FIRST` | D20 |
| `src/parcel_robot/instructnav/scoring.py:1781` | `_classify_failure` | 51 / 20 | `PRESERVE_FIRST` | D20 |
| `src/parcel_robot/instructnav/scoring.py:1834` | `_collect_flags` | 69 / 30 | `PRESERVE_FIRST` | D20 |
| `src/parcel_robot/maps/crossing.py:172` | `CrossingModePolicy.evaluate` | 136 / 19 | `PRESERVE_FIRST` | local owner |
| `src/parcel_robot/memory.py:473` | `ConversationMemory.write_realtime_turn` | 117 / 10 | `LOCAL_REVIEW` | local owner |
| `src/parcel_robot/memory.py:671` | `ConversationMemory.recall` | 120 / 21 | `LOCAL_REVIEW` | local owner |
| `src/parcel_robot/navigation/approach.py:21` | `safe_approach_pose` | 290 / 26 | `EXTRACT_FAMILY` | D20 |
| `src/parcel_robot/navigation/approach.py:488` | `resample_inside_region` | 114 / 27 | `EXTRACT_FAMILY` | D20 |
| `src/parcel_robot/navigation/collision.py:100` | `apply_collision_brake` | 90 / 23 | `PRESERVE_FIRST` | D20 |
| `src/parcel_robot/navigation/detection_lock_on.py:398` | `candidate_to_detection_msg` | 58 / 20 | `EXTRACT_FAMILY` | D20 |
| `src/parcel_robot/navigation/experimental_all_ray_shield.py:530` | `apply_v8_all_ray_shield` | 124 / 16 | `PRESERVE_FIRST` | D20 |
| `src/parcel_robot/navigation/experimental_all_ray_shield.py:162` | `V8ActionCertificate.__post_init__` | 90 / 28 | `PRESERVE_FIRST` | D20 |
| `src/parcel_robot/navigation/follow.py:926` | `FollowOwnerController._step_behind` | 129 / 16 | `EXTRACT_FAMILY` | D20 |
| `src/parcel_robot/navigation/goals.py:303` | `semantic_goal_from_directive` | 120 / 10 | `PRESERVE_FIRST` | D20 |
| `src/parcel_robot/navigation/grid_navigator.py:112` | `GridNavigator.__init__` | 239 / 31 | `EXTRACT_FAMILY` | D20 |
| `src/parcel_robot/navigation/grid_navigator.py:400` | `GridNavigator.act` | 184 / 31 | `EXTRACT_FAMILY` | D20 |
| `src/parcel_robot/navigation/grid_navigator.py:647` | `GridNavigator._safe_valley_command` | 152 / 13 | `EXTRACT_FAMILY` | D20 |
| `src/parcel_robot/navigation/grid_navigator.py:813` | `GridNavigator._select_safe_valley` | 116 / 19 | `EXTRACT_FAMILY` | D20 |
| `src/parcel_robot/navigation/grid_planner.py:208` | `GridPlannerConfig.__post_init__` | 96 / 38 | `PRESERVE_FIRST` | D20 |
| `src/parcel_robot/navigation/grid_planner.py:848` | `RollingGridPlanner.plan` | 177 / 27 | `EXTRACT_FAMILY` | D20 |
| `src/parcel_robot/navigation/grid_planner.py:1150` | `RollingGridPlanner._observed_goal_or_frontier_path` | 184 / 28 | `EXTRACT_FAMILY` | D20 |
| `src/parcel_robot/navigation/grid_planner.py:1434` | `RollingGridPlanner._astar` | 72 / 23 | `PRESERVE_FIRST` | D20 |
| `src/parcel_robot/navigation/grounder.py:90` | `PlaceGrounder.ground` | 56 / 24 | `PRESERVE_FIRST` | D20 |
| `src/parcel_robot/navigation/instructnav_recovery.py:246` | `select_search_entity_frontier` | 100 / 16 | `PRESERVE_FIRST` | D20 |
| `src/parcel_robot/navigation/models/__init__.py:99` | `StubNavigator.act` | 138 / 23 | `PRESERVE_FIRST` | D20 |
| `src/parcel_robot/navigation/pipeline.py:497` | `DirectiveNavigator.__init__` | 356 / 42 | `EXTRACT_FAMILY` | D05 |
| `src/parcel_robot/navigation/pipeline.py:855` | `DirectiveNavigator.from_config` | 220 / 22 | `EXTRACT_FAMILY` | D05 |
| `src/parcel_robot/navigation/pipeline.py:1299` | `DirectiveNavigator.step` | 164 / 35 | `EXTRACT_FAMILY` | D05 |
| `src/parcel_robot/navigation/pipeline.py:2318` | `DirectiveNavigator._try_detection_lock_on` | 111 / 12 | `EXTRACT_FAMILY` | D05 |
| `src/parcel_robot/navigation/pipeline.py:3049` | `DirectiveNavigator._commit_semantic_candidate` | 221 / 13 | `EXTRACT_FAMILY` | D05 |
| `src/parcel_robot/navigation/pipeline.py:3495` | `DirectiveNavigator._reanchor_landmark_goal` | 86 / 20 | `EXTRACT_FAMILY` | D05 |
| `src/parcel_robot/navigation/pipeline.py:3582` | `DirectiveNavigator._step_semantic_resolution` | 353 / 46 | `EXTRACT_FAMILY` | D05 |
| `src/parcel_robot/navigation/pipeline.py:3973` | `DirectiveNavigator._step_scan_behavior` | 196 / 32 | `EXTRACT_FAMILY` | D05 |
| `src/parcel_robot/navigation/pipeline.py:4170` | `DirectiveNavigator._step_search_entity_frontier` | 118 / 17 | `EXTRACT_FAMILY` | D05 |
| `src/parcel_robot/navigation/pipeline.py:5138` | `DirectiveNavigator._route_memory_navigate` | 100 / 11 | `EXTRACT_FAMILY` | D05 |
| `src/parcel_robot/navigation/pipeline.py:5701` | `DirectiveNavigator._semantic_arrival_verified` | 111 / 24 | `EXTRACT_FAMILY` | D05 |
| `src/parcel_robot/navigation/pipeline.py:6128` | `DirectiveNavigator._terminal_environment_is_clear` | 97 / 23 | `EXTRACT_FAMILY` | D05 |
| `src/parcel_robot/navigation/reactive_safety.py:434` | `apply_reactive_safety` | 139 / 38 | `PRESERVE_FIRST` | D20 |
| `src/parcel_robot/navigation/reactive_safety.py:211` | `ReactiveSafetyPolicy.__post_init__` | 127 / 11 | `PRESERVE_FIRST` | D20 |
| `src/parcel_robot/navigation/semantic_map.py:95` | `_abstention_filtered` | 128 / 23 | `EXTRACT_FAMILY` | D20 |
| `src/parcel_robot/navigation/semantic_map.py:485` | `_candidate` | 41 / 20 | `EXTRACT_FAMILY` | D20 |
| `src/parcel_robot/navigation/semantic_map.py:585` | `_match_strength` | 80 / 26 | `EXTRACT_FAMILY` | D20 |
| `src/parcel_robot/navigation/traffic_aware.py:286` | `rank_approach_candidates` | 115 / 20 | `PRESERVE_FIRST` | D20 |
| `src/parcel_robot/navigation/yield_aside.py:495` | `propose_yield_aside` | 175 / 24 | `EXTRACT_FAMILY` | D20 |
| `src/parcel_robot/online_map/entries.py:535` | `MapObservation.__post_init__` | 76 / 23 | `PRESERVE_FIRST` | D14 |
| `src/parcel_robot/online_map/naming.py:409` | `run_naming_pass` | 139 / 16 | `EXTRACT_FAMILY` | D14 |
| `src/parcel_robot/online_map/online_map.py:944` | `OnlineSemanticMap._assess` | 106 / 11 | `EXTRACT_FAMILY` | D14 |
| `src/parcel_robot/owner_tracking/gallery.py:240` | `AppearanceGallery.__post_init__` | 74 / 27 | `PRESERVE_FIRST` | D14 |
| `src/parcel_robot/patrol/mission.py:748` | `sense_from_snapshot` | 105 / 24 | `EXTRACT_FAMILY` | D20 |
| `src/parcel_robot/perception_abstention.py:1329` | `assess_place_query` | 202 / 37 | `EXTRACT_FAMILY` | D14 |
| `src/parcel_robot/perception_abstention.py:580` | `AbstentionPolicy.__post_init__` | 92 / 24 | `PRESERVE_FIRST` | D14 |
| `src/parcel_robot/prosody.py:82` | `analyze_pcm16` | 109 / 13 | `PRESERVE_FIRST` | local owner |
| `src/parcel_robot/providers.py:908` | `_post_chat_stream` | 74 / 27 | `EXTRACT_FAMILY` | D19 |
| `src/parcel_robot/realtime/audio_gateway.py:321` | `verify_capture_index` | 92 / 29 | `EXTRACT_FAMILY` | D06 |
| `src/parcel_robot/realtime/audio_gateway.py:3228` | `serve_websocket` | 142 / 33 | `EXTRACT_FAMILY` | D06 |
| `src/parcel_robot/realtime/audio_gateway.py:1022` | `BrowserAudioGateway.__init__` | 121 / 1 | `EXTRACT_FAMILY` | D06 |
| `src/parcel_robot/realtime/audio_gateway.py:2330` | `ArrayAudioGateway.__init__` | 107 / 0 | `EXTRACT_FAMILY` | D06 |
| `src/parcel_robot/realtime/lane.py:599` | `decide_realtime_arming` | 121 / 8 | `EXTRACT_FAMILY` | D09 |
| `src/parcel_robot/realtime/lane.py:913` | `RealtimeLane.__init__` | 421 / 5 | `EXTRACT_FAMILY` | D09 |
| `src/parcel_robot/realtime/lane.py:1599` | `RealtimeLane._inject_tail` | 107 / 8 | `EXTRACT_FAMILY` | D09 |
| `src/parcel_robot/realtime/lane.py:1831` | `RealtimeLane.narrate_event` | 132 / 9 | `EXTRACT_FAMILY` | D09 |
| `src/parcel_robot/realtime/lane.py:2844` | `RealtimeLane._resolve_barge_in_hold` | 130 / 9 | `EXTRACT_FAMILY` | D09 |
| `src/parcel_robot/realtime/lane.py:3155` | `RealtimeLane._on_function_call` | 103 / 5 | `EXTRACT_FAMILY` | D09 |
| `src/parcel_robot/realtime/lane.py:3916` | `RealtimeLane.snapshot` | 140 / 5 | `EXTRACT_FAMILY` | D09 |
| `src/parcel_robot/realtime/tool_broker.py:576` | `build_tool_specs` | 374 / 4 | `EXTRACT_FAMILY` | D10 |
| `src/parcel_robot/realtime/tool_broker.py:1415` | `RealtimeToolBroker._remember_fact` | 155 / 13 | `EXTRACT_FAMILY` | D10 |
| `src/parcel_robot/realtime/tool_broker.py:1779` | `RealtimeToolBroker._navigate_to` | 133 / 17 | `EXTRACT_FAMILY` | D10 |
| `src/parcel_robot/realtime/voice_identity.py:1417` | `VoiceIdentityGate._verify_locked` | 100 / 9 | `LOCAL_REVIEW` | local owner |
| `src/parcel_robot/realtime/whisperer.py:1171` | `Whisperer._pace_watch` | 120 / 11 | `LOCAL_REVIEW` | local owner |
| `src/parcel_robot/reasoner_gpu.py:73` | `load_reasoner_gpu_profile` | 100 / 57 | `EXTRACT_FAMILY` | D19 |
| `src/parcel_robot/reasoner_gpu.py:544` | `audit_reasoner_gpu_readiness` | 335 / 55 | `EXTRACT_FAMILY` | D19 |
| `src/parcel_robot/robot_profile.py:58` | `RobotProfile.__post_init__` | 33 / 23 | `PRESERVE_FIRST` | local owner |
| `src/parcel_robot/route_memory/memory.py:79` | `RouteKeyframe.__post_init__` | 36 / 20 | `PRESERVE_FIRST` | D20 |
| `src/parcel_robot/runtime.py:932` | `scene_report` | 128 / 27 | `EXTRACT_FAMILY` | D01–D03 |
| `src/parcel_robot/runtime.py:1115` | `scene_fact_lines` | 53 / 21 | `EXTRACT_FAMILY` | D01–D03 |
| `src/parcel_robot/runtime.py:1484` | `RobotRuntime.__init__` | 1333 / 73 | `EXTRACT_FAMILY` | D01–D03 |
| `src/parcel_robot/runtime.py:3092` | `RobotRuntime._accept_plan` | 123 / 21 | `EXTRACT_FAMILY` | D01–D03 |
| `src/parcel_robot/runtime.py:3731` | `RobotRuntime._apply_closed_intent` | 138 / 25 | `EXTRACT_FAMILY` | D01–D03 |
| `src/parcel_robot/runtime.py:4297` | `RobotRuntime.start` | 118 / 8 | `EXTRACT_FAMILY` | D01–D03 |
| `src/parcel_robot/runtime.py:4416` | `RobotRuntime.close` | 124 / 28 | `EXTRACT_FAMILY` | D01–D03 |
| `src/parcel_robot/runtime.py:5386` | `RobotRuntime._step_roam` | 123 / 18 | `EXTRACT_FAMILY` | D01–D03 |
| `src/parcel_robot/runtime.py:5974` | `RobotRuntime._start_navigation_locked` | 112 / 26 | `EXTRACT_FAMILY` | D01–D03 |
| `src/parcel_robot/runtime.py:6475` | `RobotRuntime._step_activities` | 110 / 18 | `EXTRACT_FAMILY` | D01–D03 |
| `src/parcel_robot/runtime.py:7081` | `RobotRuntime.submit_voice_text` | 105 / 12 | `EXTRACT_FAMILY` | D01–D03 |
| `src/parcel_robot/runtime.py:7187` | `RobotRuntime.submit_realtime_transcript` | 185 / 18 | `EXTRACT_FAMILY` | D01–D03 |
| `src/parcel_robot/runtime.py:7378` | `RobotRuntime._hosted_affect` | 143 / 7 | `EXTRACT_FAMILY` | D01–D03 |
| `src/parcel_robot/runtime.py:8216` | `RobotRuntime._build_realtime_sink` | 108 / 7 | `EXTRACT_FAMILY` | D01–D03 |
| `src/parcel_robot/runtime.py:9653` | `RobotRuntime._realtime_navigate` | 134 / 9 | `EXTRACT_FAMILY` | D01–D03 |
| `src/parcel_robot/runtime.py:10027` | `RobotRuntime.snapshot` | 231 / 19 | `EXTRACT_FAMILY` | D01–D03 |
| `src/parcel_robot/runtime.py:10318` | `RobotRuntime._control_loop_body` | 180 / 16 | `EXTRACT_FAMILY` | D01–D03 |
| `src/parcel_robot/runtime.py:10552` | `RobotRuntime._dispatch_active` | 188 / 31 | `EXTRACT_FAMILY` | D01–D03 |
| `src/parcel_robot/runtime.py:11048` | `RobotRuntime._step_navigation` | 211 / 42 | `EXTRACT_FAMILY` | D01–D03 |
| `src/parcel_robot/runtime.py:11723` | `RobotRuntime._attach_configured_camera_ingress` | 155 / 11 | `EXTRACT_FAMILY` | D01–D03 |
| `src/parcel_robot/runtime.py:12066` | `RobotRuntime._venue1_attach_physical_ingress` | 153 / 11 | `EXTRACT_FAMILY` | D01–D03 |
| `src/parcel_robot/runtime.py:12312` | `RobotRuntime._venue1_reconcile_map_origin` | 127 / 17 | `EXTRACT_FAMILY` | D01–D03 |
| `src/parcel_robot/runtime.py:13440` | `RobotRuntime.camera_stream_snapshot` | 136 / 24 | `EXTRACT_FAMILY` | D01–D03 |
| `src/parcel_robot/runtime.py:13830` | `RobotRuntime._evaluate_dispatch_input_health` | 122 / 8 | `EXTRACT_FAMILY` | D01–D03 |
| `src/parcel_robot/runtime.py:15986` | `RobotRuntime._voice_stage` | 164 / 36 | `EXTRACT_FAMILY` | D01–D03 |
| `src/parcel_robot/safety.py:133` | `SafetySupervisor.validate` | 55 / 25 | `PRESERVE_FIRST` | local owner |
| `src/parcel_robot/sim.py:108` | `run_simulator` | 434 / 91 | `EXTRACT_FAMILY` | D18 |
| `src/parcel_robot/sim.py:365` | `apply_local` | 91 / 23 | `EXTRACT_FAMILY` | D18 |
| `src/parcel_robot/sim_ipc.py:163` | `validate_simulator_message` | 62 / 28 | `LOCAL_REVIEW` | local owner |
| `src/parcel_robot/skills/executor.py:67` | `SkillExecutor.execute` | 102 / 19 | `LOCAL_REVIEW` | local owner |
| `src/parcel_robot/uwb/fusion.py:274` | `OwnerFusionStub.fuse` | 155 / 24 | `LOCAL_REVIEW` | local owner |
| `src/parcel_robot/voice_pipeline.py:614` | `DuplexVoiceSession._run_output` | 133 / 27 | `EXTRACT_FAMILY` | D15 |
| `src/parcel_robot/web_panel.py:138` | `_extract_scene_geometry` | 74 / 24 | `EXTRACT_FAMILY` | D12 |
| `src/parcel_robot/web_panel.py:246` | `RuntimeRequestHandler.do_GET` | 93 / 20 | `EXTRACT_FAMILY` | D12 |
| `src/parcel_robot/web_panel.py:340` | `RuntimeRequestHandler.do_POST` | 240 / 31 | `EXTRACT_FAMILY` | D12 |

Function/method rows: **140**.

## Operational tooling classes

Operational scripts and repository tools use the same threshold. Tests and
evaluation functions are intentionally not enumerated one by one: D23 and the
test/eval plan split them by observable product seam, and source-test length
alone is not an implementation boundary.

| Location | Class | Span / methods | Disposition | Owner |
|---|---|---:|---|---|
| `scripts/parcel_capture/attest.py:543` | `HardwareAttestationV1` | 306 / 19 | `EXTRACT_FAMILY` | D08 |
| `scripts/parcel_capture/budget.py:832` | `Budget` | 127 / 15 | `EXTRACT_FAMILY` | D08 |
| `scripts/parcel_capture/ingest/base.py:594` | `IngestAdapter` | 205 / 10 | `EXTRACT_FAMILY` | D08 |
| `scripts/parcel_capture/record.py:556` | `_Cursor` | 55 / 10 | `EXTRACT_FAMILY` | D08 |
| `scripts/parcel_capture/record.py:1018` | `CaptureRecorder` | 337 / 20 | `EXTRACT_FAMILY` | D08 |
| `scripts/parcel_capture/rosbag2.py:1151` | `_Cursor` | 67 / 11 | `EXTRACT_FAMILY` | D08 |
| `scripts/parcel_capture/rosbag2.py:1597` | `_CdrCursor` | 79 / 11 | `EXTRACT_FAMILY` | D08 |
| `scripts/parcel_capture/syncevents.py:2320` | `SyncFitV1` | 249 / 12 | `EXTRACT_FAMILY` | D08 |
| `tools/run_voice_corpus.py:969` | `CorpusRunner` | 323 / 7 | `LOCAL_REVIEW` | local tooling owner |

Operational class rows: **9**.

## Operational tooling functions and methods

| Location | Qualified symbol | Span / decisions | Disposition | Owner |
|---|---|---:|---|---|
| `scripts/build_reasoner_cuda.py:102` | `main` | 117 / 18 | `LOCAL_REVIEW` | local tooling owner |
| `scripts/ci_gate.py:1289` | `host_capabilities` | 118 / 8 | `EXTRACT_FAMILY` | D16 |
| `scripts/ci_gate.py:1747` | `evaluate_unitree_assets` | 173 / 29 | `EXTRACT_FAMILY` | D16 |
| `scripts/ci_gate.py:1923` | `evaluate_hard_safety` | 128 / 19 | `EXTRACT_FAMILY` | D16 |
| `scripts/ci_gate.py:2532` | `evaluate_pose_drift_arms` | 102 / 23 | `EXTRACT_FAMILY` | D16 |
| `scripts/ci_gate.py:2771` | `run_commit_tier` | 100 / 1 | `EXTRACT_FAMILY` | D16 |
| `scripts/fetch_reasoner_cuda_oci.py:84` | `_load_profile` | 47 / 25 | `LOCAL_REVIEW` | local tooling owner |
| `scripts/generate_skills.py:51` | `main` | 346 / 5 | `LOCAL_REVIEW` | local tooling owner |
| `scripts/parcel_capture/budget.py:325` | `static_loads` | 250 / 1 | `EXTRACT_FAMILY` | D08 |
| `scripts/parcel_capture/budget.py:1629` | `render_document` | 391 / 10 | `EXTRACT_FAMILY` | D08 |
| `scripts/parcel_capture/clockmap.py:1430` | `_fit_segment` | 131 / 35 | `EXTRACT_FAMILY` | D08 |
| `scripts/parcel_capture/clockmap.py:2654` | `main` | 130 / 28 | `EXTRACT_FAMILY` | D08 |
| `scripts/parcel_capture/ingest/base.py:401` | `_build_read_only_handle` | 122 / 11 | `EXTRACT_FAMILY` | D08 |
| `scripts/parcel_capture/ingest/dds.py:292` | `decode_low_state` | 123 / 23 | `EXTRACT_FAMILY` | D08 |
| `scripts/parcel_capture/orin_rehearsal.py:800` | `run_p0_identity` | 119 / 26 | `EXTRACT_FAMILY` | D08 |
| `scripts/parcel_capture/orin_rehearsal.py:967` | `run_p1_environment` | 242 / 31 | `EXTRACT_FAMILY` | D08 |
| `scripts/parcel_capture/orin_rehearsal.py:1540` | `run_p3_network` | 156 / 21 | `EXTRACT_FAMILY` | D08 |
| `scripts/parcel_capture/orin_rehearsal.py:1809` | `run_p4_sensors` | 202 / 25 | `EXTRACT_FAMILY` | D08 |
| `scripts/parcel_capture/orin_rehearsal.py:2221` | `run_p5_recorder` | 349 / 42 | `EXTRACT_FAMILY` | D08 |
| `scripts/parcel_capture/orin_rehearsal.py:2820` | `render_runbook` | 212 / 2 | `EXTRACT_FAMILY` | D08 |
| `scripts/parcel_capture/preflight.py:1327` | `_assess_point_cloud` | 143 / 28 | `EXTRACT_FAMILY` | D08 |
| `scripts/parcel_capture/preflight.py:1472` | `_assess_power` | 101 / 22 | `EXTRACT_FAMILY` | D08 |
| `scripts/parcel_capture/preflight.py:1575` | `_assess_foot_force` | 98 / 22 | `EXTRACT_FAMILY` | D08 |
| `scripts/parcel_capture/preflight.py:2100` | `probe_channel` | 132 / 13 | `EXTRACT_FAMILY` | D08 |
| `scripts/parcel_capture/preflight.py:2739` | `probe_jetpack` | 104 / 5 | `EXTRACT_FAMILY` | D08 |
| `scripts/parcel_capture/preflight.py:2918` | `probe_network` | 146 / 18 | `EXTRACT_FAMILY` | D08 |
| `scripts/parcel_capture/preflight.py:3341` | `probe_builtin_lidar` | 103 / 15 | `EXTRACT_FAMILY` | D08 |
| `scripts/parcel_capture/preflight.py:3892` | `_plausibility_findings` | 126 / 24 | `EXTRACT_FAMILY` | D08 |
| `scripts/parcel_capture/preflight.py:4048` | `imu_cross_check` | 110 / 14 | `EXTRACT_FAMILY` | D08 |
| `scripts/parcel_capture/record.py:613` | `read_mcap` | 172 / 26 | `EXTRACT_FAMILY` | D08 |
| `scripts/parcel_capture/rehearse.py:651` | `record_take` | 126 / 12 | `EXTRACT_FAMILY` | D08 |
| `scripts/parcel_capture/rehearse.py:917` | `classify` | 153 / 26 | `EXTRACT_FAMILY` | D08 |
| `scripts/parcel_capture/rosbag2.py:1234` | `read_rosbag2_mcap` | 150 / 27 | `EXTRACT_FAMILY` | D08 |
| `scripts/parcel_capture/rosbag2.py:2133` | `write_fixture_bag` | 110 / 14 | `EXTRACT_FAMILY` | D08 |
| `scripts/parcel_capture/sidecar.py:665` | `build_sidecar` | 117 / 10 | `EXTRACT_FAMILY` | D08 |
| `scripts/parcel_capture/sidecar.py:1616` | `validate_static_transform_snapshot` | 82 / 20 | `EXTRACT_FAMILY` | D08 |
| `scripts/parcel_capture/sidecar.py:1818` | `assess_go_record` | 240 / 40 | `EXTRACT_FAMILY` | D08 |
| `scripts/parcel_capture/sidecar.py:2192` | `build_rosbag2_sidecar` | 295 / 46 | `EXTRACT_FAMILY` | D08 |
| `scripts/parcel_capture/stage0_addendum.py:331` | `render_combined_index` | 136 / 2 | `EXTRACT_FAMILY` | D08 |
| `scripts/parcel_capture/stage0_addendum.py:1030` | `_t7_section` | 161 / 9 | `EXTRACT_FAMILY` | D08 |
| `scripts/parcel_capture/stage0_addendum.py:1193` | `_t8_section` | 125 / 2 | `EXTRACT_FAMILY` | D08 |
| `scripts/parcel_capture/stage0_addendum.py:1320` | `_t9_section` | 201 / 0 | `EXTRACT_FAMILY` | D08 |
| `scripts/parcel_capture/stage0_addendum.py:1523` | `_t10_section` | 243 / 1 | `EXTRACT_FAMILY` | D08 |
| `scripts/parcel_capture/stage0_addendum.py:1825` | `render_addendum` | 184 / 7 | `EXTRACT_FAMILY` | D08 |
| `scripts/parcel_capture/syncevents.py:1446` | `match_trains` | 179 / 23 | `EXTRACT_FAMILY` | D08 |
| `scripts/parcel_capture/syncevents.py:1715` | `estimate_pair_offset` | 107 / 19 | `EXTRACT_FAMILY` | D08 |
| `scripts/parcel_capture/syncevents.py:2125` | `detect_ritual_step` | 109 / 28 | `EXTRACT_FAMILY` | D08 |
| `scripts/parcel_capture/syncevents.py:2631` | `build_sync_fit` | 141 / 20 | `EXTRACT_FAMILY` | D08 |
| `scripts/parcel_capture/syncevents.py:3103` | `synthesize_lowstate_ritual` | 119 / 4 | `EXTRACT_FAMILY` | D08 |
| `tools/bargein_through_air.py:225` | `verify_scorecard` | 195 / 51 | `LOCAL_REVIEW` | local tooling owner |
| `tools/bargein_through_air.py:783` | `score_interrupt_latency` | 142 / 27 | `LOCAL_REVIEW` | local tooling owner |
| `tools/bargein_through_air.py:1037` | `build_scorecard` | 222 / 57 | `LOCAL_REVIEW` | local tooling owner |
| `tools/bargein_through_air.py:1285` | `main` | 99 / 27 | `LOCAL_REVIEW` | local tooling owner |
| `tools/codebase_index.py:190` | `build` | 220 / 80 | `EXTRACT_FAMILY` | D25 |
| `tools/enroll_owner_appearance.py:223` | `enroll` | 92 / 21 | `LOCAL_REVIEW` | local tooling owner |
| `tools/measure_erle.py:649` | `build_report` | 177 / 24 | `LOCAL_REVIEW` | local tooling owner |
| `tools/measure_erle.py:877` | `main` | 86 / 20 | `LOCAL_REVIEW` | local tooling owner |
| `tools/replay_turn_detection.py:754` | `replay` | 128 / 16 | `LOCAL_REVIEW` | local tooling owner |
| `tools/run_voice_corpus.py:778` | `score` | 145 / 39 | `LOCAL_REVIEW` | local tooling owner |

Operational function/method rows: **59**.

## Interpretation rule

A row is not complete merely because its file becomes smaller. An accepted
extraction must establish a single state/clock/lifecycle/authority owner, keep
the compatibility facade during migration, pass both equivalence and refutation
lanes, reduce dependency/state complexity, and delete or disable the old live
path. `PRESERVE_FIRST` rows remain cohesive unless Fable approves a smaller
pure contract supported by stronger tests.
