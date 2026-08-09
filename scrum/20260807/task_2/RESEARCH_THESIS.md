# Parcel research thesis — navigation, instruction, and companion authority

**Date:** 2026-08-07  
**Basis:** Independent Opus research wave (`research/N1`–`N8`, `RL1`, `RL2`,
`OPUS_INDEPENDENT_AUDIT.md`) challenged against prior drafts in this folder.  
**Safety status:** Not cleared for unsupervised physical motion. This document
is research guidance and program synthesis, not a certification case.

---

## 1. Abstract / thesis statement

Parcel should become a high-stakes companion dog by composing **typed proposals
with fail-closed metric authority**, not by replacing the stack with one VLN,
VLA, or RL policy.

The measured product is currently weak on instruction following
(**NAV_INSTRUCT frozen SR = 1/25 = 0.04**) and still carries **verified S0
authority defects**: ordinary proximity/TTC stops can leave residual shaped
velocity at the software HAL/manager-command boundary (physical actuator
motion was not measured); missing calibrated LiDAR on the default `grid_v1` path
falls back to open-loop translation; pause/resume can restart a motion channel
while its authorizing executive task stays suspended. Those defects, plus
oracle-shaped pose/semantics and a follow controller that bypasses the
obstacle-aware planner, make model A/B uninterpretable and physical claims
invalid.

Literature from Nav2, dual-system VLN (InternVLA-N1, NaVILA), social RPF
(Follow-Bench), LiDAR–inertial Go2 stacks, and preference/post-training nav
(X-NavDP, HALO, CityWalker) converges on the same architecture Parcel already
sketched: slow language/vision reasons; mid-level SE(2) goals propose; a
classical planner executes; an independent post-shaper geometry monitor forces
exact zero; Unitree Sport owns gait. Open weights belong in **shadow proposers
behind TTL and veto**. Custom RL/IL training is a **NO-GO now** and a
**CONDITIONAL GO later** only for a narrow residual (bounded trajectory
ranker / formation adaptation) after classical and artifact-by-artifact legally
approved, provenance-pinned open baselines
plateau on a frozen contract.

**Program order:** fix authority and lifecycle → honest state and product-path
eval → common planner + social formation + N11 residual → Nav2 challenger and
external ladders → shadow MiniCPM/CityWalker (then legally cleared locals) →
optional narrow adaptation. Do not train a foundation dog brain on one Ada GPU;
do not grant any model Sport authority.

---

## 2. Current system diagnosis

### 2.1 What works (preserve)

Independent audit and N5–N6 converge on a sound *shape*:

| Strength | Why it matters | Anchor |
| --- | --- | --- |
| Language never owns motors | PlanIR/PlanSketch → compiler → validator → `TaskExecutive` | `brain/contracts.py`, `compiler.py`, `validator.py` |
| NavigateTo admission ≠ visibility | Searchable with fresh sensors; grounding is the skill’s job | `brain/navigate_admission.py` |
| GoalRegion as independent arrival | Evals score predicates, not planner “arrived” strings | `instructnav/scoring.py` |
| TTL leases + latched E-stop | Elementwise-min authority; Sport retains gait | `authority.py`, `ControlManager` |
| Rolling occupancy + A* (`grid_v1`) | Deterministic in-process CI/city path | `grid_navigator.py` |
| `traffic_aware` pure layer | Soft rank / ramp seed; not a stop gate; empty-tracks identity | `navigation/traffic_aware.py` |
| Crossing policy | Curb-stop → announce → authenticated, authorized owner/control-channel command → gated cross; zero autonomous road entry | `maps/crossing.py` |
| Relation registry stratum | Right abstraction for FoR / terminal witnesses (not yet total) | `relation_registry.py` |

The hierarchy in `TARGET_ARCHITECTURE.md` is directionally correct. The failure
mode is incomplete composition and dishonest defaults, not a missing end-to-end
policy.

### 2.2 P0 verified defects (file-backed)

Opus independent audit **confirms** the prior stack audit’s six hazards. Severity
S0 = contact/motion without authority on the same tick.

#### P0.1 / S0.1 — Residual velocity after proximity/TTC stop

Dispatch applies collision/TTC gating, then S-curve shaping
(`runtime.py` ≈3825–3847). `emergency=True` slews toward zero at
`max_accel * dt`, not snap-to-zero (`velocity_shaping.py:102–105`). Measured:
cruise `vx=0.6` → post-emergency tick `0.4` (audit) or `0.48` at shipped
`linear_max_accel: 1.2` and `dt≈0.1`. These are synthetic shaper/command
measurements, not an end-to-end physical stopping-distance result. Latched
E-stop is a *different* path that
does reset. The pinning test
`test_stop_entry_point_6_a_proximity_stop_is_not_smoothed` only asserts
bypass_drop > smoothed_drop — it **encodes** residual motion as acceptable.
Docs claiming “every stop is unsmoothed” (`robot.yaml`, `docs/MOTION.md`) are
stale.

**Fix:** hard_safety_stop vs comfort_stop; post-shaper re-assert; exact zero +
shaper/smoother reset on the same dispatch; pin HAL command `== 0`.

#### P0.2 / S0.2 — Missing LiDAR → open-loop translation

Active model `grid_v1` (`configs/navigation/default.yaml`). Default
`safe_valley_micro_advance=False` (`grid_navigator.py:99`). Missing/malformed
scan → `StubNavigator` with `scan_missing_fallback` (`335–357`), which slews
`vx` toward the goal without occupancy. Fail-closed HOLD exists only on
opt-in safe-valley YAMLs.

**Fix:** physical/product profiles HOLD/STOP on missing/stale/malformed/
frame-invalid LiDAR (and pose/transform); labeled-sim fallback only under
explicit ODD flags.

#### P0.3 — Truth pose / health not production localization

`configs/navigation/pose.yaml` ships `provider: truth`. Drift profiles stress
interfaces; they are not SLAM. Physical translation must fail closed on
`DEGRADED`/`LOST`.

#### P0.4 / S1.1 — Resume restores channel, not executive task

Pause suspends channels **and** executive tasks; closed-intent resume only
walks `_resume_from_store` and never calls `task_executive.resume_task`
(`runtime.py` ≈1453–1465). Strict xfail
`test_resume_also_restores_the_executive_task_record` still red; sibling
channel-restore test passes. Motion without timeout/verification/recovery.

#### P0.5 — `come here` is persistent follow

`sketch_come` → `FollowFormation`; adapter
`DIRECT_FOLLOW_SUCCESS_STATES = {"following","holding"}` can succeed while the
controller stays enabled. Wrong speech act for a summons (N6).

#### P0.6 — Recovery / invariants underspecified

Compiler forces `max_attempts=1`; one global `_active_invariants` slot;
incomplete deadline hierarchy.

#### P0.7 — Unitree uncommissioned

`axes_commissioned: false`, empty `allowed_modes` — correct fail-closed; no
physical capability claim follows.

#### P0.8 — Person-stop math mixes seconds and metres

`SafetyEnvelope.person_stop()` adds the dimensionless
`person_latency_factor * reaction_latency_s` term to a distance. That is not a
valid physical quantity. Replace it with a measured distance allowance or a
declared relative closing speed times a time allowance, and verify whether the
chosen center/footprint clearance convention already accounts for robot radius.
Until then, neither the person envelope nor its current floors support a
physical safety claim.

### 2.3 P1 capability defects (summarized)

| ID | Defect | Anchor |
| --- | --- | --- |
| P1.1 / S1.2 | Follow proportional twist; no grid plan | `follow.py` direct/behind |
| P1.2 | Owner identity sim-perfect; single-frame reacquire risk | contracts vs runtime |
| P1.3 | Crowd cost diluted by `len(tracks)` / source-order `MAX_TRACKS` | `dynamic_costs.py` |
| P1.4 / S2.1 | T0 oracle semantics; truth pose | `perception_chain`, `pose.yaml` |
| P1.5 | Relation forks: sketch collapses to `near`; come≡follow alias | `local_plans.py`, registry |
| S3.1 | Historical N11 sidewalk+traffic ~0.33 m near-miss / step_timeout; not rerun by this audit | stored voice e2e xfail reason |

**Root cause (challenging “need a better VLM”):** failures are substrate —
authority, lifecycle, grounding, termination, localization, identity — not
missing foundation-model capacity. Derived NAV_INSTRUCT ceiling after U31
rescoring is ≤4/25; frozen headline remains **1/25**.

---

## 3. Literature-backed improvement program (by layer)

### 3.1 Safety / motion authority (N1 + N5)

**Import Nav2’s organizational lesson, not ROS as product authority:** Collision
Monitor sits *after* the velocity smoother; missing/`source_timeout` data →
STOP. Parcel must own an in-process post-shaper metric monitor that forces
exact zero and never widens envelopes. Keep `SafetyEnvelope`
`stop_distance(v) = r + vτ + v²/(2a) + Zs + Zr`; unify duplicated
`stop_distance_m` / `obstacle_stop_m`; commission Sport e2e latency and
`a_meas` before trusting YAML floors (current 0.8 m at ~0.9 m/s is
**UNVERIFIED**). The base formula is only a dimensionally valid design shape,
not certification; fix P0.8 and the footprint convention before using it.

### 3.2 Localization & perception (N4)

Phase-1 Go2: **two-rate** producers behind existing `PoseProvider` —

| Role | Preferred | Alternate |
| --- | --- | --- |
| ODOM ≥20 Hz | **FAST-LIO2** (Mid-360 kit) | Point-LIO / `point_lio_unilidar` (L1-only) |
| MAP 1–5 Hz | Scan-to-map / FAST-LIO localization | LIO-SAM or RTAB-Map for loop-rich mapping |

**Delta vs earlier appendix bias toward Point-LIO-as-primary:** Point-LIO is the
right *L1* baseline (CMU stack); Mid-360 + FAST-LIO2 is preferred when fitted.
LIO-SAM is mapping/long-loop, not the reactive odometry default. Capture-time
sync mandatory; L1-only ODD excludes low obstacles ~<0.3 m without depth.

Perception split: geometry 20–50 Hz (sole free space) → fast closed-set +
owner ReID 10–30 Hz → slow OV/OCR 0.2–2 Hz on query. Climb honesty ladder
R0 truth → R1 drift → R2 sensor-faithful sim → R3 bags → R4 shadow HIL → R5
supervised courses. Never call R0/R1 “real localization.”

### 3.3 Classical planner / control (N1)

**Keep `grid_v1` as production writer and CI reference.** Nav2 is an exclusive
challenger sidecar gated on measured L5/L6 local-control dominance
(adjudication D1) or frozen dynamic/BARN A/B with kill criteria — not a v1
authority migration.

Immediate steals *into Parcel* before a full ROS image:

1. Post-smoother fail-closed collision monitor semantics.
2. Speed-dependent stop envelope.
3. **RPP-style** curvature / obstacle speed regulation + arc collision check
   (best interpretable baseline; prefer over MPPI as first sidecar controller).
4. Smac Hybrid-A* / Lattice only when SE2 / footprint / turn-radius bite;
   NavFn alone does not buy kinematic feasibility.

MPPI is the dynamic-scene challenger (one BARN world anecdote where upstream
MPPI succeeded and Parcel timed out — reason to spike, not proof of global
superiority). Hard critics non-negotiable; DiffDrive ≠ Sport (**UNVERIFIED**
tracking).

### 3.4 Social / dynamic (N3)

N11 residual is **goal commitment + arrival definition**, not a missing brake.
Person-stop correctly refuses the last ~0.3 m on a contested strip; one-shot
traffic-aware placement + yield-advance seeds are necessary but insufficient.

Week-scale product fix:

1. Mid-mission re-rank (~1 Hz, hysteresis, empty-tracks no-op) while dwelling
   in `person_stop` near the goal.
2. Dwell-based `inside` arrival via `point_in_polygon_with_clearance`.
3. Keep yield-advance seed-only; never raise creep past person-stop needs.

This work starts only after P0 exact-zero/fail-closed behavior and P1-B/P1-D
fresh metric relation witnesses exist. Success additionally requires fresh
independent metric geometry, polygon membership with clearance, settled
feedback, an agent-issued stop, and no active collision brake; dwell cannot
launder an unsafe approach or near miss.

Soft proxemic costs rank/pace; hard geometry/TTC never trade. Follow-Bench is
the first external RPF comparator (oracle lane then camera lane) — **not** an
N11 flip criterion. HuNavSim 2 / MetaUrban later. Fix crowd-cost normalization
(P1.3). Replace proportional follow with formation goals → common planner
(P1.1).

### 3.5 Instruction / executive (N2 + N6)

Keep PlanIR boundary; models propose skills/waypoints, not motor ticks.
Literature (PLEXIL suspend≠outcome, ROS 2 action goal identity, SayCan,
PlanBench) endorses Parcel’s sketch.

Priority substrate:

1. Atomic suspend/resume over `{task_id, revision, step_id, channel}` (P0-C).
2. Split `ApproachOwner` (terminate + release) from persistent
   `FollowFormation`.
3. Total `RelationSpec` driving grammar, sketch, success facts, hold duration.
4. Bounded recovery subtrees with real `max_attempts` and per-revision
   invariants (P0-D).
5. `TaskRequestV1` with speaker/channel authorization (anyone may E-stop;
   environmental text never commands).

VLN/VLA: **proposals-only SE(2) + TTL shadow**. Best conceptual dual-system
match is InternVLA-N1 System 2; Qwen-RobotNav is the ABI north star (8×
waypoints) with **no public weights**. InstructNav validates modular
propose/dispose — prefer Parcel’s own geometry-first frontiers (VLFM pattern);
do not vendor unlicensed InstructNav code. Product blockers are licenses
(NC / undeclared Hub YAML / Llama derivatives), not “which SR is highest.”

### 3.6 City outdoor (N8)

Hard contract: **advisory nomination vs metric authority**.

| Advisory | Metric |
| --- | --- |
| OSM/Overture footway graph, CityWalker XY, route memory, GNSS GEO hint, Google Maps (disabled) | Calibrated LiDAR/depth/elevation, MAP/ODOM health, collision/TTC, curb height, arrival witnesses |

Allowed autonomous edges: footway/path/pedestrian/sidewalk only; crossings
require an authenticated, authorized owner/control-channel decision, not a
transcript alone. GNSS cannot decide sidewalk membership in urban canyon
(meters of error). Planar 2-D LiDAR is insufficient for curb height — use
elevation plus semantics.
CityWalker stays gate-off until original-asset license scope and loader review
clear; the local bytes match official v1.0 SHA-256
`a42326778e5e318c6222575dc5e02f1794d9a60cce4dc8f8a2ee5df7dc6d1c29`;
it emits SE(2) only; author
77.3% Go1 ≠ Parcel. P4-E city handoff waits on local localization + curb
physics.

### 3.7 Models (N2 + RL2)

Role matrix (shadow only):

| Role | First candidate | Blockers |
| --- | --- | --- |
| Owner-follow waypoints | MiniCPM-RobotTrack (Apache core code+weights) | gated/separate vision and deployment dependencies; nonzero author collisions; not identity |
| Urban prior | CityWalker (official v1.0 bytes verified; clear original-asset license scope or separately pin HF) | No yaw/language/identity; Go1 paper |
| Local detour/recovery | CE-Nav after artifact/dependency review | MIT repository/checkpoints, but legacy Isaac and transitive terms; not motor authority |
| Local detour/recovery | X-NavDP after legal | undeclared HF weight terms, NC parent ambiguity, and Isaac assets |
| Instruction research | InternVLA-N1 S2 / NaVILA | InternVLA README badge is CC BY-NC-SA 4.0 with absent machine-readable artifact grant; NaVILA weight grant undeclared; co-residency unprofiled |
| Schema donor | Qwen-RobotNav interface | Weights unreleased |

Sandbox: pin hash, no network, reviewed `trust_remote_code`, deadline/OOM ≡
unavailable proposer → deterministic HOLD. Classical continuation is permitted
only for a previously grounded, still-fresh, still-authorized goal through the
unchanged state and geometry gates.

---

## 4. RL decision — reconcile RL1 + RL2

### 4.1 Joint verdict

| Surface | Decision |
| --- | --- |
| Train Parcel-owned policy **now** | **NO-GO** (0 RL GPU-hours) |
| From-scratch E2E / VLA / Sport-replacing locomotion | **NO-GO** |
| Open-weight shadow + classical baselines | **GO** after P0 and artifact/legal gates |
| Later narrow IL → optional shielded sim RL | **CONDITIONAL GO** |

RL2’s reuse case and RL1’s steelman **agree on timing and containment**. RL1
adds a conditional case: custom adaptation may become useful for
companion-specific ranking or formation preferences after a competent baseline
exposes that residual; it is not assumed to be inevitable. RL2 supplies the
acquisition queue that must be exhausted first.

### 4.2 Why NO-GO now

1. Measured bottleneck is substrate (4% NAV_INSTRUCT; Nav2 MPPI smoke vs Parcel
   timeout on one world), not policy capacity.
2. `Go2Env` stub; MetaUrban real backend `NotImplementedError`; no sensor-only
   corpus with expert labels and independent terminals.
3. No versioned proposal serving ABI (freshness, masks, deadline, rollback,
   veto log).
4. P0 safety/lifecycle open → A/B confounded.
5. RTX 5000 Ada 32 GB plausibly supports narrow critics/LoRA or small-model
   adaptation, but no training workload has been profiled and the active
   `.parcel` environment lacks Torch. Hardware availability is not a validated
   training environment or evidence for foundation-scale reproduction.

### 4.3 Acquisition order (reuse before train)

1. **MiniCPM-RobotTrack** — first new candidate after core plus gated/transitive
   vision/deployment terms and custom code clear (Go2 EDU/Orin dry-run; 8×
   SE(2)-like waypoints).
2. **CityWalker** — official v1.0/local byte identity is verified; no execution
   until original-asset license scope and loader security clear, or a reviewed,
   independently pinned HF conversion is approved.
3. **CE-Nav** — first Go2 local-policy screen after its checkpoint,
   dependency, and legacy-Isaac review.
4. **X-NavDP** — hold until counsel resolves undeclared weight and mixed
   parent/subtree/asset terms.
5. **InternVLA-N1** — research-only if its README-declared CC BY-NC-SA 4.0
   terms, absent machine-readable artifact grant, and intended use are
   explicitly approved; study System 2 first; never S1 as
   Sport replacement.
6. **NaVILA** — defer (undeclared HF license + Llama terms; mid-level ABI).

### 4.4 Leading eventual pilot (after gates)

Bounded trajectory **ranker / social critic**: sampler → K hard-masked SE(2)
candidates + HOLD → learn index or abstain → re-validate → common controller +
independent monitor + Sport. Alternatives: MiniCPM/CityWalker IL adaptation;
FunctionGemma-class schema LoRA. Cap ≤120 single-GPU hours with stage
stop-losses. Never: physical online RL, LowCmd locomotion in this program,
E2E language→motor.

---

## 5. Phased roadmap (aligned board + deltas)

Evidence classes from `EVALUATION_AND_ROADMAP.md` remain binding: never promote
`derived_rescore` or `external_proxy` into product/leaderboard claims.

### Phase 0 — Authority & evidence valid

| Card | Exit |
| --- | --- |
| P0-0 Freeze baseline | Immutable commit/patch/config/scenario hashes; product + fault evidence before edits |
| P0-A Exact-zero stop | Same-dispatch HAL zero; shaper reset; fault pin |
| P0-B Fail-closed state | Stale/missing LiDAR/pose/transform → HOLD; typed health contract (truth labeled-sim only) |
| P0-C Atomic lifecycle | Resume restores task+channel; strict xfail → pass |
| P0-D Recovery/invariants/deadlines | Per-revision invariants; executable bounded recovery |
| P0-E Post-fix baseline | Identical episodes rerun with telemetry |
| P0-F ABI freeze | Versioned Task/Pose/Perception/NavProposal/Safety schemas |
| P0-G Approach/follow split | `ApproachOwner` terminates and releases the base; `FollowFormation` remains persistent |
| P0-H Safety-envelope units | No seconds-to-metres addition; one tested footprint/clearance convention |

**Delta:** Explicit **ApproachOwner** skill split (N6) is P0.5 work — schedule
with P0-C/D, not defer to “social polish.”

### Phase 1 — Honest state & task contract

P1-A `TaskRequestV1` · P1-B real LIO + perception (Kit B FAST-LIO2 preferred) ·
P1-C enrolled identity + formation goals · P1-D total relation witnesses ·
product-path NAV_INSTRUCT via `handle_text`.

**Deltas:**

- Close **U31 option 2** (runner hold) + U32 episode-spec re-freeze *before*
  treating the next frozen SR as capability.
- **N11 residual card** (mid-mission re-rank + dwell `inside`) — week-scale
  only after P0 exact-zero and fresh P1-B/P1-D metric witnesses; sibling of P1
  social / early Phase 2; flip xfail only on the full hard pass above.
- Port **RPP regulation patterns** into Parcel tracking before waiting on full
  P2-A ROS image.

### Phase 2 — Classical strength & social

P2-A Nav2 sidecar (Smac+RPP baseline, MPPI challenger, Parcel final monitor) ·
P2-B semantic memory · P2-C reactive subtrees · P2-D BARN public-dev adapter ·
formation follow + crowd-cost fix.

Gate: paired improvement on product nav + public BARN proxy; no hard-safety /
identity / p99 latency regression. Matched-information and full-product A/B
reported separately.

### Phase 3 — Eval overhaul & proposer harness

P3-A product eval · P3-B Follow-Bench then MetaUrban/HuNavSim · P3-C
`NavProposalV1` out-of-process harness.

### Phase 4 — Shadow models & embodiment

P4-A MiniCPM · P4-B CityWalker + cleared CE-Nav/X-NavDP · P4-C InternVLA/NaVILA
research · P4-D Go2 physics harness · P4-E GEO/MAP advisory handoff (**later**,
after localization + curb).

**Delta vs README role list:** experiment order follows RL2 acquisition
(MiniCPM → CityWalker → local policies → instruction research), not “largest
VLN first.”

### Phase 5–6 — Safety case, HIL, gated learning

P5-0 ODD/FMEA/STPA signoff · P5-A supervised courses · P6-A narrow adaptation
only if attributable residual survives open baselines.

### Ladder before SOTA (N7)

```text
P0 evidence+safety+lifecycle
  → P1 honest state + product-path NAV_INSTRUCT
  → P2 Nav2 + formation + BARN
  → P3 Follow-Bench / MetaUrban + proposer harness
  → P4 shadows → P4-D physics → P5 HIL
  → P6 train only on frozen residual
```

Promotion still requires: zero critical false-success/collision/false-owner in
promotion set; paired credible gain; no family/p99 regression; deterministic
HOLD on model failure; product + role-relevant external suite; license + device
gates; separate HIL authorization.

---

## 6. What NOT to do

1. End-to-end language/camera → motor VLA or Sport replacement.
2. Custom foundation VLN/VLA / from-scratch PointNav / physical online RL.
3. Nav2 as v1 sole motion authority or dual-smoothing without single owner.
4. Import NC / undeclared-weight models into product images or physical motion.
5. Cite VLN-CE / CityWalker 77.3% / MiniCPM EVT as Parcel NAV_INSTRUCT or
   safety evidence.
6. Call derived 0.12/0.16 or native BARN 44% a promotion sample / top-decile.
7. Flip pedestrian xfail without hard pass; weaken person-stop to “make
   progress.”
8. GNSS-only sidewalk following; autonomous road entry from learned crossing.
9. Silent nearest-person identity; single-frame reacquire; oracle fields on
   product observations.
10. Co-schedule 7–8B BF16 VLN with full Orin product stack without measured
    peak VRAM.
11. Train against `Go2Env` stub or privileged MetaUrban kinematics as if they
    were the product boundary.
12. Treat software E-stop as independent hardware E-stop; claim unsupervised
    deployability from sim zeros.

---

## 7. UNVERIFIED / open questions

| ID | Claim / question | What would verify |
| --- | --- | --- |
| U-stop | `stop_distance_m: 0.8` safe at cruise ~0.9 m/s under Sport | Instrumented stop tests → `a_meas`, `τ_e2e` |
| U-shaper | Residual stop ticks’ contribution to contact risk outdoors | Same + post-fix P0-A traces |
| U-person-envelope | Relative-closing-speed/person allowance and single footprint convention | Typed P0-H implementation + commissioned stop/approach tests |
| U-MPPI | MPPI better than Parcel local control generally | Frozen corpus A/B, same sensors/timeouts |
| U-Smac | Smac Hybrid/Lattice 50–200 ms on Orin under GPU load | Timed planner on pinned image |
| U-Sport-track | DiffDrive RPP/MPPI tracks Go2 Sport acceptably | Tracking/overshoot logs on EDU |
| U-LIO | FAST-LIO2 / Point-LIO Parcel RPE/ATE | R3 bags + surveyed courses |
| U-ZsZr | Temporary `Zs`/`Zr` = 0 outdoors | Calibrated sensing intrusion + pose covariance |
| U-CityWalker | Original v1.0 asset license scope; Orin latency | Asset-specific legal review + profiling (byte identity is verified) |
| U-X-NavDP | Weight SPDX / commercial grant | Counsel + pin |
| U-InternVLA | Hub YAML license completeness; InternData NC/SA conflict | Per-artifact legal packet |
| U-NaVILA | Weight grant + Llama compliance | Same |
| U-N11 | Mid-mission re-rank + dwell flips e2e | Hard pass under `--runxfail` |
| U-U31 | Option-2 re-freeze true capability SR | Paired baseline/candidate freeze |
| U-Follow-Bench | Adapter effort / dependency licenses | Spike B0–B1 |
| U-MetaUrban | Terms + observation adapter | Service pin; currently `NotImplementedError` |
| U-ranker | Sampler feasibility as product K-API (not stock MPPI internals) | Spike before any ranker train |
| U-Unitree-2m | Manual “≥2 m” as autonomy stop envelope | OEM-pinned PDF + policy choice |

---

## 8. Source index (`research/*`)

| Doc | Scope | Thesis use |
| --- | --- | --- |
| [`research/N1_CLASSICAL_NAV.md`](research/N1_CLASSICAL_NAV.md) | Nav2 Smac/RPP/MPPI, collision monitor, stop envelope, grid vs sidecar | Classical layer; RPP-first; keep `grid_v1` |
| [`research/N2_INSTRUCTION_VLN.md`](research/N2_INSTRUCTION_VLN.md) | InternVLA, NaVILA, StreamVLN, Uni-NaVid, InstructNav, Qwen-RobotNav | Proposals-only + license matrix |
| [`research/N3_SOCIAL_DYNAMIC.md`](research/N3_SOCIAL_DYNAMIC.md) | N11 residual, Follow-Bench, HuNavSim, MetaUrban, proxemics | Commitment/dwell fix; soft vs hard |
| [`research/N4_PERCEPTION_LOCALIZATION.md`](research/N4_PERCEPTION_LOCALIZATION.md) | FAST-LIO2/Point-LIO/LIO-SAM/DLIO, OV split, owner ReID, R0–R5 ladder | Phase-1 producers |
| [`research/N5_SAFETY_AUTHORITY.md`](research/N5_SAFETY_AUTHORITY.md) | Residual shaper velocity; LiDAR open-loop; P0-A/B | S0 defects + fix bar |
| [`research/N6_EXECUTIVE_BEHAVIOR.md`](research/N6_EXECUTIVE_BEHAVIOR.md) | Resume split, come vs follow, relation registry, PlanIR | Executive P0/P1 |
| [`research/N7_EVALUATION_LADDER.md`](research/N7_EVALUATION_LADDER.md) | Evidence classes, U31, BARN/Follow-Bench/MetaUrban honesty | Ladder-before-models |
| [`research/N8_CITY_OUTDOOR.md`](research/N8_CITY_OUTDOOR.md) | OSM/GNSS/CityWalker/curb advisory vs metric | City contract |
| [`research/RL1_CUSTOM_TRAINING_CASE.md`](research/RL1_CUSTOM_TRAINING_CASE.md) | Steelman for later narrow training; profile-first Ada feasibility hypothesis | CONDITIONAL GO shape |
| [`research/RL2_OPEN_WEIGHT_REUSE.md`](research/RL2_OPEN_WEIGHT_REUSE.md) | Acquisition order; shadow contract; no-train-now | Reuse path |
| [`research/OPUS_INDEPENDENT_AUDIT.md`](research/OPUS_INDEPENDENT_AUDIT.md) | Independent confirm of S0–S3 hazards | Diagnosis authority |

Prior drafts challenged (not rubber-stamped): `CURRENT_STACK_AUDIT.md`,
`MODEL_AND_RL_DECISION.md`, `TARGET_ARCHITECTURE.md`,
`EVALUATION_AND_ROADMAP.md`, `README.md`. Material agreements retained;
material deltas called out in §§3–5 (FAST-LIO2 preference, N11 commitment
diagnosis, RPP-in-Parcel-now, ApproachOwner as P0.5, review-first MiniCPM
candidate order, U31 re-freeze before capability claims).

Supporting ledger: [`SOURCE_LEDGER.md`](SOURCE_LEDGER.md). Board status:
[`README.md`](README.md). Wave status: [`OPUS_RESEARCH_WAVE.md`](OPUS_RESEARCH_WAVE.md).

---

## Bottom line

Ship fail-closed authority and honest evaluation first. Steal classical safety
and regulation patterns into Parcel while keeping `grid_v1` as the production
writer. Fix N11 as a commitment/arrival problem. Shadow only artifact-by-
artifact legally approved, provenance-pinned waypoint proposers behind
`NavProposalV1`. Train nothing until
that ladder leaves a narrow, attributable residual — then rank among already-safe
trajectories, never invent a motor policy.
