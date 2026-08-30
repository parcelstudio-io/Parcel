# NAV-GEN-1 — VERDICT (verifier: Fable / parcel-0e, 2026-08-29 21:1x EDT)

Executor: Opus (bounded; 180 tool calls; ~50 min; $0; 5,510 headless
episodes, zero collisions in every arm). DESIGN frozen 20:13; no criterion
moved. Status: **VERIFIED — H-NG1a REFUTED as written (all grounding failures are
one product defect), H-NG1b REFUTED (clearance is not the lever), H-NG1c
reproduced against MA-1's row with its conclusion inverted. The executor's
§7.3 attribution of MA-1's 4.5 % to the episode script is REFUTED by the
panel (§5.1): it is a gold-predicate artefact. Commissioned arm reproduced
row-for-row in scratch (530/530).**

## 1. What I checked myself

| check | where | result |
|---|---|---|
| The 0.32 m floor is a code constant | `src/parcel_robot/robot_profile.py:37` `footprint_radius_m: float = 0.32` (Go2 profile → `DEFAULT_SAFETY_ENVELOPE`); `ClearanceProfile._non_negative(planner_hard_margin_m)` | confirmed; the DESIGN's "down to 0.20 m" needs a `src/` edit; recording it was the faithful move |
| The planner is commissioned from the brake, not from `grid.yaml` | `src/parcel_robot/navigation/pipeline.py:1108-1120` `_create_navigator` → `options["map_gate_clearance_m"] = self._planner_gate_ring_m()`; `:1085-1096` docstring: "the ring THIS navigator's own brake enforces … `safety.stop_distance_m`, 0.8 m … a STRICTER authority than the runtime reactive gate's 0.65 m" (card A2, fix 3) | confirmed at the code level; A2 moved the authority after NAV-CORE, so NAV-CORE's "planner 0.42 m" describes the pre-A2 stack |
| `crosswalk_a` is a hardcoded demo POI | `configs/navigation/cities/demo_pois.yaml:38-42` `id: crosswalk_a`, names `crosswalk`, `crosswalk near coffee` | confirmed; whether the grounder consults it before scene semantics on generated scenes is checked by the panel |
| The DESIGN's H-NG1c reference values | DESIGN.md:41-43 quotes `lamppost ≈ 0.6, bench ≈ 0.0`; MA-1 RESULTS.md §2 publishes `lamppost 0.44, bench 0.19` | **my transcription error in the pre-registration**; the executor reported both comparisons and moved nothing — correct handling |
| MA-1's 4.5 % vs this probe's 65 % | MA-1 RESULTS.md §2 row (teacher SR 0.045, any-arrival 0.65); A1 gold = inside region AND stopped ≥ 5 frames | different predicates; the panel (§5.1) then showed MA-1's 0.045 is a **harness artefact**, not a script effect — see §5.1 |

### 1.1 Structural confirmation by the integrator (parcel-fb, read-only, 21:1x)

parcel-fb independently walked both product claims and concurs on structure
(counts remain NAV-GEN-1's, not re-run):
- **POI second oracle:** `navigation/grounder.py:11-27` — `PlaceGrounder`
  fires BEFORE semantic search, four `demo_pois.yaml` class names including
  "crosswalk" → a hardcoded coordinate with `goal_source: known_poi`, no
  perception consulted; `demo_pois.yaml:38-46` `crosswalk_a` at (3.5, −0.6);
  `selection.py:182-192` `poi_grounding_enabled` is True iff
  `semantic_source == oracle`; `configs/navigation/default.yaml:99`
  `semantic_source: oracle` and `prototype.yaml` does not override it
  (`admission.py:917` names it "the shipped oracle default"). So on any
  generated scene "the crosswalk" grounds to the demo point regardless of the
  scene's crosswalks; 42/90 false arrivals follow structurally.
- **Margin inert in effect, not unread:** `pipeline.py:1108-1120` commissions
  the grid planner with the brake ring; `grid_navigator.py:285/307` passes
  BOTH `safety_margin_m` and the ring into `GridPlannerConfig`;
  `grid_planner.py:278-298` documents `inflation_radius_m` as a max against
  the gate's lateral demand (with a seed-detector refusal if the max is
  deleted). At a 1.02 m ring vs 0.32 + 0.10 m the margin is read but cannot
  bind. NAV-CORE's "0.42 m" is the un-commissioned legacy value
  (`grid_navigator.py:42-47`), pre-A2. I adopt "inert in effect".

## 2. Reading of the pre-registered criteria (pending §5)

**H-NG1a — REFUTED as written, and the refutation is the finding.** Clause 1
(termination/clearance coverage ≥ 0.70) reads 0.4459; clause 2 (grounding
< 0.15) reads 0.535 and fires the ≥ 0.30 refutation. All 84 grounding-class
failures are one defect: on generated scenes "the crosswalk" is answered by the
demo POI table (`crosswalk_a` at [3.5, −0.6]) instead of the scene's crosswalk
region, so 42/90 crosswalk episodes are **false arrivals** (arrived, median
3.25 m from any crosswalk, worst 7.17 m) and 42 stall on the way to the wrong
point. Excluding that target, coverage is 0.7808 and grounding 0.000 — both
bars met. My call on the sensitivity row: `navigation_no_progress` (the
progress watchdog with the route still planned, NAV-CORE's stall class) IS a
termination-class failure for the purpose the hypothesis was asking about
(is the navigator failing to *stop correctly* or to *know where to go*), so
the honest headline is: **on four of five targets the navigator's failures are
termination/stall (0.96), not grounding; on the fifth target every failure is a
second-oracle grounding defect the product already warns about in
`configs/navigation/default.yaml`'s `semantic_source` comment.**

**H-NG1b — REFUTED.** +2.00 points at best (bar ≥ 20). Two facts underneath:
(1) the config key the DESIGN named is inert on the shipped profile — the
planner's inflation is 1.0223 m from the brake ring, and six margin values
return byte-identical rows; (2) the key that does move it
(`safety.stop_distance_m`, 0.80 → 0.32; inflation 1.02 → 0.58 m) buys two
points because **no goal band in 450 episodes is one the commissioned planner
cannot stand in** (min best-standable clearance 1.00 m vs demand 0.70 m).
Clearance is not the binding constraint on this corpus; what the sweep buys is
more episodes ending inside the 0.65 m stop band (1 → 18). The NAV-CORE
finding ("map_safety_margin_m 0.45 recovered stalls") predates A2 and does not
transfer to the shipped stack.

**H-NG1c — reproduced against the true reference (5/5 within ± 0.15 of MA-1's
row; 2/3 against my mis-transcribed values), and its conclusion inverted:**
generated scenes are *easier* (0.6511 strict) than the frozen block (0.2750);
the geometry is not what makes the navigator fail.

## 3. What it establishes for the research question

1. **The "4.5 % on unseen geometry" I carried in the wave report was
   wrong twice over.** Single-directive navigation on generated geometry
   succeeds ~0.65 (band entry 0.69; MA-1's own plain-episode band entry is
   0.775, and NAV-GEN-1's predicate applied to MA-1's saved frames gives
   0.750). MA-1's 0.045 is **not a measurement of navigation success**: its
   A1 gold requires 5 stopped frames inside the band, and its loop breaks
   one frame after the navigator's own `done()` (133/133 plain arrivals),
   so the settle is never observable; the only episodes that ever passed
   were ones a stop/owner cue happened to freeze inside the band. The
   executor's "the gap is the interruption script" is refuted (§5.1). What
   survives: the geometry is not the problem, and neither is clearance.
2. **Two product defects with exact locations:** the second-oracle POI
   lookup answering scene-relative place names on any scene that is not the
   demo block (false arrivals, the worst class the wave has: the robot
   *announces* success 7 m from the target); and the stale NAV-CORE
   clearance story — the shipped planner inflates 1.02 m, not 0.42 m.
3. **Clearance tuning is not the lever.** The lever is termination and the
   stall watchdog (68/157 failures) — an executive/arrival-authority problem,
   consistent with the 17/80 and 25/125 authority disagreements elsewhere.

## 4. Not proven / caveats

- `semantic_source: oracle` on every arm — semantic targets are ground truth;
  nothing here is perception. Zero collisions are kinematic-sim facts.
- One seed range (880000–880029), 30 scenes, 3 poses; the frozen-block
  control re-samples MA-1's poses (MA-1's probe code is not in the repo).
- "Strict" here is the harness's own status; MA-1's strict is a
  stopped-≥ 5-frames-in-region gold. Comparable only through band entry.
- The 0.20 m floor was not reached (code constant); the sweep spans what the
  config surface allows.
- No product edits; nothing fixed; the POI defect and the A2 authority are
  findings for the integrator, with file:line.

## 5. Adversarial panel + scratch reproduction (5 refuters, 1 reproducer, 1 critic; 21:1x–21:2x)

**Reproduction: 530/530 rows byte-identical.** A mirrored scratch copy
(`~/.cache/parcel-0e/ng1/verify_wf/`, `NG1_SCRATCH` env, no edits to the
copy) re-ran `--stage prepare` and the commissioned arm A0 on 16 workers
(329 s): scene manifest sha256 `b698e059…4ab43` identical; every row equal
to the executor's `rows_A0.json` under `json.dumps(sort_keys)`; derived
numbers recomputed with the folder's own `analyze.py` equal `results.json`
exactly. The executor's `--determinism` A0 repeat and A0c plumbing control
were also identical. The measurement is solid.

### 5.1 One attribution REFUTED (confidence 0.93): "MA-1's 4.5 % is the episode script"

The refuter read MA-1's saved rows (`~/.cache/parcel-0e/ma1/data/held_meta.json`,
`held.npz`) rather than re-simulating:
- The predicates differ: NAV-GEN-1 `strict_success = inside_strict AND
  terminal command zero on ONE frame` (`run.py:369-371`,
  `headless_city.py:118-121`); MA-1 `arrived = inside AND
  oracle_stop_run ≥ 5` (`closed_loop_core.py:256-267`,
  `ORACLE_SETTLE_FRAMES = 5`, `teacher.py:291`). NAV-GEN-1's text calling
  its predicate "MA-1's truth oracle" (`RESULTS.md:243`, `run.py:369-370`)
  is inaccurate.
- MA-1's loop **cannot observe the settle**: `goal_over = arrived or
  nav_dead or …` with `nav_dead` one frame after `teacher.nav.done()`
  (`closed_loop_core.py:347-349, 357-375`). In **133/133** plain held
  episodes where the navigator declared arrival, the episode ended one frame
  later; **none** is an oracle success.
- Plain-only teacher SR under MA-1's predicate: 11/200 = 0.055 strict,
  155/200 = 0.775 band entry; plain with no stop/owner cue: 2/168 = 0.012
  strict. **All 11 plain strict successes had `teacher_arrived_frame = −1`
  and 9/11 had a cue** — the cues *raised* MA-1's strict SR by freezing the
  command inside the band. Removing the script recovers nothing.
- NAV-GEN-1's predicate applied to MA-1's per-frame rows: **150/200 =
  0.750** on MA-1's held geometry vs NAV-GEN-1's 0.651 [0.606, 0.694] —
  a ~10-point residual on different episodes and target mixes, not
  investigated.
→ **Adopted.** MA-1's 0.045 is a gold-predicate artefact; RESULTS §7.3/§9.2's
"interruption / re-targeting / cue handling" attribution is withdrawn from
the wave verdict. Consequence for MA-1: its C-vs-T comparison stays
like-for-like (both scored under the same artefact), and its informative row
was always band entry (C 0.087 vs T 0.652); an erratum is added to
`model-a-stream-1/VERDICT_FABLE.md`.

### 5.2 Not refuted (4/5), with caveats adopted

- **crosswalk POI** (0.90): `parse('go to the crosswalk')` on the shipped
  config reproduces `GoalPose(3.5, −0.6, poi_id='crosswalk_a',
  goal_source='known_poi')` (`pipeline.py:1136-1147` grounder before
  semantic; `default.yaml:10/:99`). Caveats: it is **90/90** crosswalk
  episodes, not 84 — six are accidental strict "successes" (the robot
  stalled inside the real crosswalk en route to the wrong point); the
  *coordinate* does lie inside seed 880027's crosswalk polygon (the *id*
  never does) and still produced 2 false arrivals; the POI path also carries
  the looser 1.5 m point-goal arrive radius; conventional median DTG 3.17 m
  (3.25 is the upper-median convention); sweep-B arms show 39–41 false
  arrivals; raw rows do not log `goal_source`, so the attribution rests on
  `headless_city.py:757-760` + the parse reproduction.
- **gate ring** (0.96): kwargs win over the model file
  (`registry.py:56-62`); `grid_navigator.py:281-313` builds the config with
  both terms; the margin still feeds `comfort_radius_m`, inert because
  `comfort_cost_weight` defaults to 0 — "inert in effect" (parcel-fb's
  wording, §1.1). Caveats: `results.json` `arm_config_facts` for A0–A4 carry
  the OLD schema (config-only 0.42…0.32 with `map_gate_clearance_m: null`)
  while only B-arm rows carry `LIVE_planner_inflation_radius_m` — read
  literally they contradict the finding; a direct `GridNavigator` caller
  without the pipeline still gets the legacy 0.42 m; sweep B moves the
  runtime collision brake together with the ring by construction;
  `grid_planner.py` has an uncommitted working-tree diff not touching
  `inflation_radius_m`.
- **clearance not binding** (0.85): the 1.00 m figure is a truth-geometry
  best point over 72 × 5 band samples (150 (scene, target) pairs, replicated
  over poses), and for lamppost/planter 1.00 m is the band's own ceiling —
  only the "not below" half is informative; the planner's own LiDAR grid
  was not consulted. Sweep A has 5 distinct inflation values, all from
  `stop_distance_m`. **DESIGN's "without lowering minimum clearance below
  the stop band" is violated literally by every B arm (3/13/18/15 episodes
  < 0.65 m; A0 already has 1)** — H-NG1b fails on that clause too.
- **frozen block** (0.90): recomputed from raw rows; MA-1's probe recipe
  is unrecoverable, so "identical recipe" is proven only within NAV-GEN-1;
  n = 16 CIs contain both 0.44 and 0.6 for lamppost; 0.2750 is correct but
  prose-only; the blocks differ in failure *class* (frozen: 38/80
  `semantic_target_unreachable`), so "easier" is a rate statement.

### 5.3 Critic — moved/added and not established

Moved or added (all declared, none hidden): 0.20 m replaced by the 0.5842 m
floor; **sweep B on `safety.stop_distance_m`, a key the DESIGN did not name
and arguably one of the "stop bands" it said to hold fixed**; reason lists
widened (termination 3 → 8 names; grounding 5 + wrong-instance); "inside
2× band" operationalised as DTG ≤ band radius; post-hoc columns (excluding
crosswalk, any-instance, +`navigation_no_progress`) beside the bars; a
second H-NG1c reference; §7.3 reconciliation by elimination (now refuted).
Record defects: sweep-A start load 3.06/2.97/2.72 in RESULTS vs
12.94/23.51/16.13 in `results.json`; worker count stated 24/40 in
different places; a few prose numbers (3.25 m, 7.17 m, 0.2750) are not in
`results.json` despite README's "no number typed by hand".
Not established: anything off-oracle (`semantic_source: oracle` on every
arm; NAV-CORE's off-oracle 0/60 untouched); the cause of
`semantic_target_unreachable` (44 strict, 22 on bench — shown not to be
inflation, otherwise unattributed); whether the semantic ladder would have
grounded "crosswalk" had the POI table not fired; robustness beyond one
seed / 30 scenes / one generator; collision-counter sensitivity (no positive
control); the ~10-point MA-1-vs-NAV-GEN-1 residual.

**Final reading.** H-NG1a's answer, after the panel: on the four non-POI
targets the navigator's failures are stalls with the route still planned
(`navigation_no_progress`, 26 of 73) and `semantic_target_unreachable`
(44, unattributed) — neither is grounding, neither is clearance; on
`crosswalk` every episode is the POI second oracle. H-NG1b: clearance is not
the lever and the sweep also breaches the stop-band clause. H-NG1c: geometry
is not the problem. And the 4.5 % that motivated this probe was never a
navigation number.
