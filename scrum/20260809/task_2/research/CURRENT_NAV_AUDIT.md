# Current navigation, control, and behavior audit

**Audit date:** 2026-08-09  
**Code basis:** `main` at `ff07da1ed80b5ae155728a5dc7998d8762863b78`, plus the
live dirty working tree observed during this audit.  
**Scope:** read-only inspection of the active navigation/control/behavior path,
configuration, focused tests, the 2026-08-08 A/B/C architecture packet, and the
2026-08-09 task-1 measured audit. No runtime, configuration, or test behavior was
changed for this report.  
**Safety statement:** this is a software audit, not a physical safety assessment
or authorization for unsupervised public operation.

## Outcome

Parcel already has the right **high-level shape** for a production companion:
typed language plans, a task executive, time-limited motion arbitration, a
replaceable controller boundary, feedback/watchdog supervision, independent
semantic arrival checks, and Unitree Sport retaining gait and balance. Its
shipping navigation algorithm is a sensible deterministic baseline: rolling
LiDAR occupancy, footprint inflation, 8-connected A*, a forward-preferred
turn-first waypoint tracker, constant-velocity pedestrian prediction, and a
reactive/TTC brake.

It is not yet the Design-A foundation or the recommended Design-B product spine.
The most important discrepancies are below, in order:

1. an ordinary proximity/TTC veto occurs **before** S-curve shaping, whose
   “emergency” branch still ramps velocity; the command at the software HAL can
   therefore remain non-zero on the veto tick;
2. the active grid navigator can translate through `StubNavigator` when its
   calibrated LiDAR contract is missing, and the normal profile does not enforce
   synchronized scan/odometry timestamps;
3. the active pose provider is simulator truth, there is no commissioned
   `map -> odom` transform, and `DEGRADED` pose can continue translating;
4. person stopping math is dimensionally invalid and three live stop-distance
   configurations disagree;
5. owner follow and spatial behaviors bypass the obstacle-aware grid planner;
   “come” is still persistent follow, and the runtime can report success while
   follow retains motion authority;
6. the local controller is not regulated pure pursuit and has no swept-arc
   admission; lateral motion exists in the ABI but no primary autonomous
   navigator uses it;
7. dynamic-agent cost decreases for one dangerous track when unrelated tracks
   are added, source-order truncation can drop the riskiest person, and malformed
   tracks silently remove TTC/dynamic help for the tick;
8. terminal verification has useful independent predicates and settled feedback,
   but no uninterrupted dwell, and recovery abandons a semantic instance before
   trying alternate approaches to the same instance;
9. task/channel pause-resume is now fixed, but complete task/revision lineage,
   per-task invariant union, and executable typed recovery are not carried to
   every command and witness;
10. road/crossing modules exist only as isolated library code and tests; they do
    not constrain the product navigation path.

The highest-value next work is therefore **not a learned navigation model** and
not a wholesale Nav2 migration. Land the final authority/freshness contracts,
then improve `grid_v1` in place with a regulated-pure-pursuit-style controller,
monotone dynamic costs, same-target approach reranking, terminal dwell, and a
common planner for `ApproachOwner`/`FollowFormation`. Only then compare Nav2 RPP
and MPPI as exclusive challengers under the same interface and witnesses.

## Audit provenance and test result

The working tree was changing concurrently. At the source/test snapshot it
contained uncommitted near-arrival changes in
[`approach.py`](../../../../src/parcel_robot/navigation/approach.py),
[`pipeline.py`](../../../../src/parcel_robot/navigation/pipeline.py), and
[`near_arrival.py`](../../../../src/parcel_robot/instructnav/near_arrival.py),
plus associated tests. Later in the audit, separate personality/gesture assets
and small `agent.py`/`runtime.py` edits also appeared. Those changes belong to
other work and were neither altered nor treated as a frozen baseline here.
Findings that concern the near-arrival patch are explicitly labeled
**working-tree-only**.

Focused tests were re-run against this working tree:

```text
.parcel/bin/python -m pytest -q \
  tests/test_motion_shaping.py \
  tests/test_closed_intent_product_path.py \
  tests/test_grid_navigator.py \
  tests/test_dynamic_costs.py \
  tests/test_dynamic_layer.py \
  tests/test_follow_formation.py \
  tests/test_follow_prediction.py \
  tests/test_pose_consumers.py

164 passed, 1 failed, 3 warnings in 3.47 s
```

The one failure is
`test_the_collision_gate_behaviour_is_untouched_on_this_branch`. It is a stale
structural test, not evidence of a newly observed gate-behavior regression:
[`_annotated_defaults`](../../../../tests/test_dynamic_layer.py#L669-L687)
intentionally skips non-literal derived defaults, while the assertion at
[`test_dynamic_layer.py:741-754`](../../../../tests/test_dynamic_layer.py#L741-L754)
still demands that those skipped fields be present. `CollisionPolicy` now derives
those defaults from `DEFAULT_SAFETY_ENVELOPE` at
[`collision.py:41-60`](../../../../src/parcel_robot/navigation/collision.py#L41-L60),
including in committed `HEAD`. The test should compare evaluated values to a
frozen authority fixture instead of requiring AST literals. Until corrected,
the focused navigation gate is red. No full suite, headless city run, or
physical Unitree run was performed for this report.

The measured findings in today's task-1 audit remain important context rather
than results re-run here: successful missions spent 44–88% of wall time rotating,
translated at 0.21 m/s on average against a 0.9 m/s cap, and showed a 10.4 s
planner/gate dead stop
([`task_1/README.md:15-16`](../../task_1/README.md#L15-L16)). The same audit
reports zero hard collisions in its product-path artifacts, but explicitly
rates seamless navigation and the eval substrate as not met
([`task_1/README.md:15-19`](../../task_1/README.md#L15-L19)).

## The actual product path today

```text
final transcript / UI request
          |
          v
deterministic router or Gemma PlanSketch / PlanIR
          |
          v
system compiler -> validator -> TaskExecutive -> runtime adapter
          |
          +---------------------------+--------------------------+
          |                           |                          |
          v                           v                          v
 NavigateTo                    FollowFormation            spatial behavior
 DirectiveNavigator            direct/behind P-control    step/orbit P-control
 semantic grounding                   |                          |
          |                            |                          |
          v                            +-------------+------------+
 GridNavigator                                       |
 rolling LiDAR map -> A* -> waypoint tracker         |
          |                                           |
          +----------------------+--------------------+
                                 v
                    CommandArbiter source lease + TTL
                                 |
                                 v
                       acceleration smoother
                                 |
                                 v
                 reactive geometry + dynamic TTC gate
                                 |
                                 v
                        S-curve actuator shaper
                                 |
                                 v
              ControlManager target/watchdog/feedback
                                 |
                                 v
                 simulator controller OR Unitree Sport
                   (Sport owns gait/balance/joints)
```

The control loop observes the simulator, updates owner tracking/prediction,
submits direct follow, search, spatial, and navigation proposals, then dispatches
one active lease
([`runtime.py:3957-4096`](../../../../src/parcel_robot/runtime.py#L3957-L4096)).
Follow commands are generated and submitted directly at
[`runtime.py:3996-4034`](../../../../src/parcel_robot/runtime.py#L3996-L4034),
so they do not traverse `DirectiveNavigator`, the rolling grid, or A*.

The outgoing order is explicit in
[`RobotRuntime._dispatch_active`](../../../../src/parcel_robot/runtime.py#L4146-L4248):

```text
arbiter.current
  -> velocity_smoother.step
  -> rotate-only residual-translation scrub
  -> _collision_safe (reactive geometry, then TTC)
  -> velocity_smoother.force
  -> _shape_for_actuator (S-curve)
  -> ControlManager.set_target
```

That ordering is the central authority defect: the architecture packet requires
the final metric monitor after all shaping
([`SHARED_FOUNDATION.md:53-72`](../../../20260808/task_1/SHARED_FOUNDATION.md#L53-L72)),
but current code has no post-shaper recheck or non-relaxable stop disposition.

## Algorithms actually in use

| Layer | Current implementation | What it really means |
| --- | --- | --- |
| Active nav model | `active_model: grid_v1` ([`default.yaml:5-9`](../../../../configs/navigation/default.yaml#L5-L9)) | Deterministic CPU navigation; downloaded navigation weights are not active. |
| Semantic perception | T0 pass-through chain ([`default.yaml:39-68`](../../../../configs/navigation/default.yaml#L39-L68)) | The interface is useful, but default evidence is oracle-shaped simulation, not pixel inference. |
| Localization | `provider: truth` ([`pose.yaml:1-12`](../../../../configs/navigation/pose.yaml#L1-L12)) | A typed pose seam and stress providers exist; there is no production localizer. |
| Mapping | rolling log-odds occupancy from calibrated planar LiDAR | Robot-centric local map; persistent/global mapping and loop closure are absent. |
| Static route | 8-connected A* over hard inflation, unknown penalty, comfort and dynamic costs ([`grid_planner.py:1370-1441`](../../../../src/parcel_robot/navigation/grid_planner.py#L1370-L1441)) | Correctly prevents diagonal corner cutting; unknown is traversable by default. |
| Path simplification | collinearity compression plus known-free line-of-sight smoothing ([`grid_planner.py:913-960`](../../../../src/parcel_robot/navigation/grid_planner.py#L913-L960)) | Shortcuts cannot increase the peak comfort/dynamic cost, a good invariant. |
| Waypoint | farthest currently visible route vertex inside fixed lookahead ([`grid_planner.py:1281-1345`](../../../../src/parcel_robot/navigation/grid_planner.py#L1281-L1345)) | Produces body-frame forward/left geometry, but the controller ignores `left_m`. |
| Local control | yaw P-controller + slew; hard align hysteresis; forward speed scaled by goal distance, `cos(error)^2`, and waypoint distance ([`grid_navigator.py:440-497`](../../../../src/parcel_robot/navigation/grid_navigator.py#L440-L497)) | Forward-preferred and partly smooth, but not regulated pure pursuit, DWB, TEB, MPPI, or an SE(2) optimizer. |
| Autonomous lateral | `vy=0` in grid, follow, and spatial point tracking | Lateral remains available to manual/HAL code, not primary autonomous destination travel. |
| Dynamic planning | constant-velocity Gaussian rollouts as additive A* costs ([`dynamic_costs.py:39-85`](../../../../src/parcel_robot/navigation/dynamic_costs.py#L39-L85)) | A soft social forecast; no uncertainty, intent, interaction, velocity-obstacle, or crowd-flow model. |
| Dynamic emergency | analytic circle-circle TTC scales the command after reactive geometry ([`runtime.py:4897-4939`](../../../../src/parcel_robot/runtime.py#L4897-L4939)) | Useful independent brake, but malformed payload skips the TTC gate for that tick. |
| Direct owner follow | proportional range/yaw controller; turn in place over a heading threshold ([`follow.py:605-667`](../../../../src/parcel_robot/navigation/follow.py#L605-L667)) | Tracks well in open space but cannot plan around a wall/crowd. |
| Behind formation | predicted owner-relative point, keepout staging, local reactive brake ([`follow.py:669-797`](../../../../src/parcel_robot/navigation/follow.py#L669-L797)) | Better social geometry, still no grid route to the staging/formation point. |
| Relative/orbit | fixed-distance projection and tangent point tracking ([`spatial.py:406-538`](../../../../src/parcel_robot/navigation/spatial.py#L406-L538)) | Bounded and turn-first, but direct local motion rather than obstacle-aware trajectory planning. |
| Terminal | relation/evidence/environment check plus settled motion feedback ([`pipeline.py:2718-2878`](../../../../src/parcel_robot/navigation/pipeline.py#L2718-L2878)) | Independent of the planner's success string, but satisfied on one good settled tick rather than a dwell. |
| Low-level body | `ControlManager` around simulator or Unitree Sport | Unitree's Sport `Move` remains the locomotion/balance controller; Parcel closes the task/velocity/feedback loop above it. |

## Strengths to preserve

These are real foundations, not placeholders:

- **Language cannot directly author Sport velocity.** The compiler owns resource,
  success, timeout, and interrupt fields
  ([`compiler.py:29-101`](../../../../src/parcel_robot/brain/compiler.py#L29-L101));
  the validator re-derives system invariants independently of model text
  ([`validator.py:627-666`](../../../../src/parcel_robot/brain/validator.py#L627-L666)).
- **Manual control uses the same arbitration and final reactive path.** It
  atomically preempts semantic channels and then submits a normal motion lease
  ([`runtime.py:2299-2321`](../../../../src/parcel_robot/runtime.py#L2299-L2321));
  `_collision_safe` explicitly covers voice, manual, follow, and navigation
  ([`runtime.py:4874-4895`](../../../../src/parcel_robot/runtime.py#L4874-L4895)).
- **The static planner never lets a soft dynamic cost open a hard obstacle.** The
  dynamic layer is additive, finite, non-negative, and separate from the hard
  inflated mask
  ([`grid_planner.py:720-766`](../../../../src/parcel_robot/navigation/grid_planner.py#L720-L766)).
- **Turn-first behavior is not merely aspirational.** `grid_v1` enters alignment
  at 55 degrees and exits at 7 degrees
  ([`grid.yaml:7-21`](../../../../configs/navigation/models/grid.yaml#L7-L21));
  the controller sets `vx=0` while aligning
  ([`grid_navigator.py:444-470`](../../../../src/parcel_robot/navigation/grid_navigator.py#L444-L470));
  runtime now removes residual translation immediately when a raw active intent
  is rotate-only
  ([`runtime.py:4156-4165`](../../../../src/parcel_robot/runtime.py#L4156-L4165)).
- **Lateral semantics are retained end to end.** The planner computes left
  displacement, Unitree state conversion handles body `vy`, manual UI exposes
  strafe, and reactive safety uses `atan2(vy, vx)` for directional admission
  ([`reactive_safety.py:172-197`](../../../../src/parcel_robot/navigation/reactive_safety.py#L172-L197)).
  This is the right ABI even though ordinary autonomous travel should penalize
  lateral motion.
- **Owner prediction fails conservatively.** Low-confidence predictions brake
  translation but preserve yaw for reacquisition
  ([`follow.py:478-603`](../../../../src/parcel_robot/navigation/follow.py#L478-L603));
  predicted lead is clamped by owner keepout.
- **Terminal success is independently checked.** MAP pose health, fresh
  perception, target evidence, relation geometry, nearby people/obstacles, and
  settled measured motion all participate
  ([`pipeline.py:2759-2878`](../../../../src/parcel_robot/navigation/pipeline.py#L2759-L2878),
  [`pipeline.py:3081-3160`](../../../../src/parcel_robot/navigation/pipeline.py#L3081-L3160)).
- **Explicit stop paths are stronger than the ordinary proximity path.** E-stop,
  `stop_motion`, stale-perception invariant, intent expiry, and navigation
  terminal stop reset shaping and/or call `ControlManager.stop`; focused tests
  cover those paths
  ([`test_motion_shaping.py:295-393`](../../../../tests/test_motion_shaping.py#L295-L393)).
  The exact-zero defect below must not be misread as “there is no E-stop.”
- **Feedback and watchdog supervision are substantive.** `ControlManager`
  rejects stale state, delivers stop, requires post-stop feedback, and requires
  two settled samples before confirmation
  ([`manager.py:948-1019`](../../../../src/parcel_robot/control/manager.py#L948-L1019),
  [`manager.py:1150-1201`](../../../../src/parcel_robot/control/manager.py#L1150-L1201)).
- **Pause/resume was fixed since the prior audit.** Runtime restores the channel
  and parked executive task together, refusing foreign suspension ownership
  ([`runtime.py:1648-1725`](../../../../src/parcel_robot/runtime.py#L1648-L1725));
  the former xfail now requires the task to remain `running`
  ([`test_closed_intent_product_path.py:306-331`](../../../../tests/test_closed_intent_product_path.py#L306-L331)).
- **Physical activation is intentionally fail-closed.** Unitree axes and state
  frame are uncommissioned and allowed modes are empty
  ([`robot.yaml:120-135`](../../../../configs/robot.yaml#L120-L135)). This means no
  physical capability claim yet, but it is the correct default.

## Prioritized findings

| ID | Priority | Finding | Immediate implication |
| --- | --- | --- | --- |
| F-01 | P0 | Final safety is pre-shaper; emergency shaping is a bounded deceleration, not exact zero | A proximity/TTC veto can hand non-zero residual velocity to `ControlManager` on the veto tick. |
| F-02 | P0 | Missing/stale/unsynchronized required LiDAR can fall back to point-goal translation | Product motion may continue without the geometry contract the selected planner promises. |
| F-03 | P0 | No production localizer or `map -> odom` transform; `DEGRADED` may translate | Real global goals and local control cannot yet share a valid frame/freshness contract. |
| F-04 | P0 | Person-stop formula mixes metres and seconds; live stop values disagree | Safety margins cannot yet support a physical stopping-distance claim. |
| F-05 | P0 for hardware | Reverse/away behavior can command into the 270-degree LiDAR rear blind wedge | “Five steps away” may back into unobserved space; normal grid recovery correctly disables reverse, but spatial motion does not. |
| F-06 | P0 foundation | Command lineage stops at source-channel leases, and active invariants are one global slot | Late/stale output is not uniformly bound to `{task, revision, step, goal, evidence}`; concurrent tasks can overwrite invariant state. |
| F-07 | P1 | `grid_v1` is forward-preferred but not curvature-regulated and has no swept-arc check | Corner tracking, oscillation, and slow stop-turn-ramp cycles remain; today’s measured seamlessness is poor. |
| F-08 | P1 | Planner geometry/cost and final gate disagree | A* can repeatedly propose routes the body-level gate refuses, causing long stalls and candidate abandonment. |
| F-09 | P1 | Dynamic cost is non-monotone in track count; source-order truncation and weak track schema | A crowd can look cheaper as it grows; the most dangerous track can be dropped. |
| F-10 | P1 | Follow/come/orbit bypass common obstacle-aware navigation | Open-space behavior works, but walls/crowds and persistent-vs-terminal lifecycle are wrong. |
| F-11 | P1 | Terminal has no dwell; recovery releases an instance before alternate approach poses | Brief truth can become success, while a blocked approach can discard the right object. |
| F-12 | P1 | Road/crossing policy is not wired; only stale perception invariant is actively enforced | “Get off the road” can be semantically solved in the demo but has no product ODD/crossing authority. |
| F-13 | P1 working tree | New near-band fallback ignores support/road/occupancy while terminal still requires support | The tentative fix can plan an unverifiable or unsafe-side pose and recreate a plan/verifier mismatch. |
| F-14 | P2 | Main Python control loop performs mapping/planning/behavior/brain work at 10 Hz, with two smoothing stages | Tail jitter and repeated A* can degrade tracking; architecture should split rates before adding heavy learned inference. |
| F-15 | P2 | Focused navigation gate is red and diagnostic scratch test always passes | Current evidence is not a clean, immutable regression baseline. |

## Detailed control and navigation analysis

### 1. Exact-zero ordering and single authority

`_collision_safe` runs after the first acceleration smoother, which is good, but
then `_shape_for_actuator` runs afterward. Its `stopping=True` path invokes
`SCurveVelocityShaper.step(..., emergency=True)`
([`runtime.py:4181-4197`](../../../../src/parcel_robot/runtime.py#L4181-L4197)).
The shaper's emergency branch moves each current axis toward zero by
`max_accel * dt`; it does not return zero immediately
([`velocity_shaping.py:88-116`](../../../../src/parcel_robot/navigation/velocity_shaping.py#L88-L116)).
The current proximity test encodes only “drops faster than normal smoothing,”
not “final output equals zero”
([`test_motion_shaping.py:395-413`](../../../../tests/test_motion_shaping.py#L395-L413)).

There is a second semantic ambiguity. The reactive gate's normal stop preserves
yaw and zeros translation
([`reactive_safety.py:196-197`](../../../../src/parcel_robot/navigation/reactive_safety.py#L196-L197)),
while the shaper's `emergency=True` logic drives every axis toward zero. The
runtime needs a typed non-relaxable decision, not a string state:

```text
MotionAdmissionV1
  decision_id
  mode: ADMIT | SCALE | TRANSLATION_HOLD | EXACT_HOLD
  admitted_command
  reason
  geometry_evidence_ids
  valid_until
  task_id / revision / step / command_sequence
```

Recommended order:

```text
selected bounded command
  -> one actuator shaper
  -> final metric/state safety evaluation
  -> reassert:
       EXACT_HOLD       => (0, 0, 0), reset shapers, manager stop as required
       TRANSLATION_HOLD => (0, 0, admitted bounded yaw), reset linear states
       SCALE/ADMIT      => admitted bounded output
  -> assert final command matches decision
  -> ControlManager
```

The existing pre-shaper gate can remain as an early cap while this is introduced,
but only the post-shaper decision is final. Eventually, the acceleration smoother
and S-curve shaper should become one clearly owned shaping stage; two independent
stateful ramps make stopping, resume seeding, and latency harder to reason about.

### 2. Required geometry and directional coverage

When no calibrated scan can be built, `GridNavigator.act` logs and calls the
point-goal fallback
([`grid_navigator.py:351-373`](../../../../src/parcel_robot/navigation/grid_navigator.py#L351-L373)).
The test explicitly expects that behavior and expects a tracking command
([`test_grid_navigator.py:72-87`](../../../../tests/test_grid_navigator.py#L72-L87)).
Fresh LiDAR/odometry timestamp checking exists, but returns `True` without
checking anything unless the experimental `safe_valley_micro_advance` profile is
enabled
([`grid_navigator.py:940-969`](../../../../src/parcel_robot/navigation/grid_navigator.py#L940-L969));
that profile is false by default.

This violates the shared foundation's explicit rule that missing, stale,
malformed, frame-invalid, or uncovered required geometry means HOLD and that
`StubNavigator` is never the product fallback
([`SHARED_FOUNDATION.md:58-63`](../../../20260808/task_1/SHARED_FOUNDATION.md#L58-L63)).
`stub_v0` can remain an explicitly selected simulation/test model. It should not
be entered implicitly by `grid_v1`.

Directional coverage needs to be part of the same admission. The grid recovery
correctly sets reverse steps to zero because the standard LiDAR has a rear blind
wedge
([`grid.yaml:28-34`](../../../../configs/navigation/models/grid.yaml#L28-L34)).
Yet `MoveRelative(away_from_owner|backward)` intentionally emits negative `vx`
([`spatial.py:310-323`](../../../../src/parcel_robot/navigation/spatial.py#L310-L323),
[`spatial.py:406-436`](../../../../src/parcel_robot/navigation/spatial.py#L406-L436)).
If a non-empty LiDAR obstacle list contains no ray in the commanded direction,
reactive safety returns the command unchanged
([`reactive_safety.py:129-149`](../../../../src/parcel_robot/navigation/reactive_safety.py#L129-L149)).

Required rule:

```text
admit_translation(direction, swept_footprint, observation_join):
  require calibrated metric coverage of the complete swept footprint
  require fresh pose + transform in the same epoch
  require no hard occupied/unknown cell in the swept footprint
  if reverse/lateral coverage is absent: return EXACT_HOLD or turn-to-face + forward plan
```

Thus “walk five steps away from me” may back away while maintaining gaze only
when rear geometry is fresh and complete. Otherwise the dog should turn toward
the safe travel direction and move forward. Language intent does not authorize
blind reverse.

### 3. Localization, frames, and evidence joins

`PoseEstimate` is a good typed seam: frame, covariance, health, and monotonic
stamp are validated
([`pose.py:74-182`](../../../../src/parcel_robot/pose.py#L74-L182)). The active
provider returns exact simulator truth in MAP and ODOM
([`pose.py:190-220`](../../../../src/parcel_robot/pose.py#L190-L220)). That hides
the unimplemented transform. `GridNavigator` itself documents that mission goals
are MAP quantities while local control reads ODOM, with no `map -> odom`
transformation once the frames diverge
([`grid_navigator.py:326-338`](../../../../src/parcel_robot/navigation/grid_navigator.py#L326-L338)).

Current navigation stops only on `LOST`; `DEGRADED` keeps driving and merely
blocks the arrival claim
([`pipeline.py:1653-1679`](../../../../src/parcel_robot/navigation/pipeline.py#L1653-L1679)).
Pose stamp age is not part of this hold. If covariance is absent or malformed,
the collision-envelope helper silently returns zero added uncertainty
([`pipeline.py:2562-2574`](../../../../src/parcel_robot/navigation/pipeline.py#L2562-L2574)).
The degraded stub fallback remains outside the pose seam by explicit test
([`test_pose_consumers.py:447-462`](../../../../tests/test_pose_consumers.py#L447-L462)).

Before a real localizer, freeze this interface:

```text
PoseEstimateV1
  capture_time / receive_time / valid_until
  odom_T_base
  map_T_odom
  covariance
  health
  transform_epoch / reset_counter
  calibration_id / source

ObservationJoinV1
  decision_time
  pose_evidence_id
  lidar_evidence_id / coverage
  dynamic_track_set_id
  maximum_capture_skew
  common transform_epoch
  valid_until
```

Local tracking remains continuous in ODOM. Every MAP goal is transformed into
ODOM at the joined evidence time. Terminal relations remain MAP witnesses. A
loop correction increments the transform epoch, invalidates the old local path,
and resets terminal dwell; it must never teleport an active ODOM trajectory.
Truth can implement this exact ABI only in labeled simulation.

### 4. Turn-first, forward motion, and lateral motion

The user's movement preference is mostly reflected today:

| Behavior | Turn-first? | Nominal translation | Planner-aware? |
| --- | --- | --- | --- |
| `grid_v1` destination | Yes, 55° enter / 7° exit | forward `vx`; `vy=0` | Yes |
| direct follow | Yes, threshold from follow config | forward `vx`; `vy=0` | No |
| behind follow | Yes | forward `vx`; `vy=0` | No |
| orbit | Yes before each tangent point | forward arc; `vy=0` | No |
| step forward/back/away | Yes relative to chosen facing | positive or negative `vx`; `vy=0` | No |
| manual | Operator-selected | `vx`, `vy`, `vyaw` | No route, but final gate applies |

The grid controller is not sliding laterally toward a destination, which is
good. It can still command a fairly tight forward arc for heading errors below
55 degrees. Its yaw command and forward speed are independently computed; there
is no curvature relation, lateral-acceleration cap, or swept-arc footprint test
([`grid_navigator.py:450-497`](../../../../src/parcel_robot/navigation/grid_navigator.py#L450-L497)).
That explains stop/turn/ramp cycling and corner behavior better than “the robot
needs an RL policy.”

The smallest controller upgrade is an RPP-style tracker inside `grid_v1`, not a
new stack:

```text
track(path_odom, pose_odom, observation_join, limits):
  prune passed path points
  resample path by arc length
  Ld = clamp(L0 + kv * abs(v_measured), Lmin, Lmax)
  p = first path intersection at arc length Ld
  alpha = atan2(p.left, p.forward)

  if turn_first_hysteresis(alpha):
      candidate = (0, 0, bounded_yaw(alpha))
  else:
      curvature = 2 * p.left / max(Ld^2, epsilon)
      v = min(
          cruise,
          goal_cap(distance_to_goal),
          curvature_cap(curvature, lateral_accel_limit),
          clearance_cap(metric_clearance),
          ttc_cap(dynamic_tracks),
          pose_uncertainty_cap(covariance),
      )
      candidate = (v, 0, curvature * v)

  require swept_arc_clear(candidate, footprint, horizon, joined_geometry)
  return candidate or typed HOLD
```

Lateral remains an explicit, penalized candidate rather than normal travel:

```text
consider lateral only when:
  allow_lateral is true
  heading is already aligned within a small bound
  forward progress is persistently blocked
  a bounded lateral displacement materially improves route clearance/progress
  the entire lateral swept footprint has fresh metric coverage
  abs(vy), lateral acceleration, duration, and displacement are capped
```

Do not add lateral velocity as an LLM action and do not blend it continuously
into ordinary goal pursuit. This matches Design A's stated preference and keeps
the existing Unitree-compatible `MidLevelCommand` interface.

### 5. Planner/controller agreement and unknown space

The planner admits unknown cells with a cost of 2.5 by default
([`grid_planner.py:128-172`](../../../../src/parcel_robot/navigation/grid_planner.py#L128-L172)).
The controller correctly refuses a line segment unless every cell after the
start is observed and hard-clear
([`grid_planner.py:1602-1620`](../../../../src/parcel_robot/navigation/grid_planner.py#L1602-L1620)).
An opt-in frontier mode clips unknown suffixes specifically to avoid rotate-only
deadlock, but `reachable_frontier_fallback` is false by default
([`grid_planner.py:962-1000`](../../../../src/parcel_robot/navigation/grid_planner.py#L962-L1000)).
The default can therefore produce an unknown-admitting global hypothesis that
the local waypoint selector will not execute, relying on recovery rotation to
reveal enough map.

There is also a measured geometry-policy mismatch. The planner's shipping hard
inflation is footprint plus a 0.10 m map margin, while the mid-level collision
gate stops much farther from an obstacle. The pipeline documents routes that are
“routable and impassable” and waits 60 stopped ticks before releasing the target
([`pipeline.py:2628-2670`](../../../../src/parcel_robot/navigation/pipeline.py#L2628-L2670)).
Today's live audit measured a 10.4 s stall from this mismatch
([`task_1/README.md:29-34`](../../task_1/README.md#L29-L34)).

Do not solve this by blindly making every 0.8 m comfort region a hard obstacle;
that can destroy legitimate narrow-passage reachability. Instead:

1. define one centre-to-obstacle-surface convention in `SafetyEnvelope`;
2. hard-inflate by footprint plus the non-negotiable static margin and pose/sensor
   uncertainty;
3. derive a soft comfort/refusal cost from the same envelope and make its weight
   non-zero;
4. let the RPP speed cap use speed-dependent stopping distance and directional
   clearance;
5. require the final independent gate to remain authoritative;
6. evaluate any changed route distribution as a re-baseline, not a hidden tune.

This is close to the already proposed `safety-margin-derivation` card in
[`task_1/README.md:102-106`](../../task_1/README.md#L102-L106), but the dimensional
authority defect must be corrected first.

### 6. Dynamic people and moving obstacles

The soft/hard separation is good, but the current soft field has a mathematical
defect. `agent_cost_at` sums every predicted track/time Gaussian, then divides by
`weights.sum() * len(tracks)`
([`dynamic_costs.py:62-85`](../../../../src/parcel_robot/navigation/dynamic_costs.py#L62-L85)).
Adding a distant track therefore lowers the contribution of an unchanged nearby
dangerous track. This violates monotonicity: adding evidence of another person
must not make any cell cheaper.

The parser keeps the first 16 tracks in payload order and raises on any malformed
entry
([`dynamic_layer.py:159-184`](../../../../src/parcel_robot/navigation/dynamic_layer.py#L159-L184)).
`AgentTrack` carries only `x, y, vx, vy, radius`; it has no ID, timestamp, age,
covariance, health, class, or prediction provenance
([`dynamic_costs.py:12-29`](../../../../src/parcel_robot/navigation/dynamic_costs.py#L12-L29)).
One malformed item disables the entire planner layer for the tick
([`grid_navigator.py:512-525`](../../../../src/parcel_robot/navigation/grid_navigator.py#L512-L525)),
and malformed TTC input logs and returns the prior command
([`runtime.py:4916-4929`](../../../../src/parcel_robot/runtime.py#L4916-L4929)).

Use a monotone field:

```text
for each track i:
  c_i(q) = sum_t w_t * gaussian(q; predicted_i(t), Sigma_i(t)) / sum_t w_t

C_people(q) = 1 - product_i(1 - clamp(c_i(q), 0, 1))
```

`max_i c_i` is an even simpler safe first implementation; probabilistic union
also represents crowd density without dilution. Keep the owner field separate
with its lower social weight. Select the bounded track set by minimum predicted
clearance/TTC, not arrival order, with deterministic tie-breaking and dropped
track telemetry.

The track-set interface should include:

```text
DynamicTrackV1
  stable_track_id / class
  capture_time / valid_until
  frame / transform_epoch
  position / velocity / covariance / radius
  confidence / health / provenance

DynamicTrackSetV1
  sequence / evidence_id / coverage / health
  tracks[] / dropped_count / malformed_count
```

Invalid optional social prediction may remove only the soft cost and must be
loud. If dynamic-agent tracking is required by the active physical ODD, stale or
malformed `DynamicTrackSetV1` means translation HOLD. It must never silently
disable the required final TTC contract. Raw LiDAR/depth geometry remains an
independent hard layer in either case.

Replanning A* on every tick while dynamic costs are active
([`grid_navigator.py:403-413`](../../../../src/parcel_robot/navigation/grid_navigator.py#L403-L413))
is responsive but can create CPU jitter and homotopy flapping. Add route-switch
hysteresis: retain the current route unless the challenger is hard-invalid or
improves total cost by a configured relative margin for a dwell. This should be
measured before adding ORCA, MPPI, or a learned planner.

Finally, people are intentionally excluded from the static gate-blocked recovery
counter
([`pipeline.py:695-705`](../../../../src/parcel_robot/navigation/pipeline.py#L695-L705)),
and the progress watchdog freezes while a person is inside the stop band
([`pipeline.py:2431-2445`](../../../../src/parcel_robot/navigation/pipeline.py#L2431-L2445)).
Yielding is correct, but indefinite commitment is not. After a bounded patience
window, rerank alternate approach poses/routes to the **same target** before
releasing the instance; never weaken the person gate.

### 7. Owner approach, persistent follow, and orbit

The most important behavior/lifecycle mismatch is still live. `sketch_come`
says “approach” in its docstring but compiles to `FollowFormation(relation=follow)`
([`local_plans.py:79-103`](../../../../src/parcel_robot/voice/local_plans.py#L79-L103));
“go to the owner” uses that same sketch
([`local_plans.py:190-202`](../../../../src/parcel_robot/voice/local_plans.py#L190-L202)).
The compiler defines `following` as success
([`compiler.py:71-76`](../../../../src/parcel_robot/brain/compiler.py#L71-L76)),
and the adapter returns a terminal result while the follow controller is still
enabled
([`runtime_adapter.py:439-467`](../../../../src/parcel_robot/brain/runtime_adapter.py#L439-L467)).

This violates both the shared foundation and Designs A/B:

- `ApproachOwner` is terminating: choose an admissible owner-relative goal,
  arrive, stop, dwell, release the base;
- `FollowFormation` is persistent: continuously refresh an expiring formation
  goal and report `holding_formation` feedback, never terminal success merely
  because it is momentarily in band;
- `OrbitOwner` is terminating only after confirmed owner identity, collision-free
  angular progress, radial-band compliance, and a final stop witness.

All three should share a planner-facing goal interface:

```text
FormationGoalGenerator.update(
  task_key,
  owner_track,
  people_tracks,
  traversability,
  robot_pose,
) -> GoalCandidateSetV1

GoalCandidateV1
  goal_region / preferred_pose
  owner_evidence_id
  visibility_score
  path_cost_hint
  social_clearance
  valid_until
```

For follow, sample owner-relative poses behind and slightly to either side,
subtract hard geometry/road keepouts/person envelopes, score reachability,
visibility, predicted owner motion, switching cost, and path length, then send
the selected short-TTL goal to the same grid/RPP path as navigation. If no goal
is reachable, hold, keep gaze/reacquisition where safe, and explain the blocking
reason. Do not fall back to direct drive through a wall.

The current prediction filter, owner keepout clamp, bounded SearchOwner state
machine, and uncertainty brake should be retained. What is missing for physical
use is enrolled identity and ambiguity evidence; a simulator `owner` record is
not sufficient to prevent switching to a similar nearby person.

Orbit can initially generate a short sequence of collision-checked SE(2) tangent
goals around the same confirmed owner and feed them to the common local
controller. The current angular-progress logic is worth preserving, but the
direct `_track_point` command is not enough in clutter.

### 8. Terminal witnesses and recovery

Current terminal verification is stronger than ordinary navigation stacks:
geometric arrival only enters a `verifying` phase
([`pipeline.py:638-672`](../../../../src/parcel_robot/navigation/pipeline.py#L638-L672));
success additionally requires the live semantic relation and settled feedback
([`pipeline.py:2718-2757`](../../../../src/parcel_robot/navigation/pipeline.py#L2718-L2757)).
`inside` deliberately cannot succeed from a raw boundary hit; it must first reach
its approach pose
([`pipeline.py:3018-3032`](../../../../src/parcel_robot/navigation/pipeline.py#L3018-L3032)).

The gap is temporal independence. On the first tick where `relation_verified`
and `settled` are both true, the mission becomes `arrived`; there is no
uninterrupted dwell. Add a `TerminalWitnessV1` accumulator:

```text
terminal_tick(now, task_key, goal, observation_join, control_feedback):
  require current task/revision/goal IDs
  require fresh healthy MAP pose and transform epoch
  require relation-specific metric predicate
  require fresh target evidence where the relation needs it
  require no hard brake / collision / unauthorized road state
  require exact commanded hold and settled measured motion
  if every predicate true continuously:
      accumulate dwell
  else:
      reset dwell and record first failed predicate
  succeed only when dwell >= goal.required_dwell
```

Use monotonic time, not control-tick count. Reset on relocalization, candidate
change, task revision, brake, lost target, or motion above settled limits.

Recovery is currently split across layers:

- grid no-path recovery rotates, alternating direction every configured scan
  window; reverse is disabled by default
  ([`grid_navigator.py:538-559`](../../../../src/parcel_robot/navigation/grid_navigator.py#L538-L559));
- the outer semantic pipeline waits 60 no-progress ticks before releasing an
  unroutable or gate-blocked candidate
  ([`pipeline.py:2459-2511`](../../../../src/parcel_robot/navigation/pipeline.py#L2459-L2511),
  [`pipeline.py:2619-2670`](../../../../src/parcel_robot/navigation/pipeline.py#L2619-L2670));
- the broader watchdog replans twice and then fails after 200 ticks
  ([`default.yaml:24-37`](../../../../configs/navigation/default.yaml#L24-L37));
- the executive has recovery machinery, but the compiler forces
  `max_attempts=1`, so compiled steps cannot enter it
  ([`compiler.py:77-100`](../../../../src/parcel_robot/brain/compiler.py#L77-L100),
  [`executive.py:636-650`](../../../../src/parcel_robot/brain/executive.py#L636-L650)).

Consolidate this into one typed, bounded ladder owned by the task revision:

```text
BLOCKED_DYNAMIC:
  exact hold -> patience dwell -> replan same goal -> alternate approach same target
  -> alternate target only when request semantics allow -> clarify/fail

NO_PATH_STATIC:
  exact hold -> bounded observed scan -> known-free frontier micro-advance
  -> replan same goal -> alternate approach -> clarify/fail

LOCALIZATION_BAD:
  exact hold -> relocalize/reobserve -> operator assistance/fail

TARGET_AMBIGUOUS_OR_LOST:
  exact hold -> bounded resight/search -> clarify/fail
```

Every phase has an entry predicate, maximum duration/attempts, an evidence
requirement, and a terminal reason. No recovery weakens a hard mask or silently
changes the target class.

### 9. Lifecycle, command lineage, and reactions

The TaskExecutive already owns task records, resources, checkpoint-aware
interrupts, task priority, and pause/resume. Social and gesture interrupts defer
while higher-priority work is active
([`executive.py:507-573`](../../../../src/parcel_robot/brain/executive.py#L507-L573)),
which is the right answer for “react naturally, but do not interrupt an important
task.” Preserve that policy.

The missing part is complete downstream identity. `submit_motion` sends only
`source`, command, and TTL to `MotionIntent`
([`runtime.py:2270-2297`](../../../../src/parcel_robot/runtime.py#L2270-L2297));
the final setpoint cannot be traced through task revision, step, goal, planner,
evidence join, safety decision, and command sequence as required by the shared
single-writer rule
([`SHARED_FOUNDATION.md:36-51`](../../../20260808/task_1/SHARED_FOUNDATION.md#L36-L51)).

The validator derives multiple system invariants, including collision margin,
yielding, road avoidance, and owner visibility
([`validator.py:627-666`](../../../../src/parcel_robot/brain/validator.py#L627-L666)).
Runtime stores only one `_active_invariants` tuple and one owner task ID
([`runtime.py:652-655`](../../../../src/parcel_robot/runtime.py#L652-L655));
the concrete enforcement search finds only `stop_on_stale_perception`, whose
implementation is good but global
([`runtime.py:1567-1602`](../../../../src/parcel_robot/runtime.py#L1567-L1602)).
Concurrent/overlapping tasks can therefore overwrite the active invariant set,
and other declared invariants are largely descriptive or implemented in
unrelated behavior-specific code.

Adopt the shared `TaskRevisionV1`, `NavGoalV1`, `NavFeedbackV1`, and command
lineage fields before adding asynchronous model proposals. A late Gemma/VLM or
planner result must fail a same-revision check and be discarded; it must not
revive a stopped or amended task.

### 10. City semantics, road policy, and current near-arrival work

The repository contains a `FootwayCrossingGraph`, map waypoint proposer, and
`CrossingModePolicy`, and their unit tests are useful. A source search finds no
product runtime/navigation consumer outside `parcel_robot.maps`; the policy is
not on the active path. `avoid_road_when_not_crossing` is compiled as an
invariant, but no runtime implementation consumes that name. Google Maps is
correctly disabled as a placeholder
([`robot.yaml:18-22`](../../../../configs/robot.yaml#L18-L22)).

Therefore the present demo can ground a sidewalk polygon, but Parcel cannot yet
claim a general city ODD rule such as “never enter road except through an
authorized crossing transaction.” Wire road/sidewalk/curb regions as route
constraints and hard keepouts; a map or semantic label may propose a region but
camera/LiDAR metric evidence must confirm local traversability.

#### Working-tree-only near fallback risk

The current dirty patch contains two different ideas:

1. the `near` planning-band inset in `approach.py` narrows the preferred pose away
   from both terminal band edges. That is directionally sound and addresses the
   measured 1.06 cm outer-band miss, pending a clean paired run;
2. a new fallback chooses any band-midpoint sample clear of up to 64 raw obstacle
   points, explicitly dropping the support-surface constraint
   ([`near_arrival.py:1-44`](../../../../src/parcel_robot/instructnav/near_arrival.py#L1-L44),
   [`pipeline.py:1534-1608`](../../../../src/parcel_robot/navigation/pipeline.py#L1534-L1608)).

The second idea is not ready to merge as a navigation fix:

- it does not require the point to lie on a sidewalk/walkable support polygon;
- it does not apply the road keepout or common rolling-grid hard/unknown mask;
- when `lidar_obstacles` is absent, `_non_target_obstacle_points` returns an empty
  tuple and the pure sampler treats every bearing as clear
  ([`pipeline.py:1610-1651`](../../../../src/parcel_robot/navigation/pipeline.py#L1610-L1651));
- terminal verification still rejects a `near` result outside the support
  polygon
  ([`pipeline.py:2864-2875`](../../../../src/parcel_robot/navigation/pipeline.py#L2864-L2875)).

It can therefore recreate exactly the planner/verifier mismatch it intends to
fix, and—because the road invariant is not wired—can propose the road side of a
street object. Route every fallback through one admissible `GoalRegion` sampler:

```text
near_goal_candidates =
  requested_distance_band
  ∩ walkable_support
  - road/ODD keepouts
  - hard inflated occupancy/unknown
  - dynamic prediction envelopes
  - owner/person keepouts
```

If that intersection is empty, the honest result is same-target alternate
viewpoint/search, a different authorized instance, clarification, or failure—not
dropping the walkable-support contract. At the test snapshot, the untracked
diagnostic `tests/test_zzscratch_nearprobe.py` printed probe state and ended with
`assert True`; it was subsequently removed by concurrent work and was never a
quality gate.

## Delta against the selected architecture

The 2026-08-08 decision recommends Design B as the product architecture, Design
A as its deterministic operational baseline, and Design C only as a shadow
challenger
([`COMPARISON_AND_RECOMMENDATION.md:1-14`](../../../20260808/task_1/COMPARISON_AND_RECOMMENDATION.md#L1-L14)).

| Foundation / Design A-B property | Current state | Gap closure |
| --- | --- | --- |
| Unitree Sport owns gait/balance/joints | **Present in design and adapter; uncommissioned** | Commission axes, state frame, modes, stop feedback, latency, and braking before HIL. |
| Exactly one base writer | **Partial**: source-priority arbiter and manager single writer | Carry task/revision/step/goal/evidence/command lineage into every lease and setpoint. |
| Post-shaper metric safety | **Fail** | F-01 exact-zero/non-relaxable admission slice. |
| Missing required geometry means HOLD | **Fail** | Remove implicit stub fallback; add observation join and directional coverage. |
| Production MAP/ODOM pose | **Fail** | Freeze transform ABI, then integrate a commissioned estimator. |
| Atomic pause/resume | **Now present for tested path** | Extend transaction to goal/proposal buffers and stale output rejection. |
| `ApproachOwner` distinct from `FollowFormation` | **Fail** | Add terminating skill and make follow explicitly persistent. |
| Per-task executable invariants/recovery | **Partial** | Store/enforce invariant union per task revision; enable typed bounded recovery. |
| Forward/turn-first normal travel | **Present but primitive** | Replace independent yaw/speed P-control with RPP-style curvature and swept arc. |
| Lateral allowed but penalized | **ABI present; autonomous selector absent** | Add only after forward RPP is stable, behind explicit coverage/cost gates. |
| Dynamic prediction/social cost | **Partial with monotonicity defect** | Per-track normalization, monotone merge, risk-ranked tracks, health/covariance. |
| Formation goals use common planner | **Fail** | Rolling owner-relative goal regions through grid/RPP. |
| Independent terminal witness with dwell | **Partial** | Add revision/evidence-bound uninterrupted dwell and brake state. |
| Road/crossing authorization | **Library only** | Put constraints on `NavGoalV1` and active route/terminal path. |
| Async model is proposal-only and deadline-bound | **Partial**: model plans are validated; full proposal ABI absent | Land only after revision/evidence ABI; keep models out of control ticks. |
| Nav2/MPPI/learned candidates | **Not active, correctly** | Evaluate as exclusive challengers after deterministic gates. |

This means Design B does **not** replace current classical navigation. It adds
open-world task/goal/reaction proposals above a completed Design-A execution
spine. The immediate work is making that spine true.

## Ordered implementation slices

Each slice is intentionally small enough for one reviewable change family. Do
not combine a safety-authority change, controller change, and eval-budget change
in one result row.

### S0 — freeze an honest baseline

**Purpose:** make every later comparison attributable.

- Separate and review the concurrent near-arrival and personality work.
- Fix the stale AST test to compare evaluated authority values or a frozen
  fixture; remove or move the scratch always-pass probe outside collected tests.
- Record `{git_sha, dirty_patch_digest, config_digest, scene_digest, episode_set,
  max_steps, seed}` on every eval row.
- Run the default focused navigation tests and one frozen headless smoke before
  any algorithm change.

**Exit:** clean focused test gate; reproducible baseline manifest.  
**Behavior change:** none.

### S1 — post-shaper safety disposition and exact-zero assertion

**Purpose:** close F-01 without changing path planning.

- Introduce `MotionAdmissionV1` with `EXACT_HOLD` versus
  `TRANSLATION_HOLD` semantics.
- Carry the pre-shaper reason forward, re-evaluate/reassert after shaping, reset
  affected shaper state, and assert the final HAL command.
- Add command-sequence and evidence IDs to the decision log.

**Tests:** proximity, TTC, stale observation, malformed required dynamic geometry,
rotate-only hold, explicit E-stop, terminal stop, and intent expiry; assert the
exact command seen by a fake controller on the same dispatch.  
**Exit:** no veto path produces residual unauthorized motion.  
**Behavior change:** stop ticks only.

### S2 — fail-closed observation join and motion-direction coverage

**Purpose:** close F-02/F-03/F-05 at the interface before adding a localizer.

- Add `ObservationJoinV1` and `PoseEstimateV1.map_T_odom/transform_epoch`.
- Make active `grid_v1` HOLD on missing/malformed/stale/unsynchronized scan,
  pose, transform, or commanded-direction coverage.
- Keep `stub_v0` only as an explicitly selected test/simulation model.
- Gate reverse and lateral swept footprints; turn-to-face and go forward when
  rear coverage is absent.

**Tests:** missing scan, repeated timestamp, capture skew, map/odom divergence,
transform reset, `DEGRADED`/`LOST`, 270-degree rear wedge, side coverage, and
truth-provider equivalence.  
**Exit:** no required-input fault reaches non-zero translation.  
**Behavior change:** degraded inputs now HOLD instead of translating.

### S3 — dimensionally valid, single safety envelope

**Purpose:** close F-04 and planner/gate drift before physical commissioning.

Current code documents
`person_stop = max(zone, stop_distance + 1.4 * reaction_latency)` while metadata
declares `1.4` dimensionless
([`authority.py:478-503`](../../../../src/parcel_robot/authority.py#L478-L503),
[`authority.py:610-617`](../../../../src/parcel_robot/authority.py#L610-L617)).
Replace the factor with a quantity carrying speed, for example
`person_intrusion_speed_mps`, or an explicitly measured distance allowance:

```text
person_stop(v_robot) = max(
  social_zone_m,
  stop_distance(v_robot)
    + assumed_person_closing_speed_mps * response_time_s
    + person_tracking_uncertainty_m,
)
```

- Freeze one centre-to-surface convention.
- Derive planner, mid-level, runtime, TTC, and terminal thresholds from one
  versioned envelope; remove the current 0.6/0.65/0.8 drift
  ([`authority.py:575-582`](../../../../src/parcel_robot/authority.py#L575-L582)).
- Preserve separate hard stopping and soft comfort bands.

**Tests:** dimensional/unit properties, monotonicity in speed/latency/uncertainty,
family equality, and measured-deceleration fixture.  
**Exit:** one derivation and one convention; no claim of ISO/physical validity
until commissioned measurements exist.  
**Behavior change:** likely route/speed re-baseline; land separately.

### S4 — RPP-style forward controller inside `grid_v1`

**Purpose:** improve smoothness without changing the planner/backend interface.

- Resample the existing A* path and use velocity-scaled lookahead.
- Couple yaw rate to curvature; cap speed by curvature, goal distance, clearance,
  TTC, and uncertainty.
- Retain turn-first hysteresis and nominal `vy=0`.
- Add swept-arc footprint admission.
- Preserve deterministic tie-breaking and the current `MidLevelCommand` ABI.

**Tests:** 90/180-degree starts, S-turn, doorway, U-shape, obstacle corner,
goal approach, frame reset, and path invalidation. Assert turn-first compliance,
lateral fraction zero, no corner cutting, bounded curvature/lateral acceleration,
and no regression in hard interventions.  
**Eval:** paired frozen headless run with the same goals/budget; report success,
time, path length, rotation fraction, stop-turn cycles, curvature/jerk,
interventions, and p95 controller time.  
**Exit:** measured smoother progress without a safety/witness regression.

### S5 — monotone dynamic layer and route-switch hysteresis

**Purpose:** fix F-09 before trying a learned crowd policy.

- Expand track schema with time/frame/covariance/health/ID.
- Normalize time per track, combine tracks with `max` or probabilistic union.
- Select top K by minimum predicted clearance/TTC.
- Add track-set health and ODD-specific invalid-data policy.
- Add route-switch margin/dwell; hard invalidation still switches immediately.

**Tests:** adding any track never lowers cost; permutation invariance; risky track
survives truncation; covariance and age widen/expire cost; malformed/stale policy;
crossing, overtaking, sudden stop, dense opposing flow, and oscillating homotopy.  
**Exit:** monotone cost and no source-order dependence.  
**Parallelism:** pure math/schema work can proceed beside S4 after S1/S2 ABI is
frozen.

### S6 — common goal candidates, same-target rerank, and terminal dwell

**Purpose:** fix approach/recovery/terminal agreement.

- Replace one committed approach pose with an ordered, evidence-linked
  `GoalCandidateSetV1` produced from relation band, walkable support, hard
  occupancy/unknown, road keepouts, people, and path cost.
- Commit with hysteresis; rerank only after hard invalidation or bounded dynamic
  blockage.
- Try alternate poses for the same entity before excluding it.
- Add revision-bound `TerminalWitnessV1` and uninterrupted dwell.
- Make person patience expiry invoke rerank/replan, never weaken person stop.

**Tests:** sidewalk, next-to lamppost, wait-by with a person on the first approach,
narrow-support bench, wrong-side-of-road street furniture, relation flicker,
settled-feedback flicker, pose reset, and class-consistent re-grounding.  
**Exit:** planner and verifier consume the same goal-region contract; no false
success on a transient tick.  
**Parallelism:** witness accumulator can proceed beside S4/S5 once task/evidence
IDs from S1/S2 are frozen.

### S7 — split `ApproachOwner`; route formation/orbit through common navigation

**Purpose:** fix F-10 without discarding the good owner filter.

- Add `ApproachOwner` to the registry/compiler/runtime adapter.
- Change `come` and owner-directed NavigateTo to that terminating skill.
- Mark `FollowFormation` persistent; use state feedback rather than terminal
  success while enabled.
- Generate short-TTL owner-relative goal regions into grid/RPP.
- Route orbit tangent goals through the same swept-footprint controller.
- Require enrolled owner identity or stop/clarify on ambiguity.

**Tests:** stationary come, moving follow behind, wall between robot/owner,
occlusion, look-alike identity ambiguity, manual preempt/release, one small orbit
with crossing pedestrian, and stale-goal expiry.  
**Exit:** no follow adapter reports terminal success while it owns the base;
formation can route around static obstacles.  
**Parallelism:** owner goal-generator geometry can be built beside S4/S5, but
product wiring waits for S1/S2/S6 contracts.

### S8 — production localization and Unitree commissioning

**Purpose:** turn the simulation contract into a physical one.

- Integrate a real ODOM/MAP producer behind the frozen pose ABI.
- Calibrate camera/LiDAR extrinsics, timestamps, coverage, covariance, and reset
  behavior.
- Commission Unitree axes, velocity frame, allowed modes, latency, stop feedback,
  and measured braking on a restrained/controlled setup.
- Keep Sport as the closed-loop gait/balance controller.

**Gates:** recorded-bag replay, fault injection, HIL with elevated/no-load or
otherwise controlled setup, independent hardware E-stop, then progressively
bounded ODD trials.  
**Exit:** physical mode refuses to arm without every commissioned artifact ID.

### S9 — exclusive open-source challengers; learned proposals last

After S1–S8 are measurable:

1. build a Nav2 adapter with Smac/global planning plus RPP as the first exclusive
   challenger;
2. test MPPI only if dynamic-scene failures remain and device p95/p99 deadlines
   are feasible;
3. run open-weight navigation policies in shadow through a bounded trajectory
   proposal ABI;
4. train RL only if frozen counterfactual logs show a repeatable residual that
   classical/open-weight candidates do not cover.

Exactly one local controller owns a command at a time. Switch only while stopped
and in a new task/controller revision. No model emits a residual velocity or
certifies safety/success. This is the A-baseline/B-product/C-shadow composition
already recommended by the architecture packet
([`COMPARISON_AND_RECOMMENDATION.md:111-149`](../../../20260808/task_1/COMPARISON_AND_RECOMMENDATION.md#L111-L149)).

## Parallel work after the serial foundation

```text
S0 baseline
   |
S1 exact-zero + lineage header
   |
S2 observation/pose/coverage ABI
   |
S3 one dimensional safety envelope
   |
   +----------------+----------------+----------------+
   |                |                |                |
 S4 RPP         S5 dynamics      S6 witnesses     owner goal geometry
   |                |                |                |
   +----------------+-------+--------+----------------+
                            |
                  S7 common owner planner
                            |
                 S8 localization + commissioning
                            |
                  S9 Nav2/MPPI/model challengers
```

Evaluation work can proceed in parallel from S0: frozen manifests, dynamic
scenario generators, task/revision mutation tests, terminal boundary fuzz, and
latency trace plumbing do not need to change runtime behavior. Real localization
producer research can proceed behind S2's ABI, but product wiring must wait for
the contract.

## Required evaluation gates

### Per-change software gates

- final HAL exact-zero and single-writer lineage;
- stale/missing/malformed/frame/coverage fault matrix;
- deterministic replay and stale revision rejection;
- planner/controller/terminal agreement;
- dynamic cost monotonicity and permutation invariance;
- no false terminal under evidence, brake, pose, and feedback flicker;
- bounded recovery with named exit reason;
- focused test suite green, including the repaired dynamic-layer authority test.

### Headless scenario families

1. go onto the sidewalk and prove not-road;
2. wait within 1 m of the lamppost on walkable support;
3. one small orbit around the verified owner with a crossing pedestrian;
4. come to a stationary owner and terminate;
5. follow behind a moving owner around a wall and through a doorway;
6. five steps away with an obstacle/rear blind wedge;
7. dynamic crossing, sudden stop, opposing group, and temporary goal blockage;
8. missing scan, stale pose, transform reset, lost owner, planner deadline, and
   controller watchdog faults;
9. candidate ambiguity, wrong class, synonym, memory hit, and absent target;
10. manual takeover and release while a model proposal is in flight.

Each scenario must score trajectory and semantics independently: requested task,
referent, relation, forbidden-region occupancy, hard collision, minimum
person/obstacle clearance, intervention, path/rotation/lateral fractions,
recovery, terminal dwell, measured stop, lifecycle ownership, spoken claim, and
latency tails.

### Promotion rule

A controller/model is promoted only when the same frozen episode rows show an
improvement without regression in:

- hard collision or unauthorized road entry;
- exact-zero/freshness/task-lineage compliance;
- owner identity integrity;
- terminal truthfulness;
- p95/p99 sensor-to-command and user-to-response deadlines;
- target-device CPU/GPU/memory/thermal feasibility.

Success rate, SPL, or a leaderboard score alone cannot override those gates.
This preserves the robot-dog product goal while hill-climbing navigation quality.

## Team decisions requested

1. Approve Design B as product architecture, Design A as mandatory operational
   baseline, and Design C as shadow-only, as already recommended.
2. Approve S0–S3 as blocking foundation work before controller/model hill-climb.
3. Approve in-place RPP-style `grid_v1` improvement before a Nav2 migration.
4. Approve `ApproachOwner`/persistent `FollowFormation` split and a common
   formation goal generator.
5. Decide the physical localization path only after accepting the MAP/ODOM ABI;
   truth remains simulation-only.
6. Reject the working-tree near fallback in its current off-support form, or
   require it to use the common walkable/road/hard-geometry goal sampler before
   merge.
7. Do not select or train a navigation model until the deterministic baseline,
   authority gates, and frozen dynamic evals can identify a genuine residual.

The practical conclusion is straightforward: Parcel does not need a new brain
to stop sliding or to follow paths smoothly. It first needs its existing
classical controller and evidence contracts completed. Once those are reliable,
the conversational/model layer can safely make the dog smarter about **what** to
do, while deterministic planning, control, and witnesses remain authoritative
about **how** the body moves and whether it truly succeeded.
