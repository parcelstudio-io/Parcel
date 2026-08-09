# N4 — Perception and localization (Phase-1 Go2)

**Workstream:** Opus research matrix N4  
**Date:** 2026-08-07  
**Scope:** LiDAR–inertial odometry choice, sensor fusion, open-vocabulary
perception, owner re-identification, and the real-sensor evaluation ladder
versus simulator truth — for a **Phase-1 Unitree Go2** stack that satisfies
board card **P1-B** (real localization and perception producers) and feeds
**P1-C** (owner identity + formation goals).  
**Method:** repository audit of Parcel pose/perception seams + WebSearch of
primary papers/repos and Go2 field stacks. External metrics are
author-reported unless a Parcel artifact is cited.

**Safety status:** nothing in this note clears unsupervised physical
operation. Localization health and geometry freshness remain fail-closed
preconditions under P0-B; learned or open-vocab semantics never declare free
space.

---

## 1. Verdict

Phase 1 should ship a **two-rate localization producer** behind the existing
`PoseProvider` / `PoseEstimate` seam:

| Role | Frame | Producer | Rate target |
| --- | --- | --- | --- |
| Continuous odometry | `ODOM` | **FAST-LIO2** (Mid-360) or **Point-LIO** (built-in L1) | ≥20 Hz pose, IMU-propagated between scans |
| Globally consistent pose | `MAP` | Offline PCD map + scan-to-map localization (FAST-LIO localization / open3d_loc pattern), with optional loop-closure mapping pass via **LIO-SAM** or RTAB-Map | Corrections at 1–5 Hz; may jump |

**Do not** make LIO-SAM or DLIO the default Go2 odometry front-end in Phase 1.
Keep **DLIO** as a continuous-time challenger on logged Mid-360 bags.
Keep **LIO-SAM** (or RTAB-Map) as the **mapping / long-loop** backend when the
mission revisits space for more than ~tens of meters of open travel.

Perception must split into three independent lanes already sketched in
`TARGET_ARCHITECTURE.md`:

1. **Geometry** (20–50 Hz): camera depth / LiDAR occupancy / TTC — sole free-space authority.  
2. **Fast closed-set semantics + owner** (10–30 Hz): people, road/sidewalk,
   vehicles, poles, doors, curb/stairs; enrolled owner association.  
3. **Queried open-vocabulary / OCR** (0.2–2 Hz, on demand): Grounding-DINO-class
   boxes + SAM-class masks + ROI OCR — proposals only, never motor authority.

Owner identity is an **enrolled multi-frame posterior** over appearance
(OSNet / FastReID), metric depth, motion continuity, and ambiguity margin —
never a simulator `owner_id` and never “nearest person.”

---

## 2. Parcel baseline (what is broken for Phase 1)

Repository evidence (not speculative):

| Finding | Evidence | Phase-1 implication |
| --- | --- | --- |
| Production pose is sim truth | `configs/navigation/pose.yaml` ships `provider: truth`; `pose.py` documents that `TruthPoseProvider` returns identical MAP/ODOM with zero covariance | Real LIO must implement `PoseProvider`; truth remains labeled-sim only |
| Drift profiles are interface stress, not SLAM | `calibrated_go2` / `stress` in `pose.yaml` are Probabilistic-Robotics alpha stand-ins; comments pin DogLegs leg-odometry bands | Useful for consumer tests; **not** a substitute for LiDAR–IMU localization |
| Semantic detections are oracle-shaped | `detection_adapter` is GT → Habitat-style noise; no pixel inference on the product path | Replace producers; keep `DetectionMsg` / evidence envelopes |
| Owner track lacks product identity | Sim `OwnerTrack` + noise adapter; `OwnerTrackV1` already anticipates enrollment, covariance, ambiguity | Wire real association into the existing contract |
| Camera channel exists as scaffolding | `camera_channel/` (synthetic / MuJoCo EGL / D455 shapes) | Physical D455 (or equivalent) + capture-time sync is P1-B work |
| Unitree path uncommissioned | `robot.yaml` axes/state frames not commissioned | Localization cannot authorize motion until commissioning + P0-B health gates |

The seam is already REP-105-shaped (`MAP` may jump, `ODOM` drifts, health is
`HEALTHY|DEGRADED|LOST`). Phase 1 fills the producer; it does not redesign the
consumer contract.

---

## 3. LIO comparison (FAST-LIO2 / LIO-SAM / DLIO / Point-LIO)

### 3.1 What each system optimizes for

| System | Core idea | Strengths | Weaknesses for Go2 Phase 1 |
| --- | --- | --- | --- |
| **[FAST-LIO2](https://github.com/hku-mars/FAST_LIO)** (Xu et al., T-RO 2022) | Tight iEKF; direct raw-point registration; ikd-Tree map | Low latency; strong short-term RPE; solid-state Livox friendly; ARM-capable; many Go2/Mid-360 ports | No native loop closure → unbounded drift on long open paths |
| **[LIO-SAM](https://github.com/TixiaoShan/LIO-SAM)** (Shan et al., IROS 2020) | Factor graph (GTSAM); keyframe optimization; loop closure | Better long-term ATE when loops exist; map consistency for teach-repeat | Heavier; slower pose stream; more sensitive to IMU grade / sync; less common as the Go2 reactive odometry |
| **[DLIO](https://github.com/vectr-ucla/direct_lidar_inertial_odometry)** (ICRA 2023) | Coarse-to-fine continuous-time deskew + GICP; geometric observer | Accurate motion correction; lightweight relative to graph SLAM; Livox/Ouster support; ROS 2 `feature/ros2` | Smaller Go2 deployment footprint than FAST-LIO; extrinsic/IMU tuning is brittle; less field lore on quadruped vibration |
| **[Point-LIO](https://github.com/hku-mars/Point-LIO)** (He et al., 2023) | Point-by-point updates; high-bandwidth odometry; IMU-as-output model | Handles aggressive motion / vibration; used by [CMU Go2 autonomy](https://github.com/jizhang-cmu/autonomy_stack_go2) on built-in L1; Unitree ships [`point_lio_unilidar`](https://github.com/unitreerobotics/point_lio_unilidar) | Still odometry-first (not loop-closure MAP); CMU README documents drift, low-obstacle limits, camera/LiDAR timestamp skew |

Independent comparative signals (author / third-party, not Parcel measurements):

- KITTI-style studies under unified preprocessing report **FAST-LIO2 better
  short-term RPE / latency**, **LIO-SAM better long-term ATE** when loops
  exist ([ICBAIE 2025 consistency study](https://doi.org/10.1109/icbaie66852.2025.11326661)).
- Agricultural long-run loops: FAST-LIO2 can accumulate large drift; graph
  methods with loop closure remain consistent
  ([ICROS 2025 orchard evaluation](https://doi.org/10.5302/j.icros.2025.25.0218)).
- Community Mid-360 / 6-axis bag benchmarks often favor FAST-LIO2 RPE when
  LIO-SAM is patched for 6-axis IMUs
  ([lio-sam-vs-fast-lio-benchmark](https://github.com/codermery/lio-sam-vs-fast-lio-benchmark))
  — treat as indicative, not decisive for Go2 gait vibration.

### 3.2 Recommendation by sensor kit

**Kit A — Built-in Unitree L1 only (minimum hardware)**

- **ODOM:** Point-LIO (`point_lio_unilidar` or CMU stack pin).  
- **MAP:** short-session local map from Point-LIO; for revisit, export PCD and
  run scan-to-map localization, **or** RTAB-Map LiDAR mode as challenger.  
- **ODD caveat (binding):** CMU stack guidance and Parcel architecture already
  treat L1-only coverage as incomplete for low obstacles (<~0.3 m class).
  Geometry safety ODD must exclude unprotected directions; add depth camera
  before claiming sidewalk/curb work.

**Kit B — Livox Mid-360 (+ internal or Mid-360 IMU) — preferred Phase-1 kit**

- **ODOM:** FAST-LIO2 with Go2 Mid-360 YAML (see
  [FAST_LIO_LOCALIZATION_GO2](https://github.com/yuewangg/FAST_LIO_LOCALIZATION_GO2),
  [unitree-go2-waypoint-nav](https://github.com/yehna-kim/unitree-go2-waypoint-nav)).  
- **MAP:** build with FAST-LIO2; localize with FAST-LIO localization /
  open3d_loc against processed PCD; optional LIO-SAM mapping session when
  loop-rich floors/yards need global consistency.  
- **Challenger:** DLIO on the same bags for deskew quality under trot/gallop.

**Anti-recommendation:** do not fuse “best of all LIO papers” into one
process. One odometry authority publishes `ODOM`; one localization authority
publishes `MAP` corrections and health. Parcel consumers already assume that
split.

### 3.3 Fusion architecture (LiDAR + IMU + camera + optional GNSS)

```text
capture clocks (HW timestamps)
        │
        ├─ IMU ──────────────┐
        ├─ LiDAR points ───► LIO (ODOM) ──► PoseProvider.odom
        │                    │
        │                    └─ registered cloud / local map
        │                              │
        │                    scan-to-map / loop backend
        │                              ▼
        │                         PoseProvider.map (+ correction epoch)
        │
        ├─ RGB (+ depth) ──► time_sync + extrinsics
        │         │              │
        │         ├─ geometry depth / negative obstacles ──► safety costmap
        │         ├─ fast det/seg/track ──► people / regions
        │         └─ slow OV / OCR query ──► semantic memory (TTL)
        │
        └─ (optional) GNSS / UWB ──► advisory GEO prior only in Phase 1
```

Hard rules for Phase 1:

1. **Capture-time sync**, not arrival-time sync (CMU Go2 autonomy explicitly
   warns that unsynchronized camera vs LiDAR/IMU is a field failure mode).  
2. Versioned **extrinsics** (`base_link ← LiDAR ← IMU`, `base_link ← camera`)
   with calibration_id on every evidence envelope. Mid-360 internal
   IMU-to-LiDAR offset ≠ mount-to-base offset — Go2 ports document this trap.  
3. **Conservative fusion for obstacles:** one sensor cannot vote away another’s
   occupied cell; uncovered space is unknown, not free.  
4. **GNSS / Maps / UWB** remain advisory. They may propose a GEO prior or
   re-anchor candidate; they do not set `PoseHealth.HEALTHY` alone indoors.  
5. Publish **covariance + health + stamp + correction epoch**. Physical
   translation requires healthy pose under P0-B; `LOST`/`DEGRADED` → HOLD.

---

## 4. Open-vocabulary perception (fast / slow)

### 4.1 Why not “Grounding DINO everywhere”

Grounding DINO + SAM 2 is the right **research** open-set pair, but edge
deployments on Jetson Orin class hardware consistently show that the full
foundation stack is too slow for the closed control loop
([Hackster Orin Language-SAM writeup](https://www.hackster.io/lurst811/realtime-language-segment-anything-on-jetson-orin-ccf6e1);
[PMC edge OV perception study](https://pmc.ncbi.nlm.nih.gov/articles/PMC12583037/);
NVIDIA [NanoSAM](https://github.com/NVIDIA-AI-IOT/nanosam)).

Isaac ROS guidance matches Parcel’s split: **interleave** open-vocab
inference and train / run a **fast detector** for runtime classes.

### 4.2 Phase-1 component slate

| Lane | First candidates | Cadence | Authority |
| --- | --- | --- | --- |
| Fast objects | RT-DETR (or TensorRT YOLO-World-tiny as OV-lite) | 10–30 Hz | Typed detections → memory / planner proposals |
| Fast regions | PP-LiteSeg (road, sidewalk, floor, curb, stairs, doorway) | 10–20 Hz | Soft costs / terminal region priors — **not** free space |
| Tracking | NvDCF / ByteTrack-class tracker | with detections | Transient IDs only |
| Slow OV boxes | Grounding DINO (or YOLO-World) on prompt | on query / 0.2–2 Hz | Candidate generation for “lamppost / Blue Bottle” |
| Slow masks | SAM 2 / NanoSAM / EfficientViT-SAM | on query | Metric association with LiDAR; never clearance |
| OCR | PaddleOCR on rectified ROI | on query | Storefront / sign text with temporal voting |

Open-vocab outputs enter `SemanticEntityV1`-shaped memory with
`RESOLVED|AMBIGUOUS|UNSEEN|STALE`, TTL, covariance, and evidence IDs. Clio /
Khronos / VLMaps / ConceptGraphs are **later adapters** after this typed
memory works — not Phase-1 blockers.

### 4.3 Prompt and false-positive discipline

- Freeze a **prompt pack** per task family (`lamppost`, `sidewalk`, brand
  names from fixtures) with measured precision/recall on Parcel bags.  
- Require **LiDAR support** (point-in-mask or range gate) before a semantic
  goal is actionable.  
- Ambiguous multi-match → clarify / rescan, never silent nearest-neighbor.  
- RGB cannot clear a geometrically occupied cell.

---

## 5. Owner re-identification

### 5.1 Contract (already half-specified)

`OwnerTrackV1` expects: enrolled owner id, transient track id, state,
pose/velocity with 4×4 covariances, identity_score, visibility_score,
appearance evidence refs, and confirmation timestamp. Phase 1 must **fill**
this rather than invent a parallel owner channel.

### 5.2 Recommended association stack

```text
RGB person detections (fast closed-set)
        │
        ├─ short-horizon tracker (transient_track_id)
        ├─ OSNet / FastReID embedding vs enrolled gallery
        ├─ metric depth / LiDAR association (range + bearing)
        ├─ motion continuity / predicted gate
        └─ M-of-N confirmation + margin vs 2nd-best
                    │
                    ▼
              OwnerTrackV1.state ∈
                {confirmed, tentative, ambiguous, lost, ...}
```

Primary literature / tooling:

- Appearance extractors: [OSNet / deep-person-reid](https://github.com/KaiyangZhou/deep-person-reid),
  [FastReID](https://github.com/JDAI-CV/fast-reid).  
- Robot following under occlusion / appearance change: CARPE-ID
  ([arXiv:2310.19413](https://arxiv.org/abs/2310.19413)); online continual
  ReID for person following ([arXiv:2309.11727](https://arxiv.org/abs/2309.11727)).  
- Learned waypoint proposer (shadow only): MiniCPM-RobotTrack — **must not**
  own identity or safety (author-reported nonzero collisions; absent-target
  caveat).

### 5.3 Non-negotiable behaviors

1. Consent gallery enrollment (multi-view, clothing change optional second
   gallery) before follow is armed.  
2. On crossing / long occlusion: emit `AMBIGUOUS`/`LOST`, decelerate or stop,
   search, then ask — **never** silently pick the closest person.  
3. Single-frame reacquisition is forbidden (current audit P1.2).  
4. Identity posterior is independent of MiniCPM / VLA proposals; models may
   propose formation waypoints only while `confirmed`.  
5. Appearance-only match without metric support is insufficient outdoors with
   lookalikes.

Online continual learning (OCL-ReID / CARPE-ID style) is a **Phase 1.5
challenger** after a frozen gallery baseline is measured; do not block P1-C on
continual adaptation.

---

## 6. Real-sensor ladder versus sim truth

Phase 1 evaluation must climb an honesty ladder. Each rung may use richer
oracles **only** for attribution, never as the product producer under test.

| Rung | Pose producer | Semantics / owner | What a pass means |
| --- | --- | --- | --- |
| **R0 — Truth (current)** | `TruthPoseProvider` | Sim polygons / owner id (+ optional detection noise) | Lifecycle and planner tests only; **not** localization or perception claims |
| **R1 — Drift stress** | `DriftingOdomProvider` profiles | Same as R0 | Consumers honor covariance / chance constraints / HOLD on LOST |
| **R2 — Sensor-faithful sim** | LIO on simulated Mid-360/L1 + IMU (or recorded replay into LIO) | Rendered camera → real detectors; owner from pixels | Product path without oracle fields; still sim dynamics |
| **R3 — Logged real bags** | Offline LIO / localization on Go2 bags | Offline det/ReID/OV on mounted camera | Calibration, sync, vibration, lighting; no closed-loop motion claim |
| **R4 — Shadow HIL** | Live LIO on tethered / supervised Go2 | Live perception; planner in shadow or speed-limited | Compare MAP/ODOM to surveyed markers / total station / AprilTag course |
| **R5 — Supervised courses** | Commissioned stack | Full P1-B/C | Indoor then outdoor ODD courses under P5 gates |

Reporting rules:

- Never call R0/R1 “real localization.”  
- When publishing NAV_INSTRUCT or follow metrics, state the rung and whether
  semantic success used oracle polygons.  
- Pair every learned proposer A/B with the **same** rung and calibration_id.  
- Sim success is evidence for the safety case, not the safety case
  (`TARGET_ARCHITECTURE.md` / README working agreements).

Suggested frozen courses for R3–R5:

1. Straight corridor + 180° return (loop-closure / ATE).  
2. Cluttered furniture (RPE + collision monitor).  
3. Owner cross with lookalike distractor (identity).  
4. Occlusion behind pillar ≥3 s (reacquire vs ask).  
5. Outdoor sidewalk stub with curb (geometry ODD; L1-only expected fail).  
6. Open-vocab “wait by lamppost / storefront” with dual candidates.

---

## 7. Phase-1 Go2 stack (concrete pin list)

### 7.1 Processes and ownership

| Process | Runs | Publishes into Parcel |
| --- | --- | --- |
| Sensor drivers | `livox_ros_driver2` or Unitree L1 SDK; RealSense/D455; IMU | raw stamped topics |
| LIO sidecar | FAST-LIO2 **or** Point-LIO (pinned commit + hash) | `ODOM` PoseEstimate stream |
| Localization sidecar | FAST-LIO localization / open3d_loc (map session separate) | `MAP` PoseEstimate + health |
| Fast perception service | det + seg + track + ReID | DetectionMsg / OwnerTrackV1 / region masks |
| Slow OV service | Grounding-DINO-class + mask + OCR | on-demand SemanticEntity updates |
| Parcel runtime | executive, planner, safety | consumes typed snapshots only |

DDS isolation: Go2 SDK2 and ROS 2 must not share a conflicting DDS domain
(field stacks repeatedly hit this). Parcel’s Unitree Sport client stays the
locomotion boundary; LIO never writes velocity.

### 7.2 Exit criteria for P1-B / P1-C (perception slice)

P1-B done when:

1. Physical or bag-replay path produces synchronized camera/LiDAR/IMU with
   versioned extrinsics.  
2. `PoseProvider` serves non-truth MAP/ODOM with covariance and health; truth
   gated to labeled sim.  
3. Product path emits typed regions, entities, people **without** oracle
   fields.  
4. Missing/stale LiDAR, pose, or transform → HOLD (P0-B), measured.

P1-C done when:

1. Enrolled gallery + multi-frame identity with ambiguity states.  
2. Follow/approach consume `OwnerTrackV1` and emit short-TTL SE(2) formation
   goals into the common planner (not direct proportional velocity — that is
   the N6/P1.1 controller fix, but identity is this workstream’s gate).  
3. Lookalike / occlusion suite shows zero silent identity switches on the
   frozen bag set.

### 7.3 Explicit non-goals for Phase 1

- City-scale GEO routing and Google Maps authority.  
- Replacing Sport with a learned locomotion policy.  
- Full 3-D scene graphs (Clio/ConceptGraphs) as the product memory.  
- Continuous open-vocab at control rates.  
- Claiming L1-only negative-obstacle safety outdoors.

---

## 8. Disagreements with prior task docs

| Prior claim | N4 position |
| --- | --- |
| Appendix N5 lists Point-LIO / RTAB-Map / nvblox as primary | Agree Point-LIO for **L1**; prefer **FAST-LIO2** when Mid-360 is fitted; RTAB-Map/nvblox remain mapping/costmap challengers, not the first ODOM pick |
| “Built-in L1/CMU path is a useful baseline” | Agree as **baseline**, not complete sensor solution — keep the documented low-obstacle, drift, and timestamp caveats as ODD limits |
| Fast closed-set RT-DETR + slow Grounding DINO + SAM 2 | Agree architecture; add **YOLO-World / NanoSAM** as Orin latency challengers so OV does not stall the Jetson |
| Truth pose permitted in sim | Agree only when labeled; R2+ must not silently fall back to truth on the product path |

---

## 9. Confidence

| Claim | Confidence | Why |
| --- | --- | --- |
| MAP/ODOM seam + fail-closed health is the right Parcel interface | **High** | Implemented and documented in `pose.py` / pose.yaml |
| FAST-LIO2 (Mid-360) or Point-LIO (L1) as Phase-1 ODOM | **High** for ecosystem fit; **medium** for Parcel accuracy until R3 bags | Multiple Go2 ports; no Parcel closed-loop measurement yet |
| LIO-SAM as default reactive odometry | **Low** (reject) | Latency / loop-oriented design mismatches 10–50 Hz control |
| DLIO as challenger | **Medium** | Strong paper story; thinner Go2 ops record |
| Fast/slow perception split | **High** | Matches Isaac ROS guidance + Orin OV latency literature |
| OSNet/FastReID + metric gate for owner | **High** for architecture; **medium** for gallery thresholds until Parcel calibration |
| R0 truth metrics as perception success | **Reject** | Audit P0.3 / P1.4 |

---

## 10. Sources (WebSearch + primary)

### LiDAR–inertial

- FAST-LIO2 paper/page: https://ziv-lin.github.io/publication/paper_fast_lio2/ · code: https://github.com/hku-mars/FAST_LIO  
- LIO-SAM: Shan et al., IROS 2020 · https://github.com/TixiaoShan/LIO-SAM  
- DLIO: https://github.com/vectr-ucla/direct_lidar_inertial_odometry · arXiv:2203.03749  
- Point-LIO: https://github.com/hku-mars/Point-LIO · Unitree port: https://github.com/unitreerobotics/point_lio_unilidar  
- Comparative signals: https://doi.org/10.1109/icbaie66852.2025.11326661 · https://doi.org/10.5302/j.icros.2025.25.0218 · https://github.com/codermery/lio-sam-vs-fast-lio-benchmark  

### Go2 field stacks

- CMU autonomy (Point-LIO, L1): https://github.com/jizhang-cmu/autonomy_stack_go2  
- FAST-LIO localization Go2: https://github.com/yuewangg/FAST_LIO_LOCALIZATION_GO2  
- Mid-360 + FAST-LIO + RTAB-Map + Nav2: https://github.com/yehna-kim/unitree-go2-waypoint-nav  
- Mid-360 localization pattern: https://github.com/real-lsy/That-nav  

### Open-vocab / edge

- Grounding DINO · SAM 2 · NanoSAM: https://github.com/NVIDIA-AI-IOT/nanosam  
- Orin OV latency: https://pmc.ncbi.nlm.nih.gov/articles/PMC12583037/  
- Isaac ROS Grounding DINO deployment guidance (fast/slow split)  
- OneMap open-vocab mapping on Spot/Orin: https://www.finnbusch.com/OneMap/  

### Owner ReID

- OSNet / FastReID toolkits  
- CARPE-ID: https://arxiv.org/abs/2310.19413  
- OCL person-following ReID: https://arxiv.org/abs/2309.11727  

### Parcel internals

- `src/parcel_robot/pose.py`, `configs/navigation/pose.yaml`  
- `src/parcel_robot/contracts/v1.py` (`OwnerTrackV1`, evidence envelopes)  
- `src/parcel_robot/detection_adapter/`, `camera_channel/`  
- `scrum/20260807/task_2/{README,TARGET_ARCHITECTURE,CURRENT_STACK_AUDIT,SOURCE_LEDGER}.md`  

---

## 11. Handoff to synthesis

For `RESEARCH_THESIS.md` and board sequencing:

1. **P0-B** freezes pose/perception health authority before any LIO lands.  
2. **P1-B** implements Kit B (preferred) or Kit A with explicit ODD shrinkage.  
3. **P1-C** layers enrolled ReID; N6 owns formation control.  
4. **P2-B** semantic memory consumes OV outputs with TTL — after producers
   exist.  
5. Learned models (MiniCPM, CityWalker, CE-Nav, …) stay on **R2+** shadow
   only, gated by the same localization/identity producers.

**One-line summary:** Phase-1 Go2 perception is a FAST-LIO2/Point-LIO odometry
lane plus scan-to-map MAP corrections, a fast closed-set + owner ReID lane, and
a slow open-vocab query service — all feeding typed Parcel contracts while
geometry alone retains free-space authority, climbing an explicit
truth → bag → HIL ladder so sim oracles stop masquerading as localization.
