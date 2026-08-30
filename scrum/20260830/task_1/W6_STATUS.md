# W6 · VALUE-CHANGES-MEASURED-1 — executor status (Opus)

**Card:** `scrum/20260830/task_1/W6_VALUE_CHANGES_MEASURED.md` · **Verifier:** Fable ·
**Wave:** B · **RESEARCH ONLY — no product edit, no config edit, no git write, $0.**

Written incrementally. §0 pre-flight → §1 the pre-registered DESIGN and the
injection proof → §2 the frozen corpora → §3 NAV-GEN-1 → §4 the decision table →
§5 close.

---

## 0. Pre-flight

| item | value |
|---|---|
| worktree | `/home/jaewoo-jang/.cache/parcel-0e/wb/w6`, `git worktree add --detach … HEAD` |
| HEAD measured | **`c96ac34`** ("index: regenerate CODEBASE_INDEX.md in a clean worktree at 05a5cb9") |
| `git status` in the worktree at start | `?? .parcel` only (the symlink) — **no owner diff, no peer card** |
| product import proof | `python -c "import parcel_robot; print(parcel_robot.__file__)"` → `/home/jaewoo-jang/.cache/parcel-0e/wb/w6/src/parcel_robot/__init__.py` |
| env, every shell | `PYTHONPATH=<wt>/src:<wt>`, `MUJOCO_GL=egl`, `TMPDIR` **unset**, `W6_REPO=<wt>` |
| host at start | `06:38 up 7 days`, load **1.80** / 1.78 / 1.77, 192 cores, 246 GB (5 peers share it) |
| card scratch | `~/.cache/parcel-0e/w6/` (`ng1/` rows, `frozen/<arm>/`, `door_reach/`, `logs/`) |
| workers | NG1 pool **16** (card cap), 5 single-process frozen children beside it |
| hosted spend | **$0** — no hosted call on this card |
| product / config files edited | **none.** Every value is a harness override into a scratch config tree. |
| `configs/**` edited | **none** — asserted by `git status` at close (§5) |
| pytest run | none needed (no product change to regress); the guard was therefore never invoked |
| OWNS written | `research/20260830/value-changes-1/` (created) and this file |

**Instruments, all at HEAD `c96ac34`, all in isolated scratch:**

| instrument | corpus | driver |
|---|---|---|
| I1 NAV-GEN-1 A0 | 530 episodes (450 generated + 80 frozen demo) | `research/20260829/nav-gen-attribution-1/{episodes,run}.py`, imported **read-only** by path; only `build_arm_config` is this card's own |
| I2 v4 minival | 25 episodes | `evals.nav_instruct.run_nav_instruct_v1 --minival --mode baseline --episode-version v4 --no-ledger` |
| I3 mutation panel | 5 clean + 7 mutants | `scripts/mutation_panel.py::run_panel`, written to **scratch only** |

---

## 1. The DESIGN and the injection — pre-registered before the first episode

`research/20260830/value-changes-1/DESIGN.md`, frozen **2026-08-30 06:43 EDT**;
the first episode ran at 06:47. It names the five arms, both injections, every
reported row, and §6 "what this design cannot answer".

**Arms — two binary values, fully crossed, plus a plumbing reference.**

| arm | `held_stall_release` | planner `inflation_radius_m` |
|---|---|---|
| `A0ref` | False | 1.022296 m — **the repo config path itself, untouched** |
| `off_disc` | False | 1.022296 m — scratch tree (baseline) |
| `on_disc` | **True** | 1.022296 m — **V1 alone** |
| `off_full` | False | **1.12 m** — **V2 alone** |
| `on_full` | **True** | **1.12 m** — V1 + V2 |

**Both values are reachable as harness overrides. Neither is a proxy.** Read off
the LIVE objects in every process before the first episode (`values_harness.py::assert_arm`,
recorded per arm in `results.json` → `arm_facts`):

| live reading | `off_disc` | `on_disc` | `off_full` | `on_full` |
|---|---|---|---|---|
| `DirectiveNavigator.held_stall_release` | False | **True** | False | **True** |
| `GridPlannerConfig.inflation_radius_m` | 1.022296 | 1.022296 | **1.12** | **1.12** |
| `GridPlannerConfig.gate_clearance_m` | 1.12 | 1.12 | 1.12 | 1.12 |
| `DirectiveNavigator.collision.obstacle_stop_m` | 0.8 | 0.8 | **0.8** | **0.8** |
| runtime reactive gate `obstacle_stop_m` | 0.65 | 0.65 | **0.65** | **0.65** |

* **V1** is the C3 flag itself: `progress_watchdog.held_stall_release: true` added
  to the arm's scratch `default.yaml`, read at `pipeline.py:1027-1031`, stored at
  `:734`, consumed at `:4650`.
* **V2** is `controller.map_hard_safety_margin_m: 0.80` added to the arm's scratch
  `grid.yaml`. `0.32 + 0.80 = 1.12`, so `GridPlannerConfig.inflation_radius_m`
  (`grid_planner.py:328-341`) resolves to **exactly 1.12** instead of
  `1.12·sin(1.15) = 1.0222956`.

**The card's "if the 1.12 m demand cannot be injected without a product edit, say
exactly which line" — answered, and then bettered.** The line that would have to
be edited to *remove the directional-cone discount* is
**`src/parcel_robot/navigation/grid_planner.py:339-341`** — the second term of

```python
return max(
    self.robot_radius_m + self.effective_hard_margin_m,
    self.gate_lateral_clearance_m,          # <- grid_planner.py:341, = gate_clearance_m * sin(1.15)
)
```

(equivalently `grid_planner.py:325`'s `gate_lateral_clearance_m(self.gate_clearance_m)`,
or `grid_navigator.py:306`'s conversion). **No config key removes that `sin θ`.**
But the *number the planner demands* is reachable through the FIRST term of the
same `max`, and that is a real `GridNavigator.__init__` parameter
(`grid_navigator.py:145`) that the model registry takes from the YAML
`controller:` block (`registry.py:60-62`, YAML merged **under** the explicit
kwargs, so the commissioned gate ring still arrives from the brake untouched).

So this is an **exact-value injection, not a proxy**: the arm reaches the
identical value of the identical quantity — `inflation_radius_m = 1.12`, the
planner's hard non-traversable radius — that the product edit would produce on
this profile. The two mechanism differences are named in `DESIGN.md` §3.2 and
neither can reach behaviour here: (a) a real edit would move **every**
commissioned profile and the DOOR-1 seed-detector comparison at
`grid_planner.py:291-299`, this arm moves one profile; (b) `comfort_radius_m`
follows the hard margin (0.42 → 1.12), but `comfort_cost_weight` is `0.0` on the
shipped `grid.yaml`, so `comfort_cost_enabled` is **False in both arms** (measured,
§1's live table's source row in `results.json`) — the comfort layer is inert
either way.

**Plumbing control (pre-registered pass condition).** `off_disc` must reproduce
`A0ref` byte-identically or every arm is UNLICENSED. Result in §2.

---

## 2. The plumbing control — the card is licensed

`off_disc` (scratch config tree at the commissioned values) vs `A0ref` (the repo
`configs/navigation/default.yaml` itself), all three instruments:

| leg | result |
|---|---|
| NAV-GEN-1, 530 rows, outcome-field comparison | **530 / 530 byte-identical** |
| v4 minival report digest | **identical** — `021b67ab73c4e7be…` both |
| mutation panel payload | **identical** (excluding `generated_at` and this driver's own path / wall fields) |

**LICENSED.** Every difference in §3–§4 is the value, not the plumbing.

> **One analysis defect, found by the control and recorded.** The first analysis
> pass compared whole row dicts and reported "530/530 rows changed" for *every*
> arm, the control included — because each row carries its own `"arm"` label.
> `analyze_values.py` now excludes it (`ROW_IDENTITY_FIELDS`). The control is
> what caught it: two arms whose every aggregate matched could not honestly have
> had zero identical rows. All §3–§4 numbers are post-fix.

## 3. Results — the decision table

Full table, named rows and both recommendations:
`research/20260830/value-changes-1/RESULTS.md` §0, §3, §5.

| | `off_disc` shipped | `on_disc` V1 | `off_full` V2 | `on_full` V1+V2 |
|---|---|---|---|---|
| strict success (450 gen) | 343 | 343 (0) | 351 (+8) | 350 (+7) |
| settled success | 339 | 339 (0) | 346 (+7) | 345 (+6) |
| `arrived_verified` | 295 | 300 (+5) | 307 (+12) | **316 (+21)** |
| `navigation_no_progress` | 49 | **10** | 32 | **2** |
| `semantic_target_unreachable` | 62 | **95** | 66 | 87 |
| **collisions** | **0** | **0** | **0** | **0** |
| **episodes < 0.65 m** | **1** | **1** | **4** | **3** |
| worst `minimum_clearance_m` | 0.6275 | 0.6275 | **0.5837** | **0.5837** |
| steps (gen) | 128 094 | +4.0 % | **−5.9 %** | −3.4 % |
| **v4 minival digest** | `021b67ab…` | **`021b67ab…` UNMOVED** | **`5e49ef19…` MOVED** | **`5e49ef19…` MOVED** |
| minival rows / verdicts moved | — | **0 / 0** | 3 / **0** | 3 / **0** |
| **mutation panel** | pass, `{4,1}`, [] | **identical to `A0ref`** | pass, 2 clean rows moved | pass, 2 clean rows moved |
| `reactive_gate_disabled` channels | 2 | 2 | **3** | **3** |
| frozen demo rows moved (80) | — | **1** | **34** | **34** |
| whole-run rows moved (530) | — | 48 | 132 | 150 |
| strict regressions / gains | — | 2 / 2 | 10 / 21 | 11 / 21 |

**Frozen-row moves NAMED** (RESULTS §3): `on_disc` — minival 0 rows, panel
identical, frozen demo **`frozen:lamppost:10`** only. `off_full` / `on_full` —
minival `nav-region_goal-A-00-1c735162`, `nav-region_goal-D-15-1b8b2361`,
`nav-object_relative-D-15-61f68ad6` (no verdict moves); panel clean rows
`nav-region_goal-A-00-1c735162`, `nav-region_goal-D-15-1b8b2361`; frozen demo
strict regressions `frozen:bench:7`, `frozen:planter:10`, `frozen:sidewalk:6`,
`frozen:sidewalk:10` against gains `frozen:crosswalk:{3,4,7,10,15}`,
`frozen:lamppost:{6,15}` (net +3). `episode_digest` `4113607b92c734df…` is
unmoved in all five arms — **the episode SET never moved**.

**C3 §F1.3 reproduced independently at a different HEAD.** `on_disc` reads
48/530 full-row changes (C3: 48), 41 terminal-reason changes (C3: 41), 2 strict
regressions / 2 gains (C3: 2/2), the same four named episodes
(`gen:880007:crosswalk:1`, `gen:880016:crosswalk:0` /
`gen:880009:sidewalk:1`, `gen:880014:crosswalk:0`), strict success flat,
collisions 0, sub-band count unmoved, 0 rows `status=planned` with no terminal
reason. Stalls read 49 → 10 here against C3's 47 → 10.

## 4. The finding that qualifies the V1 green

`AUDIT_C3.md` §4.1 left "C3 flag ON alone → frozen panel" **NOT MEASURED**. It is
measured now, and the honest reading is two-part:

* the release door moves the frozen minival and the frozen panel **by zero**;
* **because the frozen corpora cannot reach it.** `door_reach.py` wraps
  `stall_attribution.held_release_due` and runs the full 25-episode v4 minival
  with the flag ON: **0 calls, 0 releases**, on both `on_disc` and `on_full`.
  The minival's `max_steps` is 200 and `progress_watchdog.timeout_steps` is 200,
  so the watchdog window cannot expire inside an episode; no minival episode ends
  `navigation_no_progress`. The panel's five episodes are a **subset** of those
  25 (verified in-process), so the same zero covers the panel.

The E3 concern is therefore disposed of — the door cannot move a frozen
hard-safety artifact — but "no frozen move" is evidence about the corpus's step
budget, not a safety argument for the door. Recorded as such in RESULTS §4 and
carried into the V1 recommendation.

## 5. Close

### 5.1 Files written (all inside this card's OWNS)

| file | what |
|---|---|
| `research/20260830/value-changes-1/DESIGN.md` | pre-registered, frozen 06:43 EDT before the first episode (06:47) |
| `research/20260830/value-changes-1/values_harness.py` | the five arms, the config-tree injection, the live per-arm assertion, the three instruments |
| `research/20260830/value-changes-1/door_reach.py` | §4's instrument |
| `research/20260830/value-changes-1/analyze_values.py` | every table; nothing typed by hand |
| `research/20260830/value-changes-1/RESULTS.md` | the decision table, the named moves, one recommendation per value |
| `research/20260830/value-changes-1/results.json` | every number behind RESULTS |
| `research/20260830/value-changes-1/tables.md` | T1–T5b as `analyze_values.py` renders them |
| `scrum/20260830/task_1/W6_STATUS.md` | this file |

Raw per-episode rows, the per-arm config trees and the panel/minival payloads
stay in `~/.cache/parcel-0e/w6/`, not in the repo.

### 5.2 Constraint rows

| constraint | result |
|---|---|
| product edit | **none** — `git status` in the worktree: `?? .parcel`, `?? research/20260830/` only |
| `configs/**` edit | **none** — every value is a scratch-tree override |
| safety floors | untouched: `robot.yaml` `obstacle_stop_m 0.65` / `obstacle_slow_m 1.2` asserted per work unit; nav `stop_distance_m` 0.80 identical in all five arms; the runtime reactive gate read live at 0.65 in every frozen child |
| git writes | **none** (read-only; the worktree is `--detach` at HEAD) |
| `ci_gate.py` | **not run** (executors never run it) |
| pytest | **none needed** — no product change to regress; the guard was therefore never invoked; no `-n auto`, no `--pdb` |
| `ruff check` on the three research files | **All checks passed**; **0 `noqa`** (`grep -c noqa` → 0/0/0) |
| host | 16 pool workers + 5 single-process children; load 1.80 at start; NG1 wall 751.3 s for 5 × 530 episodes |
| processes | all this card's processes exited; none left running |
| hosted spend | **$0** |
| deviation from DESIGN | one, cosmetic and recorded: DESIGN §7's host paragraph says "4 single-process arm children"; **5** ran, because DESIGN §2's arm table has five arms (`A0ref` included) and §7's count was an internal slip in the design's prose. Five arms is a superset of the pre-registered four, adds the reference column, and moves no reported row. |
| owner facts | `PARCEL_MEMORY_PATH` in card scratch; `:8765` / `/tmp/parcel_sim.sock` / `parcel_memory.sqlite3` never touched; no frozen episode set edited; the in-tree `mutation_panel.json` never written (panels go to scratch `--out` only — `AUDIT_C3.md` §4.1's lesson, and every panel row carries its own `generated_at`) |

### 5.3 What this card did NOT do

No value is enabled anywhere. No criterion is proposed, no bar declared met.
Both changes remain the owner's re-freeze decision; RESULTS §5 gives one
paragraph per value and §6 states what the measurement cannot support —
including that V2 was injected as the exact number through the other arm of
`grid_planner.py:339-341`'s `max`, where the product implementation
(`grid_planner.py:341`) would move every commissioned profile at once.
