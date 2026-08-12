# W1-D15 STATUS — DOC-1, D15-A, D15-B, D15-C (Wave 1, executor: Opus)

**Record:** `scrum/20260811/task_1/FOLLOWUP_DESIGNS.md` — §0 (synthesis), §1
(D-15 diagnosis + design), §5 (DOC-1), §6 card blocks, §7 (orchestration).
**Base:** `dd2e857`, working tree carrying the sibling W1-J lane's files
(untouched by this lane; ownership diff in §5).

**Baseline `scripts/ci_gate.py --tier commit` (verified fresh before starting):**
PASS — 3390 passed, ruff 7 violations / baseline 7 / new 0, 4 digest sentinels
byte-identical.

**Headline:** all four cards landed. Two of them landed with a MEASURED
DEVIATION from the design's expectation, both recorded here with the numbers
that forced it and both filed as handoffs rather than silently absorbed:

* **D15-B gate (2) is NOT met and could not be met inside the card's OWNS.** The
  nav_instruct harness publishes NO person channel to the planner at all, so no
  proposer-side capability can see D-15's bystander. Measured: the flag-ON v4
  minival reproduces the frozen row **bit-for-bit**, exactly like flag-OFF.
  Enabling line lives in `src/parcel_robot/headless_city.py` — a file no card in
  this batch owns → **handoff H-1**.
* **The keepout ring is not painted by inflating the planner's agent
  footprints.** Measured ablation: doing so FLATTENS the Gaussian cost lobe and
  destroys the gradient A* detours on (0.05 m of progress against 3.86 m). The
  ring's proper home is a cost layer in `grid_navigator`/`grid_planner`, also
  unowned → **handoff H-2**. `person_keepout.keepout_cost_field` is written and
  tested, ready for it.

Nothing was committed. K0, the collision gate, the person distances, the veto
semantics, `reactive_safety.py`, and all four frozen digest sentinels are
byte-untouched.

---

## 1 — Card DOC-1 [landed]

Comment-only rewrite of `configs/navigation/default.yaml` `safety.person_slow_m`.
The old comment claimed the planner-side 2.0 m band "matches the runtime
reactive person band (2.0 m)"; since the E5 retune (2026-08-10) the runtime band
is 2.5 (`configs/robot.yaml`), so the comment asserted a match that no longer
holds. The replacement records the divergence, why the VALUE stays at 2.0 this
batch (moving it moves frozen v3/v4 rows), and that alignment is an owner
decision (record §8, OPEN QUESTION 6).

**GATE — measured:**

| check | result |
|---|---|
| `git diff` is comment-only | PASS — every added/removed line starts with `#`; no key, no value, no ordering changed (`git diff -U0` inspected line by line) |
| full test suite byte-unaffected | PASS — `yaml.safe_load` of the file equals `yaml.safe_load` of `HEAD`'s copy, exactly; ci_gate default-suite green (§5.1) |
| ci_gate --tier commit | PASS (§5.1) |

`does_not_prove`: does not prove 2.0 is the right planner-side band — it
documents that the question is open and owner-gated.

---

## 2 — Card D15-A [landed]

NEW `src/parcel_robot/navigation/person_keepout.py` + NEW
`tests/test_person_keepout.py`. Nothing existing edited (adjudication #20: the
no-literal-drift assertions live in the new test file;
`tests/test_authority_no_literal_drift.py` is untouched and still passes 27/27).

Contract, everything DERIVED from a passed `ReactiveSafetyPolicy`:

* `predictive_person_stop_m(policy, v)` — the gate's own threshold expression;
* `gate_vetoes(clearance, v, policy=…)` — the gate's inequality **verbatim**,
  including the `<=` boundary (adjudication #5);
* `keepout_radius_m(policy, v)` — the veto ring in planner (centre) coordinates:
  `person_stop_m + v·reaction_time_s + owner_collision_envelope_m`;
* `compliant_speed(clearance, policy=…)` — the FLOAT-LATTICE SUPREMUM, found by
  bracketing on the analytic root and bisecting the lattice until `lo` and `hi`
  are adjacent floats;
* `keepout_cost_field(...)` — the additive ring painter, shaped for
  `GridPlanner.set_dynamic_cost_layer` (finite, non-negative, a cost never a
  mask). Its planner-side consumer is handoff H-2.

**GATE — measured (12 tests, `tests/test_person_keepout.py`, all PASS):**

| gate clause | measured |
|---|---|
| D-15 veto pin to 4 dp | clearance `1.8132 − 0.55 = 1.2632`; threshold at v=0.85 = **1.3020**; `gate_vetoes` **True**; ring **1.8520** |
| `compliant_speed(1.2632) ≈ 0.5266` | **0.526666666666665** (`pytest.approx(0.5266, abs=1e-4)`) |
| gate False at v, True at `nextafter(v, +inf)` | **PASS** — and `v` is strictly below the analytic root `(1.2632−1.2)/0.12 = 0.5266666666666661`, which the `<=` boundary vetoes |
| property over randomized (clearance, policy) | **PASS**, 400 random policies × clearances: for every `v > compliant_speed` the gate vetoes; at `compliant_speed` it does not; empty admissible set ⇔ `clearance <= person_stop_m` |
| constants read from the policy instance | **PASS** — AST scan of the module: the only float literals are `0.0` and `2.0` (comparison zero, bisection divisor); none of `{1.0, 1.2, 2.5, 0.12, 0.55, 0.85, 1.3020, 1.2632, 1.8532, 0.5266}` appears |
| ci_gate --tier commit | PASS (§5.1) |

`does_not_prove`: proves nothing about any consumer's safety. The module
PROPOSES; `apply_reactive_safety` — untouched by this card — disposes.

---

## 3 — Card D15-B [landed, with gate (2) STOPPED and filed as H-1]

`person_aware_nav`, default OFF, wired in `src/parcel_robot/navigation/pipeline.py`
(Wave-1 owner) + the additive allowlist line in `evals/nav_instruct/runner.py`
+ NEW `tests/test_person_aware_nav.py`.

Flag-ON adds exactly two proposer-side behaviours:

1. **`_publish_person_costs`** — a person carried only on the SENSED scalar
   channel (`nearest_person_m` + `person_bearing_rad`) is converted into one
   entry of the payload the planner's own additive cost layer already consumes
   (`extras['dynamic_agents']`, the `grid_navigator._refresh_dynamic_costs`
   contract). It runs ONLY when both payloads are empty, so a person is never
   costed twice; the person's footprint is their own `owner_collision_envelope_m`
   from the policy; no perception is invented.
2. **`_person_compliant_translation`** — the commanded translation is capped at
   `compliant_speed(clearance)` for every declared person inside the comfort band
   that the command is CLOSING on. The closing predicate is the gate's own
   `_toward`, imported rather than restated, at a deliberately STRICTER
   half-angle (π/2 against the gate's 1.15 rad): a proposer may be stricter than
   its disposer, never looser. The cap can only reduce a command.

`apply_reactive_safety` is byte-untouched and still disposes every tick.

**GATE — measured:**

| gate clause | measured |
|---|---|
| (1) flag-OFF byte-identical: fresh v4 25-ep minival reproduces `nav-instruct-v1-baseline-v4-20260811T070536Z` | **PASS, bit-for-bit.** All 25 episode rows byte-equal (`json.dumps(..., sort_keys=True)` equality), `aggregate` equal, `episode_digest` `4113607b…` equal, SR 0.24. Digest over the whole report minus `{report_id, elapsed_s, scene, navigator_flags}`: frozen `ee234c6376d63dbfb9c1ffa1eb8d7333ac9fcfd57bc62495795cbe7010fa70f8` = fresh flag-off, identical. Protocol pinned: minival, baseline, v4, `scaled-path-v1`, max_steps 200, seed 20260804 — the frozen row's own protocol. Run in a scratch rsync of the tree (no ledger row in-tree). |
| (2) flag-ON, FULL 25-ep protocol, D-15 flips to success on v3 AND v4, twice | **NOT MET — STOPPED and reported (rule 2 / handoff H-1).** Measured: the flag-ON v4 minival produces the SAME digest `ee234c63…` — byte-identical to the frozen row, D-15 `mission_status=timed_out`, dtg `3.0282521329294605`, unchanged. Cause, measured: `parcel_robot/headless_city.py::_nav_observation` publishes no `owner_track`, no `dynamic_agents` and never sets `nearest_person_m`, and the owner mocap is not in the LiDAR obstacle set either — the planner is structurally blind to the bystander, so no proposer-side capability can engage. That file is in NO card's OWNS in this batch. v3 was not run: the same blindness applies (same harness), and running it would only reproduce a second frozen row. |
| (3) collisions 0, false_arrival 0, no currently-passing episode lost (SR ≥ 0.24) | **PASS** — flag-off and flag-on both: collisions 0, false_arrival 0, SR 0.24, identical rows |
| (3) trace-level floor: min person clearance ≥ `person_stop_m`, predictive criterion holds at every capped tick | **PASS where the capability can run** (D15-C's declared-bystander cell), read as an APPROACH floor — see the restatement below the table: the robot never closes on a person below `person_stop_m`; on the owner-declared pin case it holds station at an unrounded **1.2000000000000002 m** (= `person_stop_m` + 2.22e-16, one ULP ABOVE the floor) while the gate veto fraction goes **0.985 → 0.000**. These are consistency checks; the unmodified gate remains the mechanism (adjudication #6) |
| (4) ci_gate --tier commit | PASS (§5.1) |
| any frozen row moves | **NONE moved.** 4/4 digest sentinels byte-identical; ledger untouched (all runs in scratch) |

**Digest-recipe correction (AF-2, 2026-08-11).** Provenance:
`AUDIT_WAVE2_FABLE.md` should-fix 4 — "the ee234c63 recipe as documented does
not reproduce". Upheld, and corrected here at its source. Gate row (1) above
says "the whole report minus `{report_id, elapsed_s, scene, navigator_flags}`",
which is **four** fields; the recipe that actually produces
`ee234c6376d63dbfb9c1ffa1eb8d7333ac9fcfd57bc62495795cbe7010fa70f8` drops a
**fifth**, `refreeze_provenance`, and serialises with `json.dumps(...,
sort_keys=True)` at its DEFAULT separators. With the four documented fields the
digest is `200f5653706c4aea161b4aee1c5af6b9b2be2ef46aa808d4d163bafd6adead30`.
The form is also **path-dependent** — `aggregate.scene` is a second, absolute
copy of the scene path that the top-level `scene` exclusion does not reach — so
a run from any other directory cannot match it; drop `aggregate.scene` too for
the portable form (`897d6ce7…` at default separators, `c172da37…` compact). The
full recipe block and both episodes-payload recipes are in W2_WIRE1_STATUS.md
§4; all five values are pinned against the frozen row by
`tests/test_nav_instruct_digest_recipe.py`. Gate row (1)'s CLAIM is unaffected
(AF-2 re-ran the protocol and reproduced 25/25 byte-equal rows, `4113607b…`
unmoved, and `ee234c63…` exactly under the five-field recipe) — only the written
recipe was wrong.

**Trace-floor row, restated precisely (AF-1 correction, 2026-08-11).** The
original wording — "min clearance over every flag-ON run = 1.2000 m =
`person_stop_m` exactly, never below" — over-generalized in two ways the Wave-1
Fable audit caught. Both are restated here from a re-measurement, not argued:

* **Placement is not approach.** `min_clearance_m` is a minimum over the run
  INCLUDING the start pose, and `person_cell.bystander_position` puts the
  bystander on the route at exactly `clearance_m` of clearance from the start.
  The sweep's `1.10` rows (§4.1 A and B) therefore report **1.1000 = the placed
  value**, not an approach inside the floor: undeclared, along-route **0.000**,
  the robot never moves at all (189 blind vetoes); declared, along-route
  **2.0037**, the robot detours and never closes below the clearance it started
  at. Neither row is a case of the robot approaching a person below
  `person_stop_m`. The floor claim is an APPROACH floor and is stated that way
  above.
* **The 1.2 is rounded.** Every `CellOutcome` float is rounded to 6 dp on the
  way out (`evals/nav_instruct/person_cell.py:365` for `min_clearance_m`), so
  the reported `1.2000` was a display value. Re-measured unrounded, the
  declared-owner (`owner_track`, flag ON, clearance 1.2632) yield floor is
  **1.2000000000000002 m** (`0x1.3333333333334p+0`), i.e. `person_stop_m` +
  `2.220446049250313e-16` — one ULP ABOVE 1.2, never below it.

Measurement: one scratch re-run of that single cell via `person_cell.run_cell`
with the module-global `round` shadowed by the identity (no file edited, no
report written, ledger untouched). It reproduces the §4.1 C row exactly —
along-route `0.0635`, `compliant_cap_ticks` **207**, veto fraction **0.000**,
outcome `yield_hold`, collisions 0.

**NON-VACUITY — the flag-on path actually engages (measured, `tests/test_person_aware_nav.py`, 11 tests PASS):**

At D-15's exact geometry (owner centre 1.8132 m, clearance 1.2632 m), driving
the real pipeline for 12 ticks:

| arm | commanded vx | REAL `apply_reactive_safety` verdict |
|---|---|---|
| flag OFF | **0.85** (grid_v1 cruise) | `_stop_translation` → `(0.0, 0.0)`, note `stopped` — **the D-15 deadlock** |
| flag ON | **0.526666666666665** (= `compliant_speed`) | translation preserved, `vx > 0`, note in `{clear, slowing}` — **the deadlock is gone** |

Counters on the flag-ON navigator: `person_compliant_cap_ticks` **7 of 12**
(zero while the controller is still ramping below the cap). Control arm: flag
OFF, the identical observation WITH and WITHOUT the person payload produces
byte-identical commands over all 12 ticks and both counters stay 0.

**Deviation from the design (recorded, not absorbed):** the design's clause (i)
was "paint the derived keepout ring into the grid plan by giving each person the
ring as its footprint". It was implemented, measured, and REVERTED ON THE
MEASUREMENT.

**Ablation, measured on a straight-route scenario with a declared bystander at
the D-15 pin clearance (800-step budget, `dynamic_agents` declaration):**

| ring-inflated footprints | compliant cap | along-route progress | veto fraction | min clearance |
|---|---|---|---|---|
| — | — | 3.856 m (detour) | 0.000 | 1.2632 |
| ✓ | — | **0.046 m (deadlock)** | 0.980 | 1.2335 |
| — | ✓ | 3.857 m (detour) | 0.000 | 1.2632 |
| ✓ | ✓ | 0.109 m | 0.000 | 1.2000 |

Inflating the footprint to the ring is a net NEGATIVE: `agent_cost_at` broadens
each Gaussian by the track radius, so a 1.85 m ring spreads the lobe until the
detour is no longer cheaper than the straight line — the same "flat mesa erases
the gradient A* needs" defect that module already records for 2026-08-04. The
ring needs a cost layer with a sharp boundary, i.e.
`person_keepout.keepout_cost_field` installed via
`GridPlanner.set_dynamic_cost_layer` — inside `grid_navigator`, which no card in
this batch owns → **handoff H-2**. Clause (i) therefore landed re-scoped to
"publish the people the planner cannot see", which is what the same measurement
shows actually produces the detour.

**Second measured correction, inside the cap:** scaling a command by
`limit / speed` is not exact on the float lattice, and a magnitude one ULP above
the limit is vetoed by the gate's `<=`. Unguarded, that cost **0.519** of
translating ticks on the cell's owner-declared pin case. The cap now proves its
own output against `gate_vetoes` and walks the lattice down until the gate's
expression is False: **0.519 → 0.000**, floor unchanged at 1.2000 m. Pinned by
`test_capped_command_is_gate_approved_by_construction` over 8 clearances × 4
bearings.

`does_not_prove`: does not prove the capability changes any nav_instruct row
(it cannot, until H-1); does not prove behaviour with multiple simultaneous
people (the gate's people list still carries one stranger scalar + the owner —
record §8, OPEN QUESTION 7); does not prove anything about `follow.py`, which
this card never touches.

---

## 4 — Card D15-C [landed]

NEW `evals/nav_instruct/person_cell.py`, NEW `tests/test_person_cell.py`, NEW
`scrum/20260811/task_1/D15_ATTRIBUTION.md`.

The cell runs the REAL stack (pipeline, planner, world, and the untouched gate)
against a synthetic episode whose route is the ray from D-15's own start pose
through the world's real default bystander — clear of static obstacles for 10 m
(measured with `truth_minimum_clearance`) — with the bystander standing ON that
route at a chosen clearance. Three declaration channels (`none` = the frozen
condition, `owner_track` = planner weight 0.6, `dynamic_agents` = planner weight
2.5) × both flag arms. It writes its own report and never the ledger.

**GATE — measured (full sweep, 800-step budget; numbers in §4.1):**

| gate clause | measured |
|---|---|
| reproduces the D-15 deadlock signature at `person_stop_m` = 1.2 | **PASS** — undeclared bystander at clearance 1.2632: veto fraction **0.985**, **200** vetoes on ticks whose planner note reads `status=planned…\|clear`, along-route progress **0.027 m**, collisions 0 |
| sweep emits pass/deadlock/detour per clearance step, boundary at `1.2 + v·0.12` | **PASS** — see §4.1; every undeclared run stalls at a min clearance inside **[1.2000, 1.3020]**, i.e. between the standing-start bound and the cruise bound |
| `person_stop = 1.0` row carries its derived-not-run label | **PASS** — `{"label": "derived-not-run", "predictive_stop_m": 1.102, "gate_vetoes": false}`, with the `ValueError` from E5's guard pinned in the test |
| marginality table for the 4 moved episodes with measured band-edge margins | **PASS** — `D15_ATTRIBUTION.md` §4; only `object_goal-D-15` is marginal (6.7 mm outside its band in context, 0.0 alone) |
| 4/4 DIGEST_SENTINELS byte-identical | **PASS** (§5.1) |
| ledger append-only prefix unchanged | **PASS** — `evals/nav_instruct/results/ledger.jsonl` byte-identical (every measurement ran in a scratch rsync); the cell has no ledger writer at all (AST-asserted: its only filesystem writes are `mkdir` + `write_text`) |
| ci_gate --tier commit | PASS (§5.1) |

`does_not_prove`: recorded in the cell's report and in `D15_ATTRIBUTION.md` §7 —
does not prove the retune optimal (only causal); does not prove detour safety at
higher pedestrian density (one bystander); does not re-measure any frozen row;
the 1.0 arm is derived, not run; outcomes are budget-limited.

### 4.1 — Sweep results (measured, landed code, 800-step budget)

Veto boundary at cruise 0.85 m/s: **1.3020 m**
(`person_stop_m + speed·reaction_time_s`). Standing-start boundary:
**1.2000 m**. `blind vetoes` = ticks the gate stopped translation while the
planner note read `status=planned…|clear` — the D-15 signature.

**A. UNDECLARED (`none`) — the frozen condition:**

| clearance | flag | outcome | along-route | veto frac | blind vetoes | min clearance |
|---|---|---|---|---|---|---|
| 1.10 | off / on | deadlock / deadlock | 0.000 / 0.000 | 1.000 / 1.000 | 189 / 189 | 1.1000 / 1.1000 |
| 1.2632 | off / on | deadlock / deadlock | 0.027 / 0.027 | 0.985 / 0.985 | 200 / 200 | 1.2359 / 1.2359 |
| 1.35 | off / on | deadlock / deadlock | 0.112 / 0.112 | 0.976 / 0.976 | 200 / 200 | 1.2385 / 1.2385 |
| 1.60 | off / on | deadlock / deadlock | 0.310 / 0.310 | 0.962 / 0.962 | 200 / 200 | 1.2920 / 1.2920 |
| 2.20 | off / on | deadlock / deadlock | 0.977 / 0.974 | 0.926 / 0.926 | 200 / 200 | 1.2343 / 1.2400 |
| 3.00 | off / on | deadlock / deadlock | 1.731 / 1.731 | 0.889 / 0.889 | 200 / 200 | 1.3012 / 1.3012 |

Two readings. (a) **The boundary is measured**: every run stalls at a min
clearance in **[1.2000, 1.3020]** — between the standing-start bound and the
cruise bound, exactly the `person_stop_m + |v|·reaction_time_s` band, with the
1.10 m case (inside `person_stop_m`) never moving at all. (b) **flag-ON changes
nothing when nothing is declared** — every row is identical to its flag-OFF
twin. The capability needs perception and does not invent it; this is the same
fact that makes D15-B's gate (2) unreachable (handoff H-1).

**B. DECLARED as a bystander (`dynamic_agents`, planner weight 2.5):**

| clearance | flag | outcome | along-route | lateral | veto frac | min clearance |
|---|---|---|---|---|---|---|
| 1.10 | off / on | detour / detour | 2.003 / 2.004 | 2.716 / 2.715 | 0.000 / 0.000 | 1.1000 / 1.1000 |
| 1.2632 | off / on | detour / detour | 2.004 / 2.004 | 2.713 / 2.714 | 0.000 / 0.000 | 1.2632 / 1.2632 |
| 1.35 | off / on | detour / detour | 2.016 / 2.020 | 2.661 / 2.646 | 0.000 / 0.000 | 1.3500 / 1.3500 |
| 1.60 | off / on | detour_incomplete ×2 | 2.062 / 2.062 | 2.522 / 2.522 | 0.000 / 0.000 | 1.5995 / 1.5995 |
| 2.20 | off / on | detour_incomplete ×2 | 2.147 / 2.143 | 2.350 / 2.357 | 0.000 / 0.000 | 1.7494 / 1.7494 |
| 3.00 | off / on | detour_incomplete ×2 | 2.320 / 2.320 | 2.128 / 2.128 | 0.000 / 0.000 | 1.9078 / 1.9078 |

**Declaring the human is what removes the deadlock.** The gate never vetoes, the
planner routes around, and min clearance never drops below the placed clearance.
(`detour_incomplete` = still routing around when the 800-step budget ended.)

**C. Declaration probe at the D-15 pin clearance (1.2632 m):**

| declaration | flag | outcome | along-route | veto frac | blind vetoes | min clearance | cap ticks |
|---|---|---|---|---|---|---|---|
| none | off | **deadlock** | 0.027 | **0.985** | 200 | 1.2359 | 0 |
| none | on | deadlock | 0.027 | 0.985 | 200 | 1.2359 | 0 |
| owner_track (w 0.6) | off | deadlock | 0.026 | 0.985 | 200 | 1.2369 | 0 |
| owner_track (w 0.6) | **on** | **yield_hold** | 0.064 | **0.000** | **0** | **1.2000** | **207** |
| dynamic_agents (w 2.5) | off | detour | 2.004 | 0.000 | 0 | 1.2632 | 0 |
| dynamic_agents (w 2.5) | on | detour | 2.004 | 0.000 | 0 | 1.2632 | 0 |

The owner-declared row is the capability in isolation: the planner's reduced
owner weight is too weak to plan around the human, so flag-OFF the gate stops
the robot on 98.5% of translating ticks; flag-ON the robot slows ITSELF to the
compliant speed, the gate stops it on **none** of them, and it holds station at
exactly `person_stop_m` = 1.2000 m. A hard, invisible deadlock becomes a visible,
compliant yield. Collisions 0 in every row of the sweep.

Counterfactual row in the report, labelled `derived-not-run`:
`person_stop_m = 1.0` → predictive stop `1.1020 m` < clearance `1.2632 m` →
**no veto**, which is why the episode passed before the retune. Unrunnable on
this tree (E5's undercut guard raises `ValueError`; pinned in the test).

Cell runtime: 32 runs, ~9.5 min. Report written to the caller's directory
(scratch during this lane); the ledger was never touched.

---

## 5 — Verification, ownership, handoffs

### 5.1 Final gate state

`scripts/ci_gate.py --tier commit`: **PASS** (see §5.4 for the run this lane
finished on). Delta against the pre-lane baseline: `default-suite` 3390 → 3472
passed (this lane adds 37 tests to the commit tier: 12 D15-A + 19 D15-B + 6 D15-C,
plus 1 D15-C `slow`-marked test the commit tier deselects and this lane ran
directly — PASS; the remainder of the delta is the sibling W1-J lane's), ruff 7 violations / baseline 7 / **new 0**, 4/4 digest sentinels
byte-identical.

Frozen-artifact audit, all measured:

| artifact | state |
|---|---|
| 4 DIGEST_SENTINELS (v3 `eb1289e9…`, v4 `b2945444…`, embodied_plan `22736f6e…`, personal_convo `d338f335…`) | byte-identical (`frozen-digest-sentinels` gate PASS) |
| `nav-instruct-v1-baseline-v4-20260811T070536Z` row | reproduced bit-for-bit, flag-off AND flag-on (digest `ee234c63…`) |
| `evals/nav_instruct/results/ledger.jsonl` | byte-identical — every measurement ran in a scratch rsync of the tree (`/tmp/.../scratchpad/tree`) with the main venv by absolute path |
| `mutation_panel.json`, episode sets v1–v4, `configs/robot.yaml` | untouched |

### 5.2 Files this lane touched

| file | card | kind |
|---|---|---|
| `configs/navigation/default.yaml` | DOC-1 | comment lines only (0 non-comment lines changed; `yaml.safe_load` output identical to `HEAD`) |
| `src/parcel_robot/navigation/person_keepout.py` | D15-A | NEW |
| `tests/test_person_keepout.py` | D15-A | NEW |
| `src/parcel_robot/navigation/pipeline.py` | D15-B | edited (Wave-1 owner) |
| `evals/nav_instruct/runner.py` | D15-B | edited — the allowlist line only |
| `tests/test_person_aware_nav.py` | D15-B | NEW |
| `tests/test_e4_evidence_seams.py` | D15-B | edited — **OWNS deviation, see §5.3** |
| `evals/nav_instruct/person_cell.py` | D15-C | NEW |
| `tests/test_person_cell.py` | D15-C | NEW |
| `scrum/20260811/task_1/D15_ATTRIBUTION.md`, `W1_D15_STATUS.md` | D15-C / lane | NEW |

MUST-NOT-TOUCH honoured: `navigation/reactive_safety.py`, `navigation/follow.py`,
`runtime.py`, `configs/**` (other than DOC-1's comment), `evals/nav_instruct/episodes/**`,
the ledger prefix, `instructnav/arbiter.py`, `instructnav/scoring.py` — all
unmodified. The sibling W1-J lane's files (`runtime.py`, `core/hard_stop.py`,
`core/motion_shaping.py`, `navigation/velocity_shaping.py`, `core/stop_ramp.py`,
`evals/companion_nav/*`, `evals/companion/duplex_v1/run_duplex_v1.py`,
`scripts/ci_gate.py` and their tests) appear in `git status` and were NOT touched
by this lane.

### 5.3 OWNS deviation (one, declared)

`tests/test_e4_evidence_seams.py::test_navigator_overrides_defaults_to_empty_and_is_a_closed_set`
pins `ALLOWED_NAVIGATOR_OVERRIDES` by exact-set equality. D15-B's OWN authorized
one-line addition to that frozenset turns the pin red (measured: ci_gate
`default-suite` FAIL, 1 failed / 3463 passed). The pin was moved by exactly one
name, with a comment recording which card moved it and that the flag defaults to
False. The alternative — leaving the suite red — is not available under rule 1.
Flagged here so the Wave-1 audit sees it in the diff without hunting: **VS-4 will
need the same one-name edit in Wave 2.**

### 5.4 Handoffs (enumerated; NOT done by this lane)

**H-1 — the nav_instruct harness publishes no person channel to the planner.**
`src/parcel_robot/headless_city.py::_nav_observation` (~line 913) builds the
`NavObservation` the runner hands to `DirectiveNavigator.step` and carries
`nearest_person_m=observation.nearest_person_m` (always `None` in this world),
no `owner_track`, no `dynamic_agents`; the owner mocap is also absent from
`_obstacle_geom_ids`, so it is not in `lidar_obstacles` either. The planner is
structurally blind to the D-15 bystander, which is why the flag-ON minival is
byte-identical to flag-OFF. The enabling change is one entry in that extras dict:

```python
"owner_track": (
    {"id": observation.owner.owner_id, "x": observation.owner.x,
     "y": observation.owner.y, "vx": 0.0, "vy": 0.0, "radius_m": 0.55},
) if observation.owner.visible else (),
```

which is the payload `runtime.py::_owner_track_payload` already publishes on the
product path. **It is in no card's OWNS in this batch** (`headless_city.py` has
zero owners in the §6.1 matrix) and it would MOVE FROZEN ROWS the moment it
lands unconditionally, so it needs an owner decision on flag-gating and a
re-freeze plan. Until then D15-B's gate (2) cannot be run and the capability is
exercised only through D15-C's cell, which declares its own bystanders.

**H-2 — the keepout ring has no cost-layer home.** `keepout_cost_field` is
written, tested, and shaped for `GridPlanner.set_dynamic_cost_layer`, but the
only caller of that setter is `grid_navigator._refresh_dynamic_costs`, which
overwrites the layer every tick and lives in a file no card owns. Expressing the
ring through the existing Gaussian payload instead was measured and rejected
(§3). The card-sized change: a keepout layer merged into `_refresh_dynamic_costs`
behind the same `person_aware_nav` flag, plus the sharp-boundary cost field
already available.

**H-3 (note, not a request)** — the sweep shows the planner detours around a
declared STRANGER (weight 2.5) but not around a declared OWNER (weight 0.6). That
asymmetry is deliberate (`dynamic_layer`: "a follower that reads its own owner as
an obstacle wall cannot follow"), and it means a robot on a NAVIGATION mission
treats the person standing in its way more leniently because that person happens
to be its owner. Whether a nav mission should use the stranger weight is an owner
decision, not a bug this lane may fix.

### 5.5 `does_not_prove` (lane-level)

* Nothing here proves the retune optimal, only that it is the cause (D15_ATTRIBUTION §7).
* No frozen row moved, and none was re-frozen; the D-15 loss is still carried
  honestly by the v4 row at SR 0.24.
* The capability is proved on synthetic declared-bystander geometry and in unit
  tests against the real gate; it is NOT proved on any frozen eval row, and
  cannot be until H-1.
* Single-bystander only. Nothing is claimed about multi-person scenes, moving
  pedestrians, or the follow/circle worlds' own undeclared owner (record §8,
  OPEN QUESTIONS 5 and 7).
* `person_aware_nav` stays default OFF. Flipping it is an owner decision on
  these numbers (record §8, OPEN QUESTION 1), and would require re-checking the
  V-D/V-E pre-registered margins on the same harness.
