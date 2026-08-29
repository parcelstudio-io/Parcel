# HS-1 — VERDICT

Verifier: Fable (parcel-0e), 2026-08-29 02:50 EDT. Executor RESULTS.md was
complete for HS1a/HS1c; the HS1b section was written by me from the
executor's `results_hs1b.json` after the account spend limit killed the
executor (18:27). Design frozen 17:40; post-start amendments 17:57 applied in
full before any result was read (RESULTS.md §Amendments applied).

## Independent re-measure (headline row)

HS1c re-run by my own hands from the executor's module in a scratch dir
(`~/.cache/parcel-0e/verify/hs1/hs1c_verify.json`, 45 s, OPENBLAS_NUM_THREADS
= 32 — the 192-core host crashes OpenBLAS otherwise): held-out RMSE global
mean 5.0350 / biases-only 4.3702 / 6-cluster 4.2802 / oracle-cluster 4.1100;
improvement over biases-only 2.06 %, over global mean 14.99 %; between-user
SD min 4.41 max 5.81, 100/100 jokes above 3.0; split-half reliability
0.9997. **Byte-for-byte the executor's numbers.** HS1a and HS1b were not
re-run by me (GPU occupied by BM-1's training all night); I checked their
`results.json` blocks for internal consistency (n, CI widths, thresholds)
and found none of the executor's tables misquoting them.

## Product-path check

Harness-only, by design. The AST detector is not wired to anything in
`src/`; there is no `SocialCueV1` producer for `laugh` (six kinds, zero
producers). The Piper voice used as a negative IS the production voice
(`providers.py::PiperSpeechProvider`, same binary and `voice.onnx`), so the
own-TTS row is a real product artifact through a research harness.

## Verdicts, per pre-registered sub-hypothesis

| | bar (DESIGN.md unless noted) | measured | verdict |
|---|---|---|---|
| **H-HS1a** laughter detectable locally | ESC-50 AUROC ≥ 0.95 | 0.9870 [0.9766, 0.9943] | met |
| | H2 amended: speech-slice lower bound ≥ 0.90 | 0.9992 [0.9970, 1.000]; own Piper TTS 1.000 | met |
| | ≤ 100 ms per 1-s window on GPU | p50 30.4 / p99 31.5 ms | met |
| | ≤ 500 ms on one CPU thread | **p50 2,266 ms** | **not met (4.5×)** |
| | → | | **PARTIALLY CONFIRMED**: the signal is clean and fast on a GPU; the pre-registered CPU deployment bar is refuted for this model (an 86.6 M-param AST is the wrong model for a CPU budget) |
| **H-HS1b** funniness prior without the laugh | ρ ≥ 0.40 (refuted < 0.25); H6 bands | ρ 0.219 [0.023, 0.399]; upper bound < 0.40 | **REFUTED** (memorisation probe 0.02 rules out contamination as the cause) |
| **H-HS1c** owner taste is real variance | SD > 3.0 for the median joke | 5.10 (min 4.41) | met |
| | 6-cluster beats global mean by ≥ 10 % | 14.99 % | met as written |
| | H5 amended: ≥ 10 % over biases-only | **2.06 %** (oracle assignment 5.95 %) | **not met** |
| | → | | **PARTIALLY CONFIRMED**: taste disagreement is large and reliably measured (noise ceiling 0.9997), but it is not six-cluster-shaped; the original bar was carried by a weak baseline |

## What this means for the program

1. The reward signal for "chuckle if funny" exists and is trustworthy in the
   operating conditions tested: laughter vs speech and vs the dog's own voice
   separates essentially perfectly; the confusers are coughs, cries and claps
   (1.65 false triggers/min on that stream) — and, by the gap sweep's
   ego-noise numbers, footsteps while walking, which were not tested.
2. The operating point FL-1 must consume is fold-5 TPR 0.625 / FPR 0.056 at
   threshold −2.2592, onset-to-detection p50 1.0 s (window fill) / p95 2.8 s.
   FL-1 ran with the amendment defaults (FN 0.20 / FP 0.05, 0.5 s) because
   this file did not exist yet; the measured miss rate is *worse* than FL-1's
   assumption (0.375 vs 0.20) on the tiny fold-5 sample (5/8 positives).
3. The laughter listener needs GPU on the dog or a much smaller model; the
   Orin has the GPU, and the gap sweep's MPS/timeslice findings say it must
   not share a CUDA context with the 50 Hz lane.
4. No text-only funniness prior is worth building from a local 7B model;
   the dog should tell jokes and *listen*, and the per-category owner table
   (FL-1) should start from a flat prior, not from a model's opinion.
5. Owner taste should be modelled per owner and per category as FL-1 does;
   a population of six "taste types" is not a faithful simulator of owners.

## Follow-ups (registered, not run)

Real-sensor row (laughs through this host's speaker → XVF3800 during Piper
playback, with the no-AEC local lane); VocalSound augmentation of the
detector (CC BY-SA, 3,504 laughs); a sub-10 M-param streaming laugh
detector for CPU; ego-noise negatives from a walking quadruped.
