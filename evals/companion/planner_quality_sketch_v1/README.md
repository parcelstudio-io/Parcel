# Parcel planner-quality PlanSketch v1 challenger

This is a separate frozen challenger over the exact five semantic cases used
by `parcel-planner-quality-v2`. The manifest independently locks the shared
case corpus, PlanSketch schema, and PlanSketch instruction. The runner uses the
same deterministic router, camera/LiDAR-only snapshot fixtures, runtime skill
registry, semantic scorer, and PlanIR validator as the paired PlanIR suite.

The provider must return raw PlanSketch v1. The runner records that raw output,
deterministically binds and compiles it into PlanIR, records the admitted
PlanIR, and validates it against the case snapshot before semantic scoring.
There is no fallback to PlanIR output.

Run against the admitted warm b10236 CUDA server on port 8081 with:

```bash
PYTHONPATH=src .parcel/bin/python -m evals.companion.run_planner_quality_sketch_v1 \
  --output evals/companion/planner_quality_sketch_v1/results/planner-sketch-v1-20260803-gemma4-gpu-run01.json \
  --base-url http://127.0.0.1:8081 \
  --model gemma-4-26b-a4b \
  --model-artifact models/gemma-4-26b-a4b/gemma-4-26B_q4_0-it.gguf \
  --model-sha256 3eca3b8f6d7baf218a7dd6bba5fb59a56ee25fe2d567b6f5f589b4f697eca51d \
  --quantization "Q4_0 QAT" \
  --backend-version "llama.cpp b10236 (1464c62d8), official CUDA12 OCI" \
  --cache-state warm \
  --device-profile cuda:rtx5000ada:sm89:31-of-31-layers \
  --threads 32 \
  --gpu-layers 999 \
  --plan-timeout 90 \
  --plan-max-tokens 1024 \
  --description "Frozen five-case PlanSketch v1 GPU challenger"
```

The model artifact is hashed before inference and output is immutable. The
report records provider output bytes, prompt/completion/total tokens, TTFT,
full model-call latency, compile/validation latency, and total case latency.

Passing proves only semantic planning and trusted PlanIR admission on these
five fixtures. Every report records zero physical episodes and a null physical
success rate. It does not establish navigation, perception, collision safety,
conversation quality, or Unitree execution.

Immutable runs and the paired PlanIR decision are in the
[result ledger](results/README.md).
