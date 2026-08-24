# H3 — drives and initiative · RESULTS (Opus) · 2026-08-24

Tree `0ec1d7c` (DEC-FS-1), working tree, **nothing committed**. Evidence tier
**desktop-sim** throughout. Hosted spend **$0.00** — no model, local or
hosted, is involved in this hypothesis.

## 1. What was run

```
# four arms x 3 seeds x 60 simulated minutes at 10 Hz, plus the two extra
# configurations rows D5 and D6 need (§2 deviation 4)
env -u TMPDIR .parcel/bin/python research/20260823/drives-and-initiative/run_h3.py \
    --duration-s 3600 --workers 6
# F4 probe: the same three night runs with the time-band withholding OFF
env -u TMPDIR .parcel/bin/python research/20260823/drives-and-initiative/run_h3.py \
    --duration-s 3600 --workers 3 --f4-probe
# D5/D6/D8 re-derived from the per-tick JSONL rather than from the summaries
env -u TMPDIR .parcel/bin/python research/20260823/drives-and-initiative/verify_log.py \
    <scratch>/h3/ticks_*.jsonl.gz
# capability test, both DEC ratchets, and the two product test files nearest
# the seams — every pytest through the mandatory wrapper, never `-n auto`
env -u TMPDIR ~/.cache/parcel-guard/pytest_guard.sh --label h3 \
    .parcel/bin/python -m pytest tests/test_h3_drives.py -q          # 15 passed
env -u TMPDIR ~/.cache/parcel-guard/pytest_guard.sh --label h3 \
    .parcel/bin/python -m pytest tests/test_dec0_debt_ratchet.py \
    tests/test_decig2_import_ratchet.py -q
env -u TMPDIR ~/.cache/parcel-guard/pytest_guard.sh --label h3 \
    .parcel/bin/python -m pytest tests/test_roam2_coverage.py \
    tests/test_curio1_chatter.py -q                                  # 86 passed
```

Environment: no GPU, no model server, no daemon, no socket. The arena builds
its own `HeadlessCityWorld` in-process; the owner's stack (`:8765`,
`/tmp/parcel_sim.sock`, `:8080`, `parcel_memory.sqlite3`) was never touched.
The host was heavily loaded throughout (load ~100 of 192 cores; H2's two
`llama-server` processes at 6333 % and 5898 % CPU). **Contention cannot move a
row here, and that is measured, not assumed**: two independent processes
re-ran the headline configuration (`radius6`, seed 1) and produced identical
command-stream digests — `command_sha 8f03fde5…`, `translation_sha d175a8e2…`,
max radius 7.157315136838721 m, 131 contacts — matching the batch run exactly.

## 2. What was built

Product seams — both inside the DESIGN's OWNS, both default-preserving:

| file | lines | what it is |
|---|---|---|
| `src/parcel_robot/attention/drives.py` | 585 | the pure drive model: `DriveState` (frozen, four drives in [0,1]), `DriveDynamics` (decay to a floor, rise from typed signals, satisfaction), `InitiativeDigest`, `InitiativePolicy` (**`travel_radius_m` default 0.0**), `InitiativeProposal`, `propose()` — bounded kinds `LOOK/APPROACH/REMARK/GO_CHECK/REST`, one drive row and one reason per proposal, every draw seeded from `(policy.seed, digest.at_s)`. No clock, no I/O, no authority. |
| `src/parcel_robot/patrol/coverage.py` | 271 | ROAM-2 handoff H2, made selectable: `CoverageSelection(min_candidate_distance_m=0.0, forward_bearing_weight=0.0, path_novelty_weight=0.0)` — **the defaults return `rows[0]`, exactly what today's consumer does** — plus `coverage_selection_from_config` (fails closed on a typo), a fail-open filter (emptying the candidate list degrades to today's row, never to "no objective"), and a tie-break that never reads `entry_id` (F9). |

Harness (research folder only): `arena.py` (venue + doors + executors +
per-tick JSONL), `run_h3.py` (arms, seeds, the D1–D8 table), `verify_log.py`.

**Every admission is an existing component, never a new authority.** `LOOK` →
`AwarenessSweep` + `awareness_yaw_permitted` (the R28 table), yaw-only by
construction; `REMARK` → `ChatterScheduler.due` from `realtime/whisperer.py`
(quiet window, night band, owner presence, Poisson cadence) plus the
admitted-name test; `GO_CHECK`/`APPROACH` →
`SkillContractRegistry.default(...).restricted(..., system_authored=True)` +
`compile_plan_sketch(sketch_navigate(...))` + `PlanValidator.validate`, then
`PatrolPolicy` with `travel_radius_m` as its ROAM-1 tether; every dispatched
command → `apply_reactive_safety` → `finalize_command`.

Deviations, all settled before the reported numbers were produced:

1. **The new stimulus kinds live in `drives.py`, not in `attention/stimuli.py`** —
   that file is not in this card's OWNS. `DriveSignalKind` carries
   `NOTICING/PERSON_SEEN/OWNER_TURN/BATTERY/IDLE_TIME`; `DriveSignal.from_stimulus`
   bridges the existing `StimulusKind` values.
2. **The annoyance budget is the one parameter taken from D1's own band.**
   `INITIATIVE_REFRACTORY_S = 600 s` ("at most one self-started behaviour per
   ten minutes") caps the rate at 6/h before any door refuses, so **D1 measures
   the rate realized through the doors, not a free-running drive rate**. Every
   other constant comes from the repo: curiosity half-life =
   `CuriosityConfig.mean_gap_s` (360 s); place-age floor =
   `PatrolLimits.coverage_min_age_s` (20 s); clearances from `limits_from_safety`;
   errand budget 240 s = a 6 m round trip at the patrol's 0.25 m/s cruise, at
   ROAM-1's measured path-to-displacement ratio.
3. **The arena's learned map uses `visibility_range_m = 4.0`, not the shipped
   8.0** — finding F5; both candidate counts are recorded in `results/*.json`.
4. **Two extra configurations**: `night` (radius-6 arm started at 21:30, so the
   second half is inside the NIGHT band) and `d5probe` (an owner turn pulled to
   +3 s after the first admitted initiative, an e-stop to +3 s after the
   second). The four arms run in the afternoon so D1's denominator is a full
   waking hour, and they report only the preemptions that happened on their own.
5. **The quiet window and the night band are applied as a WITHHOLDING at the
   initiative layer**, using the same `CuriosityConfig` fields and the same
   `time_band_of` the remark door uses — the DESIGN's own word for
   `quiet_s`/`night_quiet` is "withholding threshold". `--f4-probe` turns it off
   and measures what the product alone does (F4).
6. **Two earlier 18-run builds were discarded, not reported.** They were taken
   before F9 (the `entry_id` reproducibility defect) was found and are not
   replayable; every number below comes from the single deterministic build.

## 3. The pre-registered rows

| row | criterion | measured | met? |
|---|---|---|---|
| **D1** initiations/h by kind | 3–8 total, radius-6 arm | **5, 5, 6** per run (mean 5.33). Kinds across the arm: `look` 8, `go_check` 4, `remark` 4, `approach` 0 admitted, `rest` never proposed | **MET** |
| **D2** admitted fraction at the doors | ≥ 0.80 | **73/81 = 0.901**. One refusal reason in the whole program: `approach_no_skill_contract` (8) — F3 | **MET** |
| **D3** max radius from home; block visits | ≥ 6 m; fraction reported | radius-6 arm max **7.16 m**; per run **7.16 / 1.24 / 6.01 m** (2 of 3 ≥ 6 m). radius-10: 3.21 / 1.24 / **13.78 m**. baseline and look-remark **0.00 m** in every run. Blocks of 9 visited: 2/1/3 (radius-6), 4/1/6 (radius-10), 1/1/1 (baseline). Candidates per sample 11.4–12.0 | **MET** on the arm's max; **MISSED** on 1 of 3 runs, and seed 2 (1.24 m) fires the DESIGN's own refutation clause — F2 |
| **D4** contacts; min clearance to agents | 0; ≥ profile stop distance | **1222 contact episodes / 391 s**, of which **1213 with the dog stationary** and 9 while translating. Min clearance **0.00 m**; min clearance *while translating toward the agent* **1.00 m** (gate's `person_stop_m` 1.2). The baseline arm, which never moves at all: **0 contacts, min clearance 0.74 m**. Static: **0 collisions** in 18 runs, min clearance 0.50 m (`obstacle_stop_m` 0.65) | **MISSED** — F6 |
| **D5** preemption on owner speech / e-stop | ≤ 1 tick (0.1 s) | **22 events** (12 e-stops, 10 owner turns), **max 0 ticks (0.00 s)**, every command at yield exactly `(0,0,0)`. Behaviours had been running 0.1–222.9 s. Re-derived independently from the per-tick log | **MET** |
| **D6** initiations in quiet_s=90 or night | 0 | **0 and 0**, from the summaries and again from the log (84,583 ticks inside a quiet window and 54,000 inside the night band were withheld). With the withholding off, the same three runs admit **8 initiations inside the night band and 3 inside a quiet window** — F4 | **MET** |
| **D7** radius-0 arm changes navigation commands | 0 (byte-identical motion) | baseline vs look-remark **translation streams byte-identical**, sha `32df24f9…` across all six runs. Full streams differ by the LOOK yaw alone | **MET**, and see F1 |
| **D8** every initiation attributable to one drive | 100 % | **73/73 = 100 %** — and for all 73 the named drive is at or above the threshold in the same tick's **decision-time** feature vector, re-derived from the JSONL | **MET** |

Seven of eight met; D4 missed with a mechanism (F6), D3 met on the arm and
missed on one seed of three (F2).

## 4. Findings

**F1 — today's dog emits nothing at all, which is why D7 is easy.** The
baseline arm's dispatched command stream is 36,000 exact zeros in every run
(one sha across three seeds). No goal generator exists, the awareness sweep
ships OFF, roam is owner-commanded, and the curiosity door never fired because
nothing fed it a candidate. D7's "byte-identical" is therefore *trivially*
satisfied: the honest reading is that the radius-0 arm adds a yaw-only
behaviour to a body that was emitting nothing.

**F2 — `PatrolPolicy`'s `boxed_in` escape is unreachable under the shipped
limits (product defect).** `_turn` tests `turn_giveup_after_s` (12 s) *before*
applying `turn_flip_after_s` (4 s), and the flip **resets the same clock the
give-up reads**, so `turning_for` can never exceed 4 s. Pinned as a unit row in
`tests/test_h3_drives.py`: a permanently blocked lane yields `{turn_blocked}`
for the full 120 s budget and nothing else. Across the travel arms
`turn_blocked` is 2,443 patrol ticks against 7,972 of `advance` — a wedged dog
spins out its whole errand instead of ending the leg, which is what separates
seed 1 (7.16 m) from seed 2 (1.24 m). One-line fix, but it moves the
ROAM-1/ROAM-2 baselines, so it is a card and not a patch here.

**F3 — there is no admitted skill contract for approaching a person who is not
the owner.** All 8 `APPROACH` proposals were refused at the plan door:
`NavigateTo` takes a semantic place, `FollowFormation`/`OrbitOwner` take the
owner, `MoveRelative` takes a direction. This is the *only* refusal reason in
the program and the whole of D2's shortfall from 1.0. Either milestone 1 adds
an `ApproachEntity` contract with a standoff argument, or `APPROACH` leaves the
proposer's kind set — proposing it today buys refusals, not approaches (E2-D2).

**F4 — nothing in the product gates a discretionary *motion* by time of day.**
`night_quiet` and `quiet_s` live in the remark door only; the R28 table, the
plan validator and the reactive gate have no clock. Measured by
`--f4-probe`, which disables the initiative-layer withholding and changes
nothing else: the three night runs then admit **8 initiations inside the NIGHT
band and 3 inside a quiet window**, every one of them a `LOOK` or a `GO_CHECK`.
The band has to be read at the initiative layer, or a self-initiated errand
happens at 03:00.

**F5 — the coverage objective is starved by the map's own visibility rule.**
With the shipped `visibility_range_m = 8.0`, `coverage_candidates` returns
**1** row on `city_block` from home (the door, 8.08 m) because every other
entry is *inside* the visibility radius; at 4.0 m it returns **12**. ROAM-2
handoff H1 predicted this; H3 measures it. Any coverage objective on a
home-clustered map needs recency separated from visibility, a larger scene, or
a frontier over unexplored space rather than over known entries.

**F6 — a self-initiated errand has no return leg, and that is where every
contact comes from.** 1,213 of 1,222 contact episodes happened while the dog
was **stationary**: the errand's budget ran out, the dog stopped wherever it
stood — often inside a pedestrian route — and the crowd walked through it for
the rest of the hour. The baseline arm, which never moves, has 0 contacts *and*
a minimum clearance of 0.74 m, so the clearance half of D4 is violated by the
venue with zero initiative (`DynamicCity` agents do not avoid). The number that
separates the arms is the contact count, and its mechanism is a missing
terminal for an initiated leg: come home, or at least stand out of the way.
Secondary: the gate's `_toward` test (±1.15 rad of the travel bearing) does not
see a person closing from the side, which is the other 9.

**F7 — the consent radius and the candidate selection have to be co-designed.**
An earlier build selected the most interesting candidate and only then met
`travel_radius_m`, which refused the whole proposal. Bounding the candidate set
to places within the radius **of home** before ranking them is what made
`GO_CHECK` proposable at all; without it the arm produced roughly one errand an
hour instead of four.

**F8 — the doorstep is left, but not reliably.** Against ROAM-2's measured
~3 m net displacement, the radius-6 arm reaches 7.16 / 1.24 / 6.01 m and the
radius-10 arm 3.21 / 1.24 / 13.78 m, visiting up to 6 of 9 city blocks. The
spread is the finding: identical drive model, identical selection, three seeds,
an 11× range — because what a leg achieves is decided by whether the patrol
wedges (F2) in its first few metres.

**F9 — map entry ids are `uuid4`, so any consumer that tie-breaks on them is
not reproducible (product defect, and it bit this experiment).**
`OnlineSemanticMap` mints `entry_id = f"place-{uuid.uuid4().hex[:16]}"`, and
`coverage_candidates` sorts oldest-first with `entry_id` as its final
tie-break — then truncates to `limit`. Entries re-seen in the same 1 Hz frame
share a `last_seen_wall_s`, so those ties are common, and two processes running
the same seed选 different places. Two 18-run builds had to be discarded before
this was found. Fixed on this experiment's side (`patrol/coverage.py` breaks
ties on distance/bearing/surface point, never on the id; the arena asks for a
limit above the entry count) and pinned by a test. The map-side fix — a
content-derived id, or a geometric final tie-break inside
`coverage_candidates` — is a card; **ROAM-2's own measured rows have the same
exposure.**

## 5. Raw files

- `results/runs.json`, `results/rows.json` — the 18 runs and the D1–D8 table.
- `results/runs_f4probe.json` — the three night runs with the withholding off.
- `logs/ticks_radius6_seed1.jsonl.gz` — one full per-tick log (36,000 rows, the
  run that reached 7.16 m): `d0` (the drive vector the decision was made on),
  `d` (end of tick), `sig`, `p` (proposal), `v` (verdict), `a` (active kind),
  `cmd`, `gate`, `note`, `band`, `quiet`, `pose`, `ev`, `pre`. This is the
  Stage-B corpus shape `docs/ATTENTION_STEERING_DESIGN.md` asks for. The other
  17 logs stay in scratch.
- `arena.py`, `run_h3.py`, `verify_log.py` — the harness, reproducible from the
  repo with the command in §1.

## 6. What this does not prove

- **Nothing about a human's judgement of lifelikeness.** Five initiations an
  hour is a rate, not a personality; a rating study is a separate card.
- **Nothing about physical motion.** Base motion is kinematic (`mj_forward`) —
  no contact physics, no gait, no Go2.
- **Nothing about perception.** Semantic objects come from the scene's truth
  through the camera cone, not from a detector.
- **Nothing about the runtime.** The seams are reachable from the harness, not
  from `RobotRuntime`: nothing there constructs a `DriveState`, and
  `travel_radius_m` has no config key yet. Wiring is a milestone card.
- **Nothing about crowds.** `DynamicCity` agents are waypoint followers with no
  avoidance, which is why D4 is reported by attribution rather than as one
  number.

## 7. Cost

$0.00. No hosted call, no local model, no GPU second.
