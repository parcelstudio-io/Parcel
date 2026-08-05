# Day 34: Task Executives and Behavior Control

## Mental model

Perception and planners propose; an *executive* decides what is allowed to run, what owns scarce resources, how interruption works, and when success or failure is declared. Industry patterns include finite-state machines (FSMs), hierarchical state machines, and behavior trees (BTs). Parcel’s brain executive is a deterministic plan runner over typed PlanIR steps with resource locks, priorities, and interrupt policies—BT-adjacent in spirit, schema-first in practice.

```text
plan (what)  →  validate (may?)  →  lock resources  →  dispatch skill
                     ↑                    |
              observations ---- progress / preempt / recover
```

Without an executive, “skills” become concurrent hacks fighting for the base. The executive answers four questions every tick: *what is admitted*, *who owns which resource*, *what interrupt just arrived*, and *did success/failure actually happen?*

Industry BTs often encode recovery as fallback nodes; Parcel encodes recovery as declared `recovery_action` plus timeouts on `DispatchRequest`, so a model cannot invent an unbounded retry graph at runtime.

## Software-engineering analogy

The executive is an OS scheduler plus a workflow engine:

- Task classes and priorities ≈ nice levels / realtime priorities.
- Resource leases on `base`, `voice`, etc. ≈ mutexes with ownership records.
- Preempt / suspend / cancel ≈ signal handling with declared policies.
- Success conditions ≈ assertions in an integration test, checked online.
- Recovery actions ≈ retry with backoff and circuit breakers—not infinite loops.

BTs shine at readable reactive composition (fallback, sequence, parallel). FSMs shine at few modes with clear transitions (Idle/Follow/Search). Parcel chooses validated PlanIR + executive because the LLM must not invent control flow graphs at runtime; it fills a closed skill enum. **Tradeoff:** less free-form BT authoring from the model; more inspectable admission and headless tests (D1).

## Light equations (preemption)

Sketch of admission:

```text
dispatch(A) allowed if
  priority(A) ≥ priority(active)  (per interrupt policy)
  ∧ resources(A) acquirable
  ∧ ¬emergency
  ∧ plan still validated against current observation class
```

Policies differ by source: emergency cancels now; ambient voice may overlap; summons may suspend. Hardcoding “voice always wins” is how follow tears itself apart.

## ASCII diagram

```text
          PlanIR steps
     [SearchOwner] -> [Follow] -> [Sit]
              |
              v
     +------------------+
     | Brain executive  |-- ResourceLocks: base, voice, ...
     | tick()           |-- task state: running|paused|succeeded|...
     +--------+---------+
              | DispatchRequest(skill, args, success, timeout)
              v
     runtime skills / navigation / TTS
              |
      report progress / preempted / failed
              |
              v
     replan? recover? succeed? release locks?
```

## Map to Parcel / Go2

From `brain/executive.py`, `brain/contracts.py`, `DESIGN_DECISIONS.md` D1–D2/D8, and `INTRO.md` priorities:

- Priority ladder in product thinking: E-stop > collision/stability > explicit safety > active nav > gesture > idle personality.
- `ResourceLocks` atomically acquire system resources; conflicts return existing leases rather than silently stealing.
- Interrupt sources are enumerated (`emergency`, `manual`, `explicit_stop`, `voice`, …). Voice policy table distinguishes ambient overlap vs directive cancel—declared, not tribal knowledge.
- Pause ≠ stop (D2): pausable channels should release leases and record bounded `ResumeIntent`; replaying a stale velocity is forbidden. Today’s resume path is incomplete for some NavigateTo cases—treat that as a known honesty note, not as “pause works.”
- Expression is a subordinate 50 Hz channel (D8): personality must not become locomotion authority; hazards and E-stop gate it off.
- Progress monitoring belongs in success predicates and timeouts, not in hoping the skill “looks done.”

**Design choice:** keep the executive deterministic and LLM-free. Cost: schema evolution is engineering work. Benefit: every interrupt/resource fight is unit-testable (`tests/test_brain_executive.py`).

**Codebase anchors (executive / preemption):**

- `brain/executive.py` → `TaskExecutive`, `ResourceLocks`, `DispatchRequest`, `InterruptRequest`; `VOICE_INTERRUPT_POLICY` (`overlap` / `suspend` / `cancel_now`); `TASK_CLASS_PRIORITY`.
- `brain/contracts.py` → `RESOURCES = ("base", "posture", "voice", "attention")`; `PlanIR` / `SuccessCondition` / `ResourceLease`.
- `brain/validator.py` → `PlanValidator` / `ValidatedPlan` — admit before execute.
- `core/preemption.py` → `PreemptionTable.decide` / `PreemptionAction` (`PAUSE`/`STOP`/`DEFER`/`NONE`) mirroring `SOURCE_PRIORITIES`.
- `core/channels.py` → `BehaviorChannelRegistry`; `core/resume.py` → `ResumeIntent` / `ResumeStore` (bounded pause, not stale-velocity replay).
- `core/activities.py` → `ActivityCoordinator` — runtime activity lifecycle alongside the brain executive.
- Motion still exits through `CommandArbiter` + `ControlManager` — the executive never bypasses the HAL.

## Failure story

“Find me then follow” ran as two fire-and-forget coroutines. Search still held a yaw sweep when follow acquired the base; both wrote velocities through different helpers. The dog pirouetted while creeping forward, marked search failed on timeout, and follow reported success because owner distance dipped under threshold during the spin. The executive fix was not “better prompts”—it was exclusive `base` ownership, explicit preempt of search on follow admit, and success predicates that require stable tracking windows, not one lucky sample.

## Retrieval questions

1. Why can a behavior tree fallback be unsafe if a low-priority playful node can tick while navigation still owns the base?
2. What is the difference between suspending a task and cancelling it, and which should “hey, come here” use while crossing a curb cut?
3. (Week-back) How does Day 30’s predicate-based completion for owner-orbit relate to executive success conditions?

## Optional 10-minute exercise

Read `brain/executive.py`’s `ResourceLocks` and `VOICE_INTERRUPT_POLICY`. Draft a sequence diagram for: active Follow, incoming “stop,” then “sit,” then a social bark gesture. Mark lease acquire/release and whether each event preempts, overlaps, or is rejected. Note one gap versus the INTRO priority list.
