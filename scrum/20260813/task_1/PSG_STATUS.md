# PS-G — the ingest layer and the rosbag2 primary path

**Card:** PS-G, corrective tranche **PS-2** · **Date:** 2026-08-13
**Driver:** [RISK_ASSESSMENT.md](RISK_ASSESSMENT.md) D-1 (no card owns the ingest
layer) and D-2 (the bag format is unreadable downstream)
**OWNS:** `scripts/parcel_capture/ingest/` (new) · `scripts/parcel_capture/rosbag2.py`
(new) · `scripts/parcel_capture/sidecar.py` (amended) · `tests/test_capture_ingest.py` ·
`tests/test_rosbag2_sidecar.py`

---

## Both defects re-verified at source before any code was written

| Defect | Where | What it said |
|---|---|---|
| **D-1** | `record.py:1488` `resolve_live_source()` | raised `LiveSourceUnavailableError` for **every** transport: *"no live backend ships in card PS-B"* |
| **D-1** | `preflight.py:2407,3283` | `reader_factory: ChannelReaderFactory = unavailable_reader_factory` — the default reader refuses on every channel |
| **D-2** | `record.py:152-158` | `MCAP_PROFILE = "parcel-capture"`, `MESSAGE_ENCODING = "parcel.capture.envelope.v1+raw"`, `SCHEMA_ENCODING = "parcel.capture.channel.v1+json"` |
| **D-2** | `record.py:794` (`_decode_channel`) | `if encoding != MESSAGE_ENCODING: raise McapReadError(...)` — the Parcel reader refuses any non-Parcel encoding, so `McapScan` cannot see a rosbag2 file at all |

Both confirmed. The card's diagnosis is exact.

---

## What I built

### (a) `ros2 bag record -s mcap` is now a first-class, executable plan

`scripts/parcel_capture/rosbag2.py` (1,547 lines). It contains **no recorder** —
`ros2 bag record` is the recorder, and a second implementation of it would be a
second thing to be wrong. What it contains:

| Surface | What it is for |
|---|---|
| `record_command(plan)` | The exact argv. Explicit `--topics`, **never** `-a`: `-a` records whatever happens to be on the graph at start, which is both more than the disk budget and less than the list — a topic with no publisher yet is simply absent, and its absence looks like a decision nobody made |
| `RECORDED_TOPICS` (25) | Derived from PS-H's corrected matrix by calling `subscribe_name(id, WireNaming.ROS2)`, not from a second hand-written list. 15 `ROBOT_NATIVE` + 8 `DRIVER_NODE` + 2 `RECORDER_EVENT` |
| `TopicSource` | `ROBOT_NATIVE` / `DRIVER_NODE` / `RECORDER_EVENT`. Three different failure modes and three different remedies: the dog is off, we did not launch the driver, or the recorder does not publish that event. Mixing them is how a session records fifteen topics and misses the camera |
| `storage_config_yaml()` + `WriterProfile` | MCAP writer options. `CRASH_SAFE` (default) sets `noChunking: true`, `compression: ""`; `INDEXED` uses 4 MiB uncompressed chunks |
| `read_rosbag2_mcap()` | A **stdlib-only** rosbag2 MCAP reader: per-topic counts, per-topic bytes, log-time span, channel/schema table, and the same three-way framing verdict (CLEAN / TRUNCATED / CORRUPT) the Parcel reader uses |
| `parse_bag_info()` / `run_bag_info()` | `ros2 bag info` as data, with a refusal instead of an empty map when the output is not understood |
| `discover_bag()` | rosbag2 output is a **directory** of split files; the glob is cross-checked against `metadata.yaml` by strict line scan and a disagreement is a finding |
| `write_fixture_bag()` | rosbag2-shaped bytes for tests and tonight's dry run. Stamps `library = "parcel-capture rosbag2 FIXTURE writer (not a recorder)"` **inside the file** so a fixture can never be mistaken for a recording |

**Why `noChunking` is the default, argued rather than asserted:** a chunk buffers
messages *inside* the writer, which is exactly the state a SIGKILL or a flat
battery destroys — the same argument `record.py`'s own module docstring makes for
the Parcel writer. Compression is off in **both** profiles: it costs CPU on an
Orin already carrying the D455, and a compressed chunk is uncountable by any
stdlib tool on a night with no `zstandard` installed. That is not theoretical —
measured in C4 below: an uncompressed bag is walked message-by-message here, a
`zstd` one falls back to the writer's own `Statistics` claim and the sidecar
records `count_basis = "unavailable_compressed"`.

### (b) `parcel-capture` is demoted, in the artefact and not only in a plan

`sidecar.py` gained `BagFormat` (`parcel_capture_mcap` / `rosbag2_mcap`) and
`RecorderRole` (`primary` / `secondary`), stamped into every sidecar it builds,
plus `build_rosbag2_sidecar()` / `verify_rosbag2_sidecar()` / `finalize_rosbag2()`.
Every Parcel-native sidecar now carries this line in `does_not_prove`:

> This is the SECONDARY copy. The parcel-capture MCAP format is readable only by
> this repository — no downstream SLAM or calibration tool can open it — so it
> must never be the sole copy of a channel. The primary recording is
> `ros2 bag record -s mcap`.

**The Parcel-format path was not weakened to make this work.** `record.py:794`
still refuses a non-Parcel encoding, and `read_mcap()` still classifies a rosbag2
file as CORRUPT with `message_encoding` in the detail (measured, C7). The rosbag2
path is a **second reader**, in a second module, and `verify_sidecar()` now routes
a rosbag2 manifest to `verify_rosbag2_sidecar()` rather than digesting one split
file and calling the take bound.

**Two things are structurally weaker on the primary path, and the sidecar says
both out loud rather than papering over them:**

1. **rosbag2 mints no per-channel sequence number.** PS-A's counter is minted at
   receipt by *our* recorder. So the interior-hole signal — the only proof of an
   individual dropped message, and the thing that distinguishes a drop from a
   truncation — **does not exist in a rosbag2 bag**. What remains is a count
   against an expected rate, which catches a sustained deficit and cannot
   attribute a single lost message. Every channel record carries
   `sequence.status = "unavailable"` with that reason in it. This is the concrete
   reason the Parcel secondary path keeps its value, and the reason
   `/events/messages_lost` is on the record list.
2. **Counts may be the writer's claim rather than a walk.** `count_basis` is
   recorded per file and per channel: `walked_messages`, `mcap_statistics`,
   `unavailable_compressed`, or `ros2_bag_info`. When `ros2 bag info` and the
   stdlib walk disagree, the sidecar quotes the tool **and** records the
   disagreement (measured, C6).

### (c) The ingest subpackage: four adapters behind one interface

`scripts/parcel_capture/ingest/` — 2,145 lines across six modules.

| Adapter | Transport | Channels | Dependency | Here |
|---|---|---|---|---|
| `DdsIngest` | DDS via **`rclpy` only** | 15 | `rclpy` | refuses |
| `RealSenseIngest` | RealSense USB3 | 6 | `pyrealsense2` | refuses |
| `L2Ingest` | `unilidar_sdk2` | 2 | `unilidar_sdk2` | refuses |
| `FakeIngest` | any row, synthetically | 28 | none | **runs** |

**Structurally subscribe-only, by four independent mechanisms:**

1. **The vendor SDK is never imported.** `DdsIngest` uses `rclpy`, not
   `unitree_sdk2py` — the vendor package ships the motion clients (`SportClient`,
   `MotionSwitcherClient`) in the same tree as its subscriber, and importing it to
   read a sensor puts a command surface one attribute away. `unitree_ros2` carries
   every topic we need, so this costs nothing.
2. **`ReadOnlyHandle`.** Every vendor object an adapter holds is behind a fixed
   attribute allowlist whose `__getattr__` refuses anything else — so
   `getattr(handle, "create_" + "publisher")` **raises**, which an AST scan alone
   would never catch. The `rclpy` allowlist is three names; the L2 allowlist
   contains no mode-changing name.
3. **`NEVER_ALLOWED`.** A denylist checked *against the allowlist at construction*,
   so a later editor who "just needs" `startLidar` cannot get it by widening the
   allowlist. The construction refuses.
4. **The AST pin plus a dynamic-reach census.** No symbol or import in the package
   names a publisher/command surface, and **every** `getattr`/`setattr`/`eval`
   call site in the package is enumerated by the test — exactly two, both vetted.
   A third anywhere fails the pin.

The one place a raw `rclpy` node exists is `_SubscribeOnlySession` (40 lines,
public surface `{subscribe, spin_once, close, handle}`, node name-mangled and
never returned) — because `rclpy.spin_once` takes the node as an argument rather
than offering a method on it. That residual is stated in `does_not_prove`.

**The L2 does not get turned on by us.** `unilidar_sdk2` exposes `startLidar` /
`stopLidar` / `setLidarWorkMode`, and `utlidar/switch` is the one topic the vendor
stack treats as an *input*. `L2Ingest` attaches to a device that is already
streaming and refuses with the command to run in another process. That is the
board's first rule applied to the only sensor where "read-only" and "usable" could
plausibly have been traded off.

**Decoders carry every message-shape correction from RISK_ASSESSMENT.md**, and
they are the part that is genuinely testable here (they are pure functions over
duck-typed messages): 12 actuated joints not 20 with the padding indices reported
as a *finding*; both `foot_force[4]` and `foot_force_est[4]`; `BmsState` has no
voltage so pack voltage is `power_v` or `sum(cell_vol)/1000` **with the
millivolt→volt conversion done here** because PS-J's `PowerSample` is documented
in volts and refuses to guess units; `range_obstacle[4]`; `power_v`/`power_a`;
`wireless_remote[40]`; `tick` recorded as `tick_ms` beside its modulus and never
as a clock. Every field is read through one tolerant `read_field`, so a
documentation error about *our* unit yields a summary with a named missing field
rather than a crashed probe forty minutes into a battery.

**The fail-closed rule that makes it stick:** `IngestFrame` **refuses** a non-null
`source_timestamp_ns` on any channel whose matrix row does not declare
`SourceClock.DEVICE_TIMESPEC`. `LowState` is `WRAPPING_COUNTER`, so a decoder that
promoted `tick` to nanoseconds cannot construct a frame. All six D455 rows are
`UNVERIFIED` pending the UVC-metadata question, so the RealSense adapter records
the device timestamp **and its domain** in the summary and leaves the anchor null;
flipping the matrix row after the bench check is what turns it on, and no code
here changes.

### (d) The seam is wired, so the defect is closed at its own location

`record.py:resolve_live_source()` now resolves through `ingest.adapter_for()`
(lazy import, no cycle). On this box it still refuses — because `rclpy` genuinely
is absent — but for a different reason than before, and the string *"no live
backend ships in card PS-B"* no longer exists in the tree. A test asserts both.

---

## MEASURED claims

Every row is a command that was run and its output.

### C1 — the ingest census: 23 of 28 channels have a reader, 5 have a stated reason

```
$ .parcel/bin/python -B -c "from scripts.parcel_capture import ingest; print(ingest.dependency_report_text())"
channels in the matrix: 28  served: 23  unserved: 5

dds          15 channel(s)  UNAVAILABLE (missing: rclpy)
    remedy: rclpy: Orin only: source /opt/ros/humble/setup.bash and the unitree_ros2 overlay ...
realsense     6 channel(s)  UNAVAILABLE (missing: pyrealsense2)
    remedy: pyrealsense2: Orin only: pip install pyrealsense2 into the DEPLOY venv on CPython 3.10 or 3.12 ...
l2            2 channel(s)  UNAVAILABLE (missing: unilidar_sdk2)
    remedy: unilidar_sdk2: Orin only: build the vendor unilidar_sdk2 and put its python binding on PYTHONPATH ...

channels with NO ingest adapter (each is a stated gap, not a surprise):
  orin.tegrastats            platform_tool  tegrastats is scraped by PS-D's preflight ...
  gnss.zed_f9p               serial         the ZED-F9P is CONFIRM_ON_HAND ...
  uwb.owner_fob              vendor_uwb     the UWB ranging protocol is undocumented to us ...
  mic.xvf3800                usb_audio      the XVF3800 mic array is AWAITING_HARDWARE (BLOCKED.md B3)
  go2.front_camera_h264      vendor_video   the front camera's H.264 path is RTP over multicast ...
```

No traceback, module named, remedy attached, and every unserved channel carries a
reason rather than being missing.

### C2 — the command line the session runs

```
$ .parcel/bin/python -B -m scripts.parcel_capture.rosbag2 --print-command
ros2 bag record --storage mcap --output /data/parcel/session --node-name parcel_rosbag2_recorder
  --max-cache-size 8388608 --disable-keyboard-controls --max-bag-size 4294967296 --topics
  /utlidar/cloud /utlidar/imu /utlidar/robot_pose /utlidar/voxel_map_compressed /sportmodestate
  /lowstate /lf/lowstate /lf/sportmodestate /wirelesscontroller /frontvideostream
  /utlidar/lidar_state /utlidar/cloud_deskewed /utlidar/robot_odom /utlidar/switch /uwbstate
  /camera/camera/color/image_raw /camera/camera/depth/image_rect_raw
  /camera/camera/infra1/image_rect_raw /camera/camera/infra2/image_rect_raw
  /camera/camera/accel/sample /camera/camera/gyro/sample
  /unilidar/cloud /unilidar/imu /events/write_split /events/messages_lost
```

25 topics. **Not one of them is an `rt/` name** — pinned over the whole list by
`test_no_topic_on_the_command_line_is_ever_the_raw_dds_wire_name`, and the
`RecordedTopic` constructor refuses a `/rt/` prefix at construction (mutant M4).

### C3 — the storage config, and its honesty statement

```
$ .parcel/bin/python -B -c "from scripts.parcel_capture.rosbag2 import storage_config_yaml; print(storage_config_yaml())"
# parcel-capture rosbag2 MCAP writer options — card PS-G.
# profile: crash_safe
# TRANSCRIBED from rosbag2_storage_mcap documentation and NOT verified against
# the installed version. If `ros2 bag record` rejects this file, drop
# --storage-config-file and re-run: you lose the crash-safety tuning, not the
# session. Settle it with a 10-minute synthetic recording BEFORE the session.
noChunking: true
noMessageIndex: true
noSummary: false
noChunkCRC: false
chunkSize: 0
compression: ""
compressionLevel: ""
forceCompression: false
```

The body is JSON-compatible YAML, so it is valid input to the C++ parser rosbag2
uses **and** machine-readable back with `json` on a box with no PyYAML — pinned by
`test_the_storage_config_is_json_compatible_yaml_and_says_it_is_transcribed`,
which parses it back and compares to `writer_options()`.

### C4 — a rosbag2 MCAP read with the standard library, on a host with no ROS

```
$ .parcel/bin/python -B -c "<write a 513-message fixture bag, then read_rosbag2_mcap>"
clean       {'/lowstate': 500, '/utlidar/cloud': 10, '/events/write_split': 1}  walked_messages
chunked     {'/lowstate': 20, '/utlidar/cloud': 2}                              walked_messages
zstd chunk  {'/lowstate': 20, '/utlidar/cloud': 2}                              unavailable_compressed
            finding: "chunk uses 'zstd' compression; this reader does not decompress ..."
truncated   {'/lowstate': 500, '/utlidar/cloud': 2}  ScanTermination.TRUNCATED
            detail: "record opcode 0x05 at offset 797 declares 86 bytes, 66 present"
```

The truncated case is the one that matters: a flat battery is the expected way
this session ends, and every complete message before the cut is recovered while
the tail is classified as truncation rather than as a short recording.

### C5 — a `parcel.bag.v1` sidecar built from a rosbag2 recording

```
$ .parcel/bin/python -B -c "<finalize_rosbag2 over a 510-message bag>"
sidecar P5-DRY-20260814-take01.parcel-bag.json bytes 9960
verify True
does_not_prove lines: 15
[{"filename": "take_0.mcap",
  "sha256": "8525d4ed7e7ca78bfca745229f6ddde191e17c338caf0ebd1868a88c2957245d",
  "bytes": 147124, "termination": "clean", "count_basis": "walked_messages",
  "profile": "ros2", "library": "parcel-capture rosbag2 FIXTURE writer (not a recorder)",
  "messages": 510, "findings": []}]
```

The manifest passes `bags/schema.py:validate_manifest` unmodified, with
`source="hardware"`, `source_clock="ros"` (**not** `"sensor"` — the timestamps are
ROS receive times on the recorder host, and calling them sensor time is the
easiest way to make every later alignment quietly wrong), and topics that pass
`validate_topic`.

### C6 — `ros2 bag info` counts win, and a disagreement is recorded

From `test_ros2_bag_info_counts_win_and_a_disagreement_is_recorded`: with the tool
reporting 499 on `/lowstate` and the stdlib walk finding 500, the sidecar records
`messages: 499`, `count_basis: "ros2_bag_info"`, and this finding:

```
`ros2 bag info` reports 499 message(s) on /lowstate and the stdlib walk found 500;
the sidecar quotes ros2 bag info and records the disagreement rather than choosing quietly
```

### C7 — neither format's validation was weakened for the other

```
$ PYTHONDONTWRITEBYTECODE=1 .parcel/bin/python -B -m pytest tests/test_rosbag2_sidecar.py -q -k "weaken or refuses or right_verifier or secondary or fixture"
```
covered by five cells, all green:

| Cell | What it pins |
|---|---|
| `test_the_parcel_reader_still_refuses_a_rosbag2_encoding` | `read_mcap()` on a rosbag2 file ⇒ `termination == "corrupt"`, `"message_encoding"` in the detail, `message_count == 0`, and `if encoding != MESSAGE_ENCODING:` still present in `record.py` |
| `test_the_parcel_sidecar_path_still_refuses_a_rosbag2_file` | `build_sidecar()` on a rosbag2 file ⇒ `SidecarRefusedError` |
| `test_verify_sidecar_sends_a_rosbag2_manifest_to_the_right_verifier` | single-file verify refuses a rosbag2 manifest and names `verify_rosbag2_sidecar()` |
| `test_the_rosbag2_verifier_refuses_a_parcel_manifest` | and the reverse |
| `test_the_parcel_sidecar_now_says_it_is_the_secondary_copy` | the demotion is in the artefact |

### C8 — this card's two test files

```
$ PYTHONDONTWRITEBYTECODE=1 .parcel/bin/python -B -m pytest tests/test_capture_ingest.py tests/test_rosbag2_sidecar.py -q
90 passed in 0.25s
```
(47 ingest cells + 43 rosbag2/sidecar cells.)

### C9 — the whole capture stack, after the cross-card edits

```
$ PYTHONDONTWRITEBYTECODE=1 .parcel/bin/python -B -m pytest \
    tests/test_capture_envelope.py tests/test_capture_preflight.py \
    tests/test_capture_rehearsal.py tests/test_capture_sidecar.py \
    tests/test_clockmap.py tests/test_syncevents.py \
    tests/test_capture_ingest.py tests/test_rosbag2_sidecar.py -q
795 passed in 14.55s
```

The 605 cells PS-H measured are still green after the `sidecar.py` and `record.py`
edits, PS-I's 95 `test_syncevents.py` cells are green over the amended sidecar,
and 90 are new.

### C10 — ruff over every file this card touched

```
$ .parcel/bin/python -m ruff check tests/test_rosbag2_sidecar.py tests/test_capture_ingest.py \
    scripts/parcel_capture/rosbag2.py scripts/parcel_capture/sidecar.py \
    scripts/parcel_capture/ingest/ scripts/parcel_capture/record.py --output-format=concise
All checks passed!
```

### C11 — Python 3.10, STATIC only

```
$ .parcel/bin/python -B -c "<ast.parse feature_version=(3,10) over the new modules>"
3.10-parses scripts/parcel_capture/ingest/__init__.py
3.10-parses scripts/parcel_capture/ingest/base.py
3.10-parses scripts/parcel_capture/ingest/dds.py
3.10-parses scripts/parcel_capture/ingest/fake.py
3.10-parses scripts/parcel_capture/ingest/l2.py
3.10-parses scripts/parcel_capture/ingest/realsense.py
3.10-parses scripts/parcel_capture/rosbag2.py
3.10-parses scripts/parcel_capture/sidecar.py
3.10-parses scripts/parcel_capture/record.py
interpreter 3.14.4
```

**This host has no Python 3.10 interpreter** (PS-A and PS-H found the same). The
claim is that these modules parse under `feature_version=(3, 10)`. **No 3.10
process was executed.** The 3.14 claim is dynamic (C8/C9).

### C12 — `ci_gate --tier commit`

```
$ cd /home/jaewoo-jang/Desktop/Projects/Parcel && .parcel/bin/python scripts/ci_gate.py --tier commit
CI GATE — tier=commit  (2026-08-13T12:24:11Z)
[  PASS] HARD  ruff                       7 violation(s), baseline 7, new 0
[  PASS] HARD  hard-safety                nav frozen baseline …: collisions=0 false_arrival=0 | …
[  PASS] HARD  frozen-digest-sentinels    4 immutable manifest(s) byte-identical to pin
[  PASS] HARD  latency-tail-ledger        6 metric series within 1.2x tail ceiling (rows=5, window=5)
[  PASS] HARD  follow-bench-jerk-ratchet  1.2187 <= 1.46244 (baseline 1.2187 x 1.2)
[  PASS] HARD  model-off-non-inferiority  23 passed in 0.50s
[  PASS] HARD  frozen-digest-integrity    6 passed, 1 warning in 0.32s
[  PASS] HARD  mutation-panel-freshness   2 passed, 3 warnings in 4.29s
[  PASS] HARD  latency-tail               6 passed, 2 warnings in 0.29s
[  PASS] HARD  default-suite              4878 passed, 9 skipped, 36 deselected, 5 warnings in 197.54s
RESULT: PASS — every hard gate green.
  elapsed 209.1s
```

**An earlier run at 12:09 was RED, and that is worth recording.** It reported
`ruff` red and `default-suite` red with **8 failures, every one of them in
`tests/test_syncevents.py`** — PS-I's file, which grew on disk at 12:15 while my
run was in flight. Re-running that file alone immediately afterwards:

```
$ PYTHONDONTWRITEBYTECODE=1 .parcel/bin/python -B -m pytest tests/test_syncevents.py -q
95 passed in 1.51s
```

and `ruff check .` reported exactly the 7 baseline fingerprints. Neither failure
was mine; my owned files were clean throughout (C10). **The auditor should treat
any single `ci_gate` result from this tranche as a snapshot of a moving tree.**

A 12:19 run was green as well; the 12:24 run quoted above is the one taken
**after** the final quality edits (the `--disable-keyboard-controls` flag, the
`_does_not_prove` cleanup and the `RecorderFeed` field removal), so the result
above describes the tree as it stands.

---

## Seeded-failure table — one row per gate

Run against an **isolated copy** of `src/` + `scripts/parcel_capture/` + this
card's two test files (`scratchpad/ps_g_iso`), never the live tree: other
executors are running pytest against this repo concurrently and mutating a shared
source file underneath them would corrupt their results as well as mine. Every
case: `-B`, `PYTHONDONTWRITEBYTECODE=1`, and an explicit `__pycache__` purge
before **and after** each run — PS-A found a same-byte-length mutation defeats
CPython's `(mtime, size)` `.pyc` validity check and contaminates later runs. A
mutation whose precondition does not hold prints `NOT_APPLIED` rather than being
silently skipped; none did.

```
CONTROL  | unmutated | 90 passed in 0.26s
KILLED   | M1  source timestamp allowed on a wrapping-counter channel | 1 failed, 14 passed
KILLED   | M2  ReadOnlyHandle resolves anything                       | 1 failed, 3 passed
KILLED   | M3  handle allowlist may name a never-allowed surface      | 1 failed, 4 passed
KILLED   | M4  rt/-mangled wire name handed to ros2 bag record        | 1 failed, 49 passed
KILLED   | M5  recorder subscribes to -a instead of the topic list    | 1 failed, 47 passed
KILLED   | M6  crash-safe profile turns chunking back on              | 1 failed, 57 passed
KILLED   | M7  compressed chunk counts quoted as if walked            | 1 failed, 61 passed
KILLED   | M8  bag info parse returns an empty map instead of refusing | 1 failed, 70 passed
KILLED   | M9  sidecar digests only the first split file              | 1 failed, 73 passed
KILLED   | M10 rosbag2 sidecar claims per-channel sequence evidence   | 1 failed, 75 passed
KILLED   | M11 verify_sidecar accepts a rosbag2 manifest single-file  | 1 failed, 86 passed
KILLED   | M12 the parcel sidecar drops its SECONDARY-copy statement  | 1 failed, 40 passed
KILLED   | M13 LowState decoder reads all 20 motor slots as joints    | 1 failed, 18 passed
KILLED   | M14 BMS cell voltages left in millivolts                   | 1 failed, 21 passed
KILLED   | M15 foot_force_est dropped (one array, not two)            | 1 failed, 20 passed
KILLED   | M16 an adapter reports satisfied with its module absent    | 1 failed, 8 passed
KILLED   | M17 the ingest package gains a publisher symbol            | 1 failed
KILLED   | M18 unmapped rosbag2 topics silently dropped               | 1 failed, 77 passed
RESTORED | 90 passed in 0.26s
```

| # | Gate it seeds against | Killed by |
|---|---|---|
| M1 | The fail-closed clock rule (`tick` is not a timestamp) | `test_a_frame_cannot_carry_a_source_timestamp_on_a_channel_with_no_device_clock` |
| M2 | The facade's refusal of a computed reach | `test_the_facade_refuses_a_computed_reach_for_a_command_surface` |
| M3 | The denylist that guards the allowlist | `test_seeded_failure_a_handle_cannot_be_configured_to_reach_a_never_allowed_name` |
| M4 | The `rt/` correction on the recorder command line | `test_seeded_failure_a_wire_name_cannot_be_put_on_the_command_line` |
| M5 | Explicit topics, never `-a` | `test_the_command_line_is_exact_and_uses_the_mcap_storage_plugin` |
| M6 | The crash-safety argument for `noChunking` | `test_the_crash_safe_profile_turns_chunking_and_compression_off` |
| M7 | `count_basis` is never left implicit | `test_a_chunked_bag_is_walked_and_a_compressed_one_falls_back_and_says_so` |
| M8 | An empty count map would fabricate "recorded nothing" | `test_unparseable_bag_info_is_a_refusal_and_never_an_empty_count_map` |
| M9 | Every split file is digested | `test_the_sidecar_digests_every_split_file_and_a_mutated_byte_breaks_it` |
| M10 | The sequence-evidence gap is stated, not hidden | `test_the_sidecar_states_that_no_per_channel_sequence_evidence_exists` |
| M11 | A directory is not verified by digesting one file | `test_verify_sidecar_sends_a_rosbag2_manifest_to_the_right_verifier` |
| M12 | The demotion is in the artefact | `test_frames_flow_into_the_parcel_recorder_and_out_through_the_sidecar` |
| M13 | 12 actuated joints, not 20 (correction 5) | `test_low_state_decodes_twelve_joints_not_twenty` |
| M14 | `cell_vol` is millivolts (correction 6) | `test_bms_has_no_voltage_field_so_the_decoder_converts_millivolts_and_records_both` |
| M15 | Both foot-force arrays (correction 7) | `test_low_state_records_both_foot_force_arrays` |
| M16 | An absent dependency is never "ready" | `test_each_live_adapter_refuses_on_this_box_naming_its_module_and_a_remedy` |
| M17 | The read-only AST pin | `test_no_symbol_in_the_ingest_package_can_reach_a_command_surface` |
| M18 | An unmapped topic is counted, not dropped | `test_a_topic_with_no_matrix_row_is_counted_as_unmapped_not_dropped` |

**18 mutants, 18 killed, 0 survived, 0 not-applied.**

---

## OWNS deviations

Two files outside my OWNS were edited. Both are small and both are the completion
of the card's own defect, not scope creep.

### D1 — `scripts/parcel_capture/record.py` (PS-B). One function body, ~20 lines.

`resolve_live_source()` — the exact line the card names as DEFECT 1 — now resolves
through `ingest.adapter_for()` instead of raising unconditionally. The
missing-dependency branch is **byte-identical** to PS-B's (the existing PS-B cell
`test_resolve_live_source_refuses_and_names_the_missing_module` still passes
unchanged), and the second branch changed from *"no live backend ships in card
PS-B"* to a registry lookup. The return type changed `None` → `Any`.

**The MCAP writer was not touched.** `MinimalMcapWriter`, `read_mcap`,
`CaptureRecorder`, the framing, the latch machinery and `_decode_channel`'s
encoding refusal are all unmodified — verified by the C7 cell that asserts the
refusal is still in the source.

The import is deliberately **local to the function**: `ingest` imports `preflight`,
and keeping the edge inside the call means neither module's import graph grows a
cycle and `record.py` stays importable with the subpackage absent.

### D2 — `scripts/parcel_capture/sidecar.py` beyond "amend".

My OWNS says amend, and the amendment is large: +~700 lines (1,202 → 1,898). It
is confined to (i) two new enums, (ii) two keys added to the existing capture
block, (iii) one conditional `does_not_prove` line, (iv) one early branch in
`verify_sidecar`, and (v) a new, clearly-fenced rosbag2 section at the end. No
existing assertion was weakened and no existing key changed meaning; the 605
pre-existing capture cells are green (C9).

### Not deviated from

`src/parcel_robot/capture/**` (PS-A/PS-H), `bags/schema.py`, `preflight.py`,
`clockmap.py`, `attest.py`, `budget.py`, `rehearse.py` and every MUST-NOT-TOUCH
surface are **untouched**. No `Transport` member was added. Nothing was committed,
stashed or checked out.

---

## Findings handed on

1. **`TRANSPORT_DEPENDENCIES[VENDOR_VIDEO] = ("unitree_sdk2py",)` is still wrong**
   (`record.py:1366`), as PS-H flagged. The only remaining `VENDOR_VIDEO` channel
   is RTP-over-multicast H.264, which needs ffmpeg/GStreamer. I did **not** fix it:
   it is PS-B's table, changing it changes `missing_requirements()` for that
   channel, and `ingest.UNSERVED_TRANSPORTS` already records the correct reason in
   the place an operator will read. **For whoever owns `record.py`.**
2. **`/events/messages_lost` is UNVERIFIED and must be settled by
   `ros2 topic list -t` before the first take.** The recorder's message-loss
   reporting has moved between rosbag2 releases and this build has no ROS to check
   against. Listing a topic that does not exist costs nothing at record time;
   assuming one that does exist is not recorded costs the evidence. **For PS-F's
   run-sheet.**
3. **The eight `DRIVER_NODE` topic names are UNVERIFIED** and depend on each
   driver's launch namespace. Each row carries its `ros2 launch` line. The
   pre-session `ros2 topic list -t` is what turns them into observations — and a
   wrong name here is **silent**: the recorder simply never subscribes. **For
   PS-F.**
4. **The storage-config key names are transcribed, not verified.** Tonight's no-dog
   checklist item "10-minute synthetic recording through the exact command line"
   is what settles them, and the documented fallback is to drop
   `--storage-config-file`. **For the N0–N7 checklist.**
5. **rosbag2 gives no per-channel drop attribution.** If per-channel drop
   provenance is a requirement of the dataset — RISK_ASSESSMENT names it as one of
   the four unrecoverable quantities — then the Parcel secondary recording must run
   for at least the low-rate channels, because it is the only path that mints a
   per-channel sequence. **For PS-F and the auditor.**
6. **PS-K/PS-L's `TONIGHT_CHECKLIST.md` N4b and this card disagree about the MCAP
   writer profile, and the disagreement is real.** They independently transcribed
   the same key names (`noChunkCRC`, `chunkSize`, `compression`, `compressionLevel`)
   and chose `Zstd`/`Fast` with 4 MiB chunks; I chose unchunked and uncompressed.
   The trade is disk against crash exposure and stdlib countability: a compressed
   chunk that a killed recorder half-wrote loses the whole chunk rather than the
   tail, and cannot be counted here at all without `zstandard`. **Tonight's N4e —
   which reads the setting back out of the written file rather than trusting that
   the command did not error — is what should settle it, and whoever runs it should
   record which profile the installed plugin actually honoured.** The single key
   that matters is `compression`: if `noChunking` is silently ignored, the writer
   falls back to a default that has been `Zstd` in some releases.
7. **`/utlidar/switch` is on the record list and is an INPUT topic to the vendor
   stack.** We subscribe and never write. Nothing in `parcel_robot.capture` or
   `scripts/parcel_capture/ingest` can write to a transport at all. Recorded here
   so nobody is surprised to see it on the command line.

---

## What this does not prove

- **The final `--disable-keyboard-controls` / `_does_not_prove` / `RecorderFeed`
  edits landed after the 12:19 gate run and before the confirming run quoted in
  C12; the mutation panel and the 795-cell suite were re-run over them (both
  green, 18/18 killed).**
- **Not one line of the live transport code has ever executed.** `rclpy`,
  `pyrealsense2` and `unilidar_sdk2` are absent from this host and the board
  forbids installing them, so `DdsIngest.read_frames`, `RealSenseIngest.read_frames`
  and `L2Ingest.read_frames` have never run. What is measured is: they refuse
  correctly, their decoders are correct against synthetic messages, and the
  interface they implement works end to end under `FakeIngest`. The subscribe
  loops themselves are **unexecuted code on the critical path of a session**, and
  that is the largest single risk this card carries.
- **`ros2 bag record` has never been run.** No command line in this module has
  been executed by ROS, no storage config has been accepted or rejected by
  `rosbag2_storage_mcap`, and `ros2 bag info` has never produced output for
  `parse_bag_info` — the parser was written against transcribed output format and
  tested against a synthetic sample. If the info format differs, `parse_bag_info`
  refuses (it never returns an empty map), so the failure is loud, but it is a
  failure that would happen on session morning.
- **Every rosbag2 MCAP this card has read was written by `write_fixture_bag`.**
  The reader has never seen bytes produced by the reference MCAP writer. The
  fixture writer and the reader share my understanding of the format, so a shared
  misreading of the spec would be invisible to both. `mcap` is not installed and
  the board forbids installing it; the cross-validation belongs on the Orin.
- **The `/events/*` topics, the eight driver topic names, and the storage-config
  keys are all documentation.** See findings 2–4.
- **No message was decoded from a real Go2.** Every decoder was exercised against
  duck-typed objects I constructed from vendor message definitions. If our unit's
  `LowState` differs from the transcription, `read_field` degrades to a recorded
  missing field rather than a crash — which is a mitigation, not a verification.
- **The read-only claim is structural, not exhaustive.** The AST pin sees symbols
  and imports; the facade blocks computed attribute reaches; the dynamic-reach
  census pins the count at two. What none of them covers: `_SubscribeOnlySession`
  holds a raw node reference (name-mangled, never returned, three public methods),
  and a `.so` that a vendor module imports is outside every one of these
  mechanisms. The strongest guarantee remains the absence of `unitree_sdk2py` from
  `.parcel/`.
- **No drop, rate, or bandwidth behaviour was observed at session scale.** The
  largest fixture bag here is 510 messages and 147 KB. Whether `ros2 bag record`
  sustains 25 topics at ~100+ MB/s on the Orin's NVMe is PS-E's question and the
  session's; nothing here measures it.
- **The 3.10 claim is static.** No 3.10 interpreter exists on this host and none
  was run. See C11.
- **Concurrency caveat on C9/C12:** other executors were editing
  `scripts/parcel_capture/**` and running pytest against this working tree while
  these runs happened. C8 and the mutant table are isolated and reliable; a
  whole-tree run is a snapshot of a tree that was moving.

---

## PS-N addendum — 2026-08-13, correcting the coverage claim above

**Added by card PS-N (FIX tranche PS-3), which owns `scripts/parcel_capture/ingest/**`.
Nothing above is deleted; this supersedes one claim in it.**

The does_not_prove above is right that "not one line of the live transport code
has ever executed". The claim it makes alongside that — that the **decoders**
were exercised — was overstated, and an adversarial audit found by how much.
Measured, with a stdlib `sys.settrace` line tracer (no `coverage` package exists
in `.parcel/`; executable lines from `co_lines()` walked through `co_consts`),
over `tests/test_capture_{ingest,preflight,rehearsal,sidecar}.py` against the
sources as this card left them:

| file | executable | executed | **never executed** |
|---|---|---|---|
| `ingest/dds.py` | 462 | 369 | 93 (20.1 %) |
| `ingest/l2.py` | 145 | 79 | **66 (45.5 %)** |
| `ingest/realsense.py` | 136 | 90 | **46 (33.8 %)** |
| **total** | **743** | **538** | **205 (27.6 %)** |

So: the DDS decoders were substantially exercised; the L2 and RealSense decoders
were not — `frame_from_l2` had never been called for either L2 channel, and
`frame_from_realsense` had never been called for any of the six D455 rows. The
independent audit measured 202/743 (27.2 %) and this reproduction agrees to
within three lines.

PS-N raised the three adapters to **805/805 executable lines (100 %)** using
read-only test doubles for `rclpy`, `pyrealsense2` and `unilidar_sdk2` installed
via `monkeypatch.setitem(sys.modules, …)` — nothing is installed into `.parcel/`,
and `test_a_full_preflight_run_never_imports_a_vendor_sdk` still reports
`VENDOR []`. The residual is no longer lines; it is the vendor libraries behind
them, and it is enumerated in `PSN_STATUS.md` §3.4 and does_not_prove.

PS-N also changed two things this card shipped, with executed evidence in
`PSN_STATUS.md` §4:

* `RealSenseIngest.read_frames` started the pipeline with **no `rs.config`**, so
  every D455 row read librealsense's default profile. Measured: `d455.gyro`
  yielded 1094 colour frames and `probe_channel` reported the **gyroscope**
  PRESENT with 935 messages. Now: `stream_selection()` enables this channel's
  stream and index, and `attributable()` discards any frame that did not decode
  as that stream.
* `L2Ingest.open_reader` returned a freshly constructed `UnitreeLidarReader()`,
  which is not attached, so `l2.cloud` (CRITICAL) came back with the same
  "nothing arrived" wording an unplugged L2 would produce. Now `require_attached()`
  consults `checkInit()` and refuses with the state named. It still does **not**
  call `initialize()`.
