# Parcel AI brain and navigation research

Research date: 2026-08-03. Evidence cut-off: 2026-08-03T22:45:45Z.

Repository status in this report was audited at committed revision
`ce3814a0534d54c983f16614bd1ddb20dc1974b4` plus the explicitly dirty working
tree and the immutable V8 and V9 training artifacts identified below. This is
not a claim about a clean committed snapshot. “Implemented” means code is
connected to the normal Parcel runtime;
“tested” means a deterministic or fake-provider test exercised the contract;
“measured” means a run artifact records the result. None of those labels, by
itself, means that a live open-weight model has passed the complete companion
task suite or that a proxy score is leaderboard eligible.

## Executive recommendation

Parcel should split **responsibilities**, but it should not initially chain two
independent generative language models where one paraphrases the user and the
second plans from that paraphrase. That design adds latency, compounds errors,
and can discard exactly the spatial, emotional, or temporal detail that the
planner needs.

The recommended near-term design is:

1. Keep deterministic reflexes for emergency stop, manual control, and a small
   set of unambiguous commands.
2. Keep the implemented, bounded `IntentFrame` router. It decides only whether a turn is
   conversation, a direct skill, a deliberative task, or a clarification. It
   never controls motion, and it never replaces the original transcript.
3. Keep one admitted shared conversational/reasoning model profile, initially
   the installed Gemma 4 26B-A4B, loaded when that profile is active and invoked
   in two constrained generative modes: a short-budget conversation/social
   `AgentDecision` mode and a deliberate typed `PlanIR` mode. Reviewed direct
   skills bind deterministically before either LLM.
4. Keep the separate `PlanIR` contract and deterministic task executive for
   multi-step work. The executive validates preconditions, arbitrates
   interrupts, locks robot resources, observes progress, and decides whether a
   proposed action is accepted, deferred, recovered, or rejected.
5. Give navigation its own perception-to-waypoint lane. A learned model may
   propose semantic targets or short body-relative trajectories, but a
   camera/LiDAR map, classical global and local planning, an independent safety
   shield, and Unitree Sport remain authoritative for physical execution.
6. Treat speech as another asynchronous lane. Native audio tokens can improve
   turn-taking and expressiveness, but they should not cross the motor trust
   boundary. The action path consumes a final transcript plus bounded
   paralinguistic evidence.

This is a split brain in the useful sense: conversation, task planning,
navigation, execution, safety, and voice have distinct contracts and
timescales. It is not two uncoordinated LLMs competing to decide what the dog
does.

The publicly documented systems reviewed here support this layered direction. Google's current
robotics stack explicitly separates embodied reasoning from a
vision-language-action executor; Figure describes slow semantic reasoning above
faster visuomotor and whole-body layers; InternVLA-N1 runs asynchronous System 2
reasoning above a fast navigation policy; and BARN 2026's documented physical finalists
still combine global search, local planning, and a safety mechanism. None of the
cited systems delegates the entire robot to a conversational model. They
establish the value of hierarchy, not that one shared conversation/planning
backbone is better than two specialists. No reviewed primary study in this
audit directly compares two serial text LLMs with a shared backbone on the same
companion tasks. The shared-Gemma choice is therefore a Parcel-specific VRAM,
latency, and persona-consistency **hypothesis**, not a literature result; the
ablations below must test it.

That distinction also applies to the most suggestive examples. Gemini Robotics
ER 2 describes one high-level brain that can chat, plan, monitor success, and
reason concurrently while handing physical execution to a lower-level VLA;
Helix 02 and InternVLA-N1 separate semantic and embodied timescales. They are
evidence for contracts, authority, and asynchronous execution—not evidence for
how many text-model weight sets Parcel should load for conversation and
planning.

Two omitted counterexamples make that conclusion stronger rather than weaker.
[Robix](https://robix-seed.github.io/robix/) uses one high-level vision-language
model for interaction, reasoning, and planning while a separate controller
executes atomic commands. [OneTwoVLA](https://arxiv.org/abs/2505.11917) goes
further in a manipulation setting: one model adaptively chooses whether to
reason or emit an action chunk, retaining its latest reasoning between critical
events. Both show that distinct cognitive roles do not inherently require
distinct weight sets. Neither shows that a conversational model should own a
Go2 controller: Robix has no public checkpoint linked by its official page,
and OneTwoVLA's public code/data target manipulation rather than Parcel's
camera/LiDAR navigation contract. Their transferable lesson is event-triggered
deliberation inside a hierarchy, not end-to-end motor authority.

## Scope and evidence standard

This report answers four practical questions:

- Should Parcel use one model, a conversational model plus a planner, or a
  shared model with separate modes?
- Which ideas from successful embodied-AI systems transfer to a Unitree Go2?
- Which open or open-weight models are credible experiments on the desktop's
  RTX 5000 Ada 32 GB GPU?
- Where should language reasoning end and navigation/control begin?

The sources are project pages, papers, official repositories, model cards, and
official challenge reports. Results are separated into three evidence levels:

- **Reproducible candidate**: code and a usable checkpoint are published, the
  license is identifiable, and the action interface can plausibly be adapted.
- **Research candidate**: useful code or weights exist, but embodiment,
  dependency, hardware, or license work remains.
- **Architecture evidence only**: a successful or promising system reveals a
  design lesson, but its model is proprietary or its action space is unsuitable.

The principal candidates used later in the report are classified as follows:

| System or model | Evidence level for Parcel | Reason |
| --- | --- | --- |
| Installed Gemma 4 26B-A4B | Reproducible candidate | Official Apache-2.0 Q4 weights are installed. It passed the five-case frozen semantic-plan gate on CPU and full CUDA, and the accepted plans passed the supported deterministic headless gate; neither result proves real sensors or Go2 hardware. |
| Ministral 3 8B Instruct/Reasoning GGUF | Reproducible rejected controls | Both official Apache-2.0 Q4_K_M artifacts are installed, exact-hash verified, and measured at 35/35 CUDA layers. Instruct was rejected as both PlanIR and conversation incumbent. Reasoning failed a predeclared one-case frozen PlanSketch compatibility gate before semantic scoring; it is not a five-case baseline. |
| CityWalker | Research candidate | Code and a locally hashed original checkpoint exist, but RGB trajectory adaptation remains absent. Repository code is Apache-2.0; the exact GitHub v1.0 checkpoint is now conservatively locked as `NOASSERTION`, while a later official converted model is explicitly Apache-2.0. |
| FunctionGemma, `gpt-oss-20b`, Qwen3.6, Kimi-VL | Research candidates | Public weights exist; `gpt-oss-20b` is the first prioritized hardware-plausible general-reasoning challenger for a planner-only replacement experiment, not an admitted robotics specialist. Every candidate still needs Parcel-specific tuning or quality, runtime, peak-memory, and license/usage-policy review. |
| RoboBrain 2.5 4B | Research candidate | Official Apache-2.0 code and a 9.67 GB BF16 checkpoint are public. The model card exposes visual grounding, image-pointing navigation examples, 3D trace prediction, and progress estimation, but no Parcel adapter, desktop latency, dynamic-Go2, or collision-avoidance result exists. It is a semantic-grounding/monitoring shadow candidate, not a controller. |
| InternVLA-N1 and NaVILA | Research candidates | Relevant Go2/navigation code and weights exist, but checkpoint/data terms and dependency isolation are unresolved. |
| CE-Nav and S2E | Research candidates | Public controller code/checkpoints are unusually relevant to Go2 waypoint execution, but each needs isolated dependency, license/artifact, sensor-contract, and held-out safety validation. |
| VLFM, ConceptGraphs, ViNT/NoMaD | Research candidates | Reproducible components exist, but their sensor/goal contracts do not directly implement Parcel's companion task. |
| ABotN-Bench | Reproducible evaluator candidate | Public closed-loop PointGoal/POI evaluation has a minimal adapter and social walkability rules. No official ABot-N1 policy checkpoint was found, so the benchmark is usable evidence while the reported model is not a downloadable solution. |
| VAMOS | Research candidate | Public code and a noncommercial PaliGemma 2 3B-derived checkpoint exist. Released affordance models target Spot/Hound; Parcel would need a separately trained Go2 affordance model and must not imitate BARN's Jackal embodiment. |
| Voxtral Mini 4B Realtime, PersonaPlex, Moshi, Sesame CSM, Fish S2 Pro | Research candidates | Voice experiments need license review, GPU admission, and an isolated motor boundary. Voxtral Realtime is streaming ASR, not a duplex conversation or motion model. |
| Robostral Navigate, Mobility VLA, Gemini Robotics, Helix 02, SayCan, SayTap, Qwen-RobotNav | Architecture evidence only | They supply useful hierarchy and bounded-interface patterns, but the relevant model is proprietary, unavailable, or not a deployable Go2 policy. |
| BARN competition systems | Architecture evidence only | Their planner structure is informative; their standardized Jackal embodiment and contest protocol are not a Parcel checkpoint. |
| FSR-VLN and Nav-R1 | Architecture/research evidence only | Both report fast/slow navigation designs. FSR-VLN depends on a prebuilt RGB-D/LiDAR map and proprietary reasoning components; Nav-R1 publishes a sparse research release whose model card has no documentation and whose repository does not state code terms. Neither is an admitted Parcel dependency. |
| Qwen-VLA | Architecture evidence only | The paper reports a unified 4B-backbone/1.15B-action-decoder generalist, but the official repository currently publishes project information rather than runnable code or weights. Its broad action results do not establish a Go2 controller. |
| Robix and OneTwoVLA | Architecture/research evidence only | Robix is direct evidence for a shared high-level interaction/planning model above a separate executor, but its official page links no code or weights. OneTwoVLA publishes MIT code and training data, but no official pretrained checkpoint is linked and its evaluated action space is manipulation. Both inform model-role and trigger design rather than a deployable Parcel policy. |

Vendor demonstrations are cited as vendor-reported results, not independent
validation. Benchmark scores are not directly comparable across different
sensors, simulators, task definitions, or evaluation protocols.

## Implementation status on 2026-08-03

The first split-brain slice is implemented and the installed model has now been
measured on a small frozen semantic-plan suite. The remaining problem is not to
invent another architecture in prose; it is to broaden the language and
embodied tests, reduce usable-plan latency, improve navigation/perception below
those plans, and preserve the contracts while challengers are evaluated.

| Layer | Current status | What the evidence does and does not establish |
| --- | --- | --- |
| Sensor trust | **Implemented and tested** | Camera and LiDAR are the only admitted environment sensors. The LLM receives sensor freshness, bounded semantic entities, safety/task state, and capability flags; simulator coordinates and evaluator truth are deliberately omitted. Google Maps is disabled and has no trusted runtime path. |
| Intent routing | **Implemented and frozen at contract level** | `DeterministicIntentRouter` preserves an exact transcript reference and SHA-256, acts only on final ASR, suppresses negated/hypothetical motion, and routes conversation, reviewed direct skills, deliberate plans, or abstention. The 15-case `parcel-companion-brain-v1` suite is a regression floor, not a broad natural-language benchmark. |
| Conversation/planning model | **Provider and contract split implemented; CPU/full-CUDA plan gates and a live conversation calibration measured; concurrent scheduling not implemented** | Gemma 4 26B-A4B is the incumbent behind separate short-budget conversation and PlanIR calls. Its frozen full-CUDA PlanIR run passed 5/5 with 855.379 ms median TTFT and 5,657.459 ms median usable-plan latency. On the new ten-case conversation calibration it parsed 10/10, passed 6/10 machine cases and 9/10 structured-safety checks, with 348.843/1,236.951 ms median TTFT/full-call latency; no human review exists. The runtime exposes separate provider objects, role health, and latency attribution, but one `_agent_lock` serializes every non-E-stop model turn and the pinned server launcher does not explicitly admit multiple inference slots. A plan can therefore queue conversation for multiple seconds even with separate endpoints; E-stop and lower control loops remain independent. Ministral 3 8B Instruct reached 101.944 ms TTFT but only 5/10 conversation cases and 3/5 PlanIR, with no full-call latency win. Ministral Reasoning failed its first frozen PlanSketch compatibility case after exhausting 1,024 tokens in 12,262.204 ms; the remaining cases were not run. Neither is promoted. The plan/conversation samples are only five/ten warm sequential cases—too small for stable p95 claims—and omit cold load, concurrent queueing, ASR/TTS/audio, simulator load, sampled peak VRAM, human companion review, and physical episodes. |
| Plan contract and admission | **Implemented, compiled, and tested; compact challenger rejected for now** | Strict `IntentFrame`, `PlanIR`, `PlanSketch`, `ObservationSnapshot`, and `ExecutionResult` schemas reject unknown fields. A contextual schema is a decode hint; after decode, the trusted envelope is authoritative over source turn/task/revision/interrupt. The compiler owns step IDs, resources, required/conditional preconditions, non-navigation success policy, contract timeouts, one safe-stop attempt, and minimum interruptibility. The model still owns skill order, bounded arguments, and `NavigateTo` grounding, so invalid semantics fail closed. Raw velocities, joints, coordinates, locomotion-backend selection, and model-authored priority are absent from model-facing tools and fail closed if emitted. PlanSketch reduced canonical JSON bytes 73.2126% offline and, live on full CUDA, reached 2,037.060 ms median full-call latency, 153 median completion tokens, and 417 median output bytes—but accepted only 3/5 versus PlanIR's 5/5, so it remains opt-in and unpromoted. |
| Long-lived execution | **Implemented and integrated** | `TaskExecutive` owns task revision, checkpoints, resource leases, interruption, retries, and typed results. `SemanticTaskRuntimeAdapter` currently admits `NavigateTo`, `FollowFormation`, `OrbitOwner`, `MoveRelative`, `Hold`, `Vocalize`, and `AskClarification`, and verifies completion from controller state instead of trusting model narration. Pose/gesture and battery-safe-pose contracts exist in the registry but are not admitted by the current runtime adapter. |
| Embodied PlanIR execution | **Measured in deterministic headless simulation with idealized semantic perception** | The frozen accepted plans passed all 4/4 supported cases. One compound case is explicitly unsupported because the fixed-owner world cannot exercise moving-owner `FollowFormation`; its orbit prefix still executes but cannot be laundered into a pass. Across five cases the gate ran six physical skills and 1,137 simulator steps with zero collisions, zero timeouts, and 0.883147 m minimum clearance. The controller receives geometry-derived oracle semantic tracks constrained by camera-like range/FOV, so this is kinematic planning/controller evidence—not rendered-camera detection, association, sensor accuracy, contact physics, or Go2 hardware evidence. |
| Owner-follow formation | **Implemented and tested at controller level** | Passive camera tracks estimate the owner's direction of travel, filter outliers, require minimum displacement/speed and multiple updates, reset on owner-ID change, expire stale evidence, stage around the owner keep-out, and stop on LiDAR/person risk. This estimates motion heading, not a stationary person's body orientation; behind formation must fail closed while that evidence is absent. |
| Control and safety | **Implemented below the brain; physical commissioning pending** | Manual/E-stop arbitration, collision limits, watchdogs, and controller feedback remain authoritative. Stop deliveries are generation-ordered so delayed bookkeeping from an older asynchronous E-stop cannot overwrite a newer compensating StopMove feedback boundary; the reproduced close race passed 300/300 stress iterations after the fix. The Unitree adapter is designed to send bounded body-velocity setpoints to the closed-loop onboard Sport gait/balance controller, but axis/state-frame commissioning flags and allowed modes are intentionally unset, so the physical path currently fails closed. Parcel does not implement or claim Unitree's internal balance loop. |
| Dynamic simulation | **Implemented baseline; procedural integration pending** | The MuJoCo/headless city has seeded pedestrians/cyclists, camera/LiDAR-derived proximity and time-to-collision signals, and deterministic task tests. `MetaUrbanNavEnv` is explicitly a kinematic scaffold: `use_metaurban=True` raises until a real isolated observation/action adapter exists. |
| Voice and audio | **Text path implemented; full-duplex model is research-only** | Final transcript reasoning, cancellation, text logging, and latency stages exist. The host has a powered Bluetooth controller and an ALSA-visible analog capture device, but PipeWire exposes no active source and only a dummy sink; no Bluetooth headset is paired. Native duplex speech still must not authorize motion. |
| External evaluation | **Proxy and local runtime-compatibility paths measured; no official protocol or rank evidence** | BARN's fixed-50 native proxy remains 44%/0.106267 and unpromoted. Safe-valley v5 and guard v6 failed their frozen gates. The v7 score is permanently null because its nearest-cluster invariant failed before execution. The single-use V8 development run then authenticated all 49,744 actions across 60 evidence files and passed all safety, provenance, and latency gates, but failed all three efficacy gates: reference and candidate were both 0/30 success, metric 0, and 80% timeout. V8 is rejected. V9 supervisory-gap S2 produced the first training-only gain—1/10 success and one fewer label-independent liveness failure—but failed seven frozen scratch-gate checks. S3 was rejected by static review without execution, and S4 remained 1/10 while increasing yaw churn and reducing efficiency; both are rejected. No 100-world training screen, development run, or holdout access is authorized. Upstream MPPI alone completed ROS/Gazebo world 0 at 0.1802; Parcel's one calibrated public-world-0 row remained a timeout/metric-zero compatibility baseline. Habitat's exact runtime passes a CUDA/EGL public-test-scene action smoke but no PointNav task or metric. A 13-blocker source audit quarantines the current 3WE revision. None substantiates an official score, rank, or top-decile claim. |

### Implemented end-to-end brain path

For a final transcript, the normal runtime now performs this sequence:

```text
exact final transcript
  -> deterministic route and provenance
  -> initial camera/LiDAR-only snapshot + runtime/context-filtered schema
  -> direct skill: deterministic argument binding; or
     conversation: short-budget AgentDecision schema decode; or
     task: deliberate Gemma PlanIR/opt-in PlanSketch decode and trusted binding
  -> deterministic PlanIR binding or PlanSketch-to-PlanIR compilation when planning
  -> fresh camera/LiDAR-only snapshot for admission
  -> fail-closed PlanValidator
  -> TaskExecutive acceptance/revision/interrupt policy
  -> semantic runtime adapter
  -> existing navigation/follow/spatial controller
  -> command arbiter + safety + Unitree Sport/simulator controller
  -> typed progress or terminal ExecutionResult
```

This closes the previously missing abstraction between a one-turn
`AgentDecision` and a long-lived navigation task. It supplies explicit task
state, semantic success conditions, recovery, corrections, and
feedback-grounded completion. The five-case semantic gate verifies this
boundary for five compound instructions, and the separate headless gate
physically executes and passes all four supported cases. It does **not** prove
that live Gemma reliably plans broad paraphrases or conversation, that real
camera perception finds every sidewalk or lamppost, that moving-owner following
works in this fixed-owner world, that the Go2 executes those plans, or that the
current local planner meets the target external ranks.

### Current navigation evidence

A camera/LiDAR-compatible rolling-grid/A* challenger was selected on ten
development-only public BARN worlds disjoint from the frozen PR set, then run
without tuning on a fixed 50-world proxy subset. The selected fixed-50 paired
run is `barn-ab-20260803T093224170877Z-6b24e34f`:

| Proxy metric | Prior controller | Selected grid/A* | Paired evidence |
| --- | ---: | ---: | --- |
| Success rate | 2% | 44% | 21 success gains, zero success regressions |
| Native navigation metric | 0.004556 | 0.103698 | 22 metric gains, zero metric regressions |
| Collision rate | 0% | 0% | zero collision regressions |
| Minimum signed evaluator clearance | 0.4575 m | 0.0807 m | lower, therefore tracked as an explicit safety/comfort tradeoff |
| Failure termination | 49 stopped outside goal | 26 stopped outside goal, 2 timeouts | the recovery/no-path cases remain the main quality gap |

The selected frozen-PR run reached 90% success, metric 0.212213, and zero
collisions. A later projected closing-speed cap improved its disjoint
development slice from 70% to 80%, but only tied the selected frozen-PR result;
the final fixed-50 run `barn-native-20260803T110001471552Z-d8a245ce` also tied
the selected result episode-for-episode at 44% success, 0.103698 metric, zero
collisions, and 0.0807 m minimum signed clearance. The feature remains
deployment-disabled and was not promoted because there was no held-out gain.
Larger-map, blind-reverse, and narrow-clearance experiments were rejected or
retained as development-only evidence when they added latency, worsened
termination, or reduced clearance.

The later `grid_frontier_v2` experiment targeted the remaining recovery
deadlocks without weakening the sensor or safety boundary. All 28 selected
fixed-50 failures were deadlocks rather than collisions: 26 watchdog stops and
two timeouts, including six episodes with zero motion despite 1.781 m private
clearance. A known-free connected-frontier search marginally improved the
development and frozen-PR metrics, but on the final paired fixed-50 gate it
left success at 44%, raised metric only from 0.103698 to 0.104676, rescued none
of the failures, reduced minimum clearance from 0.080676 m to 0.077735 m, and
roughly doubled mean controller latency from 41.57 ms to 83.61 ms. Six episode
metrics improved, 11 regressed, and 33 tied. Run
`barn-native-20260803T115359163923Z-a996ed05` was therefore rejected;
`grid_frontier_v2` remains deployment-disabled and the selected `grid_v1`
incumbent is unchanged.

The bounded `grid_frontier_cached_v3` follow-up reused one observed, hard-safe
connectivity search rather than paying for v2's duplicated traversal. Its
development selection showed a large controller-latency improvement. The final
frozen fixed-50 run
`barn-native-20260803T123317614760Z-4c0dea7e` nevertheless retained exactly 44%
success and zero collisions, raised the native metric only to 0.106267, and
rescued none of the selected controller's 28 failures. Mean/p99 controller time
fell from v2's 83.610/314.923 ms to 8.248/59.461 ms, while the clearance floor
was 0.079432 m versus 0.080676 m for the selected `grid_v1` reference. This is a
useful runtime experiment, not a recovery breakthrough: v3 remains
deployment-disabled, does not replace `grid_v1`, and supplies neither a
production nor a top-decile claim.

The next recovery experiment, deployment-disabled `grid_frontier_detour_v4`,
used a hash-ranked 30-world development split and predeclared a separate
20-world sealed confirmation split before any candidate execution. Its bounded
temporary goal-regression frontier branch was exercised for 185 alignment and
75 translation ticks, but it rescued zero episodes: success remained 14/30,
the metric tied at 0.111927574, collisions remained zero, and one watchdog stop
became a timeout. Mean clearance decreased by 0.0322 m and controller mean/p99
ratios were 0.994/1.007. It failed the predeclared development gate, so the
sealed confirmation IDs were neither run nor inspected. This negative result
narrows the deadlock diagnosis without consuming held-out evidence.

The official-code runtime path has also crossed a different milestone. A
cache-only ROS 2 Jazzy rootfs, built with Bubblewrap plus pinned PRoot only for
ownership-sensitive package configuration, launched the **unchanged upstream
Nav2 MPPI example** in Gazebo Harmonic on public world 0. The checksum-bound row
was `0 1 0 0 37.7150 0.1802`: success, no collision/timeout, 37.715 seconds,
metric 0.1802. Critical evaluator hashes match pinned commit
`d6c575b51e477bd524d634e12cffeb34036fcd1e`, and the upstream checkout remains
clean. This proves the desktop can build and execute that one official-code
runtime scenario. It did not use Parcel's adapter/controller, did not use the
upstream-tested Singularity/SIF path, and did not run 500 public episodes or
hidden scoring. It is therefore compatibility evidence—not a Parcel BARN
score, policy comparison, or top-decile result.

The next compatibility slice packaged the existing Parcel ROS 2 sensor adapter
and unchanged `grid_v1` `DirectiveNavigator` into a content-addressed bundle,
then derived an overlay from the pinned official launch bytes by replacing only
the documented `launch_navigation_stack` hook. The first bounded world-0
attempt did not produce a row: its `additional_env` replaced ROS's inherited
`PYTHONPATH`, the child failed to import `rclpy`, and the required-process
handler shut down the launch. The runner therefore wrote neither Parcel result
evidence nor an append-only ledger entry.

The corrected package
`ea6904bf4ec5a19b05ad1a147f89d0f09023a135662d5330f24f3c972a4053f2`
then passed a fresh verification of all 114 manifested files, the exact
hook-only derivation, the clean pinned evaluator hashes, ROS imports, and
controller construction. Exactly one world-0 run reached the adapter startup
marker and a command-bridge marker. It nevertheless stayed in the evaluator's
pre-trial `Waiting for robot to start moving` state until the 180-second outer
bound; there was no `Trial running` marker or terminal row. This proves startup
compatibility but not an episode: BARN's 100-second trial timer begins only
after 0.1 m of translation. The ignored log SHA-256 is
`6e74d9e7f7117af0381ce68f17e4710efc96df4f3e431787c3c0b026b9504dbd`
(30,295 bytes). No Parcel raw result, evidence JSON, or ledger entry existed
for that attempt, so it supplied no Parcel adapter metric. Evaluator-only
first-sensor/first-command telemetry and a new
ten-second causal startup gate now make a future content-addressed attempt
diagnosable without changing production control. The gate requires a
positive-forward command followed by measurable XY odometry response; otherwise
it publishes zero and exits nonzero as `no_inputs`, `policy_no_translation`, or
`actuator_no_response` before any result evidence can be written.

The causal defect was then fixed at the evaluator-only sensor boundary. The
calibrated-v2 transport binds the pinned `base_link <- lidar2d_0_laser`
transform (`+0.12 m`, zero lateral/yaw), validates LiDAR and odometry frames,
keeps scan and odometry acquisition times distinct with at most 0.05 s skew,
and invalidates robot-cylinder endpoints using the 0.05 m geometry plus a
named 0.005 m half-resolution margin. Invalid self returns remain NaN/unknown,
not infinity/free; finite external hits win a reprojected bin. The frozen
production navigator and native evaluator code were not changed. In the exact
pure-core causal replay, the uncalibrated frame still returned `no_path` and
zero forward velocity, while calibrated normalization returned `vx=0.09` and
`grid_track ... status=partial`.

Exactly one new content-addressed public-world-0 run exercised bundle
`75f7ff4dfbf45d36f67cdf3eb3eac6a7e9d05abf48350db449ca23d93b597813`.
The first live frame reported 720 rays, 686 finite returns, and 100 removed
self returns; scan/odometry stamps were 8.825/8.820 s. The first command was
`vx=0.09`, startup liveness passed after three commands and 0.038266 m XY
response, and the unchanged evaluator entered `Trial running`. Parcel then
moved from approximately `(-2.25, 3.11)` to `(-2.66, 5.28)` before a
mid-episode navigation deadlock. The evaluator-owned terminal row was
`0 0 0 1 100.0070 0.0000`: timeout, no collision, metric zero. Run
`barn-ros2-parcel-20260803T155459Z-world0-75f7ff4d` is therefore the first
local Parcel-adapter BARN row and an important compatibility correction, but
it is also a failed navigation baseline. It is one consumed public episode in
a diagnostic Bubblewrap/PRoot runtime, not the 500-episode public protocol,
the upstream-tested SIF path, an official score, or rank evidence. World 0
must not now be tuned or rerun to manufacture a gain.

A read-only, sensor-faithful replay then separated that new failure from the
calibration repair without running Gazebo again. It used the immutable bundle's
code and configuration, the exact world-0 cylinders, a 360-degree/720-ray scan
from the pinned `+0.12 m` LiDAR origin, the analytic robot self-cylinder, the
calibrated normalizer, and ideal unicycle actuation. Its first-frame counts
closely matched the live frame (690 finite/99 self versus 686/100 live), and it
stalled at `(-2.6221, 5.2353)`, only 0.059 m from the evaluator's final pose,
after 2.325 m of travel. At stall onset the grid navigator still proposed
`vx=0.5647` with `grid_track ... status=planned`; the nearest normalized cluster
was 0.8592 m away at bearing 0.8639 rad. The packaged legacy safety profile
computed the projected stop boundary as
`0.8 + 0.5647 * 0.12 = 0.8678 m`, suppressed translation, and preserved yaw.
It then produced 800 consecutive `obstacle_stop` outcomes before the progress
watchdog stopped the task at step 881. Post-run evaluator geometry independently
places the final base 0.811707 m from the nearest obstacle surface, with
0.491707 m signed body clearance and only about 0.014 m deviation from the
public reference path. Those private geometry values were used only for
diagnosis after the episode, never as policy input.

This close pose and phase match strongly localizes the timeout to an
embodiment/profile mismatch: the ROS package used `barn_grid_v1.yaml`'s legacy
0.8 m stop distance plus reaction-distance term, while later eval-only Jackal
profiles use a 0.38 m base value. It does not prove that 0.38 m is the right
production Go2 threshold or authorize changing it on consumed world 0.

The initially proposed v7 experiment did not survive pre-execution review. Its
policy reduced 720 normalized rays to clusters and passed only the globally
nearest cluster into the final projected cap. A return at 0.81 m and 90 degrees
can therefore mask a return at 0.83 m directly ahead: for a 0.45 m/s command,
one 100 ms tick moves 0.045 m and takes the forward return to 0.785 m even
though the configured sensor-distance boundary is 0.8 m. The predeclared claim
that every positive-closing return retained one reaction horizon was false.
No v7 map, manifest, claim, result, confirmation asset, or score was created.
The content-authenticated
[`RETIREMENT.json`](../evals/external/development/barn_predictive_shield_v7/RETIREMENT.json)
records `invalidated_pre_execution`, and both its generator and runner now fail
before writes. IDs 3000--3049 and the v7 seed namespace remain retired rather
than being silently reused.

V8 implemented that successor as a final-shield replacement, not a YAML-only
ablation. The reference is the byte-exact historical package
`75f7ff4dfbf45d36f67cdf3eb3eac6a7e9d05abf48350db449ca23d93b597813`;
the candidate is isolated package
`189ac31f0f6a461da9e10fad2ac21b2bc3a485a4d5245c517b1492b2a16eb7d9`.
Its allowlisted source delta examines all 720 normalized rays, accounts for the
commanded yaw sweep over the reaction/control horizon, and chooses the most
restrictive positive-closing component. An evaluator-owned certifier checks the
published action independently. Before corpus freeze, the complete repository
suite passed 919 tests; the focused V8 suite passed 193 tests and covered the
tangential-nearest/forward-farther, tangent-plus-turn, ray permutation,
monotonicity, malformed-scan, transaction, and evidence mutations.

The single-use, paired development run
[`barn-v8-development-20260803-run01`](../evals/external/development/barn_all_ray_shield_v8/results/single-use-development-transaction/report.json)
completed at 2026-08-03T19:57:07Z. The frozen 30-world corpus SHA-256 is
`4b80e48fd19db59b372cd98aa002dcfe6a32387e2810e79cc58a102f91a40597`;
the read-only [manifest](../evals/external/development/barn_all_ray_shield_v8/split.json)
SHA-256 is
`09985b61d6964da01056931647b7ebe69db726b5ae7a7a4356bbdf60534a9550`.
Evaluator, adapter, model, Python/NumPy runtime, calibration, seeds, worlds, and
counterbalanced pair order were held fixed. The outcome was a completed
`development_gate_failed`, not an abort:

| V8 development measure | Historical reference | All-ray candidate |
| --- | ---: | ---: |
| Success | 0/30 | 0/30 |
| Navigation metric | 0.000000 | 0.000000 |
| Collision rate | 0% | 0% |
| Timeout rate | 80% | 80% |
| Controller-step p99 | 30.981539 ms | 31.685694 ms |
| Minimum signed body clearance | 0.466801 m | 0.479924 m |
| Mean final goal distance | 8.576011 m | 8.523303 m |
| Mean traveled distance | 1.493660 m | 1.555203 m |

V8 passed 16/19 frozen gates: zero collisions, zero observed-return certificate
violations, zero translation when perception was unavailable, the 0.475 m
candidate clearance floor, both latency limits, exact one-factor/runtime
identity, counterbalanced pairing, and complete immutable evidence. It changed
the first action under an identical observation in 20 paired episodes and
recorded 333 actions where the globally nearest ray was not the limiting ray.
All 49,744 issued actions in 60 binary artifacts were verified. It failed only
the three efficacy gates: at least three success gains, at least +0.10 success
rate, and at least +0.01 navigation metric.

The negative result is diagnostically sharper than the aggregate score. The
candidate finished closer to the goal in 19 pairs, farther away in one, and
identically in ten, but both policies had the same six startup timeouts and 23
`navigation_no_progress` terminal decisions. A later read-only audit of the
immutable final-action evidence corrected an important instrumentation claim:
V8 did **not** remove the reference's 20 physical translation stalls. It
removed the literal legacy `obstacle_stop` label used by the harness's stall
counter. Because every normalized scan contained unavailable bins, the shield
reported `all_ray_observed_returns_only_incomplete_scan` before reporting its
hard-boundary state; the note parser therefore counted zero candidate long
shield stalls even while final `vx` remained zero for hundreds of ticks.

The 30 candidate failures partition exactly as follows:

| V8 candidate failure mode | Count | Evidence-backed mechanism |
| --- | ---: | --- |
| Startup route loss | 6 | `partial` becomes `no_path`; rotate-only recovery never crosses the evaluator's 0.1 m startup threshold despite 1.781 m private initial clearance |
| Post-start route loss | 4 | after 0.5--1.4 m of progress, a replan flips the route heading by roughly 155--180 degrees and then becomes `no_path`; recovery rotates for an 800-tick stationary tail |
| Hidden all-ray boundary stall while tracking | 20 | a valid route remains, but one off-axis positive-closing return at approximately 0.8 m forces the all-ray translation scale to zero while the tracker continues proposing the same incompatible path direction |

In the dominant 20 worlds, the limiting return was 37.3--60.8 degrees off the
forward axis. This is not evidence that the all-ray invariant is wrong: the
invariant correctly vetoed its proposed vector and produced zero certificate
violations. It is evidence that a scalar final shield cannot create a new
trajectory. The global grid treats approximately 0.42 m as hard inflation,
while the downstream translation boundary is 0.8 m in the normalized LiDAR
frame. A point-waypoint tracker can therefore pursue a globally valid route
that its final safety layer will never admit.

V9 consequently retains the V8 shield and independent certifier but changes
one tracker subsystem above them. Plain Regulated Pure Pursuit is not enough:
its curvature, approach, and collision-horizon regulation can slow or reject
one reference-path arc, but it does not search a neighboring corridor. Rotation
Shim, Graceful convergence, and velocity smoothing likewise cannot repair an
infeasible route geometry. The selected hypothesis uses an RPP-style nominal
sequence only as a warm start, seeds additional candidates from scan-visible
gaps, rolls bounded forward/yaw trajectories, hard-rejects candidates that
violate the same observed-return boundary, and scores the survivors for route
progress, path agreement, clearance, smoothness, and commitment continuity.
The BARN profile remains forward-only (`vx >= 0`, `vy = 0`); Parcel retains
`vy` in its Go2/manual interface but does not use strafing as nominal
destination motion.

V9 must use fresh identities rather than rerun V8: IDs 5000--5099 are
rerunnable, evidence-ineligible training worlds; 5100--5129 are single-use
development; and 5130--5149 are an unmaterialized operational holdout recipe.
The exact rejected V8 candidate bundle is the experimental control, not a
promoted policy. A new candidate is derived from that content-addressed bundle
with only the tracker hook and implementation allowlisted; configuration,
global planner, pipeline, collision logic, final shield, adapter, evaluator,
and runtime remain byte-identical. The gate adds label-independent stationary
runs, structured shield-veto counts, no-progress reductions, and a required
safe 0.5 m escape witness to the prior safety, efficacy, provenance, and p99
limits. A three-of-30 paired-gain development threshold is only a hill-climb
screen—under zero regressions it is not independently significant at 0.05—and
cannot support an official or top-decile claim.

The immutable artifacts are bound by SHA-256: report
`048335b68d4fdd954fa1896a7f6d115ab97d1bb35a4993702fe8ac193b41bbba`,
[evidence index](../evals/external/development/barn_all_ray_shield_v8/results/single-use-development-transaction/evidence-index.json)
`f37da368cc46a6f62fa47f197e3826449e27a7e5182a02f5228005d30f5fd92c`,
[ledger](../evals/external/development/barn_all_ray_shield_v8/results/ledger/single-use-development-ledger-record.json)
`b74339c683a0c0351bf868cc49600cb492f24fa98f4787188a1bd66b1920dd80`,
claim `a4f695b12179de643fb5540912298c2b531709afc346512be1ab14f5376591c3`,
and outcome
`40757530d6ad22a232781cc4c6b61dd28f9f5bb70b361bcc32a1321a4554472c`.
The result explicitly records `official_score=false`,
`leaderboard_claim=false`, `holdout_authorized=false`, and
`holdout_evaluated=false`. Holdout IDs 4030--4049 remain only an
unmaterialized, non-cryptographically-sealed operational recipe; they are not a
secret holdout and were not generated or inspected.

### V9 training screens: one success is not yet a promotable policy

Four V9 challengers have now completed the same counterbalanced ten-world
screen on training IDs 5000--5009. These IDs are a rerunnable,
evidence-ineligible slice of the frozen 100-world V9 training corpus; none of
the runs is promotion evidence, an official score, or a leaderboard result.
All four used one trial per world and compared a content-addressed tracker-only
challenger against the exact rejected V8 all-ray bundle. The global planner,
sensor normalization, final V8 shield, independent action certifier, adapter,
evaluator, configurations, seeds, and alternating arm order remained fixed.
V9 development IDs 5100--5129 and operational-holdout IDs 5130--5149 remain
unmaterialized and unrun.

The first challenger was package
`c68bb69c247404d0deee28f26d8000200f73aeb336fb9bb0cafd0f0c3b510833`.
Its immutable [training report](../evals/external/training/barn_sampled_predictive_tracker_v9/results/runs/barn-v9-training-c68bb-screen10-20260803-run01/report.json)
has SHA-256
`ec76ac5895a8a4f3afb75447a2a1c60e0eac77fba25f731829caa3d4492193ed`;
the [label-independent analysis](../evals/external/training/barn_sampled_predictive_tracker_v9/results/runs/barn-v9-training-c68bb-screen10-20260803-run01/analysis/label-independent-liveness-v1.json)
has SHA-256
`89f4ed164a5532f09ed6989e634424e24085b98f5cb0cb73f1b693e3f52f7047`.
The second was the more conservative supervisory-gap S1 package
`841597cdb34920506f1c41fd1989faeea04416e616548361868a9f1d3bfd0172`.
Its immutable [training report](../evals/external/training/barn_sampled_predictive_tracker_v9/results/runs/barn-v9-training-supervisory-gap-s1-841597-screen10-20260803-run01/report.json)
has SHA-256
`c70e2a8d42c1c6890a1b657e620142b308a36d270b7bafab281a8be8cd8f9e28`;
the corresponding [label-independent analysis](../evals/external/training/barn_sampled_predictive_tracker_v9/results/runs/barn-v9-training-supervisory-gap-s1-841597-screen10-20260803-run01/analysis/label-independent-liveness-v1.json)
has SHA-256
`d17e1dcefd7503889007d5570cc05e7221097e341644385746bab517f7b0d4c3`.
The third was supervisory-gap S2 package
`68e3e66638aea3549bb26618c6b29e02a8e2a309726dddc55c4ef53ad5a0159c`
with manifest
`04867ea70a7c4f7f0d9f6383815e2d592df635eafb2d8833e193f70d4de4dad7`.
Its immutable [training report](../evals/external/training/barn_sampled_predictive_tracker_v9/results/runs/barn-v9-training-supervisory-gap-s2-68e3e6-screen10-20260803-run01/report.json)
has SHA-256
`3ccce81f675a7556fa9618cb8c14dfea1ff5f0d35cd17732699dcaa49157962d`;
the [label-independent analysis](../evals/external/training/barn_sampled_predictive_tracker_v9/results/runs/barn-v9-training-supervisory-gap-s2-68e3e6-screen10-20260803-run01/analysis/label-independent-liveness-v1.json)
has SHA-256
`1cc259ed55ee96ccfae9d784d9734924a7537f0e9da9b80418c05cc645a6ff9f`.

S3 was a deliberately frozen but **unexecuted** preflight candidate. Static
review found that a non-emergency hold could publish a yaw state inconsistent
with its slew state, an exhausted search could restart on unchanged route
evidence, and raw-route fallback could select a point behind the robot. Its
package `258e9a33e706babe236dd8bd517839c6ddc085ccbfc750532f1a0ce7baeec1a6`
and freeze
`88b18be078b042966b4e7c02ea2ba84dc93c750a37fd526e77a4e9ec795088ca`
are retained as negative design evidence; no simulator metric exists and none
is inferred.

S4 corrected those three defects before execution. Its package is
`3c7396633e5b5df611e343d6ca8c5cf253e1bc975019a524394c48ffb7f3fec9`
with manifest
`a80c074cb3a23148c24b4a5b217c7e9fd744ef863d635f01e9e9b112a43e6b29`
and freeze
`a26c32c92f85bd4e3d63f042578d8a5c9b3d66ef8c6690dde91a00797a140b9c`.
The immutable [training report](../evals/external/training/barn_sampled_predictive_tracker_v9/results/runs/barn-v9-training-supervisory-gap-s4-3c7396-screen10-20260803-run01/report.json)
has SHA-256
`67723082d577ec8384788faa1d8e71d498ce9c84d7aafc992bacddf5d24b54bf`;
its [label-independent analysis](../evals/external/training/barn_sampled_predictive_tracker_v9/results/runs/barn-v9-training-supervisory-gap-s4-3c7396-screen10-20260803-run01/analysis/label-independent-liveness-v1.json)
has SHA-256
`6909ad2e20ada833a0835aa2492bcf2ef4f6d5847e282ccded3ac3ee5e7e22d7`.

| Ten-world training measure | V8 experimental control | Initial sampled tracker c68 | Supervisory-gap S1 | Supervisory-gap S2 | Supervisory-gap S4 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Success / navigation metric | 0/10 / 0.000000 | 0/10 / 0.000000 | 0/10 / 0.000000 | **1/10 / 0.018911** | 1/10 / 0.012500 |
| Terminal mix | 2 startup timeouts, 8 timeouts | 10 timeouts | 10 timeouts | **1 success, 9 timeouts** | 1 success, 9 timeouts |
| Mean maximum goal progress | 1.759759 m | 1.534954 m | 2.094683 m | **2.828198 m** | 2.751902 m |
| Mean net goal progress | 1.759759 m | 1.513701 m | 1.993268 m | **2.642302 m** | 2.476663 m |
| Mean final goal distance, lower is better | 8.240241 m | 8.486299 m | 8.006732 m | **7.357698 m** | 7.523337 m |
| Mean traveled distance | 1.833977 m | 1.844547 m | 4.409941 m | 6.034672 m | 6.407573 m |
| Mean goal-progress efficiency | 0.855972 | **0.871212** | 0.536889 | 0.504140 | 0.395631 |
| Minimum signed obstacle clearance | 0.479921 m | 0.480072 m | **0.511160 m** | 0.480056 m | 0.480067 m |
| Controller-step p99 | 24.490--24.496 ms | 32.134731 ms | 24.223484 ms | **23.513026 ms** | 26.629506 ms |
| Policy stop latches / rate | 8 / 0.8 | 5 / 0.5 | **1 / 0.1** | 5 / 0.5 | 6 / 0.6 |
| Label-independent liveness failures | 10/10 | 10/10 | 10/10 | **9/10** | 9/10 |
| Moving-translation / yaw-only actions | 561 / 2,007 | 1,523 / 7,021 | **3,325 / 4,549** | 3,049 / **4,123** | 3,533 / 5,691 |
| Longest stationary run | 799 steps | 800 steps | 771 steps | 800 steps | 74 steps |

The c68 result rejects the idea that a larger amount of sampled turning is by
itself useful recovery. It issued 7,021 yaw-only actions, made less maximum and
net progress than the control, finished farther from the goal, and converted
the two control startup failures into ordinary timeouts without producing a
single success or liveness gain. Its six physical safe-escape witnesses show
that it could sometimes move at least 0.5 m while retaining the configured
clearance and action certificates; they do not show that those escapes caused
better terminal navigation.

S1 is a real subsystem improvement but still a rejected policy. It eliminated
candidate startup failures on the screen, more than doubled c68's
moving-translation action count, reduced yaw-only churn, improved maximum and
net progress, ended closer to the goal than the control, raised the observed
clearance floor, and kept controller p99 below one 100 ms navigation period.
It also produced seven physical safe-escape witnesses. Yet all ten episodes
still failed: the label-independent taxonomy contains nine other long
stationary stalls and one timeout without a long stall, exactly the same ten
liveness failures as the control. Its 4.409941 m mean travel yielded only
1.993268 m mean net goal progress. That gap is evidence of detour/commitment
inefficiency, not successful navigation. Lower policy stop-latch rate cannot be
treated as a win when physical trajectories still stall or wander.

S2 supplies the first terminal and label-independent liveness gain in V9
training, but it is not a promotion candidate. The table rounds for comparison;
the exact S2 aggregate is 1/10 success, navigation metric
0.01891066856766036, zero collisions, zero startup failures,
0.4800559279141429 m minimum clearance, 2.828198355130386 m mean maximum
progress, 7.357697889581092 m mean final distance, 6.03467178147187 m mean
travel, 0.5041404783887322 mean goal-progress efficiency, 23.513026 ms
controller p99, five policy stop latches, 4,123 yaw-only actions, and nine
liveness failures—a reduction of one from the control. It succeeded in world 5002,
finishing 0.996811 m from the goal after 9.003189 m maximum progress and
9.099867 m of travel, with 0.989376 goal-progress efficiency and only 18
maximum consecutive stationary steps. Those are real improvements, but the
aggregate cost was long, inefficient motion and five policy stop latches. The
derived scratch-gate decision, SHA-256
`254d53ac946c19a5c73dcfc6651f7e2f9c6b25911c2d8d4c43d8ea34f0e3`,
failed seven checks: the stop-latch ceiling, aggregate mean-efficiency floor,
world 5009 final-distance ceiling, and the per-world travel and efficiency
limits for both worlds 5007 and 5009. S2 is therefore rejected at the
ten-world training screen. The 100-world training screen is not authorized;
development IDs 5100--5129 and holdout IDs 5130--5149 remain unmaterialized and
unrun. This result is not promotion evidence, an official result, or evidence
of top-decile performance.

S4 is also rejected. It retained S2's one success and zero collisions, removed
S2's long holds in world 5000 (642 steps) and world 5005 (800 steps), and reduced its longest
single stationary run to 74 steps. Those facts do not amount to better
navigation. Compared with S2, nominal grid phases fell from 2,907 to 1,142,
escape rotations rose from 2,339 to 5,073, yaw-only actions rose from 4,123 to
5,691, mean efficiency fell from 0.504140 to 0.395631, and stop-latched worlds
rose from five to six. Its locally recomputed scratch-gate decision, canonical SHA-256
`e31ccf1704d12ff910c9b14d5fc7272755715f82e1784a8fc3b7371ccfa264d1`,
failed 15 checks. Among them were the two-success and two-liveness-gain floors,
the zero-stop-latch and yaw ceilings, aggregate progress/efficiency conditions,
and per-world stationary/efficiency invariants. No larger training or
development execution is authorized.

World 5002 is a paired mechanistic trace witness rather than an aggregate guess. S2
completed it in 281 actions, 27.68 seconds, and 9.10 m of travel at 0.98938
goal-progress efficiency. S4 first interrupted an escape when its current
direction fell to 0.795389 m against the immutable 0.8 m threshold. A small
0.182054 m reduction in direct goal distance exceeded S4's 0.025 m
"productive" threshold, so it immediately recommitted on the same detour side
instead of handing control back to the still-live route. The resulting chain
lasted through step 728, contained a 74-step translation-free interval, and
finished successfully only after 874 actions, 86.98 seconds, and 11.67 m of
travel at 0.77147 efficiency. Similar search-plus-rotation chains produced
four liveness stalls in world 5007. S4 therefore converted holds into motion,
but much of that motion was tangential churn rather than task progress.

An unfrozen `supervisory_gap_s5` causal control now implements the narrow trace
repair: a productive interrupted escape publishes one yaw-slew-safe braking
frame, preserves its detour memory, resets the blocked-positive counter, and
returns authority to ordinary route admission on the next frame; only a
nonproductive interruption may flip side and restart search. Thirty-two focused
tests cover that handoff, latch release, state consistency, and unchanged
nonproductive behavior. It has no source contract, freeze, package identity,
simulator run, metric, or promotion status. It is retained separately from the
planner-profile experiment so their effects cannot be conflated.

This conclusion does not depend on policy-authored diagnostic labels. For all
four executed runs, the analysis fully reread and hash-chain checked every action
artifact, independently recertified the published actions, recomputed every
post-integration trace hash, and verified the one-to-one action/trace join. It
classified liveness from odometry and issued actions and explicitly did not use
policy notes. The retained evidence lacks pre-shield requested velocity and
shield-scale fields, so null values were not counted as structured shield
vetoes and the analysis does not manufacture a shield-causality claim. The
physically observed liveness outcomes—ten failures for c68 and S1 and nine for
both S2 and S4—therefore outrank more optimistic internal phase labels.

#### What V9 changes about the split-brain decision

These results strengthen the existing architecture recommendation while saying
nothing in favor of a second serial text model. A conversation model can infer
that “go to the sidewalk” is a navigation request, and a planner can bind it to
`NavigateTo(sidewalk)` plus a semantic success relation. Neither operation
selects a safe corridor around the obstacle currently visible in LiDAR. c68,
S1, S2, and S4 received the same already-grounded metric goal; their different
outcomes came from per-tick geometry, observation coverage, trajectory
commitment, and progress recovery below PlanIR. Replacing the conversational backbone, or
having Gemma paraphrase the request for another LLM, would not target the
measured failure.

The timing boundary is equally concrete. Parcel's navigation lane refreshes at
10 Hz, so each decision is useful for approximately 100 ms. The retained Gemma
PlanIR baseline needs 855.379 ms to first output and 5,657.459 ms to a complete
usable plan at warm median—roughly nine and 57 navigation periods,
respectively. S1's 24.223484 ms, S2's 23.513026 ms, and S4's 26.629506 ms
measured controller p99s
fit inside one period, but all three still need fresh camera/LiDAR and odometry again
on the next period. A language decode therefore cannot be placed in the
synchronous local-navigation loop even when it is semantically excellent.
Variable queueing, token length,
parse failure, and stale world state would otherwise pause obstacle reaction;
fluency supplies no bounded stopping-distance or action-certificate guarantee.

The correct split is consequently:

1. conversation produces user-facing language and bounded social proposals;
2. deliberate planning receives the **original transcript**, trusted task
   state, and bounded semantic observations and emits a long-lived PlanIR goal;
3. the executive owns task revision, interrupt policy, progress, and verified
   completion;
4. a classical or separately evaluated fast navigation policy refreshes a
   timestamped local trajectory at navigation cadence; and
5. an independent collision shield (the frozen V8 shield in these V9
   experiments), controller watchdogs, and Unitree Sport remain authoritative
   over every body command.

A learned navigation model can still be valuable, but it belongs in the fourth
lane as an asynchronous waypoint or short-trajectory proposer with stale-result
rejection—not as the conversational LLM emitting the “next move.” The language
planner may choose the next **semantic skill** at a task event or checkpoint;
it must not choose the next 100 ms body command. Likewise, RL should optimize
the training-only local-policy lane under the unchanged sensor/action/safety
contract. S1 shows why progress-only reward is insufficient: it can buy more
travel without terminal success. S2 sharpens the lesson: one real success and
one fewer liveness failure still do not compensate for aggregate efficiency,
stop-latch, and per-world wandering regressions. S4 adds that "more motion" is
not a useful reward unless route progress, terminal success, and efficiency
improve together. Any learned challenger needs
terminal success, path efficiency, label-independent liveness, collision,
clearance, deadline, and action-certificate gates together.

For model-count ablations, keep the current deterministic router and shared
Gemma modes as the language incumbent until a specialist wins its own frozen
quality/latency gate. FunctionGemma remains a route-selector experiment and
`gpt-oss-20b` remains a planner-only challenger; neither is a remedy for this
local-control failure. The next executable navigation hypothesis should move
one layer upward while retaining the same sensor/action/safety boundary. In the
V8 control, eight training worlds efficiently approach almost exactly the
0.48 m signed-clearance boundary and then latch, while worlds 5007 and 5009
start with `no_path`. The grid planner's hard exclusion keeps the base center
approximately 0.42 m from occupied LiDAR return cells, versus the shield's
approximately 0.80 m normalized base-frame return boundary (approximately
0.48 m signed body clearance).

The pre-execution recommendation is a new content-addressed, config-only
planner/shield-alignment profile derived from the exact V8 package. It keeps a
0.10 m hard map margin so genuinely narrow but hard-safe routes remain
representable, adds a non-lethal 0.48 m comfort margin with weight 8.0, and
enables the already implemented sensor-only `observed_first` reachable-frontier
mode. The comfort band targets shield-incompatible route preference; the
frontier mode is required because a finite soft cost cannot change the hard
connectivity that produces the two startup `no_path` cases. This combined
profile is one predeclared planner contract, not a claim that either subsetting
has independently won. All controller source, final shield, adapter,
evaluator, kinematics, and velocity limits remain byte-identical. It must pass
the same threshold contract used for S2/S4, with V10's exact candidate identity
pinned, plus a synthetic latency preflight before its one training screen;
until then it is an unexecuted hypothesis, not a result.

If that profile fails, the next controller candidate should be a compact,
clean-room version of the repeated BARN-winning classical pattern: global A*,
corner-aware lookahead, footprint-width VFH* valleys scored by route/goal,
clearance and heading history, explicit rotate-settle-translate hysteresis,
clearance/curvature-aware speed scheduling, and bounded Bug-style progress
recovery. Full TEB or MPPI integration has much greater dependency and
reproducibility cost and does not first repair the measured planner/shield
contract. Only a candidate that passes every efficiency, stop-latch,
per-world, safety, provenance, and latency condition should advance to a larger
training screen or be frozen for the single-use development run.

These are deliberately called **native proxies**, never official BARN scores.
The runner uses deterministic planar kinematics, one trial per public world,
and a 0.6 m/s Go2 profile. The official 2026 qualifier used a standardized
Jackal, 270-degree 2D LiDAR, 50 hidden worlds, ten trials per world, Gazebo, and
a 2 m/s maximum. The selected proxy's controller p95 and maximum latency also
show why asynchronous planning and watchdog deadlines remain production gates.
The selected `grid_v1` frozen-PR run measured 16.236 ms controller-step p95 but
a 143.947 ms maximum; its fixed-50 run measured 125.938 ms p95, 129.434 ms p99,
and a 341.434 ms maximum against a 100 ms policy cadence. Cached v3 greatly
reduced those controller costs without fixing success. Success, deadline
behavior, clearance, embodiment transfer, and official eligibility must never
be collapsed into one number.

## Lessons from successful embodied systems

### Cross-system synthesis: what the reported successes actually share

The following results are deliberately not combined into one ranking: their
robots, sensors, task definitions, action spaces, and success criteria differ.
They are useful because the same interface pattern recurs across independently
developed systems.

| System | Primary-source result or claim | Boundary that transfers to Parcel | What must not be inferred |
| --- | --- | --- | --- |
| [SayCan](https://say-can.github.io/) | 84% planning and 74% execution success on its 101-task evaluation | Score semantic usefulness separately from current skill feasibility | A language score is not an executable or safe motor command |
| [Inner Monologue](https://innermonologue.github.io/) | Replanning uses success detectors, scene feedback, and human feedback | Close each skill from observations and feed typed failure/progress back to planning | Model narration is not success evidence |
| [Mobility VLA](https://proceedings.mlr.press/v270/xu25b.html) | In its simulated-office ablation, direct VLM waypoint generation was 0% successful; goal-frame selection plus graph search and an executor reached 90% | Use a large model for semantic target selection, then use a navigation representation and embodiment executor | The proprietary, prior-tour system is not a downloadable Go2 policy |
| [InternVLA-N1](https://github.com/InternRobotics/InternNav) | Author-reported slow reasoning above a greater-than-30-Hz fast trajectory lane | Make semantic updates asynchronous and discard stale proposals | The reported rate does not predict latency on Parcel's hardware |
| [NaVILA](https://github.com/AnjieCheng/NaVILA) | Author-reported 88% overall success on a custom real-Go2 suite | A language/vision model may emit bounded high-level commands while a real-time locomotion policy executes | Custom results do not establish BARN, Habitat, safety, or license suitability |
| [FSR-VLN](https://arxiv.org/abs/2509.13733) | Author-reported 80/87 target-retrieval success; 1.5 s fast retrieval and 5.5 s when slow VLM verification is invoked | Escalate to expensive spatial reasoning only when retrieval confidence or consistency requires it | Its mapped RGB-D/LiDAR office pipeline, GPT-4o use, and retrieval metric do not transfer directly to Parcel |
| [Qwen-RobotNav](https://github.com/QwenLM/Qwen-RobotNav) | Author-reported R2R validation-unseen SR/SPL 72.1/66.6 and a 196 ms Go2 demo call | Keep a compact waypoint contract, task-specific context budget, trajectory summaries, and persistent evidence outside the model | The official repository explicitly says weights will not be released; the demo is not reproducible Parcel evidence |
| [Robix](https://robix-seed.github.io/robix/) | Author-reported 92.5% average task progress with its in-house GR-3 controller across five internal real-robot task families | A shared high-level model can coordinate dialogue, planning, interruption, and progress while a distinct executor owns physical actions | Internal task progress and an unreleased model do not establish Go2, navigation, latency, or safety performance |
| [OneTwoVLA](https://arxiv.org/abs/2505.11917) | Author-reported 87% average success across three long-horizon manipulation tasks, 20 trials per task, versus flat and fixed-interval dual-system baselines | Invoke slow reasoning at subtask completion, failure, ambiguity, or human intervention and reuse the latest admitted plan between events | Its manipulation comparison is not a test of two local text specialists, Parcel's contracts, or quadruped navigation |
| [Gemini Robotics](https://deepmind.google/models/gemini-robotics/) and [Helix 02](https://www.figure.ai/news/helix-02) | Vendor-described reasoning/VLA and semantic/visuomotor/whole-body hierarchies | Give semantic planning, embodied execution, and balance different deadlines and authority | Proprietary demonstrations do not select an open-weight Parcel model |
| [BARN 2026](https://people.cs.gmu.edu/~xiao/papers/barn26_report.pdf) | The organizer reports all top-three physical finalists used classical non-ML navigation stacks | Retain global search, local collision avoidance, speed control, and a final safety mechanism below learned semantics | Jackal parameters, footprints, and scores do not transfer to a Go2 |

The repeated finding is not “use more agents.” It is **use more explicit
contracts**: semantic goals, feasibility, waypoints or skills, observed
completion, and a controller-owned safety envelope. Model count is secondary.
This also explains why a planning specialist can be useful without making it a
preprocessor for conversation, and why a conversational model can reply while
having no authority to modify an active trajectory.

### The strongest unified-model evidence still supports split authority

Robix is the closest published answer to the user's exact question. ByteDance
Seed describes a single high-level VLM that consumes camera observations and
utterances, produces both verbal responses and atomic action requests, monitors
task status, handles interruptions, and replans. The official project page
reports 92.5% average task progress when paired with the in-house GR-3
low-level controller across five internal real-robot task families. This is
credible architecture evidence that conversation and planning can share a
cognitive model and context. It is not a reproducible model-selection result:
the official page links a paper and demonstrations but no checkpoint or code,
the tasks are manipulation/transport rather than Go2 navigation, and task
progress is not Parcel's task-success or safety metric.

OneTwoVLA supplies a narrower controlled comparison. It trains one model to
emit a beginning-of-reasoning or beginning-of-action token. Reasoning is
refreshed at events such as subtask completion, detected error, or human input;
otherwise the action lane conditions on the most recent reasoning. The authors
report 87% average success over three long-horizon manipulation tasks, with 20
trials per task, and report improvements over both a flat policy and a
Gemini-2.5-Pro-plus-policy baseline that reasoned at fixed intervals. This is
evidence against **always** invoking a remote slow planner and for keeping
reasoning synchronized with execution. It is not evidence against Parcel's
separate schemas, executive, shield, or Unitree controller: the comparison did
not hold Parcel's models, local serving, quadruped embodiment, sensors, or
safety contract constant.

Parcel should copy the trigger pattern without copying the actuator topology.
Request or refresh PlanIR when a new deliberative task arrives, an admitted
step completes, a target or scene materially changes, progress reports
`blocked`/`target_lost`, or the owner corrects the task. Reuse the admitted plan
between those events. Do not call a language planner on every 100 ms navigation
tick, and do not let a model decide that a safety-critical action succeeded.
This is compatible with either shared Gemma weights or a later specialist:
the executive owns the trigger and the trust boundary in both cases.

### Language models should choose skills, not impersonate a controller

[SayCan](https://say-can.github.io/) combines an LLM's estimate of how useful a
skill is with a learned estimate of whether that skill is currently executable.
The project reports 84% planning success and 74% execution success across its
101-task evaluation. The transferable lesson is the multiplication of semantic
relevance by grounded affordance—not the particular robot or language model.

For Parcel, `NavigateTo(sidewalk)` should be selected only if perception has a
fresh sidewalk candidate, a collision-free route is plausible, and the base is
available. A fluent plan that refers to a nonexistent storefront must score
below `Search(storefront)` or `AskClarification`.

[Inner Monologue](https://innermonologue.github.io/) feeds structured success
detection, scene descriptions, and human feedback back into the language
planner. This is directly applicable to long-lived dog tasks. The planner needs
facts such as `target_lost`, `blocked`, `owner_moved`, or `battery_changed`, not
an assumption that its first plan is still valid.

Two 2026 studies sharpen the same boundary from opposite directions. The
preprint [A Modern System Recipe for Situated Embodied Human-Robot
Conversation](https://arxiv.org/abs/2602.04157) couples a real-time multimodal
dialogue manager to typed gaze and active-perception tools. Across six
home-style scenarios, its four variants averaged 4.65/5 on conversation
quality, but individual tool decisions still showed precision/recall gaps: for
example, `look_for` was precise but missed some needed calls, while
`look_at_person` was recalled reliably but over-triggered. That supports a
low-latency social lane with bounded attention tools and its own human-facing
evaluation; it does not establish that the same model should plan base motion.
Conversely, [From Language to Action](https://arxiv.org/abs/2603.03148) placed
an agentic LLM above high-level perception, navigation, grasp, and placement
tools in a simplified simulated household. The authors observed useful
planning and adaptation, but also hallucinated task success and failures to
complete sequential instructions. This is direct evidence for Parcel's rule
that only controller/perception feedback can close an action, checkpoint, or
task; an LLM's narration is never completion evidence. Both are early
preprints with small, non-Go2 evaluations, so they inform interfaces rather
than model selection or production readiness.

Google's [SayTap
announcement](https://research.google/blog/saytap-language-to-quadrupedal-locomotion/)
and [paper](https://arxiv.org/abs/2306.07580) provide a narrower quadruped
precedent. GPT-4 maps language to one of five bounded longitudinal velocities
plus a binary `4 x T` foot-contact template; a separately trained 50 Hz
reinforcement-learning controller consumes that template and proprioception and
produces Unitree A1 joint-position targets. The pattern interface is useful
evidence for expressive gait or gesture requests, not for general navigation,
obstacle avoidance, or letting a text model own joints or torque. Parcel may
select a reviewed gesture/contact-pattern skill, but a Go2-specific controller
and its safety envelope must remain the only low-level authority.

### Slow reasoning belongs above fast embodied execution

[PaLM-E](https://palm-e.github.io/) demonstrated that embodied observations can
be interleaved with language tokens and used to produce textual substeps.
[RT-2](https://robotics-transformer2.github.io/) went further by representing
robot actions as tokens in a vision-language-action model. Both are important
research results, but their manipulation-oriented action spaces are not a
reason to have Gemma emit Go2 joint targets.

Google's proprietary [Gemini Robotics
1.5](https://deepmind.google/blog/gemini-robotics-15-brings-ai-agents-into-the-physical-world/)
describes an explicit two-model organization: an embodied-reasoning model uses
tools and constructs multi-step plans, while a VLA model performs the physical
steps. Gemini Robotics-ER 1.6 introduced task planning, success detection, and
native tool calls. Google's current proprietary [Gemini Robotics ER
2](https://deepmind.google/models/gemini-robotics/embodied-reasoning/) page
describes a high-level model that chats, plans multi-step tasks, tracks success,
can plan concurrently with execution, and hands motor execution to a lower-level
VLA. These are vendor-reported architecture claims, not reproducible Parcel
candidates, but their interfaces support Parcel's implemented
planner/executive split.
Google also describes layered safety in the original [Gemini Robotics
announcement](https://deepmind.google/blog/gemini-robotics-brings-ai-into-the-physical-world/).

Figure's proprietary [Helix 02](https://www.figure.ai/news/helix-02) is another
architecture data point. Figure describes S2 for semantic goals and sequencing,
S1 at 200 Hz for visuomotor joint targets, and S0 at 1 kHz for balance and
contact. The reported capabilities cannot be reproduced from public weights,
but the timescale separation is exactly why conversation inference should not
sit in Parcel's 50 Hz control loop.

[Mobility VLA's PMLR paper](https://proceedings.mlr.press/v270/xu25b.html)
provides a particularly clean ablation of this boundary. A proprietary Gemini
1.5 Pro call selects one goal frame from a previously recorded tour; camera
localization, an offline topological graph, Dijkstra search, and a separate
embodiment executor then perform navigation. In the paper's simulated-office
ablation, asking the VLM to emit direct waypoints achieved 0% success and
25.90 +/- 8.36 s per step, while goal-frame selection plus the topological
policy achieved 90% success, SPL 0.84, and 0.19 +/- 0.047 s per low-level step.
The latter excludes a one-time 10--30 s goal-selection call. Because this
system requires a prior tour, cannot explore, and uses a proprietary VLM, it is
architecture evidence rather than a Parcel checkpoint. It still strongly
supports using language for semantic goal selection and a grounded navigation
system for repeated motion.

### Dual-system navigation is particularly relevant

[LM-Nav](https://proceedings.mlr.press/v205/shah23b/shah23b.pdf) is useful
evidence for modularity and for its limits. The authors combine language
landmark extraction, visual-language grounding, a topological graph, and a
learned visual navigation policy; they report 85% successful walks over 20
instructions and one human disengagement over 6.4 km. They also identify the
loss caused by reducing a complete instruction to landmarks: verbs, spatial
relations, and other task cues disappear. Parcel should copy the specialist
decomposition but not that bottleneck. An intent frame or landmark list is an
index beside the exact transcript, never a replacement for it.

[InternNav](https://github.com/InternRobotics/InternNav) and its
[InternVLA-N1 paper](https://internrobotics.github.io/internvla-n1.github.io/static/pdfs/InternVLA_N1.pdf)
implement an asynchronous slow/fast split for navigation. System 2 reasons
about instructions and trajectories while System 1 generates short
trajectories at a higher rate. The authors report R2R SR/SPL of 64.3/58.5,
physical-controller evaluation SR/SPL of 51.6/42.49, planning beyond 150 m,
and an optimized fast lane above 30 Hz, but those measurements are on
their models, dependencies, sensors, and hardware. They do not predict Parcel
latency. The transferable result is an asynchronous contract in which a stale
or slow semantic update cannot stall the reactive navigation loop.

[NaVILA](https://navila-bot.github.io/) is even closer in embodiment. It maps
language and images to high-level navigation commands, then uses a real-time
locomotion policy for obstacle-aware execution on a Unitree Go2. Its
[repository](https://github.com/AnjieCheng/NaVILA) and
[checkpoint](https://huggingface.co/a8cheng/navila-llama3-8b-8f) are public.
The authors report 88% overall and 75% complex-instruction success on their
real-Go2 suite, plus Isaac Go2 SR/SPL of 50.2/45.5. These are author-measured
task-specific results, not BARN, Habitat, or Parcel scores.
However, the checkpoint card does not declare a license, its Llama-derived
weights require their underlying terms to be traced, and its software stack is
old enough to make integration a research project. It is a valuable reference
and offline challenger, not a production dependency yet.

[Robostral Navigate's official
announcement](https://mistral.ai/news/robostral-navigate/) describes an 8B VLM
that consumes an instruction plus monocular RGB history and points to an
image-space waypoint/orientation, with a local-displacement form when the goal
is out of view. A separate approximately 121M-parameter diffusion policy turns
the waypoint into a short action trajectory, and a platform controller remains
below that. Mistral reported 76.6% success on R2R-CE validation-unseen in the
announcement; the later [arXiv v2 paper](https://arxiv.org/abs/2607.20785)
reports 77.4% and SPL 74.2, so those versioned author results must not be mixed.
The announcement's earlier marketing text separately says online RL improved
success by 3.2%; it does not expose that statement as the paper's
validation-unseen ablation. The later paper's explicit R2R-CE unseen result is
73.40% to 77.43%, or **+4.03 percentage points**, and is the quantitative result
used here.
Its episode prefix-tree packing reduces **training tokens** 22x; it is not a
22x inference or latency result. No public checkpoint is linked from the
official sources as of the evidence cut-off, making this architecture evidence
for a semantic-waypoint/local-policy split rather than a downloadable Parcel
policy.

[FSR-VLN](https://arxiv.org/abs/2509.13733) adds a useful conditional-compute
result. It builds a floor/room/view/object scene graph from posed RGB-D and
LiDAR data, uses inexpensive embedding retrieval first, and invokes slower VLM
verification only for ambiguous candidates. Across the authors' 87 office
instructions, the full system retrieved 80 targets; they report 1.5 seconds for
the fast path and 5.5 seconds when slow reasoning runs. This supports an
**escalation policy**, not an always-serial chain: Parcel should first try
deterministic skills and cached semantic evidence, and invoke the planner or a
visual verifier only when the task, uncertainty, or recovery state requires
it. FSR-VLN uses a preconstructed pose-rich map, RGB-D, and GPT-4o, so it is
neither sensor-contract-equivalent nor an open-weight policy for Parcel.

[Nav-R1](https://github.com/AIGeeksGroup/Nav-R1) similarly reports a
“Fast-in-Slow” split and more than 8% average improvement across the authors'
reasoning/navigation evaluations. Its public repository and model link make it
worth tracking, but not adopting: the repository does not state code license
terms, the linked model card contains no model documentation, and the published
training recipe calls for four to eight GPUs. Treat the paper as supporting
fast/slow interfaces; do not download it as a presumed 32 GB desktop upgrade.

[VAMOS](https://vamos-vla.github.io/) offers a public but noncommercial
comparison. Its PaliGemma 2 3B high-level planner proposes multiple pixel-space
paths, then a small embodiment-specific affordance model trained in simulation
re-ranks them from elevation, position, and heading before a separate controller
executes the choice. The authors report 90% average success on their custom
six-course, 30-trial real-world suite versus 67% for ViPlanner and 53% for a
modular stack; these are not BARN or another standardized benchmark. The
[repository](https://github.com/vamos-vla/vamos) and
[checkpoint](https://huggingface.co/mateoguaman/vamos) are public, but the
checkpoint is restricted to noncommercial use by its training-data terms. The
released affordance models and evaluations cover Spot and UW Hound, not Go2.
Parcel would have to train and validate a **Go2-specific** affordance model with
its camera/depth-elevation/projection and controller contract. A Jackal-specific
BARN behavior is never an acceptable imitation target for that adapter.

The official [Qwen-RobotNav](https://github.com/QwenLM/Qwen-RobotNav)
repository shows a current alternative: a Qwen3-VL-based model predicts eight
`(x, y, theta)` waypoints,
with a higher-level planner decomposing long tasks and maintaining trajectory
summaries and evidence memory. The project reports R2R VLN-CE
validation-unseen SR/SPL of 72.1/66.6 for an 8B configuration and a
vendor-reported zero-shot Go2 deployment at 196 ms per inference on Jetson
Thor. These are official project claims, not Parcel measurements. Crucially,
the repository
says there are no plans to release weights, so Parcel can learn from its
waypoint contract and memory design but cannot download the reported policy.

### BARN 2026's top physical systems were hybrid/classical

The [2026 BARN challenge](https://people.cs.gmu.edu/~xiao/Research/BARN_Challenge/BARN_Challenge26.html)
tests tight-space, collision-free navigation rather than language
understanding. Its [official report](https://people.cs.gmu.edu/~xiao/papers/barn26_report.pdf)
describes the winning stack as A* global planning with corner-aware lookahead,
VFH* local navigation, fuzzy speed control, and a safety barrier. The runner-up
combined A*, signed-distance-field waypoint correction, and TEB; another strong
entry used global planning and nonlinear model-predictive control.

This is a warning against replacing the navigation stack with an LLM solely to
improve semantic behavior. Learned models can improve target grounding,
route/waypoint proposals, and recovery selection. LiDAR mapping, global search,
local collision avoidance, and hard velocity limits remain the dependable
execution substrate.

#### Reproducibility audit of the 2026 physical top-three stacks

The official physical result was unusually strong but embodiment-specific:
IN2BOT, EW-Glab, and Team Robo entered hardware evaluation with simulation
scores of 0.4975, 0.4880, and 0.4515, then completed 7/9, 5/9, and 3/9 counted
physical trials, respectively. Team Robo was not third in the simulation
ranking; KKato held that position. The
[organizer report](https://people.cs.gmu.edu/~xiao/papers/barn26_report.pdf)
also says all three used classical, non-ML stacks. These results were obtained
on a differential-drive Jackal with a 270-degree planar LiDAR, not a Go2, and
do not establish transfer to Parcel.

| Official system | Primary-source mechanism | Reproduction and Parcel consequence |
| --- | --- | --- |
| IN2BOT | A* supplies long-horizon guidance; a corner-aware target shifts outward before turns; VFH* selects a LiDAR valley; fuzzy velocity control slows for frontal obstacles and large turn angles; a final safety barrier can suppress translation. | The organizer-linked [code snapshot](https://github.com/royalbegger/AAA/tree/0d45a1213e260bc6c32d10d57cd2e871e761c343) is MIT-licensed, but its active [VFH caller](https://github.com/royalbegger/AAA/blob/0d45a1213e260bc6c32d10d57cd2e871e761c343/local_planner/scripts/VFHtest.py) passes incompatible argument counts to several functions in [its utilities](https://github.com/royalbegger/AAA/blob/0d45a1213e260bc6c32d10d57cd2e871e761c343/local_planner/src/navigation_pkg/navigation_utils.py); the checked-in deeper VFH* search and safety-bubble block are commented, and `alpha = 1.0` removes nominal heading smoothing. Learn from the reported decomposition, but do not treat this revision as a runnable or drop-in baseline. |
| EW-Glab | A* waypoints are moved toward greater signed-distance-field clearance by a bounded line climb, then supplied as attraction points to TEB. | The pinned MIT [TEB source](https://github.com/aajin126/the-barn-challenge/blob/98d40a864b41183d22d2f9e138db28688398b55d/teb_local_planner/src/teb_local_planner_ros.cpp) implements the custom via-point path, and the [submitted parameters](https://github.com/aajin126/the-barn-challenge/blob/98d40a864b41183d22d2f9e138db28688398b55d/jackal_helper/configs/params/param_ours/teb_local_planner_params.yaml) use a 20 Hz, non-holonomic, forward-only Jackal configuration. Clearance-biased waypoints are transferable as a hypothesis; TEB parameters and footprint are not. Recomputing a full local distance field on Parcel's control path needs a measured deadline test. |
| Team Robo | Navfn supplies the global path; ACADOS NMPC tracks pose and wheel-speed state over a 2-second, 20-stage horizon while constraining two nearest static and up to ten tracked dynamic obstacles, with reverse as an emergency maneuver. | The MIT [submission wrapper](https://github.com/Team-Robo/the-barn-challenge-mlda/blob/8075e29a7041607d0fe6542ae74a41e4a27cdd97/Singularity_melodic.def) fetches important dependencies without immutable revisions. Its referenced [NMPC core](https://github.com/Team-Robo/mode-switching-mpc-2026/blob/1fb30ca808929c76eb2a05f4a11b611b87bf31f7/script/generate_acados_solver.py) has the documented horizon and SQP-RTI/HPIPM solver, but that core revision exposes no license file. Its differential-wheel state/control model and blind-zone reversal cannot be copied into the Go2 body-twist/Sport-controller boundary; licensing and dependency pinning also precede reuse. |

The official physical computer was an Intel i3 with 16 GB RAM and no GPU,
which supports a CPU-first classical navigation strategy. It does **not** prove
that any audited implementation meets Parcel's 100 ms control deadline, and the
report notes that almost every cold physical trial failed. Robustness still
requires disjoint validation rather than winner-parameter imitation.

The cross-year pattern is more informative than one winner. The official
[BARN 2025 report](https://people.cs.gmu.edu/~xxiao2/papers/barn25_report.pdf)
describes the physical winner's S3-FISVFH controller as another VFH-plus-fuzzy
speed stack. The [BARN 2023 report](https://cs.gmu.edu/~xiao/papers/barn23_report_w_references.pdf)
describes KUL+FM's 9/9 physical result using adaptive constant-curvature
free-space motion tubes; its [MIT-licensed implementation](https://github.com/romulortr/barn-kul-fm)
is a better reproducibility reference for bounded free-space geometry than the
broken organizer-linked 2026 snapshot. These systems differ in details, but
both first construct feasible local motion from LiDAR and only then choose
speed. That ordering directly addresses Parcel's current failure, where the
tracker repeatedly proposes a direction that the downstream shield cannot
admit.

The learned counterexample does not overturn that lesson. The 2024 LiCS-KI
[paper](https://arxiv.org/abs/2406.14947) and
[repository](https://github.com/damanikjosh/the-barn-challenge) publish a small
Transformer policy trained by behavior cloning a successful free-space
expert. Its interface—720 LiDAR rays plus a local goal to linear/angular
velocity—is adapter-plausible and CPU-oriented. It is a credible **shadow**
candidate after a deterministic expert exists, not the first production
choice: checkpoint provenance and safe deserialization still require review,
its Jackal action distribution is not a Go2 body-twist contract, and imitation
does not provide the independent clearance certificate. Parcel should first
build and validate the deterministic planner/VFH or motion-tube expert, then
train a small local proposer on randomized Parcel trajectories and keep the
unchanged shield and deterministic fallback authoritative.

#### Predeclared v5 hypothesis: safe-valley micro-advance

This was a **Parcel experiment hypothesis**, inspired by the reported IN2BOT
VFH decomposition; it was not an IN2BOT port and no transfer result was
assumed. The predeclared behavior was: when
cached v3 repeatedly returns `partial`/`no_path`, use only the fresh current
LiDAR scan to form a small polar histogram, extract passable valleys, and rank
them by goal alignment, previous-heading hysteresis, and minimum local
clearance. Rotate to the selected valley first, advance at most 0.3--0.5 m (or
the smaller clearance-limited distance) through a fully observed swept
corridor, stop, require a new scan, and replan. Do not reverse or use lateral
velocity in this recovery.

This specifically targets the observed 26 watchdog stops and two timeouts:
the failing controller mostly rotates, and six failures never translate even
when the evaluator-private clearance diagnostic is open. A bounded,
sensor-valid translation may expose the new scan that the observed-only local
follower needs, whereas detour v4's goal-regression frontier rescued no
episodes. That causal account is a hypothesis, not evidence of a gain.

- **Sensors and action contract:** use calibrated, timestamped LiDAR plus
  odometry only; camera remains available to other Parcel skills, and neither
  map truth nor evaluator clearance enters policy input. Emit only `vx` and
  `vyaw` through `MidLevelCommand`, the collision shield, and Unitree Sport.
  Validate the Go2 swept body envelope; Jackal wheel dynamics, footprint, and
  2 m/s limits do not apply. Planar LiDAR also cannot certify footholds or
  terrain, so hardware promotion still needs the existing camera/depth
  traversability gate.
- **Dependencies:** pin and checksum the official
  [BARN generator](https://github.com/dperille/jackal-map-creation/tree/295ca5cc7b9b0ecea93013f0c49c5a1ca4352151) and declare
  generator seeds/world hashes before a run; retain Parcel's existing scan
  freshness, odometry, rolling grid, command arbiter, collision shield, and
  Sport adapter. Review the generator repository's absent license before
  redistribution. No LLM, RL policy, GPU, or evaluator modification is needed.
- **Disjoint evidence:** generate a new public-style development corpus rather
  than reuse any consumed ID or inspect the 20-world v4 sealed confirmation
  split. Predeclare a separate generated confirmation corpus and run it once
  only if the development gate passes. Results remain native proxies, never
  official BARN scores.
- **CPU and safety gates:** polar binning is linear in LiDAR beams plus sectors
  and was treated as CPU-plausible before measurement. The frozen gate required
  the branch to be exercised,
  at least two paired success gains with zero success regressions, positive
  metric delta, zero collisions, no timeout increase, minimum signed clearance
  at least 0.075 m with no floor regression greater than 0.005 m, controller
  p99 at most 100 ms and challenger/reference p99 ratio at most 1.2. Reject
  stale scans, unknown swept corridors, reverse/lateral commands, and exhausted
  bounded attempts; every rejection ends in a safe stop.

#### Safe-valley v5 development result: useful signal, rejected candidate

The proposal above was implemented only as deployment-disabled
`grid_safe_valley_v5`. Before either policy ran, Parcel generated and hashed a
new 30-world public-style corpus under namespaced IDs 1000--1029 from the
pinned generator commit. The manifest froze every world/path hash, the
unchanged cached-v3 reference, candidate configuration, relevant harness and
policy-source hashes, paired protocol, and gates. IDs 1030--1049 remain only an
unexecuted deterministic confirmation recipe: their assets were not generated,
opened, or evaluated. This evidence is a native CPU proxy, not an official
Gazebo or leaderboard result.

| Frozen development result | cached frontier v3 | safe valley v5 | Candidate minus reference |
| --- | ---: | ---: | ---: |
| Success | 12/30 (0.4000) | 13/30 (0.4333) | one gain, zero regressions |
| Navigation metric | 0.092208 | 0.099212 | +0.007004 |
| Collisions | 0 | 0 | tie |
| Timeouts | 0 | 2 | +0.0667 rate |
| Global signed-clearance floor | 0.095222 m | 0.072034 m | -0.023188 m |
| Controller p99 | 64.274 ms | 65.077 ms | 1.0125x |

The recovery genuinely translated for 1,432 control ticks and rescued one
episode, so the hypothesis contains a useful causal signal. It nevertheless
failed four predeclared gates: at least two successes were required, timeout
rate could not increase, clearance had to remain at least 0.075 m, and its
floor could regress by no more than 0.005 m. Passing the metric, collision, and
latency gates cannot compensate for those failures. The challenger is rejected,
confirmation is unauthorized, and the selected deployment behavior is
unchanged. The immutable evidence and exact hashes are under
`evals/external/development/barn_safe_valley_v5/`.

#### Safe-valley guard v6: clearance hypothesis isolated and rejected

V6 tested only the first follow-up above on a newly generated, frozen 30-world
development corpus (namespaced IDs 2000--2029). It added exactly
`resolution/sqrt(2) = 0.0707106781 m` to raw-LiDAR valley admission and
swept-body certification; the paired reference was byte-identical v5 on the
same assets and seeds. V6 remained deployment-disabled. Confirmation IDs
2030--2049 were not generated, opened, evaluated, or authorized.

One initial invocation failed closed at metadata preflight because the generic
comparison harness rejected an experimental reference specification. It ran
zero episodes and emitted no metric. The narrow harness-only repair was frozen
under a new manifest rather than overwriting that evidence; run02 was the only
policy execution.

| Fresh-corpus development result | v5 reference | safe-valley guard v6 | Candidate effect |
| --- | ---: | ---: | ---: |
| Success | 15/30 (0.5000) | 15/30 (0.5000) | no paired gain/regression |
| Navigation metric | 0.1202936293 | 0.1202936293 | tie |
| Collisions | 0 | 0 | tie |
| Timeouts | 4/30 | 4/30 | unchanged, but nonzero |
| Global signed-clearance floor | 0.0832198928 m | 0.0832198928 m | tie; above 0.075 m gate |
| Mean episode-minimum clearance | reference | reference +0.0103934019 m | improvement across affected pairs |
| Controller p99 | 83.354964 ms | 84.3841 ms | 1.01235x |

The guard executed 964 advances and deterministically changed ten of 30 paired
episodes, so the branch was exercised. Eleven of twelve predeclared gates
passed. The decisive `zero_candidate_timeout_rate` gate failed, and mean
maximum goal progress fell by 0.0644946875 m. The candidate is therefore
rejected, not promoted because its clearance was better on average. Repaired
manifest SHA-256 is
`821e70935c447007614e1a6b939c9a1d0769443cebdf7f5028e4bdcf348e13a5`;
summary SHA-256 is
`0453abc5e900c5c8f76453a0e30661eb63e0d10ddd4d2ba969db889ce344ebb9`;
full report SHA-256 is
`6d2e31366e1d8318ad3bba37aea834fcbb96fab4247568421d2ba51433ebe319`.

This falsifies extra clearance padding as a sufficient liveness fix. Do not
tune either v5 corpus after observing it. A future experiment should isolate
the second hypothesis on another frozen development corpus: after a bounded
number of unsuccessful advances, require a timestamp-new scan sweep and replan
or safe-stop, without reverse, lateral motion, weaker inflation, or extended
episode time. Calibrated ROS transport later removed the independent startup
`policy_no_translation` cause. The resulting real trial still timed out, but a
sensor-faithful post-run replay now strongly attributes that later stall to the
legacy 0.8 m collision-brake profile suppressing forward commands, not to the
same no-path recovery. The bounded scan-sweep/replan experiment remains useful
for the distinct native failures, while the ROS failure calls for a separately
frozen, footprint-aware collision-policy ablation. Neither finding authorizes
reuse of world 0 or the consumed native corpora for tuning.

Only after a recovery ablation clears both liveness and safety should Parcel
compare a clearance-biased global path plus TEB/MPPI-style local trajectory
optimizer—the common structure suggested by EW-Glab, Team Robo, and upstream
Nav2—behind the same Go2 body-twist and collision-shield interface. That is a
more credible path to repeated gains than increasing the micro-advance length
or weakening the clearance gate.

Ranked static BARN does not evaluate moving crowds or social compliance. Urban
promotion therefore needs a separately frozen dynamic-pedestrian gate, using
held-out MetaUrban layouts/densities first and an optional, separately reported
DynaBARN protocol where reproducible. Metrics must include dynamic collision,
personal-space intrusion, time-to-collision, progress, and jerk; a static BARN
gain cannot stand in for that evidence. The [BARN 2026 official
report](https://people.cs.gmu.edu/~xiao/papers/barn26_report.pdf) lists optional
DynaBARN results in parentheses but states that the static score determined the
ranking; it is not evidence of a ranked dynamic-physical track.

### Generalist manipulation VLAs are not Go2 navigation models

Several strong open projects are valuable as design references but currently
have the wrong embodiment and action distribution:

- [OpenVLA](https://github.com/openvla/openvla) is a 7B manipulation VLA trained
  on Open X-Embodiment data. Its code is MIT licensed, while its released model
  inherits Llama 2 terms. It does not provide a Go2 navigation controller.
- [openpi](https://github.com/Physical-Intelligence/openpi) publishes π0,
  π0-FAST, and π0.5 code and checkpoints. The repository says inference needs
  more than 8 GB VRAM, LoRA fine-tuning more than 22.5 GB, and full tuning more
  than 70 GB. Its supported examples are manipulation embodiments. The useful
  lesson from the [π0.5 paper](https://www.physicalintelligence.company/download/pi05.pdf)
  is to predict a semantic subtask before a low-level action chunk; the useful
  lesson from [FAST](https://www.physicalintelligence.company/download/fast.pdf)
  is efficient action-chunk representation. Neither checkpoint maps directly
  to Go2 body motion.
- NVIDIA's [Isaac GR00T](https://github.com/NVIDIA/Isaac-GR00T) combines a VLM
  backbone with a diffusion action transformer. Current public models target
  humanoid/manipulation skills. NVIDIA's [hardware
  guide](https://github.com/NVIDIA/Isaac-GR00T/blob/main/getting_started/hardware_recommendation.md)
  recommends 48 GB-class GPUs for starter fine-tuning; Parcel's 32 GB card is
  below that recommendation. There is no released Go2 navigator to justify a
  large download.
- [MiniVLA](https://github.com/Stanford-ILIAD/openvla-mini),
  [SmolVLA](https://huggingface.co/blog/smolvla), and
  [X-VLA](https://github.com/2toinf/X-VLA) demonstrate smaller backbones,
  action chunks, asynchronous inference, and cross-embodiment adapters. Their
  public results are primarily manipulation. They inform implementation
  patterns, not a replacement Go2 policy.
- [Qwen-VLA](https://github.com/QwenLM/Qwen-VLA) reports that one
  Qwen3.5-4B backbone plus a 1.15B flow-matching action decoder can share
  manipulation, navigation, and trajectory-prediction training through
  embodiment-aware prompts. The paper reports R2R/RxR and manipulation
  results, but the official repository currently contains project information,
  not runnable code or model weights, and does not establish a Go2 action
  contract. It is evidence that joint pretraining can help a generalist; it is
  not evidence that a text embodiment description safely replaces Parcel's
  measured adapter, controller, or safety validation.

The production rule should be simple: do not adopt a model because it is a
prominent VLA; adopt it only when its observation contract, action contract,
license, latency, and evaluation task match Parcel.

## One model or multiple brains?

| Design | Advantages | Main failure mode | Parcel decision |
| --- | --- | --- | --- |
| One unconstrained LLM for talk and action | Simple prototype; one semantic context | Slow action loop, hallucinated control, conversation can interrupt safety-critical work | Reject |
| Intent LLM summarizes, planning LLM sees only summary | Specialized prompts and independent upgrades | Information loss, serial latency, compounded errors, conflicting personalities | Reject |
| Small router preserves transcript, one backbone has fast and deliberate modes | Low memory duplication, one model-family baseline, measurable routing, graceful fallback | Shared model may be weaker than a specialist on hard plans; persona consistency is unverified | Adopt now |
| Small router plus specialized conversation and planning models | Task-specific model selection; independent tuning | More VRAM/RAM, scheduling and consistency complexity | A/B after baseline |
| One VLA from camera directly to body or joints | Potential end-to-end learning | Weak inspectability, embodiment mismatch, large data need, bypassed LiDAR/safety | Research only |

The subtle but important distinction is that “intent” is not a lossy rewrite.
The router produces metadata alongside the exact transcript. A later planner
receives both.

Robix and OneTwoVLA prevent an equally simplistic reading in the other
direction: a role split is not automatically a weight split. Robix joins
conversation and planning in one high-level model but preserves a separate
physical executor. OneTwoVLA shares reasoning and action weights and adaptively
predicts when to reason from heuristically labeled critical intervals. Those results make the current
shared-Gemma baseline more defensible, while leaving the specialist ablation
necessary. They do not validate a single unconstrained model, and OneTwoVLA's
fixed-interval cloud baseline is not equivalent to two admitted local Parcel
services.

For the user's concrete proposal, the answer is therefore **not** “Gemma
extracts intent, then another LLM plans from Gemma's text.” The recommended
call graph is:

```text
final transcript + transcript hash
  -> deterministic router (later: separately admitted FunctionGemma route selector)
       -> conversation_only: conversational model
       -> direct_skill: deterministic binding + fresh-state admission
       -> deliberative_plan: planner receives the original transcript,
                             IntentFrame, task state, and sensor-derived facts
       -> clarify_or_abstain: no motion
```

The planner may eventually be a different model, but it is a **parallel role
boundary**, not a serial paraphrase boundary. Route metadata is useful for
scheduling, schemas, and deadlines; it is not a compressed substitute for the
user's words. The deterministic router remains preferable while its domain is
small because it is fast, inspectable, and conservative. A tuned FunctionGemma
is admitted only as a proposal lane if it improves held-out intent coverage
without increasing unsafe motion routes or tail latency. It may choose exactly
one bounded route—`conversation_only`, `direct_skill`, `deliberative_plan`, or
`clarify_or_abstain`—but it does not receive motor-skill tools. Deterministic
code still owns final-ASR gating, the immutable turn ID, transcript reference
and hash, router version, emergency/safety overrides, and direct-skill argument
binding. A model-authored confidence field is not evidence of calibration.

To reduce latency, routing should remove work rather than add a mandatory model
hop. Conversation-only turns never call the planner. Reviewed direct skills
never call either large planning mode. A deliberative turn enqueues the planner
immediately after routing; if an early response is needed, the voice lane may
emit a deterministic non-committal acknowledgment such as “Let me check,” while
the accepted-action acknowledgment waits for validation. On one GPU, this
avoids invoking two long decodes for the same routed turn; it does not prevent
inter-turn queueing under the current global lock. Two independently admitted
model processes could run conversation and planning concurrently only after Parcel implements
priority scheduling, cancellation, and bounded queues and admits both exact
processes together under the GPU reserve. Both results must remain joined by
the immutable turn ID and only the executive may commit the action. Measure
first log/audio separately from first valid reasoning and first accepted plan;
otherwise a quick acknowledgment can hide a multi-second planning regression.

This is a serving-topology decision, not a model-count decision. The 2026
[Speculative Interaction Agents](https://arxiv.org/abs/2605.13360) paper
decouples an agent from streaming user and environment I/O and reports
1.3--1.7x speedups for cloud APIs and 1.6--2.2x for two fine-tuned 3B edge
models on tool-calling evaluations. Importantly, it withholds sensitive tools
until confirmation. The authors did not evaluate a physical robot, so those
speedups are not Parcel forecasts. The transferable rule is to speculate on
**compute**, never on motor commitment: partial ASR may warm routing or prepare
a cancellable proposal, but only final ASR, fresh observations, validation,
and executive acceptance may authorize a physical task.

A production preprint from Baidu, [DuCCAE](https://arxiv.org/abs/2603.19248),
reports the complementary architecture at scale: real-time conversation and
long-horizon agentic execution run on separate tracks joined by shared session
state and execution traces. Its deployment and retention/task-completion
figures are vendor-authored digital-assistant evidence, not robotics evidence.
For Parcel it supports replacing the single model-turn lock with priority
queues, task-revision cancellation, and typed shared state; it says nothing
about whether one or two weight files should service those queues.

The evidence does not justify a claim that two serial text LLMs are inherently
better. No reviewed primary source here holds the companion tasks, transcript,
backbone capacity, runtime, and safety contract constant while showing that a
separate conversational LLM followed by a planner LLM beats a shared backbone.
Parcel should keep the deterministic router as the incumbent, optionally test a
fine-tuned FunctionGemma 270M route-function selector, preserve the raw
transcript in every condition, and directly compare shared-Gemma modes with
specialist planner and conversation APIs. Only those paired Parcel results can
answer the split-brain model-count question. Parcel now exposes independent
conversation and planner provider objects and the normal `parcel-panel`
configuration has an optional `planner_model` lane. It defaults to the
conversation provider when that lane is disabled. When enabled, the original
transcript goes directly to the planner, model health is reported per role, and
plan latency is attributed to the provider that served it. This implements a
real provider/configuration ablation without changing routing, transcript
provenance, validation, or motor behavior.

It does **not** yet implement dialogue/planner scheduling isolation. The normal
text and guarded-voice paths hold one `_agent_lock` across the entire
non-E-stop `agent.handle_text*` call, so a 5.66 s median plan decode can block a
new conversational model turn even when its provider is a different endpoint.
The emergency-stop path deliberately bypasses that lock, and perception and
control remain below it. The pinned Gemma launcher also does not explicitly
configure multiple inference slots. Independent deadlines in an API are
therefore not independent service availability: a future scheduler must admit
priority queues, cancellation, server-slot concurrency, per-slot KV growth,
and concurrent p95/p99 latency before the report calls the lanes concurrent. A
specialist lane is absent from the frozen default configuration because neither
measured Ministral challenger cleared the quality gates; it is added only to an
experimental configuration.

The installed Gemma 4 26B-A4B is unnecessarily large if used only as an intent
extractor. It is more useful as the shared dialogue/planning backbone. A
fine-tuned [FunctionGemma](https://ai.google.dev/gemma/docs/functiongemma)
270M model is a plausible future router: Google explicitly positions it for
function calling in compound systems. Its [model
card](https://ai.google.dev/gemma/docs/functiongemma/model_card) also warns that
it is not a dialogue model and should be fine-tuned for the target function
task. The untuned base is not an authority-grade router: Google reports BFCL
Simple 61.6 and Parallel Multiple 29.5, while its Mobile Actions example rises
from 58% base accuracy to 85% after task-specific fine-tuning. The same card's
Samsung S25 Ultra CPU measurement—dynamic-int8, 512-token prefill, 32-token
decode, approximately 0.3 s TTFT, 288 MB model, and 551 MB peak RSS—is useful
edge feasibility evidence, not a Parcel desktop latency result and not proof
that it beats deterministic routing.

Parcel should therefore compare a route-only FunctionGemma against the
deterministic router, train it on Parcel-specific labels, and calibrate
abstention from held-out evidence or token probabilities when the admitted
runtime exposes them. It must fail closed on parse error or uncertainty. It
never authors the trusted provenance fields of `IntentFrame`, never receives a
motor tool, and never directly drives a skill. A `direct_skill` selection is a
route proposal only; reviewed deterministic binding and fresh-state admission
still decide whether anything can execute.

### Implication of the shared-backbone decision

“One shared backbone” does not mean one prompt, one memory, or one trust level.
It means one admitted model profile/artifact services mutually exclusive
requests through two APIs when that profile is active. Short-budget dialogue
cannot emit PlanIR; plan mode cannot emit motor
commands or conversational prose. This yields four near-term advantages:

- one 14.4 GB Q4 weight image rather than co-resident large dialogue and planner
  weights;
- no serial intent-model paraphrase before planning;
- one vocabulary/persona foundation, which may reduce model-family drift or
  contradictory acknowledgments—an unverified Parcel hypothesis; and
- a clean baseline from which specialist value can be measured.

The 14.4 GB figure is a static Q4 weight estimate, not a runtime-residency
promise: every Gemma 4 MoE expert remains loaded and KV cache, compute buffers,
server slots, and other robot workloads are additional. Likewise,
`enable_thinking: false` is a decode request, not proof of zero thought-channel
tokens. Google's Gemma documentation notes that disabled thinking can still
produce an empty thinking block or occasional thought-channel output on these
sizes. Parcel must pin the exact template, parse and discard any thought
channel, and measure total decode rather than only visible response tokens.

The corresponding risks are queue contention, shared failure modes, and a model
that may be pleasant in conversation but mediocre at grounded PlanIR. The
runtime therefore needs admission queues and independent deadlines even while
weights are shared. A long plan call may never block E-stop, control, perception,
or a short system-owned voice alert; conversation during an active plan either
uses an independently scheduled and admitted slot or a deterministic
acknowledgment. The former is a production requirement, not a current runtime
capability.

Split into separate large conversation and planning models only if a paired
frozen experiment demonstrates a material plan/task gain that survives safety
and tail-latency gates. The planner specialist should receive the original
transcript plus `IntentFrame`, never only a summary produced by the conversation
model. A tiny learned router is a separate possible optimization and must beat
the deterministic router on calibrated unsafe-route errors, not merely average
classification accuracy.

There are three valid reasons to activate a second large model: it materially
improves accepted semantic plans, materially reduces complete accepted-plan
latency, or isolates dialogue availability from long planner calls. There are
also three non-reasons: a better generic leaderboard score, a faster first token
with a slower or invalid complete plan, or a model card that advertises tool
calling without passing Parcel's schemas and embodied tasks. `gpt-oss-20b` is
the first prioritized hardware-plausible planner-only challenger because its official
release supports function calling and Structured Outputs and reports that the
native MXFP4 checkpoint can run within 16 GB. It is a general-purpose text
reasoning model, not a robotics or PlanIR specialist. Its exact Parcel runtime,
template, KV/cache size, peak memory, latency, structured-output enforcement,
and task quality remain unmeasured; experiment priority is not evidence that it
beats the installed Gemma baseline or can share the GPU with it.

## Implemented brain architecture and remaining production boundary

The following is the architecture wired into the normal runtime. Dashed future
work is deliberately outside its actuator boundary: a different language model
can replace Gemma and a learned navigator can propose waypoints, but neither
change requires a new motor API.

```text
                         original transcript
                                  |
partial ASR -> turn end -> reflex / IntentFrame router <--- task + safety state
                         /         |          \
                 conversation  direct skill  deliberate task
                       |            |              |
             short-budget LLM  deterministic    PlanIR LLM mode
              AgentDecision    argument binding       |
                       |       + fresh admission       |
                       +------ accepted response -----+
                                      |
                            validator + executive
                             /       |        \
                       task memory  skills  semantic navigator
                                              |
camera frames -> timestamped perception -> target/waypoint proposals
LiDAR + odometry -> map -> global path -> local trajectory -> safety shield
                                                           |
                                                  bounded body velocity
                                                           |
                                              Unitree Sport closed loop

voice lane: ASR / full-duplex front-end <-> dialogue output <-> TTS
             (may overlap safely; never owns the base or posture)
```

### 1. Reflex and routing layer

The reflex path is deterministic for E-stop, `stop`, manual teleoperation, and
a short reviewed command grammar. It does not wait for an LLM.

All other final transcripts produce a bounded frame. A schema-complete example
looks like this (the digest below is illustrative):

```json
{
  "schema_version": 1,
  "turn_id": "turn-42",
  "route": "deliberative_plan",
  "confidence": 0.92,
  "speech_act": "request",
  "affect_evidence": {
    "label": "sad",
    "confidence": 1.0,
    "source": "explicit_transcript"
  },
  "spatial_references": ["the sidewalk"],
  "urgency_cues": ["dangerous"],
  "requires_fresh_scene": true,
  "original_transcript_ref": "turn:turn-42:final",
  "transcript_sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
  "router_version": "deterministic-v1",
  "matched_rule": "compound_physical_request"
}
```

Allowed routes should initially be:

- `conversation_only`;
- `direct_skill`;
- `deliberative_plan`; and
- `clarify_or_abstain`.

The router cannot assign motor priority, choose raw velocities, or declare an
object present. Unreviewed physical language goes to deliberate planning;
partial transcripts route to abstention, and only a final turn may commit an
action. A future learned router must retain the same provenance and conservative
failure behavior.

### 2. Shared conversation and planning backbone

Parcel currently defaults to one admitted shared model profile/artifact, loaded
when that profile is active, with separate system prompts, output schemas,
token budgets, and deadlines. `VoiceAgent` and `RobotRuntime` also accept an
independent planner provider, so a specialist can replace only the plan lane
without first passing through conversational paraphrasing:

- **Short-budget conversation/social mode** answers conversation and may propose
  at most one low-priority allow-listed social action. Reviewed direct skills do
  not use this model. It should default to non-thinking constrained decoding and
  short streaming responses.
- **Plan mode** receives the original transcript, an explicit task-state
  snapshot, timestamped semantic observations, and the skill catalog. It emits
  only `PlanIR`, not user-facing prose or velocity.

Raw velocity and locomotion-backend tools are absent from the model-facing
schema. If a provider emits either name anyway, `VoiceAgent` suppresses the
entire physical proposal and fails closed. Direct catalog skills, status, and
reviewed backend-selection commands bind deterministically before either LLM
and still pass fresh-state and safety admission before execution.

For a simple turn, keeping reply and direct action in one constrained decision
helps semantic consistency. For a complex turn, Parcel derives the spoken
acknowledgment only after fresh-state validation and executive acceptance. It
does not promise motion merely because the model emitted JSON. A future
speculative acknowledgment such as “Let me check” may stream earlier, but it
must be semantically distinct from plan acceptance.

### 3. PlanIR and deterministic executive

A plan needs more than a list of tool names. After trusted context binding and
deterministic contract compilation, an admitted sidewalk task can resemble:

```json
{
  "schema_version": 1,
  "task_id": "parcel-task-8388af242902285fb7292fdc",
  "plan_revision": 1,
  "source_turn_id": "turn-42",
  "goal": {
    "relation": "inside",
    "target": {"kind": "semantic_region", "query": "sidewalk"},
    "tolerance_m": 0.0
  },
  "invariants": [],
  "steps": [
    {
      "id": "step_1",
      "skill": "NavigateTo",
      "arguments": {"directive": "go to the sidewalk"},
      "preconditions": [
        "base_available",
        "camera_fresh",
        "lidar_fresh",
        "target_grounded"
      ],
      "success": {
        "fact": "inside",
        "target": "sidewalk",
        "tolerance_m": null,
        "confidence_min": null
      },
      "timeout_s": 120,
      "max_attempts": 1,
      "recovery": ["safe_stop"],
      "resources": ["base", "attention"],
      "interruptibility": "checkpoint"
    }
  ],
  "requested_interrupt": "at_checkpoint"
}
```

The schema versions every plan, allows only runtime-admitted skills, constrains
arguments, timeouts, retries, recovery, and tolerances, and rejects unknown
fields. The binder owns provenance, task identity/revision, and requested
interrupt authority. Compiler v1 owns step IDs, required and conditional
preconditions, non-navigation success policy, resources, the contract maximum
timeout, one attempt, safe-stop recovery, and minimum interruptibility. This
conservative compiler does not yet express richer retry/replan policy. The
model owns skill order, bounded arguments, and `NavigateTo` success fact/target,
so bad semantic grounding is not silently repaired.

The serialized `invariants` field is advisory: unknown labels fail validation,
but the validator compiles enforceable invariants from the admitted goal,
skills, resources, and perception dependencies. The model can neither omit a
mandatory rule nor weaken policy by reciting a different known rule. For this
sidewalk plan the system adds collision margin, road avoidance,
stale-perception stop, yielding to people, and critical-task interruption
protection. The executive, not the model, assigns effective priority and
cancellation behavior. It owns:

- resource locks for `base`, `posture`, `voice`, and `attention`;
- precondition and perception-freshness checks;
- progress monitoring and terminal success tests;
- retry budgets, recovery transitions, and clarification;
- task checkpointing and interrupt arbitration; and
- an append-only decision trace linking transcript, plan, observations,
  commands, and measured outcome.

Feedback from execution is typed: `succeeded`, `blocked`, `target_lost`,
`perception_stale`, `owner_moved`, `scene_changed`, or `battery_changed`. Do not
feed an unrestricted narration of the entire control log.

### 4. Interrupt policy is a system policy

The intended system-owned priority order is:

1. hardware E-stop, fall, imminent collision, thermal fault;
2. operator manual control;
3. balance recovery and battery-critical safe-stop procedure;
4. explicit user stop or task cancellation;
5. an active navigation/following mission;
6. an explicit gesture or pose request;
7. inferred social reactions and ambient behavior.

The model may request `interrupt_now`, `at_checkpoint`, or `when_idle`; the
executive computes the effective policy. Voice can often overlap base motion. A
chuckle therefore need not cancel following. A bow uses posture and usually the
base, so it waits until the robot is stationary and a task checkpoint permits
it. A joke never cancels a road crossing. An explicit stop always can.

Battery behavior is not an inferred emotion. At a critical threshold, a
deterministic policy should find a safe non-road region if feasible, stop,
release the base, assume a stable pose, and report the condition.

### 5. Separate memories by trust and lifetime

Parcel should maintain:

- **conversation memory**: user preferences, recent dialogue, and persona;
- **task memory**: accepted goal, plan version, current step, and verified
  outcomes;
- **semantic scene memory**: timestamped objects/regions, confidence,
  provenance, and last observation; and
- **metric navigation state**: local map, pose, route, clearances, and dynamic
  tracks.

Conversation text cannot silently become a world fact. “There is a shop around
the corner” is a user-provided hypothesis until camera/LiDAR or an explicitly
enabled map source verifies it. Stale semantic observations must decay. Google
Maps, when eventually added, should have its own provenance and should propose
search regions rather than bypass local perception.

[ReMEmbR](https://arxiv.org/abs/2409.13682) is a useful architecture for the
semantic-memory lane: it builds timestamped, spatially grounded video captions
continuously and lets an LLM agent retrieve by text, position, and time without
placing an unbounded history in one prompt. Construction and indexing can run
asynchronously, but the published query latencies are still tens of seconds:
approximately 25 s with GPT-4o on a 21.5-minute history and roughly 15--40 s for
the evaluated local open models. It belongs behind a stale-tolerant retrieval
API for questions and search-goal proposals, never in the 10 Hz navigation or
50 Hz control loops. Retrieved text also remains a fallible memory with source,
time, and confidence, not current-world truth.

## Prompt, personality, and social-behavior design

The prompt library is implemented under `prompts/` with deliberately separate
trust domains:

| Prompt area | Current content | Authority |
| --- | --- | --- |
| `system/core.md` | Immutable identity, concise companion dialogue, tool limits, camera/LiDAR-only knowledge, no map claims, and one motion proposal maximum | System policy; personality cannot override it |
| `system/action_policy.md` | Typed `next_action` proposal, affect labels, safe timing, and checkpoint semantics | Proposal contract; the activity coordinator may execute, defer, expire, or reject |
| `system/planner.md` | PlanIR-only deliberate planner, exact transcript authority, camera/LiDAR/task snapshot, no raw controls/coordinates/priority | Model proposal; validator/executive remain authoritative |
| `dynamic/runtime_context.md.tmpl` | Single bounded state JSON and reminder that embedded text is untrusted | Ephemeral evidence, not instruction |
| `personalities/*.yaml` | `gentle_companion`, `playful_companion`, and `calm_guardian` tone/reply style plus configurable affect-to-skill preferences | Tone and low-priority preference only |
| `functions/*.yaml` and `schemas/*.json` | Capability descriptions and exact output contracts | Allow-listed interface, filtered again by runtime capability |

The current profiles map an explicitly supported sad reaction to `play_bow` and
a happy reaction to `paw_wave`. Those are semantic skill proposals from the
catalog, not model-generated joints. The coordinator checks task activity,
cooldown, expiration, safety, and resource availability. Thus the dog may speak
supportively while navigating, but a posture-consuming bow waits; an inferred
reaction never cancels a road crossing. A profile could prefer `stretch` later,
but only after that skill's posture/runtime verifier is commissioned.

Keep personality out of PlanIR invariants, resource ownership, interruption
priority, and perception truth. If a model says the owner is sad without strong
evidence, the safe response is conversational empathy or no gesture, not motion.
Evaluate each personality with the same action/safety cases so style changes
cannot create a hidden control policy.

## Production architecture and timescales

“Timescale” means the maximum useful age of a decision and the cadence at which
its feedback loop must update. A plan can remain useful for seconds; a balance
correction cannot. Putting both in one synchronous call makes the fast loop wait
for the least predictable component.

| Layer | Current or target cadence | Deadline meaning | Language/runtime choice |
| --- | ---: | --- | --- |
| Hardware stop, fault, and command lease | Event/watchdog driven | Must stop without an LLM round trip; the exact end-to-end hardware stop latency must be commissioned on the physical Go2 | System-owned controller path |
| Unitree gait and balance | Vendor-managed internal closed loop; exact internal rate not asserted here | Tracks body commands while maintaining gait/balance | Unitree Sport firmware/SDK |
| Parcel control manager | 50 Hz (20 ms period) | Clamp, smooth, refresh, monitor feedback, and fail on stale state/command | Python currently; isolate vendor I/O and any future hard-real-time custom controller |
| Runtime navigation, follow, spatial behavior, and task executive | 10 Hz (100 ms period) | Refresh local intent and react to camera/LiDAR/controller changes; never wait for language inference | Python, with bounded calls and watchdogs |
| Learned short-trajectory proposal | Approximately 5–30 Hz target, asynchronous | A proposal is discarded when stale; the classical/reactive lane continues using the last safe plan | Separate GPU process behind a timestamped waypoint API |
| Intent router | Per final transcript; target under 10 ms warm | A deterministic decision or abstention should be negligible beside model decode | Current deterministic Python; tiny tuned model only after A/B |
| Conversation and PlanIR model | Event driven, typically hundreds of milliseconds to seconds | First useful output, complete decode, validation, and accepted plan are separate deadlines | One loadable shared-Gemma baseline today; specialist providers behind the same interface later. No inference server is assumed continuously active by this report. |
| Speech capture/codec/TTS | Streaming frames in tens of milliseconds; turn events over longer windows | Barge-in and first audio matter, but no audio frame owns motion | Separate service/process; trusted action begins at final transcript |

The current 50 Hz and 10 Hz Python loops are appropriate while Unitree Sport
owns the fast gait/balance controller. A full C++ or Rust rewrite would not make
Gemma faster, improve semantic perception, or fix plan quality. The production
move is process isolation and explicit deadlines:

1. keep the brain, prompt/eval tooling, semantic task executive, and research
   adapters in Python while their interfaces are changing;
2. place Unitree SDK I/O, command leases, stop/watchdog handling, and any future
   custom hard-deadline controller behind a narrow process boundary;
3. use C++ first where the vendor SDK and ROS/Nav2 ecosystem already make it the
   lowest-risk implementation, or Rust where memory safety and available driver
   support are stronger; and
4. exchange bounded timestamped messages rather than sharing model objects or
   mutable task state across processes.

This follows the same systems principle—not the same proprietary implementation—as
[Helix](https://www.figure.ai/news/helix) and [Helix
02](https://www.figure.ai/news/helix-02): slow semantic state updates an
asynchronous interface, while faster embodied and balance layers continue at
their own rates.

## Dynamic-city simulation strategy

No single simulator should be allowed to redefine Parcel's production sensor or
action contract. Each production-faithful simulator adapter should emit camera,
LiDAR, and controller feedback and consume the same bounded body command.
Semantic labels, actor routes, collision truth, and shortest paths should stay
evaluator-only. The current headless PlanIR gate is a deliberately weaker
exception: it exposes idealized geometry-derived semantic tracks to isolate the
planner/controller integration and labels that limitation explicitly.

| Environment | Parcel use | Current decision |
| --- | --- | --- |
| Parcel MuJoCo/headless city | Fast deterministic PR tests for sidewalk/road semantics, lamppost vicinity, owner orbit/follow, scripted pedestrians/cyclists, TTC stops, and failure injection | **Keep as tier 1.** It is implemented and reproducible, but its compact scripted crowd is not evidence of urban generalization. |
| [MetaUrban](https://metadriverse.github.io/metaurban/) | Procedurally composed streets, sidewalks, static objects, pedestrians, vulnerable road users, PointNav, and SocialNav | **Recommended first procedural/social-city integration tier.** Run it out of process in its supported Python/GPU environment, pin assets/code, and implement a real adapter. The current `MetaUrbanNavEnv` is only a scaffold. |
| [URBAN-SIM](https://github.com/metadriverse/urban-sim) | GPU-parallel clean/static/dynamic urban navigation built on procedural MetaUrban layouts | **Separate GPU-RL candidate.** Its repository recommends at least 12 GB VRAM, which this desktop exceeds, but reactive pedestrian agents remain on the project TODO. “Dynamic” therefore does not yet prove sophisticated interactive-human behavior. |
| [S2E / NavBench-GS](https://github.com/VAIL-UCLA/S2E) | Closed-loop visual navigation, released web-pretrained behavior-cloning waypoint model, and a Go2 waypoint-to-action path | **Separate visual-policy candidate.** The released checkpoint is the behavior-cloning prior rather than the paper's RL-refined policy; measure it against CityWalker and CE-Nav instead of assuming paper-level performance. |
| [Arena-Rosnav](https://github.com/Arena-Rosnav/arena-rosnav) | ROS-oriented social-navigation stress tests across multiple simulators, crowd/social-force models, planners, and standardized metrics | **Recommended social-controller bridge after MetaUrban.** Use it to test dynamic avoidance and Nav2 challengers, not as the primary city renderer. |
| [iGibson](https://svl.stanford.edu/igibson/) | Interactive indoor homes/offices, movable objects, Bullet physics, and its historical pedestrian SocialNav tasks | **Secondary indoor tier.** It is a strong answer for household interaction but is not the best match for streets, curbs, sidewalks, and town-scale scenes. |
| [Habitat 3.0](https://aihabitat.org/habitat3/) | Human avatars, household collaboration, human-in-the-loop data, and indoor embodied learning | **Later companion-interaction research.** Keep separate from the frozen Habitat 2020 navigation protocol. |
| BARN and Habitat 2020 official code | Narrow, versioned external protocol checks | **Evaluation tiers, not product simulators.** Never tune away Go2 behavior merely to mimic Jackal/LoCoBot embodiment. |

For MetaUrban, freeze layouts, weather/lighting, pedestrian density, behavior
seeds, routes, and sensor noise before model selection. Evaluate static
collision, dynamic collision, minimum human clearance, personal-space
compliance, time-to-collision interventions, success, SPL, jerk, lateral-motion
ratio, timeout, and perception age. Maintain three disjoint sets: development,
frozen PR, and untouched confirmation. Render realism is useful only when the
sensor and dynamics variations produce measurable transfer robustness.

## Navigation model boundary

The reasoning model should output the **next semantic skill** when useful. It
should not output the next 20 ms body command. A navigation model may output a
short, timestamped sequence of body-relative waypoints:

```text
[(x_forward_m, y_left_m, heading_rad, confidence, horizon_s), ...]
```

The waypoint adapter then:

1. rejects stale observations and out-of-bounds proposals;
2. projects candidates into the LiDAR/odometry map;
3. checks traversability, clearance, kinematics, and semantic invariants;
4. selects or repairs a candidate using the global route;
5. passes a short trajectory to the local controller; and
6. retains the ability to stop immediately without another model call.

Forward motion remains preferred for destination travel. Lateral velocity is
valid for manual control, tight recovery, expressive skills, and planners that
explicitly account for Go2 kinematics, but it should be penalized in the route
cost rather than globally forbidden.

### Smooth, forward-preferred motion is already a controller concern

Parcel's current grid and semantic controllers use heading hysteresis: when a
new path direction is sufficiently far from the body heading, translational
velocity goes to zero, yaw is slew-limited until the exit threshold is reached,
and only then does forward tracking resume. During tracking, speed is reduced by
curvature, remaining distance, waypoint distance, people/obstacle proximity,
and acceleration limits. The point-to-point path emits `vy=0`; the wider command
contract deliberately retains lateral velocity for manual control and future
holonomic recovery. This is closed-loop behavior because each command is
recomputed from fresh pose/LiDAR/controller feedback, and Unitree Sport closes
the onboard gait/balance loop below it.

The next local-controller A/B should use maintained [Nav2 controller
plugins](https://docs.nav2.org/plugins/index.html) as reference implementations:

- Rotation Shim explicitly rotates toward a new path heading before handing
  control to a path tracker;
- MPPI provides predictive control for differential, omnidirectional, and
  Ackermann models and exposes a `PreferForward` critic;
- Regulated Pure Pursuit or Graceful Controller provide understandable smooth
  baselines; and
- Velocity Smoother in closed-loop mode uses odometry feedback to respect
  acceleration/deceleration limits.

Do not import an entire ROS stack merely to obtain one behavior. Reproduce or
wrap the smallest compatible controller behind Parcel's existing
`MidLevelCommand` contract, then compare identical scenes/seeds on task success,
clearance, heading overshoot, lateral distance, curvature, jerk, deadline misses,
and watchdog stops. The current rotate-first controller remains the incumbent
until a challenger passes those gates.

### Following behind the owner

The implemented `FollowFormation("behind")` path passively observes owner camera
tracks even before following begins. It estimates the direction of motion from
time-separated positions, rejects implausible speed/outliers, smooths the
estimate, requires repeated evidence, and expires it quickly. The controller
then chooses a point behind that heading and stages around the owner keep-out
instead of crossing through the person.

This is the right fail-closed first version, but its semantic limit matters:
when the owner is stationary, position history cannot tell which way their body
faces. A future camera model may estimate body orientation from keypoints, but
it must publish confidence, timestamp, owner identity, and an explicit
`motion_heading` versus `body_heading` provenance. Until then, “follow behind”
waits for fresh motion heading or asks/uses ordinary distance following; it must
not silently pretend that bearing-to-owner is owner orientation.

### Semantic grounding is the next product bottleneck

PlanIR cannot make “go to the sidewalk” work if perception never publishes a
fresh sidewalk region and safe approach candidate. On a real city scene, use a
two-speed camera lane rather than asking the text-only Gemma GGUF to imagine
pixels:

1. run a fast reviewed urban segmenter/detector continuously for road,
   sidewalk, curb, crosswalk, person, cyclist, vehicle, and common hazards;
2. invoke an open-vocabulary detector only for uncommon user-named landmarks
   such as “that lamppost” or a storefront;
3. use masks/tracks over multiple frames to reduce flicker and establish object
   identity;
4. associate camera rays/masks with calibrated LiDAR geometry and odometry to
   produce reachable regions and approach poses outside the LLM snapshot;
5. publish only bounded label, confidence, source, timestamp, affordances, and
   visibility to `ObservationSnapshot`; and
6. verify the requested semantic relation again after stopping.

[Grounding DINO](https://github.com/IDEA-Research/GroundingDINO) is an
Apache-2.0 open-set detector with published checkpoints. [SAM
2](https://github.com/facebookresearch/sam2) provides Apache-2.0 promptable
image/video masks and tracking. They are credible research components for the
open-vocabulary lane, not proof of real-time sidewalk accuracy. VLFM provides a
stronger full-system precedent: it combines depth occupancy/frontiers with a
language-grounded value map and reports deployment on Boston Dynamics Spot.

Evaluate phrase recall, false target rate, temporal stability, calibration,
camera-to-LiDAR association error, target approach validity, inference age, and
actual semantic task success across lighting/weather/viewpoint changes. A
low-confidence or contradictory grounding triggers rescan/clarification, never
a guessed route. Fixed urban classes should eventually use a distilled fast
model; a large open-vocabulary model should not occupy every camera frame or
the control critical path.

### Practical learned-navigation candidates

**ABot-N1/ABotN-Bench: product-aligned evaluator, not a downloadable policy.**
The July 2026 [ABot-N1 paper](https://arxiv.org/abs/2607.10383) decouples a slow
vision-language reasoner from a fast continuous-waypoint expert using grounded
pixel anchors. Its public [evaluation
repository](https://github.com/amap-cvlab/ABot-Navigation) exposes a small
`reset()`/`predict()` adapter and covers point-, object-, POI-, instruction-,
and person-following navigation. The released
[PointBench](https://huggingface.co/acvlab/ABotN-PointBench) and
[POIBench](https://huggingface.co/acvlab/ABotN-POIBench) include reconstructed
indoor/outdoor scenes, walkability/social rules, commercial POIs, and
entrance-vicinity success. The authors report 92.9% outdoor and 95.4% indoor
success for ABot-N1, but no official policy checkpoint was found in this audit.
Treat those as author-reported preprint results. ABotN-Bench is nevertheless a
strong candidate gate for sidewalks, POI entrances, road avoidance, and social
compliance; adding it to the frozen top-decile portfolio requires an explicit
portfolio version.

**CE-Nav: highest-priority Go2 local-policy candidate among those reviewed.** The
[CE-Nav repository](https://github.com/amap-cvlab/CE-Nav) publishes MIT-licensed
code plus general-expert and Unitree Go2 checkpoints. It separates geometric
reasoning learned by imitation from embodiment-specific dynamics adaptation
learned with reinforcement learning. Run it offline or in shadow mode before
control authority. The authors report 120 real trials across indoor maze,
office-corridor, and outdoor-path settings at SR 0.9167/SPL 0.8913 and over
10 Hz on an Orin NX; their simulated-Go2 mean is SR 0.8575/SPL 0.8190. Those
numbers make it the most concrete released Go2 local-policy challenger in this
audit, but they remain author-reported on CE-Nav's own protocol. Its Isaac Sim
2023.1.0 dependency is substantial, training code is not yet complete,
artifact terms need to be recorded, and no result predicts Parcel's camera,
LiDAR, Sport-controller, city, or external-eval performance.

**LeLaN: visible-target and owner-following specialist.**
[LeLaN](https://learning-language-navigation.github.io/) conditions a compact
visual policy on language such as a visible person or object, and the authors
report more than 1,000 real trials including a Unitree Go1. Their long-range
demonstration combines ViNT topological navigation with LeLaN only for the
final approach. That is the right role boundary for Parcel: evaluate it as an
`approach_visible_target` or person-follow proposal model, not as a city-scale
planner or owner-identity system.

**SACSoN: social cost rather than mere collision avoidance.** The
[SACSoN paper](https://arxiv.org/pdf/2306.01874) reports a 75-hour, 58.7 km
HuRoN dataset with more than 4,000 human-robot interactions and explicitly
optimizes how the robot affects pedestrians. Its wheeled, camera-based policy
is not a Go2 controller, but its lesson transfers to the dynamic-city gate:
measure pedestrian disturbance, personal-space intrusion, and intervention,
not only collision and goal progress.

**S2E and NavBench-GS: web-pretrained trajectory challenger.**
[S2E](https://github.com/VAIL-UCLA/S2E) releases a unified ONNX behavior-cloning
checkpoint that consumes an RGB history plus a point goal and emits local
waypoints or velocity. NavBench-GS includes a Unitree Go2 waypoint-to-action
path. The released checkpoint is not the paper's RL-finetuned policy and the
closed-loop releases remain incomplete, so it is a measured
CityWalker/CE-Nav challenger rather than an assumed upgrade.

**OmniNav: slow-memory/fast-waypoint research candidate.** The
[OmniNav repository](https://github.com/amap-cvlab/OmniNav) publishes
training/inference code and R2R, RxR, and OVON checkpoints. Its fast waypoint
policy plus slow frontier and memory system is relevant to Parcel search and
instruction tasks. The repository lacks a clear license declaration, so keep
it isolated and research-only.

**CityWalker: first learned challenger.** The
[CityWalker repository](https://github.com/ai4ce/CityWalker) publishes Apache
2.0 code and a public pretrained model for body-relative trajectory prediction
from urban video. Its [CVPR 2025
paper](https://openaccess.thecvf.com/content/CVPR2025/papers/Liu_CityWalker_Learning_Embodied_Urban_Navigation_from_Web-Scale_Videos_CVPR_2025_paper.pdf)
is close to Parcel's dynamic-city goal. Parcel already has the checkpoint. It
should first run in shadow mode against timestamped RGB, with its candidate
trajectory projected through LiDAR and compared against the current planner.
The original GitHub v1.0 checkpoint release has no artifact-specific license
notice, so Parcel now records the exact locked bytes as `NOASSERTION` rather
than inheriting the repository's code license. A later official
[ai4ce converted model](https://huggingface.co/ai4ce/citywalker) is explicitly
Apache-2.0 and says it contains converted weights derived from that checkpoint;
that strong maintainer-intent evidence applies directly to the converted model,
not unambiguously to the byte-distinct original `.ckpt`. Prefer a separately
pinned compatibility review of the licensed conversion or obtain maintainer
clarification before product redistribution.

**InternVLA-N1: a well-documented Go2-relevant dual-system comparison.** InternNav includes Go2
deployment material and separates slow semantic reasoning from fast trajectory
generation. Its code is MIT licensed. The latest System2 and DualVLN cards omit
license metadata, while the older
[`InternVLA-N1-wo-dagger`](https://huggingface.co/InternRobotics/InternVLA-N1-wo-dagger)
checkpoint explicitly uses CC BY-NC-SA 4.0. InternData-N1 page metadata and its
gated agreement are inconsistent; conservatively treat the noncommercial
agreement as controlling. Keep InternVLA research-only until the authors
provide clear deployment terms. The authors' [installation
guide](https://internrobotics.github.io/user_guide/internnav/quick_start/installation.html)
targets RTX 4090/A100-class GPUs, while the paper separately reports roughly
20 GB of GPU use for one tested setup. A carefully isolated run may fit 32 GB,
but neither the guide's system-RAM listing nor the paper proves Parcel latency.

**NaVILA: Go2 embodiment comparison.** NaVILA is architecturally close and has
an available checkpoint. Its undeclared checkpoint license and older Habitat
dependencies make it a contained research adapter, never a silent production
dependency.

**VLFM and ConceptGraphs: semantic grounding components.**
[VLFM](https://github.com/bdaiinstitute/vlfm) uses open-vocabulary frontier
selection for zero-shot ObjectNav; it can inform searches such as “find a
lamppost.” [ConceptGraphs](https://github.com/concept-graphs/concept-graphs)
builds an open-vocabulary 3D scene graph and can inform persistent object
memory. Both repositories use MIT licenses. ConceptGraphs expects RGB-D-style
geometry, so Parcel would need calibrated camera-to-LiDAR association rather
than pretending a 2D scan is an RGB-D camera.

**ViNT/NoMaD: lightweight topological challenger.** The
[visualnav-transformer repository](https://github.com/robodhruv/visualnav-transformer)
provides MIT-licensed goal-conditioned visual-navigation policies and
topological-map tools. Its older dependency stack and goal-image formulation
make it a later experiment, not the first semantic planner.

## Language-model candidates

The current flagship Kimi models are not workstation candidates. Moonshot's
[Kimi K2.5](https://github.com/MoonshotAI/Kimi-K2.5) has one trillion total and
32B activated parameters; its official Hugging Face repository is about 595 GB.
The newer [Kimi K3](https://github.com/MoonshotAI/Kimi-K3) activates 104B
parameters and is larger still. Both are useful agentic-model references, but
neither belongs on a 32 GB robot desktop. The older
[Kimi-VL-A3B-Thinking-2506](https://github.com/MoonshotAI/Kimi-VL) is a more
plausible experiment at 16B total/3B active parameters under MIT terms. Its
official BF16 artifact is still approximately the size of the entire GPU before
runtime state, it is not a Go2 policy, and a separately reviewed quantization
would be required. It therefore ranks behind the already-installed Gemma;
Qwen remains an unmeasured challenger.

| Candidate | Suggested Parcel role | Public status and terms | 32 GB desktop assessment | Decision |
| --- | --- | --- | --- | --- |
| Installed Gemma 4 26B-A4B Q4 | Conversation plus constrained PlanIR | [Official Q4 card](https://huggingface.co/google/gemma-4-26B-A4B-it-qat-q4_0-gguf) lists Apache 2.0; 25.2B total, 3.8B active | 14,439,363,584-byte artifact; measured with all 31/31 layers on the RTX 5000 Ada through official `llama.cpp` b10236 CUDA12 OCI | Baseline and shared-backbone design |
| FunctionGemma 270M | Fine-tuned bounded route-function selector | [Official page](https://ai.google.dev/gemma/docs/functiongemma); Gemma terms, not Apache; not a dialogue model | Official phone evidence supports edge feasibility but not Parcel latency or calibrated safety; the base results make task-specific tuning mandatory | Train and A/B against deterministic routing; deterministic code authors trusted `IntentFrame` provenance and direct-skill binding |
| Ministral 3 8B Instruct Q4_K_M | Dialogue or non-thinking structured-plan specialist | [Official GGUF](https://huggingface.co/mistralai/Ministral-3-8B-Instruct-2512-GGUF) lists Apache 2.0, JSON/function calling, and a 256K context | Exact 5,198,911,904-byte artifact is installed at SHA-256 `33e7a72c…ca761`; b10236 measured 35/35 CUDA layers, 6,220 MiB idle process VRAM, and 101.944 ms median conversation TTFT | **Measured and rejected as incumbent:** 5/10 machine conversation cases and 3/5 PlanIR; no full-call latency win |
| Ministral 3 8B Reasoning Q4_K_M | Deliberative PlanSketch specialist | [Official GGUF](https://huggingface.co/mistralai/Ministral-3-8B-Reasoning-2512-GGUF) lists Apache 2.0, reasoning, JSON/function calling, and a 256K context | Exact 5,198,910,368-byte artifact is installed at SHA-256 `894aa364…38c6`; b10236 measured 35/35 CUDA layers and 6,220 MiB idle process VRAM | **Measured and rejected at the current boundary:** a predeclared 0/1 frozen PlanSketch compatibility gate exhausted 1,024 tokens with invalid JSON in 12,262.204 ms; no five-case, conversation, or physical claim |
| `gpt-oss-20b` | General-purpose reasoning model in a planner-only experimental lane | [Official repository](https://github.com/openai/gpt-oss) and [model card](https://huggingface.co/openai/gpt-oss-20b) list Apache 2.0; applicable OpenAI usage policy still applies; 21B total and 3.6B active parameters; Harmony is required | OpenAI reports native MXFP4 can run within 16 GB, but Parcel runtime/template compatibility, KV and sampled peak, co-residency, latency, and task quality are unmeasured | First test as a replacement profile with Gemma unloaded; not an admitted robotics planner or automatic replacement |
| Qwen3.6-35B-A3B Q4 | Plan and conversation challenger | [Official model card](https://huggingface.co/Qwen/Qwen3.6-35B-A3B) lists Apache 2.0; a [ggml-org community Q4 conversion](https://huggingface.co/ggml-org/Qwen3.6-35B-A3B-GGUF/blob/main/Qwen3.6-35B-A3B-Q4_K_M.gguf) is 20.4 GB | Fits host RAM, but GPU placement is unproven; projector, KV cache, backend support, and co-resident workloads must be measured | Download only after the evaluation harness can compare it |
| RoboBrain 2.5 4B BF16 | Camera semantic-grounding and execution-progress shadow lane | [Official checkpoint](https://huggingface.co/BAAI/RoboBrain2.5-4B) and [code](https://github.com/FlagOpen/RoboBrain2.5) list Apache 2.0; the official tree is 9.67 GB and the card labels 5B parameters | Static weights fit the RTX 5000 Ada in isolation; end-to-end VRAM, camera preprocessing, output validity, latency, and coexistence with Gemma/simulation/voice are unmeasured | High-value multimodal shadow experiment after a frozen sidewalk/lamppost grounding gate; never send its point/trace output directly to motion |
| Kimi-VL-A3B-Thinking-2506 | Optional visual reasoning challenger | Official repository lists MIT; 16B total/3B active | BF16 nearly fills VRAM; a licensed quantization must be measured | Lower priority; no current Go2 advantage |
| InternVLA-N1 8B | Navigation System 2 / waypoint research | Latest System2/DualVLN cards omit license metadata; older wo-dagger checkpoint is CC BY-NC-SA 4.0 | Paper reports about 20 GB on RTX 4090; isolate and measure | Research-only pending explicit commercial terms |
| NaVILA Llama3 8B | Go2 visual-language navigation comparison | Code Apache 2.0; checkpoint card lacks declared terms | Plausible isolated inference; legacy stack raises integration cost | Research-only |
| GR00T / π0 / OpenVLA family | Manipulation architecture references | GR00T code is Apache 2.0 and weights use NVIDIA's Open Model License; OpenVLA code is MIT and weights inherit Llama terms; openpi uses repository/checkpoint-specific terms | Some inference fits, useful tuning generally expensive | Do not download for current Go2 navigation |

“Fits 32 GB” means only that a carefully selected inference configuration may
fit. It does not mean multiple large models, KV caches, simulator rendering,
and speech can be resident together, or that latency meets the robot deadline.
The retained Gemma cycle measured a 15,280 MiB idle server process and only
15,774 MiB free after the five-case evaluation on the 32,760 MiB GPU; that was
not a sampled peak. The remaining approximately 15.4 GiB is not evidence that a
generic “within 16 GB” gpt-oss profile can coexist with Gemma. GB/GiB
interpretation, runtime, KV cache, fragmentation, simulator, and voice can make
the margin negligible or negative.

The first `gpt-oss-20b` admission must therefore unload Gemma and treat gpt-oss
as the planner replacement profile. Any later dual-residency experiment needs
an explicit reserve, exact cold/load/swap and concurrent peak measurements, and
must count model swapping or CPU offload in end-to-end latency. The model is a
general reasoning challenger that can be assigned a structured planning role;
it is not a structured-planning specialist. The two Ministral artifacts add
lower-footprint specialist controls. CE-Nav/S2E are navigation-controller
challengers, not language planners, and these roles must not be scored as
interchangeable “brain models.”

Harmony is part of the gpt-oss contract, not an optional prompt style. A
compatible serving runtime may apply it automatically; direct generation must
use [`openai-harmony`](https://github.com/openai/harmony) and Parcel must parse
only the intended final structured result. Runtime-enforced Structured Outputs
can constrain syntax, not semantic correctness, so the existing binder,
validator, compiler, executive, and sensor authority remain mandatory. The
official repository calls its PyTorch, Triton, and Metal implementations
educational/reference implementations rather than production serving stacks;
Parcel's exact checkpoint, runtime, template, and output enforcement must be
pinned and admitted independently from the existing Gemma/Ministral GGUF path.

The official gpt-oss model card also says deployments may require additional
system-level safeguards. Its generic evaluations report high hallucination
rates for `gpt-oss-20b` on SimpleQA (0.914) and PersonQA (0.532); those are not
Parcel scores, but they are enough to reject any inference that fluent
reasoning can own sensor facts or task completion. Harmony analysis can itself
be hallucinated and must never be exposed as trustworthy reasoning or spoken to
the owner. Perception supplies facts, deterministic code admits and closes
tasks, and only the executive/motor stack has physical authority.

The audited local inventory contains the complete 14,439,363,584-byte Gemma
GGUF (SHA-256
`3eca3b8f6d7baf218a7dd6bba5fb59a56ee25fe2d567b6f5f589b4f697eca51d`),
the complete 5,198,911,904-byte Ministral 3 8B Instruct Q4_K_M GGUF
(SHA-256
`33e7a72cf5e6e2cfc2f2847075acc013d68bba023e35310cef86b5cf8fdca761`),
the complete 5,198,910,368-byte Ministral 3 8B Reasoning Q4_K_M GGUF
(SHA-256
`894aa3645ef8708a81dbe201c26105ce37c4c741252c89c5a78f81b49ac438c6`),
the 1,752,028,242-byte CityWalker checkpoint (lock-file SHA-256
`a42326778e5e318c6222575dc5e02f1794d9a60cce4dc8f8a2ee5df7dc6d1c29`),
and a 147,964,211-byte Whisper `base.en` model. The `models/csm-1b` directory
contains configuration/tokenizer/reference-audio files but no safetensor
shards, so it is not a usable installed CSM model. Gemma 4 12B, Voxtral, Qwen,
Kimi-VL, InternVLA-N1, NaVILA, PersonaPlex, Moshi, and Fish
S2 Pro remain locked, partial, or research candidates rather than locally
measured dependencies. Installed Ministral Instruct and Reasoning are evaluated
rejected controls, not working production capabilities. This distinction prevents a
model card, model download, or successful CUDA load from being reported as a
quality win.

### Measured single-probe Gemma PlanIR hardening history

Five live sidewalk-plan probes were run on 2026-08-03 against `llama.cpp`
b10235 with 32 CPU threads and zero GPU layers:

| Run | Decode configuration | Result | End-to-end model call |
| --- | --- | --- | ---: |
| 1 | thinking enabled, 1,024 output tokens | Failed: consumed the full budget and returned no PlanIR response content | 39,256 ms |
| 2 | thinking disabled, before canonical prompt/schema hardening | Failed semantic parsing | 25,247 ms |
| 3 | thinking disabled, after canonical goal/target/null-success-tolerance hardening | Succeeded: `NavigateTo(sidewalk) -> Hold` parsed and passed `PlanValidator` | 26,440 ms |
| 4 | deterministic temperature zero with model-authored mandatory invariants | Failed validation because the model omitted a required road invariant | 25,105 ms |
| 5 | deterministic temperature zero with system-compiled safety invariants | Succeeded: `NavigateTo(sidewalk) -> Hold`; the model's one advisory invariant could not weaken the five effective rules | 24,825 ms |

Run 3 used a 1,973-token prompt and 612 completion tokens; time to first output
was 4,865.985 ms. Its validated plan hash was
`77116d22849ae3ae0a435b21d41d9c94d6ec279f73a99f4b62c065a27e440544`.
Run 5 used a 2,272-token prompt and 537 completion tokens; time to first output
was 5,791.517 ms and its validated plan hash was
`8ab455dfd03a9316a0007987abcccc1655129839e40876025186ac41a4f248fc`.
The raw Run 5 plan named only road avoidance, while the system compiled
collision margin, road avoidance, stale-perception stop, yielding to people,
and critical-task interruption protection. This fixes a trust-boundary bug,
not the model's general reasoning. The exact utterance routes to Parcel's
reviewed `direct_skill` lane in normal operation, so this was a deliberate
standalone planner probe, not a normal-runtime task acceptance. It proves one
live plan can cross the provider/schema/validator boundary; it does not
establish runtime routing, paraphrase
coverage, recovery quality, conversation quality, or embodied task success.
The default plan decode is now non-thinking. These probes motivated the frozen
suite below; their independent conclusion still holds: a 24.8-second plan is
far above the desired companion latency even though control remains safe and
asynchronous.

### Frozen `planner_quality_v2` result

The broader frozen suite contains five compound semantic cases: sidewalk then
hold, sidewalk then lamppost, five steps away then hold, one owner orbit then
behind-owner follow, and correction of an active task to a lamppost. It invokes
the real deterministic router, live Gemma provider, admitted registry, fresh
camera/LiDAR-only observation contract, validator, and the same admission
functions used by the runtime. To avoid prompt leakage, the current challenger
prompt states generic target/sequence rules rather than naming the suite's
sidewalk or lamppost combinations.

| Immutable run | Boundary change | Accepted semantic plans | Median TTFT | Median usable-plan/model call |
| --- | --- | ---: | ---: | ---: |
| `planner-v2-20260803113925Z-4886b1b8` | Manifest-default prompt, runner v1 | 0/5 | 5,179.488 ms | 27,695.217 ms |
| `planner-v2-20260803114428Z-dc470c6e` | Schema/context hints only; backend still authored envelope fields | 0/5 | 886.122 ms | 23,098.741 ms |
| `planner-v2-20260803114909Z-95410d63` | Post-decode trusted envelope binds runtime authority | 2/5 | 850.635 ms | 20,930.396 ms |
| `planner-v2-20260803115715Z-ad65c4ec` | Generic semantic prompt challenger, no contract compiler | 1/5 | 4,789.363 ms | 25,093.161 ms |
| `planner-v2-20260803120316Z-6406b694` | Same prompt and trusted envelope plus `semantic-planir-compiler-v1` | **5/5** | **868.039 ms** | **19,664.294 ms** |
| `planner-v2-20260803124255Z-75a84bba` | Frozen compiler/prompt on exact official b10236 full-CUDA profile | **5/5** | **855.379 ms** | **5,657.459 ms** |

The final CPU run used model SHA-256
`3eca3b8f6d7baf218a7dd6bba5fb59a56ee25fe2d567b6f5f589b4f697eca51d`,
generic prompt SHA-256
`52e3636ae1e4f3042d8cbd9839b6cd0b41883ecc7744d223a2b724796743f44e`,
and unchanged case SHA-256
`6717f2fbda80920133f20f4584630f78748b6146c17222600bf71471e9272d1a`.
Its declared server cache state was warm. Mean/p95-nearest-rank TTFT were
875.043/946.657 ms; mean/p95 usable-plan latency were
20,689.074/25,235.046 ms. The model emitted a median 551 completion tokens
(584.4 mean), which makes verbose PlanIR serialization the dominant CPU
bottleneck after first output.

The subsequent frozen GPU run retained 5/5 accepted semantic plans with the
same model, cases, generic prompt, trusted-envelope binder, and contract
compiler. Its warm median TTFT was 855.379 ms and median usable-plan/model call
was 5,657.459 ms; the latter is a **71.23% reduction** from the CPU run's
19,664.294 ms. GPU mean/p95 usable-plan latency were 5,990.583/7,201.283 ms.
This is a real full-CUDA latency result, but a 5.66 s median still misses a
fluid companion target. With only five values, nearest-rank p95 is effectively
the observed maximum, not a stable tail estimate.

The gain from 2/5 or 1/5 to 5/5 is deliberately attributed to ownership, not
to hidden model intelligence. The runtime binds provenance, task revision, and
interrupt authority after decode because JSON Schema `const` was not reliably
enforced by this backend. The compiler then supplies controller boilerplate
that the model should never own: step IDs, resources, required and conditional
preconditions, success policy, timeouts, single-attempt recovery, and minimum
interruptibility. Skill order and bounded semantic arguments remain raw-model
decisions, and invalid targets/directions still fail closed. Both raw and
admitted plans are retained in every result.

Every run reports `physical_navigation_episode_count: 0` and a null physical
success rate. Thus 5/5 proves only the selected semantic decomposition and
admission boundary. It does not prove perception, collision avoidance,
execution, conversational quality, or Unitree behavior. The next language
optimization must not treat compactness as quality: the first live PlanSketch
challenger was faster but fell to 3/5 and was rejected. Its failures may seed a
separate development corpus, after which a new untouched confirmation set can
compare corrected Gemma, Ministral, and `gpt-oss-20b` challengers under the same
hardware, schemas, cases, and evaluation gates. Each challenger runtime must be
admitted and reported independently; gpt-oss is not assumed compatible with the
existing GGUF server profile.
The immutable run ledger is in
[`evals/companion/planner_quality_v2/results/README.md`](../evals/companion/planner_quality_v2/results/README.md).

### Frozen live conversation calibration and split-model result

The new `parcel-conversation-quality-v1` corpus freezes ten turns spanning
explicit sadness, happy news, sadness during a critical navigation task,
hypothetical affect, short-term name memory, camera epistemic limits, disabled
Google Maps, joke reaction, an explicit no-gesture request, and refusal to make
a clinical diagnosis. Its manifest hash-locks the cases, result schema, core
and action-policy prompts, dynamic runtime template, companion function, and
three personality files. The runner records provider parsing, structured
action safety, affect, semantic/style heuristics, TTFT, full call, and tokens.
It exposes no tools and dispatches no motion.

This is deliberately a calibration suite, not a claim that keyword checks
measure warmth. `human_conversation_quality_score` remains null until blinded
reviewers score relevance, naturalness, empathy, persona consistency, and
promise/capability honesty. Machine semantic checks are separately reported so
that a narrow lexical miss cannot be confused with an unsafe action proposal.

| Exact full-CUDA model | Parse | Machine cases | Affect | Structured safety | Semantic heuristic | Median TTFT | Median full call |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Gemma 4 26B-A4B Q4 | 10/10 | **6/10** | 10/10 | 9/10 | **7/10** | 348.843 ms | **1,236.951 ms** |
| Ministral 3 8B Instruct Q4_K_M | 10/10 | 5/10 | 10/10 | 9/10 | 6/10 | **101.944 ms** | 1,323.932 ms |

These ten warm sequential turns do not measure cold load, a turn queued behind
a plan, concurrent inference slots, ASR/TTS or first spoken audio, simulator
contention, or human companion quality. Model selection for conversation must
therefore add blinded review of empathy, coherence, persona stability,
capability honesty, repair/barge-in behavior, and first-audio latency; planner
scores cannot select the conversational model.

Both raw providers incorrectly proposed `play_bow` when the user asked a
hypothetical question about sadness. That failure remains counted. Parcel's
deterministic production guard separately suppresses motion for hypothetical,
negated, and information-seeking language; the exact transcript is now a
regression test. This defense-in-depth result supports the split architecture:
the conversational model may suggest a social action, but deterministic route
semantics and the executive decide whether any proposal may become motion.

Several other v1 failures are rubric artifacts: Gemma used
`answer_question`/`navigation_request` rather than an enumerated synonym and
used semantically appropriate wording outside literal substrings. A future v2
must let the deterministic router supply the intent label and use human or
model-independent semantic review without retroactively changing v1.
Ministral also implied it could “check nearby locations or guide you here”
while Maps and such capabilities were disabled. It therefore produced a large
TTFT win but no quality or complete-response win.

The same Ministral artifact was evaluated as a full PlanIR planner on the
unchanged five cases. It passed only 3/5, versus Gemma's 5/5. Median TTFT fell
from 855.379 to 382.199 ms, but median usable-plan latency increased from
5,657.459 to 6,071.293 ms. Its two invalid plans failed closed: one authored an
out-of-contract five-metre goal tolerance/owner query, and one emitted numeric
orbit `size` instead of the contract enum. Thus the first concrete
specialist-model ablation answers the user's proposed split cautiously:
separate APIs and evaluation lanes are correct, but this smaller Instruct model
is not a better conversation or planning brain. Keep Gemma as the measured
shared incumbent, preserve deterministic routing, and evaluate any future
conversation and planner specialist independently before a combined test.

### Headless embodied PlanIR gate

The separate [embodied gate result](../evals/companion/embodied_plan_v1/results/embodied-plan-v1-20260803-baseline01.json)
starts from the exact admitted frozen Gemma plans, revalidates them, submits
them through `TaskExecutive` and `SemanticTaskRuntimeAdapter`, and executes the
production semantic navigation/spatial controllers in `HeadlessCityWorld`.
The gate uses synthetic LiDAR plus oracle semantic tracks constrained by
camera-like range/FOV. Region polygons, object positions, approach metadata,
and the owner track are derived directly from simulator geometry rather than
rendered-camera perception. Evaluator scoring remains separate, but this gate
tests planning/controller integration given idealized semantic perception; it
does not test detection, camera–LiDAR association, owner tracking, or real-sensor
accuracy.

The deterministic frozen result is 4/4 supported cases passed, zero supported
failures, and one explicit unsupported case. Across all five cases it executes
six physical skills and 1,137 simulator steps with zero collisions, zero
timeouts, terminal stops, and a 0.883147 m minimum clearance. Sidewalk interior,
lamppost surface vicinity, five-step owner-relative displacement, orbit winding,
and checkpoint-gated task correction are scored from evaluator truth rather
than plan text. `FollowFormation` remains explicitly unsupported because v1's
owner is fixed and supplies no moving-owner heading stream; the orbit prefix is
executed, but the compound case cannot contribute a fake pass. A v2 needs a
moving-owner camera-track episode and the production formation controller.

This closes the semantic-plan-to-headless-controller gap, not the hardware gap.
The base uses deterministic kinematics in MuJoCo geometry, not Unitree contact
dynamics, commissioned actuators, or real camera/LiDAR accuracy. It is also not
an external navigation score.

### PlanSketch prototype and rejected GPU challenger

`PlanSketch v1` is now an opt-in provider/runtime contract that carries only the
model-owned goal, ordered skills, bounded arguments, and explicit navigation
grounding. The same trusted runtime deterministically expands it into full
PlanIR before validation and execution. In the immutable
[offline counterfactual](../evals/companion/planner_contract_size/results/plansketch-v1-static-run05.json),
equivalent semantics from the five accepted CPU plans occupied 1,450 canonical
JSON bytes instead of 5,413, a **73.2126% byte reduction**.

That artifact performs no model inference and uses no tokenizer. It therefore
proves serialized contract-size reduction only—not fewer model tokens, faster
TTFT or decode, PlanSketch generation quality, or embodied success.

The required live [frozen full-CUDA
challenger](../evals/companion/planner_quality_sketch_v1/results/planner-sketch-v1-20260803-gemma4-gpu-run01.json)
has now been run against the same Gemma artifact, b10236 server, five cases,
1,024-token maximum, non-thinking decode, and semantic scorer as the valid
PlanIR GPU baseline. PlanSketch reduced median full-call latency 63.99%
(5,657.459 to 2,037.060 ms), median completion tokens 71.02% (528 to 153),
median provider output bytes 71.92% (1,485 to 417), and median TTFT 12.17%
(855.379 to 751.266 ms). Deterministic compilation took a median 0.102 ms.

Quality regressed from 5/5 to **3/5**. The owner-relative case used the wrong
goal query label, and the orbit/follow output violated the rule that a
non-`NavigateTo` skill must set navigation grounding to JSON `null`; the latter
failed closed at the provider boundary. The challenger executed zero physical
episodes. PlanSketch therefore remains opt-in and is **not promoted**. Use the
failures only to build a disjoint development set; tuning the prompt on these
five frozen confirmation cases and replaying them would be overfitting.

### Measured llama.cpp CUDA readiness

The earlier CPU-only b10235 finding is retained as history, not current state.
The immutable [readiness
artifact](../evals/companion/gpu_readiness/results/gpu-readiness-20260803-b10236-oci-cuda.json)
now passes `ready_for_gpu_inference`, binary, driver, model, memory, and planner
authorization checks against the exact official `llama.cpp` b10236 CUDA12 OCI
distribution. It pins upstream commit
`1464c62d88f699ec9700c8010bbfdbc603a9efd6`, OCI index digest
`sha256:fd68d13013141833e8214ecad6e1fbefb532db6a00b980cdecfe33603dbf2675`,
manifest digest
`sha256:fcd0f95f2c70156f03ed47c22ff4bea95018bada125c5772af71e83f2c35f2e4`,
and seven verified critical files. The server hash is
`e3c775bb274d01d5c3345f37aaea55470902187b4433d2689eab367fa4150f3c`.

The same doctor verifies the exact 14,439,363,584-byte Gemma GGUF at SHA-256
`3eca3b8f6d7baf218a7dd6bba5fb59a56ee25fe2d567b6f5f589b4f697eca51d`
and identifies the NVIDIA RTX 5000 Ada Generation, driver 595.84, compute
capability 8.9, and 32,760 MiB total VRAM. The OCI server's device probe reported
32,227 MiB usable and 30,767 MiB free before model load. A missing local source
toolchain still blocks rebuilding the same binary from source, but it does not
invalidate the verified, isolated official OCI inference distribution.

The readiness JSON intentionally does not claim a loaded model or measured
offload. The subsequent immutable [runtime-cycle
artifact](../evals/companion/gpu_readiness/results/gpu-runtime-20260803-b10236-planner-cycle01.json)
hashes and extracts the ignored verbose launch log
`.cache/reasoner/llama-b10236-cuda-planner-run06-v4.log`: `llama.cpp` reported
**31/31 layers offloaded**, a 13,755.42 MiB CUDA model buffer, 1,060.00 MiB
total CUDA KV buffers, and a 108.52 MiB CUDA compute buffer. It records 15,280
MiB server-process VRAM at post-load idle, 15,304 MiB before shutdown after the
PlanIR and PlanSketch evaluations, clean shutdown, and return to 1,144 MiB host
GPU use. These are point-in-time snapshots, not a sampled peak. The linked
planner results record the same b10236 official-OCI profile and exact model hash
with `gpu_layers: 999`/`31-of-31-layers`. The readiness, runtime-cycle, and
planner artifacts are therefore the durable claim anchors even though the raw
verbose log remains ignored. A future profiler should still capture peak VRAM.
See
[`REASONER_GPU_PROFILE.md`](REASONER_GPU_PROFILE.md) for commands and exact
evidence.

The composable Ministral overlay inherits that exact OCI/runtime profile and
changes only the model artifact and memory admission. Its readiness artifact
verifies 5,198,911,904 bytes and SHA-256
`33e7a72cf5e6e2cfc2f2847075acc013d68bba023e35310cef86b5cf8fdca761`.
The retained verbose runtime record measures **35/35 layers offloaded** (33
repeating plus output/input placement as reported by `llama.cpp`), a 4,662.05
MiB CUDA model buffer, 1,088.00 MiB KV buffer, 116.01 MiB compute buffer, and
6,220 MiB point-in-time server-process VRAM. A full-CUDA health inference
returned `READY.`; clean shutdown restored host GPU use from 7,369 MiB to
1,140 MiB. This proves compatibility and placement, not model quality. The
conversation and PlanIR results above reject production promotion despite the
smaller memory footprint and faster TTFT.

The separately locked Ministral Reasoning artifact was then downloaded only
through the exact-size/SHA fetcher and admitted through its own composable
overlay. The retained verbose record again measures **35/35 CUDA layers**,
4,662.05 MiB model, 1,088.00 MiB KV, 116.01 MiB compute, and 6,220 MiB idle
server-process VRAM. Shutdown closed its isolated port and returned host GPU
use exactly from 7,369 MiB to the 1,141 MiB pre-load observation.

Its model-quality experiment stopped at a predeclared compatibility gate. The
existing frozen PlanSketch prompt, schema, first case, router, compiler,
validator, and scorer were reused without modification; thinking was enabled
under the same 1,024-token bound. The checkpoint began a schema-shaped answer
but repeated an invented property name inside the schema's generic `arguments`
object until `finish_reason=length`. It returned no valid JSON after 3,804
bytes, 1,024 completion tokens, 343.803 ms TTFT, and 12,262.204 ms full-call
latency. The verbose log preserves the raw malformed completion. Because the
first gate failed, the other four frozen cases were not exposed, the budget was
not increased, and the prompt/schema were not tuned post hoc. This is an
honest **0/1 compatibility failure**, not a five-case accuracy baseline.

For orientation only, Gemma's paired cold PlanSketch warm-up passed 1/1 in
2,193.317 ms with 150 completion tokens; its complete five-case PlanSketch run
was 3/5 at 2,037.060 ms median. Gemma PlanIR remains 5/5 at 5,657.459 ms median,
and Ministral Instruct PlanIR was 3/5 at 6,071.293 ms median with 475 median
completion tokens. Reasoning's fast first output therefore does not compensate
for failed parsing, token exhaustion, absent semantic parity, or worse usable
latency. It is not promoted, has no conversation role, and ran zero physical
episodes.

### Gemma 4 speculative-decode hypothesis

Google's [Gemma 4 overview](https://ai.google.dev/gemma/docs/core) says every
Gemma 4 size includes a dedicated multi-token-prediction draft model for
speculative decoding, and publishes a matching [26B A4B QAT assistant
checkpoint](https://huggingface.co/google/gemma-4-26B-A4B-it-qat-q4_0-unquantized-assistant).
This is a plausible way to reduce the long post-TTFT serialization cost while
retaining the installed target model. It is only a hypothesis for Parcel: the
assistant artifact is not installed, its quantization pairing requirements must
be respected, and compatibility with the current GGUF plus `llama.cpp` b10236
path has not been demonstrated. Admit it only after exact-format support,
memory headroom, byte-for-byte or semantic output parity, accepted-plan quality,
and cold/warm latency are measured; never quote Google's general acceleration
claim as a Parcel speedup.

### Why Qwen is an experiment, not an automatic replacement

Qwen3.6-35B-A3B advertises tool use, multimodal input, and 3B active parameters
in an Apache-licensed open-weight release. Those traits make it a sensible
PlanIR challenger. They do not establish better Parcel task success. The model
is larger on disk than the current Q4 Gemma, conversation quality is
subjective, and planning quality depends heavily on the schema, perception
snapshot, and validator. Parcel should not download another 20 GB model until
the same frozen prompts, tasks, latency measurements, and safety checks can be
run against both.

## Voice, audio tokens, and the motor boundary

The current cascaded design—ASR, transcript reasoning, then TTS—is still the
recommended initial Parcel baseline because each stage is inspectable, cancellable, and
independently measurable.

The installed 26B Gemma variant does not accept native audio input. Gemma's
[official overview](https://ai.google.dev/gemma/docs/core) lists audio support
only for selected smaller variants. Feeding codec tokens into the 26B text
prompt would not create audio understanding; it would merely produce unknown
text tokens without the required audio encoder or training.

The official [Gemma 4 12B Unified model
card](https://huggingface.co/google/gemma-4-12B) and [audio
guide](https://ai.google.dev/gemma/docs/capabilities/audio) make that smaller
variant an audio-aware reasoning candidate: it accepts text, image, and audio
and supports ASR, translation, and speech understanding. Its output is still
**text**. It is not native speech generation, simultaneous listen/speak, or a
duplex voice stack, and it is not installed or measured on Parcel. Test it as
an alternative ASR-plus-reasoning stage without weakening final-transcript
authorization.

[Voxtral Mini 4B Realtime
2602](https://huggingface.co/mistralai/Voxtral-Mini-4B-Realtime-2602) is the
most concrete open streaming-ASR candidate in this audit. Its official card
lists Apache 2.0 BF16 weights, configurable delay at 80 ms multiples through
1,200 ms plus 2,400 ms, recommends 480 ms as its quality/latency balance, and
requires a single GPU with at least 16 GB for the documented vLLM path. Those
are model/card parameters, not Parcel end-to-transcript measurements. It
transcribes streaming audio to text; it does not generate conversational speech
or authorize a skill.

[Voxtral 4B TTS
2603](https://huggingface.co/mistralai/Voxtral-4B-TTS-2603) is a separate
speech-output candidate with streaming and voice adaptation. Its checkpoint is
CC BY-NC 4.0 because the reference voices carry noncommercial terms. The card's
70 ms latency is measured at concurrency one on a single NVIDIA H200 with a
500-character prompt and ten-second audio reference. Do not project that number
onto the RTX 5000 Ada, a Bluetooth audio path, time to acoustic playback, or a
commercial deployment.

[PersonaPlex](https://research.nvidia.com/labs/adlr/personaplex/) is a notable
access-gated open-weight full-duplex speech model. NVIDIA describes simultaneous listening
and speaking, interruptions, and backchannels. Its [official model
card](https://huggingface.co/nvidia/personaplex-7b-v1) lists roughly 8B BF16
parameters under the NVIDIA Open Model License and reports testing on an A100
80 GB. Parameter storage suggests an isolated experiment may fit 32 GB, but
official latency and stability on this RTX 5000 Ada are unknown.

[Moshi](https://github.com/kyutai-labs/moshi) is another native full-duplex
speech-text system and exposes its Mimi neural audio codec. Its repository
notes substantial GPU requirements for the PyTorch path. It is useful for a
voice-lab comparison, not as a motion planner.

[Qwen3-Omni](https://github.com/QwenLM/Qwen3-Omni) is an Apache-licensed native
audio/text/vision architecture reference, but its official BF16 configurations
require roughly 69--79 GB. It is not a viable resident model on this 32 GB
desktop and does not change the cascaded production recommendation.

[Sesame CSM](https://github.com/SesameAILabs/csm) is an access-gated
open-weight conversational speech-generation model whose repository metadata
lists Apache 2.0. Its Llama backbone/dependencies and applicable underlying
terms must still be recorded. The project describes it as an audio model rather
than a general multimodal reasoner and recommends a separate LLM. [Fish S2
Pro](https://huggingface.co/fishaudio/s2-pro) is also a
TTS model rather than a planner; its [inference
documentation](https://github.com/fishaudio/fish-speech/blob/main/docs/en/inference.md)
recommends 24 GB VRAM, and its weights use the Fish Audio Research License with
separate commercial terms.

Neural audio tokens are valuable inside a native speech model because they can
retain timing, prosody, overlaps, and nonverbal vocalization. They are a poor
motor interface. The trusted planning input should be:

- the final recognized transcript;
- turn-boundary and interruption events;
- optional bounded evidence such as `sadness_probability`, speech rate, or
  rising intonation, with model/version/confidence/provenance; and
- the current accepted task and safety state.

An audio model may say “mm-hm” while listening or produce an expressive
chuckle. It may not command `walk`, `pose`, or `stop`. Any inferred request
passes through the same transcript/IntentFrame/PlanIR path. This prevents a
voice model's conversational prediction from becoming unreviewed motion.

### Host audio and Bluetooth finding

The workstation can support a headset path, but it is not ready for a live
microphone session yet. The 2026-08-03 audit found:

- a powered Bluetooth controller advertising hands-free, audio-source, and
  audio-sink profiles;
- active PipeWire and WirePlumber services;
- an ALSA `ALC1220 Analog` capture device and analog/HDMI playback hardware;
- the controller currently reporting `Pairable: no`;
- no paired Bluetooth device; and
- no active PipeWire source and only a dummy PipeWire sink.

The host has the prerequisite Bluetooth and ALSA hardware, but duplex headset
operation has not been demonstrated. AirPods or another headset are a
commissioning candidate only after enabling pairability, pairing, selecting a
bidirectional HFP/HSP-style microphone profile, and passing real capture,
playback, latency, and barge-in probes. An A2DP-only profile is high-quality
playback, not duplex capture. Before enabling voice, the startup doctor should
require a selected source and sink, open each stream, perform a short
loopback/VAD probe, record sample rates and buffer sizes, and leave the existing
streaming-text UI available on failure. This is a device configuration task,
not a reason to couple audio to the motion controller.

### GPU admission profiles

The measured GPU has 32,760 MiB. The following should be explicit startup
profiles rather than hopeful dynamic co-residency:

- **Navigation development**: learned navigator on GPU; Gemma through its
  measured llama.cpp placement; lightweight or CPU speech.
- **Voice laboratory**: Voxtral Realtime/TTS, PersonaPlex, Moshi, or Fish on
  GPU under their own license and memory profiles; classical navigation on CPU;
  no large learned navigator.
- **Offline navigation evaluation**: simulator/evaluator and one navigation
  model on GPU; speech disabled.
- **Embodied-grounding shadow**: RoboBrain 2.5 4B plus the rendered-camera
  grounding/progress harness; Gemma, speech, and learned navigation disabled;
  classical navigation remains the replay authority. Its 9.67 GB file size is
  only a static-weight fact, so admit the complete process from measured peak
  VRAM rather than assuming co-residency.
- **Classical production baseline**: reasoner plus classical navigation;
  optional smaller TTS selected from a license-reviewed deployment profile.

At startup, reserve memory, warm each model, run a health inference, and reject
an impossible profile. During a mission, do not evict and reload multi-gigabyte
models on the critical path. Record model load, first-token, first-audio, and
navigation inference latency separately.

## Concrete experiments

### Brain ablation matrix

Run the same frozen instruction suite under:

| ID | Router | Conversation | Complex planner | Status and isolated question |
| --- | --- | --- | --- | --- |
| B0 | Legacy reviewed grammar | Gemma one-turn decision | Immediate tool limit | Historical compatibility baseline only; do not restore its weaker long-task semantics |
| B1 | Deterministic `IntentFrame` | Gemma short-budget mode | Same Gemma in PlanIR mode | **Implemented incumbent.** Full CUDA passed 5/5 with 5,657.459 ms warm median usable-plan latency; 4/4 supported plans passed the deterministic headless gate. Conversation calibration parsed 10/10 and passed 6/10 machine cases/9/10 structured safety, but human quality, moving-owner follow, and hardware remain unscored. |
| B1-S | Deterministic `IntentFrame` | Gemma short-budget mode | Same Gemma in PlanSketch mode | **Measured and rejected for now.** Median full call fell to 2,037.060 ms with 153 completion tokens and 417 output bytes, but semantic acceptance regressed to 3/5. Develop on a disjoint corpus before any new frozen confirmation. |
| B1-MTP | Deterministic `IntentFrame` | Gemma short-budget mode | Same Gemma target plus matching MTP assistant | Runtime-only hypothesis: does verified speculative decoding improve full-plan latency with output/quality parity and acceptable VRAM? |
| B2 | Fine-tuned FunctionGemma route selector plus deterministic `IntentFrame` binder | Gemma short-budget mode | Gemma PlanIR mode | Router-only change: does one bounded learned route proposal improve recall without worse unsafe-route false positives, abstention, calibration, or tail latency? The model receives no motor tools and authors no trusted provenance. |
| B3-I | Deterministic `IntentFrame` | Ministral 3 8B Instruct short-budget mode (dialogue-only subtest) | Ministral 3 8B Instruct PlanIR mode (planner-only subtest) | **Measured and rejected as incumbent.** 35/35 CUDA layers and 101.944 ms conversation TTFT were real, but conversation fell to 5/10 machine cases and PlanIR to 3/5; complete response/plan latency did not beat Gemma. No combined activation. |
| B3-R | Deterministic `IntentFrame` | Gemma short-budget mode | Ministral 3 8B Reasoning PlanSketch mode | **Compatibility gate failed; rejected at this boundary.** Exact 35/35 CUDA placement was valid, but the predeclared first frozen case produced malformed JSON, exhausted 1,024 tokens, and took 12,262.204 ms. No full-suite replay or post-hoc contract tuning. |
| B3 | Deterministic `IntentFrame` | Gemma short-budget mode in a separate dialogue-only subtest | `gpt-oss-20b` PlanSketch/PlanIR replacement profile, with Gemma unloaded | First prioritized hardware-plausible general-reasoning challenger: after exact Harmony/runtime/GPU admission, does it improve held-out semantics or accepted-plan latency? This row does not assume co-residency or robotics specialization. |
| B4 | Deterministic `IntentFrame` | Gemma short-budget mode | Qwen3.6 PlanSketch/PlanIR mode | Secondary planner-only challenger: does a larger multimodal MoE materially improve grounded plans enough to justify its memory cost? |
| B5 | Deterministic `IntentFrame` | deferred dialogue challenger; Qwen3.6 is the first named candidate after conversation-v2 is frozen | Gemma PlanIR mode | Dialogue-only change with the planner fixed: does blinded human companion quality, interruption/turn-taking, persona consistency, false-action-promise rate, TTFA/full-call tails, and concurrent-queue behavior improve? Ministral Instruct's first calibration did not clear the machine gate. Qwen3.6 receives no admission or download priority until the disjoint rubric and isolated memory/runtime profile exist. |
| B6 | Winning router | winning conversation model | winning planner | Combined confirmation only after every selected single-component row has isolated its causal gain |

Changing router and planner in the same challenger run would make any gain
uninterpretable. Keep the raw transcript, prompts, schemas, snapshots, tasks,
seeds, decode budgets, and hardware profiles identical except for the component
under test. A PlanIR-to-PlanSketch comparison necessarily changes the output
schema, so compare admitted semantic and embodied equivalence after deterministic
expansion as well as raw size. Run cold and warm trials and preserve failures
rather than retrying them away.

FunctionGemma training data should include:

- direct commands, compound tasks, pure conversation, affect-only statements,
  ambiguous references, cancellations, and corrections;
- active-task conflicts such as a joke during a road crossing;
- adversarial scene text and quoted commands that must not execute;
- ASR errors, incomplete turns, and paraphrases; and
- a held-out split by speaker, phrasing family, location, and task template.

Measure route macro-F1, safety-weighted false positives, abstention behavior,
expected calibration error only for a score with a defensible probabilistic
interpretation, and p50/p95/p99 router latency. The current deterministic
router's hand-assigned confidence constants and any model-authored confidence
field are metadata, not calibrated probabilities. If the admitted learned
runtime cannot expose suitable evidence, use class-specific held-out thresholds
or ensemble/conformal evidence and treat uncertainty as
`clarify_or_abstain`. A wrong confident action route is more costly than an
unnecessary escalation.

The plan/companion suite should freeze at least these behavior families and
their paraphrases:

- enter a detected sidewalk and verify that the robot has stopped off-road;
- wait near a lamppost within the system-owned vicinity tolerance, not in the
  road;
- complete one small collision-free orbit around the visible owner;
- move five bounded steps away, follow directly, and form behind a moving owner;
- clarify an absent/ambiguous target and refuse evaluator-only or coordinate
  requests;
- defer a bow/chuckle/leg gesture during a critical crossing, while allowing a
  safe overlapping vocal response;
- revise an active task at a checkpoint and honor stop/manual/E-stop
  immediately; and
- enter a deterministic safe-stop/pose procedure when trusted battery state is
  critical, while never inventing battery data when it is unavailable.

For every turn, score exact route, schema validity, validator disposition,
selected skill sequence, system-compiled invariant/precondition/resource
correctness,
clarification, unsupported-world-fact rate, accepted-plan latency, spoken
promise consistency, and final embodied outcome. Conversation-only turns also
need blinded human or frozen-judge rubrics for relevance, warmth, persona
consistency, verbosity, and interruption handling. Model promotion requires a
paired improvement with confidence intervals or bootstrap intervals on the
frozen confirmation set; the current five-case semantic pass is not enough.

### Navigation ablation matrix

| ID | Semantic/learned proposal | Metric planner and safety | Purpose |
| --- | --- | --- | --- |
| N0 | Existing semantic resolver | Current global/local LiDAR stack | Baseline |
| N1 | Existing resolver | A* plus improved local planner/safety | Establish strong classical floor |
| N2 | CityWalker in shadow mode | N1 remains authoritative | Measure candidate validity without risk |
| N3 | Accepted CityWalker waypoints | N1 validates/repairs every proposal | Urban learned challenger |
| N4 | CE-Nav Go2 checkpoint in shadow mode | Same N1 safety envelope | Cross-embodiment local-controller challenger |
| N5 | S2E released BC checkpoint | Same N1 safety envelope | Closed-loop visual waypoint challenger; do not claim unreleased RL-policy results |
| N6 | InternVLA-N1 adapter | Same N1 safety envelope | Strong offline research comparison |
| N7 | NaVILA adapter | Same N1 safety envelope | Go2 research comparison |
| N8 | VAMOS high-level planner plus a newly trained Go2 affordance model, shadow-only | Same N1 camera/LiDAR projection and safety envelope | Test semantic proposals and embodiment rejection without reusing Spot/Hound affordance weights or imitating Jackal behavior |
| N9 | RoboBrain 2.5 4B image-point/grounding and progress proposals, shadow-only | Existing semantic resolver and N1 remain authoritative; LiDAR projection and freshness checks reject every unsafe/stale point | Test whether an open embodied VLM improves sidewalk/lamppost grounding or task-progress detection without confusing a static image point with a navigable trajectory |

Do not modify a benchmark's behavior or reveal evaluator-only state to Parcel.
Adapters translate sensors, goals, and actions; the production dog behavior and
safety interfaces stay unchanged. Separately, run each viable challenger
through a versioned ABotN-Bench adapter for collision-aware, social-rule-aware
PointGoal/POI behavior; evaluator walkability annotations must not enter the
production policy. Promote a model only if it improves held-out semantic task
success or navigation efficiency without worse collision, clearance, deadline,
or recovery results.

Robostral Navigate has no public checkpoint linked by its official sources, and
Mobility VLA depends on proprietary Gemini plus a prebuilt tour graph. They stay
outside executable N-rows until a reproducible artifact exists; architecture
similarity is not a benchmark result.

### Voice ablation matrix

First compare Whisper against Voxtral Mini 4B Realtime as the ASR component of
the same cascaded transcript path. Separately compare admitted TTS choices,
including Voxtral TTS only in noncommercial research, and then compare the
winning cascade against PersonaPlex or Moshi in a voice-only laboratory.
Evaluate interruption pickup, false turn-end, time to final transcript, time to
first audible response, semantic consistency, backchannel quality, echo
robustness, GPU admission, and action-transcript agreement. Motion requests
always use the trusted planning path in every condition.

## Evaluation and promotion criteria

### Language and plan quality

- route macro-F1 and calibrated abstention;
- JSON/schema validity and retry rate;
- correct skill, semantic target, spatial relation, tolerance, and the effective
  system-compiled invariants (plus rejection of unknown advisory labels);
- clarification when the target or reference is genuinely ambiguous;
- hallucinated-object and unsupported-world-fact rate;
- plan acceptance, recovery, and terminal-success accuracy; and
- consistency between what the dog says and the plan the executive accepted.

### Embodied task quality

- task success and success weighted by path length where applicable;
- collision rate, minimum clearance, and road/sidewalk semantic violations;
- target vicinity/relation success rather than exact-coordinate overfitting;
- orbit completion, formation error, owner reacquisition, and dynamic-agent
  avoidance;
- progress stalls, replans, recoveries, and timeout reason;
- BARN, Habitat, or other benchmark metrics reported separately under their
  exact official protocols; and
- a frozen MetaUrban dynamic-pedestrian suite, followed by separately labeled
  DynaBARN evidence when available; static BARN never substitutes for either.

### Conversation and companion quality

- human-rated relevance, naturalness, persona consistency, and empathy;
- appropriate versus intrusive social gestures;
- action-promise consistency;
- successful barge-in and correction handling; and
- continuity while following or navigating.

### Latency and resource quality

- `UserQueryEndToFirstReasoningResponse`;
- `UserQueryEndToAcceptedPlan`;
- `UserQueryEndToFirstResponse`, split into first log and first spoken audio;
- router, prompt construction, prefill, first-token, full-decode, validation,
  and replanning latency;
- perception age, learned-navigation inference, global plan, local plan, safety
  shield, controller dispatch, and feedback latency;
- control deadline misses and watchdog stops; and
- GPU memory, utilization, load time, CPU load, and model-profile admission
  failures.

Use median, p95, and p99, plus cold/warm and success/failure splits. A fast
spoken acknowledgment is not equivalent to a fast accepted plan, so both must
remain visible on the latency dashboard.

The separate `/latency` dashboard and `/api/latency` endpoint are implemented.
They retain bounded per-turn query/response/status rows, stage-relative
latencies, component distributions, and definitions. Planning now records:

```text
query_end
  -> intent_routed
  -> observation_snapshot
  -> plan_first_output
  -> plan_response (complete parsed PlanIR)
  -> plan_validated
  -> plan_accepted
  -> semantic dispatch / logged or spoken response
```

The corresponding named metrics include
`UserQueryEndToFirstPlanOutput`, `UserQueryEndToAcceptedPlan`,
`IntentRouting`, `ObservationSnapshotBuild`, `PlanTimeToFirstOutput`,
`PlanDecode`, `PlanValidation`, and `PlanAcceptance`, plus rolling component
metrics for `IntentRouter`, `ObservationSnapshotBuild`, `PlanModel`,
`PlanValidation`, `PlanAcceptance`, and `ExecutiveTick`. The tracker reports
p50, p95, and p99 rather than only a mean and separates terminal status.

Two caveats prevent misleading e2e claims. `QueryEndToFirstSpokenAudio` is
currently the first software audio-sink handoff, not an acoustic presentation
timestamp. And until continuous capture/VAD/endpointer timing is wired to the
commissioned microphone, text submission time is not a measured speech
end-of-utterance. Keep both limitations visible on the dashboard.

### Official-eval feasibility and the top-decile claim

Parcel's frozen portfolio defines “top 10% across all evals” as a conjunction:
every adopted ranked evaluator must independently satisfy its exact rank rule,
and every product/safety gate must pass. Scores cannot be averaged across
benchmarks. Current status is:

| Adopted target | Frozen top-decile boundary | Current evidence | Eligibility and GPU reality |
| --- | --- | --- | --- |
| [Habitat 2020 PointNav](https://aihabitat.org/challenge/2020/) test-challenge | 6 published entries; Parcel operational rule requires rank 1 and displayed SPL at least 0.21 | The exact 23-layer runtime is materialized at 87,944 entries. Import baseline02 passed one-device CUDA, EGL 1.5, and Habitat-Sim 0.1.4. The next immutable public non-gated test-asset smoke constructed the simulator, loaded the Skokloster scene/navmesh, rendered four distinct 128x128 RGB-D frames, and executed forward/left/right with zero collisions and 0.250088 m displacement in 1,318.900083 ms. It read only episode 0's start transform—no goal, Parcel policy, STOP, task, evaluator, or metric. | Historical challenge is closed. Public `val_mini`/`val` can be official-code public validation only, never rank evidence. Licensed `Pablo.glb` remains absent. The scene/action smoke is deliberately non-Habitat-2020 and provides no SR, SPL, soft-SPL, score, rank, or top-decile evidence; Docker Engine and NVIDIA Container Toolkit were not required for the cache-only Bubblewrap path. |
| [Habitat 2020 ObjectNav](https://aihabitat.org/challenge/2020/) test-challenge | 6 published entries; rank 1; displayed SPL at least 0.10, tied at displayed precision | No eligible Parcel run; a real RGB-D category perception policy and licensed Matterport3D data are still required | Historical challenge is closed, and the displayed tie would require official rank confirmation. Simulator semantic truth may not replace perception. |
| [BARN 2026](https://people.cs.gmu.edu/~xiao/papers/barn26_report.pdf) simulation qualifier | 17-entry registered/participating cohort with 12 published numeric scores; Parcel's operational derivation requires rank at most 2 and official mean score at least 0.4880 | Parcel native proxy: cached v3 at 44%/0.106267, zero collisions, one trial on fixed public 50, unpromoted. The disjoint single-use V8 development proxy passed 16/19 gates but both arms were 0/30 success/metric zero, so V8 was rejected without authorizing or evaluating its holdout. Independent runtime smoke: untouched upstream MPPI succeeded on public world 0 at 0.1802 with no collision/timeout. The earlier Parcel hook classified `policy_no_translation`; calibrated transport v2 then removed 100 self returns on its first frame, passed liveness, entered `Trial running`, translated several metres, and produced evaluator row `0 0 0 1 100.0070 0.0000`. | None is eligible: both native runs are Go2-oriented planar proxies; upstream MPPI is not Parcel; and Parcel's only terminal row is a one-world failed compatibility baseline through a diagnostic Bubblewrap/PRoot rootfs, not the tested Singularity/SIF path or 50 worlds × 10 trials. No eligible public-protocol mean or hidden organizer score exists. The event deadline passed; official attestation remains external. Official simulation promised CPU and the physical final no GPU, so Parcel must stay CPU-capable. |
| [3WE](https://3we.org/benchmarks) PointNav/ObjectNav/Exploration | No defensible backend-specific top-decile cohort: the pinned snapshot has two Gazebo PointNav rows and one row for each other task/backend cohort | The source-only audit is bound to commit `6073a1bd0a30b6ca1348027ac35b05832b97bfe9` and found 13 critical contract blockers. It imported no upstream Python, started no simulator, ran no Parcel policy, and emitted no score. | All three targets remain claim-blocking and `not_admitted`. The runner owns wheeled Nav2; seed/reset/timeouts and PointNav success/SPL are invalid; ObjectNav leaks hidden coordinates; Exploration and Isaac are stubs; office assets disagree; schemas/results diverge; and no neutral policy hook or rankable cohort exists. Building an adapter now would preserve invalid semantics or change the evaluator/embodiment. |

These are Parcel's operational rank cutoffs on displayed historical cohorts,
not estimates of a population percentile or current state-of-the-art standing.

The GPU answer is therefore benchmark-specific. Parcel's Gemma/Ministral brain
evaluations run on the RTX 5000 Ada, and Habitat's exact CUDA/EGL simulator and
render/action boundary has passed. BARN V8 intentionally ran on CPU: the official
simulation environment was CPU-oriented and the physical final specified no
GPU, so GPU dependence would reduce protocol relevance rather than improve it.
The current 3WE snapshot has no admitted evaluator at all, and its advertised
Isaac path is a stub; calling it “GPU-capable” would not create a valid metric.
Future MetaUrban/URBAN-SIM training and simulation can use the GPU, but each
result must record whether acceleration belongs to the simulator, the learned
policy, or both.

### Why the current 3WE revision is quarantined rather than adapted

The current [3WE benchmark page](https://3we.org/benchmarks) and
[leaderboard documentation](https://docs.3we.org/leaderboard/) describe three
100-episode tasks on `office_v2`, official seeds 0–99, fixed task timeouts, and
separate backend tracking. The GitHub `main` head rechecked on 2026-08-03 is
still the Parcel-pinned commit. That makes the source stable enough to audit,
but not correct enough to score.

The fail-closed
[report](../evals/external/results/threewe/threewe-contract-audit-20260803-baseline01.json)
`threewe-contract-audit-20260803-baseline01` found 13 independent admission
blockers:

1. The CLI has no seed option; PointNav and ObjectNav use one seed-42 RNG,
   sample goals with replacement, keep one robot alive across episodes, and do
   not apply the documented start/reset sequence.
2. Implemented PointNav/ObjectNav/Exploration limits are 30/60/120 seconds,
   not the documented 60/120/180 seconds.
3. PointNav declares a 0.5 m success radius but trusts the backend boolean. The
   ROS backend marks any completed Nav2 future successful without checking its
   status or final radius.
4. ROS supplies straight-line start-to-final displacement as path length; it
   never integrates the traveled trajectory. Its “optimal” length is also
   Euclidean rather than geodesic, so obstacle detours are invisible to SPL.
5. ObjectNav independently samples a category and a pose, never presents the
   category to an agent, never applies the generated start pose, and passes
   hidden target coordinates directly to `Robot.move_to`. It is privileged
   PointNav with a decorative category, not semantic ObjectNav.
6. Gazebo/ROS Exploration explicitly sends no navigation commands and samples
   the occupancy grid after at most one second; mock Exploration returns 1.0
   coverage. Neither evaluates an exploration policy.
7. `BenchmarkRunner` constructs 3WE `Robot` itself and delegates to the
   backend's `move_to`/`explore`; no immutable external-agent observation/action
   boundary exists.
8. The Isaac/GPU backend returns constant observations, ignores velocity
   actions, reports arbitrary goals instantly reached, and suppresses both
   missing-Isaac import failures. A capable RTX cannot turn that stub into a
   GPU simulator evaluation.
9. The shipped body is a four-wheel mecanum chassis using a holonomic planar
   move plugin. Swapping in Unitree Go2 physics would change the embodiment,
   not merely adapt Parcel's I/O.
10. `office_v2` metadata says 20x15 m while the enclosed Gazebo world is 15x10
    m in positive coordinates. Fifteen of 20 starts and 34 of 50 goals are
    outside or on that enclosure boundary; sensor bridge paths refer to
    `empty_world` while the SDF world is `office`.
11. Documentation requires nested metrics/software, the runner emits a third
    flat report, and the validator expects a different flat schema. Every one
    of the six static leaderboard rows fails that implemented validator; the
    `submit` command only validates and prints rather than uploading.
12. First-party docs, static data, and comparison code give three different
    office PointNav baselines: SR/SPL 0.85/0.72, 0.915/0.87, and 0.82/0.65.
13. Comparable cohorts are too small to define a percentile: two Gazebo
    PointNav entries and one each for Gazebo ObjectNav and Exploration; the
    remaining PointNav rows mix Isaac and mock.

Therefore the static best-row numbers are unverified references, not targets,
and no 3WE run is authorized yet. The correct next step is not to monkey-patch
`threewe.Robot` or rewrite its evaluator around Parcel. Admission requires an
organizer-published immutable runner with independent episode manifests,
correct success/path/coverage math, semantic ObjectNav without coordinate
oracle access, a real simulator, a neutral agent hook, one submission schema,
and sufficiently large backend-specific cohorts with a ranking metric and tie
rule. If that future benchmark mandates its own mecanum body, it may still be
useful as an algorithm-transfer diagnostic, but it cannot replace the Go2
embodiment-preservation gate.

The Habitat 2020 adapter intentionally receives RGB-D, a static start-relative
PointGoal, and issued-action history but no simulator pose, navmesh, shortest
path, collision truth, world-coordinate goal, or evaluator metrics. The BARN
ROS 2 adapter receives the official scan/odometry/goal topics and publishes
forward/yaw commands for the differential-drive Jackal; it does not remove
lateral motion from Parcel's Go2 production interface. Changing evaluator code
would make the result less useful and less eligible, so translation stays in
the adapter.

The immutable Habitat contract smoke
`habitat20-contract-smoke-20260803-baseline02` now demonstrates that the
archived Python 3.6 process can exchange start/action JSONL with the modern
Parcel sidecar across 30 public episode identifiers. The deterministic stub
returned ten forward, ten left, and ten right actions with 0.123 ms median and
0.233 ms p95 start-plus-action bridge latency. It used no scene, RGB-D pixels,
collision physics, or success evaluator and therefore cannot report SPL,
soft-SPL, or navigation intelligence. This is exactly the boundary evidence
needed before licensed/runtime work, while preventing an adapter smoke from
being laundered into a model score.

The canonical follow-on immutable image evidence
`habitat20-image-preflight-20260803T141555Z` resolves one narrower uncertainty:
Docker Registry returned raw manifest digest
`sha256:761ca223...c52b` and config digest
`sha256:75e366...db5e`, exactly matching the frozen contract. All 23 unique
layer descriptors sum to 3,210,119,745 compressed bytes; the config declares
Linux/amd64, CUDA 10.1.243, Python 3.6 creation, and the challenge-2020
Habitat-Sim build. On this host, driver 595.84 reports an RTX 5000 Ada with
compute capability 8.9 and 32,760 MiB, while `/dev/nvidiactl`, `/dev/nvidia0`,
`/dev/nvidia-uvm`, `libcuda.so.1`, and `libEGL_nvidia.so.0` are present. The
report SHA-256 is
`ad8b46967f43215377468ce967bfbd3f15fd7dc6199600983229bf79dd592cee`.
This was deliberately a descriptor/prerequisite probe: zero layer bytes were
downloaded, and no container, kernel, render, scene, evaluator, or Parcel
policy ran. In isolation it supported a content-addressed layer fetch as the
next public-test-asset step, but no CUDA/EGL compatibility, navigation metric,
official rank, or top-decile claim.

That next step is now complete. The materializer verified and applied all 23
layers, then recorded a deterministic inventory of 87,944 entries: 8,996
directories, 72,482 regular files, 6,466 symlinks, and 7,925,803,803
regular-file bytes. The canonical tree SHA-256 is
`65caf2c814dd7d26b2430d65fcae97dc6ddd2cad279e79d5b085180f3b7be9ba`.
Baseline01 is intentionally retained under report SHA-256
`8c764f0aaeb532c4fac4391313f6c11774a8755893daaa8a83c7d77eae53b7f0`
and ledger ID `habitat20-oci-gpu-import-smoke-20260803T144820Z`: it initialized
one CUDA device, then failed before EGL initialization or Habitat import because
the injected host GLVND client required GLIBC 2.33 against the image's GLIBC
2.27.

Corrected baseline02 retained the image's compatible GLVND clients, injected
only ABI-audited NVIDIA vendor libraries, and passed: one CUDA device, one EGL
1.5 device, and Habitat-Sim 0.1.4 imported under Python 3.6.10 in 561.432697 ms.
The passing report SHA-256 is
`be4a6acba149bee47661936ee5a90947b39e22313a411f02d17eeff839c49424`,
the runner SHA-256 is
`4526fdcc3a66864a5792a188a387c7ef27ebe4c3258f92472113cf945e60607c`,
and the ledger ID is
`habitat20-oci-gpu-import-smoke-20260803T145414Z`. This proves only the exact
archived-image CUDA/EGL/Habitat-Sim import boundary. It constructed no
simulator, loaded no scene, rendered nothing, executed no GPU kernel or
navigation episode, ran no evaluator, and emitted no metric, score, rank, or
top-decile evidence.

There is one license-boundary nuance. Habitat-Sim's official data utility
publishes `habitat_test_scenes` plus `habitat_test_pointnav_dataset` without a
credential or click-through acceptance step. Those assets can support a real
GPU renderer/action compatibility smoke now that the archived import boundary
works, but
they are not Gibson `Pablo.glb` or the frozen 2020 `val_mini` protocol. A result
on them must remain a rank-ineligible compatibility result with no challenge
SPL claim. Replacing the terms-gated scene with these convenient assets inside
the adopted evaluator would change the evaluation population and is forbidden.

That separate compatibility tier is now measured. The frozen scene repository
is public and ungated at commit
`910c783fb954da8497ea5f811b843a76590ddddc`; its card specifies
CC-BY-NC-4.0. The anonymously distributed official PointNav fixture archive is
hash-, ETag-, and version-bound in ignored cache but carries no separate
license file, so Parcel makes no public-domain or general-redistribution claim.
Inside a read-only, network-disabled Bubblewrap sandbox, immutable run
`habitat-test-assets-gpu-scene-smoke-20260803T152317Z` reverified the 23 image
layers and 87,944-entry rootfs, initialized one CUDA and one EGL 1.5 device,
constructed Habitat-Sim 0.1.4, loaded the Skokloster scene/navmesh, and rendered
four distinct 128x128 RGB-D frames. Forward, left, and right produced zero
collisions and 0.2500881936561302 m displacement in 1,318.900083 ms. Report
SHA-256 is
`aed6afcb2e9af98f4f6ed8c3a3f636845e70a34b14057b1904493f8530330137`.
Only episode 0's start transform was read: its goal, geodesic distance, STOP
task action, Parcel policy, Habitat-Lab task/evaluator, and all navigation
metrics were excluded. This proves the GPU scene/render/discrete-action
boundary—not Habitat 2020 compatibility, navigation intelligence, or rank.

For reproducibility, the archived Habitat source is pinned at
`ddf1575532aecc4df2f4cd4c5db173b8eada3e1e`; the official BARN ROS 2 source is
pinned at `d6c575b51e477bd524d634e12cffeb34036fcd1e`. Those pins make a local run
repeatable. They cannot reopen a historical leaderboard or substitute public
worlds for organizer-held hidden worlds.

For BARN, the exact 52,091,122-byte `4.3.0-noble` package (SHA-256
`0d165a619a4d7ff094e041c59e1f17490b08c6bd8705378db474c823b0efc0e8`)
was downloaded into an ignored cache, verified, and extracted without package
installation or maintainer scripts. A read-only Bubblewrap probe reports the
expected version. The upstream-tested Singularity execution path still fails
closed because this host restricts unprivileged user namespaces through
AppArmor, root UID mapping fails, and
`newuidmap`/`newgidmap` are absent. The extracted runtime can assemble a tiny
SIF but cannot execute a SIF, sandbox, or the official definition's `%post`.
That remains the exact upstream-tested Singularity/SIF blocker.

A narrower, explicitly diagnostic fallback succeeded without changing the
host. Bubblewrap assembled and accessed a pinned `ros:jazzy` rootfs; a pinned
PRoot binary handled only ownership-sensitive `dpkg --configure` phases.
`rosdep check` and upstream `colcon build` passed, critical evaluator files
remained byte-identical, and the unchanged upstream MPPI world-0 smoke produced
the checksum-bound row described above. The doctor verifies the PRoot/rootfs,
package/build outputs, source hashes, evidence/raw binding, and hard-false
official/Parcel/top-decile claims. This makes the desktop useful for iterative
ROS/Gazebo compatibility work while preserving the distinction: it is not a
SIF, not Parcel's controller, not the full public protocol, and not score
evidence.

Before the calibrated repair, Parcel's own hook supplied a causal startup
diagnosis but no navigation result. Corrected bundle `ea6904...` started the policy and command bridge but
remained below the evaluator's 0.1 m translation threshold for the 180-second
outer bound. Classifier-enabled bundle
`5fbccdab524238180c8845e68a3db116d0575b53d7a2d783a1ca6090c4aa8e5f`
then ran exactly once on public world 0. At 10.007 seconds it had received 307
odometry messages and 284 scans and emitted 62 commands; odometry showed
1.052376 rad yaw response, proving the command path was live. It measured zero
forward opportunity and zero XY response and exited `policy_no_translation`
before `Trial running`. The evaluator wrote no terminal row, so no result or
ledger entry exists.

Pinned robot geometry plus an offline causal replay explains the exact
rotate-only signature. The official 360-degree, 720-ray front LiDAR is mounted
0.12 m ahead of the base, while a radius-0.05 m center cylinder intersects its
scan plane. Rear rays can therefore return from the robot itself at about 0.07
m. The transport discarded `frame_id`/extrinsic and integrated every ray from
the base center. Its 0.9 hit log-odds exceeded the 0.65 occupied threshold;
0.32 m body radius plus 0.10 m hard margin then inflated those false hits
around every start neighbor. A* cleared only the start cell, expanded one node,
returned `no_path`, and recovery selected the observed 0.18 rad/s yaw command.
`obstacle_stop` corroborated the near hit but did not zero velocity—the planner
had already requested no translation.

With otherwise identical current code, a clean analytic world-0 scan had a
2.1013 m minimum range and produced `vx=0.09` plus a partial `grid_track` route.
Adding only the 0.07 m self arc reproduced the logged `vx=0`, `yaw=0.18`,
`grid_recover_scan status=no_path|obstacle_stop`, and one expanded node. This
also explains why the native proxy missed the defect: it raycasts only world
geometry from the body center over 270 degrees, not the ROS robot mesh from a
front-offset sensor. The static goal and rolling-window clip are not causal;
the clean replay plans forward.

The repair is calibrated sensor normalization, not weaker safety: transform
finite endpoints through a timestamped LiDAR-to-base extrinsic, invalidate
only hits inside a configured body self-mask, and never convert those occluded
rays to infinity/free space. Preserve nearby external returns and fail closed
on missing/stale TF or unsynchronized odometry. Lowering inflation, clearing a
ring, cropping the rear field, or modifying evaluator geometry would hide the
bug and weaken the production contract. No extra BARN run was made for this
diagnosis. Pure-core regressions then reproduced and removed the occupied-ring
failure before exactly one new run was authorized.

That calibrated-v2 run is
`barn-ros2-parcel-20260803T155459Z-world0-75f7ff4d`, bound to package SHA-256
`75f7ff4dfbf45d36f67cdf3eb3eac6a7e9d05abf48350db449ca23d93b597813`.
Its first live scan removed 100 self returns, its first policy command was
forward tracking, liveness passed, and the official-code evaluator began a
trial. The robot made roughly 2.2 m of net XY displacement before stopping
near `(-2.66, 5.28)`; the evaluator eventually emitted
`0 0 0 1 100.0070 0.0000`. This closes the startup compatibility defect but
opens a distinct mid-episode safety-profile defect. A read-only replay of the
immutable bundle, exact public world geometry, calibrated 360-degree LiDAR,
and ideal unicycle motion stalled at `(-2.6221, 5.2353)`, 0.059 m from the live
terminal pose. At onset the upstream navigator still proposed `vx=0.5647` in
`grid_track status=planned`; the nearest normalized cluster was 0.8592 m away,
while the packaged collision shield's 0.8 m base threshold plus 0.0678 m
reaction-distance term demanded 0.8678 m. The shield therefore zeroed forward
motion. Replay counted 800 consecutive `obstacle_stop` results before the
progress watchdog emitted `navigation_no_progress` at step 881. The watchdog
terminated the deadlock but did not cause its onset, and neither `no_path` nor
rotate-only recovery reproduced at the matching pose. The final public-world
geometry had 0.491707 m signed body clearance and the robot was only about
0.014 m from the reference path; these evaluator-private diagnostics were
computed after the run and were never policy inputs.

This is strong causal evidence, not a live command trace: the immutable node
logged only its first policy command. It isolates a profile mismatch between
the ROS package's legacy 0.8 m obstacle-stop setting and the Jackal-scale
eval-only 0.38 m profiles. It does not license selecting a lower threshold on
consumed world 0, and it says nothing about the correct Go2 footprint/speed
envelope. Reproduce the comparison on a newly frozen generated corpus with
explicit footprint and reaction-distance accounting before promotion.

The immutable run bundle still uses the base-origin regular `BarnObservation`
contract: v2 transforms endpoints and conservatively reprojects them, while
the frozen downstream adapter cannot retain the true per-ray origin or
distinct odometry timestamp.
That residual must become a shared production sensor contract after the
frozen native evidence is closed. It does not justify weakening the mask,
inflation, or safety shield, and consumed world 0 is not a tuning set.
After the evaluator had already written its terminal row and initiated
shutdown, the immutable bundled node attempted a final zero publish through an
invalidated `rclpy` context and printed a teardown-only stack trace. The
working tree now checks context liveness before that cleanup publish; this
does not alter or retroactively replace the content-addressed run, and no
second episode was executed for the cleanup change.

The pinned BARN ROS 2 helpers also contain two documented discrepancies:
`test.sh` starts at index 7 and therefore skips the first seven of the stated 50
public indices, while `report_test.py` uses a stale `4*OT` lower clip instead of
the runner's current `2*OT`. Do not “fix” evaluator semantics and then call the
result official. For compatibility work, invoke the explicit documented world
set, preserve raw runner outputs, report the discrepancies upstream, and leave
organizer attestation as the only official authority. Habitat similarly fails
closed if Parcel requests reverse or lateral motion because its frozen
LoCoBot-style action space only admits stop, forward, and discrete turns;
silently projecting unsupported actions would change the controller being
evaluated.

GPU support is therefore benchmark-specific, not a checkbox. Learned
navigation, MetaUrban rendering/training, and Habitat inference can use this
GPU when the exact protocol permits it. BARN's current classical policy and
official target must stay CPU viable. Every report must record CUDA/driver,
device, model placement, simulator placement, and peak memory so a GPU speedup
cannot silently change observations, actions, or timing semantics.

### Hill-climbing without benchmark distortion

Classify every proposed optimization before running it. The class determines
which incumbent must be replayed and which claim, if any, the result can change:

| Change class | Examples | Required interpretation |
| --- | --- | --- |
| Evaluator/harness | adapter translation, simulator bridge, metric code, timing instrumentation | Cannot be credited as policy intelligence. Re-run the unchanged incumbent through old and new harnesses on eligible public/dev inputs, explain any metric delta, version the evaluator, and never rewrite an immutable result. |
| Semantic planner | prompt, PlanSketch/PlanIR contract, language weights, router classifier | Freeze original transcript, trusted observations, skill catalog, compiler/validator, and hardware profile where possible; score route/plan semantics and downstream embodied tasks. |
| Navigation proposal | semantic target, waypoint, path, or recovery proposer | Run shadow first; the same camera/LiDAR projection, classical planner, safety shield, and controller must validate both incumbent and challenger. |
| Go2 affordance/controller | VAMOS-style affordance model, local tracker, locomotion or gesture controller | Train and evaluate against Go2 geometry/dynamics and commissioned interfaces. Spot/Hound or BARN Jackal behavior cannot be relabeled as Go2 evidence. |
| Runtime-only | cache/search reuse, kernel/backend, scheduling, quantization, speculative decode | Require output/decision parity or predeclared quality tolerance, replay the incumbent, and credit only resource/latency change unless task outcomes also change under a separately classified policy modification. |

Any adapter or harness change requires an unchanged-incumbent replay before a
challenger comparison; otherwise policy improvement and measurement drift are
confounded. Keep train/development/PR/confirmation/test scenarios frozen and
log every run ID, commit, model hash, adapter version, sensor contract, seed,
hardware profile, and metric. Organizer-hidden and untouched test worlds may
**never** become an RL reward, prompt-selection signal, recovery oracle, or
hyperparameter-development set. Public development worlds can provide reward
only under a predeclared training split; every reported confirmation remains
untouched until its one permitted use.

Do not average away a weak benchmark to claim “top 10% across all evals”; each
evaluation needs its own percentile and protocol. A candidate is promoted only
when the predeclared metric improves and all applicable conjunction gates pass:

1. evaluator validity and eligible provenance;
2. embodiment match, including Go2 rather than Jackal-specific behavior;
3. unchanged camera/LiDAR-only production sensor boundary and no privileged
   evaluator state;
4. no regression in E-stop, collision, clearance, resource arbitration,
   watchdogs, or dynamic-social safety;
5. acceptable warm/cold p50/p95/p99 latency, CPU/GPU admission, and memory; and
6. no regression in companion routing, plan semantics, interruption,
   action-promise consistency, or supported embodied tasks, plus a deployable
   license for the intended use.

## Recommended development order

### Phase 1: finish measuring the implemented brain

**Implementation status:** the versioned IntentFrame, PlanIR, PlanSketch,
ObservationSnapshot, and ExecutionResult contracts, deterministic router,
trusted envelope, semantic compiler, validator,
executive/resource/checkpoint logic, shared Gemma modes, fresh snapshot
revalidation, semantic runtime adapter, correction/interrupt path, and planning
latency stages are present. The 15-case companion brain suite remains a contract
regression floor. The live five-case `planner_quality_v2` semantic gate passed
5/5 on CPU and exact full CUDA; the GPU median usable plan is 5,657.459 ms. The
language run itself has zero physical episodes, while the separate deterministic
headless gate passed 4/4 supported cases and reported one honest unsupported
moving-owner-follow case. The compact PlanSketch GPU challenger cut median
full-call latency to 2,037.060 ms but passed only 3/5, so it is not promoted.
The first ten-case live conversation calibration is also recorded: Gemma
parsed 10/10, passed 6/10 machine cases and 9/10 structured-safety checks, and
has no human score. A 35/35-layer Ministral Instruct challenger improved median
TTFT to 101.944 ms but regressed to 5/10 conversation cases and 3/5 PlanIR,
with slower complete calls/plans; it is not promoted. Its separately measured
Reasoning sibling also remains inactive: a one-case frozen PlanSketch
compatibility gate failed before semantic scoring after 1,024 tokens and
12,262.204 ms. That is not a full-suite result.

**Remaining work before a new large model:**

1. Expand and freeze the language/plan suite beyond its five literal cases to
   paraphrase families, ambiguity, absent targets, critical-task deferral,
   social behavior, low battery, and adversarial scene text. Build conversation
   v2 from disjoint cases, let the deterministic router own intent labels, and
   add blinded human review rather than tuning on v1's lexical heuristics.
2. Keep PlanSketch unpromoted after its 3/5 full-CUDA result despite large,
   measured token/output/latency reductions. Turn its two failures into a
   disjoint development corpus, preserve raw/admitted artifacts, and require
   5/5-or-better semantic parity on a new untouched confirmation set before an
   embodied replay.
3. Run B1 repeatedly with the real model, cold and warm, and record plan
   validity, validation/acceptance, embodied success, TTFT/full decode,
   p50/p95/p99, CPU, GPU, and memory.
4. Retain CPU-only as the reproducibility floor and exact full CUDA as the
   measured accelerator baseline, then capture peak VRAM and test the matching
   Gemma MTP assistant only if `llama.cpp`/format compatibility is proven. The
   5.66-second full-CUDA warm median usable plan is still not production latency.
5. Add a moving-owner embodied v2 before claiming `FollowFormation`, and admit
   Pose/Gesture/critical-battery skills only after their runtime adapters,
   feedback verifiers, hardware safety rules, and tests exist. A schema entry is
   not an implemented behavior.
6. Before adding a second large model or duplex voice lane, replace the global
   non-E-stop model-turn lock with a per-turn cancellable request broker. Give
   E-stop, manual control, and system safety events strict priority; bound every
   queue; cancel stale plans on task revision; start with single-GPU serial
   admission; and admit multiple server slots only after explicit KV-cache,
   peak-VRAM, and GPU-reserve checks. Measure concurrent p50/p95/p99 plus first
   audio, first valid reasoning, and first accepted plan so a fast acknowledgment
   cannot hide planning queue delay.

### Phase 2: strengthen and confirm the navigation floor

1. Retain the selected `grid_v1` grid/A* incumbent. The 26 watchdog stops and
   two timeouts expose a mismatch between an unknown-admitting global path and
   an observed-only follower. Frontier v2 rescued no failures and was too slow;
   cached v3 removed that search cost but still held fixed-50 at 44% and rescued
   no failures. Detour v4 then rescued zero cases on its predeclared 30-world
   development split. Safe-valley v5 rescued one of 30 on a new generated
   development corpus, but added two timeouts and regressed the clearance floor
   to 0.072034 m, failing four frozen gates. Guard v6 then isolated extra
   clearance padding on fresh IDs 2000--2029: it improved mean clearance but
   tied 15/30 success and retained four timeouts, failing its zero-timeout gate.
   V4's sealed confirmation remained unconsumed; v5 IDs 1030--1049 and v6 IDs
   2030--2049 were never generated, opened, or authorized. All five recovery
   challengers remain deployment-disabled. Select any new recovery idea on a
   new development split before frozen confirmation.
2. Move rolling-grid integration/global planning off the 100 ms control critical
   path, enforce a bounded asynchronous deadline, and retain the last safe local
   behavior on a miss.
3. A/B the current rotate-first tracker against a small Nav2-derived MPPI,
   Regulated Pure Pursuit, or Graceful/velocity-smoothing challenger under the
   same `MidLevelCommand` contract.
4. Preserve first-class semantic success relations: `inside(sidewalk)`,
   `near(lamppost, 1m)`, `behind(owner, formation tolerance)`, and
   `orbit(owner, one winding)` with camera/LiDAR timestamps and provenance.
5. Retain BARN's documented `launch_navigation_stack` adapter boundary. The
   classifier-enabled run localized the original startup stall to discarded
   LiDAR extrinsics and robot self returns. Calibrated-v2 pure-core tests fixed
   that cause, and the one authorized ROS/Gazebo smoke passed startup and
   produced a real timeout row. A sensor-faithful replay matched its terminal
   pose within 0.059 m and reproduced the stall when the packaged 0.8 m
   collision profile suppressed 800 consecutive forward proposals; the
   watchdog was downstream, not causal. Do not tune or rerun consumed world 0.
   The v7 nearest-cluster `projected_speed_cap` experiment is retired
   unexecuted because a nearer tangential cluster can mask a farther
   positive-closing return. Do not generate it, reuse IDs 3000--3049, or report
   a v7 score. V8 then implemented the byte-isolated all-720-ray, yaw-swept
   shield and independent action certifier. Its one-shot development run passed
   all safety/provenance/latency gates but tied 0/30 success and metric zero, so
   it failed the three efficacy gates and is rejected. Do not rerun IDs
   4000--4029 or materialize its unauthorized 4030--4049 operational holdout.
   Retain the certifier design, but keep fresh hypotheses above the final
   shield. V9's initial c68 and supervisory-gap S1/S2 tracker challengers have
   now completed the paired training screen on IDs 5000--5009. S2 produced the
   first V9 training success and reduced label-independent liveness failures
   from ten to nine, but its immutable scratch gate failed seven checks: five
   policy stop latches, insufficient aggregate efficiency, excessive world
   5009 final distance, and excessive travel plus insufficient efficiency in
   worlds 5007 and 5009. All three challengers are rejected. Do not run S2 on
   the 100-world training corpus, expose development IDs 5100--5129, or
   materialize holdout IDs 5130--5149. Build any successor as a fresh
   content-addressed, one-factor training challenger against the exact V8
   experimental control under the
   same body-command, final-shield, and evidence contracts. RPP alone remains
   insufficient because it cannot choose a different corridor when its single
   path arc reaches the 0.8 m boundary. Test a 0.38 m Jackal-scale profile only
   as a separate one-factor treatment rather than combining it with the
   tracker change.
   Continue to require both a valid terminal
   evaluator row and the Parcel startup marker before writing result evidence
   or a ledger entry. Only after a successful, independently justified adapter
   smoke may Parcel run the explicit 50-public-world × 10-trial compatibility
   protocol. Keep it
   non-official: AppArmor UID-map restrictions still block the upstream-tested
   Singularity/SIF path, and hidden scoring requires organizer attestation.
   Habitat's exact public non-gated test-asset CUDA/EGL/simulator/render/action
   boundary now passes. Next connect Parcel's RGB-D adapter to a separately
   labeled, bounded non-challenge test task; acquire the licensed Habitat
   challenge scene only through the user's accepted terms,
   and keep every result's eligibility flag explicit.

### Phase 3: build the dynamic-city gate

1. Freeze richer seeded MuJoCo/headless crowd scenarios immediately.
2. Install MetaUrban in an isolated supported environment and implement a real,
   versioned camera/LiDAR/body-command adapter; do not present the current
   kinematic scaffold as vendor integration.
3. Freeze disjoint MetaUrban layouts, densities, behavior seeds, lighting/noise,
   and social-safety thresholds before using them for model selection.
4. Add Arena-Rosnav or an equivalent social-controller tier only after the
   primary MetaUrban gate is reproducible.

### Phase 4: learned navigation in shadow mode

Adapt the already-downloaded CityWalker checkpoint to timestamped RGB and log
its waypoint proposals beside the authoritative planner. Validate/repair every
proposal through LiDAR and reject stale trajectories. Only after CityWalker has
a positive held-out result and checkpoint terms are resolved should CE-Nav's Go2
checkpoint and S2E's released behavior-cloning policy receive isolated shadow
adapters. InternVLA-N1 and NaVILA follow as research-only comparisons because
their terms/stacks are less production-ready. VAMOS can follow only as a
noncommercial shadow experiment with a newly trained Go2-specific affordance
model; released Spot/Hound weights and BARN Jackal behavior are not Go2
controllers. In a separate semantic-only experiment, run the official
Apache-2.0 RoboBrain 2.5 4B checkpoint against a frozen rendered-camera
sidewalk/lamppost/owner-grounding and task-progress suite. Its 9.67 GB BF16
artifact is plausible on this 32 GB GPU in isolation, but the model's
image-point and trace outputs remain shadow proposals projected through LiDAR;
they are neither paths nor body commands. Robostral remains architecture-only
until a public checkpoint is linked. Never change evaluator rules or expose
privileged state.

### Phase 5: train or replace language specialists

Fine-tune FunctionGemma as a route-function selector on Parcel's bounded labels,
compare it with the deterministic router, and retain a fail-closed deterministic
binder and fallback. It may propose one route but must not author immutable
transcript provenance, self-certify confidence, bind direct-skill arguments, or
see motor tools. This is a plausible place to test a tiny model; it is not yet a
measured latency or safety improvement, and using the 26B Gemma only to classify
intent would waste latency and memory.

The official ~5.2 GB Ministral 3 8B Instruct artifact is now installed and has
already failed its first isolated promotion tests: 5/10 machine conversation
cases and 3/5 PlanIR despite faster TTFT. Keep it as a reproducible negative
control, not a production service. The separately hash-locked Ministral 3 8B
Reasoning artifact is also installed and independently measured; it failed the
predeclared first-case PlanSketch compatibility gate with malformed,
token-exhausted output. Keep that result as a 0/1 boundary control rather than
rerunning the frozen suite with a post-hoc prompt/schema/budget change. A/B
`gpt-oss-20b` first as a Gemma-unloaded planner replacement. Pin an exact native
MXFP4 checkpoint and production-capable serving runtime, apply its required
Harmony format, parse only the final structured result, and retain strict
post-decode semantic validation. Record model load/swap time, sampled peak
VRAM, KV/cache and reserve, TTFT, complete valid-plan latency, and low/medium
reasoning settings before any co-residency attempt. Qwen3.6 Q4 remains the
larger secondary challenger. Download or retain a model only if accepted-plan
and embodied-task success justify storage, latency, and GPU contention. A
conversation specialist is a separate B5 change selected with blinded human
companion review and first-audio latency, and only the combined confirmation
may select more than one new component.

### Phase 6: full-duplex voice laboratory

First commission the local/paired headset source and sink and preserve the
streaming-text fallback. Compare Whisper with Voxtral Mini 4B Realtime at the
ASR boundary, keeping the transcript planner fixed. Separately compare TTS,
treating Voxtral TTS as noncommercial and remeasuring its H200-only 70 ms claim
locally. Then compare the winning cascade against PersonaPlex or Moshi under a
voice-only GPU profile. Gemma 4 12B can be an audio-to-text reasoning challenger,
not a duplex speech system. Neither audio tokens nor a voice model may weaken
final-transcript authorization, executive arbitration, or the camera/LiDAR
sensor boundary.

## Decisions that should remain reversible

- The router implementation can change because its schema and abstention
  behavior are stable.
- Gemma, Ministral, `gpt-oss-20b`, and Qwen can compete behind one
  `PlannerProvider` interface.
- RoboBrain 2.5 or a later embodied VLM can compete behind a timestamped
  camera-grounding/progress-proposal interface without becoming the dialogue
  model, task executive, or local controller.
- CityWalker, CE-Nav, S2E, InternVLA-N1, NaVILA, and a Go2-adapted VAMOS can
  compete behind one timestamped waypoint-proposal interface.
- classical local planners can change behind the same bounded trajectory and
  safety contracts.
- Whisper/Voxtral Realtime can change behind the ASR boundary; Voxtral TTS,
  Fish, and CSM can change behind TTS; PersonaPlex and Moshi can change behind
  the duplex voice transport. Action authorization remains transcript based.
- Unitree Sport can later be replaced by a custom closed-loop controller while
  preserving the body-command, feedback, watchdog, and lease interfaces.

This composability is more important than picking a permanent “best model” in
2026. Models will change faster than the robot's safety and evaluation
contracts should.

## Final answer to the split-brain question

Yes, Parcel should split conversation from planning at the **API, prompt,
deadline, memory, and evaluation** levels as the production target. It should
not immediately split them into two large serial LLM processes.

The provider/configuration portion of that boundary is implemented in the
browser runtime: `language_model` remains the shared incumbent, while an
independently evaluated specialist can be enabled through `planner_model` on a
separate local endpoint. Both roles see the original transcript rather than a
conversational paraphrase. Their health and latency attribution remain
separate, and `--no-llm` disables both. The specialist section is intentionally
absent from the frozen default and is added only for an admitted experiment.

Concurrent scheduling, queue isolation, and independent dialogue availability
are **not** implemented. One `_agent_lock` covers the full non-E-stop model
turn, and the pinned launcher does not explicitly admit multiple inference
slots. The measured 5,657.459 ms median and 7,201.283 ms nearest-rank p95 plan
call can therefore queue a new conversational turn even with two provider
objects. E-stop bypasses the lock, and the lower control/perception loops remain
independent. Claiming a complete deadline/memory split requires priority
queues, cancellation, slot and KV admission, concurrent p95/p99 tests, and an
explicit GPU reserve.

Keep the implemented bounded router plus one admitted shared Gemma model
profile in short-budget conversation/social and deliberate PlanIR modes while
the broader B1 baseline is measured. Reviewed direct skills bind before both
generative modes; raw velocity and backend control are absent from the model
schema and fail closed if emitted. The frozen full-CUDA
run proves that trusted binding plus deterministic contract compilation can
admit Gemma's semantic skill choices for all five selected cases. Its warm
median usable-plan latency is 5,657.459 ms—71.23% below CPU but still slow. The
separate deterministic headless gate passed 4/4 supported cases with six
physical skills, 1,137 steps, zero collision/timeouts, and 0.883147 m minimum
clearance; moving-owner follow is explicitly unsupported. That gate used
geometry-derived oracle semantic tracks constrained by camera-like range/FOV,
not rendered-camera perception. Neither gate supplies a real-sensor,
contact-physics, or commissioned-Go2 score. Conversation now has
a separate machine calibration, not a human-quality score: Gemma parsed 10/10,
passed 6/10 whole cases and 9/10 structured-safety checks, and both Gemma and
Ministral exposed a raw hypothetical-gesture failure that the deterministic
production guard suppresses.

Those are five warm sequential planning cases and ten warm sequential
conversation cases, not stable tail or companion-quality evidence. They omit
cold load, concurrent queueing, ASR/TTS and first spoken audio, simulator load,
sampled peak VRAM, blinded human review, and physical robot trials. A quick
deterministic acknowledgment must remain labeled separately from first valid
reasoning and first accepted plan so it cannot hide this latency.

Do not promote the current PlanSketch prompt: although it cut median completion
tokens 71.02% and median full-call latency 63.99%, its 3/5 semantic result loses
to PlanIR's 5/5. Correct it only on a disjoint development corpus and require a
new untouched confirmation. Add a separately benchmarked planning model only
if it gives a meaningful held-out task-success or latency gain. The installed
Ministral 3 8B Instruct control already failed that bar: despite 35/35 CUDA
placement and much faster TTFT, it scored 5/10 conversation cases and 3/5
PlanIR, with slower complete responses/plans. Its Reasoning sibling was
separately loaded at 35/35 CUDA layers but failed the predeclared first
PlanSketch case after exhausting 1,024 tokens in 12,262.204 ms; this 0/1
compatibility gate is not a five-case score. `gpt-oss-20b` is the first
prioritized hardware-plausible general-reasoning challenger in a planner-only replacement
lane, not a proven robotics specialist and not a presumed co-resident service;
Qwen follows. Every planner receives the raw transcript plus bounded metadata,
never another model's lossy paraphrase. Split navigation from both language
roles: learned models propose semantic waypoints, the executive decides what
may run, the classical camera/LiDAR stack decides how to move safely, and
Unitree Sport closes the locomotion loop after the physical adapter is
commissioned.

The one-backbone choice is the first controlled implementation hypothesis.
Robix supplies positive architecture evidence for one shared high-level
interaction/planning model, and OneTwoVLA supplies positive manipulation
evidence for event-triggered reasoning and acting in shared weights. Neither is
a comparison of two serial text LLMs under Parcel's tasks, transcript,
hardware, and safety contract. Gemini, Helix, InternVLA, Robostral, and VAMOS
likewise do not settle the weight-count question. Parcel should retain the
shared backbone only if the brain ablation matrix shows acceptable plan
quality, conversational quality, tail latency, and GPU admission relative to
specialist APIs.

The resulting decision is: keep deterministic routing plus shared Gemma as the
measured incumbent; test a fine-tuned FunctionGemma route selector as an
isolated router ablation; and test `gpt-oss-20b` as a separately admitted
planner replacement before attempting co-residency. Preserve the original
transcript and deterministic binder, validator, executive, sensor, and motor
boundaries in every condition. Split weights only after paired Parcel
measurements clear quality, safety, tail-latency, and GPU-admission gates.
Separately test RoboBrain 2.5 4B on frozen camera grounding/progress cases in
shadow mode; its open 9.67 GB BF16 artifact is a plausible multimodal helper on
this desktop, not a replacement for conversation, collision avoidance, or
Unitree Sport.

That design creates the boundary through which conversation latency can be
optimized independently once scheduling is admitted, makes complex behavior
inspectable, admits better models incrementally, and prevents the most capable
text generator from becoming the least accountable motor controller.

## Selected annotated primary-source bibliography

All links below were reviewed or rechecked on 2026-08-03. Project pages,
authors' papers, official repositories, model cards, documentation, and
organizer reports are used for technical claims. Vendor-reported results remain
vendor-reported; local Parcel evidence is identified by run ID above.

- Google: [SayCan](https://say-can.github.io/), [Inner
  Monologue](https://innermonologue.github.io/),
  [SayTap announcement](https://research.google/blog/saytap-language-to-quadrupedal-locomotion/)
  and [paper](https://arxiv.org/abs/2306.07580),
  [PaLM-E](https://palm-e.github.io/), [RT-2](https://robotics-transformer2.github.io/),
  [Gemini Robotics](https://deepmind.google/blog/gemini-robotics-brings-ai-into-the-physical-world/),
  [Gemini Robotics 1.5](https://deepmind.google/blog/gemini-robotics-15-brings-ai-agents-into-the-physical-world/),
  [Gemini Robotics-ER 1.6](https://deepmind.google/blog/gemini-robotics-er-1-6/),
  [Gemini Robotics ER 2](https://deepmind.google/models/gemini-robotics/embodied-reasoning/),
  and [Open X-Embodiment](https://github.com/google-deepmind/open_x_embodiment).
- Figure: [Helix](https://www.figure.ai/news/helix), [Helix
  02](https://www.figure.ai/news/helix-02), and [Project
  Go-Big](https://www.figure.ai/news/project-go-big).
- NVIDIA: [Isaac GR00T](https://github.com/NVIDIA/Isaac-GR00T), [GR00T
  N1 technical overview](https://developer.nvidia.com/blog/accelerate-generalist-humanoid-robot-development-with-nvidia-isaac-gr00t-n1/),
  and [PersonaPlex](https://research.nvidia.com/labs/adlr/personaplex/).
- Physical Intelligence: [openpi](https://github.com/Physical-Intelligence/openpi),
  [π0.5](https://www.physicalintelligence.company/download/pi05.pdf), and
  [FAST](https://www.physicalintelligence.company/download/fast.pdf).
- Unified interaction/reasoning systems: ByteDance Seed's
  [Robix project](https://robix-seed.github.io/robix/) and
  [paper](https://arxiv.org/abs/2509.01106), plus the
  [OneTwoVLA project](https://one-two-vla.github.io/),
  [paper](https://arxiv.org/abs/2505.11917), and
  [official code](https://github.com/Fanqi-Lin/OneTwoVLA).
- Navigation: [InternNav](https://github.com/InternRobotics/InternNav),
  [InternVLA-N1](https://internrobotics.github.io/internvla-n1.github.io/),
  [LM-Nav](https://proceedings.mlr.press/v205/shah23b/shah23b.pdf),
  [NaVILA](https://navila-bot.github.io/),
  [Robostral Navigate announcement](https://mistral.ai/news/robostral-navigate/)
  and [paper](https://arxiv.org/abs/2607.20785),
  [VAMOS project](https://vamos-vla.github.io/),
  [repository](https://github.com/vamos-vla/vamos), and
  [checkpoint](https://huggingface.co/mateoguaman/vamos),
  [Mobility VLA PMLR page](https://proceedings.mlr.press/v270/xu25b.html) and
  [paper PDF](https://openreview.net/pdf?id=JScswMfEQ0),
  [Qwen-RobotNav](https://github.com/QwenLM/Qwen-RobotNav),
  [Qwen-VLA](https://github.com/QwenLM/Qwen-VLA),
  [FSR-VLN](https://arxiv.org/abs/2509.13733),
  [Nav-R1](https://github.com/AIGeeksGroup/Nav-R1),
  [ABot-N1 paper](https://arxiv.org/abs/2607.10383),
  [ABot-Navigation](https://github.com/amap-cvlab/ABot-Navigation),
  [PointBench](https://huggingface.co/acvlab/ABotN-PointBench),
  [POIBench](https://huggingface.co/acvlab/ABotN-POIBench),
  [CE-Nav](https://github.com/amap-cvlab/CE-Nav),
  [S2E/NavBench-GS](https://github.com/VAIL-UCLA/S2E),
  [OmniNav](https://github.com/amap-cvlab/OmniNav),
  [LeLaN](https://learning-language-navigation.github.io/),
  [SACSoN](https://arxiv.org/pdf/2306.01874),
  [CityWalker repository](https://github.com/ai4ce/CityWalker),
  [paper](https://openaccess.thecvf.com/content/CVPR2025/papers/Liu_CityWalker_Learning_Embodied_Urban_Navigation_from_Web-Scale_Videos_CVPR_2025_paper.pdf),
  [official converted model](https://huggingface.co/ai4ce/citywalker),
  [VLFM](https://github.com/bdaiinstitute/vlfm),
  [Grounding DINO](https://github.com/IDEA-Research/GroundingDINO),
  [SAM 2](https://github.com/facebookresearch/sam2),
  [ConceptGraphs](https://github.com/concept-graphs/concept-graphs),
  [ReMEmbR](https://arxiv.org/abs/2409.13682), and
  [ViNT/NoMaD](https://github.com/robodhruv/visualnav-transformer).
- Classical navigation: official [Nav2 plugin
  index](https://docs.nav2.org/plugins/index.html), [Regulated Pure Pursuit
  configuration](https://docs.nav2.org/configuration/packages/configuring-regulated-pp.html),
  [Rotation Shim
  configuration](https://docs.nav2.org/configuration/packages/configuring-rotation-shim-controller.html),
  [MPPI configuration](https://docs.nav2.org/configuration/packages/configuring-mppic.html),
  [Graceful Controller
  configuration](https://docs.nav2.org/configuration/packages/configuring-graceful-motion-controller.html),
  and [Velocity Smoother
  configuration](https://docs.nav2.org/configuration/packages/configuring-velocity-smoother.html).
- Simulation and social navigation: [MetaUrban project and
  paper](https://metadriverse.github.io/metaurban/), [Arena-Rosnav official
  organization/repository](https://github.com/Arena-Rosnav/arena-rosnav),
  [URBAN-SIM](https://github.com/metadriverse/urban-sim),
  [iGibson official project](https://svl.stanford.edu/igibson/), [iGibson 2021
  Social Navigation challenge](https://svl.stanford.edu/igibson/challenge2021.html),
  and [Habitat 3.0](https://aihabitat.org/habitat3/).
- Open VLAs: [OpenVLA](https://github.com/openvla/openvla),
  [MiniVLA](https://github.com/Stanford-ILIAD/openvla-mini),
  [SmolVLA paper](https://arxiv.org/abs/2506.01844),
  [official model card](https://huggingface.co/lerobot/smolvla_base),
  [LeRobot repository](https://github.com/huggingface/lerobot), and
  [X-VLA](https://github.com/2toinf/X-VLA).
- Speech: [Sesame CSM](https://github.com/SesameAILabs/csm),
  [Fish Speech](https://github.com/fishaudio/fish-speech),
  [Voxtral Mini 4B Realtime
  2602](https://huggingface.co/mistralai/Voxtral-Mini-4B-Realtime-2602),
  [Voxtral 4B TTS
  2603](https://huggingface.co/mistralai/Voxtral-4B-TTS-2603),
  [PersonaPlex model card](https://huggingface.co/nvidia/personaplex-7b-v1),
  and [Moshi](https://github.com/kyutai-labs/moshi).
- Situated interaction and cognitive-agent evidence: [A Modern System Recipe
  for Situated Embodied Human-Robot
  Conversation](https://arxiv.org/abs/2602.04157) and [From Language to
  Action](https://arxiv.org/abs/2603.03148), plus
  [Speculative Interaction Agents](https://arxiv.org/abs/2605.13360) and
  [DuCCAE](https://arxiv.org/abs/2603.19248) for asynchronous serving evidence.
- Models: [Gemma 4 overview](https://ai.google.dev/gemma/docs/core),
  [Gemma 4 model card](https://ai.google.dev/gemma/docs/core/model_card_4),
  [Gemma thinking guide](https://ai.google.dev/gemma/docs/capabilities/thinking),
  [Gemma 4 12B](https://huggingface.co/google/gemma-4-12B),
  [Gemma audio guide](https://ai.google.dev/gemma/docs/capabilities/audio),
  [Gemma 4 26B A4B MTP assistant](https://huggingface.co/google/gemma-4-26B-A4B-it-qat-q4_0-unquantized-assistant),
  [FunctionGemma overview](https://ai.google.dev/gemma/docs/functiongemma),
  [FunctionGemma model card](https://ai.google.dev/gemma/docs/functiongemma/model_card),
  [FunctionGemma fine-tuning guide](https://ai.google.dev/gemma/docs/functiongemma/finetuning-with-functiongemma),
  [FunctionGemma official checkpoint](https://huggingface.co/google/functiongemma-270m-it),
  [gpt-oss release](https://openai.com/index/introducing-gpt-oss/),
  [gpt-oss model card](https://openai.com/index/gpt-oss-model-card/),
  [gpt-oss-20b official checkpoint](https://huggingface.co/openai/gpt-oss-20b),
  [gpt-oss repository](https://github.com/openai/gpt-oss),
  [Harmony repository](https://github.com/openai/harmony),
  [gpt-oss usage and licensing guidance](https://help.openai.com/en/articles/11870455-openai-open-weight-models-gpt-oss),
  [Ministral 3 8B Instruct GGUF](https://huggingface.co/mistralai/Ministral-3-8B-Instruct-2512-GGUF),
  [Ministral 3 8B Reasoning GGUF](https://huggingface.co/mistralai/Ministral-3-8B-Reasoning-2512-GGUF),
  [Ministral 3 8B model card](https://docs.mistral.ai/models/model-cards/ministral-3-8b-25-12),
  [Qwen3.6-35B-A3B](https://huggingface.co/Qwen/Qwen3.6-35B-A3B),
  [Qwen3.6 announcement](https://qwen.ai/blog?id=qwen3.6-35b-a3b),
  [Kimi K2.5 repository](https://github.com/MoonshotAI/Kimi-K2.5),
  [official weight listing](https://huggingface.co/moonshotai/Kimi-K2.5/tree/main),
  [Kimi K3](https://github.com/MoonshotAI/Kimi-K3), and
  [Kimi-VL](https://github.com/MoonshotAI/Kimi-VL), plus
  [RoboBrain 2.5 code](https://github.com/FlagOpen/RoboBrain2.5),
  [paper](https://arxiv.org/abs/2601.14352), and
  [official 4B checkpoint](https://huggingface.co/BAAI/RoboBrain2.5-4B).
- Local inference runtime: pinned [`llama.cpp` b10236 CUDA build
  documentation](https://github.com/ggml-org/llama.cpp/blob/1464c62d88f699ec9700c8010bbfdbc603a9efd6/docs/build.md)
  and [source commit](https://github.com/ggml-org/llama.cpp/commit/1464c62d88f699ec9700c8010bbfdbc603a9efd6).
- Evaluation: [Habitat Challenge
  2020](https://aihabitat.org/challenge/2020/), its [archived official code
  repository](https://github.com/facebookresearch/habitat-challenge/tree/challenge-2020),
  [BARN 2026 organizer page](https://people.cs.gmu.edu/~xiao/Research/BARN_Challenge/BARN_Challenge26.html),
  the [BARN 2026 official
  report](https://people.cs.gmu.edu/~xiao/papers/barn26_report.pdf), the
  [official ROS 2 evaluator
  repository](https://github.com/Saadmaghani/The-Barn-Challenge-Ros2), the
  [3WE benchmark](https://3we.org/benchmarks), [pinned audited source](https://github.com/telleroutlook/3we-robot-platform/tree/6073a1bd0a30b6ca1348027ac35b05832b97bfe9),
  and [local contract audit](../evals/external/results/threewe/threewe-contract-audit-20260803-baseline01.json).
