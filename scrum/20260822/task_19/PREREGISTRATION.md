# DOOR-1 — PRE-REGISTRATION

**Written BEFORE any measurement and before any source edit.**
Card: `README.md` · Board: `../TASK_BOARD.md` · Design: `../WAVE2_DESIGN_FABLE.md` §1 (DW-4)
Executor: Claude Opus · Verifier: Fable · Tree at HEAD `21ea2fb`.

**HARDWARE FACT (owner, authoritative, 2026-08-22): no robot hardware is on
hand — only the reSpeaker XVF3800 mic array.** Every clearance number below is
SIMULATOR POLICY derived from in-tree body constants. None of it is a physical
proof, none of it is commissioned, and no number here may be read as a
measured stopping distance of a real Go2.

---

## 0. The arithmetic the rows are derived from (stated first, so it cannot be fitted afterwards)

All quantities are `base_center_to_obstacle_surface`
(`authority.CLEARANCE_CONVENTION`). Body constants from `RobotProfile` /
`SafetyEnvelope`: footprint `r = 0.32 m`, reaction latency `tau = 0.12 s`,
decel `a = 1.4 m/s^2`. Gate cone half-angle
`GATE_TOWARD_HALF_ANGLE_RAD = 1.15 rad`, `sin(1.15) = 0.912763940260521`.

```
stop_distance(v)      = 0.32 + 0.12 v + v^2 / 2.8
stop_distance(0.00)   = 0.320000   (the hull)
stop_distance(0.12)   = 0.339543   RECOVER
stop_distance(0.22)   = 0.363686   SEARCH
stop_distance(0.35)   = 0.405750   APPROACH   <-- the proposed obstacle floor
stop_distance(0.85)   = 0.680036   CRUISE     (P1-E's person floor, 0.68)

gate_lateral_clearance(ring) = ring * sin(1.15)
narrowest corridor the GATE will drive down      = 2 * ring * sin(1.15)
narrowest corridor the PLANNER will route through = 2 * max(r + hard_margin, ring*sin(1.15))
                                                  = 2 * max(0.42, ring*0.9128)
```

| ring | gate lateral | gate-passable width | planner inflation | planner-passable width |
|---:|---:|---:|---:|---:|
| 0.65 (shipped) | 0.593297 | 1.1866 | 0.593297 | 1.1866 |
| 0.60 | 0.547658 | 1.0953 | 0.547658 | 1.0953 |
| 0.50 | 0.456382 | 0.9128 | 0.456382 | 0.9128 |
| **0.45 (proposed prototype)** | **0.410744** | **0.8215** | **0.42 (unchanged)** | **0.8400** |
| 0.41 (proposed floor) | 0.374233 | 0.7485 | 0.42 (unchanged) | 0.8400 |

Down the centreline of a corridor of width `w` the nearest obstacle INSIDE the
gate's cone is at `(w/2)/sin(1.15)`:

| w | nearest in-cone obstacle |
|---:|---:|
| 0.80 | 0.438229 |
| 0.90 | 0.493008 |
| 1.00 | 0.547787 |
| 1.20 | 0.657344 |

---

## 1. Pre-registered rows

Every row is MET or MISSED. A row that is neither is a MISS.

### D1 — the obstacle envelope has a named floor, and it refuses
`authority.OBSTACLE_STOP_FLOOR_M == 0.41`, equal to
`round(stop_distance(SpeedRegime.approach.vx_mps), 2)` (0.405750 -> 0.41).
`0.41 > stop_distance(0.0) = 0.32` (never inside the hull) and
`0.41 < PERSON_SOCIAL_ZONE_FLOOR_M = 0.68` (P1-E's property 1 preserved: a
person is never commissioned less clearance than a wall).
`ReactiveSafetyPolicy(obstacle_stop_m=0.40)` **raises** and the message names
both `obstacle_stop_m` and `0.41`; `0.41` and `0.45` construct.

### D2 — the shipped defaults do not move, in any digit
`DEFAULT_SAFETY_ENVELOPE.as_dict()` identical field-for-field to the
pre-change dict (`obstacle_stop_floor_m` still `0.6`).
`ReactiveSafetyPolicy()` -> `obstacle_stop_m 0.65`, `person_stop_m 1.2`,
`owner_slow_m 1.3`. `FollowConfig()` -> `owner_keepout_m 1.75`,
`desired_distance_m 1.85`, by exact IEEE equality with the pre-change values.
`configs/robot.yaml` sha256 unchanged (still equal to the value
`evals/companion/embodied_plan_v1/manifest.json` locks).

### D3 — one immutable commissioned profile; two consumers
A frozen `authority.ClearanceProfile` carrying the commissioned ring, the
body envelope and the planner's hard margin, with:
* `planner_inflation_m = max(footprint + hard_margin, ring*sin(half_angle))`;
* `final_gate_ring_m(v) = ring + max(0,v)*tau` — recomputed from the PROFILE
  ALONE, taking no planner input, so it is independent of the planner;
* both monotone non-decreasing in the ring (checked on a 200-point sweep of
  rings in [0.41, 1.20]) and `final_gate_ring_m` monotone in speed
  (200-point sweep of v in [0, 1.0]);
* `planner_agrees_with_gate(inflation)` TRUE at the prototype ring 0.45 with
  the legacy 0.42 inflation, FALSE at the shipped ring 0.65 with the same
  inflation.

### D4 — both production `GridPlannerConfig` sites pass a float, never `None`
The two production construction sites are
`navigation/grid_navigator.py` (the `grid_v1` controller's planner) and
`navigation/search_owner.py` (the owner-search planner). Row: an AST walk over
both files finds a `gate_clearance_m=` keyword on every `GridPlannerConfig(...)`
call, AND the config object each site actually builds at runtime has
`gate_clearance_m is not None`. **Pre-registered: 2 / 2 sites.**

### D5 — the planner may never relax the final gate
`GridPlannerConfig.__post_init__` refuses a configuration whose
`inflation_radius_m` is below the lateral clearance its own `gate_clearance_m`
implies. Checked at the prototype ring, the shipped ring, and a 200-point ring
sweep.

### D6 — HEADLINE: the doorway/corridor scenarios, on the product path
**Product path, named:** the product planner is the `RollingGridPlanner`
inside the product `GridNavigator`, constructed through
`ModelRegistry.create("grid_v1")` from `configs/navigation/models/grid.yaml`
(the same call `DirectiveNavigator` makes). The final gate is
`navigation.reactive_safety.apply_reactive_safety` driven by the
`ReactiveSafetyPolicy` that `RobotRuntime.__init__` builds from the merged
`PARCEL_PROFILE=prototype` `ConfigStore`. Every commanded velocity is passed
through that gate before it moves the body, exactly as the runtime control
loop does.

Corridor = two parallel walls, robot starting on the centreline, goal beyond
the far end, sensed by a real `LidarScan`. Widths and pre-registered verdicts:

| width | planner routes | gate traverses | robot-initiated contact |
|---:|---|---|---:|
| 0.80 m | **NO — predicted MISS** | n/a | n/a |
| 0.90 m | YES | YES | 0 |
| 1.00 m | YES | YES | 0 |
| 1.20 m | YES | YES | 0 |

**Pre-registered pass rate: 3 / 3 at 0.90 / 1.00 / 1.20 m with zero
robot-initiated contact; 0 / 1 at 0.80 m.**

The 0.80 m miss is pre-registered as a miss WITH ITS MECHANISM, so it cannot
be re-narrated afterwards: the planner models the body as a DISC of radius
0.32 m and adds `map_safety_margin_m = 0.10` (both from
`configs/navigation/models/grid.yaml`, which is card P0-D's OWNS, not
DOOR-1's), giving a hard inflation of 0.42 m against a half-width of 0.40 m.
**No safety envelope is involved in that refusal** — at the proposed
prototype ring the GATE would drive a 0.80 m corridor (0.8215 m is its
threshold... which 0.80 m is below, so the gate refuses too at ring 0.45;
at the floor ring 0.41 the gate's threshold is 0.7485 m and the gate would
pass, and the planner still would not).

Control arm, to show the card did something: the SAME 0.90 m corridor with
the SHIPPED ring 0.65 is refused by the gate (0.493008 < 0.65).
**Pre-registered: 0 / 1 traversed on the control arm.**

### D7 — the planner neither proposes what the gate refuses nor relaxes the gate
Measured by bisection on the product planner and on the product gate under the
prototype profile:
* narrowest corridor the PRODUCT PLANNER routes through: **0.90 m**
  (continuous threshold 0.84 m, quantised to the 0.05 m grid);
* narrowest corridor the PRODUCT GATE drives down: **0.8215 m** (continuous).
* Row: `planner_boundary >= gate_boundary`, margin `>= 0.05 m`.
This is the direction that matters: the planner is the STRICTER of the two, so
it never proposes a corridor the gate will always refuse; and because
`inflation_radius_m` takes a `max` against the gate's own lateral clearance it
can never be commissioned looser than the gate either.

### D8 — the follow stand-off obeys config
Through a REAL `RobotRuntime`:
* `PARCEL_PROFILE=prototype`: `follow.config.owner_keepout_m == 1.25` and
  `follow.config.desired_distance_m == 1.35` (= 1.25 + `OWNER_STAND_OFF_MARGIN_M` 0.10).
  **This intentionally moves `tests/test_prototype_profile.py`'s pinned 1.85**,
  which P1-E wrote as an open handoff naming DOOR-1 (`P1E_STATUS.md` §7/§8).
* shipped `configs/robot.yaml`: `1.75` / `1.85`, unchanged.
* with the overlay's `owner_follow` block absent, `owner_keepout_m` derives to
  `0.7 + 0.55 = 1.25` and `desired_distance_m` to `1.35` — one number, no
  second literal.

### D9 — no import-time stand-off constant in profile-dependent behaviour
`FollowConfig.desired_distance_m` and `FollowConfig.owner_keepout_m` no longer
default to an import-time constant computed off `DEFAULT_SAFETY_ENVELOPE`;
they derive from the INSTANCE in `__post_init__`. Checked by grep (no
`_FOLLOW_DESIRED_DISTANCE_M` default survives) and by constructing
`FollowConfig(person_stop_m=0.7, owner_collision_envelope_m=0.55)` with no
yaml at all and getting 1.25 / 1.35.

### D10 — the 0.70 m band stays non-default and simulator-only
`DEFAULT_SAFETY_ENVELOPE.person_social_zone_m == 1.2`;
`ReactiveSafetyPolicy().person_stop_m == 1.2`; `configs/robot.yaml` byte-identical.
`configs/robot.prototype.yaml` states IN THE FILE that the 0.70 m person band
and the new obstacle band are **simulator policy on an uncommissioned body,
with no robot hardware on hand** — one wording check, asserted by a test that
reads the real file.

### D11 — seeded RED, one per new guard
Four seeds, each applied to a byte-identical scratch copy of `src/`, each
watched to redden a NAMED test, each restored and re-verified by sha256 with
`__pycache__` purged:
* **S1** the obstacle floor removed -> `test_door1_*::…obstacle_floor…` RED.
* **S2** a production site back to `gate_clearance_m=None` -> D4's test RED.
* **S3** the planner relaxes the final gate (`inflation_radius_m` loses its
  `max` against the gate clearance) -> D5's test RED.
* **S4** the follow stand-off silently constant again -> D8/D9's test RED.

### D12 — the semantics diff is empty
The AST ratchet in `tests/test_dynamic_layer.py` shows `apply_reactive_safety`,
`ReactiveSafetyPolicy.owner_slow_m`, `_owner_comfort_band_m` and
`_owner_identity_trusted` **unchanged**. Exactly one pinned symbol may move,
`ReactiveSafetyPolicy.__post_init__` (the constructor's validation), and its
pin is regenerated with a log entry in the file, as P1-E did.
`core/hard_stop.finalize_command`, the e-stop latch, the command TTL/watchdog
and `SafetySupervisor.validate` carry **zero diff lines**.

### D13 — no frozen row moves (and the decision rule if one does)
Baseline captured BEFORE any edit, at HEAD `21ea2fb` + the working tree as
found: **549 passed, 1 xfailed** over
`tests/test_grid_planner.py tests/test_grid_navigator.py tests/test_navigation.py
tests/test_planner_quality_v2.py tests/test_planner_quality_sketch_v1.py
tests/test_planner_contract_size.py tests/test_authority_{triple,properties,
family_equality,config_drift,no_literal_drift,half_scale_smoke}.py
tests/test_p1e_social_zone_is_config.py tests/test_prototype_profile.py
tests/test_dynamic_layer.py tests/test_e2_safety_wiring.py
tests/test_e6_owner_band.py tests/test_follow_{formation,prediction,yield_wiring}.py
tests/test_person_{keepout,cell,aware_nav}.py tests/test_city_orbit_clearance.py
tests/test_navigation_model_lock.py tests/test_rm3_route_memory_arms.py`
(saved at `~/.cache/parcel-door1/BEFORE.txt`).

Row: after the change the same command is **549 passed, 1 xfailed**, with the
only intentional assertion edits being (a) the 1.85 pin in
`tests/test_prototype_profile.py` that P1-E handed to DOOR-1, and (b) the
`__post_init__` digest in `tests/test_dynamic_layer.py`.

**DECISION RULE, registered in advance.** DW-4 asks the AUTHORITATIVE ring
into both planner sites. At the SHIPPED ring (0.65) that raises the planner's
inflation 0.42 -> 0.593 and its narrowest routable corridor 0.84 -> 1.187 m,
which is a behaviour change to the shipped navigation profile and therefore a
re-freeze of the nightly navigation evidence (BARN bundles, nav_instruct
minival, FOLLOW_BENCH_V1) that DOOR-1 does not own and is forbidden to re-pin.
So:
* If wiring the authoritative shipped ring keeps the baseline at 549/1, it
  ships as the default.
* If it reddens ANY row, the shipped default becomes the named, derived
  legacy-preserving ring `LEGACY_GATE_CLEARANCE_M = (0.32+0.10)/sin(1.15)
  = 0.4601408770378502 m` — the largest ring whose lateral clearance the
  legacy footprint inflation already covers, so shipped planning is
  byte-identical — the coupling still passes a float at both sites (D4 holds),
  and **the shipped-profile coupling is reported as a HALTED item** with the
  exact re-freeze cost above. Prototype behaviour is unaffected either way
  (0.45 -> 0.4107 < 0.42, the coupling is a no-op there).

---

## 2. What this pre-registration does NOT claim

* No physical clearance is commissioned. There is no robot. 0.41 m, 0.45 m,
  0.68 m and 1.2 m are all arithmetic over in-tree constants.
* No real doorway, no real person, no real wall. The corridors are synthetic
  lidar geometry in the dev simulator.
* The 0.80 m doorway is pre-registered as a MISS. Reaching it needs the
  planner's disc-footprint model or `map_safety_margin_m` to move, both of
  which live outside DOOR-1's OWNS.
* Nothing here proves the reactive gate's LOGIC is unchanged beyond what the
  AST ratchet states; no fresh behavioural bisection of the person rings is
  run (that is `tests/test_e6_owner_band.py`'s job).
