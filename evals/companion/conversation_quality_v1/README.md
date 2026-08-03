# Parcel conversation-quality v1

This frozen suite measures the live fast-conversation boundary separately from
planning and motion. Ten cases cover explicit and hypothetical affect,
non-interruption during a critical task, recent-dialogue recall, camera/Maps
honesty, humor, an explicit no-gesture instruction, and non-diagnosis.

Machine checks are deliberately split into contract parsing, structured safety,
and limited semantic heuristics. Keyword checks do **not** prove warmth,
naturalness, or overall conversational quality. Every result therefore records
`human_review_required: true`; blinded human ratings should be added as a
separate immutable artifact rather than silently folded into the machine score.

The suite executes no skill, simulator step, or robot motion. It cannot claim
physical task success.

```bash
PYTHONPATH=src:. .parcel/bin/python -m evals.companion.run_conversation_quality_v1 \
  --output evals/companion/conversation_quality_v1/results/conversation-v1-run01.json \
  --base-url http://127.0.0.1:8081 \
  --model gemma-4-26b-a4b \
  --model-artifact models/gemma-4-26b-a4b/gemma-4-26B_q4_0-it.gguf \
  --model-sha256 3eca3b8f6d7baf218a7dd6bba5fb59a56ee25fe2d567b6f5f589b4f697eca51d \
  --backend-version "llama.cpp b10236 official CUDA12 OCI" \
  --device-profile cuda:rtx5000ada:sm89:31-of-31-layers \
  --cache-state warm \
  --description "Frozen Gemma fast-conversation baseline"
```
