# VALUE-CHANGES-MEASURED-1 — DESIGN (pre-registered, written before any run)

**Card:** `scrum/20260830/task_1/W6_VALUE_CHANGES_MEASURED.md` · **Executor:** Opus ·
**Verifier:** Fable · **Opened:** 2026-08-30 06:43 EDT · **RESEARCH ONLY — no product edit,
no config edit, no git write, $0.**

Frozen at the timestamp above. Every arm, every injection, every reported row is
named here BEFORE the first episode runs. `RESULTS.md` may add nothing to this
list; anything it discovers that is not pre-registered is reported as an
*unregistered observation* and labelled.

---

## 1. The question

Wave A wrote up two value changes and deliberately did not take either. Both are
now owner re-freeze decisions, and neither has ever been measured on the three
frozen instruments at once. This card measures them. **It does not flip them.**

| value | shipped today | the change | provenance |
|---|---|---|---|
| **V1 — the release door** | `progress_watchdog.held_stall_release` absent from the shipped profile, `DirectiveNavigator` default `False` | `True` | C3 §F1 (`scrum/20260829/task_2/C3_STATUS.md` §F1.1–F1.4), `AUDIT_C3.md` §5 |
| **V2 — the planner's demand** | planner `inflation_radius_m` = `1.12 · sin(1.15)` = **1.0223 m** (the gate's directional-cone discount) | **1.12 m** — the full `gate_range_ring_m` | C3 §1.5(a), §5.1, §F1.4 — the **0.0977 m residual** |

C3's measured claims that this card re-tests, on a *newer* tree (HEAD `c96ac34`,
not 704ba5c) and against *three* instruments rather than one:

* V1 alone: non-POI `navigation_no_progress` **47 → 10**, strict success flat
  (342 = 342), `semantic_target_unreachable` **63 → 96**, 0 collisions, 1 episode
  under 0.65 m, 48/530 rows changed. Frozen-row effect on the panel **NOT
  MEASURED** (`AUDIT_C3.md` §4.1: "C3 flag ON alone → frozen panel is NOT
  MEASURED").
* V2: "kills class A at the source … and would not shift a single episode into
  `semantic_target_unreachable`" — an *argument*, never a measurement.

Neither claim has a frozen-corpus price attached. That price is this card's output.

## 2. Arms — 4 + 1 reference

Two binary values, fully crossed. The fifth arm is the plumbing control.

| arm | release door | planner demand | what it is |
|---|---|---|---|
| `A0ref` | OFF | 1.0223 m | **reference**: the repo's own `configs/navigation/default.yaml`, untouched, no scratch tree. NG1's `A0`. |
| `off_disc` | OFF | 1.0223 m | **baseline arm**: a scratch config tree at the commissioned values. Must be byte-identical to `A0ref`. |
| `on_disc` | **ON** | 1.0223 m | **V1 alone** |
| `off_full` | OFF | **1.12 m** | **V2 alone** |
| `on_full` | **ON** | **1.12 m** | **V1 + V2** |

`off_disc` vs `A0ref` is the licence for every other arm: it proves that moving
the harness from the repo config path to a scratch config tree changes nothing,
so any difference in `on_disc` / `off_full` / `on_full` is the *value*, not the
plumbing. NG1's own `results.json` records the same control as
`plumbing_control_A0_vs_A0c_identical: true`; this card re-establishes it at
HEAD `c96ac34` rather than citing it.

**Pre-registered pass condition for the control:** `off_disc` and `A0ref` rows are
byte-identical (`json.dumps(sort_keys=True)`) on all 530 episodes. If they are
not, every arm below is reported as UNLICENSED and the card stops.

## 3. Injection — harness overrides only, never a config edit

`configs/navigation/default.yaml`, `configs/navigation/models/grid.yaml` and
`configs/robot.yaml` in the worktree are **read-only inputs**; `git status` at
close must show only untracked research files. Each arm gets its own navigation
config **tree** under `$NG1_SCRATCH/navcfg/<arm>/` — exactly NG1's idiom
(`research/20260829/nav-gen-attribution-1/run.py::build_arm_config`, "the ONLY
override: which navigation config tree the navigator is built from").

### 3.1 V1 — the release door: an added key in the scratch `default.yaml`

```yaml
progress_watchdog:
  held_stall_release: true      # <- the only added line
  timeout_steps: 200
  max_semantic_replans: 2
```

Read by `pipeline.py:1027-1031` (`DirectiveNavigator.from_config`, key
`held_stall_release`, default `False`) into `DirectiveNavigator.held_stall_release`
and consumed by `stall_attribution.held_release_due()` (`stall_attribution.py:190`,
`HELD_RELEASE_FLAG` at `:82`, `HELD_RELEASE_AFTER = 2` at `:97`; consumed at `pipeline.py:4650`, ctor `:530`/`:734`). This is the same
door C3 shipped default-OFF; the shipped profile is not edited and does not carry
the key. **This is the value change itself, not a proxy.**

### 3.2 V2 — the full 1.12 m demand: an added key in the scratch `grid.yaml`

The chain the number travels, all at HEAD:

```
DirectiveNavigator._planner_gate_ring_m()            pipeline.py:1151-1172
    -> self.collision.obstacle_stop_m = 0.80         (nav default.yaml safety.stop_distance_m)
_create_navigator -> options["map_gate_clearance_m"] = 0.80        pipeline.py:1185
grid_navigator._planner_coupling_ring_m(0.80, ...)   grid_navigator.py:21-60
    -> ClearanceProfile.gate_range_ring_m = 0.80 + 0.32 = 1.12     authority.py:1091-1118
GridPlannerConfig.gate_clearance_m = 1.12            grid_navigator.py:306
GridPlannerConfig.inflation_radius_m                 grid_planner.py:328-341
    = max(robot_radius_m + effective_hard_margin_m,   0.32 + 0.10 = 0.42
          gate_lateral_clearance_m)                   1.12 * sin(1.15) = 1.0222956
    = 1.0222956                                       <- the shipped demand
```

The 0.0977 m residual is `1.12 − 1.0222956 = 0.0977044`.

**There is no config key that removes the `sin θ` discount.** The discount is
`authority.gate_lateral_clearance_m` (`authority.py:862-893`) applied at
`grid_planner.py:325`; `GATE_TOWARD_HALF_ANGLE_RAD = 1.15` is a module constant
(`authority.py:202`). *Removing the discount* is a product edit — the honest one
being `grid_planner.py:339-341`'s `max(...)` second term, or
`grid_navigator.py:306`'s conversion.

**What is reachable without a product edit is the number itself.** The first term
of that same `max` is config-driven:

```yaml
controller:
  map_safety_margin_m: 0.10
  map_hard_safety_margin_m: 0.80   # <- the only added line;  0.32 + 0.80 = 1.12
```

`map_hard_safety_margin_m` is a real `GridNavigator.__init__` parameter
(`grid_navigator.py:145`), and `NavigationModelRegistry.create` merges the YAML
`controller:` block **under** the explicit kwargs (`registry.py:60-62`), so
`map_gate_clearance_m` still arrives from the brake as before, untouched.

**Verified on the live objects before pre-registration** (worktree `w6`, HEAD
`c96ac34`):

| | `off_disc` tree | `off_full` tree |
|---|---|---|
| `DirectiveNavigator.held_stall_release` | `False` | `False` |
| `DirectiveNavigator.collision.obstacle_stop_m` | `0.8` | **`0.8` (unmoved)** |
| `GridPlannerConfig.gate_clearance_m` | `1.12` | **`1.12` (unmoved)** |
| `GridPlannerConfig.gate_lateral_clearance_m` | `1.022296` | `1.022296` (unmoved) |
| `GridPlannerConfig.effective_hard_margin_m` | `0.10` | `0.80` |
| **`GridPlannerConfig.inflation_radius_m`** | **`1.022296`** | **`1.12`** |
| `comfort_radius_m` / `comfort_cost_enabled` | `0.42` / `False` | `1.12` / **`False`** |

**Exactness, stated plainly.** The injected arm reaches the *identical* value of
the *identical* quantity the product edit would move — `inflation_radius_m = 1.12`,
the planner's hard non-traversable radius, which is the only thing either edit
changes on this profile. It reaches it through the **first** term of the `max`
(footprint + hard margin) rather than the **second** (the gate's discounted
lateral demand). **This is an exact-value injection, not a proxy**, and the two
differ nowhere on this profile. Where they *would* differ, recorded now so nobody
over-reads the result:

1. a product edit removing the discount would also move the DOOR-1 seed-detector
   comparison at `grid_planner.py:291-299` (it compares against
   `gate_lateral_clearance_m`), and would move **every** commissioned profile
   (e.g. the person map, and NG1's sweep-B stop distances) by the same rule; the
   injection moves only this one profile's number;
2. `effective_comfort_margin_m` follows the hard margin when
   `comfort_safety_margin_m` is unset, so `comfort_radius_m` moves 0.42 → 1.12 in
   the injected arm. `comfort_cost_weight` is `0.0` on the shipped `grid.yaml`
   and `comfort_cost_enabled` therefore stays `False` **in both arms** (measured
   above) — the comfort cost layer is inert either way, so this cannot reach
   behaviour. Registered as the one mechanism-difference that exists, and it is
   provably dead.

No safety floor is touched by either injection: `configs/robot.yaml`
`safety.obstacle_stop_m 0.65` / `obstacle_slow_m 1.2` and the navigation config's
`safety.stop_distance_m 0.80` are identical in all five arms and asserted per work
unit by NG1's own `run_unit`.

### 3.3 Reaching the minival and the panel

`NavInstructRunner`'s `navigator_overrides` idiom (`evals/nav_instruct/runner.py:83-99`)
is a **closed whitelist** — `value_directed_search`, `detection_lock_on`,
`person_aware_nav`, `lock_on_verify_on_approach`, `route_memory`. **Neither
`held_stall_release` nor any planner-margin key is on it**, and adding one is a
product edit to `evals/`. So the minival and panel arms are injected the same way
NG1 injects: by the navigation config **tree** the harness builds its navigator
from. In-process, harness-side, for the lifetime of one child process:

```python
headless_city._navigation_config_from_store = lambda store: ARM_CONFIG_PATH
```

`HeadlessCityQualityHarness.__init__` (`headless_city.py:679`) assigns
`self.navigation_config` from that one function, and `NavInstructRunner._navigator`
(`runner.py:777-783`) is the only consumer. `robot_config` is untouched, so the
runtime reactive gate keeps `robot.yaml`'s 0.65 m ring in every arm. Each arm runs
in its **own child process**; nothing is patched in a process that also runs
another arm.

The patch is asserted live in every child before the first episode
(`navigator.held_stall_release` and `planner.config.inflation_radius_m` read off a
real `DirectiveNavigator.from_config(...)`), and the assertion is written into
`results.json`. A silent patch failure would otherwise report the baseline four
times.

## 4. Instruments and the rows, per arm

Three instruments, all frozen corpora, all in isolated scratch under
`~/.cache/parcel-0e/w6/`. `NG1_SCRATCH=~/.cache/parcel-0e/w6/ng1`, shared across
arms so the 30 generated scenes are built **once** and every arm runs the
identical worlds; arms are separated by row-file name, never by scene.

### I1 — NAV-GEN-1 A0, 530 episodes (450 generated + 80 frozen demo)

Harness: `research/20260829/nav-gen-attribution-1/{episodes,run}.py`, imported by
path from the worktree, **read-only** (a foreign card's folder — not edited, not
copied-and-modified; only `build_arm_config` is replaced, in my own module).

Pre-registered rows, per arm, generated block and frozen block reported separately
and both:

1. `strict_success` (MA-1 single-instance oracle) and `strict_success_any_instance`
2. `settled_success`
3. `arrived_verified`
4. terminal-reason histogram in full, with **`navigation_no_progress` split
   POI / non-POI** (non-POI = `target` not `crosswalk`, C3 §1.1's split)
5. `semantic_target_unreachable`
6. `collision_count` sum, and episode count with any collision
7. episodes with `minimum_clearance_m < 0.65`
8. total `steps` and median `steps`
9. `false_arrival`
10. band entry (`band_entry`, `band_entry_any_instance`)
11. rows changed vs `off_disc` by **full-row** dict comparison (C3's correction
    (a): reason-only comparison undercounts), and the **named** episode ids of
    every strict regression and strict gain
12. rows ending `status == "planned"` with no terminal reason (C3 amendment A1's
    row — an arm that makes a stall *quieter* is disqualified on sight)

### I2 — the v4 minival, 25 episodes

```
python -m evals.nav_instruct.run_nav_instruct_v1 --minival --mode baseline \
  --episode-version v4 --no-ledger --out <scratch>/<arm>
```

driven in-process, per arm, with §3.3's patch in force.

1. **report digest** by the recipe `tests/test_nav_instruct_digest_recipe.py`
   pins: drop the five fields
   `{report_id, elapsed_s, scene, navigator_flags, refreeze_provenance}`, drop
   `aggregate.scene`, `json.dumps(sort_keys=True, separators=(",", ":"))`, sha256
2. `episode_digest` — the **episode SET**. Pre-registered expectation: identical
   in all five arms (`4113607b92c734df…`). A move here would mean the harness,
   not the value, changed, and invalidates the card.
3. the required HEAD digest **`021b67ab73c4e7be647aba1a17e20a193ebf23b826a18d5b0990e296e5708496`**
   (C3 §F1.2, re-established by `A0ref`/`off_disc` here). Every arm's digest is
   reported as MOVED / UNMOVED against it.
4. **every moved row NAMED** — episode id, `success` before/after, `failure`
   before/after, `distance_to_goal_m` before/after — with a one-line reason read
   off the row, never guessed.
5. success rate, authority histogram (`agreement` / `authority_disagreement` /
   `tolerated_boundary` / `false_arrival`), collisions.

### I3 — the mutation panel

```
python scripts/mutation_panel.py --out <scratch>/<arm>.panel.json
```

driven in-process per arm with the same patch, `run_panel()` called directly so
the tree's committed panel is never written (`--out` into scratch only; the
in-tree `evals/nav_instruct/results/mutation_panel.json` is never the target —
`AUDIT_C3.md` §4.1's lesson: an arm that exits before writing `--out` reports the
artifact that was already sitting there, not a measurement. Every panel row in
`RESULTS.md` carries its own `generated_at`).

1. `passed`
2. `survivors` — the panel's own failure condition
3. `equivalent_mutants`
4. clean-run `authority` histogram (HEAD reads `{agreement: 4, authority_disagreement: 1}`)
5. clean-run `mean_dtg_m`, `collisions`, `successes`
6. **kill channels per mutant** — the `checks_reddened` list for each of the seven
   mutants (`arrival_radius_x2`, `reactive_gate_disabled`, `pose_offset_0m5`,
   `inverted_relation`, `dropped_detections`, `doubled_envelope`,
   `phantom_view_consistent`), and the count. HEAD live reads
   `reactive_gate_disabled` killed through **2** channels
   (`success_set_identical`, `failure_histogram_identical`) — `AUDIT_C3.md` §4.1.
   **A value that thins `reactive_gate_disabled` below 2 channels, or lets it
   survive, is the single most important negative result this card can produce**
   and is reported first in the decision table.

## 5. Output

`RESULTS.md`: a **decision table** — rows are the instruments' pre-registered
quantities, columns are the four arms, with `A0ref` as the reference column.
**No bars, no criterion, no verdict, no flip.** Frozen-row moves are NAMED per
arm (episode ids, not counts). One paragraph of recommendation per value, stating
what it buys, what it costs on the frozen corpora, and what the owner has to
re-freeze if they take it. `results.json` carries every number in the tables;
nothing in `RESULTS.md` is typed by hand that is not in `results.json`.

## 6. What this design cannot answer

* **Nothing here is physical.** Evidence tier `desktop-sim`; physical motion
  NO-GO, unchanged. No hardware exists (owner, 08-22).
* The 1.12 m arm measures the **number**, not a product implementation of it
  (§3.2). A real edit would move every commissioned profile at once; this arm
  moves one.
* The minival and panel corpora are 25 and 4 episodes. A digest that does not move
  is evidence about **those** episodes, not a guarantee.
* The generated block is 30 scenes from one generator seed family. NG1's own
  RESULTS is the authority on what that block does and does not represent.
* Interaction is measured (arm `on_full`) but not *explained*: this card reports
  whether V1+V2 is more than the sum of its parts, not why.

## 7. Host discipline

`TMPDIR` unset on every command; `PYTHONPATH=<worktree>/src:<worktree>`;
`MUJOCO_GL=egl`; worktree at HEAD `c96ac34`, `.parcel` symlinked. `uptime` recorded
at start and end. **≤ 16 pool workers** for the NG1 sweep and 4 single-process arm
children beside it — five other executors share this 192-core host. No
`pytest -n auto`, ever; any pytest goes through
`~/.cache/parcel-guard/pytest_guard.sh`. No `ci_gate.py` (executors never run it).
No `--pdb`. No watcher loop. Every process this card starts is killed by this
card. The owner's `:8765` / `/tmp/parcel_sim.sock` / `parcel_memory.sqlite3` are
never touched (`PARCEL_MEMORY_PATH` points into this card's scratch). No hosted
call: **$0**.
