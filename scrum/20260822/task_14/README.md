# Task 14 — XD-1: a 52-second commit tier (xdist without divergence)

**Executor:** Claude Opus · **Verifier:** Fable · **Board:** `../TASK_BOARD.md`
(P0 standing rules apply). **Evidence:** P0-E (`task_5/P0E_STATUS.md` §5) and
the Wave P0 verification note row E-1: `pytest -n auto` runs the default
suite in **51.9 s vs 317 s serial** (6.1×) but **7 tests diverge** under
xdist — `test_cpu_budget_proxy` ×2, `test_dynamic_costs` perf,
`test_fixa_transcript_persistence` kill switch, `test_runtime` streaming ×2,
`test_stage0_command_addendum` generator index — so the gate stayed serial.

## Why
Five to six minutes per commit-tier run is the single largest drag on
iteration speed this repo has; the audit's §9 target is "< 3 min". Six of the
seven divergences are load/timing-sensitive measurements or per-process state
(tmp dirs, kill switches) — classic xdist families, each with a known fix.

## Work
1. Classify each of the seven: `load_sensitive` (mark and run serially in a
   post-xdist serial phase), per-worker tmp/state (use `tmp_path_factory` /
   worker-id-scoped paths), generator-index order dependence (fix the test).
2. Gate change in `scripts/ci_gate.py`: `default-suite` runs `-n auto -m "not
   load_sensitive"` then the `load_sensitive` set serially; wall-clock and
   both counts recorded. `tests/test_ci_gate.py` tier pin updated.
3. Pre-register: commit tier wall-clock target (≤ 90 s end-to-end on this
   host under no wave load), zero divergences across three consecutive runs
   (the flake bar), identical pass/fail sets serial vs parallel.
4. Seeds RED: a `load_sensitive` test accidentally run under xdist must be
   caught (a marker-coverage check), and a per-worker tmp collision must
   fail loudly.

OWNS: `scripts/ci_gate.py` default-suite runner block, `tests/test_ci_gate.py`,
the seven named tests (minimal edits), `pyproject.toml` pytest markers,
`task_14/` docs. MUST NOT TOUCH: any hard gate other than default-suite, the
safety core, other cards' tests.

## Definition of done
Three consecutive green runs with identical sets serial vs parallel; the
wall-clock row; seeds RED; `XD1_STATUS.md`.
