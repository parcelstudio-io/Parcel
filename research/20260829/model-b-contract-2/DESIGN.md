# MB-2 — the receipt-typed utterance contract, measured

Author: Fable (parcel-0e), 2026-08-29 20:2x. Pre-registered before any run.
Evidence tier: `replay` (MB-1's scripted 40-scenario receipt corpus and
scorer; a local Qwen2.5-7B-Instruct Q4 on this host's CPU llama-server —
no hosted calls, $0). Physical: NO-GO.

## Why

MB-1 refuted free-form hosted narration (grounding 0.61–0.73, 45
invented-action flags) and found a local 7B grounded 0.96 on the same
scorer. Both Sol's verdict and mine recommend replacing free-form fact
inference with a deterministic utterance contract: the executive emits a
typed speech act with slots; a paraphraser may reword it; a post-condition
checker rejects any claim not licensed by the receipt and the capability
enum. This probe measures that contract on the instrument that refuted the
free-form design, so the recommendation carries a number.

## Arms
- **T** — templates only: one deterministic sentence per speech act
  {ack(goal), progress, blocked(class), completed(goal), failed(goal, class),
  cancelled, resumed(goal), resume_offer(goal), capability_refusal(keys)},
  emitted by MB-1's trigger table (arrived/blocked/failed/clarify → speak;
  progress/queued → context only).
- **T+P** — the template plus one local paraphrase (Qwen2.5-7B-Instruct
  Q4, temperature 0.3, ≤ 25 words) that must pass the post-condition checker
  (every navigation/arrival/perception/action claim maps to the triggering
  receipt or the capability enum; else fall back to the template). Report
  the fallback rate.
- **Reference rows** — MB-1's scripted-responder Q (1.000) and hosted Q
  (0.61–0.73) copied from its results.json, labelled as references.

## Hypotheses (falsifiable)
**H-MB2a** T scores grounding ≥ 0.98, coverage ≥ 0.95, invented actions 0,
premature claims 0, keys-inability 15/15 on MB-1's corpus (by construction;
this is the floor the paraphraser must not break).
**H-MB2b** T+P keeps grounding ≥ 0.95, coverage ≥ 0.9, invented actions 0
after the checker, premature 0, with a fallback rate ≤ 0.3 and a blind
"naturalness" preference (the frozen local judge, report-only) ≥ 0.6 for
T+P over T.
**H-MB2c** latency: T ≤ 5 ms; T+P TTFT p50 ≤ 1.5 s on this host's CPU
(reported; the GPU number is a follow-up).

## Measurements
MB-1's scorer as is (grounding, coverage, claims/turn, bars b1–b5,
invented-action matcher with its known over-breadth; report raw and
checker-rejected counts), fallback rate, latency, the judge preference
(report-only).

## OWNS
`research/20260829/model-b-contract-2/**`, `~/.cache/parcel-0e/mb2/`, the
llama-server on `:8093` (start; stop at close; CPU build). Reads MB-1's
`events.py`, `scorer.py`, `narrate.py`, `steer.py`, `results.json` read-only
(import by path). No product edits; no hosted calls; never :8080.

## Reproduction
`.parcel/bin/python research/20260829/model-b-contract-2/run.py --all --seed 20260829`
