# Gap note: does a body-yaw/pitch "look" from a neckless robot read as attention or help-seeking?

Date: 2026-08-28. Sweep for the Parcel behaviour-model design (Go2 EDU+, no neck; body yaw/pitch only).
Method: WebSearch to find, WebFetch (or pdftotext of the fetched PDF) to read every source before citing.
Sources that could not be read past the abstract are flagged. Nothing here is cited from memory.

## 0. One-paragraph answer

Yes, with a caveat. A torso/body re-orientation toward a person on a robot with no head is reliably read as
*engagement/attention* (Care-O-bot 3 torso gaze-following: N=119, likeability eta^2=.55; Go2 "attentive" body
behaviours: N=80, warmth 6.8 vs 3.4, p<.001; Spot expressive body cues: N=210, next-action accuracy ~44% vs ~14% with no
signal). What body orientation alone does *not* do well is say *who/what* is being attended to (mobile cart: orientation-only
addressee identification 37.5% vs 93.8% with a projected cue, N=22) or carry *trust/confidence* (Spot: body cues raised accuracy but
lowered confidence; audio/text reached ~82-88%). A "look" is also not socially neutral: facing/gazing at a person makes them keep more
distance (Spot +0.19 m, p<.001; FROG tour guide; VR drone gaze p=.039). For "look back at the owner when lost" the best-evidenced
recipe is *legible incapability*: an attempt-then-rewind motion repeated ~3 times raised goal recognition from 60% to 95% (N=120), and
forethought/anticipation before an act raises viewer sureness and appeal (N=273) without raising description accuracy. There is no
commercial expressive/pan-tilt head for the Go2; the only PTZ is a $20k+ inspection gimbal on a different SKU, and the two 2026 papers that
put a custom 2-DoF/pan-tilt servo head on a robot dog validated it with N=6 each.

## 1. Headless / appearance-constrained robots: body orientation as attention

### 1.1 Cohen, Shimizu, Song, Bharath, Larson, Maes (2026) - "Do Robots Need Body Language? Comparing Communication Modalities for Legible Motion Intent in Human-Shared Spaces"
- URL: https://arxiv.org/abs/2604.03451 (HRI Companion '26; CC BY 4.0). Read: abstract page + full PDF (pdftotext).
- Robot: Boston Dynamics Spot (with arm). Online video study, N=210 (Prolific), 78 clips (M=9.74 s), 10 clips per participant, four
  navigation scenarios (crosswalk, turning, passing, starting). Power: 80% to detect f>=0.16.
- Expressive-motion vocabulary (the part that transfers to a neckless Go2): "Directional leaning and limb gestures (yaw/roll/arm
  left/right) indicated turning; forward emphasis (pitch_up, body_extend, arm_extend) indicated movement ahead; and deferential
  postures (bow, crouch, sit) signaled yielding."
- Numbers: next-action prediction accuracy no-signal ~14%; body motion ~44%; lights ~58%; audio ~82%; text ~88% (all signal
  conditions > baseline, p<.001, Holm-corrected paired t-tests). Confidence (1-7): baseline M~4.7, body motion M~4.2 (lower than baseline),
  audio/text >5.5, redundant explicit ~6.1. Trust: baseline M~4.5; "Implicit body motion did not improve the trust rating"; text/audio >5.
- Quote: "Expressive body motion, even in a non-optimized form, substantially outperformed the no-signal baseline in accuracy (~44% vs
  ~14%) when the robot expressed directional leaning, gait cues, or deferential postures ... although confidence and trust did not
  increase above no signaling."
- Relevance: the closest thing to a recognition-rate for body-yaw/pitch intent cues on a quadruped. Body cues are informative but not
  self-sufficient; a voice channel triples accuracy.

### 1.2 Lehmann, Saez-Pons, Syrdal, Dautenhahn (2015) - "In Good Company? Perception of Movement Synchrony of a Non-Anthropomorphic Robot"
- URL: https://pmc.ncbi.nlm.nih.gov/articles/PMC4441426/ (PLOS ONE, open access). Read in full.
- Robot: Care-O-bot 3, no head; torso bends/twists to simulate gaze-following. N=119 (83 M, 36 F; mean age 35.3). Three conditions:
  positive synchrony (torso follows the human's action), negative synchrony (moves opposite), no movement.
- Numbers: likeability M=3.47 / 2.56 / 2.2, F(2,236)=147.12, p<.01, eta^2=.55; perceived intelligence 3.13 / 2.42 / 2.0, F(2,236)=114.53,
  eta^2=.49; IOS (inclusion of other in self) F(2,236)=130.29, eta^2=.52.
- Quote: even minimal synchronised torso movements were "interpreted by participants as engagement".
- Relevance: load-bearing. A headless torso re-orienting toward the person's activity reads as attention with very large effects.

### 1.3 Manor, Cohen, Keidar, Parush, Erel (2025) - "Cognitive Trust in HRI: 'Pay Attention to Me and I'll Trust You Even if You are Wrong'"
- URL: https://arxiv.org/abs/2512.09105 (full HTML read).
- Robot: Unitree Go2, "15 kg quadruped with 12 degrees of freedom", headless, Wizard-of-Oz. N=80 undergraduates (57 F, 23 M, mean 25.7).
  2x2 competence x attentiveness, collaborative search task.
- Attentive behaviours (all body-only): followed the participant keeping close proximity; "happy dance" (energetic running/hopping)
  on relevant finds; "shaking its head side to side (as if signaling 'no') and then lowering its head" on irrelevant finds (on a
  headless Go2 this is body yaw oscillation + body pitch). Low-attentive: did not follow, kept distance, no reactions.
- Numbers: manipulation check RoSAS warmth high-attentive M=6.8 (SD 1.3) vs low M=3.4 (SD 2.1), F(1,76)=74.86, p<.001; cognitive-trust
  subscale F(1,76)=12.96, p<.001; competence x attentiveness on reliance on wrong recommendations F(1,76)=4.61, p=.035.
- Quote: "High attentiveness can compensate for low competence."
- Relevance: load-bearing. Direct evidence that Go2 body-only orienting/following/pitch-shake is perceived as attentiveness and moves
  trust. Caveat: attentiveness is a composite (follow + proximity + reactions), not an isolated body-yaw look.

### 1.4 Sone, Kishi, Ikeda (2025) - "A projection-based approach for clarifying interaction partners in human-robot communication"
- URL: https://www.frontiersin.org/journals/robotics-and-ai/articles/10.3389/frobt.2025.1534060/full (open access). Read in full.
- Robot: i-Cart mini mobile base + projector (no head). N=22 (21 M, 1 F; mean age 23.1). Conditions: orientation-only vs
  projection+orientation.
- Numbers: correct identification of the addressed person 37.5% (orientation only) vs 93.8% (projection), Wilcoxon p=0.0001, large
  effect; willingness to be guided p=0.0002; all UEQ scales p<.05.
- Quote: "methods for non-humanoid robots to convey their focus, such as using body orientation ... remain difficult" (citing Karreman
  2013, Satake 2013).
- Relevance: load-bearing negative result. Body orientation alone is ambiguous about *which* person/object is targeted (~1 in 3
  correct with a small group). A Parcel "look" must be disambiguated by a second channel when more than one target is plausible.

### 1.5 Karreman, Ludden, van Dijk, Evers (2015) - "How can a tour guide robot's orientation influence visitors' orientation and formations?"
- URL: https://www.cs.kent.ac.uk/events/2015/AISB2015/proceedings/hri/7-Karreman-howcana.pdf (AISB 2015; PDF read via pdftotext).
- Robot: FROG outdoor guide robot (screen, lights, small pointer "head"; no articulated gaze). Royal Alcazar, Seville; ~500 visitors
  in groups of 1-7; 278 complete explanations coded (109 with the robot facing the visitors).
- Numbers: visitors stood far away more often when the robot faced them (31 cases, 24.4%) than when it faced the point of interest
  (17, 15.6%); visitors walked toward the robot more when it faced the point of interest (25, 22.9%) than when it faced them
  (18, 14.2%); 78% of passers-by paid no attention in either condition.
- Interpretation in the paper: facing the visitors kept people at a distance, consistent with "people walked closer to a robot that was
  not following them with gaze than when the robot was following them with gaze, as shown by Mumm and Mutlu".
- Relevance: a headless robot's *front* is read as gaze; sustained facing is read as being watched and pushes people back.

### 1.6 Xu, Meng, Li, Khamis, Zhao, Bretin (2023; ICRA 2025) - "Understanding Dynamic Human-Robot Proxemics in the Case of Four-Legged Canine-Inspired Robots"
- URL: https://arxiv.org/html/2302.10729v3 (full HTML read).
- Robot: Boston Dynamics Spot with arm; the gripper is treated as the head: "the Spot gripper can point out at a certain point in
  space while moving, which looks like gazing as the gripper is considered the head of the dog". N=32 (17 M, 15 F, mean 26).
- Numbers (minimum distance kept): forward no-gaze M=1.13 m (SD .31); forward with gaze (robot faces + gripper points at participant)
  M=1.32 m (SD .32), normalized t=-3.58, p<.001; sideways motion M=1.30 m (SD .25), t=-2.36, p<.05; backward M=1.13 m (n.s.).
- Quote: many participants "thought that the Spot stayed still in the experiment zone very suspiciously".
- Relevance: a quadruped "gaze" (body facing + a head-like appendage) is registered and changes behaviour (+0.19 m); sideways body
  orientation reads as unpredictable. Stillness without a cue reads as suspicious, not attentive.

### 1.7 Hashimoto, Hagens, Zgonnikov, Lupetti (2024) - "Safe Spot: Perceived safety of dominant and submissive appearances of quadruped robots"
- URL: https://arxiv.org/abs/2403.05400 (PDF read via pdftotext).
- Robot: Spot. N=21 (13 M, 7 F, 1 NB; 28 +/- 5 y). 2x2 within-subjects (dominant trot/extended legs/raised arm vs submissive
  crawl/bent legs/retracted arm) x (head-on, crossing); 8 repetitions each; 0.5 m/s.
- Numbers: perceived safety submissive 3.5 vs dominant 3.2, t=4.5, p<.001; appearance F=12.6 p<.001; scenario F=11.1 p<.001; prior
  in-person experience F=4.8 p=.03; 11/21 had a more negative impression of the dominant robot.
- Quotes: some participants "explained that gaze was an important aspect"; one read the crouch as "the posture of an animal in
  stalking, so felt like it might pounce".
- Relevance: body pitch/height is read as social stance (dominant vs submissive), and a low crouch can be read as predatory. Any
  "look" pose on Parcel should avoid the stalking crouch.

### 1.8 Hauser, Chan, Bhalani, Kuchimanchi, Siddiqui, Hart (2023; HICSS 2024) - "Influencing Incidental Human-Robot Encounters: Expressive movement improves pedestrians' impressions of a quadruped service robot"
- URL: https://arxiv.org/html/2311.04454 (full HTML read).
- Robot: Spot. Field study, N=222 (112 body-language, 110 control). Behaviours: tail wagging, play bow, sitting, walking in circles,
  chasing its tail (all whole-body; no head).
- Numbers: cynomorphism F(1,220)=4.10, p=.04; animacy F(1,220)=6.18, p=.01; likeability F(1,220)=3.21, p=.07; perceived intelligence
  F(1,220)=0.18, p=.67. Participants rated it "more responsive and more friendly" and "more conscious" despite no interaction.
- Relevance: canine whole-body idioms raise animacy/dog-likeness on a headless quadruped, but not perceived intelligence.

### 1.9 Yang, Biernacka, Bruno (RO-MAN 2025) - "Conveying Emotion and Intention through Quadruped Robotic Motion: A Validation Study Using Canine-Inspired Movements"
- URL: https://ieeexplore.ieee.org/document/11217857/ (DOI 10.1109/RO-MAN63969.2025.11217857). IEEE page returned no body; abstract read via
  https://api.semanticscholar.org/graph/v1/paper/DOI:10.1109/RO-MAN63969.2025.11217857 . ABSTRACT ONLY - robot model and per-movement
  rates not obtained.
- Numbers: N=35; movements for alert, neutral and yes/agree "exceeded the average human recognition rate for robotic emotional expressions
  through body gestures reported in prior work"; prior experience with robots/dogs had no significant effect.
- Relevance: whole-body canine intents are recognisable on a quadruped; "alert" is the nearest thing to an attention state validated.

### 1.10 Lakatos, Holthaus, Sharma et al. (2025) - "Does a 'robot dog' need legs, ears, and tail? A comparative analysis of intention- and emotion-attribution to Miro-E and Unitree Go1"
- URL: https://link.springer.com/article/10.1007/s42977-025-00263-5 (Biologia Futura 76:151-165). Abstract + references read; Methods/Results
  paywalled - ABSTRACT ONLY.
- N=111 children aged 7-10, within-subjects, ethologically inspired behaviours on both robots.
- Result: "there was no significant difference in children's intention-attribution to the two robots"; Miro-E (ears, tail, eyes)
  expressed emotions better; children preferred the Go1. Significant effects of embodiment, dog ownership and age.
- Relevance: a bare Go1 (no head features) conveys *intention* as well as a robot with ears/tail/eyes; what it loses is *emotion*.

## 2. Drones and other headless bodies: what orientation/motion primitives carry attention

### 2.1 Szafir, Mutlu, Fong (HRI 2015) - "Communicating Directionality in Flying Robots"
- URL: https://pages.cs.wisc.edu/~bilge/pubs/2015/HRI15-Szafir.pdf (read via pdftotext).
- Parrot AR.Drone 2.0 with an Arduino LED ring; four light designs (blinker, beacon, thruster, gaze) vs baseline; 5x2 within-subjects,
  N=16 (10 M, 6 F; mean 23.31), paid $10.
- Numbers: manipulation check (robot conveying intent) F(4,69)=38.34, p<.001; objective composite (accuracy+speed) F(4,144)=4.45, p=.002;
  Tukey: gaze p=.003, blinker p=.016, thruster p=.046, beacon p=.522 (n.s.); confidence: gaze p<.001, thruster p=.004, blinker p=.020;
  work-partner perception F(4,69)=5.27; only gaze (p<.001) and blinker (p=.027) made the task significantly easier.
- Quote (P12): "The lights came up in an 'eyes' pattern indicating which way the robot was 'facing,' i.e., the direction in which it
  intended to move."
- Relevance: on a body with no face, a two-region "eyes" cue that defines a *front* was the single best directionality signal.

### 2.2 Bevins, Duncan (2021) - "Aerial Flight Paths for Communication: How Participants Perceive and Intend to Respond to Drone Movements"
- URL: https://www.frontiersin.org/journals/robotics-and-ai/articles/10.3389/frobt.2021.719154/full (open access; read in full).
- Iterative studies: N=64 (label agreement), 20 (in-person elicitation), 80 (exploration), 40 (confirmation), 8 (in-person validation).
  16 motions (front-back, left-right, up-down, spiral, figure-8, circle, hover, yaw, etc.).
- Numbers: landing/descent 59.4% agreement; "go away" side-to-side/undulate/figure-8 40-54.5%; "follow it" front-back had the strongest
  chi-square (124.5); phase-3 effects Cramer's V 0.36-0.53 (p<.0001 Bonferroni). Hovering and vertical circles elicited "watch/observe".
- Quote: "simpler motions are more likely to have consistent interpretation across participants."
- Relevance: pure-motion states are readable at ~40-60% agreement; hover-and-watch is the attention idiom for a faceless body.

### 2.3 Bretin, Khamis, Cross, Obaid (2025) - "The Role of Drone's Digital Facial Emotions and Gaze in Shaping Individuals' Social Proxemics and Interpretation" (ACM THRI)
- URL: http://www.mkhamis.com/data/papers/bretin2025thri.pdf (PDF read via pdftotext).
- VR drone with a digital face; N=25 (26 recruited); gaze Follow vs Avert x emotions (Joy, Anger, Sadness; Surprise 76% and Fear 54%
  recognition excluded).
- Numbers: gaze main effect on minimum distance F(1,24)=7.153, p=0.039 (ges=0.004); within Anger F(1,24)=6.78, p=0.016; manipulation check
  "being watched" chi^2(4)=36.37, p=2.43e-07, Cramer's V=0.35; drone-experienced participants stood closer, e.g. back zone 0.61 m vs 0.80 m,
  g=1.29; women kept more distance (front 0.83 m vs 0.67 m, g=-0.86).
- Relevance: even a screen-face gaze on a drone is registered as "watching me" and pushes people back; effect on distance is small.

### 2.4 Jakobowsky, Abrams, Rosenthal-von der Putten (2023/2024) - "Gaze-Cues of Humans and Robots on Pedestrian Ways" (Int J Soc Robotics 16:311-325)
- URL: https://link.springer.com/article/10.1007/s12369-023-01064-3 (open access; read in full).
- Pepper with edited eyes, a six-wheeled headless delivery-robot mock-up with tablet eyes, and a human; video studies N=79 and N=128.
- Numbers: study 1 gaze-left reduced rightward skirting b=-0.94, p<.001 (gaze-right n.s., p=.69); study 2 (left-hand-traffic countries)
  left b=-0.34, p=.04 and right b=0.37, p=.02.
- Quote: gaze cues trigger complementary skirting "independently of the robot morphology."
- Relevance: a headless base with screen-eyes gets the same navigational-gaze effect as a humanoid; morphology is not the blocker.

## 3. Motion primitives: anticipation, slow-in/out, acceleration, timing

### 3.1 Takayama, Dooley, Ju (HRI 2011) - "Expressing Thought: Improving Robot Readability with Animation Principles"
- URL: https://www.leilatakayama.org/downloads/Takayama.Animation_HRI2011_prepress.pdf (PDF read via pdftotext; an earlier WebFetch
  summary of this PDF was wrong and is discarded).
- PR2 animations, online video study N=273; 2 (forethought) x 2 (reaction) between x 2 (success/failure) within.
- Numbers: forethought did NOT change description accuracy (keyword match F(1,271)=0.65, p=.42); it raised viewers' sureness 5.69 vs 5.20
  (F(1,255)=15.95, p<.00001), appeal 4.83 vs 4.27 (F(1,265)=16.51, p<.0001), approachability 5.05 vs 4.54 (F(1,262)=12.48, p<.0001).
  Goal-oriented reaction raised confidence 4.53 vs 4.14 (F(1,267)=7.51, p<.007) and "smart" 4.72 vs 3.86 (F(1,267)=28.12). Success vs
  failure: smart 4.74 vs 3.86 (F(1,797)=135.71). Scenario readability varied widely: opening door 0.84, requesting power 0.78, delivering
  drink 0.64, ushering 0.29.
- Relevance: anticipation buys *confidence and likeability*, not raw recognition; the act itself must be legible.

### 3.2 Kwon, Huang, Dragan (HRI 2018) - "Expressing Robot Incapability"
- URL: https://arxiv.org/abs/1810.08167 (PDF read via pdftotext).
- Simulated PR2 (OpenRAVE); attempt-then-rewind trajectories optimised to mimic the successful motion, vs the repeated-failure baseline.
  Timing study N=60 (58% ranked the chosen fast-attempt/moderate-rewind timing first); repetition study N=60 (N=3 attempts vs 1: ease of
  telling the goal F(1,58.14)=20.21, p<.0001; cause clarity F(1,63.64)=16.94, p=.0001); main study N=120 (24 per task, 12 per condition).
- Numbers: correct-goal selection 95% vs 60%; goal rating F(1,119)=19.43, p<.0001; goal ranking F(1,119)=30.69; ease of identifying the goal
  F(1,119)=602.38; cause rating F(1,119)=13.6, p=.0003; open-ended correct goal p=.0003, correct cause p=.0002; positive perception
  F(1,119)=182.31. Motion computed in "a fraction of a second when the base does not move".
- Relevance: load-bearing for "look back when lost". Legible help-seeking = visibly attempt the goal, rewind, repeat (~3x), then orient
  to the owner. Recognition of *what* and *why* jumps from chance-ish to ~95%.

### 3.3 Schulz, Holthaus, Amirabdollahian, Koay, Torresen, Herstad (2019) - "Differences of Human Perceptions of a Robot Moving using Linear or Slow in, Slow out Velocity Profiles When Performing a Cleaning Task"
- URL: https://arxiv.org/abs/2003.11443 (PDF read via pdftotext).
- Fetch robot in a home lab; N=38 (19 F, 19 M; 18-80 y, mean 37.4); 152 encounters; Godspeed; Wilcoxon + Holm-Bonferroni.
- Numbers: no series reached significance. Example items: Unpredictable-Predictable linear 3.96 (CI 3.71-4.16) vs slow-in/out 3.70 (3.42-3.89);
  Incompetent-Competent 3.84 vs 3.78; Perceived Safety alpha=0.63.
- Relevance: easing alone, on a base translation, is not perceived. Do not expect slow-in/out by itself to make a "look" read as a look.

### 3.4 Saerbeck, Bartneck (HRI 2010) - "Perception of Affect Elicited by Robot Motion"
- URL: https://www.bartneck.de/publications/2010/perceptionAffectElicitedRobotMotion/saerbeckBartneckHRI2010.pdf (PDF read via pdftotext).
- Roomba (external motion) and iCat (internal head motion); N=18 (10 M, 8 F; 20-45 y); 3 acceleration x 3 curvature x 2 embodiments.
- Numbers: acceleration -> arousal F=114.112, p<.001, partial eta^2=.870; curvature -> arousal F=19.546, eta^2=.535; curvature -> valence
  F=15.726, eta^2=.481; acceleration -> valence n.s. (F=.755); embodiment main effects n.s. (arousal F=.230, p=.638; valence F=2.018,
  p=.174).
- Relevance: arousal is read from acceleration, and the Roomba (no head) is read the same as the cat-head. The act-token stream should
  encode *acceleration class*, not only pose.

### 3.5 Hu, Huang, Sivapurapu, Zhang (Apple, 2025) - "ELEGNT: Expressive and Functional Movement Design for Non-anthropomorphic Robot"
- URL: https://arxiv.org/abs/2501.12493 (full HTML read).
- 6-DoF arm with a lamp head (light, projector, camera); no face. Within-subject video study N=21 (8 F, 12 M, 1 undisclosed; 26-51 y), six
  tasks, function-only vs expression+function, six 0-100 metrics.
- Primitives: intention = "briefly turn its head toward a target before moving to reach or interact with it"; attention = "looking toward
  the user can signal attention"; attitude = nodding, head shaking, hesitation pauses; emotion via light/bouncy vs slow movement.
- Numbers: overall expression-driven M=56.16 vs function-driven M=28.77 (SD 27.15), t=19.85, p<.0001; per metric t: character 10.58,
  human-likeness 9.32, engagement 8.80, connection 8.50, willingness 7.37, intelligence 5.22 (all p<.001). Social tasks (music, conversation,
  reminders) significant on all metrics; functional tasks n.s. on intelligence/willingness/engagement. Older age -> lower preference
  (p<.001); roboticists rated lower (p=.006).
- Quote (participant): "when it looked at the person for feedback, as if saying 'is this good?'"
- Relevance: an orientation-only "look" on a faceless effector is read as attention and even as a question - the exact "look back" idiom.
  Caveat: the lamp has a distinct head-like end-effector; the Go2's "front" is the whole body.

### 3.6 Schulz, Torresen, Herstad (2019, ACM THRI 8(2)) - "Animation Techniques in HRI User Studies: a Systematic Literature Review"
- URL: https://arxiv.org/abs/1812.06784 (abstract read). 27 articles; four reported benefits: better interaction quality, better perceived robot
  qualities, better understanding of intent, clearer state/emotion; helps robots "lacking humanoid or robot-like appearance".

### 3.7 Pan, Knoop, Bacher, Niemeyer (Disney Research, IROS 2019) - "Fast Handovers with a Robot Character: Small Sensorimotor Delays Improve Perceived Qualities"
- URL: https://la.disneyresearch.com/publication/fast-handovers-with-a-robot-character-small-sensorimotor-delays-improve-perceived-qualities/
  (page read; N not on the page). 3x3 speed x delay; RoSAS; no delay -> "more discomforting", long delay -> "less warm"; a human-like
  small delay was best.
- Relevance: reaction latency is itself a primitive; an instant "look" reads worse than a ~human-latency one.

## 4. Human perception background: body orientation as a gaze cue
- Moors, Germeys, Pomianowska, Verfaillie (2015) Frontiers in Psychology, https://pmc.ncbi.nlm.nih.gov/articles/PMC4485307/ (read).
  Exp 1 N=7: with the head at 40 deg, a misaligned body shifted perceived gaze to 48.7 deg vs 41.1 deg aligned (~7.6 deg overshoot).
  Conclusion: "body orientation is indeed used as a cue to determine where another person is looking." Summarises Hietanen (1999, 2002):
  reflexive cueing occurs when head and body are *incongruent*; congruent head+body produced no cueing.
- Pomianowska, Germeys, Verfaillie, Newell (2012) Frontiers Integr. Neurosci., https://www.frontiersin.org/journals/integrative-neuroscience/articles/10.3389/fnint.2012.00004/full
  (read). N=11 Simon task; task-irrelevant body orientation (30/60 deg) produced a reverse compatibility effect of 11 ms (95% CI 4.4-16.9),
  F(1,10)=14.756, p<.01: body orientation automatically activates directional codes in an allocentric frame.
- Implication: a whole-body turn (head and body congruent) is the *weakest* human gaze cue; humans read "attention" mostly from the
  head/eyes being offset from the body. A neckless robot can only produce the congruent case, so it needs a secondary front marker
  (eyes/LEDs/screen) or a temporal signature (brief re-orient, pause, re-orient back) to substitute for the head/body offset.

## 5. Head/face add-ons for the Go2 (cost, DoF)
- Unitree official accessories page (https://shop.unitree.com/collections/accessories, read): Go2 battery from $500, charger from $100,
  controller $300. No head, face, screen or pan-tilt item.
- RoboStore Go2 accessories (https://robostore.com/collections/unitree-go2-accessories, read): battery from $560, self-charging board
  $1,050, remote $375, Livox Mid-360 $3,800, Hesai XT16 $6,650, D1 arm $4,655, Z1 arm from $11,900, D1-T teleop kits from $12,000.
  No PTZ/head/screen item.
- Go2 Enterprise Plus MTPTZ U3 (https://robostore.com/products/unitree-go2-enterprise-plus-mtptz-u3, read): $22,725 for the whole robot;
  3-axis stabilised gimbal, pan -270..+270 deg, pitch -90..+25 deg, roll +/-45 deg, 1080p dual-light + 640x512 thermal, jitter +/-0.01 deg;
  15 kg total; not sold separately. Same gimbal on Go2-W Inspection (https://www.roboworks.net/store/p/unitree-go2-w, read): from $20,695.
  This is an inspection camera on a different SKU, not an expressive head, and it is nose-mounted with no eyes.
- Research heads on robot dogs (both 2026, both N=6):
  - Kim, Oh, Park, Park, HRI Companion 2026, "Toward Empathetic Robotic Dogs for Joint Attention Support in Autism Intervention",
    https://dl.acm.org/doi/10.1145/3776734.3794367 (ACM page 403; abstract read via Semantic Scholar API). "custom pan-tilt head and
    on-device facial emotion recognition"; within-subjects pilot, six neurotypical adults; "directional cues easy to interpret", but
    "subjective 'shared attention' was inconsistent", "need for smoother and more predictable gaze and motion timing". No cost/DoF detail.
  - Fang et al., CHI 2026, "Take the Dog to the Park", https://dl.acm.org/doi/10.1145/3772318.3791944 (ACM 403; abstract via Semantic
    Scholar API; search index adds "custom 2-DoF head ... vertical nodding and horizontal shaking" - that detail is from the index snippet,
    not read). Four-week deployment with six autistic children; JA improvements reported qualitatively.
- Naderi et al. 2025, arXiv:2512.13981 (https://arxiv.org/abs/2512.13981, PDF read): Go2 Edu + K1 arm + RoboSense Helios-32 + "a small
  monitor/speaker used for participant-facing expressions" (glad/sad faces + apology). N=30; trust recovery 44% (delivery) / 38% (info).
  Monitor size/cost not given. Shows the cheap alternative to a head: a screen-face + speaker on the body.
- DIY shells: Thingiverse "Unitree Go2 AlmostDynoMutt head" (https://www.thingiverse.com/thing:7078719; page is JS-rendered, only the
  search-index snippet was readable: static clip-on PLA shell, 8x M3 screws, ears broke on falls, no servos). GitHub mvrius/go2-vision-head
  (https://github.com/mvrius/go2-vision-head, read): static STL shell for dual RealSense D455f, BSD-2, 1 commit, WIP - no actuation.
- Net: there is no commercial expressive or pan-tilt head for the Go2 EDU. A 2-DoF servo head is a parts-level DIY item that two labs
  built and validated only at N=6.

## 6. Not read / dropped
- Cha, Kim, Fong, Mataric (2018) survey of nonverbal signalling for non-humanoid robots: USC PDF hosts failed (cert expired / 403). Not cited.
- Sirkin, Mok, Yang, Ju (HRI 2015) Mechanical Ottoman: only metadata via Semantic Scholar (abstract elided); ACM/DeepDyve/RG blocked. Not cited
  for numbers.
- Gielniak & Thomaz "Anticipation in robot motion" (RO-MAN 2011): the fetched Gatech PDF was the IJRR human-likeness paper, not the
  anticipation study. Dropped.
- Go2 price snippets ($1,600 Air / $2,800 Pro / EDU quote-only) came from a search index only; not verified here.

## 7. What this means for Parcel

1. A body-yaw look *will* be read as attention/engagement. Three independent lines say so on headless bodies (Care-O-bot eta^2~.5, N=119;
   Go2 attentiveness warmth 6.8 vs 3.4, N=80; Spot body cues ~44% vs ~14%, N=210). The behaviour model can treat "orient body to owner"
   as a real attention act-token, not a placeholder for a head we do not have.
2. The look is weak on *target* and *confidence*. Orientation-only addressee identification was 37.5% (N=22); body cues lowered viewer
   confidence below baseline on Spot. In the full-duplex model, a look-token should co-fire with a speech or vocal token ("hm?", the owner's
   name) - audio alone reached ~82% on the same Spot stimuli - or with a front marker (eyes/LED strip) that defines a face.
3. Because humans read attention from head/body *incongruence* (Hietanen; 11 ms reverse-compatibility; 7.6 deg overshoot), and the Go2 can
   only produce congruent whole-body turns, the temporal signature must do the head's job: brief re-orient toward the owner, hold, return.
   Follow/approach plus a body-pitch "shake" was the Go2 attentiveness cue that worked; sideways alignment and silent stillness read as
   unpredictable/suspicious (Spot).
4. "Look back when lost" should be built as legible incapability, not as a static glance: attempt the navigation goal, rewind, repeat ~3x,
   then orient to the owner and vocalise. That recipe moved goal/cause recognition from 60% to 95% (N=120). This gives the learning loop an
   observable event (the attempt-rewind pattern) that precedes the owner's help.
5. Timing primitives that matter: acceleration class (arousal, eta^2=.87), forethought pause before the act (sureness/appeal, N=273),
   human-like reaction latency (Disney handovers). Slow-in/out alone did nothing measurable (N=38). The act-token vocabulary should carry
   a 2-3 level acceleration/arousal dimension and an explicit "anticipation pause" token.
6. A sustained stare costs proximity (+0.19 m on Spot; FROG visitors stood far more often when faced; drone gaze p=.039). Companion looks
   should be short and followed by re-engagement with the task; the reward model should not learn "stare at owner" as the attention
   optimum.
7. Hardware: no commercial expressive head exists for the Go2; the $20k+ PTZ is an inspection gimbal on a different SKU. The realistic
   options are (a) body-only looks plus a cheap front marker (LED eyes or a small screen like Naderi et al.'s monitor/speaker), or (b) a DIY
   2-DoF servo head, which two labs built and validated only with N=6. Option (a) is compatible with the current no-hardware state and
   with the sim-first plan; option (b) is a week-3-plus item if body-only looks fail an in-house legibility test.
8. Evidence gap to close in-house: no study isolates a body-yaw/pitch "look" on a headless Go1/Go2 with a recognition rate. A 30-60 person
   video study (body-look vs look+vocal vs look+eyes, 3-4 scenarios, next-intent forced choice + confidence) would replicate the Spot 2026
   design on our own morphology and set the acceptance bar for the act-token stream.
