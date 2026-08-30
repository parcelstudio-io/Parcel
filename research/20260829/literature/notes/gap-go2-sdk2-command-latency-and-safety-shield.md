# Gap note: Go2 EDU SDK2/DDS command latency, rate limits, concurrency safety, and how learned outputs are shielded on quadrupeds

Literature note for the 2026-08-29 Model A / Model B study. Every source below was fetched and read on 2026-08-29 (WebFetch; the Unitree support pages are a JavaScript SPA, so they were read through the `r.jina.ai` rendering mirror of the same URL; two PDFs were saved and read locally with `pdftotext`). Numbers are quoted from the fetched text. Where a number came from an abstract or an auto-summarised page rather than the body, that is said.

Scope asked for: quantified latency and rate limits of the Go2 EDU SDK2/DDS velocity and joint commands (Move / Euler / LowCmd), command-to-motion latency measurements, concurrency-safety of `unitree_sdk2py`, and how learned navigation / expression outputs are shielded on quadrupeds (CBFs, safety filters over velocity commands, safe-RL shields, LiDAR stop envelopes), including community measurements.

Headline answers first:

1. **`Move(vx, vy, vyaw)` is a fire-and-forget DDS request, not a stream.** In `unitree_sdk2py` it is the one sport call that uses `_CallNoReply` (api id 1008); `Euler` (1007) and `StopMove` (1003) are blocking RPCs with a 1.0 s default timeout. Since firmware V1.1.6 (Motion Control Service V2.0, notice dated 2025-05-12) "the latest Move command will be maintained for 1 second", and Unitree tells you to "apply filtering before sending; when not using Move, send Move(0,0,0) or StopMove()". Ranges: vx [-2.5, 3.8] m/s, vy [-1.0, 1.0] m/s, vyaw [-4, 4] rad/s; Euler roll/pitch [-0.75, 0.75] rad, yaw [-0.6, 0.6] rad.
2. **No published step-response / command-to-motion latency measurement for Go2 sport mode exists in anything fetched.** The nearest measured figures are: 18-30 ms command transmission on a Unitree G1 through an LCM bridge (50 Hz policy / 500 Hz low level); sub-millisecond DDS hop on a Jetson Orin Nano (Fast DDS 0.685 ms mean for a Unitree L1 LiDAR frame); 33.9 ms mean WebRTC network latency on a Go2 Pro; 206.7 ms (Wi-Fi) / 78.3 ms (Ethernet) mean for a Go1 Air app-protocol bridge. The SDK's own LowCmd loop is 500 Hz (2 ms recurrent thread) and sport-client examples run at dt 0.005-0.01 s.
3. **Concurrency:** the DDS core is documented thread-safe ("everything is thread-safe"), the Python RPC future table is behind a `Lock`, but `_CallNoReply`/`_Call` take no lock, `Channel.Write` can block up to the timeout polling every 0.1 s for a matched subscriber, and subscriber handlers run *inside the DDS listener thread* when `queueLen == 0` - writing from there is a documented deadlock path in cyclonedds-python. WebRTC allows one client at a time; DDS on the robot's domain 0 has no authentication (CVE-2026-27509).
4. **Shielding on quadrupeds is done at the velocity-command layer at 10-50 Hz with sub-millisecond to few-millisecond compute**, and it has been demonstrated on exactly Parcel's stack: REASAN runs a learned safety-shield network on a Go2 + Livox Mid-360 + Jetson AGX Orin 64 GB at 50 Hz, turning "an arbitrary velocity command into a safe one", with zero collisions across 40 real traversals. Point-cloud CBFs on a Go2 (Orin NX) cost 0.78 ms per step at 10 Hz LiDAR; a safety-index QP over body-frame velocity runs at 30 Hz. Every deployed system keeps the vendor's proprietary controller underneath and filters only [v, omega].

---

## Part 1 - The official interface: what the SDK and Unitree docs actually say

### 1.1 High-level sport service (Move / Euler / StopMove), official docs

- Source: Unitree "High level Sports Service Interface", https://support.unitree.com/home/en/developer/sports_services (read via r.jina.ai mirror).
- `Move(vx, vy, vyaw)`: "Control movement speed"; vx "[-2.5~3.8 ] (m/s)", vy "[-1.0~1.0 ] (m/s)", vyaw "[-4~4 ] (rad/s)".
- `Euler(roll, pitch, yaw)`: roll "[-0.75~0.75 ] (rad)", pitch "[-0.75~0.75 ] (rad)", yaw "[-0.6~0.6 ] (rad)".
- `SpeedLevel(level)`: "-1 for slow speed, 0 for normal speed, and 1 for fast speed".
- `ContinuousGait`: "After starting a continuous gait, the robot dog will continue to maintain a gait state, even if the current speed is 0".
- Example sets `sport_client.SetTimeout(10.0f)`; the posture-tracking example uses "double dt = 0.01" (100 Hz loop).
- Error code "4201 | Action timeout error, the specified action was not completed within the expected time".
- The page does not say whether Move must be re-sent; that is in the V2.0 notice below.

### 1.2 Motion Control Service Interface V2.0 notice - the 1-second hold (load-bearing)

- Source: https://support.unitree.com/home/en/developer/Motion_Services_Interface_V2.0 (read via r.jina.ai mirror).
- Applies to "Go2 Edu models with software version >= V1.1.6", released May 12, 2025. The RobotStateClient page adds that the motion service name changed from "sport_mode" to "mcf" at 1.1.6.
- Quoted: "the latest Move command will be maintained for 1 second".
- Quoted: "when using this interface, apply filtering before sending; when not using Move, send Move(0,0,0) or StopMove()".
- Same ranges as 1.1 ("vx: Range [-2.5~3.8] (m/s); vy: Range [-1.0~1.0] (m/s); vyaw: Range [-4~4] (rad/s)"), timeout example 10.0 s.
- Community confirmation of the hold semantics (older firmware, WebRTC path): go2_ros2_sdk discussion #63, https://github.com/abizovnuralem/go2_ros2_sdk/discussions/63 - "the go2 will still move until kill the running thread"; the fix was sending 1008 with x=y=z=0 and then 1003 (StopMove). The user's loop used `move_time = 2` seconds mimicking Unitree's C++ example at 0.2 m/s.

### 1.3 The Python client: which calls block, and for how long

- `unitree_sdk2py/go2/sport/sport_client.py` (https://github.com/unitreerobotics/unitree_sdk2_python/blob/master/unitree_sdk2py/go2/sport/sport_client.py):
  - `Move`: builds `{"x": vx, "y": vy, "z": vyaw}` and calls `self._CallNoReply(SPORT_API_ID_MOVE, parameter)` - no response is awaited.
  - `Euler`: `self._Call(SPORT_API_ID_EULER, parameter)` - blocking.
  - `StopMove`: `self._Call(SPORT_API_ID_STOPMOVE, parameter)` - blocking.
  - `SPORT_API_ID_MOVE = 1008`, `SPORT_API_ID_EULER = 1007`, `SPORT_API_ID_STOPMOVE = 1003`.
- `unitree_sdk2py/rpc/client_base.py` (https://github.com/unitreerobotics/unitree_sdk2_python/blob/master/unitree_sdk2py/rpc/client_base.py):
  - default `self.__timeout = 1.0` seconds; `SetTimeout(timeout)` sets it.
  - `_Call` -> `future = self.__stub.SendRequest(request, self.__timeout)` then `result = future.GetResult(self.__timeout)` (blocks up to the timeout).
  - `_CallNoReply` -> `self.__stub.Send(request, self.__timeout)` with the header's noreply flag set.
  - request identity: `RequestIdentity(time.monotonic_ns(), apiId)`.
  - No lock or mutex in this file.
- C++ `client_base.hpp` (https://github.com/unitreerobotics/unitree_sdk2/blob/main/include/unitree/robot/client/client_base.hpp): `const int64_t ROBOT_CLIENT_TIMEOUT = 1000000;` with comment "default client timeout. 1s"; `SetTimeout(int64_t)` / `SetTimeout(float)`; no mutex members.
- Licence: unitree_sdk2_python is BSD-3-Clause; pins `cyclonedds == 0.10.2`, Python >= 3.8 (README, https://github.com/unitreerobotics/unitree_sdk2_python). unitree_ros2 is BSD-3-Clause and states "The cyclonedds version of Unitree robot is 0.10.2" (https://github.com/unitreerobotics/unitree_ros2).

### 1.4 Rates in the SDK examples (the only official rate numbers found)

- Low level, `example/go2/go2_stand_example.cpp` (https://github.com/unitreerobotics/unitree_sdk2/blob/main/example/go2/go2_stand_example.cpp): `CreateRecurrentThreadEx("writebasiccmd", UT_CPU_ID_NONE, 2000, &Custom::LowCmdWrite, this)` - a 2000 us period, i.e. 500 Hz LowCmd publishing; CRC32 with polynomial `0x04c11db7` over the LowCmd struct; before starting it loops on `queryMotionStatus()` calling `msc.ReleaseMode()` at 5-second intervals until the motion service is inactive; `msc.SetTimeout(10.0f)`; warning "Make sure the robot is hung up or lying on the ground".
- High level, `example/go2/go2_sport_client.cpp` (https://github.com/unitreerobotics/unitree_sdk2/blob/main/example/go2/go2_sport_client.cpp): `float dt = 0.005;` with the comment (Chinese) "control step 0.001~0.01"; `sport_client.SetTimeout(10.0f)`; `sport_client.Move(0.3, 0, 0.3)`; `BodyHeight` "relative height [-0.18~0.03]".
- Basic services doc (https://support.unitree.com/home/en/developer/Basic_services, via mirror): topics "rt/lowcmd" and "rt/lowstate"; `MotorCmd_` fields mode ("Foc mode (working mode) ->0x01, stop mode (standby mode) ->0x00"), q, dq, tau, kp, kd; "For data CRC verification, it is used for 32crc verification"; a "Protection Mechanism" monitoring current, board temperature, charging temperature, battery voltage, motor current. **Publish rates are not stated anywhere in the official pages fetched** (Basic services, About Go2, G1 DDS services). unitree_ros2 only says the `lf/` prefix "represents low frequency".

### 1.5 Built-in obstacle avoidance and the vendor stop envelope

- Python `ObstaclesAvoidClient` (https://github.com/unitreerobotics/unitree_sdk2_python/blob/master/unitree_sdk2py/go2/obstacles_avoid/obstacles_avoid_client.py): `SwitchSet(on)` api 1001, `SwitchGet()` 1002, `Move(vx, vy, vyaw)` 1003 (mode 0), `UseRemoteCommandFromApi(bool)` 1004, `MoveToAbsolutePosition` (mode 2) and `MoveToIncrementPosition` (mode 1) also on 1003. All Move variants use `_CallNoReply`. go2_ros2_sdk's `command_generator.py` labels 1003 "Obstacle avoidance move command" and publishes sport requests on `SPORT_MODE_TOPIC = "rt/api/sport/request"` with `parameters = {"x": x, "y": y, "z": z}` and **no clamping, filtering, or dead-zone** (https://raw.githubusercontent.com/abizovnuralem/go2_ros2_sdk/master/go2_robot_sdk/go2_robot_sdk/application/utils/command_generator.py).
- SLAM & Navigation service (https://support.unitree.com/home/en/developer/SLAM%20and%20Navigation_service, via mirror): navigation speed "0.2 (m/s) ~ 1.0 (m/s)" for Go2, "0.2 (m/s) ~ 1.5 (m/s)" for Go2_W; obstacle "mode: 1" halts on obstacles, "mode: 0" bypasses; bypass needs "a navigable area with a width of at least 0.8m is required, and obstacles must not be wider than 0.5m"; target "cannot exceed 10 meters"; "obstacles should be no less than 20 cm high" to be seen by the LiDAR; continuous SLAM "should not exceed 30 minutes" for dock-PC thermal reasons; "Hot-plugging is strictly prohibited during radar operation".
- User manual (Go2 User Manual V1.0, https://static.generation-robots.com/media/Go2-User-Manual.pdf, read locally): intelligent avoidance uses the L1 (360 x 90 deg, "the minimum detection distance is as low as 0.05m") and "only support forward obstacle avoidance"; remote: "X (Click) Avoidance on (Default)", "Y (Long Press for 3s) Avoidance off", "L2 (Long Press) + B (Click) Damping Mode (soft emergency stop)"; keep "a safe distance of at least 2 meters from obstacles, complex ground, crowds, water"; max speed "3.5m/s on flat terrain. (Maximum speed 2.5m/s for AIR version)", "5m/s (measured in the laboratory)"; side-follow 1.5 m/s slow, 3.0 m/s fast.
- Product pages: unitree.com/go2 lists AIR "0 ~ 2.5m/s", PRO "0 ~ 3.5m/s", X & EDU "0 ~ 3.7m/s (MAX ~ 5m/s)", LiDAR "360 x 96 hemispherical" with "minimum detection distance as low as 0.05m", EDU battery "15000mAh", "About 2-4h". The developer "About Go2" page (https://support.unitree.com/home/en/developer/about_Go2) adds expansion compute "Orin Nano 8GB" (40 TOPS) or "Orin NX 16GB" (100 TOPS), L2 LiDAR "21600 times per second", joint torque "About 45N.m", step height "Approximately 16cm", slope "40 deg".

### 1.6 Mode switching costs (sport mode <-> low level)

- MYBOTSHOP forum, "[Unitree Go2] mode switch", https://forum.mybotshop.de/t/unitree-go2-mode-switch/1856: "Calling ReleaseMode() causes all joint torques to drop momentarily before my low-level controller takes over, so the legs go slack and the robot risks falling"; "calling SelectMode("normal") within ~10s of ReleaseMode() always returns error code 7002". Whether a bumpless handoff exists is unanswered in the thread.
- ric.engineering, https://ric.engineering/posts/Unitree-Sportmode/: "Sport Mode runs directly on the MCU, and the ROS topics for low-level control and sport mode are inserted straight into the DDS"; "Simply publishing low-level commands without disabling Sport Mode would result in loud noises and unpredictable behavior, potentially harming the robot"; scripts use `SetTimeout(5.0)` and 1 s sleeps; after `ReleaseMode` "the motors are no longer actively actuated".
- umi-on-legs setup doc, https://github.com/real-stanford/umi-on-legs/blob/main/real-wbc/docs/codebase_setup.md: "If you call Go2's low-level motor API, it will conflict with the internal high-level commands and shake heavily"; disable with `~/unitree_sdk2/build/disable_sports_mode_go2 eth0`; joystick "L1: Emergency stop".
- RobotStateClient (https://support.unitree.com/home/en/developer/RobotStateClient, via mirror): services "sport_mode", "mcf", "basic_service", "obstacles_avoidance", "unitree_lidar", "webrtc_bridge", "vui_service", ...; `ServiceSwitch(name, 1|0)`; errors 5201 "Service switch execution error", 5202 "The service is protected and cannot be turned on or off".

---

## Part 2 - Concurrency safety of unitree_sdk2py and the DDS layer

### 2.1 What is locked and what is not

- `rpc/request_future.py`: `RequestFutureQueue` is a dict (`self.__data = {}`) guarded by `self.__lock = Lock()` for Set/Get/Remove. (https://github.com/unitreerobotics/unitree_sdk2_python/blob/master/unitree_sdk2py/rpc/request_future.py)
- `rpc/client_stub.py`: `SendRequest` creates a `RequestFuture`, registers it under the request id, then `self.__sendChannel.Write(request, timeout)`; `Send` just writes; responses arrive through a receive channel created with queue size 10 and are matched by id in `__ResponseHandler`. No other locks. Each client instance owns its own send/receive channels. (https://github.com/unitreerobotics/unitree_sdk2_python/blob/master/unitree_sdk2py/rpc/client_stub.py)
- `core/channel.py`: `ChannelPublisher.Write` -> `Channel.Write(sample, timeout)`, which first polls `__publication_matched_count` "in 0.1-second intervals until either a subscriber connects or the timeout expires" - i.e. a Move can block for up to the timeout if the sport service is not matched. `ChannelSubscriber.Init(handler, queueLen)`: with `queueLen > 0` a daemon `Thread(name='ch_reader')` drains a queue; with `queueLen == 0` the `__OnDataAvailable` listener "invokes the handler directly, bypassing the queue". `ChannelFactory` initialisation is under a class lock (`with self.__class__.__init_lock`); `ChannelFactoryInitialize(id=0, networkInterface=None)` creates one Domain/DomainParticipant per process. (https://github.com/unitreerobotics/unitree_sdk2_python/blob/master/unitree_sdk2py/core/channel.py)
- Request ids are `time.monotonic_ns()`; two threads issuing requests in the same nanosecond would collide in the future table - improbable but not impossible on a fast host.

### 2.2 The DDS core and the listener-thread hazard

- Cyclone DDS maintainer (eboasson) in eclipse-cyclonedds/cyclonedds#1913: "everything is thread-safe (that includes creating/deleting domains and entities, reading/writing on the same or different entities, waiting for data or events, attaching/detaching entries from waitsets, messing around with changeable QoS settings and listeners, ...)", the exception being topic filters. (https://github.com/eclipse-cyclonedds/cyclonedds/issues/1913)
- cyclonedds-python maintainer (thijsmie) in eclipse-cyclonedds/cyclonedds-python#7: "listeners are called synchronously with a write on local delivery and protected by some mutexes this will deadlock" when a write inside `on_data_available` triggers another callback on the same entity; "It is not disallowed to call writers in reader callbacks if those don't trigger another callback on the same entity"; alternatives are query/reply topics or `async for message in reader.take_aiter()`. (https://github.com/eclipse-cyclonedds/cyclonedds-python/issues/7)
- Consequence for `unitree_sdk2py`: a `LowState` / `SportModeState` subscriber created with `queueLen = 0` runs the user handler inside the Cyclone listener thread; calling `SportClient.Move` (a DDS write) from there is the pattern the maintainer warns about, and any blocking `_Call` (Euler/StopMove, up to 1 s) from there stalls DDS delivery for the whole process.
- Jetson note: unitree_sdk2_python#53 ("Problems with cyclonedds while using NVIDIA Jetson", https://github.com/unitreerobotics/unitree_sdk2_python/issues/53) reports "Could not locate cyclonedds. Try to set CYCLONEDDS_HOME or CMAKE_PREFIX_PATH" on aarch64, unresolved in the thread.

### 2.3 Transport-level exclusivity and authentication

- WebRTC: legion1581/go2_webrtc_connect (MIT; firmware "1.0.19 - 1.0.25, 1.1.1 - 1.1.14, 1.1.15+") raises `RobotBusyError - robot rejected - another WebRTC client is connected` (https://github.com/legion1581/go2_webrtc_connect). tfoldi/go2-webrtc (BSD-2): connecting without a security token "limits you to a single active connection at any time" (https://github.com/tfoldi/go2-webrtc).
- DDS: boschko.ca "From DDS Packets to Robot Shells" (https://boschko.ca/unitree-go2-rce/): "DDS has no built-in authentication in the default configuration"; "any device on the network can join domain 0 and participate in DDS communication without credentials"; on V1.1.7 "67 active topics" were discoverable, on V1.1.11 only 4; CVE-2026-27509 = unauthenticated DDS RCE via `rt/api/programming_actuator/request` with `api_id=1002` (V1.1.7-V1.1.11 EDU); internal interface `192.168.123.161` (eth0), external `192.168.1.7` (wlan0). Anything that can reach domain 0 can publish `rt/api/sport/request` - the same topic go2_ros2_sdk uses for 1008.
- go2_ros2_sdk README: firmware "1.1.15 and newer" moved WebRTC to per-device AES-128 keys.

---

## Part 3 - Measured latencies (none is a Go2 sport-mode step response)

| Path | Number | Source |
|---|---|---|
| Unitree G1, policy -> LCM bridge -> low-level | "Command transmission introduces a latency of 18-30ms"; policy "50Hz", low-level "500Hz" | arXiv 2510.14952, https://arxiv.org/html/2510.14952 |
| Go2 (Jetson Orin NX), Cyclone DDS + LCM | "stable control frequency at 50 Hz", motors "1000 Hz", computation must fit "within each 20ms cycle" (no measured delay) | arXiv 2505.09979, https://arxiv.org/html/2505.09979 |
| Go2-W (Orin NX), Unitree SDK over Ethernet | policies at 50 Hz; e-stop "halts the robot by setting the velocity command to zero"; 2.8 km course, six runs ~1 h 5 min; 60 C plateau vs 84 C shutdown with manufacturer control | arXiv 2606.21387, https://arxiv.org/html/2606.21387 |
| Go2 Pro, WebRTC bridge (gesture teleop) | "mean network latency of 33.9 ms", "total system reaction time of 1.75 s", "0.3-second debounce window" on STOP/FOLLOW | Springer chapter 10.1007/978-3-032-29254-4_11 (abstract), https://link.springer.com/chapter/10.1007/978-3-032-29254-4_11 |
| Go1 Air, app-protocol bridge to ArduPilot | "average latency ... over Wi-Fi is 206.7 ms, and its standard deviation is below 53 ms"; Ethernet "mean latency down to 78.3 ms" | Designs 2025, DOI 10.3390/designs9020050 (abstract read via api.semanticscholar.org; mdpi.com returned 403), https://www.mdpi.com/2411-9660/9/2/50 |
| Jetson Orin Nano, one DDS hop, Unitree 4D L1 frame (20 Hz, 2160 pts) | Fast DDS "0.685" ms mean (1 writer -> 1 reader), "1.593" ms (1 -> 10 readers); Zenoh 0.839 ms; camera 640x480@30: Fast DDS 3.40 ms; proposed SIM 0.226 ms (p99 0.382), 0.158 ms with SCHED_FIFO 99; Cyclone DDS not tested | arXiv 2510.11448, https://arxiv.org/html/2510.11448 |
| ROS 2 over DDS, generic | "ROS2 can lead to 50 % latency overhead compared to using low-level DDS communications"; RELIABLE QoS "latency overhead of up to 15 %"; Raspberry Pi 4 overloaded above 50 Hz at 13-17 nodes; CycloneDDS 0.6.0 / Foxy | Kronauer et al., arXiv 2101.02074 (PDF read locally), https://arxiv.org/abs/2101.02074 |
| go2_ros2_sdk over WebRTC (Wi-Fi) | LiDAR "now updates at 7 Hz" (was ~2 Hz); "joint states still arrive at 1 Hz ... expected with the new firmware (v1.1.7)"; driver loop `await asyncio.sleep(0.1)` (~10 Hz); no watchdog visible in `go2_driver_node.py` | https://github.com/abizovnuralem/go2_ros2_sdk |
| Go2 "Safety Index Adaptation" | high-level body-frame velocity commands integrated at "dt=1/30 Hz" | arXiv 2409.09882 |

Reading of the table: the transport itself (DDS on the Orin, Ethernet to the robot MCU) is sub-millisecond to a few ms; measured "command transmission" through a bridge on a Unitree platform is 18-30 ms; anything over Wi-Fi/WebRTC is tens of ms network plus the app pipeline; and the robot-side sport controller's own response time to a new Move is unmeasured in the public record. The "1 second hold" is therefore the only firm timing spec on the sport interface.

QRE (docs.quadruped.de) controller manual, https://www.docs.quadruped.de/projects/go2/html/controller.html: "Loss of connection or (laggy connection) may lead to the robot moving and/or not stopping immediately." - the vendor-adjacent statement of the same hazard.

---

## Part 4 - How learned outputs are shielded on quadrupeds

### 4.1 REASAN - learned velocity shield on Go2 + Mid-360 + AGX Orin 64 GB (Parcel's exact stack)

- arXiv 2512.09537, https://arxiv.org/html/2512.09537 (Dec 2025).
- Hardware: "Unitree Go2 robot equipped with a Livox Mid-360 LiDAR and a Jetson AGX Orin (64 GB)"; networks exported "from PyTorch to ONNX", run with ONNX Runtime, "each module wrapped as a ROS2 node"; "all modules maintain stable real-time performance at 50 Hz".
- Shield: input is 180 equidistant rays over 360 deg from the downsampled LiDAR (2 deg spherical grid); it "transforms an arbitrary velocity command into a safe one for locomotion, enabling reactive obstacle avoidance", outputting (vx, vy, wz); trained by PPO after freezing the locomotion policy (sequential RL), 20 s episodes.
- Compute: exteroceptive estimator "1.3 +/- 0.1 ms" (RTX 5090, batch 1; Orin figure not given).
- Sim: ScaSparse SR 91.1 +/- 1.9 %, ScaDense 79.1 +/- 4.4 %, Maze 95.2 +/- 2.9 %, DyMaze 68.2 +/- 2.3 % (termination 22.0 %, timeout 9.8 %).
- Real: "270s (Static), 180s (Dynamic), 190s (DeadEnd), 180s (Herding)" with zero collisions across 40 traversals (10 per scenario); multi-robot collision-free "93 s". Observed behaviour: "the safety-shield policy frequently outputs a lower speed than the navigation input due to nearby obstacles".

### 4.2 Point-cloud CBFs on Go2 (Orin NX) - "Sailing Through Point Clouds"

- arXiv 2403.18206, https://arxiv.org/html/2403.18206.
- "Both robots obtain the point clouds using a 16-channel 3D LiDAR at 10 Hz", "each scan has 1024 points"; "All computations for real-world experiments are performed onboard using an NVIDIA Jetson Orin NX for the Unitree Go2 and a Jetson Orin AGX for the Unitree B1".
- Filtered input: the robot's "onboard proprietary controller" tracks "commanded linear and angular velocity"; dynamics modelled as x-dot = u = [v^T omega]^T in R^4.
- Cost: mean CBF computation 0.78 ms (n_needle = 100) plus 0.37 ms local planner on the Orin NX; layers updated at 10 Hz (LiDAR), 2 Hz (planner), once (init).

### 4.3 Safety-index QP over Go2 velocity commands at 30 Hz

- arXiv 2409.09882, https://arxiv.org/html/2409.09882.
- "Unitree Go2 quadruped" driven by "high-level velocity commands in the body frame"; v_cmd = v_meas + a_cmd * dt with "dt=1/30 Hz"; safety index phi = dmin^2 - d^2 - 2 k d d-dot with dmin = 1 m; a QP modifies the velocity command with minimum deviation from nominal LQR.
- Results: non-adapted 80 % (4/5), 60 % (3/5), 80 % (4/5) -> adapted 100 % (10/10, 6/6, 7/7); adaptation costs "approximately 1.48 % of the computation time for the full synthesis".

### 4.4 UEREBot - CBF shield on Go2 + Mid-360 + D435 + Orin NX against fast dynamic obstacles

- arXiv 2602.07363, https://arxiv.org/html/2602.07363 (Feb 2026).
- "body-frame velocity command interface" u = [vx vy omega]; reference path "10-20 Hz", threat predictions "50 Hz"; CBF shield with static and dynamic feasibility barriers, r_eff = r_obstacle + r_robot + delta; trained with obstacle speeds "U(0.5, 4.0) m/s".
- Real robot, 200 trials: goal completion 75 %, avoidance success 70 %, task success 64 %.

### 4.5 SEA-Nav - differentiable LSE-CBF shield inside the policy (Go2)

- arXiv 2603.09460, https://arxiv.org/html/2603.09460 (Mar 2026).
- Go2 with onboard L1 (~1000 pts) or RPLIDAR A2 (~2000 pts) reduced to a 41-ray scan over [-2pi/3, 2pi/3], 0.1-3.0 m; 10 Hz exteroception, 50 Hz proprioception; actor outputs nominal velocity plus an adaptive gain alpha, the shield projects to h-dot >= -alpha h.
- Sim (hard): SR 90.00 +/- 1.63 %, collision 5.00 +/- 0.82 %, timeout 5.00 +/- 0.82 %. Real cluttered room row as extracted: success 100, collisions 10, speed 1.6 m/s (units of the collisions entry were not recoverable from the extract - treat with caution).

### 4.6 Value-function shields on Go1 (ABS, One Filter)

- ABS, arXiv 2401.17583, https://arxiv.org/html/2401.17583: Go1 + "Jetson Orin NX" + ZED Mini; reach-avoid value network switches: "If V >= Vthreshold, the recovery policy is activated", Vthreshold = -0.05; depth -> 11-ray prediction; peak "3.1 m/s" real, sim SR 79.1 +/- 4.4 %, collision 5.7 +/- 2.9 %.
- One Filter to Deploy Them All, arXiv 2412.09989, https://arxiv.org/html/2412.09989 (CC BY 4.0): Go1 + RPLiDAR A2, 100 rays clipped to [0.2, 10] m; observation-conditioned reachability value overrides the twist (v, w) of any nominal controller; hardware, 10 trials per row: normal floor ABS-Agile+OCR 10/0/0 (success/collision/timeout), PS+MPC+OCR 10/0/0; slippery floor 8/1/1 and 9/1/0; worst NVE+MPC+OCR 7/3/0.

### 4.7 Shields below the velocity layer (contact / joint level) and training-time shields

- Shield-Loco, arXiv 2606.07193, https://arxiv.org/html/2606.07193: Go2; filters foot-contact targets of a contact-conditioned RL policy with sampled full-physics rollouts (K = 512, N = 3, H = 5 ~ 150 physics steps) at "a planning frequency of 3 Hz" on an RTX 3090 (offboard); H = 6 ~200 ms, H = 8 ~400 ms per cycle; violations roughly 300+ nominal -> ~30 filtered; "robot remains stable even when the asynchronous optimizer is slow".
- CBF-RL, arXiv 2510.14959, https://arxiv.org/abs/2510.14959: G1 humanoid; "internalizes the safety constraints in the learned policy" so deployment needs no online filter.
- RL-Locomotion-with-Safety-Layer, https://github.com/ansh1113/RL-Locomotion-with-Safety-Layer (MIT, PyBullet only): CBF layer over PPO joint actions, "Total safety filter latency: 3.2 ms (312 Hz)", "0 falls", "99 %" of unsafe actions rejected, "90 %" speed retained; "Real robot deployment" is future work.

Pattern across 4.1-4.6: every hardware-validated shield on Go1/Go2 sits between the policy and the vendor velocity interface, runs at 10-50 Hz, consumes a ray/scan reduction of the LiDAR (41-180 rays), and costs well under one control tick on an Orin-class board. None of them touches the sport controller's gait.

---

## Part 5 - What this means for Parcel's Model A / Model B

Model A = 10 Hz act-token loop + 0.5-2 Hz language/plan lane on the AGX Orin; Model B = owner voice -> steering injection; receipts -> narration for the hosted Realtime voice. The gateway (`gateway/`, `parcel_robot/control/motion_gateway.py`, `unitree_sport.py`) is where these facts land.

1. **The 10 Hz act-token tick maps 1:1 onto `Move` and sits comfortably inside the 1 s hold - but the hold is also the failure mode.** Ten ticks per second means a single missed tick is invisible to the firmware, and a stalled Model A (or a stalled Python thread) keeps the dog moving for up to 1 s at the last velocity. The gateway must run its own watchdog well under 1 s (200-300 ms is 2-3 missed ticks) and on expiry send `Move(0,0,0)` followed by `StopMove()` - the exact sequence Unitree and the community converge on. This watchdog is a gateway property, not a Model A property, and it should be tested with a frozen Model A in the sim loop.
2. **Filter before you send.** Unitree's own guidance ("apply filtering before sending") plus go2_ros2_sdk shipping with no clamping means the act-token decoder must own slew-rate limiting and clamping: hard limits vx [-2.5, 3.8], vy [-1, 1], vyaw [-4, 4]; a companion envelope far below that (the vendor's own navigation service uses 0.2-1.0 m/s). The safety-index paper's form (command = measured + a * dt at 30 Hz) is a ready-made shape for a slew filter.
3. **Put the shield in the gateway, at the velocity layer, at the 10 Hz tick.** REASAN shows a learned velocity shield at 50 Hz on Parcel's exact hardware; point-cloud CBFs cost 0.78 ms on an Orin NX. Mid-360 -> 180-ray polar reduction -> CBF-QP or learned shield -> clamped Move is a sub-millisecond addition to each 10 Hz tick and needs no change to Model A's action codec (act tokens stay nominal; the shield may only reduce). The shield should also be the thing that turns "person within X m" into a speed cap, since the vendor's built-in avoidance is forward-only and its stop mode belongs to the nav service, not to the sport API.
4. **One writer, one thread.** `_CallNoReply` has no lock; `Channel.Write` can block up to the timeout; `Euler` and `StopMove` block up to 1 s by default. Serialise every sport call through a single gateway thread with a command queue; Model B's steering injections must enter Model A's plan/act lane (which they already do via submit / suspend / resume / amend) and never open a second `SportClient`. The blocking calls (StopMove, Euler, BodyHeight, mode switches) belong on a separate low-priority worker with `SetTimeout` set explicitly, not on the 10 Hz thread.
5. **Never write from a DDS callback.** State subscribers (`rt/lf/lowstate`, `lf/sportmodestate`, LiDAR) must be created with `queueLen > 0` (dedicated `ch_reader` thread) or read from the gateway's own loop; calling `Move` inside a `queueLen = 0` handler is the cyclonedds-python deadlock pattern.
6. **Expression lane budget.** Body-language tokens that resolve to `Euler` (roll/pitch +/-0.75 rad, yaw +/-0.6 rad) or `BodyHeight` ([-0.18, 0.03] m) are blocking RPCs; at most one per ~1 s hold window, issued from the worker in item 4, and pre-empted by the shield when speed is non-zero (Euler while walking changes the gait envelope). `ContinuousGait` is the vendor's way to keep the dog "alive" at zero velocity - useful for the idle-liveness cues Model A emits.
7. **What the simulator must model** (headless-city / MuJoCo-city rigs): the 1 s command hold; a 20-50 ms command-to-controller delay (18-30 ms measured on a Unitree bridge, plus DDS); 50 Hz state feedback (`lf/` topics; WebRTC drivers see joint states at 1 Hz - never use that path for control); and the shield's speed reduction. Model A should be trained with randomised 0-100 ms command delay in addition to the 0-10 s plan-lane delay already borrowed from TIC-VLA.
8. **Mode discipline.** Keep Model A on the sport (mcf) velocity API for the current milestone: the sport -> low-level handoff costs a torque dropout, a ~10 s cooldown (error 7002), and Unitree's own examples run the low-level loop at 500 Hz with CRC - a different engineering problem (a real-time thread, not a Python 10 Hz loop). A joint-space Model A is a later milestone with its own gate.
9. **Network hygiene is a safety property.** DDS domain 0 on the robot is unauthenticated (CVE-2026-27509); the gateway must bind `ChannelFactoryInitialize(0, "eth0")` on the robot's 192.168.123.x segment only, and the Starlink / Wi-Fi side (hosted voice, Model B) must never bridge into that domain. WebRTC is single-client - do not plan on a phone app and the gateway sharing it.
10. **Evidence gaps to close on hardware when a Go2 is on hand** (none of these exist in the public record): step response of `Move` (command -> measured body velocity) at 10 Hz; jitter of `_CallNoReply` from Python on the AGX Orin under Model A load; actual `lf/sportmodestate` rate; behaviour of the 1 s hold when `ObstaclesAvoidClient.UseRemoteCommandFromApi(True)` is active; whether error 4201 fires on `Euler` during motion.

---

## Sources (all fetched 2026-08-29)

Official / SDK
- https://support.unitree.com/home/en/developer/sports_services (via r.jina.ai)
- https://support.unitree.com/home/en/developer/Motion_Services_Interface_V2.0 (via r.jina.ai)
- https://support.unitree.com/home/en/developer/Basic_services (via r.jina.ai)
- https://support.unitree.com/home/en/developer/SLAM%20and%20Navigation_service (via r.jina.ai)
- https://support.unitree.com/home/en/developer/RobotStateClient (via r.jina.ai)
- https://support.unitree.com/home/en/developer/about_Go2 (via r.jina.ai)
- https://github.com/unitreerobotics/unitree_sdk2_python (README, BSD-3-Clause) and raw files: go2/sport/sport_client.py, rpc/client_base.py, rpc/client_stub.py, rpc/request_future.py, core/channel.py, go2/obstacles_avoid/obstacles_avoid_client.py
- https://github.com/unitreerobotics/unitree_sdk2: include/unitree/robot/client/client_base.hpp, include/unitree/robot/go2/sport/sport_client.hpp, example/go2/go2_sport_client.cpp, example/go2/go2_stand_example.cpp
- https://github.com/unitreerobotics/unitree_ros2 (BSD-3-Clause)
- https://github.com/unitreerobotics/unitree_sdk2_python/issues/53
- https://static.generation-robots.com/media/Go2-User-Manual.pdf (read locally with pdftotext)
- https://www.unitree.com/go2/

Community drivers, forums, security
- https://github.com/abizovnuralem/go2_ros2_sdk (BSD-2) + raw application/utils/command_generator.py and presentation/go2_driver_node.py
- https://github.com/abizovnuralem/go2_ros2_sdk/discussions/63
- https://github.com/legion1581/go2_python_sdk (clients/sport_client.py)
- https://github.com/legion1581/go2_webrtc_connect (MIT)
- https://github.com/tfoldi/go2-webrtc (BSD-2)
- https://github.com/Rooholla-KhorramBakht/go2Py (MIT; no rates published)
- https://forum.mybotshop.de/t/unitree-go2-mode-switch/1856
- https://forum.mybotshop.de/t/unitree-go2-low-level-control/950 (no numbers)
- https://ric.engineering/posts/Unitree-Sportmode/
- https://github.com/real-stanford/umi-on-legs/blob/main/real-wbc/docs/codebase_setup.md
- https://github.com/Glowing-Torch/Deploy-an-RL-policy-on-the-Unitree-Go2-robot (MIT; "turn down the sport mode service" warning only)
- https://www.docs.quadruped.de/projects/go2/html/controller.html
- https://unitree-go2-robot.github.io/humble/go2cli/index.html (obstacle avoidance start/stop/get; no numbers)
- https://discourse.openrobotics.org/t/new-implementation-for-unitree-go-2-in-ros-2-humble/38465 (no numbers)
- https://boschko.ca/unitree-go2-rce/
- https://github.com/eclipse-cyclonedds/cyclonedds/issues/1913
- https://github.com/eclipse-cyclonedds/cyclonedds-python/issues/7

Latency measurements
- https://arxiv.org/html/2510.14952 (G1, 18-30 ms)
- https://arxiv.org/html/2505.09979 (Go2 Orin NX, 50 Hz / 1000 Hz)
- https://arxiv.org/html/2606.21387 (Go2-W)
- https://link.springer.com/chapter/10.1007/978-3-032-29254-4_11 (Go2 Pro WebRTC 33.9 ms)
- https://www.mdpi.com/2411-9660/9/2/50 (Go1 Air 206.7 / 78.3 ms; abstract via api.semanticscholar.org)
- https://arxiv.org/html/2510.11448 (Jetson Orin Nano DDS hop)
- https://arxiv.org/abs/2101.02074 (ROS 2 / DDS overhead; PDF read locally)
- https://arxiv.org/html/2407.03091 (mesh Wi-Fi comparison; no small-message numbers in text)

Shields
- https://arxiv.org/html/2512.09537 (REASAN)
- https://arxiv.org/html/2403.18206 (Sailing Through Point Clouds)
- https://arxiv.org/html/2409.09882 (Safety Index Adaptation)
- https://arxiv.org/html/2602.07363 (UEREBot)
- https://arxiv.org/html/2603.09460 (SEA-Nav)
- https://arxiv.org/html/2401.17583 (ABS)
- https://arxiv.org/html/2412.09989 (One Filter to Deploy Them All)
- https://arxiv.org/html/2606.07193 (Shield-Loco)
- https://arxiv.org/abs/2510.14959 (CBF-RL)
- https://github.com/ansh1113/RL-Locomotion-with-Safety-Layer

Not usable / not found
- Unitree "High_motion_control" and "AI_motion_service" pages rendered only their navigation through the mirror; their bodies were not read.
- No official statement of `rt/lowstate` / `rt/lf/lowstate` / `sportmodestate` publish rates was found on any fetched Unitree page.
- No paper or forum post gives a measured Go2 sport-mode command-to-motion step response.
