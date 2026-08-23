# GATE-0b — design · Claude Opus · 2026-08-23 07:5x EDT

Card `scrum/20260822/task_30/README.md`. Written before any code, per the
owner's rule. Every claim below is tied to a `file:symbol`.

## (a) Purpose

GATE-0 made a fresh clone *print* a verdict; the verdict is still `RESULT:
FAIL` for 51 pre-existing reasons, none of them a product defect. Almost all
of them are one sentence: **a test whose evidence is not in the checkout fails
instead of saying what it needs.** This card turns that sentence into a
mechanism — a declared external root, a skip with a named reason, and a gate
row that prints the list — so that `ci_gate.py --tier commit` gives the same
honest verdict on this dev box, on the hosted `ubuntu-latest` runner (B20) and
on the Go2's Jetson Orin. Separately it stops
`evals/nav_instruct/run_nav_instruct_v1.py` appending a provenance row to
`evals/nav_instruct/results/ledger.jsonl` on runs that were never meant to be
provenance (ROAM-1 wrote two; `AUDIT_WEEK1_FABLE.md` §ROAM-1 finding 4).

## (b) Architecture fit — the seams

1. **`tests/_external_roots.py` (new): `EXTERNAL_ROOTS`, `skip_unless()`.**
   One table, `name -> {root, hint}`, where `root` is repo-relative and `hint`
   is the exact command that generates it. `skip_unless(name)` returns a
   `pytest.mark.skipif` whose `reason` is derived from the same entry, so the
   condition and the printed reason cannot drift. Test modules import it as a
   top-level module (`tests/` is on `sys.path` under pytest —
   `tests/conftest.py:212-213` does exactly this for `_repo_write_guard`).
   Consumers **as shipped** (corrected against the draft, which said one
   module-level `pytestmark =` per file): a per-TEST `@skip_unless("<name>")`
   decorator — **15** external-eval files (`tests/test_barn_*`,
   `tests/test_run_barn_*`, `tests/test_habitat2020_*`) carrying **28**
   decorations, plus 2 in `tests/test_truth1_texts.py` = 30 in the tree, and 16
   files importing the table. Per-test because most of these files are mixed:
   three of the four `test_barn_v10_planner_profile` tests need the bundle root
   and the rest are unit tests that pass in any clone, so a module-level
   `pytestmark` would have silenced the passing ones. `tests/test_threewe_*`
   needed no decoration in the end — the carve-out (seam 3) makes its evidence
   tracked. No change to any test body.
2. **`scripts/ci_gate.py` — ONE new region `# ---- CARD GATE-0b skip-list
   reporting`**, placed after XD-1's runner region ends (`:791`) and before
   the "Pure artifact checks" header, holding `SKIP_TABLE_PATH`,
   `collect_external_root_declarations()` (an `ast.literal_eval` of that one
   table plus a scan of `tests/*.py` for `skip_unless("<name>")` — no import,
   no subprocess) and `evaluate_skip_list()`. It is registered as a
   **report-only** row (`GateResult(hard=False, …)`), so
   `GateResult.gating_red` is False by construction and the row can never
   change an exit code. *(Corrected during implementation, per the COMMON
   brief: the status is `pass`, not `report` — `tests/test_ci_gate.py`, XD-1's
   closed and verified file, asserts every stage of a clean tier is `pass`, and
   `hard=False` is what carries the non-gating property; `GATE0B_STATUS.md`
   deviation 4.)* Registration costs one name in
   `COMMIT_TIER_STAGE_NAMES:1888`, one thunk in `run_commit_tier`'s stage
   tuple, and one `hard=` argument in that runner's loop so a crash in the
   reporting row cannot gate — **four** marked hunks, not one (deviation 3);
   each outside XD-1's three regions (`:551-560`, `:603-791`, and the
   default-suite row) and each inside the GATE-0b markers.
   `tests/test_ci_gate.py` asserts produced names *against that constant*
   (`:937,992,1038,1320,1358`), so the contract holds with no edit to XD-1's
   test file.
3. **`evals/external/.gitignore:1`** — `results/*` with negations only
   (`!results/barn_ros2/**`, `!results/threewe/**`), so the 3.1 MB
   `results/runs/` and the regenerated `results/latest_report.json` stay
   ignored *by construction*; the comment block above it is the manifest
   (which subtrees, how many files, why the rest stays out) — GATE-0's shape
   at `.gitignore:63-91`.
4. **`evals/nav_instruct/run_nav_instruct_v1.py`** — `LEDGER:61` becomes
   `resolve_ledger_path(args, env)`; `main()` gains `--ledger PATH` and
   `--no-ledger`; the append at `:442-443` becomes conditional. Readers of
   that ledger are `scripts/ci_gate.py:evaluate_nav_instruct_candidate:1835`
   (diffs report ids before/after) and `evaluate_hard_safety` via
   `NAV_LEDGER:387` — **the default is unchanged**, so both keep reading the
   file they read today.
5. **Composition with batch A/B and the safety core.** Nothing here is on a
   robot path: no `runtime.py`, no `reactive_safety`, no `core/hard_stop`, no
   VENUE-1/CAP-1/OT-2/DOOR-1 region. The only shared file is
   `scripts/ci_gate.py`, entered by one marked region that never reaches
   inside XD-1's; the only shared behaviour is the ledger's default path,
   which does not move.

## (c) Interfaces and contracts

* `tests/_external_roots.EXTERNAL_ROOTS: dict[str, dict[str, str]]` —
  `{"barn-policy-bundles": {"kind": "path", "target": ".cache/external-evals/
  runtime/barn-parcel-bundles", "hint": "generate it: …"}}`. `kind` is `path`
  or `module` (an optional wheel — added during implementation for the
  `pyrealsense2` rows the baseline surfaced). `skip_unless(name) ->
  pytest.MarkDecorator`; reason format
  `"needs-external-root: <target> (<noun>) is absent — <hint>"`.
* `ci_gate.evaluate_skip_list(*, tier="commit", root=REPO) -> GateResult` —
  name `skip-list`, `hard=False`, detail `"N declared external root(s), M
  absent on this host → K test module(s) skip with a named reason"` plus two
  indented lines per absent root (the modules, then the hint).
  `extra={"declared", "absent", "modules_skipped", "undeclared_used"}`.
* `run_nav_instruct_v1`: `--ledger PATH` (default the tracked ledger),
  `--no-ledger` (mutually exclusive with `--ledger`); env
  `PARCEL_NAV_LEDGER=<path|off>` for a harness that cannot edit the argv.
  Precedence: explicit flag > env > default. **Defaults are byte-unchanged.**
* The guard: when the process is a pytest child (`PYTEST_CURRENT_TEST` in the
  environment) and the resolved target is the tracked repo ledger *by
  default*, the run withholds the append, prints one line naming the reason
  and the two overrides, and still writes its report and exits 0. An
  **explicit** `--ledger <tracked path>` is honoured — a person who typed the
  path is not overruled (the rule XD-1 chose for `resolve_xdist_workers`).
  This is a provenance rule, not a fail-closed behaviour: nothing refuses.

## (d) Data flow and lifecycle

Collection time: `skip_unless` stats the root once per module; absent → the
module's tests report SKIP with the reason, so the default-suite phases in
`evaluate_default_suite` count them as skips and return 0. Gate time:
`evaluate_skip_list` re-derives the same table from source text (no import, no
process, no lock, ~60 file reads) and prints it under the table in
`summarize()`. Run time: the nav runner opens the ledger `"a"` exactly where
it does today, or not at all. No threads, no locks, no sockets, no sims. No
test in this card writes under the repo.

## (e) Hardware compatibility (the HELD brief's requirement)

Three hosts must give the same verdict from the same command: this box
(x86-64, 3.12.13 in the clone), the hosted runner (`ubuntu-latest`, x86-64, no
GPU, `MUJOCO_GL=osmesa`, 20-minute timeout — `.github/workflows/ci.yml:57-84`),
and the Go2 EDU+'s **Jetson Orin NX (aarch64, 8 cores, JetPack, CPython
3.10)**, which has no RTX and no x86 wheels. The mechanism is host-independent
by construction: a declared root is a **path stat**, not a platform test, so a
row that needs CUDA, an x86-only wheel, a generated 21 GB corpus or a GPU
detector resolves to the same printed `skip-with-reason` on all three rather
than to a red; `evaluate_skip_list` calls no platform API beyond
`Path.exists`, and the ledger rule is argv/env only. XD-1's
`resolve_xdist_workers` already makes the Orin's default 8 workers. To
CONFIGURE: nothing. UNKNOWN: whether `ubuntu-latest` finishes the tier inside
20 minutes (B20 is the owner's click, measured there, never claimed here) and
the Orin's actual JetPack/CPython pair (TRUTH-1 F5/N10 record the same).

## (f) Test strategy → the pre-registered rows

`PREREGISTRATION.md` (written before the first gate run) carries: the per-root
table re-counted in the **baseline** run of my own clean clone; the class of
fix per root; the V9 decision; the PASS row; and two seeds. **S1**: an
external-root test with its `@skip_unless(...)` decoration removed goes RED in
the clone (proves
the marker is load-bearing, not decoration). **S2**: a `--minival --no-ledger`
run that still appends is caught by
`tests/test_nav_instruct_ledger_guard.py` (proves the guard, not the flag's
existence). Both seeds run on a byte-identical scratch copy with
`PYTHONPATH=<scratch>:<scratch>/src` and `__file__` verified inside it (the
TRUTH-1 standing rule), restored by sha256, `__pycache__` purged.

## (g) The V9 mode-bit decision, and what this design does NOT cover

**Decision: drop the mode-bit requirement for the TRACKED manifest; keep it
for generated roots.** `evals/external/generate_sampled_predictive_tracker_v9_
training.py:209` (`_require_immutable_regular_file`) rejects any write bit;
`evals/external/training/barn_sampled_predictive_tracker_v9/split.json` is
tracked `100644`, is `444` here only because the generator chmod'ed it at
creation (`:361`), and git checks it out `644` in **every** clone. A mode bit
that differs between the index, the dev tree and every clone is a statement
about the developer's umask, not about the data — and for a *tracked* file git
already is the immutability mechanism. The check stays as it is for the
generated corpora under `.cache/external-evals/**` that
`_freeze_generated_tree:214-228` actually freezes. `chmod` in test setup was
rejected: it writes to the developer's checkout to satisfy an assertion about
the developer's checkout. **Outside the README's OWNS** — one keyword argument
at one call site, declared as a deviation in `GATE0B_STATUS.md`. The same
decision was applied a second time during implementation, to
`tests/test_threewe_contract_audit.py:28`'s `st_mode & 0o222 == 0` on evidence
this card made tracked; the sha256 pin on the line above it is the stronger
claim and it survives being cloned.

NOT covered: the hosted run itself (B20, owner's click); the 20-minute hosted
budget; vendoring any external corpus (21 GB — never); making the skipped
tests *runnable* on a clone (they need generated data, and generating it is
the hint the skip prints); any change to what the default suite selects
(`COMMIT_MARKERS` is untouched, so `tier-coverage` still balances).
