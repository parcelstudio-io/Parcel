# DSOAK-1 post-start validity note

Written 2026-08-29 after the soak started and after independent Sol Ultra
review; it does not alter `DESIGN.md` or any gate.

The DMC-1 receipt ledger and narration validator accept malformed/out-of-order
receipts and mismatched terminal claims; see
`../duplex-mission-control-1/adversarial-review-results.json`. Consequently,
DSOAK-1's receipt/narration counters are retained as durability diagnostics of
the frozen program but cannot establish semantic truthfulness, even if their
predeclared gates stay green. The run remains useful for continuous-process
stability, deterministic replay, bounded-memory behavior, mission refuters,
and the ideal semantic admission-gate counters. Its final verdict will be
explicitly scoped and cannot repair DMC-1 H3/H4.
