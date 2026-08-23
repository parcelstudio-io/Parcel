# XD-1 — STATUS (card `scrum/20260822/task_14`)

## Complete — 2026-08-23 07:1x EDT

**Executor:** Claude Opus, FIFTH resume (06:2x EDT dispatch, session parcel-6c
31fcc2a0; rows D1 and earlier are earlier resumes' — see §Resumed from at the
end). **Verifier:** Fable. **HEAD:** `e15e466`.
**Design:** `DESIGN.md` (edited this pass where addendum A2/A3 forced it).
**Pre-registration:** `PREREGISTRATION.md`, kept VERBATIM, sha256
`b8097c4351e6e9e82958f60c1e86e502d9df614dbf6a8d96d8f606a1fef7a7d5`
(re-verified at the start AND the end of this session — unchanged).

**Rows: W1 recorded · W2 MET · W3 MET · W4 NOT MEASURED (rule) · D1 MET ·
D2 MET · D3 MET · D4 MET · D5 MET · D6 published (2 leaks named) ·
D7 published (10 offenders → guard ships opt-in, as pre-registered) · L1 MET ·
seeds S1–S5 all as registered · addendum A1–A3 MET, A4 adopted.**

Nothing here is a claim unless it carries a command and a number. Rows were
appended as they closed.

## Resumed from

See §"Resumed from" at the end — four predecessors, all killed by kernel OOM
kills, the fourth by this card's own defect (addendum A1).

---

## Row D1 — admitted node-id set: MET (0 added, 0 removed)

Rig: the scratch clone `~/.cache/parcel-xd1/tree` at `e15e466` + this card's
OWNS only (`~/.cache/parcel-xd1/sync.sh`; the clone deliberately does NOT carry
HY-1's conftest region, whose `tests/_sim_guard.py` does not exist at
`e15e466`). Marker strings taken from the product, not retyped:

```
$ ~/.cache/parcel-xd1/collect.sh          # pytest --collect-only -q, TMPDIR unset
phaseA: 9297     -m "(not slow) and not load_sensitive"
phaseB: 10       -m "(not slow) and load_sensitive"
tier:   9307     -m "not slow"            (COMMIT_MARKERS)
```

```
phaseA=9297 phaseB=10 union=9307 tier=9307 A&B=0
union-tier: 0    tier-union: 0
```

**Exact set equality, empty intersection: the two phases are a partition of the
commit tier, measured, not argued.** (Total collected 9,388; 81 `slow`
deselected — unchanged.)

The ten tests in phase B, every one of them a pre-existing `load_sensitive`
mark from cards R26 / AIR-1 / DUPLEX-1 — **this card adds no marker to any
test**:

```
tests/test_air1_rate_pin.py::test_the_array_itself_refuses_24k
tests/test_cpu_budget_proxy.py::test_build_report_includes_budget_and_does_not_prove
tests/test_cpu_budget_proxy.py::test_cli_writes_json
tests/test_duplex1_rows.py::test_duplex1_d1_the_reply_goes_quiet_within_100ms_of_the_onset
tests/test_duplex1_rows.py::test_duplex1_d1b_a_lagging_socket_is_the_transport_bound_arm
tests/test_duplex1_rows.py::test_duplex1_d2_cancel_latency_at_the_shipped_floor
tests/test_duplex1_rows.py::test_duplex1_d3_the_shipped_floor_is_the_smallest_that_clears_survival
tests/test_duplex1_rows.py::test_duplex1_d5_no_owed_turn_is_dropped_by_a_state_transition
tests/test_duplex1_rows.py::test_duplex1_d6_without_the_prerequisites_the_floor_buys_nothing
tests/test_dynamic_costs.py::test_cost_field_vectorization_performance
```

Three of the seven P0-E divergences (`test_cpu_budget_proxy` ×2,
`test_dynamic_costs` perf) are in that list already — card R26 had marked them.
The remaining four are handled below and **not** by a new marker.

---

## The measurement rig for every row below (read this once)

All of it runs in the scratch clone `~/.cache/parcel-xd1/tree` at **`e15e466`**
(re-verified this session) + this card's OWNS only, `PYTHONPATH=<clone>/src`,
`TMPDIR` unset, **`PARCEL_XDIST_WORKERS=8` under `pytest_guard.sh --label xd1`**
(addendum rule A4). The live working tree's gate is never run.

**The rows are measured through the product's own code, not a shell copy of it.**
`~/.cache/parcel-xd1/product_run.py` imports `scripts.ci_gate` from the clone and
calls, for the "before", the exact line the gate carried before this card
(`_pytest_gate("default-suite", …, markers=COMMIT_MARKERS)`) and, for the
"after", **`evaluate_default_suite()` itself** — phase order, marker
expressions, worker resolution and verdict logic are all the product's. The only
instrument is a tee around `run_pytest` that appends `-rA` to the child's
`PYTEST_ADDOPTS` and writes each phase's stdout to a file, because
`GateResult.detail` keeps only the summary line and a node-id census needs node
ids. `PARCEL_REPO_WRITE_GUARD=off` in every row of this section, so this card's
own new guard cannot change a verdict it is being compared against; the guard's
own row is D7.

**Rig caveat, stated before the numbers:** the clone has **15 pre-existing
failures** at `e15e466` (barn corpora / prototype-profile launcher /
owner-store), caused by the clone lacking git-ignored asset trees and the live
tree's uncommitted work. They are constant in every arm, which is all D2–D5 need
— but W1–W3 are timings of a suite with 15 reds in it, and no row here claims
the clone is green.

## Row W1 — serial `default-suite` baseline: **385.33 s** (recorded, no target)

```
$ env -u TMPDIR pytest_guard.sh --label xd1 run.sh baseline w1_serial PARCEL_REPO_WRITE_GUARD=off
XD1_PHASE 1 markers='not slow' extra_args=None rc=1 wall=385.33s
15 failed, 9292 passed, 21 skipped, 81 deselected, 3 xfailed in 382.88s (0:06:22)
loadavg after: 1.34 / 1.58 / 2.40 on 192 cores
```

The live tree's last recorded figure was 407 s; 385 s on the clone is the same
number to within load. **This is the "before".**

## Row W2 — two-phase `default-suite`: **75.34 s** — target ≤ 90 s: **MET**

Run 1 of the three (all three in row D4):

```
XD1_PHASE 1 markers='(not slow) and not load_sensitive' extra_args=['-n','8','--dist','loadfile'] rc=1 wall=68.39s
XD1_PHASE 2 markers='(not slow) and load_sensitive'     extra_args=[]                             rc=0 wall=6.95s
detail: -n 8 --dist loadfile [PARCEL_XDIST_WORKERS=8 (honoured; cpu_count=192, cap=16)];
        parallel (68.4s): 15 failed, 9283 passed, 20 skipped, 3 xfailed
        serial   (7.0s):  9 passed, 1 skipped, 9402 deselected
extra:  {"workers": "8", "seconds": {"parallel": 68.39, "serial": 6.95}}
```

**A4 annotation: this is an `-n 8` number and is NOT comparable to P0-E's 51.9 s**,
which was `-n auto` = 192 workers. The target was written expecting `auto`; it is
met with **8** workers, i.e. with 1/24th of the parallelism the target assumed.
The worker count and its provenance are in the row itself, not in this document
only.

Phase B is 7.0 s of the 75.3 s and **zero of its ten tests skipped for
contention** — `scripts/load_guard.py:contention_reason()` saw a quiet machine
because phase A's workers had exited. That is the design claim in §(e) of
`DESIGN.md` measured: the serial phase is what keeps a wall-clock pin honest.

## Row W3 — speed-up W1/W2 = **385.33 / 75.34 = 5.11×** — target ≥ 4.5×: **MET**

Per-run: 385.33/75.34 = **5.11×**, /74.77 = **5.15×**, /77.10 = **5.00×**.
Same A4 annotation: 5× at eight workers, not at 192.

## Row W4 — full `--tier commit` end-to-end: **NOT MEASURED**

Anti-crash rule 3 of the 2026-08-23 dispatch forbids every executor from running
`scripts/ci_gate.py --tier <any>` in any tree; the commit tier belongs to the
integrator, once, at close, with the tree quiescent. The pre-registered ≤ 90 s
target is therefore **not measured, not estimated, and not claimed** — W2 is the
`default-suite` STAGE only, and the tier has nine other stages. What this card
can say is bounded and true: the stage that was 385 s of the tier is now 75 s of
it. The integrator's single `--tier commit` run at close is where W4 becomes a
number; the command is in §Owner/integrator-gated rows.

## Row D2 — verdict identity, parallel vs serial, three consecutive runs: **MET**

`census.py` parses every `-rA` short-summary line of both phases into
`node id -> outcome` and compares the whole map, not just the failures:

```
$ census.py summary w1_serial.phase1.txt p1.merged.txt p2.merged.txt p3.merged.txt
w1_serial : 9329 node ids | FAILED=15 PASSED=9292 SKIPPED=19 XFAIL=3
p1.merged : 9329 node ids | FAILED=15 PASSED=9292 SKIPPED=19 XFAIL=3
p2.merged : 9329 node ids | FAILED=15 PASSED=9292 SKIPPED=19 XFAIL=3
p3.merged : 9329 node ids | FAILED=15 PASSED=9292 SKIPPED=19 XFAIL=3

$ census.py diff w1_serial.phase1.txt p1.merged.txt p2.merged.txt p3.merged.txt
  admitted-only-in-base : 0     admitted-only-in-other: 0
  DIVERGENT fail-only-in-other: 0   DIVERGENT fail-only-in-base : 0     (×3)

strict outcome-level equality (every id, every outcome, not just failures):
p1: OUTCOME-LEVEL DIFFERENCES vs baseline = 0
p2: OUTCOME-LEVEL DIFFERENCES vs baseline = 0
p3: OUTCOME-LEVEL DIFFERENCES vs baseline = 0
```

**Zero divergences.** P0-E's seven are gone: three (`test_cpu_budget_proxy` ×2,
`test_dynamic_costs` perf) are in phase B by R26's pre-existing marks (row D1),
and the other four do not diverge at 8 workers.

**What this does NOT prove:** that they do not diverge at 192. P0-E's seven were
measured at `-n auto`, and three of the four remaining ones
(`test_fixa_transcript_persistence` kill switch, `test_runtime` streaming ×2)
are per-process-state families whose failure probability rises with worker
count. **A4: the 192-worker arm is NOT MEASURED and its meaning needs `auto`,
which is forbidden on this host.** The claim this row supports, stated exactly:
**non-divergent at `-n 8 --dist loadfile`**. That is not the count the gate
will use here — after A3 the gate's default on THIS host is
`min(192, 16)` = **16, which is unmeasured**; on the Go2's Orin NX the default
is **8, which is the count measured**. 192 is unreachable without an explicit
operator `PARCEL_XDIST_WORKERS` pin. So: clean at 8; 16 untested; 192 out of
reach by default. (Corrected in the 07:4x pass — the earlier wording,
"the worker count the gate will actually use", overstated it.)

**A measurement-instrument defect found and fixed mid-row (disclosed):**
`census.py`'s node-id regex was `(\S+)`, which truncated parametrized ids
containing spaces (`[the sidewalk-region]`) and collapsed 9,292 PASSED lines onto
8,978 keys — two tests sharing one key is exactly how a divergence census hides a
divergence. It also counted six captured-log `ERROR    logger:file:line` lines as
six errored tests. Both fixed (whole-remainder node id; exactly one space after
the outcome) **before** any D2/D3/D4 number above was read. The 9,329 keys now
reconcile: 9292 + 15 + 19 + 3.

## Row D3 — nothing silenced: **MET**

Skipped and xfailed sets are **identical**, not merely subsets:

```
p1/p2/p3: skipped parallel-only=[]  serial-only=[]   xfail equal=True
```

All 19 skip keys are pre-existing asset/hardware skips (`test_p1c_real_siglip2`
×7, `test_siglip_real_embeddings` ×3, `test_owlv2_detector` ×2,
`test_owner_store_isolation` ×2, `test_air1_rate_pin`, `test_endpointing`,
`test_eval_assertions`, `test_nm1_promotion_and_asks`, `test_p3_storefront_ocr`).
**Zero load-guard skips appeared in any arm** — the "parallel set ⊆ serial set ∪
{load-guard skips}" clause was never needed, because the set that had to be
excused was empty. **This card introduced no `skip`, no `xfail`, no deselect and
no new marker** (row D1 already showed all ten phase-B tests carry pre-existing
R26/AIR-1/DUPLEX-1 marks).

## Row D4 — flake bar, three consecutive two-phase runs: **MET (zero divergence)**

```
p1  06:38:12  parallel 68.39s  serial 6.95s  total 75.34s
p2  06:39:42  parallel 67.80s  serial 6.97s  total 74.77s
p3  06:41:02  parallel 69.97s  serial 7.13s  total 77.10s
```

**A4 annotation: all three are `-n 8` numbers, not comparable to P0-E's
51.9 s.** Identical outcome maps in all three (9329 ids, 15/9292/19/3) and
identical to W1's serial baseline — the diff above is run against the baseline for each of the
three, and all four maps are equal. Wall-clock spread 74.77–77.10 s (3.1 %).

## Row D5 — order-independence (module-import order): **MET**

`-p xd1_shuffle`, a measurement-only plugin that reorders the collected items by
TEST FILE with the file order shuffled by `random.Random(20260822).shuffle` —
the exact seed pre-registered. Tests keep their source order inside a file, so
exactly one channel changes: which module is imported first, and therefore which
test pays for (and observes) a module's import-time state.

```
$ pytest_guard.sh --label xd1 run.sh baseline d5_shuffle PARCEL_REPO_WRITE_GUARD=off \
      XD1_ADDOPTS="-p xd1_shuffle"
XD1_SHUFFLE: 381 test files reordered with seed 20260822
15 failed, 9292 passed, 21 skipped, 81 deselected, 3 xfailed in 377.51s (0:06:17)

baseline: 9329 ids {FAILED:15, PASSED:9292, SKIPPED:19, XFAIL:3}
shuffled: 9329 ids {FAILED:15, PASSED:9292, SKIPPED:19, XFAIL:3}
OUTCOME-LEVEL DIFFERENCES: 0
```

**Zero divergences, nothing to classify.** (Serial run: this row is about import
order, not workers, so A4's `-n 8` note does not apply to it.)

## Row D6 — process-state census: **published, 2 leaks named**

`-p xd1_state_census` snapshots `os.environ`, `sys.modules` (id-keyed) and
`os.getcwd()` around **every** test and writes a row whenever one changed;
9,801 rows, merged from `$XD1_STATE_CENSUS_OUT.<pid>` across the 8 workers +
the serial phase. Run in the two-phase configuration — the one the gate will
actually use — and its verdict was identical to every other arm, so the
instrument perturbed nothing.

| Channel | Rows | Verdict |
|---|---|---|
| `os.environ` | 9,801 | **9,801 of them are `PYTEST_CURRENT_TEST`**, which pytest itself sets and clears per test — instrument noise, not a leak. **Two real leaks**, named below. |
| `os.getcwd()` | **0** | no test leaves the process in a different directory |
| `sys.modules` | 11 | one module, `_turn1_replay_tool`, **replaced** (not deleted) by 11 tests in `tests/test_turn1_endpointing.py` — a per-test import shim of the same file, so the next importer sees an equivalent object |

The two environment leaks, with their channel:

```
tests/test_p1c_enroll_appearance.py::test_the_camera_path_refuses_cleanly_when_there_is_no_camera
    LD_LIBRARY_PATH : None -> '<repo>/.parcel/lib/python'         [set, never restored]
tests/test_venue1_physical_venue.py::test_a_physical_venue_refuses_a_simulation_map
    PARCEL_ONLINE_MAP_PATH : None -> '<tmp_path>/…'               [set, never restored]
```

Neither is this card's file. Both are **real** per-process leaks — under
`--dist loadfile` every later test in that worker inherits them — and neither
caused a divergence in D2/D4/D5, which is exactly why a census is published
rather than a pass/fail row: they are hazards that have not fired yet.
Handed off below.

## Row D7 — repo-write census: **published, 10 offenders → the guard ships OPT-IN**

`PARCEL_REPO_WRITE_GUARD=census`, rows merged from `<prefix>.<pid>` over the
two-phase run.

```
tests/test_nav_instruct_scene_gen.py  (8 tests)
    configs/scenes/generated                              [os.mkdir | w]
    configs/scenes/generated/.val_unseen_9101{1..5}.proposal.xml   [w]
    configs/scenes/generated/tmp*.xml                     [os.open flags=0o2400302]
tests/test_stage0_command_addendum.py::test_a_hand_edit_survives_the_no_arm_dynamic_harness
    scrum/20260814/task_1/STAGE0_COMMAND_ADDENDUM.md      [w]    <- TRACKED file
tests/test_barn_v9_supervisory_gap_s2_bundle.py::test_source_mutation_is_rejected_after_freeze
    evals/…/supervisory_gap_s2/experimental_sampled_predictive_tracker.py  [w]  <- TRACKED

offending node ids: 10   distinct paths: 11   session-residue rows: 0
```

**`git status` would have found ZERO of them.** The session-level porcelain net
reported nothing: every one of these tests cleans up after itself. That is the
design argument of `tests/_repo_write_guard.py` measured — the hazard is the
WINDOW during which a neighbour worker reads the path, not the residue.

### The pre-registered decision, applied

> "The repo-write guard ships **ON by default** if and only if the census (D7)
> is empty after my fixes. If it names an offender that is not mine to fix, the
> guard ships **opt-in** … and the offender is listed for its owner."

The census is not empty and **none of the three files is this card's**. So
`read_mode()`'s default is now **`census`** (record, do not fail), `on` is one
environment variable away, and the offenders are listed in §Handoffs. No
allowlist was added — the board's standing rule forbids it, and a per-test
exemption table is exactly that.

### A defect in this card's own guard, found by a peer and fixed here

**Reported by HY-1's executor (2026-08-23, via the orchestrator):**
`Recorder._record` resolved a relative audited path with `os.path.abspath`,
i.e. against the process cwd — which under pytest **is the repository**. Two
bugs, both measured, both fixed inside this card's files:

1. **`dir_fd`-relative paths charged to the repo.** `shutil.rmtree` walks with
   a directory file descriptor for safety, so its audit events carry BARE ENTRY
   NAMES. Reproduced exactly: `shutil.rmtree(<tmp_path>/scratch)` with cwd =
   repo charged `{'a.txt': 'os.remove', 'b.txt': 'os.remove'}` to the
   repository. A path relative to a `dir_fd` is not relative to the cwd and
   this module cannot resolve it, so it is no longer recorded.
2. **`symlink`/`link` recorded the SOURCE, not the path they create.** The
   created path is the second argument. The first is only read — so the guard
   was naming a path the test merely read and **missing the real write**.
   `rename` changes both ends and now records both.

The `_PATH_ARGS` table (which argument is the path, where its `dir_fd` sits) was
**verified against CPython by probe**, not assumed — the previous draft and its
tests had agreed with each other because both had invented the same tuple shape.

**Seeded RED, both fixes** (same harness, clone, restore verified by sha256):

```
REC1  seed: the dir_fd guard deleted
      RED: test_a_path_relative_to_a_dir_fd_is_not_charged_to_the_cwd
           test_an_rmtree_of_a_tmp_path_tree_charges_the_repo_with_nothing
      2 failed in 0.14s → restore verified 33f7795102368c90… → 2 passed
REC2  seed: "os.symlink": ((0, 2),) — the source, not the link
      RED: test_symlink_and_link_record_the_path_they_CREATE_not_the_one_they_read
      1 failed in 0.12s → restore verified 33f7795102368c90… → 1 passed
```

**The census above is the RE-RUN, after the fix.** The pre-fix census named 18
node ids; 8 of them were false positives the two bugs invented
(`test_closed_intent_product_path` "deleting `robot.yaml`", `test_habitat2020_*`
"symlinking `libEGL.so.1.0.0`" ×2, `test_prototype_profile` "symlinking
`.parcel`" ×5). **The pre-fix numbers are withdrawn; only the 10 above are
claimed.** A guard that cries wolf about `rmtree` would have been switched off
within a day, which is why this was worth a re-run rather than a footnote.

## Row L1 — ruff: **MET (exactly the 7 baseline fingerprints, new 0)**

```
$ .parcel/bin/ruff check <this card's files>          → All checks passed
$ .parcel/bin/ruff check .                            → 12 errors
  distinct (file, rule) fingerprints: 7 — byte-for-byte the baseline set
  src/parcel_robot/camera_channel/__init__.py::RUF022
  src/parcel_robot/camera_channel/backends/factory.py::{ISC004,S110}
  src/parcel_robot/camera_channel/channel.py::I001
  src/parcel_robot/detection_adapter/{noise.py::I001,sim_bridge.py::{B009,ISC004}}
  ruff 0.16.1 == scripts/ci_ruff_baseline.json's pinned version
```

No `noqa` added; the baseline was never re-pinned. One NEW fingerprint —
`tests/test_xd1_repo_write_guard.py::I001`, this card's own file, reported
independently by the orchestrator — was fixed at the source with
`ruff check --fix` on that file alone (import order), not silenced.

## Pre-registered seeds S1–S5 — all five as registered

| Seed | Result |
|---|---|
| **S1** a test that writes a git-visible file under the repo root | **RED as registered.** The guard named **that test** and **that path**: `tests/test_xd1_seed_s1_offender.py::test_seed_s1_writes_a_git_visible_file_under_the_repo wrote 1 path(s)… xd1_seed_s1_stray.txt (opened w)`. The seed test **wrote then DELETED** the file: `git status --porcelain` afterwards showed **nothing**, which is the whole argument for the audit hook. Re-run in the shipped `census` default: test passes, row recorded. Seed file and stray removed; clone clean. |
| **S2** phase A loses `and not load_sensitive` | **RED**: `test_no_wall_clock_assertion_can_reach_the_parallel_phase` + `test_the_two_default_suite_phases_partition_the_commit_tier`. Restore verified `c845f374124b6afe…`, re-run green. |
| **S3** phase B made non-complementary (set equal to phase A) | **RED**: `test_the_two_default_suite_phases_partition_the_commit_tier` + `test_the_parallel_phase_is_parallel_and_the_serial_phase_is_serial`. Restore verified, re-run green. |
| **S4** `runtime.py`: `_p1b_install_learned_map()` moved **after** `_attach_configured_camera_ingress()` | **RED**: `tests/test_p1b_map_learns.py::test_the_runtime_region_wires_all_three_seams`. Restore verified `fb3d22c9fd80be7a…`, re-run green. |
| **S5** an **unrelated statement inserted** between the attach and the first `self._thread` | **stays GREEN**, as registered — this is the over-specification the card removed. Same file, same sha256 restore. |

All five ran on the scratch clone's copy of the product (`src/parcel_robot/runtime.py`
at `e15e466`, untouched by any live card), each restored byte-identically by
`sha256sum` with `__pycache__` purged and the test re-run.

---

# ADDENDUM ROWS A1–A4 — the gate must not be able to run itself

Owner-mandated on 2026-08-23 06:1x EDT (parcel-6c take-over section of
`BATCHB_DISPATCH_FABLE_4a.md`), added AFTER the pre-registered rows above and
BEFORE the remaining ones. `PREREGISTRATION.md` is unchanged and still hashes to
`b8097c43…a7d5` — these rows are an addendum, not a re-registration.

**What happened.** The four "crashes" that killed this card's four predecessors
(08-22 15:36, 16:23, 17:58; 08-23 05:38) were kernel **OOM kills**, and the
05:38 one was caused by **this card's own uncommitted work**. Three faults had
to line up:

1. `default-suite` moved off `_pytest_gate` onto `evaluate_default_suite`
   (the two-phase runner, 08-22 15:33).
2. `tests/test_ci_gate.py`'s `fast_commit_tier` fixture stubbed `_pytest_gate`
   and **not** the new evaluator — so ~8 tests in that file called the REAL
   two-phase runner and each spawned the whole 9,000-test suite in a subprocess.
3. That subprocess ran `-n auto` = **192 workers on this host**, and under xdist
   it nested. Five chained runs ~29 s apart = **986 python processes, 237 GB**;
   the kernel killed Cursor's renderer first (`oom_score_adj` 300 vs 100), so
   every agent session on the box died in the same second.

Any ONE of the three would have been enough to prevent it, so all three are now
pinned. Numbers above are parcel-6c's `journalctl -k` reading, not mine.

## Row A1 — the fixture covers every commit-tier stage: **MET**

`tests/test_ci_gate.py` `fast_commit_tier` now stubs `evaluate_default_suite`
alongside `_pytest_gate` (marked `# ---- CARD XD-1 addendum A1`), and
`EXPLODING_VICTIMS` follows the stage that moved: `_pytest_gate` backs **3**
commit-tier rows now (model-off-non-inferiority, release-parity-integrity,
owner-store-isolation) and `evaluate_default_suite` backs **1** — the total is
unchanged, and the move is now visible in the table instead of silent.

Two new tests, both run through the real `run_commit_tier`:

* `test_the_stubbed_commit_tier_never_spawns_a_pytest_subprocess` — a
  record-and-raise `run_pytest` tripwire; a stubbed tier must reach it **zero**
  times.
* `test_without_the_stub_the_default_suite_stage_would_launch_the_whole_suite`
  — the permanent record of the hole: undo exactly the A1 line and the tripwire
  catches the launch, **without paying for it**. No test in this file ever
  starts a real suite.

**SEEDED RED (A1).** Seed = the A1 fixture block deleted, i.e. the fixture
exactly as it stood 08-22 16:19 → 08-23 06:2x. Run in the scratch clone
(`~/.cache/parcel-xd1/seed.sh`, which sha256s the file, seeds, runs the named
tests under the guard wrapper, restores, re-verifies the sha256, purges
`__pycache__`, re-runs):

```
$ ~/.cache/parcel-xd1/seed.sh A1 tests/test_ci_gate.py … \
    ::test_the_stubbed_commit_tier_never_spawns_a_pytest_subprocess \
    ::test_without_the_stub_the_default_suite_stage_would_launch_the_whole_suite
== SEED A1 on tests/test_ci_gate.py (sha256 before: 817402bc9f5fe813…)
E  AssertionError: a stubbed tier reached a real pytest:
   markers='(not slow) and not load_sensitive' args=['-n', '8', '--dist', 'loadfile']
FAILED …::test_the_stubbed_commit_tier_never_spawns_a_pytest_subprocess
1 failed, 1 passed in 0.20s
== RESTORE A1
   byte-identical restore VERIFIED (817402bc9f5fe813ec50461f2e3d7f1eae10c2297ca0f4a80fbaca0b047e4ccd)
-- GREEN re-run:  2 passed in 0.15s
```

The RED message **is** the crash: `selection=()` (no node-id list — the whole
suite) with `-n 8 --dist loadfile`, from inside a test. On 08-23 that `-n` read
`auto`. The hole is proved to have existed, and proved closed, without one
suite-scale process being started.

## Row A2 — the gate refuses to run the default suite inside itself: **MET**

`scripts/ci_gate.py:run_pytest` stamps `PARCEL_CI_GATE_NESTED=1`
(`CI_GATE_NESTED_ENV`) into **every** child it spawns — one line, in the shared
driver, inside its own `# ---- CARD XD-1 nesting mark` region, because the
driver is what creates the child. `evaluate_default_suite` reads it on entry and
returns a hard `error` row naming the cause, **before** any subprocess.
`_pytest_gate`'s targeted runs stay allowed nested on purpose: a bounded node-id
list costs a few tests, not a fan-out, and the gate's own self-tests depend on
it. `env_extra` is applied after the stamp, so a caller that genuinely needs an
unmarked child says so explicitly.

Four tests: the driver stamps it; the evaluator refuses (`status == "error"`,
`hard`, `extra["nested"] is True`, the variable named in `detail`, tripwire
never reached); a targeted stage still runs nested; and — because two halves
that agree only via a shared constant would still pass if the constant were
never written — one test **captures the real child environment `run_pytest`
built, installs it as `os.environ`, and checks the refusal fires on it**.

**SEEDED RED (A2), two seeds, same harness:**

```
A2a  seed: `env[CI_GATE_NESTED_ENV] = "1"` deleted from run_pytest
     RED: test_run_pytest_stamps_the_nesting_mark_into_every_child
          test_the_mark_run_pytest_writes_is_the_mark_the_default_suite_refuses_on
          (the end-to-end one fails INTO the tripwire — _SeededSuiteLaunch with
           markers='(not slow) and not load_sensitive', i.e. the fan-out itself)
     2 failed in 0.24s → restore verified c845f374124b6afe… → 2 passed
A2b  seed: the refusal block deleted from evaluate_default_suite
     RED: test_the_default_suite_refuses_to_run_inside_a_gate_spawned_pytest
          test_the_mark_run_pytest_writes_is_the_mark_the_default_suite_refuses_on
     2 failed in 0.26s → restore verified c845f374124b6afe… → 2 passed
```

## Row A3 — the worker count is derived and capped, never `auto`: **MET**

`resolve_xdist_workers(explicit, env) -> (workers, provenance)` in the XD-1
region. Default `min(os.cpu_count(), XDIST_MAX_WORKERS=16)`; `auto`/`logical`
and any non-positive-integer fall back to that default **with a reason**; an
explicit `PARCEL_XDIST_WORKERS` (or a caller argument, which outranks it) is
**honoured as written, including above the cap** — the cap exists to stop an
accident, not to overrule a person who typed a number, and a gate that silently
substituted a different worker count would make every timing row a lie. The
resolved number **and its provenance** go into the row detail and into
`extra["workers"] / extra["workers_provenance"]`.

Hardware row (§e of `DESIGN.md`, corrected this session): on the Go2 EDU+'s
onboard **Jetson Orin NX (8 cores, aarch64, CPython 3.10)** the default resolves
to **8** — exactly what `auto` would have chosen — so the cap costs the target
hardware **nothing**; it only bites a box with more cores than the suite can
use. Pinned by `test_the_default_worker_count_is_cpu_count_capped`, whose
parameter ids are `orin-nx-8-core / at-the-cap / dev-box-192-thread /
single-core`. No x86 or CUDA assumption is added: the only platform call is
`os.cpu_count()`.

**SEEDED RED (A3).** Seed = the default arm returns `"auto"` (the pre-addendum
behaviour):

```
FAILED test_the_worker_count_is_never_auto_and_never_nonsense[] and [   ]
FAILED test_the_default_worker_count_is_cpu_count_capped[orin-nx-8-core]
FAILED …[at-the-cap] …[dev-box-192-thread] …[single-core]
6 failed, 8 passed in 0.26s → restore verified c845f374124b6afe… → 14 passed
```

## Row A4 — measurement rule adopted for the remaining rows

Every pytest this session runs — one test or a whole suite, live tree or clone —
goes through `~/.cache/parcel-guard/pytest_guard.sh --label xd1` (refuses
`-n auto`, caps `-n` at 8, 40 GB cgroup, one flock for suite-scale runs, 30-min
timeout, `TMPDIR` unset by the caller). `~/.cache/parcel-xd1/twophase.sh` was
edited from `-n auto` to `-n 8` for the same reason. Consequences, stated once
and repeated in each row below:

* **Every timing row is an `-n 8` number and is NOT comparable to P0-E's 51.9 s**
  (which was `-n auto` = 192 workers on an otherwise-loaded box). The
  pre-registered W2/W3/W4 targets were written against `auto`; they are measured
  as written and a miss is reported as a **miss**, with the worker count named.
* A row whose **meaning** requires `auto` is reported **NOT MEASURED** with the
  reason, never estimated.
* Every suite-scale command is listed in §"Suite-scale runs" at the end of this
  document with its wall-clock, so the verifier can audit
  `~/.cache/parcel-guard/guard.log` against it.

---

# What changed

```
$ git diff --stat HEAD -- <OWNS>
 scripts/ci_gate.py           | 211 +++++++++++++++++++-
 tests/conftest.py            | 217 ++++++++++++++++++++
 tests/test_ci_gate.py        | 464 ++++++++++++++++++++++++++++++++++++++++++-
 tests/test_p1b_map_learns.py |  20 +-
 4 files changed, 901 insertions(+), 11 deletions(-)
new files: tests/_repo_write_guard.py (363 lines), tests/test_xd1_repo_write_guard.py (306)
```

* **`scripts/ci_gate.py`** — **THREE hunks, and after the correction pass all
  three are inside `CARD XD-1` markers** (the third was unmarked until the
  verifier found it — F1):
  1. `# ---- CARD XD-1 nesting mark` (`:551-560`) — the one line inside
     `run_pytest` that stamps `PARCEL_CI_GATE_NESTED=1` into every child.
  2. `# ---- CARD XD-1 default-suite two-phase runner` (`:603-791`) —
     `default_suite_phases`, `resolve_xdist_workers`, `evaluate_default_suite`,
     `XDIST_*`, `CI_GATE_NESTED_ENV`.
  3. `# ---- CARD XD-1 default-suite row` (`:1971-1986`) — the call site: ONE
     tuple in `run_commit_tier`, which sits **inside GATE-0's containment
     region** because a call site cannot live anywhere else. The stage NAME is
     unchanged, so `COMMIT_TIER_STAGE_NAMES`, `run_stage`'s containment and
     every `--json` consumer are untouched, and no other stage in that tuple is
     this card's.
* **`tests/test_ci_gate.py`** — the semantic partition tests, the phase
  behaviour tests, and the addendum block (A1 fixture stub + `EXPLODING_VICTIMS`
  correction, A2's four tests, A3's five).
* **`tests/conftest.py`** — ONE marked region, `BEGIN/END XD-1 repo-write
  census` at lines 190–307, strictly below HY-1's region. HY-1's region
  (lines 94–186) is **byte-identical** before and after every pass of mine:
  `sha256(sed -n '94,186p') = 259937b097256c35f83296c640337a3c8bef5fbe44aba9bec56f7583949107ba`.
  Every editing pass took `mkdir ~/.cache/parcel-batchb/lock-conftest.py` with an
  `owner` file and released it immediately.
* **`tests/_repo_write_guard.py`** (new) — the census module. No product import,
  no allowlist: `.gitignore` is the authority and `git` is the oracle.
* **`tests/test_p1b_map_learns.py`** — the AUDIT_WAVE2 carried finding: the
  two-line literal pin on `RobotRuntime.start` replaced by two offset
  comparisons (S4/S5).
* **`src/parcel_robot/runtime.py`** — a COMMENT only, in this card's hunk at
  `~4328`, recording why the pin was loosened. (The file's other hunks are
  ROAM-2's; untouched.)

# How it was verified

Every command through `~/.cache/parcel-guard/pytest_guard.sh --label xd1`, with
`env -u TMPDIR`, in the scratch clone at `e15e466` for suite work and the live
tree for this card's own targeted tests. **Suite-scale runs, in order, auditable
against `~/.cache/parcel-guard/guard.log` (13 rows with `label=xd1 targeted=0`):**

| # | Time | Command | Wall |
|---|---|---|---|
| 1 | 06:25:09 | `pytest -q tests/test_ci_gate.py` (live tree) | 19.4 s, **rc=1** — 90 passed + FZ-1's stale parity literal (see Cross-card) |
| 2 | 06:30:30 | `run.sh baseline w1_serial PARCEL_REPO_WRITE_GUARD=off` | **385.3 s** (W1) |
| 3 | 06:38:12 | `run.sh twophase p1 …` | **75.3 s** (W2, D2/D4) |
| 4 | 06:39:42 | `run.sh twophase p2 …` | 74.8 s |
| 5 | 06:41:02 | `run.sh twophase p3 …` | 77.1 s |
| 6 | 06:44:14 | `run.sh baseline d5_shuffle … XD1_ADDOPTS="-p xd1_shuffle"` | 380.0 s (D5) |
| 7 | 06:50:58 | `run.sh twophase d67_census …` (D6 + first D7) | 77.2 s |
| 8 | 06:55:27 | `pytest -q tests/test_xd1_repo_write_guard.py` | 0.2 s |
| 9 | 06:55:49 | seed S1, RED then census mode (2 runs, clone) | 0.1 s each |
| 10 | 06:59:39 | `pytest -q tests/test_xd1_repo_write_guard.py` (after the recorder fix) | 0.2 s |
| 11 | 07:00:44 | `run.sh twophase d7_census_v2 …` (**the D7 census that is claimed**) | 81.9 s |
| 12 | 07:03:17 | `pytest -q tests/test_xd1_repo_write_guard.py tests/test_p1b_map_learns.py` | 0.7 s |
| 13 | 07:0x | `pytest -q tests/test_ci_gate.py` (final) | 18.1 s, **rc=1** — same single FZ-1 red; FZ-1 has since fixed the literal and the file is green |
| 14 | 07:4x | correction pass: `pytest -q tests/test_ci_gate.py tests/test_xd1_repo_write_guard.py` | see §Correction pass |

Plus 12 targeted (`::`) runs for the seeds A1/A2a/A2b/A3/S2/S3/S4/S5/REC1/REC2
and the A1–A3 unit tests — every one of them under the wrapper. **No run was
backgrounded, no `-n auto` was issued from any script or command, no
`ci_gate.py --tier` was ever run, and no wrapper run exited 137.** Peak
available memory never dropped below ~230 GB.

**Seeded-RED, one per guard, all restored byte-identically by `sha256sum` with
`__pycache__` purged and the test re-run green:** A1 (the fixture hole), A2a/A2b
(the nesting mark and the refusal), A3 (the worker cap), REC1/REC2 (the recorder
`dir_fd` and src/dst defects), S1–S5 (the pre-registered five). Ten seeds, all
on the product or on the fixture that had the hole, none on a mock.

# What this does NOT prove

* **Nothing about 192 workers.** Every parallel number here is `-n 8`. Three of
  P0-E's seven divergences are per-process-state families whose failure
  probability rises with worker count; at `-n 8` they do not fire, and the
  arm that would settle it is forbidden on this host. After A3 the gate's own
  default is `min(cpu_count, 16)`, so **the untested regime is not one the gate
  can reach by itself** — but an operator who pins `PARCEL_XDIST_WORKERS=192` is
  in territory this card did not measure.
* **Nothing about the tier's end-to-end wall-clock (W4).** Not measured, by rule.
* **Nothing about the live working tree's verdict.** The clone lacks the owner
  store, the git-ignored asset trees and four other cards' uncommitted work, and
  it carries **15 pre-existing failures** at `e15e466`. Every row above is a
  same-rig comparison; none is a claim that the suite is green.
* **The repo-write guard cannot see a child process's writes** — only the weaker
  session-level `git status` net can, and it names files, not tests. In this
  card's runs it named nothing, which is a fact about these tests, not a proof
  of coverage.
* **`test_the_runtime_region_wires_all_three_seams` compares offsets in the
  WHOLE `runtime.py` text**, not within `RobotRuntime.start`. It is a source-text
  pin, in the style of the assertions above it in that test; it would be
  satisfiable by an occurrence in another method. Loosening it further was not
  this card's business, and tightening it to `inspect.getsource(start)` is a
  one-line change for whoever owns that test next.
* **D6 publishes hazards, not failures.** The two environment leaks caused no
  divergence in any arm measured here.

# Deviations from the pre-registration and the design

1. **`PREREGISTRATION.md` is byte-identical** (`sha256 b8097c43…a7d5`,
   re-verified at the start and end of this session). Rows were measured as
   written.
2. **W4 NOT MEASURED** — anti-crash rule 3 (see that row). A miss by
   circumstance, reported as not-measured rather than estimated.
3. **A4 supersedes the implicit `-n auto` of the design for all timing rows.**
   Declared per row.
4. **`DESIGN.md` §(c), §(e) and §(g) were edited in this pass** — the design's
   claim "no worker count is written down; `-n auto` resolves from
   `os.cpu_count()`" was the third of the three faults that OOM-killed the host,
   and A2/A3 replaced it. The edit says so in place, as the brief requires.
5. **The repo-write guard's default is `census`, not `on`** — this is the
   pre-registered D7 decision rule executing, not a change of mind (row D7).
6. **The D7 census was re-run after a defect was found in this card's own
   recorder** (rows D7/REC1/REC2). The pre-fix census is withdrawn, not amended.
7. **`census.py`, the measurement instrument, was corrected mid-run** (row D2)
   before any published number was read from it.

# Cross-card findings — 2026-08-23

* **From HY-1's executor → fixed here.** `Recorder._record`'s `os.path.abspath`
  charged `dir_fd`-relative audit paths (every `shutil.rmtree`) to the
  repository. Reproduced, fixed, seeded RED, and a second defect (src vs dst on
  `symlink`/`link`) found while verifying the first. Row D7. **Thanks — it would
  have shipped a guard that cried wolf on every `rmtree` in the suite.**
* **From the orchestrator → already closed.** `tests/test_xd1_repo_write_guard.py`
  I001 was fixed at the source at 06:5x; the tree-wide fingerprint census in row
  L1 (run 07:0x) shows exactly the 7 baseline fingerprints, new 0.
* **To FZ-1 (`task_13`) — one red test, in MY file, caused by YOUR asset.**
  `tests/test_ci_gate.py::test_release_parity_is_green_on_the_committed_tree`
  asserts `evaluate_release_parity().extra["checked"] == 91` ("90 packaged
  assets + 1 side mirror", the sentinel convention: a LITERAL). It now measures
  **100**, exactly `91 + 9`, and
  `src/parcel_robot/runtime_assets/prompts/personalities/_frozen/` holds
  **9 new files**. The gate row itself still **passes**; only the literal is
  stale. **I did not re-pin it**: the number is FZ-1's inventory claim, and
  re-pinning it from this card would be me certifying an asset count I have not
  verified. One-line fix, `tests/test_ci_gate.py:649`, `91` → `100`, in FZ-1's
  pass or the integrator's.
* **To VENUE-1 / P1-C owners (row D6).** Two tests leak an environment variable
  into their worker: `test_p1c_enroll_appearance.py::test_the_camera_path_refuses_cleanly_when_there_is_no_camera`
  (`LD_LIBRARY_PATH`) and
  `test_venue1_physical_venue.py::test_a_physical_venue_refuses_a_simulation_map`
  (`PARCEL_ONLINE_MAP_PATH`). `monkeypatch.setenv` instead of `os.environ[...]`
  is the whole fix.

# Handoffs

1. **INTEGRATOR — `tests/conftest.py` and `tests/_repo_write_guard.py` are ONE
   commit.** The conftest region imports `_repo_write_guard` at module scope; if
   the conftest lands without the module, **collection breaks for the entire
   suite**. Same for `tests/test_xd1_repo_write_guard.py` (it imports the module
   too, but that one only breaks its own file).
2. **INTEGRATOR — the commit tier's `default-suite` row will now read
   `-n 16 --dist loadfile [derived min(cpu_count=192, cap=16)]`** unless
   `PARCEL_XDIST_WORKERS` is set in the environment. That is the first `--tier
   commit` in which W4 becomes a number:
   `env -u TMPDIR .parcel/bin/python scripts/ci_gate.py --tier commit`.
   **No wall-clock is offered for 16 workers — that regime is unmeasured, and
   A4 forbids estimating one.** What was measured: **75.3 s at `-n 8`** against
   a **385.3 s** serial baseline. Run with `PARCEL_XDIST_WORKERS=8` to
   reproduce this card's number exactly.
3. **GATE-0b (`task_30`) — `scripts/ci_gate.py` is now safe to share.**
   **All THREE XD-1 hunks are inside `CARD XD-1` markers — `nesting mark`
   (`:551-560`), `default-suite two-phase runner` (`:603-791`), and
   `default-suite row` (`:1971-1986`, inside GATE-0's containment region) — and
   GATE-0b must not edit inside ANY of the three.** Add your skip-list region
   anywhere else. **Note for your own design:** `run_pytest` now stamps
   `PARCEL_CI_GATE_NESTED=1` into every child, and `evaluate_default_suite`
   refuses when it sees it — if a GATE-0b row ever wants to run the default
   suite from inside a pytest, it will get a hard `error` row, on purpose.
4. **FZ-1** — the release-parity literal above.
5. **The three D7 offender files' owners** — `tests/test_nav_instruct_scene_gen.py`
   (8 tests, `configs/scenes/generated/`), `tests/test_stage0_command_addendum.py`
   (writes the TRACKED `scrum/20260814/task_1/STAGE0_COMMAND_ADDENDUM.md`),
   `tests/test_barn_v9_supervisory_gap_s2_bundle.py` (writes a TRACKED
   `evals/external/…` source). Each is correct alone and each is a neighbour-
   reddening hazard at one-worker-per-test. When the last one is fixed,
   `read_mode()`'s default becomes `on` and the guard is a gate. Until then,
   `PARCEL_REPO_WRITE_GUARD=on` reproduces the failures on demand.
6. **The rig is reusable and is left in place**: `~/.cache/parcel-xd1/`
   (`tree/` at `e15e466`, `sync.sh`, `run.sh`, `product_run.py`, `census.py`,
   `seed.sh`, `xd1_shuffle.py`, `xd1_state_census.py`, `runs/`). The stale
   `runs/census_v3*` files are the **05:38 crash's** partial output; they are
   kept as evidence of the failure and **no number in this document comes from
   them**.

# Owner / integrator-gated rows

* **W4** — `env -u TMPDIR .parcel/bin/python scripts/ci_gate.py --tier commit`
  (integrator, once, tree quiescent). Not run by this card, by rule.
* **The nightly tier** is deliberately untouched and still serial
  (`test_the_nightly_default_suite_is_still_serial_and_that_is_deliberate`
  is where flipping it becomes a visible decision).

# Resumed from

This card had **four** predecessors, all killed by the same failure, and the
fourth was killed by this card's own defect.

* **1st (08-22 ~15:2x–15:36, dispatch 799cb356).** Wrote `PREREGISTRATION.md`,
  built the scratch clone at `~/.cache/parcel-xd1/tree`, and landed the first
  `scripts/ci_gate.py` two-phase runner (+121, **no marked region**) and
  `tests/test_ci_gate.py` (+156). **Kept**: the pre-registration verbatim (its
  sha256 is pinned in this document and re-verified at the end of this session),
  the clone, the runner's shape, the partition tests.
* **2nd (08-22 16:17–16:23, parcel-4a).** Wrapped the runner in its marked
  region, wrote `tests/_repo_write_guard.py` and the conftest XD-1 region,
  cleaned the RUF100/ISC004 debris. **Kept** all of it.
* **3rd (08-22 17:55–17:58, parcel-dd).** Wrote `DESIGN.md` (17:51) and
  `tests/test_xd1_repo_write_guard.py`. **Kept**; `DESIGN.md` was edited in this
  pass only where A2/A3 forced it, and the edit says so in place.
* **4th (08-23 05:4x–05:38:42, parcel-81).** Closed **row D1** (phase partition
  9297 + 10 = 9307, exact set equality, no new markers) and wrote
  `xd1_shuffle.py` / `xd1_state_census.py`. **Kept** row D1 as written and both
  instruments. Its census run is what killed it: five chained `pytest -n auto`
  suites, 986 processes, 237 GB, kernel OOM. `runs/census_v3*` is that run's
  wreckage — kept as evidence, **never read for a number**.
* **5th (this session, 08-23 06:2x–07:0x, parcel-6c).** Nothing was reverted.
  Closed the owner-mandated addendum **A1–A3** (with A1's seeded-RED proof that
  the hole was real, obtained without starting one suite), adopted **A4**, then
  measured **W1, W2, W3, D2, D3, D4, D5, D6, D7, L1** and the five pre-registered
  seeds; reported **W4 NOT MEASURED**; fixed a defect in this card's own
  recorder that a peer found, re-ran D7 after it, and applied the pre-registered
  D7 decision rule (guard ships opt-in). **Discarded**: nothing, except two
  measurement-instrument behaviours that were wrong (`census.py`'s node-id
  regex; the pre-fix D7 census) — both replaced and both disclosed above rather
  than quietly overwritten.

---

# Correction pass — 2026-08-23 07:4x EDT

Verifier verdict **ACCEPT-WITH-NOTES** (`~/.cache/parcel-verify/xd1/VERDICT.md`):
4 FIX, 0 HOLD. All four applied; no product logic in the three recursion stops
changed; `PREREGISTRATION.md` still byte-identical
(`b8097c4351e6e9e82958f60c1e86e502d9df614dbf6a8d96d8f606a1fef7a7d5`).

**F1 — the third `ci_gate.py` hunk was unmarked.** The verifier is right: the
`run_commit_tier` `("default-suite", …)` row was outside every `CARD XD-1`
marker and sits **inside GATE-0's containment region**, and the status doc's
"two marked regions and nothing outside them" was false as a statement of the
diff. The row is now wrapped in `# ---- CARD XD-1 default-suite row` …
`# ---- END CARD XD-1 default-suite row` (`scripts/ci_gate.py:1971-1986`); the
row itself was **not moved and nothing else in `run_commit_tier` was touched**.
`grep -n "CARD XD-1" scripts/ci_gate.py` → `551, 560, 603, 791, 1971, 1986`.
The claim is corrected in this document (§What changed) and in `DESIGN.md` §(b),
and handoff 3 now says explicitly that **GATE-0b must not edit inside any of the
three regions**.

**F2 — `.hypothesis` in `_HOT_SKIP` was a private exemption on a fresh clone.**
It is ignored on a developer box only because hypothesis writes its own
**untracked** `.hypothesis/.gitignore` at first run, so on a clean checkout —
GATE-0b's PASS-row premise — `_HOT_SKIP`'s stated premise ("every one of these
is already ignored, so the filter changes no verdict") was untrue and
`test_the_hot_path_filter_is_a_speed_trick_and_not_an_exemption_table` was RED.
Fixed where the guard says exemptions belong: **the tracked `.gitignore`**.

```diff
 .pytest_cache/
 .ruff_cache/
+# XD-1: _HOT_SKIP premise; hypothesis' runtime .gitignore is not tracked
+.hypothesis/
 .tmp_ci/
```

*Seeded both ways* on a throwaway checkout with **no `.hypothesis/`**
(`~/.cache/parcel-xd1/f2seed`: byte-identical `tests/_repo_write_guard.py`,
`tests/test_xd1_repo_write_guard.py`, `.gitignore`, its own `git init`;
`_repo_write_guard.__file__` and `REPO` verified inside the scratch):

```
BEFORE the line: FAILED …::test_the_hot_path_filter_is_a_speed_trick_and_not_an_exemption_table
                 Left contains 1 more item: {'.hypothesis/probe': 'w'}     1 failed in 0.12s
AFTER  the line: 1 passed in 0.10s
                 $ git check-ignore -v .hypothesis/probe
                   .gitignore:11:.hypothesis/   .hypothesis/probe
live tree after: .gitignore:11:.hypothesis/   .hypothesis/probe   (the TRACKED rule now
                 answers, not the runtime .hypothesis/.gitignore)
```

**DEVIATIONS, both declared.** (i) The repo root `.gitignore` is **outside this
card's OWNS**; this one line is **integrator-authorised** (verdict F2 remedy,
coordinator's instruction). It is the only edit to it. (ii) The instruction said
"one line … with a trailing comment". **`.gitignore` has no trailing comments —
`#` only starts a comment at the beginning of a line** — and the first attempt
proved it: with the comment appended, the pattern read literally
`.hypothesis/  # XD-1: …`, `git check-ignore` matched nothing and the test was
**still RED**. The comment is therefore on its own line above the rule; the rule
itself is the single line asked for. The `_HOT_SKIP` docstring now records the
finding and cites the seed.

**F3 — the D2 sentence overstated the bound.** "non-divergent at the worker
count the gate will actually use" is wrong: non-divergence was proved at **8**,
while the gate's default *on this host* is **16** (`min(192, 16)`) and
unmeasured. Row D2 now states it exactly — clean at 8; 16 untested; 8 is also
the Orin's default, i.e. the measured count is the one the target hardware will
use; 192 unreachable without an explicit operator pin — consistent with §"What
this does NOT prove" and handoff 2.

**F4 — the stale `-n auto` section comment** at `tests/test_ci_gate.py:1102`
still described the pre-addendum design ("runs `-n auto`", "192-way
contention"), contradicting A3 four screens below. Rewritten to
`-n min(cpu_count, XDIST_MAX_WORKERS)` — 16 here, 8 on the Orin, never `auto`.
(The other `auto` mentions in that file are history at `:1269` and the A3
refusal tests at `:1451/:1468`; both correct, both left.)

**Notes also closed:** N1 (audit-table rows 1 and 13 now record `rc=1` and name
FZ-1's stale literal as the single red — FZ-1 has since fixed it), N7 (handoff 2
no longer estimates a wall-clock for the unmeasured 16-worker regime), N9 (row
D4 now carries the A4 `-n 8` annotation that W2/W3 already had). N2–N6, N8, N10
are read-only observations and stand as written in the verdict.

**Verification of this pass:**

```
$ env -u TMPDIR pytest_guard.sh --label xd1 .parcel/bin/python -m pytest -q \
      -p no:cacheprovider tests/test_ci_gate.py tests/test_xd1_repo_write_guard.py
114 passed, 1 warning in 13.65s          (91 + 23; zero failures — FZ-1's literal is fixed)

$ .parcel/bin/ruff check <the six XD-1 files>      All checks passed
$ .parcel/bin/ruff check .                          12 errors, 7 fingerprints, new [] missing []
$ git diff HEAD -- scripts/ci_gate.py | grep '^+.*noqa'     (none — this card adds no noqa)
```

`git status --porcelain` for this card's files gained **exactly one** new entry
across the pass: ` M .gitignore`.
