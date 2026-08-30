# CONV-1 — VERDICT

Verifier: Fable (parcel-0e), 2026-08-29 16:05 EDT. Design frozen 15:3x;
post-start amendments C1–C3 written 15:53, AFTER the executor completed
(~15:50) — applied by me at verdict time as the amendment note says.
Executor: Opus; no hosted calls ($0.00); `evals/`, `src/`, `tests/`
untouched (`git status --porcelain evals/` = 0 before and after my own
re-runs). Evidence tiers: `replay` (corpus, duplex), `desktop-sim` (acoustic
null sinks).

## Independent re-measure (my hands, scratch outputs under ~/.cache/parcel-0e/verify/cv1/)

- Corpus scorer (`score_corpus.py`, exit 0): my artifact equals the
  executor's `cv1a-corpus-noreview.json` **in every field after dropping
  `recorded_at_utc`** (whole-artifact sha `bbca63af6733` both sides): 25
  threads / 174 turns / 0 hard failures / 66 review flags (over-60-words 32,
  repeated-refusal 17, tool/route 7, perception 4, present-motion 4,
  arrival 1, durable-memory 1), semantic review 43/76 expectations, threads
  6 PASS / 8 MIXED / 11 FAIL.
- Duplex (`run_duplex_v1.py`, exit 0, `PARCEL_LATENCY_LEDGER` redirected so
  the frozen ledger stayed clean): hard gates **7/7**, TTFT p50
  **35.52 ms** (executor 35.444; QEV-1 35.7; C1 tolerance ± 10 ms).
- Acoustic: NOT re-run by me (the runner writes PCM scratch under
  `evals/.../results/.tmp` and crashed once for the executor; a second
  crash would risk the frozen tree). Read from the executor's artifact.

## Verdicts

| | bar (DESIGN; C1 tolerances) | measured | verdict |
|---|---|---|---|
| **H-CV1a** frozen corpus rows do not move | machine-contract block + sorted findings equal to QEV-1's after dropping timestamps | identical: 25 / 174 / 0 / 66, same per-check flag composition, same semantic verdicts; reproduced by me | **CONFIRMED** (note: no prior artifact is checked into `evals/…/results/` — QEV-1's went to scratch; the pin is now this folder's artifact + sha) |
| **H-CV1b** duplex gates known | identical gate pass/fail vector; TTFT p50 ± 10 ms | 7/7 both runs; 35.444 ms executor, 35.52 ms mine, 35.7 ms QEV-1 | **CONFIRMED** |
| **H-CV1b** acoustic gates known | identical pass/fail vector; ep50 ± 0.05 s | full suite **CRASHED** (`ValueError: could not broadcast input array from shape (612,) into shape (0,)` — `robot_only_envelope`'s guard does not reject a negative offset, `run_acoustic_loop_v1.py` ≈ :241–244 / :502; timing-dependent); subset (endpointing, duplex, prosody; 17 cases, exit 1) ep50 **0.792** (QEV-1 0.812; Δ 0.020 ≤ 0.05), ep90 0.8756 (=), ack p50 0.850 (=), prosody apex 0.5714 (=), cutoff 0.0 (=); 4 barge-in gates **not measured** | **UNMEASURED for the full suite (C1: crash = UNMEASURED, not REFUTED); the five measurable gates REPRODUCE within tolerance.** A product-eval defect is recorded for the owner: the acoustic gate can crash instead of returning 0/1/2. |
| **H-CV1c** grounding improves with Model B | C3: unbacked-flag rate in arm Q ≤ 0.05/turn; D ratio reported only with ≥ 20 D flags | instrument delivered and proven equivalent (bridge over the 25-thread corpus → the same 66 flags on the same turns; 6/6 fixtures fire as designed; held-out-scene check passes by importing the id, never spelling it); **ratio pending MB-1's transcripts** | **PENDING** → computed at close by `bridge.py --transcripts` over MB-1's arm-Q/arm-D JSONL |

## What this means for the program

1. The conversation baselines this wave reads against are exact and now
   have a checked-in pin (this folder). Any later claim that Model B
   "improves grounding" is measured on the same 66-flag instrument plus the
   event-backed join (C3).
2. The acoustic gate — the only audio evidence in the wave — is fragile:
   a timing-dependent crash in the barge-in family. Until fixed (in
   `evals/`, not here), the four barge-in numbers (incl. stop p50 1.08 s vs
   0.52 bar) cannot be re-measured; the five measurable gates say the
   product's endpointing (0.79 s vs 0.50) and duplex ack (0.85 vs 0.70) are
   still red where QEV-1 left them.
3. Two harness writes into the frozen tree (`evals/latency/ledger.jsonl`
   row; acoustic `.tmp` PCM) are undirectable by flags — the executor
   contained both; future runs must set `PARCEL_LATENCY_LEDGER` and clean
   `.tmp`, and the gate's tree-integrity check should cover them.

## Defect record for the owner / integrator (second reader: parcel-6c, 16:1x, mechanism confirmed in code)

`evals/companion/acoustic_loop_v1/run_acoustic_loop_v1.py::robot_only_envelope`
(:239–247): `offset = round(lag·SR/FRAME)`; `end = min(mixed.size,
offset + owner.size)`; the guard `if offset < mixed.size and end > offset`
PASSES for a negative offset, and `aligned[offset:end] = owner[:end-offset]`
then slices with a Python negative index. Reproduction of the observed
shapes: offset = −1, owner.size = 612 → end = 611, source (612,), target
`aligned[-1:611]` is empty (0,) → "could not broadcast (612,) into (0,)".
Negative lag arises whenever `align_lag_s < interrupt_onset_in_capture`
(:494–503) — capture-timing dependent, hence intermittent. Provenance: the
guard lines blame to b75ed05 (2026-08-09, the pack's landing); d298842 did
not touch them → a pre-existing latent defect first tripped here. Fix (two
lines, flag-free, product-eval leaf; no gate pin covers the runner):
`if offset < 0: owner = owner[-offset:]; offset = 0` (shift the needle), or
refuse a negative lag with a typed reason. **Not applied by this wave** — an
integrator's edit; announced here.

Harness-write disposition (parcel-6c): not a gate item — `results/.tmp/` is
gitignored (`.gitignore:95`); the crash leftover exists only because the
`rmtree` (:973) is not in a `finally` (disk hygiene, one line); the report is
already directable (`--output`, :1010); the tracked dated results JSONs are
append-only evidence by design. Future runs: pass `--output` into the
research folder and set `PARCEL_LATENCY_LEDGER`.

## Follow-ups
Land the two-line guard fix + `try/finally` (integrator); re-run the full
acoustic suite; compute H-CV1c when MB-1 lands.
