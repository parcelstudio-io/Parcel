# SOS-1 post-evidence maintenance 3: lifecycle-oracle repair

Written after independent review of maintenance-2, before modifying the SOS-1
runner/verifier or executing maintenance-3 on 2026-08-30. Maintenance-2 is
retained as evidence that the product READY/signal race was repaired, but its
single instantaneous `process.poll()` sample is not a sound process-lifecycle
oracle.

## Oracle repair

- For SIGINT and SIGTERM, wait up to the existing bounded timeout for the
  supervisor to exit, then require exit code zero and an already-latched,
  exact-zero, stationary gateway state. Do not require exit at the exact
  instant the fake gateway first exposes its latch.
- For SIGUSR1, drain pre-signal notifier traffic, require the gateway latch,
  require the child to remain alive for a bounded dwell, and require a fresh
  post-signal watchdog pulse before sending SIGTERM for clean teardown.
- Retain the legacy `kept_running_after_signal` field for result compatibility,
  but derive it from the bounded oracle above.

## Strict-verifier repair

The maintenance-3 verifier must additionally validate manifest schema/study,
the exact frozen path set, result schema/study, unique cohort labels, and the
256-case count. For a resealed malicious result, it must prove that the digest
is valid but the claimed gates disagree and recomputed SOS-H2 is specifically
false; a pre-existing red baseline cannot satisfy this test accidentally.

## Frozen execution and decision rule

After implementing the oracle and verifier changes, freeze the complete
maintenance-3 surface in a new manifest. Run two complete suites concurrently
and two sequentially. All four must pass H1-H5, produce one identical
normalized digest, match the manifest, and pass the strengthened independent
verifier. Retain every output regardless of result.

The narrow maintenance-3 verdict passes only if
`maintenance_3_strict_verification.json.pass` is true. Its evidence ceiling is
still desktop source/fake-gateway behavior; it does not authorize physical
motion or prove independent hardware STOP, real braking, balance, mounted
timing, GPIO/remote/audio adapters, or Unitree firmware behavior.
