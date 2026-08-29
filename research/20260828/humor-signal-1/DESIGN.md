# HS-1 — can the dog tell that a joke was funny? (the reward signal)

Author: Fable (parcel-0e), 2026-08-28. Pre-registered before any run.
Evidence tiers: `replay` (public audio clips through local models) and
`desktop-real-model` (local text model on this host). No hosted calls.

## Hypotheses (falsifiable)

**H-HS1a (laughter is detectable locally).** An off-the-shelf AudioSet
classifier run locally (AST `MIT/ast-finetuned-audioset-10-10-0.4593`, or
BEATs/PANNs if AST fails to load) separates human laughter from other
non-speech human sounds at AUROC ≥ 0.95 on ESC-50's `laughing` class vs the
ESC-50 human non-speech classes (coughing, sneezing, breathing, crying_baby,
clapping, snoring, drinking_sipping, brushing_teeth, footsteps), and runs at
≤ 100 ms per 1-s window on this GPU and ≤ 500 ms on one CPU thread.

**H-HS1b (a funniness prior exists without the laugh).** A local instruct LM
(Ministral-3-8B or Qwen2.5-7B-Instruct via `transformers` in bf16; fallback
Qwen2.5-3B) asked to rate each of the 100 Jester jokes on −10..10 correlates
with the mean human rating (Jester dataset 1: 73,421 users, 4.1 M ratings)
at Spearman ρ ≥ 0.40. Refuted below 0.25.

**H-HS1c (owner taste is real variance, not noise).** In Jester, per-user
taste explains a large share of rating variance: the between-user standard
deviation of the per-joke rating exceeds 3.0 points on the −10..10 scale for
the median joke, and a 6-cluster k-means over users' rating vectors
reproduces a held-out user's ratings better than the global mean (RMSE lower
by ≥ 10 %). This grounds FL-1's synthetic owners in real human variance.

## Measurements

- HS1a: per-clip max laughter logit → AUROC, AUPRC, accuracy at the Youden
  threshold; latency p50/p99 per window, GPU and 1-thread CPU; model params.
- HS1b: 100 LLM ratings (temperature 0, fixed prompt, one call per joke,
  repeated with 2 prompt paraphrases → report the mean and both) vs Jester
  mean; Spearman and Pearson with bootstrap 95 % CI (n=100 jokes).
- HS1c: Jester dataset-1 statistics as above (users with ≥ 36 ratings, the
  dense core), k=6 clusters, 80/20 user split, RMSE.

## Success criteria (pre-registered)

a ≥ 0.95 AUROC and latency bars; b ρ ≥ 0.40; c both statements true.
Each sub-hypothesis is verdicted separately.

## What it does NOT prove

ESC-50 laughter is clean studio/field audio, not a laugh through the
XVF3800 in a living room with the dog's own TTS playing; the LM prior is
about *average* humans, not the owner; nothing about detecting *whose*
laugh.

## OWNS / must not touch

OWNS `research/20260828/humor-signal-1/**` and a download cache under
`~/.cache/parcel-0e/data/`. Must not touch `src/`, `tests/`, other folders,
git. Model weights go to `~/.cache/parcel-0e/hf/` (set `HF_HOME`).

## Reproduction

`~/.cache/parcel-0e/venv/bin/python research/20260828/humor-signal-1/run.py --all`
→ `results.json`; RESULTS.md carries only numbers from it.
