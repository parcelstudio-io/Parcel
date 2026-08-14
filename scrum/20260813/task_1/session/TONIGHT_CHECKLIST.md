# TONIGHT — no-dog checklist

> **Nothing in this sheet has been executed.** Every `RECORD:` field is blank by
> design and is filled **by hand, tonight, by a person at a laptop**. A sheet
> full of blanks is the correct state of this document until someone runs it.
> A blank is honest. A guess is the first false entry in the dataset.

**Card:** PS-L, tranche PS-2 · **Written:** 2026-08-13 · **Author:** Fable (PS-L)
**Filled:** the night before the first physical session
**Why this exists:** [`../RISK_ASSESSMENT.md:106-125`](../RISK_ASSESSMENT.md) —
six platform risks ranked by (probability × cost), **all resolvable tonight
without the dog**. Every one of them is a documented multi-hour failure if it is
discovered tomorrow morning instead.
**Pack:** [README.md](README.md) · [SAFETY_BRIEF.md](SAFETY_BRIEF.md) ·
[STAGE0_RUN_SHEET.md](STAGE0_RUN_SHEET.md) ·
[MOUNT_GEOMETRY_SHEET.md](MOUNT_GEOMETRY_SHEET.md) ·
[PHOTO_LIST.md](PHOTO_LIST.md)

**There is no second session.** Tomorrow's failures are permanent. Tonight's are
free.

---

## 0 · How to use this sheet

1. **Order matters. Do not reorder.** The ordering principle is
   **cheapest-disconfirming first**: N0 is five minutes and can invalidate the shape of the entire day, so
   it goes before anything that costs an hour.
2. Every step has five parts: **WHY** · **COMMAND** (literal, copy-paste) ·
   **EXPECTED** · **RECORD** (blank) · **STOP / BRANCH**.
3. **Paste the actual output**, not a summary of it. "Looked fine" is `NOT
   MEASURED`.
4. A step that cannot be run is `NOT RUN` with a reason. It is never assumed to
   have passed. **Unknown = absent.**
5. **STOP means stop.** Where a step says STOP, do not proceed to the next
   numbered step until the branch is decided and written down. Several branches
   change what tomorrow *is*, and the owner needs to know tonight, not at 09:00.
6. Provenance tags on every claim in this sheet:
   - **[REPO]** — verified in this repository at a cited `file:line`.
   - **[EXT]** — external research (docs, issue threads, field reports) via
     [`../RISK_ASSESSMENT.md`](../RISK_ASSESSMENT.md). **True of Go2/Orin/D455
     units described online; not yet true of ours.** Each is a hypothesis this
     sheet exists to settle.
   - **[UNVERIFIED-SYNTAX]** — a command whose exact flags could not be checked
     on the dev box (it has no ROS, no CUDA, no Jetson, no RealSense). Run
     `--help` first and correct the flag rather than fighting the sheet.

7. **Citations.** Stable documents are cited `file:line`. Three documents —
   `../README.md`, `../PHYSICAL_SESSION_PLAN.md`, `../CHANNEL_MATRIX.md` — and
   everything under `scripts/parcel_capture/` are being **rewritten by other
   PS-2 cards while this sheet is being written**, so they are cited by name
   and quoted text only. A line number into a moving file is worse than no
   line number: it looks precise and points at the wrong thing.

### Standing rules, unchanged

- **Nothing arms anything.** No step here publishes a robot command, creates a
  `ControlManager`, takes a lease, or constructs a motion client. The only
  topics anyone publishes tonight are under `/tonight/…`. **Never publish to any
  `rt/…` topic, tonight or ever.**
- **The dog stays off and disconnected**, except for the single app read in
  **PRE-1**. Tonight is a laptop-and-SSH night.
- **Do not install a vendor SDK into `.parcel/`.** Its absence is the strongest
  motion guarantee we have. **[REPO]** `../PSF_STATUS.md:88` measured all seven
  of `rclpy cyclonedds unitree_sdk2py pyrealsense2 cv2 mcap zstandard` absent
  from that venv; keep it that way. Everything tonight is installed into the
  **Orin's system Python / apt**, never into `.parcel/`.

---

## 1 · Time budget and triage

| Step | What | Wall clock | Can it be skipped? |
|---|---|---|---|
| **PRE** | Firmware read + change ledger | 10 min | **No.** It is a security precondition. |
| **N0** | Orin identity dump **+ driver-package availability probe** | **6 min** | **No.** Highest information per second on the sheet. |
| **N1** | `usbfs_memory_mb` + reboot | 20 min (incl. reboot) | No — N2 depends on it |
| **N2a–d** | RealSense 10-min all-stream frame count + IMU (`pyrealsense2`) | 45 min | **No.** This is a go/no-go. |
| **N2e** | **`realsense2_camera` ROS driver — install, launch, `topic hz`** | **30 min** | **No.** 89% of the byte budget is topics that only exist if a driver publishes them. |
| **N3** | `fio` tail throughput | 20 min | No — it sets tomorrow's camera profile |
| **N4a–e** | rosbag2 + MCAP, 10-min **synthetic** record | 45 min | **No.** It is the D-2 fix's only rehearsal. |
| **N4f** | **Record the REAL driver topics through the same command line** | **15 min** | **No.** N4a–e never touches a driver; this is the only end-to-end proof. |
| **N5a** | L2 bench, vendor SDK example (build + read) | 60–120 min | Degradable — see branch |
| **N5b** | **L2 ROS node (`unitree_lidar_ros2`) — build, launch, `topic hz`** | **30 min** | Degradable, but then the L2 is not in tomorrow's bag |
| **N6a–e** | Network pinning + staged fallback | 30 min | No |
| **N6f** | **`unitree_ros2` message packages — build + `ros2 interface show`** | **30 min** | **No.** Without these `ros2 bag record` cannot record a single dog topic. |
| **N7** | Python 3.10 import check on the Orin | 15 min | No — 15 min, first real proof |
| | **Total** | **≈ 6.5–8 h** | |

> ### ⚠ The four steps in bold are new, and they are the ones the sheet used to be missing
>
> The recorder of record is `ros2 bag record`, and **`ros2 bag record` records
> TOPICS.** A topic does not exist because a sensor exists — it exists because a
> **driver node** is running and publishing it. The previous revision of this
> sheet installed `pyrealsense2`, `librealsense2-utils` and `fio`, and never
> installed, launched or rehearsed a single ROS driver node. Measured against
> the budget (`../BANDWIDTH_BUDGET.md` §3):
>
> | Topics that exist only if we launched a driver | Share of the byte budget |
> |---|---:|
> | D455 (`realsense2_camera`): colour, depth, infra1, infra2, accel, gyro | **89.0%** |
> | Add-on L2 (`unitree_lidar_ros2`): cloud, IMU | 0.8% |
> | Dog (`unitree_ros2` **message packages**, not a node): every `go2.*` row | 10.2% |
> | Needs no ROS at all (`tegrastats`, GNSS, UWB fob) | 0.02% |
>
> `pyrealsense2` is **not** that path and does not close it —
> **[REPO]** `scripts/parcel_capture/ingest/realsense.py:3-8`: *"for the session
> the **primary** path is the `realsense2_camera` ROS node feeding `ros2 bag
> record -s mcap`. This adapter is the preflight/attestation path."* Worse, the
> two paths are **mutually exclusive at the device**: the D455 is a single USB
> node and only one process can hold it. N2a–d and N2e cannot run at the same
> time, and neither can run while tomorrow's driver is up.

**If you have only 90 minutes**, do: **PRE → N0 → N2a → N2e → N3**. Rationale:
PRE is a security gate, N0 can change the shape of the day, and N2a+N2e together
answer *is the camera a sensor tomorrow and can the recorder see it* — which is
the actual go/no-go. The ten-minute frame count (N2c) is a **quality** question
and it can be answered at reduced duration; *does the driver exist and publish
at all* cannot be answered tomorrow at any duration, because
`ros-humble-realsense2-camera` has to be **downloaded**, and tomorrow the Orin
is on a robot LAN with no route out.

**If you have only 20 minutes**, do **PRE → N0** and wake the owner with the
result. Nothing else on this sheet outranks knowing what operating system is on
the machine that is supposed to record everything — and N0 now also answers,
in sixty seconds, whether the three driver packages the day depends on are
installable on this box at all.

---

## PRE · Firmware and security precondition — **before any cable**

> Tomorrow a laptop and an Orin sit on an **unauthenticated DDS segment all
> day.** **[REPO]** `../../../20260805/task_1/adr/0002-firmware-pin.md:10-13`:
> *"Unitree DDS on the robot LAN is unauthenticated by design. Pre-1.1.13
> firmware is treated as RCE-capable on home Wi-Fi (CVE-2026-27509 / 27510
> class findings)."* The pin is **≥ V1.1.13** (`:17`).

### PRE-1 · Read the firmware version from the Unitree app, and record it

**WHY.** The pin is a *precondition for attaching a computer to that LAN*, not a
checkbox you tick afterwards. Reading it in the app needs no laptop, no Orin, no
DDS, and no code — and it is the one number that can cancel tomorrow's network
plan outright.

**Read the firmware version from the Unitree app and record it BEFORE
connecting anything** — before the Orin, before the laptop, before a cable.

**COMMAND.** Not a command. Power the Go2 in a safe posture (seated, on the mat,
hands clear of the leg envelope — see [SAFETY_BRIEF.md](SAFETY_BRIEF.md)),
connect **the phone only**, and read the version in the Unitree app's device /
firmware page. Then power the dog back down.

```text
RECORD  Go2 firmware version as displayed ......... ______________________
RECORD  Where it was read (app screen name) ....... ______________________
RECORD  Auto-update setting (on / off) ............ ______________________
RECORD  Photo id for the screen ................... ______  (add to PHOTO_LIST)
RECORD  Read at ...................... ______ UTC by ______________________
RECORD  Anything else attached to the dog's network at this moment: ______
        (correct answer: nothing but the phone)
```

**EXPECTED.** A version string of the form `V1.1.x`.

**STOP / BRANCH.**

| Reading | Branch |
|---|---|
| **≥ 1.1.13** | Proceed. Record the version into tomorrow's run header (`STAGE0_RUN_SHEET.md` §1) and into precondition **P1** (`STAGE0_RUN_SHEET.md:142`). |
| **< 1.1.13** | **STOP. Wake the owner.** Do **not** attach the Orin or the laptop to the robot LAN tomorrow. `STAGE0_RUN_SHEET.md:142` already routes this to branch **DEGRADE-MMP** — *mount, measure, photograph, record nothing* — which is a **legitimate outcome**, and tonight is when you find out you are heading for it, not 10:00 tomorrow. Everything else on this sheet (N0–N5, N7) is still worth doing: none of it touches the dog. |
| **Cannot be read** | Treat as **below pin** (fail closed: unknown = absent). Same branch. Record *why* it could not be read. |

> **Honest caveat.** Connecting the phone to the dog's own Wi-Fi puts the phone
> on that unauthenticated segment. That is the vendor's only path to the version
> number and it is unavoidable; it is one device for a few minutes rather than
> two computers for a day. Note it and move on.

### PRE-2 · The two-dock problem — **the only Orin must not be mutated more than tonight requires**

**[REPO]** `../../../20260805/task_1/P5_PROCUREMENT_BOM.md:66` specifies
**quantity 2** Orin NX docks — *"Compute: sacrificial flash dock + production
restore dock"* — with the note *"Two-dock rule is mandatory; do not flash the
only dock first."* **One dock is on hand.** `STAGE0_RUN_SHEET.md:144` rules
precondition **P3** `CANNOT BE MET` and states the consequence:

> the only dock present is therefore **not** sacrificial — **do not flash it, do
> not `apt upgrade` it, do not mutate it** during this session.

**Stated plainly: there is no restore path. If the Orin stops booting tonight,
there is no second dock to fall back to, no golden image to restore from, and
the session does not happen.** ADR 0001's whole point is that the first flash is
a one-way door; tonight we are not flashing, but N1 edits a **boot** file and
N2/N4/N5 install packages, and a bricked boot is indistinguishable in effect
from a bad flash.

**Therefore, tonight's permitted / forbidden list:**

| Permitted tonight | Forbidden tonight |
|---|---|
| `apt-get install` of the **named** packages in N2–N5 | `apt-get upgrade` / `dist-upgrade` / `full-upgrade` |
| `pip install` into system or a venv **on the Orin** | Any JetPack flash, SDK Manager, `nvbootctl` slot change |
| Appending **one** kernel arg in `/boot/extlinux/extlinux.conf`, **with a verbatim backup taken first** | Kernel package upgrade, DTB change, bootloader update |
| Cloning + building `unilidar_sdk2` **in the user's home directory** | Installing anything into `.parcel/` on the dev box |
| Static IP configuration | Rewriting the netplan/NM config without a backup |

### PRE-3 · Change ledger — snapshot before you touch anything

**WHY.** With no restore dock, the only rollback available is *knowing exactly
what changed*. This costs 60 seconds and is the difference between "undo the
three packages" and "reinstall the machine we do not have a spare of".

```bash
# ON THE ORIN
mkdir -p ~/tonight && cd ~/tonight
dpkg -l > pkgs.before.txt
pip3 freeze > pip.before.txt 2>/dev/null || true
sudo cp -a /boot/extlinux/extlinux.conf ~/tonight/extlinux.conf.bak
cat /proc/cmdline > cmdline.before.txt
ip -o addr show > ipaddr.before.txt
ip route > iproute.before.txt
sha256sum ~/tonight/extlinux.conf.bak
```

**EXPECTED.** Five files written, one sha256 printed.

```text
RECORD  sha256 of extlinux.conf.bak ............... ______________________
RECORD  ~/tonight/pkgs.before.txt line count ...... ______
RECORD  Console access (HDMI/DP+keyboard or serial) on hand? ...... ______
```

**STOP / BRANCH.** If the answer to the console-access question is **no**, do
**not** run N1's reboot (N1b/N1c). Use N1's **runtime-only** path (N1a) and
carry the "re-apply after every boot" line into tomorrow's run sheet §3. A
non-booting Orin with no console and no second dock ends the project week.

---

## N0 · ORIN IDENTITY — five minutes, highest information per second

**WHY.** The plan **asserts** JetPack 6.2 / Ubuntu 22.04 / ROS 2 Humble
throughout — **[REPO]** `../README.md`
(*"Orin runs 3.10 via JetPack 6.2.x/Humble"*) and
`../PHYSICAL_SESSION_PLAN.md`. **Nobody has read
`/etc/nv_tegra_release`.** **[REPO]** `../RISK_ASSESSMENT.md:108-111` ranks this
risk #1. If the box is JetPack 5.1.1 / Ubuntu 20.04 / Foxy, then the rosbag2
storage plugin, the Python version, the pyrealsense2 wheel, and the CycloneDDS
config schema **all move at once**, and tomorrow changes shape. Five minutes.

**COMMAND.**

```bash
# ON THE ORIN
cat /etc/nv_tegra_release
lsb_release -a
uname -r
ls /opt/ros
python3 --version
lsblk
df -h

# and one more, because N2, N4 and N5 all need to download something:
getent hosts deb.debian.org pypi.org github.com || echo 'NO DNS'
timeout 10 apt-get -s update >/dev/null 2>&1 && echo 'APT REACHABLE' || echo 'APT UNREACHABLE'

# the Orin's own address, because N7a rsyncs to it from the dev box
hostname -I
```

**COMMAND — N0b, the driver-package probe. Sixty seconds, and it is the cheapest
disconfirming check on the whole sheet.**

**WHY.** 89% of tomorrow's bytes are `/camera/camera/*` topics that exist only
while `realsense2_camera` is running, and another 10% are dog topics that
`ros2 bag record` cannot serialise at all without the `unitree_go` /
`unitree_api` interface packages. **[REPO]**
`scripts/parcel_capture/rosbag2.py:229-357` carries the topic names *and the
launch command that produces each one*; `:183-210` records that every dog topic
needs *"the `unitree_ros2` overlay sourced"*. If any of these is not obtainable
on this box, tomorrow's recorder records less than half of what the plan says it
records — and the fix requires a **download**, which tomorrow's robot LAN cannot
do.

```bash
# ON THE ORIN — read-only. Installs nothing.
source /opt/ros/humble/setup.bash 2>/dev/null || echo 'NO ROS TO SOURCE'
ROSD=$(ls /opt/ros | head -1)      # the distro N0 actually found
sudo apt-get update
for p in ros-$ROSD-realsense2-camera ros-$ROSD-realsense2-camera-msgs \
         ros-$ROSD-librealsense2 ros-$ROSD-rosbag2-storage-mcap ; do
  echo "===== $p"; apt-cache policy "$p" | head -3
done

# are the unitree interfaces already present from some earlier install?
ros2 interface list 2>/dev/null | grep -iE 'unitree' || echo 'NO UNITREE INTERFACES'
ros2 pkg list 2>/dev/null | grep -iE 'realsense|unitree|unilidar' || echo 'NO DRIVER PACKAGES'
```

```text
RECORD  ros-$ROSD-realsense2-camera Candidate ........ ______________________
RECORD  ros-$ROSD-realsense2-camera-msgs Candidate ... ______________________
RECORD  ros-$ROSD-librealsense2 Candidate ............ ______________________
RECORD  ros-$ROSD-rosbag2-storage-mcap Candidate ..... ______________________
RECORD  unitree interfaces already present? .......... ______  (expected: no)
RECORD  driver packages already present? ............. ______  (expected: none)
RECORD  Orin IP address (for N7a's rsync) ............ ______________________
```

**EXPECTED (the asserted case).** `# R36 (release), REVISION: 4.x` (JetPack
6.2) · `Ubuntu 22.04` · kernel `5.15.x-tegra` · `/opt/ros` contains `humble` ·
`Python 3.10.x` · an `nvme0n1` with a large mounted partition.

**RECORD — paste verbatim, all seven outputs:**

```text
$ cat /etc/nv_tegra_release
______________________________________________________________________

$ lsb_release -a
______________________________________________________________________

$ uname -r
______________________________________________________________________

$ ls /opt/ros
______________________________________________________________________

$ python3 --version
______________________________________________________________________

$ lsblk
______________________________________________________________________

$ df -h
______________________________________________________________________

DERIVED  JetPack release ............................ ______
DERIVED  Ubuntu release ............................. ______
DERIVED  ROS 2 distro(s) present .................... ______
DERIVED  Default python3 ............................ ______
DERIVED  Intended record target path ................ ______
DERIVED  Its device (NVMe / eMMC / SD / USB) ........ ______
DERIVED  Free space on it (GiB) ..................... ______
DERIVED  Internet uplink present (DNS + apt) ....... ______
```

**STOP / BRANCH.**

| Finding | Branch |
|---|---|
| **JetPack 6.x / 22.04 / `humble` / py3.10** | The plan holds. Continue to N1. |
| **JetPack 5.x / 20.04 / `foxy`** | **STOP. Wake the owner.** Four things move: (a) `ros-humble-rosbag2-storage-mcap` does not exist → N4 records `-s sqlite3` and converts offline; the D-2 fix's *"readable by every downstream tool"* claim weakens to *"readable after a conversion step"*. (b) `ros2 bag record` flags differ → re-derive every flag in N4 from `ros2 bag record --help` before running. (c) default `python3` is 3.8 → the pyrealsense2 wheel target in N2 moves, and **[REPO]** PS-A's static 3.10 pin (`../PSA_STATUS.md:121-153`) is aimed at the wrong version. (d) CycloneDDS config schema in N6 is the older `<NetworkInterfaceAddress>` form. |
| **`/opt/ros` is empty or missing** | **STOP. Wake the owner.** The rosbag2-primary recorder — the entire fix for defect **D-2** (`../RISK_ASSESSMENT.md:30-45`) — has no host. Options: install a ROS distro tonight (a large mutation of the only dock; see PRE-2), or accept that `parcel-capture` MCAP is the sole recorder tomorrow with a **written** acceptance that no downstream SLAM/calibration tool can read it without a converter we have not written. This is an owner decision, not an operator one. |
| **`python3` is not 3.10** | Record it. N7's target changes; note the actual version and re-aim the check. |
| **Record target is eMMC / SD / USB, not NVMe** | Expect N3 to be far worse. Continue to N3 and let the number decide; do not assume. |
| **No internet uplink** | **STOP and fix it before N2.** `apt-get install ros-$ROSD-realsense2-camera` (N2e), `pip install pyrealsense2` (N2a), `apt-get install ros-$ROSD-rosbag2-storage-mcap` (N4a), `apt-get install fio` (N3), `git clone unilidar_sdk2` (N5), and `git clone unitree_ros2` (N6f) **all need to download**. If the Orin has no uplink tonight, six of the steps below cannot run at all — and none of them can be fixed tomorrow on a robot LAN with no route out. Give it a temporary uplink now (wired, or a phone tether), do **every** download, then remove the uplink again before N6 pins the addresses. |
| **`ros-$ROSD-realsense2-camera` has no candidate** | **STOP. Owner decision, tonight, and it is the biggest one on the sheet.** 89% of tomorrow's byte budget is topics this package publishes. Options in increasing cost: (1) add Intel's apt repo or ROS's, if either serves this arch; (2) `colcon build` the driver from source against a `librealsense2` you also have to build — hours, and a large mutation of the only dock (PRE-2); (3) accept that the D455 is recorded by **`parcel-capture` only**, not by `ros2 bag record`, which reopens defect **D-2** for the single largest channel group in the rig — write that acceptance down; (4) drop the D455 tomorrow. |
| **`ros-$ROSD-rosbag2-storage-mcap` has no candidate** | See N4a's branch. Same consequence, recorded there. |
| **Free space < 125 GiB** | Tomorrow's take length is bounded **tonight**. **[REPO]** `../BANDWIDTH_BUDGET.md` §4: a 20-minute take at the recommended profile needs **123.9 GiB**. Also note N3 wants 40 GiB and N4 wants ≈55 GiB of scratch tonight — free space now, or shrink both tests and say so. |

---

## N1 · `usbfs_memory_mb` — the 16 MB default that kills dual-IR streaming

**WHY.** **[EXT]** `../RISK_ASSESSMENT.md:116-118`: the kernel's USB filesystem
buffer defaults to **16 MB**, which is not enough for the D455 streaming colour
+ depth + **two** IR streams at once. The persistent fix requires editing
`/boot/extlinux/extlinux.conf` and **rebooting**. Discovering this tomorrow
costs a reboot cycle in the middle of the session, and the failure presents as
mysterious per-frame errors rather than as "your buffer is too small".

**[REPO]** Zero hits for `usbfs` or `extlinux` anywhere in this repository —
this sheet is the first place it is recorded.

> **Order note (deviation, deliberate).** The card orders this before N2, and it
> stays before N2. But the reboot is the single highest-cost action on this
> sheet (PRE-2: no second dock), so it is split into a **reversible** part and a
> **persistent** part, cheapest first.

### N1a · Runtime write — reversible, no reboot, proves the value is settable

```bash
# ON THE ORIN
cat /sys/module/usbcore/parameters/usbfs_memory_mb          # before
echo 1000 | sudo tee /sys/module/usbcore/parameters/usbfs_memory_mb
cat /sys/module/usbcore/parameters/usbfs_memory_mb          # after
```

**EXPECTED.** `16` before, `1000` after.

```text
RECORD  before ...... ______     after ...... ______
```

**STOP / BRANCH.** If the write is refused (read-only parameter on this kernel),
skip N1a, note it, and go to N1b — the boot argument is then the *only* path.

### N1b · Persistent boot argument — with the backup already taken in PRE-3

```bash
# ON THE ORIN — the backup from PRE-3 must already exist
ls -l ~/tonight/extlinux.conf.bak
sudo nano /boot/extlinux/extlinux.conf
#   find the APPEND line of the DEFAULT (primary) LABEL and append, on the
#   SAME line, separated by a single space:
#       usbcore.usbfs_memory_mb=1000
#   Change nothing else. Do not reflow the line. Do not add a new LABEL.
grep -n APPEND /boot/extlinux/extlinux.conf
diff ~/tonight/extlinux.conf.bak /boot/extlinux/extlinux.conf
```

**EXPECTED.** `diff` shows exactly one changed line, differing only by the
appended ` usbcore.usbfs_memory_mb=1000`.

```text
RECORD  diff output (must be one line, one addition):
______________________________________________________________________
```

**STOP / BRANCH.** If `diff` shows **anything else**, restore
(`sudo cp -a ~/tonight/extlinux.conf.bak /boot/extlinux/extlinux.conf`) and
retry. If `/boot/extlinux/extlinux.conf` **does not exist** on this JetPack
image: **do not go hunting in the bootloader.** Fall back to N1a-only, record
that the setting is **not persistent**, and write a line into tomorrow's run
sheet §3 that it must be re-applied after **every** boot. That is a survivable
outcome; a broken bootloader is not.

### N1c · Reboot — **only if PRE-3 recorded console access**

```bash
sudo reboot
# wait, then re-SSH
cat /proc/cmdline
cat /sys/module/usbcore/parameters/usbfs_memory_mb
```

**EXPECTED.** `/proc/cmdline` contains `usbcore.usbfs_memory_mb=1000`; the sysfs
file reads `1000`.

```text
RECORD  /proc/cmdline ............... ______________________________________
RECORD  usbfs_memory_mb after reboot  ______
RECORD  Did the Orin come back on the network without console intervention? ___
```

**STOP / BRANCH.**

| Finding | Branch |
|---|---|
| `1000`, machine healthy | Continue to N2. |
| Value still `16` after reboot | The APPEND line edited was not the one the bootloader uses (wrong `LABEL`, or `DEFAULT` points elsewhere). Read `DEFAULT` at the top of `extlinux.conf`, edit that `LABEL`'s APPEND, repeat. If it still does not take, fall back to N1a-only + the re-apply-every-boot line. |
| **Orin does not come back** | **STOP EVERYTHING. This is the worst outcome on the sheet.** Attach the console. At the extlinux prompt or from a recovery shell, restore `~/tonight/extlinux.conf.bak`. There is **no second dock** (PRE-2). Wake the owner regardless of whether recovery succeeds — tomorrow's shape depends on it. |

---

## N2 · REALSENSE — the real go/no-go

**WHY.** **[EXT]** `../RISK_ASSESSMENT.md:112-116`: `pip install pyrealsense2`
is a real wheel on **Python 3.10 / 3.12 aarch64**, with **no wheel for 3.11+**;
worst case is a 2–3 h source build. And there are **open, unfixed reports on
this exact pairing** — D455 on Orin NX — of **~80% RGB frame drop** and a **dead
IMU**. This step is not a formality. It decides whether the D455 is a sensor
tomorrow or a paperweight, and it decides tomorrow's camera profile.

> **Contradiction in the source, flagged rather than resolved.** The brief for
> this card and `../RISK_ASSESSMENT.md:112-114` both say *"a real wheel on
> Python 3.10/3.12"* **and** *"no wheel for 3.11+"*, which cannot both be true
> of 3.12. **Do not try to reconcile these on paper — let `pip` answer.** N2a
> below records what pip actually offers for **this** interpreter on **this**
> architecture, and that output supersedes both statements.

### N2a · Install, and record what pip actually offers

```bash
# ON THE ORIN — NEVER into the dev box's .parcel/
python3 --version
uname -m
python3 -m pip index versions pyrealsense2 2>&1 | head -20
python3 -m pip install --user pyrealsense2
python3 -c "import pyrealsense2 as rs; print(rs.__version__ if hasattr(rs,'__version__') else 'no __version__')"
python3 -c "import pyrealsense2 as rs; ctx=rs.context(); print([ (d.get_info(rs.camera_info.name), d.get_info(rs.camera_info.serial_number), d.get_info(rs.camera_info.firmware_version)) for d in ctx.devices ])"
```

**EXPECTED.** A wheel installs; the device list shows one `Intel RealSense D455`
with a serial and a firmware version.

```text
RECORD  python3 version / arch ...................... ______ / ______
RECORD  pip index versions output ................... ______________________
RECORD  installed pyrealsense2 version .............. ______
RECORD  D455 name / serial / firmware ............... ______ / ______ / ______
        (serial + firmware also go in tomorrow's attestation and PHOTO_LIST)
```

**STOP / BRANCH.**

| Finding | Branch |
|---|---|
| Wheel installs, device enumerates | Continue to N2b. |
| **No wheel for this interpreter** | **STOP. Owner decision, tonight.** Options, in increasing cost: (1) install a `python3.10` (or `3.12`) alongside and use it only for capture — smallest mutation; (2) use the distro's `ros-<distro>-realsense2-camera` if `apt-cache policy` shows it, which changes the D455 ingest path to a ROS node and actually *fits* the rosbag2-primary plan better; (3) source-build librealsense (2–3 h, large mutation of the only dock — see PRE-2); (4) drop the D455 and record LiDAR-only tomorrow. Write down which was chosen and why. |
| Device does not enumerate | Check the cable and the port (**USB 3, blue, direct — no hub**), then `lsusb | grep -i intel` and `dmesg | tail -40`. If it still does not enumerate, this is a hardware/cable problem and it is far better to find it tonight. |

### N2b · The metadata tradeoff — record it explicitly, it is load-bearing

**WHY.** **[EXT]** `../RISK_ASSESSMENT.md:113-115`: the pip wheel **costs UVC
per-frame metadata** — which is exactly the **`device_source` timestamp the plan
calls non-negotiable**. **[REPO]** `../README.md` makes
`source_timestamp_ns` a per-message field of `CaptureEnvelope`, and
`../PHYSICAL_SESSION_PLAN.md` calls dual clocks one of *"the two
non-negotiables"*. If the wheel gives us `SYSTEM_TIME` instead of
`HARDWARE_CLOCK`, the D455's device clock is **not** recoverable from the
frames, and the only remaining tie is PS-C's redesigned **physical sync ritual**
(`../RISK_ASSESSMENT.md:88-99`).

```bash
# ON THE ORIN
python3 - <<'PY'
import pyrealsense2 as rs
p = rs.pipeline(); c = rs.config()
c.enable_stream(rs.stream.color, 848, 480, rs.format.rgb8, 30)
prof = p.start(c)
f = p.wait_for_frames().get_color_frame()
print("timestamp_domain:", f.get_frame_timestamp_domain())
for k in ("frame_timestamp", "sensor_timestamp", "backend_timestamp",
          "frame_counter", "actual_exposure"):
    mv = getattr(rs.frame_metadata_value, k, None)
    print(k, "supported=", (f.supports_frame_metadata(mv) if mv is not None else "n/a"))
p.stop()
PY
```

**EXPECTED (either is a valid finding — record which).**
`timestamp_domain: hardware_clock` with metadata supported → device timestamps
survive. `timestamp_domain: system_time` with metadata unsupported → they do
not.

```text
RECORD  timestamp_domain .......................... ______________________
RECORD  frame_timestamp supported ................. ______
RECORD  sensor_timestamp supported ................ ______
RECORD  backend_timestamp supported ............... ______
```

**STOP / BRANCH.**

| Finding | Branch |
|---|---|
| `hardware_clock`, metadata supported | Good. `source_timestamp_ns` is real for D455 channels. |
| `system_time` / metadata unsupported | **Not a stop, but a decision that must be written down.** Consequences, all three: (1) `CaptureEnvelope.source_timestamp_ns` for every D455 channel must be **null — fail closed. Never write the host time into the device field.** (2) The **physical sync ritual is now mandatory, not optional**, and it is the only D455-to-world timing tie that will exist. Bracket it start **and** end (`../RISK_ASSESSMENT.md:96-99`). (3) If the owner wants hardware timestamps badly enough to pay for a kernel-patched source build, **that decision is made tonight**, not tomorrow. |

### N2c · Ten minutes, all streams, **counted per stream**

**WHY.** *Messages arrive* is not *the channel is healthy*. The ~80% RGB drop
report presents as a stream that is running and delivering a fifth of its
frames. Only a per-stream count against a per-stream expectation catches it.

```bash
# ON THE ORIN — run AFTER N1 (usbfs) is in effect. 10 minutes.
python3 - <<'PY'
import time, collections
import pyrealsense2 as rs

W,H,FPS,SECS = 848,480,30,600
p = rs.pipeline(); c = rs.config()
c.enable_stream(rs.stream.color,    W,H, rs.format.rgb8, FPS)
c.enable_stream(rs.stream.depth,    W,H, rs.format.z16,  FPS)
c.enable_stream(rs.stream.infrared, 1, W,H, rs.format.y8, FPS)
c.enable_stream(rs.stream.infrared, 2, W,H, rs.format.y8, FPS)
c.enable_stream(rs.stream.accel)
c.enable_stream(rs.stream.gyro)
n = collections.Counter()
def cb(f):
    if f.is_frameset():
        for sub in f.as_frameset(): n[str(sub.profile.stream_name())] += 1
    else:
        n[str(f.profile.stream_name())] += 1
prof = p.start(c, cb)
rates = {s.stream_name(): s.fps() for s in prof.get_streams()}
t0 = time.time()
while time.time() - t0 < SECS: time.sleep(1)
p.stop(); dt = time.time() - t0
print("elapsed_s %.1f" % dt)
print("%-14s %10s %10s %8s" % ("stream","delivered","expected","pct"))
for k in sorted(n):
    exp = rates.get(k, 0) * dt
    print("%-14s %10d %10.0f %7.1f%%" % (k, n[k], exp, (100.0*n[k]/exp if exp else 0)))
PY
```

**[UNVERIFIED-SYNTAX].** The frame-callback form and `stream_name()` spelling
vary a little between pyrealsense2 builds. If it errors, the fallback is a plain
`wait_for_frames()` loop counting `frame.get_profile().stream_type()` — the
**requirement is a per-stream delivered-vs-expected count over 600 s**, not this
exact script.

**EXPECTED.** 4 video streams at ≈**18,000** frames each (30 Hz × 600 s), and
two motion streams at whatever `fps()` reports (D455 accel is commonly 63 or 250
Hz, gyro 200 or 400 Hz — **use the reported rate, do not assume**).

```text
RECORD  elapsed_s .................................. ______
RECORD  Colour     delivered ______ / expected ______ = ______ %
RECORD  Depth      delivered ______ / expected ______ = ______ %
RECORD  Infrared 1 delivered ______ / expected ______ = ______ %
RECORD  Infrared 2 delivered ______ / expected ______ = ______ %
RECORD  Accel      delivered ______ / expected ______ = ______ %
RECORD  Gyro       delivered ______ / expected ______ = ______ %
RECORD  Any error/warning text from librealsense: ______________________
```

**STOP / BRANCH.**

| Finding | Branch |
|---|---|
| Every stream ≥ **99 %** | GO at 848×480@30 colour+depth+IR — **[REPO]** the recommended profile, `../BANDWIDTH_BUDGET.md` §1. Then **N2e**: `pyrealsense2` delivering frames does not mean the ROS driver publishes topics. |
| Any stream **90–99 %** | Record the deficit as a **number**. Not a stop. Tomorrow's sidecar must report it as `DEGRADED` with the deficit quantified, which is what PS-B's per-channel expected-count assertion is for (`../README.md`). |
| Any stream **< 90 %** | **STOP. The ~80 % RGB drop report has reproduced on our unit.** This is a go/no-go and it is decided **tonight**: step down the drop ladder in `../BANDWIDTH_BUDGET.md` §2 — `848×480@30 C+D` (IR off) → `848×480@15 C+D+IR` → `848×480@30 D+IR` (colour off) — and **re-run this exact count at the new profile** until a profile holds ≥ 99 %. Whatever profile survives is tomorrow's profile, and it is also the profile N2e must be launched at. Write it in tomorrow's run sheet §3. |
| **Accel or gyro delivered = 0** | The **dead-IMU** report has reproduced. Confirm with N2d before concluding. If confirmed: the D455 IMU channel is **ABSENT** for tomorrow (fail closed — do not record an empty channel as healthy), and the camera-to-IMU extrinsic on `MOUNT_GEOMETRY_SHEET.md` becomes moot. Say so on that sheet. |
| Streams fail to start at all with a USB/bandwidth error | Re-check N1 took effect (`cat /sys/module/usbcore/parameters/usbfs_memory_mb`). **[EXT]** `../RISK_ASSESSMENT.md:64`: 720p all-streams ≈1327 Mbps is **above Intel's own ~1200 Mbps ceiling** — at 848×480 you are under it, but a hub or a USB-2 port puts you over instantly. Direct blue port, no hub. |

### N2d · `rs-motion` — the IMU sanity check

**WHY.** The dead-IMU report needs a second, independent look, and a *nonzero*
IMU is not the same as a *plausible* one. **[REPO]**
`../RISK_ASSESSMENT.md:137-140`: `utlidar/imu` has two independent reports of
emitting ~**1e24 m/s²**, which a receipt-count probe would happily attest as
healthy. The physical-plausibility gate is **|accel| = 9.81 ± 1 m/s²** and
**|gyro| < 0.05 rad/s** with the sensor **at rest**.

```bash
# ON THE ORIN — preferred: the SDK tool, if it is installable at all
apt-cache policy librealsense2-utils
sudo apt-get install -y librealsense2-utils   # may not exist for aarch64
rs-motion
```

**[EXT] Expect this to be unavailable.** Intel publishes apt packages for x86
Ubuntu; on Jetson `rs-motion` usually requires the source build. **Fallback that
needs no new packages:**

```bash
python3 - <<'PY'
import math, time
import pyrealsense2 as rs
p = rs.pipeline(); c = rs.config()
c.enable_stream(rs.stream.accel); c.enable_stream(rs.stream.gyro)
p.start(c)
a = g = None; t0 = time.time()
try:
    while time.time() - t0 < 20:
        for f in p.wait_for_frames():
            m = f.as_motion_frame()
            if not m: continue
            d = m.get_motion_data(); v = (d.x, d.y, d.z)
            if m.profile.stream_type() == rs.stream.accel: a = v
            else: g = v
        if a and g:
            print("accel %8.3f %8.3f %8.3f  |a|=%7.3f   gyro %8.4f %8.4f %8.4f  |g|=%7.4f"
                  % (a+(math.dist(a,(0,0,0)),)+g+(math.dist(g,(0,0,0)),)))
finally:
    p.stop()
PY
```

**EXPECTED — with the camera sitting still on the desk:** `|a|` ≈ **9.81**,
`|g|` < **0.05**.

```text
RECORD  rs-motion available? (yes / no) ........... ______
RECORD  |accel| observed (min / typical / max) ..... ______ / ______ / ______
RECORD  |gyro|  observed (max over 20 s) ........... ______
RECORD  Verdict: PRESENT / DEGRADED / ABSENT ....... ______
```

**STOP / BRANCH.**

| Finding | Branch |
|---|---|
| `|a|` in 8.81–10.81, `|g|` < 0.05 | **PRESENT.** IMU is real. |
| Values arrive but are implausible (0, ~1e24, constant) | **DEGRADED, not PRESENT.** Record the actual numbers. This is precisely the case a message-count probe gets wrong, and it is the reason the plausibility gate exists. |
| No motion frames at all | **ABSENT.** See the N2c dead-IMU branch. |

### N2e · `realsense2_camera` — **the ROS driver, which is the session path**

**WHY.** Everything in N2a–N2d used `pyrealsense2`, and `pyrealsense2` is **not
how tomorrow records**. **[REPO]** `scripts/parcel_capture/ingest/realsense.py:3-8`
says so in its own first paragraph: *"for the session the **primary** path is
the `realsense2_camera` ROS node feeding `ros2 bag record -s mcap`. This adapter
is the preflight/attestation path."* **[REPO]**
`scripts/parcel_capture/rosbag2.py:132-145` names the reason it matters:

> a `ROBOT_NATIVE` topic appears when the dog is on […] a `DRIVER_NODE` topic
> appears **only if we launched its driver** […] Three different failure modes,
> three different remedies, and mixing them is how a session records fifteen
> topics and misses the camera.

Six of those `DRIVER_NODE` topics are **89.0% of the byte budget**
(`../BANDWIDTH_BUDGET.md` §3). Nothing on this sheet has ever launched the node
that publishes them.

> **⚠ FREE THE CAMERA FIRST.** The D455 is one USB device and only one process
> can hold it. **Stop every `pyrealsense2` script from N2a–N2d before starting
> the driver** (`pkill -f 'python3 -'` if one is still running, and check with
> `lsof /dev/video* 2>/dev/null`). A driver that "fails to open the device" here
> is usually N2c still running in another terminal.

#### N2e-1 · Install the driver — **the ROS package, not the pip module**

```bash
# ON THE ORIN
source /opt/ros/humble/setup.bash          # or the distro N0 actually found
ROSD=$(ls /opt/ros | head -1)
sudo apt-get update
sudo apt-get install -y ros-$ROSD-realsense2-camera ros-$ROSD-realsense2-camera-msgs
dpkg -l | grep -E 'realsense'
ros2 pkg prefix realsense2_camera
ros2 pkg executables realsense2_camera
ls /opt/ros/$ROSD/share/realsense2_camera/launch/
```

**EXPECTED.** Two packages installed (the apt package pulls `librealsense2` as a
dependency), `ros2 pkg prefix realsense2_camera` prints a path, and the launch
directory contains `rs_launch.py`.

```text
RECORD  realsense2_camera installed version ......... ______________________
RECORD  librealsense2 version pulled in ............. ______________________
RECORD  ros2 pkg prefix realsense2_camera ........... ______________________
RECORD  launch files present ........................ ______________________
```

**STOP / BRANCH.**

| Finding | Branch |
|---|---|
| Installs, `rs_launch.py` present | Continue to N2e-2. |
| **No apt candidate** (N0b already warned you) | **STOP. Owner decision.** Take the branch written in N0's `no candidate` row and **write down which option was chosen**. Do not proceed to N2e-2 pretending the driver exists. |
| Installs, but `librealsense2` version differs from the `pyrealsense2` wheel in N2a | **Not a stop, but record both versions.** Two librealsense builds on one box is a real source of "works in Python, fails in ROS". If N2e-3 misbehaves, this is the first suspect. |

#### N2e-2 · Launch it at **tomorrow's profile**

The launch arguments are the profile from `../BANDWIDTH_BUDGET.md` §1 —
`848x480@30`, colour + depth + both IR + IMU — or whatever profile N2c actually
survived at. **Use the profile N2c chose, not the one written here**, and record
which.

```bash
# ON THE ORIN — terminal 1, leave running
source /opt/ros/humble/setup.bash
ros2 launch realsense2_camera rs_launch.py \
  enable_color:=true  rgb_camera.color_profile:=848x480x30 \
  enable_depth:=true  depth_module.depth_profile:=848x480x30 \
  enable_infra1:=true enable_infra2:=true \
  depth_module.infra_profile:=848x480x30 \
  enable_accel:=true  enable_gyro:=true \
  unite_imu_method:=linear_interpolation
```

**[UNVERIFIED-SYNTAX] and this one is likely to bite.** The profile-argument
spelling changed across driver 4.51 → 4.54 → 4.55: older builds use
`color_width:=848 color_height:=480 color_fps:=30` and
`depth_width/depth_height/depth_fps`; newer ones use the
`<module>.<stream>_profile:=WxHxF` form above. **Run
`ros2 launch realsense2_camera rs_launch.py --show-args | head -60` first, take
the spelling it prints, and record the substitution** — tomorrow's launch line is
derived from tonight's.

**`unite_imu_method` is not optional.** **[REPO]**
`scripts/parcel_capture/rosbag2.py:322-329`: *"`unite_imu_method` must be set or
the IMU topics do not appear."* Without it the accel and gyro topics are simply
absent and the bag has no D455 inertial data — a silent loss, not an error.

```text
RECORD  --show-args spelling actually used .......... ______________________
RECORD  Profile launched (WxH@fps, streams) ......... ______________________
RECORD  Node started cleanly? (paste last 5 log lines):
______________________________________________________________________
```

#### N2e-3 · The topics — do they exist, and at what rate?

```bash
# ON THE ORIN — terminal 2
source /opt/ros/humble/setup.bash
ros2 node list
ros2 topic list | grep -E '^/camera/'

# the six topics the recorder of record is configured to record
for t in /camera/camera/color/image_raw \
         /camera/camera/depth/image_rect_raw \
         /camera/camera/infra1/image_rect_raw \
         /camera/camera/infra2/image_rect_raw \
         /camera/camera/accel/sample \
         /camera/camera/gyro/sample ; do
  echo "===== $t"
  ros2 topic type "$t" 2>&1
  timeout 15 ros2 topic hz -w 100 "$t" 2>&1 | tail -3
done
```

**EXPECTED.** All six topics exist. The four image topics report ≈**30 Hz**; the
accel and gyro topics report whatever the driver united them at (commonly 200–400
Hz for gyro, 63–250 for accel — **use the reported rate, do not assume**).

**The topic names above are [EXT] and UNVERIFIED** — **[REPO]**
`scripts/parcel_capture/rosbag2.py:222-228` says exactly that: they depend on the
driver's `camera_name` / `camera_namespace` launch arguments, and *"a wrong name
here costs nothing at record time — the recorder simply never subscribes — which
is precisely the silent failure the pre-session topic check exists to catch."*
**Whatever `ros2 topic list` actually prints is the truth**; transcribe it.

```text
RECORD  ros2 topic list | grep ^/camera/ — paste it:
______________________________________________________________________

RECORD  colour   topic name ______________________  hz ______
RECORD  depth    topic name ______________________  hz ______
RECORD  infra1   topic name ______________________  hz ______
RECORD  infra2   topic name ______________________  hz ______
RECORD  accel    topic name ______________________  hz ______
RECORD  gyro     topic name ______________________  hz ______
RECORD  Do these six match rosbag2.py's DRIVER_TOPICS exactly? ______
```

**STOP / BRANCH.**

| Finding | Branch |
|---|---|
| Six topics, image topics ≥ 29 Hz | **GO.** Transcribe the six names verbatim into tomorrow's run sheet §3 **and** flag any that differ from `rosbag2.py`'s `DRIVER_TOPICS` — the topic list on the record command line has to be corrected before the session, not during it. |
| **Topic names differ from `rosbag2.py`** | **Not a failure — a finding, and it must be written down.** A recorder given a name nothing publishes subscribes to nothing and reports no error. Record the real names; the owner updates `DRIVER_TOPICS` (that file is not this sheet's to edit). |
| **Accel/gyro topics missing** | `unite_imu_method` was not applied, or the IMU is dead (N2c/N2d already told you which). Re-launch with the argument spelled as `--show-args` prints it. If they are still absent with a working `pyrealsense2` IMU, it is the driver argument; if `pyrealsense2` also saw nothing, it is the dead-IMU report reproducing. |
| **Image topics well below 30 Hz** while N2c's `pyrealsense2` count was ≥ 99 % | The driver, not the camera. Suspect the two-librealsense problem from N2e-1, `usbfs` (N1) not being in effect for this process, or QoS. Record both numbers side by side — that pair is the whole diagnosis. |
| **Node will not start / cannot open device** | Something still holds the camera. Kill every N2a–N2d script and retry before concluding anything. |

**Leave the driver running** if you are going straight to N4f; otherwise `Ctrl-C`
terminal 1 and record that you stopped it.

---

## N3 · STORAGE — read the **tail**, not the peak

**WHY.** **[EXT]** `../RISK_ASSESSMENT.md:118-120`: a DRAM-less NVMe can fall
**below 100 MB/s** after its SLC cache is exhausted — which is now **right at the
rate of the recommended profile**, not merely at the 720p rate. **[REPO]**
`../BANDWIDTH_BUDGET.md` §1: the recommended profile needs **91.87 MiB/s** for
the whole rig, i.e. **96.3 MB/s**. **[REPO]** `../BANDWIDTH_BUDGET.md` §5
measured 3,769 MiB/s **on the dev host** and labels it *"dev-host, to be
re-measured on the Orin"* — that number tells you nothing about the Jetson.
Tonight is the re-measurement.

> **⚠ The requirement moved and this step's thresholds moved with it.** The
> previous revision of this sheet said **84.60 MiB/s**, which was the figure the
> budget document published before the PS-H channel corrections were applied to
> the model. It was stale by 8.6%. `../BANDWIDTH_BUDGET.md` is now **generated**
> from `scripts/parcel_capture/budget.py` with a test that fails if it drifts
> again; the numbers in this step are transcribed from that generated file.

A peak reading hides exactly the failure mode we care about. **Read the tail.**

```bash
# ON THE ORIN — TARGET is the real record destination from N0
sudo apt-get install -y fio
TARGET=/data                                # <-- replace with the real path
df -h "$TARGET"
fio --name=w --rw=write --bs=1M --size=40G --end_fsync=1 \
    --filename="$TARGET/fio_tonight.bin" --ioengine=psync --direct=0 \
    --write_bw_log="$TARGET/fio_tonight" --log_avg_msec=1000 --eta=never

# peak
awk -F, 'NR>1 && $2>m {m=$2} END {printf "peak      = %8.1f MiB/s\n", m/1024}' \
    "$TARGET"/fio_tonight_bw.*.log
# tail: mean of the LAST 60 one-second samples
awk -F, 'NR>1 {v[++n]=$2} END {s=0;c=0; for(i=n;i>n-60 && i>0;i--){s+=v[i];c++}
    printf "tail %2ds  = %8.1f MiB/s\n", c, s/c/1024}' \
    "$TARGET"/fio_tonight_bw.*.log

rm -f "$TARGET/fio_tonight.bin"
df -h "$TARGET"
```

**EXPECTED.** A peak well above 500 MiB/s and a tail that may be much lower. The
tail is the number.

```text
RECORD  TARGET path ................................ ______________________
RECORD  Free before / after ........................ ______ / ______
RECORD  fio summary WRITE bw= line .................. ______________________
RECORD  peak ...................................... ______ MiB/s
RECORD  tail (last 60 s mean) ...................... ______ MiB/s
RECORD  Is a knee visible in the bw log (peak >> tail)? ______
```

**STOP / BRANCH.** Required = **91.87 MiB/s** (96.3 MB/s) at the recommended
profile — `../BANDWIDTH_BUDGET.md` §1.

| Tail | Branch |
|---|---|
| **≥ 184 MiB/s** (≥ 2×) | GO at `848×480@30 C+D+IR` **on disk grounds**. Disk is not the only ceiling: N4 still has to clear the *recorder* ceiling (`../BANDWIDTH_BUDGET.md` §2). |
| **92–184 MiB/s** (1–2×) | Thin margin, and the *stack* costs more than raw disk. Step down one rung of the ladder in `../BANDWIDTH_BUDGET.md` §2 — the cheapest is **front camera JPEG off**, which costs 6.58 MiB/s and no unique sensing modality; the next is `848×480@30 C+D` (IR off) at 61.98 MiB/s. Decide tonight. |
| **< 92 MiB/s** | **STOP.** The recommended profile is **not recordable on this destination.** Walk the drop ladder at `../BANDWIDTH_BUDGET.md` §2 until the requirement is under half the tail, or change the destination (external NVMe over USB 3 — do you have one? tonight is when you find out). Also re-check you measured the **real** target and not the eMMC. |
| **No knee: tail ≈ peak** | The test did **not** exhaust the SLC cache and has not disproven anything. Re-run with `--size=130G` (matching `../BANDWIDTH_BUDGET.md` §4's **123.9 GiB** for a 20-minute take) if the space exists. If it does not, record **"SLC exhaustion untested"** — a real limitation, not a pass. |
| Fewer than 40 GiB free | Run with a smaller `--size`, and record that the result is **weaker** for exactly the reason above. |

> **Two honest notes.** (1) `--direct=0` is deliberate: it is buffered + fsynced,
> which is how the recorder actually writes. A confirmatory `--direct=1` run
> measures the device rather than the page cache; run it if there is time and
> record both. (2) This writes 40 GiB to the record target. That is a real (if
> small) amount of flash wear and it fills the disk while it runs. Delete the
> file, and check `df` afterwards.

---

## N4 · ROSBAG2 + MCAP — rehearse the **exact** command line

**WHY.** This is the rehearsal for the fix to defect **D-2**
(`../RISK_ASSESSMENT.md:30-45`): `ros2 bag record -s mcap` becomes the
**recorder of record** because nothing downstream — GLIM, FAST-LIO2, Point-LIO,
KISS-ICP, Multi-LiCa, ros2_calib — can read `parcel-capture`'s own encoding. If
that path is not installed and rehearsed tonight, tomorrow's session records
into a format the next milestone cannot open.

**Splitting is the documented loss path**, which is why `--max-bag-size 0`.
`/events/write_split` and `/events/messages_lost` are recorded **as channels**
so that loss provenance lives **inside the bag** rather than in a terminal
scrollback nobody kept.

**[REPO]** Zero hits for `rosbag2-storage-mcap` anywhere in this repository.

### N4a · Install the storage plugin

```bash
# ON THE ORIN
source /opt/ros/humble/setup.bash          # or the distro N0 actually found
sudo apt-get update
apt-cache policy ros-humble-rosbag2-storage-mcap
sudo apt-get install -y ros-humble-rosbag2-storage-mcap
ros2 bag record --help | head -60
```

**EXPECTED.** The package installs; `--help` lists `-s/--storage`,
`--storage-config-file`, `--max-bag-size`, `--max-cache-size`,
`--disable-keyboard-controls`.

```text
RECORD  apt-cache policy candidate ................. ______________________
RECORD  installed version ........................... ______________________
RECORD  Are all five flags present in --help? ....... ______
RECORD  Any flag that is MISSING ..................... ______________________
```

**STOP / BRANCH.** Package not found → re-read N0. On Foxy the plugin does not
exist: record `-s sqlite3` and convert offline (`mcap convert`) — and write down
that the D-2 claim is now *"readable after a conversion step"*. A missing flag →
**do not silently drop it**; find its equivalent in `--help` and record the
substitution, because tomorrow's command line is derived from tonight's.

### N4b · Storage config

```bash
cat > ~/tonight_mcap.yaml <<'YAML'
noChunkCRC: true
chunkSize: 4194304
compression: "Zstd"
compressionLevel: "Fast"
YAML
cat ~/tonight_mcap.yaml
```

**[UNVERIFIED-SYNTAX].** The mcap storage plugin's YAML keys track
`mcap::McapWriterOptions` and have varied across releases. **Unknown keys may be
silently ignored** — which is why N4e verifies the settings *from the written
file*, not from the fact that the command did not error.

### N4c · Synthetic publishers at the **real** rate

**WHY.** A token 1 Hz string topic proves nothing. These **six** topics reproduce
the recommended profile's byte rate — **[REPO]** `../BANDWIDTH_BUDGET.md` §1,
**91.87 MiB/s** — so the recorder is tested where it will actually be tomorrow.

> **⚠ Two corrections to the previous revision of this step.** (1) It targeted
> **84.60 MiB/s**, the stale pre-PS-H figure; the real requirement is 8.6%
> higher. (2) It had five publishers and **no front camera**, which is now the
> fifth-largest channel in the rig at 6.59 MiB/s of JPEG. The `front_cam`
> publisher below closes both gaps.

```bash
# ON THE ORIN. Type this file on the Orin; it is NOT a repository file.
# It publishes ONLY under /tonight/. It never publishes any rt/ topic and it
# is not a robot command publisher of any kind.
cat > ~/tonight_pub.py <<'PY'
import os, rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import Image, PointCloud2, CompressedImage

W, H, N = 848, 480, 16          # N distinct random buffers per stream
JPEG_B  = 208896                # front camera worst case: 720p+360p+180p JPEG

def pool(nbytes):               # random => incompressible => WORST CASE for zstd
    return [os.urandom(nbytes) for _ in range(N)]

class P(Node):
    def __init__(self):
        super().__init__('tonight_pub')
        q = qos_profile_sensor_data
        self.pubs = {
            'color':    (self.create_publisher(Image, '/tonight/color', q),    pool(W*H*3), 'rgb8',   W*3),
            'depth':    (self.create_publisher(Image, '/tonight/depth', q),    pool(W*H*2), '16UC1',  W*2),
            'ir_left':  (self.create_publisher(Image, '/tonight/ir_left', q),  pool(W*H),   'mono8',  W),
            'ir_right': (self.create_publisher(Image, '/tonight/ir_right', q), pool(W*H),   'mono8',  W),
        }
        self.cloud = self.create_publisher(PointCloud2, '/tonight/cloud', q)
        self.cbuf = pool(300000)
        # The Go2 front camera: JPEG per frame at ~33 Hz. PS-H's correction made
        # this the fifth-largest channel in the rig; the old five-topic version
        # of this rehearsal under-drove the recorder by 6.6 MiB/s.
        self.front = self.create_publisher(CompressedImage, '/tonight/front_cam', q)
        self.fbuf = pool(JPEG_B)
        self.n = dict.fromkeys(list(self.pubs) + ['cloud', 'front_cam'], 0)
        self.create_timer(1/30.0, self.tick_img)
        self.create_timer(1/10.0, self.tick_cloud)
        self.create_timer(1/33.0, self.tick_front)

    def tick_img(self):
        for k, (pub, buf, enc, step) in self.pubs.items():
            m = Image()
            m.header.stamp = self.get_clock().now().to_msg(); m.header.frame_id = k
            m.height, m.width, m.encoding, m.step = H, W, enc, step
            m.data = buf[self.n[k] % N]
            pub.publish(m); self.n[k] += 1

    def tick_cloud(self):
        m = PointCloud2()
        m.header.stamp = self.get_clock().now().to_msg(); m.header.frame_id = 'cloud'
        m.height, m.width, m.point_step, m.row_step = 1, 18750, 16, 300000
        m.data = self.cbuf[self.n['cloud'] % N]
        self.cloud.publish(m); self.n['cloud'] += 1

    def tick_front(self):
        m = CompressedImage()
        m.header.stamp = self.get_clock().now().to_msg(); m.header.frame_id = 'front_cam'
        m.format = 'jpeg'
        m.data = self.fbuf[self.n['front_cam'] % N]
        self.front.publish(m); self.n['front_cam'] += 1

def main():
    rclpy.init(); n = P()
    try:
        rclpy.spin(n)
    except KeyboardInterrupt:
        pass
    finally:
        print('PUBLISHED ' + ' '.join('%s=%d' % kv for kv in sorted(n.n.items())))
        rclpy.shutdown()

main()
PY
# terminal 1 — leave running. SOURCE ROS FIRST: this script imports rclpy.
source /opt/ros/humble/setup.bash
python3 ~/tonight_pub.py
```

Arithmetic, so the expectation is checkable: 848×480 = 407,040 px.
colour 1,221,120 B × 30 Hz = 34.94 MiB/s · depth 814,080 × 30 = 23.29 MiB/s ·
IR pair 407,040 × 30 × 2 = 23.29 MiB/s · cloud 300,000 × 10 = 2.86 MiB/s ·
front camera 208,896 × 33 = 6.57 MiB/s.
**Total ≈ 90.9 MiB/s**, against the budget's **91.87** — the ~1 MiB/s shortfall
is the twenty small DDS channels this rehearsal does not synthesise, and it is
recorded here rather than papered over. Ten minutes ≈ **54.6 GiB** on disk
(random payloads do not compress — deliberately the worst case).

### N4d · Record — the exact command line planned for tomorrow

Start the publisher **first** (topic types must exist for discovery), then:

```bash
# ON THE ORIN — terminal 2
source /opt/ros/humble/setup.bash
TARGET=/data                                # <-- the SAME path N0/N3 recorded
df -h "$TARGET"
ros2 bag record -s mcap \
  --storage-config-file ~/tonight_mcap.yaml \
  --max-bag-size 0 \
  --max-cache-size 536870912 \
  --disable-keyboard-controls \
  -o "$TARGET/tonight_n4" \
  /tonight/color /tonight/depth /tonight/ir_left /tonight/ir_right /tonight/cloud \
  /tonight/front_cam \
  /events/write_split /events/messages_lost
# ... 10 minutes ... then Ctrl-C here, then Ctrl-C the publisher and read its
# PUBLISHED line.
```

**`TARGET` is not decoration.** N3 measured the tail throughput of the *record
destination*; recording this rehearsal somewhere else measures a different disk
and tells you nothing about tomorrow. If `TARGET` here is not the path you typed
in N3, one of the two steps is measuring the wrong volume.

```bash
# terminal 3, WHILE it records — does the events plumbing exist at all?
ros2 topic list | grep -E '^/events/'
```

**EXPECTED.** Exactly **one** `.mcap` file in `$TARGET/tonight_n4/`; no split
messages; per-topic counts matching the publisher's `PUBLISHED` line.

```text
RECORD  Publisher PUBLISHED line ................... ______________________
RECORD  ros2 topic list | grep /events/ ............ ______________________
RECORD  Number of .mcap files produced ............. ______   (expected: 1)
RECORD  Total bag size on disk ..................... ______ GiB
RECORD  Any recorder warning/error text ............ ______________________
```

### N4e · Verify — counts, splits, and whether the storage config was applied

```bash
TARGET=/data                                # <-- same path as N0, N3 and N4d
ros2 bag info "$TARGET/tonight_n4"
ls -l "$TARGET/tonight_n4/"

# was zstd actually used? weak check, no new packages:
strings -n 4 "$TARGET"/tonight_n4/*.mcap | head -40 | grep -i -E 'zstd|lz4' || echo 'NO COMPRESSION STRING FOUND IN HEADER'
# strong check, only if the mcap CLI or python package is already available:
mcap info "$TARGET"/tonight_n4/*.mcap 2>/dev/null || echo 'mcap CLI not available'
```

**EXPECTED.** `Storage id: mcap`; **six** `/tonight/*` topics with the published
counts; `/events/write_split` present with **0** messages.

```text
RECORD  ros2 bag info — paste it:
______________________________________________________________________

RECORD  /tonight/color   recorded ______ / published ______ = ______ %
RECORD  /tonight/depth   recorded ______ / published ______ = ______ %
RECORD  /tonight/ir_left recorded ______ / published ______ = ______ %
RECORD  /tonight/ir_right recorded ______ / published ______ = ______ %
RECORD  /tonight/cloud   recorded ______ / published ______ = ______ %
RECORD  /tonight/front_cam recorded ______ / published ______ = ______ %
RECORD  /events/write_split message count .......... ______  (expected 0)
RECORD  /events/messages_lost present? ............. ______
RECORD  Compression evidence ...................... ______________________
```

**STOP / BRANCH.**

| Finding | Branch |
|---|---|
| One file, counts ≥ 99 %, zero splits | **rosbag2 can be primary.** Copy this exact command line into tomorrow's run sheet §3, changing only `-o` and the topic list. |
| **More than one `.mcap`, or `write_split` count > 0** | **STOP.** Splitting is the documented loss path and `--max-bag-size 0` was supposed to prevent it. Check for a `--max-bag-duration` default, a full disk, and the actual flag spelling in `--help`. Do not proceed to tomorrow with a recorder that splits. |
| **Recorded < published** | Messages were lost. **Separate transport loss from recorder loss before concluding**: the publishers use `sensor_data` QoS (BEST_EFFORT), which *permits* loss on the wire. Re-run the publisher with a RELIABLE profile (`qos_profile_system_default`); if loss disappears, it was DDS back-pressure, and the real drivers tomorrow will have the same property. If loss persists, it is the recorder, and the profile must come down (N3's ladder). |
| **`/events/messages_lost` does not exist** | Record it **ABSENT** — do not invent it. Consequence, and it matters: per-channel loss provenance must then come from the `parcel-capture` **sidecar's** per-channel counts, which is exactly why the sidecar survives the D-2 rework as the attestation layer (`../RISK_ASSESSMENT.md:41-45`). Write that into tomorrow's plan. |
| **No compression string found** | The storage config may have been ignored. Mark **UNVERIFIED**, not "applied". A bag that is bigger than expected is the corroborating symptom. |
| Disk fills mid-run | This is N3's answer arriving late. Stop, delete, re-run shorter, and re-read N3. |

**Clean up:** `rm -rf "$TARGET/tonight_n4"` and record the freed space — but
**not until N4f has run**, because N4f reuses the same publisher-free command
line and you want both bags on the same disk state.

### N4f · Record the **REAL driver topics** — the only end-to-end proof on the sheet

**WHY.** N4a–N4e proved the *recorder*, driven by a synthetic publisher written
tonight. It did not prove that a **driver node's** topics reach the recorder, and
those are two different things: a real driver has different QoS, different
burstiness, a different message type, an image-transport plugin, and it competes
with the recorder for the same CPU. **[REPO]**
`scripts/parcel_capture/rosbag2.py:132-145` is explicit that a `DRIVER_NODE`
topic and a synthetic topic have *"three different failure modes, three different
remedies"*. Sixty seconds of the real thing is worth ten minutes of the fake one
— and it is the last chance to discover that a topic name on tomorrow's record
command line is wrong.

**Prerequisite:** N2e's driver is running (and, if N5b already ran, the L2 node
too). This step records **whatever is actually there** and says so.

```bash
# ON THE ORIN — terminal 2. Driver(s) from N2e / N5b must be RUNNING.
source /opt/ros/humble/setup.bash
mkdir -p ~/tonight                          # PRE-3 made it; do not depend on that
TARGET=/data                                # <-- same path as N3 and N4d

# 1. what actually exists right now — this list is the artifact, keep it
ros2 topic list | tee ~/tonight/n4f_topics.txt

# 2. build the record list from the topics that EXIST, not from the plan.
#    WIDEN THIS PATTERN if N2e-3 or N5b reported different namespaces — the
#    whole point of step 1 is that the plan's names may be wrong.
TOPICS=$(grep -E '^/(camera|unilidar)/' ~/tonight/n4f_topics.txt | tr '\n' ' ')
echo "RECORDING: $TOPICS"

# 3. the same command line as N4d, only the topic list differs
timeout 60 ros2 bag record -s mcap \
  --storage-config-file ~/tonight_mcap.yaml \
  --max-bag-size 0 \
  --max-cache-size 536870912 \
  --disable-keyboard-controls \
  -o "$TARGET/tonight_n4f" \
  $TOPICS /events/write_split /events/messages_lost

ros2 bag info "$TARGET/tonight_n4f"
```

**EXPECTED.** One `.mcap`. Every `/camera/camera/*` topic present with a count
near `60 s × its N2e rate` — ≈1,800 for each 30 Hz image topic. `Storage id:
mcap`. No splits.

```text
RECORD  ros2 topic list (the /camera/ and /unilidar/ lines) — paste:
______________________________________________________________________

RECORD  RECORDING: line (the topics actually passed) — paste:
______________________________________________________________________

RECORD  ros2 bag info — paste it:
______________________________________________________________________

RECORD  colour recorded ______ / expected ~1800 = ______ %
RECORD  depth  recorded ______ / expected ~1800 = ______ %
RECORD  infra1 recorded ______ / expected ~1800 = ______ %
RECORD  infra2 recorded ______ / expected ~1800 = ______ %
RECORD  accel  recorded ______   gyro recorded ______
RECORD  L2 cloud recorded ______   L2 imu recorded ______   (or NOT RUN)
RECORD  Bag size for 60 s ......................... ______ MiB
RECORD  Implied whole-rig rate (size / 60) ........ ______ MiB/s
```

**STOP / BRANCH.**

| Finding | Branch |
|---|---|
| All driver topics present, counts ≥ 99 % of `60 × rate` | **The driver→recorder path is proven.** Transcribe the topic list **verbatim** into tomorrow's run sheet §3. This is the sheet's strongest single result. |
| **`RECORDING:` line is empty** | No driver topic exists. Go back to N2e-3 — you are about to record nothing tomorrow and this is how you find out tonight rather than at 10:30. |
| **Some topics recorded 0 messages** | The recorder subscribed to a name nothing publishes, **and it did not complain** — this is the exact silent failure `rosbag2.py:222-228` warns about. Record which, and correct the name. |
| **Implied rate is far below `../BANDWIDTH_BUDGET.md` §1's 91.87 MiB/s** | Expected, and not a failure: this bag has no dog topics and possibly no L2, and the mcap storage config compresses. Record the number anyway — it is the first real datapoint about the *recorder's* throughput on this Jetson, which `../BANDWIDTH_BUDGET.md` §2 names as the only ceiling that binds the session and the only one nobody has measured. |
| Splits, or `messages_lost` non-zero | Same branches as N4e, but now with a real publisher — which makes them much more serious. Do not proceed to tomorrow with a recorder that drops the camera. |

**Clean up:** `rm -rf "$TARGET/tonight_n4f" "$TARGET/tonight_n4"`, and now record
the freed space.

---

## N5 · L2 BENCH — read the add-on LiDAR on a bench, no dog

**WHY.** **[REPO]** `../CHANNEL_MATRIX.md` and
`../PHYSICAL_SESSION_PLAN.md`: the add-on **L2 is a different SDK and a
different transport** from the dog's built-in unit — `unilidar_sdk2` over its
own Ethernet/UDP or `/dev/ttyACM0`, versus `utlidar/cloud` on the robot's DDS.
Two LiDARs at a measured relative extrinsic is the session's
**cross-validation** asset. **[REPO]** `../PSB_STATUS.md:358` and
`scripts/parcel_capture/preflight.py` both already say *"build unilidar_sdk2
on the Orin and put its Python binding on PYTHONPATH"* — **no one has done it.**
It needs no dog: power, a network cable, and a bench.

> ### ⚠ ORDERING — do **N6a and N6b first**, then come back here
>
> This step's `ping 192.168.1.2` needs the second-NIC address that **N6b**
> assigns, and N6 is *after* N5 on this sheet. That is a real ordering defect in
> the previous revision: N5 consumes an artifact N6 produces. Fix it by doing the
> two network sub-steps out of order — **N6a** (discover interface names) and
> **N6b** (pin `192.168.1.1/24` on the L2 NIC) — before N5a's `ping`. The build
> below needs no network beyond `git clone`, so start it first and configure the
> NIC while it compiles.
>
> ```text
> RECORD  N6a/N6b done before N5's ping? (yes / no) .. ______
> ```

### N5a · Vendor SDK example — does the L2 talk to *anything*?

```bash
# ON THE ORIN
sudo apt-get install -y cmake build-essential git
cd ~ && git clone https://github.com/unitreerobotics/unilidar_sdk2.git
cd unilidar_sdk2 && cat README.md | head -60      # <- the build target names live here
mkdir -p build && cd build && cmake .. && make -j4
ls -l                                              # record the example binaries produced
```

**[UNVERIFIED-SYNTAX].** Directory layout, CMake root, and example target names
differ between SDK revisions and could not be checked on the dev box. **Read the
repository's own README and use its target names.** The requirement is: *build
it, run its example, see a cloud and see IMU samples.*

Then, with the L2 on the second NIC configured in **N6b** (host `192.168.1.1/24`,
L2 factory `192.168.1.2`) — which, per the ordering note above, you did before
starting this step:

```bash
ping -c 3 192.168.1.2
./<example_target_from_the_readme>
```

**EXPECTED.** Point counts per scan at ≈10–20 Hz and IMU samples at ≈200 Hz.

```text
RECORD  git commit of unilidar_sdk2 cloned ......... ______________________
RECORD  Build result (clean / warnings / failed) ... ______________________
RECORD  Example target actually run ................ ______________________
RECORD  L2 reachable at 192.168.1.2? ............... ______
RECORD  Points per scan / scan rate ................ ______ / ______ Hz
RECORD  IMU sample rate observed .................... ______ Hz
RECORD  IMU |accel| at rest ......................... ______ m/s²
RECORD  IMU |gyro|  at rest ......................... ______ rad/s
RECORD  L2 firmware / serial if the tool prints it .. ______________________
```

**STOP / BRANCH.**

| Finding | Branch |
|---|---|
| Cloud + plausible IMU | Good. Record the binding path for tomorrow's `PYTHONPATH`. |
| **Build fails** | Not a session-stopper, but write the consequence down: the add-on L2 has **no reader tomorrow**, so the **two-LiDAR extrinsic — the cross-validation asset — is not captured, and it is unrecoverable once the bracket comes off.** Mount and tape-measure it anyway ([MOUNT_GEOMETRY_SHEET.md](MOUNT_GEOMETRY_SHEET.md)) so a later session can still use the geometry. Owner decides whether to keep fighting the build tonight. |
| L2 not reachable | Try the serial path (`/dev/ttyACM0`, `ls -l /dev/ttyACM*`), and re-check N6's second-NIC configuration. Factory IP may differ from `192.168.1.2` — record what it actually is. |
| Cloud OK, **IMU absent or implausible** | Apply the same plausibility gate as N2d: `|accel|` = 9.81 ± 1, `|gyro|` < 0.05. **[REPO]** `../RISK_ASSESSMENT.md:137-140` — `utlidar/imu` has two independent reports of ~1e24 m/s². Absurd values are **DEGRADED**, never `PRESENT`. |
| `cmake`/`git` not installed | Installing them is permitted by PRE-2. Log it in the change ledger. |

### N5b · The L2 **ROS node** — because the SDK example is not the session path

**WHY.** Exactly the same reason as N2e. The SDK example in N5a prints a cloud to
a terminal; it does not publish a topic, and `ros2 bag record` records topics.
**[REPO]** `scripts/parcel_capture/rosbag2.py:340-357` names the two L2 topics
the recorder of record is configured to record — `/unilidar/cloud` and
`/unilidar/imu` — and gives the launch command that produces them:
`ros2 launch unitree_lidar_ros2 launch.py`. Nothing on this sheet has ever built
or launched that node.

`unilidar_sdk2` ships the ROS 2 wrapper **inside the repository you already
cloned in N5a**, as a colcon workspace (commonly `unitree_lidar_ros2/`) that is
built separately from the plain-CMake SDK.

```bash
# ON THE ORIN
source /opt/ros/humble/setup.bash
sudo apt-get install -y python3-colcon-common-extensions
cd ~/unilidar_sdk2
ls                                     # find the ROS 2 workspace directory
cat unitree_lidar_ros2/README.md 2>/dev/null | head -40 || ls -R | head -60
cd ~/unilidar_sdk2/unitree_lidar_ros2
colcon build --symlink-install
source install/setup.bash
ros2 pkg list | grep -i unitree
ls src/*/launch/ 2>/dev/null || find . -name '*launch*' | head
```

**[UNVERIFIED-SYNTAX], and more so than most.** The workspace directory name, the
package name and the launch-file name all differ between SDK revisions, and the
dev box has no copy of the repository to check against. **Read the SDK's own
README and use its names.** The requirement is: *a node publishes a cloud topic
and an IMU topic, and `ros2 topic hz` shows a rate.*

**Configure the transport before launching.** The launch file carries the IP/port
or the serial device; it must match what N5a and N6b established. Edit the launch
file's parameters (or pass them on the command line) — do not launch with factory
defaults and hope.

```bash
# terminal 1 — leave running
ros2 launch unitree_lidar_ros2 launch.py

# terminal 2
source /opt/ros/humble/setup.bash
ros2 topic list | grep -iE 'unilidar|lidar'
for t in /unilidar/cloud /unilidar/imu ; do
  echo "===== $t"; ros2 topic type "$t" 2>&1
  timeout 15 ros2 topic hz -w 50 "$t" 2>&1 | tail -3
done
```

**EXPECTED.** `/unilidar/cloud` at ≈10–20 Hz carrying
`sensor_msgs/msg/PointCloud2`; `/unilidar/imu` at ≈200 Hz carrying
`sensor_msgs/msg/Imu`.

```text
RECORD  ROS 2 workspace path inside unilidar_sdk2 ... ______________________
RECORD  colcon build result ......................... ______________________
RECORD  Launch file actually used ................... ______________________
RECORD  Transport configured (UDP ip:port / ttyACM) . ______________________
RECORD  cloud topic name ______________________  hz ______  type ____________
RECORD  imu   topic name ______________________  hz ______  type ____________
RECORD  Do these match rosbag2.py's /unilidar/cloud and /unilidar/imu? ______
```

**STOP / BRANCH.**

| Finding | Branch |
|---|---|
| Both topics, plausible rates | **GO.** Leave it running and go to **N4f**, which records it. Transcribe the topic names and the `source install/setup.bash` line into tomorrow's run sheet §3 — the recorder's shell must have that overlay sourced or the node is not launchable at 09:00. |
| **Topic names differ** from `/unilidar/cloud` / `/unilidar/imu` | Record the real names. Same silent failure as N2e-3: a recorder given a wrong name subscribes to nothing and says nothing. |
| **`colcon build` fails** | Not a session-stopper, but the consequence is now bigger than N5a's: the add-on L2 has **no path into the bag at all**, so the two-LiDAR extrinsic — the cross-validation asset — is not captured, and it is unrecoverable once the bracket comes off. If N5a worked, the fallback is to record the L2 through `parcel-capture` only and accept a second, non-rosbag2 artifact — **write that acceptance down**. Mount and tape-measure the geometry regardless ([MOUNT_GEOMETRY_SHEET.md](MOUNT_GEOMETRY_SHEET.md)). |
| **Node launches but publishes nothing** | The transport parameters do not match the device. Re-check against N5a: if the SDK example reads the L2 and the ROS node does not, it is configuration, not hardware. |
| No ROS 2 wrapper in the repository at all | Record it. Then the L2 is a `parcel-capture`-only channel tomorrow, with the same written acceptance as the build-failure branch. |

---

## N6 · NETWORK — pin it tonight, because "zero topics visible" costs a morning

**WHY.** **[REPO]** `../RISK_ASSESSMENT.md:121-125`: CycloneDDS bound to the
wrong NIC is *the* classic zero-topics failure, and `configs/robot.yaml:128`
**still carries the placeholder**:

```
128:    interface: enp3s0  # replace with the dedicated robot Ethernet NIC on this host
```

**Do not type `enp3s0`. It is a placeholder from a different machine.** Discover
the real name. (Note there is a **second** copy at `configs/robot.yaml:342`
under `wifi_cards.robot.interface` — an operator who fixes only `:128` leaves a
stale name behind. Both are the owner's to change; this sheet only records the
discovered name.)

### N6a · Discover the real interface names — do not guess

```bash
# ON THE ORIN
ip -o link show
ip -o addr show
ethtool <candidate> 2>/dev/null | grep -E 'Speed|Link detected'
```

```text
RECORD  Wired NIC intended for the Go2 LAN ......... ______________________
RECORD  Second NIC intended for the L2 ............. ______________________
RECORD  Is there a second Ethernet interface at all? ______
```

**STOP / BRANCH — this one is likely.** Most Orin NX carriers have **one**
Ethernet port. If there is no second NIC: (a) a **USB-Ethernet adapter** — do
you have one? *Tonight* is when you find out; (b) an **IP alias** on the single
NIC (`sudo ip addr add 192.168.1.1/24 dev <iface>`) — works, but the dog and the
LiDAR then share one link and one bandwidth budget; (c) run the L2 over
**`/dev/ttyACM0`** serial instead of Ethernet. Choose tonight and record which.

### N6b · Pin the addresses

```bash
# ON THE ORIN — Go2 LAN
sudo ip addr add 192.168.123.222/24 dev <go2_iface>
sudo ip link set <go2_iface> up

# L2 LAN on a SECOND NIC (or alias), and NO default route via it
sudo ip addr add 192.168.1.1/24 dev <l2_iface>
sudo ip link set <l2_iface> up

ip -o addr show
ip route
```

**EXPECTED.** Both addresses present. **`ip route` shows no `default` via the L2
interface.**

```text
RECORD  ip -o addr show (the two relevant lines):
______________________________________________________________________
RECORD  ip route:
______________________________________________________________________
RECORD  Any default route via the L2 NIC? ......... ______  (must be: no)
```

**Why `192.168.1.x` needs care.** **[REPO]**
`../RISK_ASSESSMENT.md:123-124`: the L2's factory `192.168.1.2` collides with
the Go2's own `192.168.1.7` **and** with the commonest home subnet. Keeping the
L2 on its own NIC with no default route is what stops the Orin from routing
robot traffic to your house — or your house's traffic to the LiDAR.

### N6c · Wi-Fi off, everywhere

```bash
# ON EVERY HOST — Orin, laptop
nmcli radio wifi off ; nmcli radio
ip route | grep -c default          # expect 0 on the Orin, or 1 only via a deliberate uplink
```

```text
RECORD  Orin wifi state ............................ ______
RECORD  Laptop wifi state .......................... ______
RECORD  Laptop home subnet (does it collide with 192.168.1.0/24?) ______
```

**STOP / BRANCH.** If the laptop's home network **is** `192.168.1.0/24`, that is
the collision the risk assessment names. Wi-Fi off resolves it; leaving it on
will produce a LiDAR that pings but delivers nothing, and that failure looks
exactly like a broken LiDAR.

### N6d · Domain and CycloneDDS binding

```bash
# ON THE ORIN
env | grep -E 'ROS_DOMAIN_ID|RMW_IMPLEMENTATION|CYCLONEDDS_URI' || echo '(none set)'
grep -rn 'ROS_DOMAIN_ID' ~/.bashrc ~/.profile /etc/environment 2>/dev/null || echo '(no rc entries)'
```

**EXPECTED.** `ROS_DOMAIN_ID` **unset** — i.e. domain 0, which matches
**[REPO]** `configs/robot.yaml:129 domain_id: 0`.

```bash
cat > ~/cyclonedds.xml <<XML
<?xml version="1.0" encoding="UTF-8" ?>
<CycloneDDS xmlns="https://cdds.io/config">
  <Domain id="any">
    <General>
      <Interfaces>
        <NetworkInterface name="GO2_IFACE" priority="default" multicast="default" />
      </Interfaces>
    </General>
  </Domain>
</CycloneDDS>
XML
sed -i "s/GO2_IFACE/<go2_iface>/" ~/cyclonedds.xml
cat ~/cyclonedds.xml
export CYCLONEDDS_URI=file://$HOME/cyclonedds.xml
```

**[UNVERIFIED-SYNTAX] and distro-dependent.** The `<Interfaces><NetworkInterface
name=…>` form is Cyclone 0.10+ (Humble). If N0 found **Foxy**, the older schema
is `<General><NetworkInterfaceAddress><iface></NetworkInterfaceAddress></General>`.
Use the one that matches what N0 found.

**VERIFY THE BINDING — do not trust the file.** This works with no dog:

```bash
# terminal 1
sudo tcpdump -i <go2_iface> -n udp portrange 7400-7500
# terminal 2
source /opt/ros/humble/setup.bash
export CYCLONEDDS_URI=file://$HOME/cyclonedds.xml
ros2 daemon stop; ros2 topic pub -r 2 /tonight/ping std_msgs/msg/String '{data: ping}'
```

**EXPECTED.** Discovery traffic appears on `<go2_iface>` in terminal 1. Then
repeat the tcpdump on the **other** interface and see **nothing** — that
negative control is what actually proves the binding.

```text
RECORD  ROS_DOMAIN_ID ............................. ______  (expected: unset)
RECORD  CYCLONEDDS_URI ............................ ______________________
RECORD  Packets seen on the intended NIC? ......... ______
RECORD  Packets seen on the OTHER NIC (must be no)  ______
RECORD  Where CYCLONEDDS_URI is exported for tomorrow (rc file / run sheet) ___
```

**STOP / BRANCH.** Discovery on the wrong NIC, or on both → the config is not
being read (check the `file://` URI, the absolute path, and that the export
survives into the shell that will run the recorder). Fix it tonight; tomorrow
this presents as *"`ros2 topic list` is empty and the dog looks dead"*.

### N6e · Stage the fallback where you can find it at 09:00

Write the discovery-failure command on the run sheet, ready to paste:

```bash
sudo tcpdump -i <iface> -n udp portrange 7400-7500
```

```text
RECORD  Transcribed into STAGE0_RUN_SHEET §3? ...... ______
```

> **Explicitly not done tonight (owner decision if you disagree).** No link test
> against the actual Go2. PRE-1 forbids attaching computers to that LAN before
> the firmware version is cleared, and the card's premise is *no robot tonight*.
> N6 therefore pins and verifies **configuration**; the ping-the-dog test is
> tomorrow's first network action. If the owner wants that de-risked tonight, it
> requires PRE-1 to have read **≥ 1.1.13** first, and it is a departure from the
> no-robot rule that should be recorded as such.

### N6f · `unitree_ros2` message packages — **without these there are no dog topics at all**

**WHY.** The dog needs no driver node of ours — its own firmware publishes.
But `ros2 bag record` cannot record a topic whose **message type it cannot
resolve**: it creates a generic subscription against the type support library,
and if `unitree_go` / `unitree_api` are not built and sourced, every dog topic on
the record command line is skipped. **[REPO]**
`scripts/parcel_capture/rosbag2.py:183-210` states the prerequisite for every DDS
row of the matrix as *"dog powered on, on the same subnet, with the
**`unitree_ros2` overlay sourced** and CycloneDDS bound to the right NIC"*, and
**[REPO]** `scripts/parcel_capture/ingest/dds.py:5-11` records that
*"`unitree_ros2` carries every topic here"*. That is **10.2% of the byte budget**
and **every** channel that carries the dog's IMU, its foot forces, its battery,
its only device clock and its only proximity sensing.

This is a **build and an interface check**. It touches no robot, needs no dog,
and it is the one step whose failure tomorrow is completely silent: the recorder
starts, writes a bag, and the bag simply has no `unitree_go` messages in it.

> **Do not install anything into `.parcel/`.** This is a colcon workspace in the
> Orin user's home directory. It is a message-definition package set — **not**
> `unitree_sdk2py`, and nothing here creates a publisher, a `ControlManager`, a
> lease or a motion client. Build the **interface** packages only.

```bash
# ON THE ORIN
source /opt/ros/humble/setup.bash
sudo apt-get install -y python3-colcon-common-extensions ros-$(ls /opt/ros | head -1)-rmw-cyclonedds-cpp
cd ~ && git clone https://github.com/unitreerobotics/unitree_ros2.git
cd ~/unitree_ros2 && cat README.md | head -60      # <- the real build steps live here
ls cyclonedds_ws/src 2>/dev/null || ls
```

**[UNVERIFIED-SYNTAX].** The repository's layout has changed across revisions:
some carry `cyclonedds_ws/src/{unitree_go,unitree_api,cyclonedds}`, others a flat
`src/`. **Follow the repository's own README.** The typical shape is: build the
CycloneDDS dependency first, then the two interface packages.

```bash
# build the interface packages (names from the README, not from memory)
cd ~/unitree_ros2/cyclonedds_ws
colcon build --packages-select unitree_go unitree_api
source install/setup.bash
```

**VERIFY — the interfaces, not the build log:**

```bash
ros2 interface list | grep -iE 'unitree' | head -20
ros2 interface show unitree_go/msg/LowState  | head -30
ros2 interface show unitree_go/msg/SportModeState | head -30
ros2 interface show unitree_go/msg/Go2FrontVideoData | head
```

**EXPECTED.** `unitree_go/msg/LowState` shows `imu_state`, `motor_state`,
`bms_state`, `foot_force`, `foot_force_est`, `tick`, `wireless_remote`,
`power_v`, `power_a` — and **no timestamp field**, which is
`../CHANNEL_MATRIX.md` Table B row 3's whole point.

```text
RECORD  unitree_ros2 git commit cloned ............. ______________________
RECORD  colcon build result ........................ ______________________
RECORD  ros2 interface list | grep unitree — count .. ______
RECORD  LowState has power_v / power_a? ............. ______
RECORD  LowState has wireless_remote[40]? ........... ______
RECORD  LowState has foot_force AND foot_force_est? . ______
RECORD  LowState has ANY timestamp field? ........... ______  (expected: no)
RECORD  motor_state array length .................... ______  (expected: 20)
RECORD  SportModeState has range_obstacle[4]? ....... ______
RECORD  SportModeState has stamp (TimeSpec)? ........ ______
RECORD  Go2FrontVideoData fields .................... ______________________
RECORD  Overlay source line for tomorrow ............ ______________________
```

**STOP / BRANCH.**

| Finding | Branch |
|---|---|
| Interfaces build and show | **GO**, and this is a *bonus result*: you have just settled several of `../CHANNEL_MATRIX.md`'s open questions **electronically, tonight, without the dog** — the two foot-force arrays, `power_v`/`power_a`, `wireless_remote[40]`, `range_obstacle[4]`, and whether `LowState` really has no timestamp. Every one of those was `CONFIRMED`-from-documentation and is now read off an IDL. Transcribe the `source ~/unitree_ros2/cyclonedds_ws/install/setup.bash` line into tomorrow's run sheet §3 — **the shell that runs the recorder must have it.** |
| **A field the matrix asserts is missing** | **Record it and wake the owner.** The budget's per-channel sizes and PS-A's channel table are both derived from these field lists (`../BANDWIDTH_BUDGET.md` §0, *"MESSAGE FIELD LISTS"*). A wrong field list moves a budget row; a wrong *channel* moves the plan. |
| **`colcon build` fails** | **STOP. Owner decision.** With no `unitree_go` interfaces, `ros2 bag record` records **no dog topic at all** and the D-2 fix covers only the D455 and the L2. The fallback is `parcel-capture`'s raw-DDS path for the dog — which is a second artifact in a format no downstream tool reads, i.e. exactly the defect this tranche exists to remove. Write the acceptance down; do not discover it tomorrow. |
| **`RMW_IMPLEMENTATION` conflict** | The Unitree stack expects CycloneDDS. Record what `echo $RMW_IMPLEMENTATION` says in the shell that will run the recorder, and make it consistent with N6d's `CYCLONEDDS_URI`. Two different RMWs in two terminals is another silent zero-topics failure. |

> **What this step cannot settle.** Whether the *robot* publishes these topics.
> Building an IDL proves the recorder can serialise a message; it says nothing
> about whether our unit emits one. The service-gated rows
> (`sportmodestate`, `utlidar/robot_pose`, `utlidar/voxel_map_compressed`,
> `utlidar/robot_odom`) stay `VERIFY_IN_SESSION` after tonight.

---

## N7 · PYTHON 3.10 IMPORT CHECK — the first real test of a load-bearing claim

**WHY.** **[REPO]** `../PSA_STATUS.md:121-124` is unusually honest and worth
quoting: *"No Python 3.10 process was executed. There is no 3.10 interpreter on
this host."* The 3.10 claim behind `src/parcel_robot/capture/` is **static
only** — `ast.parse(feature_version=(3,10))` plus a symbol allow-list. PS-A
names the fix itself at `../PSA_STATUS.md:305-306`: *"The first real
verification is running `python3.10 -c 'import parcel_robot.capture'` on the
Orin."* That is fifteen minutes, and it is tonight.

### N7a · Get the repository onto the Orin

```bash
# ON THE DEV BOX
rsync -av --exclude '.parcel/' --exclude '__pycache__/' --exclude '.git/' \
  /home/jaewoo-jang/Desktop/Projects/Parcel/ <orin_user>@<orin_ip>:~/Parcel/
```

**`--exclude '.parcel/'` is not optional.** That venv is a 3.14 x86 venv and
copying it to the Orin is meaningless; more importantly, it is the venv whose
**emptiness** is the motion guarantee, and it has no business on the robot host.

```text
RECORD  rsync completed at ......................... ______ UTC
RECORD  Bytes transferred .......................... ______
RECORD  Repo path on the Orin ...................... ______________________
```

### N7b · Import the capture package under 3.10

```bash
# ON THE ORIN
python3.10 --version || python3 --version
cd ~/Parcel
PYTHONPATH=$PWD/src python3.10 -c "import parcel_robot.capture; print('IMPORT OK')"
```

**EXPECTED.** `IMPORT OK`. (On Ubuntu 22.04 the default `python3` **is** 3.10.x
— if `python3.10` is not a separate binary, confirm the version and use
`python3`.)

```text
RECORD  Interpreter used / version ................. ______ / ______
RECORD  Import result ............................... ______________________
RECORD  Full traceback if it failed:
______________________________________________________________________
```

### N7c · The leaf pin, dynamically, for the first time

```bash
PYTHONPATH=$PWD/src python3.10 -c "
import sys
base = set(sys.modules)
import parcel_robot.capture
new = sorted(m for m in set(sys.modules) - base if '.' not in m)
std = set(sys.stdlib_module_names)
print('NEW TOP-LEVEL MODULES:', new)
print('NON-STDLIB:', [m for m in new if m not in std and not m.startswith(('parcel_robot','_'))])
"
```

**EXPECTED.** `NON-STDLIB: []`.

```text
RECORD  NEW TOP-LEVEL MODULES ...................... ______________________
RECORD  NON-STDLIB .................................. ______  (expected: [])
```

**STOP / BRANCH.**

| Finding | Branch |
|---|---|
| `IMPORT OK`, `NON-STDLIB: []` | The 3.10 claim is now **measured**, not static. Record it — it is the first dynamic confirmation and it belongs in tomorrow's evidence. |
| **ImportError / SyntaxError** | **Not a stop, but it is a finding tonight rather than a debugging session tomorrow.** Record the module and the full traceback verbatim. PS-A's static check has a known hole (`../PSA_STATUS.md:300-306`): it catches syntax and enumerated post-3.10 names, but **not behavioural differences**. This is exactly the case it was waiting for. |
| **`NON-STDLIB` non-empty** | The leaf pin is broken on the Orin. Record the module names. The capture package is supposed to be stdlib-only plus `parcel_robot.evidence_origin` (`../PSA_STATUS.md:148-152`). |
| No 3.10 interpreter present | Record the version that **is** present. If N0 found Foxy/20.04, the static pin is aimed at the wrong Python and the owner needs to know. |

---

## 2 · Results ledger — one page, fill as you go

| Step | Result | Number that matters | Branch taken | Time |
|---|---|---|---|---|
| PRE-1 firmware | PASS / FAIL / NOT RUN | version ______ | ______ | ____ |
| PRE-3 change ledger | DONE / NOT DONE | console access? ____ | ______ | ____ |
| N0 identity | PASS / FAIL / NOT RUN | JetPack ____ / ROS ____ / py ____ | ______ | ____ |
| **N0b driver packages** | PASS / FAIL / NOT RUN | realsense2_camera candidate ______ | ______ | ____ |
| N1 usbfs | PASS / FAIL / NOT RUN | usbfs_memory_mb = ______ | ______ | ____ |
| N2a install | PASS / FAIL / NOT RUN | pyrealsense2 ______ | ______ | ____ |
| N2b metadata | HW CLOCK / SYSTEM TIME | domain ______ | ______ | ____ |
| N2c frame count | PASS / DEGRADED / FAIL | worst stream ______ % | ______ | ____ |
| N2d IMU | PRESENT / DEGRADED / ABSENT | \|a\| ______ \|g\| ______ | ______ | ____ |
| **N2e ROS driver** | PASS / FAIL / NOT RUN | **6 topics? ______ , worst hz ______** | ______ | ____ |
| N3 fio | PASS / DEGRADE / FAIL | **tail ______ MiB/s** (need 91.87) | ______ | ____ |
| N4 rosbag2+mcap (synthetic) | PASS / FAIL / NOT RUN | worst topic ______ %, splits ______ | ______ | ____ |
| **N4f real driver topics** | PASS / FAIL / NOT RUN | **topics recorded ______ , MiB/s ______** | ______ | ____ |
| N5a L2 SDK bench | PASS / DEGRADE / FAIL | ______ Hz cloud, IMU ______ | ______ | ____ |
| **N5b L2 ROS node** | PASS / DEGRADE / FAIL | **cloud ______ Hz, imu ______ Hz** | ______ | ____ |
| N6a–e network | PASS / FAIL / NOT RUN | iface ______ , binding ______ | ______ | ____ |
| **N6f unitree_ros2 msgs** | PASS / FAIL / NOT RUN | **interfaces ______ , LowState ok? ____** | ______ | ____ |
| N7 py3.10 | PASS / FAIL / NOT RUN | NON-STDLIB ______ | ______ | ____ |

```text
Filled by ____________________  on ____________  finished at ______ UTC
Owner notified of STOP branches (list them, or "none"): ______________________
```

---

## 3 · Hand-off into tomorrow — transcribe these, do not remember them

**[REPO]** `README.md:33-34` (this folder): *"Transcribe the exact commands into
STAGE0_RUN_SHEET §3. An untranscribed command is a NOT MEASURED."* The same rule
applies to tonight's outputs.

| From | Into | What exactly |
|---|---|---|
| PRE-1 | `STAGE0_RUN_SHEET.md` §1 run header, and §4 precondition **P1** (`:142`) | firmware version + who read it + when |
| N0 | §4 precondition **P2** (`:143`) | JetPack version as an **observation**, not a validated golden image |
| N0 `df -h` | §4 **P6**, and the budget check | free space on the record target |
| N1 | §3 | if N1a-only: **"re-apply `usbfs_memory_mb` after every boot"** |
| N2c | §3 and §7 C0.3 | **the D455 profile that survived**, and the per-stream deficits |
| N2b | §3, and PS-C's clock plan | whether `source_timestamp_ns` is real or must be **null** for D455 |
| **N2e** | §3 | the **verbatim `ros2 launch realsense2_camera` line** with the profile-argument spelling that worked, **and the six topic names `ros2 topic list` actually printed** — if any differs from `scripts/parcel_capture/rosbag2.py`'s `DRIVER_TOPICS`, say so loudly: a wrong name records nothing and reports nothing |
| N3 | §3 | **tail MiB/s** and the profile it permits |
| N4 | §3 | the **verbatim** `ros2 bag record` line that worked, with the flag substitutions |
| **N4f** | §3 | that driver topics actually reached the recorder, and the **observed MiB/s** — the only local datapoint about the recorder ceiling in `../BANDWIDTH_BUDGET.md` §2 |
| N5a | §3 and `MOUNT_GEOMETRY_SHEET.md` | the L2 binding path; whether the L2 is readable at all |
| **N5b** | §3 | the L2 **launch command**, its topic names, and the `source …/install/setup.bash` line the recorder's shell needs |
| N6 | §3 and §7 C0.2 | interface names, `CYCLONEDDS_URI` path, the tcpdump fallback |
| **N6f** | §3 | the `source ~/unitree_ros2/…/install/setup.bash` line — **without it in the recorder's shell, not one dog topic lands in the bag** — plus every field-list answer read off the IDL |
| N7 | §7 C0.3 | that the capture package imports on the Orin's real interpreter |

> ### ⚠ Four of those rows have nowhere to go, and that is a finding for the owner
>
> `STAGE0_RUN_SHEET.md` §3 is a six-row table — **T1 preflight, T2 budget, T3
> clock map, T4 record, T5 sidecar, T6 rehearsal** — and every one of them is a
> `scripts/parcel_capture/` command. **There is no row for launching a ROS driver
> and no row for `ros2 bag record`.** But `ros2 bag record -s mcap` is the
> **recorder of record** (`../RISK_ASSESSMENT.md:39-45`), and it records nothing
> without the two driver launches and the `unitree_ros2` overlay.
>
> That file is **PS-F's** to edit and not this sheet's. Until it gains them,
> transcribe N2e / N5b / N6f / N4f into the run sheet's **§10 "Refusals, faults
> and surprises"** free-text area *and* onto a separate sheet of paper taped to
> the Orin, and tell the owner that §3 needs four rows:
>
> | Needed row | Command to transcribe | From |
> |---|---|---|
> | T7 | `ros2 launch realsense2_camera rs_launch.py …` | N2e-2 |
> | T8 | `ros2 launch unitree_lidar_ros2 launch.py` | N5b |
> | T9 | `source ~/unitree_ros2/…/install/setup.bash` | N6f |
> | T10 | `ros2 bag record -s mcap …` with the real topic list | N4d + N4f |
>
> **A recorder command with no transcription box is exactly the "untranscribed
> command is a NOT MEASURED" failure the run sheet warns about**, applied to the
> single most important command of the day.

**Anything that FAILED tonight goes to the owner tonight**, not into tomorrow's
first hour. Several branches above change what tomorrow *is*, and
`README.md:57` already names the branch that absorbs most of them —
**DEGRADE-MMP**, *mount, measure, photograph, record nothing* — a **legitimate
outcome**, and much better chosen at 22:00 than discovered at 11:00.

---

## 4 · What this sheet does not cover, and does not prove

- **Nothing here has been executed.** This document is blank paperwork written
  the day before. Every `RECORD:` field is empty. A filled field is an
  observation by whoever filled it; **this sheet asserts no measurement of its
  own.**
- **Every [EXT] claim is about other people's hardware.** The 16 MB `usbfs`
  default, the ~80 % RGB drop, the dead D455 IMU, the missing 3.11+ wheel, the
  DRAM-less NVMe knee, the L2 factory IP — all come from documentation, issue
  threads, and field reports via `../RISK_ASSESSMENT.md`. **None of them has
  been observed on our units.** Each step exists to replace a report with a
  measurement; a step that passes has *disconfirmed* the report for our
  hardware, which is a result, not a formality.
- **Several commands are [UNVERIFIED-SYNTAX]** and could not be checked: the dev
  box has no ROS, no Jetson, no RealSense, and none of `rclpy`, `mcap`,
  `pyrealsense2`, or `unilidar_sdk2`. Flags, YAML keys, and SDK target names may
  differ from what is written. **Run `--help` and read the SDK's own README; the
  requirement is the measurement, not the exact string.**
- **This sheet touches nothing on the dog's DDS.** The `rt/` topic-name
  mangling, the service-gating of `sportmodestate` / `utlidar/robot_pose` /
  `utlidar/voxel_map_compressed`, the 12-not-20 joint question, the two
  foot-force arrays, and the L1-vs-L2 identity of the **built-in** LiDAR are all
  **untouched and still open** (`../RISK_ASSESSMENT.md:49-76`). They are
  tomorrow's first 45 minutes and no amount of laptop work settles them.
- **A green N4 does not prove tomorrow's bag is good.** It proves this recorder,
  on this disk, with synthetic random payloads at a matched byte rate, kept up
  for ten minutes. Real drivers have different QoS, different burstiness,
  different CPU cost, and share the machine with four other subsystems.
- **A green N3 does not prove the session's write path.** `fio` measures the
  disk. The recorder adds encoding, chunking, compression, and an fsync cadence.
  **[REPO]** `../BANDWIDTH_BUDGET.md` §5 measured the full stack **on the dev
  host only** and explicitly declines to extrapolate to the Orin — and what it
  measured was `parcel-capture`, **not** `ros2 bag record`, which is the recorder
  of record. §2's rosbag2 ceiling has never been measured on any of our hardware;
  **N4f is the first and only local reading of it**, and it is 60 seconds long.
- **N2's ten minutes is not tomorrow's hour.** Thermal behaviour, USB contention
  with the LiDAR, and a moving robot are all absent tonight. **[REPO]**
  `../BANDWIDTH_BUDGET.md` §0 names the power/thermal bound as an explicit
  **unknown**, and it stays unknown after tonight.
- **A green N2e/N5b/N6f does not prove tomorrow's topics.** N2e proves a driver
  publishes when the camera is on a bench and nothing else is running. Tomorrow
  it competes with a second driver, a recorder, four other subsystems and a
  moving robot for one Orin. N6f proves the recorder can *serialise* dog
  messages; it proves nothing about whether our dog *emits* them, and every
  service-gated row stays `VERIFY_IN_SESSION`.
- **The driver topic names in N2e and N5b are [EXT] and unverified**, and this
  sheet says so at each step. They depend on launch arguments and on SDK
  revision. **The names `ros2 topic list` prints tonight are the truth**; the
  ones written here are a starting guess, and the failure mode of a wrong guess
  is silent — the recorder subscribes to nothing and reports nothing.
- **The byte-budget shares quoted in §1's callout (89.0% / 0.8% / 10.2%) are
  computed from a model, not measured.** They come from
  `../BANDWIDTH_BUDGET.md` §3, whose front-camera row is an `assumed_worst_case`
  that can move the headline by more than 10% on its own.
- **N7 proves an import, not a stack.** `import parcel_robot.capture` succeeding
  under the Orin's 3.10 says nothing about whether `scripts/parcel_capture/`
  runs there — those modules need `rclpy`, `pyrealsense2` and `mcap`, and the
  first time the full stack runs on the Orin is a separate step
  (`README.md:36`: *"The stack's first run must not be on the dog"*).
- **There is no restore path for the Orin** (PRE-2). Tonight's mutations are
  small and logged, but they are mutations of the **only** dock, and the
  two-dock rule that was supposed to make them safe **cannot be met**.
- **Passing every step does not authorise anything.** Nothing here arms
  anything, and a fully green sheet still leaves tomorrow governed by
  [SAFETY_BRIEF.md](SAFETY_BRIEF.md), [STAGE0_RUN_SHEET.md](STAGE0_RUN_SHEET.md)
  and the ratified checklist's stage ladder.
