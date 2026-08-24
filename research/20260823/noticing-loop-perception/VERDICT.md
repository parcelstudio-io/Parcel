# H6 — the noticing loop · VERDICT-LITE (Fable) · 2026-08-24

Verifier: Fable (parcel-fb), 2026-08-24, solo — the account's weekly limit
stopped subagents at ~00:40. Basis: the executor's RESULTS.md and results/
files, the capability test(s) it added (run through the guard on this tree:
`tests/test_h3_drives.py tests/test_h4_body_intent.py
tests/test_h7_localization_contract.py tests/test_h6_noticing.py` + both DEC
ratchets = 63 passed, 1 skipped), git diff against OWNS, and DESIGN.md
byte-identity with `0ec1d7c`. Rows marked *reported* were read, not re-run;
rows marked *reproduced* were re-run here. Criterion integrity: no bar moved.

The assigned Fable verifier died with the weekly limit before writing; this
is the integrator's read of RESULTS.md, `test_h6_noticing.py` (8 passed, 1
skipped offline), and the product diff (`perception/noticing.py` only;
`perception_daemon/server.py` unchanged). Latency rows were measured at host
load 100–207 (two CPU judges); they are upper bounds and were NOT re-run.

| row | criterion | executor | disposition |
|---|---|---|---|
| P1 | ≥ 10 Hz sustained | 7.38 fps free-run (2.8–3.6 at load 170) | INCONCLUSIVE (contended); the executor's own diagnosis — CPU-bound preprocessing, and 640×360 costs MORE CPU than 1280×720 because `_seam_is_clean` disables the fast path below a 960 source edge — is a real finding to fix regardless |
| P2 | p95 < 100 ms | 119.6/132.7 ms p50/p95 | INCONCLUSIVE (contended) |
| P3 | 0 past 300 ms TTL | 0/443 free-run; 254/436 on the loaded host | CONFIRMED-WITH-NOTES (only on a quiet host) |
| P4 | ≤ 1 false noticing/min | 0.40/min photos, 0.00 renders at τ = 0.35 (hand-checked sheet) | CONFIRMED (reported) |
| P5 | novelty AUC ≥ 0.8 | 0.724 all-label; 0.802 person-only; frozen-split 0.75/0.51/0.34 | REFUTED — the pure gallery novelty score does not separate new from seen well enough; needs a spatial prior (map cell + label) |
| P6 | real-photo recall ≥ 0.75 at render FP ≤ int8 | 0.775 instance / 0.987 image at threshold 0.10; render FP 0.00 | CONFIRMED-WITH-NOTES — photo set rebuilt from COCO val2017 (the bench's originals are gone), so this is a fresh measurement, not the bench re-run |
| P7 | contended p95 ≤ 150 ms; 0 past TTL | 177.6 ms; 0/332 | INCONCLUSIVE on p95 (contended); TTL CONFIRMED |
| P8 | RGB-only map writes | 0 published frames, 0 writes, 33 counted errors ("silent blindness") | CONFIRMED (a null result the design must answer: depth or monocular fallback) |

Product-path freshness: ingress before 1,072 ms p50 / 16/16 expired / 0
fresh writes → after 343 ms p50 / 24/32 expired / 47/261 fresh writes —
reported; the fix (fp16 daemon + 640 source) is real but the loop is still
CPU-bound. Renders are under-confident, not blind (person recall 0 @0.10,
0.66 @0.02), which reframes the 2026-08-21 bench. Overall: CONFIRMED-WITH-
NOTES on P3/P4/P6/P8, REFUTED on P5, INCONCLUSIVE on P1/P2/P7 until a quiet-
host re-measure — scheduled for the first verifier that can run.
