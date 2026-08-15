# ORIN_RUNBOOK — the one command, and what it proves

> ## GENERATED FILE — do not hand-edit
>
> Rendered by `scripts/parcel_capture/orin_rehearsal.py::render_runbook()` from the harness's own phase table.
> Hand-editing is a defect: `tests/test_orin_rehearsal.py` reddens until it is reverted.
>
> ```
> .parcel/bin/python -m scripts.parcel_capture.orin_rehearsal --emit-runbook
> ```

**Card:** OR-1 (board [REVISED_BOARD.md](REVISED_BOARD.md) H-2, software half) · **Harness version:** `or1.1`

## 0 · Before anything: what this is

This harness is the **only** way our capture stack is allowed to meet the Orin for the first time. Not a shell history, not a paste from a status doc — this, because it fails closed, records raw output, and leaves an evidence bundle somebody else can audit.

It is **sensor-only**. No process it starts can command motion, in any form. It launches vendor sensor drivers and it subscribes; that is the whole of its physical authority.

## 1 · Get the repository onto the Orin

```bash
# ON THE DEV BOX
rsync -av --exclude '.parcel/' --exclude '__pycache__/' --exclude '.git/' \
  /home/jaewoo-jang/Desktop/Projects/Parcel/ <orin_user>@<orin_ip>:~/Parcel/
```

`--exclude '.parcel/'` is **not optional**. That venv is an x86 3.14 venv, it is meaningless on aarch64, and its emptiness of any vendor motion SDK is the project's strongest motion guarantee. It has no business on the robot host.

**No vendor SDK is ever installed into any Parcel venv.** `pyrealsense2`, `unilidar_sdk2` and the ROS driver packages are installed on the Orin, into the system or a venv **on the Orin**, exactly as the no-dog checklist says.

## 2 · The one command

```bash
# ON THE ORIN, from ~/Parcel
source /opt/ros/<the distro P0 reports>/setup.bash    # if there is one
python3 -m scripts.parcel_capture.orin_rehearsal \
  --evidence-dir ~/orin_evidence \
  --record-target /data                              # the REAL record destination
```

`$HOME` must be WRITABLE for the user running this. `ros2 bag record` opens its log under `$HOME/.ros/log` before it records a byte, and on a read-only home it exits with `Failed opening file … Read-only file system` and P5 reads *the recorder wrote nothing*. Measured, not assumed: that is exactly how P5 fails inside the repository's read-only ROS 2 sandbox until `HOME` is pointed at the writable bind.

Useful flags, and none of them is required:

| Flag | What it changes |
|---|---|
| `--full` | The long forms: a 600s frame count instead of 60s, 40 GiB written instead of 2 GiB, 120s recorded instead of 20s. Use it once the short form is green. |
| `--until PHASE` | Stop after PHASE. Later phases are written as `SKIPPED`. It does **not** make PHASE run: if an earlier phase FAILs, PHASE is `SKIPPED` too, so pair it with `--keep-going` when you want the named phase to run regardless. |
| `--keep-going` | Run later phases even after a failure. A security refusal is never overridden by it. |
| `--firmware-attested V1.1.13` | The version **read from the Unitree app**. Required before anything may be on the robot LAN. |
| `--take-minutes N` | The take length the free-space requirement is computed for (default 20). |

## 3 · What each phase proves

| Phase | Proves | Fails when |
|---|---|---|
| `p0_identity` | what this machine is, and which ROS distro the recorder argv must target | not one identity command could be run at all |
| `p1_environment` | the USB buffer is not the 16 MB default, `import parcel_robot.capture` runs under 3.10 for the first time ever, and every required package is installed | any required item is ABSENT, or `usbfs_memory_mb` is 16 |
| `p2_storage` | the record target sustains the plan's byte rate, measured as a tail, and has the free space the generated budget requires | the tail is below the requirement, free space is short, or nothing could be measured at all |
| `p3_network` | which interfaces exist, that the host is not on the robot LAN, and that the firmware pin is honoured | the host is on `192.168.123.0/24` without an attestation at or above V1.1.13, or the attestation is below it or malformed |
| `p4_sensors` | that every CONFIGURED stream — colour, depth, both IR and the IMU — delivers what its configured rate says it should; and whether the L2 reads on a bench | the camera does not enumerate, a configured stream delivers ZERO frames (including all of them: a total loss is named as one), or a stream delivers under 90% of expectation |
| `p5_recorder` | the whole recorder path: installed `--help` -> argv rendered by `Rosbag2Plan` -> a real timed recording -> read back by our own reader -> sidecar built and verified -> preflight run | the argv carries a flag the installed recorder lacks, the bag is unreadable, the sidecar does not verify, or the support-topic reconciliation could not run at all |

Every phase writes `<evidence-dir>/<phase>.json` with the **raw stdout and stderr of every command it ran**, a `PASS`/`FAIL`/`SKIPPED` verdict, and a remedy on failure. A failed phase stops the ones after it unless `--keep-going` is passed.

## 4 · STOP rules

These are stops, not suggestions.

1. **Firmware below V1.1.13, or unknown.** Nothing joins `192.168.123.0/24`. Unknown is treated as below the pin. The harness refuses, and `--keep-going` does not override it: the pin is a security control (CVE-2026-27509 / 27510 class findings), not a preference.
2. **The Orin does not come back from a reboot.** There is no second dock and no golden image. Attach the console, restore the `extlinux.conf` backup, and wake the owner regardless of whether recovery works.
3. **P0 reports a distro that is not Humble or Jazzy.** Not a failure — a report. Do not improvise an upgrade of the only dock. The recorder retargets; that is our software problem.
4. **A stream delivers under 90%, or a configured stream delivers nothing.** Walk the drop ladder and re-run the count at each rung. Whatever profile holds is the session's profile. Zero frames on a configured stream is a LOST stream, never an unscored one: P4 names it and fails.
5. **The recorder splits, or `messages_lost` is non-zero.** Do not carry a recorder that drops the camera into a session.
6. **Anything wants to be fixed by flashing, `apt upgrade`, or editing the bootloader beyond the one documented `usbfs` argument.** Stop. The two-dock rule is unmet; the only dock is not sacrificial.

## 5 · What to bring back

The whole evidence directory. It is small, it is JSON, and it is the day's primary artifact:

```bash
# ON THE DEV BOX
rsync -av <orin_user>@<orin_ip>:~/orin_evidence/ ./orin_evidence/
```

| File | Contents |
|---|---|
| `p0_identity.json` | Read what this machine actually is, and classify its ROS distro. Raw command output included. |
| `p1_environment.json` | USB buffer, the Python 3.10 import claim, and every package the session needs. Raw command output included. |
| `p2_storage.json` | Sustained write on the record target, tail not peak, against the generated budget. Raw command output included. |
| `p3_network.json` | Interfaces, the robot-LAN not-joined check, and the firmware-pin refusal. Raw command output included. |
| `p4_sensors.json` | D455 per-stream delivered-vs-expected, and the L2 bench read. No dog. Raw command output included. |
| `p5_recorder.json` | help -> argv -> record -> read back -> sidecar -> preflight, end to end. Raw command output included. |
| `verdict.json` | Every phase's verdict, the blockers, the degradations, and a `does_not_prove` list. |
| `bench_storage_config.yaml`, `bench_bag.parcel-bag.json` | The exact storage config P5 passed, and the sidecar it built, if P5 got that far. |

The **bench bag itself stays on the record target**, at `<record-target>/parcel_rehearsal_bench_bag/` — that is deliberate. P2 measured the sustained write of the record destination, and rehearsing the recorder onto a different volume measures a different disk. With `--full` and real camera topics that bag is gibibytes; do not copy it home. `p5_recorder.json` carries its path, its per-file sha256 and its message counts.

`p0_identity.json` carries a `run_header_markdown` field: that block is the day's first recorded evidence and pastes straight into the run sheet's run header.

## 6 · What a green bundle does NOT prove

- It does not issue the readiness verdict. `READY_FOR_STATIONARY_STAGE0` / `DEGRADE_MMP_ONLY` / `NOT_READY` is recorded once, at close, by AU-F. A green bundle is evidence **for** the first; it is not the first.
- It says nothing about the dog: no phase powers it, commands it, or reads its topics.
- It says nothing about SLAM, camera-LiDAR fusion, or owner tracking.
- A bench frame count is a camera on a desk, not a camera on a walking robot.

