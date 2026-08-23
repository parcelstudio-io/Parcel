# HW-1 `py310-clean` — PREREGISTRATION (task_35)

Written **before** any row is measured, at 2026-08-23 13:0x EDT, by the HW-1
executor (Opus). Once this file is written its sha256 is quoted in
`HW1_STATUS.md` and the file is not edited again; rows are measured exactly as
written and a miss is reported as a miss.

**Declared before registration (honesty note).** An *exploratory* read-only
census (`scratchpad/hw1/census.py`, run 12:5x) preceded this file, because the
card's Work 1 requires the census table to be inside `DESIGN.md` and the design
had to name the fix classes. Its output is the table in `DESIGN.md` §(c)/§(g)
and is repeated as R1's expectation below. R1 re-runs the census with the
**shipped** scanner (`tests/test_hw1_py310_clean.py`) and is a real row: if the
shipped scanner disagrees with the exploratory one, that is a MISS.

## Environment (fixed for every row)

* `.parcel/bin/python` = CPython 3.14.4; `.parcel/bin/ruff` = 0.16.1.
* Every pytest invocation goes through
  `~/.cache/parcel-guard/pytest_guard.sh --label hw1 …` with `env -u TMPDIR`;
  never `-n auto`; never `scripts/ci_gate.py --tier`.
* Scratch: `~/.cache/parcel-hw1/` only. Repo scratch: none.
* Pre-flight before any suite-scale run: `free -g` available ≥ 120 and
  `ps -eo args | grep -c '^[^ ]*python[^ ]* -m pytest'` ≤ 1.

## Rows

| # | Row | Command (verbatim) | Threshold |
|---|---|---|---|
| R1 | Pre-fix census by class | the shipped scanner from `tests/test_hw1_py310_clean.py` run over a HEAD-state copy of `src/parcel_robot` at `~/.cache/parcel-hw1/head-src` | Finds **exactly** the 11 unguarded sites named in `task_35/README.md` (5 `datetime.UTC`, 6 `typing.Self`) and credits `commissioning/session.py:77` as GUARDED; 0 findings in every other census class. Recall 11/11 is the threshold; a 12th unguarded finding is reported, not hidden |
| R2 | Post-fix census = 0 | same scanner over the working tree | 0 unguarded findings in `src/parcel_robot` |
| R3 | Guard suite green | `~/.cache/parcel-guard/pytest_guard.sh --label hw1 .parcel/bin/python -m pytest tests/test_hw1_py310_clean.py -q` | all pass, 0 fail, 0 error |
| R4 | 3.14 behaviour identical — `UTC` object | `.parcel/bin/python -c "import datetime, parcel_robot.runtime as r, parcel_robot.observability as o, parcel_robot.context.models as m, parcel_robot.context.builder as b, parcel_robot.owner_tracking.gallery as g; print(all(x.UTC is datetime.timezone.utc is datetime.UTC for x in (r,o,m,b,g)))"` | prints `True` |
| R5 | 3.14 behaviour identical — annotations | for each of the 7 `Self` sites: `__annotations__['return']` of the annotated function, compared string-by-string against the same attribute computed from the HEAD copy | every pair equal (expected `'Self'` on both sides) |
| R6 | Targeted tests of every touched module group | one guarded `pytest` run per group: (a) `tests/test_runtime*.py`, (b) `tests/test_observability*.py` + context, (c) owner_tracking/gallery, (d) camera_channel physical, (e) perception_daemon, (f) online_map store, (g) bridge client, (h) providers/realtime | each group: 0 failed, 0 error (skips allowed and counted) |
| R7 | ruff on every touched file | `.parcel/bin/ruff check <each touched file>` and `.parcel/bin/ruff check .` | 0 findings on touched files; tree-wide fingerprint set = the 7 in `scripts/ci_ruff_baseline.json` plus only other cards' in-flight debris; **0 added by HW-1**; no `noqa` added anywhere |
| R8 | `pyproject.toml` parses and publishes ranges | `.parcel/bin/python -c "import tomllib,json;d=tomllib.load(open('pyproject.toml','rb'));print(d['project']['requires-python']);print(sorted(d['project']['optional-dependencies']))"` | `>=3.10`; extras include the pre-existing `camera, camera-realsense, dev, perception, voice` **unchanged in content** plus new `base` and `perception-jetson` |
| R9 | Jetson resolution | `.parcel/bin/pip download --dest ~/.cache/parcel-hw1/jetson-wheels --only-binary=:all: --python-version 3.10 --implementation cp --abi cp310 --platform manylinux2014_aarch64 --platform manylinux_2_17_aarch64 --platform manylinux_2_28_aarch64 --platform manylinux_2_31_aarch64 --platform linux_aarch64 'mujoco>=3.3,<4' 'numpy>=2,<3' 'PyYAML>=6,<7'` | recorded, not thresholded: every resolved package/version/wheel-tag goes into `requirements-lock-jetson.txt`; **every package with no cp310 aarch64 wheel is a handoff row** naming the package, the constraint that excluded it, and the remedy |
| R10 | `requirements-lock.txt` untouched | `git diff --stat -- requirements-lock.txt` and its sha256 before/after | empty diff; sha256 unchanged |
| R11 | CI workflow still valid | `.parcel/bin/python -c "import yaml,json;d=yaml.safe_load(open('.github/workflows/ci.yml'));print(sorted(d['jobs']))"` | parses; the pre-existing job names are all still present; exactly one new job added |
| R12 | **Local 3.10 proof (primary)** | provision a real CPython 3.10 outside the repo (`uv venv --python 3.10 ~/.cache/parcel-hw1/py310` if `uv` can be obtained; else `python3.10 -m venv`), `pip install -e '.[base]'`, then `python -c "import parcel_robot.runtime; print(parcel_robot.runtime.__file__)"` | exit 0, no traceback |
| R12f | **Local 3.10 proof (declared fallback, only if R12's interpreter cannot be obtained)** | `.parcel/bin/python -c "…ast.parse(feature_version=(3,10))…"` over all 313 files + the R2 census + `python -W error` import on 3.14 | every file parses under 3.10 feature semantics; the reason R12 was impossible is recorded verbatim |
| R13 | 3.10 collects the runtime suite | `<py310>/bin/python -m pytest tests/test_runtime.py --collect-only -q` (NOT through the xdist wrapper; single process, no `-n`) | collection completes with ≥ 1 test collected; errors, if any, are recorded per module with the missing dependency named |

## Seeds (every guard gets a seeded-RED proof)

All seeds run on a **byte-identical scratch copy** at `~/.cache/parcel-hw1/tree`
(`rsync -a --exclude .cache --exclude .parcel --exclude .git` of
`src/ scripts/ tools/ tests/ configs/ prompts/`), never the working tree, with
`PYTHONPATH=<scratch>:<scratch>/src`, and with
`python -c "import parcel_robot; print(parcel_robot.__file__)"` verified to
resolve **inside the scratch** before the seed is applied (batch-B standing
rule: the editable `.pth` otherwise imports the working tree). Each seed is
restored by sha256 and `__pycache__` is purged.

| Seed | Mutation | Must redden |
|---|---|---|
| S1 | put `from datetime import UTC, datetime` back at `observability.py:12` | the Class-A census test, naming file:line |
| S2 | put `from typing import Any, Self` back (unguarded) at `online_map/store.py:40` | the Class-B census test, naming file:line |
| S3 | add `type Alias = int` (PEP 695, 3.12) to a scanned module | the `feature_version=(3, 10)` parse test |
| S4 | add `import tomllib` + `enum.StrEnum` + `itertools.batched(…)` to a scanned module | the "other census classes" test (proves the table is wired, not decorative) |
| S5 | negative control (no mutation): the scanner run against the guarded `commissioning/session.py:77` form and against benign source | **must NOT fire** — a scan that fires on everything proves nothing |

## Owner-gated / not measured here

* B9 — the vendor image's actual interpreter and JetPack level. Command for the
  box: `cat /etc/nv_tegra_release; python3 -V; ls /opt/ros`.
* aarch64 **execution** of any wheel this card resolves. R9 is a metadata
  resolution; nothing aarch64 runs on this host.
* `voice` / `perception` on 3.10: declared unsupported, not attempted.
