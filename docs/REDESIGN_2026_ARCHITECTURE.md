# Parcel target architecture (2026 redesign)

**Companion doc:** [REDESIGN_2026_ASSESSMENT.md](REDESIGN_2026_ASSESSMENT.md)
(the why). This doc is the what: the seven-layer portable architecture, what
was implemented, and the contracts that must survive any vendor swap.

Operational caveat: implementation is not the same as deployment readiness.
The current desktop/service/device state and configuration bindings are tracked in
[CURRENT_STATUS.md](CURRENT_STATUS.md); the benefits and costs of the decisions
below are centralized in [DESIGN_DECISIONS.md](DESIGN_DECISIONS.md).

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

This is **control-contract portability**, not installation portability. The
current wheel omits repository-level `prompts/`, skill YAML, and navigation YAML,
and its packaged fallback config is divergent. Run the architecture from a
source checkout/editable install until those assets and paths are packaged and a
clean external-wheel test exists.

## Layer map

```
L6  Deliberative brain     brain/            PlanIR → validator → executive → adapter
L5  Voice / duplex         voice_pipeline.py, voice_audio.py, providers.py; D0 shadow frames
L4  Skills / expression    configs/skills/, gait.py, expression.py, prosody.py; attention pure-only
L3  Motion & skills        skills/, motion.py (vendor-neutral backends)
L2  Navigation & collision navigation/       grid planner + unconditional reactive gate
L1  Perception             mujoco_lidar.py raycaster (sim) → hardware sensors (next)
L0  Vendor HAL             control/          registry, ControlManager, adapters
```

Rates: control dispatch and nominal D0 frame production 10 Hz (runtime loop;
D0 wall-clock cadence is not deadline-instrumented) / 50–100 Hz
(`ControlManager` tick when threaded); expression overlay 50 Hz; scan per
observation at 10 Hz; brain executive at control rate with zero LLM calls; LLM
planning asynchronous per turn.

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
- The legacy-named **`VoiceEndOfSpeechToFirstAudio`** metric is recorded per
  turn, but its current clocks are final-text submission → first speaker-sink
  handoff. It excludes microphone endpointing and blocking STT, and the endpoint
  is not acoustic presentation. True EOS/ASR/device-start/presentation markers
  remain required before applying the P50 <500 ms / P95 <800 ms product target.

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
  time-to-reacquire, with the repo's ledger discipline. See the
  [result ledger](../evals/companion_nav/results/README.md) for metric
  definitions and `does_not_prove` boundaries.

### Viewer
- `/viewer` — self-contained 2.5D city viewer (static geometry from
  `/api/scene`, 10 Hz dynamics from `/api/state`: robot, owner, pedestrians,
  LiDAR fan, navigation goal/status, collision/E-stop banners).

### Expressive voice slice — implemented after Phase 4

- **Semantic endpointing seam** (`endpointing.py`): optional Silero VAD framing
  and Smart Turn completion decisions behind the existing energy-VAD contract,
  with an explicit energy fallback and `TurnCommitLatency` metric.
- **ProsodyTap** (`prosody.py`): pure-DSP pre-playback envelope, pitch, accent,
  and arousal analysis. It emits timing metadata, never commands.
- **50 Hz expression channel** (`expression.py`): additive/clamped idle,
  reaction, and beat layers; speech epochs atomically suppress stale nod timing
  after barge-in. The simulator backend accepts body-height/pitch joint-offset
  overlays without making them locomotion authority. Go2 has no neck, so the
  scheduled head nod itself is telemetry-only today.
- **Conversation emotes**: curated bounded pose/trajectory skills are admitted
  through the validated `Gesture` contract. Inline `[emote:...]` speech tags
  are stripped before synthesis and dispatched only when the activity
  coordinator admits them; speech continues if a gesture is rejected.

These pieces are wired and test-covered, but physical audio and expressive
motion are not operationally validated. The canonical YAML now places the live
endpointing/device keys and Fish reference ID under `speech:`. The divergent
packaged fallback retains unsupported `fish_streaming`/`barge_in` keys, as
recorded in [CURRENT_STATUS.md](CURRENT_STATUS.md).

## 2026-08-04 adversarial review round

A 23-agent find→verify review of the Phase 0–4 changes confirmed 18 real
defects (2 critical, 8 major, 8 minor), all fixed same-day with regression
tests (suite 1293→1304 passing). The load-bearing ones, recorded so the
patterns are not reintroduced:

- **Spoken "stop" now latches the E-stop synchronously** — the mic loop is
  wired to `runtime.submit_voice_text` (the guarded fast path), never the raw
  voice session.
- **The production brain registry is built with the runtime's pose catalog** —
  an empty `pose_names` silently rejected every ReturnToSafePose plan while
  all tests passed (they built their own registries). Dispatch also stops
  motion *before* validating the pose name.
- **`ControlManager` distinguishes stop boundaries from target replacement**
  (`_stop_epoch` vs `_intent_epoch`): a command update crossing an in-flight
  vendor RPC no longer forces a compensating physical stop + confirmation
  lockout (hardware-only stop-start judder, invisible to the sim path).
- **Invariant lifetime is owner-task-keyed and cleared under the lock** —
  fixes a TOCTOU where a stale executive snapshot could permanently strip a
  new plan's `stop_on_stale_perception` invariant.
- **SpeakerSink is barge-in-race-free**: `enqueue` never re-arms an
  interrupted sink (the session re-arms per turn via `audio_turn_start`);
  `playback_active` stays true until audio actually stops (echo guard holds
  through the tail); the default player aborts in ~50 ms blocks.
- **Mic-thread death is loud**: capture preflight raises into the
  degrade-to-text branch; mid-session death fires `on_failure` and
  `microphone_active` reports thread liveness, not object existence.
- **RobotProfile actually reaches the simulator** (gait IK, scan height,
  footprint) — previously validated, reported, and ignored.
- Plus: mission-start `navigate()` passes the scan; `ControlNotReadyError` is
  a control condition, not a fake simulator disconnect; `_http_health` treats
  5xx as dead; Piper sample rate auto-detected from the voice JSON; the VAD
  noise floor can re-baseline under sustained noise; eval static collisions
  are edge-counted events; the battery-gate test actually exercises the gate.

## Dynamic prompting (2026-08-04)

`dynamic_prompting.py` adds sectioned, budgeted, two-plane prompt composition
(stable-cached prefix / volatile turn tail), an owner-profile personalization
source, and a fail-closed read-only information-tool registry (weather
example) the conversation LLM can invoke per its rendered when-to-use policy.
Inspect live at `GET /api/prompt`; add facts via `POST /api/prompt/fact`.
Design rationale and growth path: [RESEARCH_2026_ROADMAPS.md](RESEARCH_2026_ROADMAPS.md) §5.

## Subsequent companion and duplex slices (2026-08-04)

These are present in the source checkout after the Phase 0–4 redesign. Their
interfaces and regression evidence are real; the limits below are part of the
architecture, not deferred footnotes.

### Predictive navigation and owner recovery

- `OwnerMotionPredictor` feeds bounded lead/confidence into owner following.
  The direct-follow keepout clamp leaves only 0.05 m of useful lead and the
  isolated 90° turn scenario did not improve, so this is a wired mechanism—not
  a proven anticipation gain.
- `grid_v1` rebuilds projected dynamic-agent costs and the runtime applies an
  all-track TTC gate. Tests prove corridor avoidance and gate engagement, but
  not socially correct passing-side choice or a reduction distinct from the
  existing reactive-person gate.
- `SCurveVelocityShaper` runs after the safety gate and before
  `ControlManager`; stop paths bypass/reset it. A companion-eval dispatch replica
  reduced mean commanded jerk 0.9592→0.5530 m/s³ across 11 episodes, but stops
  before the manager/HAL and never exercises the calm profile.
- `SearchOwner` is a system-authored, non-model-callable skill: last observed
  point → yaw sweep → planner-backed frontier search. Phase order and budget are
  tested, but the earlier corner-loss run exhausted the budget and gave up; the
  planner-backed update has not been rerun there and no successful reacquisition
  has been measured.

### Interruption and attention foundations

Behavior channels distinguish destructive stop from pause plus bounded
`ResumeIntent`; semantic task suspension no longer redispatches while suspended.
Automatic semantic resume is still incomplete: NavigateTo redispatch does not
consume the stored intent/call `resume_navigation`, fresh-observation is only
metadata, and search→follow uses a legacy tuple. `attention/` provides a pure
`StimulusBus` and `ReactionArbiter`, but no runtime producer or 10 Hz tick uses
them yet; do not confuse those modules with the separately wired expression
reaction hooks.

### D0 dual-stream overlay (shadow-first)

`duplex/` freezes an epoch-scoped nominal-10 Hz TEXT+ACT frame. The system
composes TEXT from reply text entering the delivery path and ACT from post-gate
twist plus admitted
gaze/skill/emote/filler events; idle/silence fill every other frame. The consumer
is shadow-only and frames never drive the actuator path. Frame tests prove
index/epoch rules, not wall-clock cadence, because the caller supplies ticks.
Predictive/watchdog
fillers and aligned local JSONL outcomes are wired, but filler timing has only
fake-TTS/scripted-clock evidence and long-session log size/privacy are
unmeasured. D1—a trained dual-head decoder and non-shadow consumer—does not exist.
The complete contract and promotion gates are in
[DUPLEX_DUAL_STREAM_DESIGN.md](DUPLEX_DUAL_STREAM_DESIGN.md).

## Deferred (with the chosen path, so nobody re-researches)

| Item | Trigger | Chosen path |
|---|---|---|
| Hardware bring-up | physical Go2 access | velocity+E-stop only through `ControlManager`; never the joint path first |
| Real sensors | after hardware bring-up | Mid-360/L2 + Orbbec Gemini 335; same scan contract |
| Terrain (stairs/curbs) | after flat-ground validation | elevation_mapping_cupy |
| AEC / far-field mic | before real duplex demos | XVF3800-class hardware AEC + WebRTC residual |
| Activate Silero VAD / Smart Turn | when ONNX Runtime + weights ship and an audio endpoint is available | implemented seam in `endpointing.py`; keep loud energy fallback |
| D1 dual-head TEXT+ACT decoder | after consented D0 corpus + frozen side-by-side eval | train behind `DuplexFrame`; shadow A/B first; never bypass PlanIR/admissibility/safety |
| RL locomotion | priority 4 funded | unitree_rl_gym→lab→mjlab lineage; ONNX; damping kill switch |
| ros2_control spike | hardware phase | evaluate against the registry using `quadruped_ros2_control` as reference |
| VLN ("next to the bed") | after eval baseline | NaVILA-shaped: VLM emits mid-level commands into the existing PlanIR executive |
