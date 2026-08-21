# Ground-truth dependency ledger — `navigate_to` live path

**Scope:** read-only trace of the deployed chain `tool_broker._navigate_to → runtime._realtime_navigate → DeterministicIntentRouter → admit_navigation_place → goals.semantic_goal_from_directive → DirectiveNavigator (pipeline.py) → arrival`. All paths are absolute under `/home/jaewoo-jang/Desktop/Projects/Parcel/`. No files written to the repo; no ci_gate, no seeds, no POSTs.

---

## 0. The chain, and exactly where truth enters

| Hop | File:line | Truth consulted |
|---|---|---|
| Hosted tool arrives | `src/parcel_robot/realtime/tool_broker.py:882` `_navigate_to` | — |
| R10 place-noun gate | `tool_broker.py:895` `self._doors.places()` | **GT-4** (scene vocabulary) |
| Door → runtime | `src/parcel_robot/runtime.py:7157` `_realtime_navigate` | — |
| R20 unknown-place gate | `runtime.py:7231` → `runtime.py:6940` `_place_admission` → `src/parcel_robot/navigation/goals.py:510` `admit_navigation_place` | **GT-4, GT-5** |
| Router (shape only) | `runtime.py:7233` `agent.intent_router.route(...)` | none — grammar is shape-only, which is *why* R20 exists |
| Relation hint validation | `runtime.py:7270-7277` `_realtime_scene_vocabulary()` + `_place_matches` → `navigation/arrival_semantics.py:418` `resolve_relation` | **GT-4, GT-7** |
| Goal compilation | `goals.py:302` `semantic_goal_from_directive` → `arrival_semantics.py:307` `classify_place` | **GT-5, GT-6** |
| Mission parse | `navigation/pipeline.py:996` `parse` → `pipeline.py:1000` `self.grounder.ground(directive)` **first** | **GT-8** (POI YAML, absolute coords) |
| Semantic search | `pipeline.py:1007` fallback → `runtime.py:8793` `extras["semantic_candidates"]` → `navigation/semantic_map.py:82` | **GT-1** |
| Grounding | `navigation/semantic_map.py:57` `ObservationSemanticMap.query` / `pipeline.py:3551` `GrounderV2` | **GT-1, GT-5** |
| Commit | `pipeline.py:3086-3088` `support_polygon`, `arrival_goal_region` | **GT-2, GT-3** |
| Arrival | `pipeline.py:5888` `_inside_arrival_goal_region`, `pipeline.py:5846` `_on_support_surface` | **GT-2, GT-3** |
| Narration | `runtime.py:10289-10302` → `arrival_semantics.py:511` `arrival_fact` | **GT-4, GT-6** |

**Correction to the brief's framing:** `evals/nav_instruct/scene_truth.json` is **not** on the live path. `grep` finds zero importers under `src/`; it is a generated eval artifact with a pinned `derived` vs `transcribed` delta set (`evals/nav_instruct/scene_truth.py:1-40`). "Go to the sidewalk" resolves against **MuJoCo geom-name prefix matching**, not against `scene_truth.json`. That distinction matters for scoping: the cutover target is `city_semantics.py`, not the eval artifact.

---

## 1. The ledger, ranked hardest → easiest to replace

### GT-1 — The semantic channel itself: geom names → labeled instances ⚠️ ROOT
**`src/parcel_robot/city_semantics.py:45-133`** (`extract_city_semantics`), **`:224-228`** (`_match_prefix`), **`:136-170`** (`visible_city_semantics`), **`:294-301`** (`_visible_payload`).
Wired at **`src/parcel_robot/sim.py:204`** (extract once at model load) and **`sim.py:300-306`**, published as `semantic_regions` / `semantic_objects` at **`sim.py:337-338`**, validated into `SimObservation` at **`src/parcel_robot/backends/mujoco.py:106-121, 162-165`**.

*Provides:* it iterates `model.ngeom`, reads `mujoco.mj_id2name(...)`, matches the **name prefix** against the sidecar's tables, and emits, per instance: a class **label**, a stable **instance id**, exact **metric geometry** (region polygon from `geom_pos`±`geom_size`; object position = mean of part geoms; radius from `_geom_radius_m`, `:256-264`), and a hardcoded `"confidence": 0.98, "source": "simulator_semantic_camera", "reachable": True`.

*Class:* **(a) replaceable by perception — and it is the whole cutover.** It is the root because it bundles four separable capabilities that deployment must supply from four different mechanisms: recognition (open-vocab detector), instance segmentation/association (tracker), metric localization (depth back-projection), and traversability (`reachable`). Note the `reachable: True` literal — nothing today ever says a place is unreachable.

*Assets already in place:* `detection_adapter/perception_chain.py` is already the single ingress (`semantic_map.py:122-131`) but ships at tier **T0 = identity pass-through** (`perception_chain.py:53-70`, `configs/navigation/default.yaml:60`). `REGISTERED_TIERS` is `("T0","T1")` and the module states plainly that **no T-CAM tier exists**: "Registering a real `T-CAM` tier means giving it a `NoiseTier` whose candidates come from rendered pixels rather than the GT oracle `_lift` reads — a wiring card, not a rename" (`perception_chain.py:60-69`). The pixel path exists in parallel and is flag-gated: `runtime.py:8825` `_semantic_candidates` prefers `camera_channel.ingress` candidates when `PARCEL_CAMERA_INGRESS` is on, else returns the oracle read. **That flag is the cutover switch.**

*Difficulty:* **10/10.** Everything else in this ledger is downstream of it.

---

### GT-2 — Region polygons as goals *and* as the K0 arrival authority
**`city_semantics.py:179-194`** `_region_metadata` attaches `goal_region: {kind: "polygon", polygon: <MJCF box footprint>}`, `arrival_radius_m: 0.12`, `terminal_clearance_m: 0.32`, `target_obstacle_clearance_m: 1.30`.
Consumed at **`pipeline.py:6000-6021`** `_build_arrival_goal_region` (from `result.polygon` + `metadata["radius_m"]`), stored at **`pipeline.py:3087`**, verified at **`pipeline.py:5888+`** `_inside_arrival_goal_region` and **`pipeline.py:5670-5702`**.

*Provides:* the literal answer to "am I standing inside the sidewalk" — a rectangle transcribed from a MuJoCo box, with sub-centimetre boundaries and no uncertainty.

*Class:* **(a)+(b).** The polygon must become a *perceived and remembered* traversable-surface map (ground-plane segmentation + accumulation into an occupancy/semantic layer), not a single-frame detection — a sidewalk extends far beyond any one frame.

*Note worth carrying:* the same metadata dict is stamped `"diagnostics_only": True` (`city_semantics.py:181`), and `perception.PerceptionContract` reports `reasoning_visibility.simulator_ground_truth: False` (`src/parcel_robot/perception.py:58-66`). Mechanically that is not what happens: the polygon in that "diagnostics-only" dict **is** the arrival authority. The flag describes the coordinates, not the derived geometry riding alongside them.

*Difficulty:* **9/10.**

---

### GT-3 — Object near-bands, stand-offs, and support surfaces
**`city_semantics.py:197-221`** `_object_metadata` — `radius_m`, `stand_off_m`, `minimum_vicinity_radius_m`, `vicinity_radius_m` (from `instructnav.scoring.object_near_envelope_m`), `target_min_surface_clearance_m`, `terminal_support_clearance_m`.
**`city_semantics.py:105-117`** computes `support_label`/`support_polygon` by point-in-polygon of the object centre against the sidewalk region.
Consumed at **`pipeline.py:3086`**, gating near-arrival at **`pipeline.py:5846-5864`** `_on_support_surface` and **`pipeline.py:5698-5701`** (`arrival_not_verified_reason = "outside_support_polygon"`).

*Provides:* how big the thing is, how far to stop from it, and what ground you must be standing on to count as arrived.

*Class:* **(a).** Radius/stand-off come free from a depth-localized detection with covariance (`detection_adapter/pixel_detections.py` already emits a position covariance). `support_polygon` is the harder half — it is a *relation between two perceived things* and needs the surface map from GT-2.

*Difficulty:* **8/10.**

---

### GT-4 — The place vocabulary the hosted lane is validated against
**`runtime.py:6884-6936`** `_realtime_places` — union of (i) every label in `observation.semantic_regions`/`semantic_objects` sorted nearest-first (`:6913-6926`), and (ii) **`city_semantics.CLASS_ALIASES`**, i.e. the sidecar's entire declared class list (`runtime.py:6932`).
**`runtime.py:7328-7353`** `_realtime_scene_vocabulary` — same, plus `scene_semantics().classes` names **and aliases** (`:7345-7351`).
Consumed by `tool_broker.py:895` (R10 refusal + `valid_places` returned to the model), `runtime.py:6966-6968` → `goals.py:510-567` (R20 admission), and `runtime.py:10290` (arrival narration).

*Provides:* "is this a place I could be asked to walk to", and the offer list in a refusal ("the ones I do know nearby are…").

*Class:* **(b) replaceable by learned/remembered map**, for the observed half; **(c) genuinely external**, for the "I know how to look for a door even though I can't see one" half. Today arm (ii) is a *closed class list*; an open-vocabulary detector has no such list. The replacement is two-sourced: a **place memory** (things seen before, with poses) for the offer list, plus a **detector-prompt-able open vocabulary** for admission. `scene_semantics.detector_query_set()` (`scene_semantics.py:161-176`) was built precisely as this seam and its docstring says the detector-prompt consumer "does not exist in the tree yet".

*Fail-open behaviour to preserve:* both gates deliberately admit everything on an empty vocabulary (`goals.py:526-531, 563-564`, reason `no_vocabulary`). Under perception, "empty" stops being a config error and becomes the normal cold-start state — the fail-open needs re-deciding, not just re-plumbing.

*Difficulty:* **8/10.**

---

### GT-5 — The per-scene semantics sidecar
**`src/parcel_robot/scene_semantics.py:42`** `DEFAULT_SIDECAR = "configs/scenes/city_block.semantics.yaml"`, process-cached at **`:192-196`**. Parsed fail-closed (`:199-239`); prefix-ordering rules enforced at **`:348-362`**.
The file itself (`configs/scenes/city_block.semantics.yaml`) declares 9 classes with `geom_prefixes` / `region_prefixes` / `aliases` / `affordances` / `landmark_roles` / `size.source`.

*Provides:* four different things, which must be split for the cutover:

| Field | Class | Why |
|---|---|---|
| `geom_prefixes`, `region_prefixes` | **(d) sim-only scaffolding** | a D455 frame has no geom names. Delete at cutover; nothing replaces them. |
| `aliases` (`pavement`→sidewalk, `street light`→lamppost) | **(c) external** | real linguistic knowledge; belongs in an ontology/embedding, not a per-scene file. Already half-replaced: `semantic_map._matches` (`:263-269`) prefers SigLIP-2 cosine over substring when weights are present. |
| `affordances` (which relations a class supports) | **(c) external** | "you can be *inside* a sidewalk, *near* a door" is world knowledge, per-class not per-scene. |
| `landmark_roles`, `size.source` | **(c) external** | same. |

*Also note:* `door` is declared `kind: object` with the sidecar's own comment stating the schema has no `portal` kind and that the portal semantics live one layer up in `ARRIVAL_TABLE` — and that "the two disagree… the disagreement is a reported defect" (R14). That is a pre-existing, documented mismatch, not something I introduced.

*Difficulty:* **7/10** (mostly a re-homing problem, not a perception problem).

---

### GT-6 — Owner track = MuJoCo mocap, confidence 1.0
**`sim.py:283-286`** reads `data.mocap_pos[owner_mocap_id]`; **`sim.py:288`** `owner_is_visible = owner_visible and owner_mocap_id >= 0`; `owner_visible` is a socket-settable boolean (`sim.py:149`, `sim.py:453`) — a test knob, not a sensor. Published with `"confidence": 1.0 if visible else 0.0` (`sim.py:334`).
Consumed everywhere the owner is a goal: `goals.OWNER_REFERENT_TABLE` (`goals.py:376-388`) routes "go to me" to the approach lane, `admit_navigation_place` short-circuits it (`goals.py:552-557`), `follow.py`, `search_owner.py`, `proxemic_approach.py`, `arrival_semantics.CLASS_PERSON`.

*Class:* **(a).** Person re-ID + tracking. Seams already exist and are explicitly stubs: `src/parcel_robot/uwb/fusion.py` ("no Kalman / IMM here — stub"), `models/speaker_id`, and the `OwnerTrackV1` contract that is already channel-agnostic.

*Difficulty:* **7/10** — high because losing the owner is a *behaviour* problem, not just a data problem: today `visible=False` never happens by accident.

---

### GT-7 — Dynamic-agent tracks: scripted mocap with a `kind` string
**`src/parcel_robot/dynamic_city.py:87, 150-153`** — each actor's snapshot carries exact `x, y, vx, vy, radius_m` and `kind` straight from its spec. Published at `sim.py:339`.
Consumed by: **`runtime.py:908-911`** `_is_person_track` (trusts `kind ∈ {person, pedestrian, human}` verbatim), **`dynamic_city.py:236-241`** `select_social_collision_candidate`, `navigation/yield_aside.py:507+`, `navigation/person_keepout.py`, `navigation/traffic_aware.py:tracks_from_payload`, and the R18 scene block (`runtime.py:761+` `scene_report`).

*Class:* **(a), and the highest-safety-value item in the ledger.** Real deployment must produce: person detection, data association across frames, **velocity estimation** (today handed over exactly), and a radius. The yield/keepout/TTC policies all consume `vx, vy` as if noiseless — `dynamic_city.circle_contact_ttc` solves a quadratic on exact relative velocity (`dynamic_city.py:180-217`).

*Difficulty:* **7/10** to produce; **9/10** to produce *well enough that the existing safety envelopes still hold*, because the envelopes were tuned against zero-variance tracks.

---

### GT-8 — Robot pose = `data.qpos` (perfect localization)
**`sim.py:283-286, 316-322`** → `SimObservation.robot` (`backends/base.py:9-14, 75`). `src/parcel_robot/pose.py:904-944` `observation_pose` is the sanctioned seam, but resolution step 3 falls back to "the observation's own truth fields, which is *exactly* `TruthPoseProvider` semantics" (`pose.py:911-914`). MAP == ODOM == truth today; `accuracy_m` is reported as a flat `0.05` for the mujoco backend (`runtime.py:5544`).

*Class:* **(b) replaceable by learned/remembered map** — SLAM/VIO. Stratum 1 already landed the seam, the frame discipline, `DriftingOdomProvider`, and chance-constrained polygon membership (`pipeline.py:5683` `p_inside_polygon`, `inside_probability_threshold`), so the *consumers* are ready. What is missing is a localizer.

*Difficulty:* **7/10** — well-scoped, well-seamed, but it is real SLAM.

---

### GT-9 — The POI grounder: hardcoded absolute coordinates + street names ⚠️ FIRES FIRST
**`src/parcel_robot/navigation/grounder.py:12-70`** `PlaceGrounder`, loaded from `configs/navigation/cities/demo_pois.yaml` at **`pipeline.py:825-834`** (default path `configs/navigation/default.yaml:10`). Live on the runtime path: `skills/api.py:146-148` constructs `DirectiveNavigator.from_config`, `skills/api.py:209` calls `nav.start(directive)`, `pipeline.py:1000-1006` tries `self.grounder.ground(directive)` **before** any semantic search and tags the mission `goal_source: "known_poi"`.

*Provides:* absolute `(x, y, heading)` for `coffee shop at 42nd street` `[42.0, 8.5]`, `bookstore` `[12.0, -3.0]`, `park` `[-5.0, 20.0]`, `crosswalk` `[3.5, -0.6]`, plus `street:` and `category:` fields.

*Class:* **(c) genuinely needs an external source** for street names, business names and brands; **(b)** for the coordinates. This is the Overture/OSM slot, and the assets are already cached: `maps/overture_places_v1.json`, `maps/neighborhood_v1.json` (nodes/edges/curbs/road_keepout), `src/parcel_robot/maps/{graph,overture,crossing,waypoints}.py`. **However** — `grep` shows nothing outside `src/parcel_robot/maps/` imports that package, so the P3 city layer is built and parked, not wired.

*Live-path consequence worth flagging:* the POI table contains `crosswalk`, so any directive containing that word grounds to the static `[3.5, -0.6]` POI and **never reaches the perception path at all**. The YAML's own header says "Expand when a real city map is wired."

*Difficulty:* **6/10** — mostly a wiring + data-licensing problem, and the replacement layer already exists offline.

---

### GT-10 — LiDAR obstacle set built from a geom-**name** whitelist
**`sim.py:38-51`** `LOGICAL_OBSTACLE_PREFIXES = ("obstacle_", "bldg_", "bench_", "owner_", "pedestrian_", "cyclist_", "planter_", "tree_", "lamp_", "signal_")` + `is_logical_obstacle_name`; **`sim.py:200-203`** builds `obstacle_geom_ids` by name; **`mujoco_lidar.py:36`** `scan_mujoco_lidar` computes analytic closest surface points over *only those* geoms and returns `obstacle_id` = the geom name. Published as `lidar_obstacles` / `nearest_obstacle` (`sim.py:337-338`) — the input to the brake (`navigation/reactive_safety.py:285`) and `runtime`'s independent final stop.

*Two distinct problems:*
1. **Whitelist:** a geom whose name is not on the list is invisible to the `nearest_obstacle` channel entirely. `entry_wall_1/2` (R14) and `window_*`, `curb` are exactly such geoms.
2. **Id join:** `obstacle_id` used to be joined to `candidate_id` to answer "is this return the target". Stratum 2 **already deleted** that join — `pipeline.py:6473-6481` documents the deletion and `pipeline.py:2033-2046` `_control_observation` now answers geometrically. `associated_lidar_ids` survives as telemetry only (`city_semantics.py:114`, `pipeline.py:3038`).

*Class:* **(d)** for the ids (already retired); **(a)** for the whitelist — a real sensor returns everything and the filtering must become semantic.

*Note:* `docs/HARDWARE_PORTABILITY_AUDIT.md` still lists `navigation/pipeline.py:445` as "relational-goal terminal approach keys on MuJoCo geom names stamped onto lidar returns (oracle leak that hits ANY real hardware)". That audit line predates the Stratum-2 deletion above; the leak is narrower now than the doc claims.

*Difficulty:* **4/10.**

---

### GT-11 — Frontier search priors keyed on ground-truth class names
**`src/parcel_robot/instructnav/search_entity.py:18-30`** `SIDEWALK_BORDERS_ROAD_PRIORS` (`sidewalk: 0.95 … road: 0.08`), **`:114-140`** `semantic_prior_for_label` with a hand synonym map. Used at **`navigation/instructnav_recovery.py:280`**.

*Class:* **(c)** — a semantic co-occurrence prior is legitimate deployable knowledge (it is VLFM's own device). What must change is only the **key space**: today it is keyed on labels the oracle guarantees; under a detector the same table must tolerate misses and low-confidence labels.

*Difficulty:* **3/10.**

---

### GT-12 — The visibility/frustum model
**`city_semantics.py:143-144`** `max_range_m=12.0`, `half_fov_rad=radians(70.0)`; `_visible` (`:304-314`) is pure range+bearing with **no occlusion test**.
Real geometry already lives in the tree: `camera_channel/d455.py:15-25` — 1280×720, fx/fy 644, and a practical depth band of **0.4–6.0 m**.

*Class:* **(d) sim-only scaffolding.** The oracle frustum is 2× the D455's usable depth range, has a wider half-FOV than the sensor's vertical coverage, and sees through walls. Post-cutover the frustum stops being a parameter — visibility becomes whatever `localize_frame` returns.

*Difficulty:* **2/10** to delete; the *consequence* (roughly halved effective sighting range, plus occlusion) will move every search/recovery budget in `configs/navigation/default.yaml`.

---

### GT-13 — Language word tables (`classify_place`) and `region_support`
**`arrival_semantics.py:307-370`** `classify_place`, using `PORTAL_WORDS` (`:217-230`), `EXTRA_REGION_WORDS` (`:235-251`), `PERSON_WORDS` (`:255-265`), `_MODIFIERS` (`:269-304`), plus `goals._REGION_WORDS` (`goals.py:21-30`).
**`runtime.py:969-986`** `_place_matches` supplies `region_support` at `runtime.py:7275`, gating the hosted relation hint in `resolve_relation` (`arrival_semantics.py:470-482`).

*Class:* **mostly survives.** The word tables classify the *owner's phrase*, not the world — they are language knowledge and are deployment-portable as written. Only the injected `region_labels`/`object_labels` (GT-4) are ground-truth-derived. The `region_support` evidence gate is the one line that becomes materially weaker: "the local map has a polygon for this" degrades from certainty to a probability.

*Difficulty:* **2/10**, but it is where the honesty story changes: `resolve_relation`'s refusal reason `relation_hint_unsupported_by_local_map` will start firing constantly in a world the robot has not mapped yet.

---

### GT-14 — What the robot *says* it perceives
**`runtime.py:686`** `SCENE_SENSORS = ("lidar", "semantic_map", "person_tracks")`; **`runtime.py:695-699`** `SCENE_HONESTY_NOTE` = "these came from LiDAR ranges and a semantic map, not from a camera: **the robot has no eyes**, so … never describe colours, faces, text, or how anything looks"; **`runtime.py:684`** `SCENE_UNLABELLED`; **`runtime.py:5547-5561`** `_scene_context` publishes `visible_semantic_labels` from `semantic_regions`.

*Class:* **(d)**, but it is a **live-path string that becomes false at the moment of cutover.** Once `PARCEL_CAMERA_INGRESS` is on and the source is `pixel_detections`, the robot *does* have eyes, and this note actively instructs the hosted model to deny a capability it now has. It should be part of the cutover checklist, not discovered afterwards.

*Difficulty:* **1/10** to change; easy to forget.

---

### GT-15 — `evals/nav_instruct/scene_truth.json`
**`evals/nav_instruct/scene_truth.py:1-40`**, artifact at `evals/nav_instruct/scene_truth.json`. Zero importers under `src/`.

*Class:* **(d) sim-only scaffolding with no deployment analogue.** It is a *scorer's* copy of derived geometry, carrying a pinned `transcription_deltas` set so a scene edit that moves eval goals is a red build. Leave it alone; it does not need replacing, it needs to stop being cited as a live dependency.

*Difficulty:* **0/10.**

---

## 2. What the MuJoCo backend actually exposes as "perception" today

Full contract: `src/parcel_robot/backends/base.py:73-100` (`SimObservation`); producer `sim.py:265-345` (`state_snapshot`); validator `backends/mujoco.py:55-170`.

| Channel | Field(s) | How it's produced | Honest? | Go2 + D455 analogue |
|---|---|---|---|---|
| **Planar LiDAR scan** | `lidar_ranges`, `lidar_angle_min_rad`, `lidar_angle_increment_rad`, `lidar_range_min_m/max_m` | `mujoco_lidar.py:455-546` `raycast_planar_scan` — 360 rays via `mj_multiRay`, **occlusion-true**, self-return filtering by kinematic root, Gaussian noise σ=0.008 m, dropout 0.002, NaN = ignored vs `range_max` = free space | ✅ **Yes — a real sensor model** | ✅ **Direct.** Unitree L1 on the Go2 (a horizontal slice of it), or a 2D LiDAR. This is the one channel that needs no work. |
| **"LiDAR obstacles"** | `lidar_obstacles[]`, `nearest_obstacle_m`, `nearest_obstacle_bearing_rad`, `nearest_obstacle_id` | `mujoco_lidar.py:36-105` `scan_mujoco_lidar` — **analytic closest-surface-point per whitelisted geom**, reading ground-truth geom poses; whitelist by name (`sim.py:38-51`) | ❌ **Ground truth** (module's own comment: "read ground-truth geom poses and are kept for diagnostics/telemetry" — but the *brake* consumes it) | ⚠️ **Must be derived from the scan**, not from a separate channel. Real hardware has one range channel, not two. |
| **Semantic regions** | `semantic_regions[]` (id, label, polygon, conf 0.98) | GT-1/GT-2 — geom-name prefixes + MJCF box footprints, frustum-filtered | ❌ **Pure ground truth** | ❌ **No analogue.** Requires ground-plane/surface segmentation from D455 depth + RGB, accumulated over time. Hardest single gap. |
| **Semantic objects** | `semantic_objects[]` (id, label, position, radius, bands, support) | GT-1/GT-3 | ❌ **Pure ground truth** | ⚠️ **Buildable today**: `detection_adapter/pixel_detections.py` + `owlv2_onnx.py` (OWLv2 int8 ONNX, ~559 ms/query CPU) + `camera_channel/backends/mujoco_egl.py` → `camera_channel/ingress.py`, off the 10 Hz path. Weights absent → 2 gate tests skip. |
| **Owner track** | `owner` (id, x, y, visible, confidence) | GT-6 — mocap, conf 1.0 | ❌ **Ground truth** | ⚠️ D455 person detect + re-ID; `uwb/fusion.py` seam declared, `models/speaker_id` present. Both stubs. |
| **Dynamic agents** | `dynamic_agents[]` (id, kind, x, y, **vx, vy**, radius, yaw) | GT-7 — scripted mocap | ❌ **Ground truth incl. exact velocity** | ⚠️ D455 detect + tracker. Velocity is the hard part. |
| **Nearest person** | `nearest_person_m/bearing/id/ttc_s` | `dynamic_city.py:220-260` from the above | ❌ derived from GT | ⚠️ same |
| **Robot pose** | `robot.{x,y,z,yaw}` | GT-8 — `data.qpos` | ❌ **Ground truth** | ⚠️ Go2 leg odometry (0.5–1 %/m per `docs/STRATA_GENERALIZATION_PLAN.md`) + VIO/SLAM for MAP |
| **RGB / depth / segmentation** | **absent from `SimObservation` entirely** | rendered only inside `camera_channel/` when ingress is attached (`runtime.py:8849` `attach_camera_ingress`) | — | ✅ D455 native. **The contract has no pixel field at all** — pixels enter only as pre-digested `semantic_candidates`. |
| **Collision / e-stop** | `collision`, `emergency_stopped` | `sim.py:340-341` | ❌ `collision` is `distance ≤ 0.01` on the GT obstacle channel | ⚠️ IMU/contact-derived |

**Summary of the honest split:** exactly **one** channel on the live path is a genuine sensor model (`lidar_ranges` — occlusion-true, noisy, with dropout). Everything semantic, every person, the owner, and the robot's own pose are read from the simulator's state. `perception.PerceptionContract` (`perception.py:29-66`) advertises `spatial_sensors=("camera","lidar")` and `simulator_truth_diagnostics_only=True`; the "camera" in that tuple is `visible_city_semantics`'s frustum filter, not a camera.

---

## 3. What is already cut over, and where the switch is

The cutover is further along than the ledger suggests — the seams exist and are inert, which is the good case:

- **One semantic ingress exists** (`semantic_map.py:82-131` → `perception_chain.process`), so there is a single place to change the source.
- **The pixel path is written and flag-gated**: `runtime.py:8825-8847` `_semantic_candidates` returns pixel candidates when `PARCEL_CAMERA_INGRESS` is on and the ingress has published a frame, else the oracle. `runtime.py:8817-8823` documents `PARCEL_CAMERA_INGRESS` env-wins-over-config.
- **Real models have real ONNX loaders**: `detection_adapter/owlv2_onnx.py` (OWLv2-base-patch16-ensemble int8, Apache-2.0, no torch/no sudo), `instructnav/siglip2_onnx.py`. `semantic_map.py:263-269` already prefers SigLIP-2 cosine over substring matching **when weights are present**, with an explicit note that substring matching is what let "tree" match a lamppost via "streetlight". The 9 skipping gate tests (`tests/test_owlv2_detector.py:222,233`; `tests/test_siglip_real_embeddings.py:309,326,342`; `tests/test_p3_storefront_ocr.py:181`) are the weights gap, not a code gap.
- **The id join is already deleted** (GT-10), **the pose seam is already landed** (GT-8), **the place graph exists** (`route_memory/place_graph.py`, MAP-frame, re-anchor-aware, `waypoints_toward` refuses edges crossed by a re-anchor) but is explicitly not wired: `route_memory/runtime_hook.py:1-6` — "Does not wire into RobotRuntime by default."
- **The city/map layer exists offline and is unwired** (GT-9): `src/parcel_robot/maps/*` has zero external importers.

**The three things with no implementation at all**, in order of cost:
1. A **perceived traversable-surface / region map** (GT-2) — the only item with neither a seam nor a stub. "Inside the sidewalk" has no non-oracle answer anywhere in the tree.
2. A **person tracker producing velocity** (GT-7) — `uwb/fusion.py` says "No Kalman / IMM here — stub".
3. A **localizer** for the MAP frame (GT-8) — the seam consumes one; nothing produces one.

---

## 4. Two framing corrections for the plan

1. **`scene_truth.json` is not the dependency.** `city_semantics.extract_city_semantics` reading MuJoCo **geom names** is. Targeting the eval artifact would move nothing on the live path.
2. **`PlaceGrounder` runs before perception** (`pipeline.py:1000`), so today a subset of directives never touch the perception stack at all. Any measurement of "how well does perception ground places" that goes through `DirectiveNavigator.parse` will be silently short-circuited for `coffee shop` / `bookstore` / `park` / `crosswalk` unless that arm is disabled or the POI table is emptied first.

*Scratchpad reserved (unused, no files written): `/tmp/claude-1000/-home-jaewoo-jang-Desktop-Projects-Parcel/799cb356-4cb4-445b-a784-306b6c6fd4a6/scratchpad/perception/ledger/`*