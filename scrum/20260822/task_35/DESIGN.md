# HW-1 `py310-clean` — design (task_35) · Opus executor · 2026-08-23

Seam row **S22** (`WAVE3_HW_DESIGN_FABLE.md` §4), decision **§5.1**, card
`README.md`. Hardware-compat class **MC** (must-configure: an interpreter and a
lock, no behaviour change).

## (a) Purpose

`src/parcel_robot` does not import on CPython 3.10. The Orin NX on the Go2 EDU+
runs JetPack's system CPython 3.10 (§5.1; JetPack-5/Python-3.8 is out of scope
by declaration and forces §7.2 first). This card makes the *product package*
importable on 3.10 with **zero runtime behaviour change on 3.14**, adds a
standing AST guard so the floor cannot silently rise again, publishes the tested
interpreter range per extra in `pyproject.toml`, and produces an aarch64/cp310
resolution of the base dependencies as `requirements-lock-jetson.txt`
(`requirements-lock.txt`, the 3.14 x86_64 snapshot, is untouched).

## (b) Architecture fit — the seams, and who calls them

The 12 census sites are **import lines**, not behaviour. Each is on the product
path only in the sense that the module fails to *load*:

| Module:symbol | Product-path caller (why it is loaded on the dog) |
|---|---|
| `runtime.py:13` `datetime.UTC` | `cli.main` → `build_runtime` — the runtime itself; nothing runs if this import fails |
| `observability.py:12` | `runtime.py` → `PlanningTrace`/`StageTimer` on every turn |
| `context/{builder,models}.py:5` | `runtime.py` → `ContextBuilder.build()` per turn |
| `owner_tracking/gallery.py:63` | OT-2 `OwnerTracker` → `runtime.py` identity gate |
| `camera_channel/backends/physical.py:52` `typing.Self` | VENUE-1 `_attach_configured_camera_ingress` → `PhysicalCameraBackend.__enter__` |
| `online_map/store.py:40` | P1-B map writer (`runtime.py` `_p1b_map_lock` path) |
| `perception_daemon/{server:48,client:39}.py` | §5.2 daemon on the Orin + the runtime's client |
| `providers.py:10` | `realtime` chunk type (`__new__ -> Self`) |
| `bridge/client.py:7` | N24 gateway client (`bridge/protocol.py` DTOs) |
| `commissioning/session.py:77` | **already guarded** — the pattern this card copies |

Composition with batch A/B: nothing here touches a marked region of VENUE-1,
CAP-1, OT-2, DOOR-1, TRUTH-1, ROAM-2 or XD-1. `runtime.py` is shared with HW-4
(gateway construction ~8230); this card edits **two hunks: `:13`, the import
line, and `:374-384`, the fenced `UTC` alias** — corrected in the correction
pass on verifier NOTE N4, which caught "line 13 only" as wrong. The alias sits
after the LAST top-level import rather than beside the one it replaces so the
stdlib import block stays contiguous for ruff's isort rule (`I001`, enabled
here; `E402` is measured NOT enabled, so that is style and sortability, not a
lint failure). Both hunks were taken under the
`~/.cache/parcel-batchb/lock-runtime.py` mkdir-lock in one pass. The safety core
(`core/hard_stop`, `reactive_safety`, `SafetySupervisor`) is not in the census
and is not edited.

## (c) Interfaces / contracts

**Class A — `datetime.UTC` (3.11), 5 sites.** `UTC` is used as a *runtime value*
(`datetime.now(UTC)`). Fix: `from datetime import datetime, timezone` plus a
module-level `UTC = timezone.utc`. CPython defines `datetime.UTC` as an alias
*of that exact object* (`datetime.UTC is timezone.utc` → True), so every
`tzinfo` identity, `repr` and `isoformat` output is byte-for-byte what it is
today; the module still exports the name `UTC`. `conversation_store.py:749-751`
already spells it `timezone.utc`, so this is the tree's own idiom.

**Class B — `typing.Self` (3.11), 7 sites (6 unguarded).** Every use is a return
annotation (`__enter__`/`__new__`), and every one of the 12 files begins with
`from __future__ import annotations`, so annotations are **strings** at runtime
and no `typing.Self` object is ever constructed. Fix: the pattern already in
`commissioning/session.py:77` —
`if TYPE_CHECKING:  # pragma: no cover - annotations only; never evaluated at runtime` /
`    from typing import Self`, with `TYPE_CHECKING` added to the existing
`from typing import …` line. Runtime `__annotations__` are the same strings
before and after.

**Rejected alternatives** (stated because they change objects): rewriting call
sites to `timezone.utc` inline (10× the diff, same object, no benefit);
`typing_extensions.Self` (not a dependency — would add one to `base`, which the
Orin then has to resolve); a `sys.version_info` conditional import (adds a
branch whose 3.10 arm is never executed by the gate).

**`pyproject.toml`** (marked region): `requires-python = ">=3.10"` is unchanged
and now *true*; a comment block publishes the tested range per extra; a new
`base` extra so `pip install -e '.[base]'` (the design's §5.1 command) resolves
instead of warning — **empty**, `base = []`, amended during implementation: an
extra's requirements are ADDED to the core `dependencies`, so an empty `base`
installs exactly mujoco + numpy + PyYAML and cannot drift out of step the way a
copied list would (proved by the 3.10 install, `HW1_STATUS.md` R12); a new
`perception-jetson` extra carries `onnxruntime-gpu` **unpinned**, installed from
the Jetson index by HW-7's script. The `perception` extra keeps its name (other
cards and `scripts/` reference `.[perception]`) and gains the marker comment.

**`requirements-lock-jetson.txt`** (new): the output of a `pip download
--platform manylinux2014_aarch64 --python-version 3.10 --only-binary=:all:
--dry-run`-shaped resolution of the base dependencies. It is a *record*, not a
gate input; nothing in `scripts/ci_gate.py` reads it.

**`.github/workflows/ci.yml`** (marked region): one `py310-base` job — set up
CPython 3.10, `pip install -e '.[base]'`, `python -c "import
parcel_robot.runtime"`, and `pytest tests/test_hw1_py310_clean.py`. B20 (the
owner's click) is unchanged; the file must still `yaml.safe_load`.

## (d) Data flow / lifecycle

None. No thread, lock, file, socket or process is created or destroyed by any
edit in this card. The only lifecycle object is the `~/.cache/parcel-batchb/
lock-runtime.py` mkdir-lock held for one Edit pass on `runtime.py:13`.

## (e) Hardware compatibility — class MC (S22)

*Venue-independent by construction:* every fix is an import form; the same
bytecode-level behaviour holds on x86_64/3.14 and aarch64/3.10.
*Must configure:* the Orin's product venv is the system CPython 3.10 and its
resolution is `requirements-lock-jetson.txt`, not `requirements-lock.txt`;
`voice` and `perception` are **not installable** on 3.10 (websockets 17 and
onnxruntime-gpu ≥1.28 are ≥3.11) — the ear on the dog is HW-4's array gateway in
a lane the design puts in its own process, and perception is §5.2's separate
venv. No edit assumes x86, CUDA, or a GPU.
*What the desktop CAN prove:* the AST guard over all 313 `src/parcel_robot`
files; a real CPython 3.10 venv on this box importing `parcel_robot.runtime`;
the aarch64/cp310 wheel resolution (a metadata query against PyPI, no aarch64
execution).
*What only the box proves (B9):* which interpreter the vendor image actually
ships (JetPack 5.1.1 → 3.8 → §7.2), whether the aarch64 wheels the lock names
import on that L4T, and any C-extension ABI surprise. `mujoco` and `numpy` are
resolved for aarch64 here but **executed only on the box**.

## (f) Test strategy → pre-registered rows

`tests/test_hw1_py310_clean.py` (new, this card's only test file): an AST scan of
every `src/parcel_robot/**/*.py` for the census symbol table (Class A/B plus
`StrEnum`, `tomllib`, `hashlib.file_digest`, `itertools.batched`,
`ExceptionGroup`/`except*`, `typing.override`, PEP 695 syntax, `asyncio.TaskGroup`
/`timeout`, `contextlib.chdir`, `copy.replace`, `typing.TypeIs`,
`warnings.deprecated`, `os.process_cpu_count`, `annotationlib`), a
`feature_version=(3, 10)` parse of every file (the capture tree's idiom,
`tests/test_clockmap.py:1519`), a negative control (the scan must not fire on
benign source), and a `TYPE_CHECKING`-awareness test so the guard credits the
guarded form. **Amended during implementation:** the guard file itself must run
on 3.10, because Work 5's CI job runs it there — `ast.TryStar` (3.11) and
`ast.TypeAlias` (3.12) do not exist on that interpreter, so the scanner builds
empty `isinstance` tuples when they are absent and skips by name the three
mutants whose *syntax* a 3.10 parser cannot read (the grammar cell is what
catches that class there).
Rows and thresholds are in `PREREGISTRATION.md`; seeds S1–S4 are
run on a byte-identical scratch copy under `~/.cache/parcel-hw1/tree` with
`PYTHONPATH=<scratch>:<scratch>/src` and `parcel_robot.__file__` verified inside
it (the batch-B standing rule).

## (g) Risks and what this design does NOT cover

1. **Stdlib behaviour differences the AST scan cannot see.** Census Class E:
   `conversation_store.py:747` `datetime.fromisoformat` accepts a trailing `Z`
   only on ≥3.11; on 3.10 that branch returns `None` instead of a timestamp.
   Not fixed here (it is not an import error, and the fix is behavioural — it
   belongs to whoever owns `conversation_store`); recorded as a handoff.
2. The guard proves the *product package*. `tests/`, `tools/` and `scripts/`
   (other than the capture tree, which has its own guards) are NOT scanned —
   they run on the dev interpreter.
3. A 3.10 venv on **x86_64** does not prove the aarch64 wheels import; the lock
   is a resolution, not an installation (B9).
4. `voice`/`perception` on 3.10 are declared unsupported, not made to work.
5. `requirements-lock.txt` is untouched by rule, so the 3.14 gate resolution is
   unchanged.
