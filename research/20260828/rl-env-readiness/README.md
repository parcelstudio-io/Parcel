# RL environment readiness artifact

This directory contains the preregistered `RL-ENV-READINESS-1` audit of the
current `parcel_robot.rl.env.Go2Env`.

- `DESIGN.md` — question, frozen source digests, protocol, and gates written
  before execution.
- `experiment.py` — bounded offline-stub and tracked-MJCF audit; no socket,
  viewer, training, or physical control.
- `results-run1.json`, `results-run2.json` — byte-identical raw records.
- `verify_results.py`, `verification.json` — independent gate and artifact
  recomputation (14/14 integrity checks pass).
- `RESULTS.md` — exact measurements and reproduction log.
- `VERDICT.md` — independent readiness decision and repair order.

Headline: **2/9 gates pass; `H-RL-READY` is REFUTED.** This is local simulator
contract evidence only.

