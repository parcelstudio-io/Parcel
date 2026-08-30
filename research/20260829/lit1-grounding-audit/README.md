# LIT-1 grounding audit

This is an independent post-hoc adversarial audit of the five retained LIT-1
`door_sofa_keys` fake-voice traces. It was created after the traces existed and is
therefore a refutation probe, not a preregistered capability experiment.

`verify.py` is standard-library-only. It checks the manifest's source hashes, then
compares each scripted terminal arrival statement with the preceding executive
receipt and independent arrival-authority row. It does not import the LIT-1 harness
or its scorer.

Run from the repository root:

```bash
.parcel/bin/python research/20260829/lit1-grounding-audit/verify.py
```

