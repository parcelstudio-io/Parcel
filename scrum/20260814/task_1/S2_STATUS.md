# S-2 — run-specific Stage-0 command addendum (T7–T10)

**Card:** S-2 (`REVISED_BOARD.md`) · **Date:** 2026-08-14 · **Executor:** Sol-lane agent
(standing in for ChatGPT Sol 5.6 Ultra)
**Why:** Stage-0 had no first-class rows for RealSense launch, L2 launch, Unitree
overlay/DDS, or the actual `ros2 bag record -s mcap` argv. Historical sheets
still carried `--disable-keyboard-controls`, which Humble rejects with argparse
exit 2 and zero bytes recorded. Working agreement 7: one argv truth source.

**OWNS:** `scripts/parcel_capture/stage0_addendum.py`,
`tests/test_stage0_command_addendum.py`,
`scrum/20260814/task_1/STAGE0_COMMAND_ADDENDUM.md`, this file.
Imports only from S-1's `rosbag2.py` (`Rosbag2Plan`, `record_command`, distro
helpers, `--verify-help` / help clearance). Does **not** rewrite S-1.

**FINALIZE_BLOCKED_ON_H1:** yes — Orin distro unread.

**AU-F follow-up (same day):** combined-sheet storage path moved outside the bag
output dir (`/data/parcel/mcap_storage.yaml`, not under `/data/parcel/session`)
to clear the take-losing nest Fable flagged as MAJOR. Pin:
`test_storage_config_path_is_outside_the_bag_output_dir`.

---

## 0 · Headline

Both-distro T7–T10 templates drafted and pinned. T10 argv is rendered exclusively
from `record_command(Rosbag2Plan(distro=…))` — never hand-invented. Humble argv
omits `--disable-keyboard-controls` / `--topics` / `--node-name`. Jazzy draft
carries those flags and is refused against Humble help. Committed addendum is
byte-identical to the generator (disk-ledger pattern).

`READY_FOR_STATIONARY_STAGE0` is **not claimed**.

## 1 · What was built

1. **`stage0_addendum.py`** — sibling renderer + CLI (`--emit`, `--print-argv`,
   `--verify-help`). Header stamps H-1 UNREAD / FINALIZE blocked. T7 RealSense
   (profile from `RECOMMENDED_PROFILE`, `unite_imu_method` required), T8 L2
   launch, T9 Unitree overlay + `RMW_IMPLEMENTATION` / `CYCLONEDDS_URI`, T10
   argv + `storage_config_yaml()` block with parse markers. Calibration/TF/sync
   stop-gate pointers to S-1. Humble-specific refusal if
   `--disable-keyboard-controls` is injected.
2. **`STAGE0_COMMAND_ADDENDUM.md`** — generated run-specific operator sheet.
   Historical 20260813 templates linked as provenance only (not edited).
3. **`tests/test_stage0_command_addendum.py`** — byte-identity pin, argv ==
   `record_command` for both distros, storage-config identity, Humble keyboard
   refusal, help-mismatch refusal, hand-invented T10 mutation reddens.

## 2 · Measured claims

| # | Claim | Command | Output |
|---|---|---|---|
| M1 | Committed addendum == renderer | `pytest tests/test_stage0_command_addendum.py::test_committed_addendum_is_byte_identical_to_the_generator` | passed |
| M2 | Humble T10 argv == `record_command` and omits keyboard flag | extract markers + compare | argv positional topics; no `--disable-keyboard-controls` |
| M3 | Jazzy T10 argv == `record_command` and carries keyboard/`--topics` | same | present; refused vs Humble help |
| M4 | Inject `--disable-keyboard-controls` into Humble argv | `refuse_if_humble_carries_disable_keyboard` / `clear_argv_against_help` | `Rosbag2RefusedError` (ZERO bytes) |
| M5 | Help mismatch (strip `--max-cache-size` from help) | `clear_argv_against_help` | refused |
| M6 | Focused suite | `pytest tests/test_stage0_command_addendum.py -q` | **21 passed** |
| M7 | No-arm pin | `pytest tests/test_no_arm_pin.py -q` | **72 passed** (95 total with S-2) |
| M8 | 3.10 grammar | `ast.parse(..., feature_version=(3,10))` | parse OK |

## 3 · Seeded failures

| Seed | Expected | Result |
|---|---|---|
| Inject `--disable-keyboard-controls` into Humble argv | refuse before record | reddens / raises |
| Validate Jazzy argv against Humble `--help` | refuse (unsupported flags) | raises `Rosbag2RefusedError` |
| Strip `--max-cache-size` from help text | refuse | raises |
| Unrecognised help prose | refuse (never a clearance) | raises |
| Replace Humble argv line with `ros2 bag record -a --disable-keyboard-controls` | argv-equality pin fails | extracted ≠ `record_command` |
| Drop `BEGIN_ARGV` markers | extraction refuses | raises |

## 4 · does_not_prove

1. **H-1 has not run** — JetPack / Ubuntu / `/opt/ros/*` unread. FINALIZE blocked.
2. **No Orin measurement** of RealSense / L2 / Unitree launch argument spellings
   or real topic names (H-2). T7–T9 remain documentation-derived UNVERIFIED
   templates.
3. **No `--verify-help` against a real Orin help file** — clearance is proven
   against fixture help text and the existing rosbag2 help fixtures' contract.
4. **Does not authorize motion**, stand, gait, lease, or joining the robot LAN.
5. **Does not claim `READY_FOR_STATIONARY_STAGE0`** — that requires H-2 evidence
   from the actual Orin (AU-F / hard-stop rules).
6. **Storage-config plugin acceptance on Humble** remains UNVERIFIED (same as
   PS-M); drop `--storage-config-file` if the plugin rejects it.

## 5 · Blockers

| ID | Blocker | Unblock |
|---|---|---|
| **FINALIZE_BLOCKED_ON_H1** | Distro unknown | Operator runs H-1 identity commands; re-`--emit` is unnecessary for templates, but pick the matching T10 block and `--verify-help` against Orin help before first record |
| H-2 | Driver/topic/QoS unmeasured | No-dog Orin rehearsal |
| H-3 | Mount geometry | Independent; operator today |

---

# S-2 · Part B — the per-distro operator sheets

> **Two executors worked card S-2 concurrently in one tree.** Everything above
> is the first executor's, unchanged. This half is the second executor's, and it
> was written **additively**: `render_stage0_command_addendum()` still emits
> byte-identical output, `STAGE0_COMMAND_ADDENDUM.md` is untouched, and
> `tests/test_stage0_command_addendum.py` is green. See §B6 for the collision
> record and §B7 for a defect found in the shared half that I did **not** fix in
> their file.

**Card:** S-2 · **Date:** 2026-08-14 · **Executor:** Opus (second S-2 lane)
**OWNS (this half):** `scripts/parcel_capture/stage0_addendum.py` (additive
region only), `tests/test_stage0_addendum.py`,
`scrum/20260814/task_1/STAGE0_ADDENDUM_HUMBLE.md`,
`scrum/20260814/task_1/STAGE0_ADDENDUM_JAZZY.md`, this section.
Read-only consumers of S-1's `rosbag2.py`, `preflight.py`, `sidecar.py`,
`budget.py`, `capture/channels.py`. **No S-1 file was edited.**

## B0 · Headline

The card asked for two things the combined document does not do: a sheet whose
unit is a **row** (exact command + expected observable + explicit STOP branch,
no prose-only rows), and **two separate distro-parameterised files** of which
exactly one becomes operative after H-1. Both now exist, generated, pinned, and
regenerable with one command:

```
.parcel/bin/python -m scripts.parcel_capture.stage0_addendum --distro humble --emit-distro
.parcel/bin/python -m scripts.parcel_capture.stage0_addendum --emit-all-distros
```

22 rows across T7-T10, each carrying all three parts, because `CommandRow`
**cannot be constructed** without them. `READY_FOR_STATIONARY_STAGE0` is not
claimed and nothing here has run on an Orin.

The strongest structural result is the anti-drift half: the RealSense launch
line is **derived from the recording plan**, not typed beside it. Every
`enable_*` exists because a `d455.*` row is on `rosbag2.RECORDED_TOPICS`; the
camera namespace is parsed out of the recorded topic names; the profile is
`budget.RECOMMENDED_PROFILE`; the L2 launch line is read off the l2.* rows' own
`prerequisite` field; and a `d455.*` channel arriving on the plan with no known
launch argument is a **refusal**, not a silent omission. There is no path by
which the driver command and the recorder topic list disagree.

## B1 · Measured claims — command and output

Sandbox recipe (PSM_STATUS.md M6/D10 shape), used for every row marked
[MEASURED-JAZZY-SANDBOX]; read-only rootfs already in the repo, no install, no
network, no node, no topic:

```
bwrap --bind .cache/external-evals/runtime/ros-jazzy-base-sandbox / \
      --bind <scratch> /work --bind <scratch>/data /data \
      --proc /proc --dev /dev --unshare-net --unshare-pid \
      --setenv HOME /root --chdir /work /bin/bash -lc '…'
```

| # | Claim | Command | Output |
|---|---|---|---|
| **B-M1** | Real Jazzy recorder help captured | `source /opt/ros/jazzy/setup.bash; ros2 bag record --help` in the sandbox | `EXIT=0 bytes=10655`, sha256 `a5cba7246f957ea2df9fd9ae4b121f063d9bf7fec99c6358572cc79323362e2a` |
| **B-M2** | **Both sheets' argv clear against that real help** | `validate_argv_against_help(extract_argv_from_addendum(sheet, distro), help)` | `jazzy sheet argv, 50 tokens, 9 flag(s) -> CLEARED` · `humble sheet argv, 46 tokens, 6 flag(s) -> CLEARED` |
| **B-M3** | **Both argv parse under Jazzy's own `RecordVerb` argparse**, no node created | `verb.add_arguments(parser,…); parser.parse_args(tail)` in the sandbox | `humble: ARGPARSE OK --topics=0 storage=mcap max_bag_size=0 max_cache=8388608 node_name=rosbag2_recorder` · `jazzy: ARGPARSE OK --topics=31 … node_name=parcel_rosbag2_recorder` — the intersection claim, executed |
| **B-M4** | **`--storage-config-file` missing is exit 2 BEFORE recording** (PS-M §3.4 asserted it; here it is executed) | same probe, storage config absent | `ros2 bag record: error: argument --storage-config-file: can't open '/data/parcel/stage0/mcap_storage.yaml': [Errno 2] No such file or directory` · `ARGPARSE REFUSED exit=2` — this is why T10.2 precedes T10.6 |
| **B-M5** | **`ros2 bag record` refuses an `--output` folder that already exists** — NEW finding | `mkdir -p /data/parcel/stage0/take01; ros2 bag record --storage mcap --output /data/parcel/stage0/take01 … /lowstate` | `[ERROR] [ros2bag]: Output folder '/data/parcel/stage0/take01' already exists.` `EXIT=1`; source: `ros2bag/verb/record.py:273-274 if os.path.isdir(uri): return print_error(...)` |
| **B-M6** | `ros2 launch --show-args`, `ros2 topic hz -w`, `ros2 topic type`, `ros2 topic echo --once/--qos-durability/--qos-reliability`, `ros2 topic list -t` all exist | `ros2 <verb> --help` in the sandbox | each printed its usage, exit 0 — every observable row of the sheet uses a flag that exists |
| **B-M7** | Both sheets are byte-identical to the generator | `pytest tests/test_stage0_addendum.py -q` | **65 passed in 0.24s** |
| **B-M8** | The sibling's combined doc is unaffected by my additions | `pytest tests/test_stage0_command_addendum.py -q` (in the 509-test run below) | passed; `render_stage0_command_addendum() == STAGE0_COMMAND_ADDENDUM.md` verified `True` |
| **B-M9** | No-arm pin covers the module, statically and dynamically | `pytest "tests/test_no_arm_pin.py::…[scripts/parcel_capture/stage0_addendum.py]"` (both halves) | **2 passed**; whole pin **72 passed** inside the run below |
| **B-M10** | Focused suite | `pytest tests/test_stage0_addendum.py tests/test_stage0_command_addendum.py tests/test_no_arm_pin.py tests/test_rosbag2_sidecar.py tests/test_capture_preflight.py tests/test_bandwidth_budget_doc.py tests/test_disk_ledger_doc.py -q` | **509 passed in 22.68s** |
| **B-M11** | ruff clean on both owned files | `.parcel/bin/python -m ruff check scripts/parcel_capture/stage0_addendum.py tests/test_stage0_addendum.py` | `All checks passed!` |
| **B-M12** | 3.10 grammar (the Orin runs 3.10; this box is 3.14.4) | `ast.parse(..., feature_version=(3,10))` on both files | `both parse under Python 3.10 grammar` |
| **B-M13** | Gate names cross-checked against S-1's **landed** API | `test_every_named_stop_gate_exists_in_the_live_module` over `GATE_REFERENCES` | 6/6 resolve: `preflight.reconcile_support_topics_or_raise`, `sidecar.validate_static_transform_snapshot`, `.assess_go_record`, `.verify_calibration_digest`, `.verify_sync_fit_binding`, `.finalize_rosbag2`; and `STATIC_TF_SNAPSHOT_SCHEMA_NAME == sidecar.STATIC_TF_SNAPSHOT_SCHEMA` |

## B2 · Seeded failures — every one executed, restored byte-identically

Harness: `scratchpad/s2/seeded.py` — one defect on disk at a time, `-B` +
`PYTHONDONTWRITEBYTECODE=1`, `__pycache__` purged before and after, restore from
bytes held in memory, sha256 verified.

```
=== baseline: rc=0 65 passed in 0.24s
```

| Seed | Where | Expected | Result |
|---|---|---|---|
| **(a)** `--disable-keyboard-controls` injected into the **humble** sheet's argv row | in memory, at `Addendum` construction | caught by my own validation **before render** | `AddendumRefusedError: T10.6: 'ros2 bag record' line carries ['--disable-keyboard-controls'], which ROS 2 humble's recorder verb does not declare. argparse exits 2 … the session records ZERO bytes` |
| (a′) the *same* flag for **jazzy** | same | accepted — the gate must be distro-aware, not a denylist | returned `('--storage', '--disable-keyboard-controls')` |
| **(b)** hand-edit `--max-cache-size 8388608` → `104857600` in the committed HUMBLE sheet | on disk | pin reddens | `3 failed, 62 passed`: byte-identity[humble], hand-edit-guard[humble], committed-argv-equals-record_command[humble]. Restored `identical=True sha256=debf3ce1367463774feefeabccc581e2d3163cb8e851a2dc020555165469bee3` |
| (b′) hand-edit an **EXPECTED** cell (prose, not a command) | on disk | pin reddens — the whole file is pinned, not only the argv | `1 failed, 64 passed` (byte-identity[humble]). Restored `identical=True`, same sha256 |
| **(c)** unknown distro string | `parse_distro` | refusal, never a default | `'foxy'`, `'iron'`, `'rolling'`, `''`, `'  '`, `'HUMBLE2'` all refuse; CLI `--distro foxy --emit-distro` → `refused: … BOTH variants are VOID: take REVISED_BOARD.md H-1's 'anything else' branch, STOP` **rc=2** |
| (d) drop `"d455.infra2"` from `_D455_LAUNCH_ENABLE` (anti-drift) | on disk, in the module | the sheet must not silently lose a stream | `21 failed, 44 passed` — `realsense_launch_arguments()` raises `AddendumRefusedError: … D455 channel(s) ['d455.infra2'] with no known rs_launch.py argument`, so **no document renders at all**. Fail closed, not fail quiet. Restored `identical=True sha256=4e8d0c917950a500640a982cf024839ca10af4518b1b0dd9c547070c4409fdfb` |
| (e) a row that would command the robot | `CommandRow` | refusal | `row 'T9.9' would have the operator run 'topic pub': this session is sensors-only …` |
| (f) a row offering `enp3s0` (the stale `configs/robot.yaml` NIC) | `CommandRow` | refusal | `row 'T9.9' names 'enp3s0', the stale placeholder in configs/robot.yaml:128 and :342 — a NIC name from a different machine …` |
| (g) a row with no STOP branch / a prose-only row | `CommandRow` | refusal | both raise `AddendumRefusedError` |
| (h) forged argv substituted into the rendered sheet | in memory | layer-2 extraction oracle rejects it | extracted `!= record_command`, `'-a'` present |
| (i) missing `BEGIN_ARGV` markers | in memory | extraction refuses | `Rosbag2RefusedError` |

```
=== after restore: rc=0 65 passed in 0.23s
final digests:
  humble_doc: debf3ce1367463774feefeabccc581e2d3163cb8e851a2dc020555165469bee3
  module:     4e8d0c917950a500640a982cf024839ca10af4518b1b0dd9c547070c4409fdfb
```

## B3 · What the sheets contain

22 rows. Each carries an exact command, an expected observable and a STOP branch.

* **T7 · RealSense** — T7.1 free the camera (N2e); **T7.2 `--show-args` is a
  mandatory preceding row** because the profile-argument spelling changed across
  driver 4.51→4.55; T7.3 the launch itself, arguments derived from the plan
  (`camera_namespace`/`camera_name` parsed out of the recorded topic names,
  `enable_*` one per planned `d455.*` row, `848x480x30` from
  `RECOMMENDED_PROFILE`, `unite_imu_method` because without it the IMU topics
  are silently absent, `publish_tf:=true tf_publish_rate:=0.0` because S-1's
  GO-RECORD gate refuses a bag whose optical frames have no parent); T7.4 the
  10 topics (6 payload + 4 `camera_info`) with types and rates; **T7.5 the
  calibration must describe the stream that was recorded** — an 848×480 stream
  under a 1280×720 calibration is a named S-1 refusal, caught here instead of
  after the take.
* **T8 · L2** — T8.1 the second-NIC preconditions, values **cited** from
  TONIGHT_CHECKLIST N6a/N6b and N5a (host `192.168.1.1/24`, device
  `192.168.1.2`, no `default` route via the L2 NIC) including N5's own
  N6-before-N5 ordering note; T8.2 overlay + package; T8.3 the launch line read
  off the plan's `prerequisite`; T8.4 `/unilidar/cloud` + `/unilidar/imu` with
  the IMU plausibility gate.
* **T9 · Overlay/DDS** — T9.1 **the firmware pin as a hard stop before any LAN
  join** (≥ V1.1.13, ADR 0002 §1 / PRE-1, unreadable = below pin); T9.2
  `ip -brief addr` to discover the real names; T9.3 the CycloneDDS config
  rendered with `__GO2_IFACE__`, a `sed` substitution step, and
  **`grep -c '__GO2_IFACE__'` whose expected output is `0`** — a forcing
  function with a STOP, not a suggestion; T9.4 `ROS_DOMAIN_ID` unset and one
  RMW; T9.5 the binding proof **including the negative control**; T9.6 the
  `unitree_ros2` interface overlay.
* **T10 · Recorder** — T10.1 `--verify-help` clearance (mandatory, first);
  T10.2 emit the storage config **outside** the record target; T10.3 the S-1
  support-artifact reconciliation stop gate; T10.4 the transient-local
  `/tf_static` snapshot stop gate; T10.5 confirm the shell and that the output
  folder does not exist; **T10.6 the argv, rendered from
  `Rosbag2Plan(distro=…)` and from nothing else**, wrapped in
  `BEGIN_ARGV`/`END_ARGV` so the pin parses it back out; T10.7 the post-take
  stop gates named by their real S-1 symbols.

## B4 · Deliberate divergences from the historical sheets

| # | Divergence | Why |
|---|---|---|
| D1 | T9.5 proves the DDS binding with **participant discovery** (`ros2 daemon stop; ros2 daemon start; ros2 node list`) where N6d publishes a test topic | This session is sensors-only. Same evidence — traffic on the intended NIC and none on the other — with nothing emitted onto the robot's topics. The divergence is stated in the row's own provenance line. |
| D2 | The storage config lives at `/data/parcel/stage0/mcap_storage.yaml`, **outside** `/data/parcel/stage0/take01` | B-M5: creating anything inside the record target makes the directory exist and the recorder then refuses. |
| D3 | `<Interfaces><NetworkInterface>` values are cited from N6d, not restated with new numbers | Working agreement 3 / the card's "cite, do not restate divergently". |

## B5 · OWNS deviations

1. **`scripts/parcel_capture/stage0_addendum.py` was already occupied.** A
   concurrent S-2 executor created it at 17:22-17:23 while I was writing my
   version of the same path. I did **not** revert their work. My code is spliced
   in as an additive region; their public API (`render_stage0_command_addendum`,
   `emit_addendum`, `addendum_path`, `rendered_argv`, `session_plan`,
   `ARGV_BEGIN/END`, `STORAGE_BEGIN/END`, `extract_argv_from_addendum`,
   `extract_storage_config_from_addendum`,
   `refuse_if_humble_carries_disable_keyboard`, `clear_argv_against_help`,
   `DEFAULT_OUTPUT_DIR`, `DEFAULT_STORAGE_CONFIG_PATH`, `HISTORICAL_*`,
   `ADDENDUM_RELATIVE`, CLI `--emit` / `--print-argv` / `--verify-help`) is
   byte-for-byte behaviour-preserving, and their pin is green (B-M8).
2. **Two changes to their region, both minimal and both required.**
   (i) `--distro` lost its argparse `choices` so an unknown value reaches
   `parse_distro()` and refuses with the H-1 branch spelled out instead of a
   bare argparse message — a superset of the previous accepted values, and their
   `test_cli_verify_help_refuses_jazzy_argv_on_humble_help` still returns 0/2 as
   asserted. (ii) `main()` resolves the distro once through `parse_distro`. No
   other line of their code changed.
3. **`S2_STATUS.md` is shared.** Their status document is above, untouched; this
   is appended below it.
4. **`STAGE0_COMMAND_ADDENDUM.md` and `tests/test_stage0_command_addendum.py`
   are theirs and I did not edit either.**
5. Nothing under `src/parcel_robot/`, `evals/`, `bags/`, `configs/`, or
   `scrum/20260813/**` was touched. `.parcel/` is unmodified. No vendor SDK.

## B6 · Cross-card observations — reported, not fixed

1. **`DEFAULT_STORAGE_CONFIG_PATH = /data/parcel/session/mcap_storage.yaml` is
   inside `DEFAULT_OUTPUT_DIR = /data/parcel/session`.** Following
   `STAGE0_COMMAND_ADDENDUM.md`'s own instruction — emit the storage config,
   then run the argv — creates the output directory, and the recorder then
   refuses with `Output folder '/data/parcel/session' already exists` (B-M5,
   executed). That sheet's operator would lose the take at the first command.
   **It is not my file to change; the constant and the row need a one-line
   move.** My sheets use a path outside the record target and carry a row
   (T10.5) that checks the folder is absent.
2. `emit_addendum()` takes an all-optional signature, so the no-arm pin's
   dynamic harness calls it and **writes `STAGE0_COMMAND_ADDENDUM.md` into the
   repo during the test run**. The bytes are identical so `git status` does not
   move and nothing is corrupted, but a test that writes into the working tree
   is a latent surprise. One keyword-only or required argument fixes it.
3. S-1's landed API is consumed read-only and all six gate names resolved at the
   time of writing (B-M13). If S-1 renames one after this, my test reddens with
   a message naming the sheet row that would have lied.

## B7 · does_not_prove

1. **No command in either sheet has ever executed on a real Orin. Not one.**
   The Orin's distro is unread, no driver is installed, no topic has been
   observed, and no bag has been written. **H-1 supplies the distro and H-2
   supplies the rest**; until then both sheets are DRAFT and their own banners
   say so. Everything executed here ran in a ROS 2 **Jazzy** sandbox on this
   desktop.
2. **Jazzy is not Humble.** B-M1 to B-M6 are Jazzy measurements. Every Humble
   claim in the HUMBLE sheet is read from `ros2/rosbag2`'s source, exactly as
   PS-M left it, and its provenance line says so. `ros2 bag record --help` on
   the Orin plus `--verify-help` (row T10.1) is the only thing that closes this,
   and it is the first row of T10 for that reason.
3. **The RealSense and L2 launch argument spellings are UNVERIFIED**, including
   `publish_tf` / `tf_publish_rate` / `rgb_camera.color_profile` /
   `unite_imu_method` and the L2 package, workspace and launch-file names. The
   `--show-args` and README rows exist because of that, and a sheet that got
   them wrong would launch at the wrong profile or not at all.
4. **Every topic name is documentation-derived.** Deriving them from the plan
   makes the launch line and the record line consistent; it does **not** make
   either of them correct. `ros2 topic list -t` on the real graph is the only
   authority, and T7.4/T8.4 exist to record the differences.
5. **The gate names are cross-checked; the gate behaviour is not.** My test
   asserts each S-1 symbol exists. Whether `assess_go_record` refuses the right
   bags is S-1's evidence.
6. **`camera_info` publication is asserted, not observed.** The claim that
   `realsense2_camera` publishes a `CameraInfo` per enabled stream under the
   image topic's namespace is documentation-derived. T7.4 (topics exist) and
   T7.5 (the calibration matches the stream) are the rows that turn it into an
   observation.
7. **The `--storage-config-file` bytes were never read by the version that will
   read them.** Same limitation as PS-M: measured against
   `rosbag2_storage_mcap` 0.26.11, and a Humble-era plugin may name a key
   differently — an unknown key is *silently ignored*.
8. **Nothing here authorises motion**, a stand, a gait, a lease, or joining the
   robot LAN. The generator refuses to render a row that would command anything,
   and the recursive no-arm pin covers the module. That is a property of the
   text and the code; it is not a claim about what an operator will type.
9. **`READY_FOR_STATIONARY_STAGE0` is not claimed and cannot be** from a desk.

## B8 · Gates

```
$ .parcel/bin/python -m ruff check scripts/parcel_capture/stage0_addendum.py tests/test_stage0_addendum.py
All checks passed!

$ .parcel/bin/python -m pytest tests/test_stage0_addendum.py -q
65 passed in 0.24s

$ .parcel/bin/python -m pytest tests/test_stage0_addendum.py \
    tests/test_stage0_command_addendum.py tests/test_no_arm_pin.py -q
162 passed in 20.15s

$ .parcel/bin/python -m pytest tests/test_stage0_addendum.py \
    tests/test_stage0_command_addendum.py tests/test_no_arm_pin.py \
    tests/test_rosbag2_sidecar.py tests/test_capture_preflight.py \
    tests/test_bandwidth_budget_doc.py tests/test_disk_ledger_doc.py -q
509 passed in 22.68s

$ .parcel/bin/python -c "import ast,pathlib; ast.parse(...feature_version=(3,10))"
both parse under Python 3.10 grammar; dev interpreter 3.14.4
```

### ci_gate, twice, because the tree moved under it

```
$ .parcel/bin/python scripts/ci_gate.py --tier commit          # 21:38Z
[  FAIL] HARD  ruff          9 violation(s), baseline 7, new 2 ->
      tests/test_orin_rehearsal.py::PLR0133; tests/test_orin_rehearsal.py::RUF100
[  FAIL] HARD  default-suite 2 failed, 5279 passed, 9 skipped, 36 deselected in 221.99s
      FAILED tests/test_stage0_addendum.py::test_committed_sheet_is_byte_identical_to_the_generator[humble]
      FAILED tests/test_stage0_addendum.py::test_committed_sheet_is_byte_identical_to_the_generator[jazzy]
RESULT: FAIL — 2 hard gate(s) red: ruff, default-suite
```

Both attributed, honestly:

* the **two suite failures were mine and self-inflicted by a race with my own
  edit** — the gate's `default-suite` ran while I was correcting a provenance
  line reference (`record.py:271-272` → the actual `273-274`) in the generator,
  i.e. the committed sheets were momentarily one regeneration behind the code.
  That is exactly what the pin exists to catch, and it caught it. Regenerated
  and re-run;
* the **two ruff violations were `tests/test_orin_rehearsal.py`**, another
  in-flight card's file. I did not touch it; by the second run they were gone.

```
$ .parcel/bin/python scripts/ci_gate.py --tier commit          # 2026-08-14T21:44:46Z
[  PASS] HARD  ruff                       7 violation(s), baseline 7, new 0
[  PASS] HARD  hard-safety                collisions=0 false_arrival=0 | mutation panel clean | follow-bench 7 rows all 0
[  PASS] HARD  frozen-digest-sentinels    4 immutable manifest(s) byte-identical to pin
[  PASS] HARD  latency-tail-ledger        6 metric series within 1.2x tail ceiling
[  PASS] HARD  follow-bench-jerk-ratchet  1.2187 <= 1.46244
[  PASS] HARD  model-off-non-inferiority  23 passed
[  PASS] HARD  frozen-digest-integrity    6 passed
[  PASS] HARD  mutation-panel-freshness   2 passed
[  PASS] HARD  latency-tail               6 passed
[  PASS] HARD  default-suite              5286 passed, 9 skipped, 36 deselected in 222.72s
RESULT: PASS — every hard gate green.
  elapsed 234.5s
```

**RESULT: PASS — every hard gate green.**

Nothing was armed. No publisher, no `ControlManager`, no lease, no motion
client, no vendor SDK; `.parcel/` is untouched. The sandbox work ran under
`bwrap --unshare-net --unshare-pid` against a read-only rootfs already in the
repo, created no ROS node except the one `ros2 bag record` invocation that
refused on an existing output folder before recording, published no topic, and
wrote only into a scratch bind mount. No `git commit`, `git stash` or
`git checkout` was run.
