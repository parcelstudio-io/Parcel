# Post-Sol-Ultra remediation record

**Date:** 2026-08-30
**Scope:** bounded source defects from the fresh read-only Ultra audit
**Physical-motion decision after remediation:** **NO-GO**

This record distinguishes defects that can be closed on the desktop from
hardware, evidence, and capability gates that cannot. The independent findings
remain in [`SOL_ULTRA_FINAL_AUDIT.md`](SOL_ULTRA_FINAL_AUDIT.md).

## Closed in source

| Finding | Disposition | Evidence ceiling |
| --- | --- | --- |
| Runtime selected nonexistent `physical` profile | Unit now selects the reviewed `go2_edu_plus` overlay exactly once | Source/systemd graph only; physical observation remains absent |
| Missing `parcel.target` | Added a boot-disarmed orchestration target that requires gateway/safety/runtime and wants degradable LIO/audio. Runtime also binds to gateway/safety locally; target stop propagates to runtime/audio/LIO/gateway but deliberately leaves safety alive to observe and retry while the gateway is absent. | Target parses; target-active is not process-internal or hardware readiness, and missing runtime/LIO/audio binaries and target install remain deliberate hard failures |
| Commit gate did not identify a dirty checkout | Gate now records start/finish HEAD, complete index, Git-visible tracked/deleted/untracked byte manifests, status counts, and an unchanged flag | Start/end identity, not atomic execution attestation; ignored files, environment, remote inputs, and hardware remain out of scope |
| Executive revision publication was non-atomic | Replacement now checkpoints and compensates the process-local record, proposal sinks, transition journal, report mutations, resources, and deferred checkpoint/after-step paths. The transaction machinery is isolated in a leaf helper while `TaskExecutive` retains authority. | Exception compensation at this stage was not yet isolated from concurrent sink users; the second-review disposition below supersedes this ceiling |
| `ScanBehavior`/`SearchEntity` failures could become success | Only an unambiguous inactive `arrived` state succeeds; collision, stale, unreachable, and related reason codes fail without verified facts | Runtime-adapter contract evidence, not navigation capability |
| Model-B frame lost lineage/expired in queue | Frame retains plan/revision/step/attempt/mission/action/evidence/source/speech/deadline fields and atomically revalidates epoch, generation, future time, and expiry at drain | Commit time still begins at bridge poll; no persistent cursor, live authenticated session, provider, or audio acknowledgement |
| Terminal-pose retry mixed refreshed and committed geometry | Retry now requires exact committed arrival-region, polygon, support, radius, and clearance geometry or immediately returns to the fail-closed release path | Narrow semantic-navigation regression only; the full pose-drift nightly remains red |
| Gateway `--disarmed` assertion was optional | Gateway settings refuse to construct fake or vendor I/O unless the flag is explicit | Defense in depth; it is not an independent hardware stop |

## Still open and controlling

- all six degraded-pose arms miss frozen floors; the retained person-cell pin is
  also red;
- no normally closed, independently powered actuator-disable/E-stop chain;
- AGX 64 GB versus factory NX 16 GB/D455 BOM mismatch;
- no installed aarch64 runtime/LIO/audio artifacts or Orin service exercise;
- no synchronized physical observation source, real LIO, measured clocks or
  extrinsics;
- LiDAR health lacks contiguous travel-sector coverage, CRC/sequence/loss/time
  qualification, and mounted height-band calibration;
- commissioning hashes are not bound to the observed robot or authenticated DDS;
- a wedged vendor STOP lacks a truly independent retry/kill boundary;
- gateway audit durability, sensor/thermal/person health gates, and encrypted
  owner-data infrastructure remain incomplete; and
- DSOAK-1 remains self-reported and only partially corroborated, while physical
  acoustics, braking, power, thermal behavior, and social operation are unmeasured.

## Focused guarded verification

- executive/revision/navigation-adapter selection: **70 passed**;
- deployment/provenance direct selection: **98 passed**; broader related
  selection: **145 passed**;
- Model-B lineage and drain freshness: **9 passed**;
- terminal-pose geometry/release: **14 passed**;
- mandatory disarmed launch selection: **8 passed, 1 skipped**.
- one integrated post-review selection across these changed runtime surfaces:
  **125 passed, 4 skipped**.
- final structural transaction/debt panel after the helper extraction:
  **12 passed**; a separate gate/terminal/provenance panel passed **10/10**.

The final repository commit gate is reported in the final assessment rather
than inferred from these overlapping focused selections. Its quiet repeat
passed every hard row with 11,417 tests partitioned into 11,330 non-slow and 87
slow, and matching start/finish checkout identity.

## Second independent review and postfix dispositions

A second fresh read-only Ultra pass reviewed the first remediation instead of
accepting its focused test results. It found three additional source defects:
service loss/target-stop/environment-file semantics, valid Model-B lifecycle
sequences rejected as corrupt, and revision compensation exposed to concurrent
proposal publication/arbitration. The complete findings and dispositions are
preserved in
[`SOL_ULTRA_POSTFIX_AUDIT.md`](SOL_ULTRA_POSTFIX_AUDIT.md).

The bounded postfix changes now:

- bind runtime lifetime to both authority services, keep the stop-only safety
  principal alive when gateway/target is stopped, select only the existing
  `go2_edu_plus` profile, and place fixed boot invariants after optional
  environment files in each `ExecStart`;
- distinguish a deferred replacement from an activated replan and accept only
  exact owner-authored next-step precondition/resource waits; and
- require transaction hooks on every revision sink and hold all registered
  sink locks across commit, owner-journal append, or rollback, so concurrent
  `publish()` / `resolve()` cannot see or erase a failed half-commit.

Focused evidence is **33 passed** for the service graph, **14 passed** for the
Model-B lifecycle/oracle, and **14 passed** for revision failure/concurrency.
One combined post-fix selection passed **91/91**. Revision replacement is now
thread-isolated within one process, but it is still not crash-consistent,
database-backed, or distributed. The hardware and extended-nightly blockers
above remain controlling, so physical motion remains **NO-GO**.

A third independent read-only pass then found a stale gateway parity test,
non-fail-loud target activation, additional valid Model-B histories, and a
shared-sink inverse-registration deadlock risk. The bounded final postfix makes
the parity test parse the real late environment wrapper, requires the three core
services at target activation, admits only the additional owner-valid lifecycle
edges, and acquires all sink locks in one process-wide object-identity order.
The exact adversarial panel passed **19/19** with scoped static checks green.
Details are in
[`SOL_ULTRA_POSTFIX_AUDIT.md`](SOL_ULTRA_POSTFIX_AUDIT.md).
