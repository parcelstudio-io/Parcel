# W2-PURE status — cards VS-1, VS-2, VS-3 (2026-08-11, task_1)

Lane W2-PURE, executor Opus. Three pure-module cards from the authoritative
record `scrum/20260811/task_1/FOLLOWUP_DESIGNS.md` (§2 diagnosis + design,
§6 card blocks "Card VS-1" / "Card VS-2" / "Card VS-3"), implemented in the
dispatched order. All three are NEW files only — **zero edits to any existing
`src/`, `evals/`, `tests/`, `configs/` or `scripts/` file**. No commit made.

Contracts delivered here are FROZEN: VS-4 and VS-5 consume them and may not
change them. Each module's docstring states its contract; the surfaces are
enumerated in §5 below.

---

## 1. Baseline and gate

| | |
|---|---|
| Baseline `scripts/ci_gate.py --tier commit` (fresh, before any of my edits) | **PASS** — default-suite 3472 passed, 9 skipped, 35 deselected; ruff 7 violations = baseline 7, new 0; 4 digest sentinels byte-identical; hard-safety, latency-tail, jerk-ratchet, mutation-panel all green |
| After VS-1 + VS-2 + VS-3 | **FAIL on `ruff` only — RED IS NOT THIS LANE'S**, attributed below and in §6; every other hard gate PASS, default-suite 3541 passed |

Two sibling lanes were live in the tree during this work (AF-1 on
`tests/test_nominal_stop_wiring.py` + docs; W2-EVAL on new
`evals/nav_instruct` cell files). Nothing in this lane touches their files;
attribution notes are in §6.

---

## 2. Card VS-1 — verify-on-approach lock-on state machine + per-kind refinement gate

**OWNS (both NEW, as the card block lists):**
`src/parcel_robot/navigation/lock_on_verify.py`,
`tests/test_lock_on_verify.py`.
**MUST-NOT-TOUCH honored:** `pipeline.py`, `runtime.py`,
`instructnav/arbiter.py`, `core/**`, `reactive_safety.py`,
`velocity_shaping.py`, `multi_view_confirm.py` — none opened for write; all
consumed read-only or not at all.

### Derivations (no literal of this module's own)

| Quantity | Value | Authority, consumed BY REFERENCE |
|---|---|---|
| checkpoint radii | `(vicinity, stand_off, minimum_vicinity)` descending, de-duplicated | `instructnav.scoring.object_near_envelope_m` — the three returned floats, never re-arithmetised |
| `VIEW_ADMISSION_SEPARATION_RAD` | 0.7853981633974483 | `abs(full_turn_scan_spec().total_yaw_rad) / n_stops` = 2π/8 (adjudication #8; the fake confirmer-constant derivation is NOT used) |
| `REGION_DILATION_M` | 0.05 | `instructnav.scoring.ARRIVAL_BOUNDARY_EPSILON_M` — the boundary margin the interchangeable ranking / differential-authority verdict already use |
| `MAHALANOBIS_GATE_SIGMA` | 2.145966026289347 | `sqrt(-2·ln(1 − INSIDE_PROBABILITY_THRESHOLD))`, K0's own chance-constraint level; the `2` is the planar state dimension |
| `LockOnVerifyConfig.identity_threshold` | 0.9 | `instructnav.siglip.SIGLIP2_MATCH_THRESHOLD` |
| state vocabulary | APPROACH / VERIFY / VERIFIED / REJECTED | `instructnav.scoring.ApproachVerifyState` — reused, not re-declared |

`tests/test_lock_on_verify.py::test_module_states_no_geometry_constant_of_its_own`
is an AST audit: the only numeric literals in the module are `0, 1, 2, 3`
(identity elements, the planar dimension, the minimum polygon vertex count).
A retune of any authority above moves this module automatically.

### Gate clauses → tests (all measured, all green)

| Card gate clause | Test |
|---|---|
| (1) checkpoint radii `struct.pack`-identical to `object_near_envelope_m` | `test_checkpoint_radii_are_bit_identical_to_the_envelope`, `test_lamppost_branch_collapses_to_two_checkpoints` |
| (1) admission angle `struct.pack`-identical to 2π/n_stops, no new literals | `test_view_admission_angle_is_the_scan_stop_separation_by_reference`, `test_region_dilation_and_mahalanobis_gate_are_derived`, `test_module_states_no_geometry_constant_of_its_own` |
| (2) V-B phantom (constant bearing/range, no covariance shrink) ends REFUTED, never VERIFIED, at every operating point | `test_vb_constant_bearing_range_phantom_is_refuted_at_every_operating_point`, `test_view_consistent_phantom_without_covariance_shrink_is_refuted` (both loop the 4-point envelope grid: bare object, lamppost, tree, building) |
| (3) covariance-trace increase or persistence miss at a checkpoint ⇒ veto | `test_covariance_trace_increase_at_a_checkpoint_vetoes`, `test_persistence_miss_at_a_checkpoint_vetoes` (with a same-trace VERIFIED control so the veto is not vacuous), `test_identity_recheck_failure_at_a_checkpoint_vetoes` |
| (4) REGION — fused point outside the dilated polygon ⇒ REJECT, B-05 canned | `test_b05_wrong_instance_displacement_is_rejected` (displacement pinned to 4.778530810034543 at 1e-12), `test_region_gate_dilates_by_exactly_the_ranking_boundary_margin` (200-point sweep across the dilation edge) |
| (4) OBJECT — outside vicinity band or Mahalanobis-inconsistent ⇒ REJECT | `test_object_gate_rejects_outside_the_vicinity_band` (200-point sweep per operating point), `test_object_gate_rejects_mahalanobis_inconsistent_fusions`, `test_mahalanobis_clause_is_inert_at_zero_covariance` |
| (5) three consecutive same-pose ticks are ONE admissible view | `test_three_same_pose_ticks_are_one_admissible_view`, `test_admission_needs_a_whole_scan_arc_of_separation` |

Additionally pinned: a consistent shrinking approach clears every checkpoint
and VERIFIES (positive control, 4 operating points); a VERIFIED session keeps
re-verifying and can still be refuted — the direct fix for the measured
`if self._committed: return None` defect (record §2.1(3)); a refutation emits
the `NegativeEvidence` record VS-2 consumes, and is terminal.

### Property tests (each proven able to fail on a seeded violation)

| Property | Oracle | Seeded violation that kills it |
|---|---|---|
| Repeating one observation can never advance the machine (state, admitted-view count, cleared checkpoints) — 50 randomized references/poses | `_property_no_self_confirmation` | `test_seeded_violation_kills_the_self_confirmation_property`: a subclass that counts every tick as a view and self-VERIFIES → `pytest.raises(AssertionError)` |
| The refinement gate's acceptance equals the per-kind geometric predicate computed independently (own point-in-polygon + segment-distance implementation) — 400 randomized points over 5 references | `_property_gate_agrees_with_geometry` | `test_seeded_violation_kills_the_refinement_geometry_property`: the B-05 point asserted "accepted" → `pytest.raises(AssertionError)` |
| A closing approach verifies **iff** its D2 trace keeps shrinking — 40 randomized runs across the operating grid | `_property_shrink_decides_the_verdict` | `test_seeded_violation_kills_the_shrink_property`: a real non-shrinking run asserted "shrinking" → `pytest.raises(AssertionError)` |

### Interpretations recorded (record wins; these fill gaps it leaves)

1. **View admission is measured at the ESTIMATE** — the world bearing from the
   fused estimate to the observer (the aspect angle). Two looks from the same
   aspect are the same look however many ticks separate them, which is exactly
   the measured self-confirmation mode (`observe_candidate` re-reading one
   cached candidate with a per-tick `now_ns`). Gate clause (5) is satisfied
   directly by this choice.
2. **Checkpoint freshness** — the record fixes the M-of-N admission quantum
   and says a checkpoint "demands fresh evidence", without defining freshness
   for the checkpoint machinery. Covariance shrink ALONE is spoofable: a
   static Kalman filter re-fused with the same measurement shrinks
   monotonically (the metric form of the same bug). Implemented rule: a
   checkpoint may be cleared only by an observation whose geometry changed —
   the admission quantum in aspect, OR a strictly closer range to the
   estimate. This is strictly stronger than "any view clears", and it keeps a
   legitimate radial approach able to verify (a pure aspect rule would stall
   it forever, contradicting §2.4's "slows legitimate commits by ~one scan
   arc"). Both notions are published separately (`admits_for_confirmation`
   for M-of-N, `is_fresh_observation` for checkpoints) so VS-4 can feed
   `MultiViewConfirm` with the record's rule verbatim.
3. **"Inside the vicinity band" for objects** is read as a DISC
   (`|fused − centre| ≤ vicinity_m`), not an annulus. The band's inner edge is
   a stand-off for the BODY; the fused estimate is an estimate of the object
   itself, so an annulus reading would reject an estimate that lands exactly
   on the object.
4. **Object range is centre-referenced**, because every term
   `object_near_envelope_m` returns already includes the object radius; region
   range is the exact boundary distance, the same question the interchangeable
   ranking asks.
5. **VERIFIED is not terminal** (only REJECTED is). Re-verification after
   commit is the point of the card.

**Tests: 29, all green.** `does_not_prove` recorded in the module
(`DOES_NOT_PROVE`, 3 entries) and asserted present by a test.

---

## 3. Card VS-2 — false-positive memory: negative evidence with TTL/decay

**OWNS (both NEW, as the card block lists):**
`src/parcel_robot/detection_adapter/false_positive_memory.py`,
`tests/test_false_positive_memory.py`.
**MUST-NOT-TOUCH honored:** `multi_view_confirm.py`, `metric_localizer.py`,
`pixel_detections.py`, `camera_channel/**` — read-only or untouched.
`tests/test_vb_multiview_metric.py` is **byte-unchanged** (absent from
`git status`) and still **10 passed**.

### Derivations

| Quantity | Value | Authority |
|---|---|---|
| cell pitch + label normalisation + `key()` | 1.0 m | `instructnav.scoring.FalsePositiveMemory` — composed, not re-implemented, so the two memories cannot disagree about "the same place" |
| `DEFAULT_TTL_VIEWS` | 30 views | `MultiViewConfig().rejected_memory_views` |
| `max_entries` | 64 | `MultiViewConfig().max_hypotheses` |

Clock unit is the VIEW COUNTER — the unit the confirmer's own rejection
horizon is already expressed in, and the only clock a pure module can be
handed without inventing one. Decay is linear in age and REINFORCED by
repetition: an entry refuted `k` times survives `k · ttl_views` views with
strength falling 1 → 0 across that horizon, so "suppressed within TTL,
released after decay" is one mechanism, not two.

### Gate clauses → tests (all green)

| Card gate clause | Test |
|---|---|
| `record_refutation((class, world-cell))` ⇒ `suppressed()` true within TTL, false after decay | `test_refutation_suppresses_within_ttl_and_releases_after_decay` (every view index from 0..TTL asserted), `test_strength_decays_linearly_and_monotonically` |
| commit → refute → re-encounter suppressed on the second encounter | `test_commit_then_refute_then_re_encounter_is_suppressed` — end-to-end across modules: the phantom passes a real `MultiViewConfirm` 3-of-5 window (non-vacuity asserted: it MUST commit), a real VS-1 `LockOnVerifySession` refutes it on approach, the refutation is written, and the re-encounter (fresh id, 0.3 m away) is suppressed with the refutation's own reason |
| `MultiViewConfirm`'s window memory stays distinct and untouched | `test_multi_view_confirm_window_memory_is_a_distinct_untouched_mechanism` (flicker writes the confirmer's memory and NOTHING here; a live negative-evidence memory does not perturb the confirmer), plus `tests/test_vb_multiview_metric.py` unchanged/green |
| `does_not_prove` recorded for real-camera behaviour | `DOES_NOT_PROVE` (3 entries) + `test_does_not_prove_is_recorded` |

Also pinned: suppression survives a fresh track id and a cell boundary
(3×3 neighbourhood, the scorer's own rule), does not leak across classes or to
distant places; reinforcement extends the horizon; mission scope via `reset()`;
bounded entries with weakest-first eviction; `prune` drops only decayed
entries; fail-closed config validation.

### Property tests (each proven able to fail on a seeded violation)

| Property | Oracle | Seeded violation |
|---|---|---|
| Suppression strength is non-increasing in age and never resurrects once zero — 50 randomized labels/places/write-times over 2× the TTL | `_property_never_resurrects` | `test_seeded_violation_kills_the_no_resurrection_property`: a hand-built resurrecting series → `pytest.raises(AssertionError)` |
| This memory's cell key IS the scorer's cell key — 300 randomized labels/points | `_property_key_agrees_with_the_authority` | `test_seeded_violation_kills_the_key_agreement_property`: a memory built on a forked pitch (`cell_m/4`) → `pytest.raises(AssertionError)` |

**Tests: 17, all green.**

### Layering note

`detection_adapter/false_positive_memory.py` imports
`instructnav.scoring` (for `FALSE_POSITIVE_CELL_M` and the keying authority).
That is a new edge from `detection_adapter` → `instructnav`; it is acyclic
(`instructnav.scoring` imports only `parcel_robot.authority`) and it is the
alternative to restating the grid pitch, which the record's derivation
discipline forbids.

---

## 4. Card VS-3 — value-map evidence policy incl. miss-painting + evidence_count

**OWNS (both NEW, as the card block lists):**
`src/parcel_robot/navigation/value_evidence.py`,
`tests/test_value_evidence.py`.
**MUST-NOT-TOUCH honored:** `value_map.py`, `search_entity.py`, `pipeline.py`,
`value_directed_scan.py` — not edited. `value_map.py` is IMPORTED BY THE TESTS
ONLY, to demonstrate the miss-lowers-value claim against the real
`SemanticValueMap2D` fusion rather than asserting it.

### The evidence contract (frozen — this is what VS-5 keys on)

* `value = match_score × observation_confidence`, both already in `[0, 1]`.
  `match_score` comes from `SigLIP2Matcher.match(query, [label], threshold=0.0)`
  — the explicit `0.0` is used so a sub-threshold match still reports its TRUE
  score instead of collapsing to "no match"; the evidence decision is then
  taken at `SIGLIP2_MATCH_THRESHOLD`. The `string_fallback` degrade is
  untouched.
* A look with no query-relevant evidence is a **MISS**: its (low or zero) value
  is painted with the SAME optical-axis confidence a hit carries, so looking
  and finding nothing lowers the region's fused value. The replaced painter's
  `0.15` / `0.05` floors and its substring branch are gone.
* **`ValueEvidencePolicy.evidence_count` counts PAINTS, not candidates, and
  increments iff `EvidencePaint.is_evidence` — which is true iff at least one
  observation in the cone matched the query at or above
  `SIGLIP2_MATCH_THRESHOLD`.** Background-only and miss-only sessions therefore
  report 0 for any number of looks. That is what makes VS-5's
  `evidence_count == 0 ⇒ delegate to the flag-off scorer object` provable
  rather than accidental.

### Gate clauses → tests (all green)

| Card gate clause | Test |
|---|---|
| (1) value derives from the query-match score via the embed seam, string_fallback preserved, not substring floors | `test_value_tracks_the_neural_match_score_through_the_embed_seam` (synthetic embedder: lamppost 1.0 > streetlight 0.96 > tree 0.2 > bench 0.0 — an ordering no substring test can produce), `test_string_fallback_degrade_is_preserved`, `test_value_is_the_match_score_times_the_observation_confidence`, `test_the_replaced_floors_are_gone`, `test_evidence_decision_is_the_siglip_operating_point` |
| (2) a scanned cone with zero query evidence paints a MISS (value decrease) | `test_a_miss_paint_lowers_the_value_of_the_scanned_cone` (real `SemanticValueMap2D` + `ViewCone`; every covered cell strictly decreases, and to exactly half — the map's own fusion rule), `test_an_empty_cone_is_a_miss_and_still_paints`, `test_repeated_misses_drive_a_region_toward_zero` (below the old 0.05 floor after 24 misses) |
| (3) `evidence_count` == exactly the query-relevant evidence paints, 0 for background/miss-only | `test_evidence_count_counts_exactly_the_query_relevant_paints`, `test_evidence_count_is_zero_for_background_and_miss_only_sessions` (50 looks, 0 evidence; then one sighting → exactly 1), `test_sub_threshold_matches_are_evidence_free_but_still_painted`, `test_reset_returns_the_policy_to_an_empty_map` |

### Property tests (each proven able to fail on a seeded violation)

| Property | Oracle | Seeded violation |
|---|---|---|
| `evidence_count` equals the number of evidence paints, `miss_count` the rest, and a zero count implies every paint was a miss — 60 randomized sessions, randomized labels/confidences/look sizes | `_property_evidence_count_equals_evidence_paints` | `test_seeded_violation_kills_the_evidence_count_property`: a subclass that counts every paint → `pytest.raises(AssertionError)` |
| A paint may raise a cell's value only if it carried evidence — 60 randomized looks against the real map | `_property_miss_never_raises_value` | `test_seeded_violation_kills_the_miss_property`: the replaced painter's 0.15 scanned-floor raising a 0.05 cell → `pytest.raises(AssertionError)` |

**Tests: 19, all green.**

---

## 5. Frozen contract surfaces (VS-4 / VS-5 consume; do not change)

### `parcel_robot.navigation.lock_on_verify`

```
VIEW_ADMISSION_SEPARATION_RAD: float = 0.7853981633974483   # 2π / n_stops
REGION_DILATION_M: float = 0.05                             # ARRIVAL_BOUNDARY_EPSILON_M
MAHALANOBIS_GATE_SIGMA: float = 2.145966026289347           # sqrt(-2 ln(1-τ))
DOES_NOT_PROVE: tuple[str, ...]

class ReferenceKind(str, Enum): REGION | OBJECT
    ReferenceKind.from_goal_kind(kind) -> ReferenceKind

@dataclass(frozen=True, slots=True) GroundedReference(
    landmark_id: str, kind: ReferenceKind, label: str = "",
    polygon: tuple[tuple[float, float], ...] | None = None,
    center: tuple[float, float] | None = None, radius_m: float = 0.0)
    .range_from(robot_xy) -> float
    .checkpoint_radii_m() -> tuple[float, ...]

@dataclass(frozen=True, slots=True) ApproachView(
    robot_xy, fused_xy, covariance=None, persistence=True, identity_score=None)
    .aspect_rad / .estimate_range_m / .covariance_trace  (properties)

@dataclass(frozen=True, slots=True) RefinementVerdict(
    accepted, reason, kind, displacement_m, mahalanobis=None); .rejected
@dataclass(frozen=True, slots=True) NegativeEvidence(
    label, world_xy, reason, landmark_id, range_m)
@dataclass(frozen=True, slots=True) VerifyVerdict(
    state, reason, admitted, fresh, confirming_views, fresh_views,
    cleared_checkpoints, pending_checkpoints, covariance_trace,
    reference_range_m, refinement); .verified / .refuted / .veto
@dataclass(frozen=True, slots=True) LockOnVerifyConfig(identity_threshold=0.9)

checkpoint_radii_m(object_radius_m: float, *, label: str = "") -> tuple[float, ...]
refinement_gate(reference, fused_xy, *, covariance=None) -> RefinementVerdict
view_separation_rad(previous: ApproachView, current: ApproachView) -> float
admits_for_confirmation(previous: ApproachView | None, current) -> bool
is_fresh_observation(previous: ApproachView | None, current) -> bool

class LockOnVerifySession(reference, *, config=None, identity_fn=None)
    .observe(view: ApproachView) -> VerifyVerdict
    .negative_evidence() -> NegativeEvidence | None
    .reset() -> None
    .state / .checkpoints_m / .cleared_checkpoints / .pending_checkpoints
    .confirming_views / .fresh_views                              (properties)
```

### `parcel_robot.detection_adapter.false_positive_memory`

```
DEFAULT_TTL_VIEWS: int = 30          # MultiViewConfig().rejected_memory_views
DOES_NOT_PROVE: tuple[str, ...]

@dataclass(frozen=True, slots=True) FalsePositiveMemoryConfig(
    cell_m=FALSE_POSITIVE_CELL_M, ttl_views=DEFAULT_TTL_VIEWS, max_entries=64)
@dataclass(frozen=True, slots=True) FalsePositiveEntry(
    key, label, world_xy, reason, refutations, first_view, last_view)
@dataclass(frozen=True, slots=True) Suppression(
    suppressed, strength, refutations, reason, entry=None)

class NegativeEvidenceMemory(config: FalsePositiveMemoryConfig | None = None)
    .record_refutation(label, world_xy, *, view_index, reason="") -> FalsePositiveEntry
    .suppressed(label, world_xy, *, view_index) -> bool
    .consult(label, world_xy, *, view_index) -> Suppression
    .strength(label, world_xy, *, view_index) -> float
    .key(label, world_xy) -> tuple[int, int, str]
    .horizon_views(entry) -> int
    .entries(*, view_index=None) -> tuple[FalsePositiveEntry, ...]
    .prune(*, view_index) -> int
    .reset() -> None ; __len__
```

### `parcel_robot.navigation.value_evidence`

```
LOOK_CONFIDENCE: float = 1.0     # the map's optical-axis unit weight
DOES_NOT_PROVE: tuple[str, ...]

@dataclass(frozen=True, slots=True) ValueEvidenceConfig(
    match_threshold=SIGLIP2_MATCH_THRESHOLD, look_confidence=LOOK_CONFIDENCE)
@dataclass(frozen=True, slots=True) ObservationMatch(
    label, match_score, confidence, match_source, is_evidence); .value
@dataclass(frozen=True, slots=True) EvidencePaint(
    value, conf, is_evidence, match_score, match_source, label, observations)
    .is_miss ; .as_tuple() -> (value, conf, is_evidence)

match_observation(query, observation, *, matcher=None, config=None) -> ObservationMatch
paint_for_look(query, observations, *, matcher=None, config=None) -> EvidencePaint

class ValueEvidencePolicy(*, matcher=None, config=None)
    .paint(query, observations) -> EvidencePaint
    .evidence_count / .miss_count / .paint_count   (properties)
    .reset() -> None
```

---

## 6. Verification

* `tests/test_lock_on_verify.py` — **29 passed**
* `tests/test_false_positive_memory.py` — **17 passed**
* `tests/test_value_evidence.py` — **19 passed**
* combined: **65 passed**
* `ruff check` on all six new files — **All checks passed** (0 violations; the
  ci_gate ruff baseline of 7 is unchanged, new 0)
* `tests/test_vb_multiview_metric.py` — byte-unchanged, **10 passed**

### `scripts/ci_gate.py --tier commit` (2026-08-11T11:10:58Z, after all three cards)

```
[  FAIL] HARD  ruff              9 violation(s), baseline 7, new 2
                                 -> evals/nav_instruct/generator.py::RUF046;
                                    evals/nav_instruct/generator.py::RUF059
[  PASS] HARD  hard-safety       nav frozen baseline …v4-20260811T070536Z:
                                 collisions=0 false_arrival=0 | mutation panel clean |
                                 follow-bench 7 rows hard_collision_total all 0
[  PASS] HARD  frozen-digest-sentinels    4 immutable manifest(s) byte-identical to pin
[  PASS] HARD  latency-tail-ledger        6 metric series within 1.2x tail ceiling
[  PASS] HARD  follow-bench-jerk-ratchet  1.2187 <= 1.46244
[  PASS] HARD  model-off-non-inferiority  23 passed
[  PASS] HARD  frozen-digest-integrity    6 passed
[  PASS] HARD  mutation-panel-freshness   2 passed
[  PASS] HARD  latency-tail               6 passed
[  PASS] HARD  default-suite              3541 passed, 9 skipped, 35 deselected
RESULT: FAIL — 1 hard gate(s) red: ruff
```

### Attribution of the red (measured, not asserted)

1. Both new ruff fingerprints are in `evals/nav_instruct/generator.py`
   (`RUF046` at :1406, `RUF059` at :1484), inside a `+577 −1` diff that adds the
   `V4S_*` start lattice and target set — i.e. card **VS-6**'s deliverable
   (§6.1 ownership matrix: `evals/nav_instruct/generator.py` → Wave 2, VS-6).
   This lane never opened that file; it is in no VS-1/VS-2/VS-3 OWNS list.
2. Re-running the ratchet with that one file excluded gives
   **`new fingerprints excluding evals/nav_instruct/generator.py: []`** — this
   lane's ruff contribution is exactly zero. `ruff check` over my six files
   reports "All checks passed". The full-tree JSON shows none of my files at
   all.
3. Timing: at my fresh baseline run (10:51:11Z) ruff was PASS `new 0` and
   `evals/nav_instruct/generator.py` was unmodified (absent from `git status`).
   Its mtime is 07:07:20 local, i.e. it changed *after* my baseline and during
   this lane's work.

### Attribution of the suite delta

Collected: **3585** = baseline 3516 (3472 passed + 9 skipped + 35 deselected)
+ **65 from this lane** (verified: my three files collect exactly 65) + **4
from a sibling lane**. The only test file whose mtime is later than my baseline
run is `tests/test_nominal_stop_wiring.py` (07:07:55 local) — the AF-1 lane.
No test file of mine adds to any other file's count, and no existing test file
was edited by this lane.

`git status` shows my six new files and this status doc, and nothing else of
mine. The other modified/untracked paths in the tree belong to sibling lanes
(D15-A/B, J-A/B/C, AF-1, W2-EVAL/VS-6) and were not opened by this lane:
`configs/navigation/default.yaml`, `evals/companion*`, `evals/nav_instruct/*`,
`scripts/ci_gate.py`, `src/parcel_robot/core/*`, `navigation/pipeline.py`,
`navigation/velocity_shaping.py`, `runtime.py`, `tests/test_e4_evidence_seams.py`,
`src/parcel_robot/core/stop_ramp.py`, `navigation/person_keepout.py`,
`evals/nav_instruct/person_cell.py`, and their tests.

---

## 7. does_not_prove (lane level)

* **No wiring exists.** Nothing in the runtime, the pipeline, or any eval
  constructs these classes. Zero behaviour change is claimed for any flag, any
  episode, or any frozen row — the flag-off path cannot have moved because
  there is no flag yet. VS-4/VS-5 own that, and their gates own the evidence.
* **No arrival claim.** K0 is untouched: no epsilon widened, no arrival reason
  added, no goal special-cased. VS-1 produces verdicts that a wiring card may
  use to withhold or flush a PROPOSAL.
* **No real-camera evidence.** In the T0 eval arms "persistence" is the oracle
  frustum, which never hallucinates, so verify-on-approach passes trivially on
  real targets and phantom-rejection power is only exercised by injected
  traces (record §2.4). Real-camera persistence is hardware-deferred.
* **No statistical independence claim.** The view-admission quantum is a
  structural anti-self-confirmation rule derived from the scan spec, not a
  measured decorrelation length.
* **Empty-map == baseline is not proved here.** VS-3 makes it PROVABLE by
  defining `evidence_count`; proving float-identity on the v4 minival is
  VS-5's gate.
* **The V-B phantom traces are canned**, built from the record's measured
  description (constant bearing/range, no covariance shrink, the 4.7785 m B-05
  displacement). They are reproductions of a measured failure, not a fresh
  measurement of one.
