# C3 · STALL-CLASS-1 — executor status (Opus)

**Card:** `C3_STALL_CLASS.md` (+ **Amendment A1**, parcel-fb's second lens, binding) ·
**Verifier:** Fable · **Second lens:** parcel-fb · **Wave:** A

Written incrementally. §0 pre-flight → §1 attribution (gates the fix) → §2 fix →
§3 acceptance rows → §4 close → **§Follow-up F1**.

> **READ F1 FIRST.** The verifier found (isolated worktree, no owner diff) that
> the release door moves a frozen hard-safety row. It is now behind
> **`progress_watchdog.held_stall_release`, default OFF and OFF on the shipped
> profile**; flag-OFF the watchdog is byte-identical to HEAD. §2.2's shipped
> behaviour and §3's GREEN arm are superseded by §F1.2 (off-path proof) and
> §F1.3 (the flag-ON measurement). §1's attribution and §5's write-up stand.

---

## 0. Pre-flight

| item | value |
|---|---|
| host at start | `21:40 up 7 days`, load 4.75 / 4.25 / 4.97, 192 cores, 246 GB (5 peers share it) |
| venv | `.parcel/bin/python`, `TMPDIR` unset on every command |
| instrument | NAV-GEN-1 `research/20260829/nav-gen-attribution-1`, arm **A0** (commissioned, repo config path, untouched) |
| card scratch | `/home/jaewoo-jang/.cache/parcel-0e/c3/` (`ng1/` pre-C1, `ng1_postc1/` post-C1) |
| product state measured | **§1 attribution: PRE-C1** (`git diff --stat pipeline.py` empty at 21:41). C1 landed at ~22:0x (`poi_admission.py` + the `parse` hook); the **RED/GREEN acceptance rows in §3 are re-measured POST-C1** and labelled. C1 touches only the POI/crosswalk arm, which is disjoint from the 26 non-POI stalls this card owns. |
| hosted spend | **$0** (no hosted call on this card) |
| `noqa` added | **0** (`grep -c noqa src/parcel_robot/navigation/stall_attribution.py` → 0) |
| floors touched | **none** — `obstacle_stop_m`, `stop_distance_m`, `map_safety_margin_m`, `person_stop_m`, `apply_reactive_safety`, `finalize_command`, `core/hard_stop.py`, the A3 latch, the A6 stop path all unmodified |

**Amendment A1, recorded.** Candidate (b) "the watchdog counting brake-held ticks
as no-progress" is **NOT** the fix taken. Nothing in this card exempts a tick
from the progress watchdog: the watchdog's count, its 200-tick timeout, its
replan budget and its `navigation_no_progress` terminal all stay exactly as they
are. What changes is *which door an already-fired watchdog walks through* — an
existing, bounded, terminal-reasoned release. A1's added GREEN row (no episode
ends `status=planned` with no terminal reason) is reported in §3.

### RED (reproduction, pre-C1) — the card's row, verbatim

> RED: NAV-GEN-1 `--arms A0` reproduces 68 `navigation_no_progress` / 44
> `semantic_target_unreachable`

```
env -u TMPDIR OPENBLAS_NUM_THREADS=32 NG1_SCRATCH=~/.cache/parcel-0e/c3/ng1 \
  .parcel/bin/python research/20260829/nav-gen-attribution-1/run.py --stage prepare
env -u TMPDIR OPENBLAS_NUM_THREADS=32 NG1_SCRATCH=~/.cache/parcel-0e/c3/ng1 \
  .parcel/bin/python research/20260829/nav-gen-attribution-1/run.py \
  --arms A0 --seed 20260829 --workers 16
```

530 episodes, 315 strict successes, wall 323 s. Generated block, 450 episodes,
157 strict failures:

| reason | n | matches VERDICT §5.1 |
|---|---|---|
| `navigation_no_progress` | **68** (42 wrong-instance / **26 non-POI**) | yes |
| `semantic_target_unreachable` | **44** (49 episodes end with it) | yes |
| `arrived` (false arrivals) | 42 | yes |
| `arrived_verified` | 2 | yes |
| `semantic_target_ambiguous` | 1 | yes |

Collisions on the generated block: **0**. Episodes with
`minimum_clearance_m < 0.65`: **1**. RED reproduced exactly.

---

## 1. Attribution — the histogram (written BEFORE any product line change)

**Method.** The harness exposes no per-step hook, so the card's alternative was
taken: a scratch copy of the driver
(`~/.cache/parcel-0e/c3/instrument.py`) that reproduces
`HeadlessCityQualityHarness._run_navigation` line-for-line and adds a probe.
`simulation/headless_city.py` was **not edited** (C2 owns it) and no research
file was written. The copy is byte-faithful: over the 81 re-run episodes,
**0/81 reason mismatches and 0/81 step-count mismatches** against `rows_A0.json`.

Per tick it records: `plan.status`, route waypoint count, route length, the next
waypoint, `steps_without_progress`, `steps_gate_blocked`, `body_is_still`,
`_best_goal_distance_m`, `replan_count`, `candidate_id`, `unreachable_candidates`,
the navigator's requested `vx` **before** its own brake, the brake's verdict and
the range the brake was handed, the runtime gate's verdict, the raw
`nearest_obstacle_m` + bearing + id, the full directional LiDAR return list,
`lidar` minimum, owner range, and the body pose.

Episodes instrumented: the **26 non-POI** `navigation_no_progress`, all **49**
`semantic_target_unreachable`, and **6/42** POI stalls as a control.

### 1.1 The 26 non-POI `navigation_no_progress` — one shape, three authorities

| class | n | share | example episode |
|---|---|---|---|
| **A.** the navigator's **own** brake holds the body AT the ring (`projected_speed_cap`) | **17** | 0.65 | `gen:880000:lamppost:1` |
| **B1.** the runtime's final gate stops on the **target's own** LiDAR returns, which the navigator's view excludes | **5** | 0.19 | `gen:880001:planter:0` |
| **B2.** the runtime's final gate **yields to the OWNER**; the watchdog's person clause cannot see the owner | **4** | 0.15 | `gen:880015:lamppost:1` |

**All 26 share one shape**: `plan.status == "planned"` on 199 of the 200 ticks of
the terminal watchdog window, body travel 0.000–0.020 m over that window, and
`replan_count == 2` (the full ladder spent re-deriving the *byte-identical*
commitment to the *same* instance). `steps_gate_blocked` — card A2's release
witness — is **0** through the entire hold in 25 of the 26.

### 1.2 The card's named quantities, per class (medians, terminal 200-tick window)

| class | planned-route ticks | route length (m) | dist to next waypoint (m) | min LiDAR clearance (m) | vs brake ring **0.80 m** (body surface) | vs planner inflation **1.0223 m** (centre) | brake zeroed the command with a route planned | replans | body travel (m) |
|---|---|---|---|---|---|---|---|---|---|
| A | 199 / 200 | 2.735 | 1.362 | 1.443 | **held at exactly 0.8000** | 1.12 centre — **outside** the 1.0223 inflation, so the route is legal | 199 | 2 | **0.000** |
| B1 | 199 / 200 | 2.065 | 1.661 | 1.348 | 0.714 (raw) — **inside** the ring | 1.034 centre | 194 | 2 | 0.020 |
| B2 | 199 / 200 | 5.602 | 3.823 | 1.534 | 2.913 — obstacles irrelevant | 3.233 centre | 197 | 2 | 0.008 |

### 1.3 One worked example per class

**A — `gen:880000:lamppost:1`** (17/26). Body at `(5.032, 2.559)`, yaw 2.352 rad,
route `planned`, 3 waypoints, 5.078 m, heading error `-0.0°`, goal 4.819 m away.
Nearest return `planter_2` at **0.8000 m**, bearing **−1.056 rad (60.5° off the
travel direction)**. The shipped `safety.predictive_mode: projected_speed_cap`
computes `allowed_closing_speed = (0.8000 − 0.80)/0.12 = 0`, so
`cap_scale = 0` and translation is zeroed with the verdict
**`obstacle_projected_speed_cap`** — never `obstacle_stop`, because the range
never crosses the ring. Held at 0.8000 m for 199/200 ticks, `out_vx = 0.0` on
201/201 ticks, displacement **0.00 m**.
*The gate is right and stays untouched.* The defect is that card A2's release
authority (`_gate_blocked_route_recovery`, `GATE_BLOCKED_ROUTE_STEPS = 60`)
witnesses `cnote == "obstacle_stop"` only — one spelling of a brake that ships
in a mode which cannot produce it — so `_steps_gate_blocked` stays **0** for the
entire hold and the mission spends 3 × 200 ticks re-committing to `lamp_post_1`.

**B1 — `gen:880018:bench:1`** (5/26). Target `bench_1`. Raw nearest return
`bench_seat` at **0.7141 m**; the range the navigator's brake is actually handed
is **1.6002 m**, because `_control_observation` (pipeline.py:2220) deliberately
drops the relational target's own returns so the point controller can reach its
stand-off pose — its docstring says plainly that "the runtime's independent
final brake still sees the unmodified sensor view". So the navigator reads
`clear`, commands cruise `vx = 0.85` for 199 ticks, and `apply_reactive_safety`
returns `stopped` on 194 of them (0.7141 m ≤ 0.65 + 0.85·0.12 = 0.752 m
predictive stop). **The navigator has no channel through which it can learn its
command was refused.** Displacement 0.02 m; watchdog fails the mission.

**B2 — `gen:880025:lamppost:1`** (4/26). Nearest obstacle 3.47 m — clearance is
irrelevant. The **owner** is 1.774 m away; `owner_clearance = 1.774 − 0.55 =
1.224 m` against `predictive_person_stop = 1.2 + 0.85·0.12 = 1.302 m`, so the
runtime gate stops for the owner on 197/200 ticks. The watchdog's own person
clause reads `observation.nearest_person_m` (the owner is not on that channel)
against `self.collision.person_stop_m`, so 20 s of *correct social yielding* is
scored `navigation_no_progress`. Verified on all four: owner clearance
1.065–1.232 m, predictive stop 1.302 m.

**Control — 6/42 POI stalls** (`gen:880000:crosswalk:0`, …): all show the same
`clear`/`stopped` disagreement, all with `owner_d ≈ 1.82–1.85 m` — but they are
C1's defect (commitment to `crosswalk_a`, `semantic_goal is None`, therefore no
release door at all). **Untouched by this card**, by construction: every path
changed here is guarded on `mission.semantic_goal is not None`.

### 1.4 The 49 `semantic_target_unreachable` episodes (44 strict failures)

| class | n | share | example episode |
|---|---|---|---|
| **U1.** A* proved `no_path`/`goal_blocked` to the committed approach pose; `_unroutable_goal_recovery` released at 60 ticks; the rescan found no alternative | **29** | 0.59 | `gen:880000:bench:1` |
| **U2.** the A2 gate-blocked release **did** fire (the `obstacle_stop` spelling was reached) and the ladder was then spent | **14** | 0.29 | `gen:880002:bench:1` |
| **U3.** approach solver returned no pose / other release door | **6** | 0.12 | `gen:880003:bench:0` |

**This class is the release ladder working, not failing.** VERDICT §7.2b's
"0 of 49 goals below the planner's demand" is confirmed and explained: the
blocked thing is never the goal *band* (min best clearance 1.00 m vs a 0.7023 m
demand) — it is the *approach pose* the solver committed to, or the corridor to
it, and the ladder then honestly reports that it could not get there. `U2` is
direct evidence that A2's release door works **when its witness fires**, which
is exactly what class A above is missing.

### 1.5 Reading — what the dominant class actually is

The card's three candidate causes, adjudicated against the measurement:

* **(a) brake ring < planner inflation at corridor mouths** — *not* the general
  case, but the residual gap is real and now has a number. A2 converts the
  0.80 m ring into `1.12 m` centre-to-surface and then applies the directional
  cone discount, giving inflation `1.12·sin θ = 1.0223 m`. That discount is
  exact for a straight corridor traversed along its centreline, and *loose* for
  an obstacle in the closing cone at a bearing off the corridor axis — which is
  class A exactly (60.5° off travel, 0.8000 m). The planner considers a cell
  legal at 1.0223 m centre; the gate refuses translation from it. **The residual
  disagreement is 1.12 − 1.0223 = 0.0977 m of inflation.** Closing it is a
  value change that moves frozen routes → **written up for the owner in §5, not
  taken** (card rule: "if the honest fix is a value change, stop and write it up").
* **(b) the watchdog counting brake-held ticks as no-progress** — true as a
  description, **rejected as the fix** under amendment A1. Exempting those ticks
  would trade a loud `navigation_no_progress` for exactly the R3 silent stall
  NAV-ACCEPT found alive.
* **(c) waypoint reached-tolerance vs inflation** — **refuted**: the median
  distance to the next waypoint at the hold is 1.36–3.82 m, an order of
  magnitude above any reached tolerance, and the route is `planned` with 2–3
  waypoints throughout.

**The dominant class is A, and its cause is a witness, not a value:** the one
release authority built for "my own gate will not let me execute this plan"
(card A2) is wired to a single brake-note spelling that the shipped brake mode
never emits. The same blindness explains B1 and B2 (a refusal the navigator is
never told about at all). All three are visible from two facts the navigator
already maintains — *the planner still has a route* and *the body did not
travel* — with no gate spelling, no policy value and no floor involved.

---

## 2. The fix

**Shared-file check, before every `pipeline.py` edit** (card's rule):
`git diff --stat src/parcel_robot/navigation/pipeline.py` — empty at 21:41 (C1
not yet landed), `7 insertions(+), 10 deletions(-)` at 22:0x (C1's
`poi_admission` hook, lines ~1139-1163). My edit is confined to the watchdog
region and one import line; **no line of C1's region is touched and nothing is
reformatted**.

### 2.1 New leaf: `src/parcel_robot/navigation/stall_attribution.py` (178 lines)

Pure functions and constants; no state, no import from `pipeline`, no safety
value (`tests/test_stall_attribution.py::test_the_leaf_holds_no_safety_value`
greps the module body for `obstacle_stop_m` / `stop_distance_m` / `0.65` /
`0.8` / `1.02` and fails if any appears). It owns:

| symbol | what it is |
|---|---|
| `PROGRESS_HYSTERESIS_M = 0.025` | the watchdog's own dead band, moved out of the method verbatim |
| `ROUTED_STATUSES = {"planned", "partial"}` | "the planner still has a route", checked against `grid_planner.RouteStatus` by a test |
| `goal_progress_made` / `person_yield_holds` | the two pre-C3 clauses, unchanged, with their reasoning |
| `classify_stall` | `HELD_WITH_ROUTE` / `DRIFTING` / `NO_ROUTE`, from **route status + the odometer only** |
| `record_stall` | writes `stall_class` + `held_stalls` into the mission record; returns the held count |
| `HELD_RELEASE_AFTER = 2` | the grace re-ground (§2.3) |
| `HELD_RELEASE_NOTE` | `semantic_replan_after_held_route` — its own spelling, separable in any trace |

### 2.2 `pipeline.py`: the watchdog region only

**Line count: 7200 → 7198 (net −2).** (HEAD is 7203; C1 took it to 7200; C3
takes it to 7198.) `ruff check`: clean, **0 `noqa` added**; `ruff format
--check` fails on `pipeline.py` **exactly as it does at HEAD** — pre-existing,
not introduced (`ruff format --diff` shows nothing in the watchdog region).

The whole behavioural change is one branch:

```python
route_status = getattr(self._navigator, "last_route_status", None)
held = stall.record_stall(self.mission.metadata, route_status, self._body_is_still)
replans = int(self.mission.metadata.get("replan_count", 0))
if self.mission.semantic_goal is not None and replans < self.max_semantic_replans:
    if held >= stall.HELD_RELEASE_AFTER:
        return self._release_unreachable_candidate(..., note=stall.HELD_RELEASE_NOTE)
    return self._begin_semantic_replan(replans, note="semantic_replan_after_no_progress")
```

**What did NOT change, deliberately:** the watchdog's count, its dead band, its
`progress_timeout_steps`, its person-yield clause, its replan budget, its
`status=failed` / `resolution_state=stalled` / `navigation_no_progress`
terminal, and every safety floor. **No tick is exempted from the watchdog** —
amendment A1's hazard is not created, because nothing here can make a stall
quieter. What changes is that a *repeated* held stall walks through the release
door card A2 already built for exactly this proof (`_release_unreachable_candidate`,
the single release authority shared by A\*, the obstacle gate and the approach
solver), so the released instance is **remembered** and the rescan cannot
re-derive the byte-identical commitment a third time.

Off-path is byte-identical: a `StubNavigator` (no `last_route_status`) resolves
to `NO_ROUTE`, a POI mission has `semantic_goal is None`, and a spent ladder
still fails loudly — all three keep the pre-C3 path exactly.

### 2.3 The measured refinement: `HELD_RELEASE_AFTER = 2`

Releasing on the **first** held stall was built and measured first. It zeroed
the stall class (43 → 0) but **cost four episodes that reach their goal today**
(`gen:880011:bench:1`, `gen:880016:crosswalk:0`, `gen:880024:bench:0`,
`gen:880025:crosswalk:2`: `arrived_verified` → `semantic_target_unreachable`) —
a mission that merely paused on the way to a reachable target had that target
struck off permanently. The first held stall therefore keeps the ordinary
re-ground (the world may simply have changed under a stale plan); only a held
stall that SURVIVES a re-ground is proof about the *commitment* rather than
about the tick. Same discipline as `UNROUTABLE_GOAL_STEPS`' 6-second wait for a
transient blockage. Both variants are in the record: `ng1_green/` (release on
the first) and `ng1_green2/` (shipped).

### 2.4 Research schema hygiene — `nav-gen-attribution-1/analyze.py`

`live_planner_facts()` + one line at the `arm_config_facts` merge. A pre-A2 row
(A0–A4: `planner_inflation_radius_m 0.42`, `map_gate_clearance_m: null`) is
given the LIVE fields, recomputed from the two numbers the row already records
through the same product functions `run.py` uses — no number is re-typed — with
the original keys kept beside them under a `schema_note`. B rows are returned
unchanged.

Verified in a mirrored scratch copy at the same path depth
(`~/.cache/parcel-0e/c3/mirror/research/20260829/nav-gen-attribution-1/`,
`NG1_SCRATCH=~/.cache/parcel-0e/ng1`, the original raw rows):

* the **only** top-level key of `results.json` that changes is `arm_config_facts`;
* `tables.md` is **byte-identical**;
* `A0` now reads `LIVE_planner_inflation_radius_m: 1.022296` (RESULTS §7.2b's
  number), `A4` the same, `B1` unchanged at `0.885381`.

**Concurrency note:** C7 also owns `analyze.py` (board row C7) and landed a
large addition to it while this card was in flight. The two changes are
disjoint — mine is `live_planner_facts()` plus the one `arm_config_facts` line —
and both are present and `ruff`-clean in the current file; the mirror proof
above was taken from the copy before C7's edit, so it isolates C3's effect.

**Not applied to the tracked `results.json`**: it is not in this card's OWNS
(only `analyze.py` is), and regenerating it also rewrites `tables.md`. One
command for the integrator/verifier, output proven above:

```
env -u TMPDIR .parcel/bin/python research/20260829/nav-gen-attribution-1/analyze.py
```

---

## 3. Acceptance rows

**Which state was measured.** C1 landed while this card was in flight, so the
acceptance pair is measured on the tree C3 actually lands in:

* **RED (post-C1)** — `~/.cache/parcel-0e/c3/ng1_postc1/`, tree = HEAD + C1 +
  the owner's uncommitted diff, **without** C3.
* **GREEN** — `~/.cache/parcel-0e/c3/ng1_green2/`, the same tree **with** C3.

Same command for both (only `NG1_SCRATCH` differs):

```
env -u TMPDIR OPENBLAS_NUM_THREADS=32 NG1_SCRATCH=<scratch> .parcel/bin/python \
  research/20260829/nav-gen-attribution-1/run.py --stage prepare
env -u TMPDIR OPENBLAS_NUM_THREADS=32 NG1_SCRATCH=<scratch> .parcel/bin/python \
  research/20260829/nav-gen-attribution-1/run.py --arms A0 --seed 20260829 --workers 16
```

530 episodes each (450 generated + 80 frozen), wall 332 s / 331 s.

### 3.1 The card's bars, quoted, with the numbers beside them

> **RED: NAV-GEN-1 `--arms A0` reproduces 68 `navigation_no_progress` / 44
> `semantic_target_unreachable` (or their post-C1 counts if C1 has landed —
> record which).**

**MET, both states recorded.** Pre-C1: **68 / 44**, exactly (§0). Post-C1:
**52 `navigation_no_progress` (43 of them non-POI) / 54 `semantic_target_unreachable`**
strict failures. C1 removes 42 wrong-instance crosswalk stalls and puts 17
now-correctly-grounded crosswalk episodes into the semantic ladder, which is why
the **non-POI** count rises 26 → 43 while the total falls.

> **GREEN: non-POI stall count halves (≤ 13 of the 26, or ≤ half of the post-C1
> count) at 0 collisions and no increase in episodes below the 0.65 m stop band
> (A0 has 1); every other reason count unchanged or improved; frozen
> NAV_INSTRUCT digest unchanged.**

| # | bar | RED (post-C1) | GREEN | verdict |
|---|---|---|---|---|
| 1 | non-POI `navigation_no_progress` ≤ half of 43, i.e. **≤ 21** | **43** | **10** | **MET** (−77 %) |
| 2 | collisions **0** | 0 gen / 0 all | 0 gen / 0 all | **MET** |
| 3 | no increase in episodes below the 0.65 m stop band | 1 gen / 2 all | 1 gen / 2 all | **MET** (unchanged) |
| 4 | every other reason count unchanged or improved | see 3.2 | see 3.2 | **MISSED on one reason** — reported in full |
| 5 | frozen NAV_INSTRUCT digest unchanged | — | — | **MET for C3** (§3.4) |
| A1 | no episode ends `status=planned` with no terminal reason (all 530) | 0 | **0** | **MET** |

### 3.2 Row 4 in full — the whole reason histogram, generated block, all 450

| reason | RED (post-C1) | GREEN | Δ | reading |
|---|---|---|---|---|
| `arrived_verified` | 288 | **293** | **+5** | improved |
| `navigation_no_progress` | 54 | **19** | **−35** | improved (the card's class) |
| `semantic_target_unreachable` | 59 | **88** | **+29** | **the miss** |
| `semantic_arrival_verification_failed` | 42 | 43 | +1 | one stall became "reached it, verification failed" |
| `arrived` (false arrivals) | 6 | 6 | 0 | unchanged |
| `semantic_target_ambiguous` | 1 | 1 | 0 | unchanged |

**The miss, stated plainly and not worked around.** 28 of the 43 held stalls
become `semantic_target_unreachable`: the mission releases the instance it has
proved it cannot execute a plan for, rescans, finds no alternative it has not
already excluded, and **says so** instead of standing still. It is a real change
of terminal reason and row 4 is missed on it. What it is *not* is a capability
loss — every capability row is flat or better:

| capability row (generated, 450) | RED | GREEN | Δ |
|---|---|---|---|
| strict success (MA-1's single-instance oracle) | 335 | **335** | **0** |
| strict success, any legal instance | 337 | **342** | **+5** |
| band entry | 347 | **349** | **+2** |
| terminal `status = arrived` (both blocks, 530) | 315 | **320** | **+5** |
| false arrivals | 6 | 6 | 0 |
| episodes changed at all | — | **44 / 530** | 486 rows byte-identical |
| strict regressions / gains | — | **2 / 2** | net 0 |

The two strict regressions are `gen:880007:crosswalk:1` and
`gen:880016:crosswalk:0` — both were *accidental* successes in RED, scored
`strict_success` because the robot **stalled inside the goal band** (`dtg 0.0`
with reason `navigation_no_progress`) rather than because it arrived. Two other
episodes (`gen:880009:sidewalk:1`, `gen:880014:crosswalk:0`) become genuine
successes, so the net is zero.

**Cost, recorded:** the generated block spends **+4 483 steps (+3.6 %)** and the
43-episode stall set's median episode grows 698 → 837 steps, because a released
mission now spends its remaining budget *trying an alternative* instead of
standing still. Zero of that budget is spent moving toward an obstacle.

Frozen block (80 episodes): **1** episode changes
(`navigation_no_progress` → `semantic_target_unreachable`); stalls 18 → 17,
unreachable 38 → 39; 0 strict, any-instance or band-entry regressions.

### 3.3 Where the residual 10 stalls are

All 10 are `planter` episodes that reach the release door with the ladder
already spent (`replan_count == 2` from an earlier unroutable release), so they
fail loudly on the pre-C3 path — which is the correct behaviour and the reason
row A1 stays at 0.

### 3.4 Row 5 — frozen NAV_INSTRUCT digest, attributed

The minival was run three ways and the report digest computed with the recipe
`tests/test_nav_instruct_digest_recipe.py` pins (five-field exclusion,
`aggregate.scene` dropped, compact separators):

```
.parcel/bin/python -m evals.nav_instruct.run_nav_instruct_v1 \
  --minival --mode baseline --episode-version v4 --no-ledger --out <scratch>
```

| tree | digest | episodes differing |
|---|---|---|
| committed frozen row (`…v4-20260811T070536Z`) | `c172da375ff23987…` | — |
| **HEAD + C1 + owner diff, WITHOUT C3** (shadow package) | `847ed260124b3975…` | 15 vs frozen |
| **HEAD + C1 + owner diff, WITH C3** | `847ed260124b3975…` | **0 vs the row above** |

**C3 moves the NAV_INSTRUCT digest by nothing: the two runs are byte-identical,
all 25 episodes.** The move away from the committed `c172da37…` is entirely
pre-existing in the tree C3 landed into (`grid_planner.py` is in the owner's
uncommitted diff and moves planner routes by construction; C1's POI admission
shifts 3 failures `planning_error` → `grounding_error`). **Flagged for the
integrator — it is not C3's, and it is red before C3 exists.** The
"without C3" arm was produced with a shadow `parcel_robot` package under
`~/.cache/parcel-0e/c3/preC3root/src` (the watchdog region restored verbatim,
the leaf deleted), never by editing the shared tree.

`episode_digest` is unchanged (`4113607b92c734df…`) in every arm — the episode
set itself never moved.

### 3.5 Regression subsets (all through the guard, `TMPDIR` unset, no `-n auto`, no `ci_gate.py`)

```
env -u TMPDIR ~/.cache/parcel-guard/pytest_guard.sh --label C3 .parcel/bin/python -m pytest <files> -q
```

| subset | result |
|---|---|
| `tests/test_stall_attribution.py` (new) | **22 passed** |
| `tests/test_navcore_probe.py` `tests/test_a2_navglue.py` `tests/test_a3_discontinuity_latch.py` `tests/test_door1_doorway.py` `tests/test_grid_navigator.py` `tests/test_grid_planner.py` (+ the new file) | **144 passed** |
| `tests/test_unroutable_goal_release.py` `tests/test_semantic_navigation_regressions.py` `tests/test_yield_policy.py` `tests/test_rm2_route_memory_product_path.py` `tests/test_pose_consumers.py` | **168 passed** |
| the four BARN v9 files + `tests/test_voice_nav_e2e.py` (12-min batch) | 221 passed, 1 xfailed, **1 failed**: `test_voice_nav_e2e.py::test_sit_next_to_the_lamppost_settles_beside_it_in_a_sit` |

The one failure **passes on its own** (`1 passed in 62.89 s`, same tree, same
command). Re-run of the whole `test_voice_nav_e2e.py` file is recorded in §4.
`ruff check` clean on all four touched files; **0 `noqa` added**.

### 3.6 The one failing test, attributed — **NOT C3's**

`tests/test_voice_nav_e2e.py::test_sit_next_to_the_lamppost_settles_beside_it_in_a_sit`
is order-dependent inside its own file (it passes alone, fails when the file
runs; the `live` fixture is function-scoped and `pytest-randomly` is not
installed, so the order is deterministic). Run the same file both ways:

| tree | command | result |
|---|---|---|
| **WITH C3** | `pytest tests/test_voice_nav_e2e.py -q` | 1 failed, 16 passed, 1 xfailed (680 s) |
| **WITHOUT C3** (shadow package, `PYTHONPATH=~/.cache/parcel-0e/c3/preC3root/src`) | same | **1 failed, 16 passed, 1 xfailed** (724 s) — *the same test* |
| WITH C3, that test alone | `pytest tests/…::test_sit_next_to…` | **1 passed** (63 s) |

**Identical counts and the identical test on both sides: the failure is
pre-existing in the tree C3 landed into**, alongside the NAV_INSTRUCT digest
move of §3.4, and both have the same likely source (the owner's uncommitted
`navigation/grid_planner.py` diff, which moves planner routes by construction).
Flagged for the integrator; nothing in this card touches it.

---

## 4. Close

### 4.1 Files touched (all inside this card's OWNS)

| file | change |
|---|---|
| `src/parcel_robot/navigation/stall_attribution.py` | **new leaf**, 178 lines, 0 `noqa` |
| `src/parcel_robot/navigation/pipeline.py` | watchdog region (~4617-4653) + 1 import line; **7200 → 7198, net −2** (HEAD 7203 → C1 7200 → C3 7198) |
| `tests/test_stall_attribution.py` | **new**, 243 lines, 22 cells |
| `research/20260829/nav-gen-attribution-1/analyze.py` | `live_planner_facts()` + 1 line at the `arm_config_facts` merge |
| `scrum/20260829/task_2/C3_STATUS.md` | this file |

Not touched: `simulation/headless_city.py` (C2), `navigation/grounder.py` /
`poi_admission.py` / `pipeline.py:1139-1163` (C1), `navigation/grid_planner.py`
and every other file in the owner's uncommitted diff, `config.py` (**1000 lines, byte-unchanged**;
no config key added or moved), any `configs/**` file, any frozen digest, any
other research folder, `results.json` / `tables.md`. **No git write.**

### 4.2 Row-by-row summary

| row | verdict |
|---|---|
| RED reproduced (pre-C1 **68 / 44**; post-C1 **52 / 54**, non-POI **43**) | MET, both recorded |
| non-POI stalls halve (bar ≤ 21) → **10** | **MET** |
| 0 collisions | **MET** |
| no increase below the 0.65 m stop band (1 → 1) | **MET** |
| every other reason count unchanged or improved | **MISSED** on `semantic_target_unreachable` (59 → 88); every capability row flat or better, strict success unchanged at 335 |
| frozen NAV_INSTRUCT digest unchanged | **MET for C3** (byte-identical with/without); the tree is already red vs the committed row before C3 exists |
| A1: no episode ends `status=planned` with no terminal reason (530 rows) | **MET, 0** |
| attribution histogram in STATUS before any product line change | **MET** (§1, written at 22:0x; first product line at 22:1x) |
| regression subsets green through the guard | **MET** (22 / 144 / 168 passed); the single `voice_nav_e2e` failure reproduces without C3 |

### 4.3 What this does not prove

Everything the card excludes, plus: `semantic_source: oracle` on every arm, so
none of this is perception; the release door is measured on one seed range, 30
scenes and 3 poses; `HELD_RELEASE_AFTER = 2` is a floor justified by four named
episodes, not a swept parameter; and the class-B1/B2 mechanisms are *attributed*
but only *contained* — see §5.

---

## 5. For the owner / integrator — the two things this card deliberately did not do

**5.1 The residual planner/gate disagreement is 0.0977 m, and closing it is a
value change (re-freeze policy).** Card A2 converts the 0.80 m brake ring into
the planner's frame as `gate_range_ring_m = 0.80 + 0.32 = 1.12 m` and then
applies the gate's directional-cone discount, `1.12 · sin θ = 1.0223 m`. That
discount is exact for a straight corridor traversed along its centreline and
**loose for an obstacle in the closing cone off the corridor axis** — which is
class A exactly (measured: `planter_2` at 60.5° off travel, 0.8000 m). The
planner calls a cell legal at 1.0223 m from an obstacle centre; the gate then
refuses every translation out of it. Making the planner demand the full
`gate_range_ring_m` (1.12 m) would prevent the deadlock **at its source** rather
than recovering from it, and would not shift a single episode into
`semantic_target_unreachable` — but it raises an inflation, moves planned routes
and therefore the frozen navigation evidence (BARN, `nav_instruct`,
FOLLOW_BENCH_V1), and it lives in `authority.ClearanceProfile` /
`navigation/grid_navigator.py`, neither in this card's OWNS. **Recorded, not
taken**, per the card's own rule.

**5.2 Class B1 and B2 are attributed but not repaired.**

* **B1** (5/26): `_control_observation` drops the relational target's own LiDAR
  returns so the point controller can reach its stand-off pose, and its own
  docstring notes the runtime's brake "still sees the unmodified sensor view".
  Measured, the two views differ by **0.9 m** at the hold (navigator handed
  1.60 m; raw return 0.71 m). The navigator has **no channel** through which it
  can learn its command was refused. A one-line honest fix does not exist: it
  needs either a refusal signal from the final gate back into the navigator, or
  the exclusion to stop at the ring the runtime enforces. C3 contains it (the
  odometer witness catches the hold), it does not close it.
* **B2** (4/26): the runtime yields to the **owner** (clearance 1.065-1.232 m vs
  a 1.302 m predictive person stop) while the watchdog's person clause reads
  `nearest_person_m`, which the owner is not on. The clean fix is to widen that
  clause to the owner track the navigator already receives in
  `extras["owner_track"]` — but amendment A1 is right that any watchdog
  exemption needs a hard tick cap and its own terminal reason, and adding one to
  the existing (uncapped) stranger clause moves the N11 pedestrian evidence.
  **A design decision for the owner, not an executor's.** Until then those four
  episodes take the bounded release door like any other held stall, which is
  loud and terminated but is not "the dog waited politely for you".

**5.3 Two red rows that predate C3**, both reproduced with C3 removed from the
tree via a shadow package: the NAV_INSTRUCT minival digest (§3.4) and
`test_voice_nav_e2e.py::test_sit_next_to_the_lamppost…` (§3.6). The owner's
uncommitted `navigation/grid_planner.py` diff is the most likely common source.

---

## Follow-up F1 — the release door is behind a default-OFF flag

**Supersedes §2.2's shipped behaviour and §3's GREEN arm.** §1 (attribution),
§3.1's RED rows and §5 stand unchanged. Everything below was measured in
**isolated worktrees at HEAD 704ba5c** (`git worktree add --detach`, `ln -s
.parcel`, `PYTHONPATH=<wt>/src:<wt>`, `MUJOCO_GL=egl`), with **no owner diff and
no other wave-A card**.

### F1.0 The verifier finding, verbatim

> Verifier finding (isolated worktrees, HEAD 704ba5c, PYTHONPATH pinned,
> MUJOCO_GL=egl, NO owner diff): running scripts/mutation_panel.py — HEAD:
> passed True, clean authority {agreement 4, authority_disagreement 1}; HEAD +
> wave-A files WITH your watchdog hunk + leaf: passed FALSE, survivors
> ['reactive_gate_disabled'], clean authority {agreement 5}; the same tree with
> ONLY your watchdog hunk reverted and the leaf removed: passed True,
> {agreement 4, authority_disagreement 1}. A HEAD+C3-only arm is running to
> confirm, but the direction is clear: your release door changes D-15's terminal
> on the frozen panel episode and makes the panel's most important mutant
> (reactive gate disabled) indistinguishable from the clean run — a hard-safety
> artifact moved by a wave-A card (E3), and the executor's "C3 moves the digest
> by 0" was measured in a tree where the owner's grid_planner.py already
> prevented the gate from binding.

And the confirming arm, verbatim:

> C3-F1 nuance from the confirming arm (HEAD + your watchdog hunk + leaf ONLY,
> isolated worktree): passed True, survivors [], clean authority {agreement 4,
> tolerated_boundary 1} — your release door alone moves D-15's verdict
> (authority_disagreement → tolerated_boundary), so the committed C0 panel no
> longer reproduces; the reactive_gate_disabled SURVIVOR appears only in
> combination with the rest of wave A (C1-F1 in flight + C2).

**Accepted without reservation.** §3.4's "C3 moves the NAV_INSTRUCT digest by 0"
was measured in the shared working tree, where the owner's uncommitted
`grid_planner.py` diff was already in force — the finding is that the release
door *does* move a hard-safety artifact once that confound is removed, and my
measurement could not have seen it. The E3 rule applies: **a wave-A card may not
move a frozen hard-safety row.**

### F1.1 The flag

| | |
|---|---|
| **key** | **`progress_watchdog.held_stall_release`** in a navigation YAML (`configs/navigation/default.yaml`'s section), **default `False`** |
| kwarg | `DirectiveNavigator(held_stall_release=False)` / `from_config(path, held_stall_release=…)`; the kwarg wins over the file, the eval runner's `navigator_overrides` idiom |
| shipped profile | **does not carry the key** — asserted by `test_the_shipped_navigation_config_does_not_carry_the_key`. **No `configs/**` file was edited.** |
| off-path contract | `stall_attribution.held_release_due()` gates on `enabled` **first and short-circuits**: flag-OFF it reads nothing, writes nothing into `mission.metadata`, and returns before any classification — so `_progress_watchdog` is byte-identical to HEAD. Asserted on the mapping itself (`test_held_release_due_reads_and_writes_nothing_when_disabled`, `test_flag_off_watchdog_is_byte_identical_to_the_pre_c3_path`). |

`pipeline.py` **7200 → 7211 (+11)** — the flag plumbing (one signature line, one
assignment + 3 comment lines, a 6-line `from_config` read) costs more than the
watchdog simplification saved. §2.2's "net −2" no longer holds; the DEC-0
ratchet regression is F1's cost and is stated here rather than absorbed.

### F1.2 Off-path proof — isolated worktree, HEAD + C3 ONLY, flag OFF

`~/.cache/parcel-0e/c3/wt-f1` (detached at 704ba5c; only
`navigation/pipeline.py` modified and `navigation/stall_attribution.py` added —
`git status` shows nothing else). Verified in-process:
`DirectiveNavigator.from_config().held_stall_release is False`.

```
cd <wt>; env -u TMPDIR MUJOCO_GL=egl PYTHONPATH=<wt>/src:<wt> \
  OPENBLAS_NUM_THREADS=16 <wt>/.parcel/bin/python scripts/mutation_panel.py
```

| row | result |
|---|---|
| `passed` | **True** |
| `survivors` | **`[]`** |
| clean-run authority histogram | **`{"agreement": 4, "authority_disagreement": 1}`** |
| `reactive_gate_disabled` | **killed** (`success_set_identical`, `failure_histogram_identical`) |
| vs the C0 panel in the tree | **byte-identical** — `clean_run`, `clean_checks` and `mutants` all compare equal; the only differing keys are `generated_at` and `episode_set_provenance` |

(`mean_dtg_m` 0.3616797968250607 and `authority {agreement 4,
authority_disagreement 1}` match C0's regenerated panel exactly; the panel
committed at HEAD carries the older `{agreement 4, tolerated_boundary 1}` /
`mean_dtg 0.7754`, which is C0's own row to reconcile, not C3's.)

Minival, same worktree, same command shape:

```
python -m evals.nav_instruct.run_nav_instruct_v1 --minival --mode baseline \
  --episode-version v4 --no-ledger --out <scratch>
```

| digest (`report_digest(drop_aggregate_scene=True, compact=True)`) | value |
|---|---|
| **required** | `021b67ab73c4e7be…` |
| **measured, flag OFF** | **`021b67ab73c4e7be647aba1a17e20a193ebf23b826a18d5b0990e296e5708496`** ✅ |

`episode_digest` `4113607b92c734df…`; authority `{agreement 20,
authority_disagreement 5}`.

**Both off-path rows are green.**

### F1.3 The measurement, flag ON — harness only

The shipped config is untouched; the flag is injected into the NAV-GEN-1
harness's own per-arm scratch config tree
(`~/.cache/parcel-0e/c3/mirror_on/…/run.py`, a mirrored copy: arm A0 built from
a scratch tree at the commissioned values with `held_stall_release: true`
appended to its `progress_watchdog` block). `results.json`'s own plumbing
control (`plumbing_control_A0_vs_A0c_identical: true`) is what licenses a
scratch tree at the commissioned values as an A0 arm. Both arms, 530 episodes,
16 workers, `NG1_SCRATCH` under this card's scratch.

**The tree moved again under both arms (C1-F1 landed: false arrivals 42 → 0,
wrong-instance 0), so both columns are re-measured on the tree as of 03:5x.**

| row | flag OFF (shipped) | flag ON (harness) | Δ |
|---|---|---|---|
| **non-POI `navigation_no_progress`** | **47** | **10** | **−79 %** |
| `navigation_no_progress` (all generated) | 49 | 10 | −39 |
| `semantic_target_unreachable` | 63 | 96 | **+33 (the same miss as §3.2)** |
| `arrived_verified` | 295 | 300 | +5 |
| `semantic_arrival_verification_failed` | 42 | 43 | +1 |
| false arrivals | 0 | 0 | 0 |
| **strict success (generated)** | **342** | **342** | **0** |
| strict success, any legal instance | 344 | 349 | +5 |
| band entry | 354 | 358 | +4 |
| **collisions** | **0** | **0** | 0 |
| **episodes < 0.65 m** | **1** | **1** | 0 |
| rows with no terminal reason (A1) | 0 | **0** | 0 |
| episodes changed at all (530), **full-row comparison** | — | **48** | 482 rows byte-identical |
| strict regressions / gains | — | **2 / 2** | net 0 |

The 47 flag-OFF stalls under the flag: 30 `semantic_target_unreachable`,
**6 `arrived_verified`**, 1 `semantic_arrival_verification_failed`, 10 still
stalled.

**Recount, integrator's correction (a).** The register's 41 was a comparison of
the terminal `reason` field only. By **full-row** comparison the flag changes
**48 of 530** rows: 41 change terminal reason, and 7 more
(`gen:880000:planter:2`, `gen:880006:planter:1`, `gen:880012:planter:2`,
`gen:880018:planter:1`, `gen:880019:planter:1`, `gen:880020:planter:1`,
`gen:880022:planter:2`) keep their reason but change `target_id`,
`terminal_xy`, `dtg_m`, `dtg_any_instance_m`, `inside_2x_band`, `steps` and
`path_length_m` — the release door sent them to the scene's *other* planter and
they stalled there instead. **48 is the number; 482 rows are byte-identical.**

**Correction (b).** The two strict regressions in these F1 rows are
**`gen:880007:crosswalk:1`** and **`gen:880016:crosswalk:0`** — both accidental
successes that stalled *inside* the goal band (`dtg 0.0` with reason
`navigation_no_progress`) — against two genuine gains
(`gen:880009:sidewalk:1`, `gen:880014:crosswalk:0`). (`gen:880025:crosswalk:2`
belongs to the **pre-F1** tree's first release-on-first-held-stall variant,
§2.3, and is not one of these rows.) **The attribution of §1 and the 43 → 10 result reproduce as 47 → 10 on
the newer tree; they remain the research finding, not shipped behaviour.**

### F1.4 The sentence this card is required to record

**Enabling the release door on the shipped profile is an owner re-freeze
decision (moves frozen panel/minival rows; the honest fix is the planner
demanding the full 1.12 m — the same directional-inflation question).**

See §5.1: the residual planner/gate disagreement is **0.0977 m**
(`1.12 · sin θ = 1.0223` vs the `1.12 m` the gate actually demands off the
corridor axis). Closing it removes the deadlock at its source instead of
recovering from it — and it is the same re-freeze conversation, with a better
answer at the end of it.

### F1.5 Tests and hygiene after F1

`tests/test_stall_attribution.py` **28 cells** (was 22): six new F1 cells —
default-OFF on a real `from_config()` navigator, the shipped YAML has no key,
`held_release_due` leaves the mapping untouched when disabled (with an armed
call on the *same* mapping as the negative control), the flag-OFF watchdog takes
the plain replan with `metadata == before`, flag-OFF still fails loudly on a
spent ladder, and the key arriving from both the YAML and the kwarg.
`ruff check` clean on all four touched files; **0 `noqa`**; `config.py`
untouched at 1000 lines; no `configs/**` edit; no git write.

Regression subsets re-run against the flagged code, one guarded invocation —
`test_stall_attribution` `test_navcore_probe` `test_a2_navglue`
`test_a3_discontinuity_latch` `test_door1_doorway` `test_grid_navigator`
`test_grid_planner` `test_unroutable_goal_release`
`test_semantic_navigation_regressions` `test_yield_policy`
`test_rm2_route_memory_product_path` `test_pose_consumers`
`test_nav_instruct_digest_recipe`: **324 passed**.

The isolated worktree `~/.cache/parcel-0e/c3/wt-f1` is left in place for the
verifier (it holds the panel JSON and the flag-OFF report); remove it with
`git worktree remove --force ~/.cache/parcel-0e/c3/wt-f1`.
