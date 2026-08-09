# WALK_WITH_ME_V1 (K8)

Frozen companion integration scenario pack: 10 walk-with-me scripts with
attribution hooks compatible with instructnav `FailureClass` /
`AttributionLayer`.

```bash
# Regenerate / validate freeze
.parcel/bin/python -m evals.walk_with_me.run_walk_with_me_v1 --write-freeze
.parcel/bin/python -m evals.walk_with_me.run_walk_with_me_v1 --validate-freeze-only

# CI-light smoke (2 stub episodes)
.parcel/bin/python -m evals.walk_with_me.run_walk_with_me_v1 --smoke

# Full stub pack
.parcel/bin/python -m evals.walk_with_me.run_walk_with_me_v1 --mode stub

# Optional headless (nav/spatial via HeadlessCityQualityHarness)
.parcel/bin/python -m evals.walk_with_me.run_walk_with_me_v1 --mode headless --max-steps 40
```

Freeze seed: `20260805`. Manifest: `evals/walk_with_me/freeze/manifest.json`.

See `does_not_prove` in the manifest for honest sim boundaries.
