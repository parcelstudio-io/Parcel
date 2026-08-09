# DEEP Design D2 — Shadow-proposer hierarchy (v1)

**ID:** DEEP_D2  
**Title:** Shadow-proposer hierarchy — MiniCPM then CityWalker as out-of-process SE(2) proposers  
**Date:** 2026-08-07  
**Author role:** Claude Opus design stand-in (inherit relaunch; API-limited Opus wave)  
**Status:** deep implementation design for team review — **not implemented by this document**  
**Depth bar:** binding in [`README.md`](README.md) (≥3 passes, ≥20 file:line cites, ≥1,200 lines, worked scenario, safety argument, complete pseudocode, UNVERIFIED + acceptance matrix)  
**v0 contrast (shallow — do not implement from):** [`../DESIGN_D2_SHADOW_PROPOSERS.md`](../DESIGN_D2_SHADOW_PROPOSERS.md)  
**Depends on:** Design D1-class safety (exact-zero post-shaper monitor; fail-closed LiDAR/pose; atomic lifecycle)  
**Inputs:** [`../../RESEARCH_THESIS.md`](../../RESEARCH_THESIS.md), [`../../research/RL2_OPEN_WEIGHT_REUSE.md`](../../research/RL2_OPEN_WEIGHT_REUSE.md), [`../../research/N2_INSTRUCTION_VLN.md`](../../research/N2_INSTRUCTION_VLN.md), [`../../research/N1_CLASSICAL_NAV.md`](../../research/N1_CLASSICAL_NAV.md), [`../../research/N5_SAFETY_AUTHORITY.md`](../../research/N5_SAFETY_AUTHORITY.md), [`../../research/OPUS_INDEPENDENT_AUDIT.md`](../../research/OPUS_INDEPENDENT_AUDIT.md), [`../../TARGET_ARCHITECTURE.md`](../../TARGET_ARCHITECTURE.md), [`../../CURRENT_STACK_AUDIT.md`](../../CURRENT_STACK_AUDIT.md)  
**Sibling designs:** DEEP_D1 classical companion; DEEP_D3 social city  
**Safety status:** Not a certification case. No unsupervised physical motion. Models propose only. **No Sport path.**

---

## Pass log (binding)

| Pass | Kind | What changed | Exit criterion |
| ---: | --- | --- | --- |
| 0 | Inventory | Re-read thesis, RL2, N1/N2/N5, audit, TARGET_ARCHITECTURE, v0 D2, CityWalker adapter, arbiter, freshness, grid_v1, follow, crossing, WebSearch MiniCPM-RobotTrack + CityWalker I/O/licenses | Source map + open gaps listed |
| 1 | Draft | Full architecture, ABI freeze, complete ingress/TTL/arbiter/adapter algorithms, sandbox, eval ladder, migration | Every mechanism has Why-it-will-work triple |
| 2 | Adversarial self-critique | Attacked: Sport bleed, identity oracle creep, CityWalker road legality, IPC blocking, SHADOW promotion theater, license NOASSERTION, follow-bypass confounding A/B, TTL coasting after pause | Weak sections rewritten; kill criteria hardened |
| 3 | Gap expansion | Worked tick narrative, golden reject fixtures, compose/sandbox denylist, complete Python-shaped pseudocode modules, acceptance matrix rows, UNVERIFIED register, co-residency drop order | ≥1,200 lines dense technical prose/code; ≥20 Parcel file:line cites |

**Pass 0 inventory artifacts retained below as §A.**  
**Pass 2 critique retained as §B.**  
**No early exit:** if line count or cite count fails after Pass 3, continue expanding gaps rather than declaring done.

---

## 0. One-line thesis

MiniCPM-RobotTrack, then CityWalker, run as **out-of-process SE(2) proposers** behind TTL, sandbox, schema-validated `NavProposalV1`, classical `grid_v1` execution, and an independent D1 geometry veto — never as Sport writers, identity oracles, free-space authorities, or curb/road legality oracles. Default mode is **SHADOW**. ACTIVE is a ledgered gate, not a YAML flip.

---

## 1. Why re-derive (v0 is shallow)

v0 `DESIGN_D2_SHADOW_PROPOSERS.md` is directionally correct and already states the right hard cut (no model → Sport). It fails the deep bar because:

1. **Mechanisms lack falsifiers.** TTL, identity gate, lethal mask, and SHADOW-vs-ACTIVE are listed but not argued as *why they will work* with precedent + Parcel binding + what would disprove them.
2. **Pseudocode is incomplete for implementers.** Ingress validate is sketched; the service-side adapters, IPC framing, buffer invalidation on pause/revision, and Sport denylist checks are not implementable end-to-end.
3. **Worked scenario missing.** Hardest product case (owner-follow with distractor + occlusion + model inventing forward motion) has no tick-level state narrative.
4. **Cite density insufficient.** Claims about residual stop velocity, LiDAR open-loop, arbiter TTL, CityWalker gate-off, follow bypass are asserted without enough `file:line` anchors for review.
5. **License/I/O facts are summary-only.** Deep D2 must pin concrete MiniCPM and CityWalker I/O shapes and Apache/NOASSERTION handling from primary sources (rechecked 2026-08-07).
6. **Interaction with P0 defects underspecified.** Enabling SHADOW before P0-A/B/C confounds capability with authority; v0 lists prerequisites but does not make CI refuse `mode!=off` when pins are red.

This document re-derives D2 from research + source, treating v0 as contrast archive only.

---

## A. Pass 0 — Source inventory (kept)

### A.1 Research consensus (must obey)

| Claim | Source | D2 consequence |
| --- | --- | --- |
| Typed proposals + fail-closed metric authority; models never own Sport | RESEARCH_THESIS §1, TARGET_ARCHITECTURE §6 | Absolute hard cut left of ControlManager |
| Reuse before train; MiniCPM first, CityWalker second | RL2 acquisition queue; thesis §4.3 | Acquisition order binding |
| Proposals-only SE(2) + TTL shadow; Qwen 8× waypoints = ABI north star | N2 §1–§2 | `NavProposalV1.relative_se2_waypoints` |
| Keep `grid_v1` production writer; Nav2 exclusive challenger | N1 verdict | Models feed GoalArbiter → grid, never co-write velocity |
| Exact-zero after shaper; missing LiDAR HOLD on product | N5 verdict; thesis P0.1/P0.2 | D1 prerequisite; SHADOW must not widen envelopes |
| CityWalker advisory XY only; zero autonomous road entry | N8 / maps crossing | CityWalker never clears curb/road |
| Author EVT/Go1 SR are not Parcel evidence | RL2, N2, thesis §6 | Promotion uses Parcel frozen suites only |

### A.2 Parcel seams that already exist (extend, do not fork)

| Seam | Path | What D2 extends |
| --- | --- | --- |
| `SE2Goal` / `ProposerBus` / `GoalArbiter` | `instructnav/arbiter.py` | ACTIVE publish + lethal veto already present; SHADOW must **not** publish |
| CityWalker fail-closed adapter | `route_memory/citywalker.py` | Gate-off default; cached offline → SE2Goal; live torch not wired |
| Freshness helpers | `contracts/freshness.py` | Fail-closed TTL / clock-jump reject |
| Authority triple | `authority.py` | Elementwise-min; models never raise caps |
| Rolling A* writer | `navigation/grid_navigator.py` | Sole production consumer of winner |
| Follow proportional bypass | `navigation/follow.py` | ACTIVE MiniCPM only meaningful after formation→grid (D1) |
| Authenticated crossing gate | `maps/crossing.py` | CityWalker and transcript text cannot authorize road |
| Runtime Sport path | `runtime.py` ControlManager | No model import edge |

### A.3 External model facts (WebSearch 2026-08-07)

**MiniCPM-RobotTrack** ([openbmb/MiniCPM-RobotTrack](https://huggingface.co/openbmb/MiniCPM-RobotTrack), [OpenBMB/MiniCPM-Robot](https://github.com/OpenBMB/MiniCPM-Robot)):

- Apache-2.0 code **and** weights (HF card + repo LICENSE).
- ~0.9B; language-conditioned track; predicts **eight** future `(x, y, yaw)` waypoints.
- Load path uses `AutoModel.from_pretrained(..., trust_remote_code=True)`.
- Author Go2 EDU + Orin NX: ~5+ FPS / ~180 ms e2e; **defaults dry-run**; live control requires explicit MOVE.
- EVT-Bench author CR nonzero: STT CR 3.0%, DT CR 13.6%, AT CR 9.0% (not Parcel).
- Deployment guide warns policy may **predict forward motion when no person is visible**; client has ~1.5 s stale-plan brake (useful pattern, not Parcel safety).
- Third-party: DINOv3 gated, SigLIP, TRT, Unitree SDK — record `THIRD_PARTY_NOTICES`.

**CityWalker** ([ai4ce/CityWalker](https://github.com/ai4ce/CityWalker), [ai4ce/citywalker](https://huggingface.co/ai4ce/citywalker)):

- Apache-2.0 upstream + HF port Apache-2.0.
- Inputs: `images (B,5,3,H,W)` RGB in [0,1]; `coords (B,6,2)` = 5 past + 1 target relative poses / `step_scale`.
- Outputs: `waypoints (B,5,2)` XY in relative frame (× `step_scale` → meters); `arrive_logits (B,1)` pre-sigmoid.
- **No yaw.** Downstream derives heading via `atan2` if needed.
- Local Parcel ckpt path `models/nav/citywalker/CityWalker_2000hr.ckpt` is
  byte-identical to official v1.0 (`a423…c1c29`) and scans `NOASSERTION` —
  original-asset license scope and loader review remain required before ACTIVE.
- Paper real-robot: Go1 fine-tune ~77.3% author success ≠ Go2 zero-shot; ≠ Parcel NAV_INSTRUCT.

### A.4 Gaps D2 must close

1. `NavProposalV1` is specified in TARGET_ARCHITECTURE §6 but **not** yet a type in `contracts/v1.py` (grep empty). Freeze it here; land in M0.
2. ProposerBus exists on pipeline but mission-path poll / SHADOW compare harness incomplete for product A/B.
3. Live CityWalker torch path intentionally unwired (`citywalker.py` skip) — D2 specifies out-of-process service so runtime never imports torch.
4. MiniCPM has **no** in-tree adapter — first greenfield service under this ABI.
5. Product default follow still proportional (`follow.py` `_step_direct`) — ACTIVE MiniCPM A/B invalid until formation→grid lands (D1).

---

## B. Pass 2 — Adversarial self-critique (attacks that forced rewrites)

| Attack | Failure if ignored | Mitigation locked in Pass 3 |
| --- | --- | --- |
| Accidental model→Sport wiring via “temporary” adapter | S0 motion without classical authority | Architectural import test; sandbox device denylist; compose mounts |
| Identity oracle creep (“ask MiniCPM if this is owner”) | Silent swap / distractor follow | Parcel ADMITTED gate **before** inference; reject without calling model |
| CityWalker tip into road keepout treated as clearance | Autonomous road entry | Crossing policy remains sole road authority; lethal/road mask at ingress |
| IPC `recv` blocks 20–50 Hz loop | Deadline miss / residual unsafe motion | Non-blocking client; skip tick ≡ unavailable |
| SHADOW “would_have_won” used to flip product YAML | Promotion theater | Ledger gates; SHADOW metrics cannot change defaults |
| Local CityWalker `NOASSERTION` ignored | License violation | Byte identity is verified; clear original-asset scope or legally approve a separate HF pin before ACTIVE |
| ACTIVE MiniCPM vs proportional follow | Confounds model vs planner bypass | Gate ACTIVE on formation→grid existence |
| TTL coast after pause/resume | Motion on stale tip | Invalidate buffers on revision/pause; require fresh proposal |
| Treating arrive_logit / confidence as calibrated P | Soft safety inflation | Mark UNKNOWN; never widen hard masks |
| Co-scheduling Gemma + MiniCPM + CityWalker + OV | Orin/desktop OOM → control starvation | Drop order: OV → proposers → semantics; never drop geometry/safety |

---

## 2. Goals, non-goals, prerequisites

### 2.1 Product goals

| ID | Goal | Success looks like |
| --- | --- | --- |
| G1 | Reuse before train | Zero custom RL/VLA GPU-hours until open shadows plateau on a frozen residual |
| G2 | Interpretable A/B | Every episode logs accept/reject/TTL/veto/fallback with identical classical baseline |
| G3 | Role-matched models | MiniCPM = owner-follow / target-track waypoints; CityWalker = urban XY prior — never swap |
| G4 | Fail-closed continuity | Crash, OOM, deadline miss, stale TTL, veto ⇒ exact-zero HOLD by default; an existing classical goal continues only through the full authorization/freshness/geometry admission contract |
| G5 | No Sport path | No process boundary, IPC message, or code path maps model output → Unitree velocity |

### 2.2 Non-goals

1. End-to-end VLA / language→motor / LowCmd locomotion.
2. Nav2 as production writer (N1: `grid_v1` sole production consumer).
3. Acquiring X-NavDP, InternVLA-N1, NaVILA into product images (license gates).
4. Treating author EVT / Go1 / VLN-CE scores as Parcel NAV_INSTRUCT or safety evidence.
5. Granting MiniCPM owner-identity or presence truth; granting CityWalker curb/road legality or language goals.
6. Shipping SHADOW→ACTIVE without §14 eval ladder.
7. Training / fine-tuning MiniCPM or CityWalker in this program phase.

### 2.3 Prerequisites (D1-class — hard)

| Gate | Bar | Why D2 cannot waive |
| --- | --- | --- |
| P0-A | Same-dispatch HAL command `==(0,0,0)` on hard safety stop; shaper/smoother reset | Residual stop velocity makes model A/B uninterpretable (N5) |
| P0-B | Missing/stale/malformed LiDAR, pose, or transform → HOLD/STOP on product profile | Open-loop `scan_missing_fallback` would let ACTIVE tip drive into unknown space |
| P0-C | Resume restores `{task, revision, channel}` atomically | Stale proposals after channel-only resume |
| P0-F | Versioned `NavProposalV1` + golden reject tests | Without ABI, shadows are ad-hoc |

**CI rule:** product/eval configs with `proposers.*.mode != off` **must fail** if P0-A/B/C pin markers are red on the same commit.

---

## 3. Architecture

### 3.1 Diagram

```text
  Owner speech / TaskExecutive (revision, deadlines, witnesses)
            │
            │  formation / NavigateTo / ApproachOwner semantic goal
            ▼
  ┌─────────────────────────────────────────────────────────────┐
  │ ObservationSnapshotV1 {ids, stamps, frame, abi_hash, health} │
  └───────────────────────────┬─────────────────────────────────┘
                              │
         ┌────────────────────┼────────────────────┐
         │                    │                    │
         ▼                    ▼                    ▼
  Classical path      MiniCPM sandbox       CityWalker sandbox
  (always live)       (out-of-process)      (out-of-process)
  SearchEntity /      Apache pin+hash       provenance pin
  formation goals /   RGB feats → 8×SE2     RGB hist → 5×XY
  grid_v1 A*          waypoints             + arrive logit
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
         │                  · role gate (CityWalker only)
         │                  · hard kinematic + occupancy + road mask
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
                              FINAL metric-geometry monitor (D1)
                              (exact zero; never widens)
                                       │
                              ControlManager → Unitree Sport
```

**Hard cut:** everything left of Sport is Parcel authority. Model boxes have **no** edge into ControlManager, Sport sockets, or HAL adapters.

### 3.2 Component ownership matrix

| Component | Owns | Must not own |
| --- | --- | --- |
| MiniCPM-RobotTrack service | Relative SE(2) track waypoints + raw diagnostics | Owner ID, presence, free space, Sport cmd |
| CityWalker service | Relative XY polyline + arrive logit | Language goal, social cost, curb/road entry, yaw truth |
| ProposalIngress | Schema, TTL, frame, masks, veto log | Planner path selection |
| ProposerBus / GoalArbiter | Latest-only SE2Goal competition | Motor ticks |
| `grid_v1` | Occupancy path + local tracking | Model logits |
| Post-shaper geometry monitor (D1) | Exact-zero hard stop; freshness STOP | Soft ranking |
| Crossing policy | Authenticated, authorized owner/control-channel decision bound to task revision, event ID, curb-stop state, and TTL | CityWalker tips or transcript/phrase matches |
| Unitree Sport | Gait / balance | Task success |

### 3.3 Why this architecture will work

**Precedent:** Dual-system VLN (InternVLA-N1 S2 proposes, S1/local executes), NaVILA mid-level actions above locomotion, Nav2 Collision Monitor after smoother, InstructNav propose/dispose, Qwen-RobotNav 8× waypoint interface — all converge on mid-level goals under classical/safety authority (N2, TARGET_ARCHITECTURE §6).

**Parcel binding:** `GoalArbiter` already vetoes TTL-expired and lethal goals and states `grid_v1` as sole consumer (`instructnav/arbiter.py:110–158`). CityWalker adapter already refuses velocity authorship and defaults `gate_enabled=False` (`route_memory/citywalker.py:130–155`, `214–215`). Authority uses elementwise-min (`authority.py:62–68`).

**Falsifier:** Any merged PR that (a) maps `NavProposalV1` → `VelocityCommand` without going through GoalArbiter→`grid_v1`→D1 monitor, or (b) mounts Sport sockets into the model container, falsifies this architecture. Architectural tests in §16 must catch both.

---

## 4. Mechanisms (each with Why it will work)

Every mechanism below is **binding**. Format: definition → Why (precedent / Parcel binding / falsifier) → complete behavior.

### 4.1 Mechanism M1 — Out-of-process proposers

**Definition:** MiniCPM and CityWalker run in separate OS processes (container preferred) with no shared address space with `RobotRuntime`. Communication is request/response `NavProposeRequestV1` → `NavProposalV1 | NavProposeErrorV1` only.

**Why it will work**

- **Precedent:** Production robot stacks isolate GPU inference (TRT servers, ROS nodes); MiniCPM’s own Go2 path already separates feature extractors / inference / control client; supply-chain `trust_remote_code` is unreviewable if imported into the control process (RL2 shadow contract).
- **Parcel binding:** Runtime today must not gain a torch dependency for CI (CityWalker skip when torch missing: `citywalker.py:176–182`, `237–241`). Out-of-process preserves that invariant.
- **Falsifier:** Import graph from `parcel_robot.runtime` → `transformers` / CityWalker `model` package in product image; or shared-memory writable weights cache mounted RW into control process.

### 4.2 Mechanism M2 — `NavProposalV1` schema freeze (P0-F / P3-C)

**Definition:** Single versioned ABI for all navigation proposers. See §5 for full schema. No ad-hoc dicts on the hot path.

**Why it will work**

- **Precedent:** Qwen-RobotNav’s public interface is 8× `(x,y,θ)` waypoints (N2 §3.6); CityWalker HF port documents explicit tensor shapes; typed contracts beat logit soup for rollback and golden tests.
- **Parcel binding:** TARGET_ARCHITECTURE §6 already names the fields; `contracts/freshness.py` pattern shows Parcel prefers fail-closed typed verdicts (`FreshnessVerdict`, `check_freshness` at `freshness.py:27–111`).
- **Falsifier:** Product path accepts proposals missing `expires_at`, `observation_ids`, or `model_hash`; or silently coerces non-finite waypoints to 0.

### 4.3 Mechanism M3 — TTL + latest-only buffer

**Definition:** Each proposal carries `produced_at` and `expires_at`. Per-`model_id` single-slot buffer. Newer `produced_at` replaces older even if unexpired. On control tick, expired slots drop. No coasting on last tip after expiry.

**Recommended budgets (start; remeasure under co-residency):**

| Model | `ttl_s` | Rationale |
| --- | --- | --- |
| MiniCPM | 0.5–1.0 | Reactive track; author ~180 ms e2e; stale track is lethal |
| CityWalker | 1.0–2.0 | Slower urban prior; still revalidated each cycle |
| System-2 research (later) | ≤2.0 at ingress | Revalidation each cycle; no long-horizon trust |

Align with existing freshness defaults where applicable: `DEFAULT_TRACK_TTL_NS = 500_000_000` (`contracts/freshness.py:15`).

**Why it will work**

- **Precedent:** AsyncShield / Nav2 source_timeout stop on stale evidence (N1 collision monitor); MiniCPM upstream ~1.5 s stale-plan brake; Parcel `SE2Goal.expired` (`arbiter.py:35–36`); GoalArbiter skips expired (`arbiter.py:136–137`).
- **Parcel binding:** ProposerBus already overwrites `_latest[source]` (`arbiter.py:64–65`, `100–101`). Affect proposals use `expires_at` (`core/activities.py:42`, `120`). Crossing auth TTL (`maps/crossing.py:58`, `158`).
- **Falsifier:** Control tick continues tracking a tip after `expires_at`; or pause/resume reuses pre-pause buffer without invalidation.

### 4.4 Mechanism M4 — ProposalIngress validation (hard reject)

**Definition:** Pure function `validate(p, ctx) → Accept|Reject`. Reject never raises envelopes, never substitutes nearest-person, never opens StubNavigator translation. See §6.2 complete algorithm.

**Why it will work**

- **Precedent:** Fail-closed sensors (Nav2 collision monitor invalid source → STOP); aviation/auto stacks reject bad messages rather than “best effort” geometry.
- **Parcel binding:** Freshness rejects clock jumps (`freshness.py:114–149`); CityWalker bounds absurd waypoint steps (`citywalker.py:259–274`); GoalArbiter lethal veto (`arbiter.py:139–142`).
- **Falsifier:** Reject path that still publishes to ProposerBus; or Reject that mutates occupancy to “make progress.”

### 4.5 Mechanism M5 — SHADOW default / ACTIVE gated

**Definition:**

```text
enum ProposerMode: OFF | SHADOW | ACTIVE
```

- **OFF:** process not started; classical only.
- **SHADOW:** validate + log `ShadowCompareV1`; **never** `ProposerBus.publish`.
- **ACTIVE:** validated proposals may publish; still GoalArbiter + D1 vetoable.

Product YAML default: `mode: off`. Eval profiles may set `shadow`. `active` requires ledger gate reference.

**Why it will work**

- **Precedent:** MiniCPM dry-run-first deployment; shadow mode in autonomy stacks for policy comparison without command authority; RL2 “propose never command.”
- **Parcel binding:** CityWalker `gate_enabled: bool = False` (`citywalker.py:134`); thesis Phase 4 shadows before HIL.
- **Falsifier:** Config with `active` but no ledger artifact hash; or SHADOW path that still calls `bus.publish`.

### 4.6 Mechanism M6 — Classical `grid_v1` sole production writer

**Definition:** Winner `SE2Goal` becomes a planning goal for `grid_v1`. Models never emit `VelocityCommand`. Nav2 remains exclusive challenger (N1), never co-writer with models.

**Why it will work**

- **Precedent:** Nav2 organizational split planner/controller/monitor; adjudication D1 keep grid production writer (N1).
- **Parcel binding:** `active_model: grid_v1` (`configs/navigation/default.yaml:8`); GoalArbiter docstring (`arbiter.py:114`); pipeline constructs SE2Goal for arbiter path (`navigation/pipeline.py:1425–1433` region).
- **Falsifier:** Active product profile with two velocity writers; or model adapter returning `VelocityCommand`.

### 4.7 Mechanism M7 — D1 independent geometry veto (exact zero)

**Definition:** Post-shaper metric-geometry monitor forces exact zero on hard stop; never widens upstream envelopes. Model proposals cannot bypass person-stop, TTC, or LiDAR HOLD.

**Why it will work**

- **Precedent:** Nav2 Collision Monitor after velocity smoother (N1 §5); ISO-shaped stop distance form in SafetyEnvelope.
- **Parcel binding:** Current defect is residual slew after proximity stop (`velocity_shaping.py:102–105`; N5 §2) — D1 must fix before ACTIVE. Default grid open-loop on missing scan (`grid_navigator.py:335–357`) — D1/P0-B must HOLD on product. Latched E-stop path already resets (`runtime.py:2040–2050`).
- **Falsifier:** Hard stop tick with HAL `vx != 0`; or missing LiDAR still stamping `scan_missing_fallback` on product profile while ACTIVE enabled.

### 4.8 Mechanism M8 — Identity gate (MiniCPM only)

**Definition:** Before MiniCPM inference **and** at ingress: require Parcel enrolled-owner posterior `ADMITTED` and target visibility M-of-N. Do not ask the model “is this the owner?” Do not emit presence=true from RGB alone.

**Why it will work**

- **Precedent:** Companion robots fail by nearest-person substitution; MiniCPM author CR under distractors (DT 13.6%) and forward-when-invisible warning — identity/presence must be outside the model (TARGET_ARCHITECTURE §4; RL2).
- **Parcel binding:** Thesis P1.2 identity sim-perfect risk; follow uses `owner.owner_id` in decisions (`follow.py:617–618`) but identity quality is a separate contract; TARGET_ARCHITECTURE forbids silent closest-person.
- **Falsifier:** MiniCPM Accept while identity state ≠ ADMITTED; or automatic switch to nearest track on LOST.

### 4.9 Mechanism M9 — Role gate (CityWalker only)

**Definition:** CityWalker proposals accepted only for `POINT_GOAL | URBAN_APPROACH | DETOUR`. Reject `OWNER_FOLLOW` / `TARGET_TRACK`. Never set road-entry or crossing clearance bits.

**Why it will work**

- **Precedent:** CityWalker is urban walking/driving IL prior without language/social/yaw (RL2 dossier); N8 advisory vs metric split.
- **Parcel binding:** Crossing policy zero autonomous road entry (`maps/crossing.py:4–5`, `85`, `199–227`); CityWalker priority intentionally below OSM until promotion (`citywalker.py:139`).
- **Falsifier:** CityWalker Accept with `task_mode=OWNER_FOLLOW`; or proposal clearing `autonomous_road_entry_blocked`.

### 4.10 Mechanism M10 — Sandbox + pin/hash + no network

**Definition:** Container/cgroup: pinned image + SBOM; weights + reviewed modeling code only; network none; credentials none; writable tmpfs only; no Sport/HAL device nodes; VRAM/RSS caps; kill on overrun; vendored `trust_remote_code`.

**Why it will work**

- **Precedent:** Supply-chain attacks via HF remote code; RL2/N2 mandatory sandbox; MiniCPM deployment already sets offline HF env in go2_runtime patterns.
- **Parcel binding:** CityWalker CI skip-honest when vendor/weights missing (`citywalker.py:27–33`); product must not break without GPU.
- **Falsifier:** Sandbox with `network=host` or `/dev` Sport socket mounted; or live `trust_remote_code` fetch at runtime.

### 4.11 Mechanism M11 — Deterministic fallback

**Definition:** Any unavailable/reject/TTL/veto → exact-zero HOLD by default.
An existing classical goal may continue only if it is independently grounded,
still current for the same authenticated and authorized task/revision, and all
evidence, pose, transform, controller, and metric-geometry freshness gates pass
again. Never invent a new fallback goal or open-loop translation to “use the
model somehow.”

**Why it will work**

- **Precedent:** Fail-closed autonomy; Nav2 source_timeout STOP.
- **Parcel binding:** Today’s wrong pattern is StubNavigator open-loop (`grid_navigator.py:242`, `353–354`) — D2 must not amplify it. HOLD via safe-valley pattern (`337–341`) is the product direction under P0-B.
- **Falsifier:** Fallback that calls StubNavigator translation because “model was almost valid.”

### 4.12 Mechanism M12 — Priority: classical outranks models by default

**Definition:** ACTIVE defaults: classical formation/NavigateTo priority ≥20; MiniCPM=10; CityWalker=5. Models are helpers. Promotion may raise a model for a **named** `task_mode` after gates — never globally.

**Why it will work**

- **Precedent:** Safety-rated systems keep certified planner above learned tips.
- **Parcel binding:** GoalArbiter sorts by `-priority, -confidence, -issued_s` (`arbiter.py:150–157`); CityWalker priority=1 today (`citywalker.py:139`).
- **Falsifier:** Default ACTIVE config with MiniCPM priority > classical on product YAML without gate doc.

### 4.13 Mechanism M13 — No Sport (absolute)

**Definition:** No IPC type, adapter method, or container mount may produce Unitree Sport Move/StopMove commands from model outputs. Sport remains behind ControlManager only (`runtime.py` emergency/control paths).

**Why it will work**

- **Precedent:** Thesis bottom line; MiniCPM dry-run default acknowledges motion authority is earned separately.
- **Parcel binding:** ControlManager is the sole Sport boundary in product path (CURRENT_STACK_AUDIT product path diagram); `axes_commissioned: false` fail-closed until commissioned (thesis P0.7).
- **Falsifier:** Any code path `NavProposalV1 → sport.move` or model container with Sport SDK credentials.

### 4.14 Mechanism M14 — Observation + revision binding

**Definition:** Proposal must cite `observation_ids` matching current `ObservationSnapshotV1` and `task_revision` matching executive. Mismatch → Reject. Pause/cancel/revision → flush buffers.

**Why it will work**

- **Precedent:** ROS 2 action goal identity; PLEXIL suspend≠outcome (N6 / thesis).
- **Parcel binding:** Resume defect today restores channel without executive task (`runtime` / thesis P0.4; `executive.py:645` `resume_task` exists but closed-intent resume undershoots) — D2 must flush on revision regardless.
- **Falsifier:** Accept with mismatched revision; or buffer surviving pause.

### 4.15 Mechanism M15 — Uncalibrated confidence policy

**Definition:** Raw model logits / author confidence → `confidence="unknown"` / numeric 0.0 for arbiter until Parcel calibration set exists. Arrival logit marked uncalibrated. Never widen hard masks based on confidence.

**Why it will work**

- **Precedent:** Probability calibration literature; TARGET_ARCHITECTURE §6 explicit warning.
- **Parcel binding:** `SE2Goal.confidence` required in [0,1] (`arbiter.py:30–31`) — map unknown → 0.0 so classical wins ties on confidence.
- **Falsifier:** Using CityWalker arrive_logit > τ to disable person-stop or lethal mask.

---

## 5. `NavProposalV1` + IPC contract (frozen)

### 5.1 Schema

```text
NavProposalV1 {
  # Producer identity
  model_id:               "minicpm_robottrack" | "citywalker" | string
  model_hash:             sha256 hex of pinned weights (+ reviewed code digest)
  service_instance_id:    string

  # Binding to Parcel executive + evidence
  task_id:                string
  task_revision:          uint64
  plan_step_id:           string
  observation_ids:        string[]          # must match ObservationSnapshotV1
  captured_at:            float64 seconds   # sensor time of primary evidence
  produced_at:            float64 seconds   # service clock as declared
  expires_at:             float64 seconds   # hard TTL

  # Geometry
  frame:                  "base_link" | "odom" | "map"
  relative_se2_waypoints: [ {x, y, yaw_rad | null} ; N=1..16 ]
  time_from_start:        float64[] | null
  waypoint_covariance:    float64[] | null  # null ⇒ unknown/large
  arrival_probability:    float64 | null    # null or uncalibrated marker
  confidence:             float64 | "unknown"

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

### 5.2 Request / error

```text
NavProposeRequestV1 {
  request_id,
  deadline_at,
  task_id, task_revision, plan_step_id, task_mode,
  observation_snapshot_ref,   # shm or pinned bag frame path
  pose_ref,                   # odom_T_base at captured_at; health
  goal_hint | null,           # CityWalker point goal; MiniCPM track target if admitted
  input_abi_hash
}

NavProposeErrorV1 {
  request_id,
  code: DEADLINE | OOM | INTERNAL | UNSUPPORTED_MODE | NO_EVIDENCE | IDENTITY_CLOSED,
  message
}
```

All errors ≡ unavailable proposer.

### 5.3 IPC properties

| Property | Choice |
| --- | --- |
| Transport | Unix domain socket **or** localhost gRPC; no WAN |
| Framing | Length-prefixed JSON (v1) or protobuf with JSON golden twins |
| Auth | Filesystem socket permissions + peer credential check |
| Deadline | Client-enforced (MiniCPM default 250 ms; CityWalker 400 ms — tune) |
| Buffering | Latest-only; drop in-flight older responses when newer request issued |
| Backpressure | If service busy → skip tick; admit an existing classical goal only through M11, otherwise HOLD |
| Crash | Supervisor restarts service; Parcel treats absence as OFF until first valid proposal |

### 5.4 Mapping to in-process `SE2Goal`

```text
SE2Goal {
  source:       model_id,
  pose:         first waypoint (x,y,yaw) OR tip with derived yaw,
  waypoints:    XY pairs,
  frame:        transformed planner frame,
  confidence:   0.0 if unknown else calibrated,
  ttl_s:        expires_at - now,
  plan_step_id: from proposal,
  issued_s:     now (ingress stamp — not model clock),
  priority:     ACTIVE defaults MiniCPM=10, CityWalker=5
}
```

Parcel binding for fields: `SE2Goal` definition at `instructnav/arbiter.py:12–49`.

### 5.5 Golden reject fixtures (CI, no weights)

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
11. CityWalker tip in road keepout without a task/revision-bound authenticated and authorized crossing decision  
12. `input_abi_hash` mismatch  
13. Pose health DEGRADED/LOST on product profile  
14. Clock skew `produced_at > now + skew`  
15. Empty after horizon clamp  

Synthetic 8-waypoint fixture (Qwen-shaped) covers schema without MiniCPM weights.

---

## 6. Complete implementable algorithms

### 6.1 Modes and config

```yaml
# configs/navigation/proposers.yaml  (new; default safe)
proposers:
  ipc_deadline_ms: 250
  max_horizon_m: 3.0
  require_p0_pins: true
  minicpm_robottrack:
    mode: off          # off | shadow | active
    ttl_s: 0.8
    pin_hash: ""       # required if mode != off
    priority: 10
    request_hz: 4.0
  citywalker:
    mode: off
    ttl_s: 1.5
    pin_hash: ""
    priority: 5
    request_hz: 1.5
```

### 6.2 ProposalIngress.validate (complete)

```text
function validate(p: NavProposalV1, ctx: IngressContext, now: float)
    -> (Accept(SE2Goal) | Reject(reason)):

  # 1. Schema / finiteness / pins
  if not schema_ok(p):                        return Reject("schema")
  if not all_finite_waypoints(p):             return Reject("nonfinite")
  if p.model_hash != pinned_hash(p.model_id): return Reject("hash_mismatch")
  if p.input_abi_hash != ctx.obs_abi_hash:    return Reject("abi_mismatch")

  # 2. Task / revision binding
  if p.task_id != ctx.active_task_id:         return Reject("task_mismatch")
  if p.task_revision != ctx.active_revision:  return Reject("stale_revision")

  # 3. Observation freshness (fail-closed)
  if any_obs_missing_or_stale(p.observation_ids, ctx):
                                              return Reject("stale_observation")
  if ctx.pose.health in {DEGRADED, LOST} and ctx.profile.requires_healthy_pose:
                                              return Reject("pose_unhealthy")

  # 4. TTL / clock
  if now > p.expires_at:                      return Reject("ttl_expired")
  if p.produced_at > now + ctx.clock_skew_s:  return Reject("clock_skew")

  # 5. Frame / transform
  if not can_transform(p.frame → ctx.planner_frame, p.captured_at, ctx):
                                              return Reject("transform")

  # 6. Horizon clamp
  wps = clamp_horizon(p.relative_se2_waypoints, ctx.max_proposal_horizon_m)
  if empty(wps):                              return Reject("empty_after_clamp")

  # 7. Role / identity gates
  if p.model_id == "minicpm_robottrack":
      if ctx.owner_posterior.state != ADMITTED: return Reject("identity_gate")
      if not ctx.target_visible_m_of_n:       return Reject("no_target")
      if p.task_mode not in {OWNER_FOLLOW, TARGET_TRACK}:
                                              return Reject("role_mismatch")
  if p.model_id == "citywalker":
      if p.task_mode not in {POINT_GOAL, URBAN_APPROACH, DETOUR}:
                                              return Reject("role_mismatch")
      if (any_in_road_keepout(wps, ctx)
          and not valid_bound_crossing_authorization(ctx, p)):
                                              return Reject("road_keepout")

  # 8. Hard masks (geometry — not soft social)
  if any_waypoint_lethal(wps, ctx.occupancy, ctx.keepout):
                                              return Reject("lethal_mask")
  if violates_kinematic_profile(wps, ctx.kinematic_profile_id):
                                              return Reject("kinematic")

  # 9. Confidence
  conf = 0.0 if p.confidence == "unknown" else calibrated_or_zero(p.confidence)

  goal = SE2Goal(
      source=p.model_id,
      pose=se2_tip(wps),
      waypoints=xy_only(wps),
      frame=ctx.planner_frame,
      confidence=conf,
      ttl_s=max(1e-3, p.expires_at - now),
      plan_step_id=p.plan_step_id,
      issued_s=now,
      priority=ctx.priority_for(p.model_id),
  )
  return Accept(goal)
```

### 6.3 Latest-only buffer + SHADOW/ACTIVE tick

```text
buffer: dict[model_id, AcceptedGoal | None] = {}
mode: dict[model_id, ProposerMode]

on_message(p):
  verdict = validate(p, ctx, now=wall_now())
  log_ingress(verdict, p)
  if verdict is Reject: return
  cur = buffer.get(p.model_id)
  if cur is None or p.produced_at >= cur.produced_at:
    buffer[p.model_id] = verdict.goal_with_meta(produced_at=p.produced_at)

on_control_tick(now):
  for model_id, goal in list(buffer.items()):
    if goal is None or goal.expired(now):
      buffer[model_id] = None
      log("ttl_drop", model_id)
      continue
    if mode[model_id] == SHADOW:
      log_shadow_compare(goal, classical_goal(ctx), ctx)
      # NEVER bus.publish
    elif mode[model_id] == ACTIVE:
      bus.publish(goal)   # still subject to GoalArbiter + D1

on_executive_event(ev in {PAUSE, CANCEL, REVISION, HARD_STOP}):
  buffer.clear()
  log("buffer_invalidate", ev)
```

### 6.4 Executive goal selection

```text
function select_executive_goal(ctx, now) -> SE2Goal | HOLD:
  classical = admit_existing_classical_goal(ctx)
  # returns None unless same authorized task/revision, independently grounded
  # goal, fresh evidence/frame/pose/metric geometry, and healthy controller
  active = [g for g in bus.poll(now_s=now, context=ctx) if mode[g.source] == ACTIVE]
  # SHADOW goals must not appear in active
  winner = GoalArbiter.resolve(goals=[classical] + active, now_s=now)
  if winner is None:
    return HOLD("no_viable_goal")
  return winner
```

Fallback matrix:

| Condition | Product behavior |
| --- | --- |
| Model OFF / process dead | M11-admitted existing classical goal, otherwise HOLD |
| Deadline miss / OOM / malformed IPC | Log `proposer_unavailable`; M11 admission or HOLD |
| Validate Reject | Log reason; M11 admission or HOLD |
| TTL expiry mid-mission | Drop slot; M11 admission or HOLD; no coast |
| ACTIVE but GoalArbiter lethal veto | M11 admission or HOLD; final veto repeats |
| Hard geometry stop (D1) | Exact zero — **overrides** any winner |
| Missing LiDAR on product (P0-B) | HOLD — do not query MiniCPM to open-loop |

### 6.5 ShadowCompareV1

```text
ShadowCompareV1 {
  episode_id, t_s, model_id, mode,
  classical_se2, proposal_se2 | null,
  ingress_verdict, ingress_reason,
  would_have_won_arbiter: bool,   # counterfactual under ACTIVE priority rules
  geometric_clearance_delta_m,
  identity_gate_ok: bool,
  latency_ms, vram_mb | null,
  task_revision, observation_ids
}
```

**Promotion rule:** necessary not sufficient — see §14. Shadow-only `would_have_won` is diagnostic, not a promotion sample.

### 6.6 Python-shaped modules (implementable)

```python
# parcel_robot/proposers/schema.py  (illustrative — land under contracts/v1.py)

from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Literal, Mapping, Sequence

ModelId = Literal["minicpm_robottrack", "citywalker"]
TaskMode = Literal[
    "OWNER_FOLLOW", "TARGET_TRACK", "POINT_GOAL",
    "URBAN_APPROACH", "DETOUR", "OTHER",
]
ProposerMode = Literal["off", "shadow", "active"]

@dataclass(frozen=True, slots=True)
class WaypointSE2:
    x: float
    y: float
    yaw_rad: float | None

@dataclass(frozen=True, slots=True)
class NavProposalV1:
    model_id: str
    model_hash: str
    service_instance_id: str
    task_id: str
    task_revision: int
    plan_step_id: str
    observation_ids: tuple[str, ...]
    captured_at: float
    produced_at: float
    expires_at: float
    frame: str
    relative_se2_waypoints: tuple[WaypointSE2, ...]
    time_from_start: tuple[float, ...] | None
    waypoint_covariance: tuple[float, ...] | None
    arrival_probability: float | None
    confidence: float | Literal["unknown"]
    task_mode: TaskMode
    footprint_profile_id: str
    kinematic_profile_id: str
    input_abi_hash: str
    calibration_abi_hash: str
    evidence_handles: tuple[str, ...]
    diagnostics: Mapping[str, Any]

    def __post_init__(self) -> None:
        if self.expires_at <= self.produced_at:
            raise ValueError("expires_at must be after produced_at")
        if not self.relative_se2_waypoints:
            raise ValueError("waypoints required")
        if len(self.relative_se2_waypoints) > 16:
            raise ValueError("at most 16 waypoints")


@dataclass(frozen=True, slots=True)
class NavProposeErrorV1:
    request_id: str
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class IngressContext:
    active_task_id: str
    active_revision: int
    obs_abi_hash: str
    planner_frame: str
    max_proposal_horizon_m: float
    clock_skew_s: float
    pose_health: str
    owner_posterior_state: str
    target_visible_m_of_n: bool
    crossing_authorization: BoundCrossingAuthorizationV1 | None
    # validator checks authorized speaker/channel, same task/revision,
    # unique event ID, curb-stop state, expiry/TTL, and replay protection;
    # transcript/phrase text is never sufficient
    occupancy: Any
    keepout: Any
    kinematic_profile_id: str
    profile_requires_healthy_pose: bool
    priorities: Mapping[str, int]

    def priority_for(self, model_id: str) -> int:
        return int(self.priorities.get(model_id, 0))
```

```python
# parcel_robot/proposers/ingress.py

from __future__ import annotations
import math
from dataclasses import dataclass
from typing import Literal

from parcel_robot.instructnav.arbiter import SE2Goal
from parcel_robot.proposers.schema import IngressContext, NavProposalV1, WaypointSE2

VerdictKind = Literal["accept", "reject"]

@dataclass(frozen=True, slots=True)
class IngressVerdict:
    kind: VerdictKind
    reason: str = ""
    goal: SE2Goal | None = None


def _finite(wps: tuple[WaypointSE2, ...]) -> bool:
    for w in wps:
        if not math.isfinite(w.x) or not math.isfinite(w.y):
            return False
        if w.yaw_rad is not None and not math.isfinite(w.yaw_rad):
            return False
    return True


def clamp_horizon(
    wps: tuple[WaypointSE2, ...], max_range_m: float
) -> tuple[WaypointSE2, ...]:
    out: list[WaypointSE2] = []
    travel = 0.0
    prev = (0.0, 0.0)
    for w in wps:
        step = math.hypot(w.x - prev[0], w.y - prev[1])
        if travel + step > max_range_m:
            break
        out.append(w)
        travel += step
        prev = (w.x, w.y)
    return tuple(out)


def validate(
    p: NavProposalV1,
    ctx: IngressContext,
    *,
    now: float,
    pinned_hashes: dict[str, str],
    lethal_fn,
    transform_ok_fn,
    road_keepout_fn,
) -> IngressVerdict:
    if not _finite(p.relative_se2_waypoints):
        return IngressVerdict("reject", "nonfinite")
    if pinned_hashes.get(p.model_id) != p.model_hash:
        return IngressVerdict("reject", "hash_mismatch")
    if p.input_abi_hash != ctx.obs_abi_hash:
        return IngressVerdict("reject", "abi_mismatch")
    if p.task_id != ctx.active_task_id:
        return IngressVerdict("reject", "task_mismatch")
    if p.task_revision != ctx.active_revision:
        return IngressVerdict("reject", "stale_revision")
    if now > p.expires_at:
        return IngressVerdict("reject", "ttl_expired")
    if p.produced_at > now + ctx.clock_skew_s:
        return IngressVerdict("reject", "clock_skew")
    if not transform_ok_fn(p.frame, ctx.planner_frame, p.captured_at):
        return IngressVerdict("reject", "transform")
    if ctx.profile_requires_healthy_pose and ctx.pose_health in {"DEGRADED", "LOST"}:
        return IngressVerdict("reject", "pose_unhealthy")

    wps = clamp_horizon(p.relative_se2_waypoints, ctx.max_proposal_horizon_m)
    if not wps:
        return IngressVerdict("reject", "empty_after_clamp")

    if p.model_id == "minicpm_robottrack":
        if ctx.owner_posterior_state != "ADMITTED":
            return IngressVerdict("reject", "identity_gate")
        if not ctx.target_visible_m_of_n:
            return IngressVerdict("reject", "no_target")
        if p.task_mode not in {"OWNER_FOLLOW", "TARGET_TRACK"}:
            return IngressVerdict("reject", "role_mismatch")
    if p.model_id == "citywalker":
        if p.task_mode not in {"POINT_GOAL", "URBAN_APPROACH", "DETOUR"}:
            return IngressVerdict("reject", "role_mismatch")
        if (any(road_keepout_fn(w.x, w.y) for w in wps)
                and not valid_bound_crossing_authorization(ctx, p)):
            return IngressVerdict("reject", "road_keepout")

    if any(lethal_fn(w.x, w.y) for w in wps):
        return IngressVerdict("reject", "lethal_mask")

    conf = 0.0 if p.confidence == "unknown" else float(p.confidence)
    tip = wps[-1]
    yaw = 0.0 if tip.yaw_rad is None else float(tip.yaw_rad)
    if tip.yaw_rad is None and len(wps) >= 2:
        yaw = math.atan2(wps[-1].y - wps[-2].y, wps[-1].x - wps[-2].x)
    goal = SE2Goal(
        source=p.model_id,
        pose=(tip.x, tip.y, yaw),
        waypoints=tuple((w.x, w.y) for w in wps),
        frame=ctx.planner_frame,
        confidence=conf,
        ttl_s=max(1e-3, p.expires_at - now),
        plan_step_id=p.plan_step_id,
        issued_s=now,
        priority=ctx.priority_for(p.model_id),
    )
    return IngressVerdict("accept", goal=goal)
```

```python
# parcel_robot/proposers/buffer.py

from __future__ import annotations
from dataclasses import dataclass
from typing import Any

from parcel_robot.instructnav.arbiter import ProposerBus, SE2Goal
from parcel_robot.proposers.ingress import IngressVerdict, validate
from parcel_robot.proposers.schema import NavProposalV1, ProposerMode


@dataclass
class ProposalBuffer:
    modes: dict[str, ProposerMode]
    pinned_hashes: dict[str, str]
    bus: ProposerBus
    _latest: dict[str, tuple[float, SE2Goal]]

    def __init__(self, modes, pinned_hashes, bus):
        self.modes = dict(modes)
        self.pinned_hashes = dict(pinned_hashes)
        self.bus = bus
        self._latest = {}

    def invalidate(self, reason: str) -> None:
        self._latest.clear()

    def on_proposal(self, p: NavProposalV1, ctx, *, now: float, **fns) -> IngressVerdict:
        v = validate(p, ctx, now=now, pinned_hashes=self.pinned_hashes, **fns)
        if v.kind != "accept" or v.goal is None:
            return v
        prev = self._latest.get(p.model_id)
        if prev is None or p.produced_at >= prev[0]:
            self._latest[p.model_id] = (p.produced_at, v.goal)
        return v

    def on_tick(self, *, now: float, classical: SE2Goal | None, shadow_log) -> None:
        for model_id, (produced_at, goal) in list(self._latest.items()):
            if goal.expired(now):
                self._latest.pop(model_id, None)
                continue
            mode = self.modes.get(model_id, "off")
            if mode == "shadow":
                shadow_log(model_id, classical, goal)
            elif mode == "active":
                self.bus.publish(goal)
```

```python
# parcel_robot/proposers/client.py  — non-blocking IPC sketch

from __future__ import annotations
import json
import socket
from typing import Any


class NonBlockingProposeClient:
    """Never block the control loop. Deadline miss ≡ unavailable."""

    def __init__(self, path: str, deadline_ms: int) -> None:
        self.path = path
        self.deadline_ms = deadline_ms
        self._sock: socket.socket | None = None
        self._pending_id: str | None = None

    def try_request(self, payload: dict[str, Any]) -> None:
        # fire-and-forget latest-only; drop prior pending
        self._pending_id = str(payload["request_id"])
        # implementation: settimeout(0); send length-prefixed JSON;
        # do not wait for response here

    def try_collect(self) -> dict[str, Any] | None:
        # non-blocking recv; if incomplete, return None
        # if deadline exceeded since request, return error dict DEADLINE
        return None
```

---

## 7. Adapter algorithms (per model)

### 7.1 MiniCPM-RobotTrack → `NavProposalV1`

**Native I/O (author):** language instruction + fused DINOv3/SigLIP visual tokens → **8× `(x,y,yaw)`** future waypoints. Load with `trust_remote_code=True`. ~180 ms e2e author claim on Go2/Orin.

```text
function minicpm_propose(req: NavProposeRequestV1) -> NavProposalV1 | Error:
  if req.task_mode not in {OWNER_FOLLOW, TARGET_TRACK}:
      return Error(UNSUPPORTED_MODE)
  # Parcel identity gate BEFORE inference
  if not req.identity_admitted:          # stamped by Parcel, not model
      return Error(IDENTITY_CLOSED)
  if req.observation_snapshot_ref missing RGB evidence:
      return Error(NO_EVIDENCE)

  feats = extract_or_load_visual_tokens(req)   # inside sandbox
  wps8 = model.forward(instruction, feats)     # 8 x (x,y,yaw) relative

  wps = clamp_path_length(wps8, max_m=req.max_horizon_m or 3.0)
  return NavProposalV1(
      model_id="minicpm_robottrack",
      model_hash=PIN,
      relative_se2_waypoints=wps,
      confidence="unknown",
      arrival_probability=null,
      task_mode=req.task_mode,
      expires_at=now + ttl_s,   # 0.8s default
      observation_ids=...,
      ...
  )
  # NEVER emit Sport velocity; NEVER write presence=true
```

**Why adapter will work**

- **Precedent:** Official Go2 dry-run path already separates waypoint generation from MOVE enablement; Qwen-shaped 8× SE2 matches Parcel ABI north star (N2).
- **Parcel binding:** `SE2Goal` accepts pose+waypoints (`arbiter.py:14–27`); follow today uses proportional twist (`follow.py:596–658`) — MiniCPM SHADOW compares against that **and** against future formation→grid, but ACTIVE waits for formation→grid (audit S1.2 / thesis P1.1).
- **Falsifier:** Adapter that enables MOVE flags from MiniCPM go2_runtime; or inference without ADMITTED.

### 7.2 CityWalker → `NavProposalV1`

**Native I/O (HF port):** images `(B,5,3,H,W)`, coords `(B,6,2)` → waypoints `(B,5,2)`, arrive_logits `(B,1)`. No yaw.

```text
function citywalker_propose(req: NavProposeRequestV1) -> NavProposalV1 | Error:
  if req.task_mode not in {POINT_GOAL, URBAN_APPROACH, DETOUR}:
      return Error(UNSUPPORTED_MODE)
  if req.goal_hint is None and req.task_mode == POINT_GOAL:
      return Error(NO_EVIDENCE)

  images, coords = pack_history(req)  # 5 RGB + 5 past + target relative
  xy5, arrive_logit = model.forward(images, coords)
  xy_m = xy5 * step_scale
  se2 = derive_yaw_from_segments(xy_m)  # yaw from atan2; or yaw=null

  return NavProposalV1(
      model_id="citywalker",
      relative_se2_waypoints=se2,
      arrival_probability=uncalibrated(arrive_logit),
      confidence="unknown",
      expires_at=now + ttl_s,  # 1.5s default (matches citywalker.py:140)
      ...
  )
  # NEVER set road-entry / crossing clearance bits
```

**In-tree extension path:** keep `CityWalkerInferenceAdapter` for offline cached A/B (`citywalker.py:146–304`); live path becomes IPC service — runtime continues to call `as_bus_proposer` only after ingress, never imports torch (`citywalker.py:306–314` pattern preserved).

**Why adapter will work**

- **Precedent:** HF port documents exact tensors; CVPR CityWalker shows short-horizon relative pose IL mitigates VO drift; Parcel already emits SE2Goal from cached waypoints with step bound (`citywalker.py:259–293`).
- **Parcel binding:** `ttl_s: 1.5`, `priority: 1`, `gate_enabled=False` defaults (`citywalker.py:134–140`); crossing remains authority (`maps/crossing.py`).
- **Falsifier:** Live torch import into `RobotRuntime`; or treating arrive_logit as terminal witness for NavigateTo success (success stays GoalRegion / scoring — `instructnav/scoring.py` pattern per thesis).

### 7.3 Acquisition order (binding)

| Rank | Artifact | Action | Shadow role | Blockers |
| ---: | --- | --- | --- | --- |
| 1 | MiniCPM-RobotTrack | First new download | Owner-follow / target-track | DINOv3/SigLIP/TRT notices; author nonzero CR |
| 2 | CityWalker | Review license scope on byte-verified official v1.0 asset or re-pin HF | Urban XY prior | Original asset `NOASSERTION`; custom loader; Go1≠Go2; no yaw/language |
| 3 | CE-Nav | Review, then local-policy screen | Local detour | MIT repo/checkpoints; transitive dependencies, legacy Isaac/Orbit assets, checkpoint scope, incomplete training release |
| 4+ | X-NavDP / InternVLA / NaVILA | Hold / research | Out of D2 default | Artifact-specific terms — see RL2 |

**Do not acquire for training:** InternData dumps, Isaac packs, “retrain MiniCPM from scratch.”

---

## 8. Sandbox compose (mandatory)

```yaml
# deploy/compose.proposers.yaml (sketch)
services:
  minicpm_robottrack:
    image: parcel/minicpm-robottrack@sha256:...
    network_mode: none
    read_only: true
    tmpfs: ["/tmp"]
    environment:
      TRANSFORMERS_OFFLINE: "1"
      HF_HUB_OFFLINE: "1"
    volumes:
      - type: bind
        source: /var/parcel/pins/minicpm
        target: /models
        read_only: true
      - type: bind
        source: /var/parcel/shm/obs
        target: /obs
        read_only: true
    # NO /dev/unitree, NO Sport sockets, NO docker.sock
    deploy:
      resources:
        limits:
          memory: 8G
        reservations:
          devices:
            - capabilities: [gpu]
  citywalker:
    image: parcel/citywalker@sha256:...
    network_mode: none
    read_only: true
    # same denylist
```

**Architectural CI tests:**

1. `grep -R "unitree\|SportClient\|Move\|StopMove" deploy/docker/Dockerfile.*proposer*` → empty for command APIs.  
2. Import linter: `parcel_robot.runtime` must not import proposer torch stacks.  
3. Container config assert: `network_mode == none` and no Sport device mounts.

---

## 9. Navigation integration

### 9.1 Control-loop ownership

```text
50–100 Hz  geometry monitor + watchdog          (D1)
20–50 Hz   grid_v1 / local tracking             (classical writer)
10–20 Hz   formation goal sampler               (social; D3 sibling)
~2–5 Hz    MiniCPM propose requests             (SHADOW/ACTIVE)
~1–2 Hz    CityWalker propose requests          (SHADOW/ACTIVE)
event      TaskExecutive revisions              (invalidate buffers)
```

Under thermal/VRAM pressure, drop open-vocab and proposers **before** geometry/safety (TARGET_ARCHITECTURE §7).

### 9.2 Who may write velocity

| Writer | Allowed? |
| --- | --- |
| `grid_v1` / formation→grid | Yes (production) |
| Nav2 sidecar | Exclusive challenger only (N1) |
| MiniCPM / CityWalker | **No** — proposals only |
| Soft social costs | Rank/pace only |
| Post-shaper monitor | Tighten/zero only |
| Follow proportional (`follow.py`) | Legacy; must not be the ACTIVE baseline |

### 9.3 Mission-path wiring

1. `TaskExecutive` admits NavigateTo / FollowFormation / ApproachOwner.  
2. Classical goal generators publish `SE2Goal` (fix under-poll: D2 requires product-path poll for ACTIVE; SHADOW may use side channel). Pipeline already constructs SE2Goal in places (`navigation/pipeline.py` ~1429, ~2079).  
3. ProposalIngress → SHADOW logs always; ACTIVE publish only when mode+task_mode match.  
4. `GoalArbiter.resolve` → single goal → `grid_v1`.  
5. Shaper → **D1 exact-zero monitor** → ControlManager → Sport.

### 9.4 Interaction with follow / identity (critical)

ACTIVE MiniCPM is **invalid** as an A/B against proportional follow alone (`follow.py:641–658` emits `VelocityCommand` directly). That measures “model tip + grid” vs “bypass planner,” confounding safety. D2 requires formation-goal→common planner (D1/D3) before ACTIVE MiniCPM promotion.

SHADOW may still log against both baselines for diagnostics, labeled separately.

### 9.5 Interaction with crossing / city

CityWalker tips into a road keepout without an authenticated, authorized
owner/control-channel decision bound to the current task/revision, event ID,
curb-stop state, and TTL → Reject (`maps/crossing.py:213–227`). A recognized
transcript or phrase match alone cannot mint this authority; the independent
metric veto remains binding.

---

## 10. Worked scenario — hardest product case

**Case:** Owner says “stay with me.” Distractor in red shirt crosses. Owner briefly occluded behind a pillar. MiniCPM in SHADOW (then hypothetical ACTIVE) may invent forward motion. CityWalker not in role.

### 10.1 Initial state (t=0)

| Variable | Value |
| --- | --- |
| `task_id` | `follow-7f3a` |
| `task_revision` | 3 |
| `task_mode` | `OWNER_FOLLOW` |
| `owner_posterior.state` | `ADMITTED` (enrolled gallery match, margin OK) |
| `target_visible_m_of_n` | True (3/3) |
| `proposers.minicpm.mode` | `shadow` |
| `proposers.citywalker.mode` | `off` |
| `pose.health` | `HEALTHY` |
| LiDAR | fresh calibrated scan |
| Classical goal | formation SE2 behind owner, priority 20 |
| MiniCPM buffer | empty |

### 10.2 Tick narrative

**t=0.00–0.40 — healthy follow, SHADOW compare**

1. ObservationSnapshot `obs-100` published; abi_hash `H`.  
2. Classical formation sampler emits `SE2Goal(source=formation, priority=20, ttl=2.0)`.  
3. MiniCPM service returns proposal P1: 8 waypoints gently left-behind owner; `expires_at=t+0.8`; `observation_ids=[obs-100]`; `confidence=unknown`.  
4. Ingress Accept → buffer set; mode SHADOW → `ShadowCompareV1` logged; `would_have_won_arbiter=false` (priority 10 < 20).  
5. GoalArbiter selects formation → `grid_v1` paths → shaper → D1 monitor clear → Sport.

**t=0.45 — distractor enters frame**

1. Tracker sees person B; identity posterior still ADMITTED on owner A (margin).  
2. MiniCPM raw behavior (author DT risk) might tip toward distractor — but Parcel still feeds **admitted owner metric pose** as goal_hint, not “nearest blob.”  
3. If model tip veers toward distractor into lethal/occupied cell → ingress
   `lethal_mask` Reject → the already-authorized formation goal continues
   only after M11 freshness/health admission; otherwise HOLD.  
4. Shadow log records Reject reason; identity_gate_ok=true.

**t=0.90 — owner occlusion starts**

1. `target_visible_m_of_n` flips False (0/3).  
2. Next MiniCPM **request is not sent** (identity/visibility pre-gate). In-flight P_old still in buffer until TTL.  
3. At `expires_at`, buffer drops (`ttl_drop`). No coasting into pillar shadow.  
4. Classical formation decelerates / HOLD per D1 owner-lost policy (TARGET_ARCHITECTURE §4) — D2 does not invent search from MiniCPM.

**t=1.10 — MiniCPM would invent forward motion (author warning)**

1. Suppose a buggy build skipped visibility pre-gate and model emits forward 2 m tip with no person.  
2. Ingress must still Reject `no_target`.  
3. **Falsifier check:** if Accept occurs, kill criterion — gate bug, revert to OFF.

**t=1.40 — owner reappears; revision bump**

1. Executive issues clarification-free continue; `task_revision=4` (or pause/resume atomic under P0-C).  
2. Buffer invalidate on revision.  
3. Stale proposal with revision=3 → Reject `stale_revision`.  
4. Fresh ADMITTED + visible → new SHADOW proposals resume.

**t=2.00 — injected model kill**

1. MiniCPM container OOM killed.  
2. Client deadline → `proposer_unavailable`.  
3. Classical path uninterrupted.  
4. Acceptance: zero HAL anomaly attributable to missing proposer.

### 10.3 ACTIVE hypothetical (only after gates)

If mode were ACTIVE with priority 10 and classical 20, behavior identical for winner selection unless promotion raised MiniCPM for OWNER_FOLLOW after L2–L4. Even then:

- Lethal mask + D1 exact zero still override.  
- Identity LOST still drops buffer.  
- Missing LiDAR → HOLD (P0-B), not model open-loop.

### 10.4 Failure branches summary

| Branch | Expected |
| --- | --- |
| Distractor attraction | Lethal/identity keeps classical; shadow Reject or harmless tip |
| Occlusion + forward invent | `no_target` Reject; TTL drop; no coast |
| Stale revision after resume | Reject; require fresh |
| Model crash | Classical continuity |
| LiDAR loss | HOLD; do not ask model |
| Road tip (if CityWalker wrongly enabled) | `road_keepout` Reject |

---

## 11. Safety / correctness argument

### 11.1 Invariants

| ID | Invariant |
| --- | --- |
| I1 | No model output reaches ControlManager/Sport without GoalArbiter→`grid_v1`→D1 monitor |
| I2 | Reject/TTL/OOM/deadline ⇒ HOLD unless M11 re-admits the same existing classical goal; never open-loop StubNavigator on product |
| I3 | MiniCPM never sets identity/presence truth |
| I4 | CityWalker never authorizes road entry |
| I5 | Hard geometry envelopes are monotone non-increasing through the stack |
| I6 | SHADOW cannot change motion |
| I7 | Buffers clear on pause/cancel/revision/hard stop |
| I8 | Unknown confidence cannot beat classical on confidence key |

### 11.2 What could falsify the design

1. Measured residual HAL velocity on hard stop after D1 claim (P0-A red).  
2. Product profile still using `scan_missing_fallback` (`grid_navigator.py:353–354`) with ACTIVE on.  
3. Import/mount path from proposers to Sport.  
4. SHADOW compare writer accidentally calling `bus.publish`.  
5. Identity silent swap in frozen distractor suite.  
6. IPC blocking causing p99 control deadline miss.  
7. License hash drift / NOASSERTION unresolved at ACTIVE.

### 11.3 Why literature/practice supports the mechanism set

- Mid-level waypoints under classical control: InternVLA dual-system, NaVILA mid-level, Qwen-RobotNav interface, InstructNav propose/dispose (N2).  
- Fail-closed freshness: Nav2 collision monitor source_timeout (N1).  
- Exact-zero after smoother: Nav2 monitor placement lesson + Parcel N5 defect analysis.  
- Shadow before authority: MiniCPM dry-run; RL2 reuse doctrine.  
- Advisory vs metric city layers: N8; Parcel must replace phrase-only crossing
  with the authenticated task/revision-bound authorization contract above.

### 11.4 Residual risk (accepted, not claimed closed)

- Author MiniCPM collisions prove model tips can be wrong — mitigated by veto, not by trusting SR.  
- DiffDrive-shaped waypoints vs Sport tracking (**UNVERIFIED** U-Sport-track).  
- Orin co-residency numbers not measured.  
- Software E-stop ≠ hardware E-stop.

---

## 12. File:line citation index (≥20 binding anchors)

| # | Claim | Anchor |
| ---: | --- | --- |
| 1 | SE2Goal TTL + pose/waypoints contract | `src/parcel_robot/instructnav/arbiter.py:12–36` |
| 2 | ProposerBus latest-only publish/poll | `src/parcel_robot/instructnav/arbiter.py:52–101` |
| 3 | GoalArbiter expires + lethal veto + priority | `src/parcel_robot/instructnav/arbiter.py:110–158` |
| 4 | CityWalker gate_enabled default False | `src/parcel_robot/route_memory/citywalker.py:130–140` |
| 5 | CityWalker skip when gate disabled | `src/parcel_robot/route_memory/citywalker.py:214–215` |
| 6 | CityWalker max step fail-closed | `src/parcel_robot/route_memory/citywalker.py:259–274` |
| 7 | CityWalker emits SE2Goal not velocity | `src/parcel_robot/route_memory/citywalker.py:284–303` |
| 8 | Freshness fail-closed helpers | `src/parcel_robot/contracts/freshness.py:1–6`, `82–111` |
| 9 | Default track TTL 500 ms | `src/parcel_robot/contracts/freshness.py:15` |
| 10 | Elementwise-min authority rule | `src/parcel_robot/authority.py:62–68` |
| 11 | SafetyEnvelope stop_distance form | `src/parcel_robot/authority.py:478–490`, `598–615` |
| 12 | Active model grid_v1 | `configs/navigation/default.yaml:8` |
| 13 | safe_valley_micro_advance default False | `src/parcel_robot/navigation/grid_navigator.py:99` |
| 14 | Missing scan → StubNavigator open-loop | `src/parcel_robot/navigation/grid_navigator.py:335–357` |
| 15 | Emergency shaper residual slew | `src/parcel_robot/navigation/velocity_shaping.py:102–105` |
| 16 | Follow proportional vx command | `src/parcel_robot/navigation/follow.py:641–658` |
| 17 | Crossing zero autonomous road entry | `src/parcel_robot/maps/crossing.py:4–5`, `199–227` |
| 18 | Crossing authorization TTL | `src/parcel_robot/maps/crossing.py:58`, `158` |
| 19 | Latched emergency_stop path | `src/parcel_robot/runtime.py:2040–2050` |
| 20 | Pipeline SE2Goal construction sites | `src/parcel_robot/navigation/pipeline.py:1425–1433`, `2074–2083` |
| 21 | DIRECT_FOLLOW success states | `src/parcel_robot/brain/runtime_adapter.py:35` |
| 22 | Executive resume_task exists | `src/parcel_robot/brain/executive.py:645` |
| 23 | CityWalker YAML checkpoint path | `configs/navigation/models/citywalker.yaml:1–8` |
| 24 | Affect proposal expires_at pattern | `src/parcel_robot/core/activities.py:42`, `120` |

---

## 13. Evaluation ladder

Evidence classes from `EVALUATION_AND_ROADMAP.md` binding. Never promote `derived_rescore` or author paper SR into product claims.

```text
L0  Contract smoke
    schema / TTL / reject fixtures / sandbox boot / no-Sport mount check

L1  Offline replay (bags / frozen RGB)
    MiniCPM: owner/distractor/occlusion → proposal quality vs identity gate
    CityWalker: urban point-goal bags → XY prior vs grid classical

L2  SHADOW paired product_headless
    identical episodes; classical authority retained
    metrics: ShadowCompareV1; safety veto count; p99 latency; identity swaps = 0

L3  Role-matched suites
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
4. Paired product metric improvement **or** explicit board “no-harm prior” with latency headroom.  
5. License pin still valid (Hub YAML + SPDX + SBOM).  
6. Co-residency under declared VRAM cap.  
7. Deterministic HOLD, or M11-admitted continuation of an existing classical goal, on injected model kill.  
8. Formation→grid exists before ACTIVE MiniCPM (not proportional baseline).

### Kill criteria (revert SHADOW/OFF)

- Any S0 residual motion attributable to proposal path.  
- Identity silent swap.  
- p99 control-loop deadline miss from IPC blocking.  
- License metadata change / hash drift.  
- Forward-when-invisible Accept while visibility gate should be closed.  
- Road keepout Accept from CityWalker without a task/revision-bound,
  authenticated and authorized crossing decision.

### What does **not** promote

- MiniCPM EVT STT SR/TR/CR author numbers.  
- CityWalker Go1 77.3% author real-world.  
- NAV_INSTRUCT derived 0.12/0.16 or frozen 1/25 alone as model proof.  
- Shadow `would_have_won` counterfactuals alone.

---

## 14. Migration plan

### M0 — ABI + harness (before weight download)

| Work | Exit |
| --- | --- |
| Add `NavProposalV1` to `contracts/v1.py` + freshness helpers | Golden reject tests in CI |
| ProposalIngress + ShadowCompare logger | Unit tests, no GPU |
| Synthetic 8-waypoint fixture | L0 green |
| Sport socket denylist in sandbox compose | Review checklist |
| CI guard: mode!=off requires P0 pins | Red build if violated |

### M1 — MiniCPM SHADOW

| Work | Exit |
| --- | --- |
| Pinned inference image; hash lockfile | Offline boot |
| IPC client behind `proposers.minicpm.mode=shadow` | Default OFF in product YAML |
| Owner-follow frozen bag suite | L1–L2 ledger |
| Identity gate tests | Reject without ADMITTED |

### M2 — CityWalker SHADOW

| Work | Exit |
| --- | --- |
| Provenance decision recorded | Legal + hash |
| Extend adapter → IPC service | Fail-closed skip preserved |
| Urban point-goal shadow suite | L1–L2; no role bleed into follow |

### M3 — Mission-path ProposerBus poll

| Work | Exit |
| --- | --- |
| Wire GoalArbiter poll on product NavigateTo/FollowFormation | Classical still wins by priority |
| ACTIVE flag per model default false | Config + ledger gate reference |

### M4 — Gated ACTIVE + Orin profile

| Work | Exit |
| --- | --- |
| Promotion review §13 | Board signoff artifact |
| Orin NX co-residency measurement | Ledger numbers; drop proposers under pressure |

### M5 — Out of D2 scope

CE-Nav after checkpoint/dependency/legacy-Isaac review; X-NavDP after its
distinct legal review; InternVLA S2 research desktop; narrow ranker training
only after open baselines plateau (RL1/RL2).

---

## 15. Risks and mitigations

| ID | Risk | Severity | Mitigation |
| --- | --- | --- | --- |
| R1 | Shadows before D1 exact-zero / LiDAR HOLD | S0 confound | Hard prerequisite; CI rejects mode!=off if P0 red |
| R2 | `trust_remote_code` supply chain | High | Vendor review; no net; hash pin; SBOM |
| R3 | MiniCPM invents forward motion w/o person | High | Identity + visibility gate; author warning as design input |
| R4 | Model → Sport accidental wiring | Critical | Sandbox denylist; import linter; architectural tests |
| R5 | IPC blocks 20–50 Hz control | High | Non-blocking client; deadline; skip tick |
| R6 | CityWalker original-asset license ambiguity | Medium | Byte identity is verified; clear asset scope or legally approve a separate HF pin before ACTIVE |
| R7 | Priority inversion | Medium | Classical ≥20; promotion changes need gate doc |
| R8 | VRAM fight with Gemma / perception | Medium | Drop proposers first under pressure |
| R9 | Wrong suite (R2R vs follow) | Medium | Role-matched episodes only |
| R10 | Shadow wins psychologically | Process | SHADOW cannot flip product defaults |
| R11 | DiffDrive waypoints vs Sport tracking | Medium | Clamp horizon; classical tracks; U-Sport-track |
| R12 | Stale proposal after pause/resume | High | Invalidate on revision/pause; P0-C |
| R13 | Uncalibrated confidence as P | Medium | Mark unknown; never widen masks |
| R14 | ACTIVE vs proportional follow confound | High | Require formation→grid first |
| R15 | CityWalker tip as road clearance | High | Role + road keepout reject |
| R16 | Co-scheduling 8B VLN later on Orin | High | Out of D2 default |

---

## 16. Acceptance test matrix

| ID | Test | Layer | Pass criterion |
| --- | --- | --- | --- |
| T0.1 | Schema golden rejects 1–15 | L0 | All Reject with exact reason codes |
| T0.2 | Sandbox network_mode none | L0 | Compose assert |
| T0.3 | No Sport mount / import | L0 | Grep + import linter clean |
| T0.4 | mode=active without P0 pins | L0 | CI fails |
| T1.1 | MiniCPM bag: ADMITTED visible | L1 | Accept rate logged; confidence unknown |
| T1.2 | MiniCPM bag: identity closed | L1 | 100% Reject identity_gate; **no inference call** |
| T1.3 | MiniCPM bag: occlusion no_target | L1 | Reject; TTL drop; no coast > ttl |
| T1.4 | CityWalker bag: point goal | L1 | XY polyline Accept under masks |
| T1.5 | CityWalker bag: OWNER_FOLLOW mode | L1 | Reject role_mismatch |
| T1.6 | CityWalker tip in road keepout | L1 | Reject road_keepout |
| T2.1 | SHADOW paired headless | L2 | Classical commands identical whether service up/down |
| T2.2 | ShadowCompare written every tick | L2 | Schema valid; observation_ids aligned |
| T2.3 | Inject OOM mid-episode | L2 | Classical continuity; no HAL spike |
| T2.4 | Inject IPC block attempt | L2 | Client skips; p99 control within budget |
| T3.1 | Distractor suite identity swaps | L3 | swaps == 0 |
| T3.2 | Hard-safety veto count | L3 | no regression vs classical-only |
| T4.1 | ACTIVE priority classical wins ties | L4 | formation priority 20 beats model 10 |
| T4.2 | ACTIVE lethal veto | L4 | GoalArbiter drops lethal tip |
| T4.3 | D1 hard stop exact zero | L4 | HAL == (0,0,0) same dispatch |
| T5.1 | HIL dry-run MOVE disabled | L5 | No Sport Move despite ACTIVE tips |
| T6.1 | Supervised physical | L6 | Separate auth packet; not auto from L4 |

---

## 17. UNVERIFIED register

| ID | Claim / question | What would verify |
| --- | --- | --- |
| U-D2-Orin | MiniCPM + CityWalker latency/VRAM on Orin NX with product stack | Pinned image profiling under co-residency |
| U-D2-Desktop | Peak VRAM with Gemma q4 + MiniCPM + perception on Ada 32 GB | Process-level peak measurement |
| U-D2-CW-lic | Original v1.0 asset license scope (`NOASSERTION`) | Asset-specific legal review; byte identity is already verified |
| U-D2-CW-yaw | atan2-derived yaw sufficient for grid tracking | Paired tracking error logs |
| U-D2-TTL | 0.8 / 1.5 s TTL optimal vs Sport lag | Sweep on frozen bags + HIL |
| U-D2-Sport-track | grid tracking of model polylines under Sport | EDU tracking/overshoot (thesis U-Sport-track) |
| U-D2-ident | Parcel ADMITTED posterior quality under EVT-like distractors | Frozen identity suite with camera lane |
| U-D2-cal | Calibration map from arrive_logit / model conf → Parcel P | Holdout calibration set |
| U-D2-poll | Mission-path ProposerBus currently under-polled | Code audit + product-path test after M3 |
| U-D2-follow | Formation→grid closes S1.2 enough for ACTIVE MiniCPM | D1 acceptance + paired follow metrics |
| U-stop | stop_distance_m 0.8 safe at cruise | Instrumented stop tests (thesis U-stop) |
| U-N11 | Commitment residual interacts with CityWalker tips | N11 hard pass with shadows off first |

---

## 18. Shared ABI with D1 / D3

| Surface | Shared? | D2-specific |
| --- | --- | --- |
| Exact-zero post-shaper monitor | Yes (D1 owns) | Consumes only |
| Fail-closed LiDAR/pose | Yes | Consumes only |
| `SE2Goal` / GoalArbiter | Yes | ACTIVE publish path |
| `NavProposalV1` + IPC | Yes (freeze once) | First consumers MiniCPM/CityWalker |
| Formation→grid | D1/D3 | MiniCPM ACTIVE depends on it |
| N11 re-rank / OSM advisory | D3 | CityWalker is prior, not crossing authority |
| Sport ownership | Yes | Absolute no model edge |

---

## 19. Engineer checklist

1. Land `NavProposalV1` + golden rejects (no GPU).  
2. ProposalIngress + ShadowCompare logger + buffer invalidate.  
3. Confirm D1 P0-A/B/C pins green.  
4. MiniCPM sandbox image + hash pin.  
5. SHADOW owner-follow bags → ledger.  
6. CityWalker original-asset license/loader decision + SHADOW urban bags.  
7. Mission-path ProposerBus poll with classical priority.  
8. Formation→grid before any ACTIVE MiniCPM.  
9. Promotion review → optional ACTIVE.  
10. Orin profile before field SHADOW with MOVE enabled.

---

## 20. Bottom line

D2 is the **reuse path**: MiniCPM then CityWalker as sandboxed, TTL-bound SE(2) proposers behind a frozen `NavProposalV1` IPC, classical `grid_v1` execution, and D1 geometry veto. Default **SHADOW**; **ACTIVE** only after role-matched paired gates and formation→grid for follow. Train nothing; grant Sport to no model; never let CityWalker clear a road or MiniCPM decide identity.

---

## Appendix C — Pass 3 gap expansion notes

### C.1 Why v0’s validate sketch was insufficient

v0 omitted: road keepout role interaction, pre-inference identity short-circuit, buffer invalidate events, non-blocking client, CI P0 pin coupling, formation→grid ACTIVE precondition, uncalibrated confidence → 0.0 mapping for arbiter ties, and golden fixtures 11–15. Pass 3 added each with falsifiers.

### C.2 Co-residency drop order (binding under pressure)

```text
1. open-vocabulary / OCR query service
2. CityWalker proposer requests
3. MiniCPM proposer requests
4. slow semantic memory refresh
5. NEVER: geometry safety, D1 monitor, ControlManager watchdog, LiDAR freshness
```

### C.3 Observability fields (minimum)

Every Accept/Reject/ShadowCompare must be queryable by `episode_id`, `task_revision`, `model_id`, `ingress_reason`. Without this, L2 paired analysis is impossible and promotion is theater.

### C.4 Explicit non-actions (repeat for implementers)

- Do not vendor MiniCPM go2_runtime MOVE path into Parcel ControlManager.  
- Do not set `configs/navigation/models/citywalker.yaml` `rl.trainable: true` as a product signal — that YAML is legacy research metadata (`citywalker.yaml:8–14`) and is **not** a D2 training authorization.  
- Do not treat `proposal_ttl_s: 20` affect TTL (`runtime_assets/configs/robot.yaml` / `core/activities.py`) as navigation proposer TTL — different subsystem; nav proposers use ≤2 s.  
- Do not cite NAV_INSTRUCT 1/25 as proof MiniCPM/CityWalker help until L2–L3 paired shadows exist.

### C.5 Pseudocode index

| Algorithm | Section |
| --- | --- |
| validate | §6.2, §6.6 |
| buffer / tick / invalidate | §6.3, §6.6 |
| select_executive_goal | §6.4 |
| minicpm_propose | §7.1 |
| citywalker_propose | §7.2 |
| NonBlockingProposeClient | §6.6 |
| ShadowCompare | §6.5 |
| Worked scenario | §10 |

### C.6 Relationship to RL1/RL2 training freeze

RL2: allocate zero custom RL/VLA GPU-hours now. D2 is how that reuse is *implemented*. A later bounded trajectory ranker (RL1 conditional) must consume the **same** `NavProposalV1` ingress — D2 freezes the ABI so future learners cannot bypass masks.

### C.7 Service health machine

```text
OFF → STARTING → READY → DEGRADED → DEAD → STARTING
         │          │         │
         └─ timeout ┴─ OOM ───┴─ supervisor restart
READY: accepting requests within deadline
DEGRADED: intermittent deadline miss; Parcel treats as skip tick
DEAD: no socket; mode behaves as OFF for selection; alert
```

SHADOW/ACTIVE config bits do not auto-flip on DEAD; operator/supervisor only.

### C.8 Request scheduling

```text
function maybe_request(model_id, now):
  if mode[model_id] == OFF: return
  if service_state[model_id] not in {READY, DEGRADED}: return
  if now - last_request[model_id] < 1/request_hz: return
  if identity/role preconditions fail: return   # MiniCPM visibility etc.
  if outstanding_request[model_id] and not timed_out: return  # latest-only
  send NavProposeRequestV1 with deadline_at = now + deadline_ms
```

### C.9 Transform / frame discipline

Proposals in `base_link` at `captured_at` are preferred for short-horizon tips. Ingress transforms to planner frame using **recorded** transform history at `captured_at`, not “latest TF” (avoids time-travel). Missing transform → Reject(`transform`) — same spirit as pose health fail-closed (thesis P0.3; TARGET_ARCHITECTURE §2).

### C.10 Occupancy lethal function

```text
function any_waypoint_lethal(wps, occupancy, keepout):
  for (x,y) in wps:
    if keepout.contains(x,y): return true
    if occupancy.lethal_or_unknown_as_lethal(x,y): return true  # product: unknown ≠ free
  return false
```

Product profiles must treat unknown cells as non-free for model tips (stricter than some classical soft costs). Soft social costs from D3 must not appear here.

### C.11 Metric definitions for ShadowCompare

- `geometric_clearance_delta_m`: min clearance along proposal polyline minus min clearance along classical tip segment, in meters; positive ⇒ proposal has more clearance.  
- `would_have_won_arbiter`: run GoalArbiter on `[classical, proposal_as_if_active]` with ACTIVE priorities; boolean.  
- Neither metric alone promotes.

### C.12 Logging redaction

Do not log raw owner gallery embeddings in ShadowCompare. Log identity state enum + margin bucket only.

### C.13 Versioning

`NavProposalV1` is v1. Breaking changes require `NavProposalV2` and dual-run in SHADOW. Services advertise supported versions; Parcel rejects unknown major.

### C.14 Clock domain note

Prefer monotonic stamps for TTL expiry in-process (`contracts/freshness.py` pattern). Wire protocol may carry float seconds but ingress should convert to monotonic using receive time + declared TTL duration when clocks disagree — fail closed on skew beyond budget (`clock_skew` Reject).

### C.15 Concrete reject reason taxonomy (stable strings)

```text
schema | nonfinite | hash_mismatch | abi_mismatch | task_mismatch |
stale_revision | stale_observation | pose_unhealthy | ttl_expired |
clock_skew | transform | empty_after_clamp | identity_gate | no_target |
role_mismatch | road_keepout | lethal_mask | kinematic |
proposer_unavailable | deadline | oom | internal
```

CI golden tests pin these strings.

### C.16 MiniCPM acquisition checklist (expanded)

1. Snapshot `openbmb/MiniCPM-RobotTrack`; hash `model.safetensors*` (+ shards).  
2. Vendor `modeling_robottrack.py` / `modeling_minicpm.py` / configs; review; freeze.  
3. Clear DINOv3 and SigLIP terms for any evaluation/live vision path; review
   TensorRT separately only for the TRT deployment backend; write
   `THIRD_PARTY_NOTICES`.  
4. Build image with `TRANSFORMERS_OFFLINE=1`; deny net.  
5. Offline feature→waypoint contract tests (synthetic tokens) before robot mount.  
6. Go2 EDU dry-run upstream optional for vendor parity; Parcel MOVE stays disabled until SHADOW gates pass.  
7. Record author EVT CR as **risk literature**, not baseline.

### C.17 CityWalker acquisition checklist (expanded)

1. Record official v1.0/local identity: 1,752,028,242 bytes, SHA-256
   `a42326778e5e318c6222575dc5e02f1794d9a60cce4dc8f8a2ee5df7dc6d1c29`.  
2. Resolve original asset license scope (`NOASSERTION` means no asset-specific
   notice/embedded SPDX); do not infer the HF conversion's Apache label.  
3. Vendor HF remote modeling code; sandbox.  
4. Keep `CityWalkerInferenceAdapter` cached path for CI without GPU.  
5. Profile desktop latency; Orin later (U-D2-Orin).  
6. Never enable `rl.trainable` from model YAML as product training auth.

### C.18 Interaction with NAV_INSTRUCT honesty

Frozen NAV_INSTRUCT SR 1/25 = 0.04 is substrate-limited (thesis). D2 shadows may help urban priors **after** P0/P1, but claiming CityWalker “fixes NAV_INSTRUCT” without L2–L3 paired product_path eval is forbidden. U31 re-freeze rules still apply before capability headlines.

### C.19 Interaction with walk-with-me / duplex evals

MiniCPM SHADOW suites should reuse walk-with-me style owner-follow episodes where they exist (`evals/walk_with_me/`) as role-matched L3 — still SHADOW; still not Sport authority.

### C.20 Final adversarial reminders (Pass 2 leftovers)

- If someone proposes “temporary in-process torch for speed,” reject: supply chain + GIL + VRAM in control process.  
- If someone proposes “use MiniCPM presence to set owner lost,” reject: I3.  
- If someone proposes “CityWalker arrive_logit ends NavigateTo,” reject: GoalRegion witnesses own success.  
- If someone proposes “ACTIVE default in demo YAML,” reject: G5/R10.

---

## Appendix D — End-to-end pseudocode: one control cycle

```text
function control_cycle(runtime, now):
  # 50–100 Hz safety first
  if d1_monitor.requires_hard_zero(runtime.sensors, runtime.last_shaped):
      runtime.hal.set_command(0, 0, 0)
      runtime.shaper.reset()
      proposal_buffer.invalidate("hard_stop")
      return

  if product_profile and not lidar_pose_fresh(runtime):
      runtime.hal.set_command(0, 0, 0)  # P0-B HOLD
      return

  # Collect nonblocking proposer responses
  for model_id in active_services:
      msg = clients[model_id].try_collect()
      if msg is Error: log(unavailable); continue
      if msg is Proposal:
          proposal_buffer.on_proposal(msg, ctx(runtime), now=now, ...)

  # Maybe schedule new requests (low rate)
  maybe_request("minicpm_robottrack", now)
  maybe_request("citywalker", now)

  proposal_buffer.on_tick(now=now, classical=None, shadow_log=log_shadow)

  classical = admit_existing_classical_goal(runtime)  # M11 or None
  winner = select_executive_goal(runtime, now)  # classical + ACTIVE only

  if winner is HOLD:
      cmd = zero_or_stop_policy(runtime)
  else:
      cmd = grid_v1.act(runtime.observation, mission_from(winner))

  smoothed = smoother.step(cmd)
  gated = collision_ttc_gate(smoothed, runtime)  # cannot raise stop
  shaped = shaper.step(gated, emergency=is_hard_stop(gated))
  shaped = d1_monitor.enforce(shaped)  # may force exact zero; never widen
  runtime.control_manager.set_target(shaped)
```

This cycle makes the hard cut explicit: proposers only affect `winner` through buffer/arbiter; D1 monitor is last.

---

## Appendix E — Document control

| Field | Value |
| --- | --- |
| Deep design id | DEEP_D2_SHADOW_PROPOSERS |
| Supersedes for implementation | v0 DESIGN_D2 (archive only) |
| Passes completed | 0 inventory, 1 draft, 2 adversarial, 3 gap expansion |
| Min lines target | 1200 |
| Min cites target | 20 (index §12 has 24) |
| Next sibling | DEEP_D1 / DEEP_D3 / DEEP_COMPARISON after all three land |

**End of DEEP_D2.**
