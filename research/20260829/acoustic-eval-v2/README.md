# Acoustic evaluator validity rerun

This retained Tier-1 run repairs the measurement-validity defects found in
`acoustic_loop_v1`; it does not turn virtual audio into hardware evidence.

- [Design](DESIGN.md)
- [Results](RESULTS.md)
- [Verdict](VERDICT.md)
- [Machine report](results.json)
- [Independent verification record](verification.json)

Outcome: **expected red** — 6 gates passed, 3 failed, and 2 required physical
or isolated-channel measurements remain `not_measured`. Teardown was clean.
