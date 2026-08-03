# Companion navigation and instruction-following architecture

Research and measured baseline, 2026-08-03.

## Decision

Parcel should not be built as one language model that continuously predicts the
dog's next velocity. The production design should be a hierarchical,
closed-loop system:

The supporting system survey, split-brain decision, open-weight/license and GPU
analysis, and staged experiment matrix are in
[AI brain and navigation research](AI_BRAIN_AND_NAVIGATION_RESEARCH.md).

```text
audio/text + camera scene + task state
  -> conversation and intent model
  -> typed task plan with semantic goals
  -> affordance/precondition scorer
  -> interruptible skill executive
  -> semantic goal resolver and global route
  -> local trajectory planner
  -> independent collision/social safety shield
  -> bounded body-velocity command
  -> Unitree Sport controller
  -> robot state feedback
```

The reasoning model should propose the next **semantic skill** and explain what
success means. It must not output joint targets or raw `vx/vy/vyaw`. A
deterministic executive may accept, defer, reject, or replace the proposal after
checking the current task, resources, perception freshness, battery, and safety.

This combines the most useful ideas from:

- Google's [SayCan](https://say-can.github.io/): combine semantic usefulness
  with a skill's probability of being executable;
- Google's [Inner Monologue](https://innermonologue.github.io/): feed success,
  failure, and changed-scene observations back into planning;
- the asynchronous slow/fast split in
  [InternVLA-N1](https://internrobotics.github.io/internvla-n1.github.io/);
- open-vocabulary semantic search in
  [VLFM](https://github.com/rai-opensource/vlfm) and persistent scene memory in
  [ConceptGraphs](https://github.com/concept-graphs/concept-graphs); and
- the classical global/local/safety stacks that dominated the
  [2026 BARN Challenge](https://people.cs.gmu.edu/~xiao/papers/barn26_report.pdf).

No one system above is a drop-in Parcel controller. The design adopts their
interfaces and feedback patterns while preserving Parcel's camera/LiDAR trust
boundary and Unitree locomotion backend.

## Measured starting point

The first external gate is the static
[Benchmark for Autonomous Robot Navigation](https://www.cs.utexas.edu/~xiao/BARN/BARN.html).
BARN specifically measures metric, collision-free sense-plan-act navigation in
clutter. It does not measure conversation or semantic instruction quality.

Parcel now has a sensor-only adapter around the unchanged production
`DirectiveNavigator`. The policy receives only the goal, odometry, a 270-degree
LiDAR scan, and time. It never receives the SDF obstacle list, evaluator
contacts, reference path, or optimal path length. Lateral velocity is discarded
at the adapter boundary because the standardized BARN Jackal is differential
drive. Evaluation-owned state determines collisions and success.

The source and protocol are pinned to
[`Daffan/the-barn-challenge@bf5a226`](https://github.com/Daffan/the-barn-challenge/tree/bf5a226f6088ec96bf0d2dbee3253a8ea6119b83).
The desktop now has a cache-only Bubblewrap/PRoot ROS 2 Jazzy rootfs that ran
the unchanged upstream Nav2 MPPI example on one public world. It still lacks a
working upstream-tested Singularity/SIF path and has not run Parcel's adapter in
Gazebo. The results below remain deterministic native kinematic results,
explicitly labeled `barn-native-headless-non-official`; the separate upstream
smoke is runtime evidence only. Neither may be compared numerically with
leaderboard scores.

| Run | Scope | LiDAR rays | Success | Native metric | Collision | Stop outside goal |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `barn-native-20260803T082347318784Z-7a83e78d` | fixed 10-world PR gate | 720 | 10% | 0.02278 | 0% | 90% |
| `barn-native-20260803T082542002189Z-3d35d19a` | fixed 50-world subset sampled from 300 public worlds | 720 | **2%** | **0.00456** | **0%** | **98%** |

On the fixed-subset run, only world 42 succeeded. The mean traveled distance was
2.96 m and mean final goal distance was 8.32 m. Controller latency was very low
(0.028 ms p95; 0.038 ms p99), as was the entire adapter (0.205 ms p95; 0.226 ms
p99). Computation is not the bottleneck.

Three earlier smoke/downsample records remain in the immutable ledger. The
canonical runs above use the exact 720-ray, 270-degree, 30 m Gazebo UST-10
configuration from the pinned Jackal Melodic dependency. Their task outcomes
match the earlier 271-ray regression runs.

All 49 failures ended as `navigation_no_progress`. Many final poses accumulated
near one side of the course. The current tangent-style local avoidance chooses
a safe direction but has no long-horizon representation of a passage. It can
latch onto the wrong side of an obstacle, approach the arena boundary, and then
correctly stop when it cannot make progress. Zero collisions show that making
the same reaction more aggressive would trade a planning failure for a safety
failure.

## Measured first hill-climb

The first implementation stage adds a sensor-only rolling log-odds grid,
footprint inflation, unknown-space penalty, deterministic eight-connected A*,
known-free line-of-sight smoothing, forward-preferred turn-first waypoint
tracking, fresh-scan route invalidation, and a bounded scan recovery. It uses
only the raw LiDAR geometry, pose, goal, and clock supplied through the same
adapter. The evaluator's SDF, reference path, contacts, and score state remain
private.

The candidate was selected on ten development-only public-asset worlds
disjoint from validation, then run once on the frozen PR set and fixed
50-world public proxy subset:

| Run | Role | Success | Native metric | Collision | Controller p95/p99 |
| --- | --- | ---: | ---: | ---: | ---: |
| unchanged fixed-subset baseline | reference | 2% | 0.004556 | 0% | 0.028/0.038 ms |
| `barn-ab-20260803T085628637608Z-11434067` | development candidate | 60% | 0.142760 | 0% | 19.45/21.71 ms |
| `barn-ab-20260803T085836259527Z-02d34dc6` | frozen PR validation | 70% | 0.171962 | 0% | 17.87/21.98 ms |
| `barn-ab-20260803T092104342162Z-8e02235b` | fixed-subset validation | **36%** | **0.088595** | **0%** | **115.47/122.02 ms** |
| `barn-ab-20260803T092611245140Z-e1dbace8` | start-egress/vectorized development | 90% | 0.214258 | 0% | 18.47/26.99 ms |
| `barn-ab-20260803T092817959279Z-c1f7b9d8` | next frozen PR validation | **90%** | **0.212213** | **0%** | **16.24/26.48 ms** |
| `barn-ab-20260803T093224170877Z-6b24e34f` | next fixed-subset validation | **44%** | **0.103698** | **0%** | 125.94/129.43 ms* |

\*The last run used eight CPU workers. Its latency percentiles include host
contention and are throughput telemetry, not single-robot deployment latency.

On matched episodes in the first fixed-subset run, the candidate gained 17
successes, lost none,
and improved the native metric by 0.08404, or 19.4x over the unchanged
baseline. It still failed 32/50 worlds: 29 progress-watchdog stops and three
timeouts. The minimum signed evaluator clearance was 0.0807 m beyond the
native circular collision boundary. This is a large navigation-floor
improvement, not an official score or a completed planner.

Post-run tracing found two concrete problems. First, A* already carved out the
robot's current inflated start cell, but route visibility rejected that same
cell and entered an endless scan recovery. Exempting only supercover index zero
while retaining strict observed/non-inflated checks for every later cell raised
the development and PR gates to 90%. Fixed-subset success rose to 44%, with 21
paired success gains, no regressions, and zero collisions. Its remaining 28
failures spent most controller ticks in recovery/no-path states.

Second, repeated long-range scan integration caused the original fixed-subset
tail latency. Batched Bresenham traversal and vectorized evidence/log-odds
updates are scalar-oracle equivalent and reduced a 720-ray open-scan update
from 22.89 ms to 3.40 ms median (6.7x). The frozen PR controller then measured
2.65 ms p50, 16.24 ms p95, and 26.48 ms p99. Its 143.95 ms maximum still
justifies a bounded asynchronous map/planning worker whose output carries a
freshness deadline. The safety shield and Sport controller must never wait for
a map update.

The candidate deliberately retains a 0.6 m/s Go2-compatible cap. Official
BARN uses a standardized 2 m/s Jackal and scores 50 unseen worlds over ten
Gazebo trials. Product/Go2 and competition/Jackal profiles must remain
separate, with shared planning changes promoted only when both their benchmark
and Unitree safety gates pass.

One protocol difference is intentionally conservative: native elapsed time
starts at reset; the official script starts timing only after 0.1 m of motion.
The official run must eventually be reproduced in its pinned ROS/Gazebo stack
before making any competition claim.

## The companion executive

### A typed plan, not free-form choreography

The reasoner returns a compact `PlanIR`. A representative node is:

```json
{
  "id": "step-2",
  "skill": "NavigateTo",
  "arguments": {
    "target": {"kind": "semantic_region", "query": "sidewalk"},
    "terminal_relation": "inside"
  },
  "preconditions": ["perception_fresh", "base_available"],
  "success": {"relation": "inside", "target": "sidewalk", "confidence_min": 0.8},
  "timeout_s": 90,
  "recovery": ["rescan", "alternate_candidate", "ask_user"],
  "resources": ["base"],
  "interruptibility": "checkpoint",
  "priority_request": "normal"
}
```

Allow-listed plan nodes should initially be:

- `NavigateTo`, `FollowFormation`, `OrbitOwner`, `MoveRelative`, `Hold`, and
  `ReturnToSafePose` for base motion;
- `Pose`, `Gesture`, and `RecoverBalance` for body expression;
- `Vocalize`, `Listen`, and `AskClarification` for conversation; and
- `Verify`, `Search`, and `Replan` for explicit closed-loop feedback.

Each skill owns its typed arguments, preconditions, success relation and
tolerance, retry budget, timeout, resource locks, cancellation cleanup, and
telemetry. The model cannot invent a tool or widen its bounds.

### Use affordances to ground the plan

For every candidate skill `a`, compute a score conceptually like:

```text
score(a) = semantic_relevance(a, instruction)
         * executability(a, current_state)
         * safety_margin(a)
         * task_priority(a)
```

The language model supplies semantic relevance. Deterministic or learned
capability estimators supply the remaining terms. A fluent but currently
unexecutable action therefore loses to a useful, feasible alternative. This is
the important SayCan lesson for Parcel.

After every meaningful skill transition, feed a bounded structured result back
to the planner: `succeeded`, `blocked`, `target_lost`, `battery_changed`,
`owner_moved`, or `scene_changed`, plus verified observations. This is the
Inner-Monologue lesson, implemented as data rather than unrestricted prose.

### Arbitration and interruption

Priority is owned outside the model:

1. emergency stop, imminent collision, fall, thermal limit;
2. manual operator command;
3. balance recovery and battery-critical safe stop;
4. explicit `stop` or task cancellation;
5. active navigation/following mission;
6. explicit user gesture request;
7. inferred social gesture or ambient behavior.

Use independent `base`, `posture`, `voice`, and `attention` resource locks. A
chuckle can overlap collision-free following because it only needs `voice`. A
play bow needs `posture` and normally `base`, so it waits for a safe navigation
checkpoint. A low-battery sit is a deterministic system policy: it first
reaches a safe non-road region if feasible, releases the base, then sits. It is
not an emotion inferred by the language model.

The model may request `interrupt_now`, `at_checkpoint`, or `when_idle`, but the
executive assigns the effective policy. A joke does not cancel a road-crossing
or doorway traversal. An explicit stop still does.

### Concrete behavior flows

**"Go to the store."** Resolve a known semantic-map instance first. If none is
known, rank camera-derived store candidates and safe semantic frontiers. Plan a
route to a visible/likely entrance, continuously avoid obstacles using LiDAR,
and verify the store or entrance before declaring success. Ask for clarification
when multiple candidates materially change the task. The future maps provider
may supply a prior but never substitutes for local camera/LiDAR verification.

**"Follow behind me."** Track the owner from camera observations, estimate a
filtered heading from motion history, and create a moving anchor behind that
heading at a socially appropriate distance. The global/local planner tracks the
anchor with hysteresis, predicts short-term owner motion, yields around people,
and stops on stale/lost owner perception. This is not generic point following.

**"Walk around me once."** Capture the owner track and a bounded local radius,
plan a collision-free closed orbit in free space, approach its tangent, complete
one accumulated angular revolution, and verify both revolution and clearance.
Replan or stop if the owner moves too far.

**User sounds sad.** The reasoner may propose a gentle verbal response and
`play_bow`. Voice can start immediately; the gesture executes only when the
posture/base locks are available and the ground is safe.

**User laughs at a joke.** A short `Vocalize(chuckle)` is low-risk and can run in
the voice lane. A leg stretch is deferred while the dog is navigating through a
tight passage.

## Navigation design that should replace local-only avoidance

The 2026 BARN finalists provide unusually direct evidence about this layer. For
the second year, every physical finalist used a classical, non-learning
navigation stack. The winner combined an A* route, corner-aware lookahead,
VFH* clearance selection, fuzzy velocity control, and a final safety barrier.
The second-place system combined A*, signed-distance-field waypoint correction,
and TEB. The third used a global route with nonlinear MPC. The winning simulator
score was 0.4975 out of 0.5, but that official score is not directly comparable
to Parcel's native approximation.

The prioritized Parcel improvement is:

1. **Rolling occupancy mapping.** Fuse odometry and LiDAR into log-odds occupied,
   free, and unknown cells. Inflate occupied cells by the dog footprint plus a
   speed-dependent margin. Decay dynamic returns separately from static cells.
2. **Global route.** Run A* initially, then D* Lite for incremental replanning.
   In the strict sensor-only gate, plan over observed free space and use a
   bounded frontier/unknown penalty; do not import the evaluator's private SDF
   or reference path.
3. **Corner-aware pursuit.** Select a lookahead point along the route, shorten
   lookahead at high curvature/narrow clearance, rotate mostly in place when the
   heading error is large, and then accelerate. Lateral velocity remains allowed
   for a quadruped's evasive/fine alignment, but is penalized as the normal way
   to make route progress.
4. **Local clearance.** Score feasible short trajectories or VFH* headings
   against route alignment, time-to-collision, passage clearance, reverse cost,
   rotation, acceleration, and jerk. Keep the existing independent final brake.
5. **Recovery state machine.** On progress failure: stop, clear transient
   history, rotate/scan, replan globally, try a bounded reverse/alternate side,
   then fail with evidence. Never repeatedly amplify the same tangent command.
6. **Later optimizer.** Add SDF-guided TEB or short-horizon NMPC only after the
   map/global-route baseline. It should improve tight-passage smoothness, but is
   not the first missing capability.

This layer runs without an LLM. Learned visual trajectories can propose a local
route, but route validation, collision checking, acceleration limits, and
closed-loop execution remain deterministic.

## Model choices on this workstation

There is no single open model that is simultaneously the best conversational
companion, semantic planner, visual navigator, speech system, and safety
controller. Separate them so each can be measured and replaced.

| Candidate | Best role | Parcel decision |
| --- | --- | --- |
| installed Gemma 4 26B-A4B Q4 | conversation, intent, typed PlanIR | Keep as the tested orchestration baseline; use non-thinking mode for normal turns and deliberate mode only for ambiguous plans. |
| Qwen3.6-35B-A3B Q4 | stronger conversation/planning A/B candidate | Evaluate on an offline instruction/plan suite before swapping the baseline. Never use its text as motor commands. |
| [CityWalker](https://github.com/ai4ce/CityWalker) | urban visual local-trajectory proposal | Official 2,000-hour checkpoint is downloaded and checksum-locked. Keep inactive until Parcel transports timestamped RGB and has a trajectory/safety adapter. |
| [ViNT / NoMaD](https://github.com/robodhruv/visualnav-transformer) | compact visual goal navigation / exploration | Strong lightweight research candidates after RGB exists; evaluate behind the same local-waypoint interface. |
| [InternVLA-N1 DualVLN](https://github.com/InternRobotics/InternNav) | slow/fast language-conditioned visual navigation challenger | Best architectural research candidate for a later RGB(-D) A/B; it has documented Go2 deployment, but needs roughly 20 GB GPU memory and its checkpoint license must be resolved before product use. |
| [NaVILA](https://github.com/AnjieCheng/NaVILA) | Go2 vision-language navigation research | Exact embodiment fit, but checkpoint licensing/provenance is insufficient for production adoption. Treat as research only. |
| [Fish S2 Pro](https://github.com/fishaudio/fish-speech) | expressive streaming TTS | Already isolated from reasoning; commercial deployment requires separate Fish licensing. It is not a full-duplex reasoner. |
| [PersonaPlex](https://huggingface.co/nvidia/personaplex-7b-v1) | native full-duplex speech-to-speech research | Interesting future voice A/B, but gated/licensed and competes for the single GPU with visual navigation. Do not put audio tokens in the motor path. |

The downloaded CityWalker artifact is
`models/nav/citywalker/CityWalker_2000hr.ckpt`, 1,752,028,242 bytes, SHA-256
`a42326778e5e318c6222575dc5e02f1794d9a60cce4dc8f8a2ee5df7dc6d1c29`.
The download is deliberately not activation. This workstation currently has no
camera device and Parcel's `NavObservation.rgb` is not populated. Running a
vision checkpoint without pixels would create a false capability claim.

InternVLA-N1 is especially relevant to the design, not yet to the active build.
Its published Go2 setup sends aligned RGB/depth to an RTX 4090 server, runs the
slow language system asynchronously, generates fast trajectory candidates, and
tracks the selected trajectory with MPC. The report describes about 0.7 s for
cached slow-system trajectory tokens and about 0.03 s for 32 optimized fast
trajectories. Parcel should copy the asynchronous contract—not bypass its
safety/controller boundary.

## Low-latency multi-rate execution

Run components at the rate their information actually changes:

| Layer | Typical cadence | Deadline behavior |
| --- | ---: | --- |
| Unitree onboard balance/Sport controller | vendor real-time loop | Independent watchdog and safe stop |
| final collision/command validity shield | 50-100 Hz | stale input means stop |
| local trajectory tracking | 20-50 Hz | retain last safe short horizon; brake on expiry |
| LiDAR mapping and dynamic tracking | 10-20 Hz | reject stale observations |
| camera detector/tracker | 10-30 Hz, hardware dependent | prediction with bounded age |
| global replan | 1-5 Hz or event-driven | old route remains advisory only |
| fast intent/canonical command path | immediate | bypass deliberative LLM where possible |
| language/semantic replan | event-driven, usually 0.5-2 Hz | asynchronous; never stalls control |
| voice synthesis/playback | streaming independent lane | cancellable on barge-in/priority speech |

The control plane must never wait for a language token. Snapshot camera/scene
state once per reasoning request, run semantic resolution and conversation in
parallel where independent, stream an honest acknowledgement, and commit tools
only after complete schema validation and fresh-state revalidation.

Record at least model TTFT, end-of-query to first reasoning output,
end-of-query to first logged/spoken response, semantic grounding, global plan,
local plan, map update, controller, safety shield, backend send, observation
age, action acceptance/defer/reject time, and full task completion. Use p50,
p95, p99, and maximum; never put user text into metric labels.

## Dynamic simulation strategy

Use multiple simulators rather than forcing one environment to be fast,
photorealistic, socially rich, and an accurate quadruped digital twin.

| Environment | What it should test | Decision |
| --- | --- | --- |
| Parcel headless city | semantic task logic, owner orbit/follow, regressions, deterministic failure injection | Keep as the fastest PR gate. Increase procedural layouts and scripted pedestrian trajectories, but label semantic simulator truth as test oracle data. |
| BARN | LiDAR metric planning and tight-passage safety | First external gate; native sensor-only today, official ROS/Gazebo next. |
| [MetaUrban](https://github.com/metadriverse/metaurban) | outdoor sidewalks, roads, clutter, pedestrians, cyclists and social navigation | **Best next dynamic-city integration.** It is Apache-2.0, procedural, has RGB/depth/semantic/LiDAR sensors and PointNav/SocialNav tasks. Run it in a separate Python 3.9/container environment. Its current robot-dog actor is a dog visual mounted on a box/four-wheel `BulletVehicle`, not an articulated quadruped. |
| [Habitat 3.0](https://aihabitat.org/habitat3/) | finding/following humans and indoor social behavior | Add after the visual adapter; useful companion/social gate, not the main city simulator. |
| [iGibson](https://github.com/StanfordVL/iGibson) / OmniGibson | interactive indoor objects and household tasks | Useful later for manipulation/everyday-object interaction; not the best answer for a dynamic city. |
| [Isaac Sim](https://developer.nvidia.com/isaac/sim) / Isaac Lab | high-fidelity sensors, quadruped dynamics, sim-to-real policy training | Use as the later digital-twin/control-training tier. It is heavier than the CI/eval loop. |
| [CARLA](https://carla.org/) | vehicle traffic, crossings, weather and road hazards | Optional scenario source/bridge. Its car-centric action model is a poor primary dog simulator. |

MetaUrban's official examples support dynamic scenes with vehicles, pedestrians,
and other agents, and its published hardware guidance is well below this
desktop's RTX 5000 Ada capacity. Its complete assets require registration and
its reference environment uses Python 3.9, so it should not be installed into
Parcel's Python 3.14 environment. Define a simulator-neutral bridge with
timestamped camera, LiDAR, odometry/proprioception, owner tracks, action, reset,
and evaluator-only truth channels; run MetaUrban out of process.

Source inspection of MetaUrban's `EgoRobotDog` shows steering/speed control over
virtual wheels. It can test language grounding, city route planning, owner
following, and social collision avoidance, but cannot validate gait, lateral
stepping, foot contacts, curb traversal, falls, balance, or the Unitree Sport
controller. Those belong in the Isaac/Unitree digital-twin tier. Also test
whether pedestrians react reciprocally to the ego dog before describing the
crowd behavior as realistic rather than scripted. Pin MetaUrban itself before
integration; the researched revision was
`6b8ff9aa48dd27d5c57fa1c712db520732f11fa9`.

Isaac Sim is the later articulated tier, but its supported Ubuntu releases do
not currently include this host's Ubuntu 26.04. Use a pinned supported
container/runtime and audit NVIDIA asset/Kit terms rather than installing it
directly into Parcel.

The policy's spatial knowledge remains camera and LiDAR derived. Odometry and
proprioception are control-state feedback, not a magical map of the world.
Google Maps stays an unavailable optional prior until a real provider, privacy
policy, localization source, and local-verification rule exist.

## Evaluation ladder

External source code stays immutable and pinned. Parcel owns adapters. If an
API differs, change the adapter—not the contest's success, collision, timeout,
sensor, or score behavior. Any unavoidable evaluator patch must be separately
versioned, diffed, and reported as a nonstandard fork.

The two traced contest sources are:

- BARN at `bf5a226f6088ec96bf0d2dbee3253a8ea6119b83`, the first active gate;
- [Habitat Challenge 2020](https://aihabitat.org/challenge/2020/) at
  `ddf1575532aecc4df2f4cd4c5db173b8eada3e1e`, the second traced gate for later
  RGB-D PointNav/ObjectNav work.

Recommended gates:

1. every PR: deterministic unit/scenario tests plus fixed BARN public worlds
   `0,6,...,54`, one trial;
2. nightly: the fixed 50-world public proxy subset, three trials when policies
   are stochastic;
3. release candidate: official 50-by-10 BARN protocol in the pinned container;
4. robustness: all 300 public worlds plus freshly generated private holdouts;
5. dynamic city: MetaUrban held-out layouts/densities with SR, SPL, social
   navigation score, collision, personal-space, TTC, and jerk;
6. visual language: Habitat/InternNav-style held-out instruction routes;
7. companion task suite: semantic success predicates for store, sidewalk,
   lamppost, owner orbit/follow, social response, interruption, and low battery.

Never tune against the BARN reference path or public-world-specific geometry.
For each run, retain date, run ID, description of the change, Parcel commit and
dirty state, evaluator commit, adapter/config/model hashes, aggregate metrics,
and a checksum of the detailed report. `evals/external/ledger.py` implements the
append-only ledger and `run_barn.py` records every CLI run automatically.

## Metric-improvement experiment order

The evidence supports the following order. Each stage gets its own ledger run
and is promoted only if collision rate does not regress.

1. **Map + A*/D* Lite + corner-aware lookahead.** Primary hypothesis: remove
   tangent latching and side-boundary stalls. Target the current 98%
   stopped-outside rate before optimizing speed.
2. **VFH*/short-trajectory local scoring and bounded recovery.** Improve passage
   selection and escape recoverable deadlocks while retaining the final brake.
3. **SDF-informed TEB or NMPC.** Improve smoothness, clearance, and speed after
   route correctness is established.
4. **Dynamic tracking/social costmap.** Separate static occupancy from predicted
   people trajectories; test in MetaUrban rather than static BARN.
5. **CityWalker/ViNT advisory trajectory A/B.** Activate only after RGB transport,
   calibration, runtime isolation, and trajectory validation exist.
6. **InternVLA-N1 research A/B.** Evaluate instruction grounding and visual
   route choice with deterministic local safety below it; resolve checkpoint
   licensing and resource contention first.
7. **Reasoner A/B.** Compare Gemma and specialist challengers on typed task-plan
   correctness, ambiguity handling, defer/interrupt decisions, conversational
   quality, and latency. Ministral Instruct's first live control was rejected at
   5/10 conversation and 3/5 PlanIR. Do not use BARN score to choose a
   conversation model.

The first promotion goal should be deliberately modest: nonzero success on the
fixed PR gate with zero collisions, followed by a material reduction in
`navigation_no_progress` on the fixed 50-world public proxy subset. Only then
optimize the metric's time component. A fast collision has a score of zero.

## Immediate productionization sequence

1. Preserve the current unchanged baseline and immutable ledger.
2. Implement the rolling LiDAR occupancy-map interface behind a feature flag.
3. Add global-route and local-trajectory interfaces without replacing the
   final collision gate or Unitree Sport controller.
4. Run map/A* and recovery experiments only through explicit experimental
   configs; compare against the recorded baseline.
5. Add camera pixel transport and calibration. Until then, keep all visual
   checkpoints inactive.
6. Install MetaUrban in an isolated runtime and implement the simulator bridge;
   do not mix its legacy dependencies into `.parcel`.
7. Package Parcel's evaluator adapter into the working cache-only ROS/Gazebo
   diagnostic rootfs, run one world, then the explicit 50-by-10 public protocol.
   Keep every result non-official until the tested Singularity/SIF path and
   organizer attestation exist.
8. Add PlanIR/affordance/executive changes behind schema and feature gates, then
   evaluate language-task success separately from metric navigation.

This sequence improves the dog from the bottom up: first it can reliably reach
a geometric goal, then find semantic goals, then choose and schedule companion
behaviors, and finally express them conversationally without compromising the
closed-loop safety and locomotion layers.
