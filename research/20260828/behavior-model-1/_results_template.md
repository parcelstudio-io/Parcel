# BM-1 — RESULTS

Executor: Opus (parcel-0e). Written from `results.json` only; `report.py`
regenerates this file, so it is reproducible from the artefacts.
**Evidence tier: `desktop-sim` (synthetic token world, no physics, no sensors,
no ASR, no laughter detector).** Verdict is Fable's (`VERDICT.md`); nothing
below is a verdict.

Status of physical motion: unchanged — **NO-GO**. Nothing here gains authority;
no product caller is exercised.

## 1. What was run

| | |
|---|---|
| world | `worldsim.py`, 10 Hz `DuplexFrame` clock, 29 categorical channels, 81 act tokens |
| act vocabulary | rebuilt by name from `ActTokenCodec`; **verified identical (81/81) to the product codec and every token decodes** (A8.6) |
| training data | 3,000 episodes / 3,619,357 frames (7 families, train-allowed profiles + phrasings) |
| dev | 500 episodes / 604,168 frames |
| frozen | 1,280 episodes / 1,541,724 frames in 4 named slices (see §7) |
| generation | deterministic from `(master_seed, split, index)`; whole corpus regenerates in ~5 s on 32 workers |
| environment | `~/.cache/parcel-0e/venv` (Python 3.14, torch 2.13+cu130, transformers 5.16, peft 0.20), one RTX 5000 Ada, 12 GB cap |
| hosted API calls | **none** ($0.00) |

```
{{META}}
```

## 2. Amendments (AMENDMENTS.md, POST-START)

| id | applied? | how |
|---|---|---|
| A1 clock + ceiling | **yes** | every anchor is an observation-stream frame; anchors are additionally tagged `det_*` (the cue classifier actually fired) and an AMENDED detected-only M2 is reported beside the original; the CEILING row is the same scripted teacher re-run driven **only** by the detected cue channel |
| A2 real baselines | **yes** | arm A′ (deterministic reflex table over the current frame, teacher timings from the observable `prof_pace` channel, one-frame edge detector, no memory) and arm E (frame-level MLP, no context) |
| A3 verdict on the held-out slice | **yes** | per-slice tables in §7; slices topped up from NEW seed indices (episode *i* keeps its seed, so every pre-amendment episode is bit-identical — verified) until each scored sub-score had ≥ 200 events. **Not achievable for (d) comfort on the held-out-family slice**: `joke_while_lost` and `command_during_chuckle` contain no sad-owner cue by construction, so that cell is `n/a (n=0)`, not a low score |
| A4 decoding pre-registered | **yes** | see §3 |
| A5 phrasing without leakage | **partial** | the cue-masked phrasing pass is run for arm D; **the split holds out surface strings, not paraphrase templates** (the fragments are shared), and a template-held-out slice was NOT added — reported as such with the 4-gram overlap |
| A6 budgets + latency hygiene | **yes** | optimizer steps/epoch-equivalents in §9; every latency row records load, GPU utilisation and co-resident processes |
| A7 safety accounting + stop | **yes** | amended filter and M3 cover `<twist>` under `busy`/`critical` and the frame after `cmd:stop`; `cmd:stop` scored separately and excluded from headline (c) |
| A8 reporting slices | **yes (7/7)** | §11 |

### Teacher priority order actually implemented (A3)

`worldsim.py` resolves competing scheduled acts by
`cmd:stop (0) > command compliance (1) > look-back / lost (2) > chuckle (3) >
social reaction (4) > liveness (5)`, and applies the critical-phase gate to
**every** body act *inside* that loop: a command is **deferred** one frame at a
time until `base_busy != critical` (its event anchor moves with it), while an
expressive act is **dropped**. So the implemented order is
`cmd > look-back > chuckle > social > liveness` with the safety filter
*outranking* cmd in the sense that it delays it — the amendment's phrasing
places the safety filter below cmd. **Difference recorded, frozen data not
changed.**

### Deviations from DESIGN.md (recorded, not corrected)

1. DESIGN.md writes the gaze token as `<gaze:b>`; the real `ActTokenCodec`
   emits `<gaze_bearing_i>`, `<gaze_owner>`, `<gaze_release>`. The codec's
   names are used (they are the product truth).
2. Rule 4 asks for `attentive_stand` on `call_name`; that emote does **not**
   exist in `runtime.DEFAULT_EMOTES`. `attentive_nod` is used instead.
3. Reaction latencies are drawn as `base(prof_pace) + jitter∈{0,1,2}`, all
   inside the DESIGN.md windows (chuckle 0.3–0.9 s, comply 0.2–0.5 s, comfort
   0.5–1.3 s). Conditioning the base delay on an **observable** channel is what
   makes the teacher reproducible under an argmax decode; a purely uniform
   latency would make the argmax of any well-calibrated policy `<idle>`.
4. Act tokens are **onsets**. The executive expands an emote over 8–15 frames
   and a skill over 15–40 frames; that expansion is visible to every arm in the
   `self_act` channel, and the teacher emits `<idle>` during it.
5. `cmd:stop` is excluded from the headline (c) F1 (its target is `<idle>`,
   which every arm emits on ~97 % of frames) and scored separately (A7).
6. The frozen split is four **named** sub-splits rather than one 15 % draw, and
   after the A3 top-up it is larger than 15 % of the corpus. Train is untouched.
7. **Evaluation is open-loop / teacher-forced.** Every arm is scored against the
   recorded observation stream, whose `self_act` channel is the *teacher's*
   executive state. The world does not react to the policy, so nothing here
   measures closed-loop drift.
8. Arm A applies the arbiter's `critical_phase` veto but not a veto on ordinary
   `base_busy` (the bridge vetoes on both). The looser choice is the one that
   makes arm A stronger.
9. Arm D's 32 history lines are **delta encoded** (only changed fields printed;
   `~` = unchanged), the frame to predict is printed in full. This is what makes
   32 frames fit in ~195 LM tokens instead of ~525.

## 3. Decoding rule, fixed before the frozen pass (A4)

> **argmax decoding of class-weighted cross-entropy models**
> (`w_c ∝ n_c^-0.5`, normalised to mean 1 over observed classes).
> No per-class threshold is tuned on dev. Arm D decodes greedily, which is the
> same rule. An **emission** is the *rising edge* of a token run
> (`pred[f] != pred[f-1]`); at most one emission is matched per event window and
> each emission matches at most one anchor.

Model selection during training used the dev *subset* composite
`mean(F1 a,b,c) − false-chuckle`; the frozen split was never touched during
training or selection.

## 4. Reference rows and the A1 ceiling

The pre-registered bars are absolute. The CEILING row shows what the **scripted
teacher itself** scores when it is restricted to the noisy channel view a policy
receives (10 % cue false negatives, 3 % mislabels, 1–5 frame detector latency).

{{TABLE_FROZEN}}

Event counts behind the frozen rows:

{{COUNTS_FROZEN}}

## 5. Dev

{{TABLE_DEV}}

## 6. AMENDED M2 (A1): detected-cue anchors only, frozen split

Anchors whose cue the classifier missed or mislabelled are removed from the
event set, and emissions inside their windows are neither credited nor
penalised.

{{TABLE_FROZEN_AMENDED}}

## 7. M5 — generalization slices (frozen)

`frozen_core` = seen families/profiles/phrasings · `frozen_family` = the two
never-trained compositions (`joke_while_lost`, `command_during_chuckle`) ·
`frozen_profile` = 10 held-out owner-taste masks · `frozen_phrasing` = held-out
surface phrasings.

**(a) chuckle**

{{SLICE_A}}

**(b) look-back**

{{SLICE_B}}

**(c) command compliance**

{{SLICE_C}}

**(d) comfort**

{{SLICE_D}}

## 8. A2 — anticipatory chuckle (the sub-behaviour that needs the history channel)

{{ANTIC}}

## 9. Training budgets (A6)

{{TRAINING}}

## 10. M4 — batch-1 inference latency

{{LATENCY}}

## 11. M3 / A7 — safety accounting (frozen)

{{SAFETY}}

## 12. A8 reporting slices

{{EXTRA}}

## 13. Pre-registered criterion — met / not met

{{CRITERIA}}

## 14. Surprises, limitations, and what these numbers do NOT show

See §2 deviations first. Beyond those:

- Nothing here touches physics, gait, real perception, real ASR, real laughter
  detection, the Go2 or the Orin. A high score means a policy learned *the
  authored world*.
- The world's cue-detector latency is 0.1–0.5 s. Real owner ASR adds
  0.5–1.5 s (A8.2), so every timing bar here is **optimistic** by roughly one
  reaction window.
- Evaluation is open-loop (deviation 7). A policy that would drift in closed
  loop scores the same here.
- Arm D is scored on a *subset* of episodes (compute-bound); its event counts
  are below A3's 200-event bar and are printed in the tables.
