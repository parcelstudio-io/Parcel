# HS-1 amendments — POST-START (written 2026-08-28 17:57 from an independent design review; the executor was downloading data). The pre-registered bars stand; these add rows and fix under-specified choices BEFORE any result is read.

## H1 — label set fixed now
Laughter score = max over the six AudioSet laughter-family labels
(Laughter, Giggle, Snicker, Belly laugh, Chuckle/chortle, Baby laughter);
record their ids. Also report the single `Laughter` label.

## H2 — the negatives that matter (this row carries the reward-signal verdict)
Add negative slices: (i) SPEECH — 100 clips of read speech (LibriSpeech
dev-clean via HF datasets, or any local public speech set; record source);
(ii) the product's OWN TTS — render 50 short sentences with the repo's Piper
voice (`models/piper/voice.onnx`, read-only; `pip install piper-tts` into
the venv if needed) and, if any chuckle audio asset exists under src/
(search read-only), that too. Report AUROC per slice with bootstrap 95 % CI
over clips; amended verdict for H-HS1a: the pre-registered ESC-50 AUROC ≥
0.95 AND the speech-slice lower bound ≥ 0.90. The ESC-50-only AUROC is
labeled an upper bound.

## H3 — threshold selection is out-of-sample
Choose the operating threshold on ESC-50 folds 1–4; report TPR/FPR/accuracy
on fold 5. The reported operating point (TPR, FPR, onset latency) is what
FL-1 consumes — write it into results.json under `operating_point`.

## H4 — onset latency, not just compute latency
Stream each positive clip with a 1-s window and a 250 ms hop; annotate laugh
onset by an energy threshold; report time-to-first-detection p50/p95 at the
chosen threshold and false triggers per minute on the concatenated negative
stream.

## H5 — HS1c against a biases-only baseline
Baseline = user mean + joke mean (biases-only). Cluster (k=6) on
bias-centred residuals of the dense core. For each held-out user, assign
the cluster from a random half of their ratings and score RMSE on the other
half; amended bar: ≥ 10 % RMSE improvement over biases-only. Report
split-half reliability as the noise ceiling. Keep the original SD statement
as a reported number only.

## H6 — HS1b memorisation probe and verdict bands
Verbatim-completion probe: give the first 40 % of each joke, measure the
exact-continuation rate (≥ 8 consecutive words) — report beside ρ. Verdict
bands: CONFIRMED = point ρ ≥ 0.40 AND bootstrap lower bound ≥ 0.25; REFUTED
= upper bound < 0.40; otherwise INCONCLUSIVE. Named consumer: FL-1's
per-category Beta prior initialisation and dog-told joke selection.

## H7 — tier labels
HS1b/HS1c are `replay` (public corpora through local models); HS1a is
`replay`. A real-sensor row (laughs through this host's speaker → XVF3800
during TTS playback) is a registered follow-up, not part of this run.
