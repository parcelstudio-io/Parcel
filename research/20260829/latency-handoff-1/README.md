# LHO-1: latency-sized committed prefix and revisable tail

**Mechanism verdict:** `LHO1_MECHANISM_PASS_FRESH_PROCESS_SUPPLEMENTED`. H1–H4
pass in the original trace-first verifier. The separately frozen additive
[fresh-process supplement](FRESH_PROCESS_RESULTS.md) also passes and closes the
original H5 verifier's failure to enforce distinct OS-process identity.

LHO-1 tests one bounded scheduling mechanism: while a slow planning lane is
working, may the controller continue along an already validated, braking-safe
prefix, while keeping the remaining tail replaceable? The answer is **yes in
this deterministic scalar simulator**. It is not evidence that a learned model
can navigate, that perception is correct, or that the mechanism is physically
safe on a Go2.

## Evidence at a glance

- 1,980 frozen paired schedules across 12 route families and 5 seeds;
- 5,940 arm episodes per evidence run: blocking (`B0`), fixed 400 ms chunk
  (`F0`), and guarded latency-sized prefix (`G0`);
- ordinary revision, emergency STOP, predicted occupied-prefix, and
  no-revision controls;
- four full retained runs with the same normalized episode digest, including C
  and D observed live as distinct, sequential, non-overlapping child processes;
- an independent trace verifier that recomputes collision, boundary, wait,
  revision, STOP-timing, hypothesis, and integrity checks; and
- five original trace-integrity tamper checks plus ten fresh-process provenance
  tamper checks.

The complete numbers and interpretation are in [RESULTS.md](RESULTS.md), and
the decision boundary is in [VERDICT.md](VERDICT.md).

## Frozen protocol

The protocol was frozen in [DESIGN.md](DESIGN.md), then clarified before any
full-run evidence was opened:

1. [AMENDMENT_1_COVERING_ARRAY.md](AMENDMENT_1_COVERING_ARRAY.md) fixes the
   1,980-case balanced covering array.
2. [AMENDMENT_2_PRE_EVIDENCE_AUDIT.md](AMENDMENT_2_PRE_EVIDENCE_AUDIT.md)
   enforces causal prefix publication and independent collision/boundary
   oracles.
3. [AMENDMENT_3_FREEZE_READINESS.md](AMENDMENT_3_FREEZE_READINESS.md) makes a
   revised tail behaviorally distinct, separates occupancy prediction from
   contact truth, binds splice/exhaustion definitions, and makes timeout
   strict.

Those amendments record corrections found by independent pre-evidence source
audits. They are part of the frozen source manifest; they were not post-hoc
changes made after reading full-run metrics.

## Reproduce and verify

From the repository root, using the project environment:

```bash
.parcel/bin/python research/20260829/latency-handoff-1/run.py \
  --output research/20260829/latency-handoff-1/run_a.json
.parcel/bin/python research/20260829/latency-handoff-1/run.py \
  --output research/20260829/latency-handoff-1/run_b.json
.parcel/bin/python research/20260829/latency-handoff-1/verify_results.py \
  --run-a research/20260829/latency-handoff-1/run_a.json \
  --run-b research/20260829/latency-handoff-1/run_b.json \
  --output research/20260829/latency-handoff-1/verification.json
```

The original evidence files are [manifest.json](manifest.json),
[source-manifest.json](source-manifest.json), [run_a.json](run_a.json),
[run_b.json](run_b.json), and [verification.json](verification.json). The
additive process-provenance evidence and exact commands are listed in
[FRESH_PROCESS_RESULTS.md](FRESH_PROCESS_RESULTS.md).

## Production implication

Use `G0` as the architecture for a **committed safe prefix plus revisable
tail**, subject to all of the following:

- the prefix is created only from data and authority available before a plan
  revision;
- STOP and newly invalidated swept volume always cancel it on the next local
  control tick;
- its duration is bounded by measured end-to-end target latency, independently
  validated free corridor, and commissioned braking distance;
- only one request and one committed-prefix record may be live; and
- exhaustion is explicit and falls back to zero motion.

Before physical use, repeat the test with measured Orin timing, 2-D/3-D swept
volumes, actual localization and perception uncertainty, the Go2 velocity
interface, and instrumented braking trials under an independent hardware STOP.
