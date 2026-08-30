# Benchmarks for a companion robot: navigation, instruction following, conversation

Research note, 2026-08-29. Every source below was fetched and read during this session (arXiv HTML/PDF, GitHub READMEs, leaderboard pages, an IEEE RAM article via NSF PAR). Numbers are copied from the fetched text; where an extraction looked suspicious it is flagged. Nothing here is from memory.

Scope: the benchmarks a Parcel-class companion dog should be scored on, their metric definitions, dataset sizes, current SOTA, and whether each is runnable offline on a desktop (no robot on hand; Habitat/MuJoCo sim only).

---

## 0. Executive summary

| Family | Benchmark | Headline SOTA (as read) | Runnable offline on a desktop? |
|---|---|---|---|
| VLN | R2R-CE val-unseen | SR 68.3 / SPL 65.2 (MobileVLA-R1, 8B, ECCV'26); ETP-R1 (0.5B) SR 65 / SPL 56; test-unseen SR 64 / SPL 54 (ETP-R1) | Yes: Habitat-Sim + MP3D (~90 scenes, MP3D ToS, CC BY-NC-SA 3.0 US). No API needed. |
| VLN | RxR-CE val-unseen | SR 71.5 / SPL 66.8 / nDTW 76.1 (MobileVLA-R1); ETP-R1 SR 59.92 / nDTW 65.31 / SDTW 50.41 | Yes (same stack; 126K instructions EN/HI/TE, CC-BY annotations). |
| Open-vocab ObjectNav | HM3D-OVON val-unseen | SR 53.1 / SPL 20.9 (Qwen-RobotNav-4B, 2026); paper baselines DAgRL+OD 37.1 / 19.9, VLFM 35.2 / 19.6 | Yes: Habitat + HM3D (academic, non-commercial licence). |
| Lifelong multimodal nav | GOAT-Bench val-unseen | paper: SenseAct-NN skill-chain SR 29.5 / SPL 11.3; 2026 HGR: SR 64.14 / SPL 50.1 (full val), 72.41 / 56.22 (278-subtask subset) | Yes (Habitat + HM3D). |
| Mobile manipulation | OVMM (NeurIPS'23) | sim 10.8 % overall success (UniTeam); real 33.3 %; baselines 0.8 % / 0.0 % | Yes (Habitat), but heavy; not a priority for a Go2 without arm. |
| Social nav | Habitat 3.0 SocialNav | RL baseline: 97 % finding success, collision rate 0.51 ± 0.03 (expert 100 %, 0.52) | Yes (Habitat 3.0 + HSSD; 1190 FPS with humanoid+robot). |
| Social nav | Social-HM3D / Social-MP3D (Falcon) | Falcon SR 55.15 / SPL 55.15 / PSC 89.56 / H-Coll 42.96 (HM3D); PSC threshold 1.0 m | Yes (Habitat + HM3D/MP3D, 844 + 72 scenes, up to 6 ORCA humans). |
| Constrained nav | BARN | score ∈ [0, 0.5]; 2024 sim winner 0.4762 (baselines 0.1656–0.4354); physical 6/9 trials | Yes (ROS + Gazebo Jackal; 300 public envs). |
| Embodied IF | EmbodiedBench (ICML'25) | GPT-4o avg 50.5 %, EB-Navigation 57.7 %, EB-Manipulation 28.9 %; best open InternVL3-78B avg 43.5 % | Yes-ish: Linux, AI2-THOR + Habitat 2.0 + VLMBench, local models via LMDeploy (48 GB-GPU guidance). |
| Embodied IF | EmbodiedEval (2025) | human 97.26 %; GPT-4o 25.00 % (GcS 32.42 %); Qwen-VL-Max 28.07 %; open best LLaVA-OV-72B 12.80 % | Yes but needs a display / Xorg (LEGENT/Unity), ~20 GB, MIT. |
| Situated IF (intent changes) | SIF (ECCV'24) | Reasoner w/ learned perception SPL 19 / 11 / 15 (PnP / S_obj / S_hum); oracle 81 / 60 / 29 | Yes (Habitat, Spot model; 240 val + 240 test tasks). |
| Interruption recovery (voice) | IHBench (2026) | GPT Realtime 2 TF win .728 / RQ pass .624; Gemini 2.5 Flash (thinking) RQ .704; best open Qwen3-Omni-30B .304 / .676; filler handling 7–31 % (GPT) vs 62–68 % (Gemini 2.5) | Data on HF; scoring needs an LLM judge (κ = 0.75 / 0.70 vs humans). |
| Duplex timing | Full-Duplex-Bench v1/v1.5 | Gemini Live pause TOR 0.255, latency 1.301 s; Freeze-Omni TOR 0.642, latency 0.953 s; Moshi TOR 0.985, latency 0.265 s | v1/v1.5 runs offline locally; interruption task uses a GPT-4o score. |
| Duplex multi-turn | Full-Duplex-Bench v2 | GPT-Realtime correction 4.02 / entity 4.51 / safety 4.44 (fast pacing); Moshi 2.88 / 2.76 / 3.67 | Needs a live examiner (GPT-Realtime) + Gemini judge; human agreement r = 0.59–0.69. |
| Turn-taking naturalness | Talking Turns (Apple) | human turn-change 15.9 % vs Moshi 32.7 % / cascade 37.1 %; backchannel 0.30 % vs 0.01 %; floor-taking success 63.6 % vs 17.4 % / 59.4 % | Judge is a supervised model (ROC-AUC 92.0 on Switchboard), runnable offline. |
| Voice-assistant QA | VoiceBench (TACL'26) | leaderboard: LFG-3 89.88, Nemotron 3 Nano Omni 89.39, Whisper-v3 + GPT-4o 87.80, GPT-4o-Audio 86.75; paper: Qwen2-Audio 55.35, Moshi 27.47 | Mostly offline (MC accuracy); AlpacaEval/CommonEval/WildVoice use a GPT-4o judge. |
| Audio LLM | AudioBench (NAACL'25) | 8 tasks / 26 datasets / 400 + h / 100k + samples; judge = Llama-3-70B (corr > 0.85 with GPT-4) | Yes, fully offline with a local 70B judge. |
| Long-term memory | LoCoMo | human F1 87.9 vs GPT-4-turbo 32.1, RAG 41.4; 7,512 Qs, 50 convs (10 released) | Offline if you use a local judge/F1; repo scripts assume API keys. |
| Personalisation memory | PersonaMem | ~52 % MC accuracy (GPT-4.5 / 4.1 at 128k); hardest types 30–50 % | Yes (multiple choice; 180 + histories, ~6,000 queries). |
| User-simulator agent eval | tau2-bench | GPT-4.1 pass^1 74 / 56 / 34 (retail / airline / telecom); dual-control drop 18–25 pp; user-sim error 16 % (telecom) vs 40–47 % | Yes: MIT, LiteLLM, any provider incl. local models. |
| LLM-judge reliability | Reliability without Validity (2026) | raw agreement overstates κ by 33.8–41.3 pp on MT-Bench; "85 % agreement ⇒ κ ≈ 0.48"; position bias up to 0.192 | n/a (protocol paper). |

---

## 1. Vision-and-language navigation in continuous environments (VLN-CE)

### 1.1 R2R-CE dataset — https://jacobkrantz.github.io/vlnce/data
- R2R_VLNCE_v1-3 episodes: train 10,819; val_seen 778; val_unseen 1,839; test 3,408; EnvDrop augmentation 146,304.
- Scenes: 61 (train + val_seen), 11 (val_unseen), 18 (test), 60 (EnvDrop). English only; vocab 2,504 words; 50-d GloVe.
- "is the Room-to-Room dataset by Anderson et al. 2018 ported from the Matterport3D Simulator to the Habitat Simulator."

### 1.2 VLN-CE framework README — https://github.com/jacobkrantz/VLN-CE
- RxR-CE: EN / HI / TE, "approximately 126K instructions", splits train / val_seen / val_unseen / test_challenge.
- Scenes: Matterport3D, ~90 `.glb` scenes via the official MP3D download script; MP3D Terms of Use + CC BY-NC-SA 3.0 US.
- Habitat-Sim 0.1.7 / Habitat-Lab 0.1.7 (old pin; modern forks exist).
- Metrics: SR, SPL, nDTW, NE, OS. Action space as extracted: forward 0.25 m, turn 30° (verify in the config; R2R-CE papers commonly use 15°), success radius 3 m.

### 1.3 RxR annotations — https://github.com/google-research-datasets/RxR
- "126k navigation following demonstrations", "10x larger" than R2R; annotations CC-BY (MP3D scenes under separate ToU).
- Splits: rxr_train_guide (72.1 MB), val_seen (12.9 MB), val_unseen (12 MB), test_standard (1.9 MB), test_challenge (1.9 MB).
- nDTW = normalised DTW cost between agent path and reference; SDTW = "Success-weighted normalized DTW cost".

### 1.4 SOTA: ETP-R1 (Dec 2025) — https://arxiv.org/html/2512.20940
- 0.5B-parameter model; offline pretraining on 3.18M trajectories, then online SFT, then GRPO.
- R2R-CE val-unseen: NE 3.94, OSR 72, SR 65, SPL 56 (G3D-LF 4.53 / 68 / 61 / 52; HNR 4.42 / 67 / 61 / 51; ETPNav 4.71 / 65 / 57 / 49).
- R2R-CE test-unseen: NE 4.19, OSR 69, SR 64, SPL 54 (G3D-LF 58 / 51).
- RxR-CE val-unseen: NE 5.22, SR 59.92, SPL 48.97, nDTW 65.31, SDTW 50.41 (HNR 56.39 / 46.73 / 63.56 / 47.24).

### 1.5 SOTA: MobileVLA-R1 (Nov 2025, ECCV'26) — https://arxiv.org/html/2511.17889
- LLaMA3-8B backbone initialised from NaVILA; LoRA r = 16, α = 32; CoT data 18K episode / 78K step / 38K nav samples; SFT on 4×H20 (96 GB) ~20K steps; GRPO on 1×H20, 1K steps.
- R2R-CE val-unseen: NE 4.05, OS 69.7, SR 68.3, SPL 65.2 (NaVILA 5.22 / 62.5 / 54.0 / 49.0; StreamVLN 4.98 / 64.2 / 56.9 / 51.9; ETPNav* 4.71 / 65.0 / 57.0 / 49.0).
- RxR-CE val-unseen: NE 3.92, SR 71.5, SPL 66.8, nDTW 76.1 (NaVILA 6.77 / 49.3 / 44.0 / 58.8; StreamVLN 6.22 / 52.9 / 46.0 / 61.9).
- Real Unitree Go2: workspace 93 % / 91 % (simple / complex), corridor 100 % / 86 %, outdoor 100 % / 96 %.
- Latency: "approximately 10 seconds per reasoning step; 15 seconds end-to-end with I/O and network transmission on remote H20 server". This is the number to keep in mind: the highest-SR VLN-CE model on a Go2 is nowhere near duplex-rate.

### 1.6 Qwen-RobotNav (2026 tech report) — https://arxiv.org/html/2606.18112
- 2B / 4B / 8B variants; 15.6M training samples (85 % nav trajectory planning, 15 % VL reasoning); 8B trained for 2,816 H100 GPU-hours.
- VLN (panoramic setting) R2R val-unseen: 72.1 SR / 66.6 SPL; RxR: 76.5 SR / 72.5 nDTW (8B).
- HM3D-OVON: 4B SR 57.7 / 60.1 / 53.1 (seen / synonyms / unseen), SPL 24.4 / 25.1 / 20.9; 8B SR 56.1 / 57.8 / 51.2.
- Inference on Jetson Thor FP8: on-device 204 ms (4.9 Hz); remote server 196 ms (5.1 Hz). This is the closest published "VLM nav policy on Jetson at ~5 Hz" data point; Parcel's Orin is a generation older.

---

## 2. Open-vocabulary and lifelong object navigation

### 2.1 HM3D-OVON — https://arxiv.org/html/2409.14296
- 15,661 annotated instances, 379 categories, 181 HM3DSem scans. Train: 145 scenes × 50k episodes; val: 36 scenes × 3k episodes.
- Category splits: train 280; Val Seen 79; Val Seen Synonyms 50 (similarity 0.68–0.96); Val Unseen 49 (similarity 0.45–0.68).
- "Success is defined as the agent invoking stop within 1m of a goal object within 500 time steps." Metrics SR, SPL.
- Table III (SR / SPL, Seen | Synonyms | Unseen): BC 11.1/4.5 | 9.9/3.8 | 5.4/1.9; DAgger 18.1/9.4 | 15.0/7.4 | 10.2/4.7; RL 39.2/18.7 | 27.8/11.7 | 18.6/7.5; DAgRL 41.3/21.2 | 29.4/14.4 | 18.3/7.9; VLFM 35.2/18.6 | 32.4/17.3 | 35.2/19.6; DAgRL+OD 38.5/21.1 | 39.0/21.4 | 37.1/19.9.
- Noise robustness (Val Seen, odometry + actuation noise): DAgRL+OD 38.5→38.2 SR (−0.3); VLFM 35.2→28.8 (−6.1). No real-robot results.
- 2026 SOTA (Qwen-RobotNav-4B): 53.1 SR / 20.9 SPL unseen. Note SPL stays ~20 even as SR rises: open-vocab search remains inefficient.

### 2.2 GOAT-Bench — https://arxiv.org/html/2404.06609
- "GO to AnyThing": sequence of 5–10 subtasks per episode, goals uniformly over category name / language description / image.
- Train 725k episodes (145 scenes × 5k); val 36 scenes × 10 episodes (50–100 subtasks each). Val Unseen: 36 categories, 1,282 goals; Val Seen Synonyms: 31 categories, 877 goals.
- Success: stop within 1 m of the goal instance within 500 actions per subtask (the arXiv HTML renders the threshold as "11m", almost certainly a typo for 1 m). SPL is computed from the shortest path from the previous goal.
- Val Unseen SR / SPL: Modular GOAT 24.9 / 17.2; Modular CLIP-on-Wheels 16.1 / 10.4; SenseAct-NN Skill Chain 29.5 / 11.3; SenseAct-NN Monolithic 12.3 / 6.8. Val Seen object goals: 29.4 / 25.8 / 25.7 SR (Modular GOAT / skill chain / monolithic); language goals favour Modular GOAT by ~5 pp; image goals favour the skill chain by ~15 pp (CroCo-v2 features).
- 2026 SOTA (HGR, https://arxiv.org/html/2604.04108): full val SR 64.14 / SPL 50.1 (3D-Mem 62.9 / 44.7; ConceptGraph 61.2 / 44.3); 278-subtask subset SR 72.41 / SPL 56.22 (3D-Mem 69.1 / 48.9). HGR-style zero-shot VLM + scene-memory methods roughly doubled the 2024 numbers; note the two evaluation subsets are not comparable.

### 2.3 OVMM lessons (NeurIPS'23 HomeRobot) — https://arxiv.org/html/2407.06939
- 61 teams, 79 final leaderboard submissions. Task: "Move (object) from (start location) to (goal location)" on Hello Robot Stretch in unseen homes.
- Metrics: overall success; partial success over four stages (find object, grasp, find receptacle, place); steps.
- Baselines: heuristic 0.8 %, RL 0.0 %. Sim: UniTeam 10.8 %, Rulai 3.2 %, KuzHum 2.4 %. Real: UniTeam 33.3 %, Rulai 0.0 %, KuzHum 0.0 %.
- Lesson quoted: winners prioritised "error detection and recovery mechanisms over raw perception accuracy", task-state modelling with retry logic, and perception engineering around VLM limits.

### 2.4 HM3D licence — https://aihabitat.org/datasets/hm3d/
- 1,000 high-resolution scans; "free and available here for academic, non-commercial research" via Matterport; citation required. Implication: fine for Parcel's internal evals, not for shipping training data commercially without a separate agreement.

---

## 3. Social navigation

### 3.1 Habitat 3.0 SocialNav — https://arxiv.org/html/2310.13724
- Task: find and follow a humanoid while keeping 1–2 m in unseen scenes. Metrics: Finding Success S (within 1–2 m, facing the humanoid); SPS (success weighted by path steps vs oracle); Following rate F (fraction of steps at 1–2 m after finding); Collision Rate CR (episodes ending in robot–humanoid collision).
- End-to-end RL baseline: 97 % finding success, CR 0.51 ± 0.03; heuristic expert 100 %, CR 0.52. A 50 % collision rate on the reference baseline says the metric is loose; use PSC/H-Coll from Falcon instead.
- Sim speed ~1,190 FPS with a humanoid and a robot in batched envs; 12 avatar body shapes (4 M / 4 F / 4 neutral); HSSD 37 train / 10 test scenes.
- Social Rearrangement: SR and Relative Efficiency; 30-participant human-in-the-loop study, learned policies 123–134 % RE vs solo human.

### 3.2 Falcon / Social-HM3D + Social-MP3D (ICRA'25) — https://arxiv.org/abs/2409.13244 (PDF read)
- 844 HM3D scenes + 72 MP3D scenes (zero-shot), up to 6 humans per scene, density scaled by area, ORCA collision avoidance, goal-directed walking with natural pauses.
- Metrics: SR, SPL, STL (success weighted by time length), H-Coll (human collision rate), PSC. "Considering the human collision radius is 0.3m and the robot is 0.25m, the PSC distance threshold is set to 1.0m."
- Table II (Suc / SPL / STL / PSC / H-Coll, %), Social-HM3D: A* 46.14 / 46.14 / 46.12 / 90.56 / 53.50; ORCA 38.91 / 38.91 / 38.44 / 90.55 / 47.52; Proximity-Aware 20.11 / 18.57 / 19.51 / 92.91 / 33.99; Falcon 55.15 / 55.15 / 54.94 / 89.56 / 42.96. Social-MP3D: A* 43.85 / … / 86.74 / 57.94; ORCA 40.38 / … / 91.76 / 47.16; Proximity-Aware 18.45 / 17.09 / 16.41 / 93.37 / 32.18; Falcon 55.05 / 55.04 / 54.80 / 90.01 / 42.19.
- No real-robot results. Read the trade-off: the safest method (Proximity-Aware, H-Coll 34 %) has the worst SR (20 %); the SOTA still collides with a human in 42 % of episodes.

---

## 4. Constrained-space navigation: BARN

### 4.1 BARN Challenge 2026 page — https://people.cs.gmu.edu/~xiao/Research/BARN_Challenge/BARN_Challenge26.html
- Clearpath Jackal, 2D LiDAR, max 2 m/s; 300 public environments + generator; 50 hidden eval envs × 10 trials.
- Score per env: s_i = 1_success × OT_i / clip(AT_i, 2·OT_i, 8·OT_i); OT = path length / 2 m/s; upper bound moved from 4·OT to 2·OT so the max score is 0.5 (was 0.25).
- Physical phase: 3 obstacle courses, 5 timed trials in 30 min, top 3 count. Winners: 2026 IN2BOT / EW-Glab / Team Robo; 2025 RRSL 7/9, RobotiXX 3/9, UVA AMR 1/9; 2024 LiCS-KI 6/9, MLDA_EEE 5/9, AIMS 5/9.

### 4.2 Lessons from the 3rd BARN Challenge, ICRA 2024 (IEEE RAM, Sept 2024) — https://par.nsf.gov/servlets/purl/10596639
- Six simulation teams; six ROS move_base baselines score 0.1656–0.4354. Sim results: LiCS-KI 0.4762, AIMS 0.4723, EIT-NUS 0.3795, MLDA_EEE 0.2476.
- Physical (120 cardboard boxes, 3 courses): LiCS-KI 6/9 (avg 30 / 35 / NA s), MLDA_EEE 5/9, AIMS 5/9, EIT-NUS 0/9; nobody cleared course 3 except AIMS (3 trials).
- Lessons: all teams hybrid (learning + classical + safety layer); LiCS-KI used behaviour cloning with Gaussian noise injection and a rectangular safety-check layer; first team to win both sim and physical with a learning-based planner.

---

## 5. Embodied instruction following

### 5.1 EmbodiedBench (ICML'25 oral) — https://arxiv.org/html/2502.09560 ; https://github.com/EmbodiedBench/EmbodiedBench
- 1,128 test instances: EB-ALFRED 300, EB-Habitat 300, EB-Navigation 300, EB-Manipulation 228. Six subsets (Base, Common Sense, Complex Instruction, Spatial Awareness, Visual Appearance, Long Horizon), ~50 per subset (60 for Navigation, 48 / 36 for Manipulation).
- Simulators: AI2-THOR (ALFRED, Navigation), Habitat 2.0, VLMBench (CoppeliaSim). 24 MLLMs evaluated.
- Abstract: "with the best model, GPT-4o, scoring only 28.9% on average" refers to EB-Manipulation.
- Success rates (ALFRED / Habitat / Navigation / Manipulation / avg): GPT-4o 56.3 / 59.0 / 57.7 / 28.9 / 50.5; Claude-3.5-Sonnet 64.0 / 68.0 / 44.7 / 25.4 / 50.5; Gemini-1.5-Pro 62.3 / 56.3 / 24.3 / 21.1 / 41.0; InternVL3-78B (best open) 39.0 / 55.0 / 53.7 / 26.3 / 43.5; Qwen2-VL-72B ALFRED 33.7; Llama-3.2-90B-Vision 32.0.
- Repo: Linux, three conda envs, Docker file, headless X server, local models through LMDeploy with tp = ceil(size_B / 10) on 48 GB GPUs.

### 5.2 EmbodiedEval (2025) — https://arxiv.org/html/2501.11858 ; https://github.com/thunlp/EmbodiedEval
- 328 tasks, 125 scenes (Objaverse, AI2-THOR, HSSD, Sketchfab), LEGENT (Unity) simulator; five categories: navigation, object interaction, social interaction, attribute QA, spatial QA.
- Metrics: success rate, goal-condition success (GcS), SPL, interaction success rate.
- Human 97.26 %. GPT-4o 25.00 % (GcS 32.42 %); Qwen-VL-Max 28.07 %; Gemini-1.5-Pro 19.26 %; LLaVA-OneVision-72B 12.80 %; InternVL2-8B 8.23 %.
- Failure modes: grounding hallucination, insufficient exploration, poor spatial reasoning, wrong planning / state estimation.
- Repo: Windows / macOS / Linux with display; Linux servers need sudo, NVIDIA drivers, Xorg; ~20 GB; MIT; Python 3.10.

### 5.3 Situated Instruction Following (ECCV'24) — https://arxiv.org/pdf/2407.12061 (PDF read)
- Three task types: PnP (static), S_obj (a human moved the object), S_hum (the moving human is the receptacle); instructions are ambiguous, temporal, dynamic. 240 val + 240 test tasks (40 seen / 40 unseen per type); 6 training houses + 4 unseen = 10 houses; Spot-model agent, 0.17 m step.
- SPL is the primary metric (tests the reasoning strategy). Table 6 (Val Seen, PnP / S_obj / S_hum SPL): Oracle planner + oracle perception 100 / 100 / 98; Oracle + learned perception 47 / 44 / 59; Prompter oracle 70 / 29 / 29, learned 17 / 10 / 11; Reasoner oracle 81 / 60 / 29, learned 19 / 11 / 15.
- Table 9 (ambiguous vs clear, GT vision, Reasoner SR): S_obj clear 72 / amb 77; S_hum clear 15 / amb 75. Following a moving human is where even oracle-perception planners collapse.
- This is the closest published benchmark to "the instruction's meaning changes mid-task"; it does not cover spoken interruptions.

### 5.4 IHBench (2026, Boson AI) — https://arxiv.org/html/2606.19595 (PDF read)
- Post-interruption recovery for voice agents driving structured workflows. Six interruption types: Normal, Impatient, Correction, Topic Switch, Filler (backchannel — continue without repeating), Pushback.
- 45 conversations, 10 enterprise domains, 428 interruption points, 30.1 messages avg (19–40).
- Metrics: Task-Fulfilment win rate vs a GPT-4o Audio reference; Recovery-Quality pass rate on 2–4 type-specific criteria. 27 configurations (17 closed, 10 open), 3 epochs, 1000-iteration bootstrap over N = 428.
- Table 1: GPT Realtime 2 (medium) TF .728 / RQ .624; GPT Realtime 2 (xhigh) .702 / .613; GPT Realtime 1.5 .654 / .655; Gemini 3 Flash (thinking) .632 / .605; GPT Realtime .597 / .680; Gemini 2.5 Flash (thinking) .586 / .704; Gemini 2.5 Flash .488 / .679; Gemini 3.1 Flash Live .419 / .611; GPT Realtime Mini .417 / .621; Qwen3-Omni-30B .304 / .676.
- Filler handling: GPT models 7–31 % pass; Gemini 2.5 family 62–68 %; Gemini 3.x regresses to 13–32 %.
- TF degrades −0.030 per additional conversation turn on average; open-weight models decline 3.3× faster (closed mean slope −0.016).
- Judge validation: human κ = 0.75 (TF) / 0.70 (RQ), "at or above the inter-judge κ values typically reported for LLM-as-judge in MT-Bench" (humans agree with each other at κ = 0.45–…).

---

## 6. Conversation: duplex timing, voice QA, memory, user simulators

### 6.1 Full-Duplex-Bench v1 (ASRU'25) — https://arxiv.org/html/2503.04721 ; https://github.com/DanielLin94144/Full-Duplex-Bench
- Four tasks: pause handling (speaker pauses 0.4–1.0 s but holds the turn), backchannel, smooth turn-taking, user interruption.
- Data: Candor 216 (pause) + 119 (turn-taking); ICC 55 (backchannel); synthetic 200 (interruption) + 137 (pause) = 727 samples.
- Metrics: Takeover Rate (TOR, lower is better for pause/backchannel); backchannel frequency (events/s); JSD vs human backchannel timing; response latency (s from user turn-end); GPT-4o score 0–5 for interruption responses; latency after interruption.
- Results (pause TOR / backchannel TOR / turn-taking latency / interruption TOR / GPT-4o score): dGSLM 0.934 / 0.935 / 0.352 s / 0.917 / 0.201; Moshi 0.985 / 0.980 / 0.265 s / 1.000 / 0.765; Freeze-Omni 0.642 / 0.481 / 0.953 s / 0.867 / 3.615; Gemini Live 0.255 / 0.310 / 1.301 s / 0.891 / 3.376.
- README: v1.0/v1.5 static offline evaluation "runs offline locally with server-client inference"; v1.5 adds overlap events (listener backchannel, side conversation, ambient speech); v2.0 real-time via WebRTC/WebSocket with an automated examiner; v3.0 tool use under real human disfluent speech (5 disfluency types).

### 6.2 Full-Duplex-Bench v2 — https://arxiv.org/html/2510.07838
- Examiner = GPT-Realtime speaking via TTS, steering stepwise semantic goals; Fast pacing (may interrupt) vs Slow pacing (waits). Four families: Daily, Correction, Entity Tracking, Safety (11 hazard classes).
- Scores 1–5 from Gemini 2.5 Flash on Parakeet-TDT transcripts: turn-taking fluency, multi-turn instruction following, task-specific.
- Table 1 (Correction / Entity / Safety): Fast — Freeze-Omni 2.74 / 2.62 / 3.94; Moshi 2.88 / 2.76 / 3.67; GPT-Realtime 4.02 / 4.51 / 4.44. Slow — Freeze-Omni 3.50 / 2.86 / 4.27; Moshi 3.46 / 3.84 / 3.51; GPT-Realtime 3.94 / 4.12 / 4.53.
- Automated-vs-human agreement Pearson r = 0.59–0.69.

### 6.3 Talking Turns (Apple, 2025) — https://arxiv.org/html/2503.01174
- Judge: supervised turn-taking event predictor trained on Switchboard (2000 / 300 / 138 conversations); ROC-AUC continuation 93.3, backchannel 89.4, turn change 90.8, interruption 91.3, silence 95.1, overall 92.0; OOD Columbia Games 91.5, Fisher 91.0.
- Systems: Moshi; cascade (VAD + Whisper + SmolLM + MeloTTS); GPT-4o + Whisper, SALMONN, Qwen2-Audio, Qwen-Audio-Chat for understanding/prediction tasks. ~4 h of human–AI conversation, 11 participants (Moshi 4 h 05, cascade 3 h 35).
- Human reference vs Moshi vs cascade: turn change 15.9 % / 32.7 % / 37.1 %; backchannel 0.30 % / 0.01 % / 0.01 %; interruption 0.4 % / 0.5 % / 0.2 %; floor-taking success 63.6 % / 17.4 % / 59.4 %. Understanding-task accuracy 56.7–66.3 %; prediction 46.5–62.2 %.

### 6.4 VoiceBench (TACL'26) — https://arxiv.org/html/2410.17196 ; https://github.com/MatthewCYM/VoiceBench ; https://matthewcym.github.io/VoiceBench/
- Paper: 6,783 instructions; AlpacaEval 636, CommonEval 200, SD-QA 553, OpenBookQA 455, MMSU 3,074, IFEval 345, AdvBench 520. Metrics: GPT-4o 1–5 judge (AlpacaEval, CommonEval); accuracy (SD-QA, OBQA, MMSU); IFEval instruction accuracy; AdvBench refusal rate.
- Paper Table 3 overall: Whisper + GPT-4o 87.23; GPT-4o-Audio 86.42; Whisper + LLaMA 79.06; Qwen2-Audio 55.35; LLaMA-Omni 37.51; VITA 34.68; Mini-Omni2 31.32; Moshi 27.47. "…significantly outperforms all open-source end-to-end models on spoken instructions, with a large margin exceeding 20 points."
- Robustness: low-resource accents (Indian, Philippine English) −15 to −35 %; end-to-end models degrade below 0.5× / above 1.5× speaking rate; mispronunciation −20.34 % avg (VITA ~−33 %), disfluency −12.55 %, repetition −9.30 %, grammar −2.68 %; speech-form refusal drops to 37–57 % for some models (text ≥ 95 %).
- Repo now lists WildVoice 1,000 (human) and BBH 1,000 (human) in addition; AlpacaEval listed as 199 in the repo table.
- Leaderboard (2026): LFG-3 89.88; NVIDIA Nemotron 3 Nano Omni 30B A3B 89.39; Ultravox-GLM-4P7 88.86 (thinking 88.79); Whisper-v3-large + GPT-4o 87.80; Ultravox-GLM-4P6 87.05; LFG-2 86.98; GPT-4o-Audio 86.75; GPT-4o-mini-Audio 82.84; Ultravox-v0.6-LLaMA-3.3-70B 81.81.

### 6.5 AudioBench (NAACL'25) — https://arxiv.org/html/2406.16020
- 8 tasks, 26 datasets (7 new), 400 + h, 100k + samples; ASR ×9, SQA ×4, speech instruction ×2, AQA ×3, captioning ×2, emotion ×3, accent ×1, gender ×2.
- Metrics: WER; Model-as-Judge (Llama-3-70B-Instruct, "highest correlation with GPT-4-as-a-judge", > 0.85) rescaled 0–100; METEOR for captioning.
- Selected numbers (SALMONN / Qwen-Audio-Chat / WavLLM / Whisper + LLaMA3): LibriSpeech-clean WER 2.10 / 3.20 / 1.83 / 2.25; other 4.80 / 6.07 / 3.71 / 4.16; CN-College-Listen 65.43 / 74.50 / 85.25 / 60.85; Public-SG-SpeechQA 58.55 / 58.31 / 64.94 / 57.47; OpenHermes-Audio 22.40 / 44.80 / 63.0 / 11.00; ALPACA-Audio 21.60 / 52.60 / 70.8 / 9.60; AudioCaps METEOR 6.70 / 19.89 / 7.95 / 27.70; IEMOCAP emotion 45.91 / 49.30 / 34.43 / 27.34; VoxCeleb1 gender 70.51 / 99.12 / 53.41 / 70.56; accent 37.65 / 29.19 / 39.33 / 45.70.

### 6.6 LoCoMo (2024) — https://arxiv.org/html/2402.17753 ; https://github.com/snap-research/locomo
- 50 conversations (repo ships `locomo10.json`, 10 conversations); 19.3 sessions avg (max 35); 304.9 turns; 9,209.2 tokens per conversation.
- QA: 7,512 questions — single-hop 2,705 (36 %), multi-hop 1,104 (14.6 %), temporal 1,547 (20.6 %), open-domain 285 (3.9 %), adversarial 1,871 (24.9 %). Event summarisation (24.2 GT events / conversation) and multimodal dialogue generation.
- Overall F1: human 87.9; GPT-4-turbo 32.1; GPT-3.5-turbo (4K) 22.4; GPT-3.5-turbo-16K 37.8; RAG over observations 41.4; temporal reasoning ~73 % below human.
- Later work reports far higher LLM-judge accuracies on the 10-conversation subset (search summaries quoted ~86–94 %), but those use a different metric (judged accuracy) and subset; do not compare to the paper's F1.
- Repo scripts assume API keys (OpenAI / Anthropic / Gemini) plus an HF-model path; runnable offline with a local judge.

### 6.7 PersonaMem (2025) — https://arxiv.org/html/2504.14225
- 180 + histories, ~6,000 in-situ multiple-choice queries; 10 / 20 / 60 sessions = ~32k / 128k / 1M tokens; 15 scenarios (therapy, legal, recommendations, dating, health, finance, travel, …).
- Seven question types: recall facts; suggest new ideas; acknowledge latest preference; track preference evolution; revisit reasons for updates; preference-aligned recommendations; generalise to new scenarios.
- 128k results: GPT-4.5 ~52 %, GPT-4.1 ~52 %, Gemini-2.0-Flash ~50 %, o4-mini ~50 %, o1 ~48 %, Claude-3.7-Sonnet ~48 %, DeepSeek-R1 ~47 %, Llama-4-Maverick ~43 %. Easiest (fact recall, preference tracking) 60–70 %; hardest (new ideas, recommendations, generalisation) 30–50 %.

### 6.8 tau2-bench (2025) — https://arxiv.org/html/2506.07982 ; https://github.com/sierra-research/tau2-bench ; https://taubench.com
- Dual-control Dec-POMDP: agent and user both hold tools over a shared world; one player acts per turn. Domains: retail 115 tasks, airline 50, telecom 114 (2,285 generated, subsampled).
- User-simulator error: telecom 16 % total / 6 % critical; retail 40 % / 12 %; airline 47 % / 13 %. Reliability came from "tightly coupling the user simulator to the environment" (tools constrain the user).
- pass^k = probability all k i.i.d. trials succeed. GPT-4.1 pass^1 / pass^4: retail 74 / 82, airline 56 / 68, telecom 34 / 45; o4-mini ~50 / ~62 (telecom 50 / ~61); Claude 3.7 Sonnet ~45–49 / ~60–62.
- No-user → dual-control drop: GPT-4.1 −18 pp, o4-mini −25 pp pass^1. Oracle-plan ablation helps o4-mini more than GPT-4.1.
- Repo: MIT; LiteLLM (any provider, local models possible); `tau2 run --domain airline --agent-llm … --user-llm …`; extra domains mock, banking_knowledge. Leaderboard (2026): τ² Qwen3.5-397B-A17B 87.9 pass^1, Gemini 3.0 Pro 85.4, Claude Opus 4.5 85.3; τ³-Voice Pine Voice Preview 75.4, grok-voice-think-fast-1.0 67.3; τ³-Banking Qwen 3.8 Max 55.2.

### 6.9 LLM-as-judge reliability

**Reliability without Validity (2026)** — https://arxiv.org/html/2606.19544
- 21 judges, 9 providers, MT-Bench / JudgeBench / RewardBench, 118 runs, ~541,000 judgments.
- "kappa deflation": raw agreement overstates chance-corrected agreement by 33.8–41.3 pp on MT-Bench (mean gap 23.7 pp JudgeBench, 10.4 pp RewardBench); "a judge reporting 85% agreement on MT-Bench has κ≈0.48".
- Test-retest 0.888–0.992; position-flip degradation ≥ 1.5× for 7 / 16 judges on harder benchmarks; position bias 0.002–0.192 (Qwen 3 8B and Gemini 2.5 Flash > 0.10 despite test-retest > 0.95); verbosity bias < 0.011 for all 21.
- Minimum Viable Validation Protocol: report κ not raw agreement; AB + BA swaps; ≥ 3 independent runs; ≥ 2 benchmarks; audit the consistency–bias paradox.

**LLMs-as-Judges in free-form QA (WiNLP 2025)** — https://aclanthology.org/2025.winlp-main.37.pdf (PDF read)
- 100 samples per dataset (TruthfulQA, TriviaQA, HotpotQA); judges Mistral 7B, GPT-3.5, Llama-3.1 70B; binary True/False verdicts with references; human majority vote as gold.
- Percent agreement human 82–99 % vs judges 72–96 %. Cohen's κ (single judge vs human majority) 0.63–0.93; ensemble-majority vs human majority κ 0.72–0.96 (TruthfulQA 0.72–0.79; TriviaQA 0.79–0.96; HotpotQA 0.88–0.96). Harder / more subjective task ⇒ lower κ.
- The "dialogue κ = 0.57" figure that appeared in a search summary is not in this paper and was not verified; treat as unsourced.

**Benchmarks' own judge validations** (already above): Full-Duplex-Bench v2 r = 0.59–0.69; IHBench κ = 0.75 / 0.70; AudioBench Llama-3-70B judge corr > 0.85 with GPT-4 (not with humans).

---

## 7. What this means for Parcel's Model A / Model B

Context: Parcel's frozen instruction-nav matrix sits at SR 0.20; its conversation-quality scorer reports capability grounding 2/10 and personal conversation 3/13; the hosted OpenAI Realtime voice is the narrator; Model A is the proposed duplex trainable policy, Model B the command-injection / narration-context translator.

1. **Navigation bar to aim at, and what "generalized" costs.** Open-vocab ObjectNav SOTA on HM3D-OVON unseen is SR ~53 / SPL ~21 (Qwen-RobotNav-4B, 15.6M samples, 2,816 H100-h for the 8B); the 2024 baselines were SR 35–37. Lifelong multi-goal (GOAT) went from SR 29.5 to 64–72 in two years, but through zero-shot VLM + 3D scene-memory pipelines, not end-to-end policies (SenseAct-NN monolithic RL was 12.3 SR). Parcel's SR 0.20 on its own matrix is in the range of the 2024 modular baselines; a trainable Model A should first be evaluated on HM3D-OVON / GOAT-Bench val-unseen so the number is comparable to something. SPL ~20 is the honest SOTA for search efficiency; do not promise better without a memory module.
2. **Duplex-rate control is not what the SOTA nav models do.** The best VLN-CE model deployed on a Go2 (MobileVLA-R1, SR 68.3) runs at ~10 s per reasoning step, 15 s end-to-end on a remote H20; Qwen-RobotNav reaches 4.9 Hz on a Jetson Thor at FP8 with a 4B/8B model. Parcel's 10 Hz act-token frame clock therefore cannot be a VLM in the loop; Model A must be a small policy (ETP-R1 shows 0.5B is enough for SR 65 / SPL 56 on R2R-CE) with the VLM/hosted model updating a global plan asynchronously. Measure Model A's latency as a first-class metric alongside SR/SPL.
3. **Mid-task amendments have two published proxies, neither complete.** SIF shows even oracle-perception planners fall to SPL 29 (S_hum) when the human moves and the instruction's referent changes, and that ambiguity handling is the failure mode (S_hum clear SR 15 vs ambiguous 75 for Reasoner with GT vision — the planner over-commits on clear instructions). IHBench measures spoken interruption recovery (correction, topic switch, filler, pushback) at TF .728 / RQ .624 for the best hosted realtime model, with −0.030 TF per turn. Parcel's "revise / keep / queue" injection is exactly IHBench's Correction / Normal / Topic-Switch taxonomy applied to a navigation workflow; build the amendment eval as an IHBench-style scenario set (interruption point, type, 2–4 type-specific pass criteria) over the existing 5×5 instruction-nav matrix, and score recovery with a rubric judge validated to κ ≥ 0.7 as IHBench did.
4. **Model B's narration timing should be scored with Full-Duplex-Bench-style metrics, not only content.** The relevant numbers: pause-handling TOR (Gemini Live 0.255 vs Moshi 0.985), response latency (0.27–1.30 s), backchannel rate (humans 0.30 % vs 0.01 % for both Moshi and the cascade), floor-taking success (humans 63.6 %, Moshi 17.4 %). "Sure, I'll check the sofa" is a turn-taking event that must land inside a ~1 s window; "Done! Should I go back?" is a robot-initiated turn that must not barge in (TOR). Both are measurable offline with v1/v1.5 plus a Talking-Turns-style supervised judge (ROC-AUC 92) and require no hosted model. Full-Duplex-Bench v2's examiner pattern (LLM examiner driving stepwise goals, Fast vs Slow pacing, 1–5 rubric judge with r ≈ 0.6–0.7 vs humans) is the template for the sim-to-real "LLM converses with the robot while it navigates" rig.
5. **User simulators: tie them to the environment.** tau2-bench's telecom simulator reached 16 % error only by giving the simulated user tools that constrain it to the shared state; free-text simulators sat at 40–47 % error. The owner's "LLM converses with the robot while it navigates" harness should give the simulated owner the same StateDigest and the same map the robot has (dual control), and report pass^k over ≥ 4 trials, because pass^1 → pass^4 gaps of 8–12 pp are normal even for frontier models. Expect a large drop from scripted commands to a live user (18–25 pp on tau2).
6. **The conversation-quality scorer (2/10, 3/13) needs a validity audit before it drives training.** Raw agreement overstates κ by 34–41 pp on chat benchmarks; a judge with 85 % agreement has κ ≈ 0.48; position bias up to 0.19; verbosity bias is small. Adopt the MVVP: κ not agreement, AB/BA swaps, ≥ 3 runs, ≥ 2 benchmarks. For grounding specifically, AudioBench's finding that a local Llama-3-70B judge correlates > 0.85 with GPT-4 means a local judge is acceptable and removes the hosted dependency from the eval loop.
7. **Memory metrics exist; pick the cheap one.** PersonaMem is multiple-choice, offline, 32k/128k/1M variants, and frontier models sit at ~50 %; it is the right shape for "does the whisperer's StateDigest + history let the narrator remember the owner's preferences". LoCoMo's F1 is noisy (human 87.9 vs GPT-4 32.1) and its later "accuracy" numbers are on a different metric/subset; use it for temporal-reasoning questions only.
8. **Social navigation needs PSC + H-Coll, not Habitat 3.0's collision rate.** Habitat 3.0's SocialNav baseline succeeds 97 % of the time while colliding in 51 % of episodes; Falcon's Social-HM3D gives PSC (1.0 m threshold) and H-Coll (SOTA still 42 %). A companion dog that follows its owner is the Habitat 3.0 "find and follow at 1–2 m" task; score it with SPS + following rate + PSC + H-Coll.
9. **Licence and offline feasibility.** All Habitat-family benchmarks (VLN-CE, HM3D-OVON, GOAT, Social-HM3D, OVMM) run offline on a desktop GPU but require the MP3D ToU (CC BY-NC-SA 3.0 US) and the HM3D academic non-commercial licence; the RxR annotations are CC-BY; tau2-bench and EmbodiedEval are MIT; BARN is ROS/Gazebo. Judge dependencies: VoiceBench (GPT-4o on 3 subsets), Full-Duplex-Bench v1 interruption task (GPT-4o score) and v2 (GPT-Realtime examiner + Gemini judge) are the only ones that force a hosted call; all can be swapped for a local judge with a re-validation.
10. **Sim-to-real caveat from the competitions.** OVMM: 10.8 % sim → 33.3 % real for the winner and 0 % for the runners-up; BARN: 0.4762 sim score → 6/9 physical trials, and only hybrid stacks with an explicit safety layer survived. Plan the Go2 sim-to-real rig around error detection and recovery (the OVMM lesson) and a safety layer independent of Model A (the BARN lesson), and report both sim and physical numbers side by side.

---

## 8. Open questions
- What SR / SPL does Parcel's current planner + SigLIP-2 grounding get on HM3D-OVON val-unseen and GOAT-Bench val-unseen when run through the product code path? (Needed to place the 0.20 figure.)
- Can a 0.5B ETP-R1-class policy hit ≥ 5 Hz on the Orin 64 GB at FP8/INT8, and what SR does it lose versus the 8B models?
- Is there any published benchmark that scores spoken interruption of a *moving* robot with a navigation-state-dependent rubric? None found; IHBench (workflows) + SIF (moving humans) are the nearest halves.
- GOAT-Bench "1 m" success radius: the arXiv HTML renders "11m"; confirm in the PDF before configuring an evaluator.
- VLN-CE turn angle: README extraction said 30°, common configs use 15°; check the YAML.
- The "dialogue κ = 0.57" judge-reliability figure surfaced by search was not found in the fetched WiNLP paper; source still unknown.
- Full-Duplex-Bench v1.5 numbers (overlap events: side conversation, ambient speech) were not extracted; these matter for a robot in a household with several people.
- Talking-Turns judge and Full-Duplex-Bench measure human-human-like timing; whether a companion robot *should* backchannel at human rates is a product decision, not a benchmark outcome.
