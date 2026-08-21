# PG-2 — an answer key a sensor can actually measure · status

**Card:** `scrum/20260821/task_7/README.md` · **Executor:** Claude Opus ·
**Auditor:** Fable (DEFERRED — this doc is written to be audited cold, weeks
from now, with nobody to ask) · **Date:** 2026-08-21

---

## 0. Headline

The card asked for a surface-based ground-truth convention, per-class scoring
rules that discriminate, a required null control, an arrival reconciliation, and
a proper regeneration. All five landed. Then the re-grade of the bench's own
120-frame run said something the card did not anticipate, and it is the most
important number in this document:

> **Fixing the answer key does not turn building queries green. It turns them
> from a WRONG FAIL into an HONEST "uninformative".**

| query | old convention | new statistic | null control | new verdict |
|---|---|---|---|---|
| "the building" (Arm A) | 1.97 m — **FAIL** at the 0.30 m budget | **0.048 m** to the facade, inside budget | p = **0.786** | **UNINFORMATIVE** |
| "the building" (Arm B) | 1.95 m — **FAIL** | **0.160 m**, inside budget | p = **0.932** | **UNINFORMATIVE** |

The convention change is real and it works: a fused entry on the facade scores
**4.8 cm instead of 1.97 m**, a 41× correction, and it is the same answer from
the same pipeline. But six buildings' footprints run most of the way around this
block, so a random map of 36–105 entries lands within a few centimetres of
*some* building surface roughly half the time. The corrected metric passes; the
null says it means nothing here. Under the old convention that query would have
been reported as a failure of the perception stack. Under the new one **with the
null control** it is reported as what it is: a question this scene cannot ask.

Three other results, all with denominators, in §4:

* **The large-region metric now discriminates where bare containment could
  not.** The bench's own null gave "the sidewalk" p = 1.00 in *both* arms — it
  could not tell them apart at all. The new rule separates them: **Arm A FAIL**
  (1.3% of the answering entry's evidence is on a sidewalk, worse than the 12.6%
  a random scatter gets) and **Arm B PASS** (79.5%, p < 0.002).
* **"The crosswalk" flips from a reported NAV hit to a FAIL**, and the null for
  it goes from p = 0.586 / 0.518 (uninformative) to **p = 0.000** (informative).
  The retrieved entry is simply not on the crosswalk in either arm.
* **A known live defect is cited, not re-reported, and the key is made immune to
  it.** `classify_place` files the bare token `door` as furniture rather than as
  a portal (R14-D1, already reported). Both classifications are measured to the
  surface, and `test_the_door_is_measured_to_its_surface_under_either_classification`
  pins that so PG-2's key cannot move whichever way R14-D1 is fixed.

**14 seeds, all RED for the right reason, all restored byte-identically.**

---

## 1. Gate — verbatim

### 1.1 Baseline, read before any edit

Read at 11:56:10Z. The R22–R26 chain plus PG-1 had just landed; the working tree
already carried the owner's concurrent uncommitted voice/realtime work (61
modified files at session start, none of them mine, none of them touched).

```
CI GATE — tier=commit  (2026-08-21T11:56:10Z)
==============================================================================
[  PASS] HARD  ruff                       7 violation(s), baseline 7, new 0
[  PASS] HARD  hard-safety                nav frozen baseline nav-instruct-v1-baseline-v4-20260811T070536Z: collisions=0 false_arrival=0 | mutation panel clean: collisions=0 no_false_arrival=True | mutation panel freshness: committed fields reproduce live = True | follow-bench: 7 row(s), hard_collision_total all 0 = True | walk_with_me: 1/2 row(s) with hard_collision_total, all 0 = True
[  PASS] HARD  frozen-digest-sentinels    4 immutable manifest(s) byte-identical to pin
[  PASS] HARD  release-parity             91 packaged asset(s) byte-identical to canonical source
[  PASS] HARD  latency-tail-ledger        latest row latency-20260810T082415Z-4d83035f: 6 metric series within 1.2x tail ceiling (rows=5, window=5)
[  PASS] HARD  follow-bench-jerk-ratchet  latest shipped row follow-bench-v1-20260811023618Z-93eba090.json: 1.2187 <= 1.46244 (baseline 1.2187 x 1.2)
[  PASS] HARD  assertion-evals            5 frozen fixture(s) reproduce 20 pinned finding(s) byte-identically; harness self-test 4/4 (3 broken agents failed, clean control passed); pass^1 green on f03_estop_pass_k; 3/3 committed run folder(s) present
[  PASS] HARD  tier-coverage              7634 collected = 7592 commit (-m 'not slow') + 42 nightly (-m 'slow'), no orphans, no overlap
[  PASS] HARD  model-off-non-inferiority  23 passed in 0.47s
[  PASS] HARD  frozen-digest-integrity    6 passed, 1 warning in 0.33s
[  PASS] HARD  release-parity-integrity   10 passed in 0.73s
[  PASS] HARD  mutation-panel-freshness   2 passed, 3 warnings in 4.27s
[  PASS] HARD  latency-tail               6 passed, 2 warnings in 0.31s
[  PASS] HARD  default-suite              7583 passed, 9 skipped, 42 deselected, 5 warnings in 289.64s (0:04:49)
==============================================================================
RESULT: PASS — every hard gate green.
  elapsed 309.1s
```

### 1.2 Final, after the last edit

Read at 12:37:48Z, after the last source edit (the `evidence_inside_fraction`
single-authority refactor, §3.4). Re-run at **12:44:13Z** after this document was
finished — identical verdicts and identical counts on every line (a markdown file
under `scrum/` cannot change a test outcome, but the house rule says re-run after
the final edit, so it was re-run; `gate_final3.txt`). The 12:37:48Z run is quoted.

```
CI GATE — tier=commit  (2026-08-21T12:37:48Z)
==============================================================================
[  PASS] HARD  ruff                       7 violation(s), baseline 7, new 0
[  PASS] HARD  hard-safety                nav frozen baseline nav-instruct-v1-baseline-v4-20260811T070536Z: collisions=0 false_arrival=0 | mutation panel clean: collisions=0 no_false_arrival=True | mutation panel freshness: committed fields reproduce live = True | follow-bench: 7 row(s), hard_collision_total all 0 = True | walk_with_me: 1/2 row(s) with hard_collision_total, all 0 = True
[  PASS] HARD  frozen-digest-sentinels    4 immutable manifest(s) byte-identical to pin
[  PASS] HARD  release-parity             91 packaged asset(s) byte-identical to canonical source
[  PASS] HARD  latency-tail-ledger        latest row latency-20260810T082415Z-4d83035f: 6 metric series within 1.2x tail ceiling (rows=5, window=5)
[  PASS] HARD  follow-bench-jerk-ratchet  latest shipped row follow-bench-v1-20260811023618Z-93eba090.json: 1.2187 <= 1.46244 (baseline 1.2187 x 1.2)
[  PASS] HARD  assertion-evals            5 frozen fixture(s) reproduce 20 pinned finding(s) byte-identically; harness self-test 4/4 (3 broken agents failed, clean control passed); pass^1 green on f03_estop_pass_k; 3/3 committed run folder(s) present
[  PASS] HARD  tier-coverage              7686 collected = 7644 commit (-m 'not slow') + 42 nightly (-m 'slow'), no orphans, no overlap
[  PASS] HARD  model-off-non-inferiority  23 passed in 0.48s
[  PASS] HARD  frozen-digest-integrity    6 passed, 1 warning in 0.34s
[  PASS] HARD  release-parity-integrity   10 passed in 0.73s
[  PASS] HARD  mutation-panel-freshness   2 passed, 3 warnings in 4.26s
[  PASS] HARD  latency-tail               6 passed, 2 warnings in 0.31s
[  PASS] HARD  default-suite              7635 passed, 9 skipped, 42 deselected, 5 warnings in 293.03s (0:04:53)
==============================================================================
RESULT: PASS — every hard gate green.
  elapsed 317.6s
```

### 1.3 Baseline → final

| | baseline 11:56:10Z | final 12:37:48Z | Δ |
|---|---|---|---|
| collected | 7634 | 7686 | **+52** (the new file) |
| passed | 7583 | 7635 | **+52** |
| **skipped** | **9** | **9** | **0** — the nine deliberately-skipped gate cells were not touched and no skip condition was edited |
| deselected | 42 | 42 | 0 |
| ruff | 7, baseline 7, new 0 | 7, baseline 7, new 0 | 0 |
| frozen-digest sentinels | 4 byte-identical | 4 byte-identical | 0 |
| release-parity | 91 packaged assets | 91 packaged assets | 0 |
| hard-safety | collisions 0, false_arrival 0 | collisions 0, false_arrival 0 | 0 |

**One intermediate run was RED and is recorded here rather than quietly
re-run.** At **12:23:20Z** every gate was green except ruff:

```
[  FAIL] HARD  ruff    8 violation(s), baseline 7, new 1 -> tests/test_scene_surface_truth.py::C408
```

`C408` — an `Unnecessary dict() call` at `tests/test_scene_surface_truth.py:601`,
where I had written `kwargs = dict(...)` to share arguments between two
`score_near_class` calls. Rewritten as a dict literal; nothing else changed. The
per-file `ruff check` I had been running while building did **not** catch it: the
gate runs `ruff check .` from the repo root, which picks up the project
configuration, and my per-file invocations did not. That is a lesson worth
leaving in the record — *check the way the gate checks*.

---

## 2. What landed

| File | Status | What |
|---|---|---|
| `evals/nav_instruct/scene_truth.py` | changed (+345 lines) | `ARTIFACT_VERSION` 1→2, `SURFACE_CONVENTION_VERSION`, `derive_scene_surfaces`, `_geom_footprint`, `surface_convention()`, `surface_table()`, `SurfaceDerivationError` |
| `evals/nav_instruct/scene_truth.json` | **regenerated** with the documented tooling | gains `surfaces` + `surface_convention`; **`derived`, `transcribed`, `transcription_deltas`, `scene`, `generator_landmark_ids` are byte-identical** (proof in §3.3) |
| `evals/nav_instruct/surface_scoring.py` | **NEW** (816 lines) | the two per-class rules, the geometry, the facade selector, `MappedArea`, `NullControl`, `LocalizationClaim` |
| `src/parcel_robot/navigation/arrival_semantics.py` | changed (+71 lines) | **one field** — `ArrivalPolicy.localization_target` — plus its two constants, its accessor, and the rationale text. No geometry, no predicate, no behaviour. |
| `evals/nav_instruct/README.md` | changed (+59 lines) | the convention, documented where a reader of the eval will find it |
| `tests/test_scene_surface_truth.py` | **NEW** (916 lines) | 52 cells |
| `scrum/20260821/task_7/PG2_STATUS.md` | **NEW** | this document |

### NOT TOUCHED — frozen by the card

`src/parcel_robot/realtime/**`, the yield policy, the detector paths
(`detection_adapter/**`, `instructnav/siglip2_onnx.py` — PG-1 owns those), the 9
skipped tests and every skip condition, `evals/nav_instruct/generator.py`, every
frozen episode set and manifest, `configs/scenes/*.semantics.yaml` and their
runtime mirrors. **No commit, no stage, no stash at any point** (`git diff
--cached` empty, `git stash list` empty at close).

Two files in `evals/nav_instruct/results/` (`ledger.jsonl` and the
`nav-instruct-v1-candidate-v4-20260821T102746Z.json` run) show as modified /
untracked. They are **not mine** — both carry a 06:27 mtime, hours before this
card's 11:56 baseline, and are part of the owner's concurrent work. The owner's
stack was never contacted — no GET, no POST, and no GPU work of any kind was
done by this card (see §4.1 for why the re-grade needed none).

---

## 3. The convention

### 3.1 What was wrong, restated from the evidence

`scene_truth.json` describes every object as a centre plus a **circumscribed**
radius. `bldg_1` is a 3.6 × 3.0 m box at (−4.5, 5.5) and its recorded radius is
**2.343 m** — the corner-to-centre distance. A depth camera standing on the
sidewalk sees one thing: the y = 4.0 face. The 2026-08-21 mapping bench measured
exactly that, 120 frames, two arms
(`scrum/20260821/perception/bench_mapping.md`).

The repo already knew. `evals/nav_instruct/cam_detector.py` compares OWLv2 to a
`SegTruthDetector` ruler rather than to the geom centre, and says why in its own
docstring: *"the common monocular surface-vs-centre offset both share"*. And the
v3 episode re-freeze had already moved the `next_to` band to be a distance to the
anchor's **surface** (`instructnav.scoring.next_to_band_from_centre`). PG-2 is
that same judgement applied to the answer key rather than worked around.

### 3.2 The shape of it

Artifact v2 adds two sibling sections:

```
surfaces[entity_id] = {
  "kind":        "object" | "region",     # the geometry kind
  "label":       "building",              # the scene class
  "place_class": "object",                # the arrival_semantics class
  "measure":     "surface" | "interior",
  "parts":            [ ... ],            # objects: the nearest-surface set
  "interior_polygon": [ [x, y], ... ],    # regions: the graded interior
}
```

with `parts` one footprint primitive per constituent geom —

| primitive | from | example |
|---|---|---|
| `rect` (4 corners) | box geoms | `bldg_1` → `[[-6.3,4.0],[-2.7,4.0],[-2.7,7.0],[-6.3,7.0]]` |
| `circle` (centre + radius) | cylinder / sphere geoms | `lamp_post_1` → centre (0.2, 3.15), r = 0.06 |

Derived contents, all 17 entities:

| entity | kind | place_class | measure | parts |
|---|---|---|---|---|
| `sidewalk`, `sidewalk_south` | region | region | interior | — (interior polygon) |
| `crosswalk` | region | region | interior | — (interior polygon) |
| `bldg_1` … `bldg_6` | object | object | surface | 1 rect each |
| `bench_1` | object | object | surface | 4 rects (`bench_back`, `bench_leg_l`, `bench_leg_r`, `bench_seat`) |
| `tree_1`, `tree_2` | object | object | surface | 2 circles (trunk + canopy) |
| `planter_1`, `planter_2` | object | object | surface | 1 circle |
| `lamp_post_1`, `lamp_post_2` | object | object | surface | 1 circle |
| `door_1` | object | object¹ | surface | 1 rect |

¹ `object`, not `portal` — the known R14-D1 defect. See §6.3. Both rows are
measured to the surface, and a test pins that.

**Why a nearest-surface SET and not one merged polygon.** The bench is four
separate box geoms. A depth ray hits whichever of them faces the robot, so the
honest target is "the closest of these four surfaces", not the union outline of a
shape nothing in the scene actually is. Concretely: the seat's front face is at
y = 2.78 and the instance's merged centre is at y = 3.045, so a robot on the
south side sees a surface **26.5 cm** from where the old key said the bench was.

**Why `surface_error_m` is unsigned.** A point in the middle of a solid is as
wrong as one floating outside it — no depth ray produced either. Seed S10 flips
this to "0 if inside" and reddens.

### 3.3 Nothing that existed moved

Machine-checked against `HEAD:evals/nav_instruct/scene_truth.json`:

```
keys added: ['surface_convention', 'surfaces']
derived              IDENTICAL
transcribed          IDENTICAL
transcription_deltas IDENTICAL
generator_landmark_ids IDENTICAL
scene                IDENTICAL
generated_by         IDENTICAL
do_not_hand_edit     IDENTICAL
artifact_version 1 -> 2
```

`git diff --numstat` on the artifact: **535 insertions, 1 deletion** — the one
deletion is the `"artifact_version": 1` line. The frozen NAV_INSTRUCT minival
digest `cf4d5384…` is unmoved and `test_frozen_minival_episode_digest_is_unchanged`
still passes; the generator reads `transcribed`, which no byte of this card
touched.

**Regenerated with the documented tooling, never hand-edited:**

```
$ .parcel/bin/python -m evals.nav_instruct.scene_truth --regenerate
{"regenerated": ".../evals/nav_instruct/scene_truth.json"}
$ .parcel/bin/python -m evals.nav_instruct.scene_truth --check   # "drifted": false
```

`scene_truth.json` is **not** a `DIGEST_SENTINELS` entry and **not** a packaged
asset — `test_ship_set_excludes_dev_only_and_ground_truth` excludes ground truth
from the ship set, and it passes unchanged. Release-parity stays at 91 packaged
assets; the four frozen sentinels are untouched. There was therefore no digest
to re-pin, and none was.

### 3.4 The per-class rules

| measure | statistic | passes when | why not something simpler |
|---|---|---|---|
| `surface` | `surface_error_m` = min unsigned distance to any part's footprint outline | ≤ **0.30 m** (`RECOGNITION_LOCALIZATION_BUDGET_M`, **imported** from `cam_detector.py`, never re-typed) | a centre-distance grades a correct sensor answer as a 1.5 m failure |
| `interior` | containment of the answer point **AND** `evidence_inside_fraction` over the answering entry's supporting points | contained **and** fraction ≥ **0.5** | bare containment scored 0.00 m against a *random* map (sidewalk p=1.00, crosswalk p=0.52) |

**One definition of the statistic.** `score_inside_class` calls the public
`evidence_inside_fraction()` rather than recomputing the same sum inline, so the
number a claim reports and the number a caller can measure by hand cannot come
apart. (This was a genuine second definition until the last edit of the card; it
was collapsed and the whole 120-frame re-grade re-run to prove the output is
byte-identical — `rescore.json` before vs after: **IDENTICAL**.)

`REGION_EVIDENCE_MAJORITY = 0.5` is a **convention floor, not a tuned number**:
"more of this entry's evidence is inside the region than outside it". A threshold
fitted to this scene would be exactly the kind of metric the bench caught — one
that looks decisive and measures nothing. The discrimination comes from the null
control, which is why the null is mandatory and this floor is only the coarse
half.

### 3.5 The null control, welded on

```python
@dataclass(frozen=True)
class LocalizationClaim:
    ...
    null: NullControl          # required field, NO default
    @property
    def verdict(self) -> str:  # a property — there is no field to overwrite
        if not self.raw_pass:            return VERDICT_FAIL
        if not self.null.beats_null:     return VERDICT_UNINFORMATIVE
        return VERDICT_PASS
```

Three things make "a number without its null control is not a result" a
structural fact rather than a convention someone has to remember:

1. `null` is a required constructor argument (seed S3).
2. `__post_init__` independently re-checks its type and its draw count, so the
   guard survives even if the annotation is loosened — which is exactly what
   seed S3's canary showed (see §5.1).
3. `verdict` is a property, so `uninformative` cannot be papered over (seed S4).

`MIN_NULL_DRAWS = 200` (seed S14), `NULL_ALPHA = 0.05` and `NULL_DRAWS = 500` are
the bench's own figures, kept so the two sets of p-values are directly
comparable. `MappedArea` is required and explicit — "random" is meaningless
without saying random *where*, and quietly widening the area is the easiest way
to make a null flattering.

**`also_satisfied_by`.** "The building" is six buildings. Both the observed
statistic and the null are taken over the whole class, because a null that may
only hit one of six targets is *lenient*: it understates how easy the question
was and so overstates the answer. Measured, same answer and same seed:
`class_null_p = 0.460` over 6 instances vs **0.095 over 1** — a scorer that
forgot the other five would have called that answer significant. Seed S12.

---

## 4. Evidence — the bench's 120-frame run, re-graded

### 4.1 Method, and what it deliberately does not re-run

The bench recorded, per query, **which map entry the text retrieval returned**
(`out/eval_report.json`, field `top_entry`). The re-grade loads the same map
(`out/map_arm{A,B}.npz`: centroids, 137 109 / 391 222 fused points, per-point
owner) and re-scores **those same answers** against the new key. Nothing was
re-embedded, no model was loaded and **no GPU was touched** — the owner's ~1 GB
of VRAM was never approached. That is the point: the pipeline did not change,
only what its answers are compared against.

Script: `scratchpad/pg2/rescore_bench.py`; full output
`scratchpad/pg2/rescore.json`. Answer key: the repo's regenerated
`scene_truth.json`. Scorer: the repo's `surface_scoring.py`. Null: 500 draws,
seed 20260821.

Validation that the re-grade reproduces the bench: the old-convention column
below is recomputed here from `derived`, and it matches the bench's own recorded
`error_m` on every row (e.g. Q1/A 0.97 vs 0.966, Q9/A 1.97 vs 1.968).

### 4.2 Arm A — MuJoCo segmentation as an oracle detector (105 entries, mapped area 445.2 m²)

| Q | query | measure | instance | NEW statistic | thr | p | **NEW verdict** | OLD err | OLD tight | OLD nav | bench p |
|---|---|---|---|---|---|---|---|---|---|---|
| Q1 | the sidewalk | interior | sidewalk(+south) | 0.013 frac | 0.5 | 1.000 | **FAIL** | 0.97 m | ✗ | ✓ | 1.000 |
| Q2 | the lamppost | surface | lamp_post_1 | 0.023 m | 0.30 | 0.014 | **PASS** | 0.04 m | ✓ | ✓ | 0.000 |
| Q3 | the bench | surface | bench_1 | 4.996 m | 0.30 | 1.000 | **FAIL** | 5.74 m | ✗ | ✗ | 0.070 |
| Q4 | the grass | surface | planter_2 | 0.193 m | 0.30 | 0.382 | **UNINFORMATIVE** | 0.26 m | ✓ | ✓ | 0.054 |
| Q5 | the coffee shop | — | — | — | — | — | *negative control, no ground truth* | — | — | — | — |
| Q6 | the crosswalk | interior | crosswalk | 0.245 frac | 0.5 | 0.000 | **FAIL** | 0.31 m | ✗ | ✓ | 0.586 |
| Q7 | the door | surface | door_1 | 8.002 m | 0.30 | 1.000 | **FAIL** | 8.26 m | ✗ | ✗ | 0.202 |
| Q8 | the tree | surface | tree_2 | 0.157 m | 0.30 | 0.492 | **UNINFORMATIVE** | 0.26 m | ✓ | ✓ | 0.070 |
| Q9 | the building | surface | bldg_3 | 0.048 m | 0.30 | 0.786 | **UNINFORMATIVE** | 1.97 m | ✗ | ✓ | 1.000 |

**Arm A: 1 PASS / 3 UNINFORMATIVE / 4 FAIL, denominator 8 answerable queries.**

### 4.3 Arm B — OWLv2 + SigLIP2 open vocabulary (36 entries, mapped area 174.7 m²)

| Q | query | measure | instance | NEW statistic | thr | p | **NEW verdict** | OLD err | OLD tight | OLD nav | bench p |
|---|---|---|---|---|---|---|---|---|---|---|
| Q1 | the sidewalk | interior | sidewalk(+south) | **0.795 frac** | 0.5 | **0.000** | **PASS** | 0.00 m | ✓ | ✓ | 1.000 |
| Q2 | the lamppost | surface | lamp_post_1 | 0.046 m | 0.30 | 0.006 | **PASS** | 0.01 m | ✓ | ✓ | 0.002 |
| Q3 | the bench | surface | bench_1 | **0.000 m** | 0.30 | 0.000 | **PASS** | 0.23 m | ✓ | ✓ | 0.036 |
| Q4 | the grass | surface | planter_1 | 0.129 m | 0.30 | 0.238 | **UNINFORMATIVE** | 0.32 m | ✗ | ✓ | 0.124 |
| Q5 | the coffee shop | — | — | — | — | — | *negative control* | — | — | — | — |
| Q6 | the crosswalk | interior | crosswalk | 0.053 frac | 0.5 | 0.000 | **FAIL** | 0.78 m | ✗ | ✓ | 0.518 |
| Q7 | the door | surface | door_1 | 6.946 m | 0.30 | 1.000 | **FAIL** | 7.35 m | ✗ | ✗ | 0.644 |
| Q8 | the tree | surface | tree_1 | 0.607 m | 0.30 | 0.838 | **FAIL** | 1.19 m | ✗ | ✓ | 0.132 |
| Q9 | the building | surface | bldg_2 | 0.160 m | 0.30 | 0.932 | **UNINFORMATIVE** | 1.95 m | ✗ | ✓ | 0.968 |

**Arm B: 3 PASS / 2 UNINFORMATIVE / 3 FAIL, denominator 8.**

For comparison, the bench's own headline for Arm B was **7/8 at NAV tolerance,
3/8 at the 0.30 m budget, 2/8 beating its null**. The corrected convention plus
the mandatory null gives **3/8 pass** — and it is a *different* 3: the sidewalk
joins the lamppost and the bench, while the crosswalk and the tree, which the old
NAV column called hits, do not.

### 4.4 What each verdict change actually says

* **Q9 "the building", both arms: the convention was wrong AND the query is
  useless here.** 1.97 m → 0.048 m is the answer key correction working exactly
  as designed. Then the null: with six buildings whose footprints run most of the
  way round the block, **78.6% (Arm A) and 93.2% (Arm B)** of random maps of the
  same size put *some* entry at least as close to *some* building surface as the
  real map managed. So the corrected number cannot support a claim. Reporting it as a pass would have been a new, subtler version
  of the old mistake. **This is the card's null-control requirement earning its
  keep on the very query the card was written about.**
* **Q1 "the sidewalk": the large-region metric now discriminates.** Bare
  containment gave both arms 0.00 m and p = 1.00 — literally no information. The
  evidence rule separates them decisively. Arm A's retrieved entry sits at
  (−0.513, −1.284), in the road: **1.3%** of its 4 000 supporting points are on
  either sidewalk, against a null median of **12.6%** — *worse than random*, p =
  1.000. Arm B's entry at (−1.474, 2.646) has **79.5%** of its points on the
  sidewalk against a null median of 27.4%, p = 0.000. Same query, same metric,
  opposite verdicts, both defensible.
* **Q6 "the crosswalk": a reported hit becomes an honest failure.** The old
  metric scored boundary distance and called 0.31 m / 0.78 m a NAV hit, with a
  null (p = 0.586 / 0.518) that admitted it could not tell. The retrieved
  entries are at x = 4.16 and x = 4.63; the crosswalk spans x ∈ [2.35, 3.85].
  The answer point is **not contained**, so the rule fails it, and the null is
  now sharp (p = 0.000, null median 0.008–0.020) — the metric is informative and
  the answer is wrong.
* **Q3 "the bench", Arm B: 0.231 m → exactly 0.000 m.** The fused entry lands
  *on* a bench surface. The old key's 23 cm was pure surface-vs-centre offset.
* **Q3/A, Q7 both arms: still FAIL, and that is the control.** Where the failure
  was retrieval rather than convention — a bench answer 5 m away, a door answer
  7–8 m away — the new key does not rescue it. A convention change that made
  everything pass would have been a worse bug than the one it fixed.

### 4.5 A correction to an inherited number

The card and `SYNTHESIS.md` §3 both say building entries land 1–3 cm from the
facade "**6/6 in the oracle arm, 5/6 in the open-vocab arm**". Read against the
bench's own `out/abstention_bias.json`, the second figure is two claims fused:

| | closer to face than to centre | within 3 cm of the face |
|---|---|---|
| Arm A | **6/6** | **6/6** (0.00–0.03 m) |
| Arm B | **5/6** | **4/6** — `bldg_4` is 1.79 m off and `bldg_5` 1.23 m off |

So "5/6" is the *closer-to-face* count, not the 1–3 cm count. The oracle arm's
6/6 is exact and is the claim the convention rests on. Recording this because the
looser reading would let a future reader believe the open-vocab arm localizes
buildings to centimetres, which it does not.

Two further caveats about the bench's facade measurement, both of which the
re-grade avoids: it picked the map entry **nearest the geom centre** (not the one
the query retrieved), and it measured **|Δy| only**, a 1-D proxy. §4.2–4.3 use
the retrieved entry and the full 2-D nearest-surface distance, so the numbers
there are not expected to equal `abstention_bias.json`'s and do not.

---

## 5. Seeds — 14, each RED for the right reason, each restored byte-identically

Protocol (house rule R9, session-B), identical for all fourteen: snapshot bytes
+ sha256 → **one** textual mutation → purge every `__pycache__` under `src/
scripts/ tests/ evals/` → **fresh-interpreter canary** (`python -B`,
`PYTHONDONTWRITEBYTECODE=1`) that *calls the live code* rather than reading its
text → run the named guards, require RED → restore in a `finally` → purge again
→ assert sha256 identity → second canary proving the mutation is gone → re-run,
require GREEN.

Harness `scratchpad/pg2/seed_harness.py`; results `scratchpad/pg2/seed_results.json`.
Run twice: once mid-build and again against the final shipped tree; the table is
the final run. The card names five seeds by hand — they are **S1** (surface field
dropped), **S2** (centre used for a `near`-class building), **S3** (null control
removed from a localization claim), **S5** (large-region metric reverted to bare
containment) and **S8** (a hand-edited digest).

| # | What is broken | File | RED | first failing test | GREEN after restore | sha identical |
|---|---|---|---|---|---|---|
| **S1** | **the surface field is dropped from the answer key entirely** | `scene_truth.py` | `1 failed, 1 passed` | `test_the_whole_artifact_still_equals_a_fresh_build` | ✓ | ✓ |
| **S2** | **a near-class building is measured to its CENTRE again** | `surface_scoring.py` | `1 failed, 13 passed` | `test_a_point_on_the_visible_facade_scores_centimetres[bldg_1]` | ✓ | ✓ |
| **S3** | **the null control becomes optional on a localization claim** | `surface_scoring.py` | `1 failed, 31 passed` | `test_a_localization_claim_cannot_be_built_without_a_null_control` | ✓ | ✓ |
| S4 | a claim that lost to chance is reported as a PASS | `surface_scoring.py` | `1 failed, 33 passed` | `test_a_statistic_that_passes_but_loses_to_chance_is_uninformative` | ✓ | ✓ |
| **S5** | **the large-region metric reverts to bare containment** | `surface_scoring.py` | `1 failed, 41 passed` | `test_evidence_scattered_over_the_map_does_not_beat_chance` | ✓ | ✓ |
| S6 | an inside-class claim is allowed with no supporting evidence | `surface_scoring.py` | `1 failed, 40 passed` | `test_bare_containment_of_a_point_cannot_carry_an_inside_class_claim` | ✓ | ✓ |
| S7 | the arrival table stops calling a region interior-measured | `arrival_semantics.py` | `1 failed` | `test_the_checked_in_surfaces_equal_a_fresh_derivation` | ✓ | ✓ |
| **S8** | **a hand-edited digest: one surface coordinate nudged in the artifact** | `scene_truth.json` | `1 failed` | `test_the_checked_in_surfaces_equal_a_fresh_derivation` | ✓ | ✓ |
| S9 | the rotated-box guard is removed: a wrong answer key is emitted | `scene_truth.py` | `1 failed, 6 passed` | `test_a_rotated_box_is_refused_rather_than_flattened` | ✓ | ✓ |
| S10 | surface error goes SIGNED: a point buried in a solid scores 0 | `surface_scoring.py` | `1 failed, 19 passed` | `test_the_geom_centre_fails_the_surface_budget_by_the_measured_margin[bldg_1]` | ✓ | ✓ |
| S11 | a multi-part object collapses to its first geom only | `surface_scoring.py` | `1 failed, 27 passed` | `test_a_multi_part_object_measures_to_whichever_part_faces_the_robot` | ✓ | ✓ |
| S12 | the class-level null narrows to one instance (a lenient null) | `surface_scoring.py` | `1 failed, 37 passed` | `test_a_class_query_lets_the_null_hit_any_instance_of_that_class` | ✓ | ✓ |
| S13 | the region interior stops tracking the derived polygon | `scene_truth.py` | `1 failed` | `test_the_checked_in_surfaces_equal_a_fresh_derivation` | ✓ | ✓ |
| S14 | the null draw floor is removed: a 1-draw p-value is accepted | `surface_scoring.py` | `1 failed, 32 passed` | `test_a_null_control_below_the_draw_floor_is_refused` | ✓ | ✓ |

Every row: `red=True`, `sha_identical=True`, `canary_changed=True`,
`green_after_restore=True`. **14/14 clean.**

### 5.1 Canaries worth quoting

They show the mutation was genuinely live, not merely written to disk.

```
S2   mutated: bldg1_facade=1.5300  bldg1_centre=0.0000  bench_front=0.2650  class_null_p=1.000
     clean  : bldg1_facade=0.0300  bldg1_centre=1.5000  bench_front=0.0000  class_null_p=0.460
S4   mutated: lost_to_chance_verdict=pass
     clean  : lost_to_chance_verdict=uninformative
S5   mutated: scattered_evidence_verdict=uninformative
     clean  : scattered_evidence_verdict=fail
S7   mutated: region=surface  object=surface  portal=surface  person=surface  unknown=surface
     clean  : region=interior object=surface  portal=surface  person=surface  unknown=surface
S9   mutated: rotated_box=EMITTED [-6.3, 4.0]        <- a silently WRONG answer key
     clean  : rotated_box=REFUSED SurfaceDerivationError
S10  mutated: bldg1_centre=0.0000                     <- standing inside the block scores perfect
     clean  : bldg1_centre=1.5000
S12  mutated: class_null_p=0.095 instances=1          <- 4.8x more "significant" than the truth
     clean  : class_null_p=0.460 instances=6
S14  mutated: one_draw_null=ACCEPTED
     clean  : one_draw_null=REFUSED SurfaceScoringError
```

### 5.2 One seed found redundancy, and it is worth knowing

**S3** loosens `null: NullControl` to `null: NullControl | None = None`. The
canary crashed rather than printing `claim_without_null=BUILT`, because
`__post_init__` *independently* refuses a claim whose `null` is not a
`NullControl` — so the claim is constructed and then immediately rejected at
runtime. The guard is genuinely two-layered: the type-level requirement and the
runtime check are separate, and either alone would still redden. Recorded
because a crashing canary looks like a broken seed until you read why, and the
"why" is a real property of the code.

**S7** reddened on `test_the_checked_in_surfaces_equal_a_fresh_derivation` rather
than on an arrival test, because flipping the region row makes
`derive_scene_surfaces` **raise** — the derivation fails closed rather than
emitting a region with no measurable interior. That is the intended behaviour
(`SurfaceDerivationError`, `evals/nav_instruct/scene_truth.py`), and the harness
runs with `-x`, so it stops at the first failure.

---

## 6. Arrival-semantics reconciliation (card work item 3)

### 6.1 The smallest touch, and why it is in `src/` at all

`arrival_semantics.py` gained **one field** on `ArrivalPolicy`:

```python
localization_target: str = LOCALIZATION_SURFACE   # region row overrides to INTERIOR
```

plus its two constants, the `LOCALIZATION_TARGETS` frozenset, the accessor
`localization_target(place_class)`, one line in `as_dict()`, and rationale text.
No geometry, no predicate, no planner reads it, and
`test_the_surface_convention_never_reaches_the_navigator` walks every `.py` under
`src/parcel_robot/` and reddens if any of them ever *imports* the eval scorer.

It lives here rather than in the eval because "what does arrival mean for this
class" already has an authority. A perception scorer that spelled its own
class → metric map would be a second one, free to drift. `surface_scoring.py`
holds no such map; the answer key records the measure and
`test_every_measure_is_read_from_the_arrival_table` re-derives it from
`classify_place` + `localization_target` for all 17 entities on every run.

The default is `surface` because that is the fail-safe: measuring an unknown
place's exterior can only be conservative, while assuming an interior asserts a
containment nobody established.

### 6.2 "Go to the building" — the reconciliation, measured

Three things are asserted, all from the scene's own numbers:

**(a) The navigator's goal is unchanged.**
`test_the_near_goal_region_for_a_building_is_still_built_from_the_centre` checks,
for **every** object in the scene, that the `goal_region` `city_semantics` hands
the navigator is exactly `object_near_goal_region(centre, circumscribed_radius)`.
For `bldg_1` that is a `relative_band` at **[3.463, 3.963] m from (−4.5, 5.5)**,
anchored on the centre, with `anchor_footprint_m = 2.343075`. The surface field
is graded against; it is **not** an anchor, and nothing plumbs it into a goal.

**(b) Targeting the facade agrees with what "go to the building" means.**
`test_go_to_the_building_stops_in_front_of_the_facade_it_can_see` samples 72
bearings × both band edges for all six buildings — **864 candidate terminals** —
and asserts each one is outside the footprint, clears the nearest surface by at
least the scene's own `target_min_surface_clearance_m` (**0.8 m**, read from the
object's metadata, not re-typed), and that `visible_facade()` from that pose
returns a real face of *that* building.

Measured on all six, 720 bearings × both band edges:

| building | near band from centre | min surface clearance on the band | terminals inside the footprint |
|---|---|---|---|
| `bldg_1` | 3.463 … 3.963 m | **1.120 m** | 0 |
| `bldg_2` | 2.964 … 3.464 m | **1.120 m** | 0 |
| `bldg_3` | 3.172 … 3.672 m | **1.120 m** | 0 |
| `bldg_4` | 3.313 … 3.813 m | **1.120 m** | 0 |
| `bldg_5` | 3.322 … 3.822 m | **1.120 m** | 0 |
| `bldg_6` | 3.528 … 4.028 m | **1.120 m** | 0 |

1.120 m for all six and not by luck: `object_near_envelope_m` gives a
`building` the `vicinity(radius)` stand-off, so the band's inner edge is always
`radius + 1.12` from the centre and the tightest point is the corner diagonal,
where the circumscribed radius touches the footprint. Worked example, `bldg_1`:
the facade is 1.5 m from the centre and the band starts at 3.463 m, so the robot
stops **1.96–2.46 m in front of the face it can see** and never inside the block.
1.120 m against a 0.8 m floor is 40% of margin.

So the facade is both the measurement target and the thing at the end of the
approach, without the facade ever becoming the goal anchor. That is the
reconciliation.

**(c) `inside`-class arrival is untouched, byte for byte.** Two independent
assertions:
`test_every_region_interior_is_byte_identical_to_its_derived_polygon` (answer key
side) and `test_region_goal_regions_handed_to_the_navigator_are_the_same_polygon`
(robot side — the polygon in `metadata["goal_region"]`). Plus
`test_inside_class_places_still_classify_and_terminate_inside`: every region
still classifies `region`, still terminates `inside`, still translates to the
`inside` planner relation. Seed S13 moves an interior polygon by 5 cm and reddens.

**Deliberate: the crosswalk's graded interior is the merged bounding box, not the
four painted stripes.** The stripes are `xw1..xw4`, four 0.3 × 2.4 m boxes;
`city_semantics._merge_crosswalk_regions` already unions them into
[2.35, −0.4]–[3.85, 2.0] and *that* is what the arrival authority contains.
Making the answer key stricter than the arrival predicate would have moved
`inside` arrival, which the card forbids. Recorded as a choice, not an oversight.

### 6.3 The door, and a defect this card did not fix

`classify_place` checks the caller-supplied scene vocabulary **as a whole phrase**
before it checks `PORTAL_WORDS` against the head noun. `city_block.semantics.yaml`
declares a class literally named `door` (card R14), so the bare token classifies
as `object`:

```
'door'             -> object      # with the live scene vocabulary
'the door'         -> portal      # article not stripped yet
semantic_goal_from_directive('go to the door', <live vocabulary>)
        -> place_class=object, do_not_cross=False
        -> without the vocabulary: place_class=portal, do_not_cross=True
```

This is **R14-D1**, already reported in `scrum/20260820/task_3/R14_STATUS.md`,
and the sidecar itself points at it in a comment. It is live on
`runtime._realtime_navigate` (the hosted `navigate_to` path, which passes
`_realtime_scene_vocabulary()`), it is a portal-etiquette defect and not a
measurement one, and it is outside this card's ownership. I reproduced it to be
sure it is still live; I did not touch it.

What PG-2 does is make its answer key **immune to whichever way it is fixed**:
`object` and `portal` are both measured to the surface, and
`test_the_door_is_measured_to_its_surface_under_either_classification` pins both
sides of the disagreement so the door's grading target cannot move underneath a
future fix.

---

## 7. Deviations from the card, with reasons

1. **`surfaces` is a sibling top-level section, not a field inside `derived`.**
   The card says "alongside the existing centre+radius". A sibling section is
   alongside, and it preserves something a field would have broken:
   `test_derivation_reproduces_the_landmarks_the_transcription_got_right`
   asserts three `derived` rows are *equal* to their hand-typed counterparts, and
   that equality is the half of the Wave-0 proof showing the derivation is real.
   A sibling section also leaves the generator, the frozen minival digest and
   `derived_landmark_table` reading byte-identical input.
2. **Regions carry `interior_polygon` and no `parts`.** See §6.2. Recording the
   four crosswalk stripes as the "true" surface would have created a target
   stricter than the arrival predicate and invited someone to reconcile them by
   moving arrival.
3. **Facades are computed, not stored.** The card says "facade polygon /
   nearest-surface set". The artifact stores the nearest-surface set;
   `visible_facade(surface, observer_xy)` derives the facade from it, because
   which faces are visible depends on where the robot stands and a stored polygon
   would be one frozen viewpoint's answer. One representation, all views derived.
4. **No digest was re-pinned, because none needed to be.** The card's work item 4
   is conditional ("*if* … digest-pinned"). `scene_truth.json` is not a
   `DIGEST_SENTINELS` entry, is excluded from the ship set as ground truth, and
   no scene semantics sidecar was touched at all. Release-parity and the four
   sentinels are green and unmoved.
5. **The re-grade re-uses the bench's recorded retrievals rather than re-running
   the models.** The question this card asks is a geometry question about
   answers that were already produced; re-embedding would have burned GPU for a
   number that could not change. It also means the comparison is exactly
   like-for-like: identical answers, two answer keys.
6. **The null for an `interior` claim scatters at most 1 000 points** even when
   the entry has 4 000. Fewer points widen the null, which can only raise p, so
   the reported p is an upper bound; every affected claim carries that sentence in
   its own `notes` field. (The 4 000 is the bench's own reservoir — `build_map.py`
   uniformly subsamples per entry at seed 0 — not a cap I introduced.)
7. **One inherited number corrected**, §4.5.

---

## 8. Open risks, owner-gated questions, and what this does NOT prove

### does_not_prove

* **Nothing here is evidence about real-world perception.** The re-graded run is
  on flat-shaded untextured MuJoCo primitives; `SYNTHESIS.md` §2 is decisive that
  no perception number measured in this world means anything (0/69 person recall
  across three detectors, 127–145/156 on real photos). What the re-grade *does*
  establish is a property of the **answer key**, which is pure geometry and
  therefore does transfer: a depth camera on real hardware will land on facades
  too, and the old key would have failed it there as well.
* **The convention is proved on one scene with one geom vocabulary.** Every
  footprint in `city_block.xml` is an axis-aligned box, a cylinder or a sphere.
  A mesh, a rotated box or a capsule has no primitive today; the derivation
  raises rather than guessing (seed S9), so the failure mode is loud, but the
  coverage is genuinely narrow.
* **`person` is measured to the surface and has never been exercised** — the
  scene's owner mocap capsule is not a semantic entity, so no answer-key row uses
  that row of the arrival table.
* **The 0.5 evidence floor has not been validated against a corpus of correct
  answers.** It is a convention, and the two real cases it saw scored 0.795 and
  0.013 — far from the boundary. A pipeline that legitimately sits near 0.5 has
  not been observed and would deserve a second look at the floor.

### Owner-gated

1. **"The building" is not a usable localization query in this scene, even with
   the fix.** Six buildings, p = 0.786 / 0.932. Options, none taken here:
   (a) require the *correct instance* rather than any instance of the class,
   which makes the query discriminating but changes what the query means;
   (b) accept that building queries are ungradeable on `city_block` and stop
   reporting them; (c) fix the world (SYNTHESIS §5 fork). This wants a decision
   before anyone quotes a building number again.
2. **`transcribed` still disagrees with `derived` in 7 pinned places** (bench
   position and radius, `bldg_1` radius, crosswalk and both sidewalk polygons,
   `tree_1` radius). `surfaces` is derived from the scene, so a consumer that
   mixed `transcribed` positions with `surfaces` would be mixing two conventions.
   Nothing does that today. The clean fix is the re-freeze that adopts `derived`,
   which is a separate card.
3. **R14-D1 is still live** (§6.3). Not mine to fix, but it is a *safety*
   etiquette defect on the hosted lane and it has now been independently
   reproduced twice.

### Risks I would watch

* `surface_scoring.py` is pure Python and the `near`-class null is
  O(draws × entries × instances × parts). The Arm A re-grade (105 entries, 6
  building instances, 500 draws) took minutes, not seconds. Fine for an offline
  eval, wrong shape for anything interactive.
* `MappedArea` is an axis-aligned box. If a future map's coverage is strongly
  non-rectangular, the box overstates the mapped area and makes every null
  *easier* to beat — i.e. flattering. A convex-hull area is the obvious next
  primitive and is deliberately not in this card.

---

## 9. Reproduce everything in this document

```bash
cd /home/jaewoo-jang/Desktop/Projects/Parcel

# the answer key, regenerated from the scene (never hand-edited)
.parcel/bin/python -m evals.nav_instruct.scene_truth --check      # "drifted": false
.parcel/bin/python -m evals.nav_instruct.scene_truth --regenerate

# the convention's own tests
.parcel/bin/python -m pytest tests/test_scene_surface_truth.py -q

# the untouched contracts it must not have moved
.parcel/bin/python -m pytest tests/test_nav_instruct_scene_truth.py \
    tests/test_arrival_semantics.py tests/test_portal_world.py \
    tests/test_scene_semantics.py -q

# the gate
.parcel/bin/python scripts/ci_gate.py --tier commit
```

Scratch artifacts (will not survive; every fact they carry is restated above):

* `scratchpad/pg2/rescore_bench.py` + `rescore.json` — the 120-frame re-grade
* `scratchpad/pg2/seed_harness.py` + `seed_results.json` — the 14 seeds
* `scratchpad/pg2/gate_baseline.txt` (11:56:10Z), `gate_mid.txt` (12:23:20Z, the
  ruff RED), `gate_final.txt` (12:30:19Z), `gate_final2.txt` (12:37:48Z, quoted
  in §1.2)
* prior bench, read-only: `scratchpad/perception/bench-semmap/out/`
