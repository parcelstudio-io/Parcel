# MA-2-P1 execution amendment 2 — trace checkpoint variable binding

Frozen at: **2026-08-29T23:18:38Z**, after the evaluation process exited and
before changing any frozen source.

## Aborted binding

- manifest SHA-256:
  `876b0675816464bde630729422046195b337177a8e7792a381bec786a79fa68e`
- preconditions SHA-256:
  `394670bb1a8c669df6fbadc12235b89482d54e1e2975035452740469b370f673`
- split manifest SHA-256:
  `f2c91e8a863a5cf5327593ce171e0acb5f06205b9c1c94d1a0539b572f53d8f1`
- training SHA-256:
  `f6a2dfa442702b50ba0df35387a8b0631e39c6fe51eed1a12d3614fc4715ec85`
- evaluator SHA-256:
  `ffb3541cb02a2f3112133bcca05e4543fabe919dc0017c8dbb6f4e044a4e393a`

The optimizer-step-zero rerun completed all preregistered fit arms and repeats.
All pre-evaluation gates passed, no held shard was opened, and repeated
checkpoints and normalized logs were identical. These checkpoints are still
non-evidentiary for the final P1 result because the evaluator source bound by
their manifest contains the defect below.

## Stopped invocation and exact defect

The exact frozen evaluation command was:

```text
env -u TMPDIR PYTHONHASHSEED=0 CUBLAS_WORKSPACE_CONFIG=:4096:8 /home/jaewoo-jang/.cache/parcel-0e/venv/bin/python research/20260829/model-a-stream-2/p1/evaluate.py --manifest research/20260829/model-a-stream-2/p1/manifest.prerun.json --training research/20260829/model-a-stream-2/p1/training.json --output research/20260829/model-a-stream-2/p1/results.json
```

It exited nonzero after the first `T*` episode because the newly added trace
inventory field referenced undefined local name `checkpoint_sha256`; the loop's
frozen checkpoint digest variable is named `checkpoint_sha`. Exactly one
compressed trace existed at exit, with SHA-256
`386f6dd7e7bd3b8f610ea10a7d8877feeda098ca7564164baa5544d3a5799840`.
No `results.json`, aggregate, open-loop trace, latency result, hypothesis, or
verdict existed. No evaluation or training process remained.

The manifest, preconditions, split manifest, fit result, checkpoints, access
log, and one partial trace are to be retained under
`p1/aborts/20260829T231838Z-checkpoint-variable/` as **NON-EVIDENTIARY /
ABORTED**. No held aggregate or capability claim is made from this invocation.

## Corrective scope

The next source freeze may only replace that undefined trace-inventory value
with the already-bound loop variable `checkpoint_sha` and add this amendment to
the source manifest. It may not change a split, feature, label, model,
optimization schedule, threshold, episode, action, or observed outcome. All
bindings, shards, checkpoints, training, evaluation, verification, and tamper
tests must be regenerated from optimizer step zero.
