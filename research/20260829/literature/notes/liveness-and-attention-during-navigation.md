# Liveness and attention during navigation — literature notes

Date: 2026-08-29. Scope: how a navigating robot is made to look alive and attentive while it moves (micro-motions, sound-driven head turns, gaze during locomotion), how those behaviours are generated or learned, and what user studies say about liveliness vs task performance. Every source below was fetched and read in this session (arXiv HTML/PDF, publisher PDF, or vendor doc). Sources that could not be fetched are listed at the end as *not cited*.

Notation: **[L]** = load-bearing for the Parcel design; numbers are quoted from the source.

---

## 1. Attention / saliency engines that drive gaze

### 1.1 Disney — "Realistic and Interactive Robot Gaze" (Pan, Choi, Kennedy, McIntosh, Campos Zamora, Niemeyer, Kim, Wieland; IROS 2020) **[L]**
- URL: https://la.disneyresearch.com/wp-content/uploads/root.pdf (PDF read pp.1–7); publication page https://la.disneyresearch.com/publication/realistic-and-interactive-robot-gaze/
- Platform: humanoid Audio-Animatronics bust; the paper frames gaze "through the lens of character animation where the fidelity and believability of motion is paramount".
- Architecture (three engines): **Attention engine** builds a *curiosity score* per person from movement and distance features, with *habituation* so a persistent stimulus loses priority; a *Guestbase* stores people already interacted with so the character does not keep answering one guest and ignoring others. **Behaviour selection engine** = state machine with behaviours **Read**, **Glance**, **Engage**, **Acknowledge**. **Motor layer** = subsumption-style layered "shows": an always-on base show (breathing, blinking, saccades — the secondary-action layer) that higher layers override.
- Numbers (from the PDF): saccades are generated at **20 Hz** with dwell **0.1–0.5 s**, jumping between a guest's eyes and nose; different actuator groups run at different motion bandwidths (eyes fastest, eyelids intermediate, neck/head slowest) and *eyes lead the head*. Implementation lessons stated in the paper: "Saccades increase realism", "Subsumption can easily create complexity", "Motion bandwidth" must be tuned per actuator.
- Evaluation: qualitative (show-floor); no controlled user study numbers.
- Why it matters: the cleanest published "alive base layer + attention + behaviour selection" stack; it is the reference pattern for Parcel's liveness layer.

### 1.2 Ruesch et al. — "Multimodal Saliency-Based Bottom-Up Attention: A Framework for the Humanoid Robot iCub" (ICRA 2008) **[L]**
- URL: https://www.robotcub.org/misc/papers/08_Ruesch_Lopes_Hornstein_Victor_Pfeifer.pdf (PDF read pp.1–6)
- Mechanism: visual saliency (intensity, colour, Gabor orientation at σ∈{2,4,8} × 4 directions, Reichardt motion) and **acoustic saliency** (ITD azimuth + pinna-notch elevation, projected as a Gaussian blob with σ≈25°) are fused by **max** into a head-centred **ego-sphere** (spherical short-term memory). Attention selection = argmax of saliency × inhibition map; **habituation map** H(t)=H(t−1)+d_h(G_h−H(t−1)); when H > t_h an **inhibition-of-return** Gaussian is subtracted and decays with d_a. Result: "emergent exploratory behaviour" — the robot scans salient points in decreasing order, then revisits.
- Numbers (Table I): ego-sphere **320×240** (1.125° latitude, 0.75° longitude per cell); camera 128×128; **d_mem = 0.95** (memory decay), **d_a = 0.03** (inhibition decay), **d_h = 0.2** (habituation gain), **t_h = 0.85** (inhibition trigger), **σ_ior = 6°** (12° in the multimodal experiment). Ego-sphere updated **5–10 times per second**; motor loop **> 20 Hz**; 6-DOF head (3 neck + eye pan/tilt).
- Experiments: three salient marks are visited in a triangular gaze path, "all points are visited the same number of times"; talking to the robot injects auditory saliency and shifts gaze.
- Why it matters: concrete, tuned constants for a habituation/IOR attention loop at ~10 Hz — the same rate as Parcel's duplex frame clock.

### 1.3 Rea, Metta, Bartolozzi — "Event-driven visual attention for the humanoid robot iCub" (Frontiers in Neuroscience 2013)
- URL: https://www.frontiersin.org/journals/neuroscience/articles/10.3389/fnins.2013.00234/full
- Saliency from event-camera contrast, orientation (0°,45°,90°,−45°) and flicker maps; winner-take-all; no IOR (shifts driven by noise).
- Numbers: EVA latency **23 µs** (15 µs sensor + 8 µs algorithm) vs frame-based iNVT **≈56 ms** (33 ms acquisition + 23 ms processing); attentional shifts **158.2/s** vs **1.89/s**; CPU per shift **0.2 %** vs **6.79 %**; event rate ≈ **7 kAE/s** vs 530 Mbit/s for a frame camera.
- Why it matters: shows that "reacting to unexpected dynamic events" is a latency problem; a 10 Hz frame clock is fine for deliberate gaze but reflexive orienting wants a fast side path.

### 1.4 Ramenahalli — "A proto-object based audiovisual saliency map" (arXiv 2003.06779, 2020)
- URL: https://arxiv.org/pdf/2003.06779 (PDF read pp.1–4)
- Bottom-up AVSM: visual proto-objects (colour, intensity, orientation, motion) plus audio proto-objects (sound location, intensity) from a 360° audio-visual camera; the linear combination "captures a higher number of valid salient events compared to unisensory saliency maps" and agrees with human judgement. No robot deployment; minor.

### 1.5 SoftBank/Aldebaran NAOqi — ALBasicAwareness (Pepper/NAO) **[L]**
- URL: https://fileadmin.cs.lth.se/robot/nao/doc/naoqi/peopleperception/albasicawareness.html
- Stimulus types: **Sound** (ALSoundLocalization), **Movement**, **People**, **Touch**. Reaction: "it looks at the origin of the stimulus and checks if there is a human there"; if yes, track; if not, return to prior activity/position. Engagement modes: **Unengaged** (can be distracted by any stimulus), **FullyEngaged** ("stops listening to stimuli"), **SemiEngaged** ("if it gets a stimulus, it will look in its direction, but it will always go back to the person it is engaged with"). Tracking modes: **Head**, **BodyRotation**, **WholeBody**, **MoveContextually** ("uses the head and autonomously performs small moves such as approaching the tracked person"). Look-at speed parameters LookStimulusSpeed / LookBackSpeed are exposed (0–1 floats, per the NAOqi API page in search results; default values not shown on the fetched page).
- Why it matters: the shipped, product-grade policy for "glance at a sound, verify, return" — the exact primitive Parcel needs while navigating.

---

## 2. Sound-source localisation → orienting behaviour

### 2.1 NAOqi ALSoundLocalization (NAO/Pepper) **[L]**
- URL: http://www.bx.psu.edu/~thanh/naoqi/naoqi/audio/alsoundlocalization.html
- NAO: 4 microphones, TDOA; output azimuth (rad), elevation (rad), confidence, plus head frame; "maximum theoretical accuracy is about **10 degrees**"; CPU "**3–5 %** … up to **10 %** for a few milliseconds when the location of a sound is being computed". Pepper: ITD-based, average accuracy **10°**, theoretical **≈7°**. Limits: single source only; cannot distinguish human sounds from other loud noises; needs SNR "generally good at **3 dB+**"; saturation "successfully tested at **80 dB / 2 m**"; unreliable for a "person behind the robot (more than **120°** from the front)". Typical use: the Choregraphe *Sound Tracker* box turns the head toward the sound.

### 2.2 ODAS — Open embeddeD Audition System (Grondin et al., Frontiers in Robotics and AI 2022) **[L]**
- URL: https://pmc.ncbi.nlm.nih.gov/articles/PMC9131248/
- Typical robot arrays: "small circular microphone arrays, where the number of microphones varies between **4 and 8**"; also 16-mic planar/cubic arrays (Azimut-3, SecurBot). Localisation SRP-PHAT with hierarchical search (GCC-PHAT interpolation "since microphones are only a few centimeters apart"), "up to **four** potential DOAs" per frame; tracking with Kalman filters; separation by delay-and-sum / GSS.
- Compute on Raspberry Pi 3 (single core): localisation for an 8-mic array **38 % → 14 %**; tracking one source **24 % → 0.8 %**; four sources **98 % → 7 %**. Deployed on Azimut-3, SecurBot, Beam, T-Top and in Open-Tera telepresence. Open source on GitHub. No degree-accuracy table in the paper.

### 2.3 Liu, Du, Sehn, Collier, Grondin — "Sound Source Localization for Human-Robot Interaction in Outdoor Environments" (arXiv 2507.21431, 2025)
- URL: https://arxiv.org/html/2507.21431v1
- Argo J8 UGV with a **16-channel** circular array (51.6 cm radius); operator wears an asynchronous close-talk mic; coarse alignment + time-domain AEC + IRM mask + MVDR + SRP-PHAT. Results: "average angle error of **4 degrees** and an accuracy within 5 degrees of **95 %**" at **1 dB SNR**; static outdoor **0.95°** at 3 m; **98.75 %** within 5° at 10 m; ~**2 s** per mask computation on a 16-core workstation. HRI use: "follow me" — the robot decides "where to turn to begin following the operator".

### 2.4 Jalayer, Jalayer, Baniasadi — "A Review on Sound Source Localization in Robotics: Focusing on Deep Learning Methods" (Applied Sciences 15(17):9354, 2025; CC BY 4.0)
- URL: https://arxiv.org/html/2507.01143
- Array sizes on robots: binaural **2**; linear **3–8**; circular **8–32**; spherical **12–16**; dense up to **64**. "A large number of microphones in SSL leads to high accuracy in localization" at the cost of computing, cost and latency. Ego-noise of a moving robot (robot vacuum) "significantly degrades SSL performance"; CNN methods "significantly outperform traditional spatial spectrum-based approaches on real robot data". Platforms: Pepper, NAO, iCub, quadrotors.

### 2.5 Audio-goal navigation (context only)
- SoundSpaces (Chen et al., ECCV 2020) https://arxiv.org/abs/1912.11474 — audio renderings for Matterport3D and Replica; "audio greatly benefits embodied visual navigation".
- AV-WaN (Chen et al., ICLR 2021) https://arxiv.org/abs/2008.09622 — learned waypoints + acoustic memory; "improves the state of the art by a substantial margin" (numbers not on the abstract page).

---

## 3. Idle / secondary motion and animation principles

### 3.1 Schulz, Torresen, Herstad — "Animation Techniques in HRI User Studies: A Systematic Literature Review" (ACM THRI 8(2), 2019)
- URL: https://arxiv.org/pdf/1812.06784 (PDF read pp.1–10); abstract page https://arxiv.org/abs/1812.06784
- **27** articles reviewed (≈1,180 participants in total across them). *Secondary action* (idle/breathing/blink-type motion layered on the main action) was the most frequently used principle (8 studies), followed by anticipation, slow-in/slow-out, follow-through, timing, arcs. Conclusion: "animation techniques improves individual's interaction with robots, improving individual's perception of qualities of a robot" and help convey intent and emotional state; gaps: few long-term studies, few non-humanoid platforms.

### 3.2 Casso, Li, Nazir, Delevoye-Turrell — "The Effect of Robot Posture and Idle Motion on Spontaneous Emotional Contagion" (SCRITA @ RO-MAN 2022) **[L for the "slow idle" rule]**
- URL: https://arxiv.org/pdf/2209.00983 (PDF read); abstract page https://arxiv.org/abs/2209.00983
- Robot Buddy (Blue Fog Robotics) tells three sad stories while oscillating its head up/down at **low / medium / high** idle frequency; **N = 15**; 3D motion capture (Qualisys) of the listener's posture + Godspeed.
- Results: "greater inclinations of the shoulder/torso towards the ground in low-frequency trials and more rigid postures in high-frequency trials"; spontaneous movement greater at slow frequency. Godspeed ANOVA: main effect of idle frequency on **Anthropomorphism (p < 0.001)** and **Perceived Intelligence (p < 0.001)** — Buddy "perceived to be more anthropomorphic and more intelligent when it moved slowly"; **no effect** on Likeability or Animacy.

### 3.3 Cuijpers & Knops — "Motions of Robots Matter! The Social Effects of Idle and Meaningful Motions" (ICSR 2015)
- URL: https://research.tue.nl/en/publications/motions-of-robots-matter-the-social-effects-of-idle-and-meaningfu (abstract only)
- "Humans always move, even when 'doing' nothing, but robots typically remain immobile." Joint task with low social verification (idle motions) vs high (meaningful motions): "Social responses increase with the level of social verification in line with the threshold model of social influence." N and effect sizes not on the fetched page.

### 3.4 Castro-González, Admoni, Scassellati — "Effects of form and motion on judgments of social robots' animacy, likability, trustworthiness and unpleasantness" (IJHCS 2016) **[L]**
- URL: https://scazlab.yale.edu/sites/default/files/files/CastroGonzalez_IJHCS_16.pdf (PDF read pp.1–12)
- Baxter plays Tic-Tac-Toe (10 rounds) with participants; 2×2 (naturalistic/smooth vs mechanical/jerky motion × one-arm vs full-body humanlike form) + control; 56 recruited, 13 excluded, ≈42 analysed.
- Findings: "Naturalistic motion was judged to be more animate than mechanical motion, but only when the robot resembled a human form"; "Naturalistic motion improved likeability regardless of the robot's appearance"; "a robot with a human form was rated as more disturbing when it moved naturalistically". Motion quality mattered as much as or more than static form.

### 3.5 Apple — ELEGNT: Expressive and Functional Movement Design for Non-anthropomorphic Robot (Hu, Huang, Sivapurapu, Zhang; arXiv 2501.12493, DIS 2025) **[L]**
- URL: https://arxiv.org/html/2501.12493v1; abstract https://arxiv.org/abs/2501.12493
- Lamp robot on a 6-DOF WidowX arm (LED, projector, cameras, voice). Movement objective: **max Σ F(τ) + γ·E(τ)** — functional utility (reach goal states efficiently) plus expressive utility (intention, attention, attitude, emotion) weighted by γ. Primitives: kinesics (nod, shake, lower head, speed/pauses/jerkiness) and proxemics (gaze direction, proximity, approach/avoid).
- Study: **N = 21** (ages 26–51), within-subject **F** (γ = 0) vs **E** (γ > 0), six tasks (Photograph Light, Project Assistance, Failure Indication, Remind Water, Social Conversation, Play Music), six 0–100 scales.
- Results: E **M = 56.16** vs F **M = 28.77** (SD 27.15), **t = 19.85, p < 0.0001**; per-metric t: character 10.58, human-likeness 9.32, engagement 8.80, connection 8.50, willingness 7.37, perceived intelligence 5.22 (all p < 0.001). **Task moderation**: E wins on social tasks, but "for function-oriented tasks (photograph light, project assistance, failure indication), the two robots show no significant differences". Older participants less receptive (p < 0.001); non-roboticists rated higher (p = 0.006); gender n.s. (p = 0.2).
- Design statement: "Expression-driven movements need to complement function-driven movements by adjusting both the amount and timing of expressions to enrich—rather than conflict with—the original motions."

---

## 4. Gaze while locomoting — human data and robot use

### 4.1 Schreiter, Rudenko, Magnusson, Lilienthal — "Human Gaze and Head Rotation during Navigation, Exploration and Object Manipulation in Shared Environments with Robots" (RO-MAN 2024) **[L]**
- URL: https://arxiv.org/pdf/2406.06300 (PDF read pp.1–6); abstract https://arxiv.org/abs/2406.06300
- THÖR-MAGNI: 40 participants, **468 min** of eye tracking (Tobii/Pupil glasses) from 16 of them, walking with a mobile robot (DARKO) present.
- Fixation stats while walking between goals: durations ≈ **310–400 ms** (e.g., 354±366 ms carrier-box, 345±466 ms visitor-alone), rates **2.3–2.8 Hz**; 80 % of fixations fall inside **28 %** of the image area (90 % in 39 %).
- **Eye–head coordination**: for shifts < 10° the head contributes ≈ **50 %**; contribution falls to a minimum of ≈ **25 %** at 40–50°; rises above **90 %** for shifts > 70° (vs 35° eye-only threshold in seated viewing). Head–eye alignment correlates negatively with walking speed (ρ = −0.04, p < 0.01). Walking speeds 0.65–1.16 m/s. "Human attention towards a mobile robot in a shared environment remains constant, regardless of the participant's activity."

### 4.2 Holman, Anwar, Singh, Tec, Hart, Stone — "Watch Where You're Going! Gaze and Head Orientation as Predictors for Social Robot Navigation" (ICRA 2021)
- URL: https://www.cs.utexas.edu/~pstone/Papers/bib2html-links/ICRA21-hart.pdf (PDF read pp.1–7)
- Eye-tracked participants walking in a hallway with obstacles; gaze precedes head orientation, and both precede the trajectory change; direction of travel is predictable earlier from gaze than from head (≈95 % vs ≈89 % accuracy at one-third of the path in the reported figures). Motivation: a robot's head/gaze can likewise be used to *signal* its intended path.

### 4.3 Jakobowsky, Abrams, Rosenthal-von der Pütten — "Gaze-Cues of Humans and Robots on Pedestrian Ways" (Int J Social Robotics 2023) **[L]**
- URL: https://d-nb.info/1316676846/34 (PDF read pp.1–8)
- Two online experiments: Study 1 **n = 92** recruited / 79 analysed / 645 trials; counterparts human, Pepper, or a six-wheel delivery robot with tablet eyes, approaching at ≈ **1.3 km/h** in ~5 s videos; eyes straight, left or right. Study 2 **n = 176** in left-hand-driving countries.
- Results: gaze-left made participants skirt left **59 %** vs **45 %** for straight eyes (b = −0.94, p < 0.001); right cue n.s. in Study 1 (b = 0.10), significant in Study 2. "Skirting behavior did not differ regarding the type of counterpart" (human vs Pepper vs delivery robot). RoSAS discomfort: Pepper 3.57 vs delivery robot 2.66 (p = 0.04). Conclusion: "Equipping robots with eyes can help to indicate moving direction by gaze cues".

### 4.4 Yu et al. — "Learning from Human Gaze: Human-like Robot Social Navigation in Dense Crowds" (AAAI-26)
- URL: https://ojs.aaai.org/index.php/AAAI/article/view/38941
- GazeNav egocentric dataset (video + gaze + trajectory in crowds); "the gaze of pedestrians is closely related to the semantic presence and movement of other individuals". Gaze2Nav: **87.6 %** salient-pedestrian prediction accuracy; **15.4 %** lower trajectory error than SOTA baselines.

### 4.5 Cohen, Shimizu, Song, Bharath, Larson, Maes — "Do Robots Need Body Language? Comparing Communication Modalities for Legible Motion Intent in Human-Shared Spaces" (arXiv 2604.03451, 2026) **[L]**
- URL: https://arxiv.org/pdf/2604.03451 (PDF read pp.1–8); abstract https://arxiv.org/abs/2604.03451
- Online video study with Boston Dynamics Spot (≈210 participants), four navigation scenarios; modalities: expressive body language, lights, audio, text, combinations. Intent-prediction accuracy rose from ≈ **14 %** (no signal) to ≈ **44 %** with body language alone, ≈ **58 %** lights, ≈ **82 %** audio, ≈ **88 %** text; coordinated multimodal signals best, conflicting cues worst. Body language raised perceived safety/trust but is a weak *sole* channel for intent.

---

## 5. Learned gaze / active viewpoint during locomotion and tasks

### 5.1 Li et al. — TAGA: Terrain-aware Active Gaze Learning for Generalizable Agile Humanoid Locomotion (arXiv 2606.05880, 2026) **[L]**
- URL: https://arxiv.org/html/2606.05880; abstract https://arxiv.org/abs/2606.05880
- Unitree G1, onboard NVIDIA Jetson Orin; a learned active-gaze module selects the locomotion-relevant terrain region (differentiable grid sampling), fused by cross-attention with proprioception, MoE action decoder. "Gaze behaviors can naturally emerge through reinforcement learning alone, without requiring additional supervision."
- Numbers: stepping stones **97.90 %** vs **52.30 %** vision-only; gap crossing **98.30 %** with learned gaze vs **57.10 %** with inactive gaze; **120 cm** gap ("surpassing the best reported result by 50 %"); beam **98.5 %**; stairs **100 %**.

### 5.2 EyeRobot — "Eye, Robot: Learning Hand-Eye Coordination with Reinforcement Learning" (CoRL 2025 submission, Berkeley AUTOLab)
- URL: https://autolab.berkeley.edu/assets/publications/media/2025-04-CoRL-Justin-EyeRobot-Submitted.pdf (PDF read pp.1–9)
- 2-DOF gimbal "eyeball" with fisheye global-shutter camera on a UR5e; **BC-RL loop**: gaze policy (RL) is rewarded by the BC arm policy's action-prediction accuracy; trained in *EyeGym* by sampling viewpoints from 360° video (5.7K/30 fps Insta360). Eye action = categorical over **8 azimuth-elevation directions + stay**; Foveal Robot Transformer with multi-scale crops.
- Numbers: scene search exact-match **66.5 %** (DINO+distance reward) vs **28.1 %** random walk; object search **87 %** success, **1.8 s** average search time; Eraser pick&place **60 %** vs exo-camera **0 %**; E-Stop error **4.0 cm** vs 7.8 cm exo; Towel 72.2 % vs 62.1 % without active-visual pretraining. Emergent behaviours: target switching, search "oscillate back and forth in a sweeping motion", tracking, attending to predictive cues (a human placing an object). Limitation: no parallax; future work "mount the eyeball on a mobile robot".

### 5.3 Chen et al. — "Learning Active Camera for Multi-Object Navigation" (NeurIPS 2022)
- URLs: https://arxiv.org/abs/2210.07505 ; https://research.ibm.com/publications/learning-active-camera-for-multi-object-navigation
- "Cast moving camera to a Markov Decision Process and reformulate the active camera problem as a reinforcement learning problem"; exploration reward + rule-based human guidance; camera policy conditions on the navigation action; "consistently improves the performance of multi-object navigation over four baselines on two datasets".

---

## 6. Expressive quadruped locomotion while navigating

### 6.1 Margolis & Agrawal — "Walk These Ways: Tuning Robot Control for Generalization with Multiplicity of Behavior" (CoRL 2022) **[L]**
- URL: https://arxiv.org/pdf/2212.03238 (PDF read pp.1–8); project https://gmargo11.github.io/walk-these-ways/
- Unitree **Go1 Edu**, Jetson TX2 NX, **50 Hz** control (training and deployment), Isaac Gym + PPO, ~**20 ms** modelled action latency, PD kp = 20 / kd = 0.5, MLP [512, 256, 128].
- Interface: 3-dim command **c = [v_x, v_y, ω_z]** plus an **8-dim behaviour vector b = [θ1, θ2, θ3 (foot phase offsets), f (stepping Hz), h_z (body height), φ (pitch), s_y (stance width), h_z^f (footswing height)]**. Phase offsets encode pronking (0,0,0), trotting (0.5,0,0), bounding (0,0.5,0), pacing (0,0,0.5) and interpolations (galloping 0.25,0,0); f = 3 Hz ⇒ three contacts per second. Gait transitions demonstrated at 2 Hz ↔ 4 Hz; choreographed dance at 90 bpm; 60 cm leap; crawl under a 22 cm bar (13 cm body).
- Cost/benefit numbers: mechanical power at 3 m/s — trotting **98±9 W**, pronking 112, pacing 99, bounding **127±35 W**, gait-free baseline 102; platform-terrain survival trotting **0.88** vs gait-free **0.83**. Trade-off stated: "the benefits of adding MoB can come at a cost to in-distribution task performance, specifically limiting the robot's flat-ground sprinting performance."
- Why it matters: a single policy with a small, human-readable style vector is exactly the action interface a Model A/Model B split needs on the Go2.

### 6.2 Hauser, Chan, Bhalani, Kuchimanchi, Siddiqui, Hart — "Influencing Incidental Human-Robot Encounters: Expressive movement improves pedestrians' impressions of a quadruped service robot" (arXiv 2311.04454, HICSS 2024) **[L]**
- URL: https://arxiv.org/html/2311.04454; abstract https://arxiv.org/abs/2311.04454
- Body language = "expressive character of robotic locomotion not required for the performance of an activity". Boston Dynamics Spot, in the wild (busy UT Austin intersection, March 2022), between-subjects **N = 222** (112 body-language, 110 control). Five hand-coded canine behaviours: tail wag (roll/yaw oscillation ±π/16, ±π/8 rad), play bow (tilt 3π/14), sit (π/7), circling (1.5 rad/s with 2 m/s forward), spin (1 rad/s).
- Modified Godspeed, one-way ANOVA: cynomorphism **F(1,220)=4.10, p=0.04**; animacy **F=6.18, p=0.01**; likeability F=3.21, p=0.07; perceived intelligence F=0.18, p=0.67. "Participants rated the robot more favorably on every single scale."

### 6.3 Clark, Hejna, Sadigh — "Efficiently Generating Expressive Quadruped Behaviors via Language-Guided Preference Learning" (arXiv 2502.03717, 2025)
- URL: https://arxiv.org/html/2502.03717; abstract https://arxiv.org/abs/2502.03717
- Pupper v3 (3 joints/leg), Isaac Gym + PPO. Behaviour space **ω ∈ R^5** = desired velocity, desired pitch, and trot/pace/bound primitives. LGPL: GPT-4 proposes candidate reward/behaviour parameterisations, humans rank → preference learning. "As few as **four** queries"; **53 %** lower L2 loss than preference learning, **62 %** lower than LLM-only; offline study (11 people) preferred LGPL **75.83±5.14 %** of the time; active study (5 people) **76.67±10.59 %**.

### 6.4 Liu et al. — "Unleashing Infinite Motion: Scaling Expressive Quadrupedal Motion via Generative Video Priors" (Uni-Mo; arXiv 2606.28237, 2026)
- URL: https://arxiv.org/html/2606.28237; abstract https://arxiv.org/abs/2606.28237
- Pipeline: LLM prompts → fine-tuned video diffusion (Wan2.2) with an Identity-Consistency loss (FID 66.65→26.98) → 2D keypoints + URDF-anchored 3D reconstruction → PPO tracking policies on **Unitree Go2** (19-dim state). Dataset **Quad-Imaginarium: 7,488 motions, 18.5 h**, no animal mocap. Retention 68.1 % (97.0 % semantic gate × 70.2 % geometric); sim completion **97.6 %**, body-link error 40.6 mm; real Go2 **96.7 %** success over **392** motions × 5 trials (flat indoor floor). Human ratings: identity 7.30/10, naturalness 6.24/10, text-action alignment 4.75/10.

### 6.5 Disney — "Design and Control of a Bipedal Robotic Character" (Grandia et al., RSS 2024; arXiv 2501.05204) **[L]**
- URL: https://arxiv.org/html/2501.05204; publication page https://la.disneyresearch.com/publication/design-and-control-of-a-bipedal-robotic-character/
- Robot: 5 DoF/leg + **4-DoF neck/head**, **15.4 kg**, **0.66 m**; actuators 34 N·m / 20 rad/s (hip, knee), 24 N·m / 30 rad/s.
- **Animation engine** composes and blends three source types — *perpetual* (balance/idle), *periodic* (walk cycles), *episodic* (triggered clips) — via a background loop, triggered animations and joystick modulation; "the left joystick modifies the body posture (torso yaw and pitch), while counter-rotating the head to maintain a fixed gaze". The RL policy tracks the composed command (joint positions/velocities + foot-contact rewards) under randomised disturbances.
- Numbers: Isaac Gym, **100,000 iterations ≈ 22 days on an RTX 4090**; policy **50 Hz**, actuator bus 600 Hz; walking up to 0.7 m/s / 0.4 m/s lateral / 1.8 rad/s; standing tracking error 0.035 rad; "on the order of **10 h** of robot runtime without a single fall" in public shows.
- Why it matters: the reference for *layering animator-authored liveness on top of an RL locomotion tracker*, including a look-at/gaze-hold rule while the body moves.

---

## 7. What this means for Parcel's Model A / Model B

**Owner's ask, restated in this topic's terms:** Model A is the duplex, trainable body — it must make the Go2 look alive and attentive *while* executing navigation, and emit a representation Model B can narrate. Model B injects owner commands into Model A's plan queue and turns Model A's stream into narration.

1. **Liveness is a layered controller, not a policy output.** Disney (gaze bust and BD-X), Pepper's ALBasicAwareness and the iCat lineage all converge on: an always-on *alive* layer (breathing/sway, blink/LED, micro-saccades) → an *attention* layer (glance / engage / acknowledge with habituation and IOR) → the *task* layer (navigation, gestures). The RL locomotion policy tracks the composed command (BD-X: 50 Hz policy; WTW: 50 Hz on Go1). For Parcel: make Model A's *local-movement* output a **behaviour vector**, not joint targets — WTW's 8-dim b (phase offsets, step frequency, body height, pitch, stance width, footswing) plus a **gaze/heading token** — and keep a fixed liveness layer beneath it that Model A only modulates (amplitude, tempo).
2. **Attention constants to start from (10 Hz is the right tick).** Ruesch's ego-sphere runs at 5–10 Hz with d_mem 0.95, d_h 0.2, t_h 0.85, d_a 0.03, σ_ior 6°; Disney's curiosity score uses motion + distance with habituation and a guestbase. Parcel's 10 Hz duplex frame clock can carry a saliency/ego-sphere state; the act-token codec should include a discrete **look-at** token (EyeRobot uses 8 azimuth-elevation directions + stay). Reflexive orienting to sudden events wants a faster side path (Rea et al.: frame-based attention ≈ 56 ms; event-based 23 µs).
3. **Sound → glance → verify → return.** Small arrays (4 mics, NAO/Pepper) give ≈7–10° azimuth; 16-mic arrays ≈1–4°; ODAS tracks up to four sources on Raspberry-Pi-class CPU. Pepper's *SemiEngaged* rule ("look in its direction, but … always go back") is the right default while navigating; the glance should be a body-yaw/head token, and the navigation goal is only *revised* after visual confirmation (a StateDigest field: `orienting_to_sound`). Ego-noise from Go2 locomotion is a known degrader (SSL review) — measure it in sim-to-real.
4. **Expressiveness is context-gated — and pays off most when coupled to speech.** ELEGNT: expressive movement lifts engagement/character in social tasks (M 56 vs 29) but shows *no* difference on function tasks and is less welcome for older users; WTW: style multiplicity costs sprint performance; Casso: *slow* idle motion reads as more anthropomorphic/intelligent, fast idle as rigid/threatening; Castro-González: smooth motion raises animacy/likeability but can raise unease for humanlike forms; Cohen 2026: body language alone conveys navigation intent at ≈44 % vs audio ≈82 % / text ≈88 %, and *coordinated* multimodal cues are best. → Model B's narration ("Sure, I'll check the sofa") must be time-locked to the body's anticipatory glance/turn; Model A should expose an expressiveness gain γ (ELEGNT's term) that Model B sets from context (social vs functional segment, owner profile).
5. **Gaze while walking has measurable human statistics to imitate.** Fixations 300–400 ms at 2.3–2.8 Hz; head contributes ≈25 % of 40–50° shifts and >90 % beyond 70° (Schreiter); gaze precedes head precedes trajectory (Holman); a gaze cue to one side makes 59 % vs 45 % of pedestrians skirt that way regardless of robot morphology (Jakobowsky). On a neck-less Go2, "gaze" = body yaw/pitch + camera crop + LED/eye display; the anticipatory turn should precede path changes by roughly the human lead.
6. **Where-to-look can be learned, and the learning signal is the task.** TAGA (G1, Jetson Orin): active gaze emerges from locomotion reward and lifts stepping-stone success 52 → 98 %; EyeRobot: search/fixation/tracking emerge from a BC-RL loop (87 % search success, 1.8 s). For Model A in simulation: add a gaze/heading action with terrain-and-goal reward; the *observable* consequence (the dog looking at the sofa before walking there) is the liveness, for free. Curiosity-style exploration head turns then come from IOR/habituation on the saliency map, not from a separate script.
7. **Expressive Go2 motion libraries are cheap to grow.** Hand-coded canine behaviours on Spot raised animacy in the wild (N = 222, p = 0.01); LGPL reaches user-preferred gaits in 4 queries; Uni-Mo yields 7,488 language-annotated Go2 motions with 96.7 % real-world success. → Build a small clip library (play-bow, tail-style wiggle, sit, look-around) and let Model B trigger clips as *episodic* animations blended by the WTW-style tracker (BD-X pattern).
8. **Evaluation plan implied by the literature.** Concurrent metrics: navigation SR/SPL and instruction-following on the frozen matrix **and** Godspeed/RoSAS (animacy, anthropomorphism, likeability, discomfort) with 0–100 sliders (ELEGNT) or between-subjects in-the-wild (Hauser); an intent-legibility test (Cohen) for the anticipatory glance; measure the cost of the liveness layer in power (WTW table) and SR. No paper found measures liveliness and navigation success *jointly* on a quadruped — Parcel's eval would be new.

---

## 8. Not cited (fetch failed on every host tried)
- Matthis, Yates, Hayhoe (Current Biology 2018), "Gaze and the Control of Foot Placement When Walking in Natural Terrain" — cell.com 403, SSRN 403, PMC id wrong, Semantic Scholar 429. Canonical human look-ahead numbers remain unverified here.
- Ribeiro & Paiva (HRI 2012), "The Illusion of Robotic Life" — ACM 403, CiteSeerX→archive blocked, author page empty. Its content is summarised second-hand in Schulz et al. 2019.
- XMOS XVF3800 datasheet (the owner's reSpeaker array) — xmos.com returns 406 to the fetcher; DoA is exposed as `AEC_AZIMUTH_VALUES` (four beam azimuths) per the search snippet only. Needs a manual read.
- Breazeal & Scassellati 1999 (Kismet attention) — the guessed IJCAI URL was a different paper; not used.
