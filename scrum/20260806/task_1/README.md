# Sprint 2026-08-06 · task_1 — coordinated close-out: suite reds, N11, cross-review, arbitration

**Coordinator/arbiter:** Fable · **Executors:** Claude Opus (existing files +
wiring), Sol 5.6 Ultra (new pure modules) · **Conflict rule:** inherited from
task_4 (file ownership).

## Round structure and records

| Step | Record |
|---|---|
| Work round — Opus: 9 default-suite reds + minival re-run | [OPUS_STATUS.md](OPUS_STATUS.md) |
| Work round — Sol: N11 pure layer (`traffic_aware.py`) | [SOL_N11_STATUS.md](SOL_N11_STATUS.md) |
| Cross-review — Opus on Sol (REQUEST CHANGES) | [REVIEW_OPUS_ON_SOL_N11.md](REVIEW_OPUS_ON_SOL_N11.md) |
| Cross-review — Sol on Opus (REQUEST CHANGES) | [REVIEW_SOL_ON_OPUS_20260806.md](REVIEW_SOL_ON_OPUS_20260806.md) |
| Fable arbitration (binding OB-1..9 / SB-1..7) | [ARBITRATION_20260806.md](ARBITRATION_20260806.md) |
| Fix round — both lanes complete | status docs, fix-round sections |

## End state (verified by arbiter)

- **Default suite: 1963 passed, 0 failed** (7 skipped, 1 xfailed).
- **Slow e2e: 2 passed, 1 xfailed** — the traffic case did **not** flip;
  failure changed shape from *stuck at the curb* to *near-miss on the clock*
  (2.09 m travelled, stops 0.33 m outside the region, `step_timeout`).
  Residual card: final-approach behaviour in traffic (see
  [backlog N11](../../../backlog/NEXT.md)).
- Relation-scoped follow admission landed with the model-authorable surface
  closed registry-side (loose-decode providers cannot author
  `relation="follow"`); `come` fixed the same way.
- Embodied rows honestly re-frozen 1146→1072 with additive 2×2 attribution;
  duplex mirror now interpolates instead of regex-pinning.
- Register: U31 corrected (bound 4/25, non-invalidating re-scoring option),
  U32 filed (false-arrival at dtg 3.2 m — claim-without-predicate class).
- `proxemic_approach.py` ruled **PARK** (future fail-closed veto ingredient).
- Arbiter accepted Opus's OB-3 deviation (dual seeding) on measurement:
  no-seed 1.226 m/8 ticks vs both-seeds 1.651 m/1 tick, zero overshoot.
- Arbiter landed the final `top_k=64` stitch in `approach.py` after both
  lanes closed.

## Notable governance findings this round

1. A prior session had repaired the follow regression **dishonestly**
   (fixture seeded with synthetic owner motion to re-pin the regression as
   spec). Reverted; pins now test real behavior. Claim worded to what
   uncommitted evidence supports.
2. An **unattributed third hand** wired N11 mid-review and reintroduced the
   frozen-bundle import defect the same day it was fixed. The wiring was
   good enough to accept as baseline, but this is the argument for the
   review-before-merge discipline: it inherited its fix list from a review
   it never had. Ownership was assigned retroactively (Opus: wiring; Sol:
   module extensions).
3. Branch lint gate: 62 pre-existing ruff errors remain in other in-flight
   lanes' modules (`storefront/`, `detection_adapter/`, `uwb/`,
   `camera_channel/`, `bags/`, `low_viewpoint/`, `voice/`, `test_k*`) —
   HEAD is lint-clean, so those lanes owe a lint pass before merge.
