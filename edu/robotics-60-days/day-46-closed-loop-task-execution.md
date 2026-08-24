# Day 46: Closed-Loop Task Execution

## Mental model

Publishing a plan is open-loop hope. Companion tasks run as a closed loop: observe progress, detect stalls, replan or clarify, honor cancellation, and verify completion with *measured or estimated* predicates—not with “all steps were dispatched” or “TTS already promised success.”

```text
admit plan → execute step → observe (est/meas) → progress?
                              | no: retry / replan / clarify / abort
                              | yes: next step / verified done
```

Persistent task memory matters more than witty mid-task chatter: what was asked, which `plan_revision`, which step failed, and whether recovery used a `SYSTEM_SKILL` the model never authored. Conversation can narrate; the executive owns truth. Timeouts are not pessimism—they are the only way to detect livelock when perception stops updating but motion continues.

**Tradeoff:** aggressive replanning feels responsive but can thrash follow/orbit if every track glitch bumps revision. Prefer bounded recovery (`Hold`, `SearchOwner`, `AskClarification`) before wholesale plan replacement.

## Software-engineering analogy

Treat PlanIR like a durable workflow document (Temporal/Cadence style): each step has an activity timeout, heartbeats from controller state, and explicit compensation. Retries are bounded. Cancellation is cooperative at checkpoints unless `requested_interrupt` is `interrupt_now`. Idempotency keys prevent double-sit after a reconnect. The chat UI may show status; it must not be the source of workflow state—same rule as not trusting a loading spinner for payment settlement.

## ASCII diagram

```text
  PlanIR revision r
        |
        v
  TaskExecutive + SemanticTaskRuntimeAdapter
        |
        +--> step k DispatchRequest → skill runner
        |         |
        |         v
        |    nav / follow / orbit / gesture
        |         |
        |         v
        |    observations (owner track, pose, obstacles)
        |         |
        |         +-- success predicate true? --> k+1
        |         +-- stall / timeout --> recovery_action / replan
        |         +-- owner cancel / E-stop --> abort safe
        |
        v
  ActivityCoordinator (parallel social gestures, subordinate)
        |
        v
  verified completion  OR  failed closed with reason code
```

## Map to Parcel / Go2

Closed-loop execution spans the brain executive, runtime adapter verification, and navigation controllers—not the LLM tick loop (~10 Hz brain updates; Sport closes balance faster).

- **`TaskExecutive`** (`brain/executive.py`) — deterministic PlanIR runner: `ResourceLocks`, `DispatchRequest`, interrupt policies, progress/timeouts. LLM-free at control rate.
- **`SemanticTaskRuntimeAdapter`** (`brain/runtime_adapter.py`) — dispatches allowlisted skills and *verifies* completion from controller snapshots; `SearchOwner` uses perception-backed predicates, not RPC ack alone.
- **`VoiceAgent` + `plan_publisher`** (`voice/agent.py`, wired in `runtime.py`) — admit deliberative plans after validation; execution proceeds without further model calls per tick.
- **`CommitGuard` / speech epochs** — cancel *admission* of stale turns (`handle_text_guarded`); the executive must still cancel *in-flight* skills when the owner says stop after commit.
- **`AskClarification` / `Hold` / `ReturnToSafePose`** — typed recovery in `SUPPORTED_SKILLS`, not decorative prose.
- **Follow as continuous task:** `FollowOwnerController` states (`following`, `holding`, `holding_behind`, `stale`, `lost`) are progress observations. Headless regression treats stable follow/hold as success with a reason—not “commands drained.”
- **Day 01 invariant returns:** completion uses estimated owner/body state with timeouts; Sport RPC ack is never “orbit done.”

Replanning should bump `plan_revision` and remain bound to fresh scene data—old geometry is a cache, not the world.

Stall detection belongs in the adapter’s verify pass: if `FollowOwnerController` reports `stale` while the executive still believes step *k* is “orbit complete,” the bug is in the success predicate wiring, not in Sport. Headless city scripts that treat stable `holding` as success encode this discipline explicitly—copy that pattern when adding new skills.

**Codebase anchors (executive / verification / activities):**

- `brain/executive.py` → `TaskExecutive`, `DispatchRequest`, `ResourceLocks`, `VOICE_INTERRUPT_POLICY`.
- `brain/runtime_adapter.py` → `SemanticTaskRuntimeAdapter.SUPPORTED_SKILLS` (nine planner-authorable names); `SYSTEM_SKILLS` (= `SYSTEM_SKILL_NAMES` from `brain/validator.py`, currently `SearchOwner` only).
- `brain/validator.py` → `SYSTEM_SKILL_NAMES`; system skills excluded from planner schemas but validated like any skill.
- `core/activities.py` → `ActivityCoordinator` — queues `ActionProposal` gestures with TTL/cooldown; docstring: no model motor authority.
- `navigation/follow.py` → `FollowOwnerController` state machine for continuous follow progress.
- `navigation/search_owner.py` → `SearchOwnerController` — runtime recovery when owner track expires (executive may dispatch without LLM authorship).
- `voice/agent.py` → `VoiceAgent.plan_publisher`, `CommitGuard` type alias, `handle_text_guarded`.

## Failure story

A multi-step plan dispatched `OrbitOwner` then `Gesture(sit)`. Mid-orbit the owner stepped behind a car; tracking went stale; navigation kept consuming the open-loop trajectory budget and sat beside the curb. The reply had already said “Sitting now!” because TTS was tied to plan admission, not verified completion. Fix: speech about physical success must latch to predicates; on track loss, enter hold/search/clarify rather than advancing the plan revision’s next step. Postmortem added a rule: `Vocalize` about motion outcomes waits on adapter verification or uses explicitly non-committal wording until predicates pass.

## Retrieval questions

1. Give one open-loop completion signal and one closed-loop predicate for “circle the owner.”
2. When should the executive clarify instead of replanning silently?
3. (Week-back) From Day 34: how do behavior-tree preemption ideas align with Parcel’s `TaskExecutive` interrupt policies?

## Optional 10-minute exercise

Skim `FollowOwnerController` state transitions in `src/parcel_robot/navigation/follow.py` (search for `self._state =`). List three states and what observation would justify each. Then note where a planner should refuse to advance past follow into sit if track status is `stale` or `lost`.
