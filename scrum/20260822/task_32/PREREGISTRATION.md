# TRUTH-1 · PRE-REGISTRATION (task_32)

Written **before** any acceptance number was measured. Executor: Claude Opus.
Verifier: Fable. Board: `../TASK_BOARD.md`. Card: `README.md`.

## What was already measured before this file existed, and why that is not cheating

Three *environment inputs* were read first, because the corrected text cannot be
written without them. They are inputs to the new sentences, not acceptance rows,
and every one of them is republished verbatim in `TRUTH1_STATUS.md` with its
command:

* `.parcel/bin/pip index versions pyrealsense2` → installed **2.58.3.10794**, latest the same.
* PyPI JSON for 2.58.3.10794 → **13 files**: cp310/311/312/313/314 `manylinux1_x86_64`,
  cp39/cp310/cp312 `manylinux2014_aarch64`, cp310/311/312/313/314 `win_amd64`.
* `.parcel/lib/python3.14/site-packages/pyrealsense2-2.58.3.10794.dist-info/{WHEEL,METADATA}`
  → `Tag: cp314-…`, `Requires-Python: >=3.9`, classifiers 3.10–3.14; a real
  `pyrealsense2.cpython-314-x86_64-linux-gnu.so` (27 MB) is present.
* `ls /dev/video*` → nothing. No camera is attached to this host.

**No acceptance row below has been run.** Every BEFORE output in the status doc
is captured after this file is written, from this pre-registered command list.

## Acceptance rows (pass/fail, with the exact command)

Counts are **exact**; a row is a MISS if the number differs, and a miss is
reported as a miss.

| # | Row | Pass |
|---|---|---|
| R1 | `clockmap --check` MODULE-MISSING paragraph is **per device**. Arm: d455 module hidden, go2/l2 modules hidden. | the d455 remedy contains `.parcel/bin/pip install -e '.[camera-realsense]'`; occurrences of `Orin inside the ROS 2 Humble environment` **attached to d455 = 0**; the go2/l2 remedy still contains that sentence (≥1). Existing contract unchanged: exit 2, `REFUSED`, `permanently unrecoverable`. |
| R2 | `RealSenseIngest.requirements[0].remedy` | contains the `pip install -e '.[camera-realsense]'` line; occurrences of `Orin only` = 0; occurrences of `no wheel exists for 3.11+` = 0; carries the measured census **and the date 2026-08-22**. |
| R3 | `preflight._TRANSPORT_MODULES` | `realsense` remedy: occurrences of `Orin` = 0, contains the pip line. `dds`, `vendor_video`, `vendor_uwb`, `unilidar_sdk2` remedies: each still names the Orin (≥1). |
| R4 | `python -m scripts.parcel_capture.record --check` on this camera-less box | every channel row whose transport declares a `/dev` node and has none reads **`NO DEVICE`**; rows reading `reader deps present` for such a channel = **0**; the output contains the adapter-level ENV-1 block, i.e. `dependency_report_text()` gains **≥1 product caller** (grep for `NO DEVICE (installed: pyrealsense2)` in the CLI's own stdout). Exit code unchanged (3 on this box: rclpy/unilidar/tegrastats/ffmpeg still absent). |
| R5 | `scripts/parcel_capture/__init__.py` | occurrences of `there is no aarch64 build` = 0; the replacement carries the 13-wheel census, names cp39/cp310/cp312 as the aarch64 set, and is dated 2026-08-22. |
| R6 | `tools/replay_turn_detection.py` report | the written JSON carries top-level **`settle_s`** equal to the value passed; **every** `utterance_rows` entry carries `wall_offset_ms`, `wall_elapsed_ms`, `wall_minus_audio_ms`, `commits_wall_relative_ms`, `commit_latency_wall_ms`. Discrimination row: 2 files, `settle_s = 0.15` → file `02`'s `wall_minus_audio_ms` **≥ 100 ms** and file `01`'s **< 100 ms**, and `commits_wall_relative_ms[0] == commits_raw_ms[0] − wall_offset_ms` to ±0.1 ms. |
| R7 | the tool's docstring | occurrences of a claim that `--arms/--check/--plan` cannot reach **`lane`** = 0. Measured replacement: a subprocess running `--arms` reports `parcel_robot.realtime.lane` in `sys.modules` = **True** and `parcel_robot.realtime.ws_transport` in `sys.modules` = **False**. |
| R8 | `task_25/SESSION.md` | the primary field name `asr_beam_echo_attenuation_db` leads in **both** the §5 prose and the pre-registered-rows table (`erle_db` shown as the alias, not as the name); the mux path's prerequisites appear **exactly once**, as one block, and name all three: the step-3 udev rule + `pyusb`, firmware **v2.0.6**, and **never flash the 6-channel image**. `6-channel` occurrences in the file: was 0, becomes ≥1. |
| R9 | `planner_model` (CAP-1's carried finding) | `check_overlay_keys(base, {"planner_model": {"enabled": True}})` raises **before**, does not raise **after**; `admission.admitted()`'s `planner_model` row `admitted is True` and its reason names `OVERLAY_INTRODUCIBLE_KEYS`; the unreachable-section set becomes **empty** (`set()`), and CAP-1's pin in `tests/test_cap1_admission.py` is **updated in the same change** to assert emptiness (so a second instance of the class still reddens); a typo *inside* the section (`plan_timeoutt`) is refused **by name** where the section is read. |

## Seeded-RED, one per new guard

| Seed | Mutation | Must redden |
|---|---|---|
| S1 | `record.dependency_report` back to a module-only census | R4's guard |
| S2 | the d455 remedy re-worded to name the Orin (each of the three sites, one at a time) | R1/R2/R3 guards |
| S3 | drop `settle_s` from the written report | R6's guard |
| S4 | remove `planner_model` from `OVERLAY_INTRODUCIBLE_KEYS` | R9's guard **and** CAP-1's updated pin |
| S5 | remove the spelling guard at the `planner_model` read site | R9's typo guard |

Every seed is applied to the product, the guard is run, and the product is
restored **byte-identically** (sha256 before/after in the status doc).

## Gates

* Targeted `pytest` only (never `scripts/ci_gate.py`, never the full suite),
  `TMPDIR` unset, `.parcel/bin/python`:
  `tests/test_truth1_texts.py tests/test_clockmap.py tests/test_capture_ingest.py
  tests/test_turn1_endpointing.py tests/test_cap1_admission.py
  tests/test_prototype_profile.py tests/test_web_panel.py`.
* `.parcel/bin/ruff check` on the touched files: **0 findings**. Tree-wide
  fingerprint ratchet stays at **exactly 7**; this card adds **none**, fixes at
  source, uses no `noqa`, re-pins nothing. (Tree-wide `ruff check .` reports 12
  at the moment this file is written — 5 of them under
  `src/parcel_robot/camera_channel/` and `src/parcel_robot/detection_adapter/`
  belong to a concurrent card, none to any file this card touches.)

## What this card cannot prove, stated in advance

Every attached-camera arm (`device_report()` ATTACHED, a non-empty
`rs.context().query_devices()`, a frame past `pipeline.start()`), every hosted
`--replay` number, and every through-air AIR-1 row. No hardware is on hand
except the XVF3800 mic array, which this card never opens, plays through or
writes to.
