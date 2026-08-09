# Design D2 — Shadow-proposer hierarchy

**ID:** D2  
**Title:** Shadow-proposer hierarchy  
**Date:** 2026-08-07  
**Author role:** Claude Opus design stand-in  
**Status:** design proposal for team review (not implemented by this doc)  
**Depends on:** Design D1-class safety (exact-zero post-shaper monitor; fail-closed LiDAR/pose; atomic lifecycle)  
**Inputs:** [`../RESEARCH_THESIS.md`](../RESEARCH_THESIS.md), [`../research/RL2_OPEN_WEIGHT_REUSE.md`](../research/RL2_OPEN_WEIGHT_REUSE.md), [`../research/N2_INSTRUCTION_VLN.md`](../research/N2_INSTRUCTION_VLN.md), [`../research/N1_CLASSICAL_NAV.md`](../research/N1_CLASSICAL_NAV.md), [`../research/N5_SAFETY_AUTHORITY.md`](../research/N5_SAFETY_AUTHORITY.md), [`../research/OPUS_INDEPENDENT_AUDIT.md`](../research/OPUS_INDEPENDENT_AUDIT.md), [`../TARGET_ARCHITECTURE.md`](../TARGET_ARCHITECTURE.md)  
**Sibling designs:** D1 classical companion; D3 social city  
**Safety status:** Not a certification case. No unsupervised physical motion. Models propose only.

---

## 0. One-line thesis

MiniCPM-RobotTrack, then CityWalker, run as **out-of-process SE(2) proposers** behind TTL, sandbox, schema validation, classical `grid_v1` execution, and an independent geometry veto — never as Sport writers, identity oracles, or free-space authorities.

---

## 1. Goals

### 1.1 Product goals

| Goal | Success looks like |
| --- | --- |
| G1 Reuse before train | Zero custom RL/VLA GPU-hours until open shadows plateau on a frozen residual |
| G2 Interpretable A/B | Every episode logs accept / reject / TTL / veto / fallback with identical classical baseline |
| G3 Role-matched models | MiniCPM = owner-follow waypoints; CityWalker = urban XY prior — never swap roles |
| G4 Fail-closed continuity | Model crash, OOM, deadline miss, stale TTL, or veto ⇒ HOLD by default; the same existing classical goal continues only after full task/revision authorization and freshness/geometry re-admission |
| G5 No Sport path | No process boundary, IPC message, or code path may map model output → Unitree velocity |

### 1.2 Non-goals (explicit)

1. End-to-end VLA / language→motor / LowCmd locomotion.
2. Nav2 as production writer (D1/N1: `grid_v1` remains sole production consumer; Nav2 is exclusive challenger).
3. Acquiring X-NavDP, InternVLA-N1, or NaVILA into product images (license gates; research-only later).
4. Treating author EVT / Go1 / VLN-CE scores as Parcel NAV_INSTRUCT or safety evidence.
5. Granting MiniCPM owner-identity or presence truth; granting CityWalker curb/road legality or language goals.
6. Shipping shadow→active promotion without the eval ladder in §7.

### 1.3 Prerequisites (D1-class — assumed present)

D2 **must not** enable live shadow wiring until these are green:

| Gate | Bar |
| --- | --- |
| P0-A | Same-dispatch HAL command `== (0,0,0)` on hard safety stop; shaper/smoother reset |
| P0-B | Missing/stale/malformed LiDAR, pose, or transform → HOLD/STOP on product profile |
| P0-C | Resume restores `{task, revision, channel}` atomically |
| P0-F | Versioned `NavProposalV1` schema + golden reject tests (this design freezes the ABI) |

Without these, model A/B confounds authority defects with capability (audit S0.1–S0.2, thesis §2).

---

## 2. Architecture diagram

```text
  Owner speech / TaskExecutive (revision, deadlines, witnesses)
            │
            │  formation / NavigateTo / ApproachOwner semantic goal
            ▼
  ┌─────────────────────────────────────────────────────────────┐
  │ Observation ABI (camera RGB IDs, pose health, lidar freshness)│
  │  → ObservationSnapshotV1 {ids, stamps, frame, abi_hash}       │
  └───────────────────────────┬─────────────────────────────────┘
                              │
         ┌────────────────────┼────────────────────┐
         │                    │                    │
         ▼                    ▼                    ▼
  Classical path      MiniCPM sandbox       CityWalker sandbox
  (always live)       (out-of-process)      (out-of-process)
  SearchEntity /      Apache pin+hash       provenance pin
  formation goals /   RGB → 8× SE2          RGB hist → XY
  grid_v1 A*          waypoints             polyline + arrive
         │                    │                    │
         │                    └────────┬───────────┘
         │                             │ NavProposalV1 (IPC)
         │                             ▼
         │                  ProposalIngress
         │                  · schema / finite / horizon clamp
         │                  · frame + transform epoch
         │                  · task_id + revision match
         │                  · observation_ids freshness
         │                  · TTL / expires_at
         │                  · identity gate (MiniCPM only)
         │                  · hard kinematic + occupancy mask
         │                             │
         │                    ┌────────┴────────┐
         │                    │                 │
         │              SHADOW mode        ACTIVE mode
         │              (default)          (gated)
         │              log-only           → SE2Goal
         │              classical wins     ProposerBus
         │                    │                 │
         └────────────────────┴────────┬────────┘
                                       ▼
                              GoalArbiter
                              · TTL lethal veto
                              · plan_step ownership
                              · priority / confidence
                                       │
                                       ▼ winner SE2Goal | None
                              grid_v1 (sole production writer)
                                       │
                              velocity smoother / shaper
                                       │
                              FINAL metric-geometry monitor
                              (exact zero; never widens)
                                       │
                              ControlManager → Unitree Sport
```

**Hard cut:** everything left of Sport is Parcel authority. The dashed model boxes have **no** edge into ControlManager.

---

## 3. Component roles

| Component | Owns | Must not own |
| --- | --- | --- |
| MiniCPM-RobotTrack service | Relative SE(2) track waypoints + raw model diagnostics | Owner ID, presence, free space, Sport cmd |
| CityWalker service | Relative XY polyline + arrive logit | Language goal, social cost, curb/road entry, yaw truth |
| ProposalIngress | Schema, TTL, frame, masks, veto log | Planner path selection |
| ProposerBus / GoalArbiter | Latest-only SE2Goal competition | Motor ticks |
| `grid_v1` | Occupancy path + local tracking | Model logits |
| Post-shaper geometry monitor | Exact-zero hard stop; freshness STOP | Soft ranking |
| Unitree Sport | Gait / balance | Task success |

Existing in-tree seams to extend (do not fork):

- `instructnav/arbiter.py` — `SE2Goal`, `ProposerBus`, `GoalArbiter`
- `route_memory/citywalker.py` — fail-closed adapter pattern (skip/UNVERIFIED)
- `contracts/freshness.py` — fail-closed TTL helpers
- Target ABI in `TARGET_ARCHITECTURE.md` §6 — `NavProposalV1` (not yet a `contracts/v1.py` type; D2 freezes it)

---

## 4. Algorithms

### 4.1 Modes

```text
enum ProposerMode:
  OFF      # process not started; classical only
  SHADOW   # proposals validated + logged; never win GoalArbiter
  ACTIVE   # validated proposals may enter ProposerBus (still vetoable)
```

Default for every newly acquired model: **SHADOW**. Promotion to ACTIVE is a ledgered gate (§7), not a YAML flip alone.

### 4.2 Validate (ProposalIngress)

On every IPC message `p: NavProposalV1` at wall time `now`:

```text
function validate(p, ctx) -> (Accept | Reject, reason):
  # 1. Schema / finiteness
  if not schema_ok(p):           return Reject("schema")
  if not all_finite(p.waypoints): return Reject("nonfinite")
  if p.model_hash != pinned_hash(p.model_id):
                                  return Reject("hash_mismatch")
  if p.input_abi_hash != ctx.obs_abi_hash:
                                  return Reject("abi_mismatch")

  # 2. Task / revision binding
  if p.task_id != ctx.active_task_id:       return Reject("task_mismatch")
  if p.task_revision != ctx.active_revision: return Reject("stale_revision")

  # 3. Observation freshness (fail-closed)
  if any obs_id missing/stale vs ctx.freshness_budget:
                                  return Reject("stale_observation")
  if ctx.pose.health in {DEGRADED, LOST} and profile.requires_healthy_pose:
                                  return Reject("pose_unhealthy")

  # 4. TTL
  if now > p.expires_at:         return Reject("ttl_expired")
  if p.produced_at > now + skew: return Reject("clock_skew")

  # 5. Frame / transform
  if not can_transform(p.frame → ctx.planner_frame, p.captured_at):
                                  return Reject("transform")

  # 6. Horizon clamp (adapter may pre-clamp; ingress re-enforces)
  wps = clamp_horizon(p.relative_se2_waypoints,
                      max_range_m=ctx.max_proposal_horizon_m)  # default 3.0
  if empty(wps):                 return Reject("empty_after_clamp")

  # 7. Role gates
  if p.model_id == "minicpm_robottrack":
      if ctx.owner_posterior.state != ADMITTED:
                                  return Reject("identity_gate")
      if not ctx.target_visible_m_of_n:
                                  return Reject("no_target")   # MiniCPM warned: may invent forward motion
  if p.model_id == "citywalker":
      if ctx.task_mode not in {POINT_GOAL, URBAN_APPROACH, DETOUR}:
                                  return Reject("role_mismatch")
      # no language / identity fields allowed on this model_id
      if p.task_mode == OWNER_FOLLOW: return Reject("role_mismatch")

  # 8. Hard masks (geometry — not soft social costs)
  if any_waypoint_lethal(wps, ctx.occupancy, ctx.keepout):
                                  return Reject("lethal_mask")
  if violates_kinematic_profile(wps, ctx.kinematic_profile_id):
                                  return Reject("kinematic")

  # 9. Confidence policy
  conf = unknown_if_uncalibrated(p.confidence)  # never treat raw logit as calibrated P

  return Accept(SE2Goal_from(wps, conf, ttl=remaining_ttl(p), source=p.model_id))
```

**Invariant:** Reject never raises envelopes, never substitutes nearest-person,
and never opens StubNavigator translation. Reject → log, then deterministic
HOLD unless an already-authorized, independently grounded classical goal is
still fresh and every localization, transform, sensing, and geometry gate is
healthy; only that existing goal may continue (§4.4).

### 4.3 TTL / latest-only buffer

```text
# Per model_id, single-slot buffer
buffer[model_id] = None

on_message(p):
  verdict, payload = validate(p, ctx)
  log(verdict, reason, p.diagnostics)
  if verdict == Reject:
    return
  # Latest-only: newer produced_at replaces; older discarded even if still unexpired
  if buffer[model_id] is None or p.produced_at >= buffer[model_id].produced_at:
    buffer[model_id] = payload

on_control_tick(now):
  for model_id, goal in buffer.items():
    if goal is None or goal.expired(now):
      buffer[model_id] = None
      log("ttl_drop", model_id)
      continue
    if mode[model_id] == SHADOW:
      log_shadow_compare(goal, classical_goal)   # no ProposerBus.publish
    elif mode[model_id] == ACTIVE:
      bus.publish(goal)                          # still subject to GoalArbiter + geometry
```

Recommended TTL budgets (start values; remeasure under co-residency):

| Model | Default `ttl_s` / `expires_at − produced_at` | Rationale |
| --- | --- | --- |
| MiniCPM | 0.5–1.0 s | Reactive track; author ~180 ms e2e; stale track is lethal |
| CityWalker | 1.0–2.0 s | Slower urban prior; still revalidated each cycle |
| System-2 research (later) | ≤2.0 s at ingress even if model thinks longer | Revalidation each cycle; no long-horizon trust |

### 4.4 Fallback (deterministic)

```text
function select_executive_goal(ctx, now):
  classical = admit_existing_classical_goal(ctx)
  # None unless independently grounded for the same authorized task/revision
  # and evidence/frame/pose/metric-geometry/controller health all pass again
  active_model_goals = [g for g in bus.poll(now) if mode[g.source] == ACTIVE]

  winner = GoalArbiter.resolve(
      goals=[classical] + active_model_goals,
      now=now,
  )

  if winner is None:
    return HOLD("no_viable_goal")       # exact zero path via D1 monitor

  # Shadow never appears in active_model_goals
  return winner
```

Fallback matrix:

| Condition | Product behavior |
| --- | --- |
| Model OFF / process dead | Re-admitted existing classical goal, otherwise HOLD |
| Deadline miss / OOM / malformed IPC | Log `proposer_unavailable`; re-admission or HOLD |
| Validate Reject | Log reason; re-admission or HOLD |
| TTL expiry mid-mission | Drop buffer slot; re-admission or HOLD; no coasting on last model tip |
| ACTIVE but GoalArbiter lethal veto | Re-admission or HOLD; final geometry veto repeats |
| Hard geometry stop (D1) | Exact zero — **overrides** any winner |

### 4.5 Shadow vs active compare

Every SHADOW tick writes a paired record (same `episode_id`, `task_revision`, `observation_ids`):

```text
ShadowCompareV1 {
  episode_id, t_s, model_id, mode,
  classical_se2, proposal_se2 | null,
  ingress_verdict, ingress_reason,
  would_have_won_arbiter: bool,   # counterfactual under ACTIVE priority rules
  geometric_clearance_delta_m,    # proposal tip vs classical tip
  identity_gate_ok: bool,
  latency_ms, vram_mb | null
}
```

**Promotion rule (necessary, not sufficient):** on a frozen role-matched suite, ACTIVE must show paired improvement on product metrics **and** zero increase in hard-safety vetoes / identity swaps / p99 control latency — see §7. Shadow-only “would_have_won” rate is diagnostic, not a promotion sample.

### 4.6 Adapter algorithms (per model)

#### MiniCPM-RobotTrack → `NavProposalV1`

```text
inputs: latest RGB frame + observation_id, enrolled-owner admit flag (Parcel-side),
        task_mode=OWNER_FOLLOW | TARGET_TRACK
native: 8 × (x, y, yaw) future waypoints (author Go2 dry-run path)
adapter:
  1. Refuse inference if Parcel identity gate closed (do not ask model "is this owner?")
  2. Map waypoints to relative_se2 in base_link at captured_at
  3. Clamp cumulative path length ≤ max_proposal_horizon_m
  4. confidence := UNKNOWN until Parcel calibration set exists
  5. Set expires_at = produced_at + ttl_s
  6. Never emit Sport velocity; never write presence=true
```

#### CityWalker → `NavProposalV1`

```text
inputs: RGB history + relative pose history + point-goal (when present)
native: 5 × (x, y) + arrive logit; no yaw
adapter:
  1. Derive yaw from consecutive segment atan2 (or leave yaw free for planner)
  2. Emit relative XY polyline as SE2 with derived/free yaw
  3. arrival_probability := arrive logit marked UNCALIBRATED
  4. Role = URBAN_APPROACH / POINT_GOAL only
  5. Never set road-entry / crossing clearance bits (those stay maps/crossing.py)
```

---

## 5. `NavProposalV1` + IPC contract

### 5.1 Schema (frozen for P0-F / P3-C)

Canonical fields (align `TARGET_ARCHITECTURE.md` §6; add explicit enums for D2):

```text
NavProposalV1 {
  # Identity of the producer
  model_id:               "minicpm_robottrack" | "citywalker" | string
  model_hash:             sha256 hex of pinned weights (+ reviewed code digest)
  service_instance_id:    string

  # Binding to Parcel executive + evidence
  task_id:                string
  task_revision:          uint64
  plan_step_id:           string
  observation_ids:        string[]          # must match ObservationSnapshotV1
  captured_at:            float64 seconds   # sensor time of primary evidence
  produced_at:            float64 seconds   # service wall/monotonic as declared
  expires_at:             float64 seconds   # hard TTL

  # Geometry
  frame:                  "base_link" | "odom" | "map"
  relative_se2_waypoints: [ {x, y, yaw_rad | null} ; N=1..16 ]
  time_from_start:        float64[] | null  # optional, same length as waypoints
  waypoint_covariance:    float64[] | null  # optional; null ⇒ unknown/large
  arrival_probability:    float64 | null    # null or uncalibrated marker
  confidence:             float64 | "unknown"   # [0,1] only if Parcel-calibrated

  # Profiles / ABI pins
  task_mode:              OWNER_FOLLOW | TARGET_TRACK | POINT_GOAL |
                          URBAN_APPROACH | DETOUR | OTHER
  footprint_profile_id:   string
  kinematic_profile_id:   string
  input_abi_hash:         sha256
  calibration_abi_hash:   sha256

  # Audit
  evidence_handles:       string[]
  diagnostics:            {latency_ms, backend, notes, ...}
}
```

Golden reject fixtures (CI, no weights required — use Qwen-RobotNav-shaped 8-waypoint synthetic):

1. Schema missing field / wrong type  
2. Non-finite waypoint  
3. `expires_at` in the past  
4. `task_revision` mismatch  
5. Unknown `observation_ids`  
6. Horizon beyond clamp  
7. Lethal cell under occupancy mask  
8. MiniCPM with identity gate closed  
9. CityWalker with `task_mode=OWNER_FOLLOW`  
10. Hash mismatch vs pin  

### 5.2 IPC

| Property | Choice |
| --- | --- |
| Transport | Unix domain socket **or** localhost gRPC; no WAN |
| Framing | Length-prefixed JSON (v1) or protobuf with JSON golden twins |
| Auth | Filesystem socket permissions + peer credential check; no tokens in model env |
| Deadline | Client-enforced request deadline (MiniCPM default 250 ms; CityWalker 400 ms — tune after profile) |
| Buffering | Latest-only; drop in-flight older responses when a newer request is issued |
| Backpressure | If service busy → skip tick; re-admit the existing classical goal or HOLD (never block control loop) |
| Crash | Supervisor restarts service; Parcel treats absence as OFF until first valid proposal |

Request (Parcel → service):

```text
NavProposeRequestV1 {
  request_id,
  deadline_at,
  task_id, task_revision, plan_step_id, task_mode,
  observation_snapshot_ref,   # shared-memory or path to pinned bag frame
  pose_ref,                   # odom_T_base at captured_at; health
  goal_hint | null,           # CityWalker point goal; MiniCPM track target metric pose if admitted
  input_abi_hash
}
```

Response: `NavProposalV1` **or** `NavProposeErrorV1{request_id, code, message}` where codes ∈ `{DEADLINE, OOM, INTERNAL, UNSUPPORTED_MODE, NO_EVIDENCE}`. All errors ≡ unavailable proposer.

### 5.3 Sandbox (mandatory for both models)

```text
proposer container / cgroup:
  - pinned image + SBOM
  - weights + reviewed modeling code only (trust_remote_code reviewed & vendored)
  - network: none
  - credentials: none
  - writable paths: tmpfs scratch only; model cache read-only
  - device: GPU assigned explicitly; no robot HAL / Sport sockets mounted
  - VRAM + RSS caps; kill on overrun
  - seccomp/landlock as available on host
```

**Rule:** HF loaders for MiniCPM and CityWalker both use `trust_remote_code`. Never import that code into the control process. Vendor reviewed snapshots into the sandbox image.

### 5.4 Mapping to in-process `SE2Goal`

```text
SE2Goal {
  source:       model_id,
  pose:         first waypoint as (x,y,yaw) OR None if polyline-only tip deferred,
  waypoints:    XY pairs (yaw stripped for CityWalker polyline consumers),
  frame:        transformed planner frame,
  confidence:   0.0 if unknown else calibrated value,
  ttl_s:        expires_at - now,
  plan_step_id: from proposal,
  issued_s:     now (ingress stamp — not model clock),
  priority:     SHADOW unused; ACTIVE defaults MiniCPM=10, CityWalker=5,
                classical formation/NavigateTo typically ≥20 so classical wins ties
}
```

Priority policy: **classical semantic goals outrank model tips** unless an ACTIVE promotion explicitly raises a model for a named task_mode after gates. D2 default: models are helpers, not bosses.

---

## 6. Navigation logic (integration)

### 6.1 Control-loop ownership

```text
50–100 Hz  geometry monitor + watchdog          (D1)
20–50 Hz   grid_v1 / local tracking             (classical writer)
10–20 Hz   formation goal sampler               (social; D3 sibling)
~2–5 Hz    MiniCPM propose requests             (SHADOW/ACTIVE)
~1–2 Hz    CityWalker propose requests          (SHADOW/ACTIVE)
event      TaskExecutive revisions              (invalidate buffers)
```

Model rates are **upper bounds**. Under thermal/VRAM pressure, drop open-vocab and proposers before geometry/safety (target architecture §7).

### 6.2 Who may write velocity

| Writer | Allowed? |
| --- | --- |
| `grid_v1` / formation→grid | Yes (production) |
| Nav2 sidecar | Exclusive challenger only (N1); never co-write |
| MiniCPM / CityWalker | **No** — proposals only |
| Soft social costs | Rank/pace only |
| Post-shaper monitor | Tighten/zero only |

### 6.3 Mission-path wiring (product)

1. `TaskExecutive` admits NavigateTo / FollowFormation / ApproachOwner per existing PlanIR.  
2. Classical goal generators publish `SE2Goal` as today (fix: ProposerBus is under-polled on mission path — D2 requires polling on the product path for ACTIVE; SHADOW compare can ride a side channel).  
3. ProposalIngress feeds SHADOW logs always; ACTIVE publish only when mode bit set **and** task_mode matches.  
4. `GoalArbiter.resolve` → single goal → `grid_v1`.  
5. Shaper → **D1 exact-zero monitor** → ControlManager → Sport.

### 6.4 Interaction with safety (N5)

- Model proposal **cannot** bypass person-stop, TTC, or LiDAR HOLD.  
- If D1 monitor asserts hard stop, buffers remain but commands are zero; on resume, require fresh proposals (discard pre-stop buffer).  
- Missing LiDAR on product profile: HOLD — do not ask MiniCPM to “drive open-loop.”

### 6.5 Interaction with identity / follow (audit S1.2)

D2 does **not** replace formation→common planner work. MiniCPM SHADOW compares against:

1. current proportional follow (legacy), and  
2. formation-goal→`grid_v1` (D1/D3 target),

but ACTIVE MiniCPM is only meaningful once (2) exists — otherwise A/B measures “model vs unsafe bypass,” which is invalid.

---

## 7. Acquisition order

Acquisition = legal clearance + pin/hash + reviewed remote code + isolated image. **Not** wire-to-motion.

| Rank | Artifact | Action | Shadow role | Blockers |
| ---: | --- | --- | --- | --- |
| 1 | **MiniCPM-RobotTrack** | First new download | Owner-follow / target-track | DINOv3/SigLIP/TRT third-party notices; author nonzero collisions |
| 2 | **CityWalker** | Review license scope on the byte-verified official v1.0 asset or separately pin HF `ai4ce/citywalker` | Urban XY prior | Original asset has no asset-specific notice/embedded SPDX (`NOASSERTION`); custom loader; Go1≠Go2; no yaw/language |
| 3 | **CE-Nav** | Review, then local-policy screen | Local detour | MIT repo directly carries Go2/VelFlow checkpoints; checkpoint scope, transitive dependencies, legacy Isaac/Orbit assets, and incomplete training release still need review |
| 4 | **X-NavDP** | Hold | Local detour | MIT subtree, HF weight-metadata gap, NC parent ambiguity, and Isaac assets |
| 5 | InternVLA-N1 S2 | Research-only if counsel clears NC | Instruction pixel-goal | NC badge + Hub metadata gap; co-residency unprofiled |
| 6 | NaVILA | Defer | Mid-level text→SE2 | Undeclared HF license + Llama 3 |

### MiniCPM acquisition checklist

1. Snapshot `openbmb/MiniCPM-RobotTrack`; hash `model.safetensors*`.  
2. Vendor reviewed modeling code; disable live network in image.  
3. Clear DINOv3 and SigLIP terms for any evaluation/live vision path; review
   TensorRT terms separately only when using the TRT deployment backend; record
   `THIRD_PARTY_NOTICES`.  
4. Offline feature→waypoint contract tests (synthetic RGB) before any robot process mounts.  
5. Go2 EDU dry-run path per upstream docs; Parcel keeps MOVE disabled until SHADOW gates pass.

### CityWalker acquisition checklist

1. Record the verified official v1.0/local identity, size 1,752,028,242 bytes
   and SHA-256 `a42326778e5e318c6222575dc5e02f1794d9a60cce4dc8f8a2ee5df7dc6d1c29`;
   separately resolve the original asset's license scope or use a legally
   approved, independently pinned HF conversion.  
2. Sandbox remote modeling code.  
3. Offline cached-waypoint path already sketched in `route_memory/citywalker.py` — extend to live IPC without importing torch into runtime.  
4. Profile Orin/desktop latency (today **UNVERIFIED**).

**Do not acquire for training:** InternData dumps, Isaac packs, “retrain MiniCPM from scratch.”

---

## 8. Evaluation ladder

Evidence classes from `EVALUATION_AND_ROADMAP.md` are binding. Never promote `derived_rescore` or author paper SR into product claims.

```text
L0  Contract smoke
    schema / TTL / reject fixtures / sandbox boot / no-Sport mount check

L1  Offline replay (bags / frozen RGB)
    MiniCPM: owner/distractor/occlusion frames → proposal quality vs identity gate
    CityWalker: urban point-goal bags → XY prior vs grid classical
    class: synthetic_unit | product_headless (if full runtime)

L2  SHADOW paired product_headless
    identical episodes; classical authority retained
    metrics: ShadowCompareV1; safety veto count; p99 latency; identity swaps = 0

L3  Role-matched suites (still SHADOW or ACTIVE-gated)
    MiniCPM: frozen owner-follow / walk-with-me style
    CityWalker: urban approach / sidewalk point-goal subset of NAV_INSTRUCT
    Do NOT compare R2R SR to EVT CR

L4  ACTIVE on headless (after L2–L3 gates)
    paired A/B vs classical-only; kill on safety/identity/p99 regression

L5  HIL dry-run (restrained / Sport MOVE disabled)
    MiniCPM upstream dry-run pattern; Parcel E-stop independent

L6  physical_supervised (staffed/fenced)
    separate authorization; not implied by L4
```

### Promotion gates (SHADOW → ACTIVE)

All required:

1. D1 P0-A/B/C/H green on same commit.  
2. L0–L2 green; ledger rows immutable.  
3. Role suite: no identity swap; no hard-safety veto regression; no collision increase.  
4. Paired product metric improvement **or** explicit “no-harm prior” acceptance with latency headroom (board call).  
5. License pin still valid (recheck Hub YAML + SPDX + SBOM at pin time).  
6. Co-residency profile under declared VRAM cap (desktop Ada 32 GB; Orin later).  
7. Deterministic HOLD, or re-admitted continuation of the same existing
   classical goal, on injected model kill mid-episode.

### Kill criteria (revert to SHADOW/OFF)

- Any S0-class residual motion attributable to proposal path (should be impossible if D1 intact — treat as P0 regression).  
- Identity silent swap.  
- p99 control-loop deadline miss attributable to IPC blocking.  
- License metadata change / hash drift.  
- Author-style “forward when no person” observed while Parcel identity gate open (gate bug).

### What does **not** promote

- MiniCPM EVT STT SR/TR/CR author numbers.  
- CityWalker Go1 77.3% author real-world.  
- NAV_INSTRUCT derived 0.12/0.16.  
- “Would have won arbiter” shadow counterfactuals alone.

---

## 9. Migration plan

### Phase M0 — ABI + harness (before weight download)

| Work | Owner sketch | Exit |
| --- | --- | --- |
| Add `NavProposalV1` to `contracts/v1.py` + freshness helpers | contracts | Golden reject tests in CI |
| ProposalIngress pure module + ShadowCompare logger | instructnav / nav | Unit tests, no GPU |
| Synthetic 8-waypoint fixture (Qwen-shaped) | evals | L0 green |
| Document Sport socket denylist in sandbox compose | deploy | Review checklist |

### Phase M1 — MiniCPM SHADOW

| Work | Exit |
| --- | --- |
| Pinned inference image; hash lockfile | Image boots offline |
| IPC client in runtime behind feature flag `proposers.minicpm.mode=shadow` | Default OFF in product YAML |
| Owner-follow frozen bag suite | L1–L2 ledger rows |
| Identity gate integration tests | Reject without ADMITTED |

### Phase M2 — CityWalker SHADOW

| Work | Exit |
| --- | --- |
| Provenance decision (local vs HF) recorded | Legal + hash |
| Extend `CityWalkerInferenceAdapter` → IPC service | Fail-closed skip preserved for CI without weights |
| Urban point-goal shadow suite | L1–L2 rows; no role bleed into follow |

### Phase M3 — Mission-path ProposerBus poll

| Work | Exit |
| --- | --- |
| Wire GoalArbiter poll on NavigateTo/FollowFormation product path | Classical still wins by priority |
| ACTIVE flag per model, default false | Config + ledger gate reference |

### Phase M4 — Gated ACTIVE + optional Orin profile

| Work | Exit |
| --- | --- |
| Promotion review using §8 gates | Board signoff artifact |
| Orin NX co-residency measurement | Numbers in ledger; drop proposers under pressure |

### Phase M5 — Later (out of D2 scope)

CE-Nav after checkpoint/dependency/legacy-Isaac review; X-NavDP after its
distinct legal review; InternVLA S2 research desktop; narrow ranker training
only after open baselines plateau (RL1/RL2).

### Config sketch

```yaml
# configs/navigation/proposers.yaml  (new; default safe)
proposers:
  ipc_deadline_ms: 250
  max_horizon_m: 3.0
  minicpm_robottrack:
    mode: off          # off | shadow | active
    ttl_s: 0.8
    pin_hash: ""       # required if mode != off
    priority: 10
  citywalker:
    mode: off
    ttl_s: 1.5
    pin_hash: ""
    priority: 5
```

Product default remains `mode: off` until M1/M2 explicitly enable SHADOW in eval profiles.

---

## 10. Risks and mitigations

| ID | Risk | Severity | Mitigation |
| --- | --- | --- | --- |
| R1 | Enabling shadows before D1 exact-zero / LiDAR HOLD | S0 confound | Hard prerequisite; CI flag rejects `mode!=off` if P0 pins red |
| R2 | `trust_remote_code` supply chain | High | Vendor review; no net; hash pin; SBOM |
| R3 | MiniCPM invents forward motion w/o person | High | Parcel identity + visibility gate; author warning treated as design input |
| R4 | Model → Sport accidental wiring | Critical | Sandbox device policy; code owners; architectural test: no import path from adapters to ControlManager |
| R5 | IPC blocks 20–50 Hz control | High | Non-blocking client; deadline; skip tick |
| R6 | CityWalker original-asset license ambiguity | Medium | Byte identity is verified; clear asset scope or legally approve a separate HF pin before ACTIVE |
| R7 | Priority inversion (model outranks classical) | Medium | Default classical priority ≥20; promotion changes require gate doc |
| R8 | VRAM fight with Gemma / perception | Medium | Time-share; drop proposers first under pressure; measure peaks |
| R9 | Evaluating wrong suite (R2R vs follow) | Medium | Role-matched episodes only; ledger rejects cross-denominator prose |
| R10 | Shadow “wins” psychologically without ACTIVE gates | Process | SHADOW metrics cannot flip product defaults |
| R11 | DiffDrive-shaped waypoints vs Sport tracking | Medium | Clamp horizon; classical controller tracks; Sport lag is D1/N1 U-Sport-track |
| R12 | Stale proposal after pause/resume | High | Invalidate buffers on revision/pause; P0-C atomic resume |
| R13 | Treating arrive logit / confidence as calibrated | Medium | Mark unknown; calibrate later on Parcel holdout |
| R14 | Co-scheduling 8B VLN later on Orin | High | Out of D2 default; desktop research only |

---

## 11. Shared ABI with D1 / D3 (team-review note)

| Surface | Shared across D1–D3? | D2-specific |
| --- | --- | --- |
| Exact-zero post-shaper monitor | **Yes** (D1 owns) | Consumes only |
| Fail-closed LiDAR/pose | **Yes** | Consumes only |
| `SE2Goal` / GoalArbiter | **Yes** | ACTIVE publish path |
| `NavProposalV1` + IPC | **Yes** (freeze once) | First consumers MiniCPM/CityWalker |
| Formation→grid | D1/D3 | MiniCPM ACTIVE depends on it |
| N11 re-rank / OSM advisory | D3 | CityWalker is prior, not crossing authority |
| Sport ownership | **Yes** | Absolute no model edge |

---

## 12. Engineer checklist (implementation order)

1. [ ] Land `NavProposalV1` + golden rejects (no GPU).  
2. [ ] ProposalIngress + ShadowCompare logger.  
3. [ ] Confirm D1 P0-A/B/C pins green on integration branch.  
4. [ ] MiniCPM sandbox image + hash pin.  
5. [ ] SHADOW owner-follow bags → ledger.  
6. [ ] CityWalker original-asset license/loader decision + SHADOW urban bags.  
7. [ ] Mission-path ProposerBus poll with classical priority.  
8. [ ] Promotion review → optional ACTIVE.  
9. [ ] Orin profile before any field SHADOW with MOVE enabled.

---

## 13. Bottom line

D2 is the **reuse path**: MiniCPM then CityWalker as sandboxed, TTL-bound SE(2) proposers behind a frozen `NavProposalV1` IPC, classical `grid_v1` execution, and D1 geometry veto. Default SHADOW; ACTIVE only after role-matched paired gates. Train nothing; grant Sport to no model.
