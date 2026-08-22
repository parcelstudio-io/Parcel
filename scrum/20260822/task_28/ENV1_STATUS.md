# ENV-1 — the dev box may carry a vendor SDK · STATUS

**Card:** `../TASK_BOARD.md` (Build-order table, ENV-1) · **Executor:** Claude Opus
**Verifier:** Fable · **Date:** 2026-08-22

---

## Headline

Seven capture-stack tests encoded an **environment premise** — "this hardwareless
dev box has NO vendor SDK installed" — that P1-A made false on 2026-08-22 by
legitimately installing `pyrealsense2` 2.58.3 and `opencv-python-headless` into
`.parcel` for the desk-camera venue. Every one of the seven is now re-cut onto
the **property** it was actually protecting, and none of them is weaker.

The premise died because it conflated two facts. The capture stack now keeps
them apart everywhere:

| | the module | the device |
|---|---|---|
| **dds** | `rclpy` absent → `dependency_missing` | no `/dev` node declared → `not_attestable` |
| **realsense** | `pyrealsense2` **installed** | no `/dev/video*` → `device_node_missing` |
| **l2** | `unilidar_sdk2` absent → `dependency_missing` | `/dev/ttyACM*` also absent |

The measured payoff, on this box, from one `attest --window 0.01` run. Before:

```
DEGRADE: CHANNEL_ABSENT: d455.color (critical, matrix says live) is ABSENT:
  probe_raised — RuntimeError: stop() cannot be called before start()
```

After — the right call, the right device, an actionable remedy:

```
DEGRADE: CHANNEL_ABSENT: d455.color (critical, matrix says live) is ABSENT:
  device_node_missing — realsense: nothing matches /dev/video* — no device of this
  kind is attached to this host REMEDY: plug the D455 into a USB 3 (BLUE) port,
  direct, no hub, and confirm it enumerates: `ls /dev/video*` then
  `lsusb | grep -i intel`. ...
```

`VENDOR []` still holds: **the SDK is never imported.** The `/dev` census runs
*before* `importlib.import_module`, so a box with the wheel and no camera answers
without ever loading librealsense.

---

## The five failures, as they read before the card

| test | exact message |
|---|---|
| `test_capture_ingest.py::test_each_live_adapter_refuses_on_this_box_naming_its_module_and_a_remedy[RealSenseIngest-pyrealsense2]` | `AssertionError: assert not True … DependencyReport(adapter='realsense', satisfied=True, present=('pyrealsense2',), missing=(), remedy='').satisfied` |
| `…::test_the_dependency_report_is_actionable_text_and_never_a_traceback` | `AssertionError: assert 'pyrealsense2' in 'channels in the matrix: 28 …'` (the realsense line had collapsed to a bare `READY`) |
| `…::test_a_module_that_vanishes_between_the_probe_and_the_open_is_a_named_refusal[<lambda>-pyrealsense2-<lambda>]` | `Failed: DID NOT RAISE <class '…IngestUnavailableError'>` (deleting it from `sys.modules` just re-imported it) |
| `test_capture_preflight.py::test_a_full_preflight_run_never_imports_a_vendor_sdk` | `assert 'VENDOR []' in "… VENDOR ['pyrealsense2', 'pyrealsense2.pyrealsense2']"` |
| `test_capture_rehearsal.py::test_no_vendor_sdk_is_reachable_and_none_was_installed` | `AssertionError: pyrealsense2 is installed — it must not be` |
| `test_capture_sidecar.py::test_this_host_has_none_of_the_live_capture_dependencies` | `AssertionError: pyrealsense2 must not be installed in this venv` |
| `test_clockmap.py::test_probe_availability_fails_closed_on_this_hardwareless_dev_box` | `AssertionError: SourceDevice.D455 claims a probe this box cannot run — assert True is False` |

Traced with an `sys.addaudithook` import spy: the import came from
`RealSenseIngest.open_pipeline → _module → importlib.import_module`, inside the
channel probe — **not** an eager import on the import path. The card's guess
(`camera_channel/backends/realsense.py` or the backends `__init__`) was wrong;
that file already imports lazily inside its factory and needed no change.

---

## What changed

`git diff --stat` on OWNS:

```
 scripts/parcel_capture/clockmap.py         |  60 +++++-
 scripts/parcel_capture/ingest/__init__.py  |  34 ++-
 scripts/parcel_capture/ingest/base.py      | 131 +++++++++++-
 scripts/parcel_capture/ingest/realsense.py |  71 ++++++-
 tests/test_capture_ingest.py               | 321 +++++++++++++++++++++++++++--
 tests/test_capture_preflight.py            |  45 +++-
 tests/test_capture_rehearsal.py            |  47 +++--
 tests/test_capture_sidecar.py              |  45 +++-
 tests/test_clockmap.py                     |  62 +++++-
 9 files changed, 766 insertions(+), 50 deletions(-)
```

Edit-only, on existing files. No new product file, no file deleted, nothing
uninstalled, `pyproject.toml` untouched.

### The re-cut, per the card's four clauses

**(a) refuses on a box with no DEVICE, naming module/remedy — kept, parametrized.**
`test_each_live_adapter_refuses_on_this_box_naming_its_module_and_a_remedy` →
`test_each_live_adapter_refuses_here_naming_the_missing_module_or_the_missing_device`.
Two arms per adapter: MODULE-ABSENT (monkeypatched `find_spec` for whichever SDK
happens to be installed) asserts `dependency_missing` with the module and an
Orin remedy — the original assertions verbatim; MODULE-PRESENT asserts
`device_node_missing`, `/dev/` named, a remedy naming `USB 3 (BLUE)`, and no
traceback. `dds`/`l2` declare no `/dev` node and must report `not_attestable`
rather than guessing "attached".

**(b) a full preflight run never IMPORTS a vendor SDK — kept WORD FOR WORD.**
`assert "VENDOR []"` is unchanged. It earns it again because `require_device()`
now runs *before* `importlib.import_module` in `RealSenseIngest._module`. The
guard also gained the reason assertions, so the property can never again be
satisfied by the probe simply not running: the four D455 rows must read
`device_node_missing`, must NOT read `probe_raised`, and `go2.lowstate` must
still read `dependency_missing — rclpy` (the two reasons stay distinguished).
A companion guard,
`test_the_module_present_refusal_never_imported_the_vendor_sdk`, measures
`'pyrealsense2' in sys.modules` in a clean subprocess after the refusal.

**(c) "none was installed" — premise replaced by the real invariant.**
`test_no_vendor_sdk_is_reachable_and_none_was_installed` →
`test_no_motion_sdk_is_reachable_and_an_installed_camera_sdk_reaches_no_device`;
`test_this_host_has_none_of_the_live_capture_dependencies` →
`test_no_live_reader_can_run_here_and_the_report_says_which_half_is_missing`.
The split is **by what a module can DO**: the SDKs that can command or decode
the dog (`rclpy`, `cyclonedds`, `unitree_sdk2py`, `unilidar_sdk2`, `mcap`,
`zstandard`) must stay absent from `.parcel` — that is the motion guarantee and
it is untouched. A camera SDK may be present, and what replaces "it is not
installed" is: every live reader still refuses here, and the refusal names
*which half* is missing. `test_the_dependency_report_is_actionable_text_…` →
`test_the_dependency_report_names_each_module_state_…`, which reads the report
block by block and requires three states, not two: `UNAVAILABLE (missing: …)`,
`NO DEVICE (installed: pyrealsense2)`, `READY`.

**(d) clockmap fails closed on DEVICE absence.** `probe_availability()` now
conjoins three independent conditions, all fail-closed: the device must be
*interrogable* at all (the Go2 is not — RITUAL ONLY, so no install and no cable
can ever make its probe runnable), some required *module* must be importable,
and no declared *device node* may be missing. The module census is still
returned, so `(False, ("pyrealsense2",))` reads as "the SDK is here, the camera
is not" and `(False, ())` as "the SDK is missing". `--check` prints a
`needs a device at: /dev/video*   attached: NOTHING` line and still exits 2.

---

## How verified

Env: `.parcel/bin/python` (3.14), `.parcel/bin/ruff` 0.16.1,
`TMPDIR=/home/jaewoo-jang/.cache/parcel-env1`. Targeted pytest + ruff only;
`scripts/ci_gate.py` was **not** run.

### The five files

```
.parcel/bin/python -m pytest -p no:randomly tests/test_capture_ingest.py     -q  ->  90 passed
.parcel/bin/python -m pytest -p no:randomly tests/test_capture_preflight.py  -q  -> 248 passed
.parcel/bin/python -m pytest -p no:randomly tests/test_capture_rehearsal.py  -q  ->  88 passed
.parcel/bin/python -m pytest -p no:randomly tests/test_capture_sidecar.py    -q  -> 102 passed
.parcel/bin/python -m pytest -p no:randomly tests/test_clockmap.py           -q  -> 136 passed
```

All five together in **random order** (default `pytest-randomly` seat, no
`-p no:randomly`): **664 passed in 13.07s**.

### Collateral — everything else that reads the capture stack

```
.parcel/bin/python -m pytest tests/test_no_arm_pin.py tests/test_capture_envelope.py \
  tests/test_bandwidth_budget_doc.py tests/test_disk_ledger_doc.py tests/test_orin_rehearsal.py \
  tests/test_tonight_checklist_drivers.py tests/test_stage0_command_addendum.py \
  tests/test_syncevents.py tests/test_rosbag2_sidecar.py tests/test_stage0_addendum.py \
  tests/test_p1a_camera_backends.py -q      ->  662 passed in 24.52s
```

`tests/test_no_arm_pin.py` is the one that mattered: it walks every file under
`scripts/parcel_capture/` statically **and** imports each module in a subprocess
against a fake vendor SDK. The new device path uses the already-vetted reaches
(`read_field`, a `ReadOnlyHandle` whose allowlist is exactly `query_devices`) and
adds no entry to `VETTED_REACHES`.

### ruff

```
.parcel/bin/ruff check . --output-format=concise
```

Byte-identical before and after: **12 findings across 5 files, 7 `relpath::code`
fingerprints**, all pre-existing and all in `src/parcel_robot/{camera_channel,
detection_adapter}` — none in `scripts/parcel_capture/` or `tests/`. Two
findings I did introduce were fixed before this line was written (a `RUF022`
`__all__` ordering in `clockmap.py` and a `RUF100` unused `# noqa: BLE001` in
`realsense.py`). **Zero fingerprints added; the ratchet stays at 7.**

### Seeded RED — every re-cut guard, mutation run rather than described

Each mutation was applied to the product, the named guards were run, and the
product was restored from a byte-exact backup (md5 verified after the loop).
Driver: `/home/jaewoo-jang/.cache/parcel-env1/seed.py`.

| # | seeded defect | guard(s) that must catch it | result |
|---|---|---|---|
| M1 | both device gates removed from `RealSenseIngest` | `test_each_live_adapter_refuses_here_naming_the_missing_module_or_the_missing_device` | **RED** 1 failed, 2 passed |
| M2 | `require_device()` moved to AFTER `import_module` | `test_the_module_present_refusal_never_imported_the_vendor_sdk`, `test_a_full_preflight_run_never_imports_a_vendor_sdk` | **RED** 2 failed |
| M3 | `dependency_report_text` back to two states (bare `READY`) | `test_the_dependency_report_names_each_module_state_and_is_never_a_traceback` | **RED** 1 failed |
| M4 | `device_report()` always `ATTACHED` | rehearsal + sidecar + ingest guards | **RED** 5 failed |
| M5 | `probe_availability` satisfied by modules alone (the pre-card rule, verbatim) | `test_probe_availability_fails_closed_on_this_hardwareless_dev_box`, `test_seeded_red_a_probe_satisfied_by_its_module_alone_is_caught` | **RED** 2 failed |
| M6 | `handle.stop()` back in an unconditional `finally` | `test_a_failed_start_is_not_masked_by_the_stop_in_the_finally` | **RED** 1 failed |
| M7 | the vanish race re-raises the raw `ImportError` | `test_a_module_that_vanishes_between_the_probe_and_the_open_is_a_named_refusal` | **RED** 1 failed, 2 passed |
| M8 | `rs.context().query_devices()` check skipped | `test_a_webcam_on_dev_video_is_not_a_realsense_and_the_enumeration_says_so` | **RED** 1 failed |

---

## What this does not prove

* **No camera was ever opened.** Every live row remains OWNER-GATED on plugging
  in a D455 or any UVC webcam. The ATTACHED arm of `device_report`, the
  librealsense enumeration returning a device, and the read loop past
  `pipeline.start()` are all exercised against doubles only.
* **`/dev/video*` is a proxy, not proof.** The import-free census cannot tell a
  D455 from a laptop webcam. That is exactly why `_require_enumerated_device`
  exists behind it — but that second gate has only ever run against a fake
  `rs.context()`. On a host with a webcam and no RealSense the refusal path is
  reasoned, not measured.
* **The Orin path is untested.** Nothing here ran on a Jetson, with `rclpy`
  present, or with a real DDS peer. `dds`/`l2` device presence stays
  `not_attestable` by construction and the read remains their only probe.
* **`opencv-python-headless` / `cv2` is now unpinned by any test.** The old
  premise asserted it absent; the re-cut deliberately stops asserting anything
  about it, because nothing in the capture stack imports it. If a later card
  wants `cv2` constrained, that is a new guard, not a restored one.
* **`mcap` and `zstandard` are still asserted absent** in the rehearsal guard.
  If a future card installs an MCAP reader into `.parcel`, that assertion breaks
  for the same reason this card exists — and the fix will be the same shape.
* Not run: `scripts/ci_gate.py`, the full suite, xdist. Fable's gate is the
  authority on the tree.

---

## Deviations from OWNS (declared)

The card scoped ENV-1 to the seven tests plus "one line" of P1-A's
`camera_channel/backends/realsense.py`. **That one line was not needed** — the
eager import the card predicted does not exist; the backends package already
imports lazily inside its session factory, and `src/parcel_robot/` was not
touched at all. Four product files under `scripts/parcel_capture/` were changed
instead, because clauses (a), (c) and (d) are unenforceable without them: a
guard asserting "the refusal reason must be device-absent" cannot pass against a
stack that has no notion of a device.

1. **`scripts/parcel_capture/ingest/base.py`** — added `DevicePresence`
   (ATTACHED / ABSENT / NOT_ATTESTABLE), `DeviceReport`, and
   `IngestAdapter.device_report()` / `.require_device()` plus the
   `device_nodes` / `device_remedy` class hooks. A `/dev` glob census; imports
   nothing. `require_device` deliberately does **not** refuse on
   NOT_ATTESTABLE — doing so would ground `dds` and `l2` on an Orin where the
   dog is genuinely reachable.
2. **`scripts/parcel_capture/ingest/realsense.py`** — declares
   `device_nodes = ("video*",)` and a remedy; calls `require_device()` **before**
   `import_module` (this ordering is what preserves property (b)); adds
   `_require_enumerated_device` for the precise, post-import check; and fixes
   the `finally: handle.stop()` bug that masked the real failure.
   **This is a real bug, found by this card**, and it is the reason all six D455
   rows read `RuntimeError: stop() cannot be called before start()` — a message
   naming the wrong call, no device and no remedy.
3. **`scripts/parcel_capture/ingest/__init__.py`** — `dependency_report_text`
   prints three states instead of two, plus a `device:` line and a `plug:`
   remedy. Required by clause (c) in the card's own words ("the dependency
   report names each module's state").
4. **`scripts/parcel_capture/clockmap.py`** — `ProbeRequirement.device_nodes`,
   a `device_nodes_present()` helper, and the three-condition
   `probe_availability`. Blast radius is small and was checked: the only
   consumers are the `--check` CLI and `tests/test_clockmap.py`.
   **Note the extra condition beyond the card's letter:** `interrogable` now
   participates in `satisfied`, so the Go2 reads ABSENT even on an Orin with
   `rclpy` installed. That is the same defect class the card names — a module
   flipping a probe that no cable can make runnable — and the Go2 exposes no
   queryable clock at all. Flagged for the verifier as the one judgement call
   that changes behaviour on hardware nobody here can test.

Two test names outside the seven were also changed, both in files I own and both
forced by the re-cut: the ingest-file helper `_install_fake_realsense` now
models the BUS as well as the module (`devices=` parameter, default 1), because
the import-free gate means installing a double into `sys.modules` is no longer
enough to reach the read loop.

Git stayed read-only throughout (`diff`/`status` only). No process was started
or killed. Scratch lived under `/home/jaewoo-jang/.cache/parcel-env1/`.
`parcel_memory.sqlite3` was never opened. `docs/`, `backlog/`, `README.md` and
`scrum/20260821/` were not touched.

---

## Handoffs

* **Fable:** the one judgement call to audit is the `interrogable` term in
  `probe_availability` (deviation 4) — behaviour change on the Orin, unmeasurable
  here.
* **P1-A / VENUE-1:** `scripts/parcel_capture/ingest/base.py` now exports a
  `device_report()` seam. If the runtime venue path wants the same
  installed-vs-attached distinction, it is one classmethod and a `device_nodes`
  declaration away; `camera_channel/backends/realsense.connected_devices()` is
  the authoritative equivalent already shipped on that side.
* **Owner:** when the D455 arrives, the live arms this card could not measure
  are `device_report() is ATTACHED`, the librealsense enumeration returning a
  device, and the read loop past `pipeline.start()`. `--check` will flip to
  `[PRESENT] d455` on its own.
