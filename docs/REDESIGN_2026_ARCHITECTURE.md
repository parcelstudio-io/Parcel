# Parcel target architecture (2026 redesign)

**Companion doc:** [REDESIGN_2026_ASSESSMENT.md](REDESIGN_2026_ASSESSMENT.md)
(the why). This doc is the what: the seven-layer portable architecture, what
was implemented, and the contracts that must survive any vendor swap.

## The portability contract (non-negotiable)

Any future robot must be reachable by implementing exactly this surface:

| Contract | Shape | Where |
|---|---|---|
| Locomotion in | SE2 body velocity `VelocityCommand(vx, vy, vyaw)` in `base_link`, leased with a TTL | `control/base.py` `LocomotionController` |
| State out | `RobotMotionState` (velocity, RPY, monotonic sequence, `FaultReason`) | `control/base.py` `RobotStateSource` |
| E-stop | separate latched channel; feedback-confirmed stop | `ControlManager` |
| Perception in | planar scan `{ranges, angle_min_rad, angle_increment_rad, range_min_m, range_max_m}`; NaN = ignored ray, range_max = no return | `navigation/grid_planner.py` `LidarScan` |
| Morphology | `RobotProfile` (joint naming, link lengths, stance, footprint) | `robot_profile.py` |
| Vendor registration | one file + `register_controller_factory(name, factory)`; generic code never imports a vendor | `control/factory.py` |

**Proof, not assertion:** `control/mock_vendor.py` + `tests/test_portability_proof.py`
run a second, non-Unitree adapter through the full manager lifecycle
(registry construction → arming → velocity tracking → feedback-confirmed stop
→ latched E-stop → TTL watchdog) with zero edits to generic code.

## Layer map

```
L6  Deliberative brain     brain/            PlanIR → validator → executive → adapter
L5  Voice                  voice_pipeline.py, voice_audio.py, providers.py
L4  RL / animation         configs/skills/, gait.py (RobotProfile-driven); RL deferred
L3  Motion & skills        skills/, motion.py (vendor-neutral backends)
L2  Navigation & collision navigation/       grid planner + unconditional reactive gate
L1  Perception             mujoco_lidar.py raycaster (sim) → hardware sensors (next)
L0  Vendor HAL             control/          registry, ControlManager, adapters
```

Rates: control dispatch 10 Hz (runtime loop) / 50–100 Hz (`ControlManager`
tick when threaded); scan per observation at 10 Hz; brain executive at control
rate with zero LLM calls; LLM planning asynchronous per turn.

## What was implemented (2026-08-03)

### Phase 0 — structural portability + dead-code removal
- **Controller registry** (`control/factory.py`): `create_control_manager(name, config, limits)`;
  Unitree imports now lazy inside its factory. `import parcel_robot.control`
  is vendor-clean (test-verified).
- **`FaultReason`** enum + `vendor_extra` on `RobotMotionState`; the manager
  no longer branches on raw vendor error integers.
- **`ControllerCapabilities` enforced**: a declared no-strafe/no-velocity
  controller now rejects at the dispatch boundary instead of being silently
  commanded.
- **Loud degraded mode**: missing scan contract logs once per transition,
  counts every degraded tick, stamps `scan_missing_fallback` into the command
  note. Silent fallback is gone.
- Vendor-neutral backend naming (`vendor` with deprecated `sport` alias)
  through motion router, safety grammar, agent, and brain router.
- Deletions per the assessment §6 (file removal pending an operator command;
  all code paths already severed).

### Phase 1 — real perception → the good planner actually runs
- **`raycast_planar_scan`** (`mujoco_lidar.py`): `mj_multiRay` occlusion-true
  360-ray scan; robot self-returns filtered by kinematic-tree root and marked
  NaN (never free space); seeded Gaussian noise + dropout. 9 dedicated tests
  including occlusion correctness (a box behind a wall is invisible) and
  pedestrian visibility.
- Scan flows end-to-end: `sim.py` snapshot → IPC → `SimObservation` →
  runtime extras + `Dog.navigate(lidar=...)` → `GridNavigator`; identically in
  `headless_city.py`.
- **`active_model: grid_v1`** is the production default.
- **Two real planner bugs fixed** (found by the wiring, proving its value):
  per-mission goal tolerance now overrides the BARN-tuned 0.95 m planner
  tolerance (semantic goals use 0.12 m arrival radii), and the degenerate
  start-cell-inside-goal-region case is classified `at_goal` instead of
  `no_path` (previously an infinite recovery-scan deadlock one meter from the
  target).
- Embodied gate re-frozen under grid_v1: 4/4 supported success, 0 collisions,
  identical minimum clearance (0.883 m), 1,303 vs 1,137 steps (the grid maps
  before it commits).

### Phase 2 — the ears and the mouth
- **`build_speech_stack`** resolves the `speech:` config (previously dead):
  whisper.cpp STT + Piper TTS by default, Fish S2 opt-in; `auto` degrades
  loudly to text mode, `audio` fails closed at startup.
- **`SentenceChunkedSynthesizer`**: any blocking TTS becomes a cancellable
  stream; first audio after the first sentence; barge-in takes effect at the
  next sentence boundary at the latest.
- **`voice_audio.py`**: `EnergyVad` (adaptive noise floor, hangover,
  fully unit-tested), `MicrophoneVoiceLoop` (VAD-segmented capture → STT →
  `submit_text`; acoustic barge-in during playback behind an echo-guard
  multiplier — the documented no-AEC stopgap), `SpeakerSink` (ordered chunks,
  immediate interruption).
- **`VoiceEndOfSpeechToFirstAudio`** metric recorded per turn; targets P50
  <500 ms / P95 <800 ms once real services run.

### Phase 3 — the brain's dead surface made live
- **Battery telemetry** (simulated percent + thresholds in `robot.yaml`) flows
  into every observation snapshot; `battery_critical` procedures are reachable
  and `set_battery_percent()` exists for tests/panel drain.
- **`ReturnToSafePose`** implemented end-to-end: adapter dispatch → runtime
  stop + pose; completion verified against controller feedback (posture
  applied AND stop confirmed), never asserted.
- **Invariants enforce**: `stop_on_stale_perception` now stops all semantic
  dispatches when perception goes stale mid-plan (control-loop check);
  active invariants are runtime state exposed in the snapshot, cleared when no
  task remains active.
- **`RobotProfile`** owns morphology; `gait.py` IK and joint naming read the
  profile (different link lengths provably change kinematics; custom joint
  naming schemes work). The `robot:` config key is live.

### Phase 4 — portability proven
- `control/mock_vendor.py` second-vendor adapter + 6-test lifecycle proof.

### Evaluation (replacing BARN as the product gate)
- `evals/companion_nav/` — Follow-Bench-style scenario suite (following,
  occlusion/reacquire, sudden stop, pedestrian cut-in, doorway, POI
  navigation) scored on collision count (no sliding forgiveness),
  following-success band, personal-space intrusion time, jerk, and
  time-to-reacquire, with the repo's ledger discipline. See its README for
  metric definitions and `does_not_prove`.

### Viewer
- `/viewer` — self-contained 2.5D city viewer (static geometry from
  `/api/scene`, 10 Hz dynamics from `/api/state`: robot, owner, pedestrians,
  LiDAR fan, navigation goal/status, collision/E-stop banners).

## Deferred (with the chosen path, so nobody re-researches)

| Item | Trigger | Chosen path |
|---|---|---|
| Hardware bring-up | physical Go2 access | velocity+E-stop only through `ControlManager`; never the joint path first |
| Real sensors | after hardware bring-up | Mid-360/L2 + Orbbec Gemini 335; same scan contract |
| Terrain (stairs/curbs) | after flat-ground validation | elevation_mapping_cupy |
| AEC / far-field mic | before real duplex demos | XVF3800-class hardware AEC + WebRTC residual |
| Silero VAD / Smart Turn | when onnxruntime ships onboard | drop-in behind the `EnergyVad` interface |
| RL locomotion | priority 4 funded | unitree_rl_gym→lab→mjlab lineage; ONNX; damping kill switch |
| ros2_control spike | hardware phase | evaluate against the registry using `quadruped_ros2_control` as reference |
| VLN ("next to the bed") | after eval baseline | NaVILA-shaped: VLM emits mid-level commands into the existing PlanIR executive |
