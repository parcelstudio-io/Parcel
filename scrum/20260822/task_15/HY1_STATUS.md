# HY-1 — status: COMPLETE (all 12 rows MET; closed 06:5x, correction pass 07:2x, 2026-08-23)

**Verifier:** ACCEPT-WITH-NOTES (`~/.cache/parcel-verify/hy1/VERDICT.md`) — notes N1–N4 dispositioned in "Correction pass" at the end; no HOLD, no FIX.

**Headline.** The fixture that leaked eighteen simulators is fixed at its
source and the suite now catches the *next* leak by test name, pid and socket.
Measured end to end today: the **pre-fix** fixture, running HEAD's own file
against a **real MuJoCo simulator**, still leaks (741 MB orphan, reparented to
`systemd --user`); the **fixed** fixture on the same reproduction leaves
**zero** survivors with the guard switched off; and the guard, dropped onto the
pre-fix fixture, fails the run naming
`tests/test_voice_nav_e2e.py::test_go_to_the_sidewalk_grounds_plans_and_arrives`,
its pid and its socket, and reaps it. Another card's simulator was alive on the
host throughout and was never touched.

| row | verdict | row | verdict |
|---|---|---|---|
| R1 leak census before | **MET** | R7 census tool read-only + agrees | **MET** |
| R2 pre-fix reproduction | **MET** | R8 `launch_sim.sh --pidfile` live | **MET** |
| R3 fixed: 0 survivors | **MET** | R9 ruff | **MET** |
| R4 seeded RED, teardown | **MET** (05:38, session 4) | R10 reap pre-existing orphans | **MET** (none existed; 0 signalled) |
| R5 guard NAMES the leak | **MET** | R11 no collision with XD-1 | **MET** |
| R6 never touches what it did not start | **MET**, strengthened | R12 targeted suite, no perturbation | **MET** |

**Card:** `scrum/20260822/task_15/README.md` · **Design:**
`scrum/20260822/task_15/DESIGN.md` · **Pre-registration:**
`scrum/20260822/task_15/PREREGISTRATION.md`
(sha256 `e077845a380b50f43905289198b96cdb0927915b086459296712d3a0e95d5180`,
re-verified today — VERBATIM, rows measured as written).

**Executor:** Opus (fifth session, 06:19–06:5x EDT 2026-08-23) ·
**Dispatcher:** Fable `parcel-6c` (31fcc2a0) · **HEAD:** `e15e466`.

This document is written incrementally, row by row, because the editor
crashed four times across 08-22/23. Rows appear here as they close; the
sections below are in the order they were written, oldest first.

## Resumed from (written by the third executor — see "Resumed from — all four predecessors" at the end for the complete chain)

Two earlier executors died mid-card (~15:40 and ~17:35). Their work was in
the tree and nothing was reverted.

* **First executor (15:19–15:58)** left: `PREREGISTRATION.md`;
  `~/.cache/parcel-hy1/evidence/census_before.txt` (the R1 census of 18 live
  orphans); `tests/_sim_guard.py` (381 lines); `tests/test_hy1_sim_guard.py`
  (638 lines); the `HY-1 sim guard` marked region in `tests/conftest.py`;
  `tests/test_voice_nav_e2e.py` +107 (the `_LiveRuntime.__init__`
  `try/except BaseException` and `_stop_sim`); `scripts/launch_sim.sh` +54
  (`--pidfile`); `tools/list_parcel_procs.py` (178 lines);
  `~/.cache/parcel-hy1/{evidence,shadow}`.
* **Second executor (16:17–16:22)** left exactly one file for this card:
  `DESIGN.md` (136 lines). It touched no HY-1 code.
* **KEPT** — everything above. Re-read in full at 17:49–17:55; the design is
  accurate about the seams and the implementation matches it.
* **CHANGED / DISCARDED** — recorded in "Deviations" below as each item is
  worked.

## R10 — the pre-existing orphans: THERE ARE NONE

**Re-censused at 2026-08-22 17:49:38 EDT**, before touching anything.
Evidence: `~/.cache/parcel-hy1/evidence/census_resume3.txt`.

```
$ pgrep -af parcel_robot.sim                  -> no match (exit 1)
$ ps -eo pid,lstart,args | grep parcel_robot  -> only my own grep
$ ss -xl | grep -i parcel                     -> no match (exit 1)
$ ls -la /tmp/parcel_sim.sock                 -> No such file or directory
$ ss -ltn | grep -w 8765                      -> no match (exit 1)
$ ps -o args= -p 2447765 2447909 2448046 2448183 2448324
                                              -> NO SUCH PROCESS (all five)
```

**Result: no pre-existing orphan was alive at resume.** The five pids named
in `AUDIT_WAVE2_FABLE.md` §Housekeeping and in row R10 are gone — reaped by
the ~17:35 crash that also killed their parent session, not by me. **Zero
processes were signalled by this card's R10.** Nothing was hunted for.

The R1 census taken at 15:19 (`census_before.txt`, 18 sims, ~15.3 GB
resident, every one on a `/tmp/pytest-of-jaewoo-jang/pytest-3848/` socket
from `tests/test_voice_nav_e2e.py`) stands as the measured defect this card
fixes; it is the "before" this card's rows are argued against.

## Resume-4 census (2026-08-23 05:34:27 EDT) — still zero

Evidence: `~/.cache/parcel-hy1/evidence/census_resume4.txt`.

```
$ pgrep -af parcel_robot                      -> (none)
$ .parcel/bin/python tools/list_parcel_procs.py
      -> "No parcel_robot.sim process is running on this host."  (rc=0)
$ ss -xl | grep -i parcel                     -> (no parcel unix sockets)
$ ls -la /tmp/parcel_sim.sock                 -> No such file or directory
$ ss -ltnp | grep 8765                        -> (nothing on 8765)
```

R10 stands as closed by the third executor: **zero processes signalled by this
card, ever.** The owner's stack is down and was not touched.

## The unfinished item at resume: a SEED LEFT IN THE PRODUCT FILE

The third executor died at ~18:02 (machine reboot) **mid-seed**, with seed S1
still applied to `tests/_sim_guard.py`. This is why the file showed
"14 passed + 2 errors/failures": the tree was RED **by construction**, not
broken.

Proof it was a seed and not a defect:

| fact | value |
|---|---|
| `~/.cache/parcel-hy1/evidence/sha256_before_seeds.txt` records pre-seed | `85a9e09786d5b906c16e0f75f3b82b497cb2231e1749f77e83422d7cf3476dc2` |
| `tests/_sim_guard.py` as found at 05:34 | `fd9933981c558c32dbf4f6e6c69b310375371d3cadc52736b0360405e26228dc` |
| `~/.cache/parcel-hy1/_sim_guard.py.orig` (the executor's own backup) | `85a9e09786d5b906c16e0f75f3b82b497cb2231e1749f77e83422d7cf3476dc2` — **equals the recorded pre-seed hash** |
| the diff | exactly the 6-line `/proc/uptime` branch removed from `_boot_time()`, docstring left intact describing the removed branch |
| `~/.cache/parcel-hy1/evidence/seed_s1_clock.txt` | truncated mid-capture at `17:57:37` — `.....F...` — the executor died here |

### S1 (re-captured and closed by me) — the clock is load-bearing for attribution

**Seed.** `_boot_time()` loses its `/proc/uptime` branch and falls back to
`/proc/stat` `btime`, which is quantised to whole seconds.

**RED** (`~/.cache/parcel-hy1/evidence/seed_s1_clock_RED.txt`, 05:35):

```
$ .parcel/bin/python -m pytest tests/test_hy1_sim_guard.py -p no:randomly -q
FAILED tests/test_hy1_sim_guard.py::test_a_processs_start_time_is_dated_accurately_enough_to_attribute_it
FAILED tests/test_hy1_sim_guard.py::test_the_guard_fails_the_run_and_names_the_leaking_test
2 failed, 13 passed, 1 warning in 2.39s
```

The second failure is the card's own thesis failing: with a coarse clock the
guard still *caught* the leak but printed

```
  leaked by : /home/.../inner/rpe1ezu2t/test_leaky.py (outside every test window)
```

— the **file**, not the test. R5 demands the test's name, so the coarse clock
is a real miss, not a cosmetic one.

**Restore, byte-identical.** `cp ~/.cache/parcel-hy1/_sim_guard.py.orig
tests/_sim_guard.py`; `sha256sum` → `85a9e097…6dc2`, equal to the recorded
pre-seed hash; `find tests tools -name __pycache__ -prune -exec rm -rf {} +`.

**GREEN** (`~/.cache/parcel-hy1/evidence/seed_s1_clock_GREEN.txt`, 05:35:55):

```
$ .parcel/bin/python -m pytest tests/test_hy1_sim_guard.py -p no:randomly -q
...............                                                          [100%]
15 passed, 1 warning in 2.48s
```

`pgrep -af parcel_robot` after the run: none. The two tests the dispatch
called "unfinished" are **green on the restored tree**; no code change was
needed, only the restore the reboot interrupted.

## R4 — MET. Seeded RED on the fixture that leaked the eighteen

Seed **S2**, applied in place to `tests/test_voice_nav_e2e.py` (HY-1's
exclusive OWNS) and restored: `_LiveRuntime.__init__` reverted to its
**pre-fix shape** — the `try:` / `except BaseException:` pair removed and the
twenty body lines dedented, so the `subprocess.Popen` again sits outside any
teardown. That is the literal defect, not an analogue of it.

| | sha256 |
|---|---|
| pre-seed / restored | `7ee66b034a76ccba52cd8ddb044769936eff10ea3ba456ad5e5843e81218168c` |
| seeded | `23ee3d21c823ff29315abc2ef23ffcd40d930eb9366f93e574d4634ee32938e8` |

**RED** (`evidence/r4_seed_s2_RED.txt`, 05:38:05) — named test, child alive:

```
$ .parcel/bin/python -m pytest \
    tests/test_hy1_sim_guard.py::test_live_runtime_setup_error_tears_the_sim_down \
    -p no:randomly -q
E   AssertionError: the simulator (pid 148159) outlived a setup error — this is
E   the leak that produced 18 orphans on 2026-08-22
E   assert None is not None
E    +  where None = poll()
tests/test_hy1_sim_guard.py:386: AssertionError
1 failed, 1 warning in 1.59s
```

**GREEN** after `cp …/test_voice_nav_e2e.py.orig`, sha256 re-verified equal to
the pre-seed hash, `__pycache__` purged (`evidence/r4_seed_s2_GREEN.txt`,
05:38:17): `1 passed, 1 warning in 1.01s`.

`pgrep -af parcel_robot` after both arms: none — the test's own `finally`
reaped the stand-in it spawned, in the RED arm too.

**What it does not prove.** The seeded error stands in for the real
`MemoryPathRefused`, and `subprocess.Popen` is monkeypatched so the child is a
six-line stand-in rather than 840 MB of MuJoCo. The code under test is the
real, unmodified `_LiveRuntime.__init__` including its process-group teardown;
the real simulator is exercised by R2/R3 instead.


---

# Fifth session (2026-08-23, from 06:19 EDT) — Opus, dispatcher Fable `parcel-6c`

The fourth executor died at **05:38:42** in the kernel OOM kill described in
`BATCHB_DISPATCH_FABLE_4a.md` §parcel-6c — seconds after it wrote R4 MET
(05:38:44) and restored `tests/test_voice_nav_e2e.py`. Nothing was reverted.
**Every pytest invocation below went through
`~/.cache/parcel-guard/pytest_guard.sh --label hy1`** (40 GB cgroup, `-n` ≤ 8,
suite lock), `TMPDIR` unset, foreground, never `-n auto`, never
`scripts/ci_gate.py`.

## Resume-5 census (2026-08-23 06:19:18 EDT) — still zero

```
$ pgrep -af parcel_robot            -> only my own grep's command line
$ pgrep -af -- '-m pytest'          -> only my own grep + parcel-6c's memwatch loop
$ .parcel/bin/python tools/list_parcel_procs.py
      -> "No parcel_robot.sim process is running on this host."   (rc=0)
$ free -g | awk '/^Mem/{print $7}'  -> 234
```

Nothing signalled. The owner's stack is down (`/tmp/parcel_sim.sock` absent);
it was never touched. Tree state at resume, unseeded — every OWNS file at its
recorded pre-seed hash (`evidence/sha256_before_seeds.txt`):
`_sim_guard.py` `85a9e097…`, `test_hy1_sim_guard.py` `db69fb01…`,
`list_parcel_procs.py` `dfc520d6…`, `conftest.py` `f65ecb57…`,
`test_voice_nav_e2e.py` `7ee66b03…`, `launch_sim.sh` `19855387…`.

**Baseline, guard suite (06:20:59–06:21:02, wall 3 s):**

```
$ env -u TMPDIR ~/.cache/parcel-guard/pytest_guard.sh --label hy1 \
    .parcel/bin/python -m pytest tests/test_hy1_sim_guard.py -p no:randomly -q
15 passed, 1 warning in 2.39s
```

(The dispatch's "14 passed + 2 errors" was the fourth executor's interrupted
S1 seed, already restored and re-proved at 05:35. Nothing was left to fix.)

## R5 — MET. The guard names the leak: test, pid, socket

Re-captured today under the wrapper (06:21:43–06:21:46) with the same helper
the committed test uses (`tests/test_hy1_sim_guard._run_inner_pytest`), so the
evidence is what the test asserts on. An inner pytest session, running a copy
of **the real `tests/conftest.py`**, deliberately leaks a stand-in sim.

```
$ env -u TMPDIR ~/.cache/parcel-guard/pytest_guard.sh --label hy1 \
    .parcel/bin/python ~/.cache/parcel-hy1/scripts/r5_capture.py
r5_inner_guard_reap.txt: exit=1 pid=209812 alive_after=False
r5_inner_guard_off.txt:  exit=0 pid=209848 alive_after=True
```

**Guard arm** (`evidence/r5_inner_guard_reap.txt`, 06:21:44) — inner exit 1,
and the failure text carries all three registered facts:

```
  leaked by : test_leaky.py::test_this_one_leaks_a_sim
  process   : pid 209812 (parent 209784, started 06:21:43) socket /home/…/basetemp/test_this_one_leaks_a_sim0/sim.sock
  argv      : …/.parcel/bin/python -m parcel_robot.sim --socket /home/…/sim.sock
  cleanup   : terminated
```

**Control arm** (`evidence/r5_inner_guard_off.txt`, 06:21:46) —
`PARCEL_SIM_GUARD=off`, the identical run: `1 passed in 0.15s`, exit 0, no
"HY-1 sim guard" anywhere in the output, and the leaked pid 209848 **still
alive 1 s after pytest exited**. The guard is what reddens the run, not the
test. Both leaks are gone: the guard reaped the first, the capture script
reaped its own control (`alive=False` printed).

**What it does not prove.** The leaked process is the six-line stand-in
(`python -m parcel_robot.sim` against a shadow module), not 840 MB of MuJoCo —
argv-identical, which is all the guard reads. The real simulator is exercised
by R2/R3 below.

## R9 — MET. Ruff

```
$ .parcel/bin/ruff check tests/_sim_guard.py tests/test_hy1_sim_guard.py \
    tools/list_parcel_procs.py tests/conftest.py tests/test_voice_nav_e2e.py
All checks passed!                                    (ruff 0.16.1, rc=0)
```

Ratchet, tree-wide (`ruff check . --output-format json`, fingerprints
`file::rule`) — **measured three times, and it moved because other cards were
editing while I worked**:

| when | tree-wide | beyond the 7-entry baseline |
|---|---|---|
| 06:26 | 13 errors / 8 fingerprints | `tests/test_xd1_repo_write_guard.py::I001` (XD-1, `task_14`) |
| 06:53 | 16 errors / 9 fingerprints | + `tests/test_truth1_texts.py::PLW1510` (TRUTH-1, `task_32`) |
| **07:16 (correction pass)** | **12 errors / 7 fingerprints** | **NONE — exactly the baseline of `scripts/ci_ruff_baseline.json`** |

Both foreign fingerprints were **cleared by their own owners** between 06:53 and
07:0x, which the verifier confirmed independently (N4) and I re-measured at
07:16:16: `new beyond baseline: NONE`, `baseline not seen: none missing`. The
attribution stands and is now historical — neither was ever HY-1's, and **HY-1
adds zero** at every one of the three measurements. No `noqa` was added
anywhere (the only occurrence of the string in my files is a comment in
`tools/list_parcel_procs.py:54` explaining why one is *not* needed); the
baseline was not re-pinned. The Handoffs entry below is kept for the record and
marked resolved.

## R11 — MET. No collision with XD-1

`tests/conftest.py` carries two disjoint marked regions:
`BEGIN HY-1 sim guard` (94–186) and, strictly below it,
`BEGIN XD-1 repo-write census` (190–…). **This session made no edit to
`tests/conftest.py` at all** — the HY-1 region was already complete, so no
`~/.cache/parcel-batchb/lock-conftest.py` was ever taken and no lock of
another card was touched. The only files this session writes are HY-1's
exclusive OWNS.

**The file did change under me, and it was not me** (recorded at 06:54:48 as
part of the closing census): the whole-file sha256 moved from `f65ecb57…` to
`b2d6277b…` and XD-1's region grew from 190–298 to 190–306 — XD-1's executor
is live in this tree right now, which is exactly the situation R11 was
pre-registered for. **HY-1's region is byte-for-byte where it was**: same
boundaries (94–186), same 93 lines, sha256 of the extracted region
`259937b0…`, same three hooks (`pytest_runtest_logstart`,
`pytest_runtest_logfinish`, `_hy1_sim_guard`). It is also proved
*functionally* after XD-1's edit: `test_the_guard_fails_the_run_and_names_the_leaking_test`
copies the **real** `tests/conftest.py` into its inner session, and it passed
in the 06:54:48 run. Nothing of XD-1's was merged over, and nothing of mine
was lost — R11's "HALT that item rather than merge" was never triggered.

## R1 — MET. Leak census, before (the defect as found)

`~/.cache/parcel-hy1/evidence/census_before.txt`, taken 2026-08-22T15:19:56
before any HY-1 code existed, with `ps -eo pid=,ppid=,lstart=,etime=,rss=,args=`
— **every** live sim, not a sample.

| | |
|---|---|
| sims alive | **18** |
| resident | **14.51 GiB (15.6 GB)**, mean 825 MB each |
| parent | all 18 reparented to pid 11135 = `/usr/lib/systemd/systemd --user` — orphans, their pytest long gone |
| started | 13:20:15 → 13:20:29, **one per second**, i.e. one per test case |
| sockets | all under `/tmp/pytest-of-jaewoo-jang/pytest-3848/<case>0/sim.sock` |
| owner's stack | `/tmp/parcel_sim.sock` absent, nothing on :8765 — the leak was never the owner's |

Re-checked today: **18 of 18** socket directory names correspond to a `def
test_…` in `tests/test_voice_nav_e2e.py` (`test_go_to_the_sidewalk_ground0`,
`test_orbit_the_owner_completes0/1`, `test_sit_next_to_the_lamppost_0/1`, …).

**The source, named from the code, not guessed:** `_LiveRuntime.__init__`
spawned `subprocess.Popen([… "-m", "parcel_robot.sim", …])` and *then* ran the
socket wait, `build_runtime(…)`, `runtime.start()` and the observation wait —
all outside any `try`. The `live` fixture's `finally: session.close()` can only
run if `__init__` **returned**, so an exception anywhere in those four steps
left the child alive with no reference to it anywhere. `build_runtime` raising
`MemoryPathRefused` (card R27: no `PARCEL_MEMORY_PURPOSE` declared) is what
fired on 2026-08-22, once per case, eighteen times.

## R6 — MET, and strengthened. Never touches what it did not start

The four refusals were already asserted on hand-built `SimProcess` records.
The row was pre-registered as *"asserted on a record built from the same code
path the reaper consumes"*, so this session added four tests that repeat each
refusal **against a real, live process found by `_sim_guard.scan()`** — the
same call the conftest fixture makes — with "the process is still alive
afterwards" as the proof that nothing was signalled
(`tests/test_hy1_sim_guard.py`, 19 tests, was 15):

| new test | row | subject |
|---|---|---|
| `test_a_live_process_wearing_the_owners_argv_is_refused_by_the_real_scan` | R6(a) | a live process whose `/proc` argv is `-m parcel_robot.sim --socket /tmp/parcel_sim.sock` |
| `test_the_control_deck_on_8765_is_not_even_in_the_census` | R6(a) | a live `-m parcel_robot.web_panel --port 8765` |
| `test_a_live_sim_outside_our_basetemp_and_our_tree_is_not_ours` | R6(b) | a real orphaned sim, reparented away from pytest, socket outside every basetemp |
| `test_a_live_sim_alive_before_the_run_is_not_ours_on_the_real_scan` | R6(c) | a sim that IS ours by both routes, refused solely for being in the before-snapshot |

**The rule the dispatch set is kept exactly**: nothing here creates
`/tmp/parcel_sim.sock` or listens on :8765. The new `_STANDIN_DECOY` wears the
argv and binds only what `HY1_BIND_SOCKET` names — the owner-stack decoy binds
a scratch socket, the control-deck decoy binds **nothing**, and each test
asserts it (`/tmp/parcel_sim.sock` existence unchanged across the test;
`ss -ltnp` carries no `pid=<decoy>`).

### Seeded RED on the product for each new test (4 seeds, restored byte-identically)

Seeds were applied to `tests/_sim_guard.py` — HY-1's exclusive OWNS, the module
the conftest guard imports — and each was reverted before the next.

| seed | defect injected | seeded sha256 | RED |
|---|---|---|---|
| **S3** | `started_by_this_run` loses `if proc.is_owner_stack: return False` | `67d7b997…` | `…owners_argv_is_refused_by_the_real_scan` — `assert True is False` on the record for `--socket /tmp/parcel_sim.sock` |
| **S4** | `is_parcel_sim` matches any `parcel_robot.*` token | `f4a51edf…` | `…control_deck_on_8765_is_not_even_in_the_census` + `…predicate_matches_what_pgrep_matches` |
| **S5** | `_under()` answers "yes" for every absolute path | `6d2c7d7d…` | `…live_sim_outside_our_basetemp_and_our_tree_is_not_ours` + the hand-built basetemp test |
| **S6** | the `ownership.before` check neutered | `9c698415…` | `…alive_before_the_run_is_not_ours_on_the_real_scan` + 2 hand-built ones |

Evidence: `evidence/r6_seed_s{3,4,5,6}_*_RED.txt`, `evidence/r6_seeds_GREEN.txt`.

**S3 is the finding that justifies the whole addition.** Under S3 — with the
owner-stack refusal deleted from the product — the *old* hand-built test
`test_the_owners_live_stack_is_never_ours_to_reap` **still passed**: its record
has pid 424242, which is neither a descendant of pytest nor under any
basetemp, so `started_by_this_run` answered False for a reason that has nothing
to do with the owner check. Only the live test caught it (`1 failed, 18
passed`). A guard whose owner-protection can be deleted without a red test is
not a guard.

Restore after every seed: `tests/_sim_guard.py` sha256
`85a9e09786d5b906c16e0f75f3b82b497cb2231e1749f77e83422d7cf3476dc2`, `cmp -s`
against `~/.cache/parcel-hy1/_sim_guard.py.orig` → **byte-identical**;
`__pycache__` purged; re-run **19 passed** (06:37:15).

## R7 — MET. `tools/list_parcel_procs.py` is read-only, and agrees with the host

**Read-only, pinned over the AST** (`test_the_census_tool_cannot_signal_anything`):
no `os.kill` / `os.killpg` / `proc.kill` / `proc.terminate` / `subprocess.run` /
`subprocess.Popen` / `_sim_guard.reap` in any call position, and `signal` is
not imported. Asserted on the AST, not the text, because the module's docstring
discusses killing at length.

**Agreement on the LIVE host** (`evidence/r7_live_census_agreement.txt`,
06:38:07). The subject is a real MuJoCo sim **this card did not start** —
ROAM-2's (`task_33`), pid 239716, 729 MB, socket
`~/.cache/parcel-roam2/r2-239652.sock`:

```
pgrep hits          : [239716]
  real sims (token) : [239716]
tool census pids    : [239716]
ROW-FOR-ROW: AGREEMENT
$ ps -ww -o pid=,lstart=,args= -p 239716
 239716 Sun Aug 23 06:37:11 2026 …/.parcel/bin/python -m parcel_robot.sim --config … --socket …/parcel-roam2/r2-239652.sock --static-city
```

and the tool's own row for it: `pid 239716 [other] age 55s`, socket, start
time, `memory : 729 MB`, `parent : pid 239652 … run_roam2.py`. A second live
agreement was captured during R8 on my own sim (`[other]`, 727 MB, parent the
launch script).

**A measured caveat worth the verifier's time.** My first capture printed
DISAGREEMENT: `pgrep -f -- '-m parcel_robot\.sim'` had also matched three of my
own shell processes, because `pgrep -f` matches a **substring of any command
line** — including the command line of the shell doing the grepping. `ps -ww`
on each showed them to be bash, not sims. The tool matches an argv **token**
(`_sim_guard.is_parcel_sim`), so it excludes them by construction. The
re-capture, classifying every `pgrep` hit by its argv tokens, is the file
above. The census is the stricter instrument, and pgrep's extra hits are its
own false positives.

**Runs on a box without MuJoCo** (hardware-compat §e — the Orin NX has no
MuJoCo and no editable install):

```
$ /usr/bin/python3 -c "import mujoco"        -> ModuleNotFoundError
$ /usr/bin/python3 -c "import parcel_robot"  -> ModuleNotFoundError
$ /usr/bin/python3 tools/list_parcel_procs.py
No parcel_robot.sim process is running on this host.        (rc=0)
```

The system interpreter cannot import the project at all, and the census tool
still runs: it imports stdlib plus `tests/_sim_guard`, which is stdlib-only.
Both files also parse under `ast.parse(..., feature_version=(3, 10))` —
CPython 3.10 is what JetPack ships. (Syntax only; not an execution proof on
aarch64, which no one can give without the box.)

## R8 — MET. A real `scripts/launch_sim.sh --pidfile` launch, reaped through the pidfile

`evidence/r8_pidfile_launch.txt` + `evidence/r8_launch.log`, 06:39:34–06:40:1x.
A **real MuJoCo simulator and a real control deck**, on a unique short socket
and a unique port:

```
$ env -u TMPDIR PARCEL_SKIP_AUDIO_ENV=1 \
    PARCEL_MEMORY_PATH=$HOME/.cache/parcel-hy1/r8_memory.sqlite3 \
    PARCEL_SESSION_EVIDENCE=0 PARCEL_REALTIME_SPEND_LEDGER=$HOME/.cache/parcel-hy1/r8_spend.jsonl \
    scripts/launch_sim.sh --socket ~/.cache/parcel-hy1/r8.sock \
      --pidfile ~/.cache/parcel-hy1/r8.pid \
      --host 127.0.0.1 --port 8791 --no-browser --no-llm
```

| | before | alive | after SIGTERM |
|---|---|---|---|
| pidfile | absent | holds `257153` | **gone** (`cleanup_pidfile`) |
| `ps -ww -o args= -p 257153` | — | `…/.parcel/bin/python -m parcel_robot.sim --socket …/r8.sock` | **no such process** |
| census tool | 0 sims | `pid 257153 [other] age 3s … memory : 727 MB` | `No parcel_robot.sim process is running on this host.` |
| socket file | absent | present | gone |
| :8791 | free | `LISTEN 127.0.0.1:8791` | free |
| **:8765** | free | **free** | **free** |
| **/tmp/parcel_sim.sock** | absent | **absent** | **absent** |

Script exit status **143** — `trap 'exit 143' TERM` → the `EXIT` trap →
`cleanup` → `terminate_child` + `cleanup_owned_socket` + `cleanup_pidfile`.
The whole lifecycle was one foreground command; nothing was left running.

**Two owner-safety measures, deliberate.** (1) `launch_sim.sh` exports
`PARCEL_MEMORY_PURPOSE=owner` (card R27) and the panel it starts opens the
conversation store read-write — so the launch was given an absolute
`PARCEL_MEMORY_PATH` under my scratch. Afterwards `parcel_memory.sqlite3` in
the repo is still `Aug 22 02:19` (untouched) and
`~/.cache/parcel-hy1/r8_memory.sqlite3` exists with today's timestamp.
(2) `PARCEL_SKIP_AUDIO_ENV=1`, and the log says `Microphone not armed: no
speech recognizer` — the reSpeaker XVF3800 was never opened, never played
through, never sent a control command. The run also left **no** new path in
`git status` and no new `recordings/` folder.

## R2 — MET. The leak reproduced on the UNFIXED tree, with a real simulator

**Declared substitution, exactly as pre-registered.** The fixture no longer
errors in setup on today's tree, so the setup error is injected "at the same
seam" — and by **environment only**, no code seeded:
`PARCEL_MEMORY_PATH=hy1_r2_relative.sqlite3` makes
`memory_path.resolve_memory_path` refuse a relative override, so
`build_runtime` raises **`MemoryPathRefused`** — the same exception class, at
the same call site (`web_panel.build_runtime` → `RobotRuntime(...)`, reached
from `_LiveRuntime.__init__:126`), that produced the eighteen.

**The unfixed tree is HEAD itself, not a seed.** `git archive HEAD | tar -x` into
`~/.cache/parcel-hy1/prefix-tree` (`.parcel` symlinked in); its
`tests/test_voice_nav_e2e.py` sha256 `c524773c…` equals
`git show HEAD:tests/test_voice_nav_e2e.py`, and differs from the working
tree's fixed `7ee66b03…`. Its conftest is HEAD's — no HY-1 guard exists in it
at all. The working tree, shared with four other cards, was never seeded for
this row.

```
$ cd ~/.cache/parcel-hy1/prefix-tree
$ env -u TMPDIR PARCEL_SIM_GUARD=off PARCEL_MEMORY_PATH=hy1_r2_relative.sqlite3 \
    ~/.cache/parcel-guard/pytest_guard.sh --label hy1 …/.parcel/bin/python -m pytest \
    "tests/test_voice_nav_e2e.py::test_go_to_the_sidewalk_grounds_plans_and_arrives" \
    -p no:randomly -p no:cacheprovider -q --basetemp=~/.cache/parcel-hy1/r2bt
1 warning, 1 error in 1.18s
```

**Survivor, 3 s after pytest exited** (`evidence/r2_prefix_tree_guard_off.txt`):

```
  pid 292331  [other]  age 4s
      socket : …/parcel-hy1/r2bt/test_go_to_the_sidewalk_ground0/sim.sock
      memory : 741 MB
      parent : pid 182559  /usr/lib/systemd/systemd --user
```

A **real MuJoCo simulator**, 741 MB, reparented to `systemd --user` — the exact
shape of the eighteen in `census_before.txt`. **≥ 1 survivor: MET.**

**It was reaped, and how** (`evidence/r2_reap_of_my_own_leak.txt`, 06:44:14).
This is the only process this card has ever signalled. R10's rule was applied
to it: re-identified with `ps -ww -o args= -p 292331` **immediately before** the
signal, and three checks asserted first — `is parcel_robot.sim=1`, `on MY
basetemp=1`, `names the owner's socket=0`. Then `kill -TERM` → dead. The
owner's `/tmp/parcel_sim.sock` was absent throughout and nothing was on :8765.

### R2c — the same pre-fix fixture, met by the guard as shipped (product-path integration)

Not a pre-registered row; the strongest evidence in the card, so it is recorded.
Same pre-fix tree, with `tests/_sim_guard.py` and the HY-1 conftest region
copied in (guard in default `reap` mode). `evidence/r2c_prefix_tree_guard_on.txt`:

```
____ ERROR at teardown of test_go_to_the_sidewalk_grounds_plans_and_arrives ____
HY-1 sim guard: 1 parcel_robot.sim process(es) outlived …/tests/test_voice_nav_e2e.py.
  leaked by : tests/test_voice_nav_e2e.py::test_go_to_the_sidewalk_grounds_plans_and_arrives
  process   : pid 295078 (parent 295014, started 06:44:50) socket …/r2cbt/test_go_to_the_sidewalk_ground0/sim.sock
  argv      : …/.parcel/bin/python -m parcel_robot.sim --socket …/sim.sock --static-city
  cleanup   : terminated
```

The guard met the **real** defect on the **real** product fixture with a **real**
MuJoCo child, named the real test, and left **0 survivors**. Throughout all
three arms, ROAM-2's live sim (`task_33`, pid 291013, socket under
`~/.cache/parcel-roam2/`) sat on the same host and was **never touched** — the
ownership rule, live.

## R3 — MET. Exactly 0 survivors on the fixed tree

Same reproduction, working tree, and deliberately **`PARCEL_SIM_GUARD=off`** so
what is measured is the FIX (`_LiveRuntime.__init__`'s
`try/except BaseException` → `_stop_sim`) and not the net
(`evidence/r3_fixed_tree_guard_off.txt`, 06:45:17):

```
$ env -u TMPDIR PARCEL_SIM_GUARD=off PARCEL_MEMORY_PATH=hy1_r3b_relative.sqlite3 \
    ~/.cache/parcel-guard/pytest_guard.sh --label hy1 .parcel/bin/python -m pytest \
    "tests/test_voice_nav_e2e.py::test_go_to_the_sidewalk_grounds_plans_and_arrives" \
    -p no:randomly -q --basetemp=~/.cache/parcel-hy1/r3bt2
1 warning, 1 error in 1.04s

the sim really ran:  srw-rw-r-- …/r3bt2/test_go_to_the_sidewalk_ground0/sim.sock
survivors under MY basetemp: (none — SURVIVORS: 0)
```

The bound socket file is the proof the simulator really started and really was
torn down (rather than never having spawned); the full traceback in
`evidence/r3_fixed_tree_full.txt` shows the socket wait completed and the
raise came from `build_runtime` → `RobotRuntime` → `resolve_memory_path`.
**0 survivors: MET.**

## R12 — MET. Targeted suite; the guard does not perturb its neighbours

`evidence/r12_targeted_suite.txt`, 06:45:57–06:50:xx, all four under the wrapper:

| run | result |
|---|---|
| `pytest tests/test_hy1_sim_guard.py -p no:randomly -q` | **19 passed** in 2.63 s |
| `pytest tests/test_voice_nav_e2e.py --collect-only -q` | **18 tests collected** — the file is `-m slow`; 18 is also the number of orphans of 2026-08-22, one per case |
| `pytest tests/test_navigation.py -p no:randomly -q` (guard ON, default `reap`) | **38 passed**, 2 warnings, 0.78 s |
| `PARCEL_SIM_GUARD=off pytest tests/test_navigation.py …` | **38 passed**, 2 warnings, 0.70 s |

Counts **identical** with and without the guard. `tests/test_navigation.py`
was chosen because no other batch-B card has it dirty, so the comparison is
not contaminated by a concurrent edit. Cost of the hook on that module: two
`/proc` scans for the file, inside run-to-run noise (0.78 vs 0.70 s).

---

## What changed

```
$ git diff --stat HEAD -- tests/conftest.py tests/test_voice_nav_e2e.py scripts/launch_sim.sh
 scripts/launch_sim.sh       |  54 ++++++++++++
 tests/conftest.py           | 208 ++++++++++++++++++++++++++++++++++++++++++++
 tests/test_voice_nav_e2e.py | 107 +++++++++++++++++------
 3 files changed, 344 insertions(+), 25 deletions(-)
```

New files: `tests/_sim_guard.py` (408), `tests/test_hy1_sim_guard.py` (998,
was 720 — this session added the four live-record R6 tests and the decoy
stand-in), `tools/list_parcel_procs.py` (178).

**Scope note (verifier N2).** The card README describes the conftest change as
"one autouse fixture". The region as shipped is **three** hookpoints: the
module-scoped autouse fixture `_hy1_sim_guard` (the census and the failure),
plus the two hookimpls `pytest_runtest_logstart` and `pytest_runtest_logfinish`
that record each test's time window. The two hooks are what make the report say
*which test* rather than which file — seed S1 (and the verifier's W6) show
attribution degrading to the filename without them — so they are load-bearing,
not incidental. This was declared in **DESIGN.md §(b) Architecture fit** before
implementation; **DESIGN §(b) supersedes the README's wording**, which was
written before the attribution mechanism existed. No acceptance row moves: R5
always required the test's name.

Final sha256 (nothing seeded, nothing left applied):

```
85a9e097…  tests/_sim_guard.py            (== the recorded pre-seed hash)
94a50dfe…  tests/test_hy1_sim_guard.py    (this session's addition; was db69fb01…)
dfc520d6…  tools/list_parcel_procs.py     (unchanged)
b2d6277b…  tests/conftest.py              (NOT edited by me — XD-1 edited its own
                                           region at ~06:5x; HY-1's region 94–186
                                           is byte-identical, region sha 259937b0…)
7ee66b03…  tests/test_voice_nav_e2e.py    (== the recorded pre-seed hash)
19855387…  scripts/launch_sim.sh          (unchanged)
```

Measured at 06:54:48, after which this session wrote nothing but this document.

`.parcel/bin/ruff check` on the five Python OWNS: **All checks passed**;
`bash -n scripts/launch_sim.sh`: OK.

## What this does not prove

* **The leak class is per-test-file.** A sim spawned after the last module's
  teardown (e.g. in `pytest_sessionfinish`) is invisible to a module-scoped
  guard, and so is an orphan the run cannot prove it started — measured, not
  assumed (`test_a_live_sim_outside_our_basetemp_and_our_tree_is_not_ours`).
  `tools/list_parcel_procs.py` is the operator's answer for that class.
* **Only `parcel_robot.sim` is guarded today.** The perception daemon and the
  native Go2 gateway are a named extension point (DESIGN §e), not code.
* **`R2`/`R3` ran one case, not the file.** Pre-registered as such: 18 cases ×
  minutes each against a real sim is not something to run on a shared host, and
  the leak is per-case by construction (the census shows one orphan per case).
  The case never reached its navigation assertions — the point of both rows is
  the setup path.
* **The seeded errors stand in for the original.** R2/R3 use `MemoryPathRefused`
  from a relative `PARCEL_MEMORY_PATH`; the original came from an undeclared
  `PARCEL_MEMORY_PURPOSE`. Same class, same call site, different trigger.
* **No aarch64 execution.** The Orin claims in DESIGN §e rest on: stdlib-only
  imports, `/proc` fields that are architecture-independent, a working run
  under an interpreter with neither MuJoCo nor `parcel_robot` installed, and
  `ast.parse(feature_version=(3,10))`. Nobody can run it on the box before the
  box exists.
* **Not measured:** behaviour under `-n auto` xdist (the anti-crash rules forbid
  it this week; the design's per-worker argument in §d is unexercised),
  containers/PID namespaces, non-Linux, and a leak that manifests as a held
  socket with no live process.

## Deviations

1. **R6 strengthened beyond the draft implementation** (not beyond the
   pre-registration — it is what R6 asked for): four tests added that assert the
   refusals on live-process records from `_sim_guard.scan()`. Justified by seed
   S3, under which the hand-built owner test passed with the product's
   owner-protection deleted.
2. **R2/R3 measured on a `git archive HEAD` copy** under
   `~/.cache/parcel-hy1/prefix-tree` rather than by seeding
   `tests/test_voice_nav_e2e.py` in place. HEAD *is* the unfixed tree, and the
   working tree is shared with four live cards. The tree was deleted afterwards.
3. **Setup error injected by environment, not by code.** `PARCEL_MEMORY_PATH`
   relative → `MemoryPathRefused`. Nothing in `src/` was touched by this card at
   any point.
4. **R8 given `PARCEL_MEMORY_PATH` and `PARCEL_SKIP_AUDIO_ENV=1`.**
   `launch_sim.sh` exports `PARCEL_MEMORY_PURPOSE=owner` and its panel opens the
   conversation store read-write; the standing rule is that the owner's
   `parcel_memory.sqlite3` is never opened read-write by a test. Verified
   untouched afterwards (`Aug 22 02:19`).
5. **R7's live agreement is stated against argv-token matching**, because
   `pgrep -af` also matches the grepping shell's own command line. Both
   captures are described above; the second is the file on disk.
6. **DESIGN.md edited in the same pass** (§f amendment + one new §g bullet) to
   record 1 and 2, per the COMMON brief.

## Owner-gated rows

None. Every row was measurable here. No hosted spend, no hardware: the reSpeaker
XVF3800 was never opened (R8 ran with `PARCEL_SKIP_AUDIO_ENV=1`; the panel
logged `Microphone not armed`), and no robot hardware exists to gate on.

## Handoffs

* **XD-1 (`task_14`)** — two items. (a) Ruff — **RESOLVED 07:0x, not by me.**
  As reported at 06:53, `tests/test_xd1_repo_write_guard.py::I001` and TRUTH-1's
  `tests/test_truth1_texts.py::PLW1510` were new fingerprints beyond the 7-entry
  baseline (**none of them HY-1's**; my five Python files were clean at every
  measurement). Both owners cleared their own; re-measured at **07:16:16**,
  tree-wide is **12 errors / exactly the 7 baseline fingerprints**. Kept here as
  the record of what was seen and when. (b) The `_remove_tree` docstring in
  `tests/test_hy1_sim_guard.py` records a measured defect in
  `tests/_repo_write_guard.Recorder._record`: it resolves an audited relative
  path with `os.path.abspath`, i.e. against pytest's cwd (the repo root), so
  `shutil.rmtree`'s fd-relative deletions in a **scratch** directory get charged
  to the repo. Reported, not patched — that file is XD-1's.
* **The integrator** — `tests/conftest.py` now carries two marked regions,
  HY-1's (94–186) and XD-1's (190–298). If only one card lands, the other
  region must be removed with it: XD-1's block imports `_repo_write_guard`
  at module scope, so a conftest with that region but without the file will
  fail collection for the whole suite.
* **Anyone running `-n auto` again** — the guard is module-scoped and each xdist
  worker holds its own state and basetemp (DESIGN §d). That argument is
  reasoned, not measured; this week's rules forbade the run that would measure it.

## Every pytest run of this session (audit against `~/.cache/parcel-guard/guard.log`)

All under `~/.cache/parcel-guard/pytest_guard.sh --label hy1`, `TMPDIR` unset,
foreground, one at a time, never `-n` anything, never `scripts/ci_gate.py`.
Before each: `free -g` available ≥ 120 (it was 230–234 all session).
`grep 'label=hy1' guard.log` is the ledger; wall-clock ≤ 3 s each.

| time | run | rc | why |
|---|---|---|---|
| 06:20:59 | `pytest tests/test_hy1_sim_guard.py -q` | 0 | baseline, 15 passed |
| 06:21:43 | `python ~/.cache/parcel-hy1/scripts/r5_capture.py` (runs pytest inside — hence under the wrapper) | 0 | R5 capture |
| 06:27:59 | guard suite | 0 | 19 passed, after the R6 additions |
| 06:29:20 / 06:29:51 / 06:30:20 / 06:36:56 | guard suite ×4 | 1 | seeds S3 / S4 / S5 / S6 — RED **by construction** |
| 06:37:15 | guard suite | 0 | all seeds restored, 19 passed |
| 06:41:54, 06:42:15 | `…::test_go_to_the_sidewalk_grounds_plans_and_arrives` | 1 | R3 first pass + full traceback |
| 06:43:51 | same node id, in `prefix-tree` | 1 | R2 (pre-fix, guard off) |
| 06:44:50 | same node id, in `prefix-tree` | 1 | R2c (pre-fix, guard on) |
| 06:45:17 | same node id, working tree | 1 | R3 (fixed, guard off) |
| 06:50:38–06:50:44 | guard suite, e2e collect-only, `test_navigation.py` ×2 | 0 | R12 |
| 06:54:48 | guard suite | 0 | closing verification — 19 passed, nothing left seeded (guard.log 162–163) |

Four of these are the *seeded* red runs and five are `rc=1` because the run
under test is an error-injection; no run exceeded the 40 GB cgroup, none was
killed (no exit 137), none used xdist, and no run was backgrounded.

## Processes: everything this card started, and the one thing it signalled

* Sims started by me: **one** per R2/R2c/R3 arm (three, sequentially, never two
  at once) and **one** for R8. Every one accounted for: R2's was reaped by hand
  with re-identification, R2c's by the guard, R3's by the fix, R8's by
  `cleanup_pidfile`/`terminate_child`.
* Stand-ins started by the test suite: all reaped in `finally`; the census is
  clean after every run above.
* **Processes signalled by this card, ever: one** — pid 292331, my own R2 leak,
  after three recorded checks. Nothing else, at any point, in any session.
* Never touched: the owner's `/tmp/parcel_sim.sock` (absent all session), :8765
  (free all session), ROAM-2's live sim, and any process I did not start.

## Resumed from — all four predecessors

* **Executor 1 (08-22 15:19–15:58, died in the 15:36-onwards OOM window)** left
  `PREREGISTRATION.md`; the R1 census `evidence/census_before.txt`;
  `tests/_sim_guard.py` (381 lines); `tests/test_hy1_sim_guard.py` (638);
  the `HY-1 sim guard` region in `tests/conftest.py`; the
  `test_voice_nav_e2e.py` fix (+107); `scripts/launch_sim.sh --pidfile` (+54);
  `tools/list_parcel_procs.py` (178); the R2/R3 pid lists. **KEPT, all of it.**
* **Executor 2 (16:17–16:22)** left `DESIGN.md` (136 lines) and no code.
  **KEPT**; amended today in §f and §g (see Deviations 6).
* **Executor 3 (17:49–18:02, died in the machine's OOM/reboot)** re-censused
  (zero orphans → R10 closed, nothing signalled), captured the first R5
  evidence, and died **mid-seed** with S1 applied to `_sim_guard.py` — which is
  the entire explanation of the "14 passed + 2 errors" the dispatch inherited.
* **Executor 4 (08-23 05:34–05:38:42, died in the `pytest -n auto` OOM kill)**
  re-captured S1 RED/GREEN, restored `_sim_guard.py` byte-identically, closed
  **R4** (seed S2 on the real `_LiveRuntime.__init__`) at 05:38:44, and restored
  `test_voice_nav_e2e.py` byte-identically as its last act. **KEPT; verified**:
  both files were at their recorded pre-seed hashes when I arrived, and the
  suite it left was green (15 passed), not broken.
* **This session (5th)** re-censused (zero processes), re-ran the baseline,
  re-captured R5, **strengthened R6** with four live-record tests and proved
  each load-bearing with a seed, and closed R1, R2, R3, R7, R8, R9, R11, R12.
  **DISCARDED: nothing.** No predecessor's work was reverted or rewritten; the
  only file whose content changed this session is
  `tests/test_hy1_sim_guard.py` (additions only) plus this document and
  `DESIGN.md`.

---

## Correction pass (2026-08-23 07:2x EDT) — verifier verdict ACCEPT-WITH-NOTES

Verdict record: `~/.cache/parcel-verify/hy1/VERDICT.md` (Fable, read-only
session; 14 weakening seeds W1–W14 on a scratch copy, every row re-measured,
an adversarial four-stand-in probe of the ownership rule, and `-n 2` xdist —
which closes a gap I had listed as "not measured"). **No HOLD, no FIX.** This
pass is documentation only: no file under `tests/`, `tools/`, `scripts/` or
`src/` was touched, no pytest was run, git stayed read-only.

| note | disposition |
|---|---|
| **N1** — the 06:54:48 guard-suite run is in `guard.log` (162–163) but missing from my ledger table | **APPLIED.** Row added: `06:54:48 · guard suite · rc=0 · closing verification, 19 passed`. The table now accounts for every `label=hy1` line in `guard.log`. |
| **N4** — tree-wide ruff is back to exactly the 7 baseline fingerprints; the XD-1 / TRUTH-1 fingerprints I reported were cleared by their owners | **APPLIED.** R9 now carries all three measurements (06:26 → 8 fps, 06:53 → 9 fps, **07:16:16 → 7 fps = baseline exactly**, re-measured by me this pass), keeps the attribution as history, and the XD-1 handoff (a) is marked **RESOLVED, not by me**. |
| **N2** — README says "one autouse fixture"; the region ships a fixture **plus** `pytest_runtest_logstart` / `pytest_runtest_logfinish` | **APPLIED.** A "Scope note" in *What changed* names all three, explains that the two hooks are what make the report say *which test* (seed S1 / verifier W6), and records that **DESIGN §(b) supersedes the README's wording**. The README itself is not edited — it is the card as dispatched, and rewriting a dispatched card after the fact is worse than annotating it. No acceptance row moves. |
| **N3** — `format_report`'s strings name the simulator although §e describes a pattern-table process guard | **DECLINED as a code change; APPLIED as a doc correction + handoff.** This pass is docs-only, and the strings are honest today: the only implemented pattern *is* `parcel_robot.sim`. What was actually wrong was **my own §e sentence** ("none of them names a simulator"), so DESIGN §e is corrected to say none of their *logic* does, name the exact two lines (`_sim_guard.py:385,387`), and put the edit on the future pattern-table card's checklist. Nothing branches on those strings. |

Also recorded, no action needed from me: **N5** — `scan()` costs 18 ms at 1925
`/proc` entries, so two scans × ~385 modules ≈ 14 s CPU serial / ≈ 2 s wall at
`-n 8`; this is the integrator's number for the commit tier, and it is a
handoff below. **N6** confirms by independent probe the limitation DESIGN §g
already states (an orphan the run cannot prove it started is left alone — three
of the verifier's four stand-ins survived untouched, which is the correct
behaviour). **N7 / N8** are test-hygiene NOTEs the verifier could not reproduce
(a fixed stranger-socket path could race between two concurrent runs of this
file; a SIGKILLed worker could strand an 11 MB `sleep 3600` stand-in for an
hour) — both are real, neither is worth a code change this week under the
anti-crash rules; a future pass should give
`test_a_live_sim_outside_our_basetemp_and_our_tree_is_not_ours` a `tmp_path`-
derived socket name. **N9** — my docstring claim that `ps -o args=` truncates
at 80 columns holds on a tty but not into a pipe (158 chars measured both
ways), which makes one assertion in
`test_the_census_tool_agrees_with_ps_on_a_live_sim` trivially true and
`launch_sim.sh`'s pidfile preflight correct without `-ww`; docstring only,
listed for the next editor of that file.

**Verdict on my own numbers after the pass:** every row still MET, no number
changed, no acceptance moved. The only substantive correction to a claim I made
is the ruff ratchet, which improved (9 → 7 fingerprints) because two other
cards cleaned up after themselves.

### Handoffs added by this pass

* **The future pattern-table card (DESIGN §e).** Edit `_sim_guard.py:385` and
  `:387` with the predicate: "guarded process" instead of "parcel_robot.sim",
  and the size from the table row instead of "~840 MB".
* **The integrator.** Budget ≈ 2 s wall at `-n 8` (≈ 14 s CPU serial) for the
  guard's two `/proc` scans per test module on the commit tier (verifier N5,
  measured 18 ms/scan at 1925 `/proc` entries).
* **Whoever next edits `tests/test_hy1_sim_guard.py`.** N7's fixed socket path
  and N9's tty-only truncation docstring, both above.
