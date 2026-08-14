# PS-P — the two document defects that would mislead the operator

**Card:** PS-P, FIX tranche PS-3 · **Date:** 2026-08-13 · **Executor:** Opus
**Owns:** [`BANDWIDTH_BUDGET.md`](BANDWIDTH_BUDGET.md),
[`session/TONIGHT_CHECKLIST.md`](session/TONIGHT_CHECKLIST.md),
`scripts/parcel_capture/budget.py` (**generation only**, not the load model)
**New tests:** `tests/test_bandwidth_budget_doc.py` (16),
`tests/test_tonight_checklist_drivers.py` (33)

---

## Per-finding table

| # | Finding | Reproduced | Fixed | Regression test | Fails on old behaviour? |
|---|---|---|---|---|---|
| **F1** | `BANDWIDTH_BUDGET.md` stale by 8.6%; doc 84.60 / 297.4 / 342.1 / 114.1 vs code 91.870 / 322.98 / 371.5 / 123.9 | **YES** — §A below, command + output | **YES** — document is now **generated** from `budget.py::render_document()` | `tests/test_bandwidth_budget_doc.py` — 16 tests | **YES** — 10/16 fail on the pre-fix file, incl. the headline test with `Obtained: 84.6 / Expected: 91.86985111236572` |
| **F1b** | *sanity-check the decision the doc drives:* does 848×480 all-streams fit under rosbag2's ~110–120 MB/s ceiling? | **Computed:** 91.87 MiB/s = **96.3 MB/s**, margin **×1.14** on the low reading | **YES** — new §2 *"Does the plan of record actually fit?"* + a costed drop ladder | `test_the_plan_of_record_is_classified_thin_and_the_document_says_so`, `test_the_drop_ladder_states_a_cost_and_a_saving_for_every_rung`, +3 more | **YES** — the pre-fix doc had no ceiling analysis at all |
| **F2** | `TONIGHT_CHECKLIST.md` never installs or rehearses the ROS driver nodes that most of the byte budget depends on | **YES** — §B below, full install inventory enumerated | **YES** — 5 new steps: **N0b, N2e, N4f, N5b, N6f** | `tests/test_tonight_checklist_drivers.py` — 33 tests | **YES** — 29/31 fail on the pre-fix sheet (the 2 that pass are an arming guard and a derivation guardrail) |
| **F2b** | *last-reader pass:* does every step produce what the next consumes? | **YES** — 4 real chain defects found, §D below | **YES** — all 4 | `test_no_shell_block_uses_a_variable_it_never_assigns`, `test_the_recording_steps_use_the_target_path_n0_and_n3_established`, `test_the_l2_step_declares_its_dependency_on_the_later_network_step`, `test_the_rehearsal_publisher_sources_ros_before_importing_rclpy`, `test_the_step_that_writes_into_tonight_creates_the_directory` | **3 of 5 yes**; 2 guard defects I introduced myself — stated honestly in §D |

---

## A. Finding 1 — reproduced

```
$ .parcel/bin/python -m scripts.parcel_capture.budget --profile 848x480@30 --duration 3600
...
TOTAL                          2017                        91.870    322.98

payload 91.265 MiB/s + framing 0.604 MiB/s (0.7% of the total)
required for 3600 s: 398,816,636,940 bytes (371.5 GiB, PS-D --required-free-gib)

$ .parcel/bin/python -c "... build_budget(D455Profile(848,480,30), session_duration_s=1200).required_free_gib()"
20min required_free_gib 123.9
1h   required_free_gib 371.5
```

Against the committed document at that moment (`BANDWIDTH_BUDGET.md:60,202,219-221`):
**84.60 / 297.4 / 342.1 / 114.1**. Confirmed stale on all four. Drift on the
headline: `(91.870 - 84.604) / 84.604 = 8.59%`.

**The delta decomposes exactly**, which is what proves it was staleness and not
disagreement:

| Cause | MiB/s |
|---|---:|
| `go2.front_camera` 0.486 → 6.585 (PS-H: JPEG-per-frame, not 4 Mb/s H.264) | **+6.099** |
| Five channels PS-H added (`cloud_deskewed`, `robot_odom`, `uwbstate`, `lidar_state`, `switch`) + the new `front_camera_h264` row | **+1.167** |
| **Total** | **+7.266** ⇒ 84.604 → 91.870 ✓ |

## Finding 1 — fixed, structurally

Hand-editing four numbers would have gone stale again, so the document is now a
**build artefact**:

- `scripts/parcel_capture/budget.py` gains a *generation* section —
  `render_document()`, `document_path()`, `recorder_verdict()`, `DROP_LADDER`,
  `_fmt_*` helpers, and CLI flags `--emit-doc` / `--check-doc`. **No load model
  moved**: no rate, no payload size, no basis, no `D455Profile`, no
  `static_loads()` entry was touched. Diff is purely additive.
- `BANDWIDTH_BUDGET.md` is now rendered (407 lines, 23,194 bytes,
  sha256 `66ee7c6a…`) and carries a `⚠ GENERATED FILE — do not hand-edit` banner.
- §0's unknowns table is rendered **from `budget.UNKNOWNS`**, so module and
  document cannot drift there either.
- Precedent followed: `scripts/ci_gate.py:DIGEST_SENTINELS`. One deliberate
  difference — a frozen digest pins bytes to a **constant**; this pins bytes to
  **what the code computes**, which is the property that actually failed.

```
$ .parcel/bin/python -m scripts.parcel_capture.budget --emit-doc
wrote /home/jaewoo-jang/Desktop/Projects/Parcel/scrum/20260813/task_1/BANDWIDTH_BUDGET.md (23,194 bytes)
$ .parcel/bin/python -m scripts.parcel_capture.budget --check-doc
FRESH: .../BANDWIDTH_BUDGET.md equals budget.py::render_document()
```

### The real numbers, every profile (measured output of `--emit-doc`)

| D455 profile | rig MiB/s | rig GiB/hour | rig MB/s | D455 USB Mb/s | vs rosbag2 ceiling | vs USB ceiling | reserve 1 h (GiB) |
|---|---:|---:|---:|---:|---|---|---:|
| 1280x720@30 CD | 142.17 | 499.8 | 149.1 | 1106 | OVER both readings (x0.74) | under | 574.8 |
| 1280x720@30 CDI | 194.92 | 685.3 | 204.4 | 1548 | OVER both readings (x0.54) | **OVER** | 788.1 |
| 1280x720@15 CDI | 102.62 | 360.8 | 107.6 | 774 | THIN (x1.02) | under | 414.9 |
| 848x480@60 CDI | 173.43 | 609.7 | 181.8 | 1368 | OVER both readings (x0.60) | **OVER** | 701.2 |
| 848x480@30 CD | 68.56 | 241.0 | 71.9 | 488 | FITS (x1.53) | under | 277.2 |
| **848x480@30 CDI** | **91.87** | **323.0** | 96.3 | 684 | **THIN (x1.14)** | under | 371.5 |
| 848x480@15 CDI | 51.09 | 179.6 | 53.6 | 342 | FITS (x2.05) | under | 206.6 |
| 848x480@30 DI | 56.92 | 200.1 | 59.7 | 391 | FITS (x1.84) | under | 230.2 |
| 640x480@30 CDI | 71.87 | 252.7 | 75.4 | 516 | FITS (x1.46) | under | 290.6 |
| 424x240@30 CDI | 30.73 | 108.0 | 32.2 | 171 | FITS (x3.41) | under | 124.3 |

Twenty-minute reserve at the plan of record: **123.9 GiB** (was 114.1).

### F1b — the ceiling question, answered

**848×480@30 C+D+IR offers 96.3 MB/s against a 110–120 MB/s recorder ceiling:
×1.14, i.e. ~14% headroom, and the ceiling is somebody else's x86 field report.
An Orin NX is the weaker machine.** The document now says exactly that, in the
operator's language, and adds: *"Until N4 comes back green, treat this profile as
a hypothesis."*

USB is **not** binding at 848×480 (684 Mb/s of 1200). It **is** binding at 720p
all-streams (1548 Mb/s) — two independent ceilings, both below the 720p ask.

Three rows are named in prose as **not recordable**: `1280x720@30 CD`,
`1280x720@30 CDI`, `848x480@60 CDI`. `1280x720@15 CDI` clears by ×1.02, which the
document calls *"not a margin, a coin toss"*.

**Drop ladder — which streams to drop first and what each costs** (rung 1 first,
rungs 2–4 are alternatives on top of it):

| # | Drop | rig MiB/s | rig MB/s | saved | ceiling |
|---|---|---:|---:|---:|---|
| 1 | Front camera JPEG off (H.264 path only) | 85.29 | 89.4 | 6.58 | THIN (x1.23) |
| 2 | …and the IR pair off (848x480@30 C+D) | 61.98 | 65.0 | 29.89 | FITS (x1.69) |
| 3 | …or keep IR and halve the rate (848x480@15 C+D+IR) | 44.51 | 46.7 | 47.36 | FITS (x2.36) |
| 4 | …colour off, IR kept (848x480@30 D+IR) | 50.34 | 52.8 | 41.53 | FITS (x2.08) |

Rung 1 is first because it is the **only rung that removes no unique sensing
modality** — the D455 already looks forward. Each rung's cost is written out in
the document and asserted present by
`test_the_drop_ladder_states_a_cost_and_a_saving_for_every_rung`.

### F1 — proof the regression test fails on the old behaviour

Pre-fix file restored from `…/scratchpad/psp/BANDWIDTH_BUDGET.prefix.md`
(sha256 `748358f2…`), tests re-run, then the generated file restored and
`--check-doc` re-verified FRESH:

```
$ .parcel/bin/python -m pytest tests/test_bandwidth_budget_doc.py -q     # PRE-FIX doc in place
10 failed, 6 passed in 0.66s
FAILED ...::test_committed_document_is_byte_identical_to_the_generator
FAILED ...::test_the_document_announces_that_it_is_generated
FAILED ...::test_headline_numbers_in_the_document_are_the_ones_the_code_computes
FAILED ...::test_no_stale_headline_survives_anywhere_in_the_document
FAILED ...::test_a_model_change_reddens_the_freshness_check
FAILED ...::test_every_profile_row_carries_a_recorder_ceiling_verdict
FAILED ...::test_the_plan_of_record_is_classified_thin_and_the_document_says_so
FAILED ...::test_the_over_ceiling_profiles_are_named_as_unrecordable
FAILED ...::test_the_drop_ladder_states_a_cost_and_a_saving_for_every_rung
FAILED ...::test_unknowns_table_is_rendered_from_the_module_not_transcribed
```

The load-bearing one, with the finding's own numbers:

```
$ .parcel/bin/python -m pytest ".../test_headline_numbers_in_the_document_are_the_ones_the_code_computes" -q
E         Obtained: 84.6
E         Expected: 91.86985111236572 ± 0.005
```

The markdown parser was deliberately made tolerant of **both** label spellings
(`848x480@30 CDI` and `848×480@30 C+D+IR`) so that this failure is a **numeric**
mismatch rather than a cosmetic parse error. Post-fix: `16 passed`.

Three independent layers, so a green result means something:
1. whole-file byte equality against `render_document()`;
2. the four headline numbers parsed back **out of the markdown** and compared to
   `build_budget()` — a check that read the model twice would have passed while
   the sheet was wrong;
3. a **seeded model change** (`ASSUMED_FRONT_CAMERA_JPEG_BYTES` 208,896 → 16,666,
   i.e. PS-H's correction reversed) must move the render — otherwise layer 1
   could be green because nothing is being compared.

Plus `--check-doc` **fails closed**: a missing document exits 3 with `STALE`,
never "fresh".

---

## B. Finding 2 — reproduced

```
$ grep -n "apt-get install\|pip install\|git clone" .../TONIGHT_CHECKLIST.md
402:python3 -m pip install --user pyrealsense2
556:sudo apt-get install -y librealsense2-utils   # may not exist for aarch64
622:sudo apt-get install -y fio
695:sudo apt-get install -y ros-humble-rosbag2-storage-mcap
900:sudo apt-get install -y cmake build-essential git
901:cd ~ && git clone https://github.com/unitreerobotics/unilidar_sdk2.git

$ grep -c "realsense2_camera\|realsense2-camera\|unitree_ros2\|unitree_go\|ros2 launch" .../TONIGHT_CHECKLIST.md
1        # and that one hit is `unilidar_sdk2` in prose, not a driver
```

**Confirmed exactly as stated.** No `realsense2_camera`, no `unitree_ros2`, no
L2 ROS node, no `ros2 launch` of anything, anywhere on the sheet. `N5` clones
`unilidar_sdk2` and builds the **plain-CMake SDK example**, which prints to a
terminal and publishes no topic.

The refuters' `realsense.py:3-8` citation verified at source
(`scripts/parcel_capture/ingest/realsense.py:3-8`):

> The D455 is not on a DDS topic. Its bytes reach the Orin over USB3 through
> `pyrealsense2`, and **for the session the primary path is the
> `realsense2_camera` ROS node feeding `ros2 bag record -s mcap`.** This adapter
> is the preflight/attestation path.

### The share of the budget at stake — measured, not asserted

```
$ .parcel/bin/python -c "<sum budget rows by device prefix>"
d455 (realsense2_camera)          89.01%    81.773 MiB/s
l2 (unitree_lidar_ros2)            0.80%     0.737 MiB/s
go2 (unitree_ros2 msgs)           10.17%     9.344 MiB/s
no-ROS                             0.02%     0.016 MiB/s
driver_node total (d455+l2)       89.81%
TOTAL                              91.870 MiB/s
```

The finding said 94%; the precise figure for *driver-node* topics is **89.8%**,
and **99.98%** of the budget needs *some* ROS package that the sheet never
installed. Both numbers are now in the checklist and both are re-derived by
`test_the_driver_dependent_share_of_the_budget_is_what_the_sheet_claims`, so the
callout cannot go stale the way §1 did.

## Finding 2 — fixed

Five new steps, keeping the existing five-part structure (**WHY · COMMAND ·
EXPECTED · RECORD · STOP/BRANCH**) and the cheapest-disconfirming-first ordering.
No existing step was renumbered, so every cross-reference from
`TAKE_SCRIPT.md`, `STAGE0_RUN_SHEET.md` and `PSG_STATUS.md` (`N4b`, `N4e`, `N6`,
`N2c`, `N4`) still resolves.

| Step | What it adds | Install | Launch | Verify |
|---|---|---|---|---|
| **N0b** | Driver-package availability probe. 60 s, read-only, **cheapest disconfirming check on the sheet** | — (`apt-cache policy` ×4) | — | `ros2 interface list`, `ros2 pkg list` |
| **N2e** | `realsense2_camera` — the D455's actual session path (89.0% of bytes) | `apt-get install ros-$ROSD-realsense2-camera realsense2-camera-msgs` | `ros2 launch realsense2_camera rs_launch.py …` at the session profile, **with `unite_imu_method`** | `ros2 topic hz -w 100` on all six `DRIVER_TOPICS` |
| **N4f** | Records the **real** driver topics through the same `ros2 bag record` line | — | uses N2e/N5b | `ros2 topic list` → build the record list from what exists → `ros2 bag info` |
| **N5b** | L2 **ROS node** from `unilidar_sdk2`'s colcon workspace (0.8%) | `apt-get install python3-colcon-common-extensions`; `colcon build` | `ros2 launch unitree_lidar_ros2 launch.py` | `ros2 topic hz` on `/unilidar/cloud`, `/unilidar/imu` |
| **N6f** | `unitree_ros2` message packages + RMW/DDS (10.2%) | `git clone unitree_ros2`; `colcon build --packages-select unitree_go unitree_api` | (no node — the dog publishes) | `ros2 interface show unitree_go/msg/LowState` etc. |

Design decisions worth the auditor's attention:

1. **Every topic name and launch command is derived from
   `scripts/parcel_capture/rosbag2.py`'s `DRIVER_TOPICS`**, which already carried
   both and which nothing had ever used. The tests are parametrised over that
   table, so a driver topic added there becomes a topic the checklist must
   rehearse. That is the anti-rot property; a literal list would rot.
2. **The topic names are marked [EXT]/UNVERIFIED in the sheet**, quoting
   `rosbag2.py:222-228`: a recorder given a wrong name *"simply never
   subscribes"* — silent. Every step tells the operator that
   `ros2 topic list`'s output supersedes the sheet.
3. **`unite_imu_method` is called out as load-bearing** (`rosbag2.py:322-329`):
   without it the D455 IMU topics do not appear at all, silently.
4. **The two D455 paths are mutually exclusive at the device** — one USB node,
   one holder. N2a–d (`pyrealsense2`) and N2e (ROS driver) cannot run together.
   The sheet says so with a `pkill` / `lsof` recovery, because otherwise this
   presents as a phantom driver failure at midnight.
5. **N6f is a build + IDL check, not a robot test.** It also settles, *without
   the dog*, five of `CHANNEL_MATRIX.md`'s documentation-derived claims (both
   foot-force arrays, `power_v`/`power_a`, `wireless_remote[40]`,
   `range_obstacle[4]`, and that `LowState` carries no timestamp) — a free
   result the sheet now harvests.
6. **Nothing arms anything.** The new steps launch sensor drivers and build
   *interface* packages. `test_the_sheet_still_arms_nothing` scans the sheet's
   **code blocks** (prose must be free to name what it forbids) for
   `unitree_sdk2py`, `ControlManager`, `sport_client`, `SportClient`,
   `MotionSwitcher`, and asserts every `ros2 topic pub` is scoped to `/tonight/`.

### F2 — proof the regression tests fail on the old behaviour

```
$ .parcel/bin/python -m pytest tests/test_tonight_checklist_drivers.py -q   # PRE-FIX sheet in place
29 failed, 2 passed in 0.17s
```

Failures include all 8 `test_every_driver_topic_is_named_in_the_checklist[…]`,
all 6 `test_every_driver_launch_command_appears_in_the_checklist[…]`,
`test_the_realsense_ros_driver_is_installed_not_just_the_pip_module`,
`test_the_unitree_message_packages_are_built_and_inspected`,
`test_driver_topics_are_verified_with_topic_hz`,
`test_the_real_driver_topics_are_recorded_through_rosbag2`, and the four
artifact-chain tests. The 2 that pass are
`test_the_sheet_still_arms_nothing` (correctly — the old sheet armed nothing
either) and `test_driver_topics_is_not_empty_and_is_the_thing_being_derived_from`
(a guardrail proving the parametrisation is not vacuous).

Post-fix: `33 passed`. Checklist restored byte-identically after each swap
(sha256 `4cf0503f…` before and after).

---

## C. Stale numbers propagated *out of* the budget doc, also fixed

The checklist was quoting the stale figures **and** citing the budget document by
line number — the same coupling that made the original defect invisible.

| Where | Was | Now |
|---|---|---|
| N0 free-space branch | `BANDWIDTH_BUDGET.md:219-220` … **114.1 GiB** | §4 … **123.9 GiB**, threshold moved 115 → 125 GiB |
| N3 WHY | `:60` … **84.60 MiB/s**; `:242-247` … 3,778 MiB/s | §1 … **91.87 MiB/s (96.3 MB/s)**; §5 … 3,769 MiB/s |
| N3 STOP/BRANCH thresholds | ≥169 / 85–169 / <85 MiB/s | **≥184 / 92–184 / <92 MiB/s**, and the ladder reference is now §2 |
| N3 `--size` for SLC exhaustion | `--size=120G` (114.1 GiB) | `--size=130G` (123.9 GiB) |
| N2c GO branch | `:60,95` | §1, plus *"then N2e"* |
| N2c fail ladder | `:115-117` | §2's costed drop ladder |
| N4c rehearsal target | *"Total ≈ 84.4 MiB/s against the budget's 84.60"* | **≈90.9 MiB/s against 91.87**, with the ~1 MiB/s shortfall named as the un-synthesised small DDS channels |
| §4 does-not-prove | `:265-272`, `:219-220` | §5, §0, plus the point that §5 measured **`parcel-capture`, not `ros2 bag record`** |

**Every `BANDWIDTH_BUDGET.md:NNN` citation in the checklist is now a `§N`
citation.** The sheet's own §0.7 already said a line number into a moving file
*"looks precise and points at the wrong thing"*; it was doing it anyway.

The only two surviving mentions of `84.60` are deliberate historical notes
explaining the correction, and
`test_no_stale_headline_survives_anywhere_in_the_document` confines the budget
document's own recitation to its "why this file is generated" block.

---

## D. Last-reader pass — four real artifact-chain defects found and fixed

Ran a static audit over every fenced shell block: files written vs files read,
and shell variables used vs assigned per block (each block is pasted into a
**fresh terminal**).

| # | Defect | Consequence at midnight | Fix | Test | Pre-existing? |
|---|---|---|---|---|---|
| D1 | **N5 consumes an artifact N6 produces.** `ping 192.168.1.2` needs the `192.168.1.1/24` address N6b assigns, and N6 is *after* N5 | Reads as a dead LiDAR; sends the operator into the SDK build | Prominent `⚠ ORDERING` block: do N6a+N6b first, with its own RECORD line | `test_the_l2_step_declares_its_dependency_on_the_later_network_step` | **YES** |
| D2 | **N4c's publisher imports `rclpy` and the block never sources ROS.** N4d's block does; N4c's does not | `ModuleNotFoundError` on line 1 of the ten-minute rehearsal | `source /opt/ros/humble/setup.bash` added to N4c's terminal-1 block | `test_the_rehearsal_publisher_sources_ros_before_importing_rclpy` | **YES** |
| D3 | **N3 measures `$TARGET`; N4 hard-codes `/data`.** If the record destination is not `/data`, the two steps measure different disks | N3's go/no-go threshold is about a volume the recorder never writes to | N4d/N4e/N4f all bind `TARGET=` and use it | `test_the_recording_steps_use_the_target_path_n0_and_n3_established` | **YES** |
| D4 | **N4e used `$TARGET` with no assignment** in its own block | `ros2 bag info /tonight_n4` → "bag not found" | `TARGET=` added to N4e's block | `test_no_shell_block_uses_a_variable_it_never_assigns` | **NO — I introduced it in D3's fix and the static audit caught it** |
| D5 | N4f writes `~/tonight/n4f_topics.txt`; only PRE-3 creates `~/tonight` | Redirect failure if the sheet is run out of order | `mkdir -p ~/tonight` in N4f | `test_the_step_that_writes_into_tonight_creates_the_directory` | **NO — introduced by my own new step** |

Also fixed, non-chain:
- **N0 never recorded the Orin's IP**, which **N7a's `rsync … <orin_ip>`** needs.
  Added `hostname -I` + a RECORD line.
- **N4e expected "five `/tonight/*` topics"**; the rehearsal now publishes six.
- Results ledger and hand-off table gained rows for all five new steps
  (`test_every_new_step_has_a_row_in_the_results_ledger`,
  `test_every_new_step_hands_something_into_tomorrow`).

### D6 — the hand-off has nowhere to land, and it is not mine to fix

**`STAGE0_RUN_SHEET.md` §3 is a six-row transcription table — T1 preflight, T2
budget, T3 clock map, T4 record, T5 sidecar, T6 rehearsal — and every row is a
`scripts/parcel_capture/` command. There is no row for a `ros2 launch` and no row
for `ros2 bag record`.** But `ros2 bag record -s mcap` is the recorder of record
(`RISK_ASSESSMENT.md:39-45`), and it records nothing without the two driver
launches and the `unitree_ros2` overlay.

That file is **PS-F's OWNS**. I did not edit it. The checklist now carries a
boxed warning naming the four rows §3 needs (T7 realsense launch, T8 L2 launch,
T9 overlay source, T10 `ros2 bag record`) and an interim instruction to
transcribe into §10 free text plus a sheet taped to the Orin. **This is a real
residual and it needs an owner.**

---

## E. Measurements I executed

| # | Claim | Command | Output |
|---|---|---|---|
| M1 | Budget headline at the plan of record | `.parcel/bin/python -m scripts.parcel_capture.budget --profile 848x480@30 --duration 3600` | `TOTAL 2017 … 91.870 322.98`; `required … 371.5 GiB` |
| M2 | Twenty-minute reserve | `build_budget(D455Profile(848,480,30), session_duration_s=1200).required_free_gib()` | `123.9` |
| M3 | Dev-host sustained write | `measure_sustained_write('/home/jaewoo-jang/.cache/parcel-psp', total_bytes=32*1024**3, block_bytes=4*1024*1024, fsync_interval_s=1.0)` | 34,359,738,368 B in 8.693122 s, 9 fsync ⇒ **3,769.4 MiB/s**, ext4 — **dev-host** |
| M4 | Whole-stack throughput, 848×480@30 CDI | `rehearse.measure_stack_throughput(D455Profile(848,480,30), …)` | **1,213.4 MiB/s** at 26,586 msg/s — **dev-host** |
| M5 | Whole-stack throughput, 1280×720@30 CDI | same, 720p | **1,373.3 MiB/s** at 14,197 msg/s — **dev-host** |
| M6 | Render is byte-stable | `render_document() == render_document()` | `True`, 22,998 → 23,194 B after the ladder-prose fix |
| M7 | Document is fresh | `--check-doc` | `FRESH: … equals budget.py::render_document()` |
| M8 | Driver share of the budget | row sums by device prefix | 89.01% / 0.80% / 10.17% / 0.02%, sums to total ✓ |
| M9 | PS-P test suites | `pytest tests/test_bandwidth_budget_doc.py tests/test_tonight_checklist_drivers.py -q` | **49 passed** |
| M10 | Sibling capture suites unbroken | `pytest tests/test_capture_rehearsal.py tests/test_capture_envelope.py tests/test_capture_sidecar.py tests/test_capture_preflight.py -q` | **475 passed** |
| M11 | Full offline suite | `pytest -q -m "not slow"` | **5003 passed, 9 skipped, 36 deselected** in 218 s |
| M12 | Ruff on PS-P's files | `ruff check tests/test_bandwidth_budget_doc.py tests/test_tonight_checklist_drivers.py scripts/parcel_capture/budget.py` | `All checks passed!` |

M3/M4/M5 replace PS-E's recorded figures with ones I executed today; they are
carried in `budget.py` as `DEV_HOST_WRITE` / `DEV_HOST_STACK` constants so the
render stays byte-stable, and every one is labelled *dev-host, to be re-measured
on the Orin*.

---

## F. Concurrency incident — my edits to `budget.py` were reverted mid-card

At 09:02 a concurrent card restored `scripts/parcel_capture/budget.py` to its
pre-PS-P bytes, silently discarding the generator I had just applied (the
tranche's mutation-harness rule is *snapshot → mutate → restore byte-identically*;
a snapshot taken before my edit and restored after removes it).

Mitigation, and it should probably be a tranche-wide habit: the whole patch lives
as an **idempotent applier** at
`…/scratchpad/psp/apply.py` + `gen_block.py`. It checks for
`def render_document()` and re-grafts the block onto four exact anchors, or
refuses with `ANCHOR MISS`. Re-verified after every subsequent step:

```
$ grep -c "def render_document" scripts/parcel_capture/budget.py
1
$ .parcel/bin/python -m scripts.parcel_capture.budget --check-doc
FRESH: …
```

**Auditor: re-run `--check-doc` at land time.** If another card restores
`budget.py` again the document and the code drift apart, and
`test_bandwidth_budget_doc.py` will redden — which is the sentinel doing its job,
but it needs the applier re-run rather than the document re-edited.

---

## G. ci_gate

Final run, 2026-08-13T14:01:02Z:

```
$ cd /home/jaewoo-jang/Desktop/Projects/Parcel && .parcel/bin/python scripts/ci_gate.py --tier commit
[  FAIL] HARD  ruff                       12 violation(s), baseline 7, new 5 -> scripts/parcel_capture/ingest/__init__.py::F821; scripts/parcel_capture/preflight.py::RUF100; tests/test_capture_ingest.py::B009; tests/test_capture_ingest.py::I001; tests/test_capture_ingest.py::RUF100
[  PASS] HARD  hard-safety                nav frozen baseline …: collisions=0 false_arrival=0 | mutation panel clean | follow-bench 7 rows, all 0 | walk_with_me all 0
[  PASS] HARD  frozen-digest-sentinels    4 immutable manifest(s) byte-identical to pin
[  PASS] HARD  latency-tail-ledger        6 metric series within 1.2x tail ceiling
[  PASS] HARD  follow-bench-jerk-ratchet  1.2187 <= 1.46244
[  PASS] HARD  model-off-non-inferiority  23 passed in 0.48s
[  PASS] HARD  frozen-digest-integrity    6 passed, 1 warning in 0.43s
[  PASS] HARD  mutation-panel-freshness   2 passed, 3 warnings in 4.34s
[  PASS] HARD  latency-tail               6 passed, 2 warnings in 0.38s
[  PASS] HARD  default-suite              5049 passed, 9 skipped, 36 deselected, 5 warnings in 221.71s
==============================================================================
RESULT: FAIL — 1 hard gate(s) red: ruff
  elapsed 233.9s
```

`default-suite` went 5002 → **5049**, i.e. PS-P's 49 new tests, all green.

**The red gate is not PS-P's.** Attribution, measured against
`scripts/ci_ruff_baseline.json`:

```
BASELINE: 7
NEW (not in baseline):
   scripts/parcel_capture/ingest/__init__.py::F821      # Undefined name `Any`
   scripts/parcel_capture/preflight.py::RUF100
   tests/test_capture_ingest.py::I001 / RUF100 / B009
```

All five are in `scripts/parcel_capture/ingest/**`,
`scripts/parcel_capture/preflight.py` and `tests/test_capture_ingest.py` —
**PS-G's ingest card, landing concurrently and still moving between my two gate
runs** (three new fingerprints appeared in `test_capture_ingest.py` in the eight
minutes between them). mtimes: `ingest/__init__.py` 09:48,
`test_capture_ingest.py` 09:50, `preflight.py` 09:53, against runs at 09:52 and
10:01. `F821 Undefined name 'Any'` at
`scripts/parcel_capture/ingest/__init__.py:120` is a genuine missing-import bug in
that card's file; I did not touch it, because the last time two cards wrote the
same file in this tranche one of them lost its work (§F).

Every other hard gate is green.

**PS-P's own files are ruff-clean** (M12). The full RESULT line and the
attribution are given here rather than a green claim, per board rule 5.

---

## does_not_prove

1. **A generated document is not a correct document.** The freshness gate proves
   `BANDWIDTH_BUDGET.md` equals `budget.py`. It says nothing about whether the
   load model is right — and the model's largest assumption, the front camera's
   204 KiB JPEG frame, is `assumed_worst_case` and can move the headline by more
   than 10% on its own. `CHANNEL_MATRIX.md` open question 4 (does
   `Go2FrontVideoData_` populate one resolution or all three?) *is* that factor,
   and it is unresolved.
2. **The rosbag2 ceiling in §2 is not our measurement.** 110–120 MB/s is a band
   of field reports from other people's x86 machines. The ×1.14 verdict is a
   classification, not a permission, and nobody has measured `ros2 bag record` on
   an Orin NX — or on any of our hardware. The new N4f is 60 seconds long and is
   the only local reading that will ever exist before the session.
3. **The USB figure excludes the motion streams and assumes uncompressed
   frames.** It is `pixels × bpp × fps × 8`, nothing else. Real USB overhead,
   packet framing and controller contention are not modelled.
4. **Nothing in the checklist has been executed.** Every command in N0b, N2e,
   N4f, N5b and N6f is `[UNVERIFIED-SYNTAX]` and could not be run: this box has
   no ROS, no Jetson, no RealSense, no D455 and no L2. The apt package names, the
   `rs_launch.py` profile-argument spelling, the `unilidar_sdk2` workspace layout
   and the `unitree_ros2` build steps are all documentation-derived. The tests
   assert the sheet **contains** the right steps; they cannot assert the steps
   **work**.
5. **The driver topic names are guesses and the sheet says so.** They come from
   `rosbag2.py`'s own `Confidence.UNVERIFIED` rows. A wrong name is the silent
   failure mode this whole finding is about, and the only defence shipped is
   telling the operator to trust `ros2 topic list` over the sheet.
6. **My tests are text assertions over a markdown file.** `"ros2 topic hz" in
   window` proves a string is present within 4 KB of a topic name. It does not
   prove the step is correct, ordered sensibly, or runnable. A determined
   rewrite could satisfy every one of these tests and still be a bad checklist.
7. **The 89.0% / 0.8% / 10.2% split is model-derived, not measured**, and rests
   on the same front-camera assumption as (1). The finding said 94%; my figure
   for driver-node topics is 89.8%. I did not reconcile the difference with the
   refuters — I recomputed from the model and reported what it says.
8. **Two of the five artifact-chain defects (D4, D5) were introduced by my own
   fixes** and caught by my own static audit. That is an argument for the audit,
   not for the fixes. I do not claim the sheet is now defect-free; I claim five
   specific defects are gone and five specific tests will catch their return.
9. **The `--check-doc` sentinel is not wired into `ci_gate.py`.** It runs as a
   pytest in the default suite, which is enough for the commit tier, but
   `scripts/ci_gate.py` is not PS-P's OWNS and gained no explicit doc-freshness
   gate. If the default suite is ever narrowed, the sentinel goes with it.
10. **`STAGE0_RUN_SHEET.md` §3 still has no row for the recorder of record**
    (§D6). The checklist warns about it loudly; nothing enforces it, and the
    warning is prose an operator can skip at 08:55.
11. **The measurements in §5 of the budget document are `parcel-capture`, not
    `ros2 bag record`.** They are honest about it now, but it means the repo has
    zero throughput data about the recorder it has decided to use.
12. **`ci_gate --tier commit` is RED** (§G). I have attributed the failure to
    another card's in-flight files and shown my own are clean, but the tranche
    does not close on this card's evidence alone.
