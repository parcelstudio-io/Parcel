# Simulation and training plan — teaching the dog what to do given the state of the world

Author: Fable (parcel-0e), 2026-08-28. Companion to
`LIVING_BEHAVIOR_MODEL_REPORT.md` and `literature/LITERATURE_REVIEW.md`.
Physical motion status: **NO-GO** throughout; every stage here ends in a
signed simulation candidate or a shadow-mode log, never in actuation.

## 0. What this plan trains, in one paragraph

The dog gets three learned things and one authored thing. Learned: (1) a
**behavior policy** that reads the state of the world every 100 ms and
proposes the next act token (BM-1's BehaviorFormer today; an act stream on
a full-duplex speech backbone later); (2) an **owner table** that adapts a
few parameters of that policy to *this* owner from tens of reactions
(FL-1's bandit + explicit feedback); (3) a **body tracker** that turns a
named primitive into stable Go2 motion (reference-conditioned RL in
MuJoCo). Authored and never learned: the safety layer, the resource-track
partition, the reviewed primitive codebook, and the reward definitions.
The simulator's job is to render the state of the world, the owner, and the
rewards *with the same noise the product will have*, so that what the
policy learns in sim is what the product can actually observe.

## 1. The State of the World (SoW) — a versioned contract, not a prompt

The SoW at frame t is three things, all on the existing 10 Hz `DuplexFrame`
clock:

**(a) Dense feature vector** (≈ 40 dims, every entry a product observable or
a one-line derivation; provenance is part of the contract):

| feature | values | product producer today | status |
|---|---|---|---|
| dialogue phase | idle/listening/thinking/speaking | `DialogueStateChannel` | exists |
| owner visible / distance / bearing / motion | flags + bins | owner tracker `OwnerTrackV1` (pose + velocity with covariances, identity_score, visibility_score as a float, state) | exists |
| time since owner seen | bins incl. 2 s / 4 s / 6 s edges | derived from tracker | derivable |
| owner gaze at dog | at/away/unknown | none | **missing** (design placeholder; do not train on it) |
| DoA of last speech | 8 bins / unknown | XVF3800 DoA (udev rule currently blocks it) | exists in hardware, unwired |
| self activity, base busy, active leases | enums | executive / `ResourceLocks` | exists |
| task, task state, blocked | enums | executive receipts | exists |
| localization health | ok/degraded/lost | jump latch (`localization/discontinuity.py`, `jump_journal.py`) exists; the whole-map ambiguity latch is harness-only | exists / partial |
| env class, obstacle, doorway | enums | semantic map / local planner | exists (sim), partial (real) |
| people count | 0/1/2+ | perception | exists |
| battery | bins | SIM-only today: the physical profile refuses the inherited simulated value (SENSE-1) and the Go2 `BmsState` is unconsumed | **missing on the robot** |
| temperature | bins | no producer (the only "temperature" in the runtime is a softmax confidence) | **missing** |

**(b) Event tokens on the same clock** — `SocialCueV1`-shaped, with source
and confidence: `joke_setup`, `joke_punchline` (with *who told it* and a
coarse category), `laugh` (detector), `praise`, `scold`, `question`,
`greeting`, `call_name`, `cmd:<name>`, `steer:<param>` (calmer, livelier,
quieter, stop_that, check_more, check_less), `owner_speech_start/stop`,
`blocked`, `reacquired`, `lost`. Today `SOCIAL_CUE_KINDS` has six kinds and
no producer constructs one; the producer (ASR + local tagger + laughter
detector + DoA) is the first product seam this plan needs, flag OFF.

**(c) Slow text summary** refreshed on change (≤ 1 Hz): owner name and
consented facts, the last N interaction outcomes, current goal — the
PersonaPlex-style prompt for a speech backbone, or a MoshiVis-style
adapter input.

Owner *history for learning* is **not** in the context window: it is a
per-owner table (per-category laugh counts, preferred check-in latency,
steer overrides) that sits on the product's existing shadow→promote
learning spine (`learning_loop/{contracts,evaluation,mining,promotion}.py`,
landed in a379bf4) rather than beside it, shadow-only until promoted,
owner-readable and resettable; the check-in-shaped admission seam already
exists as `contracts/opportunity_v1.py` + `voice/companion_opportunity.py`. MemoryAgentBench's finding (no method learns
reliably at test time from context) and FL-1's design both point here.

## 2. The behavior interface and the authority partition

Output = one token per frame from the reviewed act codebook: the existing
`ActTokenCodec` (idle, 7×5 twist bins, gaze bins/owner/release, skills,
20 emotes, filler gestures) plus two additions this wave found necessary:
`<hold>` (distinct from "no opinion") and `<skill:check_in>` (the look-back
as a follow-skill sub-behavior, because a rear-hemisphere look on a
neckless Go2 is a base yaw). Authority partition, fixed:

- gaze / emote / filler → `ReactionProposalV1` on the attention /
  expression_audio tracks, through the existing bridge and arbiter (with the
  arbiter's habituation kept as the last word on repetition);
- twist / locomotion skills / check_in → *advisory* to the executive, which
  owns the base lease; the model never reaches `submit_motion`, the arbiter
  or `ControlManager` (note: `DuplexCoordinator.push_twist` is the runtime
  *telling* the act stream what it already commanded — an observation feed,
  not an actuation door). The rear-hemisphere look-back routes through the
  existing sensing-yaw proposer (`navigation/awareness_sweep.py`, AWARE-1,
  bound by the ratified R28 input-class × axis table), not a new twist door;
  and "lost owner" is not an input-health class, so it never overrides a
  HOLD or a latch;
- `cmd:stop` and the safety filter are the router's and the safety core's
  property; the model's compliance is measured, never relied on.

## 3. Three simulator layers on one clock

```
L2  social / dialogue         LLM owner simulator, jokes with categories & latent funniness,
    (1–10 Hz, text+audio)     laugh prob. per owner (Jester-calibrated) + habituation,
                              praise/scold/steer/commands, synthetic laughter audio,
                              cue-detector model (latency, FN, FP, self-echo)        ── rewards
          │ SoW events + words
L1  world / owner kinematics  procedural rooms & outdoor blocks, owner avatar walking/
    (10 Hz, geometric)        stopping/occluded, LiDAR-like visibility + DoA noise,
                              track-loss & reacquire events, blocked routes            ── SoW vector
          │ SoW vector + act token
L0  body                      MuJoCo Go2 (unitree_mujoco MJCF in repo; mjlab / Isaac
    (50–500 Hz, physics)      Lab for RL): primitive tracker, transitions, falls,
                              recovery policy with final authority                    ── execution
```

**Fast lane.** L1 + L2 without audio or physics is BM-1's `worldsim.py`: a
token world that generates millions of frames per hour on CPU. It trains
and frozen-tests the behavior policy and the owner table. Its fidelity
contract is the SoW provenance table above — every channel it renders must
be one the product can produce, and the amended BM-1 reports a
"product-available channels only" re-score to enforce it.

**Audio lane.** L2 with audio: TTS-render the owner's lines (open TTS with
laughter tags; license audit pending in the gap sweep) and the dog's own
lines and chuckle through the real Piper/CSM path, mix with room noise and
the dog's ego-noise model, and run the *real* laughter detector and ASR
over the mix. This is where "the reward is noisy and self-echo-prone" stops
being a parameter and becomes a measurement (HS-1's operating point feeds
FL-1 today; the audio lane replaces that with the detector in the loop).
It also produces the stereo (owner, dog) + timestamped transcript + act
labels that `moshi-finetune` expects, resampled 10 → 12.5 Hz with an
event-priority merge (never drop a non-idle token; DS-1 counts the drops
under hold-last).

**Owner lane.** L1's owner avatar is kinematic (Habitat-3.0-style walking
humans are the upgrade; the existing MuJoCo/headless city already has
dynamic agents). The "lost" observable is defined here, exactly as the
product will compute it: tracker state leaves `confirmed`, `t_since_seen`
grows, localization stays healthy. Loss episodes are generated with
occluders, corners, and the owner stopping behind the dog; reacquisition
depends on the dog's check-in behavior and the owner's own habits (a
parameter per synthetic owner, FL-1 §F6).

**Body lane.** L0 trains the tracker over the primitive codebook with the
recipes the literature verified (CAMP: four gaits on a real Go2 in ~7
GPU-hours from a one-hot skill vector; Disney/ExBody2: reference-conditioned
tracking at 50 Hz; QuadFM/Uni-Mo: language-labelled clip libraries), starting
from the repo's keyframe trajectories as references. Gates are the earlier
report's MOTION-COMP-1: ≥ 90 % transition survival per family, zero
joint/torque/collision/fall violations, STOP/HOLD entry within the
pre-registered envelope under interruption.

## 4. The curriculum — four stages, each with a frozen test

| stage | learner | data | signal | frozen test | gate |
|---|---|---|---|---|---|
| S1 clone the ethology | BehaviorFormer (BM-1 arm C) or the act head of a duplex backbone | token world, ≥ 3 M frames, families held out | cross-entropy to the scripted teacher (rules 1–5, priority cmd > safety > look-back > chuckle > social > liveness) | BM-1 frozen split incl. held-out families and phrasings | BM-1 amended bars (≥ 0.90 × teacher-on-observed ceiling; beats the reflex table A′ by ≥ 0.10 on held-out families) |
| S2 adapt to the owner | per-owner table (Thompson bandit per category; check-in latency arm; steer overrides) + explicit feedback | token world across ≥ 1,000 synthetic owners drawn from real taste clusters | laughter detector at its measured operating point + self-echo model; scold/praise pseudo-counts | FL-1: 100 fresh owners, 32 jokes each, noisy-reward headline | FL-1 amended bars (jokes-to-0.8 F1 with CIs; regret vs oracle; no regression on compliance/M3) |
| S3 learn timing end-to-end | duplex backbone + act stream, LoRA, GRPO-style rule rewards | audio lane: stereo + transcript + act labels | windows: chuckle 0.3–1.0 s after laugh (or after the dog's own punchline if the category is liked); check_in at the owner's latency after loss; silence during owner speech unless backchannel; command within 0.5 s; KL to S1 | replayed recorded owner sessions through the real detectors; Full-Duplex-Bench-style timing rows | improves the timing rows over S1 without degrading dialogue quality (MOSNet/judge) or compliance |
| S4 make it a body | reference tracker over the primitive codebook | MuJoCo/mjlab, 4,096 envs, domain randomization | tracking + survival rewards; recovery policy separate | MOTION-COMP-1 held-out sequences (approach→slow→bow→settle; search→reacquire→approach; follow→doorway yield→resume) | MOTION-COMP-1 gates; Isaac↔MuJoCo rank correlation ≥ 0.70 |

Stage order matters: S1 gives S2 a policy whose *shape* is right; S2's
table is what actually changes per household; S3 is the research track
that makes the speech and body one model; S4 is independent and can run in
parallel from day one because it consumes only the codebook.

## 5. Rewards, stated so they cannot be hacked

- **Chuckle.** Reward window opens *after the dog's own chuckle audio
  ends*; detector events overlapping robot playback are discarded. Today the
  LOCAL audio lane has no AEC wired (`AecStage` exists unwired; EAR-1 never
  landed) and the echo-guard mutes the mic during playback; only the hosted
  path gets the XVF3800's AEC via channel pick — so "desk today" means no
  AEC on the reward path. A
  chuckle on a joke the owner did not laugh at costs 2× a miss. Repeated
  jokes decay (novelty term in the owner simulator; non-stationary bandit).
  Explicit "that wasn't funny" = 3 negative observations + suppression for
  the episode. The reward is *positive reaction*, never engagement or
  conversation length (Pang 2023's failure mode).
- **Look back / check in.** Reward = owner reacquired within 5 s − 0.5 ×
  annoyance ("keep going" within 5 s). Learned quantity = the executive's
  `check_in_latency_s`, an owner-table value, never an act.
- **Steer.** A `steer:<param>` instruction rewrites the personality gains
  or the check-in latency for the rest of the session and persists in the
  owner table; the frozen test scores persistence (emote rate or latency
  moves within 10 s and holds ≥ 60 s).
- **Never rewarded:** anything on the base track during follow/navigation
  (vetoed by the bridge today), any act after `cmd:stop`, any act while
  `base_busy=critical`.

## 6. Evaluation ladder (evidence tiers labelled)

1. **Token world** (`desktop-sim, synthetic token world`): BM-1/FL-1 bars.
2. **Audio replay** (`replay`): recorded owner sessions (with consent) and
   public speech/laughter corpora through the real ASR + laughter detector
   + tagger; measures the SoW event stream the policy will actually see.
3. **MuJoCo execution** (`desktop-sim`): the act stream driving the
   primitive tracker; MOTION-COMP-1 rows.
4. **Runtime shadow** (`desktop-real-sensor` / on-robot later):
   `DuplexFrameConsumer(shadow=True)` receives the policy's proposal on
   every live frame and logs it beside the arbiter's decision and the
   executive's action; the diff is the promotion evidence. No dispatch.
5. **Physical ladder** — unchanged from the mount-readiness record:
   stationary Stage 0 → bag replay → tethered pulse → leashed; expressive
   primitives only after MOTION-COMP-1 and a separate commissioning plan.

## 7. Data to start logging now (so synthetic data has an expiry date)

At 10 Hz beside every `DuplexFrame`: the SoW dense vector, event tokens
with source/confidence, the proposal (if a shadow policy is installed), the
arbiter's decision, the executive's action and receipt, and — with the
owner-model consent gate — laughter/praise/scold detections with DoA. This
is the corpus that replaces the token world's teacher and calibrates the
LLM owner simulator (assistants trained against simulators fine-tuned on
*real* user utterances win 58 % vs the initial; LLM users otherwise
over-cooperate). Laughter and reaction logs are biometric-adjacent: they
fall under the existing consent/principal machinery, are per-owner, and
are never credited to a person in a multi-person room without DoA + identity
gating.

## 8. Compute and cost

All training on the desktop RTX 5000 Ada (32 GB): S1 ≤ 1 GPU-hour per arm;
S2 CPU-only (bandits) plus ≤ 1 GPU-hour for the with-history policy; S4 ≈
7–20 GPU-hours per codebook family (CAMP/Isaac recipes); S3 is the only
expensive stage — `moshi-finetune` peaks at 39.6 GB on an H100 at batch 16,
so here it runs at batch ≤ 4 / ≤ 60 s clips with gradient checkpointing,
and GRPO-style RL on LoRA parameters at small compute is *unreplicated in
the literature* (published runs used 32 H100) — treat S3 as a research
milestone with an explicit "does not converge at this scale" outcome. The
hosted ledgers ($300 Realtime / $100 text) are untouched by training; the
LLM owner simulator runs locally (Ministral-8B / Qwen-7B class).
On-robot inference: the S1/S2 artifacts run on CPU (BM-1 measures
single-thread latency; VAP-class heads report RTF 0.19); the S3 backbone
does not fit the Orin by the verified numbers and stays desktop/hosted.

## 9. 30 / 60 / 90 days for the behavior model

- **Days 0–30.** Land the `SocialCueV1` producer seam (ASR + local tagger +
  laughter detector at HS-1's operating point + DoA), flag OFF. Install the
  BM-1 policy behind `DuplexFrameConsumer(shadow=True)`; log proposals vs
  arbiter on live frames. Start the 10 Hz SoW log (§7). Generator v2
  (BM-1b: speaker, barge-in, steer, owner-ASR latency, `<hold>`).
- **Days 31–60.** FL-1's owner table in shadow with explicit feedback and a
  reset UI; per-category history; MuJoCo rendering of chuckle-bounce and
  check-in through the existing trajectories + Euler/Move; first tracker
  family (S4) in mjlab; audio lane v1 (TTS-rendered owner sessions through
  the real detectors).
- **Days 61–90.** S3 pilot: Moshi/PersonaPlex + act stream LoRA on the audio
  lane's stereo corpus; timing rows vs S1; if it does not converge at this
  compute, distill S1/S2 into the CPU head and keep the hosted speech lane.
  Package the survivor as a signed simulation candidate. Physical motion
  remains NO-GO until the separate commissioning ladder.

## 10. What would falsify this plan

- BM-1's learned arm fails to beat the reflex table A′ on held-out
  families → the sequence model is not earning its place; ship rules + the
  owner table (S2) and revisit after real logs exist.
- FL-1's headline (noisy, self-echo) row needs > 40 jokes to reach the bar
  → the household sample budget is too small for laughter-only learning;
  explicit feedback becomes the primary channel.
- HS-1's speech-negative AUROC lower bound < 0.90 → the laugh reward is not
  usable without the audio lane's AEC/DoA gating; S2 waits on that seam.
- DS-1 shows RTF > 1.0 or > 5 ms per added stream on this GPU → S3 moves
  to a hosted/cloud training plan or is dropped in favour of distillation.

## 11. How this wave's results bear on the plan (added at close, 03:16 08-29)

§10 named four falsifiers. Three of them fired, one did not, and the plan
changes accordingly:

- **BM-1's learned arm failed to beat the reflex table A′ on the held-out
  families** except on look-back (C 0.966 / B 0.888 vs A′ 0.136; chuckle
  0.457 / 0.578 vs 0.737; compliance 0.778 / 0.620 vs 0.907). → **Fired.**
  S1 becomes: a deterministic reflex table over the SoW frame (today's
  arbiter is *not* that — arm A scores 0.04 on chuckle) plus an explicit
  memory channel (last owner bearing, time-since-seen) that turns look-back
  back into a rule; a sequence model is kept only for behaviours that need
  more memory than that (barge-in, steer persistence), behind the filter
  (arm C broke `cmd:stop` 19 % of the time raw). Anticipation needs a
  per-category history channel (9.7 % of punchlines were anticipatable
  under the global window).
- **FL-1's noisy headline never reached the bar in 60 jokes** (clean: 25).
  → **Fired.** S2's mechanism stands (the table beat the meta-learned
  policy and reaches the regret bar), but the reward window is the
  blocker: masking of the owner's laugh by the dog's own chuckle biases the
  learner *against* chuckling, so S2 waits on the audio lane's AEC/DoA
  gating, and explicit feedback enters as a soft prior (the episode-long
  suppression tried here gagged the dog).
- **HS-1's speech-negative AUROC lower bound** was 0.997 ≥ 0.90. → **Did
  not fire**: the laugh reward is usable — on a GPU (the CPU bar failed
  4.5×), with coughs/cries/claps as the residual confusers (1.65 false
  triggers/min) and a held-out miss rate of 0.375 that FL-1 must adopt in
  place of its assumed 0.20. No text-only funniness prior (ρ 0.22).
- **DS-1's RTF** was 0.57 at p99 in isolation and the act stream costs
  0.56 M parameters; the measured co-resident delta with the detector and a
  GRU in-process is +2.9 ms. → **Did not fire** for the desktop; S3 stays a
  desktop research track. The Orin projection (RTF 1.23 at bf16) keeps it
  off the robot.

Net: the 30-day path in §9 is re-ordered — (1) SoW log + memory channel +
reflex table in shadow; (2) laughter detector on the GPU with the reward
window after the dog's own audio and DoA gating; (3) owner table with soft
explicit feedback; the sequence model and the duplex backbone follow.
