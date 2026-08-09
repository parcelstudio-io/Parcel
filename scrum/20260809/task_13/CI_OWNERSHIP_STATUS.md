# CI / EVAL RUNNER OWNERSHIP — status

**Card:** the gap the audit AND the independent verdict both flagged as
load-bearing-and-absent — no `.github/workflows`, empty crontab, 220+ test files
and rich eval harnesses but **no runner/scheduler**, so every promotion gate was
manual and Design A's model-off guarantee was unfalsifiable. This task delivers a
per-commit + nightly runner *over the existing harnesses* (not new evals).

**Concurrency:** built without editing any `src/`, eval-harness, `runtime.py`, or
frozen file. Owned + created only: `.github/workflows/`, `scripts/ci_gate.*`,
`scripts/ci_selftest_seed.py`, `scripts/ci_ruff_baseline.json`,
`tests/test_ci_gate.py`, `docs/CI.md` (+ index in `docs/README.md`), this record.

## Deliverables

| # | Deliverable | Path |
| --- | --- | --- |
| 1 | Runner, `--tier {commit,nightly}`, exit-coded | `scripts/ci_gate.py` (+ `scripts/ci_gate.sh` wrapper) |
| 2 | GitHub Actions workflow (push/PR commit + cron nightly) | `.github/workflows/ci.yml` |
| 3 | Self-test (mirror mutation panel) | `tests/test_ci_gate.py` + `scripts/ci_selftest_seed.py` |
| 4 | Docs (cadence, tiers, local run, handoffs) | `docs/CI.md`, indexed in `docs/README.md` |
| — | Ruff debt ratchet baseline | `scripts/ci_ruff_baseline.json` |

**Runner pick:** plain Python runner + shell wrapper (not nox/tox/make) — repo has
no such tool and its convention is `scripts/*.py` run with `.parcel/bin/python`
(e.g. `scripts/mutation_panel.py`). No new dependency; CI holds no gate logic, it
only calls the runner, so local and CI runs are identical.

## Commit tier — exits 0 on the current tree (offline, deterministic, ~100s)

```
CI GATE — tier=commit
[  PASS] HARD  ruff                       39 violation(s), baseline 39, new 0
[  PASS] HARD  hard-safety                nav frozen baseline ...161252Z: collisions=0 false_arrival=0 | mutation panel clean: collisions=0 no_false_arrival=True | follow-bench: 5 row(s), hard_collision_total all 0 = True
[  PASS] HARD  frozen-digest-sentinels    2 immutable manifest(s) byte-identical to pin
[  PASS] HARD  model-off-non-inferiority  23 passed in 0.48s
[  PASS] HARD  frozen-digest-integrity    6 passed
[  PASS] HARD  mutation-panel-freshness   1 passed
[  PASS] HARD  latency-tail               6 passed
[  PASS] HARD  default-suite              3138 passed, 9 skipped, 34 deselected in 97.78s
RESULT: PASS — every hard gate green.   elapsed 100.5s   EXIT=0
```

Gate wiring (all node-ids confirmed to collect 2026-08-09):
- **default-suite** = `pytest -m "not slow"` (the 3097→3138-passing gate).
- **ruff** = `ruff check` ratcheted vs `ci_ruff_baseline.json` (fails on a new
  `(file, rule)` fingerprint; pre-existing debt does not block).
- **frozen-digest-integrity** = nav_instruct v3, embodied plan, conversation_quality,
  personal_convo manifest-sha tests; **frozen-digest-sentinels** = independent sha
  over the immutable frozen manifests.
- **mutation-panel-freshness** = `test_mutation_panel_freshness.py` committed guard.
- **model-off-non-inferiority** = SigLIP (`PARCEL_SIGLIP2_ONNX`), OWLv2/B3
  (`PARCEL_OWLV2_ONNX`), tiered-memory flag-off byte-equal cells, gathered into one gate.
- **latency-tail** = committed p95/p99 pins (`test_beat_sync`, `test_observability_planning`).
- **hard-safety** = zero hard collisions on nav frozen-baseline row + mutation-panel
  clean run + every follow-bench row, and no new false_arrival on the frozen baseline.

## Self-test — each hard gate reddens on its seeded regression (15/15 green, 0.9s)

Mirrors `scripts/mutation_panel.py`: seed the exact regression class, prove the gate
goes red, and prove it is green clean. Seeds never touch a committed source or frozen
artifact (copies / synthetic inputs / runtime monkeypatch only).

| Seeded regression | Gate caught it? |
| --- | --- |
| flag-off drift (SigLIP fallback perturbed) → model-off | **yes** — clean 10 passed / seeded 3 failed, exit 1 |
| injected collision (`collision_total=1`) → hard-safety | **yes** |
| new false_arrival (`false_arrival=1`) → hard-safety | **yes** |
| follow-bench collision → hard-safety | **yes** |
| p99 spike past ratchet ceiling → latency-tail | **yes** |
| byte-changed frozen manifest → frozen-digest | **yes** |
| new ruff fingerprint → ruff ratchet | **yes** |

**Live proof (bonus):** during the first full commit-tier run a sibling's untracked
in-flight file (`tests/test_runtime_activation.py`) landed a failing test **and** a new
ruff violation; the gate reddened on both (`default-suite` + `ruff` FAIL, exit 1) and
went green once the sibling finished — the gate catching a real concurrent regression,
not a synthetic one.

## Nightly tier

Everything in commit (re-run) plus: `mutation-panel` (in-process `run_panel`, hard —
6/6 kills / no survivors), `nav-instruct-candidate` (candidate v3 minival; hard on
collisions=0, reports SR/authority/false_arrival), `slow-suite` (`pytest -m slow` with
`PARCEL_NIGHTLY=1` — live-sim e2e + acoustic rig + nightly metamorphic, hard), and a
report-only `metamorphic` view. Per the verdict, numeric outputs are reported; only the
pre-registered hard invariants gate. Mutation-panel wrapper validated in-process; the
full slow suite (multi-minute, EGL e2e subprocesses) is documented, not run in this pass.

## Verification

- `pytest -m "not slow"`: 3138 passed, 9 skipped (green).
- New files ruff-clean: `ruff check scripts/ci_gate.py scripts/ci_selftest_seed.py tests/test_ci_gate.py` → all checks passed.
- Workflow valid: PyYAML parse OK; jobs `commit-gate`, `nightly-gate`; triggers push/PR/schedule/dispatch.
- `git status` proves zero `src/`, eval-harness, or frozen files touched by this task.

## Handoffs (needed but not addable without touching owned code)

1. **No persisted product latency ledger.** p50/p95/p99 are computed in-memory for the
   `/latency` dashboard (`observability.py::_aggregate`, `runtime.py::latency_snapshot`)
   and never written. The latency-tail gate therefore rides the committed percentile
   *pins*; the runner already carries the ratchet (`evaluate_latency_ratchet`, self-tested)
   ready to read a real ledger. **Ask:** append `latency_snapshot()` to
   `evals/latency/ledger.jsonl` so real turn p95/p99 can be ratcheted.
2. **Ruff debt: 39 fingerprints** (storefront, uwb, route_memory, camera_channel, bags,
   detection_adapter/sim_bridge, low_viewpoint, voice, a few tests, tools/). Ratcheted so
   they do not block; burn down toward zero and re-pin with `--update-ruff-baseline`.
3. **walk_with_me records no collision field** — cannot join hard-safety. **Ask:** emit
   `hard_collision_total` like follow-bench.
4. **Acoustic loop needs a host PipeWire rig** — offline but not headless; nightly-only.

## Files touched (all new; none tracked before this task)

```
.github/workflows/ci.yml
scripts/ci_gate.py
scripts/ci_gate.sh
scripts/ci_selftest_seed.py
scripts/ci_ruff_baseline.json
tests/test_ci_gate.py
docs/CI.md
docs/README.md            (index row added)
scrum/20260809/task_13/CI_OWNERSHIP_STATUS.md
```
