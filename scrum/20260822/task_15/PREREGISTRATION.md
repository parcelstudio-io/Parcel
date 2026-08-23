# HY-1 — pre-registered acceptance rows

Written **before** any fix, any guard, and any measurement other than the
read-only census of the pre-existing orphans (`census_before.txt`, taken first
because the defect is live and would otherwise be destroyed by my own work).
Nothing below is adjusted after the fact; a row that comes out worse than
registered is recorded as a MISS with its number.

Environment for every row: `/home/jaewoo-jang/Desktop/Projects/Parcel`,
`.parcel/bin/python` (3.14.4), `.parcel/bin/ruff` 0.16.1, `TMPDIR` unset,
scratch under `/home/jaewoo-jang/.cache/parcel-hy1/`.

## Rows

| # | Row | Pre-registered acceptance |
|---|---|---|
| R1 | **Leak census, before.** Every live `parcel_robot.sim` is recorded with pid, ppid, start time, elapsed, RSS, socket path, and whether the socket is the owner's. | Census file exists and covers **every** live sim (not a sample). The leaking source is named from source code, not guessed. |
| R2 | **Fresh-sweep reproduction, pre-fix.** A fresh, minimal run of `tests/test_voice_nav_e2e.py` on the UNFIXED tree leaks at least one `parcel_robot.sim` that outlives pytest. | ≥ 1 survivor under **my** session basetemp after pytest exits. If the fixture no longer errors in setup on today's tree, the row is reproduced by injecting a setup error at the same seam, and that substitution is declared. |
| R3 | **Fix.** The same reproduction on the FIXED tree. | **Exactly 0** survivors under my session basetemp after pytest exits. |
| R4 | **Seeded RED — teardown.** A committed test injects a setup failure into `_LiveRuntime.__init__` after the sim is spawned. | Test is **RED on the pre-fix `__init__`** (child still alive) and **GREEN after**. Both outputs recorded verbatim. |
| R5 | **Seeded RED — the guard NAMES the leak.** An inner pytest session deliberately leaks a sim; the outer asserts the guard's failure text. | Guard **fails the inner run** and the failure text contains all three of: the leaking **test's name**, the **pid**, the **socket path**. With the guard off the same inner run is **GREEN** (proving the guard, not the test, is what reddens). |
| R6 | **Never touches what it did not start; never the owner.** Pinned by tests. | Guard refuses to reap (a) `/tmp/parcel_sim.sock` and the `:8765` panel, (b) a genuine `parcel_robot.sim` whose socket is outside this session's basetemp, (c) any process alive in the before-snapshot. All three assert False and are asserted on a record built from the same code path the reaper consumes. |
| R7 | **`tools/list_parcel_procs.py` is read-only.** Operator census: pid, socket, age, owner-or-not, parent. | Runs against the live host and lists **every** sim found by `pgrep -af parcel_robot.sim`, agreeing row-for-row. Contains **no** signalling call — pinned by a test over its own source. |
| R8 | **`scripts/launch_sim.sh --pidfile`.** A real launch on a unique socket and a unique port, reaped through the pidfile. | Pidfile holds a live pid whose `ps -o args=` is `parcel_robot.sim`; after the script is stopped the pidfile is **gone** and the pid is **dead**. Owner's `/tmp/parcel_sim.sock` and `:8765` untouched throughout. |
| R9 | **Ruff.** | Ratchet stays **exactly 7** fingerprints; `.parcel/bin/ruff check` reports **0** findings on every file I add or edit. No `noqa` added, no re-pin. |
| R10 | **Reaping the pre-existing orphans.** Only after the guard is in place. | Each pid re-identified with `ps -o args= -p <pid>` **immediately before** the signal and confirmed to be `parcel_robot.sim` on a `/tmp/pytest-of-*` socket. **0** processes signalled that fail that check. Every kill recorded in the status doc. |
| R11 | **No collision with XD-1 (`task_14`).** | My conftest hook lives inside a marked region (`HY-1`); `tests/conftest.py` re-read immediately before every edit. If XD-1 has claimed the same lines, I **HALT that item** and say so rather than merging over it. |
| R12 | **Targeted suite.** `tests/test_hy1_sim_guard.py` plus collection of `tests/test_voice_nav_e2e.py` plus one neighbouring module to prove the autouse hook does not perturb unrelated tests. | All targeted tests pass; the neighbouring module's pass/fail counts are **identical** with and without the guard. |

## Declared in advance

* `test_voice_nav_e2e.py` is `-m slow` and each case runs for minutes against a
  real MuJoCo sim. I will run **at most one or two cases**, never the file, and
  never `scripts/ci_gate.py` or the full suite.
* Any sim I start is mine to reap; every one is recorded.
* Numbers I cannot measure (e.g. a case that cannot reach terminal state in
  budget) are reported as **not measured**, never as passing.
