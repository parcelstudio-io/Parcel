# Parcel redesign 2026: assessment, rationale, and decisions

**Date:** 2026-08-03 · **Status:** implemented (see companion doc
[REDESIGN_2026_ARCHITECTURE.md](REDESIGN_2026_ARCHITECTURE.md)) · **Method:**
8 independent subsystem audits + 2 independent online research passes (12
research agents across two model families) + 3 adversarial architecture
proposals, adjudicated, with every load-bearing claim verified against source.

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
~24 GiB VRAM — not an onboard reality. Piper (CPU, ~40 ms-class first audio)
is the default; Fish is an opt-in docked mode. Both research passes reached
this independently.

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

1. ✓✓ **No shipping quadruped gives a learned model final collision
   authority** (Unitree, Spot, Deep Robotics, ANYbotics). Deterministic
   geometry is the last line of defense; learned components propose, never
   dispose. Parcel's unconditional `collision.py`/`reactive_safety.py` gate
   under every dispatch source is the correct architecture — keep it forever.
2. ✓✓ **The five-primitive vendor contract** (SE2 velocity, stand/sit,
   gait/mode, state feedback, separate e-stop) recurs across every vendor SDK.
   `ControlManager` already implements exactly this boundary.
3. ✓✓ **Voice barge-in requires one tightly-coupled real-time process**, not
   glued microservices — `DuplexVoiceSession`'s design was right; it needed
   ears and a mouth, not a rearchitecture.
4. ✓✓ **Latency bar:** P50 end-of-speech→first-audio under ~400–500 ms, P95
   under 800 ms. Cascaded local stacks (VAD → streaming STT → LLM → sentence-
   streamed TTS) reach 500–800 ms on-device in 2026; S2S models (Moshi/
   PersonaPlex-class, ~200 ms) still lack reliable tool-calling, so a cascade
   remains correct where commands must execute.
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
  production; experiment YAMLs under `configs/navigation/experiments/` remain
  for offline planner work.

## 7. Honest limitations that remain

- **Nothing here has moved a real motor.** Every number is simulation. The
  velocity+E-stop hardware bring-up on a physical Go2 is the first
  hardware-phase task and gates any real-world claim.
- **No acoustic echo cancellation** — the echo-guard multiplier suppresses
  self-barge-in at the cost of requiring the owner to speak up over the robot.
- **The simulator is kinematic** — locomotion dynamics, slip, and contact are
  not modeled; RL/animation execution on hardware remains future work.
- **Piper/whisper.cpp must actually be installed/launched** for audio mode;
  the stack degrades loudly to text mode otherwise.
- Scenario pedestrians in the integration eval are visible to social-distance
  metrics and controllers but not to the raycast scan (v1 limitation, noted in
  the eval's `does_not_prove`).
