# NAV_INSTRUCT episode set v2 → v3 — continuity record

**Date:** 2026-08-09 · **Trigger:** card S-1, the owner's stated fallback
("expand the k0 band so that the band is set around the entire bench") in its
principled form · **Scope: exactly one correction, and no second.**

v1 and v2 are **immutable and untouched.** Their digests are still
`cf4d5384d1787d110cbc5a74e8b46699e6aa26eaaa576b1c24beb0fbb04adfbf` and
`a17c04dbec43a1749386c304060fb479a71f27d4b51b8c1b0fbb949753fc563d`, their
checked-in episode directories are byte-identical, the first eleven ledger lines
are byte-identical, and every default in `generator.py` still resolves to v1.
v3 has to be asked for by name.

| | v2 | v3 |
|---|---|---|
| episode digest | `a17c04db…` | `919a0fea836363a6f6d04d3fb186b0dcb493aa6c76357d8af2b0c05408c556aa` |
| episode files | `evals/nav_instruct/episodes/v2/` | `evals/nav_instruct/episodes/v3/` |
| landmark table | `scene_truth.json` → `derived` | **same** |
| class matching | word boundary | **same** |
| definite reference | instance visible from the start pose | **same** |
| arrival rule | `hold-or-trace-end-v1` | **same** |
| **`next_to` band reference** | **anchor CENTRE** | **anchor SURFACE** |
| episode ids | 25 | the **same** 25 |

The id set is unchanged, so the old→new mapping is total and 1:1;
`bridge_v2_v3.spec_bridge` asserts it and
`tests/test_nav_instruct_episodes_v3.py` pins the assertion.

**This re-freeze is the first one caused by a change in `src/`, not in the
eval.** That is why the frozen sets need protecting in a new way: v1 and v2's
goals were generated *through* `object_next_to_goal_region`, the builder that
changed. `EpisodeSetSpec` now carries `next_to_band_reference`, and
`generator._superseded_centre_anchored_next_to_region` reproduces the encoding
v1/v2 were frozen under — in one place, unreachable for any `surface` version,
and pinned by both digests.

## The one correction — (d), surface-anchored `next_to`

`NEXT_TO_BAND_M = (0.4, 1.5)` was a distance to the anchor's **centre**, while
every stand-off authority in `parcel_robot.authority` is a distance to its
**surface**. For an anchor of circumscribed radius `R` that made the band's
usable width `1.5 − minimum_vicinity(R)`, i.e. it *shrank as the anchor grew*
and went empty above `R = 0.38 m`. On `city_block` that was every class except
the lamppost, and it is the whole reason `sit next to the bench` had no
admissible pose anywhere on the bench's perimeter (card B-1: 3601 bearings ×
551 radii, best slack −0.382 m).

v3 measures the band from the surface: the K0 region a `next_to` goal carries is
`(0.4 + R, 1.5 + R)` from the centre. The band's 1.1 m **width is now a property
of the relation**, not of the anchor.

It is materialised in exactly one function,
`instructnav.scoring.next_to_band_from_centre`, which the arrival authority, the
approach planner, the achievability predicate and the owner-anchored variant all
call. The episode payload stores the *materialised* band, so a v3 episode file
is self-describing and a v2 file re-scores under v2 semantics with no mode flag
anywhere.

## Per-episode mapping — every row that moved

5 of 25 rows moved. All five are `object_relative`; the other four families are
byte-identical to v2, which is the strongest statement available that (d) did
not leak. `shortest_path_m` moves with the goal because the generator's A\* runs
to the band's inner edge.

| episode id | instruction | anchor | R (m) | v2 band | **v3 band** | L (m) |
|---|---|---|---|---|---|---|
| `nav-object_relative-A-00-3efbba45` | sit next to the bench | `bench_1` | 0.733757 | (0.4, 1.5) | **(1.1338, 2.2338)** | 5.0 → 4.5 |
| `nav-object_relative-B-05-7d441aee` | wait by the bench | `bench_1` | 0.733757 | (0.4, 1.5) | **(1.1338, 2.2338)** | 4.0 → 3.5 |
| `nav-object_relative-C-10-0d3f5ebd` | stand next to the seat | `bench_1` | 0.733757 | (0.4, 1.5) | **(1.1338, 2.2338)** | 11.5 → 11.0 |
| `nav-object_relative-D-15-61f68ad6` | go next to the planter | `planter_1` | 0.450000 | (0.4, 1.5) | **(0.8500, 1.9500)** | 8.0 → 7.5 |
| `nav-object_relative-E-20-0c739ea2` | sit next to the bench (absent) | off-map | 0.300000 | (0.4, 1.5) | **(0.7000, 1.8000)** | 56.3003 → 56.0003 |

The digest this produces was **predicted in advance**: card B-1 measured
`919a0fea836363a6f6d04d3fb186b0dcb493aa6c76357d8af2b0c05408c556aa` by
monkeypatching the builder without writing anything, and the independent
implementation here reproduces it exactly.

## Bridge — the correction, measured

`evals/nav_instruct/results/bridge_v2_v3.json` (regenerate:
`.parcel/bin/python -m evals.nav_instruct.bridge_v2_v3 --run`).

All four cells (2 modes × 2 versions) measured **on one tree, in one process**.
No cell is differenced against a stored ledger row: the v2 rows were measured on
2026-08-08 code, and differencing against them would charge whatever landed
since to the band change.

| mode | correction | SR before | SR after | Δ SR | Δ mean dtg (m) | K0 predicate flips |
|---|---|---|---|---|---|---|
| baseline | (d) surface-anchored `next_to` | 0.16 | **0.20** | **+0.04** | −0.1178 | `object_relative-A-00` |
| candidate | (d) surface-anchored `next_to` | 0.08 | **0.12** | **+0.04** | −0.1178 | `object_relative-A-00` |

Collisions 0 in every cell. Per-episode distance-to-goal for the family that
moved (baseline / candidate where they differ):

| episode | v2 dtg | **v3 dtg** |
|---|---|---|
| `A-00` sit next to the bench | 0.7267 / 0.7266 | **0.0000** |
| `B-05` wait by the bench | 2.2173 | 1.4835 |
| `C-10` stand next to the seat | 8.2040 | 7.4702 |
| `D-15` go next to the planter | 4.4652 / 4.7531 | 4.0152 / 4.3031 |
| `E-20` absent target | 55.2003 / 53.9203 | 54.9003 / 53.6203 |

### The prediction, and the half of it that was wrong

Card B-1 re-scored the **frozen v2 traces** read-only and predicted:
*exactly one episode's K0 arrival predicate flips — the bench — and headline SR
does not move, because episode success additionally requires the settle hold and
was 0/5 before and after.*

- **Confirmed:** exactly one K0 flip, it is `nav-object_relative-A-00`, and it
  flips in **both** modes. No other episode's predicate moved in either
  direction.
- **Refuted:** SR *does* move, by +0.04 in both modes. The bench episode is a
  genuine success on a fresh run — final pose inside the band at dtg 0.000, and
  it holds. The prediction was made against 2026-08-08 recorded traces in which
  the bench never held; on today's tree it does.
- **Consequence for U32:** the `false_arrival` count drops **2 → 1** in both
  modes, and the row that left the class is the bench. It was a *false arrival
  because the band was wrong*, not because the navigator lied — the mission
  claimed `arrived_verified` at a pose the old band could not certify and the
  new one can.

`bridge_v2_v3.json` carries `predicted_vs_measured.prediction_confirmed: false`
with the per-mode detail, and a test pins that it says so.

## Protocol compliance

| requirement | evidence |
|---|---|
| old frozen digests unmoved | v1 `cf4d5384…`, v2 `a17c04db…` — asserted in `test_nav_instruct_episodes_v3.py` *and* `…_v2.py` |
| old episode files immutable | v2 regeneration diff still byte-exact; **no file under `episodes/v1/` or `episodes/v2/` was written** |
| old frozen goals keep the old band | every `object_relative` goal in v1/v2 still carries `band_m == (0.4, 1.5)`, asserted directly |
| old ledger rows byte-identical | first 11 lines sha256 `7c131895600022666a13001ae08c58345b5a3ccc4727eb55a582873be62048a9`, before and after; the 9-line v2-era prefix `dab60242…` is unchanged inside it |
| old report JSONs immutable | nothing under `results/` was rewritten; two new reports were added |
| v3 is a new versioned artifact | digest `919a0fea…`, own directory, own manifest with provenance |
| new rows marked | `baseline_version: "v3"`, `arrival_rule: "hold-or-trace-end-v1"`, `sr_frozen_rule` on both |
| eval-integrity tests pass against v3 | `tests/test_nav_instruct_episodes_v3.py` — regeneration diff over the checked-in v3 files, oracle isolation (v3's table *is* the derived section and equals v2's), only-`object_relative`-moved, live-builder equality |
| bridge isolates this change | `results/bridge_v2_v3.json`, 4 cells one process, one correction |
| no other frozen artifact moved | `evals/companion/**` and `evals/companion_nav/**` byte-identical (the embodied 1250 row and the duplex mirrors were neither read nor written); `evals/external/**` untouched |

### The one other artifact that had to move: `walk_with_me`

`evals/walk_with_me/freeze/manifest.json` embeds a goal built by the same K0
`next_to` builder (`wwm-lamppost-standoff`: `band_m [0.4, 1.5]`,
`anchor_footprint_m 0.06`). It is a *derived* artifact — the manifest is written
by `walk_with_me.generator.write_frozen_manifest` — so it was **regenerated
through its generator, never hand-edited**, and its digest moved:

| | before | after |
|---|---|---|
| freeze digest | `fc24837ce23b23cb5c87a7c2ccbb70df396a7870159802719069efc95ed6deab` | `d9487ce70602d69d117ef90e937546120c1c81fb03cb6908c623f18c6ff401da` |
| `wwm-lamppost-standoff` band | `[0.4, 1.5]` | `[0.46, 1.56]` |

The freeze seed (`20260805`) is unchanged, so the superseded manifest is exactly
`generate_frozen_pack(seed=20260805)` under the centre-anchored band. **The
walk_with_me ledger row and its report JSON were not touched**; they still name
the superseded digest `fc24837c…`, which is the correct record of what that run
scored against. This lane does not own `evals/walk_with_me/**` and made the
minimum change that keeps its own generator-equality test true.

## What this re-freeze does NOT claim

1. **It is not a policy improvement.** The +0.04 SR in both modes is one
   episode, and it is the episode whose *goal region* changed. Nothing about
   the navigator got better; the band it is scored against stopped being
   impossible.
2. **n = 1 run per cell.** The runner is effectively deterministic (measured
   repeat variability 2.9e−5 m, card V-3b), so a repeat adds little, but four
   cells is four runs.
3. **The bench arrives on a *sliver*.** The admissible arc under the planning
   band is 3.7° wide off the bench's east end, with ~0.006 m of pedestrian
   margin at the nearest-to-spawn point. It is possible, not robust, and it is
   the east short end rather than the front — because `pedestrian_5` and
   `pedestrian_7` box in the south face and `bldg_1`/`bldg_2` box in the north.
4. **`R* = 0.38 m` did not disappear, it changed meaning.** The same expression
   is now `next_to_band_surface_slack_m()`: the usable width of the band around
   an anchor of *any* size. Achievability no longer depends on the anchor at
   all, which is a stronger claim than the old threshold and is why the
   `building` exclusion in the scene sidecar is now declared as a vocabulary
   choice rather than a derivation.
5. **v2 and v3 numbers are comparable only through this bridge**, which is the
   only place both were measured on one tree. Subtracting a v3 row from a
   stored v2 row is a category error.
