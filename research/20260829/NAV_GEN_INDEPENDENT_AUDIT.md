# Independent audit of NAV-GEN-1

**Audit date:** 2026-08-29 (America/New_York)
**Mode:** read-only audit of retained code, reports, scene manifests, and raw
paired rows; no live stack or product files changed
**Readiness scope:** oracle/headless regression evidence only; no physical Go2
claim

## Corrected conclusion

NAV-GEN-1 executed 5,510 rows when its 530-row A0 determinism repeat is
included. There are 4,980 unique arm-condition rows and 450 unique generated
episode specifications. The reported generated-scene A0 score independently
recomputes to 293/450 strict successes (0.651111), 310 band entries, 284
navigator-claimed successes, 42 false arrivals, and zero simulated collisions.

The original report's clearance-causality wording is too strong. Lowering the
coupled `obstacle_stop_m` parameter did not improve aggregate strict success
materially: B1 was best at 302/450, a +2.00 percentage-point change. It did,
however, alter failure modes substantially. The 49 A0 rows labelled
`semantic_target_unreachable` became, under B4, 19 verified arrivals, 18
no-progress failures, eight still-unreachable results, and four
arrival-verification failures; 24 became strict successes. Unreachable counts
fell monotonically from 49 to 31, 14, 10, and eight across A0/B1/B2/B3/B4.

Therefore the defensible finding is:

> The clearance retune did not improve aggregate strict success enough, but it
> strongly altered unreachable episodes and downstream failure modes. Current
> telemetry cannot isolate whether approach selection, A* inflation, or the
> downstream gate caused the release.

The sweep is not a planner-only intervention. The same parameter influences
collision-policy construction, planner inflation, safe-approach selection,
fallback clearance, and vicinity/gating behavior. It also increased exposure
below the 0.65 m stop band from one A0 episode to 3/13/18/15 episodes in
B1/B2/B3/B4. It is not a safe global proximity recommendation.

## Crosswalk attribution

The crosswalk defect is reproduced and important. On the 90 generated A0
crosswalk cases:

- 90/90 were assigned the fixed demo POI `crosswalk_a` at `(3.5, -0.6)`;
- 90/90 selected the wrong generated-scene instance;
- only 6/90 were strict successes and 11/90 entered the true target band;
- the navigator claimed success in 42/90, all 42 being false arrivals;
- conventional median and maximum true-target distances for those false
  arrivals were 3.17215 m and 7.169 m.

This establishes a default/harness map-context defect: the demo POI catalog
declares a map identity, but the grounder discards that identity and applies the
static coordinate before semantic search. It does **not** establish that the
physical Go2 profile will choose that coordinate. The Go2 profile selects the
venue `learned_map` source and normally disables static POIs outside oracle
mode. That real path remains unvalidated.

The smallest product correction is to preserve POI catalog map/frame identity,
require it to match the active localization map, and otherwise fall through to
scene-local semantic grounding. A bare class such as “crosswalk” must not bind
globally to one coordinate. Generated scenes should receive an explicitly
empty or scene-specific POI catalog.

## Required next instrumentation

Each navigation row should retain `goal_source`, active map and POI-catalog IDs
and hashes, candidate and selected instance IDs, selected/rejected approach
poses, effective planner inflation, planning target, route status/note, gate and
progress counters, and an `unreachable_release_source` distinguishing
approach-pose rejection, planner no-path, and gate blocking. A paired factorial
should then vary planner inflation, approach clearance, and reactive braking
independently while keeping the final safety gate fixed. Grid connectivity must
be measured from start to at least one valid goal cell, rather than inferred
from a standable terminal-band sample.

## Provenance limits

The retained 30 scene XML hashes match their manifest (aggregate digest
`b698e0594a7d456050bb3740e2c961da7748dd19dd8f25b643904d1729b4ab43`),
and a verifier rerun reproduced canonical A0 rows. Original raw rows remain
outside the repository and lack an immutable row/code/config digest manifest.
This is useful reproducibility evidence, not complete original-run provenance.

Physical promotion still requires the exact Go2 learned-map profile,
synchronized perception and localization, target timing, the commissioned STOP
path, braking-distance tests, and hardware-in-loop evidence.
