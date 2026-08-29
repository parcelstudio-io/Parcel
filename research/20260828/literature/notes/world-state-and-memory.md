# World-state representation, world models, and memory for a full-duplex companion behavior model

Research note for Parcel, 2026-08-28. Topic: how to represent the "state of the
world" (sensors, voice, user history, world state) as an input a trainable
behavior model can learn from; what world-model agents actually enable; how
embodied LLM agents serialize observations; long-term memory for companion
agents; event/timestep encoding for continuous streams; personalization
benchmarks; and a concrete token schema for a full-duplex behavior model that
reads a state stream at ~2-10 Hz.

Method: every source below was located with WebSearch and then read with
WebFetch (arXiv abstract page, arXiv/ar5iv HTML body, vendor page, or GitHub
README). Numbers are quoted from what the fetch returned. Where a fetch did
not return a number I expected, I say so rather than fill it from memory.
Two fetches failed and are flagged: the ECoT/RT-2 PDFs exceeded the fetch
size limit (RT-2 was recovered via ar5iv; ECoT via arXiv HTML), and the 1X
"Evaluating Bits, not Atoms" PDF did not parse (its headline number was
recovered from the 1X vendor page). The WebSearch budget for the session
ran out after the last two searches (laughter-detection and robot-humor
papers), so those were fetched by known URL rather than found by search.

Hardware frame for the assessments: dev desktop RTX 5000 Ada 32 GB / 192
cores / 246 GB RAM / MuJoCo 3.11; deploy target Jetson AGX Orin 64 GB on a
Unitree Go2 EDU+; no robot on hand today.

---

## A. World-model RL agents: what they actually enable for behavior learning

### A1. DreamerV3 — "Mastering Diverse Domains through World Models"
- arXiv: https://arxiv.org/abs/2301.04104 (v2 April 2024); body read at
  https://arxiv.org/html/2301.04104v2 ; Nature version read at
  https://www.nature.com/articles/s41586-025-08744-2 (Nature 640, 647-653,
  published 2 April 2025); code https://github.com/danijar/dreamerv3 (MIT,
  JAX; README notes it is a reimplementation "unrelated to Google or
  DeepMind").
- Numbers: "over 150 diverse tasks" across "8 domains" with "a single
  configuration"; Atari 57 games, ProcGen 16, DMLab 30, etc.; "6 model sizes
  ranging from 12M to 400M parameters"; "All agents trained on single Nvidia
  A100 GPUs"; "All the Dreamer agents we trained on Minecraft discover
  diamonds in 100M environment steps"; robustness tricks: symlog(x) =
  sign(x) ln(|x|+1), two-hot returns with exponentially spaced bins, free
  bits (clip dynamics/representation KL below 1 nat). "Larger models not
  only increase task performance but also require less interaction to solve
  a task."
- What it enables: a world model (RSSM with categorical latents) learned
  from arbitrary sensory dicts (images + vectors) plus a policy trained in
  imagination; the same config works for continuous and discrete actions,
  visual and proprioceptive inputs.
- Assessment: the strongest "single config, any domain" claim in the
  literature, published in Nature, MIT code, one GPU per run. This is the
  most credible off-the-shelf route to "learn what to do given the state of
  the world" from a *vector/latent* (not token) state representation. It
  does not read text or user history; those must be encoded as extra vector
  channels, and there is no published result on social/conversational
  reward.

### A2. TD-MPC2 — "Scalable, Robust World Models for Continuous Control"
- arXiv: https://arxiv.org/abs/2310.16828 (ICLR 2024); body read at
  https://arxiv.org/html/2310.16828v2 ; site https://www.tdmpc2.com/ ; code
  https://github.com/nicklashansen/tdmpc2 (MIT).
- Numbers: "104 online RL tasks" across DMControl, Meta-World, ManiSkill2,
  MyoSuite; single "317M parameter agent" on 80 tasks (50 Meta-World + 30
  DMControl); model sizes 1M / 5M / 19M / 48M / 317M; released datasets
  545M transitions / 2.69M episodes / 34 GB (80 tasks) and 345M / 690k /
  20 GB (30 tasks); "324 checkpoints". Architecture: latent dim 512 in the
  5M model (1376 in 317M), SimNorm latents (8-D simplices), MPPI horizon
  H=3, 5 Q-functions (8 in 317M), proprio states up to 223-D (Dog
  embodiment), pixels 64x64 via a 4-layer conv encoder. Multi-embodiment
  handled by "zero-padding all model inputs and outputs to their largest
  respective dimensions" + action masking "during both training and
  inference" + a "96-D" learnable task embedding. Hardware (README):
  single-task online RL needs ~12 GB RAM / 8 GB GPU; the 80-task offline
  set needs 128 GB RAM and a 24 GB GPU for the 317M model.
- Assessment: decoder-free (implicit) world model with planning; the 5M
  model trains comfortably on the Parcel desktop and would run on Orin. The
  zero-pad + mask + task-embedding trick is directly reusable for a state
  vector whose channels vary (owner visible or not, speech on or off).

### A3. IRIS — "Transformers are Sample-Efficient World Models"
- arXiv: https://arxiv.org/abs/2209.00588 (ICLR 2023 top-5%); body read at
  https://ar5iv.labs.arxiv.org/html/2209.00588 ; code
  https://github.com/eloialonso/iris (GPL-3.0).
- Numbers: discrete autoencoder with K=16 tokens per 64x64 frame,
  vocabulary N=512; transformer D=256, 10 layers, 4 heads, context L=20
  timesteps, "interleaved frame tokens followed by action tokens"; Atari
  100k mean human-normalized score 1.046, median 0.289, IQM 0.501,
  "outperforms humans on 10 out of 26 games" after 100k steps ("two hours
  of gameplay"); compute "around 7 days" on "8 Nvidia A100 40GB GPUs" with
  two envs per GPU (~3.5 GPU-days per game).
- Assessment: the canonical proof that a *token* world model (frame tokens +
  action token, autoregressive transformer) can be learned and used for
  imagination-based policy learning at tiny scale. The token layout
  (observation tokens, then an action token, repeated per step) is the
  ancestor of the schema recommended below.

### A4. Delta-IRIS — "Efficient World Models with Context-Aware Tokenization"
- arXiv: https://arxiv.org/abs/2406.19320 (ICML 2024); body read at
  https://arxiv.org/html/2406.19320v1 ; code
  https://github.com/vmicheli/delta-iris (GPL-3.0; a Crafter 5M-frame agent
  checkpoint is on the Hugging Face Hub).
- Numbers: encodes frames with 4 tokens ("4 x log2(1024) = 40 bits") versus
  IRIS's 16-64 tokens (160 bits); 64x64 frames; Delta-IRIS 25M params vs
  IRIS 48M vs DreamerV3 XL 200M; Crafter return 7.7 at 1M frames (IRIS
  5.5), 16.1 at 10M frames "solving 17 out of 22 tasks", surpasses
  DreamerV3 XL beyond 3M frames; collection at "20 frames per second",
  "10 times faster than IRIS" (2 FPS). Sequence = "I-tokens, action
  tokens, and delta-tokens" interleaved, where I-tokens are continuous
  frame embeddings and delta-tokens are the stochastic change since the
  previous step.
- Assessment: the key idea for a low-rate state stream: tokenize *deltas*
  conditioned on a continuous context embedding, not full frames. Four
  tokens per step for the visual channel is a realistic budget at 5 Hz.

### A5. Genie 3 (Google DeepMind)
- Blog read at https://deepmind.google/blog/genie-3-a-new-frontier-for-world-models/
  (published 5 August 2025).
- Numbers/claims: 24 fps, 720p, consistency "several minutes", visual
  memory "as far back as one minute ago", responds to inputs "multiple
  times per second"; promptable world events; SIMA agent tested inside
  generated worlds. Stated limitations: "restricted action repertoire",
  multi-agent interaction, geographic accuracy, text rendering, "few
  minutes of continuous interaction, rather than extended hours".
  Availability: "limited research preview" for "a small cohort of academics
  and creators".
- Assessment: not trainable, not downloadable, action space limited to
  navigation-style inputs. Irrelevant as a component for Parcel; relevant
  only as evidence that generated worlds can host agent training loops.

### A6. 1X World Model (1X Technologies)
- Pages read: https://www.1x.tech/discover/1x-world-model ;
  https://www.1x.tech/discover/redwood-ai-world-model (16 June 2025);
  https://www.1x.tech/discover/world-model-self-learning (12 Jan 2026);
  challenge repo https://github.com/1x-technologies/1xgpt (Apache 2.0);
  challenge technical report https://arxiv.org/abs/2510.07092 (Team
  Revontuli, Oct 2025). The 1X "Evaluating Bits, not Atoms" PDF
  (https://www.1x.tech/1x-world-model.pdf) did not parse in the fetcher;
  its headline number below is quoted from the vendor page, so it is
  single-source.
- Numbers: trained on "thousands of hours" of EVE humanoid data; released
  "over 100 hours of vector-quantized image tokens and raw actions", each
  example "16 first-person images at 2Hz (8 seconds)", MAGVIT2 tokens at
  "16x16 tokens" per 256x256 frame, factorized 2 x 2^9 vocabulary; baselines
  GENIE_138M (8.79 CE, 0.075 s/frame) and GENIE_35M (8.99 CE, 0.030
  s/frame); compression target "loss below 8.0" ($10k). Evaluation claim:
  "Given a true real-world success rate gap of 15% between two policies, a
  World Model with 70% accuracy can accurately predict the better policy
  with 90% success"; tested on 3 tasks (air fryer, arcade, shelf); it
  "struggles to model interactions with held-out objects". 1XWM-as-policy
  (Jan 2026): 14B video diffusion backbone, 900 h egocentric human video
  mid-training, 70 h NEO data, 400 h for the inverse-dynamics model;
  inference ~11 s (multi-GPU) for 5 s of video + ~1 s IDM; 30-trial
  success 80% in-distribution (grab chips), 40-70% mid, 0% on pour
  cereal / draw smiley; parallel sampling raised "pull tissue" from 30% (1
  sample) to 45% (8 samples). Challenge winners: 23.0 dB PSNR (sampling),
  6.6386 top-500 CE (compression), using Wan-2.2 TI2V-5B + LoRA and a
  from-scratch spatio-temporal transformer.
- Assessment: the important lesson is *evaluation*, not control: a
  learned world model of modest accuracy can rank policies. The 2 Hz,
  16-frame, 16x16-token dataset format is an existence proof of a
  low-rate discrete state stream with actions. The 14B policy at ~13 s per
  decision is far from duplex real time.

### A7. NVIDIA Cosmos World Foundation Model Platform
- arXiv: https://arxiv.org/abs/2501.03575 ; body read at
  https://arxiv.org/html/2501.03575v2 ; code
  https://github.com/nvidia-cosmos/cosmos-predict1 (code Apache 2.0, models
  "NVIDIA Open Model License").
- Numbers: "about 20M hours of raw videos", ~1e8 clips for pre-training and
  ~1e7 for fine-tuning; trained on "a cluster of 10,000 NVIDIA H100 GPUs in
  a time span of three months"; diffusion WFMs 7B and 14B (Text2World /
  Video2World), autoregressive WFMs 4B/12B (5B/13B Video2World);
  tokenizers CV/DV at 4x8x8, 8x8x8, 8x16x16 (e.g. Cosmos-Tokenize1-DV8x16x16-720p);
  repo explicitly supports "Post-train diffusion-based Video2World models
  with action control using custom datasets". Inference latency not given
  in the fetched content (V-JEPA 2 reports "4 minutes" per action for a
  Cosmos-based planner baseline, A9).
- Assessment: an offline data/sim asset, not an on-robot component.
  Possible use: action-conditioned post-training to generate camera video
  for Go2 states in MuJoCo-rendered scenes, for pretraining a visual
  tokenizer. The discrete video tokenizers are the most reusable piece.

### A8. GAIA-2 (Wayve)
- arXiv: https://arxiv.org/abs/2503.20523 ; body read at
  https://arxiv.org/html/2503.20523v1 .
- Numbers: video tokenizer 85M (encoder) / 200M (decoder); world model
  8.4B; "up to five" camera streams at 448x960; ~25M 2-second sequences;
  20/25/30 Hz; conditions on ego speed and curvature, 3D agent boxes,
  weather, time of day, lane/crossing/traffic-light semantics, country.
  No weights/code release statement found.
- Assessment: not usable directly, but it is the cleanest published example
  of a world model conditioned on a *structured* state vector (ego
  dynamics + agent list + environment factors) rather than raw pixels only.
  That structure maps well onto Parcel's state stream (robot dynamics +
  owner/person list + room context).

### A9. V-JEPA 2 and V-JEPA 2-AC (Meta)
- arXiv: https://arxiv.org/abs/2506.09985 ; body read at
  https://arxiv.org/html/2506.09985v1 ; code
  https://github.com/facebookresearch/vjepa2 (MIT, some Apache-2.0 files;
  checkpoints ViT-L 300M, ViT-H 600M, ViT-g 1B; V-JEPA 2.1 adds ViT-B 80M
  and ViT-G 2B; V-JEPA 2-AC checkpoint provided).
- Numbers: pretraining "over 1 million hours" from "22 million" videos;
  action-conditioned predictor "~300M parameter transformer, 24 layers, 16
  heads, 1024 hidden", trained on "less than 62 hours" of DROID robot
  video; proprio = "a real-valued 7D vector" (EE position, Euler
  orientation, gripper); planning by CEM over a goal-conditioned energy,
  receding horizon; "16 seconds per action" vs 4 minutes for the Cosmos
  baseline; Franka zero-shot: reach 100%, grasp cup/box 70%/30%,
  reach-with-object 90%/80%, pick-and-place 80%/80%; SSv2 77.3, EK100
  R@5 39.7, PerceptionTest 84.0, TempCompass 76.9.
- Assessment: the strongest open, permissively licensed *visual state
  encoder* (frozen features) available; the AC planner at 16 s/action is
  not real time. For Parcel: use the ViT-B/L encoder frozen as the visual
  channel of the state stream (one or a few pooled tokens per tick), not
  as a planner.

---

## B. Multimodal state tokenization for embodied LLM/transformer agents

### B1. PaLM-E — "An Embodied Multimodal Language Model"
- arXiv: https://arxiv.org/abs/2303.03378 ; body read at
  https://ar5iv.labs.arxiv.org/html/2303.03378 ; site https://palm-e.github.io/ .
- Serialization: "multi-modal sentences that interleave visual, continuous
  state estimation, and textual input encodings"; state vectors s in R^S
  are mapped by an MLP phi_state into the language embedding space; ViT
  features get "a learned affine transformation psi"; OSRT object slots are
  projected to m embeddings each; entity referral: "Object 1 is <obj_1>.
  ... Object j is <obj_j>". Sizes 12B (8B LLM + 4B ViT), 84B (62B + 22B),
  562B (540B + 22B). TAMP with 1% data (320 examples): OSRT 82.5% / 76.2%
  vs ViT-4B single-robot 30.6% / 32.9%; Language-Table full-mixture 80%
  with 40 demos vs 50% single-robot; catastrophic forgetting: 562B loses
  3.9% NLG vs 87.3% for 12B. No code/weights.
- Assessment: canonical pattern for injecting continuous state as
  embedding-space vectors *alongside* text, and for per-entity tokens with
  referable IDs. Its per-entity "Object j is <obj_j>" idea is exactly what
  a companion needs for owner/person/object slots.

### B2. LEO — "An Embodied Generalist Agent in 3D World"
- arXiv: https://arxiv.org/abs/2311.12871 (ICML 2024); body read at
  https://ar5iv.labs.arxiv.org/html/2311.12871 ; site
  https://embodied-generalist.github.io/ (code and data available).
- Serialization: system message + optional 2D egocentric image tokens +
  object-centric 3D tokens + instruction -> response; "up to 60 objects
  per scene" (Mask3D proposals), one token per object after PointNet++ and
  a spatial transformer; actions "discretized" into bins and "mapped to
  the least used tokens in SentencePiece"; Vicuna-7B with ~142M tuned
  (LoRA); LEO-align ~1M (660K object captioning, 354K referring, 20K scene
  captioning), LEO-instruct ~540K over 8 task types; ObjNav MP3D success
  23.1 / SPL 15.2; CLIPort separating-piles 98.8% seen / 75.2% unseen.
- Assessment: the most direct template for "one token per world entity +
  one token per ego view + text", and for reusing rare tokens as action
  tokens in a 7B LLM. The ObjNav numbers show navigation-from-tokens is
  weak (23% success) at this scale, so body navigation should stay in the
  RL/planner lane, not the LLM.

### B3. Octo — "An Open-Source Generalist Robot Policy"
- arXiv: https://arxiv.org/abs/2405.12213 ; body read at
  https://arxiv.org/html/2405.12213v2 ; site https://octo-models.github.io
  (CC BY 4.0).
- Numbers: Octo-Small 27M, Octo-Base 93M; "800k robot demonstrations" from
  "25 datasets" of Open X-Embodiment; task tokens from t5-base (111M) ->
  "16 language embedding tokens"; images -> shallow conv -> patches: "256
  tokens for the 3rd person camera images and 64 tokens for the wrist
  camera"; learned "readout tokens" that attend to observation and task
  tokens "but is not attended to by any observation or task token";
  "block-wise masked" attention where observation tokens attend causally
  to same-or-earlier timesteps; action chunking + conditional diffusion
  head with "20 diffusion steps"; finetuning with "~100 in-domain
  demonstrations" in "<5 hours on a NVIDIA A5000 GPU"; evaluated on "9
  robot learning setups at 4 institutions".
- Assessment: the cleanest published blueprint for a small transformer
  that reads heterogeneous per-timestep observation tokens with a
  block-causal mask and emits actions via readout tokens. New sensors are
  added by adding a tokenizer, which is exactly how audio-event and
  owner-state channels would be added for Parcel. Trainable on the desktop
  and deployable on Orin at these sizes.

### B4. RT-2 — "Vision-Language-Action Models Transfer Web Knowledge to Robotic Control"
- arXiv: https://arxiv.org/abs/2307.15818 ; body read at
  https://ar5iv.labs.arxiv.org/html/2307.15818 ; site
  https://robotics-transformer2.github.io/ .
- Numbers: actions = 8 integers, each dimension "discretized into 256
  bins"; for PaLI-X "integers up to 1000 each have a unique token", for
  PaLM-E "we simply overwrite the 256 least frequently used tokens";
  example action string "1 128 91 241 5 101 127 217"; sizes 5B / 55B
  PaLI-X and 12B PaLM-E; "the 55B parameter RT-2-PaLI-X-55B model, can run
  at a frequency of 1-3 Hz", the 5B "around 5 Hz", served from "a
  multi-TPU cloud service"; "about 6,000 evaluation trajectories"; unseen
  objects 70% (easy) / 62% (hard) vs RT-1 31% / 43%; symbol understanding
  82% vs 16%. No code/weights.
- Assessment: establishes that (a) actions-as-text-tokens works in a VLM
  and (b) VLM-scale models run at 1-5 Hz even on cloud TPUs. That rate band
  is the natural rate for the semantic lane, with a faster body lane
  underneath (see GR00T N1, Helix).

### B5. ECoT — "Robotic Control via Embodied Chain-of-Thought Reasoning"
- arXiv: https://arxiv.org/abs/2407.08693 ; body read at
  https://arxiv.org/html/2407.08693v3 ; site https://embodied-cot.github.io
  (CC BY 4.0).
- Numbers: chain = TASK, PLAN, SUBTASK, MOVE, GRIPPER POSITION [x, y],
  VISIBLE OBJECTS with boxes; "from 7 for OpenVLA to 350 for ECoT" tokens
  per timestep; annotated "the complete Bridge v2 dataset with more than
  2.5M transitions" (7 days of processing); aggregate generalization:
  OpenVLA 44% +/- 3.9, ECoT 66% +/- 3.8, RT-2-X 47% +/- 4.0 (~28%
  absolute over OpenVLA, no extra robot data); "5-step synchronous" +24%
  speed at 72%, asynchronous +40% speed at 65% (double compute); human
  language feedback +48% on hard tasks.
- Assessment: explicit, structured intermediate state (what is visible,
  where the effector is, what the current sub-goal is) improves a 7B
  policy substantially, at a 50x token cost per step. For a 2-10 Hz
  stream this argues for a *compact* structured reasoning slot (a few
  tokens: current goal, target entity, mood), not free-form CoT per tick.

### B6. ELLM — "Guiding Pretraining in Reinforcement Learning with Large Language Models"
- arXiv: https://arxiv.org/abs/2302.06692 (ICML 2023); PDF read at
  https://arxiv.org/pdf/2302.06692 .
- Numbers/mechanism: state captioned to text (Crafter: "list of observed
  objects, inventory, health status"; Housekeep: "object-receptacle
  relations"); LLM = Codex; reward when SentenceBERT similarity between the
  transition caption and a suggested goal exceeds 0.99; goal suggestions
  cached and reused; "~15% increase" in ground-truth achievement coverage
  vs the compared baseline, "2-3x" sample-efficiency improvement reported
  in the fetched summary. Code released.
- Assessment: the canonical "caption the state, let the LLM propose
  goals, reward achievement" loop. Directly applicable to Parcel's
  learning loop: caption the state stream (owner laughing, owner out of
  view, robot idle) and let the text model propose socially meaningful
  goals ("re-establish eye contact", "acknowledge the joke"), rewarded by
  caption-goal match.

### B7. FAST — "Efficient Action Tokenization for Vision-Language-Action Models"
- arXiv: https://arxiv.org/abs/2501.09747 ; body read at
  https://arxiv.org/html/2501.09747v1 .
- Numbers: normalize to 1st/99th quantile -> per-dimension DCT ->
  scale-and-round -> low-frequency-first flatten -> BPE; 1-second chunks:
  BridgeV2 5 Hz naive 35 -> 20 tokens, DROID 15 Hz 105 -> 29, table
  bussing 20 Hz 140 -> 28, T-shirt folding 50 Hz 700 -> 53 (13.2x);
  handles up to 50 Hz; FAST+ trained on "approximately one million
  1-second action chunks"; naive binning "fails completely" at high
  frequency; up to 5x faster training than diffusion VLAs at 10k hours of
  data.
- Assessment: if Parcel emits body-intent as tokens at 50 Hz (the existing
  ACT-token codec over velocity bins), FAST is the way to keep the
  per-second token budget at ~30-50 tokens instead of hundreds.

### B8. GR00T N1 — "An Open Foundation Model for Generalist Humanoid Robots"
- arXiv: https://arxiv.org/abs/2503.14734 (CC BY 4.0); body read at
  https://arxiv.org/html/2503.14734v1 .
- Numbers: System 2 = Eagle-2 VLM (1.34B in the VL component, SigLIP-2 +
  SmolLM2, features from layer 12) "runs at 10Hz on an NVIDIA L40 GPU";
  System 1 = flow-matching diffusion transformer "at a higher frequency
  (120Hz)", chunk H=16, K=4 denoising steps; total "2.2B parameters";
  "inference time for sampling a chunk of 16 actions is 63.9ms on an L40
  GPU using bf16"; data: "88 hours" GR-1 teleop, OXE, 140k AgiBot
  trajectories, "827 hours" neural (video-model) trajectories, "780,000
  simulation trajectories - equivalent to 6,500 hours", plus human video
  (Ego4D etc.); embodiment-specific MLP encoders/decoders for variable
  state/action dims; sim results RoboCasa 32.1% vs 25.6% DP, DexMimicGen
  66.5% vs 56.1%, GR-1 tabletop 50.0% vs 32.7%; real robot 76.8% average
  over 8 tasks, 42.6% with 10% data vs 10.2% DP; checkpoint, data and
  benchmarks public.
- Assessment: the strongest public evidence for the dual-rate design: a
  ~10 Hz semantic module and a >100 Hz motor module, trained jointly
  end-to-end, 2.2B total, with per-embodiment state/action MLPs. It is
  the model whose *architecture* Parcel should copy (semantic stream at
  2-10 Hz conditioning a fast body lane), even if the humanoid weights are
  not used.

### B9. Helix (Figure AI) — vendor page https://www.figure.ai/news/helix
- Numbers: S2 = "a 7B-parameter open-source, open-weight VLM" at "7-9 Hz";
  S1 = "an 80M parameter cross-attention encoder-decoder transformer" at
  "200 Hz"; S2 -> S1 via "a single continuous latent vector"; "~500 hours"
  of teleop; "dual low-power-consumption embedded GPUs" per robot.
- Assessment: vendor claim, no paper; corroborates GR00T's rate split and
  the "single latent vector from the slow lane conditions the fast lane"
  interface, which matches Parcel's existing 50 Hz body-intent lane.

### B10. Moshi — "a speech-text foundation model for real-time dialogue" (Kyutai)
- arXiv: https://arxiv.org/abs/2410.00037 ; body read at
  https://arxiv.org/html/2410.00037v2 ; code
  https://github.com/kyutai-labs/moshi (code MIT/Apache-2.0, weights
  CC-BY 4.0).
- Numbers: Mimi codec "12.5 frames per second", "1.1kbps", Q=8 codebooks
  of 2048 (README: 80 ms codec latency; the README's codebook count
  differs from the paper's Q=8, likely counting semantic + acoustic
  levels differently); Helium 7B backbone (32 layers, dim 4096, 2.1T text
  tokens); depth transformer 6 layers / dim 1024 / 16 heads; two audio
  streams (Moshi and user) -> K = 2Q+1 = 17 parallel token sequences per
  12.5 Hz frame including the "inner monologue" text stream; text/audio
  delay randomized in [-0.6, +0.6] s in pretraining, fixed to 0 or 1 step
  in finetuning; "7 million hours" of audio; latency "160ms" theoretical,
  "200ms in practice"; 24 GB GPU for bf16, int8/int4 variants, MLX on
  Mac/iPhone.
- Assessment: the reference design for full-duplex token streams: parallel
  per-stream tokens at a fixed frame rate, a text "inner monologue"
  time-aligned with audio, and a small delay between semantic and acoustic
  streams. Adding a *body/expression stream* as one more parallel sequence
  is the natural extension for Parcel; this is also the family Parcel's
  duplex voice module already resembles (ACT-token codec over velocity
  bins).

### B11. Qwen2.5-Omni — TMRoPE time-aligned positions
- arXiv: https://arxiv.org/abs/2503.20215 (CC BY 4.0); body read at
  https://arxiv.org/html/2503.20215v1 ; weights https://huggingface.co/Qwen .
- Numbers: "one temporal ID corresponds to 40ms" for audio; video frames
  get temporal IDs by actual time; images keep constant temporal IDs;
  audio+video are interleaved in "chunks every 2 seconds", vision first
  then audio; audio encoder 128-mel, 25 ms window, 10 ms hop, block-wise
  attention "in blocks of 2 seconds"; Thinker 7B + Talker dual-track
  decoder; first-packet latency not stated.
- Assessment: the practical answer to "how do you timestamp heterogeneous
  streams inside one transformer": absolute-time position IDs at a fixed
  quantum (40 ms) shared across modalities, plus fixed-length chunking. A
  Parcel tick of 200 ms = 5 temporal IDs.

---

## C. Long-term memory for companion agents

### C1. Generative Agents — "Interactive Simulacra of Human Behavior"
- arXiv: https://arxiv.org/abs/2304.03442 ; body read at
  https://ar5iv.labs.arxiv.org/html/2304.03442 ; code
  https://github.com/joonspk-research/generative_agents , retrieval
  implementation read at
  https://raw.githubusercontent.com/joonspk-research/generative_agents/main/reverie/backend_server/persona/cognitive_modules/retrieve.py .
- Numbers: memory object = "a natural language description, a creation
  timestamp, and a most recent access timestamp"; retrieval score =
  recency (exponential decay, "decay factor is 0.995" per sandbox game
  hour) + importance (LLM-rated 1-10) + relevance (embedding cosine), all
  alphas = 1 in the paper; the code uses gw = [0.5, 3, 2] for
  recency/relevance/importance and retrieves n_count = 30; reflection
  fires when summed importance of recent events exceeds 150 ("roughly two
  or three times a day"); plans decomposed day -> hour -> "5-15 minute
  chunks"; 25 agents; 100 human evaluators, TrueSkill mu 29.89 (full) vs
  21.21 (no memory/reflection/planning), "d=8.16".
- Assessment: the canonical memory-stream design; every later memory
  system (A-MEM, Mem0, Letta) is a variant. For Parcel the reusable parts
  are the three-factor retrieval score and the importance-triggered
  reflection, both cheap to run on a local model.

### C2. Voyager — "An Open-Ended Embodied Agent with Large Language Models"
- arXiv: https://arxiv.org/abs/2305.16291 ; code at voyager.minedojo.org.
- Numbers: "ever-growing skill library of executable code", embedding-
  indexed; automatic curriculum; self-verification via environment
  feedback; GPT-4 black-box; 3.3x unique items, 2.3x distance, 15.3x
  faster tech-tree milestones vs prior SOTA.
- Assessment: the skill-library-as-memory idea maps to Parcel's existing
  `skill_outcomes.py` and affordance planner: store verified behaviors
  (with the state-context in which they worked) as retrievable skills.

### C3. MemGPT / Letta — "Towards LLMs as Operating Systems"
- arXiv: https://arxiv.org/abs/2310.08560 ; body read at
  https://arxiv.org/html/2310.08560v2 ; code https://github.com/letta-ai/letta
  (Apache-2.0).
- Numbers: main context = system instructions + working context ("fixed-
  size read/write block of unstructured text") + FIFO queue with recursive
  summaries; external = recall storage (messages) + archival storage;
  paging via function calls; MSC deep-memory-retrieval consistency: GPT-4
  + MemGPT 92.5% vs baseline 32.1%, GPT-4 Turbo + MemGPT 93.4% vs 35.3%;
  ROUGE-L ~0.30 -> ~0.81; opener scores 0.857-0.868 vs human.
- Assessment: the "LLM manages its own paging" pattern; strong on recall,
  but MemoryAgentBench (C6) later shows agentic memory systems still fail
  conflict resolution.

### C4. A-MEM — "Agentic Memory for LLM Agents"
- arXiv: https://arxiv.org/abs/2502.12110 (NeurIPS 2025); body read at
  https://arxiv.org/html/2502.12110v10 ; code https://github.com/WujiangXu/A-mem
  (MIT; OpenAI/vLLM/Ollama backends).
- Numbers: note fields = content, timestamp, keywords, tags, contextual
  description, embedding, links; k=10 neighbours for linking; LoCoMo
  multi-hop with GPT-4o-mini: A-MEM F1 45.85 / BLEU-1 36.67 vs MemGPT
  25.52 / 19.44 vs LoCoMo baseline 18.41 / 14.77; Qwen2.5-1.5B multi-hop
  F1 24.32 vs MemGPT 4.21; "approximately 1,200 tokens per memory
  operation", "85-93% reduction" vs ~16,900 for LoCoMo/MemGPT baselines;
  six models incl. Qwen2.5 1.5B/3B and Llama 3.2 1B/3B.
- Assessment: important because it shows a Zettelkasten-style structured
  memory works with *1.5B-3B local models* at ~1.2k tokens per operation,
  which fits Parcel's "local models run continuously" constraint.

### C5. Mem0 — "Building Production-Ready AI Agents with Scalable Long-Term Memory"
- arXiv: https://arxiv.org/abs/2504.19413 ; body read at
  https://arxiv.org/html/2504.19413v1 ; code https://github.com/mem0ai/mem0
  (Apache 2.0).
- Numbers (paper, GPT-4o-mini): LLM-judge single/multi/open/temporal:
  Mem0 67.13 / 51.15 / 72.93 / 55.51; Mem0-g 65.71 / 47.19 / 75.71 /
  58.13; A-Mem 39.79 / 18.85 / 54.05 / 49.91; LangMem 62.23 / 47.92 /
  71.12 / 23.43; Zep 61.70 / 41.35 / 76.60 / 49.31; OpenAI 63.79 / 42.92 /
  62.29 / 21.71; memory footprint ~7k tokens per conversation (Mem0), ~14k
  (Mem0-g), Zep graph ">600k", full raw context ~26k; p95 latency Mem0
  total 1.440 s (search 0.200 s), Mem0-g 2.590 s, full-context 17.117 s;
  abstract: 26% relative improvement over OpenAI memory, 91% lower p95
  latency, 90% token savings. README (April 2026, managed platform):
  LoCoMo 92.5 from 71.4, LongMemEval 94.4 from 67.8, BEAM(1M) 64.1,
  p50 0.88-1.09 s, 6.7-7.0k tokens, with the caveat that open-source
  users "should expect directionally similar gains but not identical
  numbers".
- Assessment: the strongest engineering baseline with a permissive
  license and local-LLM support; note the A-MEM numbers in Mem0's table
  are much lower than A-MEM's own paper (different judge and setup), so
  cross-paper comparisons of memory systems are unreliable.

### C6. LoCoMo — "Evaluating Very Long-Term Conversational Memory of LLM Agents"
- arXiv: https://arxiv.org/abs/2402.17753 ; body read at
  https://arxiv.org/html/2402.17753v1 ; project snap-research.github.io/locomo
  (paper page shows CC-BY-NC-SA 4.0).
- Numbers: 50 conversations, 19.3 sessions and 304.9 turns per
  conversation on average, ~9,209 tokens each; 7,512 QA items: single-hop
  2,705 (36%), multi-hop 1,104 (14.6%), temporal 1,547 (20.6%), open-domain
  285 (3.9%), adversarial 1,871 (24.9%); human overall F1 87.9 (single
  95.1, multi 85.8, temporal 92.6, open 75.4, adversarial 89.4); best
  long-context model at the time (GPT-3.5-turbo-16K) 37.8 overall
  (temporal 20.3, adversarial 2.1); RAG over observations top-5 41.4.
- Assessment: the standard episodic-memory benchmark; temporal and
  adversarial (abstain) questions are where models collapse. Both matter
  for a companion: "when did we last do X" and "you never told me that".

### C7. LongMemEval — https://arxiv.org/abs/2410.10813 (ICLR 2025, CC BY 4.0)
- Numbers: 500 questions; abilities = information extraction, multi-session
  reasoning, temporal reasoning, knowledge updates, abstention; contexts up
  to 1.5M tokens (LongMemEval_M); commercial assistants and long-context
  LLMs show "a 30% accuracy drop" across sustained interactions.

### C8. MemoryAgentBench — "Evaluating Memory in LLM Agents via Incremental Multi-Turn Interactions"
- arXiv: https://arxiv.org/abs/2507.05257 (ICLR 2026); body read at
  https://arxiv.org/html/2507.05257v2 ; code
  https://github.com/HUST-AI-HYZ/MemoryAgentBench (MIT).
- Numbers: four competencies: accurate retrieval (SH-Doc QA 100 q / 197K
  tokens, MH-Doc QA 100 q / 421K, LongMemEval S* 300 q / 355K, EventQA
  500 q / 534K), test-time learning (BANKING77/CLINC150/NLU/TREC 100-200 q
  each; movie recommendation 200 q / 1.44M tokens), long-range
  understanding (InfBench summarization 100 q / 172K; DetectiveQA 71 q /
  124K), selective forgetting / conflict resolution (FactConsolidation SH
  100 q / 262K, MH 100 q). Agents: GPT-4o/4o-mini/4.1-mini, Gemini-2.0-
  Flash, Claude-3.7-Sonnet; BM25, Contriever, text-embedding-3,
  Qwen3-Embedding; RAPTOR, GraphRAG, MemoRAG, HippoRAG-v2, Mem0, Cognee,
  Zep; Self-RAG, MemGPT, MIRIX. Best retrieval: GPT-4.1-mini 83.0% SH /
  66.0% MH / 55.7% LME / 82.6% EventQA; HippoRAG-v2 76.0 / 66.0 / 50.7.
  Test-time learning: Claude-3.7 97.0% BANKING77, 98.0% CLINC150; GPT-4o
  87.6% MCC average. LRU: GPT-4o 77.5% average. Selective forgetting:
  best single-hop GPT-4o 60.0%; multi-hop "all methods fail ... (achieving
  at most 7% accuracy)".
- Assessment: the load-bearing negative result for Parcel's owner model:
  no current memory agent reliably *overwrites* a fact when the owner
  changes their mind, especially when the update must be composed
  (multi-hop <= 7%). Consent-gated facts and preference updates therefore
  need an explicit structured store with versioning, not an LLM-managed
  free-text memory.

---

## D. Event/timestep encoding for continuous streams

### D1. "Temporal Tokenization Strategies for Event Sequence Modeling with LLMs"
- arXiv: https://arxiv.org/abs/2512.13618 (Dec 2025, rev. May 2026).
- Compares five encodings of continuous time: naive numeric strings,
  high-precision byte-level, human-semantic calendar tokens, uniform
  binning, adaptive residual scalar quantization. Finding: "No single
  strategy is universally superior; ... performance depends heavily on
  aligning the tokenizer with the data's statistical properties" (smooth
  log-normal vs spiky). No numbers in the abstract.
- Assessment: for Parcel's stream, inter-event gaps are bimodal (200 ms
  ticks vs minutes of idle), so use *both* a fixed tick index and a
  log-bucketed "time since last event of type X" token, plus calendar
  tokens (hour-of-day, weekday) for routines.

### D2. HT-Transformer — history tokens for event sequences
- arXiv: https://arxiv.org/abs/2508.01474 (CC BY 4.0, code on GitHub).
- "History tokens" accumulate prefix information during next-token
  pretraining, giving the transformer a compact state vector RNNs have;
  applied to finance, e-commerce, healthcare event sequences. No numbers
  in the abstract.
- Assessment: supports inserting periodic "summary/state" tokens into the
  stream (every N ticks) so long histories compress into a few tokens.

### D3. Dywave — event-aligned dynamic tokenization for IoT sensing
- arXiv: https://arxiv.org/abs/2605.14014 (May 2026, CC BY 4.0).
- Wavelet-based hierarchical decomposition finds "meaningful temporal
  boundaries corresponding to underlying semantic events" and compresses
  redundant intervals; "up to 12%" accuracy gain, "up to 75%" token
  reduction, more robust to domain shift and variable length.
- Assessment: evidence that *event-aligned, variable-rate* tokens beat
  fixed-rate ones for sensor streams; motivates emitting "sparse event
  tokens" (laugh onset, owner-lost, door-open) on top of the fixed tick.

### D4. Cross-references already covered: Delta-IRIS delta tokens (A4),
  TMRoPE 40 ms temporal IDs and 2 s chunks (B11), Moshi 12.5 Hz frames with
  a text/audio delay (B10), FAST DCT+BPE action chunks (B7), 1X dataset at
  2 Hz with 16-frame windows (A6).

---

## E. Do agents learn user-specific preferences over time?

### E1. PersonaMem — "Know Me, Respond to Me"
- arXiv: https://arxiv.org/abs/2504.14225 ; body read at
  https://arxiv.org/html/2504.14225v2 ; code github.com/bowen-upenn/PersonaMem.
- Numbers: 20 personas, "over 180 interaction histories", 10/20/60
  sessions per history, 15-30 turns per session, 15 topics, ~6k in-situ
  query/response pairs, contexts ~32k / 128k / 1M tokens; 7 query types:
  recall facts, suggest new ideas, acknowledge latest preferences, track
  full preference evolution, revisit reasons behind updates,
  preference-aligned recommendations, generalize to new scenarios; at
  128k, "GPT-4.1, o4-mini, GPT-4.5, o1, or Gemini-2.0-Flash score only
  around 50% overall accuracy", Llama-4-Maverick 43%; weakest on
  "Suggest New Ideas", "Provide Preference-Aligned Recommendations",
  "Generalize Reasons to New Scenarios".
- Assessment: frontier models given the full history in-context still
  only track evolving preferences at ~50%. A companion that must *learn*
  the owner cannot rely on "put the history in the prompt"; it needs an
  explicit, updatable preference state and a learning signal.

### E2. LaMP — "When Large Language Models Meet Personalization"
- arXiv: https://arxiv.org/abs/2304.11406 ; body read at
  https://ar5iv.labs.arxiv.org/html/2304.11406 ; site lamp-benchmark.github.io.
- Numbers: 7 tasks (citation identification, movie tagging, product
  rating, news headline, scholarly title, email subject, tweet
  paraphrase); e.g. product rating 20,000 / 2,500 / 2,500, news headlines
  12,527 / 1,925 / 2,376 (train/val/test, user-based split); user-based
  and time-based splits; retrievers BM25, Contriever, Recency, Random;
  retrieval-augmented personalization gives "23.5%" relative average
  improvement fine-tuned and "12.2%" zero-shot (FlanT5-XXL, GPT-3.5).
- Assessment: retrieval of a user's own past items (including a recency
  retriever) is a robust +12-24% lever; the time-based split is the right
  protocol for evaluating whether Parcel's owner model improves with
  interaction time.

---

## F. Grounding the reward signals in the state stream

### F1. Laughter detection (Gillick et al., Interspeech 2021)
- Code https://github.com/jrgillick/laughter-detection (MIT; implements
  "Robust Laughter Detection in Noisy Environments", trained on
  Switchboard with AudioSet annotations; frame threshold default 0.5,
  min_length 0.2 s). No accuracy numbers in the README.
- Assessment: an off-the-shelf, permissively licensed laugh segmenter is
  enough to turn "the joke was funny" into a per-tick state feature
  (laugh probability, onset event) and a delayed reward. It needs
  validation on the XVF3800 array audio, which is on hand.

---

## G. What this means for Parcel

### G1. Design implications
1. Two lanes at two rates, one state stream. GR00T N1 (10 Hz VLM + 120 Hz
   diffusion, 2.2B, 63.9 ms per 16-action chunk on an L40) and Helix (7-9
   Hz 7B VLM -> 200 Hz 80M policy via one latent vector) are the public
   evidence that the semantic/expressive decision rate should be 2-10 Hz
   and the body lane stays at 50 Hz. Parcel already has the 50 Hz
   body-intent lane; the missing piece is a trainable 2-10 Hz behavior
   model that emits body-intent *setpoints*, expression tokens and gaze
   targets, conditioned on the state stream.
2. Represent the state as a fixed per-tick frame of heterogeneous tokens
   (Octo: observation tokenizers + readout tokens + block-causal mask;
   Moshi: parallel streams per modality at a fixed frame rate; TMRoPE:
   absolute-time position IDs). Continuous channels can be vectors (PaLM-E
   MLP-to-embedding, TD-MPC2 zero-pad + mask) rather than text.
3. Keep the visual channel tiny: Delta-IRIS shows 4 tokens per step
   suffices for a world model at 64x64; a frozen V-JEPA 2 ViT-B/L (MIT)
   pooled to 1-4 tokens plus per-entity tokens (LEO: one token per object,
   PaLM-E: referable entity IDs) is the right budget at 5 Hz.
4. "Learn to look back when lost" is a state-feature problem first: the
   stream must carry localization confidence, owner-visible, owner
   bearing/distance, and time-since-owner-seen. With those in the state, a
   DreamerV3/TD-MPC2-class agent can learn the gaze/turn behavior from a
   dense re-engagement reward in MuJoCo; without them no model can.
5. "Learn to chuckle when the joke was funny" is a delayed-reward problem:
   laugh onset (F1) within a 0.5-3 s window after a robot utterance tagged
   as a joke is the reward; the behavior model's chuckle token is the
   action. This is learnable with a bandit/RL head on top of the behavior
   model, and the outcome should be written to memory as a skill outcome
   (Voyager pattern, existing `skill_outcomes.py`).
6. User history must be an explicit structured store, not in-context
   history: PersonaMem ~50% for frontier models at 128k, LoCoMo temporal
   20.3 / adversarial 2.1 for long-context, MemoryAgentBench multi-hop
   conflict resolution <= 7% for *every* memory agent tested. Parcel's
   consent-gated owner model should hold versioned facts and preference
   slots; the LLM reads a retrieved, summarized view of them (Generative
   Agents scoring; A-MEM-style notes at ~1.2k tokens per operation work
   with 1.5B-3B local models).
7. Evaluate with the memory benchmarks' *protocols*, not their datasets:
   time-based splits (LaMP), knowledge-update and abstention questions
   (LongMemEval), conflict-resolution probes (MemoryAgentBench), and a
   1X-style "does the world model rank two policies correctly" check
   before any hardware trial.
8. World models are for the body lane and for evaluation, not for the
   semantic lane: DreamerV3 (MIT, 12M-400M, one A100 per run, single
   config) or TD-MPC2 (MIT, 5M runs on an 8 GB GPU) are trainable on the
   desktop now against MuJoCo Go2 states; Cosmos/Genie 3/1XWM are either
   not real-time (13 s to 4 min per decision) or not available.

### G2. Concrete token schema for a full-duplex behavior model at ~5 Hz
Tick = 200 ms (5 Hz; 2.5 Mimi frames, 5 TMRoPE temporal IDs of 40 ms).
Every tick emits one fixed-layout frame; sparse event tokens are appended
only when they fire. Continuous quantities are 64- or 256-bin uniform or
log bins (RT-2 style) unless a channel is fed as an MLP embedding.

Frame layout (approx. 40-60 tokens per tick):
- [TICK t] absolute tick index (RoPE by wall-clock, 40 ms quantum) +
  [DT bucket] log-bucketed time since previous tick (catches stalls) +
  [HOUR bucket 0-23] [WEEKDAY] (calendar tokens for routines).
- Body/proprio (8-12 tokens, or one MLP embedding of the 50 Hz lane's
  summary): base vx, vy, wz bins; body roll/pitch/yaw/height bins; gait
  mode; battery bucket; contact/fall/e-stop flags; safety-layer override
  active flag (the model must see when the safety layer vetoed it).
- Localization/nav (4-6 tokens): loc-confidence bucket, distance-to-goal
  bucket, path-blocked flag, room/zone ID, "lost" derived flag.
- Vision (4-8 tokens): 1-4 pooled tokens from a frozen V-JEPA 2 ViT-B/L
  (or Delta-IRIS delta tokens if a learned tokenizer is trained), plus
  per-entity slots up to N=4: [ENTITY id] [class owner/person/pet/obstacle]
  [bearing bin 16] [distance bin 8] [facing-robot flag].
- Owner-tracker (4 tokens): owner_visible, owner bearing bin, owner
  distance bin, time-since-owner-seen (log bucket).
- Audio events per tick (5-6 tokens): user-speaking (VAD), robot-speaking
  (duplex state), laugh-probability bucket, loudness bucket, DOA bearing
  bin from the XVF3800, non-speech-event class (door, bark, clap, none).
- Conversation state (4-6 tokens): valence bin, arousal bin, current
  dialogue act (question/joke/command/none), joke-pending window flag,
  last-command intent ID, turn-taking state.
- Memory view (0-32 text tokens, refreshed every ~10 ticks / 2 s, not per
  tick): top-k retrieved memory notes summarized (Generative Agents
  scoring: recency * relevance * importance), plus owner-preference slot
  tokens (e.g. [pref: tricks=high] [pref: touch=low]) from the structured
  store.
- Sparse event tokens (appended when they fire): LAUGH_ONSET, OWNER_LOST,
  OWNER_FOUND, NAME_CALLED, COMMAND(id), SAFETY_VETO, TOUCH, DOOR.
- Optional compact reasoning slot (ECoT lesson, kept to <= 8 tokens):
  [GOAL id] [TARGET entity] [MOOD] emitted before actions; not free-form
  chain-of-thought at 5 Hz.

Action frame per tick (parallel output streams, Moshi-style, with a 1-tick
delay between the semantic stream and the body stream):
- Body-intent stream: 1-second chunk of velocity/pose setpoints,
  FAST-compressed to ~20-30 tokens at 5-20 Hz (or 5 raw ACT tokens per
  tick), replanned every tick; the 50 Hz lane and the safety layer keep
  final authority.
- Expression stream (1-2 tokens): {none, breathe, nod, head-tilt, ear/tail,
  bow, stretch, sit, chuckle, wag, look_around}.
- Gaze stream (1 token): {none, owner, speaker, sound-source, goal,
  scan}.
- Vocal stream: the existing duplex voice tokens (Mimi-style codes) or a
  discrete cue {none, chuckle, hmm, bark}.
Budget: ~50 input + ~30 output tokens per tick -> ~400 tokens/s -> ~24k
tokens/min; a 2-minute working window is ~48k tokens, so the stream must
be compressed by periodic history/summary tokens (HT-Transformer) and
MemGPT-style paging of everything older than ~60 s into the memory store.

### G3. What to do in simulation/training
- Body lane: MuJoCo Go2 with a state vector = the proprio + nav + owner
  channels above (owner as a moving target with visibility raycast); train
  TD-MPC2 (5M) and DreamerV3 (12M) with rewards for re-engagement
  (owner in view within T after OWNER_LOST), command compliance, and
  safety-layer non-veto. Log the state stream in the exact token schema.
- Semantic lane: build a scripted "social simulator" that emits the
  audio/conversation/event channels (joke -> laugh onset with p(funny),
  name-called, etc.) at 5 Hz, and train an Octo-sized (27-93M) block-
  causal transformer to emit expression/gaze/body-setpoint tokens from
  the stream by imitation of authored policies, then fine-tune the
  chuckle and look-back heads with the delayed rewards (bandit/RL).
- Memory: run A-MEM or Mem0 locally (MIT / Apache-2.0) over the owner
  store; evaluate with time-based splits and conflict-resolution probes.
- Evaluation before hardware: 1X-style policy ranking with the learned
  world model; ECoT-style structured-state ablation (does adding the
  owner/audio channels raise re-engagement and chuckle-timing accuracy).

### G4. Load-bearing claims (each rests on the cited primary source)
1. DreamerV3: single config, 150+ tasks, 12M-400M params, one A100 per
   run, MIT code (A1) - single source, but Nature-published and reproduced
   widely.
2. Octo: heterogeneous per-timestep observation tokens + readout tokens +
   block-causal mask at 27M/93M, finetune in <5 h on an A5000 (B3).
3. Moshi: parallel per-stream tokens at 12.5 Hz, 7B, 160/200 ms latency,
   CC-BY weights, MIT/Apache code (B10).
4. GR00T N1 (with Helix as vendor corroboration): 10 Hz semantic + 120 Hz
   motor, 2.2B, 63.9 ms per chunk on an L40 (B8, B9).
5. MemoryAgentBench + PersonaMem: no memory agent above 7% on multi-hop
   conflict resolution; frontier LLMs ~50% on preference tracking at 128k
   (C8, E1).
Single-source cautions: the 1X "70% accuracy -> 90% ranking success" claim
(A6) is from a vendor page whose PDF did not parse; Helix numbers (B9) are
vendor-only; Delta-IRIS 4-tokens-per-frame is one paper with one
benchmark (A4).

### G5. Open questions
- No fetched source trains a behavior model on audio-event + conversation
  state + proprio jointly; the schema above is a synthesis, not a
  replication of a published result.
- Orin throughput for a 27-93M Octo-class model at 5 Hz alongside the
  voice stack is unmeasured here (GR00T's 63.9 ms is on an L40).
- Whether laughter detection from the XVF3800 array is reliable at
  companion distances is untested; the repo gives no accuracy numbers.
- Whether the owner-lost re-engagement behavior transfers from MuJoCo
  (authored visibility model) to a real camera/LiDAR pipeline is
  unknown; the rl-env-readiness audit already refuted the current Go2Env
  as a substrate.
- Memory-system numbers are not comparable across papers (A-MEM's own
  LoCoMo F1 vs Mem0's judge score for A-MEM differ by ~2x), so choose by
  local-model support and license, then measure in-house.
