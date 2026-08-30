# Navigation WITH dialogue — datasets, benchmarks, models (literature note, 2026-08-29)

Scope: agents that talk while navigating, ask for help mid-task, or must absorb instruction changes / interruptions mid-task. Every source below was fetched and read (arXiv abstract or HTML, PMLR/AAAI PDF via pdftotext, or project README). Numbers are copied from the source; quotes are verbatim.

Headline answer to the owner's question ("does anything evaluate spoken interruptions during motion?"):
**No navigation-with-dialogue dataset does.** CVDN, DialFRED, TEACh, Alexa Arena, HANNA, VNLA, Just Ask, RobotSlang, Talk the Walk, WAY, AVDN and DialNav are all typed-text, turn-based, and almost all are evaluated *from dialog history* (offline replay of a human-human chat). The closest things to "speech interrupts motion" are (a) ELLSA (full-duplex speech+action, but *manipulation*, LIBERO), (b) DuplexSLA/DuplexOmni (audio-only full duplex with an action/tool channel), (c) InterruptBench (web agents, text), (d) P^3 and YAY-Robot (real robots that accept a new verbal instruction mid-task), (e) SIF (the human moves, so intent changes mid-task), and (f) "From Woofs to Words" (a Go2 guide dog that talks during navigation, but with Wizard-of-Oz motion). The Parcel Model A/B pair would be, as far as this survey found, the first *trainable, evaluated* system for spoken mid-navigation amendments on a legged robot.

---

## 1. Canonical dialogue-navigation datasets (2018-2021)

### 1.1 CVDN / NDH — Vision-and-Dialog Navigation (Thomason, Murray, Cakmak, Zettlemoyer; CoRL 2019)
- arXiv abstract: https://arxiv.org/abs/1907.04957 ; PMLR PDF (read): https://proceedings.mlr.press/v100/thomason20a/thomason20a.pdf ; code/data: https://github.com/mmurray/cvdn/
- "We collect 2050 human-human navigation dialogs, comprising over 7k navigation trajectories punctuated by question-answer exchanges, across 83 MatterPort houses." Built on the R2R MatterSim ("On average, 1 step corresponds to 2.25 meters").
- "Dialogs average about 6 utterances each (3 question and answer exchanges), with a fraction being much longer—up to 26 utterances. Some dialogs have no exchanges (about 5%)". "over 90% of all dialogs, contain egocentric references requiring the agent's position and orientation to interpret." "More than 10% of dialogs exhibit conversational repair".
- Each HIT paid $1.25/worker; "the entire dataset collection cost over $7k."
- NDH task: "We extract 7415 NDH instances from the 2050 navigation dialogs". Metric = goal progress in metres (topological distance reduction). Supervision variants: Oracle path, Navigator path, Mixed.
- Table 3 (seq2seq, full dialog history, mixed supervision): val seen 6.16 m / val unseen 1.83 m (2.10 m with previous questions) / test unseen 2.27-2.35 m, versus Shortest-Path agent 9.52 / 9.58 / 9.76 m and random 0.42 / 1.09 / 0.83 m. Unimodal "target-only" input gets 1.15 m unseen. So even the best 2019 baseline covers ~20% of the achievable progress in unseen houses.
- Dialog happens *between moves*: Navigator stops, types a question, Oracle answers, Navigator moves on. No speech, no concurrent motion, no interruptions.
- License: Matterport3D data requires separate access agreement (README); repo built on Matterport3DSimulator.

### 1.2 RobotSlang (Banerjee, Thomason, Corso; CoRL 2020)
- arXiv: https://arxiv.org/abs/2010.12639 ; PMLR PDF (read): https://proceedings.mlr.press/v155/banerjee21a/banerjee21a.pdf
- "169 natural language dialogs between a human DRIVER controlling a robot and a human COMMANDER" ; "nearly 5k utterances and over 1k minutes of robot camera and control streams" ; "169 trials ... carried out in 116 unique mazes" ; three target objects per trial; physical small robot car in tabletop mazes.
- "An average of 28 messages was sent per dialog, and dialogs averaged 200 words. By contrast, dialogs in ... CVDN ... contain an average of only 81.6 words per dialog". "Dialogs lasted an average of six and a half minutes."
- This is the one classic dataset where the dialog is genuinely *simultaneous* with physical robot motion (the name is "Robot Simultaneous Localization and Mapping with Natural Language") — but it is typed chat, and the released tasks (LDH, NDH) are again *from dialog history*.
- Splits: Train 79 mazes/120 trials/360 NDH; Val 19/26/78; Test 20/28/84.
- NDH baseline (seq2seq, student forcing, vision+language): test Topological Distance 3.38 ± 1.15 m vs Immediate-Stop 4.33 m and random 4.31 m. "over 10% of trials require explicitly re-localizing".
- Human LDH: "only 0.446 meters away from the true robot center" (robot ~0.254 m long). Physical transfer not validated ("Due to COVID-19").

### 1.3 Talk the Walk (de Vries et al., 2018)
- arXiv: https://arxiv.org/abs/1807.03367 ; PDF (read): https://arxiv.org/pdf/1807.03367
- NYC 360° captures of five neighbourhoods ("approximately 5x5 grid ... grid-size of roughly 10x10 per neighborhood"); tourist "can simultaneously chat with the guide and navigate".
- "over 10k successful dialogues"; "Turkers successfully completed 76.74% of all finished tasks (we use this statistic as the human success rate)"; "more than 62 acts (i.e utterances and actions)" per success; guide ~9, tourist ~8 utterances per dialogue; vocabulary >10K.
- Localization from a single human utterance: 16.17% test accuracy (Table 3) vs 6.25% random; emergent-language MASC reaches 69.85% (T=3). Full task (Table 4): humans 76.74%, best natural-language model 50.00% test, best emergent 88.33% (under "perfect perception").

### 1.4 HANNA (Nguyen & Daumé III; EMNLP 2019) and VNLA (Nguyen et al.; CVPR 2019)
- HANNA arXiv: https://arxiv.org/abs/1909.01871 ; PDF (read): https://arxiv.org/pdf/1909.01871. VNLA PDF (read): https://arxiv.org/pdf/1812.04155
- HANNA: object-finding in "68 Matterport3D environments"; agent may *request* help from a simulated assistant that returns a language subgoal + image; reuses R2R's "21,567 natural language instructions"; "training set of 51 environments and less than 9,000 language instructions"; splits ~5,000 tasks each.
- Table 3 (test): No assistance SR 17.21% seen / 8.10% unseen; "Learn to interpret assistance (ours)" 88.37% seen / 47.45% unseen with 2.9 / 5.8 requests per task; perfect-assistance-interpretation skyline 90.99 / 83.56. Table 5: RandomAsk 37.05% unseen (6.8 req), AskEvery5 34.42% (7.1 req), learned 47.45% (5.8 req). Language instruction adds +15.17 points over target-image-only in unseen (31.88 → 47.45).
- VNLA (ASKNAV dataset, Matterport3D, 289 object labels, 26 room labels, 61/11/18 env split; advisor gives k-step language subgoals under a help budget). Table 2 test-unseen SR: NONE 6.36%, FIRST 20.00%, RANDOM 25.05%, LEARNED 34.50%, TEACHER 34.95%; test seen 28.39% → 52.09%.
- Both are "ask when lost" — the *agent* initiates the dialogue mid-navigation, budgeted. Still typed, still turn-based.

### 1.5 Just Ask (Chi, Shen, Eric, Kim, Hakkani-Tür; AAAI 2020)
- PDF (read): https://arxiv.org/pdf/1912.00915
- R2R agent with a simulated user; two asking policies: Model Confusion (MC, threshold ε on action-distribution confidence) and Action-Space Augmentation (ASA, learned ask action with penalty r_ask). Answers can be noise-distorted.
- Table 1 (val unseen SR / questions per episode): base 0.471 / 0; MC ε=0.5 0.807 / 1.99; ASA r_ask=0.1 0.732 / 1.92; ASA 0.5 0.494 / 0.15. Human-guided exploration beats pre-exploration "by 5% (0.554 vs. 0.504)".

### 1.6 WAY — Where Are You? (Hahn et al.; EMNLP 2020) and DiaLoc (2024)
- WAY arXiv: https://arxiv.org/abs/2011.08277 ; DiaLoc HTML: https://arxiv.org/html/2403.06846
- "~6k dialogs in which two humans -- an Observer and a Locator -- complete a cooperative localization task" in 87 Matterport3D environments; "The Observer is spawned at random in a 3D environment and can navigate from first-person views while answering questions from the Locator." Tasks: LED, Embodied Visual Dialog, Cooperative Localization. "Our best model achieves 32.7% success at identifying the Observer's location within 3m in unseen buildings, vs. 70.4% for human Locators."
- DiaLoc: per-turn prediction; "+7.08% in Acc5@valUnseen" single-shot (40.41% vs LingUNet 33.33%), multi-shot 47.15% vs 36.30%; "using more turns leads to decreased LE".

### 1.7 AVDN — Aerial Vision-and-Dialog Navigation (ACL Findings 2023)
- arXiv: https://arxiv.org/abs/2205.12219 — "over 3k recorded navigation trajectories with asynchronous human-human dialogs between commanders and followers" in a continuous photorealistic drone simulator; HAA-Transformer predicts waypoints + human attention. (Abstract only.)

---

## 2. Dialogue-enabled embodied instruction following (household, AI2-THOR)

### 2.1 TEACh (Padmakumar et al.; AAAI 2022) + TEACh-DA (SIGDIAL 2022)
- arXiv: https://arxiv.org/abs/2110.00534 ; AAAI PDF (read): https://cdn.aaai.org/ojs/20097/20097-13-24110-1-2-20220628.pdf ; repo: https://github.com/alexa/teach ; TEACh-DA: https://arxiv.org/abs/2209.12953
- "3,047 successful gameplay sessions" (of 4,365 collected, "human-level success rate of 74.17%"); AI2-THOR; 12 task types, 438 parameter variants, 109 unique scenes, 3,320 sessions in Table 2; "over 45k utterances, with an average of 8.40 Commander and 5.25 Follower utterances per session"; avg Commander utterance 5.70 tokens, Follower 3.80; vocab 3,429. Follower actions/session 131.80 ± 109.68 overall (295 for Prepare Breakfast).
- Benchmarks: EDH (Execution from Dialog History), TfD (Trajectory from Dialog), TATC (two-agent). Splits: EDH train 5758 instances, val seen 654 / unseen 2188, test seen 696 / unseen 2370.
- Episodic Transformer baseline (Table 4, all %): EDH val seen SR 9.05 GC 9.05; val unseen SR 13.49 GC 12.97; test unseen SR 9.62 GC 10.49 (+H variant: 12.5 / 16.96 val seen). TfD: val seen SR 1.02, unseen 0.48; test unseen 0.17. Compare E.T. on ALFRED: 38.24% test-seen.
- Dialog *interleaves* with actions in the raw sessions ("interleaving utterances and environment actions"), so the Follower can ask mid-task — but the released benchmarks replay history; nothing spoken; no interruption.
- TEACh-DA: dialog-act annotation of "over 3,000 situated, task oriented conversations (consisting of 39.5k utterances in total)"; "dialog acts can improve end task success rate by up to 2 points" on EDH.
- Licenses (repo): code MIT, images Apache 2.0, data CDLA-Sharing 1.0.

### 2.2 DialFRED (Gao et al.; RA-L 2022)
- arXiv: https://arxiv.org/abs/2202.13330 ; PDF (read): https://arxiv.org/pdf/2202.13330
- ALFRED augmented to "25 types of sub-goal level" tasks; "34,253 tasks in the training fold, 1,296 tasks in the validation seen fold and 1,363 tasks in the validation unseen fold"; "53K human-annotated task-relevant questions and answers" (AMT, 2 annotators per sub-goal; Fleiss κ = 0.13 on question choice); three question types: Location / Appearance / Direction; a templated oracle answers from simulator metadata.
- Questioner–performer: performer = Episodic Transformer; questioner pre-trained on human QA, RL fine-tuned (r_suc = 1.0, penalties for questions and invalid questions).
- Table I (SR seen / unseen, NQ): Instruction only 25.4 / 18.3 (0); All QAs 43.4 / 32.0 (3.24); Random QA 39.9 / 27.9 (0.81); RL begin 47.3 / 32.7 (0.37); RL anytime 47.8 / 33.6 (0.71). Table III: asking every step (Fixed 1) 51.9 / 34.7 with 21.39 questions.
- Oracle perturbation (Table II): removing 50% of location answers hurts most; questioner shifts "28% fewer location questions and 81% more direction questions".
- Episode cap 1000 steps / 10 failed actions. Typed, turn-based, sim only.

### 2.3 Alexa Arena (Gao et al.; NeurIPS 2023 D&B)
- arXiv: https://arxiv.org/abs/2303.01586 ; README (read): https://raw.githubusercontent.com/amazon-science/alexa-arena/main/README.md ; data README (read): https://raw.githubusercontent.com/amazon-science/alexa-arena/main/data/trajectory-data/README.md
- Unity-based, multi-room, user-centric HRI platform with a "dialog-enabled instruction-following benchmark". Trajectory data: "3k+ game missions" with "3 sets of language instructions" per mission and "2 sets of questions and answers collected" per instruction set; each QA has a "question_necessary" flag ("whether the annotator thinks asking this question is necessary"). Action types include Look and Goto with visual masks.
- Licenses: Arena executable non-commercial; datasets CC BY-NC 4.0; paper CC BY-NC-SA 4.0. Recommended host: 8 vCPU, 1 GPU, 32 GiB RAM, 200 GiB.
- The full paper PDF (>10 MB) could not be fetched; mission success numbers not extracted here.

### 2.4 SIF — Situated Instruction Following (Min et al., 2024)
- HTML (read): https://arxiv.org/html/2407.12061
- Instructions "are ambiguously specified, have temporally evolving intent, can be interpreted more precisely with the agent's dynamic actions". Habitat 3.0 with simulated humans; three task types PnP / S_obj (object relocated) / S_hum ("the receptacle (human) begins to move at the start of the task phase", 0.08 m per step); "240 validation and 240 testing tasks"; 10 houses.
- SR with oracle perception: Prompter 70 / 29 / 29; Reasoner 81 / 60 / 29; Oracle 100 / 100 / 98. This is the cleanest published measurement of *intent that changes while the robot acts* — but the change is the human's motion, not a spoken amendment.

---

## 3. 2024-2026 dialogue / collaboration navigation benchmarks

### 3.1 DialNav + RAIN (Han et al., 2025) and RAINbow (2026)
- DialNav HTML (read): https://arxiv.org/html/2509.12894 ; RAINbow HTML (read): https://arxiv.org/html/2606.19948v1
- Navigator + *remote* Guide who has the map but cannot see the Navigator, so the Navigator must describe where it is (localization) and ask; "2,231 DialNav episodes" over 83 Matterport3D scans ("1,401 navigation tasks from CVDN and 838 additional tasks"); "1.87 QA pairs per episode"; questions avg 27.63 words, answers 42.24 words; a "Decision Head" learns *when* to ask. Metrics: SR/OSR/SPL/NE plus Navigation Step Count, Dialog Turn Count, Localization Error. Baseline: "27.0% SR, 34.5% OSR, 25.4% SPL" val seen; "13.9% SR on val unseen". Human raters 4.48 (Navigator) / 4.28 (Guide) of 5.
- RAINbow: automatic pipeline (concatenate 2-4 R2R/RxR/CVDN paths with endpoints within 1 m and detour ratio < 1.3 → LLaVA captions at dialog points → GPT-4o-mini reformats into multi-turn dialog) yields a 238K-episode training set at "USD 0.0016 per episode", "about 2,000 times more cost-effective than manual annotation in RAIN (USD 3.75 per episode)". SR val seen 30.77 → 58.24, val unseen 14.52 → 29.05; SPL 51.65 seen; localization error −2.56 m; human check "90.0% accuracy" goal alignment, naturalness 4.76/5 vs 4.83 human.

### 3.2 QAsk-Nav / CoIN — "Benchmarking Interaction, Beyond Policy" (2026)
- HTML (read): https://arxiv.org/html/2604.00265v1
- Collaborative Instance Object Navigation: agent must ask a (simulated) user to disambiguate among look-alike instances. ~28K reasoning traces (train 15.98k / val seen 6.38k / val unseen 5.03k); question-asking protocol on ~1,400 episodes (~1,000 train / ~400 test) with text-guided edited distractor images. Light-CoNav: SR 0.451 vs AIUTA 0.303, finish rate 0.332 vs 0.199, runtime 1.15 s vs 177.83 s; on navigation "1.50x improvement on Val Unseen" with 3x fewer params and 70x faster.

### 3.3 Ask When It Pays / TANDEM (2026)
- HTML (read): https://arxiv.org/html/2606.03175
- Instance-goal navigation with an oracle; four question types with per-type cost penalties (Appearance 0.182, Region 0.162, Direction/Route 0.240, Confirmation 0.103); Weighted SR penalizes each question. "500 episodes sampled from the full benchmark" (150 easy / 200 medium / 150 hard) from "22,905 episodes across 262 scenes, 70 target categories". TANDEM: "35.3 SR@1.5 and 21.4 Weighted SR"; exploration-area reduction 47.5% on hard vs 21.9% on easy. Backbones: Qwen3.5-8B, GPT-5.4, Gemini3-Flash.

### 3.4 InstructNav (Long et al.; CoRL 2024)
- arXiv: https://arxiv.org/abs/2406.04882 ; HTML (read): https://arxiv.org/html/2406.04882
- Zero-shot generic instruction navigation via Dynamic Chain-of-Navigation (GPT-4 gpt-4-0613 for planning, GPT-4V for vision; Llama3-70B / LLaVA-NeXT-34B tested) and multi-sourced value maps. R2R-CE zero-shot SR 31%, SPL 24, NE 6.89 m; HM3D ObjectNav SR 58.0%, SPL 20.9; DDN SR 30.0%, SPL 14.2. Real robot: TurtleBot 4 + Astra Pro Plus RGB-D + RPLIDAR-A1. No latency reported. No dialogue.

### 3.5 EmbodiedBench (Yang et al.; ICML 2025 oral)
- HTML (read): https://arxiv.org/html/2502.09560v1
- 1,128 tasks: EB-ALFRED 300, EB-Habitat 300, EB-Navigation 300, EB-Manipulation 228; six capability subsets (Base, Common Sense, Complex Instruction, Spatial Awareness, Visual Appearance, Long Horizon). Best averages: GPT-4o 57.7% on EB-Navigation, 28.9% on EB-Manipulation; Claude-3.5-Sonnet 64.0% EB-ALFRED, 68.0% EB-Habitat; long-horizon subset drops 30+ points; removing vision degrades low-level tasks 40-70%. No dialogue or interruption evaluated.

### 3.6 CoNav (2024), CoNavBench (ICLR 2026), DeCoNav (2026)
- CoNav HTML (read): https://arxiv.org/html/2406.02425 ; CoNavBench: https://mlanthology.org/iclr/2026/wang2026iclr-conavbench/ ; DeCoNav: https://arxiv.org/html/2604.12486v1
- CoNav: Habitat 3.0; "20,293 training episodes and 4,962 evaluation episodes"; 49 scenes; "107 types of activities" / 51 objects; >25k humanoid trajectories; robot must predict the human's intended destination and arrive first. Intention-aware agent: "19.8% FASR, 23.2% RASR, 20.1% collision rate". "No dialogue" — explicitly deferred: "we will expand our work to introduce dialogue information".
- CoNavBench: "4048 single and collaborative episodes with graph-level annotations" (NavCraft generator over Habitat-Sim scene graphs); finetuned Qwen2.5-VL-3B "18.11% step level success". DeCoNav: event-triggered *robot-robot* dialogue; DeCoNavBench 1,213 tasks / 176 HM3D scenes; SR 0.28 → 0.39, BSR 0.13 → 0.22 (+69.2%), SPL 0.18 → 0.32. No human dialogue.

### 3.7 HA-VLN (2024) and HA-VLN 2.0 (2025) — human-aware VLN, Unitree Go2-EDU real-world validation
- HA-VLN HTML (read): https://arxiv.org/html/2406.19236 ; HA-VLN 2.0 HTML (read): https://arxiv.org/html/2503.14229
- HA-VLN: HAPS = "145 human activity descriptions converted into 435 detailed 3D human motion models" (SMPL); HA-R2R 21,567 instructions, avg length 29 → 69 words; unseen SR: VLN-CM 0.12 (TCR 0.99), VLN-DT 0.11 (TCR 0.37), oracle 0.89.
- HA-VLN 2.0: 16,844 instructions (avg 112 words vs 27 for R2R-CE); HAPS 2.0 486 motion sequences, 910 human models across 428 regions in 90 scans (multi-human groups, 111 outdoor humans); continuous-env unseen: BEVBert NE 5.51 m SR 0.21 CR 0.55; ETPNav SR 0.17 CR 0.58. Real robot: "Unitree Go2-EDU quadruped" with RGB-D + LiDAR in four indoor spaces with "2-4 free-moving volunteers". Public leaderboard. No dialogue.

### 3.8 IVLN (Krantz et al.; CVPR 2023)
- arXiv: https://arxiv.org/abs/2210.03087 — tours of up to 100 ordered R2R episodes, "about 400 tours each in 80 indoor scenes" (IR2R and IR2R-CE); "extending the implicit memory of high-performing transformer VLN agents is not sufficient"; map-building agents benefit from persistence. Relevant to Parcel's "global history" stream.

### 3.9 OpenEQA (CVPR 2024) and NIABench (2026)
- OpenEQA: https://ai.meta.com/blog/openeqa-embodied-question-answering-robotics-ar-glasses/ , https://open-eqa.github.io/ , https://github.com/facebookresearch/open-eqa (MIT). "over 1,600 non-templated" questions, ">180" environments, 7 categories, EM-EQA vs A-EQA, LLM-Match metric; human 85.9% vs GPT-4V 48.5% (gap 37.4 points); spatial questions ≈ "blind".
- Assistance Without Interruption / NIABench: https://arxiv.org/html/2605.01368 — "Non-intrusive Assistance": robot helps "without explicit human requests, no robot-induced interruption"; 2,000 training episodes, 7 test tasks, 4 rooms, 118 objects / 800 atomic actions; NiaRR: "29.4 human steps saved on average", "95.0% SuccessAcc". The inverse problem (robot must *not* interrupt the human).

---

## 4. Interruptions, amendments, corrections mid-task

### 4.1 InterruptBench — "When Users Change Their Mind" (2026)
- arXiv: https://arxiv.org/abs/2604.00892 ; HTML (read): https://arxiv.org/html/2604.00892
- Web agents (WebArena-Lite, 165 human-verified tasks, 5 domains); three interruption types: Addition, Revision, Retraction; interruptions injected "at 60% of baseline trajectory length"; six backbones (Claude Haiku/Sonnet/Opus 4.5, Qwen3-Coder-480B, DeepSeek-V3.1, Mistral-Large-3). Post-interruption success at k=30 actions (Addition): Opus ~55%, Sonnet ~44%, Haiku ~38%, DeepSeek ~30%, Qwen ~26%, Mistral ~23%; multi-turn (3 interruptions) Opus 41.82%. "token overhead dominates adaptation cost". Text-only, no embodiment — but the taxonomy and injection recipe transfer directly.

### 4.2 P^3 — Toward Versatile Embodied Agents (2025)
- HTML (read): https://arxiv.org/html/2508.07033
- Parallel perception / LLM planner / dispatchers; Task Memory: "When a higher-priority instruction arrives, the current job is snapshot with its targets and partial progress, then later reinstated at the same step." Real robot: RealMan dual-arm mobile base on Jetson AGX Orin. 11 competing tasks; simple competing tasks 92.86%; Task 11 (active interruption: knocked-over cup detected mid-route) 42.86% vs RoboOS baseline 35.71%; Qwen-VL-Max best active-perception score 56.15%.

### 4.3 YAY Robot — Yell At Your Robot (Shi et al., 2024)
- HTML (read): https://arxiv.org/html/2403.12910
- ALOHA bimanual; high-level policy (ViT + frozen CLIP) emits language skills; low-level ACT+FiLM executes; high-level re-queried "every 4 seconds as the average skill length"; a spoken correction overrides: "if user intervention occurs, the system executes πL(at|ot,luser)". Base full-task success 15-20%; corrections give +25-50% (bag packing), +30-45% (trail mix), +15-25% (plate cleaning); fine-tuning on corrections retains +20-45% / +15-20% / +15-25%. Bag-packing data: 1170 trajectories, 41,517 skill segments, 1054 unique commands.

### 4.4 ELLSA — End-to-end Listen, Look, Speak and Act (2025)
- HTML (read): https://arxiv.org/html/2510.16756
- Full-duplex streaming model with SA-MoE (Speech Expert: Mamba 32 blocks / 2048 + LLaMA-3.1-8B-Instruct; Action Expert: Emu3-Base + FAST action tokenizer; CosyVoice2-0.5B TTS). Spoken interruptive commands during task execution: "ELLSA must immediately stop the ongoing action" — 94.3% success. LIBERO 89.4% avg (SPATIAL 90.8 / OBJECT 95.8 / GOAL 86.4 / LONG 84.4). Speaking-while-acting: speech QA drops to 68.9% on Llama Questions while manipulation stays 93.3% on SPATIAL. Latency per 1-s time block: 854 ms speech-to-speech, 786 ms speech-to-action on an A100. Training: ASR 481k, QA 729k, 3,386 LIBERO + 1,693 "defective instruction" samples. Manipulation only — no navigation.

### 4.5 DuplexSLA (2026), DuplexOmni (2026), VideoFDB (2026)
- DuplexSLA HTML (read): https://arxiv.org/html/2605.20755 — three channels on a 160 ms chunk timeline (user audio features at 80 ms; assistant TA4 = 1 text anchor + 4 audio tokens at 40 ms; action channel ≤10 text tokens/chunk for planning, JSON tool calls, and response/interrupt/backchannel labels); 7B-scale backbone from Step-Audio 2 mini; ~550k h continued pretraining + ~50k h post-training (~36k h interrupt/backchannel/pause, ~14k h tool calling). DuplexSLA-Bench 2,100 cases: Interrupt 99.33% acc / 0.40 s; Backchannel 98.33% / 0.32 s; Pause 93.33% / 0.27 s; tool call 85.56% acc at 0.64 s vs ASR+LLM 91.33% at 2.77 s. "action barge-in": tool calls emitted while speech continues. No robot.
- DuplexOmni HTML (read): https://arxiv.org/html/2606.09186v1 — 480 ms slices; Thinker-Talker; control tokens (^ speaker offset, [CUT], [WAIT]); latency 0.506 s; 72.6% ToR on Full DuplexBench; ~3.02M raw conversations (70% Chinese); 128 H20 GPUs.
- VideoFDB HTML (read): https://arxiv.org/html/2605.30256 — 237 dyadic video-call clips, 11 nonverbal/verbal dynamics (verbal/nonverbal interruption, backchannel, turn-taking...); TOR-Alignment + latency + 0-5 rubric; closed vision-speech models 2.73-3.17 vs human 4.20; MiniCPM-o 4.5 3.40 with 73% TOR-Alignment and 720 ms latency. Not embodied.

### 4.6 Legged-robot speech systems that talk while walking
- NaVILA HTML (read): https://arxiv.org/html/2412.04453 — VLA emits mid-level language actions ("moving forward 75cm"); locomotion policy runs in real time; VLA "roughly 1 FPS" on RTX 4090; R2R-CE val-unseen SR 54.0% / SPL 49.0% / NE 5.22 m; RxR-CE SR 49.3%; real world 25 instructions, Go2 88% overall, 75% on complex; same VLA on Go2/H1/Booster T1; 2K YouTube touring videos → 20K trajectories. Text instruction only.
- From Woofs to Words HTML (read): https://arxiv.org/html/2603.12574 — Unitree Go2 guide dog; Vosk ASR → GPT-4 dialog (multi-turn clarification before navigation) → ASP planner → TTS; "scene verbalization" during navigation "triggered by major scene changes or a long silence in the dialogue" when "the robot's position crosses the boundary of a semantically labeled region"; motion was Wizard-of-Oz; 7 legally blind participants (one excluded); Likert: utility 4.83, communication ease 4.50, safety 3.83; simulation 94.8% accuracy on 77 tasks, 5.2% loss under 30% character perturbation; plan info saved ~47 s per task.
- Y-BotFrame HTML (read, thin): https://arxiv.org/html/2606.13049 — quadruped assistant, ASR/TTS + LLM planner, LiDAR/GNSS/IMU + A*; no interruption or latency numbers in the fetched text.
- MM-Conv HTML (read): https://arxiv.org/html/2605.21796 — 6.7 h egocentric VR dialogue in 5 AI2-THOR apartments, 4,211 referring expressions, ~250k words with word-level timecodes, SMPTE-synced speech/gaze/motion; pronominal references 49.3%; VLM pronominal grounding 4.7-9.2% without context, 56.7% with rewriting. Useful as a model of *situated spoken reference while moving*.

---

## 5. Cross-source summary table (what is spoken, what is concurrent, what is mid-task)

| Source | Modality | Dialog concurrent with motion? | Mid-task amendment / interruption evaluated? | Sim / real | Best number |
|---|---|---|---|---|---|
| CVDN/NDH 2019 | typed | no (stop-ask-go) | no | Matterport sim | 2.35 m goal progress test unseen (of 9.76 possible) |
| RobotSlang 2020 | typed | yes (human-human, live) | no | real tabletop robot, replay sim | NDH TD 3.38 m |
| Talk the Walk 2018 | typed | yes (tourist chats+moves) | no | 360° NYC | NL full task 50% vs human 76.74% |
| HANNA / VNLA 2019 | typed subgoals | agent-initiated asks | no | Matterport | SR unseen 8.10 → 47.45 / 6.36 → 34.50 |
| Just Ask 2020 | typed | agent-initiated asks | no | R2R | SR unseen 0.471 → 0.807 |
| WAY 2020 | typed | Observer moves while answering | no | Matterport | 32.7% vs human 70.4% |
| TEACh 2022 | typed | interleaved in raw sessions | no | AI2-THOR | EDH SR 13.49 unseen; TfD 0.48 |
| DialFRED 2022 | typed | agent asks between subgoals | no | AI2-THOR | SR 18.3 → 33.6 unseen |
| Alexa Arena 2023 | typed | robot asks clarification | no | Unity | 3k+ missions, 2 QA sets/instr |
| SIF 2024 | typed | human moves during task | intent change via motion | Habitat 3.0 | Reasoner 29% S_hum |
| DialNav 2025 | typed | agent decides when to ask | no | Matterport | SR 27.0 seen / 13.9 unseen |
| RAINbow 2026 | synthetic typed | — | no | Matterport | SR 14.52 → 29.05 unseen |
| QAsk-Nav / TANDEM 2026 | typed | agent asks | no | HM3D | SR 0.451; WSR 21.4 |
| InterruptBench 2026 | typed | n/a | yes (add/revise/retract) | web | ~55% post-interrupt best |
| P^3 2025 | speech→text | yes | yes (snapshot/resume) | real mobile manipulator | 42.86% on interrupted task |
| YAY Robot 2024 | spoken corrections | yes (4 s window) | yes (corrections) | real ALOHA | +25-50% SR |
| ELLSA 2025 | full-duplex speech | yes | yes (spoken interrupt of action) | LIBERO sim | 94.3% interrupt success |
| DuplexSLA 2026 | full-duplex audio | speech ∥ tool calls | yes (interrupt 0.40 s) | audio | 99.33% |
| Woofs to Words 2026 | speech | yes (scene verbalization) | clarification before nav only | real Go2 (WoZ motion) | utility 4.83/5 |
| HA-VLN 2.0 2025 | text | no | no | sim + real Go2-EDU | SR 0.21 unseen |
| NaVILA 2024 | text | no | no | sim + real Go2 | 88% real, ~1 FPS |

---

## 6. What this means for Parcel's Model A / Model B

**The gap is real and narrow enough to own.** Every dialogue-navigation dataset is typed and turn-based; every full-duplex speech-plus-action model is manipulation or audio-only; every interruption benchmark is web/text. A Go2 that takes a spoken "actually, check the sofa first" while walking, keeps walking, and narrates, has no benchmark. Parcel should define one rather than look for one.

### Model A (fully duplex sensor→movement+representation)
1. **Chunk clock.** Published duplex systems run on 160 ms (DuplexSLA), 480 ms (DuplexOmni) or 1 s (ELLSA) blocks; ELLSA's speech-to-action latency is 786 ms per 1-s block on an A100. Parcel's existing 10 Hz frame clock (100 ms) is finer than any of them; treat the 100 ms tick as the action rate and aggregate ~2-5 ticks per speech chunk. Rate-limit the "representation" channel the way DuplexSLA rate-limits its action channel (≤10 tokens/chunk, overflow spills to the next chunk) so narration context never blocks motion.
2. **Interrupt semantics must be native, not bolted on.** DuplexSLA gets 99.33% interrupt accuracy at 0.40 s by emitting interrupt/backchannel/response labels on the same token stream as speech; ELLSA gets 94.3% on spoken interruptive commands by training on "defective instruction" samples (1,693 of them). Model A's act-token codec needs explicit HOLD / RESUME / ABORT tokens and training data that contains interruptions.
3. **Persistent memory across episodes matters.** IVLN shows implicit transformer memory is "not sufficient" and map-persistent agents win; Parcel's "global history" stream should be a spatial map + goal queue, not a token window.
4. **Human-aware motion is a hard baseline.** HA-VLN 2.0 unseen SR is 0.21 with CR 0.55 for the strongest agents even before dialogue; CoNav's intention-aware agent has 20.1% collision rate. Budget for this when setting Model A's acceptance bar.
5. **Sim-to-real path exists on the exact platform.** HA-VLN 2.0 validated on a Go2-EDU with RGB-D + LiDAR with 2-4 moving people; NaVILA runs a VLA at ~1 FPS on a 4090 with 88% real-world success on 25 instructions. Reuse their protocols (fixed instruction sets, free-moving volunteers, collision counts).

### Model B (voice command → steerable injection; Model A output → narration)
6. **Injection taxonomy = InterruptBench's three types mapped onto the owner's three verbs.** Addition → queue; Revision → revise; Retraction → keep/cancel. Inject at a controlled fraction of trajectory length (InterruptBench uses 60%) when generating training/eval episodes. Add P^3's snapshot-and-reinstate semantics for "queue" so a suspended global plan resumes "at the same step".
7. **Agent-initiated clarification is worth 2-6x in success and should be part of Model B, not an afterthought.** DialFRED 18.3 → 33.6 unseen SR with 0.71 questions/episode; HANNA 8.10 → 47.45 with 5.8 requests; VNLA 6.36 → 34.50; Just Ask 0.471 → 0.807 with ~2 questions. Use cost-aware asking (TANDEM per-type penalties 0.10-0.24; DialFRED's r_q / r_invalid) so the dog does not nag; DialFRED's Table III shows asking every step buys +4 SR at 30x the questions.
8. **Narration triggers.** "Woofs to Words" verbalizes scene on region-boundary crossings or long silence; TEACh-DA gives a dialog-act inventory (39.5k annotated utterances) to type the narration ("Confirm", "Acknowledge", "RequestForInstruction"). Model B's output to the hosted voice should be tagged with a dialog act + trigger reason, which the hosted model can render ("Sure, I'll check the sofa" = Acknowledge+Plan; "Done! Should I go back?" = Confirm+RequestForInstruction).
9. **Global plan as a historical queue is what DialNav/NDH already assume implicitly** (dialog history = plan history). Log DTC (dialog turn count) and NSC (navigation step count) per DialNav as first-class metrics.

### Data and evaluation
10. **Synthesize dialogue from existing trajectories.** RAINbow turned R2R/RxR/CVDN into 238K dialog episodes at $0.0016 each (LLaVA captions + GPT-4o-mini reformatting) and doubled unseen SR (14.52 → 29.05). Parcel's headless-city / MuJoCo trajectories can be converted the same way, with interruptions inserted at 40-70% of path length and spoken via TTS with the reSpeaker recorded at walking-noise SNR.
11. **Benchmark design ("Interrupt-Nav").** Metrics: post-interruption SR at k steps (InterruptBench), goal progress in metres (NDH), SPL, collision rate (HA-VLN), recovery steps and tokens (InterruptBench found token overhead dominates), interrupt-to-hold latency (DuplexSLA 0.40 s is the bar), narration dialog-act accuracy, plus the existing Parcel conversation-quality scorer. Keep separate splits for addition / revision / retraction and for owner-initiated vs agent-initiated turns.
12. **Do not expect frontier LLMs to handle this for free.** Even Claude Opus 4.5 reaches only ~55% post-interruption success on text web tasks; GPT-4o gets 57.7% on EmbodiedBench navigation without any dialogue; P^3's interrupted real-robot task is 42.86%.

---

## 7. Not read / thin sources (flagged, not cited in findings)
- SPRING (AAAI 2023, situated conversation agent with layout-graph QA pretraining) — search snippet only; not a navigation benchmark.
- Alexa Arena full paper (PDF > 10 MB) — only abstract + README numbers used.
- OpenEQA CVPR PDF (403) — numbers taken from Meta's blog and the project page.
- Y-BotFrame — HTML fetch returned only the system description; no numbers.
- Learning to Ask / AwN (EMNLP 2025) — tool-use clarification, not navigation; not fetched.

