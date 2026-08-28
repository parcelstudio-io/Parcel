# P0 `SIM-CONTRACT-1` implementation report

Date: 2026-08-26
Scope: software contracts and desktop simulation seams only
Physical hardware used: none
Physical-motion decision: **NO-GO**

## Outcome

The highest-priority research design is now represented by a bounded P0 code
tranche: deployment-bound capability truth, fail-closed embodied-conversation
state, a normal-runtime disarmed Unix-gateway composition, an isolated H2b
completion latch, a default-off local research plane, and a proposal-only
simulator-learning registry/promotion gate.

This is a contract implementation, not completion of `SIM-CONTRACT-1` and not
a mount authorization. In particular, it adds no native Unitree SDK2/DDS
controller, no gateway-compatible physical `SportPort`, no model-to-motion
path, no production cloud/KMS provider, and no policy/model activation path.

## Implemented boundaries

| Slice | Product code | What the implementation establishes | What it does not establish |
|---|---|---|---|
| Capability truth | `src/parcel_robot/capabilities/manifest.py`, `src/parcel_robot/skills/capability_manifest.py` | Canonical declarations and profile selection; exact artifact/schema digests; deployment/environment/adapter identity; process-local HMAC-authenticated commissioning evidence; commissioned state can only be regenerated from verified evidence; optional runtime/voice manifest consumption | No signed external commissioning service, provisioned hardware trust root, reviewed physical trajectory record, or physical deployment commission exists |
| Embodied conversation | `src/parcel_robot/contracts/{companion_v1,dialogue_state_v1,opportunity_v1,terminal_claim_v1}.py`, `src/parcel_robot/voice/{companion_auth,companion_state}.py` | Strict dialogue/envelope/proposal/admission/receipt/claim records; scoped and expiring consent; owner/operator evidence checks; process-local envelope/receipt/operator authenticity; exact manifest/action/mission binding; receipts are required before a terminal claim; proposals and admissions expose no motion authority | The reducers are not yet the complete live Realtime/session executive; there is no executive receipt publisher backed by a physical controller, no end-to-end companion-mission graph, and no owner-rated or mounted-audio validation |
| Disarmed runtime path | `src/parcel_robot/control/motion_gateway.py`, `src/parcel_robot/control/factory.py` | The normal `RobotRuntime` can accept a `ControlManager` using the real Unix `MotionGatewayClientV1` boundary; desktop tests compose runtime -> Unix gateway -> fake Sport; the adapter has no `acquire` or `command` call, refuses velocity, starts/reconnects disarmed, sends E-stop across the socket, and will not elide an ordinary stop on stale stationary evidence | Fake Sport does not attest a Unitree transport. There is no native SDK2/DDS bridge, motion-enabled mode, Orin run, physical feedback provenance, vendor writer, or measured stop envelope |
| Independent completion H2b | `src/parcel_robot/navigation/independent_completion.py` | Default-disabled, pipeline-isolated identity -> verified new pose epoch -> conservative terminal-geometry latch; outputs a terminal-claim proposal only and never motion | It is not integrated. The preregistered holdout is **REFUTED**: 113/120 alias recoveries versus the 114/120 gate, despite 120/120 nominal completion and zero false claims across 360 false-completion opportunities |
| Local research plane | `src/parcel_robot/research_plane/` | Default-off/no-I/O composition; bounded typed summaries; dedicated SQLite spool; consent subject/destination checks; deterministic content-addressed bundles; corruption/path guards; retention/revocation cascade; durable attempt-byte accounting; pending content-free remote-deletion obligations; injected AEAD- and remote-receipt-verifier seams that fail closed when absent | It contains no AES implementation, KMS/HSM integration, TLS/IAM client, object store, Starlink transport, remote deleter, backup/catalog deletion, legal-compliance proof, or production de-identification claim. A provider callback is an interface, not evidence that encryption or remote deletion occurred |
| Simulator learning | `src/parcel_robot/learning_loop/` | Immutable train/dev/frozen-test registry with leakage-group separation and canonical digests; deterministic, lineaged failure-case proposals that cannot mine frozen test; candidate evaluation digests and zero-tolerance safety counters; default-off human-review/signature/rollback gate | A successful decision is only `propose_for_activation` and always has `authorizes_activation == false`. There is no trainer, dataset service, external signing authority, shadow deployer, hot swap, rollback executor, or automatic self-learning loop |

## H2b experimental decision

The H2b package executed 600 cases across three arms (1,800 rows). The
canonical runs retained 120/120 nominal completion, converted all 360 alias,
outside-boundary, and broken-lineage false-completion opportunities to zero
false claims, and produced bounded typed uncertainty when evidence was
missing. It nevertheless recovered only 113/120 alias cases; the frozen gate
required 114/120. The 9/10-gate result is `REFUTED`, not rounded up or waived.
The feature stays default-disabled and isolated from `navigation.pipeline`.

Exact design, results, verifier, excluded pilot runs, and limitations are in
`independent-completion-h2b/`. Its artifact verifier reports 13/13 integrity
checks for the canonical result; that is research-artifact integrity, not a
product release or physical-safety result.

## Safety and authority invariants retained

- Language/model outputs can propose wording or one semantic action; they do
  not acquire a gateway lease or authorize actuation.
- Capability availability is bound to an exact deployment target and
  authenticated commissioning payload. Serialized `commissioned: true` is not
  trusted on its own.
- Movement bindings require verified-owner evidence and the exact consent
  scope; an operator path additionally requires authenticated operator
  evidence.
- Only a fresh, authenticated, exact-match terminal receipt can license a
  completion statement. A receipt identifier alone is not authentication.
- The new gateway adapter is permanently disarmed. The test composition uses
  fake Sport, while gateway vendor mode continues to refuse.
- H2b emits no velocity/command and does not authorize motion.
- Research and learning packages have no control adapter. Remote trust-provider
  seams deny when providers are missing, and a promotion result cannot activate
  a candidate.

## Verification status

Focused tests exist at:

- `tests/test_capability_manifest_v1.py`
- `tests/test_p0_companion_state.py`
- `tests/test_disarmed_gateway_composition.py`
- `tests/test_independent_completion_h2b.py`
- `tests/test_research_plane.py`
- `tests/test_learning_loop_registry.py`

Focused lint/contracts/regressions and the dependency/import ratchets are
green. The final guarded merged command was
`pytest -q -m "not slow" --tb=short` under label `final-default-suite`; it is
**RED** with 10,811 passed, 111 failed, 23 skipped, 83 deselected, and 5 xfailed
in 549.20 seconds. Most failures are the expected legacy-fixture migration
surface exposed by fail-closed commissioning: tests that intend motion do not
inject a commissioned capability manifest. Two W0B ratchets also assert the
superseded rule that runtime never imports commissioning. These are recorded
as unresolved merged-tree debt, not hidden by weakening admission.

## Immediate next build

1. Finish `SIM-CONTRACT-1` at the simulator boundary: integrate a pinned native
   `unitree_mujoco` SDK2/DDS path through a simulated `SportPort` or explicit
   high-level-to-low-level bridge while preserving the gateway as sole writer.
2. Wire the companion reducers and authenticated executive receipt publisher
   into the live multi-turn session, initially with stationary/no-motion acts
   only; add raw-audio correction, interruption, stale-receipt, non-owner,
   self-TTS, and body-busy refuters.
3. Keep H2b out of the product pipeline. Run an untouched recorded-sensor
   replay with bounded active reacquisition and jointly gate false claims and
   recovery coverage.
4. Add real research-plane providers only in an isolated consented pilot:
   client AES-256-GCM, managed key wrapping, authenticated remote receipts,
   interrupted upload, object/catalog/derived deletion, and measured Orin and
   network cost. Until then keep it local and off by default.
5. Connect generated scenarios and frozen evaluations to an offline trainer
   and signed human release workflow without adding activation authority to
   the learning package. A separately reviewed deployment service must remain
   the only activation boundary.
6. Only after those desktop/simulator gates pass, execute the stationary
   Stage-0 ladder in `MOUNT_READINESS.md`; motion-enabled physical work remains
   prohibited.
