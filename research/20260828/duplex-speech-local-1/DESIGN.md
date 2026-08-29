# DS-1 — is an open full-duplex speech model a usable local backbone?

Author: Fable (parcel-0e), 2026-08-28. Pre-registered before any run.
Evidence tier: `desktop-sim` (this host's RTX 5000 Ada 32 GB). No hosted calls.

## Hypotheses (falsifiable)

**H-DS1a (runs here in real time).** Kyutai Moshi (`kyutai/moshiko-pytorch-bf16`,
~7.7 B) runs on this GPU with the reference `moshi` package at a per-step
time ≤ 80 ms for its 12.5 Hz frame (i.e. real-time factor ≤ 1.0) in bf16,
with peak GPU memory ≤ 24 GB. Measured on ≥ 30 s of a public WAV or a
synthetic prompt; report p50/p99 step time, RTF, and memory.

**H-DS1b (an action stream is an architectural one-liner, not a rewrite).**
Reading the released code, the language model consumes/produces K parallel
token streams per frame (text + audio codebooks per speaker) through
per-stream embeddings and output heads. Adding a Parcel **act stream** (the
`ActTokenCodec` vocabulary as one more codebook, ~90 tokens) requires only:
one embedding table, one linear head, a loss term, and training data of
aligned (audio, text, act) frames — no change to the temporal transformer.
Report the exact classes/lines that would change and the number of
parameters added.

**H-DS1c (edge extrapolation).** Given the measured step time and the
public ratio of AGX Orin 64 GB to desktop-Ada bf16 throughput for 7-8 B
decoder models (cite the literature sweep's numbers), state whether Moshi-7B
fits the Orin's real-time budget; if not, name the smallest open full-duplex
alternative and its size.

## Success criteria

a: both bars met → CONFIRMED. b: the delta is ≤ 4 code sites and ≤ 1 M
parameters → CONFIRMED. c is a computed statement, not a verdict.

## What it does NOT prove

Nothing about speech quality, Korean/English handling, the mic array, or
barge-in through the real speaker path; Moshi is an English-centric research
model with a CC-BY license on weights — record the license exactly.

## OWNS / must not touch

OWNS `research/20260828/duplex-speech-local-1/**`; weights to
`~/.cache/parcel-0e/hf/` (set `HF_HOME`); a separate venv
`~/.cache/parcel-0e/venv-moshi/` is allowed if the `moshi` package pins
conflict. GPU use ≤ 24 GB, one job at a time; check `nvidia-smi` first and
do not run while another parcel-0e training job holds > 8 GB. Must not touch
`src/`, `tests/`, other folders, git.

## Reproduction

`~/.cache/parcel-0e/venv-moshi/bin/python research/20260828/duplex-speech-local-1/run.py`
→ `results.json`; RESULTS.md carries only numbers from it.
