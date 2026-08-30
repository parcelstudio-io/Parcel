# DSOAK-1 — 12.05-hour duplex durability soak

**Final status:** `SUPPORTED_PROCEDURAL_SOAK`
**Evidence class:** desktop procedural semantic stream; no physics, audio,
hardware, or motion
**Physical-motion implication:** none

The final artifact self-reports 43,380.014 monotonic seconds (12.050004 hours)
from 2026-08-29 20:05:40 UTC through 2026-08-30 08:08:40 UTC. A post-run
aggregate-consistency verifier recomputed all 17 declared gate predicates as
true from the retained counters, and a 32-case mutation campaign verified that
the result and continuity verifiers reject their exercised corruptions. The
unsigned late-start monitor partially corroborates the run; this is not strict
temporal provenance or proof against coherent post-hoc artifact replacement.

This is durability evidence for the frozen DMC-1 procedural program only. It
does not repair DMC-1's independently refuted receipt/narration oracle, promote
the learned A1 policy over the stronger deterministic L0 baseline, or establish
perception, acoustics, social safety, dynamics, stopping, Orin performance, or
mount readiness.

## Files

- [`DESIGN.md`](DESIGN.md) — frozen question, procedure, gates, and scope.
- [`POSTSTART_NOTE.md`](POSTSTART_NOTE.md) — post-start oracle-validity limit.
- [`results.json`](results.json) — final atomic runner checkpoint.
- [`external-monitor.jsonl`](external-monitor.jsonl) — late-start independent
  observer log; it covers 80.377% of final elapsed time, not the full run.
- [`verification.json`](verification.json) and
  [`monitor-verification.json`](monitor-verification.json) — independent
  result and monitor reports.
- [`final-verification.json`](final-verification.json) — combined fail-closed
  acceptance.
- [`verifier-mutation.json`](verifier-mutation.json) — 32-case verifier
  mutation result.
- [`INTERPRETATION.json`](INTERPRETATION.json) — machine-readable scope that
  prevents legacy `promotion_pass` and narration-gate fields from being read as
  model promotion or semantic-truth evidence. The frozen result files are not
  rewritten post hoc.
- [`SUPPLEMENTAL_PROVENANCE.md`](SUPPLEMENTAL_PROVENANCE.md) — clearly post-hoc
  surviving-host metadata; not a launch attestation.
- [`RESULTS.md`](RESULTS.md) — exact measurements and provenance.
- [`VERDICT.md`](VERDICT.md) — controlling interpretation.

## Reproduce the verification

From this directory, return to the repository root and use the project
environment:

```bash
cd ../../..
.parcel/bin/python research/20260829/duplex-soak-1/verify_results.py
.parcel/bin/python research/20260829/duplex-soak-1/verify_monitor.py
.parcel/bin/python research/20260829/duplex-soak-1/verify_final.py
.parcel/bin/python research/20260829/duplex-soak-1/verify_verifiers.py --out /path/to/scratch-verifier-mutation.json
```

The first three commands must exit zero and the mutation command must report
`all_expectations_met: true`. The retained output hashes are listed in
[`RESULTS.md`](RESULTS.md). The runner's own exit code is not an acceptance
oracle; use `verify_final.py`.
