# E5 STATUS — THE PERSON-CLEARANCE RETUNE (owner-authorized)

**Lane:** E5. **Authorization:** owner, 2026-08-10 — *"1. person clearance.
Implement your recommendation."* **Uncommitted, as instructed.**
**Input:** `E2_SAFETY_WIRING_STATUS.md` §3 (built, measured, reverted under
rule 2) and `AUDIT_FABLE_INDEPENDENT.md` "OPEN — owner decision required".

**Verdict: the retune is LANDED and the gate is GREEN — and the headline
finding is that E2's attribution was wrong.** The pedestrian-safety gain and
the follow-bench loss are *the same knob*, and it is not the one either of us
expected.

| | E2's claim | E5's measurement |
|---|---|---|
| what buys the pedestrian clearance | `person_stop_m` 1.0 -> 1.2 | **`person_slow_m` 2.0 -> 2.5** |
| what costs `follow_success` | `desired_distance_m` left inside the new keepout | **`person_slow_m` 2.0 -> 2.5** |
| cost of `person_stop_m` 1.0 -> 1.2 | 9/9 -> 6/9 | **zero** (9/9 preserved) |
| cost of the raised follow distance | would recover 9/9 | **zero, and it does not recover 9/9** |

`follow_success` is **6/9**, not 9/9. It is reported, attributed, and re-frozen
as a real capability regression — not massaged, and not silently accepted.
`hard_collision_total` **0**, `false_arrival` **0**, `navigate_success` **2/2**.

---

## 1 — What landed

| # | Change | Files |
|---|---|---|
| 1 | `safety.person_stop_m` 1.0 -> **1.2**, `safety.person_slow_m` 2.0 -> **2.5** | all four `robot*.yaml` copies |
| 2 | `owner_follow.owner_keepout_m` 1.55 -> **1.75** (derived) | all four copies |
| 3 | `FollowConfig.desired_distance_m` 1.6 -> **1.85** (derived), `person_stop_m`/`person_slow_m`/`owner_keepout_m`/`owner_collision_envelope_m` derived by reference | `navigation/follow.py` |
| 4 | New `FollowConfig` invariant: the follow stand-off must clear its own keepout by the stand-off margin | `navigation/follow.py` |
| 5 | **Symmetric person floor** in `ReactiveSafetyPolicy.__post_init__` | `navigation/reactive_safety.py` |
| 6 | Last two hardcoded `1.0` person literals removed | `brain/observations.py`, `evals/companion_nav/runner.py` |

The four yaml copies were kept in sync with `tools/sync_runtime_assets.py`
(`configs/robot.yaml` -> `runtime_assets/configs/robot.yaml` + the in-package
`config/robot.yaml`); `configs/robot.acoustic.yaml` is not covered by that tool
and was edited by hand to the same values.

---

## 2 — The follow-distance derivation (terms, margin, why)

Not a chosen number. Two derivations, each reading an existing authority.

### 2.1 `owner_keepout_m = person_stop_m + owner_collision_envelope_m`

`apply_reactive_safety` treats the owner as a person by subtracting
`owner_collision_envelope_m` from the owner **center** distance and comparing
the remainder against `person_stop_m` (`reactive_safety.py:127-145`). So the
ring at which the final gate refuses to translate toward the owner *is*
`person_stop_m + owner_collision_envelope_m`. That is what `owner_keepout_m`
names; `runtime.py:517` and `evals/companion_nav/runner.py:878` already enforce
it as a minimum. At the retuned values: **1.2 + 0.55 = 1.75 m** (exactly, in
IEEE-754 double — checked, no float noise).

### 2.2 `desired_distance_m = owner_keepout_m + arrival_radius_m + stand_off_margin_m`

The margin is the one `StandOffEnvelope` already puts between a *minimum
clearance* and the *stand-off that wraps it*:

```
stand_off(r)        = r + r_foot + target_surface_clearance + arrival_radius_m + stand_off_margin_m
minimum_vicinity(r) = r + r_foot + target_surface_clearance
=> stand_off(r) - minimum_vicinity(r) == arrival_radius_m + stand_off_margin_m
```

Both terms, verbatim from `authority.py` `FIELD_META`:

* `arrival_radius_m` = 0.06 — *"Controller position tolerance at the terminal
  pose."* The stand-off must clear the ring by at least what the controller can
  undershoot by.
* `stand_off_margin_m` = 0.04 — the authority's standing trailing margin on
  every stand-off.

Applied to the owner keepout ring instead of an object's minimum vicinity:

```
OWNER_STAND_OFF_MARGIN_M = 0.06 + 0.04            = 0.10
desired_distance_m       = 1.75 + 0.10            = 1.85 m
```

**Why this margin and not another.** The shipped value it replaces was
`1.6 = 1.55 + 0.05` — the same *shape* (keepout + a margin) with a bare `0.05`
literal, restated twice more in `follow.py` as `owner_keepout_m + 0.05`. The
retune keeps the shape, replaces the literal with the authority's own term, and
lands at double the old margin (strictly more conservative). The constant is
exported as `OWNER_STAND_OFF_MARGIN_M` and now feeds all three sites, so the
nominal stand-off and the two behind-formation floors cannot fork again.

`desired_distance_m` is deliberately **not** exposed in `robot.yaml`: it is
defined against `owner_keepout_m`, so exposing it would re-open exactly the
defect being fixed. A new `FollowConfig.__post_init__` invariant refuses any
config where the stand-off does not clear the keepout by that margin.

### 2.3 What this derivation is worth, honestly

It is structurally correct and it closes the "target inside its own keepout"
defect permanently. **It does not buy back a single follow-bench row** — see §4.
E2's diagnosis of the 6/9 was wrong, and this measurement refutes it.

---

## 3 — Safety, re-measured by E5 (FOLLOW_BENCH_V1, all 11 scenarios)

| metric | before (old code + old config) | after (shipped) | direction |
|---|---|---|---|
| `min_pedestrian_surface_m` | 0.3566 | **0.5300** | +0.173 m safer |
| `personal_space_time_total_s` | 3.8 | **2.3** | -1.5 s safer |
| `hard_collision_total` | 0 | **0** | unchanged |
| `pedestrian_contact_total` | 0 | **0** | unchanged |
| `intimate_space_time_total_s` | 0.0 | **0.0** | unchanged |
| `reactive_gate_stop_total` | 4 | **2** | fewer emergency stops needed |
| `navigate_success` | 2/2 | **2/2** | unchanged |
| `false_arrival` (nav_instruct frozen baseline) | 0 | **0** | unchanged |

Per-episode, where the gain actually comes from:

| episode | min pedestrian surface before -> after | personal-space dwell |
|---|---|---|
| `pedestrian_cut_in_predictive` | 0.3566 -> **0.8183** | 1.5 s -> **0.0 s** |
| `pedestrian_cut_in` | 0.9764 -> **1.4074** | 0.0 -> 0.0 |
| `pedestrian_group` | 1.2468 -> **1.4336** | 0.0 -> 0.0 |
| `navigate_crossing_ped` | 0.5300 -> 0.5300 | 2.3 s -> 2.3 s |

`navigate_crossing_ped` is unmoved because it runs `DirectiveNavigator`, whose
`CollisionPolicy` already read `person_stop_m` **1.2** from
`configs/navigation/default.yaml` (`stop_distance_m + 0.4`). The product's
*planner* has agreed with the authority all along; only the *reactive gate* was
undercutting it. That gap is what closed.

---

## 4 — `follow_success` 6/9: the honest number, with attribution

### 4.1 Factorial attribution (all cells measured on this tree, all 11 scenarios)

Each cell varies one quantity from the pre-retune baseline. Cells with
`person_stop_m < 1.2` or a stand-off inside the keepout were run with the two
new floors monkeypatched off in a scratchpad harness (diagnostic only, nothing
shipped).

| cell | `person_stop_m` | `person_slow_m` | `owner_keepout_m` | `desired_distance_m` | `follow_success` | `mean_band_fraction` | `min_pedestrian_surface_m` | dwell |
|---|---|---|---|---|---|---|---|---|
| **A** baseline (all old) | 1.0 | 2.0 | 1.55 | 1.60 | **9/9** | 0.74315 | 0.3566 | 3.8 |
| **F** stand-off only | 1.0 | 2.0 | 1.55 | 1.85 | **9/9** | 0.74334 | 0.3566 | 3.8 |
| **G** stop+keepout only | 1.2 | 2.0 | 1.75 | 1.60 | **9/9** | 0.73580 | 0.3824 | 3.8 |
| **D** stop+keepout+stand-off | 1.2 | 2.0 | 1.75 | 1.85 | **9/9** | 0.73533 | 0.3824 | 3.8 |
| **E** slow band only | 1.0 | **2.5** | 1.55 | 1.60 | **6/9** | 0.64901 | **0.5300** | **2.3** |
| **C** E2's measured cell | 1.2 | **2.5** | 1.75 | 1.60 | **6/9** | 0.63986 | **0.5300** | **2.3** |
| **B** SHIPPED | 1.2 | **2.5** | 1.75 | **1.85** | **6/9** | 0.63986 | **0.5300** | **2.3** |
| H probe | 1.2 | 2.5 | 1.75 | 2.20 | 6/9 | 0.63907 | 0.5300 | 2.3 |
| I probe | 1.2 | 2.5 | 1.75 | 2.60 | **5/9** | 0.62433 | 0.5300 | 2.3 |

Read the column, not the row:

* **`person_slow_m` 2.0 -> 2.5 is the whole story, in both directions.** It is
  the only quantity whose presence flips 9/9 -> 6/9 (cell E, with everything
  else at the old values), and it is the only quantity that moves
  `min_pedestrian_surface_m` 0.3566 -> 0.5300 and the dwell 3.8 -> 2.3.
* **`person_stop_m` 1.0 -> 1.2 costs nothing** (cells G, D still 9/9) and buys
  little on its own (0.3566 -> 0.3824). The hard safety line moved for free.
* **`desired_distance_m` 1.6 -> 1.85 costs nothing and buys nothing here**
  (A vs F, G vs D — 9/9 either way, band moves in the 3rd decimal). It is a
  structural correction, not a bench lever.
* **Raising the follow distance further makes it worse, not better**: 2.20 m
  holds 6/9, 2.60 m drops to 5/9. E2's "recovering 9/9 would need
  `desired_distance_m` raised as well" is **refuted by measurement.**

Hard collisions are **0 in every cell above.** The three lost episodes
(`pedestrian_group` 0.780->0.584 vs 0.75, `pedestrian_cut_in` 0.685->0.525 vs
0.60, `owner_turn_90` 0.821->0.500 vs 0.80) all fail by leaving the
`[1.2, 3.0] m` band **from above** — the robot falls behind. Traced on
`owner_turn_90`: 170 of 340 steps above 3.0 m, max owner distance 3.615 m,
minimum 2.00 m, **zero steps below the band minimum**. Nothing gets closer to
anything; the dog just loses the owner's pace.

### 4.2 Why — the mechanism, proven not hypothesised

`apply_reactive_safety` applies **one** comfort band to strangers *and* to the
owner: the owner is pushed into the same `people` list, and the loop scales
translation by `(d - person_stop_m) / (person_slow_m - person_stop_m)` for both
(`reactive_safety.py:127-153`).

Widening that band to 2.5 m means the owner is inside it whenever the owner
center distance is under `2.5 + 0.55 = 3.05 m` — i.e. **always, by
construction**, since the follow stand-off is 1.85 m. Before the retune the
robot ran unthrottled from 2.55 m center outward; now it is throttled from
3.05 m, which is exactly the range it needs full speed in to keep up through a
turn or after yielding to a pedestrian.

**The clinching evidence is `owner_turn_90`: that scenario contains no
pedestrians at all** (`pedestrians=[]`, `min_pedestrian_surface_m is None` in
every run), and it still drops 0.821 -> 0.500 when `person_slow_m` alone goes
2.0 -> 2.5. With no pedestrian in the episode, the only thing the widened
comfort band can be acting on is the owner.

### 4.3 What was NOT done about it

Separating the owner's comfort band from the stranger's requires editing
`apply_reactive_safety` itself. That function is pinned by
`REACTIVE_SAFETY_PIN`, and this card explicitly expects it to be
**unchanged** ("confirm `apply_reactive_safety` is unchanged"). Redesigning the
final safety gate is a bigger change than this authorization covers, so it was
not attempted — rule 2. It is the recommended follow-up card, and §7 states it.

Tuning `person_slow_m` to the largest value that still holds 9/9 was also not
done: it would be fitting a safety constant to a bench, which is exactly the
massaging the card forbids. `2.5` is `SafetyEnvelope.person_comfort_band_m`,
and that is the only reason it is `2.5`.

### 4.4 The lever, stated plainly for the owner

`safety.person_slow_m` is a one-line, one-value decision with a measured price
on both sides:

| `person_slow_m` | `follow_success` | `min_pedestrian_surface_m` | dwell |
|---|---|---|---|
| **2.5** (authority; SHIPPED) | 6/9 | 0.5300 | 2.3 s |
| 2.0 (pre-retune) | 9/9 | 0.3824 | 3.8 s |

Everything else in this lane (`person_stop_m` 1.2, `owner_keepout_m` 1.75,
`desired_distance_m` 1.85, the symmetric floor) is free of that trade and stays
either way.

---

## 5 — Embodied plan v1: behaviour UNMOVED, sha moves MECHANICALLY

This distinction is the whole point of the re-freeze, so it is stated first:
**the eval did not change. Its input hash did.**

Measured **before** the committed manifest was touched, by running the full
suite against a scratchpad copy of the manifest carrying only the refreshed
`robot_config` lock:

```
simulator_step_count 997   collision 0   timeout 0   minimum_clearance_m 0.883147
per-case: 200 / 260 / 64 / 389 / 84        (pins: 997, 0.883147, median 200, mean 199.4)
supported_case_success_rate 1.0            passed 4 / unsupported 1 / failed 0
```

**Bit-identical to the frozen row on every pinned quantity.** The only reason
the manifest had to move at all is that it SHA-locks `configs/robot.yaml` as an
input, and that file was retuned. `git diff` on the manifest is **one line**:
the `locked_inputs.robot_config.sha256` string. No other locked input, no
layout byte, no `frozen_at_utc`.

---

## 6 — Every moved pin, with its 2x2 attribution

The 2x2 convention: *old-code* = commit `6bd945d` + lanes E1-E4 as the
coordinator verified them; *new-code* = that tree plus this lane.

### Pin 1 — `evals/companion/embodied_plan_v1/manifest.json` (a `DIGEST_SENTINELS` entry)

* **old value** `33c662c8d3611f39bb1fc56dabbebb2c4c7c913a8499449107cd5add95c6e54f`
* **new value** `22736f6e0e4b106c0d130b9f7f425feca465a73b20da1431dfd5e2e3b1ce9389`
* driven by `locked_inputs.robot_config.sha256`
  `f64688874525f20d…` -> `aff691130b2513cf…` (= sha256 of the retuned
  `configs/robot.yaml`; the old value is sha256 of `HEAD:configs/robot.yaml`,
  verified directly)

| | old pin (`33c662c8…`) | new pin (`22736f6e…`) |
|---|---|---|
| **old code** | **PASS** — `tests/test_embodied_plan_eval.py` 10 passed on this tree before any E5 edit; sentinel green | **FAIL** — `HEAD:configs/robot.yaml` hashes to `f6468887…`, so the new manifest could not exist |
| **new code** | **FAIL** — `EmbodiedPlanError: locked input robot_config failed SHA-256 verification` (3 failed + 7 errors in the full suite, observed before the re-freeze) + sentinel mismatch | **PASS** — `ci_gate` `frozen-digest-sentinels`: 3 manifests byte-identical to pin; suite 3340 passed |

**Attribution: mechanical, not behavioural.** The new-code × scratch-manifest
cell (§5) reproduces 997 / 0 / 0 / 0.883147 / 200-260-64-389-84 exactly, which
is the direct proof that the sha moved because an input file's bytes moved and
for no other reason.

### Pin 2 — FOLLOW_BENCH_V1 latest-shipped row (`results/ledger.jsonl` + `FOLLOW_BENCH_POST_SPEED`)

* **old value** `follow_success 9/9`, `mean_band_fraction 0.7433396178984414`,
  `mean_rms_commanded_jerk_mps3 0.6025`, report
  `follow-bench-v1-20260809094511Z-601d8c6e.json`
* **new value** `follow_success 6/9`, `mean_band_fraction 0.6398553712083124`,
  `mean_rms_commanded_jerk_mps3 0.8918`, report
  `follow-bench-v1-20260811020631Z-2f7bbb07.json`
* `hard_collision_total 0` and `navigate_success 2/2` are **unchanged** in both.

| | old pin (9/9) | new pin (6/9) |
|---|---|---|
| **old code** | **MATCH on the pinned rows** — re-measured today: `9/9`, `2/2`, collisions `0`. (Two caveats below.) | **mismatch** — 9/9 ≠ 6/9 |
| **new code** | **mismatch** — 6/9 ≠ 9/9; this is exactly the red `tests/test_duplex_v1.py::test_nav_regression_pins_post_speed_raise_rows` produces | **MATCH** — `ci_gate` green, `hard-safety` reports "follow-bench: 6 row(s), `hard_collision_total` all 0" |

Two caveats on the old-code × old-pin cell, both **pre-existing and not this
lane's**, both already flagged by E2:

* `mean_band_fraction` re-measures at `0.74315` against a pinned `0.74334`
  (5th decimal).
* `mean_rms_commanded_jerk_mps3` re-measures at `0.9541` against a pinned
  `0.6025` — a ~58 % drift that is present on this working tree **before** any
  E5 change. Not gated (`ci_gate` pins only `hard_collision_total` for
  follow-bench) and not caused here, but it is real and it is still unowned.

**Attribution: `safety.person_slow_m` 2.0 -> 2.5, alone** — see the factorial in
§4.1. Not the stop distance, not the keepout, not the stand-off, and not
environment drift (cell A reproduces 9/9 on this same tree today).

### Pin 3 — `REACTIVE_SAFETY_PIN["ReactiveSafetyPolicy.__post_init__"]` (`tests/test_dynamic_layer.py`)

* **old value** `2be49ad05223628fbe0b06a26ff57a4d1b6c5ca02f7a25eca4d0bae0f6dfc683`
* **new value** `4c07dc077c2eb6999b46ce8a89998ce1cd73e11ed0d566ab0130f5d2285afba2`

| | old pin (`2be49ad0…`) | new pin (`4c07dc07…`) |
|---|---|---|
| **old code** | **MATCH** — `HEAD:reactive_safety.py` digests to `2be49ad0…`, measured with E3's own `_symbol_digest` | **mismatch** — this is precisely the cross-lane red E2 reported and asked E3 to revert |
| **new code** | **mismatch** — the observed initial red on this lane | **MATCH** — regenerated with the command in the pin's own docstring; `ci_gate` green |

**Attribution: the symmetric person floor, and nothing else.** Independent
corroboration: the regenerated digest is **bit-identical to the `4c07dc07…`
lane E3 captured during E2's measurement window**, i.e. the guard that finally
landed is AST-identical to the one E2 built and then reverted under rule 2. The
pin now names a state that exists in the working tree instead of one that
existed in no commit.

`apply_reactive_safety` is `1f46251c2b9ea072081bfc8d094b19fdc01e5682eac598540a9459815505a505`
in **all four cells** — HEAD, live, old pin, new pin. **The gate function did
not move; only the constructor's validation did.** Checked, not assumed.

### Not re-pinned (deliberately)

* `evals/nav_instruct/episodes/v3/manifest.json` and
  `evals/companion/personal_convo_v1/manifest.json` — untouched, still
  byte-identical to their pins.
* `tests/test_embodied_plan_eval.py`'s behavioural pins (997 / 0 / 0 /
  0.883147 / 200 / 199.4 / 64 / 389) — **not touched, because nothing moved.**
  Re-pinning an unmoved row would have destroyed the evidence that the
  manifest move was mechanical.
* `PINNED_FROZEN_FALSE_ARRIVAL = 0` and the nav_instruct frozen-baseline row —
  untouched; `ci_gate` reports `collisions=0 false_arrival=0`.
* No locked file's *content* was altered to make a pin fit. The one manifest
  edit refreshes a hash **to match** a file that legitimately changed; it does
  not edit the locked file to match a stale hash.

---

## 7 — Flagged, deliberately NOT changed

1. **The owner shares the stranger comfort band** (`apply_reactive_safety`).
   This is the root cause of the 6/9 (§4.2) and the highest-value follow-up in
   this area. The fix is to give the owner branch a band derived from the follow
   stand-off rather than from the human social zone. It changes the pinned gate
   function, so it needs its own card and its own authorization.
2. **`configs/navigation/default.yaml` `person_slow_m: 2.0`** now disagrees with
   the reactive band (2.5), and its own comment ("Match the runtime reactive
   person band (2.0 m)") is stale. **Not changed**: it is a planner cost/comfort
   band, its `person_stop_m` already derives to 1.2 and therefore agrees, and
   moving it would move the embodied and nav_instruct frozen rows — outside this
   authorization. No safety weakening: the reactive gate's own 2.5 m band still
   applies to the outgoing command.
3. **`owner_follow.behind_distance_m` stays 1.9 m.** It still clears the new
   keepout (1.75) and the behind-formation floor (1.85), but its usable lead
   budget shrank 0.35 -> 0.15 m. Raising it is a product decision about how far
   behind the owner the dog walks, it would drag `staging_radius_m` with it, and
   FOLLOW_BENCH_V1 exercises `direct` mode only — so it would be an unmeasured
   change. Flagged, not made.
4. **`src/parcel_robot/runtime_assets/configs/navigation/*` is stale at HEAD.**
   Running `tools/sync_runtime_assets.py` pulled in 53 lines of unrelated
   `default.yaml` / `grid.yaml` drift from earlier commits. Those two files were
   reverted to HEAD so this lane's diff stays surgical; the packaged-asset
   staleness is pre-existing and belongs to whoever owns `configs/navigation`.

---

## 8 — Gate

| requirement | result |
|---|---|
| `ReactiveSafetyPolicy(person_stop_m=1.0)` RAISES | **yes** — `reactive person_stop_m must not undercut SafetyEnvelope.person_stop(0.0)` |
| `person_stop_m=1.2` constructs | **yes** |
| all four yaml copies read 1.2 / 2.5 | **yes** — asserted against the authority, not against fresh literals, in `test_every_robot_config_copy_now_agrees_with_the_person_authority` (4 params) |
| a test asserts the RUNTIME-constructed policy carries 1.2 | **yes** — `test_the_runtime_constructed_policy_reflects_the_yaml_not_a_hidden_literal`: no-`safety`-section -> 1.2/2.5, the shipped `configs/robot.yaml` values read off disk -> 1.2/2.5, and an injected 1.0 is now **refused** |
| FOLLOW_BENCH_V1 `follow_success` 9/9 | **NO — 6/9**, reported with the factorial attribution above, re-frozen as a regression, with the one-line lever named. Not massaged, not silent. |
| pedestrian safety improved, re-measured | **yes** — `min_pedestrian_surface_m` 0.3566 -> **0.5300**, dwell 3.8 -> **2.3 s** |
| collisions 0 and false_arrival 0 everywhere | **yes** — follow-bench `hard_collision_total` 0 on all 6 rows, `pedestrian_contact_total` 0, nav frozen baseline `collisions=0 false_arrival=0`, mutation panel `collisions=0 no_false_arrival=True` |
| embodied behaviour unmoved, sha move explicit | **yes** — §5 |
| `ci_gate.py --tier commit` | **PASS** |
| ruff | **clean** — `All checks passed!` on all 11 touched files; gate `7 violation(s), baseline 7, new 0` |

```
CI GATE — tier=commit
[  PASS] HARD  ruff                       7 violation(s), baseline 7, new 0
[  PASS] HARD  hard-safety                nav frozen baseline …20260809T161252Z: collisions=0 false_arrival=0 |
                                          mutation panel clean: collisions=0 no_false_arrival=True |
                                          follow-bench: 6 row(s), hard_collision_total all 0 = True |
                                          walk_with_me: 1/2 row(s) with hard_collision_total, all 0 = True
[  PASS] HARD  frozen-digest-sentinels    3 immutable manifest(s) byte-identical to pin
[  PASS] HARD  latency-tail-ledger        6 metric series within 1.2x tail ceiling (rows=5)
[  PASS] HARD  model-off-non-inferiority  23 passed
[  PASS] HARD  frozen-digest-integrity    6 passed
[  PASS] HARD  mutation-panel-freshness   1 passed
[  PASS] HARD  latency-tail               6 passed
[  PASS] HARD  default-suite              3340 passed, 9 skipped, 34 deselected
RESULT: PASS — every hard gate green.
```

`3340 passed` is exactly the coordinator-verified baseline: this lane's test
edits are rewrites of existing assertions, not additions.

---

## 9 — Files touched

| Path | Change |
|---|---|
| `configs/robot.yaml` | `person_stop_m` 1.2, `person_slow_m` 2.5, `owner_keepout_m` 1.75, derivation + authorization comments |
| `configs/robot.acoustic.yaml` | same three values |
| `src/parcel_robot/config/robot.yaml` | via `tools/sync_runtime_assets.py` |
| `src/parcel_robot/runtime_assets/configs/robot.yaml` | via `tools/sync_runtime_assets.py` |
| `src/parcel_robot/navigation/reactive_safety.py` | symmetric `person_stop_m` floor; the owner-gated comment replaced by the authorization record |
| `src/parcel_robot/navigation/follow.py` | `OWNER_STAND_OFF_MARGIN_M` + `_OWNER_KEEPOUT_M` + `_FOLLOW_DESIRED_DISTANCE_M` derivations; `FollowConfig` person/keepout/stand-off fields derived; new stand-off-clears-keepout invariant; both `+ 0.05` literals replaced by the derived margin |
| `src/parcel_robot/brain/observations.py` | `person_stop_m` snapshot default derived (was `1.0`) |
| `evals/companion_nav/runner.py` | envelope-derived person fallbacks (were `1.0` / `2.0`) |
| `evals/companion/embodied_plan_v1/manifest.json` | **one line**: `locked_inputs.robot_config.sha256` |
| `scripts/ci_gate.py` | `DIGEST_SENTINELS` embodied entry + a re-pin log |
| `evals/companion/duplex_v1/run_duplex_v1.py` | `FOLLOW_BENCH_POST_SPEED` 9/9 -> 6/9 + the attribution block |
| `evals/companion_nav/results/ledger.jsonl` (+ new report json) | one appended row; the append-only prefix is untouched |
| `tests/test_e2_safety_wiring.py` | three pinned-disagreement tests flipped to pinned-agreement; the no-1.0-literal scan widened to five files |
| `tests/test_dynamic_layer.py` | `REACTIVE_SAFETY_PIN` `__post_init__` regenerated + inline log |
| `tests/test_follow_prediction.py` | two lead/rear-station expectations re-derived from the config |
| `tests/test_runtime.py` | direct stand-off expectation read from the config (1.6 -> 1.85) |
| `tests/test_resume_transaction.py` | behind-formation distance 1.8 -> 2.0 (1.8 now under the 1.85 floor) |

Nothing in MUST-NOT-TOUCH was edited: `instructnav/**`, `camera_channel/**`,
`detection_adapter/**`, `evals/nav_instruct/episodes/**`, the `personal_convo`
locked content, and the `value_map` / `detection_lock_on` feature code are all
untouched by this lane. **Nothing committed.**

---

## does_not_prove

* Does **not** prove the 6/9 is acceptable. It is a real capability regression
  on the product's headline behaviour, shipped because the safety half of the
  same knob is worth more and because the authorization was explicit. The owner
  should read §4.4 and decide.
* Does **not** prove the pedestrian-clearance gain generalises past
  FOLLOW_BENCH_V1's scripted, non-reactive pedestrians (the bench's own
  `does_not_prove` list applies in full).
* Does **not** prove the separated owner comfort band (§7.1) would restore 9/9.
  It was not built — that is a change to the pinned gate function and was out of
  scope. Only the *cause* is proven, by `owner_turn_90`.
* Does **not** prove hardware behaviour: every number here is the headless
  kinematic city block with an oracle owner track.
* Does **not** re-measure nav_instruct or the mutation panel from scratch; both
  are read from their existing frozen artifacts, which this lane did not touch.
