# SOS-1 current-source maintenance results

## Outcome

Current source passes the narrow desktop fake-gateway gate after repairing a
real startup race and two evaluator defects. All historical and red evidence
was retained.

| Cohort | Schedule | Result | Normalized digest | Interpretation |
|---|---|---:|---|---|
| Original A/B | sequential | PASS/PASS | `dbba4218141da09ab5fbc1587644a58dd52bbfc4dc0458362b11f5a1f581dc9e` | Historical frozen source only |
| Maintenance-1 A/B | concurrent | FAIL/FAIL | `0fc7c7154319718cb36a55fb81ef6562c29c20a33ee884747f38e63e791bfe69` | H4 exposed READY-before-handler race |
| Maintenance-1 C/D | sequential | PASS/PASS | `243eef62f1e0a9fb77a1d6e59a26f34e1d7360dc11d45dcc7fcefca5af0c75ae` | Scheduling-sensitive control; did not clear the defect |
| Maintenance-2 A/B/C/D | concurrent + sequential | PASS/PASS/PASS/PASS | `7232bded12417c19f418f745dad636d87b808b6b47e74537f86b384f28b8b96c` | Product ordering repair passed; immediate-poll oracle remained weak |
| Maintenance-3 A/B/C/D | concurrent + sequential | PASS/PASS/PASS/PASS | `7d1dc20402c6f0922f68625b28c9f0e83cf3c46788ea1471f7bba421a9cf529d` | Controlling current-source result with repaired lifecycle oracle |

## What failed and what changed

The supervisor previously sent `READY=1` before installing SIGUSR1, SIGINT,
and SIGTERM handlers. A service manager could therefore signal a process that
advertised readiness but still had default signal dispositions. In both
maintenance-1 parallel runs, SIGTERM exited without a confirmed gateway latch;
the later exact-zero state came from lease expiry and was not STOP proof.

`src/parcel_robot/safety_supervisor.py` now installs all three handlers before
the gateway connection loop and before readiness. A source-order regression
test protects this invariant.

The historical verifier also returned `pass:true` for the two red parallel
runs because it required only that the stored false aggregate agreed with the
recomputed false aggregate. `verify_maintenance_strict.py` explicitly requires
every recomputed gate to be true.

Independent review then found an instantaneous `process.poll()` lifecycle
oracle. Maintenance-3 replaces it with bounded clean exit for SIGINT/SIGTERM
and, for SIGUSR1, a complete liveness dwell plus a fresh post-latch watchdog
pulse. The strict verifier now checks the exact 19-file manifest, schemas,
study IDs, labels, 256-case count, all four normalized digests, current hashes,
and two tamper modes.

## Final maintenance-3 evidence

- Manifest SHA-256:
  `50a891fba65fabf0006dd31f52ecb5feef95755d49d22c2c0ea2d1c413d9a460`
- Four-run normalized digest:
  `7d1dc20402c6f0922f68625b28c9f0e83cf3c46788ea1471f7bba421a9cf529d`
- Strict verification SHA-256:
  `0f733e44a9af8edf2b6541b07b15ffdab74d85ba945d5f38ab445cd19ac6dc48`
- H1-H5: all true in all four runs.
- Parallel and sequential repeatability: true.
- Manifest structure, current source hashes, result structure, and unique
  labels: true.
- Stale-digest tamper rejection: true.
- Resealed malicious claim: digest accepted, gate disagreement detected, and
  recomputed H2 false; rejection true.
- Focused product regression: 8 passed.

The maintenance-1 strict output remains red (`pass:false`), as required. The
historical false-positive `maintenance_verification.json` is retained to make
the verifier defect auditable.

## Evidence ceiling

These executions use a desktop process, Unix socket, and fake Unitree service.
They do not measure a hardware E-stop, remote/GPIO/audio STOP adapter, Orin
scheduler or thermal behavior, Unitree firmware, DDS failure, balance, terrain,
or stopping distance. They prove neither hard real-time delivery nor physical
independence.
