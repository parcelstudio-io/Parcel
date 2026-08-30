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
- `MAINTENANCE_RESULTS.md` — current-source race discovery, repair, and reruns;
- `MAINTENANCE_VERDICT.md` — current narrow decision and evidence ceiling;
- `manifest.prerun.json` — pre-run source/config hashes;
- `run_a.json` and `run_b.json` — independent repeated results; and
- `verification.json` — independent recomputation and tamper result.

The two original frozen runs passed, but later concurrent maintenance exposed
a real READY-before-signal-handler startup race and a false-positive defect in
the historical verifier. Both defects were repaired without overwriting the
red artifacts. The final maintenance-3 parallel and sequential cohorts all
pass with normalized digest
`7d1dc20402c6f0922f68625b28c9f0e83cf3c46788ea1471f7bba421a9cf529d`;
the strengthened verifier reports `pass:true`. The physical-readiness field
remains deliberately false.

Reproduce from the repository root with the pinned Parcel environment:

```bash
.parcel/bin/python research/20260829/stop-only-safety-1/run.py \
  --manifest research/20260829/stop-only-safety-1/manifest.prerun.json \
  --output /tmp/sos1.json --run-label replay
```

Do not regenerate any retained manifest. `manifest.prerun.json` binds the
original runs; `maintenance_3_manifest.json` binds the current post-fix
lifecycle-oracle reruns.
