# Sprint 2026-08-16 — N24 bounded gateway contract/fake slice

**Executor:** ChatGPT Sol 5.6 Ultra.  
**Durable card:** [../../../backlog/NEXT.md](../../../backlog/NEXT.md) N24.  
**Accepted design:**
[../../20260812/task_1/PRODUCTION_COMPANION_PLAN.md](../../20260812/task_1/PRODUCTION_COMPANION_PLAN.md)
W0-C/W0-F, narrowed by the 2026-08-16 HLD dependency map.

## Objective

Land the software/fake portion of SG-E: reconcile the live command TTL with
the proposed latency targets, freeze strict V1 gateway DTOs and seeded
authority invariants, exercise high-level Sport failure fixtures, and prove
with separate OS processes that killing a client after a nonzero admission
causes a gateway-local stop and a disarmed, non-resuming restart.

This sprint does not create a physical or product motion path. N28 remains the
complete native gateway card, N42 owns the shared `authority-invariants` CI
runner, N29 owns generated compatibility/admission artifacts, and B16 owns
hardware proof.

## Board

| ID | Card | Depends on | Status |
| --- | --- | --- | --- |
| SG-E1 | RC-4 TTL/latency derivation and live-constant pin | — | **done** |
| SG-E2 | Strict bounded gateway V1 DTOs | SG-E1 | **done** |
| SG-E3 | Fake Sport delayed/no-reply/state/lease/writer/stop faults | SG-E2 | **done** |
| SG-E4 | Separate gateway/client SIGKILL + restart proof | SG-E2, SG-E3 | **done** |
| SG-E5 | Frozen invariant and deterministic failure-seed inventories | SG-E2–SG-E4 | **done** |
| SG-E6 | Regression, lint, static collection, and status handoff | all | **done** |

## Working agreements

1. No vendor SDK is installed or imported and no physical socket/NIC is
   opened. The new process speaks only to `FakeSportServiceV1`.
2. No code in `RobotRuntime`, navigation, the physical controller factory, or
   commissioning is wired to this package.
3. Cross-process freshness uses a duration TTL; the receiver derives its own
   monotonic deadline. Client monotonic timestamps never cross the seam.
4. Admission ACK, fake `StopMove` return, fresh fake state, and physical
   stillness are distinct claims.
5. B5–B8 remain owner decisions. No fixture or test here selects their
   product semantics.
6. The invariant list and seed inventory belong to N24; shared gate assembly,
   evaluator behavior, mutation scoring, and commit/nightly CI ownership stay
   with N42.

## Definition of done

- The executable RC-4 table fails if the live `50 Hz` / `0.35 s` values or
  proposed targets drift without a new derivation.
- All DTOs round-trip through a strict, bounded protocol and reject unknown
  versions/fields, bool-as-int, non-finite values, wrong frames, bad hashes,
  and invalid TTLs.
- Delayed/no-reply Move, late completion, stale/out-of-order state, lease
  loss, writer conflict, and StopMove failure have deterministic tests.
- A separate fake gateway survives a `SIGKILL`ed nonzero client, records a
  local confirmed fake stop, never resumes, and restarts with a new epoch in
  `DISARMED`; same-boot replay and the prior epoch are refused.
- [SG_E_STATUS.md](SG_E_STATUS.md) records evidence and the exact remaining
  W0-C/F gates without calling the slice a complete gateway.

## Handoff

The measured handoff, remaining gates, and `does_not_prove` boundary are in
[SG_E_STATUS.md](SG_E_STATUS.md).
