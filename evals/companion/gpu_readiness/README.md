# Reasoner GPU readiness evidence

This directory stores immutable device-admission snapshots produced by
read-only probes. These are not planner-quality results: the doctor hashes but
does not load the model and never contacts a provider. A failed snapshot must
not be converted into inference latency, token, layer-offload, or task-quality
claims.

The historical b10235 snapshot correctly rejects the CPU-only server. The
2026-08-03 b10236 snapshot admits the provenance-locked official CUDA 12 OCI
runtime: the image marker, 7/7 critical runtime files, binary/version, CUDA
device, exact Gemma GGUF, compute capability, and VRAM floors all pass. Its
source-build classification remains false because the local compiler
toolchain is absent; that is separate from verified OCI inference readiness.

Re-run the current host check with model hashing enabled and write a new path:

```bash
PYTHONPATH=src .parcel/bin/python -m parcel_robot.reasoner_gpu \
  --profile configs/reasoner/llama_cpp_cuda12_oci_b10236.json \
  --use-cuda-build-output \
  --require-inference-ready \
  --output evals/companion/gpu_readiness/results/<new-run-id>.json
```

Add a new timestamped artifact after a meaningful binary, toolchain, driver,
or device change. The writer refuses to overwrite old evidence. Use
`scripts/fetch_reasoner_cuda_oci.py --prepare` to verify/stage the pinned
runtime and `scripts/launch_reasoner_gpu.sh` to repeat admission before model
load.

Layer offload and inference latency require separate runtime evidence. The
[`runtime evidence record`](results/gpu-runtime-20260803-b10236-planner-cycle01.json)
hashes the retained b10236 server log, records 31/31 layers offloaded, loaded
and restored VRAM snapshots, and the linked planner runs. The frozen
five-case GPU planner record is
[`planner-v2-20260803124255Z-75a84bba`](../planner_quality_v2/results/planner-v2-20260803-gemma4-gpu-run06.json).
It passed 5/5 semantic cases with zero physical episodes, so it is neither a
navigation result nor an official benchmark score.

The compact-model admission and runtime evidence are recorded separately:

- [`gpu-readiness-20260803-b10236-ministral8b-instruct-oci-cuda.json`](results/gpu-readiness-20260803-b10236-ministral8b-instruct-oci-cuda.json)
  verifies the exact 5,198,911,904-byte artifact, model hash, OCI runtime, GPU,
  and memory admission. The source-build classification remains independently
  false.
- [`gpu-runtime-20260803-b10236-ministral8b-cycle01.json`](results/gpu-runtime-20260803-b10236-ministral8b-cycle01.json)
  records a verbose 35/35-layer CUDA load, a four-token full-CUDA inference
  smoke, 6,220 MiB point-in-time server VRAM, clean shutdown, and return to
  1,140 MiB host GPU use.
- [`gpu-readiness-20260803-ministral8b-cpu-selection-rejected.json`](results/gpu-readiness-20260803-ministral8b-cpu-selection-rejected.json)
  preserves the initial operator-error audit: selecting the CPU-only b10235
  server correctly failed CUDA admission. It is not a model-quality result.
- [`gpu-readiness-20260803-b10236-ministral8b-reasoning-oci-cuda.json`](results/gpu-readiness-20260803-b10236-ministral8b-reasoning-oci-cuda.json)
  verifies the separately pinned 5,198,910,368-byte Reasoning artifact and the
  same exact OCI/GPU/memory boundary.
- [`gpu-runtime-20260803-b10236-ministral8b-reasoning-cycle01.json`](results/gpu-runtime-20260803-b10236-ministral8b-reasoning-cycle01.json)
  records 35/35 CUDA layers, loaded/restored VRAM, and the failed predeclared
  one-case frozen PlanSketch compatibility gate. That 0/1 gate exhausted its
  1,024-token bound with malformed JSON; it is not a five-case planner result.

Ministral's successful GPU admission did not imply promotion. Its linked
development runs scored 5/10 machine conversation cases and 3/5 PlanIR cases,
versus Gemma's 6/10 and 5/5 respectively; human conversation review remains
unperformed. The Reasoning sibling likewise remains inactive because it failed
before semantic scoring on the first frozen PlanSketch compatibility case; no
conversation or physical test was claimed.
