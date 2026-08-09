# Design C — Predictive Candidate Companion

**Date:** 2026-08-08  
**Status:** implementation-grade alternative for review; no runtime activation  
**Decision class:** frontier research architecture with deterministic safe degradation  
**Embodiment:** Unitree Go2 through the existing Unitree Sport controller  
**Safety status:** architecture and evaluation plan only; not physical-motion clearance  
**Primary evidence:** the 2026-08-07 audit, target architecture, model ledger, social-navigation report, evaluation ladder, and custom-training decision

---

## 0. Decision in one page

### 0.1 Thesis

Design C treats local navigation as a bounded choice problem.

At every planning instant, several independent components may propose short
SE(2) routes or trajectories.

Those components include classical grid planning, a forward-preferred
regulated-pure-pursuit family, a reviewed MPPI candidate sampler, social and
formation generators, route memory, and legally eligible open-weight models.

Every proposal is converted to one canonical representation.

Every non-HOLD candidate is then checked by deterministic hard-admissibility
masks derived from fresh camera/LiDAR geometry, state feedback, task policy,
owner identity state, transforms, and the embodiment safety envelope.

A deterministic selector initially chooses among the survivors.

Only after explicit data, evaluation, calibration, latency, licensing, and
failure-degradation gates may a learned ranker choose one candidate index or
abstain.

The learned ranker cannot create a candidate.

It cannot restore a masked candidate.

It cannot alter the active task or revision.

It cannot emit body velocity, Unitree commands, joints, torque, identity,
free-space claims, authorization, or task completion.

Abstention, malformed output, deadline miss, out-of-distribution input, and an
empty admissible set all resolve to HOLD, or to a separately re-admitted
continuation of the same authorized deterministic plan.

Unitree Sport continues to own gait and balance.

The existing controller, outgoing collision/TTC gate, post-shaper independent
monitor, command lease, watchdog, and feedback stop confirmation remain below
the candidate system.

### 0.2 Why consider it

One deterministic local plan can be brittle in a dynamic crowd.

A single learned policy can be opaque, distribution-sensitive, and hard to
contain.

A bounded candidate set exposes meaningful alternatives such as:

- pass left;
- pass right;
- wait;
- slow behind a pedestrian;
- take a slightly longer clear route;
- preserve owner visibility;
- return to the current formation band;
- scan instead of moving;
- use a model-proposed urban waypoint only after metric re-planning;
- execute a state-authorized recovery maneuver.

This makes the learning target smaller and more auditable than end-to-end
navigation.

It also creates an oracle-coverage metric: whether the candidate set contained
a good answer before blaming the ranker.

### 0.3 Why it is not the initial product default

Design C has the largest assurance and systems burden of the three alternatives.

It needs candidate diversity without uncontrolled branching.

It needs synchronized world-state history.

It needs a stable MPPI or equivalent candidate-export ABI.

It needs counterfactual labels and selection-regret evaluation.

It adds GPU and process scheduling pressure to an already duplex voice-enabled
desktop stack.

It adds a new failure surface without removing the deterministic stack.

The recommended deployment posture is therefore:

1. implement the shared deterministic safety and task foundations first;
2. ship deterministic candidate generation and selection;
3. run every learned proposer and ranker in shadow;
4. promote only a bounded role that beats frozen baselines without safety,
   latency, availability, or failure-degradation regression;
5. preserve a no-model product profile throughout.

### 0.4 Recommended decision

Approve Design C as the frontier research branch and ABI target.

Do not approve learned active selection yet.

Use the same shared foundation as Designs A and B.

Begin with multiple deterministic candidates because that alone can improve
route diversity, explainability, recovery, and testability.

Use open-weight policies as proposal-only shadows.

Train nothing until the no-training gates in Section 15 fail in a way that
shows a Parcel-specific ranker would add value.

---

## 1. Goals, non-goals, and activation prerequisites

### 1.1 Goals

| ID | Goal | Reviewable success condition |
| --- | --- | --- |
| C-G1 | Preserve one safe locomotion authority | Exactly one admitted candidate prefix reaches one tracking controller and Unitree Sport |
| C-G2 | Improve dynamic-scene choice | Candidate oracle coverage and selected success beat the frozen single-route baseline |
| C-G3 | Preserve common-sense task semantics | Task and goal-region contracts precede local candidate generation |
| C-G4 | Make owner follow socially aware | Enrolled identity, formation geometry, dynamic prediction, and common collision planning are all present |
| C-G5 | Bound learned authority | Ranker returns only an admitted candidate ID or abstention |
| C-G6 | Fail closed | Missing/stale/malformed/deadline-missed evidence cannot create motion |
| C-G7 | Retain forward-preferred motion | Ordinary travel penalizes lateral translation, reverse, and large heading error while retaining lateral capability |
| C-G8 | Verify completion independently | Terminal witnesses use sensor/state evidence and dwell, never planner or model self-report |
| C-G9 | Support honest improvement | Frozen paired runs separate proposal coverage, ranker quality, controller quality, and safety behavior |
| C-G10 | Remain portable | Deterministic path operates without desktop GPU, network, or learned services |

### 1.2 Non-goals

The following are explicitly outside Design C:

- language directly to motor commands;
- language directly to waypoint coordinates;
- a VLM declaring metric free space;
- a VLM declaring the owner identity;
- residual velocity reinforcement learning;
- joint, torque, gait, or balance policy learning;
- replacement of Unitree Sport;
- end-to-end camera-to-Unitree control;
- online reinforcement learning on the physical robot;
- autonomous road entry inferred from a transcript, map, or learned prior;
- a learned collision shield;
- a learned task-success witness;
- unlimited candidate generation;
- blocking the control loop while waiting for a model;
- treating simulator actor truth as a deployable perception result;
- treating model download, checkpoint presence, or paper results as integration;
- optimizing an external benchmark by changing Parcel’s behavior contract;
- silently continuing an expired learned trajectory;
- using a reverse recovery without fresh swept-corridor support.

### 1.3 Preconditions before any predictive component leaves OFF

| Gate | Current reason | Required closure |
| --- | --- | --- |
| C-P0-A exact-zero | The outgoing S-curve “emergency” branch currently slews toward zero | Independent post-shaper monitor emits exact zero on the same stop tick and is regression-pinned |
| C-P0-B sensor fail-close | The shipping grid path can fall back maplessly when scan data is absent | Product profile requires fresh collision coverage or exact-zero HOLD |
| C-P0-C person units | SafetyEnvelope.person_stop adds a seconds-valued allowance to metres | Replace it with a dimensionally correct measured-distance allowance and pin one authority |
| C-P0-D transforms | Current grid code documents a MAP-to-ODOM seam | Every proposal and witness binds a healthy transform epoch and covariance |
| C-P0-E task lifecycle | Approach and persistent follow are not yet fully separated on all paths | ApproachOwner terminates/releases base; FollowFormation remains persistent |
| C-P0-F resume | Task/channel suspension and resume must be atomic | A resumed step reacquires all resources or remains stopped |
| C-P0-G terminal truth | Planner status is not enough | Independent region/relation witnesses are product-path mandatory |
| C-P0-H clocks | Cross-process model timing needs a common basis | Monotonic timestamps, boot ID, frame epoch, and expiration semantics are frozen |
| C-P0-I evidence scope | Simulator-perfect owner/semantic labels can leak into product evaluation | Sensor-only and oracle evidence channels are mechanically separated |
| C-P0-J baseline | Improvement needs a frozen comparator | Pin code, config, scenario manifest, seeds, and hardware profile |

No model flag may bypass these gates.

The OFF and deterministic-only modes remain valid if a gate is not closed.

---

## 2. Current Parcel delta

Design C is a target architecture, not a description of today’s active path.

| Current component | Useful foundation | Missing or unsafe-to-assume delta |
| --- | --- | --- |
| brain/contracts.py | Typed PlanIR, PlanStep, revisions, resources, timeouts, recovery | The world snapshot is not yet the complete immutable candidate ABI |
| brain/validator.py | Skill allowlist and model prohibition on velocities/coordinates | ApproachOwner and total relation lifecycle need full product-path closure |
| brain/executive.py | Resource locking, bounded attempts, interruptibility, revision checks | Candidate leases and rank response invalidation do not exist |
| instructnav/arbiter.py | TTL SE2Goal and deterministic priority/confidence sort | It keeps latest per source, polls synchronously, and selects one goal; it has no batch, trajectory mask, task revision, or learned rank contract |
| navigation/grid_planner.py | Sensor-built rolling occupancy, A*, dynamic additive costs | One route is exposed; candidate variants and normalized timed trajectories are absent |
| navigation/grid_navigator.py | Align-first, forward-preferred tracking; lateral interface retained | Missing-scan fallback and MAP/ODOM seam must close before active C |
| navigation/follow.py | Camera/LiDAR gates, direct/behind modes, optional prediction | Direct proportional twist bypasses the common route family; identity remains weaker than OwnerTrackV1 target |
| contracts/v1.py | OwnerTrackV1, DynamicTrackV1, SemanticRegionV1, GoalRegionV1 | Runtime consumers and evidence freshness are not yet end-to-end |
| navigation/dynamic_layer.py | Dynamic cost and outgoing TTC work exist | Candidate-horizon dynamic occupancy masking and social re-ranking need one contract |
| runtime.py | Smoother, collision gate, actuator shaper, ControlManager | Same-tick exact-zero after shaping is a prerequisite, not a solved assumption |
| authority.py | Central body/speed/stopping authority and covariance expansion seam | person_stop is dimensionally inconsistent and multiple old proximity consumers remain |
| control/unitree_sport.py | Closed-loop gait/balance and bounded high-level body velocity | Retain unchanged below the new architecture |
| navigation/models/__init__.py | Honest factory boundary | Only stub and grid are constructible; learned navigator types were removed |
| route_memory/citywalker.py | Gate-off, TTL proposal-only, skip-honest adapter | Live checkpoint inference is intentionally not wired |
| route_memory/proposer.py | Taught path emits TTL SE2Goal only | No timed trajectory, revision binding, or full hard-mask report |

This delta yields four immediate design rules:

1. introduce new versioned contracts beside the current SE2Goal;
2. adapt current grid/route-memory results into those contracts;
3. do not mutate SE2Goal into an overloaded learned-control message;
4. keep C disabled until shared P0 behavior is demonstrably correct.

---

## 3. End-to-end architecture

~~~text
 owner speech / text / manual UI / system event
                         |
                         v
              fast intent + conversation lane
                         |
              TaskRequestV1 / task revision
                         |
                         v
         typed PlanIR + deterministic validation
                         |
                         v
       active PlanStep + policy-bound GoalRegionV1
                         |
       +-----------------+--------------------+
       |                 |                    |
       v                 v                    v
 immutable sensor   semantic grounding   owner/dynamic state
 world-state slice  (advisory labels)    + short prediction
       |                 |                    |
       +-----------------+--------------------+
                         |
                         v
                bounded proposal workers
       +---------+---------+---------+---------+
       | grid    | RPP     | MPPI    | social  |
       | variants| family  | sampler | follow  |
       +---------+---------+---------+---------+
       | route memory / legally cleared open-weight shadows |
       +----------------------------------------------------+
                         |
                         v
           normalize + deduplicate + source quotas
                         |
                         v
              CandidatePoolV1 + explicit HOLD
                         |
                         v
       deterministic hard-admissibility masks, pass 1
                         |
                         v
       CandidateBatchV1 = admitted candidates + HOLD
                         |
             +-----------+-----------+
             |                       |
             v                       v
 deterministic scorer          optional learned ranker
 always available              OFF -> SHADOW -> ACTIVE
             |                       |
             +-----------+-----------+
                         |
          deadline + abstention + hysteresis selector
                         |
              hard revalidation, pass 2
                         |
                         v
        short candidate commitment / tracking reference
                         |
                         v
       common local tracker -> body velocity target
                         |
                         v
          outgoing collision/TTC and policy gate
                         |
                         v
               comfort/actuator shaping
                         |
                         v
       independent post-shaper geometry/state monitor
           stale or unsafe -> exact-zero this tick
                         |
                         v
        ControlManager lease/watchdog/feedback supervision
                         |
                         v
          Unitree Sport closed-loop gait + balance
                         |
                         v
     odometry/state feedback -> progress + terminal witness
~~~

### 3.1 Authority order

Authority is ordered and cannot be traded for a score.

| Order | Authority | May permit motion? | May veto motion? |
| --- | --- | --- | --- |
| 1 | emergency latch / manual safety control | No | Yes, unconditional |
| 2 | TaskExecutive resource and revision state | Only by authorizing a step | Yes |
| 3 | goal/crossing/operational policy | Only within task policy | Yes |
| 4 | hard candidate mask | Only candidates that pass | Yes |
| 5 | selector/ranker | Select among admitted IDs | No unmasking |
| 6 | deterministic revalidator | Preserve selected prefix | Yes |
| 7 | tracking controller | Convert reference to bounded body target | No safety override |
| 8 | outgoing collision/TTC gate | No | Yes |
| 9 | post-shaper independent monitor | No | Yes, exact zero |
| 10 | ControlManager / Sport feedback | Execute admitted target | Watchdog and stop |

### 3.2 One-writer invariant

The selector owns no Unitree API handle.

Proposal workers own no Unitree API handle.

The ranker owns no Unitree API handle.

Only the admitted tracking channel may request a bounded MidLevelCommand.

Only ControlManager may deliver that command to Unitree Sport.

Manual control uses the same authority arbiter and cannot race an autonomous
candidate writer.

### 3.3 Safety independence

The final stop monitor must not consume:

- ranker risk scores;
- model confidence;
- model depth;
- model free-space labels;
- planner arrival probability;
- semantic map traversability;
- a candidate’s self-reported collision flag.

It consumes independently fresh metric camera/depth or LiDAR coverage, robot
state, transform health, and the final post-shaper command.

---

## 4. Rates, horizons, and deadlines

These are target architecture bands from the prior research.

They are not measured Parcel physical-loop performance.

Every deployment must replace provisional ceilings with trace-derived budgets.

### 4.1 Rate groups

| Component | Initial rate band | Hard real-time dependency | Stale behavior |
| --- | --- | --- | --- |
| Unitree feedback/watchdog | vendor-compatible, targeted 50–100 Hz supervision | Yes | exact-zero / fault |
| post-shaper monitor | 50–100 Hz | Yes | exact-zero |
| body tracker/local controller | 20–50 Hz | Yes | exact-zero when reference expires |
| pose/transform fusion | 20–50 Hz | Yes | exact-zero when required transform expires |
| LiDAR integration | 10–20+ Hz | Yes for covered motion | exact-zero outside valid coverage |
| RGB/depth ingest | approximately 30 Hz when available | Task dependent | mask semantic/identity-dependent candidates |
| dynamic-agent tracking | 15–30 Hz target | Required in human ODD | HOLD if policy requires and stale |
| owner tracking | 15–30 Hz target | Required for owner-relative tasks | HOLD or SearchOwner |
| formation-goal sampling | 10–20 Hz | Required for FollowFormation | expire goal and HOLD |
| candidate pool generation | 5–10 Hz local target | No control-loop blocking | keep only unexpired admitted commitment |
| open-weight local proposer | 1–10 Hz, model dependent | No | skip source |
| semantic grounding | 5–15 Hz or event driven | Task dependent | retain only evidence-valid region |
| social re-ranking | about 1 Hz plus events | No | deterministic selection |
| global route planning | 1–5 Hz plus replan events | No | local HOLD when route becomes invalid |
| OCR/open-vocabulary lookup | 0.2–2 Hz or event driven | No | AskClarification / scan |
| task executive | event driven plus approximately 10 Hz | Yes for lease state | no dispatch |
| dialogue/reasoning | asynchronous | No motion dependency | deterministic task lane remains available |

### 4.2 Provisional simulator profile

The following values are an initial reproducible simulator profile, not field
performance claims:

| Parameter | Initial value | Rationale |
| --- | --- | --- |
| local candidate horizon | 2.4 s | Within the researched 2–3 s bounded-local window |
| trajectory knot spacing | 0.2 s | Twelve future knots; predictable payload |
| maximum non-HOLD candidates | 24 | Bounded CPU, IPC, and scoring size |
| maximum per-source contribution | 6 | Prevent correlated source flooding |
| candidate pool period | 100 ms | 10 Hz local experiment |
| local commitment prefix | at most 300 ms | Limits stale-plan exposure |
| ordinary minimum dwell | 300 ms | Reduces left/right oscillation |
| ranker process deadline | 20 ms simulator ceiling | Provisional; must fit measured slack before activation |
| late-response tolerance | zero batches | A response for an older batch is discarded |
| deterministic selector | same process as admission | Does not depend on IPC or GPU |
| model queue depth | one latest request | No backlog |

These settings are intentionally bounded.

They are changed only through a versioned profile included in every run log.

### 4.3 Deadline algebra

For batch b:

~~~text
 state_deadline(b)
   = minimum expiration of every required evidence item and transform

 candidate_deadline(c)
   = minimum(proposal expiry, state_deadline, active-step deadline)

 rank_deadline(b)
   = minimum(
       configured ranker budget,
       batch expiry - current monotonic time,
       candidate prefix start deadline
     )

 commit_deadline(c)
   = minimum(candidate expiry, next mandatory revalidation, task lease expiry)
~~~

A model never extends an evidence expiration.

A rank response received at or after rank_deadline is invalid.

Control and safety loops never wait for rank_deadline.

They consume the most recent fully admitted commitment or command HOLD.

---

## 5. Canonical state and history contracts

### 5.1 Design principles

These candidate-system contracts extend the minimum normative fields in
[`../SHARED_FOUNDATION.md`](../SHARED_FOUNDATION.md). Phase 0 merges them into
one canonical serialization; they are not alternate definitions that may omit
or reinterpret the shared task, evidence, goal, proposal, feedback, or safety
semantics.

All proposal workers for one batch see the same immutable snapshot identity.

No worker reads mutable runtime objects directly.

Capture time and receive time are distinct.

Every evidence item carries source, sequence, frame, calibration, covariance,
issued time, and expiry.

All local trajectories are normalized to ODOM for short-horizon tracking.

MAP and semantic goals remain in MAP and bind an explicit MAP-to-ODOM transform
epoch.

A discontinuous localization correction creates a new frame epoch and
invalidates old candidates.

Oracle simulator state is stored in a separate namespace inaccessible to
product-policy processes.

### 5.2 WorldStateSliceV1

The candidate subsystem consumes this exact logical envelope:

~~~text
WorldStateSliceV1
  schema_version: "parcel.world_state.v1"
  snapshot_id: UUID
  boot_id: UUID
  captured_at_monotonic_ns: uint64
  expires_at_monotonic_ns: uint64
  frame_epoch: uint64
  robot_profile_id: string
  safety_profile_id: string
  speed_regime_id: string
  robot_pose_odom: PoseSE2 + covariance + evidence_ref
  robot_twist_body: TwistSE2 + covariance + evidence_ref
  map_from_odom: TransformSE2 + covariance + health + evidence_ref
  controller_state: mode + fresh_feedback + stopped_confirmed + evidence_ref
  occupancy_window_ref: immutable raster handle + generation + resolution
  lidar_coverage_ref: angular/range/time coverage handle
  traversability_ref: optional metric elevation/slope handle
  dynamic_tracks: tuple[DynamicTrackV1]
  owner_track: OwnerTrackV1 | null
  semantic_regions: tuple[SemanticRegionV1]
  goal_region: GoalRegionV1
  task_id: UUID
  task_revision: uint64
  plan_step_id: UUID
  skill_name: allowlisted enum
  task_policy_id: string
  crossing_authorization_ref: authenticated token | null
  resource_lease_id: UUID
  sensor_health: exact per-source freshness/coverage state
  evidence_manifest_hash: SHA-256
~~~

Unknown fields are rejected.

Missing required fields are not defaulted.

The snapshot expiration is the minimum of its required evidence expirations.

Goal-specific requirements determine whether RGB, depth, owner tracking, or
dynamic tracking is mandatory.

LiDAR or independently calibrated metric depth is mandatory for translating
through space in the product ODD.

### 5.3 HistoryBundleV1

History is explicit rather than hidden in model-process memory:

~~~text
HistoryBundleV1
  schema_version: "parcel.history.v1"
  bundle_id: UUID
  snapshot_id: UUID
  frame_epoch: uint64
  rgb_frames:
    - frame_id
    - capture_monotonic_ns
    - receive_monotonic_ns
    - camera_calibration_id
    - camera_from_base_transform_ref
    - immutable image handle
    - dropped_before_count
  depth_frames: same timing/calibration discipline
  lidar_sweeps:
    - sweep_id
    - capture interval
    - lidar calibration ID
    - lidar-from-base transform ref
    - immutable point/range handle
  pose_history:
    - capture monotonic time
    - ODOM pose and covariance
  owner_history:
    - enrolled identity state
    - pose/velocity/covariance
  dynamic_track_history:
    - track IDs and predicted occupancy
  maximum_history_ns: bounded by producer profile
  history_manifest_hash: SHA-256
~~~

CityWalker’s expected five-RGB history, for example, is built from this bundle.

It does not receive a private unsynchronized frame queue.

Missing frames are represented as missing, not silently duplicated, unless a
model-specific adapter explicitly declares and evaluates that behavior.

### 5.4 State assembler

The assembler performs:

1. monotonic time validation;
2. calibration and transform lookup;
3. frame-epoch binding;
4. freshness computation;
5. covariance propagation;
6. evidence-manifest hashing;
7. task/revision/resource binding;
8. immutable handle publication;
9. product/oracle channel separation;
10. bounded history selection.

It does not:

- infer task meaning;
- score candidate quality;
- repair a stale sensor;
- relabel an ambiguous owner;
- transform a learned confidence into safety evidence.

---

## 6. Proposal, candidate, mask, and rank contracts

### 6.1 TrajectoryPointV1

A canonical local point is:

~~~text
TrajectoryPointV1
  t_from_start_ms: uint16
  x_m: finite float
  y_m: finite float
  yaw_rad: finite wrapped float
  pose_covariance_3x3: finite positive-semidefinite matrix
~~~

Points are ODOM-frame poses.

They are not velocity commands.

Velocity, acceleration, jerk, curvature, reverse distance, and lateral motion
are deterministically derived during normalization.

The first point must agree with the snapshot robot pose within a configured
covariance-expanded start tolerance.

Time must start at zero and increase strictly.

The last point must not exceed the configured horizon.

### 6.2 NavProposalV1

Every producer, classical or learned, emits:

~~~text
NavProposalV1
  schema_version: "parcel.nav_proposal.v1"
  proposal_id: UUID
  producer_id: allowlisted string
  producer_version: immutable digest
  artifact_manifest_id: string
  mode: deterministic | learned | route_memory | social | recovery
  task_id: UUID
  task_revision: uint64
  plan_step_id: UUID
  goal_id: UUID
  snapshot_id: UUID
  frame_epoch: uint64
  source_sequence: uint64
  issued_at_monotonic_ns: uint64
  expires_at_monotonic_ns: uint64
  representation: se2_trajectory | xy_waypoints | se2_waypoints
  frame_id: ODOM | MAP
  points_or_waypoints: bounded tuple
  arrival_hint: never | possible | predicted
  confidence_value: float in [0,1] | null
  calibration_id: string | null
  evidence_refs: bounded tuple[string]
  requested_constraint_tags: bounded tuple[enum]
  inference_started_ns: uint64
  inference_finished_ns: uint64
  diagnostics: bounded typed map
~~~

The producer may leave confidence null.

An uncalibrated score must not be called confidence.

arrival_hint is advisory and never completes a task.

requested_constraint_tags may ask for pass-left or visibility preference.

They cannot weaken policy.

### 6.3 Proposal ingress validation

Ingress rejects a proposal if any of the following holds:

- unknown schema or field;
- oversized payload or diagnostic map;
- non-allowlisted producer;
- artifact digest differs from the deployment manifest;
- legal/deployment status disallows the requested mode;
- task, revision, step, goal, snapshot, or frame epoch mismatch;
- issued time lies in the future beyond clock tolerance;
- expiration is not strictly after issue;
- proposal is already expired;
- unsupported frame;
- unhealthy or missing transform for MAP input;
- nonfinite coordinate, yaw, covariance, or confidence;
- too many points;
- nonmonotonic point time;
- excessive waypoint jump;
- start discontinuity;
- unsupported representation for that producer;
- missing required evidence reference;
- confidence without a known calibration ID;
- direct command, velocity, joint, torque, gait, or Sport payload;
- diagnostic content exceeding its strict allowlist.

Ingress validation is schema validation, not collision validation.

Accepted proposals remain untrusted until normalization and hard masking.

### 6.4 CandidateV1

The normalizer turns one or more proposals into:

~~~text
CandidateV1
  schema_version: "parcel.candidate.v1"
  candidate_id: SHA-256 of canonical immutable content
  source_proposal_ids: tuple[UUID]
  source_family: grid | rpp | mppi | social | recovery | route | open_weight
  source_variant_id: string
  task_id: UUID
  task_revision: uint64
  plan_step_id: UUID
  goal_id: UUID
  snapshot_id: UUID
  frame_epoch: uint64
  generated_at_monotonic_ns: uint64
  expires_at_monotonic_ns: uint64
  points_odom: tuple[TrajectoryPointV1]
  terminal_relation_intent: relation enum
  derived_kinematics:
    max_forward_mps
    max_lateral_mps
    max_yaw_radps
    max_accel_mps2
    max_yaw_accel_radps2
    max_jerk_mps3
    reverse_distance_m
    lateral_distance_m
    path_length_m
    maximum_curvature_inv_m
  soft_features: fixed versioned vector
  provenance_flags: bounded enum set
  canonical_content_hash: SHA-256
~~~

Candidate normalization:

- transforms to the batch ODOM frame;
- interpolates to the canonical knot spacing;
- infers yaw for XY-only sources with a low-confidence yaw flag;
- clips no geometry;
- repairs no collision;
- rejects an unrepresentable path;
- recomputes every derived field;
- discards producer-authored derived metrics;
- never interprets model velocity as a trajectory.

### 6.5 HoldCandidateV1

HOLD is an explicit sentinel, not an ordinary learned trajectory:

~~~text
HoldCandidateV1
  candidate_id: "HOLD"
  task_id / revision / step / snapshot / frame_epoch
  reason_context: bounded enum
  requires_exact_zero: true
~~~

HOLD is present in every batch.

Selecting HOLD requests exact-zero through the stop path.

If fresh feedback cannot confirm the robot stopped, the state is
STOP_REQUESTED_UNCONFIRMED, not successful HOLD.

### 6.6 CandidatePoolV1

Before masking:

~~~text
CandidatePoolV1
  schema_version: "parcel.candidate_pool.v1"
  pool_id: UUID
  profile_id: string
  state_snapshot_id: UUID
  state_manifest_hash: SHA-256
  task_id / revision / step_id / goal_id
  frame_epoch: uint64
  created_at_monotonic_ns: uint64
  expires_at_monotonic_ns: uint64
  candidates: tuple[CandidateV1], length <= 24
  hold: HoldCandidateV1
  source_health: tuple[ProducerHealthV1]
  deterministic_baseline_candidate_id: SHA-256 | null
  pool_hash: SHA-256
~~~

The deterministic baseline ID is recorded before learned ranking.

It is null only when no deterministic moving candidate is admissible at pool
construction time.

### 6.7 HardMaskVerdictV1

The mask engine emits one complete verdict per raw candidate:

~~~text
HardMaskVerdictV1
  schema_version: "parcel.hard_mask_verdict.v1"
  candidate_id: SHA-256
  pool_id: UUID
  mask_policy_version: immutable digest
  evaluated_at_monotonic_ns: uint64
  admissible: bool
  reason_codes: nonempty tuple[MaskReason] when rejected
  evidence_refs: tuple[string]
  minimum_static_clearance_m: float | null
  minimum_person_clearance_m: float | null
  minimum_dynamic_ttc_s: float | null
  coverage_fraction: float
  transform_epoch: uint64
  computation_digest: SHA-256
~~~

The full report is logged even when the ranker sees only admitted candidates.

### 6.8 CandidateBatchV1

The ranker input is:

~~~text
CandidateBatchV1
  schema_version: "parcel.candidate_batch.v1"
  batch_id: UUID
  pool_id: UUID
  batch_hash: SHA-256
  state_snapshot_id: UUID
  task_id / revision / step_id / goal_id
  frame_epoch: uint64
  created_at_monotonic_ns: uint64
  expires_at_monotonic_ns: uint64
  rank_deadline_monotonic_ns: uint64
  admitted_candidates: tuple[CandidateV1]
  hold: HoldCandidateV1
  deterministic_baseline_candidate_id: SHA-256 | null
  feature_schema_id: immutable digest
  mask_policy_version: immutable digest
  admission_report_hash: SHA-256
~~~

Only candidates with admissible=true enter admitted_candidates.

HOLD is represented as an additional K+1 choice.

Candidate ordering is canonical:

1. source-family ordinal;
2. source-variant ID;
3. candidate hash.

Ranker correctness never depends on process arrival order.

### 6.9 RankDecisionV1

The optional ranker returns:

~~~text
RankDecisionV1
  schema_version: "parcel.rank_decision.v1"
  decision_id: UUID
  batch_id: UUID
  batch_hash: SHA-256
  model_id: string
  model_digest: SHA-256
  calibration_id: string
  started_at_monotonic_ns: uint64
  finished_at_monotonic_ns: uint64
  selected_candidate_id: SHA-256 | "HOLD" | null
  abstain: bool
  abstain_probability: calibrated float in [0,1]
  candidate_scores: exact map[batch candidate ID -> finite score]
  candidate_uncertainty: exact map[batch candidate ID -> nonnegative float]
  ood_flags: bounded enum set
  explanation_codes: bounded enum tuple
~~~

selected_candidate_id is null exactly when abstain=true.

An explicit HOLD selection is distinct from model abstention in metrics.

Scores are preferences, not safety probabilities.

The selector rejects a response if:

- its batch ID or hash differs;
- its task binding differs indirectly through the batch;
- it arrives at or after deadline;
- the model digest or calibration ID is not active;
- it contains an unknown candidate;
- it omits a candidate score;
- any number is nonfinite;
- abstain fields are inconsistent;
- its payload is oversized;
- the service health lease is stale.

The only effect of rejection is deterministic selection or HOLD.

### 6.10 CommitLeaseV1

The admitted prefix is:

~~~text
CommitLeaseV1
  lease_id: UUID
  selected_candidate_id: SHA-256 | "HOLD"
  selector_mode: deterministic | ranker_active | fallback | hold
  batch_id / pool_id / snapshot_id
  task_id / revision / step_id / goal_id
  frame_epoch: uint64
  point_start_index: uint16
  point_end_index: uint16
  issued_at_monotonic_ns: uint64
  expires_at_monotonic_ns: uint64
  selection_trace_id: UUID
~~~

A lease authorizes only a short prefix.

It does not authorize a complete 2.4-second open-loop execution.

Every control tick checks task revision, lease time, frame epoch, reference
age, state health, and final geometry.

---

## 7. Candidate generation

### 7.1 Candidate-set invariants

The pool builder must satisfy:

- HOLD always exists;
- at least one deterministic source is requested;
- no source contributes more than its quota;
- duplicate paths do not become extra votes;
- each candidate is task-compatible;
- each candidate is short-horizon and locally trackable;
- candidates span meaningful route alternatives when geometry permits;
- source failure cannot prevent other sources from publishing;
- candidates from a newer task revision atomically supersede older candidates;
- no worker may block pool publication;
- absence is represented in source health, not by a synthetic empty path.

### 7.2 Grid family

The existing RollingGridPlanner is the first candidate source.

It remains sensor-built and A*-based.

The adapter generates bounded route variants by deterministic changes to:

- homotopy seed;
- obstacle inflation within one authority-derived allowed range;
- dynamic-cost weighting;
- unknown-space policy allowed by the active ODD;
- pass-left/pass-right waypoint constraints;
- social-cost preference;
- global-route corridor;
- terminal approach orientation.

All variants share the same hard safety envelope.

No variant may lower collision inflation below the authority floor.

No variant may turn unknown cells into known free cells.

Route smoothing is geometry checked after smoothing.

The existing forward-alignment controller can track each admitted variant.

### 7.3 Regulated Pure Pursuit family

RPP is the interpretable forward-preferred challenger.

It is not assumed to be implemented in Parcel today.

A sidecar or in-process port receives a fixed path and produces deterministic
short rollouts for a bounded parameter family:

- lookahead distance;
- curvature slowdown;
- approach slowdown;
- rotation-to-heading threshold;
- maximum forward speed;
- lateral penalty profile.

Ordinary destination travel uses zero nominal lateral motion.

Lateral velocity remains available for explicitly allowed close maneuvering
and obstacle geometry where the footprint and sensor coverage support it.

Candidate poses, not RPP velocity commands, cross into the common ABI.

The common tracker reconstructs the final body target.

### 7.4 MPPI family

MPPI is a dynamic-scene candidate generator, not safety authority.

Stock Nav2 MPPI should not be assumed to expose a stable K-best production API.

Before Design C depends on it, a time-boxed spike must establish one of:

1. an upstream-supported candidate export;
2. a small reviewed sampler plug-in with a stable versioned ABI;
3. an independent bounded sampler that reuses equivalent critics without
   scraping private controller buffers.

The spike must show:

- deterministic seeds and replay;
- fixed maximum K;
- bounded CPU/GPU time;
- no control-thread blocking;
- candidate pose sequences with timestamps;
- critic version and parameter capture;
- stable behavior across dependency upgrade;
- graceful zero-candidate failure;
- complete legal/dependency review.

Until that spike passes, MPPI contributes no production candidate.

An MPPI-selected optimal path may run as a shadow comparator.

It is not misrepresented as a diverse K-candidate source.

### 7.5 Social and owner-formation family

This source uses deterministic relation geometry:

- behind;
- direct stand-off;
- alongside left;
- alongside right;
- orbit clockwise;
- orbit counterclockwise;
- owner-visibility-preserving detour;
- wait/yield.

Only relations authorized by the active skill are generated.

FollowFormation receives short-TTL formation goals sampled at 10–20 Hz.

Those goals flow through the same grid/RPP/MPPI route candidates.

The owner’s position itself is never treated as the destination.

The destination is a covariance-expanded safe formation region.

### 7.6 Recovery family

Recovery candidates are generated only in an explicit bounded recovery state.

Possible candidates are:

- exact-zero wait;
- in-place scan;
- small yaw scan left;
- small yaw scan right;
- clear-corridor backtrack along recently traversed free poses;
- alternate global-route corridor;
- return to the last independently verified safe pose;
- AskClarification with HOLD.

No generic learned source may label itself recovery.

Reverse distance is capped by recovery policy.

Every reverse prefix requires fresh swept rear/lateral coverage.

### 7.7 Route memory

Taught routes are advisory route candidates.

They bind:

- route ID and immutable route digest;
- teaching robot profile;
- map/frame epoch;
- localization evidence;
- nearest unambiguous keyframe;
- a bounded lookahead;
- active task and revision.

A remembered route cannot declare its cells free today.

It is replanned or masked against current metric geometry.

The current RouteMemoryProposer can seed this adapter but does not yet satisfy
the full timed CandidateV1 contract.

### 7.8 Open-weight model candidates

Open-weight models are optional sources with role-specific adapters.

Their output is never placed directly on the body-command path.

| Candidate | Admissible Design C role | Current fact that constrains activation |
| --- | --- | --- |
| MiniCPM-RobotTrack | Owner-follow SE(2)-like waypoint proposal after a confirmed external owner crop/track | Core code/weights are Apache-2.0; DINOv3 and deployment dependencies are separate/gated; custom code and nonzero reported collisions require sandboxing and shielding |
| CityWalker | Urban traversability and short XY waypoint prior for a point goal | Local official-v1.0 checkpoint bytes were verified, but original asset-specific license scope/custom loader still needs review; model uses five RGB histories plus pose/point goal and does not provide language, identity, yaw authority, or safety |
| CE-Nav | First Go2 local-policy/detour shadow after artifact and dependency review | MIT repository publishes Go2/VelFlow artifacts, while checkpoint scope, transitive dependencies, legacy Isaac requirements, and incomplete training release remain review items |
| X-NavDP | RGB-D trajectory/recovery research shadow | Self-contained subtree has MIT text, but checkpoint metadata, noncommercial parent ambiguity, and Isaac assets block product acquisition |
| InternVLA-N1 System 2 / DualVLN | Desktop instruction-navigation proposal research | README badges declare CC BY-NC-SA 4.0 while machine-readable artifact grants are absent; product use is blocked and isolated research needs approval |
| NaVILA | Research-only instruction/waypoint comparison | Code is Apache, while weight grant and Llama-derived terms require artifact review |
| Qwen-RobotNav | Contract/schema donor | Official weights were not released in the audited state |
| VLFM pattern | Frontier/semantic value proposal, not local motor plan | Its modular scoring pattern is useful; geometry and terminal truth stay deterministic |

Model adapters must:

1. pin repository, artifact, loader, dependency, and license digests;
2. run custom code out of process with no credentials, network, or HAL;
3. construct the model’s exact history from HistoryBundleV1;
4. record preprocessing and camera calibration;
5. transform output through the canonical normalizer;
6. expose uncertainty honestly;
7. skip when inputs are missing;
8. use bounded TTL;
9. publish no motion when the process crashes or OOMs;
10. pass frozen offline and shadow tests before ACTIVE is even reviewable.

### 7.9 Deduplication and diversity

Candidate diversity is based on geometry, not producer count.

The normalizer computes:

- endpoint distance;
- time-aligned mean pose distance;
- maximum lateral separation;
- yaw separation;
- signed pass-side sequence;
- homotopy signature around tracked/static obstacles.

Two candidates below the configured geometric-equivalence thresholds collapse
to one representative.

The representative records every contributing proposal ID.

Source quota is applied after deduplication.

The initial thresholds are simulator-profile parameters and are frozen per run.

They require scale-specific tuning before physical use.

---

## 8. Deterministic hard-admissibility masks

### 8.1 Rule

Hard safety, authority, and task-policy constraints are never learned costs.

They are Boolean or fail-closed checks.

Every mask records evidence and a reason code.

The same policy library is invoked before ranking and immediately before
candidate commitment.

### 8.2 Mask reason vocabulary

The initial binding reason enum is:

~~~text
SCHEMA_INVALID
SOURCE_NOT_ALLOWED
ARTIFACT_NOT_ALLOWED
TASK_MISMATCH
REVISION_MISMATCH
STEP_MISMATCH
GOAL_MISMATCH
RESOURCE_LEASE_INVALID
EXPIRED
SNAPSHOT_STALE
FRAME_EPOCH_MISMATCH
TRANSFORM_MISSING
TRANSFORM_UNHEALTHY
POSE_STALE
POSE_UNCERTAINTY_EXCESSIVE
CONTROLLER_FEEDBACK_STALE
START_DISCONTINUITY
HORIZON_INVALID
KINEMATIC_LIMIT
ACCELERATION_LIMIT
JERK_LIMIT
CURVATURE_LIMIT
REVERSE_NOT_AUTHORIZED
LATERAL_COVERAGE_MISSING
STATIC_COLLISION
INSUFFICIENT_STATIC_CLEARANCE
UNKNOWN_SPACE_UNAUTHORIZED
SENSOR_COVERAGE_INCOMPLETE
DYNAMIC_TRACKS_STALE
DYNAMIC_COLLISION
TTC_BELOW_LIMIT
PERSON_ZONE_VIOLATION
OWNER_IDENTITY_UNCONFIRMED
OWNER_VISIBILITY_REQUIRED
OWNER_KEEPOUT_VIOLATION
FORMATION_RELATION_INVALID
FORBIDDEN_REGION_INTERSECTION
ROAD_ENTRY_UNAUTHORIZED
CROSSING_TOKEN_INVALID
GOAL_APPROACH_INVALID
RECOVERY_STATE_INVALID
RECOVERY_BUDGET_EXHAUSTED
TERMINAL_POSTURE_UNSAFE
DEADLINE_INFEASIBLE
INTERNAL_MASK_ERROR
~~~

An internal mask exception produces INTERNAL_MASK_ERROR and rejection.

### 8.3 Binding and freshness masks

Candidate task ID, revision, plan step, goal, resource lease, snapshot, and
frame epoch must exactly match the active executive state.

Every required evidence item must be unexpired at evaluation time.

The mask also predicts whether required evidence remains valid through the
commit prefix.

If not, DEADLINE_INFEASIBLE rejects it.

### 8.4 Kinematic masks

Derived candidate motion must fit the elementwise minimum of:

- RobotProfile;
- active SpeedRegime;
- task profile;
- environmental profile;
- controller limits;
- operator cap;
- safety cap.

Forward, lateral, yaw, acceleration, yaw acceleration, jerk, curvature, and
reverse distance are checked independently.

Ordinary lateral movement is a soft penalty only after hard caps and coverage.

Unauthorized reverse is hard-rejected.

A candidate that starts with substantial translation while misaligned can be
hard-rejected under the forward-travel profile.

### 8.5 Static geometry mask

For each trajectory segment:

1. interpolate at the collision checker’s resolution;
2. sweep the full robot footprint, not a point;
3. expand for pose and geometry covariance;
4. add speed-dependent stopping distance;
5. query only fresh independently sourced metric occupancy;
6. reject collision or insufficient clearance;
7. reject unsupported unknown space under the product policy.

Camera semantics may label a sidewalk.

They cannot erase a LiDAR obstacle.

External maps may nominate a route.

They cannot establish present free space.

### 8.6 Dynamic geometry and person mask

Each dynamic track’s predicted occupancy is expanded by:

- robot footprint;
- track covariance;
- robot pose covariance;
- sensing intrusion;
- reaction distance;
- braking distance;
- a dimensionally correct relative-motion allowance;
- human social-zone policy where applicable.

Time-aligned candidate intersections are rejected.

Minimum TTC is computed with relative velocity and uncertainty.

In a human-required ODD, stale dynamic tracks or missing coverage reject moving
candidates.

The owner is still a person for collision purposes.

Identity confirmation never disables the owner collision envelope.

### 8.7 Policy and semantic mask

The active GoalRegionV1 defines:

- acceptable terminal polygon;
- preferred pose;
- approach constraints;
- forbidden regions;
- relation;
- hold duration;
- evidence.

Road and crossing policy is independent:

- a sidewalk target does not authorize crossing a road;
- OSM, Google Maps placeholder data, CityWalker, OCR, or a transcript cannot
  authorize road entry;
- a crossing candidate requires the active task-bound authenticated token;
- token scope, route, direction, time, and revision must match;
- losing current metric curb/road geometry invalidates the candidate.

### 8.8 Owner and formation mask

Owner-relative candidates require:

- enrolled owner ID match;
- confirmed multi-frame identity state;
- acceptable identity and visibility posterior;
- bounded pose/velocity covariance;
- no unresolved same-appearance ambiguity;
- relation-specific heading evidence for “behind”;
- owner keepout and person clearance;
- task revision binding.

When heading is unavailable, “behind” does not silently become direct chasing.

When identity becomes ambiguous, follow candidates expire.

### 8.9 Revalidation

The selected candidate is checked again against a new state slice immediately
before commitment.

The revalidator never trusts the earlier verdict just because the batch is
unexpired.

It checks at least:

- task/revision/resource state;
- frame epoch;
- current start continuity;
- occupancy generation;
- dynamic-track generation;
- owner state;
- crossing token;
- controller feedback;
- commit-prefix swept geometry.

Revalidation failure selects HOLD and records the new reason.

---

## 9. Selection, abstention, and commitment

### 9.1 Modes

| Mode | Proposers | Ranker | Executed selection |
| --- | --- | --- | --- |
| OFF | Current deterministic plan only | Not loaded | Frozen deterministic baseline |
| MULTI_DETERMINISTIC | Deterministic candidates | Not loaded | Deterministic candidate selector |
| SHADOW_PROPOSERS | Learned candidates logged | Not loaded | Deterministic candidates only |
| SHADOW_RANKER | All approved candidates | Scores logged | Deterministic selector |
| ACTIVE_RANKER_SIM | All approved candidates | May select | Simulator only, hard masks and fallback active |
| ACTIVE_RANKER_HIL | Approved local candidates | May select | HIL after promotion gates |
| ACTIVE_RANKER_PHYSICAL | Narrow reviewed role | May select | Supervised ODD only after separate safety review |

Mode transition is restart-bound and audit logged.

No voice command may change it.

### 9.2 Deterministic selector

The first selector is deterministic and lexicographic.

It chooses:

1. HOLD when no moving candidate remains;
2. candidates satisfying the active terminal relation;
3. maximum policy clearance class;
4. minimum dynamic risk class;
5. maximum verified task progress;
6. minimum reverse and lateral travel for ordinary destination tasks;
7. minimum heading discontinuity and jerk;
8. minimum path length;
9. stable previous candidate when within the hysteresis band;
10. canonical candidate ID as the final tie-break.

Weights may refine ordering within a class.

No weighted term can compensate for a hard-mask failure.

### 9.3 Learned ranker

If training gates pass, the ranker consumes:

- fixed-length candidate pose embeddings;
- deterministic derived kinematics;
- metric clearance summaries;
- dynamic-occupancy/TTC summaries;
- owner-relative geometry;
- semantic relation features;
- task/skill enum;
- path progress;
- source-family indicators;
- observation health and uncertainty;
- recent selection history;
- recent stop/intervention history.

It returns preference scores for K admitted candidates plus HOLD.

It does not consume:

- simulator ground-truth collision future in product mode;
- oracle actor identity;
- future human motion beyond the online predictor;
- hidden evaluation answer;
- raw credentials or network state;
- language capable of changing the skill;
- a candidate masked out before request creation.

The initial learned class should be a small ranker or social critic.

Model size is chosen by measured latency and calibration, not branding.

### 9.4 Abstention

The ranker abstains when any configured condition holds:

- calibrated abstain probability exceeds threshold;
- ensemble disagreement exceeds threshold;
- OOD detector fires;
- all score margins lie below the indifference threshold;
- batch health differs from training support;
- the highest-scored candidate is HOLD;
- ranker process health lease is stale;
- response deadline is missed;
- calibration ID is invalid;
- selection would violate commitment hysteresis without sufficient margin.

Abstention does not mean “use the highest score anyway.”

It invokes deterministic selection if the same deterministic candidates still
pass immediate revalidation.

Otherwise it invokes HOLD.

### 9.5 Hysteresis and anti-oscillation

Candidate switching is allowed immediately for:

- emergency or explicit stop;
- current candidate hard invalidation;
- task revision;
- frame-epoch change;
- resource revocation;
- crossing authorization revocation;
- owner identity loss;
- controller or sensor fault.

An ordinary preference switch requires:

- minimum dwell completed;
- new candidate remains admissible;
- common-prefix compatibility or a trackable transition;
- improvement above a configured margin;
- no left/right sign oscillation cooldown violation.

The previous choice gets a small deterministic persistence preference.

That preference never preserves an unsafe candidate.

### 9.6 Selection algorithm

~~~text
function select_and_commit(now):
    executive = active_step_snapshot()
    if executive has no base lease:
        return request_exact_zero("no_base_lease")

    if emergency, explicit stop, manual takeover, or hard fault:
        invalidate_all_batches()
        return request_exact_zero("higher_authority")

    batch = latest_complete_batch_matching(executive)
    if batch is absent or expired:
        return re_admit_same_deterministic_continuation_or_hold()

    pass2 = revalidate_every_admitted_candidate(batch, latest_world_state())
    survivors = pass2.admitted
    if survivors is empty:
        return request_exact_zero("no_admissible_candidate")

    deterministic_choice = deterministic_select(survivors, previous_commit)

    if ranker_mode is not ACTIVE:
        choice = deterministic_choice
    else:
        decision = latest_valid_rank_decision(batch)
        if decision absent, late, malformed, OOD, or abstaining:
            choice = deterministic_choice
        else:
            choice = decision.selected_candidate_id

    if choice == HOLD:
        return request_exact_zero("selected_hold")

    if not switch_policy_allows(choice, previous_commit, latest_state):
        choice = previous_commit if immediately_revalidated else deterministic_choice

    final = revalidate_commit_prefix(choice, latest_world_state())
    if not final.admissible:
        return request_exact_zero(final.reason)

    lease = issue_short_commit_lease(choice, executive, final.evidence)
    return common_tracker.track(lease)
~~~

### 9.7 The last metre

Candidate ranking becomes less authoritative near terminal regions.

The final approach profile:

- reduces speed;
- expands uncertainty-sensitive clearance;
- respects terminal orientation;
- prevents overshoot;
- holds outside object footprint and road;
- waits for independent dwell and settled feedback.

The ranker may choose an admitted approach candidate.

It cannot decide arrival.

---

## 10. Instruction following and task planning

### 10.1 Separation of concerns

Conversation, task planning, semantic grounding, local candidate generation,
and motor control remain separate.

~~~text
utterance
  -> transcript + end-of-query event
  -> fast closed-intent lane and conversational reasoning in parallel
  -> typed TaskRequestV1
  -> PlanIR
  -> validated skill + arguments
  -> GoalRegionV1 / relation contract
  -> local candidates
~~~

The conversation model may say what it understood.

It may propose a typed skill plan.

It may not write coordinates or motion.

The grounding system resolves entities and regions from current evidence.

The executive owns task revision and interruption.

The local selector owns only trajectory choice within the active step.

### 10.2 Lane behavior

| Lane | Examples | Deadline behavior | Motion authority |
| --- | --- | --- | --- |
| literal safety | stop, freeze, manual takeover | synchronous fast path | exact-zero / authority transfer |
| common command | follow me, come here, wait, walk around me | deterministic typed templates first | validated skills |
| semantic local | sidewalk, lamppost, nearby shop | scan/ground/confirm region | GoalRegionV1 then candidates |
| slow deliberative | go to a named store across a complex route | asynchronous plan with progress dialogue | no motion until validated step |
| conversational | joke, sadness, question | dialogue can proceed while task continues | no base lease unless explicit behavior |

### 10.3 Common-sense templates

“Walk to the sidewalk” becomes:

1. detect and accumulate sidewalk semantic regions;
2. require metric free-space support and road-boundary evidence;
3. construct an acceptable sidewalk polygon;
4. subtract road, curb, obstacle, and person forbidden regions;
5. choose a preferred pose inside the remaining region;
6. plan admitted candidates without unauthorized road entry;
7. settle inside the polygon;
8. verify off-road occupancy and dwell.

“Wait by the lamppost” becomes:

1. ground a lamppost identity with camera evidence;
2. associate metric LiDAR/depth geometry;
3. construct an annular near-region outside the object/robot collision envelope;
4. remove road and obstacles;
5. navigate to any safe point in the region;
6. settle within the requested 1 m relation where physically feasible;
7. hold until released.

“Walk around me once” becomes:

1. confirm the enrolled owner;
2. construct an OrbitOwner relation with one signed revolution;
3. choose a profile-derived small social radius, not town scale;
4. plan around current obstacles and people;
5. preserve owner keepout;
6. accumulate unwrapped swept angle from sensor-derived relative pose;
7. finish after one revolution, radial tolerance, clearance, and dwell.

“Walk away from me five steps” becomes:

1. compile to MoveRelative with direction away from confirmed owner;
2. convert “step” using an explicit owner preference or robot-profile semantic
   distance, recorded in the plan;
3. use reverse only if the task semantics, rear coverage, and recovery profile
   permit it;
4. otherwise rotate, move forward away, and restore a socially appropriate
   orientation;
5. stop after odometry displacement and endpoint clearance are verified.

It must not blindly execute five open-loop reverse pulses.

### 10.4 Semantic uncertainty

If there are several lampposts, sidewalks, or stores:

- use current discourse and proximity to rank referents;
- ask a concise clarification if ambiguity affects the destination materially;
- optionally orient/scan while holding translation;
- bind the chosen entity ID and evidence to the task revision;
- invalidate the goal if association is lost.

The local trajectory ranker does not resolve referent ambiguity.

### 10.5 Task revision invalidation

Every correction creates a monotonic revision.

For example:

~~~text
"Go to the sidewalk."
  task=42 revision=1 goal=sidewalk-region-A

"No, the sidewalk on my left."
  task=42 revision=2 goal=sidewalk-region-B
~~~

Revision 2 invalidates:

- old proposals;
- old candidate pools;
- old rank decisions;
- old commit leases;
- old terminal witnesses.

No component matches a revision by natural-language similarity.

---

## 11. Owner following and social navigation

### 11.1 Owner identity state machine

The owner tracker exposes:

~~~text
UNENROLLED -> CANDIDATE -> CONFIRMED
CONFIRMED -> AMBIGUOUS -> CONFIRMED
CONFIRMED -> OCCLUDED -> CONFIRMED
AMBIGUOUS/OCCLUDED -> LOST
LOST -> SEARCHING -> CANDIDATE
~~~

Transition evidence is multi-frame.

The enrolled identity posterior stays outside MiniCPM or any local policy.

Nearest-person selection is forbidden.

Similar clothing, crossings, occlusion, re-entry, and multiple people are
first-class evaluation cases.

### 11.2 Formation goal

FollowFormationGoalV1 binds:

- task/revision/step;
- enrolled owner ID;
- owner track evidence and covariance;
- relation: behind, direct, left, or right;
- preferred distance band;
- keepout radius;
- optional heading requirement;
- short TTL;
- frame epoch;
- current predicted owner pose;
- maximum prediction horizon;
- loss behavior.

The sampler updates at 10–20 Hz.

It predicts conservatively from measured owner motion.

Prediction uncertainty widens masks and slows or stops motion.

### 11.3 Follow behavior

FollowFormation is persistent.

It emits progress checkpoints such as:

- formation_acquired;
- formation_degraded;
- yielding;
- owner_occluded_grace;
- reacquiring;
- lost_owner_hold.

It never reports terminal success merely because distance enters a deadband.

ApproachOwner is separate.

It terminates after the safe owner-relative region is held, feedback confirms
settled state, follow control is disabled, and the base lease is released.

### 11.4 Social costs after hard masks

Admitted candidates may be ranked by:

- personal-space comfort above the hard floor;
- passing side consistency;
- pedestrian flow alignment;
- visibility and legibility;
- approach angle;
- crossing behind rather than cutting in front;
- group splitting avoidance;
- owner visibility;
- formation error;
- wait versus squeeze preference;
- lateral motion, reverse, yaw rate, and jerk comfort.

These are soft preferences only above hard safety constraints.

### 11.5 Social re-ranking

A slower approximately 1 Hz social context process may update soft features.

Events also trigger immediate rebuild:

- person enters corridor;
- owner turns or accelerates;
- identity becomes ambiguous;
- group geometry changes;
- crossing token changes;
- route becomes occluded.

Hysteresis prevents pass-left/pass-right thrashing.

The real-time safety monitor remains independent.

### 11.6 Lost owner

On short occlusion:

- propagate the bounded prediction;
- decay confidence;
- reduce translation;
- retain only candidates within verified visibility and geometry limits.

On ambiguity or threshold expiry:

- expire formation candidates;
- exact-zero HOLD;
- checkpoint the follow task;
- invoke bounded SearchOwner if policy permits;
- ask the owner to speak or move if needed.

SearchOwner never resumes FollowFormation until enrolled identity is confirmed.

---

## 12. Behavior, interruption, and recovery

### 12.1 Executive boundary

The candidate selector cannot interrupt a task.

It cannot choose a candidate from a different skill.

It cannot assign priority.

TaskExecutive remains the only owner of:

- task priority;
- resource leases;
- suspend/cancel/resume;
- bounded attempts;
- recovery transitions;
- noninterruptible sections;
- completion reports.

### 12.2 Interruption matrix

| Event | Executive action | Candidate action |
| --- | --- | --- |
| emergency stop | cancel/latched stop | invalidate all; exact zero |
| explicit “stop/wait” | cancel or replace with Hold | invalidate all; exact zero |
| manual takeover | revoke autonomous base lease | invalidate all |
| safety hard fault | suspend/cancel by policy | exact zero |
| correction to active goal | increment revision | discard old batches and commitments |
| new urgent task | checkpoint/cancel according to policy | no cross-task candidate |
| ordinary conversation | no base interruption | continue current valid task |
| low-priority affect gesture | defer or overlap only non-base resource | navigation unchanged |
| critical noninterruptible segment | defer ordinary voice change | continue only while safety-valid |
| battery critical | navigate only to currently verified safe stop if possible, then Hold/Pose | no theatrical motion in road |

Safety interrupts even a noninterruptible section.

“Noninterruptible” means task coherence, never immunity from STOP.

### 12.3 Affect and companion behavior

User emotion and dialogue can produce an AffectIntent:

~~~text
AffectIntent
  task/turn ID
  valence/arousal with uncertainty
  suggested gesture enum
  suggested vocal style
  urgency: low
  expires_at
~~~

The behavior planner may translate it into Pose, Gesture, or Vocalize.

The suggestion is deferred when:

- base is in a critical maneuver;
- the gesture conflicts with balance or locomotion resources;
- safety state is degraded;
- battery policy forbids it;
- another higher-priority behavior holds the resource.

If the user is sad, a bow-like gesture may execute only when stopped and stable.

If the user is happy, a leg-lift gesture may execute only through a supported
Unitree high-level behavior and verified stance preconditions.

The ranker does not improvise body gestures.

### 12.4 Recovery state machine

~~~text
TRACKING
  -> YIELDING           dynamic obstruction, progress expected
  -> LOCAL_REPLAN       route invalid but local evidence healthy
  -> SCAN_IN_PLACE      semantic/geometry evidence insufficient
  -> BOUNDED_BACKTRACK  only along fresh verified corridor
  -> GLOBAL_REPLAN      local alternatives exhausted
  -> ASK_CLARIFICATION  destination ambiguity
  -> SAFE_HOLD          budget/freshness/authority exhausted
  -> FAILED             terminal report with evidence
~~~

Each transition records:

- trigger evidence;
- entry monotonic time;
- maximum duration;
- maximum attempts;
- maximum travel distance;
- allowed candidate families;
- exit condition;
- terminal fallback.

### 12.5 Stuck detection

Stuck detection requires a conjunction such as:

- an active moving commitment;
- expected progress above a threshold;
- odometry progress below a threshold over a window;
- no intentional person yield;
- no terminal dwell;
- fresh state feedback.

It must distinguish:

- blocked;
- yielding;
- actuator not moving;
- localization failure;
- oscillation;
- goal unreachable;
- semantic ambiguity.

Different causes permit different recovery candidates.

### 12.6 Recovery limits

Recovery cannot:

- reset safety evidence;
- clear an E-stop;
- cross a forbidden region;
- increase speed caps;
- assume rear space is clear;
- reuse an expired route;
- switch owner identity;
- exceed task attempt limits;
- declare success because motion resumed.

After the bounded budget, the dog holds, reports the concrete blocker, and asks
for help.

---

## 13. Independent terminal witnesses

### 13.1 General witness contract

TerminalWitnessV1 contains:

- task ID, revision, plan step, and goal ID;
- witness type and version;
- observed state snapshot IDs;
- semantic/entity evidence refs;
- pose/transform evidence refs;
- collision/clearance evidence refs;
- controller settled feedback;
- dwell start/end;
- relation-specific measurements;
- forbidden-region checks;
- result: satisfied, not_satisfied, or indeterminate;
- expiration.

The executive accepts satisfied only from the allowlisted independent witness
for that skill.

Model arrival hints and planner status are excluded.

### 13.2 Skill witnesses

| Skill | Terminal or persistent semantics | Required independent witness |
| --- | --- | --- |
| NavigateTo sidewalk | terminal | footprint inside acceptable sidewalk polygon, off-road, clearance valid, settled, dwell complete |
| NavigateTo object/lamppost | terminal | safe annular relation to associated metric object, within requested vicinity, off-road, settled, dwell |
| ApproachOwner | terminal | confirmed owner, safe distance band, low relative speed, settled dwell, follow disabled, base lease released |
| FollowFormation | persistent | periodic formation/progress checkpoint; no automatic terminal success |
| OrbitOwner | terminal | confirmed owner, unwrapped swept angle reaches requested revolution, radial error bounded, no collision, settled |
| MoveRelative | terminal | signed odometry displacement/orientation reached within tolerance, endpoint safe, settled |
| Hold | persistent or bounded | exact-zero requested and fresh controller feedback confirms stopped for dwell |
| Pose/Gesture | terminal | supported high-level behavior reports completion and stable stance |
| SearchOwner | terminal only on reacquisition | enrolled identity reconfirmed with multi-frame evidence |
| ScanBehavior | terminal | requested scan coverage completed while translation held |

### 13.3 Region, not point

Common-sense destinations are acceptable regions.

A sidewalk goal is a safe subset of a semantic sidewalk polygon.

A lamppost goal is an annulus clipped by free space and policy.

An owner approach is a relation band.

A shop entrance is a free-space approach region, not the door mesh centroid.

Preferred poses help ranking.

They do not invalidate other safe points in the region.

### 13.4 Indeterminate witness

If evidence becomes stale during dwell:

- witness returns indeterminate;
- motion remains held;
- the task does not succeed;
- evidence may be reacquired within the step deadline;
- otherwise recovery or failure is reported.

---

## 14. Deterministic fallback and failure semantics

### 14.1 Fallback principle

Failure of a learned source never creates a new fallback motion goal.

The system may continue only the same already-authorized deterministic goal or
candidate after full task, revision, transform, state, geometry, policy, and
deadline re-admission.

Otherwise it selects HOLD.

### 14.2 Failure matrix

| Failure | Permitted result |
| --- | --- |
| one proposer crashes/OOMs | omit source; deterministic pool continues |
| all learned proposers unavailable | deterministic candidates only |
| grid candidate unavailable but another deterministic candidate passes | select deterministic survivor |
| no deterministic moving candidate | HOLD even if a model proposes motion, unless that learned source has separately earned active proposal status and passes all gates |
| ranker process dead | deterministic selector |
| ranker deadline miss | discard response; deterministic selector |
| ranker malformed/unknown ID | discard response; deterministic selector |
| ranker abstains/OOD | deterministic selector or HOLD |
| all moving candidates hard-masked | HOLD |
| selected candidate fails pass-2 | deterministic reselect from freshly revalidated set or HOLD |
| task revision changes | discard all old state and HOLD until new batch |
| transform epoch changes | invalidate all candidates and HOLD |
| pose or required transform stale | HOLD |
| required LiDAR/metric depth stale | exact-zero HOLD |
| dynamic sensing stale in human ODD | exact-zero HOLD |
| owner identity ambiguous/lost | expire owner-relative candidates; HOLD/SearchOwner |
| crossing authorization absent/expired | mask crossing candidates |
| terminal witness indeterminate | hold and reacquire; no success |
| controller feedback stale | stop/fault through ControlManager |
| network lost | local deterministic stack only; no remote-plan continuation |
| GPU unavailable | no learned service dependency; deterministic stack |
| mask engine error | reject affected candidate; if systemic, HOLD |
| logging unavailable | continue only if safety-critical event log policy permits; learned ACTIVE should fail closed |

### 14.3 No unsafe convenience fallback

Explicitly forbidden:

- mapless translation because a scan is missing;
- replaying the last model trajectory past TTL;
- using camera appearance alone as collision-free space;
- switching to nearest person when the owner is lost;
- direct proportional follow through a wall;
- reverse pulses without rear coverage;
- bypassing the post-shaper monitor for smoothness;
- keeping motion because dialogue is still speaking;
- accepting old-rank output because it “looks similar” to the new goal.

---

## 15. Train or do not train

### 15.1 Default answer

Do not train a custom navigation or RL model now.

Spend zero RL GPU hours until the gates below are satisfied.

First determine whether:

- deterministic candidate diversity closes the observed failures;
- RPP or MPPI selection closes them;
- a legally usable open-weight proposer adds oracle coverage;
- deterministic ranking is already sufficient;
- failures originate in perception, grounding, terminal witness, or control
  rather than selection.

Training a ranker cannot repair a missing good candidate.

It cannot repair false sidewalk geometry.

It cannot repair owner identity.

It cannot repair the exact-zero path.

### 15.2 Mandatory go/no-go gates

| Gate | GO evidence | NO-GO consequence |
| --- | --- | --- |
| T-G1 shared P0 | Every prerequisite in Section 1.3 is green | no active learned motion layer |
| T-G2 stable ABI | World, proposal, pool, mask, batch, rank, commit, and witness schemas frozen | collect no training corpus yet |
| T-G3 candidate sampler | Stable bounded K candidates with replay and source diversity | no ranker project |
| T-G4 oracle gap | An offline oracle selecting admitted candidates materially beats deterministic selection on frozen failures | improve generators, not ranker |
| T-G5 sufficient data | Representative shadow batches include rare hazards, holds, owner/social cases, and recovery | continue collection |
| T-G6 label quality | Inter-rater agreement and simulator outcome labels meet declared thresholds | redesign labels |
| T-G7 no leakage | Product inputs mechanically exclude oracle/future state | invalidate dataset |
| T-G8 licensing | Every training input, checkpoint, dependency, and output-use right is approved | use deterministic/cleared sources only |
| T-G9 compute fit | Training and inference memory/latency are measured in pinned images | do not schedule or deploy |
| T-G10 safety neutrality | Ranker cannot affect masks, task authority, or final monitor | reject architecture change |
| T-G11 evaluation power | Scenario count can detect declared regressions | gather more runs |
| T-G12 maintenance owner | Named owner for data drift, calibration, and rollback | no production ranker |

“Materially” is declared before the experiment.

An initial research threshold may be a five-percentage-point success gap on the
frozen hard-case suite with no safety regression, but the review must also
specify confidence intervals and minimum sample size.

The threshold is not retrofitted after results.

### 15.3 Narrow learning target

If every gate passes, train only:

~~~text
input:
  one CandidateBatchV1 with K admitted candidates + HOLD

output:
  a categorical preference distribution over those K+1 IDs
  an abstention estimate
  uncertainty / OOD signals
~~~

Do not train:

- residual body velocity;
- correction twist;
- steering angle;
- gait;
- joint target;
- collision-mask override;
- goal coordinates from language;
- task interruption policy.

### 15.4 Data record

Each shadow decision record contains:

- run and episode ID;
- scenario manifest and seed;
- software/config/model/artifact digests;
- robot and safety profiles;
- full product-visible state references;
- candidate pool and full mask report;
- deterministic selection;
- shadow rank selection;
- operator preference if solicited;
- executed candidate;
- intervention and stop events;
- trajectory outcome;
- terminal witness;
- counterfactual simulator rollout IDs;
- all component latency spans;
- oracle-only fields in a physically separate labeled partition.

Raw personally identifying RGB/audio follows the project retention policy.

Ranker features should prefer derived bounded representations.

### 15.5 Label hierarchy

Labels are constructed in this order:

1. hard-invalid candidates are removed, never merely labeled “bad”;
2. simulator counterfactual outcomes provide collision/progress evidence;
3. deterministic oracle search provides best-achievable candidate outcome;
4. human pairwise preferences label social comfort among safe outcomes;
5. operator interventions label unsafe-looking or confusing behavior;
6. DAgger collects states induced by the current selector;
7. ambiguous examples are retained with uncertainty or excluded by policy.

Human preference never labels a masked collision candidate acceptable.

### 15.6 Dataset splits

Split by:

- city/interior scene;
- route topology;
- obstacle layout;
- pedestrian script family;
- owner identity and appearance;
- lighting/weather domain;
- camera/LiDAR corruption pattern;
- instruction paraphrase family;
- collection day and model version.

Near-duplicate candidate pools remain in one split.

Frame-level random splits are forbidden.

The test suite is frozen before tuning.

### 15.7 Training ladder

1. deterministic scorer baseline;
2. supervised multiclass behavior cloning from oracle/safe preferences;
3. pairwise ranking loss for social choices;
4. calibrated abstention head;
5. DAgger in simulator with hard masks;
6. conservative offline/preference learning only if BC plateaus;
7. optional shielded simulator RL only if it solves demonstrated recovery or
   dynamic interaction gaps unavailable in the prior stages.

No physical online exploration is allowed.

No RL reward can grant motion outside the candidate set.

### 15.8 Reward, if the final gate permits simulator RL

Reward components may include:

- terminal task success;
- safe progress;
- follow formation quality;
- social comfort;
- smoothness;
- reduced oscillation;
- justified wait;
- recovery success;
- calibrated abstention.

Hard collision, forbidden-region, authorization, and identity constraints
remain shields, not reward terms.

Reward hacking tests include:

- freezing forever;
- orbit-angle shortcut;
- cutting a road corner;
- selecting short but socially invasive paths;
- exploiting simulator-perfect labels;
- rapidly switching candidates;
- farming progress without reaching the goal.

### 15.9 Compute budget

The audited desktop has an RTX 5000 Ada with 32 GB VRAM.

The active Parcel environment did not contain Torch at audit time.

Neither fact proves training or co-resident inference fit.

If gates pass, cap the first experiment program at 120 single-GPU hours:

- up to 16 hours supervised/DAgger pilots;
- up to 36 hours across three RL seeds, only if authorized;
- up to 48 hours ablations;
- the remainder for frozen replay and calibration.

Stop early when the predeclared hypothesis is falsified.

---

## 16. Evaluation and promotion

### 16.1 Evidence ladder

| Rung | Evidence class | Purpose |
| --- | --- | --- |
| E0 | schema/contract smoke | Serialization, exact fields, digest and expiry semantics |
| E1 | synthetic unit/property/fuzz | Masks, transforms, deadline races, malformed models |
| E2 | product headless integration | utterance → PlanIR → executive → candidate system → controller → independent witness |
| E3 | frozen Parcel dynamic-city suite | Sidewalk, lamppost, orbit, follow, crowd, recovery |
| E4 | external proxy/public benchmark | BARN, Follow-Bench, Habitat-style instruction tasks as scoped adapters |
| E5 | richer dynamic simulator | MetaUrban/HuNavSim-class social and city scenes after adapter validation |
| E6 | hardware-in-the-loop | Real timing and controller feedback without free roaming |
| E7 | supervised physical ODD | Bounded course, safety operator, narrow role |

Passing a lower rung does not imply a higher rung.

Author-reported paper results remain source context, not Parcel scores.

### 16.2 Product-path headless tests

Every integration scenario enters through the same product API used by the UI
or voice route.

Required scenarios include:

- “walk to the sidewalk” from road-adjacent poses;
- paraphrased danger explanation;
- sidewalk occluded or unreachable;
- multiple sidewalk regions;
- “wait by the lamppost” with several poles;
- lamppost next to a road;
- one full owner orbit with obstacles;
- orbit interrupted by a pedestrian;
- “follow behind me” with turns and acceleration;
- short and long owner occlusion;
- similar-clothes distractor crossing;
- “walk away five steps” with and without rear coverage;
- explicit stop during every pipeline stage;
- task correction during ranker inference;
- frame-epoch change during commitment;
- LiDAR dropout;
- camera dropout;
- dynamic tracker dropout;
- ranker OOM, crash, malformed ID, NaN, and deadline miss;
- all candidates masked;
- terminal evidence expiry during dwell;
- low-battery safe pose while on a road versus in a safe region.

### 16.3 Metrics

#### Safety and authority

- collision count and rate;
- contact severity proxy;
- minimum static clearance;
- minimum person clearance;
- minimum TTC;
- forbidden-region entry;
- unauthorized road/crossing entry;
- exact-zero same-tick stop compliance;
- watchdog stop count;
- stop-confirmation latency;
- stale-evidence motion count;
- identity-switch count;
- masked-candidate execution count, required zero.

#### Task quality

- independently witnessed task success;
- success weighted by path length;
- time to terminal witness;
- path efficiency;
- semantic grounding success;
- acceptable-region occupancy;
- relation error;
- orbit completion error;
- MoveRelative displacement error;
- failure reason calibration;
- clarification rate.

#### Follow and social quality

- formation distance error;
- behind-heading error;
- owner lost time;
- reacquisition time;
- distractor switch rate;
- personal-space violation duration;
- group split rate;
- pass-side oscillation;
- unnecessary wait rate;
- owner visibility fraction.

#### Motion quality

- lateral distance fraction;
- reverse distance fraction;
- heading-before-translation compliance;
- integrated jerk;
- angular acceleration;
- stop/start count;
- path curvature;
- candidate-switch rate;
- recovery count and recovery distance.

#### Candidate-system quality

- candidates per batch;
- unique homotopy classes;
- per-source availability;
- per-source admission rate;
- mask reason distribution;
- candidate oracle success;
- candidate oracle gap over frozen baseline;
- selected regret to oracle;
- deterministic-versus-ranker disagreement;
- ranker top-1 accuracy where labels exist;
- abstention rate;
- abstention precision on failure/OOD;
- calibration error;
- fallback rate;
- HOLD precision and unnecessary-HOLD rate.

#### Latency and resource quality

- UserQueryEndToFirstReasoningResponse;
- UserQueryEndToFirstResponse;
- transcript-final to TaskRequest;
- TaskRequest to validated PlanIR;
- PlanIR to grounded GoalRegion;
- state assembly;
- per-proposer inference;
- normalization;
- hard mask pass 1;
- rank request/response;
- hard mask pass 2;
- selection to first body target;
- body target to backend send;
- backend send to measured motion;
- stop intent to zero command;
- stop intent to feedback-confirmed stop;
- p50, p95, p99, maximum, deadline-miss count;
- CPU, GPU, VRAM, RAM, queue depth, dropped snapshots, and thermal throttling.

### 16.4 Candidate attribution experiment

Every paired run records four outcomes:

1. frozen single-route baseline;
2. deterministic multi-candidate selector;
3. deterministic selector plus open-weight proposals;
4. shadow or active learned ranker over the same admitted batch.

This isolates:

- generator improvement;
- ranker improvement;
- controller improvement;
- scenario noise.

Changing masks, speed, or terminal witness in only one arm is forbidden.

### 16.5 Offline replay

Every recorded batch is replayable without simulator or robot.

Replay asserts:

- byte-identical normalization;
- byte-identical mask verdicts under the same version;
- canonical candidate ordering;
- deterministic baseline selection;
- ranker output under pinned artifacts;
- deadline and stale-state outcomes under injected timing;
- no oracle feature leakage.

### 16.6 Promotion gates

A component moves from SHADOW to ACTIVE only when:

- all safety invariants remain zero-violation with statistical bounds declared;
- terminal success improves on the frozen target suite;
- p99 latency fits the measured deadline budget;
- model absence is no worse than the deterministic baseline;
- OOD/abstention behavior is calibrated;
- resource co-residency is profiled with duplex audio and reasoning active;
- artifact and transitive licenses are approved;
- rollback is one restart-bound flag;
- scenario and evidence manifests are reproducible;
- independent reviewers sign the exact role and ODD.

Top-10-percentile external standing is a program objective.

It is not claimed until an official or faithful frozen adapter produces
comparable metrics.

No benchmark score can waive product-path safety or embodiment constraints.

### 16.7 Kill criteria

Stop or demote the predictive layer if:

- candidate oracle coverage does not exceed the deterministic baseline;
- ranker cannot beat deterministic selection across held-out scenes;
- improvement depends on simulator-only features;
- abstention is poorly calibrated;
- p99 rank latency causes control freshness loss;
- candidate switching worsens comfort or safety;
- open-weight source licensing remains unclear;
- GPU contention degrades audio or safety telemetry;
- active failure degradation differs from ranker-OFF behavior;
- maintenance cost exceeds the demonstrated task gain.

---

## 17. Deployment isolation and resource scheduling

### 17.1 Process layout

~~~text
Safety/control process, CPU pinned
  - authority arbiter
  - deterministic hard mask
  - selector and commit leases
  - local tracker
  - outgoing geometry monitor
  - ControlManager
  - no GPU dependency

State assembly process
  - calibrated sensor ingest
  - immutable shared-memory snapshots
  - transform/freshness/evidence manifests

Deterministic proposal workers
  - grid variants
  - RPP family
  - optional reviewed MPPI sampler

One sandbox per open-weight proposer
  - read-only artifact mount
  - no network
  - no credentials
  - no Unitree/HAL device
  - bounded shared memory and IPC

Optional ranker process
  - latest-only CandidateBatch queue
  - no raw sensor access unless its contract declares it
  - no HAL

Voice/conversation services
  - separately scheduled
  - cannot starve safety/control
~~~

### 17.2 IPC rules

- fixed versioned envelopes;
- explicit maximum message size;
- immutable shared-memory handles for images/maps;
- copy bounded candidate features into rank requests;
- queue depth one for real-time model work;
- newest matching revision supersedes older work;
- sender and receiver validate;
- monotonic timestamps only for deadlines;
- process boot IDs prevent stale replay after restart;
- CRC or digest detects partial/corrupt payload;
- unknown field rejects;
- no pickle across trust boundaries;
- no arbitrary Python object deserialization;
- no remote code in the safety/control process.

### 17.3 GPU scheduling

Safety does not require the GPU.

GPU work is assigned in this initial priority:

1. metric perception required by the active ODD;
2. owner/dynamic tracking required by the active task;
3. duplex audio with its user-facing streaming deadline;
4. small ranker, if active and profiled;
5. local learned proposer;
6. slow semantic/instruction research model.

Priority here is a scheduling policy proposal, not proof that these workloads
fit together.

Each service receives:

- measured peak VRAM budget;
- maximum inference concurrency;
- deadline;
- preemption or skip policy;
- warmup policy;
- thermal and OOM telemetry;
- restart limit.

No two large models are declared co-resident until measured in the exact pinned
deployment image.

### 17.4 Desktop versus onboard

The desktop can host research proposers and training.

The physical dog must retain a local deterministic navigation and STOP path.

A desktop or network-delivered proposal is advisory and short-TTL.

Network loss cannot leave a long trajectory executing.

For onboard deployment:

- profile the actual Unitree compute and power budget;
- choose one useful learned source, not every research model;
- quantize only after parity testing;
- preserve the same proposal ABI;
- preserve deterministic masks and fallback;
- never make conversational availability a locomotion prerequisite.

### 17.5 Artifact security

Every model manifest includes:

- canonical source URL;
- repository commit;
- weight digest and byte size;
- loader digest;
- dependency lock;
- license/SPDX evidence;
- custom-code flag;
- trust_remote_code use;
- network policy;
- tested camera/history contract;
- device/dtype/quantization;
- measured latency and memory;
- allowed role;
- prohibited claims;
- rollback ID.

MiniCPM and converted CityWalker loaders that execute custom code require a
reviewed sandbox.

Downloaded artifacts remain disabled until their manifest is approved.

---

## 18. Observability and review traces

### 18.1 SelectionTraceV1

One trace joins the complete decision:

~~~text
SelectionTraceV1
  run_id / episode_id / turn_id
  task_id / revision / step_id / goal_id
  snapshot_id / frame_epoch / evidence manifest
  pool_id / candidate IDs / source health
  pass-1 mask verdicts
  deterministic selection
  rank request and response or absence
  abstention/OOD/deadline state
  hysteresis decision
  pass-2 verdict
  commit lease
  tracker reference
  post-shaper command
  final monitor result
  controller feedback
  progress and terminal witness
  component trace spans
~~~

### 18.2 Dashboard

The existing latency dashboard should add a candidate panel:

- active task, revision, step, and goal;
- current selector mode;
- current selected candidate/source;
- HOLD/fallback reason;
- candidate count and unique homotopy classes;
- per-source availability and latency;
- mask-reason histogram;
- deterministic versus learned disagreement;
- rank confidence/abstention/OOD;
- candidate switch history;
- current commitment time remaining;
- current static/person clearance and TTC;
- e2e voice-to-reasoning and voice-to-first-response;
- task-to-first-motion and stop-to-zero timings.

Sensitive raw audio/images need not be rendered or retained.

### 18.3 Alerts

Page or hard-disable learned ACTIVE on:

- masked candidate selected;
- task/revision mismatch;
- repeated deadline misses;
- rank response from wrong batch;
- OOD rate above policy;
- unexpected GPU OOM;
- post-shaper nonzero on a stop tick;
- model absence changing deterministic fallback;
- stale-evidence motion;
- artifact digest mismatch.

---

## 19. Implementation plan

### 19.1 Phase C0 — shared truth and safety

Deliver before predictive work:

1. exact-zero post-shaper monitor;
2. dimensionally correct person envelope;
3. product missing-sensor HOLD;
4. transform epoch and covariance health;
5. atomic suspend/resume;
6. ApproachOwner versus FollowFormation split;
7. independent terminal witnesses;
8. frozen product-path baselines.

Exit:

- every P0 regression is green;
- no predictive component can be enabled by config.

### 19.2 Phase C1 — ABI and recorder

Implement:

- WorldStateSliceV1;
- HistoryBundleV1;
- NavProposalV1;
- CandidateV1;
- CandidatePoolV1;
- HardMaskVerdictV1;
- CandidateBatchV1;
- RankDecisionV1;
- CommitLeaseV1;
- SelectionTraceV1;
- strict serialization and fuzz tests.

Exit:

- deterministic replay is byte stable;
- oracle fields cannot enter the product contract;
- old revision and frame-epoch races fail closed.

### 19.3 Phase C2 — deterministic candidates

Implement:

- current grid route adapter;
- grid variant generator;
- geometry normalization;
- deduplication/source quotas;
- RPP rollout family;
- deterministic selector;
- HOLD and commitment leases;
- common tracker integration.

Exit:

- deterministic multi-candidate system equals or exceeds the frozen baseline;
- ranker remains absent;
- all failure injections degrade safely.

### 19.4 Phase C3 — hard-mask library

Implement:

- static swept-footprint mask;
- unknown/coverage mask;
- kinematic mask;
- dynamic occupancy/TTC mask;
- owner/formation mask;
- road/crossing policy mask;
- task/revision/lease/deadline mask;
- pass-2 commit revalidator.

Exit:

- property/fuzz tests cover every reason code;
- mask errors cannot permit motion;
- pass-1/pass-2 race suite is green.

### 19.5 Phase C4 — social and recovery candidates

Implement:

- formation goal sampler;
- enrolled identity state integration;
- owner prediction uncertainty;
- social soft features;
- bounded recovery state machine;
- dynamic re-ranking and hysteresis.

Exit:

- Follow-Bench oracle and sensor-product lanes are reported separately;
- owner distractor and occlusion gates pass;
- recovery never reverses without fresh coverage.

### 19.6 Phase C5 — MPPI feasibility

Time-box:

- inspect supported Nav2 interfaces;
- prototype stable candidate export;
- measure K diversity, determinism, cost, and latency;
- compare to grid/RPP candidates;
- document dependency and upgrade burden.

Exit:

- promote a reviewed stable adapter;
- or reject MPPI as a K-source and retain it only as a comparator.

This phase may be terminated without blocking C2–C4.

### 19.7 Phase C6 — open-weight shadows

Order:

1. MiniCPM-RobotTrack after core plus gated/transitive dependency review;
2. CityWalker after asset/license/loader review;
3. CE-Nav after artifact/dependency/Isaac review;
4. X-NavDP only after legal resolution;
5. InternVLA/NaVILA in isolated approved research only.

For each:

- acquire through a manifest;
- sandbox;
- wire exact observation history;
- produce NavProposalV1;
- run offline frozen data;
- run SHADOW_PROPOSERS;
- report availability, admission, oracle contribution, latency, VRAM, and
  failure degradation.

Exit:

- no source is promoted merely for matching an author benchmark.

### 19.8 Phase C7 — ranker decision

Compute:

- deterministic selected success;
- candidate oracle success;
- oracle gap;
- per-source marginal coverage;
- social preference disagreement;
- data coverage and power.

If no material oracle gap exists:

- stop;
- retain deterministic selection;
- improve grounding, perception, or generators.

If a material gap exists and every training gate passes:

- train the bounded K+1 ranker;
- keep it SHADOW.

### 19.9 Phase C8 — ranker shadow and simulator activation

Implement:

- inference sandbox;
- deadline/freshness validation;
- calibrated abstention;
- OOD checks;
- disagreement dashboards;
- paired frozen evaluation;
- rollback switch.

Promote first to ACTIVE_RANKER_SIM only.

Exit:

- predeclared improvements hold across unseen scene families and seeds;
- no safety/latency/failure-degradation regression.

### 19.10 Phase C9 — HIL and supervised physical course

Requirements:

- exact device and model co-residency profile;
- no-network deterministic operation;
- supervised stop tests;
- owner identity enrollment protocol;
- calibrated camera/LiDAR transforms;
- narrow ODD and speed regime;
- physical candidate-prefix validation;
- independent observer and rollback.

ACTIVE_RANKER_PHYSICAL requires a separate review.

It is not an automatic continuation of simulator activation.

### 19.11 Proposed code ownership

| Area | Proposed package/file boundary |
| --- | --- |
| contracts | src/parcel_robot/contracts/predictive_v1.py |
| state assembly | src/parcel_robot/navigation/world_state.py |
| history | src/parcel_robot/navigation/history_buffer.py |
| proposal ingress | src/parcel_robot/navigation/proposals/ingress.py |
| grid candidates | src/parcel_robot/navigation/candidates/grid_family.py |
| RPP candidates | src/parcel_robot/navigation/candidates/rpp_family.py |
| MPPI sidecar | src/parcel_robot/navigation/candidates/mppi_sidecar.py |
| social candidates | src/parcel_robot/navigation/candidates/social_family.py |
| recovery candidates | src/parcel_robot/navigation/candidates/recovery_family.py |
| normalization | src/parcel_robot/navigation/candidates/normalize.py |
| dedup/quota | src/parcel_robot/navigation/candidates/pool.py |
| hard masks | src/parcel_robot/navigation/admission/ |
| deterministic selector | src/parcel_robot/navigation/selection/deterministic.py |
| learned rank adapter | src/parcel_robot/navigation/selection/ranker_client.py |
| commitment | src/parcel_robot/navigation/selection/commit.py |
| terminal witnesses | src/parcel_robot/brain/witnesses/ |
| trace/metrics | src/parcel_robot/observability/navigation_trace.py |
| model sandboxes | services/navigation_proposers/ |
| ranker sandbox | services/navigation_ranker/ |
| offline replay | evals/predictive/replay/ |

Names are proposed boundaries.

They are not authorization to perform the refactor in this design task.

### 19.12 Test ownership

| Test layer | Proposed target |
| --- | --- |
| schema | tests/contracts/test_predictive_v1.py |
| fuzz ingress | tests/navigation/test_proposal_ingress_fuzz.py |
| hard masks | tests/navigation/admission/ |
| deadline races | tests/navigation/test_predictive_deadlines.py |
| revision races | tests/navigation/test_predictive_revision.py |
| candidate replay | tests/navigation/test_candidate_replay.py |
| ranker failure | tests/navigation/test_ranker_fail_closed.py |
| owner/social | tests/navigation/test_predictive_follow.py |
| terminal witness | tests/brain/test_terminal_witnesses.py |
| product path | tests/integration/test_predictive_product_path.py |
| external adapters | evals/external/*/parcel_adapter.py |

### 19.13 Parallel work

After C1 schemas freeze, these tracks can proceed independently:

- grid/RPP candidate family;
- hard static/kinematic masks;
- dynamic/social mask and formation goal;
- terminal witnesses;
- recorder/replay/dashboard;
- MPPI feasibility spike;
- open-weight legal/artifact review;
- product headless scenario authoring.

The learned ranker cannot begin before those tracks produce stable data.

Physical activation cannot proceed in parallel with unresolved P0 gates.

---

## 20. Comparison with the other full-stack alternatives

### 20.1 Versus Design A — deterministic companion

Shared:

- typed instruction/task path;
- independent semantic grounding;
- classical planning and collision authority;
- exact-zero final monitor;
- Unitree Sport;
- independent terminal witnesses;
- fail-closed sensing and transforms.

Design C adds:

- multiple local trajectory candidates;
- normalized candidate/pool contracts;
- explicit oracle-coverage measurement;
- optional open-weight proposal sources;
- optional learned discrete ranker;
- counterfactual and selection-regret evaluation;
- more process/GPU isolation.

Design A wins when:

- the ODD is narrow;
- deterministic planning already passes the scenarios;
- compute and assurance budgets are constrained;
- candidate oracle gap is small;
- auditability dominates long-tail social optimization.

Design C wins only when:

- hard dynamic/social scenes contain genuinely different safe options;
- at least one good option is regularly missed by single-route selection;
- a bounded selector demonstrably chooses better without degrading failure
  behavior.

Design C must retain Design A as its baseline and fallback.

### 20.2 Versus Design B — dual-system semantic companion

Shared:

- fast deterministic safety and common-command lane;
- asynchronous conversation/reasoning;
- typed PlanIR;
- learned systems as bounded proposers;
- deterministic grounding and terminal truth;
- no language-to-motor path.

Design B primarily uses the learned system to improve:

- instruction interpretation;
- semantic grounding;
- long-horizon task decomposition;
- dialogue and companion behavior.

It then hands one authorized goal to a deterministic navigation spine.

Design C additionally places a bounded learned choice inside local navigation:

- multiple already-admitted local trajectories;
- discrete index or abstention;
- short commitment and immediate revalidation.

Design B wins when:

- current failures are mainly language/semantic;
- one strong deterministic planner handles local geometry;
- lower systems complexity and GPU pressure matter;
- training data for local ranking is weak.

Design C wins when:

- local dynamic/social choice remains the measured bottleneck after Design B’s
  semantics are fixed;
- deterministic candidate diversity exposes an actionable oracle gap;
- the ranker meets calibration and latency gates.

The two concepts are compatible at a component level.

For team review, however, Design C is a complete alternative because it accepts
the additional local predictive machinery and assurance burden as a core
product direction.

### 20.3 Honest recommendation

The strongest initial product choice is likely the dual-system semantic design
with Design A’s deterministic motion spine.

Design C should be developed as:

- the candidate ABI;
- a deterministic multi-candidate experiment;
- an open-weight shadow harness;
- an eventual bounded ranker only if evidence demands it.

If C’s oracle and selection gains remain small, do not ship its learned layer.

That result would be a successful falsification, not a failed project.

---

## 21. Risks, mitigations, and falsifiers

| Risk | Why it matters | Mitigation | Falsifier / stop condition |
| --- | --- | --- | --- |
| Candidate illusion | Many near-duplicates look like diversity | geometric/homotopy dedup and source quotas | oracle coverage unchanged |
| MPPI private API | Upgrade breaks K export | reviewed stable adapter or abandon K role | no stable bounded replay |
| Ranker learns source brand | Chooses model rather than geometry | source dropout, ablation, held-out sources | quality collapses when source labels hidden |
| HOLD collapse | Conservative model freezes | separate safety mask from preference; measure unnecessary HOLD | task quality cannot improve without unsafe threshold |
| Unsafe optimism | Soft clearance score substitutes for masks | mask before and after rank | any masked execution |
| Stale trajectory | Dynamic scene changes inside horizon | short commitment, every-tick monitor | stale-prefix incident |
| Task leakage | Candidate from old instruction executes | exact revision/hash checks | any revision-race motion |
| Oracle leakage | Simulator future enters training | physical channel separation and audits | held-out product lane collapses |
| Identity switch | Follow model chases distractor | enrolled posterior external to proposer | nonzero distractor switch beyond bound |
| Social oscillation | Left/right choices thrash | dwell, hysteresis, pass-side memory | switch/jerk regression |
| Latency contention | Voice and nav models share GPU | priority, quotas, latest-only, profile | safety/audio p99 regression |
| License ambiguity | Good research model cannot ship | manifest and legal gate per artifact | rights unresolved |
| Custom-code compromise | Model loader executes arbitrary code | offline sandbox/no credentials/HAL | sandbox escape or unverifiable loader |
| Terminal gaming | Ranker drives near a point, claims success | independent region/relation witness | witness mismatch |
| Benchmark overfit | Score rises, companion quality falls | product path primary; frozen unseen scenes | external-only gain |
| Recovery escalation | Repeated motion makes trap worse | explicit state and distance/attempt budgets | recovery worsens collision/progress |
| Lateral slide | Selector exploits holonomy unnaturally | ordinary lateral/reverse penalties and alignment rule | comfort/energy regression |
| Stop shaping | nominal comfort delays zero | independent exact-zero post-shaper monitor | any same-tick nonzero |
| Person envelope units | false assurance in masks | dimensional analysis and shared authority | dimensional test fails |
| Model monoculture | all learned candidates share failure | deterministic sources mandatory | learned-source outage changes safety |
| Maintenance burden | contracts/services outgrow value | phase exits and kill criteria | gain below declared threshold |

### 21.1 Architecture falsifiers

Design C’s learned ranker should be rejected if any of these remain true after
the deterministic candidate phase:

1. candidate oracle success is not materially above deterministic selection;
2. most failures are missing semantic/metric evidence rather than route choice;
3. a tuned deterministic scorer matches the learned ranker;
4. selection improvement disappears on unseen city/interior families;
5. required compute harms duplex conversation latency;
6. abstention is not reliable under sensor corruption;
7. active failure degradation differs from deterministic-only behavior;
8. artifact terms prevent the useful candidate sources from shipping.

### 21.2 Open questions to answer with experiments

- Does grid plus RPP produce enough useful homotopy diversity?
- Can a stable reviewed MPPI sampler export K candidates at the needed rate?
- Which candidate horizon best trades foresight against dynamic staleness?
- Does MiniCPM add owner-follow oracle coverage after independent identity and
  geometry masks?
- Does CityWalker add urban-route coverage beyond grid/OSM on Parcel cameras?
- Is CE-Nav useful after normalization to the common body/tracker contract?
- Which soft social features predict human preference across cultures and
  contexts without shrinking hard person zones?
- Can a small CPU ranker match a GPU ranker?
- Does learned ranking add value beyond deterministic lexicographic selection?
- What is the measured desktop co-residency envelope with audio and reasoning?
- What subset, if any, fits the eventual onboard compute and power budget?

---

## 22. Review checklist

The team should not approve implementation until it can answer yes to:

- [ ] Unitree Sport remains the gait/balance authority.
- [ ] No proposal or ranker path can emit velocity or Unitree commands.
- [ ] HOLD is explicit and exact-zero is enforced after shaping.
- [ ] Missing required LiDAR/depth, pose, transform, dynamic state, or feedback
      fails closed.
- [ ] Every proposal binds task ID, revision, step, goal, snapshot, frame epoch,
      evidence, TTL, and artifact digest.
- [ ] Every candidate is a bounded timed SE(2) pose sequence.
- [ ] Hard masks run before ranking and immediately before commitment.
- [ ] Ranker output is only one admitted ID or abstention.
- [ ] A stale or malformed response cannot select a candidate.
- [ ] Deterministic selection and no-model operation remain supported.
- [ ] Owner identity is enrolled/multi-frame and external to navigation models.
- [ ] Formation goals route through common collision planning.
- [ ] ApproachOwner terminates and FollowFormation stays persistent.
- [ ] Affect reactions cannot interrupt critical base work.
- [ ] Recovery is state-authorized, bounded, and rear-coverage-aware.
- [ ] Terminal success comes from independent region/relation witnesses.
- [ ] External maps and learned priors cannot authorize road entry.
- [ ] Stock MPPI is not claimed to expose K until the spike proves it.
- [ ] Current model licensing and wiring status is represented honestly.
- [ ] Training remains NO-GO until candidate oracle gap and all gates pass.
- [ ] No physical online RL or residual velocity RL is proposed.
- [ ] Product-path and external evals use frozen manifests and paired controls.
- [ ] GPU co-residency is measured rather than inferred from VRAM size.
- [ ] Rollback to deterministic-only is restart-bound and tested.

---

## 23. Bottom line

Design C’s innovation is not “let an AI drive the dog.”

It is a disciplined decomposition:

1. understand and validate the owner’s request;
2. ground it into a sensor-supported goal region;
3. generate several bounded local alternatives;
4. eliminate every inadmissible alternative deterministically;
5. choose one survivor with a deterministic selector first;
6. optionally learn only that bounded choice after evidence justifies it;
7. revalidate and commit only a short prefix;
8. enforce independent geometry and exact-zero stop below it;
9. let Unitree Sport keep gait and balance;
10. verify success independently.

This can produce a more anticipatory and socially natural companion without
turning language, an open-weight model, or a learned critic into motor
authority.

It also gives the project a clean answer if custom learning is unnecessary:
keep the candidate ABI, deterministic diversity, evaluation harness, and
shadow proposers; decline the ranker.

That is the required safety and engineering posture for a high-stakes
predictive companion.
