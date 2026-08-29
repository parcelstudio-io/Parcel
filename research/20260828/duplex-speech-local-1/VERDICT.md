# DS-1 — VERDICT

Verifier: Fable (parcel-0e), 2026-08-29 03:00 EDT. Design frozen 17:40;
post-start amendments 17:57. The executor finished H-DS1a/b/c and the D2/D4
analysis before the spend limit killed it (18:27); its own notes mark the D2
measured step-time delta and D3 co-resident budget UNMEASURED because two
parcel-0e training jobs shared the card from 18:05 (stock Moshi itself
measured 95 ms under that contention). Evidence tier: desktop GPU
benchmark (`desktop-local-model`, proposed label), no hosted calls.

## Independent re-measure

Done by me in an isolated GPU window 03:03–03:16 on 08-29 (D1 stock ≥ 2,000
steps; D3 co-resident; D2 stock/shared) — see "Re-measure rows" and
"Final verdicts" at the end; the table below keeps the executor's numbers
with the re-measure status resolved.

## Product-path check

Harness-only. `moshi` 0.2.13 at pinned rev e6a55d2 in a separate venv
(Python 3.14 supported — the anticipated blocker did not appear; three
dependency pins exceeded and `NO_TORCH_COMPILE=1`, all recorded, all
conservative for timing). The patched tree with the act stream lives at
`~/.cache/parcel-0e/ds1/moshi-act`; nothing in `src/` imports it. The act
stream terminates, by the design, only in `DuplexFrameConsumer` (shadow-only
today).

## Verdicts

| | bar | measured | verdict |
|---|---|---|---|
| **H-DS1a** runs here in real time | step ≤ 80 ms (p50; D1 amended: p99), RTF ≤ 1.0, peak ≤ 24 GB, ≥ 30 s audio (D1: ≥ 2,000 steps) | p50 **41.69 ms**, p99 **43.20 ms**, RTF 0.52, peak 16.24 GiB, 492 steps over 40 s of real speech; step spread 41.6–43.6 ms (CUDA graphs) | **CONFIRMED in isolation** on every pre-registered bar and on the amended p99 value; the amended sample count (≥ 2,000 steps) is PENDING my re-measure. Never "usable backbone": the same model measured **95 ms** with two co-tenants. |
| **H-DS1b** act stream is a small delta | ≤ 4 code sites, ≤ 1 M params, no temporal-transformer change; D2 amended: p99 delta ≤ 5 ms | params: obvious V1 (dedicated depformer step) **81.8 M**; V2 shared slot **0.558 M** (act as step 0; measured on the real load 7,690,292,224 − 7,687,729,152 = +2.56 M incl. the audio-first ordering, exactly the meta-device prediction); code sites **6** (diff 68/4 lines vs the pinned rev); temporal transformer unchanged (streams are summed before the stack); wiring proven: the loop emits in-range act tokens (63 distinct of 90) | **PARTIALLY CONFIRMED**: the parameter bar is met only by the non-obvious route (`depformer_weights_per_step_schedule`), the code-site bar is missed (6 > 4), the "no temporal change" claim is stronger than stated. Timing delta PENDING (executor's p50 +2.1 ms is suggestive; its p99 +57 ms is contention). |
| **H-DS1c** Orin fit (computed statement) | — | bandwidth-bound decode validated here (83 % of the weight-sweep floor); Orin 204.8 GB/s → bf16 **98.7 ms/frame, RTF 1.23 — no**; int8 53.6 ms idealised / **72.2 ms derated (RTF 0.90) — marginal**; int4 31–40 ms — yes; English-only per the model card; no published native-duplex run on any Jetson | Stated: **not on Orin at bf16; int8 unproven and marginal; int4 the only comfortable row.** Candidates and the training-data half are in RESULTS §D4 (160 h of TTS-renderable episodes; one epoch ≈ 1 H100-hour; the published recipe peaks at 39.6 GB → batch ≤ 4 on this card). |

## What this means for the program

1. Design B (native-duplex backbone + act stream) is *real* on this desk:
   the model runs at half the frame budget, the act stream is a 0.56 M-param
   addition placed as depformer step 0 so the frame's audio is generated
   conditioned on the act — the causal direction the dog wants.
2. It is not an Orin design at 7 B. The plan's S3 stays a desktop/hosted
   research track; the on-robot artifact is BM-1's CPU policy + the owner
   table.
3. The clock mismatch (12.5 vs 10 Hz, ratio 5:4) is a product decision:
   re-clock the duplex frame to 12.5 Hz (a constructor argument) rather
   than resample.
4. Co-residency is the risk the numbers already show (42 → 95 ms with two
   neighbours); the gap sweep's Tegra timeslice facts make it worse on the
   robot. Measure D3 before believing any stack budget.
5. Korean is unverified for every candidate; Moshi is English-only.

## Re-measure rows

(appended by the verifier after the isolated run)

### D1 — stock Moshi, isolated, ≥ 2,000 steps (verifier, 03:03–03:05 08-29)

`~/.cache/parcel-0e/verify/ds1/d1_verify.json`: **2,492 steps**, decode on
every step; p50 **43.62 ms**, p90 44.81, p99 **45.35 ms**, max 46.23; RTF
p50 0.545 / p99 0.567; **0 steps over 80 ms**; peak 16.25 GiB. Host at
start: GPU 32 % util (idle desktop processes, 285 MiB), load 8.6 falling from
BM-1's retrain; at end: only this process on the card. The executor's
41.7/43.2 ms at 492 steps is confirmed and the amended sample-count bar is
met → **H-DS1a CONFIRMED (in isolation), original and amended bars.**

### D3 — co-resident budget (verifier, 03:06 08-29, isolated)

`d3_verify.json`: Moshi alone p99 45.09 ms; with the AST laughter detector
(86.6 M params, 44.1 ms p50 per window) and a 2×256 GRU (0.64 M, 0.11 ms)
ticking on the same card: p99 **48.01 ms**, delta **+2.9 ms**, headroom
**32.0 ms** of the 80 ms frame, RTF p99 0.60, peak 16.4 GiB. The whole
stack fits at RTF 0.60 — *when the co-residents are these two small models
in the same process*. This does not contradict the executor's 42 → 95 ms
under two training processes: different CUDA contexts time-slice; the
in-process co-residents here share one.

### D2 — measured act-stream delta (verifier, partial)

`d2_compare.py` failed at load for the `perstep` variant: the patched load
hook reshapes the stock depformer weights to 9 steps
(`transformer.py:442`, `shape [9, -1, 1024] invalid for 25,165,824`) — a
dedicated 9th step cannot be initialised from stock weights without a
custom loader, which the executor did not write. The `shared` variant loaded
and ran earlier (executor, under contention). Re-run of `--variants
stock,shared` in isolation: PENDING the GPU (BM-1 arms B/D retraining) —
if it lands before close it is appended below; otherwise the amended
"p99 delta ≤ 5 ms" bar is **UNMEASURED** and H-DS1b stays PARTIALLY
CONFIRMED on the parameter/wiring evidence only.

### D2 — measured act-stream delta, isolated (verifier, 03:15–03:16 08-29)

`d2_verify.json` (`d2_compare.py --variants stock,shared`, one process, back
to back, 800 steps each, pinned rev e6a55d2): stock p50 43.47 / p99
**45.16 ms**; shared act stream (+2,563,072 params on the real load, 42
distinct act tokens emitted from random init) p50 44.56 / p99 **46.09 ms**;
**delta p50 +1.10 ms, p99 +0.93 ms**; RTF p99 0.576; 0 steps over 80 ms;
peak 16.24 GiB. The amended bar "p99 delta ≤ 5 ms with RTF ≤ 1.0" is
**MET** with 4 ms to spare; the executor's contended +57 ms was contention,
as it said. `perstep` remains unmeasurable without a custom loader.

## Final verdicts

- **H-DS1a — CONFIRMED (in isolation)**: every original and amended bar,
  2,492 steps, p99 45.4 ms, 0 over budget; co-resident detector + GRU
  in-process +2.9 ms; two *training processes* on the card: 95 ms.
- **H-DS1b — PARTIALLY CONFIRMED**: parameter bar met only via the
  non-obvious shared depformer slot (0.56 M vs 81.8 M for the obvious
  step); measured timing delta bar met (+0.93 ms p99); temporal transformer
  untouched; **code-site bar missed (6 > 4)**.
- **H-DS1c — computed**: not on the Orin at bf16 (RTF 1.23); int8 marginal
  (0.90 derated, unproven); int4 fits (0.50); English-only; Korean unverified
  for every candidate.
