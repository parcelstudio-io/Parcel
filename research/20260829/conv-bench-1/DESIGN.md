# CONV-1 — conversation benchmark rows for this wave

Author: Fable (parcel-0e), 2026-08-29. Pre-registered before any run.
Evidence tiers: `replay` and `desktop-sim`; no hosted calls in this folder
(hosted rows live in MB-1 / LIT-1). Physical: NO-GO.

## Hypotheses (falsifiable)

**H-CV1a (the frozen corpus rows do not move).** Re-running
`evals/companion/realtime_convo_v1/score_corpus.py` on the captured 25-thread
corpus reproduces QEV-1's machine-contract result (25/25 threads, 0 hard
failures, 66 review flags) byte-identically — the baseline this wave's
narration claims are read against.

**H-CV1b (duplex timing gates are the product's, and known).** Re-running
`evals/companion/duplex_v1/run_duplex_v1.py` and the acoustic loop
`run_acoustic_loop_v1.py` reproduces QEV-1's rows (7/7 duplex hard gates;
acoustic 5/9 gates, endpointing ep50 0.812 s vs 0.500 bar) within the
runs' own declared tolerances; exit codes 0/1/2 recorded.

**H-CV1c (grounding improves with Model B, on the same scorer).** The
scorer's capability-overclaim and unsupported-arrival flags over MB-1's
arm-Q transcripts are ≤ 0.2 × the flag rate over arm-D transcripts of the
same scenarios (the scorer is the QEV-1 instrument; the transcripts are
MB-1's).

## Measurements

Exact scorer outputs; exit codes; flag counts per arm; wall time.

## Success criteria

a and b reproduce; c ratio ≤ 0.2.

## What it does NOT prove

The scorer is a machine contract + risk flags, "never a human preference
model" (its own docstring); acoustic rows are null-sink synthetic.

## OWNS / must not touch

OWNS `research/20260829/conv-bench-1/**`; runs existing evals with outputs
redirected into the folder; never modifies `evals/`; PipeWire null sinks
only; never the owner's audio devices.

## Reproduction

`.parcel/bin/python research/20260829/conv-bench-1/run.py --all`
