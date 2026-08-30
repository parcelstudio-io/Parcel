# NAV-GEN-1 — RESULTS

Executor: Opus (parcel-0e session), 2026-08-29/30. Design: `DESIGN.md` (FROZEN,
not moved). Evidence tier: **`desktop-sim`**. Physical motion: **NO-GO**,
unchanged. **No verdict is drawn here** — `VERDICT.md` is Fable's.

Written incrementally, one section per stage, as each stage finished.

## Headline (each bar quoted in full in its own section)

| hypothesis | pre-registered bar | measured | met? |
|---|---|---|---|
| **H-NG1a** clause 1 | >= 70 % of strict failures inside 2x band or in the DESIGN's reason list | **0.4459** [0.3703, 0.5240] | **no** |
| **H-NG1a** clause 2 | < 15 % grounding failures; **refuted if >= 30 %** | **0.5350** [0.4571, 0.6113] | **no — refutation clause fires** |
| **H-NG1b** | >= 20 points of strict success at zero collisions; **refuted if no value gains >= 10** | best **+2.00** points (arm B1, 0 collisions) | **no — refutation clause fires** |
| **H-NG1c** | frozen-block per-target rates within +- 0.15 of MA-1's probe | 5/5 within +- 0.15 of **MA-1's published row**; 2/3 within +- 0.15 of the **values the DESIGN quotes** | **mixed — the two references disagree** |

Three facts drive all of it, and each is measured, not inferred:

1. **`map_safety_margin_m` cannot move the shipped planner.** The live
   `DirectiveNavigator` commissions the grid planner with
   `map_gate_clearance_m = safety.stop_distance_m` (0.80 m), so the planner
   inflates **1.0223 m**, not the 0.42 m the config files read like — and
   NAV-CORE's "planner 0.42 m" is stale. Six arms from 0.10 down to 0.00
   return byte-identical rows (section 2.1, 4.1).
2. **On this corpus clearance is not the binding constraint at all.** The
   minimum, over all 450 episodes, of the best standable clearance inside the
   goal band is **1.00 m** against a planner demand of 0.7023 m. Zero episodes
   have a goal the commissioned planner cannot stand in (7.2b).
3. **The largest single failure class is a hardcoded lookup table.** All 84
   grounding failures resolved `crosswalk_a` — a `demo_pois.yaml` row at
   `[3.5, -0.6]` that exists in no generated scene — producing **42 false
   arrivals** (`status = arrived`, median 3.17 m from any crosswalk —
   `statistics.median` over n = 42; the upper-middle order statistic `dtg[n//2]`
   is 3.25 m; `results.json` -> `false_arrival_dtg_A0`). Excluding
   `crosswalk`, grounding failures are **0** and H-NG1a's clause 1 passes at
   **0.7808** (section 5).

## 0. Pre-flight

* Seed `20260829`; `.parcel/bin/python` (repo venv); scratch
  `~/.cache/parcel-0e/ng1/`; `TMPDIR` unset on every command.
* `PARCEL_MEMORY_PATH` -> `~/.cache/parcel-0e/ng1/scratch_memory.sqlite3`. The
  owner's `parcel_memory.sqlite3` is never opened. The headless harness needs
  no memory store; the variable is set defensively by `episodes.py`.
* No sockets, no subprocess simulator (the headless city runs in-process), no
  `/dev/bus/usb`, no hosted or VLM call, no GPU work, **$0**. The owner's
  `:8080` / `:8765` / `/tmp/parcel_sim.sock` are untouched. No `git` write.
* Nothing under `src/`, `evals/`, `configs/`, `tests/` or any other
  `research/20260829/` folder is written. MA-1's `teacher.py` is imported BY
  PATH and read-only; MA-1's own scratch is untouched (`MA1_SCRATCH` is
  repointed into this probe's tree, so the scene cache is ours).
* **The NAV evals' held-out scene is never loaded and never named.** No frozen
  episode set or digest is read or moved.
* **A foreign live session shares this host** (`research/20260829/model-b-contract-2/run.py`
  with `--threads 32`, seen at 20:28 local). Workers were pinned to one BLAS
  thread each so the pool would stay under the 48-thread ceiling. **The worker
  COUNT the recorded sweeps ran with is not in any artifact** — the first draft
  of this file quoted 24 here, 40 in section 8 and 40 in `README.md`'s reproduce
  block, and none of the three can be checked. `run.py` now writes
  `run_provenance.workers` into `raw/index.json`, and `results.json` ->
  `run_provenance.workers` reads `null` with `workers_note` saying so for these
  rows (card C7).

### Host

Rendered by `analyze.py` from `raw/index*.json`; the table is `tables.md` 8.1
verbatim, so no load average here is typed by hand.

| when | loadavg (1/5/15) | cpus | GPU (used / total, util) | UTC |
|---|---|---|---|---|
| sweep A start | 12.94 / 23.51 / 16.13 | 192 | 2058 MiB, 32760 MiB, 25 % | 2026-08-30T00:38:51Z |
| sweep A end | 3.95 / 12.86 / 17.14 | 192 | 2031 MiB, 32760 MiB, 25 % | 2026-08-30T00:52:07Z |
| sweep B start | 2.91 / 10.08 / 15.73 | 192 | 2030 MiB, 32760 MiB, 27 % | 2026-08-30T00:53:45Z |
| sweep B end | 15.04 / 23.44 / 21.07 | 192 | 2026 MiB, 32760 MiB, 41 % | 2026-08-30T00:57:42Z |

The first draft of this table printed sweep A's start as `3.06 / 2.97 / 2.72`
with GPU `2145 MiB` — a snapshot that appears in **no** artifact; the recorded
one is the `12.94 / 23.51 / 16.13` row above (`raw/index_sweepA.json` ->
`host_start`, written by `run.py` at 00:38:51Z). Corrected under card C7.

Every snapshot is in `results.json` under `run_provenance.host`
(`sweepA_start` / `sweepA_end` / `sweepB_start` / `sweepB_end`); the older,
ambiguous `host_start` / `host_end` keys are kept and are **sweep B's**, because
`index.json` belongs to whichever sweep finished last.

## 1. The episode set

| | value |
|---|---|
| generated scene seeds | `880000`-`880029`, **30 scenes** |
| targets | `bench`, `lamppost`, `planter`, `sidewalk`, `crosswalk` (MA-1's five demonstrable targets) |
| start poses per (scene, target) | **3** (DESIGN floor: >= 2) |
| **generated episodes per arm** | **450** (DESIGN floor: >= 300) |
| control block | the frozen demo block, `HeadlessCityWorld`'s default scene |
| control poses per target | **16** (DESIGN floor: >= 10) — 16 reproduces the episode count of MA-1's pre-generation probe |
| **control episodes per arm** | **80** |
| total per arm | **530** |

Seeds are disjoint from MA-1's own ranges (train `770000-770600`, dev
`780000-780060`, held `790000-790120`), from the reserved foreign block
`91000-91100`, and from `scene_gen.VAL_UNSEEN_SEEDS` (`91011-91015`).

Scenes are built by MA-1's own `build_scene_path(seed)`, i.e.
`evals.nav_instruct.scene_gen.build_scene(seed, scratch_dir=...)` with its
round-trip / overlap / layout / support / **navigability** filters. Manifest
sha256 over the 30 accepted MJCF files:
`b698e0594a7d456050bb3740e2c961da7748dd19dd8f25b643904d1729b4ab43`.

Start poses come from MA-1's own sampler (`prepare_episode`): rejection
sampling in `x in [-6.6, 6.6]`, `y in [-3.0, 1.6]`, body clearance > 0.7 m,
`2.5 m <= distance to the goal <= 9.5 m`, heading at the goal +- 0.7 rad.
**MA-1's frozen-block probe code is not in the repo** (only its numbers, its
`RESULTS.md` 2), so the control set reconstructs that probe with the same
sampler rather than replaying its RNG stream; this is recorded as a limit on
the H-NG1c comparison, not worked around.

Per-scene obstacle density, from the generator's OWN accepted `SceneParams`
(30/30 scenes carry 6 buildings): building footprint / corridor area **min
0.399, median 0.476, max 0.570**. An empirical companion measure (the fraction
of the start rectangle where the body does not fit, and the fraction inside the
0.65 m stop band) is recorded per scene in `results.json`.

## 2. The arms and the exact config keys

### 2.1 The key the DESIGN names — and the measurement that it is INERT

`DESIGN.md` H-NG1b names "the map safety margin and planner inflation as the
config store exposes them". The map safety margin is

```
configs/navigation/models/grid.yaml   controller.map_safety_margin_m   # 0.10 commissioned
```

and the planner's hard, non-traversable inflation is

```
GridPlannerConfig.inflation_radius_m
  = max(robot_radius_m + effective_hard_margin_m,   # 0.32 + margin
        gate_lateral_clearance_m)                   # from the COMMISSIONED gate ring
```

Reading only the config files, the second term looks unset on `grid_v1` and
the max collapses to `0.32 + margin = 0.42 m`. **That reading is wrong on the
product path, and the probe measured it rather than assuming it.**
`DirectiveNavigator._create_navigator` commissions every grid model with

```python
options["map_gate_clearance_m"] = self._planner_gate_ring_m()   # = safety.stop_distance_m
```

so on the shipped config the planner is handed a **0.80 m** gate ring, which
`ClearanceProfile.gate_range_ring_m` converts to 1.12 m and
`gate_lateral_clearance_m` to **1.0223 m** — and the max takes THAT, not the
footprint term. Read off the LIVE `DirectiveNavigator` object, one per arm (reproduce with
`plumbing_check.py`):

| arm | `map_safety_margin_m` | footprint term (m) | live `gate_clearance_m` | **live `inflation_radius_m` (m)** |
|---|---|---|---|---|
| **A0** (commissioned) | 0.10 | 0.42 | 1.12 | **1.022296** |
| A0c | 0.10 | 0.42 | 1.12 | 1.022296 |
| A1 | 0.07 | 0.39 | 1.12 | 1.022296 |
| A2 | 0.05 | 0.37 | 1.12 | 1.022296 |
| A3 | 0.02 | 0.34 | 1.12 | 1.022296 |
| A4 | 0.00 | 0.32 | 1.12 | 1.022296 |

**`map_safety_margin_m` cannot move the shipped planner's inflation at all**:
every value from the commissioned 0.10 down to 0.00 is swallowed by the `max`
against the gate term. Sweep A is therefore a null-by-construction arm — and
its result (section 4) is the empirical proof of that, not a redundancy.

This also corrects a stale number in the literature this probe was pointed at:
NAV-CORE (2026-08-24) recorded "the planner inflates 0.42 m". On today's code
the live planner inflates **1.0223 m**, i.e. it refuses every corridor narrower
than **2.045 m**. Card A2 landed the coupling NAV-CORE asked for, and this is
what it cost.

### 2.2 Sweep B — the key that DOES move the planner

The exposed key that actually moves the inflation is

```
configs/navigation/default.yaml   safety.stop_distance_m   # 0.80 commissioned
```

which is simultaneously the navigation pipeline's own collision brake
(`apply_collision_brake`) — deliberately, per card A2's "one clearance
authority". Sweep B moves it and records both effects:

| arm | `safety.stop_distance_m` | live gate ring (m) | **live planner inflation (m)** | narrowest routable corridor (m) |
|---|---|---|---|---|
| **A0** (commissioned) | 0.80 | 1.12 | **1.022296** | 2.045 |
| B1 | 0.65 | 0.97 | 0.885381 | 1.771 |
| B2 | 0.50 | 0.82 | 0.748466 | 1.497 |
| B3 | 0.40 | 0.72 | 0.657190 | 1.314 |
| B4 | 0.32 | 0.64 | 0.584169 | 1.168 |

`map_safety_margin_m` stays at its commissioned 0.10 across sweep B.

Held fixed in EVERY arm of both sweeps, asserted inside each work unit at run
time: `configs/robot.yaml` `safety.obstacle_stop_m` **0.65** and
`obstacle_slow_m` **1.2** — the reactive-safety stop/slow bands the DESIGN
requires be held. Those are a different authority from
`safety.stop_distance_m`, and `required_obstacle_clearance_m` on every episode
row is 0.65 in every arm.

### 2.3 The DESIGN's 0.20 m is unreachable — recorded, not worked around

`DESIGN.md` H-NG1b asks for ">= 4 values from the commissioned value down to
0.20 m". Neither key reaches it:

* on `map_safety_margin_m`, the inflation's footprint term is
  `SafetyEnvelope.footprint_radius_m` = **0.32 m**, a code constant in
  `parcel_robot.authority`, not a config key, and `ClearanceProfile` refuses a
  negative margin — measured, verbatim:
  `ValueError: planner_hard_margin_m must be non-negative` at
  `map_safety_margin_m = -0.01`;
* on `safety.stop_distance_m`, `ClearanceProfile.__post_init__` refuses any
  ring inside the body hull `SafetyEnvelope.stop_distance(0.0)` = **0.32 m**,
  and that floor still yields an inflation of **0.5842 m**.

Reaching a 0.20 m inflation would require editing `src/`, which this probe may
not do. The closest faithful thing is run: **sweep B spans the commissioned
1.0223 m down to 0.5842 m in four steps** (a 0.44 m span, versus the 0.22 m
span the DESIGN asked for), and sweep A additionally covers the DESIGN's named
key over its whole range. This bounds H-NG1b's claim: the interval
0.5842 -> 0.20 m is unmeasured here.

### 2.4 How the override is applied without editing configs

Each non-commissioned arm gets its own navigation config TREE under
`~/.cache/parcel-0e/ng1/navcfg/<arm>/`: a copy of
`configs/navigation/default.yaml` (with absolute `models_root` / `pois_path`
and, for sweep B, that arm's `stop_distance_m`) plus a copy of
`configs/navigation/models/` whose `grid.yaml` carries that arm's
`map_safety_margin_m`. The harness is pointed at it by assigning
`HeadlessCityQualityHarness.navigation_config` (a `Path`, consumed by
`DirectiveNavigator.from_config`). `reactive_safety` and `spatial_config` are
left exactly as `_reactive_safety_from_store` / `_spatial_config_from_store`
built them from the untouched `configs/robot.yaml`.

**A0 runs the repo file itself.** **A0c** runs a scratch copy at the
commissioned value and reproduces A0 **row for row, byte-identical** — that is
the proof the override plumbing is inert when it should be. The live-planner
read-back table in 2.1 is the proof it is not inert when it should not be.

## 3. What is driven, and what "success" means here

The stack under test is the shipped one, entered through the product's own
headless door: `HeadlessCityQualityHarness.run(text)` ->
`navigation_directive_from_text` -> `DirectiveNavigator.from_config` (grid
planner `grid_v1` + the semantic resolution ladder + search/recovery) ->
`apply_reactive_safety` -> `HeadlessCityWorld.apply/step`. `max_steps` is the
harness's own default, **1800**. Each episode is ONE plain directive
(`"go to the <target>"`), no interruption, no queue, no stop cue.

Four predicates are recorded per episode and never blended:

| name | definition |
|---|---|
| `nav_claimed_success` | the navigator's own verdict, `status in {arrived, completed}` |
| **`strict_success`** | terminal pose inside the goal band (`teacher.inside_goal_band`, MA-1's own region predicate) AND the terminal command is zero **on that one frame** |
| `strict_success_any_instance` | the same, but against **any** scene entity carrying the requested label |
| `band_entry` | the body was inside the goal band at any point on the path (MA-1's `success_loose`) |

`strict_success` is the headline because it is the closest predicate this
harness can compute to the one MA-1 reported. **It is NOT MA-1's arrival
oracle, and an earlier revision of this file wrongly called it that** — see the
correction in 7.3. MA-1's `arrived` additionally requires the body to hold
still for `ORACLE_SETTLE_FRAMES = 5` (`closed_loop_core.py:256-267`); this
probe checks the terminal frame only, because `HeadlessCityQualityHarness.run`
returns after the controller stops rather than exposing a post-stop settle
window. The predicate also has a known instance bias that this probe measures rather than inherits: MA-1's
oracle scores an object goal against ONE hardcoded id (`bench_1`,
`lamp_post_1`, `planter_1`), so a robot that correctly walks to `planter_2` is
scored as a failure. `strict_success_any_instance` is reported beside it.

**DTG** is metres from the terminal pose to the nearest point of the strict
band (an annulus for objects, a polygon for regions; 0 inside).
**Inside 2x band** is `DTG <= band_radius`, where the band radius is the
object's outer vicinity radius or the region's area-equivalent radius — i.e.
exactly the band doubled about its own goal, uniform over both goal kinds.

**Wrong instance** is decided against the SCENE, not against a name pattern:
the legal ids for a target class are the ids of the scene entities carrying
that label. `truth_minimum_clearance` is a SIGNED BODY-SURFACE clearance (the
0.32 m robot radius is already subtracted), so a band point is passable to the
grid planner exactly when its clearance is `>= map_safety_margin_m`, and the
reactive gate will drive there only when it is `>= obstacle_stop_m` (0.65 m).
That single mapping is what makes the per-goal clearance rows readable.

## 4. H-NG1b — the clearance sweep: **REFUTED by its own clause**

> *"Sweeping the navigation config's clearance parameters ... raises strict
> success on the same episodes by >= 20 points absolute at some value without
> raising the collision count above 0 and without lowering minimum clearance
> below the stop band. **Refuted if no value gains >= 10 points at zero
> collisions.**"* — `DESIGN.md`

### 4.1 The sweep (generated block, 450 episodes per arm)

| arm | sweep | `map_safety_margin_m` | `safety.stop_distance_m` | **live planner inflation (m)** | strict success | 95 % Wilson CI | any-instance strict | band entry | nav-claimed | grounding-class episodes | false arrivals | collisions | episodes with min clearance < 0.65 m |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A0 **(commissioned)** | A | 0.10 | 0.80 | 1.0223 | 293/450 = **0.6511** | [0.6060, 0.6937] | 0.6556 | 0.6889 | 0.6311 | 90 | 42 | **0** | 1 |
| A0c | A | 0.10 | 0.80 | 1.0223 | 293/450 = **0.6511** | [0.6060, 0.6937] | 0.6556 | 0.6889 | 0.6311 | 90 | 42 | **0** | 1 |
| A1 | A | 0.07 | 0.80 | 1.0223 | 293/450 = **0.6511** | [0.6060, 0.6937] | 0.6556 | 0.6889 | 0.6311 | 90 | 42 | **0** | 1 |
| A2 | A | 0.05 | 0.80 | 1.0223 | 293/450 = **0.6511** | [0.6060, 0.6937] | 0.6556 | 0.6889 | 0.6311 | 90 | 42 | **0** | 1 |
| A3 | A | 0.02 | 0.80 | 1.0223 | 293/450 = **0.6511** | [0.6060, 0.6937] | 0.6556 | 0.6889 | 0.6311 | 90 | 42 | **0** | 1 |
| A4 | A | 0.00 | 0.80 | 1.0223 | 293/450 = **0.6511** | [0.6060, 0.6937] | 0.6556 | 0.6889 | 0.6311 | 90 | 42 | **0** | 1 |
| B1 | B | 0.10 | 0.65 | 0.8854 | 302/450 = **0.6711** | [0.6264, 0.7129] | 0.6756 | 0.7000 | 0.6400 | 90 | 42 | **0** | 3 |
| B2 | B | 0.10 | 0.50 | 0.7485 | 298/450 = **0.6622** | [0.6173, 0.7044] | 0.6644 | 0.6956 | 0.6356 | 90 | 41 | **0** | 13 |
| B3 | B | 0.10 | 0.40 | 0.6572 | 298/450 = **0.6622** | [0.6173, 0.7044] | 0.6644 | 0.6956 | 0.6333 | 90 | 40 | **0** | 18 |
| B4 | B | 0.10 | 0.32 | 0.5842 | 296/450 = **0.6578** | [0.6128, 0.7001] | 0.6600 | 0.6933 | 0.6222 | 90 | 40 | **0** | 15 |

### 4.2 Gain vs the commissioned arm

| arm | live planner inflation (m) | gain (points, strict) | collisions | zero collisions |
|---|---|---|---|---|
| A0c | 1.0223 | +0.00 | 0 | yes |
| A1 | 1.0223 | +0.00 | 0 | yes |
| A2 | 1.0223 | +0.00 | 0 | yes |
| A3 | 1.0223 | +0.00 | 0 | yes |
| A4 | 1.0223 | +0.00 | 0 | yes |
| B1 | 0.8854 | +2.00 | 0 | yes |
| B2 | 0.7485 | +1.11 | 0 | yes |
| B3 | 0.6572 | +1.11 | 0 | yes |
| B4 | 0.5842 | +0.67 | 0 | yes |

**Both bars are missed and the DESIGN's own refutation clause fires.** The best
arm is B1 (planner inflation 0.8854 m): **+2.00 points** of strict success at
**zero collisions**. No arm reaches +10, let alone +20. Every arm ran zero
collisions, so the collision side of the bar is satisfied vacuously.

Two distinct mechanisms produce that flat curve, and the probe separates them:

1. **Sweep A is inert by construction, and measured to be so.** All six A arms
   return *byte-identical* rows: 293/450, the same 157 failures, the same
   paths. `map_safety_margin_m` never reaches the shipped planner's inflation
   (section 2.1). A0c reproducing A0 exactly is the plumbing control that makes
   this a measurement rather than a bug.
2. **Sweep B does move the inflation — 1.0223 m -> 0.5842 m, a 0.44 m
   reduction that takes the narrowest routable corridor from 2.045 m to
   1.168 m — and it buys 2 points.** The reason is in 7.2b: on these 30 scenes
   the goal bands are not tight. The *minimum* over all 450 episodes of the
   best standable clearance inside the goal band is **1.00 m**, against a
   planner demand of 0.7023 m at the commissioned inflation. **Zero of 450
   episodes have a goal the commissioned planner cannot stand in.** Clearance
   was never the binding constraint on this corpus, so relaxing it cannot pay.

The cost side is visible and monotone: episodes whose minimum truth clearance
fell below the runtime reactive gate's 0.65 m stop band go **1 -> 3 -> 13 ->
18 -> 15** as `stop_distance_m` drops 0.80 -> 0.65 -> 0.50 -> 0.40 -> 0.32.
The reactive gate held — zero collisions everywhere — but the margin the body
kept shrank, which is what the DESIGN's "without lowering minimum clearance
below the stop band" clause was guarding. Read strictly, that clause is already
grazed at the commissioned arm (1 episode of 450), so what the sweep shows is
the *slope*: the count rises 13x from A0 to B2 and 18x to B3. Even the +1.11
and +0.67 point gains therefore come with a materially thinner margin, and none
of them approaches the +10 the refutation clause needed anyway.

## 5. H-NG1a — is it termination/clearance, or grounding? **REFUTED**

> *"... >= 70 % of strict failures end with the robot inside 2x the goal band
> or with `reason in {semantic_target_unreachable, goal_blocked, arrival
> verification failed}`, and < 15 % end with a grounding failure. **Refuted if
> grounding failures >= 30 %.**"* — `DESIGN.md`

### 5.1 Reason histogram — strict failures, commissioned arm, generated block

n = 157 strict failures of 450 episodes.

| reason | n | share | of which grounding-class (wrong instance) |
|---|---|---|---|
| `navigation_no_progress` | 68 | 0.433 | 42 |
| `semantic_target_unreachable` | 44 | 0.280 | 0 |
| `arrived` | 42 | 0.268 | 42 |
| `arrived_verified` | 2 | 0.013 | 0 |
| `semantic_target_ambiguous` | 1 | 0.006 | 0 |

### 5.2 Top-5 failure reasons with one example episode each

| reason | n | example episode id | example DTG (m) | example inside 2x band |
|---|---|---|---|---|
| `navigation_no_progress` | 68 | `gen:880000:crosswalk:0` | 1.9556 | False |
| `semantic_target_unreachable` | 44 | `gen:880000:bench:1` | 3.4981 | False |
| `arrived` | 42 | `gen:880000:crosswalk:1` | 2.6865 | False |
| `arrived_verified` | 2 | `gen:880014:planter:1` | 8.8064 | False |
| `semantic_target_ambiguous` | 1 | `gen:880008:planter:2` | 6.9251 | False |

### 5.3 H-NG1a's two clauses

| quantity | commissioned arm | any-instance oracle | excluding `crosswalk` |
|---|---|---|---|
| strict failures (n) | 157 | 155 | 73 |
| inside 2x band | 0.2357 | 0.2387 | 0.3288 |
| reason in the DESIGN's list | 0.2803 | 0.2839 | 0.6027 |
| **covered by H-NG1a clause 1** | 0.4459 | 0.4516 | 0.7808 |
| **grounding failures** | 0.535 | 0.5419 | 0.0 |
| false arrivals | 0.2675 | 0.271 | 0.0 |
| sensitivity: + `navigation_no_progress` | 0.7261 | 0.7355 | 0.9589 |

**Clause 1 missed: 0.4459** (95 % Wilson CI [0.3703, 0.5240]) against a >= 0.70
bar. **Clause 2 missed and the refutation clause fires: grounding failures are
0.5350** ([0.4571, 0.6113]) against a < 0.15 bar and a >= 0.30 refutation
threshold.

**Every one of the 84 grounding failures is the same defect, and it is not the
navigator's.** All 84 resolved `target_id = crosswalk_a` — an id that exists in
no generated scene. It is a row in `configs/navigation/cities/demo_pois.yaml`,
a hardcoded coordinate `[3.5, -0.6]` kept "inside the compact MuJoCo city block
for an end-to-end demo". `PlaceGrounder` fires *before* semantic search, so
"go to the crosswalk" is answered by a lookup table rather than by the scene's
own `crosswalk` region (polygon around `[-0.35, -0.06] .. [1.15, 1.92]` on seed
880000). The mission then drives to the table's point and declares success:
**42 of the 90 crosswalk episodes are FALSE ARRIVALS** — `status = arrived`
with the body in no crosswalk at all, median DTG 3.17 m (`statistics.median`,
n = 42; upper-middle order statistic 3.25 m), worst 7.17 m — `results.json` ->
`false_arrival_dtg_A0`. The
other 42 stall out as `navigation_no_progress` on the way to the wrong place.

This is exactly the second-oracle hazard `configs/navigation/default.yaml`
already warns about in its `semantic_source` comment ("a second oracle ... a
mission that 'succeeds' through it has measured a lookup table") — measured
here, on the product path, at `semantic_source: oracle`.

**Remove that one defect and H-NG1a passes on both clauses.** On the four
targets that never touch the POI table, coverage is **0.7808** (>= 0.70, met)
and grounding failures are **0.0000** (< 0.15, met) over 73 strict failures.
The pre-registered numbers are the ones in the first column; this is reported
as attribution, not as a substitute.

**Sensitivity, reported beside the bar and never in place of it.** The DESIGN's
reason list does not name `navigation_no_progress`, which is the progress
watchdog firing with the route still planned — NAV-CORE's stall class, 68 cases
here. Counting it as termination/clearance moves coverage to **0.7261**
overall and **0.9589** excluding `crosswalk`. Whether it belongs in that class
is Fable's call, not this file's.

## 6. H-NG1c — is the frozen block special? **MET vs MA-1's published row, MISSED vs the DESIGN's quoted values (the two disagree)**

> *"On the frozen demo block the same recipe reproduces the known per-target
> rates (sidewalk ~ 0.75, lamppost ~ 0.6, bench ~ 0.0 from MA-1's
> pre-generation probe) within +- 0.15"* — `DESIGN.md`

### 6.1 Frozen demo block, per target (commissioned arm, 16 episodes each)

| target | band entry | rate | 95 % CI | strict | MA-1 published probe | delta vs MA-1 | within +-0.15 of MA-1 | DESIGN's quoted value | within +-0.15 of DESIGN |
|---|---|---|---|---|---|---|---|---|---|
| `bench` | 2/16 | **0.1250** | [0.035, 0.360] | 0.0625 | 0.19 | -0.0650 | yes | 0.0 | yes |
| `lamppost` | 6/16 | **0.3750** | [0.185, 0.614] | 0.3750 | 0.44 | -0.0650 | yes | 0.6 | NO |
| `planter` | 2/16 | **0.1250** | [0.035, 0.360] | 0.0625 | 0.06 | +0.0650 | yes | -- | -- |
| `sidewalk` | 13/16 | **0.8125** | [0.570, 0.934] | 0.8125 | 0.75 | +0.0625 | yes | 0.75 | yes |
| `crosswalk` | 1/16 | **0.0625** | [0.011, 0.283] | 0.0625 | 0.12 | -0.0575 | yes | -- | -- |

**The DESIGN's quoted reference values do not match MA-1's published row.**
`research/20260829/model-a-stream-1/RESULTS.md` 2 reports the probe as
`sidewalk 0.75, lamppost 0.44, bench 0.19, crosswalk 0.12, planter 0.06`; the
DESIGN quotes `sidewalk ~ 0.75, lamppost ~ 0.6, bench ~ 0.0`. The criterion is
FROZEN and is not moved here, so both comparisons are reported:

* **against MA-1's published row: 5 / 5 targets within +- 0.15** (largest
  |delta| 0.065). The frozen block is reproduced.
* **against the DESIGN's quoted values: 2 / 3 within +- 0.15.** `lamppost`
  misses at |0.375 - 0.6| = 0.225 — the whole of that miss is the 0.44 -> 0.6
  transcription gap; against 0.44 the delta is -0.065.

**But the hypothesis's *conclusion* does not follow, and that is the real
finding here.** H-NG1c reasoned that reproducing the frozen block would make
"the generated scenes' 4.5 % a geometry effect". The frozen block reproduces —
and the generated scenes come out **easier, not harder**: 0.6511 strict success
on 450 generated episodes against 0.2750 (22/80) on the frozen-block episodes
with the identical recipe — +37.61 points, `results.json` ->
`frozen_block_summary_A0`, `tables.md` 6.2. On this corpus the generated
geometry is not what makes the navigator fail.

## 7. Supporting rows

### 7.1 Per target, generated block, commissioned arm

| target | strict | rate | 95 % CI | band entry | top failure reasons |
|---|---|---|---|---|---|
| `bench` | 65/90 | 0.7222 | [0.622, 0.804] | 0.8222 | `semantic_target_unreachable` x22, `navigation_no_progress` x3 |
| `lamppost` | 75/90 | 0.8333 | [0.743, 0.896] | 0.8333 | `navigation_no_progress` x8, `semantic_target_unreachable` x7 |
| `planter` | 63/90 | 0.7000 | [0.599, 0.785] | 0.7333 | `navigation_no_progress` x14, `semantic_target_unreachable` x10, `arrived_verified` x2 |
| `sidewalk` | 84/90 | 0.9333 | [0.862, 0.969] | 0.9333 | `semantic_target_unreachable` x5, `navigation_no_progress` x1 |
| `crosswalk` | 6/90 | 0.0667 | [0.031, 0.138] | 0.1222 | `navigation_no_progress` x42, `arrived` x42 |

### 7.2 Goal-band clearance vs outcome (commissioned arm, generated block)

| best standable clearance inside the goal band | episodes | strict success rate |
|---|---|---|
| 1.00-2.00 m | 276 | 0.7572 |
| >=2.00 m | 174 | 0.4828 |

The >= 2.00 m bucket scores *worse* than the 1.00-2.00 m bucket because it is
where `crosswalk` lives (its region's best band clearance is ~4.16 m): the
failures there are the POI-table failures of section 5, not clearance failures.

### 7.2b Is `semantic_target_unreachable` an inflation effect?

| quantity | value |
|---|---|
| live planner inflation, centre-to-surface (m) | 1.0223 |
| band surface clearance the planner therefore demands (m) | 0.7023 |
| `semantic_target_unreachable` episodes | 49 |
| their goal-band best clearance, min (m) | 1.0 |
| their goal-band best clearance, median (m) | 1.4238 |
| of those, below the planner's demand | 0 |
| all 450 episodes: goal-band best clearance, min (m) | 1.0 |
| all 450 episodes: below the planner's demand | 0 |

`semantic_target_unreachable` (44 strict failures, the largest non-grounding
class) is therefore **not** an inflation effect on this corpus: not one of
those episodes has a goal band the commissioned planner could not stand in.
Its cause is elsewhere in the ladder and is not attributed by this probe.

For scale: across the 30 generated scenes, the median fraction of the start
rectangle where the body does not fit is **0.000** (max 0.008), and the median
fraction inside the 0.65 m stop band is **0.0086** (max 0.0402). These are open
scenes.

### 7.3 Reconciliation with MA-1's 4.5 %

| quantity | value |
|---|---|
| episodes | 450 |
| strict success, 1800-step budget | 0.6511 |
| band entry, 1800-step budget | 0.6889 |
| band entry within MA-1's 420-frame per-goal budget | 0.6778 |
| median steps | 170 |
| MA-1 held-out teacher SR | 0.045 |

**This probe does not reproduce MA-1's 4.5 %, and the gap is not the step
budget.** Truncating to MA-1's 420-frame per-goal budget moves band entry only
0.6889 -> 0.6778, and the median successful episode finishes in 170 steps.

### 7.3a CORRECTION — the episode-script attribution is WITHDRAWN

The first revision of this section attributed the remaining ~60 points to
MA-1's episode script (interruption / re-targeting / cue handling). **That
attribution is withdrawn.** Fable's adversarial panel (`VERDICT.md` 5.1,
confidence 0.93) refuted it by reading MA-1's saved rows
(`~/.cache/parcel-0e/ma1/data/held_meta.json`, `held.npz`) rather than
re-simulating, and the reasoning holds:

* **The two predicates are not the same, and this file said they were.**
  NAV-GEN-1's `strict_success` is `inside_strict AND terminal command zero` on
  a single frame; MA-1's `arrived` is `inside AND oracle_stop_run >= 5`
  (`closed_loop_core.py:256-267`, `ORACLE_SETTLE_FRAMES = 5`,
  `teacher.py:291`). Calling mine "MA-1's truth oracle" was inaccurate and is
  corrected in section 3.
* **MA-1's loop cannot observe its own settle.** `goal_over = arrived or
  nav_dead or ...` ends the goal one frame after `teacher.nav.done()`
  (`closed_loop_core.py:347-349, 357-375`). In **133/133** plain held episodes
  where the navigator declared arrival, the episode ended one frame later, so
  the 5-frame settle could never accumulate and **none** scored as an oracle
  success.
* **Removing the script recovers nothing.** Plain-only teacher SR under MA-1's
  own predicate is 11/200 = 0.055 strict against 155/200 = 0.775 band entry;
  plain episodes with no stop/owner cue score 2/168 = 0.012. All 11 plain
  strict successes had `teacher_arrived_frame = -1` and 9/11 carried a cue —
  the cues *raised* MA-1's strict SR by freezing the command inside the band.

**So MA-1's 0.045 is a gold-predicate artefact, not a behaviour gap**, and
nothing in it is attributable to the episode script or to the generated
geometry. MA-1's informative row was always band entry. A residual remains and
is NOT explained here: NAV-GEN-1's predicate applied to MA-1's per-frame rows
gives **150/200 = 0.750** on MA-1's held geometry against this probe's 0.651
[0.606, 0.694] — different episodes and a different target mix, uninvestigated.

Section 6's conclusion is unaffected: it rests on this probe's own
frozen-block-vs-generated comparison (0.2750 = 22/80 vs 0.6511 = 293/450, one
recipe, one predicate; `frozen_block_summary_A0`), not on MA-1's number.

## 8. Determinism, host, and cost

* **Determinism: PROVED.** The commissioned arm was run twice over all 530
  episodes and the two row sets are **byte-identical** (`a0_repeat_identical:
  true`, `results.json` -> `determinism`). Per-episode results are also
  independent of worker assignment: the world's LiDAR RNG is reseeded before
  every episode, and the headless world requests a zero-noise scan, so the
  stream is never drawn from at all.
* **Plumbing control: PROVED.** A0 (the repo config file) and A0c (a scratch
  copy at the commissioned value) are identical row for row.
* **Scale.** Sweep A: 6 arms x 530 episodes = 3 180 episodes, 530.4 s wall.
  A0 repeat: 530 episodes. Sweep B: 4 arms x 450 = 1 800 episodes, 236.6 s.
  Total **5 510 episodes**. (`results.json` -> `run_provenance.wall_s`.)
* **Host.** The four snapshots are the table in section 0 and `tables.md` 8.1,
  rendered from the artifacts: sweep A `12.94 / 23.51 / 16.13` -> `3.95 / 12.86
  / 17.14`; sweep B `2.91 / 10.08 / 15.73` -> `15.04 / 23.44 / 21.07`. 192 CPUs;
  each worker pinned to one BLAS thread. **The worker count is not recorded in
  any artifact of these runs** (see section 0); `run.py` records it from now on.
  A foreign session (`model-b-contract-2`, `--threads 32`) shared the host for
  part of the run.
* **Cost: $0.** No GPU work, no hosted call, no model server, no token spend.

## 9. What this does NOT prove

1. **Nothing about a robot.** Evidence tier `desktop-sim`: kinematic base
   motion advanced with `mj_forward`, an occlusion-true raycast LiDAR with no
   added noise, and the oracle semantic source. Physical motion stays
   **NO-GO**; no clearance value measured here is a stopping proof on hardware.
2. **It does not reproduce MA-1's episode script, and it does not explain
   MA-1's 4.5 %.** MA-1 scored the LAST goal of a scripted multi-goal episode
   (60 % plain / 20 % revise / 20 % queue) under a 420-frame per-goal budget,
   with stop and owner-speaking cues; this probe runs one plain directive per
   episode under the harness's own 1800-step budget. Section 7.3 measures that
   difference, and **section 7.3a withdraws the attribution this file first
   drew from it**: MA-1's 0.045 is a gold-predicate artefact, so it is not a
   behaviour number this probe — or anyone — should be reconciling against.
   A ~10-point residual between the two corpora under a common predicate
   (0.750 on MA-1's held geometry vs 0.651 here) is left uninvestigated.
3. **The frozen-block control is a reconstruction, not a replay.** MA-1's
   pre-generation probe code is not in the repo; only its numbers are. The
   control set uses MA-1's own start-pose sampler on the same block with the
   same episode count, but not MA-1's RNG stream, so an exact match was never
   available to this probe.
4. **The sweep stops at the architectural floor.** H-NG1b's 0.20 m is
   unreachable through the config store (section 2.3): the floor of the key
   that moves the planner is an inflation of 0.5842 m. The interval
   0.5842 -> 0.20 m is unmeasured here.
5. **One target vocabulary, one scene generator, one venue.** Five demonstrable
   targets on `evals.nav_instruct.scene_gen` city-block variants. `tree` and
   `door` were already out of MA-1's vocabulary and are out of this one.
6. **`semantic_source: oracle`.** Candidates come from the simulator's ground
   truth, not from a learned map. NAV-CORE measured a very different picture
   off-oracle (arm A 0/60); nothing here contradicts or replaces that.
7. **No verdict.** `VERDICT.md` is Fable's; this file records what ran.
