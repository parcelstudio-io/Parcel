# C0 independent remediation: mutation-panel coverage repair

Written on 2026-08-30 after the independent current-checkout failure and
coverage scans, before changing the panel or regenerating its gated artifact.

## Observed red

The guarded current-checkout suite reports 2 failed / 9 passed. The committed
artifact is stale in the green direction (agreement 4 / authority disagreement
1 versus live agreement 5), and `reactive_gate_disabled` survives because the
five selected episodes no longer observe a consequential gate intervention.

A guarded scan found:

- among the checked-in 25-row v4 minival, only
  `nav-region_goal-A-00-1c735162` changes a nonzero command (21/101 calls,
  slowing only); its 2.6 mm outcome delta is below the existing 0.10 m paired
  trajectory tolerance;
- across the deterministic 125-row v4 matrix (seed 20260804, digest
  `e7c302ddf19a39646aff77f01832be56b14fae6c7d4bd28e39cd5045c3c8b3f2`),
  seven rows intervene, none by full zeroing; and
- four additional rows are clean agreement/zero-collision candidates:
  `nav-region_goal-C-11-25d4e602` (88/200),
  `nav-region_goal-D-17-448696db` (17/110),
  `nav-object_goal-D-18-19a95961` (14/184), and
  `nav-object_relative-C-11-3bf174e9` (31/165). The two remaining intervening
  rows are excluded because the clean run is already authority-red.

## Frozen repair decision

1. Preserve the existing five rows so coverage for the other six mutations
   cannot silently disappear.
2. Add the four clean rows above from the pinned full v4 matrix. The expansion
   is coverage selection, not robot-parameter tuning; no safety threshold,
   planner, scorer, or control path changes.
3. Bind the generator seed and full-matrix digest in code and artifact.
4. Add an explicit clean coverage witness counting calls where the reactive
   gate alters a nonzero requested command. `reactive_gate_exercised` is an
   undisableable clean safety check. This prevents an outcome tolerance from
   turning an unexercised safety mutation into green evidence.
5. Re-run all seven mutations. Require every clean absolute check green, no
   survivors/equivalents, `reactive_gate_disabled` killed, the declared
   `no_authority_disagreement` disable removed, and all freshness tests green
   on the current checkout.

The intervention count is a structural coverage witness, not evidence that the
reactive policy is human-safe or physically sufficient. Physical motion remains
NO-GO.
