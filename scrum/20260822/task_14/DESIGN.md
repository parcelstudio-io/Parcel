# XD-1 — DESIGN: a two-phase commit tier (xdist without divergence)

**Card:** `README.md` · **Pre-registration:** `PREREGISTRATION.md`
(sha256 `b8097c43…a7d5`, VERBATIM) · **Executor:** Claude Opus (third resume)
· **Verifier:** Fable · **HEAD:** `e15e466`

## (a) Purpose

The commit gate takes 5–7 minutes because `default-suite` runs the whole
`not slow` selection in one serial pytest. P0-E measured `-n auto` at ~6× on
this host but found **seven tests that diverge under xdist**, so the gate
stayed serial. This card makes `default-suite` **two phases whose union is the
commit tier by construction** — a parallel phase for everything whose subject
is behaviour, and a serial phase for the tests whose subject is *wall-clock
duration* — and adds the guard for the defect **class** the seven were
symptoms of: a test that writes under the repository root (GATE-0's
`tests/test_unitree_asset_pack.py` probe, which reddened two innocent
neighbours at one-worker-per-test). Speed is the deliverable; **non-divergence
is the claim**.

## (b) Architecture fit

Seams touched, every hunk inside a marked region. **`ci_gate.py` carries
THREE, not one** — the verifier caught the third being unmarked (F1, 07:4x) and
it is marked now, because GATE-0b edits this file next and needs the seam
unambiguous:

* `scripts/ci_gate.py:default_suite_phases()` / `:resolve_xdist_workers()` /
  `:evaluate_default_suite()` — new, inside `# ---- CARD XD-1 default-suite
  two-phase runner` (`:603-791`).
* `scripts/ci_gate.py:run_pytest()` — one line, inside `# ---- CARD XD-1
  nesting mark` (`:551-560`); addendum A2.
* `scripts/ci_gate.py:run_commit_tier()`'s `("default-suite", …)` stage tuple —
  the CALL SITE, inside `# ---- CARD XD-1 default-suite row` (`:1971-1986`).
  It necessarily sits **inside GATE-0's containment region**, since that is
  where the stage list lives; it is wrapped by `run_stage()` (GATE-0's
  containment: an evaluator that raises becomes a hard `error` row, never a
  lost summary). The stage name stays `"default-suite"`, so
  `COMMIT_TIER_STAGE_NAMES` and every `--json` consumer are unchanged, and no
  other stage in that tuple is this card's.
* The phase expressions are derived from **`scripts/ci_gate.py:COMMIT_MARKERS`**
  — the same constant `evaluate_tier_coverage()` uses. This is the composition
  rule that matters: `tier-coverage` (card R26) asserts every collected test is
  in the commit tier or the nightly tier; if the two phases were literals they
  could drift from `COMMIT_MARKERS` and `tier-coverage` would still pass while
  tests fell out of the run.
* `scripts/load_guard.py:contention_reason()` and the `load_sensitive` marker
  (card R26) are **reused, not redefined**. `tests/conftest.py:pytest_runtest_setup`
  already skips a `load_sensitive` test under contention with a measured reason;
  this card gives those tests a phase in which contention is absent.
* `tests/conftest.py` — one new marked region `BEGIN XD-1 repo-write census`,
  appended strictly **below** HY-1's `BEGIN HY-1 sim guard` region, which it
  does not touch. Both regions are plugin hooks on the same `conftest`; they
  are disjoint (HY-1 owns `pytest_runtest_logstart/logfinish` + a module-scoped
  fixture; XD-1 owns a function-scoped autouse fixture +
  `pytest_sessionstart/sessionfinish`).
* `tests/_repo_write_guard.py` — new module, no product import. Uses
  `sys.addaudithook` for the in-process net and `git check-ignore`/`git ls-files`
  for classification, so it carries **no allowlist** (board standing rule 1).
* `tests/test_p1b_map_learns.py::test_the_runtime_region_wires_all_three_seams` —
  the AUDIT_WAVE2 carried finding: its literal
  `"…_attach_configured_camera_ingress()\n            self._thread"` pin
  over-specified `RobotRuntime.start`, which is exactly the composition root
  batch A's regions (VENUE-1's camera ingress, CAP-1's admission block, DOOR-1,
  OT-2) keep extending. Replaced by two offset comparisons that pin the
  ordering the card actually needs. Nothing in `runtime.py` changes except a
  comment recording why.

The **safety core is untouched**: no `reactive_safety`, no `core/hard_stop`, no
hard gate other than `default-suite`. `evaluate_unitree_assets` (GATE-0) and
`run_stage` are untouched.

## (c) Interfaces and contracts

```python
COMMIT_MARKERS = "not slow"                       # existing, unchanged
XDIST_WORKERS_ENV = "PARCEL_XDIST_WORKERS"        # "" -> derived, see below
XDIST_MAX_WORKERS = 16                            # addendum A3
XDIST_DIST_MODE   = "loadfile"
CI_GATE_NESTED_ENV = "PARCEL_CI_GATE_NESTED"      # addendum A2

def default_suite_phases(commit_markers: str = COMMIT_MARKERS) -> tuple[str, str]
    # -> (f"({m}) and not load_sensitive", f"({m}) and load_sensitive")

def resolve_xdist_workers(explicit=None, env=None) -> tuple[str, str]
    # -> (workers, provenance); NEVER "auto"

def evaluate_default_suite(*, tier="commit", env_extra=None,
                           timeout=1800, workers=None) -> GateResult
    # extra = {"returncodes": {...}, "workers": str,
    #          "workers_provenance": str, "seconds": {...}}
    # or, nested: status "error", extra = {"nested": True}
```

**Addendum A2/A3 (2026-08-23, owner-mandated; this design was changed by what
the implementation found).** The design above said "no worker count is written
down; `-n auto` is resolved by xdist from `os.cpu_count()`". That was wrong in a
way that cost the host four times: `auto` is **192 workers here**, and while
this card's `ci_gate.py` edit was uncommitted, `tests/test_ci_gate.py`'s
`fast_commit_tier` fixture did not stub the new evaluator — so the gate's own
self-tests ran the whole suite, which ran it again, 986 processes and 237 GB
deep, and the kernel OOM-killed every session on the box. So:

* `run_pytest` stamps `CI_GATE_NESTED_ENV=1` into every child (one line, its own
  marked region in the shared driver); `evaluate_default_suite` refuses on entry
  with a hard `error` row when it sees it. `_pytest_gate`'s bounded node-id runs
  stay allowed nested.
* the worker count is `min(os.cpu_count(), XDIST_MAX_WORKERS)` by default and
  never the string `auto`; an explicit `PARCEL_XDIST_WORKERS` is honoured
  as written (including above the cap) and its **provenance** is recorded in the
  row, because a substituted worker count silently invalidates a timing row.

`--dist loadfile` (not xdist's default `load`) is a **correctness** choice:
module- and class-scoped fixtures — HY-1's per-file simulator census among them
— assume one file is one process, and `load` scatters a file's tests across
workers silently.

`tests/_repo_write_guard.py`: `PARCEL_REPO_WRITE_GUARD` ∈ `{on, census, off}`,
fail-closed on anything else (`RepoWriteGuardMisconfigured`), same discipline as
`scripts/load_guard.py`. `PARCEL_REPO_WRITE_CENSUS_OUT` is a path **prefix**
outside the repo; each writing process appends `.<pid>` so 192 workers cannot
interleave. **Default is decided by the pre-registered D7 rule, not by taste:**
`on` iff the census is empty after this card's fixes, else `census` (opt-in
`on`) with every offender named for its owner.

## (d) Data flow and lifecycle

`main(--tier commit)` → `run_commit_tier()` → `run_stage("default-suite", …)`
→ `evaluate_default_suite()` → two sequential `run_pytest()` subprocesses
(phase A `-n <workers> --dist loadfile -m "(not slow) and not load_sensitive"`,
then phase B `-m "(not slow) and load_sensitive"`, no `-n`). **Phase B always
runs, even when phase A is red** — a gate that stops at the first failure
reports half a verdict. Both return codes and both wall-clocks land in
`GateResult.extra`.

Inside a run: the audit hook is installed **once per interpreter** (CPython
cannot remove one), and `Recorder.active` — set by the autouse fixture around
each test — is what makes it a no-op between tests. Per test the cost is one
flag check per write-mode `open`; `git` is consulted only when a candidate
exists, i.e. never on a clean tree. `pytest_sessionstart/sessionfinish` take
two `git status --porcelain` snapshots **on the controller only**
(`hasattr(config, "workerinput")` guards the workers), so the second net costs
two git calls per *run*, not per worker.

## (e) Hardware compatibility — the Orin NX, not just this box

The runner must give the same **verdict** on a 192-thread x86-64 dev box, on a
hosted `ubuntu-latest`, and on the Go2 EDU+'s onboard **Jetson Orin NX 16 GB
(aarch64, JetPack, CPython 3.10)**. What makes that true:

* **The worker count is derived from the host, capped, and recorded — never
  assumed and never `auto`** (A3). `min(os.cpu_count(), 16)` is **8** on an
  Orin NX and 16 on this 192-thread box: on the target hardware the cap costs
  exactly nothing, because 8 cores is what `auto` would have chosen anyway. It
  bites only where the marginal worker buys ~nothing and costs 0.25 GB. The
  number and where it came from land in `extra["workers"]` /
  `extra["workers_provenance"]` and in the row detail.
  `PARCEL_XDIST_WORKERS` lets an operator pin it (a bisect wanting determinism;
  a thermally-limited Orin) and is honoured as written.
* **No x86 or CUDA assumption anywhere in the runner.** It spawns
  `PYTHON -m pytest`; the only platform-dependent call is `os.cpu_count()`.
  `--dist loadfile` and the marker expressions are pure strings.
  `requires-python = ">=3.10"` holds: the region uses only `from __future__ import
  annotations` generics, `sys.addaudithook` (3.8+), and `subprocess.run`.
* **The `load_sensitive` serial phase is what keeps timing rows honest on a
  small CPU — and it matters *more* there, not less.** On 8 cores, `-n auto`
  saturates the machine with 8 workers; a wall-clock pin measured then measures
  contention. Two bad outcomes are avoided: without the split those pins either
  (i) redden for reasons unrelated to the code, or (ii) — with R26's
  `contention_reason()` doing its job — **skip on almost every Orin run**, which
  is silencing coverage on precisely the host where latency is tightest. Phase B
  runs after phase A's workers have **exited**, so `contention_reason()` sees a
  quiet machine and the pin is measured for real.
* **UNCONFIRMED / configured:** the Orin's core count, clock policy and
  `nvpmodel` power mode are unverified — no robot hardware is on hand (only the
  reSpeaker XVF3800), and no fact sheet exists for the Go2 EDU+; the raw
  research fetched for the design study is at
  `~/.cache/parcel-fable-design/hw-facts/{go2,mid360,l2,remote}.txt`. The
  W2/W4 wall-clock **targets in `PREREGISTRATION.md` are dev-box numbers and are
  not claimed for the Orin**; what transfers is the *shape* (parallel phase +
  quiet serial phase) and the *verdict*, not the seconds. A tighter Orin budget
  is a `PARCEL_XDIST_WORKERS` setting plus a re-measured row, not a code change.
* The repo-write guard is host-independent by construction: `.gitignore` is the
  authority and `git` is the oracle, so a path that is scratch on one host is
  scratch on all of them.

## (f) Test strategy → pre-registered rows and seeds

| Row | How it is measured |
|---|---|
| W1/W2/W3/W4 | `~/.cache/parcel-xd1/twophase.sh` in the scratch clone at `e15e466`: serial baseline, then two-phase; load average recorded either side; worker count recorded |
| D1 | `--collect-only -q` for phase A, phase B and `-m "not slow"`; set union compared for exact equality |
| D2/D4 | `census.py diff` over three consecutive two-phase runs vs the serial baseline: failed/errored node-id sets identical |
| D3 | same parser: skipped/xfailed sets, parallel ⊆ serial ∪ {load-guard skips}; no new skip/xfail/deselect from this card |
| D5 | serial run with module order shuffled by `random.Random(20260822)` |
| D6 | process-state census (env / `sys.modules` / cwd) |
| D7 | `PARCEL_REPO_WRITE_GUARD=census` over the whole suite; rows merged from `<prefix>.<pid>` |
| L1 | `ruff check` fingerprints vs `scripts/ci_ruff_baseline.json` |

Seeds (each on a byte-identical scratch copy, restored by `sha256sum -c`,
`__pycache__` purged, re-run green): **S1** a test that writes a git-visible
file → the guard names *that test* and *that path*; **S2** phase A loses
`and not load_sensitive` → `test_no_wall_clock_assertion_can_reach_the_parallel_phase`
+ the partition test go RED; **S3** phase B deleted / made non-complementary →
`test_the_two_default_suite_phases_partition_the_commit_tier` goes RED; **S4**
`_p1b_install_learned_map()` moved after `_attach_configured_camera_ingress()` →
`test_the_runtime_region_wires_all_three_seams` RED; **S5** an unrelated
statement inserted between attach and the first `self._thread` → the same test
stays GREEN (the over-specification being removed).

The partition test evaluates both expressions **semantically** — over every
combination of `slow` × `load_sensitive` — rather than string-matching the
source, which would pass for any literal pair containing the right words.

## (g) Risks and what this design does NOT cover

* **A behaviour test marked `load_sensitive` is a silencing**, because R26's
  `pytest_runtest_setup` will skip it under contention. This design forbids it:
  the four non-timing divergences are fixed at the source or reported as misses.
  The verifier should check every marker this card adds against that rule.
* **The audit hook cannot see a child process's writes.** Covered only by the
  weaker session-level `git status` net, which names files, not tests.
* **The A2 nesting guard is one variable in one environment.** A child that
  scrubs its own environment, or a runner that spawns the gate outside
  `run_pytest`, is not covered — the guard closes the path that actually
  happened, not every conceivable one. The A1 fixture stub and the A3 cap are
  the other two independent stops.
* Wall-clock is measured while four sibling cards edit and test in the same
  tree. Load average is recorded next to every row; a load-caused miss is
  reported as a **miss**.
* Not covered: the nightly tier's wall-clock (deliberately still serial, with
  `PARCEL_LOAD_GUARD=off`); the hosted runner's timing; any Orin number; the
  live working tree's gate verdict (every measurement is from the clone, which
  lacks the owner store and the other cards' uncommitted work).
