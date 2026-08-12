# Card Y-3 — additive yield tier: pre-registered two-stage measurement

**Verdict: STOP-AND-REPORT.** Stage A confirmed the premise; Stage B missed
every registered threshold on `pedestrian_oncoming_group` and missed the band
floor on `pedestrian_group_wide`. Nothing was retuned to recover them. The
V1-regression arm passed. The `yield_aside` flag stays code-default OFF and this
lane does not recommend flipping it.

* Report (landed, own namespace): `evals/companion_nav/results/yield-ext-20260811175456Z-bd950c37.json`
* Ledger (own file): `evals/companion_nav/results/yield-ext-ledger.jsonl`
* `evals/companion_nav/results/ledger.jsonl` and every `follow-bench-v1-*.json`:
  **untouched** (`git status` shows the two `yield-ext-*` paths as the only
  additions under `results/`).

---

## 1. What the tier is

`FOLLOW_BENCH_YIELD_EXT` (appended to `evals/companion_nav/scenarios.py`; the
`FOLLOW_BENCH_V1` tuple above it is byte-untouched) plus
`evals/companion_nav/run_follow_bench_yield.py`, a separate CLI with its own
suite id (`follow-bench-yield-ext`), its own report prefix (`yield-ext-`) and
its own ledger. One invocation runs all three arms so a Stage-B number can
never be recorded without the Stage-A baseline beside it.

Both cells live in the open block east of x = 8 m; every lane they use was
checked against `truth_minimum_clearance` (the harness re-runs that check on
every invocation, because `tests/test_follow_bench_v1.py`'s scenario-table
validation covers `FOLLOW_BENCH_V1` only and this card does not own that file
— **handoff**, §6).

---

## 2. STAGE A — flag OFF (recorded before any flag-on number was read)

| cell | band | min ped surface | stance vs swept corridor | dwell | intimate | gate stops | collisions |
|---|---|---|---|---|---|---|---|
| `pedestrian_oncoming_group` | **0.5040** | −0.4681 m | **−0.1481 m (INSIDE)** | 7.7 s | 3.1 s | 1 | 1 (pedestrian contact) |
| `pedestrian_group_wide` | **1.0000** | 2.0206 m | +2.3217 m (outside) | 0.0 s | 0.0 s | 0 | 0 |

**Stage-A premise: CONFIRMED for the oncoming cell.** The registered condition
was "stance inside the group's swept corridor at closest approach, band < 0.60".
Measured: band 0.5040 < 0.60, stance 0.1481 m *inside* the corridor. So the cell
does exhibit the displacement failure the tier exists to test, and no redesign
was authorized or performed.

**Pre-registration, fixed at this point:** the Stage-B floor for the oncoming
cell is `0.5040 + 0.15 = 0.6540`. It is computed inside the harness from the
Stage-A arm of the same run, so it cannot be back-fitted; the same number is
written into the scenario's `min_band_fraction` (0.654) with the derivation in
a comment.

`pedestrian_group_wide` at band **1.0000** is the positive control for the whole
`pedestrian_group` infeasibility argument: same controller, same group, gap
widened to 5.0 m so the robot's stranger clearance is ~2.3 m — just over the
derived 2.24 m that band pace needs. See `YIELD_DESIGN_RECORD.md` §2.

---

## 3. STAGE B — flag ON

| cell | band (A -> B) | min ped surface (A -> B) | max owner distance (A -> B) | jerk (A -> B) |
|---|---|---|---|---|
| `pedestrian_oncoming_group` | 0.5040 -> **0.5040** (bit-identical) | −0.4681 -> −0.4681 | 5.8027 -> 5.8027 | 0.6503 -> 0.6503 |
| `pedestrian_group_wide` | 1.0000 -> **0.5240** | 2.0206 -> 2.0933 | 2.9957 -> **4.1276** | 0.2363 -> **1.0298** |

Seven registered misses, as emitted by the harness:

1. `pedestrian_oncoming_group` band 0.504 < 0.654 (Stage-A + 0.15)
2. `pedestrian_oncoming_group` stance corridor clearance −0.1481 < 1.2
3. `pedestrian_group_wide` band 0.524 < 0.75
4. `pedestrian_oncoming_group` `hard_collision_count` 1
5. `pedestrian_oncoming_group` `pedestrian_contact_count` 1
6. `pedestrian_oncoming_group` `intimate_space_time_s` 3.1
7. `pedestrian_oncoming_group` `min_pedestrian_surface_m` −0.468 < 1.2

Misses 4–7 are **identical in Stage A** — they are properties of the geometry
with a fail-closed robot, not damage the flag did. Miss 3 IS damage the flag
did, and it is the important one.

### 3.1 Per-step attribution (mandatory on a miss)

Measured by replaying every proposer call of the flag-on episodes and
re-classifying the candidate set (scratch diagnostic, no writes):

**`pedestrian_oncoming_group` — the proposer was ACTIVE on 0 of 250 steps.**
Of the 176 steps where it ran at all (the rest are pre-acquisition / no-track
steps), the outcome distribution is:

| outcome | steps | mechanism |
|---|---|---|
| baseline outside the comfort band | 62 | nothing to yield from yet — the group is still beyond `person_slow_m` |
| ALL candidates rejected by the **stall guard** | **65** | the robot lags 2.6–2.9 m; no admissible rotation keeps \|robot−aim\| above the hold ring |
| ALL candidates rejected by the **person-stop reject** | 32 | the group's swept corridor covers every reachable stance; no candidate holds 1.2 m over the horizon |
| candidates admissible but below the improvement quantum | 17 | the aside would buy < 0.10 m |

Candidate-level tally over the episode: 902 stall-guard rejections, 456
person-stop rejections, 238 below-quantum.

**`pedestrian_group_wide` — ACTIVE on 84 of 250 proposer steps** (124 of 250
episode steps report `yield_aside` as the decision reason), always at or near
the maximum 1.26 m offset, and that is exactly what cost the band.

### 3.2 The mechanism, stated plainly

This is the finding of the lane, and it is structural rather than a tuning
miss. Under the shipped geometry the rotated-aim proposal has a closed-loop
fixed point (`yield_aside.YieldAsideLimits.equilibrium_floor_m`)

```
r_eq(theta) = D cos(theta) + sqrt((D + deadband)^2 - D^2 sin^2(theta))
            in [2.946, 3.880] m   for D = 1.85, deadband = 0.18, offset <= 1.26
```

and the lagging-regime stall guard makes a candidate admissible only when the
robot already lags more than about 2.95 m. The follow band's upper edge is
**3.0 m**. So:

* **inside the band** (lag <= 2.03 m, and up to ~2.95 m) every rotation is
  stall-guard-inadmissible — which is why the oncoming cell never engages while
  the robot still has the band to lose;
* **once engaged**, the aside parks the robot at 2.95–3.88 m from the owner —
  outside the band — which is why `pedestrian_group_wide` falls from 1.0000 to
  0.5240 and its maximum owner distance grows 2.9957 -> 4.1276 m.

The rotated-aim formulation cannot displace the robot laterally *and* keep it
in the band: preserving the distance law about the owner is exactly what pushes
the equilibrium out. The two skeptic-mandated clauses did not cause this — they
exposed it; without the stall guard the same geometry would have frozen a
lagging chase instead (proven able to fail in `tests/test_yield_aside.py`).

### 3.3 What did NOT go wrong

* No collision the flag caused: `hard_collision` and `pedestrian_contact` in the
  oncoming cell are bit-identical between the arms.
* No safety erosion where the aside DID engage: `pedestrian_group_wide`'s
  minimum pedestrian surface IMPROVED (2.0206 -> 2.0933) and its stance stayed
  2.28 m clear of the swept corridor. The proposer traded band for clearance,
  which is the trade it was built to make; the trade is simply not the one the
  band gate wanted.

---

## 4. V1 REGRESSION — flag ON, all eleven cells: PASS

| cell | band (flag ON) | committed dd2e857 row | min ped surface (ON) | reference |
|---|---|---|---|---|
| straight_follow | 1.0 | 1.0 | — | — |
| follow_turn_corner | 0.49583333333333335 | same | — | — |
| owner_stops | 1.0 | 1.0 | — | — |
| **pedestrian_group** | **0.580** | 0.584 (−0.004, within 0.01) | **1.6221** | 1.4336 (improved) |
| doorway_gap | 1.0 | 1.0 | — | — |
| **pedestrian_cut_in** | 0.525 | 0.525 | **1.4346** | 1.4074 (improved) |
| navigate_crossing_ped | — | — | 0.5299999999999998 | unchanged |
| owner_turn_90 | 0.9529411764705882 | same | — | — |
| pedestrian_cut_in_predictive | 0.7153846153846154 | same | 0.818256373512604 | unchanged |
| owner_corner_loss | 0.10588235294117647 | same | — | — |
| navigate_near_wall | — | — | — | — |

* aggregate `min_pedestrian_surface_m` **0.5299999999999998** — UNCHANGED
* `personal_space_time_total_s` **2.3** — at the ceiling, not above it
* hard collisions **0**
* no episode band below its reference by more than 0.01; no per-episode
  pedestrian-surface decrease

So even if the flag were switched on today it would not move the frozen suite
outside the registered tolerances. That is not a recommendation to switch it on
(§3.2 is).

---

## 5. Files

* `evals/companion_nav/scenarios.py` — APPEND-ONLY: `FOLLOW_BENCH_YIELD_EXT` +
  `yield_ext_scenario_by_id`. `FOLLOW_BENCH_V1` byte-untouched (verified by
  `git diff`: the only hunk is at the end of the file).
* `evals/companion_nav/run_follow_bench_yield.py` — NEW.
* `evals/companion_nav/results/yield-ext-20260811175456Z-bd950c37.json`,
  `evals/companion_nav/results/yield-ext-ledger.jsonl` — NEW, own namespace.
* `scrum/20260811/task_1/Y-3_STATUS.md` — this file.

---

## 6. `does_not_prove` / handoffs

* **Scripted pedestrians never yield.** The oncoming cell's
  `pedestrian_contact` is a scripted capsule walking through a fail-closed
  stopped robot. A reactive human would not produce it, and the number should
  not be read as "the robot hit someone".
* **One geometry each.** Two cells, one seed each, measured once per arm. This
  is a mechanism probe, not a distribution.
* **The engagement histogram is a scratch diagnostic**, not a report field:
  recording it properly needs a `yield_active` column on
  `metrics.StepRecord`, and this card owns neither `metrics.py` nor
  `runner.py`'s record path. **Handoff:** fold yield telemetry into
  `StepRecord` under whichever card next owns `metrics.py`.
* **Scenario-table validation.** The new tuple is validated by the harness at
  run time, not by `tests/test_follow_bench_v1.py`, which this card does not
  own. **Handoff:** extend that test's free-space sweep to
  `FOLLOW_BENCH_YIELD_EXT`.
* **Nothing here is evidence about the reactive gate's multi-stranger
  behaviour.** Its people list is still one stranger scalar plus the owner; the
  all-tracks rejection lives in the proposer (`tests/test_yield_aside.py`).
* **No claim about real robots or real sensing** — headless kinematic base,
  oracle owner track, raycast LiDAR, no curbs or drops.
