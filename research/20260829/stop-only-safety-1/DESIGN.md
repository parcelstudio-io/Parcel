# SOS-1 — independent stop-only safety principal

Frozen before implementation or evidentiary execution on 2026-08-29.

## Question

Can the existing sole-writer gateway admit a second operating-system principal
which can observe and latch STOP, but which cannot acquire a motion lease,
refresh a command, clear a latch, import the Unitree SDK, or manufacture a
positive motion claim?

This closes one software process-boundary gap. It does **not** test a physical
E-stop, stopping distance, balance, GPIO, Unitree firmware behavior, DDS
identity, AGX timing, or hardware sensor health. A pass cannot authorize
physical motion.

## Threat model and invariants

- `parcel-runtime` remains the only UID eligible to acquire or refresh the one
  gateway lease.
- `parcel-safety` is a distinct UID admitted only for read-only state and
  unconditional, latched STOP.
- Filesystem socket reachability is a shared `parcel-motion` group; kernel
  `SO_PEERCRED` UID, not group membership or a caller-supplied field, assigns
  authority.
- The safety client API must contain no `acquire`, `command`, arbitrary
  `request`, raw send, vendor object, or latch-clear method.
- A safety STOP is always emergency/latched and does not depend on the current
  lease holder, client sequence, model, network, disk, or dialogue process.
- Gateway loss cannot be called safe: the supervisor withholds systemd
  watchdog credit and reports the failure, while the gateway's own watchdog
  and a required physical E-stop remain separate layers.
- Startup/restart is disarmed but does not itself latch the gateway. `SIGUSR1`
  requests STOP; `SIGINT`/`SIGTERM` request STOP before shutdown.

## Implementation slice

1. Split gateway credential admission into connection/STOP admission and the
   strict subset eligible for leases. Preserve the existing one-UID policy as
   the backward-compatible default.
2. Add a product-owned, pure-stdlib `StopOnlyGatewayClientV1` with only
   connect/reconnect/close, read-only state, and latched emergency STOP.
3. Add the installable `parcel-safety` console process. It earns readiness and
   watchdog messages from successful gateway probes, never auto-arms, and
   accepts only local OS signals in this slice.
4. Update the two systemd units to use a dedicated `parcel-motion` socket
   group, name the separate stop UID, and start the actual executable.
5. Keep GPIO/serial remote and local audio STOP adapters as explicit box-day
   work; this experiment proves the process/authority seam, not those inputs.

## Preregistered gates

All gates must pass twice on the desktop fake gateway, plus targeted static
tests. Any exception/rejection that results in positive authority is a hard
failure.

| Gate | Required result |
|---|---|
| SOS-H1 credential separation | At least 256 safety-UID acquire/command attempts are refused; at least 256 runtime-UID acquire/refresh transactions are admitted under valid inputs. |
| SOS-H2 stop dominance | At least 256 safety-UID STOP requests reach the gateway stop path, latch it, produce exact-zero/stationary fake feedback, and invalidate the runtime lease. |
| SOS-H3 API non-authority | Static public-surface/import inspection finds no acquire, command, arbitrary/raw transport, Unitree/gateway-core/vendor import, or clear-latch capability. |
| SOS-H4 lifecycle | Fresh starts do not arm or stop; `SIGUSR1`, `SIGTERM`, and `SIGINT` each request latched STOP before exit; gateway/probe failure withholds watchdog credit. |
| SOS-H5 composition | Source wheel exposes `parcel-safety`; both unit files parse; UID roles and shared `parcel-motion` socket group agree; gateway remains the sole vendor writer. |
| SOS-H6 reproducibility | Two same-seed results are exactly equal after volatile metadata removal; a stdlib verifier recomputes gates and source/config hashes; one in-memory tamper is rejected. |

## Interpretation

- **PASS** means the repository has a tested independent *software* stop-only
  principal and deployable process skeleton.
- **FAIL** preserves the independent-safety gap.
- Either result leaves physical readiness **NO-GO** until the real remote/GPIO
  input, hardware E-stop, Orin image, Unitree feedback, stopping distance, and
  fault-injection tests pass on the commissioned robot.

