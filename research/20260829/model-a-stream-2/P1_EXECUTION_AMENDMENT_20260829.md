# MA-2-P1 execution amendment — held inventory count

Frozen at: **2026-08-29T23:11:21Z**, after restoring the original frozen source
and before applying the corrected count or any additional verifier hardening.

## Prior binding

- prior manifest SHA-256:
  `29d57736afe5d473a203ff3cf67cb408b1ccabb1a57fc75cccaf2ed5a39884c9`
- prior preconditions SHA-256:
  `a440db8b2b9d2e0221b2a7f5f7c3b7c5c1345abaae48fd496188ad7e5293357d`
- prior clean training SHA-256:
  `13e1f6e222ba388ee6ab20107797da82b33f4c96c3fec5b77a17d2c0072f64a4`
- original `evaluate.py` SHA-256:
  `cc9ff358ed38e1d51ec718acb711bd2a5e6aa8929f71381a112e9db877aa4e91`
- original `verify.py` SHA-256:
  `95a62be52c9a8cbeb65cfead63d9bb047a35c5e365bfc3f5f062685af157da19`

The complete old manifest, preconditions, training record, access log, and
checkpoints are retained under
`p1/aborts/20260829T231121Z-eval-inventory-count/`. They are non-evidentiary for
the final P1 result because the verifier source must change and every checkpoint
binds the old manifest.

## Execution history and defect

1. The first fit shell invocation mistyped only the final output directory as
   `model-a-stream-stream-2`. It was interrupted in the first `S` optimizer loop
   before a checkpoint, output file, or mistyped directory existed. No process
   remained. The exact preregistered command was then launched from a clean
   process.
2. The clean old-manifest fit completed all six arms/seeds and both repeats.
   Repeated checkpoints and normalized logs were identical, the access audit
   found no held-shard read, and peak VRAM was below the frozen limit.
3. Held evaluation correctly enumerated **198** episodes per arm. The frozen
   verifier incorrectly expected **2,100** retained closed-loop traces. The
   correct arithmetic is:

   ```text
   36 test-S + 48 test-T + 36 test-F + 24 test-TF
   + 24 test-ST + 18 test-SF + 12 test-STF = 198 episodes
   198 episodes x 10 evaluated arm/seed streams = 1,980 traces
   ```

4. Evaluation was stopped during the deterministic `DIRECT` arm, before any
   `results.json`, aggregate, hypothesis, latency result, or verdict existed.
   The partial directory contained 511 compressed episode traces and one raw
   interrupted trace. It is preserved unchanged at
   `p1/aborts/20260829T231121Z-eval-inventory-count/partial-traces/` and is
   explicitly **NON-EVIDENTIARY / ABORTED**.

No held aggregate or capability claim is made from either aborted invocation.

## Corrective scope

The next source freeze may:

- replace the incorrect verifier count `2100` with the derived count `1980`;
- bind every closed/open-loop trace to the exact learned checkpoint and prove
  raw policy command equality with the requested-action ledger; and
- independently recompute reported closed-loop aggregates from retained traces.

It may not change the split, features, labels, models, optimization schedule,
thresholds, test population, or observed outcomes. The manifest, shards,
checkpoints, training, evaluation, and verification must all be regenerated
from optimizer step zero. Only that new complete source-bound run may be used.
