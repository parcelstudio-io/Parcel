# Gap note: the observable "owner lost" event — person following, track loss, re-identification and re-acquisition on legged robots

Research note, 2026-08-28. Scope: how person-following robots (with emphasis on quadrupeds: Unitree Go1/Go2/A1, ANYmal, Spot) detect that the followed person is lost, what they do next (wait, turn toward the last bearing, go to the last observed position, spiral / belief-guided search), how they re-identify the person, and what numbers exist (track continuity, ID switches, re-acquisition delay, search success). Also covers LiDAR-only person tracking and re-ID (Mid-360 class sensors), and robot-perspective tracking benchmarks (JRDB).

Method: every source below was fetched and read in this session (arXiv HTML/abs, PMC full texts, OpenAlex / Semantic Scholar / Crossref / Europe PMC API records, GitHub raw READMEs, Google Patents, vendor pages, or PDFs saved by the fetch tool and converted with `pdftotext`). Where only an abstract or metadata record could be read, that is stated and no numbers beyond the abstract are used. Nothing is cited from memory. Paywalled or blocked full texts (SAGE, ScienceDirect, MDPI HTML/PDF, Wiley, tandfonline, GitHub HTML) are marked "record only".

Reading guide for Parcel: the design wants an event `OWNER_LOST` that can trigger a look-back act token and a later `OWNER_REFOUND` event that closes the loop (reward). Part A gives the field's definitions of "lost" and the behaviours used on loss. Part B gives the identity / re-ID numbers that bound how fast and how reliably `OWNER_REFOUND` can fire. Part C gives LiDAR-specific facts. Part D is the Parcel synthesis.

---

## Part A. What "lost" means and what robots do about it

### A1. Ye et al. 2024 (RAL) — Person Re-Identification for Robot Person Following with Online Continual Learning — on a Unitree Go1
- Source read: arXiv HTML v2, https://arxiv.org/html/2309.11727v2 (abs https://arxiv.org/abs/2309.11727). Code page: https://sites.google.com/view/oclrpf. License: arXiv non-exclusive.
- Platform (verbatim): "A dual-fisheye Ricoh camera is mounted on the robot, providing cropped perspective images with a resolution of 640×480 and a frequency of 30Hz"; "an Intel NUC 11 mini PC powered by a Core i7-1165G7 CPU and NVIDIA GeForce RTX2060-laptop GPU"; "This NUC is mounted on a Unitree Go1 quadruped robot to perform robot person following in the real world".
- Loss definition (verbatim): "If the target person is not found among the tracked people, the training process pauses, and all observations {M,y}_i become candidates for re-identification."
- Re-ID trigger (verbatim): "An individual is considered the target person if his estimated confidence has surpassed a threshold δsw for consecutive ζreid frames." Parameters: δsw = 0.35, ζreid = 5 frames, δreid = 0.7. Memory: short-term |S| = 64, long-term |L| = 512.
- Numbers: tracking success rate (fraction of frames with the recognised box within 50 px of ground truth) corridor1 93.5%, corridor2 94.9%, lab-corridor 96.0%, room 96.8%, public dataset 97.0%; re-ID mean accuracy 96.5 ± 0.4% (corridor2), 94.0 ± 0.7% (lab-corridor). Runtime 35.1 Hz main / 22.2 Hz OCL thread on a high-end PC; 18.8 Hz main / 6.6 Hz OCL thread on the onboard NUC.
- What the robot does while lost: not stated (the paper is about identity, not locomotion on loss).
- Assessment: LOAD-BEARING. This is the only quadruped (Go1) person-following system I found with an explicit, parameterised definition of the loss event and the re-found event, and it runs on NUC-class compute. At 30 Hz camera input, ζreid = 5 frames means `OWNER_REFOUND` can be declared ~0.17 s after the owner reappears with confidence; at the NUC's 18.8 Hz it is ~0.27 s.

### A2. Ye et al. 2025/2026 — Follow-Bench: A Unified Motion Planning Benchmark for Socially-Aware Robot Person Following
- Source read: arXiv abs https://arxiv.org/abs/2509.10796 and HTML https://arxiv.org/html/2509.10796 (submitted 2025-09-13, latest version 2026-05-13). Project page https://follow-bench.github.io/. "All code and deployment scripts are publicly released" (license not stated in the text I read).
- Metric definitions (verbatim, Table II): "Search Success Rate (SSR): Runs with successful search within limited time after target loss"; "Target Visibility Ratio (TVR): Ratio of target visible time to the total time"; "Avoidance Success Rate (ASR): Runs with no collision"; "Success Rate (SR): Runs with successful search and no collision". Loss/search definition (verbatim): "A search-success event is recorded when the robot successfully re-identifies the target within 0.5 N_min steps after each loss of visual contact." and "A successful trial is defined as one in which no collisions occur and the robot resumes tracking of the target within 0.5 N_min steps after each loss."
- Scenarios: 16 types — target trajectories (two-triangle, two-square, U-turn, figure-eight, L-turns 30/45/60 deg, back-and-forth), crowd dynamics (parallel/perpendicular crossing, circular, random crowds), layouts (corridors, doorways, intersections, cluttered spaces). Eight RPF planners re-implemented.
- Numbers (Table VI, MPC-family planners): Perpendicular Crossing (20 humans) SR 47.0% (MPC), 52.0% (MPC w/ Traj.), 51.0% (MPC w/ DS); Cluttered Space (20 obstacles, 30 humans) SR 44.0 / 52.0 / 45.0%.
- Real robot: Scout-mini differential drive, ZED2 camera for pedestrian detection and target identification, Livox MID-360 for obstacle detection and FAST-LIO localisation, Intel NUC 11 (i7-1165G7).
- Assessment: LOAD-BEARING. Gives Parcel a benchmark-grade definition of the loss event ("loss of visual contact") and of the success event (re-identify within a time budget), plus a simulator with 16 scenarios and a real-robot stack that already uses the Mid-360 + camera split. The 44–52% SR numbers say that, in crowds and clutter, loss-then-search is the common case, not an edge case.

### A3. Ye et al. 2025 (IEEE/ASME T-Mech) — RPF-Search: Field-based Search for Robot Person Following in Unknown Dynamic Environments
- Source read: arXiv abs https://arxiv.org/abs/2503.02188 and HTML v2 https://arxiv.org/html/2503.02188v2. Code page https://medlartea.github.io/rpf-search/. License arXiv non-exclusive.
- Problem: re-locating a target lost to topographic occlusion (walls, corners) or dynamic occlusion (pedestrians). Occluder type is inferred from bounding-box IoU history (verbatim): "If the occluder is identified as a pedestrian via the IoU assessment (i.e., the target person's bounding box previously interacted with another pedestrian), the system activates an Observation-based Search Field."
- Search behaviour: topographic loss -> belief-guided search field over frontiers (Canny edges of the occupancy map), candidates from "current and historical observation", SVR trajectory prediction, Gaussian propagation weighted by velocity and social distance, probabilistic inheritance from parent candidates. Dynamic loss -> overtaking potential field when the occluder is slow, fluid-following when overtaking is costly or the occluder is fast.
- Numbers (100 runs per scenario, simulation): topographic Room1/2/3 SR 100/100/100%, SPL 96.1/97.1/96.2% vs baseline GTPL+Greedy-NBV 94/79/42% SR; dynamic Dyna1/2/3 SR 97/100/92%, SPL 92.8/95.6/88.0% vs HB-Particle 34/12/1% SR; ablation (factory) full 100%/94.7% vs 68% without inference factor, 56% without probabilistic inheritance. Real world: 10 trials per scenario, topographic 10/10, long hallway (S) 10/10, long hallway (M) 10/10.
- Platform: sim differential-drive with 2D LiDAR (0–20 m) + RGB-D (120 deg FoV, 0.03–10 m), 2.0 m/s; real Scout-Mini + stereo camera (120 deg, 0.03–10 m), 1.8 m/s.
- Assessment: LOAD-BEARING for the "what to do after the look-back fails" tier. The strong result is that a belief field seeded by last observation + motion history beats naive last-observed-position / frontier baselines by 6–58 points in rooms and by 60–90 points against moving occluders.

### A4. Rollo et al. 2024 (ICRA) — CARPE-ID: Continuously Adaptable Re-identification for Personalized Robot Assistance
- Source read: arXiv abs https://arxiv.org/abs/2310.19413 and HTML https://arxiv.org/html/2310.19413. License: "The authors will grant access to the source code based on the GPL 3.0 license, upon paper acceptance."
- Platform: Robotnik RB-Kairos+ 5e, Intel RealSense D455, notebook with i9-11950H + RTX 3080 Laptop GPU.
- Re-acquisition delay (verbatim): "The min, mean, and max Re-ID delay, i.e. the time the framework takes to re-identify the target, was 0.06, 1.1, and 2.6 seconds."
- Robustness (verbatim): "The MOT algorithm had min and max failure rates of 2 and 7 times with a mean failure rate of 4 times for each video. Instead, our framework failed only 2 times for all the videos." Dataset: 18 videos, 53 min (113 min counting multi-person). Application test: "10 times with 5 different people as targets for a total of 837 meters of following." Tested conditions include complete disappearance from view and outfit changes; tracked correctly "in all the cases (except two limit cases)".
- Assessment: LOAD-BEARING for the timing budget. The only source that reports re-acquisition latency as a distribution; a plain MOT tracker loses the target ~4 times per ~3-minute video, i.e. losses are frequent even indoors.

### A5. Rollo et al. 2023 (IEEE ARSO) — FollowMe: a Robust Person Following Framework Based on Re-Identification and Gestures
- Source read: arXiv abs https://arxiv.org/abs/2311.12992 and HTML https://arxiv.org/html/2311.12992. Code https://github.com/FedericoRollo/followme. License arXiv non-exclusive.
- Platform: Robotnik RB-Kairos+ with UR5e, RealSense D415 on the wrist, i9-11950H + RTX 3080 Laptop; AMCL localisation.
- Loss handling (verbatim): "The KF stops the state integration when measurement updates are not received for a predefined amount of time, the expiration time t_exp." (t_exp = 3 s.) "the robot, not receiving any target position, starts searching for him/her by rotating around itself (for at most one complete turn) toward the direction of the last detected position." Safety: "In the worst case, i.e. the target is not re-identified and the obstacle avoidance module doesn't recognize the person as an obstacle (a rare occurrence), the robot has the time to stop, due to Kalman filter expiration time, nullifying the chances of collision."
- Numbers: Re-ID accuracy 94% (precision 0.96, recall 0.91, F1 0.93) on 8,500 images from 8 subjects; gestures 97%; loop 7–10 Hz depending on 1–10 people in view; safety circle 1.25 m; max velocity 0.3 m/s; framework test with 10 subjects in ~100 m^2 lab. Re-ID: IBN-ResNet-50 pretrained on MSMT17, 256-d, MMT, threshold lambda_d = mu_d + 2 sigma_d from a calibration set.
- Assessment: the cleanest published statement of the "turn toward where you last saw them" behaviour, with a bounded search (<= one turn) and a 3 s coasting window before the loss is acted on.

### A6. Scheidemann et al. 2024 — Obstacle-Avoidant Leader Following with a Quadruped Robot (ANYmal)
- Source read: arXiv HTML https://arxiv.org/html/2410.00572v1 (ETH Zurich). License arXiv non-exclusive. GitHub referenced but URL not in the text I read.
- Sensors: custom 2.4 GHz Angle-of-Arrival RF transponder, four Intel RealSense D265 cameras, Velodyne VLP-16; YOLOv8 on an onboard Jetson Orin; EKF at 10 Hz. Leader position (verbatim): "Once a valid leader is identified, we reproject the bounding box into the LiDAR point cloud to extract a hypothesis of the leader position relative to the robot."
- Loss handling (verbatim): "Leader selection is re-initialized if the two diverge for longer than a predefined amount of time. If this happens, the robot moves towards its last known target, where it interrupts movement until a new leader candidate is found." (The timeout value is not given.)
- Numbers: AoA mean error 3 deg open space, 7 deg with multipath; navigation on 2.5 CPU cores replanning at 50 Hz. Qualitative: "In all but one experiment, the robot dodged the person and continued tracking the leader. In the one case, it temporarily locked onto them as a leader but quickly noticed the mistake ... and corrected itself." No success rates, ID switches or loss counts.
- Assessment: the quadruped-specific on-loss behaviour "go to last known position and wait". Also the archetype of camera-identifies / LiDAR-localises fusion.

### A7. Algabri & Choi 2020 (Sensors 20, CC BY 4.0) — Deep-Learning-Based Indoor Human Following of Mobile Robot Using Color Feature
- Source read: PMC full text https://pmc.ncbi.nlm.nih.gov/articles/PMC7273221/.
- Platform: Gaitech Rabbot (~20 kg), Orbbec Astra RGB-D 640x480, RPLIDAR A2M8, onboard i5 8 GB, external i7-6700 over 5 GHz Wi-Fi. SSD detector, HSV colour signature, LiDAR SLAM.
- State machine: tracking, last observed position (LOP), searching. Verbatim: "When a target loss occurs, the robot navigates autonomously to the LOP of the desired target to re-find him/her and continue its following behavior." In searching: "the robot randomly rotates and scans the place to detect the desired target."
- Numbers: mission success 88.9% (16/18 multi-person experiments); successful tracking rate 91.98% average; recovery success single-person 90.91% (10/11); 23.34 fps (42.84 ms); average robot velocity 0.57 m/s, max 1.08 m/s.
- Companion paper (same authors, Sensors 2022, CC BY, PMC full text https://pmc.ncbi.nlm.nih.gov/articles/PMC9658503/): online-boosting identification with colour, height, location and a modified IoU. Verbatim: "the robot lost the target tracking in two or three frames when the occlusion was complete. However, the robot tracked the target person when the occlusion was partial ... and the robot correctly re-identified him with the online person identification model once he partially reappeared". Success with four features 100% (13/13, blue), 92% (12/13, white), 85% (11/13, black) vs 62% (8/13) with two features; ~24.2–24.9 fps; 0.65–0.74 m/s.
- Related record only (MDPI blocked; OpenAlex https://api.openalex.org/works/doi:10.3390/app11094165): Algabri & Choi 2021, Applied Sciences 11(9):4165, CC BY — adds online trajectory prediction for target recovery when the person leaves the FoV. Numbers not read.
- Assessment: the simplest documented loss pipeline with numbers: a complete occlusion drops the track within 2–3 frames (~0.1 s at 24 fps), and go-to-LOP then rotate-and-scan recovers ~91% of single-person losses.

### A8. Kim et al. 2018 — An Architecture for Person-Following using Active Target Search (Toyota HSR)
- Source read: arXiv abs https://arxiv.org/abs/1809.08793; PDF https://arxiv.org/pdf/1809.08793 saved by the fetch tool and converted with pdftotext.
- Gaze on loss (verbatim): "To track the human target, robot gaze control is essential. The gazing behavior is designed to seek for human candidates. For example, when the human target is not visible, a gaze planner forces a robot to look where humans might exist. This information can be obtained from human belief. If the target doesn't exist, the robot will seek for the target using leg candidates."
- Cascade on loss (verbatim, experiment): "At a certain moment, the target was lost during its way from the kitchen to the office. The first strategy of the robot is to try to predict where person has gone via SVR-based prediction using the input data. Then, the robot decided to go to that location to look for the existence of the person. Since it failed to seek the target using the robot's gaze for that position, the way-point search is activated for further search. Using the Algorithm 1, the robot navigated to the office location. There, the robot re-identified the target". Human belief kept as an occupancy-style grid: "the robot considers a human to be present in that region until it observes that region."
- Sensors: RGB-D (OpenPose, face recognition) + Hokuyo laser (leg detection); SVR with RBF kernel (C = 1000, eps = 0.01, gamma = 1.0). No quantitative success/time numbers.
- Assessment: the earliest explicit look-toward-belief behaviour on loss (gaze first, then locomotion), i.e. exactly the "look back" tier Parcel wants, expressed as a policy over a belief grid.

### A9. Ixova Inc. — US 12,564,968 B2, "Vision-based tracking control method for quadruped robot, and quadruped robot system" (filed 2025-09-28, granted 2026-03-03)
- Source read: Google Patents https://patents.google.com/patent/US12564968B2/en (the USPTO PDF is image-only).
- On loss (verbatim): activates "a particle filter-based predictive tracking mode to predict potential regions where the moving target may appear based on historical motion trajectories" and "controlling the quadruped robot to spirally expand a search path until the moving target is recaptured." The spiral starts from the last confirmed position or the highest-probability predicted region.
- Assessment: evidence that "predict-then-spiral-search from last known position" is now claimed IP for quadrupeds in the US; Parcel should prefer the belief-field (A3) / look-then-go-to-LOP (A5–A7) formulations and avoid a literal spiral path as the primary strategy.

### A10. Do Hoang, Yun, Choi 2017 (URAI) — The reliable recovery mechanism for person-following robot in case of missing target (record only)
- Source read: OpenAlex record https://api.openalex.org/works?search=reliable%20recovery%20mechanism%20person-following%20robot%20missing%20target&per-page=3 (DOI 10.1109/urai.2017.7992828). IEEE page blocked.
- Content: Kalman-filter prediction of where the person went after tracking failure, map-aided navigation with obstacle avoidance to "reach the human target". No numbers read.

### A11. Islam, Hong, Sattar 2019 (IJRR) — Person Following by Autonomous Robots: A Categorical Overview
- Source read: arXiv PDF https://arxiv.org/pdf/1803.08202 (converted with pdftotext).
- Verbatim: "when the robot fails to detect the person (due occlusion or noisy sensing), the recovery planner can use that anticipated person's location as prior and search probable locations for re-identification (Do Hoang et al., 2017; Gupta et al., 2017)." and (Sec. 5.9) "They mostly use feature-based template matching ... techniques; trajectory replication-based techniques (Chen et al., 2017a) are also used for re-identification when the target person transiently disappears from the robot's view and appears again."
- Assessment: confirms the field's canonical structure — predictive prior + recovery planner + re-ID — that every later system above instantiates.

### A12. Srouji et al. 2023 — Human Following in Mobile Platforms with Person Re-Identification (abstract only)
- Source read: arXiv abs https://arxiv.org/abs/2309.12479 (CC BY 4.0). Modules: "360-degree visual registration, a neural-based person re-identification using human faces and torsos, and a motion tracker that records and predicts the target person's future position"; addresses "searching for targets that move out of the camera's sight". Numbers not in the abstract; full text not read.

---

## Part B. Identity and continuity numbers (how reliably and how fast `OWNER_REFOUND` can fire)

### B1. Plozza et al. 2024 (IEEE SAS) — Autonomous Navigation in Dynamic Human Environments with an Embedded 2D LiDAR-based Person Tracker (Unitree A1)
- Source read: arXiv abs https://arxiv.org/abs/2412.15000 and HTML https://arxiv.org/html/2412.15000.
- Platform (verbatim): "Unitree A1 quadrupedal robot"; "Hokuyo UTM-30LX-EW 2D LiDAR configured with 20 Hz scan rate, a 270° scan angle"; NVIDIA Jetson Xavier NX. Detector DR-SPAAM, tracker Norfair (SORT-style).
- Numbers: MOTA 94.26% / MOTP 0.13 m / 10 ID switches (single-robot dataset SR); 81.07% / 0.17 m / 6 IDS (MR1); 81.01% / 0.18 m / 46 IDS (MR2); misses 321 / 217 / 477; false positives 112 / 1607 / 762. Latency on Xavier NX: detector 31.62 ms avg (43.04 worst), tracker 7.66 ms avg (27.42 worst), total 39.28 ms avg (64.93 worst); "reliably running in real-time at 20 Hz". Track termination (verbatim): "Existing tracks are terminated if there are no matches for over C_del updates", C_del = 15 (Config-3) — i.e. 0.75 s at 20 Hz.
- Assessment: the only quadruped-plus-LiDAR person tracker with MOT metrics and an explicit termination timeout; it is not a target-following system (no re-ID), so identity is lost after 0.75 s unmatched.

### B2. Borges, Garrote, Nunes 2026 (IEEE RO-MAN, preprint 2026-06-05, CC BY 4.0) — Does Appearance Help? A Systematic Study of Image-Based Re-Identification in Online 3D Multi-Pedestrian Tracking
- Source read: arXiv HTML https://arxiv.org/html/2606.07233.
- Setup: LiDAR PointPillars detections + AB3DMOT on KITTI pedestrians; RGB re-ID pre-trained on Market-1501, adapted on KITTI-ReID; RTX 5090 for training.
- Numbers: geometry-only HOTA 37.58, MOTA 11.35%, IDF1 54.63, 164 ID switches, 57 ms; best (MobileNetV2 + cascaded matching + EMA) HOTA 38.02, MOTA 11.44%, IDF1 55.75, 162 IDS, 114 ms (~88 FPS); appearance-only HOTA 20.06, MOTA -18.50%, IDF1 27.73, 1,951 IDS.
- Verbatim: "In crowded scenes, where pedestrians are close and occlusions are frequent or prolonged, geometric information is often insufficient to distinguish between pedestrians." and "a cascaded association strategy successfully recovers occluded tracks without compromising overall precision, effectively preventing identity switches to maintain human-robot interaction continuity."
- Assessment: appearance features barely move aggregate IDS in KITTI-like scenes (164 -> 162) and are catastrophic alone (1,951 IDS); their value is specifically for recovering identity after occlusion, which is the Parcel case. Do not expect a generic appearance head to fix continuity — the gain is in the cascade.

### B3. Guo et al. 2023 — LiDAR-based Person Re-identification (ReID3D, LReID dataset)
- Source read: arXiv HTML v2 https://arxiv.org/html/2312.03033v2. Code https://github.com/GWxuan/ReID3D. License CC BY-NC-SA 4.0.
- Dataset: 4x Livox Mid-100, 320 identities, 156,000 point-cloud frames with synchronised RGB, "About 30,000 points per frame", 2 cm distance / 0.1 deg angular accuracy, outdoor across seasons and lighting.
- Numbers: ReID3D rank-1 94.0% overall, 93.3% low light, 94.3% normal light; mAP 83.28 / 82.43 / 83.65%. Camera baseline (TCLNet) rank-1 98.6% normal light vs 60.0% low light.
- Applied follow-up (record only; tandfonline blocked): Kanazawa (Kawasaki Heavy Industries) & Demura 2026, Advanced Robotics, "Development of a human following system using 3D LiDAR and ReID3D" (received 2026-03-09, online 2026-08-10), via OpenAlex https://api.openalex.org/works/doi:10.1080/01691864.2026.2707056 and Crossref https://api.crossref.org/works/10.1080/01691864.2026.2707056. Abstract: existing followers "cannot resume tracking after losing sight" of the target; PointPillars trained on a custom 19,500-frame point-cloud dataset (TAO Toolkit) for detection, ReID3D features for re-identification after loss; evaluated on public data and a real robot. Closed access; no numbers read.
- Assessment: LiDAR-only re-ID at ~94% rank-1 is real (and light-invariant), but it was measured with four Mid-100s at outdoor ranges; nobody I found has published Mid-360 person re-ID numbers indoors at 1–4 m on a 0.3 m-tall quadruped.

### B4. Gómez, Aycard, Baber 2023 (Sensors 23, CC BY) — Efficient Detection and Tracking of Human Using 3D LiDAR Sensor
- Source read: Europe PMC record https://www.ebi.ac.uk/europepmc/webservices/rest/search?query=DOI:10.3390/s23104720&resultType=core&format=json and PMC full text https://pmc.ncbi.nlm.nih.gov/articles/PMC10222621/.
- Setup: Ouster OS1-32 at 1.2 m height, 10 Hz, indoor ~8 m; Core i5 8 GB; background subtraction + voxel + segmentation + three weak classifiers (shape, normals, shade/occlusion) + constant-velocity tracking with 0.5 m gating and a 20-scan elimination threshold.
- Numbers: single person P/R/F1 95.37 / 95.12 / 95.25 at 9.01 Hz; with occlusion 90.18 / 72.24 / 80.22 at 7.84 Hz; complex poses 94.88 / 94.49 / 94.68; two persons 93.65 / 95.16 / 94.40. Verbatim: "Although our solution does not deal explicitly with occlusions, we evaluated it to see how it behaves in their presence."
- Assessment: a clean number for what occlusion does to a LiDAR-only person tracker (recall 95% -> 72%).

### B5. Kitamoto et al. 2025 (Sensors 25(6):1754, CC BY 4.0) — Robust Human Tracking Using a 3D LiDAR and Point Cloud Projection for Human-Following Robots
- Source read: PMC full text https://pmc.ncbi.nlm.nih.gov/articles/PMC11946694/.
- Setup: Velodyne VLP-16-LITE (16 beams, 360 x +/-15 deg, 10 Hz), 25 kg omni-wheel robot (1.2 m tall), i7-9750H laptop, ROS Noetic. Method: project the top 30% of the person's height to 2D, blob detection with 0.15 m distance threshold and 100–800 mm width, nearest-neighbour association within 0.6 m with a velocity constraint.
- Numbers: 2.175 ms per frame (1.49 projection + 0.574 detection + 0.111 tracking); height RMS error 3.83 cm over 11 participants; outlier ratio 3.63% -> 1.75% (p = 0.0055); 3 participants x 10 path types.
- Verbatim limitation: "The major limitation of the proposed method is the assumption that there is only one target person and that the person is registered before tracking begins." No occlusion or loss handling.
- Assessment: LiDAR-only following is cheap (2 ms) but has no identity model; and the "top 30% of height" trick assumes a 1.2 m sensor, not a 0.3 m one.

### B6. Vu, Liu, Liu 2026 (arXiv 2026-07-22) — Gimbal-Based Human Tracking for Companion Robots Using Continual Learning
- Source read: arXiv HTML https://arxiv.org/html/2608.21388. License arXiv non-exclusive. No public code URL in the text.
- Platform: Agilex Scout Mini, Livox Mid-360 (used for the local costmap / collision avoidance only, not for tracking the person), ZED X stereo camera on a single-axis brushless gimbal (iFlight GM6208, SimpleFOC torque mode, Arduino bridge), NVIDIA Jetson Orin with JetPack 6.2.1. YOLOv8 + ByteTrack + ResNet-18 features + pixel-space PID centring; OCL with long-term memory (registration features) and short-term memory (recent appearance).
- Verbatim on loss: "relying solely on motion cues becomes insufficient when the target undergoes prolonged disappearance, substantial viewpoint changes, or temporarily leaves and later re-enters the scene." Evaluation criteria include "the system's capability to accurately ReID the user after periods of total occlusion or when the target reappears in the camera frame." No thresholds, memory sizes, fps, recovery-time or recovery-rate numbers are given.
- Numbers: following error median ~ -0.1 m, max < 0.4 m (slow/fast/run); XY error 0.02–0.04 m walking, ~0.11 m running; heading error ~0.13 rad running; user study n = 10, 5-point Likert: comfort 4.3, companionship 4.6.
- Assessment: the closest hardware analogue to Parcel (Orin + Mid-360 + stereo camera, companion framing). Note that they added a camera gimbal precisely because the camera, not the LiDAR, carries identity — on a Go2 with no neck, body yaw plays that role.

### B7. JRDB (robot-perspective) tracking benchmark
- JRDB paper: Martin-Martin et al., TPAMI 2021, arXiv abs https://arxiv.org/abs/1910.11792 — JackRabbot with stereo cylindrical 360 deg RGB, two Velodyne 16 LiDARs, 64 min annotated, 2.3 M 2D boxes, 1.8 M 3D cuboids, "over 3500 time consistent trajectories".
- Leaderboard read: https://jrdb.erc.monash.edu/leaderboards/tracking22 — 3D tracking: DRFDFF (2024-06-04) MOTA 44.247%, IDF1 31.036%, 12,971 ID switches, HOTA 27.541%; PiFeNet_SimpleTrack (2023-02-21) MOTA 36.046%, IDF1 34.249%, 6,561 IDS, HOTA 35.475%. 2D tracking: MMPAT_CVPR21 MOTA 23.596%, IDF1 29.853%, 6,890 IDS; DeepSORT MOTA 16.674%, IDF1 25.11%, 5,890 IDS.
- JRMOT (Shenoi et al., IROS 2020, CC BY-NC-SA 4.0), arXiv abs https://arxiv.org/abs/2002.08397, PDF https://arxiv.org/pdf/2002.08397 converted with pdftotext: on JRDB "20.2% MOTA at 25 fps (compared to 19.3% MOTA of AB3MOT)"; on the real robot "We evaluate on a total of 110s of data with 14 unique identities across all scenes. On the on-board computer JRMOT runs between 9-11 fps and we measure only 4 ID switches and 1 lost track." Tracks are terminated "if there has been no matching detection for n_term consecutive frames"; 2D+3D fusion gives "30% fewer ID switches" than AB3DMOT across distances.
- OmniTrack (Luo et al., CVPR 2025), arXiv HTML https://arxiv.org/html/2503.04565v2, code https://github.com/xifen523/OmniTrack: JRDB test HOTA 26.92 / MOTA 26.60 / IDF1 30.26 vs OC-SORT 25.04 / 25.64 / 27.89. Verbatim: "While it does not exhibit ID confusion when targets are severely occluded, track loss can still occur in such scenarios."
- Assessment: in crowded robot-perspective scenes, state-of-the-art multi-person trackers keep identity (IDF1) only ~30–35% of the time and switch IDs thousands of times over 27 test sequences. Parcel's problem is easier (one known owner, indoor, few people) but the benchmark says generic MOT continuity is not something to lean on; the owner needs a dedicated re-ID model.

### B8. Jia, Hermans, Leibe (IROS 2022) — 2D vs. 3D LiDAR-based Person Detection on Mobile Robots
- Source read: arXiv abs https://arxiv.org/abs/2106.11239; PDF https://arxiv.org/pdf/2106.11239 saved by the fetch tool and converted with pdftotext.
- Numbers (JRDB validation, Table I): CenterPoint (nuScenes pretrain + JRDB fine-tune, fine voxels) AP_box 70.0 / AP_BEV 71.4 / AP_centroid 74.9 (default) and 78.6 / 80.7 / 82.7 (2D-visible subset); DR-SPAAM (2D LiDAR) AP_centroid 47.6 default, 77.2 on the 2D-visible subset. Verbatim: "from 2m and onward, a significant number of the persons are invisible to 2D LiDAR scans, and thus impossible to be detected." and "The largest chunk of annotations is found within the first 12m." CenterPoint "performs significantly more stable across the whole range" of distances.
- Assessment: a multi-beam 3D LiDAR is what makes person detection range-robust and occlusion-tolerant on a low sensor; a single 2D plane misses a large share of people past 2 m. Relevant because the Go2's Mid-360 sits low and the vertical FoV is 59 deg.

### B9. Older monocular quadruped / re-ID references (records only)
- Liu et al. 2022, Biomimetic Intelligence and Robotics 2(3), CC BY-NC-ND — "A person-following method based on monocular camera for quadruped robots" (OpenAlex record https://api.openalex.org/works?search=person-following%20method%20based%20on%20monocular%20camera%20for%20quadruped%20robots&per-page=3): pose-based detection, Kalman prediction, Convolutional Channel Features + online boosting re-ID, and "an RNN-based recapture mechanism". No numbers read.
- Koide, Miura, Menegatti 2020, RAS 124 — monocular UKF tracking + CCF/online-boosting identification on a Jetson TX2 (Semantic Scholar record https://api.semanticscholar.org/graph/v1/paper/DOI:10.1016/j.robot.2019.103348?fields=title,abstract,year,venue,authors,citationCount; README https://raw.githubusercontent.com/koide3/monocular_person_following/master/README.md). No numbers read.
- Li et al. 2022, IJARS (SAGE, CC BY; page blocked, Semantic Scholar record https://api.semanticscholar.org/graph/v1/paper/DOI:10.1177/17298806221114705?fields=title,abstract,year,venue,authors,openAccessPdf,citationCount): quadruped following using UWB positioning (three-sided weighted least squares) + 3D LiDAR obstacle map + incremental A*. No loss handling in the abstract.
- Ye et al., ICRA 2023, "Robot Person Following Under Partial Occlusion" (abs https://arxiv.org/abs/2302.02121): locate the target from any visible joints; abstract only.

---

## Part C. Commercial / off-the-shelf "follow me" on the target hardware

### C1. Unitree Go2 User Manual V1.0 — Intelligent Side-follow System (ISS 2.0)
- Source read: https://static.generation-robots.com/media/Go2-User-Manual.pdf (saved by the fetch tool, converted with pdftotext).
- The follow mode is driven by a wearable "companion remote control" (not by the robot's camera or LiDAR): "Buckle the remote control to the right side of the human body on the belt, stand on the left side of the robot, and keep your torso facing the same direction as the robot." Speeds: "Short press the M button twice to start the slow auto-following mode, the maximum speed at 1.5m/s" and "fast auto-following mode with maximum speed at 3.0m/s". Obstacle avoidance toggled with L2. Stop: "Short press M button once: stop following and enter the rocker control mode." "ISS2.0 (Not supported by AIR)". The manual does not describe any behaviour for a lost or out-of-range remote beyond stopping/rocker mode; the app and the companion remote cannot control the robot at the same time.
- Assessment: the stock follow mode is a beacon follower; it gives no observable "lost" event on the perception side and cannot be reused for the owner-loss signal.

### C2. Community Go2 follower — orisharabi/unitree-go2-follow-system
- Source read: https://raw.githubusercontent.com/orisharabi/unitree-go2-follow-system/main/README.md.
- UWB tag + YOLOv8 + PID; states FOLLOW (UWB), APPROACH (visual), HOLD; "target-locking mechanism"; emergency stop from the UWB controller. No lost-target behaviour or numeric thresholds documented ("centralized in a configuration module"); no license stated.

### C3. Spot SDK — Fiducial Follow example (the only "follow" example in the current Python examples index)
- Source read: https://dev.bostondynamics.com/python/examples/fiducial_follow/readme; examples index https://dev.bostondynamics.com/python/examples/readme and https://raw.githubusercontent.com/boston-dynamics/spot-sdk/master/python/examples/docs/perception_world_objects_examples.md (neither lists a person-follow example; a `spot_detect_and_follow` path surfaced in search returned 404 on raw/docs, so it is not cited).
- Loss behaviour (verbatim): "the robot will stop exactly at its perceived location of the fiducial until another one is detected." and "To stop the robot from moving, either remove the fiducial it is following from all camera's field of view or stop the code in the command line." Default planar speed limit 1 m/s; `--avoid-obstacles` default False.
- Assessment: the vendor baseline for "what a legged robot does on loss" is "stop and wait"; there is no search, look-back or re-ID.

### C4. Livox Mid-360 vendor showcase
- Source read: https://www.livoxtech.com/showcase/13 — DEEP Robotics X30 uses four Mid-360s "to achieve omnidirectional navigation"; 360 x 59 deg FoV, 200,000 points/s, minimum detection range 10 cm. No person-tracking claims. (Follow-Bench C-A2 and the gimbal companion B6 both use a single Mid-360 for obstacles/localisation only and a camera for the person.)

---

## Part D. What this means for Parcel

**D1. The "lost" event exists in the literature as a tracker-state transition, not as a raw detection miss.** Every system with numbers defines it as "target absent from the set of tracked people for a timeout": 2–3 frames (~0.1 s) for a colour tracker (A7), 15 unmatched updates = 0.75 s for a LiDAR MOT track (B1), 3 s Kalman expiry before acting (A5), "a predefined amount of time" of AoA/camera disagreement (A6), "loss of visual contact" (A2), "target person is not found among the tracked people" (A1). Proposal: two tiers. `OWNER_OCCLUDED` at 0.3–0.75 s of no owner-ID match (coast on the LiDAR track); `OWNER_LOST` at ~2–3 s. Only the second should be allowed to emit the look-back token, or the dog will twitch at every doorway.

**D2. "Look back" is literally the first tier of the published recovery cascade.** FollowMe rotates in place at most one turn "toward the direction of the last detected position" (A5); Kim's HSR gaze planner "forces a robot to look where humans might exist" before any locomotion (A8); ANYmal goes to the last known target and waits (A6); Algabri goes to the LOP then rotates and scans (A7); RPF-Search escalates to a belief field only if that fails (A3). For a Go2 with no neck, body yaw toward the last bearing is the look-back. Because the Mid-360 already sees 360 deg, the yaw is not needed for geometry — it is needed to point the camera (identity) and it is the social signal the owner reads. That split (LiDAR keeps the geometric track, camera re-confirms identity) is what A6, A2 and B6 all do.

**D3. The reward loop closes on its own.** The pair (t_lost, last bearing) -> (t_refound, bearing at re-found) is generated by the tracker with no human labels. Follow-Bench's SSR/TVR (A2) are ready-made rewards: re-identified within a time budget after each loss; fraction of time the owner is visible. The behaviour "turn toward last bearing when lost" is then learnable as the action that minimises re-found latency, with A4's measured re-ID delay (min/mean/max 0.06/1.1/2.6 s) setting how long the act stream should hold a "searching" posture before escalating.

**D4. Re-found can fire fast, but only with a dedicated owner re-ID model.** With A1's rule (confidence > 0.35 for 5 consecutive frames) `OWNER_REFOUND` fires ~0.17 s after reappearance at 30 Hz; A4 measured a mean of 1.1 s in practice. Generic MOT continuity is not enough: JRDB SOTA holds identity ~30–35% IDF1 with thousands of switches (B7), an appearance head barely changes aggregate IDS (B2: 164 -> 162) — its value is only in the post-occlusion cascade. An owner-specific continually-learned embedding (A1, A4, B6 all converge on short-term + long-term memory) is the design pattern; A1 runs it at 18.8 Hz on a NUC with an RTX 2060, so a Jetson Orin can afford it beside an 8B int4 LLM if the perception budget is planned (~40 ms/frame class, B1).

**D5. Expect losses to be common, so the behaviour must be graceful.** Follow-Bench MPC planners succeed in only 44–52% of crowd/clutter runs (A2); a plain MOT tracker lost the target ~4 times per ~3-minute video (A4); a complete occlusion drops a colour track in 2–3 frames (A7); LiDAR-only recall falls 95% -> 72% under occlusion (B4). In a home with doorways and furniture this is a several-times-per-minute event. That is good for learning (many samples) and bad if every event triggers a big search.

**D6. LiDAR-only identity is possible but unmeasured for Parcel's geometry.** ReID3D reaches 94% rank-1 and is light-invariant (B3), and a 2026 industrial follower already pairs PointPillars + ReID3D for re-acquisition after loss (B3, Kanazawa & Demura). But those numbers come from four Mid-100s outdoors; nobody has published points-per-person or re-ID accuracy for a single Mid-360 mounted ~0.3 m off the floor at 1–4 m indoors. Jia (B8) shows a multi-beam 3D LiDAR is range-robust where a 2D plane misses most people past 2 m. Until measured on the Go2, treat the camera as the identity sensor and the Mid-360 as the 360 deg geometric track that survives the camera's FoV.

**D7. IP note.** "Particle-filter prediction + spiral search from last known position" on a quadruped is claimed in US 12,564,968 B2 (granted 2026-03-03, Ixova). Prefer the published look-back -> go-to-LOP -> belief-field cascade (A5, A7, A3), which predates it and has public code (RPF-Search, FollowMe, OCL-RPF).

**D8. Reusable assets.** Follow-Bench (16 scenarios, SSR/TVR metrics, Scout-mini + ZED2 + Mid-360 reference stack) for evaluation; RPF-Search and OCL-RPF code for the search and re-ID modules; FollowMe (GitHub) for the bounded rotate-toward-last-bearing behaviour and the 3 s KF expiry; JRDB for pre-training LiDAR person detectors from a robot's eye height (two VLP-16s on JackRabbot, still taller than a Go2).

**D9. Open measurements Parcel must make itself (no source covers them):** (i) Mid-360 points-on-owner vs distance at Go2 mount height; (ii) loss-event frequency in the target home; (iii) whether a body-yaw look-back measurably shortens re-found latency vs. standing still (the A5/A6 behaviours were never A/B tested); (iv) owner perception of the look-back (B6 measured companionship 4.6/5 for a smooth follower but not for loss behaviour).

---

## Source index (all fetched this session)
1. https://arxiv.org/html/2309.11727v2 (Ye et al., RAL 2024, OCL re-ID on Go1)
2. https://arxiv.org/html/2509.10796 (Ye et al., Follow-Bench, 2025/2026)
3. https://arxiv.org/html/2503.02188v2 (Ye et al., RPF-Search, T-Mech 2025)
4. https://arxiv.org/html/2310.19413 (Rollo et al., CARPE-ID, ICRA 2024)
5. https://arxiv.org/html/2311.12992 (Rollo et al., FollowMe, ARSO 2023)
6. https://arxiv.org/html/2410.00572v1 (Scheidemann et al., ANYmal leader following, 2024)
7. https://pmc.ncbi.nlm.nih.gov/articles/PMC7273221/ (Algabri & Choi, Sensors 2020)
8. https://pmc.ncbi.nlm.nih.gov/articles/PMC9658503/ (Algabri & Choi, Sensors 2022)
9. https://api.openalex.org/works/doi:10.3390/app11094165 (Algabri & Choi, Appl. Sci. 2021, record)
10. https://arxiv.org/pdf/1809.08793 (Kim et al., active target search, 2018)
11. https://patents.google.com/patent/US12564968B2/en (Ixova quadruped tracking patent, 2026)
12. https://api.openalex.org/works?search=reliable%20recovery%20mechanism%20person-following%20robot%20missing%20target&per-page=3 (Do Hoang et al. 2017, record)
13. https://arxiv.org/pdf/1803.08202 (Islam et al., IJRR survey)
14. https://arxiv.org/abs/2309.12479 (Srouji et al. 2023, abstract)
15. https://arxiv.org/html/2412.15000 (Plozza et al., A1 + 2D LiDAR tracker, SAS 2024)
16. https://arxiv.org/html/2606.07233 (Borges et al., RO-MAN 2026)
17. https://arxiv.org/html/2312.03033v2 (Guo et al., ReID3D, 2023)
18. https://api.openalex.org/works/doi:10.1080/01691864.2026.2707056 and https://api.crossref.org/works/10.1080/01691864.2026.2707056 (Kanazawa & Demura, Adv. Robotics 2026, record)
19. https://pmc.ncbi.nlm.nih.gov/articles/PMC10222621/ (Gomez et al., Sensors 2023)
20. https://pmc.ncbi.nlm.nih.gov/articles/PMC11946694/ (Kitamoto et al., Sensors 2025)
21. https://arxiv.org/html/2608.21388 (Vu et al., gimbal companion tracking, 2026)
22. https://arxiv.org/abs/1910.11792 (JRDB, TPAMI 2021)
23. https://jrdb.erc.monash.edu/leaderboards/tracking22 (JRDB tracking leaderboard)
24. https://arxiv.org/pdf/2002.08397 (JRMOT, IROS 2020)
25. https://arxiv.org/html/2503.04565v2 (OmniTrack, CVPR 2025)
26. https://arxiv.org/pdf/2106.11239 (Jia et al., 2D vs 3D LiDAR person detection, IROS 2022)
27. https://api.openalex.org/works?search=person-following%20method%20based%20on%20monocular%20camera%20for%20quadruped%20robots&per-page=3 (Liu et al. 2022, record)
28. https://api.semanticscholar.org/graph/v1/paper/DOI:10.1016/j.robot.2019.103348?fields=title,abstract,year,venue,authors,citationCount and https://raw.githubusercontent.com/koide3/monocular_person_following/master/README.md (Koide et al. 2020)
29. https://api.semanticscholar.org/graph/v1/paper/DOI:10.1177/17298806221114705?fields=title,abstract,year,venue,authors,openAccessPdf,citationCount (Li et al. 2022, record)
30. https://arxiv.org/abs/2302.02121 (Ye et al., ICRA 2023, abstract)
31. https://static.generation-robots.com/media/Go2-User-Manual.pdf (Unitree Go2 manual V1.0)
32. https://raw.githubusercontent.com/orisharabi/unitree-go2-follow-system/main/README.md (community Go2 follower)
33. https://dev.bostondynamics.com/python/examples/fiducial_follow/readme and https://dev.bostondynamics.com/python/examples/readme (Spot SDK)
34. https://www.livoxtech.com/showcase/13 (Livox Mid-360 showcase)
35. https://arxiv.org/abs/2510.11308 (Adap-RPF 2025, abstract; not loss-specific)
