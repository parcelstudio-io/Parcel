# BM-1 — a trainable full-duplex behavior model over the state of the world

Author: Fable (parcel-0e), 2026-08-28. Pre-registered before any run.
Evidence tier: `desktop-sim` (procedural world simulator, this host's GPU).
Status of physical motion: unchanged — **NO-GO**. Nothing here gains authority.

## Hypothesis (falsifiable)

**H-BM1.** A small causal sequence model, trained by behavior cloning from an
ethology-grounded scripted teacher on a procedurally generated
*state-of-the-world* token stream (10 Hz, the existing `DuplexFrame` clock),
learns context-dependent expressive behavior — chuckle after a funny
punchline, look back at the owner when the owner is lost, comply with a spoken
command, comfort a sad owner — and **generalizes to held-out scenario
compositions and held-out command phrasings** that the current
context-blind reaction arbiter cannot express.

Refuted if, on the frozen test split, the best learned model does not reach the
success bars below, or does not beat the rule baseline by the pre-registered
margin.

## Why this experiment (rationale)

The dog today picks from strict commands. `logs/duplex/` (1,024,983 frames
across 17,237 sessions, measured 2026-08-28) shows expressive activity is
98 % a single emote (`excited_paw_taps`, 33,828 frames, every one triggered by
`inferred_affect`), 2,023 frames carry any text, and the reaction arbiter
selects by `base_rate × temperament` with no conditioning on *what was said*
or *where the owner is*. The missing piece is a policy that reads the whole
state and emits the next act token every frame — the same object a
full-duplex speech model emits for audio, applied to the body.

## What is fixed before the run

### Frame schema — the "state of the world" at 10 Hz

Every frame is a fixed group of categorical channels. Two serializations of
the same frame are produced by one function: (i) integer token ids per
channel (for from-scratch models); (ii) one compact text line (for the
pretrained-LM arm). Channels:

| channel | vocabulary | source in the product |
|---|---|---|
| `dlg` | idle / listening / thinking / speaking | `DialogueStateChannel` |
| `cue` | none / owner_speaking / joke_setup / joke_punchline / question / praise / scold / greeting / call_name / laugh / sigh / cmd:<name> | `SocialCueV1.kind` + ASR |
| `cue_conf` | lo / mid / hi | `SocialCueV1.confidence` |
| `val`, `aro` | valence −2..2, arousal 0..2 | `SocialCueV1` |
| `own_vis` | visible / occluded / unknown | owner tracker |
| `own_dist` | near / mid / far / unknown | owner tracker |
| `own_bear` | 8 bearing bins / unknown | owner tracker |
| `own_gaze` | at_dog / away / unknown | camera (design placeholder) |
| `own_motion` | still / walking / approaching / leaving | owner tracker |
| `t_since_seen` | <1 s / 1–3 s / 3–8 s / 8–20 s / >20 s | derived |
| `self_act` | idle / emote:<name> / skill:<name> / navigating / following / hold | executive |
| `base_busy` | free / busy / critical | `ResourceLocks` |
| `loc_health` | ok / degraded / lost | localization latch |
| `task` | none / follow / go_to / come / stay / search_owner | executive |
| `task_state` | idle / progressing / blocked / done | receipts |
| `env` | kitchen / living / hall / outdoor | semantic map |
| `obstacle` | none / ahead / doorway | local planner |
| `people` | 0 / 1 / 2+ | perception |
| `hist_k` | last K=6 (joke_category, owner_laughed?) pairs | owner model |
| `profile` | 4 categorical owner-model facts (greeting style, praise habit, pace preference, sensitivity) | owner model |
| `words` | (LM arm only) the raw transcript words of the current utterance, procedurally paraphrased | ASR |

Output per frame — one act token from the **existing** `ActTokenCodec`
vocabulary: `<idle>`, `<twist:i:j>` (7×5 bins), `<gaze:b>` (8 bins),
`<skill:name>`, `<emote:name>` (the 20 `DEFAULT_EMOTES`), `<filler_gesture:k>`.
The model never emits a joint, velocity value, or anything outside this
vocabulary; a deterministic filter (`tracks_are_social_safe`-equivalent) drops
any emote/skill while `base_busy=critical`, and the filtered rate is reported.

### Teacher (the scripted "ideal dog") — ethology-grounded, stochastic

Rules with pre-registered timing; personality parameters sampled per episode:

1. **Chuckle.** After `joke_punchline`, if the owner laughs within 2 s → emote
   `chuckle` within 0.3–1.0 s of the laugh (reactive). If the punchline's
   joke category is one this owner has laughed at ≥ 2 of the last 3 times
   (from `hist_k`) → anticipatory `chuckle` 0.3–1.0 s after the punchline,
   before the laugh. Never twice within 5 s (habituation). Never while
   `base_busy=critical` or a `cmd` is pending.
2. **Look back when lost.** While `task ∈ {follow, go_to}` and the owner
   becomes not-visible: at `t_since_seen ≥ 3 s` → `<gaze:last_bearing>`
   (look back) and `<idle>` (pause); at `≥ 8 s` still unseen → turn toward the
   last bearing (`<twist:0:±yaw>`) then `confused_head_tilt`; when the owner
   reappears → `attentive_nod` and resume. When `task_state=blocked` → look at
   the owner (gaze alternation, the unsolvable-task behavior).
3. **Comply.** `cmd:<name>` → the matching `<skill:…>` within 0.5 s,
   pre-empting any emote; `cmd:stop` → `<idle>` next frame.
4. **Social reactions.** greeting → `hello_pose` / `paw_wave`; praise →
   `happy_wiggle` or `attentive_nod`; sad owner (val ≤ −1, aro 0) →
   `comfort_bow` then slow approach if far; excited owner (val ≥ 1, aro 2) →
   `excited_paw_taps`; question → `observing_head_tilt` while `dlg=thinking`;
   scold → `<idle>` + gaze aversion (`<gaze:away>`); `call_name` → gaze to the
   owner + `attentive_stand`.
5. **Liveness.** `dlg=listening` → mostly `<idle>` with gaze at the owner;
   long idle (> 20 s) → `stretch` or `curious_look` with small probability.

### World generator

Episodes of 60–180 s (600–1,800 frames). Sampled: owner profile (humor taste
over 6 joke categories, drawn from a taste prior; greeting/praise style),
room, task, owner trajectory (walks, stops, disappears behind occluders),
dialogue script (jokes with category, questions, praise, scolds, commands
including interrupts mid-emote), cue-detector noise (latency 1–5 frames,
10 % false negatives, 3 % false positives, confidence bins), visibility
flicker. Scenario **families** are named (e.g. `joke_while_following`,
`lost_outdoors`, `command_during_emote`, `sad_owner_far`,
`joke_while_lost`).

Splits by family and by profile with leakage groups: train 70 % / dev 15 % /
**frozen test 15 %**, where the frozen test additionally holds out (a) two
whole families never seen in training (`joke_while_lost`,
`command_during_chuckle`), (b) 20 % of owner-taste profiles, (c) for the LM
arm, 30 % of command/joke *phrasings*. Seeds fixed; the generator is
deterministic given the seed.

### Arms

- **A — rule baseline (today's shape).** Context-blind stochastic arbiter:
  per-emote `base_rate × gains` with cooldowns, calibrated to the teacher's
  marginal emote rates; obeys `cmd` (the deterministic router does that today).
- **B — GRU** (2 × 256) over per-channel embeddings, frame-level cross-entropy.
- **C — BehaviorFormer**: causal transformer from scratch (6 layers, d=256,
  4 heads, context 128 frames = 12.8 s), same inputs/targets.
- **D — pretrained LM + LoRA** (Qwen2.5-0.5B-Instruct or SmolLM2-360M-Instruct,
  whichever downloads first), input = the last 32 frames as text lines
  *including raw words*, target = the next act token as text. LoRA r=16 on
  attention+MLP, bf16, ≤ 12 GB GPU.

Same training frames, same seeds, same wall budget (≤ 45 min per arm on this
GPU); B/C are also evaluated on CPU single-thread for latency.

### Measurements

- **M1** frame-level act accuracy vs the teacher (dev, frozen).
- **M2 (primary) event-conditional behavior scores** on the frozen split,
  each an F1 over events with a timing window: (a) `chuckle` within
  [0.3, 1.5] s after a laugh or an anticipatable punchline; (b) look-back
  (`gaze` toward last bearing) within [3, 5] s of losing the owner while
  following; (c) command compliance within 0.5 s; (d) comfort (`comfort_bow`)
  within 2 s of a sad cue. Plus **false-chuckle rate** = chuckles per
  non-funny punchline (owner does not laugh, category unliked).
- **M3** raw safety-violation rate = emote/skill tokens emitted while
  `base_busy=critical` before the filter; post-filter must be 0 by
  construction (asserted).
- **M4** per-frame inference latency at batch 1: GPU (this host) and CPU
  single-thread, p50/p99 over 2,000 frames.
- **M5** generalization slices: held-out families, held-out profiles,
  held-out phrasings (D only vs C with cue tokens).

### Success criterion (pre-registered)

H-BM1 is **CONFIRMED** if the best learned arm on the frozen split reaches
M2 F1 ≥ 0.85 on (a), (b), (c) simultaneously, false-chuckle ≤ 0.05, exceeds
arm A by ≥ 0.30 absolute F1 on (a) and (b), raw M3 ≤ 1 %, and B/C p99 GPU
latency ≤ 20 ms (CPU ≤ 60 ms). **PARTIAL** if the bars hold on dev but not on
the held-out families (then the finding is "memorizes families"). **REFUTED**
otherwise. Arm D is reported on the same bars plus the held-out-phrasing
slice; it has its own latency bar (p99 ≤ 100 ms GPU).

## What it does NOT prove

Nothing about physics, gait, real perception, real ASR, real laughter
detection, the Go2, or the Orin. The teacher's rules are authored; a high
score means the policy learned *the authored world*, and the interesting
claim is only the held-out-composition/phrasing generalization. Latency is a
desktop proxy. No product path is exercised: the codec vocabulary and frame
schema are copied by name, not imported into a product caller.

## OWNS / must not touch

OWNS: `research/20260828/behavior-model-1/**` only. Must not touch:
anything under `src/`, `tests/`, `gateway/`, `logs/`, other research folders,
git. Reads of `src/parcel_robot/duplex/{act_codec,frames}.py`,
`runtime.py` (DEFAULT_EMOTES), `contracts/v1.py` are allowed for vocabulary.

## Reproduction

`~/.cache/parcel-0e/venv/bin/python research/20260828/behavior-model-1/run.py --arm all --seed 20260828`
writes `results.json` (+ per-arm JSON) and RESULTS.md is written from those
numbers only.
