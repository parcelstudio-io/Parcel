# Gap note — discrete behavior tokenization from continuous demonstrations for a 50 Hz body lane

Date: 2026-08-28. Author: research subagent (Fable). Scope: how to turn continuous
body-motion demonstrations (joint targets / body-pose commands at 50 Hz) into a small
discrete token stream that a full-duplex behavior model can emit on the same clock as
speech, and whether such codes are decodable by a tracking policy on a Unitree Go2.

Every source below was fetched and read during this session (arXiv HTML/ar5iv/PDF,
GitHub, project pages). Numbers are quoted from the fetched text; "—" means the fetched
text did not state it. Companion notes from the earlier sweep:
`vla-action-tokens.md` (FAST/pi0/QUART/QuadFM/Uni-Mo at the VLA level) and
`language-affect-to-motion.md` (clip-library + tracker plan). This note goes one level
down: the tokenizer itself.

---

## 0. One-paragraph answer

Nobody who succeeds emits one token per 50 Hz frame. Every working system compresses
time first — FAST packs a 1 s, 50 Hz, 14-D chunk into ~53 BPE tokens and shows that
per-frame binning at 20-50 Hz collapses ("the model simply copies the first action");
VQ-BeT emits one residual-VQ token per 5-step chunk with codebooks of only 8-16 per
layer (Nq=2) and finds larger codebooks do not help; MotionGlot, X-Tokenizer, MoReFlow
and the human-motion tokenizer literature all converge on **4 frames per token**;
QUART-Online drives a real 50 Hz quadruped controller from a 5 Hz MLLM by VQ-encoding
10-step command chunks (512 codes × 2 residual layers) and gains +65 % success. On the
Go2 specifically, the latent→tracker route is proven with *continuous* latents
(QuadFM/Gen2Control: 2 Hz generator → 50 Hz tracker, <500 ms on an Orin; Uni-Mo:
96.7 % real success over 392 motions), and a *discrete* codebook decoded by a 50 Hz
tracking policy is proven on other quadrupeds (Tencent VQ-PMC, K=256 × 32-D, on the
MAX robot; QUART-Online on a real quadruped). No paper yet decodes a discrete codebook
through a tracker on a Go2 — that is a build task, not an open research question, and
the pieces (Go2 clip datasets under CC BY 4.0, PPO trackers that train overnight on
one GPU, RVQ tokenizers with 20k-step training) are all public.

---

## 1. Source-by-source record

### 1.1 BeT — Behavior Transformers: Cloning k modes with one stone (Shafiullah et al., 2022)
- URLs: https://arxiv.org/abs/2206.11251 ; https://ar5iv.labs.arxiv.org/html/2206.11251 ; code https://github.com/notmahi/bet
- Tokenization: k-means over actions + continuous offset. "a categorical variable
  representing the closest action bin, ⌊a⌋:=argmin_i‖a−A_i‖_2, and a continuous residual
  action ⟨a⟩:=a−A⌊a⌋" ; reconstruction "a:=A⌊a⌋+⟨a⟩".
- k per environment: Point-mass k=2/3; CARLA k=32; Block-push k=24; Franka Kitchen k=64.
  Context windows: 2 / 10 / 5 / 10 steps. Model size ~1e4 (simple) to ~1e6 params (Kitchen).
- Results: CARLA driving 0.98 success; Block-push 2 blocks 0.71 vs 0 for most baselines
  (1 block 0.96 vs IBC 0.98); Kitchen sequence entropy 2.47 vs 2.96 in the demos.
- License: paper CC BY 4.0; code MIT-style (repo).
- Relevance: the ancestor of the "discrete mode + continuous residual" pattern. k-means
  is single-step and, per VQ-BeT, "does not scale to high-dimensional action spaces or
  temporally extended actions".

### 1.2 VQ-BeT — Behavior Generation with Latent Actions (Lee et al., ICML 2024 Spotlight)
- URLs: https://arxiv.org/abs/2403.03181 ; https://arxiv.org/html/2403.03181v2 ;
  https://sjlee.cc/vq-bet ; code https://github.com/jayLEE0301/vq_bet_official (MIT) ;
  LeRobot port https://raw.githubusercontent.com/huggingface/lerobot/main/src/lerobot/policies/vqbet/configuration_vqbet.py
- Tokenizer: residual VQ, "Nq:=2" layers; per-layer codebook 8-16 in the main results
  (64-256 code combinations); VQ-VAE latent 512-D (256-D for BlockPush). "primary codes
  ... perform coarse clustering ... while secondary codes handle fine-grained actions."
  A continuous offset head ζ_offset restores "full fidelity"; ablation says the offset head
  is "quite important for VQ-BeT" and removing residual VQ has a "significant negative impact".
- Windows (Table 13): Kitchen obs 10 / pred 1 / goal 10; Ant obs 100 / pred 1; PushT obs 5 /
  pred 5; nuScenes obs 1 / pred 6; real robot obs 6 / pred 1. Transformer 6 layers, 6 heads,
  120-D.
- Results: PushT IoU 0.78 vs 0.74 Diffusion-T; Kitchen 3.66 goals vs 3.44; Multimodal Ant
  3.22 vs 2.90; conditional Kitchen 3.78 vs 3.47 (CFG-BESO), PushT 0.39 vs 0.25, Ant 1.72 vs
  0.92; real robot 47/50 single-phase (DP 45/50), 19/30 two-phase (DP 11/30) = "73 %"
  relative gain; nuScenes L2 0.73 m vs 0.84, collision 0.29 % vs 0.44 %.
- Speed: 15.1 ms/step vs 100.5 ms Diffusion-C ("5× speedup in simulation and 25× on
  real-world robots"); on a robot CPU 207.25 ms vs 5,243.82 ms.
- Codebook-size ablation (Table 12): combinations 100 → 1,024 → 4,096 → 65,536; Ant 3.22 →
  3.01 (32-size) → 3.11 (deadcode mask); Kitchen 3.66 → 3.75 → 3.7 — "minimal performance
  change".
- Data: Kitchen 566 human demos; PushT 206; BlockPush 1,000 trajectories; nuScenes 684 scenes;
  real robot 45 demos/task.
- LeRobot defaults (fetched config): n_obs_steps 5; n_action_pred_token 3; action_chunk_size 5;
  vqvae_n_embed 16 ("Number of embedding vectors in the RVQ dictionary (each layer)");
  vqvae_embedding_dim 256; vqvae_enc_hidden_dim 128; n_vqvae_training_steps 20000; GPT 8
  layers / 8 heads / 512; offset_loss_weight 10000; primary_code_loss_weight 5.0;
  secondary_code_loss_weight 0.5; bet_softmax_temperature 0.1; sequentially_select False.
- Licenses: paper CC BY 4.0; official code MIT; LeRobot Apache-2.0.
- Relevance: the reference design for "tiny RVQ codebook + offset head + transformer over
  codes". Its ablation is the strongest evidence that a body lane needs only 10^1-10^2 codes
  per layer.

### 1.3 ACT — Action Chunking with Transformers (Zhao et al., 2023)
- URLs: https://arxiv.org/abs/2304.13705 ; https://ar5iv.labs.arxiv.org/html/2304.13705
- "chunk size to be k: every k steps, the agent receives an observation, generates the next
  k actions"; k=100 at "control frequency of 50Hz" (2 s chunks). CVAE β=10; ~80M params
  (4 enc / 7 dec layers, 512-D, 8 heads). 50 demos/task ("10 minutes worth of
  demonstrations"), episodes 400-700 steps. Inference "around 0.01 seconds".
- Chunk-size ablation (Fig 6a): k=1 → 1 %, k=10 → ~15 %, k=100 → 44 %, k=200-400 slight
  decline. Real tasks: Slide Ziploc 86 %, Slot Battery 93 %, Open Cup 84 %, Put On Shoe 92 %;
  sim cube transfer 97 %.
- Relevance: not a discrete tokenizer, but the cleanest evidence that at 50 Hz a policy
  should commit to whole chunks (1-2 s) rather than single steps; temporal ensembling
  (w_i = exp(−m·i)) is the standard way to blend overlapping chunks without jerk.

### 1.4 FAST / FAST+ — Efficient Action Tokenization for VLA models (Pertsch et al., Jan 2025)
- URLs: https://arxiv.org/abs/2501.09747 ; https://arxiv.org/html/2501.09747v1 ;
  https://pi.website/research/fast
- DCT per dimension → scale-and-round (γ=10) → BPE (vocab 1024) over 1 s chunks.
  Table I tokens per 1 s chunk, naive → FAST: BridgeV2 5 Hz 7-D 35 → 20 (1.75×); DROID
  15 Hz 105 → 29 (3.6×); Table Bussing 20 Hz 140 → 28 (5.0×); **T-shirt folding 50 Hz 14-D
  700 → 53 (13.2×)**.
- Why per-frame binning fails: "policies trained with naïve tokenization are unable to
  make progress" on 20 Hz and 50 Hz tasks; "the model simply copies the first action"
  because "the marginal information approaches zero as the control frequency increases."
- FAST+: "1 million 1-second action chunks" from π0 data, ALOHA, DROID, Bridge V2, OpenX;
  5-50 Hz; 7-40-D; shipped as a HuggingFace AutoProcessor. Training "5x fewer GPU hours"
  than π0; autoregressive decode "approximately 750ms" per chunk (30-60 tokens) vs ~100 ms
  for diffusion π0.
- License CC BY 4.0.
- Relevance: (a) hard evidence against per-frame body tokens at 50 Hz; (b) a ready-made
  universal tokenizer, but at ~50 tokens/s for a 50 Hz 14-D stream it is far too dense to
  interleave with 12.5 Hz speech tokens, and its 750 ms decode breaks the joint clock.

### 1.5 VQ-VLA — scaling vector-quantized action tokenizers (Wang et al., ICCV 2025)
- URLs: https://arxiv.org/abs/2507.01016 ; https://arxiv.org/html/2507.01016 ;
  code https://github.com/xiaoxiao0406/VQ-VLA
- RVQ with 256 codes per layer (layer i tokens mapped to [256(i−1), 256i−1]); chunk K=5;
  Prismatic-7B / OpenVLA backbone; trained on "over 100 times more data" (OXE + LIBERO +
  ManiSkill; "one A100 GPU ... one week").
- Results: LIBERO-90 80.98 % vs OpenVLA 73.53 %; real short-horizon 23 % → 46.25 %; up to
  +30 % long-horizon; inference 11.84 Hz vs 4.16 Hz (compression ratio 5).
- License CC BY-NC-SA 4.0.
- Relevance: shows RVQ action tokenizers keep improving with sim data scale — Parcel can
  pretrain the body tokenizer on sim rollouts (Kine2Go / Quad-Imaginarium) rather than
  scarce real clips.

### 1.6 BEAST — B-spline encoded action sequence tokenizer (Zhou et al., NeurIPS 2025)
- URLs: https://arxiv.org/abs/2506.06072 ; https://arxiv.org/html/2506.06072v2 ;
  https://intuitive-robots.github.io/beast_website/
- 5-10 B-spline control points per 1 s chunk (ablated N=5/10/15/20), 256 bins, "4−8× fewer
  tokens than binning"; "requires no separate tokenizer training"; fixed-length tokens →
  parallel decoding "entire sequence in a single forward pass", 617.3 Hz throughput, 19 ms
  per chunk; reconstruction MSE 0.0004±0.0005 vs binning 0.0215±0.0216.
- Results: CALVIN ABC 99.8 % single-task; LIBERO-LONG 86.4 % vs π0-FAST 60.2 %; real robots
  76.57 % avg; BEAST-ACT 70 % vs vanilla ACT 49 %. Frequencies 20 / 35 / 60 Hz.
- License CC BY-NC-SA 4.0.
- Relevance: a training-free way to make a fixed number of body tokens per chunk; good
  fallback if a learned codebook collapses on a tiny clip library.

### 1.7 OmniSAT — Compact Action Token, Faster Autoregression (Oct 2025)
- URLs: https://arxiv.org/abs/2510.09667 ; https://arxiv.org/html/2510.09667
- B-spline (Tc=8 control points per DoF, degree 4) then RVQ with L=8 layers, codebooks
  position 256 / rotation 256 / gripper 64; BPE vocab 2048; chunk 30 frames @ 30 Hz.
- Compression 6.8× (OmniSAT-8) / 8.1× (OmniSAT-6) vs FAST 3.7× vs BEAST 4.6×; DROID MAE
  9.4e-4 vs BEAST 8.0e-2. LIBERO avg 93.4 %; real PlaceObj/ZipSeal/TubeRack 73/63/48 % vs
  BEAST 63/45/23 %. Converges at 2.5k steps (FAST 3.5k, BEAST 4k).
- License CC BY 4.0; code "will release".
- Relevance: the current best manipulation tokenizer combines a smooth parametric basis
  with a small RVQ — the same two-stage idea Parcel can apply to body-pose chunks.

### 1.8 X-Tokenizer — multimodal action tokenizer for VLA pretraining (Jun 2026)
- URL: https://arxiv.org/html/2606.14752v2
- Semantic Residual Quantization: "Q=4 levels and V=2048 codewords per level", compression
  r=4 (T=64 frames → 16 slots), D=26 channels, pretrained on "2.4M trajectories (2.0B action
  frames)" from 17 arm families; 12-layer 1024-D encoder/decoder.
- vs FAST: reconstruction ℓ1 +17 % worse (0.01693 vs 0.01446) but real tasks 85.9 % vs 75.7 %;
  RoboTwin long-horizon 69.25 % vs 61.0 %; noise-robust (WER 0.437 vs 0.899).
- License CC BY 4.0.
- Relevance: another vote for 4 frames/token and for "semantic first level, fidelity in
  residual levels" — the first RVQ level is trained with masked action modeling so it carries
  behavior meaning, which is exactly what a language-model body lane needs.

### 1.9 DuoCore-FS — asynchronous fast-slow VLA for whole-body manipulation (Dec 2025)
- URL: https://arxiv.org/html/2512.20188v1
- Slow system 1-3 Hz (3B VLM), fast system 25-30 Hz; action tokenizer "Residual Vector
  Quantization (RVQ)" with "codebook with a size of 1024"; chunk T=32; 25-DoF Astribot S1.
  32.3 Hz vs π0 12.5 Hz; in-dist 90 % vs 85 %; OOD 50 % vs 10 %; 1,780 demos (10.22 h).
- Relevance: production-grade confirmation of the two-rate split with RVQ tokens as the
  interface.

### 1.10 RDT2-VQ (Hugging Face model card)
- URL: https://huggingface.co/robotics-diffusion-transformer/RDT2-VQ
- RVQ tokenizer (separate repo `RVQActionTokenizer`), chunk 24 steps × 20-D (≈30 Hz, 0.8 s),
  Qwen2.5-VL-7B backbone, 10k+ h UMI data, Apache 2.0.
- Relevance: open-weight RVQ action-token pipeline; license-clean reference code.

### 1.11 QUART-Online — latency-free MLLM for quadruped learning (Tong et al., Dec 2024)
- URLs: https://arxiv.org/abs/2412.15576 ; https://arxiv.org/html/2412.15576 ;
  https://quart-online.github.io/ ; code https://github.com/yuan48/QUART-Online
- Action Chunk Discretization: VQ "codebook embedding layer with 512 dimensions and 512
  quantizers (Nq=2)" — i.e. K=512 codes per layer, 2 residual layers, D=512 — over chunks of
  1 / 5 / 10 steps of the 12-D command (11 high-level commands + terminate).
- Clock rule: "the action chunk length l_ac multiplied by the frequency of MLLM inference f_m
  matches the frequency of low-level control f_l" — chunk 10 × 5 Hz = 50 Hz.
- Results: unseen-visual avg 0.37 → 0.68, unseen-language 0.52 → 0.79 ("65 % improvement");
  per task Distinguish 0.90/0.99, Go-to 0.89/1.00, Go-avoid 0.58/0.80. Reconstruction at
  chunk 10: MAE 0.012, AKI 0.0008, PSNR 32.11, UQI 0.9999. Inference 2 Hz → 50 Hz.
  Isaac Gym; real quadruped demo on the project page; dataset on HF.
- License: arXiv non-exclusive; repo license not stated on the page.
- Relevance: the only quadruped paper that VQ-tokenizes a chunk and runs it through a 50 Hz
  controller. Its codes are *command-level* (velocities, gait, body pose), which is exactly
  the abstraction Parcel's tracker consumes.

### 1.12 MotionGlot — multi-embodied motion generation (Harithas & Sridhar, Oct 2024)
- URLs: https://arxiv.org/html/2410.16623 ; https://ivl.cs.brown.edu/research/motionglot.html ;
  code https://github.com/sudarshan-s-harithas/MotionGlot-A-Multi-Embodied-Motion-Generation-Model
- Per-embodiment VQ-VAE codebook "R^{128×512}" (128 codes × 512-D), temporal downsampling
  "l=4" (4 poses per token); GPT-2 small; QUAD-LOCO: >1,000 trajectories / 2.5 h on Boston
  Dynamics Spot, ~48,000 text-motion pairs after augmentation; trained on 8× A5000, ~20k steps.
- Quadruped text-to-motion: R-precision@1/2/3 0.18/0.35/0.48, diversity 3.74, BLEU@4 36.5;
  "31.2 % on average" better than adapted baselines; hardware demo mentioned, no tracker metrics.
- License CC BY 4.0 (paper); dataset "To be released Soon".
- Relevance: a 128-code, 12.5-token/s quadruped motion vocabulary is enough for a GPT to
  generate text-conditioned gaits — the size class Parcel should start from.

### 1.13 Lifelike Agility and Play in Quadrupedal Robots — VQ-PMC (Tencent, 2023; Nat. Mach. Intell. 2024)
- URLs: https://ar5iv.labs.arxiv.org/html/2308.15143 ;
  code+data https://github.com/Tencent-RoboticsX/lifelike-agility-and-play
- "Vector Quantized Primitive Motor Control (VQ-PMC)": K=256 codes, D=32, β=0.25; ~30 min +
  9 min Labrador mocap at 120 fps (~39 min total); "The PMC is queried at 50Hz and the control
  frequency of the PD controller is 500Hz." Three-level hierarchy (PMC → EPMC → SEPMC);
  primitive level 2 days on 2× V100; real MAX robot plays chase-tag (human-operated robot lost 0:2).
- Release: code, raw + retargeted mocap; "for research purpose only" (TF 1.15).
- Relevance: the earliest real-quadruped proof that a 256-entry discrete latent at 50 Hz
  decodes to lifelike dog motion through a learned low-level controller.

### 1.14 Walk Like Dogs — steerable imitation controllers from unlabeled motion (Jul 2025)
- URL: https://arxiv.org/html/2507.00677v2
- Unitree Go2; "13076 pose samples along with their left-right mirrored counterparts";
  kino-dynamic retargeting (IK scale α_z=0.81, α_fwd=0.6, α_side=0.6; MJPC iLQG, T=2.0 s,
  dt 0.01 s). Motion synthesis = hyperspherical VAE (vMF), **18-D continuous latent**,
  MoE decoder with 6 experts; modes Pace/Trot/Gallop emerge; PPO in IsaacLab, batch 4,096,
  lr 5e-4; "policy is queried at 50 Hz"; base-velocity RMSE 0.11 m; gait switching at
  1.8 / 1.2 / 0.7 m/s. Real Go2 qualitative only. Code/license not stated.
- Relevance: Go2-native pipeline whose latent is continuous; its emergent modes are the
  natural targets a VQ layer would snap to.

### 1.15 QuadFM + Gen2Control (Gao et al., Mar 2026)
- URLs: https://arxiv.org/html/2603.24021v1 ; https://github.com/GaoLii/QuadFM
- 11,784 clips, 20.27 h, 3.64M frames at 50 Hz, 35,352 descriptions (mocap 7,998 / video-gen
  1,392 / teleop 696 / artist 1,698). Generator = MotionGPT3-style motion VAE + diffusion
  (**continuous latent**, no codebook) at 2 Hz; tracker = 4-layer MLP (2048-1024-512-256) at
  50 Hz; Go2 X + Jetson Orin, "<500 ms" end-to-end; 20,000 PPO iterations. Tracking MJPE
  0.0712 rad, MBPE 0.0744 m; human ratings 7.58 stability / 7.98 text-alignment / 7.46
  smoothness / 7.40 naturalness (0-9). CC BY 4.0; dataset "will be released" (not yet).
- Relevance: proves latent → single universal tracker on Go2/Orin at our latency budget.

### 1.16 Uni-Mo / Quad-Imaginarium — expressive Go2 motion from video priors (Jun 2026)
- URLs: https://arxiv.org/html/2606.28237 ; https://github.com/GaoLii/Quad-Imaginarium.git
- 7,488 language-annotated motions, 18.5 h, 19-D state (root pos 3 + quat 4 + 12 joints)
  resampled to 50 Hz, clips 5-15 s (mean 8.9 s); 68.1 % retention through semantic (CLIP
  ≥0.85, 97.0 %) and geometric (70.2 %) gates. Trackers at 50 Hz: sim 97.6 % over all
  7,488; **real Go2 96.7 % over 392 motions × 5 trials**; MBPE 40.6 mm, MRPE 3.8 cm, MROE
  2.7°, MPJPE 3.4°. CC BY 4.0.
- Relevance: the largest CC BY 4.0 Go2-native expressive clip set — the obvious corpus to
  fit a Go2 body tokenizer on.

### 1.17 ABot-C0 — behavior foundations for quadruped robots (Jul 2026)
- URL: https://arxiv.org/html/2607.07370
- 16,074 trajectories / 22.43 h (mocap 7,998 / teleop 547 / artist 41 / video-gen 7,488);
  "reference-window VAE" with **32-D continuous latent**; flow policy (4-layer Transformer,
  5 ODE steps); "motor-command loop runs at 200 Hz, while the decision tick, locomotion
  inference, and motion-tracking inference run at 50 Hz"; seen 92.74 % / unseen 88.54 %
  success, MPJPE 12.38 / 14.79 mm; runs on "NVIDIA Jetson AGX Orin 64GB". CC BY-NC-ND 4.0.
- Relevance: same compute module as Parcel; confirms a 50 Hz tracking stack fits on the
  Orin with headroom, but the licence forbids derivative use.

### 1.18 Multi-Domain Motion Embedding — expressive real-time mimicry (Dec 2025)
- URL: https://arxiv.org/html/2512.07673
- ANYmal D + H1 + Fourier N1; 32-D variational latent + wavelet-entropy (db2) descriptor
  (continuous); dog data "approximately 10 minutes" → ~52 min after augmentation; 50 Hz;
  PPO IsaacLab; zero-shot real. CC BY 4.0.
- Relevance: shows how little dog data (10 min) suffices for a latent that a tracker can
  follow — codebook training data will not be the bottleneck.

### 1.19 DFM — Deep Fourier Mimic (Sony aibo, Feb 2025)
- URL: https://arxiv.org/html/2502.10980
- Fourier latent c=8 channels (frequency, amplitude, offset, phase → 24-D); 34 dances × 5
  frequency variants (0.5 / 0.75 / 1.0 / 1.25 / 1.5) = 170 clips × 6 s; 100 Hz control;
  PPO 3×256; MAE 0.094 rad vs 0.132 baseline. Code not released.
- Relevance: a concrete recipe for *intensity* as a tempo scalar (0.5-1.5×) rather than
  extra codes — useful for "chuckle a little / a lot".

### 1.20 AMOR — adaptive character control via multi-objective RL (Disney, SIGGRAPH 2025)
- URLs: https://arxiv.org/abs/2505.23708 ; https://arxiv.org/html/2505.23708
- 7 reward terms; policy conditioned on weight vector w ~ Δ^m sampled per episode; humanoid
  36-DoF, bipedal robot 20-DoF (no quadruped); 300k iterations ≈ 5 days on one RTX 4090
  (8,192 envs at 250 Hz); tuning weights post-hoc "approximately 1 day" vs 5-day retrain;
  raising the smoothness weight at runtime reduces jitter and "the sim-to-real gap".
- Relevance: "intensity"/style as a runtime conditioning vector on the tracker, orthogonal
  to the token stream.

### 1.21 LGPL — expressive quadruped behaviors via language-guided preference learning (Feb 2025)
- URL: https://arxiv.org/html/2502.03717v1
- Pupper v3; behavior = continuous 5-D vector (velocity, pitch, 3 gait primitives);
  "as few as four queries"; MSE 0.223 vs 0.455 (pref) vs 0.821 (LLM); preferred 75.83 % /
  76.67 %; Likert 5.46 vs 4.44; 11 + 5 users. CC BY 4.0.
- Relevance: shows how few human preference queries are needed when the behavior space is
  a handful of discrete/parametric knobs — the regime a small codebook keeps Parcel in.

### 1.22 MoReFlow — motion retargeting via unsupervised flow matching (Sep 2025)
- URL: https://arxiv.org/html/2509.25600v1
- Character-specific VQ-VAE: humanoids "nb_code: 512, code_dim: 512"; **Spot quadruped
  "nb_code: 256, code_dim: 256"**; "Temporal downsampling by a factor of 4 reduces each
  32-frame window to a short latent sequence of 8 tokens". Sim only. CC BY-NC-SA 4.0.
- Relevance: another quadruped VQ codebook at 256 with 4-frame tokens.

### 1.23 Beyond MoCap — scaling human motion tokenizers (Jun 2026)
- URL: https://arxiv.org/html/2606.27547
- VQ-VAE with K=512 baseline → K=2048 (ablated 1,024-32,768); "approximately 76 % of codes
  active" at 2048 after ~64× synthetic augmentation of HumanML3D (14,616 → ~936k sequences);
  l=4 downsampling; FID 0.132 → 0.076; downstream T2M-GPT FID 0.116 → 0.097. CC BY 4.0.
- Relevance: codebook utilization only reaches ~76 % even at ~1M sequences; a 30-100 clip
  dog library should stay at 10^2 codes or use FSQ/RVQ to avoid collapse.

### 1.24 Heracles — tracking + generative synthesis for humanoid control (Mar 2026)
- URL: https://arxiv.org/html/2603.27756
- Discrete motion embedding via improved FSQ (levels L=2^K+1); Unitree G1 (29 DoF); policy
  50 Hz, generative middleware 25 Hz; 16,384 envs on one A100; completion 90.6 % vs 84.8 %
  MLP; fall-recovery 90.0 % vs 44.0 %.
- Relevance: FSQ tokens feeding a 50 Hz tracker on a real Unitree platform — the same
  family of hardware/firmware as the Go2.

### 1.25 Humanoid-LLA — unified human-humanoid motion vocabulary (Nov 2025) and WholeBodyVLA (ICLR 2026)
- URLs: https://arxiv.org/html/2511.22963v2 ; https://humanoidlla.github.io/ ;
  https://arxiv.org/html/2512.11047v1 ; https://github.com/OpenDriveLab/WholebodyVLA
- Humanoid-LLA: cross-embodied VQ-VAE "unified codebook" (size not stated), 26,846 AMASS
  sequences; tokens executed by a CVAE "vocabulary-directed student policy"; sim success
  87.6 %, MPJPE 56.43 mm, FID 2.626, R-precision 0.447; G1 + Booster T1; CC BY 4.0; code
  "coming soon".
- WholeBodyVLA: VQ-VAE latent actions at ~10 Hz decoded to upper-body joints + a locomotion
  command for a 50 Hz RL controller; Agibot X2; 78.0 % vs 64.0 % modular.
- Relevance: the "LLM emits motion-vocabulary tokens → student/tracker executes at 50 Hz"
  pattern is now standard on humanoids.

### 1.26 Datasets: Kine2Go (Jun 2026) and T2QRM/DogML (ACM MM Asia 2024)
- Kine2Go https://arxiv.org/html/2606.14433v1 : 800 Go2 trajectories from 40 PPO policies
  (20 each, 5-20 s) in Genesis, 60 Hz control with 4× decimation; 12-DoF joint pos/vel +
  quaternion; CC BY 4.0; HF `MIMUW-Robotics/kine2go`, code `nomagiclab/kine2go-pipeline`;
  "no trained model or tokenizer".
- T2QRM/DogML https://github.com/SCUT-BIP-Lab/T2QRM : 8,048 dog + robot clips, 8 action
  classes, 12,072 descriptions; dataset via Google Drive; code "will be released"; VQ details
  and license not given (ACM page returned 403).

---

## 2. Comparison tables

### 2a. Tokenizers (all from fetched text)
| System | Quantizer | Codes / layer × layers | Frames per token | Chunk | Rate at 50 Hz | Recon / fidelity | Decoded by |
|---|---|---|---|---|---|---|---|
| BeT 2022 | k-means + offset | 24-64 × 1 | 1 | 1 | 50 tok/s | offset restores exact | policy head |
| VQ-BeT 2024 | RVQ + offset | 8-16 × 2 (LeRobot 16 × 2) | 1-5 | 5 | 10 tok/s (chunk 5) | offset head "quite important" | MLP decoder |
| ACT 2023 | none (CVAE z) | — | 100 | 100 | 0.5 chunk/s | — | direct |
| FAST 2025 | DCT + BPE | vocab 1024 | variable | 1 s | ~53 tok/s (14-D) | lossless to γ=10 rounding | direct |
| VQ-VLA 2025 | RVQ | 256 × Nq | 1 | 5 | 10 tok/s | — | direct |
| BEAST 2025 | B-spline bins | 256 bins | — | 1 s | 5-10 tok/s | MSE 0.0004 | direct |
| OmniSAT 2025 | B-spline + RVQ | 256/256/64 × 8 | — | 1 s | ~8 tok/s per DoF group | MAE 9.4e-4 | direct |
| X-Tokenizer 2026 | SRQ | 2048 × 4 | 4 | 64 | 12.5 slot/s | ℓ1 0.0169 | direct |
| DuoCore-FS 2025 | RVQ | 1024 | — | 32 | 1-3 Hz slow | — | 25-30 Hz fast model |
| QUART-Online 2024 | RVQ (ACD) | 512 × 2 | 10 (cmd) | 10 | 5 tok/s | MAE 0.012, PSNR 32.1 | 50 Hz locomotion ctrl |
| MotionGlot 2024 | VQ | 128 × 1 | 4 | — | 12.5 tok/s | R-prec 0.48@3 | Spot controller (demo) |
| VQ-PMC 2023 | VQ | 256 × 1 (32-D) | 1 | 1 | 50 tok/s | — | PD 500 Hz on MAX |
| MoReFlow 2025 | VQ | 256 × 1 (Spot) | 4 | 32 | 12.5 tok/s | FID 33.1 | sim only |
| Heracles 2026 | iFSQ | 2^K+1 levels | — | — | 25 Hz replanning | 90.6 % completion | 50 Hz tracker on G1 |
| Beyond MoCap 2026 | VQ | 2048 × 1 | 4 | — | 7.5 tok/s @30 fps | 76 % code use | — |

### 2b. Go2 / quadruped decode evidence
| System | Robot | Latent type | Real-robot number | Onboard compute |
|---|---|---|---|---|
| Walk Like Dogs | Go2 | continuous 18-D vMF | qualitative | — |
| QuadFM / Gen2Control | Go2 X | continuous VAE | <500 ms E2E; MBPE 0.0744 m | Jetson Orin |
| Uni-Mo | Go2 | none (per-clip tracker) | 96.7 % over 392 motions | — |
| ABot-C0 | Tutu | continuous 32-D VAE | 92.74 % seen / 88.54 % unseen | AGX Orin 64 GB |
| VQ-PMC | MAX | **discrete 256** | chase-tag win 2:0 | — |
| QUART-Online | quadruped (unnamed) + Isaac Gym | **discrete 512 × 2** | success 0.68-0.79 (sim) | — |
| MotionGlot | Spot | **discrete 128** | hardware demo | — |

---

## 3. What this means for Parcel

1. **Token rate: one body token per speech frame (80 ms), not per 50 Hz frame.** FAST shows
   per-frame binning at 50 Hz makes the model copy the previous action; MotionGlot,
   X-Tokenizer, MoReFlow and Beyond-MoCap all use 4 frames/token; at 50 Hz that is exactly
   12.5 tokens/s — the Mimi/Moshi speech frame rate. The body lane can therefore be a single
   extra token position in each duplex frame, with the tracker interpolating the 4 frames in
   between (ACT-style temporal ensembling or the QuadFM 2 Hz → 50 Hz pattern).

2. **Codebook: RVQ, Nq=2, 16-128 codes per layer, plus an offset/continuous residual.**
   VQ-BeT's ablation (8-16 per layer sufficient; 65,536 combos no better) and the quadruped
   codebooks in the wild (MotionGlot 128, VQ-PMC 256, MoReFlow-Spot 256, QUART-Online 512×2)
   bound the useful range; a 30-100 clip dog library should start at 16-64 per layer to keep
   utilization high (Beyond MoCap saw only 76 % use at 2048 with ~1M sequences). Keep VQ-BeT's
   coarse/fine split: primary code = behavior mode (chuckle, look-back, play-bow, trot...),
   secondary code = variation; put intensity in a continuous scalar (DFM 0.5-1.5× tempo or
   AMOR-style tracker weights) rather than in more codes.

3. **What the token means: a chunk of *command-level* body pose, not joint torques.**
   QUART-Online tokenizes 10-step chunks of a 12-D command vector (velocities, gait, body
   height/pitch, terminate) and reaches PSNR 32 with 512×2 codes; QuadFM/ABot-C0 send a
   pose/latent reference to a universal 50 Hz tracker. For Parcel the natural token payload
   is an 80 ms window of the 19-D Go2 reference state (root pos + quat + 12 joints, the
   Uni-Mo format) or the 12-D command vector, decoded by one PPO tracker trained on the whole
   clip library. That tracker is the only thing that touches the real robot.

4. **Decodability on Go2 is a build, not a bet.** Discrete codes → 50 Hz controller is proven
   on MAX (VQ-PMC), Spot (MotionGlot), G1 (Heracles/Humanoid-LLA), and in Isaac Gym on a
   quadruped (QUART-Online); continuous latent → 50 Hz tracker is proven on the real Go2 with
   Orin at <500 ms (QuadFM) and 96.7 % success (Uni-Mo). The missing experiment — quantize a
   Go2 reference latent and confirm the tracker still hits ~95 % on held-out clips — costs one
   RVQ training (LeRobot default 20k steps) plus one overnight PPO run (4,096 envs on one
   RTX-class GPU per Walk-Like-Dogs / Uni-Mo / QuadFM). Acceptance bar: sim success ≥95 % on
   curated clips, MPJPE ≤ ~4° (Uni-Mo) on reconstructed-from-token references.

5. **Data and licences.** Fit the tokenizer on Quad-Imaginarium (7,488 Go2 motions, CC BY
   4.0) + Kine2Go (800 Go2 gait trajectories, CC BY 4.0) + Parcel's own 30-100 authored
   expressive clips; Tencent Labrador mocap is research-only; QuadFM (CC BY 4.0) and DogML
   are announced but not yet usable; ABot-C0 is CC BY-NC-ND (read, do not copy). Tokenizer
   code: VQ-BeT official (MIT) / LeRobot vqbet (Apache-2.0) / RDT2 RVQActionTokenizer
   (Apache-2.0); avoid VQ-VLA and BEAST code (CC BY-NC-SA) for anything productised.

6. **Why not FAST for the body lane.** FAST+ is universal and CC BY 4.0, but at 50 Hz it
   yields ~53 tokens per second per 14-D stream and needs ~750 ms of autoregressive decoding
   per 1 s chunk — incompatible with a 12.5 Hz shared clock. FAST remains the right choice
   if the body lane is ever moved to a separate slow VLA (the pi0-FAST pattern from the
   earlier note).

7. **How "chuckle" and "look back" become learnable.** With one token per 80 ms, a 1-2 s
   chuckle is a 12-25-token motif and a look-back is a yaw/pitch motif keyed to the owner's
   bearing; both live in the primary-code space, so a laughter-reward or track-loss-event
   signal only has to shift the probability of a handful of primary codes at the right
   conversational moment (the bandit/preference-RL regime from the first sweep; LGPL shows
   ~4 queries move a 5-D behavior space). The tracker guarantees the emitted motif is
   physically executable regardless of what the language model samples.

8. **Compute budget.** The tokenizer (VQ-BeT-class encoder/decoder, 128-256-D) and the
   tracker MLP (QuadFM 2048-1024-512-256; Uni-Mo 512/256/128) are negligible next to the
   duplex speech model on the Orin; ABot-C0 runs a 50 Hz flow-policy tracker on the same
   AGX Orin 64 GB module. The Orin latency question is entirely the speech/LM side.

## 4. Open questions this note does not settle
- Whether a 16-64-code primary layer separates "expressive" motifs (chuckle bounce, head
  tilt via body pitch/roll) from locomotion modes cleanly, or whether a factorised codebook
  (gait × posture × head) is needed; VQ-BeT's `sequentially_select` and OmniSAT's per-DoF-group
  codebooks are the two precedents.
- No paper reports codebook utilization or reconstruction on a ≤100-clip library; expect to
  need FSQ or EMA-updated RVQ (X-Tokenizer) to avoid dead codes.
- QUART-Online's real-robot success is not quantified in the text fetched; treat its +65 % as
  a simulation number.
