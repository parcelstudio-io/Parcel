## PARCEL PERCEPTION-GENERALIZATION RESEARCH — map-free / exploration-driven object-goal navigation

**Verification note:** numbers marked ✅ were read from paper text/tables; ⚠️ came via secondary citation or search summary and should be re-checked against the primary table before they enter a scrum doc. One direct conflict is flagged inline.

---

## 0. Repo reconnaissance (read-only) — what the cutover is actually starting from

Before the literature, five facts that change the shape of the answer:

| Fact | Path | Consequence |
|---|---|---|
| `third_party/CityWalker/` **is already vendored** (full repo: `model/`, `config/`, `train.py`, `fine_tune.py`) | `/home/jaewoo-jang/Desktop/Projects/Parcel/third_party/CityWalker` | CityWalker is arm-able, not a build |
| `third_party/visualnav-transformer/` **is also vendored** (GNM/ViNT/NoMaD) — `train/` + `deployment/`, **no `.pth` weights found** | `/home/jaewoo-jang/Desktop/Projects/Parcel/third_party/visualnav-transformer` | ViNT/NoMaD need a weight download only |
| **`torch` is not installed** in `.parcel/`; `onnxruntime==1.28.0` exposes only `['AzureExecutionProvider','CPUExecutionProvider']` — **no CUDA EP** | `.parcel/bin/python` | Today every ONNX path (OWLv2, SigLIP-2) would run on CPU, and CityWalker/NaVILA-class torch models cannot run at all |
| `scene_truth` appears in **8 test files and 0 src files** | `tests/test_nav_instruct_scene_truth.py` et al. | The labeled world is a *harness* coupling, not a runtime coupling — good |
| The runtime's real ground-truth leak is `city_semantics.py`, which reads **region geometry from the MJCF** | `src/parcel_robot/city_semantics.py` ("Geometry is still read from the MJCF and never from the sidecar") | This single module is the cutover target |
| `maps/overture.py`, `maps/graph.py`, `maps/waypoints.py`, `maps/crossing.py`, `gnss/{model,noise,injector}.py` exist | `src/parcel_robot/maps/`, `gnss/` | The CityWalker input contract (GPS pose + route waypoint) already has a supplier |

**The seam is `SemanticCandidate`** (`navigation/semantic_map.py:15`). It already carries `confidence`, `source`, `observed_at`, `reachable`, `polygon`, and `kind ∈ {"object","region"}`. A perception-built candidate populates the identical type. Nothing downstream — planner, admission, safety — needs to know the provenance changed. That is the whole cutover in one sentence, and it is unusually clean.

---

## 1. VLFM — Vision-Language Frontier Maps (ICRA 2024, Boston Dynamics AI Institute)

**What it does.** Fully modular, zero-shot, training-free ObjectNav. Depth → 2D occupancy map → frontier extraction. In parallel, RGB → BLIP-2 ITM cosine similarity against the prompt *"Seems like there is a `<target>` ahead."* → one scalar per camera look, painted into a co-registered **value map**. Confidence is a cone falloff on the optical axis: `c = cos²( (θ / (θ_fov/2)) · π/2 )` — 1.0 dead ahead, →0 at the FOV edge; revisited cells are confidence-weighted averaged. ✅ Pick the highest-valued frontier, drive there with a PointNav policy. Detection is split: **YOLOv7 for COCO classes, Grounding DINO for open-vocab**; **Mobile-SAM** extracts the contour from the winning box, and depth on that contour gives the final goal waypoint. ✅

**Measured results** ✅ (val splits):

| Dataset | Episodes / scenes | VLFM SR | VLFM SPL | Best prior |
|---|---|---|---|---|
| Gibson | 1,000 / 5 | **84.0%** | **52.2%** | SemUtil 69.3 / 40.5 |
| HM3D | 2,000 / 20 | **52.5%** | **30.4%** | ESC 39.2 / 22.3 |
| MP3D | 2,195 / 11 | **36.4%** | **17.5%** | ESC 28.7 / 14.2 |

Runtime: BLIP-2 + Grounding DINO + Mobile-SAM + ZoeDepth **all real-time on a single RTX 4090 MaxQ, 16 GB VRAM** ✅. Deployed on Boston Dynamics Spot in an office building with no prior map.

**Why it matters for Parcel.** `src/parcel_robot/navigation/value_map.py` is *already a VLFM value map*. Its docstring: *"No detector or runtime is invoked here. A caller supplies one scalar semantic similarity and optical-axis confidence for each camera look."* It has `ViewCone(origin_world_xy, heading_rad, fov_rad, max_range_m)` and the same rolling-grid cell convention as `RollingOccupancyGrid`. Parcel implemented VLFM's *arithmetic* and left the *scalar supplier* as a parameter. `route_memory/vlfm.py` currently fills it with `HeuristicVLFMScorer` — a label prior plus radial bias, self-labeled `DOES_NOT_PROVE`.

**Design implication.** The highest-leverage single change in this entire cutover is replacing that heuristic scalar with a real image-text similarity. Parcel already ships `instructnav/siglip2_onnx.py` — SigLIP-2 substitutes for BLIP-2 ITM as the scalar source with no architectural change. That converts `HeuristicVLFMScorer` → a real VLFM scorer and un-skips the 5 SigLIP-2 gate tests in one motion. **Do this first.** It is a ~1-file swap against an interface that already exists.

---

## 2. SysNav (2026) — the single closest system to Parcel in the literature

**What it does.** Argues explicitly that *"real-world ObjectNav should be treated as a system-level problem rather than a single-policy learning task."* Three-level modular hierarchy: (1) semantic scene representation + VLM reasoning, (2) room-based in-room exploration (classical TSP planning) + cross-room policy, (3) **embodiment-specific base autonomy: waypoint following, collision avoidance, terrain traversability** — deterministic, not learned. ✅

**Hardware — read this line carefully:** custom Mecanum wheeled robot, **Unitree Go2**, Unitree G1. Sensors: **Livox Mid-360 LiDAR** + Ricoh Theta Z1 360° panoramic camera; Go2/G1 use built-in locomotion policies. Compute: one laptop, i9-14900HX + RTX 4090. Perception stack: **YOLOv8x-worldv2 + SAM2.1_hiera_b+ + Gemini-2.5-flash**. ✅

**Measured results** ✅:

| Benchmark | SR | SPL |
|---|---|---|
| HM3D-v1 | 63.7% | 30.5% |
| HM3D-v2 | 80.8% | 37.2% |
| MP3D (2,195 eps) | 50.7% | 18.1% |
| HM3D-OVON | 54.9% | 26.1% |

Real world: **190 episodes across 3 environments**; the 112-episode difficulty table reports Easy 100%, Medium 97.5%, Hard 98.3% SR.

**Why it matters for Parcel.** This is Parcel's exact platform (Go2 + LiDAR + camera + one workstation GPU) running the exact architecture Parcel already has (VLM proposes semantics; deterministic layer disposes waypoints, collision avoidance, traversability), and it is state-of-the-art on four benchmarks *and* near-ceiling in the real world. **SysNav is the strongest available evidence that Parcel's propose/dispose split is not a safety tax — it is the winning architecture.** Do not let anyone argue the safety chain must be relaxed to get perception generalization.

**Design implications.** (a) The VLM in the loop is a *hosted flash-tier model called at room-transition boundaries*, not a per-frame policy — call frequency is low enough that Parcel's existing GPT Realtime tool-call path could carry the same role if the local Gemma reasoner is VRAM-squeezed. (b) SysNav's win is largely from a **panoramic** camera. Parcel has a forward-facing D455 (~87° H-FOV). Expect a real penalty; VLFM's mitigation is a **deliberate rotation-in-place scan** to synthesize panoramic coverage — and Parcel already has `navigation/value_directed_scan.py` and `instructnav/scan.py`. Wire the scan into frontier arrival rather than adding hardware. (c) SysNav's room decomposition has no outdoor analogue; Parcel's equivalent is block/segment decomposition off `maps/graph.py`.

---

## 3. HM3D-OVON — the benchmark Parcel should actually target

379 object categories, >15k annotated instances, free-form language goals at test time (vs. the 6–20 fixed categories of classic ObjectNav). ⚠️ Baselines: **VLFM 38.1 / 37.7 / 38.5% SR** on val-seen / synonyms / val-unseen; **DAgRL+OD 38.5 / 39.0 / 37.1%**. ⚠️ The headline finding: the end-to-end RL method drops **11.9–23.0 pp** from seen→unseen categories, while modular VLFM is *flat across all three splits and beats DAgRL on both generalization splits*. ✅ (this pattern is the paper's stated conclusion)

2026 state of the art: **NavFoM 45.2% SR zero-shot** (beating the prior fine-tuned SOTA at 43.6%) ⚠️; **SysNav 54.9 / 26.1** ✅; **FiLM-Nav** claims SOTA SPL on HM3D-OVON by fine-tuning a VLM as a frontier selector ✅ (abstract). On plain HM3D ObjectNav, VLingNav reports 79.1 SR / 42.9 SPL (v1) and 83.0 SR / 40.5 SPL (v2) ⚠️.

**Why it matters.** The seen→unseen collapse of end-to-end policies vs. the flatness of modular ones is *the* empirical argument for Parcel's directive. The owner's whole point is "we won't have the labeled world" — that is the unseen-category split, and modular wins it.

**Design implication.** Parcel currently has no external navigation benchmark. Adopt HM3D-OVON's *protocol* (seen / synonym / unseen category splits) inside the existing NAV_INSTRUCT scorer even while running in MuJoCo. A synonym split is nearly free to generate from `configs/scenes/city_block.semantics.yaml` aliases and immediately measures whether grounding generalizes past memorized vocabulary — which the current scene_truth harness structurally cannot detect.

---

## 4. GOAT and GOAT-Bench — lifelong multimodal goals, and the honest ceiling

**GOAT (RSS 2024).** Modular, platform-agnostic, with an **instance-aware semantic memory** that tracks object appearance across viewpoints so two chairs are two instances, not one category. Goals as category, image, or language. Real-world: **>90 hours, 9 homes, 675 goals, 200+ object instances, 83% overall SR** — and the number that matters most: **60% on the first goal in a home, rising to 90% after exploration.** ⚠️ Deployed on Spot and wheeled platforms.

**GOAT-Bench.** 5–10 targets per episode, mixed modality, no reset between subtasks. Best modular GOAT variant on val-unseen: **24.9% subtask SR / 17.2% SPL** ⚠️. SenseAct-NN Skill Chain beats modular by ~+4 pp SR on average but is **−6.6 pp SPL** ⚠️. Memory ablation: removing cross-subtask memory degrades both families. 2026 has moved this a long way — MTU3D 52.2 SR / 30.5 SPL (val-seen) ⚠️, **AstraNav-Memory 62.7 SR / 56.9 SPL** val-unseen (+15.5 SR / +29.2 SPL over MTU3D) ⚠️, **MetaNav 71.4 SR / 51.8 SPL** ⚠️.

**Why it matters.** Parcel is a *companion*. It revisits one neighborhood forever. The 60→90% curve is precisely Parcel's operating regime and its strongest structural advantage over every benchmark agent — Parcel gets to keep the map. `route_memory/place_graph.py`, `route_memory/vpr.py`, `route_memory/teach_repeat.py`, and `instructnav/memory.py` (`RememberedEntity`) are already the GOAT memory pattern.

**Design implications.** (a) Report Parcel's success rate **as a function of visit count**, not as a scalar — a single-number SR misrepresents a companion robot and hides the asset Parcel already has. (b) GOAT's instance-awareness is the missing discipline: `detection_adapter/multi_view_confirm.py` and `false_positive_memory.py` exist, but a *persistent per-instance embedding* keyed into `place_graph` is what makes "the bench we sat on yesterday" resolvable. `recall_memory` as a tool call is currently backed by a labeled world; GOAT shows what backs it without one. (c) Absolute GOAT-Bench numbers in the low-to-mid tens (2024) rising to ~60s (2026) is the honest expectation to set with the owner for cold-start multimodal goals — the field is nowhere near solved.

---

## 5. GNM / ViNT / NoMaD — general navigation models

**GNM** (ICRA 2023): cross-embodiment low-level policy, zero-shot transfer across robots. **ViNT** (CoRL 2023): transformer foundation model, early-fusion of observation + **goal image**, topological-graph navigation, adaptable to downstream tasks. **NoMaD** (ICRA 2024): ViNT encoder + **diffusion decoder** with **goal masking** — one policy that is goal-conditioned when the goal token is present and a pure exploration policy when it is masked. Single RGB camera. Reports lower collision rates and better performance than five baselines with a *smaller* model. ⚠️ (abstract-level; the per-baseline table was not retrieved)

**Why it matters for Parcel.** The vendored `third_party/visualnav-transformer/deployment/` is the reference implementation of the topological-graph + goal-image loop, and NoMaD's goal-masking is exactly the "explore vs. go to a thing" switch that `route_memory/proposer.py` and `instructnav/search_entity.py` are groping toward.

**Design implication — and a caution.** ViNT/NoMaD goals are **images**, not language. That is a poor fit for `navigate_to("the sidewalk")` but an excellent fit for `recall_memory` → "return to the place whose keyframe looks like this," and for teach-and-repeat. Treat NoMaD as a **local exploration proposer** feeding SE2 goals into the existing arbiter — never as the controller. Its diffusion head emits *action chunks*, which would bypass the deterministic chain if wired to velocity. `route_memory/citywalker.py` already establishes the correct discipline (*"Learned outputs are SE2Goal proposals only — never model-authored velocity"*); hold NoMaD to the identical contract.

---

## 6. CityWalker — what the vendored 1.7 GB checkpoint actually is

**Architecture** (confirmed against `third_party/CityWalker/config/citywalk_2000hr.yaml`): frozen **DINOv2 ViT-B/14** encoder, `context_size: 5`, crop/resize `[350, 630]`; a 16-layer / 8-head / 768-d transformer; a trainable polar `cord_embedding: input_target`; two heads (action MLP + arrival). **214M params, 127M trainable.** ✅

**Inputs:** last 5 RGB frames + last 5 GPS coordinates + **one target waypoint (a GPS coordinate)**. **Outputs:** 5 future waypoints in Euclidean space + a binary arrival flag. ✅ Trained on **2,000 h of YouTube city walking/driving video** with **DPVO visual-odometry pseudo-labels**, actions normalized by per-trajectory mean step length for cross-embodiment scale invariance. ✅

**Measured results** ✅: real-world **77.3% SR** vs. fine-tuned ViNT; per-scenario Forward 100%, Left Turn 62.5%, Right Turn 66.7%, **8–14 trials per scenario type**, success = arrival predicted within 5 m. Offline on 9 h of teleoperated NYC data: MAOE 15.2° vs ViNT 16.5°; arrival accuracy 81.8% vs 70.5%. Zero-shot (web-only, >1000 h) beats *fine-tuned* ViNT. Platform: **Unitree Go1 + Livox Mid-360 + RGB webcam.** ⚠️ **Conflict to resolve:** the ViNT baseline is reported as 62.5% in one source and 57.1% in another — check the paper's Table before citing.

**Why it matters — and the correction I need to make explicitly.** *CityWalker does not address the owner's directive.* It is map-free in the sense of "no metric SLAM map," but it is **not label-free in the useful sense**: it consumes a GPS target waypoint, typically from a Google Maps / OSM routing API. It answers *"how does a pedestrian-like agent get to this coordinate through a real city — curbs, crowds, crossings, detours?"* It does **not** answer *"which of these surfaces is the sidewalk?"* If the 1.7 GB checkpoint gets read as the answer to perception generalization, the sprint will burn on the wrong axis.

**Design implication.** CityWalker is nonetheless *ready to arm today* and worth arming — `maps/overture.py` + `maps/graph.py` + `maps/waypoints.py` + `gnss/` already supply exactly its input contract, and `route_memory/citywalker.py` already has the fail-closed adapter with the SE2Goal-only output rule. Blocking dependency: **torch is absent from `.parcel/`**. Frame it correctly in the scrum card as *urban motion prior*, filed next to `navigation/traffic_aware.py` and `navigation/proxemic_approach.py` — not as semantic grounding.

---

## 7. VLM-as-navigator, 2025–2026

**NaVILA** (quadruped VLA). Two-level: a VILA-family VLM emits **mid-level natural-language commands** — literally *"move forward 75 cm"*, *"turn right 30 degrees"* — parsed by a **regular expression**, and consumed by a low-level PPO locomotion policy trained single-stage in Isaac Lab (LiDAR 2.5D height map + proprioception + command velocity → 12 joint positions, >60K FPS training on an RTX 4090). ✅ Robots: **Unitree Go2**, Unitree H1, Booster T1. Results: VLN-CE R2R val-unseen **54.0 SR / 49.0 SPL / 62.5 OS / NE 5.22 m**; RxR val-unseen **44.0 SR / 44.0 SPL / 58.8 nDTW / NE 6.77 m**; new VLN-CE-Isaac benchmark over **1,077 traversable trajectories**; real world **25 instructions × 3 repeats = 75 trials, 88% SR (75% on complex multi-room)**. **~1 FPS on a single RTX 4090**; W4A16 quantization gives 40% speedup at half the memory. ✅

**StreamVLN.** LLaVA-Video 7B / Qwen2-7B, slow-fast context: sliding-window KV cache for recent turns + 3D-aware **voxel-based token pruning** for long history; KV reuse removes >99% of prefill. R2R-CE val-unseen **56.9 SR / 51.9 SPL / NE 4.98** (with extra data; 52.8 / 47.2 without); RxR-CE **52.9 SR / 46.0 SPL / NE 6.22**. **0.27 s per 4 actions on an RTX 4090.** Real robot: **Unitree Go2 + Intel RealSense D455.** Training cost: **~1,500 A100-hours**, 450K MP3D + 300K HM3D + 240K DAgger + 248K video-QA + 230K interleaved samples. ✅

**NavFoM.** Unifies VLN + object search + target tracking + autonomous driving; **8M navigation samples**; camera-identifier tokens absorb varying rig configurations; deployed on quadrupeds, drones, wheeled robots, vehicles; zero-shot SOTA/competitive without task-specific fine-tuning. ⚠️ **FiLM-Nav.** Fine-tunes a pretrained VLM directly as the policy across ObjectNav/OVON/ImageNav/spatial-reasoning; SOTA SR *and* SPL on HM3D ObjectNav among open-vocab methods, SOTA SPL on HM3D-OVON. ✅ (abstract) **Uni-NaVid** uses a 4-token action vocabulary (STOP/FORWARD/LEFT/RIGHT); StreamVLN's symbolic `↑ ← →` tokens edge it out (50.9 vs 42.7 SR ⚠️).

**Why this matters — the non-obvious finding.** StreamVLN runs on **Unitree Go2 + RealSense D455**, which is Parcel's exact sensor pair (`camera_channel/d455.py`). And crucially: **the "end-to-end" family is not actually end-to-end at the interface.** NaVILA emits regex-parseable parameterized commands; Uni-NaVid and StreamVLN emit a 3–4 symbol discrete action vocabulary. **Every one of them is structurally a proposer.** The claim that a VLA "would fight Parcel's propose/dispose architecture" is only true if you wire it to velocity. Wired to `SE2Goal`, NaVILA's output is *isomorphic to a Parcel tool call*.

**Design implications.** (a) The real conflict is not architectural, it is **jurisdictional**: a VLA replaces the *intent router and the planner*, not the safety supervisor. Parcel would be trading a deterministic, testable, 7,164-test-covered planner for a 7B model at 1 FPS — a bad trade for a companion robot whose differentiator is that the local chain disposes. (b) Cost is decisive: StreamVLN's ~1,500 A100-hours and NaVILA's Isaac Lab pipeline are not reachable on one RTX 5000 Ada. (c) **What to steal instead:** NaVILA's *action grammar*. A parameterized, regex-checkable, bounded command vocabulary between a language model and a deterministic executor is exactly Parcel's tool-call contract, independently rediscovered by the VLA community — that is strong external validation, and it is free to cite. (d) VRAM: a 7B VLA at W4A16 is ~5–7 GB, which coexists with local Gemma inside 32 GB. Keep the option open as a *shadow proposer* (the pattern `scrum/20260807/task_2/designs/DESIGN_D2_SHADOW_PROPOSERS.md` already names) — never as the executor.

---

## 8. Frontier exploration with semantic priors

**SemExp** (NeurIPS 2020) — builds a spatial semantic map and learns a goal-oriented exploration policy over it; the ancestor of the whole modular line. **PEANUT** — explicitly predicts *object likelihood in unexplored regions* rather than scoring only the frontier boundary; outperforms pure frontier methods. ⚠️ **FrontierNet** (Jan 2025) — predicts frontiers **and their information value directly from posed RGB with monocular depth priors, bypassing dense 3D mapping**; strongest in the early-exploration regime. ⚠️ **ESC** — LLM soft commonsense constraints (HM3D 39.2 SR / 22.3 SPL; MP3D 28.7 / 14.2 ✅ via VLFM's table). **OpenFrontier (2026)** — general navigation with visual-language grounded frontiers. **R2F (2026)** — repurposes ray frontiers for **LLM-free** object navigation, i.e. the field is now actively trying to *remove* the LLM from the frontier-selection loop on latency grounds.

**Why it matters.** `instructnav/search_entity.py` already defines `FrontierCandidate`, `FrontierScorer`, `semantic_prior_for_label`, and — tellingly — `SIDEWALK_BORDERS_ROAD_PRIORS`. Parcel has hand-authored the commonsense priors that ESC gets from an LLM. That is *good*: they are deterministic, auditable, and testable. The `FrontierScorer` protocol means a real scorer swaps in without touching the call site.

**Design implications.** (a) Keep the hand-authored priors as a **fail-closed floor**, and let the VLM scorer modulate above it — that gives graceful degradation when the VLM is unavailable or the render is out of distribution, which no cited paper provides. (b) FrontierNet's monocular-depth path is largely irrelevant to Parcel: `mujoco_lidar.py` gives real geometry, so occupancy → frontier is *cheap and exact*. Spend the compute budget on the semantic scalar, not on depth. (c) R2F is the useful counterweight — if VLM calls per episode become the bottleneck, an LLM-free frontier scorer is a published fallback, not a regression.

---

## 9. Open-vocabulary mapping — how you build labels without a label set

**ConceptFusion** (RSS 2023) — open-set multimodal 3D maps by fusing per-pixel foundation-model features into a 3D reconstruction. **ConceptGraphs** (ICRA 2024) — open-vocabulary **3D scene graphs**: object nodes with CLIP-family descriptors plus inter-object edges, built incrementally from posed RGB-D. **HOV-SG** (RSS 2024) — hierarchical floor→room→object scene graphs; beats ConceptFusion and ConceptGraphs on open-vocab 3D semantic segmentation (0.231 mIoU on Replica with ViT-H-14; 100% floor prediction) at a **75% smaller representation than dense open-vocab maps** ⚠️. **SG-Nav** (2024) — online 3D scene-graph prompting for LLM-based zero-shot ObjectNav. **CrossMaps** (ICRA 2026) — **confidence-aware** real-time open-vocab mapping that propagates *sensor quality* alongside semantics ⚠️. **FindAnything** (2026) — open-vocab object-centric mapping for exploration.

**Why it matters.** This is the literal answer to "build its own semantic understanding from sensors." And Parcel's `SemanticCandidate` is already a scene-graph node in all but name — it has an id, label, position, polygon, confidence, source, timestamp, reachability, and metadata. `instructnav/relations.py` (`nearest_point_in_region`) and `navigation/relation_registry.py` are the edge machinery.

**Design implications.** (a) **CrossMaps' confidence-awareness is the one to copy**, because it is the only member of this family that speaks Parcel's language. Parcel's admission layer needs to reject plans grounded on weak evidence; a semantic map that reports *"sidewalk, 0.42, from 2 views, 8 s stale, LiDAR-supported"* lets `value_evidence.py` and plan admission do their job. Every other open-vocab map hands the planner a hard label and hides the uncertainty — which would be a safety regression for Parcel. (b) HOV-SG's hierarchy has no rooms outdoors, but **block → segment → object** is the direct analogue and `maps/graph.py` already holds the upper two levels. (c) The 75% size reduction matters for a persistent companion memory that must survive across sessions.

---

## 10. The "sidewalk" problem — the gap nobody in ObjectNav solves

**This is the most important section for the owner's directive.** Every system in §1–§9 except one is **object-centric**: it detects a *thing* with a bounding box and a contour. `"go to the sidewalk"` is not an object query. It is a **region / terrain / traversability** query, and it needs a *polygon*, not a box.

**ViPlanner** (leggedrobotics, ICRA 2024) is the exception and the right template. Semantic + depth images → a **differentiable semantic costmap over 30 classes whose RGB colorspace encodes multiple levels of traversability** → local path, trained end-to-end by imperative learning on the planning objective. **Trained purely in simulation with zero-shot sim-to-real transfer**; **−38.02% traversability cost** vs. purely geometric planners; noise-resistant; ROS package tested on ANYmal C/D. ⚠️ Related: **CoNVOI** (VLM context-aware outdoor/indoor navigation), **Sem-NaVAE** (2026, semantically-guided outdoor mapless navigation with generative trajectory priors), experience-based traversability work validated on *"a grassy path and a sidewalk with a crosswalk"* using CLIPSeg. ⚠️

**Why it matters for Parcel.** `SemanticCandidate.kind` admits `"region"`, and `city_semantics.py` currently manufactures region polygons **from MJCF geometry** — the exact ground-truth dependency the owner named. `detection_adapter/` is entirely box-based (`pixel_detections.py`, `owlv2_onnx.py`). **Parcel's object track has a perception source; its region track has none.** OWLv2 will not fix this — asking a box detector for "sidewalk" is a category error.

**Design implications.** (a) The region track needs a **segmentation** model, not a detector: CLIPSeg or SAM2 + SigLIP-2 region embeddings, or a ViPlanner-style fixed traversability class set. (b) **A fixed 20–30 class outdoor semantic set (sidewalk / road / crosswalk / curb / grass / building / stairs / obstacle) is not a retreat from open-vocabulary — it is the correct engineering choice for the *safety-relevant* channel**, because ViPlanner shows it sim-to-reals zero-shot, it is enumerable, and therefore *testable* in a way that free-form text is not. Run open-vocab (SigLIP-2 / OWLv2) for the **object/goal** track and a closed traversability set for the **region/safety** track. Those two tracks have genuinely different requirements and conflating them is how the safety chain gets a soft underbelly. (c) The output of the region track should be a **cost layer**, not a label — `navigation/dynamic_costs.py` and `dynamic_layer.py` already exist to receive it, and the safety supervisor keeps veto authority over anything the cost layer proposes.

---

## 11. Family verdict: modular, decisively — with a stated caveat

| Axis | Modular (VLFM / GOAT / SysNav / ConceptGraphs) | End-to-end (NaVILA / StreamVLN / NavFoM / FiLM-Nav) |
|---|---|---|
| Preserves a deterministic planner | **Yes, by construction** | No — replaces it |
| Preserves an independent safety veto | **Yes** — SysNav's L3 is explicitly deterministic | Only if you re-add one *outside* the policy |
| Seen→unseen category generalization | **Flat** (VLFM 38.1→38.5 on HM3D-OVON) | Drops 11.9–23.0 pp (DAgRL) |
| Training data needed | **None** (VLFM, GOAT, SysNav are training-free / pretrained-only) | 8M samples (NavFoM); ~1,500 A100-h (StreamVLN) |
| Runs on Parcel's RTX 5000 Ada | **Yes** — VLFM's whole stack fits in 16 GB | Marginal: 7B @ ~1 FPS, W4A16 needed |
| Failure mode | Degrades to geometric frontier exploration — **legible** | Silent, unattributable policy error |
| Auditability per Parcel's gate | Each module unit-testable | One opaque forward pass |
| Best real-world evidence on Go2 | **SysNav: 190 episodes, 97.5–100% SR** | NaVILA: 75 trials, 88% SR |

**Verdict.** Modular, and it is not close for Parcel. The decisive facts are that (i) the SOTA on the exact platform is modular and explicitly argues navigation is a systems problem, (ii) modular is the family that *doesn't collapse* on unseen categories — which is the entirety of the owner's directive, and (iii) modular needs **zero training data**, which is the difference between a sprint and a research program.

**The caveat I owe you:** the framing "end-to-end would fight propose/dispose" is not quite right and the scrum card should say so. NaVILA proposes `"turn right 30 degrees"` through a regex parser into a separate locomotion policy; StreamVLN emits 3 symbols. These *are* propose/dispose systems. What they fight is Parcel's **planner and intent router**, not its safety layer. The right long-term position is a shadow VLA proposer competing with the deterministic planner inside `instructnav/arbiter.py`, gated on A/B evidence — the pattern `route_memory/citywalker.py` already implements. Not now, but the door should stay open and the reasoning recorded.

---

## 12. Training data vs. pretrained-only

**Runs today with pretrained weights only, zero training:**
- VLFM (BLIP-2 / SigLIP-2 + Grounding DINO or OWLv2 + Mobile-SAM/SAM2) — **the fastest path, and Parcel already has the value map**
- ConceptGraphs / HOV-SG / CrossMaps semantic mapping
- SysNav's perception stack (YOLO-World + SAM2 + a hosted flash-tier VLM)
- ViNT / NoMaD (weight download only; `third_party/visualnav-transformer` already vendored)
- CityWalker (checkpoint already on disk; needs torch)
- ViPlanner (published sim-trained checkpoint, zero-shot sim-to-real)

**Needs training you cannot afford:** NaVILA, StreamVLN (~1,500 A100-h), NavFoM (8M samples), FiLM-Nav, DAgRL, PIRLNav.

**Needs modest fine-tuning (plausible on one RTX 5000 Ada):** CityWalker fine-tune (`fine_tune.py` + `config/finetune.yaml`, from teleop trajectories — the paper used 9 h); a small frontier-scorer calibration head; per-class thresholds for the region track.

---

## 13. Safety-layer preservation — explicit ruling

Approaches that **preserve** SafetySupervisor → intent router → plan admission → task executive → navigator **unchanged**:
- **VLFM** — outputs a *goal waypoint*. Planner and safety untouched. ✅
- **SysNav** — L3 base autonomy (waypoint following, collision avoidance, traversability) is exactly Parcel's chain; the paper's own design. ✅
- **GOAT** — modular; memory + goal selection only. ✅
- **ConceptGraphs / HOV-SG / CrossMaps** — perception only; produce `SemanticCandidate`s. ✅
- **NoMaD / ViNT** — safe *only if* constrained to SE2 goal proposals; unsafe if wired to action chunks. ⚠️
- **CityWalker** — already correctly constrained in-repo (SE2Goal only, never model-authored velocity). ✅
- **ViPlanner** — it *is* a local planner; adopt its **costmap**, not its planner. Feed `navigation/dynamic_costs.py`; leave `reactive_safety.py`, `person_keepout.py`, `lethal_veto.py`, `experimental_all_ray_shield.py` with final authority. ⚠️

Approaches that **displace** the chain: NaVILA, StreamVLN, Uni-NaVid, NavFoM, FiLM-Nav — all replace router+planner. NaVILA additionally replaces the locomotion controller with a learned PPO policy, which would put a neural network *below* Parcel's safety supervisor. **That is the one line that must not be crossed.**

**The invariant to write into the card:** *perception may be learned, open-vocabulary, uncertain, and wrong; the disposal chain must remain deterministic and must treat every perceptual claim as evidence with a confidence, never as ground truth.* Parcel's `evidence_origin.py`, `value_evidence.py`, and `authority.py` suggest this is already the house style — the cutover's job is to keep it true when the evidence stops being ground truth.

---

# Design pressure

### What the existing assets get right

1. **The value map is already VLFM.** `navigation/value_map.py` implements the co-registered rolling grid, the `ViewCone`, and optical-axis confidence weighting — VLFM's actual mechanism, with the semantic scalar left as an injected parameter. Parcel built the hard, correct half and stubbed the easy half. This is the single best-positioned asset in the repo.
2. **`SemanticCandidate` is the right seam, and it is already uncertainty-native.** `confidence`, `source`, `observed_at`, `reachable`, `polygon`, `kind ∈ {object, region}` — a perception-built candidate is type-identical to a truth-built one. The cutover does not require a planner rewrite. Very few codebases are this lucky.
3. **Ground truth is confined.** `scene_truth` touches 8 test files and **zero** source files. The runtime leak is essentially one module (`city_semantics.py`, MJCF geometry → regions). The blast radius is small.
4. **The propose/dispose split is the published SOTA architecture**, not a safety compromise — SysNav (2026, Unitree Go2, 190 real episodes, 97.5–100% real-world SR) argues for it explicitly and wins four benchmarks with it.
5. **The learned-output discipline is already codified.** `route_memory/citywalker.py`: *"Learned outputs are SE2Goal proposals only — never model-authored velocity."* Every future learned proposer should inherit that docstring verbatim.
6. **Fail-closed + `DOES_NOT_PROVE` + honest skips.** The 9 skipping gate tests are a *feature*: the repo already knows exactly which claims are unbacked. Most teams discover this at deployment.
7. **The memory stack anticipates GOAT.** `place_graph.py`, `vpr.py`, `teach_repeat.py`, `false_positive_memory.py`, `multi_view_confirm.py` are the ingredients of GOAT's instance-aware memory, which is what turned 60% into 90% over nine homes.
8. **Hand-authored commonsense priors** (`SIDEWALK_BORDERS_ROAD_PRIORS`) do deterministically what ESC pays an LLM for — and they give a fail-closed floor no cited system has.
9. **The CityWalker input contract is already supplied** by `maps/overture.py` + `maps/graph.py` + `maps/waypoints.py` + `gnss/`.

### What they are missing

1. **No region-track perception at all.** This is the biggest gap and it is exactly the owner's example sentence. `detection_adapter/` is box-only; `"sidewalk"` needs segmentation → polygon → cost layer. OWLv2 cannot supply it. **Nothing in the object-centric ObjectNav literature supplies it either** — the answer is in the ViPlanner / CLIPSeg / semantic-traversability line, which the repo does not yet touch.
2. **No real semantic scalar into the value map.** `HeuristicVLFMScorer` is a label prior plus radial bias. Until SigLIP-2 (or BLIP-2 ITM) supplies the scalar, Parcel has VLFM's plumbing and none of its perception.
3. **No GPU inference path.** `onnxruntime==1.28.0` with only `CPUExecutionProvider`/`AzureExecutionProvider`, and **no torch at all** in `.parcel/`. Every weight-dependent skip is currently blocked on runtime, not on weights. This is a prerequisite ticket, not a perception ticket, and it should be sequenced first.
4. **No confidence propagation contract from perception to admission.** Perception is about to start being wrong. `value_evidence.py` exists; what is missing is a stated rule for how detection confidence, view count, and staleness compose into an admission decision — CrossMaps is the reference.
5. **No instance identity across visits.** `recall_memory` is backed by a labeled world. GOAT's per-instance multi-view embedding keyed into `place_graph` is what backs it without one.
6. **No open-vocabulary benchmark protocol.** No seen/synonym/unseen split, so there is currently no instrument that can *detect* whether grounding generalizes past memorized scene vocabulary. HM3D-OVON's protocol is adoptable inside the existing NAV_INSTRUCT scorer.
7. **No panoramic coverage and no compensating scan policy at frontier arrival.** SysNav's margin comes substantially from a 360° camera; VLFM's answer is deliberate rotation. `value_directed_scan.py` and `instructnav/scan.py` exist but are not wired to frontier arrival.
8. **No ViNT/NoMaD weights** despite the vendored repo — a download, not a build.

### Pitfalls

1. **The MuJoCo appearance gap is the top technical risk, and it is documented.** Recent work reports that MuJoCo-rendered scenes cause outright **failures in Grounding DINO, SAM2/SAM3, and Molmo2**, and that open-vocab segmenters trained on real data struggle on simulation imagery generally. ⚠️ Parcel's entire perception cutover is about to be validated against renders these models may not parse. **Mitigation:** validate OWLv2/SigLIP-2 on MuJoCo frames *before* building anything on top of them; consider a Madrona-raytraced path (MuJoCo Playground) or texture upgrades; and — most important — **never let a green MuJoCo perception gate be reported as evidence of real-world perception.** The existing `DOES_NOT_PROVE` convention is the right instrument; extend it to every sim-perception gate.
2. **Mistaking CityWalker for the answer.** 1.7 GB of checkpoint sitting in `models/nav/` will attract the sprint. It consumes a **GPS waypoint** and outputs motion; it has no semantic grounding whatsoever. Arm it — but file it under urban motion prior, not perception generalization, and say so in the card's first paragraph.
3. **Letting a learned model touch velocity.** NoMaD emits diffusion action chunks; NaVILA emits joint targets through a PPO policy. Either wired below the safety supervisor is an irreversible architecture regression. The `SE2Goal`-only rule must be enforced by *type*, not by convention.
4. **Replacing a hard label with a different hard label.** If perception outputs `label="sidewalk"` with no confidence, staleness, or view count, Parcel has swapped a *correct* oracle for an *incorrect* oracle and made the system strictly worse while feeling more advanced. Confidence must be structural, not advisory.
5. **Single-number success rates.** For a companion that revisits one neighborhood, a scalar SR is actively misleading — GOAT's 60%→90% curve is the honest instrument and happens to be where Parcel's memory stack already shines.
6. **Expecting ObjectNav numbers to transfer outdoors.** VLFM's 84% on Gibson is *indoor, 5 scenes, 1,000 episodes, closed category set*. HM3D drops it to 52.5%, MP3D to 36.4%, HM3D-OVON open-vocab to ~38%. Outdoor city with region goals is harder than all of them and has no comparable published baseline. Set expectations from the **36–55%** band, not the 84%.
7. **GOAT-Bench honesty.** Cold-start lifelong multimodal goal navigation was ~25% subtask SR in 2024 and ~60–71% SR in 2026 ⚠️. If `recall_memory` is expected to work on first exposure without the labeled world, that expectation is not supported by any published system.
8. **VRAM contention is real but not binding.** VLFM's full stack (BLIP-2 + Grounding DINO + Mobile-SAM + ZoeDepth) ran real-time in **16 GB**; Parcel has 32 GB on an RTX 5000 Ada. A local Gemma plus the modular perception stack fits. A 7B VLA at 1 FPS alongside Gemma does not fit *usefully*, which is a second independent argument against the end-to-end family.
9. **Two unresolved citations before anything enters a scrum doc:** CityWalker's ViNT baseline (62.5% vs 57.1%), and the GOAT-Bench per-modality table, which I could only obtain via secondary citation.

**Suggested sequence:** GPU runtime (torch + onnxruntime-gpu) → SigLIP-2 scalar into `value_map.py` (un-skips 5 gates, converts the stub to real VLFM) → OWLv2 object track with confidence propagation (un-skips 2 gates) → **region/traversability segmentation track** (the actual directive; ViPlanner-style closed class set) → replace `city_semantics.py`'s MJCF regions with perception-built `SemanticCandidate`s → OVON-style seen/synonym/unseen eval protocol → GOAT-style per-instance memory → CityWalker and NoMaD as shadow proposers behind the arbiter.

---

**Sources:** [VLFM (arXiv 2312.03275)](https://arxiv.org/abs/2312.03275) · [VLFM full text (ar5iv)](https://ar5iv.labs.arxiv.org/html/2312.03275) · [VLFM code](https://github.com/bdaiinstitute/vlfm) · [CityWalker (arXiv 2411.17820)](https://arxiv.org/html/2411.17820) · [CityWalker code](https://github.com/ai4ce/CityWalker) · [CityWalker project page](https://ai4ce.github.io/CityWalker/) · [SysNav (arXiv 2603.06914)](https://arxiv.org/html/2603.06914v1) · [HM3D-OVON (arXiv 2409.14296)](https://arxiv.org/abs/2409.14296) · [GOAT: GO to Any Thing (arXiv 2311.06430)](https://arxiv.org/abs/2311.06430) · [GOAT-Bench (arXiv 2404.06609)](https://mukulkhanna.github.io/goat-bench/) · [ViNT (arXiv 2306.14846)](https://arxiv.org/pdf/2306.14846) · [NoMaD (arXiv 2310.07896)](https://arxiv.org/abs/2310.07896) · [General Navigation Models](https://general-navigation-models.github.io/) · [visualnav-transformer](https://github.com/robodhruv/visualnav-transformer) · [NaVILA (arXiv 2412.04453)](https://arxiv.org/html/2412.04453) · [StreamVLN (arXiv 2507.05240)](https://arxiv.org/html/2507.05240v1) · [NavFoM (arXiv 2509.12129)](https://arxiv.org/abs/2509.12129) · [FiLM-Nav (arXiv 2509.16445)](https://arxiv.org/abs/2509.16445) · [Uni-NaVid](https://pku-epic.github.io/Uni-NaVid/) · [SemExp (NeurIPS 2020)](https://proceedings.neurips.cc/paper/2020/file/2c75cf2681788adaca63aa95ae028b22-Paper.pdf) · [PEANUT (arXiv 2212.02497)](https://arxiv.org/pdf/2212.02497) · [ESC (arXiv 2301.13166)](https://arxiv.org/pdf/2301.13166) · [OpenFrontier (arXiv 2603.05377)](https://arxiv.org/pdf/2603.05377) · [R2F (arXiv 2603.08475)](https://arxiv.org/pdf/2603.08475) · [ConceptFusion (arXiv 2302.07241)](https://arxiv.org/pdf/2302.07241) · [HOV-SG (arXiv 2403.17846)](https://arxiv.org/abs/2403.17846) · [HOV-SG code](https://github.com/hovsg/HOV-SG) · [SG-Nav (arXiv 2410.08189)](https://arxiv.org/pdf/2410.08189) · [CrossMaps (arXiv 2606.16935)](https://arxiv.org/html/2606.16935v1) · [ViPlanner (arXiv 2310.00982)](https://arxiv.org/abs/2310.00982) · [ViPlanner code](https://github.com/leggedrobotics/viplanner) · [CoNVOI (arXiv 2403.15637)](https://arxiv.org/pdf/2403.15637) · [Sem-NaVAE (arXiv 2602.01429)](https://arxiv.org/pdf/2602.01429) · [MuJoCo Playground](https://www.researchgate.net/publication/388963787_MuJoCo_Playground) · [VoLo — MuJoCo appearance gap (arXiv 2606.07723)](https://arxiv.org/pdf/2606.07723) · [Unreal Robotics Lab (arXiv 2504.14135)](https://arxiv.org/html/2504.14135v2)