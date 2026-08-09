# Design A — Deterministic Companion

**Status:** Proposed for team review  
**Date:** 2026-08-08  
**Decision class:** Full-stack alternative A  
**Safety status:** Design only; not cleared for unsupervised physical operation  
**Navigation authority:** Deterministic metric pipeline; no learned navigation authority  
**Locomotion authority:** Unitree Sport controller retains gait and balance  

---

## 1. Executive thesis

Build the first production-shaped Parcel dog as a deterministic, inspectable
companion stack. Language and vision may nominate an intent, entity, or semantic
region. They may not declare free space, certify arrival, bypass a stop, or
write body velocity. A typed executive turns accepted intent into a bounded
skill; fresh localization and metric perception ground the skill; `grid_v1`
plans; a regulated path tracker generates a body command; one smoother shapes
comfort; and an independent post-shaper monitor can force exact zero before
`ControlManager` sends a short-TTL setpoint to Unitree Sport.

This is the lowest-ambiguity design against which the other alternatives should
be measured. It deliberately trades some open-ended navigation cleverness for:

- deterministic replay and fault attribution;
- explicit behavior, preemption, and recovery semantics;
- bounded compute and predictable control timing;
- one motion authority and one terminal-witness path;
- an honest path from MuJoCo to supervised Go2 commissioning.

The design is not “no ML.” Camera detection, OCR, open-vocabulary recognition,
speaker recognition, or conversation may use learned models. Perception outputs
are typed, time-bounded evidence; conversation-model output is speech-only or a
shadow task proposal in Design A. Active physical instruction parsing,
planning, trajectory selection, collision permission, task completion, and
motor control remain deterministic.

### 1.1 Primary hypothesis

Most current failures are caused by substrate defects rather than insufficient
model intelligence: residual velocity after a hard stop, open-loop translation
when LiDAR is absent, truth localization, follow bypassing the planner,
ambiguous relation semantics, and incomplete task lifecycle. Closing those
defects and using a common metric planner should yield a larger trustworthy
gain than replacing the navigation stack with a learned policy.

### 1.2 Non-negotiable invariants

1. Only one component owns the active body-velocity lease.
2. Missing, stale, malformed, or frame-invalid required metric evidence means
   `HOLD`, never open-loop translation.
3. Semantic confidence cannot turn occupied or unknown space into free space.
4. Every hard stop is reasserted after all shaping and reaches the software HAL
   boundary as exact `(0, 0, 0)` in the same dispatch.
5. Unitree Sport owns balance, contact sequencing, and gait realization.
6. Learned and external-map outputs stop at a proposal/evidence boundary;
   learned physical-task proposals remain shadow-only in Design A.
7. A task succeeds only from an independent predicate over fresh evidence,
   settled feedback, and the same task revision.
8. `ApproachOwner` terminates; `FollowFormation` persists until cancelled.
9. Lateral velocity is permitted, but forward/turn-first travel is preferred
   for point-to-point navigation.
10. Entering a road requires an authenticated, authorized control decision
    bound to the current curb event; a transcript alone is insufficient.

---

## 2. Scope and non-goals

### 2.1 Goals

- Execute common companion instructions with explicit spatial semantics.
- Navigate around static and moving obstacles using camera and LiDAR evidence.
- Follow an enrolled owner through the same obstacle-aware planner.
- Support manual body control without weakening safety or lifecycle rules.
- React conversationally and physically without interrupting higher-priority
  work unless policy authorizes preemption.
- Run headlessly and deterministically enough for product-path regression tests.
- Preserve interfaces that can later host a different controller or a shadow
  learned proposer without changing behavior contracts.

### 2.2 Non-goals

- Reimplement quadruped balance, foothold planning, or joint control.
- Let an LLM, VLM, RL policy, OSM, GNSS, or Google Maps issue motor commands.
- Claim outdoor/city autonomy from truth-based simulation.
- Autonomously enter roads or infer crossing authorization from speech text.
- Train a general navigation model in this phase.
- Run `grid_v1` and Nav2 simultaneously as competing command writers.
- Use semantic masks as collision geometry.
- Promise a fixed safety distance before measured delay, braking, footprint,
  sensor uncertainty, and clearance conventions are commissioned.

### 2.3 Current-stack anchors

The proposal evolves existing Parcel seams rather than replacing them:

| Existing seam | Retain | Required correction |
| --- | --- | --- |
| `PlanIR` / compiler / validator / `TaskExecutive` | Yes | total relations, revision-scoped invariants, bounded recovery |
| `PoseProvider` with MAP and ODOM roles | Yes | replace production `truth`; add transform health |
| `grid_v1` rolling occupancy and A* | Yes, first writer | fail closed; common formation path; regulated tracking |
| `MidLevelCommand(vx, vy, vyaw, stop, note)` | Compatibility shell | wrap in a versioned command with provenance/TTL |
| velocity shaping | Exactly one instance | hard-stop bypass/reset and post-shaper reassertion |
| `ControlManager` leases and feedback | Yes | commission axes/modes and measure end-to-end stop |
| Unitree Sport `Move` / `SportModeState` | Yes | supervised high-level body velocity only |
| direct follow controller | Temporary compatibility only | replace with formation goals through `grid_v1` |
| crossing state machine | Shape retained | authorization must include speaker/channel identity |

---

## 3. Full component architecture

```text
 AUDIO/TEXT/UI                                      CAMERA + LiDAR + IMU/SPORT
      │                                                       │
      ▼                                                       ▼
 Conversation lane                                  Sensor ingestion / time sync
 (async; may speak; task proposal shadow only)                 │
      │ transcript / shadow TaskProposalV1                     ├── ODOM LIO estimate
      ▼                                                       ├── MAP correction
 Deterministic intent router                                  ├── metric occupancy/elevation
 + schema validator                                           ├── object/region evidence
      │ TaskRequestV1                                         └── owner/person tracks
      ▼                                                       │
 TaskExecutive ───────────────────────────┐                    │
 revision + resource leases              │                    │
      │ SkillInvocationV1                │                    │
      ▼                                  ▼                    ▼
 Skill compiler                    Relation grounder ◄── EvidenceStore
      │                              + GoalRegion sampler
      │                                        │ NavGoalV1
      └────────────────────────────────────────┤
                                               ▼
                                      Goal/route policy gates
                                      crossing + ODD + identity
                                               │
                    ┌──────────────────────────┴────────────────────────┐
                    │ production writer                                │ challenger
                    ▼                                                  ▼
             grid_v1 global/local planner                    Nav2 isolated sidecar
             occupancy + A*/SE(2) candidate                  no shared command lease
                    │ PathV1                                  │ shadow telemetry
                    ▼                                                  │
             Regulated path tracker ◄──────────────────────────────────┘
             turn-first preference, lateral escape allowed
                    │ MotionProposalV1
                    ▼
             deterministic bounds + one comfort smoother
                    │ ShapedCommandV1
                    ▼
             POST-SHAPER METRIC MONITOR
             swept footprint + TTC + stale-source gate
                    │ exact-zero or admitted bounded command
                    ▼
             Motion authority arbiter
             E-stop > hard safety > manual > executive > reaction
                    │ short-TTL VelocityCommand
                    ▼
             ControlManager ── feedback/stop confirmation
                    │
                    ▼
             Unitree Sport Move
             gait + balance + contacts
```

### 3.1 Authority lattice

Higher rows can narrow or cancel lower rows; no row can widen a higher row.

| Priority | Authority | May do | May not do |
| ---: | --- | --- | --- |
| 0 | Physical E-stop / watchdog | latch stop | resume itself |
| 1 | Post-shaper metric monitor | exact zero, lower speed | invent route |
| 2 | ODD/crossing/pose health | veto or hold | mark geometry free |
| 3 | Manual control lease | request bounded velocity | bypass rows 0–2 |
| 4 | Active executive skill | nominate goal/behavior | bypass rows 0–3 |
| 5 | Reaction expression | head/body expression if compatible | take base from critical task |
| 6 | Conversation/model proposal | speak or log a shadow typed task | submit an active physical task or own motion lease |

### 3.2 One-writer rule

`grid_v1` is the initial production navigation writer and the CI reference.
Nav2 is an exclusive challenger: a run selects exactly one local planner by
configuration before activation. In shadow comparison, Nav2 records commands
but cannot obtain a `ControlManager` lease. Authority may migrate only after a
frozen matched A/B and explicit team decision.

---

## 4. Clocks, rates, and deadlines

All internal timestamps are monotonic. Capture timestamps travel with sensor
data; receive timestamps diagnose transport latency. Values below are proposed
starting envelopes, not measured guarantees.

| Layer | Target cadence | Freshness/deadline behavior |
| --- | ---: | --- |
| Unitree Sport internal gait/balance | vendor-owned, high rate | outside Parcel timing authority |
| `ControlManager` feedback/lease loop | 50 Hz | expired command or stale feedback → stop |
| post-shaper safety monitor | 50 Hz, every command | no skip; overrun → exact zero |
| command shaping/path tracking | 20 Hz | missed deadline → hold next dispatch |
| LiDAR metric update | sensor rate, target 10–20 Hz | stale/malformed/frame-invalid → no translation |
| ODOM localization | target ≥20 Hz | `DEGRADED`/`LOST` or stale → hold |
| dynamic person/owner tracking | target 10–20 Hz | expired track → acquire/hold |
| local route replan | 5–10 Hz or event-triggered | retain only fresh collision-checked path |
| global route plan | 1–2 Hz or invalidation | bounded planning deadline; failure → recovery |
| semantic closed-set perception | 5–15 Hz | confidence and TTL required |
| open-vocabulary/OCR query | 0.2–2 Hz | nomination only; timeout → search/clarify |
| executive tick | 10 Hz | per-step and task deadlines |
| instruction compile | event-driven | model timeout → grammar result or hold |
| dialogue/TTS | asynchronous | cannot delay safety/control lanes |

Rules:

- A slower layer publishes immutable snapshots; a faster consumer never blocks
  waiting for it.
- Every consumer checks `captured_at`, `valid_until`, frame, source health, and
  revision.
- Overrun accounting is per component and included in every evaluation run.
- Speech may acknowledge immediately, but it must not claim motion completion
  before the terminal witness commits.

---

## 5. Versioned interfaces

These are implementation-oriented projections of the minimum normative fields
in [`../SHARED_FOUNDATION.md`](../SHARED_FOUNDATION.md). Phase 0 merges them
into one canonical serialization; they are not permission to omit or rename a
shared field. Implementation may use frozen dataclasses first and ROS 2
messages at deployment boundaries. Unknown fields or enum values fail
validation until a compatible schema version is installed.

### 5.1 Shared header

```python
@dataclass(frozen=True)
class HeaderV1:
    schema: str
    event_id: str
    source: str
    captured_at_s: float
    received_at_s: float
    valid_until_s: float
    frame: Literal["MAP", "ODOM", "BASE", "CAMERA", "LIDAR", "NONE"]
    sequence: int
```

Validation requires finite times, `captured <= received`, nonexpired TTL at
use, monotonically increasing sequence per source, and a frame accepted by the
consumer.

### 5.2 User and task contracts

```python
@dataclass(frozen=True)
class SpeakerAuthorizationV1:
    principal_id: str | None
    channel: Literal["voice", "text_ui", "manual_ui", "system"]
    authenticated: bool
    roles: frozenset[str]          # owner, operator, observer
    session_id: str

@dataclass(frozen=True)
class TaskRequestV1:
    header: HeaderV1
    request_id: str
    utterance: str
    speaker: SpeakerAuthorizationV1
    intent: str
    arguments: Mapping[str, JsonScalar]
    confidence: float
    requested_priority: int
    provenance: Literal["grammar", "model_proposal", "manual", "system"]

@dataclass(frozen=True)
class SkillInvocationV1:
    task_id: str
    revision: int
    step_id: str
    skill: str
    arguments: Mapping[str, JsonScalar]
    resources: frozenset[str]
    invariants: tuple[str, ...]
    success_predicate: str
    deadline_s: float
    max_attempts: int
```

The shared schema can represent a model-filled `TaskRequestV1` for comparative
replay, but Design A rejects `model_proposal` provenance from its active
physical-task path. Deterministic validation checks speaker permissions,
intent/argument schema, scene compatibility, ambiguity, and resource policy.
Motor units are not legal task arguments.

### 5.3 State and transform contracts

```python
class Health(Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    LOST = "lost"

@dataclass(frozen=True)
class PoseEstimateV1:
    header: HeaderV1            # MAP or ODOM
    x_m: float
    y_m: float
    yaw_rad: float
    covariance_3x3: tuple[float, ...]
    health: Health
    reset_counter: int

@dataclass(frozen=True)
class TransformV1:
    header: HeaderV1
    parent_frame: str
    child_frame: str
    x_m: float
    y_m: float
    yaw_rad: float
    covariance_3x3: tuple[float, ...]
    health: Health
```

MAP may jump after loop closure; ODOM must remain locally continuous. Local
tracking consumes ODOM. Semantic memory and world goals consume MAP. A goal is
transformed to ODOM from one coherent transform snapshot per tick.

### 5.4 Metric and semantic perception

```python
@dataclass(frozen=True)
class LidarScanV1:
    header: HeaderV1             # LIDAR frame
    ranges_m: tuple[float, ...]
    angle_min_rad: float
    angle_increment_rad: float
    range_min_m: float
    range_max_m: float
    calibration_id: str

@dataclass(frozen=True)
class MetricGridV1:
    header: HeaderV1             # ODOM or MAP, explicitly selected
    resolution_m: float
    origin_xy: tuple[float, float]
    occupancy_log_odds: bytes
    unknown_mask: bytes
    elevation_m: bytes | None
    evidence_ids: tuple[str, ...]

@dataclass(frozen=True)
class SemanticDetectionV1:
    header: HeaderV1
    detection_id: str
    label: str
    confidence: float
    image_bbox_xyxy: tuple[float, float, float, float]
    metric_centroid: tuple[float, float, float] | None
    metric_covariance: tuple[float, ...] | None
    embedding_ref: str | None
    text: str | None

@dataclass(frozen=True)
class EntityTrackV1:
    header: HeaderV1             # MAP for memory; ODOM view attached
    track_id: str
    semantic_label: str
    position_xy: tuple[float, float]
    velocity_xy_mps: tuple[float, float]
    covariance_4x4: tuple[float, ...]
    confidence: float
    observations: int
    identity_state: Literal["unknown", "candidate", "confirmed", "ambiguous"]

@dataclass(frozen=True)
class RegionEvidenceV1:
    header: HeaderV1             # MAP
    region_id: str
    label: str                   # sidewalk, shop entrance, lobby
    polygon_xy: tuple[tuple[float, float], ...]
    confidence: float
    supporting_detection_ids: tuple[str, ...]
    metric_support_ids: tuple[str, ...]
```

`RegionEvidenceV1` labels geometry; it does not create free geometry. Candidate
points must independently pass occupancy, footprint, uncertainty, and route
checks.

### 5.5 Goal, route, and command contracts

```python
@dataclass(frozen=True)
class RelationSpecV1:
    name: str                    # near, next_to, inside, behind, orbit
    reference_entity_id: str
    min_distance_m: float | None
    max_distance_m: float | None
    angular_sector_rad: tuple[float, float] | None
    region_id: str | None
    clearance_m: float
    hold_s: float

@dataclass(frozen=True)
class GoalRegionV1:
    header: HeaderV1             # MAP
    goal_id: str
    relation: RelationSpecV1
    polygon_xy: tuple[tuple[float, float], ...] | None
    center_xy: tuple[float, float] | None
    radius_m: float | None
    admissible_heading_rad: tuple[float, float] | None
    evidence_ids: tuple[str, ...]
    terminal_policy: str

@dataclass(frozen=True)
class NavGoalV1:
    header: HeaderV1             # MAP
    task_id: str
    revision: int
    goal_id: str
    target_xy: tuple[float, float]
    target_yaw_rad: float | None
    goal_region: GoalRegionV1
    priority: int
    allow_lateral: bool
    crossing_event_id: str | None

@dataclass(frozen=True)
class PathV1:
    header: HeaderV1             # coherent MAP path + transform snapshot ID
    task_id: str
    revision: int
    path_id: str
    poses: tuple[tuple[float, float, float | None], ...]
    cost: float
    min_clearance_m: float
    map_revision: int

@dataclass(frozen=True)
class MotionProposalV1:
    header: HeaderV1             # BASE
    task_id: str
    revision: int
    path_id: str
    vx_mps: float
    vy_mps: float
    yaw_rate_rps: float
    tracking_mode: str
    lookahead_m: float

@dataclass(frozen=True)
class SafetyDecisionV1:
    header: HeaderV1
    input_command_id: str
    disposition: Literal["PASS", "LIMIT", "HARD_ZERO", "FAULT"]
    output_velocity: tuple[float, float, float]
    reasons: tuple[str, ...]
    min_predicted_clearance_m: float | None
    min_ttc_s: float | None
    evidence_ids: tuple[str, ...]
```

### 5.6 Feedback and terminal evidence

```python
@dataclass(frozen=True)
class NavFeedbackV1:
    header: HeaderV1
    task_id: str
    revision: int
    state: str
    distance_to_region_m: float
    progress_m: float
    active_path_id: str | None
    stop_commanded: bool
    settled_feedback: bool
    blocking_reason: str | None

@dataclass(frozen=True)
class TerminalWitnessV1:
    header: HeaderV1
    task_id: str
    revision: int
    predicate: str
    satisfied: bool
    held_for_s: float
    pose_evidence_id: str
    geometry_evidence_ids: tuple[str, ...]
    relation_evidence_ids: tuple[str, ...]
    collision_brake_active: bool
    agent_stop_commanded: bool
    control_settled: bool
```

A task cannot consume a witness from another revision. A witness becomes false
on stale evidence, unhealthy transform, active hard brake, lost identity, or
loss of region clearance.

---

## 6. Deterministic instruction compilation

### 6.1 Two-lane interpretation

The active physical lane recognizes a deliberately finite command language.
The slow conversation model may ask or answer naturally and log the same schema
for shadow comparison, but it cannot submit that proposal to Design A's active
executive.

```text
utterance
  → normalize text, retain original, bind speaker/session
  → closed-command recognizer
      emergency stop / stop / pause / resume / cancel / manual release
  → deterministic companion grammar
      approach owner, follow, wait near X, enter region X,
      orbit owner N times, relative steps, sit/stand, look, react
  → if no confident parse: clarification/refusal; optional model proposal is
      recorded in shadow only
  → TaskRequestV1 validator
  → scene/authorization admission
  → skill compiler
  → TaskExecutive
```

Emergency stop is accepted from any channel. Resume, road crossing, ownership
changes, and physical commissioning require authenticated roles. Environmental
OCR is never a command channel.

### 6.2 Intent normalization algorithm

```text
compile_utterance(text, speaker, scene):
  clean = unicode_normalize(lowercase(text))

  if exact_or_high_recall_stop_pattern(clean):
      return TaskRequest(intent="EMERGENCY_STOP", provenance="grammar")

  candidates = deterministic_grammar.parse(clean)

  for c in candidates:
      reject unknown intent or unknown argument
      preserve source quantity and unit
      normalize SI-compatible physical units in trusted code
      defer embodiment units such as `step` to the versioned robot-profile adapter
      reject NaN, negative count, unbounded radius, or motor-level field
      bind deictic references using dialogue focus only as a nomination
      score = grammar_specificity + required_slots_present + scene_support

  best = stable_argmax(score, tie_break=grammar_specificity_then_lexical)
  if no candidate above intent threshold:
      return CLARIFY with missing/ambiguous slots

  admission = authorize(best, speaker, scene, executive_state)
  if admission denied:
      return REFUSE/HOLD with typed reason
  return validated TaskRequestV1
```

The compiler never guesses a metric distance when a command supplies one. It
may use documented embodiment defaults for ordinary language such as “a small
circle” or “next to,” and records which default was applied.

### 6.3 Canonical skill mapping

| User meaning | Skill | Persistence | Base resource |
| --- | --- | --- | --- |
| “come here” | `ApproachOwner` | terminating | exclusive |
| “follow behind me” | `FollowFormation` | persistent | exclusive |
| “wait by the lamppost” | `NavigateRelation` then `HoldPosition` | hold until release/deadline | exclusive |
| “go to the sidewalk” | `NavigateRegion(inside)` | terminating | exclusive |
| “go to the shop” | `NavigateRelation(entrance/inside)` | terminating or clarify | exclusive |
| “circle me once” | `OrbitOwner(revolutions=1)` | terminating | exclusive |
| “back away five steps” | `RelativeTraverse` | terminating | exclusive |
| “sit” | `Posture` | terminating/held pose | posture |
| joke/sad/happy reaction | `React` | opportunistic | expression, maybe posture |

### 6.4 Compiler output

Each skill compiles to a small deterministic behavior tree:

```text
SEQUENCE
  CheckInvariants
  ResolveReferenceOrSearch
  GroundGoalRegion
  RequestRoute
  ExecuteWithRecovery(max_attempts, deadline)
  RequestTerminalStop
  VerifyTerminalPredicate(hold_s)
  ReleaseResources
```

Persistent follow omits terminal completion and loops
`Track → FormGoal → Plan → Execute → VerifyTrack` until cancelled.

---

## 7. Localization and perception evidence

### 7.1 Production localization

Use a two-rate pose architecture behind the existing `PoseProvider`:

- ODOM: LiDAR-inertial odometry, preferably FAST-LIO2 with an external
  Mid-360; Point-LIO is the L1-specific alternative.
- MAP: lower-rate scan-to-map localization and loop corrections.
- Sport state: feedback and an auxiliary consistency signal, not the sole
  world pose.

Provider choice is hardware-dependent and must be decided from bag replay and
commissioning evidence. This design does not claim either algorithm is already
integrated or superior on Parcel hardware.

```text
localization_tick(sensor_bundle):
  require capture-time synchronization within configured skew
  validate calibration IDs and transforms
  odom = lio.update(lidar, imu)
  if lio health/covariance/age outside ODD:
      publish ODOM DEGRADED or LOST
      prohibit translation
  map_correction = scan_match_if_due(odom, map)
  publish MAP and MAP→ODOM transform atomically
  increment reset_counter on discontinuous correction/relocalization
```

Any consumer detecting a changed `reset_counter` invalidates its path and
replans. Terminal dwell resets on any pose discontinuity.

### 7.2 Metric geometry pipeline

```text
for each calibrated LiDAR/depth bundle:
  reject stale, malformed, nonfinite, frame-invalid input
  transform points using capture-time transform
  ray-clear cells only along observed beams
  mark occupied endpoints with log-odds update
  preserve unknown cells as unknown
  estimate elevation/curb geometry when depth/3-D data exists
  decay only dynamic occupancy; do not erase persistent obstacles blindly
  inflate occupied cells by footprint + uncertainty + measured margin
  publish immutable MetricGridV1 with source evidence IDs
```

Planar LiDAR alone cannot establish curb height or all low-obstacle clearance.
The outdoor ODD therefore remains restricted until depth/elevation evidence is
present and evaluated.

### 7.3 Semantic evidence pipeline

```text
camera frame → closed-set detector/tracker (person, owner candidate,
               lamppost, door, storefront, sidewalk boundary)
             → queried open-vocabulary/OCR only when task needs it
             → associate depth/LiDAR support when possible
             → transform centroid/polygon to MAP
             → temporal fusion with confidence decay
             → EvidenceStore
```

Evidence rules:

- A 2-D box without metric support can trigger `SearchEntity`; it cannot create
  a navigation goal behind unobserved geometry.
- Labels decay independently of metric occupancy.
- Multiple similar entities remain separate hypotheses until relational or
  dialogue evidence resolves them.
- Semantic memory stores provenance, covariance, TTL, and last-seen viewpoint.
- OCR text is a label hint, never physical authorization.

### 7.4 Dynamic people tracking

Use constant-velocity Kalman tracks as the deterministic baseline:

```text
predict every track to capture time
associate detections using gated Mahalanobis distance + appearance cost
reject association outside either hard gate
update matched tracks; create tentative unmatched tracks
confirm after N observations across M frames
expire after TTL; keep covariance increasing during brief occlusion
publish position, velocity, covariance, age, identity state
```

Hard collision prediction consumes track uncertainty and raw metric geometry.
Soft social costs may consume semantic “person” labels. Crowd cost is normalized
per cell or by a bounded aggregation such as `max/sum-clipped`; it is never
divided by the total number of tracks in a way that makes a nearby person safer
when a distant track appears.

---

## 8. Relation grounding and candidate goals

### 8.1 One relation registry

Grammar, compiler, grounder, planner, and verifier use the same
`RelationSpecV1`. No layer silently converts `inside`, `next_to`, `behind`, or
`follow` to generic `near`.

| Relation | Candidate set | Required terminal witness |
| --- | --- | --- |
| `inside(region)` | polygon eroded by footprint/clearance | polygon membership with clearance + dwell |
| `near(object)` | free annulus around object | distance band + visibility/identity if required |
| `next_to(object)` | side sectors of free annulus | band + side sector + metric clearance |
| `behind(owner)` | owner-heading-relative annular sector | confirmed owner + band + angle |
| `facing(object)` | free approach poses | position band + yaw error |
| `orbit(owner)` | closed ring waypoints | revolution accumulator + clearance |
| `away_from(owner)` | ray opposite owner bearing | signed projected displacement |

### 8.2 Candidate generation and scoring

```text
ground_relation(spec, evidence, grid, pose):
  reject stale/unhealthy reference evidence
  construct analytic region (annulus, sector, eroded polygon, ring)
  sample candidates at resolution tied to grid resolution
  for each candidate:
      reject unknown or occupied footprint
      reject road/ODD/crossing keepout
      reject insufficient metric support
      reject unreachable candidate under current planner
      compute:
        route_cost
        terminal_relation_error
        clearance_cost
        turn_cost
        social_exposure_cost
        goal_switch_cost
        visibility/interaction_cost
  stable-sort admissible candidates
  return best plus ordered alternatives and evidence IDs
```

Hard rejection precedes soft scoring. Candidate commitment uses hysteresis and
a minimum improvement threshold. Re-ground at a bounded rate or when evidence,
path, identity, or ODD state invalidates the current candidate.

### 8.3 Sidewalk

For “go to the sidewalk”:

1. Resolve a `sidewalk` region from current camera evidence or semantic memory.
2. Erode the polygon by the declared center-to-obstacle clearance convention.
3. Split disconnected safe interiors.
4. Exclude any component requiring unauthorized road entry.
5. Sample reachable inset points, score route length, clearance, pedestrian
   exposure, heading change, and commitment hysteresis.
6. Navigate to the chosen point.
7. If stopped by a person near the final region for a configured dwell, rerank
   alternate safe inset points at approximately 1 Hz. Reranking changes only
   the future goal; it never opens a stop gate.
8. Complete only after fresh polygon membership with clearance, an agent-issued
   stop, settled feedback, clear hard-safety state, and terminal dwell.

### 8.4 Lamppost

For “wait by the lamppost”:

1. Search if no fresh lamppost hypothesis exists.
2. If several are plausible, use dialogue focus/location modifiers or ask.
3. Build a free annulus around the metric-supported pole footprint.
4. Sample side positions, excluding the road and door/flow keepouts.
5. Choose a reachable point normally within the task’s configured vicinity
   band; the exact band is a product default, not a universal law.
6. Verify object identity/track, distance band, road exclusion, clearance,
   stopped feedback, and hold dwell.
7. Enter `HoldPosition`; replan locally only to preserve safety, otherwise wait.

### 8.5 Shop or brand store

`shop` is ambiguous between frontage, entrance, and interior. The compiler uses
the verb and ODD:

- “go to the store” outdoors defaults to a safe entrance/frontage goal.
- “go inside the store” requires an indoor map/door-transition capability;
  otherwise clarify or stop at the entrance.
- Brand/OCR selects a candidate storefront but needs metric support and
  temporal confirmation.
- External maps may nominate a coarse destination. Local sensors must
  re-ground the final entrance and all free space.

---

## 9. Planning algorithms

### 9.1 Planning layers

1. Optional topological route: known footways/rooms/doors; advisory and ODD
   constrained.
2. Global metric route: A* on inflated occupancy for current `grid_v1`.
3. Local tracking: regulated pure-pursuit-style path following with explicit
   forward preference and bounded lateral escape.
4. Independent final monitor: checks the actual shaped command against fresh
   metric geometry.

### 9.2 `grid_v1` route planning

```text
plan(goal, map_snapshot, pose_snapshot):
  require matching healthy frame/transform revisions
  transform goal and start coherently
  inflate hard occupancy by footprint + pose/sensor uncertainty
  build separate soft cost layers:
      unknown, comfort clearance, dynamic people prediction,
      social zones, turn cost, road/ODD keepout
  hard mask = occupied OR invalid OR forbidden edge
  route = deterministic A*(start, admissible_goal_cells,
                           hard_mask, nonnegative_soft_cost)
  if no route before deadline:
      return NO_PATH with frontier/recovery facts
  line-of-sight prune only if every swept segment passes hard mask
  resample at bounded spacing
  calculate min clearance and map revision
  return PathV1
```

Unknown space is a configurable risk class. Physical companion profiles do not
translate into unknown cells. Explicit exploration is a distinct supervised
skill, not a fallback inside ordinary navigation.

### 9.3 Replan triggers

Replan when any of the following occurs:

- goal or task revision changes;
- transform reset counter changes;
- current path intersects new hard occupancy;
- predicted dynamic blockage exceeds its dwell;
- cross-track error exceeds the configured envelope;
- no measured progress within a window;
- relation candidate is invalidated or a hysteresis-qualified alternative is
  materially better;
- crossing state changes.

Periodic replanning exists as a backstop but event triggers dominate.

### 9.4 Turn-first preference with lateral motion available

For a path tangent bearing error `e`:

```text
if abs(e) >= align_enter:
    mode = ALIGN
elif mode == ALIGN and abs(e) > align_exit:
    remain ALIGN
else:
    mode = TRACK

if mode == ALIGN:
    vx = 0
    vy = 0
    yaw_rate = bounded_yaw_controller(e)
else:
    compute regulated forward command
    lateral candidate allowed only if all are true:
      configuration allows lateral velocity
      path geometry or dynamic blockage predicts a material benefit
      abs(e) <= lateral_heading_limit
      lateral swept footprint is metric-clear
      speed <= lateral_speed_cap
    penalize lateral magnitude and lateral acceleration in selection
```

Thus strafing remains available for narrow repositioning, formation correction,
or obstacle avoidance, but it is not the normal way to move toward a point.
Hysteresis prevents repeated ALIGN/TRACK toggling.

### 9.5 Regulated pure-pursuit-style tracking

This is a Parcel implementation inspired by the algorithmic ideas, not a claim
of binary equivalence with Nav2 RPP.

```text
track(path, pose, grid, limits):
  prune path behind closest monotonically advancing index
  L = clamp(L0 + k_v * measured_speed, L_min, L_max)
  target = first path intersection at arc length L
  target_base = transform(target, ODOM → BASE)

  alpha = atan2(target_base.y, target_base.x)
  curvature = 2 * sin(alpha) / max(L, epsilon)

  v_goal = goal_slowdown(distance_to_goal_region)
  v_curve = curve_cap(abs(curvature), lateral_accel_limit)
  v_clear = clearance_cap(predicted_arc_clearance)
  v_ttc = ttc_cap(predicted_dynamic_tracks)
  v = min(cruise, v_goal, v_curve, v_clear, v_ttc, authority_limit)

  omega = clamp(curvature * v, -yaw_limit, yaw_limit)
  if turn_first_gate(alpha): return (0, 0, bounded_yaw_controller(alpha))

  vy = select_lateral_escape_if_admissible(...), normally 0
  forward_speed = sqrt(max(0, v^2 - vy^2))
  return MotionProposal(vx=forward_speed, vy=vy, yaw_rate=omega)
```

Candidate arcs are footprint-swept over the controller horizon. Regulation only
reduces the nominal command. It is not the final safety authority.

### 9.6 Exactly one comfort smoother

The smoother enforces acceleration and jerk comfort limits. It receives a stop
class:

- `COMFORT_STOP`: may ramp to zero within a validated comfort envelope.
- `HARD_STOP`: output exact zero immediately and reset all velocity/acceleration
  state.

No planner-specific smoother may be enabled simultaneously. Nav2 challenger
runs must disable either Nav2 smoothing or Parcel smoothing so there is exactly
one active smoother before the final monitor.

---

## 10. Collision, TTC, and exact-zero logic

### 10.1 Dimensional safety envelope

Use one declared distance convention, proposed as robot-base-center to obstacle
surface, with footprint added exactly once:

```text
d_stop(v) = r_footprint
          + v * tau_total
          + v^2 / (2 * a_brake_measured)
          + z_sensor
          + z_pose

d_person(v_rel) = max(
    d_social_floor,
    d_stop(v_robot) + v_rel_bound * tau_person_extra
)
```

Every term is in metres. The current `person_latency_factor *
reaction_latency_s` addition is dimensionally invalid and must be removed.
`a_brake_measured`, total latency, uncertainty terms, and relative-speed bound
remain unverified until commissioning.

### 10.2 Pre-shaper soft and hard checks

```text
safety_gate(command, evidence):
  if E-stop latched: HARD_ZERO("estop")
  if required pose/transform/scan stale or unhealthy:
      HARD_ZERO("state_unhealthy")
  if command violates ODD/crossing/lease/revision:
      HARD_ZERO("authority_invalid")

  predict swept footprint for each horizon sample
  check static occupancy/unknown policy
  propagate dynamic tracks with covariance inflation
  compute conservative relative TTC for positive closing motion

  if any hard envelope intersected or TTC below hard threshold:
      HARD_ZERO(reasons)
  if within comfort band:
      LIMIT speed; never raise any component
  else PASS
```

Pure rotation still uses a yaw-swept footprint. Lateral movement uses the full
body footprint rather than a front ray. Owner-orbit mode changes the desired
relation; it does not remove the owner collision envelope.

### 10.3 Post-shaper monitor

```text
dispatch_tick(proposal):
  decision_pre = metric_gate(proposal, coherent_snapshot)
  if decision_pre is HARD_ZERO:
      shaped = ZERO
      smoother.reset()
  else:
      shaped = smoother.apply(decision_pre.limited_command)

  decision_final = metric_gate(shaped, newest_coherent_snapshot)
  if decision_final != PASS:
      final = ZERO
      smoother.reset()
  else:
      final = shaped

  assert finite(final)
  if any hard_stop_reason: assert final == (0, 0, 0)
  ControlManager.set_target(final, short_ttl, provenance)
```

The second check is an independent safety monitor, not a second controller or
smoother. If its deadline, evidence, transform, or computation fails, it emits
exact zero. A zero target uses `ControlManager.stop()` and requires settled
feedback before subsequent motion.

### 10.4 Stop classes and recovery

| Reason | Class | Automatic continuation |
| --- | --- | --- |
| E-stop, stale evidence, hard proximity/TTC, road veto | hard | only after explicit gate clears; E-stop requires authorized clear |
| pause/cancel/task expiry | hard lifecycle stop | resume only atomically with task revision |
| arrival | terminal stop | verification then release |
| comfort slowdown / desired wait | regulated/comfort | yes within task |
| planner no-path | exact hold | bounded recovery may propose a new plan |

---

## 11. Owner identity and formation following

### 11.1 Enrollment and identity

Owner enrollment is an explicit authenticated session that captures multiple
camera embeddings/viewpoints and optional speaker identity. Navigation identity
uses camera tracks; voice can help establish interaction context but does not
substitute for a visible spatial track.

```text
owner_update(detections, enrolled_profile, prior_track):
  predict prior track
  calculate motion gate, appearance similarity, continuity, and occlusion age
  if exactly one candidate passes all confirmation gates across N frames:
      state = CONFIRMED
  elif multiple candidates pass or identities cross:
      state = AMBIGUOUS; freeze formation goal; HOLD/ask
  elif brief occlusion within covariance/TTL:
      state = PREDICTED; slow/hold according to ODD
  else:
      state = LOST; HOLD then bounded SearchOwner
```

Never select the nearest person as owner. Reacquisition requires multi-frame
confirmation and continuity or explicit re-enrollment.

### 11.2 Formation goal

For confirmed owner pose `p_o`, velocity `v_o`, and heading unit vector `h_o`:

```text
prediction_horizon = clamp(network+perception+planning delay, H_min, H_max)
p_pred = p_o + v_o * prediction_horizon

behind target = p_pred - follow_distance * h_o
side target   = p_pred + side_sign * side_distance * perpendicular(h_o)
```

Sample a preferred annular sector, reject unsafe candidates, and publish a
short-TTL `NavGoalV1`. `grid_v1` plans to it. The formation sampler owns social
preference; the common planner owns free space.

Formation update uses hysteresis:

- do not replan while inside a hold band;
- reissue only when owner displacement, angle, or path validity crosses a
  threshold;
- cap prediction when the owner accelerates or confidence declines;
- if the owner walks toward the robot, prefer turn/reposition rather than
  reverse blindly into unknown space.

### 11.3 Approach versus follow

`ApproachOwner`:

```text
resolve confirmed owner → sample safe approach band → common planner
→ stop in band facing owner → dwell with settled feedback → SUCCESS
→ release base lease
```

`FollowFormation`:

```text
while authorized and before cancellation:
  require confirmed/fresh owner or enter acquire state
  update formation goal through common planner
  hold inside formation band
  never report terminal success merely because currently in band
```

---

## 12. Primitive spatial behaviors

### 12.1 Walk away a number of steps

“Five steps” is converted to a configured companion step length, recorded in
the task metadata. It does not mean five Unitree gait cycles.

```text
distance = count * nominal_companion_step_m
reference bearing = direction from robot to owner at task acceptance
desired ray = opposite(reference bearing)
candidate = current_position + distance * desired_ray
clip only by task max distance; do not silently change sign
ground candidate to nearest safe point along ray
plan with grid_v1
verify signed projected displacement >= tolerance-adjusted target
```

If the space behind the robot is unknown or occupied, turn to face the travel
direction and move forward. Reverse motion is permitted only for short,
metric-visible, speed-capped repositioning and is not assumed to be safer.

### 12.2 Circle the owner

```text
require confirmed owner and safe orbit radius
radius_min = footprint + owner_envelope + margin
radius = clamp(user_radius_or_default, radius_min, ODD_max)
sample closed ring in MAP at angular spacing tied to curvature/grid resolution
for each segment require swept-footprint route and no road keepout
choose direction by lower route/social cost unless user specified it

execute waypoint ring through common planner
at each tick:
  update owner center slowly with bounded filter
  preserve unwrapped bearing theta around owner
  accumulate only signed, continuous angular progress
  reject jumps during identity ambiguity or relocalization
complete when abs(accumulated_theta) >= 2*pi*N - tolerance
and final relation/clearance/stop/dwell witnesses pass
```

Do not count a spin-in-place as an orbit. If the owner moves too far or identity
becomes ambiguous, pause and re-ground rather than stretching the circle across
the scene.

### 12.3 Look around and identify

`ScanScene` owns yaw but normally not translation:

1. Acquire a safe stationary base state.
2. Rotate through bounded view sectors with exact stop between captures if
   needed for image quality.
3. Fuse detections without duplicating tracks.
4. Return identified evidence or `not_found`; never fabricate a location.
5. A subsequent navigation task must independently ground and plan.

---

## 13. Reactions, posture, and low battery

### 13.1 Reaction admission

Conversation emits an `ExpressionProposalV1` such as chuckle, bow, stretch, or
look-at-owner. A deterministic arbiter evaluates:

```text
if emergency or hard stop transition: reject all optional expression
if active task holds conflicting base/posture resource: defer or vocal-only
if terrain/pose/control health not eligible: vocal-only or no-op
if proposal expired or duplicate in cooldown: drop
otherwise acquire expression resources with bounded duration
```

A sad/happy classification is a proposal, not a guaranteed physical action.
The response may be speech-only while navigating, crossing, recovering, or
holding a critical posture.

### 13.2 Low-battery behavior

Battery behavior is deterministic and independent of the conversation model:

| State | Trigger with hysteresis | Behavior |
| --- | --- | --- |
| NORMAL | above warning threshold | normal policy |
| CONSERVE | below warning threshold | reduce speed, reject optional long tasks, announce once |
| RETURN | below return threshold and route/dock available | preempt ordinary tasks, return through planner |
| SAFE_SIT | below critical threshold or return unavailable | exact stop, verify stable ground, Sport sit, periodic status |
| FAULT | invalid telemetry or unsafe posture | stop; no autonomous recovery requiring translation |

Thresholds need hardware calibration. “Sit to show low battery” is subordinate
to stopping in a safe, metric-clear place; the robot must not sit in a road or
block an unsafe doorway merely for expressiveness.

---

## 14. Task lifecycle, preemption, and state machines

### 14.1 Executive task state machine

```text
                      ┌───────────── clarify/reject ─────────────┐
NEW → ADMITTED → GROUNDING → PLANNING → EXECUTING → VERIFYING → SUCCEEDED
          │          │           │          │           │
          │          │           │          │           └─ witness lost → EXECUTING/HOLD
          │          │           │          └─ blocked → RECOVERING ─┐
          │          │           └─ no path ────────────────────────┤
          │          └─ no evidence → SEARCHING ────────────────────┤
          └─ denied → FAILED/REFUSED                                 │
                                                                    │
Any nonterminal state → SUSPENDING → SUSPENDED → RESUMING ──────────┘
Any state → CANCELLING → CANCELLED
Deadline/attempt exhaustion → FAILED
```

Pause is not success. Resume is one transaction over task record, revision,
current step, invariants, and every resource/channel lease. If any part cannot
resume, the base remains stopped and the task stays suspended or fails.

### 14.2 Navigation sub-state machine

```text
IDLE
 → ACQUIRE_EVIDENCE
 → GROUND_GOAL
 → PLAN
 → ALIGN
 → TRACK
 → TERMINAL_STOP
 → VERIFY
 → ARRIVED

TRACK ─ blocked/no progress → HOLD → REPLAN → ALIGN/TRACK
REPLAN ─ bounded failures → RECOVER → PLAN
any state ─ stale/health/authority fault → HOLD
any state ─ cancel/E-stop → STOPPED
```

### 14.3 Preemption matrix

| Incoming event | Navigating | Following | Reaction | Manual |
| --- | --- | --- | --- | --- |
| E-stop | cancel motion, latch stop | same | cancel | cancel |
| stop/cancel | cancel selected/current task | cancel | cancel | release |
| pause | atomic suspend + stop | atomic suspend + stop | defer/cancel | release unless operator policy says hold |
| authenticated manual lease | suspend executive base task | suspend | expression may continue if nonconflicting | replace older manual lease |
| low-battery RETURN | preempt ordinary task | preempt | cancel | warn operator; policy-dependent takeover |
| social reaction | defer/vocal-only if conflict | usually vocal/head-only | arbitrate cooldown | no base access |
| new navigation request | policy replace/queue/clarify | replace/queue | unaffected if resources free | queue until manual release |

### 14.4 Revision and resource rule

Every replacement increments `revision`. Commands, paths, terminal witnesses,
crossing authorizations, and recovery state from an older revision become
invalid immediately. Resources are leased to `(task_id, revision, step_id)`.

---

## 15. Bounded recovery

Recovery never weakens a hard mask or raises speed. Each recovery has an entry
predicate, attempt budget, timeout, progress expectation, and exit fact.

```text
recover(failure):
  STALE_SENSOR/POSE_LOST:
      exact HOLD; wait bounded time; no translation
  OWNER_LOST:
      exact HOLD; bounded in-place scan; reacquire multi-frame or fail/ask
  GOAL_NOT_VISIBLE:
      select metric-safe search viewpoint; plan; rescan; bounded count
  PATH_BLOCKED_DYNAMIC:
      hold; bounded wait; rerank goal/replan with hysteresis
  NO_PATH_STATIC:
      try ordered alternate grounded candidates
      then safe frontier only for an explicitly authorized search skill
  NO_PROGRESS:
      invalidate route; replan once; optional bounded rotate scan
  LOCALIZATION_RESET:
      hold; discard path/witness; wait healthy transform; re-ground/replan
  CONTROL_NOT_SETTLED:
      remain stopped; do not issue new motion; fault after deadline
```

The existing missing-scan point-goal fallback is removed from physical/product
profiles. Safe-valley micro-advance is not a generic recovery; if retained for
an experiment, it requires its own labeled ODD and cannot become an implicit
fallback.

---

## 16. Terminal verification

### 16.1 Generic verifier

```text
verify(task, relation, now):
  require same task_id and revision on all evidence
  require healthy fresh MAP pose, transform, metric geometry
  require relation reference fresh and unambiguous
  require relation predicate with configured clearance
  require no active collision/TTC/person/road brake
  command exact terminal stop
  require ControlManager settled feedback for hold duration
  reset dwell on any failed predicate or pose reset
  return TerminalWitnessV1(satisfied=True) only after uninterrupted dwell
```

### 16.2 Skill-specific witnesses

| Skill | Additional witness |
| --- | --- |
| sidewalk | inside semantic polygon with metric clearance; not road |
| lamppost | correct track; distance band; outside pole footprint/road |
| approach owner | confirmed identity; interaction band; optionally facing |
| follow | no terminal success; publishes `holding_formation` feedback |
| orbit | continuous signed revolution count and final relation |
| relative traverse | signed displacement projected on accepted reference ray |
| sit | stationary feedback plus Sport posture/mode evidence |
| wait | navigation terminal witness followed by active hold lease |

Being stopped by the collision monitor near a goal is not arrival. An eval disc
cannot substitute for the product relation witness; evaluation may score both
and report disagreement.

---

## 17. Manual control

Manual input is a first-class short-TTL task, not a hidden direct call to Sport.

```python
@dataclass(frozen=True)
class ManualCommandV1:
    header: HeaderV1
    operator: SpeakerAuthorizationV1
    lease_id: str
    deadman_pressed: bool
    vx_mps: float
    vy_mps: float
    yaw_rate_rps: float
    mode: Literal["BODY_VELOCITY", "STOP", "RELEASE"]
```

Rules:

1. Authenticate operator and acquire the manual base lease.
2. Atomically suspend an active executive base task; do not discard it unless
   requested.
3. Require deadman and fresh command sequence for nonzero motion.
4. Pass through speed regimes, one smoother, and the identical post-shaper
   metric monitor.
5. Deadman release, UI disconnect, stale input, or lease expiry means exact
   zero and stop confirmation.
6. Resume automation only through the atomic resume transaction and a fresh
   replan; never continue an old path blindly.

The UI displays authority owner, task/revision, sensor health, active hard/soft
limits, crossing state, and why a command was limited or rejected.

---

## 18. Road crossing authorization

### 18.1 Authorization object

```python
@dataclass(frozen=True)
class CrossingAuthorizationV1:
    header: HeaderV1
    event_id: str
    task_id: str
    revision: int
    curb_id: str
    principal_id: str
    authenticated_channel: str
    authorization_scope: Literal["THIS_CROSSING"]
    valid_until_s: float
```

### 18.2 State machine

```text
SIDEWALK
  → APPROACHING_CURB (route needs a crossing edge)
  → CURB_STOPPING
  → CURB_STOPPED (exact zero + settled + announce)
  → WAIT_AUTHORIZATION
      ├─ authenticated owner/operator decision bound to event → AUTHORIZED
      └─ timeout/cancel/identity failure → SIDEWALK/HOLD
  → CROSSING (metric monitor remains active; TTL and task binding checked)
  → FAR_SIDE_VERIFIED
  → SIDEWALK

Any unauthorized road pose/goal → BLOCKED + exact zero
Any auth expiry/revision change before road entry → WAIT_AUTHORIZATION
Any critical perception/localization loss during crossing → exact stop;
  recovery policy must be defined by the commissioned crossing ODD
```

Speech recognition can carry an authorization message only after the speaker
and channel have been authenticated and the message is cryptographically or
session-bound to the current event. Phrase matching by itself is insufficient.
OSM, GNSS, CityWalker, or a conversation model may nominate the crossing route;
none may create `CrossingAuthorizationV1`.

---

## 19. Proposed configuration

Names and values are a reviewable starting schema. Safety-sensitive numerical
defaults remain simulation-only until measured commissioning.

```yaml
navigation:
  production_writer: grid_v1
  challenger: disabled                 # nav2_rpp | nav2_mppi, exclusive
  require_lidar: true
  missing_metric_policy: hard_hold
  unknown_space_policy: occupied
  nominal_motion: turn_first
  lateral:
    enabled: true
    preferred: false
    speed_cap_mps: 0.15
    heading_limit_deg: 20
    benefit_threshold: 0.10
  align:
    enter_deg: 28
    exit_deg: 7
  planner:
    global_rate_hz: 2
    local_replan_hz: 5
    grid_resolution_m: 0.10
    goal_rerank_hz: 1
    goal_switch_improvement: 0.15
    commitment_hysteresis: 0.08
  tracker:
    control_rate_hz: 20
    lookahead_min_m: 0.35
    lookahead_max_m: 1.00
    lookahead_speed_gain_s: 0.8
    curvature_regulation: true
    obstacle_regulation: true
    swept_arc_check: true
  smoothing:
    instances: 1
    hard_stop_bypass: true

state:
  pose_provider: truth                  # labeled_sim only
  physical_pose_provider: unconfigured # commissioning blocks motion
  odom_max_age_s: 0.10
  map_max_age_s: 0.50
  transform_max_age_s: 0.10
  lidar_max_age_s: 0.15

follow:
  formation_via_planner: false         # flip only after matched tests
  identity_confirmation_frames: 3
  track_ttl_s: 0.35
  lost_hold_s: 0.5
  relation: behind
  desired_distance_m: 1.5
  hold_band_m: 0.25

behavior:
  approach_owner_hold_s: 0.75
  inside_region_hold_s: 0.75
  nominal_companion_step_m: 0.35
  default_orbit_radius_m: 1.5
  reaction_base_preemption: false

crossing:
  autonomous_road_entry: false
  authorization_scope: this_crossing
  require_authenticated_principal: true
  require_settled_curb_stop: true

control:
  backend: mock_quadruped               # Unitree remains uncommissioned
  command_ttl_s: 0.10
  stop_confirmation_required: true
  unitree_sport:
    axes_commissioned: false
    allowed_modes: []
```

Configuration validation rejects physical mode if the pose provider, Unitree
axes/modes, measured brake profile, required sensors, or safety-envelope units
are uncommissioned.

---

## 20. Nav2 challenger protocol

Nav2 is not discarded. It is introduced only after the in-process authority
path is correct.

1. Build an adapter for the frozen `NavGoalV1`, `PathV1`, metric grid, and
   `MotionProposalV1`; do not change product task behavior for the evaluator.
2. Start with Smac or grid global planning plus Regulated Pure Pursuit.
3. Add MPPI only as a separately configured dynamic-scene challenger.
4. Select one writer before the episode. Shadow outputs are logged but cannot
   acquire the base lease.
5. Both writers pass through the same Parcel final monitor and Unitree adapter.
6. Ensure exactly one smoother in each composition.
7. Compare frozen seeds, sensor inputs, goal regions, speed regimes, timeouts,
   and terminal witnesses.
8. Reject migration on safety regression, deadline misses, unexplained fallback,
   or failure to reproduce from a pinned artifact.

This protocol separates “planner/controller quality” from changes in language,
grounding, safety thresholds, or arrival definitions.

---

## 21. Implementation phases and interfaces to land

### Phase A0 — Baseline and ABI freeze

- Freeze current product episodes, configs, commit/patch hash, and failure
  taxonomy.
- Land the versioned headers and task/pose/evidence/goal/path/feedback schemas.
- Record current `grid_v1`, follow, lifecycle, and stop behavior without
  relabeling derived scores as product results.

**Exit:** deterministic replay identifies every input, revision, command writer,
and terminal witness.

### Phase A1 — Motion authority correctness

- Repair dimensionally invalid person-stop math and choose one clearance
  convention.
- Split hard and comfort stops.
- Add post-shaper exact-zero reassertion and state reset.
- Make missing/stale LiDAR, pose, or transform fail closed.
- Unify duplicate safety thresholds under one envelope.

**Exit:** software HAL command is exact zero on the same hard-stop dispatch;
fault injection pins it. No physical safety claim yet.

### Phase A2 — Lifecycle and semantics

- Make pause/resume atomic over task and channels.
- Add revision-scoped invariants, real attempt budgets, and deadlines.
- Split `ApproachOwner` from `FollowFormation`.
- Establish total relation registry and deterministic skill grammar.
- Require authenticated crossing authorization objects.

**Exit:** product-path tests distinguish pause, cancel, approach, follow, wait,
and crossing with no orphan motion lease.

### Phase A3 — Common classical navigation

- Add RPP-style curvature, obstacle, and goal regulation to `grid_v1`.
- Add swept arc checks and forward/turn-first preference.
- Permit bounded lateral candidates with explicit cost and cap.
- Route all formation goals through `grid_v1` behind a feature flag.
- Add candidate commitment, reranking, and strict dwell terminals.

**Exit:** sidewalk, lamppost, approach, follow, orbit, and relative-traverse
tests use the same planner, safety gate, and terminal path.

### Phase A4 — Honest perception/localization

- Connect sensor-faithful simulator channels and recorded-bag replay.
- Integrate selected ODOM LIO and MAP correction behind `PoseProvider`.
- Add owner enrollment/identity and semantic evidence fusion.
- Validate camera/LiDAR calibration and timestamp behavior.

**Exit:** zero truth reads on the product route; loss/degradation injections
produce typed hold/failure outcomes.

### Phase A5 — Challenger and supervised hardware

- Run exclusive Nav2 RPP and MPPI comparisons.
- Commission Unitree axes, allowed modes, latency, braking, state freshness,
  posture, and network loss in a controlled course.
- Progress through bag shadow, hardware shadow, tethered low-speed, and
  supervised ODD trials.

**Exit:** evidence packet supports a narrow supervised ODD decision; it does not
imply general city autonomy.

### Parallelizable work

After ABI freeze:

- A1 safety/control, A2 task semantics, and A4 sensor bag tooling can proceed in
  parallel with shared schema review.
- Relation/terminal tests and simulator scenario construction can proceed while
  RPP tracking is implemented.
- Nav2 adapter work may begin in shadow after `NavGoalV1`/`PathV1` freeze, but
  paired execution waits for A1 and A3.
- Hardware bag collection and calibration tooling may proceed without enabling
  physical motion.

---

## 22. Evaluation plan

### 22.1 Evidence ladder

| Level | Environment | Claim allowed |
| --- | --- | --- |
| E0 | pure unit/property tests | local algorithm invariant |
| E1 | deterministic headless truth sim | task logic under scripted geometry |
| E2 | sensor-faithful sim, no truth consumer | stack behavior under simulated sensors |
| E3 | recorded hardware bags | perception/localization/replay behavior |
| E4 | hardware shadow, no motion | timing, frames, proposals, vetoes |
| E5 | supervised low-speed course | bounded course result only |
| E6 | frozen external benchmark adapter | benchmark-specific metric |

Do not promote E0–E2 results to physical safety or city-readiness claims.

### 22.2 Mandatory scenario suites

1. **Authority faults:** stale/missing scan, malformed angles, pose lost,
   transform jump, planner timeout, smoother overrun, TTL expiry, network loss.
2. **Static navigation:** narrow door, U-shape, cul-de-sac, low-clearance turn,
   lateral reposition, turn-first path.
3. **Dynamic navigation:** crossing pedestrians, opposing corridor flow,
   occlusion, abrupt stop, final-region contest.
4. **Instruction:** synonyms, negation, corrections, deictic ambiguity,
   unsupported request, unit conversion, malformed model proposal.
5. **Relations:** inside sidewalk, next to lamppost, entrance of store, behind
   owner, approach owner, orbit, signed relative displacement.
6. **Identity:** lookalikes, crossing tracks, partial occlusion, owner loss,
   reappearance, wrong-person lure.
7. **Lifecycle:** pause/resume at every substate, replace, cancel, deadline,
   recovery exhaustion, manual takeover/release.
8. **Road policy:** far-side goal without auth, spoofed transcript, wrong
   speaker, expired auth, revision change, curb-stop success.
9. **Companion reactions:** joke during follow, sadness during navigation,
   low battery near road/door, posture rejection on unsafe terrain.

### 22.3 Core metrics

- task success with relation-specific terminal witness;
- collision and hard-envelope violation counts;
- minimum metric clearance and minimum TTC;
- exact-zero compliance at software HAL boundary;
- path efficiency, time-to-goal, replans, recoveries, oscillations;
- lateral distance fraction and turn-first compliance;
- owner identity switches, follow distance/angle error, reacquisition time;
- false success, false stop, intervention, and unauthorized-road-entry rate;
- control deadline miss and stale-evidence rate;
- user-query-end to first reasoning result, first logged response, and first
  spoken response;
- command-to-Sport send, send-to-feedback, and stop-to-settled latency;
- compute, memory, power, and thermal envelope by component.

All aggregate metrics retain per-episode distributions and failure classes.
One BARN world, one simulator seed, or a derived rescore is never a general
quality claim.

### 22.4 Acceptance examples

| Task | Success | Explicit false success |
| --- | --- | --- |
| “go to sidewalk” | inside eroded sidewalk polygon, not road, stopped/settled/dwell | stopped in road or outside polygon due to person brake |
| “wait by lamppost” | correct pole, vicinity band, road excluded, settled hold | any lamppost label without metric relation |
| “circle me once” | confirmed owner, collision-free continuous ~one revolution, terminal stop | spin in place or orbit wrong person |
| “walk away five steps” | signed displacement near configured 5-step distance | five command ticks or unsafe blind reverse |
| “come here” | interaction band then base released | persistent follow still active |
| “follow me” | persistent formation with bounded errors and no identity switch | one-time approach reported as follow |

### 22.5 Baseline and falsification comparison

Compare at least:

- current `grid_v1` product path;
- Design A `grid_v1` plus common formation and regulation;
- exclusive Nav2 RPP challenger;
- exclusive Nav2 MPPI challenger where compute permits.

Freeze semantic goal, metric evidence, speed regime, safety envelope, terminal
predicate, scenario seed, timeout, and writer identity. If these differ, label
the run exploratory rather than paired.

---

## 23. Observability and replay

Every control tick logs a causally linked record:

```text
run_id, episode_id
task_id, revision, step_id, resource_owner
sensor evidence IDs and ages
MAP/ODOM pose IDs, transform ID, health, reset counter
semantic reference and goal-region ID
path ID, planner, map revision, replan reason
raw proposal, pre-gate decision, shaped command, final decision
hard/soft reason codes, min clearance, TTC
ControlManager lease/source/TTL, Sport send and feedback sequence
terminal-witness fields
stage timestamps and deadline misses
```

Logs must distinguish commanded exact zero from physically settled feedback.
Replay verifies that identical inputs produce identical task transitions,
routes subject to stable tie-breaking, commands, vetoes, and terminal results.

---

## 24. Risks and mitigations

| Risk | Consequence | Mitigation / test |
| --- | --- | --- |
| Classical grid planner is brittle in dense crowds | stop-go or no-path | dynamic prediction, bounded wait/rerank; Nav2 MPPI challenger |
| Camera semantic errors | wrong object/region | metric support, temporal fusion, ambiguity clarification |
| Owner ReID switch | follows stranger | enrolled multi-frame confirmation; ambiguity hold |
| LIO drift or reset | wrong route/arrival | MAP/ODOM separation, covariance gates, reset invalidation |
| 2-D LiDAR misses curb/low obstacle | unsafe outdoor assumption | depth/elevation required; restrict ODD |
| RPP cannot handle some holonomic maneuvers | oscillation/inefficiency | bounded lateral selector; SE(2) planner/Nav2 challenger |
| Duplicate shaping | delayed stops/poor tracking | composition validator enforces one smoother |
| Conservative gates cause deadlock | poor completion | report false-stop separately; change soft goals, not hard masks |
| External map is stale/incomplete | bad route nomination | advisory only; local re-grounding and road policy |
| Conversation delay blocks behavior | high latency | async lane; grammar fast path; immutable snapshots |
| Unitree state/API mismatch | unobserved motion/fault | explicit mode/axis commissioning and stop confirmation |
| Configuration drift | invalid comparisons | schema validation and hashed run manifest |

---

## 25. What would falsify Design A

The team should reject or materially revise this design if controlled evidence
shows any of the following after a fair implementation:

1. Exact-zero and fail-closed changes cannot meet the required control deadline
   on target hardware without destabilizing Unitree Sport.
2. A common deterministic planner cannot satisfy the frozen core instruction
   suite despite correct grounding and perception, while a bounded learned
   proposer does so reproducibly under the same safety/terminal contract.
3. Owner-follow formation through `grid_v1` causes materially worse safety or
   tracking than a separately verified alternative and cannot be corrected by
   local-controller changes.
4. RPP-style regulation produces persistent oscillation or excessive no-path
   behavior across the frozen morphology/ODD suite.
5. The latency budget cannot support deterministic semantic grounding plus
   replanning on the target compute, after profiling and optimization.
6. The evidence and relation schemas cannot represent required real tasks
   without unsafe special cases.
7. The final monitor cannot independently validate the actual shaped command
   with sufficiently fresh metric evidence.
8. Hardware bag and supervised trials invalidate the assumed footprint,
   braking, time-sync, localization, or sensor ODD beyond practical repair.

Falsification does not justify bypassing hard safety. It triggers comparison
with Designs B/C behind the same typed authority and evaluation contracts.

---

## 26. Team decisions requested

1. Approve deterministic metric authority as the baseline, or identify the
   exact layer where learned authority is required.
2. Approve base-center-to-obstacle-surface as the single clearance convention,
   subject to commissioning review.
3. Approve `grid_v1` + Parcel RPP-style regulation as first writer and Nav2 as
   an exclusive challenger.
4. Choose the physical localization kit path: Mid-360/FAST-LIO2 or built-in
   L1/Point-LIO, after a bag-based spike.
5. Approve `ApproachOwner`/`FollowFormation` split and common formation planner.
6. Approve authenticated event-bound crossing authorization rather than
   transcript matching.
7. Agree on the initial supervised ODD and numerical latency/freshness budgets
   before commissioning values become production defaults.
8. Agree that no custom RL training begins until this baseline and the frozen
   residual evaluation are complete.

---

## 27. Review summary

Design A makes the robot’s “intelligence” a composition of explicit skills,
relations, evidence, planning, and verification rather than an opaque motor
policy. It supports rich companion behavior while keeping navigation authority
classical: language proposes what the owner wants; perception proposes what and
where things are; deterministic grounding chooses an admissible goal region;
`grid_v1` and regulated tracking choose how to approach it; the independent
monitor decides whether motion is currently permissible; and Unitree Sport
executes the commanded body motion while maintaining the quadruped.

Its value is not that it is guaranteed to win. Its value is that it creates the
first auditable, reproducible baseline whose failures tell the team whether the
remaining limitation is perception, grounding, planning, control, or behavior.
Only then can a learned alternative be compared without moving the goalposts.
