# Day 45: From Language to Typed Skills

## Mental model

Natural language is an underspecified program. “Circle me then sit” omits radius, direction, clearance, interruption policy, and what to do if the owner walks away. Parcel’s answer is a compile chain: transcript → `IntentFrame` → allowlisted skill proposals or `PlanIR` → validation against a skill registry and fresh observations → executive admission.

```text
words  →  IntentFrame  →  PlanIR / next_action  →  admitted skill  →  motion intent
         (route meta)     (typed, bounded)         (registry)         (nav/control)
```

Common-sense defaults (radius 1.5 m, clockwise) are *proposals*. Feasibility code may rewrite or reject them. Approximate success regions (“near the lamppost”) become metric goals only after perception binds a candidate with disambiguation when multiple IDs survive gating.

The LLM is a frontend to intermediate representation, not a linker. `SemanticTaskRuntimeAdapter` maps skill names to verifier branches; `SYSTEM_SKILLS` exist so runtime can recover (return to safe pose, hold) without granting the model new authorable APIs. That separation is how you add recovery behavior without expanding the attack surface of planner JSON.

## Software-engineering analogy

This is compiling a domain-specific language with a capability sandbox. The LLM is a source-to-IR frontend. The skill registry is the standard library with capability bits. The validator is the typechecker and linker. The executive is the process supervisor. You would not let a codegen bot emit arbitrary syscalls; you let it emit IR that only calls allowlisted APIs with checked args.

Prompt files (`prompts/system/core.md`, `action_policy.md`) are *style guides* for the frontend—they do not override schema or Python admission. When product asks for “smarter defaults,” the right move is tighter skill contracts and verifier tables, not longer system prompts that contradict validators. Each admitted skill should document which arguments are model-supplied versus perception-bound versus hard-coded safe defaults, so incident reviews do not devolve into arguing about prompt wording.

## ASCII diagram

```text
  "Walk a small circle around me, then sit."
                 |
                 v
        IntentFrame (deliberative_plan)
                 |
                 v
        PlanIR {
          goal, invariants,
          steps: [ OrbitOwner(...), Gesture/pose sit, ... ]
        }   # 1..12 PlanStep
                 |
                 v
        SemanticTaskRuntimeAdapter.SUPPORTED_SKILLS
          NavigateTo | FollowFormation | OrbitOwner |
          MoveRelative | Hold | Vocalize |
          AskClarification | ReturnToSafePose | Gesture
                 |
                 v
        fresh camera/LiDAR + keepout + free space
                 |
                 v
        admit / clarify / reject  →  ActivityCoordinator
```

## Map to Parcel / Go2

Verified surfaces in `brain/` and runtime:

- **`IntentFrame`** (`brain/contracts.py`) — versioned route metadata: `route`, `speech_act`, `spatial_references`, `requires_fresh_scene`, transcript digest. Router does not emit actuator parameters.
- **`PlanIR`** — `goal`, `invariants`, `steps` (1..12 in `__post_init__`), `requested_interrupt` ∈ {`interrupt_now`, `at_checkpoint`, `when_idle`}.
- **`SemanticTaskRuntimeAdapter.SUPPORTED_SKILLS`** — model-authorable skill names. **`SYSTEM_SKILLS`** are runtime-proposed recoveries the language model may *never* author, yet execute under the same validation path (`EXECUTABLE_SKILLS = SUPPORTED_SKILLS | SYSTEM_SKILLS`).
- **Conversation `next_action`** — parsed in `providers.py`: semantic skill only; unknown fields fail; trigger/timing/interrupt knobs from the model are rejected; affect-driven actions need confidence ≥ `affect_minimum_confidence` (default 0.75) and a personality-mapped catalog skill.
- **INTRO example** maps voice → structured task JSON → navigation → Unitree—never raw joint targets from tokens.

Bounded defaults belong in skill contracts and validators, not in free prose. If the owner says “small,” the compile step must map that adjective through an admitted range (for example clamp orbit radius between configured min/max meters), then check clearance against live obstacles and owner keepouts before Sport sees a twist command. Rejection should surface as clarify or a spoken constraint, not silent clamping the owner never hears about.

**Codebase anchors (language → skills):**

- `brain/contracts.py` → `IntentFrame`, `PlanIR`, `PlanStep`, `GoalSpec`.
- `brain/runtime_adapter.py` → `SemanticTaskRuntimeAdapter`, `SUPPORTED_SKILLS`, `SYSTEM_SKILLS`, `_verifier_table`.
- `brain/router.py` → `DeterministicIntentRouter` (routes compound physical language to plan mode).
- `voice/agent.py` → validation of conversation `next_action`, plan handoff to semantic task runtime.
- `providers.py` → decision JSON parsing, affect gating, `strip_emote_tags` (gesture markers separate from motion skills).
- `runtime.py` → `SemanticTaskRuntimeAdapter` wiring, configured brain skills vs system-only intersection.

## Failure story

A planner emitted `NavigateTo` with a place name string that matched two lampposts in the local semantic map. The validator accepted the skill name and a non-empty argument. Execution picked the nearer ID; the owner meant the farther one. The dog “succeeded” by predicate while failing the human contract. Fix: ambiguous bindings must force `AskClarification` (or equivalent) when multiple candidates survive gating—success regions are not unique by string equality. Numeric radii from PlanIR need the same rebinding: accept the skill, reject or rewrite args against fresh geometry (Day 41 untrusted-defaults lesson).

## Retrieval questions

1. Why are common-sense numeric defaults still “untrusted” after PlanIR parses?
2. Name two skills in `SUPPORTED_SKILLS` and one reason `SYSTEM_SKILLS` exist separately.
3. (Week-back) From Day 31: what must never appear in LLM output even if a skill is admitted?

## Optional 10-minute exercise

Open `SUPPORTED_SKILLS` in `src/parcel_robot/brain/runtime_adapter.py` and list them. Skim `PlanIR.__post_init__` in `brain/contracts.py` for step-count and interrupt constraints. Propose one adjective→metric mapping rule for “small circle” that a validator could enforce.
