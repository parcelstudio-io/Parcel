# Sol Ultra post-fix audit and disposition

**Audit date:** 2026-08-30
**Reviewer:** fresh independent `gpt-5.6-sol`, ultra reasoning, read-only
**Physical-motion decision:** **NO-GO**
**Observe-only / motors-disabled:** conditional

This record covers the second and third independent review passes. Both
reviewers made no edits, ran no tests, and did not touch the live simulator
socket, owner ports, database, or hardware. Each reviewed the preceding
remediation rather than trusting its green focused panels. The original
hardware, capability, and evidence blockers in
[`SOL_ULTRA_FINAL_AUDIT.md`](SOL_ULTRA_FINAL_AUDIT.md) remain controlling.

## Findings preserved from the read-only pass

1. **P1 — service failure semantics and fixed launch configuration were not
   yet trustworthy.** `Requires=` alone did not guarantee that runtime stopped
   after an authority service failed. Target stop propagation could also stop
   the safety supervisor with the gateway, and optional environment files could
   override boot-disarm and other fixed launch invariants.
2. **P2 — the Model-B consumer rejected valid executive histories.** After one
   step succeeded, the next step could legitimately wait for a precondition or
   resource before emitting `started`; that owner-authored sequence was rejected.
   A deferred replacement was also labelled `replanned` before the replacement
   activated, so ordinary old-plan progress looked corrupt and permanently
   latched narration closed.
3. **P2 — exception compensation was not isolated from concurrent sink users.**
   A revision could be visible to `publish()` or `resolve()` between sink commit
   and compensation, and a concurrent publish could then be erased by rollback.
   Process-local value restoration was therefore not sufficient atomicity.

The reviewer agreed with the proposal-only Model A / receipt-backed Model B
direction and found no reason to relax STOP, collision, completion, or actuator
authority. It retained physical **NO-GO**.

## Source dispositions

| Finding | Disposition | Remaining ceiling |
| --- | --- | --- |
| Runtime/service graph | Runtime now has `Requires=` + `BindsTo=` + `After=` for gateway and safety. `parcel.target` requires gateway/safety/runtime, wants degradable LIO/audio, and excludes safety from `PropagatesStopTo=` so it remains alive when the gateway disappears. Runtime selects only the existing `go2_edu_plus` profile. | Source/systemd-parse evidence only. A wanted LIO/audio service can fail and process-internal readiness is not represented; runtime/LIO/audio and pinned aarch64 artifacts are absent; no Orin lifecycle run exists. |
| Environment precedence | Each optional `EnvironmentFile=` remains available for reviewed commissioning values, but fixed disarm, role, socket, vendor body/topics/queue, peer identities, and conservative audio mode are assigned later by `/usr/bin/env` in `ExecStart`; explicit `--disarmed` remains required. | Root-owned files still control all non-fixed settings and need image schema, ownership, and target qualification. |
| Model-B lifecycle | Only an activated replacement is `replanned`; `replacement_deferred` is progress on the active lineage. Exact owner-authored next-step waits, suspend/cancel between steps, repeated waits, retry-attempt waits, and resumed-running result paths now advance under revision/hash/step/attempt checks. Forged next-step variants still permanently fail closed. | The observer remains process-local and non-speaking. Commit-time timestamps, restart-safe cursor/outbox, authenticated live speech generation, provider/audio acknowledgement, and complete child/resume lineage remain absent. |
| Concurrent revision compensation | Every registered revision sink must expose acquire/release/snapshot/restore hooks. `TaskExecutive` takes every sink lock in a process-wide `id()` total order and holds all locks across sink commits, record mutation, owner journal append, or compensation. `ProposerBus` and `GoalArbiter` serialize their live operations on those locks. | Thread-isolated in one process only. It is not crash-consistent, database-backed, or distributed; arbitrary sink hooks must not acquire hidden locks in an inverse external order. |

## Verification after disposition

- service graph, hostile environment override, socket credentials, and stop-only
  supervisor panel: **33 passed**; temporary complete-namespace
  `systemd-analyze verify`: clean;
- Model-B valid/forged lifecycle and DMC-4 oracle panel: **14 passed**;
- revision failure-injection/concurrency structural panel: **14 passed**; and
- one combined post-fix selection spanning Model B, DMC-4, revision sinks,
  stale-proposal rejection, service graph, peer credentials, stop-only safety,
  and disarmed composition: **91 passed**.

These are desktop/injected source regressions. They close the three reviewed
software defects; they do not provide a physical STOP chain, synchronized
mounted perception, a trained generalized policy, measured braking, target
power/thermal/timing evidence, or safe people-adjacent operation.

## Third read-only verification pass

A fresh post-remediation Ultra instance found four more inconsistencies instead
of accepting the 91-test panel:

1. the semantically correct `/usr/bin/env` launch wrapper broke an older gateway
   service/CLI parity test that still assumed the first token was the gateway
   executable and required the removed `Environment=` rows;
2. a target made only of `Wants=` could report active after every core service
   failed, and the stated rationale for avoiding `Requires=` was incorrect;
3. the two repaired Model-B examples left valid resumed-running results,
   retry-attempt waits, repeated waits, and suspend/cancel-between-step histories
   rejected; and
4. taking sink locks in executive registration order allowed two executives
   sharing sinks in opposite order to deadlock.

The parity test now parses the late environment wrapper and feeds only the real
gateway arguments to its CLI. The target requires gateway, safety, and runtime,
wants degradable LIO/audio, and still excludes safety from explicit stop
propagation. The Model-B reducer covers the additional exact owner histories,
and revision transactions acquire shared sinks by one process-wide object-
identity order. A guarded adversarial selection over these exact findings passed
**19/19**; scoped Ruff, `py_compile`, and diff checks passed. The complete
repository result is recorded below.

The target and its tests remain untracked worktree content until the owner
commits them, and no image installer currently delivers the target, runtime
binary, or `go2_edu_plus` overlay. Optional environment files also remain the
wrong destination for long-lived hosted/device secrets; target commissioning
must move those to systemd credentials or an equivalently narrow file-handle
boundary. Neither issue changes source fail-closed behavior, but both remain
deployment gates.

The subsequent quiet repository commit gate passed every hard row in **280.3
s**: **11,417 collected = 11,330 non-slow + 87 slow**, no orphan/overlap, Ruff
72 baseline / 72 current / 0 new, and start/finish checkout identity matched.
This is desktop source evidence only and does not alter the physical verdict.

## Controlling decision

The next permissible deployment rung remains a checklist-reviewed,
permanently-disarmed target install and motors-disabled HIL on the frozen BOM.
Powered autonomous motion—including sidewalks, crosswalks, elevators, stairs,
and close pedestrians—remains **NO-GO**.
