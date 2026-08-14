# Sol 5.6 recommendation — physical-session readiness (received 2026-08-13, verbatim)

Yes—Parcel is a good foundation for mounting sensors/compute on a Unitree and beginning supervised SLAM and perception development. It is not yet ready for autonomous city walking.

The distinction is:

- **Ready:** stationary sensor bring-up, data recording, SLAM experiments, visualization, shadow navigation, manual/remote-controlled mapping, and fenced low-speed testing.
- **Not ready:** unsupervised following, street navigation, stairs, or letting voice commands directly move the robot in public.

## What you can test in simulation

Simulation can effectively test:

- Camera/LiDAR message contracts and coordinate frames.
- Point-cloud filtering and occupancy mapping.
- SLAM interfaces and `map → odom → base_link → sensor` transforms.
- Semantic detection of people, sidewalks, doors, lampposts, and obstacles.
- Owner-tracking state machines, including LOST and AMBIGUOUS states.
- Navigation with delayed, dropped, reordered, or noisy measurements.
- Planner behavior during localization loss or map jumps.
- Collision avoidance and recovery logic.
- CPU/GPU latency and model scheduling.

Isaac Sim can generate configurable RTX LiDAR data and camera imagery, making it more suitable than Parcel's current MuJoCo renderer for perception development. [Isaac Sim RTX LiDAR](https://docs.isaacsim.omniverse.nvidia.com/latest/sensors/isaacsim_sensors_rtx_lidar.html)

But simulation cannot prove real sensor performance under:

- sunlight, darkness, rain, glass, reflective surfaces, or LiDAR multipath;
- camera motion blur, rolling shutter, vibration, lens contamination;
- clock drift and camera–LiDAR synchronization errors;
- payload vibration, thermal throttling, network loss, or cable problems;
- real pedestrian appearance, occlusion, and owner Re-ID.

So simulation validates algorithms and integration—not the physical sensing system itself.

## The best development ladder

I recommend using the exact same perception interfaces across these five modes:

| Stage | Sensors | Robot motion | What it proves |
|---|---|---|---|
| 1. Synthetic simulation | Simulated camera/LiDAR | Simulated | Interfaces, algorithms, fault injection |
| 2. Real-data replay | Recorded camera/LiDAR/IMU bags | None | Algorithms against real sensor characteristics |
| 3. Hardware-in-loop | Real mounted sensors | Robot stationary | Drivers, timestamps, calibration, throughput |
| 4. Shadow mapping | Real sensors | Manual remote control | SLAM and planning without autonomous authority |
| 5. Fenced autonomy | Real sensors | Very low-speed autonomous | Closed-loop physical navigation |

Real-data replay is particularly valuable. Record raw camera, LiDAR, IMU, Sport state, and timestamps using `rosbag2`, then replay them through unchanged Parcel perception and navigation code. [rosbag2](https://github.com/ros2/rosbag2)

Unitree's official ROS 2 stack documents LiDAR point clouds on `utlidar/cloud`, Sport state, low-level state, wireless-controller state, and bag recording. It recommends Ubuntu 22.04 with ROS 2 Humble. [Unitree ROS 2](https://github.com/unitreerobotics/unitree_ros2) Unitree also publishes an [L2 LiDAR SDK](https://github.com/unitreerobotics/unilidar_sdk2) and a [Point-LIO integration](https://github.com/unitreerobotics/point_lio_unilidar), which are reasonable initial SLAM candidates.

## What Parcel needs before the first physical session

For sensor-only work, very little motion code is required. Build these pieces first:

1. A physical sensor envelope containing:

   - source and host timestamps;
   - sequence and boot epoch;
   - frame ID;
   - calibration/extrinsics digest;
   - camera frame or raw point cloud;
   - freshness and health state.

2. A proper TF tree:

   ```text
   map → odom → base_link → lidar
                         └→ camera
   ```

3. A physical pose provider replacing `TruthPoseProvider`.

4. Raw recording and deterministic replay.

5. A strict runtime mode such as:

   ```text
   SENSOR_ONLY
   SHADOW_NAVIGATION
   MANUAL_TELEOP
   AUTONOMOUS_ARMED
   ```

   `SENSOR_ONLY` and `SHADOW_NAVIGATION` must be structurally unable to send `Move`.

6. Calibration tools for:

   - camera intrinsics;
   - LiDAR-to-base extrinsics;
   - camera-to-LiDAR extrinsics;
   - timestamp offset and drift;
   - mounted payload location and orientation.

## Before autonomous movement

Close the current physical factory/provenance gap, add the isolated Unitree gateway, and test stop behavior under process death, network loss, stale state, and competing writers. Use the Unitree handheld controller as the independent operator stop.

For initial mapping, I would deliberately avoid autonomy:

1. Mount the sensors securely.
2. Start the robot sitting or standing stationary.
3. Validate every topic and frame.
4. Record several stationary datasets.
5. Carry or remotely drive the robot through an indoor area.
6. run SLAM offline;
7. compare repeated maps and loop closures;
8. run Parcel's planner in shadow mode;
9. only then allow bounded low-speed commands in a fenced area.

So yes: you are ready to turn Parcel into a physical SLAM and perception prototype. The correct next milestone is not "autonomous dog"; it is "the same perception pipeline consumes simulated data, recorded real data, and live mounted sensors—and produces timestamped, calibrated, uncertainty-aware outputs without owning motion."
