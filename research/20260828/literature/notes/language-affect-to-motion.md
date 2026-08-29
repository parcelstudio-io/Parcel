# Language- and affect-conditioned expressive motion for legged robots — literature notes

Date: 2026-08-28. Researcher: Fable 5 subagent (literature lane). Scope: how a
categorical or continuous "style / emotion / intent" signal (text, affect label,
latent) becomes a whole-body motion on a legged robot or character, with the
Unitree Go2 EDU+ / Jetson AGX Orin as the deployment target.

Method: every source below was located with WebSearch and then READ with
WebFetch (arXiv abstract + HTML full text where it exists, project pages, GitHub
READMEs, vendor docs). Numbers are copied from the fetched text; when a number
came only from a search snippet and could not be confirmed by fetch it is marked
"(snippet only — not verified)" and is not used in the findings.

Things that could NOT be verified and are therefore excluded:

- "Conveying Emotion and Intention through Quadruped Robotic Motion: A Validation
  Study Using Canine-Inspired Movements" (ResearchGate 397229202) — 403 on fetch.
- A "Roy et al. (2025)" LLM-driven gesture generation for quadrupeds, cited in a
  search snippet of a 2026 Frontiers review; the fetched review text did not
  contain it.
- SayTap venue (CoRL 2023 by memory) — OpenReview returned a verification page;
  MotionGlot venue (IEEE Xplore 11127473) — page returned empty. Both are cited as
  arXiv preprints below.
- No Disney Research *quadruped* RL-character paper was found; the Disney
  legged-character line that could be fetched is bipedal (RSS 2024, SIGGRAPH 2024,
  SIGGRAPH 2025).

---

## 0. One-page summary

| # | Source (year) | Input → output | Robot / character | Data | Training | Real transfer | Code / license |
|---|---|---|---|---|---|---|---|
| 1 | SayTap (2023) | NL → GPT-4 → 4×T foot-contact matrix → PPO policy → 12 joint targets @50 Hz | Unitree A1 | random-pattern generator (5 gait types) | PPO, IsaacGym, 1000 iters, ~15 min on one V100 | yes, no fine-tuning | no code found; paper CC BY 4.0 |
| 2 | Disney bipedal character (RSS 2024) | animation engine (loops + triggered clips + joystick) → command signals (head/torso offsets, 2D vel + yaw rate, phase) → RL joint targets @50 Hz | custom 14-DoF biped, 15.4 kg | artist Maya clips + procedural gait | PPO, Isaac Gym, 8192 envs×24 steps, 100k iters ≈ 22 days/RTX 4090 | ~10 h runtime on up to 3 robots, no fall | none |
| 3 | Disney stylized gaits (SIGGRAPH 2024) | artist style parameters → phase-space blended walk cycles → whole-body refs → model-based control | free-walking biped + 2 sim morphologies | example walk cycles | procedural + MPC | real-time on physical robot | none |
| 4 | AMOR (SIGGRAPH 2025) | reward-weight vector on simplex (7 objectives) → single policy | 20-DoF biped character | reference clips (dance, pirouette) | MOPPO, 8192 envs @250 Hz, ~5 days/RTX 4090 | yes; jitter reduced by re-weighting post-training | none |
| 5 | Apple ELEGNT (2025) | hand-authored functional vs expressive trajectories | 6-DoF WidowX 250S lamp | — | — (no learning) | N=21 within-subject study | none |
| 6 | Apple EMOTION (2024) | social context → GPT-4o in-context → 22-D hand-pose keyframes, T=10 | Fourier GR-1 | 2 demos (Vision Pro) | none (ICL) | N=22 study; 26.8 s generation latency | prompts only |
| 7 | ExBody (RSS 2024) | upper-body joint angles + keypoints + root velocity cmd → joint targets | Unitree H1, 19 DoF | 780 CMU clips, 3.7 h | PPO, 4096 envs, Isaac Gym | yes (14 motion types) | GitHub (license file, type unlisted) |
| 8 | ExBody2 (2024/25) | 36 keypoints + 23 DoF refs + root vel/pose → 23 joint targets @50 Hz | Unitree G1 + Orin NX | CMU 1,919 seqs (filtered τ=0.15) | teacher PPO → student DAgger | joint err 0.1074 rad real | none found |
| 9 | BeyondMimic (2025) | per-motion tracking + guided diffusion (inpainting, joystick, obstacle) | Unitree G1 | LAFAN1 | PPO, Isaac Lab | zero-shot | MIT |
| 10 | Peng et al. imitate animals (RSS 2020) | dog mocap → IK retarget → per-clip PPO → latent-space real-world adaptation | Laikago 18 DoF | Zhang 2018 dog mocap + artist clips | PPO ~200M samples, PyBullet; ~50 real trials of 5–10 s | yes | Apache-2.0 (motion_imitation) |
| 11 | AMP for hardware (IROS 2022) | velocity cmd + AMP style reward (4.5 s German Shepherd) | Unitree A1 | 4.5 s mocap | dist. PPO, 5280 envs, 4B steps, 16 h/V100 | yes; CoT 0.93–1.12 vs 1.37–1.54 | MIT |
| 12 | VIM (2023, v3 2025) | latent skill embedding (+ high-level policy) → joint targets @25 Hz | Unitree A1 | 11 refs (dog mocap + synthesized + traj-opt) | PPO 4096 envs, 2e9 samples | yes (backflip 0.62 m, jump 0.50 m) | not linked |
| 13 | CAMP (2025) | one-hot skill (4 gaits) + velocity → joint targets @50 Hz | Unitree Go2 (also A1) | model-based synthetic clips ~4 s | PPO 4096 envs, ~7 h on RTX 4060 Ti | yes, no retuning | not specified |
| 14 | Walk Like Dogs (2025/26) | velocity cmd → RL → 18-D vMF latent → MoE decoder kinematic targets → tracking RL | Unitree Go2 | 13,076 dog poses (Zhang 2018) + mirrored | PPO 4096 envs, Isaac Lab, MJPC retarget | yes (grass, joystick) | none |
| 15 | MDME (2025) | raw actor motion → wavelet + VAE(32-D) embedding → policy (retargeting-free) | ANYmal D; Fourier N1 | ~10 min dog → ~52 min aug.; AMASS | PPO Isaac Lab @50 Hz | zero-shot | CC BY 4.0 paper, no repo URL |
| 16 | MotionGlot (2024) | text ↔ motion tokens (GPT-2 small; VQ codebooks 128×512 robot / 512×512 human) | Spot (SE(2) vel) + SMPL | QUAD-LOCO ~48k trajs from >1000 teleop trajs (2.5 h) | LLM instruction tuning | hardware demo | repo empty; data "soon" |
| 17 | MotionGPT (NeurIPS 2023) | text ↔ VQ motion tokens, T5-770M | SMPL human | HumanML3D 14,616 / KIT-ML 3,911 | LM pretrain + instruction tune | — | MIT |
| 18 | OmniMotionGPT (CVPR 2024) | text → animal (SMAL) motion via human prior | 36 animal identities | AnimalML3D 1,240 seqs, 3,720 captions | joint autoencoders + CLIP + GPT | — | MIT (code + data) |
| 19 | QuadFM / Gen2Control (2026) | speech → text → MotionGPT3-style generator @2 Hz → single tracker @50 Hz on Orin (~500 ms) | Unitree Go2 X | 11,784 clips, 20.27 h, 35,352 texts | stage I 48 h MI308X; stage II 2×3090, 20k iters, 4096 envs | human-rated 7.40–7.98/9 | CC BY 4.0 planned; repo Apache-2.0, empty |
| 20 | Uni-Mo / Quad-Imaginarium (2026) | LLM prompt → fine-tuned Wan2.2 video → ViTPose lift → per-motion PPO tracker | Unitree Go2 | 7,488 motions, 18.5 h | PPO (BeyondMimic setup), MuJoCo, 4096 envs/RTX 3090 | 96.7% over 392 motions × 5 trials | unreleased pending acceptance |
| 21 | WalkTheDog (SIGGRAPH 2024) | VQ periodic autoencoder → shared phase manifold human↔dog | characters | dog 151k frames @60 fps (~42 min); human ~51–70 min sets | 40 min on RTX 3090 | — | GitHub + Drive data |
| 22 | Spot Choreography API | scripted moves (54) + .cha keyframe animations, slices = ¼ beat | Boston Dynamics Spot | — | — | "The robot will fall down" | special-permissions license |
| 23 | Unitree Go2 SportClient | 40+ fixed high-level actions (Hello, Stretch, Dance1/2, Heart, Pose, FrontFlip …) | Go2 | — | — | — | BSD-3-Clause |
| 24 | Zhang et al. MANN dog mocap (SIGGRAPH 2018) | the canonical dog dataset behind #10–#15, #21 | single dog | ~10 min (filtered) | — | — | CC BY-NC 4.0 (AI4Animation) |
| 25 | RGBD-Dog (CVPR 2020) | 5 dogs × 5 motions, BVH skeletons + Kinect/HD video | — | — | — | — | academic use, release form |
| 26 | MoCapAct (NeurIPS 2022 D&B) | expert-tracking rollouts → hierarchical policy / GPT prior (humanoid) | dm_control CMU humanoid | >3 h CMU; 600 GB / 50 GB | — | — | MIT code, CDLA-P v2 data |
| 27 | Tooling: Isaac Lab, unitree_rl_lab, beyondAMP, AMP_for_hardware | — | Go2 envs exist; AMP only via skrl | — | — | — | Apache-2.0 / MIT |

---

## 1. Language → locomotion interfaces

### 1.1 SayTap: Language to Quadrupedal Locomotion (Tang, Yu, Tan, Zen, Faust, Harada; Google, 2023)
- URLs fetched: https://arxiv.org/abs/2306.07580 , https://arxiv.org/html/2306.07580v1 , https://saytap.github.io/
- Interface: a foot-contact pattern template, a **4×T matrix of 0/1** (FL, FR, RL, RR rows). The LLM is **GPT-4** at **temperature 0.5**; prompt has four parts (general instruction, gait definition, output format, examples).
- Controller: **Unitree A1**, 12 outputs, **50 Hz**; policy MLP **[512,256,128] ELU**, **65-D input**, contact-pattern window **Lw=5**; **PPO in IsaacGym, 1000 iterations, ~15 min on one V100**; gait resampled every 150 steps. A random pattern generator samples **T∈[24,28] (0.48–0.56 s cycle)** over **BOUND, TROT, PACE, STAND_STILL, STAND_3LEGS**.
- Results: ">50% success rate in predicting the correct contact patterns" and "solve 10 more tasks out of a total of 30 tasks" than other design choices; transferred to the real A1 without fine-tuning.
- Code: none linked on the project page. Paper CC BY 4.0.
- Assessment: cheapest possible language→style bridge, but the style space is gait-level only (which feet, when). No body posture, no head, no affect. Useful as a *component* (gait/tempo channel) inside a richer command vector, not as the whole answer.

### 1.2 Language to Rewards for Robotic Skill Synthesis (Yu et al., Google DeepMind, 2023)
- URL fetched: https://arxiv.org/abs/2306.08647
- LLM writes reward parameters; **MuJoCo MPC** optimizes them online. Simulated quadruped + dexterous manipulator; **17 tasks; 90% success vs 50%** for a Code-as-Policies primitive baseline; real robot arm validation.
- Assessment: reward-as-interface is the "no dataset" route to novel behaviors ("sit up", "moonwalk"). It is not a deployable controller for a Go2 on its own (MPC in MuJoCo), but it is a good **offline behavior-authoring tool**: generate a reference clip in MuJoCo from a text description, then track it with an RL tracker (the Uni-Mo/QuadFM pattern).

### 1.3 QUAR-VLA / QUART (ECCV 2024) and QUART-Online (ICRA 2025)
- URLs fetched: https://arxiv.org/abs/2312.14457 , https://arxiv.org/abs/2412.15576
- QUART: vision-language-action family for quadrupeds; QUARD dataset (navigation, terrain, whole-body manipulation); "4000 evaluation trials". QUART-Online: action-chunk discretization; "65%" success improvement; real-time inference "in sync with the underlying controller frequency" (Hz not stated in the abstract).
- Assessment: VLA-for-quadruped exists, but it targets task success, not expressive style. Relevant only as evidence that a multimodal LM can emit discretized action chunks fast enough for a quadruped.

### 1.4 MotionGlot: A Multi-Embodied Motion Generation Model (Harithas & Sridhar, Brown, 2024)
- URLs fetched: https://arxiv.org/abs/2410.16623 , https://arxiv.org/html/2410.16623 , https://ivl.cs.brown.edu/research/motionglot.html , https://github.com/sudarshan-s-harithas/MotionGlot-A-Multi-Embodied-Motion-Generation-Model
- Quadruped embodiment is **Spot**; robot motion parameterized as **SE(2) velocities (3-D)**; human as 263-D HumanML3D (22 joints). VQ-VAE codebooks **128×512 (robot)** and **512×512 (human)**, downsampling 4; motion tokens appended to **GPT-2 small** vocabulary (50,257).
- QUAD-LOCO: "approximately 48,000 trajectories" built by mirroring/time-scaling from **>1000 recorded trajectories** collected over **2.5 h** of expert teleoperation of a real Spot; direction-based text annotations. QUES-CAP: **23,000** situational prompts. Six tasks incl. text-to-robot-motion, captioning, goal-conditioned generation, **sentiment classification with gaits**; **+35.3%** average improvement. Hardware experiments mentioned.
- Code repo exists but shows only an empty README (1 commit); datasets "To be released Soon". Paper CC BY 4.0.
- Assessment: the recipe (per-embodiment VQ tokenizer + small LM + instruction template) is exactly the kind of "trainable text→motion head" Parcel could build over a Go2 latent, and it is small enough for Orin. But the quadruped action space here is *base velocity only*, so it says nothing about whole-body expressiveness.

---

## 2. Expressive robot characters (Disney, Apple)

### 2.1 Design and Control of a Bipedal Robotic Character (Grandia et al., Disney Research / WDI R&D, RSS 2024)
- URLs fetched: https://arxiv.org/abs/2501.05204 , https://arxiv.org/html/2501.05204
- Hardware: **5 DoF per leg + 4 DoF neck/head = 14 DoF; 15.4 kg** (torso 5.8, head/neck 2.4, each leg 3.6); **0.66 m**; leg actuators **34 N·m peak, 20 rad/s**; head actuators **4.8 N·m, 6.3 rad/s**.
- Architecture: an **animation engine** composes "background loops, triggered clips, and joystick-driven procedural modification" and emits **command signals**; separate RL policies per motion class consume them: *perpetual* (standing: head height/orientation offsets + torso height/orientation), *periodic* (walking: head commands + 2-D velocity + yaw rate in path frame), *episodic* (clip: phase signal only). Policies "switch seamlessly mid-performance".
- Authoring: artists in **Maya** for episodic clips (happy dance, excited, jump, tantrum, yes/no, scanning); procedural gait generation via rigid-body dynamics; inverse dynamics + MPC produce whole-body references.
- Training: **PPO, Isaac Gym, 8192 envs × 24 steps, 100,000 iterations (~22 days on an RTX 4090)** per policy; MLP 3×512 ELU; state = torso pose/velocities, joint pos/vel, previous 2 actions; action = PD joint setpoints; **50 Hz policy, 600 Hz actuator loop**.
- Results: tracking MAE **0.035 rad standing, 0.123 rad walking, 0.027–0.043 rad episodic**; max **0.7 m/s fwd, 0.4 m/s lateral, 1.8 rad/s turn**; "on the order of 10 h of robot runtime without a single fall" across up to three robots; recovers from pushes by deviating from the reference contact schedule.
- Code: none.
- Assessment (load-bearing): this is the **reference architecture** for "expressive + robust + interruptible": a kinematic *animation layer* owns style, an RL *tracking layer* owns balance, and the interface is a small command vector (head offsets, velocity, phase). It cost ~22 GPU-days per policy on a 4090 — that is the price of "no falls in 10 h".

### 2.2 Interactive Design of Stylized Walking Gaits for Robotic Characters (Hopkins et al., Disney, SIGGRAPH 2024)
- URL fetched: https://la.disneyresearch.com/publication/interactive-design-of-stylized-walking-gaits-for-robotic-characters/ (PDF fetch was unreadable)
- Each walking style = a set of **sample parameters** translated into whole-body reference trajectories; a **phase-space blending** of animator-authored example walk cycles that "preserv[es] contact constraints" generalizes across continuous velocity; model-based control stack; real-time editing on the simulated or physical biped, plus two simulated morphologies.
- Assessment: shows that *style* can be a low-dimensional continuous parameter vector over a gait generator, tuned live by an artist. For a dog: "happy trot" vs "sad walk" = different sample sets of one gait generator.

### 2.3 AMOR: Adaptive Character Control through Multi-Objective RL (Alegre, Serifi, Grandia, Mueller, Knoop, Bächer; Disney, SIGGRAPH 2025)
- URLs fetched: https://arxiv.org/html/2505.23708 , https://la.disneyresearch.com/publication/amor-adaptive-character-control-through-multi-objective-reinforcement-learning/
- A **single policy conditioned on a reward-weight vector on a simplex** over **7 objectives** (upper body, lower body, feet, rigid-body poses, root pose, root velocities, smoothness) learns the Pareto front; weights are chosen *after* training. **MOPPO; Isaac Gym 8192 envs at 250 Hz on an RTX 4090; ~5 days (300k iterations) per character; 4-layer MLP, 1024 units, ELU**; 20-DoF biped, torque-controlled. Sim-to-real: raising the smoothness weight reduced measured joint jitter on a dance; a double pirouette needed "approximately 1 day" of manual weight tuning on the real robot.
- Assessment: the cleanest published mechanism for **continuous, runtime-steerable style intensity** ("more energetic", "calmer", "smoother") without retraining. Reward-weight conditioning is a candidate "affect axis" for Parcel.

### 2.4 ELEGNT: Expressive and Functional Movement Design for Non-anthropomorphic Robot (Hu, Huang, Sivapurapu, Zhang; Apple, 2025)
- URL fetched: https://arxiv.org/html/2501.12493v1
- Robot: lamp on a **6-DoF WidowX 250S** arm with LED head, projector, cameras, voice. Framework: choose a trajectory maximizing **F(τ) + γ·E(τ)** (functional + expressive utility). Expressive dimensions: **intention, attention, attitude, emotion**; primitives from **kinesics** (spatial: nod, lower head; temporal: speed, pauses, jerk) and **proxemics** (static gaze/position; dynamic approach/avoid). Movements are **hand-authored** by HRI researchers and animators (no learning, no LLM).
- Study: **N=21** (8F/12M/1 n.r., ages 26–51), within-subject, F (γ=0) vs E (γ>0), **6 tasks** (3 function-oriented: photograph light, project assistance, failure indication; 3 social: remind water, social conversation, play music); 0–100 ratings on perceived intelligence, human-likeness, engagement, connection, willingness to interact, perceived character. **Expression M=56.16 vs Function M=28.77 (SD 27.15), Welch t=19.85, p<0.0001**; per-metric t: character 10.58, human-likeness 9.32, engagement 8.80, connection 8.50, willingness 7.37, intelligence 5.22 (all p<0.001). Expressive movement helped **social tasks** on every metric; on function tasks no significant difference for intelligence/willingness/engagement. Older participants rated expressive lower (p<0.001); non-roboticists rated higher (p=0.006).
- Assessment: the strongest quantitative evidence that expressive movement *matters most in social/conversational contexts* — Parcel's exact context. It also gives a vocabulary (intention/attention/attitude/emotion × kinesics/proxemics) that maps onto a dog with no neck: attention = body yaw/pitch + camera gaze; attitude = approach/withdraw; emotion = tempo/pauses/jerk.

### 2.5 EMOTION: Expressive Motion Sequence Generation for Humanoid Robots with In-Context Learning (Huang, Hu, Nechyporenko, Kim, Talbott, Zhang; Apple, 2024)
- URLs fetched: https://arxiv.org/abs/2410.23234 , https://arxiv.org/html/2410.23234
- **Fourier GR-1**; motion = **22 values per timestep** (hand positions 3-D ×2, Euler ×2, fingers 5-D ×2), **T=10** keyframes, executed by IK + interpolation. **GPT-4o (gpt-4o-2024-05-13)** with three agents (context analysis, generation with **2 in-context demos** from Vision Pro, refinement from feedback). 10 gestures (thumbs-up, okay, v-sign, air-quotes, come-closer, fist-pump, jazz-hands, spread-hands, stop, listening).
- Study: **N=22** valid (of 30), within-subject, 7-point Likert. EMOTION vs human oracle: no significant difference (naturalness p=0.267, understandability p=0.528). EMOTION++ (with feedback, avg **1.9 iterations**) beat EMOTION (p=0.0014 / 0.019) and beat human on understandability (p=0.003). **Latency 26.8±4.0 s** initial, **21.2±3.7 s** per refinement — authors say this is too slow for conversation and propose distilling a small local LLM.
- Assessment: a hosted LLM can author keyframe gestures that people rate as natural as human-designed ones — but at ~25 s per gesture. For Parcel this is an **offline library-authoring tool** (generate → verify in sim → cache), not a runtime path. The feedback loop (EMOTION++) is a template for "owner reaction → refine".

---

## 3. Humanoid expressive whole-body control (transferable recipes)

### 3.1 ExBody (Cheng et al., UCSD, RSS 2024)
- URLs fetched: https://arxiv.org/abs/2402.16796 , https://arxiv.org/html/2402.16796v1 , https://github.com/chengxuxin/expressive-humanoid
- **Unitree H1 (19 DoF, ~51.5 kg, ~1.8 m)**. Data: **780 CMU MoCap clips, 3.7 h**, keyword-filtered (include walk/dance/punch; exclude ladder/suitcase/stair). Policy input: upper-body **9 joint angles + 18 keypoint values** plus root command (linear velocity, roll/pitch/yaw, height); legs only track velocity. **PPO, 4096 envs, Isaac Gym**, lr 1e-3, γ 0.99, GAE 0.95. Real-world roll/pitch MAE **0.036–0.075 rad across 14 motion types vs 0.055–0.11 for an AMP baseline**. Code released (Isaac Gym training, CMU→H1 retargeting derived from ASE, deployment export); license file present, type not shown in fetched README.
- Assessment: the "expressive upper body + robust velocity-tracked legs" decoupling is directly reusable on a dog as "expressive body/head posture channel + robust gait channel".

### 3.2 ExBody2 (Ji et al., UCSD, 2024/25)
- URLs fetched: https://arxiv.org/abs/2412.13196 , https://arxiv.org/html/2412.13196 , https://exbody2.github.io/
- **Unitree G1 with Jetson Orin NX; 50 Hz policy; 18–30 ms command latency; 500 Hz low level.** Data: CMU **1,919 sequences** + ACCAD OOD; automated curation by tracking-error threshold (**τ=0.15**). Inputs: 23-DoF proprioception, **36 keypoints + 23 DoF references + root velocity/pose**; teacher PPO with privileged info, **student via DAgger with 10-frame history**; Adam lr 1e-4, batch 4096. Sim: E_vel **0.2930 m/s**, MPKPE **0.1000 m**, MPJPE **0.1079 rad**; real joint error **0.1074 rad**; 43-s choreography, sidesteps, punching. No code link found.
- Assessment: proves a **single reference-conditioned tracker** over ~2k clips runs on an Orin-class computer at 50 Hz. This is the tracker shape Parcel should aim for (one policy, clip passed in as reference window), not one policy per clip.

### 3.3 BeyondMimic (Liao et al., 2025)
- URLs fetched: https://arxiv.org/abs/2508.08241 , https://github.com/HybridRobotics/whole_body_tracking
- G1; LAFAN1 retargeted; PPO in Isaac Lab (v2.1.0 / Isaac Sim 4.5) with DeepMimic rewards; **guided diffusion at test time** for motion inpainting, joystick teleoperation, obstacle avoidance; zero-shot hardware; **MIT license**. Uni-Mo's Go2 trackers "follow the BeyondMimic setup".
- Assessment: MIT-licensed, actively maintained tracking stack that already has a Go2 downstream user (Uni-Mo). The diffusion-guidance layer is the published answer to "steer a tracked clip by a live command without retraining".

---

## 4. Animal imitation and style priors on quadrupeds

### 4.1 Learning Agile Robotic Locomotion Skills by Imitating Animals (Peng, Coumans, Zhang, Lee, Tan, Levine; RSS 2020, Best Paper)
- URLs fetched: https://arxiv.org/abs/2004.00784 , https://ar5iv.labs.arxiv.org/html/2004.00784 , https://xbpeng.github.io/projects/Robotic_Imitation/index.html , https://github.com/erwincoumans/motion_imitation
- **Laikago, 18 DoF (12 actuated)**. Mocap: public dog dataset (Zhang et al. 2018) + artist animations; **IK retargeting on keypoint pairs (feet, hips)**; **PPO in PyBullet, ~200M samples**; domain randomization over 6 dynamics parameters; **real-world adaptation with AWR in a latent space using ~50 trials of 5–10 s each**. Skills: pace, trot, backward trot, side-steps, spin, turn, hop-turn, in-place stepping; "forward running proved challenging".
- Code: **Apache-2.0** (google-research/motion_imitation, mirror erwincoumans), includes retargeted clips `dog_pace`, `dog_trot`, `dog_spin`, `dog_backward_trot`, pretrained policies, retargeting scripts, Laikago and A1 PyBullet models.
- Assessment: still the canonical dog→robot retargeting pipeline and the only Apache-licensed one with ready-made dog clips. Per-clip policies, no conditioning.

### 4.2 Adversarial Motion Priors Make Good Substitutes for Complex Reward Functions (Escontrela et al.; IROS 2022)
- URLs fetched: https://arxiv.org/abs/2203.15103 , https://ar5iv.labs.arxiv.org/html/2203.15103 , https://research.google/pubs/adversarial-motion-priors-make-good-substitutes-for-complex-reward-functions/ , https://github.com/escontra/AMP_for_hardware
- **Unitree A1**; **4.5 s of German Shepherd mocap** (Zhang & Starke dataset; pace, trot, canter, turn-in-place). Discriminator on (s, s′) of joint angles/velocities, base linear/angular velocities; **w_style 0.65, w_task 0.35, gradient penalty 10**. **Distributed PPO, Isaac Gym, 5280 envs, 4B steps, 16 h on one V100**; batch 126,720 transitions. **Cost of transport 0.93±0.04 – 1.12±0.1 (0.8–1.6 m/s) vs 1.37±0.12 – 1.54±0.17 with a complex hand-tuned reward vs 5.18–14.03 with no style reward**; pace at 0.8 m/s, trot/canter with flight phase at 1.7 m/s; commands sampled fwd (−1, 2) m/s, lateral (−0.3, 0.3). Real A1 deployment qualitative only.
- Code: **MIT**, Isaac Gym Preview 3, Python 3.8, PyTorch 1.10 (legacy stack).
- Assessment (load-bearing): a few seconds of dog data is enough to make a gait *look like a dog* and be energy-efficient; AMP is the cheapest "naturalness prior". It gives style *quality*, not style *selection*.

### 4.3 VIM — Generalized Animal Imitator (Yang et al., UCSD/CMU/USC; 2023, v3 May 2025)
- URLs fetched: https://arxiv.org/abs/2310.01408 , https://arxiv.org/html/2310.01408v3 , https://rchalyang.github.io/VIM/
- **Unitree A1, 25 Hz, PD KP 40 / KD 1.0.** Skills conditioned on a **latent skill embedding** (Gaussian) produced by a reference-motion encoder; a high-level policy emits latents for tasks. Functionality reward tracks root pose (exp(−20‖e‖²) horizontal, exp(−80‖e‖²) vertical, exp(−10‖e‖²) orientation); stylization reward is **adversarial early, joint/end-effector tracking later**, blended by a schedule. **11 reference motions**: dog mocap (Zhang 2018: walk, trot, canter, pace, jump-while-running, L/R turns), 2 synthesized, 2 from trajectory optimization (backflip, jump forward). **PPO, 4096 envs, IsaacGym at 200 Hz, 2×10⁹ samples low-level / 4×10⁸ high-level**; lr 3e-4 (disc 1e-5). Real A1 without fine-tuning: **jump height 0.50±0.003 m (ref 0.53), jump distance 0.76±0.05 m (ref 0.82), trot 1.33±0.17 m/s (ref 1.16), backflip 0.62±0.01 m**; sim root-XY error 1.24±0.62 m; joint error 0.08±0.06. Beat AMP/PPO/HRL baselines on command-following and jumping. Code not linked.
- Assessment (load-bearing): the closest published "latent-conditioned multi-skill dog controller" — one policy, a skill latent you can pick by label, robust real transfer on Unitree hardware. Skill count (11) is small; the latent is *per clip*, not per affect.

### 4.4 CAMP — Conditional Adversarial Motion Priors (Huang, Xie, Li; 2025)
- URLs fetched: https://arxiv.org/abs/2509.21810 , https://arxiv.org/html/2509.21810
- **Unitree Go2** (also A1). Skill = **one-hot vector** ("to avoid introducing implicit ordinal biases"); skill discriminator + skill-conditioned reward; **4 gaits (trot, pace, bound, pronk)** from **model-based synthetic clips (~4 s each, no mocap)**; **PPO, Isaac Gym, 4096 agents, ~7 h on an RTX 4060 Ti**, 50 Hz, 8 domain-randomization categories. **Joint-tracking accuracy 91.23–91.38%**; deployed on Go2 "without retuning". Code not specified.
- Assessment (load-bearing for the Go2 path): a categorical label → Go2 gait switch is a **7-GPU-hour** problem on consumer hardware when the reference clips exist. Synthetic (model-based) clips were enough. The ablation note that the skill discriminator is required for >2 skills is a useful design fact.

### 4.5 Walk Like Dogs (Kang, Cheng, Zargarbashi, Yoon, Choi, Coros; ETH; 2025, v2 Mar 2026)
- URLs fetched: https://arxiv.org/abs/2507.00677 , https://arxiv.org/html/2507.00677
- **Unitree Go2.** Data: subset of Zhang 2018 dog database, **13,076 pose samples + mirrored**, unlabeled. Retargeting: constrained IK with scale factors (**α_z 0.81, α_fwd 0.6, α_side 0.6; limb scaling [0.6, 0.7, 0.81]**) then **MJPC (iLQG, 2.0 s horizon, 0.01 s)** for dynamic consistency. Synthesis: **hyperspherical VAE (vMF), 18-D latent**, **mixture-of-experts decoder (6 experts)**; an RL policy maps forward/turning velocity commands to a unit latent; modes discovered automatically. Both policies **PPO, 4096 envs, [512,256,128]**, batch 24,576, lr 5e-4; tracking policy in **Isaac Lab**, Kp 30 / Kd 0.5, **50 Hz**. Results: commanded range 0.6–2.4 m/s, ±1.0 rad/s; **emergent gallop→trot→pace transitions at 1.8→1.2→0.7 m/s**; RMS base-velocity tracking error reported as "0.11" (unit as printed: m). Real Go2 joystick control on grass. No code.
- Assessment (load-bearing for the Go2 path): a **learned latent over dog data on the Go2** with a command→latent policy is published and works on hardware. Replace "velocity command" with "velocity + affect label" and this is Parcel's style-conditioned gait layer. The kino-dynamic retargeting recipe (IK scaling + MJPC) is the one to copy for Go2 morphology.

### 4.6 Multi-Domain Motion Embedding (Heyrman, Li, Klemm, Kang, Coros, Hutter; ETH; Dec 2025)
- URLs fetched: https://arxiv.org/abs/2512.07673 , https://arxiv.org/html/2512.07673
- **ANYmal D** (quadruped), H1 (sim), Fourier N1 (hardware). Embedding = **discrete wavelet transform (db2; 4 levels quadruped / 2 humanoid) + VAE latent (32-D quadruped / 64-D humanoid)**; policy sees proprioception, a motion history buffer (**25 frames quadruped / 5 humanoid**) and the embeddings; **retargeting-free** (trained on raw actor morphology). Data: AMASS (SMPL) and **~10 min of dog data (Zhang 2018) augmented to ~52 min** by mirroring and height scaling. **PPO in Isaac Lab, 50 Hz.** Zero-shot: N1 mimics humans from RGB-video SMPL; ANYmal D reproduces dog motions (pace/trot/canter, pacing in a circle) and non-expert actor motions. Outperforms VMP and PAE on reconstruction (figures, no table numbers). CC BY 4.0; no repo URL in paper.
- Assessment: evidence that a *continuous* motion embedding (not a label) can drive a quadruped in real time and generalize to unseen styles — the "latent" end of the label→latent→motion spectrum.

### 4.7 Canonical character-animation priors: AMP (SIGGRAPH 2021), ASE (SIGGRAPH 2022), CALM (SIGGRAPH 2023)
- URLs fetched: https://arxiv.org/abs/2104.02180 , https://arxiv.org/abs/2205.01906 , https://arxiv.org/abs/2305.02195
- AMP: style reward from unstructured clips + simple task reward; "composition of disparate skills emerges automatically". ASE: adversarial + unsupervised RL learns a **latent skill embedding** with a reusable low-level controller ("over a decade of simulated experiences"). CALM: jointly learns a **motion encoder + policy** so a motion clip's latent *conditions* the controller ("style-conditioning for higher-level task training"), giving video-game-like control.
- Assessment: ASE/CALM are the theory behind VIM/CAMP/Walk-Like-Dogs; CALM's encoder-conditioned control is the cleanest "clip → latent → behaviour" abstraction.

---

## 5. Text-to-motion for animals / quadrupeds, and the new Go2 datasets

### 5.1 MotionGPT (Jiang et al., NeurIPS 2023)
- URLs fetched: https://arxiv.org/abs/2306.14795 , https://github.com/OpenMotionLab/MotionGPT
- VQ motion tokens + **T5-770M**; HumanML3D (**14,616** motions) and KIT-ML (**3,911**); text-to-motion **FID 0.160±0.008**; SOTA on 18/23 metrics; **MIT**. Authors note dataset size limits gains from a larger LM.

### 5.2 OmniMotionGPT: Animal Motion Generation with Limited Data (Yang et al., CVPR 2024)
- URLs fetched: https://arxiv.org/abs/2311.18303 , https://github.com/USRC-SEA/OmniMotionGPT
- **AnimalML3D: 1,240 sequences, 36 animal identities (922 train / 23 ids; 318 test / 13 ids), 3,720 human-written captions**; motions derived from DeformingThings4D registered to the SMAL template. Joint human/animal motion autoencoders + CLIP text embedding + GPT-style decoder; outperforms human-motion baselines trained on animal data. **MIT** code and data; pretrained weights not explicitly listed.
- Assessment: the only open text→animal-motion dataset; quadruped skeleton is SMAL (needs retargeting to Go2).

### 5.3 QuadFM + Gen2Control (Gao et al., Alibaba AMAP; Mar 2026)
- URLs fetched: https://arxiv.org/html/2603.24021v1 , https://github.com/GaoLii/QuadFM
- Dataset: **11,784 clips, 20.27 h, 35,352 text descriptions** in three layers (fine-grained action labels, interaction narratives, executable commands). Composition: **locomotion 9,390 clips / 11.64 h** (real-dog mocap + video-to-motion via Qwen2.5-VL + Wan) and **interaction & emotion 2,394 clips / 8.63 h** (teleoperation **696 clips / 4.74 h**; artist keyframes **1,698 clips / 3.89 h**); video-generated **1,392 clips / 1.62 h**. Example labels: greeting, cautious/sad pacing, dancing, excited bounding, joyful bounding, stretching, peeing, pouncing toward humans, ground scratching, leg lifting.
- System: **Unitree Go2 X + Jetson Orin**; **MotionGPT3-based generator (motion VAE + diffusion LM) at 2 Hz** and a **single PPO tracker at 50 Hz** that observes "current proprioception and a short future window of the reference motion"; **~500 ms speech-to-execution incl. cloud ASR**. Training: stage I imitation **48 h on one AMD MI308X**, batch 24; stage II joint **2×RTX 3090, 20,000 iterations, 4,096 envs**, rollout 24, IsaacSim with DR; asymmetric actor-critic. Evaluation: **30 participants**, 10 unseen open-vocabulary prompts, 0–9 scales — MotionGPT3 baseline 5.77 / 5.62 / 5.54 / 6.27 (alignment / smoothness / naturalness / stability); Gen2Control **7.40–7.98**. No real-robot success percentages. Dataset "will be released" under CC BY 4.0; the GitHub repo (Apache-2.0) contained only a README saying "will be released soon" at fetch time.
- Assessment (load-bearing): this is the **published system closest to Parcel's target** — speech → text → generated Go2 motion → single tracker on an Orin at ~500 ms — and it contains an explicit *emotion-expressive* category. Its dataset is not downloadable today, so it is a design reference, not a dependency.

### 5.4 Uni-Mo / Quad-Imaginarium (Liu, Gao, Qian, Liu, Cai, Li; Alibaba AMAP; Jun 2026)
- URLs fetched: https://arxiv.org/abs/2606.28237 (via html) , https://arxiv.org/html/2606.28237 , https://github.com/GaoLii/Quad-Imaginarium
- Pipeline: LLM (Gemini) proposes prompts → **Wan2.2 image-to-video fine-tuned with an identity-consistency loss** (fine-tuned on **190 designer motions × 10 views = 1,900 video–prompt pairs, 56 H20 GPUs, 10 epochs**) → **ViTPose** keypoints → kinematic fit with reprojection loss → CLIP / geometric / tracking-error gates → **one PPO tracking policy per motion (BeyondMimic setup), MuJoCo, 4,096 envs on a single RTX 3090**, MLP (512,256,128), residual joint targets ×0.25.
- Dataset: **7,488 language-annotated Go2 motions, 18.5 h**, 19-D state (root pos 3 + quat 4 + 12 joints), clips 5–15 s (paper says 50 Hz; repo README says 24 fps — discrepancy noted). Diversity beats QuadFM and T2QRM on most kinematic axes (largest margin on pitch range).
- Results: **97.6% of 7,488 succeed in sim**; **96.7% real-Go2 success over 392 randomly sampled motions × 5 trials** (success = full motion without fall or manual intervention). No text-to-motion model trained; no latency reported. Dataset unreleased "upon paper acceptance"; no license shown.
- Assessment (load-bearing): the strongest hardware evidence that a large, *non-locomotion* expressive vocabulary is trackable on the Go2 (acrobatic and performative behaviors). It also demonstrates a zero-mocap data path (video diffusion → 3-D lift → sim filter) that Parcel could reproduce in miniature with hand-authored MuJoCo clips instead of a video model.

### 5.5 WalkTheDog: Cross-Morphology Motion Alignment via Phase Manifolds (Li, Starke, Ye, Sorkine-Hornung; SIGGRAPH 2024)
- URLs fetched: https://arxiv.org/abs/2407.18946 , https://ar5iv.labs.arxiv.org/html/2407.18946 , https://peizhuoli.github.io/walkthedog/ , https://github.com/PeizhuoLi/walk-the-dog
- Vector-quantized periodic autoencoder learns a **shared phase manifold** (multiple closed curves, one per latent amplitude) across a human and a dog with no supervision; used for motion matching, retrieval, transfer, stylization. Data: **dog 151k frames @60 fps (~42 min)**; Human-Locomotion 186k @60 (~51 min); MOCHA clown/ogre/princess ~486–501k @120 fps (~68–70 min each). Encoder/decoder: two-layer 1-D convs, kernel 23; Adam 1e-4, batch 32, 1-s windows; **40 min on an RTX 3090** (dog + human-loco). Code on GitHub (license file present, type not shown), data + pretrained human–dog model via Google Drive; Unity preprocessing.
- Assessment: a principled way to **transfer style from human performance/mocap to a dog skeleton** (e.g., an actor performing "sad" → dog "sad") without paired data. Kinematic only; needs a tracker downstream.

---

## 6. Vendor APIs

### 6.1 Boston Dynamics Spot Choreography
- URLs fetched: https://dev.bostondynamics.com/docs/concepts/choreography/choreography_service.html , https://dev.bostondynamics.com/docs/concepts/choreography/move_reference.html , https://dev.bostondynamics.com/docs/concepts/choreography/animation_file_specification.html , https://github.com/boston-dynamics/spot-sdk/blob/master/docs/concepts/choreography/README.md
- Sequence = slices-per-minute (constant) + list of moves (type, start slice, duration, MoveParams). **A slice is ¼ beat**; "many moves will be most reliable in the range of 250–450 slices per minute". **8 tracks** (Legs, Body, Arm, Gripper, Status Lights, AV Lights, AV Buzzer, Annotations/Music); moves on different tracks run simultaneously. **54 moves in 8 categories** (body 7, step 8, dynamic 8, transition 9, kneel 4, arm 11, face lights 4, audio-visual 3) with parameters such as rotation/translation/pivot/amplitude/radius, velocity/yaw_rate/swing_height/stance_width/duty_cycle, entry/exit slices. **Custom animations** as `.cha` files (tracks legs/body/arm/gripper; keyframes as body pose, leg joint angles or foot positions with stance/swing, arm joints or hand pose; time in seconds or via frequency; `bpm` scaling; `body_tracking_stiffness` 1–11; `precise_steps`; `timing_adjustability`), uploaded with `UploadAnimatedMove`. Warning: "The choreography framework is less robust than other Spot behaviors… The robot **will** fall down"; flat floor, no payload. Requires a **special-permissions choreography license**.
- Assessment: the mature industrial model of "expression = scripted timeline over independent body tracks with a beat clock". The track/timeline abstraction (legs vs body vs lights) and the "slice" tempo unit are worth copying into Parcel's expression layer even though the Go2 has no such API.

### 6.2 Unitree Go2 SportClient (unitree_sdk2, BSD-3-Clause)
- URLs fetched: https://github.com/unitreerobotics/unitree_sdk2 , https://raw.githubusercontent.com/unitreerobotics/unitree_sdk2/main/include/unitree/robot/go2/sport/sport_client.hpp , https://github.com/unitreerobotics/unitree_sdk2_python
- High-level fixed actions in the header: Damp, BalanceStand, StopMove, StandUp, StandDown, RecoveryStand, **Euler(roll, pitch, yaw)**, **Move(vx, vy, vyaw)**, Sit, RiseSit, SpeedLevel, **Hello, Stretch, Heart, Pose(flag), Scrape, FrontFlip, FrontJump, FrontPounce, Dance1, Dance2, LeftFlip, BackFlip, HandStand(flag)**, FreeWalk, FreeBound, FreeJump, FreeAvoid, ClassicWalk, WalkUpright, CrossStep, StaticWalk, TrotRun, EconomicGait, SwitchJoystick, Content, AutoRecoverSet/Get, SwitchAvoidMode. Python SDK (BSD-3) exposes StandUpDown / VelocityMove / BalanceAttitude / TrajectoryFollow / SpecialMotions examples plus **low-level joint control (kp, kd, torque) and IMU/motor state**.
- Assessment: Parcel's current fixed list ("walk", "bow", "sit", "stretch", "chuckle") is a subset of this vendor vocabulary; the only *continuous* expressive channels it offers are Euler (body attitude), Move (velocity), and body height/speed level. Anything beyond that requires low-level joint control with a learned tracker — which is what every Go2 paper above does.

---

## 7. Dog motion datasets usable for Go2 retargeting

| Dataset | What it is | Size (fetched) | Access / license | Used by |
|---|---|---|---|---|
| Zhang, Starke, Komura, Saito 2018 (MANN dog) — https://www.research.ed.ac.uk/en/publications/mode-adaptive-neural-networks-for-quadruped-motion-control , https://github.com/sebastianstarke/AI4Animation | unstructured single-dog mocap: walk, pace, trot, canter, jump, sit, turn, idle | "~10 minutes" (MDME); 4.5 s subset (AMP); 13,076 poses (Walk Like Dogs); WalkTheDog's dog set is 151k frames @60 fps (~42 min) — may be the raw capture | AI4Animation: "only for research or education purposes, and not freely available for commercial use"; mocap **CC BY-NC 4.0** | Peng 2020, AMP-hw, VIM, Walk Like Dogs, MDME, WalkTheDog |
| motion_imitation retargeted clips — https://github.com/erwincoumans/motion_imitation | dog_pace / dog_trot / dog_spin / dog_backward_trot already retargeted to Laikago/A1 | 4 clips (+ pretrained policies) | **Apache-2.0** code (clips derive from the dataset above) | Peng 2020 |
| RGBD-Dog (Kearney et al., CVPR 2020) — https://github.com/CAMERA-Bath/RGBD-Dog | 5 dogs × 5 motions (walk, trot, pole jump, pole walk, table step); BVH skeletons + markers; HD RGB 59.97 fps (8–10 cams) + Kinect ~6 fps (5–6) | 5 dogs, 5 motions each (frame count: 8,346 skeleton frames — snippet only, not verified) | academic use; release form to Prof. Cosker; companies case-by-case | pose estimation |
| AnimalML3D (OmniMotionGPT) — https://github.com/USRC-SEA/OmniMotionGPT | text-annotated animal animations on SMAL, 36 identities | 1,240 seqs, 3,720 captions | **MIT** | text→animal motion |
| QuadFM — https://github.com/GaoLii/QuadFM | Go2-native clips incl. real-dog mocap, teleop, artist, video-gen; emotion labels | 11,784 clips, 20.27 h | CC BY 4.0 planned; **not released** at fetch | Gen2Control |
| Quad-Imaginarium — https://github.com/GaoLii/Quad-Imaginarium | Go2 19-D trajectories from video diffusion | 7,488 clips, 18.5 h | **not released** (pending acceptance) | Uni-Mo |
| MoCapAct — https://github.com/microsoft/MoCapAct , https://arxiv.org/abs/2208.07363 | humanoid (dm_control CMU humanoid) expert rollouts | >3 h CMU; 600 GB large / 50 GB small | MIT code, **CDLA Permissive v2** data | pattern for "expert rollouts → generalist + GPT prior"; not a dog dataset |

---

## 8. Tooling status (fetched)

- Isaac Lab (https://isaac-sim.github.io/IsaacLab/main/source/overview/environments.html): `Isaac-Velocity-Flat/Rough-Unitree-Go2-v0` (rsl_rl + skrl PPO). **AMP environments exist only for the humanoid and only with skrl** ("AMP training is only available with the skrl library"). Motion tracking env only for Digit loco-manip.
- unitree_rl_lab (https://github.com/unitreerobotics/unitree_rl_lab): **Apache-2.0**; Go2, H1, G1-29; Isaac Lab 2.3.0 / Isaac Sim 5.1.0; sim2sim in **MuJoCo**; sim2real deploy; references `whole_body_tracking` (BeyondMimic) for motion tracking.
- beyondAMP (https://github.com/Renforce-Dynamics/beyondAMP): AMP wrapper for rsl_rl in Isaac Lab, plus an **mjlab (MuJoCo-Warp) backend**; NPZ motions aligned with BeyondMimic conventions; G1 and "dog" tasks (AMP Dog Move, AMP Knee Walk); license not shown.
- AMP_for_hardware: MIT, but pinned to Isaac Gym Preview 3 / PyTorch 1.10 (legacy).
- motion_imitation: Apache-2.0, PyBullet, MPI-parallel PPO.
- BeyondMimic whole_body_tracking: MIT, Isaac Lab 2.1.0 / Isaac Sim 4.5.

---

## 9. Assessment: what is trainable, and the most practical label → Go2 whole-body path

### 9.1 The design space, ordered by how the style signal enters

1. **Label → fixed vendor action** (Unitree SportClient). Zero training, ~40 actions, no blending, no continuous affect. This is Parcel today.
2. **Label → contact pattern → gait policy** (SayTap). 15 GPU-minutes; gait/tempo only.
3. **Label → one-hot/latent skill → single conditioned policy** (CAMP on Go2 in ~7 h/4060 Ti; VIM on A1; ASE/CALM in graphics). Requires a reference clip per skill; scales to tens of skills; transitions are learned.
4. **Label → clip → reference-conditioned tracker** (ExBody2 on G1/Orin NX; QuadFM single tracker on Go2/Orin; Uni-Mo per-clip trackers on Go2, 96.7% real success). Scales to thousands of clips if the tracker is universal; the "label → clip" step can be a lookup, a retrieval (WalkTheDog phase manifold), or a text-to-motion generator (MotionGlot/MotionGPT-style, 2 Hz onboard in QuadFM).
5. **Label → continuous style knobs on one policy**: reward-weight conditioning (AMOR, 7 objectives) or gait-parameter blending (Disney stylized gaits). Best for *intensity* ("more excited", "calmer") layered on any of 3–4.
6. **Continuous embedding of a live performance** (MDME on ANYmal D, retargeting-free): needed only if the style source is a human demonstrator in real time.

### 9.2 The most practical path for Parcel (Go2, no hardware today, RTX 5000 Ada 32 GB, MuJoCo)

The published evidence converges on a **two-layer stack**: a kinematic *expression/animation layer* that owns style and is cheap to change, and a single robust *tracking policy* that owns balance and is expensive to train once. Concretely:

- **Reference clips (the vocabulary).** Build a Go2-native clip library of 30–100 short clips (3–10 s), each tagged with (category, affect, intensity): gaits (walk/trot/pace/bound at 2–3 tempos), postures (sit, lie, bow/play-bow, stretch), gestures (Hello, head-tilt via Euler, "chuckle" = rhythmic body bounce, "look back" = yaw + pitch toward the owner's bearing while stepping), and transitions. Sources ranked by license: (a) hand-authored keyframes in MuJoCo + MJPC/IK cleanup (Walk-Like-Dogs retargeting recipe, Spot `.cha`-style keyframe format); (b) the Apache-2.0 motion_imitation dog clips; (c) Zhang 2018 dog mocap (CC BY-NC — fine for research, flag for any commercial use); (d) QuadFM / Quad-Imaginarium when released. Filter every clip by sim trackability (ExBody2 τ-style threshold; Uni-Mo multi-gate).
- **Tracker (the one expensive model).** One reference-conditioned PPO tracker (BeyondMimic-style rewards; observation = proprioception history + a short future window of the reference, as in QuadFM/ExBody2), trained across the whole library with domain randomization on the official Go2 MJCF in MuJoCo (Uni-Mo trained Go2 trackers in MuJoCo with 4,096 envs on one RTX 3090; the 32 GB Ada card is more than enough). Add an AMP-style discriminator on the dog clips as a naturalness prior (AMP-hw: 4.5 s sufficed; w_style 0.65). Budget: CAMP's 7 h (4 skills) to AMP-hw's 16 h (one V100) to QuadFM's 2×3090 × 20k iterations — i.e. overnight, not weeks, for a first tracker. Expect sim success ≥95% on curated clips (Uni-Mo 97.6%) and plan a real-robot acceptance test of ≥50 clips × 5 trials (Uni-Mo protocol) when hardware arrives.
- **Style selector (the trainable head).** Start with the deterministic map (affect label, intensity, conversation phase) → clip id + tempo scale + Euler/velocity modifiers — this alone already exceeds the fixed five-command list. Then train a small tokenized text/affect → motion head (MotionGlot recipe: per-embodiment VQ-VAE codebook ≈128×512 + GPT-2-small; QuadFM ran its generator at 2 Hz on an Orin) over the *same* clip library so novel phrasings ("do a little happy shuffle") land on plausible motions. This head is what the owner's "learn to chuckle when a joke was funny" ultimately conditions: the affect estimator output is an input token, and the owner's reaction is the training signal for which clip/latent gets selected (EMOTION++ shows ~1.9 feedback rounds move gesture ratings significantly).
- **Continuous affect knobs.** Expose 2–3 AMOR-style weights (smoothness/energy, root-motion tracking vs posture tracking) or gait-parameter offsets (tempo, body height, step height) so "intensity" is continuous without retraining; ELEGNT's temporal kinesics (speed, pauses, jerk) map directly onto these.
- **Full-duplex composition.** Copy Disney's layering: a background loop (breathing/idle — already in Parcel's expression layer) + triggered episodic clips (chuckle, bow) + procedural modification from live commands (velocity, look-at yaw/pitch); the tracker runs continuously at 50 Hz (Parcel's body-intent lane already runs at 50 Hz), and clip switches happen at phase boundaries. The deterministic safety layer stays as the final arbiter exactly as the Disney and Spot stacks keep a fall-recovery/robustness layer below choreography.
- **"Look back at the owner when lost."** No published quadruped source learns this; the primitives exist — ELEGNT's attention/intention gaze primitives, Go2 Euler attitude, a "turn head/body toward bearing" clip — and the *trigger* (localization confidence drop) is a world-state feature. Treat it as a learned selector rule (bandit/contextual policy over clips) with the clip itself authored.

### 9.3 What this means for the 12-hour experiment
- Feasible in 12 h on the desktop: (1) author ~10 Go2 keyframe clips in MuJoCo (including chuckle, play-bow, look-back, sad-slow-walk, happy-trot) and retarget 2–4 motion_imitation dog clips to the Go2 MJCF; (2) train a one-hot/latent-conditioned tracker over them (CAMP-scale, hours); (3) measure sim tracking error and success per clip (Uni-Mo criterion); (4) wire a label → (clip, tempo, Euler offset) selector to the conversation affect signal and log which clip fires per utterance. Not feasible in 12 h: a universal tracker over thousands of clips, or any real-robot evidence.
- The refuted `Go2Env` (research/20260828/rl-env-readiness) is the blocker for step 2; the fetched evidence says the working substrate is either Isaac Lab (unitree_rl_lab, Apache-2.0) with MuJoCo sim2sim, or MuJoCo-native RL as Uni-Mo did.

---

## 10. Load-bearing claims (each rests on one fetched primary source unless noted)
1. A single tracker conditioned on a reference window runs on an Orin-class computer at 50 Hz with ~0.1 rad joint error — ExBody2 (G1, Orin NX). Corroborated on Go2 by QuadFM (single tracker at 50 Hz on Jetson Orin, ~500 ms speech-to-motion).
2. Large expressive, non-gait vocabularies are trackable on the Go2: 96.7% real success over 392 clips × 5 trials — Uni-Mo (single source).
3. Categorical label → Go2 gait/skill switching is a ~7 GPU-hour problem with a one-hot skill discriminator — CAMP (single source); latent-skill version on A1 — VIM.
4. A few seconds of dog mocap as an adversarial style prior yields natural, energy-efficient gaits (CoT 0.93–1.12 vs 1.37–1.54) — AMP-for-hardware (single source).
5. Expressive motion measurably improves social interaction ratings (M 56 vs 29, p<0.0001, N=21) — ELEGNT (single source, lamp not dog).
6. The animation-layer + RL-tracker architecture survives ~10 h of live operation without falls — Disney RSS 2024 (single source, biped).

## 11. Open questions
- Will QuadFM (CC BY 4.0 planned) or Quad-Imaginarium actually be released, and in what skeleton/frame-rate convention (paper 50 Hz vs README 24 fps)?
- Is the CC BY-NC 4.0 dog mocap (Zhang 2018) acceptable for Parcel's intended use? Every quadruped imitation paper above depends on it.
- Latency of a text→motion head on the AGX Orin 64 GB alongside the existing local models (QuadFM: 2 Hz generator, ~500 ms end-to-end with cloud ASR; EMOTION: 26.8 s with GPT-4o — unusable live).
- Universal tracker vs per-clip policies on Go2: Uni-Mo used per-clip PPO; QuadFM a single tracker; no paper reports both on the same Go2 clip set.
- No source learns *when* to express (outcome-conditioned selection from owner reactions); the closest is EMOTION++'s human-feedback refinement (1.9 rounds). This is Parcel's novelty, not a literature gap that a paper fills.
- Head/gaze: the Go2 has no neck; Disney's 4-DoF head and ELEGNT's gaze primitives carry much of the expressiveness. Body Euler + camera pan may or may not read as "attention" to owners — needs a user test.

## 12. Fetch log (all read on 2026-08-28)
arXiv abs/html: 2306.07580 (+v1 html), 2501.05204 (+html), 2501.12493v1, 2412.13196 (+html), 2310.01408 (+v3 html), 2407.18946 (+ar5iv), 2410.16623 (+html), 2311.18303, 2203.15103 (+ar5iv), 2004.00784 (+ar5iv), 2507.00677 (+html), 2509.21810 (+html), 2402.16796 (+v1 html), 2505.23708 html, 2606.28237 html, 2603.24021v1 html, 2512.07673 (+html), 2410.23234 (+html), 2208.07363, 2104.02180, 2205.01906, 2305.02195, 2306.14795, 2306.08647, 2312.14457, 2412.15576, 2508.08241.
Project/vendor/code pages: saytap.github.io; rchalyang.github.io/VIM; xbpeng.github.io Robotic_Imitation; exbody2.github.io; peizhuoli.github.io/walkthedog; ivl.cs.brown.edu MotionGlot; la.disneyresearch.com (stylized gaits, AMOR); research.google AMP pub; research.ed.ac.uk MANN; dev.bostondynamics.com choreography_service / move_reference / animation_file_specification; github: spot-sdk choreography README, unitree_sdk2 (+sport_client.hpp raw), unitree_sdk2_python, unitree_rl_lab, Renforce-Dynamics/beyondAMP, escontra/AMP_for_hardware, erwincoumans/motion_imitation, sebastianstarke/AI4Animation, USRC-SEA/OmniMotionGPT, microsoft/MoCapAct, CAMERA-Bath/RGBD-Dog, PeizhuoLi/walk-the-dog, GaoLii/QuadFM, GaoLii/Quad-Imaginarium, HybridRobotics/whole_body_tracking, OpenMotionLab/MotionGPT, chengxuxin/expressive-humanoid, sudarshan-s-harithas/MotionGlot; isaac-sim.github.io IsaacLab environments; frontiersin.org fnbot.2026.1855550.
Failed: dl.acm.org (403 ×2), arxiv.org/pdf 2407.18946 and 2203.15103 (>10 MB), Disney stylized-gaits PDF (unparseable), openreview (verification page), ieeexplore (empty), researchgate (403).
