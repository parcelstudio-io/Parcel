# Sim-to-real for language-driven navigation on Unitree Go2/Go1, and human-in-the-loop LLM demos

Literature note for the 2026-08-29 Model A / Model B study. Every source below was fetched and read on 2026-08-29; numbers are quoted from the fetched text. Where the abstract and the body of a paper disagree, both are given. The WebSearch budget for the session ran out after the first three rounds, so the last third of this note is built from direct fetches of known URLs (arXiv, GitHub, vendor docs) rather than new searches; gaps that this caused are listed in "Open questions".

Scope asked for: NaVILA on Go2, LOVON, "Go2 VLN sim2real", Isaac Lab / Isaac Sim + Go2 + LLM, Habitat 3.0 HITL, LLM-driven simulation harnesses for HRI, TartanGround, Go2 ROS2 + LLM voice community projects, and any published pipeline that runs an LLM voice agent against a simulated robot with logging / replay / scoring.

---

## Part 1 - Language-driven navigation on Go2/Go1 with a measured sim-to-real story

### 1.1 NaVILA - Legged Robot Vision-Language-Action Model for Navigation (UCSD / NVIDIA, arXiv 2412.04453, RSS 2025)

- Paper: https://arxiv.org/html/2412.04453v1 (license CC BY 4.0)
- VLA code: https://github.com/AnjieCheng/NaVILA (Apache-2.0, 705 stars, checkpoints `navila-siglip-llama3-8b-v1.5-pretrain`, `navila-llama3-8b-8f`)
- Benchmark: https://github.com/yang-zj1026/VLN-CE-Isaac (MIT, 337 stars; Isaac Sim 4.1.0 + custom Isaac Lab 1.1.0; Matterport3D converted to USD; "Terminal 1: VLM Server / Terminal 2: NaVILA IsaacLab Benchmark Evaluation", VLM server needs "at least 24GB VRAM")
- Low-level: https://github.com/yang-zj1026/legged-loco (MIT, 452 stars; "train low-level locomotion policy of Unitree Go2 and H1 in Isaac Lab"; "tested with Isaac Lab 1.1.0 and may not be compatible with newer versions")
- Project page: https://navila-bot.github.io/ (real-world platforms listed: Booster T1, Unitree Go2, Unitree G1)

What it is: two-level system. An 8B VLM (VILA, SigLIP + Llama-3-8B) reads a history of frames and emits one mid-level language action; a separate RL locomotion policy trained in Isaac Lab executes it.

Numbers (quoted from the fetched HTML):
- Action space: "fixed set of actionable words, such as {move forward, turn left, turn right, stop}" mapped to "fixed command velocities {0.5 m/s, pi/6 rad/s, -pi/6 rad/s, 0}"; outputs look like "turn right 30 degrees" or "moving forward 75cm".
- Latency: "The VLA inference time is approximately 0.6 seconds per sample"; "NaVILA's current wait time between each action is about 1 second, which is practical for real-world deployment"; "The transmission time largely depends on the network conditions" (images are shipped from the robot to an external GPU; the VLM is NOT on the Orin). Real-world runs use "an 8-frame memory size due to latency constraints".
- On-robot deployment is explicitly future work: quantization gave "memory requirements dropped by half, and processing speed improved by about 40%", and deploying "directly on the robot, which will eliminate image transmission time significantly" is left "as future work".
- Locomotion: PPO in Isaac Sim / Isaac Lab, "60K FPS on an RTX 4090 GPU"; LiDAR "broadcasting point clouds at a frequency of 15Hz", converted to "a 2.5D height map" with "360 degree x 90 degree" FOV; single-stage training with domain randomisation (mass, friction, motor strength).
- VLN-CE-Isaac benchmark: "From the 1,839 trajectories in the R2R Val-Unseen split, we select 1,077 traversable trajectories". Go2 vision policy SR 50.2 (NE 5.49) vs Go2 blind policy SR 36.2; H1 vision 45.3 vs blind 24.4 ("14% improvement in Success Rate in Go2 settings and 21% in H1 settings").
- Real world: "25 instructions, each repeated three times, covering both simple and complex tasks across three types of environments: Workspace, Home, and Outdoor"; "88% success rate on 25 instructions, including a 75% success rate on complex instructions" (complex = "three or more commands, requiring the robot to traverse multiple rooms or landmarks").
- Training data: "2K egocentric touring videos from YouTube" -> "20K trajectories", plus R2R-CE / RxR-CE (Habitat), ScanQA, general VQA. R2R-CE "17% improvement in success rate"; RxR "10% improvement in SR" over NaVid. YouTube data is released as video IDs + annotations only (copyright).

Modalities the sim covers: RGB + LiDAR height map + Go2 articulated physics in Isaac Sim. No people, no audio, no speech; instructions are text.

### 1.2 TIC-VLA - Think-in-Control VLA for navigation in dynamic environments (arXiv 2602.02459, Feb 2026)

- https://arxiv.org/html/2602.02459
- Architecture: "the action policy runs at 10 Hz and asynchronous VLM reasoning running at 0.5 Hz"; backbone "InternViT-300M vision encoder and a Qwen2.5-0.5B language model" (InternVL3-1B).
- Trained to tolerate slow reasoning: "reasoning delays delta-t uniformly from [0,10] seconds".
- Measured latency (action policy / reasoning): "85.73 / 3430.73" ms on RTX 4060 Laptop (50 W); "120.27 / 4831.73" ms on "NVIDIA Jetson Orin NX (25W)"; RTX A6000 as reference.
- Benchmark: DynaNav built in Isaac Sim, "85 test cases", pedestrian density from empty to "200 agents" outdoor. Sim: SR 55.29, NE 10.55, CR 28.24.
- Real-world on Unitree Go2: "0.85" SR on RTX 4060, "0.75" on Jetson Orin NX - i.e. moving the same model onto the Orin NX cost ~10 SR points purely from latency.
- Data: SCAND 8.7 h + GND 11 h + DynaNav sim 5.1 h (~25 h total).

### 1.3 NavDP - Sim-to-real navigation diffusion policy (arXiv 2505.08712)

- Paper: https://arxiv.org/html/2505.08712 (v2: https://arxiv.org/html/2505.08712v2); project page https://wzcai99.github.io/navigation-diffusion-policy.github.io/ ; code https://github.com/wzcai99/NavDP (CC BY-NC-SA 4.0, 773 stars; benchmark on IsaacSim 4.2.0 + IsaacLab 1.2.0; checkpoints behind a form)
- Sim data: "over 200K trajectories covering more than 1M meters", 3,154 scenes, 452 hours, 40M images; "2,500 trajectories per GPU per day - achieving a 20x improvement in efficiency over real-world data collection". Project page: "363.2km trajectories across 1244 scenes".
- Training: "32 A100 cards".
- Inference: "our end-to-end policy can achieve real-time inference (>>10Hz)" (hardware on the Go2 not stated).
- Real world point-goal: Turtlebot4 9/10, Unitree Go2 7/10, Unitree G1 7/10, "76.7%" average vs ViPlanner 53.3%. Sim Dingo: 67.2% SR / 62.6% SPL.
- Gap statement: "given the observed sim-to-real gap in visual observations, we leverage the latest Gaussian Splatting approaches"; adding real-to-sim data "can improve the success rate by 30%".

### 1.4 LOVON - Legged Open-Vocabulary Object Navigator (arXiv 2507.06747, IROS 2025)

- Paper: https://arxiv.org/html/2507.06747 ; code https://github.com/DaojiePENG/LOVON (MIT, 108 stars; ships L2MM + IOE weights, data generator, Go2 deployment code; "we depoly LOVON using Jestson Orin" and it also runs "on other devices (like your laptop)")
- Planner: "DeepSeek R1" as task planner and data-generation assistant. Detector: "YOLO-11".
- L2MM (language-to-motion): "transformer-based model with feature dimension 256, 4 layers, and 8 attention heads"; "1 million samples" split 4:1; trained in "approximately 1 hour" on an RTX 3080 Ti; data generated in "less than 15 minutes to generate 1 million data with CPU Intel i9-12900KF".
- Sim: Gym-Unreal, "maximum episode length 500 steps", LOVON reaches "500 / 1.00" (episode length / SR) on most environments; "1.5 hours" training vs TrackVLA "360 hours".
- Real world: Go2, B2, H1-2; commanded at "fixed speeds of 0.3, 0.5, or 0.7 m/s"; Realsense D435i + built-in cameras; Jetson Orin inference.
- Not reported: end-to-end latency, control frequency, transfer gap.

### 1.5 HA-VLN 2.0 - Human-aware VLN with a real Go2-EDU validation (arXiv 2503.14229)

- Paper: https://arxiv.org/html/2503.14229 (real-world numbers only in Appendix D.7 of the PDF, extracted locally); code https://github.com/UWMILab/HA-VLN (MIT, 401 stars; HA-VLN-CE + HA-VLN-DE simulators; Go2 deployment code is NOT in the repo)
- Dataset: "16,844 socially grounded instructions" (10,819 / 778 / 1,839 / 3,408); HAPS 2.0 "486 SMPL-based motion sequences across 26 region types", "910 human models across 428 regions in 90 scans", "around 430 annotation hours", "172 activities, 486 models, 58k frames".
- Simulator: Matterport3D; "up to 10 humans" per scene at "30-60 FPS on a single 24GB GPU".
- Sim baseline (HA-VLN-VL, unseen): NE 7.82 m, TCR 3.67, CR 0.45, SR 0.05.
- Real robot: "Unitree Go2-EDU quadruped, equipped with Intel Realsense D435i RGB-D camera, MID360 3D LiDAR, and IMU"; "the robot is equipped with an NVIDIA Jetson NX for AI inference and a Raspberry Pi 4B for motion control"; "minimum step size of 0.25 m and a rotation increment of 15 degrees"; "The quadruped rotates to get the panoramic view at each step".
- Real-world protocol: four region types (living room, office, hallway, lobby) x 3 instances, "averaged over 30 episodes", with and without "2-4 free-moving volunteers".
- Real-world NSR (Table 10, ALL column): HA-VLN-VL trained on HA-VLN 0.44 without humans / 0.18 with humans; same model trained on plain VLN-CE 0.40 / 0.12; CMA-Base trained on HA-VLN 0.25 / 0.15; CMA-Base trained on VLN-CE 0.26 / 0.09. Quote: "agents trained on HA-VLN achieve higher NSR (0.18 vs. 0.12) than VLN-CE, demonstrating HA-R2R's sim-to-real gain under realistic conditions."
- Failure mode: "A volunteer's sudden positional change causes a mid-path collision and mission failure".

### 1.6 Speculative edge-cloud decoding on a Go2 EDU (arXiv 2505.21594)

- https://arxiv.org/html/2505.21594
- The Go2 EDU's onboard computer is documented: "an onboard NVIDIA Jetson Orin board, which includes an 8-core ARM Cortex-A78AE v8.2 64-bit CPU and 16GB of 128-bit LPDDR5 unified memory" (that is an Orin NX 16 GB; Parcel's AGX Orin 64 GB is a larger part).
- Setup: "a quantized version of Qwen-2-VL-2B as the on-device draft model and offload token verification to the full-size Qwen-2-VL-7B model hosted on an A100 GPU in the cloud".
- Measured: drafting "288ms" (gamma = 4), verification "620ms", communication "120ms", latency ratio "0.11"; "a 21% speedup over conventional cloud-based autoregressive decoding". VLN prompts like "go to the red chair"; no success rate reported.

### 1.7 QUART-Online - 50 Hz multimodal model for quadrupeds (arXiv 2412.15576)

- https://arxiv.org/html/2412.15576
- Base "Fuyu-8b"; "Action Chunk Discretization (ACD)" compresses continuous actions into discrete tokens (chunks 1/5/10); "increasing the inference rate of the original large quadruped robot model, QUART, from 2Hz to 50Hz"; QUARD benchmark average SR 0.37-0.52 -> 0.68-0.79 ("65% improvement"); Isaac Gym; real-robot section exists but hardware unspecified.

### 1.8 Isaac Sim-to-Real RL locomotion (Go1) (arXiv 2607.18135)

- https://arxiv.org/abs/2607.18135 - Isaac Sim + Isaac Lab, "validated on physical hardware using the Unitree Go1", "linear velocities of 2.0 m/s and angular velocities of 1.8 rad/s", "zero-shot sim-to-real policy", "similar velocity tracking performance to the quadruped's integrated controller" with "greater ability to recover from large disturbances".

### 1.9 Isaac Sim -> Gazebo -> real ROS 2 (arXiv 2501.02902, TurtleBot 4)

- https://arxiv.org/abs/2501.02902 (PDF text extracted locally); code https://github.com/sahars93/RL-Navigation
- End-to-end LiDAR local planner trained in Isaac Sim, benchmarked in Gazebo against Nav2, deployed zero-shot. Real robot: TurtleBot 4 Lite, RPLIDAR A1M8 (range set to 2 m, 3 degree resolution), Raspberry Pi 4B, ROS 2 Galactic node, OptiTrack for ground truth, 0.31 m/s max.
- Table 1, 10 trials x 4 experiments: 10/10, 10/10, 8/10, 7/10 success; min LiDAR range 0.25-0.43 m; average linear velocity 0.13-0.15 m/s; task time 39-53 s. Dynamic obstacle test: box moving 0.1-0.3 m/s; LSTM policy avoided it, Nav2 "relies on a precomputed cost map, which can be less effective when encountering dynamic obstacles".
- Not a Go2 paper, but it is the cleanest published "Isaac -> Gazebo -> real ROS 2" recipe with per-trial numbers.

---

## Part 2 - Simulators and benchmarks with humans, HITL, or audio

### 2.1 Habitat 3.0 (Meta, arXiv 2310.13724, ICLR 2024)

- Paper: https://arxiv.org/html/2310.13724 ; code https://github.com/facebookresearch/habitat-lab (MIT); HITL README https://github.com/facebookresearch/habitat-lab/blob/main/habitat-hitl/README.md
- Throughput: "188 +/- 2 FPS" one humanoid, "245 +/- 19" robot only, "136 +/- 8" robot + humanoid, "1191 +/- 3 FPS across 16 environments on a single GPU".
- Avatars: "12 base models with multiple gender representations, body shapes, and appearances"; HSSD "37 train, 12 validation and 10 test scenes".
- Social Navigation (find and follow a humanoid at 1-2 m): heuristic expert S 1.00 / SPS 0.97 / F 0.51 / CR 0.52; end-to-end RL S 0.97 / SPS 0.65 / F 0.44 / CR 0.51.
- Social Rearrangement ZSC: Plan-Pop3 "71.79 +/- 7.38", Plan-Pop4 "71.32 +/- 6.47".
- HITL study: "30 participants", "10 episodes per condition"; relative efficiency solo 100, Learn-Single "133.80", Plan-Pop3 "123.46". Quote: "The automated evaluation pipeline can give an indication of the relative ordering of different approaches when evaluated with real human partners."
- HITL tool: "mouse/keyboard or a VR interface", "client-server architecture", "web browsers and VR devices", "recording and replaying of HITL episodes" at multiple abstraction levels with re-rendering from other cameras. HITL README: "example HITL apps are configured to run at 30 steps per second (SPS)"; ~20 GB dependencies, ~60 GB machine.
- Modalities: vision only. No audio, no speech, no text chat between human and robot in the paper.

### 2.2 PARTNR (Meta, arXiv 2411.00081, ICLR 2025)

- Paper: https://arxiv.org/abs/2411.00081 (PDF text extracted locally); code https://github.com/facebookresearch/partnr-planner (MIT, 385 stars)
- Scale: "100,000 natural language tasks, spanning 60 houses and 5,819 unique objects"; "100,000 episodes in 37 train scenes, 1,000 episodes in 13 validation scenes, and 1,000 episodes in 10 test scenes from the HSSD dataset".
- HITL infrastructure: "We build on the human-in-the-loop infrastructure from Habitat 3.0 ... and adapt it to a server-client architecture, with the server hosted on AWS capable of supporting multiple clients"; "129 non-expert human participants"; "1000 tasks from the validation set, and 1000 tasks from the test set"; "Each task took on average 3-5 minutes"; "Each task was completed up to 3 times ... until deemed successful"; a "matchmaking service" pairs participants; users get "natural language feedback at the end of an episode, describing what went wrong".
- Table 3 (real humans): Single-user SR 0.93, sim steps 3046.99; Multi-user SR 0.93, 2369.55 steps, task offloading 0.59; Human-ReAct SR 0.91, 4267.71 steps, offloading 0.16; Human-Finetuned SR 0.92, 3443.33 steps, offloading 0.26.
- Key contrast: "humans are able to solve 93% of PARTNR tasks, SoTA LLMs can only successfully complete 30% under non-privileged conditions"; LLM baselines "achieve a success rate of 0.92 and 0.91 when evaluated with real humans ... because humans are able to adapt to LLM mistakes. On the other hand, the simulated human in Table 2 is an LLM, which is unable to recover from partner mistakes."
- "require 1.5x as many steps as two humans collaborating and 1.1x more steps than a single human"; "Finetuned 8B model performs on par with a ReAct with a 70B model, while being 8.6x faster" (0.70 vs 0.73 SR).
- Modalities: keyboard/mouse-driven human avatar; instructions are text; no speech.

### 2.3 Simulating User Agents for Embodied Conversational-AI (arXiv 2410.23535, NeurIPS 2024 workshop)

- https://arxiv.org/html/2410.23535
- AI2-THOR + TEACh (~3,000 sessions; evaluation on val-seen "181 sessions and 7923 steps"). LLM user simulator decides when to speak and what dialogue act to issue. GPT-4 zero-/few-shot Speak-F1 42.0% / 43.4%; DA-F1 35.15% / 51.13%; fine-tuned RoBERTa-base DA-F1 62.48%. Including robot move actions in context drops Speak-F1 "from 43.39% to 26.79%". Text only ("does not incorporate visual information").

### 2.4 tau-Voice - full-duplex voice-agent benchmark (arXiv 2603.13686, Sierra; code in tau2-bench)

- https://arxiv.org/html/2603.13686v1 (CC BY 4.0; "Code is available at https://github.com/sierra-research/tau2-bench")
- Harness design: "controllable and realistic voice user simulator" with "diverse accents, realistic audio environments, and rich turn-taking dynamics"; orchestrator uses "discrete simulation time" with 200 ms ticks so "both can speak simultaneously"; the user simulator is decoupled from wall-clock so it can "use the most capable LLM without real-time constraints"; LLM-based interruption/backchannel decisions.
- Scale: "278 tasks" (Retail 114, Airline 50, Telecom 114). Metrics: Pass@1 by final-state comparison plus Responsiveness / Latency / Interrupt / Selectivity.
- Results: text "GPT-5 (reasoning) achieves 85%. Voice agents reach only 31-51%"; realistic conditions "26-38%", "retaining only 30-45% of text capability"; OpenAI "fastest latency (0.90s)" but "worst selectivity (6%)"; "79-90% of failures stem from agent behavior". Logging: "instruments each simulation to log turn-taking events, audio effects, and agent responses".
- Not a robot harness, but it is the only fetched system that scores a full-duplex voice agent under simulated interruptions with replayable logs.

### 2.5 LH-AVLN - long-horizon audio-visual-language navigation (arXiv 2607.03920)

- https://arxiv.org/html/2607.03920 (CC BY 4.0). SoundSpaces 2.0 + Matterport3D "with spatialized binaural audio"; "156550" episodes, "172.17" mean steps. Audio is environmental sound from targets, NOT spoken instructions. Baselines SR 2.2-6.0%. Simulation only.

### 2.6 VLNVerse (arXiv 2512.19021)

- https://arxiv.org/html/2512.19021v1 (CC BY 4.0). "built on NVIDIA Isaac Sim"; "263 large-scale, diverse, and interactive 3D environments"; ~51,600 episode-instruction pairs across five task types; collision failure "defined as an obstacle displacing the agent by 0.1m"; GAMA 48.30% SR vs human 77.20%. Parametric agent (height/diameter), no named Go2 embodiment, no dynamic humans.

### 2.7 TartanGround (CMU AirLab + ETH RSL, arXiv 2505.10696, IROS 2025)

- Abstract https://arxiv.org/abs/2505.10696 ("910 trajectories", "70 environments", "1.5 million samples"); body https://arxiv.org/html/2505.10696 (878 trajectories: 440 omnidirectional wheeled, 198 differential-drive, 240 legged; 63 environments; "1.44 million samples"; "17.3 million RGB images"; "approximately 15 TB"). Dataset https://huggingface.co/datasets/theairlabcmu/TartanGround
- Sensors: "6 stereo RGB cameras (front, left, right, back, top, bottom), each with a fov of 90 degrees", depth, optical flow, disparity, "simulated LiDAR", semantic segmentation and "semantic occupancy maps", GT poses.
- Engine: Unreal Engine 4 + AirSim; legged trajectories from "an ANYmal D legged robot" in Gazebo. No Go2, no people, no audio.
- Gap evidence: SurroundOcc trained on nuScenes gets 12.91-22.15 IoU urban vs 6.39-13.89 IoU natural; "ORB-SLAM3 frequently loses tracking". License CC BY-NC-SA 4.0 (non-commercial).

### 2.8 Virtual Community (arXiv 2508.14893, ICLR 2026)

- https://arxiv.org/html/2508.14893 ; code https://github.com/UMass-Embodied-AGI/Virtual-Community (196 stars). Genesis physics; "35 annotated scenes of various cities"; "five types of robots: drones, quadruped robots, humanoid robots, wheeled robots, and mobile manipulators"; agent profiles and planners "driven by gpt-4o"; Community Planning LLM planner 47.2 vs heuristic 42.1; Community Robot Challenge heuristic 19.9, RL 14.3. RGB-D + segmentation; no audio/speech.

### 2.9 Genesis

- https://github.com/Genesis-Embodied-AI/Genesis (Apache 2.0, 29.8k stars); overview https://genesis-world.readthedocs.io/en/latest/user_guide/overview/what_is_genesis.html ("10-80x faster than prior GPU-accelerated simulators such as Isaac Gym/Sim/Lab and MuJoCo MJX"; sensors "IMU, lidar, depth-camera, contact-force ..."); Go2 tutorial https://genesis-world.readthedocs.io/en/v0.3.3/user_guide/getting_started/locomotion.html ("The simulation runs at 50 Hz, matching the real robot's control frequency"; "manually simulate the action latecy (~20ms, one dt)"; "This is NOT a comprehensive locomotion policy training pipeline"). No humans, no audio.

### 2.10 Isaac Lab / Isaac Sim

- Isaac Lab paper https://arxiv.org/html/2511.04831v1 : quadruped morphologies "A1, G1, H1, Go1/2, Anymal-B/C/D, Cassie, Digit, and Spot" (11); "over 900,000 frames per second" (DextrAH) and "over 1.6 million frames per second" (Franka cabinet) on 8 GPUs; RayCaster "height scanners, solid-state LiDARs, and rotating LiDARs"; tiled rendering; "robust sim to real for Anymal and Spot". Repo https://github.com/isaac-sim/IsaacLab : BSD-3 (mimic extension Apache 2.0); Isaac Lab 3.0.0 Beta 2 supports Isaac Sim 6.0.0/6.0.1; "more than 30 environments", "more than 16" robot models.
- Isaac Sim ROS 2 Navigation tutorial https://docs.isaacsim.omniverse.nvidia.com/6.0.0/ros2_tutorials/tutorial_ros2_navigation.html : Nova Carter / iw.hub with Nav2, RTX LiDAR, occupancy-map tool; "You can add people assets into the scene and they will be detected by the Lidar when being passed to Nav2"; no LLM.
- Isaac Sim actor simulation (Replicator Agent) https://docs.isaacsim.omniverse.nvidia.com/latest/action_and_event_data_generation/tutorial_replicator_agent.html : characters driven by `omni.behavior.tree` / `isaacsim.anim.robot` with YAML "routine-trigger" behaviours; "The scene requires a NavMesh"; framed as offline synthetic-data generation; no audio; no statement about reacting to robots. (The older `omni.anim.people` docs URL returns 404 on the 6.0 docs.)
- NVIDIA Isaac Sim survey https://arxiv.org/abs/2606.03551 : "more than 20 sensor types (e.g., RGB/depth cameras, LiDAR, and IMU)", stock "human characters (e.g., Worker, Police, Doctor)", ROS1/2 bridge; no throughput or sim-to-real numbers.

### 2.11 Go2-in-Isaac community platforms

- https://github.com/sallu-786/Go2_Isaac_ros2 : Isaac Sim 4.5.0 + IsaacLab 2.1.1 (Isaac Sim 6.0 / Lab 3.0 beta in progress), ROS 2 Humble; topics `/unitree_go2_0/cmd_vel`, RGB/depth/semantic camera, `detection_image` (YOLO), `/lidar/point_cloud`, `/odom`, `/pose`; "70+" environments (warehouse, office, hospital, terrain); MCP server so the robot "can also be controlled by either giving natural language commands from LLM or via web portal"; PPO / distillation policies; 36 stars; no FPS or success numbers; no license stated.
- https://github.com/Zhefan-Xu/isaac-go2-ros2 : Isaac Sim 4.5 + Isaac Lab 2.1.0, LiDAR + RGB/depth/seg camera, `/unitree_go2/cmd_vel`, warehouse and sparse/medium/dense obstacle fields, `num_envs` multi-robot; controller derived from go2_omniverse; no measured FPS.

---

## Part 3 - LLM / voice on a real Go2 (community and papers)

- go2_ros2_sdk https://github.com/abizovnuralem/go2_ros2_sdk : BSD-2, 1,000+ stars, 213 forks; Wi-Fi (WebRTC) or Ethernet (CycloneDDS); Go2 AIR/PRO/EDU; slam_toolbox + Nav2; LiDAR "7 Hz (previously 2 Hz)"; joint states "1 Hz (firmware-limited)"; COCO detection; Foxglove bridge. No voice numbers.
- unitree-go2-mcp-server https://github.com/lpigeon/unitree-go2-mcp-server : Apache 2.0, 86 stars; natural language -> MCP tools -> ROS 2 sport commands (e.g. "move forward at 0.5 m/s for 3 seconds", stand up, sit, dance); Claude Desktop client; no latency measurements, no sim.
- HackMD "Configuring Unitree Go2 EDU for Real-Time Voice Interaction with OpenAI" https://hackmd.io/@c12hQ00ySVi6JYIERU7bCg/ByAOr12qJg : Whisper (or Google web speech) -> `gpt-3.5-turbo` chat completions -> TTS; keyword matching (`if "stop" in user_text: robot.stop()`); DDS via Unitree SDK; states "the robot should ideally respond within ~3 seconds" (a design target, not a measurement); "Unitree's SDK and docs currently do not provide high-level APIs for audio"; no public API to modify the built-in BenBen assistant.
- OpenMind OM1 https://github.com/OpenMind/OM1 (MIT, 2.9k stars): loop "inputs -> fusers -> LLM -> actions"; Unitree Go2 and G1 with BrainPack (SLAM, LiDAR, Nav2); ASR/TTS configured in `config/conversation.json5`; LLM providers OpenAI, xAI, DeepSeek, Anthropic, Meta, Gemini, NearAI, Ollama; "pre-configured Prometheus and Grafana stack to monitor real-time AI pipeline metrics like LLM and ASR latencies"; Gazebo (Go2) and Isaac Sim (Go2 & G1) simulation. Robot Report (2025-09-18) https://www.therobotreport.com/openmind-launches-om1-open-source-robot-agnostic-operating-system/ : "speech-to-text (Google ASR), text-to-speech (Riva, ElevenLabs)", "$20 million" raised. No published latency numbers.
- OpenGo (arXiv 2604.01708) https://arxiv.org/html/2604.01708v1 : OpenClaw-based Go2 with skill switching; response time measured "from the moment the user issues the instruction to the initiation of the robot's execution", 10 repeats per skill and 5 per 2-4-skill composition, but the HTML gives no millisecond values; text via Feishu, not speech; CC BY 4.0.
- Scripted vs LLM HRI study (arXiv 2501.12128, HRI 2025) https://arxiv.org/html/2501.12128 : NAO on a forklift, "GPT 4o-mini", "15 participants", "The observed response latency of the API of 2.5 s constrained real-time interaction capabilities"; participants spent "31.65% (LLM), 15.74% (PPS)" of time on task execution; trust median 44 vs 42, n.s.

---

## Part 4 - What no source provides

- No fetched paper or repo runs a hosted voice LLM (audio in, audio out, barge-in) against a simulated Go2 with logged and replayable episodes. The nearest pieces are: Habitat 3.0/PARTNR HITL (humans + robot, keyboard, recorded/replayable, no audio), tau-Voice (full-duplex voice user simulator with discrete 200 ms ticks and event logs, no robot), HA-VLN (moving humans in Matterport, Go2 validation, text instructions), and OM1 (voice + Nav2 on a real Go2, Gazebo/Isaac sims, latency dashboards but no published numbers).
- No simulator in this set produces speech audio from simulated people. SoundSpaces (LH-AVLN) produces spatialised environmental sound only.
- No Go2 paper reports an 8B-class VLM running on the Orin at >= 1 Hz. NaVILA (8B) streams images to an external GPU (0.6 s per inference, ~1 s per action); TIC-VLA (1B) needs 120 ms per policy step and 4.8 s per reasoning step on an Orin NX; a quantised 2B draft model takes 288 ms on the Go2 EDU's Orin NX. Parcel's AGX Orin 64 GB is a larger part than any Go2 compute measured here, but nobody has published Orin-AGX numbers for these models.

---

## What this means for Parcel's Model A / Model B

Model A = duplex, trainable, streams sensors/voice/context in, emits local movements or global-plan updates plus a narratable representation. Model B = owner-voice command -> steerable injection (revise / keep / queue the global plan) and Model A output -> narration context for the hosted voice.

1. Split rates the way the field does, and train under the slow loop's latency. Every deployed Go2 system separates a fast control loop from a slow language loop: NaVILA ~1 Hz language actions over a real-time locomotion policy; TIC-VLA 10 Hz policy + 0.5 Hz VLM with training under uniformly random 0-10 s reasoning delays; QUART-Online reaches 50 Hz only by discretising action chunks. Parcel's 10 Hz duplex frame clock and act-token codec already match TIC-VLA/QUART-Online; the missing piece is training Model A with injected Model-B / hosted-voice latency (0.5-10 s) so plan amendments arriving late do not destabilise it.

2. Keep the mid-level action vocabulary discrete and small. NaVILA's four words at fixed velocities (0.5 m/s, +/- pi/6 rad/s) reached 88% real-world SR; HA-VLN's real Go2 used 0.25 m steps and 15 degree turns. This validates an act-token codec as the Model A -> locomotion interface and gives Model B a tiny, verifiable vocabulary to narrate ("turning right 30 degrees").

3. Budget Model A for the Orin, budget Model B for the hosted side. Measured on-robot numbers: 1B VLM at 120 ms/policy step on Orin NX; 2B quantised at 288 ms per draft; 8B not run on robot at all (external GPU, +40% after quantisation still off-robot). TIC-VLA lost 10 SR points (0.85 -> 0.75) purely by moving from a laptop GPU to the Orin NX. Design rule: Model A <= ~1-2B parameters (or a non-LLM policy), evaluated at its on-device latency; Model B can be an 8B-class or hosted model because its loop is the ~1 s language loop, and PARTNR shows a fine-tuned 8B matches a 70B planner at 8.6x lower latency and coordinates better with real humans (3443 vs 4267 steps).

4. Measure the transfer gap on three axes, because the literature shows each is large: (a) people - HA-VLN's real Go2 fell from 0.44 to 0.18 NSR when 2-4 volunteers moved through the space; (b) embodiment - NavDP's identical policy scored 9/10 on a TurtleBot but 7/10 on the Go2; (c) latency - TIC-VLA's 10-point drop above. Parcel's headless-city / MuJoCo-city evals should report SR separately with and without moving people and at real vs idealised Model A latency, and the sim-to-real rig should replay the same logged instruction set on hardware later (NaVILA: 25 instructions x 3 repeats; HA-VLN: 30 trials per region instance).

5. Simulated users under-estimate real humans; use both. PARTNR: LLM-simulated partner gives 0.30 SR, real humans paired with the same LLM give 0.91-0.92 because "humans are able to adapt to LLM mistakes"; Habitat 3.0: the automated humanoid ordering matched the ordering with 30 real participants. For Parcel's conversation-quality and interruption/amendment evals, an LLM user simulator (a la the TEACh user agent, Speak-F1 ~43%) is fine for relative ranking of Model B variants, but the acceptance bar needs a small real-owner HITL run.

6. Borrow tau-Voice's harness shape for the voice side of the sim-to-real rig: discrete simulation time (200 ms ticks), a user simulator decoupled from wall-clock, LLM-driven barge-in/backchannel decisions, per-tick logs of turn-taking events, audio effects and agent responses, and scoring by final state plus Responsiveness / Latency / Interrupt / Selectivity. Combine with Habitat-HITL-style episode recording that can be replayed at several abstraction levels (act tokens, whisperer digests, raw audio) and re-rendered.

7. Audio must be composed, not bought. No robotics simulator here emits speech; Parcel's "LLM converses with the robot while it navigates" rig should synthesise owner speech (TTS + room impulse response + XVF3800 mic-array model) into the sim, or run the hosted voice lane on real audio while the body is simulated (the same split as NaVILA's off-board VLM). SoundSpaces-style spatial audio is only needed if Model A is meant to localise the speaker.

8. Data for the language -> motion mapping can be procedural. LOVON trained its language-to-motion transformer on 1M synthetic samples in ~1 h; NavDP generated 2,500 trajectories/GPU/day in Isaac Sim. Model B's "voice command -> plan revise/keep/queue" head can be trained the same way from templated amendments over Parcel's task executive logs before any human data exists.

9. Licences to watch: Isaac Sim is proprietary (Isaac Lab BSD-3); NavDP and TartanGround are CC BY-NC-SA (non-commercial) - do not train a product model on them; Matterport3D (HA-VLN, NaVILA benchmark) needs its own licence; NaVILA code Apache-2.0 but its YouTube data ships as IDs only; Habitat, HA-VLN, OM1, partnr-planner MIT; go2_ros2_sdk BSD-2; Go2 MCP server Apache-2.0; Genesis Apache-2.0.

## Open questions

- What does an 8B VLA cost on an AGX Orin 64 GB at INT8/INT4? NaVILA's quantisation note (half memory, +40% speed) is from a workstation; no Go2 paper measured AGX Orin.
- HA-VLN 2.0 ran on "Jetson NX + Raspberry Pi 4B" with 0.25 m steps and a panoramic rotation per step; the paper does not say how the policy was shrunk or what the per-step latency was.
- TartanGround's abstract (910 / 70 / 1.5M) and body (878 / 63 / 1.44M) disagree; treat as version drift and cite the version used.
- Search budget ran out before checking NVIDIA's own Go2 + LLM demos (beyond the two community Isaac repos), HuNavSim / Arena-Rosnav-style LLM-driven pedestrian simulators, and the current status of `omni.anim.people` under Isaac Sim 6.0 (the URL 404s; the Replicator Agent page is the replacement found).
- OM1's Prometheus/Grafana latency dashboards exist but no published LLM/ASR latency numbers for Go2 were found.
- OpenGo measured instruction -> execution response time on a real Go2 but the HTML omits the values.
