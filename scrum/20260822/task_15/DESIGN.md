# HY-1 — design: no test leaks a simulator

## (a) Purpose

A pytest fixture that spawns a child process *before* the `try` that would tear
it down leaks that child on any setup error. `tests/test_voice_nav_e2e.py`
did exactly that: on 2026-08-22 it left **18** `parcel_robot.sim` processes
(≈15.3 GB resident, `~/.cache/parcel-hy1/evidence/census_before.txt`) alive on
pytest scratch sockets whose directories pytest had already deleted, and the
run reported "1 error". This card (1) fixes that fixture at its source, (2)
makes the suite itself notice the *next* leak and name it — test, pid, socket
— instead of a verifier with `pgrep`, and (3) gives executors two mechanical
tools so "stop what you started" is checkable: `scripts/launch_sim.sh
--pidfile` and the read-only census `tools/list_parcel_procs.py`.

## (b) Architecture fit

Everything here is **harness-side**. No file under `src/parcel_robot/` is
touched, nothing imports the product, and the guard sends a signal only to a
process it can prove *this* run started — so it composes with batch A's product
regions (VENUE-1 / CAP-1 / OT-2 / DOOR-1 in `runtime.py`) by not intersecting
them, and with the safety core (`core/hard_stop.finalize_command`,
`SafetySupervisor.validate`) the same way.

Seams:

* `tests/test_voice_nav_e2e.py:_LiveRuntime.__init__` — the defect. Everything
  after `subprocess.Popen` now runs inside `try/except BaseException`, whose
  handler calls the new `_LiveRuntime._stop_sim()` and re-raises.
  `_LiveRuntime.close()` (called by the `live` / `live_dynamic` fixtures'
  `finally`) delegates to the same `_stop_sim`, so success and failure exit
  through one teardown.
* `tests/_sim_guard.py` — the shared, stdlib-only process guard:
  `scan()`, `SimProcess`, `Ownership`, `started_by_this_run()`, `reap()`,
  `TestWindow`/`attribute()`, `format_report()`, `mode()`.
* `tests/conftest.py`, marked region `BEGIN HY-1 sim guard` … `END HY-1 sim
  guard` — `pytest_runtest_logstart/logfinish` (test windows) and the
  module-scoped autouse fixture `_hy1_sim_guard`. XD-1 (`task_14`) owns a
  **separate** region strictly below it (`BEGIN XD-1 repo-write census`); the
  two never interleave, and each is re-read before every edit (R11).
* `tools/list_parcel_procs.py:census()/render()` — the operator view, importing
  `tests/_sim_guard` so the predicate cannot drift from the guard's.
* `scripts/launch_sim.sh` — `--pidfile` parsing, preflight beside the socket
  checks, the write immediately after `SIM_PID=$!`, and `cleanup_pidfile` wired
  into the existing `cleanup()` trap.

## (c) Interfaces and contracts

* `PARCEL_SIM_GUARD` (`_sim_guard.GUARD_MODE_ENV`): `reap` (default) | `report`
  | `off`; an unrecognised value falls back to `reap`. A leak is a **test
  failure** in both `reap` and `report` — that is the card's definition of done,
  not a new fail-closed product default. `reap` additionally terminates the
  survivor so the *next* run starts clean; it never makes the run green.
* `started_by_this_run(proc, Ownership(session_root, pytest_pid, before))` —
  the whole safety argument in one pure function: False if `proc.key` (pid **and**
  `/proc` starttime, so a recycled pid cannot impersonate) is in `before`; False
  if `proc.is_owner_stack` (`/tmp/parcel_sim.sock` or `$PARCEL_SIM_SOCKET`);
  otherwise True only if the process descends from this pytest **or** its
  `--socket` is under this session's `basetemp`.
* `reap(proc, timeout_s=10.0) -> ReapResult` — re-reads `/proc` immediately
  before signalling and refuses on any argv/starttime mismatch; `killpg` only
  when the target leads its own group, else `os.kill`.
* `scripts/launch_sim.sh --pidfile PATH` — default empty (the owner's documented
  launch is byte-for-byte unchanged); refuses a path that names a *live* sim;
  removes the file on exit only when it still records this launch's pid.
* `tools/list_parcel_procs.py [--json]` — exit 0 always; **no** `--kill`, and
  no signalling call at all (pinned over its AST).

## (d) Data flow and lifecycle

No threads, no locks, no files written, no product import. Per test **file**:
one `/proc` scan at module setup, one at module teardown; per test, two
`time.time()` reads (`_HY1_WINDOWS`). Attribution maps a survivor's kernel start
time into a test window (±0.5 s for tick quantisation) and falls back to naming
the file. `reap` = SIGTERM → poll `/proc` for 10 s → SIGKILL. Module scope, not
session scope, so the report lands while the offending file is still on screen
and one leaky file does not indict every later one. Under `-n auto` each xdist
worker holds its own module state and its own `basetemp/popen-gwN`; a sim on a
sibling worker's socket is caught by the descendant test, not the path test.

## (e) Hardware compatibility — a PROCESS guard, not a sim guard

The seam is deliberately "a process this run started that is still running",
not "MuJoCo". `_sim_guard.py` and `tools/list_parcel_procs.py` import **stdlib
only** and read `/proc`, so both run unchanged on the Orin NX (aarch64,
JetPack, CPython 3.10) where MuJoCo is not installed: `os.sysconf("SC_CLK_TCK")`,
`/proc/stat` `btime`, `/proc/<pid>/{cmdline,stat,status}` are arch-independent
Linux, and `Path.is_relative_to` is 3.9+. `dataclass(frozen=True)` and
`str | None` annotations are 3.10-safe (`from __future__ import annotations`).

**Extension point (named, not implemented):** the predicate pair
`_sim_guard.is_parcel_sim(argv)` / `_sim_guard.socket_of(argv)` is the single
place that decides *what counts as a guarded process* and *what its endpoint
is*. A future card replaces the two with one table —

| pattern (argv token) | endpoint flag | why it must not leak |
|---|---|---|
| `parcel_robot.sim` (**implemented today**) | `--socket` | unix socket + ~840 MB |
| `parcel_robot.perception_daemon` (later) | `--socket` | holds the camera device |
| the native Go2 gateway on the Orin (later) | DDS domain id | holds the DDS participant; a leaked one silently steals `rt/utlidar/*` and `sportmodestate` from the next process |

— and `scan()`, `Ownership`, `reap()`, `attribute()`, `format_report()` and the
census tool all work off it untouched, because none of their **logic** names a
simulator. Corrected 2026-08-23 07:2x (verifier N3): two **strings** do —
`format_report`'s report body at `_sim_guard.py:385,387` says
"parcel_robot.sim process(es)" and "~840 MB", and the module docstring is
written around the eighteen. They are prose, not predicates: nothing branches
on them. The future pattern-table card must edit those two lines (say "guarded
process", take the size from the table row) at the same time as it replaces
`is_parcel_sim`/`socket_of`, or a leaked Go2 gateway will be reported as a
simulator. Left as-is today deliberately: today the only implemented pattern
*is* the simulator, and the report's job is to be readable by whoever hits it
now.
**UNKNOWN until the box:** whether the Go2 gateway is a separate process at
all, and whether a leaked CycloneDDS participant is visible as a process rather
than only as a socket — if it is not, this seam catches nothing and a DDS-level
probe is a different card.

## (f) Test strategy → the pre-registered rows

`tests/test_hy1_sim_guard.py`. Stand-in processes (`python -m parcel_robot.sim`
against a six-line shadow module on `PYTHONPATH`) give argv **identical in
shape** to the real thing without 840 MB of MuJoCo; the real simulator is
measured live once and recorded in `HY1_STATUS.md`. R1 census (evidence file).
R2/R3 real `-m slow` run, one case, pre-fix vs fixed. R4 seeded RED on the real
`_LiveRuntime.__init__`. R5 an **inner pytest session** that copies the real
`tests/conftest.py` and deliberately leaks, asserted on for test-name + pid +
socket, with a `PARCEL_SIM_GUARD=off` control that must be green and silent.
R6 three ownership refusals plus a live "refused reaps do not signal". R7 the
census tool's AST (no signal calls) and its agreement with `ps -ww`. R8 a live
`--pidfile` launch. R9 ruff. R10 the pre-existing orphans. R11 the conftest
region. R12 the guard must not perturb a neighbouring module.

**Amended 2026-08-23 (session 5), because implementation moved:** R6's three
refusals are asserted twice — once on hand-built `SimProcess` records, and
once on records `_sim_guard.scan()` built from **live processes**, which is
what the row pre-registered ("the same code path the reaper consumes") and
what a seed proved necessary: with the owner-stack check deleted from
`started_by_this_run`, the hand-built owner test still passed. That needs a
second stand-in, `_STANDIN_DECOY`: it wears the argv it is given
(`-m parcel_robot.sim --socket /tmp/parcel_sim.sock`, or
`-m parcel_robot.web_panel --port 8765`) and binds only `HY1_BIND_SOCKET`,
so the owner's socket is never created and :8765 is never listened on. R2/R3
are measured on a `git archive HEAD` copy of the tree under
`~/.cache/parcel-hy1/`, not by seeding the product file in place — the pre-fix
fixture is exactly what HEAD holds, and the working tree is shared with four
other cards.

## (g) Risks / not covered

* A process spawned **after** the last module's teardown (e.g. in
  `pytest_sessionfinish`) is invisible to a module-scoped guard. Accepted: the
  leak class this card measured is per-test-file.
* Attribution is by time window; two tests that overlap in a single worker
  cannot overlap, but a sim spawned during *collection* or module import is
  reported against the file, not a test.
* `report`/`off` are honest escape hatches; `off` is what the control arm uses.
* The guard proves nothing about a leaked process that is **not** a
  `parcel_robot.sim` today — that is the table in §e, deliberately unimplemented.
* **An orphan the run cannot prove it started is invisible to the guard**, by
  construction: a sim that is neither a descendant of this pytest nor on a
  socket under this session's basetemp is left alone even when it is plainly
  leaking (measured in
  `test_a_live_sim_outside_our_basetemp_and_our_tree_is_not_ours`). That is the
  price of being allowed to signal anything at all on a host five sessions
  share; `tools/list_parcel_procs.py` is the operator's answer for that class.
* Not covered: containers/PID namespaces, non-Linux, and any leak that manifests
  as a held socket without a live process.
