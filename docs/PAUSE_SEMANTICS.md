# Pause semantics convention

**Status:** convention of record for V1 foundations (task_4 O1/O3).
**Rule:** suspension freezes *both* budget kinds — tick-counted and wall-clock.

## Why this exists

Two budgets already disagree today:

| Budget | Owner | Kind | Today's failure mode if output is suppressed |
| --- | --- | --- | --- |
| Navigation progress watchdog | `DirectiveNavigator` | tick-counted (`_steps_without_progress`, default 400 `step()` calls ≈ 40 s at 10 Hz) | A conversation-side "pause" that still ticks the navigator burns the watchdog and fails the mission mid-talk. |
| SearchOwner give-up | `SearchOwnerController` | wall-clock (`now - _started_at` vs config budget, default 45 s) | An unticked search still ages out; a tick-paused search would otherwise burn wall time while frozen. |

Suspension must freeze **both** explicitly. Controllers that only stop emitting
commands without freezing their budget are not paused — they are silently
failing.

## Per-channel freeze table

| Channel | What freezes on pause | What keeps running | Freeze owner |
| --- | --- | --- | --- |
| `navigation` | `_steps_without_progress`, `_terminal_verification_steps`, mission advancement; `Mission.status → PAUSED` | Perception ingestion (optional), collision/E-stop authority, expression idle | `DirectiveNavigator.pause()` / `resume()`; runtime suspend path **≠** `stop_navigation()` |
| `follow` | Controller step / lease claims; generation token held | PassiveOwner track observation (passive), predictor feed | Runtime `preempt(..., PAUSE)` + `ResumeIntent` |
| `search` | Wall-clock budget accrual (`_started_at` / phase clocks advance only while unpaused); state machine step | None of the three search states advance while paused | `SearchOwnerController.pause()` / `resume()` (same convention even if v1 rarely interrupts search) |
| `spatial` | Not pausable in v1 (destructive stop only) | — | `stop` via preemption table |
| `activities` | Queue drain / dispatch | Cooldown clocks may continue (social rate-limit is wall-clock by design) | ActivityCoordinator clear vs future pause |
| Executive task | `TASK_STATES` includes `suspended` as a **status, not an outcome** | Resource leases released via reconcile-stop; completion verifier must not treat suspend as success/failure | `TaskExecutive` suspend/resume |

## Runtime contracts

1. **Pause ≠ stop.** `stop_*` destroys mission/controller state. Pause retains
   it and records a `ResumeIntent` when the preemption table says `PAUSE`.
2. **Resume is a fresh dispatch.** Re-validate step tail, re-acquire TTL lease,
   honor `requires_fresh_observation` after long suspensions, guard
   double-dispatch with `(task, revision, step, attempt)` + completed-set.
3. **Fail closed.** Unknown channel pairs in `PreemptionTable` resolve to
   `STOP` with reason `undeclared_pair`.
4. **Snapshots tell the truth.** A paused navigator/search reports paused
   state in its detail/snapshot; panels must not show "running" while frozen.

## Out of scope for this page

HAL expressive-posture composition (Go2 Euler/BodyHeight spike), attention
reactions (T2), and summons/recall (T1) consume this convention but do not
redefine it.
