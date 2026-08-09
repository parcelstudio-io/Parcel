# Pause semantics: implemented primitives and integration limits

Implementation snapshot: 2026-08-05 (K3 resume-transaction completion). This page
is the convention of record for suspending a behavior without declaring it
successful, failed, or cancelled.

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

| Channel | What pause preserves | What continues while paused | Resume consumer |
| --- | --- | --- | --- |
| `navigation` | `Mission`, its previous status, semantic-resolution state, progress count, and terminal-verification count | Runtime perception and global safety authority continue; a paused navigator itself returns zero motion | Redispatched `NavigateTo` and `resume_navigation()` consume the stored `ResumeIntent` via the central coordinator and call `navigator.resume()` — not a cold restart. |
| `search` | Search phase, rolling planner state, last observed owner location, total budget, and phase budget | The controller emits zero motion; runtime perception may continue to update shared owner tracking | Redispatched `SearchOwner` resumes a paused controller from the stored intent. |
| `follow` | A `ResumeIntent` containing follow mode and requested distance | Passive owner heading/predictor feeds can continue outside the stopped controller | Search→follow recovery and redispatched `FollowFormation` consume the stored follow intent. This remains reconstruction (pause stops the controller), not a frozen in-place controller. |
| `spatial` | Nothing | — | Not pausable; applicable preemption is destructive stop. |
| `activities` | Nothing | Cooldown is wall-clock by design | Not pausable; stop clears queued/running gestures. Gesture `safe_checkpoint` is schema metadata, not an implemented checkpoint hand-off. |
| Executive task | Current validated plan, step index, and attempt remain in a nonterminal `suspended` state | Resources are released; `tick()` emits no dispatch while suspended | `resume_task()` requeues the step; the skill adapter then consumes the channel `ResumeIntent` when present. |

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
   replayed. The central coordinator preempts conflicting channels before
   restoring the paused controller.
4. **Preemption fails closed.** An undeclared `(claimant, active)` pair resolves
   to destructive `STOP`. The current default table explicitly declares every
   ordered pair among its registered channels; `search -> follow` is its one
   `PAUSE` override, while most other interactions are `STOP`, `DEFER`, or
   `NONE` according to priority and explicit overrides.
5. **Suspension is not an outcome.** `TaskExecutive` releases resources and
   marks the task `suspended`; success/failure verification must not consume
   that state as completion.
6. **Resume fails closed on intent and freshness.** Missing or expired intents
   do not silently resume. When `ResumeIntent.requires_fresh_observation` is
   set, `resume_rejection_reason` / `_resume_from_store` reject unless the
   runtime observation passes `_observation_is_fresh` (telemetry TTL). The
   intent remains stored so a later fresh observation can retry.

## Suspend→resume transaction (K3)

The automatic semantic loop is closed for the pausable channels:

1. Suspend releases leases, pauses the channel, and records a `ResumeIntent`.
2. `resume_task()` requeues a fresh `DispatchRequest` for the same step.
3. Redispatched `NavigateTo` peeks the navigation intent; on a matching paused
   mission it calls `_resume_from_store` → `resume_navigation` semantics
   (progress retained). A different directive clears the intent and cold-starts.
4. Search→follow uses only the stored follow `ResumeIntent` (legacy
   `_resume_follow_after_search` tuple removed). Abandoned/failed search clears
   the follow intent.
5. Expired intents and stale required observations raise; they do not reconstruct
   a synthetic resume.

See [COMPANION_NAVIGATION_ARCHITECTURE.md](COMPANION_NAVIGATION_ARCHITECTURE.md)
for the wider executive, arbitration, and safety boundaries.

## Remaining limits (honest)

- Follow pause is still reconstruction (stop + intent payload), not a frozen
  controller snapshot; the follow detail may read idle while an intent is stored.
- `spatial` / `activities` remain non-pausable.
- Voice amendment of a suspended plan (re-proposal → validator → resume) is a
  later card on top of this transaction, not part of K3.
- Central freshness uses the runtime telemetry TTL, not yet the V1
  `EvidenceEnvelope` ns clocks end-to-end.
