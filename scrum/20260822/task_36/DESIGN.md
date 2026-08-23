# HW-3 `mid360-band` — DESIGN

Card `scrum/20260822/task_36/README.md`. Design rows S6 (NEW) feeding S2 (VI)
of `../WAVE3_HW_DESIGN_FABLE.md` §4; §5.3 is the decision this implements.
Executor: Opus (session 31fcc2a0 wave 3a). Over the 150-line target because
the frame table and the two "identical to the sim" derivations are the
deliverable a verifier must be able to check without re-reading Livox.

## (a) Purpose

The runtime has exactly one physical-fact source: `backends/base.py:
SimObservation` (`lidar_ranges`, `nearest_obstacle_m`), produced today only by
`backends/mujoco.py:MujocoSocketBackend.observe` (research codebase fact 10,
[measured]). Nothing in the tree reads a Livox (codebase fact 7, [measured]).
This card lands the pure, offline-testable half of the physical scan: **UDP
bytes -> points -> a planar height band -> a ranges tuple in the sim's exact
angular layout**, so HW-2's `Go2Backend` has nothing left to invent and
`navigation/reactive_safety.py` (S2, VI) is not touched at all.

The Mid-360's vertical FOV is -7 deg..+52 deg [documented, hardware fact 5]:
it sees up, not down. A band is therefore what it can honestly give a planar
consumer; floor drops and low obstacles are the D455's job (S9) and are NOT
covered here.

## (b) Architecture fit — seams, and who calls them

| Seam (`module:symbol`) | Direction | Caller on the product path |
|---|---|---|
| `parcel_robot.lidar:parse_point_frame` | new | HW-2 `backends/go2.py:Go2Backend._drain_lidar` (wave 3b), and a box-day capture reader (HW-9) |
| `parcel_robot.lidar:scan_from_frames` | new — **the HW-2 seam** | `Go2Backend.observe()` -> `SimObservation(lidar_ranges=..., lidar_angle_min_rad=..., lidar_angle_increment_rad=..., lidar_range_min_m=..., lidar_range_max_m=...)`. **`BandScan.ranges_m == ()` means the sweep is not a scan and must be published as `lidar_ranges=()` so the runtime HOLDs — never copied across** |
| `parcel_robot.lidar:nearest_obstacle_from_scan` | new — **the HW-2 seam** | `Go2Backend.observe()` -> `SimObservation.nearest_obstacle_m` / `.nearest_obstacle_bearing_rad` |
| `parcel_robot.lidar:receive_frames` | new, socket-only adapter | `Go2Backend`'s reader thread; never called by the parser or by any test |
| `navigation/reactive_safety.py:scan_present`, `:scan_evidence_from_observation` (722-747) | unchanged (VI) | already the runtime's consumer; this card only proves it accepts the band output |
| `capture/channels.py:SourceDevice.MID360` + `MID360_CHANNELS` | new rows | capture planning (HW-9 box-day), `preflight`/`record` when a Livox reader exists |
| `scripts/parcel_capture/ingest/l2.py:L2Ingest.__init__` | venue refusal added, **INERT today** | `ingest/__init__.py:117-118 adapter_for` calls `factory()` with no arguments, so nothing passes `venue=`; the only reachable effect is `RETIREMENT_NOTE` on `L2Ingest.notes`. HW-5 owns the wiring |

Nothing here imports `mujoco`, `numpy`, `rclpy`, a Livox SDK, or a socket at
module scope. `parcel_robot/lidar/` imports the standard library plus
`parcel_robot.robot_profile` (a declared leaf: "must not import anything from
`parcel_robot`", `robot_profile.py:8-13`), so the `base` extra on CPython
3.10 / aarch64 imports it (HW-1's row).

## (c) The frame layout I decode

Read: `https://raw.githubusercontent.com/Livox-SDK/Livox-SDK2/master/include/
livox_lidar_def.h` (the SDK2 header the driver compiles against; the point
structs are inside `#pragma pack(1)` / `#pragma pack()`), the HAP wire table
`https://github.com/Livox-SDK/Livox-SDK2/wiki/Livox-SDK-Communication-Protocol-HAP(English)`,
`https://raw.githubusercontent.com/Livox-SDK/livox_ros_driver2/master/src/comm/pub_handler.cpp`
(how the driver itself decodes), and the Mid-360 port map
`https://raw.githubusercontent.com/Livox-SDK/Livox-SDK2/master/samples/
livox_lidar_quick_start/mid360_config.json`. The Mid-360-specific wiki page
did not load (GitHub wiki error) — every row below marked UNCONFIRMED is a
field whose *meaning* is documented only on the HAP page or nowhere, and the
decoder refuses on it or carries it verbatim rather than guessing.

**Correction pass (verifier F3):** two refusals were first written as if
the formats were unknown. They are not. `data_type` 3 and 0x11 are fully
documented in sources this card already cites, and they are refused because
HW-3 does not implement them — out of scope, not unknown. The distinction is
load-bearing on box-day: "we could not read the format" would justify a
stall, "we chose not to implement it" is a 20-line change with a citation.

`LivoxLidarEthernetPacket`, little-endian, byte-packed, 36-byte header:

| off | size | field | what HW-3 does |
|---|---|---|---|
| 0 | 1 | `version` (u8) | **refuse** unless in `SUPPORTED_PROTOCOL_VERSIONS = {0}` — the field layout is version-defined, so decoding an unknown version fabricates geometry |
| 1 | 2 | `length` (u16) | carried as `declared_length`; **never decoded with**. "bytes from beginning of sof to end of data" is the HAP page's wording — UNCONFIRMED for Mid-360 |
| 3 | 2 | `time_interval` (u16, unit 0.1 us) | `* 100` = the packet's sampling window in ns |
| 5 | 2 | `dot_num` (u16) | point count; refuse `0` and refuse `> MAX_POINTS_PER_FRAME` |
| 7 | 2 | `udp_cnt` (u16) | carried; the sweep assembler uses it for out-of-order/gap detection |
| 9 | 1 | `frame_cnt` (u8) | carried. "HAP keeps 0" — Mid-360 behaviour UNCONFIRMED, so nothing branches on it |
| 10 | 1 | `data_type` (u8) | dispatch; see the table below |
| 11 | 1 | `time_type` (u8) | carried + exposed as `TimeType`: `0` = no sync (clock since LiDAR power-on), `1` = gPTP master clock. Both are uint64 ns [documented, HAP page]. Any other value is carried as-is and marked unknown, never mapped |
| 12 | 12 | `rsvd[12]` | carried verbatim. The HAP page names byte 12 `pack_info` (bit0-1 safety_info, bit2-3 tag type); the SDK2 header calls all twelve reserved. UNCONFIRMED -> never decoded |
| 24 | 4 | `crc32` (u32) | carried, **not verified**: "CRC-32 algorithm" is stated but the polynomial/seed/reflection/xorout are not, so a guessed CRC would reject every real packet. UNCONFIRMED |
| 28 | 8 | `timestamp` | 8 bytes in HOST order — the driver memcpy's them into a `uint64` (`pub_handler.cpp:265-268`), i.e. LE on x86_64/aarch64; the frame's base ns |
| 36 | `dot_num * S` | `data` | points |

Data types (`LivoxLidarPointDataType`) and per-point size `S` under
`#pragma pack(1)`:

| value | name | S | HW-3 |
|---|---|---|---|
| 0 | `kLivoxLidarImuData` | 24 (6x f32) | **refuse** in the point parser — IMU arrives on its own port (56400) and is not point data |
| 1 | `kLivoxLidarCartesianCoordinateHighData` | 14 (`i32 x,y,z` mm; `u8 reflectivity`; `u8 tag`) | **decoded**, scale 1e-3 m |
| 2 | `kLivoxLidarCartesianCoordinateLowData` | 8 (`i16 x,y,z` cm; `u8`; `u8`) | **decoded**, scale 1e-2 m |
| 3 | `kLivoxLidarSphericalCoordinateData` | 10 (`u32 depth`; `u16 theta`; `u16 phi`; `u8`; `u8`) | **refuse — DOCUMENTED, not decoded in HW-3.** `pub_handler.cpp:429-431` converts theta/phi at 0.01 deg and depth in mm. The Mid-360 is configured for Cartesian output; a half-tested second geometry path is a liability, and refusing keeps the scan honest |
| 0x11 | `kLivoxLidarDoubleEchoData` | 28 (two returns of `{i32 x,y,z` mm`; u8; u8}`) | **refuse — DOCUMENTED, not decoded in HW-3.** `livox_lidar_def.h:174-185` defines `LivoxLidarDoubleEchoRawPoint`; `pub_handler.cpp:469-482` decodes it. Which echo a band bin should take is a B11 question with a real sensor, not a decoder detail |

Sizes 14/10 are the packed `sizeof` of the SDK2 structs; `pub_handler.cpp`
casts `data->data` to the struct and indexes it, which is the same claim.
`livox_ros_driver2/src/comm/comm.h`'s `KCartesianPointSize = 13` /
`KSphericalPointSzie = 9` are the **SDK1** raw points (no `tag` byte:
13 = 3x4+1, 9 = 4+2+2+1) and are not the SDK2 wire sizes — recorded here
because the contradiction is the kind of thing a reader trips over.

Per-point timestamp, exactly the driver's arithmetic (`pub_handler.cpp`):
`point_interval_ns = time_interval * 100 // dot_num`;
`t_i = timestamp + i * point_interval_ns`.
Scaling, exactly the driver's: `x_m = x_raw / 1000.0` (high) or `/ 100.0`
(low). `tag` is carried as a raw byte and **never interpreted** (bit meanings
UNCONFIRMED). `time_type` is the documented three-member set of `livox_ros_driver2/src/comm/comm.h:96-98` — `NoSync = 0`, `GptpOrPtp = 1`, `Gps = 2` — and `LivoxPointFrame.synchronised` is true for the last two; an unknown value is carried and is never synced. Structural guard: `len(payload) == 36 + dot_num * S`, else
refuse — this is the truncated-frame refusal.

Ports/addresses [documented, `mid360_config.json` + hardware fact 6]: LiDAR
cmd 56100, push 56200, **point 56300**, IMU 56400, log 56500; host ports are
+1 (point data lands on host **56301**); sample host IP 192.168.1.5,
multicast 224.1.1.5. Which Orin NIC/subnet the M8 plug rides is UNKNOWN until
the box (Q-wire, design §8) — the constants are module-level and named, never
baked into a socket call inside the parser.

## (d) The band, and the angular layout it must reproduce

Sim layout, read from `mujoco_lidar.py:raycast_planar_scan` +
`PlanarScan` (lines 400-560) and `sim.py:307-322` -> `backends/mujoco.py:
_parse_lidar_scan` -> `SimObservation`:

* `DEFAULT_SCAN_RAYS = 360` bins;
* `angle_min = -math.pi`, `angle_increment = 2*pi/num_rays`, body-relative
  (`world_angles = robot_heading + body_angles`), **counter-clockwise**
  (index up = bearing up);
* `range_min_m = 0.05`, `range_max_m = 30.0`;
* **`range_max_m` = "a no-return that clears free space"; `NaN` = "an ignored
  ray" (dropout/self-return), which clears nothing** — `PlanarScan`'s
  docstring, which also says this mirrors the navigation `LidarScan` contract.

Band (all PROFILE parameters on `BandProfile`, no constants):
`z_lo_m = 0.10`, `z_hi_m = 0.60` above `base_link` — **"tune at B11"**, the
extrinsic-measurement step of design §7; `extrinsic` is a 4x4 row-major
sensor->base_link transform, default identity and **UNCONFIRMED until the
mount is measured (B11)**; `bins`, `angle_min_rad`, `angle_increment_rad`,
`range_min_m`, `range_max_m` default to the sim's five numbers, restated as
literals with a citation (importing `mujoco_lidar` would drag `mujoco` into an
aarch64 `base` venv) and pinned equal to it by
`tests/test_hw3_mid360_band.py::test_band_profile_defaults_match_the_sim_scan_contract`.

Pipeline, one pass per point: `z' = m20*x + m21*y + m22*z + m23` (the z row
only) -> reject unless `z_lo <= z' <= z_hi` -> compute `x', y'` -> planar
`r = hypot(x', y')` (the sim's rays are horizontal, so the planar projection
is the like-for-like quantity) -> reject `r < range_min_m` or `r >
range_max_m` -> `bin = floor((wrap(atan2(y', x')) - angle_min)/inc + 0.5) %
bins` (nearest ray centre, the LaserScan convention: `angle_min` is the
bearing OF bin 0, not a cell edge) -> keep the **minimum** r in the bin
(the sim's ray returns the first surface it meets).

**Empty bins are `NaN`, not `range_max_m` — a deliberate deviation from the
card's wording, and the one design judgment here.** The card says "empty bins
are the sim's 'no return' value — read what the sim emits". I read it: the sim
emits two different values for two different facts, and a MuJoCo ray that
reaches `range_max` has *looked* down that bearing and seen nothing. One
Mid-360 frame has not: the pattern is non-repetitive, so at 10 m a 0.5 m band
subtends ~3 deg of the 59 deg vertical FOV and a bin can be empty because
nothing was sampled there. Emitting `range_max` would clear free space on no
evidence, in the one channel the safety layer reads. `NaN` is the sim's own
word for "this ray clears nothing", so the band uses it and stays inside the
contract. How many frames must be accumulated before a bin may be declared
free is a MEASUREMENT, owed on box-day (HW-9/B11), not a number to pick here.

**A sweep that measured NOTHING is not a scan — corrected in the correction
pass (verifier F1, HOLD).** Per-bin emptiness and whole-sweep emptiness are
different facts and the first version conflated them: `scan_from_frames([])`
— what `Go2Backend` produces on a tick that drained no frames (cable out,
wrong NIC, unit off) — returned 360 NaN, and `reactive_safety.scan_present` is
`bool(observation.lidar_ranges)`, so zero measurements read as "a scan is
present" and `apply_reactive_safety` passed 0.3 m/s as "clear". The sim can
never produce that state (its raycaster fills no-hit rays with `range_max`),
so the band was handing the safety layer a state it had never been shown.
`BandProfile.min_populated_bins` (default `1`, the floor; the venue's real
minimum is **tuned at B11** against measured coverage) now gates it: below it
`band_scan` emits `ranges_m=()`, the `SimObservation` value for "no calibrated
scan", on which `scan_present` is False, the core health join reports SCAN
missing and translation HOLDs. `points_seen` / `points_in_band` /
`populated_bins` are still reported on that `BandScan`, because box-day needs
the coverage number even for a sweep that was not a scan. HW-2 must therefore
BRANCH on `ranges_m` rather than copy it (the seam snippet in `__init__.py`
shows the branch).

`nearest_obstacle_m`, identical to the sim's derivation — which is NOT the
scan: `sim.py:265-272` takes `scan_mujoco_lidar` hits whose `distance_m` is
`max(0.0, surface_distance - footprint_radius_m)`
(`mujoco_lidar.py:planar_geom_surface_hit`), then `sim.py:54-79
select_relevant_obstacle`: when translating (`hypot(vx,vy) > 1e-6`), the
nearest candidate whose bearing error from `atan2(vy,vx)` is `< 1.15` rad, if
any; otherwise the global nearest. `nearest_obstacle_from_scan` reimplements
exactly that over populated bins (`footprint_radius_m` from
`DEFAULT_ROBOT_PROFILE`, a profile field, not a literal) — reimplemented and
not imported because `parcel_robot.sim` imports `mujoco` and `numpy` at module
scope, and pinned to the original by a differential test that DOES import
`sim.select_relevant_obstacle` (test-only) and compares on random candidate
sets and the same 1.15 rad half-angle `reactive_safety.py:_toward` uses.

## (e) Hardware compatibility — class NEW (S6) feeding VI (S2)

* **Venue-independent by construction:** the parser and the band are pure
  functions over bytes and floats — no socket, no SDK, no ROS, no numpy, no
  mujoco; identical on x86_64/3.14 and aarch64/3.10.
* **Must be configured:** `BandProfile.extrinsic` (B11 tape measure),
  `z_lo_m`/`z_hi_m` (B11), the host NIC/IP/port the reader binds (HW-5's
  `configs/profiles/go2_edu_plus.yaml`).
* **UNCONFIRMED until the box:** which Orin NIC and subnet the M8 plug rides
  and the M8 pin voltage (Q-wire; hardware facts 7/24 are [inferred], not
  documented); whether `livox_ros_driver2` is preinstalled; the real
  `version`/`frame_cnt`/`length`/`crc32` values a Mid-360 emits; the `tag`
  bit meanings; per-bin coverage per frame.
* **NOT consumed here:** the built-in head LiDAR (`rt/utlidar/*`, hardware
  fact 4) — capture-only until its model is read (§5.3), and the L2->
  HEAD_LIDAR rename is HW-2/HW-9's.
* **What the desktop cannot prove:** that a real Mid-360's bytes match this
  table (no pcap of a Mid-360 exists here; every frame in the tests is
  synthesised from the table above), the extrinsic, the coverage number, the
  Orin's timing, and anything about the M8 plug.

## (f) Test strategy -> pre-registered rows

`PREREGISTRATION.md` rows R1-R9 map 1:1 onto the card's (a)-(d) plus the
seeds. The integration row R6 runs `reactive_safety.scan_present` and
`scan_evidence_from_observation` through the REAL functions on a real
`SimObservation` built from a real band scan — no monkeypatch, no stub.

**A finding R6 must state, because the card's wording cannot be satisfied:**
`core/input_health.py:114-134 evidence_origin` returns
`(EvidenceOrigin.SIMULATION, str(label))` for **every** input — "There is no
string ... that reaches `EvidenceOrigin.PHYSICAL` from here or from anywhere
else" (board decision D-1, card W0-A). So a `SimObservation` with
`backend="go2"` is a LABELED SIM FIXTURE, and the card's "labels it physical
when `backend='go2'`" (and design §4 row S1's "`evidence_origin == physical`")
is **not reachable through `SimObservation` by construction**. R6 asserts what
is true and useful: `scan_present` is True, the evidence is
`SIMULATION`/`"go2"`, and `evaluate_input_health` ALLOWS on it under
`reactive_safety`'s own spec (`sim_fixture_allowed=True`). Physical origin is
a HW-2 handoff — and **sharper than this card first wrote it** (verifier F5):
`control/base.py:CommissionedStateSource` carries a `RobotMotionState` through
`latest()`, i.e. pose and controller feedback, **not a scan**. There is no
typed physical scan-evidence seam in the tree at all; `evidence_origin`'s own
docstring calls migrating `reactive_safety.py` onto one "a W0-F/W1 follow-up".
Measured: under `requirements_requiring_physical_inputs()` a band scan on
`SimObservation(backend="go2")` yields `LATCHED_STOP ['sim_fixture_forbidden']`
— which is the CORRECT fail-closed result, not a defect. So a physical scan
origin needs a NEW typed source that declares `EvidenceOrigin.PHYSICAL` on the
datum plus a runtime read of it in place of `scan_evidence_from_observation`.

## (g) Risks, and what this design does not cover

1. **The frame table is read, not measured.** Mitigation: every field the
   sources did not define is refused or carried verbatim; the byte-count check
   catches a wrong `S`; box-day (HW-9) records one real frame and this table
   is falsified or confirmed in one command.
2. **`version` refusal could false-refuse on the box** if a Mid-360 ships a
   non-zero protocol version. Mitigation: it is a named module constant, the
   refusal message says to read the real value and add it, and it is a
   one-line change — never a silent decode.
3. **The capture matrix does not grow here.** `capture/channels.py:CHANNELS`
   is a verbatim transcription of the immutable `scrum/20260813/task_1/
   CHANNEL_MATRIX.md` (25 rows / 28 channels), pinned by
   `tests/test_capture_envelope.py:149,160,1489` — a file outside HW-3's OWNS,
   with four peer executors in the tree. And a raw-UDP `Transport` member
   would raise at `scripts/parcel_capture/record.py:1434` (unmapped transport)
   and redden `tests/test_capture_sidecar.py:1274`. So the Mid-360 rows land
   BESIDE the matrix as `MID360_CHANNELS`, exactly as card S-1 landed
   `SUPPORT_ARTIFACTS` beside it (`channels.py:1468-1495`), and merging them
   into a re-cut table A is a named handoff.
4. **The L2 retirement gate is inert and this design says so plainly**
   (verifier F4). `L2Ingest(venue="go2_edu_plus")` refuses with a pointer to
   `parcel_robot.lidar`, but no caller passes `venue=`: `ingest/__init__.py:
   117-118 adapter_for` does `factory()` for every `LIVE_ADAPTERS` entry,
   `orin_rehearsal.py:2072` does `L2Ingest()`, `configs/profiles/` does not
   exist yet, and `go2_edu_plus` appears nowhere outside this card's files.
   The mechanism is landed so the wiring is a one-argument change; the wiring
   belongs to HW-5, which owns the profile that names the venue. An
   unconditional raise in `__init__` would break `adapter_for` for every
   adapter, and one in `open_reader()` would redden the legacy rig's own
   contract (`tests/test_capture_ingest.py:1615,1637,2459`) — not this card's
   to change. What IS reachable today: the retirement note rides on every
   report the adapter emits.
5. **Not covered:** sweep assembly policy across UDP packets beyond
   `udp_cnt` ordering; LIO / `T_map_odom` (B17, design §5.3); the head LiDAR;
   floor drops below the band (D455, S9); Q-avoid (the Go2's own avoidance);
   any motion authority whatsoever — this card produces observations only.
