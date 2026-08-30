# SOS-1 — independent stop-only safety principal

This study implements and evaluates a second operating-system principal at the
Parcel motion gateway. `parcel-runtime` remains the sole UID permitted to
acquire or refresh motion. `parcel-safety` may read gateway state and request
an unconditional latched emergency STOP, but the gateway refuses that UID any
positive motion authority.

Start with:

- `DESIGN.md` — frozen hypotheses, scope, and gates;
- `RESULTS.md` — exact evidence and implementation pointers;
- `VERDICT.md` — adoption decision and remaining blockers;
- `manifest.prerun.json` — pre-run source/config hashes;
- `run_a.json` and `run_b.json` — independent repeated results; and
- `verification.json` — independent recomputation and tamper result.

All functional software gates passed twice. The normalized result digest is
`dbba4218141da09ab5fbc1587644a58dd52bbfc4dc0458362b11f5a1f581dc9e`.
The physical readiness field is deliberately false.

Reproduce from the repository root with the pinned Parcel environment:

```bash
.parcel/bin/python research/20260829/stop-only-safety-1/run.py \
  --manifest research/20260829/stop-only-safety-1/manifest.prerun.json \
  --output /tmp/sos1.json --run-label replay
```

Do not regenerate `manifest.prerun.json`: it is the frozen binding for the two
retained evidentiary runs.

