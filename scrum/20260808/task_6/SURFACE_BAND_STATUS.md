# SURFACE-ANCHORED next_to BAND — the owner's fallback, in its principled form · status

**Date:** 2026-08-09 · **Cards:** S-1 (one definition), S-2 (sidecars), S-3
(v2 → v3 re-freeze), S-4 (verify live), S-5 (suite).
**Owner directive (verbatim, as carried by the card):** *"expand the k0 band so
that the band is set around the entire bench"*.
**Entry state:** default suite 2871 passed / 0 failed / 14 skipped / 3 xfailed
(card B-2's exit); `sit next to the bench` xfail; `next_to` advertised by
`lamppost` only.

**The one-line result:** `NEXT_TO_BAND_M` is now a distance to the anchor's
**surface**, materialised into anchor-centre coordinates in exactly one function
that the arrival authority, the approach planner, the achievability predicate
and the owner band all call. The bench now **arrives, sits, and settles beside
the bench** — measured live, twice, `authority_category=agreement`, 1.51 m from
the bench's true surface. The NAV_INSTRUCT episode set is re-frozen v2 → v3
(digest `919a0fea…`, exactly the value card B-1 predicted without writing
anything), and the bridge says the band change flips **one** episode — the
bench — in both modes. The e2e pin does **not** flip on its own, for a reason
worth reading: the test's goal region is built from the *transcribed* landmark
table, and against the scene's own geometry the final pose is inside the band
while against the transcribed table it is **0.008 m outside**.

---

## S-1 — one definition

### The change, in one function

```python
# instructnav/scoring.py — the ONE place the surface band becomes a centre band.
def next_to_band_from_centre(anchor_footprint_m, band_m=NEXT_TO_BAND_M):
    return (band_m[0] + R, band_m[1] + R)
```

Every consumer the handoff listed goes through it, and nothing else applies an
offset:

| consumer | before | after |
|---|---|---|
| `scoring.object_next_to_goal_region` | stamped `(0.4, 1.5)` | stamps `next_to_band_from_centre(R)` |
| `scoring.owner_anchored_band_goal_region` | stamped `(0.4, 1.5)` | same call at `owner_footprint_m = 0.22` |
| `navigation.approach._next_to_planning_band` | `(0.4, 1.5)` inset | `next_to_band_from_centre(R)` inset; **`anchor_footprint_m` is a required argument** |
| `scoring.next_to_is_achievable` | `band_hi >= minimum_vicinity(R)` | `next_to_band_from_centre(R)[1] >= minimum_vicinity(R)` |
| `instructnav.relations.next_to_placement` | — | unchanged: it takes a centre band and never offsets |
| `navigation.relation_registry` | — | unchanged: it already delegates to the K0 builder |

### Why the band is materialised rather than flagged

The card suggested making the semantics explicit on `GoalRegion` rather than
adding a parallel band type. Both were considered; the band is **materialised**
at construction and `GoalRegion.band_m` keeps exactly one meaning — *a distance
to the anchor centre* — for three measured reasons:

1. **`near` is already encoded that way.** Every `near` band edge is
   `R + <composite>` (`object_near_envelope_m`). A mode flag would have made
   `relative_band` mean two things depending on a field, i.e. the D5 class one
   level up. Re-encoding `near` surface-relative was rejected too: `(x − R) + R`
   is not bit-identical in IEEE-754, so it would have perturbed every `near`
   goal by ~1e-16 for no gain.
2. **A materialised band cannot be re-read under the wrong convention.** A
   persisted v2 episode carries `[0.4, 1.5]` and re-scores as it always did; a
   v3 episode carries `[1.1338, 2.2338]` and is self-describing. A mode flag
   would have had to survive `metamorphic.transform_goal`,
   `mutation_panel`, `walk_with_me.runner`, `headless_city` and
   `GoalRegion.from_mapping` — five places where dropping it silently changes
   the meaning of a number. **None of those files needed a change** under the
   materialised design.
3. It reproduces the digest card B-1 measured in advance (below), which is an
   independent check the implementation is the one that was analysed.

`GoalRegion` now carries a class docstring stating the single convention and why
`anchor_footprint_m` is a *guard*, not a second copy of the band.

### The identity, asserted

`tests/test_next_to_approach_geometry.py::test_the_planner_and_the_arrival_authority_read_ONE_band`
— parametrised over R ∈ {0, 0.06, 0.3, 0.45, 0.58, 0.733757, 2.408}: the
verified band equals `next_to_band_from_centre(R)`, the planning band equals it
inset on both edges by `arrival_radius + stand_off_margin`, the planning band is
strictly inside the verified band, and the band's **width is R-independent**.
A companion test pins that `_next_to_planning_band` raises `TypeError` when the
footprint is omitted — a caller that forgot it would plan against a band the
arrival authority never verifies.

### The density raise travelled with it

`PLACEMENT_BEARINGS` 24 → **72** (`PLACEMENT_RADII` stays 5). Measured, both
halves, in
`tests/test_next_to_band_achievability.py::test_the_lattice_density_travelled_with_the_band_and_now_resolves_that_arc`:
the arc the surface band opens on `bench_1` is 3.7° wide (332.5–336.2°); 24, 48
and 64 bearings all miss it, 72 finds it, and the pose 72 finds is one
`object_next_to_goal_region` certifies. Raising it earlier would have found
nothing (no anchor had a non-empty set) while perturbing the one live `next_to`
case that passed — which is why it is landed here and not before.

### Achievability — before/after, every scene class

Derived from `scene_truth.json` at test time; `minimum_vicinity(R) = R + 0.32 +
0.80`.

| class | derived radii (m) | `minimum_vicinity` | old band hi (centre) | **old achievable** | new band hi (centre) | **new achievable** | sidecar `next_to` |
|---|---|---|---|---|---|---|---|
| lamppost | 0.060 | 1.180 | 1.500 | **yes** | 1.560 | **yes** | yes |
| planter | 0.450 | 1.570 | 1.500 | no (−0.070) | 1.950 | **yes** | **restored** |
| tree | 0.580 | 1.700 | 1.500 | no (−0.200) | 2.080 | **yes** | **restored** |
| bench | 0.733757 | 1.854 | 1.500 | no (−0.354) | 2.234 | **yes** | **restored** |
| building | 1.844–2.408 | 2.964–3.528 | 1.500 | no | 2.244–3.908 | **yes** | **no — declared semantic** |

**The finding the card did not expect, and it is the important one.** Under
surface anchoring `R` cancels out of the achievability inequality:

```
(R + band_hi) − minimum_vicinity(R) = band_hi − r_foot − target_surface_clearance = 0.38 m
```

so **no anchor size can make `next_to` empty any more** — not the bench, not a
building, not a synthetic 50 m anchor (pinned). That is not a weakening; it is
the defect being gone by construction, and it is exactly what "the band's width
is a property of the relation, not of the anchor" means.

Two consequences, both handled honestly rather than papered over:

* **`next_to_achievable_anchor_radius_m()` was renamed, not kept.** The same
  expression now reads `next_to_band_surface_slack_m()` and returns the same
  0.38 — as *the usable width of the band around an anchor of any size*, not as
  a maximum anchor radius. Keeping both names would have been the second
  authority this card exists to remove.
* **A genuinely unreachable affordance is still refused, and the refusal is now
  about the BODY.** `test_a_genuinely_unreachable_affordance_is_still_refused`:
  with a footprint of 0.9 m the slack is −0.2 m and `next_to_is_achievable` is
  `False` for *every* anchor including a 50 m one; a band of `(0.4, 1.0)` is
  refused at every anchor size and `(0.4, 1.12)` is admitted. The card asked for
  this proof "with a synthetic oversized anchor"; the measurement says an
  oversized anchor is no longer a refusal case, so the synthetic oversized
  anchor is pinned as **admitted** and the refusal is proved where it actually
  lives.
* **`building`'s sidecar exclusion can no longer be derived.** It is now
  declared in `city_block.semantics.yaml` as a **vocabulary** choice (landmark
  roles boundary/obstacle; "sit next to the building" is not a placement anyone
  asks for), the yaml says so in those words, and
  `test_the_one_class_without_next_to_declares_a_semantic_exclusion` asserts
  exactly that — every class in the scene *could* hold `next_to`, exactly one
  does not advertise it, and its reason is declared rather than measured. The
  2026-08-08 converse test ("no class may drop `next_to` for taste") was
  rewritten rather than deleted, because its old form would now demand that
  `building` advertise the relation. **Adding `next_to` to `building` is a
  product decision this card did not take**; it would change
  `voice/scene_reference.py`'s clarification offer and nothing else.

---

## S-2 — sidecars

* `configs/scenes/city_block.semantics.yaml`: `bench`, `tree`, `planter` regain
  `next_to`, each with the measured reason and the date it was removed and
  restored. `building`'s rationale is rewritten as declared-semantic (above).
* `configs/scenes/generated/val_unseen_9101{1..5}.semantics.yaml`: re-emitted
  through `scene_gen.semantics_sidecar_text()` and validated by the real loader
  (`_validate_sidecar`) before writing. **Not hand-edited.**

User-visible effect, measured through `voice/scene_reference.py`'s clarification
offer: a bench is again *"I can go to it, sit next to it, or walk towards it"*
(same for tree and planter); a building is still *"I can go to it or walk
towards it"*. `tests/test_owner_and_settle_plans.py::test_the_offer_names_only_relations_the_class_actually_affords`
carries both directions and both history entries.

---

## S-3 — the v2 → v3 re-freeze

Full record: [`evals/nav_instruct/EPISODES_V3_CONTINUITY.md`](../../../evals/nav_instruct/EPISODES_V3_CONTINUITY.md).

**v1 and v2 are byte-identical.** Digests `cf4d5384…` / `a17c04db…` unchanged;
no file under `episodes/v1/` or `episodes/v2/` was written; every
`object_relative` goal in both still carries `band_m == (0.4, 1.5)`, asserted
directly rather than only via the digest; the ledger's first 11 lines are
byte-identical (`7c131895…`, which contains the v2-era 9-line prefix
`dab60242…` unchanged).

This is the **first re-freeze triggered by a change in `src/`**, so the frozen
sets needed a new kind of protection: `EpisodeSetSpec` gained
`next_to_band_reference`, and `generator._superseded_centre_anchored_next_to_region`
reproduces the encoding v1/v2 were frozen under — one place, unreachable for a
`surface` version, pinned by both digests.

| | v2 | **v3** |
|---|---|---|
| digest | `a17c04db…` | **`919a0fea836363a6f6d04d3fb186b0dcb493aa6c76357d8af2b0c05408c556aa`** |
| files | `episodes/v2/` | `episodes/v3/` (25 + manifest) |
| `next_to` band | anchor **centre** | anchor **SURFACE** |
| everything else | — | identical |

`919a0fea…` is **exactly** the digest card B-1 measured in advance by
monkeypatching the builder. An independent implementation reproducing a
predicted sha256 is the strongest available check that this is the change that
was analysed.

### Bridge — `results/bridge_v2_v3.json`, 4 cells in one process

| mode | correction | SR before | SR after | Δ SR | Δ mean dtg (m) | K0 predicate flips |
|---|---|---|---|---|---|---|
| baseline | (d) surface-anchored `next_to` | 0.16 | **0.20** | **+0.04** | −0.1178 | `nav-object_relative-A-00` |
| candidate | (d) surface-anchored `next_to` | 0.08 | **0.12** | **+0.04** | −0.1178 | `nav-object_relative-A-00` |

Collisions 0 in every cell. `false_arrival` **2 → 1** in both modes.

Per-episode dtg for the only family that moved (baseline / candidate where they
differ):

| episode | v2 | **v3** |
|---|---|---|
| `A-00` sit next to the bench | 0.7267 / 0.7266 | **0.0000** |
| `B-05` wait by the bench | 2.2173 | 1.4835 |
| `C-10` stand next to the seat | 8.2040 | 7.4702 |
| `D-15` go next to the planter | 4.4652 / 4.7531 | 4.0152 / 4.3031 |
| `E-20` absent target | 55.2003 / 53.9203 | 54.9003 / 53.6203 |

### The prediction: confirmed on flips, refuted on SR

Card B-1's read-only re-scoring of the frozen v2 traces predicted *"exactly one
episode's K0 arrival predicate flips — the bench — with SR unchanged"*.

* **Confirmed:** exactly one flip, it is `nav-object_relative-A-00`, in **both**
  modes. No other episode's predicate moved either way, and only
  `object_relative` goals moved at all (asserted).
* **Refuted:** SR moves **+0.04 in both modes** (baseline 4/25 → 5/25,
  candidate 2/25 → 3/25). On a fresh run the bench episode is a genuine
  success — final pose inside the band at dtg 0.000, and it *holds*. The
  prediction was made against 2026-08-08 recorded traces in which the hold
  never accumulated.
* **U32 consequence:** the row that left `false_arrival` is the bench. It was a
  false arrival *because the band was wrong*, not because the navigator lied.

`bridge_v2_v3.json` records `predicted_vs_measured.prediction_confirmed: false`
with per-mode detail, and a test pins that it says so.

### Eval integrity

`tests/test_nav_instruct_episodes_v3.py` (13 cases): frozen-digest pins for v1
and v2 *plus* a direct assertion that their `next_to` goals still carry the
centre band; regeneration diff over the checked-in v3 files; oracle isolation
(v3's table **is** the derived section and equals v2's); only-`object_relative`
moved and by exactly R; v3 goals equal today's `object_next_to_goal_region`
output while v1/v2's do not; ledger rows declare `baseline_version: v3`; the
bridge artifact isolates the change and reports the refuted prediction.
`tests/test_nav_instruct_episodes_v2.py` is untouched and still green.

### The one other artifact that had to move

`evals/walk_with_me/freeze/manifest.json` embeds a goal built by the same K0
builder (`wwm-lamppost-standoff`). It is derived, so it was **regenerated
through `walk_with_me.generator.write_frozen_manifest`, never hand-edited**:

| | before | after |
|---|---|---|
| freeze digest | `fc24837ce23b23cb5c87a7c2ccbb70df396a7870159802719069efc95ed6deab` | `d9487ce70602d69d117ef90e937546120c1c81fb03cb6908c623f18c6ff401da` |
| band | `[0.4, 1.5]` | `[0.46, 1.56]` |

Seed unchanged (`20260805`), so the superseded manifest is exactly
`generate_frozen_pack(seed=20260805)` under the old band. Its **ledger row and
report JSON were not touched** and still name `fc24837c…`, which is the correct
record of what that run scored against. This lane does not own
`evals/walk_with_me/**` and made the minimum change that keeps its own
generator-equality test true — **reported, not assumed acceptable.**

---

## S-4 — verified live (`MUJOCO_GL=egl`, product path, static city)

### The bench, `handle_text("sit next to the bench")`

Two pytest node runs and two instrumented runs over the same fixture and the
same `handle_text` path.

| run | outcome | detail | elapsed | final pose | d(bench centre) | d(circumscribed surface) | **d(true bench surface)** | in new band | posture | settled | authority |
|---|---|---|---|---|---|---|---|---|---|---|---|
| probe 1 | **`succeeded`** | `safe_pose_stop_verified` | 21.0 s | (−0.6232, +1.8395) | **2.2329 m** | 1.4991 m | **1.5088 m** | **yes** (margin 0.0009) | **`sit`** | True | **`agreement`** |
| probe 2 | **`succeeded`** | `safe_pose_stop_verified` | 21.0 s | (−0.6222, +1.8388) | **2.2319 m** | 1.4981 m | **1.5077 m** | **yes** (margin 0.0019) | **`sit`** | True | **`agreement`** |
| pytest node ×2 | **XFAIL** (non-strict) | — | 27 s, 108 s pair | | | | | | | | |

`SitNextToOutcome` on both probes: `success=True`, `in_next_to_band=True`,
`sit_posture=True`, `settled=True`, `detail="success"`. Both authorities agree
the robot arrived. The two runs agree to 1 mm.

Compare card B-1's measurement of the same command 24 hours earlier:
`failed` / `semantic_target_unreachable`, 45.0 s, ending 2.2395 m from the bench
centre — **0.74 m outside the old band and 4 cm outside the new one**. The body
was already going almost exactly where the wider band calls arrival; what
changed is that the planner now has a pose to aim at and the verifier agrees
with it.

### Why the pytest node is still XFAIL — and it is not the robot

`tests/test_voice_nav_e2e.py` builds the bench goal from
`_LANDMARKS["bench_1"]`, which is the **transcribed** landmark table: centre
(−2.5, **3.0**), radius **0.7**. The scene's own geometry (Wave 0's `derived`
section, and what the sim actually simulates) is centre (−2.5, **3.045**),
radius **0.733757**.

| table | band (centre coords) | d(centre) at (−0.6222, 1.8388) | verdict |
|---|---|---|---|
| **derived** (the scene) | (1.1338, 2.2338) | 2.2319 | **inside**, distance-to-region **0.0000** |
| transcribed (the test) | (1.1000, 2.2000) | 2.2078 | outside by **0.0078 m** |

That is the exact defect NAV_INSTRUCT corrected in v2 (correction (a)) and this
e2e file never did. **The pin fails on a 7.8 mm eval-spec artefact**, not on
behaviour.

### The lamppost (hard gate — stays green)

| run | outcome | detail | elapsed | final pose | d(centre) | band | in band | posture | settled | authority |
|---|---|---|---|---|---|---|---|---|---|---|
| pytest node | **PASSED** | | (in the 108 s trio) | | | | | | | |
| probe | **`succeeded`** | `safe_pose_stop_verified` | 43.0 s | (−0.0884, +1.6231) | 1.5539 m | (0.46, 1.56) | **yes** (margin 0.0061) | **`sit`** | True | **`agreement`** |

`SitNextToOutcome`: `success=True`, `detail="success"`. The band moved out by
the lamppost's own 0.06 m and the pose moved with it; the case is green, as it
was before.

### The sidewalk

| run | outcome | detail | elapsed | final pose | distance-to-region | authority |
|---|---|---|---|---|---|---|
| pytest node | **PASSED** | | | | | |
| probe | **`succeeded`** | `navigation_goal_verified` | 31.0 s | (+1.5437, +2.6238) | 0.0 m (0.2238 m inside the polygon) | **`agreement`** |

### The pin text this card earned — the coordinator applies it

`tests/test_voice_nav_e2e.py` is not this card's file. **Two options, and the
first is the one the measurement supports.**

**(1) Flip to a hard gate — requires one line, in the coordinator's file.**
The case passes on the scene's own geometry. Change the goal region's source
from the transcribed table to the derived one:

```python
# tests/test_voice_nav_e2e.py — currently:
from evals.nav_instruct.generator import _LANDMARKS, _object_goal, _region_goal
_BENCH = _LANDMARKS["bench_1"]          # transcribed: (-2.5, 3.0), r=0.7
_LAMPPOST = _LANDMARKS["lamp_post_1"]

# proposed:
from evals.nav_instruct.scene_truth import derived_landmark_table
_DERIVED = derived_landmark_table()
_BENCH = _DERIVED["bench_1"]            # (-2.5, 3.045), r=0.733757 — the scene
_LAMPPOST = _DERIVED["lamp_post_1"]     # byte-equal to the transcribed entry
```

`lamp_post_1` is byte-equal between the two tables (that equality is what W0-D
used to prove the derivation is real), so this cannot move the lamppost cases.
With that change, delete the `@pytest.mark.xfail(...)` block on
`test_sit_next_to_the_bench_settles_beside_it_in_a_sit` entirely. Measured
justification to put in the commit: *"n=2 live, `succeeded` /
`safe_pose_stop_verified` in 21.0 s, final pose (−0.622, 1.839), 2.232 m from
the bench centre = 1.508 m from its true surface, inside the K0 band, posture
`sit`, settled, both authorities in agreement."*

**(2) If the coordinator does not want to touch the landmark table in that file,
the pin stays xfail and its reason must be replaced**, because every sentence in
the current one is now false. Proposed reason, verbatim:

> PLACEMENT ONLY, and re-measured 2026-08-09 (card S-1). The old reason — "THERE
> IS NO ADMISSIBLE POSE" — was true and is now fixed: NEXT_TO_BAND_M is measured
> to the anchor's SURFACE (instructnav.scoring.next_to_band_from_centre), so
> bench_1's band is 1.134-2.234 m from its centre and its outer 0.38 m clears
> StandOffEnvelope.minimum_vicinity(0.734)=1.854 m. Measured live, n=2, product
> path, static city: the mission SUCCEEDS — 'safe_pose_stop_verified' in 21.0 s,
> final pose (-0.622,1.839), 2.232 m from the bench centre, 1.508 m from the
> bench's true surface, posture 'sit', settled, system and scorer authorities in
> agreement, SitNextToOutcome.detail='success'. THIS CASE FAILS ONLY ON AN
> EVAL-SPEC ARTEFACT: _BENCH here is _LANDMARKS["bench_1"], the TRANSCRIBED
> landmark table, whose centre (-2.5,3.0) and radius 0.7 disagree with the
> scene's own geometry (-2.5,3.045) and 0.733757 — the exact defect NAV_INSTRUCT
> fixed in its v2 re-freeze (correction (a)) and this file did not. Against the
> transcribed band (1.100,2.200) the measured pose is 0.0078 m outside; against
> the derived band (1.134,2.234) it is INSIDE, distance-to-region 0.0000.
> Flipping this pin needs no navigation work: read _BENCH from
> evals.nav_instruct.scene_truth.derived_landmark_table() (lamp_post_1 is
> byte-equal between the two tables, so the lamppost cases cannot move).

**No change to `tests/test_voice_nav_e2e.py` was made by this card.**

---

## S-5 — suite, lint, frozen artifacts

| check | result |
|---|---|
| `ruff check` on every file this card touched | **clean** (`src/parcel_robot/instructnav/`, `navigation/approach.py`, `navigation/relation_registry.py`, `evals/nav_instruct/`, `evals/walk_with_me/`, `configs/`, and all 9 test modules) |
| full default suite (`MUJOCO_GL=egl pytest tests/ -q`, includes the live `-m slow` e2e block) | **`2929 passed, 14 skipped, 3 xfailed, 0 failed, 0 xpassed`** (682.6 s) |
| mutation panel (nightly, 6 mutants) | **6/6 killed, 0 survivors** — including `arrival_radius_x2` and `inverted_relation`, the two the handoff said must still die against a wider band |
| `evals/companion/**` | **byte-identical** — neither read nor written |
| `evals/companion_nav/**` | **byte-identical** |
| `evals/external/**` | **byte-identical** |
| `evals/nav_instruct/episodes/{v1,v2}/**` | **byte-identical** |
| ledger first 11 lines | **byte-identical** (`7c131895…`) |
| frozen v1/v2 report JSONs | **byte-identical** |

Entry was 2871 passed; the tree gained 58 tests (this card's ~30 plus a
concurrent voice lane's). **0 failed, 0 xpassed** — in particular the bench pin
did not become a false green, and the three xfails are the same three as at
entry (bench sit, sidewalk traffic, `test_authority_half_scale_smoke`'s
scale-covariance pin). The run shared the machine with up to eleven concurrent
`pytest tests/` processes from another lane and still came back clean.

*(Two docstring-only edits landed after the run started —
`scoring.evaluate_sit_next_to` and `scoring.next_to_band_from_centre`. No
statement changed; `test_instructnav_scoring.py`,
`test_next_to_band_achievability.py` and `test_scene_semantics.py` were re-run
green against the final bytes, 52 passed.)*

---

## Files touched

| file | change |
|---|---|
| `src/parcel_robot/instructnav/scoring.py` | `next_to_band_from_centre` (the one definition); `object_next_to_goal_region` and `owner_anchored_band_goal_region` materialise through it; `next_to_is_achievable` restated; `next_to_achievable_anchor_radius_m` → `next_to_band_surface_slack_m`; `GoalRegion` class docstring stating the single band convention |
| `src/parcel_robot/instructnav/relations.py` | `PLACEMENT_BEARINGS` 24 → 72 with the measurement; `next_to_placement` docstring: band is centre-coordinate, offsets belong to the caller's one definition |
| `src/parcel_robot/instructnav/__init__.py` | re-exports follow the rename |
| `src/parcel_robot/navigation/approach.py` | `_next_to_planning_band` takes a **required** `anchor_footprint_m` and insets the materialised band; call site passes the candidate footprint |
| `configs/scenes/city_block.semantics.yaml` | `bench`/`tree`/`planter` regain `next_to`; `building`'s exclusion restated as declared-semantic |
| `configs/scenes/generated/val_unseen_9101{1..5}.semantics.yaml` | re-emitted via `scene_gen.semantics_sidecar_text()` |
| `evals/nav_instruct/generator.py` | `EPISODE_SET_V3`; `EpisodeSetSpec.next_to_band_reference`; `_relative_goal` is version-aware; `_superseded_centre_anchored_next_to_region` |
| `evals/nav_instruct/runner.py` | `ARRIVAL_RULE_FOR_VERSION["v3"]` (v2's rule, unchanged) |
| `evals/nav_instruct/bridge_v2_v3.py` | **new** — spec + measured bridge, one correction, plus `predicted_vs_measured` |
| `evals/nav_instruct/episodes/v3/` | **new** — 25 episodes + manifest, written through the generator |
| `evals/nav_instruct/EPISODES_V3_CONTINUITY.md` | **new** |
| `evals/nav_instruct/README.md` | v3 row, v3 default invocation, `bridge_v2_v3` entry |
| `evals/nav_instruct/results/` | 2 new report JSONs, 2 appended ledger rows, `bridge_v2_v3.json`, `mutation_panel.json` (re-measured) |
| `evals/walk_with_me/freeze/manifest.json` | regenerated through its own generator (digest `fc24837c…` → `d9487ce7…`) |
| `tests/test_next_to_band_achievability.py` | rewritten: the superseded band is named as such, the fix is measured in the live scene, the density pair is asserted, refusal is proved on the body |
| `tests/test_next_to_approach_geometry.py` | the ONE-band identity test; required-footprint test; the 7 cm witness restated in the new coordinates |
| `tests/test_scene_semantics.py` | achievability check unchanged in strength; break-even test becomes the R-cancellation + body-refusal test; converse test becomes the declared-semantic-exclusion test |
| `tests/test_relation_registry.py` | the building `next_to` emptiness test inverted, with the reason; JEPD gap re-measured |
| `tests/test_k0_arrival_authority.py` | the eval/pipeline/approach identity is checked against **v3**, plus a pin that v1 does *not* agree |
| `tests/test_instructnav_compound_predicates.py` | `_beside_bench` materialises through the one definition |
| `tests/test_owner_and_settle_plans.py` | offer test: bench/tree/lamppost positive, building negative, both history entries recorded |
| `tests/test_nav_instruct_episodes_v3.py` | **new**, 13 cases |
| `scrum/20260808/task_6/SURFACE_BAND_STATUS.md` | this file |

**Not touched:** `runtime.py`, `voice/**`, `voice_pipeline.py`, `brain/**`,
`core/**`, `authority.py`, `configs/robot.yaml`, `configs/navigation/**`,
`navigation/reactive_safety.py`, `navigation/collision.py`,
`navigation/grid_planner.py`, `navigation/pipeline.py`,
`tests/test_voice_nav_e2e.py`, `tests/test_embodied_plan_eval.py`,
`tests/test_duplex_v1.py`, `evals/companion/**`, `evals/companion_nav/**`,
`evals/external/**`, `evals/nav_instruct/episodes/{v1,v2}/**`.

---

## The safety argument

Nothing in the safety chain was touched, and the test that says so is still in
place. `reactive_safety.py`, `collision.py`, `grid_planner.py`, `authority.py`,
`configs/robot.yaml` and `configs/navigation/default.yaml` are unmodified; no
terminal-clearance relaxation was introduced anywhere.
`test_the_unconditional_gate_still_zeroes_translation_at_that_clearance` still
asserts that at 0.331 m footprint-to-surface the gate returns `vx == vy == 0.0`
and `note == "stopped"`, through both the obstacle and the person channel.

This change is an **arrival-verification** change. It widens the set of final
poses the scorer and the navigator agree to call "beside it"; every one of those
poses still has to clear the same 1.20 m solver clearance and pass the same
unconditional gate on the way in. The live bench pose sits **1.508 m from the
bench's true surface** — 0.54 m outside the reactive gate's own 0.97 m
centre-to-surface envelope, not inside it.

---

## Non-claims

1. **The bench arrives on a sliver.** The admissible arc under the planning band
   is 3.7° wide off the bench's **east short end**, with ~0.006 m of pedestrian
   margin at the nearest-to-spawn point. Two live runs found it and agree to
   1 mm, but "possible" is not "robust", and it is the east end rather than the
   front because `pedestrian_5`/`pedestrian_7` box in the south face and
   `bldg_1`/`bldg_2` box in the north.
2. **Achievability is now anchor-independent, which is a bigger change than the
   card anticipated.** Every class in the scene, including buildings, would pass
   the predicate. The `building` exclusion is a declared vocabulary choice and
   nothing measures it.
3. **`R* = 0.38 m` did not disappear, it changed meaning.** Anyone quoting "next
   to is achievable up to 0.38 m" after today is quoting a retired function.
4. **The anchor is still a circumscribed circle.** For the 1.4 × 0.44 m bench
   that overstates the half-depth by 0.51 m, so "0.4–1.5 m from the surface" is
   0.4–1.5 m from the *circumscribing circle* — the live pose is 1.499 m from
   that circle and 1.509 m from the real box. A true Minkowski band around the
   real footprint would be better and is a much bigger change; not proposed.
5. **The e2e pin was not flipped by this card**, because the file is the
   coordinator's. The measurement says it should flip *and* that flipping it
   needs a one-line eval-spec correction, not navigation work.
6. **The +0.04 SR in the bridge is one episode**, and it is the episode whose
   goal region changed. Nothing about the navigator got better.
7. **n = 1 run per bridge cell**, n = 2 live per bench/lamppost case, n = 1 live
   for the sidewalk. The NAV_INSTRUCT runner is effectively deterministic
   (measured repeat sd 1.9e−5 m, card V-3b); the live product path is not, and
   two runs are two runs.
8. **`walk_with_me`'s freeze moved and this lane does not own it.** Reported
   above with both digests and the reasoning; its ledger row and report were
   left byte-identical and now name a superseded digest.
9. **`mutation_panel.json` was re-measured and overwritten.** It is a diagnostic
   (`frozen_baseline: false`), it still reports 6/6 killed, and the panel still
   runs against the **v2** episode set — moving it to v3 was out of scope.
