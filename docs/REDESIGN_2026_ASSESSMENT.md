# Parcel redesign 2026: assessment, rationale, and decisions

**Date:** 2026-08-03 · **Status:** dated rationale; implementation/status claims
are superseded by the current
[engineering handbook](CONVERSATIONAL_AUTONOMY_HIGH_LEVEL_DESIGN.md) · **Method:**
8 independent subsystem audits + 2 independent online research passes (12
research agents across two model families) + 3 adversarial architecture
proposals, adjudicated, with every load-bearing claim verified against source.

This is the redesign record, not a live readiness claim. Subsequent features,
operational blockers, configuration bindings, and inert reserved keys are tracked in
[engineering handbook](CONVERSATIONAL_AUTONOMY_HIGH_LEVEL_DESIGN.md); decision tradeoffs are in
[DESIGN_DECISIONS.md](DESIGN_DECISIONS.md).

## 1. The question

> How good is our current setup, and should we redesign the whole thing?

## 2. The verdict

**Refactor in place — not a rewrite.** The audit's unanimous, verified
diagnosis: Parcel's defining trait was not bad engineering but *engineering
never connected to reality*. Every subsystem had the same shape — a real,
tested, often well-designed component sitting one wire short of doing anything
in production:

| Subsystem | What existed | What was missing |
|---|---|---|
| Navigation | 1,691-line occupancy-grid A* planner, 35/35 tests, 2%→44% BARN improvement | **Unreachable from the product.** Default was `stub_v0`; the runtime never produced the scan contract, so even `grid_v1` silently fell back |
| Voice | Well-designed duplex coordinator with cancellable streaming output | **No audio ever produced.** Constructed with no synthesizer; STT/TTS adapters built but never instantiated; "barge-in" was a browser keystroke |
| Control HAL | Vendor-clean 1,160-line `ControlManager` (zero Unitree symbols) | `import parcel_robot.control` still dragged in Unitree symbols via the factory; no registry; only ever called from a standalone CLI |
| Brain | Fail-closed PlanIR validator + deterministic executive | `effective_invariants`, battery, and `ReturnToSafePose` computed values **nothing read** |
| RL/animation | 26-skill YAML catalog with kinematic preview | RL env fed constant rewards (`actual_vx=0.0` hardcoded); `terminated` always `False` |
| Perception | — | **None.** "LiDAR" was analytic closest-point math on ground-truth geoms: no occlusion, no noise, no raycast |

Pre-redesign scorecard (verified): brain 7/10, control HAL 6/10, portability
5/10, eval discipline 5/10, navigation-in-production 3/10, voice 2/10, RL
2/10.

## 3. Why not a rewrite

All three adversarial proposals — including the rebuild-biased one — declined
to rebuild the four core assets, because a rewrite would spend months arriving
at roughly the same designs:

1. `ControlManager`'s watchdog/TTL/feedback-confirmed-stop/E-stop machine.
2. `RollingGridPlanner`'s log-odds grid + inflation + corner-safe A*.
3. The PlanIR → validator → executive trust boundary (the LLM owns only the
   skill list, arguments, and goal; the system compiles everything else).
4. The eval-honesty culture (hash-pinned immutable results, explicit
   `does_not_prove` blocks).

## 4. Explicit adjudications (and their evidence)

**Rejected: migrate navigation to Nav2/ROS 2 now.** The repo has zero ROS 2
dependency in its production path (`rclpy` appears once, try/except-guarded,
outside the runtime). The in-house planner already matches the pattern 2026
research finds in every shipping quadruped — classical geometry owns collision
authority; learned components live above/below it. Wiring real sensing into
the existing planner was days; a middleware migration was months. **Nav2
remains the documented contingency** if post-wiring eval numbers disappoint.
A scoped `ros2_control` spike stays on the roadmap for the hardware phase —
`quadruped_ros2_control` proves same-controller multi-vendor portability and
is the strongest known argument for that substrate.

**Rejected: delete the pose/trajectory YAML system.** It is the one piece of
infrastructure serving the explicit (low-priority) requirement to run custom
animation files. Instead, a `RobotProfile` morphology layer removed the Go2
literals from the kinematics.

**Rejected: Fish-Speech as the TTS default.** Its own launcher gates at
~24 GiB VRAM — not an onboard reality. Piper is the selected lightweight CPU
default; Fish is an opt-in docked mode. The historical ~40 ms-class Piper
estimate came from the research comparison, not a Parcel measurement: Piper is
still absent on this desktop.

**Replaced: BARN as the navigation eval.** BARN measures collision-free
*speed through static clutter* on a wheeled-Jackal abstraction that discards
lateral motion — nearly orthogonal to companion quality. After the honest
2%→44% gain, versions v5–v10 produced **zero** further success improvement
while the harness grew to ~19k lines of certification machinery around ~2.6k
lines of algorithm. The replacement eval (`evals/companion_nav/`) scores what
the product actually needs — following-success, hard collisions with no
sliding forgiveness, personal-space intrusion, jerk, reacquire-after-occlusion
— per Follow-Bench (arXiv 2509.10796), the social-nav evaluation guidelines
(arXiv 2306.16740), and the sim-to-real predictivity evidence (SRCC, arXiv
1912.06321; Gervet et al. arXiv 2212.00922: modular 90% vs end-to-end 23%
real-world transfer).

## 5. Key research takeaways that shaped the design

Cross-checked across two independent research passes; agreement between both
is marked ✓✓.

1. ✓✓ **No reviewed vendor/reference quadruped stack gave a learned model final
   collision authority** (Unitree, Spot, Deep Robotics, ANYbotics). Deterministic
   geometry is the last line of defense; learned components propose, never
   dispose. Parcel's runtime-wide `reactive_safety.py` gate under every runtime
   velocity source is the correct architecture — keep an independent final
   safety veto forever. `navigation/collision.py` is an additional
   navigation-local defense, not the universal boundary; direct simulator debug
   paths remain outside `RobotRuntime`.
2. ✓✓ **A small vendor contract** (leased SE2 velocity, state feedback, and a
   separate E-stop) recurs across vendor SDKs. `ControlManager` implements that
   locomotion boundary today. Pose/trajectory execution is a separately
   serialized simulator skill path and is rejected by the physical Unitree
   adapter until a commissioned whole-body action contract exists.
3. ✓✓ **Voice barge-in requires one tightly-coupled real-time process**, not
   glued microservices — `DuplexVoiceSession`'s design was right; it needed
   ears and a mouth, not a rearchitecture.
4. ✓✓ **Latency bar:** P50 end-of-speech→first-audio under ~400–500 ms, P95
   under 800 ms. Cascaded local stacks (VAD → streaming STT → LLM → sentence-
   streamed TTS) reach 500–800 ms on-device in 2026; S2S models (Moshi/
   PersonaPlex-class, ~200 ms) still lack reliable tool-calling, so a cascade
   remains correct where commands must execute. These are product/research
   targets, not measurements from Parcel's disconnected desktop audio path.
5. ✓✓ **A speaker next to the mic makes software-only AEC marginal.** The
   2026 answer is hardware DSP AEC (XVF3800-class mic array) with software
   residual suppression. Until then, the echo-guard multiplier is an honest
   stopgap (documented in `voice_audio.py`).
6. ✓ **CMU `autonomy_stack_go2`** (Point-LIO + FAR Planner + terrain analysis
   on the stock Go2 L1 LiDAR) is the proven reference stack for the hardware
   bring-up phase.
7. ✓ **NaVILA's hierarchy** — VLM emits short mid-level commands at ~1 Hz, a
   fast safe controller executes — is the deployable shape of "go next to the
   bed"; Parcel's PlanIR executive is already this shape.
8. ✓ **Sensors for the hardware phase:** Livox Mid-360 (~$750) or Unitree L2
   as primary 360° LiDAR, plus one forward depth camera (Orbbec Gemini 335 /
   RealSense D455); LiDAR-only misses the exact failure modes (thin, low,
   glass, stairs-down) a companion dog is judged on.
9. ✓ **RL path when funded:** Unitree's own lineage (`unitree_rl_gym` →
   `unitree_rl_lab` → `unitree_rl_mjlab`): configure → PPO → ONNX →
   sim2sim → sim2real at ~50 Hz. Do not invent a bespoke pipeline. Community
   reports document a hardware-damage failure mode when Sport Mode releases
   before a joint policy initializes — keep a damping-mode kill switch during
   any future LowCmd bring-up.
10. ✓ **elevation_mapping_cupy** (2.5D terrain/traversability) is the proven
    middle layer for stairs/curbs/rugs — flagged as the next perception
    investment after flat-ground navigation is validated on hardware.

## 6. What was deliberately removed from the production path

These items are severed from the default runtime or marked research-only. Some
trees may still exist under `evals/external/` or as experiment configs until an
operator deletes them — presence in the tree is not a production claim.

- `navigation/experimental_all_ray_shield.py` — deployment-disabled research
  shield (evaluated 0/30); not on the product path.
- BARN v5–v10 certification machinery — research harnesses only; **product**
  navigation eval is `evals/companion_nav/`.
- `rl/env.py` reward/termination stubs — not a training capability; redesign
  prefers the Unitree RL lineage when funded rather than polishing the stub.
- `SportMoveBackend` (vendor-branded no-op) → neutral `VendorVelocityBackend`
  with a deprecated `sport` alias.
- `CsmSpeechProvider` (legacy, no production caller).
- Learned-navigator registry entries that unconditionally raised
  `NotImplementedError`; `build_navigator` accepts only `stub` and `grid`.
  Re-add a type only with a working inference adapter.
- Navigation config graveyard collapsed toward `grid_v1` + `stub` for
  production; research profiles under `configs/navigation/models/` remain for
  offline planner/eval work and are not runtime admission.

## 7. Honest limitations that remain

- **Nothing here has moved a real motor.** Every number is simulation. The
  velocity+E-stop hardware bring-up on a physical Go2 is the first
  hardware-phase task and gates any real-world claim.
- **No acoustic echo cancellation** — the echo-guard multiplier suppresses
  self-barge-in at the cost of requiring the owner to speak up over the robot.
- **The simulator is kinematic** — locomotion dynamics, slip, and contact are
  not modeled; RL/animation execution on hardware remains future work.
- **Piper/whisper.cpp must actually be installed/launched** for audio mode;
  at the 2026-08-04 desktop snapshot Piper is missing, whisper is not running,
  PortAudio is absent, and no endpoint is connected. The stack degrades loudly
  to text mode otherwise.
- Scenario pedestrians in the integration eval are visible to raycast LiDAR,
  owner line-of-sight, and injected person telemetry. They are absent from the
  analytic nearest-obstacle telemetry and static-collision oracle; that split is
  a v1 limitation recorded in the eval contract.

## 8. Evidence added after the redesign record

Later 2026-08-04 slices validate the **refactor-in-place** verdict while also
showing why “wired” must not mean “improved”:

- owner prediction, projected-agent costs, an all-track TTC gate, command
  shaping, and `SearchOwner` are now in the source runtime. Direct-follow
  prediction did not improve the isolated turn case; social passing-side and
  distinct TTC-gate benefit remain unproved; the owner-loss scenario searched
  and gave up before the planner-backed mobile-phase update, which has not been
  rerun there. The one positive measured delta is commanded jerk
  0.9592→0.5530 m/s³ through a partial dispatch replica, not hardware.
- pause-versus-stop channel semantics were repaired and unit-tested, but
  automatic semantic resume is incomplete: stored NavigateTo/follow intents and
  fresh-observation metadata are not consumed end to end. Attention
  stimulus/arbitration modules remain pure foundations outside the loop.
- D0 now emits/logs aligned nominal-10 Hz TEXT+ACT frames and deterministic
  fillers. The ACT consumer is shadow-only and observes behavior chosen elsewhere; no
  trained D1 model or ACT-token actuator authority exists. Filler latency and
  long-session corpus privacy/size have no real-audio/operational evidence.

These additions preserve the original authority boundaries. They are available
from the source checkout/editable install; they do not make the current Python
wheel relocatable because repository prompt/skill/navigation assets are still
outside package data.
