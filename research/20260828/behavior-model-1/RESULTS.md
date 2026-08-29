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
{
 "seed": 20260828,
 "python": "3.14.4",
 "torch": "2.13.0+cu130",
 "decoding_rule": "A4: argmax over class-weighted CE (w_c ~ n_c^-0.5); no dev-tuned per-class thresholds",
 "evidence_tier": "desktop-sim (synthetic token world, no physics/sensors)",
 "splits": {
  "train": {
   "episodes": 3000,
   "frames": 3619357
  },
  "dev": {
   "episodes": 500,
   "frames": 604168
  },
  "frozen": {
   "episodes": 1280,
   "frames": 1541724
  }
 },
 "total_wall_s": 416.9,
 "host_at_end": {
  "load_1min": 22.41,
  "nvidia_smi_util_mem": "89 %, 3616 MiB, 32760 MiB",
  "gpu_processes": "197110 227 MiB; 2743734 26 MiB; 2862102 28 MiB; 4147151 1484 MiB",
  "time": "2026-08-29 03:14:39"
 },
 "ce_alpha": 0.5
}
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

| arm | M1 acc | (a) chuckle F1 | (b) look-back F1 | (c) comply F1 | (d) comfort F1 | false-chuckle | M3 raw | stop-comply |
|---|---|---|---|---|---|---|---|---|
| TEACHER (upper bound) | 1.0000 | 1.000 | 1.000 | 1.000 | 1.000 | 0.000 | 0.00000 | 0.988 |
| CEILING A1 (teacher on the observed cue stream) | 0.9888 | 0.843 | 1.000 | 0.903 | 0.934 | 0.000 | 0.00000 | 0.988 |
| ref ALWAYS-IDLE | 0.9693 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.00000 | 1.000 |
| ref CHUCKLE-AT-EVERY-PUNCHLINE | 0.9667 | 0.134 | 0.000 | 0.000 | 0.000 | 0.870 | 0.00245 | 0.990 |
| A rule baseline (arbiter) | 0.9419 | 0.036 | 0.003 | 0.901 | 0.046 | 0.072 | 0.00000 | 0.906 |
| A' reflex table (A2) | 0.9722 | 0.773 | 0.129 | 0.902 | 0.933 | 0.003 | 0.00000 | 1.000 |
| E frame MLP (A2) | 0.9271 | 0.001 | 0.114 | 0.000 | 0.030 | 0.000 | 0.00000 | 0.972 |
| B GRU 2x256 | 0.9721 | 0.631 | 0.893 | 0.752 | 0.778 | 0.070 | 0.00005 | 0.944 |
| C BehaviorFormer (CE alpha=0.5) | 0.9404 | 0.474 | 0.961 | 0.779 | 0.929 | 0.010 | 0.00069 | 0.787 |

Event counts behind the frozen rows:

| behaviour | events | detected-cue anchors (A1) |
|---|---|---|
| chuckle | 1949 | 1692 |
| lookback | 1163 | 1163 |
| comply | 4597 | 4030 |
| comfort | 928 | 809 |
| non-funny punchlines | 2275 | - |
| cmd:stop cues | 574 | - |

## 5. Dev

| arm | M1 acc | (a) chuckle F1 | (b) look-back F1 | (c) comply F1 | (d) comfort F1 | false-chuckle | M3 raw | stop-comply |
|---|---|---|---|---|---|---|---|---|
| TEACHER (upper bound) | 1.0000 | 1.000 | 1.000 | 1.000 | 1.000 | 0.002 | 0.00000 | 0.985 |
| CEILING A1 (teacher on the observed cue stream) | 0.9892 | 0.848 | 1.000 | 0.905 | 0.923 | 0.002 | 0.00000 | 0.985 |
| ref ALWAYS-IDLE | 0.9692 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.00000 | 1.000 |
| ref CHUCKLE-AT-EVERY-PUNCHLINE | 0.9671 | 0.156 | 0.000 | 0.000 | 0.000 | 0.866 | 0.00211 | 1.000 |
| A rule baseline (arbiter) | 0.9421 | 0.026 | 0.003 | 0.901 | 0.083 | 0.079 | 0.00000 | 0.888 |
| A' reflex table (A2) | 0.9729 | 0.772 | 0.106 | 0.904 | 0.921 | 0.000 | 0.00000 | 0.995 |
| E frame MLP (A2) | 0.9280 | 0.009 | 0.140 | 0.000 | 0.020 | 0.000 | 0.00000 | 0.985 |
| B GRU 2x256 | 0.9728 | 0.669 | 0.881 | 0.828 | 0.748 | 0.064 | 0.00077 | 0.944 |
| C BehaviorFormer (CE alpha=0.5) | 0.9381 | 0.503 | 0.960 | 0.789 | 0.925 | 0.018 | 0.00047 | 0.801 |

## 6. AMENDED M2 (A1): detected-cue anchors only, frozen split

Anchors whose cue the classifier missed or mislabelled are removed from the
event set, and emissions inside their windows are neither credited nor
penalised.

| arm | M1 acc | (a) chuckle F1 | (b) look-back F1 | (c) comply F1 | (d) comfort F1 | false-chuckle | M3 raw | stop-comply |
|---|---|---|---|---|---|---|---|---|
| TEACHER (upper bound) | 1.0000 | 1.000 | 1.000 | 1.000 | 1.000 | 0.000 | 0.00000 | 0.988 |
| CEILING A1 (teacher on the observed cue stream) | 0.9888 | 0.910 | 1.000 | 0.969 | 0.997 | 0.000 | 0.00000 | 0.988 |
| ref ALWAYS-IDLE | 0.9693 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.00000 | 1.000 |
| ref CHUCKLE-AT-EVERY-PUNCHLINE | 0.9667 | 0.139 | 0.000 | 0.000 | 0.000 | 0.870 | 0.00245 | 0.990 |
| A rule baseline (arbiter) | 0.9419 | 0.031 | 0.003 | 0.967 | 0.047 | 0.072 | 0.00000 | 0.906 |
| A' reflex table (A2) | 0.9722 | 0.828 | 0.129 | 0.967 | 0.995 | 0.003 | 0.00000 | 1.000 |
| E frame MLP (A2) | 0.9271 | 0.001 | 0.114 | 0.001 | 0.032 | 0.000 | 0.00000 | 0.972 |
| B GRU 2x256 | 0.9721 | 0.660 | 0.893 | 0.815 | 0.778 | 0.070 | 0.00005 | 0.944 |
| C BehaviorFormer (CE alpha=0.5) | 0.9404 | 0.496 | 0.961 | 0.843 | 0.929 | 0.010 | 0.00069 | 0.787 |

## 7. M5 — generalization slices (frozen)

`frozen_core` = seen families/profiles/phrasings · `frozen_family` = the two
never-trained compositions (`joke_while_lost`, `command_during_chuckle`) ·
`frozen_profile` = 10 held-out owner-taste masks · `frozen_phrasing` = held-out
surface phrasings.

**(a) chuckle**

| arm | frozen_core | frozen_family | frozen_profile | frozen_phrasing | pooled frozen |
|---|---|---|---|---|---|
| TEACHER (upper bound) | 1.000 (n=390) | 1.000 (n=637) | 1.000 (n=468) | 1.000 (n=454) | 1.000 |
| CEILING A1 (teacher on the observed cue stream) | 0.831 (n=390) | 0.802 (n=637) | 0.873 (n=468) | 0.879 (n=454) | 0.843 |
| ref ALWAYS-IDLE | 0.000 (n=390) | 0.000 (n=637) | 0.000 (n=468) | 0.000 (n=454) | 0.000 |
| ref CHUCKLE-AT-EVERY-PUNCHLINE | 0.134 (n=390) | 0.118 (n=637) | 0.157 (n=468) | 0.139 (n=454) | 0.134 |
| A rule baseline (arbiter) | 0.053 (n=390) | 0.038 (n=637) | 0.022 (n=468) | 0.032 (n=454) | 0.036 |
| A' reflex table (A2) | 0.799 (n=390) | 0.737 (n=637) | 0.790 (n=468) | 0.785 (n=454) | 0.773 |
| E frame MLP (A2) | 0.000 (n=390) | 0.000 (n=637) | 0.000 (n=468) | 0.004 (n=454) | 0.001 |
| B GRU 2x256 | 0.659 (n=390) | 0.578 (n=637) | 0.663 (n=468) | 0.662 (n=454) | 0.631 |
| C BehaviorFormer (CE alpha=0.5) | 0.488 (n=390) | 0.457 (n=637) | 0.482 (n=468) | 0.481 (n=454) | 0.474 |

**(b) look-back**

| arm | frozen_core | frozen_family | frozen_profile | frozen_phrasing | pooled frozen |
|---|---|---|---|---|---|
| TEACHER (upper bound) | 1.000 (n=243) | 1.000 (n=346) | 1.000 (n=291) | 1.000 (n=283) | 1.000 |
| CEILING A1 (teacher on the observed cue stream) | 1.000 (n=243) | 0.999 (n=346) | 1.000 (n=291) | 1.000 (n=283) | 1.000 |
| ref ALWAYS-IDLE | 0.000 (n=243) | 0.000 (n=346) | 0.000 (n=291) | 0.000 (n=283) | 0.000 |
| ref CHUCKLE-AT-EVERY-PUNCHLINE | 0.000 (n=243) | 0.000 (n=346) | 0.000 (n=291) | 0.000 (n=283) | 0.000 |
| A rule baseline (arbiter) | 0.005 (n=243) | 0.000 (n=346) | 0.004 (n=291) | 0.004 (n=283) | 0.003 |
| A' reflex table (A2) | 0.116 (n=243) | 0.136 (n=346) | 0.124 (n=291) | 0.138 (n=283) | 0.129 |
| E frame MLP (A2) | 0.110 (n=243) | 0.107 (n=346) | 0.110 (n=291) | 0.130 (n=283) | 0.114 |
| B GRU 2x256 | 0.900 (n=243) | 0.888 (n=346) | 0.897 (n=291) | 0.889 (n=283) | 0.893 |
| C BehaviorFormer (CE alpha=0.5) | 0.943 (n=243) | 0.966 (n=346) | 0.958 (n=291) | 0.972 (n=283) | 0.961 |

**(c) command compliance**

| arm | frozen_core | frozen_family | frozen_profile | frozen_phrasing | pooled frozen |
|---|---|---|---|---|---|
| TEACHER (upper bound) | 1.000 (n=871) | 0.999 (n=1616) | 1.000 (n=1096) | 1.000 (n=1014) | 1.000 |
| CEILING A1 (teacher on the observed cue stream) | 0.897 (n=871) | 0.909 (n=1616) | 0.906 (n=1096) | 0.898 (n=1014) | 0.903 |
| ref ALWAYS-IDLE | 0.000 (n=871) | 0.000 (n=1616) | 0.000 (n=1096) | 0.000 (n=1014) | 0.000 |
| ref CHUCKLE-AT-EVERY-PUNCHLINE | 0.000 (n=871) | 0.000 (n=1616) | 0.000 (n=1096) | 0.000 (n=1014) | 0.000 |
| A rule baseline (arbiter) | 0.894 (n=871) | 0.908 (n=1616) | 0.902 (n=1096) | 0.896 (n=1014) | 0.901 |
| A' reflex table (A2) | 0.895 (n=871) | 0.907 (n=1616) | 0.903 (n=1096) | 0.897 (n=1014) | 0.902 |
| E frame MLP (A2) | 0.000 (n=871) | 0.000 (n=1616) | 0.002 (n=1096) | 0.000 (n=1014) | 0.000 |
| B GRU 2x256 | 0.819 (n=871) | 0.620 (n=1616) | 0.803 (n=1096) | 0.815 (n=1014) | 0.752 |
| C BehaviorFormer (CE alpha=0.5) | 0.787 (n=871) | 0.778 (n=1616) | 0.783 (n=1096) | 0.768 (n=1014) | 0.779 |

**(d) comfort**

| arm | frozen_core | frozen_family | frozen_profile | frozen_phrasing | pooled frozen |
|---|---|---|---|---|---|
| TEACHER (upper bound) | 1.000 (n=268) | n/a (n=0) | 1.000 (n=337) | 1.000 (n=323) | 1.000 |
| CEILING A1 (teacher on the observed cue stream) | 0.931 (n=268) | n/a (n=0) | 0.935 (n=337) | 0.936 (n=323) | 0.934 |
| ref ALWAYS-IDLE | 0.000 (n=268) | n/a (n=0) | 0.000 (n=337) | 0.000 (n=323) | 0.000 |
| ref CHUCKLE-AT-EVERY-PUNCHLINE | 0.000 (n=268) | n/a (n=0) | 0.000 (n=337) | 0.000 (n=323) | 0.000 |
| A rule baseline (arbiter) | 0.057 (n=268) | n/a (n=0) | 0.030 (n=337) | 0.052 (n=323) | 0.046 |
| A' reflex table (A2) | 0.931 (n=268) | n/a (n=0) | 0.934 (n=337) | 0.933 (n=323) | 0.933 |
| E frame MLP (A2) | 0.048 (n=268) | n/a (n=0) | 0.016 (n=337) | 0.030 (n=323) | 0.030 |
| B GRU 2x256 | 0.764 (n=268) | n/a (n=0) | 0.781 (n=337) | 0.785 (n=323) | 0.778 |
| C BehaviorFormer (CE alpha=0.5) | 0.913 (n=268) | n/a (n=0) | 0.931 (n=337) | 0.942 (n=323) | 0.929 |

## 8. A2 — anticipatory chuckle (the sub-behaviour that needs the history channel)

| arm | anticipatory-chuckle F1 (frozen) | on held-out-family slice |
|---|---|---|
| TEACHER (upper bound) | 1.000 (n=415) | 1.000 |
| CEILING A1 (teacher on the observed cue stream) | 0.893 (n=418) | 0.868 |
| ref ALWAYS-IDLE | 0.000 (n=415) | 0.000 |
| ref CHUCKLE-AT-EVERY-PUNCHLINE | 0.884 (n=457) | 0.851 |
| A rule baseline (arbiter) | 0.122 (n=417) | 0.108 |
| A' reflex table (A2) | 0.440 (n=422) | 0.448 |
| E frame MLP (A2) | 0.005 (n=415) | 0.000 |
| B GRU 2x256 | 0.153 (n=422) | 0.181 |
| C BehaviorFormer (CE alpha=0.5) | 0.094 (n=424) | 0.093 |

## 9. Training budgets (A6)

| arm | steps | frames/step | epoch-equivalents | wall (s) | stopped by | final loss | GPU peak (MB) | params |
|---|---|---|---|---|---|---|---|---|
| E frame MLP (A2) | 4000 | 8192 | 9.05 | 24.3 | steps | 1.0152840614318848 | 502.6 | 808305 |
| B GRU 2x256 | 23070 | 24576 | 156.65 | 411.6 | steps | 0.02229953557252884 | 837.8 | 932721 |
| C BehaviorFormer (CE alpha=0.5) | 9065 | 32768 | 82.07 | 1175.7 | steps | 0.09989242255687714 | 4197.4 | 4915057 |

## 10. M4 — batch-1 inference latency

| arm | GPU p50 / p99 (ms) | CPU 1-thread p50 / p99 (ms) | n | bar |
|---|---|---|---|---|
| A rule baseline (arbiter) | n/a | 0.008 / 0.008 | 2000 | (no bar) |
| E frame MLP (A2) | 0.45 / 0.66 | 0.248 / 0.301 | 2000 | (no bar) |
| B GRU 2x256 | 0.52 / 0.66 | 0.278 / 0.314 | 2000 | p99 GPU <= 20 ms, CPU <= 60 ms |
| C BehaviorFormer (CE alpha=0.5) | 1.74 / 2.05 | 13.197 / 15.145 | 2000 | p99 GPU <= 20 ms, CPU <= 60 ms |

## 11. M3 / A7 — safety accounting (frozen)

| arm | crit frames | M3 raw (emote/skill under critical) | A7 twist under busy/critical | A7 non-idle after cmd:stop | locomotion-skill rate free / busy / critical |
|---|---|---|---|---|---|
| TEACHER (upper bound) | 93037 | 0 (0.00000) | 427 (0.00113) | 0/574 | 0.00184 / 0.00171 / 0.00000 |
| CEILING A1 (teacher on the observed cue stream) | 93037 | 0 (0.00000) | 430 (0.00114) | 0/574 | 0.00176 / 0.00161 / 0.00000 |
| ref ALWAYS-IDLE | 93037 | 0 (0.00000) | 0 (0.00000) | 0/574 | 0.00000 / 0.00000 / 0.00000 |
| ref CHUCKLE-AT-EVERY-PUNCHLINE | 93037 | 228 (0.00245) | 0 (0.00000) | 2/574 | 0.00000 / 0.00000 / 0.00000 |
| A rule baseline (arbiter) | 93037 | 0 (0.00000) | 0 (0.00000) | 0/574 | 0.00176 / 0.00163 / 0.00000 |
| A' reflex table (A2) | 93037 | 0 (0.00000) | 0 (0.00000) | 0/574 | 0.00176 / 0.00163 / 0.00000 |
| E frame MLP (A2) | 93037 | 0 (0.00000) | 3863 (0.01024) | 13/574 | 0.00000 / 0.00000 / 0.00000 |
| B GRU 2x256 | 93037 | 5 (0.00005) | 431 (0.00114) | 17/574 | 0.00193 / 0.00194 / 0.00000 |
| C BehaviorFormer (CE alpha=0.5) | 93037 | 64 (0.00069) | 1306 (0.00346) | 107/574 | 0.00504 / 0.00501 / 0.00036 |

## 12. A8 reporting slices

### A8.1 — (b) look-back split by bearing sector

Bearings are 8 bins of 45 deg, so `|bearing| <= 40 deg` selects **bin 0 only**;
everything else needs a base rotation on a neckless Go2. The front cell is
therefore a small sample and is reported with its n.

| arm | front (bearing bin 0) | rear / side (bins 1-7) |
|---|---|---|
| TEACHER (upper bound) | 1.000 (n=145) | 1.000 (n=1018) |
| CEILING A1 (teacher on the observed cue stream) | 0.997 (n=145) | 1.000 (n=1018) |
| ref ALWAYS-IDLE | 0.000 (n=145) | 0.000 (n=1018) |
| ref CHUCKLE-AT-EVERY-PUNCHLINE | 0.000 (n=145) | 0.000 (n=1018) |
| A rule baseline (arbiter) | 0.000 (n=145) | 0.004 (n=1018) |
| A' reflex table (A2) | 0.000 (n=145) | 0.148 (n=1018) |
| E frame MLP (A2) | 0.350 (n=145) | 0.074 (n=1018) |
| B GRU 2x256 | 0.873 (n=145) | 0.894 (n=1018) |
| C BehaviorFormer (CE alpha=0.5) | 0.929 (n=145) | 0.965 (n=1018) |

### A8.2 — cue source tag

**The generator does not know who spoke.** Every cue in `worldsim.py` is an
owner utterance reaching the dog through a cue classifier over ASR/prosody;
there is no `self_speech` cue and no dog-speech act channel. The modelled
detector latency is **1-5 frames (0.1-0.5 s)**, which is the *self-speech*
regime; real owner ASR adds 0.5-1.5 s. So every timing bar reported here is
optimistic by roughly one reaction window for owner-ASR cues, and the
chuckle/comply windows in particular would have to widen on real audio.
Registered as BM-1b follow-up.

### A8.3 — product-available channels only (frozen, no retrain)

_not computed_

### A8.4 — scored events occurring while `base_busy != free`

| behaviour | events | while base_busy != free | fraction |
|---|---|---|---|
| chuckle | 1949 | 430 | 0.221 |
| lookback | 1163 | 390 | 0.335 |
| comply | 4597 | 1046 | 0.228 |
| comfort | 928 | 112 | 0.121 |

The product bridge (`SocialReactionBridge.tick`) vetoes **all** social
reactions whenever `base_busy` is true, not only in the critical phase. The
fraction above is therefore the share of this experiment's scored expressive
events that today's product would suppress outright.

### A8.5 — how often the anticipatory-chuckle condition is satisfiable

Frozen split: **468 / 4803 punchlines = 9.7%** satisfy it.

`worldsim.py` implements the condition as: take the `hist_k` channel, which is
the **last 6 jokes globally** as `(category, laughed?)` pairs; filter to the
entries whose category matches the current punchline; take up to the last 3 of
those; fire if >= 2 of them were laughed at. So it is a *per-category filter
over a global 6-slot window* -- with 6 joke categories, a category is often
absent from the window entirely, which is why only ~10 % of punchlines are
anticipatable. A per-category last-3 history (6 x 3 slots) would raise this
sharply and is the more faithful reading of DESIGN.md rule 1; recorded, not
changed.

### A8.6 — teacher token -> `ActTokenCodec` token

| teacher behaviour | act token | note |
|---|---|---|
| teacher: chuckle / comfort / greeting / ... (emote) | `<emote:NAME>` | the 20 `runtime.DEFAULT_EMOTES`, verbatim |
| teacher: gaze toward the last-known bearing | `<gaze_bearing_i>` | 8 bins; DESIGN.md wrote this `<gaze:b>` |
| teacher: gaze at the owner | `<gaze_owner>` | attention track |
| teacher: gaze aversion (`gaze:away` in DESIGN.md rule 4) | `<gaze_release>` | the codec has no `away` token |
| teacher: `attentive_stand` (DESIGN.md rule 4) | `<emote:attentive_nod>` | **`attentive_stand` does not exist in DEFAULT_EMOTES** |
| teacher: command compliance | `<skill:NAME>` | come / fetch / follow / go_to / shake_paw / sit / stay |
| teacher: `cmd:stop` | `<idle>` | scored separately (A7), not in headline (c) |
| teacher: turn back toward the owner, slow approach | `<twist:i:j>` | 7x5 bins from `default_twist_bins()` |
| teacher: thinking filler | `<filler_gesture_0>` | liveness rule 5 |


**Capability-proof check (read-only import of the product package):** the harness vocabulary is byte-identical to `ActTokenCodec(...).vocabulary()` (81/81, identical=True) and **every one of the 81 tokens decodes via `ActTokenCodec.decode()` without raising**. Run it with `python extras.py`.

### A8.7 — evidence tier

`desktop-sim (synthetic token world, no physics/sensors)`

### Arm D evaluation scale


## 13. Pre-registered criterion — met / not met

{}

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
