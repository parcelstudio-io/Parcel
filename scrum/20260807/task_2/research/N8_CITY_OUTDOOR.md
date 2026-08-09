# N8 — City outdoor / OSM / CityWalker

**Workstream:** Opus research wave N8  
**Date:** 2026-08-07  
**Question:** How should Parcel compose OSM/Overture topology, GNSS absolute
pose, sidewalk/curb geometry, and learned urban priors (CityWalker) without
letting any external map or model become metric free-space or arrival
authority?

**Method:** Independent repository audit of Parcel's city stack plus primary
literature/web sources (CityWalker CVPR 2025, OSM pedestrian guidelines,
GNSS–LiDAR urban canyon work, curb/elevation detection, Nav2 Route, MetaUrban,
Overture transportation). External metrics are author-reported unless a Parcel
artifact is cited.

**Verdict (one line):** Keep OSM/GNSS/CityWalker as TTL-bound *advisory*
proposers and geodetic/topological priors; own sidewalk/road, curb-stop,
crossing, and arrival with sensor-derived *metric* geometry — and do not
promote city-scale routing until local MAP/ODOM localization and curb physics
gates exist.

---

## 1. Scope and non-goals

### In scope

- OSM / Overture pedestrian graphs as long-horizon route priors
- GNSS (consumer / RTK-class) as absolute GEO correction, not sidewalk meter
- CityWalker as an urban visual waypoint / traversability prior
- Sidewalk vs road classification; curb detection; crossing policy
- The hard contract: **map advisory vs metric authority**
- Evaluation substrate (MetaUrban, city-block sim, teach-repeat) for outdoor

### Out of scope (owned by sibling workstreams)

- Nav2 free-space planners / MPPI internals → N1 / N3
- Owner identity and social costs → N6
- Product evaluation ladder honesty → N7 (wave ID; appendix N8 historically)
- End-to-end RL decision → RL1 / RL2

---

## 2. Parcel current state (repository evidence)

Parcel already sketches the correct *authority shape*, mostly in offline /
fail-closed form. None of it is field-proven.

| Layer | Code / asset | What it does | Honest limit |
| --- | --- | --- | --- |
| OSM footway graph | `maps/graph.py`, cached `neighborhood_v1.json` | Footway/path/pedestrian/sidewalk + crossing edges; road keepouts; curb records | Fixture topology; ENU meters are sim-scene coords, not WGS84 field localization (`DOES_NOT_PROVE` / HR-10) |
| OSM waypoints | `maps/waypoints.py` (`osm_footway_v1`) | Emits `SE2Goal` along graph; **never** self-authorizes crossing edges | Topological prior only; `grid_v1` remains motion authority |
| Crossing / curb policy | `maps/crossing.py` | curb-stop → announcement → **authenticated, authorized owner/control-channel decision** → gated crossing; transcript alone is insufficient; zero autonomous road entry | Sim policy; does not prove field curb detection (HR-11) |
| Overture places | `maps/overture.py` | Brand/category POI tile over cached fixture | Not a live Overture download; not CDLA field truth |
| GNSS sim | `gnss/*` | ZED-F9P-class noise, canyon/cold-start dropout, TTL envelope | Parameters are *not* field-characterized (HR-3); P5 logs must retune |
| CityWalker adapter | `route_memory/citywalker.py` | Fail-closed proposer; gate default **off**; live weight path unwired; cached waypoints → `SE2Goal` | Priority below OSM until promotion; `NOASSERTION` on local ckpt; does not prove urban IL SR / Orin / +5pp (HR-13) |
| Route memory | `route_memory/memory.py` | Teach-repeat keyframes → proposals | Sim teach-repeat; not GuideNav/CosPlace field (HR-12) |
| Low-viewpoint curb gate | `low_viewpoint/gates.py` | `curb_height_map_without_d455` synthetic predicate | Sim/synthetic only (HR-4) |
| City scene | `scenes/city_block.xml`, `grid_v1` | Daily city sim + planar LiDAR occupancy | Planar scan misses curb height / drop-offs; MetaUrban not integrated |
| External maps | `NullMapProvider` / Google Maps | Explicitly disabled | Design decision: advisory placeholder, never collision or pose authority |

Product architecture already states the city-scale rule
([TARGET_ARCHITECTURE.md](../TARGET_ARCHITECTURE.md) §City-scale scope;
[README.md](../README.md) card **P4-E**): Phase 1 is local mapped/observable
navigation; later `GEO → MAP → ODOM` handoff may use external maps only as
advisory nominees. That rule is correct and should not be weakened by N8
research enthusiasm.

---

## 3. OSM / Overture: topological prior, not sidewalk meter

### What the literature and OSM practice say

1. **OSM is not a ready robot graph.** Ways and tags must be preprocessed into
   a connected directed graph; sidewalks tagged only as attributes on
   carriageways often need materialization into separate footways; plazas need
   virtual edges. Stahr et al. (Robotics 2023) document exactly these
   inconsistencies for an assistive sidewalk robot and publish an OSM→graph
   preprocessing pipeline ([MDPI Robotics](https://doi.org/10.3390/robotics12040113)).

2. **Prefer separate sidewalk geometries for robotics.** OSM wiki
   ([Sidewalks](https://wiki.openstreetmap.org/wiki/Sidewalks),
   [Guidelines for pedestrian navigation](https://wiki.openstreetmap.org/wiki/Guidelines_for_pedestrian_navigation))
   distinguishes attribute-on-road (`sidewalk=left/right/both`) vs distinct
   `highway=footway` + `footway=sidewalk`. Separate ways allow `kerb=*`,
   `tactile_paving=*`, surface, width, and barrier tags — and avoid routing
   centers on the carriageway centerline.

3. **Coverage is uneven.** OpenSidewalks / TCAT work and Overture's own notes
   show many streets lack sidewalk geometries; pedestrian routers often must
   *cost* roads higher than footways rather than ban them. That heuristic is
   unacceptable as Parcel free-space policy: an incomplete sidewalk graph must
   **not** authorize road centerlines as default traversable edges for a dog.

4. **Overture transportation** publishes global segments/connectors including
   `footway` / `sidewalk` / `pedestrian` classes built from OSM + other sources
   ([Overture transportation guide](https://docs.overturemaps.org/guides/transportation/)).
   Parcel's stub correctly uses Overture for **places** (POI), not for live
   routing. If/when transportation tiles are ingested, treat them like OSM:
   versioned graph proposal → local re-grounding → metric validation.

5. **Nav2 Route Server** is the right classical *consumer* pattern: sparse
   topological route for long distance, free-space planner for the near horizon,
   last-mile gap filled by local planning
   ([nav2_route](https://docs.nav2.org/configuration/packages/configuring-route-server.html)).
   Upstream loads GeoJSON graphs today; OSM is a requested/plugin-facing
   conversion problem, not a drop-in. Parcel's `OsmWaypointProposer` is a thin
   cousin of that idea and should eventually emit into the same `NavProposalV1`
   ABI as CityWalker / route memory — never into Sport velocity.

### Parcel implication

Keep and harden the cached footway graph:

- **Allowed edges for autonomous motion:** footway / path / pedestrian /
  sidewalk only.
- **Crossing edges:** only under an authenticated, authorized owner/control-
  channel crossing decision bound to the current task/revision and TTL; a
  transcript alone cannot mint it (`maps/crossing.py`).
- **Road keepouts:** hard geofence in metric frame after localization exists;
  OSM polygon is a *seed*, not a free-space certificate.
- Live `osmnx` refresh stays offline-fail-closed (already coded).
- Do not treat Google Maps / network turn-by-turn as anything more than a
  disabled advisory placeholder until an explicit product decision + legal
  review; even then it remains nomination-only.

**Confidence:** high for the advisory-graph pattern; medium for eventual
live-tile freshness/versioning until P4-E.

---

## 4. GNSS: absolute GEO correction, not curb-line localization

### What the literature says

- Open-sky GNSS-RTK can be centimeter-class; **urban canyons** routinely
  produce multipath / NLOS errors of **many meters to >10 m** on commercial
  receivers (UrbanNav / Hong Kong reports; GPS World roundups).
- Credible robotics practice is **selective fusion**: LiDAR–inertial odometry
  for continuous local pose; admit GNSS only when sky-mask / elevation /
  quality gates say the fix is trustworthy; otherwise coast on LIO
  ([Wen/Hsu-style GNSS-RTK + LIO](https://doi.org/10.3390/app12105193);
  [factor-graph raw GNSS + IMU ± LiDAR](https://arxiv.org/abs/2209.14649)).
- Even strong tightly coupled systems often report **sub-meter to 1–2 m**
  global accuracy in hard urban settings — enough to initialize a map frame or
  correct drift, **not** enough to decide “am I on the sidewalk or the road”
  for a ~0.3–0.4 m wide Go2 body without local sensors.

### Parcel implication

Parcel's sim GNSS model (dropout windows, inflated post-dropout covariance,
1 s TTL) is directionally right as a *stress model*. Promotion rules:

1. GNSS populates / corrects **GEO** and, when covariance is healthy,
   loosely couples into **MAP**.
2. Sidewalk membership and curb approach use fresh calibrated camera/LiDAR
   (and elevation) evidence in healthy MAP/ODOM — never GNSS east/north alone.
   Terminal success additionally requires same-task/revision evidence IDs,
   polygon/region clearance, an agent-issued exact-zero stop, settled
   feedback for the hold, and no active collision/person brake.
3. Stale, high-covariance, or dropped GNSS → hold absolute correction; do
   **not** open-loop translate from a stale GEO goal.
4. Field retune against recorded ZED-F9P (or chosen receiver) sidewalk logs
   before any outdoor HIL claim (HR-3).

**Confidence:** high that GNSS cannot be sidewalk authority; medium on exact
receiver/fusion stack until commissioning.

---

## 5. CityWalker: urban prior, not city brain

### Primary source (CVPR 2025)

[CityWalker: Learning Embodied Urban Navigation from Web-Scale Videos](https://openaccess.thecvf.com/content/CVPR2025/html/Liu_CityWalker_Learning_Embodied_Urban_Navigation_from_Web-Scale_Videos_CVPR_2025_paper.html)
([code](https://github.com/ai4ce/CityWalker), Apache-2.0 project;
[project page](https://ai4ce.github.io/CityWalker/)).

- Trains on **2000+ hours** of web city walking/driving video; VO pseudo-labels
  supply action supervision (no proprietary VLM labeling at scale).
- Input: past RGB frames, past trajectory, target coordinate → transformer →
  future waypoints + arrival head.
- Explicit framing: Google Maps / GPS waypoints for *high-level* goals;
  learned policy for *between-waypoint* urban behavior (sidewalk norms,
  crossings, crowds).
- Author-reported real-world Go1 success **77.3%** fine-tuned vs ViNT† 57.1% /
  NoMaD∗ 42.9% on their NYC trials (50–100 m goals; human interrupt = fail).
  Offline critical-scenario arrival for fine-tuned CityWalker is high
  (Table 1) but is **not** a Parcel product metric.
- Embodiments: human walking → quadruped transfer with small expert fine-tune;
  driving+walking mix helps. Feature-hallucination loss interacts with
  embodiment gap.

### Parcel wiring (already correct in shape)

- Local artifact: `models/nav/citywalker/CityWalker_2000hr.ckpt` +
  `third_party/CityWalker` present; adapter gate **disabled** by default.
- Emits `SE2Goal` only; max step clamp; priority below OSM until earned.
- Live torch inference **not wired** (honest skip); cached offline path for
  A/B.
- License hygiene: local scanner `NOASSERTION` vs HF Apache-2.0 converted
  weights — **do not assume equivalence**; pin hash, review
  `trust_remote_code`, sandbox out of control process
  ([SOURCE_LEDGER.md](../SOURCE_LEDGER.md),
  [MODEL_AND_RL_DECISION.md](../MODEL_AND_RL_DECISION.md)).

### Role recommendation

| CityWalker may | CityWalker must not |
| --- | --- |
| Propose short relative XY waypoints toward a metric/topological goal | Emit Sport / HAL velocity |
| Act as urban traversability / detour prior in shadow A/B vs OSM-graph-only | Declare arrival, free space, or road-crossing authorization |
| Compete in P4-B local-policy shadows after sandbox | Own language, owner identity, or social distance |
| Fail closed on missing vendor/weights/torch | Bypass proximity/TTC or curb-stop |

Compare against OSM-graph-only and against classical Nav2 (once P2-A lands)
on the **same** frozen episodes. Author 77.3% is Go1 + their PD wrapper +
their interrupt policy — cite only as literature, never as Parcel readiness.

**Confidence:** medium for usefulness as prior (architecture fit is good);
low for onboard Orin latency until measured; high that it must stay proposers.

---

## 6. Sidewalk / curb: where metric authority lives

### Sensing (what works outdoors)

1. **Elevation / DEM from LiDAR or depth** remains the most reliable curb
   cue: height discontinuities between road and sidewalk planes
   ([Road Curb Detection survey](https://doi.org/10.3390/s21216952);
   altitude-difference / ADI curb work; wheelchair RGB-D plane extraction).
2. **Semantic segmentation** (road / sidewalk / curb / grass) is complementary
   soft evidence — useful for “walk to the sidewalk” grounding, dangerous as
   sole free-space.
3. **Planar 2-D LiDAR alone is insufficient** for curb height and drop-offs;
   Parcel's own city doc already flags this. elevation_mapping_cupy (or
   equivalent robot-centric elevation) is the right challenger for legged
   outdoor terrain ([SOURCE_LEDGER](../SOURCE_LEDGER.md)).
4. **Low dog mount (~35 cm)** hurts OCR and storefronts and changes curb
   appearance; Parcel's synthetic curb-without-D455 gate is a placeholder for
   a real height-map + depth-dropout test, not evidence.

### Policy (Parcel already has the right social contract)

Crossing policy is intentionally **conservative companion law**:

```text
sidewalk → approach curb → STOP + announce → authenticated,
authorized owner/control-channel crossing decision (never transcript alone) →
authorized crossing TTL → metric monitor still owns collision stop
```

Zero autonomous road entry. Voice never overrides an unconditional proximity
stop. That matches last-mile delivery and companion ethics better than
CityWalker's learned “crossing” behaviors, which optimize imitation success,
not Parcel's fail-closed ODD.

### Instruction grounding

“Go to the sidewalk” / “wait at the curb” require:

- typed region hypotheses from fast semantics + geometry;
- independent terminal witnesses (`inside` / `near` curb line) from fresh,
  calibrated sensors plus healthy pose/transforms, agent-issued stop, and
  settled feedback;
- OSM region hints only as priors to search/score.

Do not mark success from simulator object IDs or from GNSS proximity to an
OSM node.

**Confidence:** high for policy; medium for sensor stack selection until
mounted Go2 data.

---

## 7. Map advisory vs metric — the contract

This is the N8 hard recommendation. Encode it as an ABI rule, not a comment.

### Definitions

| Class | Examples | May decide |
| --- | --- | --- |
| **Advisory / nomination** | OSM/Overture graph, Google/network route (if ever enabled), CityWalker waypoints, route-memory replay, POI tiles, GNSS GEO hint | Candidate goals, corridor preferences, long-horizon order of nodes, search bias |
| **Metric authority** | Calibrated camera/depth + LiDAR (+ elevation) local geometry, MAP/ODOM pose with covariance/health, footprint inflation, collision/TTC monitor, curb height map | Free space, stop, road entry veto, curb-stop trigger, terminal success |

### Invariants

1. Advisory outputs are `NavProposalV1` (or today's `SE2Goal`) with source,
   frame, timestamp, TTL, confidence, and observation IDs.
2. Expired, low-confidence, or frame-mismatched proposals are dropped and
   default to exact-zero HOLD. An existing classical goal may continue only
   when it is independently grounded, current for the same authorized
   task/revision, and every evidence/frame/pose/metric-geometry gate is fresh
   and healthy; admission and the final metric veto run again. Never fall back
   to open-loop GEO.
3. External maps never set occupancy cells to free.
4. Arrival / “on sidewalk” / “at curb” predicates re-observe metric evidence.
5. Crossing authorization is a **task/policy** bit, not a map edge property
   the proposer can flip.
6. When advisory and metric conflict, metric wins; log the disagreement for
   eval (map error vs perception error attribution).

This matches existing design decisions (Google Maps advisory-only) and the
sprint board's P4-E “external maps remain advisory.”

---

## 8. Evaluation and simulation for outdoor claims

| Substrate | Use | Do not claim |
| --- | --- | --- |
| Parcel `city_block` + pedestrian scripts | Product-path curb-stop, sidewalk instructions, OSM vs CityWalker A/B scaffolding | Field localization or curb physics |
| MetaUrban (ICLR 2025) | Dynamic sidewalk micromobility stress; social/point nav | Go2 Sport safety or Parcel voice stack (adapter must not rewrite product behavior) |
| CityWalker offline/real author suites | Literature baseline for visual urban priors | Parcel promotion score |
| Supervised outdoor HIL courses (P5) | Only credible outdoor certificate | — |

MetaUrban is the strongest *dynamic city* stress lane once an observation /
action adapter exists; Parcel's `MetaUrbanNavEnv(use_metaurban=True)` is still
`NotImplementedError`. Prefer adapter-only integration per evaluation policy.

---

## 9. Recommended Parcel ordering (city outdoor)

Aligned with the sprint board; N8-specific emphasis:

### Phase A — freeze honesty (now)

1. Keep CityWalker gate off. The local bytes match the official v1.0 asset;
   finish original-asset license-scope and loader review before any shadow
   enable.
2. Keep OSM fixture + crossing policy as CI contract tests; label ENU as sim.
3. Do not enable Google Maps or live OSM network in the control path.

### Phase B — local metric outdoor prerequisites (before city claims)

1. Real MAP/ODOM localization with covariance (P1-B) — GNSS as optional GEO
   factor later.
2. Sidewalk/road/curb perception: elevation layer + fast semantics; planar
   LiDAR insufficient alone.
3. Quadruped curb/slope/slip physics harness (P4-D) before outdoor HIL.
4. Promote curb-stop from authored nodes to sensor-triggered curb lines while
   preserving authenticated, authorized crossing decisions; speech
   recognition by itself remains untrusted evidence, not authority.

### Phase C — advisory city handoff (P4-E, later)

1. Versioned `GEO → MAP` transform + route-graph freshness.
2. OSM/Overture graph → Nav2 Route (or Parcel route service) → local free-space
   planner → independent collision monitor.
3. CityWalker shadow A/B vs OSM-only (ADJUDICATION D7 / P4 binding) under
   identical episodes; promotion only on collision-safe, latency-safe gains.
4. Optional teach-repeat route memory for known neighborhoods as another
   proposer, same ABI.

### Explicit no-gos

- End-to-end CityWalker → Sport.
- GNSS-only sidewalk following.
- Autonomous road entry from learned “crossing” behavior.
- Treating author-reported 77.3% or MetaUrban RL scores as Parcel safety
  evidence.

---

## 10. Cross-links to other wave IDs

| Sibling | Handoff |
| --- | --- |
| N1 / classical | Nav2 Route + free-space for last mile; Parcel metric monitor after smoother |
| N4 / models | CityWalker license, sandbox, role matrix |
| N5 / perception | elevation, sidewalk semantics, MAP/ODOM, GNSS fusion |
| N6 / social | sidewalk context as soft cost; road as hard keepout |
| N7 / eval | adapters only; outdoor HIL separate from sim scores |
| RL1/RL2 | no custom city RL until residual survives OSM + CityWalker + Nav2 shadows |

---

## 11. Primary sources consulted

### Papers / project pages

- Liu et al., *CityWalker*, CVPR 2025 —
  https://openaccess.thecvf.com/content/CVPR2025/html/Liu_CityWalker_Learning_Embodied_Urban_Navigation_from_Web-Scale_Videos_CVPR_2025_paper.html
- CityWalker code / page — https://github.com/ai4ce/CityWalker ,
  https://ai4ce.github.io/CityWalker/
- Stahr et al., OSM path planning for assistive robot, *Robotics* 2023 —
  https://doi.org/10.3390/robotics12040113
- GNSS-RTK + LIO urban canyon — https://doi.org/10.3390/app12105193 ;
  https://www.gpsworld.com/research-roundup-gnss-in-urban-canyons/
- Factor-graph raw GNSS + IMU ± LiDAR — https://arxiv.org/abs/2209.14649
- Road curb detection survey — https://doi.org/10.3390/s21216952
- MetaUrban — https://metadriverse.github.io/metaurban/ , ICLR 2025

### Specs / docs

- OSM Sidewalks & pedestrian navigation guidelines (wiki)
- Overture Maps transportation theme —
  https://docs.overturemaps.org/guides/transportation/
- Nav2 Route Server —
  https://docs.nav2.org/configuration/packages/configuring-route-server.html

### Parcel internals

- `src/parcel_robot/maps/{graph,waypoints,crossing,overture}.py`
- `src/parcel_robot/gnss/*`
- `src/parcel_robot/route_memory/{citywalker,memory}.py`
- `src/parcel_robot/low_viewpoint/gates.py`
- `docs/NAVIGATION_CITY.md`, `docs/DESIGN_DECISIONS.md`
- Sprint docs: `TARGET_ARCHITECTURE.md`, `MODEL_AND_RL_DECISION.md`,
  `SOURCE_LEDGER.md`, `README.md` (P4-B / P4-E)

---

## 12. Confidence and `does_not_prove`

| Claim | Confidence | Does not prove |
| --- | --- | --- |
| External maps/GNSS/CityWalker must stay advisory | **high** | — |
| Separate OSM footways + authenticated, authorized crossing decisions are the right graph policy | **high** | Live city coverage quality and speaker/channel authorization |
| GNSS cannot decide sidewalk membership in urban canyons | **high** | Exact Parcel receiver accuracy |
| CityWalker is the cheapest urban visual prior to shadow | **medium** | Orin FPS, collision rate on Parcel ODD, original-asset license scope (byte identity is verified) |
| Elevation + semantics beat planar LiDAR for curbs | **high** (literature) | Parcel mount geometry |
| P4-E city handoff should wait on local localization + curb physics | **high** | Calendar date for outdoor ODD |

**Bottom line for the thesis synthesis:** Parcel's city outdoor path is
*hierarchical nomination + metric veto*, not map-free end-to-end navigation and
not HD-map autonomy. CityWalker and OSM earn their keep only as replaceable
proposers under that veto.
