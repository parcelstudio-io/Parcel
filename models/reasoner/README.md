# Reasoner challenger artifacts

`models.lock.json` pins official, Apache-2.0 Ministral 3 8B Instruct and
Reasoning Q4_K_M artifacts by immutable Hugging Face revision, exact byte size,
and SHA-256. Downloading a model does not activate it in production.

Both artifacts are currently present and verified; reproduce either one with:

```bash
.parcel/bin/python models/reasoner/fetch_models.py \
  ministral_3_8b_instruct_2512_q4_k_m

.parcel/bin/python models/reasoner/fetch_models.py \
  ministral_3_8b_reasoning_2512_q4_k_m
```

The fetcher downloads to an ignored `.incomplete` path, verifies size and hash,
then atomically exposes the GGUF. Each model remains a challenger until the
same GPU admission, frozen semantic/embodied, conversation, safety, and latency
gates used for the incumbent are passed.

Current decision: Instruct loaded at 35/35 CUDA layers and reduced median
conversation TTFT to 101.944 ms, but it passed only 5/10 machine conversation
cases and 3/5 PlanIR cases, versus Gemma's 6/10 and 5/5. It is retained as a
reproducible rejected challenger and is not activated in production. The
Reasoning also loaded at 35/35 CUDA layers, but failed its predeclared one-case
frozen PlanSketch compatibility gate. Its schema-shaped response entered a
repeated-property degeneration, exhausted the 1,024-token bound, and remained
invalid JSON after 12,262.204 ms. The other four frozen cases were not run and
no prompt/schema/budget was changed after the failure. It is a reproducible
rejected planner-boundary control, not a five-case baseline, conversation
model, or production activation.
