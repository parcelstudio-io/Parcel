# Task 3 · `SIM-CONTRACT-1-P0` — fail-closed implementation tranche

**Date:** 2026-08-26 (America/New_York)
**Status:** P0 CONTRACT TRANCHE IMPLEMENTED · MERGED DEFAULT SUITE RED ·
FULL `SIM-CONTRACT-1` INCOMPLETE · PHYSICAL MOTION `NO-GO`

## Owner request

Implement the prioritized design from DOG-GEN-1: capability truth,
conversation-to-body contracts, same-path disarmed gateway composition,
independent completion research, a governed research data plane, and an
immutable simulator-learning loop.

## Delivered

### A. Deployment-bound capability truth

`CapabilityManifestV1` now binds selected declarations to exact schema or
trajectory digests, deployment/environment/adapter identity, and a
process-local authenticated commissioning record. Availability cannot be
loaded from a serialized `commissioned: true`, inferred from a skill name, or
carried across a different deployment target. The runtime/voice agent can
consume an injected manifest and revalidate the effective motion catalog.

This does not constitute physical commissioning. No capability/trajectory was
reviewed, signed, provisioned, or exercised as a physical Go2 commission.

### B. Embodied multi-turn state contracts

Strict `DialogueStateV1`, `EmbodimentEnvelopeV1`, opportunity, action
proposal/admission/receipt, memory, repeat, and terminal-claim records were
added. Local admission binds the exact manifest/action, consent scope,
initiator, verified owner or authenticated operator evidence, body/space
state, and conservative TTLs. The complete envelope and operator/receipt
evidence cross process-local authenticated seams; a terminal receipt is needed
before completion language can be licensed. Proposals and admissions never
authorize motion.

These reducers are not yet the fully wired live Realtime/session executive,
and no physical executive produces trusted receipts.

### C. Normal runtime at the disarmed gateway rung

The registered `motion_gateway_disarmed` controller/state pair lets the normal
`RobotRuntime` use a `ControlManager` over the real Unix gateway client. The
desktop composition runs through the Unix gateway to fake Sport and remains
disarmed: there is no `acquire` or `command` call, body velocity is unsupported,
reconnect stays disarmed, E-stop crosses the socket, and stale stationary state
cannot suppress an ordinary stop.

This is not a native Unitree simulator or robot writer. Gateway vendor mode
still refuses; SDK2/DDS, AGX Orin, physical feedback, and measured STOP are
absent.

### D. H2b independent completion

The default-disabled isolated latch requires discriminative identity, a
strictly newer identity-rooted pose epoch with bounded residuals, and
covariance-expanded target-relative terminal geometry. Its positive result is
only a terminal-claim proposal; it has no motion surface and is not connected
to `navigation.pipeline`.

The preregistered 600-case x three-arm experiment is **REFUTED**. H2b achieved
113/120 alias recovery against the 114/120 gate. It retained 120/120 nominal
completion and zero false claims across 360 false-completion opportunities,
but the failed gate remains binding and the latch stays default-off.

### E. Local research and simulator-learning planes

The research plane is default-off and summary-only. It adds a dedicated
bounded SQLite spool, deterministic bundles/replay, consent and destination
binding, local retention/revocation cascade, per-attempt byte accounting,
canonical AEAD context, and fail-closed injected verification seams for
ciphertext and remote receipts. It has no encryption/key provider, network
client, object store, Starlink integration, or remote deleter.

The learning package adds immutable train/dev/frozen-test split registries,
leakage-group checks, deterministic failure-mined proposals, canonical
candidate evaluation and safety counters, and a default-off signed-review/
rollback promotion gate. Even an accepted gate result is proposal-only and
cannot activate a candidate.

## Acceptance ledger

| Original `SIM-CONTRACT-1` deliverable | State after this task |
|---|---|
| Exact capability/commissioning contract | Implemented as a process-local software boundary; no physical commission |
| Normal runtime -> Unix gateway -> fake Sport, disarmed | Implemented at desktop test tier |
| Native `unitree_mujoco` SDK2/DDS simulator writer | **Not implemented** |
| Typed progress/liveness budgets | Earlier social-progress shadow contracts exist; the full executive planner-outcome integration remains incomplete |
| H2b completion contract and holdout | Implemented and tested; hypothesis **REFUTED**, default-off, not integrated |
| Dialogue/envelope/receipt admission | Implemented as strict local contracts; complete live session/executive integration remains incomplete |
| Immutable split/eval/promotion contract | Implemented proposal-only; no trainer or activation service |
| Default-off local summary spool | Implemented locally; production crypto/cloud/deletion providers absent |
| Go2/Orin/physical promotion | **Not authorized and not attempted** |

## Verification

Focused and adjacent contract runs passed, including 193 P0 contract tests,
372 commissioned-runtime regressions, and 23 architecture/import ratchets.
The guarded merged non-slow suite (`final-default-suite`) is **RED**:
10,811 passed, 111 failed, 23 skipped, 83 deselected, and 5 xfailed in
549.20 seconds. The dominant failure is explicit migration debt: legacy motion
fixtures do not inject a commissioned capability manifest and are now disarmed
by the delivered fail-closed boundary. Two W0B ratchets also encode the older
rule that runtime must never mention commissioning. This result must not be
represented as a green merged close, and the safety boundary must not be
weakened merely to recover the legacy expectations.

## Required next task

Build the native pinned Unitree MuJoCo SDK2/DDS simulator boundary while
preserving the gateway as sole writer; wire companion state and authenticated
executive receipts into the live session in stationary mode; and connect the
immutable registry to an offline evaluator/trainer without adding activation
authority. Separately run H2b on an untouched recorded-sensor replay. The
stationary Stage-0 and every physical-motion rung remain governed by the
mount-readiness ladder.

## Artifacts

- [Implementation report](../../../research/20260826/IMPLEMENTATION_REPORT.md)
- [Research synthesis](../../../research/20260826/FINAL_REPORT.md)
- [Mount-readiness decision](../../../research/20260826/MOUNT_READINESS.md)
- [H2b verdict](../../../research/20260826/independent-completion-h2b/VERDICT.md)
- [Research data-plane implementation](../../../research/20260826/research-data-plane/IMPLEMENTATION.md)
