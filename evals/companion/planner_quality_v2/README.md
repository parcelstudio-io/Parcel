# Parcel planner quality v2

This is a frozen, five-case contract suite for Parcel's deliberate planning
mode. It exercises the real deterministic router, the runtime-admitted skill
registry, constrained PlanIR schema, camera/LiDAR-only observation contract,
and fail-closed validator.

Runner v2 records both the provider's raw plan and the context-bound admitted
plan. Routed turn provenance—and, for an active correction, task identity,
next revision, and checkpoint interrupt policy—are system-owned fields. They
are rebound after decode because a backend may not enforce JSON Schema
`const`; the provider cannot select those executive-control values.

Runner v3 additionally records aggregate per-case TTFT, model-call, runner,
and token statistics. A prompt challenger may be supplied with
`--planner-prompt`; it must live in the repository, is SHA-256 recorded in the
result, and never changes the frozen cases or expected outcomes. Record whether
the server prefix cache is `cold`, `warm`, `mixed`, or `unknown` because cache
reuse materially changes TTFT.

Runner v4 compiles the context-bound semantic plan through
`semantic-planir-compiler-v1` before validation. Skill order and bounded
arguments remain provider-owned. The system deterministically fills task/step
identity, resources, required and conditional preconditions, success policy,
timeouts, retries, recovery, and interrupt defaults. Both the raw provider plan
and final admitted plan remain in the result, so the compiler cannot hide model
semantic errors.

The cases cover:

- semantic navigation followed by a hold;
- two separately grounded navigation targets;
- owner-relative displacement followed by a hold;
- one local owner orbit followed by behind-owner formation; and
- correction of an active task without an unsafe immediate interruption.

Passing means that a provider returned an admitted plan with the expected
semantic decomposition. It does **not** mean that Parcel saw the real target,
executed a skill, avoided a collision, or succeeded in a simulator or on a
Unitree robot. Every record therefore reports zero physical navigation
episodes and a null physical success rate.

The manifest pins the cases, current planner prompt, and raw PlanIR schema by
SHA-256. Changing any one requires a new manifest or a deliberate suite
version. Results should be written to a new immutable path, for example:

```bash
PYTHONPATH=src .parcel/bin/python -m evals.companion.run_planner_quality_v2 \
  --output evals/companion/planner_quality_v2/results/<run-id>.json \
  --model-artifact /path/to/model.gguf \
  --model-sha256 <sha256> \
  --backend-version <llama.cpp-version> \
  --device-profile cuda \
  --gpu-layers 999 \
  --description "Frozen five-case GPU baseline"
```

Do not label a run GPU-backed merely because `--gpu-layers` was requested.
First use the repository's device-admission checks and retain the server log
showing a CUDA device and layer offload. The command hashes the model artifact
before inference and refuses to overwrite an existing result.

```bash
PYTHONPATH=src .parcel/bin/python -m parcel_robot.reasoner_gpu \
  --profile configs/reasoner/llama_cpp_cuda12_oci_b10236.json \
  --use-cuda-build-output --require-inference-ready
```

The historical b10235 check failed because that CPU binary reported no CUDA
device. A separately staged, provenance-pinned official b10236 CUDA 12 runtime
later passed admission and produced the immutable 5/5 GPU run 06. Its verbose
server log reports 31/31 layers offloaded. See
`docs/REASONER_GPU_PROFILE.md`; neither a requested layer count nor a healthy
driver alone is sufficient GPU evidence.
