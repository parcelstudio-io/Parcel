# VLA and behavior foundation models with action-token outputs — evaluated for Parcel

Date: 2026-08-28. Author: research subagent (Fable). Scope: which vision-language-action (VLA) and
behavior-foundation models are realistic to (a) fine-tune on ONE RTX 5000 Ada 32 GB and (b) run on a
Jetson AGX Orin 64 GB, for a Unitree Go2 companion dog whose motion must be driven by conversation and
world state in a full-duplex loop. Every source below was fetched and read during this session; numbers
are quoted from the fetched text. Where a page was too thin (arXiv abstract pages), the full-text HTML or
PDF was fetched instead. Web-search budget ran out after ~25 queries; all remaining reads were direct
fetches, so a few "did anyone benchmark X on Orin" questions remain open (listed at the end).

Reading order if short on time: Section 2 (the two tables), Section 6 (quadruped-specific work),
Section 8 (what this means for Parcel).

---

## 1. Framing: what "action tokens" means in 2026 and why it matters for a dog

Three action representations coexist:

1. **Naive binning as text tokens** (RT-2, OpenVLA, QUART): each action dimension is discretized into
   256 bins and emitted autoregressively. Simple, but one token per dimension per timestep, so slow
   (OpenVLA ~6 Hz on an RTX 4090; RT-2-55B 1-3 Hz on cloud TPUs).
2. **Compressed discrete tokens** (FAST = DCT + BPE over an action chunk; QUART-Online's VQ "Action Chunk
   Discretization"; LAPA/UniAct latent codebooks; Being-H0's GRQ motion tokens; Uni-Mo/QuadFM motion
   latents). These keep the "language model emits actions in the same token stream as text/speech"
   property that a full-duplex design needs, at 1.75-13x fewer tokens than binning.
3. **Continuous heads** (flow matching / diffusion action experts: pi0, pi0.5, pi0.6, GR00T N1.x,
   SmolVLA, Xiaomi-Robotics-0; L1-regression MLP head: OpenVLA-OFT). Fastest at inference (pi0: 73 ms
   for a 50-step chunk on a 4090; GR00T N1: 63.9 ms per 16-step chunk on an L40), but actions are not
   tokens, so they cannot be interleaved with speech tokens inside one decoder — they hang off a
   separate expert conditioned on the VLM's KV cache.

For Parcel the relevant fact is that **every quadruped VLA and every "dual-system" humanoid stack uses
a two-rate split**: a slow semantic model (1-10 Hz) emits command-level actions (velocity, gait, body
pose, or a motion latent), and a fast RL tracking/locomotion policy (50 Hz, trained in sim) executes
them. Parcel's existing 50 Hz body-intent lane, expression layer, and deterministic safety layer are
exactly the lower half of that split; the question is what to put on top.

---

## 2. Summary tables

### 2a. Model facts (all numbers from fetched sources; "—" = not stated in what I read)

| Model | Params | Weights / license | Action representation | Rate | Fine-tune data reported | Fine-tune hardware reported | Inference numbers |
|---|---|---|---|---|---|---|---|
| RT-2 (2023) | 5B / 12B (PaLM-E) / 55B (PaLI-X) | closed | 256-bin text tokens | 55B: 1-3 Hz; 5B: ~5 Hz (cloud multi-TPU) | co-fine-tune on RT-1 data | Google TPU | — |
| OpenVLA (2024) | 7B (Llama-2 + DINOv2/SigLIP) | open, MIT | 256-bin tokens overwriting 256 least-used Llama tokens | ~6 Hz on RTX 4090 bf16 | 10-150 demos/task | LoRA r=32 (1.4% params) 10-15 h on one A100; full FT 8xA100 5-15 h; pretrain 64 A100 x 14 d = 21,500 A100-h | mem bf16 16.8 GB / int8 10.2 / int4 7.0; int4 ~= bf16 success |
| OpenVLA-OFT (2025) | 7B | open, MIT | continuous L1 head, parallel decoding, chunk K=8 (LIBERO) / 25 (ALOHA) | 26x (LIBERO) / 43x (ALOHA) throughput vs OpenVLA; 0.0729 s per 8-step chunk | LIBERO 500 demos; ALOHA 20/30/45/300 demos | 8x A100/H100-80GB, 50-150K steps; repo: "1-8 GPUs with 27-80 GB" | inference ~16-18 GB VRAM; LIBERO 76.5% -> 97.1% |
| pi0 (2024) | 3.3B (PaliGemma 3B + 300M expert) | open in openpi, Apache-2.0 | flow matching, chunk H=50, 10 integration steps | 50 Hz | 5 h (simple) to 100+ h (complex) per task; pretrain 10k+ h, 7 robots, 68 tasks | openpi: LoRA >22.5 GB (4090), full >70 GB | RTX 4090 on-board 73 ms (img 14 + fwd 32 + flow 27); Orin: 920.6 ms (XPU paper), "1.2 s round trip" (openpi issue #826) |
| pi0-FAST (2025) | 3B-class | open in openpi, Apache-2.0 | FAST tokens (DCT+BPE, vocab 1024) autoregressive | ~750 ms per chunk vs ~100 ms diffusion | same as pi0; 5x fewer GPU-hours to train | as pi0 | Thor 8.1 ms/token (forum) |
| pi0.5 (2025) | 3B-class | open in openpi (+LeRobot `pi05`), Apache-2.0 | pretrain: FAST tokens; post-train: flow matching; action dim 18-19 | 50 Hz | ~400 h mobile-manip in ~100 homes on top of pi0 mix; 280k + 80k steps | LeRobot: ~24-40 GB at BS 8; A100-40 GB BS 4 ~4-8 h for 5 epochs of 50 episodes | Thor 44 ms (23 Hz, forum) / ~49 ms TensorRT FP8+NVFP4 (Jetson AI Lab); 4090 95 ms (XPU paper) |
| pi0.6 / pi*0.6 (Nov 2025) | Gemma3-4B + SigLIP 400M + 860M expert (~5B) | NOT open (openpi lists only pi0/pi0-FAST/pi0.5; issue #789 unanswered) | FAST tokens in backbone (knowledge insulation) + flow expert; prompt metadata conditioning | 63 ms per chunk on H100 (5 denoise steps, 3 cams) | RECAP RL post-training: >2x throughput, >=2x lower failure | — | — |
| GR00T N1 (Mar 2025) | 2.2B (Eagle-2 VLM 1.34B) | open, CC-BY paper | flow-matching DiT, chunk 16, K=4 denoise | VLM 10 Hz, actions 120 Hz | 30/100/300 demos post-train; 88 h real + ~827 h neural + 6,500 h sim; 50,000 H100-h pretrain | — | 63.9 ms per 16-action chunk, L40 bf16; real-robot 76.8% vs 46.4% DP |
| GR00T N1.5 / N1.6 | 3B | weights "NVIDIA License" — **non-commercial** (research/evaluation) | flow-matching DiT (N1.6: 32 layers, Cosmos-Reason-2B backbone) | — | tutorials use 3-5 episodes | README: 40 GB+ VRAM recommended (H100/L40; A6000 works, slower) | inference 16 GB+; Orin/Thor install scripts (JetPack 7.2); Thor 41-45 ms (forum) |
| GR00T N1.7 (2026 GA) | 3B (Cosmos-Reason2-2B) | **NVIDIA Open Model License — commercial OK**; code Apache-2.0 | flow-matching DiT, 16 layers | — | as above | as above; single-GPU example BS 32, 2000 steps | H100 TensorRT 27.9 ms / 35.9 Hz |
| SmolVLA (Jun 2025) | 450M (100M expert; SmolVLM-2, first 16 LLM layers) | open (LeRobot, Apache-2.0 code; model card has no license tag) | flow matching, chunk n=50 | async inference: 30% faster, 19 vs 9 cycles | ~50 episodes recommended (25 "not enough"); pretrain 481 datasets, 22.9K episodes, 10.6M frames | 20k steps ~4 h on one A100; ~10-16 GB at BS 8; pretrain ~30k GPU-h on 4 GPUs | ~2 GB inference memory; LIBERO 87.3%; SO-100 real 78.3% |
| Gemini Robotics On-Device (Jun 2025) / On-Device 2 (Jul 30 2026) | — | trusted testers only, no download | — | — | "as few as 50 to 100 demonstrations" | — | On-Device 2: SO101 53.3% vs 6.7% (v1); Dexmate 75.6% vs 33.3% |
| Figure Helix (2025) | S2 7B VLM + S1 80M | closed | S1 continuous, 35-DoF | S2 7-9 Hz, S1 200 Hz | ~500 h teleop | — | onboard "dual low-power embedded GPUs" |
| LAPA (ICLR 2025) | 7B (LWM-Chat-1M) | open, MIT | latent action codebook size 8, seq 4 (8^4) learned from video | — | pretrain 8 H100 x 34 h = 272 H100-h (30-40x cheaper than OpenVLA) | fine-tune "4 80GB-A100 GPUs" | real tabletop 50.1% vs OpenVLA 43.9% |
| UniAct (CVPR 2025) | 0.5B (LLaVA-OneVision-0.5B) | open, **CC BY-NC-SA 4.0** | universal codebook 256 x 128 + per-embodiment MLP heads | — | 1M demos / 28 embodiments pretrain; new robot: 100 demos, 4 A100, 1 h | 8-node DeepSpeed for pretrain | beats OpenVLA-7B on WidowX |
| Being-H0 (Jul 2025) | 1B / 8B / 14B (InternVL3) | open, MIT (released 2025-08-02) | GRQ hand-motion tokens, 8 layers, codebooks 4096 | — | post-train 50-100 teleop trajectories/task; UniHand 150M samples, 1,100+ h | — | — |
| Being-H0.7 (Apr 2026) | 3B | not stated | latent world-action queries K=16, chunk T=20 | "3-4 ms/step" | — | — | LIBERO 99.2%, RoboCasa 62.1% |
| Xiaomi-Robotics-0 (Feb 2026) | 4.7B (Qwen3-VL-4B + DiT) | open, Apache-2.0 | flow matching, training-time RTC with Lambda-shape mask | 80 ms on RTX 4090 | ~200M timesteps + 80M VL samples pretrain; in-house 338-400 h/task | "consumer-grade GPUs" (VRAM unstated) | LIBERO 98.7% |
| CrossFormer (2024) | 130M | open | 4 heads incl. quadruped joint positions (12-dim, 1 action @ 20 Hz) | 4-20 Hz per head | 900K traj / 20 embodiments | TPU v5e-256, 47 h | Go1 normalized reward 1.0 |
| ELLSA (Oct 2025, rev Apr 2026) | Llama-3.1-8B speech expert + Emu3-Base action expert (LoRA r=256 each) + CosyVoice2-0.5B | open, Apache-2.0, checkpoints tsinghua-ee/ELLSA | **FAST action tokens interleaved with speech/text in a 1 s time block** | 1 block/s: 8 text tokens + 1 s speech + 1 s actions | LIBERO 3,386 + 1,693 defective-instruction samples (+ ~1.2M speech samples) | — | A100: 854 ms speech-to-speech, 786 ms speech-to-action per 1 s block; LIBERO 89.4%; speaking-while-acting 93.3/96.6/86.1/73.2 |

### 2b. Quadruped-specific systems

| System | Semantic model | Action space | Rates | Robot / compute | Data | Result |
|---|---|---|---|---|---|---|
| QUAR-VLA / QUART (ECCV 2024) | Fuyu-8B | 12-dim: vx, vy, wz, gait (3), freq, height, pitch, foot width, foot height, terminate; 256 bins | 2 Hz | WR-2 quadruped | QUARD 259K sim + 3K real episodes, 7 task types | seen-task success 0.66/0.60/0.53/0.41/0.32/0.12 |
| QUART-Online (Dec 2024) | Fuyu-8B | VQ Action Chunk Discretization (512-dim codebook, Nq=2), chunk 1/5/10 | **50 Hz** (vs 2 Hz) | Isaac Gym | QUARD | avg success 0.37-0.52 -> 0.68-0.79 (+65%) |
| MoRE (ICRA 2025) | Fuyu-8B + mixture of LoRA experts, trained as Q-function (offline RL) | same 12-dim | — | **Unitree Go2** + RealSense D435 | 1,822,405 QUARD + 440,732 sub-optimal QUARD-Auto | 0.60 vs QUART 0.44 |
| NaVILA (RSS 2025) | VILA-8B (Llama3) | mid-level language ("move forward 75 cm", "turn right 30 deg") parsed by regex | VLA ~1 Hz on RTX 4090 (W4A16: 8.6 GB, +40%); loco 50 Hz | Go2, H1, Booster T1; PPO in Isaac Lab (60K FPS on 4090) | R2R/RxR + 2K YouTube touring videos -> 20K traj | real 88% on 25 instructions; R2R val-unseen 54.0%; Apache-2.0, ckpt a8cheng/navila-llama3-8b-8f |
| LocoVLM (Feb 2026) | GPT-4o builds 300-entry skill DB offline; BLIP-2 on RTX 3070 Ti laptop grounds scene (<100 ms) | style-conditioned gait policy (pronk/trot/pace/bound/gallop; period T, phase offsets) | 50 Hz | Unitree Go1 + Jetson Xavier NX | — | 87% instruction following |
| QuadFM (Mar 2026) | MotionGPT3 (VAE + diffusion) text-to-motion | motion latent -> RL tracking policy | generator 2 Hz, tracker 50 Hz; **<500 ms end-to-end on Go2 X + NVIDIA Orin** (+~0.5 s cloud ASR) | Unitree Go2 X; trained on one AMD MI308X ~48 h | 11,784 clips, 20.27 h, 3.64M frames @50 Hz, 35,352 texts; includes "Happy (Dancing, Excited)", "Sad (Cautious)", greeting, begging | human eval 7.98/9 alignment; CC BY 4.0; GitHub placeholder "will be released soon" (Apache-2.0) |
| Uni-Mo (Jun 2026) | LLM prompts -> Wan2.2 video diffusion -> ViTPose 3D lift -> PPO tracker | 19-D state (root pos, quat, 12 joints) | 50 Hz PD | Unitree Go2; PPO 4,096 envs on one RTX 3090, <=3,000 it/motion; video model 56 H20 | Quad-Imaginarium 7,488 motions, 18.5 h | sim 97.6%; real **96.7% over 392 motions x 5**; CC BY 4.0 dataset |
| OpenGo (Apr 2026) | LLM picks skill+parameters from validated library | scripted skills | — | Go2 | — | no VLA/learned motion |
| CrossFormer | 130M transformer | Go1 12 joint positions @20 Hz | 20 Hz | Go1 | 900K traj | reward-normalized 1.0 |

### 2c. Behavior foundation models (non-VLA, whole-body)

| Model | Size | License | Sim / robot | Data | Notes |
|---|---|---|---|---|---|
| Meta Motivo (ICLR 2025) | S: 24.5M; M-1: 288M | CC BY-NC 4.0 | HumEnv (SMPL humanoid) | observation-only mocap | prompt by reward / goal / tracking; not on hardware |
| BFM-Zero (Nov 2025) | actor 31.9M (6-block, 2048), latent 256 | not stated | IsaacLab 200 Hz sim / 50 Hz control, 1024 envs, 192M steps | LAFAN1 4,040 motions | zero-shot tracking/goal/reward on real Unitree G1 at 50 Hz |

---

## 3. Source-by-source notes

### 3.1 OpenVLA — https://arxiv.org/abs/2406.09246 , full text https://arxiv.org/html/2406.09246 , card https://huggingface.co/openvla/openvla-7b
- 7B; Llama-2 + fused DINOv2/SigLIP; trained on 970k OXE episodes.
- Action tokenization: "discretizes continuous robot actions into 256 bins per dimension, overwriting the 256 least used tokens in the Llama tokenizer's vocabulary" (Sec 3.2).
- Compute: "a cluster of 64 A100 GPUs for 14 days, or a total of 21,500 A100-hours".
- Inference: "6Hz on one NVIDIA RTX 4090 GPU (without compilation, speculative decoding...)" bf16. Memory bf16 16.8 GB, int8 10.2 GB, int4 7.0 GB; "4-bit quantization results in similar performance as bfloat16".
- LoRA rank 32 "only 1.4% of the parameters", "within 10-15 hours on a single A100 GPU"; full FT "8 A100s for 5-15 hours"; fine-tune sets "10-150 demonstrations of a target task".
- License MIT (model card).
- Assessment: the canonical open action-token VLA, but 7B autoregressive-per-dimension is the slowest family; ~6 Hz on a 4090 means well under 2 Hz on Orin (no primary Orin number found; do not cite the ~2 Hz blog figure).

### 3.2 OpenVLA-OFT — https://arxiv.org/abs/2502.19645 , full https://arxiv.org/html/2502.19645 , repo https://github.com/moojink/openvla-oft
- Recipe: parallel decoding (bidirectional mask, empty action embeddings), action chunking, continuous L1-regression MLP head, FiLM.
- LIBERO 76.5% -> 97.1%; throughput 26x (K=8); ALOHA K=25, 43x; LIBERO latency "0.0729 sec" per chunk.
- ALOHA demos per task: 20 (fold shorts), 30 (fold shirt), 45 (scoop), 300 (put X in pot). ALOHA 25 Hz.
- Training: 8x A100/H100-80GB, 50-150K steps. Repo: "Between 1-8 GPUs with 27-80 GB, depending on the desired training setup"; inference ~16 GB (LIBERO) / ~18 GB (ALOHA). MIT.
- Without FiLM "language following drops to 33%" on language-dependent ALOHA tasks — relevant for Parcel where language is the whole point.
- Assessment: proves that swapping token heads for chunked continuous heads gives 26-43x speedups on the same 7B backbone; but 27 GB minimum per GPU makes a 32 GB card marginal for training.

### 3.3 openpi / pi0 / pi0.5 / pi0-FAST — https://github.com/Physical-Intelligence/openpi ; pi0 https://arxiv.org/html/2410.24164 ; pi0.5 https://arxiv.org/html/2504.16054 ; FAST https://arxiv.org/html/2501.09747
- openpi README: models pi0, pi0-FAST, pi0.5; Apache-2.0; GPU table: inference "> 8 GB" (RTX 4090), LoRA fine-tune "> 22.5 GB" (RTX 4090), full fine-tune "> 70 GB" (A100-80/H100); "pre-trained on 10k+ hours of robot data"; PyTorch backend since Sep 2025; no Jetson note.
- pi0 paper: PaliGemma 3B + 300M expert = 3.3B; H=50 chunk; "control robots at frequencies of up to 50 Hz"; 10 integration steps; 903M timesteps in-house (106M single-arm, 797M dual-arm); fine-tuning "the simplest of the tasks necessitating only 5 hours and the most complex tasks using 100 or more hours"; Table I on RTX 4090: on-board 73 ms (image 14, forward 32, 10 flow steps 27), off-board 86 ms. pi0-small 470M ablation.
- pi0.5 paper: pretraining "next-token prediction of text, object locations, and FAST encoded action tokens"; post-training with flow matching; 280k + 80k steps; "about 400 hours of data of mobile manipulators ... in about 100 different home environments"; 50 Hz; action dim 18-19; unseen-home tasks lasting 2-5 min.
- FAST paper: DCT then scale-and-round then BPE; Table I: BridgeV2 5 Hz 35->20 tokens (1.75x), DROID 15 Hz 105->29 (3.6x), bussing 20 Hz 140->28 (5.0x), T-shirt 50 Hz 700->53 (13.2x); FAST+ trained on ~1M 1-second chunks; "5x fewer GPU hours for training than the pi0 model"; inference "approximately 750ms of inference time per chunk" vs ~100 ms for diffusion; only two hyperparameters (rounding scale 10, BPE vocab 1024), usable "in three lines of code" via HF AutoProcessor.
- Assessment: pi0.5 is the strongest open general VLA; on our 32 GB card it is LoRA-only (>22.5 GB); on Orin the only primary numbers are 920.6 ms (XPU paper, pi0) and a "1.2 s round trip" (issue #826), i.e. ~1 Hz, vs 23 Hz on Thor. FAST itself is the right tokenizer for Parcel's ACT-token codec regardless of backbone.

### 3.4 pi0.6 — model card https://website.pi-asset.com/pi06star/PI06_model_card.pdf (Nov 17 2025); blog https://www.pi.website/blog/pistar06 ; issue https://github.com/Physical-Intelligence/openpi/issues/789
- "vision-language backbone is initialized from the Gemma3 4B model, and the action expert ... about 860M parameters"; up to 4 images at 448x448; knowledge insulation (backbone predicts FAST tokens; expert gradient does not flow back); "can optionally take in conditioning metadata in the prompt that further modulates how the task is performed"; "With 5 denoising steps and 3 camera inputs, pi0.6 takes 63ms to produce an action chunk on a single H100 GPU."
- pi*0.6 blog: "a 5B-parameter vision-language model, augmented with an action expert"; RECAP "more than doubles the throughput on some of the hardest tasks" and "decrease failure rates by 2x or more".
- Not in openpi; issue asking for release has no maintainer answer. Treat as closed.

### 3.5 GR00T N1 / N1.5 / N1.6 / N1.7 — paper https://arxiv.org/html/2503.14734 ; repo https://github.com/NVIDIA/Isaac-GR00T ; cards https://huggingface.co/nvidia/GR00T-N1.5-3B , https://huggingface.co/nvidia/GR00T-N1.6-3B (+ raw LICENSE), https://huggingface.co/nvidia/GR00T-N1.7-3B ; blog https://developer.nvidia.com/blog/building-generalist-humanoid-capabilities-with-nvidia-isaac-gr00t-n1-6-using-a-sim-to-real-workflow/ ; license https://www.nvidia.com/en-us/agreements/enterprise-software/nvidia-open-model-license/
- N1 paper: 2.2B total, Eagle-2 VLM 1.34B; "vision-language module runs at 10Hz on NVIDIA L40", action DiT at 120 Hz; chunk 16; K=4 denoising; "inference time for sampling a chunk of 16 actions is 63.9ms on an L40 GPU using bf16"; data 88 h real teleop + ~827 h neural trajectories + 6,500 h sim + human egocentric video; ~50,000 H100 GPU-hours; post-training with 30/100/300 demos; real robot 76.8% vs 46.4% Diffusion Policy.
- Repo (N1.7 GA; N1.6 on `n1d6` branch): "3B params"; code Apache 2.0, weights NVIDIA Open Model License; "Fine-tuning: 1 or more GPUs with 40 GB+ VRAM recommended ... Other hardware (e.g., A6000) works but may require longer training time"; "Inference: 1 GPU with 16 GB+ VRAM (e.g., RTX 4090, L40, H100, Jetson AGX Thor/Orin, DGX Spark)"; `scripts/deployment/orin/install_deps.sh` (JetPack 7.2, CUDA 13.2, Python 3.12); N1.7 DiT 16 layers vs 32 in N1.6; tutorials fine-tune on 3-5 episodes; single-GPU example `--global-batch-size 32 --max-steps 2000`; no LoRA flags documented; no latency table.
- N1.7 card: Cosmos-Reason2-2B backbone; "ready for commercial/non-commercial use"; H100 TensorRT "27.9 ms" / "35.9 Hz".
- N1.6 raw LICENSE: "NVIDIA License" — "only may be used or intended for use non-commercial[ly]" (research/evaluation), NVIDIA excepted. N1.5 card likewise non-commercial. So only N1.7 weights are commercially usable.
- N1.6 blog: Cosmos-Reason-2B variant with native resolution; 2x larger 32-layer DiT; state-relative actions; data includes GR-1, Unitree G1, YAM, Agibot, DROID, BEHAVIOR, RoboCasa.
- Assessment: the only open 3B-class VLA with an official Orin deployment script; no Orin latency published (Thor: 41-45 ms per forum). 32 GB is below the 40 GB recommendation for fine-tuning, so expect small batch + gradient checkpointing or freezing the backbone; untested here.

### 3.6 SmolVLA — https://arxiv.org/html/2506.01844 ; docs https://huggingface.co/docs/lerobot/smolvla ; async docs https://huggingface.co/docs/lerobot/async ; HW guide https://huggingface.co/docs/lerobot/hardware_guide ; card API https://huggingface.co/api/models/lerobot/smolvla_base ; repo https://github.com/huggingface/lerobot
- "450 million parameters, with approximately 100 million dedicated to the action expert"; uses "first 16 layers" of the SmolVLM-2 LLM; flow matching "chunks of n=50 actions"; 481 community datasets, 22.9K episodes, 10.6M frames; pretrain 200k steps, global batch 256, ~30k GPU-hours on 4 GPUs; SO-100 real 78.3% (75/90/70); LIBERO 87.3%; async: "approximately 30% faster", 19 vs 9 pick-place cycles.
- Docs: "We recommend recording ~50 episodes"; "We tried similar dataset with 25 episodes, and it was not enough"; "20k steps will roughly take ~4 hrs on a single A100"; RTC option "use when running on low power hardware".
- Async docs: "PI0 occupies 14GB of memory at inference time, while SmolVLA requires only ~2GB"; `actions_per_chunk` 50, `chunk_size_threshold` 0.5-0.7.
- Hardware guide: SmolVLA ~10-16 GB peak at BS 8 AdamW; pi0/pi0_fast/pi05/xvla ~24-40 GB ("24 GB tight at BS 1"); groot ~24-40 GB; A100-40 GB pi0/pi05 BS 4 ~4-8 h for 5 epochs of ~50 episodes; pi05 on 4xH100 5000 steps 3h41m with gradient checkpointing; SmolVLA on L4 24 GB BS 4 ~3-6 h.
- HF API: total 450,046,176 params; no license tag on the model; LeRobot code Apache-2.0. LeRobot also ships Pi0, Pi0Fast, Pi0.5, GR00T N1.7, XVLA, EO-1, MolmoAct2, WALL-OSS, EVO1.
- Assessment: the only VLA in this list that is comfortably trainable on 32 GB with headroom for Parcel's other local models and that has a 2 GB inference footprint; no published Orin latency, but the XPU paper names Orin the cost/energy-optimal device for SmolVLA-class models.

### 3.7 Edge/Orin latency evidence
- XPU characterization (SJTU, Apr 2026) https://arxiv.org/pdf/2604.24447 : hardware table Orin 42 TFLOP/s, 64 GB, 204 GB/s; Thor 258 TFLOP/s, 128 GB, 273 GB/s. pi0 latency: RTX 4090 102.3 ms (compiled 35.2 ms, 28.41 Hz), Thor 246 ms (compiled 163 ms, 6.13 Hz), **AGX Orin 920.6 ms**, B60 306.5 ms, Ascend 310P 818 ms. V-AEFusion on Orin 920 -> 806 ms (1.14x). pi0.5-droid on Franka 95 ms baseline (4090). Findings: "the Orin is optimal for small consumers like SmolVLA" under cost-energy; energy priority "selects Jetson Thor, followed by AGX Orin"; two-phase pattern — compute-bound VLM then memory-bound action expert; on Orin "combined computational demand of VLM and Action Expert exceeds the hardware's capacity limit".
- Jetson AI Lab pi0.5 on Thor https://www.jetson-ai-lab.com/tutorials/openpi_on_thor/ : PyTorch BF16 ~132 ms; TensorRT FP8+NVFP4 ~49 ms (~2.7x); weights ~6 GB+; Orin not covered.
- NVIDIA forum (user post, May 2 2026) https://forums.developer.nvidia.com/t/real-time-inference-on-thor-rtx-pi0-5-gr00t-n1-6-1-7-thor-23-hz-rtx-5090-50-80hz/368788 : pi0.5 Thor 44 ms (23 Hz), 5090 17.58 ms (57 Hz); pi0 Thor 46 ms; GR00T N1.6 Thor 45/41 ms (T=50/16), 5090 13.08/12.53 ms; pi0-FAST Thor 8.1 ms/token. Not peer reviewed; no Orin rows.
- openpi issue #826 https://github.com/Physical-Intelligence/openpi/issues/826 : pi0.5-droid on Jetson Orin "1.2s round trip on average" with a "hacky" pipeline.
- LiteVLA-Edge https://arxiv.org/html/2603.03380v1 : SmolVLM-256M backbone, Q4_K_M GGUF, "mean end-to-end latency of 150.5 ms" on "NVIDIA Jetson AGX Orin (64GB)"; no success-rate comparison.
- vla.cpp https://arxiv.org/abs/2606.08094 : 7 architectures, BitVLA in 1.3 GiB, runs on an 8 GB embedded module; no per-device ms in abstract.
- Assessment: On Orin, 3B-class flow VLAs are ~1 Hz today unless someone ports the Thor TensorRT path; sub-500M models are the only ones with demonstrated sub-200 ms Orin latency. Thor is 5-20x faster than Orin on these workloads — a hardware decision, not a software one.

### 3.8 Latent / universal action spaces
- LAPA https://arxiv.org/html/2410.11758 , repo https://github.com/LatentActionPretraining/LAPA : VQ-VAE latent actions, vocab 8, length 4; backbone LWM-Chat-1M 7B; pretrain "8 H100 GPUs for 34 hours ... 272 H100-hours", "30-40 times more efficient" than OpenVLA's 21,500 A100-h; real tabletop 50.1% vs 43.9%; fine-tune used "4 80GB-A100 GPUs"; MIT.
- UniAct https://arxiv.org/html/2501.10105 , repo https://github.com/2toinf/UniAct : codebook 256x128; LLaVA-OneVision-0.5B; 1M demos / 28 embodiments; new-embodiment adaptation "100 demonstrations ... 4 A100 GPUs ... 1 hours"; CC BY-NC-SA 4.0.
- Being-H0 https://arxiv.org/html/2507.15597 , repo https://github.com/BeingBeyond/Being-H0 : InternVL3 1B/8B/14B; UniHand 150M samples, 1,100+ h, 11 sources; GRQ 8-layer, codebooks 4096, "millimeter-level" reconstruction; post-train 50-100 trajectories per task; MIT; released 2025-08-02.
- Being-H0.7 https://arxiv.org/html/2605.00078v1 : 3B latent world-action model; K=16 queries, T=20, H=4; LIBERO 99.2%; RoboCasa 62.1%; "3-4 ms/step" with Universal Async Chunking; weights not mentioned.
- Assessment: latent-action pretraining from video is the cheapest route to a pretrained action prior (272 H100-h), and Being-H0-1B is the smallest MIT-licensed VLA with a motion tokenizer; but all are hand/manipulation-centric — none has a quadruped or body-language action space.

### 3.9 Speech-conditioned and full-duplex VLAs
- VLAS (ICLR 2025) https://arxiv.org/html/2502.13508 : LLaVA + Whisper; 3-stage speech tuning; SQA 185K samples / 1,152 voices; CSI 194K / 500 voices; CALVIN ABCD/D 94.2/84.0/73.2/64.3/54.6; Voice RAG 86.5% vs 19.2%; 2.50 Hz vs 3.60 Hz text baseline. Half-duplex (speech in, action out).
- ELLSA (ByteDance/Tsinghua) https://arxiv.org/pdf/2510.16756 , repo https://github.com/bytedance/SALMONN/tree/ELLSA : "first full-duplex, end-to-end model that simultaneously perceives and generates across vision, text, speech, and action"; SA-MoE routes modalities to experts fused by shared attention; speech expert = streaming Mamba encoder + Llama-3.1-8B-Instruct (LoRA r=256); action expert = Emu3-Base with "the final 1,024 token IDs ... replaced with FAST tokens", Emu3-VisionTokenizer; speech synthesizer CosyVoice2-0.5B; "operates on a one-second time block, within which it processes one second of speech input and a single video frame, generates eight tokens of text output (or a single <silence> token ...), and produces one second of speech and action output"; LIBERO 89.4% (90.8/95.8/86.4/84.4) beating pi0-FAST 85.5%; speaking-while-acting manipulation 93.3/96.6/86.1/73.2; action barge-in 94.3%; per-block latency on A100: 854 ms S2S, 786 ms S2A at 1 s blocks; 455/428 ms at 0.48 s blocks (but action success drops 84-94% -> 71-85%); training robot data only 3,386 LIBERO + 1,693 defective-instruction samples; Apache 2.0; checkpoints tsinghua-ee/ELLSA.
- Assessment: ELLSA is the direct architectural template for the owner's ask (listen/speak/act at once, action barge-in). Its two 8B experts and ~800 ms/block on an A100 rule out Orin as-is; the transferable idea is the 1 s time-block schedule with FAST action tokens sharing the decoder with speech tokens.

### 3.10 Quadruped VLAs and motion generators (details in table 2b)
- QUAR-VLA https://arxiv.org/html/2312.14457 ; QUART-Online https://arxiv.org/html/2412.15576 ; MoRE https://arxiv.org/html/2503.08007 ; NaVILA https://arxiv.org/html/2412.04453 (+ https://github.com/AnjieCheng/NaVILA , https://github.com/yang-zj1026/legged-loco MIT); LocoVLM https://arxiv.org/html/2602.10399 ; QuadFM https://arxiv.org/html/2603.24021v1 (+ https://github.com/GaoLii/QuadFM); Uni-Mo https://arxiv.org/html/2606.28237 ; OpenGo https://arxiv.org/html/2604.01708v1 ; CrossFormer https://arxiv.org/html/2408.11812 .
- Key quotes: QUART "could get 2Hz"; QUART-Online "50Hz" with "fl = lac x fm" (controller freq = chunk length x MLLM freq); MoRE trains the VLA "as a Q-function" on "mixed-quality data" and reaches 0.60 vs 0.44 on a real Go2; NaVILA VLA "roughly 1 FPS" on one RTX 4090, real-world "88% success rate on 25 instructions"; QuadFM "End-to-end latency <500 ms" on "Unitree Go2 X ... NVIDIA Orin" with 2 Hz generator / 50 Hz tracker; Uni-Mo "96.7% deployment success rate" on a real Go2 across 392 motions, PPO tracker trained with "4,096 parallel environments on one NVIDIA 3090 GPU".
- Assessment: this is the body of work Parcel should copy. The action interface that every quadruped VLA converged on is a 12-dim command vector (3 velocities + gait/body-pose parameters + terminate) or a motion latent, at 2 Hz semantic / 50 Hz tracking. QuadFM is the first dataset with explicitly emotion-labelled dog motions on a Go2, but weights and data are not yet public.

### 3.11 Closed/reference systems
- RT-2 https://arxiv.org/html/2307.15818 , https://robotics-transformer2.github.io/ : 256 bins; "55B ... 1-3 Hz", "5B ... around 5 Hz" on a multi-TPU cloud service; ~6k trials; emergent 62% vs 32% RT-1. Closed.
- Figure Helix https://www.figure.ai/news/helix : S2 "7B-parameter open-source, open-weight VLM" at 7-9 Hz; S1 "80M parameter cross-attention encoder-decoder transformer" at 200 Hz; 35-DoF; "~500 hours"; "dual low-power-consumption embedded GPUs" onboard; S2 async, S1 in the control loop with a training-time temporal offset matching deployed latency. Closed.
- Gemini Robotics On-Device https://deepmind.google/blog/gemini-robotics-on-device-brings-ai-to-local-robotic-devices/ (Jun 24 2025): "as few as 50 to 100 demonstrations"; ALOHA, Franka FR3, Apollo; MuJoCo SDK; trusted testers. On-Device 2 card https://deepmind.google/models/model-cards/gemini-robotics-on-device-2/ (Jul 30 2026): "Distributed only to Trusted Testers"; SO101 53.3% vs 6.7%; Dexmate 75.6% vs 33.3%; "limited in its ability to ... control high-degree-of-freedom robots". Not obtainable for Parcel.
- Xiaomi-Robotics-0 https://arxiv.org/html/2602.12684 , https://github.com/XiaomiRobotics/Xiaomi-Robotics-0 : Qwen3-VL-4B + DiT, 4.7B; training-time RTC with "Lambda-shape attention mask"; 80 ms on RTX 4090; LIBERO 98.7%; Apache 2.0; released Feb 2026, post-training code Apr 27 2026.
- A1 truncated VLA https://arxiv.org/abs/2604.05672 (Apr 2026): early-exit flow matching, "up to 72% lower per-episode latency", full training stack released; RoboChallenge 29.00% vs pi0 28.33%.
- Behavior foundation models: Meta Motivo https://arxiv.org/abs/2504.11054 , https://github.com/facebookresearch/metamotivo (24.5M / 288M, CC BY-NC 4.0, HumEnv); BFM-Zero https://arxiv.org/html/2511.04131 (latent 256, actor 31.9M, LAFAN1 4,040 motions, IsaacLab 1024 envs, 192M steps, real G1 at 50 Hz). Neither is a quadruped model, but BFM-Zero shows a promptable whole-body latent policy trained purely in sim transfers to real hardware at 50 Hz — the same recipe Uni-Mo/QuadFM use for Go2.

---

## 4. Which of these can be fine-tuned on one RTX 5000 Ada 32 GB?

Confidence levels: HIGH = a vendor/paper number puts it inside 32 GB; MEDIUM = at the edge, needs
small batch / LoRA / checkpointing; LOW = published requirement exceeds 32 GB.

| Model | Verdict | Basis |
|---|---|---|
| SmolVLA 450M | **HIGH** | ~10-16 GB at BS 8; 20k steps ~4 h on A100; single-GPU by design |
| pi0 / pi0.5 (openpi LoRA) | **MEDIUM** | LoRA ">22.5 GB" on a 4090; LeRobot: 24-40 GB, "24 GB tight at BS 1"; full FT >70 GB impossible |
| pi0-FAST (LoRA) | MEDIUM | same envelope as pi0 |
| OpenVLA-7B (LoRA) | MEDIUM | paper: single A100 (80 GB) 10-15 h; OFT repo: "27-80 GB" per GPU; int4 base is 7 GB but LoRA training on quantized base is not documented in the fetched sources |
| GR00T N1.7 3B | **MEDIUM-LOW** | "40 GB+ VRAM recommended"; A6000 (48 GB) "works but may require longer training time"; no LoRA flags documented |
| Being-H0-1B | MEDIUM | 1B InternVL3-class, MIT; no VRAM figure fetched |
| UniAct-0.5B | MEDIUM (license NC) | 0.5B; adaptation quoted on 4 A100 for 1 h; CC BY-NC-SA |
| Xiaomi-Robotics-0 4.7B | LOW-MEDIUM | "consumer-grade GPUs" claimed, VRAM unstated |
| LAPA-7B | LOW | fine-tune "4 80GB-A100 GPUs" |
| ELLSA (8B + 8B experts) | LOW | LoRA r=256 on two 8B models; hardware not stated but >32 GB is near-certain |
| Being-H0-8B/14B, OpenVLA full FT, pi0.x full FT | LOW | published numbers exceed 32 GB |
| RT-2, Helix, Gemini On-Device, pi0.6 | N/A | closed |

## 5. Which can run on Jetson AGX Orin 64 GB?

| Model | Evidence | Practical verdict |
|---|---|---|
| SmolVLA | ~2 GB inference; Orin named cost/energy-optimal for SmolVLA-class (XPU paper); LiteVLA-Edge SmolVLM-256M 150.5 ms on Orin 64 GB | **YES** (expect a few Hz; no primary ms number for SmolVLA itself) |
| pi0 / pi0.5 | 920.6 ms (XPU paper); 1.2 s round trip (issue #826); weights ~6 GB | runs, ~1 Hz; needs a TensorRT port (Thor path exists: 49 ms) |
| GR00T N1.6/N1.7 | official `orin/install_deps.sh`; "16 GB+" inference; Thor 41-45 ms | runs; Orin latency unpublished, expect several hundred ms |
| OpenVLA-7B | 16.8 GB bf16 / 7 GB int4; 6 Hz on 4090 | fits memory; expect ~1 Hz class (no primary Orin figure) |
| NaVILA-8B | W4A16 8.6 GB; ~1 FPS on 4090 | fits memory; <1 Hz on Orin (inference in paper was off-board 4090) |
| QuadFM generator + tracker | "<500 ms end-to-end" on Go2 X + Orin | YES (weights not public yet) |
| 50 Hz RL tracking policies (Uni-Mo MLP 512/256/128, NaVILA legged-loco, BFM-Zero 31.9M) | trivially small | YES |
| ELLSA | 786-854 ms per 1 s block on an A100 | NO as published |

---

## 6. What is actually trainable toward "chuckle if the joke was funny" and "look back when lost"

These are not manipulation demos; they are state-conditioned social behaviors with a delayed, sparse
reward (owner laughed / owner was found). The literature gives three ingredients:

1. **A pretrained action prior with a tokenized command action space.** Every quadruped VLA uses a
   ~12-dim command vector; QUART-Online shows VQ chunking of that vector lets an 8B MLLM drive a
   50 Hz controller. FAST (DCT+BPE, two hyperparameters, "three lines of code") is the drop-in
   replacement for Parcel's naive velocity-bin codec and is what pi0.5, pi0.6 and ELLSA use inside the
   language decoder.
2. **A small supervised warm start.** The field's fine-tuning quantum is 50-100 episodes (SmolVLA ~50,
   Gemini On-Device 50-100, Being-H0 50-100, GR00T 30-300, OpenVLA 10-150, UniAct 100). For Parcel these
   can be scripted in MuJoCo (owner agent tells joke -> dog chuckle token; owner leaves FOV -> dog
   look-back + re-approach) rather than teleoperated.
3. **Offline RL / advantage conditioning on autonomously collected mixed-quality rollouts.** MoRE
   trains the quadruped VLA "as a Q-function" on 440K sub-optimal trajectories and lifts Go2 success
   0.44 -> 0.60; pi*0.6's RECAP lifts throughput >2x. The reward for "funny" must come from an external
   signal (owner laughter detector / LLM judge / explicit consent-gated feedback in the owner model);
   for "lost" it is geometric (owner re-acquired in camera/LiDAR within N seconds).

World-state conditioning is already a first-class input in pi0.6 ("conditioning metadata in the
prompt") and ELLSA (speech + frame + text history in one stream); Parcel's owner-model facts and
emotional state can be serialized as prompt metadata tokens the same way.

---

## 7. Licensing summary

Open and permissive: openpi pi0/pi0-FAST/pi0.5 (Apache-2.0); OpenVLA and OpenVLA-OFT (MIT); LeRobot/SmolVLA
(Apache-2.0 code); Being-H0 (MIT); LAPA (MIT); Xiaomi-Robotics-0 (Apache-2.0); ELLSA (Apache-2.0);
NaVILA (Apache-2.0; legged-loco MIT); GR00T N1.7 weights (NVIDIA Open Model License, commercial OK).
Non-commercial: GR00T N1.5/N1.6 weights ("NVIDIA License"); UniAct (CC BY-NC-SA 4.0); Meta Motivo (CC BY-NC 4.0).
Closed / gated: RT-2, Helix, Gemini Robotics On-Device 1/2 (trusted testers), pi0.6.
Datasets: QuadFM and Quad-Imaginarium papers are CC BY 4.0; QuadFM GitHub is a placeholder ("will be released soon").

---

## 8. What this means for Parcel

1. **Do not put a 3-7B VLA in the 50 Hz loop on Orin.** Primary numbers put pi0 at ~0.9-1.2 s and
   OpenVLA at ~6 Hz on a 4090 (so slower on Orin). Keep the existing 50 Hz body-intent lane and safety
   layer as the "System 1" and add a 1-2 Hz semantic layer above it — exactly the QUART (2 Hz),
   QuadFM (2 Hz generator), NaVILA (1 Hz), GR00T (10 Hz VLM / 120 Hz action) and Helix (7-9 Hz / 200 Hz)
   pattern.
2. **Replace the naive velocity-bin ACT codec with FAST tokens over a QUART-style 12-dim command
   chunk (velocities + gait + body pose + expression id).** This keeps actions as tokens (so they can
   share a decoder with speech tokens as in ELLSA/pi0.5 pretraining) while cutting token count 2-13x.
   If the semantic layer is a flow-matching model instead, use QUART-Online's VQ chunk codebook as the
   interface to the intent lane.
3. **Train the semantic layer on SmolVLA first (450M, Apache, ~10-16 GB, ~4 h per 20k steps, ~2 GB
   at inference).** It is the only VLA that fits the 32 GB card with headroom for Parcel's other local
   models and has an Orin-class footprint. Replace SmolVLA's camera+proprio inputs with Parcel's world
   state (camera, LiDAR-derived owner pose, ASR text, owner-model facts, affect) and its 6-DoF arm action
   head with the 12-dim command chunk. pi0.5-LoRA (>22.5 GB) is the upgrade path if SmolVLA plateaus;
   GR00T N1.7 (commercial license, official Orin script) is the alternative if the team accepts a
   40 GB-class training box.
4. **Full duplex = time-block scheduling, not one giant model.** ELLSA's 1 s block (1 s audio in,
   1 frame, 8 text tokens out, 1 s speech + actions out) is the schedule to copy; its 8B+8B experts
   are not. Parcel's split — hosted Realtime speech API within the $300/mo budget for the speech
   expert, local SmolVLA-class action expert on Orin, shared context via the conversation state — is the
   deployable version. Action barge-in (ELLSA: 94.3%) maps directly to the reaction arbiter.
5. **Simulation plan.** (a) Build the 50 Hz tracking/locomotion policy with the Uni-Mo/NaVILA recipe
   (PPO, 4,096 envs on one consumer GPU, MuJoCo/Isaac Lab); (b) author or import an expressive-motion
   library (QuadFM lists exactly the affective categories Parcel needs: happy/excited, sad/cautious,
   greeting, begging, stretching) and give each motion a token id; (c) script an owner agent that tells
   jokes and wanders out of view, log 50-100 episodes per behavior for the supervised warm start;
   (d) run MoRE-style offline RL (VLA as Q-function) on autonomously collected rollouts scored by a
   reward that combines an external "was it funny" signal with the geometric "owner re-acquired"
   signal. This produces "learns from the state of the world" without any teleoperation.
6. **Hardware note for the owner.** Every fast VLA number in 2026 is on Thor (pi0.5 44-49 ms, GR00T
   41-45 ms) versus Orin (pi0 920 ms). If the semantic layer ever needs to run above ~2 Hz on the dog,
   Thor is a 5-20x step; on Orin the design must stay at sub-1B models or 1-2 Hz.

---

## 9. Open questions (not answered by the fetched sources)

- No primary latency number for SmolVLA or GR00T N1.6/N1.7 on AGX Orin (only Thor and 4090/5090).
- Whether GR00T N1.7 3B fine-tunes on 32 GB at all (README: 40 GB+ recommended, no LoRA flags).
- Whether openpi's ">22.5 GB" LoRA figure leaves enough of the 32 GB card for Parcel's other resident
  local models during a training run.
- QuadFM weights/dataset release date (GitHub placeholder as of this session).
- No quadruped VLA in the literature is conditioned on conversational/affective state or speech; the
  "funny joke -> chuckle" reward signal has no published precedent and must be designed.
- ELLSA on Orin has not been attempted by anyone in the fetched sources.
- Web-search budget expired before I could check for a SmolVLA-on-Jetson community benchmark, an EdgeVLA
  primary source, or a GR00T N1.5 Orin latency post; those remain unverified.

## 10. Full URL list (all fetched this session)

- https://arxiv.org/abs/2502.19645 ; https://arxiv.org/html/2502.19645 ; https://github.com/moojink/openvla-oft
- https://arxiv.org/abs/2406.09246 ; https://arxiv.org/html/2406.09246 ; https://huggingface.co/openvla/openvla-7b
- https://github.com/Physical-Intelligence/openpi ; https://arxiv.org/html/2410.24164 ; https://arxiv.org/html/2504.16054 ; https://arxiv.org/html/2501.09747
- https://website.pi-asset.com/pi06star/PI06_model_card.pdf ; https://www.pi.website/blog/pistar06 ; https://github.com/Physical-Intelligence/openpi/issues/789 ; https://github.com/Physical-Intelligence/openpi/issues/826
- https://arxiv.org/html/2503.14734 ; https://github.com/NVIDIA/Isaac-GR00T ; https://huggingface.co/nvidia/GR00T-N1.5-3B ; https://huggingface.co/nvidia/GR00T-N1.6-3B ; https://huggingface.co/nvidia/GR00T-N1.6-3B/raw/main/LICENSE ; https://huggingface.co/nvidia/GR00T-N1.7-3B ; https://www.nvidia.com/en-us/agreements/enterprise-software/nvidia-open-model-license/ ; https://developer.nvidia.com/blog/building-generalist-humanoid-capabilities-with-nvidia-isaac-gr00t-n1-6-using-a-sim-to-real-workflow/
- https://arxiv.org/html/2506.01844 ; https://huggingface.co/docs/lerobot/smolvla ; https://huggingface.co/docs/lerobot/async ; https://huggingface.co/docs/lerobot/hardware_guide ; https://huggingface.co/api/models/lerobot/smolvla_base ; https://github.com/huggingface/lerobot
- https://arxiv.org/pdf/2604.24447 ; https://www.jetson-ai-lab.com/tutorials/openpi_on_thor/ ; https://forums.developer.nvidia.com/t/real-time-inference-on-thor-rtx-pi0-5-gr00t-n1-6-1-7-thor-23-hz-rtx-5090-50-80hz/368788 ; https://arxiv.org/html/2603.03380v1 ; https://arxiv.org/abs/2606.08094
- https://arxiv.org/html/2410.11758 ; https://github.com/LatentActionPretraining/LAPA ; https://arxiv.org/html/2501.10105 ; https://github.com/2toinf/UniAct ; https://arxiv.org/html/2507.15597 ; https://github.com/BeingBeyond/Being-H0 ; https://arxiv.org/html/2605.00078v1
- https://arxiv.org/html/2502.13508 ; https://arxiv.org/pdf/2510.16756 ; https://github.com/bytedance/SALMONN/tree/ELLSA
- https://arxiv.org/html/2312.14457 ; https://arxiv.org/html/2412.15576 ; https://arxiv.org/html/2503.08007 ; https://arxiv.org/html/2412.04453 ; https://github.com/AnjieCheng/NaVILA ; https://github.com/yang-zj1026/legged-loco ; https://arxiv.org/html/2602.10399 ; https://arxiv.org/html/2603.24021v1 ; https://github.com/GaoLii/QuadFM ; https://arxiv.org/html/2606.28237 ; https://arxiv.org/html/2604.01708v1 ; https://arxiv.org/html/2408.11812
- https://arxiv.org/html/2307.15818 ; https://robotics-transformer2.github.io/ ; https://www.figure.ai/news/helix ; https://deepmind.google/blog/gemini-robotics-on-device-brings-ai-to-local-robotic-devices/ ; https://deepmind.google/models/model-cards/gemini-robotics-on-device-2/ ; https://arxiv.org/html/2602.12684 ; https://github.com/XiaomiRobotics/Xiaomi-Robotics-0 ; https://arxiv.org/abs/2604.05672
- https://arxiv.org/abs/2504.11054 ; https://github.com/facebookresearch/metamotivo ; https://arxiv.org/html/2511.04131
