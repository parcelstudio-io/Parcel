# SOS-1 results

## Outcome

SOS-H1 through SOS-H5 passed in two fresh evidentiary runs. Their volatile run
labels differ, but their normalized contents are exactly equal with digest
`dbba4218141da09ab5fbc1587644a58dd52bbfc4dc0458362b11f5a1f581dc9e`.
The historical verifier recomputed every gate and source hash, but later audit
found that its final predicate checked agreement with a stored false gate
claim without separately requiring the recomputed gates to be true. The two
original runs were themselves green, so their outcome is unchanged; current
maintenance evidence and the corrected verification are documented in
`MAINTENANCE_RESULTS.md`.

| Gate | Run A | Run B | Evidence |
|---|---:|---:|---|
| SOS-H1 credential separation | PASS | PASS | 256/256 stop-UID acquire refusals, 256/256 stop-UID command refusals, 256/256 runtime acquires, 256/256 runtime refreshes |
| SOS-H2 stop dominance | PASS | PASS | 256/256 stops reached; 256/256 latched, lease-invalidated, exact-zero, stationary-confirmed |
| SOS-H3 API non-authority | PASS | PASS | no public acquire/command/arbitrary request/raw send/clear; no Unitree, gateway-core, port, or fake-vendor import |
| SOS-H4 lifecycle | PASS | PASS | healthy startup caused no stop; SIGUSR1 latched and stayed running; SIGINT/SIGTERM latched before clean exit; gateway loss withheld watchdog credit and exited nonzero when STOP could not be confirmed |
| SOS-H5 composition | PASS | PASS | console entry point, units, distinct UIDs, shared `parcel-motion` group/socket, and network-free safety sandbox agree |

The broader guarded gateway regression was also green: **273 passed, 4
skipped in 25.44 seconds**, with the historical ten-minute test deliberately
bounded to five seconds by `PARCEL_M1_0_SOAK_S=5` for this change gate. The
focused safety/credential suite was **27 passed**.

## What changed

- `gateway/credentials.py` now distinguishes UIDs admitted to connect/read/STOP
  from the strict subset eligible for a lease. The historical one-UID builder
  retains its original behavior.
- `gateway/core.py` uses the lease-specific UID predicate for acquire and
  refresh. STOP remains unconditional and monotone.
- `gateway/seam/cli.py` requires a distinct stop-only UID/user in physical
  vendor mode and binds it into the policy.
- `src/parcel_robot/bridge/stop_only_gateway.py` supplies a pure-stdlib client
  whose public surface is connect/reconnect/close, state, and latched STOP.
- `src/parcel_robot/safety_supervisor.py` supplies the real `parcel-safety`
  entry point, earned readiness/watchdog signaling, stale/inconsistent-state
  stop logic, and SIGUSR1/SIGINT/SIGTERM handling.
- The gateway, runtime, and safety units share only the `parcel-motion` Unix
  socket group. Kernel UID remains the authority identity. The safety unit has
  a private network namespace, AF_UNIX-only address family, and IP deny rule.

## Evidence integrity

- Frozen design SHA-256:
  `0c8d3301e956eab1475a4bb578afe7055a769e99824883d1f89fe2e2981cd9cb`
- Pre-run manifest SHA-256:
  `b1c9441023a9b733ecc88ea7c1efef9fd30f1e280f62ecbbfc318be91f59a9f7`
- Run A / Run B file SHA-256:
  `a82dc24c2ef47ba0f003a078271743c10149d7a7246ecde26ed531fb17f905b0` /
  `fe089507a5e29e7233c8762b0306d39a28554dddc1ec2cef661ea58f20b5c57a`
- Verification SHA-256:
  `6273dab4e49a1e4568e22afe8631b9b42196c5160b7b2cfcc198dbb14b1acebb`

## What this did not test

No Orin, Unitree, remote, GPIO, microphone, lidar, physical pedestrian,
firmware watchdog, or hardware E-stop was present. Fake feedback confirms the
software transaction only. If the gateway, Orin, Python scheduler, Unix socket,
power rail, or Unitree transport fails together, this process cannot guarantee
a stop. It also does not measure braking distance, balance, foot contact,
thermal limits, or human-safe clearance.

## Current-source correction

Do not use this historical section as the current-source lifecycle claim.
Concurrent maintenance later exposed and repaired READY-before-handler
ordering, then replaced the instantaneous process-state oracle. See
`MAINTENANCE_RESULTS.md` and `MAINTENANCE_VERDICT.md` for the preserved red
evidence and final four-run post-fix result.
