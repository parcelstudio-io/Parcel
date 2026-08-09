# DEEP Design D1 — Fail-closed classical companion

**Author role:** Claude Opus deep-design stand-in (inherit relaunch)
**Date:** 2026-08-07
**Status:** engineer-ready multi-pass implementation design
**Depth bar:** `designs/deep/README.md` (binding) — ≥1200 dense lines, ≥3 passes,
≥20 file:line cites, worked scenarios, why-it-works + falsifiers, complete
pseudocode, pass log, UNVERIFIED register, acceptance matrix.
**v0 contrast only:** `../DESIGN_D1_CLASSICAL_COMPANION.md` (too shallow; do not pad-copy).
**Differentiator:** **No learned policies in the motion path.** Hard-zero
post-shaper, LiDAR HOLD, atomic resume, ApproachOwner, NavigateTo ladder,
relation witnesses, V1 ABIs. Nav2 / MiniCPM / CityWalker / RL ranker are
out of scope for D1 live authority.
**Safety status:** Research + implementation design only. Not a physical
certification case. Software E-stop ≠ hardware E-stop.
**Inputs re-derived against code:** `RESEARCH_THESIS.md`,
`research/OPUS_INDEPENDENT_AUDIT.md`, `research/N1_CLASSICAL_NAV.md`,
`research/N5_SAFETY_AUTHORITY.md`, `research/N6_EXECUTIVE_BEHAVIOR.md`,
`TARGET_ARCHITECTURE.md`, plus live source under `src/parcel_robot/` and
product-path pins in `tests/test_motion_shaping.py` /
`tests/test_closed_intent_product_path.py`.

---

## 0. Pass log (binding)

| Pass | Mode | What was done | Outcome |
| --- | --- | --- | --- |
| 1 | Inventory + measure | Enumerated every velocity writer / stop entry /
| | | resume / come-follow / scan-fallback call site; measured residual
| | | `vx` under shipped and audit shaper limits | Residual confirmed;
| | | 28 call-site rows; defect map locked |
| 2 | Full design draft | Algorithms, ABIs, tick order, configs, migration,
| | | worked scenario, test matrix from Pass-1 evidence | First complete
| | | design draft |
| 3 | Adversarial rewrite | Attacked residual-zero claim, HOLD starvation,
| | | resume deadlock, ApproachOwner identity, person_stop units,
| | | dual-smoother risk; rewrote weak sections | Hardened invariants +
| | | falsifiers |
| 4 | Density / gap fill | Expanded call-site inventory, second worked
| | | scenario (come vs follow), complete monitor pseudocode, ABI
| | | rejection tables, acceptance matrix rows | Line bar cleared |

This file is the **v1 deep** artifact. Do not treat v0 as authoritative.

---

## 1. Pass 1 — Call-site inventory and residual measurement

### 1.1 Measurement protocol

Residual velocity after a declared proximity/TTC hard stop is the first
blocker for any model A/B or physical claim. Pass 1 re-measured the shaper
directly (same math the runtime uses) rather than trusting docs.

```text
from parcel_robot.navigation.velocity_shaping import SCurveVelocityShaper, ShaperLimits
# shipped configs/robot.yaml motion.shaping:
#   linear_max_accel: 1.2, linear_max_jerk: 3.0
shaper.reset((0.6, 0.0, 0.0))
v = shaper.step((0.0,0.0,0.0), dt_s=0.1, emergency=True)
```

### 1.2 Measured residuals (2026-08-07, this design pass)

| Condition | Prior shaped state | Post-emergency tick | Ticks to exact 0 |
| --- | --- | --- | --- |
| Audit accel=2.0 m/s², cruise 0.6 | `(0.6,0,0)` | **`vx=0.40`** | 3 |
| Shipped accel=1.2 m/s², cruise 0.6 | `(0.6,0,0)` | **`vx=0.48`** | **5** |
| Shipped + full SE2 `(0.6,0.2,0.5)` | same | **`(0.48, 0.08, 0.35)`** | >1 |
| Comfort (emergency=False) from 0.6 | `(0.6,0,0)` | `vx≈0.576` | many |
| Emergency drop vs comfort drop | — | drop 0.12 vs 0.024 | — |

**Interpretation:** `emergency=True` only removes the jerk limit. It still
slews at `max_accel * dt` (`velocity_shaping.py:102-105`). At shipped
`linear_max_accel: 1.2` and typical `dt_s≈0.1` (`runtime.py:3967`), a
proximity stop that the gate declared as `"stopped"` still hands the HAL
**0.48 m/s** on that same dispatch. Latched E-stop is a *different* path
that resets the shaper; ordinary sensor stops do not.

### 1.3 Velocity writers and stop entry points (inventory)

Every path that can put SE(2) on Sport / the sim backend must be classified
as: **AUTHORIZE**, **TIGHTEN**, **ZERO**, or **BYPASS**. D1 forbids any
layer from widening an upstream envelope.

| # | Site | File:line | Class today | D1 required class |
| --- | --- | --- | --- | --- |
| V1 | Arbiter current intent | `runtime.py:3800-3805` | AUTHORIZE | AUTHORIZE |
| V2 | `VelocitySmoother.step` | `runtime.py:3802-3804` | TIGHTEN (slew) | TIGHTEN |
| V3 | Rotate-in-place brake | `runtime.py:3806-3816` | TIGHTEN (zero vx/vy) | TIGHTEN |
| V4 | `_collision_safe` / reactive | `runtime.py:3825-3828` | TIGHTEN/ZERO intent | TIGHTEN + classify |
| V5 | `velocity_smoother.force` | `runtime.py:3831` | sync smoother | keep |
| V6 | `_shape_for_actuator` | `runtime.py:3835-3847` | TIGHTEN (emergency slew) | **split HARD snap** |
| V7 | `ControlManager.set_target` | `runtime.py:3871-3876` | HAL write | HAL write of monitor out |
| V8 | Intent-expired stop | `runtime.py:3888-3898` | ZERO + reset | ZERO + reset |
| V9 | `emergency_stop` | `runtime.py:2040-2050` | ZERO + latch | ZERO + latch |
| V10 | `_brain_hold` | `runtime.py:2010-2038` | ZERO + clear ResumeIntent | keep destructive |
| V11 | `stop_motion` | `runtime.py` stop path | ZERO + reset | keep |
| V12 | Watchdog sync | `runtime.py:4023-4040` | reset shaper | keep |
| V13 | Yield-advance seed | `runtime.py:3977-4008` | raise ramp ≤ cmd | keep; drop on HARD |
| V14 | `grid_v1.act` plan track | `grid_navigator.py:320+` | AUTHORIZE local | AUTHORIZE if scan/pose OK |
| V15 | Stub fallback | `grid_navigator.py:353-357` | **AUTHORIZE open-loop** | **FORBIDDEN product** |
| V16 | `_safe_valley_hold` | `grid_navigator.py:337-341` | ZERO | ZERO default product |
| V17 | Follow proportional | `follow.py:596-658` | AUTHORIZE (no grid) | still enters brake→shape→monitor |
| V18 | Approach pose sampler | `approach.py:21-120` | goal propose | goal propose only |
| V19 | Pace cap | `_pace_cap` via closed intent | TIGHTEN scale | TIGHTEN |
| V20 | TTC scale multiply | `runtime.py:4472-4477` | TIGHTEN | TIGHTEN + HARD class |
| V21 | Reactive `_stop_translation` | `reactive_safety.py:196-197` | zero vx/vy, keep vyaw | HARD; clear vyaw too |
| V22 | ControlManager watchdog | `control/manager.py:25+` | ZERO hardware | ZERO + shaper sync |
| V23 | Sport Move/Stop | ControlManager → backend | actuator | Sport owns gait |
| V24 | ★ HardZeroMonitor (NEW) | post-shaper | — | **ZERO / elementwise-min** |
| V25 | NavigateTo skill feedback | `runtime_adapter.py` | lifecycle | witness-gated |
| V26 | FollowFormation success | `runtime_adapter.py:35,412-438` | terminal while enabled | ApproachOwner split |
| V27 | Resume channel | `runtime.py:1453-1465` | channel only | **atomic w/ task** |
| V28 | `resume_task` API | `executive.py:645-660` | exists unused | must be called |

### 1.4 Closed-intent / lifecycle call sites

| Site | File:line | Today | D1 |
| --- | --- | --- | --- |
| Pause channels + interrupt tasks | `runtime.py:1418-1451` | correct two-layer pause | keep |
| Resume channels only | `runtime.py:1453-1465` | **half-wire** | call `resume_task` first |
| `_resume_from_store` | `runtime.py:2617-2675` | channel reacquire | after task resume |
| `_brain_hold` clears ResumeIntent | `runtime.py:2019-2023` | destructive | keep |
| Product pin xfail | `test_closed_intent_product_path.py:306-334` | red/xfail | must pass |
| Channel restore pin | `test_closed_intent_product_path.py:293-303` | green | keep |

### 1.5 Come / follow / relation call sites

| Site | File:line | Today | D1 |
| --- | --- | --- | --- |
| `sketch_come` | `local_plans.py:68-92` | `FollowFormation` relation=`follow` | `ApproachOwner` |
| Registry alias `come`→`follow` | `relation_registry.py:323-340` | come≡follow | remove come alias |
| `DIRECT_FOLLOW_SUCCESS_STATES` | `runtime_adapter.py:35` | `{following,holding}` terminal | follow: checkpoints only |
| Come product path | `test_closed_intent_product_path.py:375-384` | asserts FollowFormation | assert ApproachOwner |
| Compiler `max_attempts=1` | `compiler.py:140` | hard-forced | allow 2 for executable recovery only |
| NavigateTo admission pin | `navigate_admission.py:19-33` | searchable≠visible | **preserve** |

### 1.6 LiDAR / pose fail-open call sites

| Site | File:line | Today | D1 |
| --- | --- | --- | --- |
| `active_model: grid_v1` | `configs/navigation/default.yaml:8` | product | keep writer |
| Missing-scan stub fallback | `grid_navigator.py:335-357` | open-loop default | HOLD default |
| `safe_valley_micro_advance=False` | `grid_navigator.py:99` | opt-in HOLD | flip product default |
| Scan contract parse | `grid_navigator.py:964-990` | None → fallback | None → HOLD product |
| Pose provider truth | `configs/navigation/pose.yaml:11` | labeled-sim OK | physical fail-closed |
| `PoseHealth` enum | `pose.py` (PoseHealth) | exists | consume in translating profiles |
| Perception tier T0 | `default.yaml:59-60` | oracle pass-through | honesty label only |

### 1.7 Safety envelope / person_stop defect (P0.8)

`SafetyEnvelope.person_stop` (`authority.py:610-617`) adds
`person_latency_factor * reaction_latency_s` (seconds·dimensionless) to a
distance. That is dimensionally invalid. D1 must not claim physical person
clearance until this is repaired to a measured distance allowance or
`v_close * τ`. Recorded as UNVERIFIED U-P0.8; classical companion still ships
with obstacle `stop_distance(v)` which is dimensionally consistent
(`authority.py:598-608`).

### 1.8 Pass-1 verdict

1. Residual shaped velocity after proximity stop is **VERIFIED** at 0.48 m/s
   (shipped) / 0.40 m/s (audit accel).
2. Missing-scan open-loop fallback is **VERIFIED** as the product default.
3. Resume half-wire is **VERIFIED** (xfail still documents the split).
4. Come≡follow is **VERIFIED** in sketch + registry + adapter success set.
5. PlanIR → compiler → validator → TaskExecutive shape is **sound** and must
   be preserved; defects are composition holes, not missing VLAs.

---

## 2. Goals / non-goals

### 2.1 Goals (Phase-0 shippable substrate)

| ID | Goal | Exit evidence |
| --- | --- | --- |
| G1 | Exact-zero hard safety stop on same dispatch that declares proximity/TTC hard-stop | HAL/`ControlManager` command `(vx,vy,vyaw)==(0,0,0)`; shaper+smoother reset; pin replaces residual-ok test |
| G2 | Fail-closed LiDAR/pose on product/physical profiles | Missing, stale, malformed, or frame-invalid scan/pose/transform → HOLD `(0,0,0)` note; never StubNavigator translation |
| G3 | Atomic pause/resume over `{task_id, revision, step_id, channel}` | Closed-intent resume restores executive task **and** channel; xfail → pass; channel enable ⇒ authorizing revision active |
| G4 | `ApproachOwner` ≠ `FollowFormation` | Come/summons terminates + releases `base`; follow stays persistent until Hold/cancel |
| G5 | NavigateTo grounding ladder remains searchable≠visible; terminates only via relation witness | Admission pin preserved; recovery bounded; GoalRegion/registry is sole arrival authority |
| G6 | Relation witnesses totalized for product speech acts D1 claims | One `RelationSpec` drives grammar, sketch, success facts, hold duration, release policy |
| G7 | Typed V1 ABIs frozen for pose/perception/task revision/nav goal/feedback/safety | Dataclass schemas in §5; consumers reject unknown/malformed fail-closed |
| G8 | Preserve PlanIR → compiler → validator → TaskExecutive; Sport owns gait; elementwise-min authority | No language→motor shortcut; no second velocity writer |

### 2.2 Non-goals (explicit)

1. **No learned motion policies** — no VLA, MPPI-as-authority, MiniCPM,
   CityWalker, RL ranker, or `NavProposalV1` consumer on the live path.
2. **No Nav2 authority migration** — keep in-process `grid_v1`; Nav2 remains
   exclusive challenger (D2). Steal Collision Monitor *ordering* only.
3. **No physical commissioning / Sport e2e latency claim** — leave `a_meas`,
   `τ_e2e`, Unitree 2 m guidance as UNVERIFIED (§12).
4. **No T0→R2 perception replacement** — truth pose / T0 semantics stay
   labeled-sim; D1 only forbids pretending they are product localization.
5. **No N11 e2e flip** — mid-mission re-rank + dwell `inside` belong to D3;
   D1 must not weaken person-stop to "make progress."
6. **No formation-follow planner rewrite as blocking G1–G3** — follow→common
   planner is P1; D1 may stub ApproachOwner through existing approach/grid
   path without solving full RPF.
7. **No dual smoother** — one S-curve / velocity smoother owner; post-shaper
   monitor never re-smooths.
8. **No unsupervised physical deployability claim** from sim zeros.

### 2.3 P0 defect map (what D1 closes)

| Defect | Audit | Evidence (Pass 1) | D1 mechanism |
| --- | --- | --- | --- |
| P0.1 / S0.1 residual shaper velocity | N5, Opus audit | §1.2 table; `velocity_shaping.py:102-105` | Hard-zero post-shaper (§4.1) |
| P0.2 / S0.2 LiDAR open-loop | N5, Opus audit | `grid_navigator.py:335-357` | Product HOLD (§4.2) |
| P0.3 truth pose as production | thesis | `pose.yaml:11` | Typed health + fail-closed (§5.1, §4.2) |
| P0.4 / S1.1 resume split | N6, Opus audit | `runtime.py:1453-1465`; xfail | Atomic lifecycle (§4.3) |
| P0.5 come≡follow | N6 | `local_plans.py:68-92`; registry | ApproachOwner (§4.5) |
| P0.6 recovery/invariants | N6 | `compiler.py:140` | Bounded ladder (§4.4, §4.6) |
| P0.8 person_stop units | thesis | `authority.py:610-617` | Fix formula; do not claim clearance (§12) |

---

## 3. ASCII system diagram

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

**Ordering rule (Nav2 Collision Monitor lesson, N1/N5):** geometry veto after
every smoother. Parcel already gates *before* the shaper
(`runtime.py:3825-3847`); D1 adds the missing *after* assert.

---

## 4. Algorithms (complete implementable pseudocode)

### 4.1 Hard-zero post-shaper (G1 / P0.1)

#### 4.1.1 Why the current path fails

Dispatch order today (`runtime.py:3796-3876`):

```text
arbiter intent
  → VelocitySmoother.step
  → _collision_safe  (reactive proximity + TTC)
  → velocity_smoother.force(gated)
  → _shape_for_actuator(..., stopping= proximity=="stopped" | …)
  → ControlManager.set_target(shaped)
```

Comments claim stops are never smoothed (`runtime.py:3832-3834`,
`configs/robot.yaml:147-150`). The "bypass" only sets `emergency=True` on
`SCurveVelocityShaper.step` (`runtime.py:3969-3973`), which slews:

```102:105:src/parcel_robot/navigation/velocity_shaping.py
            if emergency:
                next_velocity = _move_toward(velocity, 0.0, limits.max_accel * dt_s)
                self._acceleration[index] = (next_velocity - velocity) / dt_s
                self._velocity[index] = next_velocity
```

Proximity `_stop_translation` preserves `vyaw` (`reactive_safety.py:196-197`),
so a pure geometric stop can also hand nonzero yaw into the same slew.
The pin `test_stop_entry_point_6_a_proximity_stop_is_not_smoothed`
(`test_motion_shaping.py:395-414`) only asserts `bypass_drop > smoothed_drop`
— it **encodes** residual motion as acceptable.

Latched E-stop *does* reset (`runtime.py:2040+`, `_reset_motion_shaper` at
`4010-4021`). The defect is ordinary sensor safety stops that stay inside
`_dispatch_active` and only flip `stopping=True`.

#### 4.1.2 Stop classes

```text
enum StopClass:
  NONE
  COMFORT_STOP      # owner soft stop, pace change, yield ramp, soft scale
  HARD_SAFETY_STOP  # proximity/TTC/freshness/E-stop latch/monitor veto
```

Comfort may slew. Hard safety must snap. Mixing them is how residual survives.

#### 4.1.3 Complete algorithm

```text
fn classify_stop(proximity_state, ttc_scale, sensor_health, arbiter) -> StopClass:
  if arbiter.emergency_stopped:
    return HARD_SAFETY_STOP
  if proximity_state == "stopped":
    return HARD_SAFETY_STOP
  if ttc_scale is not None and ttc_scale <= 0.0:
    return HARD_SAFETY_STOP
  if sensor_health.required_source_invalid:   # see §4.2
    return HARD_SAFETY_STOP
  if proximity_state == "slowing" or (ttc_scale is not None and ttc_scale < 1.0):
    return COMFORT_STOP
  return NONE

fn shape_and_gate(intent_cmd, obs, proximity_state, ttc_scale, arbiter) -> VelocityCommand:
  # Pre-shaper (existing): never raise a stop
  gated = apply_proximity_ttc(intent_cmd, proximity_state, ttc_scale)
  # HARD geometric stop clears translation AND yaw (change vs today)
  stop_class = classify_stop(proximity_state, ttc_scale, sensor_health(obs), arbiter)
  if stop_class == HARD_SAFETY_STOP:
    gated = VelocityCommand(0, 0, 0)

  if stop_class == HARD_SAFETY_STOP:
    # Skip comfort shaping entirely for the actuator-visible command.
    shaped = VelocityCommand(0, 0, 0)
    reset_velocity_smoother()
    reset_motion_shaper()          # clears internal vx/vy/vyaw + accel state
    latch_hard_stop_reason(proximity_state, ttc_scale, sensor_health(obs))
    # Still run post-monitor for telemetry + double-check
    return hard_zero_monitor(shaped, obs, stop_class, prior_intent=intent_cmd)

  shaped = scurve_shaper.step(gated, emergency=(stop_class == COMFORT_STOP))
  # ★ POST-SHAPER RE-ASSERT (Nav2 Collision Monitor ordering, in-process)
  return hard_zero_monitor(shaped, obs, stop_class, prior_intent=intent_cmd)

fn hard_zero_monitor(shaped, obs, prior_stop_class, prior_intent) -> VelocityCommand:
  # Uses freshest LiDAR ranges / nearest_obstacle / TTC against *shaped* cmd
  # and SafetyEnvelope.stop_distance(v=‖shaped.v‖). Never widens.
  verdict = reevaluate_raw_geometry(obs, shaped)

  if prior_stop_class == HARD_SAFETY_STOP or verdict.requires_hard_stop:
    reset_velocity_smoother()
    reset_motion_shaper()
    return VelocityCommand(0, 0, 0)   # exact; including vyaw

  if not required_sources_fresh(obs):
    reset_velocity_smoother()
    reset_motion_shaper()
    return VelocityCommand(0, 0, 0, note="monitor_source_timeout")

  # Monitor may only scale down (elementwise |cmd| min), never up
  limited = elementwise_min_abs(shaped, verdict.max_cmd)
  limited = elementwise_min_abs(limited, arbitrate_limits(...))
  return limited

fn elementwise_min_abs(a, b) -> VelocityCommand:
  return VelocityCommand(
    vx = copysign(min(abs(a.vx), abs(b.vx)), a.vx) if a.vx != 0 else 0,
    vy = ...,
    vyaw = ...,
  )
```

#### 4.1.4 Integration into `_dispatch_active`

```text
fn _dispatch_active_D1():
  with command_lock:
    sync_shaper_with_control_watchdog()
    now = monotonic()
    active = arbiter.current(now)
    intent = smoother.step(active.command) if active else ZERO
    apply_rotate_in_place_brake(intent, active)   # existing 3806-3816
    gated, proximity_state, ttc_scale = collision_safe(intent, obs)
    stop_class = classify_stop(...)
    smoother.force(gated if stop_class != HARD else ZERO)
    final = shape_and_gate(gated, obs, proximity_state, ttc_scale, arbiter)
    # INVARIANT: HARD ⇒ final==(0,0,0) ∧ shaper_reset ∧ smoother_reset
    publish_nav_feedback(cmd_pre=gated, cmd_post=final, stop_class)
    if latched_estop: control_manager.emergency_stop(); return
    control_manager.set_target(final, source=active.source, ttl=...)
```

#### 4.1.5 Pin (replaces residual-ok test)

On the stop tick, observed HAL target must satisfy
`abs(vx)+abs(vy)+abs(vyaw) == 0` (float exact after reset). Replace
`bypass_drop > smoothed_drop` as sole proximity criterion in
`test_stop_entry_point_6_a_proximity_stop_is_not_smoothed`. Keep comfort
tests proving COMFORT may slew.

#### 4.1.6 Why it works

1. **Separates intent from actuator truth.** Gate already can emit zero
   translation; actuator lied because shaper retained state. Resetting state
   + forcing exact zero makes actuator truth match gate truth on the same
   tick.
2. **Nav2 ordering.** Collision Monitor after smoother is the industry
   pattern N1 cites; Parcel already has pre-shaper gate; post-shaper closes
   the hole without importing ROS.
3. **Comfort preserved.** Soft slowing / arousal calm / yield-advance still
   use the S-curve; only HARD snaps. Avoids Sport gait thrash on every
   soft scale.
4. **Elementwise-min only.** Monitor cannot invent motion; matches existing
   authority triple (arbiter limits × envelope × leases).

#### 4.1.7 Falsifiers

1. Exact-zero pin cannot be met without Sport faults / gait trips → revisit
   comfort/hard split or use Sport StopMove path for HARD; do not re-open
   residual as "acceptable."
2. Post-monitor geometry uses stale ranges and false-zeros clear space →
   freshness contract must HOLD, not invent free space (ties to §4.2).
3. Dual path still reaches `set_target` without monitor (new bypass) →
   inventory regression test: every writer in §1.3 classified.

---

### 4.2 LiDAR / pose HOLD (G2 / P0.2 / P0.3)

#### 4.2.1 Why the current path fails

Shipping config: `active_model: grid_v1` (`default.yaml:8`) documents loud
degrade to point-goal stub when scan contract absent. Default constructor
`safe_valley_micro_advance=False` (`grid_navigator.py:99`). Missing scan:

```335:357:src/parcel_robot/navigation/grid_navigator.py
        scan = self._scan_from_observation(observation)
        if scan is None:
            if self.safe_valley_micro_advance:
                return self._safe_valley_hold("calibrated_lidar_unavailable")
            ...
            command = self._fallback.act(observation, mission)
            fallback_note = "scan_missing_fallback"
            ...
            return replace(command, note=fallback_note)
```

`_scan_from_observation` (`964-990`) returns `None` on wrong ranges type/length
or non-numeric calib. Stub then translates toward the goal without occupancy.
Fail-closed HOLD exists only on opt-in safe-valley YAMLs.

Pose ships `provider: truth` (`pose.yaml:11`) — labeled-sim OK; not product
localization. `PoseHealth` exists in `pose.py` but translating product
profiles do not yet fail-closed on DEGRADED/LOST.

#### 4.2.2 Complete algorithm

```text
fn scan_contract_ok(obs) -> Result[CalibratedScan, HoldReason]:
  if ranges missing or wrong length/type: return Err(MALFORMED)
  if calib (angle_min, increment, range_max, ...) non-numeric: return Err(MALFORMED)
  if stamp age > lidar_source_timeout_s: return Err(STALE)
  if |lidar_stamp - odom_stamp| > timestamp_slop_s: return Err(FRAME_SKEW)
  if transform lidar→base missing/invalid: return Err(TRANSFORM)
  if any range non-finite after stride: return Err(MALFORMED)
  return Ok(scan)

fn pose_contract_ok(pose: PoseEstimateV1, profile) -> Result[(), HoldReason]:
  if pose.health == LOST: return Err(POSE_LOST)
  if profile.requires_healthy_pose and pose.health == DEGRADED:
    return Err(POSE_DEGRADED)
  if pose age > pose_source_timeout_s: return Err(POSE_STALE)
  if covariance invalid / non-PSD: return Err(COVARIANCE_INVALID)
  if frame not in {odom, map}: return Err(FRAME_UNKNOWN)
  if profile.physical and not pose.calibration_id: return Err(CALIBRATION_MISSING)
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

#### 4.2.3 Default flip

Product `grid_v1` sets `fail_closed_on_missing_scan: true` (equivalent to
today's opt-in `safe_valley_micro_advance` HOLD branch for the *missing-scan*
case). Stub fallback requires explicit
`odd.allow_scan_missing_fallback: true` + `profile != physical`.

Physical overlay: `allow_scan_missing_fallback` hard-false regardless of YAML
attempt to enable; `pose.provider` ≠ truth; `calibration_id` required.

#### 4.2.4 Why it works

1. Occupancy is the free-space authority for `grid_v1`. Without a calibrated
   scan, the planner's premise is false — continuing translation is motion
   without mapped obstacle authority (S0.2).
2. Nav2 `source_timeout` → STOP is the same fail-closed lesson; Parcel
   already has HOLD code behind a flag; D1 flips the default.
3. Labeled-sim ODD keeps CI demos runnable without lying that stub is product.

#### 4.2.5 Falsifiers

1. Product HOLD rate makes NavigateTo eval unusable even with healthy
   synthetic scans → scan contract bug, not reason to restore open-loop stub.
2. Intermittent LiDAR starves city demos → fix sync / timeout budget
   (U-timeout); do not re-open stub on product.
3. Truth pose silently treated as HEALTHY on physical → profile gate must
   reject `provider: truth` when `odd.physical`.

---

### 4.3 Atomic pause / resume (G3 / P0.4)

#### 4.3.1 Why the current path fails

Pause correctly suspends channels **and** executive tasks
(`runtime.py:1418-1451`). Resume only walks channels via `_resume_from_store`
(`runtime.py:1453-1465`) and never calls `task_executive.resume_task`
(`executive.py:645-660`). Product pin documents measured split: channel
returns to `searching` / `navigation_resumed` while task stays
`suspended:closed_intent_pause` (`test_closed_intent_product_path.py:306-334`).

Motion without that step's timeout, verification, or recovery — same shape
as residual velocity: lower layer healthy, authorizing layer offline.

#### 4.3.2 Complete algorithm

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
      if resume_rejection_reason(tx.resume_intent, ...):
        continue  # fail-closed; do not partially enable
      # ★ Order matters: task BEFORE channel base reacquire
      disp = executive.resume_task(tx.task_id, reason="closed_intent_resume")
      if not disp.accepted:
        abort channel enable; report honest failure
        continue
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

Minimal product fix if full `LifecycleTransaction` helper is deferred:

```text
# inside _apply_closed_intent resume branch, BEFORE channel loop:
for row in task_executive.snapshot()["tasks"]:
  if row.state == "suspended" and row.last_detail startswith "suspended:closed_intent":
    task_executive.resume_task(row.task_id, reason="closed_intent_resume")
# then existing _resume_from_store walk
```

This is enough to green the xfail; full transaction binding is the durable
form.

#### 4.3.3 Hold remains destructive

`_brain_hold` clears ResumeIntents (`runtime.py:2019-2023`) and must **not**
call this transaction's resume path. Resume after Hold must not resurrect.

#### 4.3.4 Why it works

1. PLEXIL / ROS 2 action semantics: suspend freezes without declaring
   outcome; resume rebinds the same goal identity (N6).
2. `resume_task` already exists and requeues to `queued` — composition hole,
   not missing API.
3. Ordering (task before channel) prevents the measured split where channel
   drives while verification is offline.

#### 4.3.5 Falsifiers

1. Atomicity requires executive rewrite beyond `resume_task` wiring →
   escalate design; do not half-wire channel-only again.
2. Resume deadlocks if task resume fails mid-TX → rollback; channel stays
   paused; user-visible "still paused."
3. Multiple suspended tasks bind wrong channel → transaction must key
   `{task_id, channel, revision}`.

---

### 4.4 NavigateTo grounding ladder (G5 / P0.6)

Admission unchanged (`camera_fresh ∧ lidar_fresh ∧ base_available`; **not**
`target_grounded`) — pin `navigate_admission.py:19-33`.

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

  cmd_or_hold = grid_v1.act(snap, goal)   # may HOLD per §4.2
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
`max_attempts=2` for `rescan|alternate_candidate` only (not unbounded LLM
retry). Today's hard `max_attempts=1` (`compiler.py:140`) blocks that.

---

### 4.5 ApproachOwner (G4 / P0.5)

#### 4.5.1 Why the current path fails

`sketch_come` compiles to `FollowFormation` with `relation="follow"`
(`local_plans.py:68-92`). Registry aliases `come` onto `follow`
(`relation_registry.py:323-340`) with offer phrase "come to you". Adapter
treats direct follow as terminal success while controller stays enabled:

```text
DIRECT_FOLLOW_SUCCESS_STATES = {"following", "holding"}  # runtime_adapter.py:35
```

Product path asserts FollowFormation on "come here"
(`test_closed_intent_product_path.py:375-384`). Wrong speech act for a
summons (N6): approach should terminate and release `base`.

#### 4.5.2 Complete algorithm

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
  cmd = grid_v1.act(..., goal)   # still brake→shape→monitor

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

**FollowFormation** (unchanged speech act "follow me"): never auto-succeed on
band alone; adapter reports `in_progress` checkpoints; terminal only on
Hold/cancel/lease transfer. Remove `come` from `DIRECT_FOLLOW_SUCCESS` path.

---

### 4.6 Relation witnesses (G6)

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

## 5. Interfaces (V1 ABIs)

All times: **monotonic seconds** (`float`) unless `*_ns` noted. Frames:
`odom` | `map` | `base` | `lidar` | `camera`. Fail-closed: `__post_init__`
raises on non-finite / wrong arity / unknown enum; consumers treat raise /
`None` as HOLD, never as free space.

### 5.1 `PoseEstimateV1`

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
    map_T_odom: tuple[float, ...] | None = None
```

**Failures → HoldReason:** `LOST` | `DEGRADED` (if
`profile.requires_healthy_pose`) | `STALE` | `COVARIANCE_INVALID` |
`FRAME_UNKNOWN` | `CALIBRATION_MISSING`.

**Units:** m, rad, s. **Control consumes ODOM;** semantic goals live in MAP
and must transform through recorded history or reject.

**Truth honesty:** `source=="truth"` allowed only when
`odd_tags` contains `labeled_sim`. Product bags reject oracle fields.

### 5.2 `PerceptionSnapshotV1`

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
    owner: OwnerTrackV1 | None
    dynamic_tracks: tuple[DynamicTrackV1, ...]
    semantic_regions: tuple[SemanticRegionV1, ...]
    evidence_envelope: EvidenceEnvelopeV1 | None
    odd_tags: frozenset[str]
    perception_tier: Literal["T0", "T1", "R2", "R3"]

@dataclass(frozen=True)
class LidarScanV1:
    ranges_m: tuple[float, ...]
    angle_min_rad: float
    angle_increment_rad: float
    range_min_m: float
    range_max_m: float
    stamp_s: float
    frame_id: str
    calibration_id: str
```

**Failures:** missing scan, len mismatch, non-finite range, calib NaN,
age > timeout, skew vs pose, TF miss → monitor/grid HOLD.

### 5.3 `TaskRevisionV1`

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
    relation: str
    args: Mapping[str, object]
    resources: frozenset[str]
    preconditions: frozenset[str]
    success_facts: tuple[str, ...]
    invariants: tuple[str, ...]
    deadline_s: float
    max_attempts: int                 # ≥ 1; recovery must be executable
    recovery: tuple[str, ...]
    interruptibility: Literal["preemptable", "critical", "non_preemptable"]
    persistent: bool
    hold_duration_s: float
    authorizing_channel: str
    parent_task_id: str | None = None
    observation_snapshot_id: str | None = None
```

**Failures:** unknown skill/relation, `max_attempts>1` with empty recovery,
persistent/success_facts mismatch, missing resources for motion skills.

### 5.4 `SafetyEnvelope` (authority — keep, unify floors)

Existing `parcel_robot.authority.SafetyEnvelope`; D1 makes it the **sole**
stop-distance authority and unifies YAML drift.

```text
stop_distance(v) = r_foot + v*τ + v²/(2*a) + Zs + Zr     [m]
# person_stop(v) MUST be repaired (P0.8) before physical claim:
#   BAD today: stop_distance(v) + person_latency_factor * reaction_latency_s
#   FIX: max(person_social_zone_m, stop_distance(v) + v_close*τ_person)
#        or measured distance allowance — never seconds added to metres
```

Current fields (already in `authority.py:478+`): `footprint_radius_m`,
`reaction_latency_s`, `decel_max_mps2`, `sensing_intrusion_m`,
`pose_uncertainty_m`, `person_social_zone_m`, `person_latency_factor`,
`obstacle_comfort_band_m`, `person_comfort_band_m`, `obstacle_stop_floor_m`.
`person_latency_factor` is the deprecated source of the mixed-unit defect.
P0-H replaces it with a typed `person_dynamic_allowance_m` (measured or
derived from bounded relative closing speed × time) and a single declared
`base_center_to_obstacle_surface` clearance convention that includes the
footprint exactly once.

**Policy:** envelope may only widen via measured Zs/Zr/a_meas — never via
model confidence. Soft social costs cannot undercut `stop_distance(v)`.

### 5.5 `NavGoalV1` / `NavFeedbackV1`

```python
@dataclass(frozen=True)
class NavGoalV1:
    goal_id: str
    task_id: str
    plan_revision: int
    step_id: str
    frame: Literal["odom", "map"]
    goal_region: GoalRegionV1
    relation: str
    issued_at_s: float
    expires_at_s: float
    footprint_profile_id: str
    max_speed_mps: float
    allow_reverse: bool
    witness_id: str

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
    cmd_pre_shaper: tuple[float, float, float]
    cmd_post_monitor: tuple[float, float, float]
    stop_class: Literal["NONE", "COMFORT_STOP", "HARD_SAFETY_STOP"]
    hold_reason: str | None
    verified_facts: tuple[str, ...]
    stamp_s: float
```

Failure statuses are terminal for the `goal_id`; new work needs new
`goal_id` or `plan_revision` bump. `holding` is non-terminal (sensor HOLD).

### 5.6 ABI rejection table (fail-closed consumers)

| Input defect | Consumer | Action |
| --- | --- | --- |
| Non-finite pose / yaw | grid, monitor, approach | HOLD |
| Unknown frame | NavGoal ingest | reject goal |
| Expired `expires_at_s` | grid | reject / HOLD |
| Revision mismatch vs active task | adapter | reject / fail step |
| `lidar is None` on product | grid | HOLD (`MALFORMED`/`MISSING`) |
| `health=LOST` translating | grid/monitor | HARD_SAFETY_STOP |
| Unknown skill string | validator | plan reject |
| `max_attempts>1` empty recovery | compiler/validator | plan reject |
| `persistent=True` with release-on-success | registry | register reject |
| Oracle fields without `labeled_sim` | bag ingest | reject bag |

---

## 6. Tick nav logic (full ordering)

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
- `channel.enabled ∧ owns(base) ⇒ ∃ active TaskRevisionV1`

---

## 7. Worked scenario A — proximity hard-stop at cruise (hardest safety case)

### 7.1 Setup

| Variable | Value |
| --- | --- |
| Profile | product `grid_v1`, shaping enabled |
| Cruise shaped state | `vx=0.60`, `vy=0`, `vyaw=0` |
| Shipped accel | `linear_max_accel=1.2` m/s² |
| Tick `dt_s` | 0.10 s |
| Obstacle | appears inside stop envelope mid-mission |
| Mission | NavigateTo sidewalk (`inside`), task running |

### 7.2 Tick narrative (D1)

```text
t0  OBSERVE: scan OK, pose HEALTHY, nearest_obstacle_m = 0.55 m
    envelope.stop_distance(v=0.60) ≈ r + 0.60*τ + 0.60²/(2a) + …
    (exact metres depend on commissioned τ,a — UNVERIFIED U-stop)
    reactive gate → proximity_state="stopped", gated intent (0,0,0)

t0  CLASSIFY: HARD_SAFETY_STOP

t0  SHAPER: skipped for actuator path; reset smoother+shaper
    _last_shaped := (0,0,0); _shaped_at := None

t0  MONITOR: prior_stop_class=HARD → re-assert (0,0,0)
    note: hard_stop:proximity

t0  HAL: set_target(0,0,0)
    INVARIANT HOLD: abs(vx)+abs(vy)+abs(vyaw)==0

t0+  NavFeedbackV1.status="holding", stop_class=HARD_SAFETY_STOP
     task remains running (non-outcome); recovery may backoff
```

### 7.3 Contrast: today (pre-D1) same tick

```text
t0  gate → stopped, intent ~ (0, vyaw?)
t0  shaper emergency slew: vx := 0.60 - 1.2*0.1 = 0.48
t0  HAL receives vx=0.48  ← residual motion after declared stop
t1  vx=0.36 … t5 vx=0.00
```

Pass-1 measured this residual (§1.2). Pin today accepts it
(`bypass_drop > smoothed_drop`).

### 7.4 Failure branches

| Branch | Handling |
| --- | --- |
| Scan becomes None on next tick | HOLD via §4.2; still HARD zero |
| Owner says "resume" during hard stop | resume rejected while HARD latched / E-stop |
| Comfort slowing only ("slowing") | COMFORT slew allowed; monitor may still min |
| Latched E-stop concurrent | ControlManager.emergency_stop path; shaper reset |
| Yield-advance seed pending | dropped because stopping (§4.1; `3977-4008`) |

---

## 8. Worked scenario B — pause → resume atomicity + come vs follow

### 8.1 Pause/resume product path

```text
1. handle_text("go to the sidewalk")
   → PlanSketch NavigateTo relation=inside
   → compile/validate → TaskExecutive task state=running
   → navigation channel enabled, searching/tracking

2. handle_text("pause")
   → _apply_closed_intent suspend=True
   → pause navigation/follow/search + ResumeIntent
   → InterruptRequest → task state=suspended:closed_intent_pause
   → channel state=paused, directive preserved

3. handle_text("resume")  [D1]
   BEGIN TX
     resume_task(task_id) → state=queued  ★ NEW
     assert not suspended
     _resume_from_store("navigation") → channel searching, navigation_resumed
   COMMIT
   → _step_brain redispatches adapter; timeouts/verification live again

TODAY (pre-D1) step 3: channel resumes; task stays suspended (xfail).
```

### 8.2 Come vs follow

```text
COME:
  handle_text("come here")
  → sketch_come → ApproachOwner (D1) / FollowFormation (today)
  → approach settles in band, stop_confirmed, settle_hold
  → succeeded; release base; follow.enabled=False

FOLLOW:
  handle_text("follow me")
  → FollowFormation persistent
  → checkpoints following/holding; NEVER task success on band alone
  → terminal only Hold/cancel/lease transfer
```

### 8.3 State variables to assert in tests

| After | Assert |
| --- | --- |
| pause | nav.state=paused; tasks include suspended; ResumeIntent present |
| resume D1 | nav.state≠paused; no suspended for that task; ResumeIntent consumed |
| Hold after pause | ResumeIntent cleared; resume → "nothing paused" |
| come success | ApproachOwner skill; follow.enabled=False; base released |
| follow band | follow.enabled=True; task not succeeded |

---

## 9. Config defaults

```yaml
# configs/navigation/default.yaml  (D1 deltas)
active_model: grid_v1

grid_v1:
  fail_closed_on_missing_scan: true
  fail_closed_on_stale_scan: true
  fail_closed_on_pose_unhealthy: true
  lidar_source_timeout_s: 0.25
  pose_source_timeout_s: 0.20
  timestamp_slop_s: 0.02
  allow_scan_missing_fallback: false

safety:
  max_vx: 0.9
  max_vy: 0.25
  max_vyaw: 0.8
  obstacle_stop_floor_m: 0.6
  predictive_mode: projected_speed_cap

motion.smoothing:                      # configs/robot.yaml
  linear_max_accel: 1.2
  hard_safety_exact_zero: true         # NEW

pose:
  provider: truth                      # labeled-sim OK; physical must not ship
  require_healthy_for_translation: true

perception:
  tier: T0

executive:
  navigate_to_max_attempts: 2
  navigate_to_recovery: [rescan, alternate_candidate, safe_stop]
  approach_owner_settle_hold_s: 0.5
  resume_intent_ttl_s: 120.0
  atomic_resume: true

odd:
  labeled_sim: true
  physical: false
  allow_scan_missing_fallback: false
```

**Physical profile overlay:** `pose.provider` ≠ truth; `odd.physical: true`;
`calibration_id` required; `allow_scan_missing_fallback` hard-false.

---

## 10. Test / eval gates

### 10.1 Blocking unit / product-path pins (must go green)

| Gate | Test / assertion | Defect |
| --- | --- | --- |
| T-A1 | Proximity/TTC hard-stop tick: HAL cmd exact zero; shaper state zero | P0.1 |
| T-A2 | Comfort stop may slew; hard stop must not | P0.1 |
| T-A3 | Post-shaper monitor forces zero even if shaper emitted residual | P0.1 |
| T-A4 | HARD stop clears vyaw (change vs `_stop_translation` keep-yaw) | P0.1 |
| T-A5 | Yield-advance seed dropped on HARD tick | P0.1 |
| T-B1 | Missing/malformed/stale scan → HOLD; `scan_fallback_count` does not authorize vx>0 | P0.2 |
| T-B2 | `allow_scan_missing_fallback` false on product default YAML | P0.2 |
| T-B3 | Pose LOST/DEGRADED (physical flag) → HOLD | P0.3 |
| T-B4 | Frame skew lidar↔odom → HOLD | P0.2 |
| T-C1 | `test_resume_also_restores_the_executive_task_record` **pass** (xfail removed) | P0.4 |
| T-C2 | Invariant: channel enabled ⇒ task not `suspended` | P0.4 |
| T-C3 | Hold still clears ResumeIntents; resume after Hold does not resurrect | N6 |
| T-C4 | Resume with nothing paused remains honest refusal | preserve |
| T-D1 | `sketch_come` → ApproachOwner; success disables controller | P0.5 |
| T-D2 | `sketch_follow` remains persistent; band ≠ task success | P0.5 |
| T-D3 | Registry: `come` not alias of `follow` | P0.5 |
| T-E1 | NavigateTo admission pin (searchable≠visible) unchanged | preserve |
| T-E2 | Terminal success cites `witness_id` / registry predicate | N6 |
| T-E3 | `max_attempts=2` only with executable recovery allowlist | P0.6 |
| T-F1 | `person_stop` units test: no seconds added to metres | P0.8 |

### 10.2 Regression suites (no SR claim inflation)

- `tests/test_motion_shaping.py` — rewrite entry point 6; keep E-stop pins 1–5, 7–9.
- `tests/test_closed_intent_product_path.py` — resume pair; come→ApproachOwner.
- `tests/test_traffic_aware.py` — pure layer identity (D1 must not break).
- `tests/test_relation_registry.py` — JEPD proximity family + new approach_owner.
- Voice e2e: come vs follow **separate** episodes; do **not** flip N11 xfail in D1.

### 10.3 Eval honesty

- NAV_INSTRUCT: freeze commit/config hashes **before** D1 edits (P0-0); post-fix
  rerun identical episodes (P0-E). Do not promote `derived_rescore`.
- D1 success is **authority/lifecycle green**, not SR≥X.
- Any physical claim blocked until Unitree commissioning + measured envelope.
- Frozen headline NAV_INSTRUCT SR remains **1/25** until a new freeze; D1 does
  not invent capability.

### 10.4 Acceptance test matrix (executable checklist)

| ID | Procedure | Pass criterion | Blocking? |
| --- | --- | --- | --- |
| A1 | Unit: shaper at cruise + HARD classify | post-monitor cmd==(0,0,0) | Y |
| A2 | Runtime `_dispatch_active` with synthetic near obstacle | `_last_sent` exact zero | Y |
| A3 | Comfort slowing without HARD | residual allowed but ≤ gated | Y |
| B1 | grid act with lidar=None, product YAML | note HOLD; vx==0 | Y |
| B2 | labeled_sim ODD flag true | stub allowed with loud note | N |
| B3 | pose health LOST + physical | HOLD | Y |
| C1 | handle_text sidewalk→pause→resume→_step_brain | no suspended task | Y |
| C2 | pairing invariant property test | enabled⇒¬suspended | Y |
| C3 | Hold then resume | honest nothing-paused | Y |
| D1 | handle_text come here | ApproachOwner skill list | Y |
| D2 | settle witness | follow.enabled False | Y |
| D3 | follow me band enter | task not succeeded | Y |
| E1 | admission contract assert | searchable≠visible | Y |
| E2 | traffic_aware suite | all pass | Y |
| E3 | N11 e2e | still xfail OK in D1 | N |

---

## 11. Migration file touch list

Ordered for reviewable PRs (prefer vertical slices A→C→D→B config).

### 11.1 P0-A — hard-zero post-shaper

| Path | Change |
| --- | --- |
| `src/parcel_robot/navigation/velocity_shaping.py` | Distinguish hard snap vs comfort slew; reset API |
| `src/parcel_robot/runtime.py` | `_dispatch_active` order; call monitor after shape; reset on hard stop |
| `src/parcel_robot/navigation/reactive_safety.py` | Emit stop class; hard stop clears vyaw too |
| `src/parcel_robot/navigation/dynamic_layer.py` | TTC → HARD_SAFETY_STOP classification |
| `src/parcel_robot/authority.py` | Envelope unification helpers; fix person_stop units |
| `configs/robot.yaml` | `hard_safety_exact_zero`; fix stale "never smoothed" comments |
| `docs/MOTION.md` | Align docs with hard vs comfort |
| `tests/test_motion_shaping.py` | Exact-zero pins |

### 11.2 P0-B — LiDAR/pose HOLD

| Path | Change |
| --- | --- |
| `src/parcel_robot/navigation/grid_navigator.py` | Default fail-closed; stub only under ODD flag |
| `configs/navigation/default.yaml` | `fail_closed_on_missing_scan: true` |
| `configs/navigation/models/grid.yaml` | Mirror flags |
| `configs/navigation/pose.yaml` | Health policy notes; truth = labeled-sim |
| `src/parcel_robot/pose.py` | Export / alias `PoseEstimateV1` fields |
| `src/parcel_robot/contracts/v1.py` or new `contracts/nav_v1.py` | Snapshot/goal/feedback dataclasses |
| Tests under `tests/test_grid_navigator*.py` / new freshness tests | HOLD pins |

### 11.3 P0-C — atomic resume

| Path | Change |
| --- | --- |
| `src/parcel_robot/runtime.py` | `_apply_closed_intent` resume → `task_executive.resume_task` |
| `src/parcel_robot/brain/executive.py` | Ensure resume API binds revision |
| `src/parcel_robot/core/resume.py` | Optional `LifecycleTransaction` helper |
| `docs/PAUSE_SEMANTICS.md` | Mark product path transaction complete when green |
| `tests/test_closed_intent_product_path.py` | Remove xfail; add pairing invariant |
| `backlog/NEXT.md` | Close N14 when green |

### 11.4 P0.5 — ApproachOwner + relations

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

### 11.5 ABI freeze (P0-F subset)

| Path | Change |
| --- | --- |
| `src/parcel_robot/contracts/nav_v1.py` (**new**) | PoseEstimateV1, PerceptionSnapshotV1, TaskRevisionV1, NavGoalV1, NavFeedbackV1 |
| `scrum/20260807/task_2/designs/deep/DEEP_D1_CLASSICAL_COMPANION.md` | This doc |
| Optional: `src/parcel_robot/runtime_assets/configs/navigation/default.yaml` | Keep runtime assets in sync |

### 11.6 Explicitly untouched in D1

`route_memory/*` proposers, Nav2 sidecar, MiniCPM/CityWalker, MetaUrban backends,
N11 traffic re-rank (D3), Follow-Bench adapters, RL envs.

### 11.7 Implementation order

```text
PR1  P0-A hard-zero monitor + tests          (blocks physical + model A/B)
PR2  P0-C atomic resume + xfail removal
PR3  P0-B fail-closed grid defaults + pose health
PR4  ApproachOwner skill split + registry come alias removal
PR5  ABI dataclasses + NavFeedback telemetry fields
PR6  NavigateTo recovery max_attempts executable subset
PR7  person_stop dimensional fix (authority.py) + pins
```

Do not start D2 shadow proposers or D3 N11 polish until **PR1–PR3** are green
on product-path pins.

---

## 12. Risks, UNVERIFIED register, falsifiers

### 12.1 Engineering risks

| Risk | Mitigation |
| --- | --- |
| Exact-zero feels "jerky" to Sport / trips gait | Keep comfort class for non-safety; commission Sport stop separately; log overshoot |
| HOLD on intermittent LiDAR starves city demos | Loud reason codes; labeled-sim ODD flag for CI only; fix sync rather than re-open stub on product |
| Atomic resume deadlocks if task resume fails mid-TX | Transaction rollback; channel stays paused; user-visible "still paused" |
| ApproachOwner still uses weak identity in sim | Accept for D1; never silent nearest-person; physical blocked on enrollment (P1) |
| Unifying stop floors changes BARN clearances | Freeze BARN experiment YAMLs; product default separate from barn overlays |
| Recovery `max_attempts>1` re-opens infinite loops | Hard cap + executable allowlist only; progress watchdog |
| Dual smoother if monitor re-ramps | Monitor never re-smooths; only min/zero |
| Docs drift again claiming "never smoothed" | Rewrite robot.yaml + MOTION.md in same PR as code |

### 12.2 UNVERIFIED register

| ID | Claim | Verify by |
| --- | --- | --- |
| U-stop | `obstacle_stop_floor_m≈0.6–0.8` safe at cruise ~0.9 m/s under Sport | Instrumented stop → `a_meas`, `τ_e2e` |
| U-shaper | Residual ticks' outdoor contact contribution | Post-fix P0-A traces + hardware |
| U-ZsZr | `Zs=Zr=0` outdoors acceptable | Calibrated intrusion + pose covariance |
| U-Unitree-2m | Manual ≥2 m as autonomy envelope | OEM-pinned PDF + policy choice |
| U-Sport-track | grid/RPP tracking acceptable on Go2 gait | EDU tracking/overshoot logs |
| U-timeout | Proposed 0.25 s LiDAR timeout | Load test under CPU/GPU co-residency |
| U-N11 | D1 does not claim sidewalk e2e | D3 mid-mission re-rank + dwell |
| U-U31 | Capability SR after substrate fix | Paired freeze post-D1, not during |
| U-follow-grid | Full formation→grid (P1) needed for walls | D1 allows ApproachOwner via grid; persistent follow may lag |
| U-P0.8 | person_stop dimensional repair preserves intended clearance | Re-derive from measured `v_close`, footprint convention |
| U-τ | `reaction_latency_s` matches Sport e2e | Commissioning ledger |
| U-a | `decel_max_mps2` matches measured brake | Commissioning ledger |

### 12.3 What would falsify D1 (global)

1. Hard-zero pin cannot be met without Sport faults → revisit comfort/hard
   split or Sport StopMove path.
2. Product HOLD rate makes NavigateTo eval unusable even with healthy
   synthetic scans → scan contract bug, not reason to restore open-loop stub.
3. Resume atomicity requires executive rewrite beyond `resume_task` wiring →
   escalate design, do not half-wire channel-only again.
4. ApproachOwner cannot release base without breaking follow leasing →
   redesign resource table before shipping come.
5. Post-shaper monitor widens any command in a fuzz test → abort D1 ship.
6. Any learned proposer writes `set_target` without TaskRevisionV1 →
   architecture violation; belongs in D2 shadow only.

---

## 13. Pass 3 — Adversarial self-critique and rewrites

### 13.1 Attack: "Exact zero will thrash Sport gait"

**Attack.** Snapping to zero every proximity tick may trip Unitree Sport or
cause oscillatory stand/sit. Residual slew was "comfortable."

**Rewrite.** D1 already splits COMFORT vs HARD. Soft "slowing" and TTC
partial scales remain slewable. Only `proximity==stopped`, `ttc_scale<=0`,
freshness miss, and latched E-stop snap. Commissioning may route HARD to
Sport StopMove while keeping SE(2) zero at the Parcel HAL boundary. Residual
as safety policy is rejected; comfort lives in COMFORT class.

### 13.2 Attack: "HOLD on missing scan breaks CI city demos"

**Attack.** Default HOLD will red city headless jobs that omit calibrated
scans.

**Rewrite.** Explicit `odd.labeled_sim` + `allow_scan_missing_fallback` for
CI only. Product/physical hard-false. Demo scripts that relied on silent
stub must opt in loudly — that is the point.

### 13.3 Attack: "resume_task alone is not a transaction"

**Attack.** Calling `resume_task` then `_resume_from_store` can still leave
partial state if channel resume raises.

**Rewrite.** §4.3 requires: on channel failure, re-suspend or fail the task
and abort channel enable. Minimal wiring greens the xfail; durable form is
`LifecycleTransaction` with rollback. Pairing invariant test is mandatory.

### 13.4 Attack: "ApproachOwner via grid still needs owner identity"

**Attack.** Sim-perfect owner track makes ApproachOwner look solved; physical
reacquire is P1.

**Rewrite.** D1 forbids nearest-person substitute on LOST/AMBIGUOUS. Physical
ApproachOwner blocked on enrollment (P1). Sim may use labeled owner track
under honesty tags.

### 13.5 Attack: "person_stop still wrong — D1 safety claim invalid"

**Attack.** Leaving P0.8 open means person envelope is not trustworthy.

**Rewrite.** PR7 fixes dimensional formula before any person-clearance
claim. Obstacle `stop_distance(v)` remains the geometric HARD authority for
P0-A. Soft social costs must not undercut it. Document U-P0.8 explicitly.

### 13.6 Attack: "Post-monitor is a second smoother"

**Attack.** Re-evaluating geometry and scaling could reintroduce slew.

**Rewrite.** Monitor API is only `{exact_zero, elementwise_min_abs}`. No
accel/jerk integration inside the monitor. Telemetry may record would-be
shaped residual without sending it.

### 13.7 Attack: "v0 already said this — deep doc is pad"

**Attack.** Depth bar requires re-derive, not pad-copy.

**Rewrite evidence.** Pass 1 re-measured residuals under shipped accel 1.2
(0.48 m/s, 5 ticks) and full SE2 residual; inventoried 28 writer sites;
cited live xfail text; tied person_stop units defect; expanded come/follow
adapter success-set behavior; specified rollback on resume; added second
worked scenario and acceptance matrix. v0 lacked measurement tables,
adversarial falsifiers, and call-site inventory.

---

## 14. Pass 4 — Gap fill (density and missing edges)

### 14.1 ControlManager contract (HAL boundary)

`ControlManager` (`control/manager.py:25+`) is the single writer, feedback
watchdog, and lifecycle owner for locomotion. D1 rules:

1. Only `_dispatch_active`'s post-monitor command (or explicit
   emergency/stop/hold paths) may call `set_target` / `stop` /
   `emergency_stop`.
2. Watchdog stops bump `_watchdog_stops`; runtime sync resets shaper
   (`runtime.py:4023-4040`) — preserve.
3. TTL leases remain; expired command → stop + shaper reset (entry point 5).
4. Sport owns gait; Parcel emits body twist only.

### 14.2 Pre-shaper gate details that interact with HARD class

- Reactive proximity `_stop_translation` currently keeps `vyaw`
  (`reactive_safety.py:196-197`). D1 HARD clears yaw.
- TTC may force `scale<=0` and rewrite proximity to `"stopped"`
  (`dynamic_layer.py` / `runtime.py:4472-4477`). Classify as HARD.
- Partial TTC scale in (0,1) is COMFORT unless other HARD predicates fire.

### 14.3 Validator / compiler skill table deltas

| Skill | Preconditions | Success | Recovery |
| --- | --- | --- | --- |
| NavigateTo | camera_fresh, lidar_fresh, base_available | registry witness | rescan, alternate_candidate, safe_stop |
| ApproachOwner | camera_fresh, base_available, owner_trackable | approach_settled | safe_stop |
| FollowFormation | camera_fresh, base_available (+ heading for behind) | none auto (persistent) | wait, safe_stop |
| Hold | — | skill_completed settle | — |

Validator rejects `target_grounded` on NavigateTo admission (preserve pin).
Compiler stops forcing `max_attempts=1` for NavigateTo when recovery ⊆
allowlist; still caps at 3 (`contracts.py:366-367`).

### 14.4 Telemetry fields required for bisect

Every HARD stop tick must log:

```text
stop_class, proximity_state, ttc_scale,
cmd_pre_shaper, cmd_post_monitor,
shaper_reset: bool, smoother_reset: bool,
hold_reason, nearest_obstacle_m, pose.health,
task_id, plan_revision, step_id
```

Without this, residual regressions hide behind "it felt slow."

### 14.5 Dual-path audit: follow still enters monitor

Follow proportional twist (`follow.py:596-658`) is P1 for planner parity,
but D1 requires it still enter `_collision_safe` → shape → HardZeroMonitor
→ `set_target`. No HAL bypass for follow. ApproachOwner should prefer
short-TTL `NavGoalV1` into `grid_v1` when scan OK.

### 14.6 Literature / practice anchors (why mechanisms work)

| Mechanism | Anchor | Parcel mapping |
| --- | --- | --- |
| Post-smoother collision monitor | Nav2 Collision Monitor | HardZeroMonitor |
| source_timeout → STOP | Nav2 | scan/pose freshness HOLD |
| stop_distance(v) | ISO-shaped envelope in `authority.py` | sole floor |
| Suspend ≠ outcome | PLEXIL | TaskExecutive suspend/resume |
| Goal identity continuity | ROS 2 actions | ResumeIntent + task_id |
| searchable≠visible | VLN grounding practice | navigate_admission pin |
| Formation ≠ approach | Follow-Bench / RPF | ApproachOwner split |
| Elementwise-min authority | in-repo arbiter/limits | monitor never widens |

### 14.7 Explicit anti-patterns D1 rejects

1. Language model emitting raw `(vx,vy,vyaw)`.
2. Learned critic raising speed above gated command.
3. Silent stub translation on product when scan missing.
4. Channel motion without active task revision.
5. `come` aliasing `follow` in registry.
6. Pinning tests that encode residual as success.
7. Claiming T0/truth as real localization.
8. Flipping N11 e2e to green by weakening person-stop.

---

## 15. Correctness argument (summary)

### 15.1 Invariants

I1. `HARD_SAFETY_STOP` on tick t ⇒ `cmd_post_monitor(t)==(0,0,0)` and shaper
    state zero.
I2. Product translating profile ∧ (¬scan_ok ∨ ¬pose_ok) ⇒ HOLD zero.
I3. `channel.enabled ∧ owns(base)` ⇒ ∃ active non-suspended `TaskRevisionV1`.
I4. Skill `succeeded` ⇒ registry witness (+ settle if required).
I5. Monitor output ≤ elementwise abs of its input and of arbiter limits.
I6. Hold clears ResumeIntent; cannot resurrect via resume.
I7. No learned module in the live `set_target` path.

### 15.2 Why composition closes S0/S1

- S0.1 closed by I1 + post-shaper placement.
- S0.2 closed by I2 + default flip.
- S1.1 closed by I3 + resume ordering.
- P0.5 closed by ApproachOwner + I4.
- Authority shape preserved by I5 + I7.

### 15.3 What remains outside D1 (honest)

Follow around walls (P1), owner ReID (P1), N11 final metre (D3), Nav2
sidecar (D2), physical commissioning (P5), person_stop numeric clearance
until PR7 + U-P0.8 verification.

---

## 16. Bottom line

D1 ships the fail-closed classical companion the thesis demands: **PlanIR
authorizes, `grid_v1` writes, post-shaper monitor forces exact zero, missing
sense HOLDs, pause/resume is one transaction, come approaches and releases.**
No learned policy enters the motion path. Learned proposers and Nav2 remain
consumers of these ABIs later — never replacements for them.

Pass-1 measured residual **0.48 m/s** on the stop tick under shipped limits;
that alone falsifies "every stop is unsmoothed" documentation. D1 replaces
the documentation with a pin: HAL command exact zero on HARD stops.

---

## Appendix A — File:line cite index (≥20)

| # | Claim | Cite |
| --- | --- | --- |
| 1 | Dispatch gate then shaper | `runtime.py:3825-3847` |
| 2 | Emergency slew not snap | `velocity_shaping.py:102-105` |
| 3 | Shaper step call | `runtime.py:3969-3973` |
| 4 | dt clamp ~0.1 | `runtime.py:3967` |
| 5 | Stale "never smoothed" comment | `runtime.py:3832-3834` |
| 6 | YAML stale claim | `configs/robot.yaml:147-150` |
| 7 | Accel 1.2 shipped | `configs/robot.yaml:154` |
| 8 | Residual pin compares drops only | `test_motion_shaping.py:395-414` |
| 9 | E-stop resets shaper | `runtime.py:2040-2050` |
| 10 | `_reset_motion_shaper` | `runtime.py:4010-4021` |
| 11 | Missing scan stub fallback | `grid_navigator.py:335-357` |
| 12 | safe_valley default False | `grid_navigator.py:99` |
| 13 | Scan parse None | `grid_navigator.py:964-990` |
| 14 | active_model grid_v1 | `default.yaml:8` |
| 15 | Pause suspends tasks | `runtime.py:1418-1451` |
| 16 | Resume channels only | `runtime.py:1453-1465` |
| 17 | resume_task API | `executive.py:645-660` |
| 18 | Resume xfail pin | `test_closed_intent_product_path.py:306-334` |
| 19 | sketch_come → FollowFormation | `local_plans.py:68-92` |
| 20 | come alias follow | `relation_registry.py:323-340` |
| 21 | DIRECT_FOLLOW_SUCCESS_STATES | `runtime_adapter.py:35` |
| 22 | Follow success while enabled | `runtime_adapter.py:412-438` |
| 23 | Come product asserts FollowFormation | `test_closed_intent_product_path.py:375-384` |
| 24 | NavigateTo admission pin | `navigate_admission.py:19-33` |
| 25 | compiler max_attempts=1 | `compiler.py:140` |
| 26 | _stop_translation keeps vyaw | `reactive_safety.py:196-197` |
| 27 | person_stop units bug | `authority.py:610-617` |
| 28 | stop_distance formula | `authority.py:598-608` |
| 29 | Hold clears ResumeIntent | `runtime.py:2019-2023` |
| 30 | Yield-advance seed | `runtime.py:3977-4008` |
| 31 | Watchdog shaper sync | `runtime.py:4023-4040` |
| 32 | ControlManager single writer | `control/manager.py:25+` |
| 33 | pose provider truth | `pose.yaml:11` |
| 34 | perception T0 | `default.yaml:59-60` |
| 35 | Channel resume restore green | `test_closed_intent_product_path.py:293-303` |

---

## Appendix B — Pass log (detailed)

```text
PASS 1 — Inventory + measure
  - Enumerated V1–V28 velocity/lifecycle writers
  - Measured residual: shipped 0.48 m/s (5 ticks); audit 0.40; SE2 residual
  - Confirmed xfail resume split; come≡follow; scan stub default
  - Outcome: defect map locked; no design yet

PASS 2 — Full design
  - Algorithms §4.1–4.6 complete pseudocode
  - ABIs §5; tick order §6; scenarios §7–8; config §9
  - Outcome: first complete engineer-ready draft

PASS 3 — Adversarial rewrite
  - Attacks: Sport thrash, CI HOLD starvation, resume partial TX,
    identity weakness, person_stop units, dual smoother, pad-copy
  - Rewrites: comfort/hard split emphasis; ODD flags; rollback; PR7;
    monitor API restriction; measurement evidence vs v0
  - Outcome: falsifiers hardened

PASS 4 — Gap fill
  - ControlManager contract; gate/yaw interaction; validator tables;
    telemetry; follow-into-monitor; literature anchors; anti-patterns;
    cite index; acceptance matrix
  - Outcome: depth bar cleared; ready for team review
```

---

## Appendix C — Residual measurement transcript (Pass 1)

```text
shipped linear_max_accel 1.2
shipped linear_max_jerk 3.0
audit accel=2.0 cruise=0.6 post_emergency (0.4, 0.0, 0.0)
shipped accel=1.2 cruise=0.6 emergency ticks:
  [(1, 0.48), (2, 0.36), (3, 0.24), (4, 0.12), (5, 0.0)]
shipped with full SE2 residual after 1 emergency tick
  (0.48, 0.08, 0.35)
emergency drop 0.12  smooth drop 0.024
residual_em 0.48  residual_sm 0.576
```

This transcript is the binding quantitative evidence that ordinary
`emergency=True` shaping is not a hard safety stop.

---

END DEEP_D1_CLASSICAL_COMPANION
