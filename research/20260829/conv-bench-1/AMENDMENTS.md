# CONV-1 amendments — POST-START (15:53 08-29, from the design review)

## C1 — baselines pinned to artifacts, "reproduce" defined
Pre-register the exact baseline artifacts and their sha256:
`research/20260826/system-readiness/realtime_convo_v1_offline_score.json`;
`evals/companion/duplex_v1/results/duplex-v1-20260810082415Z-53d8fb6a.json`;
the specific acoustic run you compare against (name it; the stored runs show
ep50 0.772 / 0.784 s and 4/9 gates — QEV-1's "5/9, 0.812" must be cited to
its run or corrected). Reproduce = equality of the `machine_contract` block
and the sorted finding list after dropping `recorded_at_utc` / `utc` /
`elapsed_ms`; acoustic: identical gate pass/fail vector + ep50 within
± 0.05 s; duplex: TTFT p50 within ± 10 ms. Any non-zero exit with a
traceback (the acoustic rerun already crashed: `ValueError: could not
broadcast input array from shape (612,) into shape (0,)`) = UNMEASURED with
the traceback and `wpctl` state attached, never REFUTED.

## C2 — the frozen evals tree stays clean
`run_duplex_v1.py` appends to `<results-dir>/ledger.jsonl` and the acoustic
loop writes `evals/companion/acoustic_loop_v1/results/.tmp`: pass the
results-dir argument into this folder, assert `git status evals/` is clean
after every run (record before/after hashes), and if a runner cannot be
redirected, record the mutation and revert nothing by hand — report it.

## C3 — H-CV1c restated
The corpus scorer has NO capability-overclaim check; its RISK_PATTERNS are
lexical, review-severity. Unsupported = lexical flag on turn t ∧ no backing
event in MB-1's event JSONL for that scenario within the window before t
(join by scenario id + turn index). Add a deterministic capability check in
this folder against the session's exposed tool/gesture set (`play_bow`,
`paw_wave`, `navigate_to`, …) so the QEV-1 invented-action class is
measured. Criterion: absolute UNBACKED-flag rate in arm Q ≤ 0.05 per turn,
with the D ratio reported and read only if D has ≥ 20 flags. Pre-register
the conversion of MB-1 transcripts into the corpus format (one thread per
scenario; `tool_calls` populated with the broker calls the harness made);
note `DECLARED_TOOLS` parity (schema.py) may hard-fail — record explicitly.

## Verifier note (15:55 08-29)
The executor completed at ~15:50, BEFORE this file existed; its RESULTS.md
already satisfies C2 (results dirs redirected; the two undirectable harness
writes into `evals/` — the latency ledger row and the acoustic `.tmp` PCM —
were contained, restored and documented; `git status evals/` clean). C1's
tolerances and C3's restated H-CV1c are applied by the VERIFIER at verdict
time: C1 on the executor's recorded artifacts; C3 by running the executor's
`bridge.py` over MB-1's transcripts when they exist. The acoustic runner's
crash (`ValueError: could not broadcast input array from shape (612,) into
shape (0,)`, negative offset in `robot_only_envelope`, run_acoustic_loop_v1.py
≈ :241–244 / :502) is a product-eval defect recorded, not fixed (it lives in
`evals/`).
