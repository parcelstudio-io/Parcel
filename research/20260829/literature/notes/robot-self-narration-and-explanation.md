# Robots narrating what they do and feel for a voice agent — self-explanation, inner speech, progress reports

Literature note for the Parcel Model A / Model B study. Date: 2026-08-29. Every source below was fetched and read (arXiv abs/html/pdf, publisher page, or project page); numbers are transcribed from the fetched text. Where only an abstract was readable this is stated. Web-search budget for the session ran out after ~35 queries, so a few planned queries (annoyance threshold for status-update frequency; quadruped-specific narration; "When to Explain" HRI-2026 field study) were not run.

Scope covered: (1) inner speech in robots (Pipitone/Chella); (2) verbal explanation of plans and failures (REX, Das & Chernova, REFLECT, RONAR, BT explanations, Explainable Planning); (3) thought-to-speech (Think-Verbalize-Speak, STITCH, Inner Thoughts); (4) proactive status updates and trust (Kox 2024; Wang/Pynadath/Hill 2016; Fischer & Jelinek 2026; Heron & Lau 2025; Zhu & Williams 2020; Belsare 2026); (5) commentary during navigation (Verbalization/CoBot, NarraGuide, CLIO, Alter-Ego, R1 5G guide, Dobby); (6) compact state/intent representations consumed by a separate dialogue model (REFLECT summaries, RONAR, H-EMV, KITE, graph-to-text, MomaGraph, ECoT, ProAssist, the "Modern System Recipe" for OpenAI Realtime/Gemini Live robots); (7) grounding and hallucination evidence (NarraGuide, Dobby, Kim/Lee/Mutlu, "From Language to Action", Levy et al.).

---

## 1. Inner speech in robots (Pipitone / Chella)

### 1.1 Pipitone, Geraci, D'Amico, Seidita, Chella (2021). "Robot's Inner Speech Effects on Trust and Anthropomorphic Cues in Human-Robot Cooperation." arXiv:2109.09388
URL: https://arxiv.org/abs/2109.09388 (PDF read via pdftotext)

- Setup: Pepper cooperates with a person to set a virtual table on a 15-inch tablet according to an etiquette schema. Inner speech is implemented in ACT-R integrated with ROS; utterances are recalled rule-based from declarative memory in a fixed order (no LLM). Inner vs outer speech is distinguished for the listener by voice tune/volume, LED colour and a "double effect" on the voice.
- Example inner/outer sequence when the user asks to place the knife on the wrong side:
  - I: "To make this request, Bill does not know that the knife should not be placed in that position or he wants to test me."
  - I: "Should I put the knife to the left of the plate? But if it goes right!"
  - O: "Bill, do you really want to infringe the etiquette rule for the knife?"
  - (user says yes) I: "I don't want to disappoint him..." O: "Ok Bill, I will place the knife to the left of the plate, as you want."
  - (user says no) O: "Great! I will place the knife in the position expected for it!" I: "I must pay attention; the knife is dangerous!" I: "But I'm robot, the knife never hurts me" O: "Knife moved to the right of the plate!"
- Design: pre-test / post-test (post-test administered 15 days after pre-test), N = 27 in the experimental group; the control group had not yet been run at preprint time (stated limitation).
- Scales: Trust Perception Scale-HRI (short form), Godspeed (24 items, 5-point), Self-Talk Scale.
- Table II (paired t, df = 26): Trust 65.70 (SD 7.60) -> 68.91 (SD 6.91), t = -2.06, p < .05. Anthropomorphism 2.70 -> 3.31, t = -4.20, p < .001. Animacy 3.19 -> 3.78, t = -4.43, p < .001. Likeability 4.10 -> 4.30, t = -1.40 (marked *). Perceived intelligence 3.90 -> 4.19, t = -2.47, p < .05. Perceived safety 4.07 -> 4.04, n.s. Everyday self-talk frequency as covariate: ANOVA n.s.
- Journal version: "Robot's Inner Speech Effects on Human Trust and Anthropomorphism", Int. J. Social Robotics (2023/2024), https://link.springer.com/article/10.1007/s12369-023-01002-3 — paywalled (303 to idp.springer.com); its control-group numbers could not be read.

### 1.2 Pipitone & Chella (2021). "What robots want? Hearing the inner voice of a robot." iScience — press release
URL: https://www.eurekalert.org/news-releases/693465 (Cell Press release, 21 April 2021). The iScience full text (cell.com, sciencedirect, pubmed) returned 403/cookie walls.
- Task: place a napkin at a dining table while a user's request conflicts with etiquette rules.
- Inner speech example: "Ehm, this situation upsets me. I would never break the rules, but I can't upset him, so I'm doing what he wants."
- Claim: "higher task-completion rate when engaging in self-dialogue" and that the robot "outperformed the international standard functional and moral requirements for collaborative robots." No percentages given in the release.

### 1.3 Code: Arianna-Pipitone/robot-inner-speech
URL: https://github.com/Arianna-Pipitone/robot-inner-speech
- ACT-R cognitive architecture + ROS + MoveIt!, Pepper; rule-based generation from declarative facts (INNER folder); Python bridge for speech. Runs standalone or on the robot; Ubuntu 16.04+.

### 1.4 Pipitone, Corvaia, Chella (2026). "Towards robot affective appraisal linking inner speech and emotion." Robotics and Autonomous Systems
URL: https://www.sciencedirect.com/science/article/pii/S0921889026000369 — 403; only the title/venue were visible in search results. Not read; listed for completeness only.

**Takeaway for Parcel:** the inner-speech line gives (a) the only direct pre/post evidence that overt self-talk raises trust (+3.2 points on a ~100-point TPS-HRI scale, small effect, no control group in the readable version) and anthropomorphism (+0.6 on 5-point, large effect), and (b) a concrete utterance grammar: an inner "why" line followed by an outer "what I'll do" line, delivered with a distinct voice signature. Nothing in this line is learned; it is rule-based ACT-R.

---

## 2. Proactive status updates, transparency utterances and trust (numbers)

### 2.1 Kox, van den Boogaard, Turjaka, Kerstholt (2024). "The Journey or the Destination: The Impact of Transparency and Goal Attainment on Trust in Human-Robot Teams." ACM THRI 14(2), art. 23
URL: https://publications.tno.nl/publication/34643331/wVP1udsi/kox-2024-journey.pdf (open PDF; ACM page 403)
- N = 82 (87 minus 5 excluded), 2 x 2 between subjects: transparency (low/high) x outcome (positive/negative). Virtual military mission; the robot deviates from the planned route.
- High transparency = "regular status updates including an explanation (i.e., the what and why) of its actions": Table 1 audio messages: "Moving to location: left turn", "Moving to location: straight ahead", "Moving to location: approaching bridge", "Moving to location: crossing bridge"; deviation message "A faster alternative route has been detected, because the river had dried up. Moving to location: right turn." Four updates per mission; TTS (ttsmp3.com, US English Matthew). Low transparency = no updates.
- Perceived trustworthiness: main effect of transparency F(1,78) = 16.72, p < .001, eta^2 = .177; high M = 5.1 (SE 0.1) vs low M = 4.3. Transparency x time F(2.48,234) = 12.37, p < .001, eta^2 = .137; gap opens at T6 immediately after the deviation (delta M = 1.2, p < .001), shrinks to 1.0 (T7) and 0.8 (T8, p = .003). Outcome main effect F(1,78) = 7.93, p = .006, eta^2 = .092; three-way interaction n.s. (p = .445). Ability sub-dimension effect of transparency delta M = 0.8, F(1,78) = 31.80, eta^2 = .290. Abstract: transparency gave "higher and more stable levels of trust, without increasing subjective workload" (NASA-TLX).
- The buffer effect is tied to the *explained deviation*: "the robot's silent deviation before T6 results in a trust violation."

### 2.2 Wang, Pynadath, Hill (2016). "Trust Calibration within a Human-Robot Team: Comparing Automatically Generated Explanations." HRI 2016
URL: https://people.ict.usc.edu/~nwang/PDF/HRI_2016_NW_DVP_SGH.pdf
- 160 AMT participants recruited, 140 analysed; 2 (robot ability high/low) x 3 (no explanation / confidence-level explanation / observation explanation), POMDP-based explanations generated by PsychSim; 3 reconnaissance missions.
- Explanation templates: confidence-level adds the robot's certainty in its recommendation; observation explanation states the sensor evidence, e.g. "...My microphone picked up a friendly conversation."
- Main effect of explanations (Table III): Trust 6.17 (confidence) / 6.29 (observation) / 5.37 (none), both vs none p < .05; Transparency 5.96 / 5.52 / 4.75; Compliance 86.0 / 86.4 / 83.9 (n.s.).
- Low-ability robot (Table IV): Trust 6.15 / 6.07 / 4.31; Transparency 5.51 / 5.71 / 3.66; Mission success 97.1 / 93.7 / 52.2; Correct decisions 91.9 / 87.0 / 71.9 (all explanation vs none p < .05). High-ability robot: trust 6.18 / 6.57 / 6.39 (n.s.).
- Trust correlates with transparency r(137) = .712, p < .001.
- Reading: explanations matter most when the robot is unreliable; a fallible robot that says why it decided is trusted like a reliable one.

### 2.3 Fischer & Jelinek (2026). "Towards a Systematic Model of the Effects of Transparency Utterances on Calibrating Trust in Social Robots." HRI 2026
URL: https://portal.findresearcher.sdu.dk/en/publications/towards-a-systematic-model-of-the-effects-of-transparency-utteran/ (ACM page 403)
- In-person between-subject experiment, N = 47. Depending on utterance design, users "perceive the competence, benevolence and transparency of the robot differently and infer more or fewer additional capabilities"; confirms an effect of transparency-utterance design on (over-)trust. Utterance examples not in the readable abstract.

### 2.4 Zhu & Williams (2020). "Effects of Proactive Explanations by Robots on Human-Robot Trust." ICSR 2020 / MIRRORLab thesis page
URL: https://mirrorlab.mines.edu/publications/zhu2020thesis/ (Springer chapter 303-redirected)
- Resource-management testbed; explanations given *before* actions. Finding: "a positive relationship between providing proactive explanations and human-robot trust." No numbers readable.

### 2.5 Heron & Lau (2025). "Trust in Autonomous Human-Robot Collaboration: Effects of Responsive Interaction Policies." arXiv:2603.00154
URL: https://arxiv.org/pdf/2603.00154
- Misty-II, fully autonomous (no WoZ), dialogue-driven puzzle; responsive policy (proactive, affect-aware, adapts assistance) vs neutral reactive policy. 29 completed sessions; 5 non-viable due to ASR breakdown; eligible n = 24 (control 10, responsive 14).
- Experienced trust (TI-HRC) 39 (SD 22) vs 67 (SD 21), p = .004; perceived trust (TPS-HRI) 59 (17) vs 77 (18), p = .022. Mixed model: TI-HRC beta = 16.28, SE 5.14, p = .005; TPS-HRI beta = 14.17, p = .046. Bayesian posterior medians 14.98 [7.29, 22.22] and 12.76.
- Dialogue coding: responsive robot used collaborative language ("we", "let's") in 42% of turns vs 5% (p < .001); control robot did more silence check-ins (21% vs 13% of turns). Communication-breakdown turns did not differ (25% vs 22%, p = .70). Including breakdown sessions attenuates the trust advantage to beta ~7 with CIs crossing zero: "experienced trust is particularly sensitive to interaction breakdown."

### 2.6 Belsare, Karimi, Mattson, Nakka, Brown (2026). "What Is My Robot Thinking? Design Considerations for Transparent and Trustworthy Shared Autonomy." arXiv:2606.06870
URL: https://arxiv.org/abs/2606.06870 (abstract)
- N = 25, two assistive manipulation tasks; feedback modality (visual vs auditory) x richness (sparse vs rich). Feedback "significantly improves intent alignment and reduces corrective intervention"; "effective transparency enhances coordination primarily through goal legibility, while trust depends on task-appropriate information exposure rather than maximal disclosure." Participants preferred visual feedback.

### 2.7 REX — Lee, Praveena, Mutlu (2024). "REX: Designing User-centered Repair and Explanations to Address Robot Failures." DIS 2024
URL: https://arxiv.org/abs/2405.16710
- Online study n = 162 and in-person n = 24. Users reported increased trust, satisfaction and utility when the robot performed automated repair plus explanations; but safety, privacy and complexity risks require adaptive repair/explanation strategies by risk severity and type.

### 2.8 Kim, Lee, Mutlu (2024). "Understanding Large-Language Model (LLM)-powered Human-Robot Interaction." HRI 2024
URL: https://arxiv.org/html/2401.03217
- N = 32; Pepper; GPT-3.5 (text-davinci-003, T = 0.7); text vs voice vs robot agents; four tasks. Voice agent had the highest failure rate, robot moderate, text lowest. Hallucination example: told a user to "bring a sand baking tray and ski on the tray." Sophisticated speech raised expectations for matching non-verbal behaviour ("movements... were random and didn't have any relation to what it was saying").

**Takeaway for Parcel:** the effect sizes for spoken progress/explanation are large when (a) the robot deviates or fails (Kox: eta^2 = .177 main effect; gap 1.2 on 7-point right after the deviation) and (b) the robot is unreliable (Wang: mission success 52 -> 97). Utterances of the form "<progress> + <why>" are what worked. Trust gains are fragile under ASR/communication breakdown (Heron & Lau), and utterance design can induce over-trust in capabilities the robot lacks (Fischer & Jelinek) — directly relevant to Parcel's capability-grounding score of 2/10.

---

## 3. Verbal explanations of plans and failures

### 3.1 Das, Banerjee, Chernova (2021). "Explainable AI for Robot Failures: Generating Explanations that Improve User Assistance in Fault Recovery." HRI 2021 (best paper, technical)
URL: https://arxiv.org/abs/2101.01625 (PDF read)
- Study 1: 80 AMT recruited, 70 analysed, 13-15 per condition; conditions None / Action-Based / Context-Based / AB-History / CB-History. Presence of context: failure identification F(2,67) = 6.95, p = .0018 (CB vs None t = 3.729, p = .0012); solution identification trend F = 2.92, p = .06 (CB vs None t = 3.12, p = .007). History: FId F(2,67) = 3.36, p = .04 (History vs None t = 3.447, p = .003). CB-H best, especially for internal errors (CB-H vs None t(62) = -3.955, p = .0018).
- Study 2: 45 recruited / 41 analysed; encoder-decoder (GRU, hidden 20) trained on 60 kitchen simulations (2100 timesteps) generates CB-H explanations with 81.81% accuracy on the six failure causes; in an unseen office environment, generated explanations (CB-H-M) vs None: FId t(38) = -4.158, p = .00049; CB-H-M vs hand-scripted CB-H: t = -0.208, p = .97 (no difference).
- Explanation content = current action + last successful action + environmental context.

### 3.2 REFLECT — Liu, Bahety, Song (2023). "REFLECT: Summarizing Robot Experiences for Failure Explanation and Correction." CoRL 2023
URL: https://arxiv.org/html/2306.15724 ; project page https://robot-reflect.github.io/
- Hierarchical summary: (1) sensory-input summary: RGB-D + audio + robot state -> task-informed scene graph (MDETR detection, CLIP state classification, heuristic spatial relations inside/on/left/right/above/below/occluding/near; AudioCLIP audio labels; gripper state); (2) event-based summary: keyframes when scene graph changes, audio event or subgoal end, serialized as "[timestep] Action: <robot action> / Visual observation: <objects, states, relations> / Auditory observation: <audio>"; (3) subgoal-based summary at subgoal endpoints.
- Progressive failure explanation: check subgoals in order; on mismatch, fetch the event-level observations; if all subgoals pass but task fails, compare plan against final state (planning error).
- RoboFail: 100 simulated failures over 10 AI2THOR kitchen tasks + 30 real failures over 11 tasks (UR5e). GPT-4.
- Sim results: explanation accuracy 88.4%, localization 96.0%, correction success 79.1%; without sound 50.0% / 68.8%; without progressive 46.5% / 62.8% / 60.5%. Correction planning success with vs without explanation 79.1% vs 41.9%.
- Example output: "At 02:27, the robot failed to make coffee because it picked up the pink cup instead of the blue cup."
- Code: github.com/columbia-ai-robotics/reflect; dataset at cs.columbia.edu/~liuzeyi/reflect_data (license not stated on page).

### 3.3 RONAR — Wang, Liang, Dhat, Brumbaugh, Walker, Krishna, Cakmak (2024). "I Can Tell What I am Doing: Toward Real-World Natural Language Grounding of Robot Experiences." arXiv:2411.12960 (CC BY 4.0)
URL: https://arxiv.org/html/2411.12960
- Inputs: environmental (RGB-D, optical flow), internal (joint states, base odometry), task planning (high-level state). Streams aligned at 0.2 Hz (closest timestamp per 5 s frame). Key-event selection by optical-flow magnitude, joint derivatives and plan-state transitions; normalized cumulative-sum threshold 80 reduces ~1,018 frames to ~30 keyframes per demonstration.
- Summaries: environment as spatial-relation triplets (YOLO-World, FastSAM, depth-filtered), internal state as numeric + lay text, planning as sub-goal sequence/history/outcome. Narration is progressive (conditioned on prior narration). Three modes: Alert (critical events only), Info (multi-sentence, no numbers), Debug (full technical detail).
- RoboNar dataset: 70 real demonstrations, 4 home tasks (pick cup, microwave food, hang hat, collect clothes), Stretch SE3; 76 labelled failures (54 manipulation, 12 navigation, 7 detection). GPT-4o backbone.
- Results: failure explanation +11% over REFLECT; localization 50% better than vision-only; narration Likert 4.50 overall vs 4.13 (TEM-LLM baseline); informativeness 4.56 vs 4.06; coherence 4.56 vs 4.25. Limitation quoted: "Two-step summarization using LLM ... makes the system slow and affects the user experience on real robot systems."

### 3.4 H-EMV — Baermann, DeChant, Plewnia, Peller-Konrad, Bauer, Asfour, Waibel (2024/2025). "Episodic Memory Verbalization using Hierarchical Representations of Life-Long Robot Experience."
URL: https://arxiv.org/html/2409.17702
- Tree: L0 raw (RGB/depth, audio, joints, objects, speech transcripts) -> L1 scene graphs -> L2 events (grouped on scene change/action/speech) -> L3 goals with NL summaries -> L4+ recursive LLM summaries to a root. LLM agent (Gemini 1.5 Pro, GPT-4o) expands collapsed nodes, semantic search, VLM calls, via Python API.
- Data: TEACh up to 100 episodes (~2 months) with 500 QA; Ego4D two recordings 6:43 h and 4:28 h, 40 QA; ARMAR-7 real robot 3.3 h over two months, 30 QA.
- Full multimodal TEACh, 100 episodes: 34% correct + 62% partially correct; ~10K tokens per query vs 1,256K for flat baselines; token cost roughly constant in history length.

### 3.5 KITE — Hosseinzadeh, Wong, Dayoub (2026). "KITE: Keyframe-Indexed Tokenized Evidence for VLM-Based Robot Failure Analysis." arXiv:2604.07034
URL: https://arxiv.org/html/2604.07034
- Training-free front-end: up to M = 8 motion-salient keyframes (512x512), open-vocab detections with confidence, pseudo-BEV schematic, contact-transition tokens (Gain/Loss/Stable), 3D scene-graph relations (left_of, above, in_front_of), robot profile, serialized context string with timestamps.
- Qwen2.5-VL-7B on RoboFAC: +36 failure detection, +18 identification, +33 localization points in sim; +1-5 real; QLoRA-tuned 0.93 detection. Free-text explanation ROUGE-L 0.248 vs 0.194 (sim), 0.252 vs 0.233 (real). Removing pseudo-BEV costs 0.05 ROUGE-L.

### 3.6 Love, Andriella, Alenya (2025). "Temporal Counterfactual Explanations of Behaviour Tree Decisions." arXiv:2509.07674
URL: https://arxiv.org/abs/2509.07674 (abstract)
- Builds a causal model from the BT structure plus domain knowledge; answers contrastive "why" questions with diverse counterfactual explanations in real time; covers BT structures earlier methods could not. No user-study numbers in the abstract.

### 3.7 Chekam et al. (2025). "Interpretable Robot Control via Structured Behavior Trees and Large Language Models." arXiv:2508.09621
URL: https://arxiv.org/abs/2508.09621 (abstract)
- LLM -> BT with domain plugins (person tracking, gesture); "average cognition-to-execution accuracy of approximately 94%" in real environments; interpretability comes from the BT structure, not from generated NL explanations. Code: snt-arg/robot_suite.

### 3.8 Pramanick & Rossi (2024). "Multimodal Coherent Explanation Generation of Robot Failures." IROS 2024
URL: https://arxiv.org/abs/2410.00659 (abstract)
- Checks logical coherence across text/visual explanation modalities by fine-tuning a textual-entailment model; numbers not in abstract.

### 3.9 Zhang, Guo, Stepputtis, Sycara, Campbell (2023). "Explaining Agent Behavior with Large Language Models." arXiv:2309.10346
URL: https://arxiv.org/abs/2309.10346 (abstract)
- Learns a compact behavioural representation from state-action observations (model-agnostic), then a pre-trained LLM produces explanations "with minimal hallucination" and supports clarification/counterfactual queries; claimed as helpful as a human domain expert. Numbers not in abstract.

### 3.10 Fox, Long, Magazzeni (2017). "Explainable Planning." IJCAI-17 XAI workshop
URL: https://arxiv.org/abs/1709.10256
- Canonical framing: plan explanations must answer why-this-action / why-not-that / why-is-this-plan-better questions using the planning model as the shared vocabulary between planner and human.

### 3.11 Sobrin-Hidalgo, Guerrero-Higueras, Matellan-Olivera (2025). "Generating Explanations for Autonomous Robots: a Systematic Review." arXiv:2412.18516
URL: https://arxiv.org/html/2412.18516
- 22 papers (2015-2024) from 803 hits. 50% generate explanations in real time; 16/22 are question-driven (user asks); descriptive > causal > contrastive; text dominant. Navigation is the most-explained skill (15 mentions). Only 11/22 propose an evaluation method. One paper uses an LLM over ROS logs.

### 3.12 Halilovic (2025). "Explainable Robot Navigation." AAAI-25 Doctoral Consortium
URL: https://ojs.aaai.org/index.php/AAAI/article/view/35208/37363 (PDF)
- Thesis programme on explanation representation/abstraction/timing for navigation; reports that "in most situations, people prefer visual-textual explanations"; raises the open question of higher vs lower abstraction levels in navigation explanations. (The 2023 HRI companion paper and the 2024 satisfaction study are ACM-403.)

**Takeaway for Parcel:** the representation that LLMs explain well from is a hierarchical, time-stamped, change-triggered textual summary (subgoal / event / sensory), and explanations that carry *context + recent history* are the ones non-experts can act on. RONAR fixes 0.2 Hz as its stream alignment rate and ~30 keyframes per episode; REFLECT shows the explanation itself nearly doubles correction success (41.9 -> 79.1%). All of these are offline/post-hoc; RONAR explicitly says the two-stage LLM path is too slow for live narration.

---

## 4. Thought-to-speech and "when to speak"

### 4.1 Liu et al. (2025). "Proactive Conversational Agents with Inner Thoughts." CHI 2025
URL: https://arxiv.org/html/2501.00383
- Five stages: Trigger (on_new_message; on_pause after 10 s silence) -> Retrieval (memory saliency by cosine similarity x importance x decay, lambda = 0.95, threshold 0.3) -> Thought formation (System-1 fast and System-2 deliberate thoughts, each < 15 words, tagged with stimulus) -> Evaluation (chain-of-thought rating 1-5 intrinsic motivation) -> Participation (turn-taking prediction + motivation threshold; may interrupt above a limit).
- Eight expression heuristics from a 24-person formative study (394 quotes): relevance (77 mentions), information gap (33), balance (33), coherence (30), dynamics (30), expected impact (23), originality (16), urgency (14).
- Evaluation: 12 participants in pairs, three 10-minute conversations with settings Non-stop Chatter (system1Prob 0.7), Active Contributor (system1Prob 0.2, threshold 3.59), Selective Participant (system1Prob 0, threshold 4.09). Active Contributor preferred by 6/12; social presence median 6 vs 5.5 (p < .05).

### 4.2 ProAssist — "Proactive Assistant Dialogue Generation from Streaming Egocentric Videos." EMNLP 2025
URL: https://arxiv.org/html/2506.05904v1 ; project https://pro-assist.github.io/ (code github.com/pro-assist/ProAssist)
- 30,135 synthetic dialogues over 478.7 h of egocentric video (Ego4D, EpicKitchens, HoloAssist, Assembly101, EgoExoLearn, WTaG), synthesized with LLaMA-3.1-70B.
- Model: LLaMA-3.1-8B-Instruct + SigLIP-SO400M; 1/5/10 tokens per frame; at every frame a binary "remain silent vs speak" decision; negative-frame subsampling ratio rho = 0.1 to fight class imbalance; Iterative Progress Summarization: when near the context limit the model writes a concise task-progress summary and restarts with it in the system prompt.
- Metrics: bipartite matching of semantic similarity + temporal alignment (P/R/F1); LLM-judge correctness/timing/efficiency/helpfulness; Pearson with humans 0.67 (F1) and 0.47 (overall); human eval 100 dialogues, 81% inter-rater agreement; best domain helpfulness 2.67/5.

### 4.3 Woo, Lee, Kim, Kim (2025). "Think, Verbalize, then Speak." EMNLP 2025
URL: https://arxiv.org/abs/2509.16028 (abstract)
- Decouples reasoning from spoken delivery; ReVerT is "a latency-efficient verbalizer based on incremental and asynchronous summarization" that turns intermediate reasoning into speech-ready text; "enhances speech naturalness and conciseness with minimal impact on reasoning."

### 4.4 Chiang et al. (2025/2026). "STITCH: Simultaneous Thinking and Talking with Chunked Reasoning for Spoken Language Models." ICLR 2026
URL: https://arxiv.org/abs/2507.15375
- Alternates unspoken reasoning chunks with spoken chunks; reasoning happens while audio of the previous chunk plays, so latency equals a no-reasoning baseline; +15% on math reasoning; parity elsewhere.

### 4.5 Levy, Elyoseph, Goldberg (2025). "Humans Perceive Wrong Narratives from AI Reasoning Texts."
URL: https://arxiv.org/abs/2508.16599
- Humans asked which reasoning steps causally influence later steps: 29% accuracy (chance 25%); 42% for majority vote on high-agreement items. "Reasoning texts should be treated as an artifact to be investigated, not taken at face value."

### 4.6 Huang et al. (2022). "Inner Monologue: Embodied Reasoning through Planning with Language Models."
URL: https://arxiv.org/abs/2207.05608 (abstract)
- Closes the loop by feeding textual success detection, scene descriptions and human feedback back into the LLM planner; "significantly improves high-level instruction completion" on simulated and real tabletop and long-horizon kitchen mobile manipulation.

### 4.7 Zawalski, Chen, Pertsch, Mees, Finn, Levine (2024). "Robotic Control via Embodied Chain-of-Thought Reasoning." CoRL 2024
URL: https://arxiv.org/html/2407.08693v2
- Chain: TASK -> PLAN -> SUBTASK -> SUBTASK_REASON -> MOVE -> MOVE_REASON -> GRIPPER POSITION -> VISIBLE OBJECTS. ~2.5 M Bridge-v2 transitions annotated synthetically (7 days).
- OpenVLA-7B base: in-distribution view 44% +/- 3.9 -> 66% +/- 3.8 (+28 abs); OOD view 30% -> 64% (+34). Tokens per step 7 -> ~350. Speed-ups: 5-step reasoning freeze +24% speed (72% success); asynchronous execution +40% speed (65%). One natural-language correction lifts hard-task success 32% -> 80%.

### 4.8 Cox, Martin-Lise, Hosio, van Berkel (2026). "Watching AI Think: User Perceptions of Visible Thinking in Chatbots."
URL: https://arxiv.org/pdf/2601.16720 — only metadata readable; studies visible reasoning vs baseline for trust/transparency/help-seeking. Numbers not extracted.

**Takeaway for Parcel:** Model B's narration layer should (i) keep a covert thought stream and gate speech by an intrinsic-motivation score with thresholds (Inner Thoughts), (ii) learn the per-frame speak/silent decision from streams with heavy negative subsampling and periodic progress summaries (ProAssist), (iii) verbalize a compact speech-ready line rather than the reasoning chain (Think-Verbalize-Speak, STITCH), and (iv) never expose raw reasoning as if it were the cause of behaviour (Levy: 29% comprehension). ECoT shows a trainable policy can emit a plan/subtask/move representation before acting, at a 50x token cost that async decoding partly hides.

---

## 5. Commentary during navigation and tours

### 5.1 Rosenthal, Selvaraj, Veloso (2016). "Verbalization: Narration of Autonomous Robot Experience." IJCAI 2016
URL: https://www.ijcai.org/Proceedings/16/Papers/127.pdf
- Verbalization space with three axes: Abstraction (Level 1 raw coordinates/distances "I went straight for 8.5 meters and turned left..."; Level 2 turn angles/distances; Level 3 landmarks; Level 4 room numbers/corridors/bridges), Locality (global route / region / landmark subset), Specificity (general picture / summary / detailed narrative). Template sentences, e.g. "[I] [visited/passed] the [room]", "[I] [went through/took] the [corridor/bridge]".
- Example Level-4 detailed narrative: "I started from Office 3201, then I went through the 3200 corridor, then I took the elevator ... then I reached office 7416." Detailed narratives are 55-104 words; general-picture narratives are much shorter and contain no numbers at Level 4. CoBot multi-floor deployment; different user groups want different points in the space.

### 5.2 NarraGuide — Hu, Sato, Du, Ye, Zhu, Praveena, Mutlu (2025). "NarraGuide: an LLM-based Narrative Mobile Robot for Remote Place Exploration." UIST 2025
URL: https://arxiv.org/pdf/2508.01235
- TurtleBot3 + gimbal camera in a geology museum; ROS2 Nav2; GPT-4 intent classifier and per-intent handlers, each with its own grounding text keyed to the robot's current location/exhibit; navigation goal chosen via GPT-4 function calling; robot proactively speaks (suggests next exhibit, asks a question) after 45 s of user silence; browser STT/TTS.
- User study n = 20. Participants accepted robot suggestions M = 2.90 (SD 2.32) times vs rejected 0.9; majority (11/20) said they trusted the narratives as "accurate"/"correct"; six noted information "was not completely correct" but still satisfying. Quote: "we have observed instances where the robot came up with fake information from hallucination, however, participants couldn't detect the fake information" (two participants believed a made-up answer about a rock they pointed at). Users complained the robot moved on before they were done and that ASR failed during robot speech and with bystander noise.

### 5.3 CLIO — Chen et al. (2025). "CLIO: A Tour Guide Robot with Co-speech Actions for Visual Attention Guidance and Enhanced User Engagement."
URL: https://arxiv.org/html/2512.05389
- Wheel-legged base, LED-eye head, RGB-D, laser pointer. OpenAI o3-pro parses the exhibition script into a per-sentence action queue (waypoints + LookAtExhibit / PointLaser / face tracking / blink), executed by ROS2 action servers so gesture and sentence finish together.
- N = 28 (mean age 25.3), within-subjects vs audio-only: all robot-impression and engagement subscales p < .001; time-to-first-fixation on exhibits reduced by ~4-7 s for ambiguous items; fixation durations up.

### 5.4 Garello, Cocchella, Sciutti, Catalano, Rea (2025). "Next-Gen Museum Guides: Autonomous Navigation and Visitor Interaction with an Agentic Robot." arXiv:2507.12273
URL: https://arxiv.org/pdf/2507.12273
- Alter-Ego dual-arm mobile robot; Hector SLAM + AMCL; proximity/orientation-triggered pre-recorded utterances ("We are now passing by the 'Sails' area, where you can see..."); GPT-4o mini with function calls go_to(destination) and end_tour(); Google STT; dynamic prompt rebuilt at each area transition containing robot identity, list of areas visited / not yet visited, artworks near the robot with relative position, chat history — explicitly "to interrogate the LLM with a limited number of input tokens ... reducing the Input/Output delay." No verbal response for 120 s -> end_tour(). YOLOv10-n face detection to start.
- Field study: 34 Italian participants (mean age 30.5), 17 announced / 17 surprise. Mean interaction 19.2 min; 7.29 questions per visitor (SD 6.21), of which 3.71 answered correctly, 2.25 out of scope, 1.26 comprehension failures. Comprehension-failure rate 33.33% in the noisiest areas vs 5.88% in the quietest. Perceived competence dropped slightly pre -> post (p = .019); latency in responses was a repeated complaint.

### 5.5 Rosa et al. (2024). "Tour guide robot: a 5G-enabled robot museum guide." Frontiers in Robotics and AI
URL: https://www.frontiersin.org/journals/robotics-and-ai/articles/10.3389/frobt.2023.1323675/full
- R1 humanoid on wheels; exhibit texts in JSON spoken via Google TTS at POIs, pointing gestures, Dialogflow intents for pre-defined questions; AMCL + A* + DWA. Two-week deployment in two museums; >100 questionnaires; tours 20-45 min; localization RMSE 0.07-0.15 m; 5G latency 23.5 ms (SD 15); battery ~1 h. "The largest complaint was directed to speech interaction, which sometimes presented delays." Noise/reverb hurt ASR.

### 5.6 Dobby (2023). "Dobby: A Conversational Service Robot Driven by GPT-4." arXiv:2310.06303
URL: https://arxiv.org/pdf/2310.06303
- gpt-4-0613 function calling: ExecutePlan(actionSequence[]), CancelPlan(), ContinuePlan(); LLM action strings matched to executable action titles by embedding similarity; invalid plans (e.g. holding two items) caught and re-prompted with an error. "System messages update the agent on the state of the robot": e.g. "SYSTEM: Starting action: Drive to Apple" -> "DOBBY: Off I go, driving towards the apple." Six seconds of silence triggers a re-prompt. Pre-built lab map, LiDAR localization.
- 22 participants toured with Dobby and an identical non-conversational robot: every participant preferred the conversational robot; enjoyment 6.59 vs 4.00 (7-point); landmarks visited 5.27 vs 3.00. Participants noted response delay and that Dobby "hallucinated information about the lab."

### 5.7 "A Modern System Recipe for Situated Embodied Human-Robot Conversation with Real-Time Multimodal LLMs and Tool-Calling" (2026, anonymous MIT/CMU). arXiv:2602.04157
URL: https://arxiv.org/html/2602.04157v1
- Jibo (and Reachy Mini) driven by OpenAI Realtime API or Gemini Live; continuous mic audio; camera frames only on demand via tools look_at_person / look_at_object / look_around / look_for / use_vision; the dialogue model speaks interleaved with tool calls and does not narrate tool execution.
- Latency end-to-end: OpenAI Realtime 689.98 +/- 389.08 ms; Gemini Live 739.10 +/- 593.45 ms. On-device YOLO11-pose 49.3 ms (20.37 Hz); SAM3 161.7 ms (6.18 Hz).
- Tool-decision correctness over 6 scenarios x 4 variants (2 annotators, kappa 0.41): macro accuracy 0.72 (OpenAI) / 0.77 (Gemini); precision 0.88 / 0.84; recall 0.62 / 0.60 — the models under-invoke perception ("Not looking is itself an error because it breaks common ground"). look_at_person over-triggers (precision 0.52-0.68). Fluency 4.62 / 4.42 of 5. Cost per interaction $0.047 (OpenAI) vs $0.018 (Gemini).

### 5.8 Walker, Ultes, Lison (2023/2025). "A Graph-to-Text Approach to Knowledge-Grounded Response Generation in Human-Robot Interaction."
URL: https://arxiv.org/html/2311.16137
- Dialogue-state graph (entity / Image / Location nodes with probabilities and timestamps; spatial/temporal edges) updated continuously from the robot's sensors during an office tour; graph traversals verbalized by parameterized functions ("a laptop was seen in an image taken in an office"; 7 style parameters incl. pronoun, distance precision, uncertainty) and inserted into the prompt of GPT-4 / LLaMA-2-chat.
- Pepper; N = 18. Perceived factuality: GPT-Verbal 4.06 vs GPT-Triples 3.44 (Wilcoxon p = .03); LLaMA-Verbal 3.68. Adequacy 3.88 vs 3.69. The verbalized-graph model used 40 uncertainty markers vs 6 for triples and fewer negations (68 vs 112); remaining factual errors came mostly from undetected objects, not from the LM.

### 5.9 MomaGraph (2025). "State-Aware Unified Scene Graphs with Vision-Language Model for Embodied Task Planning."
URL: https://arxiv.org/abs/2512.16909 (abstract)
- Unified scene graph with spatial-functional relations, part-level interactive elements and object states, produced by a 7B VLM (MomaGraph-R1, RL-trained); 71.6% on MomaGraph-Bench (+11.4 over best baseline); transfers to a real robot.

### 5.10 3DGraphLLM — Zemskova & Yudin (2024/2025)
URL: https://arxiv.org/abs/2412.18450 (abstract) — learnable 3D scene-graph tokens with semantic relations fed to an LLM; evaluated on ScanRefer, Multi3DRefer, ScanQA, SQA3D, Scan2Cap; numbers not in abstract.

### 5.11 Shaji, Huppertz, Mitrevski, Houben (2026). "From Language to Action: Can LLM-Based Agents Be Used for Embodied Robot Cognition?"
URL: https://arxiv.org/html/2603.03148
- GPT-4.1, Claude 4 Sonnet, Qwen3-Coder-480B, DeepSeek-V3.1 as cognitive controllers of a simulated mobile manipulator (PyBullet) with working + episodic memory. T1 (put items in cupboard): 100 / 100 / 80 / 100%. T2 (swap objects): 44.4 / 100 / 66.2 / 75.5%. All except Claude were overconfident; DeepSeek "believes that it has succeeded in all execution trials." Conclusion: LLM belief about success needs external verification.

**Takeaway for Parcel:** every deployed narrating robot found here pushes *robot state into the LLM prompt as text* (Dobby system messages; Alter-Ego dynamic prompt rebuilt per area with visited/unvisited lists; NarraGuide per-location grounding text; graph-to-text verbalization), and every one reports (a) latency as the top user complaint and (b) undetected hallucinations. Verbalized state with explicit uncertainty raised perceived factuality by 0.6 on a 5-point scale. Real-time APIs give ~0.7 s turn latency but only ~0.6 recall on pulling perception via tools, so state must be pushed (the whisperer pattern), not pulled.

---

## 6. What this means for Parcel's Model A / Model B

Parcel today: hosted OpenAI Realtime voice + deterministic tool broker + whisperer that forwards a small StateDigest (nav state/goal, blocked, following, battery, e-stop); task executive with submit/suspend/resume and transactional amendment; LiDAR grid planner + SigLIP-2 grounding; 10 Hz duplex frame clock with act-token codec; instruction-nav SR 0.20; capability grounding 2/10; personal conversation 3/13.

### 6.1 The representation Model A should emit (for Model B / the hosted voice)
1. Make it a *hierarchical, time-stamped, change-triggered text/JSON digest*, not a per-frame embedding. Three levels map directly onto REFLECT/RONAR/H-EMV: (L3) goal/plan level = the global-plan queue entry, its status, and the last amendment; (L2) event level = one entry whenever the scene graph, plan state, or blocked/following/battery flags change, serialized "[t] action / visual / audio / plan"; (L1) sensory level kept on-robot for debugging (RONAR Debug mode) and never sent to the hosted model.
2. Rate: RONAR aligns at 0.2 Hz and keeps ~30 keyframes per episode; Alter-Ego rebuilds the prompt only at area transitions; Kox used four spoken updates per mission. The 10 Hz act-token clock is the *control* rate; the narration digest should update at ~0.2-1 Hz plus event triggers. That keeps hosted-model token cost and latency bounded (Alter-Ego's stated reason for its dynamic prompt).
3. Content that has evidence behind it: current action + last completed action + environmental context (Das & Chernova CB-H: F(2,67) = 6.95, p = .0018 for context; history p = .04), the *reason for any deviation* (Kox 2b message), the robot's confidence/observation basis (Wang: confidence and observation explanations both rescued the low-ability robot), and explicit uncertainty markers (Walker: factuality 4.06 vs 3.44). Add a `deviation_reason` field and a `confidence` field to the StateDigest.
4. Success/failure flags must come from Model A's detectors (Inner Monologue success detection; REFLECT subgoal checks), never from the hosted model's own belief (From Language to Action: 3 of 4 frontier LLMs overestimate their success; DeepSeek believes 100%).
5. ECoT is the closest trainable precedent for "policy emits a plan/subtask/move/visible-objects representation before acting": +28/+34 absolute success from the reasoning itself, at 7 -> ~350 tokens/step, recovered by 5-step freeze (+24% speed) or async decode (+40%). For Parcel, generate ECoT-style annotations from the simulator's ground truth (plan, subgoal, blocked reason, visible objects) and train Model A to emit them as the digest; they double as the narration source and as supervision.

### 6.2 Model B: command injection and narration
1. Voice command -> steerable injection: Dobby's ExecutePlan / CancelPlan / ContinuePlan and Alter-Ego's go_to / end_tour are the deployed vocabulary; Parcel already has submit / suspend / resume / amend. What the literature adds is the *narrated acknowledgement pattern*: "SYSTEM: Starting action: Drive to Apple" -> "Off I go, driving towards the apple." i.e. every accepted injection produces an event-level digest entry that the narrator turns into one short line ("Sure, I'll check the sofa").
2. When to speak: implement an Inner-Thoughts style gate — covert thought candidates (< 15 words) scored 1-5 on relevance / information gap / urgency / balance, spoken only above a threshold; pause trigger ~10 s (NarraGuide used 45 s before a proactive suggestion; Dobby 6 s; Alter-Ego 120 s to end). ProAssist gives the trainable version: a per-frame speak/silent head with negative subsampling rho = 0.1 and an iterative progress summary when context fills — the same summary is exactly the "last 1 minute / global history" object the owner wants.
3. Thought-to-speech: narrate a compact speech-ready line, not the reasoning (Think-Verbalize-Speak; STITCH interleaves unspoken reasoning between spoken chunks at zero added latency). Humans misread reasoning text (29% accuracy), so the narrated "why" must be a *verified* digest field (blocked_by, deviation_reason), not free-form CoT.
4. Abstraction control: choose the verbalization-space point per situation (Rosenthal): Level-3/4 landmark language ("heading to the sofa", "going around the chair") for progress; Level-1/2 only when asked. Keep utterances far below the 55-104-word detailed narratives.
5. Distinguish inner from outer voice: Pipitone's voice-signature trick (tone/volume/LED) is cheap on the Go2 speaker/LEDs and is the only tested way to let the owner hear "thinking" without confusing it with a commitment.

### 6.3 Expected effects and how to evaluate
- Trust: expect the biggest gains at deviation/blocked/failure moments (Kox delta M = 1.2 on a 7-point scale right after an explained deviation; eta^2 = .177 overall) and when the robot is unreliable (Wang: mission success 52 -> 97). Instrument the sim-to-real setup with per-event trust probes (Kox T1-T8 pattern), TPS-HRI pre/post (Pipitone; Heron & Lau), and NASA-TLX to show no workload cost.
- Grounding: audit narration against the digest for fabricated facts (NarraGuide, Dobby found undetected hallucinations; Walker counts uncertainty markers 40 vs 6). Report a hallucination-per-utterance rate — no fetched paper reports one, so Parcel would be adding a number the field lacks.
- Timing: ProAssist's temporally aligned P/R/F1 against annotated "should-speak" points; LLM-judge on timing (their human correlation was only 0.47-0.67, so keep a human panel).
- Narration quality: RONAR's 5-point naturalness / informativeness / coherence (their 4.50 overall is the bar).
- Failure explanations: Das & Chernova's failure-identification and solution-identification accuracy for a helper (owner) after hearing the robot's explanation.
- Latency budget: real-time hosted APIs are ~0.7 s per turn (689.98 +/- 389.08 ms OpenAI Realtime); speech delay was the top complaint in three deployments, so the narration line should be ready *before* the hosted model is asked to speak it (pre-computed by Model B from the digest).
- Over-trust: check that narration never implies capabilities the dog lacks (Fischer & Jelinek: utterance design changes inferred capabilities, N = 47); this is the lever for the 2/10 capability-grounding score.

### 6.4 Risks the literature flags
- ASR breakdown erases the trust advantage of a proactive policy (Heron & Lau: beta 16 -> 7 with breakdown sessions included; comprehension-failure rate 33% in noisy areas vs 6% in quiet ones for Alter-Ego). The XVF3800 array and barge-in handling matter as much as the narration model.
- Rich speech raises expectations for matching motion (Kim/Lee/Mutlu); CLIO shows co-speech gestures synchronized per sentence yield p < .001 gains — tie narration events to Go2 gestures via the existing gesture tool.
- Every hosted deployment hallucinated; participants could not detect it. The digest-only narration constraint is the mitigation, and it must be measured.

---

## Sources (all fetched)
- https://arxiv.org/abs/2109.09388 — Pipitone et al. 2021, inner speech and trust (N=27)
- https://www.eurekalert.org/news-releases/693465 — iScience 2021 press release (Pepper inner speech)
- https://github.com/Arianna-Pipitone/robot-inner-speech — code
- https://link.springer.com/article/10.1007/s12369-023-01002-3 — IJSR version (paywalled, not read)
- https://publications.tno.nl/publication/34643331/wVP1udsi/kox-2024-journey.pdf — Kox et al. 2024 THRI
- https://people.ict.usc.edu/~nwang/PDF/HRI_2016_NW_DVP_SGH.pdf — Wang, Pynadath, Hill 2016
- https://portal.findresearcher.sdu.dk/en/publications/towards-a-systematic-model-of-the-effects-of-transparency-utteran/ — Fischer & Jelinek HRI 2026
- https://mirrorlab.mines.edu/publications/zhu2020thesis/ — Zhu & Williams 2020
- https://arxiv.org/pdf/2603.00154 — Heron & Lau 2025
- https://arxiv.org/abs/2606.06870 — Belsare et al. 2026
- https://arxiv.org/abs/2405.16710 — REX, DIS 2024
- https://arxiv.org/html/2401.03217 — Kim, Lee, Mutlu HRI 2024
- https://arxiv.org/abs/2101.01625 — Das, Banerjee, Chernova HRI 2021
- https://arxiv.org/html/2306.15724 and https://robot-reflect.github.io/ — REFLECT
- https://arxiv.org/html/2411.12960 — RONAR
- https://arxiv.org/html/2409.17702 — H-EMV
- https://arxiv.org/html/2604.07034 — KITE
- https://arxiv.org/abs/2509.07674 — BT counterfactual explanations
- https://arxiv.org/abs/2508.09621 — BT + LLM interpretable control
- https://arxiv.org/abs/2410.00659 — multimodal coherent failure explanations
- https://arxiv.org/abs/2309.10346 — Explaining agent behavior with LLMs
- https://arxiv.org/abs/1709.10256 — Explainable Planning
- https://arxiv.org/html/2412.18516 — systematic review of robot explanation generation
- https://ojs.aaai.org/index.php/AAAI/article/view/35208/37363 — Halilovic AAAI-25 DC
- https://arxiv.org/html/2501.00383 — Inner Thoughts, CHI 2025
- https://arxiv.org/html/2506.05904v1 and https://pro-assist.github.io/ — ProAssist
- https://arxiv.org/abs/2509.16028 — Think, Verbalize, then Speak
- https://arxiv.org/abs/2507.15375 — STITCH
- https://arxiv.org/abs/2508.16599 — Levy et al., wrong narratives from reasoning text
- https://arxiv.org/abs/2207.05608 — Inner Monologue
- https://arxiv.org/html/2407.08693v2 — ECoT
- https://arxiv.org/pdf/2601.16720 — Watching AI Think (metadata only)
- https://www.ijcai.org/Proceedings/16/Papers/127.pdf — Verbalization, IJCAI 2016
- https://arxiv.org/pdf/2508.01235 — NarraGuide
- https://arxiv.org/html/2512.05389 — CLIO
- https://arxiv.org/pdf/2507.12273 — Next-Gen Museum Guides (Alter-Ego)
- https://www.frontiersin.org/journals/robotics-and-ai/articles/10.3389/frobt.2023.1323675/full — R1 5G museum guide
- https://arxiv.org/pdf/2310.06303 — Dobby
- https://arxiv.org/html/2602.04157v1 — Modern System Recipe (Realtime/Gemini Live)
- https://arxiv.org/html/2311.16137 — Graph-to-text grounded response generation
- https://arxiv.org/abs/2512.16909 — MomaGraph
- https://arxiv.org/abs/2412.18450 — 3DGraphLLM
- https://arxiv.org/html/2603.03148 — From Language to Action (LLM overconfidence)
