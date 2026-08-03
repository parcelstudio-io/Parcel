# Live planner v1 boundary probe

This suite records one real `llama.cpp`/Gemma PlanIR response and makes it
offline-replayable. It measures a narrow language boundary:

1. parse a frozen strict `IntentFrame` and camera/LiDAR-only
   `ObservationSnapshot`;
2. ask the local model for schema-constrained `PlanIR`; and
3. run the parsed plan through `PlanValidator`, including system-compiled
   effective invariants.

It runs **zero physical or simulated navigation episodes**. An accepted plan
does not mean the dog reached a sidewalk, avoided a collision, or even
dispatched a navigation skill. Those outcomes belong in the headless city,
BARN/Habitat, and hardware-in-the-loop suites.

## Important routing boundary

The frozen sentence routes to `direct_skill` under Parcel's deterministic
router. Normal runtime therefore executes it through the reviewed simple-skill
lane; it does not call the deliberate planner. The captured Run 5 was an
explicit standalone provider probe. It used
`SkillContractRegistry.default(owner_heading_supported=True)`, the raw
`plan_ir_v1.schema.json`, and `PlanValidator`; it did **not** use the runtime's
restricted registry/schema or pass `RobotRuntime._accept_plan`.

That makes this artifact useful evidence that one real model output crossed
the provider, JSON schema/parser, and validator boundary. It is not evidence
for runtime routing, broad instruction following, or embodied task success. A
future runtime-path model corpus should use a new suite version rather than
silently changing this profile.

## Reproduce or replay

Start the pinned local reasoner separately, then run a new live probe:

```bash
.parcel/bin/python -m evals.companion.run_live_planner_v1 \
  --output evals/companion/live_planner_v1/results/my-run.json \
  --model-artifact models/gemma-4-26b-a4b/gemma-4-26B_q4_0-it.gguf \
  --model-sha256 3eca3b8f6d7baf218a7dd6bba5fb59a56ee25fe2d567b6f5f589b4f697eca51d \
  --backend-version b10235 \
  --device-profile cpu_only --threads 32 --gpu-layers 0 \
  --gpu-available-but-unused --health-status ok \
  --description "Gemma baseline after planner change X"
```

The runner refuses to overwrite an existing record. It logs the run ID and UTC
date, change description, model artifact and quantization, backend/device
profile, complete generation configuration, provider latency/token metrics,
parsed raw PlanIR, validation outcome, plan SHA-256, and compiled invariants.
If the provider or parser fails, the failed call is retained with its error and
metrics rather than disappearing from the experiment history.
The artifact is streamed through SHA-256 before the timed provider call; an
optional `--model-sha256` assertion fails before inference if the wrong weights
are selected.

Replay a committed result without a model server:

```bash
.parcel/bin/python -m evals.companion.run_live_planner_v1 \
  --replay evals/companion/live_planner_v1/results/live-planner-20260803-gemma4-run05.json
```

Replay verifies the frozen case, prompt, schema, and result-schema digests,
re-parses the stored PlanIR, and compares the current validation decision,
plan hash, snapshot binding, and effective invariants with the recorded values.
It does not reproduce stochastic decoding or assert the latency will repeat.

For a future GPU comparability run, first require
`python -m parcel_robot.reasoner_gpu --use-cuda-build-output
--require-inference-ready` and retain the server's actual layer-offload log.
The historical b10235 audit did not pass that boundary, so no GPU v1 record
was created. The later b10236 CUDA profile passed and was measured with the
five-case `planner_quality_v2` suite, but this legacy v1 suite was deliberately
not rerun. It continues to use manifest-pinned `planner_v1.md`; use v2 for the
current prompt/runtime quality baseline.

## Recorded baseline

`live-planner-20260803-gemma4-run05.json` is a manually transcribed artifact
from the live 2026-08-03 probe. The output and provider metrics are the captured
values. Absolute monotonic timestamps are process-local and were not retained,
so the replay fixture normalizes them to `100.0s` while preserving the exact
30ms camera and 20ms LiDAR ages and all other supplied semantic fields.

Run 5 produced `NavigateTo(sidewalk) -> Hold` and passed validation. Its outer
elapsed time was 24,825.232ms, time to first model output was 5,791.517ms, and
token usage was 2,272 prompt plus 537 completion tokens. The model proposed one
advisory road invariant; the validator compiled five effective invariants. The
recorded plan hash is
`8ab455dfd03a9316a0007987abcccc1655129839e40876025186ac41a4f248fc`.
At roughly 24.8 seconds this is correctness evidence for one case, not an
acceptable companion latency result.

## Frozen-data policy

`manifest.json` pins the case, immutable `planner_v1.md` prompt, raw PlanIR
schema, and result schema. The normal runtime prompt may evolve without
rewriting this historical inference input. Do not change the frozen case,
prompt, or an old result to make a newer model look better. Add a new result
for each comparable run; create a new suite version when the inference
contract or fixture meaning changes.
