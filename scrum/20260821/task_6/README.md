# Task 6 — PG-1: the detector on the GPU (36× for free)

**Executor:** Claude Opus (agent) · **Auditor:** Fable (deferred)
**Evidence:** `scrum/20260821/perception/bench_detectors.md` (pre-registered
bench on the RTX 5000 Ada). The incumbent OWLv2 runs **int8 ONNX on CPU at
560 ms/query (1.8 Hz)** — loop-incapable, and int8 costs quality too (.144 vs
.164 recall vs fp16). Nothing has ever tried the GPU. Measured: torch fp16
GPU 50.9 ms; and **73% of remaining latency is CPU-side preprocessing that
scales with SOURCE resolution** although the model always sees 960×960, so
halving the input edge is a free 2.8× with bit-identical tensors.
**560 ms → 15.7 ms.** SigLIP-2: 49.3 ms CPU int8 → 4.07 ms GPU fp16.

## Work

1. **A GPU execution path behind the EXISTING `Detector` protocol** — no
   caller changes. Provider selection is config-driven with a documented,
   fail-closed fallback order (CUDA fp16 → CPU int8), logged once at
   construction so which path is live is never a mystery. A machine without
   CUDA must behave exactly as today.
2. **Source-resolution downscale before preprocessing**, pinned by a test
   asserting the resulting model-input tensor is bit-identical to the
   full-resolution path (that equivalence is the whole justification).
3. **Same for the SigLIP-2 embedding path.**
4. **Contention guard — the finding that matters most for safety:** with a
   VLM generating, detector p95 goes 56 → 150 ms. The person-yield /
   reactive-safety path must NEVER queue behind a scene description. Pin the
   priority explicitly: either separate CUDA streams with the safety-relevant
   inference privileged, or an admission rule that refuses to start a
   long-running generation while a mission is active. State the mechanism and
   seed it.
5. **Do NOT unskip the 9 gate tests** (PG-4/world work owns that). Their
   env-flag gating is deliberate and correct until the world is fixed —
   unskipping now would encode 0% person recall as expected.

OWNS: `detection_adapter/owlv2_onnx.py` + provider plumbing,
`instructnav/siglip2_onnx.py`, the perception config surface, tests,
`PG1_STATUS.md`.
MUST NOT TOUCH: the live mission path's semantics source (still ground truth
until the cutover), `realtime/*`, yield/person-stop policy, the scene assets,
`evals/**` fixtures, the 9 skipped tests' skip conditions. Standard house
rules (gate verbatim; snapshot-restore seed harness + `__pycache__` purge +
fresh-interpreter canary; never commit/stage/stash; owner's :8765 read-only).

## Definition of done

Gate green (unchanged skip counts); ≥8 seeds RED (GPU path silently falls
back without logging; downscale changes the model-input tensor; fp16 path
selected on a CUDA-less machine; contention guard removed; int8 quality
regression unpinned). **Measured evidence, not claims:** a latency table
(p50/p95, VRAM, batch, resolution) for CPU-int8 vs GPU-fp16 vs
GPU-fp16+downscale on the same frames, plus a contention measurement with a
VLM generating. `PG1_STATUS.md` standard register.
