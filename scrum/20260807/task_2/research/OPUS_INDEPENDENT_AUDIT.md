# Opus independent code audit — Parcel nav + instruction

**Auditor role:** Claude Opus stand-in (independent of prior task_2 drafts).  
**Date:** 2026-08-07.  
**Code basis:** `main` @ `4f6342d` plus dirty working tree (not a frozen patch digest).  
**Scope:** Navigation + instruction product path — residual shaper velocity,
LiDAR open-loop fallback, pause/resume authority mismatch, follow vs planner,
oracle semantics, N11 near-miss — plus named strengths (PlanIR, GoalRegion,
`traffic_aware`, NavigateTo admission).  
**Method:** Source read with file:line verification; targeted pytest; one
shaper residual measurement. This is a software authority audit, not a physical
safety certificate.

**Verdict:** Prior stack audit claims on the six hazards are **confirmed**.
The stack is not cleared for unsupervised physical motion. Highest residual
risk is **stop ordering** (nonzero command after proximity/TTC veto), then
**missing-LiDAR open-loop translation**, then **resume that moves without an
active executive task**.

---

## Targeted evidence

```text
.parcel/bin/python -m pytest \
  tests/test_motion_shaping.py::test_stop_entry_point_6_a_proximity_stop_is_not_smoothed \
  tests/test_closed_intent_product_path.py::test_resume_also_restores_the_executive_task_record \
  tests/test_closed_intent_product_path.py::test_resume_restores_the_paused_channel \
  tests/test_traffic_aware.py -q
→ 58 passed, 1 xfailed, 3 warnings in 0.42s
```

| Check | Result | Meaning |
| --- | --- | --- |
| Proximity-stop “unsmoothed” test | **passes** | Only asserts emergency drop > jerk-limited drop — **does not** require exact zero |
| Resume channel restore | **passes** | Channel motion returns |
| Resume executive task restore | **xfail** | Task stays `suspended` while channel drives |
| `test_traffic_aware` | **all pass** | Pure N11 layer contract holds |

Shaper residual measurement (accel=2.0 m/s², dt=0.1 s, cruise 0.6 m/s):

```text
pre_stop_vx=0.6000
post_emergency_tick_vx=0.4000   # not zero
ticks_to_zero_from_cruise=3
```

---

## Findings ranked by safety

Severity key: **S0** contact/motion without authority on the same tick;
**S1** can authorize unsafe translation or lose lifecycle shields;
**S2** capability/correctness that becomes unsafe under real sensing;
**S3** measured product gap without immediate open-loop contact risk.

### S0.1 — Confirmed: proximity/TTC stop can emit residual shaped velocity

| Field | Value |
| --- | --- |
| Status | **VERIFIED** |
| Hazard | Ordinary collision-gate stop does not force exact-zero at HAL on the stop tick |
| Why S0 | After every authority above the shaper has asked for stop, the actuator still receives nonzero SE(2) |

**Evidence**

1. Dispatch order: collision gate → shaper → `ControlManager.set_target`
   (`runtime.py:3825-3876`). Comment at `3832-3834` claims stops route to an
   emergency bypass so “no stop decision is ever smoothed.”
2. “Bypass” sets `emergency=stopping` on `SCurveVelocityShaper.step`
   (`runtime.py:3969-3973`).
3. Emergency branch **slews toward zero at `max_accel * dt_s`**, not snap-to-zero
   (`velocity_shaping.py:102-105`).
4. Proximity-stop path does **not** call `_reset_motion_shaper()` inside
   `_dispatch_active` (reset is used by E-stop / `stop_motion` / intent expiry /
   terminal stop entry points — see `runtime.py:4010+` and tests 1–5, 7–9).
5. `test_stop_entry_point_6_a_proximity_stop_is_not_smoothed`
   (`test_motion_shaping.py:395-414`) only compares drop rates; it **preserves**
   residual motion as acceptable.
6. Docs are stale relative to this behavior: `docs/MOTION.md:60` (“every stop
   uses the emergency bypass”) reads as hard-zero to a reader; measured
   emergency tick leaves `0.4 m/s` from a `0.6 m/s` cruise under typical limits.

**Not confused with:** latched `emergency_stop()` → `ControlManager.emergency_stop()`
plus `_reset_motion_shaper()` (`runtime.py:2040-2056`). Explicit E-stop is a
different path.

**Fix bar (agree with P0-A):** distinguish comfort vs hard safety stop; after
shaper, re-evaluate raw-sensor veto and force exact zero; reset smoother/shaper;
assert HAL command `== 0` on the same dispatch.

---

### S0.2 — Confirmed: missing calibrated LiDAR falls back to open-loop translation

| Field | Value |
| --- | --- |
| Status | **VERIFIED** (default product path) |
| Hazard | `grid_v1` without a calibrated scan commands the point-goal stub |
| Why S0 | Occupancy mapping off → translation without the mapped obstacle plan |

**Evidence**

1. Shipping config: `configs/navigation/default.yaml:5-8` — `active_model: grid_v1`,
   documents loud degrade to point-goal stub when scan contract absent.
2. Default constructor: `safe_valley_micro_advance: bool = False`
   (`grid_navigator.py:99`).
3. Missing scan branch (`grid_navigator.py:335-357`):
   - if `safe_valley_micro_advance` → HOLD (`calibrated_lidar_unavailable`);
   - **else** → `self._fallback.act(...)` with note `scan_missing_fallback`,
     incrementing `scan_fallback_count` and warning once per transition.
4. Opt-in challenger is the fail-closed path; the **shipping default is the
   open-loop fallback**.

**Related (S1 soft-layer):** one malformed dynamic-track payload disables the
entire social cost layer for that tick (`grid_navigator.py:496-505`). Loud and
static-map-safe, but weakens crowd avoidance — secondary to LiDAR open-loop.

**Fix bar (agree with P0-B):** physical / production profile must HOLD/STOP on
stale, missing, malformed, or frame-invalid LiDAR/pose; never open a fallback
translation path. Sim may keep labeled degrade only under explicit ODD flags.

---

### S1.1 — Confirmed: pause/resume restores the channel, not the executive task

| Field | Value |
| --- | --- |
| Status | **VERIFIED** (product path; pinned xfail) |
| Hazard | Motion resumes while authorizing task stays `suspended` |
| Why S1 | Timeouts, verification, recovery no longer run over the moving channel |

**Evidence**

1. Pause path suspends channels **and** interrupts executive tasks
   (`runtime.py:1418-1451`).
2. Resume path only walks `("navigation", "follow", "search")` and calls
   `_resume_from_store` (`runtime.py:1453-1465`). **No**
   `task_executive.resume_task(...)`.
3. `_resume_from_store` reacquires channel authority and calls
   `channel_obj.resume` (`runtime.py:2617-2675`) — channel-only.
4. Strict product-path pin:
   `test_resume_also_restores_the_executive_task_record`
   (`test_closed_intent_product_path.py:306-334`, reason documents measured
   split: navigation returns to `searching` / `navigation_resumed` while task
   remains `suspended:closed_intent_pause`).
5. This audit re-ran that test → **xfail** (defect still present). Sibling
   `test_resume_restores_the_paused_channel` → **pass** (proves the half-wire).

**Fix bar (agree with P0-C):** atomic `{task_id, revision, step_id, channel,
results}` suspend/resume; channel must not reacquire base without active task
revision.

---

### S1.2 — Confirmed: follow bypasses the obstacle-aware planner

| Field | Value |
| --- | --- |
| Status | **VERIFIED** |
| Hazard | Owner follow emits proportional SE(2) toward owner/behind point |
| Why S1 | Local nearest-obstacle gate only; cannot route around wall/crowd; “behind” may be occluded |

**Evidence**

1. Direct mode (`follow.py:596-658`): compute `dx/dy` to owner (or lead),
   `vx = distance_error * gain`, `vyaw` from heading error; obstacle handling is
   stop/slow on `nearest_obstacle_m` / bearing cone — **no** grid plan, A*, or
   formation goal submission.
2. Behind mode (`follow.py:660+`) same family: formation geometry → velocity,
   not a short-TTL goal into `grid_v1`.
3. Contrast: destination navigation uses rolling occupancy + A*
   (`grid_navigator.py` / `grid_planner.py`). Follow never enters that path.

**Fix bar (agree with P1-C / architecture board):** formation-goal generator →
same metric planner as NavigateTo; independent geometry shield remains outside.

---

### S2.1 — Confirmed: semantic product path is still oracle-shaped at T0

| Field | Value |
| --- | --- |
| Status | **VERIFIED** |
| Hazard | Mission-path semantics are simulator truth round-tripped as “detections” |
| Why S2 | Physical transfer and eval claims over-state perception readiness |

**Evidence**

1. Perception default `tier: T0` (`configs/navigation/default.yaml:43-60`) —
   documented as byte-identical to pre-chain oracle read.
2. Chain module states previous direct oracle read; T0 is identity pass-through
   of caller dict objects (`perception_chain.py:1-20`, `299-335`).
3. Runtime still feeds `semantic_candidates_from_observation(observation)` into
   nav extras (`runtime.py:4284`).
4. Pose seam ships `provider: truth` (`configs/navigation/pose.yaml:11`) — no
   SLAM/EKF; truth is the shipping default by construction.

**Honest positive:** the chain is now the **one** ingress (structural
improvement). T0 equality is intentional and labeled — but it must not be
mistaken for sensor-faithful perception.

**Fix bar:** real camera–LiDAR producers; agent bags reject oracle fields
(already sketched in bag schema); truth only in labeled sim.

---

### S3.1 — Confirmed: N11 near-miss residual (wired, xfail not flipped)

| Field | Value |
| --- | --- |
| Status | **VERIFIED** as residual capability gap (not S0 open-loop) |
| Hazard | Pedestrian sidewalk case still fails after traffic-aware wiring |
| Why S3 | Progress exists; failure is final-metre / clock near-miss, not contact in the pin |

**Evidence**

1. Pure layer present and tested: `navigation/traffic_aware.py` (`rank_approach_candidates`,
   `RampMemory`); approach seam calls ranking (`approach.py:372+`); runtime seeds
   shaper from ramp memory (`runtime.py:3977-4008`).
2. E2E pin `test_go_to_the_sidewalk_with_pedestrian_traffic`
   (`test_voice_nav_e2e.py:413-442`): post-wiring measurement — travel ~2.09 m to
   `(-0.28, 2.07)`, **~0.33 m outside** sidewalk `GoalRegion`, fail
   `step_timeout` at 240 s NavigateTo budget. Reason text: moved from “stuck”
   to “near-miss on the clock.”
3. `test_traffic_aware.py` all green in this audit — pure contract ≠ e2e gate.

**Interpretation:** N11 landed partial value (placement + yield-advance). Residual
belongs to final-approach / proxemic policy under traffic, not to “traffic_aware
unwired.” Do not treat green unit tests as sidewalk e2e clearance.

---

## Strengths (preserve)

Ranked by how much they reduce systemic risk if kept intact:

### 1. Typed PlanIR + fail-closed validation

- `PlanIR` is a bounded, field-exact contract (`brain/contracts.py:421+`).
- Validator skill tables pin NavigateTo preconditions and recovery vocabulary
  (`brain/validator.py:214-241`).
- Language never directly owns motors; compiler/validator sit between model and
  executive. **Keep** as the sole dispatch authority for high-level skills.

### 2. NavigateTo admission: searchable ≠ visible

- Pin module `brain/navigate_admission.py:19-33` —
  required `{camera_fresh, lidar_fresh, base_available}`; forbids
  `target_grounded` at admission.
- Mirrored in validator NavigateTo contract (`validator.py:221-231`) with
  historical note that requiring grounded visibility dead-ended
  “go to the sidewalk.”
- **Keep:** grounding-with-recovery remains NavigateTo’s job; admission must
  not demand frustum presence.

### 3. GoalRegion as independent arrival authority

- Typed `disc` / `polygon` / `relative_band` with `contains` / `distance_to`
  (`instructnav/scoring.py:143-216`).
- E2E and walk-with-me evals score against GoalRegion, not planner `arrived`
  strings. **Keep** separating semantic success from controller chatter.

### 4. `traffic_aware` pure layer + approach wiring

- Stdlib-pure ranking and `RampMemory` with explicit safety argument: memory is
  not a gate (`traffic_aware.py:1-46`, `403+`).
- Approach uses rank-then-proxemic-veto (veto cannot re-rank into the stream)
  (`approach.py:360-389`).
- Yield-advance seed clamped to already-authorized `command.vx` and dropped on
  stopping ticks (`runtime.py:3983-4008`).
- **Keep** the purity/ladder rules; finish final-metre policy to flip N11 e2e.

---

## Cross-check vs `CURRENT_STACK_AUDIT.md`

| Prior claim | This audit |
| --- | --- |
| P0.1 residual shaper velocity | **Confirm** — stronger: measured 0.6→0.4 m/s on one emergency tick; proximity test encodes the bug |
| P0.2 LiDAR open-loop | **Confirm** — default `safe_valley_micro_advance=False` is the load-bearing detail |
| P0.4 resume split | **Confirm** — xfail still red on product path |
| P1.1 follow bypasses planner | **Confirm** — `follow.py` direct/behind velocity laws |
| P1.4 oracle semantics | **Confirm** — T0 + truth pose |
| N11 near-miss | **Confirm** — e2e reason string + green pure tests |
| Strengths PlanIR / GoalRegion / traffic / admission | **Confirm** — cite as preserve list above |

No contradiction found that would demote S0.1–S0.2. Pose-health / Unitree
uncommissioned (prior P0.3 / P0.7) remain true but were out of the six-item
verify list; they still block physical claims.

---

## Recommended fix order (safety)

1. **Exact-zero hard stop after shaper** (S0.1) — same-tick HAL zero + reset.
2. **Fail-closed LiDAR/pose for any translating profile** (S0.2).
3. **Atomic pause/resume across executive + channel** (S1.1).
4. **Follow → formation goals through common planner** (S1.2).
5. **Replace T0/truth producers on product path** (S2.1).
6. **Final-metre traffic approach to flip N11 e2e** (S3.1) — after safety
   ordering is honest enough that yield-advance cannot be misread as a gate bypass.

Do **not** start learned navigation A/B until 1–3 have regression tests that
fail closed under sensor loss and stop veto.
