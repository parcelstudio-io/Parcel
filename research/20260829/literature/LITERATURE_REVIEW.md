# Literature review — navigating while conversing: streaming controllers, narration, interruptible plans, hosted voices

Compiled 2026-08-29 by Fable (parcel-0e) from a ten-topic sweep (`sweep.json`;
notes in `notes/*.md`): every claim fetched by a finder and re-fetched by an
adversarial verifier. Tags: **[S]** supported, **[P]** partially supported
(the verifier's correction is applied in the text), **[n/v]** finder-only.
Numbers are as printed by their sources; nothing here is Parcel evidence.
Coverage caveat from the critic: five of ten finders exhausted their search
budget before reaching quadruped self-narration, SoundSpaces/AVLEN, and the
NVIDIA Go2+LLM demos — a direct precedent may still be missing.

## 1. Streaming navigators: what "constant input streams" look like when they work

**The reference streaming design is a video-LLM run as an online dialogue.**
StreamVLN [S] (arXiv 2507.05240, ICRA 2026): LLaVA-Video/Qwen2-7B over the
camera stream with a sliding-window KV cache of the last 8 dialogue turns, a
slow memory of 8 frames × 196 tokens, and depth-voxel token pruning; 4
discrete actions per turn; R2R-CE val-unseen SR 56.4 / SPL 50.2 (57.4 / 51.1
with pruning + memory); deployed on a Unitree Go2 (D455) from a remote RTX
4090 at 0.27 s per 4 actions; ~1,500 A100-hours; weights CC BY-NC-SA. Its
ablation is the memory lesson: 8×196 bounded memory beats *all* context
(SR 45.5 vs 40.0) [P]. Uni-NaVid [S] compresses history by age (64 tokens
current frame / 4 per short-term frame / 1 per long-term frame), 4 actions per
step at ~5 Hz on an A100, MIT-licensed; removing all memory collapses R2R SR
48.7 → 9.6 while person-following barely moves (61.2 → 56.3) [P — the
collapse is for removing *all* memory, not the long-term tier alone].

**Dual-rate is the deployed shape.** DualVLN / InternVLA-N1 [S] (arXiv
2512.08186): a 2 Hz Qwen2.5-VL planner emits a pixel goal + 4 latent query
tokens; a 30 Hz diffusion-transformer policy emits 32-waypoint trajectories;
asynchronous; R2R-CE SR 64.3 / SPL 58.5; Go2/G1/Turtlebot; 20 GB on a remote
4090. TIC-VLA [P] (arXiv 2602.02459) is the only dual-system navigator
measured on a Go2 *with an onboard Jetson*: InternVL3-1B (InternViT-300M +
Qwen2.5-0.5B) at 0.5 Hz writing KV features + waypoints for a 10 Hz policy,
trained under randomized 0–10 s reasoning delay; real Go2 SR 0.75 on an Orin
NX at 25 W vs 0.85 on an RTX 4060 laptop (the paper presents 0.75 as
robustness *despite* latency, not as a pure-latency loss). NaVILA [P] (RSS
2025): an 8B VLM emits mid-level *text* actions ("move forward 75 cm", "turn
right 30 degrees") cast to fixed velocities for an Isaac-Lab locomotion
policy; 88 % on 25 real Go2 instructions at ~1 s per action, VLM off-robot;
the paper never states a 50 Hz controller rate. The best Go2-deployed VLN
model, MobileVLA-R1 [S] (R2R-CE SR 68.3 / SPL 65.2), runs ~10–15 s per step
via a remote H20. ETP-R1 shows a 0.5B model reaching R2R-CE SR 65 / SPL 56
[n/v].

**Even streaming navigators stall on a real robot.** LiveVLN [P] (arXiv
2604.19536): on a Unitree G1, StreamVLN waited 17.4 % of episode time, while
NaVIDA waited 30.5 % with 94.9 % of its inference rounds causing stop-and-go.
A guarded handoff—a committed guard buffer sized from measured sense +
inference latency, plus a revisable tail—cut waiting 77.7 % / 72.8 % with
success essentially preserved (StreamVLN 57.2 vs 56.4; NaVIDA 59.9 vs 61.4),
without retraining. NaVIDA is not NaVILA; the latter was only a reference row
in that study.

**The Go2 gap is embodiment, light and controller, not only data.** VLN-PE
[P] (ICCV 2025): moving from the ideal continuous sim to physics, NaVid drops
40.7 → 22.4 SR on a humanoid; a CMA model drops to 4.7 % on a 0.5 m quadruped;
RGB-only loses ~12 points in low light vs 2–3 for RGB-D; 14 real Go2 episodes
went 7.1 → 28.6 % SR after fine-tuning on physics-sim data. HA-VLN [P]: 2–4
free-moving people cut a real Go2-EDU (D435i + Mid-360 + Jetson NX) from
0.44 to 0.18 SR (numbers from arXiv v2; the current v5 removed the table).

**Consequence for Model A.** Every real legged deployment runs the language
lane at 0.5–4 Hz and a separate fast loop at 10–50 Hz; nobody runs a language
model at 10 Hz. Parcel's Model A should be the fast loop over the existing
10 Hz frame clock with a slow language/plan lane on top, a
LiveVLN-style committed-prefix / revisable-tail contract in the act codec,
age-tiered bounded memory (not a flat 600-tick window), RGB-D/LiDAR channels,
and training traces captured through the same motion gateway used at
deployment.

## 2. Dialogue while navigating: the benchmarks do not exist yet

CVDN [P] (2,050 human–human dialogs, 83 houses; navigator stops, types,
waits) and its successors are typed, turn-based and replayed from history —
none evaluates spoken interruptions while the robot moves. Agent-initiated
help multiplies unseen success: HANNA [S] 8.1 → 47.5 % with 5.8 requests per
task; DialFRED [S] 18.3 → 33.6 % at 0.71 questions per episode (asking every
step buys little at 30× the questions); RAINbow [P] auto-converts R2R/RxR/
CVDN into 238 K dialog episodes at $0.0016 each and doubles unseen success.
InterruptBench [P] (arXiv 2604.00892) formalizes Addition / Revision /
Retraction injected at 60 % of a trajectory — on web tasks even the best
model adapts ~20 % single-interruption (multi-turn Opus 41.8 %) and often
continues with stale assumptions. EchoChain [P] names the voice-model
failure modes on mid-utterance updates: contextual inertia (acknowledge but
do not apply), interruption amnesia (apply then revert), objective
displacement (abandon the original task); mean pass rate < 50 % for every
hosted duplex model. IHBench [P] types spoken interruptions (Normal /
Impatient / Correction / Topic switch / Filler / Pushback) for enterprise
workflows — judge-vs-human κ is only 0.45–0.51. ELLSA [P] (arXiv 2510.16756,
18 B, Apache-2.0) is the closest single model to "Model A": full-duplex
listen/look/speak/act in 1 s blocks, stops an ongoing action on a spoken
interruptive command 94.3 % of the time, answers progress questions while
acting — tabletop only, sim only, 786–854 ms per block on an A100, and
speaking while acting costs 84.4 → 73.2 on LIBERO-Long (≈ 2 points on the
four-suite average).

**Consequence.** Parcel must *define* its interruption benchmark (injection
point, revise/keep/queue labels, SR + SPL + recovery + stop latency, with
EchoChain's three failure modes as named rows) rather than adopt one — no
published number is comparable. The codec should carry HOLD / RESUME / ABORT
/ BACKCHANNEL as first-class tokens. A cost-aware *ask* policy belongs in
Model B (2–6× success from asking, but HRI evidence says interleaving lowers
perceived competence — only a cost-weighted policy reconciles the two).

## 3. Speak-while-acting and the Model B precedent

Hi Robot [S] (arXiv 2502.19417) is the direct precedent for "Model B over
Model A": a PaliGemma-3B high level re-runs every ~1 s *or immediately on a
user interjection*, emits an atomic language command for the π0 low level
(73 ms/step on-board, 50 Hz chunked) plus a verbal reply grounded in the
current image; instruction accuracy 76 % vs 36 % for a flat VLA vs 30 % for
a GPT-4o high level; the high level trains in ~2 h on 8×H100 on
VLM-synthesised situated interjections. Yell At Your Robot [S] gives the
simplest injection: a spoken correction temporarily overrides the high
level's language output straight into the low-level policy; fine-tuning on
the logged corrections (4–11 % extra data) lifts success 15–45 points. RT-H,
π0.5 and NaVILA all make the slow lane's output *language*, which is what
makes it narratable; the fastest deployed navigators (DualVLN, TIC-VLA,
Helix) use *latent* interfaces — no paper compares the two on control
quality or narratability. DuplexSLA [S] (arXiv 2605.20755) shows a native
duplex model carrying a rate-limited action channel (≤ 10 text tokens per
160 ms chunk: interrupt/backchannel labels, planning text, JSON tool calls)
beside continuous speech — but its tool accuracy (85.6 %) is *below* an
ASR+LLM cascade (91.3 %); it wins only on delay (0.64 vs 2.77 s), and its
backbone size is unresolved ("77B-scale" in the HTML vs "~7B" README).

**Consequence.** Model B's cadence is Hi Robot's (≈ 1 s and on every owner
utterance); its injection is YAY's override switch mapped onto the
executive; narration stays *off* the control path (ELLSA's penalty), which
is exactly Parcel's split (hosted voice + local controller).

## 4. Interruptible plans and the queue

Two-LLM coordinator/worker robots with per-task memory can be interrupted,
switch, and later resume from a stored snapshot [P] (NICOL, 50 trials per
condition). Information-state update over {current goal, plan tail,
completed-steps ledger, per-goal snapshot} is the consistent mechanism;
implicit transformer memory does not carry across instructions (IVLN
t-nDTW 61 → 45) [n/v]; frontier LLM controllers believe they succeeded in
every trial, so success must be externally verified [n/v]. **Consequence.**
The plan queue is explicit and snapshot-able (what Parcel's executive lacks
— the amendment transaction *consumes* the parked resume intent on commit),
and "resume" is a re-issue with lineage.

## 5. Narration: push, don't pull; say what and why; not too often

Kox 2024 [S] (N = 82): four spoken status updates per mission that say *what
and why* on a deviation keep trust high (η² = .177; a silent deviation is a
trust violation, Δ = 1.2 on a 7-point scale). Wang 2016 [S]: explanations
rescue an unreliable robot (mission success 97 % vs 52 %) and do nothing for a
reliable one. REFLECT [S]: a change-triggered, hierarchical text summary of
the robot's experience lets GPT-4 explain failures at 88 % accuracy and
nearly doubles correction-planning success. Realtime backends driving a
social robot [P]: ~0.7 s turn latency but they *under-invoke* perception
tools (recall ≈ 0.6) — the paper's remedy is better prompting, but the
digest's conclusion "push state in, don't wait for a tool call" is the safe
reading. A streaming video-LM can learn a per-frame speak/silent decision
and write its own progress summary into its prompt [P] (30 K synthetic
dialogues). Inner-Thoughts-style gating (score covert candidate lines on
relevance/urgency; users dislike non-stop chatter) [n/v].

**Consequence.** Model B narrates from a change-triggered, hierarchical
digest (goal/plan level + event level with *what + why* on deviations),
pushed into the hosted session as small text items, at a rate a gate
controls; "done" claims originate from detectors/receipts, never from the
voice model's belief.

## 6. The hosted voice: mechanisms, latencies, prices, traps

OpenAI Realtime [S]: audio billed at 1 token/100 ms in and 1 token/50 ms out
(mini tier $10 / $20 per 1 M audio tokens — list-price arithmetic gives ≈ $0.006 per *uploaded speech* minute; Parcel's own H1 measurement (08-24) found streamed SILENCE is not billed under server VAD, so this is not a per-minute listening cost); server
VAD with `interrupt_response` / `create_response` switches, barge-in via
`conversation.item.truncate`, out-of-band responses, and — GA since
2025-08-28 — asynchronous function calling with filler utterances; 32 K
context, 60-minute session cap. Gemini Live [P]: NON_BLOCKING tools with
INTERRUPT / WHEN_IDLE / SILENT scheduling — but only on the 2.5 Flash Live
preview, not the current 3.1 Flash Live. Measured behaviour: Full-Duplex-
Bench v1.5 [n/v] — GPT-4o Realtime stops 0.23 s after a user interruption
but resumes after side-talk only 2 % of the time (Gemini 2.0 Flash Live 98 %);
FDB-v3 [S] with zero-latency mock tools — gpt-realtime-1.5 pass@1 0.60 at
6.9 s average latency; DuplexSLA-Bench [S] — GPT-Realtime turn-taking 96.5 %
at 1.57 s (semantic VAD) or 85.5 % at 0.83 s (40 ms server VAD); τ-Voice [S]
— hosted voice agents complete 31–51 % of tasks that text GPT-5 completes
85 % of; IHBench [P] — GPT-family continue correctly after a filler only
7–31 %. The quoted "turn latencies" (0.4 s … 6.9 s) are different metrics
on different VAD settings and model versions — never one number.

**Consequence.** Model A never blocks on the hosted voice; Model B uses async
tool semantics so "Sure, I'll check the sofa" is spoken in the same turn the
robot starts moving; barge-in splits into a fast reflex (speech_started →
soft hold to Model A) and a slow decision; robot state enters as small
event-driven *text* items; the household needs an owner + addressee gate
(hosted models treat every utterance as addressed to them); session cycling
for an all-day companion is undesigned anywhere.

## 7. Benchmarks worth running offline

R2R-CE / RxR-CE (SR, SPL, nDTW; SOTA ~64–68 SR), HM3D-OVON [S] (15,661
instances; 2024 baselines SR 35–37; 2026 Qwen-RobotNav-4B SR 53.1 at 4.9 Hz on
a Jetson *Thor*), GOAT-Bench, Habitat social-nav (PSC, collisions), LiveVLN's
idle ratio / visible gap, Full-Duplex-Bench timing rows, τ2-bench's lesson
that user simulators are reliable only when tied to the environment (16 %
error vs 40–47 % prompt-only) and that dual control costs frontier agents
18–25 points — report pass^k, not pass^1; and chance-corrected κ for every
LLM judge (raw agreement overstates κ by 34–41 points) [S].

## 8. Sim-to-real and LLM-in-the-loop harnesses

Habitat 3.0 [S]: humanoid avatars, social nav, a recordable/replayable
human-in-the-loop tool; 136 FPS robot + human; automated humanoid evaluation
preserves the *ranking* of policies seen with real humans. PARTNR [P]: 129
participants; LLM partners score 0.30 with a simulated LLM human but 0.91 with
real humans, who adapt to robot mistakes — an LLM owner-simulator ranks
variants, it is not an acceptance bar. τ-Voice [S]: a 200 ms-tick orchestrator
with a wall-clock-decoupled LLM user simulator, LLM-driven barge-in, per-tick
event logging. No simulator combines spatial audio, moving people, a Go2 twin
and an LLM voice agent with scored, replayable episodes — the harness the
owner asked for is unbuilt anywhere and must be assembled (τ-Voice's tick +
user-sim design, a Go2 twin, an audio channel).

## 9. Liveness during navigation

Disney's animatronic gaze stack [P] (attention engine with curiosity +
habituation; Read / Glance / Engage / Acknowledge; an always-on "alive"
layer of breathing/blinking/saccades at 20 Hz); iCub's ego-sphere attention
with inhibition-of-return [S]; Pepper's SemiEngaged rule (glance at a new
stimulus, return to the engaged person) [S]; Walk-These-Ways [S] (Go1: one
50 Hz RL policy conditioned on an 8-dim human-readable behaviour vector —
gait phase, frequency, body height, pitch, stance width — executes trot /
pronk / bound / dance); ELEGNT [P] (expressive movement doubles engagement
ratings, N = 21; non-significant on function-oriented tasks). **Consequence.**
Liveness is a fixed layered controller *beneath* Model A (alive base →
attention glance → task), Model A's local action is a behaviour vector +
velocity, and Model B sets an expressiveness gain from context.

## 10. What is still unknown (the critic's gaps, kept)

No on-Orin throughput for a 1–8 B navigator at StreamVLN token counts (only a
0.5 B LLM has been measured, and it lost 10 SR points); no owner-voice /
addressee gate surveyed; no tokenization recipe for putting voice, LiDAR and
user context *into* a navigation policy (all memory budgets are RGB priors);
no faithfulness test between a jointly trained narration head and the control
decision; no (state stream → spoken commentary) training corpus; no
LLM-user-simulator-in-the-loop *training*; no Go2 SDK2 command-to-leg
latency; no ASR/DoA numbers on a walking Go2; no multi-rate token interleave
design; no Starlink jitter to hosted endpoints.

## 11. What this means for Parcel, in one table

| owner's element | the evidence says | Parcel mapping |
|---|---|---|
| Model A over constant streams | a 10 Hz fast loop + a 0.5–2 Hz language lane; bounded age-tiered memory; committed-prefix / revisable-tail | BM-1 family policy on the 10 Hz frame; `DirectiveNavigator` as the slow lane today, a ≤ 1 B VLM later |
| "last minute + global history" | 8-turn window + compressed older frames; explicit ledger for plans | age-binned event channels (MA-1 A5) + the executive's queue |
| narration representation | language-level subtask/status at ≤ 1 Hz, change-triggered, what + why | narration events partitioned into product-backed vs research-only (MA-1 A7); Model B renders receipts (MB-1 M7) |
| Model B steering | re-run on every owner utterance; override switch; Addition/Revision/Retraction → queue/revise/retract | steer over the executive's verbs; re-issue for resume |
| Model B narration | push small text items; async tools; rate gate | tail-seam conversation item + trigger table (MB-1 M6) |
| benchmarks | define Interrupt-Nav; report pass^k; κ-corrected judges | NAV-INT-1 tier; MB-1 scorer with blind adjudication |
| harness | τ-Voice tick + user sim + Go2 twin + audio; LLM users rank, humans accept | LIT-1 with provenance per hop and real-swappable hops |

## 12. Gap sweep (second round, six topics; `sweep-gaps.json`, `notes/gap-*.md`)

**Orin sizing — the number the design was missing.** NVIDIA's AGX Orin 64 GB
figures are aggregate vLLM throughput at concurrency 8 (Qwen2.5-VL-3B 216
tok/s, 7B 154 tok/s) [P]; Thor's concurrency-1 rows show single-stream is
~5× below the aggregate, so derived single-stream decode on the Orin is
≈ 43 tok/s (3B) / 27 tok/s (7B). Jetson AI Lab's end-to-end multimodal
streaming rate (encoder + projector + VLM, 4-bit MLC) on AGX Orin: VILA1.5-3B
7.6 FPS, Llama-3-VILA1.5-8B 5.1 FPS, Llava-7B 1.4 FPS [S]. Component study
(ETRI, ICML-W 2026) [P]: SigLIP-class vision encoders cost 98–160 ms per
frame FP16 on AGX Orin (8 fresh frames = 0.8–1.3 s before any LLM work);
eager-transformers decode 90–138 ms/token for 0.5–3B VLMs; BitsAndBytes INT4
*raises* TPOT 32–56 % (a VRAM tool, not a latency tool); INT8 SigLIP is
2.4–4.7× slower. EdgeReasoning [n/v] fits single-stream vLLM FP16 on AGX
Orin: TBT 0.024–0.029 s (1.5B), 0.09–0.10 s (8B); prefill of ~1,600 tokens
(8 frames × 196) 0.45 s (1.5B) / 2.27 s (8B). TIC-VLA's 1B took 4.8 s per
reasoning step on an Orin NX because it writes reasoning text [P].
**Sizing table (AGX Orin 64 GB):** ≤ 2B VLM with 1–2 frames and ≤ 16 output
tokens ≈ 2 Hz; the same with an 8-frame × 196-token memory ≈ 1 Hz; 7–8B ≈
0.3–0.5 Hz with memory; no VLM fits a 10 Hz loop (fastest measured step
150 ms for SmolVLM-256M). Cache vision tokens per frame; make the plan lane's
output a short structured object (≤ 16–32 tokens) or a latent/KV handoff,
never on-device chain-of-thought; report every latency with runtime,
precision and nvpmodel.

**Owner voice and addressee gating.** Wake-word-free device-directed speech
detection runs on an ARM Cortex-A72 as a three-stage cascade (~520 K params,
< 20 MB): audio-only F1 0.86 at 2.1 % false triggers (7.8 % with TV audio),
audio+video F1 0.95, median latency 38 ms [S]. Apple's multimodal
device-directed detector (ASR text + acoustic embeddings + decoder signals
in a GPT-2 classifier) reaches 6.5–8 % EER vs 11–13 % for audio- or
text-only [P]. Hosted APIs do not solve addressee: OpenAI Realtime has no
"ignore speech not directed at me" option; Gemini's `proactive_audio` exists
only on 2.5 Flash Live preview [S]. In a controlled multi-party lab study a
cloud speaker-ID was nearly useless (18–27 % correct) while face recognition
and gaze carried addressee (92.6 % dyads / 79.3 % group, 1.35 s latency) [P].
RoboVox [n/v]: speaker verification on a moving robot at 1–3 m with actuator
noise degrades to 15–18 % EER (close-talk 9.3 %). Personal VAD 2.0 [n/v]: a
~1 MB / ~10 MFLOP target-speaker VAD is the right primitive for a continuous
"is the OWNER speaking" bit. → Model B's gate is two-tier and local (personal
VAD every frame; per-utterance verification fused with DoA and head-pose),
planned at 10–18 % EER, not VoxCeleb's 1 %; the owner + addressee bits land
0.3–1 s after speech onset, so voice steering enters through the 0.5–2 Hz
lane while barge-in stays a fast reflex.

**Non-RGB tokens for a navigation policy.** ViLiNT-style LiDAR tokens
(polar sector-ring grid → K pooled tokens) beside RGB tokens: masking LiDAR
costs SR 0.79 → 0.17 while masking images costs far less; real Husky 85 % vs
15 % [P]. REASAN [P]: a 30 × 180 LiDAR ray image + proprioception at 50 Hz in
~1.3 ms on a Go2 + Mid-360 + AGX Orin 64 GB (Parcel's exact stack), beside PPO
locomotion, a safety shield and navigation, zero real collisions. For VLMs a
raw occupancy image is worth ~0 SR but an *annotated* semantic map rendered as
one image replaces the frame history (R2R-CE SR 27.3 → 36.5, constant
0.17 MB, inference 0.25 vs 1.22 s) [S]. Direct speech tokens (Whisper →
~300 tokens) match text instructions within 1–4 points and enable
owner-specific tasks (86.5 % vs 19.2 %) [P]. → The Mid-360 enters Model A's
10 Hz loop as LiDAR tokens (tens to a few hundred), the plan lane gets one
annotated map image, structured state is one MLP token per vector with a
goal mask, and audio events arrive as a low-rate bearing/class token.

**Multi-rate token interleaving.** ELLSA: fixed 1 s blocks, speech → image →
text → action with explicit idle tokens; the 0.48 s variant costs 4–13
points [P]. DuplexSLA: 160 ms chunks, ≤ 10 action-channel tokens per chunk
(≤ 62.5 tok/s), a 2-chunk delayed transcript, idle chunks emit
`<vad_silence>`; the backbone is 7B (the "77B" was a parse artefact) [S].
Moshi pads the text stream ~65 % with PAD tokens to reconcile 3–4 text
tokens/s with 12.5 Hz audio [S]. Real-Time Chunking [S]: freeze the first
d = ⌊δ/dt⌋ actions of the next chunk and inpaint the rest → no degradation
under 320 ms inference delay at 50 Hz. → One block = LCM(100, 80, ~1000 ms)
= 400 ms: 4 act tokens + 5 audio features + a capped plan slot, every lane
filled with an explicit idle token, a one-block delay line for the plan
lane, and no 8B-class interleaved model at 10 Hz on the Orin.

**Go2 SDK2 and shielding.** Since firmware V1.1.6 the sport-mode `Move` is
held for 1 s after the last message; Unitree instructs filtering velocities
before sending and `Move(0,0,0)` / `StopMove()` when idle; limits vx
[−2.5, 3.8], vy [−1, 1], vyaw [−4, 4] [S]. In `unitree_sdk2py` `Move` is
fire-and-forget while `Euler` and `StopMove` are blocking RPCs with a 1 s
default timeout; nothing locks `_Call`/`_CallNoReply` [S]; cyclonedds-python
listeners run synchronously under mutexes (writing from a callback can
deadlock) [S]. REASAN's learned shield maps 180 rays + the nominal velocity to
a safe (vx, vy, wz) at 50 Hz on the Orin [P]. → The gateway owns a 200–300 ms
watchdog that zeroes `Move` under the 1 s hold, clamps and slew-limits in the
act-token decoder, runs a velocity-layer shield in the 10 Hz tick, serialises
all sport calls through one thread, and never writes from a DDS callback.

**Starlink and hosted-session lifetime.** Starlink latency has a
deterministic 15 s period with a +74 ms spike at the start of each period
(~215 ms of boundary per period) [P]; voice/video breaks on link gaps > ~1 s
while < 0.5 s is absorbed; 2022–23 outages averaged 6.5 s [S]; a moving
terminal spent ~2.7 % of a 5-hour drive in outage, mostly transient sky-search
[S]. OpenAI Realtime sessions are hard-capped at 60 min (`session_expired`;
Azure now 60 too), 32 K context, and automatic truncation busts the prompt
cache [P]; byte-identical instruction prefixes ≥ 1,024 tokens are cached at
0.1× across sessions [n/v]; Gemini Live's binding limit is the ~10-minute
connection (GoAway ~60 s before), with resumption tokens and context
compression [n/v]. → Model A's 10 Hz loop never touches the link; plan-lane
requests avoid the 15 s boundary windows; WebRTC with a 100–150 ms jitter
buffer; local VAD/barge-in stays authoritative; proactive session rotation at
a natural pause well before 60 min with a text summary + last N turns
replayed and a byte-identical instruction block.
