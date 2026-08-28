# 2026-08-26 — generalized companion autonomy and Go2 readiness

This research day reviewed the current prototype and Claude's committed motion
seam, implemented the continuing-companion prompt, reran conversation and
navigation quality evidence, tested three architecture families, designed a
governed simulator-learning loop, and issued a physical mount decision.

A subsequent P0 `SIM-CONTRACT-1` implementation tranche turned the highest-risk
interfaces into default-off/fail-closed product seams. It did **not** enable a
physical robot, a native Unitree SDK2/DDS writer, cloud sync, or automatic model
activation. See `IMPLEMENTATION_REPORT.md` for the exact implementation ceiling.

## Decision

**Motion-enabled mount: NO-GO.**
**Stationary, secured, supervised Stage 0: conditional and unexecuted.**
**Simulation investment: strongly recommended, beginning at the real
SDK2/DDS/gateway contract.**

## Start here

- `FINAL_REPORT.md` — research synthesis, architecture, eval program, budget,
  and execution priorities.
- `IMPLEMENTATION_REPORT.md` — P0 code delivered after the research phase,
  trust boundaries, verification status, and remaining integration work.
- `MOUNT_READINESS.md` — exact physical promotion ladder and stop conditions.
- `system-readiness/` — preregistration, raw outputs, corrective iterations,
  remeasurement results, and verdict.
- `conversational-embodiment/` — capability envelope, dialogue state,
  proactive admission, and cognition-router hypotheses.
- `navigation-generalization/` — liveness and independent-completion
  hypotheses plus simulator ladder.
- `independent-completion/` — preregistered 360-case follow-up showing that an
  identity witness blocks map-alias false arrivals but misses the nominal
  recall gate; product integration remains rejected pending H2b.
- `independent-completion-h2b/` — implemented isolated H2b contract and the
  600-case, three-arm holdout; overall `REFUTED` at 113/120 alias recovery
  versus the preregistered 114/120 gate, so it remains default-disabled.
- `dynamic-social-progress/` — pedestrian disappearance/release, predictive
  occupancy, sidewalk/crosswalk/elevator semantics, and social-stall recovery.
- `research-data-plane/` — isolated summary-first spool/bundle/replay probe and
  long-term data architecture, plus the default-off local implementation seam.

The user-linked Claude artifact returned `Page not found` on 2026-08-26. Only
the committed repository work was reviewable.
