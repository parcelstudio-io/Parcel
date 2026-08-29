# BM-1 amendments — POST-START (written 2026-08-28 17:57 from an independent three-lens design review; the executor had already generated the world and begun training)

Labeling rule: every number below is reported as an AMENDED row beside the
original pre-registered row; the verdict states which bar it used. No frozen
data is regenerated unless stated. Additive metrics need no retraining.

## A1 — clock and ceiling (bar restated)
All M2 windows anchor to the DETECTED-CUE frame (the frame where `cue` shows
the event), not the true event. Add a CEILING row: the teacher re-run on
exactly the noisy channel view the policy receives. Amended CONFIRM bar: the
best learned arm reaches ≥ 0.90 × ceiling on each of (a), (b), (c) — reported
beside the absolute 0.85 bar.

## A2 — real baselines (bar restated)
Add arm A′ = deterministic reflex table over the CURRENT frame's channels
with the teacher's timings and no history; add arm E = frame-level MLP (no
context). Amended CONFIRMED additionally requires the best sequence arm
(B/C/D) to beat A′ by ≥ 0.10 F1 on the held-out-family slice AND on
anticipatory-chuckle F1; if not, the pre-registered finding is "rules
suffice; the sequence model is not demonstrated".

## A3 — the verdict is read on the held-out slice
CONFIRMED is decided on the held-out-family slice (M5) separately from the
pooled frozen split. Report event counts per M2 sub-score per slice; if any
slice has < 200 events, generate additional frozen episodes of that family
from NEW seeds (never touching training) until it does, and record it.
Pre-registered teacher priority order for composed families: cmd > safety
filter > look-back > chuckle > social > liveness. Record what worldsim.py
implements; if different, report the difference (do not change frozen data).

## A4 — decoding pre-registered
Decoding = argmax with class-weighted cross-entropy, OR a per-class
threshold chosen on dev only and frozen before the test pass (state which,
once, before evaluating frozen). An emission = the rising edge of a token
run, at most one per event window. Reference rows: ALWAYS-IDLE and
CHUCKLE-AT-EVERY-PUNCHLINE, so the F1 floor is visible.

## A5 — phrasing slice without leakage (arm D)
On the held-out-phrasing slice feed D `words` with `cue` masked to `none`
and `cue_conf=lo` on command/joke frames; hold out paraphrase TEMPLATES, not
surface strings; report train/test 4-gram overlap for the slice. If the
current split holds out strings only, report it as such and add the
template-held-out slice from new seeds.

## A6 — budgets and latency hygiene
Report optimizer steps/epochs per arm (wall time secondary). Every latency
row records nvidia-smi utilization, co-resident processes, and 1-min load at
start and end. The verifier re-measures the headline latency row in
isolation at close.

## A7 — safety accounting and stop
Extend the deterministic filter and M3 to: any `<twist>` while `base_busy ∈
{busy, critical}`; any non-idle token in the frame after `cmd:stop`. Report
raw rates per arm and per base_busy state, and locomotion-skill emission
rates by base_busy state, for every arm AND the teacher. Score `cmd:stop`
separately as "no non-idle act for ≥ 5 frames after the cue" and exclude it
from the headline (c) F1.

## A8 — reporting slices (additive, no retraining)
1. M2(b) split by bearing sector: front (|bearing| ≤ 40°, executable as a
   head/body-yaw overlay) vs rear (requires base rotation on a neckless Go2).
2. Cue source tag `self_speech` vs `owner_asr` if the generator knows who
   spoke; if it does not, say so and report that the timing bars are
   meaningful only for self-speech cues (owner ASR adds 0.5–1.5 s).
3. "Product-available channels only" re-score of the frozen split with
   `own_gaze`, `hist_k`, `profile` masked to unknown (no retrain); any
   sub-score drop > 0.05 is stated as "depends on a signal the product cannot
   produce today".
4. Fraction of scored M2 events occurring while `base_busy != free` (the
   product bridge vetoes all social reactions there today).
5. Fraction of punchlines where the anticipatory condition is satisfiable
   under the implemented history channel; state which interpretation
   worldsim.py implements (last-6 global vs per-category).
6. Token mapping table (teacher token → ActTokenCodec token: gaze:away →
   <gaze_release>, gaze toward bearing → <gaze_bearing_i>, attentive_stand →
   <skill:attentive_stand>, etc.) and a one-line assertion that every emitted
   token decodes via `ActTokenCodec` (import read-only from the product
   package) without error.
7. Tier label in RESULTS/VERDICT: `desktop-sim (synthetic token world, no
   physics/sensors)`.

## Registered follow-ups (NOT for this run)
BM-1b: world generator v2 — speaker ∈ {owner, dog} on joke cues, teacher
rules for `dlg=speaking` (gaze to owner + filler at clause boundaries,
chuckle after the dog's own punchline only if the owner laughs or the
category is liked), a `barge_in` family (owner speech during a dog emote →
<idle> within 2 frames + epoch increment; M2(e)), `steer:<param>` cues
(calmer, livelier, quieter, stop_that, check_more, check_less) with a
persistence score, owner-ASR latency 0.5–1.5 s, a `<hold>` token distinct
from `<idle>`. M6: replay-tier distribution sanity on ≥ 1,000 real
logs/duplex sessions.
