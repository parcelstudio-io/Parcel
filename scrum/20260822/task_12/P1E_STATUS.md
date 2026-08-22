# P1-E — the social zone is a config, not a constant · STATUS

**Card:** `README.md` · **Board:** `../TASK_BOARD.md` · **Verifier's note:**
`../WAVE_P0_VERIFICATION_FABLE.md` (row **A-1**, the minimal change)
**Executor:** Claude Opus · **Verifier:** Fable · **Date:** 2026-08-22
**Pre-registration:** `/home/jaewoo-jang/.cache/parcel-p1e/PREREG.md`, written
`2026-08-22T02:32:45-04:00` (sha256 `bb888918…`), **before** the first
measurement and before any of the four source edits.

---

## Headline

**COMPLETE. Every pre-registered row was met; none was missed.**

`safety.person_stop_m` now COMMISSIONS `SafetyEnvelope.person_social_zone_m`
instead of being floored by it, under a named hard floor
`PERSON_SOCIAL_ZONE_FLOOR_M = 0.68 m` — the Go2's own ISO/TS-15066 stopping
distance at cruise. `configs/robot.prototype.yaml` carries `person_stop_m: 0.7`
and a runtime **boots** on it; a value below the floor **refuses to boot** and
names the floor.

**The card's third clause — "the planner and the gate agree on one envelope" —
is NOT delivered, and is handed to DOOR-1** (`../task_19`). What landed is the
derivation and the measurement, not the agreement: see §1.3.

**Measured where it bit.** MOVE-1's owner-standoff arm (`held_static`, static
city, 40 s, fresh sim on a pid-unique socket), re-run twice:

| arm | `person_stop_m` | net displacement | owner centre distance at rest | clearance | contact |
|---|---:|---:|---:|---:|---:|
| control | 1.2 (shipped) | **0.312756 m** | 1.75977 m | 1.20977 m | 0 ticks |
| treatment | 0.7 (prototype) | **0.843330 m** | 1.26011 m | **0.71011 m** | 0 ticks |

Pre-registered treatment prediction: **0.84258 m**. Measured **0.84333 m** —
**agreement to 0.75 mm**. Control reproduces MOVE-1's 0.3134 m to 0.6 mm. The
dog now walks up to 0.71 m of its owner and stops there, and it does it without
one robot-initiated contact.

**The semantics diff is empty.** The repo's own AST ratchet
(`tests/test_dynamic_layer.py`) holds `apply_reactive_safety` at
`f52db9c50cd6efe3958471a87d7f53e7ef3ba7b0038c895422dd0d7a4cf6bded`,
`ReactiveSafetyPolicy.owner_slow_m` at `119af4ad…`, `_owner_comfort_band_m` at
`7d5050eb…` and `_owner_identity_trusted` at `5262d3ed…` — **all four
unchanged**. Exactly one pinned symbol moved, `ReactiveSafetyPolicy.__post_init__`
(`e01bcca9…` → `c228b5f8…`), which is the constructor's validation and nothing
else. `core/hard_stop.finalize_command`, the e-stop latch, the command
TTLs/watchdog and `SafetySupervisor.validate` carry **zero diff lines**.

---

## 1. What changed

`git diff --numstat` against HEAD `904edd2`.

| File | + | − | Note |
|---|---:|---:|---|
| `src/parcel_robot/authority.py` | 116 | 1 | floor constant + `__post_init__` refusal + `with_person_social_zone` + `gate_lateral_clearance_m` + the gate-cone constant |
| `src/parcel_robot/navigation/reactive_safety.py` | 88 | 2 | `envelope` dataclass field; the two floor checks read it; **two** derived properties (`commissioned_envelope`, `planner_inflation_m`, `:226-256`); comments. **No gate logic** — see §8 for the honest hunk-by-hunk shape. |
| `src/parcel_robot/navigation/grid_planner.py` | 45 | 4 | `gate_clearance_m` + the inflation derivation; footprint read off the authority instead of the deprecation shim |
| `configs/robot.prototype.yaml` | 38 | 27 | the blocker comment replaced by the `safety` block it blocked, plus the paired `owner_follow` keepout |
| `tests/test_p1e_social_zone_is_config.py` | 482 | — | new, 28 tests |
| `tests/test_prototype_profile.py` | 62 | 19 | 3 hunks — **declared deviation §6.1** |
| `tests/test_e2_safety_wiring.py` | 16 | 2 | 2 hunks — **declared deviation §6.1** |
| `tests/test_person_keepout.py` | 7 | 1 | 1 hunk — **declared deviation §6.1** |
| `tests/test_person_cell.py` | 8 | 2 | 1 hunk — **declared deviation §6.1** |
| `tests/test_dynamic_layer.py` | 26 | 1 | AST-ratchet pin regenerated + its log entry — **declared deviation §6.2** |

Every edit to an existing file was an exact-match single-occurrence replacement
applied against the file as re-read at that moment. No `git add/commit/stash/
checkout/reset/restore` was run. `configs/robot.yaml` was **read only** and its
sha256 still equals the one `evals/companion/embodied_plan_v1/manifest.json`
locks (`test_the_overlay_did_not_move_the_sha_locked_shipped_config`, green).
`tools/sync_runtime_assets.py --check` → `release parity OK: 91 packaged
file(s) match source`.

### 1.1 The change, in one paragraph

`ReactiveSafetyPolicy.__post_init__` used to compare the configured
`person_stop_m` against `DEFAULT_SAFETY_ENVELOPE.person_stop(0.0)` — the
SHIPPED social zone, 1.2 m. That made the shipped commissioning value its own
floor: no profile could set an indoor stand-off, and the 0.7 m overlay P0-A
wanted did not relax the robot, it stopped the robot from booting. Now:

```python
commissioned = self.envelope.with_person_social_zone(self.person_stop_m)
if self.person_stop_m + 1e-12 < commissioned.person_stop(0.0):
    raise ValueError("reactive person_stop_m must not undercut …")
```

`with_person_social_zone` raises out of `SafetyEnvelope.__post_init__` when the
value is under `PERSON_SOCIAL_ZONE_FLOOR_M`, and the gate re-raises it in its
own vocabulary so one line carries both the config key and the floor:

```
ValueError: reactive person_stop_m must not undercut the commissioning floor:
person_social_zone_m 0.6 m is below the commissioning floor
PERSON_SOCIAL_ZONE_FLOOR_M (0.68 m) — the Go2's ISO/TS-15066 stopping distance
at cruise. Refusing to build a safety envelope.
```

The obstacle floor check moved from `DEFAULT_SAFETY_ENVELOPE.obstacle_stop_floor_m`
to `self.envelope.obstacle_stop_floor_m` in the same edit — the "three floor
checks read `self.envelope`" half of row A-1 — so a scaled body brings its own
terms. The floor is enforced on **every** construction path (`from_mapping`,
`from_profile`, `replace`, `with_person_social_zone`), which
`test_every_construction_path_lands_on_the_floor` asserts.

### 1.2 Why 0.68 m is the floor

The card asked for "a named constant at the commissioning band … pick it from
the audit's hardware section and say why". **The audit artifact is not in this
tree** (`grep -ril` finds no §6/§11 text anywhere under `scrum/`), so the floor
is derived from the in-tree hardware authority instead and the substitution is
declared here rather than implied:

```
PERSON_SOCIAL_ZONE_FLOOR_M = stop_distance(cruise)
                           = footprint + v·τ + v²/2a
                           = 0.32 + 0.85×0.12 + 0.85²/(2×1.4)
                           = 0.680036 m        →  0.68
```

`0.85 m/s` is `SpeedRegime._REFERENCE_CRUISE.vx_mps`, which the authority
already transcribes from `configs/navigation/models/grid.yaml`; the other three
terms are `RobotProfile.footprint_radius_m` / `reaction_latency_s` /
`decel_max_mps2`. Three properties make it the right floor, and each is a test:

1. **It dominates both obstacle floors** (`SafetyEnvelope.obstacle_stop_floor_m`
   0.60 and `reactive_safety._REACTIVE_OBSTACLE_STOP_FLOOR_M` 0.65), so a person
   can never be commissioned less clearance than a wall.
2. **The gate's predictive term still covers the ISO sum at top speed.** At the
   floor, `person_stop_m + max_vx·τ = 0.68 + 1.0×0.12 = 0.80 m ≥
   stop_distance(1.0) = 0.7971 m`. Had the floor been the obstacle ring (0.65)
   this would have failed by 0.027 m — that arithmetic is what chose 0.68 over
   the easier answer.
3. **Every term is a Go2 quantity**, which is what a real commissioning record
   pins — as opposed to the 1.2 m social zone, which is a proxemics preference.

Written as a literal, because a floor that moves when someone retunes
`linear_decel` is not a floor; `test_the_floor_is_the_bodys_stopping_distance_at_cruise`
reddens if the literal and its derivation ever part company.

### 1.3 One number, two consumers

`ReactiveSafetyPolicy.planner_inflation_m` → `GridPlannerConfig.gate_clearance_m`.
The conversion is the gate's own geometry, and it lives in the authority:

```python
gate_lateral_clearance_m(ring) = ring · sin(GATE_TOWARD_HALF_ANGLE_RAD)
```

Derivation: the gate stops only for obstacles inside a ±1.15 rad cone about
travel (`_toward`). Down a straight corridor of half-width `h`, the nearest
obstacle INSIDE that cone is at `h / sin(half_angle)`, so the gate refuses to
translate exactly when `h ≤ ring·sin(half_angle)` — which is the inflation
radius a planner needs in order not to plan what the gate will refuse.
`GATE_TOWARD_HALF_ANGLE_RAD` is pinned against the gate function's **own
signature** by `test_the_gate_cone_named_in_the_authority_is_the_cone_the_gate_uses`,
so the planner derives from the cone without importing the gate and without
copying the number.

At the shipped obstacle ring: `0.65 × sin(1.15) = 0.5933 m` versus the legacy
footprint-only `0.32 + 0.10 = 0.42 m`. **That 0.17 m is audit §6's "planner and
gate disagree", in metres**: the gate already refuses every corridor narrower
than 1.19 m while the planner plans through anything wider than 0.84 m.

### NOT DELIVERED: "the planner and the gate agree on one envelope"

Stated plainly, because the card's *Proves* line claims it and this card did
not earn it:

* `gate_clearance_m` defaults to `None` and **nothing in the product sets it**.
  The two production construction sites — `grid_navigator.py:228` (from the
  `map_*` kwargs of `configs/navigation/**`) and `search_owner.py:624` — both
  build a `GridPlannerConfig` without it. **Shipped planner inflation is still
  0.42 m while the gate still refuses corridors under 1.19 m.** The
  disagreement audit §6 names is unchanged in the running product.
* `planner_inflation_m` is keyed on `obstacle_stop_m`, **not** on the social
  zone this card moved. So even wired, it would be the OBSTACLE envelope
  agreeing with the planner, not the person envelope — "one envelope, two
  consumers" is true of the *mechanism* and not yet of the *robot*.

What this card did deliver on that clause: the derivation (`gate_lateral_clearance_m`,
pinned to the gate's own cone), the field, and the measurement of what turning
it on would cost (§2.1). **The wiring is handed to DOOR-1** (`../task_19`),
which now owns the obstacle envelope and the planner coupling together — the
right order, because the coupling is only safe once `safety.obstacle_stop_m`
is itself a config with a floor.

**Why the default is `None` rather than on** — a decision, not an omission:

* At the shipped ring the coupled radius closes every corridor under 1.19 m —
  **including a standard 0.8–0.9 m interior doorway**. An indoor companion that
  refuses to plan through its own front door is the opposite of this wave's
  directive. (The dev scene's own doorway, `entry_wall_1`↔`entry_wall_2`, is
  0.800 m.)
* Defaulting it on moves the frozen `nav_instruct` v4 baseline, the BARN
  bundles and FOLLOW_BENCH_V1 in one step — all owned by other cards.
* Turning it on is a navigation-profile decision (`configs/navigation/**`,
  P0-D's OWNS) and needs a paired run, not a planner default.

Handed off in §7 with the one-line change and the blast radius named.

### 1.4 The overlay

```yaml
safety:
  person_stop_m: 0.7

owner_follow:
  owner_keepout_m: 1.25
```

Both key paths already exist in `configs/robot.yaml`, so P0-A's overlay key
walk accepts them and **no `OVERLAY_INTRODUCIBLE_KEYS` entry was needed** — see
§6.3 for why this departs from row A-1's `safety.envelope.person_social_zone_m`
spelling. The long blocker comment P0-A left in the file was replaced by the
history, the fix and the reason for 0.7, so the file still explains itself.

---

## 2. Pre-registered rows — measured

Rows verbatim from `PREREG.md`; nothing was added or reworded after the fact.

| id | pre-registered | measured | verdict |
|---|---|---|---|
| **P1** | `PERSON_SOCIAL_ZONE_FLOOR_M == 0.68`; `SafetyEnvelope(person_social_zone_m=0.679)` raises naming `0.68`; 0.68 and 0.7 construct | 0.68; `stop_distance(0.85) = 0.680036`; refusal text names the constant and the number; 0.68/0.7/1.2/2.0 all construct | **MET** |
| **P2** | prototype `safety.person_stop_m == 0.7`; a real runtime boots with `person_stop_m == 0.7`, `owner_slow_m == 0.80`, `owner_keepout_m == 1.25` | all four exactly | **MET** |
| **P3** | `person_stop_m: 0.6` → `RobotRuntime` construction raises, message names `0.68`; refusal, not a clamp | raises `ValueError`; message contains `person_stop_m must not undercut`, `PERSON_SOCIAL_ZONE_FLOOR_M`, `0.68`; no runtime object is produced | **MET** |
| **P4** | no profile: `DEFAULT_SAFETY_ENVELOPE.as_dict()` and `ReactiveSafetyPolicy()` unchanged; resolved-config sha256 still `0eebb529…` | envelope dict identical (10 fields); policy `0.65 / 1.2 / 1.2 / 2.5 / owner_slow 1.30 / τ 0.12`; sha256 `0eebb5290e20fed7dab8f0fcb7b0829871fcbe173b60ed20a4b296df83ff94dc`, 5274 bytes | **MET** |
| **P5** | `GridPlannerConfig().inflation_radius_m == 0.42`; with `gate_clearance_m=0.65` → `0.65·sin(1.15) = 0.59328`; three dev-scene corridors classified before/after | 0.42000000000000004 and 0.5932965611693387 exactly; corridor table below | **MET** |
| **P6** | control 0.3134 ± 0.05, treatment 0.84258 ± 0.05, gain ≥ +0.45 m, contact 0 on both | **0.312756** / **0.843330**, gain **+0.530574 m**, `collision_ticks` **0 / 0** | **MET** |
| **P7** | three seeds RED, each restored and sha-verified | §4 | **MET** |

**Missed rows: none.** Deviations from the card's method (not from the rows)
are declared in §6 and are all in the *method*, not in the numbers.

### 2.1 P5 — the corridors, measured on the real planner

Widths quantise to the 0.05 m grid, so the continuous thresholds (0.84 m legacy,
1.187 m coupled) land at 0.90 m and 1.20 m. Boundaries found by bisection on
`RollingGridPlanner` + a real `LidarScan` of two parallel walls:

| planner configuration | narrowest corridor it will plan |
|---|---:|
| legacy (`gate_clearance_m=None`) | **0.90 m** |
| coupled at the obstacle ring (0.65) | **1.20 m** |
| coupled at the prototype person ring (0.70) | **1.30 m** |

**The three dev-scene corridors.** The card says "the three dev-scene corridors
the audit names"; with the audit absent, they were selected by a script that
parses `scenes/city_block.xml`, keeps only geoms whose z-extent crosses the
0.45 m scan height, drops movable bodies, and takes the narrowest un-occluded
gaps:

| corridor | width | legacy planner | coupled planner | the GATE |
|---|---:|---|---|---|
| `bldg_4` ↔ `tree_2` | 0.700 m | refuse | refuse | refuse |
| `bldg_1` ↔ `tree_1` | 0.750 m | refuse | refuse | refuse |
| `bldg_1` ↔ `bench_back` | 0.770 m | refuse | refuse | refuse |
| (`entry_wall_1` ↔ `entry_wall_2`, the doorway, if `door_1` were open) | 0.800 m | refuse | refuse | refuse |

**A null result, reported as one.** Every static corridor in `city_block` is
narrower than the LEGACY planner's own threshold, so coupling changes no verdict
in the dev scene: planner and gate already agree there. The full pairwise sweep
finds exactly one static gap in the disagreement band (0.84–1.187 m) —
`bldg_1`↔`entry_wall_1` at 1.050 m — and it is **occluded** by `entry_wall_2`
and `door_1`, so it is not a corridor at all. The disagreement is real
arithmetic (the boundary table above, and
`test_the_planner_stops_choosing_corridors_the_gate_refuses`, which flips at
1.00 m and 1.10 m); this scene simply does not exercise it.

---

## 3. How verified

```
$ TMPDIR=~/.cache/parcel-p1e .parcel/bin/python -m pytest -q -p no:randomly \
    tests/test_p1e_social_zone_is_config.py tests/test_prototype_profile.py \
    tests/test_authority_{triple,properties,config_drift,family_equality,half_scale_smoke,no_literal_drift}.py \
    tests/test_grid_planner.py tests/test_e2_safety_wiring.py tests/test_e6_owner_band.py \
    tests/test_person_{keepout,cell,aware_nav}.py tests/test_next_to_band_achievability.py \
    tests/test_yield_aside.py tests/test_follow_yield_wiring.py tests/test_dynamic_layer.py \
    tests/test_nominal_stop_wiring.py tests/test_unroutable_goal_release.py \
    tests/test_p4_place_graph.py tests/test_arrival_semantics.py tests/test_fail_closed_limits.py \
    tests/test_follow_bench_v1.py tests/test_runtime.py tests/test_headless_city_tasks.py \
    tests/test_mujoco_lidar.py tests/test_sa2_live_pipeline.py tests/test_p0d_navigation_unblocks.py \
    tests/test_move1_patrol.py tests/test_barn_frontier_detour_v4.py \
    tests/test_barn_safe_valley_{v5,guard_v6}.py tests/test_rm2_route_memory_product_path.py \
    tests/test_nav_instruct_episodes_v4.py tests/test_runtime_activation.py
992 passed, 5 skipped, 1 xfailed in 47.94s

$ .parcel/bin/ruff check <the four OWNS files + the five touched test files>
All checks passed!

$ .parcel/bin/python tools/sync_runtime_assets.py --check
release parity OK: 91 packaged file(s) match source
```

That set is every test file in the tree that mentions `reactive_safety`,
`ReactiveSafetyPolicy`, `GridPlannerConfig`/`grid_planner`, `SafetyEnvelope`,
`person_stop`, `person_social_zone` or `PARCEL_PROFILE`. Per the board, the full
suite and `scripts/ci_gate.py` are the verifier's, not this card's, and neither
was run here.

**One transient, attributed.** An earlier pass of the same command showed
`test_prototype_profile.py::test_realtime_prototype_example_validates_and_carries_its_departures`
failing; it reads `configs/realtime.yaml.example` and
`configs/realtime.prototype.yaml.example`, which P0-B/P2-B are editing in this
tree. It passes alone and passed on the clean re-run above. Nothing in this card
touches `realtime/**`.

**One foreign red, attributed and NOT fixed.**
`tests/test_c3_cutover.py::test_the_online_map_package_is_not_modified_by_this_card`
fails because `src/parcel_robot/online_map/__init__.py` is modified in the
working tree — P1-B's file, P1-B's card. This card never opened `online_map/`.

---

## 4. Seeded RED — every new guard

Each mutation was applied to the product source, the suite re-run, the file
restored from a pre-mutation copy, and the sha256 verified identical before and
after (`authority.py` `875696eb…`, `grid_planner.py` `9f4357b7…`,
`robot.prototype.yaml` `2081c5c7…`).

**(a) The floor removed** — `SafetyEnvelope.__post_init__`'s refusal replaced by
`pass`:

```
FAILED test_p1e…::test_below_the_floor_the_envelope_refuses_and_names_the_floor[0.0]
FAILED test_p1e…::test_below_the_floor_the_envelope_refuses_and_names_the_floor[0.3]
FAILED test_p1e…::test_below_the_floor_the_envelope_refuses_and_names_the_floor[0.6]
FAILED test_p1e…::test_below_the_floor_the_envelope_refuses_and_names_the_floor[0.679]
FAILED test_p1e…::test_every_construction_path_lands_on_the_floor
FAILED test_p1e…::test_the_gate_refuses_below_the_floor_naming_both_the_key_and_the_floor
FAILED test_p1e…::test_a_below_floor_config_refuses_to_boot_and_names_the_floor
FAILED test_prototype_profile.py::test_indoor_person_standoff_is_floored_by_the_safety_authority
FAILED test_e2_safety_wiring.py::test_the_person_floor_guard_is_now_symmetric_with_the_obstacle_guard
FAILED test_e2_safety_wiring.py::test_the_runtime_constructed_policy_reflects_the_yaml_not_a_hidden_literal
FAILED test_person_keepout.py::test_d15_pin_is_a_veto_only_under_the_retune
FAILED test_person_cell.py::test_person_stop_10_counterfactual_is_labelled_derived_not_run
12 failed, 92 passed
```

**(c) A below-floor overlay boots** — seed (a) still applied, and the real
`configs/robot.prototype.yaml` edited to `person_stop_m: 0.6`:

```
SEED-RED (c): overlay person_stop_m = 0.6 -> policy BUILT with person_stop_m = 0.6 (no refusal)
```

i.e. with the floor gone the overlay walks the prototype's person clearance
0.08 m under the distance the body can stop in, silently. Both files restored;
`104 passed` on the restored tree.

**(b) The planner inflation decoupled from the envelope** —
`inflation_radius_m`'s `max(…, self.gate_lateral_clearance_m)` replaced by the
footprint term alone:

```
FAILED test_p1e…::test_the_planner_inflation_derives_from_the_same_envelope_quantity
FAILED test_p1e…::test_the_planner_stops_choosing_corridors_the_gate_refuses[1.0-True-False]
FAILED test_p1e…::test_the_planner_stops_choosing_corridors_the_gate_refuses[1.1-True-False]
3 failed, 25 passed
```

Restored; `28 passed`.

---

## 5. The MOVE-1 re-run, in detail

**Pre-registered before the harness was copied**, from MOVE-1 §1.4's own
closed-form stop condition `hypot(2.0 − x, 0.5) = person_stop_m +
owner_collision_envelope_m + v·τ`:

| | predicted | measured | error |
|---|---:|---:|---:|
| control (1.2) | 0.3117 m (MOVE-1's own arithmetic; measured there at 0.3134) | **0.312756** | 0.6 mm vs MOVE-1 |
| treatment (0.7) | `hypot(2−x,0.5) = 0.7+0.55+0.09×0.12 = 1.26080` → **0.84258** | **0.843330** | **0.75 mm** |

Both arms: `motion_accepted 160`, `motion_rejected 0`, `collision_ticks 0`,
`pose_samples 400`, fresh simulator, `--static-city`.
Attribution buckets moved exactly where the mechanism says they should:
`gate_scaled` **14 → 124** and `delivered_moving` **6 → 19** — the dog spends
its ticks inside the comfort ramp instead of parked on the stop ring.
`gate_zeroed_obstacle`, `gate_zeroed_ttc` and `ttc_gate_zeroed` are 0 in both
arms, so nothing but the person branch changed.

Artifacts (scratch, not in the repo):
`~/.cache/parcel-p1e/move1_control_1p2/` and `…/move1_treatment_0p7/`, each with
`summary.json`, `held_static_trace.json` (400 per-tick rows) and
`simulator_held_static.log`.

**Method deviation, declared.** `scrum/20260821/` is read-only, and the harness
writes its own config from a `BASE_CONFIG` string with no `safety` block. The
harness was therefore **copied** to
`~/.cache/parcel-p1e/harness/run_move1_p1e.py` and given exactly two edits,
which `diff -u` against the original reports as **3 hunks** (the `BASE_CONFIG`
change and its `.format(...)` call site are separated by ~400 lines, so they
are two hunks, not one): `REPO` made absolute (the copy sits outside the repo,
so `parents[4]` no longer resolves), and a `safety` / `owner_follow` block
appended to `BASE_CONFIG` parameterised by `$P1E_PERSON_STOP_M`. Nothing else —
the arm, the drive, the instrumentation, `start_simulator`/`stop_simulator` and
the trace format are byte-identical. The original under
`scrum/20260821/task_20/evidence/` was **not written to**.

**Caveat on what the pair measures.** `obs.person_m` is `None` in **all 400
rows of both traces**: the body the dog stops for is reached through the OWNER
TRACK (`observation.owner`, sim ground truth), not through the person detector
channel. This is the same condition MOVE-1 recorded in §1.3, and it means the
pair proves the *gate arithmetic* on a known-position human, not the
perception that would find one. The harness's `gate_zeroed_person` bucket is 0
in both arms for exactly this reason, and the stops land in
`gate_zeroed_other`.

**Process hygiene.** Socket `/tmp/parcel-move1-<pid>.sock` (the harness's own
pid-unique path), never the owner's `/tmp/parcel_sim.sock` — which did not exist
during this card, and pid 910287 was already gone. No port was opened. Both
simulators were stopped by the harness's `finally`; `ls /tmp/parcel-move1-*.sock`
is empty and `pgrep -af parcel_robot.sim` is empty at the end of this card. No
process this card did not start was signalled. `city_block.xml` sha256
`e89f4f1219f7a92a…` — the value MOVE-1 recorded, unchanged. Every arm ran with
`memory.path: ":memory:"`.

---

## 6. Deviations from OWNS (declared)

### 6.1 Five test files outside `tests/test_p1e_*.py`

The card's deliverable RETIRES the floor these files pinned, so they had to
change or the deliverable could not land. Each is a **value move on the probe,
not a weakening of the property**: every one still asserts that a config cannot
walk the person clearance down without limit and that the limit is a refusal at
construction. The probe moves from the retired 1.0 / 0.7 to 0.6, which is under
the new floor.

| file | hunks | what moved |
|---|---:|---|
| `tests/test_e2_safety_wiring.py` | 2 | floor probe 1.0 → 0.6, plus a NEW assertion that 0.7 is now legal; the runtime-path "undercut" cell 1.0 → 0.6 |
| `tests/test_person_keepout.py` | 1 | D-15 counterfactual: the arithmetic is unchanged, the refusal is re-probed at 0.6 |
| `tests/test_person_cell.py` | 1 | same, plus an explicit assertion that 1.0 now constructs |
| `tests/test_prototype_profile.py` | 3 | P0-A's `MINIMAL` base gains `safety`/`owner_follow` (its own comment already said a base used with the real overlay must carry the overlay's key paths); the "blocker" test flips to pin the fix AND the new floor; the boot test asserts 0.7 / 1.25 |
| `tests/test_dynamic_layer.py` | 1 | §6.2 |

P0-A/B/C/D have closed and their OWNS are open under Edit-only + re-read; each
file was re-read immediately before each edit. This is the same shape as P0-A's
own declared deviation on `tests/test_c1_camera_stream.py`.

### 6.2 The reactive-safety AST ratchet was regenerated

`REACTIVE_SAFETY_PIN["ReactiveSafetyPolicy.__post_init__"]` moved `e01bcca9…` →
`c228b5f8…`. The ratchet reddened **unprompted and named the symbol**; the pin
was regenerated with the command in its own docstring, and a regeneration-log
entry was added in the file's established format saying what moved, why, under
whose authority, and — checked, not assumed — that `apply_reactive_safety`,
`owner_slow_m`, `_owner_comfort_band_m` and `_owner_identity_trusted` are all
unchanged. The test was not deleted or weakened.

Authority for the move: the board's standing rule 1 ("`reactive_safety`
*semantics* untouched; distances are config and may move"), the card, and the
verifier's row A-1. This is **not** an owner-authorized value change of the kind
E5/E6 needed, because **no shipped value moved**: `configs/robot.yaml` still
carries 1.2 / 2.5 / 1.75 and `DEFAULT_SAFETY_ENVELOPE` still reports 1.2. What
moved is which config values are *admissible*.

### 6.3 Row A-1's spelling was not followed literally — and why

A-1's minimal change is `safety.envelope.person_social_zone_m: 0.7` carried
through `runtime.py ~1657` via
`replace(DEFAULT_SAFETY_ENVELOPE, **safety_config.get("envelope", {}))`. This
card took the same mechanism (`envelope` field on the policy; `self.envelope` in
the floor checks; `SafetyEnvelope` doing the refusing) but sourced the zone from
the **existing** `safety.person_stop_m` instead of a new `safety.envelope` block.
Three reasons, in order:

1. **A-1's route needs two files outside this card's OWNS**: `runtime.py`
   (another card's active region this wave) and `config.py`'s
   `OVERLAY_INTRODUCIBLE_KEYS` — P0-A's own handoff warns that the new key path
   does not exist in the SHA-locked `configs/robot.yaml`, so the key walk would
   refuse the overlay. Sourcing from `safety.person_stop_m` needs **neither**.
2. **It would create a new drift surface.** `safety.envelope.person_social_zone_m`
   and `safety.person_stop_m` are two numbers that must agree and that nothing
   forces to agree — which is precisely the defect class (`F-proximity`, "six
   copies, one drift live") that `authority.py` exists to end. One number cannot
   drift from itself.
3. It keeps the card's own words exactly: "`person_social_zone_m` comes from
   config (`safety.person_stop_m`)".

`SafetyEnvelope.from_mapping`'s unknown-key refusal (`authority.py:672`) is
untouched and still available for the `safety.envelope` route if a later card
wants a full envelope in yaml.

### 6.4 `owner_follow.owner_keepout_m` in the overlay

The card scopes the overlay to its `safety` block; A-1 additionally requires
`owner_follow.owner_keepout_m: 1.25`. It is included: without it the prototype
boots with a 0.7 m gate and still holds formation at 1.75 m of centre distance,
because `configs/robot.yaml:61` carries a LITERAL that cannot re-derive. One
key, in the same file, named in the file's own comment.

### 6.5 `grid_planner.py` no longer imports `parcel_robot.geometry`

Replacing `ROBOT_FOOTPRINT_RADIUS_M` with `DEFAULT_SAFETY_ENVELOPE.footprint_radius_m`
(same 0.32 m) is inside the "inflation derivation" OWNS and removes one
`DeprecationWarning` emitter. Side effect for whoever owns `geometry.py`: its
importer census comment still lists `navigation/grid_planner.py`; the remaining
importers are `navigation/pipeline.py` and `navigation/models/__init__.py`. Not
edited — `geometry.py` is not in this card's OWNS.

---

## 7. What this does not prove

* **The follow controller still stands off at 1.85 m.**
  `FollowConfig.desired_distance_m` is an IMPORT-TIME constant
  (`follow.py:_FOLLOW_DESIRED_DISTANCE_M = DEFAULT_SAFETY_ENVELOPE.person_stop(0.0)
  + 0.55 + 0.10`) and is deliberately not exposed in yaml, so it does not
  re-derive from the overlay. It only has to CLEAR the keepout ring
  (1.25 + 0.10 = 1.35), which it does. **So: the GATE now lets the dog come to
  0.7 m, and the FOLLOW FORMATION still chooses 1.85 m.** Pinned as a live
  assertion in `test_the_shipped_prototype_overlay_boots_a_runtime` rather than
  left to be rediscovered, and handed off below. The MOVE-1 arm is unaffected —
  it drives the gate directly, not the follow controller.
* **`navigation/arrival_semantics.py:SOCIAL_STANDOFF_M` is still 1.2 m**
  (`= PERSON_SOCIAL_ZONE_M`, import-time). "Next to a person" as an ARRIVAL
  target therefore still means 1.2 m under the prototype profile. Outside OWNS.
* **No real person was approached.** Everything is the dev simulator with a
  scripted owner body at `(2.0, −0.5)`. The 0.7 m number is a config value that
  the gate now honours; whether 0.7 m reads as companionable to a human being is
  unmeasured and unmeasurable here.
* **The planner coupling is NOT delivered.** `gate_clearance_m` defaults to
  `None` and nothing constructs a `GridPlannerConfig` with it —
  `grid_navigator.py:228` and `search_owner.py:624` are the two production
  sites and neither passes it. Shipped inflation is still 0.42 m against a gate
  that refuses under 1.19 m, so **the planner and the gate do not yet agree on
  one envelope**, which is one third of this card's *Proves* line. Its effect
  is measured (§2.1) and its default is argued (§1.3); the wiring is DOOR-1's
  (`../task_19`). Additionally, `planner_inflation_m` is keyed on
  `obstacle_stop_m`, so the envelope it would make the planner agree with is
  the OBSTACLE one, not the social zone this card moved.
* **The floor is a construction-time floor, not a speed-aware one.** The gate's
  person ring is `person_stop_m + v·τ`, and at the floor that covers the ISO sum
  at `motion.max_vx` by 2.9 mm (§1.2). It is not a margin anyone should spend:
  raising `motion.max_vx` above 1.0 m/s, or lowering `decel_max_mps2`, breaks
  that inequality, and `test_the_floor_plus_the_gates_predictive_term_still_covers_the_iso_sum`
  is the thing that will say so.
* **`obstacle_stop_m` was not touched, and it is the next blocker indoors.** At
  0.65 m the gate refuses to translate down any corridor narrower than ~1.19 m
  (§1.3) — a standard 0.8–0.9 m doorway included. The prototype dog cannot walk
  through a door, and that is an obstacle-clearance decision, not a person one.
* **No gate was re-measured behaviourally.** The evidence that the gate did not
  change is the AST ratchet plus 992 green tests, not a fresh bisection of the
  stop ring at three speeds (that is E6's, `tests/test_e6_owner_band.py`, and it
  is green).
* **Concurrency.** Six other P1/P2 executors were writing this tree throughout.
  Every number here was taken from the tree as it stood at the moment of the
  command shown.

---

## 8. Handoffs

* **DOOR-1 (`../task_19`) — `navigation/follow.py`, one line between the gate
  and the behaviour.** `FollowConfig.desired_distance_m` should derive from the
  INSTANCE's `owner_keepout_m` (`self.owner_keepout_m + OWNER_STAND_OFF_MARGIN_M`,
  applied in `__post_init__` when the caller did not set it) rather than from
  the import-time `DEFAULT_SAFETY_ENVELOPE`. Blast radius, named: FOLLOW_BENCH_V1
  and its nightly jerk ratchet, plus E5/E6's recorded stand-off evidence. Not
  taken here because `follow.py` is outside this card's OWNS and the bench is a
  paired-run decision.
* **DOOR-1 (`../task_19`) — turning the planner coupling on.** `GridPlannerConfig(gate_clearance_m=policy.planner_inflation_m)`, reached
  from `grid_navigator.py`'s `map_*` kwargs. Read §1.3 first: at the shipped
  obstacle ring it closes every corridor under 1.19 m. The honest sequence is
  (1) decide `safety.obstacle_stop_m` for indoors, (2) then couple, (3) then
  re-freeze the nav baselines.
* **The indoor doorway blocker → DOOR-1 (`../task_19`), which now owns it.**
  `safety.obstacle_stop_m: 0.65` makes a 0.9 m doorway impassable to the
  reactive gate regardless of the planner. It is an obstacle clearance, so this
  card did not touch it; DOOR-1 takes the obstacle envelope and the planner
  coupling together, which is the only order in which the coupling is safe.
* **`navigation/arrival_semantics.py`.** `SOCIAL_STANDOFF_M` should read the
  commissioned zone rather than `PERSON_SOCIAL_ZONE_M`, or "go next to the
  person" will keep targeting 1.2 m under a 0.7 m profile.
* **`geometry.py`'s importer census** (§6.5) is now stale by one entry.
* **Verifier — where to look first.** (1) `tests/test_dynamic_layer.py`'s
  regeneration log entry and the four unchanged digests: that is the whole
  "semantics diff is empty" claim in one place, and it is falsifiable in one
  command. (2) The `git diff` of `navigation/reactive_safety.py`, which is
  **6 hunks and not comment-only** (an earlier draft of this doc said it was;
  that was wrong and the verifier caught it): the `authority` import list; the
  `envelope: SafetyEnvelope = DEFAULT_SAFETY_ENVELOPE` dataclass field; the
  class docstring; the obstacle floor check switching to `self.envelope`; the
  person floor check becoming `with_person_social_zone` + its re-raise; and
  **two new read-only properties after `owner_slow_m`** —
  `commissioned_envelope` and `planner_inflation_m` (`:226-256`), both
  side-effect-free, neither called from `apply_reactive_safety`. A third,
  `person_stop_floor_m`, was written and had no caller anywhere; it was removed
  under verification (§9). The claim that survives is narrower and checkable:
  **no code the gate executes changed**, which the AST ratchet states exactly. (3) The MOVE-1 pair, which is
  reproducible with two commands from `~/.cache/parcel-p1e/harness/`.
* **Not run here, by the board's rule:** the full suite and
  `scripts/ci_gate.py`. `pyproject.toml` and `scripts/ci_gate.py` were never
  opened; the P0-E hand-off gate (`task_5/P0E_STATUS.md`) existed before any
  `tests/**` file was created or modified by this card.

---

## 9. Post-verification corrections (2026-08-22)

Verdict on the first submission: **DISCREPANCIES_FOUND**. Every number
reproduced independently (the verifier's own MOVE-1 pair: 0.312942 / 0.843333 m
against my 0.312756 / 0.843330 — 0.19 mm and 0.003 mm apart; floor arithmetic,
AST digests, the five test edits judged tighter-not-weaker, hygiene clean). Two
**claims** were inaccurate and one detail was wrong. All three are corrected
above and recorded here rather than silently edited.

### 9.1 "everything below `__post_init__` is comment-only" — FALSE, withdrawn

It was not comment-only. `git diff` on `navigation/reactive_safety.py` is **6
hunks**, and the last one added three `@property` methods (~42 lines) plus an
`envelope` dataclass field. The claim was written from memory of the *intent*
("no gate logic") and not from the diff, which is exactly the failure mode this
register exists to catch. §8 hint 2 now describes the diff hunk by hunk, and
the surviving claim is the narrow, checkable one: **no code the gate executes
changed** — which is what the AST ratchet actually states.

**Dead code removed.** `ReactiveSafetyPolicy.person_stop_floor_m` had **no
reference anywhere** in `src/`, `tests/`, `evals/`, `scripts/` or `tools/` — it
was written for a status-doc convenience that the status doc never used. Removed,
along with the now-unused `PERSON_SOCIAL_ZONE_FLOOR_M` import in that module.
`grep -rn person_stop_floor_m` over the whole tree is now empty. The two
properties the tests exercise stay: `commissioned_envelope` (the config→authority
conversion, asserted by `test_the_gate_takes_its_person_clearance_from_config`)
and `planner_inflation_m` (asserted by
`test_the_planner_inflation_derives_from_the_same_envelope_quantity`).

**The second `__post_init__` check stays, and now says why.** It reads as
vestigial and is not: `commissioned.person_stop(0.0)` is
`max(person_stop_m, stop_distance(0.0))`, and `stop_distance(0.0)` is the body
itself (`footprint_radius_m + Zs + Zr`). At Go2 scale that is 0.32 m, the 0.68 m
proxemics floor dominates, and the branch is unreachable — **but the `envelope`
field is injectable precisely so a different body can arrive**, and a body whose
hull is wider than the commissioned person clearance would otherwise be allowed
to commission a stop ring inside itself. Two floors, binding for two different
robots. Reachability is now **demonstrated rather than asserted**, by a new test:

```
tests/test_p1e_social_zone_is_config.py::test_the_physics_floor_still_binds_for_a_wider_body
    SafetyEnvelope(footprint_radius_m=1.5) -> stop_distance(0.0) == person_stop(0.0) == 1.5
    ReactiveSafetyPolicy(person_stop_m=0.7, envelope=wide)
      -> ValueError: reactive person_stop_m must not undercut SafetyEnvelope.person_stop(0.0)
    ReactiveSafetyPolicy(person_stop_m=0.6, envelope=wide)
      -> ValueError: … PERSON_SOCIAL_ZONE_FLOOR_M (0.68 m) …   (the other floor, same body)
```

A code comment at the check names the arithmetic and points at that test, so the
next reader does not have to re-derive it to know the branch is live.

### 9.2 "the planner and the gate agree on one envelope" — NOT DELIVERED

Correct, and now stated as such in the headline, §1.3 ("NOT DELIVERED"), §7 and
§8. The two facts that decide it, both verified in-tree:

* `GridPlannerConfig.gate_clearance_m` defaults to `None` and **no production
  site sets it** — `grid_navigator.py:228` and `search_owner.py:624` are the two
  constructors and neither passes it. Shipped inflation stays 0.42 m while the
  gate refuses corridors under 1.19 m.
* `planner_inflation_m` is keyed on `obstacle_stop_m`, not on the social zone
  this card moved, so the envelope it would reconcile is the OBSTACLE one.

Per the coordinator, the wiring was **not** attempted here: it belongs to
**DOOR-1** (`../task_19`), which now owns the obstacle envelope and the planner
coupling together — the only order in which the coupling is safe, since coupling
to a 0.65 m ring closes every doorway. What P1-E leaves DOOR-1 is the derivation
pinned to the gate's own cone, the field, and the measured cost of switching it
on (§2.1).

### 9.3 The harness diff, and what the MOVE-1 pair measures

* "a 4-line `diff -u`" → **3 hunks** (the `BASE_CONFIG` change and its
  `.format(...)` call site are ~400 lines apart). Corrected in §5.
* **Caveat added to §5:** `obs.person_m` is `None` in **all 400 rows of both
  traces**. The dog stops for the OWNER TRACK (sim ground truth), not for a
  detected person, which is why `gate_zeroed_person` is 0 and the stops land in
  `gate_zeroed_other` — the same condition MOVE-1 recorded in its §1.3. The pair
  proves the gate arithmetic against a known-position human; it proves nothing
  about the perception that would have to find one.

### 9.4 Verification after the corrections

```
$ TMPDIR=~/.cache/parcel-p1e .parcel/bin/python -m pytest -q -p no:randomly <the §3 set>
993 passed, 5 skipped, 1 xfailed in 47.01s        (992 before; +1 = the new reachability test)

$ .parcel/bin/ruff check src/parcel_robot/{authority.py,navigation/reactive_safety.py,navigation/grid_planner.py} \
      tests/test_p1e_social_zone_is_config.py
All checks passed!
```

**The AST ratchet stayed green — no regeneration was needed.**
`ReactiveSafetyPolicy.__post_init__` is still `c228b5f85688e727…`, the value §6.2
recorded, because the only change inside it was a comment and the ratchet
normalises through `ast`. `apply_reactive_safety` `f52db9c5…`, `owner_slow_m`
`119af4ad…`, `_owner_comfort_band_m` `7d5050eb…`, `_owner_identity_trusted`
`5262d3ed…` — all five pinned symbols verified `OK` after the edits.
`navigation/reactive_safety.py` numstat is now **+88 / −2** (was +86 / −2:
−11 for the deleted property and its import, +13 for the comment explaining the
physics floor); the §1 table is updated.

Nothing else in the card moved: no source file outside the three OWNS modules
was touched in this pass, the overlay is unchanged (`2081c5c7…`), and no
process was started or signalled.
