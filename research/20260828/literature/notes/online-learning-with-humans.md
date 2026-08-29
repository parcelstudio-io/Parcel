# Safe online / interactive learning of robot behavior from sparse human feedback

Research note for Parcel, 2026-08-28. Topic: the mechanism by which a companion dog can LEARN
"chuckle when the joke was funny" and "look back at the owner when it gets lost" from a few real
interactions, without giving up the deterministic safety layer.

Method: every source below was located with web search and then READ (arXiv abstract/HTML/ar5iv
page, publisher page, vendor page, or the PDF converted locally with `pdftotext`). Numbers are
copied from the text that was read; where a number could not be verified it is marked as such.
Search budget for this session was exhausted after the discovery phase, so a few candidate sources
(e.g. "Agile But Safe" details, Vintix details) were verified by fetching their arXiv HTML directly.

Sections:
1. Preference-based RL (Christiano 2017 -> PEBBLE -> SURF/RUNE -> B-Pref/RIME -> few-shot/meta -> ICPL)
2. Human evaluative feedback (TAMER, COACH, Deep COACH)
3. Bandits and Thompson sampling (theory, deep-bandit practice, a 12-day public HRI deployment, an in-home SAR RL personalization study)
4. In-context RL (Algorithm Distillation, DPT, Vintix, the ICRL survey, LLM ICRL "Reward is Enough")
5. LLM/VLM-as-reward and language-feedback-to-policy (RL-VLM-F, Large Reward Models, YAY Robot, RT-H, OLAF, APO)
6. Safe learning on real legged robots (Yang et al. 2022, Agile But Safe 2024)
7. Continual learning without forgetting for small policies (Liu et al. 2026)
8. Pet-like products: what they actually learn (aibo ERS-1000, MiRo, Loona, Vector)
9. Perception building block for the "funny" reward: laughter detectors
10. Sample-efficiency table
11. What this means for Parcel: the most sample-efficient credible design for the two target behaviors
12. Open questions

---

## 1. Preference-based RL

### 1.1 Christiano et al., "Deep Reinforcement Learning from Human Preferences" (NeurIPS 2017)
- URL read: https://ar5iv.labs.arxiv.org/html/1706.03741 (arXiv 1706.03741)
- What it is: the canonical RLHF-for-control paper. A reward model is fit to pairwise comparisons
  of 1-2 s trajectory clips; the policy (TRPO/A2C) optimizes the learned reward.
- Numbers:
  - MuJoCo: 350, 700, 1,400 synthetic comparisons compared; 700 real-human comparisons used.
  - Atari: 5,500 human comparisons; raters spent 3-5 s per comparison, "between 30 minutes and 5 hours" total.
  - Novel behaviors: Hopper backflip "900 queries in less than an hour"; Half-Cheetah on one leg 800 queries; Enduro ~1,300.
  - Human labels cover "less than 1% of our agent's interactions with the environment".
  - Reward net for robotics: 2 hidden layers x 64 units, leaky ReLU (alpha = 0.01).
- Assessment: the baseline order of magnitude for learning a NEW motor behavior from scratch with
  preferences is ~10^3 comparisons. Too many for a home owner; every later method is about cutting this.

### 1.2 PEBBLE (Lee, Smith, Abbeel, ICML 2021)
- URLs read: https://arxiv.org/abs/2106.05091 and https://ar5iv.labs.arxiv.org/html/2106.05091
- What it is: off-policy (SAC) preference RL with unsupervised pre-training (10K steps of intrinsic
  exploration) and relabeling of the whole replay buffer whenever the reward model changes; reward
  ensemble of 3; disagreement-based query selection.
- Numbers (simulated teacher): Walker-walk / Quadruped-walk / Cheetah-run at 400, 700, 1,400 queries;
  Meta-world Door Open, Window Open, Button Press, Drawer Close at 2,500 / 5,000 / 10,000; Drawer Open and
  Sweep Into at 25,000 / 50,000. Segment length 50 steps (DMControl), 10 (Meta-world); feedback every
  20K steps (DMControl); M = 140/70/40 queries per session depending on budget. With 1,400 queries
  PEBBLE "reaches the same performance as SAC" on locomotion while Preference PPO cannot match PPO even at 2,100.
- Numbers (REAL humans, the authors): Cart-pole "winding/waving" 50 queries; Quadruped waving a leg
  200 queries; Hopper backflip 50 queries; at most 1 hour of human time; clips shown as 1-second videos.
- Assessment: LOAD-BEARING. Shows that a single expressive behaviour that is easy to judge visually
  ("wave a leg", "backflip") can be taught with 50-200 comparisons in under an hour when the agent
  already has diverse exploration data. Our chuckle / look-back primitives are of this kind.

### 1.3 SURF (Park et al., ICLR 2022)
- URL read: https://arxiv.org/abs/2203.10050 (PDF converted locally)
- What it is: PEBBLE + pseudo-labelling of unlabeled clip pairs (confidence threshold tau = 0.99, 0.999
  for Window Open / Sweep Into / Cheetah) + temporal cropping augmentation (segments of 54-60 steps
  cropped to 45-55 / 48-52); unlabeled batch ratio mu = 4, 10x unlabeled samples drawn per feedback session.
- Numbers: on Window Open, SURF with 400 queries matches SAC while PEBBLE "needs 2,500 queries ...
  about 6 times more"; "~100% of success rate on complex robotic manipulation task using only a few
  hundred preference queries, while its baseline method only achieves ~50%"; query-size ablation over
  N in {50, 100, 200, 400}; Walker-walk experiments with 100 queries; Meta-world budgets 10000/50,
  4000/20, 2000/25, 400/10 (total/per-session); DMControl 100 and 1,000.
- Assessment: cheap, orthogonal 3-6x label saving. Anything we build should pseudo-label the huge
  unlabeled stream of the dog's own behaviour clips.

### 1.4 RUNE (Liang, Shu, Lee, Abbeel, ICLR 2022)
- URL read: https://arxiv.org/abs/2205.12401 (PDF converted locally)
- What it is: exploration bonus = standard deviation across the reward-model ensemble; total reward =
  mean ensemble reward + beta * std. Improves both feedback- and sample-efficiency on Meta-world.
- Numbers: the abstract and intro give no absolute budgets; the paper's claim is relative improvement
  over PEBBLE at equal feedback. (Not extracted numerically here; treat as qualitative.)
- Assessment: minor. For a bandit-style behaviour selector the analogue is simply Thompson sampling.

### 1.5 B-Pref (Lee, Smith, Dragan, Abbeel, NeurIPS D&B 2021)
- URLs read: https://arxiv.org/abs/2111.03026 and https://ar5iv.labs.arxiv.org/html/2111.03026
- What it is: benchmark with SIMULATED IRRATIONAL TEACHERS: rationality beta (Oracle beta -> inf,
  Stoc beta = 1), myopia gamma (1.0 default, 0.9 myopic), mistake probability epsilon (0 default,
  0.1 "Mistake"), skip and equal thresholds.
- Numbers: budgets DMControl 2000/200, 1000/100, 500/50 (total/per session); Meta-world 20K/100,
  10K/50. Headline: "existing methods often suffer from poor performance when teachers provide wrong
  labels (Mistake and Stoc)"; PEBBLE and PrefPPO degrade substantially already at epsilon = 0.1.
- Assessment: LOAD-BEARING for risk. A home owner's implicit "was that funny" signal will be far
  noisier than 10%; naive preference learning will break.

### 1.6 RIME (Cheng et al., 2024, arXiv 2402.17257v4)
- URL read: https://arxiv.org/html/2402.17257v4
- What it is: denoising discriminator for preference RL (KL-divergence lower bound tau_lower keeps
  trustworthy samples; upper bound tau_upper flips very unreliable labels) + warm-started reward model.
- Numbers: noise epsilon in {0.1, 0.15, 0.2, 0.25, 0.3}; budgets Walker 500-1000, Button Press 10-20K,
  Hammer up to 80K at epsilon = 0.3. At epsilon = 0.3: Walker PEBBLE 431 +/- 157 vs RIME 741 +/- 139;
  Button Press 22.0 +/- 13.8 vs 80.0 +/- 27.7 (% success); Hammer 8.6 +/- 4.8 vs 58.5 +/- 42.0.
  Human study: 5 non-expert annotators on Hopper produced ~40% annotation error; RIME beat PEBBLE.
- Assessment: the real-human error rate (~40%) is the number to plan around; label filtering is mandatory.

### 1.7 Few-Shot Preference Learning for Human-in-the-Loop RL (Hejna, Sadigh, CoRL 2022)
- URLs read: https://arxiv.org/abs/2212.03363 and https://ar5iv.labs.arxiv.org/html/2212.03363
- What it is: MAML meta-learned reward-model prior over prior tasks; adapt to a new task with few queries.
- Numbers: "reduce the amount of online feedback needed to train manipulation policies in Meta-World
  by 20x" vs PEBBLE (PEBBLE used up to 25,000; this method ~100-500 depending on task). Human study:
  one expert user, budgets 36-100 queries per task on Meta-World/DMControl. Real Franka Panda reach
  (within 2.5 cm) / push (5 cm) using reward priors transferred from simulation.
- Assessment: LOAD-BEARING. The recipe "pre-train the reward/behaviour prior in simulation over many
  variants of the behaviour, then adapt with tens of owner labels" is the only preference-RL route
  whose label count fits a household.

### 1.8 ICPL: Few-shot In-context Preference Learning via LLMs (2024, arXiv 2410.17233)
- URL read: https://arxiv.org/html/2410.17233
- What it is: GPT-4 writes K = 6 candidate reward functions; policies are trained; the human ranks
  videos; the LLM rewrites rewards; N = 5 iterations.
- Numbers: 49 human queries total vs baselines at 150 / 1,500 / 15,000; "over a 30 times reduction";
  9 IsaacGym tasks + HumanoidJump; e.g. Ant ICPL 12.04 vs PrefPPO-49 0.743 vs PEBBLE-15k 8.543;
  Humanoid 9.227 vs 0.457 vs 6.162. Human study: 7 volunteers labelling, 20 evaluators; 17/20 preferred
  the ICPL humanoid-jump agent; < 1 day per experiment. Proxy runs used GPT-4-0613, human runs GPT-4o.
- Assessment: the strongest "LLM as reward author + human as ranker" result. The pattern maps to
  Parcel's hosted text-model budget: a handful of hosted calls per iteration, not per step.

### 1.9 Learning Human-Robot Handshaking Preferences for Quadruped Robots (Chappuis, Bellegarda, Ijspeert, 2024)
- URL read: https://arxiv.org/abs/2406.19893 (PDF converted locally)
- What it is: a Unitree Go1 balances on three legs and shakes with the fourth; the handshake is a CPG
  parameterised by amplitude, frequency, stiffness, duration; active preference-based reward learning
  with the APReL library from BINARY comparisons.
- Numbers: 10 binary choices per user; 25 subjects; 76% happy with the identified optimal handshake,
  20% neutral; optimized handshakes reduced amplitude error vs random/test handshakes (33% / 51% / 47%
  mean amplitude errors quoted for the comparison handshakes).
- Assessment: LOAD-BEARING for feasibility on our exact platform class: a per-owner social-motion
  preference on a Unitree quadruped was learned from 10 comparisons. Parameterise chuckle / look-back
  as low-dimensional primitives and learn per-owner parameters the same way.

---

## 2. Human evaluative feedback (scalar praise/scold)

### 2.1 TAMER (Knox, Stone, K-CAP 2009)
- URL read: https://www.cs.utexas.edu/~pstone/Papers/bib2html/b2hd-KCAP09-knox.html (PDF converted locally)
- What it is: the agent models the human's reinforcement H(s,a) and greedily takes argmax_a H; credit
  is assigned to recent time steps with a gamma(2.0, 0.28) delay density (Tetris) or Uniform(0.2, 0.6) s
  (Mountain Car); human reaction assumed >= 0.2 s.
- Numbers: 9 humans trained Tetris agents, 19 trained Mountain Car agents; at least a quarter of
  trainers could not program. Tetris: TAMER 65.89 lines/game by game 3, vs RRL-KBR 50 lines after ~120
  games, Sarsa(lambda) ~30 lines after hundreds of games. Mountain Car actions every ~150 ms.
- Assessment: scalar praise can shape a behaviour in a handful of episodes when the state space is
  small. The weakness appears in COACH below.

### 2.2 COACH (MacGlashan et al., ICML 2017)
- URL read: https://proceedings.mlr.press/v70/macglashan17a.html (PDF converted locally)
- What it is: human feedback is POLICY-DEPENDENT (people reward improvement, show diminishing returns,
  and treat silence as meaningful). COACH interprets feedback as the advantage function and does
  actor-critic updates with eligibility traces (lambda = 0.95 for +/-1, 0.9999 for +4), feedback-action
  delay d = 6 steps = 0.198 s.
- Numbers: 5 behaviours on a TurtleBot (navigate to ball, back away when near, alternate between
  ball and cylinder, "lure" training, stay/forward) "each ... trained in less than two minutes".
  TAMER learned only the flat behaviours and "tended to forget behavior" (a weaker positive reward
  later can UNLEARN a previously reinforced action).
- Assessment: LOAD-BEARING for the reward semantics. An owner's laugh or "good dog" is a statement
  about the dog relative to what it usually does; the learner must treat it as an advantage/preference
  signal with a decay window (~0.2-2 s) rather than as an absolute reward.

### 2.3 Deep COACH (Arumugam, Lee, Saskin, Littman, 2019)
- URL read: https://arxiv.org/abs/1902.04257
- Numbers: pixel-input policies in Minecraft learned from "10-15 minutes of interaction" of live human
  critique. No robot. Treat as evidence that COACH scales to deep nets with minutes of feedback.

---

## 3. Bandits and Thompson sampling for behaviour selection

### 3.1 Agrawal, Goyal, "Thompson Sampling for Contextual Bandits with Linear Payoffs" (ICML 2013)
- URL read: https://proceedings.mlr.press/v28/agrawal13.html
- Numbers: high-probability regret O~( (d / sqrt(eps)) * sqrt(T^(1+eps)) ) for any eps in (0,1)
  (the paper's d^(3/2) sqrt(T) form); lower bound Omega(sqrt(dT)); resolves the Chapelle-Li COLT 2012 open problem.
- Assessment: with a d ~ 16-64 context embedding and a few arms, regret grows like sqrt(T): the
  cumulative "wrong chuckle" count over the first few hundred interactions is bounded and shrinks per step.

### 3.2 Riquelme, Tucker, Snoek, "Deep Bayesian Bandits Showdown" (ICLR 2018)
- URLs read: https://arxiv.org/abs/1802.09127 and https://ar5iv.labs.arxiv.org/html/1802.09127
- Numbers: 8 real datasets + synthetic; 25+ algorithm variants; ~10,000 contexts per run; 50 runs.
  Best overall: NeuralLinear (learned representation + exact Bayesian linear regression on the last
  layer) and exact-posterior linear models; methods needing long optimisation of their uncertainty
  underperform because "partially optimized uncertainty estimates can lead to catastrophic decisions".
- Assessment: LOAD-BEARING for the implementation choice: a Bayesian linear head over a frozen
  embedding (voice-LLM state + owner model + perception) is the right on-robot learner; it is
  closed-form, tiny, and its uncertainty is honest from the first sample.

### 3.3 Song, Okafuji, Ariu, Koike, "What you reward is what you learn" (Jan 2026, arXiv 2601.01969)
- URLs read: https://arxiv.org/abs/2601.01969 and https://arxiv.org/html/2601.01969
- What it is: a 28 cm Sota humanoid in a Japanese shopping mall runs Beta-Bernoulli Thompson sampling
  (alpha = beta = 1 prior) over 6 arms (speech rate slow/normal/fast x verbosity concise/detailed).
- Numbers: 12 days, ~8 h/day, > 1,400 encounters; per reward condition 30 cold-start + 450 bandit-active
  = 480 interactions; each arm pulled 5 times in cold start. Three binary rewards: Ru (Likert >= 6 of 7),
  Rc (conversation reached a closing routine), Rt (>= 2 turns). Results: under Ru Normal-Concise had the
  best success 63.3% (Normal-Detailed most selected, 50%); under Rc Normal-Concise 39.2% success / 30.8%
  selection, with Slow-Detailed and Fast-Detailed at 0%; under Rt Fast-Detailed 59.8% success and
  Slow-Concise most selected (42.4%). Context (group size, crowd) changed which arm worked.
- Assessment: LOAD-BEARING. This is the closest published analogue to "learn which social behaviour to
  emit online from sparse binary outcomes": ~480 pulls over 6 arms produced clearly separated posteriors,
  and the DEFINITION of the reward changed the learned policy. For Parcel the reward definition
  ("owner laughed within 3 s" vs "owner said something positive" vs "owner kept talking") must be
  fixed deliberately.

### 3.4 Clabaugh et al., "Long-Term Personalization of an In-Home SAR for Children with ASD" (Frontiers Robotics & AI 2019)
- URLs read: https://www.frontiersin.org/articles/10.3389/frobt.2019.00110/full and
  https://viterbischool.usc.edu/news/2020/02/socially-assistive-robot-helps-children-with-autism-learn/
- Numbers: 17 children (3-7 y); average 41 days; 14.10 sessions per child; 13.27 games per session;
  robot SPRITE/Kiwi (6 DOF). Hierarchical RL (Q-learning) with two controllers: level of challenge (1-5),
  level of feedback (1-4). Convergence "~100 episodes for challenge; 25-50 for feedback". Engagement
  65% average (70% when robot speaking); all 16 completers improved math (p < 0.01, d ~ 0.54).
  USC news: engagement detection 90% (7 participants); ~70% engagement within one minute of robot
  speech vs < 50% after a minute of silence.
- Assessment: an in-home, weeks-long RL personalisation that converged in 25-100 episodes per
  controller. This is the realistic time-scale for Parcel: a few dozen labelled events per behaviour.

---

## 4. In-context RL

### 4.1 Algorithm Distillation (Laskin et al., DeepMind, 2022; ICLR 2023)
- URLs read: https://arxiv.org/abs/2210.14215, https://ar5iv.labs.arxiv.org/html/2210.14215, PDF locally
- Numbers: causal transformer with 4 layers, 64-dim embeddings, 4 heads, FF 2048; context spanning
  2-4 episodes is needed for in-context RL to emerge; Dark Room (20-step episodes) and Dark Key-to-Door
  (50 steps): 2,000 learning histories from A3C (100 actors); Watermaze (50 steps): 4,000 histories
  from distributed DQN (16 actors); single-stream experiment: 2,048 Dark Key-to-Door tasks x 2,000
  episodes; AD matches RL^2 on Dark Room and is within 13% on Watermaze; "learns a more data-efficient
  RL algorithm than the one that generated the source data", though the source keeps slightly higher asymptote.
- Assessment: the learner can be TINY. A 4-layer/64-dim transformer that improves a discrete
  behaviour choice in-context after 2-4 episodes is trivially deployable on Orin, but it needs thousands
  of simulated learning histories of the SAME family of tasks - i.e. a simulator of owner reactions.

### 4.2 DPT: Supervised Pretraining Can Learn In-Context RL (Lee et al., 2023, arXiv 2306.14892)
- URL read: https://arxiv.org/abs/2306.14892
- Claim: training a transformer to predict the optimal action from in-context histories yields
  posterior sampling (Thompson sampling) behaviour; regret bounds show it "can learn faster than
  algorithms used to generate the pretraining data". No numbers extracted from the abstract page.
- Assessment: theoretical bridge between Sections 3 and 4: an ICRL model is an amortised Thompson sampler.

### 4.3 Vintix (Polubarov et al., 2025, arXiv 2501.19400)
- URLs read: https://arxiv.org/abs/2501.19400 and https://arxiv.org/html/2501.19400
- Numbers: 300M params, 24 layers, 16 heads, 1024 emb, 8192-token context; 87 tasks over MuJoCo (11),
  Meta-World (45), Bi-DexHands (15), Industrial-Benchmark (16); 1.6M episodes / 222.7M transitions;
  reaches ~0.95-0.97 normalised demonstrator score on training tasks after several in-context episodes;
  on genuinely new tasks 31-47% of expert on the successes and random-level on failures. Paper CC BY 4.0;
  code "to be released at dunnolab/vintix"; weights not stated as available.
- Assessment: cross-domain ICRL is real but 300M parameters, no weights, and weak novel-task transfer.

### 4.4 A Survey of In-Context RL (Moeini et al., 2025, arXiv 2502.07978)
- URL read: https://arxiv.org/html/2502.07978
- Taxonomy: supervised pretraining (AD, DPT-style) vs reinforcement pretraining. One cited method adapts
  in "only 300 interactions". Open problems: no sim-to-real demonstrations for robotics; multi-agent OOD.
- Assessment: ICRL on a physical robot is unproven in the literature. Treat as an experiment lane.

### 4.5 "Reward Is Enough: LLMs Are In-Context Reinforcement Learners" (Song, Moeini, et al., ICLR 2026)
- URL read: https://arxiv.org/pdf/2506.06303 (v6, converted locally)
- What it is: ICRL prompting - after each response the LLM receives a scalar reward; the next prompt
  concatenates all prior responses + rewards; quality improves as context grows, even when the SAME
  LLM generates the reward.
- Numbers (GPT-4.1 as both policy and reward): Game of 24 running-max success: CoT-only 6%, Long-CoT 47%,
  Reflexion 44%, Best-of-N 49%, Self-Refine 47%, ICRL Preset 90%, ICRL Autonomous 84%. Creative writing
  length-controlled win rates: 59.48% vs Reflexion, 78.36% vs Best-of-N, 86.32 +/- 3.03 vs Self-Refine;
  ICRL keeps improving over +50 extra episodes while Self-Refine plateaus then declines. ScienceWorld
  30 tasks with GPT-4.1-mini.
- Assessment: the ZERO-TRAINING route for the hosted text model: keep the last N (joke, reward)
  pairs in the prompt and the model re-weights its humour choices. Works for text decisions; not a
  motor learner.

---

## 5. LLM/VLM-as-reward and language feedback into policies

### 5.1 RL-VLM-F (Wang et al., ICML 2024)
- URL read: https://arxiv.org/html/2402.03681
- What it is: a VLM (Gemini-Pro; GPT-4V for cloth) answers PREFERENCE queries between image pairs
  given a text goal; a reward model is learned from those labels (PEBBLE-style).
- Numbers: 40-100 VLM queries per session; query frequency every 1,000-5,000 steps; caps 500 (Fold
  Cloth), 10,000 (CartPole), 12,000 (rope, water), 20,000 (drawer, soccer, sweep). Outperforms VLM
  score, CLIP, BLIP-2, RoboCLIP on all 7 tasks; matches or beats ground-truth-preference training on 6/7;
  label accuracy rises with the visual difference between the two images.
- Assessment: a VLM can replace the owner as the labeller for PRE-training in simulation (e.g. "which
  clip looks more like a chuckle / more like checking back on the owner"), with 10^3-10^4 hosted calls.

### 5.2 Large Reward Models (Wu et al., 2026, arXiv 2603.16065v2)
- URL read: https://arxiv.org/html/2603.16065v2
- Numbers: Qwen3-VL-8B-Instruct + LoRA, three reward heads (temporal contrastive, absolute progress,
  task completion) trained on 24 data sources; queried every K = 10 environment steps as a frozen online
  reward engine; ManiSkill3 SFT 56.88% -> 60.93%; real pick-and-place 38.3% -> 51.7% "within just 30 RL iterations".
- Assessment: an 8B VLM reward model fits on Orin 64 GB for OFFLINE/batched reward labelling; not 50 Hz.

### 5.3 Yell At Your Robot (Shi et al., 2024, arXiv 2403.12910)
- URL read: https://arxiv.org/html/2403.12910
- What it is: hierarchical policy; high-level (ViT with frozen CLIP + DistilBERT) emits language skill
  commands roughly every 4 s; low-level ACT (EfficientNet-b3, FiLM) executes; a human can yell a
  correction (USB mic -> Whisper), the correction overrides the high-level command in real time, and the
  (observation, correction) pairs are added to the high-level dataset for fine-tuning. Saves data from
  2 s before the intervention for context.
- Numbers: ALOHA bimanual, 14-D actions, 50 Hz; base datasets 1,170 / 317 / 265 trajectories; the
  correction data added over 2-3 iterations was only 4.8% / 4.2% / 10.8% of the base data; real-time
  corrections raised success 15% -> 50%; after fine-tuning on corrections 15% -> 45%; per-task gains
  15-45 points; 20 trials per evaluation.
- Assessment: LOAD-BEARING for the "look back when lost" behaviour: an owner saying "look at me" /
  "I'm over here" is exactly a high-level language correction; tens-to-hundreds of such events
  (single-digit percent of base data) moved success by 20-45 points.

### 5.4 RT-H: Action Hierarchies Using Language (Belkhale et al., RSS 2024)
- URL read: https://arxiv.org/html/2403.01823
- Numbers: PaLI-X 55B with frozen 22B ViT; ~100K demonstrations (70K kitchen, 30K diverse), > 2,500
  automatically extracted language motions; +15% average over RT-2 on 8 tasks; with a human typing
  language-motion corrections success is "near-perfect"; training on 30 correction episodes per task
  (RT-H-Intervene) lifted average success 40% -> 63%, while teleoperated corrections (RT-2-IWR)
  DEGRADED it 25% -> 13%.
- Assessment: language corrections are more sample-efficient than teleop corrections; 30 episodes per
  task is the number. Model size is irrelevant to us; the data-shape lesson transfers.

### 5.5 OLAF: Interactive Robot Learning from Verbal Correction (Liu et al., 2023, arXiv 2310.17555)
- URL read: https://arxiv.org/abs/2310.17555 (PDF converted locally)
- What it is: user stops the robot and says what it should have done; GPT-4 (temperature 0.5) is
  queried ONCE per correction to relabel the 1-2 s pre-intervention segment with a better action; the
  19M-parameter BC-transformer (ResNet-18, spatial softmax, GMM head, history 10) is retrained by
  imitation on the aggregated data.
- Numbers: sim (robomimic, Franka): M = 50 demos + N = 100 correction trajectories; verbal-only Table I:
  Pick Place Can 73.6 -> 84.6, Threading 53.3 -> 60.5, Square 41.0 -> 59.0, Coffee Machine 16.0 -> 51.0
  (long feedback). Real Franka, M = 40 + N = 80: PickPlace-Bin 35.3 -> 73.5, PickPlace-Drawer-Basket
  52.9 -> 70.6. Average +20.0 points; verbal-only +17.8. Corrections typed; they "envision" Whisper.
- Assessment: LLM-relabelled verbal corrections, ~80-100 events, lift a small policy by 20-40 points.

### 5.6 APO: Human-assisted Robotic Policy Refinement via Action Preference Optimization (Xia et al., 2025)
- URLs read: https://arxiv.org/abs/2506.07127 and https://arxiv.org/html/2506.07127
- Numbers: OpenVLA (also pi0-FAST); last K = 10 actions before an intervention marked undesirable;
  50 trajectories per RoboMimic task: base 40.5% -> 48.0% (DAgger 39.0, KTO 43.5, TPO 41.5); real
  insertion with 20 interaction trajectories: 65% -> 85%, position-disrupted 25% -> 55%, background 10% -> 30%.
- Assessment: DPO-style "these last 10 actions were bad" from 20 real interventions is a viable
  update rule for a small policy head.

---

## 6. Safe learning on real legged robots

### 6.1 Safe Reinforcement Learning for Legged Locomotion (Yang, Zhang, Luu, Ha, Tan, Yu, 2022)
- URL read: https://arxiv.org/abs/2203.02638
- What it is: learner policy + safe recovery policy; a switch activates recovery when safety
  constraints are about to be violated and hands back control when clear, "minimally intervening".
- Numbers: 48.6% fewer falls in simulation vs baselines; fewer than 5 falls over 115 minutes of
  real-hardware learning; learned efficient gait 34% more energy-efficient, catwalk 40.9% narrower
  feet, two-leg balance 2x longer.
- Assessment: LOAD-BEARING for the safety architecture: online learning on a real quadruped was done
  with a fixed recovery controller holding the last word. Parcel's deterministic safety layer plays that role.

### 6.2 Agile But Safe (He et al., RSS 2024)
- URLs read: https://arxiv.org/abs/2401.17583 and https://arxiv.org/html/2401.17583
- Numbers: Unitree Go1; peak 3.1 m/s; agile policy + recovery policy switched by a learned reach-avoid
  value with V_threshold = -0.05; RA network trained on 200k agile-policy episodes; Isaac Gym 1,280 envs,
  PPO; 9-10/10 success across three real testbeds; onboard Jetson Orin NX; ray-prediction net 9 ms.
- Assessment: a learned safety value + recovery policy runs on an Orin-class board at real-time rates.

---

## 7. Continual learning without forgetting

### 7.1 Pretrained VLAs are Surprisingly Resistant to Forgetting (Liu, Kim, Liu, Liu, Zhu, 2026, arXiv 2603.03818)
- URLs read: https://arxiv.org/abs/2603.03818 and https://arxiv.org/html/2603.03818
- Numbers: LIBERO suites, 10 sequential tasks each. With 20% replay (1,000 samples): GR00T N1.5 (~3B)
  0.919 success / 0.027 NBT (negative backward transfer); pi0 (~3B) 0.768 / -0.016; BC-Transformer (~15M)
  0.585 / 0.245; BC-ViT (~15M) 0.508 / 0.193. With only 2% replay (100 samples): VLAs 0.1-0.2 NBT vs
  scratch policies 0.4-0.5. Sequential + EWC: NBT 0.6-0.8 (worse than replay). pi0 recovers peak in
  6.2-10.5% of the original steps; BC-Transformer 33-187%. Simulation only.
- Assessment: LOAD-BEARING for the update rule: a ~15M scratch policy forgets 20-25% of prior tasks
  even with 20% replay; EWC does not save it. Learn a small HEAD over a frozen backbone and always
  replay a buffer of past owner episodes; never fine-tune the whole motion policy online.

---

## 8. Pet-like products: what do they actually learn?

### 8.1 Sony aibo ERS-1000 (official Help Guide)
- URLs read: https://helpguide.sony.net/aibo/ers1000/v1/en-us/contents/TP0001970096.html (personality),
  .../TP0001970095.html (growth), .../TP0001970094.html (desires and emotions)
- Quotes: "aibo develops its personality through interactions and experiences with the owner ...
  turns out totally different over time"; personalities shown in the app include "Clingy" and "Wild";
  "changing your attitude toward your aibo or giving it a new toy may shift your aibo's personality";
  "it takes about 3 years for aibo to reach the maturity stage from the infancy stage" depending on
  interaction; "the pattern of tricks and the strength of desires change"; "When your aibo accomplishes
  something, give a lot of compliments. When your aibo gets into mischief ... teach it a lesson."
  Desires: affection, curiosity, sleep, "show feelings"; emotions "similar to delight, anger, sorrow and pleasure".
- Assessment: Sony documents a slowly-drifting personality/desire model steered by praise/scolding and
  a 3-year growth curve, but gives NO mechanism, no evaluation, and no claim of learning a new
  context-conditioned behaviour. The owner-facing evidence is the personality label in the app.

### 8.2 MiRo (Prescott, Mitchinson, Conran, HRI 2017 companion paper)
- URL read: https://eprints.whiterose.ac.uk/id/eprint/116446/1/HRI2017_final.2.pdf
- Facts: six senses, eight degrees of freedom, 6 h+ battery; "3B-CS" brain-based control: layered
  architecture with basal-ganglia-style action selection between competing behaviours; responds to
  stroking touch and sound; positioned as a research platform for "learning from reward" models.
- Assessment: no documented owner-specific online learning in the product; learning is a research option.

### 8.3 KEYi Loona (vendor guide, dated 2026-08-21)
- URL read: https://keyirobot.com/en-us/blogs/loona-tutorials/what-is-loona-petbot-a-complete-guide-to-smart-ai-robot-pet
- Claims: "learns from you and evolves over time", "actually remembers what you like over time",
  "Affective Computing" engine; 5 TOPS BPU; 720P RGB camera; "over 1,000 unique movements"; tracks
  "over 200 signals every minute"; "95% accuracy rate for spotting human feelings"; ChatGPT-backed chat.
- Assessment: marketing-level claims, no mechanism, no data. Not evidence.

### 8.4 Anki Vector (Pickr, 2018-08-13)
- URL read: https://www.pickr.com.au/news/2018/anki-connects-robots-with-personality-in-vector/
- Quote: "With a cloud system capable of adapting and learning, what he does next will be based on
  what he learns from the people that connect with him"; 120-degree camera, four mics, Qualcomm chip.
- Assessment: press-release language; nothing measurable.

Conclusion of Section 8: no shipped pet robot publishes a verifiable account of learning a
context-conditioned behaviour from owner feedback. Parcel can differentiate by LOGGING the posterior.

---

## 9. Perception building block for the "funny" reward

### 9.1 jrgillick/laughter-detection (Interspeech 2021 "Robust Laughter Detection in Noisy Environments")
- URL read: https://github.com/jrgillick/laughter-detection
- Facts: MIT licence; PyTorch (>= 1.3.1), librosa; models trained on Switchboard, evaluation annotations
  for AudioSet; CLI `segment_laughter.py --threshold 0.5 --min_length 0.2`; outputs laugh segments in seconds.
### 9.2 omine-me/LaughterSegmentation (Interspeech 2024 "Robust Laughter Segmentation with Automatic Diverse Data Synthesis")
- URL read: https://github.com/omine-me/LaughterSegmentation
- Facts: code MIT, weights "research use only"; model.safetensors ~1.26 GB; Python <= 3.11, torch 2.1.2;
  16 kHz WAV; GPU recommended (tested on RTX 2060 SUPER).
- Assessment: an owner-laughter event detector exists off the shelf (MIT for the 2021 one). Echo from
  the dog's own speaker and the XVF3800 beamformer output are untested here.

---

## 10. Sample-efficiency table (labels/episodes needed, as reported)

| Setting | Labels / episodes | Source |
|---|---|---|
| New motor behaviour from scratch, sim, preferences | 700-1,400 comparisons (MuJoCo), 900 for backflip | Christiano 2017 |
| Same, with off-policy + relabel + pretraining | 50-200 human comparisons, < 1 h (waving leg, backflip) | PEBBLE 2021 |
| + pseudo-labels/cropping | ~400 vs 2,500 (6x) on Window Open | SURF 2022 |
| + meta-learned reward prior | 36-100 human queries per task; 20x vs PEBBLE | Hejna & Sadigh 2022 |
| LLM writes rewards, human ranks | 49 queries (> 30x fewer) | ICPL 2024 |
| Per-owner social-motion parameters on a Go1 | 10 binary choices per user, 76% satisfied | Chappuis 2024 |
| Scalar praise, small state space | ~3 games (Tetris), < 2 min per TurtleBot behaviour | TAMER 2009, COACH 2017 |
| Bandit over 6 social arms, binary reward, public | 480 pulls per reward condition (30 cold start) | Song 2026 |
| In-home RL personalisation (Q-learning) | ~25-50 episodes (feedback), ~100 (challenge) | Clabaugh 2019 |
| Language corrections into a high-level policy | 4-11% extra data; 30 episodes/task; 80-100 corrections | YAY 2024, RT-H 2024, OLAF 2023 |
| Preference optimisation from interventions | 20 real interventions: 65 -> 85% | APO 2025 |
| In-context RL (tiny transformer) | improves within 2-4 episodes, after 2,000-4,000 sim histories | AD 2022 |
| Noise tolerance | epsilon = 0.1 already hurts; humans ~40% error | B-Pref 2021, RIME 2024 |

---

## 11. What this means for Parcel

### 11.1 Reframe the two targets as DECISIONS, not motions
Both "chuckle when funny" and "look back when lost" are discrete triggers of expressive primitives that
already exist (chuckle; look_around / turn-head-to-owner) or are trivially parameterised (amplitude,
duration, delay - exactly the CPG-parameter shape of Chappuis 2024). The learning problem is
"given the state of the world, should primitive P fire, and with which parameters" - a contextual
bandit / small policy head, not continuous RL over torques. This keeps every learned output inside
the set the deterministic safety layer already vets (Yang 2022 pattern: recovery controller has
final authority; ABS 2024 shows the same runs on an Orin NX).

### 11.2 The most sample-efficient credible design (recommended)
Layer A - frozen context encoder (no learning on-robot): concatenate (i) the duplex voice module's
utterance/semantic state (was a joke just told, by whom, sentiment), (ii) owner-model features
(consented facts: humour style, name), (iii) perception (owner face/voice bearing, time since owner
was last seen, LiDAR-lost flag), (iv) laughter-detector output (Section 9) and prosody, into a
d ~ 32-64 embedding.

Layer B - Bayesian linear (NeuralLinear) Thompson-sampling head per primitive (Riquelme 2018): arms =
{do nothing, chuckle-soft, chuckle-big, ...} and {keep going, glance back, turn and look back, stop
and look back}. Closed-form posterior updates, honest uncertainty from sample one, regret ~ sqrt(T)
(Agrawal-Goyal). Cold-start every arm a few times as Song 2026 did (5 pulls each).

Layer C - reward definition, fixed in advance (Song 2026: the reward IS the policy):
  - chuckle: binary success = owner laughter onset detected within a 0.2-3 s window after the
    owner's utterance ends (TAMER/COACH windows), OR an explicit positive utterance; penalise a
    chuckle that lands in silence or on a serious utterance. Treat the signal as ADVANTAGE-like
    (COACH): compare to the running baseline rate for that owner, do not treat silence as zero reward.
  - look back: success = owner re-acquired (face/voice bearing) within N seconds after the primitive
    fires, or owner utterance like "good, here" ; language corrections such as "look at me" go straight
    into Layer D.
  Filter labels RIME-style (drop low-confidence events; expect ~40% label error).

Layer D - language-correction channel (YAY / RT-H / OLAF): the owner's spoken corrections
("look back when you lose me", "don't laugh at that") are transcribed (Whisper is already the pattern),
relabel the last 2 s of context, and are appended to a small replay dataset that (re)fits the Layer-B
priors and, later, a small high-level policy head. Budget: tens of corrections move policies 20-45 points.

Layer E - simulation pre-training so the real-world count is tens, not thousands
(Hejna & Sadigh; ICPL; RL-VLM-F):
  - Build an owner-reaction simulator: an LLM plays the owner (hosted text budget), emitting jokes /
    non-jokes / getting lost, and a laugh/no-laugh label with a controllable error rate
    (B-Pref teacher model: beta, gamma, epsilon). Run thousands of episodes to learn the Layer-A
    encoder and a PRIOR for Layer B (meta-learned or simply a well-calibrated Gaussian prior).
  - Optionally distil the learning process into a tiny AD-style transformer (4 layers/64 dims)
    so the on-robot head adapts in-context within 2-4 episodes; but ICRL has no sim-to-real
    evidence (survey), so keep the Bayesian head as the primary path.
  - In MuJoCo/Isaac, tune the primitive parameters (chuckle amplitude, look-back turn rate) with
    VLM preference labels (RL-VLM-F) before any owner sees them.

Layer F - continual-learning rule: only Layer B/D heads update online; the backbone and the motion
policy stay frozen (Liu 2026: 15M scratch policies lose 20-25% of old tasks even with 20% replay;
EWC does not help). Keep a replay buffer of every labelled owner episode (2-20%) and refit heads
from it, never sequentially.

### 11.3 Expected numbers for Parcel
- Song 2026: 480 pulls separated 6 arms with Bernoulli rewards; Clabaugh 2019: 25-100 episodes per
  controller; Chappuis 2024: 10 comparisons for continuous parameters; PEBBLE humans: 50-200 comparisons.
  So plan for ~30-100 labelled events per behaviour per owner to get a confidently separated posterior,
  and ~10 comparisons for parameter styling. At a few jokes and a few "lost" events per day this is
  1-3 weeks of ordinary use, which is why Layer E (prior from simulation) is not optional.
- Hosted budget fits: Layer C/D use the hosted text model only per event (a few calls/day); Layer E
  simulation calls happen offline on the desktop; the on-robot learner is closed-form and runs on CPU.

### 11.4 What NOT to do
- Do not run PEBBLE/SAC-style preference RL on the real dog for these behaviours (10^2-10^3 clips
  plus exploration; the noise finding in B-Pref/RIME).
- Do not fine-tune the whole 50 Hz body-intent policy from owner feedback (forgetting; safety).
- Do not adopt Vintix-class ICRL (300M, no weights, weak novel-task transfer).
- Do not claim "personality learning" the way aibo/Loona do without a logged posterior and an
  A/B-able reward definition.

## 12. Open questions
1. Real event rates: how many jokes and how many "owner lost" episodes per day in a home? This sets
   wall-clock time to 30-100 labels.
2. Laughter detection on the XVF3800 with the dog's own speech playing (echo/AEC) - unmeasured.
3. Is owner feedback stationary? COACH shows feedback depends on the current policy; Song notes
   context dependence; the bandit may need discounting / contextual arms for time-of-day, mood.
4. What is the humour label noise for a single owner? RIME's 40% was for a motion task; humour may be worse.
5. Does a hosted-LLM "was that funny" judge agree with actual laughter? Needs a small paired dataset.
6. Simulating "lost": what perception signal (LiDAR track loss, face absence > t s) defines it, and
   can MuJoCo/Isaac produce a believable owner-motion generator?
7. Consent/privacy for logging owner laughter and corrections into the owner model (existing consent
   mechanism must cover reward logs).
8. ICRL sim-to-real is untested in the literature; if we try the AD-style head, it needs its own
   preregistered evaluation.
