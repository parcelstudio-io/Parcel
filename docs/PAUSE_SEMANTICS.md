# Pause semantics: implemented primitives and integration limits

Implementation snapshot: 2026-08-04. This page is the convention of record for
suspending a behavior without declaring it successful, failed, or cancelled.

The rule is simple: a true pause freezes every mission budget owned by the
paused controller and emits no motion. Merely suppressing its command while its
watchdog or deadline continues to advance is not a pause.

## Why budget type matters

| Budget | Owner | Type | Implemented pause behavior |
| --- | --- | --- | --- |
| Navigation progress and terminal-verification watchdogs | `DirectiveNavigator` | Tick-counted (`_steps_without_progress` and `_terminal_verification_steps`) | `pause()` retains the mission and counters; `step()` returns `mission_paused` without advancing them. `resume()` restores the previous mission status and counters. |
| Owner-search total and phase deadlines | `SearchOwnerController` | Wall-clock | `pause(now=...)` snapshots elapsed times; `resume(now=...)` rewinds the clock origins so paused wall time is excluded. A paused `step()` returns zero motion. |

This distinction is observable: an unticked search can still age out, while a
navigation loop that continues to call `step()` can still exhaust a tick
watchdog. Each controller therefore owns its own freeze implementation.

## What is implemented by channel

| Channel | What pause preserves | What continues while paused | Current limitations |
| --- | --- | --- | --- |
| `navigation` | `Mission`, its previous status, semantic-resolution state, progress count, and terminal-verification count | Runtime perception and global safety authority continue; a paused navigator itself returns zero motion | `resume_navigation()` is an explicit runtime API. Semantic task redispatch does not yet consume the stored intent automatically. |
| `search` | Search phase, rolling planner state, last observed owner location, total budget, and phase budget | The controller emits zero motion; runtime perception may continue to update shared owner tracking | The generic stored search intent has no automatic consumer. Search-to-follow recovery still uses a separate legacy tuple. |
| `follow` | A `ResumeIntent` containing only follow mode and requested distance | Passive owner heading/predictor feeds can continue outside the stopped controller | This is reconstruction, not a frozen controller: pause calls `FollowOwnerController.stop()`, cancels its lease, and bumps its generation token. The normal follow snapshot consequently appears idle rather than paused. |
| `spatial` | Nothing | — | Not pausable; applicable preemption is destructive stop. |
| `activities` | Nothing | Cooldown is wall-clock by design | Not pausable; stop clears queued/running gestures. Gesture `safe_checkpoint` is schema metadata, not an implemented checkpoint hand-off. |
| Executive task | Current validated plan, step index, and attempt remain in a nonterminal `suspended` state | Resources are released; `tick()` emits no dispatch while suspended | `resume_task()` only requeues the step for a fresh dispatch. It does not itself resume a behavior channel. |

Per-channel generation tokens invalidate late asynchronous work. Tokens are
**bumped** on pause; they are not held constant. `ResumeStore` keeps at most one
replace-on-suspend intent per channel and drops it when taken after its TTL.

## Runtime authority contracts

1. **Pause is not stop.** `stop_*` destroys controller or mission state. A
   pause retains controller state where supported and records a bounded
   `ResumeIntent`.
2. **Safety never pauses.** E-stop, stale-data checks, collision gates, and
   command ownership remain authoritative while another behavior is frozen.
3. **Resume must reacquire authority.** A resumed channel must make a new lease
   claim and pass current perception/safety gates; stored motion is never
   replayed.
4. **Preemption fails closed.** An undeclared `(claimant, active)` pair resolves
   to destructive `STOP`. The current default table explicitly declares every
   ordered pair among its registered channels; `search -> follow` is its one
   `PAUSE` override, while most other interactions are `STOP`, `DEFER`, or
   `NONE` according to priority and explicit overrides.
5. **Suspension is not an outcome.** `TaskExecutive` releases resources and
   marks the task `suspended`; success/failure verification must not consume
   that state as completion.

`ResumeIntent.requires_fresh_observation` currently records policy intent but
is not enforced by a central resume dispatcher. Navigation and owner search do
still reject stale observations in their normal per-tick execution paths.

## End-to-end gap to close

The repository has tested controller primitives, task suspension, intent TTLs,
and redispatch, but it does **not** yet implement one automatic semantic
suspend-to-resume transaction. In particular:

1. resuming a `TaskExecutive` task produces a fresh `DispatchRequest`;
2. a redispatched `NavigateTo` does not take the navigation `ResumeIntent` or
   call `resume_navigation()`;
3. follow and search intents have no general runtime consumer; and
4. the `requires_fresh_observation` bit is not centrally checked before resume.

The existing executive integration test proves that a suspended task emits no
dispatch and later redispatches `NavigateTo`; it does not prove that the old
mission resumes, retains progress, and completes. Until a resume coordinator
closes that loop, callers that need non-destructive navigation continuation
must explicitly use `pause_navigation()` / `resume_navigation()` and should
verify fresh observations before the latter call. Note that
`resume_navigation()` currently resumes a paused navigator even when the
stored intent is absent or expired, so intent expiry alone is not a safety
interlock.

See [COMPANION_NAVIGATION_ARCHITECTURE.md](COMPANION_NAVIGATION_ARCHITECTURE.md)
for the wider executive, arbitration, and safety boundaries.
