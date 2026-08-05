# Day 49: Choosing and Deploying Open-Weight Models

## Mental model

Model choice for a companion robot is a *multi-objective admission problem*: conversation quality, structured planning quality, latency (TTFT *and* time-to-valid-JSON), VRAM/power, context cost, and recovery under load. Smaller/faster is not automatically better. Open weights help with on-robot or docked privacy and control—but licenses, quantization artifacts, and serving stacks are part of the product.

```text
challenger beats incumbent only if:
  conversation suite ∧ PlanIR suite ∧ embodied gates
  ∧ latency/memory budgets ∧ license/ops fit
```

Parcel documents evidence, not vibes (`docs/VOICE_AI_MODELS.md`). Promotion is a release decision: pinned artifact hash, launcher script, rollback path, and separate metrics for *chat* vs *planner* contention when both share one GPU endpoint.

**Tradeoff:** one backbone simplifies ops but couples failure modes—a planner spike can starve conversational fillers. Split endpoints cost VRAM or context switches; measure before assuming “two small models” beats “one MoE.”

## Software-engineering analogy

This is canarying a new query planner in a database. You do not promote on microbenchmarks of parse time alone. You require plan correctness suites, p99 latency under contention, memory ceilings, and a rollback binary. Quantization is like compression: check semantic checksums (schema-valid plans), not only size on disk. Hidden chain-of-thought is like logging verbose EXPLAIN output into the user-facing column—fast first bytes, never a valid row.

## ASCII diagram

```text
  GGUF artifact + llama-server profile
           |
           v
  LlamaCppProvider → OpenAI-compatible base_url
           |
           v
  admission: hash, layers, VRAM, device
           |
           +--> conversation eval (parse, safety, semantics)
           +--> frozen PlanIR cases (valid JSON + skill sense)
           +--> embodied frozen-plan execution (separate!)
           |
           v
     promote to language_model [/ planner_model slot]
           |
     rollback: prior launcher + artifact
```

## Map to Parcel / Go2

From `docs/VOICE_AI_MODELS.md` (workstation audit) and runtime wiring:

- **Incumbent:** Gemma-family GGUF via **`LlamaCppProvider`** (`providers.py`) → OpenAI-compatible HTTP (`language_model.base_url`, canonical `127.0.0.1:8080`). **`RobotRuntime`** never mmaps weights directly; launchers own artifacts (`scripts/launch_reasoner.sh`, GPU profile scripts).
- **`VoiceAgent.planner_model`** — separate constructor slot defaulting to `language_model`; enables split endpoints without rewriting conversation code (`agent.py`).
- **Split interfaces:** conversation vs planner providers may diverge; default shares one backbone—measure TTFT *and* time-to-valid PlanIR under duplex + follow load.
- **Rejected challenger lesson (documented):** Ministral-class 8B showed faster median TTFT but weaker conversation acceptance and PlanIR scores—not promoted. A “reasoning” checkpoint failed PlanSketch gates by exhausting tokens on malformed output.
- **Quantization / memory:** Q4 is an explicit VRAM trade; GPU profile admission pins provenance hashes and layer offload. Mobile dog power ≠ workstation dock—budget idle VRAM plus peaks during deliberative ~1k-token plans.
- **Specialist routing:** deterministic router removes easy commands from the GPU path; do not burn tokens re-detecting “stop.”
- **TTS/ASR are models too:** whisper.cpp, Piper/Fish voices, separate licenses—swap independently at the cascade boundary documented in `VOICE_AI_MODELS.md`.

Industry aside: on-device MoE and speech-native demos move quickly. Parcel’s bar remains typed-tool reliability at the robot’s safety standard, not leaderboard chat Elo.

Eval harnesses should stress *compound* utterances—the kind that force PlanIR with follow preemption—because TTFT on single-sentence chit-chat hides planner collapse under mid-sentence corrections. Log tokenizer failures and truncated JSON as first-class robot metrics beside latency histograms.

**Codebase anchors (providers / agent / runtime / doc):**

- `providers.py` → `LlamaCppProvider` (HTTP client to llama-server); conversation JSON parse helpers alongside TTS `SpeechChunk` paths.
- `agent.py` → `VoiceAgent` with `language_model`, optional `planner_model`, `plan_publisher` hook to runtime PlanIR admission.
- `runtime.py` → constructs agent/providers from config; brain enablement gates `TaskExecutive` + adapter without loading GGUF in-process.
- `brain/runtime_adapter.py` → skill surface the planner must respect—eval suites should mirror `SUPPORTED_SKILLS`, not generic JSON beauty.
- `docs/VOICE_AI_MODELS.md` → incumbent vs rejected tables, ASR/TTS pins, expression/duplex research boundaries.

## Failure story

An engineer swapped in a “reasoning” GGUF because demos looked thoughtful. Hidden reasoning consumed the deliberative token budget; JSON never closed; the filler watchdog looped; the owner heard stall phrases while follow continued on an old goal. TTFT dashboards were green (first tokens were chain-of-thought). Fix: evaluate *time to schema-valid actionable object*, disable unbounded thinking for robot contracts, and keep CPU rollback launchers pinned. Added a promotion gate: no model ships without passing frozen PlanIR files under the same `VoiceAgent` code path used in production.

Treat ASR and TTS swaps as independent canaries: a faster whisper profile that garbles owner names will poison routing before the LLM ever runs—exercise the full voice stack, not isolated llama-server benchmarks alone.

## Retrieval questions

1. Why is TTFT an incomplete promotion metric for Parcel’s planner lane?
2. What evidence separated the documented incumbent from the installed-but-rejected challenger?
3. (Week-back) From Day 44: when would you split `planner_model` from `language_model` in deployment?

## Optional 10-minute exercise

Read the “Model selection” section of `docs/VOICE_AI_MODELS.md`. Copy the incumbent vs rejected table into your notes. Add one row you would require for *battery-powered* deployment that the workstation audit might miss (thermal throttle, idle VRAM, or wake-from-sleep latency).
