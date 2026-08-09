# BENCH PLACEMENT — measure, then resolve · status

**Date:** 2026-08-08 · **Cards:** B-1 (measure three constraint sets), B-2
(implement the least-invasive resolution the measurement supports + fix the
achievability check), B-3 (verify).
**Owner directive (verbatim):** *"Make sure the dog gets to the band and make
just stand next to the pedestrian or determine if it is possible to sit on the
other side of the bench. If not expand the k0 band so that the band is set
around the entire bench".*
**Entry state:** default suite 2777 passed / 0 failed / 3 xfailed (F-1's exit);
`sit next to the bench` xfail with F-1's exhaustive-sweep reason.

**The one-line claim:** the bench is not a bench problem. `next_to` is
achievable **only for anchors with radius ≤ 0.38 m**, because the K0 band is
measured to the anchor's *centre* while every stand-off authority is measured to
its *surface* — so for any larger anchor the `next_to` band lies **entirely
inside** the disc the `near` relation's own inner edge forbids. The sidecar was
advertising that impossible relation for **three** classes, not one. The owner's
fallback (expand the K0 band) is measured, works, and flips exactly the one
episode it should — and it moves both frozen NAV_INSTRUCT episode digests, so it
is filed here as an exact handoff instead of applied.

---

## B-1 — the measurement

Method: the F-1 sweep extended. Ground truth is the MJCF itself, projected the
way `mujoco_lidar.planar_geom_surface_hit` projects it (every
`sim.is_logical_obstacle_name` geom whose bottom sits below
`RobotProfile.obstacle_clearance_height_m = 0.9`, as an oriented box or a
circle; 29 solids). 3601 bearings × 551 radii over the whole annulus. Nothing
reads the shipped 5×24 placement lattice — the question is whether an admissible
pose *exists*.

**The atoms** (all derived, none written):

| quantity | value | where from |
|---|---|---|
| `footprint_radius_m` | 0.32 | `StandOffEnvelope` / `RobotProfile` |
| `target_surface_clearance_m` | 0.80 | `StandOffEnvelope` |
| arrival tolerance (next_to branch floor) | 0.08 | `approach.py` `max(metadata 0.06, 0.08)` |
| **solver clearance, centre-to-surface** | **1.20** | `approach.py::_occupied` = 0.32+0.80+0.08 |
| runtime reactive gate, centre-to-surface | 0.97 | `configs/robot.yaml safety.obstacle_stop_m` 0.65 + 0.32 |
| navigator collision brake, centre-to-surface | 1.12 | `configs/navigation/default.yaml stop_distance_m` 0.80 + 0.32 |
| person social zone | 1.20 | `SafetyEnvelope.person_social_zone_m` (HUMAN bucket) |
| K0 band / planning band | (0.4, 1.5) / (0.52, 1.38) | `NEXT_TO_BAND_M` / F-1's arrival inset |
| bench solid extent | x ∈ [−3.200, −1.800], y ∈ [2.780, 3.230] | MJCF, 4 geoms |
| `bench_1` anchor / radius | (−2.5, 3.045) / 0.733757 | `scene_truth.json` derived |
| `pedestrian_5` | (−2.0, 1.8), capsule r 0.20 | MJCF rest pose |

### The table

`d_*` are centre-to-surface. "K0 band" is the verify band; "planning band" is
the K0 band inset by the arrival tolerance the controller may spend (F-1).

| # | constraint set | band | bench | person | others | **admissible** | nearest to spawn |
|---|---|---|---|---|---|---|---|
| a1 | **TODAY** | K0 | 1.20 | 1.20 | 1.20 | **0** | — |
| a2 | TODAY | planning | 1.20 | 1.20 | 1.20 | **0** | — |
| a3 | TODAY, person as a plain obstacle | K0 | 1.20 | 1.20 | 1.20 | **0** | — |
| a4 | TODAY, person as a plain obstacle | planning | 1.20 | 1.20 | 1.20 | **0** | — |
| a5 | runtime gate only | K0 | 0.97 | 1.20 | 0.97 | **0** | — |
| a6 | runtime gate only, people ignored | K0 | 0.97 | — | 0.97 | 91 321 | (−1.627, +1.825) at **r = 1.500** |
| b1 | **(b)** terminal person 1.20 / 1.12 / 0.97 / 0.72 | K0 | 1.20 | ↓ | 1.20 | **0** | — |
| b2 | (b) terminal person **0.52** | K0 | 1.20 | 0.52 | 1.20 | 539 | (−2.678, +1.556) at **r = 1.500** |
| b3 | (b) terminal person 0.36 | K0 | 1.20 | 0.36 | 1.20 | 2 079 | (−2.500, +1.545) at r = 1.500 |
| b4 | (b) terminal person **0.00** (may touch) | K0 | 1.20 | 0.00 | 1.20 | 4 298 | (−2.178, +1.580) at r = 1.500 |
| b5 | (b) terminal person **0.00**, planning band | planning | 1.20 | 0.00 | 1.20 | **0** | — |
| c | **(c)** full perimeter, current band | K0 | 1.20 | 1.20 | 1.20 | **0 on every one of 360 bearings** | best slack **−0.382 m** at bearing 29° |
| 3 | **surface-anchored band** (0.4+R, 1.5+R) | K0 | 1.20 | 1.20 | 1.20 | 3 557 | (−0.602, +1.868) at r = 2.234 |
| 3p | surface-anchored band | planning | 1.20 | 1.20 | 1.20 | **999** | (−0.625, +2.069) at r = 2.114 |

### Constraint set × side/arc × admissible? × margin

The matrix the card asked for. Cells read `YES n=<admissible poses>` or
`no, slack <m>` — **slack** is the best achievable
`min(d_bench−req, d_person−req, d_other−req)` anywhere on that arc, i.e. how far
short the best pose on that side falls. 1801 bearings × 276 radii.

| constraint set | E end (315–45°) | N back (45–135°) | W end (135–225°) | S front (225–315°) |
|---|---|---|---|---|
| **(a) TODAY**, planning band | no, −0.451 | no, −0.506 | no, −0.521 | no, −0.405 |
| (a) TODAY, K0 band | no, −0.381 | no, −0.507 | no, −0.441 | no, −0.405 |
| **(b)** person 0.00, planning band | no, −0.438 | no, −0.506 | no, −0.438 | no, **−0.085** |
| (b) person 0.00, K0 band | no, −0.326 | no, −0.507 | no, −0.326 | **YES n=1111** |
| **(c)** full perimeter, current band | no, −0.381 | no, −0.507 | no, −0.441 | no, −0.405 |
| **(3)** surface band, planning | **YES n=254** | no, −0.532 | no, −0.374 | no, −0.266 |
| (3) surface band, K0 | **YES n=899** | no, −0.506 | no, −0.375 | no, −0.187 |

Three readings worth stating:

* **(c) is identical to (a) row for row.** The full-perimeter question has the
  same answer as the today question, because the sampler was never the limit.
* **(b) gets closest on the south front and still misses by 0.085 m** in the
  planning band even when the dog is allowed to touch the pedestrian. It only
  turns YES once the arrival inset is discarded as well — and every one of those
  1111 poses sits at r = 1.500.
* **(3) opens the east short end, not the south front.** That is not where a
  person would say "beside the bench", and it is where it is because
  `pedestrian_5` (SE) and `pedestrian_7` at (−3.8, 1.4) (SW) box in the front
  while `bldg_1`/`bldg_2` box in the back.

### Per-side / per-arc, and what binds

Under the **current** band the polar sampler is *not* biased — unlike
`nearest_point_in_region`'s inset lattice (F-3(b)), which anchored a rectangular
grid at `(min_x, min_y)`, this one steps uniformly in bearing and has no
preferred axis. Every bearing is searched; every bearing is short. Max distance
to the bench surface achievable **inside the K0 band**, by bearing:

| bearing | 0° (E end) | 45° | **90° (back)** | 135° | 180° (W end) | 225° | **270° (front)** | 315° |
|---|---|---|---|---|---|---|---|---|
| max `d_bench` | 0.800 | 0.947 | **1.315** | 0.947 | 0.800 | 0.874 | **1.235** | 0.874 |
| same, planning band | 0.680 | 0.838 | **1.195** | 0.838 | 0.680 | 0.762 | 1.115 | 0.762 |

North/south asymmetry (0.947 vs 0.874) is the anchor, not the sampler: the
semantic centre is y = 3.045 and the union of the bench solids is centred at
y = 3.005.

| side | verdict | what binds |
|---|---|---|
| **north (the "other side of the bench")** | **impossible** | `bldg_1`'s south face is 0.77 m north of the bench back. Best `min(d_bench, d_other)` over the 60–120° arc is **0.685 m** (bearing 60.9°, r = 0.996); widening to 45–135° only reaches **0.694 m** (bearing 45.0°, r = 1.217, now bounded by `bldg_2`) — both inside the runtime gate's own 0.97 m envelope. Over 85–125° it collapses to **0.353 m**: the band there is *inside the building*. |
| **south (front)** | impossible | The bench alone is clearable at r ∈ [1.465, 1.500] (max 1.235 ≥ 1.20) — but that arc is outside the **planning band** (hi = 1.38), and `pedestrian_5` sits at bearing 291.9°, 1.342 m from the bench centre, i.e. **inside the bench's own next_to band**. |
| **east / west short ends** | impossible | Max `d_bench` 0.800 m (K0) / 0.680 m (planning) — the two *worst* bearings, because the band's outer edge is a fixed 1.5 m from the centre while the bench reaches 0.7 m along that axis. |

**The single strongest statement, and it needs no solver argument:** restricted
to poses that already clear every other solid and every person, the greatest
achievable distance to the bench's own surface anywhere in the K0 band is
**0.78 m** (0.68 m in the planning band) — **inside the unconditional reactive
gate's 0.97 m centre-to-surface stop envelope.** The body could not stand there
even if the approach solver asked it to. No loosening of any solver margin can
open this case.

### (b) is refuted twice over

1. **The planning band is empty even if the dog may touch the pedestrian.**
   b5: 0 admissible at person clearance 0.00. The **bench** forbids it — the
   greatest `d_bench` over the entire planning band is **1.195 m** against a
   1.20 m requirement, and that maximum is due north, 0.20 m from `bldg_1`'s
   face. The person is moot.
2. **The clearance that would open the raw K0 band is inside the gate.**
   Bisected: poses appear only once the terminal person clearance drops to
   **0.651 m centre-to-person-surface = 0.331 m footprint-to-surface**. That is
   below `ReactiveSafetyPolicy.obstacle_stop_m` (0.65) *and* below
   `person_stop_m` (1.0), so the body is hard-stopped before it can reach such a
   pose. Pinned live in
   `tests/test_next_to_band_achievability.py::test_the_unconditional_gate_still_zeroes_translation_at_that_clearance`,
   asserted through both channels (`lidar_obstacles` — how a stationary
   pedestrian actually arrives in the **static** city, see below — and
   `nearest_person_m`).
3. And every one of those poses sits at **r = 1.500 exactly**, the band edge
   F-1's arrival inset exists to forbid.

### The terminal clearance value, derived — and why it is not introduced

The card asks for a first-principles value even if unused. Deriving it from the
authority rather than picking one:

* **Floor.** `SafetyEnvelope.stop_distance(0.0)` = `r_foot + 0·τ + 0 + Zs + Zr`
  = **0.32 m** centre-to-surface at rest. That is the ISO/TS-15066 sum at zero
  speed, and it is exactly the body radius: it says "do not overlap", nothing
  more.
* **Plus the authority's own name for "and a little more than exactly enough":**
  `StandOffEnvelope.stand_off_margin_m` = 0.04.
* **Candidate:** `terminal_person_clearance_m = stop_distance(0.0) +
  stand_off_margin_m = 0.36 m` centre-to-person-surface = **0.04 m
  footprint-to-surface**.

**It is not introduced, for three independent reasons**, and only the first is
about this scene:

1. It does not open a placement. At 0.36 the planning band is still empty (b5);
   only the raw K0 band opens, at r = 1.500, which the arrival inset forbids.
2. 0.04 m of air between a dog's footprint and a standing person is not a
   defensible terminal pose under any reading of the HUMAN bucket, whose whole
   documented point is that *the person*, not the robot's brakes, sets the final
   metre. The card's own floor (`≥ footprint_radius + obstacle margin`) is met
   only in the narrowest arithmetic sense.
3. It would be unreachable anyway: the unconditional reactive gate stops
   translation at 0.65 m footprint-to-surface and never exempts anything, so a
   0.04 m terminal pose is not a pose this body can arrive at. Relaxing the
   *placement* without relaxing the *gate* produces a planned pose the robot
   deadlocks in front of — the exact planner/gate disagreement F-1 named as
   mechanism 3.

So no `terminal_person_clearance_m` field was added anywhere, and **no handoff
against `authority.py` is filed** — the measurement says the field is not the
missing piece.

### One thing the F-1 reason string assumes that the static city does not do

`pedestrian_5` is **not a tracked person** in the static city. `dynamic_city` is
disabled, so `snapshots()` is empty, `nearest_person_m` is `None`, and both
person gates are inert; the pedestrian arrives as a **LiDAR obstacle** (its geom
name matches `LOGICAL_OBSTACLE_PREFIXES`), bound by `obstacle_stop_m`, not by
the social zone. Applying the 1.2 m person zone to it — as F-1's sweep did and
as rows a1/a3 do here — is therefore a *modelling choice*, correctly
conservative but not a live constraint. It changes nothing: rows a3/a4 hold the
pedestrian to the plain 1.20 m obstacle clearance and the admissible set is
still empty.

---

## B-2 — the resolution

The card's priority order, against the measurement:

| branch | condition | measured | taken? |
|---|---|---|---|
| (1) terminal-vs-motion clearance | "if (b) alone opens a viable placement" | **it does not** — b5 = 0 at *any* value, and the value that opens the raw K0 band is inside the gate | no |
| (2) fix the band/sampling for the full perimeter | "else if (c) opens a placement on another side" | **it does not** — the sampler is unbiased and all 360 bearings are short by ≥ 0.382 m | no |
| (3) expand the K0 band to encircle the entire bench | "else" | **it works**, and it is the owner's stated fallback | **measured, filed as a handoff — see "stopped and reported"** |

### The defect, in one inequality

`NEXT_TO_BAND_M` is a distance to the anchor's **centre**;
`StandOffEnvelope` is a distance to its **surface**. A pose at the band's outer
edge sits `band_hi − R` from the surface of an anchor of circumscribed radius
`R`, and must clear `minimum_vicinity(R) = R + r_foot + target_surface_clearance`
— *the same composite that already sets the inner edge of the `near` band*. So

```
next_to is achievable  <=>  NEXT_TO_BAND_M[1] >= StandOffEnvelope.minimum_vicinity(R)
                       <=>  R <= band_hi - r_foot - target_surface_clearance = 0.38 m
```

Above `R* = 0.38 m` **the two relations invert**: `next_to`'s outer edge lies
inside `near`'s inner edge, so "next to X" names a band that is entirely inside
the region the stand-off authority forbids the body from standing in. For the
bench the inversion is **0.354 m** deep (`minimum_vicinity(0.734) = 1.854` vs
`band_hi = 1.5`).

Measured over `scene_truth.json` — **`lamppost` is the only class in the scene
that clears it**:

| class | radii | `minimum_vicinity` | ≤ 1.5? | advertised `next_to` before | after |
|---|---|---|---|---|---|
| lamppost | 0.060 | 1.180 | **yes** | yes | **yes** |
| planter | 0.450 | 1.570 | no (by 0.07) | **yes** | **dropped** |
| tree | 0.580 | 1.700 | no | **yes** | **dropped** |
| bench | 0.734 | 1.854 | no | **yes** | **dropped** |
| building | 1.844–2.408 | 2.964–3.528 | no | no (already) | no |

### What landed

Everything below is inside this card's ownership, is green, and moves no frozen
artifact.

1. **`instructnav/scoring.py`** — `next_to_is_achievable(R)` and
   `next_to_achievable_anchor_radius_m()`. **Not a new band and not a new
   literal**: it is the inequality between two authorities that already exist,
   written down once. `R* = 0.38` is derived, never typed.
2. **`tests/test_scene_semantics.py`** — the achievability check named in the
   card now uses the real stand-off envelope. It used to test only that the goal
   region was a non-empty *set of points* (`max(band_lo, footprint) ≤ band_hi`),
   which is a statement about the band and the radius and says nothing about
   whether a **body** can stand in it. The old assertion is kept as well, so the
   two questions stay visibly distinct. `test_building_would_fail_...` is
   replaced by two stronger tests: one pins the derivation of `R*`, the other
   pins the *converse* — no class may drop `next_to` for taste, only because a
   real instance's radius fails the derivation.
3. **`configs/scenes/city_block.semantics.yaml`** — `bench`, `tree` and
   `planter` drop `next_to`, each with the measured reason, exactly as
   `building` already did. Consequence check: affordances are read by
   **`voice/scene_reference.py` clarification offers only** — not by grounding,
   not by the navigator, not by the NAV_INSTRUCT generator (which reads
   `scene_truth.json`). So this is an advertisement change, not a behaviour
   change; the sit-next-to-the-bench command still compiles and still runs.

   **The one user-visible effect, measured:** the novel-verb clarification for a
   bench was *"I can go to it, sit next to it, or walk towards it"* and is now
   *"I can go to it or walk towards it"* (same for tree and planter; the
   lamppost still offers all three). That is the honest offer — the robot was
   promising a placement it could not reach. It surfaced as a red in
   `tests/test_owner_and_settle_plans.py::test_the_offer_names_only_relations_the_class_actually_affords`,
   whose docstring is literally *"A building cannot be sat next to; the offer
   must not say otherwise"* — the invariant was already the right one; only its
   example needed to move. The test was updated to assert **both** directions
   against the derived rule (lamppost positive; building, bench and tree
   negative, and all three still offered `go to it` / `walk towards it`), which
   makes it a stronger test than before.
4. **`configs/scenes/generated/val_unseen_9101{1..5}.semantics.yaml`** —
   re-emitted through `scene_gen.semantics_sidecar_text()`, never hand-edited,
   so the five generated sidecars do not go stale against their source.
5. **`instructnav/relations.py`** — `next_to_placement`'s `band_m` **default
   `(0.4, 0.9)` is deleted and the argument made required**. It was a second
   band literal disagreeing with the K0 authority by 0.6 m on its outer edge,
   inert only because the single production caller always passed `band_m=`
   explicitly. Two bands is the D5 defect class. The lattice size is named
   (`PLACEMENT_BEARINGS`/`PLACEMENT_RADII`) and its measured resolution limit
   documented — see the handoff.
6. **`tests/test_next_to_band_achievability.py`** — new, 12 cases. Every scene
   number is read from the MJCF at test time; nothing is transcribed.

### The safety argument — what remains unconditional

Nothing in the safety chain was touched, and one new test exists to keep it that
way.

* `navigation/reactive_safety.py`, `navigation/collision.py`,
  `navigation/grid_planner.py`, `authority.py`, `configs/robot.yaml`,
  `configs/navigation/default.yaml` — **not modified.**
* No terminal-clearance relaxation was introduced anywhere, so the person and
  obstacle stop distances are byte-identical to entry.
* `test_the_unconditional_gate_still_zeroes_translation_at_that_clearance`
  asserts that at the 0.331 m footprint-to-surface clearance (b) would have
  needed, `apply_reactive_safety` returns `vx == vy == 0.0` and
  `note == "stopped"` — through **both** the obstacle channel and the person
  channel, at the shipping `ReactiveSafetyPolicy`. The gate is consumed, never
  retuned.
* The proposed band change (below) is an **arrival-verification** change. It
  cannot move a stop distance, a brake, or a speed cap: it only widens the set of
  final poses the scorer and the navigator agree to call "beside it", and every
  one of those poses still has to clear the same 1.20 m solver clearance and pass
  the same unconditional gate on the way in.

---

## B-3 — verification

### The live bench case, run twice by node id (`MUJOCO_GL=egl`, product path)

`tests/test_voice_nav_e2e.py::test_sit_next_to_the_bench_settles_beside_it_in_a_sit`
plus an instrumented driver over the same fixture and the same `handle_text`
path.

| run | outcome | reason | elapsed | final pose | d(bench centre) | d(K0 band) | K0 predicate | posture | settled | authority category |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `failed` | `semantic_target_unreachable` | 45.03 s | (−0.8691, +1.4652) | **2.2395 m** | 0.7395 m | **False** | `unknown` (never sat) | True | `agreement` |
| 2 | `failed` | `semantic_target_unreachable` | 45.01 s | (−0.8685, +1.4655) | **2.2398 m** | 0.7398 m | **False** | `unknown` | True | `agreement` |
| pytest node | **XFAIL** (non-strict), reason unchanged | | 99.2 s for the pair | | | | | | | |

Both authorities agree the robot did not arrive (`agreement`, not
`false_arrival`) — the mission refuses to claim anything, which is the honest
answer and unchanged from F-1's conclusion. What *has* drifted since F-1 is the
shape of the failure: F-1 measured `semantic_target_unreachable` at 7.5 s with
0.00 m travelled; today the body takes 45 s and ends **1.80 m in a straight
line from its start pose** (0.1, −0.05) before saying the same thing. (Straight
line, not path length — the driver records the final pose, not the trajectory.)
Not investigated here, and it does not touch this card's claim.

**The number worth staring at:** the robot stops **2.24 m from the bench
centre** — 0.74 m *outside* today's band, and only **0.037–0.040 m outside the
surface-anchored band** the handoff proposes. It is already going almost exactly
where the wider band would call arrival.

### The lamppost case (hard gate — must stay green)

| run | outcome | elapsed | final pose | d(centre) | K0 | posture | settled |
|---|---|---|---|---|---|---|---|
| 1 | **`succeeded`** / `safe_pose_stop_verified` / `arrived_verified` | 46.01 s | (−0.1955, +1.7102) | 1.4931 m | **in band, miss 0.000** | **`sit`** | True |
| 2 | **`succeeded`** / `safe_pose_stop_verified` | 46.06 s | (−0.1958, +1.7051) | 1.4981 m | **in band, miss 0.000** | **`sit`** | True |
| pytest node | **PASSED** | | | | | | |

`SitNextToOutcome`: `success=True`, `in_next_to_band=True`, `sit_posture=True`,
`settled=True`, `detail="success"` on both runs. Three consecutive green
observations on top of F-1's three.

### Paired protocol for the proposed K0 change — read-only, per episode

The card asks for NAV_INSTRUCT candidate before/after. **The protocol as written
is not runnable for this change**, and that is itself a finding: the band lives
*inside the frozen episode payload* (`goal.band_m`), so applying it changes the
episode set rather than the policy under test — a before/after would compare two
different benchmarks. What *is* a valid paired measurement is re-scoring the
**same** frozen traces under the two band definitions, which is what follows.
Nothing was written; no ledger row was appended.

Frozen v2 reports (`nav-instruct-v1-{baseline,candidate}-v2-20260808T00*.json`),
all five `object_relative` (`next_to`) episodes:

| episode | anchor R | K0 old | K0 new | d_old | d_new | instruction |
|---|---|---|---|---|---|---|
| `nav-object_relative-A-00-3efbba45` | 0.7338 | False | **True** | 0.503 / 0.672 | **0.000** | *sit next to the bench* ← **the only flip** |
| `nav-object_relative-B-05-7d441aee` | 0.7338 | False | False | 2.217 | 1.484 | wait by the bench |
| `nav-object_relative-C-10-0d3f5ebd` | 0.7338 | False | False | 8.204 | 7.470 | stand next to the seat |
| `nav-object_relative-D-15-61f68ad6` | 0.4500 | False | False | 4.465 / 4.753 | 4.015 / 4.303 | go next to the planter |
| `nav-object_relative-E-20-0c739ea2` | 0.3000 | False | False | 55.2 / 53.9 | 54.9 / 53.6 | sit next to the bench (absent) |

*(two values = baseline / candidate where they differ)*

**Exactly one episode's K0 arrival predicate flips, it is the bench, and it
flips in both modes.** Episode `success` (which additionally requires the settle
hold) is **0/5 before and 0/5 after** in both modes, so headline SR on the
recorded traces does not move. The change moves precisely the case it is meant
to move and nothing else.

### Frozen rows

| artifact | status |
|---|---|
| `tests/test_embodied_plan_eval.py` — the 1250 row | **10 passed, unmoved** (in the full run below; its cases are `near`/`inside`, no `next_to`) |
| `tests/test_duplex_v1.py` | 3 passed |
| `tests/test_nav_instruct_episodes_v2.py` — the two episode digests | passed; **nothing under `evals/` was written by this card** |
| `evals/**` | byte-identical to entry — code *and* data |

### Suite and lint

| check | result |
|---|---|
| `ruff check` on every file this card touched | **clean** |
| `ruff check .` repo-wide | 61 findings, **none in this card's files** (pre-existing / other lanes) |
| targeted: scene semantics, relation registry, K0 authority, compound predicates, superlatives, walk-with-me, city semantics, **embodied plan eval**, **duplex**, **nav_instruct episodes v2** | **187 passed** |
| targeted: achievability, scene semantics, owner+settle plans, instructnav relations, next_to approach geometry | **98 passed** |

**Full default suite** (`MUJOCO_GL=egl .parcel/bin/python -m pytest tests/ -q`,
includes the live `-m slow` e2e block). Run twice: the first exposed one red
this card caused, the second is the final tree. Entry baseline was 2777 passed
(F-1); the tree has grown ~90 tests from concurrent lanes since.

| run | result | wall |
|---|---|---|
| 1 — before the offer-test update | `1 failed, 2870 passed, 14 skipped, 3 xfailed` | 704.3 s |
| **2 — final tree** | **`2871 passed, 14 skipped, 3 xfailed, 0 failed, 0 xpassed`** | 703.4 s |

The three xfails are the two nav pins F-1 left (bench sit, sidewalk traffic) and
`test_authority_half_scale_smoke`'s scale-covariance pin — all untouched. **No
xpass in either run**, so nothing pinned here now passes; in particular the
bench pin did not become a false green.

*(One comment block was added to `scoring.py`'s `NEXT_TO_BAND_M` definition
after run 2 started. It is comments only — no statement changed — and
`tests/test_instructnav_scoring.py`, `tests/test_next_to_band_achievability.py`
and `tests/test_scene_semantics.py` were re-run green against the final bytes.)*

Run 1's single red was
`tests/test_owner_and_settle_plans.py::test_the_offer_names_only_relations_the_class_actually_affords`
— **caused by this card**, diagnosed as the sidecar change doing exactly what it
was supposed to do (a bench can no longer be offered "sit next to it"), and
fixed by moving the test's examples onto the derived rule while strengthening it
in both directions. No other red appeared, and no xpass: nothing pinned here now
passes.

---

## The handoff — the K0 band change, exact

**This is B-2(3), measured and proven, and deliberately NOT applied.** It moves
frozen `evals/**` artifacts, which this card does not own and which B-2(3) tells
it to stop on rather than re-freeze.

### The one definition

`NEXT_TO_BAND_M` becomes a band around the anchor's **surface** rather than its
centre, materialised in exactly one place:

```python
# instructnav/scoring.py — ONE function; every other site calls it.
def next_to_band_from_centre(
    anchor_footprint_m: float,
    band_m: tuple[float, float] = NEXT_TO_BAND_M,
) -> tuple[float, float]:
    """The surface-relative K0 band, materialised in anchor-centre coordinates.

    The band's WIDTH (1.1 m) is a property of the relation and must not depend
    on how big the anchor is. Measuring it from the centre made it depend:
    a 0.734 m bench got 0.77 m of usable band and a 1.5 m anchor got none.
    """
    r = float(anchor_footprint_m)
    return (float(band_m[0]) + r, float(band_m[1]) + r)
```

Call sites that must switch to it (and nothing else may add an offset):

* `scoring.object_next_to_goal_region` — the band it stamps into the GoalRegion;
* `scoring.owner_anchored_band_goal_region` — same treatment for
  `owner_footprint_m = 0.22`, otherwise the owner band and the object band mean
  different things;
* `navigation/approach.py::_next_to_planning_band` — takes the materialised
  band, keeps the arrival inset unchanged;
* `instructnav/relations.py` — raise `PLACEMENT_BEARINGS` **24 → 72** (see
  below). `PLACEMENT_RADII` may stay at 5.

`GoalRegion.contains`'s `dist >= anchor_footprint_m` guard becomes redundant
(`band_lo + R > R` always) and should be left in place — it costs nothing and it
is the last line of defence if someone ever passes a negative band.

### Why the density raise must travel with it, not before

Measured: under the surface-anchored planning band the bench's admissible set is
a **3.7°-wide arc** (bearings 332.5–336.2°, radii 2.001–2.114). 24 bearings are
15° apart and miss it entirely; 48 and 64 also miss; **72 finds it.** Raising the
density *today*, with the current band, would find nothing new (no anchor in any
scene has a non-empty set) and would perturb the one live `next_to` case that
passes — measured: it moves the lamppost pose 5–10 cm tangentially, always to a
lower approach cost, always at the same radius. So it is filed here, not landed.
`tests/test_next_to_band_achievability.py::test_the_shipping_lattice_cannot_resolve_the_arc_that_band_would_open`
pins both halves of that statement and will fail loudly if the band moves without
the density.

### What it moves — measured, not predicted

| artifact | before | **after** |
|---|---|---|
| `FROZEN_V1_DIGEST` | `cf4d5384d1787d110cbc5a74e8b46699e6aa26eaaa576b1c24beb0fbb04adfbf` | `14e67521dff65b2d9321c6267660a92ffca4ec552162ee5a25812100c5d85517` |
| `FROZEN_V2_DIGEST` | `a17c04dbec43a1749386c304060fb479a71f27d4b51b8c1b0fbb949753fc563d` | `919a0fea836363a6f6d04d3fb186b0dcb493aa6c76357d8af2b0c05408c556aa` |

(Measured by monkeypatching the builder and calling
`generator.matrix_digest(generate_minival(version=...))`; nothing was written.)

Ten episode JSON files carry `band_m: [0.4, 1.5]` verbatim
(`evals/nav_instruct/episodes/{v1,v2}/nav-object_relative-{A-00,B-05,C-10,D-15,E-20}-*.json`)
and both `manifest.json` files carry the digest. A re-freeze therefore touches:
10 episode files + 2 manifests + the 2 constants in
`tests/test_nav_instruct_episodes_v2.py` + one ledger row. Also affected and to
be checked in the same change: `evals/walk_with_me/freeze/manifest.json`
(`wwm-lamppost-standoff` embeds `band_m: [0.4, 1.5]`,
`anchor_footprint_m: 0.06`), `scripts/mutation_panel.py` (its relation-family
episode is `nav-object_relative-A-00-3efbba45`; the `arrival_radius_x2` and
`inverted_relation` mutants must still die against a wider band), and
`tests/test_relation_registry.py`'s `proximity_band_overlaps` pins.

### The pin change this card earned (coordinator applies it)

**`tests/test_voice_nav_e2e.py` is not this card's file.** Two things in the
bench xfail reason are now wrong, and one is a live-measured drift:

1. *"the admissible set is EMPTY"* — still true, but the reason string names
   only the bench. It should name the general rule: **`next_to` is achievable
   only for anchors with R ≤ 0.38 m** (`next_to_achievable_anchor_radius_m()`),
   and `bench`/`tree`/`planter` all failed it, not just `bench`.
2. *"either next_to's band scales with the anchor's footprint … or bench drops
   next_to from its sidecar affordances"* — **the second half has now happened**
   (`configs/scenes/city_block.semantics.yaml`, this card). The remaining route
   to flipping the pin is the band change, and its handoff is this file.
3. *"safe_approach_pose returns None and the mission says
   'semantic_target_unreachable' in 7.5 s, 0.00 m travelled"* — **re-measured
   2026-08-08, n=2: 45.0 s, ending (−0.869, +1.465) = 1.80 m in a straight line
   from the (0.1, −0.05) start, 2.240 m from the bench centre, 0.740 m outside
   the band, posture `unknown`, `authority_category=agreement`.** Same verdict,
   different timing and displacement. Root cause not investigated here.
4. The reason string's pointer
   `tests/test_scene_semantics.py::test_declared_affordances_are_achievable_at_the_scene_s_real_radii`
   *"checks band emptiness against the footprint only … which is why it passes
   bench today"* — **fixed by this card**; it now uses the stand-off envelope
   and bench no longer advertises the affordance.

The pin **stays xfail**. Nothing measured here flips it.

---

## Non-claims

1. **The bench is still not fixed.** What changed is *why*: it is a relation-family
   inversion (`next_to` outer edge inside `near` inner edge for R > 0.38 m), not
   a bench-shaped accident, and the sidecar no longer advertises the impossible
   relation. The behaviour is unchanged and the pin is unchanged.
2. **The surface-anchored band is measured, not validated.** It opens 999
   admissible poses in the planning band — but they are a **sliver**: a 3.7° arc
   with 0.006 m of pedestrian margin and 0.000 m of lamppost margin at the
   nearest-to-spawn point. It would make the bench case *possible*, not *robust*.
   Whether the live run then arrives there was not measured, because the change
   was not applied.
3. **The paired protocol was run on recorded traces, not on fresh episodes.** A
   fresh candidate run under the new band is a run against a *different* episode
   set, which is not a paired comparison. The re-scoring is the honest paired
   measurement available without a re-freeze; it is not a claim about how a fresh
   run would score.
4. **`R* = 0.38 m` is exact for a circumscribed-radius anchor model.** K0 carries
   one scalar `anchor_footprint_m`, so a long thin anchor is modelled as its
   circumscribing circle. That is conservative on the short axis (the bench's
   0.734 m circle overstates its 0.225 m half-depth by 0.51 m) and nearly exact
   on the long axis. A true Minkowski band around the anchor's real footprint
   would be better and is a bigger change than this one; it is not proposed here.
5. **"The sampler is unbiased" is a statement about bearing, not about ties.**
   `next_to_placement` still breaks exact score ties by `(x, y)`, i.e. min-x
   wins. Ties in a float approach cost are measure-zero outside exact symmetry
   and no measurement here triggered one, so it was left alone rather than
   perturbing pose selection for a latent issue. Recorded, not fixed.
6. **Dropping `next_to` from three classes is an advertisement change only.** It
   was verified that affordances are consumed solely by
   `voice/scene_reference.py`'s clarification offers — but "verified by reading
   every consumer and running the suite" is not the same as "proved nothing else
   reads it".
7. **The 45 s / 1.80 m drift in the live bench case is reported, not explained.**
   It differs from F-1's 7.5 s / 0.00 m by far more than run-to-run noise (n=2,
   the two runs agree to 0.4 mm), and something between 2026-08-07 and now
   changed it. Out of scope here, and it does not change the verdict: both runs
   still end `semantic_target_unreachable` with both authorities in agreement.
8. **`terminal_person_clearance_m = 0.36 m` is a derivation, not a
   recommendation.** It is written down so the next person does not have to
   re-derive it, together with the three reasons it is the wrong tool for this
   problem.

---

## Files touched

| file | change |
|---|---|
| `src/parcel_robot/instructnav/scoring.py` | `next_to_is_achievable`, `next_to_achievable_anchor_radius_m` — the inequality between the band and the stand-off envelope, written once |
| `src/parcel_robot/instructnav/relations.py` | `next_to_placement`: `band_m` default `(0.4, 0.9)` **deleted** (second band authority) and the argument made required; `PLACEMENT_BEARINGS`/`PLACEMENT_RADII` named with the measured resolution limit |
| `src/parcel_robot/instructnav/__init__.py` | re-export the two new predicates |
| `configs/scenes/city_block.semantics.yaml` | `bench`, `tree`, `planter` drop `next_to`, each with its measured `minimum_vicinity`; `building`'s existing rationale re-stated as derived |
| `configs/scenes/generated/val_unseen_9101{1..5}.semantics.yaml` | re-emitted via `scene_gen.semantics_sidecar_text()` (not hand-edited) |
| `tests/test_scene_semantics.py` | achievability check strengthened to the real stand-off envelope; `test_building_would_fail_...` replaced by the derivation pin + the converse pin |
| `tests/test_owner_and_settle_plans.py` | `test_the_offer_names_only_relations_the_class_actually_affords`: same invariant, examples moved to match the measurement, and now asserts **both** directions (lamppost positive; building/bench/tree negative) |
| `tests/test_next_to_band_achievability.py` | **new**, 12 cases |
| `scrum/20260808/task_3/BENCH_PLACEMENT_STATUS.md` | this file |

**Not touched:** `runtime.py`, `voice/**`, `brain/**`, `core/**`,
`authority.py`, `configs/robot.yaml`, `configs/navigation/**`,
`navigation/reactive_safety.py`, `navigation/collision.py`,
`navigation/pipeline.py`, `navigation/approach.py`, `navigation/grid_planner.py`,
`tests/test_voice_nav_e2e.py`, `evals/**` (code *or* data),
`tests/test_embodied_plan_eval.py`, `tests/test_duplex_v1.py`.

---

## Stopped and reported

1. **B-2(3) — the K0 band change — is proven and not applied.** It moves both
   frozen NAV_INSTRUCT episode digests (exact values above), because the band is
   stored inside the frozen episode payload. Applying it requires a re-freeze of
   10 episode files, 2 manifests, 2 test constants and a ledger row under
   `evals/**`, which this card does not own and which B-2(3) instructs it to stop
   on. The complete one-definition diff, the call-site list, the density raise
   that must travel with it, and the measured per-episode deltas are all above.
2. **The paired protocol as specified cannot be run for this change.** A
   before/after candidate eval would compare two different episode sets. The
   read-only trace re-scoring above is the paired measurement that *is* valid,
   and it says: one episode flips, it is the bench, SR does not move.
3. **The sidecar advertised three impossible affordances, not one.** `bench`,
   `tree` and `planter` all fail the derivation. The old achievability check
   could not see any of them because it tested a point set rather than a body.
4. **`next_to_placement` carried a second band literal** (`(0.4, 0.9)` vs K0's
   `(0.4, 1.5)`) as a default argument. Deleted. It was inert only by the
   accident of having exactly one production caller.
