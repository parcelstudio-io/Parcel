# Task 35 — HW-1: `py310-clean` — the product package imports on the Orin's interpreter

**Executor:** Claude Opus · **Verifier:** Fable · **Board:** `../TASK_BOARD.md`
(P0 standing rules + the parcel-6c anti-crash rules in
`../BATCHB_DISPATCH_FABLE_4a.md` apply). **Design:** `../WAVE3_HW_DESIGN_FABLE.md`
§2.8, §4 rows S22, §5.1, §9 HW-1. **Evidence:** `task_20/GATE0_STATUS.md`
(3.10 and 3.13 recorded as unproven; CI runs 3.12 only), the codebase lens of
`~/.cache/parcel-fable-design/research.json` (fact 0, 3, 5).

## Why
The dog's onboard Orin NX runs JetPack's CPython 3.10 (or 3.8 on a JetPack-5
dock — out of scope by declaration). `src/parcel_robot` does not import on
3.10: `from datetime import UTC` and `from typing import Self` are unguarded
at (measured 08-23) `runtime.py:13`, `observability.py:12`,
`context/{models,builder}.py:5`, `owner_tracking/gallery.py:63`,
`providers.py:10`, `perception_daemon/{server:48,client:39}.py`,
`camera_channel/backends/physical.py:52`, `bridge/client.py:7`,
`online_map/store.py:40` (+ `commissioning/session.py:77`, check whether it
is already guarded). The capture tree (`scripts/parcel_capture`) is 3.10-safe
by construction and has tests forbidding 3.11 idioms; the product package
has neither. The lock is a 3.14 x86_64 snapshot; `voice` needs ≥ 3.11
(websockets 17), the desktop `perception` extra needs ≥ 3.11 (ort ≥ 1.28),
numpy 2.5.1 needs ≥ 3.12.

## Work
1. **Census first, in `DESIGN.md`:** every 3.11+/3.12+ idiom in `src/parcel_robot`
   (`datetime.UTC`, `typing.Self`, `StrEnum`, `tomllib`, `hashlib.file_digest`,
   `itertools.batched`, PEP 604 unions evaluated at runtime, `match` is fine,
   `ExceptionGroup`, `typing.override`, f-string nesting) — list file:line,
   grouped by fix class. Use the capture tree's own guard idioms as the
   pattern (`scripts/parcel_capture/__init__.py`, `tests/test_clockmap.py:1519`,
   `tests/test_syncevents.py:1355`).
2. Fix by class, minimal edits, each inside a marked `CARD HW-1` region:
   `UTC` → `timezone.utc` (or a guarded alias in ONE module re-exported),
   `Self` → `typing_extensions.Self` only if `typing_extensions` is already a
   dependency, else the `TYPE_CHECKING` / string-annotation form; nothing
   behavioural changes (the 3.14 gate must be byte-for-byte the same verdict).
3. A 3.10-idiom guard test for the product package modelled on the capture
   tree's (`tests/test_hw1_py310_clean.py`): AST scan of `src/parcel_robot`
   for the census classes; seeded RED by re-introducing one site on a scratch.
4. `pyproject.toml`: publish tested ranges per extra — `base` ≥ 3.10;
   `voice` ≥ 3.11 (websockets); `perception` (renamed `perception-desktop`
   only if no other card references the old name — else leave the name, add
   the marker) ≥ 3.11; a new `perception-jetson` extra with
   `onnxruntime-gpu` UNPINNED from PyPI (installed from the Jetson index by a
   script — the script is HW-7's; here only the extra + a comment). Keep the
   lock untouched; write `requirements-lock-jetson.txt` produced by
   `pip download --platform manylinux2014_aarch64 --python-version 3.10
   --only-binary=:all: --dry-run` (or `uv pip compile --python-platform
   aarch64-manylinux_2_17 --python-version 3.10`) for the `base` extra —
   record every package that has NO cp310 aarch64 wheel as a handoff row.
5. CI: add a `base`-extra job on CPython 3.10 to `.github/workflows/ci.yml`
   running `python -c "import parcel_robot.runtime"` + the guard test
   (B20 stays the owner's click; the file must parse and pass `act`-style
   dry validation or `yaml.safe_load`).
6. Prove locally: `uv venv --python 3.10 ~/.cache/parcel-hw1/py310` (or
   `python3.10 -m venv` if present; if neither exists on this box, record it
   and prove with the AST guard + `python -W error -c "import ast; ..."`
   compile-only check under `--python-version 3.10` semantics), `pip install
   -e '.[base]'` → `python -c "import parcel_robot.runtime"` green, plus the
   existing `tests/test_runtime.py` collected (not necessarily all run) on
   3.10.

OWNS: the import lines named above (marked regions; nothing else in those
files), `tests/test_hw1_py310_clean.py` (new), `pyproject.toml` extras +
`requires-python` comment (marked), `.github/workflows/ci.yml` one job
(marked), `requirements-lock-jetson.txt` (new), `task_35/` docs. MUST NOT
TOUCH: `requirements-lock.txt`, any module's behaviour, the capture tree,
`scripts/ci_gate.py`, other cards' regions, the safety core.

## Definition of done
`import parcel_robot.runtime` on CPython 3.10 (or the compile-only proof with
the reason); AST guard seeded RED; gate on 3.14 unchanged; per-extra ranges
published; the jetson lock written with its no-wheel handoff rows;
`HW1_STATUS.md` in the lightweight register, every row pre-registered in
`PREREGISTRATION.md` before it is measured.

## Hardware-compat (§e of DESIGN.md)
Class MC (S22). Name the module:symbol seams; state what the desktop CAN prove
(AST guard, 3.10 venv) and what only the box proves (the vendor image's
actual interpreter, B9). No x86/CUDA assumption anywhere in the edits.
