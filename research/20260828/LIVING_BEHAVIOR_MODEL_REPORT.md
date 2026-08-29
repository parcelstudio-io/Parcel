# A trainable, full-duplex, voice-steerable behavior model for the companion dog

Date: 2026-08-28 · Author: Fable (session parcel-0e) · Status: **FINAL (03:18 EDT 2026-08-29)** — every experiment has RESULTS.md and VERDICT.md; physical motion remains NO-GO.
Physical motion status: unchanged, **NO-GO**. Nothing in this wave gains
actuation authority.

## 0. The owner's ask, restated as testable questions

1. Is there a state-of-the-art *trainable* model that can generate the dog's
   movement commands as a **full-duplex** stream — moving while listening and
   speaking — that is **steerable by voice** and driven by the emotional and
   conversational state rather than by a fixed command list?
2. Can such a system **learn** "chuckle if the joke was funny" and "look back
   at the owner when lost" — i.e., acquire owner-specific behavior from
   experience rather than from authored rules?
3. What must the **simulation and training** look like so the robot learns
   what to do given the **state of the world** (all sensors, voice, user
   history, world state)?

## 1. Where the dog actually is today (measured, not inferred)

- **Vocabulary.** The conversation model may only select names from a
  catalog of 39 skills (`runtime_assets/configs/skills/catalog.yaml`): 11
  poses, 6 velocity primitives, 3 gaits, 19 trajectories. Twenty of them are
  the bounded emotes the prompt exposes (`DEFAULT_EMOTES`, runtime.py:3671),
  including `chuckle` — a keyframed "chuckle bounce" body proxy tagged
  `hardware_unverified`.
- **Selection.** Expressive reactions are chosen by `ReactionArbiter`
  (`attention/arbiter.py`): `base_rate × temperament gains`, cooldown,
  habituation. It is **context-blind** — nothing in the score depends on what
  was said, whether the owner is visible, or what the dog is doing.
  Conversation → body coupling today is three fixed hooks: orient to speech,
  a thinking pose, and a 10 Hz dialogue-phase → gaze/pace mapper
  (`voice/dialogue_state.py`).
- **The full-duplex seam already exists.** `duplex/frames.py` defines a 10 Hz
  `DuplexFrame(text, act)` clock and `duplex/act_codec.py` a discrete act
  vocabulary: `<idle>`, `<twist:i:j>` (7 × 5 speed bins inside SafetyLimits),
  `<gaze:b>` (8 bins), `<skill:name>`, `<emote:name>`, `<filler_gesture:k>`.
  The product logs every frame to `logs/duplex/`.
- **What the log says.** 1,024,983 frames across 17,237 sessions
  (measured 2026-08-28): 61 % `twist`, 38 % `idle`, 0.4 % `skill`. Expressive
  activity is 98 % a single emote (`excited_paw_taps`, 33,828 frames, every
  one triggered by `inferred_affect`); 2,023 frames in 14 sessions carry any
  text. The corpus is a navigation record, not a social-behavior signal —
  which is exactly the owner's complaint, quantified.
- **Contracts the new model must respect.** `SocialCueV1` (kinds
  `explicit_affect | joke | greeting | praise | frustration | attention_bid`,
  modality `transcript | prosody | camera`, valence/arousal) is the typed
  input for "what just happened socially"; `ReactionProposalV1` is the typed
  output; the social path may never claim `base`, `posture` or
  `perception_scan` (`voice/reaction_bridge.py`). The learned model slots in
  as a *proposer* behind these contracts; the deterministic layer keeps
  authority.
- **Learning today.** `learning_loop/` and the untracked `skill_outcomes.py`
  are offline, proposal-only contracts; `rl/env.py` is a Gymnasium-shaped
  stub that the 03:xx `rl-env-readiness` audit refuted (2/9 gates). Nothing
  learns online.

## 2. Literature: what is state of the art and trainable

Full review with verdict tags: `literature/LITERATURE_REVIEW.md` (ten
verified topics + a gap sweep; `literature/sweep.json`; `notes/*.md`).
The five facts that shape the design:

1. **Native full-duplex speech LMs are real, open, and fine-tunable.**
   Moshi (7B temporal + depth transformer over 17 parallel 12.5 Hz streams,
   CC-BY weights, LoRA recipe published) is the base of every 2025–26
   duplex release; PersonaPlex steers it by a text+voice prompt; Kyutai's
   GRPO post-training teaches *timing* (backchannel, interruption) with
   rule rewards computed from the two audio channels — the direct recipe for
   "chuckle when the joke lands". Speech + an action token stream on one
   clock has been built (DuplexSLA, RoboEgo, ELLSA) but no weights are out.
2. **A 7B duplex backbone does not fit the Orin.** Verified numbers: 8B int4
   decodes at 28–35 tok/s on AGX Orin; pi0 takes 920 ms per step there vs
   102 ms on a 4090; no native-duplex model has been run on any Jetson.
   Sub-1B heads (≈ 150 ms) and ~10 M-parameter reaction heads (VAP-class,
   RTF 0.19 on CPU) are the on-robot class.
3. **Expressive Go2 motion is a tracking problem once a reference exists.**
   CAMP (4 gaits on a real Go2, one-hot skill, ~7 GPU-h), VIM, Walk Like
   Dogs, ExBody2 (50 Hz on an Orin NX), Disney's animation-engine + RL
   tracker; QuadFM and Uni-Mo supply language/emotion-labelled quadruped
   clip libraries (20 h / 7.5 k clips) — but per-clip policies, empty repos
   and NC licenses are the caveats. The Go2 sport presets have no documented
   durations or interruptibility; sport and low-level control are mutually
   exclusive.
4. **The reward for "funny" is the weak link.** Open laughter detectors:
   F1 0.75 clean → 0.61 (precision 0.51) in the wild; a synthetic-laughter
   fine-tune of wav2vec2 lifts detection F1 to 0.78–0.94; text-only
   funniness has a low ceiling (GPT-4-Turbo 67 % vs editor 94 % on 284 M
   crowd ratings); implicit-feedback RL that optimizes engagement produces
   *more* controversial output — the reward definition decides what is
   learned. Sample budgets from preference/interactive RL: 10–200 human
   judgments per behaviour; a public robot needed ~480 bandit pulls per
   condition.
5. **Dogs really do look back.** The unsolvable-task literature: 33/33 pet
   and pack dogs looked back at the human; gaze alternation is help-seeking
   while an alternative remains and giving-up afterwards; dog-laughter is a
   play pant produced in play/greeting that initiates play in listeners.
   People read happy dog body language at ~0.90; children attribute
   intentions to a Go1 as readily as to a MiRo-E but emotions less (no
   ears/tail).

## 3. Candidate designs

Four architectures survived the sweep and the adversarial review. They are
not exclusive; the recommendation composes them.

| | A · Hosted voice + local reaction head | B · Native-duplex backbone + act stream | C · Small VLA semantic head | D · Shared expression substrate |
|---|---|---|---|---|
| what is trainable | a 5–10 M causal transformer (BM-1's BehaviorFormer / VAP-class) at 10 Hz over the SoW; the per-owner table (FL-1) | Moshi/PersonaPlex-7B + LoRA with one more depth-transformer stream = the act codebook; GRPO timing rewards | SmolVLA-class (0.26–0.45 B) or Qwen2.5-VL-3B LoRA emitting 1–2 Hz mid-level behavior tokens from image + SoW + memory text | a 50 Hz reference tracker over a reviewed primitive codebook (CAMP/VIM/ExBody2 recipes) |
| full-duplex | yes, by construction: the head runs while the hosted lane listens/speaks; body leads voice (VAP: predict 500 ms ahead) | yes, natively (17 streams + act) | no — per-utterance | n/a (actuator) |
| voice steering | `cmd`/`steer` tokens in the SoW; hard commands via the deterministic router | in-stream (the model hears the instruction) + prompt refresh | in-prompt | n/a |
| learns chuckle / look-back | S1 clone + S2 owner table; rewards through the detector operating point | S3 rule rewards (laughter-gated window; loss-gated check-in) | weakly (slow) | executes them |
| trains on this GPU | minutes | yes at batch ≤ 4 / ≤ 60 s clips (39.6 GB H100 peak at batch 16); GRPO at this scale unreplicated | LoRA 10–16 GB | 7–20 GPU-h per family |
| runs on Orin | yes (CPU) | **no** (verified) | marginal / yes for ≤ 0.5 B | yes (MLP) |
| license | Parcel + MIT | CC-BY (Moshi) / NVIDIA Open Model (PersonaPlex); RL checkpoints CC-BY-NC | Apache / Qwen research | Apache/BSD; dog mocap CC-BY-NC |
| status today | **BM-1 + FL-1 in this wave** | DS-1 probe in this wave | design only | keyframe trajectories exist; no tracker |

**Recommendation.** A is the 30-day design and the one this wave tests: it
is the smallest thing that is genuinely full-duplex, voice-steerable and
trainable, it keeps the hosted speech lane the owner already pays for, and
it puts every learned parameter in an auditable place (a small policy
behind `DuplexFrameConsumer(shadow=True)`, a per-owner table under the owner
model). D is the parallel body track that A, B and C all need. B is the
research track — the only design in which speech and body are one model
and timing is learned end-to-end — and DS-1 measures whether it is even
runnable here. C is deferred until a vision-driven behavior (social
referencing about an *object*) is on the roadmap.

What every design shares, because the review forced it: the act vocabulary
is the existing codec plus `<hold>` and `<skill:check_in>`; gaze/emote/
filler go through `ReactionProposalV1`, twist/check_in are advisory to the
executive, stop and safety belong to the router and safety core; the
look-back on a neckless Go2 is a body yaw owned by the follow skill, not a
gaze bin; the reward window for a chuckle opens after the dog's own chuckle
audio ends.

## 4. Experiments run today

Four pre-registered experiments (`DESIGN.md` frozen before any run; an
independent three-lens design review at 17:57 produced `AMENDMENTS.md` in
each folder — pre-run for FL-1, post-start and labelled for the other
three). **Execution record:** Opus executors ran all four from 17:38; the
account's monthly spend limit killed every executor at ~18:27 on 08-28.
Salvage and completion by the verifier, solo, from 02:29 on 08-29: HS-1 and
DS-1 were complete on disk (HS-1's HS1b section and both VERDICTs written
by me from the JSON artefacts); FL-1's H-FL1d was run by me and its results
sections generated from the JSONs; **BM-1's learned arms C, E and B were
retrained by me from 02:30 (D could not run — Triton toolchain)** (the executor's arm C died at step 3,100 of
4,916 and its checkpoint was set aside) — every BM-1 learned-arm number is
therefore a solo re-run with the executor's frozen data, splits, code and
seed, not the executor's own run.

| id | question | tier | verdict |
|---|---|---|---|
| BM-1 `behavior-model-1/` | can a small sequence model learn context-dependent expressive behavior from a state-of-the-world stream and generalize to held-out compositions/phrasings — and does it beat a reflex table? | desktop-sim (synthetic token world) | **REFUTED as pre-registered; PARTIAL finding.** Arm C (4.9 M causal transformer, solo retrain) on the held-out-family slice: look-back **0.966** vs reflex table 0.136 (memory is what rules lack) but chuckle 0.457 vs 0.737, compliance 0.778 vs 0.907, anticipatory chuckle 0.093 vs 0.448; raw `cmd:stop` violations 19 % before the filter; latency p99 2.1 ms GPU / 15.1 ms CPU (bars met ~10×). Arm B (GRU, 0.93 M): chuckle 0.578 / look-back 0.888 / comply 0.620 on the same slice, false-chuckle 0.070 — same shape. Arm D (LoRA on Qwen2.5-0.5B, the unseen-phrasing test) could not run (Triton JIT needs Python-3.14 headers this host lacks); E (no-context MLP) learned nothing. Reference rows reproduced by my hands. |
| FL-1 `feedback-learning-1/` | can the dog learn *this owner's* humor and check-in latency online from tens of reactions, safely? | desktop-sim | H-FL1a **REFUTED** (the per-category rule beats the meta-learned policy; oracle ceiling 0.83 sat at the 0.80 bar); H-FL1b **PARTIAL** (regret bar met; 25 clean jokes, never under the noisy headline — self-echo masking biases the learner against chuckling); H-FL1c **CONFIRMED** (check-in latency in 1–6 losses); H-FL1d **INCONCLUSIVE** (REINFORCE 3× worse on regret, no measurable safety change in 60 updates); H-FL1e **REFUTED as parameterised** (episode-long suppression after a scold gags the dog) |
| HS-1 `humor-signal-1/` | is the reward signal real: local laughter detection, a funniness prior, real human taste variance? | replay | H-HS1a **PARTIAL** (AUROC 0.987 ESC-50, 0.999 vs speech, 1.000 vs own TTS, 30 ms/window GPU; **CPU bar failed 4.5×**); H-HS1b **REFUTED** (ρ 0.22, not memorisation); H-HS1c **PARTIAL** (taste SD 5.1 real; six clusters only 2 % over rater bias — reproduced by my hands) |
| DS-1 `duplex-speech-local-1/` | is an open full-duplex speech model (Moshi) a usable local backbone, and is an act stream a small delta? | desktop GPU benchmark | H-DS1a **CONFIRMED in isolation** (my re-measure: 2,492 steps, p50 43.6 / p99 45.4 ms, RTF 0.57, 0 steps > 80 ms, 16.2 GiB; 95 ms with two training co-tenants); D3 co-resident: laughter detector + GRU in-process add **+2.9 ms p99**, 32 ms headroom; H-DS1b **PARTIAL** (0.558 M params via the shared depformer slot — the obvious route costs 81.8 M; 6 code sites > 4; measured step-time delta **+0.93 ms p99** in isolation — bar met; `perstep` needs a custom loader); H-DS1c computed: **not on Orin at bf16** (RTF 1.23), int8 marginal, int4 fits |

## 5. What a trainable model looks like — the answer

Yes, such a system can be trained. Concretely, the trainable object is a
**behavior policy over a state-of-the-world stream**, not a bigger prompt.
Its v1 (design A, built and measured in this wave) and v2 (design B, probed
in this wave) share one interface:

```
 every 100 ms (the existing DuplexFrame clock)
 ┌──────────────────────────── STATE OF THE WORLD (t) ─────────────────────────────┐
 │ dense vector  : owner visible/dist/bearing/motion, t_since_seen, DoA, dialogue   │
 │                 phase, self activity, base_busy, task/state/blocked, loc health, │
 │                 env/obstacle/people, battery                                     │
 │ event tokens  : joke_setup/punchline(who, category), laugh, praise, scold,       │
 │                 question, greeting, call_name, cmd:<name>, steer:<param>,        │
 │                 owner_speech_start/stop, lost, reacquired, blocked               │
 │ words         : the current utterance (LM arms only)                            │
 │ owner table   : per-category laugh counts, check-in latency, steer overrides    │
 └────────────────────────────────────┬────────────────────────────────────────────┘
                                      ▼
            v1  BehaviorFormer  6-layer causal transformer, d=256, 12.8 s context,
                ~5 M params, class-weighted CE to the ethology teacher (S1),
                CPU-resident on the Orin; OR
            v2  Moshi/PersonaPlex-7B + LoRA with an 18th depth-transformer stream
                (the act codebook, ~0.5 M added params), GRPO timing rewards (S3),
                desktop/hosted
                                      │
                                      ▼  one act token per frame
   <idle> | <hold> | <twist:i:j> | <gaze_*> | <skill:name> | <skill:check_in> | <emote:name> | <filler_k>
                                      │
                 deterministic filter (tracks, base_busy, cmd:stop, habituation)
                                      ▼
   ReactionProposalV1 (attention/expression)  ·  advisory subgoal to the executive (base;
   the model never reaches submit_motion / the arbiter / ControlManager)
```

**How it is steered by voice.** Two ways, both in the stream: a hard
`cmd:<name>` token pre-empts any emote within 0.5 s (and the deterministic
router executes it regardless of the model); a soft `steer:<param>` token
("calm down", "check on me more") rewrites personality gains / check-in
latency for the session and persists in the owner table. In v2 the model
also *hears* the instruction.

**How it learns "chuckle if the joke was funny".** Three timescales, none
of which rewrites the live motor stack: (i) cloned reflex — chuckle
0.3–1.0 s after the owner's laugh (S1); (ii) owner table — anticipatory
chuckle when this owner's per-category laugh posterior exceeds 2/3, learned
by Thompson sampling from laughter detections *after the dog's own chuckle
audio ends*, corrected instantly by "that wasn't funny" (S2, FL-1);
(iii) end-to-end timing (S3, v2 only) with a laughter-gated reward window.

**How it learns "look back when lost".** The `lost` event is the tracker
leaving `confirmed` while localization stays healthy; the cloned behavior
is `<skill:check_in>` (a body yaw toward the last DoA/bearing + pause)
after the owner's preferred latency; the latency is the learned owner-table
value (4-arm bandit on reacquisition − annoyance); escalation to
attention-getting (`confused_head_tilt`, a bark-equivalent) follows the
ethology when the owner does not respond.

**What it costs to run.** v1: **15.1 ms p99 per frame on one CPU thread,
2.05 ms on this GPU** (BM-1, 4.9 M params); v2: **41.7 ms per 12.5 Hz step
on this desktop GPU** (DS-1; RTF 0.52), projected RTF 1.23 on the Orin at
bf16 — not an Orin design.

**What it needs from the product first (all flag-OFF seams).** A
`SocialCueV1` producer with the extra sub-kinds (ASR + local tagger +
laughter detector + DoA); `<hold>` and `<skill:check_in>` in the act codec;
`DuplexFrameConsumer(shadow=True)` fed by the policy; the per-owner table
under the owner model with a reset path; the 10 Hz SoW log.

## 6. Simulation and training plan

`SIM_TRAINING_PLAN.md` is the full plan. In brief: the state of the world is
a versioned contract with a provenance column (what the product produces
today, what is derivable, what is missing — `own_gaze` is missing and must
not be trained on); three simulator layers share the 10 Hz clock — a
token world for millions of frames per hour (BM-1's `worldsim.py`), an audio
lane that renders the owner and the dog through the *real* ASR/laughter
detector so the reward noise is measured rather than assumed, and a MuJoCo
body lane that trains a 50 Hz tracker over the primitive codebook; a
four-stage curriculum (clone the ethology → adapt to the owner → learn
timing end-to-end → make it a body), each with a frozen test and a gate;
rewards written so they cannot be hacked (chuckle window opens after the
dog's own audio; false chuckle costs 2× a miss; repeated jokes decay;
nothing on the base track during follow is ever rewarded); an evaluation
ladder from token world → audio replay → MuJoCo → runtime shadow → the
unchanged physical ladder; and a 10 Hz SoW log to start now so synthetic
data has an expiry date.

## 7. Verdicts, costs, and what is NOT proven

**Direct answers to the owner's three questions.**

1. *Is there a trainable SOTA model for full-duplex, voice-steerable
   movement?* Yes, two of them, at two scales. On this desk a 7.7 B
   native-duplex speech model (Moshi, CC-BY) runs at half its 80 ms frame
   budget and takes a Parcel act stream for 0.56 M added parameters placed
   so the frame's speech is generated *conditioned on the act* (DS-1). On
   the robot the trainable object is a ~5 M-parameter causal transformer
   over the 10 Hz state-of-the-world stream (BM-1), CPU-resident, behind
   the existing reaction contracts. The 7 B backbone does not fit the Orin
   (RTF 1.23 at bf16, verified by roofline + the one published 7B Orin
   measurement); it is a desktop/hosted research track.
2. *Can it learn "chuckle if funny" and "look back when lost"?* The
   look-back part is easy and learned in one to six losses as an
   executive config value. The chuckle part is learnable as a per-owner
   per-category table in ~25 *clean* jokes — but the household's reward is
   not clean: the best local laughter detector misses ~37 % of laughs at
   its held-out operating point, a walking Go2 hears 72–79 dBA of its own
   feet, and the dog's own chuckle masks the owner's laugh in the next
   second, which biases the learner *against* chuckling (FL-1's noisy
   headline never reached the bar). A meta-learned policy did not beat the
   explicit per-category rule; online policy-gradient was 3× worse. So:
   yes, with a table, a clean reward window (after the dog's own audio, with
   AEC on the local lane — none today), and explicit verbal feedback as a
   soft prior.
3. *What to do in simulation/training?* `SIM_TRAINING_PLAN.md`: a
   versioned state-of-the-world contract with provenance (three channels
   the product cannot produce today are marked and excluded from training:
   owner gaze, battery on the robot, temperature), three simulator layers on
   one clock (token world → audio lane through the real detectors → MuJoCo
   body lane), a four-stage curriculum with frozen tests, rewards written
   so they cannot be hacked, and a 10 Hz SoW log to start now.

**Costs.** Hosted spend this wave: $0.00 (every model local). Desktop GPU:
≈ 6 h total across the four experiments plus retraining. No product file
was modified; no git write; physical motion remains **NO-GO**.

**What is NOT proven.** Nothing about real audio through the XVF3800 (no
AEC on the local lane), real perception, real ASR latency (owner-told
punchlines arrive 0.5–1.5 s late — BM-1's timing bars are meaningful for
dog-told jokes only), the Go2, or the Orin (all Orin numbers are
projections from bandwidth plus one published 7B measurement). The token
world's teacher is authored; a high BM-1 score means the policy learned the
authored world, and only the held-out-family/phrasing slices carry a
generalization claim. FL-1's owners are synthetic (HS-1's real-taste
artifact landed after FL-1 ran) and its detector noise is milder than HS-1
measured. The literature's ten 2026-dated arXiv ids were verified by
finder + verifier agents but are beyond any human reader on this project.

**Execution record for the integrator** (per parcel-fb): the monthly spend
limit killed the four Opus executors at ~18:27 on 2026-08-28; BM-1 arms
C, E and B and FL-1 arm d were re-run solo by the verifier on 08-29 from
02:30 (BM-1 arm D could not run: Triton JIT toolchain); HS-1 HS1b and all four VERDICT files are the verifier's. The two
index lines added at close, verbatim:

- `research/20260828/README.md` → `- \`LIVING_BEHAVIOR_MODEL_REPORT.md\`, \`SIM_TRAINING_PLAN.md\`, \`literature/\`, \`behavior-model-1/\`, \`feedback-learning-1/\`, \`humor-signal-1/\`, \`duplex-speech-local-1/\` — parcel-0e's 12-hour wave on a trainable full-duplex voice-steerable behavior model (learn chuckle-if-funny / look-back-when-lost from the state of the world) and the sim/training plan; physical motion still NO-GO.`
- `research/README.md` → `- \`20260828/LIVING_BEHAVIOR_MODEL_REPORT.md\` — trainable full-duplex behavior model wave (BM-1/FL-1/HS-1/DS-1, verified literature review, SIM_TRAINING_PLAN); see \`20260828/README.md\`.`
