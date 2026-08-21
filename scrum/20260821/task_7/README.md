# Task 7 — PG-2: an answer key a sensor can actually measure

**Executor:** Claude Opus (agent) · **Auditor:** Fable (deferred)
**Evidence:** `scrum/20260821/perception/bench_mapping.md`. Building entries
built from real RGB-D land **1–3 cm from the visible facade and 1.2–1.7 m
from the geom centre — 6/6 in the oracle arm, 5/6 in the open-vocab arm.**
That is correct sensor behaviour: a depth camera sees surfaces, never
centroids. `scene_truth.json`'s centre+radius convention is therefore
**unmeasurable by any RGB-D sensor**, and grading perception against it would
fail a working pipeline. The bench also disclosed a flaw in its own metric:
containment scoring is uninformative for large regions (sidewalk and
crosswalk scored 0.00 m against a *random* map, p=1.00).

## Work

1. **A surface-based ground-truth convention.** For each semantic entity,
   ground truth gains a sensor-measurable target: the observable surface
   (facade polygon / nearest-surface set) alongside the existing
   centre+radius, with the convention documented and versioned. Existing
   consumers keep working (R10's arrival semantics use region containment for
   `inside` classes — that stays); the new field is what perception is graded
   against.
2. **Per-class scoring rules that discriminate.** Large-region queries
   (`inside` classes: sidewalk, grass, crosswalk) need a metric a random map
   cannot pass — e.g. containment PLUS a null-control margin requirement, or
   distance-to-nearest-boundary. Adopt the bench's own null control
   (re-scatter entries uniformly, N draws, report p) as a REQUIRED companion
   statistic for every perception localization claim. A number without its
   null control is not a result.
3. **Arrival-semantics reconciliation:** confirm — with a test — that
   targeting the facade for `near`-class building queries agrees with what
   the owner means by "go to the building", and that `inside`-class arrival is
   unaffected.
4. **Regenerate the pinned artifacts properly** if `scene_truth.json` or the
   scene semantics sidecars are digest-pinned: use the documented
   regeneration tooling, never a hand-edited digest, and keep sentinels and
   release-parity green.

OWNS: `scene_truth.json` + generator, scene semantics sidecars, the
perception scoring/eval helpers, `navigation/arrival_semantics.py` ONLY where
the facade/centre distinction is consumed (smallest touch, justified), tests,
`PG2_STATUS.md`.
MUST NOT TOUCH: `realtime/*`, yield policy, the detector paths (PG-1 owns
those), the 9 skipped tests. Standard house rules.

## Definition of done

Gate green including sentinels and release-parity; ≥8 seeds RED (surface
field dropped; centre used for a `near`-class building; null control removed
from a localization claim; large-region metric reverted to bare containment;
a hand-edited digest). Evidence: re-score the mapping bench's 120-frame run
against the NEW convention and show the corrected verdict per query, with
null controls — i.e. demonstrate the convention change actually re-grades the
pipeline correctly. `PG2_STATUS.md` standard register.
