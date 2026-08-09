# Design D1 — Fail-closed classical companion

**Author role:** Claude Opus design stand-in  
**Date:** 2026-08-07  
**Status:** engineer-ready proposal for team review  
**Inputs:** `RESEARCH_THESIS.md`, `research/OPUS_INDEPENDENT_AUDIT.md`,
`research/N1_CLASSICAL_NAV.md`, `research/N5_SAFETY_AUTHORITY.md`,
`research/N6_EXECUTIVE_BEHAVIOR.md`, `TARGET_ARCHITECTURE.md` (ABI names)  
**Differentiator:** **No learned policies in the motion path.** Fix verified P0
defects; keep PlanIR + `grid_v1` + post-shaper hard-zero monitor +
`ApproachOwner` + atomic resume. Nav2 / MiniCPM / CityWalker are out of scope
for D1 (challenger/shadow designs D2/D3 may consume D1 ABIs later).

**Safety status:** Research + implementation design only. Not a physical
certification case. Software E-stop ≠ hardware E-stop.

---

## 1. Goals / non-goals

### 1.1 Goals (Phase-0 shippable substrate)

| ID | Goal | Exit evidence |
| --- | --- | --- |
| G1 | **Exact-zero hard safety stop** on the same dispatch that declares proximity/TTC hard-stop | HAL/`ControlManager` command `(vx,vy,vyaw)==(0,0,0)`; shaper+smoother reset; pin replaces residual-ok test |
| G2 | **Fail-closed LiDAR/pose** on product/physical profiles | Missing, stale, malformed, or frame-invalid scan/pose/transform → HOLD `(0,0,0)` note; never `StubNavigator` translation |
| G3 | **Atomic pause/resume** over `{task_id, revision, step_id, channel}` | Closed-intent resume restores executive task **and** channel; xfail → pass; channel enable ⇒ authorizing revision active |
| G4 | **`ApproachOwner` ≠ `FollowFormation`** | Come/summons terminates + releases `base`; follow stays persistent until Hold/cancel |
| G5 | **NavigateTo grounding ladder** remains searchable≠visible; terminates only via relation witness | Admission pin preserved; recovery bounded; GoalRegion/registry is sole arrival authority |
| G6 | **Relation witnesses totalized** for product speech acts D1 claims | One `RelationSpec` drives grammar, sketch, success facts, hold duration, release policy |
| G7 | **Typed V1 ABIs frozen** for pose/perception/task revision/nav goal/feedback/safety | Dataclass schemas in §4; consumers reject unknown/malformed fail-closed |
| G8 | **Preserve** PlanIR → compiler → validator → TaskExecutive boundary; Sport owns gait; elementwise-min authority | No language→motor shortcut; no second velocity writer |

### 1.2 Non-goals (explicit)

1. **No learned motion policies** — no VLA, MPPI-as-authority, MiniCPM, CityWalker, RL ranker, or NavProposal consumer on the live path.
2. **No Nav2 authority migration** — keep in-process `grid_v1`; Nav2 remains exclusive challenger (D2/Phase-2). Steal Collision Monitor *ordering* only.
3. **No physical commissioning / Sport e2e latency claim** — leave `a_meas`, `τ_e2e`, Unitree 2 m guidance as UNVERIFIED (§9).
4. **No T0→R2 perception replacement** — truth pose / T0 semantics stay labeled-sim; D1 only forbids pretending they are product localization.
5. **No N11 e2e flip** — mid-mission re-rank + dwell `inside` belong to D3; D1 must not weaken person-stop to “make progress.”
6. **No formation-follow planner rewrite as blocking G1–G3** — follow→common planner is P1; D1 may stub ApproachOwner through existing approach/grid path without solving full RPF.
7. **No dual smoother** — one S-curve / velocity smoother owner; post-shaper monitor never re-smooths.
8. **No unsupervised physical deployability claim** from sim zeros.

### 1.3 P0 defect map (what D1 closes)

| Defect | Audit | D1 mechanism |
| --- | --- | --- |
| P0.1 / S0.1 residual shaper velocity | N5, Opus audit | Hard-zero post-shaper (§3.1, §5) |
| P0.2 / S0.2 LiDAR open-loop | N5, Opus audit | Product HOLD (§3.2, §6) |
| P0.3 truth pose as production | thesis | Typed health + fail-closed on DEGRADED/LOST for translating profiles (§4.1, §6) |
| P0.4 / S1.1 resume split | N6, Opus audit | Atomic lifecycle (§3.3) |
| P0.5 come≡follow | N6 | ApproachOwner (§3.5) |
| P0.6 recovery/invariants | N6 | Bounded ladder + per-revision invariants (§3.4, §3.6) — minimal executable subset |

---

## 2. ASCII system diagram

```text
 owner speech / closed intents
            │
   ┌────────┴────────┐
   │ literal E-stop  │  reviewed common lane (no LLM)
   │ (anyone)        │  PlanSketch ──► compile ──► validate
   └────────┬────────┘         │
            │                  ▼
            │           TaskExecutive
            │        (queue/run/suspend/
            │         resume/recover)
            │                  │
            │     ┌────────────┼────────────────────────────┐
            │     ▼            ▼                            ▼
            │ NavigateTo   ApproachOwner              FollowFormation
            │ (ladder)     (terminate+release)        (persistent lease)
            │     │            │                            │
            │     └────┬───────┴────────────┬───────────────┘
            │          ▼                    ▼
            │   NavGoalV1 / Feedback   formation SE(2) goal (P1 stub OK)
            │          │
            │          ▼
            │     grid_v1  (rolling occ + A* + RPP-ish track)
            │          │
            ▼          ▼
      obs snapshot ──────────────► reactive proximity + TTC  (pre-shaper)
            │                              │
            │                              ▼
            │                    VelocitySmoother / SCurve shaper
            │                              │
            │                              ▼
            │              ★ HardZeroMonitor (POST-SHAPER) ★
            │                 exact (0,0,0) + reset on hard stop
            │                 freshness miss → HOLD
            │                              │
            │                              ▼
            │                      ControlManager / leases
            │                              │
            └──────────────────────────────► Unitree Sport Move/Stop
                                              (gait owned onboard)

  Legend:  ★ = D1 new/changed authority   — = data   ► = command
  Explicitly absent: NavProposalV1 consumer, Nav2 writer, learned critic
```

**Authority rule:** any layer may tighten or zero a command; **no** layer may
widen an upstream envelope or resurrect motion without an active
`TaskRevisionV1`.

---

## 3. Algorithms (pseudocode)

### 3.1 Hard-zero post-shaper

Distinguish stop classes. Comfort may slew; hard safety must snap.

```text
enum StopClass:
  NONE
  COMFORT_STOP      # owner soft stop, pace change, yield ramp
  HARD_SAFETY_STOP  # proximity/TTC/freshness/E-stop latch/monitor veto

fn shape_and_gate(intent_cmd, obs, proximity_state, ttc_scale) -> VelocityCommand:
  # Pre-shaper (existing): never raise a stop
  gated = apply_proximity_ttc(intent_cmd, proximity_state, ttc_scale)
  stop_class = classify_stop(proximity_state, ttc_scale, sensor_health(obs))
  #   HARD if proximity=="stopped" OR ttc_scale<=0 OR required_source_invalid
  #   COMFORT if soft scale-down / owner comfort only
  #   else NONE

  if stop_class == HARD_SAFETY_STOP:
    # Still run shaper for telemetry continuity, then veto — or skip shape.
    shaped = VelocityCommand(0, 0, 0)
    reset_velocity_smoother()
    reset_motion_shaper()          # clears internal vx/vy/vyaw + accel state
    latch_hard_stop_reason(...)
    return shaped

  shaped = scurve_shaper.step(gated, emergency=(stop_class==COMFORT_STOP))
  # ★ POST-SHAPER RE-ASSERT (Nav2 Collision Monitor ordering, in-process)
  return hard_zero_monitor(shaped, obs, stop_class)

fn hard_zero_monitor(shaped, obs, prior_stop_class) -> VelocityCommand:
  verdict = reevaluate_raw_geometry(obs, shaped)
  # Uses freshest LiDAR ranges / nearest_obstacle / TTC against *shaped* cmd
  # and SafetyEnvelope.stop_distance(v=‖shaped.v‖)

  if prior_stop_class == HARD_SAFETY_STOP or verdict.requires_hard_stop:
    reset_velocity_smoother()
    reset_motion_shaper()
    return VelocityCommand(0, 0, 0)   # exact; including vyaw

  if not required_sources_fresh(obs):  # see §3.2
    reset_velocity_smoother()
    reset_motion_shaper()
    return VelocityCommand(0, 0, 0, note="monitor_source_timeout")

  # Monitor may only scale down (elementwise |cmd| min), never up
  return elementwise_min_abs(shaped, verdict.max_cmd)
```

**Pin:** on the stop tick, observed HAL target must satisfy
`abs(vx)+abs(vy)+abs(vyaw) == 0` (float exact after reset). Replace
`bypass_drop > smoothed_drop` as sole proximity criterion.

### 3.2 LiDAR / pose HOLD (fail-closed)

```text
fn scan_contract_ok(obs) -> Result[CalibratedScan, HoldReason]:
  if ranges missing or wrong length/type: return Err(MALFORMED)
  if calib (angle_min, increment, range_max, ...) non-numeric: return Err(MALFORMED)
  if stamp age > lidar_source_timeout_s: return Err(STALE)
  if |lidar_stamp - odom_stamp| > timestamp_slop_s: return Err(FRAME_SKEW)
  if transform lidar→base missing/invalid: return Err(TRANSFORM)
  return Ok(scan)

fn pose_contract_ok(pose: PoseEstimateV1, profile) -> Result[(), HoldReason]:
  if pose.health == LOST: return Err(POSE_LOST)
  if profile.requires_healthy_pose and pose.health == DEGRADED:
    return Err(POSE_DEGRADED)
  if pose age > pose_source_timeout_s: return Err(POSE_STALE)
  return Ok(())

fn grid_v1.act(obs, mission) -> VelocityCommand:
  match scan_contract_ok(obs):
    Err(reason):
      if profile.allow_open_loop_stub:   # labeled-sim ODD ONLY
        return stub.act(...)            # loud note; never default product
      else:
        return HOLD(0,0,0, note=reason) # same as _safe_valley_hold
  match pose_contract_ok(obs.pose, profile):
    Err(reason): return HOLD(0,0,0, note=reason)
  # else: update occ, A*, track — existing path
```

**Default flip:** product `grid_v1` sets `fail_closed_on_missing_scan: true`
(equivalent to today’s opt-in `safe_valley_micro_advance` HOLD branch for the
*missing-scan* case). Stub fallback requires explicit
`odd.allow_scan_missing_fallback: true` + `profile != physical`.

### 3.3 Atomic pause / resume

```text
@dataclass
LifecycleTransaction:
  task_id: str
  plan_revision: int
  step_id: str
  channel: str                 # navigation|follow|search
  resume_intent: ResumeIntent
  resources: frozenset[str]    # e.g. {"base"}
  generation: int              # channel generation token

fn pause_closed_intent(runtime, reason="closed_intent_pause"):
  BEGIN TX
    for channel in pausable_channels:
      intent = capture_ResumeIntent(channel, reason, ttl=...)
      pause_channel(channel, intent)
      store.record(intent)
      bump_generation(channel)
    for task in executive.tasks_matching(channels):
      executive.suspend_task(task.id, reason)   # non-outcome
      bind LifecycleTransaction(task, channel, intent)
  COMMIT  # or rollback all on failure

fn resume_closed_intent(runtime):
  BEGIN TX
    txs = take_matching_transactions()
    if empty: return reject("nothing_to_resume")
    for tx in txs:
      if resume_rejection_reason(tx.resume_intent, ...): continue  # fail-closed
      # ★ Order matters: task BEFORE channel base reacquire
      executive.resume_task(tx.task_id)          # → queued/running
      assert executive.task_state(tx.task_id) not in NON_OUTCOME_SUSPENDED
      ok = _resume_from_store(tx.channel, expect_revision=tx.plan_revision)
      if not ok:
        executive.re_suspend_or_fail(tx.task_id, "channel_resume_failed")
        abort channel enable
    COMMIT

invariant:
  channel.enabled ∧ channel.owns("base")  ⇒  ∃ active TaskRevisionV1
    with matching task_id/revision/step authorizing that channel
```

**Hold remains destructive:** `_brain_hold` clears ResumeIntents and does **not**
call this transaction’s resume path.

### 3.4 NavigateTo grounding ladder

Admission unchanged (`camera_fresh ∧ lidar_fresh ∧ base_available`; **not**
`target_grounded`).

```text
fn NavigateTo.tick(task_rev, snap: PerceptionSnapshotV1) -> SkillFeedbackV1:
  if not admission_ok(snap): return blocked("admission")

  # Ladder — each rung bounded; max_attempts from TaskRevisionV1
  target = resolve_from_frustum(snap, task_rev.args)
  if target is None:
    target = resolve_from_memory(snap, task_rev.args)
  if target is None:
    run ScanBehavior / rotate-in-place (budgeted)
    target = resolve_from_frustum(snap, ...)
  if target is None:
    target = semantic_frontier_candidate(snap, task_rev)  # geometry-first
  if target is None:
    return fail_or_clarify("ungrounded", attempts++)

  region = relation_registry[task_rev.relation].goal_region(anchor)
  goal = NavGoalV1.from_region(region, frame=MAP|ODOM, ttl=..., task_rev)

  cmd_or_hold = grid_v1.act(snap, goal)   # may HOLD per §3.2
  publish NavFeedbackV1(progress, nearest, plan_status)

  if relation_registry[relation].holds(pose, anchor) \
     and settled(snap) \                    # stop_confirmed ∧ ¬moving
     and hold_elapsed(task_rev.hold_duration_s):
    release_channel_if(spec.success_releases_channel)
    return succeeded(witness=registry_predicate_id)

  if progress_watchdog.stalled: replan_or_recover(bounded)
  if deadline_exceeded: return failed("step_timeout")
```

Recovery subtree (executable subset for D1):

```text
no_route      → rebuild_local_occ → alternate_approach → ask/Hold
ungrounded    → rescan → alternate_candidate → fail/clarify
controller_stall → hard_zero → short backoff → replan → fail
sensor_loss   → HARD_SAFETY_STOP (bypass comfort)
```

Compiler must allow `max_attempts ≥ 1` **only** when the named recovery action
exists in the adapter table; default product NavigateTo uses
`max_attempts=2` for `rescan|alternate_candidate` only (not unbounded LLM retry).

### 3.5 ApproachOwner

```text
# Speech act: come / go to me / go to the owner
# NOT FollowFormation. Alias "come" must NOT map to relation "follow".

Skill ApproachOwner:
  args: { owner_ref, band: RelationSpec("near"|"next_to" owner), settle_hold_s }
  persistent: false
  success_releases_channel: true

fn ApproachOwner.tick(...):
  if owner_identity in {LOST, AMBIGUOUS}:
    decelerate_under_geometry() or HARD_ZERO if geometry also bad
    return blocked("owner_unresolved")   # never nearest-person substitute

  # Short-TTL owner-relative SE(2) goal → SAME grid_v1 path as NavigateTo
  goal = sample_approach_pose(owner_track, band, occ)
  cmd = grid_v1.act(..., goal)

  witness = (
    relation.holds(robot_xy, owner_anchor)
    and stop_confirmed
    and control_feedback_fresh
    and not robot_moving
    and settle_timer >= settle_hold_s
  )
  if witness:
    disable_follow_controller()
    release_base_lease()
    return succeeded("approach_settled")
  return in_progress(checkpoint=band_entered?)
```

**Sketch change:** `sketch_come` → `ApproachOwner`, not `FollowFormation`.
Preserve behind-vs-plain admission (heading only for behind).

**FollowFormation** (unchanged speech act “follow me”): never auto-succeed on
band alone; adapter reports `in_progress` checkpoints; terminal only on
Hold/cancel/lease transfer.

### 3.6 Relation witnesses

```text
RelationSpecV1 (extends today's RelationSpec):
  name, aliases, anchor_kinds, frame_of_reference
  terminal_behavior: stop|hold
  goal_region_builder | None
  nominal_band_m, hold_duration_s
  persistent: bool
  success_releases_channel: bool
  planir_goal_relation: str          # first-class PlanIR token
  sketch_grounding: inside|near|…    # no silent collapse of towards→near without note
  witness_id: str                    # cited in SkillFeedbackV1.verified_facts

fn terminal_success(skill, pose, snap) -> bool:
  spec = REGISTRY[skill.relation]
  if spec.persistent:
    return False   # checkpoints only
  if not spec.holds(pose.xy, anchor_from(snap)):
    return False
  if spec.terminal_behavior == "hold":
    return settle_ok(snap) and hold_timer >= spec.hold_duration_s
  return settle_ok(snap)
```

D1 required registrations (product claims):

| Speech / relation | persistent | releases channel | notes |
| --- | --- | --- | --- |
| `inside` (region) | no | yes | dwell optional via hold_duration |
| `near` / `next_to` / `towards` (object) | no | yes | distinct bands; JEPD family |
| `approach_owner` (new; aliases come/go-to-me) | no | yes | owner anchor only |
| `follow` | **yes** | no | remove `come` alias |
| `behind` | **yes** | no | heading admission preserved |
| `hold` / stay | no | clears intents | destructive settle |

---

## 4. Interfaces (dataclasses)

All times: **monotonic seconds** (`float`) unless `*_ns` noted. Frames:
`odom` | `map` | `base` | `lidar` | `camera`. Fail-closed: `__post_init__`
raises on non-finite / wrong arity / unknown enum; consumers treat raise /
`None` as HOLD, never as free space.

### 4.1 `PoseEstimateV1`

Promotes / freezes `pose.PoseEstimate` + target-architecture fields.

```python
@dataclass(frozen=True)
class PoseEstimateV1:
    x: float                          # m, in `frame`
    y: float                          # m
    yaw: float                        # rad, CCW from frame +x
    frame: Literal["odom", "map"]
    health: Literal["HEALTHY", "DEGRADED", "LOST"]
    covariance: tuple[float, ...]     # row-major 3×3; m², m·rad, rad²
    captured_at_s: float              # sensor capture monotonic
    received_at_s: float              # host receive monotonic
    transform_epoch: int              # bump on TF tree change
    source: str                       # "truth"|"fast_lio2"|"point_lio"|...
    calibration_id: str               # empty forbidden on physical profile
    # Optional dual-rate extras (None = unused)
    map_T_odom: tuple[float, ...] | None = None  # 3×3 SE2 or 4×4; document choice in impl

# Failures → HoldReason:
#   LOST | DEGRADED (if profile.requires_healthy_pose) | STALE
#   | COVARIANCE_INVALID | FRAME_UNKNOWN | CALIBRATION_MISSING
```

**Units:** m, rad, s. **Control consumes ODOM;** semantic goals live in MAP and
must transform through recorded history or reject.

### 4.2 `PerceptionSnapshotV1`

```python
@dataclass(frozen=True)
class PerceptionSnapshotV1:
    snapshot_id: str
    captured_at_s: float
    pose: PoseEstimateV1
    lidar: LidarScanV1 | None         # None ≡ missing
    camera_fresh: bool
    lidar_fresh: bool
    nearest_obstacle_m: float | None  # m; None if unknown (not +inf)
    nearest_person_m: float | None
    owner: OwnerTrackV1 | None        # from contracts.v1; identity posterior
    dynamic_tracks: tuple[DynamicTrackV1, ...]
    semantic_regions: tuple[SemanticRegionV1, ...]
    evidence_envelope: EvidenceEnvelopeV1 | None
    odd_tags: frozenset[str]          # e.g. {"labeled_sim","allow_scan_missing_fallback"}
    perception_tier: Literal["T0", "T1", "R2", "R3"]  # honesty ladder label

@dataclass(frozen=True)
class LidarScanV1:
    ranges_m: tuple[float, ...]
    angle_min_rad: float
    angle_increment_rad: float
    range_min_m: float
    range_max_m: float
    stamp_s: float
    frame_id: str                     # usually "lidar"
    calibration_id: str

# Failures:
#   missing scan, len mismatch, non-finite range, calib NaN,
#   age > timeout, skew vs pose, TF miss → monitor/grid HOLD
```

Oracle/`truth` fields allowed only when `perception_tier in {T0,T1}` **and**
`odd_tags` contains `labeled_sim`. Product bags reject oracle fields.

### 4.3 `TaskRevisionV1`

```python
@dataclass(frozen=True)
class TaskRevisionV1:
    task_id: str
    plan_revision: int                # ≥ 1; immutable per revision
    step_id: str
    skill: Literal[
        "NavigateTo", "ApproachOwner", "FollowFormation",
        "Hold", "OrbitOwner", "MoveRelative", "AskClarification",
    ]
    relation: str                     # registry name
    args: Mapping[str, object]        # FrozenDict in impl
    resources: frozenset[str]         # {"base", ...}
    preconditions: frozenset[str]
    success_facts: tuple[str, ...]
    invariants: tuple[str, ...]       # per-revision; union arbitrated
    deadline_s: float                 # step wall budget
    max_attempts: int                 # ≥ 1; recovery must be executable
    recovery: tuple[str, ...]         # subset of adapter table
    interruptibility: Literal["preemptable", "critical", "non_preemptable"]
    persistent: bool                  # skill-level; must match RelationSpec
    hold_duration_s: float
    authorizing_channel: str
    parent_task_id: str | None = None
    observation_snapshot_id: str | None = None

# Failures:
#   unknown skill/relation, max_attempts>1 with empty recovery,
#   persistent/success_facts mismatch, missing resources for motion skills
```

### 4.4 `SafetyEnvelope` (authority — keep, unify floors)

Existing `parcel_robot.authority.SafetyEnvelope`; D1 makes it the **sole**
stop-distance authority and unifies YAML drift.

```python
# With clearance measured from base centre to obstacle surface:
# stop_distance(v) = r_foot + v*τ + v²/(2*a) + Zs + Zr     [m]
# person_stop(v)   = max(person_social_zone_m,
#                        stop_distance(v) + person_dynamic_allowance_m)
# person_dynamic_allowance_m must be measured or derived as
# bounded_relative_closing_speed_mps * person_time_allowance_s.

@dataclass(frozen=True)
class SafetyEnvelope:  # already in authority.py — pin fields
    footprint_radius_m: float           # m
    reaction_latency_s: float           # s (τ); UNVERIFIED vs Sport e2e
    decel_max_mps2: float               # m/s²; prefer a_meas when commissioned
    sensing_intrusion_m: float          # Zs; default 0 UNVERIFIED outdoors
    pose_uncertainty_m: float           # Zr; from PoseEstimateV1.position_sigma
    person_social_zone_m: float         # m; unscaled human floor
    person_dynamic_allowance_m: float  # m; measured/derived with provenance
    clearance_convention: Literal["base_center_to_obstacle_surface"]
    obstacle_comfort_band_m: float
    person_comfort_band_m: float
    obstacle_stop_floor_m: float        # m; replaces competing stop_distance_m

# Failures / policy:
#   reject mixed-unit or ambiguous-clearance configuration at startup
#   footprint radius is included exactly once under the declared convention
#   envelope may only widen via measured Zs/Zr/a_meas — never via model confidence
#   soft social costs cannot undercut stop_distance(v)
```

### 4.5 `NavGoalV1` / `NavFeedbackV1`

Concrete names for TARGET’s NavigateGoalV1 seam (D1 classical only).

```python
@dataclass(frozen=True)
class NavGoalV1:
    goal_id: str
    task_id: str
    plan_revision: int
    step_id: str
    frame: Literal["odom", "map"]
    goal_region: GoalRegionV1           # contracts.v1; polygon / preferred pose
    relation: str
    issued_at_s: float
    expires_at_s: float                 # TTL; expired → reject, do not track
    footprint_profile_id: str
    max_speed_mps: float                # m/s; further min'd by SafetyEnvelope
    allow_reverse: bool
    witness_id: str

# Failures: expired TTL, unknown frame, TF miss, empty polygon,
#           revision mismatch with active TaskRevisionV1 → reject / HOLD

@dataclass(frozen=True)
class NavFeedbackV1:
    goal_id: str
    task_id: str
    plan_revision: int
    status: Literal[
        "accepted", "tracking", "replanning", "holding",
        "blocked", "succeeded", "failed", "rejected",
    ]
    pose: PoseEstimateV1
    distance_to_region_m: float
    nearest_obstacle_m: float | None
    path_len_m: float | None
    cmd_pre_shaper: tuple[float, float, float]   # vx, vy, vyaw
    cmd_post_monitor: tuple[float, float, float]
    stop_class: Literal["NONE", "COMFORT_STOP", "HARD_SAFETY_STOP"]
    hold_reason: str | None
    verified_facts: tuple[str, ...]
    stamp_s: float

# Failure statuses are terminal for the goal_id; new work needs new goal_id
# or plan_revision bump. "holding" is non-terminal (sensor HOLD).
```

---

## 5. Tick nav logic

Single dispatch ordering (replaces gate→shaper→HAL without post-assert):

```text
every control tick (target 20–50 Hz local; safety monitor mentally 50–100 Hz):

1. OBSERVE
   snap = build_PerceptionSnapshotV1(sensors)
   pose_ok = pose_contract_ok(snap.pose)
   scan_ok = scan_contract_ok(snap.lidar)
   if executive has no active motion revision:
        cmd = (0,0,0); goto MONITOR   # idle fail-closed

2. PLAN / SKILL
   task_rev = executive.active_revision()
   feedback = skill.tick(task_rev, snap)   # NavigateTo | ApproachOwner | …
   if feedback.status in {blocked, failed}:
        intent = (0,0,0)
   else:
        intent = last NavGoal tracking intent from skill

3. GRID (grid_v1)
   if not scan_ok or not pose_ok:
        grid_cmd = HOLD(0,0,0, note=...)
   else:
        grid_cmd = grid_v1.act(snap, active_NavGoalV1)
   # FollowFormation in D1 may still use legacy proportional path BUT still
   # enters the same brake→shaper→monitor chain (no HAL bypass).

4. BRAKE (pre-shaper reactive + TTC)
   gated, proximity_state, ttc_scale = collision_safe(grid_cmd, snap)
   stop_class = classify_stop(...)

5. SHAPER
   if stop_class == HARD_SAFETY_STOP:
        shaped = (0,0,0); reset smoother+shaper
   else:
        shaped = scurve.step(gated, emergency=(stop_class==COMFORT_STOP))

6. POST-SHAPER VETO  ★
   final = hard_zero_monitor(shaped, snap, stop_class)
   # re-check geometry on shaped; freshness; exact zero + reset if needed
   # elementwise min only

7. HAL
   if latched_estop: ControlManager.emergency_stop(); return
   ControlManager.set_target(final)   # leases + Sport
   publish NavFeedbackV1(... cmd_pre_shaper, cmd_post_monitor ...)
```

**Invariants per tick:**

- `HARD_SAFETY_STOP ⇒ final == 0 ∧ shaper_reset`
- `required_source_invalid ∧ translating_profile ⇒ final == 0`
- `final` never exceeds `arbitrate_limits(...)` elementwise
- Skill feedback `succeeded` only with registry witness (+ settle if required)

---

## 6. Config defaults

D1 shipping defaults (product profile). Labeled-sim overrides called out.

```yaml
# configs/navigation/default.yaml  (D1 deltas)
active_model: grid_v1

grid_v1:
  fail_closed_on_missing_scan: true    # NEW default true (was stub fallback)
  fail_closed_on_stale_scan: true
  fail_closed_on_pose_unhealthy: true
  lidar_source_timeout_s: 0.25         # Nav2-like freshness; tune under load
  pose_source_timeout_s: 0.20
  timestamp_slop_s: 0.02
  allow_scan_missing_fallback: false   # true ONLY under odd.labeled_sim

safety:
  max_vx: 0.9                          # m/s
  max_vy: 0.25
  max_vyaw: 0.8
  # Unify floors — SafetyEnvelope is source of truth; these are mirrors:
  obstacle_stop_floor_m: 0.6           # was split 0.65 / 0.8 — pick envelope floor
  # stop_distance_m retained as deprecated alias → obstacle_stop_floor_m
  predictive_mode: projected_speed_cap

motion.smoothing:                      # configs/robot.yaml
  linear_max_accel: 1.2                # m/s² comfort / emergency slew for COMFORT only
  # HARD_SAFETY_STOP ignores accel and snaps to 0
  hard_safety_exact_zero: true         # NEW

pose:
  provider: truth                      # labeled-sim OK; physical must not ship this
  require_healthy_for_translation: true

perception:
  tier: T0                             # honesty label; not "real perception"

executive:
  navigate_to_max_attempts: 2
  navigate_to_recovery: [rescan, alternate_candidate, safe_stop]
  approach_owner_settle_hold_s: 0.5
  resume_intent_ttl_s: 120.0
  atomic_resume: true                  # NEW; product path must call resume_task

odd:
  labeled_sim: true                    # CI/city headless
  physical: false
  allow_scan_missing_fallback: false
```

**Physical profile overlay** (when commissioned): `pose.provider` ≠ truth;
`odd.physical: true`; `calibration_id` required; `allow_scan_missing_fallback`
hard-false regardless of YAML attempt to enable.

---

## 7. Test / eval gates

### 7.1 Blocking unit / product-path pins (must go green)

| Gate | Test / assertion | Defect |
| --- | --- | --- |
| T-A1 | Proximity/TTC hard-stop tick: HAL cmd exact zero; shaper state zero | P0.1 |
| T-A2 | Comfort stop may slew; hard stop must not | P0.1 |
| T-A3 | Post-shaper monitor forces zero even if shaper emitted residual | P0.1 |
| T-B1 | Missing/malformed/stale scan → HOLD, `scan_fallback_count` does not authorize vx>0 | P0.2 |
| T-B2 | `allow_scan_missing_fallback` false on product default YAML | P0.2 |
| T-B3 | Pose LOST/DEGRADED (physical flag) → HOLD | P0.3 |
| T-C1 | `test_resume_also_restores_the_executive_task_record` **pass** (xfail removed) | P0.4 |
| T-C2 | Invariant: channel enabled ⇒ task not `suspended` | P0.4 |
| T-C3 | Hold still clears ResumeIntents; resume after Hold does not resurrect | N6 D3 |
| T-D1 | `sketch_come` → ApproachOwner; success disables controller | P0.5 |
| T-D2 | `sketch_follow` remains persistent; band ≠ task success | P0.5 |
| T-E1 | NavigateTo admission pin (searchable≠visible) unchanged | preserve |
| T-E2 | Relation registry: `come` not alias of `follow`; ApproachOwner witness | P1.5 subset |
| T-E3 | Terminal success cites `witness_id` / registry predicate | N6 |

### 7.2 Regression suites (no SR claim inflation)

- `tests/test_motion_shaping.py` — rewrite entry point 6; keep E-stop pins 1–5, 7–9.
- `tests/test_closed_intent_product_path.py` — resume pair.
- `tests/test_traffic_aware.py` — pure layer identity (D1 must not break).
- `tests/test_relation_registry.py` — JEPD proximity family + new approach_owner.
- Voice e2e: come vs follow **separate** episodes; do **not** flip N11 xfail in D1.

### 7.3 Eval honesty

- NAV_INSTRUCT: freeze commit/config hashes **before** D1 edits (P0-0); post-fix
  rerun identical episodes (P0-E). Do not promote `derived_rescore`.
- D1 success is **authority/lifecycle green**, not SR≥X.
- Any physical claim blocked until Unitree commissioning + measured envelope.

---

## 8. Migration file touch list

Ordered for reviewable PRs (prefer vertical slices A→C→D→B config).

### 8.1 P0-A — hard-zero post-shaper

| Path | Change |
| --- | --- |
| `src/parcel_robot/navigation/velocity_shaping.py` | Distinguish hard snap vs comfort slew; reset API |
| `src/parcel_robot/runtime.py` | `_dispatch_active` order; call monitor after shape; reset on hard stop |
| `src/parcel_robot/navigation/reactive_safety.py` | Emit stop class; hard stop clears vyaw too |
| `src/parcel_robot/navigation/dynamic_layer.py` | TTC → HARD_SAFETY_STOP classification |
| `src/parcel_robot/authority.py` | Envelope unification helpers if needed |
| `configs/robot.yaml` | `hard_safety_exact_zero`; fix stale “never smoothed” comments |
| `docs/MOTION.md` | Align docs with hard vs comfort |
| `tests/test_motion_shaping.py` | Exact-zero pins |

### 8.2 P0-B — LiDAR/pose HOLD

| Path | Change |
| --- | --- |
| `src/parcel_robot/navigation/grid_navigator.py` | Default fail-closed; stub only under ODD flag |
| `configs/navigation/default.yaml` | `fail_closed_on_missing_scan: true` |
| `configs/navigation/models/grid.yaml` | Mirror flags |
| `configs/navigation/pose.yaml` | Health policy notes; truth = labeled-sim |
| `src/parcel_robot/pose.py` | Export / alias `PoseEstimateV1` fields |
| `src/parcel_robot/contracts/v1.py` or new `contracts/nav_v1.py` | Snapshot/goal/feedback dataclasses |
| Tests under `tests/test_grid_navigator*.py` / new freshness tests | HOLD pins |

### 8.3 P0-C — atomic resume

| Path | Change |
| --- | --- |
| `src/parcel_robot/runtime.py` | `_apply_closed_intent` resume → `task_executive.resume_task` |
| `src/parcel_robot/brain/executive.py` | Ensure resume API binds revision |
| `src/parcel_robot/core/resume.py` | Optional `LifecycleTransaction` helper |
| `docs/PAUSE_SEMANTICS.md` | Mark product path transaction complete when green |
| `tests/test_closed_intent_product_path.py` | Remove xfail; add pairing invariant |
| `backlog/NEXT.md` | Close N14 when green |

### 8.4 P0.5 — ApproachOwner + relations

| Path | Change |
| --- | --- |
| `src/parcel_robot/voice/local_plans.py` | `sketch_come` → ApproachOwner |
| `src/parcel_robot/brain/contracts.py` | Skill enum / PlanIR tokens |
| `src/parcel_robot/brain/compiler.py` | Success facts; `max_attempts` for NavigateTo recovery |
| `src/parcel_robot/brain/validator.py` | ApproachOwner skill table |
| `src/parcel_robot/brain/runtime_adapter.py` | ApproachOwner branch; remove come from DIRECT_FOLLOW_SUCCESS |
| `src/parcel_robot/navigation/relation_registry.py` | Split come alias; register `approach_owner` |
| `src/parcel_robot/navigation/approach.py` | Wire settle witness / release |
| `tests/test_voice_nav_e2e.py` | Come terminates; follow persists |

### 8.5 ABI freeze (P0-F subset)

| Path | Change |
| --- | --- |
| `src/parcel_robot/contracts/nav_v1.py` (**new**) | PoseEstimateV1, PerceptionSnapshotV1, TaskRevisionV1, NavGoalV1, NavFeedbackV1 |
| `scrum/20260807/task_2/designs/DESIGN_D1_CLASSICAL_COMPANION.md` | This doc |
| Optional: `src/parcel_robot/runtime_assets/configs/navigation/default.yaml` | Keep runtime assets in sync |

### 8.6 Explicitly untouched in D1

`route_memory/*` proposers, Nav2 sidecar, MiniCPM/CityWalker, MetaUrban backends,
N11 traffic re-rank (D3), Follow-Bench adapters, RL envs.

---

## 9. Risks & UNVERIFIED

### 9.1 Engineering risks

| Risk | Mitigation |
| --- | --- |
| Exact-zero feels “jerky” to Sport / trips gait | Keep comfort class for non-safety; commission Sport stop separately; log overshoot |
| HOLD on intermittent LiDAR starves city demos | Loud reason codes; labeled-sim ODD flag for CI only; fix sync rather than re-open stub on product |
| Atomic resume deadlocks if task resume fails mid-TX | Transaction rollback; channel stays paused; user-visible “still paused” |
| ApproachOwner still uses weak identity in sim | Accept for D1; never silent nearest-person; physical blocked on enrollment (P1) |
| Unifying stop floors changes BARN clearances | Freeze BARN experiment YAMLs; product default separate from barn overlays |
| Recovery `max_attempts>1` re-opens infinite loops | Hard cap + executable allowlist only; progress watchdog |

### 9.2 UNVERIFIED register (inherited + D1-specific)

| ID | Claim | Verify by |
| --- | --- | --- |
| U-stop | `obstacle_stop_floor_m≈0.6–0.8` safe at cruise ~0.9 m/s under Sport | Instrumented stop → `a_meas`, `τ_e2e` |
| U-shaper | Residual ticks’ outdoor contact contribution | Post-fix P0-A traces + hardware |
| U-ZsZr | `Zs=Zr=0` outdoors acceptable | Calibrated intrusion + pose covariance |
| U-Unitree-2m | Manual ≥2 m as autonomy envelope | OEM-pinned PDF + policy choice |
| U-Sport-track | grid/RPP tracking acceptable on Go2 gait | EDU tracking/overshoot logs |
| U-timeout | Proposed 0.25 s LiDAR timeout | Load test under CPU/GPU co-residency |
| U-N11 | D1 does not claim sidewalk e2e | D3 mid-mission re-rank + dwell |
| U-U31 | Capability SR after substrate fix | Paired freeze post-D1, not during |
| U-follow-grid | Full formation→grid (P1) needed for walls | D1 allows ApproachOwner via grid; persistent follow may lag |

### 9.3 What would falsify D1

1. Hard-zero pin cannot be met without Sport faults → revisit comfort/hard split or Sport StopMove path.
2. Product HOLD rate makes NavigateTo eval unusable even with healthy synthetic scans → scan contract bug, not reason to restore open-loop stub.
3. Resume atomicity requires executive rewrite beyond `resume_task` wiring → escalate design, do not half-wire channel-only again.

---

## 10. Implementation order (recommended)

```text
PR1  P0-A hard-zero monitor + tests          (blocks physical + model A/B)
PR2  P0-C atomic resume + xfail removal
PR3  P0-B fail-closed grid defaults + pose health
PR4  ApproachOwner skill split + registry come alias removal
PR5  ABI dataclasses + NavFeedback telemetry fields
PR6  NavigateTo recovery max_attempts executable subset
```

Do not start D2 shadow proposers or D3 N11 polish until **PR1–PR3** are green
on product-path pins.

---

## Bottom line

D1 ships the fail-closed classical companion the thesis demands: **PlanIR
authorizes, `grid_v1` writes, post-shaper monitor forces exact zero, missing
sense HOLDs, pause/resume is one transaction, come approaches and releases.**
No learned policy enters the motion path. Learned proposers and Nav2 remain
consumers of these ABIs later — never replacements for them.
