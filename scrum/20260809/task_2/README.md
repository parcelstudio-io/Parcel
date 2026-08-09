# Task 2 — navigation algorithm research and embodied reactions

**Date:** 2026-08-09  
**Status:** research/design complete; simulator emotion/gesture slice implemented
and focused-tested; navigation production changes intentionally not bundled
with concurrent near-arrival/search work

## Request

Deeply research how Parcel should improve navigation and instruction following
for its city/indoor companion goal, while respecting the current Unitree Sport,
camera/LiDAR, voice, behavior, and safety architecture. Add a basic vocabulary
of poses and gestures for emotions and reactions.

## Outcome

The product direction remains the selected dual-system architecture:

- Unitree Sport owns closed-loop balance and gait;
- Parcel owns task intent, goal grounding, route/local navigation, arbitration,
  safety admission, feedback witnesses, and conversation;
- the deterministic path handles common instructions and real-time motion;
- learned language/vision/navigation systems may emit typed, expiring proposals
  but never raw velocity, joints, priority, safety verdicts, or arrival claims;
- the first controller improvement is an in-place RPP-style smooth path tracker;
- MPPI Omni is the best local-controller challenger, initially shadow-only;
- current 2-D A*/Smac 2-D remains the global baseline; a Go2 state lattice is an
  experiment only if yaw/path executability shows a repeatable residual;
- lateral motion remains legal and useful, but normal destination travel
  penalizes it and prefers forward arcs/turning; and
- no broad end-to-end RL training is justified before deterministic defects,
  sensor contracts, and frozen outcome logs are repaired.

Permanent design:

- [navigation algorithm and interfaces](../../../docs/NAVIGATION_ALGORITHM_2026.md)
- [embodied-expression contract](../../../docs/EMBODIED_EXPRESSION.md)

Evidence reports:

- [code-linked current navigation audit](research/CURRENT_NAV_AUDIT.md)
- [primary-source navigation/model research](research/NAVIGATION_RESEARCH.md)

## Most important audit correction

The documentation previously described the environmental collision gate as a
post-shaper exact-zero boundary. The code does not currently satisfy that
description:

```text
selected command
  -> acceleration smoother
  -> camera/LiDAR proximity + TTC decision
  -> S-curve shaper emergency branch (bounded deceleration)
  -> ControlManager
```

An ordinary proximity/TTC veto can therefore leave residual velocity at the
final handoff on that tick. Explicit E-stop, terminal stop, and manager-stop
paths are stronger; this finding does not mean Parcel lacks E-stop. It means the
normal environment-safety contract needs a typed, non-relaxable final decision:

```text
selected bounded command
  -> one actuator shaper
  -> final MotionAdmissionV1
       ADMIT | SCALE | TRANSLATION_HOLD | EXACT_HOLD
  -> reassert final command and reset affected shaper state
  -> ControlManager
```

`EXACT_HOLD` must produce exactly `(0, 0, 0)`. `TRANSLATION_HOLD` may preserve
only independently admitted bounded yaw. Tests must assert the actual final HAL
command, not the earlier gate output. The relevant permanent docs were corrected
in this task rather than leaving a false production claim.

## Current system: strengths to preserve

- The model cannot directly author Unitree velocity or joint commands.
- `ControlManager` remains the one physical body-velocity writer with leases,
  feedback freshness, faults, limits, stop confirmation, and E-stop.
- `grid_v1` already uses sensor-built occupancy, hard geometry separate from
  soft crowd costs, forward-preferred alignment/tracking, bounded recovery, and
  terminal semantic verification.
- Manual, voice, navigation, follow, search, and spatial commands share runtime
  arbitration and environmental checking.
- Owner prediction fails conservatively and keeps an owner-specific keepout.
- Physical Unitree activation is fail-closed while axes, frames, modes, sensors,
  and limits are uncommissioned.
- The platform/HAL retains `vy`; the current autonomous controllers normally
  emit `vy=0`, which matches the desired movement style without freezing the
  future interface.

## Current system: ordered findings

### P0 — repair before controller or model promotion

1. **Final command ordering:** environmental veto is pre-shaper and is not an
   exact-zero final assertion.
2. **Required geometry:** missing/stale/unsynchronized LiDAR can fall back from
   `grid_v1` to point-goal translation rather than holding.
3. **Localization/frame gap:** no production localizer or commissioned
   `map -> odom` transform; degraded pose may still translate.
4. **Dimensional safety drift:** person-stop logic mixes units and multiple
   live stop/clearance values disagree.
5. **Directional coverage:** “move away/backward” can command into the rear
   blind wedge unless full swept-footprint coverage is represented.
6. **Lineage:** the final command is not uniformly joined to task, revision,
   step, goal, evidence, transform epoch, and expiry.

### P1 — navigation quality

1. `grid_v1` uses a yaw P-controller plus a waypoint speed heuristic, not
   regulated pure pursuit or swept-arc validation.
2. Planner geometry and the later reactive refusal envelope disagree, causing
   routes that are plan-feasible but command-infeasible.
3. Dynamic-agent cost is not monotone in track count; source-order truncation
   can omit the most dangerous actor and the schema lacks age/covariance.
4. `come`, follow formation, and owner orbit use direct local controllers rather
   than the common obstacle-aware route path.
5. Terminal truth has no dwell; recovery can discard the right entity before
   trying other safe approach poses around that entity.
6. Road/crossing policy is not an active product authority.
7. Fixed full-turn search, wide rotate mode, and final creeping make successful
   tasks visibly slow; the prior audit measured 44–88% rotation time.

### P2 — scale and reality gaps

- mapping/planning/behavior/model work shares a nominal Python 10 Hz path;
- no real camera open-vocabulary perception, owner re-identification, or
  camera/LiDAR localization is commissioned;
- the MuJoCo base is kinematic and semantic observations derive from scene
  metadata; and
- current physical pose/trajectory actuation is intentionally rejected.

## Proposed navigation algorithm

### 1. Interpret a task, not a motor action

Compile the fast deterministic route or model `PlanSketch` into a revisioned
`TaskRequestV1`. Common commands—stop, follow, wait, move away N steps, orbit N
times, sit, and admitted semantic navigation—should not wait for a large model.
Compound/ambiguous requests use the planner lane. Corrections create a new
revision and invalidate late proposals.

### 2. Join camera, LiDAR, and robot state explicitly

Introduce immutable `PoseEstimateV1`, `ObservationJoinV1`, and
`DynamicTrackSetV1` records with capture/receive times, common transform epoch,
calibration/provenance, covariance, coverage, health, and expiry. Camera answers
identity/semantic questions; LiDAR answers current metric occupancy/clearance;
odometry closes control. Missing required coverage means hold or turn-to-face,
not blind translation.

### 3. Ground language into acceptable goal regions

Generate `GoalCandidateSetV1` from semantic confidence, relation geometry,
walkable support, hard occupancy, road policy, people, uncertainty, visibility,
and path cost. Examples:

- sidewalk: a robot-footprint-eroded interior polygon outside road;
- lamppost: a reachable collision-free annulus around the observed surface;
- owner follow: a rolling free-space region behind/beside enrolled-owner
  heading, not the owner's body center;
- orbit: obstacle-aware tangent regions around the verified owner.

Try alternate poses around the same verified target before excluding that
target. Use enter/exit hysteresis and an uninterrupted terminal dwell with fresh
semantic evidence plus settled-motion feedback.

### 4. Plan globally with one map and one clearance convention

Use current A* or Smac 2-D first over a common layered costmap. Derive hard
footprint inflation, pose/sensor uncertainty, controller stopping distance, and
soft comfort costs from one `SafetyEnvelope`. For city scale, route-graph edges
carry sidewalk, crossing, entrance, speed, and closure metadata while local
camera/LiDAR geometry retains authority.

A state-lattice challenger may later add forward arc, rotation, short lateral,
and short reverse primitives with swept-footprint checks. It is not required
before evidence shows that 2-D planning plus RPP is insufficient.

### 5. Track smoothly with RPP-style control

Use adaptive arc-length lookahead, curvature-linked yaw, continuous curvature/
clearance/braking/goal speed caps, path pruning, acceleration/jerk limits, and
rotate-mode hysteresis. Rotate in place for a large initial discontinuity; turn
while advancing on ordinary curves. Nominal point-to-point `vy=0`; bounded
lateral candidates are admitted only with complete directional coverage when
they measurably improve clearance/progress.

### 6. Predict people conservatively

Make the constant-velocity baseline uncertainty-aware and monotone. Rank/truncate
tracks by predicted clearance/TTC rather than source order. Add anisotropic
front/side/back comfort costs and route-switch dwell, but keep raw LiDAR and
conservative TTC as independent hard evidence. When a person blocks a goal,
wait for bounded patience, then rerank safe poses/routes around the same target;
never weaken the person stop.

### 7. Shadow MPPI and learned systems through one contract

`NavProposalV1` carries task/revision/evidence IDs, observation time, frame,
expiry, bounded horizon, generator/model/artifact IDs, confidence, and either a
semantic/pixel goal, waypoint, or trajectory proposal. Deterministic code
metricizes and admits it. The final safety/authority path remains unchanged.

Candidate order:

1. VLFM-style semantic frontier scoring;
2. installed CityWalker as a shadow urban trajectory proposal only after its
   RGB/history adapter and checkpoint licensing are resolved;
3. LeLaN for visible-target last-mile study;
4. InternVLA-N1/StreamVLN-style slow/fast VLN in a license-isolated research
   service;
5. GenSafeNav/Trajectron++ ideas for crowd uncertainty; and
6. MPPI Omni as the strongest classical time-indexed local challenger.

InternVLA-N1 has downloadable 8B weights but unclear checkpoint license
metadata. The installed CityWalker checkpoint is not executable on Parcel's
live path and its exact artifact license is `NOASSERTION`. The advertised
SocialNav Hugging Face repositories were empty at research time. No artifact
was downloaded merely because a paper reported a strong result.

## Implemented embodied-expression slice

### New poses

- `attentive_stand`
- `relaxed_crouch`

They are persistent, explicit posture options and are never selected by an
inferred-affect personality map.

### New self-returning gestures

- `comfort_bow` — supportive/sadness acknowledgement;
- `happy_wiggle` — playful celebration;
- `excited_paw_taps` — four rapid front-paw bend/return cycles for explicit
  strong positive anticipation;
- `attentive_nod` — restrained acknowledgement; and
- `curious_look` — explicit/future curiosity reaction;
- `head_nod` and `head_shake` — affirmative/negative forequarter proxies;
- `chuckle` — a silent three-bob body reaction paired with TTS when appropriate;
- `shrug` — bounded uncertainty; and
- `confused_head_tilt` / `observing_head_tilt` — distinct clarification and
  decorative-attention proxies.

All new trajectories start/end at neutral stand, contain all 12 joints, finish
within 1.5 seconds, stay within a 0.30 rad authored delta, and are tagged
`hardware_unverified`. Source and packaged runtime assets are byte-identical.

Go2 has no articulated neck, so every “head” action is explicitly tagged as an
embodiment proxy and only moves the legs/forequarter silhouette. Contextual
reactions use a two-second TTL and are skipped while the body is busy; explicit
owner requests retain the existing defer policy. `confused`, `observing`, and
`amused` were deliberately not added to the owner-affect enum.

Personality maps now use:

| Personality | sad | happy | excited anticipation |
| --- | --- | --- | --- |
| gentle | `comfort_bow` | `paw_wave` | `excited_paw_taps` |
| playful | `comfort_bow` | `happy_wiggle` | `excited_paw_taps` |
| calm guardian | `attentive_nod` | `attentive_nod` | `excited_paw_taps` |

This corrects the earlier semantic mismatch where sadness triggered
`play_bow`, which is an invitation to play. The system prompt now explicitly
permits no gesture when confidence is weak or motion would add little.

The excited reaction is a trajectory, not a persistent pose. Its authored
keyframes contain exactly four cycles in 0.96 seconds (the regression ceiling
is five), return to neutral after every bend, and do not allow an unbounded
repeat or a leg-up terminal state. The `excited` affect label is reserved for
explicit first-person anticipation and remains subject to the same activity
deferral, TTL, cooldown, E-stop, and physical-runtime rejection boundaries.
The affect extension first recorded `deterministic-v1.1`; the reviewed natural
gesture aliases advance the observable router behavior to
`deterministic-v1.2`. The intent
frame keeps structural schema version 1, but strict external consumers that pin
the old affect enum must update atomically with this release; a future public
wire API should publish a separately versioned schema before widening it.

### Hardware boundary

Custom YAML poses/trajectories currently render only through the synchronous
simulator backend. Physical `_run_pose`/`_run_trajectory` calls fail closed
because there is no controller-owned whole-body handoff. Do not bypass Unitree
Sport with raw joint commands.

The physical path should later map supported semantics to commissioned Sport
actions (`Sit`/`RiseSit`, `Hello`, `Stretch`, bounded `Euler`, recovery/stand)
through a typed controller action with feedback, timeout, clearance,
cancel/abort/recovery, capability, and exact firmware checks.

### Simulator pose-review gallery

`scripts/launch_pose_review.sh` now reuses `launch_sim.sh` to open MuJoCo and a
dedicated `/poses` browser sequencer. It lists the catalog's poses and
trajectories in canonical order and supports Run, Run All, Previous/Next,
filtering, dwell time, Stop, and neutral reset. The launcher starts the complete
catalog after a three-second countdown by default; `--manual` suppresses that
automatic run for individual inspection. `--autoplay` remains an explicit,
backward-compatible spelling of the default.

The preview surface is explicit and simulator-only: ordinary panel servers
return 404 for it, the runtime requires the `mujoco` backend, and only bounded
pose/trajectory skills are admitted. Velocity, gait, policy, unknown skills,
physical runtimes, missing CSRF tokens, and non-enabled panel sessions fail
closed. The Stop path restores the simulator's standing joints between items.

Focused automated verification:

```text
79 passed, 3 existing warnings in 6.12 s
10 portability/runtime-asset tests passed in 3.38 s
ruff: all checks passed
bash -n scripts/launch_pose_review.sh: passed
```

The live desktop smoke used an isolated socket and port. `/poses` loaded 24
bounded motions, the API dispatched `excited_paw_taps` to MuJoCo, Stop restored
neutral stand, and Ctrl+C removed the owned socket and stopped both processes.
Non-fatal Wayland decoration/window-position and OpenGL warnings were observed;
they did not prevent the native viewer or trajectory path from running.

The expanded follow-up smoke exposed 30 bounded motions and dispatched all six
new expression clips (`head_shake`, `head_nod`, `chuckle`, `shrug`,
`confused_head_tilt`, and `observing_head_tilt`) through the live simulator API.
Stop restored neutral and launcher shutdown again cleaned the isolated port and
Unix socket. The focused behavior suite passed 26 tests; the broader
runtime/web/packaging suite passed 158 tests with three existing deprecation
warnings.

The gallery and skill executor now also accept normalized motion speed in
`[0, 1]`: `1` preserves authored timing and `0` selects the slowest bounded
playback (at least 0.25×), while Stop remains cancellation. Optional YAML
`speed` supplies the catalog default; a trusted execution/API override controls
one run. Pose transition duration and trajectory timestamps are retimed without
changing joint targets or gesture shape. Execution receipts are the shared UI
and activity-scheduler timing authority. Activity-owned dispatch also no longer
self-preempts its coordinator record.

Verification for the speed-control change: 143 skill, expression, runtime,
pose-review HTTP, simulator-control, and packaged-asset tests passed; Ruff and
`git diff --check` also passed. The three warnings are existing footprint
deprecations outside this change.

## Ordered implementation plan

```text
S0 frozen honest baseline
  -> S1 final exact-zero disposition + command lineage
  -> S2 fail-closed observation/frame/coverage join
  -> S3 one dimensionally valid SafetyEnvelope
       |-> S4 RPP-style controller and swept-arc gate
       |-> S5 monotone dynamic layer and route-switch hysteresis
       |-> S6 goal-candidate set and terminal dwell
       `-> owner formation goal geometry
              -> S7 common ApproachOwner/follow/orbit navigation
              -> S8 real localization + Unitree commissioning
              -> S9 Nav2/MPPI/open-weight shadow tournament
```

Evaluation/trace work can run beside S0–S3. After the observation and safety
contracts freeze, S4 controller, S5 dynamics, S6 terminal candidates, and owner
geometry can proceed in parallel. Hardware wiring waits for those foundations;
model labs remain isolated and proposal-only.

## Evaluation gates

Every change uses the same frozen product path and separately scores task truth
and trajectory quality:

- semantic/relation success, false arrival, honest not-found;
- hard collision, forbidden-road time, minimum obstacle/person clearance, TTC;
- path length/time, time to first progress, rotation/lateral/reverse fraction,
  jerk, yaw reversals, stop-start count, and settle dwell;
- owner formation error, identity switches, visibility loss/reacquisition;
- dynamic deadlock, reroute, intervention, and recovery outcomes;
- sensor age/skew, planner/controller deadlines, final command age, CPU/GPU/
  VRAM, and p50/p95/p99 latency; and
- user-query-to-first-reasoning/response correlated with physical task outcome.

Environment ladder: unit/property tests -> headless Parcel city -> BARN/Habitat
diagnostics -> one immutable social/city environment (HuNavSim/SocNavBench or
MetaUrban) -> sensor replay -> HIL -> fenced Go2. External percentile goals are
research diagnostics and cannot justify changing the dog embodiment, using an
oracle, or bypassing safety.

## Verification record

Focused gesture/runtime/agent/prompt-asset suite run by the primary task:

```text
91 passed, 3 existing warnings in 1.39 s
```

Command:

```bash
.parcel/bin/python -m pytest -q \
  tests/test_emotion_gesture_library.py \
  tests/test_skills.py \
  tests/test_emote_skill.py \
  tests/test_intelligence.py \
  tests/test_runtime_assets.py \
  tests/test_prompting_activities.py \
  tests/test_dynamic_prompting.py
```

The conversation-quality v1 manifest locks the action policy and personality
files. Their hashes were re-frozen to the changed files in the same worktree so
the gate fails on future unrecorded prompt drift; historical result JSON files
remain untouched and retain their original input hashes.

The direct runtime and frozen-conversation checks also passed:

```text
55 passed, 3 existing warnings in 3.55 s
```

That suite includes the full idle affect path: text inference, personality
mapping, coordinator queue, runtime control tick, and simulator trajectory
dispatch of `comfort_bow`.

The excited-paw extension then passed the combined gesture, router, prompt,
provider, schema, frozen-conversation, skill, agent, and runtime regression set:

```text
163 passed, 3 existing warnings in 4.83 s
```

That run includes explicit excitement parsing, rejection of a false excitement
match for “wait by the lamppost,” the non-authoritative “looking forward to our
walk” case, exact four-cycle trajectory shape, source/package parity, idle
dispatch, navigation deferral, and return to neutral stand.

The independent navigation audit ran a broader focused suite and observed
`164 passed, 1 failed, 3 warnings`; the failure is a stale structural AST test
that still expects a literal default after a `SafetyEnvelope` derivation. That
is not represented as a green baseline. The audit made no runtime edits.

The complete repository suite was also run:

```text
2955 passed, 14 skipped, 2 xfailed, 3 failed, 5 warnings in 767.80 s
```

The three failures are navigation-baseline pins, not gesture/prompt/runtime
failures:

- `test_dynamic_layer.py::test_the_collision_gate_behaviour_is_untouched_on_this_branch`
  is the same stale AST/literal-default assertion identified by the audit;
- `test_embodied_plan_eval.py::test_full_gate_executes_physics_and_separates_unsupported`
  still expects 1,250 steps while the concurrent tree completes the same five
  cases in 1,219, with identical pass/fail/unsupported, collision, timeout, and
  minimum-clearance results; and
- `test_embodied_plan_eval.py::test_correction_waits_for_checkpoint_then_executes_replacement`
  still expects 153 steps while the concurrent near-arrival path takes 124;
  checkpoint/revision/task outcome remain correct.

Those baselines were not silently re-frozen in this task because the navigation
changes belong to the concurrent workstream and require their own attribution.

The working tree also contains concurrent near-arrival/search changes outside
this task (`instructnav`, `navigation/approach.py`, `navigation/pipeline.py`, and
their tests). This task did not overwrite, stage, or attribute those changes.

## Definition of done for the next implementation slice

S1 is complete only when:

- final HAL dispatch exactly matches the typed admission;
- `EXACT_HOLD` produces bitwise/fieldwise zero and resets both smoother states;
- `TRANSLATION_HOLD` cannot regain translation after shaping;
- manual, voice, follow, spatial, search, and navigation exercise the same
  final path;
- stale task/evidence decisions cannot affect a new revision; and
- explicit E-stop/manager stop behavior remains green.

RPP or a model should not be promoted in the same change as S1. That keeps the
safety correction independently reviewable and makes later quality deltas
attributable.
