# Terminal-aware continuous action — results

Date run: 2026-08-24

Design SHA-256: `1a32b273616617b166652a9c67ec25e081c14789ac1a59535fee430637cef517`

Evidence tier: deterministic desktop simulation

Hosted spend: **$0.00**

## Result in one sentence

The combined hypothesis is **refuted**: explicit returns reached home and the
combined proposed arm had no translating contact episodes without reducing
initiative or preemption, but stopping for predicted people and waiting until
the 240 s outbound budget ended did not make the occupied location safe.
Stationary contacts rose from **316 to 323**, while contact time rose from
**89.1 s to 244.6 s**.

## What ran

```text
env -u TMPDIR .parcel/bin/python \
  research/20260824/terminal-aware-continuous-action/run_experiment.py

.parcel/bin/python \
  research/20260824/terminal-aware-continuous-action/make_compact.py

.parcel/bin/ruff check \
  research/20260824/terminal-aware-continuous-action/run_experiment.py \
  research/20260824/terminal-aware-continuous-action/make_compact.py
```

Six runs were executed sequentially: H3 `radius6` and the proposed policy on
seeds 1, 2 and 3, each for 3,600 simulated seconds at 10 Hz. No model, network,
daemon, live robot process or product file was used or changed.

Raw aggregated evidence is in `results.json`; the complete review table is the
8.3 kB `results.compact.json`. No per-tick log was needed to calculate a row.

## Integrity controls

The comparison is valid. For every baseline seed, all six frozen values match
H3's canonical `results/runs.json` exactly:

- expressive initiative count;
- total, stationary and translating contact counts;
- full command-stream SHA-256;
- translation-only command-stream SHA-256.

The five-case geometry table also passed. Circle prediction selected front,
side and rear closing tracks (`TTC = 1.44 s` in each fixture) and rejected a
diverging and a static track. This verifies all-bearing selection, not safe
behavior after selection.

## Preregistered rows

| row | baseline | proposed | bar | result |
|---|---:|---:|---|---|
| TA1 stationary contact episodes | 316 | **323** (102.2%) | <= 5% of baseline | **FAIL** |
| TA2 all contact episodes | 319 | **323** (101.3%) | <= 10% of baseline | **FAIL** |
| TA3 translating contacts | 3 | **0** | <= baseline | PASS |
| TA4 expressive initiatives | 16 (`5/5/6`) | **16 (`5/5/6`)** | every seed nonzero; >= 80% pooled | PASS |
| TA5 preemption | — | 6 events; **0 tick max**, all exact zero | <= 1 tick and exact zero | PASS |
| TA6 natural terminals | — | **4/4 reached home**; all five terminal exits released exact zero | >= 90%; every terminal releases | PASS |
| TA7 contact time | 89.1 s | **244.6 s** (274.5%) | <= 10% of baseline | **FAIL** |

TA1, TA2, TA4, TA5 and TA6 were mandatory. Since TA1 and TA2 fail, the
headline result is false even though four other mechanism rows pass.

## Seed-level results

| seed | policy | initiatives | contacts (stationary / moving) | contact time | max radius |
|---:|---|---:|---:|---:|---:|
| 1 | H3 | 5 | 131 (129 / 2) | 65.3 s | 7.16 m |
| 1 | proposed | 5 | 128 (128 / 0) | **119.3 s** | 5.31 m |
| 2 | H3 | 5 | 183 (183 / 0) | 19.0 s | 1.24 m |
| 2 | proposed | 5 | 184 (184 / 0) | **110.2 s** | 1.41 m |
| 3 | H3 | 6 | 5 (4 / 1) | 4.8 s | 6.01 m |
| 3 | proposed | 6 | 11 (11 / 0) | **15.1 s** | 4.74 m |

Initiative was retained exactly, but useful translation was not: maximum
radius decreased on seeds 1 and 3. Initiative counts alone are therefore an
insufficient lifelikeness metric; an admitted action that spends its budget
stopped is not an accomplished action.

## Terminal and dynamic-join observations

Five terminals began and the policy returned an exact-zero command on every
release:

- four natural terminals reached `HOME` in **41.4, 29.0, 1.1 and 0.1 s**;
- one `RETURN_HOME` was interrupted by the preregistered owner turn after
  **3.0 s** and returned zero in the same tick;
- no terminal timed out and `STAND_ASIDE` was never entered.

The `release_command` value in each terminal summary is policy metadata written
by this same harness, not a separate gateway or actuator witness. For the one
terminal-specific preemption, TA5 independently reads the dispatched command
row and observes exact zero. Natural release rows were not independently
witnessed at an IPC, gateway or physical actuator boundary; TA6 demonstrates
the simulator policy's return value and lifecycle bookkeeping only.

The all-track join made **544 interventions**: 342 on seed 1, 4 on seed 2 and
198 on seed 3. The threatened actor was lateral on 305 ticks, rear on 146 and
front on 93. This directly verifies the H3 lateral blind spot: most predicted
risks were outside the old forward cone. It also demonstrates why detection is
not resolution. A stop-only response makes the robot stationary on the same
path as a non-avoiding scripted actor. The **combined arm** observed moving
contacts fall to zero while prolonged stationary overlap more than doubled
total contact time.

There is no terminal-only or TTC-only factorial arm. Therefore this experiment
cannot causally assign the moving-contact change—or any contact change—to one
component independently. The mechanism trace shows when the TTC join
intervened, but the effect estimate belongs to the bundled policy.

## Mechanism analysis

Three assumptions were wrong or incomplete.

1. **The terminal starts too late.** H3's travel action owns up to 240 s, and
   reactive safety can make it stationary during that outbound phase. The
   first proposed seed-1 contact occurs at 676.9 s, only 23.5 s after the
   action begins and 216.5 s before its terminal starts. Reserving no return
   time means `RETURN_HOME` cannot repair exposure incurred during execution.
2. **A dynamic veto is not a social trajectory planner.** All-bearing TTC
   correctly sees side and rear conflicts, but exact zero is not collision
   avoidance when the other actor does not avoid. Safe behavior requires a
   collision-free yield/shoulder trajectory derived jointly from static and
   dynamic occupancy; blindly generating an evasive velocity would be no
   safer and was correctly excluded from this design.
3. **Preemption and safe relocation are different authorities.** An owner turn
   or e-stop must remove initiative authority immediately. If that happens
   away from a safe hold region, the initiative layer cannot continue a return
   afterward. The new owner/safety action must explicitly decide `HOLD`,
   `FOLLOW`, or a supervised safe relocation. The action contract cannot
   secretly retain motion authority in order to clean up its pose.

The result also weakens H3's earlier wording that stationary contact is only a
post-budget missing-return problem. A substantial part can begin *while the
errand remains active but the final safety gate emits zero*. The missing
terminal is real, but it is not sufficient.

## Deviations and unexercised branches

The frozen first-return preemption probe overlapped `RETURN_HOME` only on seed
1. On seed 2 the relevant travel action was naturally preempted before a
terminal began; on seed 3 the first return reached home in 0.1 s, before the
event scheduled for +3 s. TA5 still has six measured zero-tick preemptions and
one is specifically a terminal, but terminal preemption has only one sample.

`STAND_ASIDE` was not exercised because all non-preempted returns reached home.
Nothing in this result validates its 16-sample shoulder selector. The full
`RETURN -> STAND_ASIDE -> RELEASE` chain is therefore not confirmed even
apart from the failed contact rows.

## What the next design must test

A follow-up should not tune this return controller. It should test a different
contract:

- admit an initiative only when there is a currently reachable safe-hold
  region and reserve time/energy to reach it;
- give the outbound phase a success/arrival condition, not only a 240 s clock;
- replan over predicted dynamic occupancy toward either the objective or a
  mapped safe-hold region; a stop is a short-lived control response, not a
  completed social yield;
- make `HOLD`, `RETURN`, `YIELD_ASIDE`, `FOLLOW_OWNER` and
  `RELEASE_AUTHORITY` explicit terminal outcomes with one authority owner;
- score useful progress and safe-hold occupancy in addition to initiative
  count;
- inject track delay, dropout, velocity noise and route-phase variation before
  considering a physical test.

That is the smallest credible continuous-action kernel for a proactive dog:
the controller may emit `HOLD` continuously, while autonomous translation is
always a bounded, interruptible action with a proved safe terminal.

## Evidence boundary

The result does not test physical braking, real person tracking, occlusion,
fall risk, terrain, gait, ROS/SDK latency or a human who reacts to the robot.
It is not sufficient for physical promotion. Its value is architectural: it
prevents the prototype plan from treating “add a return leg” or “check every
person track” as a complete safety solution.
