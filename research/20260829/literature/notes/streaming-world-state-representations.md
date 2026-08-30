# Streaming world-state representations for a trainable duplex robot model

Literature note, 2026-08-29. Topic: how to represent "the state of the world over the last
minute + global history" as an input stream a trainable model (Parcel's Model A) can learn
from, and what to emit for a narrator (Model B -> hosted voice).

Method: every source below was located by web search and then read (arXiv HTML/PDF, project
page, or the DeepMind blog) before any number was recorded. Numbers are quoted from the
source text; where a fetch only exposed an abstract, that is stated. No number here is from
memory.

Sections:
1. Streaming navigation VLAs and their memory budgets (StreamVLN, Uni-NaVid, NaVILA)
2. Memory tokens and memory banks in manipulation VLAs (MemoryVLA, HAMLET, EventVLA,
   Explicit Language Memory) plus the canonical Recurrent Memory Transformer
3. Streaming video LLMs: sparse/event tokens and when-to-speak gating (VideoLLM-online,
   Flash-VStream, Event-VStream, LiveStar)
4. Scene-graph memory (ConceptGraphs, HOV-SG, SayPlan, Mem2Ego)
5. World-model tokens (DreamerV3, V-JEPA 2-AC, Genie 3)
6. Episodic / tiered LLM memory and plan traces (Generative Agents, Voyager, MemGPT,
   ReAct, Inner Monologue)
7. Structured belief state for dialogue (NL-DST)
8. Cross-source table: token budgets, update rates, history-length effects
9. What this means for Parcel's Model A / Model B
10. Open questions

---

## 1. Streaming navigation VLAs

### 1.1 StreamVLN: Streaming Vision-and-Language Navigation via SlowFast Context Modeling
- URL: https://arxiv.org/abs/2507.05240 (full text read at https://arxiv.org/html/2507.05240)
- Wei, Wan, Yu, Wang, ... Pang (InternRobotics / Shanghai AI Lab). arXiv July 2025; accepted ICRA 2026.
- What it is: a Video-LLM (LLaVA-Video base) that emits navigation actions as a
  streaming multi-turn dialogue. Two contexts: a **fast sliding window of the last N
  dialogue turns** (interleaved observation tokens + action tokens, KV cache reused) and a
  **slow memory context** of past visual tokens compressed by 3D voxel pruning.
- Memory mechanics: "back-projecting 2D patches into 3D space" and, when multiple frames
  project to the same voxel, "only the token from the most recent observation is retained";
  this gives "approximately 28% reduction in memory tokens on R2R".
- Numbers (Table IV, R2R-CE val-unseen):
  - Memory size with 8-turn window: 2x196 tokens SR 37.3 / SPL 34.2; 4x196 SR 38.9 / SPL
    35.4; **8x196 SR 45.5 / SPL 41.6**; **"all" context (no pruning) SR 40.0 / SPL 36.4**.
    Bounded, pruned memory beats keeping everything.
  - Window size with 8x196 memory: 2 turns SR 43.7; 4 turns SR 41.4; **8 turns SR 45.5**.
    Smaller windows also inflate training samples 450K -> 815K -> 1.5M.
  - Headline (with extra data): R2R-CE NE 4.90, OS 63.6, **SR 56.4, SPL 50.2**; RxR-CE
    SR 54.4, SPL 45.4, nDTW 63.7. RGB-only without extra data: R2R SR 52.8 / SPL 47.2.
  - Latency: "average inference (0.27s for 4 actions)" on an RTX 4090; Fig. 7: with full KV
    reuse ~0.03 s/step flat, without reuse rising to ~0.10 s by turn 24. KV reuse removes
    ~99% of prefill.
  - Data: 450K VLN samples from 60 MP3D envs + 300K ScaleVLN (700 HM3D scenes) + 240K DAgger
    + 248K video-QA + 230K MMC4 interleaved.
  - Real robot: **Unitree Go2** with an upward-facing RealSense D455, model on a remote
    RTX 4090 workstation.
- Why it matters for Parcel: this is the closest published shape to Model A's "last minute
  window + compressed history" and it runs on a Go2. The ablation is the cleanest evidence that
  a bounded ~1.5K-token memory (8x196) outperforms unbounded history.

### 1.2 Uni-NaVid: A Video-based Vision-Language-Action Model for Unifying Embodied Navigation Tasks
- URL: https://arxiv.org/abs/2412.06224 (full text read at https://arxiv.org/html/2412.06224v2)
- Zhang et al. (PKU-EPIC). arXiv Dec 2024 (v2 2025).
- What it is: EVA-CLIP encoder -> **online token merging** -> Vicuna-7B; outputs low-level
  actions for VLN, ObjectNav, EQA and human-following from egocentric RGB video.
- Three-tier token budget per frame: **current frame 64 tokens** (alpha_curr=2), **short-term
  4 tokens/frame** (alpha_short=8, buffer B=64 frames), **long-term 1 token/frame**
  (alpha_long=16). A frame moves from short- to long-term when it leaves the 64-frame buffer.
- History-length / memory ablation (Table X): VLN R2R SR **current-only 9.61% -> +short 39.7%
  -> +short+long 48.7%**; human following SR 56.3% -> 59.7% -> 61.2%. Paper: "the VLN task
  shows the most significant performance drop (-80.3% SR) when visual memory is removed" and
  "For the Following task, the absence of memory results in only a minor performance
  decline (-8% SR)".
- Headline: R2R-CE val-unseen SR 47.0 / SPL 42.7 / NE 5.58; RxR-CE SR 48.7 / SPL 40.9;
  HM3D ObjectNav SR 73.7 / SPL 37.1; MP3D-EQA 47.3%; following SR 61.21.
- Data: 3.6M navigation samples (VLN 2.4M, ObjectNav 483k, EQA 240k video-action + 10k QA,
  following 544k) + 2.3M internet video-QA. Training 40x H800 for ~35 h (1400 GPU-h).
- Runtime: "approximately 0.2 seconds to generate the next four actions" (~5 Hz), on a
  remote A100.
- Why it matters: quantifies which tasks need history. Instruction following needs the
  long-term memory (SR would collapse to <10% without it); person-following is nearly
  memoryless. Parcel's "follow me" and "go to the sofa" therefore need different memory
  depth from the same stream.

### 1.3 NaVILA: Legged Robot Vision-Language-Action Model for Navigation
- URL: https://arxiv.org/abs/2412.04453 (full text read at https://arxiv.org/html/2412.04453v1)
- Cheng, Ji, Yang, ... Xiaolong Wang (UCSD/NVIDIA). arXiv Dec 2024, rev. Feb 2025.
- What it is: VILA-based VLM emits mid-level language actions ("moving forward 75cm",
  "turn right 30 degrees") at low rate; a visual RL locomotion policy executes them on
  legged robots (Unitree Go2, H1, G1). Memory = a set of uniformly sampled history frames
  plus the current frame, distinguished by textual cues.
- History-length ablation (Table 8, R2R-CE val-unseen): **8 frames SR 49.7 / SPL 45.5;
  16 frames 48.6 / 44.4; 32 frames 49.5 / 44.1; 64 frames 50.1 / 45.4.** The paper concludes
  8 frames are sufficient; "For real-world experiments, we use an 8-frame memory size due
  to latency constraints."
- Headline: R2R-CE SR 54.0 / SPL 49.0; RxR-CE SR 49.3 / SPL 44.0. Real world: "88% success
  rate on 25 instructions"; 75% on complex instructions across Workspace/Home/Outdoor.
- Runtime: "The VLA inference time is approximately 0.6 seconds per sample"; quantization
  improved speed ~40%. LiDAR on the robot broadcasts at 15 Hz; locomotion runs in real time.
- Why it matters: on a Go2 with a language-action interface, 8 frames of history saturate
  R2R-CE success; extra frames buy nothing. Combined with 1.2, the recipe is "few frames,
  but they must span the whole episode".

## 2. Memory tokens and memory banks in VLAs

### 2.1 MemoryVLA: Perceptual-Cognitive Memory in Vision-Language-Action Models for Robotic Manipulation
- URL: https://arxiv.org/abs/2508.19236 (full text read at https://arxiv.org/html/2508.19236)
- Shi et al. arXiv Aug 2025, rev. Jan 2026.
- What it is: 7B Prismatic VLM (LLaMA-7B) produces per step **256 perceptual tokens + 1
  cognitive token**; a Perceptual-Cognitive Memory Bank keeps up to L entries per stream;
  working memory queries it by cross-attention with timestep positional encoding; the bank
  is consolidated by merging the most similar adjacent entries (averaging).
- Memory-length ablation (Table 6, SimplerEnv-Bridge): **L=4 -> 67.7%; L=16 -> 71.9%;
  L=64 -> 67.7%.** Memory type: both 71.9% vs cognitive-only 63.5% vs perceptual-only 64.6%.
- Headline: Bridge 71.9%, Fractal 72.7%, LIBERO-5 96.5%, Mikasa-Robo 41.2%; real-world
  6 long-horizon temporal tasks avg 83% ("+26" over CogACT): Sequential Push Buttons 58%,
  Change Food 85%, Guess Where 72%, Clean Table & Count 84%, Pick Place Order 100%, Clean
  Restaurant Table 96%.
- Why it matters: a second independent "bounded memory beats long memory" result (16 >
  64 entries), and the 1-token "cognitive" summary per step is a cheap representation the
  narrator side could read.

### 2.2 HAMLET: Switch your Vision-Language-Action Model into a History-Aware Policy
- URL: https://arxiv.org/abs/2510.00695 (full text read at https://arxiv.org/html/2510.00695v1)
- Koo, Choi, Kim, Lee, Kim, Seo, Shin (KAIST). arXiv Oct 2025.
- What it is: plug-in for pretrained VLAs: **4 moment tokens per timestep** initialised with
  time-contrastive learning (photometric/blur/noise/occlusion perturbations) + a lightweight
  memory module over the past timesteps (default history length 4).
- Ablation (Table 5b, success rate vs number of tokens): 1: 64.3%, 4: 65.4%, **8: 66.4%**,
  16: 65.9%, 32: 62.7%, 64: 62.5%. (Note: the fetch labelled the axis "token lengths"; verify
  against the PDF whether it is moment-token count or history length before quoting further.)
- Headline: GR00T N1.5 on RoboCasa Kitchen 66.4% vs 64.1% baseline; CogACT on SimplerEnv-
  Bridge 63.5% vs 52.1%; LIBERO-Long 92.2% vs 87.8%; real-world 3-task avg 76.4% vs 29.2%.
- Overhead (Table 4): at history length 4, latency 1.02x and peak memory 1.96x vs
  single-frame.
- Why it matters: a few (4-8) learned tokens per timestep is enough to make a frozen VLA
  history-aware at ~2% latency cost; more tokens hurt.

### 2.3 EventVLA: Event-Driven Visual Evidence Memory for Long-Horizon VLA Policies
- URL: https://arxiv.org/pdf/2606.20092 (full text read at https://arxiv.org/html/2606.20092)
- Yang, Tu, Yang, et al. arXiv June 2026 (v2).
- What it is: a Keyframe Evidence Memory commits an "event" whenever a learned keyframe
  probability crosses **tau_commit = 0.55**; memory M_t = anchors (initial frame o_0 + a
  short window of ~3 recent frames) plus at most **N_max = 5 event keyframes**; the memory is
  fed to the VLM as concatenated raw images.
- Numbers: RoboTwin-MeM avg **75.2%** vs pi0.5 (no memory) 7.8% vs MemoryVLA (dense memory)
  10.8%; RMBench 67.8%; real bimanual up to 80%; "+40% improvement over state-of-the-art
  memory-augmented VLAs". Buffer ablation: **N_max=2 -> 32.0%** (from 75.2%).
- Throughput: 0.94 Hz / 1.09 s latency for full EventVLA vs 2.91 Hz / 0.36 s for the
  QwenOFT baseline.
- Why it matters: "sparse event tokens" in practice = a handful of committed keyframes.
  Five was enough to beat dense memory by 7x on a memory-diagnostic benchmark; two was not.

### 2.4 Explicit Language Memory for Long-Horizon Planning in Vision-Language-Action Models
- URL: https://arxiv.org/html/2608.04765v1
- Xu, Li, Ye (Fudan). arXiv Aug 2026.
- What it is: a high-level VLM (PaliGemma) reads {global instruction, current observation,
  previous memory} and writes an updated **natural-language memory** that "stores completed
  skills in the past tense and transitions to the next skill using a future-oriented
  statement", tracking "completed stages, completion evidence, relevant object attributes,
  observed failures, and the next pending milestone". A rolling-compression rule collapses a
  finished subtask into one past-tense sentence. Example: "I am moving to the red radio on
  the coffee table." -> "I moved to the radio, and I am going to pick up the red radio." The
  low-level VLA (300M Gemma action expert) gets only the current observation + subtask and
  predicts a fixed-horizon action chunk.
- Numbers: BEHAVIOR-1K radio task 30.0% -> 40.0%; Genie Sim 3.0 package sorting 41.7% ->
  63.9% (single) and 31.3% -> 46.9% (continuous); real XLeRobot pick-and-place 62.5% ->
  66.3% over 20 trials. No latency or memory-format ablation reported.
- Why it matters: this is almost exactly the Model B narration representation ("Sure,
  I'll check the sofa" / "Done!") used as a *policy input*, and it improves the policy.
  It argues for one shared past-tense/future-tense language memory serving both Model A
  and the narrator.

### 2.5 Recurrent Memory Transformer (canonical "memory tokens")
- URL: https://proceedings.neurips.cc/paper_files/paper/2022/hash/47e288629a6996a17ce50b90a056a0e1-Abstract-Conference.html
  (PDF read locally after download)
- Bulatov, Kuratov, Burtsev. NeurIPS 2022.
- What it is: special read/write memory tokens prepended/appended to each segment; the
  written memory vectors are passed to the next segment; trained with BPTT across segments.
- Numbers (Table 2, WikiText-103, segment 150): Tr-XL memory 25 ppl 25.57; Tr-XL memory 75
  ppl 24.68; **RMT 10 memory tokens (BPTT-3) ppl 25.04**; RMT 25 tokens 24.85; Tr-XL 150 +
  RMT 10 = 23.99 (best). Segment 50: RMT 1 memory token 28.71 ~ Tr-XL memory 10 28.98;
  RMT 10 tokens 26.37 vs Tr-XL 50 cached states 26.54. "RMT wins a lot when only one memory
  token is added but then the effect from increasing memory size from 5 to 50 fades".
  Adding 10 memory tokens to 512-token BERT/RoBERTa "allows to encode longer stretches of a
  text up to 2000 tokens".
- Why it matters: the canonical result that 5-25 learned memory tokens carry as much as
  50-75 raw cached states, with diminishing returns above ~10. Sets the prior for how many
  "world-state tokens" Model A should carry between 10 Hz frames.

## 3. Streaming video LLMs: sparse tokens and when-to-speak

### 3.1 VideoLLM-online: Online Video Large Language Model for Streaming Video
- URL: https://arxiv.org/abs/2406.11816 (full text read at https://arxiv.org/html/2406.11816)
- Chen et al. (NUS). CVPR 2024.
- What it is: the LIVE framework; frames sampled at **2 FPS**, each frame = **1 CLS token**
  (efficient) or **1 + 3x3 pooled = 10 tokens**; language and frame tokens interleaved in a
  continuous KV cache; a **streaming EOS objective** trains the model to emit EOS on frames
  where no narration is due, so the model learns *when* to speak. A 5-minute clip at 2 FPS
  (~600 frames) is 600 tokens in the 4096 Llama window.
- Numbers (Ego4D narration stream): LM-PPL 2.43, **TimeDiff 2.32 s**, Fluency 42.6%.
  Speed "over 10 FPS on an A100" for 5-minute videos, memory "< 20 GB". Base Llama-2-7B-Chat /
  Llama-3-8B-Instruct. Narration format: timestamped egocentric sentences like "C picks up a
  wire from the floor".
- Why it matters: gives the narrator-timing mechanism (EOS-on-frame) and a metric
  (TimeDiff, seconds between expected and emitted narration) Parcel's conversation-quality
  scorer lacks today.

### 3.2 Flash-VStream: Memory-Based Real-Time Understanding for Long Video Streams
- URL: https://arxiv.org/abs/2406.08085 (full text read at https://arxiv.org/html/2406.08085v2)
- Zhang, Wang, Tang, Liu, Feng, Dai, Jin. arXiv June 2024 (ICCV 2025 version at 2506.23825).
- What it is: a frame handler writes into a fixed-size **STAR memory** (Spatial, Temporal,
  Abstract, Retrieved) while a question handler reads it asynchronously. Implementation:
  P_spa=8, P_tem=4, P_abs=1, N_buff=300, N_spa=1, N_tem=N_abs=25, N_ret=3, i.e. spatial 1x64
  tokens, temporal 25x16, abstract 25x1, retrieved 3x64; **"The MAXSIZE of STAR memory is set
  to 681 tokens"**; feature buffer 300 frames x 64 tokens.
- Numbers: VRAM 16.03 GB vs LLaMA-VID 33.64 GB vs Chat-UniVi 77.56 GB (A100); answers
  "within 1 second" on streams up to ~1000 frames; VStream-QA RVS-Ego 57.3 acc, RVS-Movie
  53.1. Vicuna-7B.
- Why it matters: a concrete, fixed 681-token budget for "everything the model remembers",
  split by granularity, with the writer and reader decoupled - the same decoupling Model A
  (writer) / Model B (reader) needs.

### 3.3 Event-VStream: Event-Driven Real-Time Understanding for Long Video Streams
- URL: https://arxiv.org/html/2601.15655
- arXiv Jan 2026. LLaMA-3-8B backbone with the VideoLLM-online encoder at 2 FPS.
- What it is: an "event" = "a temporally coherent segment in which visual semantics remain
  stable". Boundary score E_t = w_sem(1-s_t) + w_mot*m_t + w_pred*c_t (semantic drift,
  motion energy, next-embedding prediction error); a boundary fires when sigma(E_t) exceeds
  an adaptive threshold tau_t = tau_0(1 + eta*Var(m)) with **tau_0 = 0.96**. Each event is
  stored as **one consolidated embedding** in an event memory bank with a merge-or-append rule.
- Numbers: OVOBench-Realtime 28.15 vs VideoLLM-Online-8B 17.73 (+10.4) vs Flash-VStream-7B
  28.37; Ego4D 2-hour streams ~70% GPT-5 win rate (88.3% in the final segment) while
  frame-based baselines degrade or OOM; ~17 FPS on one RTX 6000 Ada; 0.05-0.08 s/token.
- Why it matters: the operational definition of a "sparse event token" stream: run change
  detection on the embedding stream, emit one token per stable segment. This is how Parcel
  could turn 10 Hz sensor frames into the "last minute" at a few dozen tokens.

### 3.4 LiveStar: Live Streaming Assistant for Real-World Online Video Understanding
- URL: https://arxiv.org/html/2511.05299
- Yang, Zhang, Hu, Wang, Qian et al. arXiv Nov 2025. InternVideo2.5 (InternViT + InternLM2.5-7B).
- What it is: **response-silence decoding**: generate a new caption only if
  PPL_now > alpha * PPL_last with **alpha = 1.03** (best in 1.02-1.04); "peak-end" memory
  compression prunes frames older than a **W = 40-frame** window probabilistically by relative
  perplexity and age; 1-4 FPS, **16 tokens per frame**; dual-level KV cache gives 1.53x speedup.
- Numbers: 3.82 FPS on 5-minute videos; OmniStar-RNG SemCor 3.19 vs MMDuet 1.93, TimDiff
  1.91 vs 2.32; Ego4D narration TokAcc 61.1% vs LION-FS 52.4%; ~19.5% SemCor gain and 18.1%
  TimDiff reduction averaged over 5 tasks.
- Why it matters: a second, model-agnostic gate for "should the narrator say something now"
  (surprise relative to the last utterance), which Model B can compute over Model A's stream.

## 4. Scene-graph memory

### 4.1 ConceptGraphs: Open-Vocabulary 3D Scene Graphs for Perception and Planning
- URL: https://arxiv.org/abs/2309.16650 (full text read at https://arxiv.org/html/2309.16650v1)
- Gu et al. (Toronto/MIT/Montreal...). arXiv Sept 2023, ICRA 2024.
- What it is: SAM segments + CLIP features fused across views into object nodes; LLaVA
  captions; GPT-4 writes node tags and spatial edges. For planning, objects are serialised to
  JSON: `{"id": 3, "bbox_extent": [0.6, 0.5, 0.4], "bbox_center": [2.8, -0.4, -0.8],
  "object_tag": "vase"}` (+ caption).
- Numbers: scenes hold ~23-60 valid objects (Replica room0 54, office3 60); scene-graph
  "71% node precision, 88% edge precision on average"; Replica semantic seg 40.63 mAcc /
  35.95 F-mIoU; LLM object retrieval on 10 real-lab affordance queries 1.00; LLaVA-7B
  captions "inaccurate about 30% of the time". Robots: Clearpath Jackal, Boston Dynamics Spot.
  Per-frame runtime not stated; cost of many LVLM/LLM calls flagged as a limitation.
- Why it matters: the per-object JSON node is the natural "global history" unit for
  Parcel's SigLIP-2 semantic grounding; a whole room is a few dozen nodes.

### 4.2 HOV-SG: Hierarchical Open-Vocabulary 3D Scene Graphs for Language-Grounded Robot Navigation
- URL: https://arxiv.org/abs/2403.17846 (full text read at https://arxiv.org/html/2403.17846v2)
- Werby, Huang, Buechner, Valada, Burgard (Freiburg/TU Nuremberg). RSS 2024.
- What it is: floor -> room -> object hierarchy with open-vocabulary features; GPT-3.5
  decomposes "find the toilet in the bathroom on floor 2" into [floor, room, object]; a
  cross-floor Voronoi graph for traversal.
- Numbers: representation size across 8 HM3DSem scenes **1493 MB (HOV-SG) vs 6068 MB
  (VLMaps)** ("75% reduction"); floor count 100% correct; room classification 73.93% exact /
  84.10% approximate; object AUC-top-k 84.88%; Replica mIoU 0.231 / F-mIoU 0.386 / mAcc 0.304.
  Real world on Spot, two-storey office: **object retrieval 29/41 = 70.7%, navigation 23/41
  = 56.1%**. Limitations: construction "is time-consuming, rendering the method unsuitable
  for real-time mapping" and "assumes a static environment".
- Why it matters: gives the size of a whole-building semantic memory (~190 MB/scene) and
  the real-robot gap between "knows where it is" (71%) and "gets there" (56%).

### 4.3 SayPlan: Grounding Large Language Models using 3D Scene Graphs for Scalable Robot Task Planning
- URL: https://arxiv.org/abs/2307.06135 (full PDF read locally; PMLR v229 CoRL 2023)
- Rana, Haviland, Garg, Abou-Chakra, Reid, Suenderhauf (QUT). CoRL 2023.
- What it is: the 3DSG (floors/rooms/assets/objects + a dynamic agent node) is
  "text-serialised into a JSON data format"; sample node: `{name: coffee_machine, type:
  asset, location: kitchen, affordances: [turn_on, turn_off, release], state: off,
  attributes: [red, automatic], position: [2.34, 0.45, 2.23]}`. The LLM works on a
  **collapsed** graph and calls expand/contract/verify_plan; a scene-graph simulator feeds
  back errors for iterative replanning (capped at 5 rounds). GPT-4; static prompt ~3900 tokens.
- Token counts (Tables 2, 4, 5): Office full graph 407 entities / **6731 tokens** vs collapsed
  105 entities / **878 tokens** (86.9% compression; 82.1% reduction of initial input); Home
  6598 vs 1817 (72.5%). Per-entity averages: room node 9.19 tokens, asset node 27.3, object
  node 32.6, edge 8.45; whole-graph average 16.5 tokens/entity. Node contraction keeps the
  token count "near-constant" during search (Fig. 3).
- Results (Table 1/3): semantic search success GPT-4 86.7% (simple) / 73.3% (complex) vs
  GPT-3.5 6.6% / 0.0%; long-horizon planning **SayPlan correctness 73.3% / executability
  86.6%** vs LLM-As-Planner 66.7% / 13.3% vs LLM+P 33.3% / 0.0%; simple planning all 93.3%
  correct, SayPlan 100% executable. Robot: Franka Panda on an Omron LD-60 base.
- Why it matters: the only source with explicit LLM token costs for a serialised world
  model at building scale, and evidence that a verifier loop (not a bigger context) is what
  makes plans executable.

### 4.4 Mem2Ego: Empowering VLMs with Global-to-Ego Memory for Long-Horizon Embodied Navigation
- URL: https://arxiv.org/abs/2502.14254 (full text read at https://arxiv.org/html/2502.14254)
- Zhang et al. (Huawei Noah's Ark). arXiv Feb 2025 (v2 June 2025).
- What it is: three global memories - frontier map, landmark semantic memory (text
  descriptions + coordinates), visitation memory - projected into the egocentric panorama as
  labelled circles (green candidates, blue visited) so the VLM (GPT-4o, or Llama3.2-11B
  fine-tuned on 30,352 VQA pairs from 104 scenes) reasons in image space instead of text.
- Numbers (HSSD ObjectNav): **SR 0.8685 / SPL 0.5788** vs PIVOT 0.7840 / 0.5658 vs LFG
  0.6244 / 0.3371; HSSD-Hard 0.7647 vs 0.6372. Ablation: no visitation memory SR 0.8450; no
  landmark memory SR 0.8356.
- Why it matters: shows that rendering global memory *into the current frame* beats
  verbalising the map, which is relevant to how Parcel's occupancy grid + goal could be
  injected into Model A's visual stream rather than as text.

## 5. World-model tokens

### 5.1 DreamerV3: Mastering Diverse Domains through World Models
- URL: https://arxiv.org/abs/2301.04104 (full PDF read locally; Nature 640:647-653, 2025)
- Hafner, Pasukonis, Ba, Lillicrap.
- What it is: RSSM world model - sequence model h_t = f(h_{t-1}, z_{t-1}, a_{t-1}); encoder
  z_t ~ q(z_t | h_t, x_t); dynamics predictor p(z_t | h_t); reward/continue/decoder from
  (h_t, z_t). Latents are vectors of categorical (softmax) distributions with straight-through
  gradients; "the categorical distributions ... as mixtures of 1% uniform and 99% neural
  network output". Actor/critic act on s_t = {h_t, z_t}, "the Markovian representations
  learned by the recurrent world model".
- Sizes (Table 3): 12M/25M/50M/100M/200M/400M params; hidden 256/384/512/768/1024/1536;
  **recurrent units 1024/3072/4096/6144/8192/12288** (GRU with block-diagonal weights, 8
  blocks); codes per latent 16/24/32/48/64/96; number of latents fixed across sizes.
- Training (Table 4): batch 16 x **length 64 steps**; **imagination horizon 15**; free nats 1;
  loss scales pred 1 / dyn 1 / rep 0.1; replay capacity 5e6; 200M model default on one A100;
  Minecraft diamonds at 100M env steps with 10 seeds; "over 150 diverse tasks" with one
  config; performance rises monotonically 12M -> 400M.
- Why it matters: the learned-summary alternative to token memory: a single recurrent
  state (1-12K units) is the whole history, trained on 64-step windows (6.4 s at 10 Hz) and
  used for 15-step imagination. A world-model h_t is an obvious candidate for the
  "representation the narrator reads", but nothing in the paper decodes it to language.

### 5.2 V-JEPA 2: Self-Supervised Video Models Enable Understanding, Prediction and Planning (V-JEPA 2-AC)
- URL: https://arxiv.org/abs/2506.09985 (full text read at https://arxiv.org/html/2506.09985)
- Meta FAIR, June 2025. CC BY 4.0.
- What it is: ViT-g encoder (>1B params) pretrained on VideoMix22M (22M samples, "over 1
  million hours of internet video" + 1M images); V-JEPA 2-AC post-trains a ~300M
  action-conditioned predictor (24 layers, 16 heads, 1024 hidden) on "less than 62 hours of
  unlabeled robot videos from the Droid dataset"; context = **16-frame clips at 256x256, 4 fps**
  (4 s); planning by CEM with 800 samples x 10 iterations, horizon 1 step.
- Numbers: **"only 16 seconds per action"** vs Cosmos "4 minutes"; zero-shot Franka (2 labs
  avg) reach 100%, grasp cup 65%, grasp box 25%, pick-and-place cup 80%, box 65%. Video
  understanding: SSv2 77.3 top-1, EK100 anticipation 39.7 R@5, PerceptionTest 84.0.
- Why it matters: latent world-model planning works zero-shot from ~60 h of robot video,
  but at 16 s/action it is a training-time or offline tool, not a 10 Hz runtime; its 4 s
  context is the "last few seconds", not the last minute.

### 5.3 Genie 3: A New Frontier for World Models
- URL: https://deepmind.google/blog/genie-3-a-new-frontier-for-world-models/
- Google DeepMind blog, 5 Aug 2025 (no paper).
- Numbers: generated worlds at **720p, 24 fps**, "largely consistent for several minutes",
  "visual memory extending as far back as one minute ago"; promptable world events; tested
  with a SIMA agent. Stated limitations: "Limited action space", "a few minutes of continuous
  interaction", weak multi-agent simulation, imperfect geographic accuracy, poor text.
- Why it matters: the frontier's own horizon for a generative world memory is ~1 minute, the
  same window the owner asked for; also a candidate sim for the sim-to-real "LLM talks while
  the robot navigates" testbed, but only via DeepMind access.

## 6. Episodic / tiered memory and plan traces

### 6.1 Generative Agents: Interactive Simulacra of Human Behavior
- URL: https://arxiv.org/abs/2304.03442 (full text read at https://ar5iv.labs.arxiv.org/html/2304.03442)
- Park, O'Brien, Cai, Morris, Liang, Bernstein (Stanford/Google). UIST 2023.
- What it is: a memory stream of natural-language records ("Isabella Rodriguez is setting
  out the pastries"), each with creation and last-access timestamps; retrieval score =
  normalised recency (exponential decay, **factor 0.995** per game hour since last access) +
  importance (LLM integer 1-10) + relevance (embedding cosine), equal weights; **reflection
  fires when summed importance of recent events exceeds 150** ("roughly two or three times a
  day"); plans recursively decomposed day -> hour -> 5-15 minute chunks. 25 agents; gpt-3.5-turbo.
- Numbers (TrueSkill mu): full 29.89; no reflection 26.88; no reflection+planning 25.64;
  human crowdworker 22.95; no memory/planning/reflection 21.21.
- Why it matters: the reference design for a "global history" store: append-only NL
  events, three-factor retrieval, periodic reflection. The importance-threshold trigger is a
  ready-made rule for when Model B should compress old plan-queue entries.

### 6.2 Voyager: An Open-Ended Embodied Agent with Large Language Models
- URL: https://arxiv.org/abs/2305.16291 (full text read at https://arxiv.org/html/2305.16291)
- Wang, Xie, Jiang, Mandlekar, Xiao, Zhu, Fan, Anandkumar (NVIDIA et al.). 2023.
- What it is: the LLM's state input is a structured text block: "inventory, equipment,
  nearby blocks and entities, biome, time, health and hunger bars, and position" plus seen
  chests and "previously completed and failed tasks"; a skill library of executable code
  indexed by GPT-3.5 descriptions, top-5 retrieval; iterative prompting with environment
  feedback, execution errors and a GPT-4 self-verification critic.
- Numbers: 63 unique items in 160 prompting iterations; 3.3x items, 2.3x distance, tech tree
  15.3x (wooden) / 8.5x (stone) / 6.4x (iron) faster; without self-verification -73% items;
  GPT-4 vs GPT-3.5 5.7x more items.
- Why it matters: canonical example of a compact, typed state digest plus explicit
  completed/failed task lists as LLM input - the ancestor of Parcel's StateDigest.

### 6.3 MemGPT: Towards LLMs as Operating Systems
- URL: https://arxiv.org/abs/2310.08560 (full text read at https://arxiv.org/html/2310.08560)
- Packer, Wooders, Lin, Fang, Patil, Stoica, Gonzalez (Berkeley). Oct 2023 / Feb 2024.
- What it is: main context = system instructions + working context (fixed-size read/write
  text, editable only by function calls) + FIFO message queue; external = recall storage
  (message DB) + archival storage. Memory-pressure warning at "70% of the context window",
  flush at "100%", evicted messages folded into a recursive summary. All edits self-directed
  via function calls.
- Numbers: deep memory retrieval MemGPT+GPT-4 **92.5% acc / 0.814 ROUGE-L** vs GPT-4 fixed
  context 32.1% / 0.296; conversation opener 0.868 vs human 0.800; nested key-value retrieval
  perfect across nesting levels while GPT-4 baseline "hit 0 percent accuracy by 3 nesting
  levels".
- Why it matters: the tiered-context template for the "historical queue of global plans":
  a small always-present working block, a FIFO of recent turns, and archival retrieval.

### 6.4 ReAct: Synergizing Reasoning and Acting in Language Models
- URL: https://arxiv.org/abs/2210.03629
- Yao, Zhao, Yu, Du, Shafran, Narasimhan, Cao. ICLR 2023. (Abstract read.)
- What it is: interleaved thought / action / observation traces; "reasoning traces help
  the model induce, track, and update action plans".
- Numbers: ALFWorld +34 percentage points and WebShop +10 points over imitation/RL
  baselines with "only one or two in-context examples".
- Why it matters: canonical "plan trace" format; the thought line is the narrator's raw
  material.

### 6.5 Inner Monologue: Embodied Reasoning through Planning with Language Models
- URL: https://arxiv.org/abs/2207.05608 (full text read at https://ar5iv.labs.arxiv.org/html/2207.05608)
- Huang et al. (Google). CoRL 2022.
- What it is: the LLM planner's prompt is a running trace interleaving "Robot action:",
  "Scene:", "Success:", "Human:" lines, e.g. "Scene: There is a cyan, yellow, brown block.
  Human: Move all the blocks to the top left corner. Robot thought: ... Robot action: Pick the
  cyan block ... Scene: You have completed ...". Feedback types: success detection, passive
  scene description (structured, automatic), active scene description (LLM asks VQA/human),
  human feedback.
- Numbers: simulated tabletop pick-and-place 24.0% (CLIPort) -> 94.0% with object+scene
  feedback; unseen "put blocks in matching bowls" 0% -> 82.0%; real tabletop 90% vs 45%;
  real kitchen mobile manipulation **75% vs SayCan 50%** without disturbances and **60.4% vs
  30.8%** with adversarial disturbances. InstructGPT 1.3B (tabletop), PaLM 540B (kitchen).
- Why it matters: the strongest evidence that a *structured status stream* (success flags +
  scene deltas) fed back as text roughly doubles long-horizon completion under
  interruptions - the interruption/amendment case Parcel's evals target.

## 7. Structured belief state for dialogue

### 7.1 Interpretable and Robust Dialogue State Tracking via Natural Language Summarization with LLMs (NL-DST)
- URL: https://arxiv.org/abs/2503.08857 (full text read at https://arxiv.org/html/2503.08857)
- Carranza, Rojas. arXiv March 2025.
- What it is: instead of slot-value JSON, the LLM "directly generate[s] natural language
  descriptions of the dialogue state".
- Numbers: MultiWOZ 2.1 JGA **65.9% vs 58.1%** (structured GPT-2 baseline); Taskmaster-1
  48.7% vs 42.5%; at 20% input noise NL-DST keeps 52.1% JGA while the structured baseline
  drops to 43.5%. Model sizes not reported.
- Why it matters: for the narrator-facing belief state, a short NL summary is both more
  accurate and more noise-robust than slot JSON; keep JSON for the executive, NL for the
  hosted voice model.

---

## 8. Cross-source table

| Source | Per-step / per-frame budget | Total memory budget | Update rate | History-length effect (measured) |
|---|---|---|---|---|
| StreamVLN | 196 tokens/frame (memory); 8 dialogue turns in window | 8x196 = 1568 memory tokens + window | 4 actions per 0.27 s (RTX 4090) | Memory 2x196 SR 37.3 -> 8x196 45.5; all-context 40.0. Window 2/4/8 turns: 43.7/41.4/45.5 |
| Uni-NaVid | current 64, short 4, long 1 token/frame | 64-frame short buffer + unbounded 1-token long tail | 4 actions per 0.2 s (A100) | VLN SR 9.61 (current) -> 39.7 (+short) -> 48.7 (+long); following 56.3 -> 61.2 |
| NaVILA | frames of history (count varies) | 8 frames in real world | VLA 0.6 s/sample; LiDAR 15 Hz | 8/16/32/64 frames SR 49.7/48.6/49.5/50.1 (flat) |
| MemoryVLA | 256 perceptual + 1 cognitive token/step | L entries per stream | not stated | L=4/16/64: 67.7/71.9/67.7% |
| HAMLET | 4 moment tokens/step | history 4 | latency 1.02x, memory 1.96x | 1/4/8/16/32/64: 64.3/65.4/66.4/65.9/62.7/62.5% |
| EventVLA | 1 keyframe per committed event (tau 0.55) | N_max 5 keyframes + init + 3 recent | 0.94 Hz | N_max 2 -> 32.0%, 5 -> 75.2% |
| RMT | 1-25 memory tokens per segment | same | per segment | 1 token ~ Tr-XL cache 10; 10 tokens ~ cache 50-75; gains fade above ~10 |
| VideoLLM-online | 1 or 10 tokens/frame at 2 FPS | 600 tokens per 5 min (efficient) | >10 FPS A100 | TimeDiff 2.32 s |
| Flash-VStream | 64 tokens/frame into buffer | STAR max 681 tokens | answers <1 s at 1000 frames | - |
| Event-VStream | 1 embedding per event | event bank | 17 FPS RTX 6000 Ada | stable over 2 h; baselines OOM |
| LiveStar | 16 tokens/frame, 1-4 FPS | 40-frame window + peak-end pruning | 3.82 FPS | alpha 1.02-1.04 gate |
| SayPlan | 8-33 tokens per graph entity | Office 6731 full / 878 collapsed tokens (+3900 prompt) | per replanning round, max 5 | executability 13% -> 86.6% via replanning, not context |
| HOV-SG | - | 1493 MB / 8 scenes vs 6068 MB dense | offline | - |
| DreamerV3 | h_t 1024-12288 units | one recurrent state | every env step | trained on 64-step windows, 15-step imagination |
| V-JEPA 2-AC | 16 frames @ 4 fps | 4 s context | 16 s per planned action | - |
| Genie 3 | 720p @ 24 fps | ~1 minute visual memory | real time | consistency "several minutes" |
| Generative Agents | one NL record per event | unbounded stream, retrieval top-k | reflection when importance sum > 150 | ablation: 29.89 -> 21.21 TrueSkill |
| MemGPT | working context block + FIFO | warn 70%, flush 100% | per turn | 92.5% vs 32.1% deep retrieval |

## 9. What this means for Parcel's Model A / Model B

**Model A input stream ("last minute + global history")**

1. Use a three-tier budget, not a flat window. Every strong streaming policy allocates
   tokens by age: full current frame, ~1/16 for the recent window, ~1/64 for the far past
   (Uni-NaVid 64/4/1), or 8 turns fast + 8x196 slow (StreamVLN), or a fixed 681-token STAR
   memory (Flash-VStream). At Parcel's 10 Hz act-token clock, "the last minute" is 600
   frames; nobody feeds 600 full frames. Concretely: current frame full; last ~6 s (60 ticks)
   at 4 tokens/tick = 240 tokens; the remaining ~54 s at 1 token/tick = 540 tokens; total
   under ~1.2K tokens for the minute, plus a global tail.
2. Bounded beats unbounded, three times over. StreamVLN "all context" 40.0 SR vs pruned
   8x196 45.5; MemoryVLA 64 entries 67.7% vs 16 entries 71.9%; HAMLET 32-64 tokens 62.7/62.5%
   vs 8 tokens 66.4%. RMT's language-model result says the same (gains fade above ~10 memory
   tokens). Design the memory as a fixed budget with a merge rule (MemoryVLA: merge most
   similar adjacent entries; Event-VStream: merge-or-append by similarity), not a growing log.
3. "Global history" should be event-sparse keyframes plus a language ledger, not video.
   EventVLA needed only 5 committed keyframes (2 was catastrophic: 32% vs 75%); Event-VStream
   keeps one embedding per stable segment with tau_0 0.96 and stays flat over 2-hour streams.
   Parcel already has the discrete act-token codec; add an event-boundary detector on the
   embedding stream (semantic drift + motion energy + prediction error) and let Model A commit
   keyframes into a small bank.
4. Which tasks need which depth is measurable and task-dependent: instruction following
   collapses without long-term memory (Uni-NaVid VLN 48.7 -> 9.61), person-following barely
   changes (61.2 -> 56.3), and 8 spanning frames saturate R2R-CE (NaVILA). So the 5x5
   instruction-navigation matrix should be run with memory depth as an axis; expect the
   long-horizon tiers to be the only ones that move.
5. Inject global structure into the frame, not only as text. Mem2Ego's projected landmark /
   frontier / visited marks beat verbalised maps (SR 0.8685 vs 0.7840), and SayPlan shows a
   serialised building costs ~6.7K tokens uncollapsed. For Model A, the LiDAR occupancy grid,
   goal, and semantic anchors should be rendered into the visual stream (or a compact grid
   token), with the JSON scene graph reserved for the executive and Model B.
6. If a learned world-model state is used as the "representation the narrator reads", note
   the scale: DreamerV3's recurrent state is 1-12K units trained on 64-step windows with a
   15-step imagination horizon; V-JEPA 2-AC's context is 4 s and its planner takes 16 s per
   action. Latent world models are training-time/imagination tools here; the narrator needs a
   decodable representation, which none of these provide by themselves.

**Model B (voice injection + narration context)**

7. Keep one explicit language memory shared by policy and narrator. The Explicit Language
   Memory paper's past-tense/future-tense ledger ("I moved to the radio, and I am going to
   pick up the red radio") raised success 10-22 points *as a policy input* and is literally
   the "Sure, I'll check the sofa ... Done!" narration the owner asked for. Model B should write
   this ledger from Model A's output stream and the executive's queue; the hosted voice reads it.
8. Represent status to the LLM as an interleaved trace, not a snapshot. Inner Monologue's
   "Robot action / Scene / Success / Human" lines doubled real-kitchen completion under
   adversarial disturbances (60.4% vs 30.8%), and ReAct's thought/action/observation trace
   gives +34 points on ALFWorld. Parcel's StateDigest (nav state, blocked, following, battery,
   e-stop) is a snapshot; extend it to a rolling trace of (intent -> action chunk -> outcome ->
   scene delta) events that the whisperer forwards.
9. Decide *when* to narrate with a learned or surprise-based gate. VideoLLM-online's
   streaming-EOS objective and LiveStar's perplexity-ratio gate (alpha 1.03) are the two
   published mechanisms; timing is measured as TimeDiff (~2 s). Parcel's conversation-quality
   scorer has no timing metric; add TimeDiff-style scoring of narration relative to plan-state
   transitions (goal accepted, blocked, replanned, done).
10. Belief state: JSON for the executive, NL sentence for the voice. NL-DST beat slot JSON
    by 7.8 JGA points and held up better under 20% noise (52.1 vs 43.5). The transactional goal
    amendment already has a structured form; render each queue entry as one NL line
    ("Going to the sofa first, then back to the door; the kitchen check is queued") for the
    hosted model's context.
11. Global-plan queue as tiered memory. Use MemGPT's shape (small always-present working
    block = current plan + last outcome; FIFO of recent turns; archival retrieval for older
    plans) with Generative Agents' retrieval score (recency decay 0.995, importance 1-10,
    relevance) and its reflection trigger (importance sum > 150) as the rule for when Model B
    compresses old queue entries into a summary.
12. Runtime budget reality check for Orin. Every VLN policy above ran its 7-8B VLM on a
    remote RTX 4090 / A100 at 2-5 Hz emitting 4-action chunks (StreamVLN 0.27 s, Uni-NaVid
    0.2 s, NaVILA 0.6 s). The 10 Hz duplex clock is therefore best served by Model A emitting
    act-token chunks at 2-5 Hz with the codec filling the 10 Hz ticks, and Model B / narration
    at ~1 Hz or event-triggered.

## 10. Open questions

- None of the memory ablations were run under mid-task interruption or goal amendment; the
  measured history-length effects are for uninterrupted VLN/manipulation episodes. Parcel's
  interruption tier is uncharted.
- Token budgets above are for RGB video. There is no published budget for LiDAR occupancy,
  audio/voice, or user-context streams inside one duplex model; the 64/4/1 and 8x196
  numbers are priors, not answers, for those modalities.
- Narration-timing metrics (TimeDiff, TokAcc, SemCor) exist only for egocentric video
  narration, never for a robot narrating its own plan while acting; whether hosted-voice
  narration at ~2 s lag is acceptable to an owner is untested.
- Whether the language ledger should be produced by a frozen VLM (Explicit Language Memory
  uses PaliGemma) or trained jointly with Model A end-to-end is open; no paper trains both.
- HAMLET's Table 5b axis (number of moment tokens vs history length) should be verified
  against the PDF before the 8-token optimum is quoted as a history-length result.
- Onboard latency on Jetson AGX Orin for a 7-8B streaming VLM at 2-5 Hz is not reported by
  any of these works; all used desktop/server GPUs.
- Genie 3 is blog-only (no paper, no access); its "one minute of visual memory" is a
  capability statement, not a benchmark.
