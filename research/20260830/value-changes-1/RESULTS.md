# VALUE-CHANGES-MEASURED-1 — RESULTS

**Card:** `scrum/20260830/task_1/W6_VALUE_CHANGES_MEASURED.md` · **Executor:** Opus ·
**Verifier:** Fable · **Pre-registration:** `DESIGN.md`, FROZEN 2026-08-30 06:43 EDT
(first episode 06:47) · **Tree:** worktree at HEAD **`c96ac34`**, no owner diff ·
**RESEARCH ONLY — no product edit, no config edit, no git write, $0.**

Every number here is rendered by `analyze_values.py` into `tables.md` and
`results.json`; nothing is typed by hand. Physical motion: **NO-GO**, unchanged.
Evidence tier `desktop-sim`.

**This card presents. It does not flip.** No criterion is proposed, no bar is
declared met, and neither value is enabled anywhere in the tree.

---

## 0. The decision table

Four arms, two binary values fully crossed, plus `A0ref` — the repo's own
`configs/navigation/default.yaml`, untouched — as the plumbing reference.
`off_disc` (both values OFF, through a scratch config tree) is the baseline every
Δ is taken against.

| | **`off_disc`** shipped | **`on_disc`** V1: release door ON | **`off_full`** V2: planner 1.12 m | **`on_full`** V1+V2 |
|---|---|---|---|---|
| planner `inflation_radius_m` | 1.022296 m | 1.022296 m | **1.12 m** | **1.12 m** |
| `held_stall_release` | False | **True** | False | **True** |
| **— NAV-GEN-1, generated block (450) —** | | | | |
| strict success | 343 | 343 **(0)** | 351 **(+8)** | 350 **(+7)** |
| strict success, any legal instance | 345 | 350 (+5) | 359 (+14) | **368 (+23)** |
| settled success | 339 | 339 (0) | 346 (+7) | 345 (+6) |
| `arrived_verified` | 295 | 300 (+5) | 307 (+12) | **316 (+21)** |
| `navigation_no_progress` | 49 | **10 (−80 %)** | 32 (−35 %) | **2 (−96 %)** |
| `semantic_target_unreachable` | 62 | **95 (+33)** | 66 (+4) | 87 (+25) |
| **collisions** | **0** | **0** | **0** | **0** |
| **episodes < 0.65 m** | **1** | **1** | **4 (+3)** | **3 (+2)** |
| worst `minimum_clearance_m` | 0.6275 m | 0.6275 m | **0.5837 m** | **0.5837 m** |
| steps (total) | 128 094 | 133 170 (+4.0 %) | 120 506 (**−5.9 %**) | 123 725 (−3.4 %) |
| `status=planned`, no terminal reason | 0 | 0 | 0 | 0 |
| **— NAV-GEN-1, frozen demo block (80) —** | | | | |
| strict success | 22 | 22 (0) | 25 (+3) | 25 (+3) |
| `navigation_no_progress` | 18 | 17 (−1) | 16 (−2) | 15 (−3) |
| collisions / < 0.65 m | 0 / 1 | 0 / 1 | 0 / 1 | 0 / 1 |
| **frozen rows moved (full row)** | — | **1** | **34** | **34** |
| **— the v4 minival (25) —** | | | | |
| report digest | `021b67ab…` **= HEAD** | `021b67ab…` **= HEAD** | **`5e49ef19…` MOVED** | **`5e49ef19…` MOVED** |
| `episode_digest` (the episode SET) | `4113607b…` | `4113607b…` | `4113607b…` | `4113607b…` |
| rows moved / verdicts moved | — | **0 / 0** | **3 / 0** | **3 / 0** |
| SR · SPL · collisions | 0.20 · 0.1533 · 0 | 0.20 · 0.1533 · 0 | 0.20 · 0.1533 · 0 | 0.20 · 0.1533 · 0 |
| **— the mutation panel —** | | | | |
| `passed` / survivors | True / [] | True / [] | True / [] | True / [] |
| clean authority | {4, 1} | {4, 1} | {4, 1} | {4, 1} |
| panel identical to `A0ref` | **yes** | **yes** | no (2 clean rows) | no (2 clean rows) |
| `reactive_gate_disabled` kill channels | 2 | 2 | **3** | **3** |
| **whole-run rows moved (530)** | — | **48** | **132** | **150** |
| strict regressions / gains | — | 2 / 2 | 10 / 21 | 11 / 21 |

**The two sentences the owner is being asked to decide on:**

* **V1 (the release door) moves the frozen navigation evidence by ZERO** — the
  minival digest is `021b67ab…` and the mutation panel is identical to the
  reference arm. *But it does so because the frozen corpora cannot reach the
  door at all* (§4). On the 530-episode generated corpus it does everything C3
  said it does, and this run reproduces C3's corrected counts exactly.
* **V2 (the full 1.12 m) buys more than V1 on capability and costs more on
  every frozen artifact**: +8 strict / +12 `arrived_verified` / −5.9 % steps, and
  it moves the minival digest, 34 of 80 frozen demo rows, and 2 of the panel's 5
  clean rows — while raising the count of episodes inside the 0.65 m band from
  1 to 4.

---

## 1. What was injected, and that it is not a proxy

Both values are reachable as **harness overrides into a per-arm scratch
navigation config tree** — NG1's own idiom. The repo's `configs/**` is a
read-only input in every arm; `git status` in the worktree at close shows only
untracked research files (§7).

| | key added to the arm's scratch tree | live reading (asserted per arm, in every process, before episode 1) |
|---|---|---|
| **V1** | `default.yaml` → `progress_watchdog.held_stall_release: true` | `DirectiveNavigator.held_stall_release` = **True** |
| **V2** | `grid.yaml` → `controller.map_hard_safety_margin_m: 0.80` | `GridPlannerConfig.inflation_radius_m` = **1.12** (from 1.022296) |

**The card's fallback clause, answered.** The line that would have to be edited
to *remove the directional-cone discount* is **`grid_planner.py:341`** — the
second term of

```python
return max(self.robot_radius_m + self.effective_hard_margin_m,
           self.gate_lateral_clearance_m)      # grid_planner.py:341
```

(`gate_lateral_clearance_m` = `gate_clearance_m · sin(1.15)` = `1.12 · 0.9127639`
= `1.0222956`; equivalently `grid_planner.py:325` or `grid_navigator.py:306`).
**No config key removes that `sin θ`** — `GATE_TOWARD_HALF_ANGLE_RAD` is a module
constant at `authority.py:202`.

**But the reachable thing here is not a proxy — it is the same number.** The
first term of that same `max` is config-driven (`grid_navigator.py:145`, merged
from the YAML `controller:` block under the explicit kwargs at `registry.py:60-62`),
and `0.32 + 0.80 = 1.12` sets `inflation_radius_m` to **exactly** the value the
product edit would produce. What travels differs only in which arm of the `max`
wins, and every neighbouring quantity is measured unmoved:

| live reading | `off_disc` | `off_full` |
|---|---|---|
| `GridPlannerConfig.inflation_radius_m` | 1.022296 | **1.12** |
| `GridPlannerConfig.gate_clearance_m` | 1.12 | 1.12 (unmoved) |
| `GridPlannerConfig.gate_lateral_clearance_m` | 1.022296 | 1.022296 (unmoved) |
| `DirectiveNavigator.collision.obstacle_stop_m` (the navigator's brake) | 0.8 | **0.8 (unmoved)** |
| runtime reactive gate `obstacle_stop_m` | 0.65 | **0.65 (unmoved)** |
| `comfort_cost_enabled` | False | **False** (the comfort layer is inert in both — `comfort_cost_weight` is 0.0 on the shipped `grid.yaml`) |

Two mechanism differences are recorded rather than argued away
(`DESIGN.md` §3.2): a real edit would move **every** commissioned profile and the
DOOR-1 seed-detector comparison at `grid_planner.py:291-299`, where this arm
moves one profile; and `comfort_radius_m` follows the hard margin (0.42 → 1.12),
which is provably dead because the comfort cost is disabled in both arms.
**Neither can reach behaviour on this profile.**

## 2. The plumbing control — all three legs green

`off_disc` is a scratch config tree at the commissioned values; `A0ref` is the
repo file itself. The pre-registered pass condition was byte-identity, and
without it every arm would have been reported UNLICENSED.

| leg | result |
|---|---|
| NAV-GEN-1, 530 rows, outcome-field comparison | **530 / 530 byte-identical, 0 changed** |
| v4 minival report digest | **identical** (`021b67ab…` both) |
| mutation panel payload | **identical** (excluding `generated_at` and this driver's own path/wall fields) |

**Licensed.** Every difference reported below is the value, not the plumbing.

> **One analysis defect, found and fixed, recorded because it would have
> invalidated the card.** The first pass compared whole row dicts and read
> "530/530 rows changed" for *every* arm — including the control. The cause was
> that each row carries its own `"arm"` label. `ROW_IDENTITY_FIELDS` now excludes
> it (`analyze_values.py`), and the control is what caught it: two arms whose
> every aggregate matched could not honestly have had 0 identical rows.

## 3. Frozen-row moves, NAMED per arm

### 3.1 `on_disc` (V1 — the release door)

* **v4 minival: 0 rows moved.** Digest `021b67ab73c4e7be…` = HEAD.
* **mutation panel: identical** to `A0ref` — `passed` True, survivors `[]`,
  clean authority `{agreement: 4, authority_disagreement: 1}`, `mean_dtg`
  0.36168, all seven mutants killed through the same channels.
* **NAV-GEN-1 frozen demo block: 1 row of 80 — `frozen:lamppost:10`**, a
  `navigation_no_progress → semantic_target_unreachable` transition; **0 strict
  regressions, 0 strict gains** on the frozen block.
* Generated block, named: strict regressions **`gen:880007:crosswalk:1`**,
  **`gen:880016:crosswalk:0`**; strict gains **`gen:880009:sidewalk:1`**,
  **`gen:880014:crosswalk:0`**. Both regressions are the accidental successes C3
  §F1.3 correction (b) identified — episodes that scored `strict_success` by
  *stalling inside the goal band* rather than by arriving.

**This reproduces C3 §F1.3 exactly on a different HEAD**: 48/530 rows changed by
full-row comparison (C3: 48), 41 terminal-reason changes (C3: 41), 2 strict
regressions against 2 gains (C3: 2/2), the same four named episodes, strict
success flat, collisions 0, `<0.65 m` count unmoved, 0 rows ending
`status=planned` with no terminal reason. The stall count reads **49 → 10**
here against C3's 47 → 10.

### 3.2 `off_full` / `on_full` (V2 — the full 1.12 m demand)

**v4 minival: digest MOVED `021b67ab…` → `5e49ef19…`, 3 rows of 25, 0 verdicts.**
`episode_digest` `4113607b92c734df…` unmoved — the episode SET never moved.

| moved row | what moved | verdict |
|---|---|---|
| `nav-region_goal-A-00-1c735162` | `trace_len` 101 → 102; `time_to_goal_s` 10.000 → 10.100; final pose 2.3 mm | **unchanged — still a success** |
| `nav-region_goal-D-15-1b8b2361` | final pose (2.811, 0.750) → (2.773, 0.900), 0.156 m | **unchanged — still a failure** |
| `nav-object_relative-D-15-61f68ad6` | `trace_len` 83 → 79; `distance_to_goal_m` 4.1591 → 4.1481 | **unchanged — still `grounding_error`** |

SR 0.20, SR (frozen rule) 0.12, SPL 0.15326, collisions 0, authority histogram
`{agreement 20, authority_disagreement 5}` — **all unmoved**. The digest moves on
one extra control tick, one 0.156 m pose and 11 mm of distance. It is a real
re-freeze (the digest is the gated artifact), and it is the smallest kind.

**Mutation panel: passes, and gets STRONGER.** `passed` True, survivors `[]`,
clean authority `{4, 1}`, `mean_dtg` 0.36168 — all unmoved. Two of the five clean
rows move, both `region_goal`:

| clean row | `min_clearance_m` | final pose |
|---|---|---|
| `nav-region_goal-A-00-1c735162` | 0.8879 → 0.8838 | 2.3 mm |
| `nav-region_goal-D-15-1b8b2361` | 1.2804 → 1.2296 | 0.156 m |

and the panel's most important mutant, **`reactive_gate_disabled`, goes from 2
kill channels to 3** — `final_poses_within_tolerance` now reddens under it as
well as `success_set_identical` and `failure_histogram_identical`. Against
`AUDIT_C3.md` §4.1's standing worry about a *thinning* of that mutant's evidence,
V2 moves it the other way.

**NAV-GEN-1 frozen demo block: 34 rows of 80 move, 8 terminal reasons.**
Named strict regressions: **`frozen:bench:7`, `frozen:planter:10`,
`frozen:sidewalk:6`, `frozen:sidewalk:10`**. Named strict gains:
**`frozen:crosswalk:3`, `frozen:crosswalk:4`, `frozen:crosswalk:7`,
`frozen:crosswalk:10`, `frozen:crosswalk:15`, `frozen:lamppost:6`,
`frozen:lamppost:15`** — net **+3** (22 → 25). Frozen-block reason transitions:
`arrived_verified → semantic_target_unreachable` ×2,
`navigation_no_progress → arrived_verified` ×2,
`semantic_arrival_verification_failed → semantic_target_unreachable` ×2,
`navigation_no_progress → semantic_target_unreachable` ×1,
`arrived → navigation_no_progress` ×1.

**Generated block, 10 strict regressions named:** `gen:880000:bench:0`,
`gen:880001:sidewalk:2`, `gen:880005:lamppost:1`, `gen:880007:sidewalk:1`,
`gen:880014:sidewalk:1`, `gen:880023:crosswalk:0` (+ the four frozen rows above).
**21 gains**, including `gen:880015:lamppost:1` and `gen:880025:lamppost:1` —
C3 §1.3's worked class-B2 examples, the owner-yield stalls.

### 3.3 The one safety-relevant cost of V2, stated plainly

Episodes whose `minimum_clearance_m` falls inside the 0.65 m reactive stop band
rise **1 → 4** on the generated block (3 under V1+V2), and the worst single
reading falls **0.6275 → 0.5837 m**. Collisions stay **0** in every arm, and the
runtime gate's own 0.65 m ring is untouched.

| episode | `off_disc` | `off_full` | what it is |
|---|---|---|---|
| `gen:880007:bench:1` | 0.6275 | 0.6275 | the baseline's own sub-band episode; unmoved |
| `gen:880003:bench:0` | 0.6762 | **0.6112** | `semantic_target_unreachable` → **`arrived_verified`** — an episode that used to give up now arrives |
| `gen:880011:bench:1` | 0.6735 | **0.5837** | `arrived_verified` both arms; the closest approach tightened |
| `gen:880018:bench:1` | 0.7141 | **0.6470** | `navigation_no_progress` both arms; the hold sits closer |

**All four are `bench` episodes** — C3 class B1 exactly, where
`_control_observation` (`pipeline.py:2220`) deliberately drops the relational
target's own LiDAR returns so the point controller can reach its stand-off pose,
and the runtime's independent brake still sees the unmodified view. So a large
part of this row is "V2 turns give-ups into bench arrivals, and standing at a
bench means standing inside 0.65 m of the bench". It is **not** all of it:
`gen:880011` and `gen:880018` keep their outcome and simply end up closer, and
`0.5837 m` is a real number that a re-freeze would have to accept.

## 4. The finding that changes how the V1 result should be read

`on_disc`'s "the frozen evidence moves by zero" is true, and its mechanism is
**not** that the door fired harmlessly. **The door is never consulted at all.**

`door_reach.py` wraps `stall_attribution.held_release_due` and runs the full v4
minival with the flag ON:

| arm | corpus | `held_release_due` calls | releases |
|---|---|---|---|
| `on_disc` | v4 minival, 25 episodes, `max_steps` 200 | **0** | **0** |
| `on_full` | v4 minival, 25 episodes, `max_steps` 200 | **0** | **0** |

The reason is structural: the minival's step budget is **200** and
`progress_watchdog.timeout_steps` is **200**, so the watchdog's window cannot
expire inside an episode. No minival episode ends `navigation_no_progress` (the
25 terminals are 6 `semantic_target_not_found`, 6 `semantic_target_unreachable`,
5 `spatial_step_limit`, 3 `at_follow_distance`, 2 `arrived_verified`,
2 `tracking_owner`, 1 `navigation_step_limit_inside_goal`). The mutation panel's
five episodes are a **subset** of those 25 (verified), so the same zero covers
the panel.

**So `AUDIT_C3.md` §4.1's "C3 flag ON alone → frozen panel is NOT MEASURED" is
now measured, and the answer is: it cannot move it.** That is a genuine
green — the E3 concern that the door might move a hard-safety artifact is
disposed of — but it is a statement about the corpus, not a safety argument for
the door. The frozen corpora are **structurally blind** to this flag.

## 5. Recommendation, one paragraph per value

**V1 — the release door (`progress_watchdog.held_stall_release`).** The evidence
now says the thing wave A could not check: enabling it on the shipped profile
moves **no frozen artifact at all** — the v4 minival digest stays `021b67ab…`,
the mutation panel is byte-identical to the reference arm including all seven
mutants' kill channels, and the frozen demo block moves a single row with no
strict change. On the 530-episode generated corpus it converts a silent 20-second
stall into an honest terminal in 39 of 49 cases, buys +5 `arrived_verified`, and
costs 2 accidental "successes" that were robots stalled inside a goal band,
against 2 genuine gains, at 0 collisions and no change in sub-0.65 m exposure, for
+4.0 % steps. Its price is the label churn C3 already reported and did not hide:
`semantic_target_unreachable` 62 → 95. **The honest caveat is that the frozen
corpora cannot exercise the door** (§4), so "no frozen move" is cheap evidence
rather than strong evidence, and the case for the door rests entirely on the
generated corpus. If the owner wants stronger evidence before flipping it, the
cheapest instrument is a minival arm at `max_steps` > 200, not another frozen run.

**V2 — the planner demanding the full 1.12 m.** C3 §5.1 predicted this would kill
the stall class at its source and "not shift a single episode into
`semantic_target_unreachable`". **Half right.** It does attack the source — stalls
49 → 32 alone and 49 → **2** when combined with the door, `arrived_verified`
295 → 307, strict success 343 → 351, and the robot gets there in **5.9 % fewer
steps** rather than the door's 4.0 % more, which is the signature of preventing a
deadlock instead of recovering from one. But the prediction that no episode moves
into `semantic_target_unreachable` is **wrong**: that count rises 62 → 66 on the
generated block and 38 → 43 on the frozen one, because a 1.12 m inflation closes
corridors the 1.0223 m planner would route down. And the re-freeze bill is real
and much larger than V1's: the v4 minival digest **moves** (3 rows, no verdict
change, on one control tick and 0.156 m of pose), 34 of 80 frozen demo rows move
with 4 named strict regressions against 7 named gains, 2 of the panel's 5 clean
rows move, and sub-0.65 m exposure goes 1 → 4 with a worst reading of 0.5837 m.
The panel itself *passes and gets stronger* (`reactive_gate_disabled` killed
through 3 channels instead of 2). **The two values are complementary, not
alternatives** — `on_full` is the only arm that nearly eliminates the stall class
(2 of 450) and it has the best any-instance capability (+23 strict any-instance,
+21 `arrived_verified`) — but it is also the arm with the largest frozen bill
(150/530 rows, both frozen artifacts moved). If the owner takes V2, it should be
taken as a v5 episode-set-independent **report** re-freeze with the four named
frozen strict regressions and the 0.5837 m clearance row written into the
provenance, and the product implementation should be the `grid_planner.py:341`
edit (which moves every commissioned profile), not this card's single-profile
injection.

## 6. What this does not prove

* **Nothing physical.** `desktop-sim`; no hardware exists. Physical motion NO-GO.
* V2 was injected as the **number**, exactly, through the other arm of the same
  `max` (§1). A product edit would move every commissioned profile at once and
  the DOOR-1 seed detector; this arm moved one profile.
* The minival is 25 episodes and the panel 5. "The digest did not move" is a
  statement about those episodes — and for V1, §4 shows it is a statement about
  their step budget.
* The generated block is 30 scenes from one generator seed family
  (`manifest_sha256 b698e059…`, identical to NG1's). NG1's own `RESULTS.md` is the
  authority on what it represents.
* `on_full` is measured but not explained: this card reports that V1+V2 is more
  than the sum of its parts on stalls (49 → 2 versus 10 and 32 alone), not why.
* No claim is made that any arm should ship. Both remain owner re-freeze
  decisions.

## 7. Reproduce

```bash
cd <worktree at c96ac34>
export PYTHONPATH=$PWD/src:$PWD MUJOCO_GL=egl W6_REPO=$PWD; unset TMPDIR
H=research/20260830/value-changes-1

.parcel/bin/python $H/values_harness.py --stage facts        # the live per-arm readings
.parcel/bin/python $H/values_harness.py --stage prepare      # 30 scenes, manifest b698e059...
.parcel/bin/python $H/values_harness.py --stage ng1 --workers 16          # 175 units, 751 s
for a in A0ref off_disc on_disc off_full on_full; do
  .parcel/bin/python $H/values_harness.py --stage frozen --arm $a         # minival + panel
done
.parcel/bin/python $H/door_reach.py --arm on_disc            # sec. 4
.parcel/bin/python $H/analyze_values.py --out $H             # results.json + tables.md
```

Host: `06:38 up 7 days`, load 1.80 at start, 192 cores; NG1 pool 16 workers
(751.3 s wall for 5 × 530 episodes), five frozen children beside it (minival
~21 s, panel ~41 s each). `TMPDIR` unset throughout; `PARCEL_MEMORY_PATH` in this
card's scratch; the owner's `:8765` / `/tmp/parcel_sim.sock` /
`parcel_memory.sqlite3` never touched. Raw per-episode rows and the per-arm
config trees live in `~/.cache/parcel-0e/w6/`, not in the repo. `git` read-only;
no hosted call; **$0**.
