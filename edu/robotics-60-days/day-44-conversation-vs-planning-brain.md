# Day 44: Conversation Brain vs Planning Brain

## Mental model

Fluent chat and reliable physical task planning are different products that happen to share language. Conversation optimizes for latency, tone, tool answers, and social repair (“sorry, let me check the map”). Planning optimizes for structured goals, invariants, ordered skills, and admissibility under fresh scene state. Parcel splits *contracts and routes* even when it shares one resident model backbone—because the failure modes and evaluation metrics diverge.

```text
same transcript
    ├─ conversation contract: reply, tools, affect, ≤1 next_action
    └─ PlanIR contract: goal, invariants, 1..12 typed steps
evaluation: separate scorecards (charm ≠ orbit correctness)
```

If you grade both with “sounds smart,” you will ship a witty dog that walks into planter boxes. Conversely, a planner that reads like a JSON log will erode trust even when motion is correct. The architecture accepts that tension instead of collapsing both into one undifferentiated “assistant” blob.

**Correlated failure** is real: one slow or hallucinating shared Gemma hurts chat and PlanIR together. Mitigation is independent provider interfaces (`language_model` vs `planner_model` slots), deterministic fast paths in the router, and promotion gates that require evidence on *both* lanes before swapping weights.

## Software-engineering analogy

This is the classic *BFF vs workflow engine* split. The BFF answers user-facing questions quickly with a small response schema. The workflow engine accepts a versioned job document, persists it, and executes with retries and compensation. You can host both behind one JVM (or one llama.cpp server), but you do not let the BFF’s JSON shape become the workflow’s persistence model—and you do not evaluate them with the same dashboard KPI.

Parcel’s default is **split contracts over one Gemma backbone** via llama.cpp (`docs/VOICE_AI_MODELS.md`): saves VRAM, avoids a lossy “intent extraction” hop, keeps deterministic commands fast. The router sends compound or ambiguous physical language to `deliberative_plan` while greetings and pure Q&A stay in `conversation_only`. Independent interfaces still allow a later specialist planner if a challenger wins on embodied metrics, not lab TTFT alone.

## ASCII diagram

```text
  final transcript
         |
         v
  DeterministicIntentRouter → IntentFrame.route
         |
    +----+------------------+--------------------+
    |                     |                    |
 direct_skill      conversation_only     deliberative_plan
    |                     |                    |
 reviewed grammar    LlamaCppProvider      LlamaCppProvider
 stop/follow/...     decision schema       PlanIR / PlanSketch
    |                     |                    |
    |              VoiceAgent validates   plan_publisher /
    |              tools + next_action    skill contracts
    |                     |                    |
    +----------+----------+----------+---------+
               v
        ActivityCoordinator / arbiter / SafetySupervisor
```

## Map to Parcel / Go2

From `src/parcel_robot/agent.py` and `brain/`:

- **`VoiceAgent.planner_model`** defaults to `language_model` but remains a separate constructor slot—replacement without dual paraphrase hops.
- **`_handle_text` routing:** `frame.route == "deliberative_plan"` (when `_planning_ready()`) goes to `_handle_plan`; ordinary language uses the conversation decision schema (`reply`, `tool_calls`, `intent`, `affect`, `next_action`).
- **Deadlines differ.** Ordinary conversation disables thinking and caps ~256 tokens; deliberative mode allows a larger budget (documented 1,024) but still defaults to no hidden chain-of-thought that can exhaust tokens before valid JSON.
- **Memory:** `ConversationMemory` stores text roles in SQLite—not raw mic audio. Prompt assembly via `DynamicPromptComposer` budgets character counts; runtime context is labeled untrusted/possibly stale.
- **Slow-path telemetry:** `_emit_slow_path("deliberative_plan")` marks planner latency separately from chat—useful when tuning fillers (Day 43).

Fast intent paths stay deterministic: stop, follow, bounded spatial grammar, catalog skills—reviewed rules in `DeterministicIntentRouter`, not “ask the LLM if this sounds like stop.” On Go2, both lanes still converge on the same arbiter and Sport backend; the split is cognitive and contractual, not a second robot. When owners mix chat and motion in one breath (“hi—circle me”), `_COMPOUND` and correction regexes bias toward plan mode so the conversation schema does not silently drop the physical half of the utterance.

**Codebase anchors (dual contracts):**

- `agent.py` → `VoiceAgent`, `planner_model` fallback, `_handle_text`, `_handle_plan`, `_planning_ready`, `_emit_slow_path`.
- `brain/router.py` → routes `conversation_only`, `direct_skill`, `deliberative_plan`, `clarify_or_abstain`; `_COMPOUND` regex for multi-step language.
- `brain/contracts.py` → `IntentFrame`, `PlanIR`, `PlanStep`, `GoalSpec`.
- `providers.py` → `LlamaCppProvider` (separate prompt/schema paths per call site).
- `runtime.py` → `SemanticTaskRuntimeAdapter` construction, plan publishing when `frame.route == "deliberative_plan"`.
- `docs/VOICE_AI_MODELS.md` → shared backbone rationale, Ministral-style promotion caution.

## Failure story

A deployment used conversation quality win-rate to promote a smaller, snappier model into the shared backbone. Chat got punchier; PlanIR acceptance dropped on compound corrections (“no, the other lamppost, then sit”). The dog apologized charmingly while compiling a plan against the wrong landmark. The regression was invisible to the conversation ledger. Fix: gate promotion on *both* frozen PlanIR cases and embodied execution, with independent provider boundaries ready when scores diverge. Keep router deterministic rules as the floor when the planner lane degrades.

## Retrieval questions

1. Why can one resident model still be a “split brain” architecturally?
2. What does Parcel refuse to do with a non-final ASR hypothesis on either lane?
3. (Week-back) From Day 42: which pipeline stages dominate latency before the conversation brain even starts?

## Optional 10-minute exercise

Open `VoiceAgent.__init__` in `src/parcel_robot/agent.py` and find where `planner_model` falls back to `language_model`. Skim `_handle_text` for the `deliberative_plan` branch. Write two bullet evaluation criteria you would never mix between lanes.
