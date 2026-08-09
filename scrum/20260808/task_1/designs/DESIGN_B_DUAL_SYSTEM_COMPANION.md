# Design B: Dual-System Semantic Companion

**Status:** proposed full-stack architecture; implementation is gated by the P0 corrections below<br>
**Date:** 2026-08-08<br>
**Scope:** Parcel simulator and future Unitree deployment<br>
**Decision owner:** robotics/navigation review
## 0. Decision summary

Parcel should use two deliberately unequal systems:

1. a fast, deterministic, continuously running robotics system that owns task state, metric grounding, navigation, safety, control, and completion; and
2. asynchronous language/vision/navigation models that may propose interpretations, semantic goals, plans, dialogue, or bounded short-horizon motion candidates.
The second system never owns a motor, a resource lease, a crossing authorization, an identity decision, or a success transition. Its outputs become useful only after a trusted compiler and current-state validator admit them into the first system.
This is the recommended architecture for a companion dog because conversation and open-world instruction interpretation benefit from foundation models, while physical authority needs bounded latency, explicit state, geometric evidence, and deterministic failure behavior. The design keeps Unitree Sport as the gait and balance controller. Parcel supplies semantic behavior, metric navigation, and velocity intent; it does not replace whole-body stabilization in this phase.
The critical design rule is:
> Models propose meaning; trusted software grants authority; independent metric
> evidence controls motion and proves outcomes.
No evaluation-score improvement may weaken that rule.
## 1. Thesis, goals, and non-goals

### 1.1 Thesis

The companion loop should feel unified to the owner but remain split internally:

- the conversational lane acknowledges, asks, explains, and expresses personality;
- the task lane interprets commands into typed requests and revisions;
- the executive decides which task is active and which resources it owns;
- the navigation lane grounds semantic goals and produces safe base intent;
- the final safety lane can only reduce or zero that intent;
- Unitree Sport converts the admitted body velocity into stable locomotion.
This permits speech and planning to overlap without allowing a slow or stale model response to mutate a newer physical task.
### 1.2 Goals

- Follow the enrolled owner in a persistent, socially acceptable formation.
- Approach the owner as a terminal task distinct from follow.
- Ground open-world commands such as “go to the sidewalk” or “wait by the lamp.”
- Execute local relational commands such as orbit, step away, stand beside, and face.
- React socially without interrupting a safety-critical or higher-value base task.
- Navigate around static and moving obstacles using camera/LiDAR metric evidence.
- Preserve responsive conversation while physical work continues.
- Support deterministic manual control through the same safety boundary.
- Make every accepted, rejected, superseded, and completed decision observable.
- Permit optional learned planners to compete in shadow mode without changing authority.
- Retain an implementation seam for a future Parcel controller below the velocity API.
### 1.3 Non-goals

- Training a general-purpose end-to-end locomotion policy in the current phase.
- Replacing Unitree Sport gait, balance, fall recovery, or joint-level control.
- Giving an LLM/VLM raw motor or Unitree SDK access.
- Treating RGB labels, map data, or language confidence as collision-free geometry.
- Treating a transcript, speaker resemblance, or UI text as crossing authorization.
- Claiming task success from elapsed time, model narration, or controller command alone.
- Optimizing benchmark score by changing the dog embodiment or benchmark semantics.
- Solving every city ODD before bounded indoor/private-campus ODDs pass evidence gates.
## 2. Mandatory corrections before model competition

The following are release blockers, not backlog refinements.
### P0-A — hard stop after all shaping

The final safety monitor reads the shaped command, checks current commissioned metric geometry and feedback, and writes the exact command sent to `ControlManager` in the same dispatch. On hard intervention it writes `(0, 0, 0)` and resets every shaper/smoother. No cached nonzero command may survive the stop.
### P0-B — stale data fails closed

Missing, stale, malformed, or frame-inconsistent required LiDAR, pose, transform, or controller feedback forbids translation. The response is HOLD or latched STOP according to severity. Stub geometry is allowed only in an explicitly labeled simulator fixture; it must never silently satisfy a physical sensor requirement.
### P0-C — atomic lifecycle identity

Every dispatch, feedback item, proposal, terminal witness, and cancellation is keyed by:
```text
{task_id, plan_revision, step_id, channel_epoch}
```
Revision replacement increments `channel_epoch`, revokes old leases, flushes old model buffers, and publishes the new tuple atomically. Results with any mismatched field are recorded as stale and have no behavioral effect.
### P0-D — executable recovery

Recovery is bounded, stateful, and keyed to the same revision. Each step has explicit attempt count, retry deadline, invariant checks, and a finite recovery ladder. The current compiler behavior that collapses effective retries to one must be corrected only after validator tests prove bounds cannot be widened by model output.
### P0-F — freeze typed boundaries

Freeze and version the schemas in section 7 before integrating additional models. Unknown fields are rejected at authority boundaries. Additive fields require a minor version and conservative defaults; semantic changes require a major version and adapter.
### P0-G — split approach from follow

`ApproachOwner` is a terminal skill: reach an admissible owner-relative goal, stop, verify, release base. `FollowFormation` is persistent and continually refreshes a short TTL goal. The current local `come` sketch must stop compiling to `FollowFormation`.
### P0-H — correct person stopping dimensions

Do not add dimensionless scale factors to meters. A person constraint must use either a measured distance allowance or a dimensionally valid closing allowance:
```text
required_person_clearance_m = max(
    social_zone_m,
    braking_distance_m(v) + max(0, closing_speed_mps) * person_latency_s
)
```
Use exactly one footprint convention throughout planning, safety, and evaluation.
## 3. Complete component architecture

```text
 microphones / text UI / manual UI / camera / LiDAR / odometry / battery / Sport state
                  |               |                         |
                  v               v                         v
       +----------------+  +--------------------+   +-------------------+
       | Audio frontend |  | Metric perception  |   | State/health mux  |
       | VAD/ASR/turns  |  | tracks, depth, TF  |   | pose, power, gait |
       +-------+--------+  +----------+---------+   +---------+---------+
               |                      |                       |
               v                      +-----------+-----------+
       +------------------+                       v
       | Authenticated    |             +---------------------+
       | interaction bus  |------------>| Snapshot assembler  |
       +---+----------+---+             | immutable, stamped  |
           |          |                 +----------+----------+
           |          |                            |
     literal/common   | open-world                 |
     deterministic    v                            |
           |   +---------------------+              |
           |   | Async model broker  |<-------------+
           |   | intent/LLM/VLM/nav  |
           |   +----------+----------+
           |              | typed proposals only
           v              v
       +--------------------------+       +-----------------------+
       | Trusted request compiler |<----->| Conversation manager  |
       | auth, units, bounds, IDs  |       | streaming speech only |
       +-------------+------------+       +-----------------------+
                     |
                     v
       +--------------------------+
       | Task/revision executive  |
       | leases, priority, policy |
       +----+---------+-----------+
            |         |
      semantic skill  | social proposal
            |         v
            |   +--------------------+
            |   | Reaction arbiter   |
            |   | attention/audio/   |
            |   | bounded expression |
            |   +--------------------+
            v
       +--------------------------+      +-------------------------+
       | Goal grounding + memory  |<---->| optional proposal svc   |
       | camera/LiDAR metric gate |      | VLM / learned navigator |
       +-------------+------------+      +-------------------------+
                     |
                     v
       +--------------------------+
       | Common navigation server |
       | global/local/formation   |
       | grid_v1 baseline         |
       +-------------+------------+
                     |
                     v
       +--------------------------+
       | Command owner + shaper   |<----- manual semantic/twist request
       | one base writer          |
       +-------------+------------+
                     | shaped velocity
                     v
       +--------------------------+
       | Independent final metric |
       | safety monitor           |
       | can tighten or zero only |
       +-------------+------------+
                     | final velocity
                     v
       +--------------------------+
       | ControlManager           |
       | watchdog/readiness       |
       +-------------+------------+
                     |
                     v
       +--------------------------+
       | Unitree Sport controller |
       | gait/balance/joint loops |
       +--------------------------+
```
The model broker, conversation manager, and slow semantic perception are out of process. Control, safety, state estimation, lifecycle authority, and hardware I/O remain in the trusted runtime. IPC queues are bounded and latest-only where data is supersedable.
## 4. Why this alternative

### 4.1 Internal comparison

| Property | Classical-only stack | **Dual-system companion** | Predictive learned hierarchy |
|---|---|---|---|
| Physical authority | deterministic | **deterministic** | learned output needs strong shield |
| Open-world language | grammar/ontology limited | **foundation-model proposal** | foundation-model proposal |
| Conversation | separate and shallow | **native asynchronous lane** | native asynchronous lane |
| Goal grounding | engineered detectors | **engineered metric gate + VLM hints** | learned spatial representations |
| Dynamic motion | classical local planner | **classical baseline; learned challenger** | predictive policy primary |
| Failure diagnosis | strong | **strong at authority boundary** | harder attribution |
| Compute pressure | lowest | **degrades by dropping optional work** | highest and deadline-sensitive |
| Near-term implementation risk | low | **moderate** | high |
| Long-term model leverage | limited | **high without authority transfer** | high |
The classical alternative is the reference for safety, latency, and regressions, but it cannot interpret enough open-world requests or converse naturally. The predictive alternative is a valid later challenger for crowded local navigation, but making it the primary stack now couples model availability to safe motion and increases validation surface before Parcel has trustworthy witnesses. Dual-system preserves the classical reference while allowing model improvements to enter through narrow contracts.
### 4.2 Falsifiable decision

Replace this recommendation if controlled evaluation shows all of the following:

- a simpler classical-only system reaches the required semantic-task success envelope;
- its clarification and grounding burden is acceptable to owners;
- foundation-model proposals do not produce a statistically meaningful task benefit;
- removing the async system materially improves measured reliability or latency.
Conversely, do not promote a predictive planner merely because it improves path score. It must also pass safety, identity, revision-isolation, terminal-witness, latency-tail, and out-of-distribution gates.
## 5. Timing, rates, and deadlines

All numbers below are initial engineering budgets, not measured capability claims. Each must become a configuration parameter, be measured on target hardware, and be frozen by the safety case. A missed mandatory deadline fails closed.
| Loop or event | Initial rate/budget | Deadline consequence |
|---|---:|---|
| Unitree Sport internal control | vendor-owned | SDK health loss -> exact zero / vendor stop |
| final metric safety monitor | 50–100 Hz | one missed period -> exact zero and latch degraded |
| ControlManager dispatch/watchdog | 50 Hz | timeout -> exact zero; require readiness recovery |
| local planner/controller | 20–50 Hz | retain no stale command; HOLD until fresh result |
| metric obstacle/tracking fusion | 20–50 Hz | freshness breach -> no translation |
| owner tracking | 15–30 Hz | TTL breach -> slow, then HOLD/search |
| task executive supervision | 10 Hz + events | timeout -> bounded recovery or fail |
| reaction/dialogue influence | 10 Hz | drop reaction; never delay base or safety |
| fast semantic perception | 10–30 Hz | keep last typed fact only within its TTL |
| slow open-vocabulary/OCR | 0.2–2 Hz | no motion dependency; result may be discarded |
| deterministic text routing | target <= 50 ms | acknowledge inability; no model-created authority |
| local request compile/validate | target <= 100 ms | reject request; retain current safe task |
| conversational first useful output | target <= 2 s ceiling | filler/brief status; physical task independent |
| async task-model proposal | per-request deadline <= 2 s initially | expire proposal and clarify/HOLD |
| bounded nav-model proposal | service-specific, measured | expire by `valid_until`; classical stays reference |
Deadline ordering is strict:
```text
safety freshness < control watchdog < local-plan validity
                 < semantic-goal TTL < task/model deadline
```
A longer-lived artifact may not legalize a shorter-lived dependency. For example, a fresh language goal cannot make a stale transform usable.
## 6. Processes, concurrency, and ownership

### 6.1 Processes

- `parcel_trusted_runtime`: executive, resource manager, grounding gate, navigation reference, safety monitor, ControlManager, Unitree adapter, audit ledger.
- `parcel_perception`: calibrated camera/LiDAR ingestion, metric fusion, semantic facts.
- `parcel_voice`: audio I/O, VAD, ASR, TTS, turn coordination, barge-in.
- `parcel_model_broker`: LLM/VLM/intent services with no hardware device access.
- `parcel_nav_challenger`: optional learned proposal service, sandboxed and shadow-first.
- `parcel_ui`: simulator/manual panel/latency dashboard, no direct hardware path.
Model processes receive read-only immutable snapshots, cannot open Sport/serial/CAN devices, and have bounded CPU/GPU/memory quotas. If compute is constrained, disable in this order: speculative dialogue, open-vocabulary refresh, VLM grounding, navigation challenger. Metric perception, safety, control, and state estimation are never shed.
### 6.2 Resource namespaces

```text
base             exclusive motion authority
posture          bounded whole-body pose/trajectory request
attention        head/gaze target
expression_audio nonverbal sound
voice            spoken response
camera_semantics schedulable slow inference
gpu_slow         low-priority model compute
```
`base` has exactly one writer. Follow, approach, orbit, navigate, relative move, manual twist, and collision recovery all acquire it through the executive. A social reaction does not acquire `base`. A reaction requiring base or posture becomes an explicit gesture task and is deferred or rejected by policy.
### 6.3 Queue rules

- Safety and lifecycle events use lossless bounded priority queues.
- Pose/track/snapshot streams are latest-only with sequence numbers.
- Model proposal queues are latest-only per `{task, revision, proposal_role}`.
- Dialogue tokens are ordered by voice turn and epoch; barge-in advances the epoch.
- Queue overflow in an authority path is a health fault and causes HOLD.
- Queue overflow in an optional proposal path drops oldest proposals and increments a diagnostic counter.
- No callback on the control thread performs network I/O, model inference, TTS, or sleep.
## 7. Versioned interfaces

These are implementation-oriented projections of the minimum normative fields
in [`../SHARED_FOUNDATION.md`](../SHARED_FOUNDATION.md). Phase 0 merges them
into one canonical serialization; they are not permission to omit or rename a
shared field. All authority-bearing messages use canonical serialization for
hashing, finite numeric validation, monotonic timestamps for local deadlines,
and an origin/authentication envelope. Wall-clock time is informational only.
### 7.1 `EvidenceEnvelopeV1`

```yaml
schema: parcel.evidence.v1
event_id: uuid
source_id: string
source_kind: camera|lidar|odometry|controller|audio|ui|map_advisory
sequence: uint64
captured_monotonic_ns: uint64
published_monotonic_ns: uint64
frame_id: string|null
calibration_id: string|null
payload_sha256: hex64
quality: {health: healthy|degraded|invalid, confidence: float|null}
```
An envelope does not make evidence metric. Metric authority additionally requires an approved source kind, commissioned calibration, transform chain, covariance/quality gate, and freshness check.
### 7.2 `PoseEstimateV1`

```yaml
schema: parcel.pose_estimate.v1
evidence: EvidenceEnvelopeV1
continuous_frame: odom
pose_se2: {x_m: float, y_m: float, yaw_rad: float}
velocity_body: {vx_mps: float, vy_mps: float, yaw_rate_rps: float}
covariance: [float x 36]
map_to_odom_revision: uint64
transform_health: healthy|degraded|invalid
```
Local control uses continuous `odom`; map correction is represented separately and may not teleport an active local trajectory.
### 7.3 `PerceptionSnapshotV1`

```yaml
schema: parcel.perception_snapshot.v1
snapshot_id: uuid
created_monotonic_ns: uint64
pose: PoseEstimateV1
lidar_scan_ref: EvidenceEnvelopeV1
metric_obstacles: [MetricObstacleV1]
dynamic_tracks: [DynamicTrackV1]
owner_track: OwnerTrackV1|null
semantic_regions: [SemanticRegionV1]
landmarks: [SemanticLandmarkV1]
sensor_health: {camera: enum, lidar: enum, transforms: enum}
```
Semantic regions and landmarks carry source evidence and confidence, but a goal becomes executable only after projection/intersection with metric free space.
### 7.4 `SpeakerAuthorizationV1`

```yaml
schema: parcel.speaker_authorization.v1
interaction_event_id: uuid
channel: enrolled_voice|paired_ui|local_operator|unknown
principal_id: string|null
authentication: verified|unverified|failed
replay_risk: low|unknown|high
verified_monotonic_ns: uint64
valid_until_monotonic_ns: uint64
allowed_authorization_classes: [ordinary_motion|crossing|estop_clear|configuration]
```
Speaker identity and visual owner identity are separate posteriors. Neither may silently substitute for the other.
### 7.5 `TaskRequestV1`

```yaml
schema: parcel.task_request.v1
request_id: uuid
turn_id: string
transcript_sha256: hex64
speech_act: command|question|correction|cancel|social|information
task_kind: navigate|approach_owner|follow_formation|orbit_owner|move_relative|
           hold|gesture|vocalize|clarify|compound
semantic_arguments: object
quantities: [TypedQuantityV1]  # source text/value/unit; normalized SI optional
constraints: [TypedConstraintV1]
candidate_referents: [ReferentV1]
ambiguity: none|resolvable|requires_clarification
target_task_id: string|null
urgency: normal|urgent|emergency
authorization: SpeakerAuthorizationV1
snapshot_id: uuid
created_monotonic_ns: uint64
valid_until_monotonic_ns: uint64
producer: deterministic_router|task_model
producer_version: string
```
The model may produce a draft excluding identity, authorization, task IDs, timestamps, and safety bounds. The trusted compiler fills those fields and rejects semantic values outside the admitted ontology. Embodiment-relative units such as `step` remain unexpanded until the trusted skill adapter reads the versioned robot profile.
### 7.6 `TaskRevisionV1`

```yaml
schema: parcel.task_revision.v1
task_id: string
plan_revision: uint32
step_id: string
channel_epoch: uint64
request_id: uuid
state: queued|running|waiting_checkpoint|recovering|suspended|succeeded|failed|cancelled
task_class: safety|manual|explicit_action|background|social|voice
resources: [resource]
invariants: [InvariantV1]
step_deadline_monotonic_ns: uint64
attempt: uint8
max_attempts: uint8
plan_sha256: hex64
```
Only the executive authors this message.
### 7.7 Goal and proposal contracts

```yaml
schema: parcel.goal_region.v1
goal_id: uuid
task_key: {task_id, plan_revision, step_id, channel_epoch}
frame_id: map|odom
polygon_xy_m: [[float, float]]
preferred_pose_se2: {x_m: float, y_m: float, yaw_rad: float}|null
relation: inside|near|behind|approach|orbit|relative
clearance_min_m: float
semantic_evidence_ids: [uuid]
metric_evidence_ids: [uuid]
created_monotonic_ns: uint64
valid_until_monotonic_ns: uint64
grounding_state: candidate|metric_admitted|invalid
```
```yaml
schema: parcel.nav_proposal.v1
proposal_id: uuid
task_key: {task_id, plan_revision, step_id, channel_epoch}
proposal_role: semantic_goal|global_route|local_se2_trajectory
observation_snapshot_id: uuid
frame_id: map|odom
waypoints_se2: [{x_m: float, y_m: float, yaw_rad: float, t_from_start_s: float}]
goal_region_id: uuid
assumptions: [string]
producer: string
model_artifact_sha256: hex64
created_monotonic_ns: uint64
valid_until_monotonic_ns: uint64
```
`NavProposalV1` has no raw actuator fields. Even a local trajectory is sampled only by the trusted controller after kinematic, footprint, transform, task-key, freshness, authorization, and collision checks.
### 7.8 `SkillFeedbackV1` and `TerminalWitnessBundleV1`

```yaml
schema: parcel.skill_feedback.v1
task_key: {task_id, plan_revision, step_id, channel_epoch}
status: in_progress|succeeded|failed|cancelled
checkpoint: bool
feedback_code: enum
verified_facts: [VerifiedFactV1]
evidence_ids: [uuid]
reported_monotonic_ns: uint64
```
```yaml
schema: parcel.terminal_witness_bundle.v1
task_key: {task_id, plan_revision, step_id, channel_epoch}
goal_region_id: uuid
pose_evidence_id: uuid
geometry_evidence_ids: [uuid]
inside_goal_region: bool
clearance_satisfied: bool
relation_satisfied: bool
agent_command_exact_zero: bool
measured_motion_settled: bool
active_brake: none|comfort|hard
dwell_started_monotonic_ns: uint64
dwell_completed_monotonic_ns: uint64
transform_health: healthy
```
Success requires a complete bundle. An absent field is failure to prove, not `true`.
### 7.9 `CrossingAuthorizationV1`

```yaml
schema: parcel.crossing_authorization.v1
authorization_id: uuid
interaction_event_id: uuid
principal_id: string
task_id: string
plan_revision: uint32
crossing_candidate_id: uuid
curb_stop_evidence_id: uuid
nonce: hex
decision: authorize_once|deny
issued_monotonic_ns: uint64
valid_until_monotonic_ns: uint64
consumed_monotonic_ns: uint64|null
signature_or_session_mac: string
```
This replaces phrase matching. It is single-use and cannot survive task revision, curb departure, candidate change, expiry, replay, or principal loss.
### 7.10 `BatteryStateV1`

```yaml
schema: parcel.battery_state.v1
evidence: EvidenceEnvelopeV1
percent: float|null
voltage_v: float|null
current_a: float|null
temperature_c: float|null
state: normal|low|critical|shutdown_imminent|unknown
remaining_energy_estimate_wh: float|null
telemetry_health: healthy|degraded|invalid
```
The physical runtime must not label simulated battery evidence as physical telemetry.
### 7.11 Compatibility and rejection

Each consumer declares supported major/minor versions. Rejections use stable reason codes such as `schema_unknown`, `task_key_stale`, `ttl_expired`, `snapshot_stale`, `transform_invalid`, `metric_evidence_missing`, `identity_ambiguous`, `authorization_missing`, `kinematic_invalid`, and `resource_not_owned`. Rejection details are logged but cannot be used by a model to relax a gate.
## 8. Core algorithms

### 8.1 Intent to task

```python
def on_final_interaction(event):
    auth = authenticate_channel(event)              # system-owned
    snapshot = snapshots.capture_immutable()
    if literal_emergency_stop(event.text):
        safety.latch_hard_stop(event.id)
        executive.cancel_all(source="explicit_stop")
        conversation.say_minimal("Stopping.")
        return
    local = deterministic_router.parse(event, auth, snapshot)
    conversation.submit(event, snapshot)            # may stream independently
    if local.is_complete:
        draft = local.task_request_draft
    elif local.requires_clarification:
        conversation.ask(local.question)
        return
    else:
        model_broker.submit_latest(
            key=event.turn_id,
            input=redacted_task_context(event, snapshot),
            deadline=TASK_MODEL_DEADLINE,
        )
        conversation.acknowledge_pending_without_claiming_completion()
        return
    admit_task_draft(draft, event, auth, snapshot)
def on_task_model_result(result):
    pending = pending_turns.get(result.turn_id)
    if pending is None or result.expired:
        audit.reject(result, "turn_stale")
        return
    current = snapshots.capture_immutable()
    draft = strict_schema_parse(result)
    admit_task_draft(draft, pending.event, pending.auth, current)
def admit_task_draft(draft, event, auth, snapshot):
    request = trusted_compiler.compile(draft, event, auth, snapshot)
    validator.validate_request(request, snapshot)
    plan = deterministic_skill_expander.expand(request, snapshot)
    validator.validate_plan(plan, snapshot)
    executive.submit_or_replace_atomically(plan)
```
Common intents remain deterministic: stop, hold, come/approach, follow, bounded relative motion, bounded orbit, known poses, and explicit cancel/correction forms. The model is used for ambiguity and open-world composition, not for obvious commands.
### 8.2 Ground semantic goals into metric goal regions

```python
def ground_goal(task_key, referent_query, relation, snapshot):
    require_current_task_key(task_key)
    require_fresh(snapshot.pose, snapshot.lidar_scan_ref)
    require_healthy_transform(snapshot.pose)
    facts = semantic_memory.query(referent_query, ttl_by_fact_type)
    candidates = associate_to_current_snapshot(facts, snapshot)
    candidates = [c for c in candidates if c.semantic_confidence >= threshold(c.kind)]
    if not candidates:
        return NEED_RESCAN_OR_CLARIFICATION
    regions = []
    for candidate in candidates:
        metric_support = project_or_associate_metric_geometry(candidate, snapshot)
        if not metric_support.valid:
            continue
        region = construct_relation_region(candidate, relation, metric_support)
        region = intersect(region, commissioned_free_space(snapshot))
        region = subtract(region, static_inflation(snapshot))
        region = subtract(region, dynamic_prediction_envelopes(snapshot))
        region = subtract(region, forbidden_semantic_masks(snapshot))
        if feasible(region, robot_footprint, required_clearance):
            regions.append(score_goal_region(region, candidate, snapshot))
    if not regions:
        return GROUNDING_FAILED_SAFE
    if ambiguous_top_pair(regions):
        return NEED_CLARIFICATION
    return commit_best_region_with_ttl(regions, task_key)
```
Examples:

- “sidewalk” yields an inside-polygon goal eroded by footprint and clearance, not a semantic centroid.
- “by the lamppost” yields a ring/sector near the pole, intersected with non-road free space; success is within the admitted vicinity, not one coordinate.
- “store” first resolves a storefront/entrance candidate, then a reachable waiting region; advisory map data may suggest candidates but may not assert free space.
While safely stopped near a goal, the grounder may re-rank candidates at a bounded rate with hysteresis. It may not change the active goal while moving unless the executive commits a revision.
### 8.3 Navigation and command dispatch

```python
def control_tick(now):
    state = state_mux.read_current(now)
    health = mandatory_health_gate(state)
    if not health.translation_allowed:
        return dispatch_exact_zero_and_reset(reason=health.reason)
    lease = resource_manager.current("base")
    if lease is None:
        raw = ZERO
    else:
        raw = active_base_skill(lease).tick(state, now)
    raw = enforce_kinematics_and_preferred_motion(raw)
    # Lateral velocity exists, but normal goal travel favors yaw-align then forward.
    raw.vy *= LATERAL_PENALTY
    shaped = single_command_shaper.step(raw, state, now)
    verdict = independent_metric_monitor.evaluate(
        shaped_command=shaped,
        pose=state.pose,
        lidar=state.lidar,
        depth=state.commissioned_metric_camera_depth,
        tracks=state.dynamic_tracks,
        controller_feedback=state.controller,
        swept_footprint=robot_footprint,
    )
    final = verdict.tighten_or_zero(shaped)
    if verdict.stop_class == HARD:
        final = ZERO
        single_command_shaper.reset()
    assert magnitude(final) <= magnitude(shaped) + EPSILON
    control_manager.dispatch(final, now)
```
`grid_v1` remains the production reference. A Nav2/RPP adapter is the first structured challenger; MPPI or a learned predictive local planner is evaluated later. Exactly one velocity smoother is active. Planner switching occurs only while stopped and through a revision-bound executive transition.
### 8.4 Owner approach, follow, and orbit

Owner tracking maintains an enrolled multi-view identity posterior rather than choosing the nearest person. Association requires M-of-N agreement across admitted visual cues and motion continuity. Ambiguity is explicit.
```python
def owner_relation_tick(skill, owner_track, snapshot):
    if owner_track is None or owner_track.expired:
        return slow_then_hold_and_request(SearchOwner)
    if owner_track.identity_state != "enrolled_verified":
        return HOLD_IDENTITY_AMBIGUOUS
    if skill.kind == "ApproachOwner":
        goal = owner_approach_region(owner_track, standoff_m=skill.distance_m)
        nav.update_short_ttl_goal(goal)
        if terminal_relation_witness(goal, snapshot):
            nav.stop_exactly()
            return SUCCEEDED_RELEASE_BASE
    if skill.kind == "FollowFormation":
        goal = formation_region(owner_track, relation=skill.relation)
        nav.update_short_ttl_goal(goal)
        return IN_PROGRESS_CHECKPOINT_WHEN_SETTLED
    if skill.kind == "OrbitOwner":
        path = collision_checked_local_orbit(owner_track, skill.radius_m, skill.turns)
        progress = unwrap_bearing_progress(path, owner_track)
        return succeed_only_if(progress >= requested_angle and terminal_witness())
```
Follow is persistent until cancelled or revised. It does not succeed merely because the dog is momentarily in formation. Orbit radius is bounded to a local companion-scale range by the trusted compiler and expands only if geometry requires an admissible detour; it never becomes a town-scale circle.
### 8.5 Social reactions

```python
def propose_reaction(cue, dialogue_state, current_task):
    proposal = reaction_policy_or_model(cue, dialogue_state)
    proposal = schema_validate_and_catalog_resolve(proposal)
    if proposal.requires_base:
        return convert_to_explicit_gesture_task(proposal)
    return reaction_arbiter.consider(proposal)
def reaction_arbiter_consider(p):
    if critical_phase or emergency_stop or battery_critical:
        return VETO
    if p.resources intersects held_exclusive_resources:
        return DEFER_UNTIL_IDLE if p.valid_until > expected_checkpoint else DROP
    if cooldown_or_habituation_rejects(p):
        return DROP
    lease(p.resources, bounded_duration=p.duration)
    return EXECUTE
```
“User is sad, bow” and “user is happy, stretch” are cues, not unconditional commands. The response can be voice-only, gaze, audio, or a bounded catalog gesture. During a road crossing, collision recovery, terminal verification, critical battery procedure, or noninterruptible checkpoint, base/posture reactions are vetoed. Conversation may still offer a brief empathetic response if voice does not conflict.
### 8.6 Interruption, correction, and preemption

Priority is deterministic:
```text
emergency/hard safety > physical recovery > authenticated manual > explicit owner task
> background autonomy > social gesture > conversational expression
```
```python
def apply_event(event):
    with lifecycle_transaction():
        active = executive.active_revision()
        policy = interrupt_policy(event, active)
        if policy == OVERLAP_VOICE_ONLY:
            conversation.accept(event)
        elif policy == CANCEL_NOW:
            stop_active_channel(active)
            revoke_leases(active)
            advance_channel_epoch(active.channel)
            flush_old_proposals(active.key)
            mark_cancelled(active)
        elif policy == SUSPEND_AT_CHECKPOINT:
            mark_pending_interrupt(active, event)
        elif policy == REPLACE:
            require_target_task_match(event, active)
            stage_validated_revision(event)
            activate_only_at_admitted_boundary(active)
        elif policy == DEFER:
            queue_with_ttl(event)
```
Corrections must identify the active task and increment its revision. A late response from the previous revision is inert. Resume either restores a serialized controller intent and rebinds the same step, or cold-dispatches once; it never does both.
### 8.7 Bounded recovery

Each skill declares a code-indexed recovery table owned by trusted configuration:
```text
NO_PATH             -> rescan -> alternate candidate -> fail/clarify
OWNER_TEMP_LOST     -> stop -> bounded search -> reacquire verified owner -> resume
IDENTITY_AMBIGUOUS  -> stop -> request owner disambiguation -> fail on timeout
DYNAMIC_BLOCKED     -> wait with deadline -> replan -> alternate region -> fail
LOCALIZATION_BAD    -> exact zero -> relocalize -> operator assistance
HARD_SAFETY_BRAKE   -> exact zero -> clear evidence -> replan; never blind retry
MODEL_UNAVAILABLE   -> existing admitted classical goal only, else HOLD/clarify
```
```python
def recover(task_key, feedback):
    require_current_task_key(task_key)
    action = recovery_table.lookup(feedback.code, attempt)
    if action is None or attempt >= max_attempts or now > step_deadline:
        return fail_task(feedback.code)
    require_invariants_still_true(task_key)
    executive.enter_recovering(task_key, action)
    dispatch_system_recovery(action, bounded_deadline(action))
```
No recovery action invokes an LLM on the control thread. A model may asynchronously propose an alternate semantic candidate, which enters as a new revision after validation.
### 8.8 Terminal verification

```python
def verify_terminal(task_key, goal, now):
    require_current_task_key(task_key)
    evidence = capture_independent_metric_evidence(now)
    if not evidence.pose_fresh or not evidence.geometry_fresh:
        return NOT_PROVEN
    if evidence.transform_health != HEALTHY:
        return NOT_PROVEN
    if evidence.active_brake != NONE:
        return NOT_PROVEN
    if not inside_or_related(goal, evidence):
        reset_dwell(task_key); return NOT_PROVEN
    if not clearance_satisfied(goal, evidence):
        reset_dwell(task_key); return NOT_PROVEN
    command_owner.issue_exact_zero(task_key)
    if not controller_feedback_settled(evidence):
        reset_dwell(task_key); return NOT_PROVEN
    if not dwell_complete_with_continuous_fresh_evidence(task_key, now):
        return IN_PROGRESS
    return witnessed_success_bundle(task_key, goal, evidence)
```
The dog may say “I’m there” only after the executive accepts this witness. Before that it may say “I’m heading there” or “I’m checking the spot.”
### 8.9 Model failure and degradation

```python
def on_model_fault(role, task_key, reason):
    isolate_and_restart_service(role)
    audit.model_fault(role, task_key, reason)
    if role == "conversation":
        use_brief_deterministic_status(); physical_task_continues()
    elif preexisting_classical_goal_is_fresh_authorized_and_same_revision(task_key):
        continue_reference_navigation_without_goal_change()
    else:
        executive.hold(task_key, reason="model_unavailable")
        ask_for_clarification_or_operator_help()
```
The continuation exception is narrow: the goal must predate the fault, be independently grounded, remain fresh, match the current task key, and pass all pose/transform/metric and authorization gates. A cached model output cannot become a fallback.
### 8.10 Road crossing authorization

```python
def request_crossing(task_key, candidate):
    navigate_to_verified_curb_stop(candidate)
    stop_and_build_curb_witness()
    conversation.ask_for_crossing_decision(candidate.id)
def on_crossing_decision(interaction):
    auth = authenticate_channel(interaction)
    require(auth.verification == VERIFIED)
    require("crossing" in auth.allowed_classes)
    require(current_state == STOPPED_AT_CURB)
    authorization = issue_single_use_crossing_auth(
        principal=auth.principal,
        task_key=current_task_key,
        candidate_id=current_candidate.id,
        curb_evidence=current_curb_witness.id,
        ttl=CROSSING_AUTH_TTL,
    )
def consume_crossing_auth(task_key, candidate):
    atomically_require_unconsumed_current_valid_match()
    mark_consumed_before_motion()
```
Any new task revision, lost curb witness, moved robot, changed crossing candidate, identity/authentication loss, expiry, replay, or safety fault invalidates authorization. The words “cross,” “go ahead,” or similar never create authority by themselves.
### 8.11 Low and critical battery behavior

Battery policy is deterministic and hysteretic. It uses hardware telemetry on the dog and explicitly marked simulated telemetry in simulation.
```python
def battery_supervisor_tick(b):
    if b.telemetry_health == INVALID:
        inhibit_new_nonessential_motion()
        publish_power_unknown()
        return HOLD if physical_odd_requires_battery else DEGRADED
    state = debounced_hysteretic_classify(b)
    if state == LOW:
        announce_once("My battery is getting low.")
        suppress_optional_base_and_posture_reactions()
        propose_return_or_dock_only_if_route_and_energy_are_verified()
    elif state in {CRITICAL, SHUTDOWN_IMMINENT}:
        cancel_or_checkpoint_normal_tasks_atomically()
        if currently_in_immediate_hazard and safe_exit_is_short_and_metric_verified():
            execute_bounded_hazard_exit_under_safety_monitor()
        else:
            dispatch_exact_zero_and_reset(reason="battery_critical")
        if stopped_and_terrain_is_posture_admissible():
            execute_trusted_ReturnToSafePose("sit")
        announce_once("My battery is critical; I need help charging.")
```
The dog never sits in a road merely to express low battery. `ReturnToSafePose` is post-stop and terrain-gated; inability to actuate the pose leaves the robot stopped and reports degraded completion rather than falsely claiming it sat.
## 9. Exact failure behavior

| Condition | Immediate behavior | Task effect | Recovery/release condition |
|---|---|---|---|
| LiDAR stale/missing | exact zero, reset shaper | suspend/recover | fresh commissioned scan + health dwell |
| pose/transform invalid | exact zero | suspend | relocalized, healthy transform, revision valid |
| camera semantics stale | retain no semantic update | continue only already metric-grounded goal | fresh semantic evidence or rescan |
| dynamic track stale | use conservative occupancy then stop | replan/wait | fresh tracks and clearance |
| owner track lost | decelerate then HOLD | bounded SearchOwner | enrolled owner reacquired M-of-N |
| owner ambiguous | HOLD | no nearest-person substitution | disambiguated identity |
| planner no path | stop/HOLD | bounded recovery | new metric goal/path or fail |
| learned proposal invalid | ignore proposal | reference planner unchanged | later valid proposal |
| LLM/VLM timeout | no new authority | current admitted task may continue | retry async/clarify |
| model process crash | isolate | narrow classical continuation or HOLD | healthy restart + new request |
| proposal TTL expired | discard | no effect | fresh same-revision proposal |
| task key mismatch | discard/log stale | no effect | never re-admit old result |
| resource conflict | do not dispatch | wait/defer by priority | lease release before deadline |
| command queue overflow | exact zero | health fault | operator/runtime recovery |
| optional queue overflow | drop oldest | no physical effect | automatic |
| controller feedback stale | exact zero | suspend | readiness handshake and stable feedback |
| hard collision verdict | exact zero same dispatch | recovery | obstacle clear + explicit monitor release |
| road authorization absent | stop at curb | wait | valid single-use authorization or reroute |
| road authorization expires | stop/no entry | wait/fail | issue new authorization at curb |
| battery telemetry invalid | inhibit new nonessential motion | degraded/HOLD by ODD | healthy telemetry |
| battery critical | safe hazard exit or exact zero, then safe pose | cancel/defer normal task | charging/operator recovery |
| terminal evidence incomplete | remain in progress, zero if dwelling | no success | continuous complete witness |
| manual command malformed | reject | active safe task unchanged | corrected command |
| emergency stop | latch exact zero | cancel all physical tasks | authenticated operator clear + readiness |
## 10. Observability and latency

Every interaction and physical task shares trace IDs without sharing authority. Record:

- `UserQueryEndToFirstReasoningResponse`;
- `UserQueryEndToFirstResponse` for first logged or spoken response, labeled by medium;
- end-of-speech to ASR-final, routing, snapshot, model first token, model complete;
- schema parse, compile, validation, acceptance, grounding, first motion;
- planner cycle, perception age, transform age, safety-monitor cycle, dispatch jitter;
- time to first checkpoint, recovery time, terminal dwell, task completion;
- model proposal acceptance/rejection and stable reason code;
- hard/comfort intervention counts and minimum predicted clearance/TTC;
- owner track age, ambiguity, reacquisition time, formation error;
- resource wait, preemption latency, stale result count, queue drops;
- energy state transitions and time spent in degraded modes.
Latency dashboards must separate dialogue responsiveness from physical authority. Filler speech is labeled filler and does not count as reasoning or task acceptance. A response that says “done” before terminal witness is a correctness failure regardless of latency.
Use monotonic timestamps inside one host. For cross-process timing, publish clock-domain metadata and measure IPC ingress/egress locally; do not subtract unsynchronized clocks. Report distributions and tails, not only means, stratified by simulator/physical, model-on/off, task type, sensor degradation, and cold/warm model state.
## 11. Phased implementation

### Phase 0 — freeze and repair authority

1. Add schema package and golden compatibility tests.
2. Implement atomic task key and channel epochs end-to-end.
3. Move hard monitor after the sole shaper and prove exact-zero same dispatch.
4. Make missing metric dependencies fail closed outside explicit sim fixtures.
5. Correct person stopping dimensions and unify footprint convention.
6. Split `ApproachOwner` from `FollowFormation`; change local `come` compilation.
7. Replace phrase crossing with authenticated event authorization.
8. Add real `BatteryStateV1` provider seam and safe power supervisor.
Exit: fault-injection tests prove no stale revision, model result, missing sensor, or crossing phrase can move the robot.
### Phase 1 — trusted semantic baseline

1. Implement `TaskRequestV1`, trusted compiler, and deterministic common intents.
2. Make recovery tables executable and bounded per revision.
3. Implement independent terminal witness bundles.
4. Route sidewalk/landmark/owner-relative goals through one metric grounder.
5. Route approach, follow formation, and orbit through the common planner.
6. Keep `grid_v1` as the only production planner.
Exit: headless deterministic integration scenarios pass without any LLM/VLM.
### Phase 2 — asynchronous companion brain

1. Split conversation and task-planning model roles, even if one artifact serves both.
2. Add out-of-process broker, bounded queues, TTLs, cancellation, and sandboxing.
3. Admit model task drafts only through the trusted compiler.
4. Add social cue proposals through the existing reaction/attention arbitration path.
5. Add truthful progress narration from executive events.
Exit: model crashes, hangs, malformed streams, and late outputs cannot affect active authority; conversation remains responsive during physical tasks.
### Phase 3 — stronger semantic perception

1. Separate fast closed-set semantics from scheduled open-vocabulary/OCR inference.
2. Add evidence-linked semantic memory and candidate ambiguity handling.
3. Add VLM goal hints in shadow, then proposal-only mode.
4. Add advisory map-provider interface with no free-space or crossing authority.
Exit: open-world goal success improves on held-out scenes without regression in metric safety, calibration, latency tails, or ambiguity behavior.
### Phase 4 — navigation challengers

1. Build a common planner adapter and replay harness.
2. Evaluate Nav2 with RPP against `grid_v1` using identical goals and witnesses.
3. Evaluate MPPI for dynamic local motion if compute and tail deadlines permit.
4. Evaluate open-weight learned proposal models in shadow using the same ABI.
5. Promote only per ODD/scenario slice with instant reference fallback while stopped.
Exit: preregistered gates pass; no challenger owns safety or Sport.
### Phase 5 — physical Unitree deployment

1. Commission camera/LiDAR extrinsics, coverage, time synchronization, and footprint.
2. Integrate hardware pose, controller, and battery providers.
3. Validate standstill, tethered, closed-course, indoor, private outdoor, then city slices.
4. Freeze firmware/model/config hashes for every run.
5. Expand ODD only after evidence review.
## 12. Concrete code seams

Expected work should preserve existing good boundaries and add adapters rather than one large rewrite:

- `src/parcel_robot/contracts/v1.py`: add frozen task, proposal, authorization, battery, and witness contracts or split into versioned modules with a re-export layer.
- `src/parcel_robot/brain/router.py`: keep deterministic routing; emit request drafts, not implicit action side effects.
- `src/parcel_robot/brain/compiler.py`: system-owned IDs, units, bounds, invariants, and bounded recovery; do not erase validated retry policy.
- `src/parcel_robot/brain/executive.py`: atomic task key/channel epoch and task-keyed lifecycle transactions.
- `src/parcel_robot/brain/runtime_adapter.py`: add `ApproachOwner`; return evidence-linked feedback rather than snapshot-derived success alone.
- `src/parcel_robot/voice/local_plans.py`: compile `come` to `ApproachOwner`.
- `src/parcel_robot/maps/crossing.py`: replace transcript phrase gate with `CrossingAuthorizationV1` consumer.
- `src/parcel_robot/authority.py`: dimensionally correct person constraint and one post-shaper hard-stop path.
- `src/parcel_robot/voice/reaction_bridge.py`: retain proposal-only reactions and add task-key/TTL observability.
- `src/parcel_robot/runtime.py`: remove simulated/physical ambiguity, orchestrate async proposals, and keep model calls off control ticks.
- new `src/parcel_robot/grounding/`: semantic-to-metric candidates and goal regions.
- new `src/parcel_robot/navigation/adapters/`: `grid_v1`, Nav2/RPP, MPPI, learned proposal.
- new `src/parcel_robot/power/`: telemetry provider and deterministic supervisor.
- new `src/parcel_robot/model_services/`: schemas, IPC client, TTL/restart/sandbox policy.
## 13. Test and evaluation plan

### 13.1 Unit and property tests

- Schema round-trip, unknown-field rejection, NaN/Inf rejection, version mismatch.
- Dimensional tests for braking/person clearance with generated SI values.
- Task-key mismatch and channel-epoch stale result rejection.
- Exactly one base lease and one command shaper.
- Hard verdict implies exact zero on the same dispatch and shaper reset.
- A safety monitor can never increase any command component or norm.
- Crossing authorization is task-bound, revision-bound, single-use, TTL-bound.
- Model output cannot author IDs, authorization, resources, bounds, or success.
- Resume restores or redispatches, never both.
- Terminal success requires every witness field and continuous dwell.
- Low-battery posture cannot run before stop and terrain admissibility.
### 13.2 Headless scenario matrix

Required scenarios include:

- sidewalk command from the road, ending inside safe sidewalk region;
- wait near lamppost within the admitted <=1 m vicinity and outside road;
- one orbit around the verified owner with dynamic obstacles;
- approach owner and release base, contrasted with persistent follow;
- follow behind through turns, stops, occlusion, and distractor people;
- ambiguous owner identity and adversarial nearest-person crossing;
- moving pedestrian crossing path with person-space constraint;
- correction during navigation and old planner result arriving late;
- joke/sadness/happiness reaction during idle, navigation, crossing, and recovery;
- planner/VLM crash, timeout, malformed output, and GPU pressure;
- LiDAR dropout, transform discontinuity, controller feedback loss;
- crossing request via phrase only, authenticated approval, replay, and expiry;
- low and critical battery in free space, beside road, and mid-crossing;
- manual control contention with active autonomous navigation;
- terminal relation satisfied briefly but without dwell or settled feedback.
Each scenario asserts trajectory, forbidden-region occupancy, collision/intervention, lifecycle state, resource ownership, dialogue claims, witness provenance, and latency.
### 13.3 Evaluation ladder

```text
L0 contract/property tests
L1 deterministic 2-D/headless fixtures
L2 recorded sensor replay and counterfactual proposals
L3 dynamic simulator scenes with randomized people/lighting/occlusion
L4 external benchmark adapters without modifying dog behavior
L5 hardware-in-the-loop with Sport adapter and sensor timing
L6 staged physical ODD trials
```
External benchmarks measure transferable navigation primitives; Parcel-specific companion scenarios remain the product gate. Keep benchmark adapters outside core behavior. Log run ID, date, git SHA, model/config hashes, hardware, seed set, change description, metrics, safety events, and artifact links for every run.
### 13.4 Metrics and promotion gates

Measure at minimum:

- task success with independent terminal witness;
- collision/contact and forbidden-region entry;
- minimum clearance and safety interventions;
- path efficiency, time, smoothness, yaw-first adherence, lateral use;
- dynamic-agent comfort violations;
- owner identity precision, retention, and reacquisition;
- clarification appropriateness and referent grounding precision;
- stale proposal/revision rejection rate;
- truthful dialogue and premature-completion rate;
- compute, power, loop deadline misses, and latency distributions.
Promotion is multi-objective and preregistered. A model cannot be promoted if it improves task/path score while regressing hard safety, identity integrity, terminal truthfulness, or mandatory deadline tails beyond the approved tolerance.
## 14. Risks and mitigations

### 14.1 Semantic confidence masquerades as geometry

Risk: a VLM confidently labels a sidewalk or doorway at the wrong metric location. Mitigation: semantic outputs nominate candidates only; calibrated camera depth/LiDAR and current transforms establish executable regions.
### 14.2 Two brains create contradictory behavior

Risk: dialogue promises one action while the executive performs another. Mitigation: conversation reads executive events and cannot claim acceptance/completion. Task authority comes only from admitted revisions.
### 14.3 Async results mutate newer tasks

Risk: late model output replaces a correction or cancel. Mitigation: complete task key, TTL, snapshot validation, channel epoch, latest-only queue, and atomic buffer flush.
### 14.4 Learned navigation overfits benchmark structure

Risk: score rises without product improvement. Mitigation: unchanged dog interface, held-out companion scenarios, external adapters, cross-benchmark evaluation, and metric/safety gates.
### 14.5 Identity association follows a stranger

Risk: nearest-person heuristics or occlusion swap the target. Mitigation: enrolled identity posterior, temporal M-of-N gate, ambiguity state, and HOLD.
### 14.6 Compute contention harms safety latency

Risk: VLM/LLM/GPU work creates control or perception deadline tails. Mitigation: process isolation, quotas, priorities, bounded queues, pinned core budgets, and ordered feature shedding.
### 14.7 Double smoothing produces sliding or delayed stops

Risk: planner and runtime each smooth velocity. Mitigation: one declared shaper; normal navigation penalizes lateral motion and uses yaw-align then forward where feasible; hard stop bypasses and resets it.
### 14.8 Power expression creates a new hazard

Risk: the dog sits in unsafe terrain or blocks a road at low battery. Mitigation: deterministic hazard-first power policy, exact stop, terrain gate, and only then safe pose.
## 15. Falsifiers and stop conditions

Pause this architecture track and redesign if any of these persists after the named P0 work:

- hard-stop tests observe a nonzero command after a hard verdict;
- stale sensor or stale revision can cause translation;
- terminal success can occur without independent metric evidence;
- owner ambiguity can select a different person;
- model process availability becomes necessary for stopping safely;
- crossing can be initiated by transcript content without authenticated single-use auth;
- task and dialogue lanes cannot be reconciled without serializing all model calls;
- target hardware cannot maintain mandatory loops after optional workloads are shed;
- the common planner abstraction changes dog behavior merely to fit an evaluation.
## 16. Review verdict

Adopt Design B as the target architecture after P0-A/B/C/D/F/G/H. It makes the current Parcel strengths—typed planning, resource leases, semantic skills, Unitree Sport, and reaction arbitration—the trusted spine, while putting open-weight models where they add the most value: open-world interpretation, goal nomination, conversation, and optional navigation proposals.
The first quality hill-climb is not model training. It is making task identity, evidence, metric grounding, recovery, and success definitions impossible to bypass. After that, compare open-weight intent/VLM/navigation artifacts in shadow against the deterministic reference. Custom RL becomes justified only for a narrow residual capability when a reproducible dataset, simulator-to-robot validation path, and measurable gap remain.
## 17. Implementation review checklist

- [ ] Unitree Sport remains the only gait/balance owner.
- [ ] Camera/LiDAR metric authority is commissioned and freshness-gated.
- [ ] RGB semantics and map data never assert free space.
- [ ] All async artifacts carry full task key, snapshot ID, and TTL.
- [ ] `ApproachOwner` and `FollowFormation` have distinct lifecycle semantics.
- [ ] There is one base writer and one velocity shaper.
- [ ] Final safety is post-shaper and can only tighten or zero.
- [ ] Hard stop is exact zero in the same dispatch and resets state.
- [ ] Person stopping math is dimensionally valid.
- [ ] Recovery is finite, executable, revision-bound, and deadline-bound.
- [ ] Completion requires fresh independent terminal witnesses.
- [ ] Social reactions cannot steal base from critical work.
- [ ] Model failure defaults to HOLD except the narrow admitted-goal continuation case.
- [ ] Crossing authority is authenticated, single-use, task-bound, and curb-bound.
- [ ] Low-battery posture is subordinate to immediate physical safety.
- [ ] Conversation never claims unverified acceptance or success.
- [ ] External eval adapters do not alter core dog behavior.
- [ ] Every run records code, model, configuration, evidence, and latency provenance.
