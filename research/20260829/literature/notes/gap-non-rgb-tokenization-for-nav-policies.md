# Non-RGB tokenization for navigation policies: LiDAR/BEV/occupancy, audio/speech, and structured state

Literature note, 2026-08-29. Gap covered: how to put LiDAR occupancy grids / BEV maps, audio and
speech events, and user/plan context INTO a transformer navigation policy - token budgets,
encoders, and the measured effect on success.

Method: every source below was located by web search and then read (arXiv HTML, or the arXiv PDF
extracted locally with pdftotext when the HTML fetch returned binary) before any number was
recorded. Numbers are quoted from the source text or tables; where only an abstract was
readable, that is stated. Nothing here is from memory.

Sections:
1. Metric / BEV / occupancy maps as tokens inside VLN transformers (BEVBert, GridMM, BSG, VER)
2. Maps as images or annotations for VLM navigators (MapNav, TopV-Nav, Mem2Ego, FloorPlan-VLN)
3. Structured object/frontier/path tokens (FOM-Nav) and LiDAR-to-LLM tokens (LiDAR-LLM)
4. LiDAR in learned policies on quadrupeds (REASAN on Go2 + Mid-360 + Orin; ViLiNT; HiCo-Nav)
5. Goal, embodiment, proprioception, and identifier tokens (NavDP, NoMaD, ViLiNT, GR00T N1, NavFoM)
6. Audio-visual navigation: encoders, tokens, sim2real (SoundSpaces 2.0, AVLEN, Sim2Real-AVN,
   ASGF-Nav, Samba, MAGNet/SAVN-CE, LH-AVLN, AVLMaps, BAT/Spatial-AST)
7. Speech-conditioned policies (VLAS, Audio-VLA, adverb-constrained speech navigation)
8. Cross-source table: token counts, encoders, measured effects
9. What this means for Parcel's Model A / Model B
10. Open questions and gaps

---

## 1. Metric / BEV / occupancy maps as tokens inside VLN transformers

### 1.1 BEVBert: Multimodal Map Pre-training for Language-guided Navigation
- URL: https://arxiv.org/abs/2212.04385 (PDF read at https://arxiv.org/pdf/2212.04385)
- An, Qi, Li, Huang, Wang, Tan, Shao. ICCV 2023. Code: https://github.com/MarSaKi/VLN-BEVBert
- What it is: a hybrid topo-metric map. A local metric map of grid cells is fused with the
  instruction by a "cross-modal short-term transformer" (cell tokens + text), while a global
  topological map of nodes is fused by a long-term transformer; action scores from both are
  dynamically fused. Pre-training tasks include masked language modeling, hybrid single-step
  action prediction, and masked semantic imagination over map cells (C = 40 MP3D classes).
- Map/token spec (from text): "We set the metric map scale as 21 x 21, and 0.5m (the entire map is
  thus 10.5m x 10.5m)" - i.e. 441 cell tokens, each cell carries a feature plus a position
  embedding built from the normalized distance to the map centre (agent).
- Table 7 (R2R val unseen), the only ablation found that prices map size in FLOPs:
  | scale | cell | map | short-term FLOPs | NE | OSR | SR | SPL |
  | 11x11 | 0.5 m | 5.5 m | 4.5 G | 2.98 | 81.61 | 73.27 | 63.07 |
  | 11x11 | 1.0 m | 11.0 m | 4.5 G | 2.82 | 83.01 | 74.58 | 63.37 |
  | 21x21 | 0.5 m | 10.5 m | 15.2 G | 2.81 | 83.65 | 74.88 | 63.60 |
  | 31x31 | 0.5 m | 15.5 m | 32.7 G | 2.83 | 83.23 | 74.84 | 64.88 |
  "With a larger map scale, Row 4's performance does not increase obviously." Going from 121 to
  961 cells costs 7.3x FLOPs for +1.6 SR.
- Headline: "in test-unseen splits, 73 SR on R2R dataset, 59 SR on R2R-CE dataset, and 54.2 SDTW
  on RxR". On R2R-CE "4 SR and 2 SPL improvement over the topo-map-only ETPNav". RxR val unseen
  SR 68.5 / nDTW 69.6, test unseen SR 64.4.
- Map-vs-no-map: the "hybrid maps" ablation shows topo-only rows lose "due to the lack of metric
  information for local spatial reasoning" (text).
- License: arXiv paper; code repo (MIT per GitHub, not verified here).

### 1.2 GridMM: Grid Memory Map for Vision-and-Language Navigation
- URL: https://arxiv.org/abs/2307.12907 (PDF read at https://arxiv.org/pdf/2307.12907)
- Wang, Li, Yang, Liu, Jiang. ICCV 2023. Code: https://github.com/MrZihan/GridMM
- What it is: a top-down, egocentric, dynamically growing N x N grid whose side length L_t grows
  with the visited area; every historical CLIP-ViT grid feature is projected into a cell, and
  an "instruction relevance aggregation" pools the features in each cell into one D-dim token.
  Map tokens, panoramic view tokens and trajectory tokens enter a two-stage transformer.
- Token spec: default N = 14 (Table 7), i.e. 196 map tokens, in dynamically relative
  (egocentric) coordinates.
- R2R-CE val unseen (Table 4): GridMM SR 49 / SPL 41 (test unseen 46 / 39) vs DUET (topological
  map, same waypoint predictor) 47 / 39.
- Table 5, the cleanest map-type ablation on R2R-CE val unseen:
  | map type | OSR | SR | SPL |
  | No map | 57.24 | 45.19 | 37.82 |
  | DUET topological map | 57.91 | 47.02 | 38.86 |
  | Top-down semantic map (CM2-style, conv over classes) | 57.46 | 46.36 | 38.41 |
  | Map with object-detector features | 59.12 | 47.61 | 40.13 |
  | GridMM (grid features) | 60.90 | 49.05 | 40.99 |
  A plain semantic-class top-down map is worth only +1.2 SR over no map; dense feature grids are
  worth +3.9 SR.
- Table 7 (map scale): 8x8 SR 47.07 / SPL 39.49; 14x14 49.05 / 40.99; 20x20 49.86 / 42.52.
- Table 6: absolute-coordinate map 48.72 SR vs egocentric relative 49.05 - "the egocentric
  relative coordinate system works better than the absolute coordinate system".

### 1.3 Bird's-Eye-View Scene Graph for Vision-Language Navigation (BSG)
- URL: https://arxiv.org/abs/2308.04758 (PDF read at https://arxiv.org/pdf/2308.04758)
- Liu, Wang, Wang, Yang. ICCV 2023.
- What it is: BEVFormer-style BEV queries lifted from multi-view images and supervised by
  BEV 3D detection; node embeddings of a global scene graph are built from the BEV grids around
  each candidate node; local grid-level and global graph-level action scores are fused.
- BEV spec: "The default size of BEV queries is 11 x 11 with four reference points (i.e., Z = 4)
  for each query, and the perception ranges are [-5.0 m, 5.0 m] for x and y axes", height
  anchors uniformly in [-1.0 m, 2.0 m]; 9 neighbouring grids per node embedding. So 121 BEV
  tokens covering a 10 m square at ~0.9 m/cell.
- Table 4 (val unseen):
  | model | REVERIE SR | SPL | RGS | R2R SR | SPL |
  | basic agent (DUET) | 46.98 | 33.73 | 32.15 | 71.52 | 60.36 |
  | BEV branch only | 39.03 | 25.73 | 25.09 | 65.56 | 52.21 |
  | w/o detection loss | 49.25 | 32.44 | 33.21 | 72.65 | 60.20 |
  | full | 52.12 | 35.59 | 35.36 | 73.73 | 62.33 |
  BEV alone is worse than panoramas alone; BEV + panoramas + a 3D-detection auxiliary loss gives
  +5.1 SR on REVERIE. The detection supervision is worth +2.9 SR by itself.
- Camera images at 1280 x 1024 into the BEV encoder; scale/perception range affects detection
  accuracy and thereby navigation (Fig. 5).

### 1.4 Volumetric Environment Representation for Vision-Language Navigation (VER)
- URL: https://arxiv.org/abs/2403.14158 (PDF read at https://arxiv.org/pdf/2403.14158); CVPR 2024.
  Code: https://github.com/DefaultRui/VLN-VER
- Liu, Wang, Yang. Voxelizes the world into X x Y x Z cells with features gathered by 2D-3D
  sampling; coarse-to-fine extraction with multi-resolution occupancy labels at 0.4 m and
  0.2 m; multi-task heads predict 3D occupancy, room layout and 3D boxes; a "volume state"
  over surrounding cells feeds local action prediction. "We annotate over 50 billion voxels".
- Table 4 (val unseen): w/o volume state REVERIE SR 52.31 / SPL 34.91, R2R 72.71 / 61.13; w/o
  episodic memory 49.33 / 33.71, 68.21 / 61.70; full 55.98 / 39.66, 75.80 / 65.37.
- Table 8 (which auxiliary 3D task helps, R2R val unseen): occupancy only SR 74.90 / SPL 63.82;
  occupancy + objects 75.21 / 64.79; objects + room 74.03 / 63.51; occupancy + room 74.97 /
  64.66; all three 75.80 / 65.37 (occupancy mIoU 12.93, detection mAP 33.57, layout IoU 66.45).
- Headline: "about 3% SR and 4% SPL on R2R test, 4% SR and 4% SPL on REVERIE val unseen".
- Why it matters: occupancy prediction as an auxiliary loss on top of a volumetric token grid
  is the measured lever; occupancy alone is worth ~+2 SR over the no-volume baseline.

## 2. Maps as images or annotations for VLM navigators

### 2.1 MapNav: Annotated Semantic Map memory for VLM-based VLN (ACL 2025)
- URL: https://arxiv.org/abs/2502.13451 (full text read at https://arxiv.org/html/2502.13451v5)
- Backbone LLaVA-OneVision: SigLIP-so400m-patch14-384 encoder, Qwen2-7B-Instruct LLM.
- Representation: a C x W x H top-down tensor, C = number of object classes + 4 (obstacles,
  explored, agent position, trajectory), built from RGB-D point clouds and Mask2Former masks;
  text labels ("chair", "bed") are drawn at region centroids. The annotated map is rendered as
  an IMAGE and passes through the same SigLIP encoder as the RGB frame, then its own MLP
  projector - i.e. the map costs one image's worth of tokens regardless of trajectory length.
- R2R-CE val unseen: ASM + current RGB SR 36.5 / SPL 34.3; ASM + current + 2 history frames
  SR 39.7 / SPL 37.2; NaVid with all frames 37.4 / 35.9. RxR-CE zero-shot: 32.6 / 27.7 vs
  NaVid 23.8 / 21.2.
- Table 4 ablation (R2R-CE val unseen): no map SR 27.3 / SPL 23.2; plain top-down obstacle map
  26.4 / 21.9; semantic map without text labels 29.1 / 24.5; full ASM 36.5 / 34.3. A raw
  occupancy image is worth nothing to the VLM; semantic classes +1.8 SR; text annotations
  +7.4 SR on top.
- Efficiency: inference 0.25 s vs 1.22 s for NaVid (-79.5%); memory a constant 0.17 MB vs
  276 MB at 300 steps.

### 2.2 TopV-Nav: top-view spatial reasoning of an MLLM for zero-shot object navigation
- URL: https://arxiv.org/abs/2411.16425 (PDF read at https://arxiv.org/pdf/2411.16425)
- Map: 1000 x 1000 px at 20 px per metre (a 50 m square); obstacles, frontiers, detected objects
  drawn on it; text boxes with category names, DBSCAN "key area" markers (eps 1.3 m, min pts 2),
  a coordinate grid, and dynamic zoom (DMS). MLLM = Qwen2.5-VL-7B by default.
- Main (Table 1): MP3D SR 35.2 / SPL 16.4; HM3D SR 52.0 / SPL 28.6 (VoroNav 42.0 / 26.0).
- Table 2 (HM3D subset): LLM reasoning in language only 45.0 SR / 25.44 SPL; + top-view map
  image (AVPG) 49.0 / 28.07; + DMS 50.0 / 27.16; + PTD 52.0 / 28.73.
- Table 3 (which visual prompt matters): full 52.0 / 28.73; w/o history 51.0; w/o obstacle layer
  49.0 / 26.88; w/o text boxes 45.0 / 26.16; w/o coordinate grid 46.0 / 26.08.
- Table 5 (MLLM): LLaVA-NeXT (Llama-3-8B) 50.0; Qwen2.5-VL-7B 52.0; GPT-4o 53.0.
- Same message as MapNav: the obstacle layer alone is worth +3 SR; text labels and coordinate
  references are worth +6-7 SR - a VLM reads a map as a labelled diagram, not as geometry.

### 2.3 Mem2Ego: global-to-ego memory for long-horizon embodied navigation
- URL: https://arxiv.org/abs/2502.14254 (full text read at https://arxiv.org/html/2502.14254);
  Huawei Noah's Ark; Feb 2025 (v2 June 2025). License CC BY-NC-SA 4.0; no code release stated.
- Memory = frontier map (voxel free/unexplored boundary), landmark semantic memory (VLM text
  descriptions + global coordinates), visitation memory. Instead of map tokens, global
  coordinates are "projected onto the egocentric image plane as pixel locations" and drawn as
  labelled green circles (candidates) and blue circles (visited) on the panoramic image.
- Results: HSSD (213 episodes) GPT-4o SR 0.8685 / SPL 0.5788; fine-tuned Llama-3.2-11B-Vision
  (30,352 VQA pairs from 104 scenes, 5,678 object-nav tasks; 3 epochs) 0.8732 / 0.5995;
  HSSD-Hard 0.7647 / 0.4790 and 0.7843 / 0.5274. Ablations: w/o visitation memory SR 0.8450;
  w/o landmark memory 0.8356.
- Why it matters: an 11B open VLM fine-tuned on ~36K samples beats GPT-4o once the map is
  rendered into the ego view; the extra "memory" costs zero tokens beyond the image.

### 2.4 FloorPlan-VLN / FP-Nav (2026)
- URL: https://arxiv.org/abs/2603.17437 (full text read at https://arxiv.org/html/2603.17437)
- Floor plans are "rasterized into images" with region types colour-coded and numbered; the
  ego frame and the floor plan (with trajectory and current pose drawn) are horizontally
  concatenated into a single "dual-view" frame for Qwen-2.5-VL-7B; video truncated to at most
  6 frames. Benchmark: >10k episodes, 72 scenes, >100 annotated floor plans.
- FloorPlan-R2R val unseen SR 28.8 / SPL 24.0 / NE 9.4; FloorPlan-RxR 25.2 / 20.1. Auxiliary
  reasoning tasks: SR 17.8 -> 20.9. Real-world: FP-Nav SR 24.0 vs NaVid-ft 8.0 (NE 6.4 vs 9.3 m).
  Abstract: ">60% relative improvement in navigation success rate" over adapted baselines.

## 3. Structured object / frontier / path tokens, and LiDAR-to-LLM tokens

### 3.1 FOM-Nav: Frontier-Object Maps for Object Goal Navigation
- URL: https://arxiv.org/abs/2512.01009 (full text read at https://arxiv.org/html/2512.01009v1)
- Chabal, Chen, Ponce, Schmid (Inria/ENS/NYU), Nov 2025. Code: https://github.com/thomaschabal/fom-nav
- This is the clearest example of tokenizing STRUCTURED STATE for a frozen LLM (LLaVA-1.6-7B,
  D = 4096): every frontier is one token = MLP(endpoints) + MLP(centre) + DINOv2 patch features
  from a local mask + MLP(geodesic distance) + learnable type vector; every object is one token =
  MLP(centre) + MLP(box corners) + MLP(geodesic distance) + averaged DINOv2 features +
  CLIP-text(category) + type vector; every past position is one path token.
- Budget: "5 frontiers, 100 objects, 50 path tokens and the text ones ... resulting in around
  200 tokens, which is 2 times smaller than, e.g., Uni-Navid".
- Results: HM3D v2 SR 75.8 / SPL 47.9 (VLFM 64.0 / 33.0); HM3D v1 73.0 / 52.1; MP3D 44.6 / 23.9.
  Ablation: no visual features in tokens SR 63.7 / SPL 38.2 -> full 75.8 / 47.9; local frontier
  masks +5.3 SR over global features. Data: 760k steps (270k automatic + 490k GT).
- Real robot: TIAGo++, RTX 4060 desktop, map update 130 ms, LLaVA forward 100 ms, 20 GB GPU.

### 3.2 LiDAR-LLM: LiDAR BEV features as soft prompts for an LLM
- URL: https://arxiv.org/abs/2312.14074 (PDF read at https://arxiv.org/pdf/2312.14074)
- Point-cloud range [-54, 54] m, BEV grid 0.6 m; a View-Aware Transformer with K = 576
  learnable queries (dim 768) cross-attends the BEV feature (six view position embeddings) and
  the 576 output queries are soft-prompted into a frozen LLaMA-7B with adapters.
- Ablation (nu-Caption): BEV feature -> MLP directly into the LLM gives BERT 88.14 / BLEU-4
  11.37; + query transformer 90.60 / 15.41; + view position embedding 91.32 / 19.26. Headline
  40.9 BLEU-1 captioning; grounding 63.1% top-1 (5 classes), 14.3% BEV mIoU.
- Why it matters: a Q-Former bottleneck over a BEV grid is the standard way to get a LiDAR map
  into a language model at a fixed token count; raw BEV-to-MLP is measurably worse.

## 4. LiDAR in learned policies on quadrupeds

### 4.1 REASAN: Learning Reactive Safe Navigation for Legged Robots (Dec 2025)
- URL: https://arxiv.org/abs/2512.09537 (full text read at https://arxiv.org/html/2512.09537)
- Yuan, Cao, Cao, Li. Platform: Unitree Go2 + Livox Mid-360 + Jetson AGX Orin 64 GB - Parcel's
  exact stack.
- LiDAR representation: spherical-grid downsampling at 2 degrees -> a 30 x 180 circular depth
  image; a ray-based exteroceptive representation of 180 equidistant rays over 360 degrees;
  15 frames of history. "LiDAR and proprioceptive features of all frames are concatenated
  along the channel dimension at each spatial location to form tokens" into a transformer
  encoder with learnable temporal encodings.
- Policy stack: locomotion, safety-shield and navigation PPO policies (RSL-RL, IsaacLab);
  navigation policy takes the goal position in the base frame; LSTM(256) + MLP(512-256-128)
  + 1D-CNN(64). Training: 4 h / 15 h / 7 h / 10 h (estimator, 12 GB VRAM).
- Numbers: sim success ScaSparse 91.1 +- 1.9%, ScaDense 79.1 +- 4.4%, Maze 95.2 +- 2.9%,
  DyMaze 68.2 +- 2.3%, Hold 65.8 +- 3.4%. Real: static 270 s, dynamic 180 s, dead-end 190 s,
  multi-robot 93 s, all zero collisions. All modules at 50 Hz; estimator ~1.3 ms per cycle.
- Why it matters: proves a transformer over 180-ray LiDAR tokens runs at 50 Hz on the Orin
  beside locomotion; the 10 Hz act-token loop can afford this as a front-end.

### 4.2 ViLiNT: Multimodal embodiment-aware navigation transformer (Apr 2026)
- URL: https://arxiv.org/abs/2604.19267 (full text read at https://arxiv.org/html/2604.19267)
- Dezons, Picard, Marsal, Goulette, Filliat. License CC BY 4.0.
- Tokens: RGB history C+1 frames -> (C+1) tokens via DUNE ViT; LiDAR point cloud ->
  PointTransformerV3 -> polar grid K_theta x K_r sectors -> K tokens by GeM pooling; goal (2D)
  -> 1 token by MLP; embodiment (width, length) -> 1 token by MLP. Sequence S = (C+1) + K + 2
  with learned type and temporal embeddings; modality dropout during training.
- Table II (100 trials per env, Isaac-Sim Husky):
  | model | Env1 SR | Env2 SR | Env3 SR |
  | NoMaD-FT (RGB only) | 0.33 | 0.37 | 0.12 |
  | ViLiNT LiDAR masked | 0.17 | 0.37 | 0.20 |
  | ViLiNT image masked | 0.72 | 0.67 | 0.23 |
  | ViLiNT full | 0.79 | 0.61 | 0.76 |
  Real Husky (Ouster OS1-32): ViLiNT 85% vs NoMaD-FT 15%. "166% increase in SR and 62%
  reduction in CR compared to NoMaD-FT". Doubling the embodiment token's size makes the robot
  refuse corridors narrower than 1.5 x max(w, l).
- Why it matters: this is the direct measurement that LiDAR tokens, not RGB tokens, carry the
  obstacle-avoidance signal in a navigation transformer (masking LiDAR costs ~50% SR, masking
  images ~10-30%), and that a single MLP token can encode a scalar body-size prior.

### 4.3 HiCo-Nav: deployable VLN system on a Unitree quadruped (Apr 2026)
- URL: https://arxiv.org/abs/2604.21363 (full text read at https://arxiv.org/html/2604.21363v1)
- Unitree quadruped + Mid-360 + RealSense D455 + Jetson Orin NX; Qwen3-Omni API online or local
  Qwen3-VL-8B offline; YOLO-World, Mobile-SAM, CLIP.
- LiDAR is used for SLAM/pose and for frontier scoring, but "the resulting map representation is
  not passed directly to the VLM as an image or tokens"; the VLM reasons over keyframe
  "visual anchors" and detected objects in a cognitive memory graph.
- Sim SR/SPL: MP3D 48.5 / 21.5; HM3D 61.0 / 31.8; HM3D-OVON 52.4 / 20.7. Real: 95% large objects,
  65% small (40 episodes). Per-frame 0.22 s, 1.54 m/s, 21.5 s mean task time.
- Why it matters: the one 2026 Mid-360 quadruped VLN system keeps LiDAR OUT of the model and
  uses it only in the classical stack - a data point for the modular alternative.

## 5. Goal, embodiment, proprioception and identifier tokens

### 5.1 NavDP: sim-to-real navigation diffusion policy (May 2025)
- URL: https://arxiv.org/abs/2505.08712 (full text read at https://arxiv.org/html/2505.08712v2)
- Shanghai AI Lab. RGB and depth each give 256 patch tokens; a transformer decoder compresses
  the 512 to 16 fused tokens; goals are separate tokens: point goal (2D relative coordinates),
  image goal, trajectory goal, or no-goal, i.e. 3 goal tokens + 1 trajectory token, about 20
  tokens total into a two-layer transformer; a critic shares the policy weights.
- Data: 363.2 km, 1,244 scenes, 56,000 trajectories, 10 M RGB-D frames, 2,500 trajectories per
  GPU-day. Inference > 10 Hz on an RTX 5080 laptop.
- Point-goal sim: Go2 83.0% SR / 61.8 SPL; Dingo 81.3%; Galaxea R1 52.6%. Real Unitree Go2:
  80% over 20 episodes. Adding 27% in-domain real-to-sim data improved target-scene success by 30%.

### 5.2 NoMaD: goal-masked diffusion policies (2023, CC BY 4.0)
- URL: https://arxiv.org/abs/2310.07896 (full text read at https://arxiv.org/html/2310.07896)
- EfficientNet-B0 encodes each context frame to a 256-d token; a goal-fusion encoder makes one
  goal token; a binary goal mask (Bernoulli p = 0.5 in training) applied via attention masking
  switches between goal-reaching and exploration; 4-layer, 4-head transformer; 19 M params;
  runs on-the-edge on a Jetson Orin. Real: 98% exploration success, 0.2 collisions, 90%
  navigation success.
- Why it matters: the canonical "goal as one token + mask" pattern; the mask is the same
  mechanism Parcel needs for "no active goal / owner said stop".

### 5.3 GR00T N1: proprioception via per-embodiment MLP into a DiT (2025)
- URL: https://arxiv.org/abs/2503.14734 (full text read at https://arxiv.org/html/2503.14734v1)
- State and action of varying dimension are embedded by "an MLP per embodiment to project them
  to a shared embedding dimension" as input to the diffusion transformer; vision-language
  tokens (Eagle-2 VLM, 224 x 224, 64 image tokens per frame after pixel shuffle) enter via
  cross-attention. Action chunk H = 16, K = 4 denoising steps; VLM at 10 Hz on an L40; DiT at
  120 Hz; 63.9 ms to sample 16 actions on an L40.
- Why it matters: the accepted recipe for structured low-dimensional state is a single MLP
  token per state vector, not per-dimension tokens; and the 10 Hz VLM / high-rate action head
  split is the same dual-rate shape as Parcel's Model A.

### 5.4 NavFoM: Embodied Navigation Foundation Model (Sept 2025, CC BY 4.0)
- URL: https://arxiv.org/abs/2509.12129 (full text read at https://arxiv.org/html/2509.12129)
- Qwen2-7B with DINOv2 + SigLIP; 12.7 M training samples (8.02 M navigation: VLN 3.37 M,
  object-nav 1.02 M, tracking 897 K, driving 681 K, web video 2.03 M; 4.76 M QA).
- Token budget: fixed 1600 tokens (navigation) or 2048; the latest observation gets 64 tokens
  per frame, history frames 4 tokens per frame; "Budget-Aware Temporal Sampling" with an
  exponential-decay keep probability P(t) = (1 - eps) e^{k(t-T)/T} + eps, eps = 0.1.
- Identifier tokens (TVI): base embedding + sinusoidal angle embedding of the camera azimuth
  (must "preserve the circular continuity of azimuthal angles") + time embedding - i.e.
  structured camera-pose and time state is injected as dedicated tokens, not text.
- Results: VLN-CE R2R SR 61.7 / SPL 55.3 (4 cameras); RxR 64.4 / 56.2 (single camera 57.4 /
  49.4); HM3D-OVON SR 45.2 zero-shot; EVT-Bench tracking SR 88.4. "at most 0.5 seconds to
  generate an eight-waypoint trajectory under a 1600-token budget" on a remote RTX 4090 - not
  on the robot. Real tests: 110 cases across quadrupeds (Go2), humanoids (G1), drones, cars.

## 6. Audio-visual navigation: encoders, tokens, sim2real

### 6.1 SoundSpaces 2.0: A Simulation Platform for Visual-Acoustic Learning
- URL: https://arxiv.org/abs/2206.08312 (PDF read at https://arxiv.org/pdf/2206.08312);
  NeurIPS 2022 Datasets & Benchmarks. Code: https://github.com/facebookresearch/sound-spaces
- On-the-fly bidirectional path-tracing RIRs for arbitrary meshes and mic positions; models
  direct sound, early specular/diffuse reflections, reverberation, diffraction, materials;
  outputs mono, binaural (HRTF) or ambisonics.
- Speed (Table 2, Xeon Gold 6230): high-quality 0.9 FPS (1 thread) / 4.0 FPS (5 threads);
  high-speed 7.7 / 33.5 FPS at 9.5% relative RT60 error. Direct-to-reverberant error vs real
  measurements 0.98 dB (SoundSpaces 1.0: 11.0 dB).
- Table 3 (continuous AudioGoal): agent trained on SoundSpaces 1.0 tested in continuous space
  64.2% SR / 27.5% SPL; with continuous sound too 0.9% SR; agent trained on SoundSpaces 2.0
  64.7% SR / 49.3% SPL / DTG 5.9 m.
- Table 4 (far-field ASR WER on real RIR test data): pretrained 29.10; fine-tuned on real IRs
  13.32; Pyroomacoustics 16.24; SoundSpaces 1.0 18.48; SoundSpaces 2.0 12.48.
- Why it matters: it is the only simulator that can generate Parcel's speech-through-rooms
  training audio, and its RIRs transfer to real ASR better than real IR sets did.

### 6.2 AVLEN: Audio-Visual-Language Embodied Navigation (NeurIPS 2022)
- URL: https://arxiv.org/abs/2210.07940 (full text read at https://ar5iv.labs.arxiv.org/html/2210.07940)
- Audio: "65 x 26 spectrograms" of binaural input into a CNN goal-estimation network that emits
  location + category of the sounding target. Language help (GloVe or CLIP embeddings) fused
  by a two-transformer policy (T1 over observation + goal, FC fusion with language, T2 over
  belief history). Hierarchical RL chooses audio-following vs asking; K = 3 queries per
  episode, 3 steps per instruction.
- SoundSpaces/MP3D results: heard sounds SAVi SR 33.9 / SPL 24.0 / SNA 18.3 -> AVLEN 36.1 /
  24.6 / 19.7 (oracle GT-action ceiling 48.2 / 34.3); unheard 24.8 -> 26.2 (ceiling 36.7);
  with distractor sounds 11.8 -> 14.0. CLIP vs GloVe: "comparable".
- Why it matters: language help on top of audio-goal following buys ~+2 SR with a learned
  ask-policy; the ceiling with perfect instruction following is +14, so grounding the words is
  the bottleneck, not the audio.

### 6.3 Sim2Real Transfer for Audio-Visual Navigation with Frequency-Adaptive Acoustic Field Prediction
- URL: https://arxiv.org/abs/2405.02821 (PDF read at https://arxiv.org/pdf/2405.02821); IROS 2024;
  project page https://vision.cs.utexas.edu/projects/sim2real/ (read; no extra numbers).
- Chen et al. (UT Austin). Disentangles AV-nav into an acoustic-field predictor (AFP) and a
  waypoint planner. AFP input: a 128 x 128 egocentric depth image (ResNet -> 512-d) plus ONE
  SECOND of binaural audio (STFT -> 2D conv), output an L x L (L = 9) top-down sound-pressure
  field; the peak is the long-term goal. Frequency-adaptive: divide the spectrum into N bands,
  weight each by measured sim2real error and by received energy, predict from the best band.
- Table I (continuous AudioGoal, sim): Random 0.01 SR; DDPPO 0.82 / 0.63 SPL; Direction
  Follower 0.67 / 0.50; Gan et al. 0.63 / 0.53; AFP w/ predicting max 0.54; AFP w/o vision
  0.84 / 0.71; AFP (ours) 0.91 / 0.76. Using all frequencies: 0.86 m error vs best band.
- Real robot: Hello Robot Stretch + 3Dio binaural microphone (Focusrite interface); robot
  self-noise augmentation; "20 navigation examples ... 75% success rate"; the end-to-end
  DDPPO policy "failed all the test scenarios".
- Why it matters: the only measured real-robot audio navigation transfer; it says predict a
  local sound field (a 9 x 9 grid = 81 cells) from 1 s of audio and hand it to a planner,
  rather than feeding raw audio to an end-to-end policy.

### 6.4 ASGF-Nav: Audio Spatially-Guided Fusion for Audio-Visual Navigation (Apr 2026)
- URL: https://arxiv.org/abs/2604.02389 (full text read at https://arxiv.org/html/2604.02389)
- Zhou, Yu (Xinjiang Univ.). License CC BY-NC-ND 4.0. Binaural STFT spectrograms -> CNN ->
  BiGRU, 512-d frame embeddings; an "audio spatial state" is the query of a cross-attention over
  concatenated visual + audio features with sigmoid gating; GRU policy, actor-critic.
- Table I SPL/SR/SNA: Replica unheard 63.3 / 76.5 / 36.9 (SoundSpaces baseline 34.7 / 50.9;
  AV-WaN 34.7 / 52.8); MP3D unheard 52.2 / 66.4 / 29.9 (baseline 25.9 / 40.5; AV-WaN 40.9 /
  56.7). Heard MP3D 59.1 / 87.6 (AV-WaN 72.3 / 93.6). Ablation MP3D unheard: w/o the fusion
  31.6 / 40.0; w/o audio-state encoder 41.4 / 59.9; full 52.2 / 66.4.

### 6.5 Samba: A Hybrid Mamba for Audio-Visual Navigation (Jul 2026)
- URL: https://arxiv.org/abs/2607.13110 (full text read at https://arxiv.org/html/2607.13110)
- Wang, Yu. License CC BY-NC-ND 4.0. Binaural spectrogram S_t in R^{C x F x T} is tokenized by
  flattening channel x frequency per time step; bidirectional Mamba "Audio Mamba Encoder"
  (0.4 M params vs 0.7 M CNN) and a Mamba state encoder (2.7 M vs 3.9 M GRU) that runs
  recurrently at deployment.
- Results: MP3D unheard SR 68.0 / SPL 47.1 / SNA 36.2 (AV-WaN 56.7 / 40.9 / 30.6); heard 95.0 /
  73.3; Replica unheard SR 72.8 (AV-WaN 52.8), heard 93.4 (AV-WaN 98.7). Total 4.6 M params on
  MP3D vs 5.6 M.

### 6.6 MAGNet / SAVN-CE: Semantic Audio-Visual Navigation in Continuous Environments (Mar 2026)
- URL: https://arxiv.org/abs/2603.19660 (full text read at https://arxiv.org/html/2603.19660);
  code https://github.com/yichenzeng24/SAVN-CE
- SoundSpaces 2.0 on MP3D, 16 kHz audio, 0.25 s simulation steps; goals emit sound only briefly
  or intermittently. Audio front-end: 512-point FFT, hop 160, four channels (magnitude, cos and
  sin inter-channel phase difference, inter-channel level difference). A multimodal
  transformer fuses audio, RGB-D (ResNet-18), pose and action embeddings into a scene memory;
  a memory-augmented goal-descriptor network and a transformer encoder-decoder policy.
- Results (clean): MAGNet SR 37.7 / SPL 32.9 / SNA 27.4 / DTG 8.0 m vs SAVi 25.6 / 21.2, SMT +
  audio 24.8, AV-Nav 21.3; "up to a 12.1% absolute improvement in success rate".

### 6.7 LH-AVLN: Long-Horizon Audio-Visual-Language Navigation benchmark (Jul 2026, CC BY 4.0)
- URL: https://arxiv.org/abs/2607.03920 (full text read at https://arxiv.org/html/2607.03920)
- HKUST(GZ)/Jilin. 156,550 episodes (550 validation) in MP3D with SoundSpaces 2.0 binaural
  audio, 2-4 heterogeneous goals per mission given by category, language or reference image;
  multiple alternating sound sources.
- Baselines: MAV-Nav = SAVN-CE scene-memory transformer + frozen CLIP ViT-B/32 goal encoder +
  CNN binaural encoder; PAG-Nav training-free with a "temporal uniform semantic map" of rooms,
  objects and acoustic events.
- Ordered / unordered SR: MTU3D 1.7 / 2.1; 3D-Mem 0.0 / 1.0; SAVi 0.0 / 0.0; GOAT-Bench 0.0 /
  0.2; PAG-Nav 2.3 / 3.1; MAV-Nav 2.2 / 6.0. No LLM/VLM agent evaluated.
- Why it matters: every current method, learned or not, is below 6% on long-horizon
  multi-goal audio-visual-language missions; this task family is unsolved.

### 6.8 AVLMaps: Audio Visual Language Maps for Robot Navigation (ISER 2023)
- URL: https://arxiv.org/abs/2303.07522 (PDF read at https://arxiv.org/pdf/2303.07522)
- Huang, Mees, Zeng, Burgard. Sounds heard while mapping are segmented and embedded with
  AudioCLIP (wav2clip also possible) into a shared 3D voxel map with LSeg visual features and
  visual-localization features; language/sound/image queries produce heatmaps that are
  multiplied to disambiguate ("the table where you heard coughing").
- Table I sound-goal navigation SR (%) for 1 / 2 / 3 / 4 subgoals in a row: domestic sounds
  59.5 / 33.0 / 15.5 / 7.0; + human sounds 69.5 / 47.0 / 36.5 / 23.0; + animal sounds 74.5 /
  58.5 / 45.5 / 33.0. Multimodal goals (Table II) 71.5 / 40.5 / 25.0. Cross-modal indexing
  recall@1 within 1 m: 24.44% vs VLMaps 7.78% (abstract: "50% better recall in ambiguous
  scenarios"). 200 sound-goal sequences over 10 scenes.
- Why it matters: audio events as MAP ENTRIES (where a sound was heard) rather than as policy
  tokens; the retrieval-time success of 60-75% for one goal is a floor for Parcel's
  "go to where the kettle was".

### 6.9 BAT / Spatial-AST: reasoning about spatial sounds with an LLM (ICML 2024, CC BY 4.0)
- URL: https://arxiv.org/abs/2402.01591 (PDF read at https://arxiv.org/pdf/2402.01591)
- Zheng, Peng, Ma, Chen, Choi, Harwath. Encoder input: binaural at 32 kHz, 10 s clips, window
  1024, hop 320, 128 mel bins, plus cos/sin of the interaural phase difference -> a (4, 1024,
  128) tensor; a 16 x 16 Patch-Embed CNN gives non-overlapping patch tokens (64 x 8 = 512,
  computed from the stated dims; 25% masked in training) plus three [CLS] tokens (class,
  distance, direction) into a 12-layer transformer initialised from AudioMAE; output tokens
  are linearly projected into LLaMA-2 7B (LLaMA-Adapter v2).
- Spatial-AST: mAP 50.03% event classification, 17.94 degrees mean angular error, distance error
  rate within 0.5 m 32.54% (Table 3: mel + IPD binaural stage-2 mAP 50.03 / ER20 23.89 / MAE
  17.9; SELDnet 42.66 / 25.19 / 19.21). BAT QA accuracy 76.89% on SpatialSoundQA (binaural
  AudioSet clips rendered with SoundSpaces 2.0 in Matterport3D).
- Why it matters: a ready-made binaural encoder whose [CLS] direction/distance tokens are the
  natural "audio event token" for a policy: one clip -> three small tokens with 18-degree DoA.

## 7. Speech-conditioned policies

### 7.1 VLAS: Vision-Language-Action Model With Speech Instructions (ICLR 2025)
- URL: https://arxiv.org/abs/2502.13508 (full text read at https://arxiv.org/html/2502.13508);
  code https://github.com/whichwhichgone/VLAS
- LLaVA (CLIP + Vicuna) plus a Whisper encoder: 80-bin mel padded to 3000 frames -> 1500
  hidden states -> reduction factor 5 -> MLP projector, i.e. about 300 speech tokens per
  utterance in the LLM's embedding space.
- Three stages: speech-text alignment on LibriSpeech-360 (MLP only); speech-QA on SQA (185 K
  samples, >1,152 voices) + VQA; behaviour cloning on CSI (CALVIN with 389 instructions x 500
  voices, ~194 K clips).
- CALVIN long-horizon chains LH-1..LH-5: text VLA 95.5 / 85.0 / 74.9 / 66.8 / 58.2; VLAS text
  94.5 / 84.4 / 73.6 / 64.6 / 56.6; VLAS synthesized speech 94.2 / 84.0 / 73.2 / 64.3 / 54.6;
  VLAS real speech (10 speakers) 93.6 / 82.8 / 71.6 / 61.4 / 51.3; VLA + ASR cascade 88.7 /
  74.1 / 61.0 / 49.2 / 40.2.
- Customisation (ownership / preference / compound, needs speaker identity via "Voice RAG"):
  VLAS 86.5% (real speech 78.6%); text VLA 19.2%; VLAS without RAG 16.0%.
- Why it matters: direct speech tokens beat an ASR cascade by 5-18 points on chained tasks,
  and the speaker's voice is the only channel that carries "whose command" - the user-context
  signal Parcel's Model B needs.

### 7.2 Audio-VLA: contact audio in a VLA (Nov 2025)
- URL: https://arxiv.org/abs/2511.09958 (full text read at https://arxiv.org/html/2511.09958)
- Llama-2 7B with DINOv2 + SigLIP; audio per timestep -> FBSP layer (window 1024, hop 256,
  1025 bins) -> log power -> ResNeXt (AudioCLIP, further trained on ManiWAV) -> N_a audio
  tokens -> 3-layer MLP into the LLM space, concatenated with visual and proprio tokens; LoRA
  rank 32, 50-100 K steps, 2 x H20.
- LIBERO avg: Audio-VLA 97.6% vs OpenVLA-OFT 97.1% vs pi0-FAST 85.6%; domain shift 74.7 / 71.0 /
  64.2. RLBench (5 tasks) 55.1 / 48.1 / 43.9; contact-intensive task 3: 18.9 / 8.7 / 5.2. Real
  (20 trials per condition): whiteboard erasing seen 60% vs 20% / 20%; oatmeal scooping seen
  30% vs 10% / 10%.
- Why it matters: a general-purpose audio encoder (AudioCLIP) can be added as tokens to a
  7B VLA with LoRA and it pays off where audio carries information vision lacks.

### 7.3 Constrained navigation on preferred terrains using LLMs and speech instruction (2024)
- URL: https://arxiv.org/abs/2404.02294 (full text read at https://arxiv.org/html/2404.02294v1)
- McGill MRL. Whisper ASR -> GPT-3.5 extracts landmarks, terrain preferences and adverbs ->
  adverbs become speed constraints in an MPC (e.g. 3 m/s to 1.5 m/s at a landmark); LSeg
  terrain segmentation; RC car in Unreal Engine; no success-rate table, ablations show
  navigation fails when adverbs or terrain preferences are dropped. CC BY-NC-SA 4.0.
- Why it matters: the "speech -> text -> structured constraint -> controller" pattern is the
  cascade baseline that VLAS beats; but it shows adverbs ("slowly", "carefully") are the
  content worth extracting for a steering injection.

## 8. Cross-source table: tokens, encoders, measured effects

| Source | Non-RGB input | Encoder -> tokens | Measured effect |
|---|---|---|---|
| BEVBert (ICCV23) | local metric map | 21x21 cells x 0.5 m -> 441 cell tokens, 15.2 GFLOPs | 11x11 -> 21x21: +1.6 SR for 3.4x FLOPs; 31x31 flat |
| GridMM (ICCV23) | growing top-down grid | 14x14 = 196 tokens, CLIP grid feats, ego coords | no map 45.2 -> semantic map 46.4 -> grid 49.1 SR (R2R-CE) |
| BSG (ICCV23) | BEV from cameras | 11x11 queries, +-5 m, Z=4 | +5.1 SR REVERIE only with detection loss; BEV alone worse than panoramas |
| VER (CVPR24) | voxel grid + occupancy heads | X x Y x Z cells, occ at 0.4/0.2 m | +3 SR / +4 SPL R2R test; occupancy-only head +2 SR |
| MapNav (ACL25) | annotated semantic map image | one SigLIP image | no map 27.3 -> obstacle map 26.4 -> semantic 29.1 -> annotated 36.5 SR; 0.17 MB constant |
| TopV-Nav | top-view map image | 1000x1000 px @ 20 px/m for Qwen2.5-VL-7B | text-only 45.0 -> +map 49.0 -> full 52.0 SR; w/o text boxes 45.0 |
| Mem2Ego | frontier/landmark/visited memory | drawn as labelled circles on the ego image | SR 0.87 HSSD; w/o landmark memory 0.84 |
| FloorPlan-VLN (2026) | rasterised floor plan | concatenated to ego frame, <= 6 frames | real 24% vs 8% SR |
| FOM-Nav | frontiers, objects, path | ~200 tokens: 5 + 100 + 50 + text; per-token MLP(coords, distance) + DINOv2 + CLIP-text | HM3D v2 75.8 SR; tokens w/o visual feats 63.7 |
| LiDAR-LLM | LiDAR BEV (0.6 m, +-54 m) | Q-Former 576 x 768 -> LLaMA-7B | BEV->MLP BLEU-4 11.4 -> Q-Former 15.4 -> +view-pos 19.3 |
| REASAN (Go2/Mid-360/Orin) | 360-deg LiDAR rays | 30x180 depth image; 180 rays x 15 frames -> transformer | 50 Hz, ~1.3 ms; sim SR 68-95%; real zero collisions |
| ViLiNT (2026) | LiDAR + goal + body size | PTv3 -> polar K tokens; goal 1 MLP token; embodiment 1 MLP token | mask LiDAR: 0.79 -> 0.17 SR; real 85% vs 15% |
| NavDP | depth + goal | 256 depth + 256 RGB -> 16 fused; 3 goal tokens + 1 traj | Go2 real 80% (20 eps); >10 Hz laptop |
| NoMaD | goal image + mask | 1 goal token, Bernoulli mask | 98% exploration; 19 M params on Jetson Orin |
| GR00T N1 | proprio state | 1 MLP token per embodiment; 64 img tokens/frame | 63.9 ms / 16 actions (L40) |
| NavFoM | camera azimuth + time | identifier tokens (sinusoidal angle + time) | 1600-token budget: 64 tok latest frame, 4 tok/history frame; 0.5 s on 4090 |
| SoundSpaces 2.0 | binaural/ambisonic RIRs | simulator | 33.5 FPS high-speed; SS2-trained SPL 49.3 vs 27.5 |
| AVLEN | 65x26 binaural spectrogram | CNN goal estimator + 2 transformers | +2.2 SR over SAVi with language help; ceiling +14 |
| Sim2Real-AVN (IROS24) | 1 s binaural + 128x128 depth | conv -> 9x9 acoustic field -> planner | sim SR 0.91; real 75% (20 trials); e2e RL 0% |
| ASGF-Nav (2026) | binaural spectrogram | CNN + BiGRU 512-d; cross-attn gated | MP3D unheard SR 40.5 -> 66.4 |
| Samba (2026) | binaural spectrogram | per-timestep tokens, Mamba 0.4 M | MP3D unheard SR 68.0; 4.6 M params total |
| MAGNet (2026) | 4-ch (mag, IPD cos/sin, ILD) | transformer scene memory | SR 25.6 -> 37.7 with intermittent sounds |
| LH-AVLN (2026) | multi-goal audio + language | benchmark | all methods <= 6% SR |
| AVLMaps | AudioCLIP sound events in a voxel map | retrieval heatmaps | 1-goal SR 59.5-74.5%; 4-goal 7-33% |
| BAT / Spatial-AST | binaural 10 s, mel + IPD | 512 patch tokens + 3 CLS -> linear -> LLaMA-2 | MAE 17.9 deg DoA, 50.0 mAP, 76.9% QA |
| VLAS (ICLR25) | speech | Whisper -> ~300 tokens/utterance | speech 94.2 vs ASR cascade 88.7 (LH-1); customisation 86.5 vs 19.2 |
| Audio-VLA | contact audio | AudioCLIP -> N_a tokens -> 3-layer MLP; LoRA r=32 | LIBERO 97.6 vs 97.1; RLBench 55.1 vs 48.1 |

## 9. What this means for Parcel's Model A / Model B

Model A = 10 Hz act-token loop + 0.5-2 Hz language/plan lane on the Orin 64 GB; Model B =
owner voice -> steering injection, receipts -> narration for the hosted Realtime voice.

1. LiDAR belongs in the 10 Hz loop as tokens; the map belongs in the slow lane as an image.
   The only measured navigation transformer with LiDAR tokens (ViLiNT) loses ~50% of its
   success when LiDAR is masked and only 10-30% when images are masked; REASAN shows a
   180-ray x 15-frame LiDAR transformer runs at 50 Hz in ~1.3 ms on Parcel's own Go2 /
   Mid-360 / Orin stack. So the Mid-360 should feed the fast policy directly as a polar-grid
   (ViLiNT: PTv3 + K_theta x K_r GeM pooling) or ray-image (REASAN: 30 x 180) token set of a
   few dozen to a few hundred tokens, not as text and not via the VLM.

2. For the slow lane, render the occupancy grid as an ANNOTATED image and let the VLM read it.
   Every VLM study agrees a raw obstacle map is worth ~0 (MapNav: 27.3 -> 26.4 SR; TopV-Nav:
   +3 SR) while labels and a coordinate grid are worth +7-10 SR (MapNav 36.5; TopV-Nav
   52.0 with text boxes vs 45.0 without). Mem2Ego shows projecting map memory INTO the ego
   image as labelled markers lets an 11B open VLM beat GPT-4o. Cost: one image's tokens
   (MapNav 0.17 MB constant; NavFoM's 64 tokens per current frame). Parcel's 0.5-2 Hz lane
   can afford one annotated map image plus the current frame.

3. Budget the map-token grid at BEVBert / GridMM scale if it ever goes into the trained policy
   rather than the VLM: 11x11 to 21x21 cells at 0.5 m (121-441 tokens) is where the gains
   live; 31x31 is flat for 2x the FLOPs (BEVBert Table 7), and 14x14 -> 20x20 is +0.8 SR
   (GridMM Table 7). Use egocentric relative coordinates (GridMM +0.3 SR over absolute) and
   attach an occupancy-prediction auxiliary head (VER: +2 SR from occupancy alone).

4. Structured state goes in as ONE MLP token per vector, plus identifier tokens for pose/time.
   NavDP (3 goal tokens + 1 trajectory), NoMaD (1 goal token + Bernoulli mask), ViLiNT
   (1 goal + 1 embodiment token), GR00T N1 (1 per-embodiment state MLP token) and NavFoM
   (sinusoidal azimuth + time identifier tokens) all converge on this. For Parcel: goal
   bearing/distance -> 1 token; plan state (current sub-goal id, step index, "paused by
   owner") -> 1 token; a goal mask (NoMaD) to express "no goal / stopped". FOM-Nav's per-entity
   token recipe (MLP(coords) + MLP(geodesic distance) + visual feature + CLIP-text(category) +
   type vector) is the pattern for object/frontier tokens if the plan lane wants to hand the
   fast loop a small set of candidate targets: about 200 tokens total.

5. Audio events: predict a local sound field or a DoA/distance token; do not feed raw audio
   to the act-token policy. The only real-robot result (Sim2Real-AVN, 75% over 20 trials)
   used 1 s of binaural audio -> 9 x 9 acoustic-field grid -> classical planner, and the
   end-to-end RL policy scored 0% on the real robot. BAT's Spatial-AST offers three [CLS]
   tokens (class, distance, direction; 17.9-degree MAE) from a 10 s clip - a natural "audio
   event token" to append to the 10 Hz stream at ~1 Hz. Note Parcel's XVF3800 is a 4-mic
   array, not a binaural head; all encoders above are binaural/HRTF, so DoA must come from the
   array's own beamformer and be tokenised as bearing, or the audio branch must be retrained on
   array-rendered SoundSpaces 2.0 audio (it supports arbitrary mic configs, 33.5 FPS).

6. Speech should reach Model B as speech tokens, with ASR as a fallback, because identity is in
   the voice. VLAS: ~300 Whisper tokens per utterance beat an ASR cascade by 5-18 points on
   chained tasks, and speaker-conditioned retrieval lifts owner-specific tasks from 19% to
   86%. For Parcel that argues for: owner-voice embedding (speaker ID) as a persistent user
   token in Model B; extracted adverbs/constraints ("slowly", "not the kitchen") as the
   steering injection (the McGill pattern), emitted as a structured constraint the 10 Hz loop
   consumes as one state token; and narration receipts built from the same structured plan
   token so Model B's narration and Model A's plan cannot drift.

7. Long-horizon multi-goal audio-visual-language missions are unsolved (LH-AVLN: every method
   <= 6% SR; AVLMaps 4-goal 7-33%). Parcel's companion behaviours should be scoped as
   single-goal audio events ("go to the sound") with the plan lane sequencing them, not as
   end-to-end multi-goal policies.

8. Simulation: SoundSpaces 2.0 is the only place to train the audio branch and its RIRs
   transfer to real far-field ASR (WER 12.48 vs 13.32 fine-tuned on real IRs). For LiDAR the
   IsaacLab pipeline used by REASAN and NavDP (Go2 asset, 2,500 trajectories per GPU-day)
   provides the desktop-simulation path Parcel already relies on.

## 10. Open questions and gaps
- No paper was found that puts a LiDAR occupancy grid as tokens into a language-conditioned
  navigation VLA on a quadruped; the 2026 Mid-360 quadruped VLN system (HiCo-Nav) keeps LiDAR
  out of the model entirely. ViLiNT (wheeled Husky, point-goal) is the closest evidence.
- No paper was found that tokenises a "user context" (owner identity, preferences) for a
  navigation policy; VLAS's Voice RAG is the nearest analogue (manipulation, speaker ID).
- No published navigation policy consumes a microphone ARRAY; all audio-nav work is binaural.
- BAT's audio-token count (512) is computed from the stated feature dims and patch size; the
  paper does not print the number.
- BEVBert's R2R-CE val-unseen SR/SPL table was in a column the PDF extraction truncated; the
  cited R2R-CE claims are the abstract's "59 SR" (test unseen) and the text's "+4 SR, +2 SPL
  over ETPNav".
