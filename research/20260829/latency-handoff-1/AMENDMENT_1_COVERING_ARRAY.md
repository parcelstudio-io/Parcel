# LHO-1 pre-implementation amendment 1: finite covering array

Date frozen: 2026-08-29  
Timing: before policy/evaluator implementation and before any test result  
Reason: `DESIGN.md` lists factor coverage but did not state whether it requires
the full Cartesian product. This amendment removes that ambiguity before code.

The evidence manifest uses a deterministic balanced covering array, not the
full Cartesian product:

- ordinary revision: 12 families × 5 seeds × 9 deciles = 540 schedules;
- emergency STOP: the same 540 family/seed/decile cells;
- occupied-prefix invalidation: the same 540 cells;
- no-revision controls: 12 families × 5 seeds × 6 base-latency levels = 360
  schedules;
- total: 1,980 paired schedules and 5,940 arm episodes.

Within each 540-cell block, the six latency levels and five estimator-error
levels are assigned by a deterministic modular Latin schedule, so every
family, seed, decile, latency, and error level appears in each event mode and
all latency × error pairs recur. Controls enumerate all latency levels and
rotate the five estimator-error levels evenly. Every schedule is paired across
B0/F0/G0 with exactly the same exogenous values.

All hypothesis bars and non-claims remain unchanged. Results must report this
covering-array design and may not describe it as a full factorial. The manifest
generator and coverage verifier are frozen and hashed before either evidence
run.
