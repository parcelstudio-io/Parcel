# Fable audit — SLAM_M_PLAN Wave 3 (RM-3), 2026-08-12

## Verdict: CONFIRMED — the measurement is honest, the pre-registered gate FAILED, and the failure's cause is now correctly attributed. This closes the plan.

**The scientific result stands: route memory, as wired, does not convert the
bottleneck — net paired flips 0 (needed ≥6), exact McNemar p = 1.000 (needed
≤ 0.031), SR 7/60 identical on both arms — and the reason is a pre-existing
product defect (backlog B6), not the route-memory mechanism, which measurably
worked** (42/60 episodes armed chains, 53 armings, 54 arbitration wins, 0
vetoes, 4,892 chain ticks driven; ON travelled 7.51 m vs OFF 5.04 m; 0 of the
armed episodes succeeded).

1. Fresh ci_gate at the revision-2 state: **PASS — 3943/0, 10/10 hard gates**
   (Fable's closing run recorded below; executor's 09:51 run agrees). Delta:
   3909 Wave-2 close + 34 RM-3 tests.
2. Adversarial protocol executed: 3 hunters + 2-refuter panels on every major
   (11 agents). The null result was attacked on six confound surfaces and
   held on all six — pre-drive parity proved with a bit-identical 1,213-tick
   per-tick trace across both arms; process isolation, matcher/budget/seed
   parity, success-set identity (the same 7 episode ids succeed on both arms,
   all with zero chain activity), 2×2 and exact p recomputed from rows; the
   pre-registered cell-set digest `a23c802b…` regenerated from the shipped
   generator with identical ids and order; the smallest budget re-derived
   (758 = 120 + ceil(19.13/0.03), 75× the 10-tick probe hold).
3. RETURN cycle: four majors upheld 8/8 — all against the status doc's causal
   NARRATIVE, none against a measured number. Revision 2 corrected all four
   with no sweep re-run and no artifact rewritten (mtimes preserved);
   `src/**` stayed byte-untouched throughout, as the measurement card
   requires.

## The four upheld corrections (now folded into RM3_STATUS rev 2)

- **Wedge mis-localization (the one that mattered):** revision 1 exonerated
  `apply_collision_brake` by feeding it the module-default policy
  (obstacle_stop_m = 0.60; its quoted "40.9 m/s" is the fingerprint —
  (0.80−0.60)/0.12/cos 1.53). Under the SHIPPING policy
  (`stop_distance_m: 0.8`, projected_speed_cap) the brake IS the zeroer: a
  static crate at exactly the stop radius, 88° off the travel axis, passes
  the any-positive-closing-fraction relevance gate and hard-stops the body —
  63 zeroed nonzero requests instrumented on the named cell. Reachable
  flag-OFF on the same cell (executed): a pre-existing product defect that
  route memory exposes at scale. The owner handoff was re-targeted from
  `grid_navigator.py` to the brake/config interaction → **backlog B6**.
- **"Permanent stall" overstatement struck:** the wedge is ~61 chain-live
  zero-vx ticks plus a bounded tail, and the arms are NOT identical on that
  cell — ON ended materially further from the goal (dtg 15.45 vs 9.86).
- **Trigger decomposition units:** honest numbers are 40 episodes
  trigger-(ii)-only, 2 with trigger-(i) activity (≤2 of 53 armings via (i));
  10 episodes re-armed via the watchdog — RM-2 F3's pinned-INTENDED behavior,
  now cross-referenced. The Wave-2 binding item (trigger (ii) measured) is
  closed, stronger than first stated. A new test pins the counter units.
- **Pilot-B membership disclosed:** the 6 pilot cells are cells 00–05 of the
  gated 60; only concordant outcomes were known pre-freeze (bias toward the
  null); excluding them leaves p = 1.000 — verdict unchanged.

Minor sweeps also closed: the stale "sighted" `set_provenance` string (fixed
in the generator; frozen artifacts deliberately not regenerated, digest
re-verified unchanged), the mid-session driver-schema drift (disclosed; the
audit reproduced the gated rows bit-identically with the shipped driver), and
the §1 freeze claim softened to what mtimes actually evidence.

## Report-only arms, audited

- **v4s LA/BB (n=120): exact no-op** — SR 0.000 both arms, per-row dtg equal
  to 4 dp, 1,241 keyframes recorded and **0 routes found**. The memory-honesty
  rule confirming itself, exactly as the r2 plan re-registered it.
- **Drifted arm** (calibrated_go2 × ON, stated prefix n=6):
  `graph_reanchor_events = 0` on every episode — MAP-frame discipline
  observed; arrival-honesty (B5) untouched by construction (MAP is
  truth-passthrough on this profile).
- **Teach-and-repeat:** deviation from the taught line 1.96 m (ON) vs 1.86 m
  (OFF) — RM-2's waypoint is an aim point, not a path replay. Recorded as a
  capability boundary, not a defect.

## Sprint close — where SLAM_M_PLAN lands

- **Wave 1 (RM-1, DR-1): CONFIRMED.** Place-graph memory + drift ladder, 110
  tests, all contracts held downstream.
- **Wave 2 (RM-2, DR-2): CONFIRMED** after one return each; 131 tests. Two
  real wiring defects fixed pre-landing (stale-task bus residue, cadence-blind
  hand-back probe); the degraded-pose arms caught the arrival-honesty defect
  (**B5**, nightly `pose-drift-arms:safety` deliberately red, owner-gated).
- **Wave 3 (RM-3): CONFIRMED**, gate honestly failed; cause isolated to the
  collision-brake/config interaction (**B6**, owner-gated 2×2). The
  route-memory mechanism is wired, audited sound, measurably active, and
  default-OFF; it cannot convert the bottleneck until B6 is decided.
- Owner queue, in dependency order: **B6** (unblocks any route-memory value),
  **B5** (arrival honesty under drifting MAP), then the plan's standing OPEN
  items (cross-session persistence policy, teach-and-repeat voice surface,
  drift-floor tiering, CityWalker/VLFM).

## Closing gate (Fable's run)

`ci_gate --tier commit`, 2026-08-12T09:57:02Z, at the final tree state:
**RESULT: PASS — every hard gate green** — default-suite **3943 passed,
9 skipped, 0 failed**, ruff 7 violation(s) = baseline 7 (new 0), 4/4 frozen
sentinels byte-identical, elapsed 187.5 s. (Executor's independent
09:51:41Z run: identical verdict.)
