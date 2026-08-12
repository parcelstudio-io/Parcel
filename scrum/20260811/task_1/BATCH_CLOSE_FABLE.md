# Batch close — follow-up designs, all three waves + two fix lanes (2026-08-11)

Orchestration per owner directive: **Opus implemented, Fable audited.** Base
`dd2e857`; the whole batch is UNCOMMITTED for owner review.

Final consolidated `ci_gate --tier commit` (Fable's own run): **PASS — 3668
passed, all 10 hard gates green** (incl. the new follow-bench-jerk-ratchet),
ruff 7/baseline 7/new 0, 4 digest sentinels byte-identical, frozen v4
baseline `false_arrival=0` intact.

## Verdicts

| Lane | Verdict |
|---|---|
| Wave 1: DOC-1, D15-A/B/C, J-A/B/C | CONFIRMED (AUDIT_WAVE1_FABLE.md) + AF-1 closure |
| Wave 2: VS-1/2/3/6 | CONFIRMED |
| Wave 2: VS-5 | CONFIRMED-with-corrections (honest effect-gate STOP stands) |
| Wave 2: VS-4 | RETURNED → **repaired by AF-2, verified** |
| Wave 3: Y-1/Y-2/Y-4 | CONFIRMED |
| Wave 3: Y-3 | honest STOP — rotated-aim formulation structurally refused on the oncoming corridor; flag stays OFF |

Verification depth note: Waves 1–2 received full adversarial workflows (34 +
~30 refutation attempts). AF-2 and Wave 3 received targeted verification
(fresh gate, spot-run of the healed-repro/PH-31/Y-1 property suites — 100/100
— plus the two lanes cross-attributing each other's transient reds). Chosen
deliberately: both lanes executed audit-specified fixes with binding
directions and carry seeded-failure proofs; a third full adversarial round
was judged low-yield. The residual risk class is the one all audits share:
what no lens thought to attack.

## What the batch delivered (net)

- **D-15 diagnosed and answered**: the deadlock-behind-humans capability gap
  has a working, flag-gated person-aware nav (declared-owner yield at exactly
  the 1.2 m floor; planner-blindness root cause measured; H-1 handoff is the
  one line that makes it live — owner-gated, moves frozen rows).
- **Jerk**: severity-split smoothing built and measured (1.2187 → 1.0813,
  honest miss vs the 1.05 pre-registration — the gap is the measured price of
  the two skeptic-mandated safety closures); jerk is now HARD-ratcheted in CI
  either way; the 58% historical drift attributed to two deliberate changes.
- **Visual search**: B-05 wrong-instance false arrival structurally closed
  (reference/estimate separation; verify-on-approach; per-relation
  no-dead-zone checkpoints after AF-2 — 0 offenders over 9 604 probes);
  phantom chain (commit→refute→suppress) proven live; FP-memory made
  effective (0 → 18 suppressions on the PH cells, false arrivals halved);
  the revision-usurpation blocking defect repaired revision-neutrally with
  the audit's repro healed; 180-episode v4s search benchmark landed with
  non-vacuous gates.
- **VS-5's negative result redirects the roadmap**: value-directed search is
  mechanically sound but cannot lift SR because **planner reach (~8 m) is the
  measured bottleneck** vs 12+ m sensing. route_memory / long-horizon routing
  is now evidence-backed as the next capability lane.
- **Yield-aside**: pure proposer with proven equilibrium (floor 2.946 m vs
  1.75 keepout) and stall guard; wiring safe (flag-off byte-identical,
  strictly upstream of the untouched gate); the corridor-displacement aim
  honestly refused — the formulation cannot displace and hold band.
- **Eval integrity**: digest recipes now reproduce (pinned by test); v4s
  matcher-arm pinned; the defective lock-on-without-verify combination warns
  loudly at construction.

## Consolidated owner decision queue (nothing blocks on these; safe defaults shipped)

1. **Jerk smoothing**: accept 1.0813 & flip ON (Fable leans accept) / hold OFF.
2. **H-1**: publish people to the planner → person-aware nav live (frozen-row
   re-freeze authorization, same class as v4).
3. **pedestrian_group ≥0.75 band**: unreachable at person_slow 2.5 — Y-4's
   memo prices 5 options (incl. the one-line person_slow_m lever: 2.5 → 6/9 +
   0.530 m vs 2.0 → 9/9 + 0.382 m).
4. **SigLIP default-on matcher**: lifts baseline search 0→0.100, zeroes 10
   false arrivals; alias fallback is actively harmful where weights exist.
5. **Planner reach / route_memory lane**: the measured next capability.
6. **Flag flips**: lock_on+verify (now sound on the eval path), value-map
   (sound, effect blocked on #5), yield_aside (refused — keep OFF);
   whether to hard-refuse detection_lock_on-without-verify.

Handoffs carried (non-blocking, recorded in lane docs): metrics yield_active
column; FOLLOW_BENCH_YIELD_EXT fold-in; dynamic_agents gate widening; C2
mission.metadata instrumentation; failed-mission session-lifecycle note;
harness scan-RNG isolation (open question 8).
