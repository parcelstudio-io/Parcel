# Shared foundation — contracts, invariants, and common algorithms

This document defines the parts that must not vary between the three proposed
designs. A design may replace a goal proposer, semantic reasoner, global
planner, or local controller. It may not replace the task authority, evidence
rules, final safety monitor, or Unitree Sport boundary without a separate
safety and embodiment program.

## 1. Authority model

Parcel has five authority levels. Data moves downward; authority does not move
upward.

```text
L4  dialogue / LLM / VLM / route memory / external maps
      may propose text, task sketches, semantic candidates, goals, trajectories
                              │
L3  trusted compiler + task executive + authorization policy
      owns task/revision, resources, deadlines, recovery, interruption
                              │
L2  metric planner + local controller
      owns one selected path and one bounded body-velocity target
                              │
L1  final post-shaper safety + ControlManager
      may reduce or zero motion; owns watchdog and feedback admission
                              │
L0  Unitree Sport
      owns gait, balance, joint control, motor feedback
```

An L4 result can be useful and still be rejected. Confidence never allows an
L4 or L3 component to widen an L1 envelope. The final monitor never decides
where the dog should go; it only admits, reduces, or stops the already shaped
command.

### Single-writer rule

At any instant there is exactly one base-lease owner and one command lineage:

```text
task_id/revision/step
  → admitted goal_id
  → controller_plan_id
  → command_sequence
  → safety_decision_id
  → ControlManager setpoint sequence
```

Manual input is another L3 task source, not a bypass. It preempts lower-priority
base work but still uses limits, shaping, the final monitor, feedback watchdog,
and Unitree Sport.

## 2. Required Phase-0 corrections

The interfaces below are not evidence that the current stack is safe. Before
any design gains physical authority, all of these gates must be green:

1. A proximity/TTC/state veto reasserts exact zero **after** every smoother and
   shaper in the same dispatch and resets their state.
2. Missing, stale, malformed, frame-invalid, or uncovered required geometry
   produces HOLD/STOP. `StubNavigator` translation is never a product fallback.
3. Production pose comes from a commissioned estimator with covariance,
   freshness, and transform health. Simulator truth is labeled simulation only.
4. Pause/resume/cancel/replace changes the executive task, channel lease,
   controller goal, and proposal buffers in one revision transaction.
5. `ApproachOwner` and `FollowFormation` have distinct lifecycle semantics.
6. Recovery actions, queue/precondition/step/task deadlines, and per-task
   invariants are executable and bounded.
7. Unitree axes, frames, supported modes, stop feedback, latency, and measured
   deceleration are commissioned before HIL.
8. The person-stop equation is dimensionally valid and uses one clearance
   convention.

## 3. Time and evidence rules

All control-relevant time uses a monotonic clock. Wall time is logging metadata
only. Every sensor-derived record includes capture time, receive time, expiry,
sequence, frame, transform epoch, calibration ID, scene revision, source, and
provenance.

### Proposed timing bands

These are initial engineering budgets, not measured guarantees:

| Loop | Target cadence | Miss behavior |
| --- | --- | --- |
| Sport gait/balance | vendor-owned | vendor fault/stop policy |
| ControlManager + final monitor | 50–100 Hz | exact-zero stop |
| Local controller | 20–50 Hz | re-admit last plan only while fresh; else HOLD |
| LIO/ODOM producer | sensor-driven, at least 20 Hz target | DEGRADED slows; LOST stops |
| LiDAR/depth geometry | 10–30 Hz | direction/ODD coverage loss stops |
| Owner/person tracking | 15–30 Hz | ambiguous owner stops follow motion |
| Fast semantics | 5–15 Hz | semantic goal waits or re-observes |
| Global planning | 1–5 Hz or event-driven | local controller uses current valid path |
| Follow formation update | 5–20 Hz | expired goal stops/acquires |
| Learned proposer | 1–10 Hz by model | latest-only; expired output discarded |
| Task executive | event-driven plus ~10 Hz supervision | deadline/recovery/HOLD |
| Slow instruction planning | asynchronous | acknowledge, then clarify/HOLD on deadline |
| Conversation/TTS | streaming | independent of motion authority |

### Freshness join

A consumer validates all required inputs against **one decision time**. It does
not combine individually fresh values from incompatible epochs.

```text
valid_join(inputs, decision_time):
  require every input not expired at decision_time
  require capture skew <= contract.max_capture_skew
  require compatible calibration IDs and transform epoch
  require task/revision and scene revision constraints
  require pose/transform health for every referenced frame
  return immutable ObservationJoinV1 with evidence IDs
```

Any failed required check yields a typed reason and no motion output.

## 4. Versioned interface set

Existing `contracts/v1.py` types should be retained where possible:
`EvidenceEnvelopeV1`, `OwnerTrackV1`, `DynamicTrackV1`, `SemanticRegionV1`,
`GoalRegionV1`, `ReactionProposalV1`, `SceneQueryV1`, and `SkillFeedbackV1`.
The following complete the missing cross-lane ABI.

### Interface governance

The fields below are the **minimum normative semantics shared by all three
designs**. Each design document also shows implementation-oriented projections
or extensions for its own processes. Those are review proposals, not parallel
messages with the same name: an implementation may add versioned fields but may
not omit, rename, weaken, or reinterpret a shared field. Phase 0 must merge the
selected projections into one canonical serialization, publish conformance
fixtures, and reject ambiguous aliases at authority boundaries.

Quantities always preserve `{source_text, value, source_unit}`. SI-compatible
physical units may also carry a trusted normalized value. Embodiment-relative
units such as `step` remain unexpanded until the authorized skill adapter reads
the versioned robot profile; a model or parser does not invent that conversion.

### 4.1 `TaskRequestV1`

One canonical interpretation of an authorized user turn. Deterministic rules,
a small intent model, and a large planner all emit the same type.

```text
TaskRequestV1 {
  schema_version
  request_id, turn_id, session_id
  transcript_ref, transcript_sha256
  speaker_or_channel_authorization_id
  speech_act: request | correction | cancel | question | statement
  intent: NavigateTo | ApproachOwner | FollowFormation | OrbitOwner |
          MoveRelative | Hold | SearchEntity | Pose | Gesture | Converse |
          Clarify | EmergencyStop
  relation: inside | near | next_to | towards | behind | orbit | relative | hold
  target_query, target_kind
  quantity { value, unit, source_text }?
  modifiers { direction, size, speed_class, duration, repetitions }
  candidate_referents[]
  ambiguity: NONE | RESOLVABLE_FROM_SCENE | REQUIRES_USER
  urgency: EMERGENCY | SAFETY_CORRECTION | EXPLICIT | NORMAL | SOCIAL
  requested_interrupt: NOW | CHECKPOINT | WHEN_IDLE | NEVER
  evidence_ids[], observation_snapshot_id?
  created_monotonic_ns, expires_monotonic_ns
  parser_id, parser_revision
}
```

The parser never supplies raw coordinates or velocities from language. A
quantity is normalized only after unit and intent validation. “Five steps” is
stored as five steps until the trusted skill adapter reads the robot-profile
step length.

### 4.2 `TaskRevisionV1`

The trusted compiler expands a request or model sketch into bounded work.

```text
TaskRevisionV1 {
  schema_version
  task_id, plan_revision, parent_task_id?
  source_request_id, authorizing_channel_id
  goal_spec
  steps[] {
    step_id, skill, typed_arguments
    resources[]
    required_evidence_classes[]
    preconditions[]
    success_witness_spec
    queue_deadline, precondition_deadline, step_deadline
    max_attempts, recovery_actions[]
    interruptibility: IMMEDIATE | CHECKPOINT | WHEN_IDLE | NEVER
    persistence: TERMINATING | PERSISTENT
  }
  invariants[]
  task_deadline
}
```

System code owns resources, limits, witnesses, deadlines, retry count, and the
recovery allow-list. A model may choose only admitted skills and semantic
arguments. Unknown fields, raw motor fields, missing witnesses, and inconsistent
persistence are rejected.

### 4.3 State and perception

```text
PoseEstimateV1 {
  envelope
  odom_T_base, map_T_odom
  covariance
  linear_velocity, angular_velocity
  health: HEALTHY | DEGRADED | LOST
  transform_epoch
}

PerceptionSnapshotV1 {
  envelope
  pose_evidence_id
  geometry_layers[] { source, coverage, resolution, evidence_id }
  semantic_regions[]: SemanticRegionV1
  entities[]
  owner_track?: OwnerTrackV1
  people[]: DynamicTrackV1
  unknown_space_policy
}
```

Semantics can add keepouts or reduce speed. Only calibrated metric layers may
declare traversable geometry. A semantic label with no metric support is a
search or re-observation candidate, not a free cell.

### 4.4 Goals and controller feedback

```text
NavGoalV1 {
  goal_id, task_id, plan_revision, step_id
  frame: MAP | ODOM
  goal_region: GoalRegionV1
  preferred_pose?
  terminal_relation
  route_constraints { road_keepouts, crossing_auth_id?, floor_id, max_slope }
  kinematic_profile_id, robot_profile_id, safety_envelope_id
  observation_ids[], scene_revision
  issued_monotonic_ns, expires_monotonic_ns
}

NavFeedbackV1 {
  goal_id, controller_plan_id, sequence
  state: ACCEPTED | PLANNING | TRACKING | BLOCKED | HOLDING |
         VERIFYING | SUCCEEDED | FAILED | CANCELLED
  pose_evidence_id, geometry_evidence_ids[]
  path_progress, cross_track_error, heading_error
  command_sequence, command_is_zero
  feedback_velocity, settled
  active_brake_reason?
  replan_count, recovery_count
  blocking_reason?
}

NavResultV1 {
  goal_id, task_id, plan_revision, step_id
  outcome
  witness_bundle_id?
  terminal_pose_evidence_id?
  reason
}
```

Feedback is not success by itself. The terminal witness service independently
constructs the witness bundle.

### 4.5 Optional proposal and candidate interfaces

Designs B and C use these; Design A may implement only the classical source.

```text
NavProposalV1 {
  proposal_id, model_or_rule_id, artifact_hash, input_abi_hash
  task_id, plan_revision, step_id
  observation_ids[], scene_revision, frame, transform_epoch
  relative_se2_waypoints[] { x, y, yaw, t_from_start, covariance }
  claimed_role: OWNER_TRACK | URBAN_PRIOR | LOCAL_DETOUR | SEMANTIC_GOAL
  confidence_kind: CALIBRATED | SCORE_ONLY | UNKNOWN
  confidence?
  produced_monotonic_ns, expires_monotonic_ns
  diagnostics_ref
}

TrajectoryCandidateV1 {
  candidate_id, generator_id
  task_id, plan_revision, goal_id
  state_evidence_ids[]
  poses[] { x, y, yaw, t, vx, vy, wz }
  swept_footprints_ref
  generator_costs
  hard_admissible: false  # only validator may set true in a derived record
}
```

Proposals are immutable suggestions. Validation transforms them through
recorded history, clamps horizon and speed, rejects stale/foreign revisions,
checks role and identity policy, and applies hard geometry masks. Rejection
defaults to HOLD unless the same existing classical goal is independently
grounded, authorized, fresh, and re-admitted through every state/geometry gate.

### 4.6 Crossing authorization

```text
CrossingAuthorizationV1 {
  authorization_id
  task_id, plan_revision, step_id
  owner_identity_or_control_channel_id
  authorization_policy_revision
  curb_stop_event_id
  nonce
  issued_monotonic_ns, expires_monotonic_ns
  permitted_crossing_edge_ids[]
  replay_protection_state
}
```

ASR text, a phrase match, a model output, OSM, or CityWalker cannot construct
this object. A trusted policy verifies enrolled speaker/control-channel
authority at a current curb-stop event. Geometry and traffic checks remain
able to veto an authorized crossing.

### 4.7 Safety decision

```text
SafetyDecisionV1 {
  decision_id, command_sequence
  input_command, admitted_command
  pose_evidence_id, geometry_evidence_ids[], feedback_sequence
  envelope_id, robot_profile_id
  verdict: PASS | REDUCE | STOP
  reason_codes[]
  directional_clearance, predicted_ttc
  produced_monotonic_ns
}
```

The admitted command is elementwise no more permissive than the input. `STOP`
is exactly zero, resets every upstream shaper, and calls the stop path in the
same dispatch.

## 5. Dimensionally valid stopping envelope

Use one declared convention: every distance below is from the robot base
center to the obstacle/person surface in the planning plane. The robot
footprint radius is therefore included exactly once.

```text
d_robot(v) = r_footprint
           + v * tau_e2e
           + v^2 / (2 * a_measured)
           + z_sensing
           + z_pose

d_person(v, v_rel) = max(
    d_social_floor,
    d_robot(v) + max(0, v_rel_bound) * tau_person_prediction + z_person
)
```

All terms are metres. `v_rel_bound` is metres/second and its time allowance is
seconds. The present `person_latency_factor * reaction_latency_s` term must be
removed because it adds seconds to metres.

Parameters remain unverified until commissioning measures command-to-motion
latency, braking deceleration, pose uncertainty, sensing intrusion, and human
tracking uncertainty on the actual mount and surface.

## 6. Common navigation algorithm

The three designs differ in how candidate goals/paths are produced. Once a
goal is admitted, they share this execution contract.

### 6.1 Goal grounding

```text
ground(request, snapshot, memory):
  require task/revision and a valid evidence join
  candidates = registry.query(request.target_query, request.target_kind)
  candidates += fresh perception detections
  candidates += advisory map/memory nominees, labeled advisory

  if no candidates:
    if request permits active scan: return SearchEntity/ScanBehavior subtree
    return ClarifyOrFail("target_not_grounded")

  score only candidates whose metric support is sufficient for the relation
  if top candidates are materially ambiguous: return Clarify
  build relation-specific GoalRegionV1 and preferred-pose samples
  reject road/crossing/level constraints before planning
  return NavGoalV1 with evidence IDs and expiry
```

Grounding searches even when the target is not currently visible if fresh
semantic memory provides a re-observable hypothesis. It never invents a
coordinate solely from a language model.

### 6.2 Region and approach sampling

For a polygonal region, erode by footprint plus terminal clearance, sample the
remaining area, and score:

```text
J_goal(q) = w_path * estimated_path_cost(q)
          + w_heading * heading_change(q)
          + w_social * dynamic_exposure(q)
          + w_edge * inverse_clearance(q)
          + w_semantic * semantic_preference(q)
          + w_commit * goal_switch_penalty(q)
```

Hard occupancy, road keepouts, unsupported floors, excessive slope, and
crossing policy remove candidates rather than adding a large soft cost.
Dynamic exposure ranks already geometrically admissible candidates.

Commitments are temporary. Re-rank at a bounded rate when the current approach
is blocked for a dwell, the scene revision materially changes, the owner moves,
or expected cost improves beyond hysteresis. Never re-rank merely to bypass an
active hard stop.

### 6.3 Global and local planning

```text
admitted NavGoalV1
  → MAP global path (grid A*/Smac 2D baseline)
  → path validity and footprint corridor
  → ODOM local tracking (Parcel RPP first; Nav2 RPP/MPPI challenger)
  → exactly one smoother/shaper
  → final swept-footprint + TTC monitor
  → ControlManager
  → Unitree Sport
```

`grid_v1` stays the production and CI reference until an exclusive challenger
passes frozen matched-information comparisons. Nav2 is a sidecar behind a
narrow goal/state/feedback ABI, not a second simultaneous writer.

### 6.4 Forward-preferred tracking

For a lookahead point in the body frame `(x_L, y_L)`:

```text
L      = max(epsilon, hypot(x_L, y_L))
kappa  = 2 * y_L / L^2
e_yaw  = wrap(path_heading - robot_yaw)

if abs(e_yaw) > rotate_threshold
   and swept_rotation_is_clear
   and enough_rotation_clearance:
       vx = 0; vy = 0; wz = bounded_heading_controller(e_yaw)
else:
       v_curve = sqrt(a_lateral_max / max(abs(kappa), epsilon))
       v_clear = inverse_stop_envelope(directional_clearance)
       vx = min(v_requested, v_curve, v_clear, v_goal, v_state)
       wz = clamp(kappa * vx + k_heading * e_yaw)
       vy = lateral_assist_if_and_only_if(
           robot_supports_lateral,
           lateral_metric_coverage_fresh,
           swept_lateral_corridor_clear,
           improvement_exceeds_penalty,
       )
```

Lateral motion remains legal for manual strafing, tight local avoidance, and
formation correction. Its cost is higher than yaw-plus-forward travel for an
ordinary destination. A large heading error does not force rotation when the
full rotation footprint is less safe than a smooth arc.

### 6.5 Dynamic agents and TTC

People tracks are predicted over the local horizon with covariance. Hard TTC
uses conservative swept occupancy. Social costs influence speed and side
choice only after hard feasibility.

```text
for each candidate trajectory:
  for each time sample:
    expand robot footprint by pose/sensing uncertainty
    expand predicted person occupancy by track covariance
    if intersection or TTC below hard bound: reject/STOP
    accumulate proxemic exposure and pass-side cost for ranking
```

Empty or stale people tracks never dilute an obstacle cost and never trigger a
nearest-person identity substitution.

### 6.6 Controller failure and recovery

```text
if required evidence/state/transform/feedback unhealthy: HOLD
elif goal expired or revision changed: cancel plan + HOLD
elif path invalidated: bounded replan
elif blocked by dynamic actor: yield; re-rank admissible approach after dwell
elif no path: rescan or alternate semantic candidate
elif owner ambiguous/lost: HOLD; bounded SearchOwner; clarify/fail
elif recovery budget exhausted: HOLD + report typed failure
```

No recovery widens an envelope, enters a road, substitutes an identity, repeats
forever, or generates open-loop translation.

## 7. Relation-specific task algorithms

### 7.1 `NavigateTo(sidewalk)`

1. Detect/recall sidewalk polygons with metric support and evidence expiry.
2. Prefer a reachable same-side polygon; road polygons are keepouts.
3. Erode the sidewalk polygon by footprint plus clearance.
4. Sample approach points, rank path/clearance/social exposure, and commit with
   hysteresis.
5. Plan and execute through the common controller.
6. If traffic blocks the committed point, yield and boundedly re-rank another
   admissible inset; do not weaken person-stop.
7. Issue an agent exact-zero stop inside the region.
8. Declare success only after fresh metric polygon+clearance membership,
   healthy pose/transform, settled feedback for the dwell, and no active brake.

### 7.2 `NavigateTo(lamppost)` / `NavigateTo(shop)`

For an object, construct a reachable annulus or façade approach region rather
than navigating to its center. Intersect candidate poses with sidewalk/floor
free space and face the object/entrance when safe. “By the lamppost” uses a
configurable comfortable band whose external evaluation may accept a wider
vicinity; the product witness and evaluator are recorded separately. A shop
name may require slow open-vocabulary/OCR confirmation; ambiguous multiple
stores trigger clarification or a bounded scan.

### 7.3 `ApproachOwner`

1. Require the enrolled owner posterior to be confirmed over multiple frames.
2. Build a goal band around the owner, not the owner's body center.
3. Route the goal through the common planner.
4. Stop, verify identity, range band, fresh evidence, and settled feedback.
5. Release the base and terminate. Do not leave follow running.

### 7.4 `FollowFormation`

For confirmed owner pose `p_o`, heading unit vector `h_o`, and desired distance
`d`:

```text
behind:      g = p_o - d * h_o
side-left:   g = p_o + d * left(h_o)
side-right:  g = p_o - d * left(h_o)
direct:      choose nearest point in preferred owner annulus
```

Heading comes from a filtered owner orientation or sufficiently confident
velocity; otherwise use the direct annulus or ask for clarification rather than
guessing behind. Publish short-TTL SE(2) formation goals through the common
planner. Use prediction only within covariance and horizon limits. Identity
ambiguity, loss, stale formation, or missing geometry decelerates to HOLD and
enters bounded reacquisition. The skill remains active until Hold/cancel.

### 7.5 `OrbitOwner`

Infer a small companion-scale radius from the request, robot profile, owner
comfort band, and local clearance. “One time” means `2*pi` accumulated signed
angle about the same confirmed owner, not a town-scale loop.

```text
radius = clamp(requested_or_default, safe_min, locally_feasible_max)
sample tangent waypoints around owner in requested direction
route each short segment through common planner
accumulate unwrapped bearing only while owner ID is confirmed
replan for bounded owner drift; abort/HOLD on identity loss or blocked arc
succeed after angle >= 2*pi*N, terminal band, agent stop, settled witness
```

### 7.6 `MoveRelative(away_from_owner, five steps)`

Convert steps with the commissioned robot-profile step length and retain the
original unit in evidence. The direction is the normalized vector from the
owner to the robot at task admission. For a short distance, reverse is preferred
when the owner is in front, rear metric coverage is commissioned, and the swept
rear corridor is clear. Otherwise rotate toward the away vector and walk
forward. Success is projected displacement along the frozen away vector within
tolerance, not five control ticks.

### 7.7 Social reaction and low battery

Social models/rules emit `ReactionProposalV1`, never direct gestures. The
activity coordinator checks resource conflicts, task criticality,
interruptibility, posture stability, collision clearance, expiry, and
personality policy.

```text
if emergency or safety correction: suppress/drop reaction
elif base is in critical/non-interruptible task phase: defer until checkpoint
elif proposal expires before admission: drop
elif gesture needs base/posture and lease unavailable: use voice-only response
else execute admitted catalog gesture, then verify activity completion
```

Low battery is system state, not inferred affect:

- LOW: announce once; schedule sit/crouch at the next safe checkpoint if it
  does not abandon a safety-critical task.
- CRITICAL while moving: exact-zero safe stop; settle; sit/lie only if posture
  conditions and terrain are valid; otherwise remain stable and announce.
- Charging/recovery cancels stale low-battery reaction proposals by revision.

## 8. Task lifecycle and interruption

### State machine

```text
QUEUED
  → WAITING_PRECONDITION → WAITING_RESOURCE → RUNNING
  → WAITING_CHECKPOINT → SUSPENDED → RUNNING
  → RECOVERING → RUNNING
  → VERIFYING → SUCCEEDED
  → FAILED | CANCELLED | TIMED_OUT
```

`SUSPENDED` is not an outcome. Resume is a compare-and-swap transaction over
`{task_id, revision, step_id, base lease, channel, goal_id}`. If any member no
longer matches, resume fails to HOLD and requires re-dispatch/re-grounding.

### Priority and preemption

```text
Emergency stop             immediate, accepted from any source
Final safety/system fault  immediate
Authenticated manual       immediate below safety; cancels/suspends base task
Safety correction          immediate/checkpoint by hazard policy
Explicit user action       declared checkpoint policy
Active persistent task     retains base unless validly preempted
Conversation/voice         normally overlaps without base
Social reaction            defer/drop; never steals a critical base phase
```

Corrections create a higher plan revision. Every older goal, proposal, and
controller plan is invalidated before the replacement can move.

## 9. Independent terminal verification

Planning and execution must not grade themselves. The verifier consumes fresh
sensor/state evidence and controller feedback for the same task revision.

```text
verify_terminal(spec, snapshot, nav_feedback):
  require IDs match task/revision/step/goal
  require fresh evidence join and healthy transforms
  require relation predicate:
    inside  → footprint-in-eroded-polygon
    near    → distance in configured band
    next_to → near + admissible side/region constraint
    orbit   → accumulated angle/revolution + owner identity continuity
    relative→ projected displacement and direction tolerance
    approach→ owner identity + stand-off band
  require agent-issued exact-zero terminal command
  require fresh feedback reports settled for dwell interval
  require no active collision/person/TTC brake
  emit immutable WitnessBundleV1 or remain VERIFYING/HOLD
```

Being stopped by an obstacle inside a goal region is not task success. An eval
adapter cannot weaken the product witness; it may apply an additional external
scoring region and must report disagreements.

## 10. Observability contract

Every user turn/task emits trace spans for:

- query-end → first logged response;
- query-end → first spoken audio;
- query-end → first reasoning result;
- final ASR, intent parsing, task compile/validate/admit;
- grounding, perception join, global plan, first controller command;
- each local-control and safety decision;
- model request/queue/inference/validation when present;
- stop request → HAL dispatch → fresh settled feedback;
- task completion and terminal-witness construction.

Each record carries `session/turn/task/revision/step/goal/plan/command` IDs,
model/config/artifact revisions, evidence IDs, and monotonic timestamps. The
latency dashboard can summarize these spans without becoming a control
dependency.

## 11. Evaluation and promotion

All designs run the same product semantics and shared safety tests:

1. unit/property tests for schemas, freshness, geometry, task transitions, and
   exact-zero ordering;
2. deterministic headless instruction scenarios for sidewalk, lamppost, shop,
   relative steps, orbit, approach, follow, pause/resume/cancel, reactions, and
   low battery;
3. faults: stale/missing LiDAR/camera metric channel, pose LOST, transform jump,
   delayed feedback, planner crash, model OOM, task revision race, owner
   distractor/occlusion, crossing replay, and manual preemption;
4. dynamic city/crowd scenarios with success, SPL/path efficiency, time,
   clearance distribution, TTC, jerk, lateral-motion share, replans,
   oscillation, identity continuity, false success, and p50/p95/p99 latency;
5. matched BARN/controller and role-specific external adapters, labeled
   `external_proxy` unless official protocol requirements are met;
6. Go2 physics and delay harness, then supervised HIL only after ODD/safety
   review and commissioning.

Promotion requires a frozen source/config/scenario/evaluator digest, identical
episodes and information where a direct comparison is claimed, paired
statistics, no hard violation, no task-family or p99 regression beyond its
predeclared margin, deterministic failure degradation, and a separate physical
authorization. Zero observed collisions is reported with exposure/confidence
bounds, never as a safety certificate.
