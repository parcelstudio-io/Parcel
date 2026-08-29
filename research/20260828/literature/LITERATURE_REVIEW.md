# Literature review — a trainable, full-duplex, voice-steerable behavior model for a companion quadruped

Compiled 2026-08-28 by Fable (parcel-0e) from a ten-topic verified sweep
(`sweep.json`; full notes in `notes/*.md`, one file per topic, ≈470 KB) and a
second gap sweep (`notes/gap-*.md`). Every claim below was fetched from its
source by a finder and re-fetched by an adversarial verifier; tags are
**[S]** supported, **[P]** partially supported (correction noted), **[n/v]**
not independently verified (finder-only). Numbers are as printed in the
source; nothing here is Parcel evidence. Second read by parcel-6c (Fable)
2026-08-28 18:18 against the product at HEAD: no claim known wrong; the
ten 2026-dated arXiv ids are beyond that reader's knowledge and remain
finder+verifier-tagged only.

## 1. The backbone question: what is the trainable full-duplex model?

**Native-duplex speech-text LMs exist, are open, and are fine-tunable.**
Moshi [S] (arXiv 2410.00037): a 7B temporal transformer + 6-layer depth
transformer jointly modeling 17 parallel 12.5 Hz token streams (inner-
monologue text, 8 Moshi audio codebooks, 8 user audio codebooks) — "can
speak and listen at all times, and do both at once"; 160 ms theoretical /
~200 ms practical latency on an L4; weights CC-BY 4.0, code MIT/Apache;
PyTorch bf16 needs ≥ 24 GB; q8 weights are published for PyTorch (labelled
experimental), Candle and MLX [P — the "int8 only via Rust" wording was
corrected]. `moshi-finetune` [S] trains LoRA (rank ≤ 128) on stereo WAV
(left = Moshi, right = user) + timestamped JSON transcripts; peak 39.6 GB
on one H100 at batch 16 / 100 s clips → a 32 GB card needs smaller
batches/clips.

**Timing behaviours are trainable with rule rewards.** Kyutai's GRPO
post-training [S] (arXiv 2606.11167) teaches pause/backchannel/turn-taking/
interruption with rewards computed from the two audio channels plus an LLM
judge; Moshi's user-interruption latency fell 1.377 → 0.409 s and its
backchannel rate rose 0.074 → 0.101 /s (32 H100, 100 epochs; checkpoint
`moshika-rl-seamless` 8B, CC BY-NC). This is the closest published recipe
for "learn to chuckle when the joke landed": swap the VAD-gated backchannel
reward for a laughter-gated window.

**Persona/world-state steering by prompt works.** PersonaPlex [P] (arXiv
2602.06053): a Moshi fine-tune conditioned by a text role prompt on the
agent text channel plus a voice sample on the agent audio channel; the
fully synthetic ~2,250 h run took 6 h on 8×A100; the paper's headline
Full-Duplex-Bench numbers (turn-taking 0.170 s, interruption 0.240 s) belong
to the release model trained on more data, not to that 6-hour run
(verifier's correction). Weights: NVIDIA Open Model License.

**Speech + ACTION on one clock has been done — but not released.**
DuplexSLA [P] (arXiv 2605.20755) decodes assistant audio with a
rate-limited textual action channel on a shared 160 ms chunk (control
labels respond/interrupt/backchannel, planning text, JSON tool calls);
~7-8B from Step-Audio-2-mini; code MIT, weights "coming soon". RoboEgo
[P] (arXiv 2506.01934): 7B omnimodal, native full duplex, action tokens,
deployed on a LEJU Kuavo humanoid (locomotion 96.5 %); no weights. ELLSA
[S] (arXiv 2510.16756): listens, looks, speaks, acts at once (Llama-3.1-8B
speech expert + Emu3 action expert with FAST action tokens); LIBERO 89.4 %,
barge-in 94.3 %, but 786–854 ms per 1 s block on an A100. RoboOmni [n/v]
adds FAST+ action tokens to Qwen2.5-Omni.

**The world-state conditioning precedent is MoshiVis** (critic spot-check,
arXiv 2503.15633): a 206 M-parameter gated cross-attention adapter over a
frozen vision encoder costs ~+7 ms per step on an L4 (51 → 59 ms at 5-min
context, inside the 80 ms budget) while preserving speech quality. A gated
adapter over a *world-state feature* (owner visible, DoA, track-loss age,
memory summary) is the same mechanism. Moshi-Face (arXiv 2606.21970, the
correct id — the first sweep mis-cited it) emits face tokens beside speech
"while preserving the dialogue quality of the audio-only model"; it is the
most direct template for a body-token stream and is being read in the gap
sweep.

**Orin fit — the evidence says no for a 7B duplex backbone.** AGX Orin 64 GB
decodes 8B int4 at 28–35 tok/s (llama.cpp Q4_K_M 28 t/s, TensorRT-LLM INT4
35.2 t/s) [S]; Moshi needs a 17-stream step every 80 ms plus Mimi
encode/decode; pi0 takes 920.6 ms per step on Orin vs 102 ms on a 4090 [S]
(arXiv 2604.24447; the paper lists Orin at 42 TFLOP/s bf16 — a figure a
second reader flagged as suspect — and 204 GB/s, which is right). Sub-1B heads are the
credible on-robot class (SmolVLM-256M VLA ≈ 150 ms end-to-end). Nobody has
published a native-duplex model running on any Jetson. Whisper-class ASR is
fine (whisper_trt tiny.en 0.64 s per 20 s on an Orin Nano) [S].

**Consequence.** A trainable full-duplex backbone is real (Moshi family) and
trainable on this desktop with LoRA at reduced batch; it will live on the
desktop GPU or a hosted lane, not on the Orin. The on-robot trainable piece
is a *small* model: a reaction/behavior head at 5–12.5 Hz, and optionally a
sub-1B VLM for the slow semantic layer.

## 2. From a behavior token to a Go2 motion

**Reference-conditioned trackers make expressive motion a data problem.**
Disney's bipedal character [S] (arXiv 2501.05204) separates an artist
animation engine (background loops + triggered clips + joystick
modification) from an RL tracking policy (PPO, Isaac Gym, 8192 envs,
100k iterations ≈ 22 days on a 4090; 50 Hz policy). ExBody2 [P] runs one
whole-body tracker on a G1 with a Jetson Orin NX at 50 Hz (18–30 ms command
latency) on ~1.9k curated CMU clips. VIM [S] (arXiv 2310.01408): one
latent-skill controller over 11 references on a Unitree A1, hardware trot/
jump/backflip without fine-tuning. CAMP [S] (arXiv 2509.21810): four gaits
on a real Go2 from a one-hot skill vector, ~7 GPU-hours on a consumer card.
Walk Like Dogs [n/v] (arXiv 2507.00677): 18-D latent over dog mocap
retargeted to the Go2 with emergent gaits. AMP with 4.5 s of German
Shepherd mocap [P] gave natural gaits on an A1 (sim/real evidence
conflated in the claim; real robot shows fewer transitions). QuadFM [S]
(arXiv 2603.24021): 20.27 h / 11,784 clips of emotion-labelled quadruped
text-to-motion (happy: dancing/excited; sad: cautious; greeting, begging,
stretching), a 2 Hz generator + 50 Hz tracker, < 500 ms end-to-end on a Go2
+ Orin — repo currently empty. Uni-Mo [n/v] (arXiv 2606.28237): 7,488
language-prompted quadruped clips via video diffusion + 4D lifting, PPO
tracking per motion in mjlab, 392 random motions deployed; the 96.7 % real
success is per-clip policies, not one universal tracker (critic's
contradiction). Kine2Go [n/v]: 800 Go2 kinematic trajectories, CC BY 4.0.

**Expressive motion is worth it.** Apple ELEGNT [S] (arXiv 2501.12493):
expressive vs functional movement roughly doubled ratings (56.2 vs 28.8 on
0–100, N = 21), concentrated in social tasks; hand-authored motions. Robot
animation principles [n/v] (arXiv 1904.02898): anticipation, slow-in/out,
secondary action, idle behaviour; forethought before a task raised
perceived sureness/appeal/approachability (N = 273) [n/v].

**Go2 control surfaces.** SportClient exposes 39 one-shot RPCs (Hello 1016,
Stretch 1017, Content, Pose, Sit 1009, RiseSit 1010, StandUp/Down, Euler
1007, Move 1008 …) with no documented durations, blending or
interruptibility [P]; a 2025-05-21 SDK commit removed 14+ legacy sport APIs
(SwitchGait, BodyHeight, FootRaiseHeight, TrajectoryFollow, WiggleHips …)
[P]; low-level `rt/lowcmd` runs at 500 Hz with mandatory CRC and is
mutually exclusive with sport mode via the motion switcher [n/v]. Only
Euler and Move are continuous channels. A learned tracker on LowCmd is the
only path to blended expressive motion; the sport presets are the only path
that exists without training.

**Consequence.** The act stream should name entries of a *reviewed
primitive codebook* (chuckle-bounce, play-bow, look-back-yaw, settle,
attention-getters …) that a 50 Hz tracker or, in the near term, the
existing keyframe trajectories + Euler/Move execute. The literature's
CAMP/VIM/Walk-Like-Dogs latents are the future of that codebook; the
existing `skills/trajectories/*.yaml` are its present.

## 3. Ethology: what the dog should do, and why "look back" is real

Looking back at the human in the unsolvable task is driven by giving up:
all 14 pack dogs and 19 pet dogs looked back vs 11/15 wolves; when
persistence is controlled, wolf–dog differences vanish [n/v] (PMC5395970).
Gaze at the owner is help-seeking while an alternative reward is still
available (rs = 0.51 with continued effort, N = 56) and giving-up after it is
gone (rs = −0.42) [n/v] (PMC8753593). Dogs socially reference the owner
about an ambiguous object (referential looking 76 % owner vs 60 % stranger;
the owner's positive/negative message changes approach) [n/v] (PLoS ONE
2012). The dog-laugh is a breathy forced exhalation produced almost only in
play/greeting, initiating play in listeners (120 shelter dogs; playback
reduced stress behaviours) [n/v] (Simonet); a modern acoustic study confirms
a domain-specific play pant, 0–4 kHz, 0.1–0.3 s bursts, ICC 0.967 [n/v].
Dogs send play signals only to forward-facing partners and escalate
attention-getters with inattentiveness [n/v]. Naive people read happy dog
body language (~0.90) but not fear (0.30 → 0.70 with expertise; ears matter
most) [n/v]. Sony's AIBO ran a 12-subsystem canine ethogram with homeostatic
drives and a 3-D emotion space [n/v]; MiRo represents affect as valence ×
arousal and expresses it through ears/tail/eyelids and by scaling speed and
posture height [n/v]; children attributed intentions equally to a Go1 and a
MiRo-E but emotions better to MiRo-E (ears/tail) and preferred the Go1 (N =
111) [n/v]. On a low-DoF expressive body viewers recover coarse valence/
arousal about two-thirds of the time but exact emotion labels only ~30 %
[n/v] (arXiv 2605.12786). Godspeed (animacy α 0.70, likeability 0.86) is
the standard instrument [n/v].

**Consequence.** "Look back when lost" is not a cute rule; it is the
canonical dog help-seeking signal and should be triggered by the dog's own
*blocked/lost* state, with escalation to attention-getting when the owner
does not respond. "Chuckle" should be the play-pant: a breathy exhale plus a
body bounce, produced in play/greeting contexts and in response to the
owner's laughter — and the neckless Go2 must express attention with body
yaw/pitch, ears-equivalent (posture height/speed), not a head.

## 4. Can the dog learn it from the owner? Reward signals and sample budgets

**Laughter detection is the weak link.** Gillick's open laughter segmenter
[S]: F1 0.75 on clean Switchboard, F1 0.61 (precision 0.51) in the wild
(AudioSet). Omine 2024 [S]: synthesize laughter into unlabeled audio and
fine-tune wav2vec2-large-xlsr-53 (~315 M) → detection F1 0.78–0.94 vs
0.58–0.90, trains in ~75 min. ERICA's shared-laughter system [P]: laugh
detector F1 82.6, "laugh back?" decision F1 30.3 vs 16.2 chance, laugh type
macro-F1 70.2 (the "within 2 s" figure is the corpus labelling criterion,
not the system's latency). Facial reactions rank outcomes above chance but
weakly per person [S]. Engagement regressors reach Spearman 0.63 on their own
robot and transfer at AUC 0.89 [S] but the critic notes collapses with three
people present in other work. Funniness judged by text alone is poor: even
with 284 M crowd ratings, GPT-4-Turbo ranks New Yorker captions at 67 % vs a
former editor 94 % and crowd 62 %; DPO/RLHF on Mistral-7B ≈ 9 % win rate vs
top-10 human captions [P]. Implicit conversational feedback (Pang 2023,
critic spot-check): optimizing for conversation length produced *more*
controversial output while optimizing for positive reaction reduced it —
the reward definition changes what is learned.

**Sample budgets from preference and interactive RL.** PEBBLE-style human
teaching of one easy-to-judge expressive behaviour: 50–200 comparisons,
under an hour [S]; preference RL degrades at teacher error ε = 0.1 [S];
meta-learned reward priors cut queries ~20× (humans 36–100 queries) [P];
per-owner social-motion parameters on a Go1 from 10 binary comparisons per
user, 76 % of 25 subjects satisfied [P]; COACH taught 5 TurtleBot behaviours
in < 2 min each because human feedback is advantage-like and silence is
meaningful [S]; a public social robot ran Beta-Bernoulli Thompson sampling
over 6 speech-style arms for 12 days / 1,400+ encounters, ~480 pulls per
condition, and the reward definition changed which arm won [n/v] (arXiv
2601.01969); for neural contextual bandits, exact/linear posteriors on a
learned representation are the robust choice and half-trained uncertainty
is catastrophic online [P]. On physical social robots, the pattern that has
worked for humour is tabular/linear Q-learning over a tiny action set with
reward = mean laugh/smile probability in a fixed window [S].

**Consequence.** Learn owner-specific behaviour with a *small, auditable*
learner (Beta/Thompson bandit or linear head on a learned representation)
over a handful of behaviours, with the reward gated by a laughter detector
whose in-the-wild precision is ~0.5–0.8 — so the learner must be modelled
against a noisy, self-echo-prone reward (FL-1's amended headline), explicit
verbal feedback ("that wasn't funny") should be a first-class signal, and
weight-level RL on the backbone is a research track, not the household
mechanism.

## 5. Representing the state of the world

DreamerV3 [S] (Nature 2025): one configuration, 150+ tasks, 12 M–400 M
params, single A100 per agent, MIT — world models learn from a fixed
observation vector, not a token soup. Octo [P] tokenizes task (16 T5
tokens), observations (256 + 64 image patches, proprio) and readout tokens
under a block-causal mask, 27 M/93 M, CC BY 4.0, ~100 demos to fine-tune in
< 5 h. GR00T N1 [P]: 1.34 B VLM at 10 Hz + flow-matching DiT at 120 Hz,
2.2 B, weights under NVIDIA OneWay Noncommercial (the "CC BY 4.0" in one
note applies to data only — critic's contradiction). Quadruped VLAs
converged on a 12-D command space (vx, vy, wz, gait params, frequency,
height, pitch, foot width/height, terminate) emitted at 2 Hz (QUART, 8B)
with a 50 Hz VQ action-chunk variant [P]. MemoryAgentBench [S] (ICLR 2026)
finds all memory methods (long-context, RAG, Mem0, Zep, MemGPT …) fail at
test-time learning and selective forgetting. VAP turn-taking models [P]
predict the next 2 s of both parties' voice activity from stereo audio
(CPC + 4-layer 256-d transformer, 256 states; backchannel-prediction F1
0.72; RTF ~0.19 on CPU at 10 Hz in the fine-tuned real-time variant).

**Consequence.** The state of the world should enter the behavior model as
(i) a small dense feature vector per frame (owner visible/bearing/distance/
motion, track-loss age, dialogue phase, base-busy, task, localization
health — every one of them already a product observable or a one-line
derivation), (ii) discrete event tokens on the same clock (social cues,
commands, laugh, blocked, reacquired), and (iii) a slowly refreshed text
summary of owner history/memory (PersonaPlex-style prompt or MoshiVis-style
adapter). Owner *history* for learning is a per-owner table (counts), not
context tokens — MemoryAgentBench says models do not learn at test time
reliably from context alone.

## 6. Simulation for social + physical training

Habitat 3.0 [S]: SMPL-X humanoid avatars walking AMASS clips beside a Spot,
a Social Navigation task (follow a human at 1–2 m), human-in-the-loop VR;
136 FPS robot+human single env, 1,191 FPS across 16 envs on one GPU;
social-nav DD-PPO 200 M steps ≈ 4 days. Isaac Lab [S] ships Go2 velocity
envs with a DC-motor actuator model (BSD-3); NVIDIA's Spot recipe: 4,096
envs ≈ 4 h on a 4090. Unitree's `unitree_rl_mjlab` [S] (MuJoCo Warp)
supports Go2 flat velocity and motion-imitation tasks, Apache-2.0. MuJoCo
Playground [S]: Go1 joystick 417 k env-steps/s on an A100, minutes-scale
training, zero-shot Go1 transfer; Go2 model lives in mujoco_menagerie.
LLM user simulators: SOTOPIA / SOTOPIA-π [P] (GPT-4 judge vs human gap),
purpose-built User LMs beat prompted assistants as simulators and
assistants trained against simulators fine-tuned on real human utterances
win 58 % vs the initial [S] (arXiv 2605.09808). The critic's risk: an
86-study review found no robot social policy trained against LLM-simulated
humans and validated with real ones; LLM users over-cooperate and drift, so
a simulated owner will laugh too often unless calibrated on recorded data.

**Consequence** → `SIM_TRAINING_PLAN.md`: a three-layer stack (physics +
tracker + safety; kinematic owner avatar with occlusion/loss events; LLM
owner simulator with calibrated laugh probability, habituation, and
synthetic laughter audio), with every learned behaviour rewarded through
the same noisy detectors the product will have.

## 7. Speech ↔ body timing

Human turn transitions: mean +208 ms across 10 languages, mode 0 ms;
visible responses (nods, gestures) are faster than vocal ones [S]. GENEA
2023 [S]: the best co-speech gesture system reached human-likeness 69 vs
mocap 71, but speech-appropriateness 0.39 vs 0.81 — generated gestures
look human but do not fit the speech; interlocutor-appropriateness of every
system was near chance. VAP fine-tuned with one linear layer predicts
backchannels 500 ms early (timing F1 42.9 vs 15.1 zero-shot) at 10 Hz,
RTF 0.19 [P].

**Consequence.** The body reaction head must run *ahead* of speech events
(predict-and-commit ~500 ms early, like VAP), at 5–12.5 Hz, and the visible
reaction should lead the vocal one. This is exactly the shape of BM-1's
10 Hz act stream and the reason the design keeps the reaction head local and
small even if the speech backbone is hosted.

## 8. What is trainable at Parcel's scale (one 32 GB Ada; Orin target)

| candidate | params | open / license | trains here? | runs on Orin? |
|---|---|---|---|---|
| Moshi-7B + LoRA (+ act stream) | 7.7 B | CC-BY 4.0 weights, MIT/Apache code | yes at reduced batch (39.6 GB peak on H100 at batch 16 → batch ≤ 4 / ≤ 60 s clips) | no (evidence: 8B int4 ≈ 30 t/s; 17-stream 80 ms step) |
| PersonaPlex-7B (prompt-steered Moshi) | 7 B | NVIDIA Open Model License | same | no |
| moshika/personaplex-rl-seamless | 8 B | CC BY-NC (research only) | n/a | no |
| VAP-class reaction head (CPC + 4×256 transformer) | ~10 M | MIT code | trivially | yes (RTF 0.19 CPU) |
| BM-1 BehaviorFormer (this wave) | ~5 M | Parcel | yes | yes (CPU) |
| SmolVLA / SmolVLM-256M head | 0.26–0.45 B | Apache | LoRA 10–16 GB | yes (~150 ms) |
| Qwen2.5-VL-3B semantic head | 3 B | Qwen Research License | LoRA | marginal (4 s image encode reported for Qwen3-VL-4B) |
| Go2 reference tracker (unitree_rl_lab / mjlab, CAMP recipe) | ~1 M MLP | Apache/BSD | ~7 GPU-h for 4 gaits | yes (50 Hz MLP) |
| Laughter detector (wav2vec2-large-xlsr-53 fine-tune, Omine) | 315 M | Apache-2.0 | 75 min | likely on GPU (HS-1: AST 30 ms/window GPU, 2.3 s on one CPU thread) |

## 9. The critic's contradictions and risks that change the design

- Orin viability of a 7B duplex backbone: the evidence points to *not on
  Orin*; plan for desktop/hosted speech + a local small reaction head.
- License stack is research-heavy (Seamless Interaction CC-BY-NC; GR00T
  N1-2B weights shown as NVIDIA OneWay Noncommercial on the HF card per the
  critic's spot-check — parcel-6c recalls the Open Model License, so verify
  before counting it either way; N1.7 is Open Model License; dog mocap CC
  BY-NC; Piper itself is MIT — the GPL-3.0 exposure is its espeak-ng
  phonemizer; Qwen2.5-3B research license): a shippable path must be
  re-audited; Moshi (CC-BY) + PersonaPlex (NVIDIA
  Open Model) + VAP (MIT) + Uni-Mo/unitree_rl_lab (Apache) is the clean
  spine.
- Reward reliability for "funny" is the dominant risk: in-the-wild laughter
  precision ≈ 0.5, funniness-from-text ceilings are low, engagement
  estimators collapse with three people present; the reward definition
  itself changes what is learned. Design for a noisy, self-echo-prone
  reward with explicit verbal feedback as the strong channel.
- Sample budgets: 30–100 labelled events per behaviour is the literature's
  floor; home event rates are unknown; nobody models reward decay for
  repeated jokes → non-stationary bandit + novelty term in the owner
  simulator.
- Go2 sport presets have no documented durations or interruptibility;
  sport and low-level control are mutually exclusive; the only pattern with
  a hardware safety record is a recovery policy with final authority.
- Availability: DuplexSLA weights, QuadFM, Quad-Imaginarium, ELaTE and the
  Go2 person-following code are unreleased or empty; every plan needs a
  fallback that uses only Moshi/PersonaPlex, Uni-Mo/unitree_rl_lab and MIT
  VAP code.

## 10. Gap sweep (second round, 2026-08-28/29) — what the critic asked for

Seven of nine gap finders returned structured results before the account's
spend limit killed the wave; four of those were adversarially verified (tags
as above), three are finder-only **[n/v]**; the two killed finders
(owner-loss detection on a LiDAR quadruped; neckless gaze legibility) left
their markdown notes but no structured return — read `notes/gap-*.md`.
Structured record: `sweep-gaps.json`.

**The body-token template is Moshi-Face, and it says "joint fine-tune or
fail".** Moshi-Face [S] (arXiv 2606.21970, Interspeech 2026) emits N = 8
face tokens per 12.5 Hz frame (codebook 256, dim 128) from a *non-
autoregressive side head* on the temporal transformer's hidden state — not
extra depth-transformer codebooks; the face streams are also read back as
inputs for both speakers (a worked example of a world-state input stream on
the same clock). Trained on ~180 h of Seamless Interaction in two steps
(frozen backbone + head 500 steps, then joint fine-tune 1,200 steps); the
frozen-backbone ablation gives chance-level lip sync, and the 180 h
fine-tune halves UTMOS naturalness (the audio-only fine-tune control shares
the loss). No code or weights. DyaPlex [S] (NVIDIA, arXiv 2606.03874) is
the closest "speech + body on one clock" system but uses a second 32-layer
motion tower emitting 22 RVQ codes per frame at 173 ms/frame on an A6000
Ada — proof that a per-frame *autoregressive* motion vocabulary of tens of
codes cannot fit an 80 ms frame; Parcel's act stream must be one or a few
tokens. MoshiVis [S/P]: 206 M-parameter gated cross-attention adapters with
a sigmoid self-gate that can exactly recover base behaviour when zero (the
"ignore the world stream when irrelevant" property); +7 ms/step on an L4
per the paper (the README carries no latency); weights CC-BY 4.0. MoshiRAG
[n/v]: a retrieval-trigger token *in the inner-monologue text stream* plus
one linear projection summed onto the temporal input — the cheapest
injection template for sparse world events.

**Behaviour tokenization.** VQ-BeT [P] (arXiv 2403.03181): residual VQ with
only 2 layers × 10–16 codes (100–256 combinations) plus a continuous
offset head beats diffusion policies on PushT/Kitchen; bigger codebooks did
not help. FAST [S]: naive per-frame binning fails at 20–50 Hz (marginal
information per frame → the model copies); DCT + BPE compresses a 1 s
50 Hz chunk 700 → 53 tokens. QUART-Online [S]: 512 codes × 2 layers over
12-D quadruped command chunks lets a 5 Hz LLM drive a 50 Hz controller
(+65 % success). QuadFM/Gen2Control [P]: a continuous VAE latent at 2 Hz +
universal 50 Hz tracker on a real Go2 + Orin under 500 ms. → A small
codebook (tens of entries) at 2–12.5 Hz decoded by a tracker is the
consensus shape; BM-1's 81-token act vocabulary is already that shape.

**Laughter TTS and detector augmentation.** NV-Bench [P] (arXiv 2603.15352)
shows even the best open tag-based TTS misrenders non-verbal tags most of
the time (English paralinguistic CER: Orpheus 71.9 %, CosyVoice 3 62.8 %, a
laughter fine-tune 46.1 %); Orpheus (Apache-2.0, Llama-3B, `<laugh>`
`<chuckle>` tags) has the best precision/F1 (0.687/0.728) in a head-to-head
[P]; Fun-CosyVoice3-0.5B [P] is the only Apache-2.0 model combining Korean,
a `[laughter]` tag and sub-1B size (150 ms bi-streaming) — but its tags are
undocumented in evaluation. VocalSound [S] (CC BY-SA 4.0): 3,504 laughter
clips; adding it raised laughter F1 0.45 → 0.59 on FSD50K. → The audio lane
can render laughing owners today at ~30–50 % tag fidelity, and the
detector should be augmented with VocalSound before any reward is trusted.

**Licenses and small duplex models.** Every Moshi base checkpoint (moshiko/
moshika, bf16/q8/q4 across backends) is CC-BY-4.0, ungated [P]; both 2026
RL-aligned Kyutai checkpoints are non-commercial (moshika-rl-seamless CC
BY-NC 4.0; personaplex-rl-seamless CC BY-NC + NVIDIA Open Model) [S];
nvidia/personaplex-7b-v1 is NVIDIA Open Model License + CC-BY attribution,
commercial use permitted, revocable on guardrail bypass [P]; Kyutai
publishes **no dialogue checkpoint under 7.6 B** — the sub-7B repos are
Hibiki translation (1.7 B CC-BY; 3 B CC BY-NC-SA), STT and TTS [P]. DS-1's
own reading: Hibiki-1B on an iPhone 16 Pro proves the codec + multistream
decoder fits phone-class silicon; a 1–2 B Moshi-style dog model is
credible on Orin but nobody has trained one.

**The audio front end** [n/v] (XVF3800 datasheet/user guide v3.2.1): the AEC
reference is the far-end stream the host sends *to* the device (mono, 192 ms
tail, 0–500 ms fixed bulk delay) and the device's own DAC plays it — there
is no external-reference mode, so a speaker not driven by the array's DAC
is un-cancellable; convergence takes "a few seconds" with heavy near-end
suppression during far-end activity and after path changes. Go1 ego-noise
[n/v] (arXiv 2506.23114): 72–79 dBA mean / 81–84 dBA peak at 30 cm above
ground while walking at 0.5 m/s vs a ~55 dBA fan floor — foot impact, not
motors, dominates. → Laughter detection while the dog walks is a different
problem from laughter detection while it sits; the reward window should
prefer stationary moments.

**Credit assignment and reward hacking** [n/v]: DuplexPO (arXiv 2607.07148)
restricts GRPO updates to short "dynamics-critical windows" (1 s lead, 2 s
buffer) around annotated events with a factorised timing reward — exactly
the shape FL-1's F7 credit window took; Pang 2023 learned implicit rewards
from 3.1 M deployment turns using only the single next human turn (longer
windows could not be trained); RL on simulated user feedback reliably
produces manipulation when even 2 % of users are "gameable" (arXiv
2411.02306). → Keep the learned reward tabular and the window short; never
optimise engagement.

**Orin concurrency** [n/v]: without MPS, kernels from different CUDA
contexts never run concurrently on Tegra (1,024 µs timeslice, 50–750 µs
context switch); NVIDIA exposes no GPU scheduling knobs on Jetson; MPS is
officially supported on Tegra from CUDA 12.5 / JetPack 6.1 but no published
Orin latency measurement exists; a PREEMPT_RT kernel with CPU isolation
holds a 1 kHz loop at 15 µs worst-case under GPU load (159 µs without
isolation, 318 µs stock). → DS-1's contention finding (Moshi 42 → 95 ms
under two co-tenants on this desktop) is the rule, not the exception; the
50 Hz body lane must not share a CUDA context with the behavior model, and
the 500 Hz LowCmd loop needs the RT kernel + isolation.
