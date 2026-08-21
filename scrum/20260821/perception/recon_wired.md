Investigation complete. I did not modify anything in the repo.

## Component-by-component state

| Component | State | Call-site evidence |
|---|---|---|
| `navigation/semantic_map.py` | **WIRED** — the load-bearing one | `runtime.py:189` imports `semantic_candidates_from_observation`; `runtime.py:8793` puts it in the nav view every tick via `_semantic_candidates()`. `DirectiveNavigator.semantic_map` defaults to `ObservationSemanticMap()` (`pipeline.py:480`) — verified live: `<ObservationSemanticMap object>` |
| `city_semantics.py` | **WIRED** — the ground-truth source | `sim.py:204` `extract_city_semantics(model)` walks MuJoCo geoms; `sim.py:300` `visible_city_semantics(...)` applies a 12 m / ±70° frustum and stamps `confidence: 0.98`, `source: "simulator_semantic_camera"` (`city_semantics.py:294`) |
| `scene_semantics.py` | **WIRED** | Loaded at import of `city_semantics` (`_SCENE = scene_semantics()`); `runtime.py:7345` for place-admission vocabulary; `voice/scene_reference.py:28`. Reads `configs/scenes/city_block.semantics.yaml` — vocabulary only, no coordinates |
| `detection_adapter/perception_chain.py` | **WIRED but a no-op stage** | `runtime.py:8731` `_install_perception_chain()`; config `perception.tier: T0`. T0 is a *documented identity*: `process()` returns "the caller's own `dict` object" (`perception_chain.py:355-358`) |
| `instructnav/` grounding, scoring, arbiter, memory, scan, relations | **WIRED** | `pipeline.py:237-251` hard imports; `pipeline.py:502` constructs `GrounderV2()`; used at `pipeline.py:3551-3558` under `instructnav_recovery=True` (config default). `soft_import_health()` → `instructnav: true` |
| `instructnav/siglip.py`, `siglip2_onnx.py` | **PARTIAL — present, loaded, switched off** | Imported by `semantic_map.py:218`, `grounding.py:19`, `value_evidence.py:58`, `detection_lock_on`, `lock_on_verify`. Live check: `GrounderV2(matcher=None, ...)`, `SigLIP2Matcher().available == False` |
| `instructnav/search_entity.py` | **DORMANT** | Imported via `pipeline.py:252`, but its value-map scorer is inert: live `nav.semantic_value_map is None` |
| `navigation/value_evidence.py` | **DORMANT** | Only importers are `pipeline.py:269` and `value_map.py`. Live: `nav._value_evidence is None` |
| `camera_channel/` (`ingress.py`, `channel.py`, `frames.py`) | **DORMANT — fully built, never attached** | `runtime.attach_camera_ingress()` exists (`runtime.py:8849`) with **zero non-test call sites** repo-wide. No `camera_ingress` key in any config; `PARCEL_CAMERA_INGRESS` unset → `_camera_ingress_enabled()` False |
| `camera_channel/d455.py` | **WIRED as constants only** | Consumed by `pixel_detections.py:55`, `low_viewpoint/gates.py`, `storefront/render.py`, `capture/channels.py`. Its own docstring: "design constants for the sim/CameraChannel contract, **not commissioned hardware calibration**". No `pyrealsense2` anywhere in `src/` |
| `detection_adapter/pixel_detections.py`, `owlv2_onnx.py`, `metric_localizer.py`, `multi_view_confirm.py` | **DORMANT** | Reachable only through `camera_channel/ingress.py` (unattached) or `detection_lock_on` — live `nav.detection_lock_on == False`, `nav._detection_lock_on is None` |
| `detection_adapter/adapter.py`, `noise.py`, `sim_bridge.py` | **WIRED as libraries** | `label_embedding` / `bearing_range_from_pose` run in `PerceptionChain._lift` on every tick |
| `detection_adapter/false_positive_memory.py` | **DORMANT** | `pipeline.py:343` imports it, but `nav.lock_on_verify_on_approach == False` |
| `route_memory/place_graph.py` | **DORMANT** | `pipeline.py:378` soft-imports (succeeds), but `configs/navigation/default.yaml: route_memory: false`; live `nav.route_memory == False`. `runtime_hook.py` docstring: "Does not wire into RobotRuntime by default" |
| `perception.py` | **WIRED but vacuous** | `runtime.py:1236`; snapshot exposed at `runtime.py:5515, 7620`. It is a *declaration*, not perception: validates config, `NullMapProvider` always returns `available: False` |

## The weights claim in the brief is wrong

The 9 skipped tests do **not** skip for want of weights. **The weights are on disk and they work.**

```
~/.cache/parcel/siglip2-b16/  398M  text_model_int8.onnx, vision_model_int8.onnx, tokenizer.json
~/.cache/parcel/owlv2-b16/    160M  model_int8.onnx, tokenizer.json
onnxruntime 1.28.0, tokenizers 0.21.4  — both installed
```

They skip on an unset **env flag**. Verified by running them:

- `PARCEL_SIGLIP2_ONNX=1 pytest tests/test_siglip_real_embeddings.py` → **28 passed, 0 skipped** (was 23 passed / 5 skipped). The real cells confirm cosine synonym grounding (`streetlight`→`lamppost` 0.962) and refusal of the two cross-class false arrivals (`streetlight`/`tree` 0.869, `tree`/`lamppost` 0.872), plus unit-norm 768-d embeddings.
- `PARCEL_OWLV2_ONNX=1 pytest tests/test_owlv2_detector.py` → **13 passed, 1 skipped** (was 11/3). The real cells load the detector and run a full EGL-rendered scene end-to-end: OWLv2 names a red ball + green box correctly and localizes each within `RECOGNITION_LOCALIZATION_BUDGET_M` of the seg-truth ruler.

So **7 of the 9 are one env var away from green**, and the OWLv2 one already proves pixels→detect→localize→world-point works on rendered frames. Only the storefront OCR skip is a genuine missing dependency (`paddleocr` not installed; the test is marked "UNVERIFIED optional, never gate CI"). I measured 8 skips in the three named files, not 9 — the brief's count appears off by one.

The gating is deliberate, not an oversight: both loaders document opt-in so "merely landing the weights on disk never flips CI/mission onto a heavy CPU model" (OWLv2 is ~559 ms/query on CPU). Note nothing has tried these on the RTX 5000 Ada — both paths are CPU ONNX Runtime, no CUDA provider configured.

## Input contracts

Nothing in the live path consumes a real camera frame. Three tiers:

1. **Live mission path** — MuJoCo ground truth. `extract_city_semantics` reads geom names from the MJCF, `visible_city_semantics` frustum-filters, `PerceptionChain` T0 passes the dicts through unchanged, `ObservationSemanticMap.query` string-matches labels.
2. **Built-but-unattached pixel path** — `CameraIngress` renders through `MujocoEglCameraBackend` (**still MuJoCo**, just pixels instead of the oracle) and runs OWLv2. Camera backends are `mujoco_egl` and `synthetic` only.
3. **Test/eval-only** — `evals/nav_instruct/cam_*.py` cells call the detector/localizer modules directly. Per `perception_chain.py:56-69`, these carry `T-cam-proxy-*` ids and **none travels through the mission seam** — a prior audit returned every "T-cam" gate row for exactly that conflation. `storefront/` (OCR→`SemanticMemory2D`) has no importer in `runtime.py` or `pipeline.py` at all.

## If the ground-truth semantic map were deleted tomorrow

**Would still work — the entire geometric and safety stack, which never reads semantics:**
- Raycast LiDAR → rolling occupancy grid → A* (`grid_v1`). `lidar_payload_from_observation` is a separate, independent read.
- The whole safety chain: SafetySupervisor, reactive obstacle gate, collision filter, TTC gate, velocity smoother, S-curve shaper, hard-stop/preemption.
- Person yield and keep-out. `nearest_person_*` and `dynamic_agents` come from `sim.py:292` `select_social_collision_candidate` over dynamic-agent tracks — a **separate channel** from `semantic_objects`. This matters: deleting the semantic map does not blind the robot to people.
- `follow_owner`, `circle_owner`, `play_gesture`, `set_pose`, `get_status` — owner-anchored or proprioceptive, no scene semantics.
- Pose/route memory plumbing, voice, plan admission, tool broker, arbiter TTL/veto logic.

**Would break immediately:**
- Every `navigate_to` naming a scene thing. `ObservationSemanticMap.query` reads `observation.extras["semantic_candidates"]`; empty → `GrounderV2` returns `UNSEEN` → scan recovery → `honest_not_found_reply`. The robot degrades honestly rather than crashing, but it can no longer reach "the sidewalk", "the bench", "the lamppost".
- Arrival verification. `arrival_goal_region_for_relation` / `evidence_arrival_verified` build goal regions from candidate polygons and `near` bands. No candidates, no K0 arrival — so even a correct approach can't be declared successful.
- Relational grounding (`next_to`, `near`) — `instructnav/relations.py` needs candidate polygons.
- Place admission vocabulary shrinks. `runtime.py:6932` builds the admissible noun set from live `semantic_regions`/`semantic_objects` **plus** the sidecar's `CLASS_ALIASES`. The sidecar half survives, so "go to the bench" stays *admissible* but becomes ungroundable — it fails one stage later, at grounding rather than admission.

**Two things to flag beyond the brief's framing:**

**There is a second labeled world nobody mentioned.** `PlaceGrounder` (`pipeline.py:834`, tried *first* at `pipeline.py:1000`) loads `configs/navigation/cities/demo_pois.yaml` — a hand-authored POI table with hardcoded world coordinates (`coffee_42nd` at `[42.0, 8.5, 0.0]`, etc.) and its own comment "Expand when a real city map is wired." Deleting MuJoCo GT leaves this intact, so named POIs would still "resolve" — to coordinates nothing has verified. That is arguably worse than failing closed, and it's the cutover's sharpest hazard.

**The perception contract currently asserts something untrue.** `PerceptionContract.snapshot()` reports `reasoning_visibility: {"simulator_ground_truth": False}` and `simulator_truth_diagnostics_only: True`, and that snapshot is exposed at `runtime.py:5515` and `7620`. But the semantic candidates the navigator acts on *are* simulator ground truth, relabeled `source: "simulator_semantic_camera"` with a literal `confidence: 0.98`. The contract describes the system you want after this cutover, not the one running. Fixing that assertion is a good acceptance test for the work.

**Bottom line:** this is a cutover with less distance to travel than the brief assumes. The pixel path is fully built (`CameraIngress` → OWLv2 → `localize_frame` → world point → the same `semantic_candidates` dict shape), the weights are downloaded, and its end-to-end test passes against a seg-truth ruler. What is missing is three things, none of them a model: (1) nobody ever calls `attach_camera_ingress`, (2) three env flags are off, (3) the render source is still MuJoCo EGL rather than a D455 — and there is no RealSense driver in the tree at all. The `models/nav/citywalker` checkpoint is a red herring for this work; its own lock file marks it `research_only_until_rgb_trajectory_adapter_exists`.