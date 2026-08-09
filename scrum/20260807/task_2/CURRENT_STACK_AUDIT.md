# Current navigation and behavior audit

**Audit date:** 2026-08-07. **Code basis:** `main` at `4f6342d` plus the
then-current dirty working tree. This is a source audit, not a physical safety
assessment. The targeted product-path tests run during this audit were:

```text
.parcel/bin/python -m pytest \
  tests/test_motion_shaping.py tests/test_closed_intent_product_path.py -q
61 passed, 1 xfailed, 3 warnings in 1.61 s
```

The model-lock checks also passed (`2 passed in 0.07 s`). A direct local
SHA-256 read and an independent stream of the official CityWalker v1.0 asset
both produced
`a42326778e5e318c6222575dc5e02f1794d9a60cce4dc8f8a2ee5df7dc6d1c29`
(1,752,028,242 bytes). This establishes byte/source identity, not the original
asset's license scope or runtime safety.

The strict xfail is intentional evidence of the task/channel resume defect. A
full current-worktree suite or navigation evaluation was not run. The 2,130
passing suite in task 1 belongs to that task's earlier snapshot.
The command above was observed on a dirty/moving tree and was not stored as an
immutable result with a dirty-patch digest; it must not be treated as P0-0's
frozen baseline.

## Current product path

```text
final transcript
  -> emergency/manual literal path OR deterministic intent router
  -> local PlanSketch OR optional Gemma PlanIR
  -> system compiler + validator
  -> TaskExecutive
  -> semantic runtime adapter
  -> navigation / search / follow / spatial / gesture channel
  -> time-limited CommandArbiter intent
  -> velocity smoother
  -> proximity + constant-velocity TTC checks
  -> S-curve actuator shaping
  -> ControlManager (50 Hz configuration, watchdog, feedback, lifecycle)
  -> simulator adapter OR uncommissioned Unitree Sport adapter
```

The shape is fundamentally sound: language does not directly control motors,
the executive has typed skills, arbitration uses expiring leases, the Go2's
onboard Sport controller retains balance/gait, and semantic success can require
both a spatial witness and a settled body. The problem is that several seams
are half-wired and the default evidence is still simulator truth.

## What should be preserved

- Literal emergency handling and the latched `ControlManager` E-stop path.
- Unitree Sport as the low-level gait/balance controller.
- Typed PlanIR/PlanSketch, system-owned compiler fields, validation, and the
  `TaskExecutive` resource/checkpoint concept.
- TTL-based motion arbitration and generation checks.
- Rolling camera/LiDAR-derived occupancy planning, inflated footprint, A*, and
  forward-preferred/rotate-first behavior.
- Lateral velocity in the HAL for manual control and constrained avoidance,
  while penalizing it for ordinary destination travel.
- Independent semantic terminal verification rather than trusting a planner's
  `arrived` string.
- Honest xfails and explicit degraded-mode telemetry.
- Evaluation adapters that leave Parcel behavior unchanged.

## P0 — fix before learned navigation or physical motion

### P0.1 Final stop ordering can emit residual motion

`RobotRuntime._dispatch_active` in
[`runtime.py`](../../../src/parcel_robot/runtime.py) applies proximity/TTC
gating, then calls the S-curve shaper. The shaper's `emergency=True` branch in
[`navigation/velocity_shaping.py`](../../../src/parcel_robot/navigation/velocity_shaping.py)
removes the jerk limit but still slews by its acceleration bound; it is not an
exact-zero bypass. The existing
[`test_motion_shaping.py`](../../../tests/test_motion_shaping.py) verifies only
that this drop is faster than normal smoothing, so the test currently preserves
residual motion.

This finding does **not** mean the explicit latched E-stop is absent: that path
calls `ControlManager.emergency_stop()`. It means an ordinary raw-sensor
proximity/TTC stop can still hand the controller a nonzero command on the stop
tick. Existing comments in `configs/robot.yaml`, `docs/MOTION.md`, and
`docs/COMPANION_NAVIGATION_ARCHITECTURE.md` claiming every stop is unsmoothed
are stale relative to this behavior.

Required correction:

1. Distinguish `comfort_stop` from `hard_safety_stop` in the type system.
2. After every shaper and learned component, re-evaluate the latched independent
   metric-geometry verdict and force the command to exact zero.
3. Reset smoother/shaper state and call the manager stop path where appropriate.
4. Assert the final HAL-observed command is exactly zero on the same dispatch.
5. Derive the forward safety envelope from measured latency and deceleration:
   `margin + v * e2e_latency + v^2 / (2 * measured_deceleration)`.

### P0.2 Missing sensing can become open-loop translation

The active `grid_v1` navigator in
[`configs/navigation/default.yaml`](../../../configs/navigation/default.yaml)
falls back loudly to the point-goal stub when its calibrated scan is missing.
That is useful for simulator/API continuity, but a physical deployment must not
translate on a stale, missing, malformed, or frame-invalid LiDAR/pose input.
Today one malformed dynamic track also disables the entire soft social cost
layer for that tick in
[`grid_navigator.py`](../../../src/parcel_robot/navigation/grid_navigator.py).

Required correction: validate tracks individually, publish `TrackSetHealth`,
rank/retain the riskiest tracks, and make physical freshness/frame health a
hard HOLD/STOP precondition. Soft semantic/social layers may disappear; raw
geometry safety may not.

### P0.3 Pose health is not a fail-closed contract; production localization is absent

[`configs/navigation/pose.yaml`](../../../configs/navigation/pose.yaml) ships
with `provider: truth`; `RobotRuntime` constructs `TruthPoseProvider`. The drift
profiles exercise interfaces but are not SLAM/localization. Several paths still
read raw observation poses, and map-frame goals can meet odometry-frame robot
state without a commissioned transform.

P0 correction: freeze the timestamped MAP/continuous-ODOM contract, transform
history, covariance, health, correction epoch, and explicit degraded/lost
behavior; make physical translation fail closed when those inputs are not
healthy. Truth may implement the contract only in labeled simulation.

Phase 1 correction: implement and calibrate the real localization producer.
The local controller consumes continuous ODOM; global and semantic goals live
in MAP and are transformed at the relevant observation time. No identity, POI,
or terminal predicate may bypass this seam. P0 defines authority/health; it
does not claim the real producer exists.

### P0.4 Resume can separate motion from its authorizing task

[`TaskExecutive.resume_task`](../../../src/parcel_robot/brain/executive.py)
exists, but the runtime's closed-intent resume branch restores navigation,
follow, or search without resuming the executive task. The strict xfail
`test_resume_also_restores_the_executive_task_record` records the product-path
result: the channel moves while the task remains `suspended`, so its timeout,
verification, and recovery are no longer running.

Required correction: suspend/resume/cancel/lease-transfer must be atomic over
`{task_id, revision, step_id, channel, resources}`. A channel may not reacquire
the base without the authorizing task revision being active.

### P0.5 Persistent and terminating owner behaviors are conflated

The local plan for “come here” compiles to persistent `FollowFormation`.
[`runtime_adapter.py`](../../../src/parcel_robot/brain/runtime_adapter.py) can
then report the skill successful while the follow controller keeps running.

Required correction:

- `ApproachOwner` terminates after reaching a verified safe owner-relative
  region and settling;
- `FollowFormation` is explicitly persistent/nonterminal until cancel or lease
  transfer;
- `OrbitOwner` terminates on swept-angle, radial-error, collision-free, and
  stopped witnesses;
- adapters cannot delete a dispatch while its controller remains authoritative.

### P0.6 Invariants, recovery, and waiting deadlines are incomplete

The runtime holds one global `_active_invariants` slot, so concurrent task
submission can overwrite another plan's constraints. The validator describes
replan/rescan/alternate/backoff recovery, but the compiler reduces attempts to
one. Resource and precondition waits do not have a complete admission/queue
deadline hierarchy.

Required correction: store immutable invariants per task revision and enforce
their union at arbitration; add admission, queue, precondition, step, and total
task deadlines; preserve typed failure causes; execute bounded recovery
subtrees and then ask/abstain safely.

### P0.7 Unitree is intentionally uncommissioned

[`configs/robot.yaml`](../../../configs/robot.yaml) has
`axes_commissioned: false`, `state_frame_commissioned: false`, and an empty
`allowed_modes` list. This is correct fail-closed configuration, but it means
no physical capability claim follows from the current adapter. A software
E-stop is not an independent hardware E-stop.

### P0.8 The person-stop envelope is dimensionally invalid

[`authority.py`](../../../src/parcel_robot/authority.py) correctly expresses
the base stopping terms in metres, but `person_stop()` then adds
`person_latency_factor * reaction_latency_s`: a dimensionless value times
seconds is added to metres. The result cannot be treated as a physically valid
distance or an ISO-derived safety calculation.

Replace it with an explicitly measured distance allowance, or a declared
relative closing speed multiplied by a time allowance. Then freeze one
clearance convention—center-to-surface versus footprint-to-surface—and verify
whether `footprint_radius_m` is already represented by collision geometry so it
cannot be double-counted. Add dimensional/unit tests and commissioned stop data
before this envelope supports a physical claim.

## P1 — correctness and capability

### P1.1 Follow bypasses obstacle-aware planning

The current follow controller turns and drives directly toward an owner or
behind point with proportional velocities and a local nearest-obstacle gate.
It cannot route around a wall or crowd, and a geometrically “behind” point may
be on the other side of an obstacle.

Replace direct follow velocity with an adaptive formation-goal generator. It
samples short-lived owner-relative poses, scores visibility, predicted owner
motion, static reachability, stranger/group proxemics, path cost, and temporal
stickiness, then submits the chosen goal/corridor to the same local planner as
ordinary navigation. The independent metric-geometry shield remains outside
the learned/social planner; physical coverage may require both LiDAR and a
camera-derived depth/negative-obstacle channel.

### P1.2 Owner identity is simulator-perfect, not product-ready

The runtime's simple owner record lacks the covariance, enrolled identity,
transient track identity, evidence, and ambiguity already anticipated by richer
contracts. Reacquisition can accept a single frame. Similar-looking people,
crossings, and occlusion can therefore cause a silent identity switch once real
camera tracks replace simulator truth.

Wire an enrolled-owner identity associator over person detections, appearance,
depth, motion continuity, and multi-frame evidence. It must emit `AMBIGUOUS`
rather than selecting the nearest person, and stop/ask/reacquire when confidence
or the margin to the second candidate is inadequate.

### P1.3 Crowd cost weakens as crowd size grows

[`dynamic_costs.py`](../../../src/parcel_robot/navigation/dynamic_costs.py)
adds predicted person lobes and then divides by `weights.sum() * len(tracks)`.
Thus the cost contributed by one dangerous nearby person decreases as unrelated
people are added. `MAX_TRACKS=16` also keeps source-order tracks rather than the
riskiest tracks.

Normalize temporal samples per track, then combine tracks with `max`, capped
sum, or probabilistic union. Select tracks by minimum predicted clearance/TTC,
not arrival order, and expose dropped-track telemetry. Hard geometry/TTC never
uses this soft learned/predicted cost.

### P1.4 Semantic perception remains an oracle-shaped simulation path

The T0 setting in
[`configs/navigation/default.yaml`](../../../configs/navigation/default.yaml)
passes simulator semantic candidates through a noise adapter. The current
“SigLIP” helper is not real pixel inference, the product has no physical camera
producer, and semantic verification can depend on exact simulator polygons and
associated LiDAR IDs. Known POIs can also skip the same terminal semantic
witness used by discovered targets.

Preserve the detection/evidence contracts, but replace their producers with:

- calibrated camera–LiDAR projection and metric association;
- a fast closed-set detector/segmenter/tracker for people, road, sidewalk,
  vehicles, doorway, curb/stairs, poles, and obstacles;
- a separate on-demand open-vocabulary detector/mask/OCR service;
- provenance-bearing semantic memory with covariance, TTL, scene revision,
  re-observation, and `RESOLVED/AMBIGUOUS/UNSEEN/STALE` states.

Only raw geometry can declare free space.

### P1.5 Relation semantics diverge between planner and verifier

Some local navigation plans reduce any relation other than `inside` to `near`,
while navigator paths may distinguish `towards`. Known POIs can be declared
arrived geometrically without proving the requested contextual relation. A
failure reason can also be mistaken for navigation completion in an adapter
path.

Create one relation registry with a controller, valid goal region, approach
sampler, final predicate, hold duration, and explanation for each relation.
“Next to a lamppost” is a collision-free region on a walkable surface, not its
center point; “towards” is a stop-short ray predicate; “on the sidewalk” is
region membership plus not-road; “wait by” adds a settled hold.

### P1.6 Clarification and social reactions are only partly wired

Candidate-aware clarification text exists but many failures become generic
replies. The reaction bridge chooses/logs social reactions but does not dispatch
them. Gesture behavior must not steal locomotion from an important task.

Represent clarification as persistent task state bound to candidate/evidence
handles. Represent affect/gesture as a proposal with expiry and an audited
resource requirement. A trusted arbiter—not the model—maps explicit owner
requests, uncertain inferred affect, current task criticality, checkpoint state,
and safety into execute/defer/drop. Conversation/audio overlays may overlap;
posture gestures require an idle or safe checkpoint and a settle witness.

### P1.7 Voice commands have no product speaker-authorization boundary

The code search found audio transport, echo/barge-in handling, and loopback
service guidance, but no motion-task contract carrying enrolled speaker
evidence, input-channel trust, replay risk, or an authorization result. A TV,
phone replay, bystander, remote text path, or model-readable sign could
therefore be interpreted through the same semantic lane as the owner once live
audio/perception is connected.

Add those fields to `TaskRequestV1` and enforce them before task admission.
Accept literal emergency stop from anyone; require owner/authorized-channel
evidence for new motion or posture authority; treat OCR/signage/retrieved text
as untrusted world evidence that can ground a place but never issue a command.
Test bystander speech, overlapping speakers, recorded owner audio, TV prompts,
network replay, and visual prompt injection under every executive state.

## P2 — performance, maintainability, and evidence quality

- The runtime nominally reasons, maps, plans, controls, and dispatches in one
  Python 10 Hz loop. Slow planning may wait up to 90 seconds. Move perception,
  model inference, map/global planning, and local control into bounded-rate
  services with latest-only queues and explicit deadlines.
- Parsing is duplicated across the router, agent, local plans, and navigation
  goal parsers. One utterance can be reinterpreted differently downstream.
- Safety/footprint/arrival/proximity constants are duplicated; the prior audit
  counted roughly 335 tuned values, with about 43% config-exposed and only 1%
  robot-profile-derived. Consolidate `RobotProfile`, `SafetyEnvelope`, and
  `SpeedRegime` authorities.
- `build_navigator` currently supports only `stub` and `grid`; downloaded
  CityWalker weights are inactive. This fail-closed choice is good, but “model
  installed” must never be confused with “integrated or evaluated.”
- The configured `motion.backend: rl` has an empty policy path and is not the
  product locomotion authority. The RL environments are stubs/kinematic and do
  not justify training.
- Route-memory proposers and richer perception contracts exist one wire short
  of the mission path. Close those seams through versioned adapters rather than
  adding parallel authorities.

## Measured evidence inventory

| Artifact | Result | Correct interpretation |
| --- | --- | --- |
| [NAV_INSTRUCT measured baseline](../../../evals/nav_instruct/results/nav-instruct-v1-baseline-20260805T070524Z.json) | 25 episodes; SR 0.04; SPL 0.0001648; 14 planning, 2 grounding, 4 refusal, 4 termination failures; 0 recorded collisions | Historical direct-navigator minival; broadly unsuccessful; does not exercise the full product executive |
| [NAV_INSTRUCT measured candidate](../../../evals/nav_instruct/results/nav-instruct-v1-candidate-20260806T070335Z.json) | Same episode digest and SR/SPL; 18 planning, 2 grounding, 4 termination failures | No measured quality improvement |
| [NAV_INSTRUCT derived ledger](../../../evals/nav_instruct/results/ledger.jsonl) | Re-scores old traces to baseline 0.12 and candidate 0.16; finds one false arrival and four authority disagreements | Diagnostic rescoring only; **not a run** |
| [Local companion-nav result](../../../evals/companion_nav/results/follow-bench-v1-20260804104134Z-d1adc373.json) | 11 scripted episodes; 8/9 follow, 2/2 navigation, 0 hard collisions; mean commanded jerk 0.553 m/s³ | Useful kinematic regression; oracle owner, injected agents, no full physical/product path |
| [Best fixed-50 native BARN proxy](../../../evals/external/results/ledger/runs/barn-native-20260803T123317614760Z-4c0dea7e.json) | 44% success, metric 0.1063, 0 collisions; deployment-disabled | Non-official headless proxy, not Go2 or leaderboard evidence |
| [Same upstream BARN world with untouched Nav2 MPPI](../../../evals/external/results/ledger/runs/barn-ros2-upstream-mppi-20260803T133200Z-world0-01.json) | success in 37.715 s, metric 0.1802 | Strong reason to spike MPPI; not a Parcel score |
| [Parcel ROS2 BARN world 0](../../../evals/external/results/ledger/runs/barn-ros2-parcel-20260803T155459Z-world0-75f7ff4d.json) | timeout at 100.007 s, score 0 | Adapter/evaluator liveness; current Parcel controller did not solve the episode |
| Habitat artifacts | CUDA/EGL/import and test-scene render/action smokes | GPU compatibility only; no Parcel navigation episode or metric |
| MetaUrban | configured integration raises `NotImplementedError` | No integration or result exists |

The local NAV_INSTRUCT harness currently calls its parser and
`DirectiveNavigator` directly. The first new evaluation card must route the
unchanged production path from text/voice through task execution and terminal
verification. Oracle-injection replays stay separate and are used only to
attribute failures.

## Root-cause conclusion

Parcel is not failing because it lacks one smarter language model. Its measured
failures span task admission/lifecycle, grounding/search, relation semantics,
terminal verification, localization, owner identity, obstacle-aware following,
and local control. The highest-return order is:

1. exact-zero/fail-closed safety and commissioned state;
2. atomic task authority, recovery, deadlines, and terminal witnesses;
3. real localization and camera/LiDAR evidence;
4. one common navigation/follow planner and a strong classical baseline;
5. only then, frozen shadow comparisons of open-weight proposers.

That sequence improves the robot dog rather than a benchmark adapter, and it
makes any later model or learning gain attributable.
