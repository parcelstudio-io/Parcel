# Open-weight model and custom-training decision

## Executive decision

Two independent RL assessments reached the same conclusion:

> **Do not train a Parcel-owned end-to-end navigation, task-planning,
> locomotion, or VLA policy now. Spend zero RL GPU-hours until the safety,
> state, simulator, dataset, serving, and evaluation prerequisites are valid.**

Reuse Unitree Sport and a strong classical planner, evaluate released
waypoint-producing models, and repair Parcel's perception/executive substrate.
If an attributable gap remains, adapt the narrowest component first. The best
leading eventual learning hypothesis is a bounded candidate-trajectory
ranker/social critic, contingent on a feasible candidate sampler and a measured
residual gap—not raw velocity, joints, balance, or language-to-motor control.

No new model was downloaded or installed during this research task.

The official Hugging Face loaders for MiniCPM-RobotTrack and the converted
CityWalker artifact both call `trust_remote_code=True`; that code is executable,
not passive weight data. Any trial must pin/review it and run in Parcel's
networkless, credentialless, resource-bounded model sandbox. Hub scanning does
not replace review.

## Current device and model reality

The audited desktop has:

```text
NVIDIA RTX 5000 Ada, 32,760 MiB VRAM, compute capability 8.9
AMD Threadripper PRO 7995WX, 96 cores / 192 threads
246 GiB system RAM
```

Local artifacts include:

| Artifact | Approximate stored size | Current authority/status |
| --- | ---: | --- |
| Gemma 4 26B-A4B q4 | 14.4 GB | stored GGUF size; configured conversation/planning backbone and measured in prior voice/planner evals |
| Ministral 3 8B instruct q4 | 5.2 GB | prior challenger, rejected on measured quality |
| Ministral 3 8B reasoning q4 | 5.2 GB | failed the recorded 0/1 schema-compatibility gate; no broad planning-suite comparison was run |
| CityWalker checkpoint | 1.75 GB | original GitHub checkpoint stored locally but inactive; no pixel/history inference adapter; local artifact license scanner reports `NOASSERTION` |

`build_navigator` still accepts only the `stub` and `grid` types. The active
navigation observation has no production RGB/RGB-D tensor stream, and the
configured `motion.backend: rl` has an empty policy path. “Downloaded” is not
“wired,” and “configured RL backend” is not a running policy.

The desktop can run useful inference, replay, and small adaptation. Official
InternVLA 8B artifact trees expose roughly 16.6–16.8 GB of BF16 weight files;
20–24 GB is only a Parcel planning estimate after runtime allocations, not an
official peak-memory measurement. Gemma's 14.4 GB is stored-file size; a prior
observed CUDA process occupied 15,280 MiB at idle, not at peak. Do not assume
that runtime can co-host vision encoders, simulator, and perception with safe
headroom. Measure peak/resident memory and latency under co-residency; use
quantization, time sharing, another device, or separate services where needed.
The active `.parcel` environment currently cannot import `torch`
(`ModuleNotFoundError`), so GPU hardware availability is not equivalent to a
reproducible training or model-serving environment. Build any candidate in a
pinned isolated image/environment rather than mutating the control runtime.

## Best released candidates by job

There is no honest single “best model” for the dog. These models solve different
interfaces, use different sensors, and report non-comparable metrics.

### Owner following: MiniCPM-RobotTrack

First shadow candidate because it is unusually close to the product target:

- public Apache-2.0 code and weights;
- compact policy with up to 31 historical frames plus a separate current
  fine-resolution frame, and eight future `(x,y,yaw)` waypoints;
- official Go2 EDU/Orin deployment instructions;
- author reports stable 5+ FPS and about 180 ms end-to-end on the Go2 path.

Its own reported EVT results include nonzero collision rates, and the deployment
material warns about behavior when a person is not visible. It is therefore not
sufficient as enrolled-owner identity or safe target-presence authority.
Parcel supplies an enrolled identity posterior, multi-frame confirmation, TTL,
reachability checks, common local planning, and independent metric-geometry
safety.

### Instruction grounding/navigation: InternVLA-N1

Best large desktop research challenger found:

- a slow System 2 grounds language to a visual goal;
- System 1/NavDP or DualVLN generates fast trajectories;
- code and multiple checkpoints are downloadable;
- authors demonstrate Go2 deployment and report System 1 above 30 Hz;
- author-reported DualVLN R2R SR/SPL is 64.3/58.5 and RxR 61.4/51.8.

These are not Parcel results. InternNav code is MIT; the current System 2 and
DualVLN README badges declare CC BY-NC-SA 4.0, while machine-readable Hugging
Face license metadata/artifact grants are absent. InternData-
N1's gated card text says CC BY-NC-SA 4.0 while its YAML badge says CC BY-SA
4.0. Those are not a clear weight grant. InternVLA therefore remains blocked
from acquisition/product use until artifact-by-artifact legal review; an
explicitly approved isolated offline study would still not authorize motion.

### Local obstacle avoidance/recovery: X-NavDP

Recent learned RGB-D local-trajectory/recovery challenger:

- very recent open code/checkpoint release with explicit quadruped/Go2 work;
- point-goal plus RGB-D and embodiment conditioning to a local trajectory;
- online RL post-training adds backing out, detour, and embodiment adaptation;
- authors report simulation SR rising from 61.20% to 84.28%, Go2 SR/SPL
  79.85/74.04, and 60–80% success across three ten-trial real hard-case sets.

The sample sizes and benchmark are author-defined; VRAM/Orin behavior is not
established. Only the original self-contained `baselines/x-navdp` source has an
MIT license file. The HF checkpoint has no license metadata, the parent NavDP
repository has no top-level license file while its README says CC BY-NC-SA
4.0, and Isaac/NVIDIA assets retain separate terms. Acquisition is therefore
blocked pending legal review. If approved for isolated research, it would
propose trajectories behind Parcel's validator/shield.

### Cross-embodiment local policy: CE-Nav

CE-Nav must enter the local-policy screen rather than treating X-NavDP as the
only Go2-specific learned option. Its official MIT repository now includes an
evaluation framework plus VelFlow expert and Unitree Go2 checkpoints. It uses
imitation learning followed by embodiment-specific RL refinement, which closely
matches the eventual bounded-adaptation hypothesis. However, the checkpoint
terms still require artifact-level review, Go2/VelFlow training code is listed
as forthcoming, and evaluation requires legacy Isaac Sim
2023.1.0-hotfix.1. First reproduce its own evaluation in an isolated image,
then adapt only its proposal output to Parcel's role-matched local-policy suite.

### First low-cost adapter: CityWalker

Parcel stores the original GitHub checkpoint. That local artifact currently
scans as `NOASSERTION`; the converted Hugging Face weights are labeled
Apache-2.0, so provenance and equivalence must be established rather than
transferring one artifact's terms to another. CityWalker consumes five RGB
frames, pose history, and target pose to emit five relative XY waypoints plus
arrival probability. It is a useful urban traversability prior. Its smaller
checkpoint makes onboard optimization worth profiling, but Go2/Orin latency
and memory have not been established. It does not understand language, owner
identity, open-vocabulary places, yaw, or social rules. The paper's reported
77.3% fine-tuned real-world success was on the authors' Unitree Go1 test cases
and must not be read as zero-shot Parcel performance.

### Semantic exploration: VLFM pattern

VLFM is a modular system rather than one weight. Its value-map/frontier pattern
is a promising immediate architecture reference for “find the
sidewalk/store/lamppost”: score
geometric frontiers with open-vocabulary visual evidence, then send one
short-lived goal to the common planner. Parcel should reuse its own occupancy,
controller, and safety rather than VLFM's PointNav execution.

### Specialized comparators

| Candidate | Useful role | Why it is not first |
| --- | --- | --- |
| NaVILA 8B | Go2-oriented instruction-to-mid-level-motion baseline | authors report 594.58 ms/18.5 GB FP16 and 367.80 ms/8.6 GB W4A16 on an RTX 4090; it emits a discrete verb plus continuous distance/angle that is mapped to velocity/duration; HF checkpoint license and packaged Llama 3 terms need review |
| StreamVLN | streaming video-language memory and action bursts | official work/repository is CC BY-NC-SA 4.0 and documents remote Go2 execution; target-device latency/VRAM are unspecified, and checkpoint/upstream model/data terms need separate review |
| Uni-NaVid | multi-task navigation and human-follow comparison | roughly 15.5 GB BF16 and A100-class evidence; unclear weight metadata |
| VAMOS 3B | steerable pixel-path planner plus embodiment affordance critic | inference/ROS code and planner/Spot/HOUND checkpoints are public; model is under Gemma terms and noncommercial-data restriction, code repository has no detected top-level license, and there is no Go2 affordance model |
| OmniNav | prospective exploration and slow/fast OVON/R2R/RxR comparison | public code/checkpoints, but legacy Habitat variants, no detected top-level code license, ModelScope artifact terms, and no Go2 deployment evidence require review |
| NoMaD/ViNT | teach-repeat, image-goal, topological route recovery | no open-language semantic planner |
| OmTrackVLA | compact 0.6B owner-tracking comparison | HF checkpoint declares MIT, but repository has no detected top-level license; no verified Go2/Orin deployment evidence found |
| FunctionGemma 270M | shadow parser for a fixed `TaskRequestV1` API | must be fine-tuned/calibrated; not a dialogue or navigation model; HF access and derivatives are subject to Gemma terms |

### Research references, not installable choices

- Qwen-RobotNav provides the clearest unified task-adaptive waypoint design,
  but its official repository says there is currently no plan to release
  weights.
- ABot-N1 and NavFoM/TrackVLA/SocialNav offer useful slow/fast, tracking, or
  social ideas. ABotN-Bench is now a public Apache-2.0 evaluation target with
  separate 3DGS terms; the remaining policy artifacts were absent, incomplete,
  or restricted in this audit.

## Why not train now

### 1. The measured bottleneck is not policy capacity

The two NAV_INSTRUCT minivals both measured 4% success. Failures were dominated
by planning, grounding/refusal, and termination. One Parcel BARN ROS episode
timed out while untouched Nav2 MPPI solved that same public world. This does not
prove MPPI is globally better, but it makes classical integration a much
stronger immediate experiment than reward optimization.

The organizers' 2026 BARN retrospective also reports that every physical
finalist used a classical navigation approach for the second consecutive year.
That is strong evidence for exhausting mature classical control in constrained
LiDAR navigation, not proof that classical methods solve Parcel's language,
owner-follow, semantics, city dynamics, or quadruped embodiment.

### 2. The training environments do not represent the product boundary

[`Go2Env`](../../../src/parcel_robot/rl/env.py) is explicitly a stub: its
observation/reward/termination plumbing omits contacts, torque, feet, actuator
delay, terrain, falls, thermal state, and real dynamics; several values are
constants or derived from the wrong observation slot.

The current MetaUrban wrapper's real-backend mode raises `NotImplementedError`.
Its default path is privileged kinematics with global pose/goal/person/obstacle
state and simple point-human motion. Its residual action is added to planner
output rather than selected from proven-safe trajectories. Normal headless city
motion directly updates the kinematic base, and people/owner identity are
scripted/oracle-shaped.

A policy trained here can learn simulator and reward bugs rather than
navigation.

### 3. There is no representative learning corpus

The repository has no aligned hardware dataset containing synchronized
camera/LiDAR/pose/instruction, expert candidate/actions, next state,
interventions, independent terminal predicates, owner identity evidence, and
outcomes. A recorder interface is not a dataset. Offline RL cannot recover
missing action support or fix wrong rewards.

### 4. There is no production policy-serving contract

Although an RL loader can read ONNX/TorchScript, no product call site supplies a
versioned observation/normalization ABI, freshness clock, frame transforms,
action mask, target-device deadline, rollback, safety-veto logging, or Unitree
delivery. Training before this contract risks producing an unusable artifact.

### 5. Safety and commissioning are incomplete

The hard-stop ordering defect, sensor-loss fallback, truth localization,
task/channel resume split, and uncommissioned Unitree axes/frame/modes all
precede learning. Online exploration on hardware is not acceptable. Low-level
RL would also conflict with Sport's authority and is a wholly separate LowCmd
program.

### 6. Foundation-model scale is a reuse problem

This workstation's hardware may support a small critic, LoRA, replay, or
simulator learning experiment, but that capability has not been profiled and
the active environment cannot import Torch. The candidates in this audit depend
on large pretrained backbones and/or data collection programs that Parcel has
neither reproduced nor validated. Training a new foundation navigation model is
therefore unjustified: start from released representations/policies and measure
the residual product gap first.

## Build-versus-reuse matrix

| Approach | Decision now | Trigger to reconsider | Hard containment |
| --- | --- | --- | --- |
| Classical Nav2 + frozen open weights | **do next** | honest state contract and frozen eval | proposals only; common planner; final independent metric-geometry stop |
| SFT/LoRA for typed intent or waypoint head | later, first adaptation | repeated model-addressable gap plus reviewed examples whose coverage and learning curve support the pilot | train parser/head only; no authority change |
| Behavior cloning / DAgger | later, before RL | strong expert exists; learner has a statistically credible rollout gap; interventions captured | sensor-only sim collection; teacher override; shadow deployment |
| Offline RL (IQL/TD3+BC/CQL class) | no | coverage analysis shows broad representative action support and rewards/terminal labels are trustworthy | conservative action support; candidate selection only |
| Bounded trajectory ranker/critic | **leading eventual hypothesis, not selected yet** | sampler feasibility spike passes and classical/open baselines plateau on a repeated attributable social/local-control gap | choose only among hard-admissible trajectories; it cannot select a masked candidate or alter the independent safety verdict |
| Standalone social-policy RL | no | real reactive-human simulator and owner tracking show a remaining comfort/proxemics deficit | output cost/preference, never collision authority |
| Planner/executive RL | no | only after task semantics/rewards become correct and model-addressable | typed plan proposals still compiled/validated |
| Online physical RL | reject | no near-term trigger | no exploration on people or production hardware |
| End-to-end language/camera-to-motor VLA | reject | only reconsider after multiple strong models plus narrow adaptations share a verified ceiling | even then retain bounded waypoint and external safety boundary |
| Custom low-level locomotion RL | separate future program only | measured Sport limitation justifies risk/cost | Unitree reference env, Sport off, LowCmd isolation, sim2sim/HIL/fall/thermal gates |

Concrete data volumes and effect thresholds must come from coverage analysis,
learning curves, baseline variance, and a predeclared power analysis—not a
generic transition count. Freeze them before collecting or tuning against the
promotion split.

## Prerequisites for a learning pilot

Requirements depend on the learned boundary; a small intent parser does not
need the transition corpus required by a navigation ranker.

**Common gates for every learned component:** clean source/config/evaluator
freeze; a versioned input/output/normalization ABI; target-device latency and
resource deadline; immutable model/code/data provenance; out-of-process shadow,
fallback and rollback; frozen task-level comparison; and independent outcome
labels for the component being changed.

**Typed-intent SFT/LoRA:** a stable `TaskRequestV1`, speaker/channel policy,
schema and semantic validators, reviewed utterance labels, held-out speakers and
paraphrases, calibration/abstention tests, and unchanged executive authority.
It does not require millions of navigation transitions.

**Waypoint or trajectory imitation/ranking:** exact-zero/fail-closed safety,
atomic task lifecycle, calibrated camera/LiDAR and real MAP/ODOM state, no
privileged policy fields, strong grid/RPP/MPPI/open-model baselines on the same
contract, a sensor-only simulator/replay path, expert candidates or
interventions, and independently verified geometry/terminal outcomes.

**Offline or online RL:** all trajectory-ranking gates plus either (a) broad,
representative logged action support and trustworthy rewards for offline RL,
or (b) a real reactive simulator adapter with delay/dropout/extrinsic/dynamics
randomization, held-out layouts/human behaviors, and hard shielding for online
simulation RL. A pilot must quantify state/action/scene coverage, rare hazards,
and real-shadow distribution overlap before training; aggregate transition
count alone is not sufficient.

**Low-level locomotion learning:** a separate LowCmd program with Unitree
reference dynamics, contacts/feet/torque/thermal/fall observations, sim-to-sim,
HIL, fall and hardware commissioning gates. None of the navigation work grants
this authority.

## Earliest justified learned-ranking experiment

If the sampler feasibility spike succeeds, compare a bounded local trajectory
ranker/critic. This is discrete selection, not the additive action residual from
Residual RL:

```text
explicit candidate sampler produces K feasible 2–3 s SE(2) trajectories + HOLD
  -> hard masks remove stale/colliding/road/footprint/TTC-invalid candidates
  -> learned ranker selects one index or abstains
  -> deterministic validation repeats
  -> common controller + final independent metric-geometry monitor + Sport
```

Stock Nav2 MPPI is a controller and does not expose its internal sampled
trajectories as a stable K-candidate API. Before training, run a feasibility
spike: either add a separately reviewed candidate sampler/plugin around the
same costmap and kinematics, or abandon the K-choice formulation. Do not patch
the benchmark or assume an internal MPPI representation is a product contract.

Input is a short sensor-derived history: occupancy/dynamic-track uncertainty,
goal/formation vector, current velocity, and task mode. It excludes exact world
polygons, future actor truth, simulator IDs, and global truth pose.

Training branches after the same BC/DAgger baseline:

1. BC/DAgger on MPPI/ORCA/operator choices;
2. if a representative simulator is valid, shielded PPO or constrained online
   optimization in simulation, with at least three seeds; **or**
3. if logged action support is broad and rewards are trustworthy, a
   conservative offline-RL comparison. Offline and online RL are alternatives,
   not mandatory sequential stages.

Collision, stale sensing, forbidden road entry, speed, footprint, and TTC are
constraints, never reward tradeoffs. Social formation, progress, path/time,
pass-side preference, jerk, and oscillation can be ranking objectives.

Before training, derive the frozen held-out episode count from baseline variance
and the predeclared practically meaningful effect, and derive the p99 ranker
deadline from the measured controller budget. Promotion then requires paired
seeds, a statistically credible gain, no family/termination regression, zero
hard violations with exposure/confidence bounds, noninferior
near-miss/proxemics/jerk, deterministic HOLD on every miss (or re-admission of
the same existing authorized, fresh, independently grounded classical goal
through healthy state/transform/geometry gates), hardware shadow,
and a separate safety review. None of those gates is waived because the pilot
hits its compute cap.

## Bounded pilot budget and stop loss

This is a future planning cap, not authorization to train now:

- **now:** 0 RL GPU-hours;
- **after every prerequisite:** at most 120 single-GPU hours and one 2–3 week
  engineering sprint for the first reranker pilot;
- staged planning envelope: up to 16 h for BC/DAgger, then—only if its learning
  curve and held-out gap justify continuation—up to 36 h for three independent
  RL seeds, up to 48 h for baselines/ablations, and the remainder for replay and
  latency work;
- stop at every stage gate if its predeclared development effect is absent, a
  reward exploit or hard-constraint bypass appears, sensor-only performance
  collapses, or independent seeds fail to reproduce; do not spend the remaining
  cap merely because it was budgeted;
- not budgeted: foundation VLA pretraining, custom low-level Go2 locomotion, or
  physical online RL.

## Final implication

The owner's prior is correct: strong released policies and mature planners
should be exhausted before custom RL. Parcel's durable advantage is the
companion-specific composition—voice, intent, identity, semantic memory,
behavior arbitration, verified task completion, and safe embodiment—not a
from-scratch motor policy. Learning should hill-climb one measured residual
without changing those authority boundaries.
