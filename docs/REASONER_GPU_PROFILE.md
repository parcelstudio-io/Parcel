# Parcel llama.cpp CUDA profiles

## Current decision

Parcel now has an admitted GPU inference path for the installed Gemma 4
26B-A4B QAT Q4 model. It uses the official `llama.cpp`
`server-cuda12-b10236` OCI image staged in a repository-managed, ignored
directory. It does not replace the known CPU b10235 runtime.

The immutable readiness record is
[`gpu-readiness-20260803-b10236-oci-cuda.json`](../evals/companion/gpu_readiness/results/gpu-readiness-20260803-b10236-oci-cuda.json).
At `2026-08-03T12:38:00.846961Z`, its inference classification passed. Local
source-build readiness remained false because CMake, Ninja, CUDA, and C/C++
compilers are absent; that does not invalidate an exact, verified upstream OCI
runtime.

## Exact admission evidence

| Boundary | Evidence | Decision |
| --- | --- | --- |
| Upstream runtime | Official tag `server-cuda12-b10236`; source commit `1464c62d88f699ec9700c8010bbfdbc603a9efd6`; CUDA 12.8.1 | Pinned |
| OCI identity | Index `sha256:fd68d13013141833e8214ecad6e1fbefb532db6a00b980cdecfe33603dbf2675`; amd64 manifest `sha256:fcd0f95f2c70156f03ed47c22ff4bea95018bada125c5772af71e83f2c35f2e4` | Verified |
| Staged contents | 13/13 compressed layers and 7/7 critical runtime files matched size and SHA-256 | Verified |
| Server | b10236 (`1464c62d8`); SHA-256 `e3c775bb274d01d5c3345f37aaea55470902187b4433d2689eab367fa4150f3c` | Exact |
| GPU | NVIDIA RTX 5000 Ada Generation; UUID `GPU-97535feb-2b93-d984-921f-885dda608bb1`; compute capability 8.9 | Ready |
| Driver | 595.84; both `nvidia-smi` and `llama-server --list-devices` saw the device | Ready |
| VRAM at audit | 32,760 MiB total; 31,086 MiB free | Passes 24,576 MiB total and 18,432 MiB free floors |
| Gemma artifact | 14,439,363,584 bytes; GGUF; SHA-256 `3eca3b8f6d7baf218a7dd6bba5fb59a56ee25fe2d567b6f5f589b4f697eca51d` | Exact |
| Weights-only headroom | 17,315.550 MiB at audit, including more than the required 4,096 MiB reserve | Startup admission passed |

`nvidia-smi` alone is not GPU-inference evidence. Parcel additionally requires
the exact binary/version, a CUDA backend that enumerates a device, the image
provenance marker and critical hashes, model hash, matching compute
capability, and memory floors. Skipping the model hash is diagnostic only and
fails closed.

## Safe staging and admission

[`llama_cpp_cuda12_oci_b10236.json`](../configs/reasoner/llama_cpp_cuda12_oci_b10236.json)
pins the source, OCI index/platform manifest/config/layers, critical files,
runtime library paths, model, and device floors. Inspect or prepare it with:

```bash
.parcel/bin/python scripts/fetch_reasoner_cuda_oci.py
.parcel/bin/python scripts/fetch_reasoner_cuda_oci.py --prepare
```

The fetcher authenticates only to the public registry, verifies the pinned
remote manifests and every layer, rejects archive traversal, safely rebases
container-absolute links inside a fresh staged rootfs, and never runs image
hooks, a package manager, or the image entrypoint. It refuses to replace an
unverified rootfs or invalid cached blob.

Run the fail-closed doctor and write a new immutable record with:

```bash
PYTHONPATH=src .parcel/bin/python -m parcel_robot.reasoner_gpu \
  --profile configs/reasoner/llama_cpp_cuda12_oci_b10236.json \
  --use-cuda-build-output \
  --require-inference-ready \
  --output evals/companion/gpu_readiness/results/<new-run-id>.json
```

The doctor is read-only except for an explicitly requested result file. Its
exclusive writer refuses to overwrite prior evidence.

## Measured model placement and planner result

The verbose b10236 server log recorded:

- 31/31 model layers offloaded to CUDA0;
- 13,755.42 MiB CUDA model buffer;
- 160 + 900 = 1,060 MiB CUDA KV buffers at an 8,192-token server context;
- 108.52 MiB CUDA compute buffer; and
- 15,280 MiB attributed to the server in one idle post-load `nvidia-smi`
  process snapshot. This is an observed snapshot, not a sampled peak.

The frozen GPU planner baseline is
[`planner-v2-20260803124255Z-75a84bba`](../evals/companion/planner_quality_v2/results/planner-v2-20260803-gemma4-gpu-run06.json).
It kept the same Gemma artifact, generic planner prompt, trusted context
binding, semantic compiler, frozen cases, and generation settings as admitted
CPU run 05. It passed 5/5 semantic cases. Warm median/mean/p95 TTFT was
855.379/701.293/881.942 ms; median/mean/p95 usable-plan latency was
5,657.459/5,990.583/7,201.283 ms. Median usable-plan latency fell 71.23% from
CPU run 05's 19,664.294 ms.

That result executed zero physical episodes. It proves neither perception,
navigation, collision avoidance, companion dialogue, nor Unitree execution.

## Compact Ministral challenger

The composable
[`llama_cpp_cuda12_oci_b10236_ministral8b_instruct.json`](../configs/reasoner/llama_cpp_cuda12_oci_b10236_ministral8b_instruct.json)
profile inherits the exact runtime distribution above and changes only the
model identity and its lower memory floors. The exact official Q4_K_M artifact
is 5,198,911,904 bytes at SHA-256
`33e7a72cf5e6e2cfc2f2847075acc013d68bba023e35310cef86b5cf8fdca761`.
The retained runtime record measured 35/35 layers offloaded, 4,662.05 MiB model,
1,088.00 MiB KV, and 116.01 MiB compute buffers, with 6,220 MiB attributed to
the idle server. Clean shutdown returned host GPU use to 1,140 MiB.

That admission did not earn activation. The compact model passed 5/10 machine
conversation cases and 3/5 PlanIR cases, with slower median complete calls than
Gemma in both suites. See the [runtime evidence](../evals/companion/gpu_readiness/results/gpu-runtime-20260803-b10236-ministral8b-cycle01.json),
[conversation ledger](../evals/companion/conversation_quality_v1/results/README.md),
and [planner ledger](../evals/companion/planner_quality_v2/results/README.md).

The separate
[`llama_cpp_cuda12_oci_b10236_ministral8b_reasoning.json`](../configs/reasoner/llama_cpp_cuda12_oci_b10236_ministral8b_reasoning.json)
overlay pins the official 5,198,910,368-byte Reasoning artifact at SHA-256
`894aa3645ef8708a81dbe201c26105ce37c4c741252c89c5a78f81b49ac438c6`.
It independently passed admission and measured the same 35/35 CUDA placement,
buffer sizes, 6,220 MiB idle server process, and exact return from 7,369 to
1,141 MiB host GPU use after shutdown.

Placement did not imply planner compatibility. A predeclared development-only
one-case gate reused the frozen PlanSketch prompt/schema/case unchanged, enabled
thinking, and retained the 1,024-token bound. The checkpoint began a
schema-shaped object but degenerated into one repeated invented property inside
the generic `arguments` object. It stopped at the token limit after 12,262.204
ms and failed JSON parsing, so the remaining four cases were not run and no
post-hoc prompt/schema/budget change was attempted. See the
[Reasoning runtime evidence](../evals/companion/gpu_readiness/results/gpu-runtime-20260803-b10236-ministral8b-reasoning-cycle01.json)
and [PlanSketch ledger](../evals/companion/planner_quality_sketch_v1/results/README.md).
This is a 0/1 compatibility result, not a five-case accuracy baseline, and the
checkpoint is not activated for planning or conversation.

## Launch and shutdown

The GPU launcher defaults to port 8081 so it cannot overwrite/collide with the
CPU rollback service. The canonical runtime, however, targets port 8080. To use
the admitted GPU profile with the normal stack, start it explicitly on 8080;
the stack will detect and reuse it:

```bash
mkdir -p .cache/reasoner
PARCEL_REASONER_PORT=8080 \
PARCEL_REASONER_LOG_FILE=.cache/reasoner/<new-log>.log \
  scripts/launch_reasoner_gpu.sh -- --verbosity 4

# In another terminal after /health is ready:
./scripts/launch_stack.sh
```

Alternatively, retain the launcher's 8081 default and use an experimental
runtime config whose `language_model.base_url` is `http://127.0.0.1:8081`;
starting a server on 8081 alone does not connect the canonical runtime. The
launcher re-hashes the model,
repeats admission, exports only the pinned application/CUDA libraries plus the
verified NCCL preload, and then requests all layers. Retain the log line with
the actual offload count; `--n-gpu-layers 999` is only a request.

After an evaluation, stop the server cleanly and confirm the port closes and
VRAM returns near its pre-load baseline. Do not leave the 15 GB reasoner
resident while admitting a competing navigation or voice profile.

## Historical b10235 failure and source-build fallback

The earlier
[`gpu-readiness-20260803-b10235-current.json`](../evals/companion/gpu_readiness/results/gpu-readiness-20260803-b10235-current.json)
remains valid historical evidence: that b10235 server reported
`Available devices: (none)` and had no `libggml-cuda.so`. Passing it a nominal
GPU-layer flag would still be a false GPU claim. It remains the CPU fallback.

The profile also contains a pinned source-build recipe for environments that
already provide Git, CMake, Ninja, `nvcc`, and C/C++ compilers:

```bash
scripts/build_reasoner_cuda.py \
  --profile configs/reasoner/llama_cpp_cuda12_oci_b10236.json
```

The build path is isolated under `third_party/llama.cpp-build`; the script
does not fetch source, install tools, or replace the CPU binary. This host does
not currently satisfy that optional build path.

## Primary sources

- [Pinned upstream `llama.cpp` build instructions](https://github.com/ggml-org/llama.cpp/blob/1464c62d88f699ec9700c8010bbfdbc603a9efd6/docs/build.md)
- [Official `llama.cpp` container package](https://github.com/ggml-org/llama.cpp/pkgs/container/llama.cpp)
- [Official Gemma 4 26B-A4B QAT Q4 GGUF](https://huggingface.co/google/gemma-4-26B-A4B-it-qat-q4_0-gguf)
