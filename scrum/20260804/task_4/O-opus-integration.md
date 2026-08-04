# Workstream O — Claude Opus: hygiene + repo integration

Owns every existing file. Builds against the S-card signatures in
[S-sol-modules.md](S-sol-modules.md) as written — do not wait for Sol's code
to start O2/O4 scaffolding, but do not merge until the module has landed
with its tests.

---

## O1 — V0 hygiene · days · start now

1. **Pause-semantics convention doc** → `docs/PAUSE_SEMANTICS.md`, one page:
   suspension freezes *both* budget kinds — tick-counted (navigation
   progress watchdog: 400 `step()` calls) and wall-clock (SearchOwner 45 s).
   Per-channel table: what freezes, what keeps running, who owns the freeze.
   This doc is O3/O4's spec; the audit found the two existing conventions
   are opposite, so write it before touching either.
2. **Go2 posture-composition spike procedure** → appended to
   [../task_3/A-foundations.md](../task_3/A-foundations.md): exact SportClient
   call sequence, read-back of achieved posture, pass/fail criteria for HAL
   Option A. Runs when hardware arrives; written now.
3. **B4 sweep prep**: refresh the deletion list against today's tree, stage
   the operator command in `backlog/BLOCKED.md` B4, and add the lazy v8
   shield import so BARN test files leave the grep surface of the area O2
   is about to refactor.

## O2 — BehaviorChannel registry + preempt() · ~3 days · after S1, S3

**Freeze the follow-bench + embodied ledger rows first** (the byte-identical
gate). Then:

1. `BehaviorChannel` protocol (name, arbiter source, priority, stop(reason),
   snapshot(), optional pause()/resume()) + registry in the runtime; wrap
   follow / navigation / spatial / search / activities.
2. One `runtime.preempt(claimant, *, reason)` consulting Sol's
   `PreemptionTable.default()`; replace the **16 stop sites** with calls to
   it. Behavior-preserving: the table encodes today's semantics, so every
   existing preemption test must pass unchanged — those tests are the proof
   the table is faithful.
3. Migrate `_detail` dicts to Sol's typed dataclasses (S3), `as_dict()` at
   the snapshot boundary; goldens in S3's tests guarantee JSON identity.
4. Derive `ActivityContext.busy_reason`, the expression gate inputs, and
   `SemanticRuntimeState` channel fields from the registry instead of
   per-site enumeration.
5. Swap `_behavior_generation` for Sol's `GenerationTokens` (S2) channel by
   channel; the audit's named regression (one channel's bump invalidating
   another's in-flight check) gets a runtime-level test.

**Exit:** suite green; ledger rows byte-identical; grep shows zero direct
`.stop(` calls on channels outside the registry; the preemption graph is
readable in one place.

## O3 — Navigator pause seam · ~2 days · after O1's doc

`DirectiveNavigator.pause()/resume()` per the convention doc: freezes
`_steps_without_progress` and `_terminal_verification_steps`, retains the
`Mission`; `Mission.status` → Enum including `PAUSED`; runtime suspend path
distinct from `stop_navigation()`; SearchOwner's wall-clock budget gains the
same freeze hook (even if v1 scope excludes interrupting search, the
convention applies uniformly). Tests: pause mid-mission → tick N times →
resume → mission completes; watchdog does not fire during pause; paused
snapshot states it honestly.

## O4 — Executive SUSPENDED + verifier table · ~4 days · after S2, O3

1. `SUSPENDED` added to `TASK_STATES` as a **status, not an outcome**; the
   completion verifier and `_reconcile_semantic_tasks` treat it as neither
   success nor failure (the audit's most-likely-bug warning — pin with a
   test: suspending a task must not trigger replan/abandon).
2. Suspend path releases leases via the existing reconcile-stop machinery
   and records Sol's `ResumeIntent` (S2) in the `ResumeStore`.
3. Resume-as-fresh-dispatch: re-validate the step tail, re-acquire the TTL
   lease, honor `requires_fresh_observation` after long suspensions, guard
   double-dispatch with the (task, revision, step, attempt) identity + a
   completed-set.
4. The `voice` interrupt source gets its declared suspend-vs-overlap policy
   table (it is a hardcoded no-op today — the audit's smoking gun).
5. Adapter verifier table-ization: skill→verifier registry over frozen
   controller sub-views; terminal-state constants imported from the owning
   controllers (kills the silent-literal-drift hole before `paused` becomes
   a controller state).

**Exit:** suite green; ledger rows still byte-identical; a scripted
integration test suspends a running NavigateTo via the voice source, ticks,
resumes, and the mission completes with no duplicate dispatch.
