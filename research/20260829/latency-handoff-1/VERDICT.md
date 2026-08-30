# LHO-1 verdict

**Decision: `LHO1_MECHANISM_PASS_FRESH_PROCESS_SUPPLEMENTED`**

The latency-sized committed-prefix/revisable-tail mechanism met all five
pre-registered gates in two reproducible full runs. It materially reduced
planner-induced stop-and-go in the authored scalar scheduling simulator while
preserving revision, STOP, occupied-prefix, queue-bound, and trace-integrity
requirements.

The original verifier proves two normalized-identical retained inputs but does
not enforce that they came from distinct OS processes. This post-evidence audit
finding does not change H1–H4. The separately frozen
[fresh-process supplement](FRESH_PROCESS_RESULTS.md) observed two additional
full runs as distinct, sequential, non-overlapping Linux child processes,
reverified H1–H4, linked A/B/C/D to one digest, and passed ten provenance-tamper
checks. That local-host evidence closes the registered H5 gap; it is not remote
attestation.

Adopt the mechanism as a **candidate transaction design** for the disarmed
runtime and higher-fidelity simulators. Do not interpret this verdict as a
trained Model A result or a physical readiness result.

## Promotion gate

It may advance from authored simulation only after the same invariants pass
with:

1. measured p50/p95/p99 perception-to-command latency on the intended AGX
   Orin deployment;
2. an independent 2-D/3-D swept-volume and uncertainty-aware corridor oracle;
3. separately commissioned Go2 braking envelopes across speed, surface,
   payload, slope, and stale-sensor conditions;
4. real STOP/E-stop and obstacle-invalidation timing at the hardware boundary;
5. revision, timeout, packet-loss, clock-jump, and process-restart fault
   injection; and
6. motors-disabled replay, then tethered low-speed trials under an independent
   operator and physical emergency stop.

Until those gates pass, physical autonomous motion remains **NO-GO**.
