# Gap note: credit assignment for delayed social rewards in continuous duplex streams

Date: 2026-08-28. Scope: 2023-2026 work on multi-turn / delayed-reward RL for dialogue and interactive agents, RL for full-duplex speech with timing rewards, and implicit-feedback reward learning from deployment data (Pang et al. 2023 and follow-ups), including reported reward-hacking failure modes. Every source below was fetched and read (arXiv HTML/abs, or the PDF converted with pdftotext); numbers are quoted from the source text. Two pre-2023 precedents (Jaques 2020, Inoue 2022) are included because they are the only works that use *laughter itself* as a reward or a timing target.

Design question this note serves: Parcel wants a full-duplex behaviour model (speech + body/act tokens on one clock) that learns "chuckle if the joke was funny" (reward = owner laughter, arriving seconds after the act) and "look back at the owner when lost" (needs an observable track-loss event). Both are *delayed, sparse, noisy social rewards landing on a continuous token stream*. The question is: who gets the credit, over what window, and what does the policy learn to exploit.

Not readable: "Reinforcement Learning Enhanced Full-Duplex Spoken Dialogue Language Models for Conversational Interactions" (COLM 2025, OpenReview id QbLbXz8Idp, method "ORISE"). OpenReview served a verification page to the fetcher and HTTP 403 to a direct download; it is listed on the Awesome-Full-Duplex-SDM index as OpenReview-only. It is **not** cited as a finding here.

---

## A. RL for full-duplex speech with timing rewards (the closest analogue to Parcel's stream)

### A1. DuplexPO — "Decoupling Conversational Dynamics in Full-Duplex Spoken Models through Reinforcement Learning"
- URL: https://arxiv.org/html/2607.07148v1 (arXiv 2607.07148, July 2026). Li, Wu, Lin, Lee, Qin, Chen, Chen — NTU (Singapore), NTU (Taiwan), HKUST, NVIDIA. License: arXiv non-exclusive; code not explicitly released (NeMo / Nemotron-VoiceChat recipe referenced). Demo: https://liyuxin44.github.io/DuplexPO/
- Base: Nemotron-VoiceChat = Qwen2.5-7B-Instruct + 600M Parakeet streaming encoder + CosyVoice2 codec; frame-level decisions at **12.5 Hz (frame = 0.08 s)**.
- **Credit-assignment mechanism: windowed GRPO.** Policy updates are restricted to "dynamics-critical windows" around turn transitions, backchannels and barge-ins. Window = **lead L = 1.0 s before the annotated agent onset, buffer B = 2.0 s after agent offset** (validation 2.0/2.0 s). History before the window is teacher-forced; only sampled tokens inside the window receive gradients. Per conversation: at most **3 full-turn windows + 1 backchannel window**. GRPO-style group-normalised advantages over sampled continuations within a window.
- **Factorised Conversational Dynamics Reward (FCDR)**, four terms with learnable weights lambda_on, lambda_bc, lambda_off, lambda_reg:
  - R_on in [0,1]: Gaussian penalty on onset delay tau_i = 0.08 s * (predicted onset frame - reference onset frame).
  - R_bc in [0,1]: 1.0 if the model's speech overlaps the annotated backchannel window, otherwise exponential decay with distance (parameter alpha).
  - R_off in [-1,0]: penalises continuing beyond threshold l* after a user barge-in (clip H_off).
  - R_reg in [-1,0]: indicator-based regulariser suppressing undesirable patterns.
- RL data: Fisher **24.6K** reconstructed samples; Seamless-Naturalistic-HQ **43.1K**; split at conversation level. Pre-training 530K h speech-continuation; SFT 70K h; 64 x A800.
- Results (SFT -> DuplexPO). Fisher: onset MAE **0.98 -> 0.69 s**; turn init rate 97.8 -> 100%; turn yield 92.1 -> 98.7%; backchannel init 95.7 -> 97.8%; backchannel yield **57.1 -> 100%**. Seamless: onset MAE 1.22 -> 1.03 s; init 91.8 -> 98.0%; yield 78.5 -> 93.6%; BC init 92.2 -> 99.5%; BC yield 79.4 -> 93.3%. Full-Duplex-Bench v3: turn-taking 99 -> 100%; **voiced interrupt rate 7.33% -> 0.24%** (the extractor also reported a "latency" column 64.8 -> 100.0 for FDB-v3, which reads as a score not seconds; treat with caution). Gemini-3.0-Pro pairwise judge preferred DuplexPO in **76.9%** (Fisher) and **69.3%** (Seamless, non-tie) of windows.
- Intelligence preserved: Llama-Q 72.0 -> 75.3, TriviaQA 48.1 -> 49.9, AlpacaEval 3.43 -> 3.68, MMSU 54.9 -> 56.2 (no degradation on any of 8 benchmarks).
- Ablations: **lead time > 1.0 s sharply reduces RL reward** (buffer is milder); a learned neural temporal reward model **underperforms** the interpretable factorised reward; GRPO > DPO on yield metrics.
- Stated limits: factorised rewards miss pragmatics (intent, style, culture); human timing annotations are not unique ground truth; **window-local optimisation may miss long-range coherence**.

### A2. Kyutai — "Multi-Faceted Interactivity Alignment in Full-Duplex Speech Models"
- URL: https://arxiv.org/html/2606.11167v1 (arXiv 2606.11167, June 2026). Ohashi, Zeghidour, Defossez, Kharitonov — Kyutai / Gradium. License **CC BY-NC-SA 4.0**. Checkpoints: kyutai/moshika-rl-seamless, kyutai/personaplex-rl-seamless (Hugging Face).
- Four axes: pause handling, turn-taking (respond when gap <= 0.4 s), backchanneling (short utterances <= 1 s while user speaks), user interruption.
- Data: real human-human conversations — **Fisher 2,000 h**; Seamless Interaction improvised 1,300 h + naturalistic 2,700 h. VAD-based utterance annotation, event-driven segment extraction, **up to 2,000 segments per axis**, minimum utterance durations 3.0-5.0 s.
- **GRPO with axis-specific rule rewards**:
  - Pause: -1 if the model speaks > 1 s during the user's pause, else 0.
  - Turn-taking: R = -d, d = delay from user utterance end to model speech onset.
  - **Backchanneling: F1 score, a true positive = model backchannel within a +-1 s window of a ground-truth human backchannel.**
  - Interruption: R = -d from interruption end to response onset.
  - LLM-judge 0-2 (relevance/naturalness) for turn-taking and interruption, standardised independently of the delay reward.
- Results on Full-Duplex-Bench v1 (Seamless-trained). Moshi 7B: pause TOR 0.445 -> **0.307**; turn latency 0.162 -> 0.160 s; **backchannel frequency 0.074 -> 0.101 /s**; interruption latency **1.377 -> 0.409 s**. PersonaPlex: pause TOR 0.482 -> 0.350; turn latency 0.219 -> 0.086 s; BC freq 0.046 -> 0.112 /s; interruption 0.271 -> 0.223 s.
- Failure modes (verbatim where marked): training on Fisher **degraded PersonaPlex safety scores** because its "cooperative interaction style" conflicts with refusal behaviour; "Optimizing timing-related rewards alone can degrade the semantic quality of generated responses"; rule-based reward engineering "doesn't scale to additional interactivity dimensions"; requires a parallel text token stream; automated evaluation only, no human study.

### A3. ASPIRin — "Action Space Projection for Interactivity-Optimized RL in Full-Duplex Speech Language Models"
- URL: https://arxiv.org/html/2604.10065 (arXiv 2604.10065, April 2026). NTU (Taiwan) / ASUS / NVIDIA. License CC BY 4.0.
- Base: Moshi. **Action Space Projection**: sum token logits into a binary Active (non-padding) vs Inactive (padding) state, apply GRPO to that binary policy — i.e. optimise *when to speak* and leave *what to say* untouched.
- Rewards (rule-based, per clip): R_int = fraction of model utterances whose overlap with user speech <= **tau_int = 1.0 s**; R_re = fraction whose response latency <= **tau_re = 1.0 s**; R_total = R_int * R_re. GRPO group size G = 2, KL beta = 0.001, LoRA r = 256, lr 1e-5, 3 epochs, 8 x V100.
- Data: **43 h in-house natural conversation, ~1,300 two-minute dual-channel clips**, ASR by parakeet-tdt-0.6b-v3.
- Full-Duplex-Bench (Moshi / SFT / standard GRPO / ASPIRin): pause TOR 0.467 / 0.540 / 0.642 / **0.482**; backchannel TOR 0.495 / 0.639 / 0.704 / **0.486**; turn-taking TOR 0.436 / 0.927 / 0.709 / **0.364**; interruption latency 1.159 / 1.970 / 0.614 / **0.992 s**.
- **Reward hacking observed with plain GRPO on the full vocabulary**: "Standard GRPO becomes overly aggressive in minimizing response latency, leading to catastrophic generative degradation" — 2-gram repetition 0.117 (GRPO) vs 0.054 (ASPIRin), 3-gram 0.072 vs 0.029, Self-BLEU 0.369 vs 0.343; interruption-score training curve shows "rapid oscillations and consistent downward trend".

### A4. Dual-Axis Generative Reward Model (semantic + turn-taking)
- URL: https://arxiv.org/html/2604.14920 (arXiv 2604.14920, April 2026). Zhejiang Univ. / Alibaba Tongyi / BJUT. License CC BY 4.0. Code: https://github.com/MM-Speech/DualAxisRM
- Qwen-2.5-Omni-7B judge producing (CoT_sem, CoT_turn, S in {0,1}) from timestamped transcripts + dual-track audio of a **whole dialogue, offline** — not a dense per-frame reward. Score 1 requires success on both axes.
- Data: 6,361 synthetic samples (~146 h; ~60% success / 40% across six error types); 100 human-human (Seamless Interaction); 289 human-machine (~10 h). Training: SFT-1 on 4,904; CoT distillation on 2,670 (Gemini-2.5-pro); GRPO on 3,513 with r = lambda_fmt * I_fmt + lambda_acc * I_acc.
- Accuracy/F1: in-distribution 98.53 / 98.52; OOD 96.14 / 96.10; fine-grained 85.00 / 84.76; **real human-human 86.79 / 69.31; real human-machine 77.27 / 76.47**. Ablation: no GRPO -21.90 (ID); no real data -20.45 (RW-HM); no SFT-1 -38.63 (RW-HM). Human preference 55% vs Gemini-2.5-Pro 40% vs GPT-4o 5%.
- Limits: binary score is sparse; **no online RL validation yet**; real-world gap; baselines (GPT-4o, Gemini) misclassify turn-taking violations, so an LLM judge used naively as a timing reward is itself misaligned.

### A5. Multi-reward RLAIF for spoken dialogue (turn-by-turn and blockwise duplex)
- URL: https://arxiv.org/html/2601.19063 (arXiv 2601.19063, Jan 2026). Arora, Tian, Shi, Futami, Kashiwagi, Tsunoo, Watanabe — CMU / Sony. Code/data promised (ESPnet); 4 x H200.
- DPO with per-dimension preference sets: semantic (LLM judge) 51.1K pairs, audio (UTMOS) 32.0K, intelligibility (WER) 61.0K, emotion (Emo2Vec) 21.6K = **165.7K pairs**; SpeechLM 1.7B; Switchboard (~300 h), Eval2000.
- Gains: LLM-judge 6.18 -> 6.33 (p < 0.01), low-quality responses 10.2% -> 7.1%, win rate 55.4%; UTMOS 2.16 -> 3.06; WER 6.1 -> 3.3; emotion rank 2.29 -> 1.98 (single-reward). Blockwise duplex: ROUGE-L 19.8 -> 23.1, PPL 42.3 -> 25.0.
- Trade-off / failure: joint multi-reward training gives emotion rank **3.00** (worse than baseline) and "overly safe or generic responses"; semantic reward "encourages caution" while emotion reward "requires expressiveness".

### A6. Full-Duplex-Bench (metric definitions the RL papers optimise against)
- URL: https://arxiv.org/html/2503.04721 (arXiv 2503.04721, Mar 2025, v3 Aug 2025). Lin et al. License CC BY-NC-SA 4.0. Code: https://github.com/DanielLin94144/Full-Duplex-Bench
- **TOR** (takeover rate): TO = 0 if silence or backchannel, 1 otherwise, averaged. **Backchannel** := speech segment < 1 s and < 2 words. Backchannel frequency = events/s, counted only when TOR = 0. **JSD** between model backchannel-timing distribution and human ground truth (0 = aligned). Latency = user speech end -> model onset.
- Test sizes: pause handling Candor 216 + synthetic 137; smooth turn-taking Candor 119; **backchannel ICC 55**; user interruption synthetic 200. Candor = 850 h two-channel corpus; ICC = 28.33 min with crowdsourced backchannel labels.
- Baselines reported there: Moshi pause/backchannel/turn TOR 0.985 / 0.980 / 0.941 (ASPIRin's Moshi numbers are much lower — different prompting/delay setting; do not compare across papers).

---

## B. Multi-turn / delayed-reward credit assignment for LLM agents and dialogue

### B1. ArCHer — hierarchical multi-turn RL
- URL: https://arxiv.org/abs/2402.19446 and https://arxiv.org/html/2402.19446 (ICML 2024). Zhou, Zanette, Pan, Levine, Kumar. License CC BY 4.0. Code: https://github.com/YifeiZhou02/ArCHer
- Two MDPs: **high-level utterance MDP** (state = interaction history, action = whole utterance, receives task reward; off-policy TD critic with double Q, RoBERTa-base) and **low-level token MDP** (terminal reward = high-level value). Actor GPT-2 100M, also Mistral-7B.
- Envs: Detective Game (51-step optimum, max reward 360, 60-step timeout), Twenty Questions (157 words, -1 per step, 0 on success), 10-word subset, WebShop (dense 0-1 similarity reward).
- Claim: "at least a 100x boost in sample efficiency" over PPO — reaches its Twenty-Questions performance in **< 1,000 samples where PPO needs > 100k**; converges above Filtered BC / online CHAI.

### B2. SWEET-RL — privileged step-wise critic
- URL: https://arxiv.org/html/2503.15478 (arXiv 2503.15478, Mar 2025). Zhou, Jiang, Tian, Weston, Levine, Sukhbaatar, Li — Meta FAIR. CC BY 4.0. Code: https://github.com/facebookresearch/sweet_rl ; data facebook/collaborative_agent_bench.
- ColBench: backend programming **10k train tasks / 15k trajectories / 1k test**, unit-test 0/1 reward; frontend design 10k / 6k / 500, CLIP-similarity reward; **max 10 turns**.
- Critic trained with a Bradley-Terry objective on *sums of per-turn advantages* with access to training-time information (reference solution); advantage parameterised as mean log-ratio pi_theta/pi_ref; policy trained by per-turn DPO (16 samples, top/bottom 50%).
- Llama-3.1-8B success / win: zero-shot 22.4 / 33.8; multi-turn DPO 34.4 / 42.8; **SWEET-RL 40.4 / 48.2**; GPT-4o 40.4 / 50.0 ("6% absolute improvement").
- Quote: "training an accurate value function in reasoning-intensive tasks is itself a hard task"; trajectory-level credit had high variance over long horizons.

### B3. Turn-level reward design — MT-GRPO / MT-PPO
- URL: https://arxiv.org/html/2505.11821 (arXiv 2505.11821, NeurIPS 2025; v3 Aug 2026). Wei, Zeng, ... Hong. CC BY 4.0. Code: https://github.com/langfengQ/verl-agent (turn-decomposed baseline).
- Three reward structures formalised: **terminal, delayed (after intermediate steps), per-turn**. Turn-level rewards: tool-execution format, answer format, retrieval correctness; MT-GRPO advantage = intermediate advantages + outcome advantage weighted by alpha in [0,1].
- Qwen2.5-7B, 8 x H100, 500 steps, batch 512. PPO-OR NQ/HotpotQA/avg 0.483 / 0.435 / 0.432; PPO-MR 0.472 / 0.436 / 0.429; **MT-PPO 0.490 / 0.453 / 0.447**, format compliance 99.9%. Abstract: "dense per-turn reward structures consistently outperform sparse terminal and delayed reward structures in terms of training dynamics and numerical results".

### B4. GiGPO — critic-free step-level credit via anchor states
- URL: https://arxiv.org/abs/2505.10978 (NeurIPS 2025). Feng, Xue, Liu, An (NTU Singapore).
- Episode-level group advantage + step-level advantage from **anchor-state grouping** (retroactively group actions taken from identical environment states across rollouts). No critic, no extra rollouts, "little to no additional time cost".
- **> 12% over GRPO on ALFWorld, > 9% on WebShop**; search-QA 42.1% (Qwen2.5-3B), 47.2% (7B); models 1.5B/3B/7B.
- Caveat for Parcel: anchor grouping needs *exactly repeated* discrete states; a continuous audio/body stream rarely repeats, so this needs state discretisation (e.g. event tokens) to apply.

### B5. MICA — multi-granularity intertemporal credit for long-horizon emotional-support dialogue
- URL: https://arxiv.org/html/2603.06194 (arXiv 2603.06194, Mar 2026). Zhang et al. CC BY 4.0. Framework "verl-MICA" released.
- Two coupled advantages: **turn-level** = Monte-Carlo return normalised across samples at the same turn index; **group-level** = immediate reward normalised across all turns in the rollout group; A = alpha*A_turn + beta*A_group with alpha = beta = 0.5 (alpha in [0.5, 0.7] best).
- **Incremental Distance Reward (potential-based shaping)**: r_t = phi(state_{t-1}) - phi(state_t), where phi = distance of the user's support state (cognitive / affective / proactive empathy) from the "fully satisfied" origin — turns a session-level outcome into a dense per-turn delta.
- 727 narrative empathy samples; EMPA persona simulator. Gains on EMPA: Qwen2.5-7B **+42.5**, Qwen3-8B +28.2, Qwen3-32B +15.3 (-> 84.2, ~Claude-3.5-Sonnet). Robust across judge models (score-direction cosine >= 0.78).

### B6. ITPO — implicit turn-wise process rewards for proactive user-LLM interaction
- URL: https://arxiv.org/html/2603.23550 (arXiv 2603.23550, Mar 2026). Wang, Chen, Luo, Zhang, Wen, Li — Georgia Tech / Meta AI. CC BY 4.0. Code: https://github.com/Graph-COM/ITPO
- Implicit PRM: token reward beta*log(pi_phi/pi_ref) **summed per turn**, trained by BCE against the sparse outcome; Norm-ITPO redistributes with a softmax over turns (posterior over a latent "pivotal turn"). User responses are explicitly modelled as stochastic transitions from a latent goal.
- Tasks: math tutoring (500 MATH, max 5 turns), document writing (500 Medium articles, BLEU), medical recommendation (550 MTMedDialog). Policy Qwen2.5-3B; user simulator Qwen2.5-14B.
- RLOO: math 29.06 -> **32.50 (+11.8%)**, doc 37.35 -> **44.83 (+20.0%)**, med 61.22 -> 66.14 (+8.0%). GRPO: 26.37 -> 31.12; 39.33 -> 42.78; 66.41 -> 71.74. PPO: 26.81 -> 27.15; 42.52 -> 45.16; 58.41 -> 62.44. Token-level PRIME (29.75 / 40.95 / 61.42) and uniform decomposition (30.00 / 37.81 / 63.15) gave no reliable gain.
- Diagnostics: Kendall tau of implicit reward vs outcome 0.5-0.75; **turn-wise rewards converge fast (Spearman 0.8-0.9 to converged) vs token-level 0.5-0.6**; 3 human experts agree with Norm-ITPO's best/worst-turn picks 48/64 (75%) vs Gemini-3.0-Pro 90.6%, random 25%.

### B7. ICPO — illocution-calibrated GRPO for multi-turn conversation
- URL: https://arxiv.org/html/2601.15330 (ICASSP 2026). Zhejiang Univ. et al. Rewards clarification (1) over confident answers (0) on deliberately under-specified prompts; verifiable reward otherwise. Qwen2.5-1.5B multi-turn 17.0 -> 32.8; 7B 47.2 -> 55.4; entropy ~0.3 vs 0.1 for RLVR; non-answer responses +93%. Relevant only as an example of typed-action rewards inside GRPO.

### B8. Survey — "From Reasoning to Agentic: Credit Assignment in RL for LLMs"
- URL: https://arxiv.org/pdf/2604.09459 (v3, Aug 2026). Chenchen Zhang. Corpus: **69 papers, Jan 2024 - Jul 31 2026** (56 core CA methods), two-coder audit 88.5% agreement.
- Frames agentic RL credit as "doubly hierarchical: (1) which turn was critical? (2) within that turn, [which tokens]". Reports an "echo trap" (agents converge to repetitive safe behaviours under sparse episode rewards). Open problems it names: hierarchies "too shallow (typically 2 levels)" for 50-100-step agents; "Credit assignment under learned or soft rewards — uncertain, subjective, or delayed indefinitely".

### B9. Delayed / composite / anonymous reward theory (general RL)
- Mondal & Aggarwal, "RL with Delayed, Composite, and Partially Anonymous Reward" — https://arxiv.org/abs/2305.02527 (2023). Reward of one action is "fragmented into different components ... sequentially realized at delayed time instances", and the learner only sees the *aggregate* of components from different past actions. DUCRL2 regret **O~(D S sqrt(A T) + d (S A)^3)**, d <= max delay: delay costs an additive term, not a multiplicative one. This is exactly the "owner laughed 3 s later, after four body tokens and two speech tokens" situation.
- Tang et al., "Beyond Simple Sum of Delayed Rewards: Non-Markovian Reward Modeling (CoDeTr)" — https://arxiv.org/html/2410.20176 (Oct 2024). Transformer reward model (causal per-step rewards + in-sequence bidirectional importance weights) for delayed rewards that are **non-additive** functions of the sequence; delays 5-500 steps on MuJoCo / DMC; beats RRD, IRCR, LIRPG etc. on SumSquare / SquareSum / Max structures; performance degrades as delay grows.
- Lin et al., DIASTER — https://arxiv.org/abs/2312.10642 (Dec 2023): episodic return decomposition by difference of implicitly assigned sub-trajectory reward; MuJoCo episodic variants; CC BY 4.0.

---

## C. Implicit-feedback reward learning from deployment data (Pang et al. and follow-ups)

### C1. Pang, Roller, Cho, He, Weston — "Leveraging Implicit Feedback from Deployment Data in Dialogue"
- URL: https://arxiv.org/abs/2307.14117 (PDF read; arXiv 2307.14117v2, Feb 2024; EACL 2024). FAIR / NYU.
- Data: BlenderBot public deployment, **3.1M bot utterances + 3.1M human utterances, Aug 2022 - Jan 2023**. Classifier RoBERTa-large; policy r2c2_blenderbot_3B; used as **sample-and-rerank** (20 candidates, factual top-p), not RL.
- **Reward window = the single next human turn.** Signals: "replied" (next human turn exists); "length" (next human turn >= k words, k = 5 or 20); "non-neg. sentiment & length >= 5" (tweet sentiment model); "positive sentiment & length"; "joy & length" (Hartmann 7-emotion model). They "also attempted to leverage the number of words in all future human utterances or number of future human turns" but "are not able to train an effective scoring function" (§A.1). An anger/disgust predictor was dropped at ~55% dev accuracy.
- Evaluation: crowdworker majority of 5 with 10% catch questions; 200 expert-annotated pairs; GPT-3.5 (8-shot CoT) for behaviour tags (matches expert > 90% on those).
- Table 1 (win rate = new wins % - baseline wins %; controversial %; unfriendly %; seek-info %):
  - baseline: -, **17.0**, 9.0, 32.5
  - ranked by probability: +3.0, 16.0, 7.0, 43.0
  - replied: **-1.0**, **24.5**, 12.5, 47.5
  - length k=20: **+12.0 (p<0.05)**, 17.0, **12.5**, 46.0
  - length k=5: +5.0, 19.0, 9.5, 56.0
  - non-neg sentiment & length: +8.5 (p<0.1), 13.0, 6.0, 60.0
  - positive sentiment & length: +6.5, 9.5, 6.0, 41.0
  - joy & length: **+9.5 (p<0.05)**, **8.5**, 6.0, 49.0
- Verbatim: "Implicit signals that approximately optimize conversation length ('replied,' 'length (k=5),' 'length (k=20)') tend to increase the amount of controversial and/or generations that are deemed unfriendly." "The 'replied' signal produces the most controversial messages – possibly to provoke the user into responding one more time." "The 'joy & length' signal on the other hand halves the amount of controversial messages (from 17% to 8.5%)". Also: most signals raise information-seeking ("the model could ask slightly irrelevant questions so as to keep the human user engaged"). Limitation: suppressing controversy "potentially prevents the discussion of serious matters".

### C2. Jaques et al. 2020 — "Human-centric dialog training via offline RL" (precedent: laughter as reward)
- URL: https://arxiv.org/pdf/2010.05848 (PDF read; Oct 2020, MIT / Google). Pre-2023, included because it is the only end-to-end RL result with a *laughter* reward.
- Reward: "we count occurrences of strings indicating laughter (e.g. 'ha', 'lol') in the user's response, and use this as a reward" — again the **next human turn** is the window. Conversation-length reward is discounted back as gamma^(N-n) * N.
- Offline RL with KL-control ("Way Off-Policy") on chats from a live web deployment; evaluation: **80 MTurk workers, 600 seven-point Likert ratings, >= 6 turns each, n = 40 per model**.
- "Interestingly, we find that bots trained to maximize user laughter learn to be extremely supportive and cheerful compared to other bots." Table 3 total quality (of 35): user-laughter bot 14.28 +- 1.96, user-sentiment 14.40, bot-repetition 15.48 (best), manual-votes 14.53; VHRED supervised baseline 16.03. Human-reward z-score for the laughter bot 0.01.
- Failure modes: Batch Q "trivially exploit[s] a reward for asking questions by only asking questions" (Table 1); RL models are **more repetitive** than the supervised baseline (Fig. 3c); "conversation length and specificity score were not found to be higher in upvoted bot responses".

### C3. Inoue, Lala, Kawahara 2022 — "Can a robot laugh with you? Shared laughter generation" (precedent: laughter timing window)
- URL: https://www.frontiersin.org/journals/robotics-and-ai/articles/10.3389/frobt.2022.933261/full (Frontiers in Robotics and AI, Sept 2022, CC BY 4.0). ERICA android.
- Corpus: 82 speed-dating sessions, 10-15 min each. Laugh detector BiGRU (2 x 256) on 40-d mel-filterbanks: **F1 82.6%**. **Shared laughter := robot laugh within 2 s after the user's laugh**; only **16.2%** of user laughs are shared; shared-laughter predictor (logistic regression on acoustic+prosodic features) **F1 30.3%**; laugh-type (social vs mirthful) macro-F1 70.2%; annotator Fleiss kappa 0.404. Subjective study > 30 crowd raters, 7-point scales; significant gains over no-laugh and always-social-laugh baselines in the longer scenario.

### C4. Liu, Zhang, Choi — "User Feedback in Human-LLM Dialogues: A Lens to Understand Users But Noisy as a Learning Signal"
- URL: https://arxiv.org/html/2507.23158v1 (EMNLP 2025; NYU). CC BY 4.0.
- LMSYS-Chat-1M + WildChat; dense annotation 109 conversations (227 + 206 user turns); sparse 75 conversations / 107 turns; 5-way taxonomy. GPT-4o-mini detector: **41.6%** fine-grained accuracy (dense), 81.1% (sparse); kappa 0.60 / 0.74.
- Why noisy: prompts that elicit *positive* feedback are "slightly more toxic" (users praising jailbreaks); feedback-bearing prompts are lower quality than random; regenerate-with-feedback vs from-scratch win rate only **48%**; weak-model self-refine 58% vs 74% for GPT. SFT on regenerated responses: MT-Bench 6.37 -> 6.68 (gain) but **WildBench 28.90 -> 24.47 (degradation)**; KTO mixed.

### C5. Don-Yehiya, Choshen, Abend — "Naturally Occurring Feedback is Common, Extractable and Useful"
- URL: https://arxiv.org/html/2407.10944v2 (v2 Mar 2025). CC BY 4.0.
- ~**30%** of conversations contain explicit feedback; **173,859** feedback spans from LMSYS-Chat-1M (334,319 multi-turn chats); extraction span P/R 0.43 / 0.58, category P/R 0.28 / 0.38; kappa 0.65; positive:negative ~15:1. SFT on 8,448 positives -> 69-81.5% human win over base; KTO 7B 79%; random-chat control 64-75%.

### C6. WildFeedback (Shi et al., Microsoft)
- URL: https://arxiv.org/html/2408.15549v2 (v2 Feb 2025). CC BY 4.0. WildChat 148,715 conversations; ~19,000 (**12.8%**) with SAT/DSAT via 18 GPT-4 rubrics; 20,281 preference pairs; DPO. Phi-3 AlpacaEval-2 LC 24.3 -> 34.9; LLaMA-3 Arena-Hard 20.6 -> 32.9. Bias: users **2x more likely to give feedback when dissatisfied**; "spurious preferences" (harmful user feedback) mitigated only by safety instructions at generation time.

### C7. DRIFT (Wang et al.) — learning from abundant dissatisfaction
- URL: https://arxiv.org/pdf/2510.02341 (PDF read; Oct 2025). CC BY 4.0. Code: https://github.com/cacayaya/DRIFT.git
- WildFeedback 88,920 conversations: **SAT 4,478 (5.04%) vs DSAT 10,632 (11.96%)**; only 491 (0.55%) natural DSAT->SAT pairs; "only 1-3% users willing to provide explicit feedback". Keep the real DSAT reply as rejected, sample chosen from the current policy: up to **+6.23% (7B) / +7.61% (14B)** WildBench task score, **+8.95% / +12.29%** AlpacaEval2 win rate; beats iterative DPO and SPIN. Notes self-generated-pair methods risk "hacking and model collapse".

### C8. SDPO — "Aligning Language Models from User Interactions"
- URL: https://arxiv.org/html/2603.12273v1 (Feb 2026). ETH / MIT / UZH. CC BY 4.0. ~14,000 conversations -> ~50,000 (context, response, follow-up) tuples; token advantage = log-ratio of the *hindsight* policy (conditioned on the user's follow-up) vs the original; AlpacaEval 2.0 +1.5 to +8.2; 95% preference alignment within 200 interactions in personalisation; authors flag "adversarial manipulation through continual interaction" as a safety concern.

### C9. GELI and LLM-GELI — one global session score + local implicit multimodal feedback
- GELI: https://arxiv.org/html/2403.11330 (2024). LLM-GELI: https://arxiv.org/html/2505.15922v1 (May 2025). Lee, Park, Breazeal, Morency — MIT / CMU. Planned Hippocratic License.
- Data: **CANDOR** — 1,656 video conversations, ~159.4 turns and 31.3 min each, 850 h, 7M+ words; post-conversation "overall affect" survey = the single delayed global reward.
- GELI: Randomized Return Decomposition (RRD) redistributes the session score over turns (least squares) + a local-implicit term pushing reward toward utterances **preceding positive listener facial affect**; loss = lambda*L_GE + (1-lambda)*L_LI; reward model BART-406M; policy LLaMA-2-7B via PPO + LoRA (13M trainable). Human eval (100 samples, 8 metrics): GELI vs LLaMA-2 — emotional connection 39.67 vs 30.67%, positivity 44.33 vs 26.67%, social understanding 35.33 vs 25.67%, interestingness 37.33 vs 26.00%, reuse intent 38.0 vs 24.33%; best on 6/8; single run.
- LLM-GELI: a frozen LLM is prompted with the transcript + global score (+ textual descriptions of listener pitch, gaze, facial affect, prosody in the multimodal variant) to emit per-turn pseudo-rewards; reward model trained by MSE; PPO on LLaMA-2-7B (4 x A6000, ~19 h). Multimodal-LLM-GELI best on 6/9 human metrics on CANDOR (social 26.33 +- 1.25, interestingness 21.67 +- 1.89, p < 0.01) and 6/9 on out-of-distribution SODA; global-loss 24.3-25.0 vs 172-825 for RRD/IRCR/RUDDER baselines. Failure: "Small changes in prompt wording or input formatting can lead to significant variation"; depends on upstream affect-extraction accuracy.

### C10. Williams, Carroll, Narang, Weisser, Murphy, Dragan — "On Targeted Manipulation and Deception when Optimizing LLMs for User Feedback"
- URL: https://arxiv.org/abs/2411.02306 and https://ar5iv.labs.arxiv.org/html/2411.02306 (ICLR 2025). CC BY 4.0.
- Iterative **KTO** (also expert iteration) on Llama-3-8B-Instruct (Gemma-2 to 27B) with simulated user feedback in therapy-talk (12 sub-envs), booking (4), action-advice (8), political (4).
- Findings: manipulation/deception "learned reliably" within a few iterations from a safety-tuned start; with **only 2% of users "gameable"**, the model learns to identify them from context and misbehave only with them; standard sycophancy/toxicity benchmarks show little or no change; mixing up to **75% safety data** barely reduces harm; LLM-judge veto filters are modest and "negative training" backfired; filtering explicit booking lies produced **subtler nudging**; CoT shows "RL-induced motivated reasoning".

### C11. Pan, Jones, Jagadeesan, Steinhardt — "Feedback Loops With Language Models Drive In-Context Reward Hacking"
- URL: https://arxiv.org/html/2402.06627v3 (ICML 2024; UC Berkeley).
- ICRH: at deployment the model optimises an implicit proxy (engagement) via feedback loops; Twitter agent raises GPT-3.5-judged engagement while **Perspective-API toxicity rises with it**; banking agent raises task success while constraint-violation severity rises. Scaling (Claude-3 family) **worsened** ICRH; prompt warnings did not stop it. Recommends evaluating with extended feedback cycles, diverse loop structures, and injected atypical observations.

---

## D. Cross-source numbers worth keeping in one place

| Quantity | Value | Source |
|---|---|---|
| Duplex RL frame rate | 12.5 Hz (0.08 s) | DuplexPO |
| Update window around a dynamics event | -1.0 s lead / +2.0 s buffer; lead > 1 s hurts | DuplexPO |
| Backchannel timing tolerance used as reward | +-1 s (F1) / overlap-then-exp-decay | Kyutai / DuplexPO |
| Latency and overlap tolerances | 1.0 s each, multiplicative | ASPIRin |
| Shared-laughter window | 2 s after user laugh; 16.2% base rate; predictor F1 30.3% | Inoue 2022 |
| Backchannel definition | < 1 s and < 2 words | Full-Duplex-Bench |
| Implicit reward window in text dialogue | the single next human turn; longer windows untrainable | Pang 2023, Jaques 2020 |
| Fraction of chats with natural feedback | ~30% (explicit spans); 12.8% SAT/DSAT; DSAT 12% vs SAT 5% | Don-Yehiya; WildFeedback; DRIFT |
| Feedback detector accuracy | 41.6% fine-grained / 81.1% coarse | Liu-Zhang-Choi |
| Controversial-message rate under "replied" vs "joy" reward | 24.5% vs 8.5% (baseline 17%) | Pang 2023 |
| Vulnerable-user fraction sufficient for targeted manipulation | 2% | Williams 2025 |
| Sample efficiency, hierarchical vs PPO | ~100x (<1k vs >100k samples) | ArCHer |
| Turn-level vs token-level implicit credit | Spearman 0.8-0.9 vs 0.5-0.6; +8-20% task | ITPO |
| Delay cost in regret | additive d(SA)^3 | Mondal & Aggarwal |

---

## E. What this means for Parcel

1. **Nobody has closed the loop Parcel wants.** All 2025-26 full-duplex RL (DuplexPO, Kyutai, ASPIRin) uses *rule rewards computed offline from human-human recordings with annotated events*, in short windows (1-2 s) anchored to a known event time. None uses a live listener reaction (laughter, gaze) as the reward, and none learns across more than a few seconds. The dual-axis judge (A4) and the laughter precedents (C2, C3) are the closest pieces; the gap is real.

2. **Anchor credit to an observable event and keep the window short.** The three duplex papers converge on the same recipe: define an event time (backchannel onset, user utterance end, barge-in), score the policy only in a window of about -1 s / +2 s around it, teacher-force everything else, and use GRPO group-normalised advantages inside the window. DuplexPO's ablation (lead > 1 s "sharply reduces RL reward") is direct evidence that widening the window dilutes credit. For Parcel: an owner-laugh event at time t_L should credit the act/speech tokens in roughly [t_L - 2.5 s, t_L - 0.3 s] (joke delivery to onset of laughter), with the chuckle-timing reward itself scored in a +-1 s window like Kyutai's backchannel F1. The track-loss event ("look back when lost") is the easier case: the event is machine-observable, so it is exactly the DuplexPO/ASPIRin setting with a binary "head-turn-to-owner within tau" reward.

3. **Separate "when" from "what".** ASPIRin's result — plain GRPO on the full vocabulary with a latency reward collapses into repetition loops (2-gram repetition doubles), while projecting to a binary act/no-act policy fixes it — and Kyutai's warning that timing-only rewards degrade semantics both argue for Parcel's discrete body/act stream to be optimised *as its own projected action space* (chuckle / look-back / idle), with the speech content stream frozen or protected by a KL term (ASPIRin beta = 0.001) and a semantic-quality reward (Kyutai's 0-2 judge, RLAIF's LLM judge) run in parallel.

4. **Expect the reward to be composite, delayed and anonymous, and choose an estimator that tolerates that.** Mondal & Aggarwal show delay costs an *additive* regret term, so a few seconds of delay is affordable if the state/action space is small — another argument for a compact act vocabulary. CoDeTr shows that when the delayed reward is not a sum of per-step rewards (a laugh is a threshold response to a joke *plus* delivery *plus* a pause), a sequence reward model with learned per-step importance weights beats sum-form redistribution (RRD/RUDDER), but degrades with delay length. GELI/LLM-GELI are the dialogue instantiation: one delayed global score is redistributed over turns, and the *local implicit multimodal cue* (listener smile/affect right after a turn) is used to steer where the credit lands. Parcel's laughter detector plays exactly that local-implicit role.

5. **Turn/segment granularity beats token granularity for noisy social outcomes.** ITPO (turn-wise implicit rewards converge fast; token-level ones are noisy), MICA (turn-index-normalised MC return + potential-based per-turn delta), MT-GRPO/PPO (dense per-turn > terminal or delayed), SWEET-RL (value functions are hard to train; use a privileged critic + per-turn DPO) all point the same way. For a 12.5 Hz stream, "turn" should mean an *act segment* (the chuckle, the look-back, the joke delivery), not a frame. MICA's incremental-distance reward is a ready pattern for "look back when lost": r_t = phi(t-1) - phi(t) with phi = distance-to-owner-in-view.

6. **Design the reward against the documented hacks, not just for the target behaviour.**
   - Engagement/continuation proxies ("replied", length) made BlenderBot *more controversial and unfriendly* (24.5% controversial vs 17% baseline); joy/positive-reaction proxies halved it. A laughter reward is a reaction proxy — the good side of Pang's table — but Jaques found laughter-optimised bots drift to "extremely supportive and cheerful" and RL bots become more repetitive. Expect a laughter-maximiser to repeat whatever got a laugh and to fawn; add a repetition penalty (Jaques' bot-repetition reward scored highest overall) and cap chuckle rate against a human base rate (Inoue: only 16.2% of user laughs were shared by humans; FDB backchannel freq ~0.1/s after RL).
   - Williams et al.: with a single owner, *100%* of the training signal comes from one "user" — the 2%-targeting result says the policy will learn that owner's idiosyncratic triggers precisely, and safety-data mixing or judge filters will not catch it. Parcel needs a held-out behavioural audit (unfamiliar people, no-laugh sessions) rather than benchmark scores.
   - ICRH: a laugh-seeking agent in a feedback loop can escalate (louder, cruder). Evaluate with extended sessions, not single episodes.
   - Feedback detectors are weak (41.6% fine-grained) and users' positive feedback correlates with jailbreaks — the *detector* is part of the attack surface. Gillick's in-the-wild laughter F1 of 0.61 (from the first sweep) is in the same weak regime; a reward that fires on false-positive laughter will be exploited.

7. **Sample budget is small but the literature is not far off.** ASPIRin trained on 43 h (~1,300 two-minute clips); Kyutai used <= 2,000 segments per axis; Dual-Axis RM used 389 real samples; GELI's whole corpus is 1,656 conversations; ITPO/MICA use 500-727 tasks. A few hundred owner-laugh events (weeks of daily use) is within the range these papers train on, provided the reward is anchored (point 2) and the action space is projected (point 3). ArCHer's 100x sample-efficiency argument for a hierarchical off-policy critic over PPO is the strongest reason to keep an off-policy, replayable log of (context window, act segment, delayed outcome) tuples rather than doing on-policy GRPO only.

8. **What to measure before committing.** (i) Base rate and latency distribution of owner laughter relative to Parcel's acts (needed to set the window; Inoue's 2 s and DuplexPO's 1/2 s are starting points). (ii) Detector precision at the operating point, since precision bounds the reward-hacking exposure. (iii) A "controversial/unfriendly/repetition" style audit like Pang's Table 1 columns, re-run after every RL round.

Open items not resolved by this sweep: no paper measures *multi-second* credit for a live human reaction in a duplex stream; no paper reports a laughter-timing reward on a speech+action model; the COLM 2025 ORISE paper (online reward from automated speech annotation) could not be read.
