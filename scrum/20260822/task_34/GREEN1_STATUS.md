# GREEN-1 — two order-dependent guards, made order-independent · STATUS

**Card:** GREEN-1 (urgent, from Fable's `--tier commit` run) · **Executor:** Claude Opus
**Verifier / integrator:** Fable · **Date:** 2026-08-22 · **HEAD at start:** `21ea2fb`
(uncommitted wave-2 tree on top, taken as the baseline; nothing reverted)

---

## Headline

Both tests now measure their property in a **clean subprocess**, which is the
pattern the capture stack already uses
(`tests/test_capture_preflight.py::test_a_full_preflight_run_never_imports_a_vendor_sdk`,
and `test_the_module_present_refusal_never_imported_the_vendor_sdk` directly
above the first of the two). Neither assertion was weakened, skipped, xfailed or
reordered; both got **stronger**, because a fresh interpreter gives them a
starting line instead of whatever the sweep had already loaded.

Both go green **alone**, **in their own file**, and **in the sweep that broke
them** — including under the gate's own environment.

**One finding Fable must weigh before re-gating.** Only *one* of the two was a
`sys.modules` artefact. The venue-1 cell was failing on
`assert "MUJOCO_GL" not in os.environ` — an **environment** leak, not an import
one. And `scripts/ci_gate.py::_base_env` (line 513) does
`env.setdefault("MUJOCO_GL", "egl")` for every gate pytest subprocess, so that
in-process assertion **could not pass under `ci_gate.py` in any order at all**,
even run alone. Measuring in a child whose env is scrubbed fixes the
order-dependence *and* the gate-dependence in one move. See §"What it does not
prove" for what that costs.

---

## What changed

Two test files. No product code. (`scripts/parcel_capture/ingest/base.py` and
`src/parcel_robot/runtime.py` were seeded and restored — sha256-verified
identical, see §Seeded RED.)

```
$ git diff --stat -- tests/test_capture_ingest.py tests/test_venue1_physical_venue.py
 tests/test_capture_ingest.py | 56 +++++++++++++++++++++++++++++++++++++-------
 1 file changed, 48 insertions(+), 8 deletions(-)
```

`tests/test_venue1_physical_venue.py` is **untracked** in the wave-2 tree (`??`
in `git status`), so `git diff --stat` cannot show it. Its four hunks:

| hunk | change |
|---|---|
| imports | `+import subprocess` (line 50) |
| `_MUJOCO_ROOTS` comment | "before **either** MuJoCo fixture" → "before **the** MuJoCo fixture" (one word; there is now one) |
| `mujoco_unloaded` fixture | **removed** (16 lines) and replaced with a 6-line comment saying why. It had exactly one user — the test below — and `grep` over the whole repo (`*.py`, `*.md`) confirms no other reference. `_forget_mujoco` and `mujoco_is_fatal` are untouched and still used by `test_a_physical_venue_never_imports_mujoco`. |
| the test itself | 39 lines → 93 lines (docstring carries the whole diagnosis; the four original assertions survive one-for-one as `BEFORE False` / `AFTER True` / `GL <unset>` / `SCENE city_block`, plus a new `MAP True`) |

### 1. `test_no_adapter_import_ever_installs_or_imports_a_vendor_module`

**Why it was order-dependent.** `tests/test_venue1_physical_venue.py` calls
`_attached_realsense()` → `connected_devices()` → `import pyrealsense2` at
**module scope** (it feeds a `skipif` marker, line ~1813). Pytest imports every
selected module during collection, before running a single cell, so in any
sweep containing both files `pyrealsense2` is in `sys.modules` before this file
starts. Confirmed by an `__import__` trace: the stack is
`test_venue1_physical_venue.py:1814 → :78 → realsense.py:92`.

**The fix.** A `-B -c` child imports `dependency_report_text` and prints the
vendor census before and after the call. Three assertions:
`BEFORE []` (a real starting line), `AFTER []` (the property), and
`REPORTED True` — every one of the three vendor module names appears in the text
the report produced, so `AFTER []` cannot be satisfied by a probe that never
ran.

**Strictly stronger than before.** The old cell checked `pyrealsense2` only
*before* the call and dropped it from the after-check — it could not do
otherwise on a box where P1-A's wheel had already been dragged in by a
neighbour. The child checks all three, both sides.

### 2. `test_the_map_installer_still_imports_mujoco_and_that_is_a_handoff`

**Why it was order-dependent.** Not the import. `mujoco_unloaded` already
forgot both `mujoco` *and* `parcel_robot.sim`, and that half kept working — the
observed failure was `assert "MUJOCO_GL" not in os.environ`.
`src/parcel_robot/runtime.py:11491` sets `os.environ["MUJOCO_GL"] = "egl"`
process-wide when the **simulated** camera ingress attaches. Measured: either of
`tests/test_runtime_activation.py` or `tests/test_scene_assets.py`, alone, ahead
of this file, is enough. The cell was going red on a fact about a neighbour.

**Why a subprocess and not `monkeypatch.delenv`.** The file's own
`test_a_physical_venue_never_imports_mujoco` (line 538) defends its copy of the
same assertion exactly that way, and that is right *there*: it asserts a path
returns **before** the preamble, so the process it runs in is not part of the
claim. Here `delenv` would have fixed the env half and not the other one: the docstring's claim is "imported, **never
initialized** — no `MjModel`, no `MjData`, no EGL context". In a process where an
earlier cell already built an `MjModel` and bound EGL, that is unmeasurable
however clean `sys.modules` looks — no amount of module surgery un-initializes a
MuJoCo that has already run. This cell's subject is a **first import** — the
tripwire only fires if `parcel_robot.sim` is genuinely loaded from source by the
installer — and a fresh interpreter is the only thing that gives it one.

**The fix.** The child puts `REPO` and `REPO/tests` on `sys.path`, imports
*this same module* for its `_config` / `_learned_map_nav_config` / `_runtime`
helpers (so the runtime under measurement is built exactly the way every other
cell in the file builds one), runs `_p1b_install_learned_map()` under the
parent's `tmp_path`, and prints the four facts. The child's env is a copy of the
parent's with `MUJOCO_GL`, `PARCEL_CAMERA_BACKEND`, `PARCEL_CAMERA_CONFIG` and
`PARCEL_PERCEPTION_SOCKET` popped and `PARCEL_ONLINE_MAP_PATH=:memory:` set —
the same scrubbing the file's `_clean_venue_env` autouse fixture does in-process,
plus the one variable it never covered.

`BEFORE False` is asserted so that importing this module for its helpers can
never itself be what puts MuJoCo in the child — otherwise `AFTER True` would be
vacuous. Measured: importing `test_venue1_physical_venue` in a fresh interpreter
leaves both `mujoco` and `parcel_robot.sim` absent.

---

## How verified

`.parcel/bin/python`, **`TMPDIR` unset** on every run. `ci_gate.py` was never
run and the full suite was never run (Fable gates).

### The reproducing commands (failure reproduced FIRST, then re-run)

The two suggested combos did **not** reproduce, for one reason worth recording:
pytest runs files in the order given on the command line, and in both combos the
target file was listed *first*, so the poisoner never got to run ahead of it. In
the real sweep the order is alphabetical and `test_venue1_physical_venue.py`
sorts near the end.

**Guard #1** — minimal reproducer (the poisoner is the venue file's collection):

```
env -u TMPDIR .parcel/bin/python -m pytest \
  tests/test_capture_ingest.py tests/test_venue1_physical_venue.py -p no:randomly -q
```

* before: `1 failed, 136 passed` — `AssertionError: assert 'pyrealsense2' not in sys.modules`
* after (widened to the card's combo + the poisoner): **789 passed**

```
env -u TMPDIR .parcel/bin/python -m pytest tests/test_capture_ingest.py \
  tests/test_capture_preflight.py tests/test_capture_rehearsal.py \
  tests/test_capture_sidecar.py tests/test_clockmap.py tests/test_no_arm_pin.py \
  tests/test_venue1_physical_venue.py -q -p no:cacheprovider
```

**Guard #2** — minimal reproducer (`tests/test_runtime_activation.py` alone, or
`tests/test_scene_assets.py` alone, ahead of the file):

```
env -u TMPDIR .parcel/bin/python -m pytest \
  tests/test_c1_camera_stream.py tests/test_runtime_activation.py \
  tests/test_owlv2_detector.py tests/test_scene_assets.py tests/test_dynamic_city.py \
  tests/test_venue1_physical_venue.py -p no:randomly -q
```

* before: `1 failed, 159 passed` — `AssertionError: assert 'MUJOCO_GL' not in environ(...)`
* after, widened and **under the gate's environment**
  (`MUJOCO_GL=egl PYTHONPATH=<repo>`, which is what `_base_env` hands pytest):
  **312 passed, 2 skipped**

```
env -u TMPDIR MUJOCO_GL=egl PYTHONPATH=$PWD .parcel/bin/python -m pytest \
  tests/test_c1_camera_stream.py tests/test_dynamic_city.py tests/test_owlv2_detector.py \
  tests/test_p1b_map_learns.py tests/test_runtime.py tests/test_runtime_activation.py \
  tests/test_scene_assets.py tests/test_sim.py tests/test_venue1_physical_venue.py \
  -q -p no:cacheprovider
```

### The acceptance bar

| | (a) alone | (b) own file | (c) reproducing sweep |
|---|---|---|---|
| `test_no_adapter_import_ever_installs_or_imports_a_vendor_module` | 1 passed | 91 passed | 789 passed |
| `test_the_map_installer_still_imports_mujoco_and_that_is_a_handoff` | 1 passed | 46 passed | 312 passed, 2 skipped |

Both also pass together under the gate env (`MUJOCO_GL=egl`, `PYTHONPATH=<repo>`,
`-p no:cacheprovider`): 2 passed.

### Lint

`.parcel/bin/ruff check` on both files: **All checks passed.** Repo-wide
fingerprint census: **exactly 7**, identical to `scripts/ci_ruff_baseline.json`.
No `noqa` added, nothing re-pinned. `ruff format --diff` shows no diff inside
either new block (the pre-existing format drift elsewhere in both files is
untouched and is not a gate).

---

## Seeded RED — one per changed guard

Each seed changes the **product property** the guard protects, not the test.
Restore verified by `sha256sum -c`; `__pycache__` purged before every run.

### Guard #1 — `scripts/parcel_capture/ingest/base.py::Requirement.present`

`importlib.util.find_spec(self.module)` → `importlib.import_module(self.module)`
— i.e. exactly the thing the docstring says is forbidden ("a probe that imports
a vendor SDK to find out whether it exists has already done the thing the board
forbids").

```
E       AssertionError: BEFORE []
E         AFTER ['pyrealsense2']
E         REPORTED True
1 failed in 0.42s
```

The seed is visible **because** the child starts clean — `BEFORE []` /
`AFTER ['pyrealsense2']` names the probe as the importer, which the in-process
version could not have done in a sweep. Restored:
`sha256 012e4b58…beb289` → `OK`, re-run **1 passed**.

### Guard #2 — `src/parcel_robot/runtime.py::RobotRuntime._p1b_scene_id`

The handoff, **taken**: `from parcel_robot.sim import resolve_scene` removed and
the venue's own path resolved instead — the one-line remedy `VENUE1_STATUS.md`
proposes.

```
E       AssertionError: the handoff was taken; delete this cell
E         BEFORE False
E         AFTER False
E         GL <unset>
E         MAP True
E         SCENE robot
1 failed, 1 warning in 1.74s
```

Note `SCENE robot`: the naive remedy reintroduces the *exact* defect
`_p1b_scene_id`'s docstring records ("every entry stamped with the stem of the
ROBOT CONFIG file"). The cell catches both halves of the handoff. Restored:
`sha256 fb3d22c9…0d0c84` → `OK`, re-run **1 passed**.

---

## What it does not prove

1. **Nothing about the full suite.** I never ran it and never ran `ci_gate.py`.
   The widest sweeps here are 789 and 312 tests, chosen to contain the measured
   poisoners. A third test — `tests/test_arrival_semantics.py` — is another
   agent's and was not run by me.
2. **The child's env is scrubbed, so the venue cell no longer measures the
   process the gate actually launches.** That is deliberate — the property
   belongs to `_p1b_install_learned_map`, not to whatever a neighbour exported —
   but it does mean *this cell* would no longer notice if the product itself
   started depending on an inherited `MUJOCO_GL`. Nothing else in the file
   covers that, and I did not add it: it is outside GREEN-1's brief. See
   handoff H2.
3. **`AFTER True` proves `mujoco` entered `sys.modules`, not that it stayed
   uninitialized in every sense.** `GL <unset>` is the operative half (no EGL
   binding); no `MjModel`/`MjData` census is taken, exactly as before.
4. **`REPORTED True` (guard #1) checks that the three module names appear in the
   report text, not that each appears in the right state line.** That is
   `test_the_dependency_report_names_each_module_state_and_is_never_a_traceback`'s
   job, unchanged, in the same file.
5. **Cost:** guard #2 now spends ~1.3 s on a subprocess instead of ~0.1 s
   in-process; guard #1 ~0.35 s instead of ~0.01 s. Both trivial against the
   file totals (0.6 s / 24 s).
6. Both subprocesses run the **same interpreter** (`sys.executable`), so the
   ENV-1b two-venv branching story is unaffected: a `.[dev]` venv without the
   wheel still reaches `BEFORE []` / `AFTER []` (the property is unbranched) and
   guard #1 grew no new venv dependence.

---

## Deviations

* **Reproducing commands.** Neither suggested combo reproduced; both were
  widened and re-ordered (target file **last**) as the card permits. Both
  recorded above.
* **Removed a fixture.** `mujoco_unloaded` lost its only user and would have
  become dead scaffolding that a reader might trust. Removed, with a comment in
  its place explaining why the subprocess replaced it. `_forget_mujoco` and
  `mujoco_is_fatal` are untouched.
* **Guard #1's after-check widened** from two modules to three. The original
  omitted `pyrealsense2` from the after-check because in-process it could not
  ask; the child can, and the answer is `[]`. This is a strengthening, not a
  behaviour change.
* **Nothing else touched.** No git write ops. No `docs/`, `backlog/`,
  `README.md`, `scrum/20260821/`, `reactive_safety`, `core/hard_stop`, venv, or
  `evals/nav_instruct/results/ledger.jsonl`. The five leaked `parcel_robot.sim`
  processes were left alone.

---

## Handoffs

* **H1 (for Fable, before re-gating).** `scripts/ci_gate.py::_base_env` sets
  `MUJOCO_GL=egl` for every gate pytest run, so any in-process
  `assert "MUJOCO_GL" not in os.environ` that does not first clear the variable
  is doomed under the gate regardless of ordering. I did sweep `tests/`, `src/`
  and `scripts/` for the pattern: **exactly two** occurrences, both in
  `tests/test_venue1_physical_venue.py`. The other one
  (`test_a_physical_venue_never_imports_mujoco`, line 538) is **already safe** —
  it calls `monkeypatch.delenv("MUJOCO_GL", raising=False)` at line 528 — and I
  did not touch it. So after this card the pattern is clean tree-wide, and the
  gate's `MUJOCO_GL=egl` is no longer a hidden dependency for either cell.
* **H2 (VENUE-1, task_16).** No cell now asserts that the product tolerates an
  inherited `MUJOCO_GL`. If the venue path should refuse (or accept) a
  pre-bound GL backend, that is a new property and wants its own cell;
  `runtime.py:11483` already has the refusal branch for the *simulated* ingress.
* **H3 (VENUE-1 / P1-B, unchanged).** The handoff this cell pins is still open:
  `_p1b_scene_id` still imports `parcel_robot.sim`. The seeded-RED run above
  also shows that the naive one-line remedy re-stamps entries with the robot
  config's stem (`SCENE robot`) — whoever takes the handoff must resolve the
  venue's name, not just delete the import.
* **H4 (housekeeping, not mine).** `tests/test_venue1_physical_venue.py`'s
  module-scope `_attached_realsense()` imports `pyrealsense2` during
  *collection*, for every sweep that includes the file. Guard #1 is now immune,
  but the import is still a collection-time side effect that any future
  "nothing imported the vendor SDK" cell will trip over. Deferring the probe
  into the `skipif` (a lazily-evaluated marker or a fixture-level skip) would
  remove it. Outside GREEN-1's brief.
