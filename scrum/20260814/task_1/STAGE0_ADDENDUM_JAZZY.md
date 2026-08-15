# Stage-0 command addendum — ROS 2 JAZZY sheet (card S-2)

> # ⚠ DRAFT UNTIL H-1 — NOT YET OPERATIVE
>
> Nobody has executed a command on the Orin. Its ROS distro is an **assertion, not an observation**. Two sheets are generated: this one for ROS 2 **jazzy**, and one for ROS 2 **humble**.
>
> **Exactly one becomes operative** when the operator reports the observed distro from the H-1 identity dump (`cat /etc/nv_tegra_release; lsb_release -a; ls /opt/ros`). If H-1 reports `/opt/ros/jazzy`, this document is the sheet and `STAGE0_ADDENDUM_HUMBLE.md` is **VOID**. If it reports `/opt/ros/humble`, **this document is VOID** and `STAGE0_ADDENDUM_HUMBLE.md` is the sheet.
>
> If H-1 reports **anything else** — Foxy, JetPack 5.x, no ROS at all — **both are void.** Take REVISED_BOARD.md H-1's 'anything else' branch: STOP, report the exact output, and retarget. The generator refuses to render an unknown distro rather than defaulting to a plausible one.
>
> Regeneration after H-1 is one command:
>
> ```
> .parcel/bin/python -m scripts.parcel_capture.stage0_addendum --distro jazzy --emit-distro
> ```

> ## ⚠ GENERATED FILE — do not hand-edit
>
> Every command below is rendered by `scripts/parcel_capture/stage0_addendum.py::render_addendum()`. The recorder argv comes from `Rosbag2Plan(distro=…)`; the RealSense launch arguments and every topic name are DERIVED from `rosbag2.RECORDED_TOPICS` / `rosbag2.SUPPORT_TOPICS`; the camera profile is `budget.RECOMMENDED_PROFILE`. Hand-editing is a defect: `tests/test_stage0_addendum.py` reddens until it is reverted.

## 0 · What this is, and what it replaces

`scrum/20260814/task_1/README.md`'s opening assessment: *"Stage-0 command transcription has no first-class rows for the RealSense launch, L2 launch, Unitree overlay and actual `ros2 bag record` command."* Those four rows are **T7-T10**, and they are below. This document is **run-specific** and lives under this task; `scrum/20260813/task_1/session/STAGE0_RUN_SHEET.md` and `scrum/20260813/task_1/session/TONIGHT_CHECKLIST.md` are historical provenance and are not edited (working agreement 3).

Working agreement 7 is why this is generated: *operator commands are rendered from the distro-aware plan after `--verify-help`; they are not maintained as a second handwritten CLI in Markdown.* The historical sheets hard-code `--disable-keyboard-controls`, which Humble's recorder does not declare — argparse exits 2 and the session records zero bytes. That flag cannot reach this document: every rendered `ros2 bag record` line is checked against this distro's own recorder CLI at construction time, and an unsupported flag is a refusal before a byte of Markdown exists.

### Run parameters

| | |
|---|---|
| ROS 2 distro (DRAFT — H-1 confirms) | `jazzy` |
| Record target | `/data/parcel/stage0/take01` |
| Storage config (outside the record target) | `/data/parcel/stage0/mcap_storage.yaml` |
| Writer profile | `crash_safe` (chunking off) |
| Camera profile | `848x480@30 CDI` (colour + depth + infra1 + infra2 + IMU) |
| Topics on the record command line | 31 |
| of which S-1 support artifacts | 4 `camera_info` + 2 transform |

### Row index

| row | what it does | passes when |
|---|---|---|
| `T7.1` | Free the camera before the driver opens it | No process holds `/dev/video*`. |
| `T7.2` | Read the driver's own argument spelling — MANDATORY before T7.3 | A list of launch arguments containing EITHER the `<module>.<stream>_profile` form used in T7.3… |
| `T7.3` | Launch at the plan of record (848x480@30, colour+depth+IR pair+IMU) | The node starts and stays up. |
| `T7.4` | The topics, their types and their rates — including camera_info | All 10 topics exist. |
| `T7.5` | The calibration actually describes the stream being recorded | `width: 848` and `height: 480`, matching the profile T7.3 launched, plus a non-empty distortion… |
| `T8.1` | Second-NIC preconditions — do these BEFORE anything else in T8 | The L2 NIC (or alias) carries `192.168.1.1/24`, the L2 answers at `192.168.1.2`, and `ip route`… |
| `T8.2` | Source the L2 workspace overlay and confirm the package exists | The L2 ROS package appears. |
| `T8.3` | Launch the L2 node with the transport configured, not defaulted | The node starts and stays up. |
| `T8.4` | The L2 topics, their types and their rates | `/unilidar/cloud` at ≈10-20 Hz carrying `sensor_msgs/msg/PointCloud2`; `/unilidar/imu` at ≈200… |
| `T9.1` | HARD STOP — firmware pin ≥ V1.1.13 before ANY LAN join | A version string of the form `V1.1.x`, recorded, and **≥ V1.1.13**. |
| `T9.2` | Discover the REAL interface names — never guess, never copy the config | Two names written down: the wired NIC for the Go2 LAN, and the second NIC (or alias) for the L2. |
| `T9.3` | Render the CycloneDDS config, then substitute the real name | `grep -c` prints **0**. |
| `T9.4` | ROS_DOMAIN_ID unset, RMW consistent, in the shell that will record | `ROS_DOMAIN_ID` **unset** — i.e. |
| `T9.5` | Prove the binding — including the negative control | Discovery traffic on the intended NIC, and **nothing on the other one**. |
| `T9.6` | Source the unitree_ros2 interface overlay and prove the types resolve | The `unitree_go` / `unitree_api` interfaces resolve. |
| `T10.1` | Clear the argv against the INSTALLED recorder — MANDATORY, first | `argv cleared against …: N flag(s) all present` and **exit 0**. |
| `T10.2` | Emit the storage config OUTSIDE the bag directory, before the argv uses it | `wrote /data/parcel/stage0/mcap_storage.yaml` and a file containing `compression: "None"` and `… |
| `T10.3` | STOP GATE — support-artifact reconciliation against the observed graph | No refusal, and every one of the 4 `camera_info` topics plus 2 transform topic(s) reported `pre… |
| `T10.4` | STOP GATE — snapshot the transient-local /tf_static BEFORE record start | A non-empty capture of the latched transforms. |
| `T10.5` | Confirm the recording shell, and that the output folder does NOT exist | `output folder absent: OK`, all three overlays sourced in **this** shell, and free space on the… |
| `T10.6` | THE RECORD COMMAND — rendered from the plan, never typed from memory | The recorder starts and creates `/data/parcel/stage0/take01/` containing `metadata.yaml` and ex… |
| `T10.7` | STOP GATES after the take — calibration, transforms, sync, certification | `GO-RECORD` and a sidecar written beside the bag. |

Every row carries an exact command, an expected observable, and an explicit STOP branch. A row missing any of the three cannot be constructed — the generator refuses.

---

## T7 · RealSense D455 driver launch

The six D455 payload topics are 89.0% of the byte budget and the four `camera_info` topics are what make them usable afterwards. Nothing on any sheet has ever launched the node that produces them. Every `enable_*` argument below is DERIVED from the recording plan's own D455 rows, so the driver cannot enable a stream the recorder does not record, or omit one it does.

#### T7.1 · Free the camera before the driver opens it

**Provenance.** [CITE] session/TONIGHT_CHECKLIST.md N2e ⚠ FREE THE CAMERA FIRST

```bash
pkill -f 'python3 -' || true
lsof /dev/video* 2>/dev/null || echo '(no process holds a video node)'
```

**EXPECTED.** No process holds `/dev/video*`. The D455 is one USB device and only one process can own it.

**STOP.** If a `pyrealsense2` bench script is still running, the driver's 'failed to open device' is that script, not the camera. STOP, kill it, and re-run this row before T7.3 — do not diagnose hardware on a device somebody else has open.

#### T7.2 · Read the driver's own argument spelling — MANDATORY before T7.3

**Provenance.** [MEASURED-JAZZY-SANDBOX] `ros2 launch -s/--show-args/--show-arguments` exists · [CITE] TONIGHT_CHECKLIST N2e-2 · [UNVERIFIED-SYNTAX] on the profile-argument spelling

```bash
source /opt/ros/jazzy/setup.bash
ros2 launch realsense2_camera rs_launch.py --show-args | head -80
```

**EXPECTED.** A list of launch arguments containing EITHER the `<module>.<stream>_profile` form used in T7.3 (driver 4.55-era) OR the older `color_width` / `color_height` / `color_fps` and `depth_width` / `depth_height` / `depth_fps` form (4.51-era). Whichever it prints is the truth; record the substitution.

**STOP.** Neither form appears, or the launch file is absent: STOP — the installed driver is not one this sheet was written against. Record the printed argument list verbatim into the run sheet and re-derive T7.3 from it. Do not launch on a hunch: a rejected argument is a driver at the wrong profile or no driver at all, and the profile is what the whole disk budget is sized on.

#### T7.3 · Launch at the plan of record (848x480@30, colour+depth+IR pair+IMU)

**Provenance.** [DERIVED] enable_* set and the topic namespace from rosbag2.RECORDED_TOPICS; the profile from budget.RECOMMENDED_PROFILE · [UNVERIFIED-SYNTAX] argument spelling, gated by T7.2

```bash
source /opt/ros/jazzy/setup.bash
ros2 launch realsense2_camera rs_launch.py \
  camera_namespace:=camera \
  camera_name:=camera \
  enable_color:=true \
  enable_depth:=true \
  enable_infra1:=true \
  enable_infra2:=true \
  enable_accel:=true \
  enable_gyro:=true \
  rgb_camera.color_profile:=848x480x30 \
  depth_module.depth_profile:=848x480x30 \
  depth_module.infra_profile:=848x480x30 \
  unite_imu_method:=linear_interpolation \
  publish_tf:=true \
  tf_publish_rate:=0.0
```

**EXPECTED.** The node starts and stays up. Every `enable_*` above exists because a topic on the recording plan needs it: 4 image stream(s) and 2 IMU stream(s). `unite_imu_method` is not optional — without it the accel and gyro topics are simply absent and the bag has no D455 inertial data, silently. `publish_tf:=true tf_publish_rate:=0.0` is what puts the camera's own frames on `/tf_static`, which S-1's GO-RECORD gate requires.

**STOP.** Node will not start, or cannot open the device: STOP and re-run T7.1 before concluding anything about the camera. An argument the driver rejects: STOP and return to T7.2 — use the spelling `--show-args` printed, never this line as-is.

#### T7.4 · The topics, their types and their rates — including camera_info

**Provenance.** [DERIVED] topic list from rosbag2.RECORDED_TOPICS + rosbag2.SUPPORT_TOPICS · [MEASURED-JAZZY-SANDBOX] `ros2 topic hz -w` and `ros2 topic type` accept these arguments

```bash
source /opt/ros/jazzy/setup.bash
for t in \
  /camera/camera/color/image_raw \
  /camera/camera/depth/image_rect_raw \
  /camera/camera/infra1/image_rect_raw \
  /camera/camera/infra2/image_rect_raw \
  /camera/camera/accel/sample \
  /camera/camera/gyro/sample \
  /camera/camera/color/camera_info \
  /camera/camera/depth/camera_info \
  /camera/camera/infra1/camera_info \
  /camera/camera/infra2/camera_info
; do
  echo "===== $t"; ros2 topic type "$t" 2>&1
  timeout 15 ros2 topic hz -w 100 "$t" 2>&1 | tail -3
done
```

**EXPECTED.** All 10 topics exist. The 4 image topics report ≈30 Hz; accel and gyro report whatever the driver united them at (use the reported rate, do not assume); the 4 `camera_info` topics carry `sensor_msgs/msg/CameraInfo`.

**STOP.** A topic name that differs from this list is a FINDING, not a failure — record the real name; a recorder given a name nothing publishes subscribes to nothing and reports no error. Do not proceed to T10 with a mismatch unrecorded: STOP and correct the plan first, because the omission is invisible until the bag is opened. `camera_info` absent on any active optical stream: STOP — T10.7's GO-RECORD gate will refuse the bag anyway, and finding that out after the take costs the take.

#### T7.5 · The calibration actually describes the stream being recorded

**Provenance.** [DERIVED] profile from budget.RECOMMENDED_PROFILE; topic from rosbag2.SUPPORT_TOPICS · [MEASURED-JAZZY-SANDBOX] `ros2 topic echo --once` exists

```bash
source /opt/ros/jazzy/setup.bash
timeout 10 ros2 topic echo --once /camera/camera/color/camera_info 2>&1 | head -20
```

**EXPECTED.** `width: 848` and `height: 480`, matching the profile T7.3 launched, plus a non-empty distortion model and a `k` matrix that is not all zeros.

**STOP.** A 1280x720 calibration under an 848x480 stream is a calibration for a stream that was not recorded. STOP: relaunch at one profile or record at the other. This exact mismatch is a named S-1 refusal, and left alone it refuses the bag after the take instead of before it.

---

## T8 · Add-on Unitree L2 driver launch

The add-on L2 is a different SDK and a different transport from the dog's built-in unit, and the two LiDARs at a measured relative extrinsic are the session's cross-validation asset — unrecoverable once the bracket comes off. The vendor SDK example prints a cloud to a terminal; it does not publish a topic, and `ros2 bag record` records topics. This section is the ROS node, which is the session path.

#### T8.1 · Second-NIC preconditions — do these BEFORE anything else in T8

**Provenance.** [CITE] session/TONIGHT_CHECKLIST.md N6a/N6b (addresses, no-default-route rule) and N5a (the ping, and the N6-before-N5 ordering note)

```bash
ip -brief addr
ip route
ping -c 3 192.168.1.2
```

**EXPECTED.** The L2 NIC (or alias) carries `192.168.1.1/24`, the L2 answers at `192.168.1.2`, and `ip route` shows **no `default` via the L2 interface**. These are TONIGHT_CHECKLIST N6a/N6b's values, not new ones; N5's own ordering note applies — the address this ping needs is assigned in N6b, which sits later on that sheet than N5.

**STOP.** No second Ethernet interface at all (most Orin NX carriers have one): STOP and take one of N6a's three recorded branches — USB-Ethernet adapter, an IP alias on the single NIC, or the `/dev/ttyACM0` serial path — and write down which. L2 unreachable: STOP, re-check N6b, and record the address it actually answers on; the factory address may differ. A `default` route via the L2 NIC: STOP — that is the 192.168.1.0/24 collision the risk assessment names, and it routes robot traffic to a house network.

#### T8.2 · Source the L2 workspace overlay and confirm the package exists

**Provenance.** [CITE] TONIGHT_CHECKLIST N5b · [UNVERIFIED-SYNTAX] on all three names

```bash
source /opt/ros/jazzy/setup.bash
source ~/unilidar_sdk2/unitree_lidar_ros2/install/setup.bash
ros2 pkg list | grep -i unitree
```

**EXPECTED.** The L2 ROS package appears. The workspace directory, package name and launch-file name all differ between SDK revisions; the SDK's own README is authoritative and the path above is the shape N5b recorded.

**STOP.** Package absent or the overlay path differs: STOP and read the SDK README; record the real workspace path. If `colcon build` never succeeded, the L2 has no path into the bag at all and the two-LiDAR extrinsic is not captured. Write that acceptance down now — not after the bracket is torqued.

#### T8.3 · Launch the L2 node with the transport configured, not defaulted

**Provenance.** [DERIVED] launch line read off rosbag2.RECORDED_TOPICS' own `prerequisite` field for the l2.* rows · [UNVERIFIED-SYNTAX]

```bash
source /opt/ros/jazzy/setup.bash
ros2 launch unitree_lidar_ros2 launch.py
```

**EXPECTED.** The node starts and stays up. Its launch file carries the IP/port or the serial device and it must match what T8.1 established — configure the transport before launching; do not launch with factory defaults and hope.

**STOP.** Node launches but publishes nothing: STOP — the transport parameters do not match the device. If the SDK example reads the L2 and the ROS node does not, it is configuration, not hardware.

#### T8.4 · The L2 topics, their types and their rates

**Provenance.** [DERIVED] topic list from rosbag2.RECORDED_TOPICS l2.* rows · [CITE] TONIGHT_CHECKLIST N5b for the expected rates and N5a for the IMU plausibility gate

```bash
source /opt/ros/jazzy/setup.bash
ros2 topic list | grep -iE 'unilidar|lidar'
for t in \
  /unilidar/cloud \
  /unilidar/imu
; do
  echo "===== $t"; ros2 topic type "$t" 2>&1
  timeout 15 ros2 topic hz -w 50 "$t" 2>&1 | tail -3
done
```

**EXPECTED.** `/unilidar/cloud` at ≈10-20 Hz carrying `sensor_msgs/msg/PointCloud2`; `/unilidar/imu` at ≈200 Hz carrying `sensor_msgs/msg/Imu`. Apply the bench IMU plausibility gate: |accel| = 9.81 ± 1, |gyro| < 0.05 at rest. Absurd values are DEGRADED, never PRESENT.

**STOP.** Topic names differ from these: record the real names and STOP before T10 — the recorder subscribes to the planned names and says nothing when they do not exist. Both topics absent: STOP; the L2 is a `parcel-capture`-only channel for this session, which is a second artifact in a format no downstream tool reads. Record that acceptance.

---

## T9 · Unitree overlay and CycloneDDS environment

CycloneDDS bound to the wrong NIC is *the* classic zero-topics failure, and at 09:00 it presents as 'the dog looks dead'. Without the `unitree_ros2` interface packages sourced, `ros2 bag record` cannot resolve the dog message types and every dog topic on the command line is skipped — 10.2% of the byte budget, silently. Neither failure raises an error. Both are configuration, and both are settled here before the recorder starts.

**`configs/robot.yaml:128` and `:342` carry `enp3s0`. That is a placeholder from a different machine and it has never been observed on the Orin. Do not type it.** The rows below carry `__GO2_IFACE__` / `__L2_IFACE__`, which are deliberately unusable: a command still carrying one fails loudly instead of binding to the wrong interface.

#### T9.1 · HARD STOP — firmware pin ≥ V1.1.13 before ANY LAN join

**Provenance.** [CITE] adr/0002-firmware-pin.md §1 (the pin) and session/TONIGHT_CHECKLIST.md PRE-1 (how it is read and its branches)

```bash
# Not a shell command. Read the firmware version in the Unitree app,
# phone only, with nothing else attached to the dog's network, and
# record it in the run header BEFORE a cable is connected.
grep -n 'firmware' scrum/20260814/task_1/S2_STATUS.md || echo '(record the reading in the run sheet run header)'
```

**EXPECTED.** A version string of the form `V1.1.x`, recorded, and **≥ V1.1.13**. Unitree DDS on the robot LAN is unauthenticated by design; pre-V1.1.13 firmware is treated as RCE-capable on home Wi-Fi.

**STOP.** Below V1.1.13, or unreadable (unknown = absent, fail closed): **STOP. Wake the owner.** Do not attach the Orin or the laptop to the robot LAN. The session takes the DEGRADE-MMP path — mount, measure, photograph, record nothing — which is a legitimate outcome. T9.2-T9.6 and every dog topic in T10 are void until this clears; T7 and T8 touch no robot network and remain valid.

#### T9.2 · Discover the REAL interface names — never guess, never copy the config

**Provenance.** [CITE] session/TONIGHT_CHECKLIST.md N6a

```bash
ip -brief addr
ip -o link show
ethtool <candidate> 2>/dev/null | grep -E 'Speed|Link detected'
```

**EXPECTED.** Two names written down: the wired NIC for the Go2 LAN, and the second NIC (or alias) for the L2. `ip -brief addr` is the only authority — the interface name is a property of this Orin and nothing in the repository knows it.

**STOP.** No second Ethernet interface: STOP and take a recorded N6a branch (USB-Ethernet adapter / IP alias / serial L2) before continuing. The only candidate reporting `Link detected: no`: STOP — binding DDS to a down interface is the zero-topics failure with an innocent-looking config file.

#### T9.3 · Render the CycloneDDS config, then substitute the real name

**Provenance.** [CITE] TONIGHT_CHECKLIST N6d · [UNVERIFIED-SYNTAX] on the Cyclone schema for anything older than 0.10

```bash
cat > ~/cyclonedds.xml <<'XML'
<?xml version="1.0" encoding="UTF-8" ?>
<CycloneDDS xmlns="https://cdds.io/config">
  <Domain id="any">
    <General>
      <Interfaces>
        <NetworkInterface name="__GO2_IFACE__" priority="default" multicast="default" />
      </Interfaces>
    </General>
  </Domain>
</CycloneDDS>
XML

# Substitute the name T9.2 printed. The placeholder must be gone
# before the file is used by anything.
sed -i "s/__GO2_IFACE__/<the name ip -brief addr printed>/" ~/cyclonedds.xml
cat ~/cyclonedds.xml
grep -c '__GO2_IFACE__' ~/cyclonedds.xml
export CYCLONEDDS_URI=file://$HOME/cyclonedds.xml
```

**EXPECTED.** `grep -c` prints **0**. The file names the interface `ip -brief addr` printed, and `CYCLONEDDS_URI` is an absolute `file://` URI. The `<Interfaces><NetworkInterface name=…>` schema is Cyclone 0.10+, which is what ROS 2 jazzy ships.

**STOP.** `grep -c` prints anything but 0: **STOP.** The placeholder is still there and CycloneDDS will refuse the config or fall back to a NIC nobody chose. If H-1 reported an older distro whose Cyclone wants `<NetworkInterfaceAddress>` instead, STOP — that is the branch that voids this whole addendum.

#### T9.4 · ROS_DOMAIN_ID unset, RMW consistent, in the shell that will record

**Provenance.** [CITE] TONIGHT_CHECKLIST N6d · [REPO] configs/robot.yaml:129

```bash
env | grep -E 'ROS_DOMAIN_ID|RMW_IMPLEMENTATION|CYCLONEDDS_URI' || echo '(none set)'
grep -rn 'ROS_DOMAIN_ID' ~/.bashrc ~/.profile /etc/environment 2>/dev/null || echo '(no rc entries)'
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
```

**EXPECTED.** `ROS_DOMAIN_ID` **unset** — i.e. domain 0, matching `configs/robot.yaml:129 domain_id: 0`. `CYCLONEDDS_URI` set from T9.3. `RMW_IMPLEMENTATION` identical in every terminal that will run a driver or the recorder.

**STOP.** `ROS_DOMAIN_ID` set anywhere, or two terminals disagreeing about the RMW: STOP and make them consistent before launching anything. Two RMWs in two terminals is another silent zero-topics failure, and it gets diagnosed as a dead robot.

#### T9.5 · Prove the binding — including the negative control

**Provenance.** [CITE] TONIGHT_CHECKLIST N6d, with one deliberate divergence: N6d generates traffic by publishing a test topic. This session is sensors-only, so the row uses participant discovery from `ros2 node list` instead — same evidence, nothing emitted onto the robot's topics.

```bash
# terminal 1 — the intended NIC
sudo tcpdump -i <the Go2 NIC from T9.2> -n udp portrange 7400-7500
# terminal 2 — participant discovery only; this session emits no topic
source /opt/ros/jazzy/setup.bash
export CYCLONEDDS_URI=file://$HOME/cyclonedds.xml
ros2 daemon stop; ros2 daemon start; ros2 node list
# terminal 1 again, on the OTHER interface
sudo tcpdump -i <the other NIC> -n udp portrange 7400-7500
```

**EXPECTED.** Discovery traffic on the intended NIC, and **nothing on the other one**. The negative control is what actually proves the binding; traffic on the intended NIC alone proves only that something is talking.

**STOP.** Discovery on the wrong NIC, or on both: STOP. The config is not being read — check the `file://` URI, that the path is absolute, and that the export survives into the shell that will run the recorder. Fix it now; at 09:00 this presents as `ros2 topic list` empty and the dog apparently dead.

#### T9.6 · Source the unitree_ros2 interface overlay and prove the types resolve

**Provenance.** [CITE] session/TONIGHT_CHECKLIST.md N6f

```bash
source /opt/ros/jazzy/setup.bash
source ~/unitree_ros2/cyclonedds_ws/install/setup.bash
ros2 interface list | grep -iE 'unitree' | head -20
ros2 interface show unitree_go/msg/LowState | head -30
```

**EXPECTED.** The `unitree_go` / `unitree_api` interfaces resolve. `LowState` shows `imu_state`, `motor_state`, `bms_state`, `foot_force`, `foot_force_est`, `tick`, `wireless_remote`, `power_v`, `power_a` — and **no timestamp field**, which is the channel matrix's whole point. These are message-definition packages only: nothing here creates a command surface, a lease or a motion client.

**STOP.** Interfaces absent: **STOP. Owner decision.** With no `unitree_go` interfaces the recorder resolves no dog message type and records **no dog topic at all** — the bag simply has none, with no error. The fallback is a second artifact in a format no downstream tool reads. Write the acceptance down before recording, not after.

---

## T10 · The recorder: argv, storage config, and the stop gates around it

This is the only row on the sheet that writes the session. Every flag in the argv is rendered by `Rosbag2Plan(distro='jazzy')` and cleared against the installed recorder's own `--help` first, because the historical sheets hard-code flags Humble's recorder does not have — argparse exits 2 and the session records zero bytes. The gates on either side are S-1's, named by their real symbols.

#### T10.1 · Clear the argv against the INSTALLED recorder — MANDATORY, first

**Provenance.** [DERIVED from Rosbag2Plan(distro=jazzy)] · flags [MEASURED] against a real `ros2 bag record --help` executed in the repo's ROS 2 Jazzy sandbox (rosbag2 0.26.11)

```bash
source /opt/ros/jazzy/setup.bash
ros2 bag record --help > /tmp/parcel_record_help.txt
cd <the Parcel checkout on the Orin>
python3 -m scripts.parcel_capture.rosbag2 --distro jazzy --verify-help /tmp/parcel_record_help.txt
echo "verify-help exit=$?"
```

**EXPECTED.** `argv cleared against …: N flag(s) all present` and **exit 0**. The checker also refuses a help text it does not recognise: an unrecognised help must never read as 'nothing wrong'.

**STOP.** Exit 2 (`refused:`): **STOP.** The installed recorder lacks a flag this argv uses. Regenerate this sheet for the distro the machine actually runs — one command: `python -m scripts.parcel_capture.stage0_addendum --distro <observed> --emit-distro`. Do NOT edit the command line by hand; that is the second handwritten CLI working agreement 7 forbids. Exit 3: `ros2` is not on PATH in this shell — source the overlay and repeat.

#### T10.2 · Emit the storage config OUTSIDE the bag directory, before the argv uses it

**Provenance.** [MEASURED] enum spellings against rosbag2_storage_mcap 0.26.11 + libmcap 1.3.1 (PS-M F2) · [MEASURED-JAZZY-SANDBOX] the output-folder rule in ros2bag/verb/record.py:273-274

```bash
mkdir -p /data/parcel/stage0
python3 -m scripts.parcel_capture.rosbag2 --emit-storage-config /data/parcel/stage0/mcap_storage.yaml
cat /data/parcel/stage0/mcap_storage.yaml
```

**EXPECTED.** `wrote /data/parcel/stage0/mcap_storage.yaml` and a file containing `compression: "None"` and `compressionLevel: "Default"` — never the empty string, which makes the MCAP storage plugin fail its YAML conversion so `ros2 bag record` exits 1 having written zero bytes. Note the path is **not** under `/data/parcel/stage0/take01`: creating anything inside the record target makes that directory exist, and the recorder refuses an output folder that already exists.

**STOP.** File not written, or the directory is not on the record target: STOP. On Humble `--storage-config-file` is argparse's `FileType('r')`, so a missing file is an exit-2 before any recording starts. If the installed plugin later rejects the file, the documented remedy is to drop `--storage-config-file` and re-run: the plugin default measured as chunked-and-uncompressed, which the stdlib reader counts. You lose the crash-safety tuning, not the session.

#### T10.3 · STOP GATE — support-artifact reconciliation against the observed graph

**Provenance.** [DERIVED] gate name cross-checked against S-1's landed API · [MEASURED-JAZZY-SANDBOX] `ros2 topic list -t` accepts `-t`

```bash
source /opt/ros/jazzy/setup.bash
ros2 topic list -t > /tmp/parcel_topic_list.txt
python3 - <<'PY'
from pathlib import Path
from scripts.parcel_capture.preflight import reconcile_support_topics_or_raise
text = Path('/tmp/parcel_topic_list.txt').read_text()
print(reconcile_support_topics_or_raise(text).to_dict())
PY
```

**EXPECTED.** No refusal, and every one of the 4 `camera_info` topics plus 2 transform topic(s) reported `present` with the declared type. Unknown is absent; a type mismatch is affirmative evidence of misconfiguration and refuses regardless of need.

**STOP.** `PreflightError: support-artifact reconciliation refused`: **STOP — do not start the recorder.** A REQUIRED support topic missing at run time means the bag it would have completed cannot certify, and no post-session effort recovers intrinsics that were never recorded. Fix the driver launch (T7.3/T7.4) and repeat this row.

#### T10.4 · STOP GATE — snapshot the transient-local /tf_static BEFORE record start

**Provenance.** [DERIVED] schema name cross-checked against S-1's sidecar · [MEASURED-JAZZY-SANDBOX] `ros2 topic echo` accepts `--once`, `--qos-durability`, `--qos-reliability`

```bash
source /opt/ros/jazzy/setup.bash
timeout 15 ros2 topic echo /tf_static --once --qos-durability transient_local --qos-reliability reliable > /tmp/parcel_tf_static.yaml
wc -l /tmp/parcel_tf_static.yaml
```

**EXPECTED.** A non-empty capture of the latched transforms. `/tf_static` is published once and latched, so a recorder started afterwards may never receive it; the snapshot is bound into the sidecar under schema `parcel.capture.static_tf_snapshot.v1` and validated, not trusted.

**STOP.** Empty capture, or no `/tf_static` on the graph: **STOP.** A graph with no `/tf_static` has nothing to snapshot either, and the GO-RECORD gate refuses a bag whose optical frames have no parent. Prose is not a snapshot: a hand-written description of the mount is geometry with uncertainty (working agreement 6), never calibrated TF, and it cannot satisfy this gate.

#### T10.5 · Confirm the recording shell, and that the output folder does NOT exist

**Provenance.** [MEASURED-JAZZY-SANDBOX] ros2bag/verb/record.py:273-274 — `if os.path.isdir(uri): return print_error(...)`, executed: `[ERROR] [ros2bag]: Output folder '…' already exists.` exit 1

```bash
source /opt/ros/jazzy/setup.bash
source ~/unitree_ros2/cyclonedds_ws/install/setup.bash
source ~/unilidar_sdk2/unitree_lidar_ros2/install/setup.bash
export CYCLONEDDS_URI=file://$HOME/cyclonedds.xml
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
test ! -d /data/parcel/stage0/take01 && echo 'output folder absent: OK' || echo 'OUTPUT FOLDER EXISTS — STOP'
df -h /data/parcel/stage0
```

**EXPECTED.** `output folder absent: OK`, all three overlays sourced in **this** shell, and free space on the record target at or above the run-specific figure in `DISK_LEDGER.md` for the take length you intend.

**STOP.** `OUTPUT FOLDER EXISTS`: **STOP and choose a new take directory.** The recorder checks `os.path.isdir(uri)` and exits with `Output folder … already exists` before writing anything — a re-run after an aborted take fails here, not mysteriously later. Overlays missing from this shell: STOP and return to T9.6 — a recorder launched from an unsourced shell records a bag with no dog topics and no error.

#### T10.6 · THE RECORD COMMAND — rendered from the plan, never typed from memory

**Provenance.** [DERIVED from Rosbag2Plan(distro=jazzy)] · flags [MEASURED] against a real `ros2 bag record --help` executed in the repo's ROS 2 Jazzy sandbox (rosbag2 0.26.11)

<!-- BEGIN_ARGV:jazzy -->
```
ros2 bag record --storage mcap --output /data/parcel/stage0/take01 --max-cache-size 8388608 --node-name parcel_rosbag2_recorder --disable-keyboard-controls --max-bag-size 0 --max-bag-duration 0 --storage-config-file /data/parcel/stage0/mcap_storage.yaml --topics /utlidar/cloud /utlidar/imu /utlidar/robot_pose /utlidar/voxel_map_compressed /sportmodestate /lowstate /lf/lowstate /lf/sportmodestate /wirelesscontroller /frontvideostream /utlidar/lidar_state /utlidar/cloud_deskewed /utlidar/robot_odom /utlidar/switch /uwbstate /camera/camera/color/image_raw /camera/camera/depth/image_rect_raw /camera/camera/infra1/image_rect_raw /camera/camera/infra2/image_rect_raw /camera/camera/accel/sample /camera/camera/gyro/sample /unilidar/cloud /unilidar/imu /camera/camera/color/camera_info /camera/camera/depth/camera_info /camera/camera/infra1/camera_info /camera/camera/infra2/camera_info /tf /tf_static /events/write_split /events/messages_lost
```
<!-- END_ARGV:jazzy -->

**EXPECTED.** The recorder starts and creates `/data/parcel/stage0/take01/` containing `metadata.yaml` and exactly ONE `.mcap` file that grows. 31 topics are subscribed. `--max-bag-size 0` and `--max-bag-duration 0` are emitted explicitly and mean *never split*: more than one `.mcap`, or a `write_split` count above 0, is the take script's abort condition.

**STOP.** Exit 2 before any file appears — an unrecognised option: **STOP**, return to T10.1, and regenerate this sheet for the distro that machine actually runs. Exit 1 with zero bytes — the storage config was rejected: **STOP**, apply T10.2's documented remedy and restart the take. A second `.mcap` appearing mid-take: **STOP** the take per the abort rule and record why.

#### T10.7 · STOP GATES after the take — calibration, transforms, sync, certification

**Provenance.** [DERIVED] every symbol named here is cross-checked against S-1's live modules by tests/test_stage0_addendum.py

```bash
cd <the Parcel checkout on the Orin>
python3 - <<'PY'
from scripts.parcel_capture.sidecar import finalize_rosbag2
sidecar, path = finalize_rosbag2('/data/parcel/stage0/take01', bag_id='<run id>',
                                 require_go_record=True)
print(path, sidecar['capture']['go_record']['status'])
PY
```

**EXPECTED.** `GO-RECORD` and a sidecar written beside the bag. The gates that had to pass, by name:

    - `scripts.parcel_capture.preflight.reconcile_support_topics_or_raise` — a REQUIRED CameraInfo/tf_static topic missing or type-mismatched on the observed graph refuses BEFORE the recorder starts
    - `scripts.parcel_capture.sidecar.validate_static_transform_snapshot` — the transient-local /tf_static captured before record start is a machine-readable snapshot or it is nothing; prose is not a snapshot
    - `scripts.parcel_capture.sidecar.assess_go_record` — an optical stream with no matching intrinsics, a mismatched calibration profile, or an ambiguous transform tree cannot certify
    - `scripts.parcel_capture.sidecar.verify_calibration_digest` — the calibration bound to the manifest is re-derived from the bag's own CameraInfo bytes; one perturbed byte names itself
    - `scripts.parcel_capture.sidecar.verify_sync_fit_binding` — a cross-device time claim is the session's fit only when a digest says so; a fit supplied after the fact is not evidence
    - `scripts.parcel_capture.sidecar.finalize_rosbag2` — with require_go_record=True a refused bag writes NO certified manifest, not even transiently

**STOP.** `GoRecordRefusedError`: **STOP and read the refusal list — it names every reason.** Nothing is written: a certified manifest for an uncertifiable bag must not exist on disk even transiently. A refusal here is not a tooling problem; it is the dataset saying it cannot feed camera SLAM or camera-LiDAR fusion. Record the refusals verbatim, then decide whether the take is repeatable while the rig is still assembled — after the bracket comes off, it is not.

### The `--storage-config-file` bytes

Written to `/data/parcel/stage0/mcap_storage.yaml` by T10.2. Reproduced here so the sheet is self-contained if the Orin has no checkout yet; the bytes are `rosbag2.storage_config_yaml()` and nothing else.

<!-- BEGIN_STORAGE_CONFIG -->
```yaml
# parcel-capture rosbag2 MCAP writer options — card PS-G, corrected by PS-M.
# profile: crash_safe
# Key names and the accepted `compression`/`compressionLevel` spellings were
# MEASURED against rosbag2_storage_mcap 0.26.11 + libmcap 1.3.1 (ROS 2 Jazzy):
# a writer opened with this file wrote a real bag. The Orin runs Humble and its
# plugin build is UNVERIFIED. If `ros2 bag record` rejects this file, drop
# --storage-config-file and re-run: the plugin default measured as chunked and
# UNCOMPRESSED, which read_rosbag2_mcap() counts. You lose the crash-safety
# tuning, not the session. Settle it with a synthetic recording BEFORE the session.
# NEVER write compression: "" — the plugin refuses and records zero bytes.
noChunking: true
noMessageIndex: true
noSummary: false
noChunkCRC: false
chunkSize: 0
compression: "None"
compressionLevel: "Default"
forceCompression: false
```
<!-- END_STORAGE_CONFIG -->

---

## What this sheet does not prove

1. **No command in this document has ever executed on a real Orin.** Not one. The distro is unread, the drivers are uninstalled, and no topic here has been observed. H-1 (identity) and H-2 (the no-dog rehearsal) are the cards that produce that evidence; this sheet is what H-2 executes, not a substitute for having executed it.
2. **The RealSense and L2 launch argument spellings are UNVERIFIED.** They differ across driver and SDK revisions, which is why `--show-args` (T7.2) and the SDK's own README (T8.2) are mandatory rows that precede the launches rather than footnotes after them.
3. **Every topic name here is documentation-derived.** `ros2 topic list -t` on the real graph is the authority, and a name that differs is a finding to record, not an error to work around.
4. **The jazzy recorder CLI facts are measured against a Jazzy sandbox, not against the Orin.** T10.1 exists precisely because that gap cannot be closed from a desk.
5. **The gate names are cross-checked; the gate behaviour is not.** A test asserts every symbol named in T10.7 exists in S-1's modules. Whether those gates refuse the right bags is S-1's evidence, not this card's.
6. **Nothing here authorises motion.** Every row observes, launches a vendor sensor driver, or records. No Parcel process commands the robot, and the generator refuses to render a row that would.

