# TRUTH-1 · STATUS (task_32) — **## Complete · correction pass applied (8/9 rows MET; R3 a declared MISS; 6 FIX closed)**

**Executor:** Claude Opus (FIFTH resume, session started ~06:20 EDT 2026-08-23).
**Verifier:** Fable (parcel-6c, 31fcc2a0). **Card:** `README.md`. **Design:**
`DESIGN.md`. **Rows:** `PREREGISTRATION.md`, verbatim, unmodified —
`sha256 b5c8dd59c6727e90715def77762ef8ca276a92ec71b068caf116d16a3217fae7`
(re-verified 2026-08-23 06:2x with `sha256sum`; the file's mtime is 15:27 on
08-22, before any acceptance number existed).

*This document was written incrementally, row by row, because four previous
sessions died mid-card (all four were kernel OOM kills from `pytest -n auto`,
not this card's work). The header said "In progress" until the last row closed;
had this session died too, that header would have meant the session died, not
that a row was hidden.*

## Environment inputs (measured BEFORE the pre-registration; republished here as it requires)

Every one of these is an INPUT to the corrected sentences, not an acceptance
row. Re-measured today; the numbers are unchanged from 08-22.

```
$ .parcel/bin/pip index versions pyrealsense2
pyrealsense2 (2.58.3.10794)
Available versions: 2.58.3.10794, 2.58.2.10647, 2.58.1.10581, 2.58.0.10793, 2.57.7.10387
  INSTALLED: 2.58.3.10794
  LATEST:    2.58.3.10794
```

```
$ .parcel/bin/python  # urllib GET https://pypi.org/pypi/pyrealsense2/2.58.3.10794/json
files: 13
   pyrealsense2-2.58.3.10794-cp310-cp310-manylinux1_x86_64.whl
   pyrealsense2-2.58.3.10794-cp310-cp310-manylinux2014_aarch64.whl
   pyrealsense2-2.58.3.10794-cp310-cp310-win_amd64.whl
   pyrealsense2-2.58.3.10794-cp311-cp311-manylinux1_x86_64.whl
   pyrealsense2-2.58.3.10794-cp311-cp311-win_amd64.whl
   pyrealsense2-2.58.3.10794-cp312-cp312-manylinux1_x86_64.whl
   pyrealsense2-2.58.3.10794-cp312-cp312-manylinux2014_aarch64.whl
   pyrealsense2-2.58.3.10794-cp312-cp312-win_amd64.whl
   pyrealsense2-2.58.3.10794-cp313-cp313-manylinux1_x86_64.whl
   pyrealsense2-2.58.3.10794-cp313-cp313-win_amd64.whl
   pyrealsense2-2.58.3.10794-cp314-cp314-manylinux1_x86_64.whl
   pyrealsense2-2.58.3.10794-cp314-cp314-win_amd64.whl
   pyrealsense2-2.58.3.10794-cp39-cp39-manylinux2014_aarch64.whl
aarch64 (manylinux2014): ['cp310', 'cp312', 'cp39']
x86_64  (manylinux1)   : ['cp310', 'cp311', 'cp312', 'cp313', 'cp314']
win_amd64              : ['cp310', 'cp311', 'cp312', 'cp313', 'cp314']
```

Full transcript: `~/.cache/parcel-truth1/evidence/wheel_census_20260823.txt`.
This is the census the fourth executor was capturing when it was OOM-killed at
05:38:42; re-run whole today, same 13 files.

```
$ cat .parcel/lib/python3.14/site-packages/pyrealsense2-2.58.3.10794.dist-info/WHEEL
Wheel-Version: 1.0 / Generator: hatchling 1.31.0 / Root-Is-Purelib: true
Tag: cp314-cp314-linux_x86_64
$ grep Requires-Python .../METADATA        →  Requires-Python: >=3.9
$ classifiers                              →  3.10, 3.11, 3.12, 3.13, 3.14
$ ls -la .parcel/.../pyrealsense2/pyrealsense2.cpython-314-x86_64-linux-gnu.so
   27528728 bytes (27 MB), plus pyrealdds (11 MB) and pyrsutils (854 KB)
$ ls /dev/video*
   ls: cannot access '/dev/video*': No such file or directory
```

No camera is attached to this host, and `pyrealsense2` is genuinely importable
here. Those two facts together are the whole card.

## Rows

| # | Verdict | Note |
|---|---|---|
| R1 | **MET** | `clockmap --check`'s MODULE-MISSING paragraph is now per device. |
| R2 | **MET** | `RealSenseIngest.requirements[0].remedy`: `Orin only` 0, `no wheel exists for 3.11+` 0, pip line + dated census present. |
| R3 | **MISS (declared, 1 vs 0)** | `Orin` in the realsense preflight remedy = **1**, registered pass = **0**. See §Deviations — the row was registered at 15:27 on 08-22, the owner named the Orin as the real deploy host at 16:00, and a remedy that hides that is the same lie in the other direction. The four vendor remedies still name the Orin (≥1) as registered. |
| R4 | **MET** | `record --check`: `reader deps present` 7 → **0**; all six `d455.*` rows read `NO DEVICE`; `dependency_report_text()` has a product caller; exit 3 unchanged. |
| R5 | **MET** | `__init__.py`: `there is no aarch64 build` = **0**, 13-wheel census + cp39/cp310/cp312 + date present. |
| R6 | **MET** | `settle_s` + five wall columns in the report; the two candidate origins separate by **171.2 ms** on file 02 and **3.0 ms** on file 01; the wall arithmetic reconciles to **0.000 ms**. |
| R7 | **MET** | `--arms` subprocess: `lane` in `sys.modules` **True**, `ws_transport` **False**; the stale claim's phrasing now occurs **0** times. |
| R8 | **MET** | `SESSION.md`: long name leads §5 prose and the rows table; one prerequisites block naming all three; `6-channel` 0 → **1**. |
| R9 | **MET** | `check_overlay_keys` raises BEFORE / passes AFTER; admission row `admitted=True` naming `OVERLAY_INTRODUCIBLE_KEYS`; unreachable set `{planner_model}` → `set()`; CAP-1's pin updated in the same change; `plan_timeoutt` refused BY NAME at the read site. |

## How each row was verified — exact commands and results

Evidence transcripts are under `~/.cache/parcel-truth1/evidence/`.

### R1 — the MODULE-MISSING paragraph is per device

Driven through the PRODUCT `main()` (no fakes; only `importlib.util.find_spec`
is narrowed, so the census sees the modules absent the way it would on a bare
host):

```
$ .parcel/bin/python ~/.cache/parcel-truth1/probe_clockmap2.py . \
      rclpy cyclonedds pyrealsense2 unitree_lidar_sdk_pybind
```

BEFORE (`~/.cache/parcel-truth1/evidence/R1_before.txt`, captured from the
pristine copy at `~/.cache/parcel-truth1/before/`) — **one** sentence for all
three devices:

```
  MODULE MISSING — the SDK is not on this interpreter's import path: d455, go2, l2
  Run this on the Orin inside the ROS 2 Humble environment that owns the vendor SDKs.
```

AFTER (`R1_after.txt`) — one line per REMEDY:

```
  MODULE MISSING — the SDK is not on this interpreter's import path: d455, go2, l2
    d455: pyrealsense2 is an ordinary pip wheel, not a vendor SDK build … `.parcel/bin/pip
          install -e '.[camera-realsense]'` … On the Orin NX (aarch64) it depends on WHICH
          JetPack the dock boots, and that is UNCONFIRMED until the box is opened …
    go2, l2: Run this on the Orin inside the ROS 2 Humble environment that owns the vendor
          SDKs. The Python path to the dog itself is `unitree_sdk2py` over CycloneDDS 0.10.2 …
```

Measured: d455 remedy contains `.parcel/bin/pip install -e '.[camera-realsense]'`
→ yes; `Orin inside the ROS 2 Humble environment` attached to **d455 = 0**;
attached to go2/l2 = 1. Existing contract unchanged: `[exit=2]`, `REFUSED:`
present, `permanently unrecoverable` present.

### R2 / R3 / R5 — the three remedy sites and the package docstring

```
$ .parcel/bin/python  # imports the live objects; transcript: evidence/R2_R3_R5.txt
```

| measurement | value | registered | verdict |
|---|---|---|---|
| R2 `remedy` contains the pip line | True | contains | MET |
| R2 `remedy.count("Orin only")` | 0 | 0 | MET |
| R2 `remedy.count("no wheel exists for 3.11+")` | 0 | 0 | MET |
| R2 `remedy` carries census + `2026-08-22` | True | required | MET |
| R3 `_TRANSPORT_MODULES["realsense"]` `.count("Orin")` | **1** | **0** | **MISS** |
| R3 realsense contains the pip line | True | contains | MET |
| R3 `dds` / `vendor_video` / `vendor_uwb` / `unilidar_sdk2` `.count("Orin")` | 2 / 1 / 1 / 1 | each ≥1 | MET |
| R5 `__init__.py.count("there is no aarch64 build")` | 0 | 0 | MET |
| R5 names cp39/cp310/cp312, 13-file census, `2026-08-22` | True | required | MET |

### R4 — `record --check` on this camera-less box, through the real CLI

```
$ .parcel/bin/python -m scripts.parcel_capture.record --check    # evidence/R4_{before,after}.txt
```

| | BEFORE (pristine copy) | AFTER |
|---|---|---|
| `reader deps present` occurrences | **7** | **0** |
| the six `d455.*` rows | `reader deps present` | `NO DEVICE (installed: pyrealsense2)` |
| `NO DEVICE (installed: pyrealsense2)` in stdout | 0 | **7** |
| exit code | 3 | **3** (unchanged) |

The seventh `NO DEVICE` line is the adapter-level ENV-1 block — that is
`ingest.dependency_report_text()` printing from `_cli_check`, which is the
product caller it had never had. The one row that is neither `UNAVAILABLE` nor
`NO DEVICE` is `mic.xvf3800`, which reads
`deps present (installed: sounddevice); DEVICE NOT ATTESTABLE` — `usb_audio`
declares no `/dev` node, so the filesystem cannot answer, and the row says so
instead of claiming readiness.

### R7 — the tool's docstring, measured rather than asserted

```
$ .parcel/bin/python -c "<load the tool by path, call main(['--arms']), print sys.modules>"
RC 0
lane_in_sys_modules True
ws_transport_in_sys_modules False
```

`parcel_robot.realtime.lane` is reached by every offline mode (the package
`__init__` imports it); `parcel_robot.realtime.ws_transport` is not, and that is
the property that actually matters — importing `lane` opens nothing, importing
`ws_transport` puts a websocket client in the process. Claim occurrences after
the rewrite: **0**.

### R8 — `task_25/SESSION.md`

```
$ .parcel/bin/python  # evidence/R8.txt
'6-channel' BEFORE : 0        'Prerequisites for the mux path' blocks : 1
'6-channel' AFTER  : 1        names udev rule + `pyusb` / v2.0.6 / never flash : yes / yes / yes
```

§5 prose now opens `The measured field is **asr_beam_echo_attenuation_db**`; the
pre-registered rows table row reads
`` | `asr_beam_echo_attenuation_db` (scorecard row id: `erle_db`) | ≥ 20 dB | ``
— long name for the measurement, `erle_db` shown as the frozen row id, which is
the alias relationship the row asked for. The scattered sentence
`This only works once step 3's udev rule is in.` is gone (0 occurrences).

### R9 — `planner_model`, CAP-1's carried finding

HEAD's frozenset is read by AST from `git show HEAD:src/parcel_robot/config.py`
(no import of a stale module, no file mutation), and the PRODUCT
`check_overlay_keys` is called against both datasets:

```
HEAD OVERLAY_INTRODUCIBLE_KEYS      : [camera_ingress, camera_ingress.enabled,
  perception.camera_backend, perception.camera_ingress, …_max_detections_per_frame,
  …_queries, …_queue_capacity, …_rate_hz, perception.detector, roam]
TREE adds                           : ['planner_model']          (exactly one key)

BEFORE check_overlay_keys(base, {"planner_model": {"enabled": True}})
   → ProfileError: overlay: unknown key 'planner_model' — the base configuration does
     not define it, so merging it would change nothing and the setting would silently
     stay at its shipped value. Did you mean: language_model? …
AFTER  → does not raise

admission.admitted() planner_model row: admitted = True
  reason: "absent from the SHA-locked base but listed in OVERLAY_INTRODUCIBLE_KEYS,
           so a profile overlay may introduce it"

unreachable sections BEFORE: ['planner_model']
unreachable sections AFTER : []                       == set()  → True

web_panel._check_planner_model_section({"enabled": True, "plan_timeoutt": 5})
   → ValueError: unknown planner_model config key(s): plan_timeoutt; allowed: base_url,
     context_char_budget, context_messages, enable_thinking, enabled, …
   ({"enabled": True, "plan_timeout": 5.0}) → passes through unchanged
```

Defaults are unchanged: the SHA-locked base still omits the block, so
`planner_config.get("enabled", False)` is still False on every run that does not
write one. This entry only makes writing one possible.

### R6 — the replay report carries both candidate origins

Driven through the TOOL'S OWN `replay()` on a real `RealtimeLane` over
`transport_pair()` — same config path, same `_NullSink`, same `open_session`,
only the socket swapped — over a two-file corpus at `settle_s = 0.15`
(transcript: `evidence/R6.txt`; the same arrangement is the permanent guard in
`tests/test_truth1_texts.py::test_the_replay_report_carries_both_candidate_origins_and_can_tell_them_apart`):

```
schema                  : parcel.turn1.replay.v2
settle_s                : 0.15
wall_minus_audio_ms_max : 171.2

  01: audio_offset=    0.0   wall_offset=    3.0   wall_minus_audio =   3.0
      commits_raw_ms=[600]   commits_wall_relative_ms=[597.0]
      commit_latency_ms=300.0   commit_latency_wall_ms=297.0
      check: raw - wall_offset = 597.0  vs reported 597.0   |diff| = 0.000 ms
  02: audio_offset=  600.0   wall_offset=  771.2   wall_minus_audio = 171.2
      commits_raw_ms=[1200]  commits_wall_relative_ms=[428.8]
      commit_latency_ms=300.0   commit_latency_wall_ms=128.8
      check: raw - wall_offset = 428.8  vs reported 428.8   |diff| = 0.000 ms
```

Registered: file `02`'s `wall_minus_audio_ms` ≥ 100 ms → **171.2 MET**; file
`01`'s < 100 ms → **3.0 MET**; `commits_wall_relative_ms[0] ==
commits_raw_ms[0] − wall_offset_ms` to ±0.1 ms → **0.000 ms MET**. `settle_s`
equals the value passed, and every `utterance_rows` entry carries all five wall
columns.

**Why the row is worth what it cost.** On file 02 the same commit is 300.0 ms
late against the appended-audio origin and 128.8 ms late against the wall
origin. Those are two different answers, from one run, to the question TURN-1's
handoff could only pose: the first live recording can now read which index the
provider used off the report and CORRECT the latency without re-recording the
owner. Before this the report carried one origin and no way to tell.

## Seeded-RED, one per new guard

All five seeds were applied to the **PRODUCT** in the working tree, one at a
time, inside a single `pytest_guard.sh` flock window so that no peer executor's
suite could import a module while it was mutated. Script:
`~/.cache/parcel-truth1/seeds.sh`; transcript:
`~/.cache/parcel-truth1/evidence/seeds.txt`; wall clock **14.9 s** for all seven
arms.

```
$ ~/.cache/parcel-guard/pytest_guard.sh --label truth1 bash ~/.cache/parcel-truth1/seeds.sh
… seed failures: 0 … no .truth1bak left behind
```

The harness refuses to score a seed that does not change the file's sha256, so a
mutation that silently missed its target is reported rather than counted as a
pass.

| Seed | File | sha256 before = after | Reddened |
|---|---|---|---|
| **S1** `dependency_report` back to a module-only census | `record.py` | `051304ac…b69c0` | `test_check_says_no_device_for_a_camera_nobody_owns` |
| **S2a** the d455 remedy re-worded to the vendor sentence | `clockmap.py` | `e4c070ea…f9b0d` | `test_the_module_missing_paragraph_gives_the_d455_its_own_remedy`, `test_the_remedy_table_groups_devices_and_defaults_to_the_vendor_sentence` |
| **S2b** the adapter remedy re-worded to `Orin only` | `ingest/realsense.py` | `bc86e14b…b9326` | `test_the_adapter_remedy_names_the_extra_and_carries_the_dated_census` |
| **S2c** the preflight remedy re-worded to `Orin only` | `preflight.py` | `8666ec0d…6541d` | `test_the_preflight_realsense_remedy_is_a_pip_line_and_the_vendors_stay_vendors` |
| **S3** drop `settle_s` from the written report | `replay_turn_detection.py` | `81247920…7d35a` | `test_the_replay_report_carries_both_candidate_origins_and_can_tell_them_apart` |
| **S4** remove `planner_model` from `OVERLAY_INTRODUCIBLE_KEYS` | `config.py` | `abe9ee36…41d5` | `test_an_overlay_may_now_introduce_the_planner_section`, `test_the_survey_of_unreachable_config_sections_is_now_empty`, **`test_cap1_admission.py::test_the_wider_survey_finds_no_unreachable_section`**, **`test_prototype_profile.py::test_introducible_keys_are_exactly_the_three_documented_families`** |
| **S5** neuter the spelling guard at the read site | `web_panel.py` | `45d77a38…f72f6` | `test_a_typo_inside_the_planner_section_is_refused_by_name`, `test_prototype_profile.py::test_introducible_keys_…` |

Every arm: RED under the seed, sha256 after = sha256 before (byte-identical
restore), `__pycache__` purged both ways, GREEN again on the same command.

**S4 is the row the pre-registration asked for by name.** Removing the entry
reddens this card's guard *and* CAP-1's updated pin *and* the introducible-keys
pin — three files, one mutation. That is the "the fix reddens the pin too"
signal CAP-1 registered when it declined to patch a frozenset outside its OWNS.

## What changed

```
$ git diff --stat HEAD -- <OWNS>
 scripts/parcel_capture/__init__.py         |  23 +++++-
 scripts/parcel_capture/clockmap.py         |  73 +++++++++++++++++-
 scripts/parcel_capture/ingest/realsense.py |  36 ++++++++-
 scripts/parcel_capture/preflight.py        |  17 ++++-
 scripts/parcel_capture/record.py           | 112 ++++++++++++++++++++++++---
 scrum/20260822/task_25/SESSION.md          |  49 ++++++++++--
 src/parcel_robot/config.py                 |  22 ++++++      (R9, one marked region)
 src/parcel_robot/web_panel.py              |  71 ++++++++++++++++-  (R9, one marked region)
 tests/test_cap1_admission.py               |  41 ++++++----   (R9, CAP-1's pin)
 tests/test_capture_ingest.py               |  24 +++++-       (remedy pins)
 tools/replay_turn_detection.py             | 119 +++++++++++++++++++++++++++--
 11 files changed, 531 insertions(+), 56 deletions(-)

$ git diff --stat HEAD -- tests/test_prototype_profile.py   # SHARED with ROAM-2
 tests/test_prototype_profile.py | 35 +++++++++++++++++++++++++++++++++++
   of which 30 lines are this card's TWO marked `CARD TRUTH-1 (task_32)` regions
   (:334-344 and :374-391); the remaining 5 (`"coverage"` in ROAM_CONFIG_KEYS)
   are ROAM-2's and were not touched.
```

New files: `tests/test_truth1_texts.py` (718 lines, 15 tests),
`scrum/20260822/task_32/DESIGN.md` (145), `PREREGISTRATION.md` (74).

**Seams added, by symbol** — `clockmap.MODULE_MISSING_REMEDIES` /
`DEFAULT_MODULE_MISSING_REMEDY` / `module_missing_remedies()`;
`record.device_presence()`; `replay_turn_detection.UtteranceResult.wall_offset_ms`
/ `.wall_elapsed_ms` / `.wall_minus_audio_ms` / `.commits_wall_relative` /
`.commit_latency_wall_ms` and `REPORT_SCHEMA` v1→v2;
`config.OVERLAY_INTRODUCIBLE_KEYS += {"planner_model"}`;
`web_panel._PLANNER_MODEL_KEYS` / `_check_planner_model_section()`.
`probe_availability`, `PROBE_REQUIREMENTS`, `ingest/base.py`, `pyproject.toml`,
`lane.py` and the array's control path are byte-identical to HEAD — this card
never opened them.

## Gates

Every pytest invocation went through `~/.cache/parcel-guard/pytest_guard.sh
--label truth1`, `TMPDIR` unset, `.parcel/bin/python`. No `-n auto`, no
`ci_gate.py` tier, no background pytest, no `-n` above the wrapper's cap. The
suite-scale runs, with wall clock, for auditing against `guard.log`:

| # | command (all prefixed by the wrapper) | wall | result |
|---|---|---|---|
| 1 | `pytest tests/test_truth1_texts.py -q -p no:randomly` | 25.4 s (22 s waiting on the flock) | 14 passed, 1 failed — my wrong guess at `LlamaCppProvider`'s module |
| 2 | same, after the fix | 3.0 s | **15 passed** |
| 3 | `pytest tests/test_truth1_texts.py tests/test_cap1_admission.py` in the scratch clone | 5 m 16 s (5 m on the flock) | 39 passed, 11 errors — **clone finding, see below** |
| 4 | `bash ~/.cache/parcel-truth1/seeds.sh` (S1–S5, seven arms) | 14.9 s | **0 seed failures** |
| 5 | the pre-registered gate list | 10.2 s | **389 passed** |
| 6 | the pre-registered gate list, re-run after the ruff fix | 9.9 s | **389 passed** |
| 7 | `pytest tests/test_truth1_texts.py tests/test_cap1_admission.py tests/test_prototype_profile.py` (final state) | 5.0 s | **81 passed** |

```
$ .parcel/bin/python -m pytest tests/test_truth1_texts.py tests/test_clockmap.py \
    tests/test_capture_ingest.py tests/test_turn1_endpointing.py \
    tests/test_cap1_admission.py tests/test_prototype_profile.py tests/test_web_panel.py \
    -q -p no:randomly
389 passed, 1 warning in 9.90s
```

Ruff, on every file this card touched (`__init__.py`, `clockmap.py`,
`preflight.py`, `record.py`, `ingest/realsense.py`, `replay_turn_detection.py`,
`config.py`, `web_panel.py`, `test_truth1_texts.py`, `test_capture_ingest.py`,
`test_cap1_admission.py`, `test_prototype_profile.py`): **All checks passed**.
Tree-wide `ruff check .` reports 13, **none of them in a file this card
touched** — 11 under `src/parcel_robot/{detection_adapter,camera_channel}/`
(another card) and 1 in `tests/test_xd1_repo_write_guard.py` (XD-1). The three
`PLW1510` findings this card DID introduce (`subprocess.run` without an explicit
`check`) were fixed at source with `check=False` and a comment saying why —
`--check` exits 3 on this box by design, so a raising call would fail the very
row it measures. No `noqa`, nothing re-pinned, nothing added to
`scripts/ci_ruff_baseline.json`.

**Process hygiene.** No sim was started; no process was signalled; the owner's
`/tmp/parcel_sim.sock` and `:8765` were never touched (both absent all session);
`parcel_memory.sqlite3` was never opened. `tools/list_parcel_procs.py` clean
before this report.

## What this does not prove

* **No attached camera, anywhere.** Every `device_report()` ATTACHED arm, a
  non-empty `rs.context().query_devices()`, and any frame past
  `pipeline.start()` are unmeasured. R4 proves the CLI reports `NO DEVICE`
  honestly when there is none; it cannot prove it reports `READY` correctly when
  there is one.
* **No Orin, no Go2, no Mid-360, no head LiDAR.** Every aarch64 claim in every
  remedy this card wrote is a *file exists on PyPI* fact or a *vendor document
  says* fact, never a *ran on the unit* fact, and each says so in the operator
  text itself. The JetPack the EDU dock actually boots is UNCONFIRMED and the
  remedies now say that instead of assuming 6.2.x.
* **No hosted `--replay` number.** R6 proves the report can DISCRIMINATE the two
  candidate origins and that its arithmetic reconciles. Which origin the real
  provider uses is still unknown — that is the first live run's answer, and the
  point of the card is that one run will now be enough.
* **No through-air AIR-1 number.** R8 changed words in a runbook. It measured no
  echo attenuation, no barge-in, nothing acoustic. The XVF3800 was never opened,
  played through, or written to.
* **R9's guard is bypassable by construction.** `check_overlay_keys` exempts the
  whole `planner_model` subtree, so `web_panel._check_planner_model_section` is
  the only thing between a typo and a silent default. Anyone who constructs
  `RobotRuntime` directly instead of going through `build_runtime` merges the
  typo silently. That is the same trade every introducible family in this tree
  makes; it is stated here so it is a known cost and not a surprise.
* **The clone finding (run 3) — CORRECTED in the correction pass.** As first
  written this said a scratch copy "does NOT isolate `src/`". That was too
  strong and the correction pass disproved it. What is true: `cd <clone> &&
  pytest` alone does NOT isolate `src/` — `.parcel`'s editable install resolves
  `parcel_robot` to the real working tree, so a seed applied to the clone's
  `config.py` would have been a **no-op that looked like a passing seed**. What
  works, and what S6/S7 used, is an explicit
  `PYTHONPATH=<scratch>/src:<scratch>` with `parcel_robot.__file__` PRINTED and
  asserted inside the scratch before any mutation:

  ```
  parcel_robot          : ~/.cache/parcel-truth1/scratch2/src/parcel_robot/__init__.py
  parcel_robot.web_panel: ~/.cache/parcel-truth1/scratch2/src/parcel_robot/web_panel.py
  preflight             : ~/.cache/parcel-truth1/scratch2/scripts/parcel_capture/preflight.py
  ```

  `seeds2.sh` refuses to run if that assertion fails. S1–S5 were run in the
  working tree inside the guard's flock with byte-identical restore; S6–S7 on
  the isolated scratch. **The lesson stands in its corrected form: never trust a
  clone-based seed without printing the module's `__file__`.**

## Deviations

1. **R3 is a MISS as registered: `Orin` = 1, pass condition 0.** Declared in
   advance in `DESIGN.md` §(g)1. The row was written at 15:27 on 08-22, when the
   Orin was believed irrelevant to a D455 remedy. At 16:00 the owner named the
   Go2 EDU+ with its onboard Orin NX as the real deploy host. A realsense remedy
   that now refuses to name the Orin is the SAME defect pointing the other way:
   the operator standing at the dog is told nothing about the dog. The remedy
   names it exactly once, as the SECOND host, and the number is pinned in
   `test_the_preflight_realsense_remedy_is_a_pip_line_and_the_vendors_stay_vendors`
   so that reverting to 0 is a deliberate, reddening decision. **The verifier
   decides; this is reported as a miss, not as a pass.**
2. **R9's constant is in `config.py`, not `runtime.py`.** The re-dispatch
   EXTRAS guessed `runtime.py`; the grep decided. `runtime.py` only *documents*
   the frozenset (`:5120`, `:11809`) and reads nothing from it, so this card
   never opened `runtime.py` and never took `lock-runtime.py`. Recorded as a
   deviation because the brief named a file this card did not touch.
3. **Six files outside the README's OWNS were edited, all pre-registered.**
   `src/parcel_robot/config.py` and `src/parcel_robot/web_panel.py` (R9's two
   halves), `tests/test_cap1_admission.py` (CAP-1's pin, which the fix HAD to
   redden and which is updated in the same change), and
   `tests/test_prototype_profile.py` (the introducible-keys pin, shared with
   ROAM-2). The last was edited in ONE pass inside two marked `CARD TRUTH-1
   (task_32)` regions. `tests/test_capture_ingest.py` (+24) is a fifth: the D455
   remedy change forced two blanket `"Orin" in remedy` assertions to become
   per-module. A pin the text change forced, not new scope. **Corrected count
   (verifier NOTE N1):** the sixth is `scripts/parcel_capture/__init__.py`,
   which is not in the README's OWNS list either and is registered by R5. Six,
   all registered, none HOLD.
4. **The remedy texts were re-worded this session against `research.json`.**
   The fourth executor's drafts asserted "JetPack 6.2.x CPython 3.10" as settled
   and said an aarch64 source build was needed only on 3.11/3.13/3.14. Both are
   wrong given the forwarded constraint: the EDU dock may ship **JetPack 5.1.1
   (Ubuntu 20.04, CPython 3.8)** — for which this release publishes **no aarch64
   wheel at all** — or run 6.2.1. All five sites now state the ambiguity and mark
   it UNCONFIRMED. This is a correction to a draft this session inherited, made
   under the card's own citation rule, and it is the difference between a remedy
   that works on the dock and one that fails on it.
5. **Two retractions were re-worded because they quoted the claim they killed.**
   `__init__.py`'s aarch64 retraction (caught by the fourth executor) and the
   replay tool's `lane` retraction (caught this session: `cannot reach ``lane``
   even by accident` was still present once, so R7's own grep would have counted
   1). Both now describe the claim instead of reproducing it. The rule is stated
   in `tests/test_truth1_texts.py`'s header so the next stale-string row inherits
   it.

## Owner-gated rows — the exact commands, never claimed

Nothing in R1–R9 is owner-gated; all nine were measured. These are the rows the
card explicitly cannot reach, with the command that would close each:

```bash
# The attached-camera arm. Needs a D455 on a USB3 (blue) port, direct, no hub.
ls /dev/video* && lsusb | grep -i intel
.parcel/bin/python -m scripts.parcel_capture.record --check
#   expected once attached: the six d455.* rows read
#   READY (installed: pyrealsense2; device attached)

# The hosted replay — the row R6 built the report FOR. A few cents.
.parcel/bin/python tools/replay_turn_detection.py --plan --out <corpus>
<corpus>/record.sh                                    # ~10 minutes of the owner
.parcel/bin/python tools/replay_turn_detection.py --replay --live \
    --recording <corpus> --arm server_vad_default --settle-s 0.15 --out <results>
#   then read `wall_minus_audio_ms_max` and compare `commit_latency_ms` with
#   `commit_latency_wall_ms`: whichever origin makes the per-file latencies
#   AGREE across files is the one the provider indexes.

# The AIR-1 through-air rows. Needs the array in a room, a speaker, and 1 m.
#   `scrum/20260822/task_25/SESSION.md` §5A — prerequisites now stated once.
```

## Handoffs

1. **`preflight.L4T_TO_JETPACK` has no JetPack 5 row — a HANDOFF, not an edit.**
   `scripts/parcel_capture/preflight.py:271-276` maps only `36.3.0` / `36.4.0` /
   `36.4.3` / `36.4.4` (JetPack 6.0–6.2.1). Multiple reseller and NVIDIA-forum
   reports have Go2 EDU docks shipping **JetPack 5.1.1**, which is L4T **35.x**
   — absent from the table, so the JetPack observation comes back ABSENT and the
   preflight fails closed on a dock that is working correctly. Deliberately NOT
   edited: the table is a DECLARED falsifiable artifact whose own comment says
   guessing a JetPack from an unknown L4T is the permissive default board rule 3
   forbids, and adding a row is a decision with a reviewer, not a text fix.
   Source: `~/.cache/parcel-fable-design/research.json`, `hardware` lens,
   confidence `documented`.
2. **`onnxruntime-gpu` cannot be installed on the Orin at the pinned version.**
   `pyproject.toml:58` pins `onnxruntime-gpu[cuda,cudnn]>=1.28,<2`; there is no
   public aarch64 CUDA wheel satisfying `>=1.28` (known Jetson prebuilts stop at
   1.23.0/cp310). `pyproject.toml` is MUST-NOT-TOUCH for this card. Whoever owns
   the deploy story needs a Jetson-specific extra or a source build.
   Source: same file, confidence `measured`.
3. **The Mid-360 has no row in this tree's channel matrix, and must not be given
   the `l2` one.** `hw-facts/mid360.txt` puts the Mid-360 on **Livox SDK2 over
   100BASE-TX Ethernet (UDP)**; `hw-facts/l2.txt` puts the add-on Unitree L2 on
   `unilidar_sdk2` over **ENET UDP or TTL UART**. Different vendor, different
   protocol, different transport, and on the EDU+ the Mid-360 lands on the
   Jetson dock's M8 plug rather than the head board. Reusing the `l2` row would
   make `preflight` and `record --check` lie about which SDK is missing — which
   is this card's entire subject. A wave-3 decision; no code written here.
4. **FIVE texts outside this card's registered remedy sites still state
   "JetPack 6.2.x" as settled** (verifier F6; the first draft said "two" and gave
   no `file:line`). `grep -rn 'JetPack 6\.2' scripts/parcel_capture/`:

   | file:line | text |
   |---|---|
   | `record.py:1397` | `"rclpy": "Orin only: source /opt/ros/humble/setup.bash (JetPack 6.2.x ships it)"` |
   | `record.py:1781` | the `--check` refusal header: `"(JetPack 6.2.x / Humble / Python 3.10). Nothing was installed."` |
   | `scripts/parcel_capture/__init__.py:8-9` | `"(JetPack 6.2.x)"` — **seven lines above this card's own R5 hunk, in a file it edited** |
   | `ingest/dds.py:731` | `"(JetPack 6.2.x ships Humble). Never install a ROS stack into .parcel/."` |
   | `rosbag2.py:612` | `"and JetPack 6.2 on the Orin is Humble."` |

   `preflight.py:2746` also matches the grep but is about ADR 0001's golden-image
   pin and is true as written; `preflight.py:280-281` are `L4T_TO_JETPACK` rows,
   which are handoff 1. All five above are true if the dock is flashed to
   JetPack 6 and false if it ships 5.1.1. Two of them (`record.py:1397`,
   `dds.py:731`) print in the SAME `record --check` output as this card's
   corrected remedies — measured after the correction pass:

   ```
   34:  rclpy: Orin only: source /opt/ros/humble/setup.bash (JetPack 6.2.x ships it)
   43:    remedy: rclpy: Orin only: source /opt/ros/humble/setup.bash and the
           unitree_ros2 overlay (JetPack 6.2.x ships Humble). …
   ```

   Not edited: they are outside R1–R9, and changing five unmeasured strings
   inside a card whose subject is measured claims would be exactly the habit this
   card exists to break. `clockmap._ORIN_ROS2_REMEDY` now tells the operator to
   `ls /opt/ros/` rather than trust any of these hints, including its own.

6. **`record --check` and `preflight` still call the XVF3800 "awaiting
   hardware" — the one device that IS on hand** (verifier NOTE N3):
   `scripts/parcel_capture/ingest/__init__.py:102`
   ("the XVF3800 mic array is AWAITING_HARDWARE (BLOCKED.md B3)"),
   `preflight.py:2358` ("the XVF3800 is in the post (BLOCKED.md B3); expect
   ABSENT today"), `preflight.py:3835`. The array has been on the desk since
   task_25 measured its firmware as `bcdDevice 0206`. Same class of stale
   operator text as SDK-REM-1, outside R1–R9, and it needs the BLOCKED.md entry
   retired with it rather than a one-line string edit.
5. **The head LiDAR's model is unknown until the box.** `hw-facts/go2.txt`
   documents the standard head unit as the **4D LiDAR L1 (360°×90°)** while
   Unitree's current comparison table lists the **L2 (360°×96°)** on every SKU.
   Either way software reaches it only through the on-robot DDS services
   (`rt/utlidar/*`, head board `192.168.123.161`) — there is no documented direct
   Ethernet or UART path. This card writes no code against it.

## Resumed from

This card has now had **five** executors. Every one of the first four died in a
kernel OOM kill caused by `pytest -n auto` (192 workers on this host) running in
some session — never by this card's own work. Nothing was ever reverted.

* **Executor 1 (15:2x–15:58, 08-22).** Wrote `PREREGISTRATION.md` (15:27, before
  any acceptance number existed) and the first pass of the product texts:
  `scripts/parcel_capture/{__init__,clockmap,preflight,record}.py`,
  `ingest/realsense.py`, `tools/replay_turn_detection.py` (+117),
  `task_25/SESSION.md` (+23), `tests/test_capture_ingest.py` (+24), and the
  draft texts under `~/.cache/parcel-truth1/new*.txt`. Died ~15:36/16:23.
* **Executor 2 (17:55–18:0x, 08-22).** Wrote `DESIGN.md` and the status-doc
  header stub with the sha256 pin. Died in the 18:02 crash.
* **Executor 3 (05:3x, 08-23).** Landed R9 as ONE marked `CARD TRUTH-1` region
  in `src/parcel_robot/config.py` — **not** `runtime.py` as the dispatch EXTRAS
  guessed — plus `web_panel.py`'s read-site guard, CAP-1's updated pin, and the
  two `test_prototype_profile.py` regions.
* **Executor 4 (05:37–05:38:42, 08-23).** Captured the R1 before/after
  transcripts and started the PyPI wheel census. OOM-killed at 05:38:42 mid-census.
* **Executor 5 (this session, 06:2x–, 08-23).** KEPT everything above: every
  product edit, the DESIGN, the PREREGISTRATION (sha re-verified), R9's four
  files. CHANGED: the JetPack over-claims in all five remedy sites (deviation 4);
  the replay tool's `lane` retraction, which still quoted the claim it retracted
  and would have made R7 measure 1 (deviation 5). ADDED: the census, finished and
  re-run whole (13 files, unchanged); `tests/test_truth1_texts.py` (718 lines, 15
  tests) — the pre-registered file that did not exist; every acceptance
  measurement R1–R9; all five seeds; the ruff fixes; this document. DISCARDED:
  nothing.

## Verdict

**8 of 9 rows MET. R3 is a MISS as registered (1 vs 0) and is reported as one,
with the reason and the number.** All five seeds RED on the product and restored
byte-identically. The card's own drafts contained two instances of the defect it
exists to prevent — a retraction that quotes the stale claim — and both were
caught by measuring the row rather than reading the paragraph. That is the
strongest evidence here that the guards are guards.

---

# Correction pass — 2026-08-23, after the verifier's ACCEPT-WITH-NOTES

Verdict record: `~/.cache/parcel-verify/truth1/VERDICT.md` (6 FIX, 0 HOLD).
`PREREGISTRATION.md` unchanged, sha256 still
`b5c8dd59c6727e90715def77762ef8ca276a92ec71b068caf116d16a3217fae7`. No
pre-registered threshold moved; **R3 stays a MISS (1 vs 0)**.

| FIX | What it was | What was done | Guard |
|---|---|---|---|
| **F1** | `preflight.py:3259-3267` `probe_d455` — a SECOND D455 remedy on the preflight product path still said "install pyrealsense2 in the Orin capture environment" on a box where it IS installed | `_unavailable_device_reader` gained an optional `remedy_when_present` (defaults to `remedy`, so go2/l2/uwb are behaviourally unchanged); `probe_d455` now carries **two** remedies, one per branch | `test_the_preflight_identity_probe_has_its_own_true_remedy_per_branch` · seed **S6** |
| **F2** | the R9 typo guard was pinned as a FUNCTION; deleting the call from `build_runtime` reddened nothing | two `build_runtime`-level tests on a REAL profile overlay (no product symbol monkeypatched) | `test_build_runtime_refuses_a_misspelled_planner_key_from_a_real_profile`, `test_build_runtime_accepts_the_same_profile_spelled_correctly` · seed **S7** |
| **F3** | `ingest/realsense.py:271-272` — the comment reproduced BOTH stale strings verbatim, defeating the file-level grep | rewritten to DESCRIBE the claims | `grep -c` both → **0** |
| **F4** | `preflight.py:68` docstring still asserted "there is no aarch64 build" | replaced with the measured census + the narrow true statement | `grep -c` → **0** |
| **F5** | `clockmap.py:2601-2602` "a JetPack 6.x dock ships nothing until you add it" — unsupported, and contradicted `record.py:1397` / `dds.py:731` in the same output | reworded: which ROS the dock has is UNCONFIRMED, the 5.1.1/Foxy vs 6.2.1/Humble pairings are named, and the operator is told to `ls /opt/ros/` "before trusting any of those hints, **including this one**" | R1 re-measured |
| **F6** | §Handoffs 4 said "two texts", no `file:line` | rewritten as a five-row `file:line` table + the two that print in the same `--check` output; NOTE **N3** (XVF3800 "awaiting hardware") added as handoff 6 | — |

Accepted NOTEs: **N1** — §Deviations 3 now says **six** files outside the
README's OWNS (the sixth is `scripts/parcel_capture/__init__.py`, registered by
R5), all registered, none HOLD. **N2** — the `build_runtime` hunk now sits
inside a fenced `---- CARD TRUTH-1 … END ----` region (no concurrent writer on
`web_panel.py`); the comment inside it says why the CALL, not the function, is
the guard. **N5/N7** left as measured. The §"What this does not prove"
clone-isolation finding was **corrected**: it was cwd-only, not a property of
clones — see below.

## F1 — the rendered preflight line, before and after

```
$ .parcel/bin/python -m scripts.parcel_capture.preflight --window 0.2

BEFORE (pristine copy at ~/.cache/parcel-truth1/before/)
  d455.firmware_version                 ABSENT
      [absent] d455: this build ships no live identity reader
      remedy: install pyrealsense2 in the Orin capture environment; check the D455
              is on a USB3 port.                                  ← false twice over
  [exit=1]

AFTER (module-present branch — the one THIS box takes)
  d455.firmware_version                 ABSENT
      [absent] d455: this build ships no live identity reader
      remedy: pyrealsense2 is importable here, so this is NOT a missing wheel: this
              build ships no live D455 identity reader, and the firmware/serial come
              from PS-D against the attached unit. Plug the D455 into a USB 3 (BLUE)
              port, direct, no hub, confirm it enumerates (`ls /dev/video*`,
              `lsusb | grep -i intel`), then read the identity there. Do not pip
              install anything for this row.
  [exit=1]                                                        ← unchanged

AFTER (module-missing branch — pyrealsense2 hidden, a bare host)
  [dependency_missing] d455: none of pyrealsense2 importable in …/.parcel/bin/python
      remedy: pyrealsense2 is an ordinary pip wheel, not a vendor SDK build. On this
              dev box run `.parcel/bin/pip install -e '.[camera-realsense]'` (already
              installed here: 2.58.3.10794 cp314, measured 2026-08-22). On the Orin NX
              run `pip install pyrealsense2` in the DEPLOY venv, never into .parcel/,
              IF the dock boots a JetPack 6.x (CPython 3.10) — that release publishes
              aarch64 wheels for cp39/cp310/cp312 ONLY, so a JetPack 5.1.1 dock
              (CPython 3.8) is a source build. Which JetPack the unit ships with is
              UNCONFIRMED.
```

`grep -c "install pyrealsense2 in the Orin capture environment"` over the whole
rendered report: **0**. Exit code unchanged (1 before and after).

## Rows re-measured after the corrections

```
R1  d455 line: pip line present; `Orin inside the ROS 2 Humble environment` on d455 = 0,
    on `go2, l2` = 1; exit 2, REFUSED, permanently unrecoverable   → MET
R2  pip line True | 'Orin only' 0 | 'no wheel exists for 3.11+' 0 | dated True   → MET
R3  _TRANSPORT_MODULES["realsense"] 'Orin' = 1 (registered 0); pip line True;
    dds/vendor_video/vendor_uwb/unilidar_sdk2 = 2/1/1/1 (each >=1)  → MISS (declared, unchanged)
R4  reader deps present 0 | NO DEVICE (installed: pyrealsense2) 7 | six d455 rows | exit 3  → MET
R5  __init__.py 'there is no aarch64 build' 0; census present       → MET
F4  preflight.py 'there is no aarch64 build' 0                      → closed
```

## Seeds S6 and S7 — on an ISOLATED scratch, provenance asserted first

`~/.cache/parcel-truth1/seeds2.sh`, run once under the wrapper; transcript
`evidence/seeds2.txt`; wall clock **14.0 s**. `PYTHONPATH=<scratch>/src:<scratch>`,
and the script **refuses to seed** unless `__file__` for both modules is inside
the scratch:

```
web_panel : ~/.cache/parcel-truth1/scratch2/src/parcel_robot/web_panel.py
preflight : ~/.cache/parcel-truth1/scratch2/scripts/parcel_capture/preflight.py
baseline  : 18 passed
```

| Seed | Mutation | RED | Restore | GREEN |
|---|---|---|---|---|
| **S6** (F1) | `probe_d455`'s two remedies → the old single stale sentence (`ab1ef530…` → `e82a10d0…`) | `test_the_preflight_identity_probe_has_its_own_true_remedy_per_branch` **1 failed** | sha-identical | 1 passed |
| **S7** (F2) | remove the `_check_planner_model_section(...)` **CALL** from `build_runtime`, body intact (`2e9e0182…` → `a8a6fc90…`) | `test_build_runtime_refuses_a_misspelled_planner_key_from_a_real_profile` **1 failed** (2 passed) | sha-identical | 3 passed |

**S7 is the verifier's own S5b, now reddening.** That mutation produced 6/6
passing before this pass; it is the difference between a guard that exists and a
guard that is wired. `seed failures: 0`, no `.bak` left behind, and the working
tree's `web_panel.py` / `preflight.py` shas are unchanged by the scratch run.

## Gates after the correction pass

Pre-flight, checked before the suite-scale run: `free -g` available **233**
(≥ 120); pytest **root** count **0** (≤ 1 — counted by resolving each
`-m pytest` match's `comm` and `ppid`, so bash wrappers and xdist workers are
not miscounted).

| # | command (all under the wrapper, `--label truth1`) | wall | result |
|---|---|---|---|
| 8 | `pytest tests/test_truth1_texts.py` (F2 added) | 2.7 s | 16 passed, 1 failed — my wrong attribute (`runtime.planner_model` → `runtime.agent.planner_model`) |
| 9 | same, fixed | 2.7 s | 17 passed |
| 10 | same, F1 pin added | 2.7 s | 18 passed |
| 11 | `bash ~/.cache/parcel-truth1/seeds2.sh` (S6, S7) | 14.0 s | **0 seed failures** |
| 12 | the pre-registered gate list | 10.1 s | **392 passed** (was 389; +3 new tests) |

```
$ .parcel/bin/python -m pytest tests/test_truth1_texts.py tests/test_clockmap.py \
    tests/test_capture_ingest.py tests/test_turn1_endpointing.py \
    tests/test_cap1_admission.py tests/test_prototype_profile.py tests/test_web_panel.py \
    -q -p no:randomly
392 passed, 1 warning in 10.10s
```

`ruff check` on all twelve touched files: **All checks passed**. Tree-wide
**12**, every one under `src/parcel_robot/{detection_adapter,camera_channel}/`
(another card) — the `tests/test_xd1_repo_write_guard.py` finding the verifier
saw is gone, fixed by XD-1 meanwhile. `scripts/ci_ruff_baseline.json` untouched;
**0** `noqa` added anywhere in this card's hunks.

## Deviation added by the correction pass

7. **`_unavailable_device_reader` gained a parameter (F1).** The card's OWNS is
   "preflight.py remedies", and F1's site needed TWO remedies where the shared
   refusal factory offered one. `remedy_when_present` defaults to `None` →
   falls back to `remedy`, so the go2, l2 and uwb readers are unchanged in
   behaviour and in output. This is a signature change to shared machinery
   rather than a pure string edit, and it is recorded as such: it is the
   smallest change that makes the module-present branch stop printing the
   module-missing remedy, which is SDK-REM-1 itself.
