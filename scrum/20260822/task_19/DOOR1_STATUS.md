# DOOR-1 — through a doorway, and a follow stand-off that obeys config · STATUS

**Card:** `README.md` · **Board:** `../TASK_BOARD.md` · **Design:** `../WAVE2_DESIGN_FABLE.md` §1 (DW-4)
**Executor:** Claude Opus · **Verifier:** Fable · **Date:** 2026-08-22 · **Tree at HEAD** `21ea2fb`
**Pre-registration:** `PREREGISTRATION.md`, sha256
`15a2e8deefc35567e35e155c53fde2e8144c7557163e50dc82676a1359b71f61`,
written `2026-08-22T13:02:01-04:00` — **before the first measurement and before
any source edit**. Frozen copy: `~/.cache/parcel-door1/PREREG.md.frozen` (same sha).

> **HARDWARE FACT, and it governs every number in this document.** No robot
> hardware is on hand (owner, 2026-08-22: only the reSpeaker XVF3800 mic array).
> 0.41 m, 0.45 m, 0.68 m, 1.2 m and every corridor width below are ARITHMETIC
> OVER IN-TREE BODY CONSTANTS and a synthetic lidar corridor in the dev
> simulator. **The 0.70 m person band and the new 0.45 m obstacle band are
> simulator policy on an uncommissioned body — not physical clearance proofs.**
> They ship only inside `configs/robot.prototype.yaml`; `configs/robot.yaml`
> still carries 1.2 m and 0.65 m and its sha256 is unchanged.

---

## Headline

**COMPLETE, with one pre-registered row MISSED and one item HALTED.**

**The dog could not walk through its own front door, and the reason was an
obstacle number.** `safety.obstacle_stop_m` was floored on the shipped
`SafetyEnvelope.obstacle_stop_floor_m` (0.6 m), and the final gate is
DIRECTIONAL: at any ring ≥ 0.6 m it refuses to translate down every corridor
narrower than `2·ring·sin(1.15)` ≥ 1.10 m. At the shipped 0.65 m ring that is
1.19 m — every interior doorway, and no profile could commission its way out.

`safety.obstacle_stop_m` now COMMISSIONS the envelope's obstacle ring
(`SafetyEnvelope.with_obstacle_stop_ring`) under a named hard floor
`OBSTACLE_STOP_FLOOR_M = 0.41 m` — the body's ISO/TS-15066 stopping distance at
the APPROACH regime. Below it the runtime **refuses to boot and names the
floor**. The prototype overlay commissions **0.45 m**.

**Measured on the product path** (product planner + the product final gate),
1400 ticks = 140 s per arm, robot-initiated contact counted every tick:

| corridor | planner routes | ring 0.65 (shipped) travelled | ring 0.45 (prototype) travelled | contacts |
|---:|---|---:|---:|---:|
| 0.80 m | no | 0.0000 m | 0.0000 m | 0 |
| 0.90 m | no | 0.0000 m | 0.0000 m | 0 |
| 1.00 m | no | 0.0000 m | 0.0000 m | 0 |
| 1.05 m | **yes** | **0.0000 m** | **3.1162 m** | 0 |
| 1.10 m | **yes** | **0.0000 m** | **5.7006 m — TRAVERSED** | 0 |
| 1.20 m | **yes** | **0.0014 m** | **5.7011 m — TRAVERSED** | 0 |

Read the two right-hand columns together, because that pair is audit §6 in
metres: **at the shipped ring the product plans a route through a 1.20 m
corridor and then stands still in it — 1.4 mm of travel in 140 s.** At the
commissioned indoor ring it drives through, and through a 1.10 m corridor too,
with zero robot-initiated contact and 0.18 m of minimum wall clearance.

**The follow stand-off now obeys config.** `FollowConfig.desired_distance_m` and
`owner_keepout_m` were import-time constants computed off the SHIPPED social
zone; P1-E pinned the consequence as an open handoff (the prototype booted with
a 0.7 m gate and still held formation at 1.85 m). They now derive per instance:
prototype **1.25 / 1.35 m**, shipped **1.75 / 1.85 m bit-identical**.

**Both production `GridPlannerConfig` sites now pass a float, never `None`** —
`grid_navigator.py` and `search_owner.py`, seeded RED at each site.

**MISSED (pre-registered as MET):** the 0.90 m and 1.00 m corridors. See §3.

**HALTED (one item):** the commissioned ring does not reach production planner
site 1 in the product, because the seam that would carry it is in
`navigation/pipeline.py`, outside DOOR-1's OWNS. See §6.

**The semantics diff is empty.** `apply_reactive_safety` (`f52db9c5…`),
`ReactiveSafetyPolicy.owner_slow_m` (`119af4ad…`) and `_owner_comfort_band_m`
(`7d5050eb…`) are **unchanged**. Exactly one pinned symbol moved for this card,
`ReactiveSafetyPolicy.__post_init__` (`c228b5f8…` → `8c39f4ee…`), the
constructor's validation, with a regeneration log entry in the file.
(`_owner_identity_trusted` also moved on this tree — that is card OT-2, which
owns it and regenerated its own pin.) `core/hard_stop`, the e-stop latch, the
command TTL/watchdog and `SafetySupervisor.validate` carry **zero diff lines**.

---

## 1. What changed

`git diff --numstat` against HEAD `21ea2fb`, **after the correction pass (§10)**. Files marked ⚠ are shared with a
concurrently-executing card; the "mine" column counts only DOOR-1's hunks.

| File | + | − | mine | Note |
|---|---:|---:|---:|---|
| `src/parcel_robot/authority.py` | 349 | 0 | all | `OBSTACLE_STOP_FLOOR_M`, `PLANNER_HARD_MARGIN_M`, `LEGACY_GATE_CLEARANCE_M`, `SafetyEnvelope.with_obstacle_stop_ring` + its floor check, `ClearanceProfile` + `DEFAULT_CLEARANCE_PROFILE`, `__all__` |
| `src/parcel_robot/navigation/reactive_safety.py` ⚠ | 223 | 6 | 5 of 8 hunks | the `authority` import; `__post_init__` obstacle commissioning + its re-raise; the obstacle hull twin beside the person one; `commissioned_envelope` now commissions both rings; new `clearance_profile` property. **The other 3 hunks are card OT-2's identity seam.** |
| `src/parcel_robot/navigation/grid_planner.py` | 23 | 0 | all | the "planner may not relax the final gate" construction guard |
| `src/parcel_robot/navigation/grid_navigator.py` | 60 | 0 | all | `map_gate_clearance_m` kwarg + production site 1 always passing a float |
| `src/parcel_robot/navigation/search_owner.py` | 26 | 0 | all | production site 2 takes the runtime's own commissioned ring |
| `src/parcel_robot/navigation/follow.py` | 63 | 10 | all | the two import-time stand-off constants removed; per-instance derivation in `__post_init__` |
| `configs/robot.prototype.yaml` ⚠ | 96 | 7 | 3 of 5 hunks | `safety.obstacle_stop_m: 0.45` + the uncommissioned/simulator-policy wording + the follow-derivation note. **The other 2 hunks are card VENUE-1's `camera_backend` block.** |
| `tests/test_door1_doorway.py` | 996 | — | all | **new**, 37 tests |
| `tests/test_e2_safety_wiring.py` | 14 | 1 | all | the obstacle probe moved under the new floor — **declared deviation §5.1** |
| `tests/test_prototype_profile.py` ⚠ | 58 | 16 | 4 of 9 hunks | the 1.85 pin P1-E handed to DOOR-1, the overlay's safety block, the MINIMAL base — **declared deviation §5.1** |
| `tests/test_dynamic_layer.py` ⚠ | 76 | 2 | 2 of 3 hunks | the `__post_init__` pin + its log entry — **declared deviation §5.2**. The `_owner_identity_trusted` pin is OT-2's. |

Every edit to an existing file was an exact-match single-occurrence replacement
applied against the file **as re-read at that moment**. No `git add/commit/
stash/checkout/reset/restore` was run. `configs/robot.yaml` was read only and
still hashes to `f7b57dcd…`, the value
`evals/companion/embodied_plan_v1/manifest.json` locks.
`tools/sync_runtime_assets.py --check` → `release parity OK: 91 packaged
file(s) match source`.

### 1.1 The change, in one paragraph

`ReactiveSafetyPolicy.__post_init__` compared the configured `obstacle_stop_m`
against `self.envelope.obstacle_stop_floor_m` — the shipped 0.6 m field — which
made the shipped envelope its own floor. Now:

```python
try:
    self.envelope.with_obstacle_stop_ring(self.obstacle_stop_m)
except ValueError as error:
    raise ValueError(
        f"reactive obstacle_stop_m must not undercut the commissioning floor: {error}"
    ) from error
```

`with_obstacle_stop_ring` raises out of `SafetyEnvelope.__post_init__` when the
value is under `OBSTACLE_STOP_FLOOR_M`, and the gate re-raises it in its own
vocabulary so one line carries both the config key and the floor:

```
ValueError: reactive obstacle_stop_m must not undercut the commissioning floor:
obstacle_stop_floor_m 0.4 m is below the commissioning floor
OBSTACLE_STOP_FLOOR_M (0.41 m) — the Go2's ISO/TS-15066 stopping distance at the
APPROACH regime. Refusing to build a safety envelope.
```

This is exactly the shape card P1-E used one ring out, deliberately: the person
half and the obstacle half of the same problem now read the same way.

### 1.2 Why 0.41 m is the floor

```
OBSTACLE_STOP_FLOOR_M = stop_distance(approach)
                      = footprint + v·tau + v²/2a
                      = 0.32 + 0.35×0.12 + 0.35²/(2×1.4)
                      = 0.405750 m        →  0.41
```

`0.35 m/s` is `SpeedRegime.approach.vx_mps`, which the authority already
transcribes from `FollowConfig.max_vx` — the fastest regime the controller uses
while it is working near an obstacle. Three properties, each a test:

1. **It is strictly above the HULL.** `stop_distance(0.0)` = footprint + Zs + Zr
   = 0.32 m, so no commissioning can put the stop ring inside the robot's own
   body. (`test_the_floor_is_above_the_hull_and_below_the_person_floor`.)
2. **It stays strictly below `PERSON_SOCIAL_ZONE_FLOOR_M` (0.68 m)**, which
   preserves P1-E's property 1: a person can never be commissioned LESS
   clearance than a wall.
3. **It is not the number that decides doorways, and that matters.** At the
   floor the gate would drive a 0.75 m corridor — but the grid planner models
   the body as a DISC (0.32 m) plus `map_safety_margin_m` (0.10 m) and refuses
   anything under 0.84 m regardless. The binding indoor constraint is the
   planner's footprint model, not this floor. §3 measures exactly that.

Written as a literal for the same reason P1-E's is: a floor that moves when
someone retunes `linear_decel` is not a floor.
`test_the_obstacle_floor_is_the_bodys_stopping_distance_at_approach` reddens if
the literal and its derivation part company.

**Uncommissioned.** `decel_max_mps2` and `reaction_latency_s` are config values,
not instrumented ones. There is no robot. This is simulator policy.

### 1.3 One immutable profile, two consumers, independent recomputation

`authority.ClearanceProfile` (frozen) states the commissioned ring ONCE:

* `planner_inflation_m = max(footprint + hard_margin, ring·sin(half_angle))` —
  a `max`, so the planner can only ever be TIGHTER than legacy, never looser;
* `final_gate_ring_m(v) = ring + max(0,v)·tau` — recomputed **from the profile
  alone**, taking no planner input, no planner config and no inflated radius, so
  the two can be COMPARED rather than assumed equal.

Both are monotone non-decreasing in the ring (200-point sweep over
[0.41, 1.20]); `final_gate_ring_m` is monotone in speed (200-point sweep over
[0, 1.0]). `test_the_final_gate_ring_is_recomputed_from_the_profile_alone`
drives the REAL gate and checks it stops just inside the profile's predicted
ring and moves just outside it, at three rings × three speeds.

`ReactiveSafetyPolicy.clearance_profile` is the runtime's commissioning wearing
that type. The gate itself still reads `obstacle_stop_m` directly —
the profile tells the gate nothing, which is the point of an independent
recomputation.

### 1.4 The overlay

```yaml
safety:
  person_stop_m: 0.7
  obstacle_stop_m: 0.45
```

0.45 m because at that ring the gate refuses corridors under
`2 × 0.45 × sin(1.15) = 0.8215 m` instead of 1.1866 m, it clears the 0.41 m
floor by 0.04 m, and — measured — the coupled planner inflation it implies
(0.4107 m) is **below** the planner's own footprint term (0.42 m), so
commissioning it changes no planned route anywhere. The file says in its own
comments that the band is **not commissioned, simulator policy, no robot
hardware on hand**, and names `OBSTACLE_STOP_FLOOR_M`;
`test_the_prototype_overlay_says_the_bands_are_uncommissioned_simulator_policy`
reads the real file for that wording.

---

## 2. Pre-registered rows — measured

Rows verbatim from `PREREGISTRATION.md`; nothing added or reworded after the fact.

| id | pre-registered | measured | verdict |
|---|---|---|---|
| **D1** | `OBSTACLE_STOP_FLOOR_M == 0.41 == round(stop_distance(0.35),2)`; > hull 0.32; < 0.68; `obstacle_stop_m=0.40` raises naming the key and `0.41`; 0.41/0.45 construct | 0.41; `stop_distance(0.35)=0.405750`; refusal text carries `obstacle_stop_m`, `OBSTACLE_STOP_FLOOR_M`, `0.41`; all four construction paths refuse 0.40 | **MET** |
| **D2** | shipped envelope dict, policy and `FollowConfig()` identical, by exact IEEE equality | envelope dict identical (10 fields, `obstacle_stop_floor_m` still 0.6); policy 0.65 / 1.2 / owner_slow 1.3; follow `1.75` / `1.85` bit-identical (`0x1.c000000000000p+0`, `0x1.d99999999999ap+0`); `configs/robot.yaml` sha `f7b57dcd…` unchanged | **MET** |
| **D3** | frozen `ClearanceProfile`; monotone inflation and gate ring; independent recomputation; agrees at 0.45, disagrees at 0.65 | 200-point sweeps monotone in ring and in speed; gate bisection matches `final_gate_ring_m` at 3 rings × 2 speeds; `planner_agrees_with_gate(0.42)` True at 0.45, False at 0.65 | **MET** |
| **D4** | 2 / 2 production sites carry a `gate_clearance_m` float, statically and at runtime | 2 / 2, AST + live objects; the AST check also rejects a literal `None`; both seeded RED (S2, S5) | **MET** |
| **D5** | the planner may not relax the final gate; refusal at construction | guard lands in `GridPlannerConfig.__post_init__`; invariant holds on 200 rings; seeded RED (S3) | **MET** |
| **D6** | 3/3 traversed at 0.90 / 1.00 / 1.20 m, 0 contacts; 0/1 at 0.80 m; control arm 0/1 at 0.90 m | **1 of the 3 pre-registered widths traversed** (1.20 m). 0.90 m and 1.00 m are refused by the PLANNER. 0 contacts on every arm. Control arm: at the shipped ring the 1.20 m corridor is planned and yields **0.0014 m** of travel | **MISSED — see §3** |
| **D7** | planner boundary ≥ gate boundary, margin ≥ 0.05 m; planner 0.90 m, gate 0.8215 m | direction **MET**, numbers **corrected**: gate boundary **0.8628 m** (bisected on the real gate at vx 0.25; arithmetic 0.8215 m plus the predictive term and 2° ray quantisation), planner boundary **1.0000 m** (bisected on the real planner at the PRODUCT 0.10 m grid, not P1-E's 0.05 m harness; `routes(1.0000)=False`, `routes(1.0001)=True`). Margin **0.137 m**, and the planner is the stricter one | **MET (direction); numbers corrected — see §3** |
| **D8** | prototype 1.25 / 1.35; shipped 1.75 / 1.85; overlay's `owner_follow` block removable | through the product `ConfigStore(PARCEL_PROFILE=prototype)` + `FollowConfig.from_mapping`: keepout **1.25**, stand-off **1.35**; a real `RobotRuntime` on the prototype overlay: 1.25 / 1.35; shipped `FollowConfig()` 1.75 / 1.85 bit-identical; with no yaml at all `FollowConfig(person_stop_m=0.7)` → 1.25 / 1.35 | **MET** |
| **D9** | no import-time stand-off constant survives | `follow._FOLLOW_DESIRED_DISTANCE_M` and `follow._OWNER_KEEPOUT_M` are gone; both field defaults are `None`; seeded RED (S4) | **MET** |
| **D10** | 0.70 m band non-default; `configs/robot.yaml` byte-identical; one wording check | `DEFAULT_SAFETY_ENVELOPE.person_social_zone_m == 1.2`, `obstacle_stop_floor_m == 0.6`, `ReactiveSafetyPolicy()` 1.2 / 0.65; shipped yaml unchanged; wording check green | **MET** |
| **D11** | four seeds RED, restored and sha-verified | **five** seeds (site 2 got its own), each RED on a named test, each restored with matching sha256, each re-run green — §4 | **MET** |
| **D12** | semantics diff empty; only `__post_init__` moves, with a log entry | `apply_reactive_safety` / `owner_slow_m` / `_owner_comfort_band_m` unchanged; `__post_init__` `c228b5f8…` → `8c39f4ee…` with a log entry; safety core zero diff lines | **MET** |
| **D13** | targeted baseline 549 passed / 1 xfailed holds, modulo two named files | 838 passed / 5 skipped / 1 xfailed over the extended set (the baseline set plus the search / patrol / follow-bench group and the new file). Zero failures. The two intentional edits are the ones named in advance | **MET** |

**Rows missed: D6. Row corrected under measurement: D7.**

---

## 3. D6 — the miss, and what it actually says

**Pre-registered:** 0.90 m and 1.00 m corridors traversed. **Measured:** the
product planner refuses to route either one, so nothing was traversed. That is a
miss, not a re-narration, and here is the mechanism.

The pre-registered 0.90 m planner boundary was **taken from P1-E's harness,
which runs the planner at a 0.05 m grid resolution.** The PRODUCT planner runs
at **0.10 m** (`configs/navigation/models/grid.yaml` `grid_resolution_m`), and
at that resolution the continuous 0.84 m threshold quantises up to exactly
**1.0000 m** — so a nominal 1.00 m doorway sits precisely on the knife edge.
Measured by bisection on the product planner:

| planner configuration | narrowest corridor it routes (product 0.10 m grid) |
|---|---:|
| un-commissioned default (the scoped coupling ring) | **1.0000 m** |
| commissioned at the prototype ring 0.45 | **1.0000 m** (the coupling is a no-op) |
| coupling ring raised to the shipped 0.65 (H-2's cost, not shipped) | **1.2000 m** |

I should have measured the product's own resolution before pre-registering
instead of inheriting another card's harness number. The row stands as a miss.

**What the miss does NOT mean.** It is not a safety refusal. At the prototype
ring the GATE ADMITS a **0.8628 m** corridor on a single tick (bisected on the
real gate at 0.25 m/s — a centreline admission, NOT a traverse: a traverse also
needs the planner to route it. The static-ring arithmetic is 0.8215 m; the gap
is the gate's predictive `+ v·tau` term and the 2° ray grid). 0.90 m and 1.00 m
are both admitted by the gate and both refused by the planner. What refuses 0.90 m is the planner's DISC
footprint model — 0.32 m radius + `map_safety_margin_m` 0.10 m = 0.42 m of hard
inflation against a 0.45 m half-width, then quantised. A Go2 is ~0.31 m wide and
physically fits a 0.80 m doorway; the disc is a modelling choice, and both of
its terms live in `configs/navigation/**` and `GridPlannerConfig`, which are
card P0-D's OWNS and a frozen-baseline decision respectively.

So the honest statement of what this card achieved indoors is:

> **DOOR-1 removed the SAFETY blocker on interior doorways. The remaining
> blocker is the planner's disc-footprint model plus the 0.10 m grid, and it is
> a different card's number.**

`test_the_measured_corridor_boundaries_at_the_indoor_ring` pins exactly this,
width by width, including the two widths where the gate would go and the planner
will not.

---

## 4. Seeded RED — every new guard

Seven seeds (five in the first pass, two added by the correction pass), each
applied to a **byte-identical scratch copy of `src/`**
(`~/.cache/parcel-door1/seedsrc/`, on `PYTHONPATH`; the repo's own `src/` was
never edited for a seed), each watched to redden a NAMED test, each restored
from the pristine copy, re-verified by sha256, `__pycache__` purged, re-run
green. Script + full transcript: `~/.cache/parcel-door1/seeds.sh`,
`~/.cache/parcel-door1/SEEDS.txt`.

| seed | what was broken | test that reddened | restored sha256 == repo |
|---|---|---|---|
| **S1** | the obstacle floor check disabled in `SafetyEnvelope.__post_init__` | `…::test_an_under_floor_obstacle_ring_refuses_and_names_the_floor` + `…::test_every_envelope_construction_path_lands_on_the_obstacle_floor` | `a0fcdf0a…` YES |
| **S2** | production site 1 back to `gate_clearance_m=None` | `…::test_every_production_planner_site_passes_gate_clearance[grid_navigator]` + `…::test_the_grid_navigator_planner_is_never_built_with_none` | `919f8775…` YES |
| **S3** | `inflation_radius_m` loses its `max` against the gate clearance | `…::test_a_planner_that_relaxes_the_final_gate_refuses_to_construct` | `7a7a7251…` YES |
| **S4** | the follow stand-off silently constant again (`desired_distance_m = 1.85`) | `…::test_the_follow_stand_off_derives_from_the_instance_not_the_import` + `…::test_no_module_level_stand_off_constant_survives_in_follow` | `30b6fbf4…` YES |
| **S5** | production site 2 no longer passes the ring | `…::test_every_production_planner_site_passes_gate_clearance[search_owner]` + `…::test_the_owner_search_planner_takes_the_runtimes_own_commissioned_ring` | `2596557c…` YES |
| **S6** *(correction pass)* | site 2 back to the RAW commissioned ring — the shipped 0.65 m reaching a follow-bench consumer | `…::test_the_owner_search_planner_keeps_its_legacy_inflation_when_shipped` | `2596557c…` YES |
| **S7** *(correction pass)* | site 1's per-profile cap removed (a flat, un-scoped ring) | `…::test_every_grid_model_profile_keeps_its_legacy_inflation` — reddens on `grid_clearance_v2` (0.35 → 0.42 m) | `c8b14a87…` YES |

`diff -r -x __pycache__ src ~/.cache/parcel-door1/seedsrc/src` → **identical**
after all seven. Transcript and script are committed under
`evidence/seeds.txt` and `evidence/seeds.sh`.

One correction made under seeding, recorded because it changed a guard: S2's
first run reddened only the DYNAMIC test, because the static AST check read the
repo path rather than the imported package. Two fixes followed — the check now
resolves its source from `parcel_robot.__file__` (so a seeded copy on
`PYTHONPATH` reddens it too) and it now rejects a literal `gate_clearance_m=None`
as well as a missing keyword. Both S2 tests redden after the fix.

---

## 5. How verified

```
$ TMPDIR unset; .parcel/bin/python -m pytest -q -p no:randomly \
    tests/test_grid_planner.py tests/test_grid_navigator.py tests/test_navigation.py \
    tests/test_planner_quality_v2.py tests/test_planner_quality_sketch_v1.py \
    tests/test_planner_contract_size.py tests/test_authority_{triple,properties,\
    family_equality,config_drift,no_literal_drift,half_scale_smoke}.py \
    tests/test_p1e_social_zone_is_config.py tests/test_prototype_profile.py \
    tests/test_dynamic_layer.py tests/test_e2_safety_wiring.py tests/test_e6_owner_band.py \
    tests/test_follow_{formation,prediction,yield_wiring,bench_v1}.py \
    tests/test_person_{keepout,cell,aware_nav}.py tests/test_city_orbit_clearance.py \
    tests/test_navigation_{model_lock,admission_regression,tracker,inside_resampling}.py \
    tests/test_rm3_route_memory_arms.py tests/test_search_{owner,budget_freeze,instance_selection}.py \
    tests/test_safety_log.py tests/test_brain_safety_wiring.py tests/test_move1_patrol.py \
    tests/test_roam1_behavior.py tests/test_navigator_pause.py tests/test_door1_doorway.py
838 passed, 5 skipped, 1 xfailed in 63.35s
```

Baseline captured BEFORE any edit over the smaller pre-registered subset:
**549 passed, 1 xfailed** (`~/.cache/parcel-door1/BEFORE.txt`). Final:
`~/.cache/parcel-door1/AFTER.txt`.

```
$ .parcel/bin/ruff check <the 6 source files + the 4 test files>
All checks passed!                              # ruff 0.16.1, ratchet untouched
```

No `noqa` was added, no ruff baseline entry was added or re-pinned, no
`scripts/ci_gate.py` tier and no full suite was run (board rule 4).

### 5.0 The product path, named

* **Product planner:** the `RollingGridPlanner` inside the product
  `GridNavigator`, constructed through `ModelRegistry.create("grid_v1")` from
  `configs/navigation/models/grid.yaml` — the same call `DirectiveNavigator`
  makes at `pipeline.py:776` / `:1080`.
* **Product final gate:** `navigation.reactive_safety.apply_reactive_safety`,
  the gate the runtime control loop applies, driven by a `ReactiveSafetyPolicy`
  built from `configs/robot*.yaml` exactly as `RobotRuntime.__init__` builds it
  (`runtime.py:1744`). Every commanded velocity passes through it before it
  moves the body; nothing in the harness moves the body that the gate did not
  admit.
* **Product config:** `ConfigStore('configs/robot.yaml')` with
  `PARCEL_PROFILE=prototype`, i.e. the real overlay, read by the real loader.
  Verified end to end through a real `RobotRuntime` in
  `tests/test_prototype_profile.py::test_the_shipped_prototype_overlay_boots_a_runtime`
  (0.45 ring, 0.7 person stop, 1.25 keepout, 1.35 stand-off).
* **NOT the product:** the corridor WORLD. Two synthetic parallel walls, ray-cast
  into a `LidarScan`. There is no MuJoCo scene, no doorway geometry and no
  physics behind the numbers in §Headline — only the planner and the gate are
  real. Stated here so nobody reads a simulated traverse as a driven one.

### 5.1 Deviation — three test files outside OWNS

The card's OWNS names `tests/test_door1_*.py`. Three existing test files
carried assertions this card's deliverable necessarily moves:

* **`tests/test_prototype_profile.py`** — 4 hunks. The 1.85 m stand-off pin is
  the one **P1-E wrote as an explicit open handoff naming DOOR-1**
  (`task_12/P1E_STATUS.md` §7/§8: *"Pinned as a live assertion … and handed off
  below"*). It now reads 1.35 with the reason in the comment. The overlay's
  safety-block comparison gained `obstacle_stop_m`, and the file's `MINIMAL`
  base config gained `safety.obstacle_stop_m` / `obstacle_slow_m` at their
  SHIPPED values (the overlay-key walk refuses a key the base does not define,
  so this is the same maintenance P1-E did when it added `safety:` there).
* **`tests/test_e2_safety_wiring.py`** — 1 hunk, and the identical class of edit
  P1-E made to this same test for the PERSON half. The probe
  `ReactiveSafetyPolicy(obstacle_stop_m=0.5)` no longer refuses (0.5 ≥ 0.41), so
  it moved to 0.40, under the new floor, with the history in the comment — plus
  a new positive assertion that 0.45 is accepted, which is the deliverable.
* **`tests/test_dynamic_layer.py`** — §5.2.

Every one of these is **tighter or equal**, never weaker: no assertion was
deleted, and two were added.

### 5.2 Deviation — the reactive-safety AST ratchet was regenerated

The card authorises this explicitly ("AST ratchet regenerated with a log entry
if `__post_init__` moves again"). One digest moved for DOOR-1,
`ReactiveSafetyPolicy.__post_init__` `c228b5f8…` → `8c39f4ee…`, with a 25-line
log entry above the pin dict recording what moved (the SOURCE of one number),
what did not (`apply_reactive_safety`, `owner_slow_m`, `_owner_comfort_band_m`),
and that the number is uncommissioned. The `_owner_identity_trusted` digest also
moved on this tree — that is **card OT-2**, which owns the identity-gate source
and regenerated its own pin; DOOR-1 changed exactly one entry in that dict.

### 5.3 Deviation — the two production planner construction sites

`navigation/grid_navigator.py` and `navigation/search_owner.py` are not named in
the card's OWNS line, which says "`navigation/grid_planner.py` inflation". They
were edited because the dispatch's card-specific instruction names them
directly ("the authoritative obstacle/gate envelope into BOTH production
`GridPlannerConfig` construction sites"), and DW-4 does the same. Checked before
editing: neither file, nor `grid_planner.py`, `follow.py` or `authority.py`,
appears in any other wave-2 card's OWNS (`grep -n OWNS scrum/20260822/task_{13..18,26,30..33}/README.md`).
Both edits are additive; `search_owner.py`'s is 1 keyword.

### 5.4 Deviation — the shipped-default ring, decided by the pre-registered rule

`PREREGISTRATION.md` D13 registered the decision rule in advance. The
experiment was run: `DEFAULT_CLEARANCE_PROFILE` flipped to the authoritative
shipped ring (0.65) on a scratch copy, 135 planner/navigator/search rows green.
**But that is not evidence about the frozen NIGHTLY navigation evidence**, which
no row here runs, and the arithmetic says it would move (narrowest routable
corridor 0.84 → 1.19 m). An independent probe of the BARN corpus
(`.cache/external-evals/barn/BARN_dataset`, 300 worlds) was inconclusive: under
a pure disc-connectivity metric **0/300 worlds are routable at EITHER radius**,
i.e. the metric does not reproduce how the BARN arm actually plans, so it
licenses nothing. The saved transcript is
`evidence/barn_probe.txt` (added in the correction pass; the first submission
made this claim with no transcript).

Under the pre-registered fallback the coupling is therefore **SCOPED**: the ring
handed to a planner is the commissioned ring capped at that profile's own
legacy-equivalent ring (`ClearanceProfile.planner_coupling_ring_m`), so no
inflation anywhere is raised. **No frozen route moves, at either site and on
every grid profile in the tree** —
`test_every_grid_model_profile_keeps_its_legacy_inflation` walks all nine
through the product constructor and asserts exact IEEE equality with
`robot_radius_m + effective_hard_margin_m`.

**CORRECTED IN THE CORRECTION PASS — the first submission's version of this
paragraph was wrong in two ways, both frozen-evidence risks. See §10 C-1 and
C-2.** It claimed a flat `LEGACY_GATE_CLEARANCE_M` default and "no frozen route
moves"; in fact site 2 was passing the RAW commissioned ring (0.65 m on the
shipped config, reaching a follow-bench consumer), and the flat cap would have
moved `grid_clearance_v2`'s inflation 0.35 → 0.42 m. Both are fixed and seeded.

---

## 6. HALTED items

**H-1. The commissioned ring does not reach production planner site 1 in the
product.** `search_owner.py` (site 2) already holds the runtime's
`ReactiveSafetyPolicy` and takes `clearance_profile.obstacle_ring_m` from it, so
site 2 is genuinely commissioned. Site 1 (`grid_navigator.py`) is built by
`ModelRegistry.create(model_id, arrive_radius_m=…)` from
`navigation/pipeline.py:776` and `:1080`, and that call does not carry a ring.
It always passes a float now (the authority default, never `None`), but the
prototype's 0.45 m does not reach it.

**The exact seam I need, one line:**

```python
# navigation/pipeline.py, both registry.create call sites
self._navigator = self.registry.create(
    model_id,
    arrive_radius_m=self.arrive_radius_m,
    map_gate_clearance_m=<the commissioned ring>,
)
```

`pipeline.py` is not in DOOR-1's OWNS and the ring's source (robot.yaml's
`safety.obstacle_stop_m`) does not currently reach `DirectiveNavigator` at all —
the pipeline reads `configs/navigation/**`'s own `safety:` block, which has no
`obstacle_stop_m` key. So closing this needs a decision about WHICH config owns
the navigator's ring, which is a `configs/navigation/**` question. **The seam
itself is in nobody's OWNS** — `pipeline.py` appears in no wave-2 card's OWNS
line, including P0-D's, so it needs dispatching rather than handing over
(corrected in the correction pass; the first submission attributed it to P0-D).
**Cost of NOT closing it is currently zero** for the prototype: at
0.45 m the coupled inflation (0.4107 m) is below the planner's own footprint
term (0.42 m), so the commissioned value would change no route
(`test_the_prototype_ring_makes_the_planner_and_the_gate_agree` proves the
no-op). It becomes non-zero the moment anyone commissions a ring above
`LEGACY_GATE_CLEARANCE_M` = 0.4601 m.

**H-2. Lifting the cap so a planner actually couples to a gate that demands MORE
room than the planner already leaves** is a re-freeze of the nightly navigation
evidence (BARN bundles, nav_instruct minival, FOLLOW_BENCH_V1) and DOOR-1 is
forbidden to re-pin it.

**Scope, stated exactly, because the first submission got this wrong (§10 C-1).**
The coupling is wired at BOTH production sites and is **inert at both** wherever
the cap binds:

| | site 1 `grid_navigator.py` | site 2 `search_owner.py` |
|---|---|---|
| passes a float, never `None` | yes | yes |
| receives the real commissioned ring | no — the seam is H-1 | **yes** (`runtime.py:1809` injects the runtime's policy) |
| coupling ACTIVE on the prototype (0.45) | n/a (H-1) | yes, and it is a no-op: 0.4107 < 0.42 |
| coupling DEFERRED on the shipped config (0.65) | yes | **yes — capped at 0.4601, inflation stays 0.42** |

`ClearanceProfile.planner_coupling_is_deferred` is the machine-readable form of
the last row and is asserted both ways by
`test_the_coupling_is_tighter_only_and_says_when_it_is_deferred`.

The cost of lifting the cap, so whoever owns the baselines does not have to
re-derive it: planner inflation 0.42 → 0.5933 m, narrowest routable corridor
0.84 → 1.19 m continuous (1.0000 → 1.2000 m at the product's 0.10 m grid); at
the owner-search planner's 0.20 m grid the inflated non-traversable set around a
point obstacle grows 18 → 30 cells (+67%, the verifier's measurement).
`ClearanceProfile.uncapped_planner_inflation_m` states the cost per profile.
One-line change: drop the `min(...)` in `planner_coupling_ring_m`.
**Do not re-run or re-freeze any baseline to do it** — that is the owner's call
and the verifier's gate.

**OT-2's envelope seam: NOT halted.** OT-2 published its seam in
`navigation/reactive_safety.py` while this card was executing, with an explicit
stability contract for DOOR-1 ("nothing above this marker moved;
`OWNER_STAND_OFF_MARGIN_M` keeps its name, value and meaning"). That is the only
thing DOOR-1 consumes from it. Read read-only; nothing was needed that was
missing.

---

## 7. What this does not prove

* **No physical clearance is commissioned. There is no robot.** 0.41 m and
  0.45 m are arithmetic over config values (`decel_max_mps2`,
  `reaction_latency_s`, `footprint_radius_m`) that nobody has measured on a
  body. A real commissioning would instrument a stop and derive the floor from
  `a_meas` and `tau_e2e`. Until then the prototype band is simulator policy.
* **No real doorway, no real wall, no real person.** The corridors are two
  synthetic parallel walls ray-cast into a lidar scan. The dev scene's own
  doorway (`entry_wall_1`↔`entry_wall_2`, 0.800 m) was NOT driven — the product
  planner refuses 0.80 m (§3), so there was nothing to drive.
* **The 0.80 / 0.90 / 1.00 m doorways are still closed to the product**, and the
  blocker is the planner's disc footprint plus the 0.10 m grid, not this card's
  envelope. A Go2 is ~0.31 m wide and physically fits all three.
* **The prototype's ring does not reach the navigator's planner** (§6 H-1). What
  is measured through the planner at 0.45 m is the planner as it ships (0.42 m
  inflation), which happens to equal what the commissioned ring would produce.
* **The 1.05 m corridor is a PARTIAL, not a pass.** The robot entered and
  travelled 3.12 m of 5.70 m in 140 s and did not finish; the gate's slow band
  floors translation at 0.15× and the controller oscillates at that width. It is
  reported as measured, not rounded up.
* **The gate's LOGIC was not re-measured behaviourally beyond the corridors.**
  The evidence that the gate did not change is the AST ratchet plus 838 green
  tests, not a fresh bisection of every ring (that is `test_e6_owner_band.py`'s
  job, and it is green).
* **The nightly evidence ratchets were not run** (board rule 4), so "no frozen
  row moves" rests on the bit-identity of the default inflation
  (`test_the_legacy_planner_inflation_is_bit_identical`) and on the 838-row
  targeted suite — not on a nav_instruct or FOLLOW_BENCH re-run.
* **`navigation/arrival_semantics.py:SOCIAL_STANDOFF_M` is still 1.2 m**
  (import-time), so "go next to the person" still targets 1.2 m under a 0.7 m
  profile. P1-E flagged it; it is outside DOOR-1's OWNS too. Still open.
* **Concurrency.** Five other wave-2 executors were writing this tree
  throughout. Every number here was taken from the tree as it stood at the
  moment of the command shown.

---

## 8. Owner-gated rows

**None new.** Nothing in this card needs the owner, hardware, a camera or hosted
spend. What it does add to the standing queue:

* When a body exists, **every clearance number in this card is re-derived from
  an instrumented stop** — `OBSTACLE_STOP_FLOOR_M`, `PERSON_SOCIAL_ZONE_FLOOR_M`
  and both prototype bands. Until then they stay simulator policy and the file
  says so.
* A **taste call** the owner may want on the prototype ring: 0.45 m of wall
  clearance indoors is close. It is 0.04 m above the floor the body could stop
  in at the approach regime, and it is a wall, not a person (the person ring is
  unchanged at 0.7 m and still dominates). Cheap to move: one line in
  `configs/robot.prototype.yaml`.

---

## 9. Handoffs

* **`navigation/pipeline.py` (whoever owns the navigator's config seam) —
  H-1 above.** One kwarg at two `registry.create` call sites, plus a decision
  about which config owns the navigator's ring. Zero behavioural cost today.
* **P0-D / `configs/navigation/**` — the doorway that is still closed.** The
  first-ODD widths (0.80–1.00 m) are refused by `map_safety_margin_m` (0.10 m)
  and `grid_resolution_m` (0.10 m), not by any safety envelope. A 0.80 m doorway
  needs a hard margin ≤ 0.075 m AND a finer grid, or a non-disc footprint model.
  Blast radius: every frozen navigation baseline. Measured boundaries are in §3.
* **Whoever re-freezes the nightly navigation evidence — H-2 above.** Coupling
  the shipped profile costs planner inflation 0.42 → 0.5933 m.
* **`navigation/arrival_semantics.py`.** `SOCIAL_STANDOFF_M` should read the
  commissioned zone rather than `PERSON_SOCIAL_ZONE_M` — P1-E's handoff, still
  open, still outside OWNS.
* **Card P1-E's corridor numbers** (`P1E_STATUS.md` §2.1: "legacy planner
  admits 0.90 m") were measured at a 0.05 m grid; the PRODUCT planner is 0.10 m
  and admits **1.0000 m** (the 0.05 m grid reproduces P1-E's 0.9000 m exactly).
  Both are correct for their harness; the product number is the one that decides
  doorways.
* **Verifier — where to look first.**
  1. **§3.** It is the pre-registered miss and the one place a reader could come
     away over-claiming. The two numbers that matter are the gate boundary
     (0.8628 m, single-tick) and the planner boundary (1.0000 m), both bisected on the real
     objects by `test_the_planner_is_the_stricter_of_the_two_at_the_indoor_ring`.
  2. **The two-column headline table.** The control arm (shipped ring, 1.20 m
     corridor, 0.0014 m of travel) is the whole claim in one row and it is
     reproducible in one command: `pytest tests/test_door1_doorway.py::test_the_shipped_ring_plans_a_corridor_it_then_refuses_to_drive`.
  3. **`tests/test_dynamic_layer.py`'s pin dict and its log.** Three digests
     unchanged, one moved by DOOR-1, one moved by OT-2. Falsifiable in one command.
  4. **`~/.cache/parcel-door1/SEEDS.txt`** — the five seeds, their RED runs,
     their sha-verified restores and their GREEN re-runs, in one transcript.
  5. **§5.4** — the shipped-default decision, and the BARN probe that did NOT
     license flipping it.
* **Not run here, by the board's rule:** the full suite and
  `scripts/ci_gate.py`. `pyproject.toml` and `scripts/ci_gate.py` were never
  opened. No `evals/nav_instruct/results/ledger.jsonl` append; no minival run.

---

## 10. Correction pass (2026-08-22, after Fable's verification)

Verdict on the first submission: **ACCEPT with corrections.** The headline was
independently reproduced — Fable's verifiers built the product planner through
`ModelRegistry.create("grid_v1")` from the unmodified `grid.yaml`, passed every
proposed velocity through `apply_reactive_safety`, and measured 0.0000–0.0014 m
of travel at the shipped 0.65 m ring against 5.7011–5.7013 m at 0.45 m, 0
contacts, 0.2304 m wall clearance. Two findings were **frozen-evidence risks I
had missed and had actively mis-stated**, one was a wrong published number, and
the rest were honesty/scoping notes. All are corrected in place above and
recorded here rather than silently edited.

Refuted by the verifier's own skeptic pass, no action taken: the E2 probe
re-aim, the injected-floor construction check, the "relaxes-the-gate test is a
tautology" reading, and `with_obstacle_stop_ring` overwriting an injected
stricter floor (fail-closed by construction).

### C-1 (major) — H-2 was NOT halted; site 2 was live on the shipped profile

**The finding.** `search_owner.py` passed
`gate_clearance_m=self._safety_policy.clearance_profile.obstacle_ring_m`, and
`runtime.py:1809` injects the runtime's own policy — **0.65 m on the shipped
`configs/robot.yaml`**. So site 2's planner hard inflation moved 0.42 → 0.5933 m
on every un-commissioned runtime. The verifier found the consumer that makes
this a frozen-evidence risk and I had not:
**`evals/companion_nav/runner.py:213` constructs `SearchOwnerController`, and the
follow-bench is a hard-safety gate row.** Measured cost at the search planner's
0.20 m grid: the inflated non-traversable set around a point obstacle grows
**18 → 30 cells (+67%)**.

§5.4's "the shipped default is `LEGACY_GATE_CLEARANCE_M` … no frozen route
moves" and H-2's "not done" were **true of site 1 only**. That is the worst kind
of error in this document: a claim of safety that was accurate about the half I
was looking at.

**The fix — scoping, not re-pinning.** No baseline was run, re-run or
re-frozen. `ClearanceProfile` gained `planner_coupling_ring_m` =
`min(commissioned ring, legacy-equivalent ring)`, and both sites resolve through
it. Result, measured:

| profile | commissioned ring | ring passed to the planner | hard inflation | deferred? |
|---|---:|---:|---:|---|
| shipped `configs/robot.yaml` | 0.65 | 0.4601 (capped) | **0.42 — unchanged** | yes |
| `configs/robot.prototype.yaml` | 0.45 | **0.45 (through)** | 0.42 — unchanged | no |

`ClearanceProfile.planner_coupling_is_deferred` makes the deferral a value the
code carries rather than a sentence in a doc, and
`uncapped_planner_inflation_m` states H-2's cost per profile. Seeded RED as
**S6**. §5.4 and §6 H-2 are rewritten to say which site is coupled, which is
capped, and what lifting the cap costs.

### C-2 (major, same class) — the bit-identity claim held only at a 0.10 m margin

**The finding.** "Bit-identical for an un-commissioned profile" was checked
against `GridPlannerConfig`'s default 0.10 m hard margin only.
`configs/navigation/models/grid_clearance.yaml` (`grid_clearance_v2`) runs
`map_hard_safety_margin_m: 0.03` — a 0.35 m footprint term — and a flat
module-level `LEGACY_GATE_CLEARANCE_M` cap (lateral demand 0.42 m) would have
raised it **0.35 → 0.42 m**. Same class as C-1: a frozen route moving as a side
effect of wiring a seam.

**The fix.** The cap is per-profile:
`ClearanceProfile.legacy_equivalent_ring_m` = `(footprint + THIS profile's hard
margin) / sin(half_angle)`, so `grid_clearance_v2` is capped at 0.3835 m and
keeps 0.35 m exactly. Site 1 computes it from the margins it is constructing
with; site 2 uses the default-margin profile, which is the config it builds.
`LEGACY_GATE_CLEARANCE_M`'s docstring now says it is the value for the default
margin only and points at the property.

**The row the verifier asked for**, added:
`test_every_grid_model_profile_keeps_its_legacy_inflation` walks **all nine**
grid profiles in `configs/navigation/models/` through the PRODUCT constructor
and asserts `inflation_radius_m == robot_radius_m + effective_hard_margin_m` by
exact IEEE equality. Measured: 9/9 unchanged (`grid_clearance_v2` 0.35;
the other eight 0.42000000000000004). Seeded RED as **S7**.

### C-3 (minor, numbers) — the planner boundary is 1.0000 m, not 1.05 m

My §3 table came from a 0.05 m-step sweep and published 1.05 m; the assertion I
wrote (`1.00 < planner_boundary <= 1.05`) was a 0.05-wide window that admitted
both the true value and the published one. Re-bisected on the real objects with
this file's own helpers:

| | measured |
|---|---:|
| planner boundary, authority default and prototype 0.45 | **1.0000 m** (`routes(1.0000)=False`, `routes(1.0001)=True`) |
| planner boundary, coupling ring raised to 0.65 | **1.2000 m** (was published as 1.25) |
| gate single-tick admission boundary at 0.45, vx 0.25 | **0.862842 m** |
| **D7 margin** | **0.137 m** (was published as 0.187) |
| full product path at 1.0001 m | routed, travelled 0.2647 m |
| P1-E's 0.05 m grid, for comparison | reproduces **0.9000 m** exactly |

Corrected in §3, D7, §6 H-2, §9 and in `configs/robot.prototype.yaml`. The
assertion is now `pytest.approx(1.0000, abs=1e-3)` — the published number is the
one the test pins. `1.05` was replaced by `1.0001` in the boundary table so the
knife edge is pinned: **a nominal 1.00 m doorway does not route; 1.0001 m does.**
**The D6 MISS itself stands unchanged** — 0.80 / 0.90 / 1.00 m are all still
refused by the planner.

### C-4 (notes) — five honesty items, all acted on

1. **The control arm was not the pre-registered one and pinned a 20 s horizon
   against a 140 s headline.** The pre-registered control was 0.90 m; the
   delivered one is 1.20 m (the pre-registered width is refused by the planner,
   so there was no route to refuse). The test now runs **1400 ticks = 140 s**,
   the same horizon as the traversal arm, so control and treatment are
   comparable. Both facts are stated here rather than left to be noticed.
2. **"The gate will drive a 0.8628 m corridor" was wrong wording** — it is a
   SINGLE-TICK centreline admission, not a traverse. Reworded in §3, in the
   parametrised boundary table's comment, in `_gate_drives_corridor`'s new
   docstring and in the overlay, each time alongside the static-ring 0.8215 m so
   the two questions are not conflated.
3. **The BARN probe had no saved transcript.** Re-run and committed as
   `evidence/barn_probe.txt`, verdict included: **inconclusive, licenses
   nothing** (0/300 routable at BOTH radii, so the metric does not model the
   BARN arm).
4. **D9 was verified for `follow.py` only.**
   `navigation/arrival_semantics.SOCIAL_STANDOFF_M` is still an import-time
   1.2 m on a product path. Now pinned as a KNOWN GAP by
   `test_the_arrival_stand_off_is_still_an_import_time_constant`, which asserts
   the gap EXISTS so that closing it is deliberate rather than drift.
5. **`GridPlannerConfig`'s new construction guard is unreachable** while
   `inflation_radius_m` keeps its `max` — it is a seed detector (S3), not a live
   gate. Said so in the guard's own comment and in the test's docstring.
   Also recorded: the **name collision** between `authority.OBSTACLE_STOP_FLOOR_M`
   (0.41 m, the commissioning floor) and
   `evals/nav_instruct/route_memory_cells.OBSTACLE_STOP_FLOOR_M` (0.6 m, the
   envelope field) — flagged in the authority docstring, not renamed.
   And **H-1's seam is in nobody's OWNS**: `pipeline.py` appears in no wave-2
   card's OWNS line, P0-D's included, so it needs dispatching rather than
   handing over. Re-attributed in §6 and §9.

### C-5 — verification after the corrections

```
$ .parcel/bin/python -m pytest -q -p no:randomly tests/test_door1_doorway.py
37 passed

$ <the same 39-file targeted set as §5, TMPDIR unset>
842 passed, 5 skipped, 1 xfailed in 65.10s        # was 838 before the pass

$ .parcel/bin/ruff check <the 6 source files + the 4 test files>
All checks passed!

$ bash evidence/seeds.sh
7 seeds, each RED on a named test, each restored with a matching sha256,
each re-run green; diff -r -x __pycache__ src <scratch>/src → identical
```

`tests/test_follow_bench_v1.py` is inside that set and is green — the row C-1
put at risk. Still not run, by the board's rule: the full suite,
`scripts/ci_gate.py`, and any nightly evidence ratchet. No baseline was re-run
or re-frozen; no ledger was appended.

### C-6 — what the correction pass did NOT change

* The headline. Every number in it was independently reproduced by the verifier
  and none moved.
* The D6 MISS. 0.80 / 0.90 / 1.00 m are still refused by the planner's
  disc-footprint model, and DOOR-1 still does not open a real doorway.
* The floor (0.41 m), the prototype bands (0.7 / 0.45 m), the refusal
  behaviour, the AST-ratchet position, or anything in the safety core.
* The hardware fact. There is still no robot, and every clearance number in this
  document is still simulator policy on an uncommissioned body.
