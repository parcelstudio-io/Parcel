# Hardware-readiness ledger — sim stand-ins → P5 re-run gates

**Card:** K2′ · **Opened:** 2026-08-05 · **Refreshed:** 2026-08-05 (P5 readiness)  
**Binding:** [ADJUDICATION.md](ADJUDICATION.md) Owner amendment (hardware last, sim throughout).

Nothing on this ledger may be quoted as hardware-validated. Each row is a
**sim stand-in** with a named **P5 re-run gate**. Extends the U1/U2 register
discipline in `backlog/UNVERIFIED.md`.

**P5 physical work is blocked** until the owner purchase decision. See
[PHASE5_GATE.md](PHASE5_GATE.md), [P5_PROCUREMENT_BOM.md](P5_PROCUREMENT_BOM.md),
[P5_COMMISSIONING_CHECKLIST.md](P5_COMMISSIONING_CHECKLIST.md).

| ID | Sim stand-in | Sim test / evidence today | Does not prove | P5 re-run gate (exact name) | Status |
|---|---|---|---|---|---|
| HR-1 | Motion dynamics | Kinematic MuJoCo / headless SE2 base; bag topics `odom/se2` + `robot/sport_state`. CI: `tests/test_bags_roundtrip.py`, `tests/test_sim.py`, `tests/test_motion.py` | Sport-mode tracking, contact, slip, balance under the 10 Hz command stream | **P5-G-MOTION** — Replay the same command bag on a commissioned Go2 through `ControlManager` only; compare commanded vs measured SE2; confirm latched E-stop feedback | **unvalidated** |
| HR-2 | UWB noise model | P2 `parcel_robot.uwb`: bearing/range noise + multipath dropout → `UwbSample` / extras[`uwb`] / bag `uwb/state`; `OwnerFusionStub` vision↔UWB → `OwnerTrackV1`. CI: `tests/test_p2_uwb_noise.py`. Status: [P2_UWB_STATUS.md](P2_UWB_STATUS.md) | Indoor/outdoor multipath, occlusion, true `rt/uwbstate` statistics; that sim noise params match field error | **P5-G-UWB** — Characterize DDS `rt/uwbstate` vs vision truth (indoor/outdoor/occlusion/multipath); compare error model to P2 noise params; decide primary channel (`OwnerFusionConfig.primary`) | **unvalidated** |
| HR-3 | GNSS covariance/dropout model | P3 `parcel_robot.gnss`: east/north jitter + cov inflation after canyon dropouts → `GnssFix` / extras[`gnss`] / bag `gnss/fix`. CI: `tests/test_p3_city_layer.py`. Status: [P3_CITY_STATUS.md](P3_CITY_STATUS.md) | Real urban canyon GNSS, NTRIP, cold-start; that sim noise params match field error | **P5-G-GNSS** — Bench + sidewalk GNSS logs into the pre-built bag harness; verify covariance/dropout model calibration against recorded fixes | **unvalidated** |
| HR-4 | Rendered-pixel perception | MuJoCo CameraChannel (EGL when `MUJOCO_GL=egl`) + CI synthetic CameraBackend; bag `camera/color/meta` at D455-nominal intrinsics + 35 cm mount; low-viewpoint sample-pack; P3 storefront placard textures (`parcel_robot.storefront`). CI: `tests/test_k5_camera_detection_gates.py`, `tests/test_k5_opus_sim_wiring.py`, `tests/test_p3_storefront_ocr.py`. Status: [P3_OCR_STATUS.md](P3_OCR_STATUS.md), [K5_STATUS.md](K5_STATUS.md) | Real low-viewpoint optics, lighting, motion blur, domain gap; wild storefront OCR precision | **P5-G-PIXEL** — Re-run low-viewpoint gate pack on day-one D455 bags; PP-OCR / detector / ReID on real pixels; report delta vs sim gates (incl. storefront named-place recall vs P3 synthetic baseline) | **unvalidated** |
| HR-5 | LiDAR geometry | Sim planar / raycast `lidar/scan` in bags. CI: `tests/test_mujoco_lidar.py`, `tests/test_raycast_lidar.py`, `tests/test_bags_roundtrip.py` | Real Unitree L1 (or installed) noise, sync, and sub-0.3 m obstacles | **P5-G-LIDAR** — Replay day-one lidar bags through localization + collision gate; compare freeze/collision rates to sim | **unvalidated** |
| HR-6 | CPU-budget proxy timing | Desktop timing of the 10 Hz hot path via `evals/cpu_budget_proxy.py` (K7); bag monotonic receive stamps. CI: `tests/test_cpu_budget_proxy.py`. Artifact: [cpu-budget-proxy-k7.json](cpu-budget-proxy-k7.json). Status: [K7_STATUS.md](K7_STATUS.md) | Orin NX 16GB latency, thermal, GPU co-residency | **P5-G-ORIN-TIMING** — On-device replay of the same bags; assert integrated hot path ≤176 ms median; publish proxy→device delta | **unvalidated** |
| HR-7 | Desktop audio | K6/P2 voice lanes + dialogue-state × T2 with fakes; host audio after backlog [B1 apt](../../../backlog/BLOCKED.md). CI: `tests/test_p2_dialogue.py`, `tests/test_voice_audio.py`. Status: [P2_DIALOGUE_STATUS.md](P2_DIALOGUE_STATUS.md), [K6_STATUS.md](K6_STATUS.md) | Acoustic UX, XVF3800 AEC, cabin acoustics, barge-in under motion | **P5-G-AUDIO** — WoZ + AEC characterization on mounted XVF3800; ack/barge-in budgets on hardware voice path | **unvalidated** |
| HR-8 | Bag replay harness | `parcel_robot.bags` recorder/replayer + `parcel.bag.v1` schema. CI: `tests/test_bags_roundtrip.py`. Status: [K2_STATUS.md](K2_STATUS.md) | That real bags need zero schema change *and* closed-loop safety | **P5-G-BAG-DROPIN** — Drop day-one real bags into this harness without schema redesign; Orin replay smoke; no agent-path oracle fields | **unvalidated** (schema ready in sim) |
| HR-9 | Golden image + firmware pin ADRs | ADR stubs drafted under `adr/` (no flash executed). Docs: [adr/0001-golden-image.md](adr/0001-golden-image.md) (**Draft**), [adr/0002-firmware-pin.md](adr/0002-firmware-pin.md) (**Draft**) | That the sacrificial-dock flash and ≥1.1.13 pin survive commissioning | **P5-G-INSTALL** — Validate ADRs on sacrificial Orin NX dock + Go2 EDU firmware gate during P5 install | **unvalidated** (ADRs draft only) |
| HR-10 | OSM / Overture map priors | P3 `parcel_robot.maps`: cached `runtime_assets/maps/neighborhood_v1.json` + `OsmWaypointProposer`→`SE2Goal`; offline `OvertureTileClient` over `overture_places_v1.json`. CI: `tests/test_p3_city_layer.py`. Status: [P3_CITY_STATUS.md](P3_CITY_STATUS.md) | Live osmnx topology, surveyed sidewalks, CDLA Overture field refresh, WGS84 localization | **P5-G-MAPS** — Re-pull / validate neighborhood graph against field GNSS+survey; refresh Overture tile from production extract; confirm brand OCR cascade precision on day-one bags | **unvalidated** |
| HR-11 | Crossing / curb geofence | P3 `CrossingModePolicy`: curb-stop + voice initiation; road keepout hard geofence; zero autonomous road entry pinned in CI. CI: `tests/test_p3_city_layer.py`. Status: [P3_CITY_STATUS.md](P3_CITY_STATUS.md) | Field curb detection, leashed-course curb-stop rate, minutes-per-intervention on mixed outdoor course | **P5-G-CROSSING** — Leashed 20-min mixed course: curb-stop on 100% of mapped crossings, zero autonomous street entries; voice initiation through T1 with gate concurrence | **unvalidated** |
| HR-12 | Route memory / teach-and-repeat (rendered VPR) | P4 `parcel_robot.route_memory`: keyframe store + StubVPREmbedder + gated `RouteMemoryProposer`→`SE2Goal`. CI: `tests/test_p4_route_memory.py`. Status: [P4_ROUTE_STATUS.md](P4_ROUTE_STATUS.md) | GuideNav CosPlace+Reloc3r field SR, Orin NX 5 Hz, km-scale routes, MegaLoc recall @ 35 cm | **P5-G-ROUTE** — Teach ≥2 habitual walks on hardware; repeat-route ≥90% over 10 runs/route with ≤1 intervention/km; profile Reloc3r/VPR vs StubVPR on day-one D455 bags | **unvalidated** |
| HR-13 | CityWalker learned proposer | P4 `CityWalkerInferenceAdapter`: vendor detect + fail-closed UNVERIFIED skip; cached-offline waypoints → gated `SE2Goal` only. CI: `tests/test_p4_route_memory.py`. Status: [P4_ROUTE_STATUS.md](P4_ROUTE_STATUS.md) | Urban IL success rate, Orin co-residency, promotion ≥+5pp vs OSM-graph-only with no added gate interventions | **P5-G-CITYWALKER** — Run CityWalker A/B on recorded sim then day-one sidewalk bags behind GoalArbiter; admit only if ≥+5pp with zero extra gate interventions | **unvalidated** |
| HR-14 | VLFM value-map → SearchEntity | P4 `HeuristicVLFMScorer` implements `FrontierScorer` for `select_frontier` (headless heuristic). CI: `tests/test_p4_route_memory.py`. Status: [P4_ROUTE_STATUS.md](P4_ROUTE_STATUS.md) | Real VLFM VLM scoring, frontier value-map quality, tier-C SearchEntity lift | **P5-G-VLFM** — Swap heuristic for offboard VLFM service; require ≥ prior table on frozen tier C with no gate regression | **unvalidated** |

## Rules

1. A green sim test against an HR-* stand-in updates **sim evidence only**.
2. Promotion language that omits the matching P5 gate is a process bug.
3. Agent bags (`source=sim` or `hardware`) must keep `does_not_prove` non-empty
   and must fail closed on privileged oracle fields (see
   `tests/test_bags_roundtrip.py`).
4. When a P5 gate passes, move the row to **validated** with run ID + bag
   digest; do not delete the historical unvalidated claim.
5. Status remains **unvalidated** until the named P5-G-* gate has physical
   evidence. Parenthetical notes (schema ready / ADR draft) are sim/doc state
   only — they are not hardware validation.

## Gate name index (P5 execution order, draft)

| Order | Gate | HR rows |
|---|---|---|
| 1 | P5-G-INSTALL | HR-9 |
| 2 | P5-G-BAG-DROPIN | HR-8 |
| 3 | P5-G-MOTION | HR-1 |
| 4 | P5-G-LIDAR | HR-5 |
| 5 | P5-G-PIXEL | HR-4 |
| 6 | P5-G-UWB | HR-2 |
| 7 | P5-G-GNSS | HR-3 |
| 8 | P5-G-ORIN-TIMING | HR-6 |
| 9 | P5-G-AUDIO | HR-7 |
| 10 | P5-G-MAPS | HR-10 |
| 11 | P5-G-CROSSING | HR-11 |
| 12 | P5-G-ROUTE | HR-12 |
| 13 | P5-G-CITYWALKER | HR-13 |
| 14 | P5-G-VLFM | HR-14 |

Exact staging (dry-run → bench → leashed → free) is in
[P5_COMMISSIONING_CHECKLIST.md](P5_COMMISSIONING_CHECKLIST.md). Gates above
do not authorize purchase or flash.

## Pointers

- Bag MVP: `src/parcel_robot/bags/`
- UWB sim stand-in (P2 / HR-2): `src/parcel_robot/uwb/` · [P2_UWB_STATUS.md](P2_UWB_STATUS.md)
- Storefront / OCR sim (P3 / HR-4): `src/parcel_robot/storefront/` · [P3_OCR_STATUS.md](P3_OCR_STATUS.md)
- GNSS / maps / crossing (P3 / HR-3, HR-10, HR-11): `src/parcel_robot/gnss/`, `src/parcel_robot/maps/`, `src/parcel_robot/runtime_assets/maps/` · [P3_CITY_STATUS.md](P3_CITY_STATUS.md)
- Route memory / CityWalker / VLFM stubs (P4 / HR-12, HR-13, HR-14): `src/parcel_robot/route_memory/` · [P4_ROUTE_STATUS.md](P4_ROUTE_STATUS.md)
- Status: [K2_STATUS.md](K2_STATUS.md), [K7_STATUS.md](K7_STATUS.md)
- Compose skeleton (desktop/CI, no flash): `deploy/compose.yaml`
- CPU-budget proxy: `evals/cpu_budget_proxy.py`
- ADRs (still **Draft**): [adr/0001-golden-image.md](adr/0001-golden-image.md),
  [adr/0002-firmware-pin.md](adr/0002-firmware-pin.md)
- P5 readiness pack: [PHASE5_GATE.md](PHASE5_GATE.md),
  [P5_PROCUREMENT_BOM.md](P5_PROCUREMENT_BOM.md),
  [P5_COMMISSIONING_CHECKLIST.md](P5_COMMISSIONING_CHECKLIST.md),
  [PROGRAM_STATUS.md](PROGRAM_STATUS.md)
