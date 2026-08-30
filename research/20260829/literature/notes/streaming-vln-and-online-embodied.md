# Streaming / online vision-language navigation and embodied models that act on continuous input

Research note for the Parcel Model A / Model B study. Date: 2026-08-29.
Every source below was fetched and read (arXiv HTML/ar5iv/abs pages, GitHub READMEs, HF model cards); numbers are quoted from the fetched text. Where two fetched sources disagree (paper table vs. repo README, v1 vs v2 of a preprint), both numbers are recorded.

Scope of the ask: input rate, memory mechanism (sliding window / token pruning / KV cache), output form (waypoint, velocity, action token), model size, training data, success on VLN-CE R2R/RxR, real-robot platform, latency, open weights + license.

---

## 0. One-table summary

| System | Year | Backbone / size | Input cadence | Memory | Output | R2R-CE val-unseen SR / SPL | Robot | Latency | Weights / license |
|---|---|---|---|---|---|---|---|---|---|
| VLN-CE (benchmark) | 2020 | Seq2Seq / CMA (~36M) | per-step RGBD | recurrent | fwd 0.25 m / turn 15° / stop | 20 / 0.18 (Seq2Seq); 32 / 0.30 (CMA+aug) | — (Habitat, 90 MP3D scenes) | — | code MIT; data CC BY-NC-SA 3.0 |
| NaVid | 2024 | Vicuna-7B + EVA-CLIP | video stream, all frames | 64 tok current + 4 tok/history frame | discrete action + argument (cm / degrees) in text | 37.4 / 35.9 (paper); 41.9 / 36.5 (repo) | Turtlebot4 + Kinect | 1.2–1.5 s/action | HF weights; repo MIT |
| Uni-NaVid | 2024 | Vicuna-7B + EVA-CLIP | 1 FPS video | online token merge 64 / 4 / 1 tokens | 4 discrete actions per step (25 cm, 30°) | 47.0 / 42.7 (paper); 51.8 / 47.7 (repo) | remote A100; platform in suppl. | ~0.2 s per 4 actions; ~5 Hz | HF weights; repo MIT |
| NaVILA | 2024 | VILA (Llama3-8B / Qwen2-7B) | 8–64 sampled frames | uniform frame sampling incl. first frame | mid-level language ("move forward 75 cm") -> RL policy at 50 Hz | 54.0 / 49.0 | Unitree Go2, H1, G1; 88% on 25 instr. | ~1 s per action (0.6 s VLA) | HF weights; code Apache-2.0 |
| StreamVLN | 2025 | LLaVA-Video (Qwen2-7B; HF card says 8B) | continuous video, 4 actions/turn | sliding-window KV cache (8 turns) + slow memory 8x196 tok + voxel pruning | 4 discrete actions per turn | 56.4 / 50.2; prune-mem 57.4 / 51.1 | Unitree Go2 + D455, remote RTX 4090 | 0.27 s per 4 actions + 0.2 s comm | HF weights CC BY-NC-SA 4.0 |
| DualVLN / InternVLA-N1 | 2025 | Qwen2.5-VL 7B (S2) + 384-d 12-layer DiT (S1) | S2 2 Hz, S1 30 Hz | pixel-goal + 4 latent query tokens | 32-waypoint trajectory | 64.3 / 58.5 | Turtlebot4, Go2, G1 | S2 0.7–1.1 s; S1 0.03 s (TensorRT); 20 GB on 4090 | HF weights CC BY-NC-SA 4.0 |
| Robostral Navigate | 2026 | 8B VLM + 121M diffusion | VLM 0.5 Hz, diffusion 10 Hz, ctrl 100 Hz | frame history | pixel waypoint (u,v) + heading | 77.4 / 74.2 | Galaxea R1, Hiwonder JetAuto | — | not stated (paper CC BY 4.0) |
| StereoNav ("What limits VLN?") | 2026 | stereo RGB agent | — | target-location priors as persistent visual cues | joint action+depth | 81.1 / 68.3 (w/ external data) | real robot, 4 scenarios: 60.6% vs StreamVLN 24.3% | — | — |
| TIC-VLA | 2026 | InternVL3-1B | policy 10 Hz, reasoning 0.5 Hz async | latency-conditioned reasoning tokens | 30-chunk (dx,dy,dθ) over 3 s | (DynaNav) SR 55.29 | Unitree Go2; 0.85 on RTX 4060 laptop, 0.75 on Jetson Orin NX | 86 ms action / 3.4 s reasoning (laptop); 120 ms / 4.8 s (Orin NX) | — |
| LiveVLN (runtime) | 2026 | wraps StreamVLN / NaVILA | async guard buffer | — | same as base model | 57.2 / 50.0 (StreamVLN+Live) | Unitree G1, RTX 5090 | waiting 7.32 s -> 1.63 s per episode | code on GitHub (paper CC BY 4.0) |
| Mobility VLA | 2024 | Gemini 1.5 Pro, 1M ctx | tour 948 frames @1 Hz | whole tour in context + COLMAP topo graph | waypoint (dx,dy,dθ) to MPC | 57 real instr.: RF 80%, RR 80%, SO 40%, MM 85% | wheeled mobile manipulator, 836 m² | 10–30 s per VLM call; 0.19 s low-level | closed |
| VLMnav | 2024 | Gemini Flash zero-shot | per step | 2-D explored voxel map | numbered arrow -> polar (r, θ) | HM3D ObjectNav 50.4 SR / 0.210 SPL | none (sim) | — | code released; paper CC BY 4.0 |
| NavGPT / DiscussNav / MapGPT | 2023–24 | GPT-4 / GPT-4V zero-shot | nav-graph step | textual history summary / linguistic topo map | node choice | R2R (nav-graph) SR 34 / 43 / 43.7 | DiscussNav: Turtlebot4, 25% on 20 instr. | tokens/step 2465 vs 672 | — |
| LOVON | 2025 | DeepSeek-R1 planner + YOLO-11 + 3.3M-param L2MM | camera stream | 5-state execution logic | [vx, vy, θ] velocity | Gym-Unreal SR 1.00 | Go2, B2, H1-2 | — | MIT (repo, weights) |
| QUART / QUART-Online | 2023–24 | Fuyu-8B | single image | none | 12-dim action tokens (vx, vy, ωz, gait, height, ...) | sim per-task 12–66%; real 13/20 | WR-2 quadruped | 2 Hz -> 50 Hz (ACD) | — |
| LocoVLM | 2026 | GPT-4o skill DB + BLIP-2 | advisory <100 ms | 300 skill descriptors | style-conditioned RL policy 50 Hz | 87/100 instruction accuracy | Unitree Go1, Jetson Xavier NX | <100 ms advisory | CC BY-NC-ND 4.0 |
| UrbanVLA | 2025 | Qwen2 backbone | 4 cameras, 2 Hz | route waypoints (20 over 40 m) | SE(2) waypoint trajectory | MetaUrban SocialNav 91% test / 88% unseen | Unitree Go2 (>500 m routes), remote RTX 4090 | 2 Hz | paper CC BY 4.0 |
| TartanGround (dataset) | 2025 | — | 10 Hz, 6 stereo pairs | — | — | — | omni-wheeled / diff-drive / legged (ANYmal D) | — | CC BY-NC-SA 4.0, ~15 TB |
| VLN-PE (embodied-gap benchmark) | 2025 | Isaac Sim + RL controllers | physical | — | — | NaVid zero-shot: H1 22.42, Aliengo 4.73, Jetbot 11.02 | real Go2 + D455: CMA 7.14 -> 28.57 after PE finetune | — | code in InternNav |

---

## 1. Benchmarks and datasets

### 1.1 VLN-CE — "Beyond the Nav-Graph" (Krantz et al., ECCV 2020)
- Fetched: https://ar5iv.labs.arxiv.org/html/2004.02857 and https://github.com/jacobkrantz/VLN-CE
- "the VLN-CE dataset consists of 4475 trajectories converted from R2R train and validation splits."
- "four simple, low-level actions for agents in VLN-CE – move forward 0.25m, turn-left or turn-right 15 degrees, or stop"; "an average action length of 55.88 compared to 5 in R2R."
- Baselines val-unseen: Seq2Seq SR 20% / SPL 0.18 / NE 8.94 m; CMA with all augmentations SR 32% / SPL 0.30 / NE 7.37 m.
- Gap to nav-graph: "our model yields 0.21 SPL" vs nav-graph SOTA "near 0.47 SPL, over 2x what we report".
- Repo: Habitat-Sim 0.1.7, 90 Matterport3D scenes, 480x640 RGBD; **challenge config uses "30 degree turn angles, a 0.25m step size"** (paper text says 15°). Code MIT; datasets CC BY-NC-SA 3.0 US + Matterport3D ToU. R2R val-unseen has 1,839 episodes (from NaVid repo / VLN-Cache).
- RxR-VLNCE: multilingual (English, Hindi, Telugu), Guide + Follower trajectories.

### 1.2 RxR — Room-Across-Room (Ku et al., EMNLP 2020)
- Fetched: https://github.com/google-research-datasets/RxR and https://arxiv.org/abs/2010.07954
- "126k navigation instructions in English, Hindi and Telugu"; "126k navigation following demonstrations"; "10x larger" than R2R with "longer and more variable paths"; pose traces (18.6 GB) time-align each word to the annotator's camera pose; "1.1m grounded landmarks"; annotations CC-BY 4.0.
- Why it matters: the pose-trace alignment is the only large dataset where speech-like language is time-locked to viewpoint — the closest existing supervision to "tight coupling of speech to movement".

### 1.3 IVLN — Iterative VLN (Krantz et al., 2022)
- Fetched: https://ar5iv.labs.arxiv.org/html/2210.03087
- Tours "of up to 100 ordered instruction-following Room-to-Room (R2R) episodes"; IR2R-CE: 414 tours, 48.1 mean episodes per tour; "after just 10 episodes an agent has seen on average over 50% of the target path associated with the next language instruction."
- Results: HAMT episodic SR 63%, t-nDTW 61%; TourHAMT degrades to t-nDTW 45%; MAP-CMA with iterative maps t-nDTW 48% val-unseen; unstructured-memory CMA variants stuck at t-nDTW 38%.
- Conclusion (quote): "extending the implicit memory of high-performing transformer VLN agents is not sufficient for IVLN, but agents that build maps can benefit from environment persistence."

### 1.4 CVDN — Cooperative Vision-and-Dialog Navigation (Thomason et al., 2019)
- Fetched: https://ar5iv.labs.arxiv.org/html/1907.04957
- 2050 human-human dialogs, 83 Matterport houses, "over 7k navigation trajectories punctuated by question-answer exchanges"; 7415 NDH instances (4742 / 382 / 907 / 1384).
- Dialogs average 81.6 words vs R2R 29; paths 25.0±12.9 (human) vs R2R 6.0±0.85.
- Goal-progress metric (metres); seq2seq full-history val-unseen 2.10 m vs shortest-path oracle 9.58 m — dialog-conditioned navigation was far from solved in 2019 and there is no continuous-environment successor with a streaming agent.

### 1.5 VLN-PE — "Rethinking the Embodied Gap in VLN" (Wang et al., ICCV 2025)
- Fetched: https://arxiv.org/html/2507.13019v1
- Platform: GRUTopia on Isaac Sim; RL controllers for Unitree H1/G1 humanoids, Unitree Aliengo quadruped, Jetbot wheeled. Real test: Unitree Go2 + RealSense D455.
- Zero-shot VLN-CE -> VLN-PE (humanoid, R2R val-unseen): Seq2Seq 25.99 -> 15.00; CMA 32.08 -> 16.04; NaVid 40.67 -> 22.42.
- Cross-embodiment (NaVid zero-shot): H1 22.42, **Aliengo 4.73**, Jetbot 11.02 — "The quadruped robot (about 0.5 m), with a significantly lower camera height, causes the model to nearly fail completely."
- Lighting (NaVid, RGB-only): 22.42 -> 9.95 (low light) / 11.17 (camera light); RGB-D CMA/RDP lose only ~2–3 points.
- Controller consistency: "the model performance is highest when the physical locomotion controller used during data collection and evaluation remains consistent" (CMA: 18.78 SR with controller in both phases, fall rate 18.63%, stuck 3.12%).
- Training on humanoid+quad+wheeled data: SR 18.78 -> 26.87, SPL 14.56 -> 23.54.
- Real Go2 (14 episodes): CMA VLN-CE-only SR 7.14 / OS 14.29; VLN-PE fine-tuned SR 28.57 / OS 57.14.
- 441 episodes from 3 synthetic scenes fine-tune CMA-CLIP 15.31 -> 22.46, RDP 26.19 -> 28.52, vs NaVid zero-shot 18.64.

### 1.6 TartanGround (Patel et al., IROS 2025)
- Fetched: https://arxiv.org/html/2505.10696 (878 traj / 63 env / 1.44 M samples) and https://arxiv.org/abs/2505.10696 (updated: 910 traj / 70 env / 1.5 M samples).
- Unreal Engine 4 + AirSim; 6 stereo RGB pairs (360°), depth, semantics, LiDAR, optical flow, IMU, semantic occupancy; 10 Hz; ~15 TB; 17.3 M RGB images.
- Motion patterns: 440 omni-wheeled, 198 diff-drive, 240 legged (ANYmal D in Gazebo, with proprioception, joint states, contact forces).
- Baselines: SurroundOcc occupancy IoU 12.91–22.15 (urban) vs 6.39–16.97 (natural); SLAM rel. trans. error ORB-SLAM3 0.152–0.563 m/frame, DPVO 0.010–0.089, MAC-VO 0.008–0.016.
- License CC BY-NC-SA 4.0. Not a VLN dataset — no language — but the only large legged-motion-pattern outdoor perception set.

---

## 2. Video-LLM navigation policies (the Model-A lineage)

### 2.1 NaVid (Zhang et al., RSS 2024)
- Fetched: https://arxiv.org/html/2402.15852v6 ; repo https://github.com/jzhzhang/NaVid-VLN-CE (MIT)
- Vicuna-7B + EVA-CLIP + Q-Former. Current frame: 64 instruction-agnostic + 1 instruction-queried token; each history frame: 4 + 1 tokens; `<HIS>`, `<OBS>`, `<NAV>` delimiters.
- Output: `{FORWARD, TURN-LEFT, TURN-RIGHT, STOP}` with distance / degrees as text, regex-parsed.
- Data: 510k navigation samples (320k oracle R2R + 180k DAgger) + 10k instruction-reasoning + 763k web video-caption; 672 A100 GPU-hours.
- "The agent requires about 1.2 to 1.5 seconds to output one action per frame."
- R2R-CE val-unseen: SR 37.4 / SPL 35.9 / NE 5.47 / OS 49.1 (paper); repo README (later weights): SR 41.9 / SPL 36.5 / NE 5.65; RxR-CE cross-dataset 23.8 SR (paper); repo 45.7 SR (trained on RxR).
- Real: Turtlebot4 + Kinect DK, 4 scenes, 200 instructions: ~66% simple, ~42% complex.

### 2.2 Uni-NaVid (Zhang et al., RSS 2025)
- Fetched: https://arxiv.org/html/2412.06224v2 ; https://pku-epic.github.io/Uni-NaVid/ ; https://github.com/jzhzhang/Uni-NaVid (MIT; weights `uninavid-7b-full-224-video-fps-1-grid-2` on HF)
- Vicuna-7B + EVA-CLIP; video at 1 FPS.
- Online token merge: current frame 64 tokens (α_curr=2), short-term (last 64 frames) 4 tokens (α_short=8), long-term 1 token (α_long=16), merge threshold τ=0.95.
- Actions: `{FORWARD 25 cm, TURN 30°, STOP}`; "predicts 4 future actions per inference step"; "approximately 0.2 seconds to generate the next four actions" on a remote A100; "about 5 Hz model inference".
- Data: 3.6 M navigation samples — VLN-CE R2R+RxR 2.4 M, ObjectNav (HM3D) 483k, EQA 250k, human following 544k — plus 2.3 M VQA; 40 H800 x 35 h = 1400 GPU-h.
- R2R-CE val-unseen: SR 47.0 / SPL 42.7 / NE 5.58 / OS 53.3 (paper); README: SR 51.8 / SPL 47.7 / NE 4.96 / OS 57.4. RxR-CE: 48.7 / 40.9 (paper); README 56.1 / 44.5. ObjectNav HM3D SR 73.7 / SPL 37.1; EQA 54.4%; **human following SR 61.21, following rate 71.93**.
- Real-robot platform not named in main text (supplementary).

### 2.3 NaVILA (Cheng et al., RSS 2025) — legged, Go2
- Fetched: https://arxiv.org/html/2412.04453v1 ; https://github.com/AnjieCheng/NaVILA (Apache-2.0 code; checkpoints `a8cheng/navila-llama3-8b-8f`, `navila-siglip-llama3-8b-v1.5-pretrain`; a `navila-qwen2-7b-64k-64f` also listed); HF card https://huggingface.co/a8cheng/navila-llama3-8b-8f has no model card / no license field.
- Two-level: VLA emits mid-level language ("move forward 75cm", "turn right 30 degrees"), regex-parsed, then "casts...to fixed command velocities {0.5 m/s, π/6 rad/s, -π/6 rad/s, 0}" with durations; low-level PPO policy trained in Isaac Lab at 50 Hz from proprioception + LiDAR height map ("over 60K FPS on an RTX 4090").
- History: latest frame + uniformly sampled preceding frames, first frame always kept; 8–64 frames tested, real world uses 8.
- Latency: "wait time between each action is about 1 second" = image transmission Go2 -> server + "approximately 0.6 seconds per sample"; W4A16 quantization 594.58 -> 367.80 ms.
- Data: R2R-CE, RxR-CE, EnvDrop, ScanQA, VQA, plus "2K egocentric touring videos" from YouTube -> "20K trajectories".
- R2R-CE val-unseen SR 54.0 / SPL 49.0 / NE 5.22; RxR-CE zero-shot 34.3 / 28.2.
- VLN-CE-Isaac (1,077 of 1,839 R2R val-unseen trajectories with good meshes): Go2 vision 50.2 SR vs blind 36.2; H1 45.3 vs 24.4.
- Real: 25 instructions x 3 trials across Workspace / Home / Outdoor: 88% overall, 75% complex. Go2, H1, G1 with the same VLA.

### 2.4 StreamVLN (Wei et al., ICRA 2026) — the streaming reference design
- Fetched: https://arxiv.org/html/2507.05240v2 ; https://github.com/InternRobotics/StreamVLN ; https://huggingface.co/mengwei0427/StreamVLN_Video_qwen_1_5_r2r_rxr_envdrop_scalevln
- Base: "LLaVA-Video 7B model, which uses Qwen2-7B as the language model" (HF card: "8B params", BF16). Interleaved vision-language-action as multi-turn dialogue over a continuous video stream; 4 actions per turn.
- Memory: "sliding window KV cache over continuous dialogues, retaining a fixed number N of recent dialogues" — "retaining 8 continuous dialogue turns achieves the best balance"; slow memory context 8 frames x 196 tokens; "voxel-based 3D spatial pruning strategy" back-projecting patches with depth: visual tokens cut 32% (R2R) / 30% (RxR), overall 28% / 22%.
- Data: 450K samples from 60 MP3D envs (R2R/EnvDrop/RxR) + 300K ScaleVLN (700 HM3D scenes) + 240K DAgger + 248K video VQA + 230K MMC4; ~1500 A100 GPU-hours. Trajectory data on HF (`cywan/StreamVLN-Trajectory-Data`).
- R2R-CE val-unseen (with extra data): SR 56.4 / SPL 50.2 / NE 4.90 / OS 63.6; with pruning+memory 57.4 / 51.1 / 4.73. RxR-CE: README NE 5.65 / SR 54.4 / SPL 45.4 / nDTW 63.7 (the HTML extraction of the RxR SR column read 45.4, which is the SPL; README value used). Abstract (v1) quotes 56.9 SR / 51.9 SPL.
- Deployment: "Unitree Go2 robotic dog" + "upward facing camera (Intel RealSense D455)"; "remote workstation with an RTX 4090 GPU"; "averge inference (0.27s for 4 actions) and communication (0.2s for indoor and 1.0s for outdoor environments) latency". 20 trials per scenario (hallway / bedroom / office) vs CMA, NaVid, NaVILA; StreamVLN best in all, NaVILA fails the office; exact per-scenario SR only in Fig. 5. Mall/outdoor qualitative.
- Weights: CC BY-NC-SA 4.0; two checkpoints (benchmark and "real_world" with better obstacle avoidance).

### 2.5 DualVLN / InternVLA-N1 ("Ground Slow, Move Fast", Dec 2025)
- Fetched: https://arxiv.org/html/2512.08186 ; https://huggingface.co/InternRobotics/InternVLA-N1-DualVLN ; https://huggingface.co/InternRobotics/InternVLA-N1
- System 2: Qwen2.5-VL 7B (HF card: 8B BF16) predicts pixel goal + view adjustment at **2 Hz**; System 1: Diffusion Transformer (hidden 384, 12 layers, 6 heads) conditioned on high-rate RGB + 4 learnable latent query tokens from frozen Qwen hidden states, outputs **32-waypoint trajectories at 30 Hz**, "within 0.03s using TensorRT"; asynchronous, "allowing dynamic obstacle avoidance".
- Data: StreamVLN recipe for S2 (one epoch); S1 competitive with "only 1% of the trajectories"; Social-VLN 763K episodes / 60 MP3D scenes; InternData-N1 (simulation only).
- R2R-CE val-unseen SR 64.3 / SPL 58.5 / NE 4.05 / OS 70.7; RxR-CE SR 61.4 / NE 4.58 / nDTW 70.0; VLN-PE zero-shot SR 51.60 / SPL 42.49.
- Real: Turtlebot4, Unitree Go2, Unitree G1; 20 trials per scenario per model (hallway/bedroom/office); "20GB memory" on a remote RTX 4090; S2 latency 1.1 s -> 0.7 s with KV-cache.
- License CC BY-NC-SA 4.0 (weights); code InternNav.

### 2.6 Robostral Navigate (2026)
- Fetched: https://arxiv.org/html/2607.20785v3
- 8B VLM (from a spatial-grounding VLM) at 0.5 Hz emitting pixel waypoint (u,v) + Δθ (metric fallback when out of view) + 121M diffusion policy at 10 Hz -> 100 Hz commands; frame history for progress tracking; online RL (CISPO) for exploration/recovery.
- "We generate 2.4 million trajectories across 350k simulated scenes"; sim-only; prefix caching "reducing training tokens by 22x".
- R2R-CE val-unseen SR 77.4 / SPL 74.2 ("surpassing the best monocular method by 10.5 points"); RxR-CE 75.1 / 68.7. Robots: Galaxea R1, Hiwonder JetAuto, same weights. Open weights not stated.

### 2.7 "What Limits Vision-and-Language Navigation?" / StereoNav (2026)
- Fetched: https://arxiv.org/html/2605.13328
- Analyses StreamVLN, JanusVLN, NaVid, Uni-NaVid, NaVILA, InternVLA-N1, NaVid-4D, Dynam3D, NavFoM, ABot-N0.
- "SR plummets from 57.0% to 35.3% under motion blur, and further to 20.1% under viewpoint oscillation" (LLaVA-based); Qwen-based "SPL drops from 56.8% to a mere 4.2% under motion blur".
- Failed episodes have directional-ambiguity score 51.7 vs 77.3 for successes.
- "the correlation between training data scale and success remains surprisingly weak."
- StereoNav: R2R-CE SR 81.1 / SPL 68.3; real 4-scenario macro SR 60.6% vs StreamVLN 24.3%; oscillation degradation 37.0% vs StreamVLN 64.7%.

### 2.8 VLN-Cache (2026) — KV reuse for VLN VLAs
- Fetched: https://arxiv.org/html/2603.07080
- Applied to InternVLA-N1 (7B, Qwen2.5-VL); training-free; depth-guided geometric remapping of tokens between frames + instruction-conditioned semantic-change detection; splices fresh KV only for refreshed tokens.
- A100-40GB BF16, R2R-CE val (1,839 episodes): per-step 637 -> 419 ms (1.52x), ~31% token reuse, 12.3 GFLOPs saved (18.3% of attention), SR 64.3 -> 63.1, SPL 58.5 -> 57.6; ~11.2 MB per frame cache. Needs depth + relative pose.

---

## 3. Runtime / latency work: what "streaming" actually buys

### 3.1 LiveVLN — "Breaking the Stop-and-Go Loop" (2026)
- Fetched: https://arxiv.org/html/2604.19536 ; https://github.com/NIneeeeeem/LiveVLN
- Diagnosis on a Unitree G1 with StreamVLN / NaVILA-class navigators: "Average waiting is 10.64 s per episode, corresponding to a 30.5% waiting ratio"; "94.9% of rounds are stop-and-go"; visible gap 1.09 s.
- Fix: guarded handoff with revisable tail — executed actions / guard buffer (committed, sized from an exponential average of sense+inference latency + margin δ) / revisable tail; next inference conditioned on the committed guard, so refresh is asynchronous. No retraining.
- Metrics introduced: waiting ratio η_wait, visible gap ℓ_gap, N_pause (>0.5 s), interrupted-round duration.
- Sim: StreamVLN+Live R2R SR 57.2 (vs 56.4), RxR 53.7; NaVILA+Live 59.9 (vs 61.4).
- Real G1 (D455f, RTX 5090, Wi-Fi <50 ms jitter): StreamVLN waiting 7.32 -> 1.63 s (-77.7%), pauses 6.75 -> 0.80, episode 41.98 -> 36.71 s, gap 0.96 -> 0.11 s; NaVILA waiting 10.64 -> 2.89 s, gap 1.09 -> 0.16 s.

### 3.2 TIC-VLA — Think-in-Control (2026), Go2, edge compute
- Fetched: https://arxiv.org/html/2602.02459v2
- InternVL3-1B (InternViT-300M + Qwen2.5-0.5B) + 6-layer cross-attention action expert; "action policy running at 10 Hz and asynchronous VLM reasoning running at 0.5 Hz"; latency Δt = t_infer + t_elapse modelled explicitly; actions 30 chunks of (dx, dy, dθ) over 3 s.
- Training: ~25 h (SCAND 8.7 h, GND 11 h, DynaNav sim 5.1 h); stage 2 "Imitation Learning under Reasoning Latency" with delays "uniformly from [0,10] seconds"; stage 3 PPO.
- DynaNav: SR 55.29 / CR 28.24 (no RL: 47.06 / 34.12); NavDP with privileged goal 54.12 / 30.59.
- Real Unitree Go2, 4 tasks: 0.85 SR on RTX 4060 laptop ("85.73 / 3430.73 ms" action / reasoning); **0.75 SR on Jetson Orin NX ("120.27 / 4831.73 ms")**; DualVLN 0.50, NaVILA 0.35 on the same tasks.

### 3.3 Slow Brain, Fast Planner (2026) — latency-resilient fusion
- Fetched: https://arxiv.org/html/2606.20458
- 5–20 Hz local planner (S2E, 64 anchors -> top-K=18, ~4 s horizon) + cloud VLM at "1–3s per query" (Gemini 2.5 Flash Lite median 1.7 s; Gemini 3 Flash 8.1 s; 4G real-world 1.5–3.0 s), streamed at 1 Hz non-blocking with pipelined requests.
- Score fusion with decay w(Δt)=exp(-Δt/τ_decay), τ 3–5 s; "Score Fusion holds above 80% out to 5 s", "VLM Hold collapses past 2 s".
- Real sidewalk robot: takeovers 3.49 -> 0.87 per 100 m (-75%); longest autonomous segment 111.7 m. Dataset ~5,000 snapshots (3,000 normal / 2,000 hard).

### 3.4 Real-world VLN via Online Visual-Language Mapping (2023)
- Fetched: https://arxiv.org/html/2310.10822
- GPT-3.5 parses instructions into macro-actions; online VLMaps (LSeg + CLIP) at 5 cm grid; DBSCAN landmark localiser; DD-PPO local controller; LoCoBot WX250 + D435 at 53 cm height. Landmark tasks 95% (vs CM2 30%), complex instruction 100% (5 runs). CC BY-NC-ND 4.0.

---

## 4. Long-context and zero-shot LLM navigators (the Model-B lineage)

### 4.1 Mobility VLA (Google DeepMind, CoRL 2024)
- Fetched: https://arxiv.org/html/2407.07775
- Gemini 1.5 Pro "1M token context-length"; demonstration tour "roughly 16 minutes long (948 frames @ 1Hz)"; phone tour "75 seconds long and contains 224 frames (3 Hz)"; COLMAP poses; edge if target "in front of" and "within 2m".
- Low-level: waypoint (Δx, Δy, Δθ) to MPC, "0.19±0.047s" per step vs VLM "10-30s" per goal call.
- 836 m² office, 57 instructions: RF 80%, RR 80%, SO 40%, MM 85%; 900 sim trials 90%. Closed model.

### 4.2 VLMnav (Goetting, Singh, Loquercio, 2024)
- Fetched: https://arxiv.org/html/2411.05755
- Gemini Flash zero-shot; candidate arrows numbered on the image, navigability from depth, r_i <- min(2/3 r_i, r_max); 2-D voxel map of explored area; 131° FOV camera at 25° pitch.
- HM3D ObjectNav SR 50.4 / SPL 0.210 (PIVOT 24.6 / 0.106; prompt-only 29.8); GOAT 16.3 / 0.066. Without sliding, SR drops 12.9 points. Sim only. Paper CC BY 4.0, code released.

### 4.3 NavGPT (AAAI 2024), DiscussNav (ICRA 2024), MapGPT (ACL 2024)
- Fetched: https://arxiv.org/html/2305.16986v3 ; https://ar5iv.labs.arxiv.org/html/2309.11382 ; https://arxiv.org/html/2401.07314v2
- NavGPT: BLIP-2 ViT-G FlanT5XL captions of 24 views + Faster R-CNN objects within 3 m; GPT-3.5 history summariser; R2R val-unseen (nav-graph) SR 34 / SPL 29 / OSR 42 / NE 6.46 / TL 11.45 vs trained ~66 SR.
- DiscussNav: GPT-4 experts (decomposition, landmarks, completion estimation, decision testing), ChatGPT summariser, InstructBLIP scene expert, RAM-14M objects; SR 43 / SPL 40 / OSR 61 / NE 5.32; real Turtlebot4 Lite + OAK-D Lite, 20 instructions: 25% (NavGPT 10%, DUET 0%).
- MapGPT: online linguistic topological map (explored / accessible / unexplored-inaccessible nodes) + adaptive multi-step plan; GPT-4V SR 43.7 / SPL 34.8 / OSR 57.6 / NE 5.63 on 783 val-unseen; REVERIE (500) SR 31.6; "672 input tokens and 115 output tokens per step" vs NavGPT "2,465 input tokens and 317 output tokens". Simulator only.

---

## 5. Quadruped VLAs and skill-conditioning

### 5.1 QUAR-VLA / QUART (ECCV 2024) and QUART-Online (2024)
- Fetched: https://arxiv.org/html/2312.14457 ; https://arxiv.org/html/2412.15576
- QUART: Fuyu-8B (LLaVA-7B variant tested); single RGB + text -> "12-dimensional action tokens": vx, vy, ωz, gait (θ1..θ3), frequency f, height hy, pitch φ, foot width sy, foot height hzf, termination; 256 bins; **2 Hz**.
- QUARD: 259K sim + 3K real episodes; sim SR: distinguish 66%, go-to 60%, obstacle avoid 53%, tunnel 41%, crawl 32%, unload 12%; real 13/20 with 256K:3K mix; WR-2 quadruped (12 joints, ~25 cm tall) + D435.
- QUART-Online: Action Chunk Discretization (codebook 512, chunks 1/5/10) -> **50 Hz in sync with the controller** (from 2 Hz); QUART 0.37 -> QUART-Online-10 0.68 average on unseen visuals; 0.99 on "Go to" unseen language; Isaac Gym.

### 5.2 LOVON (2025) — Go2 / B2 / H1-2
- Fetched: https://arxiv.org/html/2507.06747 ; https://github.com/DaojiePENG/LOVON (MIT; L2MM + IOE weights released)
- DeepSeek-R1 as planner; YOLO-11 open-vocab detector; L2MM transformer (d=256, 4 layers, 8 heads, ff 1024; 3.30 M params) trained on 1 M generated samples (~1 h on RTX 3080 Ti) mapping language + detection state -> [vx, vy, θ]; Laplacian blur threshold T_blur=150 (+15% qualified frames); 5-state execution logic (new mission / run to object / search lost object / maintain / accomplish).
- Gym-Unreal SR 1.00 across ParkingLot / UrbanCity / SnowVillage; real demos only qualitative. RealSense D435i default.

### 5.3 LocoVLM (Feb 2026)
- Fetched: https://arxiv.org/html/2602.10399
- GPT-4o synthesises 300 motion descriptors (gait period T, 4-D phase offsets, max velocity); BLIP-2 encoder grounds camera+text online on a laptop RTX 3070 Ti ("less than 100 ms"); style-conditioned PPO policy (Isaac Gym) at 50 Hz on Jetson Xavier NX, motors 200 Hz; Unitree Go1; retrieval accuracy 72/100 (text) -> 87/100 (text rendered as image). CC BY-NC-ND 4.0.

### 5.4 UrbanVLA (Oct 2025) — Go2 outdoors
- Fetched: https://arxiv.org/html/2510.23576
- Qwen2 backbone; four RGB cameras on a Unitree Go2; "The system operates at 2 Hz"; route resampled to 20 waypoints over D=40 m at d=2 m; outputs SE(2) waypoint trajectory.
- Data: MetaUrban "2,400 episodes (approximately 40 hours)" + "roughly 8 hours of real-world demonstrations" + Sekai web video; 8 H100 x 12 h.
- MetaUrban SocialNav SR 91% test / 88% unseen; real routes ">500 meters" (overpasses, crossings) qualitative; remote RTX 4090 via Web-ADK. CC BY 4.0.

---

## 6. What this means for Parcel's Model A / Model B

### 6.1 The field has converged on a two-rate split; no single model is both "fully duplex" and fast
- Every 2025–26 system that runs on a real legged robot separates a slow language model (0.5–2 Hz: DualVLN S2 2 Hz, Robostral 0.5 Hz, TIC-VLA 0.5 Hz, StreamVLN ~3.7 Hz per 4-action turn) from a fast motion generator (10–50 Hz: DualVLN DiT 30 Hz, Robostral diffusion 10 Hz, TIC-VLA 10 Hz, NaVILA/LocoVLM RL policies 50 Hz). Parcel's existing 10 Hz duplex frame clock is exactly the fast-lane rate; **Model A should be the slow lane (1–4 Hz) that writes a goal/latent into the 10 Hz act-token loop, not the 10 Hz loop itself.**
- The Go2-specific numbers say on-robot compute is the constraint: StreamVLN/DualVLN/NaVILA/UrbanVLA all run on a remote RTX 4090 (DualVLN needs 20 GB); the only Go2 result on Jetson-class hardware is TIC-VLA's 1B model at 0.75 SR with 4.8 s reasoning latency on an Orin NX. An AGX Orin 64 GB can hold a 7–8B BF16 model (~16 GB) but the cited 0.27–1.1 s per inference are 4090 numbers — budget 2–4x slower on Orin unless quantized (NaVILA W4A16: 595 -> 368 ms on server GPU).

### 6.2 "Streaming" needs a runtime contract, not just a streaming model
- LiveVLN measured StreamVLN-class navigators at 30.5% idle time and 94.9% stop-and-go rounds on a real Unitree robot even though the model is "streaming". The fix is a committed guard buffer sized to measured sense+inference latency, with a revisable tail; it preserved SR (56.4 -> 57.2) and cut waiting 77.7%.
- Parcel's act-token codec should therefore carry (a) a committed prefix the executive will not revoke, (b) a revisable tail Model A may overwrite, and (c) the timing metrics LiveVLN defines (waiting ratio, visible gap, pause count) as first-class eval rows next to SR/SPL.
- Slow-Brain/Fast-Planner shows the fusion rule for stale slow-lane output: decay its weight with exp(-Δt/τ), τ 3–5 s, and keep the fast lane authoritative; success held >80% out to 5 s of VLM latency. This is directly the "Model B keeps / revises / queues the plan" arbitration, expressed as a staleness weight.

### 6.3 Memory: sliding-window KV + compressed long-term tokens is the proven recipe; maps still matter for multi-instruction sessions
- StreamVLN: 8-turn sliding-window KV cache + 8x196-token slow memory + depth-voxel token pruning (-28–32% tokens). Uni-NaVid: 64 / 4 / 1 tokens for current / last-64-frames / older. VLN-Cache: geometric KV reuse gives 1.52x per-step speedup at -1.2 SR. These are the mechanisms for the "last 1 minute" stream in the owner's spec.
- For "global history" (a session of many commands), IVLN found that implicit transformer memory does not carry across episodes (t-nDTW 61 -> 45) while map-building agents benefit. Parcel already has a LiDAR occupancy grid + semantic grounding; keep it as the persistent store and feed Model A a compact map/plan-queue token rather than trying to hold hours of video in context. Mobility VLA's 1M-token tour approach works but at 10–30 s per call (closed model) — not a live-lane option.

### 6.4 The representation the hosted voice narrates from already exists in the literature: NaVILA's mid-level language actions
- NaVILA emits "move forward 75cm / turn right 30 degrees" as text, which is then cast to velocities for a 50 Hz RL policy, and got 88% on 25 real Go2 instructions. That text stream is precisely a narratable representation ("I'm turning right toward the sofa"). Model A's output head can be a small discrete/mid-level action vocabulary (NaVid/Uni-NaVid: forward 25 cm / turn 30° / stop; DualVLN: pixel goal + latent) plus a short natural-language status line; Model B then rewrites that line for the hosted voice.
- Uni-NaVid shows one 7B video-LLM can carry VLN + ObjectNav + EQA + human following (61.2 SR following) with unified action tokens — the same task set a companion dog needs (follow me / go check X / answer what you see). Training samples were 3.6 M navigation + 2.3 M VQA at 1400 GPU-h.

### 6.5 Sim-to-real for a Go2 is dominated by camera height, lighting and controller mismatch — not data scale
- VLN-PE: NaVid zero-shot 22.4 SR humanoid -> 4.7 on a ~0.5 m quadruped; RGB-only models lose ~12 SR points under low light while RGB-D lose ~2–3; training with the same locomotion controller as deployment is best; mixing embodiments adds +8 SR; 14 real Go2 episodes went 7.1 -> 28.6 SR after fine-tuning on physics-sim data. "What Limits VLN?" adds motion blur (57.0 -> 35.3 SR) and viewpoint oscillation (-> 20.1) — a walking dog produces both — and finds data scale weakly correlated with success.
- Implication: Parcel's MuJoCo city should render at the Go2 camera height with the actual gait (oscillation) and lighting variation, and Model A should consume depth/LiDAR alongside RGB. The existing kinematic "headless city" is fine for language/plan supervision but not for the visual policy.

### 6.6 Speech-movement coupling data
- No fetched benchmark couples live speech with continuous motion; CVDN is dialog-history-conditioned (2050 dialogs, goal progress 2.10 m vs 9.58 m oracle) and RxR has word-level pose traces (126k instructions). Parcel will have to synthesise its own interleaved (speech-turn, act-token, state-digest) traces in sim; RxR pose traces are the closest existing supervision format to copy.

### 6.7 Licensing map for building on open weights
- Commercial-friendly: NaVid / Uni-NaVid code MIT (weights on HF, base Vicuna-7B); LOVON MIT; NaVILA code Apache-2.0 (weights card has no license field); VLN-CE code MIT. Non-commercial: StreamVLN weights, InternVLA-N1 weights, TartanGround (CC BY-NC-SA 4.0); LocoVLM CC BY-NC-ND. Datasets: R2R-CE CC BY-NC-SA 3.0 + Matterport ToU; RxR annotations CC-BY 4.0. Closed: Mobility VLA (Gemini 1.5 Pro), VLMnav's Gemini Flash, MapGPT/NavGPT (GPT-4).

---

## 7. Open questions
1. StreamVLN / DualVLN per-scenario real-world SR values live only in figures (Fig. 5); need to read the PDF figure or the InternNav repo eval logs to get numbers for the Go2 hallway/bedroom/office trials.
2. VLN-CE success threshold: the ar5iv extraction mentions a 0.5 m threshold in the trajectory-transfer context; confirm the evaluation success radius from the PDF before pinning eval rows to it.
3. Uni-NaVid's real-robot platform is in the supplementary (not fetched); confirm whether a quadruped was used for the human-following demo.
4. NaVILA weight license: GitHub shows Apache-2.0 for code; the HF card has no license field. Ask the authors before commercial use.
5. Orin AGX 64 GB latency for a 7–8B video-LLM at StreamVLN token counts (8 turns x 4 actions, 196 tokens/frame) has no published number; only the Orin NX 1B (TIC-VLA) datapoint exists.
6. Robostral Navigate's 2.4 M trajectories / 350k scenes sim-only recipe and 77.4 SR: whether the weights are released under Mistral's terms is not stated in the paper.
7. No benchmark yet scores mid-task interruption/amendment with a live human; LiveVLN's timing metrics plus IVLN's tour format are the nearest building blocks.
