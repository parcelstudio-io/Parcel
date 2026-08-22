# Parcel 2026 research roadmaps: duplex voice, expressive motion, navigation, benchmarks

**Date:** 2026-08-04 · **Method:** three independent multi-agent online research
passes (14 agents total: 4-agent duplex-voice workflow + 4-agent
expressive/nav/benchmark workflow + 1 context-engineering agent, each with a
max-effort synthesis), adjudicated against each other and against the codebase.
**Companions:** [REDESIGN_2026_ASSESSMENT.md](REDESIGN_2026_ASSESSMENT.md),
[REDESIGN_2026_ARCHITECTURE.md](REDESIGN_2026_ARCHITECTURE.md).

> This is a research record and roadmap, not the operational source of truth.
> Since the original synthesis, Parcel has wired the ProsodyTap, 50 Hz
> expression/BeatLayer, epoch cancellation, bounded Gesture emotes, and an
> optional semantic-endpointing seam. It also has a D0 system-composed
> nominal-10 Hz TEXT+ACT frame/logging overlay and deterministic filler policy. D0 is
> shadow-only—not a trained behavior model or actuator source. Hardware AEC,
> streaming acoustic STT, speculative generation, an overlap classifier,
> expressive neural TTS, D1, and physical timing calibration remain future work.
> See the [engineering handbook](CONVERSATIONAL_AUTONOMY_HIGH_LEVEL_DESIGN.md)
> for current implementation and quality; this roadmap preserves dated research direction.

> **2026-08-22 artifact/device delta:** the XVF3800 now enumerates over USB and
> Piper's binary, voice and metadata are present. Native PortAudio/product
> capture-playback, AEC/DoA and through-air evidence remain uncommissioned. The
> “absent,” “not attached,” and latency-baseline statements below describe the
> original research audit; they are retained so its reasoning is reproducible.

---

## 1. Full-duplex voice: the verdict

**Hybrid engineered-duplex — not native speech-to-speech, not the status-quo
cascade.** The text LLM stays the sole PlanIR dispatch authority forever; a set
of duplex reflexes around it reproduces the "mixed-tape" interleaved feel piece
by piece. Three independently fatal grounds against native S2S today:

1. **Dispatch reliability.** Full-Duplex-Bench v3 puts the best duplex system
   anywhere (hosted gpt-realtime) at ~60% multi-step tool Pass@1 under real
   disfluent speech; open duplex models (Moshi, PersonaPlex) have *no*
   function-calling mechanism at all. A wrong dispatch physically moves a
   quadruped — 60% is disqualifying against a typed-PlanIR cascade that works.
2. **Compute.** Moshi/PersonaPlex want 24 GB bf16 / A100-class; the Go2 dock is
   an Orin NX 16 GB shared with STT+LLM+TTS.
3. **Quality.** Edge-fit native-audio models pay a ~30-point reasoning tax
   (~69% Big Bench Audio vs 97–99% for text brains). "Deep semantic
   understanding" currently comes only from a text brain.

The industry converged on the same split (Moshi's inner monologue, Hume EVI 3,
Nova Sonic half-cascade, Kyutai Unmute): expressive/duplex audio shell + text
brain owning cognition and tools.

### Where duplexness should live — six independently shippable target mechanisms

This table records the target design. It is not an implementation matrix; the
current state is summarized in the build-order table and the D0 overlay below.

| Mechanism | Target design |
|---|---|
| Listen while speaking | Hardware AEC (XVF3800) + always-on streaming STT during playback |
| Real barge-in | Provisional epoch: VAD hit during playback ducks TTS immediately; supersession commits only on >400 ms speech or a content word in partials ("yeah/mm-hmm" never kills a reply) |
| Overlap tolerance | Backchannel classification — the dog talks through murmurs |
| Overlap generation | Semantic-free utterances (SFU: stylized boofs/yips/whines) + gesture backchannels while the USER speaks — a dog persona dodges the uncanny valley and residual-echo self-transcription |
| Perceived instantaneity | Speculative LLM generation on stable partials (dispatch held to turn-commit) + zero-latency SFU acknowledgment sounds (~150–250 ms) |
| Atomic cancellation | Speech epochs spanning audio AND scheduled motion (epoch-tag every gesture event) |

### Component choices (primary / fallback)

“Primary” below means the selected target, not necessarily installed or active.
The current desktop still runs the energy endpointing fallback and has no usable
audio endpoints or Piper installation.

The Orin NX 16 GB “Go2 dock” used in the sizing argument is an assumed future
onboard target, not owned or verified hardware. The only verified accelerator in
this checkout is the desktop RTX 5000 Ada.

| Role | Primary | Fallback |
|---|---|---|
| Acoustic front-end / AEC | Purchased Seeed ReSpeaker XVF3800 USB 4-mic array + CQRobot 4 Ω 3 W JST-PH2.0 speaker, intended to use the array's own playback/amp reference path; not attached, enumerated, electrically checked, or acoustically calibrated in Parcel | WebRTC AEC3 (desktop/sim only) |
| VAD | Silero VAD v6 ONNX (2 MB, 32 ms frames, CPU) | Existing EnergyVad kept as zero-cost pre-gate |
| End-of-turn | Pipecat Smart Turn v3 (BSD-2, 8 MB int8 ONNX, 12–60 ms CPU): ~200 ms commit on "complete", 2–3 s hold on "incomplete" — the single biggest latency win, sim-testable | TEN Turn Detection / LiveKit EOU |
| Streaming STT | NVIDIA Parakeet TDT 0.6B v3 via sherpa-onnx (GPU) | Moonshine v2 streaming (CPU); whisper.cpp behind a build flag |
| Brain + dispatch | Existing local Gemma text LLM → typed PlanIR (speculation on partials remains planned; dispatch held to commit) | Smaller 3–4B Q4 llama.cpp candidate, identical PlanIR schema — reflexes never bypass local deterministic policy |
| Expressive TTS | Chatterbox Turbo (MIT, 350M, ~5 s persona cloning, exaggeration knob from affect arousal — set once per utterance; Orin gate: first chunk ≤300 ms or auto-fallback) | CosyVoice 3 (0.5B, Apache-2.0, continuation-aware streaming); Piper always-on degraded mode |
| Motion-sync timing | New **ProsodyTap** at the synthesizer→SpeakerSink seam: per-chunk (pre-playback) 10 ms-hop RMS envelope + pitch-gated accent list → BeatTrack on the playback clock. Engine-agnostic | wav2vec2 CTC forced alignment per chunk (stressed-word gestures) |
| Wake/sleep | Always-on VAD-gated (audio never leaves robot); "go to sleep" → openWakeWord-gated low-power mode | Porcupine |
| Native-duplex research vehicle | PersonaPlex-7B offboard, inner-monologue text relayed into PlanIR as a *proposal* channel — never load-bearing | Moshi + moshi-finetune on Parcel's own logs |

Adopt on-robot native duplex only when ALL hold: open duplex model <~2B with
native tool support (watch Step-Audio 2 lineage, MiniCPM-o 4.x), Thor/AGX-class
compute, and demonstrated adherence-gap closure.

### Speech-synchronized body motion (the "excited leg bounce")

Three signals, cleanly split — **the LLM decides WHAT at sentence granularity,
the audio decides WHEN at 10 ms granularity** (each doing the other's job is a
known failure):

1. **PlanIR side:** existing affect estimate + two additive schema extensions —
   optional `motion_style {valence, arousal, intensity}` and `emote_trigger`
   *category* (not clip name) on Vocalize; inline span tags
   (`[excited]…[/excited]`) mapped to sentence indices by
   SentenceChunkedSynthesizer.
2. **Audio side:** ProsodyTap BeatTrack + ArousalEnvelope, computed before each
   chunk plays — free lookahead that live-reactive systems structurally lack.
3. **Dialogue acts:** sentence boundaries trigger emote clips; user-side
   prosody feeds a listener-backchannel predictor.

**Scheduling:** analyze-then-schedule. Apex time = accent − motion lag + audio
lag (calibrate on hardware; expect 50–150 ms through the Go2 SDK). Bias EARLY —
ITU asymmetry: +45 ms motion-lead undetectable, −125 ms lag detectable. Budget:
apex within ±100 ms of the pitch accent; >±200 ms is worse than no motion. New
metric **ApexToAccentError**, target P50 <30 ms / P95 <100 ms, validated in
MuJoCo before hardware.

**Layering (BDX pattern; MotionMixer with Cozmo-style per-track masking):**
- **IdleLayer** (always on): 0.2–0.3 Hz breathing (±3–5 mm body height), Perlin
  micro-sway, 4–8 s weight shifts, DoA-driven head-orient — the listening half
  of duplex.
- **BeatLayer** (playback only): ArousalEnvelope → 2–4 Hz body-height/pitch
  oscillation (the excited bounce is *stance-compliance* bounce, not per-leg
  stepping); BeatTrack accents → head-nod apexes. Hard clamps: ±2 cm height,
  ±10–12° head pitch, CoM excursion <15% of support-polygon margin.
- **EmoteSequencer**: the 26-skill YAML catalog extended per-clip with
  entry/exit stance declarations (Spot-style transition validation), intensity
  scalar (0.5–1.5× from affect confidence × arousal), per-keyframe variability;
  triggers are categories with weighted random selection.
- New **50 Hz ExpressivePoseChannel** for the mixer output; the 10 Hz
  decision/arbitration tick is unchanged; E-stop and collision authority sit
  above everything, exactly as today.

### Latency budget (end-of-speech → first audio; target P50 <500 ms)

No acoustic end-to-end sample exists on this desktop: PipeWire has no real
source/output route, PortAudio is unavailable, and Piper is absent. The left
column is therefore a dated architecture estimate, not “today's measured
latency”; the right column is an upgrade target.

| Stage | Baseline design estimate (unmeasured here) | Post-upgrade target |
|---|---|---|
| Front-end AEC | n/a (echo-guard) | ~58 ms, overlapped |
| Silence tail → turn commit | 500–800 ms fixed | ~200 ms semantic commit (+12–60 ms Smart Turn) |
| STT finalize | one blocking full-utterance whisper.cpp request; duration unmeasured | 50–100 ms residual (streaming partials caught up) |
| LLM TTFT | serial and workload-dependent; no acoustic E2E sample | ~0–100 ms perceived (speculation hit; dispatch still held) |
| TTS first chunk | Piper absent, so no local number | Piper target, with Chatterbox gated at ≤300 ms on the eventual onboard target |
| Audio out | 30–60 ms | 30–60 ms |
| **Total** | **not measured** | **P50 target ~250–350 ms** (speculation hit, Piper); ~450–500 with Chatterbox |

Target barge-in → audible+visible yield: TTS duck within ~100 ms of post-AEC VAD
hit; full supersession (audio + epoch-tagged motion) on commit.

### Build order and current status (sim first, hardware gated)

| Step | Slice | Status on 2026-08-04 |
| --- | --- | --- |
| 1 | Order XVF3800 + speaker | Purchased: XVF3800 enclosure and CQRobot 4 Ω 3 W JST-PH2.0 speaker; not connected, enumerated, electrically checked, or heard by Parcel |
| 2–3 | Silero v6 + Smart Turn dual-timeout seam | **Implemented/tested**, but inactive: ONNX Runtime/weights are absent and canonical mode remains `energy` |
| 4 | Stage latency, turn-commit, apex error, interrupt metrics | **Partially implemented**; software metrics exist, physical-device timestamps do not |
| 5 | ProsodyTap + head-nod BeatLayer | Timing, epochs, and metrics are **implemented/tested**; Go2 has no neck, so the scheduled nod is not actuated or visible |
| 6 | Epoch-tagged motion + interruption classifier | Epoch cancellation **implemented**; semantic backchannel/interruption classifier remains planned |
| 7 | True streaming STT partials | Planned; browser text partials are not streaming acoustic ASR |
| 8 | Speculative generation with plan gating | Planned |
| 9 | SFU library + backchannel predictor | Planned |
| 10 | Chatterbox behind the synthesizer interface | Planned; Piper/Fish adapters remain current choices |
| 11 | 50 Hz expression + idle + bounded emotes | **Implemented as a conservative additive v1**; full clip mixer/transitions remain planned |
| 12–15 | XVF3800/Jetson integration, target benchmarks, ego-noise hardening, lag calibration | Hardware-gated and not started |
| 16 | PersonaPlex/Moshi proposal-channel experiment | Research only |
| D0 overlay | System-composed aligned TEXT+ACT frames, deterministic fillers, local session log, scripted eval | **Implemented/wired shadow-first**; no retained real-audio result, continuity checks index/epoch rather than wall-clock cadence, ACT observes existing behavior, and the consumer never drives commands. D1 remains future work. |

---

## 2. Expressive conversation-driven behavior (7-step roadmap)

Implementation overlay: step 1 and the stationary, bounded core of step 2 are
now wired. The engine has idle/reaction/beat layers, a 50 Hz backend overlay,
curated `Gesture` admission, sentence-local emote tags, activity gating, and
epoch cancellation. It does **not** yet have the richer stance-transition
schema, blending graph, Laban variation, authored physical clips, or RL style
tracking described in steps 3–7.

1. **(days)** Procedural micro-expression layer + deterministic reaction hooks:
   additive head/body channel over the SE2 stream; VAD-onset head-orient
   <300 ms, question head-tilt, visible "thinking" pose owning the
   end-of-speech→first-TTS gap; idle breathing/weight shifts; ELEGNT amplitude
   gating (full in conversation/idle, head-only while navigating).
2. **(week)** Thin `Emote(clip_id, intensity)` PlanIR skill (stationary-only v1
   precondition, executive-verified completion) + inline emote tags in TTS
   sentences routed through the existing affect/proposal/cooldown arbiter.
   Selection-not-generation — both research passes reject LLM-generated motion
   code (open-loop, bypasses the validator).
3. **(week)** YAML schema upgrade before authoring more clips (Spot
   Choreographer pattern): track ownership, entry/exit blends,
   interruptible flags, stance-transition graph enforced by the validator;
   Laban parameterization (valence→amplitude/smoothness, arousal→tempo) turns
   26 clips into hundreds of distinct expressions with zero ML.
4. **(weeks)** Disney-style three-layer engine (perpetual idle / episodic clips
   with 0.1–0.35 s blends and priority interruption / continuous modulation);
   then relax Emote's stationary-only into validator-compiled downscoping.
5. **(week)** Author the v1 emote set (8–12): mirror Go2 SportClient built-ins
   (hello, stretch, wallow, front_pounce…) for a one-line hardware path, plus
   3–4 canine-validated gestures (play bow, alert posture, head-tilt).
6. **(week)** Eval extension (latency-to-acknowledgment, blend-continuity jerk,
   interruption correctness, emote duty-cycle caps — over-triggering is the
   documented HRI failure mode) + Blender→YAML authoring loop (DogML/Kine2Go as
   reference only; Bandai mocap is CC BY-NC — never ship derived assets).
7. **(month+, gated)** AMP-style stylized gaits / RL clip tracking; re-evaluate
   text-to-motion (T2QRM, Uni-Mo) only when code actually ships.

---

## 3. Navigation & following (8-step roadmap)

The original sequence is retained below, but its implementation overlay now
matters more than the forecast:

1. **Implemented/wired; direct-follow benefit not demonstrated.** Kalman CV
   owner predictor (2–3 s horizon) behind a swappable
   interface; FollowOwnerController servos the *predicted* path; NIS
   uncertainty brake as a validator rule. Follow-Bench's winning recipe at our
   exact 0.1 s timestep. The current owner-clearance clamp leaves only 0.05 m
   lead in direct mode, and the isolated 90° turn result was unchanged/slightly
   worse; behind-mode benefit has not been evaluated.
2. **Implemented/wired; social-quality and distinct-yield claims remain open.**
   Dynamic agent cost layer on grid_v1 (time-decayed forward-projected
   Gaussian lobes along predicted agent paths) + 1–2 s rollout TTC gate
   before command shaping. Repeated A* at 10 Hz is sufficient today. Tests prove
   corridor avoidance and TTC engagement, but not pass-behind choice or fewer
   interventions than the existing reactive gate.
3. **Implemented/wired; partially measured.** Jerk-limited S-curve velocity
   shaping between safety and `ControlManager`, with affect-modulated profiles.
   A partial dispatch replica reduced suite mean commanded jerk
   0.9592→0.5530 m/s³ with no collision regression; the manager/HAL and calm
   profile remain outside that evidence.
4. **Planned.** MPPI local controller (pytorch_mppi, MIT): K~500, T~20–30,
   costs = grid occupancy + predicted agents + path-align + legibility critics;
   runs at its own faster inner rate while the brain stays at 10 Hz.
5. **Implemented/wired; successful recovery not demonstrated.** `SearchOwner`
   is system-authored rather than model-callable: tracking →
   last-observed-position → yaw-sweep scan → frontier search scored by info
   gain, pruned by a max-owner-velocity reachability disk. The original scenario
   exercised all phases and gave up; planner-backed mobile phases landed later
   but the scenario has not been rerun to a finite reacquisition.
6. **Planned.** Occlusion-aware behind-formation (Adap-RPF): sample 30–50
   candidate follow points per tick around the predicted owner pose, published
   weights (occlusion 10, distance 10, social 1, travel 1, stickiness 0.5).
7. **Planned.** Generalize to objects: OwnerTrack → TargetTrack; open-vocab
   detection (YOLO-World/FAn-style) only at query time to seed a Kalman +
   re-ID tracker; `target` argument on FollowFormation/OrbitOwner.
8. **Planned, hardware/perception-gated.** 2.5D terrain: MuJoCo heightfields + simulated depth +
   elevation_mapping_cupy core as one more cost layer; only after flat-ground
   following is solid.

---

## 4. External benchmark recommendation

**PRIMARY — BARN Challenge, ICRA 2027 cycle** (call expected ~Nov–Dec 2026).
The only active refereed external leaderboard with sim + physical phases that a
classical CPU-only stack can enter and credibly win (the 2025 winner was
rule-based) — and Parcel already speaks its language. Bridge in order:
(1) *days, now:* extend the offline harness from the 50-world proxy to all 300
public worlds and report the official score distribution — externally
comparable with zero ROS; (2) thin ROS2 bridge (/scan → HAL scan frame, HAL SE2
→ /cmd_vel) + Singularity container validated in the official Gazebo pipeline;
(3) the MPPI inner loop serves BARN's 0.3–0.5 m gaps without touching the 10 Hz
companion runtime; (4) DynaBARN (60 worlds) offline for the dynamic-obstacle
part.

**SECONDARY — self-run Follow-Bench comparison** (1–2 weeks, start now): port
FollowOwnerController into the MIT-licensed pure-Python harness
(github.com/MedlarTea/follow-bench) — planner I/O is nearly isomorphic to our
HAL. Report success/jerk/personal-zone against their 6–8 published planners.
Highest companion-quality correlation available; the port pays three times
(comparison table, recipe donor for nav step 1, metric alignment). State
honestly: paper under review, young repo — pin the evaluated commit.

**AVOID:** Habitat (dormant since 2023), MetaUrban (RL protocol, GPU-bound, no
leaderboard), BEHAVIOR/OmniGibson (manipulation axis), Earth Rover Challenge
(interface mismatch), Arena/SocNavBench/HuNavSim as "benchmarks" (metric tools
without leaderboards — mine their definitions only). **WATCH:** RoboSense
SocialNav (needs RGB-D mapless), VLN-CE-Isaac/NaVILA-class Go2 benchmarks once
Parcel moves past the SE2 HAL.

BARN is the refereed flag to plant; Follow-Bench is the number that correlates
with the product. They are complementary, not competing.

---

## 5. Dynamic prompting & context engineering (implemented 2026-08-04, bare v1)

Research verdict (vendor docs + framework source + shipping-companion
analyses): every major realtime voice API converged on three channels —
slow session instructions, fast per-turn silent context, and tool-result
events. A per-turn *mutating system prompt is a prompt-cache anti-pattern*
(volatile content belongs at the tail); retrieval must be prefetched off the
critical path (snapshot-only reads at compose time); and shipping companions
inject **structured profiles + rolling summaries**, not per-turn RAG
(ChatGPT memory, Replika, Letta memory-blocks; hosted memory services cost
150–650 ms p95 per turn — wrong for a robot).

**Implemented now** (`src/parcel_robot/dynamic_prompting.py`, wired through
runtime/agent/safety/panel — see §"What shipped" in the module docstring):

- `DynamicPromptComposer` — named sections, two placement planes
  (`stable` renders first for cache stability; `turn` renders last), per-section
  priorities + char budgets, a global turn budget with *reported* drops.
- `ContextSource` protocol + `CallableContextSource` — the extension point;
  `snapshot()` must never block (fetch in background, return cached text).
- `UserProfileSource` — owner personalization facts (location/home/occupation…)
  from `prompting.user_profile` config, live-updatable
  (`runtime.set_user_fact`, `POST /api/prompt/fact`).
- `ConversationToolRegistry` + `ToolPolicySource` — read-only information tools
  with explicit *when-to-use* guidance rendered into the prompt; the LLM
  decides per turn; the agent dispatches and folds results into the spoken
  reply and memory; the safety supervisor admits tools by exact name,
  fail-closed. `get_weather` ships as the canonical example (offline stub;
  `build_weather_tool(fetch=...)` for a real provider).
- `RecentToolResultsSource` — last N tool results re-rendered per turn.
- **Hillclimb surface:** `GET /api/prompt` returns the full system prompt, the
  section breakdown (chars, truncation, drops), registered tools, and profile
  facts.

`current_situation` is already registered as a volatile `turn` source; the
earlier growth item to move runtime context out of the stable prefix is complete.
The remaining growth path is: verify provider-side stable-prefix cache behavior;
add an async prefetch hook (`refresh()` on partial ASR) for retrieval-backed
sources; add SQLite episodic memory plus a background reflector (Letta
sleep-time pattern); then add a `PendingEvents` source with Gemini-style
`INTERRUPT | WHEN_IDLE | SILENT` scheduling for late async results (navigation
finishing 30 s later) and proactive perceptions.

---

## 6. D0 dual-stream overlay: what the roadmap has actually produced

The approved always-output contract is documented in
[DUPLEX_DUAL_STREAM_DESIGN.md](DUPLEX_DUAL_STREAM_DESIGN.md): one epoch-scoped
nominal-10 Hz frame carries TEXT-or-`<silence>` and ACT-or-`<idle>`. The current
D0 producer composes those frames from existing outputs—reply text entering the
delivery path plus post-gate twists and admitted gaze/skill/emote/filler events.
It also has a deterministic slow-route/watchdog filler policy, a shadow decoder,
local rotating JSONL outcomes, and the scripted `DUPLEX_V1` harness.

That is a useful interface/corpus milestone, not native or model-driven duplex:

- input remains turn-committed; real acoustic streaming partials do not exist;
- ACT observes behavior selected elsewhere and the consumer never drives the
  robot;
- frame continuity covers index/epoch production, not 10 Hz wall-clock timing;
  the caller supplies every tick;
- filler TTFT/ceiling tests use text/fake-TTS clocks because Piper and devices
  are unavailable;
- no retained long-session run proves the log-size target or the privacy of
  reply-derived text plus owner/context values (the user transcript is not
  written today); and
- no D1 dual-head weights, trainer, inference service, or live-ACT admission
  result exists.

D1 should be promoted only by side-by-side replay of identical turns and product
navigation scenarios, with consented/reviewed corpus handling, zero stale-epoch
execution, unchanged collision and interruption gates, and an explicit check
that decoded ACT proposals still pass the current PlanIR/admissibility chain.
