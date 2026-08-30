# Model A Stream 2 (MA-2)

Status: **P0 teacher substrate passed; P1 learned challenger refuted**.  
Model-A status: **not established**.  
Physical status: **NO-GO; no checkpoint has motion authority**.

MA-2 first repaired the invalid MA-1 causal-data substrate, then tested the
smallest honest learned-controller question. P0 produced 300 source-bound,
leakage-free teacher episodes with exact action/application and terminal/queue
semantics. P1 trained a snapshot MLP (`S`) and a 16-frame GRU (`C16`) on 72
whole episodes and evaluated strict held scene, target-role, task-family, and
combined splits.

The P1 result is a useful negative. Both learned arms looked accurate on frozen
teacher-state rows, but all six learned seed runs completed **0/198** held
missions in closed loop. The teacher, reflex, and direct-bearing controls each
completed **198/198**. The independent verifier passed all retained evidence,
so this is not a provenance or safety-integrity failure: one-step behavioral
cloning did not tolerate its own state-distribution shift.

## Latest result at a glance

| measure | retained P1 result |
|---|---:|
| train / dev episodes | 72 / 12 |
| held episodes per arm/seed stream | 198 across 7 disjoint splits |
| teacher / reflex / direct success | 198/198 each |
| idle success | 0/198 |
| `S` success, each of 3 seeds | 0/198 |
| `C16` success, each of 3 seeds | 0/198 |
| `C16` test-STF open-loop MSE | 0.001630--0.001819 |
| `C16` test-STF direction agreement | 0.990491--0.997887 |
| `C16` test-STF stop F1 | 0.882759--0.895105 |
| contacts / post-gate unsafe / stale / unbacked | 0 / 0 / 0 / 0 |
| final closed-loop evidence | 1,980 traces / 677,784 frames |
| open-loop evidence | 42 traces / 153,684 rows |
| latency evidence | 120,000 raw samples; H-P1c passed |
| independent verification / tamper | pass / 5 of 5 rejected |
| controlling verdict | `P1_REFUTED` |

## Artifact index

- [`RESULTS.md`](./RESULTS.md): exact P1 metrics, commands, hashes, failures,
  and execution history.
- [`VERDICT.md`](./VERDICT.md): controlling interpretation and bounded P2
  recommendation.
- [`P1_DESIGN.md`](./P1_DESIGN.md): frozen P1 hypotheses and gates.
- [`P1_EXECUTION_AMENDMENT_20260829.md`](./P1_EXECUTION_AMENDMENT_20260829.md)
  and
  [`P1_EXECUTION_AMENDMENT_20260829_2.md`](./P1_EXECUTION_AMENDMENT_20260829_2.md):
  transparent stopped-run records.
- [`p1/results.json`](./p1/results.json): final per-episode rows, aggregates,
  open-loop metrics, raw latency samples, and verdict.
- [`p1/manifest.prerun.json`](./p1/manifest.prerun.json): final source,
  environment, shard, split, and exact-command freeze.
- [`p1/training.json`](./p1/training.json): all fit logs, checkpoint hashes,
  deterministic repeats, and held-access audit.
- [`p1/verification.json`](./p1/verification.json) and
  [`p1/tamper-test.json`](./p1/tamper-test.json): independent recomputation and
  five rejecting mutations.
- [`p1/traces/`](./p1/traces/): 1,980 full hash-chained closed-loop traces.
- [`p1/open-loop/`](./p1/open-loop/): 42 full prediction/label traces.
- [`p1/dryruns/20260829T233412Z-no-optimizer-integration/`](./p1/dryruns/20260829T233412Z-no-optimizer-integration/):
  non-evidentiary, deliberately failing pre-fit integration proof.
- [`p1/aborts/`](./p1/aborts/): preserved non-evidentiary stopped invocations.

P0 remains separately reproducible through [`P0_PROTOCOL.md`](./P0_PROTOCOL.md),
[`manifest.json`](./manifest.json), [`results.json`](./results.json), and
[`verification.json`](./verification.json).

## Reproduce the final P1 stages

From the repository root, using only the separate PyTorch research environment:

```bash
env -u TMPDIR PYTHONHASHSEED=0 CUBLAS_WORKSPACE_CONFIG=:4096:8 \
  ~/.cache/parcel-0e/venv/bin/python \
  research/20260829/model-a-stream-2/p1/prepare.py \
  --output research/20260829/model-a-stream-2/p1/preconditions.json

env -u TMPDIR PYTHONHASHSEED=0 CUBLAS_WORKSPACE_CONFIG=:4096:8 \
  ~/.cache/parcel-0e/venv/bin/python \
  research/20260829/model-a-stream-2/p1/train.py \
  --manifest research/20260829/model-a-stream-2/p1/manifest.prerun.json \
  --train-shard research/20260829/model-a-stream-2/p1/shards/train.npz \
  --dev-shard research/20260829/model-a-stream-2/p1/shards/dev.npz \
  --output research/20260829/model-a-stream-2/p1/training.json

env -u TMPDIR PYTHONHASHSEED=0 CUBLAS_WORKSPACE_CONFIG=:4096:8 \
  ~/.cache/parcel-0e/venv/bin/python \
  research/20260829/model-a-stream-2/p1/evaluate.py \
  --manifest research/20260829/model-a-stream-2/p1/manifest.prerun.json \
  --training research/20260829/model-a-stream-2/p1/training.json \
  --output research/20260829/model-a-stream-2/p1/results.json

env -u TMPDIR PYTHONHASHSEED=0 CUBLAS_WORKSPACE_CONFIG=:4096:8 \
  ~/.cache/parcel-0e/venv/bin/python \
  research/20260829/model-a-stream-2/p1/verify.py \
  --manifest research/20260829/model-a-stream-2/p1/manifest.prerun.json \
  --training research/20260829/model-a-stream-2/p1/training.json \
  --results research/20260829/model-a-stream-2/p1/results.json \
  --output research/20260829/model-a-stream-2/p1/verification.json \
  --tamper-output research/20260829/model-a-stream-2/p1/tamper-test.json
```

These commands access no Go2, Orin, live Parcel socket, owner database, audio
device, network service, or hosted model API.

## Next experiment

Do not scale this checkpoint or mount it. Freeze a P2 recovery-learning probe
that trains on learner-visited states labeled by the qualified teacher, compares
residual/hybrid control against pure cloning, and requires all seeds to recover
closed-loop success before adding pedestrians, obstacles, perception failures,
or hardware dynamics. Keep `DIRECT` or `R` as the desktop champion and safety
fallback until a learned challenger beats the closed-loop gates.
