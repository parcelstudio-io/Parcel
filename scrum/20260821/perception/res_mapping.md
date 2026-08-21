# Open-Vocabulary Semantic Mapping for Parcel — Research Brief

**Scope:** online, sensor-built semantic maps that replace a labeled world; map persistence and cross-session re-localization. All numbers are from primary sources with denominators where the source states them; where I could not extract a number I say so rather than round one.

---

## 1. The dense-feature-grid lineage (VLMaps → OneMap)

### VLMaps (ICRA 2023)
**What it does.** Back-projects LSeg per-pixel CLIP-space embeddings into a top-down grid `M ∈ R^(H×W×C)`; multiple 3D points landing in one cell are **averaged**. Query = cosine of a text embedding against every cell. Obstacle maps are generated per-embodiment by thresholding.

**Measured.** Built from 12,096 RGB-D frames over 10 Habitat scenes (1,826 frames for AI2THOR). Multi-object nav, **91 task sequences × 4 subgoals**: 59% / 34% / 22% / 15% for 1/2/3/4 consecutive subgoals (CoW 42/15/7/3; LM-Nav 26/4/1/1). Spatial-goal nav, **21 trajectories × 4 subgoals**: 62 / 33 / 14 / 10%. Real robot: **10/20 goals = 50%**, failures attributed to depth error and action noise. Size: HOV-SG later measured VLMaps at **6,068 MB averaged over 8 scenes**. Authors' stated limits: sensitive to reconstruction noise and odometry drift; cannot disambiguate similar objects in clutter.

**Why it matters for Parcel.** This is the only family in the survey that natively answers **"go to the sidewalk."** A dense per-cell feature grid has no notion of object instance, so "stuff" classes (sidewalk, road, grass, crosswalk) are first-class. Everything object-centric downstream (§2) structurally cannot do this.

**Design implication.** A BEV feature grid at Parcel's existing 0.10 m planner resolution over the 161×161-cell rolling window is 25,921 cells ≈ **40 MB at 768-d fp16** — free. A 100 m × 100 m block at that resolution is ~1M cells ≈ 1.5 GB, which is *not* free rolling. So: dense grid **inside the window only**, compressed to the place graph on eviction.

### OneMap — "One Map to Find Them All" (ICRA 2025)
**What it does.** The 2025 correction to VLMaps. Stores CLIP-aligned features **plus per-cell variance** `σ²(x,y)` in a 2D belief map, fed by **SED** patch-level features (a dense open-vocab *segmenter*, not an instance proposer). Explicitly models three uncertainty sources: distance-dependent feature quality, **projective feature leakage at depth discontinuities**, and depth sensor accuracy. Uses sparse inverse Gaussian convolution for speed.

**Measured.** **2 Hz update onboard a Jetson Orin AGX** with a single depth camera + lidar — the cheapest real-time operating point in this entire survey. New multi-object benchmark, **236 episodes / 20 scenes**: 54.24% SR vs 44.92% baseline; progress rate 65.54% (~2 of 3 objects); 1.5× SPL gain by the third object. Variance filters false detections when map confidence is low.

**Why it matters for Parcel.** This is the single closest match to what Parcel needs, and it runs on a *Jetson*. Parcel has an RTX 5000 Ada. The variance channel is also the missing piece for the Narnia problem (§5): it is what lets you say *"I haven't looked there"* instead of *"it isn't there."*

**Design implication.** Adopt the **(feature, variance)** pair as the unit of the region channel, not a bare confidence scalar. Parcel's `SemanticCandidate.confidence: float ∈ [0,1]` currently has no provenance — you cannot recover coverage from it.

---

## 2. The object-centric lineage (ConceptFusion → ConceptGraphs → Clio → DualMap)

### ConceptFusion (RSS 2023)
Pixel-aligned local+global CLIP fusion into 3D via standard SLAM/multi-view fusion; zero-shot, no finetuning. Reports **>40% margin on 3D IoU** over supervised baselines and better long-tail retention. Establishes the fusion primitive the rest of the lineage uses.

### ConceptGraphs (ICRA 2024)
**What it does.** Instance segmentation → per-region CLIP → 3D projection → multi-view association/fusion → VLM captions → LLM-inferred relation edges. Nodes carry geometry + fused CLIP + caption.

**Measured.** Replica mIoU **0.1501** (DualMap's comparison table). **2.0–8.1 s/frame** (Clio's measurement) / **4.188 s/frame** (DualMap's), map construction **"several hours."** Object counts blow up: **751 objects in a cubicle scene at F1 0.25**; apartment 181 @ 0.39; office 339 @ 0.35 (Clio's open-set eval). Authors' limits: fails on multi-concept / negated / compositional queries; needs an LLM at inference.

**Design implication for Parcel: do not build this.** It is the reference architecture everybody cites and nobody deploys. Every 2025–26 winner got fast by refusing to build an exhaustive map.

### Clio (RA-L 2024, MIT-SPARK)
**What it does.** Applies the **Information Bottleneck** to compress task-agnostic primitives into task-relevant objects *given the natural-language task list*. Granularity is decided by the task, not a fixed threshold.

**Measured.** Cubicle **F1 0.80 with 84 objects** vs ConceptGraphs 0.25 with 751; apartment 0.57/48 vs 0.39/181; office 0.55/90 vs 0.35/339 — roughly **an order of magnitude fewer objects at 2–3× the F1**. Replica closed-set: 37.95% mAcc / 36.98% F-mIoU (ConceptGraphs 40.63% mAcc). **0.26–0.31 s/frame on RTX 3090**, ~6× ConceptGraphs; ran **onboard a Boston Dynamics Spot** (i9-13950HX + laptop RTX 4090). Manipulation: 57% grasp success over **21 attempts**. Named limits: CLIP prompt sensitivity, over-clustering, and **averaging CLIP embeddings on merge**.

**Why it matters for Parcel.** Parcel has a *fixed, tiny* task vocabulary — seven tools, and only `navigate_to`/`circle_owner`/`follow_owner` need semantics. That is the most favorable possible input to an IB compressor. Parcel does not need a map of the world; it needs a map of *what its seven tools can be asked about*.

**Design implication.** The task list that drives compression should be derived from the tool schema + observed owner phrasings, and it should be **explicit and inspectable**, not a prompt. This is a natural fit for Parcel's "table not prompt" discipline.

### Bayesian Fields (2025) — the fix for Clio's named flaw
Probabilistic measurement model of CLIP semantics + **Bayesian updating across views**, then IB clustering over Gaussian splats. Directly targets "averaging embeddings on merge is wrong." **Design implication:** whatever Parcel's merge rule is, it should be a Bayesian update over observations with a stated measurement model, not a mean — because a mean drifts silently and produces no signal you can gate on.

### DualMap (2025) — the current practical SOTA
**What it does.** Two maps. **Concrete map**: online object instances with point clouds, features, class IDs, observation histories. **Abstract map**: only static **anchor** objects (furniture unlikely to move) plus their spatial relations to *volatile* objects. Navigation = pick anchor from abstract map → local concrete exploration → re-select if the target moved.

**Measured.** Replica **mIoU 0.2538** (HOV-SG 0.2050, ConceptGraphs 0.1501); object density ratio 0.97. HM3D nav: **70.5% static / 64.8% dynamic in-anchor / 60.3% cross-anchor**. Real world: meeting room 92.3% static / 69.2% dynamic; indoor hallway 75.0% / 53.3%. **0.163 s/frame on ScanNet vs HOV-SG's 8.039 s** (24× faster than ConceptGraphs at 0.276 vs 4.188 s). Memory **2,120.9 MB avg / 2,820.2 MB peak**. RTX 4090 + i7-12700KF.

**Why it matters for Parcel.** The anchor/volatile split is the map-maintenance policy Parcel has none of. A city block has exactly this structure: lampposts, benches, storefronts, and hydrants are anchors; parked cars, trash bins, and people are volatile.

**Design implication.** Persist anchors; do **not** persist volatiles across sessions. Parcel's `route_memory` keyframe labels (≤64/keyframe) should carry anchor-class labels only, or they will encode last Tuesday's parked car as a landmark.

### BBQ / Beyond Bare Queries (2024–25)
DINO embeddings + MobileSAMv2 proposals + LLaVA captions; **metric edges** (Euclidean between bbox centers) rather than semantic edge types; two-call LLM deductive retrieval over a query-filtered scene description. Sr3D **R@1 0.74**, Nr3D **R@1 0.49**; **1–1.5 fps** map construction (~3× ConceptGraphs). **Design implication:** metric edges + LLM-at-query-time beats materializing a semantic relation graph. Parcel already has `relation_registry` and `relations.py` locally — keep relations local and computed, don't store LLM-authored edges.

---

## 3. The hierarchy lineage — and where region-vs-object actually lives

### HOV-SG (RSS 2024)
**What it does.** Floor → room → object hierarchy, each level carrying open-vocab features. Rooms segmented by **watershed on BEV histograms** after wall-skeleton extraction + Euclidean distance field.

**Measured.** 3D semantic segmentation: Replica (**8 scenes**) mIoU **0.231** / F-mIoU 0.386; ScanNet (**5 scenes**) 0.222 / 0.303. Room classification on HM3DSem (**8 scenes**): **73.93% exact / 84.10% approximate**. Sim nav on HM3DSem: object retrieval **37.32% (28 trials)**, navigation **40.41% (31 trials)**. Real 2-story building: retrieval **70.7% (41 queries)**, navigation **56.1% (41 episodes)**. Size **1,493 MB avg over 8 scenes vs VLMaps' 6,068 MB = the 75% reduction**. Authors' own limits: "a large number of hyper-parameters," "time-consuming, rendering the method unsuitable for real-time mapping," "assumes a static environment."

**Why it matters for Parcel.** HOV-SG is the canonical *region* system — and even indoors, where **walls bound the regions for you**, room classification tops out at 73.93% exact. Outdoors there are no walls. Watershed-on-BEV will not transfer to a sidewalk.

### OpenGraph (2024) — the outdoor answer
**What it does.** Five layers: point cloud → **lane graph** (from trajectories, with topology for planning) → instance (objects with centers, boxes, captions, features) → **segment** (road regions partitioned by lane connectivity: straight roadway, intersection, T, L) → environment. Pipeline: RAM → Grounding DINO → TAP → Sentence-BERT → LLaMA, zero-shot, no finetuning.

**Measured.** SemanticKITTI F1: seq 03 **0.7302**, seq 05 **0.7749**, seq 08 **0.7633**. Object retrieval top-1 recall: ontology queries **0.90**, proximity **0.80**, functionality **0.63**. No runtime reported in the paper.

**Why it matters for Parcel — this is the structural answer to the focus question.** OpenGraph represents **traversable surface topologically (segment/lane layer)** and **objects instance-wise (instance layer)**, as two separate channels that never merge. Note the retrieval gradient: 0.90 for "what kind of thing is it" collapsing to **0.63 for "what is it for."**

**Design implication.** "Go to the sidewalk" should resolve against a *segment/surface* channel, and "go to the bench" against an *instance* channel — and these should be two different producers with two different confidence models, not one map queried twice. This is exactly Parcel's existing `kind ∈ {object, region}` split, which means the type system is already right and only the producers are missing.

### Search3D (RA-L 2025)
Hierarchical open-vocab 3D segmentation at three granularities: **object part / whole object / region-described-by-attribute (e.g. material)**, using **SigLIP** for both object-node and part-segment embeddings. Contributes a scene-scale part-segmentation benchmark on MultiScan plus open-vocab part annotations on ScanNet++.

**Why it matters.** It's the explicit statement that granularity is a first-class axis, and it uses SigLIP — the same encoder family already in `instructnav/siglip2_onnx.py`.

### RoboHop (ICRA 2024) — the cheapest thing that works
**What it does.** No 3D reconstruction at all. A **purely topological graph whose nodes are image segments**; edges from (a) segment-descriptor association between consecutive images and (b) pixel-centroid adjacency *within* an image. Yields a continuous notion of "place" from inter-image segment persistence. Supports relational queries like "the closest available seat to Merlo's coffee shop."

**Design implication for Parcel.** This is the floor on representation cost, and it is startlingly close to what `route_memory/place_graph.py` already is — a topological graph of visited places with per-keyframe embeddings and labels. Adding **segment-level** nodes to existing keyframes is a smaller change than building a metric semantic map, and it gets region semantics ("this stretch of sidewalk") for free because a segment *is* a region.

---

## 4. Persistence and re-localization (the part Parcel is furthest along on and most exposed by)

### The honest state of the art
- **"Build Once, Monitor Continuously" (2024):** frontier exploration builds a persistent open-vocab semantic map, then *incrementally updates* it rather than rebuilding — explicitly handling object **removal, addition, and movement** on revisit. Numbers were not extractable from my fetch.
- **OVAL (2026) — lifelong ObjectNav.** Memory entry = `{label, image buffer (≤N), 3D position, HSV scene descriptor, confidence}`. Crucially, **visual features replace text labels as the index key** because labels are error-prone. Instance matching uses `Sm = λ_H·Sim(H_i,H_j) − λ_X·Sigmoid(k‖X_i−X_j‖)`, with SuperGlue for ambiguous cases; higher-confidence instances overwrite lower. **Lifelong ObjectNav, 1000 episodes:** HM3D **68.1% SR / 33.8% SPL**; MP3D **44.1% / 18.6%**. Standard ObjectNav: HM3D 58.2%/24.5%, MP3D 41.1%/15.3% — i.e. **~10 points of SR come purely from retained memory.** Runs at **1.14 FPS on an RTX 4090D (24 GB)** (VLFM 1.67, GOAT 1.85). Memory persists across episodes in the same scene/floor and **clears on scene change**.
- **BinTrack / GangnamLoop (2026)** — the most Parcel-shaped datapoint I found. **Unitree Go2 + Intel RealSense D455 + Livox MID-360**, public urban streets, day/night revisits of identical locations: 8 recordings, 4 round-trip routes, **221 minutes, 383,800 RGB frames, 360 queries**, ≤10 m annotator disagreement tolerance. Memory = three complementary captions per segment (full 2×2 concat / center / detail-for-storefront-text) from Qwen2.5-VL-7B; retrieval by **binary search over trajectory intervals, O(log n)**, cost `2·c_ret·⌈log₂(n/k_leaf)⌉ + c_ver`. Results: **SpaceLocQA (270 queries, τ=15 m): 67.4% overall** (74.4 basic / 65.6 local / 62.2 global) vs open-source Meta-Memory 44.6%, matching closed-source GPT-4o's 62.2% global. **GangnamLoop: 45.3%** vs open-source ReMEmbR 18.0%. **Latency 59 s/query** (45–70 s), >1.5× speedup over priors. Compute: **2× RTX 6000 Ada (48 GB each) + 128 GB RAM**; a lightweight ~20 GB single-GPU variant using 7B-class models throughout. Stated limits: offline captioning per new route; **per-trajectory memory with no cross-trajectory benefit (Appendix J)**; **24.4% on the 600 m+ trajectory**; mean error 59.7 m masking catastrophic failures.
- **ReMEmbR (NVIDIA, 2024/25):** caption short video segments with time + position metadata into a vector DB; LLM issues iterative text/time/position queries at ask time. NaVQA: **210 examples** across three horizons up to 20 minutes. Deployed on Nova Carter via Isaac ROS.
- **Belief consistency in persistent maps (2026):** conformal prediction + Bayesian updating to reconcile VLM semantic evidence against geometric evidence, evaluated on ScanNet and KITTI-360. Core claim: **VLM labels alone are insufficient for a persistent map; geometric agreement is what licenses selective trust.** I could not extract its tables.
- **AnyLoc (RA-L):** zero-shot universal VPR — frozen DINOv2 features + unsupervised **VLAD**, no training, works indoor/outdoor/aerial. Beats MixVPR by ~5% and CosPlace by ~20% R@1 on average across indoor sets; reported R@1 spans ~65–100% depending on dataset.

**Why this matters for Parcel.** `RoutePlaceGraph` already has the schema, the frame discipline, the re-anchor semantics, and the all-or-nothing load. What it does not have is **any way to recognize that it is back**. Its `embed_fn` defaults to `stub_embed_image` — a 64-d deterministic hash — and its own `DOES_NOT_PROVE` string says so out loud: *"does not prove … visual place recognition recall."*

**Design implications.**
1. **AnyLoc-style VLAD over DINOv2 (or SigLIP-2) is the drop-in for `embed_fn`.** The seam already matches `siglip2_onnx.embed_image`'s call shape. That single injection converts the place graph from a visit log into a re-localizable map.
2. **Index by visual feature, not by label** (OVAL's central finding). Parcel's keyframes already carry both — make the embedding authoritative and labels advisory.
3. **Budget ~20 points of loss for outdoor revisit.** 67.4% → 45.3% is the same system on the same task, differing only by "day/night revisits of the same public streets from a 0.8 m Go2 viewpoint." Any target set from indoor benchmark numbers will be wrong.
4. **Do not assume cross-session merging works.** BinTrack tried cross-trajectory retrieval over shared landmarks and found **no benefit**. Parcel's graph is structurally multi-session; that is not the same as being multi-session *useful*.

---

## 5. Open-set failure — what replaces the known-place list

Today `validate_place()` admits an unheard-of noun for authority parity, and `PlaceAdmission` (card R20, from live_run_1 2026-08-20 §d) refuses goal-phrased directives naming nothing resolvable, offering `PLACE_OFFER_LIMIT = 3` real places back, with `_EXPLICIT_SEARCH_PATTERN` as the escape hatch. That gate exists because "Go to Narnia" and "Take me to the moon" ran as missions for **4.25 s and 10.7 s of `state=searching reason=scan_behavior_rotate`**.

**Finding: no surveyed system abstains.** Not ConceptGraphs, not DualMap, not OVAL, not BinTrack (which states plainly that "queries depend on target appearing in the memorized trajectory" and offers no absence verdict), not OneMap, not CausalNav. **Parcel's deterministic refusal is ahead of the published field**, and the primary risk of this cutover is regressing it.

What the literature *does* offer to rebuild it on a learned vocabulary:

1. **Coverage, not membership.** OneMap's per-cell variance is the mechanism that distinguishes *unobserved* from *absent*. The refusal must split into two verdicts: `PLACE_UNOBSERVED` (plausible referent, no coverage → offer the search) vs `PLACE_UNKNOWN` (no plausible referent at any confidence → refuse and offer nearest three). Parcel currently has only the second.
2. **CLIP/SigLIP cosine is not calibrated.** Reported "good" thresholds are dataset-specific (~0.37–0.38 in one family of work; ~0.7 retaining ~96% of true matches at <1% FP in another). A bare cosine gate on "narnia" against real candidates is **not** zero.
3. **Negative/background prompt sets + softmax rectification.** Learning-Background-Prompting-style approaches cluster background-specific prompts and debias the softmax when background clusters overlap novel classes. The stated design rule: a negative vocabulary must occupy a *sweet spot* — far enough from the positive distribution to suppress false activations, close enough to remain informative.
4. **Monotonic calibration + multi-source arbitration (measured on a quadruped).** The Go1 semantic-exploration work uses `C̃ = clamp((C − τ)/(1 − τ))` to kill low-confidence noise before fusion, then fuses scene-level (Qwen2.5-VL) and object-level (GroundingDINO) evidence weighted by **IoU spatial consistency and depth feasibility**. That arbitration was worth **+4.8 points of semantic accuracy (85.3% → 90.1%)**. Real robot: **Unitree Go1 + D435i, 5 environments × 20 trials, SR 40–55%, SPL 26.8–35.4%, OASR 71.9–77.2%.** Latency per decision cycle: Qwen-VL ~2.5 s, GroundingDINO ~1.2 s, utility ~2.0 s, with control at 12–50 Hz underneath.
5. **Conformal prediction for a coverage guarantee.** KnowNo (CoRL 2023) aligns an LLM planner's uncertainty to a user-specified target success rate and asks for help otherwise — statistical guarantees, no finetuning. The 2026 belief-consistency work applies the same machinery *to the map*, using conformal bounds to decide when a VLM label may be trusted. This is the only route I found to a refusal threshold that is **derived** rather than tuned — which matters, given how much of Parcel's config is derived-by-construction.

**Concrete recommendation.** Re-source `known` as the union of: (i) place-graph keyframe labels already persisted (≤64/kf), (ii) live in-window candidates above a calibrated operating point, (iii) a small always-known a-priori ontology of stuff classes the perception stack can recognize without ever having seen them here. Then add the `PLACE_UNOBSERVED` verdict, gated on **map coverage** at the query bearing, and route it to the existing explicit-search path rather than to a refusal.

---

## 6. Compute and latency — the real budget

| System | Per-frame / cycle | Hardware | Map size |
|---|---|---|---|
| ConceptGraphs | 2.0–8.1 s (Clio) / 4.188 s (DualMap) | RTX 3090 | hours to build |
| HOV-SG | **8.039 s** | — | 1,493 MB / 8 scenes |
| VLMaps | — | — | 6,068 MB / 8 scenes |
| BBQ | 0.67–1.0 s (1–1.5 fps) | — | — |
| OVAL | 0.88 s (1.14 FPS) | RTX 4090D 24 GB | — |
| Clio | **0.26–0.31 s** | RTX 3090; onboard Spot w/ 4090 laptop | — |
| DualMap | **0.163 s** (ScanNet) | RTX 4090 + i7-12700KF | 2,121 MB avg / 2,820 peak |
| OneMap | **0.5 s (2 Hz)** | **Jetson Orin AGX** | — |
| CausalNav | **105 ms total cycle** | RTX 4070 + i9-13900H | — |
| BinTrack (query) | **59 s/query** | 2× RTX 6000 Ada 48 GB (or ~20 GB lite) | vector DB |

**Detector-level costs are not the bottleneck.** The Jetson AGX Orin study (JetPack 6.0, CUDA 12.2, TensorRT 8.6.2) measured: NanoOWL patch32 FP16 **9.81 ms**, YOLO-World-S **26.07 ms**, NanoOWL patch14 FP16 **195.69 ms**; EfficientViT-SAM-L0 FP16 **7.88–10.19 ms**. Best end-to-end **47.51 FPS at 84.64% mIoU** (NanoOWL p32 + EffViT-L0); best YOLO-World pipeline 26.68 FPS. **Detection is ~10 ms. Fusion, graph maintenance, and LLM calls are the seconds.**

**CausalNav's rate stratification is the design to copy:** object tracking **30 Hz**, spatio-temporal filtering **20 Hz**, local planning **10 Hz**, **graph updates only 1 Hz** — 105 ms total cycle on an RTX 4070. The semantic map does *not* need to run at control rate.

**Parcel's budget.** RTX 5000 Ada 32 GB, minus a resident Gemma-4-26B-A4B (≈14–15 GB at 4-bit). Remaining ~15 GB comfortably holds: SigLIP-2 so400m ONNX fp16 (~0.9 GB) + OWLv2-L fp16 (~1.5 GB) + a SED/CAT-Seg-class dense segmenter with a ConvNeXt-L CLIP backbone (~1.5–2 GB) ≈ **4–5 GB**. What does *not* fit alongside a resident reasoner is a 3DGS/NeRF semantic field — **VISTA** (open-vocab task-relevant exploration with online semantic Gaussian splatting) required a **dedicated offboard RTX 4090** and streams data off-robot; its own limits list "CLIP embeddings restrict search to object-centric tasks" and "cannot distinguish multiple instances of the same object." Skip that branch.

### What degrades gracefully, and what falls off a cliff

**Graceful:** BEV feature grids with variance (unobserved cells report high variance — you get "I don't know," not a wrong answer); topological/segment maps (you lose precision, not validity); frontier-value/evidence ledgers (evidence decays smoothly — Parcel already has `value_evidence.py` doing exactly this).

**Cliff-edges, all of them silent:**
1. **FP16 quantization of the segmentation encoder.** The Jetson study measured mIoU collapse from **0.81–0.92 down to 0.4–0.5** on specific EfficientViT-SAM FP16 encoder configurations. No error is raised. It also found the distilled model (NanoSAM) was *robust* under aggressive quantization while the efficient-architecture model was **"brittle"** — i.e. you cannot infer quantization safety from architecture quality.
2. **Averaging CLIP embeddings on instance merge** (Clio names it; Bayesian Fields fixes it) — merged nodes drift semantically with no observable signal.
3. **Lighting and appearance change.** OSMa-Bench exists specifically to measure open-semantic-map degradation under varying lighting (I could not extract its tables — flagging as a gap). GangnamLoop's day/night pairing is the empirical version: **67.4% → 45.3%**.
4. **Odometry drift** — VLMaps' own named failure. Parcel's place graph already handles the MAP re-anchor case honestly, which is more than most of these systems do.

---

## 7. One note on `models/nav/citywalker`

**CityWalker** (CVPR 2025) trains a point-goal action policy on 1,000+ hours of web city-walking video; zero-shot it beat fine-tuned baselines, and performance scaled monotonically with data past 1,000 hours. Deployed on a **Unitree Go2** (fisheye camera, velocity-control API over native gait) and a Coco wheeled delivery robot. **It has no semantic map.** CausalNav matched CityWalker's long-range success rate exactly (**80% vs 80%, over 25 tasks × 10 trials**) while cutting collisions from **4.5 to 1.2** and adding >500 m real-world capability — purely by adding the hierarchical graph on top. CityWalker is the *locomotion* half; it will not close the perception-generalization gap, and the 1.7 GB is not a substitute for a map.

---

# Design pressure

## What our existing assets get right

1. **The things/stuff split is already in the type system.** `SemanticCandidate.kind ∈ {"object", "region"}` with a `polygon` field (`navigation/semantic_map.py:40, 24`) is precisely the division OpenGraph enforces with separate instance and segment layers, Search3D with separate granularity levels, and HOV-SG with objects vs rooms. Every object-centric system in §2 had to bolt this on or gave up on region queries entirely. **No refactor is needed — only producers.**

2. **`arrival_semantics` is stronger than the published field.** INSIDE/NEAR/SOCIAL as a **local table**, with hosted hints admitted only when they *agree* or when they *refine a genuinely UNKNOWN class* **and** the local map supplies the geometry (grounded polygon for `inside`, person anchor for `social`) — with `face`/`do_not_cross`/`standoff_m` unreachable from any hosted argument. LangMap's headline finding is that current systems show exactly the **"gaps between region- versus object-level navigation"** and mishandle hierarchical/relative descriptions. Parcel's 36/36 relation bench plus local override is a better answer than any of these papers has.

3. **The cutover seam is already narrow and typed.** `ObservationSemanticMap.query()` reads one key (`observation.extras["semantic_candidates"]`, capped at 64) and `semantic_candidates_from_observation()` is documented as "the **one** semantic ingress on the mission path." Replacing MuJoCo `semantic_regions`/`semantic_objects` (parsed in `backends/mujoco.py:107–308`) with a learned producer is a **single-producer change**, not a stack rewrite. This is a genuinely unusual position to be in.

4. **`RoutePlaceGraph` is the persistence layer everyone else bolts on last.** MAP-frame-only ingestion with an explicit refusal of ODOM; re-anchor edges *recorded but flagged and excluded from routing*; versioned schema with all-or-nothing load; per-keyframe `embedding` + `labels` (≤64); derived constants (0.50 m spacing from 0.10 m grid res × non-overlapping 0.25 m arrival discs; 2.00 m contiguity; 8.05 m attach radius = half the 161-cell planner window). Note that **0.50 m keyframe spacing ≈ 4 keyframes/m² is already a coarse BEV semantic lattice** — the persistence substrate for a learned map exists.

5. **Uncertainty-directed exploration machinery already exists.** `value_evidence.py` (match-scored paints, misses, `evidence_count`, a stated SigLIP operating point held by reference), plus `value_map.py` and `value_directed_scan.py`. This is the same primitive OneMap and VISTA use for semantic frontier selection.

6. **The detection chain already has the right components.** `detection_adapter/` contains `owlv2_onnx.py`, **`multi_view_confirm.py`**, **`false_positive_memory.py`**, `metric_localizer.py`, `noise.py`, and a tiered `perception_chain.py` with T0 pass-through. Multi-view confirmation is exactly the mechanism Bayesian Fields and the Go1 calibration work found necessary, and a tiered chain means the cutover can be staged and *measured* rather than flipped.

7. **The Narnia refusal is a genuine differentiator.** Nothing surveyed abstains. Keep it.

## What they are missing

1. **No stuff-channel producer.** Everything downstream of `kind="region"` exists; nothing produces one from sensors. **OWLv2 is a box detector — it cannot emit a sidewalk polygon.** The missing pieces are (a) a dense open-vocab segmenter in CLIP/SigLIP space (SED-class; SED is the cheaper choice — hierarchical encoder, no extra backbone, **linear cost in input size**, whereas CAT-Seg's cost grows with the number of open-vocab classes), (b) BEV projection through D455 depth + MAP pose, (c) a contour step to turn a thresholded similarity field into the `polygon` the type already carries. This is the load-bearing gap for the owner's canonical example.

2. **No per-candidate uncertainty with provenance.** `confidence: float ∈ [0,1]` cannot express "not looked at." All three of OneMap's uncertainty sources apply directly to a D455 on a 0.8 m-tall quadruped — distance-dependent feature degradation, **projective feature leakage at depth discontinuities** (severe at curb edges, which is exactly where sidewalk boundaries live), and depth accuracy.

3. **No absence verdict and no coverage estimate.** `GroundingOutcome` has `AMBIGUOUS` and `honest_not_found_reply(query, scanned, searched)`, but the vocabulary check is against a static list. There is no `PLACE_UNOBSERVED`, and no coverage measure that would justify either verdict once the list is learned.

4. **No cross-session re-localization.** `embed_fn` defaults to `stub_embed_image` — a 64-d deterministic hash — and `DOES_NOT_PROVE` explicitly disclaims VPR recall. Nothing matches a live frame against stored keyframes. Without this, session 2 builds a *different map*, and OVAL's measured **~10 points of SR** from retained memory is simply forfeited.

5. **No map maintenance.** Nothing removes, moves, or ages a candidate. DualMap's anchor/volatile split and "Build Once, Monitor Continuously"'s add/remove/move handling are both absent. `false_positive_memory.py` is a rejection cache, not a decay policy.

6. **Semantic matching is string/alias, not embedding.** `_matches()` walks `city_semantics.CLASS_ALIASES`, sourced from `scene_semantics()` loading `configs/scenes/city_block.semantics.yaml` — **a curated closed-vocabulary sidecar, which is the labeled world in miniature.** Its own comment records the substring-fallback failure: *"tree" matched a lamppost via its "streetlight" alias ("tree" ⊂ "street")*. With a learned vocabulary there is no alias table to fall back to, and the substring path becomes the only path whenever weights are absent.

7. **Nine weight-gated tests still skip** (OWLv2 ×2, SigLIP-2 ×5, storefront OCR ×1, plus `test_runtime_activation.py:496`). Every implication above is unverifiable until those run. **That is the first card, not the last** — you cannot calibrate an operating point against a hash stub.

## Pitfalls

1. **Do not build a ConceptGraphs- or HOV-SG-class map.** 2.0–8.1 s/frame and 8.039 s/frame respectively; HOV-SG's authors say in print it is "unsuitable for real-time mapping" and "assumes a static environment." Every 2025–26 winner got fast by refusing to map exhaustively.

2. **Do not expect an object-centric pipeline to answer "the sidewalk."** SAM-class proposals fragment ground planes; instance merging assumes bounded objects. This is the most likely way a cutover ships, passes its object tests, and then fails on the owner's exact stated example.

3. **Treat FP16 as an accuracy change, not a perf change.** Measured mIoU collapse **0.81–0.92 → 0.4–0.5** on specific FP16 encoder configs, silently. With a Gemma resident on a 32 GB card the pressure to quantize is real. Pin a real-weight accuracy cell before any precision change lands.

4. **Do not let the hosted model become the vocabulary.** The arrival table already refuses hosted `face`/`do_not_cross`/`standoff_m`. Region *membership* needs the same discipline: `inside` must be decided by a polygon containment test against grounded geometry, never by a VLM asserting "you're on the sidewalk." CausalNav's `η(n) = β·κ_spatial(n,L) + (1−β)·Λ(ζ)` is the pattern — **the language model ranks; geometry decides.**

5. **Do not weaken the Narnia gate on the grounds that "the vocabulary is open now."** live_run_1 measured the cost: 4.25 s and 10.7 s of `scan_behavior_rotate`. An open vocabulary makes this **more** likely, not less, because SigLIP cosine for "narnia" against real candidates is not zero. Any replacement threshold must be a calibrated operating point with a negative/background prompt set — and the negatives must sit in the sweet spot: far enough to suppress false activation, near enough to stay informative.

6. **Do not route the place graph over learned semantics.** `waypoints_toward` deliberately returns only recorded, non-re-anchor edges and never synthesizes a shortcut. If learned regions start feeding routing, that property dies. Keep the semantic map as goal **resolution** and the place graph as goal **reachability** — the same split OpenGraph makes between its lane graph (planning) and instance layer (reference).

7. **Cross-session semantic merging is not free.** BinTrack tested cross-trajectory retrieval over shared landmarks and reported **no benefit** (Appendix J); its memory is per-trajectory by design. OVAL clears memory on scene change. Nothing I found supports "just merge the sessions."

8. **Set targets from outdoor-revisit numbers, not indoor ones.** Same system, same task, indoor-static vs Go2-on-public-streets-day/night: **67.4% → 45.3%**. Long routes are worse still: **24.4% on the 600 m+ trajectory**, with a 59.7 m mean error masking catastrophic individual failures.

9. **The region channel will be the weakest link — plan for it.** HOV-SG gets **73.93% exact / 84.10% approximate** room classification with **walls doing the segmentation**. Outdoor regions have no walls, watershed-on-BEV will not transfer, and OpenGraph only recovers road segments because it has a *lane graph from trajectories* to partition against. Parcel's analogue of that lane graph is the place graph — which is the one asset that makes an outdoor region channel plausible at all, and the reason the persistence work and the region work are the same card, not two.

---

**Sources:** [VLMaps](https://arxiv.org/abs/2210.05714) · [vlmaps.github.io](https://vlmaps.github.io/) · [ConceptFusion](https://arxiv.org/abs/2302.07241) · [CLIP-Fields](https://arxiv.org/abs/2210.05663) · [OpenScene (CVPR'23)](https://openaccess.thecvf.com/content/CVPR2023/html/Peng_OpenScene_3D_Scene_Understanding_With_Open_Vocabularies_CVPR_2023_paper.html) · [ConceptGraphs](https://concept-graphs.github.io/) · [HOV-SG (RSS'24)](https://arxiv.org/abs/2403.17846) · [Clio](https://arxiv.org/html/2404.13696v3) · [Bayesian Fields](https://arxiv.org/pdf/2503.05949) · [DualMap](https://arxiv.org/html/2506.01950v1) · [OneMap](https://arxiv.org/html/2409.11764v2) · [OpenGraph](https://arxiv.org/html/2403.09412v2) · [Search3D](https://arxiv.org/abs/2409.18431) · [RoboHop](https://arxiv.org/abs/2405.05792) · [BBQ](https://arxiv.org/html/2406.07113v2) · [CausalNav](https://arxiv.org/html/2601.01872v1) · [BinTrack / GangnamLoop](https://arxiv.org/html/2606.16902v1) · [OVAL](https://arxiv.org/html/2604.12872v1) · [ReMEmbR](https://arxiv.org/pdf/2409.13682) · [Build Once, Monitor Continuously](https://arxiv.org/pdf/2409.15493) · [Belief Consistency in Persistent Maps](https://arxiv.org/pdf/2606.00318) · [Dynamic Resilient Spatio-Semantic Memory](https://arxiv.org/pdf/2606.00576) · [KnowNo](https://arxiv.org/abs/2307.01928) · [AnyLoc](https://arxiv.org/pdf/2308.00688) · [Confidence-Calibrated Legged Exploration](https://arxiv.org/html/2509.20739) · [VISTA](https://arxiv.org/html/2507.01125v1) · [LangMap](https://arxiv.org/pdf/2602.02220) · [Uncertainty-Informed Active Perception](https://arxiv.org/pdf/2506.13367) · [OSMa-Bench](https://arxiv.org/pdf/2503.10331) · [Semantic Mapping Survey](https://arxiv.org/html/2501.05750v1) · [Edge OV-perception latency study](https://pmc.ncbi.nlm.nih.gov/articles/PMC12583037/) · [SED](https://arxiv.org/html/2311.15537) · [CAT-Seg](https://arxiv.org/abs/2303.11797) · [SigLIP 2](https://arxiv.org/abs/2502.14786) · [CityWalker](https://arxiv.org/abs/2411.17820) · [Quadruped online object-level mapping](https://arxiv.org/pdf/2510.18776)