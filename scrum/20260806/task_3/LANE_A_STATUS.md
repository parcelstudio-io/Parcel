# Lane A — embodiment / config (strata 4+5) · status

**Date:** 2026-08-07 · **Plan:** [docs/STRATA_GENERALIZATION_PLAN.md](../../../docs/STRATA_GENERALIZATION_PLAN.md)
(strata 4+5, the authority triple) · **Audit:**
[docs/NAV_GENERALIZATION_AUDIT.md](../../../docs/NAV_GENERALIZATION_AUDIT.md)
· **Predecessor:** [W0_STATUS.md](W0_STATUS.md) (Wave 0 — untouched by this round).

**Constraint honored: ZERO value changes.** Every edit in this round is a
derivation with a bit-for-bit equality proof. No frozen row, no eval artefact,
no config *value* moved. The one value change the card named (1.25 → 1.2) turned
out to live in files this lane does not own — see
[the 1.25 finding](#the-125-vs-12-drift-is-not-where-the-card-expected-it).

## Outcome per card

| card | outcome |
|---|---|
| A-1 default-argument fixes | **done, and one site more than the card listed.** 5 sites (not 4); 4 of them gained a real `profile=` injection seam. |
| A-2 authority triple | **done**, at `src/parcel_robot/authority.py` with a re-export at the planned `core/authority.py` path. The path split is forced by an import cycle — [see below](#why-the-authority-module-is-not-only-at-coreauthoritypy). |
| A-3 family-by-family migration | **F-robot-radius, F-proximity, F-arrival migrated** with bit-equality proofs. Two families additionally collapsed (F-scan-height, F-obstacle-height). **Edit set 2 (the value change) is empty** — the drift is in unowned files. |
| A-4 drift-prevention tests | **done.** AST ratchet (33 allowlisted sites), 18 Hypothesis properties, half-scale smoke pinned `xfail` and **confirmed red**. |

---

## A-1 — default arguments an injected profile can never reach

A Python default argument binds at import. `RobotProfile` therefore could never
reach any of these, no matter how carefully it was threaded through the caller.
All are now `float | None = None`, resolved in-body.

| site (pre-migration) | now | injection seam |
|---|---|---|
| `mujoco_lidar.py:44,45` `scan_mujoco_lidar` | `robot_radius_m`/`obstacle_height_m` = `None`, resolved by `_resolve_body` | **yes** — new `profile: RobotProfile \| None` kwarg |
| `mujoco_lidar.py:166,167` `planar_geom_surface_hit` | same | **yes** — new `profile=` kwarg |
| `headless_city.py:122` `HeadlessCityWorld.__init__` | `robot_radius_m=None`, resolved from `self.profile` | **yes** — new `profile=` kwarg; also exposes `world.profile` |
| `proxemic_approach.py:68` `ProxemicApproachConfig.robot_radius_m` | `None`, resolved in `__post_init__` via `object.__setattr__` | **yes** — new `profile` field |
| **`approach.py:26` `safe_approach_pose.footprint_clearance_m`** (not in the card's list — found by the census) | `None`, resolved from `DEFAULT_STAND_OFF_ENVELOPE` | **no** — resolves against the module-level default. `obstacle_stop_m` (was `0.8`) got the same treatment. |

**Archon-rule sites** (resolve against a module-level default because no
injection seam exists yet — these are what a pytest-archon rule should forbid
growing):

- `navigation/approach.py` `safe_approach_pose` — resolves `DEFAULT_STAND_OFF_ENVELOPE`.
- `navigation/collision.py` `CollisionPolicy` — class-body defaults read
  `DEFAULT_SAFETY_ENVELOPE`. A per-robot policy needs a `from_envelope`
  constructor; not built (nothing calls it yet).
- `instructnav/scoring.py` `object_near_envelope_m` — resolves
  `DEFAULT_STAND_OFF_ENVELOPE`. Making this per-profile changes goal regions and
  therefore the frozen minival digest; it is a re-freeze card, not this one.
- `mujoco_lidar.py` `DEFAULT_SCAN_HEIGHT_M` — module constant, now
  `DEFAULT_ROBOT_PROFILE.scan_height_m`.

**Still bound as a default argument, unowned:**
`navigation/grid_planner.py:140` `GridPlannerConfig.robot_radius_m =
ROBOT_FOOTPRINT_RADIUS_M`. This is the 6th site and the one that matters most —
it is why the half-scale smoke is red.

---

## A-2 — the authority triple

`src/parcel_robot/authority.py` (implementation) +
`src/parcel_robot/core/authority.py` (re-export at the planned path).

### RobotProfile additions (`robot_profile.py`)

| field | value | provenance | bucket |
|---|---|---|---|
| `decel_max_mps2` | 1.4 | `configs/robot.yaml motion.smoothing.linear_decel` — the jerk-limited shaper's braking authority, the largest deceleration the actuator hand-off actually produces. **Derived from config, not measured on hardware.** | dynamics |
| `reaction_latency_s` | 0.12 | the two live reaction horizons already agree at 0.12 s: `CollisionPolicy.reaction_time_s` and `ReactiveSafetyPolicy.reaction_time_s`. One 10 Hz tick + 0.02 s hand-off. | latency |
| `obstacle_clearance_height_m` | 0.9 | was `geometry.ROBOT_OBSTACLE_HEIGHT_M`, value unchanged | embodiment |
| `footprint_radius_m` | 0.32 | **moved here** from `geometry.ROBOT_FOOTPRINT_RADIUS_M`; value unchanged. `robot_profile.py` no longer imports `geometry`, which is what breaks the cycle. | embodiment |
| `leg_length_m` (property) | 0.426 | `upper_link_m + lower_link_m`. Kinematic length, not standing hip height (`abs(stance_z_m)` = 0.265) — both conventions exist; this one is used consistently. | embodiment |

`from_config` accepts the three new keys and still fails closed on unknown ones.
`DEFAULT_ROBOT_PROFILE = RobotProfile.go2()` is the module-level default every
un-injected site resolves against.

### SpeedRegime

Frozen dataclass. Four regimes (`cruise` / `search` / `approach` / `recover`),
each a `RegimeLimits` with `[vx, vy, vyaw]` **plus** the accel pair
`(accel_mps2, yaw_accel_radps2)`. `from_mapping` fails closed on unknown *and*
missing keys (repo pattern). Reference values transcribed 2026-08-07:

| regime | vx | vy | vyaw | accel | yaw accel | transcribed from |
|---|---|---|---|---|---|---|
| cruise | 0.85 | 0.25 | 0.90 | 0.9 | 1.8 | `grid.yaml controller` + `default.yaml safety.max_vy` |
| search | 0.22 | 0.0 | 0.35 | 0.9 | 1.8 | frontier crawl caps + `default.yaml semantic_search.yaw_rate` |
| approach | 0.35 | 0.25 | 0.75 | 0.9 | 1.8 | `follow.py FollowConfig` |
| recover | 0.12 | 0.0 | 0.35 | 0.9 | 1.8 | `grid.yaml controller recovery_*` |

`SpeedRegime.froude` = `v_cruise^2 / (g * L)` = **0.1729** at Go2 scale (well
below the Fr = 1 walk/run transition, as expected for this gait).

`from_froude(profile, Fr)` sets `v_cruise = sqrt(Fr * g * L)` and carries every
other quantity across by dimensional law, not by a global scale factor:
`v ~ sqrt(lambda)`, `t ~ sqrt(lambda)`, `omega ~ 1/sqrt(lambda)`,
`a ~ lambda^0` (invariant), `alpha ~ 1/lambda`. Measured for a half-size Go2 at
constant Froude: cruise **0.601 m/s** (= 0.85/sqrt(2), *not* 0.425), yaw
**1.273 rad/s** (= 0.90*sqrt(2)), accel **0.9** unchanged, yaw accel **3.6**.

**Arbitration rule, documented and tested, not yet wired:** `arbitrate_limits`
takes the **elementwise minimum**. No authority may raise another's cap; the
effective bound is the componentwise floor. Empty input raises — an absent
authority must never read as permission. `configs/robot.yaml`'s
`safety.max_vx = 0.9` vs `grid.yaml cruise_vx = 0.85` is now also asserted
directly (`test_the_nav_clamp_is_not_below_the_cruise_regime_it_bounds`), which
is the 2026-08-05 miss expressed as a standing check.

### SafetyEnvelope

```
stop_distance(v) = footprint_radius + v*tau + v^2/(2*decel_max) + Zs + Zr
person_stop(v)   = max(person_social_zone, stop_distance(v) + 1.4*tau)
```

Measured at Go2 scale: `stop_distance(0) = 0.32`, `stop_distance(0.85) = 0.680`,
ISO sum at rest `= 0.488`, `person_stop(0) = person_stop(0.85) = 1.2`. **The
human floor binds at every speed this robot reaches** — that is the point, and
`social_zone_is_binding` exposes it.

- `pose_uncertainty_m` (`Z_r`) is **0.0** and is the single field Lane B sets
  when stratum-1 covariance goes live. Property-tested as exactly additive:
  `stop_distance` widens by precisely `Z_r`, every consumer for free.
- `sensing_intrusion_m` (`Z_s`) is **0.0** — no measured value exists yet.
- `person_social_zone_m = 1.2` carries the HUMAN-BUCKET marker
  (`FieldMeta.never_scales`), provenance: the quadruped-proxemics decision
  recorded in the plan.

### Field metadata

Every field of `RegimeLimits`, `SafetyEnvelope` and `StandOffEnvelope` carries a
PX4-style `FieldMeta(unit, source, date, bucket, note)`, reachable via
`cls.field_meta(name)` / `cls.fields_in_bucket(bucket)`; a test asserts
`metadata_covers_every_field()` for all three, so a new field without metadata
is a red build. `FieldMeta` fails closed on an unknown bucket.

**Bucket vocabulary is exactly the four the plan names.** Note the honest
wrinkle: `Z_s` and `Z_r` are sensor/environment properties, not human ones, but
their defining property *is* the human bucket's — they never scale with `L`. They
are filed under `human` and the module docstring says why rather than inventing
a fifth bucket.

### Why the authority module is not only at `core/authority.py`

Measured, not assumed. Importing anything under `parcel_robot.core` executes
`core/__init__.py`, which imports `navigation.velocity_shaping` and therefore
the whole `navigation` package (`navigation/__init__` → `envs` → `pipeline`).
`pipeline` imports `approach`, which imports `instructnav.scoring` — one of the
authority's own consumers. The result is a hard circular import:

```
ImportError: cannot import name 'NEXT_TO_BAND_M' from partially initialized
module 'parcel_robot.instructnav.scoring'
```

An authority that must sit *low* in the import graph cannot live under a package
whose `__init__` sits *high* in it. So the implementation is
`parcel_robot/authority.py` and `parcel_robot/core/authority.py` re-exports the
same objects (asserted by `test_the_core_path_re_exports_the_same_objects` —
identity, not equality). **Handoff:** collapsing the two into one file is a
one-line change once `core/__init__.py` stops eagerly importing `navigation`.
`core/__init__.py` was deliberately **not** edited (another lane holds it) and
the authority was deliberately **not** added to its `__all__`.

---

## A-3 — family-by-family migration, with equality proofs

Branch-by-abstraction, structured as two edit sets. **Edit set 1 (derivation,
bit-for-bit equal) landed. Edit set 2 (value change) is empty** — see the 1.25
finding. Proofs live in `tests/test_authority_family_equality.py`; all use `==`
on floats, never `pytest.approx`.

### F-robot-radius

| derived value | old literal | proof |
|---|---|---|
| `RobotProfile.footprint_radius_m` | `geometry.ROBOT_FOOTPRINT_RADIUS_M = 0.32` | `== 0.32` |
| `RobotProfile.obstacle_clearance_height_m` | `geometry.ROBOT_OBSTACLE_HEIGHT_M = 0.9` | `== 0.9` |
| `mujoco_lidar.DEFAULT_SCAN_HEIGHT_M` | `0.45` | `== 0.45` and `== profile.scan_height_m` |
| `ProxemicApproachConfig().robot_radius_m` | `0.32` | `== 0.32`; injected half profile gives `0.16` |
| `_resolve_body(None, None, None)` | `(0.32, 0.9)` | tuple equality; injected profile gives `(0.16, 0.45)` |
| `HeadlessCityWorld().robot_radius_m` | `0.32` | `== 0.32`, and `world.profile is DEFAULT_ROBOT_PROFILE` |
| `approach.py` `_observed_obstacle_points` ray | `distance + 0.32` | covered by the suite's existing approach tests + the AST scan showing zero `0.32` left in the file |

### F-proximity

| derived value | old literal | proof |
|---|---|---|
| `CollisionPolicy.person_stop_m` = `envelope.person_stop(0.0)` | `1.2` | `== 1.2` (the social-zone branch; ISO sum at rest is 0.488) |
| `CollisionPolicy.person_slow_m` | `2.5` | `== 2.5` |
| `CollisionPolicy.obstacle_stop_m` | `0.6` | `== 0.6` |
| `CollisionPolicy.obstacle_slow_m` | `1.2` | `== 1.2` — this collapses **6 copies** to one authority |
| `CollisionPolicy.reaction_time_s` | `0.12` | `== 0.12`, `== profile.reaction_latency_s` |
| `approach.py` `stop_short_m` (towards) | `1.2` | `StandOffEnvelope.towards_stop_short_m == 1.2` |
| `approach.py` `stand_off_m` default (near) | `1.2` | `near_stand_off_floor_m == 1.2` |
| `approach.py` `obstacle_stop_m` default | `0.8` | `target_surface_clearance_m == 0.8` |
| `approach.py` `terminal_clearance_m` default | `0.32` | `envelope.footprint_radius_m == 0.32` |

`slow_scale = 0.35` was **left a literal on purpose** — it is a dimensionless
comfort scale that merely happens to share a number with the TTC radius. It is
allowlisted as `not-a-radius`, which is exactly the distinction a magic-number
lint could not have made (plan anti-goal: no ruff magic-number lint).

### F-arrival — the stand-off composite

`instructnav/scoring.py object_near_envelope_m` was
`radius + 0.32 + 0.8 + 0.06 + 0.04` with the lamppost case as the bare `1.32`.
Now every term is a named `StandOffEnvelope` field:

```
stand_off(r)        = r + footprint_radius + target_surface_clearance
                        + arrival_radius + stand_off_margin
minimum_vicinity(r) = r + footprint_radius + target_surface_clearance
vicinity(r)         = r + footprint_radius + vicinity_margin
lamppost            = point_anchor_stand_off() = vicinity(0.0)
```

**The `1.32` decomposition, found rather than assumed.** Two candidate readings
were tested numerically:

| candidate | value | bit-equal to `1.32`? |
|---|---|---|
| `footprint + vicinity_margin` = `0.32 + 1.0` | `1.32` | **yes** |
| generic composite at a 0.1 m reference radius | `1.3200000000000003` | no (one ULP high) |

So the lamppost branch is exactly "treat the pole as a zero-radius anchor and
stand off by the full vicinity margin", and it reproduces the literal
bit-for-bit. The rejected reading is pinned by an assertion so nobody
"simplifies" into it. Note this also means the lamppost stand-off was **never**
the generic formula at the lamppost's real radius (0.06 m → 1.28); that
discrepancy is pre-existing and is preserved exactly.

**Equality coverage:** `object_near_envelope_m` is compared against a verbatim
copy of the pre-migration function over 11 radii × 6 labels = **66 exact-equality
assertions**, including every radius the live city scene produces
(`lamp_post 0.06`, `planter 0.45`, `tree 0.58`, `bench_1 0.733757`, and all five
`bldg_*` radii from `scene_truth.json`). All pass with `==`.

### The 1.25-vs-1.2 drift is not where the card expected it

The card scoped the drift resolution to `collision.py` + `proxemic_approach.py` +
`approach.py`. **None of those files contains a 1.25.** A full-tree census
(`grep -rn '1\.25' --include=*.py src/`) finds exactly two proximity-family sites:

| site | value | file owned by Lane A? |
|---|---|---|
| `navigation/follow.py:114` `FollowConfig.obstacle_slow_m` | `1.25` | **no** |
| `city_semantics.py:212` `non_target_obstacle_clearance_m` | `1.25` | **no** |

The `obstacle_slow_m` family is exactly the audit's "6 copies, one drift live":
`collision.py` 1.2, `reactive_safety.py` 1.2, `pipeline.py` 1.2,
`headless_city.py` 1.2, `configs/robot.yaml` 1.2, **`follow.py` 1.25**.

**Consequence, stated plainly: no value change was made, and therefore no paired
NAV_INSTRUCT run was executed.** Running a paired eval for a change that was not
applied would produce a zero delta and prove nothing. The change is handed off
below with its provenance and the exact protocol it needs. The authority side is
already in place: `SafetyEnvelope.obstacle_comfort_band_m = 1.2` is the single
value `follow.py` should derive from, and flipping it becomes a one-line edit
plus a paired run.

### Poisoned constants (PEP 562)

`geometry.py` is now a shim. Both retired names resolve through module
`__getattr__`. Importer census taken 2026-08-07 **before** deciding which to
hard-error:

| name | remaining importers | disposition |
|---|---|---|
| `ROBOT_FOOTPRINT_RADIUS_M` | `navigation/pipeline.py`, `navigation/grid_planner.py`, `navigation/models/__init__.py` — all owned by other lanes | **warn** (`DeprecationWarning`), still returns 0.32 |
| `ROBOT_OBSTACLE_HEIGHT_M` | **zero**, after Lane A migrated `mujoco_lidar`, `headless_city`, `sim` and `tests/test_city_orbit_clearance` | **hard error** (`AttributeError`) |

The three warning importers each emit one `DeprecationWarning` at import. The
project has no `filterwarnings` configuration, so this is visible without being
fatal. `retired_constant_value(name)` is the migration tests' escape hatch.

### Files edited outside the owned set, and why

Three files outside the ownership list had to change because removing a
re-export broke them. All three edits are mechanical and bit-equal:

- `src/parcel_robot/sim.py` — imported `ROBOT_OBSTACLE_HEIGHT_M` *from
  `mujoco_lidar`*. It already had `robot_profile` in scope; now reads
  `robot_profile.obstacle_clearance_height_m`. (Closes one of the audit's
  "one wire short" seams as a side effect.)
- `tests/test_mujoco_lidar.py` — same re-export; now imports
  `DEFAULT_ROBOT_PROFILE`.
- `tests/test_city_orbit_clearance.py` — imported both names from `geometry`;
  migrated so `ROBOT_OBSTACLE_HEIGHT_M` could be hard-errored.

A fourth edit was forced by a **collision with card W4's safety guard**:

- `tests/test_dynamic_layer.py` — `test_the_safety_authority_files_are_untouched_on_this_branch`
  asserted `git status --porcelain` is empty for `navigation/collision.py` **and**
  `navigation/reactive_safety.py`. Lane A's card assigns `collision.py` to this
  lane, so the two cards are in direct conflict.

  Resolution: the guard was **split, not deleted**. `reactive_safety.py` keeps
  its byte-level git check unchanged. `collision.py` gets a stricter,
  *behavioural* guard —
  `test_the_collision_gate_behaviour_is_untouched_on_this_branch` — which
  AST-normalises `apply_collision_brake` and `CollisionPolicy.__post_init__` and
  compares them against `git show HEAD:...`, then compares every live
  `CollisionPolicy` threshold with `==` against the literal that stood at HEAD.
  W4's claim ("the gate only ever reduces an admitted command, and this file did
  not change to make that true") is preserved and is now enforced against
  re-tuning as well as against editing.

  **Negative control run:** replacing the derived `obstacle_slow_m` with a
  hardcoded `1.25` makes the new guard fail (`1 failed`); restoring it passes
  (`1 passed`). The old `git status` guard could not have caught a re-tuned
  constant hidden behind a derivation — this one does.

No file on the DO-NOT-TOUCH list was modified.

---

## A-4 — drift prevention

### (a) AST ratchet — `tests/test_authority_no_literal_drift.py`

Plain `ast`, no ruff plugin. Scans 24 navigation/embodiment modules (the
`navigation/` package plus `geometry`, `robot_profile`, `headless_city`,
`mujoco_lidar`, `sim`, `instructnav/scoring`, `city_semantics`), skipping the
authority modules themselves. Values scanned: `0.32`, `0.35` (F-robot-radius),
`1.2`, `1.25` (F-proximity), `1.32` (F-arrival).

**The ratchet turns both ways.** A new or over-cap occurrence is red; an
allowlist entry whose real count has *dropped* is also red ("lower the cap").
Migrating a site therefore forces a visible one-line record of the shrink.

Allowlist state at hand-off — **33 sites across 17 entries**:

| file | value | count | family | owner |
|---|---|---|---|---|
| `navigation/pipeline.py` | 0.32 | 5 | F-robot-radius | pipeline owner (forbidden this round) |
| `navigation/pipeline.py` | 0.35 | 6 | F-robot-radius | pipeline owner |
| `navigation/pipeline.py` | 1.2 | 1 | F-proximity | pipeline owner |
| `navigation/grid_navigator.py` | 0.35 | 1 | F-robot-radius | grid_navigator owner |
| `navigation/follow.py` | 0.35 | 4 | F-robot-radius | unassigned |
| `navigation/follow.py` | 1.2 | 1 | F-proximity | unassigned (`yaw_gain`, not a distance) |
| `navigation/follow.py` | 1.25 | 1 | F-proximity | unassigned — **the live drift** |
| `navigation/reactive_safety.py` | 1.2 | 1 | F-proximity | unassigned |
| `navigation/dynamic_costs.py` | 0.35 | 1 | F-robot-radius | unassigned |
| `navigation/dynamic_layer.py` | 0.35 | 2 | F-robot-radius | unassigned |
| `navigation/traffic_aware.py` | 0.35 | 3 | F-robot-radius | unassigned |
| `navigation/search.py` | 0.35 | 1 | F-robot-radius | unassigned |
| `city_semantics.py` | 0.32 | 2 | F-robot-radius | Lane C |
| `city_semantics.py` | 1.25 | 1 | F-proximity | Lane C — **the second live 1.25** |
| `headless_city.py` | 1.2 | 1 | F-proximity | Lane A, deferred (scope was default-arg only) |
| `navigation/approach.py` | 0.35 | 1 | not-a-radius | Lane A (metadata clamp bound) |
| `navigation/collision.py` | 0.35 | 1 | not-a-radius | Lane A (`slow_scale`) |

Five files are asserted to hold **zero** family literals:
`instructnav/scoring.py`, `mujoco_lidar.py`, `geometry.py`, `sim.py`,
`navigation/proxemic_approach.py`.

A companion config-side ratchet (`tests/test_authority_config_drift.py`) pins the
YAML surface: the two `robot.yaml` copies must stay byte-identical, the
`SpeedRegime` reference must keep matching `grid.yaml` / `default.yaml`, and the
0.35 TTC radius is pinned **as a known drift** (see handoff).

### (b) Property tests — `tests/test_authority_properties.py`

18 Hypothesis properties over the admissible `RobotProfile` space (link lengths,
footprint, decel, latency, `Z_s`, `Z_r`, speed), 200 examples each:

- **envelope orderings** — `person_stop >= stop_distance + 1.4*tau`; both
  monotone non-decreasing in `v`; `stop_distance(0)` is exactly the static terms;
  `Z_r` is exactly additive;
- **`person_stop >= 1.2 m` at every scale**, plus "scaling the body never moves a
  human-bucket field" and its converse "embodiment fields do follow the body";
- **`from_froude` dimensional sanity** — round-trips through the `froude`
  property, matches the closed form, preserves regime speed ordering, and obeys
  `v ~ sqrt(lambda)` / `omega ~ 1/sqrt(lambda)` / `a` invariant under a random
  length ratio;
- **arbitration** — lower bound on every contributor, order-independent,
  idempotent.

One property is deliberately conditional and worth naming: `person_stop` can
fall *below* `stop_distance` for a body whose own braking distance already
exceeds 1.2 m. The test records that case (`assert stop > social_zone`) rather
than asserting it away — for a large, fast robot the ISO term should dominate
and the social floor stops being the binding constraint.

**Hypothesis is not in `pyproject.toml`.** It was installed into `.parcel` for
this round; the module `importorskip`s so a machine without it skips rather than
reddens. Adding the dev dependency is a handoff (that file is contested).

### (c) Half-scale smoke — `tests/test_authority_half_scale_smoke.py`

Uses the existing `NavInstructRunner` programmatic API on 2 frozen-minival
episodes (`object_goal`, `region_goal`), Go2 vs a geometrically half-size
profile whose regimes are re-derived at the **same Froude number**. No new
harness. Runtime ~6 s.

**`test_half_scale_run_differs_from_the_go2_run` is `xfail` and confirmed
XFAIL** (i.e. the two runs are bit-identical). The assertion is deliberately a
*difference* assertion, not an equivalence one: asserting that a half-size robot
reproduces Go2 outcomes passes today for the wrong reason — it passes precisely
because the body change is being ignored. What scale covariance needs first is
for the change to be **observable at all**.

Attribution, named in the xfail reason:

1. `GridPlannerConfig.robot_radius_m` — footprint inflation, still Go2-pinned
   (asserted directly by a non-xfail test that flips when it is injected);
2. `grid_resolution_m` / `grid_size_cells` — the plan wants these pinned as
   cells-per-footprint; not done (unowned file);
3. K0 arrival bands — Go2-derived in `instructnav/scoring.py` by design;
   re-deriving them per profile moves goal regions and the frozen minival digest.

A companion test asserts the half-scale run still completes with zero collisions,
so a genuine regression is distinguishable from the pinned gap.

---

## Handoff notes

### H-1 · The 1.25 → 1.2 value change (highest priority)

- **Site:** `src/parcel_robot/navigation/follow.py:114`
  `FollowConfig.obstacle_slow_m = 1.25` → derive from
  `parcel_robot.authority.DEFAULT_SAFETY_ENVELOPE.obstacle_comfort_band_m` (1.2).
- **Second site:** `src/parcel_robot/city_semantics.py:212`
  `non_target_obstacle_clearance_m = 1.25`.
- **Provenance for 1.2:** the quadruped-proxemics decision in
  `docs/STRATA_GENERALIZATION_PLAN.md` strata 4+5.
- **Protocol:** this is edit set 2 — a paired-seed run, no `--freeze`. For
  `follow.py` the binding harness is NAV_INSTRUCT (`follow_owner` /
  `circle_owner` families) plus `walk_with_me`; for `city_semantics.py` it is
  NAV_INSTRUCT `object_goal`.
- The equality tests are already green, so the delta will be attributable to the
  value and nothing else.

### H-2 · The five speed authorities (SpeedRegime wiring)

Not wired this round by design. Sites, with what each currently owns:

| # | site | value(s) | consumer |
|---|---|---|---|
| 1 | `configs/navigation/models/grid.yaml` `controller.cruise_vx` etc. | 0.85 / 0.90 / 0.9 / 1.8 | `navigation/grid_navigator.py` |
| 2 | `configs/navigation/default.yaml` `safety.max_vx/max_vy/max_vyaw` | 0.9 / 0.25 / 0.8 | `navigation/pipeline.py:526` clamp |
| 3 | `configs/robot.yaml` `motion.max_vx/max_vy/max_vyaw` | 1.0 / 0.5 / 1.5 | arbiter `SafetyLimits` |
| 4 | `navigation/models/__init__.py:226` + `navigation/pipeline.py:1431` | 0.22 (twice) | frontier crawl — **the pair both 2026-08 speed raises missed** |
| 5 | `navigation/follow.py:105,106` `FollowConfig.max_vx/max_vyaw` | 0.35 / 0.75 | follow controller |

Also in the family but outside the "five": `navigation/search_owner.py:85`
`linear_speed_mps = 0.3`, `configs/navigation/default.yaml`
`semantic_search.yaw_rate = 0.35`.

Wiring shape: each site contributes a `RegimeLimits`; the effective bound is
`arbitrate_limits(...)`. Every one of these files is owned by another lane.

### H-3 · Needs a change in a forbidden/unowned file

| what | where | why it matters |
|---|---|---|
| `GridPlannerConfig.robot_radius_m` default argument → injected profile | `navigation/grid_planner.py:140` | the single biggest blocker for the half-scale xfail |
| grid resolution as cells-per-footprint | `configs/navigation/models/grid.yaml` `grid_resolution_m` / `grid_size_cells`, consumed by `navigation/grid_navigator.py` | stratum-5 first step, not done |
| 5 × `ROBOT_FOOTPRINT_RADIUS_M` uses | `navigation/pipeline.py:11,842,896,1652,1654` | keeps the deprecation warning alive |
| `ROBOT_FOOTPRINT_RADIUS_M` use | `navigation/models/__init__.py:7,359` | same |
| collapse `core/authority.py` into one module | `parcel_robot/core/__init__.py` | needs the eager `navigation` import removed |
| add `hypothesis` to dev extras | `pyproject.toml` | property tests currently skip without it |
| TTC radius 0.35 → 0.32 | `configs/robot.yaml` + `src/parcel_robot/config/robot.yaml`, consumed by `runtime.py` (forbidden), sha256-locked by `evals/companion/embodied_plan_v1/manifest.json` (forbidden) | see H-4 — needs a manifest re-lock in the same change |

### H-4 · The other live radius drift (0.35 TTC)

`safety.time_to_collision.robot_radius_m = 0.35` vs the profile's 0.32 — the
audit's "second inconsistent radius". **Deliberately not changed.** Its only
consumer is `runtime.py`'s TTC gate (forbidden file), and NAV_INSTRUCT never
builds that gate, so the paired run it needs is `walk_with_me` /
`voice_nav_e2e`, not NAV_INSTRUCT. The drift is pinned by
`test_robot_config_ttc_radius_is_the_pinned_f_robot_radius_drift`, so it cannot
widen unnoticed.

**`configs/robot.yaml` is SHA-256-locked and cannot carry documentation.** A
provenance comment was added beside the value and then reverted: the file's
sha256 is pinned in `evals/companion/embodied_plan_v1/manifest.json`
(`f6468887…`), and `tests/test_embodied_plan_eval.py` fails 1 test + 7 errors on
any byte change, including a comment. `configs/robot.yaml` is therefore
**append-only-by-re-lock**, not freely editable, despite being in Lane A's
ownership list. The provenance lives in the test instead. Whoever resolves the
drift must re-lock the manifest (`evals/**`, forbidden this round) in the same
change.

---

## Verification

| check | result |
|---|---|
| `pytest tests/ -q` (final) | **2313 passed, 7 skipped, 5 xfailed, 4 failed** in 662 s. **All 4 reds are outside Lane A's files and were proven so** — see the attribution below. |
| Lane A + neighbour files, re-run after the concurrent edits settled | **290 passed, 1 xfailed, 0 failed** (`test_authority_*`, `test_dynamic_layer`, `test_navigation`, `test_proxemic_approach`, `test_mujoco_lidar`, `test_city_orbit_clearance`, `test_k0_arrival_authority`, `test_instructnav_scoring`, `test_city_semantics`) |
| new tests | **+187** across 6 files (`test_authority_triple` 38, `test_authority_family_equality` 95, `test_authority_no_literal_drift` 22, `test_authority_properties` 18, `test_authority_config_drift` 9, `test_authority_half_scale_smoke` 5 incl. 1 xfail) |
| `ruff check` on every touched file | **clean** (18 findings introduced and all fixed; repo-wide pre-existing findings elsewhere untouched) |
| bit-equality tests green **before** any value change | **yes** — and no value change followed, so nothing to compare against |
| frozen rows / eval artefacts | **untouched.** No file under `evals/` was modified. The frozen minival digest depends on `object_near_envelope_m`, whose output is proven bit-identical over every live scene radius. |
| paired NAV_INSTRUCT delta for the 1.25 → 1.2 change | **not run — the change was not made** (H-1) |

### The four reds, attributed

Another executor (the Lane B pose seam) was landing edits to
`navigation/base.py` (01:39), `headless_city.py` (01:40) and
`navigation/pipeline.py` (01:44) *during* these runs. Each red was chased down
rather than dismissed:

| red | attribution | evidence |
|---|---|---|
| `test_embodied_plan_eval::test_full_gate_executes_physics_and_separates_unsupported` and `::test_correction_waits_for_checkpoint_then_executes_replacement` | **not Lane A.** `simulator_step_count` 1071 vs the pinned 1072 — a one-tick shift on the mission path. | **Reproduced with Lane A's entire diff reverted.** A copy of the working tree was made in scratch, all eight Lane A source edits were surgically reverted to their pre-Lane-A form and `authority.py` deleted; both tests still fail identically. |
| `test_barn_v8_policy_bundle::test_real_historical_bundle_derives_only_the_reviewed_v8_delta` | **not Lane A.** `ImportError: cannot import name '_HAS_POSE' from 'parcel_robot.navigation.base'` inside the frozen BARN bundle snapshot. | `_HAS_POSE` is a symbol Lane B added to `navigation/base.py` today; Lane A never touched that file. (This test also has a pre-existing flake history — W0 recorded it failing once and passing standalone.) |
| `test_habitat2020_contract_smoke::test_real_subprocess_sidecar_smoke_uses_unchanged_config` | **not Lane A — and not reproducible.** | Passes standalone in the live tree (`3 passed`). Full-suite-only, i.e. ordering/contention. |

Two earlier reds were Lane A's and were fixed rather than explained away: the
`configs/robot.yaml` SHA lock (reverted, see H-4) and card W4's `collision.py`
git guard (split into a stricter behavioural guard, with a negative control).

An additional transient was observed and is worth recording for whoever owns
concurrency hygiene: a mid-run `NameError: name 'POSE_PROVIDER_KEY' is not
defined` at `headless_city.py:890`, from reading that file between two of
another executor's writes. It disappeared on re-run.

## Non-claims

- **Nothing was tuned and nothing got safer.** Every number in the running
  system is the number it was yesterday. What changed is that each one now has
  exactly one home, a unit, a provenance, and a scaling law.
- **The authority is not wired into the five speed sites.** `SpeedRegime` is
  constructed, tested, and consumed by nobody. Its reference values are a
  *transcription* of the live configs, kept honest by a test that compares them
  — not a second source of truth the controllers read.
- **`decel_max_mps2 = 1.4` is derived from a config, not measured.** It is the
  shaper's braking authority, which is an upper bound on what the actuator
  produces, not a measured deceleration on hardware. Same for
  `reaction_latency_s = 0.12` — it is the value two modules already agreed on,
  not a latency measurement.
- **`Z_s` and `Z_r` are both 0.0.** The envelope has the ISO/TS-15066 *shape*; it
  does not yet have the ISO/TS-15066 *numbers*, because two of the five terms
  have never been measured on this system.
- **The half-scale smoke does not test a half-scale world.** Only the robot
  shrinks; the city, the goal regions and the scorer stay Go2-scale. A true
  scale-covariance metamorphic pair (scene and robot both scaled) is a separate
  eval-instrument card.
- **Two `1.2` values in `approach.py` were named, not justified.**
  `towards_stop_short_m` and `near_stand_off_floor_m` now have single homes and
  provenance strings pointing at the code they came from. Nobody has established
  that 1.2 m is the right stand-off for either; the drift test just guarantees
  there is now one of each instead of several.
- **The `leg_length_m` convention is a choice.** Froude numbers computed against
  standing hip height (0.265 m) would be ~1.6× larger. Comparisons to published
  Froude numbers must check which length the source used.
- **`tolerated_boundary`, `false_arrival` and the W0 instruments were not
  exercised** by this round — no episode outcome moved, so there is nothing new
  for them to report.
