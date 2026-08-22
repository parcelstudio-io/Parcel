# ENV-1b — the follow-up to ENV-1 · STATUS

**Card:** `../TASK_BOARD.md` (Build-order table, ENV-1 → ENV-1b) · **Executor:** Claude Opus
**Verifier:** Fable · **Prior:** `ENV1_STATUS.md`, `../AUDIT_WAVE_P1P2_FABLE.md` §ENV-1
**Date:** 2026-08-22 · **HEAD at start:** `8862220`

---

## Headline

Six items, all small, all landed. The one that mattered: **ENV-1's re-cut made
six assertions hard-require the `pyrealsense2` wheel**, which lives in `.parcel`
only because P1-A put it there — the `dev` extra does not carry it and must not
(no aarch64 wheel; declaring it would break `pip install .[dev]` on the Orin).
A venv built from the `dev` extra alone therefore failed 6 tests *about the
product*. Every module-present arm now **branches on
`importlib.util.find_spec("pyrealsense2")`** the way
`tests/test_capture_rehearsal.py` already did, and asserts the module arm in the
other venv rather than skipping. **Both venv arms measured: 667 passed each.**

The second real change: `clockmap --check`'s REFUSED paragraph handed *every*
unsatisfied device the SDK remedy — "Run this on the Orin inside the ROS 2
Humble environment that owns the vendor SDKs" — including a D455 whose SDK is
installed and whose cable is not. That remedy sends the operator to reinstall
something they already have. The paragraph now splits **MODULE MISSING** from
**DEVICE MISSING** and prints the attach remedy for the latter:

```
REFUSED: no clock probe is possible for: d455, go2, l2
This host cannot record offset triples for those devices.

  MODULE MISSING — the SDK is not on this interpreter's import path: go2, l2
  Run this on the Orin inside the ROS 2 Humble environment that owns the vendor SDKs.

  DEVICE MISSING — d455: the SDK is installed and nothing is attached.
  Plug the device in and confirm the node appears at /dev/video* (`ls /dev/video*`).
  No SDK install and no Python environment can substitute for the cable.

Recording a session without them leaves their timestamps permanently unrecoverable.
```

Item 5 was a real fail-open and is **closed, not declared**: a build with no
`rs.context` used to fall through to `pipeline.start()`, which on a webcam-only
host produces the `probe_raised — RuntimeError` that card ENV-1 exists to
remove.

Fable's two corrections in `clockmap.py` (`interrogable` out of
`probe_availability`, the L2's `device_nodes`) and the guard
`test_a_non_interrogable_device_is_a_ritual_not_a_missing_probe` were **not
touched**. `probe_availability`, `PROBE_REQUIREMENTS`, `ingest/base.py`,
`pyproject.toml` and everything under `src/` were **not touched**.

---

## What changed

`git diff --stat HEAD` on OWNS:

```
 scripts/parcel_capture/__init__.py         |  23 +++--
 scripts/parcel_capture/clockmap.py         |  42 +++++++--
 scripts/parcel_capture/ingest/realsense.py |  22 ++++-
 scripts/parcel_capture/preflight.py        |  36 +++++---
 tests/test_capture_ingest.py               | 102 ++++++++++++++++++++--
 tests/test_capture_preflight.py            |  44 ++++++++--
 tests/test_capture_rehearsal.py            |   7 +-
 tests/test_capture_sidecar.py              |  20 ++++-
 tests/test_clockmap.py                     | 134 +++++++++++++++++++++++++++--
 9 files changed, 375 insertions(+), 55 deletions(-)
```

Edit-only on existing files; no file created, deleted or `Write`-replaced.
`scripts/parcel_capture/clockmap.py` has **exactly one hunk**, inside `main()`'s
`--check` branch (`git diff HEAD -- …clockmap.py | grep -c '^@@'` → `1`).

### Item 1 (minor) — six assertions hard-required the wheel

Every one now branches. What each asserts in the wheel-absent venv:

| file · assertion | wheel present (`.parcel`) | wheel absent (`.[dev]`) |
|---|---|---|
| `test_capture_ingest.py` `…never_imported_the_vendor_sdk` | subprocess prints `SATISFIED True` / `REASON device_node_missing` | `SATISFIED False` / `REASON dependency_missing` |
| `test_capture_ingest.py` `…names_each_module_state…` | `NO DEVICE (installed: pyrealsense2)` | `UNAVAILABLE (missing: pyrealsense2)` |
| `test_capture_preflight.py` `…never_imports_a_vendor_sdk` | six d455 rows `device_node_missing` + `/dev/video*` + `USB 3 (BLUE)` | six d455 rows `dependency_missing` naming `pyrealsense2` |
| `test_capture_sidecar.py` `…which_half_is_missing` | `states['realsense'] == 'device_absent'` | `== 'module_absent'` |
| `test_clockmap.py` `…fails_closed_on_this_hardwareless_dev_box` | `d455_present == ('pyrealsense2',)` | `== ()` |
| `test_clockmap.py` `test_seeded_red_a_probe_satisfied_by_its_module_alone…` | the real host feeds the pre-ENV-1 module-only rule | the module is *staged* present via `find_spec`, and the shipped rule must still refuse on the `/dev` node |

Three things were held **unbranched**, because they are the properties and they
hold in both venvs: `assert "VENDOR []"` (word for word, untouched);
`IMPORTED False` in the ingest subprocess; `"probe_raised" not in line` for
every d455 row. Two assertions were *added* to keep the wheel-absent arms from
going vacuous — `realsense.device_report().presence is ABSENT` in the sidecar
guard (the `/dev` census is import-free, so it answers for the camera with or
without the wheel) and `/dev/video*` + `USB 3 (BLUE)` in the report block in
both arms.

Nothing was skipped, and **`pyrealsense2` was NOT added to the `dev` extra** —
`pyproject.toml` is byte-unchanged.

### Item 2 (minor) — `--check`'s REFUSED paragraph

`clockmap.main()` classifies each unsatisfied device by *the condition that
actually failed*: module census empty → MODULE MISSING (keeps the ROS 2 Humble
sentence); module census non-empty and a declared `device_nodes` pattern
unmatched → DEVICE MISSING (gets the attach remedy naming `/dev/<pattern>` and
the `ls` command). Exit code, the word `REFUSED`, the device list on the
`REFUSED:` line, and `permanently unrecoverable` are all unchanged, so the three
existing tests that pin them still pass unmodified.

New guard: `test_a_device_absent_refusal_gives_the_attach_remedy_not_the_sdk_remedy`
(`tests/test_clockmap.py`). In-process `main(["--check"])`, `importlib.util.find_spec`
patched, `clockmap.device_nodes_present` patched to `()`. Two arms — (1) the
D455 is the *only* unsatisfied device, so the ROS 2 sentence must not appear
anywhere in the output; (2) `go2`/`l2` unsatisfied too, so both halves print and
the ROS 2 sentence must be in the MODULE half and `d455` must not be.

### Item 3 (note) — stale dead-premise docstrings

* `scripts/parcel_capture/__init__.py` — the bullet that claimed the box "has
  none of `rclpy`, `cyclonedds`, `unitree_sdk2py`, `pyrealsense2`, `cv2`, `mcap`
  or `zstandard`" is replaced by the two-facts rule (module vs device, with the
  probe for each named: `find_spec` and a `/dev` glob, neither an import), and
  it now records that the box may or may not carry a camera SDK.
* Same file, the adjacent bullet: "no vendor SDK installed into `.parcel/`" →
  "no **motion** SDK", with the by-what-it-can-DO split spelled out. **Declared
  as a one-bullet extension beyond the card's line range** — it was the same
  dead premise one bullet down and would have read as a contradiction.
* `scripts/parcel_capture/preflight.py` — the "Two Pythons, no vendor SDK"
  section is retitled "Two Pythons, and two facts: the module and the device"
  and rewritten to the same rule, keeping the `unitree_sdk2py` motion guarantee
  verbatim and scoping it to the motion SDKs.
* `tests/test_capture_rehearsal.py` — "Six of the seven still are" → "FIVE of
  the seven still are", with the arithmetic spelled out: `pyrealsense2` **and**
  `cv2` both dropped out, and the loop's sixth name (`unilidar_sdk2`) was never
  in the original seven.

### Item 4 (note) — all six d455 rows

`tests/test_capture_preflight.py` pinned `color`, `depth`, `infra1`, `infra2`.
It now pins `accel` and `gyro` too. These are not redundant rows: they are the
`MOTION_CHANNELS` branch of `stream_selection`/`decode_motion_frame`, a
different code path from the four video rows.

### Item 5 (note) — `_require_enumerated_device` was fail-open. **Gated, not declared.**

`if not present(factory): return` became a fail-closed `IngestUnavailableError`
(`UNPARSEABLE`) naming `rs.context` with a version-check remedy. Three reasons
to close rather than declare:

1. The fall-through does not "let the open speak for itself" — the open
   *crashes*. `pipeline.start()` on a webcam-only host raises a librealsense
   `RuntimeError`, which preflight files as `probe_raised`: the unattributable
   absence, naming no device and offering no remedy, that is verbatim the defect
   ENV-1 was written to remove (`ENV1_STATUS.md`, deviation 2).
2. It is inconsistent with the same file two methods down: `stream_selection`
   already refuses `UNPARSEABLE` when a build exposes no `rs.stream`/`rs.config`.
   A build that cannot be interrogated cannot be trusted to select a stream
   either, so the fall-through bought nothing.
3. It attributes the failure to the wrong thing. "This build exposes no
   `rs.context`" is a fact about the wheel; `probe_raised — RuntimeError` reads
   as a fact about the camera, and the operator debugs the camera.

New guard: `test_a_build_with_no_rs_context_refuses_instead_of_falling_through_to_start`
(`tests/test_capture_ingest.py`), staging a webcam-shaped `/dev/video0` (so the
import-free census cannot refuse) and deleting `context` from the double. Asserts
`unparseable`, the symbol named, a remedy, and — the half that matters —
`log["started"] == 0`.

### Item 6 (handoff) — status-doc only, no code. See **Handoffs** below.

---

## How verified

Env: `.parcel/bin/python` (3.14), `.parcel/bin/ruff` 0.16.1, **`TMPDIR` unset**
on every pytest invocation (`env -u TMPDIR …` — see the AF_UNIX handoff below
for why). Targeted pytest + ruff only. `scripts/ci_gate.py` was **not** run and
neither was the full suite.

### Item 1 — BOTH venv arms

The wheel-absent venv is modelled by a scratch `sitecustomize.py` at
`/home/jaewoo-jang/.cache/parcel-env1b/nowheel/`, on `PYTHONPATH` only. **No
repo edit, no `pip uninstall`, nothing installed.** It wraps every
`sys.meta_path` entry so none of them — `PathFinder` above all — can answer for
`pyrealsense2`; with no finder providing a spec, `find_spec` returns `None` and
`import` raises `ModuleNotFoundError`, exactly as a venv without the wheel does.
It is `sys.modules`-aware for free (CPython consults `sys.modules` before
`sys.meta_path` for `import`, and `find_spec` returns `module.__spec__` for
anything already there), so the suite's `monkeypatch.setitem(sys.modules,
"pyrealsense2", double)` fakes still resolve — only the real wheel on disk goes
invisible. Verified directly before use:

```
find_spec: None
import:    ModuleNotFoundError No module named 'pyrealsense2'
double find_spec: ModuleSpec(name='pyrealsense2', loader=None)
double import is m: True
```

**The reproduction, before any edit** (this is item 1's seeded RED: the pre-fix
assertions are the seed, run and observed):

```
env -u TMPDIR PYTHONPATH=…/nowheel .parcel/bin/python -m pytest -p no:randomly -q \
  tests/test_capture_{ingest,preflight,rehearsal,sidecar}.py tests/test_clockmap.py
  ->  6 failed, 659 passed in 13.82s
FAILED …ingest.py::test_the_module_present_refusal_never_imported_the_vendor_sdk
FAILED …ingest.py::test_the_dependency_report_names_each_module_state_and_is_never_a_traceback
FAILED …preflight.py::test_a_full_preflight_run_never_imports_a_vendor_sdk
FAILED …sidecar.py::test_no_live_reader_can_run_here_and_the_report_says_which_half_is_missing
FAILED …clockmap.py::test_probe_availability_fails_closed_on_this_hardwareless_dev_box
FAILED …clockmap.py::test_seeded_red_a_probe_satisfied_by_its_module_alone_is_caught
```

Exactly the six the card names, at the six line numbers it names. **After**, the
same five files, both arms, `-p no:randomly` and again in the default random
order:

```
                                     no:randomly        random order
wheel PRESENT  (.parcel as it is)    667 passed 13.24s  667 passed 13.80s
wheel HIDDEN   (PYTHONPATH shim)     667 passed 13.11s  667 passed 13.38s
```

(665 → 667: two new guards, items 2 and 5.)

### Collateral — everything else that reads the capture stack

```
env -u TMPDIR .parcel/bin/python -m pytest -q tests/test_no_arm_pin.py \
  tests/test_capture_envelope.py tests/test_bandwidth_budget_doc.py \
  tests/test_disk_ledger_doc.py tests/test_orin_rehearsal.py \
  tests/test_tonight_checklist_drivers.py tests/test_stage0_command_addendum.py \
  tests/test_syncevents.py tests/test_rosbag2_sidecar.py tests/test_stage0_addendum.py \
  tests/test_p1a_camera_backends.py      ->  662 passed in 24.67s
```

`tests/test_no_arm_pin.py` is the one that matters: it enumerates every dynamic
attribute reach in `scripts/parcel_capture/`. The item-5 change adds **no** new
reach — it only replaces a `return` with a `raise` after the existing
`read_field(rs, "context")` — so `VETTED_REACHES` is unchanged.

### The product paths, run as the owner would

```
.parcel/bin/python -m scripts.parcel_capture.clockmap --check      -> exit 2, new split paragraph (quoted above)
.parcel/bin/python -c "…attest.main(['--window','0.01'])"          -> all SIX d455 rows device_node_missing
```

### ruff

```
.parcel/bin/ruff check scripts/parcel_capture/ tests/test_capture_ingest.py \
  tests/test_capture_preflight.py tests/test_capture_rehearsal.py \
  tests/test_capture_sidecar.py tests/test_clockmap.py --output-format=concise
  ->  All checks passed!   (exit 0)
```

**Zero fingerprints added; the ratchet's 7 baseline entries are byte-identical**
and are exactly the pre-existing set:
`camera_channel/backends/factory.py::{ISC004,S110}`,
`camera_channel/channel.py::I001`, `camera_channel/__init__.py::RUF022`,
`detection_adapter/noise.py::I001`, `detection_adapter/sim_bridge.py::{B009,ISC004}`.

**Observation for the verifier, not mine:** a whole-tree `ruff check .` right now
shows *more* than 7 fingerprints, and the set moved between two runs eight
minutes apart. The extras are all in files belonging to cards executing
concurrently — `src/parcel_robot/realtime/config.py::RUF009` and
`tools/replay_turn_detection.py::{EXE001,PLC0206,RUF100}` (TURN-1),
`tests/test_mark1_barge_in_mark.py::{F401,ISC004,RUF046}` (MARK-1), and
transiently `src/parcel_robot/runtime.py::F401` (ROAM-1's `KIND_ROAM` imports).
None is in ENV-1b's OWNS. Whoever runs the tree-wide ratchet at the wave close
should attribute these to their cards, not to this one.

### Seeded RED — every new guard, mutation run rather than described

Driver: `/home/jaewoo-jang/.cache/parcel-env1b/seed.py`. Each mutation is applied
to the product, the named guards run, the file restored from a byte-exact
backup, **all `__pycache__` under the repo purged**, and the guards re-run green.
md5 checked after each restore.

| # | seeded defect | guard(s) that must catch it | result |
|---|---|---|---|
| S1 | `--check`'s REFUSED paragraph back to one list + the ROS 2 remedy for everything (pre-ENV-1b, in effect) | `test_a_device_absent_refusal_gives_the_attach_remedy_not_the_sdk_remedy` | **RED** 1 failed → restored → 1 passed |
| S2 | `_require_enumerated_device` back to `return` (the fail-open ENV-1 shipped) | `test_a_build_with_no_rs_context_refuses_instead_of_falling_through_to_start` | **RED** 1 failed → restored → 1 passed |
| S3 | `d455.accel` / `d455.gyro` deleted from `STREAM_PROFILES` | `test_a_full_preflight_run_never_imports_a_vendor_sdk` (item 4's two added rows) | **RED** 1 failed → restored → 1 passed |
| S4 | `require_device()` moved BEFORE `require_dependencies()` in `_module` | `…never_imported_the_vendor_sdk` (item 1's branch) | **RED in the wheel-HIDDEN arm only** |

Two of these are worth reading in detail.

**S3 proves the added rows, not the old ones.** With accel/gyro gone from
`STREAM_PROFILES` the first four rows still pass and the failure lands on the
fifth:

```
AssertionError:   ADVISORY …: CHANNEL_ABSENT: d455.accel (important, matrix says live)
  is ABSENT: not_attempted — d455.accel: pyrealsense2 is importable but this reader
  factory ships no live realsense reader …
assert 'device_node_missing' in '…d455.accel…'
```

**S4 proves item 1's branch is load-bearing, not decorative.** Swapping the two
gates makes the wheel-absent venv report the device reason instead of the module
reason. Same seed, same guards, two venvs:

```
### wheel PRESENT (seeded)   2 passed in 0.25s        <- the old arm cannot see it
### wheel HIDDEN  (seeded)   1 failed, 1 passed
E  assert 'REASON dependency_missing' in 'SATISFIED False\nREASON device_node_missing\nIMPORTED False\n'
```

The preflight half of S4 stayed green in both arms: on that path preflight's own
module census answers before the adapter's `_module` is reached, so the reason
does not move. That branch's RED is the reproduction at the top of this section
(the pre-fix `device_node_missing` assertion, run under the shim, observed red).

Restoration, verified after the last seed:

```
b11383d46de52cb7958e9178b5399edd  scripts/parcel_capture/ingest/realsense.py
82bdf01588d00e0782514a4e4009491a  scripts/parcel_capture/clockmap.py
```
— identical to the pre-seed backup at `…/parcel-env1b/backup/md5.txt`.

---

## What this does not prove

* **No camera was opened, and none exists.** No robot hardware is on hand (owner,
  2026-08-22): no Go2, no D455, no Orin — only the reSpeaker XVF3800. Every
  attached-device arm is still doubles. **OWNER-GATED rows, with their exact
  commands, for the day a camera arrives:**
  * `ls /dev/video*` then `lsusb | grep -i intel` — the census flips to non-empty.
  * `.parcel/bin/python -m scripts.parcel_capture.clockmap --check` — the D455
    row flips `[ ABSENT]` → `[PRESENT]`, and the **DEVICE MISSING** paragraph
    added by item 2 disappears. Unrun here by construction.
  * `.parcel/bin/python -c "import pyrealsense2 as rs; print(len(list(rs.context().query_devices())))"`
    — the ATTACHED arm of `_require_enumerated_device`.
  * `env -u TMPDIR .parcel/bin/python -m pytest -q tests/test_capture_sidecar.py -k which_half_is_missing`
    — this guard **refuses** with "this host has hardware attached and cannot
    measure the hardwareless invariant" once a camera is present. That is by
    design and is the next card's problem, not a regression.
* **The wheel-absent venv is modelled, not built.** The shim hides the wheel from
  the import path; it does not reproduce a from-scratch `pip install .[dev]`
  (different transitive versions, no `opencv-python-headless`, etc.). The claim
  proved is precisely "the six assertions no longer depend on `pyrealsense2`
  being findable", which is the claim the card made.
* **`cv2` is still unpinned by any test** — unchanged from ENV-1, restated here
  because item 3 removed the last docstring that mentioned it.
* **Item 5's refusal path has never met a real librealsense build without
  `rs.context`.** No such build is known to exist; the guard runs against a
  double with the attribute deleted. If a real one turns up, the new behaviour is
  a refusal where there used to be a crash — strictly better, but still untested
  against the vendor.
* **The Orin path is simulated.** Item 2's MODULE-MISSING half is the arm a
  correctly-set-up Orin never sees; the arm it *does* see (everything present,
  exit 0) is pinned only by Fable's existing modelled guard.
* Not run: `scripts/ci_gate.py`, the full suite, xdist. Fable's gate is the
  authority on the tree.

---

## Deviations from OWNS (declared)

1. **One bullet beyond item 3's line range.** The card scoped
   `scripts/parcel_capture/__init__.py` to lines 10–13. I also reworded the very
   next bullet ("no vendor SDK installed into `.parcel/`" → "no **motion** SDK
   …"). Reason: it is the same dead premise one line down — `pyrealsense2` *is*
   installed into `.parcel` — and fixing 10–13 while leaving it would have left
   the file self-contradicting. Same file, same OWNS entry, four lines.
2. **Item 5 gated rather than declared.** The card allowed either. I closed it;
   the three reasons are in the item-5 section above. This is a behaviour change
   on a code path nobody here can exercise against a real vendor build, so it is
   flagged as the one judgement call in this card.
3. **Two assertions added to keep wheel-absent arms non-vacuous** (sidecar
   `device_report()` ABSENT; `/dev/video*` + `USB 3 (BLUE)` in both report arms).
   Not asked for; without them the branch would assert less in the `.[dev]` venv
   than in `.parcel`, which is how a branch becomes a skip in disguise.
4. **Seeds S3 and S4 mutated regions of `ingest/realsense.py` outside my edit
   scope** (`STREAM_PROFILES`, the gate ordering in `_module`) — temporarily, to
   produce the RED, restored byte-identically and md5-verified within the same
   command. No seed ever touched `probe_availability`, `PROBE_REQUIREMENTS`,
   `ingest/base.py`, `pyproject.toml` or anything under `src/`.

Git stayed read-only (`diff`/`status`/`log` only). No process was started or
killed. Scratch lived under `/home/jaewoo-jang/.cache/parcel-env1b/`.
`parcel_memory.sqlite3` was never opened. `docs/`, `backlog/`, `README.md` and
`scrum/20260821/` were not touched. Every edit was made with a targeted
edit-in-place after re-reading the region; no existing file was `Write`-replaced.
No credentials were needed or used.

---

## Handoffs

### Item 6a — D455 arrival checklist: `uvcvideo` must actually bind

The `/dev/video*` census that `RealSenseIngest.device_report()` and
`clockmap.device_nodes_present()` both rest on presumes the **`uvcvideo` kernel
driver binds the D455**. RSUSB-backend guides for librealsense sometimes
blacklist `uvcvideo` (the RSUSB backend talks to the camera through libusb and
does not need it), and on such a host a perfectly working D455 produces **no
`/dev/video*` node at all** — the census would then refuse `device_node_missing`
on a camera that is attached and readable, which is a false negative in the same
report ENV-1 fixed for false positives.

Add to the arrival checklist, before anything else:

```
lsmod | grep uvcvideo                 # must print a line once the D455 is plugged in
cat /etc/modprobe.d/*.conf | grep -i uvcvideo   # must NOT show `blacklist uvcvideo`
ls /dev/video*                        # the census's own input
```

Measured on this box today: `lsmod | grep -c uvcvideo` → **0**. The module is not
loaded, which is expected with no UVC device attached (it autoloads on attach) —
but it means the very first plug-in is also the first test of this assumption.
If the node never appears while `lsusb | grep -i intel` does, the fix is a
`_require_enumerated_device`-style librealsense enumeration *instead of* the
`/dev` census for that host, not a relaxed census.

### Item 6b — VENUE-1: P1-A's daemon tests break under any long `TMPDIR`

`tests/test_p1a_perception_daemon.py:97` binds its unix socket inside `tmp_path`:

```python
def socket_path(tmp_path) -> str:
    return str(tmp_path / "p1a_perception.sock")
```

`AF_UNIX` `sun_path` is **108 bytes**. pytest's `tmp_path` already nests
`pytest-of-<user>/pytest-<n>/<test-name-truncated-to-30>/`, so a `TMPDIR` of any
length above roughly 40 characters overflows it — a realistic path under
`~/.cache/parcel-fable-gate/` measures **129 bytes**. This is exactly what turned
Fable's 05:45 gate red (7 failures + 13 errors, all `OSError: AF_UNIX path too
long`; `AUDIT_WAVE_P1P2_FABLE.md`, "Not a tree defect — a verifier environment
defect"). It is not fixed, only avoided by running with `TMPDIR` unset.

**Not edited — `tests/test_p1a_perception_daemon.py` is not ENV-1b's OWNS.** For
VENUE-1, which will own the daemon wiring: bind under a short, fixed directory
(`tempfile.mkdtemp(dir="/tmp")` or a per-test `pathlib.Path("/tmp")` name) rather
than `tmp_path`, or have the daemon accept an abstract-namespace socket. Until
then, every gate that touches these tests must run with `TMPDIR` unset, and any
executor who sets a long `TMPDIR` will see a red that is theirs, not the tree's.

### Item 6c — for whoever closes the wave's ruff ratchet

See the observation under **ruff** above: the tree-wide fingerprint set is
currently above 7 because of concurrently-executing cards (TURN-1, MARK-1,
ROAM-1). ENV-1b's OWNS is clean at zero.
