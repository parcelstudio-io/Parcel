# Simulation platforms and procedures for training a companion quadruped's social + physical behavior

Date: 2026-08-28. Author: research subagent (Fable 5). Scope: platforms and
procedures for TRAINING (not just evaluating) a Go2 companion's locomotion,
expression, social decision, and dialogue layers in simulation; where the
"owner" can be an LLM agent vs scripted vs recorded; sim-to-real evidence for
EXPRESSIVE (not just locomotion) motion on Go2/Go1/Spot.

Method: every source below was fetched and read on 2026-08-28 (WebFetch);
nothing is cited from memory. Numbers are quoted as extracted. Where a fetch
returned only an abstract, that is stated. The WebSearch budget ran out
mid-task, so a few desired sources (Isaac Sim benchmark page, DFM dance paper,
SOTOPIA-RL) were not reached; they are listed under "Open questions".

Local facts that shape the recommendation (checked in this tree):
`.parcel/bin/python` has `mujoco 3.11.0`; `mujoco.mjx` is NOT importable in the
venv; `research/20260828/rl-env-readiness/VERDICT.md` refuted the checked-in
`Go2Env` as a training substrate (2/9 gates) and the report already chose
"official Go2 Isaac Lab -> MuJoCo loop"; `src/parcel_robot/motion/expression.py`
carries `IdleLayer` (breathing 0.25 Hz, 4 mm) and `ExpressionGate`.

---

## 0. Quick answer

| Question | Answer (evidence below) |
|---|---|
| Which sim trains the Go2 body fastest on one GPU? | GPU MuJoCo (MJX / MuJoCo Warp via mjlab) or Isaac Lab. Go1 joystick: 417k env-steps/s on an A100 (MJX, Playground); Go1 flat 4096 envs: mjlab 190k vs Isaac Lab 240k steps/s (community benchmark); Spot in Isaac Lab: 85-95k FPS, 4096 envs, ~4 h for 15k iterations on an RTX 4090. |
| Does any of them simulate people? | Habitat 3.0 (SMPL-X avatars, 12 base models, AMASS clips, 136 FPS robot+humanoid single env, 1191 FPS across 16 envs), MetaUrban (1,100 rigged humans, 2,314 BEDLAM motions, Spot "robot dog" agent), Isaac Sim IRA (GoTo/Idle/LookAround/Sit/Queue characters; omni.anim.people deprecated). None simulate SPEECH. |
| Does any of them simulate audio? | Only SoundSpaces 2.0 / habitat-sim audio sensor (ray-traced acoustics, 7 mic layouts incl. ambisonics/binaural). It is CPU-bound: 0.9-33.5 FPS. Usable for mic-array/DoA data, not for RL inner loops. |
| Go2 asset? | Isaac Lab (`Isaac-Velocity-Flat/Rough-Unitree-Go2-v0`, DCMotor 23.5 N m), unitree_rl_lab (Isaac Lab), unitree_rl_mjlab (MuJoCo, `Unitree-Go2-Flat`), unitree_rl_gym (Isaac Gym, BSD-3), mujoco_menagerie `unitree_go2` (BSD-3, MJX variant), Genesis `examples/locomotion/go2_train.py` (4096 envs). NOT in MuJoCo Playground, Habitat, MetaUrban, ProcTHOR. |
| Has expressive (non-locomotion) motion transferred to a real Go2? | Yes: Uni-Mo (2026) 392 generated motions x 5 trials on a real Go2, 96.7% success, tracking policy trained in MuJoCo/MjLab; STMR (2024) dog-mocap + animator clips on Go1/Go2/AlienGo/B2, 48.7 mm keypoint error, 1 h on an A6000. |
| Can an LLM stand in for the owner? | For dialogue/social decisions yes, with known biases: SOTOPIA-pi shows the LLM-judge/human gap widens when you optimise against the judge (5.71 GPT-4-rated vs 4.29 human-rated); "better assistants yield worse simulators" (GPT-4o eval drops 74.6% -> 57.4% under a purpose-built User LM); fine-tuned-on-real-humans simulators beat role-play prompting (58%/57% win rates). tau-bench uses gpt-4-0613 as the user; tau2-bench adds full-duplex VOICE user simulation over realtime APIs (OpenAI, Gemini, xAI). |
| LLM-generated rewards/curricula? | Eureka: 29 tasks, 10 morphologies, beats human rewards on 83%, +52% normalised; Eurekaverse: GPT-4o curricula for Go1 parkour, 24 h on 8x A6000, ~$15 API, real jumps to 75 cm. |

---

## 1. Habitat 3.0 (Meta) - humanoid avatars, social navigation, human-in-the-loop

Source: arXiv 2310.13724 (abstract + full HTML), https://arxiv.org/abs/2310.13724 and https://arxiv.org/html/2310.13724 ; project page https://aihabitat.org/habitat3/ ; code https://github.com/facebookresearch/habitat-lab (MIT).

What it simulates: a Spot robot plus SMPL-X humanoid avatars in indoor scenes;
RGB/depth sensing; no audio, no speech (the paper never mentions audio).

Numbers (quoted from the paper):
- Avatars: "a library of avatars made from 12 base models with multiple gender representations, body shapes, and appearances"; body "J in R^109 ... beta in R^10" (SMPL-X).
- Motion: "we use a walking motion clip from the AMASS dataset, trim it to contain a single walking cycle and play it cyclically until reaching the next waypoint"; pick/place via VPoser pre-computed poses. i.e. cached kinematic motion, not a learned humanoid controller.
- Speed: "a robot operates at 245+-19 frames per second (FPS) in a single environment, while the humanoid achieves 188+-2 FPS"; "robot-robot achieves a frame rate of 150+-13, while robot-humanoid achieves 136+-8"; "robot-humanoid reaching 1191+-3 FPS across 16 environments on a single GPU".
- Social Navigation task: "a humanoid walks in a scene, and the robot must locate and follow the humanoid while maintaining a safety distance ranging from 1 m to 2 m". Metrics: Finding Success S, SPS, Following rate F, Collision rate CR. Observations: "egocentric arm depth, a humanoid detector, and a humanoid GPS".
- Training: DD-PPO, "200 million environment steps (roughly 4 days of training)" on "4 NVIDIA A100 GPUs", "24 parallel environments" per GPU, 128 steps per update, lr 1e-4.
- Results (test): Heuristic expert S 1.00 / SPS 0.97 / F 0.51 / CR 0.52; End-to-end RL S 0.97+-0.00 / SPS 0.65 / F 0.44+-0.01 / CR 0.51+-0.03.
- Social Rearrangement with unseen partners: "Plan-pop3,4 have the highest ZSC-pop-eval SR of 71.7%".
- Human-in-the-loop: "30 participants", mouse/keyboard or VR; with real humans "Plan-Pop3 and Learn-Single improve RE to 123% and 134% respectively"; success 1.0 across episodes.
- Project page: avatars can be animated "with your own motion, via motion capture, or using off-the-shelf text to motion models".

Assessment: the best open, MIT-licensed "person walks around a house, robot must
keep track of them" trainer. Exactly the substrate for the "look back at the
owner when lost" behaviour at the decision level. Caveats: no Go2 asset (Spot
is the quadruped), humanoid motion is canned, training budget for the end-to-end
social-nav policy was 4 A100-days, and the RL policy still collides in ~51% of
episodes - the heuristic expert is as good, so a scripted follow controller plus
a learned "when to look back" head is the cheaper design.

## 2. SoundSpaces 2.0 / habitat-sim audio - the only acoustic simulator in this set

Sources: arXiv 2206.08312 (abstract + ar5iv full text) https://arxiv.org/abs/2206.08312 ; habitat-sim AUDIO.md https://github.com/facebookresearch/habitat-sim/blob/main/docs/AUDIO.md

- Engine: "bi-directional ray tracer based audio simulator" (RLRAudioPropagation) inside habitat-sim; "seven built-in microphone types, including mono, stereo, binaural, quad, surround_5_1, surround_7_1 and ambisonics"; custom arrays "by provide an array of mono microphones" (relevant to the XVF3800 4-mic array). Binaural uses an HRTF; edge diffraction limit 10 events (compile-time).
- Speed (CPU, "Xeon(R) Gold 6230 CPU with 2.10GHz"): high-quality "0.9 +-0.0 FPS (1 thread), 4.0 +-0.1 FPS (5 threads)"; high-speed "7.7 +-0.2 FPS (1 thread), 33.5 +-0.4 FPS (5 threads)".
- Sim2real: ASR fine-tuned on synthetic IRs: WER 29.10% -> 12.48%, vs 13.32% with real IRs. Continuous-space audio nav success "64.7 +-3.9%" vs "0.9 +-0.2%" for the grid version, 0.15 m steps.

Assessment: speech itself is never simulated by any platform here; SoundSpaces
gives room acoustics for TTS/recorded speech so the mic pipeline (DoA, "owner
called from behind") can be trained on synthetic far-field audio. It is far too
slow for a 50 Hz body-policy RL loop; use it offline to render an audio dataset.

## 3. MetaUrban (ICLR 2025 Spotlight) - pedestrians, crowds, a Spot "robot dog" agent

Sources: arXiv 2407.08725 (abstract + full HTML v2) https://arxiv.org/abs/2407.08725 ; GitHub https://github.com/metadriverse/metaurban (Apache-2.0); project page https://metadriverse.github.io/metaurban/

- Assets: "10,000 high-quality obstacles in real-world category distributions"; "1,100 rigged human models" (68 garments, 32 hairs, 13 beards, 46 accessories, 1,038 textures); "2,314 movements" per model ("2,311 unique movements" from BEDLAM). Objects from Objaverse-XL / OmniObject3D, humans from SynBody.
- Agents: "Delivery bot (COCO Robotics), electric wheelchair, mobility scooter, robot dog (Boston Dynamics Spot), and humanoid robot". Engine: Panda3D. README: "~60 FPS" and "~2GB GPU memory" on the static example; GPU >= 3 GB VRAM; tested on RTX 3090/4080/4090/A5000/V100.
- Baselines: PPO PointNav SR 66%, SPL 0.64, cost 0.51; PPO SocialNav SR 34%, SNS 0.64, cost 0.66. 7 baselines (PPO, PPO-Lag, BC, GAIL ...).
- License: code Apache-2.0, paper CC BY 4.0. No Go2, no audio, no speech.

Assessment: the richest open library of animated humans (2,314 motions x 1,100
bodies), but it is an outdoor-sidewalk, kinematic-agent simulator at ~60 FPS.
Useful as a source of human animation + crowd behaviour if Parcel ever trains
"walk beside the owner on a sidewalk"; not a body-level trainer.

## 4. Isaac Lab / Isaac Sim ecosystem (NVIDIA + Unitree)

### 4a. Isaac Lab Go2 environments and asset

Sources: environment list https://isaac-sim.github.io/IsaacLab/main/source/overview/environments.html ; Go2 config https://github.com/isaac-sim/IsaacLab/blob/main/source/isaaclab_assets/isaaclab_assets/robots/unitree.py ; performance page https://isaac-sim.github.io/IsaacLab/main/source/overview/reinforcement-learning/performance_benchmarks.html

- Go2 tasks: "Isaac-Velocity-Flat-Unitree-Go2-v0", "Isaac-Velocity-Rough-Unitree-Go2-v0" (also Go1, A1, Spot, ANYmal B/C/D). Imitation: "Isaac-Humanoid-AMP-Dance-Direct-v0", "...-Run-...", "...-Walk-..." (AMP via skrl) and "Isaac-Tracking-LocoManip-Digit-v0" - i.e. AMP/motion-tracking infrastructure exists but the shipped examples are humanoid.
- Go2 asset: `Robots/Unitree/Go2/go2.usd` on Nucleus; `DCMotorCfg` with `effort_limit=23.5`, `saturation_effort=23.5`, `velocity_limit=30.0`, `stiffness=25.0`, `damping=0.5`, `friction=0.0`; default pose hip +-0.1, thigh 0.8, calf -1.5. License header BSD-3-Clause.
- Throughput (RTX 4090, 4096 envs, `Isaac-Velocity-Rough-G1-v0`): 94,000 env-steps/s sim-only, 88,000 with inference, 82,000 with training; L40: 72k/64k/62k; 4x L40: 290k/270k/250k; memory 6.5 GB RAM / 6.1 GB VRAM. Cartpole 4096 envs: 1.1M/910k/510k. (The page has no Go2-specific row.)
- Spot example (NVIDIA blog https://developer.nvidia.com/blog/closing-the-sim-to-real-gap-training-spot-quadruped-locomotion-with-nvidia-isaac-lab/ ): "With 4,096 environments and 15,000 iterations, equivalent to approximately 4 hours of training time on the NVIDIA RTX 4090 GPU"; "85,000 to 95,000 frames per second (FPS)"; MLP [512, 256, 128], PPO; actions = 12 joint position targets; randomised mass, friction, random pushes; zero-shot on hardware, inference on a Jetson Orin.

### 4b. Unitree's official RL repos

- unitree_rl_lab https://github.com/unitreerobotics/unitree_rl_lab : "Currently supports Unitree Go2, H1 and G1-29dof robots"; badges IsaacSim-5.1.0 / Isaac Lab-2.3.0; sim2sim through `unitree_mujoco` before real deployment; Apache-2.0.
- unitree_rl_mjlab https://github.com/unitreerobotics/unitree_rl_mjlab : "built upon the mjlab, using MuJoCo as its physics simulation backend"; "currently supporting Unitree Go2, A2, As2, G1, R1, H1_2 and H2"; velocity tasks "Unitree-Go2-Flat, ..." and motion-imitation tasks such as "Unitree-G1-Tracking-No-State-Estimation"; Apache-2.0. THIS is the MuJoCo-native equivalent of unitree_rl_lab.
- unitree_rl_gym https://github.com/unitreerobotics/unitree_rl_gym : Isaac Gym Preview + legged_gym + rsl_rl, "supporting Unitree Go2, H1, H1_2, and G1", sim2sim in MuJoCo, sim2real via unitree_sdk2_python, BSD 3-Clause.
- unitree_sim_isaaclab https://github.com/unitreerobotics/unitree_sim_isaaclab : G1/H1-2 manipulation scenes only; "Go2 is not mentioned"; no social scenarios; Apache-2.0.

### 4c. mjlab and MuJoCo Warp (what unitree_rl_mjlab and Uni-Mo run on)

- mjlab https://github.com/mujocolab/mjlab : "combines Isaac Lab's manager-based API with MuJoCo Warp"; "requires an NVIDIA GPU for training"; Apache-2.0 (Isaac-Lab-derived utilities BSD-3).
- MuJoCo Warp https://github.com/google-deepmind/mujoco_warp : "GPU-accelerated version of the MuJoCo physics simulator, designed for NVIDIA hardware"; not yet supported: IMPLICITFAST, PGS/noslip solvers, PLUGIN actuators/sensors; Flex experimental; Apache 2.0.
- Community benchmark, Go1 flat terrain, https://github.com/mujocolab/mjlab/discussions/220 : after a corrected install, mjlab "190k steps/s" at 4096 envs (25% VRAM, 90% GPU, ETA 1 h 30 min) vs Isaac Lab "240k steps/s" at 4096 envs; a mis-installed mjlab ran at 11k vs 72k at 1024 envs. Maintainers caution the two stacks differ in network, sensors and collision geometry.

### 4d. People in Isaac Sim

Sources: https://docs.isaacsim.omniverse.nvidia.com/5.1.0/action_and_event_data_generation/ext_replicator-agent/ext_omni_anim_people.html ; .../actor_control.html ; .../tutorial_replicator_agent.html

- "Omni.Anim.People is being deprecated in the next release and we are replacing it with a better system"; replacement is Isaacsim.Replicator.Agent (IRA).
- IRA character commands: `GoTo` ("Character_02 GoTo 10 10 0 90"), `Idle` (seconds), `LookAround` ("moving its head from left to right"), `Sit` ("Character_03 Sit /World/Chair 5"), `Queue`. Robots: only "Nova Carter" and "iw.hub" (GoTo/Idle, LiftUp/LiftDown). Commands are a txt file, one line per agent; "Command injection ... only works while the simulation is running"; "IRA requires a NavMesh in the stage". The docs say nothing about characters reacting to a robot.

Assessment: Isaac Lab is the reference locomotion trainer with a Go2 asset and
Unitree's own sim2sim->sim2real path; its people system is a synthetic-data
tool (scripted GoTo/Idle), not a social partner, and it is being replaced. For
Parcel's desktop (RTX 5000 Ada 32 GB) the Isaac Sim install cost is the main
obstacle in a 12-hour window; unitree_rl_mjlab gives the same Go2 task on MuJoCo.

## 5. Genesis

Sources: README (raw, fetched 2026-08-28) https://raw.githubusercontent.com/Genesis-Embodied-AI/Genesis/main/README.md ; docs overview https://genesis-world.readthedocs.io/en/latest/user_guide/overview/what_is_genesis.html ; Go2 example https://github.com/Genesis-Embodied-AI/Genesis/blob/main/examples/locomotion/go2_train.py

- License: "The Genesis source code is licensed under Apache 2.0." Solvers: "Rigid, FEM, MPM, Particle (PBD / SPH), uipc, an explicit coupler, and SAP"; sensors incl. IMU, lidar, depth camera, contact force, tactile.
- Speed: the docs overview claims "10-80x faster than prior GPU-accelerated simulators such as Isaac Gym/Sim/Lab and MuJoCo MJX". The README fetched today contains NO FPS figure (the widely repeated "43 million FPS" claim was not present on any page I fetched, so I do not cite it).
- Go2: `go2_train.py` defaults `--num-envs 4096` ("Training throughput comes from the 4096 parallel environments, which need a GPU"), `rsl-rl-lib>=5.0.0` PPO, `--max-iterations 101`, `num_steps_per_env 24`, `episode_length_s 20.0`; rewards tracking_lin_vel 1.0, tracking_ang_vel 0.2, lin_vel_z -1.0, base_height -50.0, action_rate -0.005, similar_to_default -0.1. Also `examples/sensors/contact_force_go2.py`.

Assessment: usable Go2 locomotion path with a tiny script, but no published
sim-to-real on Go2 from the maintainers that I could fetch, no people, no audio,
and the speed claims are not benchmarked on a page I could read. Second choice
behind MuJoCo-Warp/mjlab for Parcel because Parcel already standardises on MuJoCo.

## 6. MuJoCo Playground / MJX / Menagerie Go2

Sources: arXiv 2502.08844 (full HTML) https://arxiv.org/html/2502.08844 ; repo https://github.com/google-deepmind/mujoco_playground (Apache-2.0); site https://playground.mujoco.org/ ; Menagerie Go2 https://github.com/google-deepmind/mujoco_menagerie/tree/main/unitree_go2

- Quadruped envs: Go1 Joystick (flat/rough), Go1 Getup, Go1 Handstand, Go1 Footstand, Spot Joystick, Barkour Joystick. "No Go2 is mentioned" in the paper or on the site.
- Throughput (A100, env-steps/s): Go1 Joystick Flat "417451 +- 2955"; Go1 Handstand "204416 +- 738"; Go1 Footstand "204578 +- 906"; Go1 Getup "96173 +- 230"; Spot Joystick "404931 +- 2710"; Barkour "385920 +- 2162"; Berkeley Humanoid 120,145. Pixels: CartpoleBalance ~403k, Franka PickCube ~37k.
- Wall clock: Go1 joystick flat "within 5 minutes (2x RTX 4090)"; Berkeley Humanoid "under 15 minutes"; G1/T1 "under 30 minutes"; LEAP reorient "within 30 min"; LeapCubeReorient 1x 4090 ~2080 s vs 8x H100 ~670 s.
- Sim-to-real: Go1 joystick/handstand/footstand/getup deployed on grass, concrete, indoors; Franka pixels 100% in 12 trials; non-prehensile 100% in 35 trials. License CC BY 4.0 (paper), Apache-2.0 (code).
- Menagerie `unitree_go2`: BSD-3-Clause, derived from Unitree's `go2_description` URDF, foot contacts softened, separate MJX variant using sphere collision geometry "due to MJX's current limitations with non-sphere collision shapes".

Assessment: the canonical "minutes on one GPU" result. Go2 is a Menagerie
swap-in for the Go1 envs (same 12-DoF layout); the Go1 numbers are the
expected order of magnitude for a Go2 port. Note the local venv has no `mjx`
import today; MuJoCo Warp (mjlab) is the more current GPU path.

## 7. ProcTHOR / AI2-THOR - procedural homes

Sources: arXiv 2206.06994 (abstract + ar5iv full) https://arxiv.org/abs/2206.06994 ; repo https://github.com/allenai/procthor (Apache-2.0)

- "10,000 fully interactive houses" (+1,000 val, +1,000 test); "16 different scene specifications"; "1633 fully interactable instances" across "108 object types".
- Speed (single GPU, 15 processes): navigation "1,427+-74 FPS" and "6,280+-40 FPS" (paper reports per-house-size and per-operation rates; treat as ~1.4-6k FPS aggregate).
- Downstream: Habitat 2022 ObjectNav ">3 point gain in SPL"; RoboTHOR ObjectNav "8.8 point improvement in SPL"; AI2-THOR Rearrangement 0.19 -> 0.245.

Assessment: the cheapest way to get thousands of distinct apartments for a
"where did the owner go / navigate home layout" curriculum; Unity-based, no
Go2 physics, no people (pair with Habitat 3.0 or IRA for humans).

## 8. LLM-driven user / owner simulators

### 8a. SOTOPIA and SOTOPIA-pi (social RL with LLM partners and LLM judges)

Sources: arXiv 2310.11667 (full HTML) https://arxiv.org/html/2310.11667 ; arXiv 2403.08715 (abstract + full HTML) https://arxiv.org/html/2403.08715 ; repo https://github.com/sotopia-lab/sotopia (MIT)

- SOTOPIA: "90 social scenarios", "40 characters", "five types of relationships" -> "450 tasks"; SOTOPIA-Eval = Goal [0-10], Believability [0-10], Knowledge [0-10], Secret [-10-0], Relationship [-5-5], Social Rules [-10-0], Financial [-5-5]; SOTOPIA-hard "20 challenging tasks"; GPT-4 goal 4.85 vs humans 5.95 on hard; human eval "Two hundred episodes", Randolph kappa 0.503.
- SOTOPIA-pi: Mistral-7B; "100 social tasks ... per round", 10 interactions per task; behaviour cloning + self-reinforcement on GPT-4-filtered episodes. Goal on hard tasks, GPT-4-rated: base 3.25 -> 5.71 (GPT-4 expert 5.89); human-rated: 2.89 -> 4.29 (GPT-4 expert 5.25). MMLU 49.21% -> 48.57%; toxic words 0.9 vs 3.6. Authors report "an increasing gap between GPT-4-based and human evaluation" as the model optimises against the judge.

### 8b. tau-bench / tau2-bench (LLM user simulators, incl. full-duplex voice)

Sources: arXiv 2406.12045 (abstract + full HTML) https://arxiv.org/html/2406.12045 ; repo https://github.com/sierra-research/tau2-bench (MIT)

- tau-retail "115" tasks, tau-airline "50"; user simulated by "gpt-4-0613" from a task instruction + full history; pass^k = E[C(c,k)/C(n,k)]; gpt-4o pass^1 61.2 (retail) / 35.2 (airline); "pass^8 < 25%" on retail. Acknowledged simulator limits: typos/ambiguity in instructions, missing domain knowledge, "limited capacity at reasoning, calculation, long-context memorization".
- tau2-bench: domains `mock, airline, retail, telecom, banking_knowledge`; "End-to-end voice evaluation with realtime providers (OpenAI, Gemini, xAI)" as a full-duplex "Audio Native" mode (`uv sync --extra voice`); LLM user with persona/instructions; MIT.

### 8c. User LMs, simulator utility, and survey findings

- "Flipping the Dialogue" (User LMs) https://arxiv.org/abs/2510.06552 : "better assistants yield worse simulators"; "the performance of a strong assistant (GPT-4o) drops from 74.6% to 57.4%" when evaluated against User LMs instead of assistant-based simulators.
- "Quantifying the Utility of User Simulators for Building Collaborative LLM Assistants" https://arxiv.org/abs/2605.09808 : measure simulators by "how an LLM assistant trained with this user simulator performs in the wild when interacting with real humans"; assistants trained against fine-tuned simulators win "58% over the initial and 57% over the one trained against role-playing".
- Survey on LLM-based conversational user simulation https://arxiv.org/html/2604.24977v1 : five families (prompting, RAG, fine-tuning, RL/DPO, hybrid); failure modes: persona "drift in style, beliefs, or goals", "Simulated users are also unrealistically cooperative", and "overly polite, homogeneous behavior".
- UserLM-R1 https://arxiv.org/abs/2601.09215 : user LM trained with SFT + multi-reward RL, "outperforms competitive baselines, particularly on the more challenging adversarial set" (abstract only, no numbers).
- Personality-aware RL for persuasion https://arxiv.org/abs/2601.06877 : Dueling Double DQN policy trained against "an agenda-based LLM simulation pipeline", PersuasionForGood; reports "LLM-driven simulation enhances generalization to unseen user behaviors" (abstract only).
- HRI systematic review https://arxiv.org/html/2602.15063v1 : "86 studies"; Pepper/Nao/Furhat dominate; the review surfaces no study that trains a robot against LLM-simulated humans (only ChatGPT-generated feedback data) - i.e. "sims for HRI" is still an open gap in the literature.
- "LLM Social Simulations Are a Promising Research Method" https://arxiv.org/abs/2504.02234v2 : "can already be used for pilot and exploratory studies"; "results to date have been limited".

Assessment (load-bearing for the owner-sim design): an LLM owner is fine for
generating diverse dialogue + affect events and for shaping a decision policy,
but (i) it is too cooperative and homogeneous, (ii) a judge-optimised policy
inflates judge scores more than human scores, and (iii) simulators fine-tuned
on real owner transcripts transfer better than prompted role-play. Every
Parcel learned-social loop therefore needs a small recorded-owner calibration
set and a human-rated hold-out, not just an LLM judge.

## 9. Human motion synthesis into sim

- HumanML3D https://github.com/EricGuo5513/HumanML3D : "14,616 motions and 44,970 descriptions ... 5,371 distinct words", "28.59 hours", 20 fps, clips 2-10 s (mean 7.1 s), SMPL 22 joints; repo MIT (underlying AMASS/HumanAct12 terms apply).
- Habitat 3.0 project page: avatars can be driven by "off-the-shelf text to motion models" (i.e. a HumanML3D-trained generator -> SMPL-X -> Habitat avatar is the documented path).
- MetaUrban: 2,311 BEDLAM motions on 1,100 SynBody rigs.
- MDME (Dec 2025) https://arxiv.org/abs/2512.07673 : embeds "AMASS dataset parametrized using the SMPL body model" and a "dog training dataset" of "approximately 10 minutes of motion" augmented to "52 minutes"; PPO in Isaac Lab; runs "at 50 Hz in both simulation and on physical hardware"; robots ANYmal D (quadruped), H1 (sim), Fourier N1 (hardware); 30k/40k PPO iterations; zero-shot novel styles.

Assessment: text-to-motion gives unlimited owner gestures (wave, crouch, point,
laugh) for the avatar side; for the dog side, quadruped motion data is scarce
(10 min of dog mocap in MDME, six clips in STMR) - which is exactly why Uni-Mo's
video-prior pipeline (7,488 clips) matters.

## 10. LLM-generated rewards and curricula

- Eureka https://arxiv.org/abs/2310.12931 + https://github.com/eureka-research/Eureka : "29 open-source RL environments that include 10 distinct robot morphologies, Eureka outperforms human experts on 83% of the tasks, leading to an average normalized improvement of 52%"; Isaac Gym Preview 4; defaults 16 samples x 5 iterations; gpt-4-0314; MIT.
- Eurekaverse https://arxiv.org/html/2411.01775 + https://github.com/eureka-research/eurekaverse : "GPT-4o"; Unitree Go1 (12 DoF), Isaac Gym / legged_gym / Extreme Parkour; "5 iterations of generation, each with 8 parallel policy training runs of 2000 steps"; "around 24 hours on 8 A6000 GPUs ... OpenAI API cost of around $15"; real: "jumps up to 75cm", "climbing up over 50cm", "30 degree ramp", 10 trials per difficulty, four unseen courses; MIT.

Assessment: proven for locomotion rewards/terrains. For social rewards the
analogous move is "LLM writes the reward for chuckle timing", which inherits the
judge-gap problem from 8a; keep LLM-written rewards for the physical layers
and use them only as proposals (human-approved) for the social layer.

## 11. Sim-to-real for EXPRESSIVE motion on Go2 / Go1 / Spot / aibo

- Uni-Mo (June 2026) https://arxiv.org/html/2606.28237 : LLM proposes prompts -> "Wan2.2-I2V-A14B" video diffusion (LoRA fine-tuned on 56 H20 GPUs) -> "ViTPose ... fine-tuned on rendered images" + "URDF-anchored optimization" -> PPO tracking policy "following the BeyondMimic setup, re-implemented in MuJoCo with the MjLab infrastructure", one RTX 3090 per motion. Dataset Quad-Imaginarium "7,488 quadruped motion clips at 24 fps, totaling 18.5 hours"; sim success 97.6%; real Go2: "392 motions ... executed each K=5 times ... 96.7% deployment success rate". CC BY 4.0.
- STMR (2024) https://arxiv.org/html/2404.11557 : dog mocap + animator-authored clips; Isaac Gym; deployed on "Go1, Go2, AlienGo, and B2"; six motions (Trot0/1, Pace0/1, SideSteps, HopTurn); keypoint error "48.7 mm" vs 88.4-275.3 mm baselines; "approximately 50 million data samples requiring one hour of training with NVIDIA RTX A6000 GPU".
- Peng et al. 2020 https://arxiv.org/abs/2004.00784 (canonical): "18-DoF quadruped", imitation of animal reference motion + "sample efficient domain adaptation", gaits "to dynamic hops and turns".
- AMP 2021 https://arxiv.org/abs/2104.02180 (canonical): discriminator "style-rewards" from "unstructured motion clips", task reward separate - the standard recipe for "natural-looking" expression without per-clip tracking.
- Spot RL (RAI, ICRA 2025) https://arxiv.org/html/2504.17857v1 : Isaac Lab + RSL_RL; "5.2m/s in a flying trot" vs default "1.6m/s"; sim parameters tuned by Wasserstein/MMD + CMA-ES against hardware data; code open. (Locomotion, not expression, but the only open Spot RL sim-to-real.)
- Spot Choreography SDK https://dev.bostondynamics.com/docs/concepts/choreography/readme : scripted, music-synchronised moves via Choreographer; "requires a special-permissions license" - the vendor baseline for expressive quadruped motion is authored, not learned.
- aibo quiet walking (ICRA 2025) https://arxiv.org/abs/2502.10983 : Sony's home dog robot, RL that minimises foot contact velocity with learned per-joint PD gains and contact sensors; "superior quietness compared to a RL baseline and the carefully handcrafted Sony commercial controllers". Relevant because a companion in a home must also be quiet.
- Isaac Lab AMP envs (section 4a) provide the AMP trainer, humanoid examples only.

Assessment (load-bearing): expressive motion on a real Go2 is a solved
tracking problem when a kinematic reference exists (96.7% over 392 motions;
48.7 mm error). The bottleneck is the reference library, and the 2026 answer is
generated video priors (7,488 clips) rather than mocap. Parcel's "chuckle",
"bow", "stretch", "look back" can be authored or generated as references and
tracked by one policy in MuJoCo/mjlab - the same stack Uni-Mo used.

---

## 12. Cross-platform comparison

| Platform | Physics for Go2 | People | Audio / speech | Go2 asset | 1-GPU throughput (quoted) | License |
|---|---|---|---|---|---|---|
| MuJoCo Playground (MJX) | yes (12-DoF quadrupeds) | no | no | Go1/Spot/Barkour only; Go2 via Menagerie | Go1 joystick 417k steps/s (A100); train in 5 min on 2x4090 | Apache-2.0 / CC BY 4.0 |
| MuJoCo Warp + mjlab / unitree_rl_mjlab | yes | no | no | `Unitree-Go2-Flat` | Go1 flat 190k steps/s at 4096 envs (community) | Apache-2.0 |
| Isaac Lab (+ unitree_rl_lab) | yes | IRA scripted characters (deprecated people ext) | no | `Isaac-Velocity-*-Unitree-Go2-v0` | G1 rough 94k/82k steps/s (4090); Go1 flat 240k (community); Spot 85-95k FPS, ~4 h | BSD-3 / Apache-2.0 |
| Genesis | yes | no | no | `go2_train.py` (4096 envs) | "10-80x faster than Isaac Gym/Sim/Lab and MJX" (no figure on fetched pages) | Apache-2.0 |
| Habitat 3.0 | Spot kinematic/dynamic, no Go2 | SMPL-X avatars, 12 base models, AMASS clips, HITL VR/keyboard | no (audio via SoundSpaces) | no | 136 FPS robot+humanoid single env; 1191 FPS / 16 envs | MIT |
| SoundSpaces 2.0 | n/a | n/a | ray-traced acoustics, 7 mic layouts; no speech generation | no | 0.9-33.5 FPS (CPU) | open (habitat-sim) |
| MetaUrban | kinematic agents incl. Spot | 1,100 rigged humans, 2,314 motions | no | no | ~60 FPS | Apache-2.0 |
| ProcTHOR / AI2-THOR | Unity, no Go2 | no | no | no | 1.4-6.3k FPS / 15 procs | Apache-2.0 |
| SOTOPIA / tau2-bench | none | LLM personas | tau2 voice via realtime APIs | n/a | LLM-bound | MIT |

---

## 13. Layered simulation design for Parcel

Principle from the evidence: no single simulator covers body + people + speech.
Train each layer where its throughput lives, and connect layers by contracts
(skills, intents, events) - which matches the existing 50 Hz body-intent lane,
expression layer, reaction arbiter and deterministic safety layer.

### L0 - Locomotion + whole-body tracking (physics, 100k+ steps/s)
- Simulator: MuJoCo Warp via mjlab / unitree_rl_mjlab (`Unitree-Go2-Flat`) on the RTX 5000 Ada; Menagerie `unitree_go2` (BSD-3) as the model; Isaac Lab `Isaac-Velocity-Rough-Unitree-Go2-v0` only as the cross-simulator transfer check the readiness verdict already asks for.
- Trains: velocity tracking, fall recovery / getup, and ONE motion-tracking policy over a clip library (Uni-Mo/STMR recipe). Expected cost: a Go1-class joystick policy in tens of minutes; a tracking policy ~1 h/clip-set (STMR: 50M samples, 1 h, A6000).
- Owner: absent. Domain randomisation: mass/payload, friction, motor strength, latency, pushes (Isaac Lab Spot recipe).

### L1 - Expression vocabulary (kinematic references -> L0 tracking)
- References: author 5-10 clips (chuckle = 2-4 Hz body-height/pitch oscillation + head bob; bow; stretch; look-back = yaw head/torso toward last owner bearing; nod) as keyframes, or generate them with a video-prior pipeline (Uni-Mo) or retarget dog mocap (STMR). Style regulariser: AMP discriminator on the clip set so composed motions stay dog-like.
- Output contract: parameterised skills (intensity 0-1, duration, gaze target) exposed to the 50 Hz lane - replacing the fixed command list.
- Owner: absent; safety layer stays authoritative (clip tracking never bypasses it).

### L2 - Social decision / body-intent policy (abstract or Habitat-style sim, 1-10 Hz decisions)
- Simulator: a lightweight kinematic world (Habitat 3.0 for following/losing the owner in HSSD/ProcTHOR-scale homes; or a Parcel-native 2D/3D abstract sim) where the dog is a point-body with L1 skills as discrete-continuous actions.
- State of the world: owner pose/visibility, owner utterance + affect features (from L3), recent joke/punchline events, owner-model facts, time since last interaction, battery/terrain flags.
- Targets: (a) "look back when lost": episode = owner walks a waypoint path (Habitat 3.0 social-nav template, 1-2 m follow band, metrics S/F/CR); reward = regain detection quickly, no collisions, plus an L1 look-back skill fired when detection drops. Baseline to beat: Habitat's heuristic expert (S 1.00, F 0.51). (b) "chuckle if the joke was funny": episode = owner tells a joke (LLM owner emits text + a latent funniness + a laugh/no-laugh reaction); policy chooses chuckle intensity and TIMING (during vs after the punchline - the full-duplex part); reward = owner laugh event and an LLM-judge score, calibrated against human ratings.
- Owner: LLM agent (persona + memory + affect), constrained by scripted physical trajectories; SOTOPIA-style scenario sampling for diversity.

### L3 - Dialogue / voice (text-level RL; voice only for evaluation)
- Simulator: tau2-bench-style LLM user with personas for text-level policy learning (cheap, fits the <= $100/mo text budget when using a local judge/user model); tau2's full-duplex voice mode over a realtime provider for evaluation episodes only (fits <= $300/mo Realtime budget if used sparingly).
- Owner: LLM user, fine-tuned or few-shot-grounded on recorded owner transcripts (utility paper: fine-tuned simulators transfer better).

### Audio layer (offline data generation, not RL)
- SoundSpaces 2.0 / habitat-sim audio sensor with a 4-mono-mic custom array matching the XVF3800: render TTS/recorded owner speech and laughter from randomised positions in ProcTHOR/HSSD rooms for DoA / "owner called from behind" detectors.

### Where the owner must be simulated by an LLM vs scripted vs recorded
- LLM agent: dialogue content, jokes, affect trajectory, consented facts, reactions to dog behaviour (laugh/ignore/annoyed). Required for L2 (b) and L3.
- Scripted: physical trajectories (walk, leave room, hide behind a corner, sit), timing of events, and safety-critical positions. Required for L2 (a); Habitat 3.0 / IRA GoTo commands are exactly this.
- Recorded: voice, prosody, laughter, real reaction labels, and the calibration/hold-out set that every LLM-judged reward must be checked against (SOTOPIA-pi gap; utility paper). Required to keep L2/L3 honest.

---

## 14. What this means for Parcel (and a 12-hour plan)

1. Do not spend the 12 hours installing Isaac Sim. Use MuJoCo Warp/mjlab with unitree_rl_mjlab's `Unitree-Go2-Flat` (Apache-2.0, Go2 included) - it is the same MuJoCo family the project already pins (3.11) and the same stack Uni-Mo used for 96.7% real-Go2 expressive transfer. Check `mujoco_warp` installs against the RTX 5000 Ada first; `mjx` is not in the venv today.
2. Replace the refuted `Go2Env` with the mjlab task rather than repairing it; that satisfies the readiness verdict's repair list (joint index map, telemetry, termination, timing, metrics, DR) by construction.
3. Author the expression vocabulary as kinematic references and train ONE tracking policy (STMR/Uni-Mo recipe). This is the trainable object the owner asked for: expressive skills are parameters, not a fixed list.
4. Build the L2 abstract social sim with an LLM owner + scripted trajectories; measure "chuckle timing" and "look-back on lost" against scripted ground-truth events, then against a 30-50 episode human-rated set. Budget the LLM owner locally (the SOTOPIA-pi judge-gap result says a hosted judge alone will overstate progress).
5. Full-duplex: the timing decision (chuckle while the owner is still talking) lives in L2 at 5-10 Hz and is executed by L1/L0 at 50 Hz; tau2-bench's voice mode is the closest existing full-duplex user-sim harness and is MIT.
6. Keep the deterministic safety layer above all learned layers; every source that transferred expressive motion still tracked references under a low-level controller.

## 15. Open questions

- Go2-specific throughput on MuJoCo Warp vs Isaac Lab on THIS GPU (RTX 5000 Ada) is unmeasured; the closest numbers are Go1 (mjlab 190k vs Isaac Lab 240k at 4096 envs) and A100 MJX (417k).
- No fetched source trains a robot's SOCIAL policy against LLM-simulated humans end-to-end and validates with real humans; the HRI review (86 studies) found none. Parcel would be early here.
- Uni-Mo's Quad-Imaginarium dataset licence/download and its exact motion categories were not readable from the HTML; verify before relying on it as the reference library.
- Genesis's headline FPS claims were not on any fetched page; treat "10-80x" as an unverified vendor claim.
- The DFM dance-motion paper and SOTOPIA-RL could not be fetched (search budget exhausted); both may add evidence for music-timed expression and social-reward design.
- SoundSpaces 2.0 has no speech generator; owner voice must be TTS or recordings rendered through it.

## 16. All sources fetched (2026-08-28)

- https://arxiv.org/abs/2310.13724 ; https://arxiv.org/html/2310.13724 ; https://aihabitat.org/habitat3/ ; https://github.com/facebookresearch/habitat-lab
- https://arxiv.org/abs/2206.08312 ; https://ar5iv.labs.arxiv.org/html/2206.08312 ; https://github.com/facebookresearch/habitat-sim/blob/main/docs/AUDIO.md
- https://arxiv.org/abs/2407.08725 ; https://arxiv.org/html/2407.08725v2 ; https://github.com/metadriverse/metaurban ; https://metadriverse.github.io/metaurban/
- https://isaac-sim.github.io/IsaacLab/main/source/overview/environments.html ; https://isaac-sim.github.io/IsaacLab/main/source/overview/reinforcement-learning/performance_benchmarks.html ; https://github.com/isaac-sim/IsaacLab/blob/main/source/isaaclab_assets/isaaclab_assets/robots/unitree.py ; https://github.com/isaac-sim/IsaacLab/issues/2761
- https://developer.nvidia.com/blog/closing-the-sim-to-real-gap-training-spot-quadruped-locomotion-with-nvidia-isaac-lab/
- https://docs.isaacsim.omniverse.nvidia.com/5.1.0/action_and_event_data_generation/ext_replicator-agent/ext_omni_anim_people.html ; .../ext_replicator-agent/actor_control.html ; .../tutorial_replicator_agent.html ; .../index.html
- https://github.com/unitreerobotics/unitree_rl_lab ; https://github.com/unitreerobotics/unitree_rl_mjlab ; https://github.com/unitreerobotics/unitree_rl_gym ; https://github.com/unitreerobotics/unitree_sim_isaaclab
- https://github.com/mujocolab/mjlab ; https://github.com/mujocolab/mjlab/discussions/220 ; https://github.com/google-deepmind/mujoco_warp
- https://raw.githubusercontent.com/Genesis-Embodied-AI/Genesis/main/README.md ; https://genesis-world.readthedocs.io/en/latest/user_guide/overview/what_is_genesis.html ; https://github.com/Genesis-Embodied-AI/Genesis/blob/main/examples/locomotion/go2_train.py
- https://arxiv.org/abs/2502.08844 ; https://arxiv.org/html/2502.08844 ; https://github.com/google-deepmind/mujoco_playground ; https://playground.mujoco.org/ ; https://github.com/google-deepmind/mujoco_menagerie/tree/main/unitree_go2
- https://arxiv.org/abs/2206.06994 ; https://ar5iv.labs.arxiv.org/html/2206.06994 ; https://github.com/allenai/procthor
- https://arxiv.org/abs/2310.11667 ; https://arxiv.org/html/2310.11667 ; https://arxiv.org/abs/2403.08715 ; https://arxiv.org/html/2403.08715 ; https://github.com/sotopia-lab/sotopia
- https://arxiv.org/abs/2406.12045 ; https://arxiv.org/html/2406.12045 ; https://github.com/sierra-research/tau2-bench
- https://arxiv.org/abs/2510.06552 ; https://arxiv.org/abs/2605.09808 ; https://arxiv.org/html/2604.24977v1 ; https://arxiv.org/abs/2601.09215 ; https://arxiv.org/abs/2601.06877 ; https://arxiv.org/html/2602.15063v1 ; https://arxiv.org/abs/2504.02234v2
- https://github.com/EricGuo5513/HumanML3D ; https://arxiv.org/abs/2512.07673
- https://arxiv.org/abs/2310.12931 ; https://github.com/eureka-research/Eureka ; https://arxiv.org/abs/2411.01775 ; https://arxiv.org/html/2411.01775 ; https://github.com/eureka-research/eurekaverse
- https://arxiv.org/abs/2606.28237 ; https://arxiv.org/html/2606.28237 ; https://arxiv.org/html/2404.11557 ; https://arxiv.org/abs/2004.00784 ; https://arxiv.org/abs/2104.02180 ; https://arxiv.org/html/2504.17857v1 ; https://dev.bostondynamics.com/docs/concepts/choreography/readme ; https://arxiv.org/abs/2502.10983
