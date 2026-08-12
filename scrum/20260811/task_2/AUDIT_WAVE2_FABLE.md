# Fable audit — SLAM_M_PLAN Wave 2 (RM-2, DR-2), 2026-08-12

## Verdict: both cards CONFIRMED — each after one RETURN cycle, fully re-verified.

1. Fresh ci_gate (Fable's run, 2026-08-12T07:53:17Z): **PASS — 3909/0,
   10/10 hard gates**, ruff 7 = baseline 7. Delta accounting: 3778 baseline
   + 43 RM-2 (40-cell `tests/test_rm2_route_memory_product_path.py` + 3 AF-2
   interleaving extension) + 88 DR-2 (`tests/test_dr2_pose_drift_arm.py`).
2. Adversarial protocol as pre-registered, executed for real: two workflows,
   22 agents (RM-2: 6 hunters over the five pre-registered surfaces + 2-refuter
   panels on every major; DR-2: 4 hunters + panels). Every blocking/major
   verdict required an EXECUTED repro; every upheld finding was re-verified by
   Fable with the auditors' own instruments after the fix.
3. Ownership: clean after one correction. RM-2's `route_memory/__init__.py`
   +18/−2 beyond the Wave-1 pin was initially misattributed to RM-1 in
   RM2_STATUS §6 (upheld 2-0); now owned with the enumerated out-of-literal-OWNS
   note on RM-1's own precedent — verified additive re-exports, the 2 deletions
   isort interleaving, no export altered. DR-2 OWNS-clean; `headless_city.py`
   untouched; Wave-1 files byte-frozen. One info nit for the record:
   DR1_STATUS §8 says pose.py +219/−1, git measures +218/−1 — doc off-by-one,
   no content question.

## RM-2 — returned with 4 findings, revision 2 confirmed

- **F1 (upheld 2-0, fixed):** task-switch correction flushed the ProposerBus
  under the NEW task id — the corrected-away waypoint stayed buffered and could
  still win resolve. Fixed by recording the published-under task at publish
  time; mission boundaries now purge the bus; withdrawal is source-scoped (no
  bystander blast radius); `set_active_revision`'s pre-RM-2 body restored
  verbatim on the unconditional path. Fable re-ran the audit's attack suite:
  **7/7 PASS** (was 4 defects).
- **F2 (upheld 2-0, fixed):** the hand-back probe read `last_route_status` one
  tick after probing, but the shipping GridNavigator replans on a 5-tick
  cadence and never on goal change — so the probe read the WAYPOINT's cached
  status, falsely handed back, and irreversibly blacklisted the candidate in
  exactly the scenario class route memory exists to win. Fixed: the verdict is
  trusted only when the plan's `requested_goal_world` IS the probed goal, held
  up to 2× the pinned planner cadence, fail-closed to REFUTED. Fable re-ran the
  mission repro: CADENCE arm 5/5 phases went failed-at-dtg-9.10-with-blacklist →
  **arrived dtg 2.45, no blacklist**, matching the fresh-plan reference.
- **F3 (panel split 1-1, adjudicated — doc + design record, no code change):**
  a watchdog-replan re-commit re-arms the same candidate ("one chain per
  committed instance" was false as stated). The dissenting refuter proved by
  execution that the one-line spent-marking "fix" converts a recoverable
  world's ARRIVAL into a blacklist failure. Recorded as a two-sided design
  decision with the honest bound (advancing-chain deferral, terminated by the
  flag-independent watchdog ladder), pinned as INTENDED by a regression test.
- **F4 (upheld 2-0, doc):** the §6 attribution correction above.
- Standing notes in §7 does_not_prove (no action): lethal veto over a waypoint
  leg is point-sampled at keyframe spacing with no attach-segment coverage
  (pre-existing S-B behavior; planner costmap + reactive gate are the actual
  obstacle defense); a won interim waypoint is one-shot-arbitrated and outlives
  its 2.0 s TTL for the leg (sanctioned, bounded by the 8.05 m reach rule);
  priority 3-vs-10 verified but vacuous (all product resolve pools are
  singletons). Trigger (ii) non-vacuity remains UNMEASURED — every measured
  row came through trigger (i); binding on RM-3 below.

## DR-2 — confirmed; its hard red stands as the wave's headline finding

- Measurement layer verified to the bit: auditors re-ran arm prefixes and the
  full re-anchoring arm with independent instrumentation — **all 61 per-episode
  rows match the Stage-A artifact exactly**; all 61 per-episode seeds
  re-derived; LOST scoping (61/61 held 30 ticks, recovered) and re-anchor
  counting (518 on the re-anchoring arm, 0 elsewhere) verified against an
  instrumented provider; Stage B reproduces Stage A bit-for-bit; floors are
  mechanically sr − 1/61 from the named artifact.
- Four minors fixed on return: two comment overclaims (per-episode bands cannot
  detect a tier mix-up — bands overlap almost completely, `ladder_monotone` at
  the arm mean is the tier check; DR1's p90 column does NOT reproduce
  "exactly" under any estimator, mean/median/min/max do), and the floor-dodge
  closed (a truncated `--stage b --limit N` run can no longer certify pinned
  full-set floors; traceability now asserts full-substrate, full-arm-set
  provenance). No measured number moved; no sweep re-run needed.
- **The false arrival (CONFIRMED 4-0, bit-for-bit, and STRENGTHENED):** under
  `calibrated_go2_reanchoring` the arrival predicate consumes 100 % of the K0
  band with no reserve for pose error — MAP-frame stop margins 0.002–0.040 m
  against claim-tick MAP errors 0.007–0.239 m; **3/7 arrivals stopped
  TRUE-outside the band** (only the −0.153 m one exceeded the scorer's 0.05 m
  epsilon; −0.043 and −0.024 were absorbed as `tolerated_boundary`). The honest
  rate is 3/61, not 1/61, set by the drift tier, not geometry. Neither existing
  guard can catch it (provider HEALTHY at claim; covariance 3.6× optimistic by
  documented design). The nightly `pose-drift-arms:safety` gate is RED on this
  and **stays red** — the fix is owner-gated as
  [backlog B5](../../../backlog/BLOCKED.md) (frozen-row movement ⇒ 2×2).
  Commit tier is unaffected and green.

## Cross-lane intel binding on Wave 3 (RM-3)

- **The eval runner has never run flag-ON.** `route_memory` is not in
  `ALLOWED_NAVIGATOR_OVERRIDES`; RM-3 owns `runner.py` this wave and must add
  it — treat any pinned-allowlist test edit as an enumerated amendment. DR-2's
  drift-arm plumbing in the same file is frozen for RM-3 except additively
  (88 tests pin it).
- **The hand-back probe hold costs ~9 ticks** (bounded at 2× planner cadence,
  distribution on the real planner unmeasured). Paired ON/OFF budgets must not
  straddle it; the DELTA is the evidence, never the win alone.
- **Trigger (ii) is unmeasured.** RM-3's cell set should include at least one
  partial-plan non-progress cell, or report it as still unmeasured — do not
  let the gate silently ride on trigger (i) alone.
- **B5 does not contaminate RM-3:** the gated cells run truth MAP, and the
  report-only drifted arm is `calibrated_go2`, where MAP is truth-passthrough.
- Scenario honesty per the memory-honesty rule (Y-3): recorded edges must
  cover start→goal; the goal sighted-or-known but beyond planner reach; both
  attach ends within 8.05 m of recorded keyframes. Isolated ON/OFF processes;
  `reset_track()` at every episode boundary.

## OPEN (owner-gated) — unchanged from the plan, plus B5

- **B5 (new): arrival honesty under a drifting MAP** — see backlog/BLOCKED.md.
- Cross-session place-graph persistence policy; voice surface for
  teach-and-repeat; drift-arm floors nightly-vs-commit; CityWalker A/B +
  VLFM-real (out of scope until this lands). Arbiter-owner candidate:
  `ProposerBus.withdraw(source)` (RM-2's poll/flush/re-publish sandwich stands
  until then).
