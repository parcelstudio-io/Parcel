# Sprint 2026-08-06 · task_3 — strata generalization plan (research complete, pending owner approval)

Deep-research plan for the five hardcoded strata from
[docs/NAV_GENERALIZATION_AUDIT.md](../../../docs/NAV_GENERALIZATION_AUDIT.md),
plus the six-instrument robust eval program. The full plan is the docs
record: [docs/STRATA_GENERALIZATION_PLAN.md](../../../docs/STRATA_GENERALIZATION_PLAN.md)
(workflow `wf_3ba06b92-a88`, 4 researchers + synthesis).

Shape: Wave 0 truth-keeping (U31/U32 closure + differential authority
logging + derived eval tables, days, no behavior change), then four
parallel lanes — A embodiment/config authority triple, B pose seam +
drift injector, C vocabulary/relation registries (contains N12/N13/U33),
D perception chain + classical tracker (contains N11-residual). Every
stratum fix names its eval gate in an existing harness; anti-goals
binding (no new harnesses, no SLAM in sim, derivation over exposure).

**Status: APPROVED by owner 2026-08-06 — implementation dispatched.**
Rounds: Wave 0 (single executor) → Lanes A+B parallel → Lanes C+D parallel
→ cross-review → Fable arbitration → final verification. Per-round status
docs land in this folder.

## Rounds

- **Wave 0 — [W0_STATUS.md](W0_STATUS.md) · landed 2026-08-06.** U31 closed by
  derived re-scoring (baseline 1/25 → 3/25, candidate 1/25 → **4/25**, the
  predicted bound), U32's `false_arrival` class landed and D-15 reclassified,
  differential authority verdicts logged in all three harnesses, scene-truth
  artifact + regeneration diff. Zero behavior change; frozen rows byte-identical.
  **Carried forward:** the hand-transcribed eval landmark table disagrees with
  the scene in 7 fields (sidewalk band 0.8 m too narrow, `bldg_1` radius 0.54 m
  short, …) — pinned, not adopted; adoption needs a re-freeze card, best
  sequenced with U31 option 2.

## Program close-out (2026-08-07, Fable)

All waves and lanes landed; suite **2643 passed / 0 failed / 5 xfailed**
(the whole collection). Post-lane arbitration rounds: the coordinator's
frozen-bundle fallback + ratchet entries; the region-instance selection
card (boundary-distance ranking, look-around-before-commit,
[REGION_INSTANCE_STATUS.md](REGION_INSTANCE_STATUS.md)) with the honest
1072→1250 embodied re-freeze; and the unroutable-goal release
(alternate_candidate recovery — the towards-lamppost freeze, root-caused
to bldg_5 standing on sidewalk_south leaving a 0.85 m strip).

Remaining honest xfails: sit-next-to ×2 (placement half — N11 family),
sidewalk-in-traffic (flip decision deferred pending a post-arbitration
measured run; Lane D's pre-arbitration evidence was 2/3 seeds arriving),
half-scale profile smoke (Lane A's pin until profile reaches the
planner), one Lane-C towards-paraphrase baseline. Sharp edges recorded,
not smuggled: first-confirmed edge at ≥2-visible/1-confirmed;
nearest_point_in_region 0.4 m sampling bias; safe_approach_pose None
fails instead of releasing; bldg_5/sidewalk_south scene overlap;
tree/planter co-location (N-SUP-4); W0-D transcription-mismatch adoption
+ mis-specified episodes (D-15, B-05) awaiting the single bundled
re-freeze decision (owner call).
