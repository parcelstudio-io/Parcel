# SG-E status — N24 bounded gateway contract/fake slice

**Date:** 2026-08-16  
**Base commit:** `8473a5159bab` plus preserved pre-existing/concurrent worktree
changes outside this card.  
**Verdict:** **N24 bounded fake/process slice LANDED.** This is not the complete
W0-C/W0-F implementation and is not a product or physical gateway.

## What landed

### 1. RC-4 derivation before protocol freeze

[../../../docs/GATEWAY_TTL_LATENCY_DERIVATION.md](../../../docs/GATEWAY_TTL_LATENCY_DERIVATION.md)
reconciles every accepted proposed p99 target against the unchanged live
`ControlTiming` / factory / canonical config values:

- `50 Hz` = `20 ms` per control period;
- `command_timeout_s = 0.35 s` = `350 ms` = `17.5` periods;
- at the proposed `0.3–0.5 m/s` pilot ceiling, the simple TTL travel bound is
  `0.105–0.175 m`, before any physical braking distance;
- the `150 ms` client/lease-loss stop-initiation target cannot be guaranteed
  by a `350 ms` TTL fallback, so the fake gateway detects local connection and
  lease loss directly;
- stop initiation, RPC completion, fake stationary feedback, and physical
  motion ended remain separate events.

The same executable record also closes W0-B handoff H2 at the derivation
layer: commissioning TTL is capped at the live `0.35 s`; step duration is
capped at the live `1.0 s stop_timeout_s` (a `0.10 m` command+stop software
bound at `0.05 m/s`); and the record exposes why production settled thresholds
`0.08 m/s` / `0.12 rad/s` cannot be reused as low-speed commissioning
stillness. N24 records these facts but does not choose new product thresholds.

The table is rendered from `parcel_robot.bridge.timing` and the test pins its
text plus `ControlTiming`, `control.factory._timing({})`, and
`configs/robot.yaml`. N24 made no TTL/config retune.

### 2. Strict versioned gateway DTOs

The isolated `parcel_robot.bridge.protocol` module adds strict V1 DTOs:

- `GatewayHelloV1`: fresh gateway boot epoch, gateway sequence, current phase,
  and required hash identities;
- `GatewayAcquireV1`: writer, matching boot epoch, per-boot sequence, and a
  bounded duration TTL;
- `GatewayCommandV1`: writer/epoch/sequence, receiver-local duration TTL,
  `base_link` body velocity, task/trace identity, and config/capability/
  calibration/firmware hashes;
- `GatewayStopV1`, `GatewayStateV1`, and `GatewayStopReportV1`: explicit stop,
  fake state, stop RPC outcome, and later fake stationary-state evidence;
- `GatewayAckV1`: explicitly scoped to `gateway_admission`; it cannot claim
  physical motion or stillness.

The JSON payload is one bounded (`16 KiB`) Unix `SOCK_SEQPACKET` message.
Decoding rejects duplicate/unknown fields, unknown major versions, bool-as-int,
non-finite velocity values, out-of-range packet/string/integer/TTL fields, wrong
frame, and malformed SHA-256 identities. No client absolute monotonic deadline
exists on the wire. Velocity values are finite-only: N24 does not admit their
magnitude against a capability or safety envelope.

### 3. Fake Sport and gateway failure substrate

`FakeSportServiceV1` deterministically models delayed `Move`, a Move that
applies and never replies, late completion, stale/out-of-order state, lease
loss, second-writer conflict, and failed `StopMove`. The test-only Python
gateway owns one boot epoch/writer, a per-boot replay high-water mark, local
deadline, state freshness/order fence, and stop epoch.

A Move completing after a stop epoch is followed by a compensating
`StopMove`; a later compensation cannot clear an existing latch. A failed
`StopMove`, or a successful call without a fresh later stationary fake-state
sequence, stays unconfirmed and latched.

The fake event sink is a bounded best-effort observer, not a causal recorder.
Stop effects occur before observation and neither a blocked nor raising sink
can delay, throw through, or change stop/disarm. Shutdown drains evidence only
for a bounded interval; a drain failure, sink error, or dropped event makes the
fake process exit nonzero. N42 still owns the durable shared recorder.

### 4. Real subprocess death/restart evidence

`tests/test_gateway_process.py` starts a standalone fake gateway process and a
separate client process. The client acquires the current epoch and submits
`vx=0.2 m/s`; the test observes fake `move_applied`, sends the client
`SIGKILL` (so no client `close`/`finally` can stop), and leaves the gateway
alive. The surviving gateway observes socket EOF, calls local `StopMove`, and
records fresh later stationary fake feedback. A new observer sees exact zero
and `DISARMED`, and a captured same-boot sequence cannot re-acquire.

The gateway is then stopped and started as a new process. The second process
mints a different boot epoch, starts `DISARMED`, refuses an acquire carrying
the first epoch, and remains disarmed. No restart state or command is loaded.

### 5. Frozen N24 invariants and seeds

`gateway_invariants_v1.json` freezes 12 gateway invariants and explicitly
records `owner=N24`, `evaluator_owner=N42`. `gateway_fault_seeds_v1.json`
freezes 19 uniquely numbered negative fixtures (`GWF-001`–`GWF-019`), including
a distinct valid-duration/receiver-local-expiry seed. The loader rejects
schema/ownership drift, duplicate IDs/seeds, unknown fixture
references, and unseeded invariants.

This is an inventory, not the shared CI evaluator. No
`authority-invariants` tier, seam-diff evaluator, or mutation score was added.

## Executed evidence

| Evidence | Result |
| --- | --- |
| Focused DTO/timing/inventory, fake-fault, and process suite | `41 passed in 0.47s` |
| Focused stability loop | `30/30` clean runs; `1,230` test executions |
| Existing control + W0-B + no-arm plus reference design-spike regressions | `394 passed in 25.69s`; design spike is reference-only |
| Ruff check and format check on N24 source/tests | pass |
| Static bytecode compilation | pass |
| Non-slow static collection | `5435/5471` collected; `36 deselected`; three existing deprecation warnings |
| Full commit gate | not run; concurrent non-N24 work made a whole-tree result unattributable to this slice |
| `git diff --check` | pass |

The focused suite includes direct rejection coverage for version/packet/string/
integer/TTL bounds, finite velocity values, frame/hash, first-command admission,
local TTL expiry, delayed and no-reply Move, stale and out-of-order fake state,
lease loss, duplicate/per-boot replay, writer conflict, StopMove failure,
compensation after a late Move, and the real subprocess SIGKILL/restart sequence.
It also proves raising, blocked, and capacity-full best-effort observers cannot
alter stop/disarm, while any sink error, bounded drain failure, or dropped
evidence makes the fake evidence process nonzero.

## Remaining W0-C / N28 gates

N24 intentionally leaves all completion work to N28/N29/B16:

- native C++/Rust process and production launcher/service lifecycle;
- peer credential checks, least-privilege identities, bounded backpressure,
  production socket ownership/permissions, and credential rotation;
- an authenticated, recoverable lease/session sequence contract and controlled
  writer handover; N24's process-local per-boot high-water mark is only a fake
  replay fence, not the final product session schema;
- the sole real Unitree DDS/vendor writer and exclusion of the app, remote,
  rogue DDS participant, legacy ROS JSON, debug Dog, UI, and Python paths;
- verified Unitree API/firmware/service compatibility and real lease behavior;
- N29-generated schemas/validators, signed release/capability manifest, and one
  immutable safety-envelope identity, plus N28 velocity magnitude/capability
  admission enforced by the native product path rather than this fake;
- complete `Acquire/Heartbeat/Release`, capability-admitting launch, action/
  posture/gesture lifecycle, cancellation, and command/action conflict;
- unknown-mode, malformed/oversized IPC, and local-clock discontinuity
  campaigns under the native decoder/clock owner, including non-finite or
  backward monotonic readings and suspend/resume; process freeze/OOM/NIC/
  discovery faults; and fake send-success/no-motion detection;
- physical post-stop feedback semantics, scheduling tails, stop distance,
  balance, and commissioning evidence (B16).

The Python seqpacket server is a deterministic process/fault substrate. It is
not promoted into `RobotRuntime`, `control.factory`, commissioning, or a
physical profile.

## Remaining W0-F / N42 gates

N42 still owns:

- assembly of the shared hard `authority-invariants` commit-tier gate;
- evaluator nonzero behavior and reproducible run manifests;
- automatic authority-seam coverage checks;
- the accepted mutation campaign and its honest class/kill count;
- integration of provenance, B5 reserve, B6 bearing relevance, monotone
  disposition, and later gateway/product seams into one evaluator;
- hosted CI execution evidence (separately B20).

## B5–B8 boundary

No B5–B8 policy was chosen or implemented:

- no arrival-reserve rule or frozen-row rebaseline (B5);
- no collision-brake directional/closing rule (B6);
- no HOLD/sensing-rotation axis matrix (B7);
- no no-provider pose fallback change (B8).

Their accepted fixtures may later join N42's shared evaluator only after the
named owner decisions. Nothing in this slice authorizes positive product
motion while those promotion gates remain open.

## Does not prove

This slice does **not** prove a complete native gateway, product authority,
peer isolation, real DDS sole-writer exclusivity, vendor compatibility, HIL,
physical stop initiation/settling/distance, scheduling p99, robot balance,
velocity-envelope enforcement, action feasibility, first-ODD readiness, B5–B8
semantics, or the W0-F shared CI/mutation gate. All stationary claims in these
tests are explicitly `FakeSportStateV1` evidence, never physical evidence.

## Final validation

The following commands were executed on 2026-08-16 against base commit
`8473a5159bab` plus the preserved concurrent dirty worktree. No inherited
baseline count is promoted as N24 evidence.

```text
.parcel/bin/python -m pytest -q -p no:cacheprovider \
  tests/test_gateway_protocol_v1.py \
  tests/test_fake_sport_gateway.py \
  tests/test_gateway_process.py
# 41 passed in 0.47s

# The same focused command, repeated in a shell loop 30 times:
# 30/30 clean runs; 1,230/1,230 test executions passed

.parcel/bin/python -m pytest -q -p no:cacheprovider \
  tests/test_control.py \
  tests/test_w0b_commissioning.py \
  tests/test_no_arm_pin.py \
  scrum/20260812/task_1/design_spike/test_contracts.py
# 394 passed in 25.69s

.parcel/bin/ruff check src/parcel_robot/bridge \
  tests/test_gateway_protocol_v1.py \
  tests/test_fake_sport_gateway.py \
  tests/test_gateway_process.py
# All checks passed

.parcel/bin/ruff format --check src/parcel_robot/bridge \
  tests/test_gateway_protocol_v1.py \
  tests/test_fake_sport_gateway.py \
  tests/test_gateway_process.py
# All files already formatted

.parcel/bin/python -m compileall -q src/parcel_robot/bridge
# pass

MUJOCO_GL=egl .parcel/bin/python -m pytest --collect-only -q \
  -p no:cacheprovider -m 'not slow'
# 5435/5471 tests collected (36 deselected) in 1.27s; 3 warnings

git diff --check
# pass
```

The complete commit tier was not run or claimed: N27 and other work were
actively changing maps, configuration, fixtures, and runtime assets in the
shared worktree. The focused suite, adjacent authority regressions, and static
collection above are the attributable N24 evidence.
