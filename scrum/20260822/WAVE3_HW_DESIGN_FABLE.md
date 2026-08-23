# Wave 3 — hardware design: Parcel on the Go2 EDU Plus with Mid-360 · Fable

**Author:** Fable (parcel-81, session 23d56828, 2026-08-23; the study was
begun by 799cb356 on 08-22 and its research phase survived the fourth crash).
**Sources:** `~/.cache/parcel-fable-design/research.json` — three lenses
(hardware 26 facts / codebase 27 seams / prior intent 39 facts), every claim
tagged documented / measured / inferred, with URLs; raw fetches in
`~/.cache/parcel-fable-design/hw-facts/`. Facts below carry their tag where
it matters; anything untagged is repo-measured. **Method deviation, on the
record:** the proposals→judges workflow died three times with nothing
journaled; this doc is written directly from the finished research, then
given one adversarial critic pass against `research.json` before it is
final (§10 records the result).

## 1. Purpose

The owner ordered the **Go2 EDU Plus with Mid-360** (robostore, $17,055):
Jetson **Orin NX 16 GB onboard** (aarch64, custom Unitree carrier), **Livox
Mid-360** on the dock's M8 air plug, a built-in wide-angle head LiDAR
(model L1-vs-L2 unknown until the box — design against `rt/utlidar/*`),
720p/120° RGB front camera (no depth — the D455 buy stands), Wi-Fi 6 + 4G,
15 Ah. Delivery lead time 2–4 weeks. This document is the design that makes
the existing product — the sim-venue companion that roams on command, talks
full duplex, perceives, remarks, and stays inside the safety core — run on
that machine, and it is written BEFORE any hardware-facing implementation
(owner's rule). It decides what changes, what is venue-independent by
construction, what is UNKNOWN until the box opens, and cuts wave-3 cards
(`task_35+`) in two rails: **software-now** (no hardware needed, starts
today) and **box-day** (gated on delivery, each with its exact first
command).

## 2. What the research overturned (the design carries these, not the old plan's assumptions)

1. **"The Orin" is two possible machines.** 2024–25 units ship **JetPack
   5.1.1 / Ubuntu 20.04 / CPython 3.8** [documented]; a JetPack 6.2.1
   update path exists (theroboverse, page unreachable — [inferred]). Our
   preflight's L4T table (`scripts/parcel_capture/preflight.py:267-276`)
   covers only 36.3.0–36.4.4 (JetPack 6.0–6.2.1) and **fails closed on
   JetPack 5 — correctly**. Day 1 on the box is a READ (B9), not a run;
   the JetPack-6 reflash is a dock operation, owner-gated,
   full-backup-first (the carrier is custom; NVIDIA defers to Unitree
   [documented]).
2. **No public Jetson wheel of onnxruntime-gpu satisfies our pin.**
   `pyproject.toml` pins `onnxruntime-gpu[cuda,cudnn]>=1.28,<2`
   (Requires-Python ≥3.11, x86_64 wheels); known aarch64 CUDA wheels stop
   at 1.23.0 cp310 (Ultralytics / jetson-ai-lab) [measured]. The Orin
   perception venv therefore CANNOT be the packaged `perception` extra.
3. **The Mid-360 lands on the dock, not the head.** M8 air plug =
   Ethernet + power [inferred from MYBOTSHOP/cable listings]; Livox SDK2
   is C++-only; the Python-practical reader is `livox_ros_driver2`
   PointCloud2/CustomMsg over DDS, or a raw-UDP decoder (ports
   56100–56500, host convention 192.168.1.5x, lidar 192.168.1.1xx)
   [documented]. `capture/channels.py`'s "add-on Unitree L2 via
   unilidar_sdk2" concept is dead weight and must be retired/re-labelled.
4. **The head LiDAR is reachable only via DDS** `rt/utlidar/*` from
   192.168.123.161, whichever model it is [documented]; L2 spec 360°×96°,
   64 k pts/s, 5.55 Hz [documented]. Which unit feeds `voxel_map` once a
   Mid-360 is fitted: UNKNOWN (`rt/utlidar/switch` exists).
5. **The "wireless vector positioning tracking module" is probably the UWB
   owner fob** (`rt/uwbstate`) [inferred] — the repo already models it
   (`src/parcel_robot/uwb/`); indoor accuracy unknown (U39).
6. **Dock ports:** 1× USB 3.0 A, 1–2× USB-C, 2× GbE, M8 [documented,
   resellers disagree on the C count]; payload power output and battery
   life under Orin+Mid-360+D455+array load: UNKNOWN (vendor 2–4 h is
   unloaded).
7. **Firmware on a 2026 unit: UNKNOWN.** ADR 0002 pins ≥ 1.1.13;
   CVE-2026-27509 (unauthenticated DDS RCE on the robot LAN) has
   **no known patched version** [documented] — the load-bearing control is
   the firewall of 192.168.123.0/24, not the version pin. Newest firmware
   seen in the wild 1.1.15.
8. **CPython 3.10 breaks the product tree as written.** `datetime.UTC`
   and `typing.Self` are imported unguarded in `runtime.py:13`,
   `camera_channel/backends/physical.py:52`, `online_map/store.py:40`,
   `owner_tracking/gallery.py:63`, `perception_daemon/server.py:48`,
   `perception_daemon/client.py:39` (codebase lens; sweep needed). The
   lock is a 3.14 x86_64 snapshot; the `voice` extra needs ≥3.11.

## 3. Target architecture — processes, venvs, networks on the dog

The spine (HLD) is unchanged: **Python semantic app → deterministic
admission sidecar → native sole-writer gateway**, WorldModel as an evidence
plane, no learned component manufacturing physical truth. What the purchase
changes is WHERE things run and WHAT feeds them.

**Process/venv topology on the Orin (three Python worlds + native, by
construction — the DDS singleton and wheel families force it):**

| Process | Venv / runtime | Why separate |
|---|---|---|
| Product runtime (runtime.py, lane, maps, OT-2, CURIO-1) | `~/parcel-venv` CPython 3.10 (JetPack system) — **src/ made 3.10-clean, §5.1** | the semantic app; no vendor SDK inside (preflight rule 1 stands) |
| Capture/recorder (parcel_capture, rosbag2/MCAP) | capture venv, rclpy (Humble, only if installed) | 3.10-safe by construction already; refuses rather than guesses |
| Motion: unitree_sdk2py + cyclonedds 0.10.2 (source-built) | motion venv | CycloneDDS is process-global; the SDK ships motion clients — never beside capture (ingest/dds.py rule) |
| Perception daemon (OWLv2/SigLIP over AF_UNIX) | perception venv, ort-gpu ≤1.23 aarch64 wheel or TensorRT EP (§5.2) | wheel family differs from x86; one GPU, one socket |
| Native gateway (N28/N43, C++ unitree_sdk2) | native binary | the sole writer; watchdog independent of Python |
| MuJoCo | **absent** | `Go2Backend` replaces `MujocoSocketBackend` (§5.4) |

**Network topology (constraint C0 of the hardware lens):** the Orin is
multi-homed — (a) internal robot LAN 192.168.123.0/24 (dock .18, head
board .161): unauthenticated DDS domain 0, CVE-2026-27509 class — **never
forwarded**; nftables on the Orin drops robot-LAN↔WAN forwarding, day-1
item; (b) Mid-360 point/cmd UDP on the 192.168.1.x convention (which NIC —
UNKNOWN, Q2); (c) Wi-Fi 6 (or 4G) WAN for the hosted realtime lane and the
panel over tailnet only (ADR 0002 item 4). `web_panel` keeps binding
127.0.0.1; remote view goes over the tailnet.

**Sensor→seam map (the one picture to keep):**

```
Mid-360 (UDP/DDS livox) ──► planar height-band filter ──► lidar_ranges ──► reactive_safety gate + grid planner
                        └─► LIO (bake-off B17) ──► T_map_odom ──► PoseProvider(MAP) ──► tether, ROAM-2 coverage, map frame
rt/utlidar/* (head, model?) ──► capture only, wave 3; voxel_map consumer UNKNOWN
rt/sportmodestate ──► PoseProvider(ODOM) day-1 odom + Go2Backend.observe
D455 (USB3, cp310 wheel) ──► CameraIngress physical venue (VENUE-1, unchanged) ──► detector daemon / OT-2 / P1-B map
front camera (RGB 720p) ──► NOT an ingress (VENUE-1 ruling stands); capture-only channel
XVF3800 (USB, 16 kHz) ──► local audio gateway (§5.6) ──► lane.send_audio / array-amp playback
rt/uwbstate ──► capture + OT-2 fusion stub input (evidence only, no authority)
```

*(§4 onward written by parcel-6c, session 31fcc2a0, 06:3x EDT 08-23, from
the same `research.json`; parcel-81 died at §3.)*

## 4. Seam by seam — what changes, what is venue-independent by construction, what is UNKNOWN until the box

The codebase lens found 27 seams; they collapse into nine decisions. Each
row names the product-path caller (the verifier's rule: seeds prove guards,
callers prove integration), the hardware-compat class the DESIGN.md §e of
every wave-3 card must declare — **VI** (venue-independent: no change, the
sim proves it), **MC** (must-configure: a profile/overlay/env change only),
**NEW** (code that does not exist), **UNK** (cannot be designed until the
box is read) — and the first thing that proves it on the dog.

| # | Seam (file:symbol) | Today | On the dog | Class | First proof on the box |
|---|---|---|---|---|---|
| S1 | `backends/base.py:SimulatorBackend.observe` → `SimObservation` (lidar_ranges, nearest_obstacle_m, pose) — the ONE source of pose/scan/obstacle facts for the runtime [measured] | `MujocoSocketBackend` only | `Go2Backend` (§5.4): pose from `rt/sportmodestate` odom + `T_map_odom` from LIO; `lidar_ranges` from the Mid-360 height band | NEW | `observe()` returns a scan with `evidence_origin == physical` while the dog stands still, and `reactive_safety.scan_present` is true |
| S2 | `navigation/reactive_safety.py:722-747 scan_present / scan_evidence_from_observation` | origin labelled from `observation.backend` | unchanged — it consumes whatever S1 delivers; the nine `ClearanceProfile`s stay pinned at IEEE equality (AUDIT_WAVE2) | VI | the pinned-profile test is the same test |
| S3 | `pose.py:658-683 PoseProvider` (stratum-1 seam), `runtime.py:11286 update_pose` | ODOM = sim truth | ODOM = `rt/sportmodestate`; MAP = LIO `T_map_odom` with covariance/health/jump flags (HLD §8.3 WorldSnapshotV2) | NEW (MAP) / MC (ODOM) | B17 bake-off: `T_map_odom` drift over a 10-minute loop closure, recorded, not asserted |
| S4 | `control/unitree_sport.py:UnitreeChannelContext` (`ChannelFactoryInitialize` once per process, NIC under /sys/class/net; Move/StopMove only) [measured] | Python writes the Sport lease | stays the COMMISSIONING-only writer; autonomous motion goes through the native sole-writer gateway (N28/N43) — **no Parcel autonomous motion without it** (MOTION.md, intent constraint) | NEW (gateway) / VI (adapter) | Stage 0 observe-only: `SportModeState_` received, zero `Move` calls, journal proves it |
| S5 | `bridge/{protocol,fake_gateway,timing}.py` (N24 fake SOCK_SEQPACKET gateway, V1 DTOs, RC-4 TTL derivation) [measured] | test-only | the contract the native gateway implements; the TTL derivation becomes the stopping-envelope check of §6 | VI (contract) / NEW (impl) | RC-4 derivation re-run with the dog's measured braking latency |
| S6 | `capture/channels.py` (28 channels; `SourceDevice` {GO2, L2, D455, ORIN, GNSS, UWB, MIC}; `L2Ingest` via `unilidar_sdk2`) [measured] | add-on L2 concept | `L2` → `HEAD_LIDAR` (DDS `rt/utlidar/*`, model read from the box) + NEW `MID360` source (livox UDP/DDS) — retire the unilidar path (§2.3) | MC + NEW | `preflight.probe_builtin_lidar` settles L1-vs-L2 from the box, not from a listing |
| S7 | `scripts/parcel_capture/preflight.py` (`probe_jetpack` 2731; `L4T_TO_JETPACK` 267-276 = 36.3.0–36.4.4 only) [measured] | fails closed on JetPack 5 — correctly | unchanged until B9 is read; if JetPack 5.1.1 ships, the reflash decision (§7.2) comes BEFORE any table edit | UNK | B9: `cat /etc/nv_tegra_release; python3 -V; ls /opt/ros` |
| S8 | `scripts/parcel_capture/ingest/dds.py` rule: `unitree_sdk2py` never beside `rclpy` (CycloneDDS is process-global) [measured] | one capture venv | the three-venv topology of §3 is this rule applied to the whole dog | VI (rule) / MC (venvs) | `python -c "import unitree_sdk2py, rclpy"` in the capture venv must FAIL by construction (no SDK installed) |
| S9 | `camera_channel/backends/realsense.py` + VENUE-1 `CameraIngress` (depth required; RGB-only never passes; `PHYSICAL_BACKEND_KINDS = uvc/realsense/recorded`) [measured] | desktop D455 | same code; pyrealsense2 cp310 aarch64 wheel exists (2.58.3.10794) [measured]; the front camera stays capture-only | VI / MC | R9-style venue check: ≥ 1 depth frame published on the Orin's USB 3.0 A port |
| S10 | `perception_daemon/{server,client,protocol}.py` — AF_UNIX under `$XDG_RUNTIME_DIR`, absent daemon = typed degrade [measured]; `pyproject.toml` `perception` extra `onnxruntime-gpu>=1.28` [documented] | RTX 5000 Ada, 83 ms OWLv2 fp16 | §5.2: daemon on the Orin in its own venv with ort-gpu ≤ 1.23 cp310 aarch64 or TensorRT EP; the runtime never imports ort | MC (socket) / UNK (latency) | OWLv2 latency at the allowed power mode, recorded (`PARCEL_PERCEPTION_SOCKET`) |
| S11 | `realtime/audio_gateway.py:BrowserAudioGateway` → `lane.send_audio` (sole caller `runtime.py:8543`); `BrowserSink` [measured]; XVF3800 = 16 kHz both ways, ch1 = ASR beam, speaker on the array's own amp (AIR-1) [documented] | the ear is a browser | §5.6: `ArrayAudioGateway` on the Orin — same `send_audio` seam, resampling 16↔24 kHz inside the gateway | NEW | through-air false barge-in ≤ 2 % TV-on (the unmeasured tell) |
| S12 | `duplex/turn_controller.py`, local endpointing (TURN-1) | runs beside the browser | runs on the Orin, fed by ch1; the hotword e-stop is a BEHAVIOURAL stop only (MOTION.md) | VI | same corpus replay (`tests/test_realtime_corpus_replay.py`) on aarch64 |
| S13 | `realtime/spend_ledger.py:474-482` hosted spend | desktop link | same ledger; link = Wi-Fi 6 or 4G (§5.6) — link-loss mid-utterance behaviour is UNKNOWN (Q-link) | VI / UNK | measured RTT from the Orin, recorded |
| S14 | `config.py:109-204 OVERLAY_INTRODUCIBLE_KEYS` + SHA-locked base `robot.yaml` (TRUTH-1 adds `planner_model`; VENUE-1 `perception.camera_ingress*`; `roam`) [measured] | sim profile | ONE physical profile `configs/profiles/go2_edu_plus.yaml` that declares `required_capabilities` (CAP-1 is inert today — nothing declares [measured]) and exposes NO truth/oracle fields | MC | `check_required_capabilities` refuses on the desktop (no D455, no DDS) — that refusal is the test |
| S15 | `admission.py` CAP-1 view; `runtime.py check_required_capabilities` one line before ingress attach [measured] | inert | becomes load-bearing the day S14 lands | VI | as S14 |
| S16 | `patrol/mission.py:PatrolPolicy` (`forward_clearance_m`, `tether_m` from pose-distance-to-home; prototype overlay budget_s 120 / cruise_vx 0.25 / turn_vyaw 0.8 / tether_m 10) + ROAM-2 coverage objective reading the learned map [measured] | sim | unchanged policy; inputs come from S1/S3 — coverage needs the MAP frame to persist across sessions (N31 seam ROAM-2's DESIGN names) | VI | a tethered 120 s run on the dog through `submit_realtime_transcript('Go explore.')` |
| S17 | `online_map/` P1-B camera→map writer (`runtime.py:1586-1604,12278-12744`) | sim camera | same writer behind the D455 venue; map entries keyed in the MAP frame once S3 lands | VI (writer) / MC (frame) | a `place_learned` remark about a real doorway (CURIO-1 on real places) |
| S18 | `owner_tracking/` OT-2 + `uwb/{SimUwbInjector,OwnerFusionStub}` (no real UWB; `rt/uwbstate` modelled) [measured] | sim injector | `rt/uwbstate` becomes a capture channel and an EVIDENCE input to the fusion stub — never authority (exec summary §9) | MC | `rt/uwbstate` payload decoded and logged; accuracy U39 measured against a tape |
| S19 | `commissioning/` (limits, arming, record, session, one-axis steps) + `parcel-commission` CLI [documented] | fail-closed flags, sim | unchanged; the ladder of §6 runs it on the dog | VI | Stage 0 record written on the Orin |
| S20 | `scripts/parcel_capture/attest.py FIRMWARE_PIN 146-149` (≥ 1.1.13) [measured] | pin exists | read and record BEFORE the dog joins any LAN (ADR 0002); CVE-2026-27509 has no known fixed version — the firewall is the control, the pin is the record | VI | `attest` output with the shipped version |
| S21 | `scripts/env-audio.sh` (x86_64 PortAudio prefix), `install_speech_services.sh` (Piper x86_64 asset), llama.cpp build [measured] | x86 pins | aarch64 variants of the same scripts, selected by `uname -m`; nothing may assume x86 (intent constraint) | MC | `scripts/env-audio.sh` on the Orin builds PortAudio and `tools/xvf3800_probe.py` enumerates 2886:001a |
| S22 | `pyproject.toml:9,14-27` interpreter contract; lock is 3.14 x86_64; `voice` extra ≥ 3.11; numpy 2.5.1 ≥ 3.12 [measured] | one venv, one lock | §5.1: published tested ranges per extra (HLD open decision 10) and a `jetson` lock | MC | `pip install -e .[base]` on CPython 3.10 aarch64 from the jetson lock |
| S23 | `deploy/compose.yaml` desktop/CI skeleton; 'Orin image bake deferred to P5' [documented] | skeleton | the golden image question (ADR 0001 two-dock rule vs one integrated Orin) is re-opened in §8, not decided here | UNK | — |
| S24 | `docs/MOTION.md:158,357,441-442,491-492` stop rules [documented] | doctrine | unchanged; PO-1's e-stop decision (§6) is recorded against 441-442 | VI | the recorded decision |
| S25 | `tests/_sim_guard.py`, `tools/list_parcel_procs.py` (HY-1 process guard, pattern table) | sim pattern | pattern table gains the native gateway process name when N28 lands (HY-1's DESIGN names the extension point) | VI | — |
| S26 | `scripts/ci_gate.py` | x86 desktop, 9,3xx tests | the same `--tier commit` must print the same row set on the Orin minus the rows that need MuJoCo/GPU, each of those a typed SKIP with the reason (never a silent pass) | MC | the gate's JSON on the Orin, diffed against the desktop's |
| S27 | `docs/HARDWARE_PORTABILITY_AUDIT.md` (retired), handbook, acoustic plan | prose | superseded by this doc where they disagree (§10) | — | — |

Three facts the table rests on and that a card may NOT re-derive: the
runtime has exactly one physical-fact source (S1) [measured]; the Sport
lease adapter is Python and therefore not a sole writer (S4) [measured];
CAP-1 is wired but inert (S14/S15) [measured]. Everything "NEW" above is
a wave-3 card; everything "VI" is proven by the existing sim gate and is
not re-tested on the dog beyond its "first proof" column.

## 5. The nine decisions

### 5.1 Interpreter contract: src/ is made 3.10-clean; the Orin product venv is the system CPython 3.10 (on JetPack 6) — and if the box ships JetPack 5, nothing runs until §7.2 is decided

The alternative — a 3.12 venv on the Orin via uv/deadsnakes, keeping the
3.11-only imports — was weighed (codebase lens, last open question) and
rejected: pyrealsense2 has cp310 and cp312 aarch64 wheels but
onnxruntime-gpu's only prebuilt aarch64 CUDA wheels are cp310 [measured],
cyclonedds 0.10.2 must be built from source on any interpreter [measured],
and the capture tree is already 3.10-safe by construction with tests that
forbid 3.11 idioms (`tests/test_clockmap.py:1519`, `test_syncevents.py:1355`)
[documented]. One interpreter for the dog, the one the vendor image gives
us. Concretely: the unguarded `from datetime import UTC` / `typing.Self`
sites (`runtime.py:13`, `observability.py:12`, `context/{builder,models}.py:5`,
`owner_tracking/gallery.py:63`, `camera_channel/backends/physical.py:52`,
`online_map/store.py:40`, `perception_daemon/{server:48,client:39}.py`)
[measured] are replaced by the guarded form the capture tree already uses;
`pyproject.toml` publishes **tested ranges per extra** (base ≥ 3.10;
voice ≥ 3.11 because websockets 17 [measured]; perception-desktop ≥ 3.11
because ort ≥ 1.28; perception-jetson = 3.10 exactly) and CI adds a 3.10
job for `base` (GATE-0 recorded 3.10 and 3.13 as unproven [measured]).
numpy 2.5.1 requires ≥ 3.12 [measured] — the jetson lock pins the last
numpy with cp310 wheels; this is a lock, not a code change. **Does not
decide:** JetPack 5 (Python 3.8). 3.8 is out of scope by declaration — the
capture tree's own floor is 3.10 — so a JetPack-5 box forces §7.2 first.

### 5.2 Perception on the dog: the detector daemon moves onto the Orin in its own venv; the runtime never learns which EP it got

The daemon boundary already exists (`perception_daemon/*`, AF_UNIX, absent
daemon = typed degrade) [measured]; it was built for exactly this. On the
Orin the daemon's venv installs the Ultralytics / jetson-ai-lab
`onnxruntime_gpu-1.23.0-cp310-linux_aarch64` wheel [measured] with the CUDA
EP, and the TensorRT EP is the measured fallback if OWLv2 fp16 latency at
the allowed power mode misses the 10 Hz thread's budget — both are
`perception_providers` choices, invisible above the socket. The desktop
GPU remains the VLM-veto and SigLIP-embedding host for the first sessions
(hosted over the tailnet, never on the control thread — the "no VLM on the
10 Hz thread" fatal test is unchanged). The `perception` extra's pin
`>= 1.28` is NOT relaxed: it is renamed `perception-desktop` and a
`perception-jetson` extra with `onnxruntime-gpu` unpinned-from-PyPI
(installed from the Jetson index by the install script, recorded by
`preflight.probe_detector_runtime`) is added. **Unknown until the box:**
Orin latency (Q-ort). **Falsifies:** the handbook sentence that the RTX
measurements stand in for Orin behaviour — they never did, and now there is
an Orin to measure.

### 5.3 Mid-360 → scan and pose: a planar height-band filter feeds `lidar_ranges`; LIO feeds `T_map_odom`; the head LiDAR is capture-only until its model is read

The Mid-360's vertical FOV is −7°…+52° [documented]: it sees up, not down;
it is NOT a floor-clearance sensor (hardware constraint). So the scan the
runtime consumes is a **planar band** (z ∈ [0.10, 0.60] m above base_link
after extrinsics B11) binned to the same angular layout `SimObservation.
lidar_ranges` has today, so `reactive_safety` and the grid planner are
unchanged (S2 VI). Floor drops, stairs and low obstacles below the band
come from the D455 depth (S9) and from the Go2's own sport-mode avoidance
(whose interaction with Parcel's yield/doorway logic is UNKNOWN, Q-avoid).
Reader: `livox_ros_driver2` over DDS in the capture venv (rclpy) or a raw
UDP decoder (ports 56100/56300/56400, host 192.168.1.5x) [documented] — the
decoder is the venue-independent choice because it needs no ROS and is
testable against a recorded UDP pcap on the desktop; it is wave-3 card
HW-3. Odometry/SLAM provider is **not chosen here**: B17 bakes off
FAST-LIO2 / Point-LIO on the same 10-minute recording and the winner
publishes `T_map_odom` with covariance and a jump flag into `PoseProvider
(MAP)`; until then ROAM-2 coverage and the learned map key on ODOM and the
map does not persist across power cycles (a declared degradation, not a
bug). Which unit feeds `voxel_map` after the Mid-360 is fitted is UNKNOWN
(`rt/utlidar/switch`); the head unit is a capture channel only.

### 5.4 `Go2Backend`: the physical `SimulatorBackend`, observe-only first

`MujocoSocketBackend` is the only `SimulatorBackend` [measured]; the
runtime's pose, scan and obstacle facts all come from `observe()` (S1).
`Go2Backend.observe()` composes: ODOM pose from `rt/sportmodestate` (the
existing `UnitreeChannelContext` subscriber, motion venv, read-only in this
card), `lidar_ranges` from §5.3's band filter, `nearest_obstacle_m` derived
from the band exactly as the sim derives it, and `backend = "go2"` so
`evidence_origin` labels the scan physical. Its `apply`/`step` side is
**refused** (raises `NotImplementedError` with the MOTION.md citation) until
the native gateway exists — the backend is an eye, not a hand. This is the
card that makes `runtime.py` start on the dog at all (MuJoCo is absent from
the Orin by construction, §3) and it is software-now: the desktop proves it
against recorded DDS (`tests/` fixtures from the 08-13 Stage-0 recording
format) and the box proves it live in Stage 0.

### 5.5 Motion authority: commissioning stays Python-Sport; autonomy waits for the native sole-writer gateway; the independent stop is decided by PO-1 before the first armed step

Nothing here is new doctrine — it is the HLD spine applied to the box.
The Python Sport adapter (S4) is allowed ONLY inside `parcel-commission`'s
armed one-axis sessions (Stage 0 observe → single axis 0.10 m/s / 0.25 rad/s
/ 2 s on a stand → leashed vx ≤ 0.15 → restricted free), operator at the
stop, second person present. Autonomous roam on the dog requires N28/N43:
a C++ `unitree_sdk2` process (Ubuntu 20.04 / gcc 9.4 target [documented] —
it builds on 22.04 but that is a box-day measurement) that owns the DDS
writer, enforces RC-4 TTLs from `bridge/timing.py`, and **stops on its own
watchdog** independent of Python. The stop itself: the handheld remote's
L2+B = Damping = torques off = the dog drops [documented]; there is no
documented hold-position e-stop. PO-1 records (a) remote + leash with the
MOTION.md:441-442 waiver on file, or (b) a battery-path relay — this doc
does not choose, it **requires the record to exist before any `--arm`**,
and it names the open question Q-stop (does L2+B act through the MCU when
the head board hangs?) as a box-day test with the dog on a stand.

### 5.6 The ear moves from Chrome to the array on the Orin; the mouth stays on the array's amp; the hosted lane crosses Wi-Fi 6 (4G is the fallback, not the plan)

`BrowserAudioGateway` is the only `lane.send_audio` caller [measured]. An
`ArrayAudioGateway` (PortAudio, XVF3800 ch1 ASR beam in, 16 kHz; playback
through the array's own DAC/amp so hardware AEC keeps its reference
[documented]) resamples 16 ↔ 24 kHz inside the gateway and presents the
same `send_audio` seam; `BrowserSink`/browser mic remain selectable for the
desktop. TURN-1's endpointer and the hotword stop run in the same process
on the Orin. The AIR-1 through-air session that is still owed (TV-on false
barge-in ≤ 2 %) is measured with THIS gateway on the desktop first (the
array is on hand) — software-now — and repeated on the dog. Link: Wi-Fi 6
to the home AP over the dock's WAN NIC, tailnet for the panel; 4G only if
the owner provisions a SIM (the GPS on that module is not known to reach
DDS, Q-gps). Link-loss mid-utterance: the lane already degrades to
`local-only` on websocket close; what the BODY does on link loss is a
behaviour rule — HOLD, not return — recorded in the profile (S14), because
motion never depended on the cloud (exec summary §9).

### 5.7 Networks: the robot LAN is a security boundary, enforced on the Orin on day 1

192.168.123.0/24 is unauthenticated CycloneDDS domain 0 with a known
unauthenticated RCE class and no fixed version [documented]. The Orin is
the only thing with a foot in both worlds. Day-1 item B-fw: nftables on the
Orin — default-drop forwarding between the robot-LAN NIC and any WAN
interface (Wi-Fi, 4G, second RJ45), DDS multicast confined to the robot
NIC, panel bound to 127.0.0.1 and reached over the tailnet (ADR 0002 item 4).
The Mid-360's 192.168.1.x convention [documented] must not be the home
LAN's /24 (robot.yaml already flags this collision) — the Mid-360 NIC, if
it is the dock's second RJ45 (UNKNOWN, Q-wire), gets a static 192.168.1.5
and no gateway.

### 5.8 One physical profile, declared capabilities, no oracle fields

`configs/profiles/go2_edu_plus.yaml`, an overlay over the SHA-locked base,
introducing only keys in `OVERLAY_INTRODUCIBLE_KEYS` (adding
`backend: go2`, `required_capabilities`, `audio.gateway: array`,
`perception.detector: daemon`, `lidar.band: [0.10, 0.60]`) — each a new
introducible key with a TRUTH-1-style marked region and a pin test. CAP-1's
`check_required_capabilities` then refuses on a desktop without the D455
and the DDS NIC, which is the test that proves the declaration is real.

### 5.9 Box-day is a READ; software-now is most of the work

Of the 27 seams, 16 are VI or MC and are finished and proven on the
desktop before delivery (the cards of §9's software-now rail). The box-day
rail is short by design: read identity (B9), firewall (B-fw), firmware
record (S20), mount + extrinsics (B11), Stage 0 observe (S19/S4), D455 on
the dock's USB 3.0 A (S9), array enumerates (S21), recorder smoke (B12),
and — only after all of those — the first armed one-axis step. The owner's
6–8 h over two weeks fits that list and nothing else.

## 6. Safety — what this design does not touch, and the one envelope it must measure

Untouched by any wave-3 card (TASK_BOARD rule 1; AUDIT_WAVE2 rulings):
`core/hard_stop.finalize_command`, the e-stop latch, command TTLs/watchdog,
`reactive_safety` semantics, the nine grid profiles at IEEE equality, the
frozen follow-bench and nav baseline v4, planner coupling 0.42 (prototype
0.45), the ASK-grants-no-motion rule, `MIN_DUCK_GAIN 0.05`, the no-VLM-on-
the-control-thread fatal test. Hardware cards that need a clearance change
ask the owner; they do not re-pin.

**The envelope (HLD §8.8):** candidate age + IPC + gateway watchdog period
+ vendor braking latency + localization uncertainty must fit inside the
commissioned stopping distance at the active regime. Three of those five
terms are box-day measurements (braking latency of `StopMove`/Damp on a
stand with the foot-force sensor as the clock; LIO jump magnitude; gateway
period under load), and **the RC-4 derivation in `bridge/timing.py` is
re-run with the measured numbers before the leashed stage** — that re-run
is a gate row, not a note. Until it passes, the commissioned speed is the
one-axis 0.10 m/s, which the existing sim TTLs already cover with margin.

**Independent stop:** decided by PO-1 (§5.5), recorded before `--arm`, and
tested on a stand (Q-stop). Software stops (hotword, panel, `HOLD`) are
behavioural and are documented as such in every card.

## 7. Box-day protocol — the first two hours, in order, each step a read with a written result

| Step | Command / action on the Orin (dog on a stand, sport mode OFF, remote in hand, no LAN joined) | Result file | Branch |
|---|---|---|---|
| B9 identity | `cat /etc/nv_tegra_release; uname -a; python3 -V; ls /opt/ros; nvidia-smi \|\| tegrastats --interval 1000 \| head -3; ip -br a; lsusb; lsblk` | `hw/B9_identity.txt` | **JetPack 5 → stop at §7.2.** JetPack 6 → continue |
| B-fw firewall | apply the nftables ruleset from HW-1's DESIGN; verify `nft list ruleset`; robot NIC has no default route | `hw/B_fw.txt` | must pass before any WAN interface comes up |
| S20 firmware | `parcel-capture attest` (reads version over DDS on the robot NIC only); record; disable OTA in the app | `hw/S20_firmware.txt` | version < 1.1.13 → owner decision, still firewalled |
| Q-dev DDS exposure | `ros2 topic list` / `cyclonedds ls` on domain 0: do `rt/sportmodestate`, `rt/utlidar/*`, `rt/uwbstate`, `rt/frontvideostream` appear? | `hw/Q_dev_topics.txt` | absent → "secondary development" toggle (app / go2_firmware_tools), recorded |
| Q-lidar head model | `preflight.probe_builtin_lidar`: `rt/utlidar/lidar_state` model string + measured cloud rate | `hw/Q_lidar.txt` | settles L1/L2 and the voxel_map question |
| Q-wire Mid-360 | which NIC sees Livox UDP (`tcpdump -i <nic> udp port 56300`), device IP, M8 voltage (meter, powered off first) | `hw/Q_wire.txt` | decides §5.7's static address |
| Q-usb dock USB | `lsusb -t`; D455 on USB 3.0 A → `rs-enumerate-devices`; XVF3800 on a C port → `tools/xvf3800_probe.py` | `hw/Q_usb.txt` | both enumerate at USB 3 / full-speed respectively or the mount sheet changes |
| B11 extrinsics | mount sheet (two persons): D455 height/tilt, Mid-360 to base_link, array position; tape + the clock-map ritual (B25 `syncevents`) | `hw/B11_extrinsics.yaml` | numbers go in the profile, never in code |
| B12 recorder smoke | `parcel-capture record --plan stage0 --dry-run` then 60 s real; rosbag2 Humble argv; sidecar written | `hw/B12_record.mcap` | the 08-13 Stage-0 run sheet rewritten for EDU+ (no separate dock, Mid-360 not L2) |
| S19 Stage 0 | `parcel-commission observe` 10 min: `SportModeState_` rate, zero `Move`, journal | `hw/S19_stage0.json` | gate for any `--arm` |
| Q-stop | on the stand, sport mode on, issue `StopMove` then L2+B from the remote with the head board's NIC unplugged; does it damp? | `hw/Q_stop.txt` | PO-1's record cites this |
| Q-ort | daemon venv: OWLv2 fp16 latency at the dog's power mode (`tegrastats` alongside) | `hw/Q_ort.txt` | EP choice (§5.2) |
| Q-link | RTT from the Orin to the hosted lane over Wi-Fi 6 (and 4G if provisioned), 5-min sample | `hw/Q_link.txt` | spend ledger + HOLD rule |

### 7.2 If B9 says JetPack 5.1.1 (Ubuntu 20.04 / Python 3.8)

Three options, owner-decided, none taken by a card on its own: (i) reflash
the dock to JetPack 6.2.1 — supported only if Unitree publishes a BSP for
the custom carrier (UNKNOWN, Q-jp); full backup first; warranty-sensitive;
ADR 0001's two-dock rule is waived on record or a second unit is bought;
(ii) run the product on a deadsnakes/uv CPython 3.10 on 20.04 with CUDA
11.4 — the perception daemon then has no prebuilt ort-gpu wheel at all and
OWLv2 moves to the desktop over the tailnet; (iii) hold the software-now
rail's box-day proofs until (i) is possible. This doc's default is (i) if
the BSP exists, else (ii) with perception off-dog — and either way §5.1's
3.10-clean sweep is needed.

## 8. Unknowns register — every one with its resolving measurement and who decides

| Id | Unknown | Resolved by | Decider |
|---|---|---|---|
| Q-jp | JetPack/L4T on the 2026 EDU+ dock; BSP for 6.2.1 on the Unitree carrier | B9; Unitree support ticket (software-now: ask now) | owner |
| Q-lidar | head LiDAR L1 vs L2; `rt/utlidar` rates; coexistence with the Mid-360; `utlidar/switch` | §7 Q-lidar | design (this doc updates §5.3) |
| Q-wire | Mid-360 NIC/subnet/M8 voltage; `livox_ros_driver2` preinstalled? | §7 Q-wire | design |
| Q-fwv | shipped firmware; OTA default; CVE-2026-27509 fixed version | S20; GHSA watch | owner (pin), design (firewall stands regardless) |
| Q-stop | does L2+B damp when head board/dock hang? | §7 Q-stop | PO-1 |
| Q-usb / Q-pwr | USB-C count; payload power; runtime under Orin+Mid-360+D455+array | §7 Q-usb; a 30-min idle + 30-min roam battery log | owner (mount sheet) |
| Q-cam | H264 multicast reaches the dock NIC? `rt/frontvideostream` 33 Hz usable? | capture channel smoke | design (capture-only either way) |
| Q-uwb | `rt/uwbstate` contents; fob shipped; indoor accuracy (U39) | decode + tape test | design (evidence only) |
| Q-ort | ort-gpu ≥ 1.28 buildable on JetPack 6.2.1? else ≤ 1.23 / TensorRT | §7 Q-ort | design |
| Q-dev | DDS exposure on by default? | §7 Q-dev | — |
| Q-avoid | sport-mode obstacle avoidance under `SportClient.Move` vs Parcel's yield/doorway | Stage-1 one-axis toward a box at 0.10 m/s | design (HW-6) |
| Q-slam | FAST-LIO2 vs Point-LIO; Parcel owns `T_map_odom` or integrates | B17 bake-off on one recording | design |
| Q-image | golden image with ONE integrated Orin (ADR 0001 two-dock rule) | owner | owner |
| Q-link | Wi-Fi 6 vs 4G RTT; link-loss behaviour | §7 Q-link | design (HOLD) |
| Q-pose | do `curious_look`/sit/greet get a commissioned `GatewayActionV1` on the dog? | after leashed stage | owner + PO-1 |
| Q-batt | duty cycle, dock/charge, low-battery roam behaviour | battery log | design (HOLD at 20 %, recorded) |

## 9. Wave-3 cards (`scrum/20260822/task_35+`), two rails — every card writes `DESIGN.md` before code, names its seam rows from §4, the product-path caller, §e hardware-compat class, and its first command

**Software-now rail (starts today; no hardware; the sim gate proves it):**

| Card | Seams | Deliverable | Acceptance (pre-registered by the executor) | First command |
|---|---|---|---|---|
| HW-1 `py310-clean` | S22, §5.1 | guarded imports at the eight sites; per-extra Python ranges; `requirements-lock-jetson.txt` (cp310 aarch64 resolvable, dry-run with `pip download --platform manylinux2014_aarch64 --python-version 3.10`); CI 3.10 `base` job | `python3.10 -c "import parcel_robot.runtime"` green in a 3.10 venv on the desktop; gate unchanged on 3.14 | `uv venv --python 3.10 ~/.cache/parcel-hw1/py310` |
| HW-2 `go2-backend` | S1, S3(ODOM), §5.4 | `backends/go2.py:Go2Backend` observe-only, `evidence_origin` physical, `apply` refused with citation; recorded-DDS fixture | `reactive_safety.scan_present` true from a recorded `rt/sportmodestate` + band scan; `apply` raises; sim baselines byte-identical | the fixture from the 08-13 Stage-0 recording format |
| HW-3 `mid360-band` | S6, §5.3 | raw-UDP Livox decoder (no ROS) + planar band filter → `lidar_ranges`; `SourceDevice.MID360`; `L2` → `HEAD_LIDAR`; unilidar path retired | a recorded pcap of one Mid-360 sweep (from Livox's public samples) yields a scan with the sim's angular layout; filter pure, property-tested on the z-band | `tests/test_hw3_mid360_band.py` against the sample pcap |
| HW-4 `array-gateway` | S11, S12, §5.6 | `ArrayAudioGateway` (PortAudio, 16 ↔ 24 kHz), selectable `audio.gateway`; the AIR-1 through-air session on the desktop with the array | TV-on false barge-in ≤ 2 % over the owed 1.3 h session; corpus replay green on the new path | `tools/xvf3800_probe.py` then `launch_stack.sh --audio array` |
| HW-5 `physical-profile` | S14, S15, §5.8 | `configs/profiles/go2_edu_plus.yaml`; new introducible keys with pins; `required_capabilities` declared | desktop start with the profile REFUSES (no D455/DDS) with the CAP-1 message; sim profile unchanged | `parcel-runtime --profile go2_edu_plus` (expected refusal) |
| HW-6 `stopping-envelope` | S5, §6 | RC-4 derivation parameterised by measured braking/LIO/period; a gate row that fails when the sum exceeds the commissioned distance; Q-avoid test plan | seeded: a 50 ms braking latency over budget reddens the row | `bridge/timing.py` derivation with placeholder inputs marked UNMEASURED |
| HW-7 `gate-on-aarch64` | S26, S21 | `ci_gate --tier commit` row set identical on aarch64 minus typed SKIPs; `env-audio.sh`/Piper/llama aarch64 variants | the gate JSON diff is exactly the declared SKIP set; proven in a qemu-user aarch64 container on the desktop (slow, nightly) | `docker run --platform linux/arm64 ...` |
| HW-8 `box-day-runbook` | §7 | the §7 table as `docs/BOX_DAY.md` + the rewritten Stage-0 run sheet (EDU+, Mid-360, no separate dock) + the Unitree support ticket for Q-jp/Q-wire filed NOW | owner read and signed; ticket reference recorded | — |

**Box-day rail (gated on delivery; each step of §7 is one row; the card is
`HW-9 first-two-hours` and its status doc IS the §7 result files).** After
it: HW-10 `b17-lio-bakeoff` (one recording, two providers, drift table),
HW-11 `native-gateway-on-orin` (N28/N43 build on 22.04, watchdog proof,
pattern table for HY-1's guard), HW-12 `first-armed-step` (PO-1 record on
file, HW-6 row green with measured numbers, one axis, 0.10 m/s, stand).

Nothing in the box-day rail is estimated in hours here; the owner's
6–8 h budget covers HW-9 and HW-12 only. HW-10/11 are engineer time.

## 10. What this design falsifies in prior documents (explicit), and the critic pass

**Falsified / superseded (the sentence, where, by what):**
1. `PLAN_ASSESSMENT_FABLE.md:57-60` "Don't buy Orin NX docks / EDU Plus /
   the L2" and its Phase-3 row "the Orin is unnecessary; B9/B10/B12/U37/U38
   retire" — reversed by the purchase; B9/B10/B12 are live again (§7).
2. `task_27/README.md:3-16,24-63` "EDU Standard quote; decline the Orin
   dock and L2 add-on" — superseded by the banner; the D455 buy survives
   verbatim (front camera is RGB-only [documented], VENUE-1 ruling stands).
3. HLD §2.2 / exec summary §1.2 "decline assumed Orin/L2 add-ons until a
   consumer and compute need are proven" — the consumer is §5.3/§5.4, the
   compute need is §5.2/§5.6.
4. `RESEARCH_2026_ROADMAPS.md:42,71-73` "the Orin NX 16 GB dock is an
   assumed future target, not owned" — it is ordered; the duplex sizing
   argument there is now a measurement (Q-ort, Q-link), not an assumption.
5. `capture/channels.py:145-154` and the 28-channel matrix's "add-on
   Unitree L2 via unilidar_sdk2" — there is no add-on L2; the head unit is
   DDS-only and the external LiDAR is a Mid-360 (§5.3, HW-3).
6. The handbook's implication that RTX measurements characterise the
   Orin — never true; §5.2 measures.
7. ADR 0001's two-dock golden-image rule — not falsified but re-opened
   (Q-image): there is one integrated Orin on a custom carrier.
8. `PLAN_ASSESSMENT` weeks 4–5 "N28 sidecar gateway in a 3.11 venv with
   unitree_sdk2py" — the gateway is native C++ (§5.5) and the Python SDK
   is commissioning-only; no 3.11 on the dog (§5.1).
9. WAVE2_DESIGN's DW-5 deferral "hardware-gated" — the gate lifts with a
   2–4 week lead time; its pre-hardware pieces are HW-2/3/5/6.

**Unchanged and re-affirmed:** ADR 0002 (pin, OTA off, firewall, tailnet,
never flash); MOTION.md stop doctrine; the first ODD; the four tells
(ROAM-1 met 7/7; through-air TV-on owed = HW-4; owner backlog open;
GATE-0b's clean-clone row); exec summary §9 (no learned component
manufactures physical truth) — §5.3's LIO publishes geometry, the learned
map proposes, admission decides.

**Critic pass (adversarial re-read against `research.json`, parcel-6c,
06:4x):** every `[documented]`/`[measured]` tag above was checked against
a fact entry in the file; the three claims I could not ground in it and
therefore softened to UNKNOWN or marked as design choice: the Mid-360 band
limits `[0.10, 0.60]` (a design parameter, not a fact — goes in the profile
as a number to be tuned at B11); the assertion that `livox_ros_driver2`
needs ROS (documented) versus the raw-UDP decoder being "testable against a
pcap" (a claim about OUR future code, not a fact); and "the lane already
degrades to local-only on websocket close" (codebase lens fact 13 names the
browser gateway and sink, not the degrade path — HW-4 must verify it in
`realtime/lane.py` before relying on it; recorded as a check, not a fact).
One inconsistency found and fixed: §3's table said the product venv is
"CPython 3.10 (JetPack system)" unconditionally — §5.1 and §7.2 now carry
the JetPack-5 branch it omitted. No other claim in §1–§3 contradicted the
file.
