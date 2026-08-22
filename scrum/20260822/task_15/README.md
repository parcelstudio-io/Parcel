# Task 15 — HY-1: no test leaks a simulator

**Executor:** Claude Opus · **Verifier:** Fable · **Board:** `../TASK_BOARD.md`
(P0 standing rules apply). **Evidence:** Wave P0 verification note, "Hygiene
found on the way": `tests/test_voice_nav_e2e.py` (nightly) leaks
`parcel_robot.sim` processes when its setup errors — the verifier found and
killed **30 orphans** under pytest basetemps. Tonight's register also carries
two executor-leftover sims (MOVE-1's patrol sim, an R-17 probe) that outlived
their owners by hours and contended for the GPU during P0-C's timing rows.

## Why
Orphaned sims distort every latency measurement taken after them (P0-C's
bound was load-conditional: 98 ms idle vs 132–139 ms under load), occupy
sockets, and make "never kill processes you did not start" impossible to
honour safely. A leak that survives a setup error is a fixture bug.

## Work
1. `tests/test_voice_nav_e2e.py`: the sim launch moves into a fixture with a
   `finally`/`addfinalizer` teardown that terminates the process group (not
   just the child) and waits; setup errors tear down too. Seed RED: inject a
   setup error and assert zero `parcel_robot.sim` processes survive.
2. A shared `tests/_sim_guard.py` helper (session-scoped autouse) that
   records sim PIDs launched under pytest and reports any survivor at session
   end as a test failure with the leaking test's name — so the next leak is
   found by the suite, not by a verifier with `pgrep`.
3. Harness hygiene for executors: `scripts/launch_sim.sh` gains
   `--pidfile` so card harnesses can stop exactly what they started; the
   executor contract's "your last act is returning" gets a mechanical check
   (`tools/list_parcel_procs.py` — prints every `parcel_robot.*` process with
   start time, socket, and parent).

OWNS: `tests/test_voice_nav_e2e.py`, new `tests/_sim_guard.py` + its
`conftest.py` hook (one autouse fixture), `scripts/launch_sim.sh`
`--pidfile` region, `tools/list_parcel_procs.py`, `task_15/` docs.
MUST NOT TOUCH: `parcel_robot.sim` itself, other cards' tests, the owner's
live stack on `/tmp/parcel_sim.sock`.

## Definition of done
Seeded setup error leaves zero survivors; the guard reports a deliberately
leaked sim by test name; `HY1_STATUS.md`.
