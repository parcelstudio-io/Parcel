# Evaluation program and phased roadmap

## Evidence policy

Every report and ledger row must declare one evidence class:

```text
derived_rescore       old observations under a new scorer; not a run
contract_smoke        imports/schema/device/service only; no task metric
synthetic_unit        component under generated inputs
product_headless      unchanged product path in deterministic simulation
external_proxy        nonofficial/reduced/deployment-disabled external-shaped proxy
external_public       official-shaped public benchmark episodes
external_hidden       organizer-held episodes/protocol
HIL                   hardware in loop, body restrained or actuator bounded
physical_supervised   staffed/fenced physical task course
```

Never promote a metric to a stronger class in prose. In particular:

- the 0.12/0.16 NAV_INSTRUCT values are derived rescoring, not new runs;
- the native BARN 44% is non-official and deployment-disabled;
- upstream MPPI on one BARN world is not a Parcel score;
- Habitat CUDA/EGL/render evidence is not a navigation result;
- simulator metadata semantics and owner identity do not prove camera
  perception or re-identification.

## Evaluation architecture

```text
frozen scenario + sensor/fault seed
            │
      simulator/service
            │ camera/LiDAR/odom only
            v
 unchanged Parcel product runtime ──> actuator adapter
            │                              │
            │ typed trace                  │ executed commands/state
            └──────────────┬───────────────┘
                           v
              isolated truth-side evaluator
                           │
                 immutable result + ledger

separate attribution replays:
  oracle grounding only
  oracle identity only
  oracle route only
  scripted controller only
The first replay that repairs an episode identifies the causal boundary;
none is a product score.
```

The evaluator must reject oracle fields in the agent observation. The robot
must issue its own stop/hold; the scorer independently checks the terminal
predicate and settled feedback. A crash, OOM, missing telemetry, sensor timeout,
planner timeout, or model deadline miss is a failed episode, not excluded data.

## Phase 0 — make evidence and authority valid

### 0A. Freeze the current baseline before fixes

Freeze:

- source commit and exact dirty patch (prefer no patch);
- environment/container and dependency lock;
- robot/navigation/prompt/model hashes;
- adapter and evaluator hashes;
- scenario manifest, episode IDs, seeds, sensor/fault schedules;
- CPU/GPU/power/thermal/resource limits.

Run current product-path and component baselines before changing safety,
lifecycle, planners, or models. The physical path remains disabled; known
unsafe/degraded cases are exercised only in unit/headless fault tests. Historical
artifacts remain in the ledger and are not silently overwritten.

### 0B. Exact-zero and sensor-loss safety

- Add a final post-shaper independent metric-geometry stop gate.
- Reset motion shaping/smoothing and exercise the manager stop path.
- Fail closed on stale/missing LiDAR, pose, transform, or control feedback.
- Establish the typed pose/transform covariance, timestamp, epoch, and health
  contract. Simulator truth may implement it only in labeled simulation; this
  phase does not claim a physical localization producer.
- Inject clock skew, dropped scans, malformed tracks, pose loss/jump, manager
  delay, backend exceptions, and E-stop races.
- Record raw evidence age, gate decision time, final command, manager receipt,
  feedback stop time, and physical/sim stopping distance.

Gate: every hard-stop trace has an exact-zero final HAL command on the same
dispatch; no motion resumes without fresh evidence and an active authority.

### 0C. Executive and channel lifecycle

- Atomic pause/resume/cancel/lease transfer by task and revision.
- Separate terminating `ApproachOwner` from persistent `FollowFormation`.
- Store invariants per task; implement admission/queue/precondition/step/task
  deadlines and bounded recovery.
- Test amendments, barge-in, manual takeover, emergency, task replacement,
  stale planner result, clarification expiry, and cancel acknowledgment in
  every task state.

Gate: no channel can move without a live authorizing task; no task can report
success while its physical channel persists; strict resume xfail becomes pass.

### 0D. Freeze the post-fix baseline

Rerun the identical product-path, controller, and fault episodes after 0B/0C.
Record the paired delta, newly passing strict regressions, and any changed
latency/stopping behavior. This becomes the base for state/perception, planner,
and learned-model comparisons.

## Phase 1 — one honest state and task contract

Parallel lanes after Phase 0 interfaces freeze:

### State/perception lane

- Real/sensor-faithful RGB/depth/LiDAR/IMU capture with hardware timestamps.
- Implement the real versioned MAP/ODOM localization producer with covariance,
  health, transform history, and correction epochs behind the Phase 0 contract.
- Fast regions/entities/people; enrolled owner association with ambiguity.
- Eliminate simulator-only IDs/polygons/future tracks from product input.

### Instruction/executive lane

- `TaskRequestV1` becomes the only semantic parse.
- Candidate-aware clarification and amendment lineage.
- Relation/quantity/units/formation registry.
- Sensor-grounded terminal witnesses and typed failures.

### Evaluation lane

- Route NAV_INSTRUCT through `RobotRuntime.handle_text`/voice-final path,
  router, compiler, validator, executive, adapter, controller, and stop witness.
- Retain direct-controller tests as a lower-level suite, clearly named.
- Expand absent/unreachable/ambiguous/unsafe-target tiers.

Gate: product-path command families below work with the same controller and
truth-side evaluator, and oracle counterfactuals can identify the failing layer.

## Phase 2 — strong classical navigation and social behavior

### Nav2 spike

After P0 and the in-Parcel RPP-style regulation baseline pass, run a time-boxed
isolated sidecar challenger with an identical observation/action adapter.
`grid_v1` remains the sole production writer; Nav2 promotion is attribution-
gated, not implied by scheduling the spike:

1. Smac 2D + Regulated Pure Pursuit;
2. Smac/State Lattice + MPPI;
3. current Parcel grid controller.

Run them on the same local and BARN episodes. Validate the smoothed path, use
one velocity smoother, then apply the final independent metric-geometry
monitor. Penalize lateral travel but retain it for avoidance/manual behavior.

Run two complementary A/B protocols. A **matched-information** comparison gives
each controller/model the same camera/LiDAR/state fields and adapter so the
component effect is identifiable. A **full-product** comparison gives each
system its intended, permitted inputs and measures the deployable composition.
Report both. Never attribute an RGB model versus LiDAR-only classical delta to
the model alone.

### Owner/social control

- Replace direct follow twist with a formation-goal generator feeding the same
  planner.
- Fix dynamic-agent cost aggregation and risk-based track selection.
- Add uncertainty-aware short-horizon prediction and owner occlusion search.
- Keep stranger/group proxemics as soft context outside the raw geometry stop.

Gate: statistically credible improvement over the current grid baseline on a
public-development BARN `external_proxy` and product navigation; no hard-
safety, identity, lateral-motion, jerk, or p99 latency regression. Park or kill
the sidecar if the frozen comparison does not isolate a useful controller gap.

## Phase 3 — learned proposers in replay and shadow

### Shared harness

Every candidate emits `NavProposalV1`, but comparisons are role-specific. An
owner-follow proposer competes on frozen owner-follow episodes, a semantic
planner on semantic-search episodes, and a local policy on point-goal/detour
episodes. Within a matched-information comparison, baseline and candidate
receive the same declared observation contract/history. If a model natively
requires a different permitted sensor subset, run a separate full-product lane
and attribute the result to the composition, not the model alone. Every model
runs out of process with:

- latest-frame-wins queues and bounded memory;
- task/revision/generation and observation IDs;
- explicit capture, queue, inference, validation, and selection latency;
- finite/frame/bounds/TTL/reachability checks;
- deterministic fallback and safety-veto reason;
- model/code/data/license provenance and peak VRAM/thermal telemetry.

### Experiment order

1. Existing CityWalker checkpoint only after original-asset license-scope and
   custom-code review. Its bytes match the official v1.0 asset (SHA-256
   `a42326778e5e318c6222575dc5e02f1794d9a60cce4dc8f8a2ee5df7dc6d1c29`),
   but byte identity does not supply the missing asset-specific license notice.
2. CE-Nav and X-NavDP point-goal/local-trajectory shadows only after each
   checkpoint, dependency, and simulator-asset review clears.
3. MiniCPM-RobotTrack owner-follow shadow only after core and transitive vision-
   encoder/deployment terms plus custom code clear.
4. VLFM-style semantic frontier scoring for unseen objects.
5. InternVLA-N1 System 2/DualVLN only after explicit legal approval for the
   intended isolated research use; README badges declare CC BY-NC-SA 4.0,
   while machine-readable Hub metadata/artifact grants are absent.
6. NaVILA, StreamVLN, Uni-NaVid, VAMOS, OmniNav, and NoMaD/ViNT as specialized
   legally eligible comparators.

No model advances because of an author's score. It advances only on Parcel's
frozen paired protocol, then an external suite, then HIL/physical gates.

## Phase 4 — simulation and benchmark ladder

### Tier 1: Parcel product headless

Run on every relevant PR. Required command families:

- go/walk/run to visible, out-of-view, distant, ambiguous, absent, and
  unreachable object/region/place;
- `inside`, `near`, `next_to`, `towards`, `wait_by`, and safe-side constraints;
- walk away/toward N steps with unit normalization;
- orbit owner N times with small common-sense radius;
- approach owner, follow beside/behind, stop following, pause/resume/cancel;
- owner stops, turns, runs, is occluded, crosses distractors, and leaves range;
- low-battery return/sit and social reaction execute/defer/drop;
- mid-task correction, clarification answer, barge-in, model timeout, sensor
  loss, localization correction, and manual takeover.

### Tier 2: BARN ROS2

First external controller gate. Use Parcel's repository-local/public
development worlds for reproducible nonofficial regression. The 2026 official
simulation evaluation uses **50 new organizer-hidden environments with 10
trials each**; only that organizer run supports a leaderboard/top-decile claim.
Preserve the official evaluator and disclose resource use. BARN measures LiDAR
constrained navigation, not voice, semantics, following, city behavior, Go2
gait, or physical safety.

Compute rules differ by stage. The official page specifies an Intel Xeon Gold
6342 simulation platform and says simulator overhead prevents a specific
compute restriction; it does not promise a GPU. The physical stage uses an i3/
16 GB computer and explicitly has no GPU. Local ROS/Gazebo regression is
primarily CPU. A learned candidate must either fit the relevant declared path
or remain a separately labeled research comparator.

Retain DynaBARN only as a separate nonofficial dynamic-obstacle regression. The
completed 2026 retrospective says simulation participation was optional, its
parenthesized result was excluded from final scoring/ranking, and the physical
dynamic arena was not run. The organizers plan to focus the competition on
static obstacles for the foreseeable future. Do not present DynaBARN as a 2026
official ranking, combine it into static BARN, or imply it predicts owner-
follow/city-crowd quality.

### Tier 3: Follow-Bench

Best external owner-follow planner comparator. Maintain two lanes:

- oracle target state to isolate formation/local planning;
- camera-derived enrolled-owner tracks to measure the product.

Use target trajectories, crowds, corridors, intersections, doorways, clutter,
back/side formations, range sweeps, and 100 randomized trials per configuration.
The benchmark is largely CPU/CVXPY/OSQP; GPUs are optional for learned models.
Review the top-level and component licenses before vendoring.

### Tier 4: MetaUrban

Best dynamic-city stress service: procedural sidewalks/roads/street furniture,
pedestrians, cyclists, vehicles, RGB/depth/semantic/LiDAR, PointNav/SocialNav,
and Gym/ROS bridge. Run as a pinned Python 3.9 GPU service; full assets require
registration/terms review. Agent observations expose only permitted sensors and
localization; semantic/collision truth stays evaluator-side.

GPU: suitable for the RTX 5000 Ada 32 GB in principle, but measure full-stack
VRAM and latency. The current Parcel MetaUrban path is unimplemented.

### Tier 5: HuNavSim 2 / Arena-Rosnav

Use HuNavSim for ROS2 social-force/group/queue/proxemics/jerk evaluation and
Arena for broader planner comparisons. HuNavSim can run over Gazebo/Isaac/
Webots; start with headless CPU/Gazebo, then add an Isaac GPU lane if it buys
needed sensor/physics fidelity. Neither is a product benchmark by itself.

### Tier 6: Habitat 3 / VLN-CE / EVT / NaVILA-Bench

Use for indoor find-and-follow, distractors/occlusion, language paths, and
physics-aware quadruped research. Habitat's current official repository states
that Meta no longer actively maintains releases after v0.3.4; VLN-CE depends
on a legacy stack and scene/data terms. Keep these in isolated containers.

The current desktop passed CUDA/EGL/archived Habitat import and test-scene
render/action smokes, but has not run a Parcel navigation episode or metric.

Add **ABotN-Bench** after the product-path evaluator is stable. Its public
PointBench/POIBench/short-horizon OVON interface makes it a useful GPU-backed,
closed-loop lane for waypoint, entrance, and approach skills, including
CityWalker and OmniNav comparisons. Keep it role-specific: 3DGS RGB evaluation
does not validate Parcel's LiDAR/camera fusion, owner following, quadruped
physics, or physical safety. The evaluator is Apache-2.0, while its render
server, scenes, and datasets retain separate terms.

### Tier 7: OmniGibson/BEHAVIOR for interactive indoor tasks

Stanford's current BEHAVIOR documentation identifies OmniGibson on Isaac Sim as
the successor to iGibson. It is the better future lane for high-fidelity indoor
physics, articulated/interactive objects, household scene predicates, and
long-horizon activities. It is **not** the next dynamic-city or owner-follow
gate: MetaUrban, Follow-Bench, and HuNavSim map more directly to those failures,
and Parcel does not yet manipulate objects. Add OmniGibson only after basic
indoor navigation/perception works and a concrete interactive task requires its
additional physics/assets. Dataset and Isaac Sim terms remain separate.

### Quadruped embodiment physics gate before HIL

Every **deployable composition** that survives planar and semantic evaluation
must run in a Go2-specific Unitree MuJoCo or Isaac lane before hardware-in-loop.
This tests the complete controller/planner/adapter combination rather than
pretending each model independently owns dynamics. Reproduce
the measured footprint, mass/inertia approximation, gait/Sport-like velocity
response and command delay, acceleration/deceleration, slopes, curbs, stairs,
slip, contact, falls, sensor mount vibration, and stopping envelope. Report
fall/contact/foot-slip/attitude and completion metrics alongside navigation.

This is an embodiment transfer gate, not another leaderboard. BARN, Habitat,
MetaUrban kinematics, or circular-base proxy success cannot validate quadruped
dynamics, low obstacle visibility, actuator lag, or fall risk.

### Physical-operation safety case before HIL

Freeze the intended ODD (surface, friction, slope/curb/stair limits, weather,
illumination, crowd density, speed, sensor visibility, compute/thermal state,
connectivity, fence and supervisor). Build an FMEA/STPA-style hazard log with
severity/exposure/controllability, mitigation owner, linked verification
evidence, residual-risk acceptance, incident/bag replay process, and a named
go/no-go signoff. Commission frame/axes/modes, independent E-stop, sensor
coverage, stopping envelope, and degraded states against it.

Manual joystick/UI/API commands use the same authenticated authority, limits,
watchdog, final geometry monitor, and E-stop as autonomous motion. No reference-
stack/manual bypass of collision avoidance is accepted as a Parcel product path.

## Scenario matrix

Freeze episodes across these orthogonal axes rather than averaging easy cases:

| Axis | Required strata |
| --- | --- |
| Target visibility | visible; outside frustum; behind occluder; beyond local map; absent; unreachable |
| Language | canonical; paraphrase; politeness/safety rationale; quantity/units; correction; ambiguity; negation/hypothetical |
| Relation | inside; near; next-to; towards; wait-by; avoid-road; behind/beside owner |
| Geometry | open; doorway; narrow corridor; cul-de-sac; curb/stair/drop-off; glass/dark/reflective obstacle |
| Dynamic agents | none; crossing; head-on; overtaking; cut-in; group/F-formation; queue; dense opposing flow |
| Owner | steady; stop/start; turn; accelerate; short/long occlusion; similar-clothes crossing; out of range |
| Sensors/state | blur/night/glare; frame drop; stale LiDAR; timestamp skew; extrinsic error; pose drift/jump/loss |
| Compute | warm/cold; concurrent Gemma/TTS/perception; model timeout; OOM; network loss; thermal throttle |
| Task lifecycle | idle; busy interruptible; busy critical; checkpoint; paused; clarifying; recovery; cancel in flight |
| Command trust | enrolled owner; authorized controller; bystander; TV/phone replay; remote stream; OCR/signage prompt injection; ambiguous speaker; anyone-issued emergency stop |

## Metrics

### Task and instruction

- success rate with agent-issued stop;
- independent predicate accuracy and false-success rate;
- SPL, soft-SPL, nDTW/sDTW where the benchmark supports them;
- distance-to-goal, path length, route efficiency, time, and recovery count;
- parse, admission, grounding, localization, route, control, and termination
  success waterfall;
- clarification precision, minimum-question efficiency, refusal/abstention
  correctness, amendment/cancel success;
- per-family and per-tier results, not only aggregate.

### Safety and motion quality

- collisions/contact, forbidden road/region entries, near misses, minimum TTC,
  minimum signed clearance, safety interventions, and deadlocks;
- exact-zero stop latency, measured stopping distance, sensor age at decision;
- speed, acceleration, jerk, cumulative yaw, oscillation/stop-start count,
  reversal and lateral-motion fraction;
- raw shield veto rate and reason; stale/invalid proposal rate.

### Owner and social quality

- top-1 owner identity, identity switches, false reacquisition, ambiguity rate;
- reacquisition success/time under short and long occlusion;
- time in requested formation band, angular error, visibility, radial RMSE;
- stranger intimate/personal-zone time, group/F-formation intrusion, pass-side
  compliance, directional collision, social work/comfort metrics.

### Latency and resource metrics

Define every event on a monotonic trace clock and carry `turn_id`, `task_id`,
`task_revision`, and cancellation/barge-in epoch across processes. `UserQueryEnd`
is the capture-time end of owner speech chosen by VAD/end-of-turn logic, not the
later ASR callback. Preserve the requested compatibility headlines, but never
mix modalities silently:

- `UserQueryEndToFirstReasoningResponse`: first committed typed intent/task
  proposal usable by the executive;
- `UserQueryEndToFirstReasoningToken`: first model token or structured delta,
  a diagnostic that does not imply an executable proposal;
- `UserQueryEndToFirstResponse`: first rendered audio sample in audio mode, or
  first committed robot response log in text-only mode; always record the
  modality;
- `UserQueryEndToFirstLoggedText`;
- `UserQueryEndToFirstTTSAudioProduced`;
- `UserQueryEndToFirstAudioRendered` (the primary audible-response metric).

Canceled or superseded generations cannot satisfy first-response latency.
Report failures/timeouts separately rather than dropping them from latency.
For a remote inference host, use synchronized clocks with recorded error bound
or compute service spans locally and propagate the original capture event;
never subtract unrelated wall clocks.

Also record p50/p95/p99 and deadline misses for:

```text
audio capture -> VAD/end-of-turn -> ASR final
ASR final -> intent route -> acknowledgment
ASR final -> TaskRequest -> admitted task / clarification
camera capture -> detection/segmentation -> owner association
required metric-sensor capture -> fused geometry -> independent safety verdict
snapshot -> global plan -> local command
model queue -> inference -> proposal validation -> selection
arbiter -> shaping -> final safety -> manager send -> controller feedback
task start -> first motion; cancel -> exact-zero command -> settled feedback
```

Record CPU, GPU utilization, peak/resident VRAM, queue depth, dropped frames,
power/temperature, and co-resident service identities with every latency run.

For models requiring custom or remote code, also record immutable repository
revision, artifact hash, reviewed-code/SBOM digest, sandbox policy, network and
credential denial, and process exit reason. A supply-chain or sandbox failure
is a failed/abstained proposer episode, not a reason to bypass isolation.

## Statistics and promotion

- Freeze development, public-validation, and hidden-promotion splits before
  tuning.
- Baseline/candidate use identical episodes, seeds, faults, and resource limits.
- Use exact McNemar tests and paired success confidence intervals; paired
  bootstrap intervals for SPL, latency, clearance, jerk, and social metrics.
- Repeat nondeterministic GPU runs; report variance and worst seeds.
- For zero observed critical events, report exposure and a one-sided confidence
  bound. Never write “safe” from zero observed simulation collisions.
- Report every stratum; no aggregate gain hides a sidewalk, owner identity,
  absent-target, cancel, or terminal-verification regression.

A candidate promotes only when all hold:

1. zero critical collision, forbidden road entry, false owner, unsafe action,
   and false success in the promotion set;
2. statistically credible paired primary-metric gain with a predeclared
   practically meaningful effect;
3. no task-family success regression beyond its frozen margin;
4. no p99 safety/control latency regression or deadline violation;
5. timeout/OOM/network/model failure degrades to deterministic HOLD; the same
   existing classical goal may continue only after task/revision authorization
   and unchanged evidence, pose/transform, controller, and metric-geometry
   safety gates re-admit it;
6. gain reproduces in a product suite and at least one relevant external suite;
7. license/provenance and target-device resource gates pass;
8. HIL/physical authorization remains a separate review.

## Top-decile objective

“Top 10 percentile across all evals” is a research target, not yet proven and
not a single scalar objective. For each benchmark record:

- exact version/protocol/split and whether an active leaderboard exists;
- eligible hardware/resource rules;
- published field distribution or threshold used to infer the percentile;
- official public versus hidden/organizer-attested status;
- metrics that do not transfer to the dog embodiment.

Parcel behavior remains unchanged behind adapters. A BARN gain cannot trade off
owner identity or sidewalk safety; a VLN score cannot trade off collisions; a
social score cannot authorize poor instruction termination.

## Result ledger contract

Each run writes one immutable report and one append-only ledger row:

```json
{
  "run_id": "...",
  "timestamp_utc": "...",
  "evidence_class": "product_headless",
  "change_description": "...",
  "source": {"commit": "...", "dirty_patch_sha256": "..."},
  "environment": {"image": "...", "gpu": "...", "resource_limits": {}},
  "scenario": {"manifest_sha256": "...", "episode_digest": "..."},
  "components": {"adapter": {}, "model": {}, "config": {}, "evaluator": {}},
  "metrics": {},
  "failure_histogram": {},
  "latency": {},
  "safety_exposure": {},
  "report_path": "...",
  "report_sha256": "...",
  "does_not_prove": []
}
```

Derived rescoring rows carry `parent_run_id`, scorer hash, and both frozen and
derived metrics. They never overwrite the source run or enter a promotion
comparison as an independent sample.

## Immediate next four implementation slices

1. **Evidence/interface freeze:** capture the current source/patch/config,
   product/fault baseline, scenarios, and result hashes before edits. Freeze
   minimal versioned task/state/perception/navigation-proposal/safety ABIs so
   parallel lanes cannot invent competing contracts; this authorizes no model.
2. **Authority slice:** exact-zero post-shaper stop, physical sensor-loss
   fail-closed behavior, atomic task/channel resume, per-task invariants and
   real deadlines. Rerun the identical post-fix baseline.
3. **Honest state slice:** implement the real MAP/ODOM localization producer,
   synchronized camera/
   LiDAR producer, owner identity state, one relation/witness registry, and
   product-path NAV_INSTRUCT.
4. **Strong baseline slice:** port RPP-style regulation into `grid_v1`, then run
   a time-boxed Nav2 RPP/MPPI challenger; `grid_v1` stays the production writer
   unless promotion gates pass. Scaffold the BARN adapter after P0-F, execute it
   only when the compared controllers exist, and start Follow-Bench after owner
   identity/formation. Freeze results before executing any legally approved and
   provenance-pinned CityWalker/CE-Nav/X-NavDP/MiniCPM/InternVLA proposer.

These slices repair the measured system before introducing a new source of
variance, while leaving perception, behavior, navigation, evaluation, and model
integration teams able to work in parallel behind frozen contracts.
